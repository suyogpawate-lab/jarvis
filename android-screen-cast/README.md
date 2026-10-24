# JARVIS Screen Cast companion (Android 10+)

This companion is a separate Android app because Android grants live-display capture and Accessibility capabilities to installed apps, not to an ordinary Termux Python process.

## Architecture

- Android MediaProjection captures the display only after the system consent dialog.
- The companion streams JPEG video frames continuously over local TCP to Termux at 127.0.0.1:21340. Each frame has a 4-byte big-endian length prefix. Frames are held in RAM; no recording file is written.
- An Android Accessibility Service provides taps, swipes, focused-field text entry, Back, Home, Recents, and Notifications over local TCP port 21341.
- A foreground notification and Android screen-sharing indicator remain visible during capture.

## Setup

1. Build this Gradle project using Android Studio, Android SDK 35, and JDK 17.
2. Install the debug APK on the same Android device as JARVIS.
3. Open the companion and enable its JARVIS Screen Control Accessibility Service in Android settings.
4. Select Start live cast and accept the Android screen-capture prompt.
5. Update JARVIS in Termux and restart the HTTP bridge.

This repository's CI checks Python syntax and regression tests, not Android compilation. Build and device-test the companion before relying on it.

## Termux configuration

Optional environment overrides:
- JARVIS_SCREEN_STREAM_PORT=21340
- JARVIS_SCREEN_CONTROL_PORT=21341

Configure GEMINI_API_KEYS (or GEMINI_API_KEY) in Termux for visual interpretation. Do not embed API keys in Android source.

## HTTP bridge API (authentication required except /health)

- GET /screen/stream/status — stream freshness, frame count, bytes received, RAM-only status.
- GET /screen/stream/frame — latest JPEG frame.
- POST /screen/analyze with {"prompt":"What is visible?"} — analyze the latest frame using Gemini vision.
- POST /control with {"action":"tap","x":400,"y":500}.
- POST /control with {"action":"swipe","x1":400,"y1":800,"x2":400,"y2":300,"duration_ms":350}.
- POST /control with {"action":"type","text":"example text"}.
- POST /control with {"action":"back"}, home, recents, or notifications.
- POST /chat supports "what's on my screen", "screen back", "screen tap 400 500", "screen swipe 400 800 400 300", and "screen type hello".

Example:
```sh
TOKEN=$(python -c 'import os; from jarvis_env import load_env; load_env(); print(os.environ["JARVIS_HTTP_TOKEN"])'); curl -H "X-Token: $TOKEN" http://127.0.0.1:21339/screen/stream/status
```

Coordinates are physical screen pixels. Android can block capture of secure/DRM content, and Accessibility actions cannot operate every protected screen. Enable Accessibility only if you understand the access it grants.
