"""
JARVIS WhatsApp manager.

Communicates with the persistent local Baileys bridge.
"""

import base64
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

        # Permit a unique partial display-name match (e.g. "Richie" for
        # "Richie Pawate"), but never guess when more than one contact matches.
        partial_matches = [
            contact
            for contact in contacts
            if target in self._normalize_name(contact.get("name", ""))
            and self._normalize_number(contact.get("number", ""))
        ]
        if len(partial_matches) == 1:
            return self._normalize_number(partial_matches[0]["number"])
        if len(partial_matches) > 1:
            names = ", ".join(
                str(item.get("name", "")) for item in partial_matches[:5]
            )
            raise ValueError(
                f"Multiple contacts partially match '{name}': {names}. "
                "Please specify the full contact name."
            )

        raise ValueError(
            f"No contact found for '{name}'."
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

        # Already a WhatsApp JID (@s.whatsapp.net, @g.us, or @lid).
        if "@" in value:
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
        # CommandDispatcher._whatsapp_send(). Convert bridge/server errors
        # into a useful recipient-resolution message instead of exposing HTTP 500.
        try:
            group = self.resolve_group(value)
            return str(group["jid"]).strip()
        except requests.RequestException as exc:
            raise ValueError(
                f"No matching WhatsApp contact or group was found for '{value}'. "
                "Use the saved contact's full name or provide the phone number."
            ) from exc
        except RuntimeError as exc:
            raise ValueError(
                f"Could not resolve WhatsApp group '{value}': {exc}"
            ) from exc

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

    def get_history(self, chat_jid, limit=12):
        """Recent stored messages (both directions) for one direct chat."""
        response = requests.get(
            f"{self.base_url}/history",
            params={"chat": str(chat_jid), "limit": int(limit)},
            timeout=self.timeout,
        )

        response.raise_for_status()
        data = response.json()

        if not data.get("ok"):
            raise RuntimeError(
                data.get("error", "WhatsApp history retrieval failed.")
            )

        return data.get("messages", [])

    def get_chat_history(self, who, limit=15):
        """
        Recent messages (both directions, oldest first) with a contact.

        `who` can be a contact name, a phone number, or a WhatsApp JID.
        """
        value = str(who or "").strip()
        if not value:
            raise ValueError("A contact name or number is required.")

        chat = ""
        name = ""

        if "@" in value:
            chat = value
        else:
            digits = self._normalize_number(value)
            if len(digits) >= 10:
                chat = digits
            else:
                name = value
                try:
                    chat = self.resolve_contact(value)
                except ValueError as exc:
                    if "Multiple contacts match" in str(exc):
                        raise
                except RuntimeError:
                    pass

        params = {"limit": max(1, min(int(limit), 50))}
        if chat:
            params["chat"] = chat
        if name:
            params["name"] = name

        response = requests.get(
            f"{self.base_url}/history",
            params=params,
            timeout=self.timeout,
        )

        response.raise_for_status()
        data = response.json()

        if not data.get("ok"):
            raise RuntimeError(
                data.get("error", "WhatsApp history retrieval failed.")
            )

        return data.get("messages", [])

    def send_media(
        self,
        to,
        data,
        file_name,
        mimetype="application/octet-stream",
        caption="",
        kind="document",
        gif_playback=False,
    ):
        """Send an image or document (raw bytes) to a direct chat."""
        if not to:
            raise ValueError("WhatsApp recipient is required.")

        if not data:
            raise ValueError("File data is required.")

        response = requests.post(
            f"{self.base_url}/send-media",
            json={
                "to": self._resolve_recipient(to),
                "data_base64": base64.b64encode(data).decode("ascii"),
                "file_name": str(file_name),
                "mimetype": str(mimetype),
                "caption": str(caption or ""),
                "kind": kind if kind in {"image", "video", "audio"} else "document",
                "gif_playback": bool(gif_playback),
            },
            timeout=max(self.timeout, 90),
        )

        response.raise_for_status()
        payload = response.json()

        if not payload.get("ok"):
            raise RuntimeError(
                payload.get("error", "WhatsApp media send failed.")
            )

        return payload["result"]
