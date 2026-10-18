"""
JARVIS MEMORY MANAGER

Memory layers:
    personal     -> user-specific long-term facts
    semantic     -> project / technical knowledge
    episodic     -> completed events and discussions
    conversation -> recent conversation history

This module contains only orchestration.
SQLite/database operations remain inside MemoryStorage.
"""

from .storage import MemoryStorage


class MemoryManager:

    def __init__(self):
        self.storage = MemoryStorage()

    # ==========================================================
    # GENERIC REMEMBER API
    # ==========================================================

    def remember(self, content, kind="personal", importance=7):
        """
        Generic memory API.

        kind:
            personal
            project
            semantic
        """

        content = str(content or "").strip()

        if not content:
            return None

        kind = str(kind or "personal").lower().strip()

        if kind == "personal":
            return self.remember_personal(
                content,
                importance=importance,
            )

        if kind in {"project", "semantic"}:
            return self.remember_project(
                content,
                importance=importance,
            )

        raise ValueError(
            f"Unknown memory kind: {kind}"
        )

    # ==========================================================
    # PERSONAL MEMORY
    # ==========================================================

    def remember_personal(
        self,
        content,
        importance=8,
    ):
        content = str(content or "").strip()

        if not content:
            return None

        return self.storage.add_memory(
            memory_type="personal",
            content=content,
            importance=importance,
            source="personal",
        )

    def personal(self, limit=20):
        return self.storage.search_memories(
            memory_type="personal",
            limit=limit,
        )

    # ==========================================================
    # PROJECT MEMORY
    # ==========================================================

    def remember_project(
        self,
        content,
        importance=7,
    ):
        content = str(content or "").strip()

        if not content:
            return None

        return self.storage.add_memory(
            memory_type="semantic",
            content=content,
            importance=importance,
            source="project",
        )

    def project(self, limit=20):
        return self.storage.search_memories(
            memory_type="semantic",
            limit=limit,
        )

    # ==========================================================
    # EPISODIC MEMORY
    # ==========================================================

    def remember_episode(
        self,
        topic,
        summary,
        details="",
    ):
        topic = str(topic or "").strip()
        summary = str(summary or "").strip()
        details = str(details or "").strip()

        if not topic and not summary:
            return None

        return self.storage.add_episode(
            topic=topic,
            summary=summary,
            details=details,
        )

    def recent_episodes(self, limit=10):
        return self.storage.recent_episodes(
            limit=limit,
        )

    # ==========================================================
    # CONVERSATION MEMORY
    # ==========================================================

    def remember_message(
        self,
        role,
        content,
    ):
        role = str(role or "").strip()
        content = str(content or "").strip()

        if not content:
            return None

        return self.storage.add_conversation(
            role=role,
            content=content,
        )

    def recent_conversation(self, limit=12):
        return self.storage.recent_conversations(
            limit=limit,
        )

    # ==========================================================
    # SEARCH
    # ==========================================================

    def search(
        self,
        query,
        limit=10,
    ):
        query = str(query or "").strip()

        if not query:
            return []

        return self.storage.search_memories(
            query=query,
            limit=limit,
        )

    # ==========================================================
    # MEMORY CONTEXT
    # ==========================================================

    def build_context(
        self,
        query,
        max_personal=8,
        max_project=8,
        max_episodes=6,
        max_conversation=10,
    ):
        query = str(query or "").strip()

        personal = self.personal(
            limit=max_personal,
        )

        project = self.storage.search_memories(
            query=query,
            memory_type="semantic",
            limit=max_project,
        )

        if not project:
            project = self.project(
                limit=max_project,
            )

        episodes = self.recent_episodes(
            limit=max_episodes,
        )

        conversation = self.recent_conversation(
            limit=max_conversation,
        )

        sections = []

        # ------------------------------------------------------
        # PERSONAL
        # ------------------------------------------------------

        if personal:
            lines = []

            for item in personal:
                content = str(
                    item.get("content", "")
                ).strip()

                if content:
                    lines.append(
                        f"- {content}"
                    )

            if lines:
                sections.append(
                    "PERSONAL MEMORY:\n"
                    + "\n".join(lines)
                )

        # ------------------------------------------------------
        # PROJECT
        # ------------------------------------------------------

        if project:
            lines = []

            for item in project:
                content = str(
                    item.get("content", "")
                ).strip()

                if content:
                    lines.append(
                        f"- {content}"
                    )

            if lines:
                sections.append(
                    "PROJECT / SEMANTIC MEMORY:\n"
                    + "\n".join(lines)
                )

        # ------------------------------------------------------
        # EPISODES
        # ------------------------------------------------------

        if episodes:
            lines = []

            for item in episodes:

                topic = str(
                    item.get("topic", "")
                ).strip()

                summary = str(
                    item.get("summary", "")
                ).strip()

                if topic or summary:
                    lines.append(
                        f"- {topic}: {summary}"
                    )

            if lines:
                sections.append(
                    "RECENT EPISODIC MEMORY:\n"
                    + "\n".join(lines)
                )

        # ------------------------------------------------------
        # CONVERSATION
        # ------------------------------------------------------

        if conversation:
            lines = []

            for item in conversation:

                role = str(
                    item.get("role", "unknown")
                ).upper()

                content = str(
                    item.get("content", "")
                ).strip()

                if content:
                    lines.append(
                        f"{role}: {content}"
                    )

            if lines:
                sections.append(
                    "RECENT CONVERSATION:\n"
                    + "\n".join(lines)
                )

        if not sections:
            return "(No relevant memory found.)"

        return "\n\n".join(sections)

    # ==========================================================
    # DISCUSSION MEMORY
    # ==========================================================

    def save_discussion(
        self,
        topic,
        transcript,
        final_answer,
    ):
        successful = [
            item
            for item in transcript
            if (
                isinstance(item, dict)
                and item.get("content")
                and item.get("status", "SUCCESS")
                == "SUCCESS"
            )
        ]

        if not successful:
            return None

        summary_parts = []

        for item in successful[:8]:

            name = str(
                item.get("name", "Agent")
            ).strip()

            content = str(
                item.get("content", "")
            ).strip()

            if content:
                summary_parts.append(
                    f"{name}: {content}"
                )

        details = "\n\n".join(
            summary_parts
        )

        summary = str(
            final_answer or ""
        ).strip()

        if len(summary) > 1200:
            summary = (
                summary[:1200]
                .rsplit(" ", 1)[0]
                + "..."
            )

        return self.remember_episode(
            topic=topic,
            summary=summary,
            details=details,
        )
