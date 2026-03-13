"""Email notifications via Gmail SMTP."""

from __future__ import annotations

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from ..config import AppConfig
from ..models import Alert

log = logging.getLogger(__name__)


def _build_html_body(alerts: list[Alert], subject: str) -> str:
    """Build an HTML email body from a list of alerts."""
    sev_color = {"urgent": "#dc2626", "important": "#d97706", "info": "#2563eb"}
    type_label = {"price_drop": "Price Drop", "better_deal": "Better Deal", "upgrade": "Upgrade"}

    rows = []
    for a in alerts:
        color = sev_color.get(a.severity, "#64748b")
        typ = type_label.get(a.alert_type, a.alert_type)

        detail_html = ""
        if a.details:
            for d in a.details:
                room = d.get("room_type") or "Standard"
                pct = d.get("percentage_diff", 0)
                link = d.get("link", "")
                platform = d["platform"]
                if link:
                    platform = f'<a href="{link}" style="color:#2563eb;">{platform}</a>'
                cancel = " | Free cancel" if d.get("is_cancellable") else ""
                bfast = " | Breakfast" if d.get("breakfast_included") else ""
                detail_html += (
                    f'<div style="padding:4px 0;">'
                    f"{platform}: <b>{d['price']:,.0f} {d['currency']}</b> "
                    f"({pct:+.1f}%) &mdash; {room}{cancel}{bfast}</div>"
                )

        detail_section = ""
        if detail_html:
            detail_section = f'<div style="margin-top:6px;font-size:13px;">{detail_html}</div>'

        rows.append(
            f"<tr>"
            f'<td style="padding:12px;border-bottom:1px solid #e2e8f0;">'
            f'<span style="color:{color};font-weight:700;">{a.severity.upper()}</span>'
            f"</td>"
            f'<td style="padding:12px;border-bottom:1px solid #e2e8f0;">{typ}</td>'
            f'<td style="padding:12px;border-bottom:1px solid #e2e8f0;">'
            f"<b>{a.title}</b>{detail_section}"
            f"</td>"
            f'<td style="padding:12px;border-bottom:1px solid #e2e8f0;text-align:right;">'
            f"{a.price_diff:,.0f} ({a.percentage_diff:.1f}%)"
            f"</td>"
            f"</tr>"
        )

    return (
        f'<div style="font-family:-apple-system,sans-serif;max-width:700px;margin:0 auto;">'
        f'<h2 style="color:#1e293b;">{subject}</h2>'
        f'<p style="color:#64748b;">Found {len(alerts)} alert{"s" if len(alerts) != 1 else ""}.</p>'
        f'<table style="width:100%;border-collapse:collapse;font-size:14px;">'
        f'<thead><tr style="background:#f8fafc;">'
        f'<th style="padding:8px 12px;text-align:left;">Severity</th>'
        f'<th style="padding:8px 12px;text-align:left;">Type</th>'
        f'<th style="padding:8px 12px;text-align:left;">Details</th>'
        f'<th style="padding:8px 12px;text-align:right;">Savings</th>'
        f"</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody>"
        f"</table></div>"
    )


def send_email(
    config: AppConfig,
    subject: str,
    html_body: str,
    recipients: list[str] | None = None,
) -> bool:
    """Send an HTML email via Gmail SMTP."""
    gmail_user = config.gmail_user.get_secret_value()
    gmail_pass = config.gmail_app_password.get_secret_value()

    if not gmail_user or not gmail_pass:
        log.warning("Gmail not configured (missing user or app password)")
        return False

    to_addrs = recipients or config.notifications.email.recipients
    if not to_addrs:
        log.warning("No email recipients configured")
        return False

    msg = MIMEMultipart("alternative")
    msg["From"] = gmail_user
    msg["To"] = ", ".join(to_addrs)
    msg["Subject"] = subject
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15) as server:
            server.login(gmail_user, gmail_pass)
            server.sendmail(gmail_user, to_addrs, msg.as_string())
        log.info("Email sent to %s", ", ".join(to_addrs))
        return True
    except Exception as e:
        log.error("Email send failed: %s", e)
        return False


def notify_alerts_email(config: AppConfig, alerts: list[Alert]) -> int:
    """Send a triggered email with all pending alerts.

    Returns the count of alerts included in the email.
    """
    if not config.notifications.email.triggered_enabled:
        return 0

    pending = [a for a in alerts if not a.notified_email]
    if not pending:
        return 0

    subject = f"Hotel Tracker: {len(pending)} new alert{'s' if len(pending) != 1 else ''}"
    body = _build_html_body(pending, subject)

    if send_email(config, subject, body):
        return len(pending)
    return 0


def send_digest_email(
    config: AppConfig,
    alerts: list[Alert],
    summary: str = "",
) -> bool:
    """Send a digest email with LLM-generated summary + alert details.

    Parameters
    ----------
    config:
        App configuration.
    alerts:
        Alerts to include in the digest.
    summary:
        LLM-generated summary text (optional).
    """
    if not alerts:
        log.info("No alerts for digest email")
        return False

    subject = f"Hotel Tracker Daily Digest: {len(alerts)} alert{'s' if len(alerts) != 1 else ''}"

    summary_html = ""
    if summary:
        summary_html = (
            f'<div style="background:#eff6ff;border-left:4px solid #3b82f6;'
            f'padding:12px 16px;margin-bottom:20px;border-radius:4px;">'
            f"<b>Summary</b><br>{summary}</div>"
        )

    body_html = _build_html_body(alerts, subject)
    full_html = (
        f'<div style="font-family:-apple-system,sans-serif;max-width:700px;margin:0 auto;">'
        f"{summary_html}{body_html}</div>"
    )

    return send_email(config, subject, full_html)
