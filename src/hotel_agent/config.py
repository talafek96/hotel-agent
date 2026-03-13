"""Configuration management for hotel price tracker.

Uses pydantic-settings for env/.env loading and pydantic models for
validation.  Non-secret settings live in config.yaml; secrets live in
.env and are exposed as ``SecretStr`` fields so they never leak into
logs or tracebacks.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .models import TravelerComposition

log = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = Path("config.yaml")
EXAMPLE_CONFIG_PATH = Path("config.example.yaml")


# ── Sub-models (BaseModel, loaded from YAML) ───────────


class LLMConfig(BaseModel):
    provider: str = "openai"
    model: str = "gpt-4o-mini"


class CurrencyConfig(BaseModel):
    base: str = "USD"
    rates: dict[str, float] = {}

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


class PriceDropThresholds(BaseModel):
    min_absolute: float = 10.0
    min_percentage: float = 5.0


class UpgradeThresholds(BaseModel):
    max_extra_cost: float = 50.0
    max_extra_percentage: float = 10.0


class AlertThresholds(BaseModel):
    price_drop: PriceDropThresholds = PriceDropThresholds()
    upgrade: UpgradeThresholds = UpgradeThresholds()
    only_cancellable: bool = False


class TelegramNotifConfig(BaseModel):
    enabled: bool = False


class EmailNotifConfig(BaseModel):
    enabled: bool = False
    digest_time: str = "08:00"


class NotificationConfig(BaseModel):
    telegram: TelegramNotifConfig = TelegramNotifConfig()
    email: EmailNotifConfig = EmailNotifConfig()


# ── Top-level settings ──────────────────────────────────


class AppConfig(BaseSettings):
    """Top-level application configuration.

    Secrets are loaded automatically from environment variables / ``.env``
    by pydantic-settings.  Everything else is loaded from ``config.yaml``
    via :func:`load_config`.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        arbitrary_types_allowed=True,
    )

    # Non-secret settings (populated from YAML in load_config)
    travelers: TravelerComposition = TravelerComposition()
    llm: LLMConfig = LLMConfig()
    currency: CurrencyConfig = CurrencyConfig()
    alerts: AlertThresholds = AlertThresholds()
    notifications: NotificationConfig = NotificationConfig()
    db_path: str = "data/hotel_tracker.db"

    # Secrets (auto-loaded from env / .env by pydantic-settings)
    openai_api_key: SecretStr = SecretStr("")
    gemini_api_key: SecretStr = SecretStr("")
    anthropic_api_key: SecretStr = SecretStr("")
    serpapi_key: SecretStr = SecretStr("")
    telegram_bot_token: SecretStr = SecretStr("")
    telegram_chat_id: SecretStr = SecretStr("")
    gmail_user: SecretStr = SecretStr("")
    gmail_app_password: SecretStr = SecretStr("")

    @field_validator("travelers", mode="before")
    @classmethod
    def _parse_travelers(cls, v: object) -> TravelerComposition:
        if isinstance(v, dict):
            return TravelerComposition.from_dict(v)
        if isinstance(v, TravelerComposition):
            return v
        return TravelerComposition()


# ── Loading ─────────────────────────────────────────────


def load_config(config_path: Path | str = DEFAULT_CONFIG_PATH) -> AppConfig:
    """Load configuration from YAML file + environment variables.

    Priority (highest first): env vars > .env file > YAML > defaults.
    """
    load_dotenv()

    yaml_overrides: dict = {}

    path = Path(config_path)
    if not path.exists():
        if path == DEFAULT_CONFIG_PATH and EXAMPLE_CONFIG_PATH.exists():
            log.warning(
                "config.yaml not found. "
                "Copy config.example.yaml to config.yaml and adjust to your needs:\n"
                "  cp config.example.yaml config.yaml"
            )
    else:
        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

        # Travelers
        if "travelers" in raw:
            yaml_overrides["travelers"] = raw["travelers"]

        # LLM
        if "llm" in raw:
            yaml_overrides["llm"] = raw["llm"]

        # Currency
        if "currency" in raw:
            yaml_overrides["currency"] = raw["currency"]

        # Alerts (nested YAML → nested pydantic)
        if "alerts" in raw:
            yaml_overrides["alerts"] = raw["alerts"]

        # Notifications (nested YAML → nested pydantic)
        if "notifications" in raw:
            yaml_overrides["notifications"] = raw["notifications"]

        # Database
        if "database" in raw:
            yaml_overrides["db_path"] = raw["database"].get("path", "data/hotel_tracker.db")

    config = AppConfig(**yaml_overrides)
    return config


# ── Saving (YAML) ──────────────────────────────────────


def save_config(config: AppConfig, config_path: Path | str = DEFAULT_CONFIG_PATH) -> None:
    """Save non-secret configuration to a YAML file."""
    data: dict = {}

    # Travelers
    data["travelers"] = {
        "adults": config.travelers.adults,
        "children": config.travelers.children_ages,
    }

    # LLM
    data["llm"] = config.llm.model_dump()

    # Currency
    data["currency"] = config.currency.model_dump()

    # Alerts
    data["alerts"] = config.alerts.model_dump()

    # Notifications
    data["notifications"] = config.notifications.model_dump()

    # Database
    data["database"] = {"path": config.db_path}

    path = Path(config_path)
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    log.info("Configuration saved to %s", path)


# ── Saving (secrets → .env) ────────────────────────────


_SECRET_ENV_MAP = {
    "openai_api_key": "OPENAI_API_KEY",
    "gemini_api_key": "GEMINI_API_KEY",
    "anthropic_api_key": "ANTHROPIC_API_KEY",
    "serpapi_key": "SERPAPI_KEY",
    "telegram_bot_token": "TELEGRAM_BOT_TOKEN",
    "telegram_chat_id": "TELEGRAM_CHAT_ID",
    "gmail_user": "GMAIL_USER",
    "gmail_app_password": "GMAIL_APP_PASSWORD",
}


def save_secrets(config: AppConfig, env_path: Path | str = Path(".env")) -> None:
    """Write secret values to a .env file and update os.environ."""
    path = Path(env_path)

    lines: list[str] = []
    for attr, env_var in _SECRET_ENV_MAP.items():
        secret: SecretStr = getattr(config, attr)
        value = secret.get_secret_value()
        if value:
            lines.append(f"{env_var}={value}")
            os.environ[env_var] = value
        else:
            os.environ.pop(env_var, None)

    path.write_text("\n".join(lines) + "\n" if lines else "", encoding="utf-8")
    log.info("Secrets saved to %s", path)
