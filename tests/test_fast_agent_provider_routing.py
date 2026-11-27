import unittest
from unittest.mock import patch

from agents.ai_provider import AIProviderRouter
from agents.fast_agent import FastAgent


class FastAgentProviderRoutingTests(unittest.TestCase):
    def test_action_detection_routes_side_effects_away_from_chat_only_models(self):
        self.assertTrue(FastAgent._request_requires_tools("Send a WhatsApp message to Alex"))
        self.assertTrue(FastAgent._request_requires_tools("Set an alarm for 6 AM"))
        self.assertFalse(FastAgent._request_requires_tools("Explain why neutron stars are dense"))

    def test_local_provider_is_used_for_chat(self):
        agent = object.__new__(FastAgent)
        agent._ai_provider_router = AIProviderRouter({"JARVIS_AI_PROVIDER": "local"})
        fake = type("Response", (), {"status_code": 200})()
        with patch.object(agent._ai_provider_router, "post", return_value=fake) as post:
            result = agent._chat_post({"messages": [{"role": "user", "content": "hello"}]})
        self.assertIs(result, fake)
        self.assertEqual(post.call_args.kwargs["provider"], "local")

    def test_groq_failure_uses_local_only_when_fallback_is_allowed(self):
        agent = object.__new__(FastAgent)
        agent._ai_provider_router = AIProviderRouter({
            "JARVIS_AI_PROVIDER": "groq",
            "JARVIS_AI_FALLBACK_PROVIDER": "local",
        })
        fake = type("Response", (), {"status_code": 200})()
        with patch.object(agent, "_groq_post", side_effect=RuntimeError("rate limited")):
            with patch.object(agent._ai_provider_router, "post", return_value=fake) as local:
                result = agent._chat_post({"messages": []}, allow_local_fallback=True)
        self.assertIs(result, fake)
        self.assertEqual(local.call_args.kwargs["provider"], "local")

    def test_groq_failure_does_not_fallback_after_tool_execution(self):
        agent = object.__new__(FastAgent)
        agent._ai_provider_router = AIProviderRouter({
            "JARVIS_AI_PROVIDER": "groq",
            "JARVIS_AI_FALLBACK_PROVIDER": "local",
        })
        with patch.object(agent, "_groq_post", side_effect=RuntimeError("rate limited")):
            with patch.object(agent._ai_provider_router, "post") as local:
                with self.assertRaises(RuntimeError):
                    agent._chat_post({"messages": []}, allow_local_fallback=False)
        local.assert_not_called()


if __name__ == "__main__":
    unittest.main()
