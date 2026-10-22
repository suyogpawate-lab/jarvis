import jarvis_env
from jarvis_env import TERMUX_BASH
"""
JARVIS Android control layer.
"""

import difflib
import json
import os
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path

# Inventory of installed apps (package, label, common names). Built by
# `python setup.py apps` and refreshed automatically when an app is missing.
APPS_JSON = Path(jarvis_env.__file__).resolve().parent / "apps.json"


class AndroidTools:

    # Single source of truth for friendly app names (dispatcher + agents use this).
    APP_ALIASES = {
        # Communication and social
        "whatsapp": "com.whatsapp",
        "discord": "com.discord",
        "truecaller": "com.truecaller",
        "instagram": "com.instagram.android",
        "threads": "com.instagram.barcelona",
        "twitter": "com.twitter.android",
        "x": "com.twitter.android",
        "facebook": "com.facebook.katana",
        "messenger": "com.facebook.orca",
        "telegram": "org.telegram.messenger",
        "snapchat": "com.snapchat.android",
        "reddit": "com.reddit.frontpage",

        # AI assistants
        "chatgpt": "com.openai.chatgpt",
        "claude": "com.anthropic.claude",
        "grok": "ai.x.grok",
        "gemini": "com.google.android.apps.bard",
        "copilot": "com.microsoft.copilot",
        "google assistant": "com.google.android.apps.googleassistant",

        # Browsers
        "chrome": "com.android.chrome",
        "google chrome": "com.android.chrome",
        "firefox": "org.mozilla.firefox",
        "tor browser": "org.torproject.torbrowser",
        "edge": "com.microsoft.emmx",
        "brave": "com.brave.browser",

        # Google apps
        "youtube": "com.google.android.youtube",
        "youtube music": "com.google.android.apps.youtube.music",
        "youtube studio": "com.google.android.apps.youtube.creator",
        "gmail": "com.google.android.gm",
        "maps": "com.google.android.apps.maps",
        "google maps": "com.google.android.apps.maps",
        "drive": "com.google.android.apps.docs",
        "google drive": "com.google.android.apps.docs",
        "photos": "com.google.android.apps.photos",
        "google photos": "com.google.android.apps.photos",
        "files": "com.google.android.apps.nbu.files",
        "google files": "com.google.android.apps.nbu.files",
        "play store": "com.android.vending",
        "calendar": "com.google.android.calendar",
        "calculator": "com.google.android.calculator",
        "contacts": "com.google.android.contacts",
        "phone": "com.google.android.dialer",
        "messages": "com.google.android.apps.messaging",
        "google messages": "com.google.android.apps.messaging",
        "settings": "com.android.settings",
        "clock": "com.google.android.deskclock",

        # Termux and development
        "termux": "com.termux",
        "termux api": "com.termux.api",
        "termux widget": "com.termux.widget",
        "termux window": "com.termux.window",
        "pydroid": "ru.iiec.pydroid3",
        "arduino droid": "name.antonsmirnov.android.arduinodroid2",

        # Microsoft and media
        "excel": "com.microsoft.office.excel",
        "word": "com.microsoft.office.word",
        "powerpoint": "com.microsoft.office.powerpoint",
        "vlc": "org.videolan.vlc",
        "spotify": "com.spotify.music",

        # Shopping and services
        "amazon": "in.amazon.mShop.android.shopping",
        "hotstar": "in.startv.hotstar",
        "disney hotstar": "in.startv.hotstar",
        "zepto": "com.zeptoconsumerapp",
        "rapido": "com.rapido.passenger",
        "myjio": "com.jio.myjio",

        # VPN / security
        "proton vpn": "ch.protonvpn.android",
        "windscribe": "com.windscribe.vpn",
        "malwarebytes": "org.malwarebytes.antimalware",

        # Notes and games
        "notes": "notes.notepad.checklist.calendar.todolist.notebook",
        "notepad": "notes.notepad.checklist.calendar.todolist.notebook",
        "call of duty": "com.activision.callofduty.shooter",
        "cod mobile": "com.activision.callofduty.shooter",
        "fifa": "com.ea.gp.fifamobile",
        "spaceflight simulator": "com.StefMorojna.SpaceflightSimulator",
        "jarvis companion": "com.jarvis.companion",
    }


    def _run(self, command, timeout=15):
        try:
            p = subprocess.run(
                command,
                shell=True,
                executable=TERMUX_BASH,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return {
                "exit": p.returncode,
                "stdout": p.stdout.strip(),
                "stderr": p.stderr.strip(),
            }

        except subprocess.TimeoutExpired:
            return {
                "exit": -1,
                "stdout": "",
                "stderr": "Command timed out.",
            }

        except Exception as exc:
            return {
                "exit": -1,
                "stdout": "",
                "stderr": str(exc),
            }

    @staticmethod
    def _quote(value):
        return "'" + str(value).replace("'", "'\\''") + "'"

    def find_contact(self, name):
        return self._run(
            "termux-contact-list"
        )

    def list_packages(self, third_party_only=False):
        command = (
            "pm list packages -3"
            if third_party_only
            else "pm list packages"
        )
        return self._run(command)

    def list_launcher_apps(self):
        return self._run(
            "cmd package query-activities "
            "--user 0 "
            "--brief "
            "-a android.intent.action.MAIN "
            "-c android.intent.category.LAUNCHER"
        )

    def find_package(self, name):
        name = str(name).strip().lower()

        result = self.list_packages()

        if result["exit"] != 0:
            return result

        matches = []

        for line in result["stdout"].splitlines():
            package = line.removeprefix("package:").strip()

            if name in package.lower():
                matches.append(package)

        for package in self._index_lookup(name):
            if package not in matches:
                matches.append(package)

        if not matches:
            return {
                "exit": 1,
                "stdout": "",
                "stderr": f"No package matched '{name}'.",
            }

        return {
            "exit": 0,
            "stdout": "\n".join(matches),
            "stderr": "",
        }

    def find_launcher_app(self, name):
        norm = self._normalize_app_name(name)
        hits = self._index_lookup(norm)
        if hits:
            return {"exit": 0, "stdout": "\n".join(hits), "stderr": ""}
        result = self._find_launcher_app_by_package(name)
        if result["exit"] != 0 and self._refresh_index_on_miss():
            hits = self._index_lookup(norm)
            if hits:
                return {"exit": 0, "stdout": "\n".join(hits), "stderr": ""}
        return result

    def _find_launcher_app_by_package(self, name):
        name = self._normalize_app_name(name)
        packages = self._installed_packages(refresh=True)

        if packages is None:
            return {"exit": 1, "stdout": "", "stderr": "Could not list launcher apps."}

        for package in packages:                       # exact package ID
            if package.lower() == name:
                return {"exit": 0, "stdout": package, "stderr": ""}

        compact = name.replace(" ", "")
        tokens = [t for t in name.split() if t]
        matches = [
            pkg for pkg in packages
            if compact in pkg.lower().replace("_", "")
            or (tokens and all(t in pkg.lower() for t in tokens))
        ]
        if not matches:
            # Fuzzy fallback: compare against each meaningful package segment
            # (handles typos / speech-to-text errors like "whatsap", "instagrm").
            generic = {"com", "org", "net", "in", "android", "apps", "app", "google", "www"}
            scored = []
            for pkg in packages:
                segs = [x for x in re.split(r"[._]", pkg.lower()) if x and x not in generic]
                best = max(
                    (difflib.SequenceMatcher(None, compact, seg).ratio() for seg in segs),
                    default=0.0,
                )
                if best >= 0.78:
                    scored.append((best, pkg))
            if scored:
                scored.sort(key=lambda t: (-t[0], len(t[1])))
                return {"exit": 0, "stdout": "\n".join(p for _, p in scored), "stderr": ""}
            return {"exit": 1, "stdout": "", "stderr": f"No launcher app matched '{name}'."}

        # Best first: last segment equals the name, then shortest ID.
        matches.sort(key=lambda p: (p.rsplit(".", 1)[-1].lower() != compact, len(p)))
        return {"exit": 0, "stdout": "\n".join(matches), "stderr": ""}

    def resolve_package(self, package):
        package = str(package).strip()

        return self._run(
            "cmd package resolve-activity "
            "--user 0 "
            "--brief "
            + self._quote(package)
        )

    # ------------------------------------------------------------------
    # App resolution + launch
    # ------------------------------------------------------------------
    _LAUNCHER_TTL = 30.0
    _FAIL_RE = re.compile(
        r"^\s*error\b|exception|unable to resolve|does not exist|no activity found",
        re.IGNORECASE | re.MULTILINE,
    )

    def _launcher_packages(self, refresh=False):
        """Installed launchable packages (cached briefly). None if the query failed."""
        cache = getattr(self, "_lp_cache", None)
        if cache and not refresh and time.time() - cache[0] < self._LAUNCHER_TTL:
            return cache[1]
        result = self.list_launcher_apps()
        if result["exit"] != 0:
            return None
        packages = []
        for line in result["stdout"].splitlines():
            line = line.strip()
            if "/" not in line or line.startswith("No activities"):
                continue
            pkg = line.split("/", 1)[0].split()[-1]
            if pkg not in packages:
                packages.append(pkg)
        self._lp_cache = (time.time(), packages)
        return packages

    def _installed_packages(self, refresh=False):
        """Launchable packages; falls back to `pm list packages` if that query is empty."""
        packages = self._launcher_packages(refresh=refresh)
        if packages:
            return packages
        result = self.list_packages()
        if result["exit"] == 0:
            found = [
                line.removeprefix("package:").strip()
                for line in result["stdout"].splitlines()
                if line.strip()
            ]
            return found or None
        return None

    # ------------------------------------------------------------------
    # Installed-app inventory (apps.json)
    # ------------------------------------------------------------------
    _GENERIC_SEGMENTS = {
        "com", "org", "net", "in", "io", "co", "android", "apps", "app",
        "google", "www", "mobile", "free", "lite", "main", "client", "release",
    }

    @staticmethod
    def _name_key(value):
        value = re.sub(r"[^\w\s]", " ", str(value or "").casefold())
        return re.sub(r"\s+", " ", value).strip()

    def _aapt_command(self):
        cached = getattr(self, "_aapt_cmd", None)
        if cached is not None:
            return cached or None
        result = self._run("command -v aapt || command -v aapt2")
        found = result["stdout"].splitlines()[0].strip() if result["exit"] == 0 and result["stdout"] else ""
        self._aapt_cmd = found or False
        return found or None

    def _app_label(self, package, aapt):
        """The name shown under the app's icon, read from its APK. None if unavailable."""
        path = self._run("pm path " + self._quote(package))
        apks = [l.removeprefix("package:").strip() for l in path["stdout"].splitlines() if l.startswith("package:")]
        if path["exit"] != 0 or not apks:
            return None
        apk = next((a for a in apks if a.endswith("base.apk")), apks[0])
        result = self._run(
            self._quote(aapt) + " dump badging " + self._quote(apk) + " 2>/dev/null | grep '^application-label'",
            timeout=25,
        )
        labels = {}
        for line in result["stdout"].splitlines():
            m = re.match(r"application-label(?:-([\w-]+))?:'(.*)'\s*$", line.strip())
            if m and m.group(2).strip():
                labels[m.group(1) or ""] = m.group(2).strip()
        for key in ("", "en", "en-US", "en-GB", "en-IN"):
            if key in labels:
                return labels[key]
        return next(iter(labels.values()), None)

    def _make_app_entry(self, package, label):
        names = []

        def add(value):
            key = self._name_key(value)
            if key and key not in names:
                names.append(key)

        if label:
            add(label)
            add(label.replace(" ", ""))
        for alias, pkg in self.APP_ALIASES.items():
            if pkg == package:
                add(alias)
        tail = package.rsplit(".", 1)[-1]
        if len(tail) >= 3 and tail.lower() not in self._GENERIC_SEGMENTS:
            add(tail.replace("_", " "))
        return {"package": package, "label": label or "", "names": names}

    def load_app_index(self):
        """Entries from apps.json ([] if missing/unreadable). Re-read when the file changes."""
        try:
            mtime = APPS_JSON.stat().st_mtime
        except OSError:
            return []
        cache = getattr(self, "_app_index_cache", None)
        if cache and cache[0] == mtime:
            return cache[1]
        try:
            data = json.loads(APPS_JSON.read_text(encoding="utf-8"))
            entries = [e for e in data.get("apps", []) if isinstance(e, dict) and e.get("package")]
        except (OSError, ValueError, AttributeError):
            return []
        self._app_index_cache = (mtime, entries)
        return entries

    def build_app_index(self, progress=None, incremental=False):
        """
        Scan installed launchable apps and write apps.json.
        incremental=True keeps known apps and only reads labels of newly installed ones.
        """
        packages = self._launcher_packages(refresh=True) or self._installed_packages(refresh=True)
        if not packages:
            return {"exit": 1, "stderr": "Could not list installed apps."}

        aapt = self._aapt_command()
        existing = {e["package"]: e for e in self.load_app_index()} if incremental else {}

        entries = []
        total = len(packages)
        for i, package in enumerate(packages, 1):
            old = existing.get(package)
            if old and (old.get("label") or not aapt):
                entries.append(old)
                continue
            label = self._app_label(package, aapt) if aapt else None
            entries.append(self._make_app_entry(package, label))
            if progress:
                progress(i, total, package, label)

        entries.sort(key=lambda e: (e["label"] or e["package"]).casefold())
        payload = {
            "version": 1,
            "generated": datetime.now().astimezone().isoformat(timespec="seconds"),
            "labels_from": "aapt" if aapt else "package names and aliases only",
            "apps": entries,
        }
        tmp = APPS_JSON.with_name(APPS_JSON.name + ".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
        os.replace(tmp, APPS_JSON)
        return {
            "exit": 0,
            "count": len(entries),
            "labelled": sum(1 for e in entries if e["label"]),
            "aapt": bool(aapt),
            "path": str(APPS_JSON),
        }

    def _index_lookup(self, name):
        """Packages matching a spoken/typed app name, best first. [] if none."""
        key = self._name_key(name)
        entries = self.load_app_index()
        if not key or not entries:
            return []
        preferred = self.APP_ALIASES.get(self._normalize_app_name(name))

        def order(pkgs):
            return sorted(pkgs, key=lambda p: (p != preferred, len(p)))

        exact = [e["package"] for e in entries if key in e["names"]]
        if exact:
            return order(exact)

        tokens = key.split()
        if all(len(t) >= 3 for t in tokens):
            loose = []
            for e in entries:
                label_tokens = self._name_key(e["label"]).split()
                if label_tokens and all(any(lt.startswith(t) for lt in label_tokens) for t in tokens):
                    loose.append((len(e["label"]), e["package"]))
            if loose:
                return order([p for _, p in sorted(loose)])

        if len(key) >= 4:
            scored = []
            for e in entries:
                best = max(
                    (difflib.SequenceMatcher(None, key, n).ratio() for n in e["names"]),
                    default=0.0,
                )
                if best >= 0.84:
                    scored.append((-best, len(e["package"]), e["package"]))
            if scored:
                return [p for _, _, p in sorted(scored)]
        return []

    def _refresh_index_on_miss(self):
        """After a failed lookup, pick up newly installed apps (cheap, at most once every 20 seconds)."""
        if not APPS_JSON.exists():
            return False
        if time.time() - getattr(self, "_last_index_refresh", 0) < 20:
            return False
        self._last_index_refresh = time.time()
        return self.build_app_index(incremental=True).get("exit") == 0

    @staticmethod
    def _normalize_app_name(name):
        name = re.sub(r"\s+", " ", str(name or "").strip().casefold())
        name = re.sub(r"^(?:the|my)\s+", "", name)
        name = re.sub(r"\s+(?:app|application)$", "", name)
        return name.strip(" .!?")

    @staticmethod
    def looks_like_package_id(value):
        """com.example.app style IDs; not domains ('google.com') or files ('notes.txt')."""
        value = str(value or "").strip()
        if not re.fullmatch(r"[A-Za-z][\w]*(?:\.[A-Za-z_][\w]*)+", value):
            return False
        tail = value.rsplit(".", 1)[-1].lower()
        return tail not in {
            "com", "org", "net", "io", "in", "co", "edu", "gov", "app", "dev", "ai",
            "txt", "md", "py", "sh", "json", "pdf", "log", "csv", "html", "js", "zip",
        }

    def resolve_app(self, name):
        """
        Map a friendly name / alias / package ID to an installed launchable package.

        Returns {"exit": 0, "stdout": <package>} or {"exit": 1, "stderr": <reason>}.
        Aliases are only trusted when that package is really installed; otherwise
        resolution falls back to matching the name against installed launcher apps.
        """
        raw = str(name or "").strip()
        norm = self._normalize_app_name(raw)
        if not norm:
            return {"exit": 1, "stdout": "", "stderr": "No application specified."}

        if not self.looks_like_package_id(raw):
            hits = self._index_lookup(norm)
            if hits:
                return {"exit": 0, "stdout": hits[0], "stderr": ""}

        installed = self._installed_packages()

        alias = self.APP_ALIASES.get(norm)
        if alias:
            if installed is None or alias in installed:
                return {"exit": 0, "stdout": alias, "stderr": ""}
            # alias points at an app that isn't installed: try discovery below

        if self.looks_like_package_id(raw):
            if installed is None or raw in installed:
                return {"exit": 0, "stdout": raw, "stderr": ""}
            return {"exit": 1, "stdout": "", "stderr": f"Package '{raw}' is not installed."}

        found = self.find_launcher_app(norm)
        if found["exit"] != 0:
            return found
        return {"exit": 0, "stdout": found["stdout"].splitlines()[0].strip(), "stderr": ""}

    def launch_package(self, package):
        """Launch an installed Android app by package ID or friendly name."""
        resolved = self.resolve_app(package)
        if resolved["exit"] != 0:
            return resolved
        package = resolved["stdout"]

        # `am start` often exits 0 even when nothing launched, so inspect its output.
        result = self._run(
            "am start --user 0 "
            "-a android.intent.action.MAIN "
            "-c android.intent.category.LAUNCHER "
            "-p " + self._quote(package)
        )
        output = (result["stdout"] + "\n" + result["stderr"]).strip()
        if result["exit"] != 0 or self._FAIL_RE.search(output):
            # Fallback: monkey launches the default launcher activity.
            alt = self._run(
                "monkey -p " + self._quote(package)
                + " -c android.intent.category.LAUNCHER 1"
            )
            alt_out = (alt["stdout"] + "\n" + alt["stderr"])
            if alt["exit"] == 0 and "Events injected: 1" in alt_out:
                return alt
            return {
                "exit": 1,
                "stdout": result["stdout"],
                "stderr": output or f"Could not launch {package}.",
            }
        return result

    def get_foreground_app(self):
        """
        Return the package/activity currently associated with
        Android's resumed foreground activity.
        """
        result = self._run(
            "dumpsys activity activities | "
            "grep -m 1 -E 'mResumedActivity|ResumedActivity'"
        )

        if result["exit"] != 0:
            return result

        return result

    def list_services(self, package):
        package = str(package).strip()

        return self._run(
            "cmd package query-services "
            "--user 0 "
            "--brief "
            "-p "
            + self._quote(package)
        )

    def list_activities(self, package):
        package = str(package).strip()

        return self._run(
            "cmd package query-activities "
            "--user 0 "
            "--brief "
            "-p "
            + self._quote(package)
        )

    def background_launch_package(self, package):
        """
        Launch an app's launcher activity (what "start X in background" asks for).

        Android may still bring the UI forward; this does not bypass background-start
        restrictions. (Discovery lives in background_start_package, defined below.)
        """
        return self.launch_package(package)

    def start_service(self, component):
        """
        Request Android to start an explicitly named service.

        component must be:
            package/class
        """
        component = str(component).strip()

        if "/" not in component:
            return {
                "exit": 1,
                "stdout": "",
                "stderr": "Service component must be package/class.",
            }

        return self._run(
            "am startservice --user 0 -n "
            + self._quote(component)
        )

    def stop_service(self, component):
        """
        Stop an explicitly named Android service.
        """
        component = str(component).strip()

        if "/" not in component:
            return {
                "exit": 1,
                "stdout": "",
                "stderr": "Service component must be package/class.",
            }

        return self._run(
            "am stopservice --user 0 -n "
            + self._quote(component)
        )

    def start_foreground_service(self, component):
        """
        Request an explicitly named Android foreground service.
        component must be package/class.
        """
        component = str(component).strip()

        if "/" not in component:
            return {
                "exit": 1,
                "stdout": "",
                "stderr": "Service component must be package/class.",
            }

        return self._run(
            "am start-foreground-service --user 0 -n "
            + self._quote(component)
        )

    def force_stop_package(self, package):
        """
        Force-stop an Android package.
        """
        package = str(package).strip()

        if not package:
            return {
                "exit": 1,
                "stdout": "",
                "stderr": "Package name missing.",
            }

        if "." not in package:
            resolved = self.find_launcher_app(package)

            if resolved["exit"] != 0:
                return resolved

            package = resolved["stdout"].splitlines()[0]

        return self._run(
            "am force-stop --user 0 "
            + self._quote(package)
        )

    def summarize_inspection(self, raw, app_name=None):
        """
        Convert verified Android package inspection output into a
        concise deterministic human-readable summary.

        No AI inference is used.
        """

        import re

        package = None
        activities = []
        services = []

        section = None

        for line in raw.splitlines():
            line = line.strip()

            if not line:
                continue

            if line.startswith("PACKAGE:"):
                package = line.split(":", 1)[1].strip()
                continue

            if line == "ACTIVITIES:":
                section = "activities"
                continue

            if line == "SERVICES:":
                section = "services"
                continue

            if section == "activities":
                if "/" in line and not line.startswith(
                    ("priority=", "match=", "specificIndex=", "Activity")
                ):
                    activities.append(line)

            elif section == "services":
                if "/" in line and not line.startswith(
                    ("priority=", "match=", "specificIndex=", "Service")
                ):
                    services.append(line)

        def component_name(component):
            return component.rsplit("/", 1)[-1]

        def simplify_name(name):
            name = name.replace("$", " ")
            name = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", name)
            name = re.sub(r"[_\-]+", " ", name)
            name = re.sub(r"\s+", " ", name)
            return name.strip()

        def describe_component(component, component_type):
            name = component_name(component)
            simple = simplify_name(name)
            lower = simple.lower()

            if "settings" in lower:
                role = "settings-related component"
            elif "search" in lower or "results" in lower:
                role = "search/results component"
            elif "home" in lower:
                role = "home/main interface component"
            elif "watch" in lower or "media" in lower:
                role = "media/playback component"
            elif "notification" in lower or "fcm" in lower:
                role = "notification/messaging component"
            elif "firebase" in lower:
                role = "Firebase messaging component"
            elif "browser" in lower:
                role = "media-browser component"
            elif "provenance" in lower:
                role = "media provenance component"
            elif "capability" in lower:
                role = "device-capability component"
            elif "network" in lower:
                role = "network-related component"
            elif "live" in lower:
                role = "live-content component"
            elif "creation" in lower:
                role = "content-creation component"
            else:
                role = "registered Android component"

            return f"{simple} — {role}"

        output = [
            "[ANDROID_INSPECT]",
            "STATUS: SUCCESS",
        ]

        if app_name:
            output.append(f"APP: {app_name}")

        if package:
            output.append(f"PACKAGE: {package}")

        output.append("")

        output.append(f"ACTIVITIES: {len(activities)}")

        for activity in activities:
            output.append(
                f"- {describe_component(activity, 'activity')}"
            )

        output.append("")

        output.append(f"SERVICES: {len(services)}")

        for service in services:
            output.append(
                f"- {describe_component(service, 'service')}"
            )

        output.append("")

        output.append(
            f"REGISTERED COMPONENTS: "
            f"{len(activities) + len(services)}"
        )

        return "\n".join(output)

    def inspect_package(self, package):
        """
        Inspect activities and services exposed by a package.
        """
        package = str(package).strip()

        if not package:
            return {
                "exit": 1,
                "stdout": "",
                "stderr": "Package name missing.",
            }

        if "." not in package:
            resolved = self.find_launcher_app(package)

            if resolved["exit"] != 0:
                return resolved

            package = resolved["stdout"].splitlines()[0]

        activities = self.list_activities(package)
        services = self.list_services(package)

        output = [
            f"PACKAGE: {package}",
            "",
            "ACTIVITIES:",
            activities["stdout"] or "(none)",
            "",
            "SERVICES:",
            services["stdout"] or "(none)",
        ]

        return {
            "exit": (
                0
                if activities["exit"] == 0 or services["exit"] == 0
                else 1
            ),
            "stdout": "\n".join(output),
            "stderr": (
                ""
                if activities["exit"] == 0 or services["exit"] == 0
                else (
                    activities["stderr"]
                    or services["stderr"]
                    or f"Unable to inspect {package}."
                )
            ),
        }

    def background_start_package(self, package):
        """
        Discover background-capable components.

        Does NOT launch the application.
        """
        return self.inspect_package(package)

    def open_url(self, url):
        return self._run(
            "termux-open " + self._quote(url)
        )

    def toast(self, message):
        return self._run(
            "termux-toast " + self._quote(message)
        )

    def send_intent(self, action, data=None):
        command = (
            "am start --user 0 -a "
            + self._quote(action)
        )

        if data:
            command += " -d " + self._quote(str(data))

        return self._run(command)
