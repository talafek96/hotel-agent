"""Telegram bot notifications."""

from __future__ import annotations

import logging
from datetime import datetime

import requests

from ..config import AppConfig
from ..models import Alert

log = logging.getLogger(__name__)

_SEVERITY_EMOJI = {
    "urgent": "🔴",
    "important": "🟡",
    "info": "🔵",
}

_ALERT_TYPE_EMOJI = {
    "price_drop": "💰",
    "better_deal": "✨",
    "upgrade": "⬆️",
}


def send_telegram_message(
    config: AppConfig,
    message: str,
    parse_mode: str = "HTML",
) -> bool:
    """Send a message via Telegram Bot API."""
    token = config.telegram_bot_token.get_secret_value()
    chat_id = config.telegram_chat_id.get_secret_value()

    if not token or not chat_id:
        log.warning("Telegram not configured (missing token or chat_id)")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }

    try:
        resp = requests.post(url, json=payload, timeout=10)
        if resp.ok:
            log.info("Telegram message sent successfully")
            return True
        else:
            log.error(f"Telegram API error: {resp.status_code} {resp.text}")
            return False
    except Exception as e:
        log.error(f"Telegram send failed: {e}")
        return False


def _format_single_alert(alert: Alert) -> str:
    """Format one alert as a compact section for the consolidated message."""
    sev = _SEVERITY_EMOJI.get(alert.severity, "")
    typ = _ALERT_TYPE_EMOJI.get(alert.alert_type, "")

    lines = [f"{sev}{typ} <b>{alert.title}</b>"]

    if alert.details:
        # Extract header info from the plain message
        for line in alert.message.split("\n"):
            if line.startswith("  - "):
                break
            if "Your price:" in line or "Dates:" in line:
                key, value = line.split(": ", 1)
                lines.append(f"  {key}: {value}")

        # Vendor list — compact
        for d in alert.details:
            cancel = "✅" if d.get("is_cancellable") else ""
            bfast = "🍳" if d.get("breakfast_included") else ""
            icons = f"{cancel}{bfast}".strip()
            room = d.get("room_type") or "Standard"
            pct = d.get("percentage_diff", 0)
            link = d.get("link", "")

            platform = d["platform"]
            if link:
                platform = f'<a href="{link}">{platform}</a>'

            line = f"  • {platform}: <b>{d['price']:,.0f} {d['currency']}</b> ({pct:+.1f}%)"
            extras = " | ".join(filter(None, [room, icons]))
            if extras:
                line += f" — {extras}"

            deadline = d.get("cancellation_deadline", "")
            if deadline:
                line += f" (cancel by {deadline})"

            lines.append(line)
    else:
        # Plain text fallback
        for line in alert.message.split("\n"):
            if line.strip():
                lines.append(f"  {line.strip()}")

    return "\n".join(lines)


def format_consolidated_message(alerts: list[Alert]) -> str:
    """Format all alerts into a single consolidated Telegram message."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    urgent = [a for a in alerts if a.severity == "urgent"]
    important = [a for a in alerts if a.severity == "important"]
    info = [a for a in alerts if a.severity == "info"]

    lines = [
        f"🏨 <b>Hotel Price Tracker</b> — {now}",
        f"📊 <b>{len(alerts)} alert{'s' if len(alerts) != 1 else ''}</b>",
    ]

    if urgent:
        lines.append(f"  🔴 {len(urgent)} urgent")
    if important:
        lines.append(f"  🟡 {len(important)} important")
    if info:
        lines.append(f"  🔵 {len(info)} info")

    lines.append("")

    # Group alerts by severity (urgent first)
    ordered = urgent + important + info
    for i, alert in enumerate(ordered):
        if i > 0:
            lines.append("")
        lines.append(_format_single_alert(alert))

    return "\n".join(lines)


def format_alert_message(alert: Alert) -> str:
    """Format a single alert as an HTML message for Telegram."""
    return _format_single_alert(alert)


def notify_alerts(config: AppConfig, alerts: list[Alert]) -> int:
    """Send alert notifications via Telegram.

    Sends all pending alerts as a single consolidated message.
    Returns the count of alerts included in the message.
    """
    if not config.notifications.telegram.enabled:
        return 0

    pending = [a for a in alerts if not a.notified_telegram]
    if not pending:
        return 0

    msg = format_consolidated_message(pending)

    # Telegram has a 4096 char limit — split if needed
    if len(msg) <= 4096:
        if send_telegram_message(config, msg):
            log.info("Sent consolidated Telegram notification (%d alerts)", len(pending))
            return len(pending)
        return 0

    # Message too long — send in chunks by alert
    sent = 0
    for alert in pending:
        single = _format_single_alert(alert)
        if send_telegram_message(config, single):
            sent += 1

    if sent > 0:
        log.info("Sent %d individual Telegram notifications (message too long for single)", sent)

    return sent
