"""
Shell command guard for ShellExecutor and JobManager.

Not a sandbox - a speed bump. It stops the model (or text injected into it
through WhatsApp, notifications or web pages) from running destructive or
unreviewed commands on its own:

  * a short list of read-only commands runs immediately
  * clearly destructive commands are always blocked
  * everything else is held until the OWNER approves that exact command:
        python jarvis_approve.py yes <code>

JARVIS_SHELL_POLICY=off in .env disables the guard (old behaviour).
"""

import json
import os
import re
import secrets
import shlex
import time
from hashlib import sha256
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PENDING_FILE = ROOT / "data" / "pending_commands.json"
TTL_SECONDS = 600

SAFE_PROGRAMS = {
    "ls", "pwd", "cat", "head", "tail", "wc", "df", "du", "free", "uptime",
    "ps", "date", "whoami", "uname", "echo", "grep", "id", "hostname",
    "getprop", "termux-battery-status", "termux-wifi-connectioninfo",
    "termux-telephony-deviceinfo",
}

# anything that could write, chain, substitute or redirect
FORBIDDEN_CHARS = re.compile(r"[;&`$<>\n\r\\]")

# reading these is never "safe" - they hold keys, sessions, contacts
SENSITIVE = re.compile(
    r"(\.env|/auth\b|whatsapp|contacts|credential|secret|token|password|"
    r"\.ssh|\.netrc|id_rsa|\.db\b|\.pem|\.key\b)",
    re.IGNORECASE,
)

DENY = [
    (re.compile(r"\bmkfs\b"), "formatting a filesystem"),
    (re.compile(r"\bdd\b[^|;]*\bof=/dev/"), "writing to a device"),
    (re.compile(r">\s*/dev/(sd|block|mmcblk)"), "writing to a device"),
    (re.compile(r":\s*\(\s*\)\s*\{"), "a fork bomb"),
    (re.compile(r"\bchmod\b[^|;]*-r[^|;]*\s/(\s|$)"), "recursive chmod on /"),
    (re.compile(r"\b(curl|wget)\b[^;]*\|\s*(sudo\s+)?(ba|z|da)?sh\b"), "piping a download into a shell"),
    (re.compile(r"jarvis_approve|command_guard|pending_commands"), "tampering with the approval system"),
]

RM_TARGET = re.compile(
    r"(\s|=)(/|~|\$home|\$\{home\}|\*|/data|/storage|/sdcard|\.\.?)/?\*?(\s|$)"
)


def _policy():
    return os.environ.get("JARVIS_SHELL_POLICY", "strict").strip().lower()


def _hash(command):
    return sha256(command.strip().encode("utf-8")).hexdigest()


def _load():
    try:
        data = json.loads(PENDING_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save(data):
    PENDING_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = PENDING_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, PENDING_FILE)


def _purge(data):
    now = time.time()
    return {k: v for k, v in data.items() if v.get("expires", 0) > now}


def _denied_reason(command):
    low = command.lower()
    for rx, why in DENY:
        if rx.search(low):
            return why
    if re.search(r"\brm\b", low) and re.search(r"\s(-[a-z]*r|--recursive)", low) \
            and RM_TARGET.search(low + " "):
        return "recursive delete of a broad path"
    return None


def _is_safe(command):
    if FORBIDDEN_CHARS.search(command):
        return False
    for segment in command.split("|"):
        try:
            parts = shlex.split(segment)
        except ValueError:
            return False
        if not parts or os.path.basename(parts[0]) not in SAFE_PROGRAMS:
            return False
        if SENSITIVE.search(" ".join(parts[1:])):
            return False
    return True


def check(command):
    """Return None if the command may run, otherwise a message to show instead."""
    if _policy() == "off":
        return None

    command = str(command).strip()

    why = _denied_reason(command)
    if why:
        return f"[BLOCKED] Refused: {why}. This command was NOT run:\n  {command}"

    if _is_safe(command):
        return None

    digest = _hash(command)
    data = _purge(_load())

    for code, entry in list(data.items()):
        if entry.get("hash") == digest and entry.get("approved"):
            del data[code]            # one-time approval
            _save(data)
            return None

    for code, entry in data.items():
        if entry.get("hash") == digest:
            _save(data)
            return _needs_approval(code, command)

    code = secrets.token_hex(2)
    while code in data:
        code = secrets.token_hex(2)
    data[code] = {
        "hash": digest,
        "command": command,
        "expires": time.time() + TTL_SECONDS,
        "approved": False,
    }
    _save(data)
    return _needs_approval(code, command)


def _needs_approval(code, command):
    return (
        "[NEEDS_APPROVAL] This command is not on the safe list and was NOT run:\n"
        f"  {command}\n"
        "Only the owner can allow it, from a second Termux session:\n"
        f"  python {ROOT}/jarvis_approve.py yes {code}\n"
        "Then ask JARVIS to run the same command again (valid for 10 minutes)."
    )
