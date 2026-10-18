import queue
import threading
import time

from voice.tts import speak as edge_speak


class TTSManager:
    """Queued Edge TTS manager with a stable JARVIS-compatible API."""

    def __init__(self):
        self.queue = queue.Queue(maxsize=16)
        self.running = True
        self.worker_alive = False

        self.last_error = ""
        self.last_provider = ""
        self.last_started = 0.0
        self.last_finished = 0.0

        self._active_lock = threading.Lock()
        self._active_playback = False

        self._thread = threading.Thread(
            target=self._queue_worker,
            daemon=True,
            name="JarvisTTS",
        )
        self._thread.start()

    def _run_edge(self, text, speed=1.0):
        # Rate and pitch are configured centrally in tts.py.
        result = edge_speak(text, wait=True)
        if not result:
            raise RuntimeError("Edge TTS playback failed")
        return result

    def _speak_with_fallbacks(self, text, speed=1.0):
        try:
            with self._active_lock:
                self._active_playback = True

            self._run_edge(text, speed)
            self.last_provider = "edge"
            self.last_error = ""
            return True

        except Exception as exc:
            self.last_provider = ""
            self.last_error = f"edge: {exc}"
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
                    self._speak_with_fallbacks(text, speed)
                finally:
                    self.queue.task_done()
        finally:
            self.worker_alive = False

    def _chunk_text(self, text, words_per_chunk=120):
        words = str(text).split()
        chunks = []
        for i in range(0, len(words), words_per_chunk):
            chunk = " ".join(words[i:i + words_per_chunk]).strip()
            if chunk:
                chunks.append(chunk)
        return chunks

    def speak(self, text, speed=1.0):
        if text is None:
            return False

        text = str(text).strip()
        if not text or not self.running:
            return False

        self.clear()
        chunks = self._chunk_text(text)
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
        if text is None:
            return False

        text = str(text).strip()
        if not text:
            return False

        self.last_started = time.monotonic()
        return self._speak_with_fallbacks(text, speed)

    def clear(self):
        """Discard pending speech without interrupting Edge's current synthesis."""
        try:
            while True:
                self.queue.get_nowait()
                self.queue.task_done()
        except queue.Empty:
            pass

    def stop(self):
        """Stop accepting speech and request worker shutdown."""
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

        return {
            "worker_alive": self.worker_alive,
            "active_playback": active,
            "primary_provider": "edge-tts/en-GB-RyanNeural",
            "last_provider": self.last_provider,
            "last_error": self.last_error,
            "last_started": self.last_started,
            "last_finished": self.last_finished,
            "queue_pending": self.queue.qsize(),
            "fish_available": False,
            "sherpa_available": False,
            "android_tts_available": False,
            "socket": None,
            "model": "edge-tts/en-GB-RyanNeural",
        }


tts = TTSManager()
