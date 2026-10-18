"""
JARVIS WhatsApp manager.

Communicates with the persistent local Baileys bridge.
"""

import json
import re
import subprocess

import requests


class WhatsAppManager:

    def __init__(
        self,
        base_url="http://127.0.0.1:23841",
        timeout=20,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    @staticmethod
    def _normalize_name(value):
        return re.sub(r"\s+", " ", str(value).strip().lower())

    @staticmethod
    def _normalize_number(value):
        return re.sub(r"\D", "", str(value))

    def status(self):
        response = requests.get(
            f"{self.base_url}/status",
            timeout=self.timeout,
        )

        response.raise_for_status()

        return response.json()

    def resolve_contact(self, name):
        """Resolve an exact Android contact name to its phone number."""

        if not name:
            raise ValueError("WhatsApp contact name is required.")

        try:
            completed = subprocess.run(
                ["termux-contact-list"],
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
        except Exception as exc:
            raise RuntimeError(
                f"Contact lookup failed: {exc}"
            ) from exc

        if completed.returncode != 0:
            raise RuntimeError(
                completed.stderr.strip()
                or "termux-contact-list failed."
            )

        try:
            contacts = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                "Invalid contact-list output."
            ) from exc

        target = self._normalize_name(name)

        exact_matches = [
            contact
            for contact in contacts
            if self._normalize_name(contact.get("name", "")) == target
            and self._normalize_number(contact.get("number", ""))
        ]

        if len(exact_matches) == 1:
            return self._normalize_number(
                exact_matches[0]["number"]
            )

        if len(exact_matches) > 1:
            raise ValueError(
                f"Multiple contacts match '{name}'."
            )

        raise ValueError(
            f"No exact contact found for '{name}'."
        )

    def resolve_group(self, name):
        """Resolve an exact WhatsApp group name through the Baileys bridge."""
        if not name:
            raise ValueError("WhatsApp group name is required.")

        response = requests.post(
            f"{self.base_url}/resolve-group",
            json={"name": str(name).strip()},
            timeout=self.timeout,
        )

        response.raise_for_status()
        data = response.json()

        if not data.get("ok"):
            raise RuntimeError(
                data.get("error", "WhatsApp group resolution failed.")
            )

        group = data.get("group") or {}
        jid = group.get("jid")

        if not jid or not str(jid).endswith("@g.us"):
            raise RuntimeError(
                "WhatsApp bridge returned an invalid group JID."
            )

        return group

    def _resolve_recipient(self, to):
        value = str(to).strip()

        # Already a WhatsApp JID.
        if value.endswith("@s.whatsapp.net") or value.endswith("@g.us"):
            return value

        # Direct phone number.
        digits = self._normalize_number(value)

        if len(digits) >= 10:
            return digits

        # Prefer an exact Android contact match for personal DMs.
        # Only fall back to group resolution when no exact contact exists.
        try:
            return self.resolve_contact(value)
        except ValueError as exc:
            if "Multiple contacts match" in str(exc):
                raise

        # If it isn't a contact, try an exact WhatsApp group name.
        # Group sends still pass through the confirmation gate in
        # CommandDispatcher._whatsapp_send().
        group = self.resolve_group(value)
        return str(group["jid"]).strip()

    def get_incoming_messages(self, limit=50):
        """Return unprocessed incoming WhatsApp messages."""
        limit = max(1, min(int(limit), 200))

        response = requests.get(
            f"{self.base_url}/messages",
            params={"limit": limit},
            timeout=self.timeout,
        )

        response.raise_for_status()
        data = response.json()

        if not data.get("ok"):
            raise RuntimeError(
                data.get("error", "WhatsApp message retrieval failed.")
            )

        return data.get("messages", [])

    def acknowledge_messages(self, message_ids):
        """Mark incoming WhatsApp messages as processed."""
        ids = [
            str(message_id).strip()
            for message_id in message_ids
            if str(message_id).strip()
        ]

        if not ids:
            return {
                "acknowledged": 0,
            }

        response = requests.post(
            f"{self.base_url}/messages/ack",
            json={"ids": ids},
            timeout=self.timeout,
        )

        response.raise_for_status()
        data = response.json()

        if not data.get("ok"):
            raise RuntimeError(
                data.get("error", "WhatsApp acknowledgement failed.")
            )

        return data

    def send(self, to, message):
        if not to:
            raise ValueError("WhatsApp recipient is required.")

        if not message:
            raise ValueError("WhatsApp message is required.")

        recipient = self._resolve_recipient(to)

        response = requests.post(
            f"{self.base_url}/send",
            json={
                "to": recipient,
                "message": str(message),
            },
            timeout=self.timeout,
        )

        response.raise_for_status()

        data = response.json()

        if not data.get("ok"):
            raise RuntimeError(
                data.get("error", "WhatsApp bridge error.")
            )

        return data["result"]
