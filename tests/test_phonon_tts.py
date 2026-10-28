import json
import os
import tempfile
import threading
import time
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from voice import phonon_tts


class FakeStdin:
    def __init__(self):
        self.data = ""

    def write(self, value):
        self.data = value

    def flush(self):
        pass


class FakeWorker:
    def __init__(self):
        self.stdin = FakeStdin()
        self.returncode = None
        self.stdout = StringIO()

    def poll(self):
        return self.returncode

    def terminate(self):
        self.returncode = -15


class PhononAdapterTests(unittest.TestCase):
    def setUp(self):
        self.old_state = (
            phonon_tts._WORKER_PROCESS,
            phonon_tts._WORKER_CONFIG,
            phonon_tts._WORKER_BUSY,
            phonon_tts._ACTIVE_PROCESS,
            phonon_tts._GENERATION,
        )
        phonon_tts._WORKER_PROCESS = None
        phonon_tts._WORKER_CONFIG = None
        phonon_tts._WORKER_BUSY = False
        phonon_tts._ACTIVE_PROCESS = None
        phonon_tts._GENERATION = 0

    def tearDown(self):
        (
            phonon_tts._WORKER_PROCESS,
            phonon_tts._WORKER_CONFIG,
            phonon_tts._WORKER_BUSY,
            phonon_tts._ACTIVE_PROCESS,
            phonon_tts._GENERATION,
        ) = self.old_state

    def make_model(self, root):
        model = root / "model"
        (model / "voices").mkdir(parents=True)
        for filename in ("config.json", "tokenizer.json", "model.q8.gguf"):
            (model / filename).write_text("fixture", encoding="utf-8")
        (model / "voices" / "edwin.safetensors").write_bytes(b"voice")
        return model

    def test_model_dir_rejects_incomplete_checkpoint(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.dict(os.environ, {"JARVIS_PHONON_DIR": temp}):
                with self.assertRaisesRegex(RuntimeError, "checkpoint is incomplete"):
                    phonon_tts.model_dir()

    def test_synth_uses_cli_immediately_when_worker_binary_is_missing(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            model = self.make_model(root)
            output = root / "fallback.wav"

            def fake_cli(text, directory, voice, quant):
                output.write_bytes(b"wav")
                self.assertEqual(text, "Hello there.")
                self.assertEqual(directory, model)
                self.assertEqual(voice, "edwin")
                self.assertEqual(quant, "q8")
                return output

            with patch.object(phonon_tts, "model_dir", return_value=model), \
                 patch.object(phonon_tts, "WORKER_BIN", root / "missing-worker"), \
                 patch.object(phonon_tts, "_synth_cli", side_effect=fake_cli) as cli, \
                 patch.dict(os.environ, {
                     "JARVIS_PHONON_VOICE": "edwin",
                     "JARVIS_PHONON_QUANT": "q8",
                 }):
                result = phonon_tts.synth("  Hello   there.  ")
                self.assertEqual(result, output)
                cli.assert_called_once_with("Hello there.", model, "edwin", "q8")
                output.unlink()

    def test_synth_waits_for_background_preheat_when_worker_binary_exists(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            model = self.make_model(root)
            worker = FakeWorker()
            worker_bin = root / "jarvis-phonon-worker"
            finished = threading.Event()
            result = []

            def fake_readline(process, timeout):
                request = json.loads(process.stdin.data)
                Path(request["output"]).write_bytes(b"wav")
                return json.dumps({"ok": True}) + "\n"

            def run_synth():
                try:
                    with patch.object(phonon_tts, "model_dir", return_value=model), \
                         patch.object(phonon_tts, "WORKER_BIN", worker_bin), \
                         patch.object(phonon_tts, "_ensure_worker", return_value=worker), \
                         patch.object(phonon_tts, "_readline_timeout", side_effect=fake_readline), \
                         patch.object(phonon_tts, "_synth_cli", side_effect=AssertionError("CLI should not run")):
                        result.append(phonon_tts.synth("Preheated audio."))
                except Exception as exc:
                    result.append(exc)
                finally:
                    finished.set()

            # Simulate startup warmup holding the lock while loading the model.
            phonon_tts._WORKER_LOCK.acquire()
            thread = threading.Thread(target=run_synth, daemon=True)
            try:
                thread.start()
                time.sleep(0.05)
                self.assertFalse(finished.is_set(), "synthesis should wait for preheat")
                # The worker binary appears while startup warmup owns the lock.
                worker_bin.write_bytes(b"test binary placeholder")
            finally:
                phonon_tts._WORKER_LOCK.release()

            thread.join(timeout=3)
            self.assertTrue(finished.is_set(), "synthesis did not resume after preheat")
            self.assertEqual(len(result), 1)
            if isinstance(result[0], Exception):
                raise result[0]
            self.assertTrue(result[0].is_file())
            result[0].unlink()

    def test_synth_uses_persistent_worker_and_returns_audio(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            model = self.make_model(root)
            worker = FakeWorker()
            worker_bin = root / "jarvis-phonon-worker"
            worker_bin.write_bytes(b"test binary placeholder")

            def fake_readline(process, timeout):
                request = json.loads(process.stdin.data)
                Path(request["output"]).write_bytes(b"wav")
                return json.dumps({"ok": True}) + "\n"

            with patch.object(phonon_tts, "model_dir", return_value=model), \
                 patch.object(phonon_tts, "WORKER_BIN", worker_bin), \
                 patch.object(phonon_tts, "_ensure_worker", return_value=worker), \
                 patch.object(phonon_tts, "_readline_timeout", side_effect=fake_readline), \
                 patch.dict(os.environ, {
                     "PREFIX": temp,
                     "JARVIS_PHONON_VOICE": "edwin",
                     "JARVIS_PHONON_QUANT": "q8",
                 }):
                output = phonon_tts.synth("  Hello   there.  ")
                self.assertTrue(output.is_file())
                self.assertEqual(output.read_bytes(), b"wav")
                request = json.loads(worker.stdin.data)
                self.assertEqual(request["text"], "Hello there.")
                output.unlink()

    def test_synth_falls_back_to_cli_if_worker_unavailable(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            model = self.make_model(root)
            self_test = self

            class FakeProcess:
                returncode = 0

                def __init__(self, command, **kwargs):
                    self.command = command
                    self.stdout = ""
                    self.stderr = ""

                def communicate(self, timeout=None):
                    output = Path(self.command[self.command.index("-o") + 1])
                    output.write_bytes(b"wav")
                    self_test.assertEqual(self.command[self.command.index("-o") - 1], "Hello there.")
                    self_test.assertEqual(self.command[self.command.index("--voice") + 1], "edwin")
                    return ("", "")

                def poll(self):
                    return self.returncode

                def terminate(self):
                    self.returncode = -15

                def kill(self):
                    self.returncode = -9

            with patch.object(phonon_tts, "model_dir", return_value=model), \
                 patch.object(phonon_tts, "_ensure_worker", side_effect=RuntimeError("Cargo unavailable")), \
                 patch.object(phonon_tts, "_exe", return_value="/fake/ptts"), \
                 patch.object(phonon_tts.subprocess, "Popen", side_effect=FakeProcess), \
                 patch.dict(os.environ, {
                     "PREFIX": temp,
                     "JARVIS_PHONON_VOICE": "edwin",
                     "JARVIS_PHONON_QUANT": "q8",
                 }):
                output = phonon_tts.synth("  Hello   there.  ")
                self.assertTrue(output.is_file())
                self.assertEqual(output.read_bytes(), b"wav")
                output.unlink()

    def test_empty_text_is_rejected_without_invoking_ptts(self):
        with patch.object(phonon_tts.subprocess, "run") as run:
            with self.assertRaisesRegex(RuntimeError, "empty text"):
                phonon_tts.synth("  ")
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
