# JARVIS

A personal assistant that lives in Termux on your Android phone. Talk to it in a
terminal UI (or by voice) and it can reason, run shell commands, control the
phone through Termux:API, read and send Gmail, send and read WhatsApp messages,
watch notifications and search the web.

> **JARVIS can run commands on your phone.** Risky commands are flagged, but read
> what it does before you give it access to anything you can't afford to lose.

## Install

You need [Termux](https://f-droid.org/packages/com.termux/) and the
[Termux:API](https://f-droid.org/packages/com.termux.api/) app (both from F-Droid).

```bash
pkg install -y git
git clone https://github.com/suyogpawate-lab/jarvis
cd ~/jarvis
bash install.sh            
```

`install.sh` installs the packages, then starts the guided setup. Re-run it any time;
it only installs what is missing.

## Setup

`python setup.py` walks you through everything personal. Run a single part with
`python setup.py gmail` (also `keys`, `whatsapp`, `contacts`), or check your
configuration with `python setup.py --status`.

| Part | What it does |
|------|--------------|
| keys | **Required:** Groq (tested before saving), Gemini, Anthropic and OmniRoute keys. Optional: Brave, Bing and Veriphone search keys |
| gmail | Gmail address and an [App Password](https://myaccount.google.com/apppasswords) |
| whatsapp | Links your account with an 8-character pairing code (or QR) |
| contacts | Syncs phone contacts and an optional "priority people" list |

All of it is stored on your device in files that git ignores: `.env`,
`contacts.json`, `priority_contacts.txt` and `whatsapp/auth/`. See `.env.example`
for the variables, if you prefer to edit by hand.

## Run

```bash
python jarvis_ui.py            # terminal UI
python jarvis.py               # plain command line
bash whatsapp_daemon.sh        # WhatsApp bridge (keep it in tmux: tmux new -d -s wa 'bash whatsapp_daemon.sh')
python jarvis_http_bridge.py   # optional HTTP API on 127.0.0.1:21339
```

## Notes

- The HTTP bridge requires an `X-Token` header matching `JARVIS_HTTP_TOKEN` in `.env`, and listens on localhost only.
- Gmail uses IMAP/SMTP with an App Password, which needs 2-Step Verification on your Google account.
- Runtime data (memory, conversations, logs, WhatsApp messages) stays in `data/`, `logs/` and `whatsapp/data/`, all git-ignored.

