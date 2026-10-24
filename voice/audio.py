"""Streaming microphone input for the legacy offline Vosk voice engine.

Audio is delivered as mono, 16 kHz, signed 16-bit PCM bytes, matching
OfflineSTT's KaldiRecognizer configuration. The active Whistle listener uses
its own stream and is not changed by this compatibility backend.
"""
import queue
import threading

import sounddevice as sd


class AudioInput:
    def __init__(self, sample_rate=16000, blocksize=4000, queue_size=16):
        self.sample_rate = int(sample_rate)
        self.blocksize = int(blocksize)
        self.running = False
        self.queue = queue.Queue(maxsize=max(1, int(queue_size)))
        self.stream = None
        self.thread = None
        self.dropped_frames = 0
        self._lock = threading.Lock()

    def _callback(self, indata, frames, time_info, status):
        if not self.running:
            return
        payload = bytes(indata)
        try:
            self.queue.put_nowait(payload)
        except queue.Full:
            # Keep latency bounded: discard the oldest block rather than
            # allowing stale audio to accumulate behind slow transcription.
            try:
                self.queue.get_nowait()
                self.queue.task_done()
            except queue.Empty:
                pass
            try:
                self.queue.put_nowait(payload)
            except queue.Full:
                self.dropped_frames += frames

    def start(self):
        with self._lock:
            if self.running:
                return
            self.running = True
            try:
                self.stream = sd.RawInputStream(
                    samplerate=self.sample_rate,
                    blocksize=self.blocksize,
                    channels=1,
                    dtype="int16",
                    callback=self._callback,
                )
                self.stream.start()
            except Exception as exc:
                self.running = False
                if self.stream is not None:
                    try:
                        self.stream.close()
                    except Exception:
                        pass
                self.stream = None
                raise RuntimeError(
                    "Could not start microphone input. Check Termux:API/microphone "
                    f"permission and the selected audio device: {exc}"
                ) from exc

    def read(self, timeout=None):
        try:
            return self.queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def stop(self):
        with self._lock:
            self.running = False
            stream, self.stream = self.stream, None
        if stream is not None:
            try:
                stream.stop()
            except Exception:
                pass
            try:
                stream.close()
            except Exception:
                pass
        self.thread = None
