"""Configuration management for hotel price tracker."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv

from .models import TravelerComposition

log = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = Path("config.yaml")
EXAMPLE_CONFIG_PATH = Path("config.example.yaml")


@dataclass
class LLMConfig:
    provider: str = "openai"
    model: str = "gpt-4o-mini"


@dataclass
class CurrencyConfig:
    base: str = "USD"
    rates: dict[str, float] = field(default_factory=dict)

    def convert(self, amount: float, from_currency: str) -> float:
        """Convert an amount to the base currency."""
        if from_currency == self.base:
            return amount
        key = f"{from_currency}_to_{self.base}"
        rate = self.rates.get(key)
        if rate is None:
            raise ValueError(
                f"No conversion rate for {from_currency} -> {self.base}. "
                f"Add '{key}' to currency.rates in config.yaml"
            )
        return amount * rate


@dataclass
class AlertThresholds:
    price_drop_min_absolute: float = 10.0
    price_drop_min_percentage: float = 5.0
    upgrade_max_extra_cost: float = 50.0
    upgrade_max_extra_percentage: float = 10.0
    only_cancellable: bool = False


@dataclass
class NotificationConfig:
    telegram_enabled: bool = False
    email_enabled: bool = False
    email_digest_time: str = "08:00"


@dataclass
class AppConfig:
    """Top-level application configuration."""

    travelers: TravelerComposition = field(default_factory=TravelerComposition)
    llm: LLMConfig = field(default_factory=LLMConfig)
    currency: CurrencyConfig = field(default_factory=CurrencyConfig)
    alerts: AlertThresholds = field(default_factory=AlertThresholds)
    notifications: NotificationConfig = field(default_factory=NotificationConfig)
    db_path: str = "data/hotel_tracker.db"

    # Secrets from .env
    openai_api_key: str = ""
    gemini_api_key: str = ""
    anthropic_api_key: str = ""
    serpapi_key: str = ""
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    gmail_user: str = ""
    gmail_app_password: str = ""


def load_config(config_path: Path | str = DEFAULT_CONFIG_PATH) -> AppConfig:
    """Load configuration from YAML file and environment variables."""
    load_dotenv()

    config = AppConfig()

    # Load YAML if it exists
    path = Path(config_path)
    if not path.exists():
        if path == DEFAULT_CONFIG_PATH and EXAMPLE_CONFIG_PATH.exists():
            log.warning(
                "config.yaml not found. "
                "Copy config.example.yaml to config.yaml and adjust to your needs:\n"
                "  cp config.example.yaml config.yaml"
            )
        # Fall through with defaults
    else:
        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

        # Travelers
        if "travelers" in raw:
            t = raw["travelers"]
            config.travelers = TravelerComposition(
                adults=t.get("adults", config.travelers.adults),
                children_ages=t.get("children", []) or [],
            )

        # LLM — use dataclass defaults as fallbacks
        if "llm" in raw:
            d_llm, llm = LLMConfig(), raw["llm"]
            config.llm = LLMConfig(
                provider=llm.get("provider", d_llm.provider),
                model=llm.get("model") or llm.get("extraction_model", d_llm.model),
            )

        # Currency
        if "currency" in raw:
            d_cur, c = CurrencyConfig(), raw["currency"]
            config.currency = CurrencyConfig(
                base=c.get("base", d_cur.base),
                rates=c.get("rates", {}),
            )

        # Alerts
        if "alerts" in raw:
            d_a = AlertThresholds()
            a = raw["alerts"]
            pd = a.get("price_drop", {})
            up = a.get("upgrade", {})
            config.alerts = AlertThresholds(
                price_drop_min_absolute=pd.get("min_absolute", d_a.price_drop_min_absolute),
                price_drop_min_percentage=pd.get("min_percentage", d_a.price_drop_min_percentage),
                upgrade_max_extra_cost=up.get("max_extra_cost", d_a.upgrade_max_extra_cost),
                upgrade_max_extra_percentage=up.get(
                    "max_extra_percentage", d_a.upgrade_max_extra_percentage
                ),
                only_cancellable=a.get("only_cancellable", d_a.only_cancellable),
            )

        # Notifications
        if "notifications" in raw:
            d_n = NotificationConfig()
            n = raw["notifications"]
            tg = n.get("telegram", {})
            em = n.get("email", {})
            config.notifications = NotificationConfig(
                telegram_enabled=tg.get("enabled", d_n.telegram_enabled),
                email_enabled=em.get("enabled", d_n.email_enabled),
                email_digest_time=em.get("digest_time", d_n.email_digest_time),
            )

        # Database
        if "database" in raw:
            config.db_path = raw["database"].get("path", config.db_path)

    # Load secrets from environment
    config.openai_api_key = os.environ.get("OPENAI_API_KEY", "")
    config.gemini_api_key = os.environ.get("GEMINI_API_KEY", "")
    config.anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    config.serpapi_key = os.environ.get("SERPAPI_KEY", "")
    config.telegram_bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    config.telegram_chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    config.gmail_user = os.environ.get("GMAIL_USER", "")
    config.gmail_app_password = os.environ.get("GMAIL_APP_PASSWORD", "")

    return config


def save_config(config: AppConfig, config_path: Path | str = DEFAULT_CONFIG_PATH) -> None:
    """Save non-secret configuration to a YAML file."""
    data: dict = {}

    # Travelers
    data["travelers"] = {
        "adults": config.travelers.adults,
        "children": config.travelers.children_ages,
    }

    # LLM
    data["llm"] = {
        "provider": config.llm.provider,
        "model": config.llm.model,
    }

    # Currency
    data["currency"] = {
        "base": config.currency.base,
        "rates": config.currency.rates,
    }

    # Alerts
    data["alerts"] = {
        "price_drop": {
            "min_absolute": config.alerts.price_drop_min_absolute,
            "min_percentage": config.alerts.price_drop_min_percentage,
        },
        "upgrade": {
            "max_extra_cost": config.alerts.upgrade_max_extra_cost,
            "max_extra_percentage": config.alerts.upgrade_max_extra_percentage,
        },
        "only_cancellable": config.alerts.only_cancellable,
    }

    # Notifications
    data["notifications"] = {
        "telegram": {"enabled": config.notifications.telegram_enabled},
        "email": {
            "enabled": config.notifications.email_enabled,
            "digest_time": config.notifications.email_digest_time,
        },
    }

    # Database
    data["database"] = {"path": config.db_path}

    path = Path(config_path)
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    log.info("Configuration saved to %s", path)
