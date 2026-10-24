""""On-demand visual interpretation of the latest live-stream frame via Gemini."""
from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.request

from .receiver import get_receiver

# Prefer current, cost-efficient vision models. Gemini 2.5 remains a final
# compatibility fallback because some newly created projects no longer have
# access to the 2.5 family.
_DEFAULT_MODELS = (
    "gemini-3.5-flash-lite",
    "gemini-3.6-flash",
    "gemini-3.8-flash",
    "gemini-2.5-flash",
)


def _vision_models() -> list[str]:
    preferred = os.environ.get("JARVIS_SCREEN_VISION_MODEL", "").strip()
    return list(dict.fromkeys(([preferred] if preferred else []) + list(_DEFAULT_MODELS)))


def _http_error_detail(exc: urllib.error.HTTPError) -> str:
    """Return a short provider error without ever including request headers."""
    try:
        raw = exc.read(4096).decode("utf-8", errors="replace")
        parsed = json.loads(raw)
        message = parsed.get("error", {}).get("message", "")
        if message:
            return str(message).replace("\\n", " ")[:180]
    except Exception:
        pass
    return f"HTTP {exc.code}"


def analyze_latest_screen(prompt: str = "Describe the current screen and the main visible controls.") -> str:
    frame, timestamp = get_receiver().latest_frame()
    if not frame:
        return "Sir, I don't have a live screen frame yet. Open the JARVIS Screen Cast companion, start casting, and try again."
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
                {"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(frame).decode("ascii")}},
            ],
        }],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 500},
    }
    body = json.dumps(payload).encode("utf-8")
    models = _vision_models()
    errors: list[str] = []

    for key in keys:
        for model in models:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
            req = urllib.request.Request(
                url,
                data=body,
                headers={"Content-Type": "application/json", "x-goog-api-key": key},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=20) as response:
                    result = json.loads(response.read().decode("utf-8"))
                candidates = result.get("candidates") or []
                parts = candidates[0].get("content", {}).get("parts", []) if candidates else []
                answer = " ".join(str(part.get("text", "")) for part in parts if part.get("text")).strip()
                if answer:
                    return answer
                errors.append(f"{model}: no text returned")
            except urllib.error.HTTPError as exc:
                detail = _http_error_detail(exc)
                errors.append(f"{model}: HTTP {exc.code} ({detail})")
                if exc.code == 404:
                    # Model unavailable to this project: try the next supported model.
                    continue
                if exc.code in (401, 403, 429):
                    # Try the next configured key before giving up.
                    break
                return "Sir, Gemini rejected the screen-analysis request: " + detail
            except Exception as exc:
                errors.append(f"{model}: {type(exc).__name__}")
                return "Sir, screen analysis failed while contacting Gemini (" + type(exc).__name__ + ")."

    details = "; ".join(errors[:3])
    if details:
        details = " Details: " + details
    return "Sir, I received the live frame but couldn't analyze it. Check Gemini API access and key configuration." + details
