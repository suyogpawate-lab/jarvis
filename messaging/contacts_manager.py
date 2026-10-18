import json
import re
import subprocess
from pathlib import Path


class ContactsManager:
    def __init__(self):
        self.contacts_file = Path.home() / "jarvis" / "contacts.json"

    @staticmethod
    def normalize_name(value):
        return re.sub(r"\s+", " ", str(value).strip().lower())

    @staticmethod
    def normalize_number(value):
        return re.sub(r"[^\d+]", "", str(value).strip())

    def sync(self):
        try:
            result = subprocess.run(
                ["termux-contact-list"],
                capture_output=True,
                text=True,
                timeout=20,
            )

            if result.returncode != 0:
                return f"[ERROR] Contact sync failed: {result.stderr.strip()}"

            contacts = json.loads(result.stdout or "[]")

            cleaned = []

            for contact in contacts:
                name = (
                    contact.get("name")
                    or contact.get("display_name")
                    or ""
                ).strip()

                number = (
                    contact.get("number")
                    or contact.get("phone")
                    or ""
                ).strip()

                if not name or not number:
                    continue

                cleaned.append({
                    "name": name,
                    "number": self.normalize_number(number),
                })

            self.contacts_file.write_text(
                json.dumps(cleaned, indent=2, ensure_ascii=False)
            )

            return f"[CONTACTS] Synced {len(cleaned)} contacts."

        except Exception as exc:
            return f"[ERROR] Contact sync failed: {exc}"

    def load(self):
        if not self.contacts_file.exists():
            self.sync()

        try:
            return json.loads(self.contacts_file.read_text())
        except Exception:
            return []

    def find(self, name):
        target = self.normalize_name(name)
        contacts = self.load()

        exact = [
            c for c in contacts
            if self.normalize_name(c["name"]) == target
        ]

        if exact:
            return exact

        partial = [
            c for c in contacts
            if target in self.normalize_name(c["name"])
        ]

        return partial

    def resolve(self, name):
        matches = self.find(name)

        if not matches:
            return None, f"Contact '{name}' was not found."

        if len(matches) > 1:
            names = ", ".join(
                f'{c["name"]} ({c["number"]})'
                for c in matches
            )
            return None, f"Multiple contacts matched: {names}"

        return matches[0]["number"], None

    def call(self, name):
        import time

        resolve_started = time.monotonic()
        number, error = self.resolve(name)
        resolve_elapsed = time.monotonic() - resolve_started

        if error:
            return (
                f"[CALL] {error} "
                f"(contact_resolution={resolve_elapsed:.3f}s)"
            )

        try:
            call_started = time.monotonic()

            result = subprocess.run(
                ["termux-telephony-call", number],
                capture_output=True,
                text=True,
                timeout=15,
            )

            call_elapsed = time.monotonic() - call_started

            if result.returncode != 0:
                stderr = result.stderr.strip()
                stdout = result.stdout.strip()

                details = (
                    f"returncode={result.returncode}, "
                    f"contact_resolution={resolve_elapsed:.3f}s, "
                    f"telephony_command={call_elapsed:.3f}s"
                )

                if stderr:
                    details += f", stderr={stderr}"

                if stdout:
                    details += f", stdout={stdout}"

                return (
                    f"[ERROR] Call failed for {name}: "
                    f"{details}"
                )

            return f"[CALL] Calling {name}."

        except subprocess.TimeoutExpired as exc:
            elapsed = time.monotonic() - call_started

            return (
                f"[ERROR] Call timed out for {name}: "
                f"timeout=15s, "
                f"contact_resolution={resolve_elapsed:.3f}s, "
                f"telephony_command={elapsed:.3f}s"
            )

        except Exception as exc:
            elapsed = time.monotonic() - call_started

            return (
                f"[ERROR] Call failed for {name}: "
                f"contact_resolution={resolve_elapsed:.3f}s, "
                f"telephony_command={elapsed:.3f}s, "
                f"exception={type(exc).__name__}: {exc}"
            )
