import requests

from agents.base import BaseAgent


class OllamaAgent(BaseAgent):
    def __init__(
        self,
        model: str = "qwen2.5:0.5b",
        host: str = "http://127.0.0.1:11434",
    ):
        super().__init__("Ollama")
        self.model = model
        self.host = host

    def ask(self, prompt: str) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
            "think": False,
            "stream": False,
            "options": {
                "temperature": 0.2,
                "num_predict": 128,
            },
        }

        response = requests.post(
            f"{self.host}/api/chat",
            json=payload,
            timeout=120,
        )

        if not response.ok:
            raise RuntimeError(
                f"Ollama HTTP {response.status_code}: "
                f"{response.text}"
            )

        data = response.json()

        return data["message"]["content"].strip()
