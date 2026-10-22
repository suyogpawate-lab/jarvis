"""Starts JARVIS's helper services in the background when JARVIS starts.

Called from jarvis.init_services(), which both jarvis.py (terminal) and
jarvis_ui.py (terminal UI + web UI) run, so either way starts everything.

  OmniRoute       omniroute_daemon.sh        port 20128
  Knowledge Hub   knowledge_hub/app.py       port 8766
  WhatsApp bridge is started by ensure_whatsapp_daemon() in jarvis.py (unchanged).

Each service is checked first, so nothing is started twice. They run detached
(nohup + new session), so they keep running after JARVIS exits.
Set JARVIS_AUTOSTART_SERVICES=0 to turn all of this off.
"""

import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
LOG_DIR = ROOT / "data"

_started = False
_lock = threading.Lock()


def _say(text):
    print(f"[SERVICES] {text}", flush=True)


def _port_open(port, timeout=0.5):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def _wait_for(check, seconds):
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            if check():
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def _detached(cmd, cwd, log_name):
    """Start cmd fully detached from this process and terminal."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    if shutil.which("nohup"):
        cmd = ["nohup"] + list(cmd)
    with open(LOG_DIR / log_name, "a", encoding="utf-8") as log:
        return subprocess.Popen(
            cmd,
            cwd=str(cwd),
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            start_new_session=True,
        )


def _ensure_omniroute():
    if _port_open(20128):
        return _say("OmniRoute already running.")

    script = ROOT / "omniroute_daemon.sh"
    if not script.is_file():
        return _say("OmniRoute skipped: omniroute_daemon.sh not found.")
    if not shutil.which("omniroute"):
        return _say("OmniRoute skipped: the 'omniroute' command is not installed.")

    try:
        # The script itself uses nohup + a pid file and exits right away.
        _detached([shutil.which("bash") or "bash", str(script)], ROOT, "omniroute_start.log")
    except Exception as exc:
        return _say(f"OmniRoute failed to start: {exc}")

    if _wait_for(lambda: _port_open(20128), 30):
        _say("OmniRoute started (port 20128).")
    else:
        _say(f"OmniRoute did not come up. Log: {ROOT / 'omniroute.log'}")


def _hub_healthy():
    return requests.get("http://127.0.0.1:8766/health", timeout=1.5).ok


def _ensure_knowledge_hub():
    if _port_open(8766):
        return _say("Knowledge Hub already running.")

    hub = ROOT / "knowledge_hub"
    if not (hub / "app.py").is_file():
        return _say("Knowledge Hub skipped: knowledge_hub/app.py not found.")

    try:
        proc = _detached([sys.executable, "app.py"], hub, "knowledge_hub.log")
        (LOG_DIR / "knowledge_hub.pid").write_text(str(proc.pid))
    except Exception as exc:
        return _say(f"Knowledge Hub failed to start: {exc}")

    if _wait_for(_hub_healthy, 30):
        _say("Knowledge Hub started (port 8766).")
    else:
        _say(f"Knowledge Hub did not come up. Log: {LOG_DIR / 'knowledge_hub.log'}")


def _run_all():
    workers = [
        threading.Thread(target=_ensure_omniroute, daemon=True),
        threading.Thread(target=_ensure_knowledge_hub, daemon=True),
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()


def start_background():
    """Non-blocking. Safe to call more than once."""
    global _started
    if os.getenv("JARVIS_AUTOSTART_SERVICES", "1") == "0":
        return
    with _lock:
        if _started:
            return
        _started = True
    threading.Thread(target=_run_all, daemon=True).start()

