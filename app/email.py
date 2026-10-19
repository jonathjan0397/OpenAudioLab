"""Best-effort transactional email. Empty SMTP host leaves delivery pending."""

from __future__ import annotations

import smtplib
from email.message import EmailMessage

from .config import Settings


def send_email(settings: Settings, to: str, subject: str, body: str) -> str:
    if not settings.smtp_host:
        return "pending"
    if not settings.smtp_from:
        return "error"
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.smtp_from
    message["To"] = to
    message.set_content(body)
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
            if settings.smtp_user or settings.smtp_password:
                smtp.starttls()
                smtp.login(settings.smtp_user, settings.smtp_password)
            smtp.send_message(message)
    except Exception:
        return "error"
    return "sent"
