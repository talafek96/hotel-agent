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

_TG_MAX = 4096


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


def _format_alert_line(alert: Alert) -> str:
    """Format one alert as a compact 1-3 line block for the consolidated message."""
    sev = _SEVERITY_EMOJI.get(alert.severity, "")
    typ = _ALERT_TYPE_EMOJI.get(alert.alert_type, "")

    # Title line
    line = f"{sev}{typ} <b>{alert.title}</b>"

    # Best deal from details (first entry = best, already sorted by savings)
    if alert.details:
        best = alert.details[0]
        platform = best["platform"]
        link = best.get("link", "")
        if link:
            platform = f'<a href="{link}">{platform}</a>'
        pct = best.get("percentage_diff", 0)
        cancel = " ✅" if best.get("is_cancellable") else ""
        line += (
            f"\n  {platform}: <b>{best['price']:,.0f} {best['currency']}</b> ({pct:+.1f}%){cancel}"
        )
        if len(alert.details) > 1:
            line += f"  <i>+{len(alert.details) - 1} more</i>"

    return line


def _build_header(alerts: list[Alert]) -> str:
    """Build the summary header block."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    urgent = sum(1 for a in alerts if a.severity == "urgent")
    important = sum(1 for a in alerts if a.severity == "important")
    info = sum(1 for a in alerts if a.severity == "info")

    parts = [f"🏨 <b>Hotel Price Tracker</b> — {now}"]
    counts = []
    if urgent:
        counts.append(f"🔴{urgent}")
    if important:
        counts.append(f"🟡{important}")
    if info:
        counts.append(f"🔵{info}")
    parts.append(f"📊 <b>{len(alerts)}</b> alerts  {' '.join(counts)}")
    parts.append("━━━━━━━━━━━━━━━━━━━━")
    return "\n".join(parts)


def _build_messages(alerts: list[Alert]) -> list[str]:
    """Build one or more Telegram messages, each within the 4096 char limit.

    Alerts are grouped by severity (urgent first). Each message gets a header.
    """
    # Order by severity
    ordered = (
        [a for a in alerts if a.severity == "urgent"]
        + [a for a in alerts if a.severity == "important"]
        + [a for a in alerts if a.severity == "info"]
    )

    alert_blocks = [_format_alert_line(a) for a in ordered]
    header = _build_header(alerts)

    # Try to fit everything in one message
    full = header + "\n\n" + "\n\n".join(alert_blocks)
    if len(full) <= _TG_MAX:
        return [full]

    # Split into pages
    messages: list[str] = []
    page_num = 1
    current_blocks: list[str] = []
    current_len = 0

    for block in alert_blocks:
        # Estimate: header + separator + blocks so far + this block
        test_len = len(header) + 30 + current_len + len(block) + 2  # +2 for \n\n
        if current_blocks and test_len > _TG_MAX - 50:
            # Flush current page
            page_header = header + f"\n📄 <b>({page_num}/{'-'})</b>"
            messages.append(page_header + "\n\n" + "\n\n".join(current_blocks))
            current_blocks = []
            current_len = 0
            page_num += 1
        current_blocks.append(block)
        current_len += len(block) + 2

    if current_blocks:
        if len(messages) == 0:
            messages.append(header + "\n\n" + "\n\n".join(current_blocks))
        else:
            page_header = header + f"\n📄 <b>({page_num}/{'-'})</b>"
            messages.append(page_header + "\n\n" + "\n\n".join(current_blocks))

    # Patch page counts now that we know the total
    total = len(messages)
    if total > 1:
        for i in range(total):
            messages[i] = messages[i].replace(f"({i + 1}/{'-'})", f"({i + 1}/{total})")

    return messages


def format_consolidated_message(alerts: list[Alert]) -> str:
    """Format all alerts into a single consolidated Telegram message.

    For backward compat — returns just the first page if splitting is needed.
    """
    msgs = _build_messages(alerts)
    return msgs[0] if msgs else ""


def format_alert_message(alert: Alert) -> str:
    """Format a single alert as an HTML message for Telegram."""
    return _format_alert_line(alert)


def notify_alerts(config: AppConfig, alerts: list[Alert]) -> int:
    """Send alert notifications via Telegram.

    Consolidates all pending alerts into as few messages as possible.
    Returns the count of alerts successfully included.
    """
    if not config.notifications.telegram.enabled:
        return 0

    pending = [a for a in alerts if not a.notified_telegram]
    if not pending:
        return 0

    messages = _build_messages(pending)
    all_sent = True
    for msg in messages:
        if not send_telegram_message(config, msg):
            all_sent = False

    if all_sent:
        log.info("Sent %d Telegram message(s) with %d alerts", len(messages), len(pending))
        return len(pending)

    log.warning("Some Telegram messages failed to send")
    return 0
