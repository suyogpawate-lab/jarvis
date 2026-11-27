import threading

import service_launcher
from messaging.whatsapp_autoreply import WhatsAppAutoReplyWorker


def test_service_lifecycle_messages_are_logged_not_printed(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(service_launcher, "LOG_DIR", tmp_path)
    service_launcher._say("OmniRoute started (port 20128).")
    assert capsys.readouterr().out == ""
    assert (tmp_path / "services.log").read_text(encoding="utf-8") == (
        "[SERVICES] OmniRoute started (port 20128).\n"
    )


def test_whatsapp_worker_messages_are_logged_not_printed(tmp_path, capsys):
    worker = object.__new__(WhatsAppAutoReplyWorker)
    worker.data_dir = tmp_path
    worker._log_lock = threading.Lock()
    worker._log("[WHATSAPP AUTO] Bridge connection restored.", flush=True)
    assert capsys.readouterr().out == ""
    assert (tmp_path / "worker.log").read_text(encoding="utf-8") == (
        "[WHATSAPP AUTO] Bridge connection restored.\n"
    )
