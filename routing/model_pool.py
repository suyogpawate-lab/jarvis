import os
import requests


class ModelPool:
    def __init__(self):
        self.base_url = os.getenv(
            "OMNIROUTE_BASE_URL",
            "http://127.0.0.1:20128/v1",
        ).rstrip("/")

        self.api_key = os.getenv("OMNIROUTE_API_KEY", "")

    def _headers(self):
        headers = {"Content-Type": "application/json"}

        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        return headers

    def all_models(self):
        response = requests.get(
            f"{self.base_url}/models",
            headers=self._headers(),
            timeout=20,
        )

        response.raise_for_status()

        data = response.json()

        return [
            item["id"]
            for item in data.get("data", [])
            if item.get("id")
        ]

    def classify_models(self, models):
        """
        Categorize models heuristically from their IDs.

        This is deliberately broad because OmniRoute may expose
        hundreds of changing model IDs.
        """

        simple = []
        creative = []
        complex_models = []

        for model in models:
            m = model.lower()

            if any(x in m for x in (
                "embedding",
                "moderation",
                "whisper",
                "image",
                "vision",
            )):
                continue

            if any(x in m for x in (
                "reasoning",
                "thinking",
                "opus",
                "pro",
                "deepseek",
                "glm",
                "o1",
                "o3",
                "o4",
            )):
                complex_models.append(model)

            elif any(x in m for x in (
                "creative",
                "sonnet",
                "grok",
                "kimi",
                "mistral",
            )):
                creative.append(model)

            elif any(x in m for x in (
                "flash",
                "haiku",
                "fast",
                "cheap",
                "mini",
                "small",
                "chat",
            )):
                simple.append(model)

            else:
                creative.append(model)

        return {
            "simple": simple,
            "creative": creative,
            "complex": complex_models,
        }
