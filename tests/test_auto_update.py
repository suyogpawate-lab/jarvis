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



def test_update_can_be_deferred_and_rejects_non_main_checkout(tmp_path):
    updater = AutoUpdater(tmp_path)
    updater._pending.set()

    # Explicit deferral remains supported for callers that request it.
    assert updater.apply_if_pending(approved=False) is False
    assert updater.pending is True

    # The idle updater must not mutate a directory that is not a JARVIS main checkout.
    assert updater.apply_if_pending(approved=True) is False
    assert updater.pending is False
