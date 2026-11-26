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

Configure OmniRoute in Termux and select a vision-capable model in OmniRoute for visual interpretation. Do not embed API keys in Android source.

## HTTP bridge API (authentication required except /health)

- GET /screen/stream/status — stream freshness, frame count, bytes received, RAM-only status.
- GET /screen/stream/frame — latest JPEG frame.
- POST /screen/analyze with {"prompt":"What is visible?"} — analyze the latest frame using the configured OmniRoute vision-capable model.
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


## Local JARVIS owner calls (Android 10+)

The companion can register a self-managed Android Telecom account and accept
local incoming-call requests from the Termux HTTP bridge. This does not place a
cellular call, use a SIM, contact a remote caller, or send call data to a provider.
Telecom tracks the local call lifecycle; because this is a self-managed account,
JARVIS displays its own full-screen incoming-call activity and ringing notification
rather than replacing the device's default Phone app.

### Enable once

1. Install/update the companion APK and open it.
2. Tap **Enable local JARVIS calls**. Keep the companion's persistent
   "JARVIS calling ready" notification enabled.
3. Tap **Call JARVIS** in the companion app to start an owner-initiated local Telecom call session.
4. Keep the Termux HTTP bridge running for immediate event-triggered calls.
   Scheduled wake-up alarms are held by Android's AlarmManager and do not require
   Termux to remain running after scheduling. Android clears alarms on reboot,
   so this first version requires wake-ups to be scheduled again after a reboot.

### Local HTTP API

All requests are loopback-only and are accepted by the existing HTTP bridge on
port 21339:

- `GET /owner/status`
- `POST /owner/call` with `{"reason":"overnight_research_complete","message":"Your report is ready.","priority":"normal","source":"overnight_research","event_id":"research-123"}`
- `POST /owner/wakeup` with `{"at_epoch":1795800000,"message":"JARVIS wake-up call","event_id":"wake-1"}`
- `POST /owner/wakeup/cancel` with `{"event_id":"wake-1"}`

Python subsystems can use `jarvis.call_owner(reason, message, priority="normal",
source="jarvis", event_id=None)`. Event IDs are deduplicated locally. The
overnight-research completion callback now uses this API while preserving the
existing notification path.

### Current implementation boundary

This first integration provides Android Telecom call registration, incoming
ringing/full-screen UI, owner-initiated outgoing Telecom sessions, answer/reject/
end lifecycle, local TCP bridge on 127.0.0.1:21342, and device-side exact wake-up
alarms. **Two-way speech is not wired yet**: the outgoing Call JARVIS action
starts a local Telecom session and opens its call screen, while answering an
incoming call marks the session active. Neither path currently connects the
microphone to JARVIS STT or JARVIS TTS to the call audio route. Do not treat it
as a completed voice-call conversation until that audio path is implemented
and tested on the device.

Alarm delivery depends on Android's alarm service and device power state. A
powered-off device cannot ring; OEM battery-management behaviour can also affect
delivery. The app must be opened once after installation so its call bridge can
be enabled. Android 10 device testing is required before relying on this feature.
