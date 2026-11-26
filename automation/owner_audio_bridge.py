"""Full-duplex local audio bridge for Android Telecom calls.

Android streams 16 kHz mono PCM16 frames to this loopback-only server.
Utterances are transcribed by the same Needle model used by voice.listener,
then routed through jarvis.handle_prompt. Replies are synthesized to WAV and
streamed back as PCM16 for Android AudioTrack playback.
"""
from __future__ import annotations

import json
import os
import queue
import socket
import struct
import subprocess
import tempfile
import threading
import time
import wave
from pathlib import Path

RATE = 16000
FRAME_BYTES = 640  # 20 ms, mono, signed PCM16 at 16 kHz
PORT = int(os.environ.get("JARVIS_OWNER_AUDIO_PORT", "21344"))


class OwnerAudioBridge:
    def __init__(self, command_handler, token_provider, host="127.0.0.1", port=PORT):
        self.command_handler = command_handler
        self.token_provider = token_provider
        self.host = host
        self.port = int(port)
        root = Path(__file__).resolve().parents[1]
        self.model_path = root / "whistle.cact"
        self.needle = root / "android-arm64" / "needle"
        self.running = False
        self.server = None
        self.thread = None
        self._active_lock = threading.Lock()
        self._active_socket = None
        self._command_lock = threading.Lock()

    def start(self):
        if self.running:
            return self
        if not self.model_path.is_file() or not self.needle.is_file():
            raise RuntimeError("Call audio requires whistle.cact and android-arm64/needle.")
        self.running = True
        self.thread = threading.Thread(target=self._serve, daemon=True, name="JarvisOwnerAudio")
        self.thread.start()
        return self

    def stop(self):
        self.running = False
        try:
            if self.server:
                self.server.close()
        except OSError:
            pass
        with self._active_lock:
            active = self._active_socket
        if active:
            try:
                active.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                active.close()
            except OSError:
                pass
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2)

    def _serve(self):
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            server.bind((self.host, self.port))
            server.listen(2)
            server.settimeout(1.0)
            self.server = server
            print(f"[JARVIS CALL AUDIO] Listening on {self.host}:{self.port}", flush=True)
            while self.running:
                try:
                    client, address = server.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break
                if address[0] not in ("127.0.0.1", "::1"):
                    client.close()
                    continue
                worker = threading.Thread(
                    target=self._handle_call, args=(client,), daemon=True,
                    name="JarvisCallSession",
                )
                worker.start()
        except OSError as exc:
            if self.running:
                print(f"[JARVIS CALL AUDIO] Listener failed: {exc}", flush=True)
        finally:
            try:
                server.close()
            except OSError:
                pass

    @staticmethod
    def _read_exact(sock, size):
        data = bytearray()
        while len(data) < size:
            chunk = sock.recv(size - len(data))
            if not chunk:
                return None
            data.extend(chunk)
        return bytes(data)

    def _handle_call(self, client):
        client.settimeout(30.0)
        with self._active_lock:
            if self._active_socket is not None:
                client.close()
                return
            self._active_socket = client
        utterances = queue.Queue(maxsize=8)
        send_lock = threading.Lock()
        session_running = threading.Event()
        session_running.set()
        try:
            reader = client.makefile("rb")
            hello_line = reader.readline(2048)
            hello = json.loads(hello_line.decode("utf-8"))
            expected = str(self.token_provider() or "")
            supplied = str(hello.get("token") or "")
            if not expected or not supplied or not __import__("hmac").compare_digest(expected, supplied):
                client.sendall(b'{"ok":false,"error":"unauthorized"}\n')
                return
            client.sendall(b'{"ok":true,"sample_rate":16000,"frame_bytes":640}\n')
            client.settimeout(None)

            def read_audio():
                samples = []
                speech_frames = 0
                silence_frames = 0
                threshold = float(os.environ.get("JARVIS_CALL_VAD_RMS", "330"))
                max_frames = int(15 * RATE * 2 / FRAME_BYTES)
                try:
                    while session_running.is_set():
                        frame = self._read_exact(client, FRAME_BYTES)
                        if frame is None:
                            break
                        import numpy as np
                        pcm = np.frombuffer(frame, dtype="<i2")
                        rms = float(np.sqrt(np.mean(pcm.astype(np.float32) ** 2))) if pcm.size else 0.0
                        if rms >= threshold:
                            samples.append(frame)
                            speech_frames += 1
                            silence_frames = 0
                        elif speech_frames:
                            samples.append(frame)
                            silence_frames += 1
                        if speech_frames and (silence_frames >= 32 or len(samples) >= max_frames):
                            if speech_frames >= 10:
                                try:
                                    utterances.put_nowait(b"".join(samples))
                                except queue.Full:
                                    pass
                            samples, speech_frames, silence_frames = [], 0, 0
                except (OSError, ValueError):
                    pass
                finally:
                    if speech_frames >= 10:
                        try:
                            utterances.put_nowait(b"".join(samples))
                        except queue.Full:
                            pass
                    session_running.clear()
                    try:
                        utterances.put_nowait(None)
                    except queue.Full:
                        pass

            threading.Thread(target=read_audio, daemon=True, name="JarvisCallMic").start()
            print("[JARVIS CALL AUDIO] Two-way audio session connected.", flush=True)
            initial_message = str(hello.get("initial_message") or "").strip()
            if initial_message:
                self._send_reply(client, send_lock, initial_message)
            while session_running.is_set() or not utterances.empty():
                try:
                    utterance = utterances.get(timeout=0.25)
                except queue.Empty:
                    continue
                if utterance is None:
                    break
                try:
                    transcript = self._transcribe(utterance)
                    if not transcript:
                        continue
                    print(f"[JARVIS CALL STT] {transcript}", flush=True)
                    with self._command_lock:
                        answer, _should_speak = self.command_handler(transcript, source="voice_call")
                    if not answer:
                        continue
                    self._send_reply(client, send_lock, str(answer))
                except Exception as exc:
                    print(f"[JARVIS CALL] Turn failed: {type(exc).__name__}: {exc}", flush=True)
            session_running.clear()
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            if self.running:
                print(f"[JARVIS CALL] Session ended: {type(exc).__name__}: {exc}", flush=True)
        finally:
            session_running.clear()
            try:
                client.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                client.close()
            except OSError:
                pass
            with self._active_lock:
                if self._active_socket is client:
                    self._active_socket = None
            print("[JARVIS CALL AUDIO] Session closed.", flush=True)

    def _transcribe(self, pcm_bytes):
        import numpy as np
        with tempfile.NamedTemporaryFile(prefix="jarvis-call-", suffix=".wav", delete=False) as handle:
            wav_path = Path(handle.name)
        try:
            with wave.open(str(wav_path), "wb") as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(RATE)
                output.writeframes(pcm_bytes)
            env = os.environ.copy()
            env["LD_LIBRARY_PATH"] = str(self.needle.parent) + ":" + env.get("LD_LIBRARY_PATH", "")
            result = subprocess.run(
                [str(self.needle), "--model", str(self.model_path), "--audio", str(wav_path), "--audio-language", "en"],
                capture_output=True, text=True, env=env, timeout=30,
            )
            if result.returncode:
                detail = (result.stderr or result.stdout or "")[-400:]
                print(f"[JARVIS CALL STT] Needle exit {result.returncode}: {detail}", flush=True)
                return ""
            output_text = (result.stdout or "").strip()
            payload = None
            try:
                payload = json.loads(output_text)
            except json.JSONDecodeError:
                for line in reversed(output_text.splitlines()):
                    try:
                        candidate = json.loads(line)
                        if isinstance(candidate, dict) and "text" in candidate:
                            payload = candidate
                            break
                    except json.JSONDecodeError:
                        continue
            text = str(payload.get("text") or "").strip() if isinstance(payload, dict) else ""
            return text
        except (OSError, subprocess.TimeoutExpired) as exc:
            print(f"[JARVIS CALL STT] {type(exc).__name__}: {exc}", flush=True)
            return ""
        finally:
            wav_path.unlink(missing_ok=True)

    def _send_reply(self, client, send_lock, text):
        from voice.tts_manager import tts
        path = Path(tts.synthesize_for_call(text))
        try:
            import numpy as np
            with wave.open(str(path), "rb") as source:
                if source.getcomptype() != "NONE":
                    raise RuntimeError("Call TTS returned compressed WAV audio.")
                channels = source.getnchannels()
                width = source.getsampwidth()
                rate = source.getframerate()
                raw = source.readframes(source.getnframes())
            if width == 2:
                audio = np.frombuffer(raw, dtype="<i2").astype(np.float32)
            elif width == 4:
                audio = np.frombuffer(raw, dtype="<i4").astype(np.float32)
            elif width == 1:
                audio = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) * 256.0
            else:
                raise RuntimeError(f"Unsupported TTS WAV sample width: {width}")
            if channels > 1:
                audio = audio.reshape(-1, channels).mean(axis=1)
            if rate != RATE and audio.size:
                new_size = max(1, int(round(audio.size * RATE / rate)))
                old_x = np.arange(audio.size, dtype=np.float64)
                new_x = np.linspace(0, max(0, audio.size - 1), new_size)
                audio = np.interp(new_x, old_x, audio).astype(np.float32)
            pcm = np.clip(audio, -32768, 32767).astype("<i2").tobytes()
            with send_lock:
                for offset in range(0, len(pcm), FRAME_BYTES):
                    frame = pcm[offset:offset + FRAME_BYTES]
                    if len(frame) < FRAME_BYTES:
                        frame += b"\x00" * (FRAME_BYTES - len(frame))
                    client.sendall(frame)
        finally:
            path.unlink(missing_ok=True)
