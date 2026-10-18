import threading
import queue
import select
import sys
from pathlib import Path

import readline
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
        r"^(?:jarvis[,\s]+)?discuss\s+(.+?)"
        r"\s+for\s+(\d+)\s*"
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
# LOCAL ANDROID ROUTER (NO LLM LATENCY)
# ==============================================================
# Exact device actions are handled before CommandDispatcher/Groq.
# Add aliases here as needed. Package IDs are checked against the
# installed package list before attempting to launch an app.

ANDROID_APP_ALIASES = {
    "yt": ("com.google.android.youtube", "com.google.android.youtube"),
    "youtube": ("com.google.android.youtube", "com.google.android.youtube"),
    "chrome": ("com.android.chrome", "com.google.android.chrome"),
    "google chrome": ("com.android.chrome", "com.google.android.chrome"),
    "google": ("com.google.android.googlequicksearchbox",),
    "gmail": ("com.google.android.gm",),
    "maps": ("com.google.android.apps.maps",),
    "google maps": ("com.google.android.apps.maps",),
    "play store": ("com.android.vending",),
    "playstore": ("com.android.vending",),
    "settings": ("com.android.settings",),
    "camera": ("com.android.camera2", "com.google.android.GoogleCamera"),
    "photos": ("com.google.android.apps.photos",),
    "google photos": ("com.google.android.apps.photos",),
    "files": ("com.google.android.documentsui", "com.google.android.apps.nbu.files"),
    "google files": ("com.google.android.apps.nbu.files",),
    "whatsapp": ("com.whatsapp",),
    "telegram": ("org.telegram.messenger",),
    "instagram": ("com.instagram.android",),
    "facebook": ("com.facebook.katana",),
    "messenger": ("com.facebook.orca",),
    "spotify": ("com.spotify.music",),
    "discord": ("com.discord",),
    "reddit": ("com.reddit.frontpage",),
    "tiktok": ("com.zhiliaoapp.musically",),
    "netflix": ("com.netflix.mediaclient",),
    "amazon": ("com.amazon.mShop.android.shopping",),
    "chatgpt": ("com.openai.chatgpt",),
    "ollama": ("com.termux",),
    "termux": ("com.termux",),
}

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
    try:
        result = subprocess.run(
            ["pm", "list", "packages"],
            capture_output=True, text=True, timeout=4
        )
        return {
            line.strip().split(":", 1)[-1]
            for line in result.stdout.splitlines()
            if line.strip().startswith("package:")
        }
    except Exception:
        return set()


def _launch_android_package(package):
    installed = _android_package_ids()
    if package not in installed:
        return False
    # monkey launches the package's launcher activity without an LLM.
    result = subprocess.run(
        ["monkey", "-p", package, "1"],
        capture_output=True, text=True, timeout=8
    )
    return result.returncode == 0 and (
        "No activities found" not in (result.stdout + result.stderr)
    )


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
    candidates = ANDROID_APP_ALIASES.get(app_text)

    # For unknown names, attempt a conservative package-name match.
    # Never fuzzy-match a normal sentence to an installed app.
    if candidates is None and re.fullmatch(r"[a-z0-9][a-z0-9 ._-]{0,39}", app_text):
        packages = _android_package_ids()
        slug = app_text.replace(" ", "").replace("-", "").replace("_", "")
        matches = [
            pkg for pkg in packages
            if slug and slug in pkg.lower().replace(".", "")
        ]
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
            "It may not be installed, or its package ID may need an alias."
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


def handle_prompt(prompt):
    """
    Process ONE user message.

    Returns (answer_text_or_None, should_speak).
    Nothing is printed or spoken here, so the CLI and the
    terminal UI can each present the answer their own way.
    """

    prompt = prompt.strip()

    if not prompt:
        return None, False

    guard_reply = handle_guard_reply(prompt)
    if guard_reply is not None:
        return guard_reply, False

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
        dispatched = dispatcher.dispatch(prompt)

        if dispatched is not None:
            answer = str(dispatched or "").strip()

            if answer:
                save_message("assistant", answer)
                return answer, True

            return None, False

    except Exception as exc:
        print(f"\n[DISPATCH ERROR] {exc}\n")

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


def init_services():
    global notification_watcher, voice_listener

    ensure_whatsapp_daemon()

    notification_watcher = NotificationWatcher(
        output_queue=notification_queue
    ).start()

    try:
        from voice.listener import WhisperWakeListener
        voice_listener = WhisperWakeListener(voice_command_queue).start()
    except Exception as exc:
        print(f"[VOICE DISABLED] {exc}", flush=True)


def shutdown():
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


def read_prompt():
    print("YOU  > ", end="", flush=True)
    while True:
        try:
            command = voice_command_queue.get_nowait()
            if command.strip():
                return command.strip()
        except queue.Empty:
            pass

        summary = pop_notification()
        if summary is not None:
            print(f"\\nJARVIS [NOTIFICATIONS] > {summary}")
            print("YOU  > ", end="", flush=True)

        ready, _, _ = select.select([sys.stdin], [], [], 0.25)
        if ready:
            line = sys.stdin.readline()
            if line == "":
                raise EOFError
            return line.strip()


# ==============================================================
# MAIN (plain terminal CLI)   -   the fancy UI is: python jarvis_ui.py
# ==============================================================

def main():

    init_services()

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

            prompt = read_prompt()

            if not prompt:
                continue

            if prompt.lower() in {"exit", "quit"}:
                shutdown()
                print("JARVIS OFFLINE")
                break

            if prompt.lower() in MEMORY_VIEW_COMMANDS:
                print_memory()
                continue

            answer, should_speak = handle_prompt(prompt)

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
