"""Tests for the isolated background Claude Code runner."""
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from automation.coding_agent import CodingAgentManager


class CodingAgentManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.jobs = self.root / "jobs"
        self.worktrees = self.root / "worktrees"

    def manager(self):
        return CodingAgentManager(
            repo_root=self.root,
            jobs_dir=self.jobs,
            worktrees_dir=self.worktrees,
        )

    def test_classifier_routes_substantial_code_changes_only(self):
        self.assertTrue(CodingAgentManager.is_complex_coding_request(
            "Fix the concurrency bug in the JARVIS project tests"
        ))
        self.assertTrue(CodingAgentManager.is_complex_coding_request(
            "Implement CLI telemetry and token tracking in the JARVIS codebase"
        ))
        self.assertTrue(CodingAgentManager.is_complex_coding_request(
            "Fix the floating window loading bug in the JARVIS web workspace"
        ))
        self.assertFalse(CodingAgentManager.is_complex_coding_request(
            "How does Python memory management work?"
        ))
        self.assertFalse(CodingAgentManager.is_complex_coding_request(
            "How do I fix a test in this project?"
        ))
        self.assertFalse(CodingAgentManager.is_complex_coding_request(
            "Explain this function"
        ))

    def test_command_is_noninteractive_and_does_not_bypass_permissions(self):
        with patch.dict(os.environ, {
            "JARVIS_CODING_AGENT_MODEL": "claude-code",
            "OMNIROUTE_COMPLEX_MODEL": "auto/best-reasoning",
        }, clear=False):
            manager = self.manager()
            command = manager._command("implement a feature")
        self.assertIn("-p", command)
        self.assertIn("--output-format", command)
        self.assertIn("json", command)
        self.assertIn("--model", command)
        self.assertIn("claude-code", command)
        self.assertIn("--permission-mode", command)
        self.assertIn("dontAsk", command)
        self.assertNotIn("--dangerously-skip-permissions", command)

    def test_omniroute_environment_forces_local_anthropic_compatible_route(self):
        with patch.dict(os.environ, {
            "OMNIROUTE_BASE_URL": "http://127.0.0.1:20128/v1",
            "OMNIROUTE_API_KEY": "local-token",
            "JARVIS_CODING_AGENT_MODEL": "claude-code",
            "ANTHROPIC_API_KEY": "must-not-leak",
        }, clear=False):
            env = self.manager()._omniroute_env()
        self.assertEqual(env["ANTHROPIC_BASE_URL"], "http://127.0.0.1:20128")
        self.assertEqual(env["ANTHROPIC_AUTH_TOKEN"], "local-token")
        self.assertEqual(env["ANTHROPIC_MODEL"], "claude-code")
        self.assertNotIn("ANTHROPIC_API_KEY", env)

    def test_job_id_path_validation(self):
        manager = self.manager()
        with self.assertRaises(ValueError):
            manager._path("../outside")
        self.assertEqual(manager._path("code-1234abcd").name, "code-1234abcd.json")


class SideQuestTests(unittest.TestCase):
    def test_btw_side_question_uses_direct_answer_without_tool_dispatch(self):
        from automation.command_dispatcher import CommandDispatcher
        dispatcher = object.__new__(CommandDispatcher)
        dispatcher.fast_agent = type("Fast", (), {
            "_answer_simple_direct": lambda self, question: "direct:" + question
        })()
        self.assertEqual(
            dispatcher._handle_btw("/btw what is orbital resonance?"),
            "direct:what is orbital resonance?",
        )

    def test_btw_quest_runs_agent_task_in_background(self):
        from automation.command_dispatcher import CommandDispatcher
        finished = threading.Event()

        class AgentEngine:
            def handle(self, command, source="external"):
                if command.startswith("/agent plan "):
                    return "[AGENT PLAN] task-12345678"
                if command == "/agent run task-12345678":
                    finished.set()
                    return "[AGENT TASK] COMPLETED"
                raise AssertionError(command)

        dispatcher = object.__new__(CommandDispatcher)
        dispatcher.agent_engine = AgentEngine()
        dispatcher.coding_agent = type("Coding", (), {
            "is_complex_coding_request": staticmethod(lambda goal: False)
        })()
        dispatcher._side_quest_lock = threading.Lock()
        dispatcher._side_quest_active = False
        result = dispatcher._handle_btw("/btw quest research a new battery chemistry")
        self.assertIn("SIDE QUEST RUNNING IN BACKGROUND", result)
        self.assertIn("task-12345678", result)
        self.assertTrue(finished.wait(2))




if __name__ == "__main__":
    unittest.main()
