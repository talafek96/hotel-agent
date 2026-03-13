"""Telegram bot notifications."""

from __future__ import annotations

import logging

import requests

from ..config import AppConfig
from ..models import Alert

log = logging.getLogger(__name__)

# Severity to emoji mapping
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
    token = config.telegram_bot_token
    chat_id = config.telegram_chat_id

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


def format_alert_message(alert: Alert) -> str:
    """Format an alert as an HTML message for Telegram.

    Uses the structured details list if available for rich per-vendor info.
    """
    severity_emoji = _SEVERITY_EMOJI.get(alert.severity, "")
    type_emoji = _ALERT_TYPE_EMOJI.get(alert.alert_type, "")

    lines = [
        f"{severity_emoji}{type_emoji} <b>{alert.title}</b>",
        "",
    ]

    if alert.details:
        # Structured consolidated alert
        header_lines = alert.message.split("\n")
        # Add header lines (hotel name, your price, dates) up to the vendor list
        for line in header_lines:
            if line.startswith("  - "):
                break
            if ": " in line:
                key, value = line.split(": ", 1)
                lines.append(f"<b>{key}:</b> {value}")
            elif line.strip():
                lines.append(line)
            else:
                lines.append("")

        # Add detailed vendor list from structured data
        for d in alert.details:
            cancel_icon = "✅" if d.get("is_cancellable") else ""
            bfast_icon = "🍳" if d.get("breakfast_included") else ""
            icons = f" {cancel_icon}{bfast_icon}".rstrip()
            room = d.get("room_type") or "Standard"
            pct = d.get("percentage_diff", 0)
            link = d.get("link", "")

            platform = d["platform"]
            if link:
                platform = f'<a href="{link}">{platform}</a>'

            line = f"  • <b>{platform}</b>: {d['price']:,.0f} {d['currency']} ({pct:+.1f}%)"
            line += f"\n    {room}{icons}"

            amenities = d.get("amenities", [])
            if amenities:
                line += f"\n    {', '.join(amenities[:3])}"

            deadline = d.get("cancellation_deadline", "")
            if deadline:
                line += f"\n    Cancel by: {deadline}"

            lines.append(line)
    else:
        # Legacy format: plain text message
        for line in alert.message.split("\n"):
            if ": " in line:
                key, value = line.split(": ", 1)
                lines.append(f"<b>{key}:</b> {value}")
            else:
                lines.append(line)

    return "\n".join(lines)


def notify_alerts(config: AppConfig, alerts: list[Alert]) -> int:
    """Send alert notifications via Telegram. Returns count of sent messages."""
    if not config.notifications.telegram_enabled:
        return 0

    sent = 0
    for alert in alerts:
        if alert.notified_telegram:
            continue
        msg = format_alert_message(alert)
        if send_telegram_message(config, msg):
            sent += 1

    if sent > 0:
        log.info(f"Sent {sent} Telegram notifications")

    return sent
