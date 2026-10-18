"""
JARVIS MEMORY INTENT ENGINE

Conservative long-term memory detection.

Long-term memory is saved only when:
1. The user explicitly asks JARVIS to remember/save/store something, or
2. The message contains a strong, unambiguous personal preference/future
   instruction, or
3. The user explicitly identifies something as project memory.

Ordinary questions, commands, project discussions, and mentions of
Jarvis/OmniRoute/etc. are NOT automatically stored as long-term memory.
"""

from __future__ import annotations

import re


# ==============================================================
# EXPLICIT MEMORY REQUESTS
# ==============================================================

EXPLICIT_PERSONAL = (
    r"\bremember that\b",
    r"\bremember this\b",
    r"\bdon't forget that\b",
    r"\bdo not forget that\b",
    r"\bkeep this in mind\b",
    r"\bkeep in mind that\b",
    r"\bsave this\b",
    r"\bstore this\b",
    r"\bnote that\b",
)

EXPLICIT_PROJECT = (
    r"\bremember this as a project\b",
    r"\bsave this as a project\b",
    r"\bstore this as project memory\b",
    r"\bremember this for the project\b",
    r"\bsave this for the project\b",
    r"\bstore this for the project\b",
)


# ==============================================================
# STRONG PERSONAL MEMORY SIGNALS
# ==============================================================

PERSONAL_PATTERNS = (
    r"\bi prefer\b",
    r"\bi like\b",
    r"\bi dislike\b",
    r"\bi don't like\b",
    r"\bmy preference is\b",
    r"\bmy favorite\b",
    r"\bfrom now on\b",
    r"\bgoing forward\b",
)


# ==============================================================
# THINGS THAT ARE QUESTIONS / OPERATIONS
# ==============================================================

QUESTION_PATTERNS = (
    r"^what\b",
    r"^who\b",
    r"^where\b",
    r"^when\b",
    r"^why\b",
    r"^how\b",
    r"^can you\b",
    r"^could you\b",
    r"^would you\b",
    r"^is\b",
    r"^are\b",
    r"^do\b",
    r"^does\b",
    r"^did\b",
)

OPERATION_PATTERNS = (
    r"\bsend\b",
    r"\bmessage\b",
    r"\bemail\b",
    r"\bwhatsapp\b",
    r"\bsms\b",
    r"\blaunch\b",
    r"\bopen\b",
    r"\bexecute\b",
    r"\brun\b",
    r"\bstart\b",
    r"\bstop\b",
    r"\bkill\b",
    r"\bcheck\b",
    r"\binspect\b",
    r"\bread\b",
    r"\bsearch\b",
    r"\bshow\b",
    r"\blist\b",
    r"\bdownload\b",
    r"\bupload\b",
    r"\binstall\b",
    r"\buninstall\b",
    r"\bdelete\b",
    r"\bcreate\b",
    r"\bremove\b",
    r"\brestart\b",
)


def _matches(patterns, text):
    return any(
        re.search(pattern, text, re.IGNORECASE)
        for pattern in patterns
    )


def _clean(text):
    text = str(text or "").strip()

    text = re.sub(
        r"\s+",
        " ",
        text,
    )

    return text.strip()


def _remove_memory_prefix(text):
    patterns = (
        r"^\s*(?:please\s+)?remember\s+(?:that\s+)?",
        r"^\s*(?:please\s+)?don't\s+forget\s+(?:that\s+)?",
        r"^\s*(?:please\s+)?do\s+not\s+forget\s+(?:that\s+)?",
        r"^\s*(?:please\s+)?keep\s+(?:this\s+)?in\s+mind\s*:?\s*",
        r"^\s*(?:please\s+)?save\s+(?:this\s+)?(?:fact\s*:?\s*)?",
        r"^\s*(?:please\s+)?store\s+(?:this\s+)?(?:fact\s*:?\s*)?",
        r"^\s*(?:please\s+)?note\s+that\s+",
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


def _remove_project_prefix(text):
    patterns = (
        r"^\s*(?:please\s+)?remember\s+this\s+as\s+a\s+project\s*:?\s*",
        r"^\s*(?:please\s+)?save\s+this\s+as\s+a\s+project\s*:?\s*",
        r"^\s*(?:please\s+)?store\s+this\s+as\s+project\s+memory\s*:?\s*",
        r"^\s*(?:please\s+)?remember\s+this\s+for\s+the\s+project\s*:?\s*",
        r"^\s*(?:please\s+)?save\s+this\s+for\s+the\s+project\s*:?\s*",
        r"^\s*(?:please\s+)?store\s+this\s+for\s+the\s+project\s*:?\s*",
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


def _looks_like_question(text):
    lower = text.lower().strip()

    if lower.endswith("?"):
        return True

    return _matches(
        QUESTION_PATTERNS,
        lower,
    )


def _looks_like_operation(text):
    return _matches(
        OPERATION_PATTERNS,
        text.lower(),
    )


class MemoryIntent:

    @classmethod
    def classify(cls, text):
        """
        Return:

            personal
            project
            none
        """

        text = _clean(text)

        if not text:
            return "none"

        lower = text.lower()

        # ------------------------------------------------------
        # Explicit project memory has highest priority.
        # ------------------------------------------------------

        if _matches(EXPLICIT_PROJECT, lower):
            return "project"

        # ------------------------------------------------------
        # Explicit personal memory.
        # ------------------------------------------------------

        if _matches(EXPLICIT_PERSONAL, lower):
            return "personal"

        # ------------------------------------------------------
        # Questions are never automatic long-term memory.
        # ------------------------------------------------------

        if _looks_like_question(text):
            return "none"

        # ------------------------------------------------------
        # Operational requests are never long-term memory.
        # ------------------------------------------------------

        if _looks_like_operation(text):
            return "none"

        # ------------------------------------------------------
        # Strong personal preference / future-policy statements.
        # ------------------------------------------------------

        if _matches(PERSONAL_PATTERNS, lower):
            return "personal"

        # ------------------------------------------------------
        # Everything else is not long-term memory.
        # ------------------------------------------------------

        return "none"

    @classmethod
    def extract(cls, text):
        text = _clean(text)

        if not text:
            return ""

        # Explicit project request.
        if _matches(EXPLICIT_PROJECT, text):
            return _remove_project_prefix(text)

        # Explicit personal request.
        return _remove_memory_prefix(text)

    @classmethod
    def detect(cls, text):
        kind = cls.classify(text)

        if kind == "none":
            return {
                "kind": "none",
                "content": "",
            }

        content = cls.extract(text)

        if len(content) < 4:
            return {
                "kind": "none",
                "content": "",
            }

        return {
            "kind": kind,
            "content": content,
        }
