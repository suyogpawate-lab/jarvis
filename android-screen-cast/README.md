# JARVIS Android companion

This Android 10+ companion provides live screen casting/control and a local
Telecom calling provider. **Calls use the device's existing Phone app UI**;
the companion app is only for one-time setup and background services.

## Local JARVIS calling

The calling path is entirely on this Android device. It does not use a SIM,
carrier number, public VoIP service, or remote call provider.

### One-time setup

1. Install and open this companion app.
2. Tap **Enable JARVIS Phone calls** and grant microphone permission.
3. Tap **Create JARVIS Phone contact** and allow contacts access. This creates
   a contact named **JARVIS**, with local dial string **0** and JARVIS set as
   that contact's preferred calling account.
4. Open **Calling accounts** from the companion app and enable **J.A.R.V.I.S.**
   once. Leave the SIM as the default outgoing account; do not select Ask every
   time and do not make JARVIS the global default.
5. Keep the JARVIS Termux process running. The companion's foreground bridge
   service must remain enabled for incoming call alerts.

Android's ContactsContract supports a preferred PhoneAccountHandle on an
individual phone-number row. Android Telecom consults that preference when
resolving an outgoing contact call, so JARVIS can be selected for this contact
without changing the account used for other contacts.

### Calling JARVIS from the Phone app

- Open the normal Phone app and dial **0**, then tap Call; or
- Search for **JARVIS** in the Phone app's contacts/dial-pad search and tap Call.

Both paths use the JARVIS contact's preferred calling account. No account
chooser should appear for this contact. Ordinary phone numbers continue to
use the SIM/default account. If the dialer does not resolve the single-digit
number to the contact on this device, call **JARVIS** from the contact search;
OEM dialers can differ in short-number lookup behavior.

The 0 dial string is a local route selector only; it is not sent to a carrier
when Telecom resolves the JARVIS contact preference.

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
  spoken replies. If it is stopped, the Phone app may still show the call
  account, but no assistant audio endpoint is available.
- The Android companion must have microphone permission and its calling bridge
  foreground service must be running.
- Android may clear scheduled alarms on reboot; wake-up alarms must be
  re-scheduled after reboot.
- OEM battery management can stop background services; exempt the companion
  and Termux from battery optimization if the device interrupts them.
- This is a local device call provider, not a cellular phone number.
