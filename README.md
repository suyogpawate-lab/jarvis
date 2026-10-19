# JARVIS

A personal assistant built for Android and Termux. JARVIS combines natural-language conversation, phone and shell actions, persistent memory, web search, optional voice input/output, Gmail and WhatsApp integrations, background jobs, scheduled actions, and a local document knowledge hub.

> **Important:** JARVIS can run commands on your phone and access personal data through permissions you grant it. Risky shell commands require explicit approval by default, but this is a safety net—not a sandbox. Review actions before approving them.

## Install

Use **Termux on Android**. Install [Termux](https://f-droid.org/packages/com.termux/) and the [Termux:API Android app](https://f-droid.org/packages/com.termux.api/) from F-Droid. The installer also installs the Termux-side `termux-api` package.

```bash
pkg update
pkg install -y git
git clone https://github.com/suyogpawate-lab/jarvis.git
cd ~/jarvis
bash install.sh
```

Installer options:

```bash
bash install.sh                 # core install and guided setup
bash install.sh --skip-setup    # install dependencies without launching guided setup
bash install.sh --skip-osint    # skip optional OSINT tool clones/dependencies
bash install.sh --with-voice    # also attempt optional wake-word/STT dependencies and whisper.cpp
bash install.sh --help          # show installer options
```

The optional voice build is large and can fail on Android if native dependencies or compatible Python wheels are unavailable. Core JARVIS does not require the optional voice packages.

## First-time setup and configuration

Run the guided setup from the project directory:

```bash
python setup.py
```

You can also configure one part at a time or inspect configuration status:

```bash
python setup.py keys
python setup.py gmail
python setup.py whatsapp
python setup.py contacts
python setup.py --status
```

| Setup section | What to configure |
|---|---|
| `keys` | Groq, Gemini, Anthropic and OmniRoute provider settings. Optional search/lookup keys include Brave, Bing and Veriphone. |
| `gmail` | Gmail account(s) and a Google [App Password](https://myaccount.google.com/apppasswords), not your normal account password. Enable 2-Step Verification and ensure IMAP access is available. |
| `whatsapp` | Link WhatsApp with a pairing code or QR code. Pairing code is convenient when WhatsApp is on the same phone. |
| `contacts` | Optionally sync Android contacts and maintain a priority-people list. Android may ask for permission. |

Press Enter to keep existing values or skip optional questions. Completed sections are saved as you go.

Secrets and personal state belong in local, git-ignored files such as `.env`, `contacts.json`, `priority_contacts.txt` and `whatsapp/auth/`. Never commit these files or paste API keys into public issues. See [`.env.example`](.env.example) for supported environment variables.

## Start and exit JARVIS

From `~/jarvis`, start the main terminal interface:

```bash
jarvis
```

Or start the simpler command-line interface:

```bash
jarvis-cli
```

Type a request and press **Enter**. The UI shows JARVIS's standby, listening, thinking, speaking and alert states. The plain CLI prints responses and accepts typed or available voice input. Type `exit` or `quit` to leave the CLI; in the UI, use `/q`, `/quit`, `/exit` or **Ctrl-C**.

### Terminal UI keyboard controls

- **Left / Right:** move the cursor; **Ctrl/Alt + Left/Right:** move by word.
- **Home / End** or **Ctrl-A / Ctrl-E:** move to the start/end of the input.
- **Up / Down** or **Ctrl-P / Ctrl-N:** browse previous prompts when not scrolling a long response.
- **Ctrl-Up / Ctrl-Down** or **Page Up / Page Down:** scroll a long response.
- **Backspace / Delete:** edit text; **Ctrl-U:** clear the input line; **Ctrl-W:** delete the previous word.
- The UI has visual-only state previews: `/listening`, `/thinking`, `/speaking`, `/alert`, `/standby`.

## What to ask JARVIS to do

Most tasks are requested in ordinary language. These are examples of supported routes and useful starting prompts; exact results depend on Android permissions, installed apps, configured accounts, network access and running services.

### Phone and system control

Try prompts such as:

```text
open WhatsApp
open Wi-Fi settings
show battery status
show RAM and storage
list installed apps
list running processes
check if whatsapp_daemon.sh is running
```

JARVIS can perform local Android actions, inspect system resources, launch supported apps/settings, inspect processes and run shell commands. App aliases are defined in the code, so an app that is not recognized may need a package-name alias. Phone-control capabilities depend on Termux:API and Android permissions.

### Web search and deeper research

```text
search the web for Android 10 Termux limitations
deep search how Whisper.cpp works on Android pages 10 depth 3
```

A normal web search gathers a small set of results and asks the fast agent to summarize the evidence. `deep search` invokes the deeper research/crawling route. Search providers and results depend on network availability and the configured providers/keys.

### WhatsApp messages and phone calls

Examples:

```text
Ask Rahul on WhatsApp if he can send me the physics notes.
Tell Mom on WhatsApp that I'll be home late.
wa send Rahul "I'll call you later"
call Rahul
```

JARVIS can resolve names from Android contacts and send messages through the linked WhatsApp bridge. Unquoted natural-language requests may have a message drafted; when you need the **exact wording**, put it in quotes as in the `wa send` example. Direct messages and group messages have different flows: **group messages require explicit confirmation** before sending. A `call <contact name>` request uses the Termux phone-call integration; verify the resolved contact before proceeding.

To link or relink WhatsApp, use `python setup.py whatsapp`. Start the bridge separately if it is not already running:

```bash
wa
# or:
bash whatsapp_daemon.sh
```

The main JARVIS runtime also attempts to start the bridge when needed. Do not run multiple copies unnecessarily.

### Gmail

After configuring Gmail with `python setup.py gmail`, ask JARVIS in natural language to search or summarize recent email, find messages, or send an email. Gmail uses IMAP/SMTP and a Google App Password. If several accounts are configured, setup can select a default account. Email access will not work until valid credentials and network connectivity are available.

### Memory and multi-agent discussion

JARVIS has persistent personal/project memory and can use relevant stored context in later responses. Useful explicit commands:

```text
/remember I prefer concise technical explanations
/project JARVIS is installed in ~/jarvis on Termux
/memory
/memory personal
/memory project
/discuss Termux-compatible offline speech recognition
/discuss5m compare local STT options for Android
```

`/remember` saves personal memory; `/project` saves project memory. `/memory` displays memory, with optional `personal` or `project` filters. `/discuss` starts a multi-agent discussion; a duration suffix such as `/discuss5m` requests a five-minute discussion (duration is capped at one hour).

### Shell commands and background jobs

Explicit dispatcher commands include:

```text
/exec <shell command>
/bg start <shell command>
/bg list
/bg status <job-id>
/bg output <job-id>
/bg stop <job-id>
/notifications
```

These let you run a shell command, start/manage background jobs, inspect job output and retrieve active Android notifications. JARVIS can also route many shell/device tasks from natural-language requests.

**Safety approvals:** with the default strict shell policy, some risky shell operations are paused and not executed until you approve them from the interactive JARVIS terminal. Follow the exact response, for example `approve ab12` or `deny ab12`. Codes expire after 10 minutes. Do not approve a command unless you understand its effect. The approval system is not a sandbox; `JARVIS_SHELL_POLICY=off` disables this guard and is not recommended.

### Timers, alarms and scheduled automations

Examples of supported timer/alarm phrasing:

```text
set a timer for 10 minutes
remind me in 20 minutes to check the download
wake me at 6:30 am
remind me tomorrow at 7 pm to study
list automations
cancel auto-<id>
```

Timers and alarms are sent to the Android Clock app through an Android intent. Verify that your Clock app accepted the request. Recurring daily alarms are not automatically configured by this route; set repeat days in Android Clock. JARVIS also supports scheduled automations; use `list automations` to inspect scheduled items and cancel them with their returned ID.

### Notifications

JARVIS can inspect active Android notifications and summarize/analyze them. For example:

```text
show my notifications
summarize my notifications
```

Grant notification access/permissions when Android requests them. Notification availability and content are controlled by Android and the source apps.

## Optional voice input and speech output

The core installer does not force-install all voice dependencies. To attempt the optional voice setup:

```bash
bash install.sh --with-voice
```

This attempts to install voice dependencies, build `whisper.cpp`, and download the English tiny Whisper model. On Android, native packages or microphone libraries may not have compatible builds; a failed optional voice install does not mean the text interface itself is unusable. Grant microphone permission and confirm that Termux can record audio. JARVIS may disable voice input when its listener or model is unavailable. Speech output uses the configured TTS path and may require network access depending on the provider.

## Local Knowledge Hub (RAG/document library)

Start the local document web interface:

```bash
rag
# or:
nohup python knowledge_hub/app.py > /dev/null 2>&1 &
```

Open [http://127.0.0.1:8766](http://127.0.0.1:8766) on the same Android device. Use the page to upload and index `.txt`, `.pdf`, `.docx`, `.jpg`, `.jpeg` or `.png` files, search indexed text, and refresh the document list. PDFs/DOCX files are text-extracted; images are retained and OCR is attempted through Tesseract if available. Uploads are limited to 25 MiB. This is the local knowledge hub interface; its document search is separate from ordinary JARVIS chat unless you explicitly use the relevant integration.

## Shell aliases

The installer adds these aliases to `~/.bashrc` in a managed block and avoids adding a duplicate block on repeated installs.

| Alias | What it does |
|---|---|
| `jarvis` | Start the terminal UI |
| `jarvis-cli` | Start the plain CLI |
| `olser` | Start `ollama serve` in the background |
| `wa` | Start the WhatsApp bridge in the background |
| `omni` | Start the OmniRoute daemon |
| `rag` | Start the local knowledge hub in the background |

After the first install, load aliases in your **current** Termux shell:

```bash
source ~/.bashrc
```

New Termux shells normally load `~/.bashrc` automatically. A script cannot change the parent shell that launched it, so the installer cannot make aliases instantly appear in that already-open shell without this command.

## Localhost services and ports

These services bind to loopback and are intended for use **on the Android device itself**, not directly from other devices on Wi-Fi. A URL will not respond until its service is running.

| Service | Local URL | What it is for |
|---|---|---|
| Knowledge Hub | [http://127.0.0.1:8766](http://127.0.0.1:8766) | Local document upload/search UI |
| WhatsApp bridge | [http://127.0.0.1:23841/status](http://127.0.0.1:23841/status) | JSON connection status for the linked WhatsApp session |
| OmniRoute | [http://127.0.0.1:20128](http://127.0.0.1:20128) | Local API base; not a web dashboard |
| JARVIS HTTP bridge (optional) | [http://127.0.0.1:21339/health](http://127.0.0.1:21339/health) | Health endpoint for the optional HTTP API |

You can use `localhost` in place of `127.0.0.1` for these URLs.

### Optional JARVIS HTTP API

Start the API in a separate Termux session:

```bash
python jarvis_http_bridge.py
```

It listens on `127.0.0.1:21339`. `GET /health` reports service health. API requests to `POST /chat` and `GET/POST /screen` require the `X-Token` header to match `JARVIS_HTTP_TOKEN` in your local `.env`. The chat request body is JSON such as:

```json
{"command": "show battery status"}
```

The `/screen` routes accept screen-layout data for integrations. Do not expose this bridge to a public interface or share the token: it can trigger actions through JARVIS.

## Local model and OmniRoute services

- `olser` starts `ollama serve` in the background. Install/pull a model separately if you want to use local inference, for example `ollama pull qwen2.5:0.5b`; local-model speed depends on device memory and CPU.
- `omni` starts the OmniRoute daemon, which prints its API base URL (`http://127.0.0.1:20128`). JARVIS provider configuration uses `OMNIROUTE_BASE_URL` and `OMNIROUTE_API_KEY`.
- OmniRoute is optional at runtime for some routes, but the current guided setup describes it as part of the full provider configuration. If it fails to install/start, check `omniroute.log` and verify the local endpoint before relying on it.

## Troubleshooting

Check the current configuration and required tools:

```bash
python setup.py --status
```

Useful checks:

- **Missing API keys:** run `python setup.py keys`.
- **Gmail login fails:** use a Google App Password, confirm 2-Step Verification and IMAP access, and rerun `python setup.py gmail`.
- **WhatsApp is offline:** check `http://127.0.0.1:23841/status`, then run `python setup.py whatsapp` if linking is needed. Inspect `data/whatsapp_bridge.log` if present.
- **OmniRoute is offline:** run `omni` and inspect `~/jarvis/omniroute.log`.
- **A port is not responding:** confirm the service is running and listening on the documented port.
- **Termux API actions fail:** install the Termux:API Android app and Termux package, grant the requested Android permissions, and test the relevant `termux-*` command directly.
- **Optional voice setup fails:** use the text interface first; check microphone permission, the model file and native dependency availability before troubleshooting voice packages.

## Data and privacy notes

- Conversation/memory data, logs, local document indexes, and WhatsApp message/session data may contain personal information. Keep the device secure.
- `.env`, contact files, WhatsApp authentication and runtime data are intended to stay local and are git-ignored.
- Gmail uses IMAP/SMTP with an App Password.
- The HTTP bridge requires an `X-Token` header for protected routes and binds to localhost only.
