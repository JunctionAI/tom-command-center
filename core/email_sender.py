"""
email_sender.py — Gmail SMTP sender for tom-command-center agents.

Generic, configurable outbound email utility. Used initially by rory-coach
agent but designed to serve any agent needing to ship email to a client.

Auth: Gmail App Password (SMTP_EMAIL + SMTP_APP_PASSWORD env vars OR
passed in via per-agent config).

Docs on App Passwords: https://support.google.com/accounts/answer/185833

Usage:
    from core.email_sender import send_email

    send_email(
        to="rory@example.com",
        subject="Rory — week of Apr 21-27",
        body_text="Hey mate,\\n\\n...",
        sender_email="tom@junctionai.com",
        sender_password=os.environ["TOM_GMAIL_APP_PASSWORD"],
        sender_name="Tom",
    )
"""

from __future__ import annotations

import logging
import os
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

logger = logging.getLogger(__name__)

SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 465  # SSL


def send_email(
    to: str,
    subject: str,
    body_text: str,
    sender_email: Optional[str] = None,
    sender_password: Optional[str] = None,
    sender_name: Optional[str] = None,
    body_html: Optional[str] = None,
    reply_to: Optional[str] = None,
) -> dict:
    """
    Send a plain-text (optionally multipart HTML) email via Gmail SMTP.

    Args:
        to: recipient email address
        subject: email subject line
        body_text: plain text body
        sender_email: Gmail address. Defaults to SMTP_EMAIL env var.
        sender_password: Gmail App Password. Defaults to SMTP_APP_PASSWORD env var.
        sender_name: display name in From header. Defaults to "".
        body_html: optional HTML alternative body
        reply_to: optional Reply-To header

    Returns:
        dict with keys: {ok: bool, error: str|None}

    Notes:
        - Uses SSL (port 465) not STARTTLS.
        - Gmail requires App Password, not account password, when 2FA is on.
        - Silent-fails gracefully — returns {ok: False, error: ...} rather than raising,
          so scheduled agents don't crash the orchestrator loop.
    """
    sender_email = sender_email or os.environ.get("SMTP_EMAIL", "")
    sender_password = sender_password or os.environ.get("SMTP_APP_PASSWORD", "")

    if not sender_email or not sender_password:
        msg = "SMTP credentials missing (SMTP_EMAIL / SMTP_APP_PASSWORD)"
        logger.error(msg)
        return {"ok": False, "error": msg}

    from_header = (
        f"{sender_name} <{sender_email}>" if sender_name else sender_email
    )

    if body_html:
        msg = MIMEMultipart("alternative")
        msg.attach(MIMEText(body_text, "plain", "utf-8"))
        msg.attach(MIMEText(body_html, "html", "utf-8"))
    else:
        msg = MIMEText(body_text, "plain", "utf-8")

    msg["Subject"] = subject
    msg["From"] = from_header
    msg["To"] = to
    if reply_to:
        msg["Reply-To"] = reply_to

    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, context=ctx, timeout=30) as server:
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, [to], msg.as_string())
        logger.info(f"Email sent: to={to}, subject={subject[:60]}")
        return {"ok": True, "error": None}
    except smtplib.SMTPAuthenticationError as e:
        err = f"SMTP auth failed — check App Password: {e}"
        logger.error(err)
        return {"ok": False, "error": err}
    except Exception as e:
        err = f"SMTP send failed: {type(e).__name__}: {e}"
        logger.error(err)
        return {"ok": False, "error": err}


def verify_credentials(
    sender_email: Optional[str] = None,
    sender_password: Optional[str] = None,
) -> dict:
    """
    Test SMTP credentials without sending an email. Useful for CI / env sanity checks.
    """
    sender_email = sender_email or os.environ.get("SMTP_EMAIL", "")
    sender_password = sender_password or os.environ.get("SMTP_APP_PASSWORD", "")

    if not sender_email or not sender_password:
        return {"ok": False, "error": "credentials not set"}

    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, context=ctx, timeout=15) as server:
            server.login(sender_email, sender_password)
        return {"ok": True, "error": None}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


if __name__ == "__main__":
    # Quick CLI test: python -m core.email_sender
    import sys

    logging.basicConfig(level=logging.INFO)

    result = verify_credentials()
    if not result["ok"]:
        print(f"Credential check failed: {result['error']}")
        print("Set SMTP_EMAIL and SMTP_APP_PASSWORD env vars.")
        sys.exit(1)

    print("SMTP credentials valid.")

    if len(sys.argv) > 1 and sys.argv[1] == "--test-send":
        to = sys.argv[2] if len(sys.argv) > 2 else os.environ.get("SMTP_EMAIL")
        r = send_email(
            to=to,
            subject="email_sender.py test",
            body_text="If you're reading this, SMTP is working.",
            sender_name="Tom",
        )
        print(r)
