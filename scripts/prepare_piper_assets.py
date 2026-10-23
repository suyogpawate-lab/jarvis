#!/usr/bin/env python3
"""Keep Piper runtime assets inside the JARVIS repository.

Existing external files are copied, not moved or deleted. Termux's shared
libraries are never overwritten; only the private Piper bundle is copied.
"""
import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env"
PREFIX = Path(os.environ.get("PREFIX", "/data/data/com.termux/files/usr")).expanduser()
OLD_LIB = Path.home() / ".local/opt/piper-tts-cli/data/data/com.termux/files/usr/lib"
OLD_MODELS = Path.home() / "piper_models"
DEFAULT_MODEL = "en_GB-alan-medium.onnx"
TARGET_LIB_DIR = ROOT / "lib/piper"
TARGET_MODEL_DIR = ROOT / "models/piper"
TARGET_ESPEAK = ROOT / "voice/data/espeak-ng-data"
TARGET_OUTPUT = ROOT / "cache/piper"


def env_values():
    values = {}
    if ENV_FILE.is_file():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            values[key.strip()] = value.strip().strip("\"'").replace("\\$", "$")
    return values


def copy_file_if_missing(source, target):
    source, target = Path(source).expanduser(), Path(target)
    if source.is_file() and not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        print(f"[PIPER] Copied {source} -> {target}")


def merge_tree_missing(source, target):
    source, target = Path(source).expanduser(), Path(target)
    if not source.is_dir():
        return
    target.mkdir(parents=True, exist_ok=True)
    for item in source.iterdir():
        dest = target / item.name
        if item.is_dir():
            merge_tree_missing(item, dest)
        elif item.is_file() and not dest.exists():
            shutil.copy2(item, dest)


def write_env(values):
    if not ENV_FILE.exists():
        return
    keys = {
        "JARVIS_PIPER_LIBRARY": str(TARGET_LIB_DIR / "libpiper.so"),
        "JARVIS_PIPER_MODEL": str(TARGET_MODEL_DIR / DEFAULT_MODEL),
        "JARVIS_PIPER_CONFIG": str(TARGET_MODEL_DIR / (DEFAULT_MODEL + ".json")),
        "JARVIS_ESPEAK_DATA": str(TARGET_ESPEAK),
        "JARVIS_PIPER_OUTPUT_DIR": str(TARGET_OUTPUT),
    }
    lines = ENV_FILE.read_text(encoding="utf-8").splitlines()
    seen = set()
    updated = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in keys:
                updated.append(f"{key}={keys[key]}")
                seen.add(key)
                continue
        updated.append(line)
    for key, value in keys.items():
        if key not in seen:
            updated.append(f"{key}={value}")
    ENV_FILE.write_text("\n".join(updated) + "\n", encoding="utf-8")


def main():
    for directory in (TARGET_LIB_DIR, TARGET_MODEL_DIR, TARGET_ESPEAK, TARGET_OUTPUT):
        directory.mkdir(parents=True, exist_ok=True)

    values = env_values()
    configured_library = Path(os.environ.get("JARVIS_PIPER_LIBRARY") or values.get("JARVIS_PIPER_LIBRARY") or OLD_LIB / "libpiper.so").expanduser()
    configured_model = Path(os.environ.get("JARVIS_PIPER_MODEL") or values.get("JARVIS_PIPER_MODEL") or OLD_MODELS / DEFAULT_MODEL).expanduser()
    configured_config = Path(os.environ.get("JARVIS_PIPER_CONFIG") or values.get("JARVIS_PIPER_CONFIG") or str(configured_model) + ".json").expanduser()
    configured_espeak = Path(os.environ.get("JARVIS_ESPEAK_DATA") or values.get("JARVIS_ESPEAK_DATA") or PREFIX / "share/espeak-ng-data").expanduser()

    # Copy the private Piper bundle together so its adjacent private runtime
    # and any other bundled dependencies remain available beside libpiper.so.
    if configured_library.is_file():
        merge_tree_missing(configured_library.parent, TARGET_LIB_DIR)
    elif OLD_LIB.is_dir():
        merge_tree_missing(OLD_LIB, TARGET_LIB_DIR)
    copy_file_if_missing(configured_library, TARGET_LIB_DIR / "libpiper.so")

    model_name = DEFAULT_MODEL
    config_name = model_name + ".json"
    target_model = TARGET_MODEL_DIR / model_name
    target_config = TARGET_MODEL_DIR / config_name
    copy_file_if_missing(configured_model, target_model)
    copy_file_if_missing(configured_config, target_config)
    if not target_model.exists():
        copy_file_if_missing(OLD_MODELS / DEFAULT_MODEL, TARGET_MODEL_DIR / DEFAULT_MODEL)
    if not target_config.exists():
        copy_file_if_missing(OLD_MODELS / (DEFAULT_MODEL + ".json"), TARGET_MODEL_DIR / (DEFAULT_MODEL + ".json"))

    merge_tree_missing(configured_espeak, TARGET_ESPEAK)

    # Standardize configuration to repository-local paths; the original
    # external files are intentionally left intact.
    write_env(values)
    print(f"[PIPER] Repository asset paths prepared under {ROOT}")
    print("[PIPER] Missing source assets are not downloaded automatically.")


if __name__ == "__main__":
    main()
