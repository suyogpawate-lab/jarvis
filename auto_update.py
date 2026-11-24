"""Safe GitHub updater for a running JARVIS checkout."""
from __future__ import annotations
import os, subprocess, threading, time
from pathlib import Path

class AutoUpdater:
    def __init__(self, root: str | os.PathLike, interval: float = 10.0):
        self.root = Path(root).resolve()
        try: interval = float(os.getenv("JARVIS_UPDATE_INTERVAL", str(interval)))
        except (TypeError, ValueError): interval = 10.0
        self.interval = max(5.0, min(interval, 300.0))
        self.enabled = os.getenv("JARVIS_AUTO_UPDATE", "1").strip().lower() not in {"0", "false", "no", "off"}
        self._pending, self._stop = threading.Event(), threading.Event()
        self._thread, self._lock, self._last_error = None, threading.RLock(), ""
        self._log_path = self.root / "data" / "auto_update.log"

    def _log(self, message):
        try:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            with self._log_path.open("a", encoding="utf-8") as f:
                f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}\n")
        except OSError: pass

    def _git(self, *args, timeout=20):
        return subprocess.run(["git", "-C", str(self.root), *args], text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, check=False)

    def _eligible_checkout(self):
        if not (self.root / ".git").exists(): return False
        branch = self._git("branch", "--show-current")
        return not branch.returncode and branch.stdout.strip() == "main"

    @staticmethod
    def _paths_conflict(changed, untracked):
        return any(incoming == local
            or incoming.startswith(local.rstrip("/") + "/")
            or local.startswith(incoming.rstrip("/") + "/")
            for incoming in changed for local in untracked)

    def poll_once(self):
        if not self.enabled or not self._eligible_checkout(): return False
        with self._lock:
            try:
                fetch = self._git("fetch", "--quiet", "origin", "+refs/heads/main:refs/remotes/origin/main", timeout=35)
                if fetch.returncode: raise RuntimeError(fetch.stderr.strip() or "git fetch failed")
                counts = self._git("rev-list", "--left-right", "--count", "HEAD...origin/main")
                if counts.returncode: raise RuntimeError(counts.stderr.strip() or "cannot compare commits")
                ahead, behind = (int(v) for v in counts.stdout.split())
                if ahead:
                    self._log("Update deferred: local main contains commits not on origin/main.")
                    return False
                if behind:
                    self._pending.set()
                    self._log(f"Update detected: origin/main is {behind} commit(s) ahead.")
                    return True
                self._last_error = ""
                return False
            except Exception as exc:
                message = f"{type(exc).__name__}: {exc}"
                if message != self._last_error:
                    self._log(f"Update check unavailable: {message}")
                    self._last_error = message
                return False

    def _watch(self):
        if self._stop.wait(2.0): return
        while not self._stop.is_set():
            self.poll_once()
            if self._stop.wait(self.interval): break

    def start(self):
        if not self.enabled or self._thread is not None: return False
        self._thread = threading.Thread(target=self._watch, name="jarvis-auto-updater", daemon=True)
        self._thread.start()
        self._log(f"Automatic updater active; polling origin/main every {self.interval:g}s.")
        return True

    @property
    def pending(self): return self._pending.is_set()

    def pending_summary(self, max_items=12):
        """Return a concise changelog for the pending fast-forward update."""
        if not self._pending.is_set():
            return "No update is pending."
        commits = self._git("log", "--oneline", "--no-decorate", "HEAD..origin/main")
        files = self._git("diff", "--name-status", "HEAD", "origin/main")
        commit_lines = [line.strip() for line in commits.stdout.splitlines() if line.strip()]
        file_lines = [line.strip() for line in files.stdout.splitlines() if line.strip()]
        lines = [f"JARVIS update available: {len(commit_lines)} commit(s), {len(file_lines)} changed path(s)."]
        if commit_lines:
            lines.append("Changes:")
            lines.extend(f"  - {line[:180]}" for line in commit_lines[:max_items])
            if len(commit_lines) > max_items:
                lines.append(f"  - ... and {len(commit_lines) - max_items} more commit(s)")
        if file_lines:
            lines.append("Files:")
            lines.extend(f"  - {line[:180]}" for line in file_lines[:max_items])
            if len(file_lines) > max_items:
                lines.append(f"  - ... and {len(file_lines) - max_items} more path(s)")
        lines.append("Nothing has been installed. Type /update approve to install, or /update later to defer.")
        return "\n".join(lines)

    def apply_if_pending(self, approved=False):
        """Apply only after explicit owner approval, from an idle main loop."""
        if not approved:
            self._log("Update remains pending: explicit approval is required.")
            return False
        if not self.enabled or not self._pending.is_set(): return False
        with self._lock:
            if not self._pending.is_set(): return False
            if not self._eligible_checkout():
                self._pending.clear()
                return False
            tracked = self._git("diff", "--quiet", "HEAD", "--")
            staged = self._git("diff", "--cached", "--quiet")
            if tracked.returncode or staged.returncode:
                self._log("Update deferred: local tracked changes are present.")
                self._pending.clear()
                return False
            changed_result = self._git("diff", "--name-only", "HEAD", "origin/main")
            untracked_result = self._git("ls-files", "--others", "--exclude-standard")
            if changed_result.returncode or untracked_result.returncode:
                self._log("Update deferred: could not inspect local file state.")
                self._pending.clear()
                return False
            changed, untracked = set(changed_result.stdout.splitlines()), set(untracked_result.stdout.splitlines())
            if self._paths_conflict(changed, untracked):
                self._log("Update deferred: an untracked local file conflicts with an incoming path.")
                self._pending.clear()
                return False
            if self._git("diff", "--check", "HEAD", "origin/main").returncode:
                self._log("Update rejected: incoming diff failed whitespace validation.")
                self._pending.clear()
                return False
            old_result = self._git("rev-parse", "HEAD")
            if old_result.returncode:
                self._pending.clear()
                return False
            old_sha = old_result.stdout.strip()
            merged = self._git("merge", "--ff-only", "origin/main", timeout=45)
            if merged.returncode:
                self._log(f"Update deferred: fast-forward merge failed: {merged.stderr.strip()}")
                self._pending.clear()
                return False
            for name in sorted(changed):
                if not name.endswith(".py") or not (self.root / name).is_file(): continue
                checked = subprocess.run([os.environ.get("PYTHON", "python"), "-m", "py_compile",
                    str(self.root / name)], cwd=str(self.root), text=True,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20, check=False)
                if checked.returncode:
                    rollback = self._git("reset", "--hard", old_sha, timeout=30)
                    self._log(f"Update rolled back: syntax check failed for {name}; "
                              f"rollback={'ok' if not rollback.returncode else 'FAILED'}.")
                    self._pending.clear()
                    return False
            new_result = self._git("rev-parse", "HEAD")
            new_sha = new_result.stdout.strip() if not new_result.returncode else "unknown"
            self._pending.clear()
            self._log(f"Update installed: {old_sha[:12]} -> {new_sha[:12]}; process reload required.")
            return True

    def stop(self): self._stop.set()
