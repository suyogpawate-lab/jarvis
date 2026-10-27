#!/usr/bin/env python3
"""Download and validate the small English Phonon checkpoint and voice embeddings."""
from __future__ import annotations

import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = Path(os.environ.get("JARVIS_PHONON_DIR", str(Path.home() / "phonon-model"))).expanduser()
MODEL_URL = "https://huggingface.co/gradium/phonon-31m-en/resolve/main"
VOICE_URL = "https://huggingface.co/gradium/phonon-voices/resolve/main/voices"
FILES = {
    "config.json": (f"{MODEL_URL}/config.json", 100),
    "tokenizer.json": (f"{MODEL_URL}/tokenizer.json", 100),
    "default-voice.safetensors": (f"{MODEL_URL}/default-voice.safetensors", 1000),
    "model.q8.gguf": (f"{MODEL_URL}/model.q8.gguf", 10_000_000),
}
VOICES = {
    "edwin": "zUCxzrOrugTSis03",
    "toby": "dME3IWyZBvmh1n1q",
    "aldric": "gSgG5Tor0GPEnqzC",
    "trevor": "0zLApsZfVLLNaEGl",
    "hugh": "YyKcxPG7iIgS3jsK",
    "spencer": "JOW0vchyswkQUMDS",
    "bramwell": "y2eiKxtQo2B67deU",
}


def download(url: str, destination: Path, minimum_size: int) -> None:
    if destination.is_file() and destination.stat().st_size >= minimum_size:
        print(f"[PHONON] Already present: {destination.name}")
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + ".part")
    last_error = None
    for attempt in range(1, 4):
        try:
            request = urllib.request.Request(
                url, headers={"User-Agent": "JARVIS-Phonon-Setup/1.0"}
            )
            with urllib.request.urlopen(request, timeout=45) as response, partial.open("wb") as out:
                while True:
                    block = response.read(1024 * 1024)
                    if not block:
                        break
                    out.write(block)
            size = partial.stat().st_size
            if size < minimum_size:
                raise RuntimeError(f"download too small ({size} bytes) for {destination.name}")
            partial.replace(destination)
            print(f"[PHONON] Downloaded {destination.name} ({size:,} bytes)")
            return
        except (OSError, urllib.error.URLError, TimeoutError, RuntimeError) as exc:
            last_error = exc
            try:
                partial.unlink(missing_ok=True)
            except OSError:
                pass
            if attempt < 3:
                print(f"[PHONON] Retry {attempt}/3 for {destination.name}: {exc}", file=sys.stderr)
                time.sleep(attempt * 2)
    raise RuntimeError(f"Could not download {destination.name} from {url}: {last_error}")


def main() -> int:
    print(f"[PHONON] Model directory: {MODEL_DIR}")
    try:
        for name, (url, minimum) in FILES.items():
            download(url, MODEL_DIR / name, minimum)
        for name, voice_id in VOICES.items():
            download(
                f"{VOICE_URL}/{voice_id}.safetensors",
                MODEL_DIR / "voices" / f"{name}.safetensors",
                1000,
            )
    except Exception as exc:
        print(f"[PHONON ERROR] {exc}", file=sys.stderr)
        print("[PHONON] Check the network and rerun: python scripts/prepare_phonon_assets.py", file=sys.stderr)
        return 1
    print("[PHONON] Assets ready. The original default voice file was preserved; JARVIS selects Edwin explicitly.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
