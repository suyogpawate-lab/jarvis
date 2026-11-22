from auto_update import AutoUpdater


def test_paths_conflict_detects_exact_and_parent_collisions():
    assert AutoUpdater._paths_conflict({"voice/new.py"}, {"voice/new.py"})
    assert AutoUpdater._paths_conflict({"voice/new.py"}, {"voice"})
    assert AutoUpdater._paths_conflict({"voice"}, {"voice/new.py"})
    assert not AutoUpdater._paths_conflict({"voice/new.py"}, {"data/local.json"})


def test_paths_conflict_handles_multiple_untracked_paths():
    assert not AutoUpdater._paths_conflict(
        {"voice/a.py", "voice/b.py"},
        {"data/cache.json", "notes.txt"},
    )
