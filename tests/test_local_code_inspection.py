"""Regression tests for local code inspection and bounded Groq retries."""
import unittest
from unittest.mock import Mock, patch

from automation.command_dispatcher import CommandDispatcher
from agents.fast_agent import FastAgent


class LocalCodeInspectionTests(unittest.TestCase):
    def setUp(self):
        self.dispatcher = object.__new__(CommandDispatcher)
        self.dispatcher.fast_agent = Mock()
        self.dispatcher.fast_agent.model = "test-model"
        response = Mock()
        response.status_code = 200
        response.json.return_value = {
            "choices": [{"message": {"content": "The file defines a shell executor."}}]
        }
        self.dispatcher.fast_agent._groq_post.return_value = response

    def test_reads_repository_file_and_uses_one_no_tools_completion(self):
        result = self.dispatcher._local_code_inspection(
            "code inspect android/shell_executor.py and tell me how to use it"
        )
        self.assertIn("[FILE INSPECTION] android/shell_executor.py", result)
        payload = self.dispatcher.fast_agent._groq_post.call_args.args[0]
        self.assertNotIn("tools", payload)
        self.assertEqual(payload["max_tokens"], 650)
        self.dispatcher.fast_agent._groq_post.assert_called_once()

    def test_rejects_paths_outside_repository(self):
        result = self.dispatcher._local_code_inspection(
            "inspect ../../etc/passwd.py"
        )
        self.assertIn("restricted to files inside", result)
        self.dispatcher.fast_agent._groq_post.assert_not_called()

    def test_ignores_requests_without_file_inspection_intent(self):
        self.assertIsNone(self.dispatcher._local_code_inspection(
            "What does a Python file do?"
        ))
        self.dispatcher.fast_agent._groq_post.assert_not_called()


class SimpleQuestionRoutingTests(unittest.TestCase):
    def test_short_factual_question_is_routed_without_tools(self):
        self.assertEqual(
            FastAgent._simple_direct_request("What is an X-Token?"),
            "What is an X-Token?",
        )
        self.assertIsNone(
            FastAgent._simple_direct_request("Send a WhatsApp message to Alex"),
        )
        self.assertIsNone(
            FastAgent._simple_direct_request("Inspect jarvis_http_bridge.py"),
        )

    def test_simple_answer_payload_omits_tool_schemas_and_skill_index(self):
        agent = object.__new__(FastAgent)
        agent.model = "test-model"
        agent._jarvis_base_system_prompt = Mock(return_value="compact system prompt")
        response = Mock()
        response.status_code = 200
        response.json.return_value = {
            "choices": [{"message": {"content": "It authenticates a request."}}]
        }
        agent._groq_post = Mock(return_value=response)
        result = agent._answer_simple_direct("What is an X-Token?")
        self.assertEqual(result, "It authenticates a request.")
        payload = agent._groq_post.call_args.args[0]
        self.assertNotIn("tools", payload)
        self.assertEqual(payload["max_tokens"], 256)
        self.assertEqual(payload["messages"][0]["content"], "compact system prompt")


class GroqRetryTests(unittest.TestCase):
    def test_model_scoped_tpm_limit_stops_key_rotation_without_sleeping(self):
        agent = object.__new__(FastAgent)
        agent.api_keys = ["key-a", "key-b", "key-c"]
        agent.current_key_index = 0
        agent.base_url = "https://example.invalid/v1"
        agent.model = "test-model"
        limited = Mock()
        limited.status_code = 429
        limited.headers = {}
        limited.text = '{"error":{"message":"tokens per minute limit"}}'
        limited.json.return_value = {
            "error": {"message": "tokens per minute limit"}
        }
        with patch("agents.fast_agent.requests.post", return_value=limited) as post, \
             patch("time.sleep") as sleep:
            result = agent._groq_post({"model": "test-model", "messages": []})
        self.assertEqual(result.status_code, 429)
        self.assertEqual(post.call_count, 1)
        sleep.assert_not_called()




class OmniRouteSpecialistTests(unittest.TestCase):
    def test_specialist_provider_is_always_omniroute(self):
        agent = object.__new__(FastAgent)
        self.assertEqual(agent._select_complex_provider("debug this project"), "omniroute")

    def test_omniroute_post_uses_shared_gateway_and_expert_model(self):
        agent = object.__new__(FastAgent)
        agent.omniroute_base_url = "http://127.0.0.1:20128/v1"
        agent.omniroute_api_key = "test-token"
        agent.omniroute_model = "auto/best-reasoning"
        response = Mock()
        payload = {"model": "old-provider-model", "messages": [{"role": "user", "content": "test"}]}

        with patch("agents.fast_agent.requests.post", return_value=response) as post:
            result = agent._omniroute_post(payload, timeout=17)

        self.assertIs(result, response)
        args, kwargs = post.call_args
        self.assertEqual(args[0], "http://127.0.0.1:20128/v1/chat/completions")
        self.assertEqual(kwargs["json"]["model"], "auto/best-reasoning")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer test-token")
        self.assertEqual(kwargs["timeout"], 17)
        self.assertEqual(payload["model"], "old-provider-model")

    def test_direct_gemini_and_anthropic_endpoints_are_removed(self):
        source = (
            Path(__file__).resolve().parents[1] / "agents" / "fast_agent.py"
        ).read_text(encoding="utf-8")
        for legacy in (
            "generativelanguage.googleapis.com",
            "api.anthropic.com",
            "GEMINI_API_KEY",
            "ANTHROPIC_API_KEY",
        ):
            self.assertNotIn(legacy, source)


if __name__ == "__main__":
    unittest.main()
