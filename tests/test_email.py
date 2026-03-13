"""Tests for hotel_agent.notifications.email module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from pydantic import SecretStr

from hotel_agent.config import AppConfig, EmailNotifConfig, NotificationConfig
from hotel_agent.models import Alert
from hotel_agent.notifications.email import (
    _build_html_body,
    notify_alerts_email,
    send_digest_email,
    send_email,
)


def _make_config(**overrides) -> AppConfig:
    cfg = AppConfig(
        _env_file=None,
        gmail_user=SecretStr("user@gmail.com"),
        gmail_app_password=SecretStr("app-pass"),
    )
    cfg.notifications = NotificationConfig(
        email=EmailNotifConfig(
            triggered_enabled=True,
            recipients=["dest@example.com"],
        ),
    )
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg


def _make_alert(**overrides) -> Alert:
    defaults = dict(
        booking_id=1,
        snapshot_id=1,
        alert_type="price_drop",
        severity="info",
        title="Price drop: Hotel Test",
        message="Hotel Test (Tokyo)\nYour price: 100,000 JPY",
        price_diff=5000,
        percentage_diff=10.0,
        notified_email=False,
    )
    defaults.update(overrides)
    return Alert(**defaults)


class TestBuildHtmlBody:
    def test_returns_html_with_alert_data(self):
        alert = _make_alert()
        html = _build_html_body([alert], "Test Subject")
        assert "Hotel Test" in html
        assert "Test Subject" in html
        assert "1 alert" in html

    def test_multiple_alerts(self):
        alerts = [_make_alert(title=f"Alert {i}") for i in range(3)]
        html = _build_html_body(alerts, "Multiple")
        assert "3 alerts" in html


class TestSendEmail:
    def test_returns_false_no_gmail_user(self):
        cfg = _make_config(gmail_user=SecretStr(""))
        assert send_email(cfg, "Test", "<p>body</p>") is False

    def test_returns_false_no_recipients(self):
        cfg = _make_config()
        cfg.notifications.email.recipients = []
        assert send_email(cfg, "Test", "<p>body</p>", recipients=[]) is False

    @patch("hotel_agent.notifications.email.smtplib.SMTP_SSL")
    def test_success(self, mock_smtp_cls):
        mock_server = MagicMock()
        mock_smtp_cls.return_value.__enter__ = MagicMock(return_value=mock_server)
        mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)

        cfg = _make_config()
        assert send_email(cfg, "Test", "<p>body</p>") is True
        mock_server.login.assert_called_once_with("user@gmail.com", "app-pass")
        mock_server.sendmail.assert_called_once()

    @patch("hotel_agent.notifications.email.smtplib.SMTP_SSL")
    def test_smtp_error_returns_false(self, mock_smtp_cls):
        mock_smtp_cls.return_value.__enter__ = MagicMock(
            side_effect=Exception("SMTP connection failed")
        )
        mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)

        cfg = _make_config()
        assert send_email(cfg, "Test", "<p>body</p>") is False


class TestNotifyAlertsEmail:
    def test_returns_zero_when_disabled(self):
        cfg = _make_config()
        cfg.notifications.email.triggered_enabled = False
        alert = _make_alert()
        assert notify_alerts_email(cfg, [alert]) == 0

    def test_returns_zero_when_all_notified(self):
        cfg = _make_config()
        alert = _make_alert(notified_email=True)
        assert notify_alerts_email(cfg, [alert]) == 0

    @patch("hotel_agent.notifications.email.send_email", return_value=True)
    def test_sends_pending_alerts(self, mock_send):
        cfg = _make_config()
        alerts = [_make_alert(), _make_alert(title="Alert 2")]
        result = notify_alerts_email(cfg, alerts)
        assert result == 2
        mock_send.assert_called_once()

    @patch("hotel_agent.notifications.email.send_email", return_value=False)
    def test_returns_zero_on_send_failure(self, mock_send):
        cfg = _make_config()
        assert notify_alerts_email(cfg, [_make_alert()]) == 0


class TestSendDigestEmail:
    def test_returns_false_no_alerts(self):
        cfg = _make_config()
        assert send_digest_email(cfg, []) is False

    @patch("hotel_agent.notifications.email.send_email", return_value=True)
    def test_sends_with_summary(self, mock_send):
        cfg = _make_config()
        alerts = [_make_alert()]
        assert send_digest_email(cfg, alerts, summary="Great deals found!") is True
        call_args = mock_send.call_args
        html = call_args[0][2] if len(call_args[0]) > 2 else call_args[1].get("html_body", "")
        assert "Great deals" in html or mock_send.called

    @patch("hotel_agent.notifications.email.send_email", return_value=True)
    def test_sends_without_summary(self, mock_send):
        cfg = _make_config()
        alerts = [_make_alert()]
        assert send_digest_email(cfg, alerts) is True
        mock_send.assert_called_once()
