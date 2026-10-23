"""Streaming OpenWakeWord + Whistle (Needle) listener for JARVIS."""
import json
import os
import re
import subprocess
import threading
import time
import wave
import warnings
from collections import deque
from pathlib import Path

import numpy as np
import sounddevice as sd

# Termux ONNX Runtime emits this known Android platform warning on every import.
# Suppress only that specific warning; all other warnings remain visible.
warnings.filterwarnings(
    "ignore",
    message=r"Unsupported platform \(android\).*",
    category=UserWarning,
)
from openwakeword.model import Model


class WhistleWakeListener:
    RATE = 16000
    FRAME = 1280                 # 80 ms at 16 kHz
    WAKE_THRESHOLD = float(os.getenv("JARVIS_WAKE_THRESHOLD", "0.30"))
    # More trailing context helps Needle decode complete word endings.
    SILENCE_SECONDS = float(os.getenv("JARVIS_VOICE_SILENCE_SECONDS", "1.25"))
    MAX_COMMAND_SECONDS = 15
    MIN_COMMAND_SECONDS = 0.30
    # Configurable so quieter speech isn't discarded by a fixed high threshold.
    RMS_THRESHOLD = float(os.getenv("JARVIS_VOICE_RMS_THRESHOLD", "300"))

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
        self.log_path = self.runtime / "listener.log"

        # Don't trigger on (or transcribe) JARVIS's own spoken replies.
        try:
            from voice import tts as _tts
            self._is_speaking = _tts.is_speaking
        except Exception:
            self._is_speaking = lambda: False

    def _log(self, *args, sep=" ", end="\n", flush=True):
        """Write voice diagnostics to a log instead of corrupting the interactive prompt."""
        message = sep.join(str(arg) for arg in args)
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        try:
            self.runtime.mkdir(parents=True, exist_ok=True)
            with self.log_path.open("a", encoding="utf-8") as log:
                log.write(f"[{timestamp}] {message}{end}")
        except OSError:
            pass

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
        self._log("[VOICE] Listener thread launched; wake phrase: Hey Jarvis", flush=True)
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
        # Remove it if Whistle also recognized it in the command buffer.
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
                    "--audio-language", "en",
                ],
                capture_output=True,
                text=True,
                env=env,
                timeout=30,
            )
            if result.returncode != 0:
                detail = (result.stderr or result.stdout or "")[-500:]
                self._log(f"[VOICE STT ERROR] Needle exited {result.returncode}: {detail}", flush=True)
                return ""

            # Parse clean JSON first; tolerate runtime logs around a JSON line.
            output = (result.stdout or "").strip()
            payload = None
            try:
                payload = json.loads(output)
            except json.JSONDecodeError:
                for line in reversed(output.splitlines()):
                    try:
                        candidate = json.loads(line.strip())
                        if isinstance(candidate, dict) and "text" in candidate:
                            payload = candidate
                            break
                    except json.JSONDecodeError:
                        continue
            if not isinstance(payload, dict):
                self._log(f"[VOICE STT ERROR] Could not parse Needle output: {output[-500:]}", flush=True)
                return ""
            text = str(payload.get("text") or "").strip()
            return self._clean_wake_phrase(text) if text else ""
        except subprocess.TimeoutExpired:
            self._log("[VOICE STT ERROR] Needle timed out after 30 seconds.", flush=True)
            return ""
        except Exception as exc:
            self._log(f"[VOICE STT ERROR] {type(exc).__name__}: {exc}", flush=True)
            return ""
        finally:
            try:
                wav_path.unlink(missing_ok=True)
            except OSError:
                pass

    def _loop(self):
        # Try the Termux-packaged ONNX Runtime first, then TFLite if available.
        frameworks = ["onnx", "tflite"]  # Prefer Termux ONNX Runtime; fall back to TFLite
        self._wake_model = None
        
        for framework in frameworks:
            try:
                # Model initialization may download its official pretrained
                # assets the first time, depending on the installed package.
                self._wake_model = Model(
                    wakeword_models=["hey_jarvis"],
                    inference_framework=framework,
                )
                self._log(f"[VOICE] OpenWakeWord loaded with {framework} framework", flush=True)
                break
            except Exception as exc:
                self._log(f"[VOICE] {framework} framework unavailable: {exc}", flush=True)
                continue
        
        if self._wake_model is None:
            self._log(
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
        conversation_timeout = max(
            5.0, float(os.getenv("JARVIS_CONVERSATION_TIMEOUT", "15"))
        )
        conversation_until = 0.0
        max_frames = int(self.MAX_COMMAND_SECONDS * self.RATE / self.FRAME)
        silence_limit = int(self.SILENCE_SECONDS * self.RATE / self.FRAME)
        # End the voice conversation locally; never forward farewell/stop phrases to the LLM.
        exit_phrase = re.compile(
            r"^(?:"
            r"goodbye(?:\\s+jarvis)?|good\\s+bye(?:\\s+jarvis)?|bye(?:\\s+jarvis)?|"
            r"see\\s+you(?:\\s+later)?(?:\\s+jarvis)?|talk\\s+(?:to\\s+you\\s+)?later|"
            r"that(?:'s|\\s+is)\\s+all(?:\\s+for\\s+now)?|"
            r"i(?:'m|\\s+am)\\s+(?:done|finished)|we(?:'re|\\s+are)\\s+done|"
            r"(?:end|stop|cancel|exit|quit|close|finish)\\s+(?:the\\s+)?"
            r"(?:conversation|chat|session|voice\\s+mode|listening)(?:\\s+jarvis)?|"
            r"(?:end|stop|cancel|exit|quit)\\s+jarvis|stop|cancel|quit"
            r")[.!?\\s]*$",
            re.IGNORECASE,
        )

        try:
            with sd.InputStream(
                samplerate=self.RATE,
                channels=1,
                dtype="int16",
                blocksize=self.FRAME,
            ) as stream:
                self._log("[VOICE] Microphone stream active at 16 kHz mono; say Hey Jarvis.", flush=True)
                while self.running:
                    block, overflowed = stream.read(self.FRAME)
                    if not self.running:
                        break

                    audio = np.asarray(block, dtype=np.int16).reshape(-1).copy()
                    if audio.size != self.FRAME:
                        continue

                    # Never transcribe JARVIS's own voice. If playback starts during
                    # capture, discard that partial recording and wait until playback
                    # and its acoustic tail have ended before listening again.
                    if self._is_speaking():
                        if capturing:
                            self._log(
                                "[VOICE] Discarding partial capture while JARVIS is speaking.",
                                flush=True,
                            )
                        capturing = False
                        command_frames = []
                        speech_started = False
                        silent_frames = 0
                        speech_frames = 0
                        preroll.clear()
                        mute_until = time.time() + 0.8
                        if conversation_until:
                            conversation_until = time.time() + conversation_timeout
                        continue

                    if time.time() < mute_until:
                        preroll.clear()
                        continue

                    if not capturing:
                        preroll.append(audio)
                        level = self._rms(audio)

                        # During an active conversation, voice activity starts capture
                        # directly; the wake phrase is no longer required.
                        if conversation_until > time.time():
                            if level >= self.RMS_THRESHOLD:
                                self._log("[VOICE] Follow-up speech detected; listening...", flush=True)
                                capturing = True
                                command_frames = list(preroll)
                                speech_started = True
                                silent_frames = 0
                                speech_frames = 1
                                preroll.clear()
                            continue
                        elif conversation_until:
                            conversation_until = 0.0
                            self._log("[VOICE] Conversation timed out; say Hey Jarvis to resume.", flush=True)

                        try:
                            # OpenWakeWord requires 16 kHz mono signed int16 PCM.
                            # 1280 samples is its recommended 80 ms frame size.
                            pcm = np.ascontiguousarray(audio, dtype=np.int16)
                            scores = self._wake_model.predict(pcm)
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
                                self._log(f"[VOICE WARN] Wakeword prediction error: {e}", flush=True)
                                self._wake_error_logged = True
                            continue

                        if score >= self.WAKE_THRESHOLD:
                            message = f"[VOICE] Hey Jarvis detected (score={score:.3f}) — listening..."
                            self._log(message, flush=True)
                            # Make wake detection visible immediately in the terminal.
                            print(f"\r{message}", flush=True)
                            try:
                                self._wake_model.reset()
                            except Exception:
                                pass
                            # Play a short random prerecorded acknowledgement, if prepared.
                            # Playback is tracked by voice.tts so its audio is never transcribed.
                            try:
                                from voice.wake_responses import play_random_wake_response
                                play_random_wake_response()
                            except Exception as exc:
                                self._log(f"[VOICE] Wake acknowledgement unavailable: {exc}", flush=True)
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
                            if exit_phrase.fullmatch(text.strip()):
                                conversation_until = 0.0
                                self._log("[VOICE] Conversation ended; say Hey Jarvis to wake me again.", flush=True)
                            else:
                                # Keep listening for follow-ups without another wake phrase.
                                conversation_until = time.time() + conversation_timeout
                                self._log(f"[VOICE] Recognized command: {text}", flush=True)
                                self._log(
                                    f"[VOICE] Continuous conversation active for {conversation_timeout:g}s of inactivity.",
                                    flush=True,
                                )
                                self.output_queue.put(text)
                        else:
                            self._log("[VOICE WARN] No command transcript returned; ready to listen again.", flush=True)

                        command_frames = []
                        capturing = False
                        speech_started = False
                        silent_frames = 0
                        speech_frames = 0
                        preroll.clear()

        except Exception as exc:
            if self.running:
                self._log(f"[VOICE STREAM ERROR] {exc}", flush=True)
                if "device" in str(exc).lower() or "portaudio" in str(exc).lower():
                    self._log("  No usable microphone through PortAudio. On Termux a common fix is:\n"
                          "  pkg install pulseaudio; pulseaudio --start --exit-idle-time=-1;\n"
                          "  pactl load-module module-sles-source   (then: python scripts/test_voice.py mic)",
                          flush=True)
        finally:
            self.running = False
            self._wake_model = None
