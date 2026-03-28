"""Tests for hotel_agent.config module."""

import os
from unittest.mock import patch

import pytest
import yaml

from hotel_agent.config import (
    AlertThresholds,
    AppConfig,
    CurrencyConfig,
    LLMConfig,
    NotificationConfig,
    load_config,
    save_config,
)

# ── Default Config Values ──────────────────────────────────


class TestDefaultConfig:
    """Tests for default configuration values."""

    def test_default_app_config(self):
        with patch.dict(os.environ, {}, clear=True):
            cfg = AppConfig(_env_file=None)
        assert cfg.db_path == "data/hotel_tracker.db"
        assert cfg.travelers.adults == 2
        assert cfg.travelers.children_ages == []
        assert cfg.openai_api_key.get_secret_value() == ""
        assert cfg.gemini_api_key.get_secret_value() == ""
        assert cfg.anthropic_api_key.get_secret_value() == ""

    def test_default_llm_config(self):
        llm = LLMConfig()
        assert llm.provider == "openai"
        assert llm.model == "gpt-4o-mini"

    def test_default_currency_config(self):
        cc = CurrencyConfig()
        assert cc.base == "USD"
        assert cc.rates == {}

    def test_default_alert_thresholds(self):
        at = AlertThresholds()
        assert at.price_drop.min_absolute == 10.0
        assert at.price_drop.min_percentage == 5.0
        assert at.upgrade.max_extra_cost == 50.0
        assert at.upgrade.max_extra_percentage == 10.0

    def test_default_notification_config(self):
        nc = NotificationConfig()
        assert nc.telegram.enabled is False
        assert nc.email.triggered_enabled is False
        assert nc.email.digest_enabled is False
        assert nc.email.digest_time == "08:00"


# ── Currency Conversion ───────────────────────────────────


class TestCurrencyConversion:
    """Tests for currency conversion."""

    def test_convert_jpy_to_ils(self):
        cc = CurrencyConfig(base="ILS", rates={"JPY_to_ILS": 0.0196008})
        result = cc.convert(100000, "JPY")
        expected = 100000 * 0.0196008
        assert result == pytest.approx(expected)

    def test_convert_usd_to_ils(self):
        cc = CurrencyConfig(base="ILS", rates={"USD_to_ILS": 3.0912})
        result = cc.convert(100, "USD")
        expected = 100 * 3.0912
        assert result == pytest.approx(expected)

    def test_convert_same_currency(self):
        cc = CurrencyConfig(base="USD")
        result = cc.convert(500, "USD")
        assert result == 500

    def test_convert_unknown_currency_raises(self):
        cc = CurrencyConfig(base="USD")
        with pytest.raises(ValueError, match="No conversion rate"):
            cc.convert(100, "EUR")

    def test_convert_zero_amount(self):
        cc = CurrencyConfig(base="ILS", rates={"JPY_to_ILS": 0.0196008})
        result = cc.convert(0, "JPY")
        assert result == 0.0

    def test_convert_with_custom_rates(self):
        cc = CurrencyConfig(
            base="USD",
            rates={"EUR_to_USD": 1.08},
        )
        result = cc.convert(100, "EUR")
        assert result == pytest.approx(108.0)


# ── Load Config from YAML ─────────────────────────────────


class TestLoadConfig:
    """Tests for loading configuration from YAML files."""

    def test_load_nonexistent_file_returns_defaults(self, tmp_path):
        """Loading from a non-existent file should return default config."""
        with patch.dict(os.environ, {}, clear=True):
            cfg = load_config(tmp_path / "nonexistent.yaml")
        assert cfg.travelers.adults == 2
        assert cfg.llm.provider == "openai"

    def test_load_empty_yaml(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text("", encoding="utf-8")
        with patch.dict(os.environ, {}, clear=True):
            cfg = load_config(config_file)
        assert cfg.travelers.adults == 2

    def test_load_travelers(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        data = {
            "travelers": {
                "adults": 3,
                "children": [2, 8],
            },
        }
        config_file.write_text(yaml.dump(data), encoding="utf-8")
        with patch.dict(os.environ, {}, clear=True):
            cfg = load_config(config_file)
        assert cfg.travelers.adults == 3
        assert cfg.travelers.children_ages == [2, 8]

    def test_load_llm(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        data = {
            "llm": {
                "provider": "gemini",
                "model": "gemini-pro",
            },
        }
        config_file.write_text(yaml.dump(data), encoding="utf-8")
        with patch.dict(os.environ, {}, clear=True):
            cfg = load_config(config_file)
        assert cfg.llm.provider == "gemini"
        assert cfg.llm.model == "gemini-pro"

    def test_load_llm_backward_compat(self, tmp_path):
        """Old configs with extraction_model should fall back gracefully."""
        config_file = tmp_path / "config.yaml"
        data = {
            "llm": {
                "provider": "openai",
                "extraction_model": "gpt-4o",
            },
        }
        config_file.write_text(yaml.dump(data), encoding="utf-8")
        with patch.dict(os.environ, {}, clear=True):
            cfg = load_config(config_file)
        # extraction_model is an unknown field, pydantic ignores it
        # model should be default since "model" key wasn't in YAML
        assert cfg.llm.provider == "openai"

    def test_load_currency(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        data = {
            "currency": {
                "base": "USD",
                "rates": {"EUR_to_USD": 1.08},
            },
        }
        config_file.write_text(yaml.dump(data), encoding="utf-8")
        with patch.dict(os.environ, {}, clear=True):
            cfg = load_config(config_file)
        assert cfg.currency.base == "USD"
        assert cfg.currency.rates == {"EUR_to_USD": 1.08}

    def test_load_alert_thresholds(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        data = {
            "alerts": {
                "price_drop": {
                    "min_absolute": 20,
                    "min_percentage": 8,
                },
                "upgrade": {
                    "max_extra_cost": 100,
                    "max_extra_percentage": 15,
                },
            },
        }
        config_file.write_text(yaml.dump(data), encoding="utf-8")
        with patch.dict(os.environ, {}, clear=True):
            cfg = load_config(config_file)
        assert cfg.alerts.price_drop.min_absolute == 20
        assert cfg.alerts.price_drop.min_percentage == 8
        assert cfg.alerts.upgrade.max_extra_cost == 100
        assert cfg.alerts.upgrade.max_extra_percentage == 15

    def test_load_notifications(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        data = {
            "notifications": {
                "telegram": {"enabled": True},
                "email": {"triggered_enabled": True, "digest_time": "09:30"},
            },
        }
        config_file.write_text(yaml.dump(data), encoding="utf-8")
        with patch.dict(os.environ, {}, clear=True):
            cfg = load_config(config_file)
        assert cfg.notifications.telegram.enabled is True
        assert cfg.notifications.email.triggered_enabled is True
        assert cfg.notifications.email.digest_time == "09:30"

    def test_load_database_path(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        data = {
            "database": {"path": "/custom/path.db"},
        }
        config_file.write_text(yaml.dump(data), encoding="utf-8")
        with patch.dict(os.environ, {}, clear=True):
            cfg = load_config(config_file)
        assert cfg.db_path == "/custom/path.db"

    def test_load_full_config(self, tmp_path):
        """Test loading a complete YAML config."""
        config_file = tmp_path / "config.yaml"
        data = {
            "travelers": {"adults": 2, "children": [4, 7]},
            "llm": {"provider": "openai", "model": "gpt-4o"},
            "currency": {"base": "ILS", "rates": {"JPY_to_ILS": 0.02}},
            "database": {"path": "my_db.db"},
        }
        config_file.write_text(yaml.dump(data), encoding="utf-8")
        with patch.dict(os.environ, {}, clear=True):
            cfg = load_config(config_file)
        assert cfg.travelers.adults == 2
        assert cfg.travelers.children_ages == [4, 7]
        assert cfg.llm.model == "gpt-4o"
        assert cfg.currency.rates["JPY_to_ILS"] == 0.02
        assert cfg.db_path == "my_db.db"


# ── Environment Variables ──────────────────────────────────


class TestEnvVarLoading:
    """Tests for loading secrets from environment variables."""

    def test_openai_key_from_env(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text("", encoding="utf-8")
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test-env"}, clear=True):
            cfg = load_config(config_file)
        assert cfg.openai_api_key.get_secret_value() == "sk-test-env"

    def test_gemini_key_from_env(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text("", encoding="utf-8")
        with patch.dict(os.environ, {"GEMINI_API_KEY": "gemini-env-key"}, clear=True):
            cfg = load_config(config_file)
        assert cfg.gemini_api_key.get_secret_value() == "gemini-env-key"

    def test_anthropic_key_from_env(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text("", encoding="utf-8")
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "anthropic-env-key"}, clear=True):
            cfg = load_config(config_file)
        assert cfg.anthropic_api_key.get_secret_value() == "anthropic-env-key"

    def test_serpapi_key_from_env(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text("", encoding="utf-8")
        with patch.dict(os.environ, {"SERPAPI_KEY": "serpapi-env-key"}, clear=True):
            cfg = load_config(config_file)
        assert cfg.serpapi_key.get_secret_value() == "serpapi-env-key"

    def test_telegram_from_env(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text("", encoding="utf-8")
        env = {
            "TELEGRAM_BOT_TOKEN": "bot-token-123",
            "TELEGRAM_CHAT_ID": "chat-456",
        }
        with patch.dict(os.environ, env, clear=True):
            cfg = load_config(config_file)
        assert cfg.telegram_bot_token.get_secret_value() == "bot-token-123"
        assert cfg.telegram_chat_id.get_secret_value() == "chat-456"

    def test_gmail_from_env(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text("", encoding="utf-8")
        env = {
            "GMAIL_USER": "user@gmail.com",
            "GMAIL_APP_PASSWORD": "secret-password",
        }
        with patch.dict(os.environ, env, clear=True):
            cfg = load_config(config_file)
        assert cfg.gmail_user.get_secret_value() == "user@gmail.com"
        assert cfg.gmail_app_password.get_secret_value() == "secret-password"

    def test_missing_env_vars_default_empty(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text("", encoding="utf-8")
        with patch.dict(os.environ, {}, clear=True):
            cfg = load_config(config_file)
        assert cfg.openai_api_key.get_secret_value() == ""
        assert cfg.telegram_bot_token.get_secret_value() == ""
        assert cfg.gmail_user.get_secret_value() == ""

    def test_multiple_env_vars(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text("", encoding="utf-8")
        env = {
            "OPENAI_API_KEY": "sk-key",
            "GEMINI_API_KEY": "gem-key",
            "ANTHROPIC_API_KEY": "ant-key",
            "TELEGRAM_BOT_TOKEN": "bot-tok",
            "TELEGRAM_CHAT_ID": "chat-id",
            "GMAIL_USER": "user@test.com",
            "GMAIL_APP_PASSWORD": "pass",
        }
        with patch.dict(os.environ, env, clear=True):
            cfg = load_config(config_file)
        assert cfg.openai_api_key.get_secret_value() == "sk-key"
        assert cfg.gemini_api_key.get_secret_value() == "gem-key"
        assert cfg.anthropic_api_key.get_secret_value() == "ant-key"
        assert cfg.telegram_bot_token.get_secret_value() == "bot-tok"
        assert cfg.telegram_chat_id.get_secret_value() == "chat-id"
        assert cfg.gmail_user.get_secret_value() == "user@test.com"
        assert cfg.gmail_app_password.get_secret_value() == "pass"


# ── Save Config ───────────────────────────────────────────


class TestSaveConfig:
    """Tests for saving configuration to YAML."""

    def test_save_config_creates_file(self, tmp_path):
        cfg = AppConfig(_env_file=None)
        out = tmp_path / "out.yaml"
        save_config(cfg, out)
        assert out.exists()

    def test_save_config_roundtrip(self, tmp_path):
        cfg = AppConfig(_env_file=None)
        cfg.travelers.adults = 3
        cfg.travelers.children_ages = [4, 7]
        cfg.llm.provider = "anthropic"
        cfg.llm.model = "claude-3"
        cfg.currency.base = "ILS"
        cfg.currency.rates = {"JPY": 0.025, "USD": 3.6}
        cfg.alerts.price_drop.min_absolute = 500.0
        cfg.alerts.price_drop.min_percentage = 5.0
        cfg.notifications.telegram.enabled = True
        cfg.notifications.email.triggered_enabled = True
        cfg.notifications.email.digest_time = "09:00"
        cfg.db_path = "custom.db"

        out = tmp_path / "out.yaml"
        save_config(cfg, out)

        with patch.dict(os.environ, {}, clear=True):
            loaded = load_config(str(out))

        assert loaded.travelers.adults == 3
        assert loaded.travelers.children_ages == [4, 7]
        assert loaded.llm.provider == "anthropic"
        assert loaded.llm.model == "claude-3"
        assert loaded.currency.base == "ILS"
        assert loaded.currency.rates["JPY"] == pytest.approx(0.025)
        assert loaded.alerts.price_drop.min_absolute == pytest.approx(500.0)
        assert loaded.notifications.telegram.enabled is True
        assert loaded.notifications.email.digest_time == "09:00"
        assert loaded.db_path == "custom.db"

    def test_save_config_yaml_structure(self, tmp_path):
        cfg = AppConfig(_env_file=None)
        out = tmp_path / "out.yaml"
        save_config(cfg, out)

        with open(out) as f:
            data = yaml.safe_load(f)

        assert "travelers" in data
        assert "llm" in data
        assert "currency" in data
        assert "alerts" in data
        assert "notifications" in data
        assert "database" in data

    def test_excluded_platforms_roundtrip(self, tmp_path):
        """excluded_platforms should survive save → load."""
        cfg = AppConfig(_env_file=None)
        cfg.alerts.excluded_platforms = ["trivago", "kayak"]

        out = tmp_path / "config.yaml"
        save_config(cfg, out)

        with patch.dict(os.environ, {}, clear=True):
            loaded = load_config(out)

        assert loaded.alerts.excluded_platforms == ["trivago", "kayak"]

    def test_excluded_platforms_default_empty(self):
        """Default config has no excluded platforms."""
        cfg = AppConfig(_env_file=None)
        assert cfg.alerts.excluded_platforms == []
