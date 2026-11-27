# JARVIS Android companion

This Android 10+ companion provides live screen casting/control and a local
Telecom calling provider. Calls use Android Telecom's normal Phone app UI;
the companion is used for one-time setup and background audio services.

## Local JARVIS calling

The calling path is entirely on this Android device. It does not use a SIM
for the JARVIS conversation, a carrier number, a public VoIP service, or a
remote call provider. JARVIS registers a Telecom ConnectionService as both a
local call provider and a SIM call manager.

### One-time setup

1. Install and open this companion app.
2. Tap **Enable JARVIS Phone calls** and grant microphone permission.
3. Tap **Open calling-account settings** and enable **J.A.R.V.I.S.**
4. In Android's system calling settings, select **J.A.R.V.I.S.** as the
   **SIM call manager** (the wording/location varies by manufacturer).
5. Keep your SIM as the default outgoing phone account. Do not set JARVIS as
   the global outgoing account.
6. Tap **Create JARVIS Phone contact** and allow contacts access. This creates
   or updates a contact named **JARVIS**, with reserved virtual number
   **+1 202-555-0147**.
7. Keep the JARVIS Termux process running. The companion's foreground bridge
   service must remain enabled for incoming call alerts.

### Calling JARVIS from the Phone app

- Open the normal Phone app, search for **JARVIS**, and tap Call.
- When JARVIS is selected as the SIM call manager, Telecom sends outgoing
  SIM calls through the JARVIS ConnectionService first.
- Calls to the reserved JARVIS virtual number are handled locally by JARVIS;
  they do not get sent to the SIM.
- Every other outgoing call is delegated to the originally selected SIM via
  Telecom's createRemoteOutgoingConnection API.
- Incoming SIM calls are delegated back to the SIM via
  createRemoteIncomingConnection. JARVIS-originated incoming calls continue
  to use the local JARVIS call connection.
- The companion's **Open Phone app with JARVIS number** shortcut opens the
  stock dialer with the local number prefilled; it does not place the call.

Android's ConnectionService API explicitly supports this connection-manager
pattern: the manager receives the original SIM PhoneAccount in the request
and can create a RemoteConnection to proxy the call to that SIM. This avoids
the unsupported CallRedirectionService.redirectCall() path, which cannot
target an app-provided VoIP PhoneAccount.

### JARVIS calling you

Any JARVIS subsystem can request an incoming call through the shared
jarvis.call_owner(...) API. Incoming calls are delivered to Telecom with
TelecomManager.addNewIncomingCall, so the existing Phone app handles ringing,
answer/reject, and the in-call screen. Scheduled wake-up calls use Android
AlarmManager.

### Two-way audio pipeline

- Android captures mono 16 kHz PCM16 from AudioRecord using
  VOICE_COMMUNICATION and enables acoustic echo cancellation when available.
- The Android audio service connects to Termux over loopback TCP port 21344.
- The Termux bridge segments speech, transcribes it using the same Needle
  binary/model used by voice.listener, and passes recognized text to
  jarvis.handle_prompt(..., source="voice_call").
- JARVIS synthesizes the response to WAV using its configured local voice
  backend and streams PCM16 back to Android AudioTrack.
- Telecom owns call state and audio routing; the companion does not replace
  the default Phone app.

The control bridge remains on 127.0.0.1:21342; the audio stream is on
127.0.0.1:21344. The audio handshake uses a per-install token stored in
Android private preferences and retrieved over the loopback control bridge.

### Termux API

The existing local HTTP bridge exposes:

- GET /owner/status
- POST /owner/call with reason, message, priority, source, event_id
- POST /owner/wakeup with at_epoch, message, event_id
- POST /owner/wakeup/cancel with event_id

Python callers can use jarvis.call_owner(...) from any subsystem. The
overnight research completion callback is already connected as an example.

### Operational limits

- The Termux JARVIS process must be running to transcribe speech and generate
  spoken replies. If it is stopped, Telecom can still show the calling account,
  but no assistant audio endpoint is available.
- The Android companion must have microphone permission and its calling bridge
  foreground service must be running.
- Android may clear scheduled alarms on reboot; wake-up alarms must be
  re-scheduled after reboot.
- OEM battery management can stop background services; exempt the companion
  and Termux from battery optimization if the device interrupts them.
- This is a local device call provider, not a cellular phone number.
