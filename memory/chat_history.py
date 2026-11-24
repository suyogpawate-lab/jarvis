"""Persistent, resumable JARVIS chat sessions.

Long-term memories and episodic notes remain separate. /clear removes only
conversation transcripts and session metadata, not personal/project memories.
"""
import os
import re
import sqlite3
import threading
import time
import uuid

from memory.storage import DB_PATH


class ChatHistory:
    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path
        self._lock = threading.RLock()
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._initialize()

    def _connect(self):
        db = sqlite3.connect(self.db_path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    def _initialize(self):
        with self._lock, self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS chat_sessions (
                    code TEXT PRIMARY KEY,
                    description TEXT NOT NULL DEFAULT 'New chat',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS chat_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_code TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    FOREIGN KEY(session_code) REFERENCES chat_sessions(code)
                        ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_chat_messages_session
                    ON chat_messages(session_code, id);
                CREATE TABLE IF NOT EXISTS chat_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
            """)

    @staticmethod
    def _description(value):
        text = re.sub(r"\s+", " ", str(value or "")).strip()
        return (text[:87].rsplit(" ", 1)[0] + "...") if len(text) > 90 else (text or "New chat")

    def _active_code(self, db):
        row = db.execute("SELECT value FROM chat_state WHERE key='active_session'").fetchone()
        code = str(row["value"]) if row else ""
        exists = db.execute("SELECT 1 FROM chat_sessions WHERE code=?", (code,)).fetchone()
        return code if exists else ""

    def ensure_active(self):
        with self._lock, self._connect() as db:
            code = self._active_code(db)
            if code:
                return code
            code = "JH-" + uuid.uuid4().hex[:7].upper()
            now = time.time()
            db.execute(
                "INSERT INTO chat_sessions(code,description,created_at,updated_at) VALUES(?,?,?,?)",
                (code, "New chat", now, now),
            )
            db.execute(
                "INSERT OR REPLACE INTO chat_state(key,value) VALUES('active_session',?)",
                (code,),
            )
            return code

    @property
    def active_code(self):
        return self.ensure_active()

    def save(self, role, content):
        role = str(role or "").strip().lower()
        content = str(content or "").strip()
        if role not in {"user", "assistant", "system", "tool"} or not content:
            return None
        with self._lock, self._connect() as db:
            code = self._active_code(db)
            if not code:
                code = "JH-" + uuid.uuid4().hex[:7].upper()
                now = time.time()
                db.execute(
                    "INSERT INTO chat_sessions(code,description,created_at,updated_at) VALUES(?,?,?,?)",
                    (code, "New chat", now, now),
                )
                db.execute(
                    "INSERT OR REPLACE INTO chat_state(key,value) VALUES('active_session',?)",
                    (code,),
                )
            now = time.time()
            db.execute(
                "INSERT INTO chat_messages(session_code,role,content,created_at) VALUES(?,?,?,?)",
                (code, role, content, now),
            )
            if role == "user":
                row = db.execute("SELECT description FROM chat_sessions WHERE code=?", (code,)).fetchone()
                if not row or row["description"] == "New chat":
                    db.execute(
                        "UPDATE chat_sessions SET description=? WHERE code=?",
                        (self._description(content), code),
                    )
            db.execute("UPDATE chat_sessions SET updated_at=? WHERE code=?", (now, code))
            return code

    def list_sessions(self, limit=30):
        limit = max(1, min(int(limit), 100))
        with self._lock, self._connect() as db:
            rows = db.execute("""
                SELECT s.code, s.description, s.created_at, s.updated_at,
                       COUNT(m.id) AS message_count
                FROM chat_sessions s
                LEFT JOIN chat_messages m ON m.session_code=s.code
                GROUP BY s.code
                ORDER BY s.updated_at DESC
                LIMIT ?
            """, (limit,)).fetchall()
            return [dict(row) for row in rows]

    def messages(self, code=None, limit=30):
        limit = max(1, min(int(limit), 100))
        with self._lock, self._connect() as db:
            selected = str(code or self._active_code(db)).strip().upper()
            rows = db.execute("""
                SELECT role, content, created_at FROM chat_messages
                WHERE session_code=? ORDER BY id DESC LIMIT ?
            """, (selected, limit)).fetchall()
            return [dict(row) for row in reversed(rows)]

    def resume(self, code):
        selected = str(code or "").strip().upper()
        with self._lock, self._connect() as db:
            session = db.execute("SELECT * FROM chat_sessions WHERE code=?", (selected,)).fetchone()
            if not session:
                return None
            db.execute(
                "INSERT OR REPLACE INTO chat_state(key,value) VALUES('active_session',?)",
                (selected,),
            )
            # Rebuild the legacy context table from this session only. This keeps
            # existing MemoryManager/dispatcher consumers session-scoped.
            db.execute("DELETE FROM conversations")
            rows = db.execute("""
                SELECT role, content, created_at FROM chat_messages
                WHERE session_code=? ORDER BY id
            """, (selected,)).fetchall()
            db.executemany(
                "INSERT INTO conversations(role,content,created_at) VALUES(?,?,?)",
                [(r["role"], r["content"], r["created_at"]) for r in rows],
            )
            return dict(session)

    def new_session(self):
        with self._lock, self._connect() as db:
            code = "JH-" + uuid.uuid4().hex[:7].upper()
            now = time.time()
            db.execute(
                "INSERT INTO chat_sessions(code,description,created_at,updated_at) VALUES(?,?,?,?)",
                (code, "New chat", now, now),
            )
            db.execute(
                "INSERT OR REPLACE INTO chat_state(key,value) VALUES('active_session',?)",
                (code,),
            )
            db.execute("DELETE FROM conversations")
            return code

    def clear(self):
        with self._lock, self._connect() as db:
            count = db.execute("SELECT COUNT(*) FROM chat_messages").fetchone()[0]
            db.execute("DELETE FROM chat_messages")
            db.execute("DELETE FROM chat_sessions")
            db.execute("DELETE FROM chat_state")
            # Remove legacy transcript rows, but preserve memories and episodes.
            db.execute("DELETE FROM conversations")
        # The web panel maintains a second transcript file; clear that too.
        if os.path.abspath(self.db_path) == os.path.abspath(DB_PATH):
            try:
                import jarvis_web
                jarvis_web._hist_clear()
            except Exception:
                web_history = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "web_chat.json")
                try:
                    os.remove(web_history)
                except OSError:
                    pass
        return int(count)
