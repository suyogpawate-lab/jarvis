# JARVIS Multi-Surface Workspace (development)

This is a separate, opt-in workspace prototype. It does not replace the existing
terminal UI or production web UI.

## Run

```sh
python workspace_server.py
```

Open `http://127.0.0.1:8767` on the same device. The startup log prints a
per-process token. The server binds to loopback only and requires that token for
state-changing requests.

## Current capabilities

- Six bounded, independently managed workspace surfaces.
- Web, YouTube, direct video, image, live-screen placeholder, terminal,
  Android-app, task, tools/MCP, and telemetry surface types.
- SSE event stream and snapshot API.
- Task/side-quest event API and bounded telemetry fields.
- URL scheme and local-host checks for embedded content.
- Responsive JARVIS-themed interface.

## API

- `POST /api/surfaces/open`: `{kind,title,url?,metadata?}`
- `POST /api/surfaces/close`: `{id}`
- `POST /api/surfaces/update`: `{id,status?,title?}`
- `POST /api/tasks/event`: `{id,name,status,detail?}`
- `POST /api/telemetry`: bounded token/model/confidence/tool metadata
- `POST /api/intent`: deterministic convenience intents; complex natural
  language must be classified by the JARVIS brain before calling the typed API.

## Platform boundary

The workspace can show six simultaneous web/native-status surfaces, but Android
10 does not expose a general API for embedding six arbitrary installed apps as
independent interactive windows inside a web page. The existing accessibility
service controls the currently active Android window; it is not six isolated
app sessions. Native app launch/switching, multi-window behavior, and a true
floating overlay require a separately tested Android companion implementation.

Terminal output is not streamed by default. Add only a redacted, explicitly
authorized read-only output adapter; never mirror secrets or raw environment
variables. Confidence is optional metadata, not a calibrated probability unless
the underlying model supplies a meaningful score.

## Tests

```sh
python -m unittest tests.test_workspace
```
