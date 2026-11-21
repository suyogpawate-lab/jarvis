"""
JARVIS Gmail email manager.

Reading:
    IMAP over SSL

Sending:
    SMTP over SSL

Credentials are supplied by email_config.py.
"""

import email
import imaplib
import smtplib

from email.header import decode_header
from email.message import EmailMessage

from messaging.email_config import resolve_account


class EmailManager:

    def __init__(self, timeout=20):
        self.timeout = timeout

    @staticmethod
    def _decode(value):
        if not value:
            return ""

        parts = decode_header(value)
        output = []

        for part, encoding in parts:
            if isinstance(part, bytes):
                try:
                    output.append(
                        part.decode(
                            encoding or "utf-8",
                            errors="replace",
                        )
                    )
                except Exception:
                    output.append(
                        part.decode(
                            "utf-8",
                            errors="replace",
                        )
                    )
            else:
                output.append(str(part))

        return "".join(output)

    @staticmethod
    def _body(message):
        if message.is_multipart():
            for part in message.walk():
                content_type = part.get_content_type()
                disposition = str(
                    part.get("Content-Disposition", "")
                )

                if (
                    content_type == "text/plain"
                    and "attachment" not in disposition.lower()
                ):
                    payload = part.get_payload(
                        decode=True
                    )

                    if payload:
                        return payload.decode(
                            part.get_content_charset() or "utf-8",
                            errors="replace",
                        )

            return ""

        payload = message.get_payload(
            decode=True
        )

        if not payload:
            return ""

        return payload.decode(
            message.get_content_charset() or "utf-8",
            errors="replace",
        )

    @staticmethod
    def _preview(text, limit=500):
        text = str(text or "")

        # Collapse excessive whitespace.
        text = " ".join(text.split())

        if len(text) <= limit:
            return text

        return text[:limit].rstrip() + "..."

    def _account(self, requested=None):
        account = resolve_account(requested)

        if "error" in account:
            raise RuntimeError(account["error"])

        if not account["password"]:
            raise RuntimeError(
                f"No app password configured for {account['email']}"
            )

        return account

    def _imap(self, account):
        mail = imaplib.IMAP4_SSL(
            account["imap_host"],
            account["imap_port"],
            timeout=self.timeout,
        )

        mail.login(
            account["email"],
            account["password"],
        )

        return mail

    def list_recent(
        self,
        requested_account=None,
        mailbox="INBOX",
        limit=10,
        unread_only=False,
    ):
        account = self._account(
            requested_account
        )

        mail = None

        try:
            mail = self._imap(account)

            status, _ = mail.select(
                mailbox,
                readonly=True,
            )

            if status != "OK":
                raise RuntimeError(
                    f"Unable to open mailbox: {mailbox}"
                )

            status, data = mail.uid(
                "search",
                None,
                "UNSEEN" if unread_only else "ALL",
            )

            if status != "OK":
                raise RuntimeError(
                    "Unable to search mailbox."
                )

            message_ids = data[0].split()

            message_ids = message_ids[
                -int(limit):
            ]

            message_ids.reverse()

            results = []

            for uid in message_ids:

                status, fetched = mail.uid(
                    "fetch",
                    uid,
                    "(BODY.PEEK[])",
                )

                if status != "OK":
                    continue

                raw = None

                for item in fetched:
                    if isinstance(item, tuple):
                        raw = item[1]
                        break

                if not raw:
                    continue

                message = email.message_from_bytes(
                    raw
                )

                body = self._body(message)

                results.append({
                    "uid": uid.decode(
                        errors="replace"
                    ),
                    "account": account["email"],
                    "from": self._decode(
                        message.get("From", "")
                    ),
                    "to": self._decode(
                        message.get("To", "")
                    ),
                    "subject": self._decode(
                        message.get("Subject", "")
                    ),
                    "date": message.get(
                        "Date",
                        "",
                    ),
                    "preview": self._preview(
                        body,
                        500,
                    ),
                })

            return results

        finally:
            if mail:
                try:
                    mail.close()
                except Exception:
                    pass

                try:
                    mail.logout()
                except Exception:
                    pass

    def mark_all_unread_as_read(
        self,
        requested_account=None,
        mailbox="INBOX",
    ):
        """Mark all currently unread messages in one mailbox as read."""
        account = self._account(requested_account)
        mail = None

        try:
            mail = self._imap(account)
            status, _ = mail.select(mailbox, readonly=False)
            if status != "OK":
                raise RuntimeError(f"Unable to open mailbox: {mailbox}")

            status, data = mail.uid("search", None, "UNSEEN")
            if status != "OK":
                raise RuntimeError("Unable to search unread messages.")

            uids = data[0].split() if data and data[0] else []
            if not uids:
                return {
                    "status": "OK",
                    "account": account["email"],
                    "mailbox": mailbox,
                    "marked_read": 0,
                }

            uid_set = b",".join(uids)
            status, _ = mail.uid("store", uid_set, "+FLAGS", r"(\Seen)")
            if status != "OK":
                raise RuntimeError("Gmail did not confirm the read-status update.")

            return {
                "status": "OK",
                "account": account["email"],
                "mailbox": mailbox,
                "marked_read": len(uids),
            }
        finally:
            if mail:
                try:
                    mail.close()
                except Exception:
                    pass
                try:
                    mail.logout()
                except Exception:
                    pass

    def search(
        self,
        query,
        requested_account=None,
        mailbox="INBOX",
        limit=20,
    ):
        account = self._account(
            requested_account
        )

        query = str(query).strip()

        if not query:
            raise ValueError(
                "Search query cannot be empty."
            )

        mail = None

        try:
            mail = self._imap(account)

            status, _ = mail.select(
                mailbox,
                readonly=True,
            )

            if status != "OK":
                raise RuntimeError(
                    f"Unable to open mailbox: {mailbox}"
                )

            status, data = mail.uid(
                "search",
                None,
                "TEXT",
                f'"{query}"',
            )

            if status != "OK":
                raise RuntimeError(
                    "Email search failed."
                )

            message_ids = data[0].split()

            message_ids = message_ids[
                -int(limit):
            ]

            message_ids.reverse()

            results = []

            for uid in message_ids:

                status, fetched = mail.uid(
                    "fetch",
                    uid,
                    "(RFC822)",
                )

                if status != "OK":
                    continue

                raw = None

                for item in fetched:
                    if isinstance(item, tuple):
                        raw = item[1]
                        break

                if not raw:
                    continue

                message = email.message_from_bytes(
                    raw
                )

                body = self._body(message)

                results.append({
                    "uid": uid.decode(
                        errors="replace"
                    ),
                    "account": account["email"],
                    "from": self._decode(
                        message.get("From", "")
                    ),
                    "to": self._decode(
                        message.get("To", "")
                    ),
                    "subject": self._decode(
                        message.get("Subject", "")
                    ),
                    "date": message.get(
                        "Date",
                        "",
                    ),
                    "preview": self._preview(
                        body,
                        500,
                    ),
                })

            return results

        finally:
            if mail:
                try:
                    mail.close()
                except Exception:
                    pass

                try:
                    mail.logout()
                except Exception:
                    pass

    def send(
        self,
        to,
        subject,
        body,
        requested_account=None,
    ):
        account = self._account(
            requested_account
        )

        to = str(to).strip()

        if not to:
            raise ValueError(
                "Recipient cannot be empty."
            )

        message = EmailMessage()

        message["From"] = account["email"]
        message["To"] = to
        message["Subject"] = str(subject)

        message.set_content(
            str(body)
        )

        with smtplib.SMTP_SSL(
            account["smtp_host"],
            account["smtp_port"],
            timeout=self.timeout,
        ) as smtp:

            smtp.login(
                account["email"],
                account["password"],
            )

            smtp.send_message(
                message
            )

        return {
            "status": "SENT",
            "from": account["email"],
            "to": to,
            "subject": str(subject),
        }


    # ------------------------------------------------------------------
    # Individual messages, threads, attachments, folders and labels
    # ------------------------------------------------------------------

    @staticmethod
    def _uid_bytes(uid):
        value = str(uid or "").strip()
        if not value.isdigit():
            raise ValueError("A numeric IMAP UID is required.")
        return value.encode("ascii")

    def _fetch_raw(self, mail, uid):
        status, fetched = mail.uid("fetch", self._uid_bytes(uid), "(BODY.PEEK[])")
        if status != "OK":
            raise RuntimeError(f"Unable to fetch email UID {uid}.")
        for item in fetched or []:
            if isinstance(item, tuple) and len(item) > 1 and isinstance(item[1], bytes):
                return item[1]
        raise RuntimeError(f"Email UID {uid} was not found in the selected mailbox.")

    @staticmethod
    def _message_details(message, uid, account, include_body=True):
        body = EmailManager._body(message) if include_body else ""
        attachments = []
        if message.is_multipart():
            for part in message.walk():
                filename = part.get_filename()
                disposition = str(part.get("Content-Disposition", "")).lower()
                if filename or "attachment" in disposition:
                    attachments.append({
                        "filename": EmailManager._decode(filename or "attachment"),
                        "content_type": part.get_content_type(),
                        "size": len(part.get_payload(decode=True) or b""),
                    })
        return {
            "uid": str(uid),
            "account": account,
            "message_id": str(message.get("Message-ID") or ""),
            "from": EmailManager._decode(message.get("From", "")),
            "to": EmailManager._decode(message.get("To", "")),
            "cc": EmailManager._decode(message.get("Cc", "")),
            "reply_to": EmailManager._decode(message.get("Reply-To", "")),
            "subject": EmailManager._decode(message.get("Subject", "")),
            "date": str(message.get("Date") or ""),
            "in_reply_to": str(message.get("In-Reply-To") or ""),
            "references": str(message.get("References") or ""),
            "body": body,
            "preview": EmailManager._preview(body, 1000),
            "attachments": attachments,
        }

    def get_email(self, uid, requested_account=None, mailbox="INBOX"):
        account = self._account(requested_account)
        mail = None
        try:
            mail = self._imap(account)
            status, _ = mail.select(mailbox, readonly=True)
            if status != "OK":
                raise RuntimeError(f"Unable to open mailbox: {mailbox}")
            raw = self._fetch_raw(mail, uid)
            message = email.message_from_bytes(raw)
            return self._message_details(message, uid, account["email"])
        finally:
            if mail:
                try: mail.logout()
                except Exception: pass

    def set_read(self, uid, read=True, requested_account=None, mailbox="INBOX"):
        account = self._account(requested_account)
        mail = None
        try:
            mail = self._imap(account)
            status, _ = mail.select(mailbox, readonly=False)
            if status != "OK":
                raise RuntimeError(f"Unable to open mailbox: {mailbox}")
            flag = "+FLAGS" if read else "-FLAGS"
            status, _ = mail.uid("store", self._uid_bytes(uid), flag, r"(\\Seen)")
            if status != "OK":
                raise RuntimeError("Gmail did not confirm the read-status update.")
            return {"status": "OK", "account": account["email"], "mailbox": mailbox,
                    "uid": str(uid), "is_read": bool(read)}
        finally:
            if mail:
                try: mail.logout()
                except Exception: pass

    def list_mailboxes(self, requested_account=None):
        account = self._account(requested_account)
        mail = None
        try:
            mail = self._imap(account)
            status, rows = mail.list()
            if status != "OK":
                raise RuntimeError("Unable to list Gmail labels/mailboxes.")
            names = []
            for row in rows or []:
                if not row:
                    continue
                # The mailbox name is the final quoted or unquoted LIST token.
                import re
                match = re.search(rb'(?:"((?:[^"\\\\]|\\\\.)*)"|(\\S+))$', row)
                if match:
                    raw = match.group(1) or match.group(2)
                    names.append(raw.decode("utf-8", errors="replace").replace(r"\\", ""))
            return {"account": account["email"], "mailboxes": names}
        finally:
            if mail:
                try: mail.logout()
                except Exception: pass

    def manage_label(self, action, label, requested_account=None):
        account = self._account(requested_account)
        label = str(label or "").strip()
        if not label or len(label) > 120 or any(ch in label for ch in "\r\n"):
            raise ValueError("A valid Gmail label name (1–120 characters) is required.")
        if action not in ("create", "delete"):
            raise ValueError("Label action must be create or delete.")
        mail = None
        try:
            mail = self._imap(account)
            status, _ = mail.create(label) if action == "create" else mail.delete(label)
            if status != "OK":
                raise RuntimeError(f"Gmail could not {action} label: {label}")
            return {"status": "OK", "account": account["email"], "action": action, "label": label}
        finally:
            if mail:
                try: mail.logout()
                except Exception: pass

    def archive(self, uid, requested_account=None, mailbox="INBOX"):
        account = self._account(requested_account)
        mail = None
        try:
            mail = self._imap(account)
            status, _ = mail.select(mailbox, readonly=False)
            if status != "OK":
                raise RuntimeError(f"Unable to open mailbox: {mailbox}")
            # Gmail's IMAP extension removes only the INBOX label; the message
            # remains in All Mail and can be restored later.
            status, _ = mail.uid("store", self._uid_bytes(uid), "-X-GM-LABELS", r"(\\Inbox)")
            if status != "OK":
                raise RuntimeError("Gmail did not confirm the archive operation.")
            return {"status": "OK", "account": account["email"], "uid": str(uid), "archived": True}
        finally:
            if mail:
                try: mail.logout()
                except Exception: pass

    def delete(self, uid, requested_account=None, mailbox="INBOX"):
        account = self._account(requested_account)
        mail = None
        try:
            mail = self._imap(account)
            status, _ = mail.select(mailbox, readonly=False)
            if status != "OK":
                raise RuntimeError(f"Unable to open mailbox: {mailbox}")
            # Soft-delete only: copy to Gmail Trash before removing the original.
            status, _ = mail.uid("copy", self._uid_bytes(uid), '"[Gmail]/Trash"')
            if status != "OK":
                raise RuntimeError("Gmail could not move the message to Trash.")
            status, _ = mail.uid("store", self._uid_bytes(uid), "+FLAGS", r"(\\Deleted)")
            if status != "OK":
                raise RuntimeError("Message was copied to Trash but original cleanup failed.")
            mail.expunge()
            return {"status": "OK", "account": account["email"], "uid": str(uid), "moved_to_trash": True}
        finally:
            if mail:
                try: mail.logout()
                except Exception: pass

    def _send_message(self, account, message):
        with smtplib.SMTP_SSL(account["smtp_host"], account["smtp_port"], timeout=self.timeout) as smtp:
            smtp.login(account["email"], account["password"])
            smtp.send_message(message)

    def send_with_attachments(self, to, subject, body, paths, requested_account=None):
        import mimetypes
        from pathlib import Path
        account = self._account(requested_account)
        recipients = [x.strip() for x in str(to).split(",") if x.strip()]
        if not recipients or any("@" not in x for x in recipients):
            raise ValueError("At least one valid recipient email address is required.")
        message = EmailMessage()
        message["From"] = account["email"]
        message["To"] = ", ".join(recipients)
        message["Subject"] = str(subject)
        message.set_content(str(body))
        attached = []
        for raw_path in paths or []:
            path = Path(str(raw_path)).expanduser()
            if not path.is_file():
                raise FileNotFoundError(f"Attachment not found: {path}")
            data = path.read_bytes()
            if len(data) > 20 * 1024 * 1024:
                raise ValueError(f"Attachment exceeds 20 MB: {path.name}")
            ctype, encoding = mimetypes.guess_type(path.name)
            if not ctype or encoding:
                ctype = "application/octet-stream"
            maintype, subtype = ctype.split("/", 1)
            message.add_attachment(data, maintype=maintype, subtype=subtype, filename=path.name)
            attached.append({"filename": path.name, "size": len(data)})
        self._send_message(account, message)
        return {"status": "SENT", "from": account["email"], "to": recipients,
                "subject": str(subject), "attachments": attached}

    def download_attachments(self, uid, requested_account=None, mailbox="INBOX"):
        from pathlib import Path
        import re
        account = self._account(requested_account)
        mail = None
        try:
            mail = self._imap(account)
            status, _ = mail.select(mailbox, readonly=True)
            if status != "OK":
                raise RuntimeError(f"Unable to open mailbox: {mailbox}")
            message = email.message_from_bytes(self._fetch_raw(mail, uid))
            root = Path.home() / "jarvis" / "data" / "email_attachments"
            root.mkdir(parents=True, exist_ok=True)
            saved = []
            for index, part in enumerate(message.walk()):
                filename = part.get_filename()
                disposition = str(part.get("Content-Disposition", "")).lower()
                if not filename and "attachment" not in disposition:
                    continue
                payload = part.get_payload(decode=True)
                if payload is None:
                    continue
                filename = self._decode(filename or f"attachment-{index}.bin")
                filename = Path(filename.replace("\\", "/")).name
                filename = re.sub(r"[^A-Za-z0-9._() -]", "_", filename).strip(" .") or f"attachment-{index}.bin"
                destination = root / f"{uid}-{index}-{filename}"
                destination.write_bytes(payload)
                saved.append({"filename": filename, "path": str(destination), "size": len(payload)})
            return {"status": "OK", "account": account["email"], "uid": str(uid),
                    "directory": str(root), "attachments": saved}
        finally:
            if mail:
                try: mail.logout()
                except Exception: pass

    def reply(self, uid, body, requested_account=None, mailbox="INBOX", reply_all=False):
        from email.utils import getaddresses
        account = self._account(requested_account)
        mail = None
        try:
            mail = self._imap(account)
            status, _ = mail.select(mailbox, readonly=True)
            if status != "OK":
                raise RuntimeError(f"Unable to open mailbox: {mailbox}")
            original = email.message_from_bytes(self._fetch_raw(mail, uid))
        finally:
            if mail:
                try: mail.logout()
                except Exception: pass
        parsed = email.utils.parseaddr(self._decode(original.get("Reply-To") or original.get("From") or ""))[1]
        if not parsed or "@" not in parsed:
            raise ValueError("The original email has no valid reply address.")
        recipients = [parsed]
        if reply_all:
            for _, addr in getaddresses([self._decode(original.get("To", "")), self._decode(original.get("Cc", ""))]):
                if addr and addr.lower() not in {account["email"].lower(), parsed.lower()} and addr not in recipients:
                    recipients.append(addr)
        subject = self._decode(original.get("Subject", ""))
        if not subject.lower().startswith("re:"):
            subject = "Re: " + subject
        message = EmailMessage()
        message["From"] = account["email"]
        message["To"] = ", ".join(recipients)
        message["Subject"] = subject
        if original.get("Message-ID"):
            message["In-Reply-To"] = original["Message-ID"]
            refs = str(original.get("References") or "").strip()
            message["References"] = (refs + " " + str(original["Message-ID"])).strip()
        message.set_content(str(body))
        self._send_message(account, message)
        return {"status": "SENT", "from": account["email"], "to": recipients,
                "subject": subject, "in_reply_to": str(original.get("Message-ID") or "")}

    def forward(self, uid, to, body="", requested_account=None, mailbox="INBOX"):
        from email.utils import parseaddr
        account = self._account(requested_account)
        recipients = [x.strip() for x in str(to).split(",") if x.strip()]
        if not recipients or any("@" not in x for x in recipients):
            raise ValueError("At least one valid forwarding recipient is required.")
        mail = None
        try:
            mail = self._imap(account)
            status, _ = mail.select(mailbox, readonly=True)
            if status != "OK":
                raise RuntimeError(f"Unable to open mailbox: {mailbox}")
            original = email.message_from_bytes(self._fetch_raw(mail, uid))
        finally:
            if mail:
                try: mail.logout()
                except Exception: pass
        subject = self._decode(original.get("Subject", ""))
        if not subject.lower().startswith("fwd:"):
            subject = "Fwd: " + subject
        message = EmailMessage()
        message["From"] = account["email"]
        message["To"] = ", ".join(recipients)
        message["Subject"] = subject
        original_body = self._body(original)
        forwarded = (
            str(body).strip() + "\n\n" if str(body).strip() else ""
        ) + "---------- Forwarded message ----------\n" + (
            f"From: {self._decode(original.get('From', ''))}\n"
            f"Date: {self._decode(original.get('Date', ''))}\n"
            f"Subject: {subject}\n\n{original_body}"
        )
        message.set_content(forwarded)
        self._send_message(account, message)
        return {"status": "SENT", "from": account["email"], "to": recipients, "subject": subject}
