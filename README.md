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

## Mission memory and diagnostics

JARVIS now includes local mission history analysis alongside its task executor and Skill Forge. It inspects saved task JSON records without making an AI/API request.

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
- Search output may include snippets from prior commands/results. Sensitive-looking key/token/password values are redacted in displayed snippets, but users should still keep local task data private.

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

## Architecture

1. `jarvis.py` starts the application and its configured interaction modes.
2. `CommandDispatcher` handles explicit slash commands and deterministic local abilities, and initializes the search hub, deep-search engine, local AI adapter, fast agent, autonomous agent, and scheduler.
3. The agent engine can ask configured Gemini planning support to create bounded multi-step plans. Every action goes through the existing dispatcher and task executor.
4. `TaskExecutor` persists task state and execution events. If the process dies during a step, JARVIS does not blindly replay that side effect on startup.
5. Mission insights and Skill Forge read local task history. They do not require an extra model call for recall, diagnosis, or repeated-workflow suggestions.
6. Device actions are implemented through the Android/Termux layer. Risky shell operations are gated by the command guard by default; this guard is a safety check, not a sandbox.
7. Persistent memory and job/automation state are stored in local runtime data. Gmail and WhatsApp require separately configured credentials/session state; the WhatsApp manager talks to the local Baileys bridge.

### Dependency boundaries

- **Core:** `requirements.txt` contains the primary Python runtime dependencies.
- **Voice:** `requirements-voice.txt` lists optional wake-word/audio packages. The installer’s `--with-voice` option downloads the Needle ARM64 runner and Whistle model. Python audio dependencies can be platform-sensitive on Android; voice is not required for typed interaction.
- **OSINT:** `requirements-osint.txt` contains additional optional packages for selected OSINT integrations; some adapters may have their own external tool/runtime requirements.
- **WhatsApp:** `whatsapp/package.json` and its lockfile define the Node.js Baileys bridge dependencies.
- **Configuration:** `.env.example` documents provider and integration variables. Use `python setup.py` for guided setup; the real `.env`, account credentials, contact lists, authentication sessions, and runtime databases must remain local.

### Review and verification scope

This README describes the tracked source layout and intended integration boundaries. It does not imply that every optional provider, native Android action, external worker, or account integration has been exercised on every device. Installation success and runtime behavior depend on Termux packages, Android permissions, network access, valid credentials, model files, and optional services. Use the troubleshooting section below to verify each configured integration on the target device.

## Local regression checks

Run the syntax scan and deterministic regression tests before trying new features:

```bash
python scripts/smoke_test.py
# Or run only the unit tests:
python -m unittest discover -s tests -v
```

These checks are local-only: they do not call Groq, Gemini, OmniRoute, or other providers, and they do not launch apps or send messages. They do not replace live checks of Android permissions, microphone capture, or configured providers.

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
