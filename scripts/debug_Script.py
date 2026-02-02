import json
import os
import time
import uuid
from typing import Any, Dict, List, Tuple
from wsgiref import headers

import requests

import dotenv

dotenv.load_dotenv()
BASE_URL = "http://localhost:3000"  # Change to your Open WebUI URL
API_KEY = os.getenv("OPENWEBUI_API_KEY", "")  
BASE_MODEL_ID = os.getenv("BASE_MODEL_ID", "gpt-4o")
HTTP_TIMEOUT = 60

def _slug(s: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "-" for ch in s).strip("-")[:60]


class OWUI:
    def __init__(self, base_url: str, api_key: str, timeout: int = 60) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def _url(self, path: str) -> str:
        if not path.startswith("/"):
            path = "/" + path
        return self.base_url + path

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "accept": "application/json"}

    def _json_headers(self) -> Dict[str, str]:
        return {**self._headers(), "Content-Type": "application/json"}

    def _require_ok(self, resp: requests.Response, context: str) -> Any:
        ctype = (resp.headers.get("content-type") or "").lower()
        if not resp.ok:
            raise RuntimeError(f"{context} failed: {resp.status_code} {resp.text[:1200]}")
        if "text/html" in ctype:
            raise RuntimeError(f"{context} returned HTML (wrong route?): url={resp.url}")
        if resp.text and resp.text.strip():
            try:
                return resp.json()
            except Exception:
                return resp.text
        return {}

    def list_chat_models(self) -> List[Dict[str, Any]]:
        r = requests.get(self._url("/api/models"), headers=self._headers(), timeout=self.timeout)
        data = self._require_ok(r, "list_chat_models")
        # common shapes: {"data":[...]} or [...]
        if isinstance(data, dict) and isinstance(data.get("data"), list):
            return data["data"]
        if isinstance(data, list):
            return data
        return []

    def resolve_chat_model_id(self, custom_model_id: str) -> str:
        """
        Find the identifier that /api/chat/completions accepts.
        We try matching against several common fields.
        """
        models = self.list_chat_models()
        for m in models:
            # common keys across builds
            if m.get("id") == custom_model_id:
                return m["id"]
            if m.get("model") == custom_model_id:
                return m["model"]
            if m.get("name") == custom_model_id:
                return m.get("id") or m.get("model") or m.get("name")

        # fallback: sometimes custom models appear as-is but under /api/v1/models/list
        raise RuntimeError(
            f"Could not resolve custom model '{custom_model_id}' to a chat-usable model id. "
            f"Try printing /api/models output to see what chat expects."
        )


    # ---------- Knowledge ----------
    def create_knowledge(self, name: str, description: str) -> Dict[str, Any]:
        payload = {"name": name, "description": description, "data": {}, "access_control": {}}
        r = requests.post(
            self._url("/api/v1/knowledge/create"),
            headers=self._json_headers(),
            json=payload,
            timeout=self.timeout,
        )
        data = self._require_ok(r, "create_knowledge")
        if not data.get("id"):
            raise RuntimeError(f"KB create returned unexpected payload: {data}")
        return data

    def get_knowledge(self, kb_id: str) -> Dict[str, Any]:
        r = requests.get(
            self._url(f"/api/v1/knowledge/{kb_id}"),
            headers=self._headers(),
            timeout=self.timeout,
        )
        return self._require_ok(r, "get_knowledge")
    
    def list_knowledges(self) -> List[Dict[str, Any]]:
        params = {"page": 1}

        r = requests.get(
            self._url("/api/v1/knowledge/"),
            headers=self._headers(),
            params=params,
            timeout=self.timeout,
        )
        data = self._require_ok(r, "list_knowledges")    
        if isinstance(data, dict) and isinstance(data.get("items"), list):
            return data["items"]
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and isinstance(data.get("data"), list):
            return data["data"]
        return []

    def add_file_to_knowledge(self, kb_id: str, file_id: str) -> None:
        payload = {"file_id": file_id}
        r = requests.post(
            self._url(f"/api/v1/knowledge/{kb_id}/file/add"),
            headers=self._json_headers(),
            json=payload,
            timeout=self.timeout,
        )
        self._require_ok(r, "add_file_to_knowledge")

    # ---------- Files ----------
    def upload_file_bytes(self, filename: str, content: bytes) -> str:
        params = {
            "process": "true",
            "process_in_background": "false",  # deterministic
        }
        files = {"file": (filename, content, "text/markdown")}
        r = requests.post(
            self._url("/api/v1/files/"),
            headers=self._headers(),
            files=files,
            params=params,
            timeout=self.timeout,
        )
        data = self._require_ok(r, "upload_file")
        file_id = data.get("id") or (data.get("file") or {}).get("id")
        if not file_id:
            raise RuntimeError(f"Upload returned no file id: {data}")
        return file_id

    def wait_file_processed(self, file_id: str, timeout_s: int = 300) -> None:
        t0 = time.time()
        while time.time() - t0 < timeout_s:
            r = requests.get(
                self._url(f"/api/v1/files/{file_id}/process/status"),
                headers=self._headers(),
                timeout=self.timeout,
            )
            data = self._require_ok(r, "file_process_status")
            if (data.get("status") or "").lower() == "completed":
                return
            time.sleep(1.5)
        raise TimeoutError(f"File {file_id} not processed in time")

    # ---------- Models ----------
    def create_model(self, model_id: str, name: str) -> None:
        payload = {
            "id": model_id,
            "name": name,
            "base_model_id": BASE_MODEL_ID,
            "params": {"system": "You are a helpful retrieval-augmented assistant."},
            "meta": {
                "description": "KB smoketest model",
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
        r = requests.post(
            self._url("/api/v1/models/create"),
            headers=self._json_headers(),
            json=payload,
            timeout=self.timeout,
        )
        self._require_ok(r, "create_model")

    def get_model(self, model_id: str) -> Dict[str, Any]:
        r = requests.get(
            self._url("/api/v1/models/model"),
            headers=self._headers(),
            params={"id": model_id},
            timeout=self.timeout,
        )
        return self._require_ok(r, "get_model")

    def attach_kb_to_model(self, model_id: str, kb_obj: Dict[str, Any]) -> None:
        current = self.get_model(model_id)
        model = current.get("model") if isinstance(current.get("model"), dict) else current

        meta = model.get("meta") or {}
        meta["capabilities"] = meta.get("capabilities") or {}
        meta["knowledge"] = [kb_obj]

        model["meta"] = meta
        model["id"] = model_id

        r = requests.post(
            self._url("/api/v1/models/model/update"),
            headers=self._json_headers(),
            json=model,
            timeout=self.timeout,
        )
        self._require_ok(r, "update_model")

    # ---------- RAG (docs-recommended) ----------
    def chat_with_collection(self, model_id: str, kb_id: str, question: str) -> Dict[str, Any]:
        payload = {
            "model": model_id,
            "messages": [{"role": "user", "content": question}],
            "files": [{"type": "collection", "id": kb_id}],
        }
        r = requests.post(
            self._url("/api/chat/completions"),
            headers=self._json_headers(),
            json=payload,
            timeout=self.timeout,
        )
        return self._require_ok(r, "chat_with_collection")


def make_test_docs(run_id: str) -> List[Tuple[str, bytes]]:
    a = f"Needle A: the quick brown fox jumps over the lazy dog {run_id}\n"
    b = f"Needle B: pack my box with five dozen liquor jugs {run_id}\n"
    return [
        (f"a_{run_id}.md", a.encode()),
        (f"b_{run_id}.md", b.encode()),
    ]


def main() -> None:
    run_id = uuid.uuid4().hex[:8]
    owui = OWUI(BASE_URL, API_KEY, timeout=HTTP_TIMEOUT)

    kb_name = f"kb-smoketest-{run_id}"
    model_id = f"model-smoketest-{run_id}"

    print("RUN:", run_id)

    # 1) KB
    kb = owui.create_knowledge(kb_name, f"Smoketest KB {run_id}")
    kb_id = kb["id"]
    print("KB:", kb_id)

    # 2) Files
    file_ids = []
    for fn, content in make_test_docs(run_id):
        fid = owui.upload_file_bytes(fn, content)
        owui.wait_file_processed(fid)
        owui.add_file_to_knowledge(kb_id, fid)
        file_ids.append(fid)
        print("FILE:", fid)

    # 3) Model
    owui.create_model(model_id, model_id)
    print("MODEL:", model_id)

    # testing
    knowledge_list = owui.list_knowledges()

    # get the knowledge from the knowledge list using the kb_id
    model_knowledge = next((k for k in knowledge_list if k.get("id") == kb_id), None) 
 
    # add "type": "collection" to the knowledge object
    if model_knowledge: 
        model_knowledge["type"] = "collection"

    #model_knowledge = owui.get_knowledge(kb_id)

    # 4) Attach KB
    owui.attach_kb_to_model(model_id, model_knowledge)
    print("KB attached")

    # 5) RAG query (forced)
    chat_model_id = owui.resolve_chat_model_id(model_id)
    print("CHAT_MODEL_ID:", chat_model_id)

    resp = owui.chat_with_collection(chat_model_id, kb_id, f"...{run_id}...")


    print("\n--- RESPONSE ---")
    print(json.dumps(resp, indent=2)[:3000])


if __name__ == "__main__":
    main()