import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from automation.overnight_research import OvernightResearch, _redact


class OvernightResearchTests(unittest.TestCase):
    def test_delivery_deadline_uses_device_local_timezone(self):
        import time
        from datetime import datetime
        deadline = OvernightResearch._resolve_delivery_deadline("at 5:30 AM")
        self.assertGreater(deadline, time.time())
        target = datetime.fromtimestamp(deadline).astimezone()
        self.assertEqual((target.hour, target.minute), (5, 30))

    def test_interrupted_mission_is_auto_resumed_on_startup(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            state_path.write_text(json.dumps({"schema": 1, "missions": [{
                "id": "overnight-recover-me",
                "query": "quantum physics",
                "status": "COLLECTING",
                "phase": "collection",
                "collection_deadline": 0,
                "evidence_file": str(Path(directory) / "evidence.jsonl"),
                "directory": directory,
                "report_file": str(Path(directory) / "FINAL_REPORT.md"),
            }]}), encoding="utf-8")
            with patch.object(OvernightResearch, "resume", autospec=True) as resume:
                manager = OvernightResearch(Mock(), Mock(), state_path)
            resume.assert_called_once_with(manager, "overnight-recover-me")
            saved = json.loads(state_path.read_text(encoding="utf-8"))
            mission = saved["missions"][0]
            self.assertEqual(mission["status"], "PAUSED_RECOVERY")
            self.assertTrue(mission["auto_resume"])

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
                "\napi_key=super-secret-value must never leave this device."
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

    def test_model_analysis_uses_only_groq_transport(self):
        agent = Mock()
        agent.model = "openai/gpt-oss-120b"
        response = SimpleNamespace(
            status_code=200,
            json=lambda: {"choices": [{"message": {"content": "Analysis complete."}}]},
        )
        agent._groq_post.return_value = response
        with tempfile.TemporaryDirectory() as directory:
            manager = OvernightResearch(Mock(), agent, Path(directory) / "state.json")
            answer = manager._groq(
                [{"role": "user", "content": "Analyze this evidence."}],
                "Research analyst",
            )
            self.assertEqual(answer, "Analysis complete.")
            agent._groq_post.assert_called_once()
            self.assertEqual(agent._groq_post.call_args.kwargs["timeout"], 90)

    def test_deadline_report_is_explicitly_marked_partial(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence = root / "evidence.jsonl"
            evidence.write_text(json.dumps({
                "id": "S0001", "title": "Fixture source",
                "provider": "fixture", "content": "A short evidence excerpt.",
            }) + "\n", encoding="utf-8")
            manager = OvernightResearch(Mock(), Mock(), root / "state.json")
            mission = {
                "id": "overnight-test", "query": "JARVIS reliability",
                "evidence_file": str(evidence),
                "report_file": str(root / "FINAL_REPORT.md"),
            }
            count = manager._write_deadline_report(mission)
            report = Path(mission["report_file"]).read_text(encoding="utf-8")
            self.assertEqual(count, 1)
            self.assertTrue(mission["deadline_report_written"])
            self.assertIn("not a synthesized conclusion", report)
            self.assertIn("[S0001]", report)

    def test_deterministic_query_expansion_does_not_call_a_model(self):
        agent = Mock()
        with tempfile.TemporaryDirectory() as directory:
            manager = OvernightResearch(Mock(), agent, Path(directory) / "state.json")
            queries = manager._queries("JARVIS Android 10 1GB RAM")
            self.assertEqual(len(queries), 6)
            self.assertIn("JARVIS Android 10 1GB RAM research papers studies", queries)
            agent._groq_post.assert_not_called()

    def test_streamed_batches_preserve_every_evidence_record(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = OvernightResearch(
                Mock(), Mock(), Path(directory) / "state.json"
            )
            evidence = Path(directory) / "evidence.jsonl"
            with evidence.open("w", encoding="utf-8") as stream:
                for index in range(11):
                    stream.write(json.dumps({
                        "id": f"S{index:04d}",
                        "kind": "web_page",
                        "content": ("technical evidence " + str(index) + " ") * 500,
                    }) + "\n")
            mission = {"evidence_file": str(evidence)}
            batches = list(manager._iter_batches(mission))
            collected = [item["id"] for batch in batches for item in batch]
            self.assertEqual(collected, [f"S{index:04d}" for index in range(11)])
            self.assertTrue(all(len(batch) <= 8 for batch in batches))

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
        with tempfile.TemporaryDirectory() as directory:
            manager = OvernightResearch(hub, agent, Path(directory) / "state.json")
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
