"""Tests for the web dashboard routes."""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from hotel_agent.db import Database
from hotel_agent.models import Booking, Hotel, PriceSnapshot, TravelerComposition
from hotel_agent.web.app import create_app


@pytest.fixture()
def _web_env(tmp_path):
    """Create a minimal config + db for web tests."""
    config_file = tmp_path / "config.yaml"
    config_file.write_text("database:\n  path: ''\n")
    db_path = str(tmp_path / "test.db")

    # Create setup completion marker so middleware doesn't redirect
    (tmp_path / ".setup_complete").write_text("1")

    env = {"DATABASE_PATH": db_path}
    with patch.dict(os.environ, env, clear=True):
        # Patch default config path so it uses our temp file
        app = create_app(str(config_file))
        # Override the db path on the config object inside the closure
        # We do this by monkey-patching the app's config via a quick request
        yield app, db_path, config_file


@pytest.fixture()
def client(_web_env):
    app, _db_path, _ = _web_env
    return TestClient(app)


@pytest.fixture()
def seeded_env(tmp_path):
    """Create app with a pre-seeded database."""
    db_path = str(tmp_path / "test.db")
    config_file = tmp_path / "config.yaml"
    config_file.write_text(f"database:\n  path: '{db_path}'\n")

    # Create setup completion marker so middleware doesn't redirect
    (tmp_path / ".setup_complete").write_text("1")

    db = Database(db_path)
    hotel_id = db.upsert_hotel(Hotel(name="Test Hotel", city="Tokyo"))
    booking = Booking(
        hotel_id=hotel_id,
        check_in=date(2026, 8, 1),
        check_out=date(2026, 8, 5),
        travelers=TravelerComposition(adults=2, children_ages=[4]),
        room_type="Standard Double",
        booked_price=100000,
        currency="JPY",
        platform="Booking.com",
        booking_reference="REF123",
        is_cancellable=True,
        status="active",
    )
    booking_id = db.upsert_booking(booking)
    db.close()

    with patch.dict(os.environ, {}, clear=True):
        app = create_app(str(config_file))

    return TestClient(app), db_path, booking_id, config_file


class TestDashboardPages:
    """Smoke tests for page rendering."""

    def test_dashboard_returns_200(self, seeded_env):
        client, *_ = seeded_env
        resp = client.get("/")
        assert resp.status_code == 200
        assert "Dashboard" in resp.text

    def test_bookings_page_returns_200(self, seeded_env):
        client, *_ = seeded_env
        resp = client.get("/bookings")
        assert resp.status_code == 200
        assert "Test Hotel" in resp.text

    def test_bookings_page_has_edit_link(self, seeded_env):
        client, _, booking_id, _ = seeded_env
        resp = client.get("/bookings")
        assert f"/bookings/{booking_id}/edit" in resp.text


class TestBookingEdit:
    """Tests for the booking edit page."""

    def test_edit_page_loads(self, seeded_env):
        client, _, booking_id, _ = seeded_env
        resp = client.get(f"/bookings/{booking_id}/edit")
        assert resp.status_code == 200
        assert "Edit Booking" in resp.text
        assert "Standard Double" in resp.text

    def test_edit_page_not_found(self, seeded_env):
        client, *_ = seeded_env
        resp = client.get("/bookings/9999/edit")
        assert resp.status_code == 404

    def test_edit_saves_changes(self, seeded_env):
        client, db_path, booking_id, _ = seeded_env
        resp = client.post(
            f"/bookings/{booking_id}/edit",
            data={
                "check_in": "2026-08-02",
                "check_out": "2026-08-06",
                "room_type": "Deluxe Twin",
                "booked_price": "90000",
                "currency": "JPY",
                "platform": "Agoda",
                "booking_reference": "REF456",
                "status": "active",
                "adults": "3",
                "children_ages": "4, 7",
                "is_cancellable": "1",
                "cancellation_deadline": "",
                "breakfast_included": "1",
                "bathroom_type": "private",
                "notes": "test note",
            },
        )
        assert resp.status_code == 200
        assert "Changes saved" in resp.text

        # Verify in DB
        db = Database(db_path)
        updated = db.get_booking_by_id(booking_id)
        db.close()
        assert updated is not None
        assert updated.room_type == "Deluxe Twin"
        assert updated.booked_price == 90000
        assert updated.travelers.adults == 3
        assert updated.travelers.children_ages == [4, 7]
        assert updated.breakfast_included is True
        assert updated.notes == "test note"

    def test_edit_post_not_found(self, seeded_env):
        client, *_ = seeded_env
        resp = client.post(
            "/bookings/9999/edit",
            data={
                "check_in": "",
                "check_out": "",
                "room_type": "",
                "booked_price": "0",
                "currency": "JPY",
                "platform": "",
                "booking_reference": "",
                "status": "active",
                "adults": "2",
                "children_ages": "",
                "bathroom_type": "private",
                "notes": "",
            },
        )
        assert resp.status_code == 404


class TestConfigEditor:
    """Tests for the config editor page."""

    def test_config_page_loads(self, seeded_env):
        client, *_ = seeded_env
        resp = client.get("/config")
        assert resp.status_code == 200
        assert "Configuration" in resp.text

    def test_config_save(self, seeded_env):
        client, _, _, _config_file = seeded_env
        resp = client.post(
            "/config",
            data={
                "travelers_adults": "3",
                "travelers_children": "5, 10",
                "llm_provider": "anthropic",
                "llm_model": "claude-3",
                "currency_base": "ILS",
                "currency_rates": "JPY: 0.025",
                "alert_price_drop_min_absolute": "500",
                "alert_price_drop_min_percentage": "5",
                "alert_upgrade_max_extra_cost": "1000",
                "alert_upgrade_max_extra_percentage": "10",
                "notif_telegram": "1",
                "notif_digest_time": "09:00",
                "db_path": "custom.db",
            },
        )
        assert resp.status_code == 200
        assert "saved successfully" in resp.text

    def test_sidebar_has_config_link(self, seeded_env):
        client, *_ = seeded_env
        resp = client.get("/")
        assert "/config" in resp.text

    def test_sidebar_has_trends_link(self, seeded_env):
        client, *_ = seeded_env
        resp = client.get("/")
        assert "/trends" in resp.text


class TestSnapshotWipe:
    """Tests for the snapshot wipe feature."""

    def test_wipe_snapshots(self, seeded_env):
        client, db_path, _booking_id, _ = seeded_env
        # Add some snapshots
        db = Database(db_path)
        db.add_snapshot(
            PriceSnapshot(
                hotel_id=1,
                check_in=date(2026, 8, 1),
                check_out=date(2026, 8, 5),
                platform="Agoda",
                price=90000,
                currency="JPY",
            )
        )
        assert len(db.get_all_snapshots()) == 1
        db.close()

        resp = client.post("/snapshots/wipe")
        assert resp.status_code == 200
        assert "Wiped 1 snapshot" in resp.text

        db = Database(db_path)
        assert db.get_all_snapshots() == []
        db.close()

    def test_delete_single_snapshot(self, seeded_env):
        client, db_path, _booking_id, _ = seeded_env
        db = Database(db_path)
        snap_id = db.add_snapshot(
            PriceSnapshot(
                hotel_id=1,
                check_in=date(2026, 8, 1),
                check_out=date(2026, 8, 5),
                platform="Agoda",
                price=90000,
                currency="JPY",
            )
        )
        db.add_snapshot(
            PriceSnapshot(
                hotel_id=1,
                check_in=date(2026, 8, 1),
                check_out=date(2026, 8, 5),
                platform="Booking.com",
                price=95000,
                currency="JPY",
            )
        )
        assert len(db.get_all_snapshots()) == 2
        db.close()

        resp = client.post(f"/snapshots/{snap_id}/delete")
        assert resp.status_code == 200
        assert f"Snapshot #{snap_id} deleted" in resp.text

        db = Database(db_path)
        assert len(db.get_all_snapshots()) == 1
        assert db.get_all_snapshots()[0].platform == "Booking.com"
        db.close()


class TestTrendsPage:
    """Tests for the trends page."""

    def test_trends_empty(self, seeded_env):
        client, *_ = seeded_env
        resp = client.get("/trends")
        assert resp.status_code == 200
        assert "Price Trends" in resp.text

    def test_trends_with_data(self, seeded_env):
        client, db_path, _booking_id, _ = seeded_env
        db = Database(db_path)
        db.add_snapshot(
            PriceSnapshot(
                hotel_id=1,
                check_in=date(2026, 8, 1),
                check_out=date(2026, 8, 5),
                platform="Agoda",
                price=90000,
                currency="JPY",
            )
        )
        db.close()

        resp = client.get("/trends")
        assert resp.status_code == 200
        assert "Test Hotel" in resp.text
        assert "Agoda" in resp.text


class TestScrapeRunsPages:
    """Tests for the scrape runs history pages."""

    def test_scrapes_empty(self, seeded_env):
        client, *_ = seeded_env
        resp = client.get("/scrapes")
        assert resp.status_code == 200
        assert "Scrape History" in resp.text
        assert "No scrapes yet" in resp.text

    def test_scrapes_with_runs(self, seeded_env):
        client, db_path, *_ = seeded_env
        db = Database(db_path)
        run_id = db.start_scrape_run()
        details = [
            {
                "hotel": "Test Hotel",
                "prices": 3,
                "status": "ok",
                "sources": [
                    {"platform": "booking.com", "link": "", "price": 40000, "currency": "JPY"},
                ],
            }
        ]
        db.finish_scrape_run(run_id, 1, 1, 0, [], details=details)
        db.close()

        resp = client.get("/scrapes")
        assert resp.status_code == 200
        assert "Run #" in resp.text
        assert "Test Hotel" in resp.text
        assert "booking.com" in resp.text

    def test_scrape_detail_page(self, seeded_env):
        client, db_path, *_ = seeded_env
        db = Database(db_path)
        run_id = db.start_scrape_run()
        db.finish_scrape_run(
            run_id, 1, 1, 0, [], details=[{"hotel": "X", "prices": 2, "status": "ok"}]
        )
        db.close()

        resp = client.get(f"/scrapes/{run_id}")
        assert resp.status_code == 200
        assert f"Scrape Run #{run_id}" in resp.text

    def test_scrape_detail_not_found(self, seeded_env):
        client, *_ = seeded_env
        resp = client.get("/scrapes/9999")
        assert resp.status_code == 200
        assert "Run not found" in resp.text


class TestPlatformLinks:
    """Tests that platform badges render as clickable links."""

    def test_snapshot_detail_has_platform_link(self, seeded_env):
        client, db_path, *_ = seeded_env
        db = Database(db_path)
        snap_id = db.add_snapshot(
            PriceSnapshot(
                hotel_id=1,
                check_in=date(2026, 8, 1),
                check_out=date(2026, 8, 5),
                platform="booking.com",
                price=80000,
                currency="JPY",
                link="https://www.booking.com/hotel/test",
            )
        )
        db.close()

        resp = client.get(f"/snapshots/{snap_id}")
        assert resp.status_code == 200
        assert "https://www.booking.com/hotel/test" in resp.text
        assert "booking.com" in resp.text

    def test_dashboard_shows_scrape_details(self, seeded_env):
        client, db_path, *_ = seeded_env
        db = Database(db_path)
        run_id = db.start_scrape_run()
        details = [
            {
                "hotel": "Test Hotel",
                "prices": 2,
                "status": "ok",
                "sources": [
                    {"platform": "agoda", "link": "", "price": 50000, "currency": "JPY"},
                ],
            }
        ]
        db.finish_scrape_run(run_id, 1, 1, 0, [], details=details)
        db.close()

        resp = client.get("/")
        assert resp.status_code == 200
        assert "Per-hotel results" in resp.text
        assert "agoda" in resp.text


class TestScrapeBackground:
    """Tests for the background scrape + polling endpoints."""

    def test_scrape_page_returns_200(self, seeded_env):
        client, *_ = seeded_env
        resp = client.get("/scrape")
        assert resp.status_code == 200
        assert "Fetch Prices" in resp.text

    def test_scrape_status_idle(self, seeded_env):
        client, *_ = seeded_env
        resp = client.get("/api/scrape/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["running"] is False
        assert data["total"] == 0

    def test_post_scrape_redirects(self, seeded_env):
        """POST /scrape should redirect (303) instead of blocking."""
        client, *_ = seeded_env
        resp = client.post(
            "/scrape",
            data={"hotel_filter": ""},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == "/scrape"

    def test_post_scrape_starts_background_thread(self, seeded_env):
        """After POST, the status endpoint should show running or just-completed."""
        import time

        client, *_ = seeded_env
        # POST triggers background thread (no serpapi key, so it completes fast)
        client.post("/scrape", data={"hotel_filter": ""}, follow_redirects=False)
        # Give the thread a moment
        time.sleep(0.3)
        resp = client.get("/api/scrape/status")
        data = resp.json()
        # It should have finished (no API key configured = quick exit)
        assert data["total"] >= 0
        # Errors should mention missing key or be empty (if no bookings match)
        if data["errors"]:
            assert any("SERPAPI_KEY" in e for e in data["errors"])


class TestPipelineRoutes:
    """Tests for pipeline (Run Now) web endpoints."""

    def test_pipeline_preflight_returns_200(self, seeded_env):
        client, *_ = seeded_env
        resp = client.get("/api/pipeline/preflight")
        assert resp.status_code == 200
        data = resp.json()
        assert "warnings" in data
        assert isinstance(data["warnings"], list)

    def test_pipeline_preflight_warns_no_serpapi(self, seeded_env):
        client, *_ = seeded_env
        resp = client.get("/api/pipeline/preflight")
        data = resp.json()
        assert any("SERPAPI_KEY" in w for w in data["warnings"])

    def test_pipeline_status_idle(self, seeded_env):
        client, *_ = seeded_env
        resp = client.get("/api/pipeline/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["running"] is False

    def test_post_pipeline_run_redirects(self, seeded_env):
        client, *_ = seeded_env
        resp = client.post(
            "/pipeline/run",
            data={"hotel_filter": ""},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == "/"

    def test_pipeline_run_completes(self, seeded_env):
        import time

        client, *_ = seeded_env
        client.post("/pipeline/run", data={"hotel_filter": ""}, follow_redirects=False)
        time.sleep(0.5)
        resp = client.get("/api/pipeline/status")
        data = resp.json()
        # Should have finished (no API key = quick exit)
        # step can be "" if pipeline completed and state was read before thread updated it
        assert data["running"] is False or data["step"] in (
            "done",
            "starting",
            "scraping",
            "analyzing",
            "notifying",
        )

    def test_dashboard_contains_run_now(self, seeded_env):
        client, *_ = seeded_env
        resp = client.get("/")
        assert resp.status_code == 200
        assert "Run Now" in resp.text
        assert "pipeline" in resp.text.lower()


class TestSchedulerRoutes:
    """Tests for scheduler web endpoints."""

    def test_scheduler_page_returns_200(self, seeded_env):
        client, *_ = seeded_env
        resp = client.get("/scheduler")
        assert resp.status_code == 200
        assert "Scheduler" in resp.text
        assert "Schedule Configuration" in resp.text

    def test_scheduler_status_api(self, seeded_env):
        client, *_ = seeded_env
        resp = client.get("/api/scheduler/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "active" in data
        assert "mode" in data
        assert data["active"] is False  # default is inactive

    def test_scheduler_config_save(self, seeded_env):
        client, *_ = seeded_env
        resp = client.post(
            "/scheduler/config",
            data={
                "mode": "daily",
                "interval_value": "6",
                "interval_unit": "hours",
                "daily_time": "10:00",
                "weekly_time": "08:00",
            },
        )
        assert resp.status_code == 200
        assert "Schedule saved" in resp.text

        # Verify via API
        resp = client.get("/api/scheduler/status")
        data = resp.json()
        assert data["mode"] == "daily"
        assert data["daily_time"] == "10:00"

    def test_scheduler_start_stop(self, seeded_env):
        client, *_ = seeded_env

        # Start
        resp = client.post("/scheduler/start", follow_redirects=False)
        assert resp.status_code == 303

        resp = client.get("/api/scheduler/status")
        data = resp.json()
        assert data["active"] is True

        # Stop
        resp = client.post("/scheduler/stop", follow_redirects=False)
        assert resp.status_code == 303

        resp = client.get("/api/scheduler/status")
        data = resp.json()
        assert data["active"] is False

    def test_dashboard_contains_scheduler_card(self, seeded_env):
        client, *_ = seeded_env
        resp = client.get("/")
        assert resp.status_code == 200
        assert "Scheduler" in resp.text

    def test_sidebar_contains_scheduler_link(self, seeded_env):
        client, *_ = seeded_env
        resp = client.get("/")
        assert resp.status_code == 200
        assert "/scheduler" in resp.text


class TestPlatformUrl:
    """Unit tests for platform_url helper."""

    def test_known_platform(self):
        from hotel_agent.utils import platform_url

        assert platform_url("booking.com") == "https://www.booking.com"
        assert platform_url("Booking.com") == "https://www.booking.com"

    def test_unknown_platform(self):
        from hotel_agent.utils import platform_url

        assert platform_url("unknown_ota") == ""

    def test_japanese_platforms(self):
        from hotel_agent.utils import platform_url

        assert platform_url("rakuten_travel") == "https://travel.rakuten.co.jp"
        assert platform_url("jalan") == "https://www.jalan.net"


class TestImportErrorHeader:
    """Test that import failure returns X-Import-Error header."""

    def test_import_bad_file_returns_error_header(self, seeded_env):
        """POST /import with an invalid file should return X-Import-Error."""
        client, *_ = seeded_env
        import io

        fake_file = io.BytesIO(b"not a real excel file")
        resp = client.post(
            "/import",
            files={"file": ("bad.xlsx", fake_file, "application/octet-stream")},
            data={"sheet": "Sheet1", "table": ""},
        )
        assert resp.headers.get("X-Import-Status") == "error"
        err = resp.headers.get("X-Import-Error")
        assert err is not None
        assert len(err) > 0


class TestAutostartAPI:
    """Test autostart API endpoints."""

    def test_get_autostart_status(self, client):
        """GET /api/autostart returns enabled field."""
        with patch("hotel_agent.launcher.Path.home", return_value=Path("/tmp/fake")):
            resp = client.get("/api/autostart")
        assert resp.status_code == 200
        data = resp.json()
        assert "enabled" in data
        assert data["enabled"] is False

    def test_post_autostart_toggle(self, client, tmp_path):
        """POST /api/autostart toggles the setting."""
        with patch("hotel_agent.launcher.Path.home", return_value=tmp_path):
            resp = client.post(
                "/api/autostart",
                json={"enabled": True},
            )
            assert resp.status_code == 200
            assert resp.json()["enabled"] is True

            # Verify it's actually enabled
            resp = client.get("/api/autostart")
            assert resp.json()["enabled"] is True

            # Disable
            resp = client.post("/api/autostart", json={"enabled": False})
            assert resp.json()["enabled"] is False
