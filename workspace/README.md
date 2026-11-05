# JARVIS Floating Workspace (development)

A JARVIS-controlled desktop-like visual workspace for the existing Termux UI.
It is a separate, opt-in development surface and does not replace the production
terminal or web UI.

## Interaction model

- Up to six independent floating windows on a shared workspace.
- Drag a title bar to move a window; use the resize grip to resize it.
- Minimize a window to the bottom dock, restore it from the dock, maximize it,
  focus it, or close it independently.
- Window placement is remembered locally by the browser.
- JARVIS can open visual URLs and issue minimize/restore/close commands through
  its event bridge. The authenticated HTTP API can also open, update and close
  surfaces directly.

## Content types

Browser/web pages, YouTube, direct video, images, PDF documents, audio, live
screen, task activity, tools/MCP activity, terminal and telemetry surfaces.
The server accepts only HTTP(S) URLs for remote embeds and rejects loopback and
.local destinations. Embedded sites may block iframe playback or embedding;
in those cases, open the original URL in a browser.

## Run

```sh
python workspace_server.py
```

Open `http://127.0.0.1:8767`. The startup log prints the per-process token.
The server binds to loopback and requires that token for state-changing API
requests.

## API

- `POST /api/surfaces/open`: `{kind,title,url?,metadata?}`
- `POST /api/surfaces/close`: `{id}`
- `POST /api/surfaces/update`: `{id,status?,title?}` (status includes active/minimized)
- `POST /api/tasks/event`: `{id,name,status,detail?}`
- `POST /api/telemetry`: measured token/model/confidence/tool metadata
- `GET /api/snapshot` and `GET /events`: state and SSE updates

## JARVIS integration

The terminal UI publishes presence state and task lifecycle metadata. The
bridge routes explicit URL display requests and explicit window commands such
as "minimize all windows", "restore all windows", "close all windows", or
"minimize the browser window". Prompts and replies are not persisted.

The task activity window is created when the first task event arrives. Tool,
token and confidence values remain blank until actual instrumentation supplies
them; confidence is not fabricated.

## Known integration boundaries

- Live screen pixels still need an authenticated frame adapter from the
  existing screen-cast service.
- Terminal output still needs a redacted, read-only stream. Raw shell output,
  environment variables, credentials and private data must not be mirrored.
- Generic sites can deny iframe embedding. YouTube playback can be restricted
  by browser autoplay policy, video privacy, or embed permissions.
- This is not a production release. Test on the target Android browser before
  merging or packaging.
