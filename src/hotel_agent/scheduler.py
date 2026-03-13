"""Configurable scheduler that runs the pipeline on a timer.

State is persisted to a JSON file alongside the database so the
scheduler auto-resumes after a server restart.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable
    from contextlib import AbstractContextManager

    from .config import AppConfig
    from .db import Database

log = logging.getLogger(__name__)

_WEEKDAY_MAP = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


# ── Schedule configuration ──────────────────────────────


@dataclass
class ScheduleConfig:
    """Persisted scheduler configuration."""

    active: bool = False
    mode: str = "interval"  # "interval" | "daily" | "weekly"

    # interval mode
    interval_value: int = 12
    interval_unit: str = "hours"  # "hours" | "days"

    # daily mode
    daily_time: str = "08:00"

    # weekly mode
    weekly_days: list[str] = field(default_factory=lambda: ["monday", "friday"])
    weekly_time: str = "08:00"

    # bookkeeping
    last_run_at: str = ""
    next_run_at: str = ""
    last_digest_at: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> ScheduleConfig:
        known = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in known}
        return cls(**filtered)


def _parse_time(t: str) -> tuple[int, int]:
    """Parse 'HH:MM' -> (hour, minute)."""
    parts = t.split(":")
    return int(parts[0]), int(parts[1])


def compute_next_run(cfg: ScheduleConfig, now: datetime | None = None) -> datetime:
    """Calculate the next run time from *now* given the schedule config."""
    now = now or datetime.now()

    if cfg.mode == "interval":
        if cfg.interval_unit == "days":
            delta = timedelta(days=cfg.interval_value)
        else:
            delta = timedelta(hours=cfg.interval_value)

        if cfg.last_run_at:
            last = datetime.fromisoformat(cfg.last_run_at)
            candidate = last + delta
            if candidate > now:
                return candidate
        # No last run or it's overdue — run soon (1 minute grace)
        return now + timedelta(minutes=1)

    if cfg.mode == "daily":
        h, m = _parse_time(cfg.daily_time)
        today_at = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if today_at > now:
            return today_at
        return today_at + timedelta(days=1)

    if cfg.mode == "weekly":
        h, m = _parse_time(cfg.weekly_time)
        target_weekdays = sorted(
            _WEEKDAY_MAP[d.lower()] for d in cfg.weekly_days if d.lower() in _WEEKDAY_MAP
        )
        if not target_weekdays:
            target_weekdays = [0]  # fallback Monday

        for day_offset in range(8):
            candidate = now + timedelta(days=day_offset)
            if candidate.weekday() in target_weekdays:
                at = candidate.replace(hour=h, minute=m, second=0, microsecond=0)
                if at > now:
                    return at
        # Fallback
        return now + timedelta(days=1)

    # Unknown mode — default to 12h
    return now + timedelta(hours=12)


# ── Scheduler engine ────────────────────────────────────


class Scheduler:
    """Background thread that runs the pipeline on a schedule."""

    def __init__(
        self,
        config: AppConfig,
        get_db: Callable[[], AbstractContextManager[Database]],
        state_path: str | Path,
    ):
        self._app_config = config
        self._get_db = get_db
        self._state_path = Path(state_path)
        self._sched: ScheduleConfig = ScheduleConfig()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._on_run_start: Callable[[], None] | None = None
        self._on_run_end: Callable[[dict], None] | None = None
        self._on_progress: Callable[[str, dict], None] | None = None
        self.load_state()

    # ── State persistence ───────────────────────────

    def load_state(self) -> None:
        if self._state_path.exists():
            try:
                data = json.loads(self._state_path.read_text(encoding="utf-8"))
                self._sched = ScheduleConfig.from_dict(data)
                log.info(
                    "Scheduler state loaded: active=%s, mode=%s",
                    self._sched.active,
                    self._sched.mode,
                )
            except Exception:
                log.warning("Failed to load scheduler state, using defaults")
                self._sched = ScheduleConfig()
        else:
            self._sched = ScheduleConfig()

    def save_state(self) -> None:
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        self._state_path.write_text(
            json.dumps(self._sched.to_dict(), indent=2),
            encoding="utf-8",
        )

    # ── Public API ──────────────────────────────────

    @property
    def schedule_config(self) -> ScheduleConfig:
        return self._sched

    @schedule_config.setter
    def schedule_config(self, cfg: ScheduleConfig) -> None:
        self._sched = cfg
        self.save_state()

    @property
    def is_active(self) -> bool:
        return self._sched.active and self._thread is not None and self._thread.is_alive()

    @property
    def next_run_at(self) -> str:
        return self._sched.next_run_at

    @property
    def last_run_at(self) -> str:
        return self._sched.last_run_at

    def start(self) -> None:
        """Activate the scheduler and start the background thread."""
        if self._thread is not None and self._thread.is_alive():
            log.warning("Scheduler already running")
            return

        self._sched.active = True
        self._sched.next_run_at = compute_next_run(self._sched).isoformat()
        self.save_state()

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        log.info("Scheduler started, next run at %s", self._sched.next_run_at)

    def stop(self) -> None:
        """Deactivate the scheduler and stop the background thread."""
        self._sched.active = False
        self.save_state()
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
        log.info("Scheduler stopped")

    def update_config(self, cfg: ScheduleConfig) -> None:
        """Update schedule settings (without changing active/last_run_at)."""
        was_active = self.is_active
        cfg.active = self._sched.active
        cfg.last_run_at = self._sched.last_run_at
        self._sched = cfg
        self._sched.next_run_at = compute_next_run(self._sched).isoformat()
        self.save_state()
        # Restart the thread so it picks up the new timing
        if was_active:
            self._stop_event.set()
            if self._thread is not None:
                self._thread.join(timeout=5)
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._loop, daemon=True)
            self._thread.start()

    # ── Background loop ─────────────────────────────

    def _loop(self) -> None:
        from .pipeline import pipeline_lock, run_pipeline

        while not self._stop_event.is_set():
            next_dt = compute_next_run(self._sched)
            self._sched.next_run_at = next_dt.isoformat()
            self.save_state()

            # Sleep until next run (interruptible)
            wait_seconds = max(0, (next_dt - datetime.now()).total_seconds())
            if wait_seconds > 0:
                log.debug("Scheduler sleeping %.0f seconds until %s", wait_seconds, next_dt)
                if self._stop_event.wait(timeout=wait_seconds):
                    break  # stop() was called

            if self._stop_event.is_set():
                break

            # Try to acquire pipeline lock
            if not pipeline_lock.acquire(blocking=False):
                log.info("Scheduler: pipeline busy, skipping this cycle")
                # Wait a bit then try next cycle
                self._stop_event.wait(timeout=60)
                continue

            try:
                log.info("Scheduler: starting pipeline run")
                if self._on_run_start:
                    self._on_run_start()

                result = run_pipeline(
                    self._app_config,
                    self._get_db,
                    on_progress=self._on_progress,
                )

                self._sched.last_run_at = datetime.now().isoformat()
                self.save_state()

                summary = {
                    "scrape_total": result.scrape_total,
                    "scrape_success": result.scrape_success,
                    "scrape_failed": result.scrape_failed,
                    "new_alerts": result.new_alerts,
                    "notifications_sent": result.notifications_sent,
                }
                log.info("Scheduler: pipeline completed — %s", summary)
                if self._on_run_end:
                    self._on_run_end(summary)

                # Check if digest email is due
                self._maybe_send_digest()

            except Exception:
                log.exception("Scheduler: pipeline run crashed")
                self._sched.last_run_at = datetime.now().isoformat()
                self.save_state()
            finally:
                pipeline_lock.release()

            # Small delay before computing next cycle
            time.sleep(1)

    def _maybe_send_digest(self) -> None:
        """Send a digest email if the configured digest time has passed since the last digest."""
        if not self._app_config.notifications.email.digest_enabled:
            return

        now = datetime.now()
        h, m = _parse_time(self._app_config.notifications.email.digest_time)
        digest_time_today = now.replace(hour=h, minute=m, second=0, microsecond=0)

        # Only send if we're past the digest time today
        if now < digest_time_today:
            return

        # Only send once per day
        if self._sched.last_digest_at:
            last = datetime.fromisoformat(self._sched.last_digest_at)
            if last.date() >= now.date():
                return

        # Get alerts since last digest
        since = self._sched.last_digest_at or (now - timedelta(days=1)).isoformat()
        try:
            with self._get_db() as db:
                alerts = db.get_alerts_since(since)

            if not alerts:
                log.info("Scheduler: no alerts since last digest, skipping")
                self._sched.last_digest_at = now.isoformat()
                self.save_state()
                return

            # Generate LLM summary
            summary = self._generate_digest_summary(alerts)

            from .notifications.email import send_digest_email

            if send_digest_email(self._app_config, alerts, summary=summary):
                log.info("Scheduler: digest email sent with %d alerts", len(alerts))
            else:
                log.warning("Scheduler: digest email failed")

            self._sched.last_digest_at = now.isoformat()
            self.save_state()

        except Exception:
            log.exception("Scheduler: digest email crashed")

    def _generate_digest_summary(self, alerts: list) -> str:
        """Use LLM to generate a brief summary of the alerts for the digest."""
        try:
            from .llm.client import call_llm

            alert_texts = []
            for a in alerts[:20]:  # limit to avoid token overflow
                alert_texts.append(
                    f"- [{a.severity}] {a.title}: savings {a.price_diff:,.0f} ({a.percentage_diff:.1f}%)"
                )

            prompt = (
                "Summarize these hotel price alerts in 2-3 sentences. "
                "Focus on the best deals and most important findings. "
                "Be concise and actionable.\n\n" + "\n".join(alert_texts)
            )

            return call_llm(self._app_config, prompt, temperature=0.3, max_tokens=200)
        except Exception:
            log.warning("Scheduler: LLM summary generation failed, sending digest without summary")
            return ""
