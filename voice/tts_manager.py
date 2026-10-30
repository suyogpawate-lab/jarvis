"""Provider-neutral, punctuation-aware JARVIS speech queue."""
import os
import queue
import subprocess
import tempfile
import threading
import time
import wave
from pathlib import Path

from voice.tts import speak as edge_speak, interrupt as edge_interrupt
from voice.text_chunking import chunk_text, phonon_chunk_text
from voice.spoken import to_speakable

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
    """Edge speaks the whole reply; local engines synthesize ahead of playback."""
    def __init__(self):
        self.queue = queue.Queue(maxsize=64)
        self.running = True
        self.worker_alive = False
        self._gen = 0
        self._proc = None
        self.last_error = ""
        self.last_provider = ""
        self.last_spoken_text = ""
        self.last_started = 0.0
        self.last_finished = 0.0
        self.last_pipeline_metrics = {}
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
        elif _provider() == "phonon":
            threading.Thread(target=self._warm_phonon, daemon=True, name="PhononWarmup").start()

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

    def _warm_phonon(self):
        try:
            from voice.phonon_tts import warmup
            warmup()
            print("[TTS] Phonon persistent worker ready; model preloaded.", flush=True)
        except Exception as exc:
            self.last_error = str(exc)
            print(f"[TTS WARN] Phonon preload failed; CLI fallback remains available: {exc}", flush=True)

    def _run_provider(self, text, speed=1.0, gen=None):
        gen = self._gen if gen is None else gen
        provider = _provider()
        if provider == "say":
            from voice.jarvis_voice_runtime import speak as say_speak
            result = True
            for s in phonon_chunk_text(text):  # first ~50 words, then ~15-word sentence-aligned chunks
                if self._gen != gen:
                    break
                say_speak(s)
        elif provider == "piper":
            result = self._play_pipeline(provider, text, speed, gen)
        elif provider == "sherpa":
            result = self._play_pipeline(provider, text, speed, gen)
        elif provider == "edge":
            result = edge_speak(text, wait=True)
        elif provider == "phonon":
            # The producer synthesizes ahead while one continuous mpv stream plays.
            result = self._play_pipeline(provider, text, speed, gen)
        else:
            raise RuntimeError(f"Unknown JARVIS_TTS_PROVIDER {provider!r}; choose say, edge, piper, sherpa, or phonon.")
        if not result:
            raise RuntimeError(f"{provider} TTS playback failed")
        return provider

    def _speak_with_fallbacks(self, text, speed=1.0, gen=None):
        try:
            with self._active_lock:
                self._active_playback = True
            self.last_provider = self._run_provider(text, speed, gen)
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
                    text, speed, gen = item
                    self.last_spoken_text = str(text).strip()
                    self.last_started = time.monotonic()
                    if self._gen == gen and not self._speak_with_fallbacks(text, speed, gen):
                        # The public speak() API only queues work; report worker
                        # failures so a silent TTS outage is diagnosable in Termux.
                        print(f"[TTS ERROR] {self.last_error or 'Speech playback failed.'}", flush=True)
                finally:
                    self.queue.task_done()
        finally:
            self.worker_alive = False

    # ---- local pipeline: synth sentence N+1 while sentence N plays ----
    def _synth(self, provider, sentence, speed):
        if provider == "piper":
            from voice.piper_tts import _synthesize_to_wav
            return _synthesize_to_wav(sentence)
        if provider == "phonon":
            from voice.phonon_tts import synth
            return synth(sentence)
        from voice import sherpa_tts as st
        import soundfile as sf
        voice = os.environ.get("JARVIS_SHERPA_VOICE", "alan").strip().lower()
        voice = voice if voice in ("alan", "bryce") else "alan"
        audio = st._engine(voice).generate(sentence, sid=0, speed=max(0.5, min(2.0, float(speed))))
        if audio.samples is None or len(audio.samples) == 0:
            raise RuntimeError("Sherpa returned no audio samples.")
        out = st._paths(voice)["output"]
        out.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix="speech-", suffix=".wav", dir=str(out))
        os.close(fd)
        sf.write(name, audio.samples, audio.sample_rate)
        return Path(name)

    def _put(self, q, item, gen):
        while self._gen == gen:
            try:
                q.put(item, timeout=0.2)
                return True
            except queue.Full:
                pass
        return False

    def _play_pipeline(self, provider, text, speed, gen):
        # Local engines share the same buffered policy: no split up to 50
        # words, a ~50-word first chunk, then ~15-word chunks. The producer
        # synthesizes ahead into a two-item queue while mpv plays one stream.
        sentences = phonon_chunk_text(text)

        q = queue.Queue(maxsize=2)  # current chunk + one ready-ahead chunk
        errors = []
        first_ready = threading.Event()
        pipeline_started = time.monotonic()

        def producer():
            try:
                for sentence in sentences:
                    if self._gen != gen:
                        break
                    path = self._synth(provider, sentence, speed)
                    if not self._put(q, path, gen):
                        Path(path).unlink(missing_ok=True)
                        break
                    first_ready.set()
            except Exception as exc:
                errors.append(exc)
            finally:
                first_ready.set()
                self._put(q, None, gen)

        threading.Thread(target=producer, daemon=True, name="TTSSynth").start()
        first_ready.wait()

        proc = None
        audio_format = None
        chunk_count = 0
        starvation_seconds = 0.0
        starvation_events = 0
        first_chunk_seconds = 0.0
        playback_started = None
        interrupted = False

        try:
            while True:
                wait_started = time.monotonic()
                try:
                    path = q.get(timeout=0.2)
                except queue.Empty:
                    waited = time.monotonic() - wait_started
                    if proc is not None and self._gen == gen:
                        starvation_seconds += waited
                        starvation_events += 1
                    if self._gen != gen:
                        interrupted = True
                        break
                    continue

                if path is None:
                    break

                try:
                    if self._gen != gen:
                        interrupted = True
                        break

                    with wave.open(str(path), "rb") as wav:
                        if wav.getcomptype() != "NONE":
                            raise RuntimeError(
                                f"{provider} returned unsupported WAV compression: {wav.getcomptype()}"
                            )
                        params = (
                            wav.getnchannels(),
                            wav.getsampwidth(),
                            wav.getframerate(),
                        )
                        if audio_format is None:
                            channels, sample_width, sample_rate = params
                            formats = {
                                1: "u8",
                                2: "s16le",
                                3: "s24le",
                                4: "s32le",
                            }
                            if sample_width not in formats:
                                raise RuntimeError(
                                    f"Unsupported PCM sample width: {sample_width} bytes"
                                )
                            audio_format = params
                            proc = subprocess.Popen(
                                [
                                    "mpv", "--no-video", "--no-terminal", "--really-quiet",
                                    "--demuxer=rawaudio",
                                    f"--demuxer-rawaudio-format={formats[sample_width]}",
                                    f"--demuxer-rawaudio-rate={sample_rate}",
                                    f"--demuxer-rawaudio-channels={channels}",
                                    "-",
                                ],
                                stdin=subprocess.PIPE,
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL,
                                bufsize=0,
                            )
                            self._proc = proc
                            first_chunk_seconds = time.monotonic() - pipeline_started
                            playback_started = time.monotonic()
                        elif params != audio_format:
                            raise RuntimeError(
                                f"{provider} WAV format changed between chunks: "
                                f"{audio_format} -> {params}"
                            )

                        while self._gen == gen:
                            frames = wav.readframes(8192)
                            if not frames:
                                break
                            try:
                                remaining = memoryview(frames)
                                while remaining:
                                    written = proc.stdin.write(remaining)
                                    if not written:
                                        raise BrokenPipeError("mpv audio pipe accepted zero bytes")
                                    remaining = remaining[written:]
                            except (BrokenPipeError, OSError):
                                if self._gen == gen:
                                    raise RuntimeError("mpv closed its audio input unexpectedly")
                                interrupted = True
                                break

                    chunk_count += 1
                finally:
                    Path(path).unlink(missing_ok=True)
                    q.task_done()

                if interrupted:
                    break

            if proc is not None and proc.stdin and not proc.stdin.closed:
                try:
                    proc.stdin.close()
                except OSError:
                    pass
            if proc is not None and not interrupted and self._gen == gen:
                return_code = proc.wait()
                if return_code:
                    raise RuntimeError(f"mpv exited with status {return_code}")
            elif proc is not None and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
        finally:
            if proc is not None:
                if proc.stdin and not proc.stdin.closed:
                    try:
                        proc.stdin.close()
                    except OSError:
                        pass
                if proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=1.0)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait()
                if self._proc is proc:
                    self._proc = None

        self.last_pipeline_metrics = {
            "chunks": chunk_count,
            "first_chunk_seconds": round(first_chunk_seconds, 3),
            "queue_starvation_seconds": round(starvation_seconds, 3),
            "queue_starvation_events": starvation_events,
            "playback_seconds": round(time.monotonic() - playback_started, 3)
                if playback_started is not None else 0.0,
        }
        if provider == "phonon":
            print(f"[TTS PIPELINE] {self.last_pipeline_metrics}", flush=True)
        if interrupted or self._gen != gen:
            return True
        if errors:
            raise errors[0]
        return True

    def speak(self, text, speed=1.0):
        if text is None:
            return False
        text = to_speakable(text)
        if not text or not self.running:
            return False
        self.interrupt()
        try:
            # Edge gets the whole reply; local engines split into sentences inside _play_pipeline.
            self.queue.put_nowait((text, speed, self._gen))
            return True
        except queue.Full:
            self.clear()
            self.last_error = "TTS client queue full"
            return False

    def speak_blocking(self, text, speed=1.0):
        text = to_speakable(text) if text is not None else ""
        if not text:
            return False
        self.last_spoken_text = text
        self.last_started = time.monotonic()
        return self._speak_with_fallbacks(text, speed, self._gen)

    def interrupt(self):
        self._gen += 1
        proc = self._proc
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except OSError:
                pass
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
        try:
            from voice.phonon_tts import interrupt as phonon_interrupt
            phonon_interrupt()
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
        elif provider == "phonon":
            model = "phonon/" + (os.environ.get("JARVIS_PHONON_VOICE", "").strip() or "default")
            primary = model
        else:
            model = "edge-tts/en-GB-RyanNeural"
            primary = model
        return {
            "worker_alive": self.worker_alive,
            "active_playback": active,
            "primary_provider": primary,
            "last_provider": self.last_provider,
            "last_spoken_text": self.last_spoken_text,
            "last_error": self.last_error,
            "last_started": self.last_started,
            "last_finished": self.last_finished,
            "queue_pending": self.queue.qsize(),
            "pipeline_metrics": dict(self.last_pipeline_metrics),
            "fish_available": False,
            "sherpa_available": provider in ("sherpa", "say"),
            "android_tts_available": False,
            "socket": None,
            "model": model,
        }


tts = TTSManager()
