import os

from agents.providers.openai_compatible import OpenAICompatibleAgent


def _groq_api_key():
    """Match FastAgent's GROQ_API_KEYS / GROQ_API_KEY configuration."""
    raw = os.getenv("GROQ_API_KEYS") or os.getenv("GROQ_API_KEY", "")
    keys = [
        key.strip()
        for key in raw.replace("\n", ",").replace(" ", ",").split(",")
        if key.strip()
    ]
    return keys[0] if keys else None


class GroqAgent(OpenAICompatibleAgent):
    def __init__(self):
        super().__init__(
            name="Groq",
            api_key=_groq_api_key(),
            base_url="https://api.groq.com/openai/v1",
            model=os.getenv(
                "GROQ_MODEL",
                "openai/gpt-oss-20b",
            ),
        )
