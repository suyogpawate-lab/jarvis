"""
Shell command guard for ShellExecutor and JobManager.

Not a sandbox - a safety net. Normal commands run straight away. Commands that
delete, kill, uninstall, overwrite secrets, etc. are held until YOU type, in
JARVIS itself:

    approve <code>        (or just: approve, if only one is waiting)
    deny <code>

Only terminal input (jarvis.py / jarvis_ui.py) can approve. WhatsApp, the HTTP
bridge and the model itself cannot.

Routine shell syntax is allowed. Destructive/high-impact actions require typed approval.
"""

import json
import os
import re
import secrets
import time
from hashlib import sha256
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PENDING_FILE = ROOT / "data" / "pending_commands.json"
TTL_SECONDS = 600

# never allowed, even with approval
HARD_DENY = [
    (r"\bmkfs\b", "formatting a filesystem"),
    (r"\bdd\b[^|;]*\bof=/dev/", "writing to a device"),
    (r">\s*/dev/(sd|block|mmcblk)", "writing to a device"),
    (r":\s*\(\s*\)\s*\{", "a fork bomb"),
    (r"\bchmod\b[^|;]*-r[^|;]*\s/(\s|$)", "recursive chmod on /"),
    (r"command_guard|pending_commands", "tampering with the approval system"),
]

# allowed only after you approve
RISKY = [
    # Routine shell syntax is allowed; approval is for destructive or
    # consequential actions, not command complexity.
    (r"\b(rm|rmdir|unlink|shred|truncate)\b", "deletes files"),
    (r"\bfind\b[^|;]*-delete", "deletes files"),
    (r"\bdd\b", "raw disk copy"),
    (r"\b(kill|killall|pkill)\b", "kills processes"),
    (r"\b(chmod|chown|chgrp)\b", "changes permissions"),
    (r"\b(pkg|apt|apt-get|pip|pip3|npm)\s+(uninstall|remove|purge|autoremove)\b", "uninstalls software"),
    (r"\bpm\s+(uninstall|clear|disable|disable-user)\b", "removes or disables an app"),
    (r"\bgit\s+(reset\s+--hard|clean|push\s+(-f|--force))", "destroys git history or files"),
    (r"\b(shutdown|reboot|poweroff|halt)\b", "shuts the device down"),
    (r"\b(su|sudo)\b", "runs as another user"),
    (r"\b(curl|wget)\b[^;]*\|\s*(ba|z|da)?sh\b", "runs a downloaded script"),
    (r"(\.env\b|whatsapp/auth|id_rsa|\.ssh/|creds\.json|contacts\.json|\.netrc)", "touches secrets or personal data"),
    (r"termux-(sms-send|telephony-call)", "sends an SMS or makes a call"),
]

HARD_DENY = [(re.compile(p), why) for p, why in HARD_DENY]
RISKY = [(re.compile(p), why) for p, why in RISKY]
RM_BROAD = re.compile(r"(\s|=)(/|~|\$home|\$\{home\}|\*|/data|/storage|/sdcard|\.\.?)/?\*?(\s|$)")
REPLY_RE = re.compile(r"^\s*(approve|deny)(?:\s+([0-9a-f]{4}))?\s*[.!]?\s*$", re.IGNORECASE)


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


def _hard_denied(low):
    for rx, why in HARD_DENY:
        if rx.search(low):
            return why
    return None


def _risky_reason(low):
    for rx, why in RISKY:
        if rx.search(low):
            return why
    return None


def requires_approval(command):
    """Return whether a command needs a one-time, terminal-approved confirmation."""
    low = str(command or "").strip().lower()
    return bool(_risky_reason(low)) or bool(re.search(
        r"\b(delete|erase|wipe|shred|truncate|format|overwrite|purge|factory\s+reset|reset\s+(?:the\s+)?device)\b",
        low,
    ))


_authorized_once = set()
_authorized_lock = __import__("threading").Lock()


def authorize_command_once(command):
    """Permit one exact command after an enclosing task approval; hard denies remain active."""
    with _authorized_lock:
        _authorized_once.add(_hash(str(command).strip()))


def _consume_authorization(digest):
    with _authorized_lock:
        if digest not in _authorized_once:
            return False
        _authorized_once.remove(digest)
        return True


def revoke_command_authorization(command):
    """Remove an unused one-shot authorization after its dispatch attempt."""
    with _authorized_lock:
        _authorized_once.discard(_hash(str(command).strip()))


def check(command, kind="shell"):
    """Return None if the command may run, otherwise a message to show instead."""
    if _policy() == "off":
        return None

    command = str(command).strip()
    low = command.lower()

    why = _hard_denied(low)
    if why:
        return f"[BLOCKED] Refused: {why}. This command was NOT run:\n  {command}"

    reason = _risky_reason(low)
    if not reason:
        return None

    digest = _hash(command)
    if _consume_authorization(digest):
        return None
    data = _purge(_load())

    for code, entry in list(data.items()):
        if entry.get("hash") == digest and entry.get("approved"):
            del data[code]            # one-time approval
            _save(data)
            return None

    for code, entry in data.items():
        if entry.get("hash") == digest:
            _save(data)
            return _needs_approval(code, command, reason)

    code = secrets.token_hex(2)
    while code in data:
        code = secrets.token_hex(2)
    data[code] = {
        "hash": digest,
        "command": command,
        "kind": kind,
        "reason": reason,
        "expires": time.time() + TTL_SECONDS,
        "approved": False,
    }
    _save(data)
    return _needs_approval(code, command, reason)


def _needs_approval(code, command, reason):
    return (
        f"[NEEDS_APPROVAL] Risky command ({reason}) - NOT run yet:\n"
        f"  {command}\n"
        f"Tell the user to type exactly:  approve {code}   (or: deny {code})\n"
        "Do not approve it yourself. Valid for 10 minutes."
    )


def handle_user_reply(text):
    """Called with the owner's typed message. Returns a reply, or None if the
    message is not an approve/deny answer."""
    m = REPLY_RE.match(text or "")
    if not m:
        return None

    action = m.group(1).lower()
    code = (m.group(2) or "").lower()
    data = _purge(_load())
    waiting = {k: v for k, v in data.items() if not v.get("approved")}

    if not waiting:
        return "Nothing is waiting for approval."

    if not code:
        if len(waiting) > 1:
            lines = [f"  {k}: {v['command']}" for k, v in waiting.items()]
            return "Several commands are waiting. Reply 'approve <code>':\n" + "\n".join(lines)
        code = next(iter(waiting))

    entry = waiting.get(code)
    if not entry:
        return f"No waiting command with code {code} (expired?)."

    command = entry["command"]

    if action == "deny":
        del data[code]
        _save(data)
        return f"Denied. Not run: {command}"

    entry["approved"] = True
    _save(data)

    if entry.get("kind") == "job":
        from automation.job_manager import JobManager
        return f"Approved. Started in background:\n  {command}\n{JobManager().start(command)}"

    from android.shell_executor import ShellExecutor
    return "Approved.\n" + ShellExecutor().execute(command)
