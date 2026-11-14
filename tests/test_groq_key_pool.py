"""Shared Groq key-pool and rotation regression tests."""
import os
import unittest
from unittest.mock import patch

from agents.groq_keys import get_groq_api_keys
from agents.fast_agent import FastAgent


class FakeResponse:
    def __init__(self, status, message=""):
        self.status_code = status
        self.headers = {"retry-after": "2"}
        self.text = message

    def json(self):
        return {"error": {"message": self.text}}


class GroqKeyPoolTests(unittest.TestCase):
    def test_merges_all_sources_deduplicates_and_accepts_delimiters(self):
        env = {
            "GROQ_API_KEY": "primary",
            "GROQ_API_KEYS": "account2,account3;account4 account5\\naccount6,primary",
        }
        self.assertEqual(
            get_groq_api_keys(env),
            ["primary", "account2", "account3", "account4", "account5", "account6"],
        )

    def test_fast_agent_tries_all_seven_keys_before_success(self):
        agent = object.__new__(FastAgent)
        agent.api_keys = [f"key{i}" for i in range(1, 8)]
        agent.current_key_index = 0
        agent.base_url = "https://api.groq.com/openai/v1"
        responses = [FakeResponse(429, "requests per minute (RPM)")] * 6
        responses.append(FakeResponse(200))
        with patch("agents.fast_agent.requests.post", side_effect=responses) as post:
            result = agent._groq_post({"model": "test", "messages": []})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(post.call_count, 7)
        self.assertEqual(
            [call.kwargs["headers"]["Authorization"] for call in post.call_args_list],
            [f"Bearer key{i}" for i in range(1, 8)],
        )

    def test_fast_agent_sweeps_all_keys_even_for_tpm_limit(self):
        agent = object.__new__(FastAgent)
        agent.api_keys = [f"key{i}" for i in range(1, 4)]
        agent.current_key_index = 0
        agent.base_url = "https://api.groq.com/openai/v1"
        response = FakeResponse(429, "tokens per minute (TPM)")
        with patch("agents.fast_agent.requests.post", return_value=response) as post:
            result = agent._groq_post({"model": "test", "messages": []})
        self.assertIs(result, response)
        self.assertEqual(post.call_count, 3)


if __name__ == "__main__":
    unittest.main()
