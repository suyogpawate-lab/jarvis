import os
import re
import socket
import subprocess
import gc
import numpy as np
import sherpa_onnx
import soundfile as sf

SOCKET_FILE = "/data/data/com.termux/files/usr/tmp/jarvis_tts.sock"
TMP_WAV = "/data/data/com.termux/files/usr/tmp/seamless_out.wav"
VOICE_ROOT = os.path.expanduser("~/jarvis_voice")
FX_ROOT = os.path.join(VOICE_ROOT, "fx")

if os.path.exists(SOCKET_FILE):
    os.remove(SOCKET_FILE)

MODELS = {
    "alan": {
        "dir": "vits-piper-en_GB-alan-medium",
        "model": "en_GB-alan-medium.onnx",
        "noise_scale": 0.667,
        "noise_scale_w": 0.8,
        "length_scale": 0.92
    },
    "bryce": {
        "dir": "vits-piper-en_US-bryce-medium",
        "model": "en_US-bryce-medium.onnx",
        "noise_scale": 0.70,
        "noise_scale_w": 0.85,
        "length_scale": 0.95
    }
}

active_name = None
active_tts = None

def get_engine(name):
    global active_name, active_tts
    if active_name == name and active_tts is not None:
        return active_tts

    active_tts = None
    gc.collect()

    cfg = MODELS[name]
    model_dir = os.path.join(VOICE_ROOT, cfg["dir"])
    model_path = os.path.join(model_dir, cfg["model"])

    tts_config = sherpa_onnx.OfflineTtsConfig(
        model=sherpa_onnx.OfflineTtsModelConfig(
            vits=sherpa_onnx.OfflineTtsVitsModelConfig(
                model=model_path,
                tokens=os.path.join(model_dir, "tokens.txt"),
                data_dir=os.path.join(model_dir, "espeak-ng-data"),
                noise_scale=cfg["noise_scale"],
                noise_scale_w=cfg["noise_scale_w"],
                length_scale=cfg["length_scale"]
            ),
            num_threads=4,
            debug=False,
            provider="cpu"
        )
    )
    active_tts = sherpa_onnx.OfflineTts(tts_config)
    active_name = name
    return active_tts

def find_tag_file(model_name, tag):
    tag = tag.lower()
    tag_aliases = {
        "laugh": "chuckle",
        "clear": "ahem",
        "hmm": "uhm"
    }
    resolved_tag = tag_aliases.get(tag, tag)

    model_dir = os.path.join(FX_ROOT, model_name)
    candidates = [
        os.path.join(model_dir, f"{resolved_tag}.wav"),
        os.path.join(model_dir, f"{tag}.wav"),
        os.path.join(model_dir, f"trimmed-{model_name}-{resolved_tag}.wav")
    ]
    for c in candidates:
        if os.path.exists(c):
            return c

    return None

print("[*] Loading default voice (Alan) into RAM...")
get_engine("alan")
print("[*] Dual-Voice (Alan & Bryce) Server Ready.")

server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
server.bind(SOCKET_FILE)
server.listen(5)

while True:
    conn, _ = server.accept()
    raw = b""
    while True:
        chunk = conn.recv(4096)
        if not chunk:
            break
        raw += chunk

    payload = raw.decode("utf-8").strip()
    if payload:
        if ":::" in payload:
            model_req, text = payload.split(":::", 1)
        else:
            model_req, text = "alan", payload

        if model_req not in MODELS:
            model_req = "alan"

        engine = get_engine(model_req)

        tokens = re.split(r'(\[[a-zA-Z0-9_\-]+\])', text)
        audio_segments = []
        target_sample_rate = 22050

        for token in tokens:
            token = token.strip()
            if not token:
                continue

            if token.startswith("[") and token.endswith("]"):
                tag_name = token[1:-1]
                fx_path = find_tag_file(model_req, tag_name)
                if fx_path:
                    data, sr = sf.read(fx_path)
                    if len(data.shape) > 1:
                        data = data.mean(axis=1)

                    if sr != target_sample_rate and len(data) > 0:
                        new_len = int(len(data) * target_sample_rate / sr)
                        data = np.interp(
                            np.linspace(0, len(data), new_len, endpoint=False),
                            np.arange(len(data)),
                            data
                        )
                    audio_segments.append(data.astype(np.float32))
            else:
                gen = engine.generate(token, sid=0, speed=1.0)
                target_sample_rate = gen.sample_rate
                audio_segments.append(np.array(gen.samples, dtype=np.float32))

        if audio_segments:
            full_audio = np.concatenate(audio_segments)
            sf.write(TMP_WAV, full_audio, target_sample_rate)
            subprocess.run(["play", "-q", TMP_WAV])

    conn.close()
