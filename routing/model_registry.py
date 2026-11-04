"""
JARVIS curated discussion model registry.

Only models listed here may enter a discussion room.
"""

DISCUSSION_MODELS = {

    "simple": [

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
    ],

    "creative": [

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
    ],

    "complex": [

        {
            "name": "GPT-5.6 Luna",
            "provider": "omniroute",
            "model": "gpt-5.6-luna-xhigh",
        },

        {
            "name": "Groq",
            "provider": "groq",
            "model": "openai/gpt-oss-20b",
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
