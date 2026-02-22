"""
title: canvas_course_provisioner
description: Provisions a Canvas course assistant in Open WebUI by running the orchestrator, creating a Knowledge Base from produced chunks, and creating a model bound to that KB.
requirements:requests,pydantic,open-canvas @ git+https://github.com/Pris-mo/Open_Canvas.git
"""


from __future__ import annotations

import shutil
from typing import List, Union, Generator, Iterator, Dict, Any, Optional
import os
import json
import logging
import re
from urllib.parse import urlparse
import sys
import time
import random

import requests
from pydantic import BaseModel, Field

import subprocess
from pathlib import Path

from concurrent.futures import ThreadPoolExecutor, as_completed

# better: 8-char uuid
import uuid

# --- Orchestrator defaults (hardcoded to avoid extra valves) ---
PIPELINE_ROOT = Path(__file__).resolve().parent
ORCH_RUNS_ROOT_DEFAULT = str(PIPELINE_ROOT / "runs")  # e.g. /app/pipelines/Open_Canvas_Pipeline/runs
ORCH_DEPTH_LIMIT_DEFAULT = 10
# How many files to upload in parallel to Open WebUI
UPLOAD_WORKERS_DEFAULT = int(os.getenv("UPLOAD_WORKERS", "6"))
FILE_PROCESS_DEFAULT = True
FILE_PROCESS_IN_BACKGROUND_DEFAULT = True
HTTP_READ_TIMEOUT_SECS = 180     
HTTP_UPLOAD_READ_TIMEOUT_SECS = 300  
HTTP_CONNECT_TIMEOUT_SECS = 10


logger = logging.getLogger("canvas_course_provisioner")
logging.basicConfig(level=logging.INFO)


class Valves(BaseModel):
    OPENWEBUI_BASE_URL: str = Field(default="http://open-webui:8080")
    OPENWEBUI_API_KEY: str = Field(default="")

    CANVAS_API_KEY: str = Field(default="", description="Canvas API token")
    OPENAI_API_KEY: str = Field(default="", description="Optional. Enables LLM fallback during conversion/chunking.")

    BASE_MODEL_ID: str = Field(default="gpt-5")

    INCLUDE_METADATA: bool = Field(default=True, description="Include metadata in markdown")

    HTTP_TIMEOUT_SECS: int = Field(default=30)

    # NEW: control how much orchestrator output you see
    DEBUG: bool = Field(
        default=False,
        description=(
            "If true, all output will be streamed to chat."
        ),
    )


Valves.model_rebuild()


def _parse_course_url(course_url: str) -> tuple[str, str]:
    """
    Accepts:
      https://learn.canvas.net/courses/3376
      https://learn.canvas.net/courses/3376/
      https://learn.canvas.net/courses/3376?foo=bar

    Returns:
      (base_url, course_id)
        base_url: https://learn.canvas.net
        course_id: 3376
    """
    u = urlparse(course_url.strip())
    if not u.scheme or not u.netloc:
        raise ValueError("URL must include scheme and host (e.g. https://learn.canvas.net/courses/3376)")

    # base URL = scheme + host
    base_url = f"{u.scheme}://{u.netloc}"

    # extract course id from path
    # expected path like /courses/<id>
    m = re.search(r"/courses/([^/]+)", u.path)
    if not m:
        raise ValueError("Expected path like /courses/<course_id>")

    course_id = m.group(1).strip()
    if not course_id:
        raise ValueError("course_id was empty")

    return base_url, course_id


def _slug(s: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
    return s[:60]


class Pipeline:
    Valves = Valves

    def __init__(self):
        # This is what makes it show up as a "model" in Open WebUI
        self.name = "Canvas Course Provisioner"

        # Load defaults from env, but primarily use valves in the UI
        self.valves = self.Valves(
            OPENWEBUI_BASE_URL=os.getenv("OPENWEBUI_BASE_URL", "http://host.docker.internal:3000"),
            OPENWEBUI_API_KEY=os.getenv("OPENWEBUI_API_KEY", ""),
            CANVAS_API_KEY=os.getenv("CANVAS_API_KEY", ""),
            OPENAI_API_KEY=os.getenv("OPENAI_API_KEY", ""),
            BASE_MODEL_ID=os.getenv("BASE_MODEL_ID", "gpt-5"),
            INCLUDE_METADATA=os.getenv("INCLUDE_METADATA", "true").lower() in ("1", "true", "yes", "y", "on"),
            # Comma-separated env var support if you want it:
            INCLUDE_CONTENT_TYPES=None,
            HTTP_TIMEOUT_SECS=int(os.getenv("HTTP_TIMEOUT_SECS", "30")),
            DEBUG=os.getenv("DEBUG", "true").lower() in ("1", "true", "yes", "y", "on"),
        )

    async def on_startup(self):
        logger.info("Pipeline startup: canvas_course_provisioner")

    async def on_shutdown(self):
        logger.info("Pipeline shutdown: canvas_course_provisioner")

    # ----------------------------
    # Open WebUI API helpers
    # ----------------------------
    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.valves.OPENWEBUI_API_KEY}",
            "Accept": "application/json",
        }

    def _iter_markdown_files(self, chunks_root: Path) -> List[Path]:
        """Return all .md files under chunks_root recursively, sorted for stability."""
        if not chunks_root.exists():
            return []
        files = [p for p in chunks_root.rglob("*.md") if p.is_file()]
        files.sort()
        return files

    def _safe_upload_name(self, root: Path, path: Path) -> str:
        """
        Turn a file path into a stable filename for OpenWebUI uploads.
        Preserves subfolder structure by encoding it into the filename.
        """
        rel = path.relative_to(root).as_posix()
        # Avoid weird chars; keep it readable
        rel = re.sub(r"[^a-zA-Z0-9/_\.\-]+", "_", rel)
        return rel.replace("/", "__")  # "unit1/chunk_001.md" -> "unit1__chunk_001.md"

    def _with_retries(self, fn, *, attempts: int = 5, base_delay: float = 1.0, max_delay: float = 20.0):
        if attempts < 1:
            raise ValueError("attempts must be >= 1")

        for i in range(attempts):
            try:
                return fn()
            except Exception as e:
                s = str(e).lower()

                transient = any(k in s for k in (
                    "read timed out", "timeout", "502", "503", "504",
                    "connection reset", "temporarily unavailable",
                ))

                # If it's not transient, or we're out of attempts, raise the real exception
                if (not transient) or (i == attempts - 1):
                    raise

                delay = min(max_delay, base_delay * (2 ** i)) + random.random()
                time.sleep(delay)

        # Should be unreachable because the last iteration raises
        raise RuntimeError("Retry loop exited unexpectedly")

    def _upload_and_attach_one(
        self,
        kb_id: str,
        chunks_root: Path,
        md_path: Path,
    ) -> tuple[str, Optional[str], Optional[str]]:
        """
        Returns: (md_path_str, file_id_or_none, error_or_none)
        """
        try:
            def do():
                up = self.upload_markdown_file(chunks_root, md_path)
                file_id = up.get("id") or (up.get("file") or {}).get("id")
                if not file_id:
                    raise RuntimeError(f"Unexpected upload payload: {up}")
                self.add_file_to_knowledge(kb_id, file_id)
                return file_id

            file_id = self._with_retries(do, attempts=5)
            return (str(md_path), file_id, None)

        except Exception as e:
            return (str(md_path), None, str(e))

    def _fetch_canvas_course_name(self, base_url: str, course_id: str) -> Optional[str]:
        """
        Use the Canvas API to look up the course name.

        Returns:
            The course name (or course_code) if available, else None.
        """
        if not self.valves.CANVAS_API_KEY:
            # Already warn in the main flow; keep this quiet to avoid spam.
            return None

        url = f"{base_url.rstrip('/')}/api/v1/courses/{course_id}"
        headers = {
            "Authorization": f"Bearer {self.valves.CANVAS_API_KEY}",
            "Accept": "application/json",
        }

        # Be a bit conservative on timeout
        timeout = max(5, min(self.valves.HTTP_TIMEOUT_SECS, 30))

        try:
            resp = requests.get(url, headers=headers, timeout=timeout)
            resp.raise_for_status()
        except Exception as e:
            logger.warning("Canvas course name lookup failed for %s: %s", url, e)
            return None

        try:
            data = resp.json()
        except Exception as e:
            logger.warning("Canvas course name lookup returned non-JSON for %s: %s", url, e)
            return None

        name = (data.get("name") or data.get("course_code") or "").strip()
        if not name:
            logger.info("Canvas course %s had no usable 'name' or 'course_code' field", course_id)
            return None

        return name

    # ----------------------------
    # Key validation helpers
    # ----------------------------
    def _validate_openwebui_key(self) -> tuple[bool, Optional[str]]:
        """
        Validate that the OpenWebUI API key works for the configured base URL.
        """
        if not self.valves.OPENWEBUI_API_KEY:
            err = (
                "Error: Your OpenWebUI API key is missing or invalid. "
                "Please note that this is a separate key from your OpenAI API key.\n"
                "To create an OpenWebUI API key, follow "
                "[these steps](https://github.com/Pris-mo/Open_Canvas_Pipeline/blob/main/docs/open-webui-api.md)."
            )
            return False, err

        try:
            # Use a lightweight, authenticated endpoint.
            resp = self._http(
                "GET",
                "/api/v1/models",
                timeout=max(5, min(self.valves.HTTP_TIMEOUT_SECS, 30)),
            )
            self._require_ok(resp, "validate_openwebui")
        except Exception as e:
            logger.warning("OpenWebUI API key validation failed: %s", e)
            err = (
                "**Error OpenWebUI:** Your OpenWebUI **API key is invalid**, or, your **OpenWebUI base URL is incorrect** \n"
                "Please note that this is a separate key from your OpenAI API key.\n"
                "To create or verify your OpenWebUI API key, follow "
                "[these steps](https://github.com/Pris-mo/Open_Canvas_Pipeline/blob/main/docs/open-webui-api.md)."
            )
            return False, err

        return True, None

    def _validate_canvas_key(
        self,
        base_url: str,
        course_id: str,
        course_url: str,
    ) -> tuple[bool, Optional[str], Optional[str]]:
        """
        Validate that the Canvas key exists and can read the given course.
        Returns (ok, error_message_or_None, course_name_or_None).
        """
        if not self.valves.CANVAS_API_KEY:
            err = (
                "**Error Canvas:** Your Canvas **API key is invalid or missing**. "
                f"Please ensure that it has access to `{course_url}`.\n"
                "For help provisioning your Canvas API key, please follow "
                "[these steps](https://github.com/Pris-mo/Open_Canvas_Pipeline/blob/main/docs/canvas-api-key.md)."
            )
            return False, err, None

        course_name = self._fetch_canvas_course_name(base_url, course_id)
        if not course_name:
            err = (
                "**Error Canvas:** Your Canvas **API key is invalid, expired, or does not have access** to this course. "
                f"Please ensure that it has access to `{course_url}`.\n"
                "For help provisioning your Canvas API key, please follow "
                "[these steps](https://github.com/Pris-mo/Open_Canvas_Pipeline/blob/main/docs/canvas-api-key.md)."
            )
            return False, err, None

        return True, None, course_name
    def _validate_openai_key(self) -> tuple[bool, Optional[str]]:
        """
        Validate that the OpenAI key (if present) appears usable.

        This is *soft*: failures become warnings and do not block provisioning.
        """
        key = (self.valves.OPENAI_API_KEY or "").strip()

        # Case 1: no key provided at all
        if not key:
            warning = (
                "Warning: No OpenAI API key was provided. "
                "You will not be able to run an OpenAI-hosted model, and documents containing images "
                "or hard-to-parse content may not make it into your knowledge base.\n"
                "For help provisioning an OpenAI API key, please follow "
                "[these steps](https://github.com/Pris-mo/Open_Canvas_Pipeline/blob/main/docs/openai-api-key.md)."
            )
            return False, warning

        try:
            timeout = max(5, min(self.valves.HTTP_TIMEOUT_SECS, 30))
            resp = requests.get(
                "https://api.openai.com/v1/models",
                headers={"Authorization": f"Bearer {key}"},
                timeout=timeout,
            )

            # Try to parse error payload if present
            try:
                data = resp.json()
            except Exception:
                data = None

            # Case 2: explicit "invalid_api_key" (what you just saw in your test)
            if resp.status_code == 401:
                err_code = None
                err_msg = None
                if isinstance(data, dict):
                    err = data.get("error") or {}
                    err_code = err.get("code") or None
                    err_msg = err.get("message") or None

                logger.warning(
                    "OpenAI API returned 401 during validation (code=%r, message=%r)",
                    err_code,
                    (err_msg or "")[:200],
                )

                warning = (
                    "**Warning OpenAI:** Your *OpenAI API key appears to be invalid. "
                    "The OpenAI API returned an authentication error.\n"
                    "You will not be able to run an OpenAI-hosted model, and documents containing images "
                    "or hard-to-parse content may not make it into your knowledge base.\n"
                    "For help provisioning an OpenAI API key, please follow "
                    "[these steps](https://github.com/Pris-mo/Open_Canvas_Pipeline/blob/main/docs/openai-api-key.md)."
                )
                return False, warning

            # Case 3: other non-OK responses (quota, region, generic 4xx/5xx, etc.)
            if not resp.ok:
                logger.warning(
                    "OpenAI API key validation failed with status=%s, body_snippet=%s",
                    resp.status_code,
                    (resp.text or "")[:200],
                )
                warning = (
                    "**Warning OpenAI:** Your **OpenAI API key** may be expired, out of quota, or the OpenAI service "
                    "returned an error (status code {}). "
                    "You may not be able to run an OpenAI-hosted model, and documents containing images "
                    "or hard-to-parse content may not make it into your knowledge base.\n"
                    "For help provisioning an OpenAI API key, please follow "
                    "[these steps](https://github.com/Pris-mo/Open_Canvas_Pipeline/blob/main/docs/openai-api-key.md)."
                ).format(resp.status_code)
                return False, warning

        except Exception as e:
            # Case 4: network/SSL/timeouts/etc.
            logger.warning("OpenAI API key validation encountered an exception: %s", e)
            warning = (
                "**Warning OpenAI:** Your **OpenAI API key** could not be validated from this environment "
                "(network error, timeout, or similar). "
                "You may not be able to run an OpenAI-hosted model, and documents containing images "
                "or hard-to-parse content may not make it into your knowledge base.\n"
                "For help provisioning an OpenAI API key, please follow "
                "[these steps](https://github.com/Pris-mo/Open_Canvas_Pipeline/blob/main/docs/openai-api-key.md)."
            )
            return False, warning

        # If we got here, the key looks usable enough
        return True, None

    def _stream_process_lines(self, cmd: list[str], cwd: Path, env: dict[str, str]):
        """
        Yields lines from stdout/stderr while the process runs.
        """
        proc = subprocess.Popen(
            cmd,
            cwd=str(cwd),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,   # merge stderr into stdout
            text=True,
            bufsize=1,                  # line-buffered
            universal_newlines=True,
        )

        assert proc.stdout is not None
        for line in proc.stdout:
            yield line.rstrip("\n")

        rc = proc.wait()
        return rc

    def upload_markdown_file(self, chunks_root: Path, md_path: Path) -> Dict[str, Any]:
        name = self._safe_upload_name(chunks_root, md_path)
        content = md_path.read_bytes()
        return self.upload_file_from_bytes(name, content)

    def _url(self, path: str) -> str:
        # path should start with "/"
        return f"{self.valves.OPENWEBUI_BASE_URL.rstrip('/')}{path}"

    def _http(self, method: str, path: str, **kwargs) -> requests.Response:
        url = self._url(path)
        headers = kwargs.pop("headers", {})
        merged = {**self._headers(), **headers}

        timeout = kwargs.pop(
            "timeout",
            (HTTP_CONNECT_TIMEOUT_SECS, HTTP_READ_TIMEOUT_SECS),  # ✅ globals
        )

        return requests.request(method, url, headers=merged, timeout=timeout, **kwargs)

    def _require_ok(self, resp: requests.Response, context: str) -> Any:
        """
        Fail fast if:
        - non-2xx
        - endpoint returns HTML (very common when you hit a non-API route in OpenWebUI)
        """
        ctype = (resp.headers.get("content-type") or "").lower()

        if not resp.ok:
            snippet = (resp.text or "")[:500]
            raise RuntimeError(f"{context} failed: {resp.status_code} {snippet}")

        # If we asked for JSON but got HTML, we almost certainly hit the SPA index / wrong route
        if "text/html" in ctype:
            snippet = (resp.text or "")[:300].replace("\n", " ")
            raise RuntimeError(
                f"{context} returned HTML (wrong endpoint for this OpenWebUI build). "
                f"url={resp.url} snippet={snippet}"
            )

        if resp.text and resp.text.strip():
            # Prefer JSON, fall back to text
            try:
                return resp.json()
            except Exception:
                return resp.text

        return None

    def _is_model_id_conflict(self, err: Exception) -> bool:
        """
        Return True if the error looks like OpenWebUI's 'model id already registered' conflict.
        We keep this intentionally fuzzy because the exact payload varies by version.
        """
        s = str(err).lower()
        return ("already registered" in s) or ("model id is already registered" in s) or ("conflict" in s and "model" in s)

    def create_model_stable_first(
        self,
        stable_model_id: str,
        name: str,
        base_model_id: str,
        knowledge_id: Optional[str],
        knowledge_name: Optional[str],
    ) -> tuple[str, Dict[str, Any]]:
        """
        Try creating the model with a stable ID first.
        If it already exists, retry once with a unique suffix.

        Returns: (created_model_id, create_model_response)
        """
        try:
            resp = self.create_model(
                model_id=stable_model_id,
                name=name,
                base_model_id=base_model_id,
                knowledge_id=knowledge_id,
                knowledge_name=knowledge_name,
            )
            return stable_model_id, resp

        except Exception as e:
            if not self._is_model_id_conflict(e):
                raise  # real failure, bubble up

            suffix = uuid.uuid4().hex[:8]
            retry_id = f"{stable_model_id}-{suffix}"
            logger.info("Model id conflict for %s; retrying with %s", stable_model_id, retry_id)

            resp = self.create_model(
                model_id=retry_id,
                name=name,
                base_model_id=base_model_id,
                knowledge_id=knowledge_id,
                knowledge_name=knowledge_name,
            )
            return retry_id, resp

    # ----------------------------
    # Knowledge flow
    # ----------------------------
    def create_knowledge(self, name: str, description: str = "") -> Dict[str, Any]:
        payload = {
            "name": name,
            "description": description,
            "data": {},
            "access_control": {},
        }
        resp = self._http("POST", "/api/v1/knowledge/create", json=payload)
        data = self._require_ok(resp, "create_knowledge")
        if not isinstance(data, dict):
            raise RuntimeError(f"create_knowledge returned unexpected payload: {data}")
        return data

    def upload_file_from_bytes(self, filename: str, content_bytes: bytes) -> Dict[str, Any]:
        files = {"file": (filename, content_bytes, "text/markdown")}

        params = {
            "process": "true" if FILE_PROCESS_DEFAULT else "false",
            "process_in_background": "true" if FILE_PROCESS_IN_BACKGROUND_DEFAULT else "false",
        }

        resp = self._http(
            "POST",
            "/api/v1/files/",
            files=files,
            params=params,
            timeout=(HTTP_CONNECT_TIMEOUT_SECS, HTTP_UPLOAD_READ_TIMEOUT_SECS),  # ✅ globals
        )
        data = self._require_ok(resp, "upload_file")
        if not isinstance(data, dict):
            raise RuntimeError(f"upload_file returned unexpected payload: {data}")
        return data

    def add_file_to_knowledge(self, knowledge_id: str, file_id: str) -> Dict[str, Any]:
        payload = {"file_id": file_id}
        resp = self._http("POST", f"/api/v1/knowledge/{knowledge_id}/file/add", json=payload)
        data = self._require_ok(resp, "add_file_to_knowledge")
        if not isinstance(data, dict):
            # Some builds return {"status":"ok"} or similar; still fine, but keep it consistent
            return {"raw": data}
        return data

    def get_knowledge(self, knowledge_id: str) -> Dict[str, Any]:
        resp = self._http("GET", f"/api/v1/knowledge/{knowledge_id}")
        return self._require_ok(resp, "get_knowledge")

    def default_system_prompt(self) -> str:
        return f"""
            You are a helpful, retrieval-augmented assistant for a Canvas course.

            PRIMARY GOALS
            - Prefer answers grounded in retrieved course materials.
            - When using course content, clearly cite it and hyperlink to the Canvas resource when available.
            - If information is missing or ambiguous, ask a clarifying question rather than guessing.
            - Be concise, friendly, and student-focused.

            -------------------------------------

            ACADEMIC INTEGRITY & COURSE GUIDELINES
            - Do not invent policies, deadlines, or requirements.
            - If asked for answers to graded assessments, provide guidance and explanations instead of direct answers.
            - When relevant, suggest where in Canvas the student can find information (e.g., Modules → Week 3).
            - Use retrieved metadata (title, type, url, etc.) to improve clarity and accuracy when referencing resources.

            -------------------------------------

            HYPERLINKING RULES
            When relevant Canvas resources exist:

            - Include hyperlinks ONLY at the END of your response under a section titled:

            Relevant Course Resources:

            - Include a maximum of 3 links.
            - Include ONLY the most helpful and directly related resources.
            - Prefer graded or required content over optional materials.
            - Prefer assignments, quizzes, modules, pages, or files.
            - Do NOT include duplicate or low-value links.

            LINK FORMAT REQUIREMENTS
            - Links MUST use Markdown hyperlink syntax:
            [Resource Title](URL)

            - Use descriptive titles instead of raw URLs.
            - Never display raw URLs.
            - Never place URLs in parentheses after text.
            - Never add commentary on the same line as a hyperlink.

            If more than 3 relevant resources are available:
            - Select the most instructionally helpful resources.

            If a URL exists in retrieved metadata:
            - Always prefer generating a Markdown hyperlink.

            -------------------------------------

            RESPONSE FORMAT
            - Provide the main answer first.
            - Only include the hyperlink section if relevant resources are retrieved.
            - Hyperlinks must appear only in the final section.

            Example Format:

            Relevant Course Resources:
            • [Resource Title](URL)

            -------------------------------------

            CORRECT EXAMPLE
            • [Summary Statistics Quiz](https://learn.canvas.net/courses/2251/quizzes/18810)

            INCORRECT EXAMPLES (DO NOT USE)
            • Summary Statistics Quiz (https://learn.canvas.net/courses/2251/quizzes/18810)
            • https://learn.canvas.net/courses/2251/quizzes/18810

            -------------------------------------

            WHEN NO RELEVANT KNOWLEDGE IS RETRIEVED
            - State that no relevant course material was found.
            - Explain what additional information would help.

            """.strip()

    # ----------------------------
    # Model flow
    # ----------------------------
    def create_model(
        self,
        model_id: str,
        name: str,
        base_model_id: str,
        knowledge_id: Optional[str],
        knowledge_name: Optional[str],
    ) -> Dict[str, Any]:

        payload: Dict[str, Any] = {
            "id": model_id,
            "name": name,
            "base_model_id": base_model_id,
            "params": {
                "system": self.default_system_prompt(),
            },
            "meta": {
                "description": "Course assistant model created by Canvas Course Provisioner.",
                "suggestion_prompts": [],
                "capabilities": {
                    "file_context": "true",
                    "vision": "true",
                    "file_upload": "true",
                    "web_search": "true",
                    "image_generation": "true",
                    "code_interpreter": "true",
                    "citations": "true",
                    "status_updates": "true",
                    "builtin_tools": "true"
                    },
            },
            "access_control": None,
        }

        # Some builds expect "knowledge" at top-level meta as an array of KB objects
        # Attach KB in the shape the UI expects.
        if knowledge_id:
            # Prefer the full KB object so UI can render name/description.
            try:
                kb_obj = self.get_knowledge(knowledge_id)
            except Exception:
                # Fallback: at least provide id + name so UI doesn't show "undefined"
                kb_obj = {"id": knowledge_id, "name": knowledge_name or "Knowledge Base"}

            if isinstance(kb_obj, dict) and kb_obj.get("type") != "collection":
                kb_obj["type"] = "collection"

            # This matches what your working model payload looks like (meta.knowledge = [{...}])
            payload["meta"]["knowledge"] = [kb_obj]

        resp = self._http("POST", "/api/v1/models/create", json=payload)
        data = self._require_ok(resp, "create_model")
        if not isinstance(data, dict):
            return {"raw": data}
        return data

    def run_orchestrator_stream(self, course_url: str):
        runs_root = Path(ORCH_RUNS_ROOT_DEFAULT)
        orch_py = sys.executable  # use current interpreter

        if not Path(orch_py).exists():
            yield f"❌ Orchestrator python not found: {orch_py}"
            yield {"type": "final", "returncode": 2}
            return

        run_dir = runs_root / "openwebui"  # matches --run-name openwebui

        if run_dir.exists():
            shutil.rmtree(run_dir)
        run_dir.mkdir(parents=True, exist_ok=True)

        cmd = [
            orch_py, "-u",
            "-m", "orchestrator.cli",
            "--course-url", course_url,
            "--runs-root", ORCH_RUNS_ROOT_DEFAULT,   # 👈 absolute path, respected by orchestrator
            "--depth-limit", str(ORCH_DEPTH_LIMIT_DEFAULT),
            "--model", self.valves.BASE_MODEL_ID,
            "--run-name", "openwebui",
            "--include-frontmatter",
        ]

        if self.valves.CANVAS_API_KEY:
            cmd += ["--canvas-token", self.valves.CANVAS_API_KEY]

        env = os.environ.copy()
        if self.valves.CANVAS_API_KEY:
            env["CANVAS_TOKEN"] = self.valves.CANVAS_API_KEY
        if self.valves.OPENAI_API_KEY:
            env["OPENAI_API_KEY"] = self.valves.OPENAI_API_KEY

        rc = 0
        try:
            # cwd doesn’t matter much now; PIPELINE_ROOT is fine
            gen = self._stream_process_lines(cmd, cwd=PIPELINE_ROOT, env=env)
            while True:
                try:
                    line = next(gen)
                    yield line + "\n"
                except StopIteration as e:
                    rc = e.value if e.value is not None else 0
                    break
        except Exception as e:
            yield f"❌ Orchestrator exception: {e}"
            yield {"type": "final", "returncode": 2}
            return

        if rc != 0:
            yield f"❌ Orchestrator failed (exit {rc})"
            yield {"type": "final", "returncode": rc}
            return

        yield "✅ Orchestrator finished successfully."
        yield {"type": "final", "returncode": 0}

    def run_orchestrator(self, course_url: str) -> dict[str, Any]:
        runs_root = Path(ORCH_RUNS_ROOT_DEFAULT)
        orch_py = sys.executable

        if not Path(orch_py).exists():
            return {
                "returncode": 2,
                "stdout": "",
                "stderr": "❌ Orchestrator environment not ready.\n",
                "cmd": "",
            }

        run_dir = runs_root / "openwebui"

        if run_dir.exists():
            shutil.rmtree(run_dir)
        run_dir.mkdir(parents=True, exist_ok=True)

        cmd = [
            orch_py,
            "-u",
            "-m", "orchestrator.cli",
            "--course-url", course_url,
            "--runs-root", ORCH_RUNS_ROOT_DEFAULT,  # 👈 same absolute runs root
            "--depth-limit", str(ORCH_DEPTH_LIMIT_DEFAULT),
            "--model", self.valves.BASE_MODEL_ID,
            "--run-name", "openwebui",
            "--include-frontmatter",
        ]

        if self.valves.CANVAS_API_KEY:
            cmd += ["--canvas-token", self.valves.CANVAS_API_KEY]

        env = os.environ.copy()
        if self.valves.CANVAS_API_KEY:
            env["CANVAS_TOKEN"] = self.valves.CANVAS_API_KEY
        if self.valves.OPENAI_API_KEY:
            env["OPENAI_API_KEY"] = self.valves.OPENAI_API_KEY

        proc = subprocess.run(
            cmd,
            cwd=str(PIPELINE_ROOT),
            env=env,
            capture_output=True,
            text=True,
        )

        return {
            "returncode": proc.returncode,
            "stdout": (proc.stdout or "")[-4000:],
            "stderr": (proc.stderr or "")[-4000:],
            "cmd": " ".join(cmd),
        }

    def _stream_provision(
        self,
        course_url: str,
        base_url: str,
        course_id: str,
        warnings: list[str],
        course_name: Optional[str] = None,
    ):
        # 🔔 Show any pre-flight warnings (e.g., OpenAI key issues) *before* we do anything heavy.
        if warnings:
            yield "⚠️ Warnings detected before provisioning:\n"
            for w in warnings:
                # Handle multi-line warnings nicely
                for line in str(w).splitlines():
                    if line.strip():
                        yield f"- {line}\n"
            yield "\n[Starting] Running orchestrator for the course...\n\n"

        # 6) Orchestrator streaming
        orch_rc = None

        for item in self.run_orchestrator_stream(course_url):
            if isinstance(item, dict) and item.get("type") == "final":
                orch_rc = item.get("returncode", 2)
            else:
                line = str(item).rstrip()

                if self.valves.DEBUG:
                    # Stream all orchestrator output
                    clean = line.replace("::STEP::", "- ", 1)
                    yield clean + "\n"
                else:
                    # Only show STEP lines
                    if "::STEP::" in line:
                        clean = line.replace("::STEP::", "- ", 1)
                        yield clean + "\n"

        if orch_rc != 0:
            yield "❌ Orchestrator failed"
            return
        if orch_rc is None:
            yield "❌ Orchestrator ended without final status"
            return

        # ✅ Status message once the orchestrator has finished
        yield "\n[Uploading] Now uploading files and creating the model\n"

        u = urlparse(course_url)
        host = u.netloc or "canvas"
        host_slug = _slug(host)
        course_slug = _slug(course_id)

        # Try to get a human-readable course name from Canvas if we don't already have one
        if not course_name:
            course_name = self._fetch_canvas_course_name(base_url, course_id)

        if course_name:
            display_name = f"Canvas: {course_name}"
        else:
            # Fallback if the API call fails or token isn't set
            display_name = f"Canvas: {host} {course_id}"

        kb_name = display_name
        model_name = display_name

        # Keep a stable, compact model id that doesn't depend on the full course name
        stable_model_id = f"canvas-{host_slug}-{course_slug}"

        # 7) Create KB
        desc_course = course_name or course_url
        kb = self.create_knowledge(
            name=kb_name,
            description=f"Autocreated KB for course {desc_course}",
        )

        kb_id = kb.get("id")
        if not kb_id:
            yield f"KB create returned unexpected payload: {kb}"
            return

        # 8) Upload chunks
        runs_root = Path(ORCH_RUNS_ROOT_DEFAULT)
        run_dir = runs_root / "openwebui"
        chunks_dir = run_dir / "chunker" / "chunks"

        md_files = self._iter_markdown_files(chunks_dir)
        if not md_files:
            yield (
                "❌ Orchestrator succeeded, but no chunk .md files were found.\n\n"
                f"Expected chunks under:\n  {chunks_dir}\n\n"
                "Next steps:\n"
                "• Confirm chunker is enabled in the orchestrator run\n"
                "• Check the orchestrator logs for where chunks were written"
            )
            return
        else:
            yield f"Found {len(md_files)} markdown files under:\n  {chunks_dir}\n"

        uploaded_file_ids: List[str] = []
        upload_failures: List[str] = []

        workers = UPLOAD_WORKERS_DEFAULT

        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = {
                ex.submit(self._upload_and_attach_one, kb_id, chunks_dir, p): p
                for p in md_files
            }
            for fut in as_completed(futures):
                p = futures[fut]
                try:
                    path_str, file_id, err = fut.result()
                    if file_id:
                        uploaded_file_ids.append(file_id)
                    else:
                        upload_failures.append(f"{path_str} -> {err or 'upload/add returned no file id'}")
                except Exception as e:
                    upload_failures.append(f"{p} -> {e}")
        yield (
            f"\nUpload summary:\n"
            f"- Markdown files discovered: {len(md_files)}\n"
            f"- Files uploaded successfully: {len(uploaded_file_ids)}\n"
            f"- Files that failed to upload: {len(upload_failures)}\n"
        )

        if upload_failures:
            yield "Example upload failures (first 5):\n"
            for fail in upload_failures[:5]:
                yield f"- {fail}\n"

        if not uploaded_file_ids:
            yield (
                "❌ No chunk files were uploaded successfully.\n\n"
                "Failures:\n- " + "\n- ".join(upload_failures[:20]) +
                ("\n\n(Only first 20 shown)" if len(upload_failures) > 20 else "")
            )
            return

        if upload_failures:
            warnings.append(
                f"{len(upload_failures)} chunk files failed to upload (uploaded {len(uploaded_file_ids)})."
            )

        created_id, created_model = self.create_model_stable_first(
            stable_model_id=stable_model_id,
            name=model_name,
            base_model_id=self.valves.BASE_MODEL_ID,
            knowledge_id=kb_id,
            knowledge_name=kb_name,
        )

        warn_text = ("\n\n⚠️ Warnings:\n- " + "\n- ".join(warnings)) if warnings else ""

        yield (
            "✅ Success Provisioning complete\n\n"
            f"- Knowledge Base Created at: `{kb_name}` (id={kb_id})\n"
            f"- Uploaded chunk files: {len(uploaded_file_ids)}\n"
            f"- Model created at: `{created_id}` (base={self.valves.BASE_MODEL_ID})\n"
            f"{warn_text}\n\n"
        )


    def pipe(self, user_message: str, model_id: str, messages: List[dict], body: dict):
        # 1) Title
        if body.get("title"):
            return "🧱 Canvas Course Provisioner"

        # 2) Tags
        if body.get("tags"):
            return json.dumps({"tags": ["Education", "Canvas", "RAG"]})

        # 3) Ignore background prompt shenanigans
        if user_message and (
            "### Task:" in user_message
            or "<chat_history>" in user_message
        ):
            return "Ignored background title/tags request."

        warnings: list[str] = []

        m = re.match(r"^\s*/?provision\s+(.+?)\s*$", user_message or "", flags=re.I)
        if not m:
            return "To run this pipeline, send: `provision <course_url>` (example: `provision https://learn.canvas.net/courses/3376`)."

        course_url = m.group(1).strip()
        if not course_url:
            return "Provide a Canvas course URL. Example: `provision https://learn.canvas.net/courses/3376`."

        try:
            base_url, course_id = _parse_course_url(course_url)
        except Exception as e:
            return f"Invalid Canvas course URL: {e}"

        logger.info("User input course_url=%s (base=%s course_id=%s)", course_url, base_url, course_id)

        # ----------------------------
        # NEW: Key validation
        # ----------------------------
        errors: list[str] = []
        course_name: Optional[str] = None

        # 1) OpenWebUI key (hard stop on failure)
        openweb_ok, openweb_err = self._validate_openwebui_key()
        if not openweb_ok and openweb_err:
            errors.append(openweb_err)

        # 2) Canvas key (hard stop on failure; also fetch course name)
        canvas_ok, canvas_err, course_name = self._validate_canvas_key(base_url, course_id, course_url)
        if not canvas_ok and canvas_err:
            errors.append(canvas_err)

        # 3) OpenAI key (soft warning; do NOT block provisioning)
        openai_ok, openai_warning = self._validate_openai_key()
        if not openai_ok and openai_warning:
            warnings.append(openai_warning)

        # If any hard-stop errors occurred, report *all* of them, plus any warnings, and do not run.
        if errors:
            msg_lines: list[str] = [
                "The following problems need to be fixed before provisioning can run:",
                "",
            ]
            msg_lines.extend(f"- {e}" for e in errors)

            if warnings:
                msg_lines.append("")
                msg_lines.append("Warnings:")
                msg_lines.extend(f"- {w}" for w in warnings)

            return "\n".join(msg_lines)

        logger.info("All required keys validated successfully for course_url=%s", course_url)

        # 👉 IMPORTANT: return a generator *object* here.
        # OpenWebUI will treat this as a streaming pipeline.
        return self._stream_provision(course_url, base_url, course_id, warnings, course_name)
