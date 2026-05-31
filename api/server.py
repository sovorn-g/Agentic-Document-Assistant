import json
import logging
import shutil
import tempfile
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from core.chat_interface import ChatInterface
from core.document_manager import DocumentManager
from core.rag_system import RAGSystem


class _SuppressOtelDetachWarning(logging.Filter):
    def filter(self, record):
        return "Failed to detach context" not in record.getMessage()


logging.getLogger("opentelemetry.context").addFilter(_SuppressOtelDetachWarning())


class ProjectCreate(BaseModel):
    name: str = "Untitled Project"


rag_system = RAGSystem()
rag_system.initialize()
store = rag_system.store
default_project_id = store.ensure_default_project()
doc_manager = DocumentManager(rag_system)
chat_interface = ChatInterface(rag_system)

app = FastAPI(title="Agentic Document Assistant")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def project_or_404(project_id: str) -> dict[str, Any]:
    project = store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def serialize_messages(session_id: str) -> list[dict[str, str]]:
    return chat_interface.format_history(session_id)


def serialize_documents(project_id: str) -> list[dict[str, Any]]:
    return doc_manager.list_documents(project_id)


def project_payload(project_id: str, session_id: str | None = None) -> dict[str, Any]:
    project_or_404(project_id)
    session_id = store.get_or_create_session(project_id, session_id)
    return {
        "projects": store.list_projects(),
        "selected_project_id": project_id,
        "sessions": store.list_sessions(project_id),
        "selected_session_id": session_id,
        "documents": serialize_documents(project_id),
        "messages": serialize_messages(session_id),
    }


@app.get("/api/bootstrap")
def bootstrap():
    project_id = store.ensure_default_project()
    return project_payload(project_id)


@app.get("/api/projects")
def list_projects():
    return {"projects": store.list_projects()}


@app.post("/api/projects")
def create_project(payload: ProjectCreate):
    project_id = store.create_project(payload.name)
    return project_payload(project_id)


@app.delete("/api/projects/{project_id}")
def delete_project(project_id: str):
    project_or_404(project_id)
    doc_manager.clear_project(project_id)
    shutil.rmtree(rag_system.get_project_storage_dir(project_id), ignore_errors=True)
    store.delete_project(project_id)
    rag_system.clear_agent_graph_cache(project_id)
    next_project_id = store.ensure_default_project()
    return project_payload(next_project_id)


@app.get("/api/projects/{project_id}/sessions")
def list_sessions(project_id: str):
    project_or_404(project_id)
    return {"sessions": store.list_sessions(project_id)}


@app.post("/api/projects/{project_id}/sessions")
def create_session(project_id: str):
    project_or_404(project_id)
    session_id = store.create_session(project_id)
    return {
        "sessions": store.list_sessions(project_id),
        "selected_session_id": session_id,
        "messages": serialize_messages(session_id),
    }


@app.get("/api/sessions/{session_id}/messages")
def list_messages(session_id: str):
    session = store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"messages": serialize_messages(session_id)}


@app.delete("/api/sessions/{session_id}")
def delete_session(session_id: str):
    project_id = store.delete_session(session_id)
    if not project_id:
        raise HTTPException(status_code=404, detail="Session not found")
    sessions = store.list_sessions(project_id)
    if not sessions:
        selected_session_id = store.create_session(project_id)
        sessions = store.list_sessions(project_id)
    else:
        selected_session_id = sessions[0]["id"]
    return {
        "sessions": sessions,
        "selected_session_id": selected_session_id,
        "messages": serialize_messages(selected_session_id),
    }


@app.get("/api/projects/{project_id}/documents")
def list_documents(project_id: str):
    project_or_404(project_id)
    return {"documents": serialize_documents(project_id)}


@app.post("/api/projects/{project_id}/documents")
async def upload_documents(project_id: str, files: list[UploadFile] = File(...)):
    project_or_404(project_id)
    with tempfile.TemporaryDirectory() as tmpdir:
        temp_paths = []
        for upload in files:
            suffix = Path(upload.filename or "").suffix.lower()
            if suffix not in DocumentManager.SUPPORTED_SUFFIXES:
                continue
            safe_name = DocumentManager._safe_name(upload.filename or f"document{suffix}")
            temp_path = Path(tmpdir) / safe_name
            with temp_path.open("wb") as tmp:
                shutil.copyfileobj(upload.file, tmp)
            if temp_path.stat().st_size == 0:
                continue
            temp_paths.append(str(temp_path))

        if files and not temp_paths:
            raise HTTPException(status_code=400, detail="Upload at least one non-empty PDF or Markdown (.md/.markdown) file.")

        added, skipped = doc_manager.add_documents(project_id, temp_paths)
        return {
            "added": added,
            "skipped": skipped + max(0, len(files) - len(temp_paths)),
            "documents": serialize_documents(project_id),
        }


@app.delete("/api/documents/{document_id}")
def delete_document(document_id: str):
    deleted = doc_manager.delete_document(document_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Document not found")
    return {"deleted": True}

def sse_event(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@app.get("/api/projects/{project_id}/sessions/{session_id}/chat/stream")
def stream_chat(project_id: str, session_id: str, message: str):
    project_or_404(project_id)
    if not store.get_session(session_id):
        raise HTTPException(status_code=404, detail="Session not found")

    def generate():
        for item in chat_interface.stream_events(project_id, session_id, message):
            yield sse_event(item["event"], item["data"])

    return StreamingResponse(generate(), media_type="text/event-stream")


FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"

if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")


@app.get("/{full_path:path}")
def serve_frontend(full_path: str):
    index_path = FRONTEND_DIST / "index.html"
    requested_path = FRONTEND_DIST / full_path
    if full_path and requested_path.is_file():
        return FileResponse(requested_path)
    if index_path.exists():
        return FileResponse(index_path)
    raise HTTPException(status_code=404, detail="Frontend build not found. Run npm install && npm run build in frontend/.")
