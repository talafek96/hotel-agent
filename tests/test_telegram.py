"""Tests for hotel_agent.notifications.telegram module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from pydantic import SecretStr

from hotel_agent.config import AppConfig, NotificationConfig, TelegramNotifConfig
from hotel_agent.models import Alert
from hotel_agent.notifications.telegram import (
    _build_header,
    _build_messages,
    _build_telegraph_content,
    _create_telegraph_page,
    _format_alert_block,
    _format_alert_compact,
    format_alert_message,
    format_consolidated_message,
    notify_alerts,
    send_telegram_message,
)


def _make_config(**overrides: object) -> AppConfig:
    cfg = AppConfig(
        _env_file=None,
        telegram_bot_token=SecretStr("fake-token"),
        telegram_chat_id=SecretStr("123456"),
    )
    cfg.notifications = NotificationConfig(
        telegram=TelegramNotifConfig(enabled=True),
    )
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg


def _make_alert(**overrides: object) -> Alert:
    defaults = dict(
        booking_id=1,
        snapshot_id=1,
        alert_type="price_drop",
        severity="urgent",
        title="Price drop: Hotel Grand Tokyo",
        message="Hotel Grand Tokyo\nYour price: 50,000 JPY\nDates: 2025-01-01 to 2025-01-05\nRoom: Deluxe\n  - Booking.com: 45,000 JPY",
        price_diff=5000.0,
        percentage_diff=10.0,
        notified_telegram=False,
        details=[
            {
                "platform": "Booking.com",
                "price": 45000,
                "currency": "JPY",
                "percentage_diff": -10.0,
                "room_type": "Deluxe",
                "is_cancellable": True,
                "breakfast_included": False,
                "cancellation_deadline": "2025-01-01",
                "link": "https://booking.com/hotel-grand",
            },
            {
                "platform": "Hotels.com",
                "price": 46000,
                "currency": "JPY",
                "percentage_diff": -8.0,
                "room_type": "Standard",
                "is_cancellable": False,
                "breakfast_included": True,
                "link": "https://hotels.com/hotel-grand",
            },
        ],
    )
    defaults.update(overrides)
    return Alert(**defaults)


# ── Compact format ──────────────────────────────────────


class TestFormatAlertCompact:
    def test_shows_best_deal_only(self):
        alert = _make_alert()
        result = _format_alert_compact(alert)
        assert "Booking.com" in result
        assert "45,000" in result
        assert "Hotels.com" not in result

    def test_no_plus_n_more(self):
        """Compact format should NOT show '+N more'."""
        alert = _make_alert()
        result = _format_alert_compact(alert)
        assert "+1 more" not in result
        assert "+2 more" not in result

    def test_shows_extras(self):
        alert = _make_alert()
        result = _format_alert_compact(alert)
        assert "✅" in result  # first deal is cancellable

    def test_single_deal_no_extras(self):
        alert = _make_alert(
            details=[
                {
                    "platform": "Agoda",
                    "price": 44000,
                    "currency": "JPY",
                    "percentage_diff": -12.0,
                    "is_cancellable": False,
                    "breakfast_included": False,
                }
            ]
        )
        result = _format_alert_compact(alert)
        assert "Agoda" in result
        assert "44,000" in result
        assert "✅" not in result
        assert "🍳" not in result


# ── Detailed format ─────────────────────────────────────


class TestFormatAlertBlock:
    def test_shows_all_vendors(self):
        alert = _make_alert()
        result = _format_alert_block(alert)
        assert "Booking.com" in result
        assert "Hotels.com" in result

    def test_includes_booking_context(self):
        alert = _make_alert()
        result = _format_alert_block(alert)
        assert "Your price" in result
        assert "Dates" in result

    def test_includes_extras(self):
        alert = _make_alert()
        result = _format_alert_block(alert)
        assert "cancel" in result
        assert "bfast" in result


# ── Header ──────────────────────────────────────────────


class TestBuildHeader:
    def test_header_includes_counts(self):
        alerts = [
            _make_alert(severity="urgent"),
            _make_alert(severity="important"),
            _make_alert(severity="info"),
        ]
        header = _build_header(alerts)
        assert "3" in header
        assert "🔴" in header
        assert "🟡" in header
        assert "🔵" in header


# ── _build_messages strategy ────────────────────────────


class TestBuildMessages:
    def test_single_detailed_message_when_short(self):
        """One small alert → detailed format, one message."""
        alerts = [_make_alert()]
        msgs = _build_messages(alerts)
        assert len(msgs) == 1
        assert "Hotels.com" in msgs[0]  # detailed includes all vendors
        assert "Booking.com" in msgs[0]

    @patch("hotel_agent.notifications.telegram._create_telegraph_page")
    def test_falls_back_to_compact_plus_telegraph(self, mock_telegraph: MagicMock):
        """Many alerts → compact format + Telegraph link."""
        mock_telegraph.return_value = "https://telegra.ph/test-page"
        # Create enough alerts to exceed 4096 chars in detailed mode
        alerts = [
            _make_alert(title=f"Price drop: Hotel {i} Very Long Name Resort and Spa")
            for i in range(30)
        ]
        msgs = _build_messages(alerts)
        assert len(msgs) == 1
        assert "telegra.ph" in msgs[0]
        mock_telegraph.assert_called_once()

    @patch("hotel_agent.notifications.telegram._create_telegraph_page")
    def test_fallback_when_telegraph_fails(self, mock_telegraph: MagicMock):
        """If Telegraph fails, compact-only with truncation."""
        mock_telegraph.return_value = None
        alerts = [
            _make_alert(title=f"Price drop: Hotel {i} Very Long Name Resort") for i in range(30)
        ]
        msgs = _build_messages(alerts)
        assert len(msgs) == 1
        assert "telegra.ph" not in msgs[0]
        assert len(msgs[0]) <= 4096


# ── Telegraph content ───────────────────────────────────


class TestBuildTelegraphContent:
    def test_returns_dom_nodes(self):
        alerts = [_make_alert()]
        nodes = _build_telegraph_content(alerts)
        assert isinstance(nodes, list)
        assert len(nodes) > 0
        # Should contain h4 for alert title
        h4_nodes = [n for n in nodes if isinstance(n, dict) and n.get("tag") == "h4"]
        assert len(h4_nodes) >= 1
        assert "Hotel Grand Tokyo" in str(h4_nodes[0])

    def test_includes_all_vendors(self):
        alert = _make_alert()
        nodes = _build_telegraph_content([alert])
        text = str(nodes)
        assert "Booking.com" in text
        assert "Hotels.com" in text

    def test_includes_vendor_links(self):
        alert = _make_alert()
        nodes = _build_telegraph_content([alert])
        # Find anchor tags
        a_nodes = [n for n in nodes if isinstance(n, dict) and n.get("tag") == "p"]
        text = str(a_nodes)
        assert "booking.com/hotel-grand" in text


class TestCreateTelegraphPage:
    @patch("hotel_agent.notifications.telegram._get_telegraph_token")
    @patch("hotel_agent.notifications.telegram.requests.post")
    def test_creates_page_successfully(self, mock_post: MagicMock, mock_token: MagicMock):
        mock_token.return_value = "fake-token"
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"ok": True, "result": {"url": "https://telegra.ph/test-123"}}
        mock_post.return_value = mock_resp

        url = _create_telegraph_page([_make_alert()])
        assert url == "https://telegra.ph/test-123"

    @patch("hotel_agent.notifications.telegram._get_telegraph_token")
    @patch("hotel_agent.notifications.telegram.requests.post")
    def test_returns_none_on_api_error(self, mock_post: MagicMock, mock_token: MagicMock):
        mock_token.return_value = "fake-token"
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"ok": False, "error": "bad request"}
        mock_post.return_value = mock_resp

        url = _create_telegraph_page([_make_alert()])
        assert url is None

    @patch("hotel_agent.notifications.telegram._get_telegraph_token")
    def test_returns_none_on_exception(self, mock_token: MagicMock):
        mock_token.side_effect = RuntimeError("no network")
        url = _create_telegraph_page([_make_alert()])
        assert url is None


# ── send_telegram_message ───────────────────────────────


class TestSendTelegramMessage:
    @patch("hotel_agent.notifications.telegram.requests.post")
    def test_sends_message(self, mock_post: MagicMock):
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_post.return_value = mock_resp

        cfg = _make_config()
        result = send_telegram_message(cfg, "hello")
        assert result is True
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        assert call_kwargs[1]["json"]["text"] == "hello"

    def test_returns_false_when_not_configured(self):
        cfg = _make_config(
            telegram_bot_token=SecretStr(""),
            telegram_chat_id=SecretStr(""),
        )
        result = send_telegram_message(cfg, "hello")
        assert result is False

    @patch("hotel_agent.notifications.telegram.requests.post")
    def test_returns_false_on_api_error(self, mock_post: MagicMock):
        mock_resp = MagicMock()
        mock_resp.ok = False
        mock_resp.status_code = 400
        mock_resp.text = "Bad Request"
        mock_post.return_value = mock_resp

        cfg = _make_config()
        result = send_telegram_message(cfg, "hello")
        assert result is False


# ── notify_alerts ───────────────────────────────────────


class TestNotifyAlerts:
    @patch("hotel_agent.notifications.telegram._build_messages")
    @patch("hotel_agent.notifications.telegram.send_telegram_message")
    def test_sends_pending_alerts(self, mock_send: MagicMock, mock_build: MagicMock):
        mock_build.return_value = ["message1"]
        mock_send.return_value = True

        cfg = _make_config()
        alerts = [_make_alert(notified_telegram=False)]
        count = notify_alerts(cfg, alerts)
        assert count == 1
        mock_send.assert_called_once_with(cfg, "message1")

    def test_skips_when_disabled(self):
        cfg = _make_config()
        cfg.notifications.telegram.enabled = False
        count = notify_alerts(cfg, [_make_alert()])
        assert count == 0

    @patch("hotel_agent.notifications.telegram._build_messages")
    @patch("hotel_agent.notifications.telegram.send_telegram_message")
    def test_skips_already_notified(self, mock_send: MagicMock, mock_build: MagicMock):
        cfg = _make_config()
        alerts = [_make_alert(notified_telegram=True)]
        count = notify_alerts(cfg, alerts)
        assert count == 0
        mock_send.assert_not_called()


# ── Convenience functions ───────────────────────────────


class TestConvenienceFunctions:
    def test_format_consolidated_message(self):
        alerts = [_make_alert()]
        msg = format_consolidated_message(alerts)
        assert "Hotel Grand Tokyo" in msg
        assert len(msg) > 0

    def test_format_alert_message(self):
        alert = _make_alert()
        msg = format_alert_message(alert)
        assert "Hotel Grand Tokyo" in msg
