import unittest
from pathlib import Path
from unittest.mock import patch
from agents.ai_provider import AIProviderRouter, compact_local_context

class AIProviderTests(unittest.TestCase):
    def test_context_pack_keeps_memory_latest_turns_and_current_request(self):
        prompt = (
            "RELEVANT JARVIS MEMORY:\nUser prefers concise answers.\n\n"
            "CONVERSATION HISTORY:\nUSER: first\nJARVIS: one\nUSER: second\nJARVIS: two\n"
            "USER: third\nJARVIS: three\nUSER: fourth\nJARVIS: four\n"
            "USER: fifth\nJARVIS: five\nUSER: sixth\nJARVIS: six\n"
            "CURRENT USER REQUEST:\nWhat did I ask you to remember?"
        )
        packed = compact_local_context(prompt)
        self.assertIn("User prefers concise answers", packed)
        self.assertIn("USER: third", packed)
        self.assertIn("What did I ask you to remember?", packed)
        self.assertNotIn("USER: first", packed)

    def test_setup_entrypoint_is_valid_python(self):
        setup_path = Path(__file__).resolve().parents[1] / "setup"
        compile(setup_path.read_text(encoding="utf-8"), str(setup_path), "exec")

    def test_unknown_provider_defaults_to_groq(self):
        self.assertEqual(AIProviderRouter({"JARVIS_AI_PROVIDER": "unknown"}).active_provider(), "groq")

    def test_local_model_default_matches_bundled_ollama_alias(self):
        config = AIProviderRouter({"JARVIS_AI_PROVIDER": "local"}).config("local")
        self.assertEqual(config["model"], "jarvis-lfm")

    def test_omniroute_is_available_but_chat_only(self):
        router = AIProviderRouter({
            "JARVIS_AI_PROVIDER": "omniroute",
            "OMNIROUTE_BASE_URL": "http://127.0.0.1:20128/v1",
            "OMNIROUTE_COMPLEX_MODEL": "auto/best-reasoning",
        })
        self.assertEqual(router.active_provider(), "omniroute")
        self.assertFalse(router.supports_tools("omniroute"))
        self.assertEqual(router.config("omniroute")["model"], "auto/best-reasoning")

    def test_local_tool_calling_is_off_by_default(self):
        self.assertFalse(AIProviderRouter({"JARVIS_AI_PROVIDER": "local"}).supports_tools())

    def test_local_request_uses_model_and_removes_unsupported_tools(self):
        router = AIProviderRouter({
            "JARVIS_AI_PROVIDER": "local",
            "JARVIS_LOCAL_AI_BASE_URL": "http://127.0.0.1:11434/v1",
            "JARVIS_LOCAL_AI_API_KEY": "ollama",
            "JARVIS_LOCAL_AI_MODEL": "lfm2.5-350m",
        })
        fake = type("Response", (), {"status_code": 200})()
        with patch("agents.ai_provider.requests.post", return_value=fake) as post:
            result = router.post({
                "model": "ignored", "reasoning_effort": "low",
                "messages": [{"role": "system", "content": "long"}, {"role": "user", "content": "CURRENT USER REQUEST:\nhello"}],
                "tools": [{"type": "function"}], "tool_choice": "auto",
            })
        self.assertIs(result, fake)
        kwargs = post.call_args.kwargs
        self.assertTrue(post.call_args.args[0].endswith("/chat/completions"))
        self.assertEqual(kwargs["json"]["model"], "lfm2.5-350m")
        self.assertNotIn("tools", kwargs["json"])
        self.assertNotIn("reasoning_effort", kwargs["json"])
        self.assertIn("CURRENT USER REQUEST", kwargs["json"]["messages"][1]["content"])


    def test_local_provider_request_never_includes_tool_schemas_by_default(self):
        router = AIProviderRouter({"JARVIS_AI_PROVIDER": "local"})
        self.assertFalse(router.supports_tools("local"))

    def test_custom_tool_calling_is_explicit(self):
        self.assertTrue(AIProviderRouter({
            "JARVIS_AI_PROVIDER": "custom", "JARVIS_CUSTOM_AI_TOOL_CALLING": "1"
        }).supports_tools())

if __name__ == "__main__":
    unittest.main()
