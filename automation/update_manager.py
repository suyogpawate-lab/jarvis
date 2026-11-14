"""Approval-gated fast-forward updater for JARVIS Git installations.

Checking fetches metadata and presents a changelog. Applying requires an
explicit /update apply command, a clean working tree, the configured branch,
and an unchanged remote target SHA. A backup branch is created before update.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PENDING_FILE = ROOT / "data" / "updates" / "pending.json"
DEFAULT_BRANCH = "main"


class UpdateManager:
    def __init__(self, repo_root=None, runner=None, branch=None):
        self.root = Path(repo_root or ROOT).resolve()
        self.pending_file = (self.root / "data" / "updates" / "pending.json") if repo_root else PENDING_FILE
        self.runner = runner or subprocess.run
        self.branch = str(branch or os.getenv("JARVIS_UPDATE_BRANCH", DEFAULT_BRANCH)).strip()
        if not re.fullmatch(r"[A-Za-z0-9._/-]{1,100}", self.branch):
            raise ValueError("Invalid update branch name.")

    def _git(self, *args, timeout=90):
        return self.runner(
            ["git", *args], cwd=str(self.root), capture_output=True,
            text=True, timeout=timeout, check=False,
        )

    @staticmethod
    def _detail(result):
        return " ".join(str(result.stderr or result.stdout or "").split())[:400]

    def _current_branch(self):
        result = self._git("rev-parse", "--abbrev-ref", "HEAD")
        return result.stdout.strip() if result.returncode == 0 else ""

    def _working_tree_clean(self):
        result = self._git("status", "--porcelain")
        if result.returncode != 0:
            raise RuntimeError("Could not inspect working-tree state: " + self._detail(result))
        return not bool(result.stdout.strip())

    def _save_pending(self, data):
        self.pending_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.pending_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, self.pending_file)

    def _load_pending(self):
        try:
            value = json.loads(self.pending_file.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else None
        except (OSError, ValueError, TypeError):
            return None

    def check(self):
        branch = self._current_branch()
        if not branch:
            return "[UPDATE ERROR] This directory is not a Git checkout."
        if branch != self.branch:
            return (
                f"[UPDATE BLOCKED] Current branch is {branch}; updates are restricted "
                f"to {self.branch}. Switch branches deliberately before checking."
            )
        fetched = self._git("fetch", "--quiet", "origin", self.branch)
        if fetched.returncode != 0:
            return "[UPDATE ERROR] Git fetch failed: " + self._detail(fetched)
        local = self._git("rev-parse", "HEAD")
        remote = self._git("rev-parse", f"origin/{self.branch}")
        if local.returncode != 0 or remote.returncode != 0:
            return "[UPDATE ERROR] Could not resolve local and remote commits."
        local_sha, remote_sha = local.stdout.strip(), remote.stdout.strip()
        if local_sha == remote_sha:
            try:
                self.pending_file.unlink(missing_ok=True)
            except OSError:
                pass
            return "[UPDATE] JARVIS is already up to date."
        count = self._git("rev-list", "--count", f"HEAD..origin/{self.branch}")
        commits = self._git("log", "--format=%s", f"HEAD..origin/{self.branch}")
        stats = self._git("diff", "--stat", f"HEAD..origin/{self.branch}")
        try:
            ahead = int(count.stdout.strip())
        except (ValueError, TypeError):
            return "[UPDATE ERROR] Could not count incoming commits."
        if ahead <= 0:
            return "[UPDATE] No incoming commits were found."
        messages = [line.strip() for line in commits.stdout.splitlines() if line.strip()][:12]
        data = {
            "branch": self.branch, "from_sha": local_sha, "target_sha": remote_sha,
            "commit_count": ahead, "messages": messages,
            "diff_stat": stats.stdout.strip()[:4000], "checked_at": time.time(),
        }
        self._save_pending(data)
        lines = [
            f"[UPDATE AVAILABLE] {ahead} commit(s) on origin/{self.branch}.",
            "Changes:",
        ]
        lines.extend("- " + message[:180] for message in messages)
        if data["diff_stat"]:
            lines.extend(["", "File summary:", data["diff_stat"]])
        lines.extend([
            "",
            f"Current: {local_sha[:12]}",
            f"Target:  {remote_sha[:12]}",
            "No files have been changed. Review this summary, then run /update apply to approve.",
        ])
        return "\n".join(lines)

    def status(self):
        pending = self._load_pending()
        if not pending:
            return "[UPDATE] No pending update approval."
        return (
            f"Pending update: {pending.get('commit_count', 0)} commit(s) "
            f"to {pending.get('branch', self.branch)} "
            f"({str(pending.get('target_sha', ''))[:12]}). "
            "Run /update check to refresh the summary or /update apply to approve."
        )

    def apply(self):
        pending = self._load_pending()
        if not pending:
            return "[UPDATE] No pending update. Run /update check first."
        branch = self._current_branch()
        if branch != self.branch or pending.get("branch") != self.branch:
            return f"[UPDATE BLOCKED] Switch to {self.branch} before applying updates."
        try:
            if not self._working_tree_clean():
                return (
                    "[UPDATE BLOCKED] Your working tree has local changes. "
                    "Commit or back up those changes before updating; nothing was overwritten."
                )
        except RuntimeError as exc:
            return "[UPDATE ERROR] " + str(exc)
        fetched = self._git("fetch", "--quiet", "origin", self.branch)
        if fetched.returncode != 0:
            return "[UPDATE ERROR] Could not refresh remote metadata: " + self._detail(fetched)
        remote = self._git("rev-parse", f"origin/{self.branch}")
        if remote.returncode != 0 or remote.stdout.strip() != pending.get("target_sha"):
            return (
                "[UPDATE STALE] The remote changed after the summary was shown. "
                "Run /update check again; no update was applied."
            )
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = f"backup/pre-update-{stamp}"
        backup_result = self._git("branch", backup, "HEAD")
        if backup_result.returncode != 0:
            return "[UPDATE ERROR] Could not create backup branch: " + self._detail(backup_result)
        merged = self._git("merge", "--ff-only", f"origin/{self.branch}", timeout=180)
        if merged.returncode != 0:
            return (
                "[UPDATE ERROR] Fast-forward update failed: " + self._detail(merged)
                + f"\nBackup branch preserved: {backup}"
            )
        current = self._git("rev-parse", "HEAD")
        if current.returncode != 0 or current.stdout.strip() != pending.get("target_sha"):
            return (
                "[UPDATE ERROR] Post-update verification did not match the approved target. "
                f"Backup branch preserved: {backup}"
            )
        try:
            self.pending_file.unlink(missing_ok=True)
        except OSError:
            pass
        return (
            "[UPDATE APPLIED] JARVIS fast-forwarded successfully.\n"
            f"Backup branch: {backup}\n"
            f"New commit: {pending['target_sha'][:12]}\n"
            "Run /doctor and verify voice, WhatsApp, OmniRoute and workspace services."
        )

    def handle(self, command):
        action = str(command or "").strip().lower()
        if action in {"", "help", "?"}:
            return "/update check\n/update status\n/update apply\nApplying requires a clean working tree and explicit approval."
        if action == "check":
            return self.check()
        if action == "status":
            return self.status()
        if action == "apply":
            return self.apply()
        return "Use /update check, /update status or /update apply."
