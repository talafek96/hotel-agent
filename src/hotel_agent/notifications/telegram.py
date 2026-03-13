"""Telegram bot notifications with Telegraph for detailed alerts."""

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

# ── Telegraph (telegra.ph) ──────────────────────────────

_telegraph_token: str | None = None


def _get_telegraph_token() -> str:
    """Get or create a Telegraph access token (cached per process)."""
    global _telegraph_token
    if _telegraph_token:
        return _telegraph_token
    resp = requests.post(
        "https://api.telegra.ph/createAccount",
        json={"short_name": "HotelTracker", "author_name": "Hotel Price Tracker"},
        timeout=10,
    )
    data = resp.json()
    if data.get("ok"):
        _telegraph_token = data["result"]["access_token"]
        return _telegraph_token
    raise RuntimeError(f"Failed to create Telegraph account: {data}")


def _build_telegraph_content(alerts: list[Alert]) -> list:
    """Build Telegraph DOM nodes from alerts."""
    nodes: list = []

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    urgent = sum(1 for a in alerts if a.severity == "urgent")
    important = sum(1 for a in alerts if a.severity == "important")
    info = sum(1 for a in alerts if a.severity == "info")
    counts = []
    if urgent:
        counts.append(f"🔴 {urgent} urgent")
    if important:
        counts.append(f"🟡 {important} important")
    if info:
        counts.append(f"🔵 {info} info")
    nodes.append(
        {"tag": "p", "children": [{"tag": "em", "children": [f"{now} — {' | '.join(counts)}"]}]}
    )

    ordered = (
        [a for a in alerts if a.severity == "urgent"]
        + [a for a in alerts if a.severity == "important"]
        + [a for a in alerts if a.severity == "info"]
    )

    for alert in ordered:
        sev = _SEVERITY_EMOJI.get(alert.severity, "")
        typ = _ALERT_TYPE_EMOJI.get(alert.alert_type, "")

        # Alert title
        nodes.append({"tag": "h4", "children": [f"{sev}{typ} {alert.title}"]})

        # Booking context from message header
        if alert.details:
            booking_parts = []
            for msg_line in alert.message.split("\n"):
                if msg_line.startswith("  - "):
                    break
                if "Your price:" in msg_line or "Dates:" in msg_line or "Room:" in msg_line:
                    booking_parts.append(msg_line.strip())
            if booking_parts:
                nodes.append(
                    {
                        "tag": "p",
                        "children": [{"tag": "i", "children": [" | ".join(booking_parts)]}],
                    }
                )

            # All vendor deals
            for d in alert.details:
                platform = d["platform"]
                link = d.get("link", "")
                pct = d.get("percentage_diff", 0)
                room = d.get("room_type") or "Standard"

                extras = []
                if d.get("is_cancellable"):
                    extras.append("✅ cancellable")
                if d.get("breakfast_included"):
                    extras.append("🍳 breakfast")
                deadline = d.get("cancellation_deadline", "")
                if deadline:
                    extras.append(f"cancel by {deadline}")
                extras_str = f"  [{', '.join(extras)}]" if extras else ""

                children: list = ["→ "]
                if link:
                    children.append({"tag": "a", "attrs": {"href": link}, "children": [platform]})
                else:
                    children.append(platform)
                children.append(
                    f": {d['price']:,.0f} {d['currency']} ({pct:+.1f}%) — {room}{extras_str}"
                )
                nodes.append({"tag": "p", "children": children})
        else:
            for msg_line in alert.message.split("\n"):
                stripped = msg_line.strip()
                if stripped:
                    nodes.append({"tag": "p", "children": [stripped]})

        nodes.append({"tag": "hr"})

    return nodes


def _create_telegraph_page(alerts: list[Alert]) -> str | None:
    """Create a Telegraph page with full alert details. Returns URL or None."""
    try:
        token = _get_telegraph_token()
        content = _build_telegraph_content(alerts)
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        resp = requests.post(
            "https://api.telegra.ph/createPage",
            json={
                "access_token": token,
                "title": f"Hotel Alerts — {now}",
                "content": content,
                "author_name": "Hotel Price Tracker",
            },
            timeout=15,
        )
        data = resp.json()
        if data.get("ok"):
            url: str = data["result"]["url"]
            log.info("Telegraph page created: %s", url)
            return url
        log.error("Telegraph API error: %s", data)
    except Exception as e:
        log.error("Telegraph page creation failed: %s", e)
    return None


# ── Telegram message sending ────────────────────────────


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
        "disable_web_page_preview": False,
    }

    try:
        resp = requests.post(url, json=payload, timeout=10)
        if resp.ok:
            log.info("Telegram message sent successfully")
            return True
        else:
            log.error("Telegram API error: %s %s", resp.status_code, resp.text)
            return False
    except Exception as e:
        log.error("Telegram send failed: %s", e)
        return False


# ── Message formatting ──────────────────────────────────


def _format_alert_compact(alert: Alert) -> str:
    """Format one alert as a compact summary line (best deal only)."""
    sev = _SEVERITY_EMOJI.get(alert.severity, "")
    typ = _ALERT_TYPE_EMOJI.get(alert.alert_type, "")

    line = f"{sev}{typ} <b>{alert.title}</b>"

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
    """Build Telegram messages — always ONE message.

    Strategy:
    1. Try detailed format (all vendors) in a single message.
    2. If too long, create a Telegraph page with full details and send
       a compact summary with an Instant View link.
    3. If Telegraph fails, fall back to compact-only (no link).
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

    # 2) Compact summary + Telegraph link with full details
    compact_blocks = [_format_alert_compact(a) for a in ordered]
    telegraph_url = _create_telegraph_page(alerts)

    if telegraph_url:
        footer = f'\n\n📋 <a href="{telegraph_url}">Full details (tap for Instant View)</a>'
        body = header + "\n\n" + "\n\n".join(compact_blocks) + footer
        # Truncate alerts from the end if even compact + link is too long
        while len(body) > _TG_MAX and len(compact_blocks) > 1:
            compact_blocks.pop()
            remaining = len(ordered) - len(compact_blocks)
            truncated_footer = f"\n\n… +{remaining} more"
            body = header + "\n\n" + "\n\n".join(compact_blocks) + truncated_footer + footer
        return [body]

    # 3) Fallback: compact only, truncate to fit one message
    body = header + "\n\n" + "\n\n".join(compact_blocks)
    while len(body) > _TG_MAX and len(compact_blocks) > 1:
        compact_blocks.pop()
        remaining = len(ordered) - len(compact_blocks)
        body = header + "\n\n" + "\n\n".join(compact_blocks) + f"\n\n… +{remaining} more"
    return [body]


def format_consolidated_message(alerts: list[Alert]) -> str:
    """Format all alerts into a single consolidated Telegram message."""
    msgs = _build_messages(alerts)
    return msgs[0] if msgs else ""


def format_alert_message(alert: Alert) -> str:
    """Format a single alert as an HTML message for Telegram."""
    return _format_alert_block(alert)


def notify_alerts(config: AppConfig, alerts: list[Alert]) -> int:
    """Send alert notifications via Telegram.

    Consolidates all pending alerts into a single message (with Telegraph
    link for full details when the message would exceed Telegram's limit).
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
