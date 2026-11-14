"""Tests for approval-gated fast-forward updates."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from automation.update_manager import UpdateManager


class FakeGit:
    def __init__(self, dirty=False):
        self.dirty = dirty
        self.commands = []
        self.merged = False

    def __call__(self, args, **kwargs):
        self.commands.append(args[1:])
        parts = args[1:]
        if parts == ["rev-parse", "--abbrev-ref", "HEAD"]:
            return SimpleNamespace(returncode=0, stdout="main\n", stderr="")
        if parts == ["status", "--porcelain"]:
            return SimpleNamespace(returncode=0, stdout=" M local.py\n" if self.dirty else "", stderr="")
        if parts == ["fetch", "--quiet", "origin", "main"]:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if parts == ["rev-parse", "HEAD"]:
            sha = "remote-sha" if self.merged else "local-sha"
            return SimpleNamespace(returncode=0, stdout=sha + "\n", stderr="")
        if parts == ["rev-parse", "origin/main"]:
            return SimpleNamespace(returncode=0, stdout="remote-sha\n", stderr="")
        if parts == ["rev-list", "--count", "HEAD..origin/main"]:
            return SimpleNamespace(returncode=0, stdout="2\n", stderr="")
        if parts == ["log", "--format=%s", "HEAD..origin/main"]:
            return SimpleNamespace(returncode=0, stdout="Fix bug\nAdd feature\n", stderr="")
        if parts == ["diff", "--stat", "HEAD..origin/main"]:
            return SimpleNamespace(returncode=0, stdout="2 files changed\n", stderr="")
        if len(parts) == 3 and parts[0] == "branch":
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if parts[:2] == ["merge", "--ff-only"]:
            self.merged = True
            return SimpleNamespace(returncode=0, stdout="Fast-forward\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")


class UpdateManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_check_presents_summary_without_applying(self):
        git = FakeGit()
        manager = UpdateManager(repo_root=self.root, runner=git)
        result = manager.check()
        self.assertIn("2 commit(s)", result)
        self.assertIn("Fix bug", result)
        self.assertIn("No files have been changed", result)
        self.assertTrue(manager.pending_file.is_file())
        self.assertFalse(any(command[:2] == ["merge", "--ff-only"] for command in git.commands))

    def test_apply_refuses_dirty_worktree(self):
        git = FakeGit(dirty=True)
        manager = UpdateManager(repo_root=self.root, runner=git)
        manager._save_pending({
            "branch": "main", "target_sha": "remote-sha", "commit_count": 1,
        })
        result = manager.apply()
        self.assertIn("working tree has local changes", result)
        self.assertFalse(any(command and command[0] == "branch" for command in git.commands))
        self.assertFalse(any(command and command[0] == "merge" for command in git.commands))

    def test_apply_creates_backup_before_fast_forward(self):
        git = FakeGit()
        manager = UpdateManager(repo_root=self.root, runner=git)
        manager._save_pending({
            "branch": "main", "target_sha": "remote-sha", "commit_count": 1,
        })
        result = manager.apply()
        self.assertIn("[UPDATE APPLIED]", result)
        backup_index = next(i for i, command in enumerate(git.commands) if command and command[0] == "branch")
        merge_index = next(i for i, command in enumerate(git.commands) if command and command[0] == "merge")
        self.assertLess(backup_index, merge_index)
        self.assertFalse(manager.pending_file.exists())


if __name__ == "__main__":
    unittest.main()
