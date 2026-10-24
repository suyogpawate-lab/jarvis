
import json
import os
import requests

from messaging.whatsapp_manager import WhatsAppManager
from messaging.style_profile import style_instructions


class GroqAgent:

    def __init__(self):
        # Keys come from the environment (same variables as fast_agent.py):
        #   export GROQ_API_KEYS="key1,key2,key3"   (or a single GROQ_API_KEY)
        raw_keys = os.getenv("GROQ_API_KEYS") or os.getenv("GROQ_API_KEY", "")
        self.api_keys = [
            k.strip() for k in raw_keys.replace("\n", ",").split(",") if k.strip()
        ]
        if not self.api_keys:
            raise RuntimeError(
                "No Groq API key set. Export GROQ_API_KEYS (comma-separated) "
                "or GROQ_API_KEY before starting."
            )
        self.current_key_index = 0
        self.base_url = "https://api.groq.com/openai/v1"
        self.model = os.getenv(
            "JARVIS_GROQ_MODEL",
            "openai/gpt-oss-120b",
        )

        self.whatsapp = WhatsAppManager(
            timeout=20,
        )

    def _tool_definitions(self):
        return [
            {
                "type": "function",
                "function": {
                    "name": "send_whatsapp_message",
                    "description": (
                        "Send one WhatsApp text message through "
                        "the local JARVIS WhatsApp bridge. "
                        "Use this when the user explicitly asks "
                        "JARVIS to send or message someone on WhatsApp."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "recipient": {
                                "type": "string",
                                "description": (
                                    "The exact contact name, phone "
                                    "number, or WhatsApp JID."
                                ),
                            },
                            "message": {
                                "type": "string",
                                "description": (
                                    "The exact natural-language "
                                    "message to send."
                                ),
                            },
                        },
                        "required": [
                            "recipient",
                            "message",
                        ],
                    },
                },
            },
        ]

    def _execute_tool_call(self, tool_call):
        name = tool_call["function"]["name"]

        try:
            arguments = json.loads(
                tool_call["function"]["arguments"]
            )
        except Exception as exc:
            return {
                "ok": False,
                "error": f"Invalid tool arguments: {exc}",
            }

        if name == "send_whatsapp_message":
            recipient = arguments.get("recipient")
            message = arguments.get("message")

            if (
                not isinstance(recipient, str)
                or not recipient.strip()
            ):
                return {
                    "ok": False,
                    "error": "Missing WhatsApp recipient.",
                }

            if (
                not isinstance(message, str)
                or not message.strip()
            ):
                return {
                    "ok": False,
                    "error": "Missing WhatsApp message.",
                }

            try:
                result = self.whatsapp.send(
                    to=recipient.strip(),
                    message=message.strip(),
                )

                return {
                    "ok": True,
                    "result": result,
                }

            except Exception as exc:
                return {
                    "ok": False,
                    "error": f"WhatsApp send failed: {exc}",
                }

        return {
            "ok": False,
            "error": f"Unknown tool: {name}",
        }

    def ask(self, prompt):
        messages = [
            {
                "role": "system",
                "content": (
                    "You are the fast WhatsApp action agent for JARVIS. "
                    "Your job is to understand the user's request and "
                    "send the requested WhatsApp message using the "
                    "send_whatsapp_message tool. "
                    "Do not explain how to send it manually. "
                    "When the user asks to contact someone, use the tool. "
                    "Infer natural message wording from the user's intent. "
                    "Do not claim success unless the tool confirms success. "
                    "Keep the final response extremely concise. " + style_instructions("outbound")
                ),
            },
            {
                "role": "user",
                "content": str(prompt),
            },
        ]

        for _ in range(4):
            total_keys = len(self.api_keys)
            attempts = 0
            response = None

            while attempts < total_keys:
                active_key = os.getenv("GROQ_API_KEY", "").strip()

                if not active_key:
                    raise RuntimeError(
                        "GROQ_API_KEY is not configured."
                    )
                    self.current_key_index = (self.current_key_index + 1) % total_keys
                    attempts += 1
                    continue

                try:
                    res = requests.post(
                        f"{self.base_url}/chat/completions",
                        headers={
                            "Authorization": f"Bearer {active_key}",
                            "Content-Type": "application/json",
                        },
                        json={
                            "model": self.model,
                            "messages": messages,
                            "tools": self._tool_definitions(),
                            "tool_choice": "auto",
                            "temperature": 0,
                            "max_tokens": 120,
                            "reasoning_effort": "low",
                            "stream": False,
                        },
                        timeout=10,
                    )

                    if res.status_code != 200:
                        print(f"Groq Account {self.current_key_index + 1} failed. Code: {res.status_code}, Body: {res.text}")
                        self.current_key_index = (self.current_key_index + 1) % total_keys
                        attempts += 1
                        continue

                    response = res
                    break

                except requests.exceptions.RequestException as e:
                    print(f"Connection issue with Groq Account {self.current_key_index + 1}: {e}")
                    self.current_key_index = (self.current_key_index + 1) % total_keys
                    attempts += 1

            if response is None:
                raise RuntimeError("All configured Groq API keys are exhausted or failing.")

            response.raise_for_status()

            data = response.json()
            message = data["choices"][0]["message"]

            tool_calls = message.get("tool_calls")

            if not tool_calls:
                return (
                    message.get("content")
                    or "No response from Groq."
                ).strip()

            messages.append(message)

            for tool_call in tool_calls:
                result = self._execute_tool_call(
                    tool_call
                )

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call["id"],
                        "content": json.dumps(result),
                    }
                )

        return "[ERROR] Groq tool loop exceeded its limit."
