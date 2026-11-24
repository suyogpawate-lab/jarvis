import threading

from monitoring import token_meter


def test_usage_updates_are_visible_and_thread_safe():
    token_meter.request_started("Groq", "openai/gpt-oss-120b", "initial")
    running = token_meter.snapshot()
    assert running["phase"] == "running"
    assert running["provider"] == "Groq"
    token_meter.request_completed("Groq", "openai/gpt-oss-120b", {
        "prompt_tokens": 100, "completion_tokens": 25, "total_tokens": 125
    })
    done = token_meter.snapshot()
    assert done["phase"] == "complete"
    assert done["prompt_tokens"] == 100
    assert done["completion_tokens"] == 25
    assert done["total_tokens"] == 125


def test_usage_meter_handles_concurrent_writes():
    workers = [
        threading.Thread(target=token_meter.request_started, args=("Groq", f"model-{i}"))
        for i in range(4)
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()
    assert token_meter.snapshot()["phase"] == "running"
