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
                "ALL",
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
