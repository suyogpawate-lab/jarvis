#!/usr/bin/env python3
"""Prepare Piper VITS assets for sherpa-onnx.

Downloads the upstream Piper model/config, preserves the versioned JARVIS token
maps, and writes the metadata sherpa-onnx requires directly into the ONNX
protobuf wire format. This avoids compiling the optional onnx Python package
on constrained platforms such as Android/Termux.
"""
from __future__ import annotations

import datetime
import os
import shutil
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

# ONNX ModelProto.metadata_props is repeated StringStringEntryProto field 14.
# StringStringEntryProto stores key in field 1 and value in field 2.
_METADATA_FIELD_NUMBER = 14


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

    # Sherpa's Piper conversion recipe maps legacy 22500 Hz metadata to 22050 Hz.
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


def _read_varint(data: bytes, offset: int) -> tuple[int, int]:
    value = 0
    shift = 0
    while offset < len(data) and shift < 70:
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if byte < 0x80:
            return value, offset
        shift += 7
    raise RuntimeError("Malformed ONNX protobuf: invalid varint")


def _encode_varint(value: int) -> bytes:
    if value < 0:
        raise ValueError("protobuf varints must be non-negative")
    result = bytearray()
    while value > 0x7F:
        result.append((value & 0x7F) | 0x80)
        value >>= 7
    result.append(value)
    return bytes(result)


def _encode_metadata_entry(key: str, value: str) -> bytes:
    key_bytes = key.encode("utf-8")
    value_bytes = value.encode("utf-8")
    entry = (
        b"\x0a" + _encode_varint(len(key_bytes)) + key_bytes
        + b"\x12" + _encode_varint(len(value_bytes)) + value_bytes
    )
    tag = (_METADATA_FIELD_NUMBER << 3) | 2
    return _encode_varint(tag) + _encode_varint(len(entry)) + entry


def _replace_model_metadata(model_data: bytes, metadata: dict[str, str]) -> bytes:
    """Replace ModelProto field 14 while preserving every other wire field."""
    offset = 0
    preserved = bytearray()
    found_fields = 0

    while offset < len(model_data):
        field_start = offset
        tag, offset = _read_varint(model_data, offset)
        field_number, wire_type = tag >> 3, tag & 7
        if field_number == 0:
            raise RuntimeError("Malformed ONNX protobuf: field number zero")

        if wire_type == 0:
            _, offset = _read_varint(model_data, offset)
        elif wire_type == 1:
            offset += 8
        elif wire_type == 2:
            length, offset = _read_varint(model_data, offset)
            offset += length
        elif wire_type == 5:
            offset += 4
        else:
            raise RuntimeError(
                f"Unsupported protobuf wire type {wire_type} in ONNX ModelProto"
            )

        if offset > len(model_data):
            raise RuntimeError("Malformed ONNX protobuf: field exceeds file size")

        if field_number == _METADATA_FIELD_NUMBER:
            if wire_type != 2:
                raise RuntimeError("Malformed ONNX metadata_props field")
            found_fields += 1
        else:
            preserved.extend(model_data[field_start:offset])

    if offset != len(model_data):
        raise RuntimeError("Malformed ONNX protobuf: trailing bytes")

    for key, value in metadata.items():
        preserved.extend(_encode_metadata_entry(key, value))
    print(f"[SHERPA] Replaced {found_fields} existing metadata field(s)")
    return bytes(preserved)


def _validate_with_onnxruntime(model_path: Path) -> None:
    """Use the already-installed inference runtime when available."""
    try:
        import onnxruntime as ort
    except ImportError:
        print("[SHERPA] onnxruntime not installed; protobuf structure checked only")
        return

    session = ort.InferenceSession(
        str(model_path), providers=["CPUExecutionProvider"]
    )
    if not session.get_inputs() or not session.get_outputs():
        raise RuntimeError("ONNX Runtime loaded the model but found no inputs/outputs")
    print(
        "[SHERPA] ONNX Runtime validation passed "
        f"({len(session.get_inputs())} input(s), {len(session.get_outputs())} output(s))"
    )
    del session


def add_sherpa_metadata(model_path: Path, config_path: Path) -> None:
    """Atomically add/repair sherpa-onnx metadata, retaining a backup."""
    metadata = _metadata_from_piper_config(config_path)
    original = model_path.read_bytes()
    updated = _replace_model_metadata(original, metadata)
    if updated == original:
        print(f"[SHERPA] Metadata unchanged: {model_path.name}")
        return

    fd, temp_name = tempfile.mkstemp(
        prefix=model_path.name + ".", suffix=".metadata.tmp", dir=model_path.parent
    )
    os.close(fd)
    temp = Path(temp_name)
    try:
        temp.write_bytes(updated)
        _validate_with_onnxruntime(temp)

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
        download(f"{BASE}/{item['remote']}/{model_name}.json", config_path, 100)
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
