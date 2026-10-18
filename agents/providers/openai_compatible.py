from openai import OpenAI

from agents.base import BaseAgent


class OpenAICompatibleAgent(BaseAgent):
    def __init__(
        self,
        name,
        api_key,
        base_url,
        model,
    ):
        super().__init__(name)

        if not api_key:
            raise RuntimeError(f"{name} API key is not set")

        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url,
        )

        self.model = model

    def ask(self, prompt: str) -> str:
        response = self.client.responses.create(
            model=self.model,
            input=prompt,
        )

        return response.output_text.strip()
