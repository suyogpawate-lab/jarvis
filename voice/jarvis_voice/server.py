#!/data/data/com.termux/files/usr/bin/python3
"""Persistent ZIP Sherpa/Piper voice server.

The Unix socket is made available before loading a model. Model initialization is
lazy, so a slow or broken ONNX model cannot masquerade as a server-startup hang.
"""
import gc
import os
import re
import socket
import subprocess
import traceback
from pathlib import Path

PREFIX = Path(os.environ.get("PREFIX", "/data/data/com.termux/files/usr"))
SOCKET_FILE = PREFIX / "tmp" / "jarvis_tts.sock"
TMP_WAV = PREFIX / "tmp" / "jarvis_zip_voice.wav"
VOICE_ROOT = Path.home() / "jarvis_voice"
FX_ROOT = VOICE_ROOT / "fx"

MODELS = {
    "alan": {
        "dir": "vits-piper-en_GB-alan-medium",
        "model": "en_GB-alan-medium.onnx",
        "noise_scale": 0.667,
        "noise_scale_w": 0.8,
        "length_scale": 0.92,
    },
    "bryce": {
        "dir": "vits-piper-en_US-bryce-medium",
        "model": "en_US-bryce-medium.onnx",
        "noise_scale": 0.70,
        "noise_scale_w": 0.85,
        "length_scale": 0.95,
    },
}

active_name = None
active_tts = None


def get_engine(name):
    global active_name, active_tts
    if active_name == name and active_tts is not None:
        return active_tts

    # Keep only one medium-sized model resident at a time on the Android device.
    active_tts = None
    active_name = None
    gc.collect()

    import sherpa_onnx

    cfg = MODELS[name]
    model_dir = VOICE_ROOT / cfg["dir"]
    model_path = model_dir / cfg["model"]
    required = (model_path, model_dir / "tokens.txt", model_dir / "espeak-ng-data")
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError("Missing voice assets: " + ", ".join(missing))

    print(f"[ZIP TTS] Loading {name} model: {model_path}", flush=True)
    tts_config = sherpa_onnx.OfflineTtsConfig(
        model=sherpa_onnx.OfflineTtsModelConfig(
            vits=sherpa_onnx.OfflineTtsVitsModelConfig(
                model=str(model_path),
                tokens=str(model_dir / "tokens.txt"),
                data_dir=str(model_dir / "espeak-ng-data"),
                noise_scale=cfg["noise_scale"],
                noise_scale_w=cfg["noise_scale_w"],
                length_scale=cfg["length_scale"],
            ),
            num_threads=2,
            debug=False,
            provider="cpu",
        )
    )
    engine = sherpa_onnx.OfflineTts(tts_config)
    active_tts = engine
    active_name = name
    print(f"[ZIP TTS] {name} model loaded.", flush=True)
    return engine


def find_tag_file(model_name, tag):
    tag = tag.lower()
    aliases = {"laugh": "chuckle", "clear": "ahem", "hmm": "uhm"}
    resolved = aliases.get(tag, tag)
    folder = FX_ROOT / model_name
    for candidate in (
        folder / f"{resolved}.wav",
        folder / f"{tag}.wav",
        folder / f"trimmed-{model_name}-{resolved}.wav",
    ):
        if candidate.is_file():
            return candidate
    return None


def speak(model_name, text):
    import numpy as np
    import soundfile as sf

    engine = get_engine(model_name)
    pieces = re.split(r"(\[[a-zA-Z0-9_\-]+\])", text)
    audio_segments = []
    sample_rate = None

    for piece in pieces:
        piece = piece.strip()
        if not piece:
            continue
        if piece.startswith("[") and piece.endswith("]"):
            effect = find_tag_file(model_name, piece[1:-1])
            if effect:
                data, rate = sf.read(str(effect), dtype="float32")
                if data.ndim > 1:
                    data = data.mean(axis=1)
                if sample_rate is not None and rate != sample_rate:
                    target_len = int(len(data) * sample_rate / rate)
                    data = np.interp(
                        np.linspace(0, len(data), target_len, endpoint=False),
                        np.arange(len(data)),
                        data,
                    )
                else:
                    sample_rate = rate
                audio_segments.append(data.astype(np.float32))
        else:
            generated = engine.generate(piece, sid=0, speed=1.0)
            if generated.samples is None or len(generated.samples) == 0:
                raise RuntimeError("Sherpa returned empty audio.")
            if sample_rate is not None and generated.sample_rate != sample_rate:
                raise RuntimeError(
                    f"Audio sample-rate mismatch: {sample_rate} vs {generated.sample_rate}"
                )
            sample_rate = generated.sample_rate
            audio_segments.append(np.asarray(generated.samples, dtype=np.float32))

    if not audio_segments:
        return
    audio = np.concatenate(audio_segments)
    sf.write(str(TMP_WAV), audio, sample_rate)
    try:
        result = subprocess.run(
            ["play", "-q", str(TMP_WAV)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            timeout=180,
            check=False,
        )
        if result.returncode:
            raise RuntimeError(
                f"Termux 'play' exited with {result.returncode}: {result.stderr[-500:]}"
            )
    finally:
        try:
            TMP_WAV.unlink()
        except OSError:
            pass


def main():
    SOCKET_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        SOCKET_FILE.unlink()
    except FileNotFoundError:
        pass

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(SOCKET_FILE))
    os.chmod(SOCKET_FILE, 0o600)
    server.listen(4)
    print(f"[ZIP TTS] Socket ready: {SOCKET_FILE}; voice models load on first use.", flush=True)

    try:
        while True:
            conn, _ = server.accept()
            with conn:
                try:
                    chunks = []
                    while True:
                        chunk = conn.recv(4096)
                        if not chunk:
                            break
                        chunks.append(chunk)
                    payload = b"".join(chunks).decode("utf-8").strip()
                    if not payload:
                        conn.sendall(b"OK")
                        continue
                    if ":::" in payload:
                        model_name, text = payload.split(":::", 1)
                    else:
                        model_name, text = "alan", payload
                    if model_name not in MODELS:
                        raise ValueError(f"Unknown voice: {model_name}")
                    if not text.strip():
                        raise ValueError("No text supplied.")
                    speak(model_name, text)
                    conn.sendall(b"OK")
                except Exception as exc:
                    detail = f"{type(exc).__name__}: {exc}"
                    print(f"[ZIP TTS ERROR] {detail}", flush=True)
                    traceback.print_exc()
                    try:
                        conn.sendall(("ERROR: " + detail).encode("utf-8", errors="replace"))
                    except OSError:
                        pass
    finally:
        server.close()
        try:
            SOCKET_FILE.unlink()
        except OSError:
            pass


if __name__ == "__main__":
    main()
