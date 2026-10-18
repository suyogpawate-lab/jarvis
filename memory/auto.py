"""
JARVIS AUTOMATIC MEMORY DETECTOR

This intentionally uses deterministic rules.

It does NOT send every user message to an LLM.
It does NOT save ordinary questions.
It only detects strong memory signals.
"""

from __future__ import annotations

import re


# ==============================================================
# EXPLICIT MEMORY SIGNALS
# ==============================================================

EXPLICIT_PERSONAL = (
    "remember that",
    "remember this",
    "don't forget that",
    "do not forget that",
    "keep this in mind",
    "keep in mind that",
)

PERSONAL_PATTERNS = (
    r"\bi prefer\b",
    r"\bi like\b",
    r"\bi dislike\b",
    r"\bi don't like\b",
    r"\bi use\b",
    r"\bmy preference is\b",
    r"\bmy favorite\b",
    r"\bfrom now on\b",
    r"\bgoing forward\b",
)

PROJECT_PATTERNS = (
    r"\bi am building\b",
    r"\bi'm building\b",
    r"\bi am working on\b",
    r"\bi'm working on\b",
    r"\bwe are building\b",
    r"\bwe're building\b",
    r"\bwe are working on\b",
    r"\bwe're working on\b",
    r"\bthe project\b",
    r"\bthis project\b",
    r"\bthe jarvis project\b",
    r"\bwe decided\b",
    r"\bwe chose\b",
    r"\bwe will use\b",
    r"\bwe're using\b",
    r"\bwe are using\b",
)

# Things that should generally NOT become memories.
IGNORE_PATTERNS = (
    r"^what is\b",
    r"^who is\b",
    r"^where is\b",
    r"^when is\b",
    r"^why is\b",
    r"^how is\b",
    r"^how do\b",
    r"^how can\b",
    r"^can you explain\b",
    r"^explain\b",
    r"^calculate\b",
    r"^solve\b",
)


def _clean(text: str) -> str:
    text = str(text or "").strip()

    # Remove repeated whitespace.
    text = re.sub(
        r"\s+",
        " ",
        text,
    )

    return text.strip()


def _remove_memory_prefix(text: str) -> str:

    patterns = (
        r"^\s*remember\s+that\s+",
        r"^\s*remember\s+",
        r"^\s*don't\s+forget\s+that\s+",
        r"^\s*do\s+not\s+forget\s+that\s+",
        r"^\s*keep\s+this\s+in\s+mind\s*:?\s*",
        r"^\s*keep\s+in\s+mind\s+that\s+",
    )

    result = text

    for pattern in patterns:

        result = re.sub(
            pattern,
            "",
            result,
            flags=re.IGNORECASE,
        )

    return result.strip()


def _looks_like_question(text: str) -> bool:

    lower = text.lower().strip()

    if lower.endswith("?"):
        return True

    return any(
        re.search(pattern, lower)
        for pattern in IGNORE_PATTERNS
    )


def detect_memory(text: str):
    """
    Return:

        {
            "type": "personal" | "project",
            "content": "...",
            "importance": 1-10
        }

    or None.
    """

    text = _clean(text)

    if not text:
        return None

    lower = text.lower()

    # ----------------------------------------------------------
    # Explicit "remember" has highest priority.
    # ----------------------------------------------------------

    if any(
        phrase in lower
        for phrase in EXPLICIT_PERSONAL
    ):

        content = _remove_memory_prefix(text)

        if len(content) >= 4:
            return {
                "type": "personal",
                "content": content,
                "importance": 9,
            }

    # ----------------------------------------------------------
    # Explicit project statements.
    # ----------------------------------------------------------

    if re.search(
        r"^\s*(remember|save|store)\s+(?:this\s+)?"
        r"(?:as\s+)?(?:a\s+)?project",
        lower,
    ):

        content = re.sub(
            r"^\s*(remember|save|store)\s+"
            r"(?:this\s+)?(?:as\s+)?(?:a\s+)?project\s*:?\s*",
            "",
            text,
            flags=re.IGNORECASE,
        ).strip()

        if len(content) >= 4:
            return {
                "type": "project",
                "content": content,
                "importance": 9,
            }

    # ----------------------------------------------------------
    # Don't automatically memorize obvious questions.
    # ----------------------------------------------------------

    if _looks_like_question(text):
        return None

    # ----------------------------------------------------------
    # Strong project signals.
    # ----------------------------------------------------------

    if any(
        re.search(pattern, lower)
        for pattern in PROJECT_PATTERNS
    ):

        return {
            "type": "project",
            "content": text,
            "importance": 8,
        }

    # ----------------------------------------------------------
    # Strong personal signals.
    # ----------------------------------------------------------

    if any(
        re.search(pattern, lower)
        for pattern in PERSONAL_PATTERNS
    ):

        return {
            "type": "personal",
            "content": text,
            "importance": 8,
        }

    return None
