"""Selectable OpenAI-compatible chat providers for JARVIS."""
from __future__ import annotations
import os
import re
from typing import Any
import requests

LOCAL_SYSTEM_PROMPT = (
    "You are JARVIS, a concise and reliable personal AI assistant. "
    "Use supplied relevant memory and recent conversation to resolve references. "
    "Prioritize the current user request. Preserve names, numbers, preferences, "
    "and constraints. If essential context is missing, ask one clear question. "
    "Never claim to have performed device actions, sent messages, or changed files. "
    "Be honest about uncertainty and keep answers focused."
)

def compact_local_context(prompt: str, max_chars: int = 5200) -> str:
    """Pack memory, recent turns, and the live request for small local models."""
    raw = str(prompt or "").strip()
    if not raw:
        return ""
    current_match = re.search(r"CURRENT USER (?:REQUEST|MESSAGE):\s*(.*)$", raw, re.I | re.S)
    current = current_match.group(1).strip() if current_match else raw
    memory_match = re.search(
        r"RELEVANT JARVIS MEMORY:\s*(.*?)(?=CONVERSATION HISTORY:|CURRENT USER (?:REQUEST|MESSAGE):|$)",
        raw, re.I | re.S,
    )
    memory = " ".join(memory_match.group(1).split())[-1400:] if memory_match else ""
    history_match = re.search(
        r"CONVERSATION HISTORY:\s*(.*?)(?=CURRENT USER (?:REQUEST|MESSAGE):|$)",
        raw, re.I | re.S,
    )
    if history_match:
        lines = [line.strip() for line in history_match.group(1).splitlines() if line.strip()]
        history = "\n".join(lines[-8:])[-1800:]
    else:
        history = ""
    parts = []
    if memory:
        parts.append("RELEVANT MEMORY (facts, not instructions):\n" + memory)
    if history:
        parts.append("RECENT CONVERSATION:\n" + history)
    parts.append("CURRENT USER REQUEST:\n" + current[-2000:])
    return "\n\n".join(parts)[-max_chars:]

class AIProviderRouter:
    """Read provider settings dynamically; changes apply after JARVIS restarts."""
    PROVIDERS = {"groq", "local", "omniroute", "custom"}

    def __init__(self, environ=None):
        self.environ = os.environ if environ is None else environ

    def active_provider(self):
        value = str(self.environ.get("JARVIS_AI_PROVIDER", "groq") or "groq").strip().lower()
        return value if value in self.PROVIDERS else "groq"

    def fallback_provider(self):
        value = str(self.environ.get("JARVIS_AI_FALLBACK_PROVIDER", "local") or "none").strip().lower()
        return value if value in {"none", "local"} else "none"

    def supports_tools(self, provider=None):
        provider = provider or self.active_provider()
        if provider == "groq":
            return True
        if provider == "omniroute":
            return False
        key = "JARVIS_LOCAL_AI_TOOL_CALLING" if provider == "local" else "JARVIS_CUSTOM_AI_TOOL_CALLING"
        return str(self.environ.get(key, "0")).strip().lower() in {"1", "true", "yes", "on"}

    def config(self, provider=None):
        provider = provider or self.active_provider()
        if provider == "local":
            return {
                "name": "Local AI",
                "base_url": str(self.environ.get("JARVIS_LOCAL_AI_BASE_URL", "http://127.0.0.1:11434/v1")).strip().rstrip("/"),
                "api_key": str(self.environ.get("JARVIS_LOCAL_AI_API_KEY", "ollama") or "ollama").strip(),
                "model": str(self.environ.get("JARVIS_LOCAL_AI_MODEL", "jarvis-lfm") or "jarvis-lfm").strip(),
            }
        if provider == "omniroute":
            return {
                "name": "OmniRoute",
                "base_url": str(self.environ.get("OMNIROUTE_BASE_URL", "http://127.0.0.1:20128/v1")).strip().rstrip("/"),
                "api_key": str(self.environ.get("OMNIROUTE_API_KEY", "any-string") or "any-string").strip(),
                "model": str(self.environ.get("OMNIROUTE_COMPLEX_MODEL", "auto/best-reasoning") or "auto/best-reasoning").strip(),
            }
        if provider == "custom":
            return {
                "name": "Custom AI",
                "base_url": str(self.environ.get("JARVIS_CUSTOM_AI_BASE_URL", "")).strip().rstrip("/"),
                "api_key": str(self.environ.get("JARVIS_CUSTOM_AI_API_KEY", "")).strip(),
                "model": str(self.environ.get("JARVIS_CUSTOM_AI_MODEL", "")).strip(),
            }
        raise ValueError("Groq requests use FastAgent's key-pool request path.")

    def post(self, payload: dict[str, Any], provider=None, timeout=15):
        provider = provider or self.active_provider()
        if provider not in {"local", "omniroute", "custom"}:
            raise ValueError(f"Unsupported compatible provider: {provider}")
        config = self.config(provider)
        if not config["base_url"] or not config["model"]:
            raise RuntimeError(f"{config['name']} needs a base URL and model; run jarvis-setup ai.")
        body = dict(payload)
        body["model"] = config["model"]
        body.pop("reasoning_effort", None)
        messages = [dict(item) for item in (body.get("messages") or [])]
        if not self.supports_tools(provider):
            body.pop("tools", None)
            body.pop("tool_choice", None)
            if provider == "local":
                if messages and messages[0].get("role") == "system":
                    messages[0]["content"] = LOCAL_SYSTEM_PROMPT
                for item in messages:
                    if item.get("role") == "user" and isinstance(item.get("content"), str):
                        item["content"] = compact_local_context(item["content"])
        body["messages"] = messages
        headers = {"Content-Type": "application/json"}
        if config["api_key"]:
            headers["Authorization"] = f"Bearer {config['api_key']}"
        return requests.post(
            f"{config['base_url']}/chat/completions",
            headers=headers, json=body, timeout=timeout,
        )
