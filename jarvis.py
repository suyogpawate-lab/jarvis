import asyncio
import threading
import queue
import select
import sys
from pathlib import Path

from prompt_toolkit import PromptSession, print_formatted_text
from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit.formatted_text import HTML, ANSI
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

import requests

from core import Jarvis
from android.command_guard import handle_user_reply as handle_guard_reply
from automation.command_dispatcher import CommandDispatcher
from core.discussion import DiscussionCoordinator
from memory import MemoryManager
from memory.chat_history import ChatHistory
from terminal_utils import clear_scrollback
from memory.intent import MemoryIntent
from monitoring.system_telemetry import get_telemetry
from monitoring.notification_watcher import NotificationWatcher
import service_launcher
from auto_update import AutoUpdater


# ==============================================================
# JARVIS CLI COLOR PALETTE
# ==============================================================

_R = "\033[0m"          # reset
_B = "\033[1m"          # bold
_D = "\033[2m"          # dim
_CYAN = "\033[36m"
_BCYAN = "\033[96m"
_GREEN = "\033[32m"
_BGREEN = "\033[92m"
_GOLD = "\033[33m"
_BGOLD = "\033[93m"
_RED = "\033[31m"
_BRED = "\033[91m"
_MAG = "\033[35m"
_BMAG = "\033[95m"
_WHITE = "\033[97m"
_GRAY = "\033[90m"
_BBLUE = "\033[94m"

_J = f"{_B}{_BCYAN}"       # JARVIS accent
_U = f"{_B}{_BGREEN}"      # user accent
_TAG = f"{_B}{_GOLD}"      # status tags
_ERR = f"{_B}{_BRED}"      # errors
_WARN = f"{_B}{_BGOLD}"    # warnings
_OK = f"{_B}{_BGREEN}"     # success
_DIM = f"{_D}{_GRAY}"      # secondary text
_ACCENT = f"{_B}{_BCYAN}"  # general accent


def _c(style, text):
    return f"{style}{text}{_R}"


def _tag(label, style=None):
    s = style or _TAG
    return f"{s}[{label}]{_R}"


def _print(*args, **kwargs):
    """Print using prompt_toolkit's print_formatted_text so stdout is correctly patched."""
    sep = kwargs.get("sep", " ")
    end = kwargs.get("end", "\n")
    text = sep.join(str(a) for a in args)
    if end == "\n":
        print_formatted_text(ANSI(text))
    else:
        print_formatted_text(ANSI(text), end=end)


builtin_print = print
print = _print


# ==============================================================
# CORE OBJECTS
# ==============================================================

_auto_updater = AutoUpdater(Path(__file__).resolve().parent)
_auto_update_restart = False
_auto_update_notified = False
_active_task_future = None
_deferred_prompts = []
_btw_agent = None


def start_auto_updater():
    return _auto_updater.start()


def apply_auto_update_if_ready(approved=True):
    global _auto_update_restart
    if _auto_update_restart: return True
    _auto_update_restart = _auto_updater.apply_if_pending(approved=approved)
    return _auto_update_restart


def restart_after_update():
    script = Path(sys.argv[0]).resolve()
    if not script.is_file(): script = Path(__file__).resolve()
    os.execv(sys.executable, [sys.executable, str(script), *sys.argv[1:]])


jarvis = Jarvis()
discussion = DiscussionCoordinator()
memory = MemoryManager()
chat_history = ChatHistory()
chat_history.ensure_active()
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
    print(_c(_J, "━━━━━ PERSONAL MEMORY ━━━━━"))

    personal = memory.personal(
        limit=20,
    )

    if personal:

        for item in personal:

            content = str(
                item.get("content", "")
            ).strip()

            if content:
                print(f"  {_c(_BCYAN, '▸')} {content}")

    else:

        print(f"  {_c(_DIM, '(empty)')}")

    print()
    print(_c(_J, "━━━━━ PROJECT MEMORY ━━━━━"))

    projects = memory.project(
        limit=20,
    )

    if projects:

        for item in projects:

            content = str(
                item.get("content", "")
            ).strip()

            if content:
                print(f"  {_c(_BGREEN, '▸')} {content}")

    else:

        print(f"  {_c(_DIM, '(empty)')}")

    print()
    print(_c(_J, "━━━━━ RECENT EPISODES ━━━━━"))

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
                f"  {_c(_BGOLD, '▸')} {_c(_B + _WHITE, topic)}{_c(_DIM, ':')} {summary}"
            )

    else:

        print(f"  {_c(_DIM, '(empty)')}")

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
                f"{_tag('MEMORY', _OK)} Personal memory saved."
            )

        elif kind == "project":

            result = memory.remember_project(
                content,
                importance=7,
            )

            print(
                f"{_tag('MEMORY', _OK)} Project memory saved."
            )

        else:

            return False

        return result is not None

    except Exception as exc:

        print(
            f"{_tag('MEMORY ERROR', _ERR)} {exc}"
        )

        return False


# ==============================================================
# SAVE CONVERSATION
# ==============================================================

def save_message(role, content):
    try:
        chat_history.save(role, content)
        memory.remember_message(role, content)
    except Exception as exc:
        print(f"{_tag('MEMORY WARN', _WARN)} Conversation save failed: {exc}")


def format_chat_history():
    sessions = chat_history.list_sessions(limit=30)
    if not sessions:
        return f"{_c(_DIM, 'No saved chats.')}"
    lines = [_c(_J, "━━━━━ SAVED CHATS ━━━━━") + f"  {_c(_DIM, '(resume with /resume CODE)')}"]
    for item in sessions:
        stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(item["updated_at"]))
        lines.append(
            f'  {_c(_BCYAN, item["code"])} {_c(_DIM, "│")} {item["description"]} {_c(_DIM, "│")} '
            f'{_c(_DIM, str(item["message_count"]) + " msgs")} {_c(_DIM, "│")} {_c(_DIM, stamp)}'
        )
    return "\n".join(lines)


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
            f"{_tag('MEMORY WARN', _WARN)} Context retrieval failed: {exc}"
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
        print(f"{_tag('HTTP BRIDGE ERROR', _ERR)} jarvis_http_bridge.py not found.", flush=True)
        return False

    # Reuse an existing healthy bridge; never launch a duplicate process.
    try:
        response = requests.get(bridge_url, timeout=1.5)
        if response.ok:
            data = response.json()
            if data.get("ok") and data.get("service") == "JARVIS":
                print(f"{_tag('HTTP BRIDGE', _OK)} Already running.", flush=True)
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
        print(f"{_tag('HTTP BRIDGE ERROR', _ERR)} Could not start bridge: {type(exc).__name__}: {exc}", flush=True)
        return False

    # Give Python a moment to bind the port, but do not block startup for long.
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        try:
            response = requests.get(bridge_url, timeout=0.8)
            if response.ok:
                data = response.json()
                if data.get("ok") and data.get("service") == "JARVIS":
                    print(f"{_tag('HTTP BRIDGE', _OK)} Started on http://127.0.0.1:21339.", flush=True)
                    return True
        except Exception:
            pass
        time.sleep(0.25)

    print(
        f"{_tag('HTTP BRIDGE WARN', _WARN)} Startup was not confirmed. Check {cache_dir / 'http_bridge.log'}; "
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
                    f"{_tag('WHATSAPP', _OK)} Bridge already connected."
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
            f"{_tag('WHATSAPP ERROR', _ERR)} whatsapp_daemon.sh not found."
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
            f"{_tag('WHATSAPP ERROR', _ERR)} Failed to start bridge: {exc}"
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
                        f"{_tag('WHATSAPP', _OK)} Bridge connected."
                    )

                    return True

        except Exception:
            pass

        time.sleep(0.5)

    print(
        f"{_tag('WHATSAPP WARN', _WARN)} Bridge started but connection "
        "was not confirmed."
    )

    print(
        f"{_tag('WHATSAPP', _ACCENT)} Log: {log_file}"
    )

    return False




# ==============================================================
# ON-DEMAND SCREEN PERCEPTION
# ==============================================================
def handle_screen_question(prompt):
    """Ask the local HTTP bridge for a fresh Accessibility snapshot only on request.

    Do not save the prompt or answer to conversation memory: answers may contain
    private screen contents, and screen perception is explicitly ephemeral.
    """
    from screen_cast.perception import is_screen_context_request
    if not is_screen_context_request(prompt):
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
            # Mirage runs locally before Groq summarizes the visual context.
            # Allow enough time for both stages on slower Android hardware.
            timeout=(5, 90),
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

    buf = io.StringIO()
    _saved_print = globals()["print"]
    globals()["print"] = lambda *args, **kwargs: buf.write(
        kwargs.get("sep", " ").join(str(a) for a in args) + kwargs.get("end", "\n")
    )
    try:
        print_memory()
    finally:
        globals()["print"] = _saved_print

    return buf.getvalue().strip()


def speak(text, quiet=False, user_prompt=""):
    """Speak a JARVIS response, selecting Kokoro's style from the user's request."""
    try:
        from voice.tts_manager import tts
        tts.speak(text, user_prompt=user_prompt)
        return True
    except Exception as exc:
        if not quiet and "status -15" not in str(exc):
            try:
                log_file = Path(__file__).resolve().parent / "data" / "ui.log"
                with log_file.open("a", encoding="utf-8") as lf:
                    lf.write(f"[TTS ERROR] {exc}\n")
            except Exception:
                pass
        return False


def stop_speaking():
    """Interrupt the currently configured speech provider."""
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

    lower_prompt = prompt.strip().lower()
    if lower_prompt in {"/history", "jarvis-chat-history", "chat history"}:
        return format_chat_history(), False
    resume_match = re.fullmatch(r"/resume\s+(JH-[A-Z0-9]+)", prompt.strip(), re.IGNORECASE)
    if resume_match:
        session = chat_history.resume(resume_match.group(1))
        if not session:
            return "That resume code was not found. Use /history to see saved chats.", False
        count = len(chat_history.messages(resume_match.group(1), limit=100))
        return f"Resumed {resume_match.group(1).upper()}: {session['description']} ({count} messages).", False
    if lower_prompt in {"/newchat", "/new-chat"}:
        code = chat_history.new_session()
        return f"Started a new chat. Resume code: {code}", False
    if lower_prompt == "/clear":
        return "Use /clear in the interactive JARVIS terminal; it clears terminal scrollback only and does not delete chats.", False

    # The user pressed Enter: stop talking now, before the new answer is worked out.
    stop_speaking()

    guard_reply = handle_guard_reply(prompt)
    if guard_reply is not None:
        return guard_reply, False

    # ----------------------------------------------------------
    # Explicit sqlmap CLI route (scoped launcher; no LLM rewriting)
    # ----------------------------------------------------------
    sqlmap_match = re.match(
        r"^(?:jarvis[,\s]+)?(?:run\s+)?sqlmap(?:\s+(.*))?$",
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
        print(f"\n{_tag('DISPATCH WARN', _WARN)} {type(exc).__name__}: {exc}; trying core fallback.\n", flush=True)

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
# Overnight reports are delivered through the existing notification path.
try:
    dispatcher.research.overnight.on_complete = lambda message: notification_queue.put(str(message))
except Exception:
    pass

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
        print(f"{_tag('WHATSAPP AUTO', _DIM)} Disabled (JARVIS_WA_AUTOREPLY=0).", flush=True)
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
                print(f"{_tag('WHATSAPP AUTO DISABLED', _WARN)} Missing module: {exc.name}", flush=True)
                return
        except Exception as exc:
            print(f"{_tag('WHATSAPP AUTO DISABLED', _WARN)} {exc}", flush=True)
            return

    if worker_class is None:
        print(f"{_tag('WHATSAPP AUTO DISABLED', _WARN)} whatsapp_autoreply.py not found.", flush=True)
        return

    try:
        whatsapp_autoreply = worker_class(
            autonomy_event_callback=dispatcher.ingest_autonomy_event,
        )
        # The same worker owns explicit group-send confirmations and DM reviews.
        # Attach it before accepting CLI requests so group sends can be queued.
        dispatcher.set_whatsapp_confirmation_worker(whatsapp_autoreply)
        if whatsapp_autoreply.start():
            print(f"{_tag('WHATSAPP AUTO', _OK)} Auto-reply is ON for direct messages.", flush=True)
    except Exception as exc:
        print(f"{_tag('WHATSAPP AUTO DISABLED', _WARN)} {exc}", flush=True)


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
        output_queue=notification_queue,
        autonomy_event_callback=dispatcher.ingest_autonomy_event,
    ).start()

    try:
        from voice.listener import WhistleWakeListener
        voice_listener = WhistleWakeListener(voice_command_queue).start()
    except Exception as exc:
        print(f"{_tag('VOICE DISABLED', _WARN)} {exc}", flush=True)


def shutdown():
    try:
        active_dispatcher = globals().get("dispatcher")
        if active_dispatcher is not None:
            active_dispatcher.stop_background_services()
    except Exception as exc:
        print(f"{_tag('SHUTDOWN WARN', _WARN)} Dispatcher-owned services: {exc}", flush=True)

    try:
        if whatsapp_autoreply is not None:
            whatsapp_autoreply.stop()
    except Exception as exc:
        print(f"{_tag('SHUTDOWN WARN', _WARN)} WhatsApp auto-reply: {exc}", flush=True)

    try:
        if voice_listener is not None:
            voice_listener.stop()
    except Exception as exc:
        print(f"{_tag('SHUTDOWN WARN', _WARN)} Voice listener: {exc}", flush=True)

    try:
        if notification_watcher is not None:
            notification_watcher.stop()
    except Exception as exc:
        print(f"{_tag('SHUTDOWN WARN', _WARN)} Notification watcher: {exc}", flush=True)

    try:
        scheduler = getattr(dispatcher, "automation", None)
        if scheduler is not None:
            scheduler.shutdown()
    except Exception as exc:
        print(f"{_tag('SHUTDOWN WARN', _WARN)} Automation scheduler: {exc}", flush=True)


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
        print(f"\n{_tag('JARVIS WHATSAPP GROUP', _BGOLD)} {_c(_WHITE, group)}:")
        print(f"  {_c(_DIM, 'Message:')} {message}")
        print(f"  {_c(_DIM, 'Reply')} {_c(_BGREEN, 'YES')} {_c(_DIM, 'to send or')} {_c(_BRED, 'NO')} {_c(_DIM, 'to cancel.')}")
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
        print(f"\n{_tag('JARVIS WHATSAPP REVIEW', _BGOLD)} Message from {_c(_WHITE, sender)}:")
        print(f"  {_c(_DIM, 'Message:')} {event.get('incoming', '')}")
        print(f"  {_c(_DIM, 'Why review is needed:')} {event.get('reason', 'Not enough reliable context.')}")
        evidence = str(event.get("evidence", "")).strip()
        if evidence:
            print(f"  {_c(_DIM, 'Available evidence:')} {evidence}")
        drafts = []
        if str(event.get("suggested_reply", "")).strip():
            drafts.append(str(event["suggested_reply"]).strip())
        drafts.extend(str(x).strip() for x in event.get("alternatives", []) if str(x).strip())
        for index, draft in enumerate(drafts[:2], 1):
            print(f"  {_c(_BCYAN, f'Draft {index}:')} {draft}")
        print(f"  {_c(_DIM, 'Decide:')} {_c(_BGREEN, f'wa-reply {review_id} 1')} {_c(_DIM, '|')} {_c(_BGOLD, f'wa-reply {review_id} 2')}")
    return True

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
        print(f"{_c(_J, 'JARVIS')} {_tag('NOTIFICATIONS', _BMAG)} {_c(_WHITE, summary)}", flush=True)
        _web_notify(summary)


async def _read_prompt_async(working=False):
    global _cli_pending_text, _auto_update_notified
    pending_idle_since = None
    prompt_label = (
        HTML('<style fg="#2fe39a"><b>J❯</b></style> ')
        if is_float_mode()
        else HTML('') if working
        else HTML('<style fg="#5af78e"><b>YOU</b></style>  <style fg="#606060">❯</style> ')
    )
    prompt_task = asyncio.create_task(
        _cli_prompt_session.prompt_async(
            prompt_label,
            default=_cli_pending_text,
            bottom_toolbar=_cli_bottom_toolbar,
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
                try:
                    _cli_pending_text = _cli_prompt_session.default_buffer.text
                except Exception:
                    _cli_pending_text = ""
                prompt_task.cancel()
                try:
                    await prompt_task
                except asyncio.CancelledError:
                    pass
                return command.strip(), "voice"

            active_future = globals().get("_active_task_future")
            if active_future is not None and active_future.done():
                try:
                    _cli_pending_text = _cli_prompt_session.default_buffer.text
                except Exception:
                    _cli_pending_text = ""
                prompt_task.cancel()
                try: await prompt_task
                except asyncio.CancelledError: pass
                return "", "task_done"

            if _auto_updater.pending:
                try:
                    has_draft = bool(_cli_prompt_session.default_buffer.text.strip())
                except Exception:
                    has_draft = False
                active = globals().get("_active_task_future")
                if not has_draft and (active is None or active.done()):
                    if pending_idle_since is None:
                        pending_idle_since = time.monotonic()
                    idle_seconds = max(30.0, float(os.getenv("JARVIS_UPDATE_IDLE_SECONDS", "90")))
                    if time.monotonic() - pending_idle_since >= idle_seconds:
                        if apply_auto_update_if_ready(approved=True):
                            prompt_task.cancel()
                            try:
                                await prompt_task
                            except asyncio.CancelledError:
                                pass
                            return "", "update_restart"
                        pending_idle_since = None
                else:
                    pending_idle_since = None
            else:
                pending_idle_since = None
            await asyncio.sleep(0.08)

        _service_cli_background_events()
        return (await prompt_task).strip(), "text"
    finally:
        if not prompt_task.done():
            prompt_task.cancel()
        try:
            await prompt_task
        except BaseException:
            pass


def _answer_btw(question):
    """Answer an ephemeral side question without changing the active task or chat history."""
    global _btw_agent
    question = str(question or "").strip()
    if not question:
        return "Usage: /btw your side question"
    try:
        if _btw_agent is None:
            from agents.fast_agent import FastAgent
            _btw_agent = FastAgent(enable_extensions=False)
        prompt = (
            "This is an ephemeral side question asked while JARVIS is working on another task. "
            "Answer only this question, briefly and directly. Do not use tools, do not modify "
            "the active task, do not claim to have performed actions, and do not add this "
            "exchange to the active task's context.\n\n"
            f"Side question: {question}"
        )
        answer = _btw_agent._answer_simple_direct(prompt, allow_omniroute_fallback=False)
        return str(answer or "").strip() or "I couldn't produce a side answer."
    except Exception as exc:
        return f"[BTW ERROR] {type(exc).__name__}: {exc}"


def _cli_bottom_toolbar():
    try:
        from monitoring.token_meter import snapshot
        usage = snapshot()
    except Exception:
        usage = {}
    active = _active_task_future is not None and not _active_task_future.done()
    provider = usage.get("provider") or "JARVIS"
    model = usage.get("model") or ""
    if active:
        return HTML('<style bg="#1a2a1a" fg="#2fe39a"><b> ⟐ JARVIS WORKING </b></style>')
    return HTML('<style bg="#0a1a2a" fg="#3fd8ff"><b> ⟐ JARVIS READY </b></style>')


def read_prompt(working=False):
    """Editable prompt responsive to voice and notifications.

    During an active task the prompt label is hidden, avoiding a second YOU
    prompt while retaining /btw and queued text input.
    """
    while True:
        prompt, source = asyncio.run(_read_prompt_async(working=working))
        if source in {"update_restart", "task_done"}: return prompt, source
        if prompt: return prompt, source


# ==============================================================
# MAIN (plain terminal CLI)   -   the fancy UI is: python jarvis_ui.py
# ==============================================================

def main():

    # Preload the supplied ZIP voice server only when Alan/Bryce is selected.
    # Edge TTS remains the default and does not start the local Sherpa server.
    try:
        from voice.tts_manager import _provider
        if _provider() == "say":
            from voice.jarvis_voice_runtime import ensure_server
            ensure_server()
            print(f"{_tag('VOICE', _OK)} ZIP say server is ready.", flush=True)
    except Exception as exc:
        print(f"{_tag('VOICE WARN', _WARN)} Local ZIP voice server unavailable: {exc}", flush=True)

    init_services()
    start_auto_updater()
    time.sleep(1.2)

    if is_float_mode():
        print(f"{_J}JARVIS FLOAT ONLINE{_R}")
        print(f"{_DIM}Commands: /memory | /clear | exit{_R}")
    else:
        web_url = "http://127.0.0.1:8765"
        try:
            import jarvis_ui, jarvis_web
            url = jarvis_web.start(jarvis_ui, sys.modules[__name__])
            if url:
                web_url = url
        except Exception as exc:
            print(f"{_tag('WEB UI DISABLED', _WARN)} {exc}")

        # Startup diagnostics are useful while services initialize, but the
        # interactive terminal should begin with one clean, persistent banner.
        clear_scrollback()

        print(f"\n{_B}{_BCYAN}    ┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓{_R}")
        print(f"{_B}{_BCYAN}    ┃{_R}  {_B}{_WHITE}J.A.R.V.I.S.{_R}  {_DIM}System Online{_R}        {_B}{_BCYAN}┃{_R}")
        print(f"{_B}{_BCYAN}    ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛{_R}")
        print(f"  {_c(_DIM, '▸')} {_c(_BCYAN, '/memory')}    {_c(_DIM, 'Inspect memory')}")
        print(f"  {_c(_DIM, '▸')} {_c(_BCYAN, '/clear')}     {_c(_DIM, 'Clear terminal')}")
        print(f"  {_c(_DIM, '▸')} {_c(_BCYAN, '/history')}   {_c(_DIM, 'Chat sessions')}")
        print(f"  {_c(_DIM, '▸')} {_c(_BCYAN, '/resume')}    {_c(_DIM, 'Resume a chat  (+ CODE)')}")
        print(f"  {_c(_DIM, '▸')} {_c(_BCYAN, '/newchat')}   {_c(_DIM, 'Start fresh session')}")
        print(f"  {_c(_DIM, '▸')} {_c(_BCYAN, '/btw')}       {_c(_DIM, 'Side question while working')}")
        print(f"  {_c(_DIM, '▸')} {_c(_BCYAN, '/update')}    {_c(_DIM, 'Check for updates')}")
        print(f"  {_c(_DIM, '▸')} {_c(_BCYAN, 'Jarvis Web')} {_c(_DIM, web_url)}")
        print(f"  {_c(_DIM, '▸')} {_c(_BCYAN, 'exit')}       {_c(_DIM, 'Shut down')}")
    print()

    from concurrent.futures import ThreadPoolExecutor
    global _active_task_future, _auto_update_notified
    task_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="jarvis-chat")

    with patch_stdout():
        while True:
            try:
                while True:
                    summary = pop_notification()
                    if summary is None:
                        break
                    print(f"\n{_c(_J, 'JARVIS')} {_tag('NOTIFICATIONS', _BMAG)} {_c(_WHITE, summary)}\n", flush=True)
                    _web_notify(summary)

                if _deferred_prompts:
                    prompt, prompt_source = _deferred_prompts.pop(0)
                else:
                    prompt, prompt_source = read_prompt()

                if prompt_source == "update_restart":
                    print(f"\n{_tag('JARVIS UPDATE', _OK)} Update installed. Restarting into the new version...", flush=True)
                    shutdown()
                    restart_after_update()
                if prompt_source == "task_done" or not prompt:
                    continue

                update_command = re.fullmatch(r"/update(?:\s+(approve|later))?", prompt.strip(), re.IGNORECASE)
                if update_command:
                    action = (update_command.group(1) or "").lower()
                    if not _auto_updater.pending:
                        print(f"{_tag('JARVIS UPDATE', _ACCENT)} No update is pending.\n", flush=True)
                    elif action == "approve":
                        if apply_auto_update_if_ready(approved=True):
                            print(f"{_tag('JARVIS UPDATE', _OK)} Approved and installed. Restarting...", flush=True)
                            shutdown()
                            restart_after_update()
                        else:
                            print(f"{_tag('JARVIS UPDATE', _ERR)} Update could not be installed; see data/auto_update.log.\n", flush=True)
                    elif action == "later":
                        _auto_update_notified = True
                        print(f"{_tag('JARVIS UPDATE', _ACCENT)} Still queued; it will install automatically after a safe idle window.\n", flush=True)
                    else:
                        print(_auto_updater.pending_summary() + "\n", flush=True)
                    continue

                if prompt.lower() in {"exit", "quit"}:
                    shutdown()
                    print(f"\n{_B}{_BCYAN}    ┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓{_R}")
                    print(f"{_B}{_BCYAN}    ┃{_R}  {_B}{_WHITE}J.A.R.V.I.S.{_R}  {_DIM}System Offline{_R}       {_B}{_BCYAN}┃{_R}")
                    print(f"{_B}{_BCYAN}    ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛{_R}")
                    break

                # /clear is a terminal-display command, not a chat/database command.
                if prompt.strip().lower() == "/clear":
                    if not clear_scrollback():
                        print(f"{_tag('CLEAR', _WARN)} This terminal does not support scrollback clearing.", flush=True)
                    continue

                if (
                    whatsapp_autoreply is not None
                    and whatsapp_autoreply.pending_group_replies
                    and prompt.strip().lower() in {"yes", "y", "confirm"}
                ):
                    print(f"{_c(_J, 'JARVIS')} {_c(_DIM, '❯')} {whatsapp_autoreply.confirm_latest_group_reply(True)}\n")
                    continue
                if (
                    whatsapp_autoreply is not None
                    and whatsapp_autoreply.pending_group_replies
                    and prompt.strip().lower() in {"no", "n", "cancel"}
                ):
                    print(f"{_c(_J, 'JARVIS')} {_c(_DIM, '❯')} {whatsapp_autoreply.confirm_latest_group_reply(False)}\n")
                    continue

                review_match = re.fullmatch(
                    r"wa-reply\s+(\S+)\s+(1|2|skip|none|no|0)",
                    prompt.strip(),
                    re.IGNORECASE,
                )
                if review_match:
                    if whatsapp_autoreply is None:
                        print(f"{_tag('WHATSAPP', _WARN)} Auto-reply worker is not running.")
                    else:
                        try:
                            result = whatsapp_autoreply.resolve_reply_review(
                                review_match.group(1), review_match.group(2)
                            )
                            print(f"{_c(_J, 'JARVIS')} {_c(_DIM, '❯')} {result}\n")
                        except Exception as exc:
                            print(f"{_c(_J, 'JARVIS')} {_c(_DIM, '❯')} {_c(_ERR, 'Could not process reply decision:')} {exc}\n")
                    continue

                if prompt.lower() in MEMORY_VIEW_COMMANDS:
                    print_memory()
                    continue

                if prompt_source == "voice":
                    print(f"{_c(_U, 'YOU')} {_c(_BGOLD, '(VOICE)')} {_c(_DIM, '❯')} {prompt}", flush=True)
                dispatcher.fast_agent._last_used_tools = []
                future = task_pool.submit(handle_prompt, prompt, prompt_source)
                _active_task_future = future

                # Keep the responsive input channel for /btw and queued messages,
                # but hide its YOU label while the current request is processing.
                while True:
                    incoming, incoming_source = read_prompt(working=True)
                    if incoming_source == "task_done":
                        break
                    if not incoming:
                        continue
                    if incoming.strip().lower().startswith("/btw"):
                        side_question = re.sub(r"^/btw\s*", "", incoming.strip(), flags=re.IGNORECASE)
                        if not side_question:
                            print(f"{_tag('JARVIS BTW', _ACCENT)} Usage: /btw your side question", flush=True)
                            continue
                        print(f"{_c(_U, 'YOU')} {_c(_BBLUE, '(BTW)')} {_c(_DIM, '❯')} {side_question}", flush=True)
                        side_answer = _answer_btw(side_question)
                        print(f"{_c(_J, 'JARVIS')} {_c(_BBLUE, '(BTW)')} {_c(_DIM, '❯')} {side_answer}\n", flush=True)
                    else:
                        _deferred_prompts.append((incoming, incoming_source))
                        print(f"{_tag('JARVIS', _ACCENT)} Current task is still running. Message queued.", flush=True)

                _active_task_future = None
                try:
                    answer, should_speak = future.result()
                except Exception as exc:
                    answer, should_speak = f"[ERROR] {type(exc).__name__}: {exc}", False

                if not answer:
                    continue

                print(f"{_c(_J, 'JARVIS')} {_c(_DIM, '❯')} {answer}\n", flush=True)
                if should_speak:
                    speak(answer, user_prompt=prompt)

            except KeyboardInterrupt:
                shutdown()
                print(f"\n{_c(_J, 'JARVIS OFFLINE')}")
                break
            except EOFError:
                shutdown()
                print(f"\n{_c(_J, 'JARVIS OFFLINE')}")
                break
            except Exception as exc:
                _active_task_future = None
                print(f"\n{_tag('FATAL ERROR', _ERR)} {exc}\n")

if __name__ == "__main__":
    main()
