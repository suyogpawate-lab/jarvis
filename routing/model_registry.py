"""
JARVIS curated discussion model registry.

Only models listed here may enter a discussion room.
"""

DISCUSSION_MODELS = {

    "simple": [

        {
            "name": "Gemini Flash",
            "provider": "omniroute",
            "model": "gemini/gemini-3.7-flash",
        },

        {
            "name": "Qwen",
            "provider": "omniroute",
            "model": "cfp/qwen/qwen3-30b-a3b-fp8",
        },

        {
            "name": "Llama",
            "provider": "omniroute",
            "model": "cfp/meta-llama/llama-3.3-70b-instruct-fp8-fast",
        },

        {
            "name": "Groq",
            "provider": "groq",
            "model": "openai/gpt-oss-20b",
        },

        {
            "name": "Ollama",
            "provider": "ollama",
            "model": "qwen2.5:0.5b",
        },
    ],

    "creative": [

        {
            "name": "Claude Sonnet",
            "provider": "omniroute",
            "model": "agy/claude-sonnet-4-6",
        },

        {
            "name": "Gemini",
            "provider": "omniroute",
            "model": "gemini/gemini-3.6-flash",
        },

        {
            "name": "GPT-5.6 Luna",
            "provider": "omniroute",
            "model": "gpt-5.6-luna",
        },

        {
            "name": "Qwen",
            "provider": "omniroute",
            "model": "cfp/qwen/qwen3-30b-a3b-fp8",
        },

        {
            "name": "Kimi",
            "provider": "omniroute",
            "model": "dva/kimi-k3-max",
        },

        {
            "name": "Groq",
            "provider": "groq",
            "model": "openai/gpt-oss-20b",
        },

        {
            "name": "Ollama",
            "provider": "ollama",
            "model": "qwen2.5:0.5b",
        },
    ],

    "complex": [

        {
            "name": "Claude Opus",
            "provider": "omniroute",
            "model": "agy/claude-opus-4-6-thinking",
        },

        {
            "name": "Gemini Pro",
            "provider": "omniroute",
            "model": "gemini/gemini-3.1-pro-preview",
        },

        {
            "name": "GPT-5.6 Luna",
            "provider": "omniroute",
            "model": "gpt-5.6-luna-xhigh",
        },

        {
            "name": "Claude Sonnet",
            "provider": "omniroute",
            "model": "agy/claude-sonnet-4-6",
        },

        {
            "name": "Groq",
            "provider": "groq",
            "model": "openai/gpt-oss-20b",
        },

        {
            "name": "Ollama",
            "provider": "ollama",
            "model": "qwen2.5:0.5b",
        },
    ],
}


def get_models(category: str):
    """Return curated models for a discussion category."""
    return DISCUSSION_MODELS.get(
        category.lower().strip(),
        [],
    )


def all_models():
    """Return every curated discussion model."""
    result = []

    for category, models in DISCUSSION_MODELS.items():

        for model in models:

            item = dict(model)
            item["category"] = category
            result.append(item)

    return result
