"""Tests for hotel_agent.scheduler module."""

import json
from contextlib import nullcontext
from datetime import datetime, timedelta
from unittest.mock import patch

from hotel_agent.config import AppConfig
from hotel_agent.scheduler import ScheduleConfig, Scheduler, compute_next_run

# ── Helpers ────────────────────────────────────────────────


def _make_config(**kwargs) -> ScheduleConfig:
    """Create a ScheduleConfig with sensible defaults, overridable via kwargs."""
    defaults = dict(
        active=False,
        mode="interval",
        interval_value=12,
        interval_unit="hours",
        daily_time="08:00",
        weekly_days=["monday", "friday"],
        weekly_time="08:00",
        last_run_at="",
        next_run_at="",
    )
    defaults.update(kwargs)
    return ScheduleConfig(**defaults)


def _make_app_config(tmp_path) -> AppConfig:
    """Create a minimal AppConfig for Scheduler tests."""
    cfg = AppConfig()
    cfg.db_path = str(tmp_path / "test.db")
    return cfg


def _get_db():
    """Dummy get_db callable that returns a no-op context manager."""
    return nullcontext()


# ── ScheduleConfig ─────────────────────────────────────────


class TestScheduleConfig:
    """Tests for ScheduleConfig dataclass serialization."""

    def test_to_dict_returns_all_fields(self):
        cfg = ScheduleConfig()
        d = cfg.to_dict()
        assert d["active"] is False
        assert d["mode"] == "interval"
        assert d["interval_value"] == 12
        assert d["interval_unit"] == "hours"
        assert d["daily_time"] == "08:00"
        assert d["weekly_days"] == ["monday", "friday"]
        assert d["weekly_time"] == "08:00"
        assert d["last_run_at"] == ""
        assert d["next_run_at"] == ""

    def test_to_dict_from_dict_roundtrip(self):
        original = _make_config(
            active=True,
            mode="daily",
            daily_time="14:30",
            last_run_at="2025-01-15T10:00:00",
        )
        d = original.to_dict()
        restored = ScheduleConfig.from_dict(d)
        assert restored.active == original.active
        assert restored.mode == original.mode
        assert restored.daily_time == original.daily_time
        assert restored.last_run_at == original.last_run_at
        assert restored.to_dict() == original.to_dict()

    def test_from_dict_ignores_unknown_keys(self):
        data = {
            "active": True,
            "mode": "daily",
            "unknown_key": "should_be_ignored",
            "another_bad_key": 42,
        }
        cfg = ScheduleConfig.from_dict(data)
        assert cfg.active is True
        assert cfg.mode == "daily"
        assert not hasattr(cfg, "unknown_key")
        assert not hasattr(cfg, "another_bad_key")

    def test_from_dict_with_empty_dict_uses_defaults(self):
        cfg = ScheduleConfig.from_dict({})
        default = ScheduleConfig()
        assert cfg.to_dict() == default.to_dict()

    def test_from_dict_partial_data(self):
        cfg = ScheduleConfig.from_dict({"mode": "weekly", "weekly_time": "10:00"})
        assert cfg.mode == "weekly"
        assert cfg.weekly_time == "10:00"
        # Other fields keep defaults
        assert cfg.active is False
        assert cfg.interval_value == 12


# ── compute_next_run ───────────────────────────────────────


class TestComputeNextRunInterval:
    """Tests for compute_next_run() in interval mode."""

    def test_interval_hours_from_last_run(self):
        now = datetime(2025, 6, 15, 10, 0, 0)
        last = datetime(2025, 6, 15, 8, 0, 0)
        cfg = _make_config(
            mode="interval",
            interval_value=6,
            interval_unit="hours",
            last_run_at=last.isoformat(),
        )
        result = compute_next_run(cfg, now=now)
        expected = last + timedelta(hours=6)  # 14:00
        assert result == expected

    def test_interval_days_from_last_run(self):
        now = datetime(2025, 6, 15, 10, 0, 0)
        last = datetime(2025, 6, 14, 10, 0, 0)
        cfg = _make_config(
            mode="interval",
            interval_value=2,
            interval_unit="days",
            last_run_at=last.isoformat(),
        )
        result = compute_next_run(cfg, now=now)
        expected = last + timedelta(days=2)  # June 16 10:00
        assert result == expected

    def test_interval_no_last_run_returns_now_plus_1_min(self):
        now = datetime(2025, 6, 15, 10, 0, 0)
        cfg = _make_config(mode="interval", last_run_at="")
        result = compute_next_run(cfg, now=now)
        assert result == now + timedelta(minutes=1)

    def test_interval_overdue_returns_now_plus_1_min(self):
        """When last_run + interval is in the past, run in 1 minute."""
        now = datetime(2025, 6, 15, 20, 0, 0)
        last = datetime(2025, 6, 15, 6, 0, 0)  # 14 hours ago
        cfg = _make_config(
            mode="interval",
            interval_value=6,
            interval_unit="hours",
            last_run_at=last.isoformat(),
        )
        result = compute_next_run(cfg, now=now)
        assert result == now + timedelta(minutes=1)


class TestComputeNextRunDaily:
    """Tests for compute_next_run() in daily mode."""

    def test_daily_today_if_time_not_passed(self):
        now = datetime(2025, 6, 15, 7, 0, 0)  # 07:00
        cfg = _make_config(mode="daily", daily_time="08:00")
        result = compute_next_run(cfg, now=now)
        expected = now.replace(hour=8, minute=0, second=0, microsecond=0)
        assert result == expected

    def test_daily_tomorrow_if_time_passed(self):
        now = datetime(2025, 6, 15, 9, 0, 0)  # 09:00, past 08:00
        cfg = _make_config(mode="daily", daily_time="08:00")
        result = compute_next_run(cfg, now=now)
        expected = now.replace(hour=8, minute=0, second=0, microsecond=0) + timedelta(days=1)
        assert result == expected
        assert result.day == 16

    def test_daily_exact_time_returns_tomorrow(self):
        """If it's exactly 08:00:00, the daily_time is not > now, so tomorrow."""
        now = datetime(2025, 6, 15, 8, 0, 0)
        cfg = _make_config(mode="daily", daily_time="08:00")
        result = compute_next_run(cfg, now=now)
        assert result.day == 16

    def test_daily_custom_time(self):
        now = datetime(2025, 6, 15, 12, 0, 0)
        cfg = _make_config(mode="daily", daily_time="18:30")
        result = compute_next_run(cfg, now=now)
        expected = now.replace(hour=18, minute=30, second=0, microsecond=0)
        assert result == expected


class TestComputeNextRunWeekly:
    """Tests for compute_next_run() in weekly mode."""

    def test_weekly_next_weekday(self):
        # June 15, 2025 is a Sunday (weekday=6)
        now = datetime(2025, 6, 15, 10, 0, 0)
        cfg = _make_config(
            mode="weekly",
            weekly_days=["monday", "friday"],
            weekly_time="08:00",
        )
        result = compute_next_run(cfg, now=now)
        # Next Monday is June 16
        assert result == datetime(2025, 6, 16, 8, 0, 0)

    def test_weekly_same_day_future_time(self):
        # June 16, 2025 is a Monday (weekday=0)
        now = datetime(2025, 6, 16, 7, 0, 0)
        cfg = _make_config(
            mode="weekly",
            weekly_days=["monday"],
            weekly_time="09:00",
        )
        result = compute_next_run(cfg, now=now)
        assert result == datetime(2025, 6, 16, 9, 0, 0)

    def test_weekly_same_day_past_time_skips_to_next(self):
        # June 16, 2025 is a Monday
        now = datetime(2025, 6, 16, 10, 0, 0)
        cfg = _make_config(
            mode="weekly",
            weekly_days=["monday"],
            weekly_time="08:00",
        )
        result = compute_next_run(cfg, now=now)
        # Should skip to next Monday, June 23
        assert result == datetime(2025, 6, 23, 8, 0, 0)

    def test_weekly_skips_to_friday(self):
        # June 17, 2025 is a Tuesday (weekday=1)
        now = datetime(2025, 6, 17, 10, 0, 0)
        cfg = _make_config(
            mode="weekly",
            weekly_days=["friday"],
            weekly_time="08:00",
        )
        result = compute_next_run(cfg, now=now)
        # Next Friday is June 20
        assert result == datetime(2025, 6, 20, 8, 0, 0)

    def test_weekly_empty_days_falls_back_to_monday(self):
        now = datetime(2025, 6, 15, 10, 0, 0)  # Sunday
        cfg = _make_config(
            mode="weekly",
            weekly_days=[],
            weekly_time="08:00",
        )
        result = compute_next_run(cfg, now=now)
        # Fallback Monday → June 16
        assert result == datetime(2025, 6, 16, 8, 0, 0)


class TestComputeNextRunUnknownMode:
    """Tests for compute_next_run() with unknown mode."""

    def test_unknown_mode_defaults_to_12h(self):
        now = datetime(2025, 6, 15, 10, 0, 0)
        cfg = _make_config(mode="bogus_mode")
        result = compute_next_run(cfg, now=now)
        assert result == now + timedelta(hours=12)

    def test_empty_mode_defaults_to_12h(self):
        now = datetime(2025, 6, 15, 10, 0, 0)
        cfg = _make_config(mode="")
        result = compute_next_run(cfg, now=now)
        assert result == now + timedelta(hours=12)


# ── Scheduler ──────────────────────────────────────────────


class TestSchedulerStatePersistence:
    """Tests for Scheduler load_state / save_state JSON persistence."""

    def test_load_state_creates_default_if_no_file(self, tmp_path):
        state_path = tmp_path / "scheduler.json"
        app_cfg = _make_app_config(tmp_path)
        sched = Scheduler(app_cfg, _get_db, state_path)
        assert sched.schedule_config.active is False
        assert sched.schedule_config.mode == "interval"

    def test_save_state_creates_file(self, tmp_path):
        state_path = tmp_path / "scheduler.json"
        app_cfg = _make_app_config(tmp_path)
        sched = Scheduler(app_cfg, _get_db, state_path)
        sched.save_state()
        assert state_path.exists()
        data = json.loads(state_path.read_text(encoding="utf-8"))
        assert data["mode"] == "interval"

    def test_save_load_roundtrip(self, tmp_path):
        state_path = tmp_path / "scheduler.json"
        app_cfg = _make_app_config(tmp_path)
        sched = Scheduler(app_cfg, _get_db, state_path)

        # Modify config and save
        sched._sched.mode = "daily"
        sched._sched.daily_time = "14:00"
        sched._sched.last_run_at = "2025-06-15T10:00:00"
        sched.save_state()

        # Create a new scheduler from the same file
        sched2 = Scheduler(app_cfg, _get_db, state_path)
        assert sched2.schedule_config.mode == "daily"
        assert sched2.schedule_config.daily_time == "14:00"
        assert sched2.schedule_config.last_run_at == "2025-06-15T10:00:00"

    def test_load_state_uses_defaults_on_corrupt_json(self, tmp_path):
        state_path = tmp_path / "scheduler.json"
        state_path.write_text("{corrupt json!!!}", encoding="utf-8")
        app_cfg = _make_app_config(tmp_path)
        sched = Scheduler(app_cfg, _get_db, state_path)
        # Should fall back to defaults, not crash
        assert sched.schedule_config.mode == "interval"
        assert sched.schedule_config.active is False

    def test_save_state_creates_parent_directories(self, tmp_path):
        state_path = tmp_path / "subdir" / "deep" / "scheduler.json"
        app_cfg = _make_app_config(tmp_path)
        sched = Scheduler(app_cfg, _get_db, state_path)
        sched.save_state()
        assert state_path.exists()


class TestSchedulerStartStop:
    """Tests for Scheduler start / stop lifecycle."""

    def test_start_sets_active_and_saves(self, tmp_path):
        state_path = tmp_path / "scheduler.json"
        app_cfg = _make_app_config(tmp_path)
        sched = Scheduler(app_cfg, _get_db, state_path)

        with patch.object(sched, "_loop"):
            sched.start()

        assert sched.schedule_config.active is True
        # Verify it was persisted
        data = json.loads(state_path.read_text(encoding="utf-8"))
        assert data["active"] is True
        assert data["next_run_at"] != ""

        sched.stop()

    def test_stop_sets_inactive_and_saves(self, tmp_path):
        state_path = tmp_path / "scheduler.json"
        app_cfg = _make_app_config(tmp_path)
        sched = Scheduler(app_cfg, _get_db, state_path)

        with patch.object(sched, "_loop"):
            sched.start()
        sched.stop()

        assert sched.schedule_config.active is False
        data = json.loads(state_path.read_text(encoding="utf-8"))
        assert data["active"] is False

    def test_is_active_false_when_not_started(self, tmp_path):
        state_path = tmp_path / "scheduler.json"
        app_cfg = _make_app_config(tmp_path)
        sched = Scheduler(app_cfg, _get_db, state_path)
        assert sched.is_active is False

    def test_is_active_false_after_stop(self, tmp_path):
        state_path = tmp_path / "scheduler.json"
        app_cfg = _make_app_config(tmp_path)
        sched = Scheduler(app_cfg, _get_db, state_path)

        with patch.object(sched, "_loop"):
            sched.start()
        sched.stop()

        assert sched.is_active is False


class TestSchedulerUpdateConfig:
    """Tests for Scheduler.update_config()."""

    def test_update_config_preserves_active(self, tmp_path):
        state_path = tmp_path / "scheduler.json"
        app_cfg = _make_app_config(tmp_path)
        sched = Scheduler(app_cfg, _get_db, state_path)
        sched._sched.active = True
        sched.save_state()

        new_cfg = _make_config(mode="daily", daily_time="10:00", active=False)
        sched.update_config(new_cfg)

        # active should be preserved from the old config (True), not the new one
        assert sched.schedule_config.active is True
        assert sched.schedule_config.mode == "daily"
        assert sched.schedule_config.daily_time == "10:00"

    def test_update_config_preserves_last_run_at(self, tmp_path):
        state_path = tmp_path / "scheduler.json"
        app_cfg = _make_app_config(tmp_path)
        sched = Scheduler(app_cfg, _get_db, state_path)
        sched._sched.last_run_at = "2025-06-15T10:00:00"
        sched.save_state()

        new_cfg = _make_config(mode="weekly", last_run_at="")
        sched.update_config(new_cfg)

        assert sched.schedule_config.last_run_at == "2025-06-15T10:00:00"
        assert sched.schedule_config.mode == "weekly"

    def test_update_config_recalculates_next_run(self, tmp_path):
        state_path = tmp_path / "scheduler.json"
        app_cfg = _make_app_config(tmp_path)
        sched = Scheduler(app_cfg, _get_db, state_path)

        new_cfg = _make_config(mode="daily", daily_time="23:59")
        sched.update_config(new_cfg)

        assert sched.schedule_config.next_run_at != ""

    def test_update_config_saves_to_disk(self, tmp_path):
        state_path = tmp_path / "scheduler.json"
        app_cfg = _make_app_config(tmp_path)
        sched = Scheduler(app_cfg, _get_db, state_path)

        new_cfg = _make_config(mode="daily", daily_time="15:00")
        sched.update_config(new_cfg)

        data = json.loads(state_path.read_text(encoding="utf-8"))
        assert data["mode"] == "daily"
        assert data["daily_time"] == "15:00"


class TestSchedulerConfigProperty:
    """Tests for the schedule_config property setter."""

    def test_setter_saves_to_disk(self, tmp_path):
        state_path = tmp_path / "scheduler.json"
        app_cfg = _make_app_config(tmp_path)
        sched = Scheduler(app_cfg, _get_db, state_path)

        new_cfg = _make_config(mode="weekly", weekly_time="11:00")
        sched.schedule_config = new_cfg

        data = json.loads(state_path.read_text(encoding="utf-8"))
        assert data["mode"] == "weekly"
        assert data["weekly_time"] == "11:00"

    def test_setter_updates_in_memory(self, tmp_path):
        state_path = tmp_path / "scheduler.json"
        app_cfg = _make_app_config(tmp_path)
        sched = Scheduler(app_cfg, _get_db, state_path)

        new_cfg = _make_config(mode="daily", daily_time="06:00")
        sched.schedule_config = new_cfg

        assert sched.schedule_config.mode == "daily"
        assert sched.schedule_config.daily_time == "06:00"
