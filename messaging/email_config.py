"""
JARVIS email account configuration.
"""

import os

from jarvis_env import load_env

# Credentials live in <project root>/.env (written by `python setup.py`).
load_env()


def get_default_email():
    """Optional: JARVIS_DEFAULT_EMAIL. Empty means 'use the first account'."""
    return os.getenv("JARVIS_DEFAULT_EMAIL", "").strip()


def get_accounts():
    """
    Returns configured Gmail accounts.

    Environment format:

        JARVIS_GMAIL_1_EMAIL
        JARVIS_GMAIL_1_APP_PASSWORD

        JARVIS_GMAIL_2_EMAIL
        JARVIS_GMAIL_2_APP_PASSWORD
    """

    accounts = {}

    for index in range(1, 10):

        email = os.getenv(
            f"JARVIS_GMAIL_{index}_EMAIL"
        )

        password = os.getenv(
            f"JARVIS_GMAIL_{index}_APP_PASSWORD"
        )

        if not email:
            continue

        accounts[email.lower()] = {
            "email": email,
            "password": password or "",
            "smtp_host": "smtp.gmail.com",
            "smtp_port": 465,
            "imap_host": "imap.gmail.com",
            "imap_port": 993,
        }

    return accounts


def resolve_account(requested=None):

    accounts = get_accounts()

    if requested:

        requested = requested.strip().lower()

        if requested in accounts:
            return accounts[requested]

        return {
            "error": (
                f"Email account is not configured: "
                f"{requested}"
            )
        }

    if not accounts:
        return {
            "error": (
                "No email account is configured. "
                "Run `python setup.py` to add a Gmail account."
            )
        }

    default_email = get_default_email().lower()

    if not default_email:
        return next(iter(accounts.values()))

    if default_email in accounts:
        return accounts[default_email]

    return {
        "error": (
            f"Default email account is not configured: "
            f"{default_email}"
        )
    }
