"""Shared Groq API-key parsing for every JARVIS provider path.

Accept comma, semicolon, whitespace, and escaped/newline-separated lists.
The legacy singular variable is merged with the plural pool; duplicates are
removed while preserving configured order. Never log or expose key values.
"""
from __future__ import annotations

import os
import re


def get_groq_api_keys(environ=None):
    env = os.environ if environ is None else environ
    keys = []
    seen = set()
    for variable in ("GROQ_API_KEY", "GROQ_API_KEYS"):
        raw = str(env.get(variable, "") or "").replace("\\n", "\n")
        for item in re.split(r"[,;\\s]+", raw):
            key = item.strip()
            if key and key not in seen:
                seen.add(key)
                keys.append(key)
    return keys
