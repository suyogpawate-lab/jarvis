import os
import re

from agents.providers.openai_compatible import OpenAICompatibleAgent


class OmniRouteAgent(OpenAICompatibleAgent):
    def __init__(self):
        super().__init__(
            name="OmniRoute",
            api_key=os.getenv("OMNIROUTE_API_KEY", "any-string"),
            base_url=os.getenv(
                "OMNIROUTE_BASE_URL",
                "http://127.0.0.1:20128/v1",
            ),
            model=os.getenv(
                "OMNIROUTE_MODEL",
                "auto",
            ),
        )
        if re.search(r"gemini|claude|anthropic|antigravity", self.model, re.IGNORECASE):
            raise RuntimeError(
                "This model ID is disabled. Choose a non-Gemini, non-Claude OmniRoute model."
            )
