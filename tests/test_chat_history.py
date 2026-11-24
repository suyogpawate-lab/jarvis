import sqlite3

from memory.chat_history import ChatHistory
from memory.storage import MemoryStorage


def test_chat_sessions_resume_and_clear_only_transcripts(tmp_path):
    db_path = str(tmp_path / "jarvis_memory.db")
    storage = MemoryStorage(db_path=db_path)
    storage.add_memory("personal", "keep this memory", importance=9)
    history = ChatHistory(db_path=db_path)

    first = history.ensure_active()
    history.save("user", "Help me configure my robotics project")
    history.save("assistant", "Let's inspect the project structure.")

    second = history.new_session()
    assert second != first
    history.save("user", "Explain orbital mechanics")

    sessions = history.list_sessions()
    assert {item["code"] for item in sessions} == {first, second}
    first_item = next(item for item in sessions if item["code"] == first)
    assert "robotics project" in first_item["description"]
    assert first_item["message_count"] == 2

    resumed = history.resume(first.lower())
    assert resumed["code"] == first
    messages = history.messages(first)
    assert [item["role"] for item in messages] == ["user", "assistant"]

    with sqlite3.connect(db_path) as db:
        legacy = db.execute("SELECT role, content FROM conversations ORDER BY id").fetchall()
    assert len(legacy) == 2
    assert legacy[0][1] == "Help me configure my robotics project"

    erased = history.clear()
    assert erased == 3
    assert history.list_sessions() == []
    assert history.messages() == []
    assert storage.search_memories("keep this memory", memory_type="personal")
    with sqlite3.connect(db_path) as db:
        assert db.execute("SELECT COUNT(*) FROM conversations").fetchone()[0] == 0
