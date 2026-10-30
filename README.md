# JARVIS

A personal assistant built for Android and Termux. JARVIS combines natural-language conversation, phone and shell actions, persistent memory, web search, optional voice input/output, Gmail and WhatsApp integrations, background jobs, scheduled actions, and a local document knowledge hub.

> **Important:** JARVIS can run commands on your phone and access personal data through permissions you grant it. Multi-step tasks run ordinary actions without an extra task-level approval; destructive data-loss actions still pause for confirmation. The shell command guard remains a separate safety layer, not a sandbox.

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
bash install.sh --with-voice    # install OpenWakeWord dependencies + Needle/Whistle STT
bash install.sh --with-phonon   # build ptts and download Phonon q8 model + voice embeddings
bash install.sh --help          # show installer options
```

The optional voice setup downloads the Android ARM64 Needle runner and Whistle speech model, and installs OpenWakeWord dependencies. Python audio dependencies may still fail on Android if compatible wheels are unavailable. Core JARVIS does not require optional voice packages.

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
| `keys` | Groq and OmniRoute model-role settings. Optional search/lookup keys include Brave, Bing and Veriphone. |
| `gmail` | Gmail account(s) and a Google [App Password](https://myaccount.google.com/apppasswords), not your normal account password. Enable 2-Step Verification and ensure IMAP access is available. |
| `whatsapp` | Link WhatsApp with a pairing code or QR code. Pairing code is convenient when WhatsApp is on the same phone. |
| `contacts` | Optionally sync Android contacts and maintain a priority-people list. Android may ask for permission. |
| `voice` | Select Edge TTS, local Sherpa (Alan/Bryce), Piper, or Phonon. You can change this later with `python setup.py voice` or `./voice-config`. |

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

#### Conservative WhatsApp auto-replies

The optional direct-message auto-reply worker uses recent chat history and, when allowed, Knowledge Hub search. It sends a reply only when Groq returns a supported answer with confidence at or above the configured threshold and a stated evidence basis. If facts are missing, intent is ambiguous, or a personal decision is required, JARVIS queues a review instead of sending a guess. In the terminal CLI, review prompts show the incoming message and up to two drafts:

```text
wa-reply <review-id> 1
wa-reply <review-id> 2
wa-reply <review-id> skip
```

Review the draft before approving it. `skip` sends nothing. Messages that need no response are silently skipped. Auto-replies are direct-message only; group messages are not auto-replied to. Replies that require Knowledge Hub attachments are restricted to phone numbers listed in `JARVIS_WA_FILE_CONTACTS` (comma-separated numbers including country code) so private files are not sent to arbitrary contacts. Set `JARVIS_WA_AUTOREPLY=0` to disable the worker.

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
/doctor
/health
/agent help
/agent history
/agent do <goal>
/agent plan <goal>
/agent run <task-id>
/agent status <task-id>
/agent list
/agent approve|deny|cancel <task-id>
/task plan <step 1> || <step 2> [|| ...]
/task run <task-id>
/task status <task-id>
/task list
/task approve <task-id>
/task deny <task-id>
/task cancel <task-id>
/skill help
/skill list
/skill suggest
/skill save <completed-task-id> as <name>
/skill show <name>
/skill run <name>
/exec <shell command>
/bg start <shell command>
/bg list
/bg status <job-id>
/bg output <job-id>
/bg stop <job-id>
/notifications
```

Multi-step plans use the explicit `/task` commands above. Plans are limited to 10 steps, run sequentially, persist under `data/tasks/`, and stop on the first reported failure. The runtime records step starts, results, and durations in an append-only event journal at `data/tasks/agent_events.jsonl`; `/agent history` shows recent events with common credentials redacted. Only clearly read-only requests may be retried once after a transient network/provider failure. Side-effecting requests such as sends and writes are never automatically retried. Event logging is best-effort and cannot block a task if storage is unavailable. **Skill Forge** lets you save a successfully completed task as a reusable local skill: `/skill save task-1234abcd as device-check`. Inspect saved skills with `/skill list` or `/skill show device-check`, then run one with `/skill run device-check`. `/skill suggest` scans completed local task history for repeated workflows that could become skills; this analysis does not call an AI provider. Skills persist under `data/skills/` and run by creating a fresh normal task, so command routing, event journaling, and destructive-step confirmation still apply. Re-running a saved skill does not require another model planning call.

The Agent Engine adds OmniRoute-backed planning and execution. Direct natural-language action requests such as “fix the project tests”, “inspect the codebase”, or “build a CLI tool” are planned and started immediately; task IDs remain internal. `/agent do <goal>` explicitly does the same. `/agent plan <goal>` remains available when you want a review-only plan, and `/agent run <task-id>` remains available for saved workflows. Plans contain at most 8 generated steps, each routed through the existing dispatcher and safeguards. Interrupted workflows are paused for review rather than automatically replayed. `/health` or `/agent health` shows read-only CPU, RAM, swap, storage, and local-service checks. A low-overhead background monitor checks every 5 minutes by default (configurable with `JARVIS_HEALTH_INTERVAL`, minimum 60 seconds) and reports newly appearing warnings; it never kills processes, restarts services, or deletes files. OmniRoute configuration is required for Agent Engine planning and specialist fallbacks. Routine actions—including messages, calls, settings changes, and installs—run without an extra task-level approval. Destructive data-loss actions (such as deleting, wiping, formatting, or overwriting data) pause before execution. For a paused destructive step, `/task approve <id>` (typed in the plain CLI terminal) confirms only that step; `/task deny <id>` cancels the remaining plan. Voice and external sources cannot confirm the destructive step. Each step still goes through the normal dispatcher and its existing guards. This is not a sandbox; outcomes are based on the tool/dispatcher result and still require user verification for external effects.

These let you run a shell command, start/manage background jobs, inspect job output and retrieve active Android notifications. JARVIS can also route many shell/device tasks from natural-language requests.

**Safety approvals:** with the default strict shell policy, some risky shell operations are paused and not executed until you approve them from the interactive JARVIS terminal. Follow the exact response, for example `approve ab12` or `deny ab12`. Codes expire after 10 minutes. Do not approve a command unless you understand its effect. The approval system is not a sandbox; `JARVIS_SHELL_POLICY=off` disables this guard and is not recommended.

### sqlmap security testing tool

JARVIS can invoke the upstream [sqlmap](https://github.com/sqlmapproject/sqlmap) CLI directly, without having an LLM rewrite its arguments. The installer fetches a sparse checkout containing the core runtime only: `sqlmap.py`, `lib/`, `plugins/`, `data/`, `thirdparty/`, `tamper/`, and the upstream license. It excludes documentation, tests, demos, and other auxiliary directories.

Examples:

```text
sqlmap --help
sqlmap -hh
sqlmap -u http://127.0.0.1:8080/vuln.php?id=1 --batch --risk=1 --level=1
```

The last example is for an intentionally vulnerable local lab only. JARVIS's wrapper requires exactly one explicit `-u/--url` or `-d/--direct` target, rejects indirect target lists/config/request-file sources, and checks the target hostname against `JARVIS_SQLMAP_ALLOWED_HOSTS`. By default, only loopback hosts are allowed. To add a system you own or have explicit permission to test, set a comma-separated allowlist in the project `.env`, for example:

```dotenv
JARVIS_SQLMAP_ALLOWED_HOSTS=localhost,127.0.0.1,::1,lab.example
```

Replace `lab.example` with your own authorized lab hostname; do not add public systems without permission. The wrapper passes sqlmap's other CLI options through, including advanced options, and uses `--batch` for non-interactive requests. This hostname check is a guardrail, **not a sandbox**: redirects, DNS changes, and options within sqlmap can affect behavior. Review the target and options before each run. To install or refresh the sparse checkout, run `bash install.sh --skip-setup`. The upstream project's complete option reference is available with `sqlmap -hh` and in its [official usage manual](https://github.com/sqlmapproject/sqlmap/wiki/Usage).

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

This installs OpenWakeWord dependencies and downloads the ARM64 Needle runner and `whistle.cact` model; it no longer builds Whisper.cpp or downloads the Whisper tiny model. Python audio dependencies may still be incompatible with some Android/Termux environments. Grant microphone permission and confirm that the microphone backend works. JARVIS may disable voice input when its listener or model is unavailable. Speech output uses the configured TTS path and may require network access depending on the provider.



### Speech output providers and low-latency chunking

JARVIS keeps Edge TTS as the default and supports local Piper, Sherpa (Alan/Bryce), and Phonon. Choose during setup or change later:

```bash
./voice-config
python setup.py voice
```

Choose **Edge** for the network-based en-GB-RyanNeural voice. **Piper** uses the configured local Piper model/runtime. **Alan/Bryce** use the persistent local Sherpa voice server. **Phonon** uses Gradium's compact English Phonon 31m q8 checkpoint through the Rust `ptts` CLI; Edwin is the default JARVIS voice.

Install Phonon explicitly (the model download and Rust compilation are optional and are not forced on core-only installs):

```bash
bash install.sh --with-phonon
python setup.py voice
```

The installer builds `ptts` with Cargo and downloads the checkpoint files to `~/phonon-model` by default: `config.json`, `tokenizer.json`, `model.q8.gguf`, the original `default-voice.safetensors`, and the supported voice embeddings under `voices/`. It preserves the model's original default-voice file and selects Edwin explicitly. The English q8 weights are about 64.5 MB; Rust compilation needs additional temporary storage and can take several minutes. After the first download, Phonon synthesis works offline. To use another model directory, set `JARVIS_PHONON_DIR`; select the voice with `JARVIS_PHONON_VOICE` (Edwin, Toby, Aldric, Trevor, Hugh, Spencer, Bramwell, or `default`). Optional CPU tuning is available with `JARVIS_PHONON_THREADS`.

All JARVIS-owned Piper assets and generated audio remain in repository-local directories such as `lib/piper/`, `models/piper/`, and `cache/piper/`. Existing Piper asset migration copies rather than moves source files and does not replace Termux shared ONNX Runtime libraries. Sherpa model downloads and Python dependencies are installed only if you choose the Sherpa voice, rather than being downloaded during every core installation. Do not commit model files or private runtime libraries.

Long answers are processed at sentence boundaries, preserving commas and phrase prosody. Local Piper, Sherpa and Phonon synthesize the next sentence while the current sentence plays. A new response interrupts playback and discards queued chunks. The provider and voice preferences are stored in the git-ignored `.env` file.

The acoustic wake phrase is **“Hey Jarvis”**. After the first recognized command, voice input enters continuous-conversation mode: follow-up speech is captured without another wake phrase, and JARVIS returns to wake-word standby after 20 seconds of inactivity by default. Say **“Goodbye Jarvis”** to end the conversation immediately. Configure the idle window with `JARVIS_CONVERSATION_TIMEOUT` (seconds; minimum 5). JARVIS's own TTS playback keeps the conversation active and is muted from input capture. The detector consumes 16 kHz mono signed 16-bit PCM frames; Whistle transcribes each utterance after a pause. Run these checks from `~/jarvis`:

```bash
python scripts/test_voice.py imports
python scripts/test_voice.py files
python scripts/test_voice.py mic
python scripts/test_voice.py stt
python scripts/test_voice.py wakeword
```

`wakeword` tests the real acoustic model against the live microphone for up to 15 seconds; say “Hey Jarvis” when prompted. In `jarvis.py`, recognized commands enter the CLI input queue. In `jarvis_ui.py`, the UI polls that same queue and sends recognized commands through its normal response pipeline. Look for `[VOICE] Microphone stream active` in `data/ui.log` when using the UI, then `[VOICE] Wake phrase detected` and `[VOICE] Recognized command` during a successful end-to-end test.

## Local Knowledge Hub (RAG/document library)

Start the local document web interface:

```bash
rag
# or:
nohup python knowledge_hub/app.py > /dev/null 2>&1 &
```

Open [http://127.0.0.1:8766](http://127.0.0.1:8766) on the same Android device. The upload form accepts an optional display filename; the original file extension is preserved, and re-uploading identical content updates its display name. Text-search indexing is available for `.txt`, `.pdf`, and `.docx`; common images are retained and OCR is attempted through Tesseract if available. Other retained assets include GIFs, common image/video/audio formats, archives (ZIP/TAR/GZ/7Z/RAR), structured/text files (CSV/JSON/XML/YAML/Markdown/logs/source code), and common office/e-book formats (DOC/XLS/PPTX/ODT/ODS/EPUB). Non-text assets are discoverable by filename and can be attached by the WhatsApp worker when a contact clearly asks for a matching item and that contact is allowed by `JARVIS_WA_FILE_CONTACTS`. GIFs are converted to WhatsApp-compatible animated MP4s when `ffmpeg` is available; otherwise the original GIF is sent as a document. Video and audio assets use the bridge's native media send path. Uploads are limited to 25 MiB. This is the local Knowledge Hub interface; its document search is separate from ordinary JARVIS chat unless you explicitly use the relevant integration.

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
- OmniRoute supplies specialist coding/reasoning, screen vision fallback, and sustained Groq-quota fallback. Simple Groq routes can still work without it. If it fails to install/start, check `omniroute.log` and verify the local endpoint.

## Project architecture and source map

The repository is organized as a Python application with optional Android/Termux integrations and a small Node.js WhatsApp bridge. The main execution path is the CLI/UI or an optional local HTTP interface, which delegates requests to the shared dispatcher and its service modules.

| Path | Responsibility |
|---|---|
| `jarvis.py` | Main terminal CLI, interactive command loop, memory commands, discussion commands, and service coordination. |
| `jarvis_ui.py` | Rich terminal interface and input/response presentation. |
| `core/` | Main `Jarvis` reasoning client and multi-agent discussion coordination. |
| `automation/command_dispatcher.py` | Parses explicit commands and coordinates abilities, search, local AI, autonomous execution, messaging, and scheduled work. |
| `agents/` | Fast agent, autonomous execution loop, local Ollama adapter, and provider adapters for Groq, Ollama, and OmniRoute. |
| `routing/` | Discussion topic classification, model registry/pool, and fast-tool routing helpers. |
| `android/` | Android app aliases and device actions, shell execution, process/system inspection, and risky-command approval guard. |
| `config/abilities.json` | Declarative abilities registry used by the dispatcher and reasoning layer. |
| `memory/` | Personal/project memory, conversation history, episodes, and SQLite-backed storage under local runtime data. |
| `automation/` | Command dispatch, persistent background jobs, and timezone-aware scheduled automations. |
| `search/` | Normalized multi-provider search, web-engine/community providers, Tor transport, and adaptive deep-research crawling. |
| `messaging/` | Android contact lookup, Gmail IMAP/SMTP, WhatsApp orchestration, and WhatsApp-related helpers. |
| `whatsapp/` | Node.js Baileys bridge, package manifest, and local WhatsApp session integration. |
| `monitoring/` | System telemetry, notifications, alerts, notification ingestion, and watchers. |
| `voice/` | Optional OpenWakeWord listener, Whistle speech recognition through the Needle ARM64 runner, audio handling, and TTS components. |
| `knowledge_hub/` | Local Flask document library with SQLite full-text search, supported document extraction, and an upload/search page. |
| `jarvis_http_bridge.py` | Optional token-protected localhost HTTP bridge for chat and transient screen-state data. |
| `jarvis_bridge.py`, `jarvis_web.py`, `web/`, `web-ip.py` | Additional bridge/web entry points and web assets; these are separate from the default terminal workflow. |
| `osint/` | Pluggable OSINT adapters, registry/team orchestration, and result formatting. Optional dependencies are listed separately. |
| `workers/` | Worker registry and adapters for supported external/local coding or task workers, including OpenCode and OWL integration points. |
| `tools/` | Tool registry with argument-contract validation, skill loading, progress reporting, and MCP client integration. |
| `skills/` | Bundled operational and interface-design skill instructions. |
| `scripts/` | Voice test, app-inventory capture, and publishing checks. |
| `install.sh`, `setup.py`, `jarvis_env.py` | Termux installation, guided configuration, and environment loading. |
| `requirements*.txt`, `packages/` | Core and optional Python dependency lists plus Node package metadata. |

### Request and service flow

1. The CLI/UI receives typed input; the optional voice listener can place a recognized command into the same application flow when its dependencies and model files are available.
2. `CommandDispatcher` handles explicit slash commands and deterministic local abilities, and initializes the search hub, deep-search engine, local AI adapter, fast agent, autonomous agent, and scheduler.
3. The fast agent uses the configured Groq API for fast model requests and can use configured provider fallbacks and registered tools. The core reasoning client uses the configured OmniRoute-compatible endpoint. Actual route selection depends on the request, provider configuration, and service availability.
4. Device actions are implemented through the Android/Termux layer. Risky shell operations are gated by the command guard by default; this guard is a safety check, not a sandbox.
5. Persistent memory and job/automation state are stored in local runtime data. Gmail and WhatsApp require separately configured credentials/session state; the WhatsApp manager talks to the local Baileys bridge.

### Dependency boundaries

- **Core:** `requirements.txt` contains the primary Python runtime dependencies.
- **Voice:** `requirements-voice.txt` lists optional wake-word/audio packages. The installer’s `--with-voice` option downloads the Needle ARM64 runner and Whistle model. Python audio dependencies can be platform-sensitive on Android; voice is not required for typed interaction.
- **OSINT:** `requirements-osint.txt` contains additional optional packages for selected OSINT integrations; some adapters may have their own external tool/runtime requirements.
- **WhatsApp:** `whatsapp/package.json` and its lockfile define the Node.js Baileys bridge dependencies.
- **Configuration:** `.env.example` documents provider and integration variables. Use `python setup.py` for guided setup; the real `.env`, account credentials, contact lists, authentication sessions, and runtime databases must remain local.

### Review and verification scope

This README describes the tracked source layout and intended integration boundaries. It does not imply that every optional provider, native Android action, external worker, or account integration has been exercised on every device. Installation success and runtime behavior depend on Termux packages, Android permissions, network access, valid credentials, model files, and optional services. Use the troubleshooting section below to verify each configured integration on the target device.

## Local regression checks

Run the Phase 1 syntax scan and deterministic regression tests before trying new features:

```bash
python scripts/smoke_test.py
# Or run only the unit tests:
python -m unittest discover -s tests -v
```

These checks are local-only: they do not call Groq, OmniRoute, or other providers, and they do not launch apps or send messages. The tests cover app-name normalization, aliases, nickname resolution, and safe handling of ambiguous matches. They do not replace live checks of Android permissions, microphone capture, or configured providers.

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


## Mission memory and diagnostics

JARVIS includes local mission history analysis alongside its task executor and Skill Forge. It inspects saved task JSON records without making an AI/API request.

```text
/agent insights
/agent learn
/agent diagnose task-1234abcd
/agent recall battery
```

- **Insights** summarizes saved task outcomes and recurring failed-step commands.
- **Diagnose** explains the recorded state of a task, including its failed step and result.
- **Recall** searches prior goals, commands, and results on-device.
- These commands are read-only. They do not execute, resume, or automatically retry a task.
- A task marked completed means the executor finished its steps; it is not independent proof that an external side effect occurred.
- Sensitive-looking key/token/password values are redacted in displayed snippets, but keep local task data private.

The Skill Forge can turn a successfully completed workflow into a reusable local skill:

```text
/skill help
/skill list
/skill suggest
/skill save task-1234abcd as device-check
/skill show device-check
/skill run device-check
```

Saving a skill requires a completed task. Running one creates a fresh task and uses the normal dispatcher and its existing safeguards.


## Message personality and multi-skill installation

Configure the wording JARVIS uses for WhatsApp drafts and automatic replies:

```bash
python setup.py message_style
```

Choose **mirror**, **casual**, **Gen Z**, **friendly**, or **formal**; set a preferred language such as English or Hinglish; and optionally give examples of your normal phrasing (for example, `damnnn, gng`). These preferences are stored in the local `.env` file. The style is a default, not a blind rule: when you explicitly request professional wording or the context calls for a teacher/employer/official message, serious matter, apology, or formal request, JARVIS switches to respectful formal language. It should not force slang into every message. The same policy is used by outbound WhatsApp drafting and the direct-message auto-reply worker.

Install multiple Agent Skills from a GitHub repository or a folder containing multiple `SKILL.md` files:

```bash
python skills/multi_install.py https://github.com/owner/repository --list
python skills/multi_install.py https://github.com/owner/repository
python skills/multi_install.py https://github.com/owner/repository/tree/main/path/to/skills
```

The installer discovers all `SKILL.md` files in the selected repository/folder, lists them, and asks before installing the set. Add `--yes` only when you intentionally want non-interactive installation. It installs each skill into its own folder under `skills/`, refuses to overwrite existing folders, and does not execute installed skill content. Review skills from unfamiliar sources before using them. The installer downloads each discovered skill folder, including its `SKILL.md` and supporting files, with per-file/total-size limits. It does not execute installed skill content.


## Live Android Screen Cast

JARVIS now includes a live-stream receiver and an Android companion app source project in [`android-screen-cast/`](android-screen-cast/README.md). The companion uses Android's visible MediaProjection consent flow to stream continuous frames into Termux over localhost, and an optional Accessibility Service provides UI actions. JARVIS keeps frames in RAM and analyzes the latest frame on request through the configured OmniRoute vision model, using Groq first and OmniRoute when Groq quota is exhausted to avoid sending a model request for every video frame. See the companion README for build, permission, HTTP API, and device-test instructions.
