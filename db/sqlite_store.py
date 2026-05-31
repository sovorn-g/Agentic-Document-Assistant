import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

import config


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class SQLiteStore:
    def __init__(self, db_path: str = config.APP_DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS chat_sessions (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    title TEXT NOT NULL,
                    memory_summary TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS chat_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
                    role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                    content TEXT NOT NULL,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    filename TEXT NOT NULL,
                    original_path TEXT,
                    markdown_path TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_chat_sessions_project
                    ON chat_sessions(project_id, updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_chat_messages_session
                    ON chat_messages(session_id, id);
                CREATE INDEX IF NOT EXISTS idx_documents_project
                    ON documents(project_id, status, filename);
                """
            )

    def ensure_default_project(self) -> str:
        projects = self.list_projects()
        if projects:
            return projects[0]["id"]
        return self.create_project("Default Project")

    def create_project(self, name: str) -> str:
        project_id = str(uuid.uuid4())
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO projects (id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (project_id, name.strip() or "Untitled Project", now, now),
            )
        self.create_session(project_id, "New Chat")
        return project_id

    def list_projects(self) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM projects ORDER BY updated_at DESC, created_at DESC"
            ).fetchall()
        return [dict(row) for row in rows]

    def get_project(self, project_id: str) -> Optional[dict]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        return dict(row) if row else None

    def delete_project(self, project_id: str) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))

    def touch_project(self, project_id: str) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE projects SET updated_at = ? WHERE id = ?", (utc_now(), project_id))

    def create_session(self, project_id: str, title: str = "New Chat") -> str:
        session_id = str(uuid.uuid4())
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO chat_sessions (id, project_id, title, memory_summary, created_at, updated_at)
                VALUES (?, ?, ?, '', ?, ?)
                """,
                (session_id, project_id, title.strip() or "New Chat", now, now),
            )
            conn.execute("UPDATE projects SET updated_at = ? WHERE id = ?", (now, project_id))
        return session_id

    def list_sessions(self, project_id: str) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT s.*, COUNT(m.id) AS message_count
                FROM chat_sessions s
                LEFT JOIN chat_messages m ON m.session_id = s.id
                WHERE s.project_id = ?
                GROUP BY s.id
                ORDER BY s.updated_at DESC, s.created_at DESC
                """,
                (project_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_or_create_session(self, project_id: str, session_id: Optional[str] = None) -> str:
        if session_id:
            with self.connect() as conn:
                row = conn.execute(
                    "SELECT id FROM chat_sessions WHERE id = ? AND project_id = ?",
                    (session_id, project_id),
                ).fetchone()
            if row:
                return session_id

        sessions = self.list_sessions(project_id)
        if sessions:
            return sessions[0]["id"]
        return self.create_session(project_id, "New Chat")

    def get_session(self, session_id: str) -> Optional[dict]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM chat_sessions WHERE id = ?", (session_id,)).fetchone()
        return dict(row) if row else None

    def delete_session(self, session_id: str) -> Optional[str]:
        session = self.get_session(session_id)
        if not session:
            return None
        now = utc_now()
        with self.connect() as conn:
            conn.execute("DELETE FROM chat_sessions WHERE id = ?", (session_id,))
            conn.execute("UPDATE projects SET updated_at = ? WHERE id = ?", (now, session["project_id"]))
        return session["project_id"]

    def update_session_summary(self, session_id: str, summary: str) -> None:
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                "UPDATE chat_sessions SET memory_summary = ?, updated_at = ? WHERE id = ?",
                (summary or "", now, session_id),
            )

    def add_message(self, session_id: str, role: str, content: str, metadata: Optional[dict] = None) -> None:
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO chat_messages (session_id, role, content, metadata, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (session_id, role, content, json.dumps(metadata or {}), now),
            )
            row = conn.execute(
                "SELECT project_id, title FROM chat_sessions WHERE id = ?", (session_id,)
            ).fetchone()
            if row:
                title = row["title"]
                if role == "user" and title == "New Chat" and content.strip():
                    title = content.strip().splitlines()[0][:60]
                conn.execute(
                    "UPDATE chat_sessions SET title = ?, updated_at = ? WHERE id = ?",
                    (title, now, session_id),
                )
                conn.execute(
                    "UPDATE projects SET updated_at = ? WHERE id = ?", (now, row["project_id"])
                )

    def list_messages(self, session_id: str, limit: Optional[int] = None) -> list[dict]:
        sql = "SELECT * FROM chat_messages WHERE session_id = ? ORDER BY id"
        params: tuple = (session_id,)
        if limit:
            sql = """
                SELECT * FROM (
                    SELECT * FROM chat_messages WHERE session_id = ? ORDER BY id DESC LIMIT ?
                ) ORDER BY id
            """
            params = (session_id, limit)
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        messages = []
        for row in rows:
            item = dict(row)
            try:
                item["metadata"] = json.loads(item.get("metadata") or "{}")
            except json.JSONDecodeError:
                item["metadata"] = {}
            messages.append(item)
        return messages

    def count_messages(self, session_id: str) -> int:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS count FROM chat_messages WHERE session_id = ?", (session_id,)
            ).fetchone()
        return int(row["count"])

    def add_document(
        self,
        project_id: str,
        filename: str,
        original_path: Optional[str],
        markdown_path: str,
        document_id: Optional[str] = None,
    ) -> str:
        document_id = document_id or str(uuid.uuid4())
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO documents
                    (id, project_id, filename, original_path, markdown_path, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 'active', ?, ?)
                """,
                (document_id, project_id, filename, original_path, markdown_path, now, now),
            )
            conn.execute("UPDATE projects SET updated_at = ? WHERE id = ?", (now, project_id))
        return document_id

    def list_documents(self, project_id: str, include_deleted: bool = False) -> list[dict]:
        where = "project_id = ?" if include_deleted else "project_id = ? AND status = 'active'"
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM documents WHERE {where} ORDER BY filename, created_at",
                (project_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_document(self, document_id: str) -> Optional[dict]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
        return dict(row) if row else None

    def find_active_document_by_filename(self, project_id: str, filename: str) -> Optional[dict]:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM documents
                WHERE project_id = ? AND filename = ? AND status = 'active'
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (project_id, filename),
            ).fetchone()
        return dict(row) if row else None

    def mark_document_deleted(self, document_id: str) -> None:
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                "UPDATE documents SET status = 'deleted', updated_at = ? WHERE id = ?",
                (now, document_id),
            )

    def mark_project_documents_deleted(self, project_id: str) -> None:
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                "UPDATE documents SET status = 'deleted', updated_at = ? WHERE project_id = ? AND status = 'active'",
                (now, project_id),
            )

    def delete_documents(self, document_ids: Iterable[str]) -> None:
        ids = list(document_ids)
        if not ids:
            return
        placeholders = ",".join("?" for _ in ids)
        with self.connect() as conn:
            conn.execute(f"DELETE FROM documents WHERE id IN ({placeholders})", ids)
