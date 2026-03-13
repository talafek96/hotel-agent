"""Tests for the pipeline module (scrape → analyze → notify)."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date
from unittest.mock import patch

import pytest

from hotel_agent.api.serpapi_client import SerpAPIError, SerpAPIResult
from hotel_agent.db import Database
from hotel_agent.models import Alert, Booking, Hotel, PriceSnapshot
from hotel_agent.pipeline import (
    PipelineResult,
    pipeline_lock,
    preflight_check,
    run_pipeline,
)


# ── Helpers ─────────────────────────────────────────────


def _make_get_db(db_path: str):
    """Context-manager factory matching the ``get_db`` signature expected by
    :func:`run_pipeline`."""

    @contextmanager
    def _get_db():
        db = Database(db_path)
        try:
            yield db
        finally:
            db.close()

    return _get_db


def _insert_hotel(db: Database, name: str = "Test Hotel", city: str = "Osaka") -> int:
    """Insert a hotel and return its id."""
    return db.upsert_hotel(
        Hotel(name=name, city=city, country="Japan", platform="Booking.com")
    )


def _insert_booking(db: Database, hotel_id: int, **overrides) -> int:
    """Insert an active booking and return its id."""
    defaults = dict(
        hotel_id=hotel_id,
        check_in=date(2026, 8, 31),
        check_out=date(2026, 9, 3),
        room_type="Standard Double",
        booked_price=135833,
        currency="JPY",
        is_cancellable=True,
        breakfast_included=False,
        platform="Agoda",
        status="active",
    )
    defaults.update(overrides)
    return db.add_booking(Booking(**defaults))


@pytest.fixture(autouse=True)
def _release_pipeline_lock():
    """Ensure the global pipeline lock is released after every test."""
    yield
    if pipeline_lock.locked():
        pipeline_lock.release()


# ── PipelineResult ──────────────────────────────────────


class TestPipelineResult:
    """PipelineResult dataclass should have sensible zero/empty defaults."""

    def test_defaults_are_zero_and_empty(self):
        r = PipelineResult()
        assert r.scrape_total == 0
        assert r.scrape_success == 0
        assert r.scrape_failed == 0
        assert r.new_alerts == 0
        assert r.notifications_sent == 0
        assert r.warnings == []
        assert r.errors == []

    def test_list_fields_are_independent_instances(self):
        """Each PipelineResult gets its own list objects (mutable default safety)."""
        a = PipelineResult()
        b = PipelineResult()
        a.warnings.append("oops")
        assert b.warnings == []


# ── preflight_check ─────────────────────────────────────


class TestPreflightCheck:
    """Tests for preflight_check()."""

    def test_no_serpapi_key_warns(self, tmp_db, config):
        config.serpapi_key = ""
        warnings = preflight_check(config, tmp_db)
        assert any("SERPAPI_KEY" in w for w in warnings)

    def test_no_active_bookings_warns(self, tmp_db, config):
        config.serpapi_key = "test-key"
        warnings = preflight_check(config, tmp_db)
        assert any("No active bookings" in w for w in warnings)

    def test_missing_dates_warns(self, tmp_db, config):
        config.serpapi_key = "test-key"
        h = _insert_hotel(tmp_db)
        _insert_booking(tmp_db, h, check_in=None, check_out=None)

        warnings = preflight_check(config, tmp_db)
        assert any("missing check-in/check-out" in w for w in warnings)

    def test_telegram_enabled_missing_token_warns(self, tmp_db, config):
        config.serpapi_key = "test-key"
        config.notifications.telegram_enabled = True
        config.telegram_bot_token = ""
        config.telegram_chat_id = ""
        h = _insert_hotel(tmp_db)
        _insert_booking(tmp_db, h)

        warnings = preflight_check(config, tmp_db)
        assert any("Telegram" in w for w in warnings)

    def test_all_clear_returns_empty(self, tmp_db, config):
        config.serpapi_key = "test-key"
        config.notifications.telegram_enabled = False
        h = _insert_hotel(tmp_db)
        _insert_booking(tmp_db, h)

        warnings = preflight_check(config, tmp_db)
        assert warnings == []


# ── run_pipeline ────────────────────────────────────────


class TestRunPipeline:
    """Tests for run_pipeline() orchestration."""

    # -- happy path --------------------------------------------------

    @patch("hotel_agent.pipeline.notify_alerts", return_value=0)
    @patch("hotel_agent.pipeline.run_analysis", return_value=[])
    @patch("hotel_agent.pipeline.verify_hotel_match", return_value=True)
    @patch("hotel_agent.pipeline.search_hotel_prices")
    def test_full_pipeline_runs_all_steps(
        self, mock_search, mock_verify, mock_analysis, mock_notify, tmp_db, config,
    ):
        """scrape → analyze → notify all execute when config is valid."""
        config.serpapi_key = "test-key"
        h = _insert_hotel(tmp_db, name="Namba Oriental Hotel")
        _insert_booking(tmp_db, h)

        mock_search.return_value = SerpAPIResult(
            snapshots=[
                PriceSnapshot(
                    hotel_id=h,
                    check_in=date(2026, 8, 31),
                    check_out=date(2026, 9, 3),
                    room_type="Standard Double",
                    platform="Booking.com",
                    price=120000,
                    currency="JPY",
                ),
            ],
            matched_name="Namba Oriental Hotel",
            matched_address="Osaka",
            property_token="tok123",
            used_cached_token=False,
        )

        result = run_pipeline(config, _make_get_db(config.db_path))

        assert result.scrape_total == 1
        assert result.scrape_success == 1
        assert result.scrape_failed == 0
        mock_search.assert_called_once()
        mock_verify.assert_called_once()
        mock_analysis.assert_called_once()
        mock_notify.assert_called_once()

    # -- no serpapi key ----------------------------------------------

    @patch("hotel_agent.pipeline.notify_alerts", return_value=0)
    @patch("hotel_agent.pipeline.run_analysis", return_value=[])
    def test_no_serpapi_key_skips_scraping(
        self, mock_analysis, mock_notify, tmp_db, config,
    ):
        """Without SERPAPI_KEY scraping is skipped, but analyze + notify still run."""
        config.serpapi_key = ""
        h = _insert_hotel(tmp_db)
        _insert_booking(tmp_db, h)

        result = run_pipeline(config, _make_get_db(config.db_path))

        assert result.scrape_total == 0
        assert result.scrape_success == 0
        assert any("SERPAPI_KEY" in e for e in result.errors)
        mock_analysis.assert_called_once()
        mock_notify.assert_called_once()

    # -- on_progress callback ----------------------------------------

    @patch("hotel_agent.pipeline.notify_alerts", return_value=0)
    @patch("hotel_agent.pipeline.run_analysis", return_value=[])
    @patch("hotel_agent.pipeline.verify_hotel_match", return_value=True)
    @patch("hotel_agent.pipeline.search_hotel_prices")
    def test_on_progress_invoked_for_each_step(
        self, mock_search, mock_verify, mock_analysis, mock_notify, tmp_db, config,
    ):
        config.serpapi_key = "test-key"
        h = _insert_hotel(tmp_db)
        _insert_booking(tmp_db, h)
        mock_search.return_value = SerpAPIResult(snapshots=[], used_cached_token=True)

        calls: list[tuple[str, dict]] = []

        result = run_pipeline(
            config,
            _make_get_db(config.db_path),
            on_progress=lambda step, detail: calls.append((step, detail)),
        )

        steps = [c[0] for c in calls]
        assert "preflight" in steps
        assert "scraping" in steps
        assert "analyzing" in steps
        assert "notifying" in steps
        assert "done" in steps

    @patch("hotel_agent.pipeline.notify_alerts", return_value=0)
    @patch("hotel_agent.pipeline.run_analysis", return_value=[])
    def test_on_progress_done_includes_stats(
        self, mock_analysis, mock_notify, tmp_db, config,
    ):
        """The 'done' progress call carries final result stats."""
        config.serpapi_key = ""

        calls: list[tuple[str, dict]] = []
        run_pipeline(
            config,
            _make_get_db(config.db_path),
            on_progress=lambda step, detail: calls.append((step, detail)),
        )

        done_calls = [c for c in calls if c[0] == "done"]
        assert len(done_calls) == 1
        detail = done_calls[0][1]
        assert "scrape_total" in detail
        assert "new_alerts" in detail

    # -- hotel filter ------------------------------------------------

    @patch("hotel_agent.pipeline.notify_alerts", return_value=0)
    @patch("hotel_agent.pipeline.run_analysis", return_value=[])
    @patch("hotel_agent.pipeline.verify_hotel_match", return_value=True)
    @patch("hotel_agent.pipeline.search_hotel_prices")
    def test_hotel_filter_restricts_bookings(
        self, mock_search, mock_verify, mock_analysis, mock_notify, tmp_db, config,
    ):
        config.serpapi_key = "test-key"
        h1 = _insert_hotel(tmp_db, name="Namba Oriental Hotel")
        _insert_booking(tmp_db, h1)
        h2 = _insert_hotel(tmp_db, name="Tokyo Tower Hotel", city="Tokyo")
        _insert_booking(tmp_db, h2, booked_price=200000)

        mock_search.return_value = SerpAPIResult(snapshots=[], used_cached_token=True)

        result = run_pipeline(
            config, _make_get_db(config.db_path), hotel_filter="Namba",
        )

        assert result.scrape_total == 1
        mock_search.assert_called_once()
        assert mock_search.call_args.kwargs["hotel"].name == "Namba Oriental Hotel"

    @patch("hotel_agent.pipeline.notify_alerts", return_value=0)
    @patch("hotel_agent.pipeline.run_analysis", return_value=[])
    @patch("hotel_agent.pipeline.verify_hotel_match", return_value=True)
    @patch("hotel_agent.pipeline.search_hotel_prices")
    def test_hotel_filter_case_insensitive(
        self, mock_search, mock_verify, mock_analysis, mock_notify, tmp_db, config,
    ):
        config.serpapi_key = "test-key"
        h = _insert_hotel(tmp_db, name="Namba Oriental Hotel")
        _insert_booking(tmp_db, h)
        mock_search.return_value = SerpAPIResult(snapshots=[], used_cached_token=True)

        result = run_pipeline(
            config, _make_get_db(config.db_path), hotel_filter="namba",
        )

        assert result.scrape_total == 1

    # -- result stats ------------------------------------------------

    @patch("hotel_agent.pipeline.notify_alerts", return_value=3)
    @patch("hotel_agent.pipeline.run_analysis")
    @patch("hotel_agent.pipeline.verify_hotel_match", return_value=True)
    @patch("hotel_agent.pipeline.search_hotel_prices")
    def test_returns_correct_pipeline_result(
        self, mock_search, mock_verify, mock_analysis, mock_notify, tmp_db, config,
    ):
        config.serpapi_key = "test-key"
        h = _insert_hotel(tmp_db, name="Namba Oriental Hotel")
        _insert_booking(tmp_db, h)

        mock_search.return_value = SerpAPIResult(
            snapshots=[
                PriceSnapshot(
                    hotel_id=h,
                    check_in=date(2026, 8, 31),
                    check_out=date(2026, 9, 3),
                    room_type="Standard Double",
                    platform="Booking.com",
                    price=120000,
                    currency="JPY",
                ),
            ],
            matched_name="Namba Oriental Hotel",
            matched_address="Osaka",
            property_token="tok",
            used_cached_token=False,
        )
        mock_analysis.return_value = [
            Alert(booking_id=1, snapshot_id=1, alert_type="price_drop",
                  title="Price drop", message="msg"),
            Alert(booking_id=1, snapshot_id=2, alert_type="upgrade",
                  title="Upgrade", message="msg"),
        ]

        result = run_pipeline(config, _make_get_db(config.db_path))

        assert result.scrape_total == 1
        assert result.scrape_success == 1
        assert result.scrape_failed == 0
        assert result.new_alerts == 2
        assert result.notifications_sent == 3

    # -- error handling ----------------------------------------------

    @patch("hotel_agent.pipeline.notify_alerts", return_value=0)
    @patch("hotel_agent.pipeline.run_analysis", return_value=[])
    @patch("hotel_agent.pipeline.search_hotel_prices")
    def test_serpapi_error_recorded_as_failure(
        self, mock_search, mock_analysis, mock_notify, tmp_db, config,
    ):
        config.serpapi_key = "test-key"
        h = _insert_hotel(tmp_db)
        _insert_booking(tmp_db, h)
        mock_search.side_effect = SerpAPIError("rate limit exceeded")

        result = run_pipeline(config, _make_get_db(config.db_path))

        assert result.scrape_total == 1
        assert result.scrape_failed == 1
        assert result.scrape_success == 0
        assert any("rate limit" in e for e in result.errors)

    @patch("hotel_agent.pipeline.notify_alerts", return_value=0)
    @patch("hotel_agent.pipeline.run_analysis", return_value=[])
    @patch("hotel_agent.pipeline.verify_hotel_match", return_value=False)
    @patch("hotel_agent.pipeline.search_hotel_prices")
    def test_llm_rejects_match_counts_as_failed(
        self, mock_search, mock_verify, mock_analysis, mock_notify, tmp_db, config,
    ):
        config.serpapi_key = "test-key"
        h = _insert_hotel(tmp_db)
        _insert_booking(tmp_db, h)

        mock_search.return_value = SerpAPIResult(
            snapshots=[],
            matched_name="Wrong Hotel Entirely",
            matched_address="Unknown City",
            property_token="tok",
            used_cached_token=False,
        )

        result = run_pipeline(config, _make_get_db(config.db_path))

        assert result.scrape_failed == 1
        assert result.scrape_success == 0
        assert any("not a match" in e for e in result.errors)

    @patch("hotel_agent.pipeline.notify_alerts", return_value=0)
    @patch("hotel_agent.pipeline.run_analysis", return_value=[])
    @patch("hotel_agent.pipeline.search_hotel_prices")
    def test_missing_dates_skips_scrape_call(
        self, mock_search, mock_analysis, mock_notify, tmp_db, config,
    ):
        """Bookings without check-in/out dates are skipped (no API call)."""
        config.serpapi_key = "test-key"
        h = _insert_hotel(tmp_db)
        _insert_booking(tmp_db, h, check_in=None, check_out=None)

        result = run_pipeline(config, _make_get_db(config.db_path))

        assert result.scrape_total == 1
        assert result.scrape_failed == 1
        mock_search.assert_not_called()

    # -- LLM verification paths --------------------------------------

    @patch("hotel_agent.pipeline.notify_alerts", return_value=0)
    @patch("hotel_agent.pipeline.run_analysis", return_value=[])
    @patch("hotel_agent.pipeline.verify_hotel_match", return_value=True)
    @patch("hotel_agent.pipeline.search_hotel_prices")
    def test_cached_token_skips_llm_verification(
        self, mock_search, mock_verify, mock_analysis, mock_notify, tmp_db, config,
    ):
        """When the property token is cached, the LLM is not consulted."""
        config.serpapi_key = "test-key"
        h = _insert_hotel(tmp_db)
        _insert_booking(tmp_db, h)

        mock_search.return_value = SerpAPIResult(
            snapshots=[],
            matched_name="Test Hotel",
            property_token="cached-tok",
            used_cached_token=True,
        )

        run_pipeline(config, _make_get_db(config.db_path))

        mock_verify.assert_not_called()

    @patch("hotel_agent.pipeline.notify_alerts", return_value=0)
    @patch("hotel_agent.pipeline.run_analysis", return_value=[])
    @patch("hotel_agent.pipeline.verify_hotel_match", return_value=True)
    @patch("hotel_agent.pipeline.search_hotel_prices")
    def test_verified_match_caches_property_token(
        self, mock_search, mock_verify, mock_analysis, mock_notify, tmp_db, config,
    ):
        """An LLM-approved match persists the property token on the hotel."""
        config.serpapi_key = "test-key"
        h = _insert_hotel(tmp_db, name="Namba Oriental Hotel")
        _insert_booking(tmp_db, h)

        mock_search.return_value = SerpAPIResult(
            snapshots=[],
            matched_name="Namba Oriental Hotel",
            matched_address="Osaka",
            property_token="new-token-abc",
            used_cached_token=False,
        )

        run_pipeline(config, _make_get_db(config.db_path))

        mock_verify.assert_called_once()
        # Token should be persisted in the database
        with _make_get_db(config.db_path)() as db:
            hotel = db.get_hotel(h)
            assert hotel is not None
            assert hotel.serpapi_property_token == "new-token-abc"


# ── Alert dedup ─────────────────────────────────────────


class TestAlertDedup:
    """Tests for alert deduplication via db.alert_exists()."""

    def test_alert_exists_returns_false_when_no_match(self, tmp_db):
        result = tmp_db.alert_exists(
            booking_id=999, alert_type="price_drop", snapshot_id=999,
        )
        assert result is False

    def test_alert_exists_returns_true_when_match(self, tmp_db):
        h = _insert_hotel(tmp_db)
        b = _insert_booking(tmp_db, h)
        s = tmp_db.add_snapshot(
            PriceSnapshot(
                hotel_id=h,
                check_in=date(2026, 1, 1),
                check_out=date(2026, 1, 3),
                room_type="Standard",
                platform="Booking.com",
                price=80,
                currency="JPY",
            )
        )
        tmp_db.add_alert(
            Alert(
                booking_id=b,
                snapshot_id=s,
                alert_type="price_drop",
                title="Drop",
                message="Price dropped",
            )
        )

        assert tmp_db.alert_exists(booking_id=b, alert_type="price_drop", snapshot_id=s) is True

    def test_alert_exists_false_for_different_alert_type(self, tmp_db):
        h = _insert_hotel(tmp_db)
        b = _insert_booking(tmp_db, h)
        s = tmp_db.add_snapshot(
            PriceSnapshot(
                hotel_id=h,
                check_in=date(2026, 1, 1),
                check_out=date(2026, 1, 3),
                room_type="Standard",
                platform="Booking.com",
                price=80,
                currency="JPY",
            )
        )
        tmp_db.add_alert(
            Alert(
                booking_id=b,
                snapshot_id=s,
                alert_type="price_drop",
                title="Drop",
                message="Price dropped",
            )
        )

        # Same booking + snapshot but different alert_type → not a duplicate
        assert tmp_db.alert_exists(booking_id=b, alert_type="upgrade", snapshot_id=s) is False

    def test_run_analysis_skips_existing_alerts(self, tmp_db, config):
        """run_analysis does not re-create alerts that already exist in the DB."""
        from hotel_agent.analysis.comparator import run_analysis

        config.currency.rates = {"JPY": 150.0, "EUR": 0.92}

        h = _insert_hotel(tmp_db)
        _insert_booking(
            tmp_db, h, booked_price=200, currency="USD", room_type="Standard Double",
        )
        tmp_db.add_snapshot(
            PriceSnapshot(
                hotel_id=h,
                check_in=date(2026, 8, 31),
                check_out=date(2026, 9, 3),
                room_type="Standard Double",
                platform="Booking.com",
                price=100,
                currency="USD",
                is_cancellable=True,
            )
        )

        # First analysis run → should produce at least one alert
        first_alerts = run_analysis(tmp_db, config)
        assert len(first_alerts) > 0

        # Second run with the same data → duplicates skipped
        second_alerts = run_analysis(tmp_db, config)
        assert second_alerts == []
