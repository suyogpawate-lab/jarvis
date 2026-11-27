# JARVIS Android companion

This Android 10+ companion provides live screen casting/control and a local
Telecom calling provider. Calls use Android Telecom's normal system call UI;
the companion is used for one-time setup and background audio services.

## Local JARVIS calling

The calling path is entirely on this Android device. It does not use a SIM,
carrier number, public VoIP service, or remote call provider. JARVIS is a
managed ConnectionService account exposed to Android as a separate calling
method.

### One-time setup

1. Install and open this companion app.
2. Tap **Enable JARVIS Phone calls** and grant microphone permission.
3. Tap **Open calling-account settings** and enable **J.A.R.V.I.S.**
4. In the Phone app's calling settings, select **Ask every time** for the
   outgoing account if that option is available. This keeps the SIM available
   for ordinary calls without making JARVIS the global default.
5. Tap **Create JARVIS Phone contact** and allow contacts access. This creates
   or updates a contact named **JARVIS**, with reserved virtual number
   **+1 202-555-0147**.
6. Keep the JARVIS Termux process running. The companion's foreground bridge
   service must remain enabled for incoming call alerts.

### Calling JARVIS from the Phone app

- Open the normal Phone app and select the JARVIS contact.
- When Android asks which calling account to use, choose **J.A.R.V.I.S.**
  for this contact. Choose your SIM for ordinary phone calls.
- The companion's **Open Phone app with JARVIS number** shortcut opens the
  stock dialer with the local number prefilled; it does not place the call.
- Do not choose a SIM for the JARVIS virtual number. The number is a local
  routing token, not a real telephone destination.

Android's public CallRedirectionService.redirectCall() API cannot redirect
a call to an arbitrary app-provided VoIP ConnectionService account; its
target account is restricted to SIM-subscription accounts. Therefore JARVIS
uses the supported Telecom calling-account selection path instead of trying
to redirect a SIM call. The Phone app may ask which account to use; automatic
contact-specific selection is OEM-dependent and is not guaranteed on Lenovo's
Phone app.

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
