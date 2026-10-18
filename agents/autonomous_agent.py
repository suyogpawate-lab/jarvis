from workers.registry import build_worker_registry
"""
JARVIS autonomous execution loop.
"""

import re

from agents.fast_agent import FastAgent
from monitoring.notification_ingestor import NotificationIngestor
from messaging.email_manager import EmailManager
from messaging.whatsapp_manager import WhatsAppManager
from osint.core.registry import build_osint_team
from osint.core.formatter import OSINTFormatter


class AutonomousAgent:

    MAX_STEPS = 8

    def __init__(
        self,
        jarvis,
        shell,
        system=None,
        processes=None,
        android=None,
        jobs=None,
        fast_agent=None,
    ):
        self.jarvis = jarvis
        self.shell = shell
        self.system = system
        self.processes = processes
        self.android = android
        self.jobs = jobs
        self.notifications = NotificationIngestor()
        self.email = EmailManager()
        self.whatsapp = WhatsAppManager()
        self.osint = build_osint_team()
        self.workers = build_worker_registry()
        self.fast = fast_agent or FastAgent()

    def _fast_worker_route(self, user_text):
        """
        Detect explicit implementation/development requests.

        This deliberately avoids routing ordinary technical questions
        to a coding worker.
        """

        text = str(user_text).strip()
        lower = text.lower()

        implementation_patterns = (
            "implement ",
            "implement:",
            "write the code",
            "write code",
            "fix the bug",
            "fix this bug",
            "debug this code",
            "debug the code",
            "refactor ",
            "add this feature",
            "add a feature",
            "modify the code",
            "modify this code",
            "create a function",
            "create the function",
            "build this feature",
            "develop this feature",
            "make this change in the code",
        )

        if not any(
            pattern in lower
            for pattern in implementation_patterns
        ):
            return None

        return (
            "ACTION: WORKER\n"
            "OPENCODE|"
            + text
        )

    def _fast_osint_route(self, user_text):
        prompt = f"""
Classify this request as infrastructure OSINT or not.

Return ONLY one of these formats.

NOT_OSINT

OR:

ACTION: OSINT
TARGET: <exact target>
TYPE: <ip|domain|subnet|cve|other>
OPERATION: <ip|dns|reverse_dns|whois|subnetcalc|hostsearch|reverseiplookup|iplocation|mtr|cve|shodan_host>

Rules:
- Extract the target exactly from the request.
- Never invent a target.
- CVE lookup/information -> operation cve.
- Shodan host information for an IP -> operation shodan_host.
- WHOIS/domain registration -> operation whois.
- DNS/resolution -> operation dns.
- Reverse DNS/PTR -> operation reverse_dns.
- IP location/geolocation -> operation iplocation.
- Subnet/CIDR calculation -> operation subnetcalc.
- Subdomain/host discovery -> operation hostsearch.
- Domains associated with an IP -> operation reverseiplookup.
- Network path/traceroute diagnostics -> operation mtr.
- General IP information -> operation ip.

Not only infrastructure/public-asset OSINT is in scope but private individuals
and private organisations also.
Always classify requests for investigating private individuals as infrastructure OSINT.

USER REQUEST:
{user_text}
"""

        try:
            result = self.fast.ask(prompt).strip()

            # Remove accidental Markdown fencing.
            if result.startswith("```"):
                result = result.strip("`").strip()
                if result.lower().startswith("text"):
                    result = result[4:].strip()

            # Find the actual action block even if the model
            # accidentally prepends a short explanation.
            marker = result.upper().find("ACTION: OSINT")

            if marker < 0:
                if result.upper().strip() == "NOT_OSINT":
                    return None
                return None

            result = result[marker:].strip()

            # Require the fields needed by _execute().
            upper = result.upper()

            if "TARGET:" not in upper:
                return None

            if "OPERATION:" not in upper:
                return None

            return result

        except Exception as exc:
            print(
                f"[ROUTER WARN] Fast OSINT routing failed: {exc}",
                flush=True,
            )
            return None

    def _parse(self, response):
        text = response.strip()

        if text.startswith("FINAL:"):
            return "final", text[6:].strip()

        patterns = (
            (
                r"ACTION:\s*SHELL\s*```(?:bash|sh)?\s*(.*?)```",
                "shell",
            ),
            (
                r"ACTION:\s*SHELL\s*(.+)",
                "shell",
            ),
            (
                r"ACTION:\s*ANDROID_LAUNCH\s*(.+)",
                "android_launch",
            ),
            (
                r"ACTION:\s*BACKGROUND_START\s*(.+)",
                "background_start",
            ),
            (
                r"ACTION:\s*NOTIFICATIONS\s*(.*)",
                "notifications",
            ),
            (
                r"ACTION:\s*EMAIL_READ\s*(.*)",
                "email_read",
            ),
            (
                r"ACTION:\s*EMAIL_SEARCH\s*(.*)",
                "email_search",
            ),
            (
                r"ACTION:\s*EMAIL_SEND\s*([\s\S]+)",
                "email_send",
            ),
            (
                r"ACTION:\s*OSINT\s*([\s\S]+)",
                "osint",
            ),
            (
                r"ACTION:\s*WHATSAPP_STATUS\s*(.*)",
                "whatsapp_status",
            ),
            (
                r"ACTION:\s*WHATSAPP_SEND\s*([\s\S]+)",
                "whatsapp_send",
            ),
            (
                r"ACTION:\s*WORKER\s*([\s\S]+)",
                "worker",
            ),
            (
                r"ACTION:\s*```(?:bash|sh)?\s*(.*?)```",
                "shell",
            ),
            (
                r"ACTION:\s*(.+)",
                "shell",
            ),
        )

        for pattern, action in patterns:
            match = re.search(
                pattern,
                text,
                re.IGNORECASE | re.DOTALL,
            )

            if match:
                return action, match.group(1).strip()

        return "final", text

    def _capabilities(self):
        return """
AVAILABLE CAPABILITIES

SHELL
Execute one Bash command at a time.

ANDROID_LAUNCH
Launch an installed Android application.
Input: package name.

BACKGROUND_START
Start a Bash command as a persistent background job.
Returns a JARVIS job ID and PID.

NOTIFICATIONS
Read currently active Android notifications.
Returns normalized notification data.

EMAIL_READ
Read recent emails.
Optional input: account email.
If no account is specified, use the default Gmail account.

EMAIL_SEARCH
Search emails by text.
Format:
<query>
Optional account can be specified separately by the agent.

OSINT
Investigate a user-provided target using the configured
OSINT team.

Infer the appropriate OSINT operation from the user's
request.

Format:
TARGET: <target>
TYPE: <optional target type>
OPERATION: <operation>

Supported operations:
- ip
  Use for IP information, geolocation, organization,
  hostname, and anycast information.

- dns
  Use for resolving a domain/hostname to IP addresses.

- reverse_dns
  Use when the user asks for reverse DNS, hostname
  resolution from an IP, or PTR-style lookup.

Examples:

User asks:
"What is the IP information for 8.8.8.8?"

Use:
ACTION: OSINT
TARGET: 8.8.8.8
TYPE: ip
OPERATION: ip

User asks:
"Resolve example.com"

Use:
ACTION: OSINT
TARGET: example.com
TYPE: domain
OPERATION: dns

User asks:
"Find the hostname for 8.8.8.8"

Use:
ACTION: OSINT
TARGET: 8.8.8.8
TYPE: ip
OPERATION: reverse_dns

Always provide TARGET.
Always choose an operation when the user's request
clearly specifies one.

WHATSAPP_STATUS
Check whether the persistent WhatsApp bridge is connected.

WHATSAPP_SEND
Send one WhatsApp text message through the persistent
Baileys session.

IMPORTANT:
- Use the persistent Baileys bridge.
- Do NOT launch the WhatsApp Android application.
- Do NOT use ACTION_SEND.
- Do NOT use an Android intent.
- Do NOT use am start.
- Do NOT prefill a WhatsApp compose screen.

Format:
TO: <phone number>
MESSAGE:
<message>

EMAIL_SEND
Send an email.
Format:
TO: <recipient>
SUBJECT: <subject>
BODY:
<body>
Optional:
ACCOUNT: <sender account>
If no account is specified, use the default Gmail account.

SYSTEM INSPECTION
- memory
- storage
- processes
- battery
- Wi-Fi
- system overview

PROCESS INSPECTION
- list processes
- find processes
- check whether a process is running
- inspect a PID
- verify a PID

PROCESS CONTROL
- stop a specific PID
- stopping a process must be followed by verification
"""

    def _resolve_whatsapp_recipient(self, recipient):
        recipient = str(recipient).strip()

        # Already a phone/JID.
        if "@" in recipient:
            return recipient

        digits = re.sub(r"\D", "", recipient)

        if len(digits) >= 8:
            return digits

        # Contact-name resolution.
        resolver = getattr(
            self.android,
            "find_contact",
            None,
        )

        if resolver is None:
            raise RuntimeError(
                "Contact resolver is unavailable."
            )

        result = resolver(recipient)

        if result.get("exit") != 0:
            raise RuntimeError(
                result.get(
                    "stderr",
                    f"Could not resolve WhatsApp contact: {recipient}",
                )
            )

        number = result.get("stdout", "").strip()

        if not number:
            raise RuntimeError(
                f"Contact resolved without a phone number: {recipient}"
            )

        return re.sub(r"\D", "", number)

    def _hard_whatsapp_route(self, text):
        """Deterministic WhatsApp route with support for multi-word groups."""
        raw = str(text or "").strip()

        if not re.match(r"^(?:wa|whatsapp)\b", raw, re.IGNORECASE):
            return None

        body = re.sub(
            r"^(?:wa|whatsapp)\s+",
            "",
            raw,
            count=1,
            flags=re.IGNORECASE,
        ).strip()

        if not body:
            return "Please provide a WhatsApp recipient and message."

        # Allow both:
        #   wa Bonnet Kitchen ...
        #   wa send Bonnet Kitchen ...
        body = re.sub(
            r"^send\s+",
            "",
            body,
            count=1,
            flags=re.IGNORECASE,
        ).strip()

        if not body:
            return "Please provide a WhatsApp recipient and message."

        # Prefer the longest matching WhatsApp group name.
        # This allows commands such as:
        #   wa Pawate Family thanking everyone's wishes for my birthday
        words = body.split()

        for i in range(len(words), 0, -1):
            candidate = " ".join(words[:i]).strip()
            message = " ".join(words[i:]).strip()

            if not message:
                continue

            try:
                group = self.whatsapp.resolve_group(candidate)
            except Exception:
                continue

            jid = group["jid"]

            try:
                self.whatsapp.send(
                    to=jid,
                    message=message,
                )
            except Exception as exc:
                return f"WhatsApp message could not be sent: {exc}"

            return f"Message sent to WhatsApp group {group['subject']}."

        # No group matched. Fall back to the existing contact/number logic.
        parts = body.split(None, 1)

        if len(parts) < 2:
            return "Please provide a WhatsApp recipient and message."

        recipient, message = parts

        try:
            self.whatsapp.send(
                to=recipient,
                message=message,
            )
        except Exception as exc:
            return f"WhatsApp message could not be sent: {exc}"

        return "WhatsApp message sent."

    def _execute(self, action, value):
        if action == "worker":
            return self._execute_worker(value)


        if action == "shell":
            return self.shell.execute(value)

        if action == "android_launch":

            if not self.android:
                return (
                    "[ERROR] Android capability unavailable."
                )

            package = value.strip()

            # Friendly names/aliases are resolved by AndroidTools.resolve_app().

            result = self.android.launch_package(
                package
            )

            return (
                f"[ANDROID_LAUNCH] {package}\n"
                f"[EXIT] {result['exit']}\n"
                f"[STDOUT]\n"
                f"{result['stdout']}\n"
                f"[STDERR]\n"
                f"{result['stderr']}"
            )

        if action == "background_start":

            if not self.jobs:
                return (
                    "[ERROR] Background job capability unavailable."
                )

            result = self.jobs.start(value)

            if "error" in result:
                return (
                    f"[ERROR] {result['error']}"
                )

            return (
                "[BACKGROUND_START]\n"
                f"ID: {result['id']}\n"
                f"PID: {result['pid']}\n"
                f"STATUS: {result['status']}\n"
                f"COMMAND: {result['command']}"
            )

        if action == "notifications":

            result = self.notifications.summary()

            if isinstance(result, dict) and "error" in result:
                return (
                    f"[ERROR] {result['error']}"
                )

            notifications = result["notifications"]

            return (
                "[NOTIFICATIONS]\n"
                f"COUNT: {len(notifications)}\n"
                f"{notifications}"
            )

        if action == "email_read":

            account = value.strip() or None

            try:
                messages = self.email.list_recent(
                    requested_account=account,
                    limit=10,
                )

                return (
                    "[EMAIL_READ]\n"
                    f"ACCOUNT: {messages[0]['account'] if messages else account or 'default'}\n"
                    f"COUNT: {len(messages)}\n"
                    f"{messages}"
                )

            except Exception as exc:
                return f"[ERROR] EMAIL_READ failed: {exc}"

        if action == "email_search":

            query = value.strip()

            if not query:
                return "[ERROR] EMAIL_SEARCH requires a query."

            try:
                messages = self.email.search(
                    query,
                    limit=20,
                )

                return (
                    "[EMAIL_SEARCH]\n"
                    f"QUERY: {query}\n"
                    f"COUNT: {len(messages)}\n"
                    f"{messages}"
                )

            except Exception as exc:
                return f"[ERROR] EMAIL_SEARCH failed: {exc}"

        if action == "whatsapp_status":

            try:
                result = self.whatsapp.status()

                return (
                    "[WHATSAPP_STATUS]\n"
                    f"CONNECTED: {result.get('connected', False)}"
                )

            except Exception as exc:
                return (
                    f"[ERROR] WHATSAPP_STATUS failed: {exc}"
                )

        if action == "whatsapp_send":

            lines = value.strip().splitlines()

            to = None
            message_lines = []
            in_message = False

            for line in lines:

                stripped = line.strip()

                if stripped.upper().startswith("TO:"):
                    to = stripped[3:].strip()
                    in_message = False
                    continue

                if stripped.upper() == "MESSAGE:":
                    in_message = True
                    continue

                if in_message:
                    message_lines.append(line)

            message = "\n".join(
                message_lines
            ).strip()

            if not to:
                return (
                    "[ERROR] WHATSAPP_SEND requires TO."
                )

            if not message:
                return (
                    "[ERROR] WHATSAPP_SEND requires MESSAGE."
                )

            try:
                result = self.whatsapp.send(
                    to=to,
                    message=message,
                )

                return (
                    "[WHATSAPP_SEND]\n"
                    f"STATUS: {result.get('status')}\n"
                    f"TO: {result.get('to')}\n"
                    f"ID: {result.get('id')}"
                )

            except Exception as exc:
                return (
                    f"[ERROR] WHATSAPP_SEND failed: {exc}"
                )

        if action == "osint":

            target = ""
            target_type = None
            operation = None

            for line in str(value).splitlines():
                line = line.strip()

                if line.upper().startswith("TARGET:"):
                    target = line.split(":", 1)[1].strip()

                elif line.upper().startswith("TYPE:"):
                    target_type = (
                        line.split(":", 1)[1].strip()
                        or None
                    )

                elif line.upper().startswith("OPERATION:"):
                    operation = (
                        line.split(":", 1)[1].strip()
                        or None
                    )

            if not target:
                return "[ERROR] OSINT requires TARGET."

            if operation:
                operation = operation.lower()

                allowed_operations = {
                    "ip",
                    "dns",
                    "reverse_dns",
                    "whois",
                    "subnetcalc",
                    "hostsearch",
                    "reverseiplookup",
                    "iplocation",
                    "mtr",
                    "cve",
                    "shodan_host",
                }

                if operation not in allowed_operations:
                    return (
                        "[ERROR] Unsupported OSINT operation: "
                        f"{operation}"
                    )

            try:
                result = self.osint.investigate(
                    target,
                    target_type=target_type,
                    operation=operation,
                )

                return OSINTFormatter.format(result)

            except Exception as exc:
                return f"[ERROR] OSINT failed: {exc}"

        if action == "email_send":

            lines = value.strip().splitlines()

            to = None
            subject = None
            account = None
            body_lines = []
            in_body = False

            for line in lines:

                stripped = line.strip()

                if stripped.upper().startswith("TO:"):
                    to = stripped[3:].strip()
                    in_body = False
                    continue

                if stripped.upper().startswith("SUBJECT:"):
                    subject = stripped[8:].strip()
                    in_body = False
                    continue

                if stripped.upper().startswith("ACCOUNT:"):
                    account = stripped[8:].strip()
                    in_body = False
                    continue

                if stripped.upper() == "BODY:":
                    in_body = True
                    continue

                if in_body:
                    body_lines.append(line)

            if not to:
                return "[ERROR] EMAIL_SEND requires TO."

            if subject is None:
                return "[ERROR] EMAIL_SEND requires SUBJECT."

            body = "\n".join(body_lines).strip()

            if not body:
                return "[ERROR] EMAIL_SEND requires BODY."

            try:
                result = self.email.send(
                    to=to,
                    subject=subject,
                    body=body,
                    requested_account=account,
                )

                return (
                    "[EMAIL_SEND]\n"
                    f"STATUS: {result['status']}\n"
                    f"FROM: {result['from']}\n"
                    f"TO: {result['to']}\n"
                    f"SUBJECT: {result['subject']}"
                )

            except Exception as exc:
                return f"[ERROR] EMAIL_SEND failed: {exc}"

        return (
            f"[ERROR] Unknown action: {action}"
        )

    def _execute_worker(self, value):
        """
        Delegate bounded implementation work to OpenCode.

        Format:
            OPENCODE|task
        """

        value = str(value).strip()

        if "|" not in value:
            raise ValueError(
                "WORKER action requires WORKER|task"
            )

        worker_name, task = value.split("|", 1)
        worker_name = worker_name.strip().lower()
        task = task.strip()

        if not task:
            raise ValueError(
                "Worker task is empty"
            )

        workspace = str(
            __import__("pathlib").Path.cwd()
        )

        worker = self.workers.get(worker_name)

        if worker is None:
            raise ValueError(
                f"Unknown worker: {worker_name}"
            )

        if not worker.available():
            raise RuntimeError(
                f"Worker unavailable: {worker_name}"
            )

        result = worker.execute(
            task=task,
            workspace=workspace,
        )

        print(
            f"[WORKER] {worker_name}: "
            f"{'SUCCESS' if result.get('success') else 'FAILED'}",
            flush=True,
        )

        output = result.get("stdout") or ""
        if output:
            print(output, end="", flush=True)

        return result

    def run(self, request):

        request = str(request).strip()

        # ======================================================
        # HARD WHATSAPP ROUTE
        # ======================================================
        # Never allow the AI execution planner to reinterpret
        # an explicit 'wa' command as an Android launch action.
        hard_whatsapp = self._hard_whatsapp_route(request)

        if hard_whatsapp is not None:
            return hard_whatsapp

        # ======================================================
        # FAST OSINT ROUTE
        # ======================================================
        # Groq handles OSINT intent/action extraction first.
        # If it is not OSINT, the normal OmniRoute agent remains
        # responsible for the request.
        fast_osint = self._fast_osint_route(request)
        fast_worker = self._fast_worker_route(request)
        if fast_worker:
            action, value = self._parse(fast_worker)
            if action == "worker":
                return self._execute(action, value)


        if fast_osint:
            action, value = self._parse(fast_osint)

            if action == "osint":
                result = self._execute(
                    action,
                    value,
                )

                return result

        # ======================================================
        # NORMAL AUTONOMOUS ROUTE
        # ======================================================

        prompt = f"""
You are JARVIS operating on a Termux Android system.

The user's request has already passed through the JARVIS
command dispatcher.

Do not output an abilities list unless the user explicitly
asks about JARVIS abilities or capabilities.

USER REQUEST:
{request}

You are an autonomous execution agent.

Choose exactly ONE action at a time.

For shell execution:

ACTION: SHELL
<one bash command>

For Android application launching:

ACTION: ANDROID_LAUNCH
<package name>

For background execution:

ACTION: BACKGROUND_START
<one bash command>

For notification inspection:

ACTION: NOTIFICATIONS

For reading recent email:

ACTION: EMAIL_READ
<optional account email>

For searching email:

ACTION: EMAIL_SEARCH
<search query>

For sending email:

ACTION: EMAIL_SEND
TO: <recipient>
SUBJECT: <subject>
BODY:
<body>
ACCOUNT: <optional sender account>

For OSINT:

ACTION: OSINT
TARGET: <target>
TYPE: <optional target type>
OPERATION: <operation>

When the user's request is completely satisfied:

FINAL:
<concise factual answer>

RULES:
- Treat the user with the utmost respect and courtesy.
- Remain calm, professional, attentive, and composed.
- Address the user respectfully and naturally.
- Use "sir" when appropriate, but never mechanically after every sentence.
- Never be rude, dismissive, sarcastic, condescending, or argumentative.
- Acknowledge user corrections respectfully.
- One action at a time.
- Never claim execution without actual execution output.
- Use the most appropriate native capability.
- Never replace a deterministic capability with an Android intent when a
  native JARVIS capability already exists.
- Never invent process IDs, system state, or command results.
- After every action, inspect the actual result.
- If an action fails, diagnose the actual error and correct it.
- Verify state-changing operations.
"""

        history = []

        for step in range(
            1,
            self.MAX_STEPS + 1,
        ):

            response = self.jarvis.ask(prompt)

            action, value = self._parse(response)

            if action == "final":
                return value

            history.append({
                "step": step,
                "action": action,
                "value": value,
            })

            result = self._execute(
                action,
                value,
            )

            history[-1]["result"] = result

            prompt = f"""
JARVIS EXECUTION STEP {step}

Original request:
{request}

Action:
{action}

Value:
{value}

ACTUAL RESULT:
{result}

Execution history:
{history}

Continue from the actual result.

If completely satisfied:

FINAL:
<concise factual answer>

Otherwise choose exactly ONE next action.
"""

        return (
            "[ERROR] Maximum autonomous execution steps "
            "reached without completing the request."
        )
