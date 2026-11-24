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
    def test_tpm_message_does_not_claim_every_key_was_exhausted(self):
        agent = object.__new__(FastAgent)
        message = agent._groq_limit_message(_RateLimitResponse())
        self.assertIn("model/organization token-per-minute limit", message)
        self.assertNotIn("all keys", message)
        self.assertIn("4 seconds", message)

    def test_simple_groq_rate_limit_does_not_automatically_delegate(self):
        agent = object.__new__(FastAgent)
        agent.model = "openai/gpt-oss-120b"
        agent._groq_post = lambda payload, timeout=15: _RateLimitResponse()

        def unexpected_delegate(*args, **kwargs):
            raise AssertionError("Groq did not choose OmniRoute delegation")

        agent._omniroute_request = unexpected_delegate
        answer = agent._answer_simple_direct(
            "What is a neutron star?", allow_omniroute_fallback=False
        )
        self.assertIn("token-per-minute limit", answer)

    def test_groq_can_explicitly_call_omniroute_delegation_tool(self):
        agent = object.__new__(FastAgent)
        agent._last_used_tools = []
        agent._omniroute_request = lambda *args, **kwargs: "Specialist analysis"

        result = agent._execute_tool_call({
            "function": {
                "name": "delegate_to_omniroute",
                "arguments": '{"task":"Compare two algorithmic approaches"}'
            }
        })
        self.assertTrue(result["ok"])
        self.assertEqual(result["provider"], "OmniRoute")
        self.assertEqual(result["result"], "Specialist analysis")
        self.assertIn("delegate_to_omniroute", agent._last_used_tools)
        names = {
            item["function"]["name"]
            for item in agent._builtin_tool_definitions()
        }
        self.assertIn("delegate_to_omniroute", names)

    def test_local_tool_result_fallback_does_not_need_a_second_provider(self):
        messages = [
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "call-email-1",
                        "function": {
                            "name": "email_send",
                            "arguments": "{}",
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call-email-1",
                "name": "email_send",
                "content": '{"ok":true}',
            },
        ]
        self.assertEqual(
            FastAgent._local_tool_result_fallback(messages),
            "The email tool confirmed that the message was sent successfully.",
        )


if __name__ == "__main__":
    unittest.main()
