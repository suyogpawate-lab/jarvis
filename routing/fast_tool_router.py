import subprocess
import json
import time


ROUTER_PROMPT = """You are JARVIS's tool router.

Choose exactly ONE label:

BATTERY
MEMORY
PROCESSES
WIFI
STORAGE
PACKAGES
NOTIFICATIONS
WHATSAPP
EMAIL
JOBS
LAUNCH_APP
OPEN_URL
TOAST
NONE

Rules:
- Output ONLY the label.
- Do not answer the user.
- Do not explain.
- Use NONE when no tool is required.

User: {prompt}
"""


class FastToolRouter:
    def __init__(self, model="qwen2.5:0.5b"):
        self.model = model

    def route(self, prompt):
        text = ROUTER_PROMPT.format(prompt=prompt)

        started = time.perf_counter()

        result = subprocess.run(
            [
                "ollama",
                "run",
                self.model,
                text,
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )

        elapsed = time.perf_counter() - started

        label = result.stdout.strip().upper()

        valid = {
            "BATTERY",
            "MEMORY",
            "PROCESSES",
            "WIFI",
            "STORAGE",
            "PACKAGES",
            "NOTIFICATIONS",
            "WHATSAPP",
            "EMAIL",
            "JOBS",
            "LAUNCH_APP",
            "OPEN_URL",
            "TOAST",
            "NONE",
        }

        if label not in valid:
            label = "NONE"

        return {
            "label": label,
            "latency": round(elapsed, 3),
        }


if __name__ == "__main__":
    router = FastToolRouter()

    tests = [
        "What is my current battery status?",
        "How much memory is available?",
        "What processes are currently running?",
        "What is 2 + 2?",
    ]

    for prompt in tests:
        result = router.route(prompt)
        print(f"{prompt}")
        print(json.dumps(result))
        print()
