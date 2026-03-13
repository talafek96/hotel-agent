"""Tests for the pipeline module."""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

from hotel_agent.config import AppConfig, NotificationConfig
from hotel_agent.db import Database
from hotel_agent.models import (
    Alert,
    Booking,
    Hotel,
    PriceSnapshot,
    TravelerComposition,
)
from hotel_agent.pipeline import PipelineResult, preflight_check, run_pipeline


def _get_db(db_path: str):
    """Factory that returns a Database context manager."""
    return Database(db_path)


def _make_config(tmp_path, **overrides) -> AppConfig:
    db_path = str(tmp_path / "test.db")
    cfg = AppConfig(
        db_path=db_path,
        travelers=TravelerComposition(adults=2, children_ages=[4]),
    )
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg


class TestPipelineResult:
    def test_defaults_are_zero(self):
        r = PipelineResult()
        assert r.scrape_total == 0
        assert r.scrape_success == 0
        assert r.scrape_failed == 0
        assert r.new_alerts == 0
        assert r.notifications_sent == 0
        assert r.warnings == []
        assert r.errors == []


class TestPreflightCheck:
    def test_no_serpapi_key(self, tmp_path):
        cfg = _make_config(tmp_path, serpapi_key="")
        db = Database(cfg.db_path)
        warnings = preflight_check(cfg, db)
        db.close()
        assert any("SERPAPI_KEY" in w for w in warnings)

    def test_no_active_bookings(self, tmp_path):
        cfg = _make_config(tmp_path, serpapi_key="test-key")
        db = Database(cfg.db_path)
        warnings = preflight_check(cfg, db)
        db.close()
        assert any("No active bookings" in w for w in warnings)

    def test_missing_dates_warning(self, tmp_path):
        cfg = _make_config(tmp_path, serpapi_key="test-key")
        db = Database(cfg.db_path)
        hotel_id = db.upsert_hotel(Hotel(name="Test", city="Tokyo"))
        db.upsert_booking(
            Booking(
                hotel_id=hotel_id,
                check_in=date(2026, 8, 1),
                check_out=date(2026, 8, 5),
                booked_price=100,
            )
        )
        # Mock get_active_bookings to return one with missing dates
        booking_no_dates = Booking(hotel_id=hotel_id, booked_price=100)
        with patch.object(db, "get_active_bookings", return_value=[booking_no_dates]):
            warnings = preflight_check(cfg, db)
        db.close()
        assert any("missing check-in" in w for w in warnings)

    def test_telegram_missing_token_warning(self, tmp_path):
        cfg = _make_config(
            tmp_path,
            serpapi_key="test-key",
            notifications=NotificationConfig(telegram_enabled=True),
            telegram_bot_token="",
            telegram_chat_id="",
        )
        db = Database(cfg.db_path)
        hotel_id = db.upsert_hotel(Hotel(name="Test", city="Tokyo"))
        db.upsert_booking(
            Booking(
                hotel_id=hotel_id,
                check_in=date(2026, 8, 1),
                check_out=date(2026, 8, 5),
                booked_price=100,
            )
        )
        warnings = preflight_check(cfg, db)
        db.close()
        assert any("Telegram" in w for w in warnings)

    def test_all_clear(self, tmp_path):
        cfg = _make_config(tmp_path, serpapi_key="test-key")
        db = Database(cfg.db_path)
        hotel_id = db.upsert_hotel(Hotel(name="Test", city="Tokyo"))
        db.upsert_booking(
            Booking(
                hotel_id=hotel_id,
                check_in=date(2026, 8, 1),
                check_out=date(2026, 8, 5),
                booked_price=100,
            )
        )
        warnings = preflight_check(cfg, db)
        db.close()
        assert warnings == []


class TestRunPipeline:
    def _seed_db(self, db_path: str) -> int:
        """Seed a hotel + booking, return booking_id."""
        db = Database(db_path)
        hotel_id = db.upsert_hotel(Hotel(name="Test Hotel", city="Tokyo"))
        booking_id = db.upsert_booking(
            Booking(
                hotel_id=hotel_id,
                check_in=date(2026, 8, 1),
                check_out=date(2026, 8, 5),
                room_type="Standard",
                booked_price=100000,
                currency="JPY",
                platform="booking.com",
            )
        )
        db.close()
        return booking_id

    def test_no_serpapi_key_skips_scraping(self, tmp_path):
        cfg = _make_config(tmp_path, serpapi_key="")
        self._seed_db(cfg.db_path)

        with (
            patch("hotel_agent.analysis.comparator.run_analysis", return_value=[]),
            patch("hotel_agent.notifications.telegram.notify_alerts", return_value=0),
        ):
            result = run_pipeline(cfg, lambda: Database(cfg.db_path))

        assert result.scrape_total == 0
        assert "scraping skipped" in result.errors[0].lower()

    @patch("hotel_agent.notifications.telegram.notify_alerts", return_value=0)
    @patch("hotel_agent.analysis.comparator.run_analysis", return_value=[])
    @patch("hotel_agent.api.serpapi_client.search_hotel_prices")
    def test_happy_path_scrape(self, mock_search, mock_analysis, mock_notify, tmp_path):
        from hotel_agent.api.serpapi_client import SerpAPIResult

        cfg = _make_config(tmp_path, serpapi_key="test-key")
        self._seed_db(cfg.db_path)

        snap = PriceSnapshot(
            hotel_id=1,
            check_in=date(2026, 8, 1),
            check_out=date(2026, 8, 5),
            room_type="Standard",
            platform="booking.com",
            price=90000,
            currency="JPY",
        )
        mock_search.return_value = SerpAPIResult(
            snapshots=[snap],
            matched_name="Test Hotel",
            matched_address="Tokyo",
            property_token="tok123",
            used_cached_token=True,
        )

        result = run_pipeline(cfg, lambda: Database(cfg.db_path))

        assert result.scrape_total == 1
        assert result.scrape_success == 1
        assert result.scrape_failed == 0
        mock_search.assert_called_once()
        mock_analysis.assert_called_once()

    @patch("hotel_agent.notifications.telegram.notify_alerts", return_value=0)
    @patch("hotel_agent.analysis.comparator.run_analysis", return_value=[])
    @patch("hotel_agent.api.serpapi_client.search_hotel_prices")
    def test_serpapi_error_is_caught(self, mock_search, mock_analysis, mock_notify, tmp_path):
        from hotel_agent.api.serpapi_client import SerpAPIError

        cfg = _make_config(tmp_path, serpapi_key="test-key")
        self._seed_db(cfg.db_path)

        mock_search.side_effect = SerpAPIError("API limit reached")

        result = run_pipeline(cfg, lambda: Database(cfg.db_path))

        assert result.scrape_total == 1
        assert result.scrape_failed == 1
        assert any("API limit" in e for e in result.errors)

    @patch("hotel_agent.notifications.telegram.notify_alerts", return_value=0)
    @patch("hotel_agent.analysis.comparator.run_analysis", return_value=[])
    @patch("hotel_agent.api.serpapi_client.search_hotel_prices")
    def test_hotel_filter(self, mock_search, mock_analysis, mock_notify, tmp_path):
        from hotel_agent.api.serpapi_client import SerpAPIResult

        cfg = _make_config(tmp_path, serpapi_key="test-key")

        db = Database(cfg.db_path)
        h1 = db.upsert_hotel(Hotel(name="Grand Hyatt", city="Tokyo"))
        h2 = db.upsert_hotel(Hotel(name="Hilton Osaka", city="Osaka"))
        db.upsert_booking(
            Booking(
                hotel_id=h1,
                check_in=date(2026, 8, 1),
                check_out=date(2026, 8, 5),
                booked_price=100000,
                currency="JPY",
            )
        )
        db.upsert_booking(
            Booking(
                hotel_id=h2,
                check_in=date(2026, 8, 1),
                check_out=date(2026, 8, 5),
                booked_price=80000,
                currency="JPY",
            )
        )
        db.close()

        mock_search.return_value = SerpAPIResult(snapshots=[], used_cached_token=True)

        result = run_pipeline(
            cfg,
            lambda: Database(cfg.db_path),
            hotel_filter="hyatt",
        )

        assert result.scrape_total == 1
        mock_search.assert_called_once()

    @patch("hotel_agent.notifications.telegram.notify_alerts", return_value=0)
    @patch("hotel_agent.analysis.comparator.run_analysis", return_value=[])
    @patch("hotel_agent.api.serpapi_client.search_hotel_prices")
    def test_progress_callback_called(self, mock_search, mock_analysis, mock_notify, tmp_path):
        from hotel_agent.api.serpapi_client import SerpAPIResult

        cfg = _make_config(tmp_path, serpapi_key="test-key")
        self._seed_db(cfg.db_path)
        mock_search.return_value = SerpAPIResult(snapshots=[], used_cached_token=True)

        progress_calls: list[tuple] = []

        def on_progress(step: str, detail: dict) -> None:
            progress_calls.append((step, detail))

        run_pipeline(cfg, lambda: Database(cfg.db_path), on_progress=on_progress)

        steps = [c[0] for c in progress_calls]
        assert "preflight" in steps
        assert "scraping" in steps
        assert "analyzing" in steps
        assert "notifying" in steps
        assert "done" in steps

    @patch("hotel_agent.notifications.telegram.notify_alerts", return_value=2)
    @patch("hotel_agent.analysis.comparator.run_analysis")
    @patch("hotel_agent.api.serpapi_client.search_hotel_prices")
    def test_notifications_counted(self, mock_search, mock_analysis, mock_notify, tmp_path):
        from hotel_agent.api.serpapi_client import SerpAPIResult

        cfg = _make_config(tmp_path, serpapi_key="test-key")
        self._seed_db(cfg.db_path)
        mock_search.return_value = SerpAPIResult(snapshots=[], used_cached_token=True)
        mock_analysis.return_value = [
            Alert(booking_id=1, snapshot_id=1, alert_type="price_drop", title="Test"),
        ]

        result = run_pipeline(cfg, lambda: Database(cfg.db_path))

        assert result.new_alerts == 1
        assert result.notifications_sent == 2

    @patch("hotel_agent.notifications.telegram.notify_alerts", return_value=0)
    @patch("hotel_agent.analysis.comparator.run_analysis", return_value=[])
    @patch("hotel_agent.llm.hotel_matcher.verify_hotel_match", return_value=False)
    @patch("hotel_agent.api.serpapi_client.search_hotel_prices")
    def test_llm_rejection_skips_hotel(
        self, mock_search, mock_verify, mock_analysis, mock_notify, tmp_path
    ):
        from hotel_agent.api.serpapi_client import SerpAPIResult

        cfg = _make_config(tmp_path, serpapi_key="test-key")
        self._seed_db(cfg.db_path)

        mock_search.return_value = SerpAPIResult(
            snapshots=[],
            matched_name="Wrong Hotel",
            matched_address="Wrong City",
            property_token="tok123",
            used_cached_token=False,
        )

        result = run_pipeline(cfg, lambda: Database(cfg.db_path))

        assert result.scrape_failed == 1
        assert any("not a match" in e for e in result.errors)
