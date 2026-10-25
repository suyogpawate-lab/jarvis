#!/usr/bin/env python3
"""Download the two optional Sherpa-ONNX Piper voices used by JARVIS.

Only model weights/configs are downloaded. Token maps are small, versioned
source assets under voice/assets/sherpa; eSpeak NG data comes from Termux.
"""
from __future__ import annotations

import os
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0"
VOICES = {
    "alan": {
        "folder": "en_GB-alan-medium",
        "remote": "en/en_GB/alan/medium",
    },
    "bryce": {
        "folder": "en_US-bryce-medium",
        "remote": "en/en_US/bryce/medium",
    },
}


def download(url: str, destination: Path, minimum: int = 100) -> None:
    if destination.is_file() and destination.stat().st_size >= minimum:
        print(f"[SHERPA] Present: {destination.relative_to(ROOT)}")
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=destination.name + ".", suffix=".part", dir=destination.parent)
    os.close(fd)
    temp = Path(temp_name)
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "JARVIS-Termux-setup"})
        with urllib.request.urlopen(request, timeout=45) as response, temp.open("wb") as output:
            total = 0
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)
                total += len(chunk)
        if total < minimum:
            raise RuntimeError(f"download was unexpectedly small ({total} bytes): {url}")
        os.replace(temp, destination)
        print(f"[SHERPA] Downloaded {destination.relative_to(ROOT)} ({total / 1024 / 1024:.1f} MiB)")
    finally:
        temp.unlink(missing_ok=True)


def main() -> int:
    selected = sys.argv[1:] or list(VOICES)
    for name in selected:
        if name not in VOICES:
            print(f"Unknown voice {name!r}; choose: {', '.join(VOICES)}", file=sys.stderr)
            return 2
        item = VOICES[name]
        model_name = item["folder"] + ".onnx"
        model_dir = ROOT / "models" / "sherpa" / name
        download(f"{BASE}/{item['remote']}/{model_name}", model_dir / model_name, 50_000_000)
        download(f"{BASE}/{item['remote']}/{model_name}.json", model_dir / (model_name + ".json"), 100)
        token_source = ROOT / "voice" / "assets" / "sherpa" / name / "tokens.txt"
        token_target = model_dir / "tokens.txt"
        if not token_source.is_file():
            raise FileNotFoundError(f"Required token map is missing: {token_source}")
        token_target.parent.mkdir(parents=True, exist_ok=True)
        if not token_target.exists() or token_target.read_bytes() != token_source.read_bytes():
            token_target.write_bytes(token_source.read_bytes())
        print(f"[SHERPA] Ready: {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
