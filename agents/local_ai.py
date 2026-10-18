"""
Local AI utilities for JARVIS.

Uses Ollama for cheap/local transformations that do not
require OmniRoute-level reasoning.
"""

import requests


class LocalAI:

    def __init__(
        self,
        model="qwen2.5:0.5b",
        base_url="http://127.0.0.1:11434",
    ):
        self.model = model
        self.base_url = base_url.rstrip("/")

    def ask(self, prompt, timeout=60):
        response = requests.post(
            f"{self.base_url}/api/generate",
            json={
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.1,
                    "num_predict": 300,
                },
            },
            timeout=timeout,
        )

        response.raise_for_status()

        data = response.json()
        answer = data.get("response", "").strip()

        if not answer:
            raise RuntimeError("Ollama returned an empty response.")

        return answer
