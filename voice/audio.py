"""
Local microphone abstraction.

The rest of JARVIS does not need to know how Android/Termux
provides microphone data.

This module intentionally keeps the audio interface isolated
so we can replace the backend later without rewriting the
voice engine.
"""

import subprocess
import shutil
import threading
import queue
import time


class AudioInput:

    def __init__(self, sample_rate=16000):
        self.sample_rate = sample_rate
        self.running = False
        self.queue = queue.Queue()
        self.process = None
        self.thread = None

    def start(self):
        if self.running:
            return

        self.running = True

        # We currently use Termux:API as the microphone bridge.
        # The backend is isolated here so it can later be replaced
        # with a native localhost audio bridge.

        if shutil.which("termux-microphone-record") is None:
            raise RuntimeError(
                "termux-microphone-record not found. "
                "Install Termux:API."
            )

        self.thread = threading.Thread(
            target=self._capture_loop,
            daemon=True,
            name="JarvisAudioInput",
        )

        self.thread.start()

    def _capture_loop(self):
        """
        Placeholder backend.

        We deliberately do not allow the rest of the application
        to depend directly on Termux:API.

        The backend will be upgraded to a true streaming PCM
        transport after the basic local voice stack is verified.
        """

        while self.running:
            time.sleep(0.1)

    def read(self, timeout=None):
        try:
            return self.queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def stop(self):
        self.running = False

        if self.process:
            try:
                self.process.terminate()
            except Exception:
                pass

        self.process = None
        self.thread = None
