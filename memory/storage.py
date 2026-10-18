import os
import sqlite3
import threading
import time


BASE_DIR = os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)

MEMORY_DIR = os.path.join(
    BASE_DIR,
    "data",
    "memory",
)

DB_PATH = os.path.join(
    MEMORY_DIR,
    "jarvis_memory.db",
)


class MemoryStorage:

    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path
        self._lock = threading.RLock()

        os.makedirs(
            os.path.dirname(self.db_path),
            exist_ok=True,
        )

        self._initialize()

    def _connect(self):
        connection = sqlite3.connect(
            self.db_path,
            timeout=10,
        )

        connection.row_factory = sqlite3.Row

        return connection

    def _initialize(self):

        with self._lock:

            connection = self._connect()

            try:

                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS memories (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        memory_type TEXT NOT NULL,
                        content TEXT NOT NULL,
                        importance INTEGER NOT NULL DEFAULT 5,
                        source TEXT,
                        created_at REAL NOT NULL,
                        updated_at REAL NOT NULL
                    );

                    CREATE INDEX IF NOT EXISTS
                    idx_memories_type
                    ON memories(memory_type);

                    CREATE INDEX IF NOT EXISTS
                    idx_memories_created
                    ON memories(created_at);

                    CREATE TABLE IF NOT EXISTS episodes (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        topic TEXT NOT NULL,
                        summary TEXT NOT NULL,
                        details TEXT,
                        created_at REAL NOT NULL
                    );

                    CREATE INDEX IF NOT EXISTS
                    idx_episodes_created
                    ON episodes(created_at);

                    CREATE TABLE IF NOT EXISTS conversations (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        role TEXT NOT NULL,
                        content TEXT NOT NULL,
                        created_at REAL NOT NULL
                    );

                    CREATE INDEX IF NOT EXISTS
                    idx_conversations_created
                    ON conversations(created_at);
                    """
                )

                connection.commit()

            finally:
                connection.close()

    # ----------------------------------------------------------
    # GENERIC MEMORY
    # ----------------------------------------------------------

    def add_memory(
        self,
        memory_type,
        content,
        importance=5,
        source="jarvis",
    ):

        content = str(content).strip()

        if not content:
            return None

        now = time.time()

        with self._lock:

            connection = self._connect()

            try:

                cursor = connection.execute(
                    """
                    INSERT INTO memories
                    (
                        memory_type,
                        content,
                        importance,
                        source,
                        created_at,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        memory_type,
                        content,
                        int(importance),
                        source,
                        now,
                        now,
                    ),
                )

                connection.commit()

                return cursor.lastrowid

            finally:
                connection.close()

    def search_memories(
        self,
        query="",
        memory_type=None,
        limit=10,
    ):

        query = str(query or "").strip()
        limit = max(1, min(int(limit), 100))

        with self._lock:

            connection = self._connect()

            try:

                if query:

                    pattern = f"%{query}%"

                    if memory_type:

                        rows = connection.execute(
                            """
                            SELECT *
                            FROM memories
                            WHERE memory_type = ?
                              AND content LIKE ?
                            ORDER BY
                                importance DESC,
                                updated_at DESC
                            LIMIT ?
                            """,
                            (
                                memory_type,
                                pattern,
                                limit,
                            ),
                        ).fetchall()

                    else:

                        rows = connection.execute(
                            """
                            SELECT *
                            FROM memories
                            WHERE content LIKE ?
                            ORDER BY
                                importance DESC,
                                updated_at DESC
                            LIMIT ?
                            """,
                            (
                                pattern,
                                limit,
                            ),
                        ).fetchall()

                else:

                    if memory_type:

                        rows = connection.execute(
                            """
                            SELECT *
                            FROM memories
                            WHERE memory_type = ?
                            ORDER BY
                                importance DESC,
                                updated_at DESC
                            LIMIT ?
                            """,
                            (
                                memory_type,
                                limit,
                            ),
                        ).fetchall()

                    else:

                        rows = connection.execute(
                            """
                            SELECT *
                            FROM memories
                            ORDER BY
                                importance DESC,
                                updated_at DESC
                            LIMIT ?
                            """,
                            (limit,),
                        ).fetchall()

                return [dict(row) for row in rows]

            finally:
                connection.close()

    # ----------------------------------------------------------
    # EPISODES
    # ----------------------------------------------------------

    def add_episode(
        self,
        topic,
        summary,
        details="",
    ):

        topic = str(topic).strip()
        summary = str(summary).strip()
        details = str(details or "").strip()

        if not topic or not summary:
            return None

        with self._lock:

            connection = self._connect()

            try:

                cursor = connection.execute(
                    """
                    INSERT INTO episodes
                    (
                        topic,
                        summary,
                        details,
                        created_at
                    )
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        topic,
                        summary,
                        details,
                        time.time(),
                    ),
                )

                connection.commit()

                return cursor.lastrowid

            finally:
                connection.close()

    def recent_episodes(self, limit=10):

        limit = max(1, min(int(limit), 100))

        with self._lock:

            connection = self._connect()

            try:

                rows = connection.execute(
                    """
                    SELECT *
                    FROM episodes
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()

                return [dict(row) for row in rows]

            finally:
                connection.close()

    # ----------------------------------------------------------
    # CONVERSATIONS
    # ----------------------------------------------------------

    def add_conversation(
        self,
        role,
        content,
    ):

        content = str(content).strip()

        if not content:
            return None

        with self._lock:

            connection = self._connect()

            try:

                cursor = connection.execute(
                    """
                    INSERT INTO conversations
                    (
                        role,
                        content,
                        created_at
                    )
                    VALUES (?, ?, ?)
                    """,
                    (
                        role,
                        content,
                        time.time(),
                    ),
                )

                connection.commit()

                return cursor.lastrowid

            finally:
                connection.close()

    def recent_conversations(self, limit=12):

        limit = max(1, min(int(limit), 100))

        with self._lock:

            connection = self._connect()

            try:

                rows = connection.execute(
                    """
                    SELECT *
                    FROM conversations
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()

                rows = list(reversed(rows))

                return [dict(row) for row in rows]

            finally:
                connection.close()
