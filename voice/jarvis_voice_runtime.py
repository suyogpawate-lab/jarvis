"""Bootstrap and route JARVIS speech through the ZIP's persistent Sherpa server."""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VOICE_ROOT = Path.home() / "jarvis_voice"
SERVER = ROOT / "voice" / "jarvis_voice" / "server.py"
SAY = ROOT / "voice" / "jarvis_voice" / "say"
PREFIX = Path(os.environ.get("PREFIX", "/data/data/com.termux/files/usr"))
SOCKET_FILE = PREFIX / "tmp" / "jarvis_tts.sock"


def _link(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink() and target.resolve() == source.resolve():
        return
    if target.exists() or target.is_symlink():
        if target.is_dir() and not target.is_symlink():
            return
        target.unlink()
    target.symlink_to(source, target_is_directory=source.is_dir())


def prepare_layout() -> None:
    """Map project-local model assets to the paths expected by the ZIP scripts."""
    models = {
        "alan": ("en_GB-alan-medium", "en_GB-alan-medium.onnx"),
        "bryce": ("en_US-bryce-medium", "en_US-bryce-medium.onnx"),
    }
    espeak_candidates = [
        Path(os.environ.get("JARVIS_ESPEAK_DATA", "")).expanduser()
        if os.environ.get("JARVIS_ESPEAK_DATA") else Path("/nonexistent"),
        ROOT / "voice" / "data" / "espeak-ng-data",
        PREFIX / "share" / "espeak-ng-data",
    ]
    espeak = next((p for p in espeak_candidates if p.is_dir() and any(p.iterdir())), None)
    VOICE_ROOT.mkdir(parents=True, exist_ok=True)
    for voice, (model_name, model_file) in models.items():
        source = ROOT / "models" / "sherpa" / voice
        target = VOICE_ROOT / ("vits-piper-" + model_name)
        target.mkdir(parents=True, exist_ok=True)
        for filename in (model_file, "tokens.txt"):
            src = source / filename
            if not src.is_file():
                raise FileNotFoundError(f"Missing Sherpa voice asset: {src}. Run python scripts/prepare_sherpa_assets.py")
            _link(src, target / filename)
        if espeak is None:
            raise FileNotFoundError("eSpeak NG data is missing. Install it with: pkg install espeak-ng")
        _link(espeak, target / "espeak-ng-data")
    (VOICE_ROOT / "fx").mkdir(parents=True, exist_ok=True)


def server_running() -> bool:
    if not SOCKET_FILE.exists():
        return False
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(0.5)
            client.connect(str(SOCKET_FILE))
        return True
    except OSError:
        return False


def ensure_server(timeout: float = 60.0) -> bool:
    """Start the exact ZIP server detached, waiting for its model warmup/socket."""
    if server_running():
        return True
    prepare_layout()
    cache = Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache"))) / "jarvis"
    cache.mkdir(parents=True, exist_ok=True)
    with (cache / "zip_voice_server.log").open("a", encoding="utf-8") as log:
        subprocess.Popen(
            [sys.executable, str(SERVER)],
            cwd=str(ROOT),
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            start_new_session=True,
            close_fds=True,
        )
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if server_running():
            return True
        time.sleep(0.25)
    raise RuntimeError(f"ZIP voice server did not start; inspect {cache / 'zip_voice_server.log'}")


def speak(text: str, voice: str | None = None) -> bool:
    text = str(text or "").strip()
    if not text:
        return False
    if not server_running():
        ensure_server()
    selected = (voice or os.environ.get("JARVIS_SHERPA_VOICE", "alan")).strip().lower()
    if selected not in ("alan", "bryce"):
        selected = "alan"
    result = subprocess.run(
        [sys.executable, str(SAY), selected, text],
        cwd=str(ROOT),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        timeout=15,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "The ZIP say client failed.")
    return True
