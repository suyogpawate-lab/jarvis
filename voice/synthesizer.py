import os
import requests


class DiscussionSynthesizer:

    def __init__(self):
        self.base_url = os.getenv(
            "OMNIROUTE_BASE_URL",
            "http://127.0.0.1:20128/v1",
        ).rstrip("/")

        self.api_key = os.getenv(
            "OMNIROUTE_API_KEY",
            "",
        )

        self.model = os.getenv(
            "JARVIS_SYNTHESIS_MODEL",
            "auto/best-reasoning",
        )

    def synthesize(self, topic, discussion):

        if not isinstance(discussion, list):
            raise TypeError(
                "Discussion transcript must be a list."
            )

        contributions = []

        for item in discussion:

            if not isinstance(item, dict):
                continue

            content = item.get("content")

            if not content:
                continue

            name = item.get("name", "Agent")

            contributions.append(
                f"[{name}]\n{content}"
            )

        if not contributions:
            raise RuntimeError(
                "No usable discussion contributions."
            )

        transcript = "\n\n".join(contributions)

        prompt = f"""
You are JARVIS's final answer engine.

USER QUESTION:
{topic}

DISCUSSION:
{transcript}

Produce the final answer to the user's question.

VOICE-FIRST RULES:

- Answer the question directly.
- Keep the answer concise.
- Normally target 50 to 120 words.
- Use natural spoken language.
- Make it easy to understand when read aloud.
- Use short sentences.
- Include important technical details, but remove unnecessary depth.
- Explain specialized terms briefly when needed.
- Resolve contradictions using your own reasoning.
- Correct factual errors.
- Do not mention agents, models, the discussion, or synthesis.
- Do not use headings, tables, code blocks, or large lists.
- Avoid unnecessary equations.
- Do not repeat the user's question.
- Do not add filler or greetings.

The result must sound like JARVIS speaking directly to the user.
"""

        response = requests.post(
            f"{self.base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are JARVIS. "
                            "Give concise, technically accurate, "
                            "natural voice-friendly answers."
                        ),
                    },
                    {
                        "role": "user",
                        "content": prompt,
                    },
                ],
                "stream": False,
                "temperature": 0.2,
            },
            timeout=120,
        )

        response.raise_for_status()

        data = response.json()

        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise RuntimeError(
                f"Invalid synthesis response: {data}"
            )

        if not isinstance(content, str) or not content.strip():
            raise RuntimeError(
                "Synthesis model returned an empty response."
            )

        return content.strip()
