"""Compact, curated model registry for JARVIS routing.

Complex tasks use models exposed through the local OmniRoute gateway. Model IDs
can be overridden through environment variables when the gateway's catalog
changes; no direct Gemini or Anthropic API keys are needed for these routes.
"""
import os


# Known OmniRoute model IDs already used by the project. Keep the default
# catalog small to reduce configuration and memory overhead.
OMNIROUTE_PROFILES = {
    "coding": {
        "name": "OmniRoute Qwen Coding",
        "provider": "omniroute",
        "model": os.getenv(
            "OMNIROUTE_CODING_MODEL",
            "cfp/qwen/qwen3-30b-a3b-fp8",
        ),
    },
    "smart": {
        "name": "OmniRoute Smart Reasoning",
        "provider": "omniroute",
        "model": os.getenv(
            "OMNIROUTE_SMART_MODEL",
            "gpt-5.6-luna-xhigh",
        ),
    },
}

DISCUSSION_MODELS = {
    "simple": [
        {"name": "Groq", "provider": "groq", "model": "openai/gpt-oss-20b"},
        {"name": "Ollama", "provider": "ollama", "model": "qwen2.5:0.5b"},
    ],
    "creative": [
        dict(OMNIROUTE_PROFILES["smart"]),
        dict(OMNIROUTE_PROFILES["coding"]),
        {"name": "Groq", "provider": "groq", "model": "openai/gpt-oss-20b"},
        {"name": "Ollama", "provider": "ollama", "model": "qwen2.5:0.5b"},
    ],
    "complex": [
        dict(OMNIROUTE_PROFILES["coding"]),
        dict(OMNIROUTE_PROFILES["smart"]),
        {"name": "Groq", "provider": "groq", "model": "openai/gpt-oss-20b"},
        {"name": "Ollama", "provider": "ollama", "model": "qwen2.5:0.5b"},
    ],
}


def get_complex_profile(task: str) -> dict:
    """Choose a coding-specialist or general reasoning model for a task."""
    text = str(task or "").lower()
    coding_terms = (
        "code", "coding", "program", "python", "javascript", "typescript",
        "node", "npm", "pip", "function", "class ", "refactor", "bug",
        "exception", "traceback", "stack trace", "repository", "repo", "git",
        "compile", "implementation", "script", "debug", "test suite",
    )
    key = "coding" if any(term in text for term in coding_terms) else "smart"
    return dict(OMNIROUTE_PROFILES[key])


def get_models(category: str):
    """Return curated models for a discussion category."""
    return DISCUSSION_MODELS.get(str(category).lower().strip(), [])


def all_models():
    """Return every curated discussion model, tagged by category."""
    result = []
    for category, models in DISCUSSION_MODELS.items():
        for model in models:
            item = dict(model)
            item["category"] = category
            result.append(item)
    return result
