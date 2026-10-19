import os

from openai import OpenAI

from agents.providers.openai_compatible import OpenAICompatibleAgent


def _groq_api_keys():
    """Load the plural key list, falling back to the legacy singular variable."""
    raw = os.getenv("GROQ_API_KEYS", "")
    keys = [
        item.strip()
        for item in raw.replace("\\n", ",").replace(",", " ").split()
        if item.strip()
    ]

    if not keys:
        single = os.getenv("GROQ_API_KEY", "").strip()
        if single:
            keys = [single]

    return keys


class GroqAgent(OpenAICompatibleAgent):
    def __init__(self):
        self.api_keys = _groq_api_keys()
        self.current_key_index = 0

        # The base class validates configuration and initializes the first client.
        super().__init__(
            name="Groq",
            api_key=self.api_keys[0] if self.api_keys else None,
            base_url="https://api.groq.com/openai/v1",
            model=os.getenv("GROQ_MODEL", "openai/gpt-oss-20b"),
        )

    def ask(self, prompt: str) -> str:
        """Try configured keys in order, advancing when a key/request fails."""
        last_error = None
        total = len(self.api_keys)

        for offset in range(total):
            index = (self.current_key_index + offset) % total
            try:
                self.client = OpenAI(
                    api_key=self.api_keys[index],
                    base_url="https://api.groq.com/openai/v1",
                )
                answer = super().ask(prompt)
                self.current_key_index = index
                return answer
            except Exception as exc:
                last_error = exc

        if last_error is not None:
            self.current_key_index = (self.current_key_index + 1) % total
            raise last_error

        raise RuntimeError("No Groq API keys are configured.")
