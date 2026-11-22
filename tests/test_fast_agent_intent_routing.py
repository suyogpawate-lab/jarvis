import unittest

from agents.fast_agent import FastAgent


class FastAgentIntentRoutingTests(unittest.TestCase):
    def setUp(self):
        self.agent = object.__new__(FastAgent)

    def test_memory_context_cannot_turn_greeting_into_shell_work(self):
        prompt = (
            "RELEVANT MEMORY:\n"
            "Earlier discussion: run commands, install packages, fix code, configure services.\n\n"
            "CURRENT USER MESSAGE:\n\nhow are you?"
        )
        self.assertFalse(self.agent._is_shell_reasoning_request(prompt))
        self.assertFalse(self.agent._is_complex_shell_request(prompt))

    def test_current_explicit_code_request_still_routes_to_shell(self):
        prompt = (
            "RELEVANT MEMORY:\nA greeting from an earlier chat.\n\n"
            "CURRENT USER MESSAGE:\n\nfix this code and run the tests"
        )
        self.assertTrue(self.agent._is_shell_reasoning_request(prompt))
        self.assertTrue(self.agent._is_complex_shell_request(prompt))


if __name__ == "__main__":
    unittest.main()
