import asyncio
import threading
import queue
import select
import sys
from pathlib import Path

import readline
from prompt_toolkit import PromptSession
from prompt_toolkit.patch_stdout import patch_stdout
"""
JARVIS CLI

Core capabilities:

    normal conversation
    live multi-agent discussion
    personal memory
    project memory
    memory retrieval
    conversation history
"""

import re
import os
import subprocess
import shutil
import time
from pathlib import Path

import requests

from core import Jarvis
from android.command_guard import handle_user_reply as handle_guard_reply
from automation.command_dispatcher import CommandDispatcher
from core.discussion import DiscussionCoordinator
from memory import MemoryManager
from memory.intent import MemoryIntent
from monitoring.system_telemetry import get_telemetry
from monitoring.notification_watcher import NotificationWatcher
import service_launcher


# ==============================================================
# CORE OBJECTS
# ==============================================================

jarvis = Jarvis()
discussion = DiscussionCoordinator()
memory = MemoryManager()
dispatcher = CommandDispatcher(
    jarvis,
    discussion,
    memory,
)



# ==============================================================
# DISCUSSION COMMANDS
# ==============================================================

def parse_discuss_command(prompt):

    text = prompt.strip()

    # ----------------------------------------------------------
    # /discuss <topic>
    # ----------------------------------------------------------

    match = re.match(
        r"^/discuss\s+(.+)$",
        text,
        re.IGNORECASE,
    )

    if match:

        return (
            60,
            match.group(1).strip(),
        )

    # ----------------------------------------------------------
    # /discuss60s
    # /discuss5m
    # ----------------------------------------------------------

    match = re.match(
        r"^/discuss(\d+)(s|m)\s+(.+)$",
        text,
        re.IGNORECASE,
    )

    if match:

        value = int(match.group(1))

        unit = match.group(2).lower()

        topic = match.group(3).strip()

        if unit == "m":
            value *= 60

        return value, topic

    # ----------------------------------------------------------
    # Natural language
    #
    # Jarvis, discuss X for 5 minutes
    # ----------------------------------------------------------

    match = re.match(
        r"^(?:jarvis[,\s]+)?(?:run\s+)?discuss\s+(.+?)\s+for\s+(\d+)\s*"
        r"(seconds?|secs?|s|minutes?|mins?|m)\s*$",
        text,
        re.IGNORECASE,
    )
    if match:

        topic = match.group(1).strip()

        value = int(match.group(2))

        unit = match.group(3).lower()

        if unit.startswith("m"):
            value *= 60

        return value, topic

    return None


# ==============================================================
# EXPLICIT MEMORY COMMANDS
# ==============================================================

def parse_memory_command(prompt):

    text = prompt.strip()

    # ----------------------------------------------------------
    # /remember
    # ----------------------------------------------------------

    match = re.match(
        r"^/remember\s+(.+)$",
        text,
        re.IGNORECASE,
    )

    if match:

        return {
            "kind": "personal",
            "content": match.group(1).strip(),
        }

    # ----------------------------------------------------------
    # /project
    # ----------------------------------------------------------

    match = re.match(
        r"^/project\s+(.+)$",
        text,
        re.IGNORECASE,
    )

    if match:

        return {
            "kind": "project",
            "content": match.group(1).strip(),
        }

    return None


# ==============================================================
# MEMORY DISPLAY
# ==============================================================

def print_memory():

    print()
    print("===== PERSONAL MEMORY =====")

    personal = memory.personal(
        limit=20,
    )

    if personal:

        for item in personal:

            content = str(
                item.get("content", "")
            ).strip()

            if content:
                print(f"- {content}")

    else:

        print("(empty)")

    print()
    print("===== PROJECT MEMORY =====")

    projects = memory.project(
        limit=20,
    )

    if projects:

        for item in projects:

            content = str(
                item.get("content", "")
            ).strip()

            if content:
                print(f"- {content}")

    else:

        print("(empty)")

    print()
    print("===== RECENT EPISODES =====")

    episodes = memory.recent_episodes(
        limit=10,
    )

    if episodes:

        for item in episodes:

            topic = str(
                item.get("topic", "")
            ).strip()

            summary = str(
                item.get("summary", "")
            ).strip()

            print(
                f"- {topic}: {summary}"
            )

    else:

        print("(empty)")

    print()


# ==============================================================
# AUTOMATIC MEMORY
# ==============================================================

def process_automatic_memory(prompt):

    intent = MemoryIntent.detect(
        prompt
    )

    kind = intent["kind"]

    content = intent["content"]

    if kind == "none":
        return False

    if not content:
        return False

    try:

        if kind == "personal":

            result = memory.remember_personal(
                content,
                importance=8,
            )

            print(
                f"[MEMORY] Personal memory saved."
            )

        elif kind == "project":

            result = memory.remember_project(
                content,
                importance=7,
            )

            print(
                f"[MEMORY] Project memory saved."
            )

        else:

            return False

        return result is not None

    except Exception as exc:

        print(
            f"[MEMORY ERROR] {exc}"
        )

        return False


# ==============================================================
# SAVE CONVERSATION
# ==============================================================

def save_message(
    role,
    content,
):

    try:

        memory.remember_message(
            role,
            content,
        )

    except Exception as exc:

        print(
            f"[MEMORY WARN] Conversation save failed: {exc}"
        )


# ==============================================================
# MEMORY CONTEXT
# ==============================================================

def get_memory_context(prompt):

    try:

        return memory.build_context(
            prompt,
            max_personal=8,
            max_project=8,
            max_episodes=6,
            max_conversation=10,
        )

    except Exception as exc:

        print(
            f"[MEMORY WARN] Context retrieval failed: {exc}"
        )

        return "(No relevant memory found.)"


# ==============================================================
# WHATSAPP DAEMON
# ==============================================================

def ensure_http_bridge():
    """Start jarvis_http_bridge.py once, and leave it running in the background."""
    root = Path(__file__).resolve().parent
    try:
        from jarvis_env import load_env
        load_env()
    except Exception:
        pass
    bridge_script = root / "jarvis_http_bridge.py"
    bridge_url = "http://127.0.0.1:21339/health"

    if not bridge_script.is_file():
        print("[HTTP BRIDGE ERROR] jarvis_http_bridge.py not found.", flush=True)
        return False

    # Reuse an existing healthy bridge; never launch a duplicate process.
    try:
        response = requests.get(bridge_url, timeout=1.5)
        if response.ok:
            data = response.json()
            if data.get("ok") and data.get("service") == "JARVIS":
                print("[HTTP BRIDGE] Already running.", flush=True)
                return True
    except Exception:
        pass

    cache_dir = Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache"))) / "jarvis"
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        log_file = cache_dir / "http_bridge.log"
        with log_file.open("a", encoding="utf-8") as log:
            subprocess.Popen(
                [sys.executable, str(bridge_script)],
                cwd=str(root),
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=log,
                start_new_session=True,
                close_fds=True,
            )
    except Exception as exc:
        print(f"[HTTP BRIDGE ERROR] Could not start bridge: {type(exc).__name__}: {exc}", flush=True)
        return False

    # Give Python a moment to bind the port, but do not block startup for long.
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        try:
            response = requests.get(bridge_url, timeout=0.8)
            if response.ok:
                data = response.json()
                if data.get("ok") and data.get("service") == "JARVIS":
                    print("[HTTP BRIDGE] Started on http://127.0.0.1:21339.", flush=True)
                    return True
        except Exception:
            pass
        time.sleep(0.25)

    print(
        f"[HTTP BRIDGE WARN] Startup was not confirmed. Check {cache_dir / 'http_bridge.log'}; "
        "JARVIS will continue starting.",
        flush=True,
    )
    return False


def ensure_whatsapp_daemon():

    bridge_url = "http://127.0.0.1:23841/status"

    # ----------------------------------------------------------
    # Already running?
    # ----------------------------------------------------------

    try:

        response = requests.get(
            bridge_url,
            timeout=2,
        )

        if response.ok:

            data = response.json()

            if data.get("connected"):

                print(
                    "[WHATSAPP] Bridge already connected."
                )

                return True

    except Exception:
        pass

    # ----------------------------------------------------------
    # Start the persistent bridge.
    # ----------------------------------------------------------

    root = Path(__file__).resolve().parent

    launcher = root / "whatsapp_daemon.sh"

    log_dir = root / "data"

    log_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    log_file = log_dir / "whatsapp_bridge.log"

    if not launcher.exists():

        print(
            "[WHATSAPP ERROR] whatsapp_daemon.sh not found."
        )

        return False

    try:

        with open(
            log_file,
            "a",
            encoding="utf-8",
        ) as log:

            subprocess.Popen(
                [str(launcher)],
                cwd=str(root),
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=log,
                start_new_session=True,
            )

    except Exception as exc:

        print(
            f"[WHATSAPP ERROR] Failed to start bridge: {exc}"
        )

        return False

    # ----------------------------------------------------------
    # Wait for the HTTP bridge and WhatsApp connection.
    # ----------------------------------------------------------

    deadline = time.time() + 8

    while time.time() < deadline:

        try:

            response = requests.get(
                bridge_url,
                timeout=2,
            )

            if response.ok:

                data = response.json()

                if data.get("connected"):

                    print(
                        "[WHATSAPP] Bridge connected."
                    )

                    return True

        except Exception:
            pass

        time.sleep(0.5)

    print(
        "[WHATSAPP WARN] Bridge started but connection "
        "was not confirmed."
    )

    print(
        f"[WHATSAPP] Log: {log_file}"
    )

    return False




# ==============================================================
# ON-DEMAND SCREEN PERCEPTION
# ==============================================================
_SCREEN_QUESTION_RE = re.compile(
    r"^(?:what(?:'s| is) on my screen|describe my screen|look at my screen|"
    r"analyze my screen|read my screen|what(?:'s| is) open|"
    r"what does this screen(?: show)?|tell me what is on my screen)[?.! ]*$",
    re.IGNORECASE,
)


def handle_screen_question(prompt):
    """Ask the local HTTP bridge for a fresh Accessibility snapshot only on request.

    Do not save the prompt or answer to conversation memory: answers may contain
    private screen contents, and screen perception is explicitly ephemeral.
    """
    if not _SCREEN_QUESTION_RE.fullmatch(prompt.strip()):
        return None

    try:
        from jarvis_env import load_env
        load_env()
    except Exception:
        pass

    token = os.environ.get("JARVIS_HTTP_TOKEN", "").strip()
    if not token:
        return (
            "Sir, screen perception is not configured: JARVIS_HTTP_TOKEN is missing "
            "from the environment and .env file."
        )

    try:
        response = requests.post(
            "http://127.0.0.1:21339/screen/analyze",
            headers={"X-Token": token},
            json={"prompt": prompt.strip()},
            timeout=15,
        )
        if response.status_code == 401:
            return "Sir, the screen bridge rejected its authentication token. Check JARVIS_HTTP_TOKEN in .env."
        response.raise_for_status()
        payload = response.json()
        answer = str(payload.get("response", "")).strip()
        if not answer:
            return "Sir, the screen bridge returned an empty response."
        return answer
    except requests.RequestException as exc:
        return (
            "Sir, I couldn't reach the screen-perception bridge. "
            "JARVIS will try to start it at startup; check ~/.cache/jarvis/http_bridge.log. "
            f"({type(exc).__name__})"
        )
    except (ValueError, TypeError):
        return "Sir, the screen bridge returned an invalid response."


# ==============================================================
# LOCAL ANDROID ROUTER (NO LLM LATENCY)
# ==============================================================
# Exact device actions are handled before CommandDispatcher/Groq.
# App names are resolved from data/installed_apps.json (written by install.sh via
# scripts/capture_apps.py: real launcher name, shortforms, package ID). Optional personal
# nicknames live in data/app_nicknames.json, e.g. {"yt": "youtube"}. Nothing is hardcoded here.

APPS_FILE = Path(__file__).resolve().parent / "data" / "installed_apps.json"
NICKNAMES_FILE = Path(__file__).resolve().parent / "data" / "app_nicknames.json"
_apps_cache = {"mt": None, "apps": []}


def _norm(text):
    return re.sub(r"[^a-z0-9]+", " ", str(text).lower()).strip()


def _load_apps():
    """Installed-app index, reloaded whenever the file changes."""
    import json
    try:
        mt = APPS_FILE.stat().st_mtime
        if _apps_cache["mt"] != mt:
            data = json.loads(APPS_FILE.read_text(encoding="utf-8"))
            _apps_cache["apps"] = [a for a in data.get("apps", []) if a.get("package")]
            _apps_cache["mt"] = mt
    except Exception:
        _apps_cache["apps"], _apps_cache["mt"] = [], None
    return _apps_cache["apps"]


def _nicknames():
    import json
    try:
        return {_norm(k): v for k, v in json.loads(NICKNAMES_FILE.read_text(encoding="utf-8")).items()}
    except Exception:
        return {}


def _resolve_app(query, explicit):
    """Resolve an app alias to package IDs using the testable shared resolver."""
    from android.app_aliases import resolve_app_candidates
    return resolve_app_candidates(
        query,
        explicit,
        _load_apps(),
        _nicknames(),
    )


ANDROID_SETTINGS = {
    "wifi": "android.settings.WIFI_SETTINGS",
    "wi-fi": "android.settings.WIFI_SETTINGS",
    "bluetooth": "android.settings.BLUETOOTH_SETTINGS",
    "sound": "android.settings.SOUND_SETTINGS",
    "volume": "android.settings.SOUND_SETTINGS",
    "display": "android.settings.DISPLAY_SETTINGS",
    "display settings": "android.settings.DISPLAY_SETTINGS",
    "battery": "android.settings.BATTERY_SAVER_SETTINGS",
    "battery settings": "android.settings.BATTERY_SAVER_SETTINGS",
    "location": "android.settings.LOCATION_SOURCE_SETTINGS",
    "location settings": "android.settings.LOCATION_SOURCE_SETTINGS",
    "app settings": "android.settings.APPLICATION_SETTINGS",
    "date and time": "android.settings.DATE_SETTINGS",
    "date & time": "android.settings.DATE_SETTINGS",
    "accessibility": "android.settings.ACCESSIBILITY_SETTINGS",
    "accessibility settings": "android.settings.ACCESSIBILITY_SETTINGS",
    "notification settings": "android.settings.NOTIFICATION_SETTINGS",
    "notifications": "android.settings.NOTIFICATION_SETTINGS",
}


def _android_package_ids():
    """Return package IDs when Android's package service is queryable.

    This is advisory only: some Android/Termux builds return an empty list even
    for apps that can be launched explicitly.
    """
    try:
        result = subprocess.run(
            ["pm", "list", "packages", "--user", "0"],
            capture_output=True, text=True, timeout=5
        )
        packages = {
            line.strip().split(":", 1)[-1]
            for line in result.stdout.splitlines()
            if line.strip().startswith("package:")
        }
        if packages:
            return packages
        result = subprocess.run(
            ["pm", "list", "packages"],
            capture_output=True, text=True, timeout=5
        )
        return {
            line.strip().split(":", 1)[-1]
            for line in result.stdout.splitlines()
            if line.strip().startswith("package:")
        }
    except Exception:
        return set()


def _android_start_succeeded(result):
    output = (result.stdout or "") + "\n" + (result.stderr or "")
    lowered = output.lower()
    return result.returncode == 0 and not any(
        marker in lowered for marker in (
            "error:", "exception", "unable to resolve", "no activities found",
            "activity class", "does not exist",
        )
    )


def _launch_android_package(package):
    """Launch an app without depending on monkey or a successful package query."""
    if not package or not re.fullmatch(r"[A-Za-z0-9_.]+", package):
        return False

    def start(args, timeout=8):
        try:
            result = subprocess.run(
                args, capture_output=True, text=True, timeout=timeout
            )
            return _android_start_succeeded(result)
        except (OSError, subprocess.SubprocessError):
            return False

    resolved = ""
    try:
        result = subprocess.run(
            [
                "cmd", "package", "resolve-activity", "--brief", "--user", "0",
                "-a", "android.intent.action.MAIN",
                "-c", "android.intent.category.LAUNCHER", "-p", package,
            ],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            for line in (result.stdout or "").splitlines():
                candidate = line.strip().split()[-1] if line.strip() else ""
                if "/" in candidate and candidate.split("/", 1)[0] == package:
                    resolved = candidate
                    break
    except (OSError, subprocess.SubprocessError):
        pass

    if resolved and start(["am", "start", "-n", resolved]):
        return True

    if start([
        "am", "start", "-a", "android.intent.action.MAIN",
        "-c", "android.intent.category.LAUNCHER", "-p", package,
    ]):
        return True

    monkey = shutil.which("monkey")
    if monkey and start([monkey, "-p", package, "1"]):
        return True

    # A few Android builds cannot resolve launcher activities but accept these
    # common explicit component names. Try them only after normal resolution.
    for activity in (".Main", ".MainActivity", ".Launcher", ".SplashActivity"):
        if start(["am", "start", "-n", f"{package}/{activity}"]):
            return True
    return False


def handle_local_android_command(prompt):
    """Return a response string when handled locally, otherwise None."""
    text = re.sub(r"\s+", " ", prompt.strip().lower())
    if not text:
        return None

    # Android settings are deterministic and should never reach Groq.
    match = re.fullmatch(
        r"(?:open|go to|show|launch)?\s*(?:android\s+)?"
        r"(?:the\s+)?(.+?)(?:\s+settings)?",
        text
    )
    if match:
        target = match.group(1).strip()
        action = ANDROID_SETTINGS.get(target)
        if action:
            try:
                result = subprocess.run(
                    ["termux-am", "start", "-a", action],
                    capture_output=True, text=True, timeout=6
                )
                if result.returncode == 0:
                    return f"Opening {target} settings locally."
                return f"Could not open {target} settings: {(result.stderr or result.stdout).strip()}"
            except Exception as exc:
                return f"Could not open {target} settings: {exc}"

    # App names can be typed alone, or with "open/launch/start".
    app_text = re.sub(r"^(?:open|launch|start|run)\s+", "", text).strip()
    app_text = re.sub(r"^(?:the\s+)", "", app_text)
    app_text = re.sub(r"\s+app$", "", app_text)
    explicit = bool(re.match(r"^(?:open|launch|start|run)\s+", text))
    candidates = None
    # Deterministic fallbacks for common apps when Android package enumeration
    # is unavailable in Termux and installed_apps.json is stale or missing.
    built_in_packages = {
        "whatsapp": "com.whatsapp",
        "whatsapp messenger": "com.whatsapp",
        "wa": "com.whatsapp",
        "chrome": "com.android.chrome",
        "google chrome": "com.android.chrome",
        "youtube": "com.google.android.youtube",
        "gmail": "com.google.android.gm",
        "google maps": "com.google.android.apps.maps",
        "maps": "com.google.android.apps.maps",
    }
    if explicit:
        candidates = (built_in_packages.get(_norm(app_text)),) if _norm(app_text) in built_in_packages else None
    if re.fullmatch(r"[a-z0-9][a-z0-9 ._-]{0,39}", app_text):
        candidates = candidates or (tuple(_resolve_app(app_text, explicit)) or None)
        if candidates is None and explicit and len(_norm(app_text)) >= 3:
            q = _norm(app_text)
            many = [a["name"] for a in _load_apps() if a.get("launchable") is not False and q in _norm(a["name"])]
            if len(many) > 1:                 # several apps match: ask instead of guessing
                return "Which app did you mean: " + ", ".join(sorted(set(many))[:6]) + "?"

    # Not in the index (new install, or index not built yet): conservative live package-ID match.
    # Never fuzzy-match a normal sentence to an installed app.
    if candidates is None and re.fullmatch(r"[a-z0-9][a-z0-9 ._-]{0,39}", app_text):
        packages = _android_package_ids()
        from android.app_aliases import resolve_installed_packages
        matches = resolve_installed_packages(app_text, packages)
        if len(matches) == 1:
            candidates = (matches[0],)

    if candidates:
        for package in candidates:
            try:
                if _launch_android_package(package):
                    return f"Opened {app_text} locally."
            except Exception:
                continue
        return (
            f"I couldn't launch {app_text} locally. "
            "It may not be installed, or data/installed_apps.json may be outdated "
            "(refresh it with: python scripts/capture_apps.py)."
        )

    return None


# ==============================================================
# PROMPT HANDLING  (shared by the CLI below and jarvis_ui.py)
# ==============================================================

MEMORY_VIEW_COMMANDS = {
    "/memory",
    "/mem",
    "memory",
    "show memory",
    "show my memory",
}

# Operational requests are actions, not memories.
OPERATIONAL_RE = re.compile(
    r"\b(?:send|message|email|whatsapp|sms|launch|open|"
    r"execute|run|start|stop|kill|check|inspect|read|search|"
    r"show|list|download|upload|install|uninstall|delete|"
    r"create|remove|restart)\b",
    re.IGNORECASE,
)


def format_memory():
    """print_memory() output as a string."""
    import io
    import contextlib

    buf = io.StringIO()

    with contextlib.redirect_stdout(buf):
        print_memory()

    return buf.getvalue().strip()


def speak(text, quiet=False):
    """Speak text through TTS. Returns True if it was handed to TTS, False on failure."""
    try:
        from voice.tts_manager import tts
        tts.speak(text)
        return True
    except Exception as exc:
        if not quiet:
            print(f"[TTS ERROR] {exc}")
        return False


def stop_speaking():
    """Cut off any speech in progress (called when a new prompt is submitted)."""
    try:
        from voice.tts_manager import tts
        tts.interrupt()
    except Exception:
        pass


def handle_prompt(prompt, source="external"):
    """
    Process ONE user message.

    Returns (answer_text_or_None, should_speak).
    Nothing is printed or spoken here, so the CLI and the
    terminal UI can each present the answer their own way.
    """

    prompt = prompt.strip()

    if not prompt:
        return None, False

    # The user pressed Enter: stop talking now, before the new answer is worked out.
    stop_speaking()

    guard_reply = handle_guard_reply(prompt)
    if guard_reply is not None:
        return guard_reply, False

    # ----------------------------------------------------------
    # Explicit sqlmap CLI route (scoped launcher; no LLM rewriting)
    # ----------------------------------------------------------
    sqlmap_match = re.match(
        r"^(?:jarvis[,\\s]+)?(?:run\\s+)?sqlmap(?:\\s+(.*))?$",
        prompt,
        re.IGNORECASE | re.DOTALL,
    )
    if sqlmap_match:
        import shlex
        from security.sqlmap_tool import run_sqlmap

        raw_args = (sqlmap_match.group(1) or "--help").strip()
        try:
            sqlmap_args = shlex.split(raw_args)
            answer = run_sqlmap(sqlmap_args)
        except Exception as exc:
            answer = f"[SQLMAP ERROR] {exc}"
        save_message("user", prompt)
        save_message("assistant", answer)
        return answer, False

    # ----------------------------------------------------------
    # On-demand screen perception (ephemeral; bypass conversation memory)
    # ----------------------------------------------------------
    screen_answer = handle_screen_question(prompt)
    if screen_answer is not None:
        return screen_answer, False

    # ----------------------------------------------------------
    # Local Android actions (no LLM)
    # ----------------------------------------------------------

    try:
        local_answer = handle_local_android_command(prompt)
    except Exception as exc:
        local_answer = f"Local Android action failed: {exc}"

    if local_answer is not None:
        save_message("user", prompt)
        save_message("assistant", local_answer)
        return local_answer, True

    # ----------------------------------------------------------
    # Memory inspection
    # ----------------------------------------------------------

    if prompt.lower() in MEMORY_VIEW_COMMANDS:
        return format_memory(), False

    # ----------------------------------------------------------
    # Discussion (checked BEFORE automatic memory)
    # ----------------------------------------------------------

    parsed = parse_discuss_command(prompt)

    if parsed:
        duration, topic = parsed
        save_message("user", prompt)

        try:
            final = discussion.discuss(topic, duration=duration)
        except Exception as exc:
            return f"[DISCUSS ERROR] {exc}", False

        if final:
            save_message("assistant", final)
            return str(final), False

        return None, False

    # ----------------------------------------------------------
    # Explicit memory commands
    # ----------------------------------------------------------

    memory_command = parse_memory_command(prompt)

    if memory_command:
        kind = memory_command["kind"]
        content = memory_command["content"]

        if not content:
            return "[MEMORY ERROR] Empty memory.", False

        try:
            if kind == "personal":
                result = memory.remember_personal(content, importance=8)
                label = "Personal"
            else:
                result = memory.remember_project(content, importance=7)
                label = "Project"

            if result is not None:
                return f"[MEMORY] {label} memory saved.", False

            return "[MEMORY WARN] Nothing was saved.", False

        except Exception as exc:
            return f"[MEMORY ERROR] {exc}", False

    # ----------------------------------------------------------
    # Automatic memory
    # ----------------------------------------------------------

    if not OPERATIONAL_RE.search(prompt):
        process_automatic_memory(prompt)

    # ----------------------------------------------------------
    # Autonomous action / normal conversation
    # ----------------------------------------------------------

    save_message("user", prompt)

    try:
        dispatched = dispatcher.dispatch(prompt, source=source)

        if dispatched is not None:
            answer = str(dispatched or "").strip()

            if answer:
                save_message("assistant", answer)
                return answer, True

            return None, False

    except Exception as exc:
        print(f"\n[DISPATCH WARN] {type(exc).__name__}: {exc}; trying core fallback.\n", flush=True)

    # ----------------------------------------------------------
    # Fallback: plain JARVIS with memory context
    # ----------------------------------------------------------

    memory_context = get_memory_context(prompt)

    augmented_prompt = (
        "RELEVANT MEMORY:\n\n"
        f"{memory_context}\n\n"
        "CURRENT USER MESSAGE:\n\n"
        f"{prompt}"
    ).strip()

    try:
        answer = str(jarvis.ask(augmented_prompt) or "").strip()
    except Exception as exc:
        return f"[ERROR] {exc}", False

    if answer:
        save_message("assistant", answer)
        return answer, False

    return "[ERROR] Empty response.", False


# ==============================================================
# BACKGROUND SERVICES
# ==============================================================

# Notification summaries are queued by the background watcher.
notification_queue = queue.Queue()
notification_watcher = None

# VOICE LISTENER INTEGRATION
voice_command_queue = queue.Queue()
voice_listener = None


def _web_notify(summary):
    """Show a notification in the web UI too (no-op if jarvis_ui is unavailable)."""
    try:
        import jarvis_ui
        jarvis_ui.notify(summary)
    except Exception:
        pass


whatsapp_autoreply = None


def start_whatsapp_autoreply():
    """Start the DM auto-reply worker (set JARVIS_WA_AUTOREPLY=0 to turn it off)."""
    global whatsapp_autoreply

    if os.getenv("JARVIS_WA_AUTOREPLY", "1").strip().lower() in {"0", "false", "no", "off"}:
        print("[WHATSAPP AUTO] Disabled (JARVIS_WA_AUTOREPLY=0).", flush=True)
        return

    import importlib

    worker_class = None
    for module_name in (
        "messaging.whatsapp_autoreply",
        "automation.whatsapp_autoreply",
        "whatsapp_autoreply",
    ):
        try:
            worker_class = importlib.import_module(module_name).WhatsAppAutoReplyWorker
            break
        except ModuleNotFoundError as exc:
            if exc.name and not module_name.endswith(exc.name):
                print(f"[WHATSAPP AUTO DISABLED] Missing module: {exc.name}", flush=True)
                return
        except Exception as exc:
            print(f"[WHATSAPP AUTO DISABLED] {exc}", flush=True)
            return

    if worker_class is None:
        print("[WHATSAPP AUTO DISABLED] whatsapp_autoreply.py not found.", flush=True)
        return

    try:
        whatsapp_autoreply = worker_class()
        # The same worker owns explicit group-send confirmations and DM reviews.
        # Attach it before accepting CLI requests so group sends can be queued.
        dispatcher.set_whatsapp_confirmation_worker(whatsapp_autoreply)
        if whatsapp_autoreply.start():
            print("[WHATSAPP AUTO] Auto-reply is ON for direct messages.", flush=True)
    except Exception as exc:
        print(f"[WHATSAPP AUTO DISABLED] {exc}", flush=True)


def init_services():
    global notification_watcher, voice_listener

    # Start the local HTTP bridge before other services so screen-control endpoints
    # are ready as JARVIS comes online.
    ensure_http_bridge()

    # OmniRoute + Knowledge Hub start in the background while WhatsApp is checked below.
    service_launcher.start_background()

    ensure_whatsapp_daemon()
    start_whatsapp_autoreply()

    notification_watcher = NotificationWatcher(
        output_queue=notification_queue
    ).start()

    try:
        from voice.listener import WhistleWakeListener
        voice_listener = WhistleWakeListener(voice_command_queue).start()
    except Exception as exc:
        print(f"[VOICE DISABLED] {exc}", flush=True)


def shutdown():
    try:
        if whatsapp_autoreply is not None:
            whatsapp_autoreply.stop()
    except Exception as exc:
        print(f"[SHUTDOWN WARN] WhatsApp auto-reply: {exc}", flush=True)

    try:
        if voice_listener is not None:
            voice_listener.stop()
    except Exception as exc:
        print(f"[SHUTDOWN WARN] Voice listener: {exc}", flush=True)

    try:
        if notification_watcher is not None:
            notification_watcher.stop()
    except Exception as exc:
        print(f"[SHUTDOWN WARN] Notification watcher: {exc}", flush=True)

    try:
        scheduler = getattr(dispatcher, "automation", None)
        if scheduler is not None:
            scheduler.shutdown()
    except Exception as exc:
        print(f"[SHUTDOWN WARN] Automation scheduler: {exc}", flush=True)


def pop_notification():
    try:
        return notification_queue.get_nowait()
    except queue.Empty:
        return None


def _show_whatsapp_group_events():
    """Surface pending outgoing group messages without interrupting CLI input."""
    if whatsapp_autoreply is None:
        return False
    try:
        events = whatsapp_autoreply.drain_events(event_type="GROUP_CONFIRMATION")
    except Exception:
        return False
    if not events:
        return False
    for event in events:
        group = str(event.get("group_subject") or event.get("chat_jid") or "WhatsApp group")
        message = str(event.get("text") or event.get("suggested_reply") or "")
        print(f"\n[JARVIS WHATSAPP GROUP CONFIRMATION] {group}:")
        print(f"  Message: {message}")
        print("  Reply YES to send or NO to cancel.")
    return True


def _show_whatsapp_review_events():
    """Surface uncertain auto-replies in the CLI without interrupting input."""
    if whatsapp_autoreply is None:
        return False
    try:
        events = whatsapp_autoreply.drain_events(event_type="REPLY_REVIEW")
    except Exception:
        return False
    if not events:
        return False
    for event in events:
        review_id = str(event.get("review_id", ""))
        sender = str(event.get("sender", "Unknown contact"))
        print(f"\n[JARVIS WHATSAPP REVIEW] Message from {sender}:")
        print(f"  Message: {event.get('incoming', '')}")
        print(f"  Why review is needed: {event.get('reason', 'Not enough reliable context.')}")
        evidence = str(event.get("evidence", "")).strip()
        if evidence:
            print(f"  Available evidence: {evidence}")
        drafts = []
        if str(event.get("suggested_reply", "")).strip():
            drafts.append(str(event["suggested_reply"]).strip())
        drafts.extend(str(x).strip() for x in event.get("alternatives", []) if str(x).strip())
        for index, draft in enumerate(drafts[:2], 1):
            print(f"  Draft {index}: {draft}")
        print(f"  Decide: wa-reply {review_id} 1 | wa-reply {review_id} 2")

def is_float_mode():
    """True when launched through the compact Termux:Float entry point."""
    return os.environ.get("JARVIS_FLOAT_MODE", "").strip().lower() in {"1", "true", "yes", "on"}


_cli_prompt_session = PromptSession()
_cli_pending_text = ""


def _service_cli_background_events():
    """Render queued notifications without losing the active editable prompt."""
    _show_whatsapp_group_events()
    _show_whatsapp_review_events()
    while True:
        summary = pop_notification()
        if summary is None:
            break
        print(f"\nJARVIS [NOTIFICATIONS] > {summary}\n", flush=True)
        _web_notify(summary)


async def _read_prompt_async():
    global _cli_pending_text
    with patch_stdout():
        prompt_task = asyncio.create_task(
            _cli_prompt_session.prompt_async(
                "J> " if is_float_mode() else "YOU  > ",
                default=_cli_pending_text,
            )
        )
        _cli_pending_text = ""

        try:
            while not prompt_task.done():
                _service_cli_background_events()
                try:
                    command = voice_command_queue.get_nowait()
                except queue.Empty:
                    command = None

                if command and command.strip():
                    # Preserve anything the user was midway through typing. The
                    # voice command is handled now; their draft returns next prompt.
                    try:
                        _cli_pending_text = _cli_prompt_session.default_buffer.text
                    except Exception:
                        _cli_pending_text = ""
                    prompt_task.cancel()
                    try:
                        await prompt_task
                    except asyncio.CancelledError:
                        pass
                    print(f"\nYOU (VOICE) > {command.strip()}\n", flush=True)
                    return command.strip(), "voice"

                await asyncio.sleep(0.08)

            _service_cli_background_events()
            return (await prompt_task).strip(), "text"
        finally:
            # Ctrl+C cancels asyncio.run's main task. Always cancel and retrieve
            # the child prompt task so prompt_toolkit cannot leak an unhandled
            # KeyboardInterrupt/CancelledError during shutdown.
            if not prompt_task.done():
                prompt_task.cancel()
            try:
                await prompt_task
            except BaseException:
                pass


def read_prompt():
    """Editable terminal prompt that remains responsive to voice and notifications.

    prompt_toolkit supplies readline-style arrow-key editing while its async
    prompt allows JARVIS to consume voice commands before the user presses Enter.
    """
    while True:
        prompt, source = asyncio.run(_read_prompt_async())
        if prompt:
            return prompt, source


# ==============================================================
# MAIN (plain terminal CLI)   -   the fancy UI is: python jarvis_ui.py
# ==============================================================

def main():

    init_services()

    if is_float_mode():
        # Termux:Float is a small terminal surface; keep the CLI compact and
        # avoid starting the separate Rich full-screen UI/web companion.
        print("JARVIS FLOAT ONLINE")
        print("Commands: /memory | exit")
    else:
        try:
            import jarvis_ui, jarvis_web
            url = jarvis_web.start(jarvis_ui, sys.modules[__name__])
            if url:
                print(f"Web UI: {url}")
        except Exception as exc:
            print(f"[WEB UI DISABLED] {exc}")

        print("JARVIS ONLINE")
        print("Type '/memory' to inspect memory.")
        print("Type 'exit' to quit.")
    print()

    while True:

        try:

            # Deliver only from the main thread, never over an active prompt.
            while True:
                summary = pop_notification()

                if summary is None:
                    break

                print(f"\nJARVIS [NOTIFICATIONS] > {summary}\n", flush=True)
                _web_notify(summary)

            prompt, prompt_source = read_prompt()

            if not prompt:
                continue

            if prompt.lower() in {"exit", "quit"}:
                shutdown()
                print("JARVIS OFFLINE")
                break

            # Explicit YES/NO controls apply only while a group message is pending.
            if (
                whatsapp_autoreply is not None
                and whatsapp_autoreply.pending_group_replies
                and prompt.strip().lower() in {"yes", "y", "confirm"}
            ):
                print(f"JARVIS > {whatsapp_autoreply.confirm_latest_group_reply(True)}\n")
                continue
            if (
                whatsapp_autoreply is not None
                and whatsapp_autoreply.pending_group_replies
                and prompt.strip().lower() in {"no", "n", "cancel"}
            ):
                print(f"JARVIS > {whatsapp_autoreply.confirm_latest_group_reply(False)}\n")
                continue

            review_match = re.fullmatch(
                r"wa-reply\s+(\S+)\s+(1|2|skip|none|no|0)",
                prompt.strip(),
                re.IGNORECASE,
            )
            if review_match:
                if whatsapp_autoreply is None:
                    print("WhatsApp auto-reply worker is not running.")
                else:
                    try:
                        result = whatsapp_autoreply.resolve_reply_review(
                            review_match.group(1), review_match.group(2)
                        )
                        print(f"JARVIS > {result}\n")
                    except Exception as exc:
                        print(f"JARVIS > Could not process reply decision: {exc}\n")
                continue

            if prompt.lower() in MEMORY_VIEW_COMMANDS:
                print_memory()
                continue

            answer, should_speak = handle_prompt(prompt, source=prompt_source)

            if not answer:
                continue

            print()

            if parse_discuss_command(prompt):
                print("--- SYNTHESIS ---")
                print()
                print(f"JARVIS >> {answer}")
            else:
                print(f"JARVIS > {answer}")

            print()

            if should_speak:
                speak(answer)

        except KeyboardInterrupt:
            shutdown()
            print("\nJARVIS OFFLINE")
            break

        except EOFError:
            shutdown()
            print("\nJARVIS OFFLINE")
            break

        except Exception as exc:
            print(f"\n[FATAL ERROR] {exc}\n")


if __name__ == "__main__":
    main()
