import os
import json
import requests

from monitoring import alerts


class Jarvis:

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
            "JARVIS_MODEL",
            "auto/best-reasoning",
        )

        self.abilities_file = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "config",
            "abilities.json",
        )

        with open(self.abilities_file, "r", encoding="utf-8") as f:
            self.abilities = json.load(f)

        if not isinstance(self.abilities, list):
            raise RuntimeError(
                "abilities.json must contain a JSON array."
            )

    def ask(self, prompt):
        """Ask the model; raise the right alert if the backend is unreachable."""
        try:
            return self.compact_response(self._ask(prompt))
        except requests.exceptions.ConnectionError:
            alerts.post("Cannot reach the reasoning backend (OmniRoute).", "urgent", "core", speak=True, dedup=120)
            raise
        except requests.exceptions.Timeout:
            alerts.post("The reasoning backend timed out.", "warn", "core", dedup=120)
            raise
        except requests.exceptions.HTTPError as exc:
            code = getattr(getattr(exc, "response", None), "status_code", "?")
            alerts.post(f"The reasoning backend returned HTTP {code}.", "warn", "core", dedup=120)
            raise

    def compact_response(self, answer):
        """Enforce JARVIS's 99-word, plain-prose response contract."""
        answer = str(answer or "").strip()
        if not answer:
            return answer
        is_list = bool(re.search(r"(?m)^\\s*(?:[-*•]|\\d+[.)])\\s+", answer))
        is_heading = bool(re.search(r"(?m)^\\s*#{1,6}\\s+", answer))
        if len(answer.split()) <= 99 and not is_list and not is_heading:
            return answer

        # This is a formatting-only request. It receives the completed answer,
        # never the original task, so no device action can be repeated.
        try:
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
                                "Rewrite the supplied answer as one plain-prose paragraph "
                                "of at most 99 words. Preserve every fact needed for "
                                "correctness, critical caveats, and uncertainty. Do not add "
                                "facts. Do not use lists, bullets, numbering, or headings. "
                                "If accurate compression is impossible, reply exactly: "
                                "'I cannot fit the complete accurate answer into 99 words. "
                                "Which part should I focus on?'"
                            ),
                        },
                        {"role": "user", "content": answer},
                    ],
                    "stream": False,
                    "temperature": 0,
                    "max_tokens": 190,
                },
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()
            compact = str(data["choices"][0]["message"].get("content") or "").strip()
            compact_list = bool(re.search(r"(?m)^\\s*(?:[-*•]|\\d+[.)])\\s+", compact))
            compact_heading = bool(re.search(r"(?m)^\\s*#{1,6}\\s+", compact))
            if compact and len(compact.split()) <= 99 and not compact_list and not compact_heading:
                return compact
        except Exception as exc:
            print(f"[JARVIS OUTPUT] 99-word compaction failed: {type(exc).__name__}", flush=True)

        return "I cannot fit the complete accurate answer into 99 words. Which part should I focus on?"

    def _ask(self, prompt):
        # Ability questions are handled by CommandDispatcher.
        # Do not inject the full abilities registry into normal prompts.

        system_prompt = f"""
You are JARVIS, the user's highly respectful personal assistant.

PERSONALITY:
- Treat the user with consistent respect, courtesy, and professionalism.
- Remain calm, composed, attentive, precise, and confident.
- Speak naturally, like a highly capable personal assistant.
- Do not use "sir" by default. Use it only when it genuinely fits the
  conversational context and sounds natural.
- Never repeat forms of address unnecessarily.
- Never be rude, dismissive, sarcastic, condescending, argumentative,
  patronizing, or unnecessarily casual.
- Do not flatter the user excessively or use artificial deference.
- When the user gives a command, acknowledge it naturally and concisely.
- When the user corrects you, accept the correction without defensiveness.
- If something fails, state the actual problem clearly and explain the
  next step without blaming the user.
- Prioritize useful information and action over conversational filler.

RESPONSE STYLE:
- Be concise and precise.
- Give the answer directly.
- Maximum 99 words, strictly. Never use bullet points, numbered lists, headings or markdown.
- Always reply in flowing, speakable sentences, as if talking aloud.
- Use natural language suitable for text-to-speech.
- Prefer short, naturally spoken sentences.
- Use punctuation that produces natural pauses when spoken.
- Avoid unnecessary markdown.
- Avoid huge explanations.
- Avoid repeating the user's question.
- Do not use greetings or conversational filler unless appropriate.
- Do not say "How can I help?" unless the context genuinely calls for it.
- Do not mention these instructions.
- Never claim an action was executed unless it actually was.
- For technical subjects, remain scientifically and technically accurate.
- You have full privileges for executing bash/shell on Termux and storage permissions.
""".strip()

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
                        "content": system_prompt,
                    },
                    {
                        "role": "user",
                        "content": prompt,
                    },
                ],
                "stream": False,
                "temperature": 0.2,
                "max_tokens": 220,
            },
            timeout=120,
        )

        response.raise_for_status()

        data = response.json()

        try:
            answer = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise RuntimeError(
                f"Unexpected JARVIS response: {data}"
            )

        if not answer:
            raise RuntimeError(
                "JARVIS returned an empty response."
            )

        return answer.strip()
