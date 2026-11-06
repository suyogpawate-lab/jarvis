#!/usr/bin/env python3
"""Prepare Piper VITS assets for sherpa-onnx.

Downloads the upstream Piper model/config, preserves the versioned JARVIS token
maps, and embeds the metadata sherpa-onnx requires in the ONNX graph. Existing
models are processed too; this makes the operation safe to rerun.
"""
from __future__ import annotations

import datetime
import os
import shutil
import sys
import tempfile
import urllib.request
from pathlib import Path
from typing import Any

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
    fd, temp_name = tempfile.mkstemp(
        prefix=destination.name + ".", suffix=".part", dir=destination.parent
    )
    os.close(fd)
    temp = Path(temp_name)
    try:
        request = urllib.request.Request(
            url, headers={"User-Agent": "JARVIS-Termux-setup"}
        )
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
        print(
            f"[SHERPA] Downloaded {destination.relative_to(ROOT)} "
            f"({total / 1024 / 1024:.1f} MiB)"
        )
    finally:
        temp.unlink(missing_ok=True)


def _metadata_from_piper_config(config_path: Path) -> dict[str, str]:
    import json

    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
        language = config["language"]["name_english"]
        voice = config["espeak"]["voice"]
        speakers = int(config["num_speakers"])
        sample_rate = int(config["audio"]["sample_rate"])
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise RuntimeError(
            f"Invalid Piper model configuration {config_path}: {exc}"
        ) from exc

    # sherpa-onnx's Piper conversion recipe maps legacy 22500 Hz metadata to
    # 22050 Hz, which is the supported VITS output rate for these voice files.
    if sample_rate == 22500:
        sample_rate = 22050
    if not language or not voice or speakers < 1 or sample_rate <= 0:
        raise RuntimeError(f"Incomplete Piper metadata in {config_path}")

    return {
        "model_type": "vits",
        "comment": "piper",
        "language": str(language),
        "voice": str(voice),
        "has_espeak": "1",
        "n_speakers": str(speakers),
        "sample_rate": str(sample_rate),
    }


def add_sherpa_metadata(model_path: Path, config_path: Path) -> None:
    """Atomically add/repair sherpa-onnx metadata, retaining a backup."""
    try:
        import onnx
    except ImportError as exc:
        raise RuntimeError(
            "The ONNX editing package is required to prepare Sherpa voices. "
            "Install it with: python -m pip install onnx"
        ) from exc

    metadata = _metadata_from_piper_config(config_path)
    model = onnx.load(str(model_path), load_external_data=True)
    current = {item.key: item.value for item in model.metadata_props}
    if all(current.get(key) == value for key, value in metadata.items()):
        print(f"[SHERPA] Metadata already valid: {model_path.name}")
        return

    # Replace the metadata set rather than appending duplicate keys. Sherpa
    # reads these keys from the ONNX ModelProto metadata_props field.
    del model.metadata_props[:]
    for key, value in metadata.items():
        entry = model.metadata_props.add()
        entry.key = key
        entry.value = value

    fd, temp_name = tempfile.mkstemp(
        prefix=model_path.name + ".", suffix=".metadata.tmp", dir=model_path.parent
    )
    os.close(fd)
    temp = Path(temp_name)
    try:
        onnx.save(model, str(temp))
        # Validate the temporary graph before touching the working model.
        onnx.checker.check_model(str(temp))

        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = model_path.with_name(model_path.name + f".pre-sherpa-{stamp}.bak")
        shutil.copy2(model_path, backup)
        os.replace(temp, model_path)
        print(f"[SHERPA] Metadata repaired: {model_path.name}")
        print(f"[SHERPA] Original model backup: {backup.name}")
    finally:
        temp.unlink(missing_ok=True)


def main() -> int:
    selected = sys.argv[1:] or list(VOICES)
    for name in selected:
        if name not in VOICES:
            print(
                f"Unknown voice {name!r}; choose: {', '.join(VOICES)}",
                file=sys.stderr,
            )
            return 2

        item = VOICES[name]
        model_name = item["folder"] + ".onnx"
        model_dir = ROOT / "models" / "sherpa" / name
        model_path = model_dir / model_name
        config_path = model_dir / (model_name + ".json")

        download(f"{BASE}/{item['remote']}/{model_name}", model_path, 50_000_000)
        download(
            f"{BASE}/{item['remote']}/{model_name}.json",
            config_path,
            100,
        )
        add_sherpa_metadata(model_path, config_path)

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
