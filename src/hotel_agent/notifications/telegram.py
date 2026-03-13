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


def _format_alert_compact(alert: Alert) -> str:
    """Format one alert as a single compact line (best deal only)."""
    sev = _SEVERITY_EMOJI.get(alert.severity, "")
    typ = _ALERT_TYPE_EMOJI.get(alert.alert_type, "")

    line = f"{sev}{typ} <b>{alert.title}</b>"

    # Show only the best deal (first detail entry)
    if alert.details:
        d = alert.details[0]
        platform = d["platform"]
        link = d.get("link", "")
        if link:
            platform = f'<a href="{link}">{platform}</a>'
        pct = d.get("percentage_diff", 0)
        extras = []
        if d.get("is_cancellable"):
            extras.append("✅")
        if d.get("breakfast_included"):
            extras.append("🍳")
        extras_str = f" {' '.join(extras)}" if extras else ""
        line += (
            f"\n  → {platform}: <b>{d['price']:,.0f} {d['currency']}</b> ({pct:+.1f}%){extras_str}"
        )
        if len(alert.details) > 1:
            line += f"  +{len(alert.details) - 1} more"

    return line


def _format_alert_block(alert: Alert) -> str:
    """Format one alert as a detailed block with all vendor info."""
    sev = _SEVERITY_EMOJI.get(alert.severity, "")
    typ = _ALERT_TYPE_EMOJI.get(alert.alert_type, "")

    lines = [f"{sev}{typ} <b>{alert.title}</b>"]

    # Extract booking info from message header
    if alert.details:
        for msg_line in alert.message.split("\n"):
            if msg_line.startswith("  - "):
                break
            if "Your price:" in msg_line or "Dates:" in msg_line or "Room:" in msg_line:
                key, value = msg_line.split(": ", 1)
                lines.append(f"  <i>{key}:</i> {value}")

        # All vendor deals
        for d in alert.details:
            platform = d["platform"]
            link = d.get("link", "")
            if link:
                platform = f'<a href="{link}">{platform}</a>'
            pct = d.get("percentage_diff", 0)
            room = d.get("room_type") or "Standard"

            extras = []
            if d.get("is_cancellable"):
                extras.append("✅ cancel")
            if d.get("breakfast_included"):
                extras.append("🍳 bfast")
            deadline = d.get("cancellation_deadline", "")
            if deadline:
                extras.append(f"by {deadline}")
            extras_str = f"  [{', '.join(extras)}]" if extras else ""

            lines.append(
                f"  → {platform}: <b>{d['price']:,.0f} {d['currency']}</b>"
                f" ({pct:+.1f}%) {room}{extras_str}"
            )
    else:
        for msg_line in alert.message.split("\n"):
            stripped = msg_line.strip()
            if stripped:
                lines.append(f"  {stripped}")

    return "\n".join(lines)


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
    """Build Telegram messages, preferring ONE message over many.

    Strategy:
    1. Try detailed format (all vendors) in a single message.
    2. If too long, try compact format (best deal only) in a single message.
    3. If still too long, paginate using compact format.
    """
    ordered = (
        [a for a in alerts if a.severity == "urgent"]
        + [a for a in alerts if a.severity == "important"]
        + [a for a in alerts if a.severity == "info"]
    )

    header = _build_header(alerts)

    # 1) Try detailed — all vendors, single message
    detailed_blocks = [_format_alert_block(a) for a in ordered]
    full = header + "\n\n" + "\n\n".join(detailed_blocks)
    if len(full) <= _TG_MAX:
        return [full]

    # 2) Try compact — best deal only, single message
    compact_blocks = [_format_alert_compact(a) for a in ordered]
    full_compact = header + "\n\n" + "\n\n".join(compact_blocks)
    if len(full_compact) <= _TG_MAX:
        return [full_compact]

    # 3) Paginate using compact format
    messages: list[str] = []
    page_num = 1
    current_blocks: list[str] = []
    current_len = 0

    for block in compact_blocks:
        # header + page indicator + accumulated + new block + separators
        test_len = len(header) + 30 + current_len + len(block) + 2
        if current_blocks and test_len > _TG_MAX - 50:
            page_header = header + f"\n📄 <b>({page_num}/{{total}})</b>"
            messages.append(page_header + "\n\n" + "\n\n".join(current_blocks))
            current_blocks = []
            current_len = 0
            page_num += 1
        current_blocks.append(block)
        current_len += len(block) + 2

    if current_blocks:
        if not messages:
            messages.append(header + "\n\n" + "\n\n".join(current_blocks))
        else:
            page_header = header + f"\n📄 <b>({page_num}/{{total}})</b>"
            messages.append(page_header + "\n\n" + "\n\n".join(current_blocks))

    # Patch total page count
    total = len(messages)
    if total > 1:
        for i in range(total):
            messages[i] = messages[i].replace("{total}", str(total))

    return messages


def format_consolidated_message(alerts: list[Alert]) -> str:
    """Format all alerts into a single consolidated Telegram message."""
    msgs = _build_messages(alerts)
    return msgs[0] if msgs else ""


def format_alert_message(alert: Alert) -> str:
    """Format a single alert as an HTML message for Telegram."""
    return _format_alert_block(alert)


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
