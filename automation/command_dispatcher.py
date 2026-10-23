"""
JARVIS COMMAND DISPATCHER

Supports:

/remember <fact>
/project <fact>
/memory
/memory personal
/memory project
/discuss <topic>
/discuss5m <topic>

/remember X /project Y
/discuss X /remember Y

Multiple commands can exist in one input.
"""

import re
import shlex
import json
import os
from datetime import datetime, timedelta

from android.shell_executor import ShellExecutor
from messaging.contacts_manager import ContactsManager
from agents.autonomous_agent import AutonomousAgent
from android.system_tools import SystemTools
from android.process_tools import ProcessTools
from automation.job_manager import JobManager
from android.android_tools import AndroidTools
from monitoring.notification_ingestor import NotificationIngestor
from agents.local_ai import LocalAI
from agents.fast_agent import FastAgent
from automation.scheduler import AutomationScheduler
from voice.tts_manager import tts
from search.search_hub import build_default_search_hub
from search.deep_search import DeepSearch


class CommandDispatcher:

    COMMAND_PATTERN = re.compile(
        r"/(doctor|exec|bg|notifications?|discuss\d*(?:s|m)?|remember|project|memory)\b",
        re.IGNORECASE,
    )

    def __init__(
        self,
        jarvis,
        discussion,
        memory,
    ):
        self.jarvis = jarvis
        self.discussion = discussion
        self.memory = memory

        # Deterministic JARVIS abilities registry.
        self.abilities_file = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "config",
            "abilities.json",
        )

        with open(
            self.abilities_file,
            "r",
            encoding="utf-8",
        ) as f:
            self.abilities = json.load(f)

        if not isinstance(self.abilities, list):
            raise RuntimeError(
                "abilities.json must contain a JSON array."
            )
        self.shell = ShellExecutor()
        self.contacts = ContactsManager()
        self.system = SystemTools()
        self.processes = ProcessTools()
        self.jobs = JobManager()
        self.android = AndroidTools()
        self.notifications = NotificationIngestor()
        self.local_ai = LocalAI(model="qwen2.5:0.5b")
        self.search_hub = build_default_search_hub()
        self.fast_agent = FastAgent(search_hub=self.search_hub)
        self.deep_search = DeepSearch(self.search_hub, self.fast_agent)
        self.fast_agent.deep_search = self.deep_search

        # Groq calls WhatsApp through a tool; the dispatcher owns the
        # actual send (group confirmation gate, contact/group resolution).
        self.fast_agent.whatsapp_send_handler = self._whatsapp_tool_send


        # Injected by jarvis.py after the WhatsApp confirmation
        # worker is initialized.
        self.whatsapp_confirmation_worker = None

        # Persistent automation scheduler.
        # Timing is handled here; actual commands are routed
        # through the existing dispatcher when they become due.
        self.automation = AutomationScheduler(
            callback=self._scheduled_callback,
        )

        self.autonomous = AutonomousAgent(
            self.jarvis,
            self.shell,
            self.system,
            self.processes,
            self.android,
            self.jobs,
            self.fast_agent,
        )

    # ==========================================================
    # COMMAND SPLITTING
    # ==========================================================

    def split_commands(self, text):

        text = str(text).strip()

        if not text:
            return []

        matches = list(
            self.COMMAND_PATTERN.finditer(text)
        )

        if not matches:
            return []

        commands = []

        for index, match in enumerate(matches):

            command = match.group(1).lower()

            start = match.end()

            if index + 1 < len(matches):
                end = matches[index + 1].start()
            else:
                end = len(text)

            argument = text[start:end].strip()

            if argument or command == "doctor":
                commands.append(
                    (
                        command,
                        argument,
                    )
                )

        return commands

    # ==========================================================
    # DISCUSSION DURATION
    # ==========================================================

    def _discussion_duration(self, command):

        if command == "discuss":
            return 60

        match = re.fullmatch(
            r"discuss(\d+)(s|m)?",
            command,
            re.IGNORECASE,
        )

        if not match:
            return 60

        value = int(match.group(1))
        unit = match.group(2)

        if unit and unit.lower() == "m":
            value *= 60

        if value <= 0:
            value = 60

        # Safety cap for accidental huge values.
        return min(value, 3600)

    # ==========================================================
    # EXECUTE ONE COMMAND
    # ==========================================================

    def execute_one(
        self,
        command,
        argument,
    ):

        # ------------------------------------------------------
        # DOCTOR (read-only local diagnostics)
        # ------------------------------------------------------
        if command == "doctor":
            from monitoring.doctor import run_doctor
            return run_doctor()

        # ------------------------------------------------------
        # EXEC
        # ------------------------------------------------------

        if command == "exec":

            if not argument.strip():
                return "[ERROR] Shell command missing."

            return self.shell.execute(
                argument.strip()
            )

        # ------------------------------------------------------
        # BACKGROUND JOBS
        # ------------------------------------------------------

        if command == "bg":

            parts = argument.strip().split(
                maxsplit=1
            )

            if not parts:
                return (
                    "[ERROR] Usage: "
                    "/bg start|list|status|output|stop ..."
                )

            action = parts[0].lower()
            value = parts[1].strip() if len(parts) > 1 else ""

            if action == "start":

                if not value:
                    return "[ERROR] Background command missing."

                job = self.jobs.start(value)

                if "error" in job:
                    return f"[ERROR] {job['error']}"

                return (
                    "[OK] Background job started.\n"
                    f"ID: {job['id']}\n"
                    f"PID: {job['pid']}\n"
                    f"COMMAND: {job['command']}"
                )

            if action == "list":

                jobs = self.jobs.list()

                if not jobs:
                    return "[INFO] No background jobs."

                return "\n\n".join(
                    f"{j['id']} | "
                    f"{j['status']} | "
                    f"PID={j['pid']} | "
                    f"{j['command']}"
                    for j in jobs
                )

            if action == "status":

                if not value:
                    return "[ERROR] Job ID missing."

                result = self.jobs.status(value)

                if "error" in result:
                    return f"[ERROR] {result['error']}"

                return (
                    f"[JOB] {result['id']}\n"
                    f"STATUS: {result['status']}\n"
                    f"PID: {result['pid']}\n"
                    f"COMMAND: {result['command']}"
                )

            if action == "output":

                if not value:
                    return "[ERROR] Job ID missing."

                result = self.jobs.output(value)

                if "error" in result:
                    return f"[ERROR] {result['error']}"

                return (
                    f"[JOB] {result['id']}\n"
                    f"STATUS: {result['status']}\n"
                    f"[STDOUT]\n"
                    f"{result['stdout'] or '(empty)'}\n"
                    f"[STDERR]\n"
                    f"{result['stderr'] or '(empty)'}"
                )

            if action == "stop":

                if not value:
                    return "[ERROR] Job ID missing."

                result = self.jobs.stop(value)

                if "error" in result:
                    return f"[ERROR] {result['error']}"

                return (
                    f"[JOB] {result['id']}\n"
                    f"STATUS: {result['status']}"
                )

            return (
                "[ERROR] Unknown /bg action. "
                "Use start, list, status, output, or stop."
            )

        # ------------------------------------------------------
        # NOTIFICATIONS
        # ------------------------------------------------------

        if command in {"notification", "notifications"}:

            result = self.notifications.summary()

            if isinstance(result, dict) and "error" in result:
                return f"[ERROR] {result['error']}"

            notifications = result["notifications"]

            if not notifications:
                return "[INFO] No active notifications."

            lines = [
                f"[NOTIFICATIONS] {len(notifications)} active"
            ]

            for item in notifications:
                package = item["package"] or "(unknown)"
                title = item["title"] or "(no title)"
                content = item["content"] or "(no content)"
                when = item["when"] or "(unknown time)"

                lines.append(
                    f"\n[{package}]\n"
                    f"TITLE: {title}\n"
                    f"CONTENT: {content}\n"
                    f"WHEN: {when}"
                )

            return "\n".join(lines)

        # ------------------------------------------------------
        # REMEMBER
        # ------------------------------------------------------

        if command == "remember":

            self.memory.remember(
                argument,
                kind="personal",
            )

            return (
                "[MEMORY] Personal memory saved."
            )

        # ------------------------------------------------------
        # PROJECT
        # ------------------------------------------------------

        if command == "project":

            self.memory.remember(
                argument,
                kind="project",
            )

            return (
                "[MEMORY] Project memory saved."
            )

        # ------------------------------------------------------
        # MEMORY
        # ------------------------------------------------------

        if command == "memory":

            arg = argument.lower().strip()

            if arg in {
                "personal",
                "project",
            }:
                return self.memory.format_memory(
                    kind=arg
                )

            return self.memory.format_memory()

        # ------------------------------------------------------
        # DISCUSSION
        # ------------------------------------------------------

        if command.startswith("discuss"):

            duration = self._discussion_duration(
                command
            )

            topic = argument.strip()

            if not topic:
                return (
                    "[ERROR] Discussion topic missing."
                )

            print(
                "\n--- DISCUSSION ---\n",
                flush=True,
            )

            result = self.discussion.discuss(
                topic,
                duration=duration,
            )

            return (
                "\n--- SYNTHESIS ---\n\n"
                f"{result}"
            )

        return (
            f"[ERROR] Unknown command: /{command}"
        )

    # ==========================================================
    # MULTI COMMAND
    # ==========================================================

    def dispatch_commands(self, text):

        commands = self.split_commands(text)

        if not commands:
            return None

        results = []

        for command, argument in commands:

            try:

                result = self.execute_one(
                    command,
                    argument,
                )

                if result:
                    results.append(result)

            except Exception as exc:

                results.append(
                    f"[ERROR] /{command}: {exc}"
                )

        return "\n\n".join(results)

    # ==========================================================
    # NORMAL AI REQUEST WITH MEMORY
    # ==========================================================

    def _is_fast_request(self, text):
        """Deterministic gate for genuinely lightweight requests."""
        text = str(text).strip().lower()

        if not text:
            return False

        # Substantial reasoning requests stay on the complex path.
        complex_markers = (
            "research",
            "deep dive",
            "in detail",
            "comprehensive",
            "compare",
            "comparison",
            "architecture",
            "design a system",
            "plan",
            "strategy",
            "analyze this codebase",
            "investigate",
            "why does this fail",
            "debug this",
            "implement",
            "build",
            "develop",
            "write the code",
            "refactor",
        )

        if any(marker in text for marker in complex_markers):
            return False

        # Project-specific questions need JARVIS/project context.
        project_markers = (
            "jarvis",
            "omniroute",
            "owl",
            "freebuff",
            "our router",
            "our routing",
            "our code",
            "our project",
            "this project",
            "this codebase",
            "my code",
            "my project",
        )

        if any(marker in text for marker in project_markers):
            return False

        fast_patterns = (
            r"^(hi|hello|hey|thanks|thank you)\b",
            r"^(what|who|where|when|which|is|are|can|does|do)\b",
            r"^(define|meaning of|translate|summarize)\b",
            r"^(explain)\s+[^.]{0,120}$",
            r"\b(spell|abbreviation|acronym)\b",
            r"\b(what can you do|what are your abilities|what are your capabilities)\b",
        )

        return any(
            re.search(pattern, text)
            for pattern in fast_patterns
        )

    # ==========================================================
    # DETERMINISTIC ABILITIES HELPERS
    # ==========================================================

    def _groq_simple_request(self, text):
        """Send an obvious lightweight natural-language request directly to Groq."""
        return self._fast_agent_request(
            str(text).strip()
        )

    def _fast_agent_request(self, text):
        """Use Groq FastAgent for lightweight decision tasks."""
        try:
            return self.fast_agent.ask(text)
        except Exception as exc:
            # Keep the existing fallback behavior, but make provider failures diagnosable.
            print(
                f"[ROUTING WARN] Groq FastAgent failed "
                f"({type(exc).__name__}): {exc}",
                flush=True,
            )
            return None

    def _abilities_request(self, text):
        """
        Detect only explicit requests asking what JARVIS can do.

        Normal commands must never be intercepted by this route.
        """
        text = str(text).strip().lower()

        patterns = (
            r"^what can you do\??$",
            r"^what are your abilities\??$",
            r"^what are your capabilities\??$",
            r"^what can jarvis do\??$",
            r"^what are jarvis'?s abilities\??$",
            r"^what are jarvis'?s capabilities\??$",
            r"^list your abilities\??$",
            r"^list your capabilities\??$",
            r"^show your abilities\??$",
            r"^show your capabilities\??$",
        )

        return any(
            re.fullmatch(pattern, text, re.IGNORECASE)
            for pattern in patterns
        )

    def _format_abilities(self):
        """
        Format the deterministic abilities registry for display.
        """
        lines = []

        for index, ability in enumerate(self.abilities, 1):
            if isinstance(ability, str):
                value = ability.strip()
            elif isinstance(ability, dict):
                value = (
                    ability.get("description")
                    or ability.get("name")
                    or ability.get("ability")
                    or str(ability)
                )
                value = str(value).strip()
            else:
                value = str(ability).strip()

            if value:
                lines.append(f"{index}. {value}")

        if not lines:
            return "JARVIS abilities registry is empty."

        return "I can:\n" + "\n".join(lines)

    # ==========================================================
    # MAIN ENTRY
    # ==========================================================

    def _fast_android_explain(self, text):
        """
        Optional Android explanation hook.

        Returning None allows the existing Android and Groq
        routing below to handle the request.
        """
        return None

    def _fast_android_control(self, text):
        """Deterministic Android package/component control."""
        text = str(text).strip()

        # ----------------------------------------------------
        # INSPECT APP
        # ----------------------------------------------------
        match = re.match(
            r"^\s*inspect\s+(?:app|application|package\s+)?(.+?)\s*$",
            text,
            re.IGNORECASE,
        )

        if match:
            target = match.group(1).strip()

            try:
                result = self.autonomous.android.inspect_package(target)

                if result["exit"] == 0:
                    return self.autonomous.android.summarize_inspection(
                        result["stdout"],
                        app_name=target,
                    )

                return (
                    "[ANDROID_INSPECT]\n"
                    "STATUS: FAILED\n"
                    f"APP: {target}\n"
                    f"ERROR: {result['stderr'] or result['stdout']}"
                )

            except Exception as exc:
                return f"[ERROR] ANDROID_INSPECT failed: {exc}"

        # BACKGROUND DISCOVERY
        # ----------------------------------------------------
        match = re.match(
            r"^\s*background\s+(?:discover|inspect)\s+(.+?)\s*$",
            text,
            re.IGNORECASE,
        )

        if match:
            target = match.group(1).strip()

            try:
                result = self.autonomous.android.background_start_package(
                    target
                )

                if result["exit"] == 0:
                    return (
                        "[ANDROID_BACKGROUND_DISCOVERY]\n"
                        "STATUS: SUCCESS\n"
                        f"{result['stdout']}"
                    )

                return (
                    "[ANDROID_BACKGROUND_DISCOVERY]\n"
                    "STATUS: FAILED\n"
                    f"ERROR: {result['stderr'] or result['stdout']}"
                )

            except Exception as exc:
                return (
                    "[ERROR] ANDROID_BACKGROUND_DISCOVERY failed: "
                    f"{exc}"
                )

        # ----------------------------------------------------
        # FORCE STOP
        # ----------------------------------------------------
        match = re.match(
            r"^\s*(?:stop|kill|force\s+stop)\s+"
            r"(?:app|application|package\s+)?(.+?)\s*$",
            text,
            re.IGNORECASE,
        )

        if match:
            target = match.group(1).strip()

            try:
                result = self.autonomous.android.force_stop_package(target)

                if result["exit"] == 0:
                    return (
                        "[ANDROID_FORCE_STOP]\n"
                        "STATUS: SUCCESS\n"
                        f"APP: {target}\n"
                        f"{result['stdout']}"
                    )

                return (
                    "[ANDROID_FORCE_STOP]\n"
                    "STATUS: FAILED\n"
                    f"APP: {target}\n"
                    f"ERROR: {result['stderr'] or result['stdout']}"
                )

            except Exception as exc:
                return f"[ERROR] ANDROID_FORCE_STOP failed: {exc}"

        return None

    def _looks_like_osint(self, text):
        """Cheap deterministic OSINT gate.

        Prevents the expensive LLM-based OSINT classifier from
        running on ordinary conversational requests.
        """
        text = str(text).strip().lower()

        indicators = (
            "ip address",
            "ip lookup",
            "reverse dns",
            "reverse ip",
            "whois",
            "rdap",
            "dns lookup",
            "dns record",
            "subnet",
            "cidr",
            "hostsearch",
            "iplocation",
            "ip location",
            "shodan",
            "cve-",
            "vulnerability lookup",
            "mtr ",
            "network trace",
            "port scan",
        )

        return any(item in text for item in indicators)

    def _looks_like_notification_analysis(self, text):
        """Detect requests that require analyzing notifications."""
        text = str(text).strip().lower()

        analysis_terms = (
            "summarize",
            "summary",
            "analyze",
            "analyse",
            "analysis",
            "important",
            "prioritize",
            "priority",
            "what matters",
            "anything urgent",
            "any urgent",
            "which notifications",
            "organize",
            "group",
            "categorize",
            "categorise",
        )

        notification_terms = (
            "notification",
            "notifications",
            "notif",
            "notifs",
            "get me the status on notifications"
        )

        return (
            any(term in text for term in notification_terms)
            and any(term in text for term in analysis_terms)
        )

    def _looks_like_notification_retrieval(self, text):
        """Detect natural-language requests for the notification list."""
        text = str(text).strip().lower()

        notification_terms = (
            "notification",
            "notifications",
            "notif",
            "notifs",
        )

        retrieval_terms = (
            "show",
            "list",
            "read",
            "check",
            "get",
            "view",
            "see",
            "have",
            "received",
            "what",
            "which",
            "any",
        )

        return (
            any(term in text for term in notification_terms)
            and any(term in text for term in retrieval_terms)
        )

    def _notification_analysis(self, text):
        """Retrieve notifications and produce a concise spoken summary."""

        result = self.notifications.summary()

        if isinstance(result, dict) and "error" in result:
            return f"[ERROR] {result['error']}"

        notifications = result.get("notifications", [])

        if not notifications:
            return "[INFO] No active notifications."

        # Keep the analysis input bounded. Notifications can contain
        # enormous email bodies or app payloads that are inappropriate
        # for speech.
        lines = []

        for item in notifications:
            package = item.get("package") or "unknown app"
            title = item.get("title") or ""
            content = item.get("content") or ""

            title = " ".join(str(title).split())
            content = " ".join(str(content).split())

            if len(title) > 120:
                title = title[:117] + "..."

            if len(content) > 240:
                content = content[:237] + "..."

            lines.append(
                f"APP: {package}\n"
                f"TITLE: {title}\n"
                f"CONTENT: {content}"
            )

        notification_text = "\n\n".join(lines)

        prompt = f"""
Analyze the user's Android notifications.

USER REQUEST:
{text}

NOTIFICATIONS:
{notification_text}

STRICT OUTPUT RULES:
- Produce a SHORT spoken summary.
- Maximum 4 sentences.
- Prefer 2-3 sentences.
- Mention only genuinely important items.
- Group related notifications.
- Ignore repetitive homework, promotional, and low-value alerts unless
  they are specifically relevant to the user's request.
- Do not enumerate every notification.
- Do not read email bodies aloud.
- Do not invent urgency or facts.
- Use only the supplied notifications.
- Write naturally for JARVIS text-to-speech.
- Be respectful toward the user.
""".strip()

        answer = self._fast_agent_request(prompt)

        if answer:
            # Hard safety limit for TTS-friendly notification analysis.
            answer = " ".join(str(answer).split())
            sentences = []
            current = ""

            for part in answer.replace("!", ".").replace("?", ".").split("."):
                part = part.strip()

                if not part:
                    continue

                sentences.append(part)

                if len(sentences) >= 4:
                    break

            if sentences:
                return ". ".join(sentences) + "."

            return answer[:700].strip()

        return (
            f"[WARN] Notification analysis unavailable. "
            f"You have {len(notifications)} active notifications."
        )

    def _respectful_response(self, response, text=""):
        """
        Add a natural respectful acknowledgement to short local responses.

        This is deliberately conservative: JARVIS must not say 'sir' after
        every sentence, but important direct acknowledgements should retain
        the respectful assistant personality even when no LLM was involved.
        """
        if not response:
            return response

        response = str(response).strip()

        if not response:
            return response

        lower = response.lower()

        # Never modify errors, structured tool output, or already respectful
        # responses. Those are handled by their own formatters.
        if (
            lower.startswith("[error]")
            or lower.startswith("[warn]")
            or lower.startswith("[info]")
            or lower.startswith("[whatsapp_")
            or "sir" in lower[:120]
        ):
            return response

        command_words = (
            "open ",
            "launch ",
            "start ",
            "send ",
            "call ",
            "message ",
            "stop ",
            "kill ",
            "close ",
            "check ",
            "show ",
            "read ",
            "get ",
            "find ",
            "search ",
        )

        if str(text).strip().lower().startswith(command_words):
            return "Certainly, sir. " + response

        return response

    def _automation_route(self, text):
        """
        Deterministic natural-language automation commands.

        Returns a response string when handled, otherwise None.
        """

        raw = str(text).strip()
        lower = raw.lower()

        # --------------------------------------------------
        # LIST AUTOMATIONS
        # --------------------------------------------------
        if re.fullmatch(
            r"(?:list|show)\s+(?:my\s+)?"
            r"(?:automations|scheduled\s+(?:tasks|jobs|reminders))",
            raw,
            re.IGNORECASE,
        ):
            items = self.automation.list()

            if not items:
                return "You have no scheduled automations, sir."

            lines = []

            for item in items:
                status = item.get("status", "UNKNOWN")
                aid = item.get("id", "?")
                command = item.get("command", "")
                next_run = item.get("next_run")

                if next_run:
                    when = datetime.fromtimestamp(
                        float(next_run),
                        self.automation.timezone,
                    ).strftime("%Y-%m-%d %H:%M:%S")

                    lines.append(
                        f"{aid} — {status} — {when} — {command}"
                    )
                else:
                    lines.append(
                        f"{aid} — {status} — {command}"
                    )

            return "Scheduled automations:\n" + "\n".join(lines)

        # --------------------------------------------------
        # CANCEL AUTOMATION
        # --------------------------------------------------
        cancel_match = re.fullmatch(
            r"(?:cancel|delete|remove)\s+"
            r"(?:automation|reminder|scheduled\s+task|job)?\s*"
            r"(auto-[a-f0-9]+)",
            raw,
            re.IGNORECASE,
        )

        if cancel_match:
            result = self.automation.cancel(
                cancel_match.group(1)
            )

            if "error" in result:
                return f"[ERROR] {result['error']}"

            return (
                f"Automation {cancel_match.group(1)} "
                f"has been cancelled, sir."
            )

        # Android Clock intent helper shared by all timer/alarm routes.
        def _set_android_clock_intent(action, extras):
            command = ["am", "start", "-a", action]
            for flag, key, value in extras:
                command.extend([flag, key, str(value)])
            try:
                result = self.android._run(
                    " ".join(shlex.quote(part) for part in command),
                    timeout=10,
                )
            except Exception as exc:
                return f"[ERROR] Could not configure Android Clock: {exc}"

            if not isinstance(result, dict) or result.get("exit") != 0:
                detail = (
                    str(result.get("stderr", "")).strip()
                    if isinstance(result, dict) else str(result)
                )
                return (
                    "[ERROR] Android Clock did not confirm the request. "
                    + detail
                )
            return None

        # --------------------------------------------------
        # TIMER — Android Clock only.
        # --------------------------------------------------
        timer_match = re.fullmatch(
            r"(?:set\s+(?:a\s+)?timer\s+for|"
            r"timer\s+for|"
            r"remind\s+me\s+in)\s+"
            r"(\d+(?:\.\d+)?)\s*"
            r"(seconds?|secs?|minutes?|mins?|hours?|hrs?)"
            r"(?:\s+(?:to|that)\s+(.+))?",
            raw,
            re.IGNORECASE,
        )

        if timer_match:
            amount = float(timer_match.group(1))
            unit = timer_match.group(2).lower()
            label = (timer_match.group(3) or "Timer finished").strip()
            if amount <= 0:
                return "[ERROR] Timer duration must be greater than zero."

            if unit.startswith(("second", "sec")):
                seconds = amount
            elif unit.startswith(("minute", "min")):
                seconds = amount * 60
            else:
                seconds = amount * 3600

            length = max(1, int(round(seconds)))
            error = _set_android_clock_intent(
                "android.intent.action.SET_TIMER",
                [
                    ("--ei", "android.intent.extra.alarm.LENGTH", length),
                    ("--es", "android.intent.extra.alarm.MESSAGE", label),
                    ("--ez", "android.intent.extra.alarm.SKIP_UI", "true"),
                ],
            )
            if error:
                return error
            return f"Done, sir. Android Clock was asked to start a {amount:g} {unit} timer: {label}."

        # --------------------------------------------------
        # DELAYED REMINDER — Android Clock countdown timer.
        # --------------------------------------------------
        delayed_reminder_match = re.fullmatch(
            r"remind\s+me\s+about\s+(.+?)\s+after\s+"
            r"(\d+(?:\.\d+)?)\s*"
            r"(seconds?|secs?|minutes?|mins?|hours?|hrs?)",
            raw,
            re.IGNORECASE,
        )
        if delayed_reminder_match:
            label = delayed_reminder_match.group(1).strip()
            amount = float(delayed_reminder_match.group(2))
            unit = delayed_reminder_match.group(3).lower()
            if amount <= 0:
                return "[ERROR] Reminder duration must be greater than zero."

            if unit.startswith(("second", "sec")):
                seconds = amount
            elif unit.startswith(("minute", "min")):
                seconds = amount * 60
            else:
                seconds = amount * 3600

            error = _set_android_clock_intent(
                "android.intent.action.SET_TIMER",
                [
                    ("--ei", "android.intent.extra.alarm.LENGTH",
                     max(1, int(round(seconds)))),
                    ("--es", "android.intent.extra.alarm.MESSAGE",
                     f"Reminder: {label}"),
                    ("--ez", "android.intent.extra.alarm.SKIP_UI", "true"),
                ],
            )
            if error:
                return error
            return f"Done, sir. Android Clock was asked to start a reminder timer for {label} ({amount:g} {unit})."

        # Alarms and clock reminders are handled by the set_alarm tool in fast_agent.py.

        return None

    def _deep_search_route(self, text):
        import re

        match = re.match(
            r"^deep\s+search\s+(.+)$",
            text.strip(),
            re.IGNORECASE,
        )

        if not match:
            return None

        query = match.group(1).strip()

        if not query:
            return "What would you like me to research, sir?"

        # Optional controls:
        #   deep search <query>
        #   deep search <query> pages 10
        #   deep search <query> depth 3
        #   deep search <query> pages 10 depth 3
        pages_match = re.search(
            r"\s+pages?\s+(\d+)\s*$",
            query,
            re.IGNORECASE,
        )
        depth_match = re.search(
            r"\s+depth\s+(\d+)\s*$",
            query,
            re.IGNORECASE,
        )

        pages = 0
        depth = 0

        if pages_match:
            pages = int(pages_match.group(1))
            query = query[:pages_match.start()].strip()

        if depth_match:
            depth = int(depth_match.group(1))
            query = query[:depth_match.start()].strip()

        # Support both controls regardless of their order.
        pages_match = re.search(
            r"\s+pages?\s+(\d+)\s*$",
            query,
            re.IGNORECASE,
        )
        if pages_match:
            pages = int(pages_match.group(1))
            query = query[:pages_match.start()].strip()

        self.deep_search.max_pages = pages
        self.deep_search.max_depth = depth

        return self.deep_search.search(query, limit=8)

    def _search_route(self, text):
        import re

        patterns = [
            r"^search the web for\s+(.+)$",
            r"^search for\s+(.+)$",
            r"^web search\s+(.+)$",
            r"^look up\s+(.+)$",
            r"^search wikipedia for\s+(.+)$",
            # Generic search must follow the more specific patterns.
            r"^search\s+(.+)$",
        ]

        query = None

        for pattern in patterns:
            match = re.match(pattern, text.strip(), re.IGNORECASE)
            if match:
                query = match.group(1).strip()
                break

        if not query:
            return None

        results = self.search_hub.search(query, limit=5)

        if not results:
            return "I couldn't find anything useful for that search, sir."

        # Let Groq turn the search evidence into a short,
        # natural, speakable JARVIS response.
        evidence = []

        for result in results:
            evidence.append(
                f"Source: {result.source}\n"
                f"Title: {result.title}\n"
                f"Snippet: {result.snippet[:500]}\n"
                f"URL: {result.url}"
            )

        prompt = f"""
Summarize these web search results for the user.

Query:
{query}

Search results:
{chr(10).join(evidence)}

Rules:
- Give a concise spoken answer.
- Maximum 3 short sentences.
- Mention only information supported by the results.
- Do not read URLs.
- Do not say "search results" unless useful.
- Do not invent facts.
- If the results are ambiguous, say so briefly.
- Speak naturally, like a personal assistant.
"""

        try:
            summary = self.fast_agent.ask(prompt)
            if summary and str(summary).strip():
                return str(summary).strip()
        except Exception:
            pass

        # Safe fallback if Groq is temporarily unavailable.
        return (
            f"I found {len(results)} relevant results. "
            f"The leading result is {results[0].title}."
        )

    def _scheduled_callback(self, text):
        """Execute a scheduled command and announce its result."""
        result = self.dispatch(text)

        if result:
            try:
                tts.speak(str(result))
            except Exception as exc:
                print(
                    f"[SCHEDULER TTS ERROR] {exc}",
                    flush=True,
                )

        return result

    def set_whatsapp_confirmation_worker(self, worker):
        """Attach the WhatsApp group-confirmation owner."""
        self.whatsapp_confirmation_worker = worker

    def _whatsapp_send(self, to, message):
        """
        Send a WhatsApp message while enforcing the group confirmation gate.

        DMs are sent immediately.
        Groups are always queued for explicit YES/NO confirmation.
        """
        recipient = str(to or "").strip()
        message = str(message or "").strip()

        if not recipient:
            raise ValueError("WhatsApp recipient is required.")

        if not message:
            raise ValueError("WhatsApp message is required.")

        # A literal WhatsApp group JID is already authoritative.
        if recipient.endswith("@g.us"):
            if self.whatsapp_confirmation_worker is None:
                raise RuntimeError(
                    "WhatsApp group confirmation is unavailable."
                )

            return self.whatsapp_confirmation_worker.prepare_explicit_group_message(
                recipient,
                message,
            )

        # A named recipient may actually be a group. Resolve it before
        # allowing the normal DM send path.
        try:
            group = self.autonomous.whatsapp.resolve_group(recipient)
        except Exception:
            group = None

        if group:
            if self.whatsapp_confirmation_worker is None:
                raise RuntimeError(
                    "WhatsApp group confirmation is unavailable."
                )

            return self.whatsapp_confirmation_worker.prepare_explicit_group_message(
                recipient,
                message,
            )

        # Not a group: preserve the existing DM behavior.
        return self.autonomous.whatsapp.send(
            to=recipient,
            message=message,
        )

    def _whatsapp_tool_send(self, to, message):
        """
        Tool entry point used by Groq (FastAgent `whatsapp_send`).

        Returns a JSON-serialisable dict. Group sends are never sent here:
        they are queued for YES/NO confirmation, and `final_reply` carries
        the exact confirmation block the UI/CLI expects.
        """
        recipient = str(to or "").strip()
        text = str(message or "").strip()

        if not recipient:
            return {"ok": False, "error": "WhatsApp recipient is required."}
        if not text:
            return {"ok": False, "error": "WhatsApp message is required."}

        label = recipient
        target = recipient

        # Named recipient may be a group: resolve once, then send by JID.
        if not recipient.endswith("@g.us"):
            try:
                group = self.autonomous.whatsapp.resolve_group(recipient)
            except Exception:
                group = None
            if group and group.get("jid"):
                label = group.get("subject", recipient)
                target = str(group["jid"]).strip()

        try:
            result = self._whatsapp_send(to=target, message=text)
        except Exception as exc:
            return {"ok": False, "error": f"WhatsApp send failed: {exc}"}

        if isinstance(result, dict) and result.get("pending"):
            shown = result.get("message", text)
            return {
                "ok": True,
                "status": "WAITING_FOR_CONFIRMATION",
                "final_reply": (
                    "[WHATSAPP_GROUP_CONFIRMATION]\n"
                    f"GROUP: {label}\n"
                    f"MESSAGE: {shown}\n"
                    "STATUS: WAITING_FOR_CONFIRMATION\n"
                    "TYPE YES TO SEND OR NO TO CANCEL."
                ),
            }

        info = result if isinstance(result, dict) else {}
        return {
            "ok": True,
            "status": "SENT",
            "to": info.get("to") or label,
            "message": text,
            "id": info.get("id") or info.get("key"),
        }

    def dispatch(self, text, conversation=None):
        text = str(text).strip()
        original_text = text

        # Explicit local diagnostics must bypass the AI fallback.
        if re.fullmatch(r"/doctor\s*", text, re.IGNORECASE):
            return self.execute_one("doctor", "")

        # ======================================================
        # DETERMINISTIC AUTOMATION ROUTE
        # Timers, reminders, and scheduled commands must never
        # be sent through Groq/OmniRoute for interpretation.
        # ======================================================
        automation_result = self._automation_route(text)

        if automation_result is not None:
            return automation_result

        # ======================================================
        # DETERMINISTIC ABILITIES ROUTE
        # ======================================================
        # Only explicit ability/capability questions reach this
        # handler. Ordinary requests must never receive the list.
        if self._abilities_request(text):
            return self._format_abilities()

        # ======================================================
        # INSTANT GREETING ROUTE
        # ======================================================

        if re.fullmatch(
            r"(hi|hello|hey|yo|hiya|good morning|good afternoon|good evening|jarvis|jarvis?|Jarvis|Jarvis?|JARVIS|JARVIS?)",
            text,
            re.IGNORECASE,
        ):
            greet = ['System initialized. Awaiting your input.', 'JARVIS online and standing by for commands.', 'I am online and ready to assist you, sir.', 'At your service. What do you require?', 'Connection established. I am ready for your directives.', 'Systems are stable. Please state your command, sir.', 'Ready when you are. Hit me with your next task.', 'Online and fully optimized. Sir, how shall we proceed?', 'Link established. Command me, sir.']
            import random
            
            return random.choice(greet)

        # ======================================================
        # DIRECT PHONE CALL ROUTE
        # ======================================================
        #
        # Examples:
        #   Call Rahul
        #   Call SuyogPawate
        #   Phone Rahul
        #   Please call Rahul
        #   Call Rahul now
        #
        # ContactsManager resolves the Android contact and uses
        # termux-telephony-call for the actual call.
        #

        call_match = re.fullmatch(
            r"(?:please\s+)?"
            r"(?:call|phone)"
            r"\s+"
            r"(.+?)"
            r"(?:\s+now)?",
            text,
            re.IGNORECASE,
        )

        if call_match:
            recipient = call_match.group(1).strip()

            result = self.contacts.call(recipient)

            return result

        # ======================================================
        # WHATSAPP
        # No regex routes here on purpose. Groq handles WhatsApp
        # requests through the `whatsapp_send` tool (FastAgent),
        # which calls _whatsapp_tool_send() (defined above).
        # ======================================================

        # ======================================================
        # ANDROID AI EXPLANATION
        # ======================================================
        fast_explain = self._fast_android_explain(text)

        if fast_explain is not None:
            return fast_explain

        # ======================================================
        # ANDROID HARD ROUTE
        # ======================================================
        fast_android = self._fast_android_control(text)

        if fast_android is not None:
            return fast_android

        # ======================================================
        # NOTIFICATION ROUTES
        # ======================================================
        #
        # Retrieval stays entirely local.
        # Analysis retrieves locally first, then sends the
        # normalized notification data to Groq.
        #
        if self._looks_like_notification_analysis(text):
            return self._notification_analysis(text)

        if self._looks_like_notification_retrieval(text):
            result = self.notifications.summary()

            if isinstance(result, dict) and "error" in result:
                return f"[ERROR] {result['error']}"

            notifications = result.get("notifications", [])

            if not notifications:
                return "[INFO] No active notifications."

            lines = [
                f"[NOTIFICATIONS] {len(notifications)} active"
            ]

            for item in notifications:
                package = item.get("package") or "(unknown)"
                title = item.get("title") or "(no title)"
                content = item.get("content") or "(no content)"
                when = item.get("when") or "(unknown time)"

                lines.append(
                    f"\n[{package}]\n"
                    f"TITLE: {title}\n"
                    f"CONTENT: {content}\n"
                    f"WHEN: {when}"
                )

            return "\n".join(lines)

        # ======================================================
        # LOCAL TOOL RESULT FORMATTER
        # ======================================================

        def _format_local_tool_result(kind, result):
            """Convert raw local tool envelopes into concise UI/TTS text."""

            if result is None:
                return None

            if isinstance(result, str):
                return result.strip()

            if not isinstance(result, dict):
                return str(result)

            if result.get("error"):
                return f"[ERROR] {result['error']}"

            if result.get("exit", 0) != 0:
                error = str(result.get("stderr") or "").strip()
                return f"[ERROR] {error or 'Local tool failed.'}"

            raw = str(result.get("stdout") or "").strip()

            # ------------------------------
            # GENERIC SYSTEM STATUS
            # ------------------------------
            if kind == "status":
                battery = result.get("battery") or {}
                memory = result.get("memory") or {}
                storage = result.get("storage") or {}
                wifi = result.get("wifi") or {}

                def stdout(value):
                    if not isinstance(value, dict):
                        return str(value).strip()
                    if value.get("exit", 0) != 0:
                        return ""
                    return str(value.get("stdout") or "").strip()

                # Battery
                battery_text = stdout(battery)
                battery_summary = "unavailable"

                if battery_text:
                    try:
                        data = json.loads(battery_text)
                        percentage = data.get("percentage", data.get("level"))
                        state = str(data.get("status") or "").strip().lower()
                        plugged = str(data.get("plugged") or "").strip().lower()

                        if percentage is not None:
                            battery_summary = f"{percentage}%"
                            if state:
                                battery_summary += f", {state}"
                            if plugged:
                                battery_summary += f", {plugged}"
                    except Exception:
                        pass

                # Memory
                memory_summary = "unavailable"
                memory_text = stdout(memory)
                for line in memory_text.splitlines():
                    if line.startswith("Mem:"):
                        parts = line.split()
                        if len(parts) >= 7:
                            memory_summary = f"{parts[6]} available"
                        break

                # Storage
                storage_summary = "unavailable"
                storage_text = stdout(storage)
                for line in storage_text.splitlines():
                    if "/data " in line or "/data" in line:
                        parts = line.split()
                        if len(parts) >= 5:
                            storage_summary = f"{parts[3]} available"
                        break

                # Wi-Fi
                wifi_summary = "unavailable"
                wifi_text = stdout(wifi)
                if wifi_text:
                    try:
                        data = json.loads(wifi_text)
                        state = str(data.get("supplicant_state") or "").strip().lower()
                        ssid = str(data.get("ssid") or "").strip()

                        if state == "completed" and ssid and ssid != "<unknown ssid>":
                            wifi_summary = f"connected to {ssid}"
                        else:
                            wifi_summary = "disconnected"
                    except Exception:
                        pass

                return (
                    "System status: "
                    f"battery {battery_summary}; "
                    f"memory {memory_summary}; "
                    f"storage {storage_summary}; "
                    f"Wi-Fi {wifi_summary}."
                )

            # ------------------------------
            # BATTERY
            # ------------------------------
            if kind == "battery":
                try:
                    data = json.loads(raw)

                    percentage = data.get("percentage", data.get("level"))
                    status = str(data.get("status") or "").strip().lower()
                    plugged = str(data.get("plugged") or "").strip().lower()
                    temperature = data.get("temperature")

                    parts = []

                    if percentage is not None:
                        parts.append(f"Battery is at {percentage} percent.")

                    if status:
                        parts.append(f"Status: {status}.")

                    if temperature is not None:
                        parts.append(f"Temperature is {temperature} degrees Celsius.")

                    if plugged and plugged != "unplugged":
                        parts.append(f"Power: {plugged}.")

                    return " ".join(parts)

                except Exception:
                    return raw or "Unable to read battery status."

            # ------------------------------
            # RAM
            # ------------------------------
            if kind == "memory":
                for line in raw.splitlines():
                    line = line.strip()

                    if line.startswith("Mem:"):
                        fields = line.split()

                        # free -h:
                        # Mem: total used free shared buff/cache available
                        if len(fields) >= 7:
                            return (
                                f"You have {fields[6]} of RAM available. "
                                f"{fields[2]} is currently used."
                            )

                return raw or "Unable to read memory status."

            # ------------------------------
            # STORAGE
            # ------------------------------
            if kind == "storage":
                # Prefer the internal /data filesystem rather than
                # tmpfs, vendor, cache, or removable media.
                candidates = []

                for line in raw.splitlines():
                    if not line.strip() or line.startswith("Filesystem"):
                        continue

                    fields = line.split()

                    if len(fields) < 6:
                        continue

                    mount = fields[-1]

                    if mount in (
                        "/data",
                        "/storage/emulated",
                    ):
                        candidates.append(fields)

                if candidates:
                    fields = candidates[0]

                    size = fields[1]
                    available = fields[3]
                    usage = fields[4]

                    return (
                        f"Internal storage has {available} available "
                        f"out of {size}. {usage} is used."
                    )

                return raw or "Unable to read storage status."

            # ------------------------------
            # WIFI
            # ------------------------------
            if kind == "wifi":
                try:
                    data = json.loads(raw)

                    state = str(
                        data.get("supplicant_state") or ""
                    ).strip().upper()

                    ssid = str(
                        data.get("ssid") or ""
                    ).strip()

                    if state in (
                        "DISCONNECTED",
                        "INACTIVE",
                        "UNINITIALIZED",
                    ):
                        return "Wi-Fi is disconnected."

                    if not ssid or ssid == "<unknown ssid>":
                        return "Wi-Fi is connected, but the network name is unavailable."

                    return f"Connected to Wi-Fi network {ssid}."

                except Exception:
                    return raw or "Unable to read Wi-Fi status."

            # ------------------------------
            # PROCESS LIST
            # ------------------------------
            if kind == "processes":
                lines = [
                    line
                    for line in raw.splitlines()
                    if line.strip()
                ]

                if lines:
                    count = max(0, len(lines) - 1)
                    return (
                        f"I found {count} running processes. "
                        f"The detailed process list is available in the console."
                    )

                return "No running processes were found."

            # ------------------------------
            # PROCESS STATUS
            # ------------------------------
            if kind == "process_status":
                running = bool(result.get("running"))

                if running:
                    return "Yes. That process is running."

                return "No. That process is not running."

            # ------------------------------
            # PROCESS FIND
            # ------------------------------
            if kind == "process_find":
                if raw:
                    lines = [
                        line for line in raw.splitlines()
                        if line.strip()
                    ]

                    return (
                        f"I found {len(lines)} matching process"
                        f"{'' if len(lines) == 1 else 'es'}."
                    )

                return "I couldn't find a matching process."

            # ------------------------------
            # FALLBACK
            # ------------------------------
            return raw or "The local tool returned no data."

        # ======================================================
        # LOCAL SYSTEM / DEVICE TOOL ROUTES
        # ======================================================
        # Deterministic local execution for simple device queries.
        # These must stay before OSINT and normal Groq routing.
        #
        # IMPORTANT:
        # Do not use a broad "\\bmemory\\b" match here because
        # /memory is JARVIS persistent-memory functionality.
        # ======================================================

        local_tool_result = None
        local_tool_kind = None

        # BATTERY
        if re.search(
            r"\b(?:battery|battery\s+status|battery\s+level)\b",
            text,
            re.IGNORECASE,
        ):
            local_tool_result = self.system.battery()
            local_tool_kind = "battery"

        # RAM / SYSTEM MEMORY
        elif re.search(
            r"\b(?:ram|system\s+memory|available\s+memory|free\s+memory|"
            r"memory\s+(?:available|usage|used|free))\b",
            text,
            re.IGNORECASE,
        ):
            local_tool_result = self.system.memory()
            local_tool_kind = "memory"

        # STORAGE
        elif re.search(
            r"\b(?:storage|disk\s+space|free\s+storage|"
            r"available\s+storage|storage\s+(?:available|free|usage))\b",
            text,
            re.IGNORECASE,
        ):
            local_tool_result = self.system.storage()
            local_tool_kind = "storage"

        # WIFI
        elif re.search(
            r"\b(?:wifi|wi-fi|wireless)\b",
            text,
            re.IGNORECASE,
        ):
            local_tool_result = self.system.wifi()
            local_tool_kind = "wifi"

        # RUNNING PROCESSES
        elif re.search(
            r"\b(?:running\s+processes|processes\s+running|"
            r"what\s+processes|list\s+processes)\b",
            text,
            re.IGNORECASE,
        ):
            local_tool_result = self.processes.list()
            local_tool_kind = "processes"

        # PROCESS STATUS
        #
        # Recognize both:
        #   is whatsapp_daemon.sh running
        #   check if whatsapp_daemon.sh is running
        #   whatsapp_daemon.sh is running
        #   whatsapp_daemon.sh is already running
        #
        # These are deterministic local checks and MUST NOT fall through
        # to an AI response.

        else:
            process_match = re.search(
                r"\b(?:is|check\s+if|whether)\s+"
                r"([A-Za-z0-9_.:@+/-]+)"
                r"\s+(?:process\s+)?(?:running|active)\b",
                text,
                re.IGNORECASE,
            )

            # Natural form:
            #   whatsapp_daemon.sh is running
            #   whatsapp_daemon.sh is already running
            if not process_match:
                process_match = re.search(
                    r"\b([A-Za-z0-9_.:@+/-]+)"
                    r"\s+is\s+(?:already\s+)?"
                    r"(?:running|active)\b",
                    text,
                    re.IGNORECASE,
                )

            if process_match:
                local_tool_result = self.processes.is_running(
                    process_match.group(1)
                )
                local_tool_kind = "process_status"

        # PROCESS FIND
        if local_tool_result is None:
            process_find = re.search(
                r"\b(?:find|search\s+for|locate)\s+"
                r"(?:the\s+)?process\s+([A-Za-z0-9_.:@+/-]+)\b",
                text,
                re.IGNORECASE,
            )

            if process_find:
                local_tool_result = self.processes.find(
                    process_find.group(1)
                )
                local_tool_kind = "process_find"

        # INSTALLED PACKAGES / APPS
        if local_tool_result is None and re.search(
            r"\b(?:installed\s+(?:apps|applications|packages)|"
            r"what\s+apps\s+are\s+installed|list\s+installed\s+apps)\b",
            text,
            re.IGNORECASE,
        ):
            local_tool_result = self.android.list_packages(
                third_party_only=True
            )

        # LAUNCHER APPS
        if local_tool_result is None and re.search(
            r"\b(?:launcher\s+apps|apps\s+on\s+(?:my\s+)?home\s+screen|"
            r"apps\s+i\s+can\s+open|list\s+launcher\s+apps)\b",
            text,
            re.IGNORECASE,
        ):
            local_tool_result = self.android.list_launcher_apps()

        # FIND ANDROID PACKAGE
        if local_tool_result is None:
            package_match = re.search(
                r"\b(?:find|locate|search\s+for)\s+"
                r"(?:the\s+)?(?:android\s+)?(?:package|app)\s+"
                r"(.+?)\s*$",
                text,
                re.IGNORECASE,
            )

            if package_match:
                target = package_match.group(1).strip()
                if target:
                    local_tool_result = self.android.find_package(target)

        # JOBS
        if local_tool_result is None and re.search(
            r"\b(?:background\s+jobs|running\s+jobs|"
            r"list\s+jobs|what\s+jobs\s+are\s+running)\b",
            text,
            re.IGNORECASE,
        ):
            local_tool_result = self.jobs.list()

        if local_tool_result is not None:
            return _format_local_tool_result(
                local_tool_kind,
                local_tool_result,
            )

        # ======================================================
        # GENERIC SYSTEM STATUS
        # ======================================================
        #
        # Generic status requests must be handled locally.
        # Do not let the conversational agent interpret
        # "status" as a service-specific status request.

        if re.search(
            r"^\s*(?:what(?:'s| is)\s+the\s+status|"
            r"system\s+status|"
            r"jarvis\s+status|"
            r"status\s+check)\s*[?.!]?\s*$",
            text,
            re.IGNORECASE,
        ):
            try:
                result = _format_local_tool_result(
                    "status",
                    {
                        "battery": self.system.battery(),
                        "memory": self.system.memory(),
                        "storage": self.system.storage(),
                        "wifi": self.system.wifi(),
                    },
                )
                return "Certainly, sir. " + result
            except Exception as exc:
                return f"[ERROR] System status check failed: {exc}"

        # ======================================================
        # OSINT GATE
        # ======================================================
        #
        # IMPORTANT:
        # _fast_osint_route() uses Groq internally. Therefore it
        # is only called after this cheap deterministic gate.
        #
        if self._looks_like_osint(text):
            try:
                fast_osint = self.autonomous._fast_osint_route(text)

                if fast_osint:
                    action, value = self.autonomous._parse(fast_osint)

                    if action == "osint":
                        return self.autonomous._execute(
                            action,
                            value,
                        )

            except Exception as exc:
                print(
                    f"[ROUTER WARN] Fast OSINT dispatch failed: {exc}",
                    flush=True,
                )

        # ======================================================
        # NORMAL ROUTING
        # ======================================================
        if not text:
            return ""

        # Groq selects web/deep research through FastAgent tool calling.
        # Legacy route methods remain available as manual fallback helpers.


        commands = self.split_commands(text)

        if not commands:

            # --------------------------------------------------
            # PERSISTENT MEMORY CONTEXT
            # --------------------------------------------------
            # Use the same MemoryManager used by the CLI.
            # This makes HUD conversations persistent instead
            # of relying only on browser localStorage.
            #
            memory_context = ""

            try:
                memory_context = self.memory.build_context(
                    text,
                    max_personal=8,
                    max_project=8,
                    max_episodes=6,
                    max_conversation=10,
                )
            except Exception as exc:
                print(
                    f"[MEMORY WARN] Context retrieval failed: {exc}",
                    flush=True,
                )

            if memory_context:
                text = (
                    "RELEVANT JARVIS MEMORY:\n\n"
                    + str(memory_context)
                    + "\n\nCURRENT USER REQUEST:\n"
                    + text
                )

            # --------------------------------------------------
            # GROQ MAIN AGENT
            # --------------------------------------------------
            # Groq is the primary conversational agent.
            # Existing deterministic routes have already been
            # handled above.
            #
            # Memory and conversation history remain available
            # to the main agent.
            if conversation:
                try:
                    history_lines = []

                    for item in conversation[-20:]:
                        if not isinstance(item, dict):
                            continue

                        role = str(item.get("role", "")).strip().lower()
                        content = str(item.get("content", "")).strip()

                        if role not in {"user", "assistant"}:
                            continue

                        if not content:
                            continue

                        label = "USER" if role == "user" else "JARVIS"
                        history_lines.append(
                            f"{label}: {content}"
                        )

                    if history_lines:
                        text = (
                            "CONVERSATION HISTORY:\n"
                            + "\n".join(history_lines)
                            + "\n\nCURRENT USER REQUEST:\n"
                            + text
                        )

                except Exception:
                    pass

            result = self._groq_simple_request(text)

            if result:
                return result

            return "[ERROR] Groq main agent unavailable."

        return self.dispatch_commands(text)
