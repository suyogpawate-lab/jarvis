"""On-demand visual interpretation of the latest live-stream frame via Gemini."""
from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request

from .receiver import get_receiver


def analyze_latest_screen(prompt: str = "Describe the current screen and the main visible controls.") -> str:
    frame, timestamp = get_receiver().latest_frame()
    if not frame:
        return "Sir, I don't have a live screen frame yet. Open the JARVIS Screen Cast companion, start casting, and try again."
    import time
    if time.time() - timestamp > 5:
        return "Sir, the last screen frame is stale. Check that the companion is still casting, then try again."
    raw_keys = os.environ.get("GEMINI_API_KEYS", "") or os.environ.get("GEMINI_API_KEY", "")
    keys = [item.strip() for item in raw_keys.replace(";", ",").split(",") if item.strip()]
    if not keys:
        return "Sir, the live stream is connected, but screen understanding needs GEMINI_API_KEYS configured for Gemini vision."
    request_text = (prompt or "Describe the current screen.").strip()[:1200]
    payload = {
        "contents": [{
            "role": "user",
            "parts": [
                {"text": "You are JARVIS, interpreting the user's current Android screen. Describe only visible evidence; do not infer hidden content. For action requests, identify visible controls and ask for coordinates only if needed. User request: " + request_text},
                {"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(frame).decode("ascii")}}
            ]
        }],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 500}
    }
    body = json.dumps(payload).encode("utf-8")
    errors = []
    for key in keys:
        url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json", "x-goog-api-key": key}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=20) as response:
                result = json.loads(response.read().decode("utf-8"))
            candidates = result.get("candidates") or []
            parts = (candidates[0].get("content", {}).get("parts", []) if candidates else [])
            answer = " ".join(str(part.get("text", "")) for part in parts if part.get("text")).strip()
            if answer:
                return answer
            errors.append("Gemini returned no text")
        except urllib.error.HTTPError as exc:
            errors.append(f"HTTP {exc.code}")
            if exc.code not in (401, 403, 429):
                break
        except Exception as exc:
            errors.append(type(exc).__name__)
            break
    return "Sir, I received the live frame but couldn't analyze it. Check Gemini vision access and API key configuration (" + ", ".join(errors[:4]) + ")."
