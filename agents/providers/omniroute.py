import os

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
                os.getenv(
                    "OMNIROUTE_GENERAL_MODEL",
                    "cfp/deepseek-ai/deepseek-v4-pro-0813",
                ),
            ),
        )
