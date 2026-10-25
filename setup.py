#!/usr/bin/env python3
"""
JARVIS first-run setup.

    python setup.py                 # full guided setup
    python setup.py gmail           # just one part: keys | gmail | whatsapp | contacts | apps
    python setup.py wake            # generate/cache prerecorded wake acknowledgements
    python setup.py --status        # show what is configured (secrets are masked)

What it configures
    keys      AI provider keys (Groq, Gemini, Anthropic and OmniRoute required; search keys optional)
    gmail     Gmail account(s) + App Password, tested against Gmail before saving
    whatsapp  links your WhatsApp account to the local bridge (pairing code or QR)
    contacts  syncs your phone contacts and an optional "priority people" list
    apps      scans installed apps (package + name shown on your home screen) into apps.json

Everything personal ends up in files that git ignores:
    .env, contacts.json, priority_contacts.txt, apps.json, whatsapp/auth/
Standard library only, so it runs before any pip install.
"""

import argparse
import getpass
import imaplib
import importlib.util
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from jarvis_env import parse_env_line  # noqa: E402  (stdlib-only module)

ENV_PATH = ROOT / ".env"
WA_DIR = ROOT / "whatsapp"
WA_AUTH = WA_DIR / "auth"
WA_PORT = 23841
CONTACTS_PATH = ROOT / "contacts.json"
PRIORITY_PATH = ROOT / "priority_contacts.txt"
APPS_PATH = ROOT / "apps.json"

USE_COLOR = sys.stdout.isatty()


def detect_system_timezone():
    """Return the device's IANA timezone name without asking the user."""
    # Android/Termux exposes the canonical zone ID, unlike date +%Z,
    # which returns abbreviations such as IST that are ambiguous worldwide.
    commands = []
    getprop = shutil.which("getprop")
    if getprop:
        commands.append([getprop, "persist.sys.timezone"])
    if Path("/system/bin/getprop").is_file():
        commands.append(["/system/bin/getprop", "persist.sys.timezone"])

    for command in commands:
        try:
            result = subprocess.run(
                command, capture_output=True, text=True, timeout=2, check=False
            )
            name = result.stdout.strip()
            if result.returncode == 0 and re.fullmatch(
                r"[A-Za-z0-9_+.-]+(?:/[A-Za-z0-9_+.-]+)*", name
            ) and "/" in name:
                return name
        except (OSError, subprocess.SubprocessError):
            pass

    # On Unix, /etc/localtime is often a symlink into the IANA zoneinfo tree.
    try:
        localtime = os.path.realpath("/etc/localtime")
        marker = "/zoneinfo/"
        if marker in localtime:
            name = localtime.split(marker, 1)[1]
            if re.fullmatch(r"[A-Za-z0-9_+.-]+(?:/[A-Za-z0-9_+.-]+)*", name):
                return name
    except OSError:
        pass

    # Respect a platform-provided TZ identifier only after checking system data.
    name = os.environ.get("TZ", "").strip().lstrip(":")
    if "/" in name and re.fullmatch(r"[A-Za-z0-9_+.-]+(?:/[A-Za-z0-9_+.-]+)*", name):
        return name
    return None


def sync_system_timezone(env):
    """Persist the automatically detected system zone for JARVIS components."""
    name = detect_system_timezone()
    if name:
        if env.get("JARVIS_TIMEZONE") != name:
            env.set("JARVIS_TIMEZONE", name)
            env.save()
        os.environ["JARVIS_TIMEZONE"] = name
        info(f"System timezone detected automatically: {name}")
        return name
    warn("Could not identify the system's IANA timezone; JARVIS will use its runtime local-time fallback.")
    return None


# ─────────────────────────── small UI helpers ───────────────────────────

def _c(code, text):
    return f"\033[{code}m{text}\033[0m" if USE_COLOR else text


def info(msg):
    print(_c("36", "•"), msg)


def ok(msg):
    print(_c("32", "✓"), msg)


def warn(msg):
    print(_c("33", "!"), msg)


def fail(msg):
    print(_c("31", "✗"), msg)


def heading(title):
    print()
    print(_c("1;35", f"── {title} " + "─" * max(4, 60 - len(title))))


def ask(prompt, default=None, secret=False, validate=None, allow_empty=True):
    """Prompt until valid. Enter returns `default` (or '' when there is none)."""
    suffix = f" [{default}]" if default else ""
    while True:
        try:
            raw = (getpass.getpass if secret else input)(f"  {prompt}{suffix}: ")
        except EOFError:
            raise KeyboardInterrupt
        value = raw.strip()
        if not value:
            if default is not None:
                return default
            if allow_empty:
                return ""
            warn("A value is required.")
            continue
        if validate:
            problem = validate(value)
            if problem:
                warn(problem)
                continue
        return value


def yes_no(prompt, default=True):
    hint = "Y/n" if default else "y/N"
    while True:
        try:
            raw = input(f"  {prompt} [{hint}]: ").strip().lower()
        except EOFError:
            raise KeyboardInterrupt
        if not raw:
            return default
        if raw in ("y", "yes"):
            return True
        if raw in ("n", "no"):
            return False


def mask(value):
    value = str(value or "")
    if not value:
        return "(not set)"
    if len(value) <= 8:
        return "set"
    return f"{value[:4]}…{value[-2:]} ({len(value)} chars)"


# ───────────────────────────── .env handling ─────────────────────────────

class EnvFile:
    """Edit .env in place: keeps comments and unknown keys, writes with mode 600."""

    def __init__(self, path):
        self.path = Path(path)
        self.lines = []
        if self.path.is_file():
            self.lines = self.path.read_text(encoding="utf-8").splitlines()

    def get(self, key, default=""):
        found = default
        for line in self.lines:
            parsed = parse_env_line(line)
            if parsed and parsed[0] == key:
                found = parsed[1]
        return found

    @staticmethod
    def _format(key, value):
        if re.fullmatch(r"[A-Za-z0-9_@.+:/,=-]*", value):
            return f"{key}={value}"
        return f'{key}="{value}"'

    def set(self, key, value):
        value = str(value)
        if any(ch in value for ch in ('"', "\n", "\r")):
            raise ValueError(f"{key}: value contains a quote or newline")
        new_line = self._format(key, value)
        for i, line in enumerate(self.lines):
            parsed = parse_env_line(line)
            if parsed and parsed[0] == key:
                self.lines[i] = new_line
                return
        self.lines.append(new_line)

    def unset(self, key):
        self.lines = [
            line for line in self.lines
            if not ((p := parse_env_line(line)) and p[0] == key)
        ]

    def save(self):
        text = "\n".join(self.lines).rstrip("\n") + "\n"
        tmp = self.path.with_name(self.path.name + ".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.path)


# ───────────────────────────── 1. AI keys ─────────────────────────────

def split_keys(raw):
    return [k for k in re.split(r"[,\s]+", raw.strip()) if k]


def test_groq_key(key):
    """Return (True|False|None, message). None means 'could not verify'."""
    request = urllib.request.Request(
        "https://api.groq.com/openai/v1/models",
        headers={"Authorization": f"Bearer {key}", "User-Agent": "jarvis-setup"},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return (response.status == 200, f"HTTP {response.status}")
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            return False, "Groq rejected this key"
        return None, f"HTTP {exc.code}"
    except (urllib.error.URLError, OSError) as exc:
        return None, f"could not reach Groq ({exc})"


REQUIRED_KEYS = [
    ("GEMINI_API_KEYS", "Gemini API key(s), comma-separated"),
    ("ANTHROPIC_API_KEYS", "Anthropic (Claude) API key(s), comma-separated"),
    ("OMNIROUTE_BASE_URL", "OmniRoute base URL (default http://127.0.0.1:20128/v1)"),
    ("OMNIROUTE_API_KEY", "OmniRoute API key"),
]

OPTIONAL_KEYS = [
    ("BRAVE_SEARCH_API_KEY", "Brave Search API key"),
    ("BING_SEARCH_API_KEY", "Bing Search API key"),
    ("VERIPHONE_API_KEY", "Veriphone API key (phone lookup)"),
]


def step_keys(env):
    heading("AI provider keys")
    info("Groq is the main model provider. Get a key at https://console.groq.com/keys")

    current = split_keys(env.get("GROQ_API_KEYS") or env.get("GROQ_API_KEY"))
    if current:
        info(f"Currently configured: {len(current)} Groq key(s).")

    raw = ask("Groq API key(s), comma-separated (Enter to keep current)", secret=True)
    if raw:
        keys = split_keys(raw)
        if not all(k.startswith("gsk_") for k in keys):
            warn("Groq keys normally start with 'gsk_' - double-check what you pasted.")
        good, detail = test_groq_key(keys[0])
        if good:
            ok("First key works.")
        elif good is None:
            warn(f"Could not verify the key ({detail}). Saving it anyway.")
        else:
            fail(f"{detail}.")
            if not yes_no("Save it anyway?", default=False):
                keys = []
        if keys:
            env.set("GROQ_API_KEYS", ",".join(keys))
            env.unset("GROQ_API_KEY")
            env.save()
            ok(f"Saved {len(keys)} Groq key(s).")
    elif not current:
        warn("No Groq key set - JARVIS will not be available.")

    info("Gemini, Anthropic and OmniRoute are also required for full JARVIS.")
    for var, label in REQUIRED_KEYS:
        secret = var.endswith("KEY") or var.endswith("KEYS")
        have = env.get(var)
        shown = f" (currently {mask(have) if secret else have})" if have else ""
        value = ask(f"{label}{shown} - Enter to keep current", secret=secret)
        if value:
            env.set(var, value)
            env.save()
        elif not have and var != "OMNIROUTE_BASE_URL":
            warn(f"{var} not set - JARVIS will not work fully without it.")
    ok("Provider keys saved.")

    if yes_no("Configure optional search keys (Brave, Bing, Veriphone)?", default=False):
        for var, label in OPTIONAL_KEYS:
            secret = var.endswith("KEY") or var.endswith("KEYS")
            have = env.get(var)
            shown = f" (currently {mask(have) if secret else have})" if have else ""
            value = ask(f"{label}{shown} - Enter to skip", secret=secret)
            if value:
                env.set(var, value)
                env.save()
        ok("Optional keys saved.")


# ───────────────────────────── 2. Gmail ─────────────────────────────

GMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@(gmail|googlemail)\.com$", re.IGNORECASE)


def gmail_accounts(env):
    accounts = {}
    for index in range(1, 10):
        email = env.get(f"JARVIS_GMAIL_{index}_EMAIL")
        if email:
            accounts[index] = email
    return accounts


def test_gmail(email, app_password):
    """Return (True|False|None, message) by logging in to Gmail IMAP."""
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com", 993, timeout=15)
    except OSError as exc:
        return None, f"could not reach imap.gmail.com ({exc})"
    try:
        mail.login(email, app_password)
        mail.logout()
        return True, "login OK"
    except imaplib.IMAP4.error as exc:
        text = str(exc)
        if "AUTHENTICATIONFAILED" in text.upper() or "Invalid credentials" in text:
            return False, "Gmail rejected the login (wrong App Password, or IMAP is disabled)"
        if "Application-specific password required" in text:
            return False, "Gmail requires an App Password (not your normal password)"
        return False, text
    except OSError as exc:
        return None, f"network problem ({exc})"


def step_gmail(env):
    heading("Gmail")
    info("JARVIS uses a Gmail *App Password*, never your normal password.")
    info("1) Turn on 2-Step Verification:  https://myaccount.google.com/security")
    info("2) Create an App Password:       https://myaccount.google.com/apppasswords")
    info("3) Make sure IMAP is enabled in Gmail > Settings > Forwarding and POP/IMAP.")

    accounts = gmail_accounts(env)
    for index, email in accounts.items():
        info(f"Configured: {email}  (password {mask(env.get(f'JARVIS_GMAIL_{index}_APP_PASSWORD'))})")

    if not yes_no("Add or update a Gmail account?", default=not accounts):
        return

    while True:
        email = ask(
            "Gmail address",
            validate=lambda v: None if GMAIL_RE.match(v) else "Enter a full @gmail.com address.",
            allow_empty=False,
        ).lower()

        def check_pw(value):
            cleaned = value.replace(" ", "")
            return None if re.fullmatch(r"[A-Za-z0-9]{16}", cleaned) else (
                "An App Password is 16 letters (spaces are fine)."
            )

        password = ask("App Password (hidden)", secret=True, validate=check_pw,
                       allow_empty=False).replace(" ", "")

        info("Testing login with Gmail...")
        good, detail = test_gmail(email, password)
        if good:
            ok("Gmail login works.")
        elif good is None:
            warn(f"Could not verify ({detail}). You can still save it.")
        else:
            fail(detail)

        if good is not True and not yes_no("Save this account anyway?", default=(good is None)):
            pass
        else:
            accounts = gmail_accounts(env)
            slot = next((i for i, e in accounts.items() if e.lower() == email), None)
            if slot is None:
                free = [i for i in range(1, 10) if i not in accounts]
                if not free:
                    fail("All 9 account slots are used.")
                    break
                slot = free[0]
            env.set(f"JARVIS_GMAIL_{slot}_EMAIL", email)
            env.set(f"JARVIS_GMAIL_{slot}_APP_PASSWORD", password)
            env.save()
            ok(f"Saved {email}.")

        if not yes_no("Add another Gmail account?", default=False):
            break

    accounts = gmail_accounts(env)
    if len(accounts) > 1:
        current = env.get("JARVIS_DEFAULT_EMAIL")
        listing = ", ".join(accounts.values())
        choice = ask(f"Default account for 'send an email' ({listing})",
                     default=current or next(iter(accounts.values())))
        env.set("JARVIS_DEFAULT_EMAIL", choice.lower())
        env.save()
    elif accounts:
        env.unset("JARVIS_DEFAULT_EMAIL")
        env.save()


# ───────────────────────────── 3. WhatsApp ─────────────────────────────

def whatsapp_linked():
    creds = WA_AUTH / "creds.json"
    try:
        return bool(json.loads(creds.read_text(encoding="utf-8")).get("registered"))
    except (OSError, ValueError):
        return False


def bridge_status():
    """Return the bridge's /status dict, or None when it is not running."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{WA_PORT}/status", timeout=3) as r:
            return json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return None


def npm_install_whatsapp():
    baileys = WA_DIR / "node_modules" / "@whiskeysockets" / "baileys"
    if baileys.is_dir():
        return True
    info("Installing WhatsApp bridge packages (this can take a few minutes)...")
    use_ci = (WA_DIR / "package-lock.json").is_file()
    for command in (["npm", "ci", "--omit=dev"] if use_ci else None, ["npm", "install", "--omit=dev"]):
        if not command:
            continue
        if subprocess.run(command, cwd=WA_DIR).returncode == 0:
            return True
    return False


def stop_process_group(proc):
    if proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        proc.terminate()
    try:
        proc.wait(timeout=8)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            proc.kill()


def run_bridge_until_linked(command, env, timeout=300, poll=2.0, status_fn=None, linked_fn=None):
    """
    Start the bridge, relay its output (pairing code / QR), wait until the
    account is linked and connected, then stop it. Returns True on success.
    """
    status_fn = status_fn or bridge_status
    linked_fn = linked_fn or whatsapp_linked

    proc = subprocess.Popen(
        command, cwd=WA_DIR, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1, start_new_session=True,
    )

    def relay():
        for line in proc.stdout:
            line = line.rstrip("\n")
            if "PAIRING CODE" in line:
                print(_c("1;32", f"\n    {line}\n"))
            else:
                print(f"    {line}")

    threading.Thread(target=relay, daemon=True).start()

    success = False
    deadline = time.time() + timeout
    try:
        while time.time() < deadline:
            if proc.poll() is not None:
                fail(f"The bridge exited early (code {proc.returncode}).")
                return False
            status = status_fn()
            if status and status.get("connected") and linked_fn():
                success = True
                break
            time.sleep(poll)
        if success:
            time.sleep(3)  # let the session files finish writing
        else:
            fail("Timed out waiting for WhatsApp to link.")
    except KeyboardInterrupt:
        warn("Interrupted.")
    finally:
        stop_process_group(proc)
    return success


def step_whatsapp(env):
    heading("WhatsApp")
    if not (WA_DIR / "bridge.js").is_file():
        fail("whatsapp/bridge.js not found - skipping.")
        return
    if not shutil.which("node") or not shutil.which("npm"):
        fail("Node.js is missing. Run: pkg install nodejs   (install.sh does this for you)")
        return

    if bridge_status() is not None:
        warn("A WhatsApp bridge is already running on port %d." % WA_PORT)
        warn('Stop it first (pkill -f "node bridge.js") and run `python setup.py whatsapp` again.')
        return

    if whatsapp_linked():
        ok("WhatsApp is already linked.")
        if not yes_no("Unlink it and link a different account?", default=False):
            return
        if not yes_no("This deletes the saved WhatsApp session on this device. Continue?", default=False):
            return
        shutil.rmtree(WA_AUTH, ignore_errors=True)

    if not yes_no("Link a WhatsApp account now?", default=True):
        return
    if not npm_install_whatsapp():
        fail("Could not install the bridge packages. Check your connection and retry.")
        return

    child_env = os.environ.copy()
    info("How do you want to link?")
    info("  1) Pairing code  - best when WhatsApp is on THIS phone (you cannot scan your own screen)")
    info("  2) QR code       - scan from another phone")
    method = ask("Choose 1 or 2", default="1", validate=lambda v: None if v in ("1", "2") else "Type 1 or 2.")

    if method == "1":
        number = re.sub(r"\D", "", ask(
            "Your WhatsApp number with country code, digits only (e.g. 911234567890)",
            validate=lambda v: None if 8 <= len(re.sub(r"\D", "", v)) <= 15 else "Expected 8-15 digits.",
            allow_empty=False,
        ))
        child_env["JARVIS_WHATSAPP_PAIR_NUMBER"] = number
        info("On your phone open WhatsApp > Settings > Linked devices > Link a device >")
        info("'Link with phone number instead', then type the code that appears below.")
    else:
        child_env.pop("JARVIS_WHATSAPP_PAIR_NUMBER", None)
        info("Scan the QR below: WhatsApp > Settings > Linked devices > Link a device.")

    if run_bridge_until_linked(["node", "bridge.js"], child_env):
        ok("WhatsApp linked. The session is stored in whatsapp/auth/ (never committed).")
        info("Start the bridge any time with:  bash whatsapp_daemon.sh")
        info("Keep it running in the background:  tmux new -d -s wa 'bash whatsapp_daemon.sh'")
    else:
        fail("Linking did not complete. Re-run:  python setup.py whatsapp")


# ───────────────────────────── 4. Contacts ─────────────────────────────

def clean_contacts(raw_list):
    cleaned = []
    for contact in raw_list:
        name = (contact.get("name") or contact.get("display_name") or "").strip()
        number = (contact.get("number") or contact.get("phone") or "").strip()
        number = re.sub(r"[^\d+]", "", number)
        if name and number:
            cleaned.append({"name": name, "number": number})
    return cleaned


def write_private(path, text):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(text)
    os.chmod(path, 0o600)


def step_contacts(env):
    heading("Contacts")
    if not shutil.which("termux-contact-list"):
        warn("termux-contact-list not found. Install Termux:API (app) and `pkg install termux-api`.")
    elif yes_no("Sync contacts from this phone now? (Android will ask for permission)", default=True):
        try:
            result = subprocess.run(["termux-contact-list"], capture_output=True, text=True, timeout=40)
            if result.returncode != 0:
                fail(f"Contact sync failed: {result.stderr.strip() or 'no permission?'}")
            else:
                contacts = clean_contacts(json.loads(result.stdout or "[]"))
                write_private(CONTACTS_PATH, json.dumps(contacts, indent=2, ensure_ascii=False))
                ok(f"Synced {len(contacts)} contacts to contacts.json (git-ignored).")
        except (subprocess.TimeoutExpired, ValueError) as exc:
            fail(f"Contact sync failed: {exc}")

    info("Priority people: calls/messages from these names are flagged as urgent.")
    if PRIORITY_PATH.is_file():
        info("priority_contacts.txt already exists.")
    raw = ask("Names, comma-separated (Enter to skip / keep)")
    if raw:
        names = [n.strip() for n in raw.split(",") if n.strip()]
        write_private(PRIORITY_PATH, "# one name per line\n" + "\n".join(names) + "\n")
        ok(f"Saved {len(names)} priority contact(s).")


# ───────────────────────────── 5. Installed apps ─────────────────────────────

def ensure_gitignored(filename):
    """Append `filename` to .gitignore when a .gitignore exists and lacks it."""
    path = ROOT / ".gitignore"
    try:
        if not path.is_file():
            return
        lines = path.read_text(encoding="utf-8").splitlines()
        if filename in (line.strip() for line in lines):
            return
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(("" if not lines or path.read_text(encoding="utf-8").endswith("\n") else "\n") + filename + "\n")
        info(f"Added {filename} to .gitignore.")
    except OSError:
        pass


def step_apps(env):
    heading("Installed apps")
    info("Builds apps.json: every launchable app with its package name and the name")
    info("shown under its icon, so you can say 'open Instagram' or 'open Calculator'.")

    try:
        from android.android_tools import AndroidTools
    except Exception as exc:  # noqa: BLE001 - show any import problem plainly
        fail(f"Could not load the Android tools ({exc}).")
        return

    if not (shutil.which("aapt") or shutil.which("aapt2")):
        warn("'aapt' is not installed, so real app names cannot be read (only package names).")
        if shutil.which("pkg") and yes_no("Install it now? (pkg install aapt)", default=True):
            if subprocess.run(["pkg", "install", "-y", "aapt"]).returncode == 0:
                ok("aapt installed.")
            else:
                warn("Could not install aapt; continuing with package names only.")

    if APPS_PATH.is_file() and not yes_no("apps.json already exists. Rescan all apps?", default=True):
        return

    tools = AndroidTools()
    started = time.time()

    def progress(done, total, package, label):
        print(f"\r    {done}/{total}  {(label or package)[:40]:<40}", end="", flush=True)

    result = tools.build_app_index(progress=progress)
    print()
    if result.get("exit") != 0:
        fail(result.get("stderr") or "Scan failed.")
        return
    ok(f"Saved {result['count']} apps to apps.json in {time.time() - started:.0f}s "
       f"({result['labelled']} with real names).")
    if not result["aapt"]:
        warn("Names came from package IDs only. Install aapt and rerun: python setup.py apps")
    ensure_gitignored("apps.json")
    info("New apps are picked up automatically the first time you ask for one that is missing.")



# ───────────────────────────── voice provider ─────────────────────────────

def step_voice(env):
    heading("Speech output")
    current = (env.get("JARVIS_TTS_PROVIDER", "edge") or "edge").strip().lower()
    if current not in ("edge", "piper", "sherpa"):
        current = "edge"
    info("Edge is network-based; Piper and Sherpa are local after their runtime assets are installed.")
    print("  1) Edge TTS (default)")
    print("  2) Piper C-API (local, single voice)")
    print("  3) Sherpa-ONNX (local, Alan + Bryce voices)")
    defaults = {"edge": "1", "piper": "2", "sherpa": "3"}
    choice = ask("Choose speech provider: 1=Edge, 2=Piper, 3=Sherpa dual voice", default=defaults[current])
    if choice.strip().lower() in ("3", "sherpa", "sherpa-onnx"):
        provider = "sherpa"
    elif choice.strip().lower() in ("2", "piper"):
        provider = "piper"
    else:
        provider = "edge"
    env.set("JARVIS_TTS_PROVIDER", provider)
    if provider == "piper":
        migration = ROOT / "scripts" / "prepare_piper_assets.py"
        try:
            subprocess.run([sys.executable, str(migration)], check=False)
        except OSError as exc:
            warn(f"Could not prepare repository-local Piper assets: {exc}")
        defaults = {
            "JARVIS_PIPER_LIBRARY": str(ROOT / "lib/piper/libpiper.so"),
            "JARVIS_PIPER_MODEL": str(ROOT / "models/piper/en_GB-alan-medium.onnx"),
            "JARVIS_PIPER_CONFIG": str(ROOT / "models/piper/en_GB-alan-medium.onnx.json"),
            "JARVIS_ESPEAK_DATA": str(ROOT / "voice/data/espeak-ng-data"),
            "JARVIS_PIPER_OUTPUT_DIR": str(ROOT / "cache/piper"),
        }
        for key, default in defaults.items():
            env.set(key, default)
        cfg = {
            "JARVIS_PIPER_LIBRARY": Path(env.get("JARVIS_PIPER_LIBRARY")).expanduser(),
            "JARVIS_PIPER_MODEL": Path(env.get("JARVIS_PIPER_MODEL")).expanduser(),
            "JARVIS_PIPER_CONFIG": Path(env.get("JARVIS_PIPER_CONFIG")).expanduser(),
            "JARVIS_ESPEAK_DATA": Path(env.get("JARVIS_ESPEAK_DATA")).expanduser(),
            "JARVIS_PIPER_OUTPUT_DIR": Path(env.get("JARVIS_PIPER_OUTPUT_DIR", str(ROOT / "cache/piper"))).expanduser(),
        }
        env.save()
        missing = [f"{key}: {path}" for key, path in cfg.items()
                   if not ((path.is_dir() and any(path.iterdir())) if key == "JARVIS_ESPEAK_DATA" else path.is_file())]
        if missing:
            warn("Piper selected, but these paths need attention:")
            for item in missing:
                warn("  " + item)
            info("Install a compatible Piper C-API package and voice model, then rerun ./voice-config.")
        else:
            ok("Piper paths exist. A live synthesis test will happen on first speech.")
    elif provider == "sherpa":
        selected_voice = ask(
            "Default Sherpa voice: 1=Alan (British), 2=Bryce (American)",
            default="1" if env.get("JARVIS_SHERPA_VOICE", "alan").lower() != "bryce" else "2",
        )
        env.set("JARVIS_SHERPA_VOICE", "bryce" if selected_voice.strip().lower() in ("2", "bryce") else "alan")
        env.save()
        info("Preparing both voice models (~125 MiB total download; assets stay in ignored models/sherpa/).")
        prepare = ROOT / "scripts" / "prepare_sherpa_assets.py"
        result = subprocess.run([sys.executable, str(prepare)], check=False)
        if result.returncode != 0:
            warn("Sherpa model download did not complete. Retry: python scripts/prepare_sherpa_assets.py")
        prefix = Path(os.environ.get("PREFIX", "/data/data/com.termux/files/usr"))
        espeak = Path(env.get("JARVIS_ESPEAK_DATA") or prefix / "share/espeak-ng-data").expanduser()
        if not espeak.is_dir() or not any(espeak.iterdir()):
            warn("eSpeak NG data is missing. Install it with: pkg install espeak-ng")
        try:
            import sherpa_onnx  # noqa: F401
            import soundfile  # noqa: F401
        except ImportError:
            info("Installing optional Sherpa runtime dependencies...")
            try:
                result = subprocess.run(
                    [sys.executable, "-m", "pip", "install", "-r", str(ROOT / "requirements-sherpa.txt")],
                    check=False,
                    timeout=180,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                result = None
                warn(f"Could not finish the optional Sherpa dependency install: {exc}")
            if result is not None and result.returncode != 0:
                warn("pip could not install the Sherpa runtime on this Android build.")
        try:
            import sherpa_onnx  # noqa: F401
            import soundfile  # noqa: F401
            ok("Sherpa-ONNX and soundfile are importable.")
        except ImportError:
            warn("Sherpa Python runtime is still unavailable.")
            info("Use a Termux-compatible sherpa-onnx build; see requirements-sherpa.txt.")
    else:
        env.save()
        ok("Edge TTS selected.")
    info("You can change this later with ./voice-config")


# ─────────────────────── wake acknowledgements ───────────────────────

def step_wake(env):
    heading("Wake-word acknowledgements")
    generator = ROOT / "scripts" / "generate_wake_responses.py"
    if not generator.is_file():
        warn("Wake-response generator is missing; skipping.")
        return
    cache_dir = Path.home() / ".cache" / "jarvis" / "wake_responses"
    existing = sum(
        1 for index in range(1, 26)
        if (cache_dir / f"wake_{index:02d}.mp3").is_file()
        and (cache_dir / f"wake_{index:02d}.mp3").stat().st_size > 1024
    )
    info(f"Prerecorded clips available: {existing}/25.")
    if existing == 25:
        ok("All wake acknowledgements are already generated.")
        return
    info("Generating missing clips requires internet access for Edge TTS.")
    if not yes_no("Generate the 25 wake-word acknowledgements now?", default=True):
        info("Skipped. JARVIS can use its speech synthesizer as a fallback.")
        return
    result = subprocess.run([sys.executable, str(generator)], cwd=ROOT, check=False)
    if result.returncode == 0:
        ok("Wake-word acknowledgements are ready.")
    else:
        warn(f"Clip generation exited with status {result.returncode}. Run later: python setup.py wake")


# ───────────────────────── message style profile ─────────────────────────

def step_message_style(env):
    heading("Message style and language")
    info("Applies to WhatsApp drafts and auto-replies. Context can override the saved default.")
    current_style = (env.get("JARVIS_MESSAGE_STYLE", "mirror") or "mirror").strip().lower()
    if current_style not in {"mirror", "casual", "genz", "friendly", "formal"}:
        current_style = "mirror"
    print("  1) Mirror my normal wording (default)")
    print("  2) Casual")
    print("  3) Gen Z / slang-friendly")
    print("  4) Friendly")
    print("  5) Formal")
    defaults = {"mirror": "1", "casual": "2", "genz": "3", "friendly": "4", "formal": "5"}
    choice = ask("Default message style", default=defaults[current_style])
    styles = {"1": "mirror", "2": "casual", "3": "genz", "4": "friendly", "5": "formal",
              "mirror": "mirror", "casual": "casual", "genz": "genz", "friendly": "friendly", "formal": "formal"}
    env.set("JARVIS_MESSAGE_STYLE", styles.get(choice.lower(), current_style))
    language = ask("Preferred messaging language (match, English, Hinglish, Hindi, etc.)",
                   default=env.get("JARVIS_MESSAGE_LANGUAGE", "match"))
    env.set("JARVIS_MESSAGE_LANGUAGE", language[:40] or "match")
    examples = ask("Your style examples (optional; e.g. damnnn, gng)", default=env.get("JARVIS_MESSAGE_EXAMPLES", ""))
    env.set("JARVIS_MESSAGE_EXAMPLES", examples[:500])
    env.save()
    ok("Message style saved.")
    info("Formal/professional requests and serious contexts override casual slang automatically.")


# ───────────────────────────── status ─────────────────────────────

def have_module(name):
    return importlib.util.find_spec(name) is not None


def show_status():
    env = EnvFile(ENV_PATH)
    heading("Status")

    if ENV_PATH.is_file():
        mode = oct(ENV_PATH.stat().st_mode & 0o777)
        (ok if mode == "0o600" else warn)(f".env present (permissions {mode})")
    else:
        warn(".env not found - run `python setup.py`")

    groq = split_keys(env.get("GROQ_API_KEYS") or env.get("GROQ_API_KEY"))
    (ok if groq else warn)(f"Groq keys: {len(groq)}")
    for var in ("GEMINI_API_KEYS", "ANTHROPIC_API_KEYS", "OMNIROUTE_API_KEY"):
        if env.get(var):
            ok(f"{var}: {mask(env.get(var))}")
        else:
            warn(f"{var}: NOT SET (required)")

    accounts = gmail_accounts(env)
    if accounts:
        for index, email in accounts.items():
            has_pw = bool(env.get(f"JARVIS_GMAIL_{index}_APP_PASSWORD"))
            (ok if has_pw else warn)(f"Gmail {index}: {email} ({'password set' if has_pw else 'NO app password'})")
    else:
        warn("Gmail: no account configured")

    if whatsapp_linked():
        live = bridge_status()
        ok("WhatsApp: linked" + (" and bridge running" if live and live.get("connected") else " (bridge not running)"))
    else:
        warn("WhatsApp: not linked")

    if CONTACTS_PATH.is_file():
        try:
            ok(f"Contacts: {len(json.loads(CONTACTS_PATH.read_text()))} synced")
        except ValueError:
            warn("Contacts file is unreadable")
    else:
        warn("Contacts: not synced")

    if APPS_PATH.is_file():
        try:
            data = json.loads(APPS_PATH.read_text(encoding="utf-8"))
            apps = data.get("apps", [])
            named = sum(1 for a in apps if a.get("label"))
            ok(f"Apps: {len(apps)} indexed ({named} with real names), scanned {data.get('generated', '?')}")
        except ValueError:
            warn("apps.json is unreadable - run: python setup.py apps")
    else:
        warn("Apps: not scanned - run: python setup.py apps")

    style = (env.get("JARVIS_MESSAGE_STYLE", "mirror") or "mirror").strip().lower()
    language = (env.get("JARVIS_MESSAGE_LANGUAGE", "match") or "match").strip()
    info(f"WhatsApp message style: {style}; language: {language}")

    heading("Tools")
    for tool in ("node", "npm", "termux-notification-list", "termux-contact-list", "ollama", "mpv", "tmux", "git"):
        (ok if shutil.which(tool) else warn)(f"{tool}: {'found' if shutil.which(tool) else 'missing'}")
    for module in ("requests", "openai", "rich", "edge_tts", "flask", "pypdf"):
        (ok if have_module(module) else warn)(f"python module {module}: {'found' if have_module(module) else 'missing (pip install -r requirements.txt)'}")


# ───────────────────────────── main ─────────────────────────────

STEPS = {
    "keys": step_keys,
    "gmail": step_gmail,
    "whatsapp": step_whatsapp,
    "contacts": step_contacts,
    "apps": step_apps,
    "voice": step_voice,
    "wake": step_wake,
    "message_style": step_message_style,
}


def main():
    parser = argparse.ArgumentParser(description="JARVIS first-run setup")
    parser.add_argument("sections", nargs="*", metavar="section",
                        help="any of: %s (default: all)" % ", ".join(STEPS))
    parser.add_argument("--status", action="store_true", help="show configuration status and exit")
    args = parser.parse_args()
    unknown = [name for name in args.sections if name not in (*STEPS, "all")]
    if unknown:
        parser.error("unknown section(s): %s (choose from %s)" % (", ".join(unknown), ", ".join(STEPS)))
    if not args.sections:
        args.sections = ["all"]

    if args.status:
        show_status()
        return 0

    if not sys.stdin.isatty():
        fail("Setup is interactive. Run it from a terminal:  python setup.py")
        return 2

    chosen = list(STEPS) if "all" in args.sections else args.sections
    print(_c("1;35", "\nJARVIS setup"))
    info("Everything personal stays on this device in git-ignored files.")
    info("Press Enter to skip any question. Ctrl-C quits (finished parts stay saved).")

    env = EnvFile(ENV_PATH)
    # Keep JARVIS aligned with the device timezone automatically. No prompt
    # or manual timezone configuration is required.
    sync_system_timezone(env)
    try:
        for name in chosen:
            STEPS[name](env)
    except KeyboardInterrupt:
        print()
        warn("Setup cancelled. Anything you already confirmed was saved.")
        return 130

    heading("Done")
    show_status()
    print()
    info("Start JARVIS:   python jarvis_ui.py")
    info("Change anything later with:   python setup.py <keys|gmail|whatsapp|contacts|apps|voice|wake|message_style>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
