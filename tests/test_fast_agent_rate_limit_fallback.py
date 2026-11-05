import unittest

from agents.fast_agent import FastAgent


class _RateLimitResponse:
    status_code = 429
    text = "rate limit reached"
    headers = {"retry-after": "4"}

    @staticmethod
    def json():
        return {
            "error": {
                "message": "Rate limit reached for tokens per minute (TPM). Try again in 4s."
            }
        }


class FastAgentRateLimitFallbackTests(unittest.TestCase):
    def test_tool_results_are_synthesized_without_replaying_actions(self):
        agent = object.__new__(FastAgent)
        agent._jarvis_system_prompt = lambda: "JARVIS system rules"
        captured = {}

        def fake_omniroute(messages, **kwargs):
            captured["messages"] = messages
            captured["kwargs"] = kwargs
            return "The JARVIS window was opened."

        agent._omniroute_request = fake_omniroute
        messages = [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call-window-1",
                        "function": {
                            "name": "open_workspace_surface",
                            "arguments": "{\"url\":\"https://google.com\"}",
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call-window-1",
                "name": "open_workspace_surface",
                "content": "{\"ok\":true,\"title\":\"google.com\"}",
            },
        ]

        answer = agent._omniroute_tool_result_fallback(
            "overlay google.com window", messages
        )

        self.assertEqual(answer, "The JARVIS window was opened.")
        prompt = captured["messages"][0]["content"]
        self.assertIn("open_workspace_surface", prompt)
        self.assertIn('"ok":true', prompt)
        self.assertIn("ALREADY been executed", prompt)
        self.assertIn("do not repeat any action", prompt)
        self.assertNotIn("tool_calls", captured["messages"][0])
        self.assertEqual(captured["kwargs"]["system_prompt"], "JARVIS system rules")

    def test_tool_result_fallback_refuses_to_run_without_tool_results(self):
        agent = object.__new__(FastAgent)
        with self.assertRaisesRegex(RuntimeError, "No completed tool results"):
            agent._omniroute_tool_result_fallback("open a window", [])

    def test_tpm_message_does_not_claim_every_key_was_exhausted(self):
        agent = object.__new__(FastAgent)
        message = agent._groq_limit_message(_RateLimitResponse())
        self.assertIn("model/organization token-per-minute limit", message)
        self.assertNotIn("all keys", message)
        self.assertIn("4 seconds", message)


if __name__ == "__main__":
    unittest.main()
