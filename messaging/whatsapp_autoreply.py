"""
JARVIS autonomous WhatsApp reply worker.

Consumes incoming messages from the local Baileys bridge,
generates replies through FastAgent/Groq, sends them, and
acknowledges messages only after a successful send.
"""

import json
import queue
import threading
import time
from pathlib import Path

from agents.fast_agent import FastAgent
from messaging.whatsapp_manager import WhatsAppManager


class WhatsAppAutoReplyWorker:
    def __init__(
        self,
        poll_interval=2.0,
        queue_limit=50,
        context_limit=12,
    ):
        self.poll_interval = float(poll_interval)
        self.queue_limit = max(1, min(int(queue_limit), 200))
        self.context_limit = max(1, min(int(context_limit), 50))

        self.whatsapp = WhatsAppManager()
        self.fast_agent = FastAgent()

        self.root = Path(__file__).resolve().parent
        self.data_dir = self.root.parent / "data" / "whatsapp_autoreply"
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.context_file = self.data_dir / "conversation_context.json"
        self.handled_file = self.data_dir / "handled_message_ids.json"
        self.pending_file = self.data_dir / "pending_group_replies.json"

        self._stop_event = threading.Event()
        self._thread = None
        self._lock = threading.Lock()

        self.context = self._load_json(
            self.context_file,
            {},
        )

        self.handled_ids = set(
            self._load_json(
                self.handled_file,
                [],
            )
        )

        self.pending_group_replies = self._load_json(
            self.pending_file,
            {},
        )

        # Background worker events are consumed by the main JARVIS
        # thread. The worker must never print while input() is active.
        self._events = queue.Queue()

        # Re-surface confirmations that survived a JARVIS restart.
        for pending in self.pending_group_replies.values():
            self._events.put({
                "type": "GROUP_CONFIRMATION",
                **pending,
            })

    @staticmethod
    def _load_json(path, default):
        try:
            if not path.exists():
                return default

            with open(path, "r", encoding="utf-8") as handle:
                value = json.load(handle)

            return value

        except Exception:
            return default

    @staticmethod
    def _save_json(path, value):
        temporary = path.with_suffix(path.suffix + ".tmp")

        with open(
            temporary,
            "w",
            encoding="utf-8",
        ) as handle:
            json.dump(
                value,
                handle,
                ensure_ascii=False,
                indent=2,
            )

        temporary.replace(path)

    def _save_state(self):
        self._save_json(
            self.context_file,
            self.context,
        )

        self._save_json(
            self.handled_file,
            sorted(self.handled_ids),
        )

        self._save_json(
            self.pending_file,
            self.pending_group_replies,
        )

    @staticmethod
    def _chat_key(message):
        return str(
            message.get("chatJid")
            or ""
        ).strip()

    @staticmethod
    def _message_id(message):
        return str(
            message.get("id")
            or ""
        ).strip()

    @staticmethod
    def _sender_name(message):
        return str(
            message.get("pushName")
            or message.get("senderJid")
            or "Unknown contact"
        ).strip()

    @staticmethod
    def _message_text(message):
        return str(
            message.get("text")
            or ""
        ).strip()

    def _remember(self, chat_jid, role, sender, text):
        if not chat_jid or not text:
            return

        history = self.context.setdefault(
            chat_jid,
            [],
        )

        history.append(
            {
                "role": role,
                "sender": sender,
                "text": text,
                "timestamp": int(
                    time.time()
                ),
            }
        )

        del history[:-self.context_limit]

    def _format_context(self, chat_jid):
        history = self.context.get(
            chat_jid,
            [],
        )

        if not history:
            return "(No previous conversation context.)"

        lines = []

        for item in history:
            sender = item.get(
                "sender",
                "Unknown",
            )

            text = item.get(
                "text",
                "",
            )

            role = item.get(
                "role",
                "incoming",
            )

            if role == "outgoing":
                label = "JARVIS"
            else:
                label = sender

            lines.append(
                f"{label}: {text}"
            )

        return "\n".join(lines)

    def drain_events(self):
        """Return queued UI events without printing from the worker thread."""
        events = []

        while True:
            try:
                events.append(self._events.get_nowait())
            except queue.Empty:
                break

        return events

    def prepare_explicit_group_message(self, recipient, message):
        """Queue an explicitly requested WhatsApp group message for confirmation."""
        recipient = str(recipient or "").strip()
        message = str(message or "").strip()

        if not recipient:
            raise ValueError("WhatsApp group recipient is required.")

        if not message:
            raise ValueError("WhatsApp group message is required.")

        # If the caller already resolved the group, the @g.us JID
        # is authoritative. Do not resolve it again by name.
        if recipient.endswith("@g.us"):
            chat_jid = recipient
            subject = recipient
        else:
            group = self.whatsapp.resolve_group(recipient)

            chat_jid = str(group.get("jid", "")).strip()
            subject = str(group.get("subject", recipient)).strip()

            if not chat_jid.endswith("@g.us"):
                raise RuntimeError(
                    "Resolved WhatsApp destination is not a group."
                )

        # Explicit outgoing group commands do not have an incoming
        # message ID, so create a local pending ID.
        message_id = f"explicit-group-{time.time_ns()}"

        pending = {
            "message_id": message_id,
            "chat_jid": chat_jid,
            "sender": "JARVIS",
            "text": message,
            "suggested_reply": message,
            "timestamp": int(time.time()),
            "created_at": int(time.time()),
        }

        self.pending_group_replies[message_id] = pending
        self._save_state()

        self._events.put({
            "type": "GROUP_CONFIRMATION",
            **pending,
            "explicit_command": True,
            "group_subject": subject,
        })

        return {
            "pending": True,
            "to": chat_jid,
            "subject": subject,
            "message": message,
            "id": message_id,
        }

    def confirm_latest_group_reply(self, approved):
        """Approve or reject the newest pending group reply."""
        if not self.pending_group_replies:
            return "There are no pending WhatsApp group replies, sir."

        pending = max(
            self.pending_group_replies.values(),
            key=lambda item: float(item.get("created_at", 0)),
        )

        message_id = str(
            pending.get("message_id", "")
        ).strip()

        sender = str(
            pending.get("sender", "Unknown")
        ).strip()

        chat_jid = str(
            pending.get("chat_jid", "")
        ).strip()

        suggested_reply = str(
            pending.get("suggested_reply", "")
        ).strip()

        if not approved:
            self.pending_group_replies.pop(
                message_id,
                None,
            )
            self._save_state()

            return (
                f"Understood, sir. "
                f"I discarded the pending reply to {sender}."
            )

        if not suggested_reply:
            return (
                "I cannot send that group reply yet, sir, "
                "because no reply draft is available."
            )

        # Safety gate: confirmation is required, and this method
        # only accepts a stored group JID.
        if not chat_jid.endswith("@g.us"):
            return (
                "I refused to send that reply, sir, "
                "because the pending destination is not a WhatsApp group."
            )

        try:
            self.whatsapp.send(
                chat_jid,
                suggested_reply,
            )
        except Exception as exc:
            return (
                f"I could not send the group reply, sir: {exc}"
            )

        self.pending_group_replies.pop(
            message_id,
            None,
        )

        self._save_state()

        return (
            f"Sent the approved WhatsApp group reply "
            f"to {sender}, sir."
        )

    def _process_message(self, message):
        message_id = self._message_id(message)
        chat_jid = self._chat_key(message)
        text = self._message_text(message)
        sender = self._sender_name(message)

        if not message_id or not chat_jid or not text:
            return False

        if message_id in self.handled_ids:
            return False

        # The bridge already filters fromMe messages, but keep this
        # guard here as a second layer.
        if message.get("fromMe"):
            self.handled_ids.add(message_id)
            self._save_state()
            return False

        # Group messages NEVER receive an autonomous reply.
        # Generate a draft, store it, and ask the main JARVIS
        # thread for explicit confirmation.
        if chat_jid.endswith("@g.us"):
            context = self._format_context(chat_jid)

            try:
                suggested_reply = (
                    self.fast_agent.generate_whatsapp_reply(
                        sender=sender,
                        conversation=context,
                        incoming_message=text,
                    )
                )
            except Exception as exc:
                suggested_reply = ""

                print(
                    f"[WHATSAPP AUTO] Could not generate "
                    f"group draft: {exc}",
                    flush=True,
                )

            pending = {
                "message_id": message_id,
                "chat_jid": chat_jid,
                "sender": sender,
                "text": text,
                "suggested_reply": suggested_reply,
                "timestamp": message.get("timestamp"),
                "created_at": int(time.time()),
            }

            self.pending_group_replies[
                message_id
            ] = pending

            self.handled_ids.add(
                message_id
            )

            self._save_state()

            self.whatsapp.acknowledge_messages(
                [message_id]
            )

            self._events.put({
                "type": "GROUP_CONFIRMATION",
                **pending,
            })

            return False

        conversation = self._format_context(
            chat_jid
        )

        # Remember the incoming message before generation so that
        # the generated reply sees the current message in context.
        self._remember(
            chat_jid,
            "incoming",
            sender,
            text,
        )

        conversation = self._format_context(
            chat_jid
        )

        print(
            f"[WHATSAPP AUTO] Incoming from {sender}: {text}",
            flush=True,
        )

        try:
            reply = self.fast_agent.generate_whatsapp_reply(
                sender,
                conversation,
                text,
            )

            reply = str(reply).strip()

            if not reply:
                raise RuntimeError(
                    "Generated WhatsApp reply was empty."
                )

            # Send to the exact originating chat. This supports both
            # direct chats and group chats.
            self.whatsapp.send(
                chat_jid,
                reply,
            )

            print(
                f"[WHATSAPP AUTO] Sent reply: {reply}",
                flush=True,
            )

            self._remember(
                chat_jid,
                "outgoing",
                "JARVIS",
                reply,
            )

            # Mark handled locally immediately after successful send.
            self.handled_ids.add(message_id)
            self._save_state()

            # Bridge acknowledgement happens only after send succeeded.
            self.whatsapp.acknowledge_messages(
                [message_id]
            )

            return True

        except Exception as exc:
            print(
                f"[WHATSAPP AUTO ERROR] {exc}",
                flush=True,
            )

            # Do NOT acknowledge on failure.
            # The message remains available for a later retry.
            return False

    def run_once(self):
        messages = self.whatsapp.get_incoming_messages(
            limit=self.queue_limit
        )

        processed = 0

        for message in messages:
            if self._process_message(message):
                processed += 1

        return processed

    def _run(self):
        print(
            "[WHATSAPP AUTO] Worker started.",
            flush=True,
        )

        while not self._stop_event.is_set():
            try:
                self.run_once()

            except Exception as exc:
                print(
                    f"[WHATSAPP AUTO ERROR] Queue poll failed: {exc}",
                    flush=True,
                )

            self._stop_event.wait(
                self.poll_interval
            )

        print(
            "[WHATSAPP AUTO] Worker stopped.",
            flush=True,
        )

    def start(self):
        with self._lock:
            if (
                self._thread is not None
                and self._thread.is_alive()
            ):
                return False

            self._stop_event.clear()

            self._thread = threading.Thread(
                target=self._run,
                name="whatsapp-autoreply",
                daemon=True,
            )

            self._thread.start()

            return True

    def stop(self):
        self._stop_event.set()

        thread = self._thread

        if thread is not None:
            thread.join(
                timeout=3
            )
