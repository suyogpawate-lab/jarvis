import os

from agents.providers.openai_compatible import OpenAICompatibleAgent


class GroqAgent(OpenAICompatibleAgent):
    def __init__(self):
        super().__init__(
            name="Groq",
            api_key=os.getenv("GROQ_API_KEY"),
            base_url="https://api.groq.com/openai/v1",
            model=os.getenv(
                "GROQ_MODEL",
                "openai/gpt-oss-20b",
            ),
        )
