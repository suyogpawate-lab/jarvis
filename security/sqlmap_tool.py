"""Scoped launcher for the upstream sqlmap CLI.

JARVIS launches sqlmap only when the requested target host is explicitly
allowlisted in JARVIS_SQLMAP_ALLOWED_HOSTS. This is a scope check, not a
network sandbox; use it only for systems you own or are authorized to test.
"""
from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
SQLMAP_DIR = ROOT / "security" / "sqlmap-dev"
SQLMAP_ENTRY = SQLMAP_DIR / "sqlmap.py"
HELP_FLAGS = {"-h", "--help", "-hh", "--version"}


def _env_value(name: str) -> str:
    value = os.getenv(name, "").strip()
    if value:
        return value
    env_file = ROOT / ".env"
    try:
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, raw = line.split("=", 1)
            if key.strip() == name:
                return raw.strip().strip("\\"'").strip()
    except OSError:
        pass
    return ""


def _allowed_hosts() -> set[str]:
    raw = _env_value("JARVIS_SQLMAP_ALLOWED_HOSTS")
    if not raw:
        raw = "localhost,127.0.0.1,::1"
    return {
        item.strip().lower().rstrip(".").strip("[]")
        for item in raw.split(",")
        if item.strip()
    }


def _host_from_url(value: str) -> str:
    value = value.strip()
    parsed = urlsplit(value if "://" in value else "//" + value)
    host = parsed.hostname
    if not host:
        raise ValueError("Target URL must include a valid hostname.")
    return host.lower().rstrip(".").strip("[]")


def _extract_target(args: list[str]) -> tuple[str, str]:
    """Accept one explicit URL (-u/--url) or direct DB connection (-d)."""
    found: list[tuple[str, str]] = []
    blocked = {
        "-r", "--request-file", "-l", "--log-file", "-m", "--bulk-file",
        "-g", "--google-dork", "-c", "--config-file", "--openapi",
    }
    i = 0
    while i < len(args):
        arg = args[i]
        if arg in blocked or any(arg.startswith(flag + "=") for flag in (
            "--request-file", "--log-file", "--bulk-file", "--google-dork",
            "--config-file", "--openapi",
        )):
            raise ValueError(
                f"Target source {arg!r} is disabled by JARVIS's scope guard. "
                "Use one explicit -u/--url target or -d/--direct target."
            )
        if arg in {"-u", "--url", "-d", "--direct"}:
            if i + 1 >= len(args):
                raise ValueError(f"{arg} requires a target value.")
            kind = "url" if arg in {"-u", "--url"} else "direct"
            found.append((kind, args[i + 1]))
            i += 2
            continue
        if arg.startswith("--url="):
            found.append(("url", arg.split("=", 1)[1]))
        elif arg.startswith("--direct="):
            found.append(("direct", arg.split("=", 1)[1]))
        i += 1

    if len(found) != 1:
        raise ValueError(
            "Provide exactly one explicit target: -u/--url URL or "
            "-d/--direct DB_CONNECTION. Indirect/multiple target lists are disabled."
        )
    return found[0]


def _validate_scope(kind: str, target: str) -> str:
    allowed = _allowed_hosts()
    if kind == "url":
        host = _host_from_url(target)
    else:
        parsed = urlsplit(target)
        host = parsed.hostname
        if not host:
            raise ValueError(
                "Direct database targets must specify a hostname; local-file "
                "database targets are not accepted by this launcher."
            )
        host = host.lower().rstrip(".").strip("[]")

    if host not in allowed:
        shown = ", ".join(sorted(allowed)) or "(none)"
        raise ValueError(
            f"Target host {host!r} is not allowlisted. Set "
            "JARVIS_SQLMAP_ALLOWED_HOSTS in .env to a comma-separated list "
            f"of systems you own or are authorized to test. Current allowlist: {shown}"
        )
    return host


def run_sqlmap(command_args: list[str] | str, timeout: int = 1800) -> str:
    """Run sqlmap with argument-list execution (never through a shell)."""
    args = shlex.split(command_args) if isinstance(command_args, str) else list(command_args)

    if not args or args[0].lower() == "help":
        args = ["--help"] if not args or len(args) == 1 else ["--help", *args[1:]]

    if not SQLMAP_ENTRY.is_file():
        return "sqlmap is not installed in security/sqlmap-dev. Run: bash install.sh --skip-setup"

    if any(arg in HELP_FLAGS for arg in args):
        checked_args = args
    else:
        kind, target = _extract_target(args)
        host = _validate_scope(kind, target)
        checked_args = list(args)
        if kind == "url" and "--scope" not in checked_args and not any(
            arg.startswith("--scope=") for arg in checked_args
        ):
            checked_args.extend([
                "--scope",
                r"(?i)^https?://" + re.escape(host) + r"(?::\d+)?(?:/|$)",
            ])
        if "--batch" not in checked_args:
            checked_args.append("--batch")

    try:
        proc = subprocess.run(
            [sys.executable, str(SQLMAP_ENTRY), *checked_args],
            cwd=str(SQLMAP_DIR),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            timeout=max(1, min(int(timeout), 3600)),
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        output = exc.stdout or ""
        if isinstance(output, bytes):
            output = output.decode("utf-8", "replace")
        return (output + "\n[JARVIS] sqlmap timed out; the scan was stopped.").strip()
    except OSError as exc:
        return f"[SQLMAP ERROR] Could not launch sqlmap: {exc}"

    output = (proc.stdout or "").strip()
    if len(output) > 18000:
        output = output[-18000:] + "\n\n[JARVIS] Output truncated to the last 18,000 characters."
    return (output + f"\n[JARVIS] sqlmap exited with code {proc.returncode}.").strip()


def main(argv: list[str] | None = None) -> int:
    print(run_sqlmap(list(sys.argv[1:] if argv is None else argv)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
