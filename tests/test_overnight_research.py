import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from automation.overnight_research import OvernightResearch, _redact


class OvernightResearchTests(unittest.TestCase):
    def test_only_public_https_urls_are_eligible(self):
        self.assertEqual(OvernightResearch._url("http://example.com/page"), "")
        self.assertEqual(OvernightResearch._url("https://localhost/private"), "")
        self.assertEqual(OvernightResearch._url("file:///etc/passwd"), "")
        self.assertEqual(
            OvernightResearch._url("https://example.com/a#fragment"),
            "https://example.com/a",
        )

    def test_local_evidence_redacts_credentials_before_persistence(self):
        with tempfile.TemporaryDirectory() as directory:
            agent = Mock()
            manager = OvernightResearch(Mock(), agent, Path(directory) / "state.json")
            mission_dir = Path(directory) / "mission"
            mission_dir.mkdir()
            mission = {
                "id": "overnight-test",
                "evidence_file": str(mission_dir / "evidence.jsonl"),
                "source_count": 0,
            }
            seen = set()
            text = (
                "JARVIS architecture and Android compatibility findings. "
                "The memory manager has a bounded cache and deterministic startup. "
                "api_key=super-secret-value must never leave this device."
            )
            self.assertTrue(manager._append_evidence(mission, {
                "provider": "local_file", "title": "notes.md",
                "path": "/private/notes.md", "kind": "local_file",
                "content": text,
            }, seen))
            self.assertFalse(manager._append_evidence(mission, {
                "provider": "local_file", "title": "notes.md",
                "path": "/private/notes.md", "kind": "local_file",
                "content": text,
            }, seen))
            saved = json.loads((mission_dir / "evidence.jsonl").read_text().splitlines()[0])
            self.assertNotIn("super-secret-value", saved["content"])
            self.assertIn("[REDACTED", saved["content"])
            self.assertEqual(mission["source_count"], 1)

    def test_model_analysis_uses_only_omniroute_transport(self):
        agent = Mock()
        agent._omniroute_request.return_value = "Analysis complete."
        manager = OvernightResearch(Mock(), agent)
        answer = manager._omni(
            [{"role": "user", "content": "Analyze this evidence."}],
            "Research analyst",
        )
        self.assertEqual(answer, "Analysis complete.")
        agent._omniroute_request.assert_called_once()
        self.assertEqual(agent._omniroute_request.call_args.kwargs["timeout"], 90)

    def test_deterministic_query_expansion_does_not_call_a_model(self):
        agent = Mock()
        manager = OvernightResearch(Mock(), agent)
        queries = manager._queries("JARVIS Android 10 1GB RAM")
        self.assertEqual(len(queries), 6)
        self.assertIn("JARVIS Android 10 1GB RAM research papers studies", queries)
        agent._omniroute_request.assert_not_called()

    def test_search_result_is_persisted_without_model_synthesis(self):
        provider = Mock()
        provider.name = "fixture"
        provider.search.return_value = [
            SimpleNamespace(
                url="https://example.org/jarvis",
                title="JARVIS Android architecture",
                snippet=("JARVIS uses a modular Python architecture with local tools, "
                         "a background worker and a persistent state store."),
                content="",
            )
        ]
        hub = Mock()
        hub.providers = [provider]
        agent = Mock()
        manager = OvernightResearch(hub, agent)
        with tempfile.TemporaryDirectory() as directory:
            mission_dir = Path(directory)
            mission = {
                "id": "overnight-test",
                "query": "JARVIS Android architecture",
                "evidence_file": str(mission_dir / "evidence.jsonl"),
                "source_count": 0,
                "search_rounds": 0,
                "provider_failures": [],
            }
            manager._cancel[mission["id"]] = __import__("threading").Event()
            seen = set()
            from collections import deque
            frontier = deque()
            manager._search_round(mission, seen, frontier)
            self.assertEqual(len(frontier), 1)
            self.assertEqual(mission["search_rounds"], 1)
            self.assertTrue((mission_dir / "evidence.jsonl").exists())
            agent._omniroute_request.assert_not_called()
            manager._cancel.clear()


if __name__ == "__main__":
    unittest.main()
