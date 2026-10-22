"""Streaming OpenWakeWord + Whistle (Needle) listener for JARVIS."""
import json\nimport os\nimport re\nimport subprocess
import threading
import time
import wave
from collections import deque
from pathlib import Path

import numpy as np
import sounddevice as sd
from openwakeword.model import Model


class WhistleWakeListener:
    RATE = 16000
    FRAME = 1280                 # 80 ms at 16 kHz
    WAKE_THRESHOLD = 0.50
    SILENCE_SECONDS = 0.90
    MAX_COMMAND_SECONDS = 15
    MIN_COMMAND_SECONDS = 0.30
    RMS_THRESHOLD = 420

    def __init__(self, output_queue, chunk_seconds=5, threads=4):
        self.output_queue = output_queue
        self.threads = threads
        self.running = False
        self.thread = None
        self.root = Path(__file__).resolve().parent
        self.runtime = self.root / "runtime"
        self.project_root = self.root.parent
        self.model_path = self.project_root / "whistle.cact"
        self.needle = self.project_root / "android-arm64" / "needle"
        self._wake_model = None

        # Don't trigger on (or transcribe) JARVIS's own spoken replies.
        try:
            from voice import tts as _tts
            self._is_speaking = _tts.is_speaking
        except Exception:
            self._is_speaking = lambda: False

    def start(self):
        for path in (self.model_path, self.needle):
            if not path.is_file():
                raise RuntimeError(
                    f"Required Whistle voice file not found: {path}. "
                    "Run: bash install.sh --with-voice"
                )
        if not os.access(self.needle, os.X_OK):
            raise RuntimeError(
                f"Needle runner is not executable: {self.needle}. "
                f"Run: chmod +x {self.needle}"
            )

        self.runtime.mkdir(parents=True, exist_ok=True)
        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()
        print("[VOICE] Streaming listener starting; wake phrase: Hey Jarvis",
              flush=True)
        return self

    def stop(self):
        self.running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=5)

    @staticmethod
    def _rms(audio):
        if audio.size == 0:
            return 0.0
        values = audio.astype(np.float32)
        return float(np.sqrt(np.mean(values * values)))

    @staticmethod
    def _clean_wake_phrase(text):
        text = text.strip()
        # The acoustic detector already verified "Hey Jarvis".
        # Remove it if Whisper also recognized it in the command buffer.
        text = re.sub(
            r"^\s*(?:hey\s+)?jarvis[\s,.:;!?-]*",
            "",
            text,
            flags=re.IGNORECASE,
        )
        return text.strip()

    def _transcribe(self, audio):
        """Transcribe one completed in-memory command using a transient WAV."""
        if audio.size < int(self.RATE * self.MIN_COMMAND_SECONDS):
            return ""

        # One temporary WAV at a time; never create rolling chunk files.
        wav_path = self.runtime / "_command_stream.wav"
        env = os.environ.copy()
        env["LD_LIBRARY_PATH"] = (
            str(self.needle.parent) + ":" + env.get("LD_LIBRARY_PATH", "")
        )

        try:
            pcm = np.clip(audio, -32768, 32767).astype("<i2", copy=False)
            with wave.open(str(wav_path), "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(self.RATE)
                wf.writeframes(pcm.tobytes())

            result = subprocess.run(
                [
                    str(self.needle), "--model", str(self.model_path),
                    "--audio", str(wav_path),
                ],
                capture_output=True,
                text=True,
                env=env,
                timeout=30,
            )
            if result.returncode != 0:
                return ""

            # Needle/Whistle emits one JSON object, including timing metadata.
            try:
                payload = json.loads((result.stdout or "").strip())
            except json.JSONDecodeError:
                return ""
            text = str(payload.get("text") or "").strip()
            return self._clean_wake_phrase(text) if text else ""
        except Exception:
            return ""
        finally:
            try:
                wav_path.unlink(missing_ok=True)
            except OSError:
                pass

    def _loop(self):
        # Try multiple inference frameworks (ONNX works best on x86, TFLite on ARM/Termux)
        frameworks = ["tflite", "onnx"]  # TFLite first on ARM devices
        self._wake_model = None
        
        for framework in frameworks:
            try:
                # Model initialization may download its official pretrained
                # assets the first time, depending on the installed package.
                self._wake_model = Model(
                    wakeword_models=["hey_jarvis"],
                    inference_framework=framework,
                )
                print(f"[VOICE] OpenWakeWord loaded with {framework} framework", flush=True)
                break
            except Exception as exc:
                print(f"[VOICE] {framework} framework unavailable: {exc}", flush=True)
                continue
        
        if self._wake_model is None:
            print(
                f"[VOICE INIT FAILED] OpenWakeWord: no compatible inference framework\n"
                "  Install one of: onnx, tflite\n"
                "  If the wake-word model is missing, download it with:\n"
                "  python -c \"import openwakeword.utils as u; u.download_models(['hey_jarvis'])\"\n"
                "  Full self-test: python scripts/test_voice.py",
                flush=True,
            )
            self.running = False
            return

        # Preserve a short pre-roll so the first command syllable is not lost.
        preroll = deque(maxlen=10)  # 0.8 seconds
        command_frames = []
        capturing = False
        speech_started = False
        silent_frames = 0
        speech_frames = 0
        mute_until = 0.0          # ignore the mic while JARVIS talks (+ a short tail)
        max_frames = int(self.MAX_COMMAND_SECONDS * self.RATE / self.FRAME)
        silence_limit = int(self.SILENCE_SECONDS * self.RATE / self.FRAME)

        try:
            with sd.InputStream(
                samplerate=self.RATE,
                channels=1,
                dtype="int16",
                blocksize=self.FRAME,
            ) as stream:
                while self.running:
                    block, overflowed = stream.read(self.FRAME)
                    if not self.running:
                        break

                    audio = np.asarray(block, dtype=np.int16).reshape(-1).copy()
                    if audio.size != self.FRAME:
                        continue

                    if not capturing:
                        if self._is_speaking():
                            mute_until = time.time() + 0.6
                        if time.time() < mute_until:
                            preroll.clear()
                            continue
                        preroll.append(audio)
                        try:
                            # OpenWakeWord expects float32 in range [-1.0, 1.0]
                            # Ensure audio is C-contiguous for model compatibility
                            audio_float = np.ascontiguousarray(
                                audio.astype(np.float32) / 32768.0
                            )
                            scores = self._wake_model.predict(audio_float)
                            score = max(
                                (
                                    float(v) for k, v in scores.items()
                                    if "hey_jarvis" in k.lower()
                                ),
                                default=0.0,
                            )
                        except Exception as e:
                            # Log first occurrence only to avoid spam
                            if not hasattr(self, '_wake_error_logged'):
                                print(f"[VOICE WARN] Wakeword prediction error: {e}", flush=True)
                                self._wake_error_logged = True
                            continue

                        if score >= self.WAKE_THRESHOLD:
                            capturing = True
                            command_frames = list(preroll)
                            speech_started = False
                            silent_frames = 0
                            speech_frames = 0
                            preroll.clear()
                        continue

                    command_frames.append(audio)
                    level = self._rms(audio)

                    if level >= self.RMS_THRESHOLD:
                        speech_started = True
                        speech_frames += 1
                        silent_frames = 0
                    elif speech_started:
                        silent_frames += 1

                    done = (
                        speech_started and silent_frames >= silence_limit
                    ) or len(command_frames) >= max_frames

                    if done:
                        combined = np.concatenate(command_frames)
                        text = self._transcribe(combined)

                        if text:
                            # Direct to the existing JARVIS queue.
                            self.output_queue.put(text)

                        command_frames = []
                        capturing = False
                        speech_started = False
                        silent_frames = 0
                        speech_frames = 0
                        preroll.clear()

        except Exception as exc:
            if self.running:
                print(f"[VOICE STREAM ERROR] {exc}", flush=True)
                if "device" in str(exc).lower() or "portaudio" in str(exc).lower():
                    print("  No usable microphone through PortAudio. On Termux a common fix is:\n"
                          "  pkg install pulseaudio; pulseaudio --start --exit-idle-time=-1;\n"
                          "  pactl load-module module-sles-source   (then: python scripts/test_voice.py mic)",
                          flush=True)
        finally:
            self.running = False
            self._wake_model = None
