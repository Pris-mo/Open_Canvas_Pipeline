"""
title: canvas_kb_prototype
description: Creates a Knowledge Base, uploads 2 test markdown files, adds them to that KB, and (best-effort) creates a custom model bound to that KB.
requirements: requests,pydantic
"""

from __future__ import annotations

from typing import List, Union, Generator, Iterator, Dict, Any, Optional
import os
import json
import logging
import re

import requests
from pydantic import BaseModel, Field

logger = logging.getLogger("canvas_kb_bootstrap")
logging.basicConfig(level=logging.INFO)


class Pipeline:
    class Valves(BaseModel):
        OPENWEBUI_BASE_URL: str = Field(default="http://host.docker.internal:3000")
        OPENWEBUI_API_KEY: str = Field(default="")
        BASE_MODEL_ID: str = Field(default="gpt-4o")
        KB_PREFIX: str = Field(default="Canvas Course")
        MODEL_PREFIX: str = Field(default="Canvas Assistant")
        HTTP_TIMEOUT_SECS: int = Field(default=30)

    def __init__(self):
        # This is what makes it show up as a "model" in Open WebUI
        self.name = "Canvas KB Bootstrap (Prototype)"

        # Load defaults from env, but primarily use valves in the UI
        self.valves = self.Valves(
            OPENWEBUI_BASE_URL=os.getenv("OPENWEBUI_BASE_URL", "http://host.docker.internal:3000"),
            OPENWEBUI_API_KEY=os.getenv("OPENWEBUI_API_KEY", ""),
            BASE_MODEL_ID=os.getenv("BASE_MODEL_ID", "gpt-4o"),
            HTTP_TIMEOUT_SECS=int(os.getenv("HTTP_TIMEOUT_SECS", "30")),
        )

    async def on_startup(self):
        logger.info("Pipeline startup: canvas_kb_bootstrap")

    async def on_shutdown(self):
        logger.info("Pipeline shutdown: canvas_kb_bootstrap")

    # ----------------------------
    # Open WebUI API helpers
    # ----------------------------
    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.valves.OPENWEBUI_API_KEY}",
            "Accept": "application/json",
        }

    def _url(self, path: str) -> str:
        # path should start with "/"
        return f"{self.valves.OPENWEBUI_BASE_URL.rstrip('/')}{path}"

    def _http(self, method: str, path: str, **kwargs) -> requests.Response:
        url = self._url(path)
        headers = kwargs.pop("headers", {})
        merged = {**self._headers(), **headers}

        timeout = kwargs.pop("timeout", self.valves.HTTP_TIMEOUT_SECS)

        resp = requests.request(method, url, headers=merged, timeout=timeout, **kwargs)
        return resp

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
        resp = self._http("POST", "/api/v1/files/", files=files)
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

            Your goals:
            - Prefer answers grounded in retrieved course materials.
            - When using course content, cite it clearly and link to the Canvas page when available.
            - If information is missing or ambiguous, ask a clarifying question rather than guessing.
            - Be concise, friendly, and student-focused.

            Guidelines:
            - Do not invent policies, deadlines, or requirements.
            - If asked for answers to graded assessments, provide guidance and explanations instead of direct answers.
            - When relevant, suggest where in Canvas the student can find the information (e.g., Modules → Week 3).

            If no relevant knowledge is retrieved, say so explicitly and explain what information would help.
            """.strip()



    # ----------------------------
    # Model flow (best-effort)
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
                "description": "Prototype model created by Canvas KB Bootstrap pipeline.",
                "suggestion_prompts": [],
            },
            "access_control": None,
        }


        # Some builds expect "knowledge" at top-level meta as an array of KB objects
        # Best-effort attach KB in the shape the UI expects.
        if knowledge_id:
            # Prefer the full KB object so UI can render name/description.
            try:
                kb_obj = self.get_knowledge(knowledge_id)
            except Exception:
                # Fallback: at least provide id + name so UI doesn't show "undefined"
                kb_obj = {"id": knowledge_id, "name": knowledge_name or "Knowledge Base"}

            # This matches what your working model payload looks like (meta.knowledge = [{...}])
            payload["meta"]["knowledge"] = [kb_obj]

            # Some builds also read a top-level "knowledge" field; harmless to include.
            payload["knowledge"] = [kb_obj]


        resp = self._http("POST", "/api/v1/models/create", json=payload)
        data = self._require_ok(resp, "create_model")
        if not isinstance(data, dict):
            return {"raw": data}
        return data

        
    def pipe(self, user_message: str, model_id: str, messages: List[dict], body: dict):
        # 1) Open WebUI background: chat title generation
        if body.get("title"):
            return "🧱 Canvas KB Bootstrap"

        # 2) Open WebUI background: chat tags generation
        if body.get("tags"):
            return json.dumps({"tags": ["Education", "Canvas", "RAG"]})

        # 3) Defensive: ignore OWUI “### Task:” prompts even if flags aren't present
        if user_message and (
            "### Task:" in user_message
            or "<chat_history>" in user_message
            or len(user_message) > 60  # defensive; your course_id should be short
        ):
            return "Ignored background title/tags request."

        # 4) Optional: require explicit command so normal chat doesn't trigger bootstrap
        # Expected: "bootstrap 3376" or "/bootstrap 3376"
        m = re.match(r"^\s*/?bootstrap\s+(.+?)\s*$", user_message or "", flags=re.I)
        if not m:
            return "To run this pipeline, send: `bootstrap <course_id>` (example: `bootstrap 3376`)."

        course_id = m.group(1).strip()
        if not course_id:
            return "Type a course id (any string) to bootstrap KB + upload 2 test files + create a model."

        logger.info("User input course_id=%s", course_id)

        kb_name = f"{self.valves.KB_PREFIX} {course_id}"
        model_name = f"{self.valves.MODEL_PREFIX} {course_id}"
        model_id_new = f"canvas-assistant-{course_id}".lower().replace(" ", "-").replace("/", "-")

        # 1) Create KB
        kb = self.create_knowledge(
            name=kb_name,
            description=f"Autocreated KB for course {course_id}",
        )
        kb_id = kb.get("id")
        if not kb_id:
            return f"KB create returned unexpected payload: {kb}"

        # 2) Upload 2 test MD files
        md1 = f"# Course {course_id}\n\nThis is test file 1 for course {course_id}.\n"
        md2 = f"# Course {course_id} - Notes\n\nThis is test file 2 for course {course_id}.\n"

        up1 = self.upload_file_from_bytes(f"{course_id}_test_1.md", md1.encode("utf-8"))
        up2 = self.upload_file_from_bytes(f"{course_id}_test_2.md", md2.encode("utf-8"))

        file1_id = up1.get("id") or (up1.get("file") or {}).get("id")
        file2_id = up2.get("id") or (up2.get("file") or {}).get("id")
        if not file1_id or not file2_id:
            return f"Upload returned unexpected payloads:\n1={up1}\n2={up2}"

        # 3) Add to KB (no polling)
        add1 = self.add_file_to_knowledge(kb_id, file1_id)
        add2 = self.add_file_to_knowledge(kb_id, file2_id)

        # 4) Create model (best-effort attach KB)
        created_model = self.create_model(
            model_id=model_id_new,
            name=model_name,
            base_model_id=self.valves.BASE_MODEL_ID,
            knowledge_id=kb_id,
            knowledge_name=kb_name,
        )


        return (
            "✅ Prototype complete\n\n"
            f"- Input: `{course_id}`\n"
            f"- Knowledge Base: `{kb_name}` (id={kb_id})\n"
            f"- Uploaded files: `{file1_id}`, `{file2_id}`\n"
            f"- Added-to-KB responses: {json.dumps({'file1': add1, 'file2': add2})[:400]}\n"
            f"- Model created: `{model_id_new}` (base={self.valves.BASE_MODEL_ID})\n\n"
            "Notes:\n"
            "• Your OpenWebUI indexes files asynchronously; this pipeline does not wait for processing.\n"
            "• If the KB doesn’t show as attached in the model editor, you can manually attach it once in the UI.\n"
            f"• Raw model create response (truncated): {str(created_model)[:400]}"
        )
