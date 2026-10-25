"""Provider-neutral, punctuation-aware JARVIS speech queue."""
import os
import queue
import re
import threading
import time
from pathlib import Path

from voice.tts import speak as edge_speak, interrupt as edge_interrupt
from voice.text_chunking import chunk_text

_ABBREVIATIONS = {"mr.", "mrs.", "ms.", "dr.", "prof.", "sr.", "jr.", "st.", "vs.", "etc.", "e.g.", "i.e.", "no.", "fig.", "approx.", "inc.", "ltd.", "co.", "u.s.", "u.k.", "a.m.", "p.m."}


def _provider():
    value = os.environ.get("JARVIS_TTS_PROVIDER", "").strip().lower()
    if value:
        return value
    try:
        from jarvis_env import parse_env_line
        env_path = Path(__file__).resolve().parents[1] / ".env"
        for line in env_path.read_text(encoding="utf-8").splitlines():
            parsed = parse_env_line(line)
            if parsed and parsed[0] == "JARVIS_TTS_PROVIDER":
                return parsed[1].strip().lower()
    except (OSError, ImportError, ValueError):
        pass
    return "edge"


class TTSManager:
    """Queued Edge, Piper C-API, or Sherpa-ONNX TTS manager."""
    def __init__(self):
        self.queue = queue.Queue(maxsize=64)
        self.running = True
        self.worker_alive = False
        self.last_error = ""
        self.last_provider = ""
        self.last_started = 0.0
        self.last_finished = 0.0
        self._active_lock = threading.Lock()
        self._active_playback = False
        self._thread = threading.Thread(target=self._queue_worker, daemon=True, name="JarvisTTS")
        self._thread.start()
        # Piper's model is warmed asynchronously at startup, not on the first
        # user-facing response. Native-library failures remain visible in logs.
        if _provider() == "piper":
            threading.Thread(target=self._warm_piper, daemon=True, name="PiperWarmup").start()
        elif _provider() == "say":
            threading.Thread(target=self._warm_say, daemon=True, name="ZipSayWarmup").start()

    def _warm_piper(self):
        try:
            from voice.piper_tts import warmup
            warmup()
            print("[TTS] Piper localhost service ready; model preloaded.", flush=True)
        except Exception as exc:
            self.last_error = str(exc)
            print(f"[TTS ERROR] Piper preload failed: {exc}", flush=True)

    def _warm_say(self):
        try:
            from voice.jarvis_voice_runtime import ensure_server
            ensure_server()
            print("[TTS] ZIP say server ready; Alan/Bryce model cached.", flush=True)
        except Exception as exc:
            self.last_error = str(exc)
            print(f"[TTS ERROR] ZIP say server startup failed: {exc}", flush=True)

    def _run_provider(self, text, speed=1.0):
        provider = _provider()
        if provider == "say":
            from voice.jarvis_voice_runtime import speak as say_speak
            result = say_speak(text)
        elif provider == "piper":
            from voice.piper_tts import speak as piper_speak
            result = piper_speak(text, wait=True, speed=speed)
        elif provider == "sherpa":
            from voice.sherpa_tts import speak as sherpa_speak
            result = sherpa_speak(text, wait=True, speed=speed)
        elif provider == "edge":
            result = edge_speak(text, wait=True)
        else:
            raise RuntimeError(f"Unknown JARVIS_TTS_PROVIDER {provider!r}; choose say, edge, piper, or sherpa.")
        if not result:
            raise RuntimeError(f"{provider} TTS playback failed")
        return provider

    def _speak_with_fallbacks(self, text, speed=1.0):
        try:
            with self._active_lock:
                self._active_playback = True
            self.last_provider = self._run_provider(text, speed)
            self.last_error = ""
            return True
        except Exception as exc:
            self.last_provider = ""
            self.last_error = str(exc)
            return False
        finally:
            with self._active_lock:
                self._active_playback = False
            self.last_finished = time.monotonic()

    def _queue_worker(self):
        self.worker_alive = True
        try:
            while self.running:
                try:
                    item = self.queue.get(timeout=0.2)
                except queue.Empty:
                    continue
                try:
                    if item is None:
                        break
                    text, speed = item
                    self.last_started = time.monotonic()
                    if not self._speak_with_fallbacks(text, speed):
                        # The public speak() API only queues work; report worker
                        # failures so a silent TTS outage is diagnosable in Termux.
                        print(f"[TTS ERROR] {self.last_error or 'Speech playback failed.'}", flush=True)
                finally:
                    self.queue.task_done()
        finally:
            self.worker_alive = False

    @staticmethod
    def _chunk_text(text, max_chars=4500):
        """Group long replies near 15 words at sentence punctuation only."""
        # max_chars remains accepted for compatibility with existing callers;
        # normal chunk boundaries are sentence-ending .?!, never commas.
        return chunk_text(text, target_words=15, threshold_words=20)

    def speak(self, text, speed=1.0):
        if text is None:
            return False
        text = str(text).strip()
        if not text or not self.running:
            return False
        self.interrupt()
        # Piper and Sherpa localhost services own sentence splitting and
        # synthesize chunk N+1 while chunk N is playing.
        chunks = [text] if _provider() in ("sherpa", "piper") else self._chunk_text(text)
        if not chunks:
            return False
        try:
            for chunk in chunks:
                self.queue.put_nowait((chunk, speed))
            return True
        except queue.Full:
            self.clear()
            self.last_error = "TTS client queue full"
            return False

    def speak_blocking(self, text, speed=1.0):
        if text is None or not str(text).strip():
            return False
        self.last_started = time.monotonic()
        chunks = [str(text).strip()] if _provider() in ("sherpa", "piper") else self._chunk_text(text)
        for chunk in chunks:
            if not self._speak_with_fallbacks(chunk, speed):
                return False
        return True

    def interrupt(self):
        self.clear()
        try:
            edge_interrupt()
        except Exception:
            pass
        try:
            from voice.piper_tts import interrupt as piper_interrupt
            piper_interrupt()
        except Exception:
            pass
        try:
            from voice.sherpa_tts import interrupt as sherpa_interrupt
            sherpa_interrupt()
        except Exception:
            pass

    def clear(self):
        try:
            while True:
                self.queue.get_nowait()
                self.queue.task_done()
        except queue.Empty:
            pass

    def stop(self):
        self.running = False
        self.clear()
        try:
            self.queue.put_nowait(None)
        except queue.Full:
            pass
        if self._thread.is_alive():
            self._thread.join(timeout=1.0)

    def status(self):
        with self._active_lock:
            active = self._active_playback
        provider = _provider()
        if provider == "say":
            voice = os.environ.get("JARVIS_SHERPA_VOICE", "alan").strip().lower()
            primary = f"say/{voice if voice in ('alan', 'bryce') else 'alan'} (ZIP socket server)"
            model = str(Path.home() / "jarvis_voice")
        elif provider == "piper":
            model = str(Path(__file__).resolve().parents[1] / "models/piper/en_GB-alan-medium.onnx")
            primary = f"piper/{Path(model).name}"
        elif provider == "sherpa":
            voice = os.environ.get("JARVIS_SHERPA_VOICE", "alan").strip().lower()
            if voice not in ("alan", "bryce"):
                voice = "alan"
            model_name = "en_GB-alan-medium.onnx" if voice == "alan" else "en_US-bryce-medium.onnx"
            model = str(Path(__file__).resolve().parents[1] / "models" / "sherpa" / voice / model_name)
            primary = f"sherpa/{voice}/{model_name}"
        else:
            model = "edge-tts/en-GB-RyanNeural"
            primary = model
        return {
            "worker_alive": self.worker_alive,
            "active_playback": active,
            "primary_provider": primary,
            "last_provider": self.last_provider,
            "last_error": self.last_error,
            "last_started": self.last_started,
            "last_finished": self.last_finished,
            "queue_pending": self.queue.qsize(),
            "fish_available": False,
            "sherpa_available": provider in ("sherpa", "say"),
            "android_tts_available": False,
            "socket": None,
            "model": model,
        }


tts = TTSManager()
