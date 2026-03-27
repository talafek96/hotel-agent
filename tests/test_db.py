"""Tests for hotel_agent.db module."""

import json
from datetime import date

from hotel_agent.db import Database
from hotel_agent.models import (
    Alert,
    Booking,
    Hotel,
    PriceSnapshot,
    TravelerComposition,
    WatchlistEntry,
)

# ── Schema ─────────────────────────────────────────────────


class TestSchema:
    """Tests for database schema creation."""

    def test_schema_creates_tables(self, tmp_db):
        """Verify all expected tables are created."""
        rows = tmp_db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        table_names = {r["name"] for r in rows}
        expected = {"hotels", "bookings", "watchlist", "price_snapshots", "alerts", "scrape_runs"}
        assert expected.issubset(table_names)

    def test_schema_creates_indexes(self, tmp_db):
        rows = tmp_db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'"
        ).fetchall()
        index_names = {r["name"] for r in rows}
        assert "idx_snapshots_hotel_date" in index_names
        assert "idx_alerts_created" in index_names
        assert "idx_bookings_status" in index_names
        assert "idx_bookings_hotel" in index_names

    def test_schema_is_idempotent(self, tmp_db):
        """Running _init_schema twice should not fail."""
        tmp_db._init_schema()
        rows = tmp_db.conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        assert len(rows) > 0

    def test_database_creates_parent_dir(self, tmp_path):
        nested = tmp_path / "sub" / "dir" / "test.db"
        db = Database(str(nested))
        assert nested.parent.exists()
        db.close()


# ── Hotels CRUD ────────────────────────────────────────────


class TestHotelCRUD:
    """Tests for hotel database operations."""

    def test_insert_hotel(self, tmp_db, sample_hotel):
        hotel_id = tmp_db.upsert_hotel(sample_hotel)
        assert hotel_id is not None
        assert hotel_id > 0

    def test_get_hotel(self, tmp_db, sample_hotel):
        hotel_id = tmp_db.upsert_hotel(sample_hotel)
        retrieved = tmp_db.get_hotel(hotel_id)
        assert retrieved is not None
        assert retrieved.name == "Namba Oriental Hotel"
        assert retrieved.city == "Osaka"
        assert retrieved.country == "Japan"
        assert retrieved.platform == "Booking.com"
        assert retrieved.id == hotel_id

    def test_get_hotel_not_found(self, tmp_db):
        result = tmp_db.get_hotel(9999)
        assert result is None

    def test_get_hotel_has_added_at(self, tmp_db, sample_hotel):
        hotel_id = tmp_db.upsert_hotel(sample_hotel)
        retrieved = tmp_db.get_hotel(hotel_id)
        assert retrieved.added_at is not None

    def test_upsert_updates_existing_by_id(self, tmp_db, sample_hotel):
        hotel_id = tmp_db.upsert_hotel(sample_hotel)
        sample_hotel.id = hotel_id
        sample_hotel.name = "Updated Name"
        sample_hotel.notes = "Renovated"
        updated_id = tmp_db.upsert_hotel(sample_hotel)
        assert updated_id == hotel_id

        retrieved = tmp_db.get_hotel(hotel_id)
        assert retrieved.name == "Updated Name"
        assert retrieved.notes == "Renovated"

    def test_upsert_deduplicates_by_name_and_city(self, tmp_db, sample_hotel):
        """Inserting same name+city hotel should update, not duplicate."""
        hotel_id1 = tmp_db.upsert_hotel(sample_hotel)

        # Create a new Hotel object with same name and city but no id
        hotel2 = Hotel(
            name="Namba Oriental Hotel",
            city="Osaka",
            country="Japan",
            url="https://new-url.com",
        )
        hotel_id2 = tmp_db.upsert_hotel(hotel2)
        assert hotel_id1 == hotel_id2

        all_hotels = tmp_db.get_all_hotels()
        assert len(all_hotels) == 1
        assert all_hotels[0].url == "https://new-url.com"

    def test_get_all_hotels_empty(self, tmp_db):
        hotels = tmp_db.get_all_hotels()
        assert hotels == []

    def test_get_all_hotels_multiple(self, tmp_db):
        tmp_db.upsert_hotel(Hotel(name="Hotel A", city="Tokyo"))
        tmp_db.upsert_hotel(Hotel(name="Hotel B", city="Osaka"))
        tmp_db.upsert_hotel(Hotel(name="Hotel C", city="Kyoto"))
        hotels = tmp_db.get_all_hotels()
        assert len(hotels) == 3
        assert hotels[0].name == "Hotel A"
        assert hotels[2].name == "Hotel C"

    def test_different_cities_same_name_are_separate(self, tmp_db):
        tmp_db.upsert_hotel(Hotel(name="Grand Hotel", city="Tokyo"))
        tmp_db.upsert_hotel(Hotel(name="Grand Hotel", city="Osaka"))
        hotels = tmp_db.get_all_hotels()
        assert len(hotels) == 2


# ── Bookings CRUD ──────────────────────────────────────────


class TestBookingCRUD:
    """Tests for booking database operations."""

    def _insert_hotel(self, db):
        return db.upsert_hotel(Hotel(name="Test Hotel", city="Tokyo"))

    def test_upsert_booking(self, tmp_db, sample_booking):
        hotel_id = self._insert_hotel(tmp_db)
        sample_booking.hotel_id = hotel_id
        booking_id = tmp_db.upsert_booking(sample_booking)
        assert booking_id is not None
        assert booking_id > 0

    def test_upsert_booking_dedup_by_reference(self, tmp_db, sample_booking):
        """Importing the same booking twice should not create duplicates."""
        hotel_id = self._insert_hotel(tmp_db)
        sample_booking.hotel_id = hotel_id
        id1 = tmp_db.upsert_booking(sample_booking)
        id2 = tmp_db.upsert_booking(sample_booking)
        assert id1 == id2
        assert len(tmp_db.get_active_bookings()) == 1

    def test_upsert_booking_no_dedup_without_reference(self, tmp_db):
        """Without booking_reference, same hotel/dates/platform creates separate rows."""
        hotel_id = self._insert_hotel(tmp_db)
        b = Booking(
            hotel_id=hotel_id,
            check_in=date(2026, 8, 1),
            check_out=date(2026, 8, 5),
            booked_price=100000,
            platform="Booking.com",
        )
        id1 = tmp_db.upsert_booking(b)
        b2 = Booking(
            hotel_id=hotel_id,
            check_in=date(2026, 8, 1),
            check_out=date(2026, 8, 5),
            booked_price=95000,
            platform="Booking.com",
        )
        id2 = tmp_db.upsert_booking(b2)
        assert id1 != id2
        assert len(tmp_db.get_active_bookings()) == 2

    def test_upsert_hotel_case_insensitive(self, tmp_db):
        """Hotel dedup should be case/whitespace insensitive."""
        id1 = tmp_db.upsert_hotel(Hotel(name="Hotel Gracery", city="Shinjuku"))
        id2 = tmp_db.upsert_hotel(Hotel(name="hotel gracery", city="shinjuku"))
        id3 = tmp_db.upsert_hotel(Hotel(name="Hotel  Gracery", city=" Shinjuku "))
        assert id1 == id2 == id3
        assert len(tmp_db.get_all_hotels()) == 1

    def test_get_active_bookings(self, tmp_db, sample_booking):
        hotel_id = self._insert_hotel(tmp_db)
        sample_booking.hotel_id = hotel_id
        tmp_db.upsert_booking(sample_booking)

        active = tmp_db.get_active_bookings()
        assert len(active) == 1
        assert active[0].hotel_id == hotel_id
        assert active[0].check_in == date(2026, 8, 31)
        assert active[0].check_out == date(2026, 9, 3)
        assert active[0].booked_price == 135833
        assert active[0].is_cancellable is True
        assert active[0].booking_reference == "628875015"

    def test_get_active_bookings_excludes_cancelled(self, tmp_db):
        hotel_id = self._insert_hotel(tmp_db)
        active_booking = Booking(
            hotel_id=hotel_id,
            check_in=date(2026, 1, 1),
            check_out=date(2026, 1, 3),
            booked_price=50000,
            status="active",
        )
        cancelled_booking = Booking(
            hotel_id=hotel_id,
            check_in=date(2026, 2, 1),
            check_out=date(2026, 2, 3),
            booked_price=60000,
            status="cancelled",
        )
        tmp_db.upsert_booking(active_booking)
        tmp_db.upsert_booking(cancelled_booking)

        active = tmp_db.get_active_bookings()
        assert len(active) == 1
        assert active[0].status == "active"

    def test_get_active_bookings_empty(self, tmp_db):
        assert tmp_db.get_active_bookings() == []

    def test_get_bookings_for_hotel(self, tmp_db):
        hotel_id1 = tmp_db.upsert_hotel(Hotel(name="Hotel A", city="Tokyo"))
        hotel_id2 = tmp_db.upsert_hotel(Hotel(name="Hotel B", city="Osaka"))

        tmp_db.upsert_booking(
            Booking(
                hotel_id=hotel_id1,
                check_in=date(2026, 1, 1),
                check_out=date(2026, 1, 3),
                booked_price=50000,
            )
        )
        tmp_db.upsert_booking(
            Booking(
                hotel_id=hotel_id1,
                check_in=date(2026, 2, 1),
                check_out=date(2026, 2, 3),
                booked_price=60000,
            )
        )
        tmp_db.upsert_booking(
            Booking(
                hotel_id=hotel_id2,
                check_in=date(2026, 3, 1),
                check_out=date(2026, 3, 3),
                booked_price=70000,
            )
        )

        bookings_h1 = tmp_db.get_bookings_for_hotel(hotel_id1)
        assert len(bookings_h1) == 2

        bookings_h2 = tmp_db.get_bookings_for_hotel(hotel_id2)
        assert len(bookings_h2) == 1

    def test_get_bookings_for_hotel_empty(self, tmp_db):
        hotel_id = self._insert_hotel(tmp_db)
        bookings = tmp_db.get_bookings_for_hotel(hotel_id)
        assert bookings == []

    def test_booking_travelers_persisted(self, tmp_db):
        hotel_id = self._insert_hotel(tmp_db)
        booking = Booking(
            hotel_id=hotel_id,
            check_in=date(2026, 1, 1),
            check_out=date(2026, 1, 3),
            travelers=TravelerComposition(adults=2, children_ages=[4, 7]),
            booked_price=80000,
        )
        tmp_db.upsert_booking(booking)
        retrieved = tmp_db.get_active_bookings()[0]
        assert retrieved.travelers.adults == 2
        assert retrieved.travelers.children_ages == [4, 7]

    def test_booking_cancellation_deadline_persisted(self, tmp_db):
        hotel_id = self._insert_hotel(tmp_db)
        booking = Booking(
            hotel_id=hotel_id,
            check_in=date(2026, 1, 1),
            check_out=date(2026, 1, 3),
            booked_price=50000,
            cancellation_deadline=date(2025, 12, 30),
        )
        tmp_db.upsert_booking(booking)
        retrieved = tmp_db.get_active_bookings()[0]
        assert retrieved.cancellation_deadline == date(2025, 12, 30)

    def test_get_booking_by_id(self, tmp_db, sample_booking):
        hotel_id = self._insert_hotel(tmp_db)
        sample_booking.hotel_id = hotel_id
        booking_id = tmp_db.upsert_booking(sample_booking)
        retrieved = tmp_db.get_booking_by_id(booking_id)
        assert retrieved is not None
        assert retrieved.id == booking_id
        assert retrieved.booked_price == 135833

    def test_get_booking_by_id_not_found(self, tmp_db):
        assert tmp_db.get_booking_by_id(9999) is None

    def test_update_booking(self, tmp_db, sample_booking):
        hotel_id = self._insert_hotel(tmp_db)
        sample_booking.hotel_id = hotel_id
        booking_id = tmp_db.upsert_booking(sample_booking)

        booking = tmp_db.get_booking_by_id(booking_id)
        assert booking is not None
        booking.booked_price = 120000
        booking.room_type = "Superior Twin"
        booking.travelers = TravelerComposition(adults=3, children_ages=[5])
        booking.is_cancellable = False
        booking.notes = "updated"
        tmp_db.update_booking(booking)

        updated = tmp_db.get_booking_by_id(booking_id)
        assert updated is not None
        assert updated.booked_price == 120000
        assert updated.room_type == "Superior Twin"
        assert updated.travelers.adults == 3
        assert updated.travelers.children_ages == [5]
        assert updated.is_cancellable is False
        assert updated.notes == "updated"

    def test_update_booking_without_id_raises(self, tmp_db):
        import pytest

        booking = Booking(hotel_id=1, booked_price=50000)
        with pytest.raises(ValueError, match="without an ID"):
            tmp_db.update_booking(booking)


# ── Price Snapshots ────────────────────────────────────────


class TestSnapshotCRUD:
    """Tests for price snapshot database operations."""

    def _setup_hotel(self, db):
        return db.upsert_hotel(Hotel(name="Test Hotel", city="Tokyo"))

    def test_add_snapshot(self, tmp_db):
        hotel_id = self._setup_hotel(tmp_db)
        snap = PriceSnapshot(
            hotel_id=hotel_id,
            check_in=date(2026, 8, 31),
            check_out=date(2026, 9, 3),
            room_type="Standard",
            platform="Booking.com",
            price=120000,
            currency="JPY",
        )
        snap_id = tmp_db.add_snapshot(snap)
        assert snap_id > 0

    def test_get_latest_snapshots(self, tmp_db):
        hotel_id = self._setup_hotel(tmp_db)
        check_in = date(2026, 8, 31)
        check_out = date(2026, 9, 3)

        for price in [120000, 115000, 110000]:
            tmp_db.add_snapshot(
                PriceSnapshot(
                    hotel_id=hotel_id,
                    check_in=check_in,
                    check_out=check_out,
                    platform="Booking.com",
                    price=price,
                    currency="JPY",
                )
            )

        latest = tmp_db.get_latest_snapshots(hotel_id, check_in, check_out)
        # Same platform deduplicates to only the most recent
        assert len(latest) == 1
        assert latest[0].price == 110000

    def test_get_latest_snapshots_dedup_by_platform(self, tmp_db):
        """Multiple scrapes per platform: only the newest is returned."""
        hotel_id = self._setup_hotel(tmp_db)
        check_in = date(2026, 8, 31)
        check_out = date(2026, 9, 3)

        # 2 scrapes for Booking.com, 2 for Agoda
        for platform, price in [
            ("Booking.com", 120000),
            ("Agoda", 115000),
            ("Booking.com", 110000),
            ("Agoda", 108000),
        ]:
            tmp_db.add_snapshot(
                PriceSnapshot(
                    hotel_id=hotel_id,
                    check_in=check_in,
                    check_out=check_out,
                    platform=platform,
                    price=price,
                    currency="JPY",
                )
            )

        latest = tmp_db.get_latest_snapshots(hotel_id, check_in, check_out)
        assert len(latest) == 2
        platforms = {s.platform: s.price for s in latest}
        assert platforms["Booking.com"] == 110000  # latest
        assert platforms["Agoda"] == 108000  # latest

    def test_get_latest_snapshots_empty(self, tmp_db):
        hotel_id = self._setup_hotel(tmp_db)
        snaps = tmp_db.get_latest_snapshots(hotel_id, date(2026, 1, 1), date(2026, 1, 3))
        assert snaps == []

    def test_get_latest_snapshots_filters_by_dates(self, tmp_db):
        hotel_id = self._setup_hotel(tmp_db)
        tmp_db.add_snapshot(
            PriceSnapshot(
                hotel_id=hotel_id,
                check_in=date(2026, 8, 31),
                check_out=date(2026, 9, 3),
                platform="Booking.com",
                price=120000,
                currency="JPY",
            )
        )
        tmp_db.add_snapshot(
            PriceSnapshot(
                hotel_id=hotel_id,
                check_in=date(2026, 10, 1),
                check_out=date(2026, 10, 5),
                platform="Booking.com",
                price=90000,
                currency="JPY",
            )
        )

        snaps = tmp_db.get_latest_snapshots(hotel_id, date(2026, 8, 31), date(2026, 9, 3))
        assert len(snaps) == 1
        assert snaps[0].price == 120000

    def test_snapshot_boolean_fields_persisted(self, tmp_db):
        hotel_id = self._setup_hotel(tmp_db)
        snap = PriceSnapshot(
            hotel_id=hotel_id,
            check_in=date(2026, 1, 1),
            check_out=date(2026, 1, 3),
            platform="Agoda",
            price=80000,
            currency="JPY",
            is_cancellable=True,
            breakfast_included=True,
            bathroom_type="private",
        )
        tmp_db.add_snapshot(snap)
        retrieved = tmp_db.get_latest_snapshots(hotel_id, date(2026, 1, 1), date(2026, 1, 3))[0]
        assert retrieved.is_cancellable is True
        assert retrieved.breakfast_included is True
        assert retrieved.bathroom_type == "private"

    def test_snapshot_null_boolean_fields(self, tmp_db):
        hotel_id = self._setup_hotel(tmp_db)
        snap = PriceSnapshot(
            hotel_id=hotel_id,
            check_in=date(2026, 1, 1),
            check_out=date(2026, 1, 3),
            platform="Booking.com",
            price=90000,
            currency="JPY",
            is_cancellable=None,
            breakfast_included=None,
        )
        tmp_db.add_snapshot(snap)
        retrieved = tmp_db.get_latest_snapshots(hotel_id, date(2026, 1, 1), date(2026, 1, 3))[0]
        assert retrieved.is_cancellable is None
        assert retrieved.breakfast_included is None

    def test_snapshot_amenities_persisted(self, tmp_db):
        hotel_id = self._setup_hotel(tmp_db)
        snap = PriceSnapshot(
            hotel_id=hotel_id,
            check_in=date(2026, 1, 1),
            check_out=date(2026, 1, 3),
            platform="Booking.com",
            price=90000,
            currency="JPY",
            amenities=["wifi", "pool", "gym"],
        )
        tmp_db.add_snapshot(snap)
        retrieved = tmp_db.get_latest_snapshots(hotel_id, date(2026, 1, 1), date(2026, 1, 3))[0]
        assert retrieved.amenities == ["wifi", "pool", "gym"]

    def test_get_price_history(self, tmp_db):
        hotel_id = self._setup_hotel(tmp_db)
        check_in = date(2026, 8, 31)
        check_out = date(2026, 9, 3)
        for price in [130000, 125000, 120000]:
            tmp_db.add_snapshot(
                PriceSnapshot(
                    hotel_id=hotel_id,
                    check_in=check_in,
                    check_out=check_out,
                    platform="Booking.com",
                    price=price,
                    currency="JPY",
                )
            )

        history = tmp_db.get_price_history(hotel_id, check_in, check_out)
        assert len(history) == 3
        # Ordered by scraped_at ASC
        assert history[0].price == 130000
        assert history[2].price == 120000

    def test_get_price_history_empty(self, tmp_db):
        hotel_id = self._setup_hotel(tmp_db)
        history = tmp_db.get_price_history(hotel_id, date(2026, 1, 1), date(2026, 1, 3))
        assert history == []

    def test_wipe_snapshots(self, tmp_db):
        hotel_id = self._setup_hotel(tmp_db)
        for price in [100000, 90000]:
            tmp_db.add_snapshot(
                PriceSnapshot(
                    hotel_id=hotel_id,
                    check_in=date(2026, 1, 1),
                    check_out=date(2026, 1, 3),
                    platform="Booking.com",
                    price=price,
                    currency="JPY",
                )
            )
        tmp_db.add_alert(
            Alert(
                alert_type="price_drop",
                severity="info",
                title="Test",
                message="Test",
            )
        )
        count = tmp_db.wipe_snapshots()
        assert count == 2
        assert tmp_db.get_all_snapshots() == []
        assert tmp_db.get_pending_alerts() == []

    def test_delete_snapshot(self, tmp_db):
        hotel_id = self._setup_hotel(tmp_db)
        snap_id_1 = tmp_db.add_snapshot(
            PriceSnapshot(
                hotel_id=hotel_id,
                check_in=date(2026, 1, 1),
                check_out=date(2026, 1, 3),
                platform="Booking.com",
                price=100000,
                currency="JPY",
            )
        )
        snap_id_2 = tmp_db.add_snapshot(
            PriceSnapshot(
                hotel_id=hotel_id,
                check_in=date(2026, 1, 1),
                check_out=date(2026, 1, 3),
                platform="Agoda",
                price=90000,
                currency="JPY",
            )
        )
        # Alert tied to snap 1
        tmp_db.add_alert(
            Alert(
                snapshot_id=snap_id_1,
                alert_type="price_drop",
                severity="info",
                title="Drop",
                message="price dropped",
            )
        )
        # Alert tied to snap 2
        tmp_db.add_alert(
            Alert(
                snapshot_id=snap_id_2,
                alert_type="price_drop",
                severity="info",
                title="Drop 2",
                message="price dropped 2",
            )
        )
        assert len(tmp_db.get_all_snapshots()) == 2
        assert len(tmp_db.get_pending_alerts()) == 2

        # Delete snap 1 — should remove its alert but keep snap 2's alert
        assert tmp_db.delete_snapshot(snap_id_1) is True
        assert len(tmp_db.get_all_snapshots()) == 1
        assert tmp_db.get_all_snapshots()[0].platform == "Agoda"
        remaining_alerts = tmp_db.get_pending_alerts()
        assert len(remaining_alerts) == 1
        assert remaining_alerts[0].title == "Drop 2"

    def test_delete_snapshot_not_found(self, tmp_db):
        assert tmp_db.delete_snapshot(9999) is False


# ── Alerts ─────────────────────────────────────────────────


class TestAlertCRUD:
    """Tests for alert database operations."""

    def test_add_alert(self, tmp_db):
        alert = Alert(
            alert_type="price_drop",
            severity="urgent",
            title="Price drop: Grand Hotel",
            message="Price dropped by 20%",
            price_diff=15000,
            percentage_diff=20.0,
        )
        alert_id = tmp_db.add_alert(alert)
        assert alert_id > 0

    def test_get_pending_alerts(self, tmp_db):
        tmp_db.add_alert(
            Alert(
                alert_type="price_drop",
                severity="important",
                title="Test Alert",
                message="Test message",
            )
        )
        pending = tmp_db.get_pending_alerts()
        assert len(pending) == 1
        assert pending[0].title == "Test Alert"
        assert pending[0].notified_telegram is False
        assert pending[0].notified_email is False

    def test_get_pending_alerts_empty(self, tmp_db):
        assert tmp_db.get_pending_alerts() == []

    def test_mark_alert_notified_telegram(self, tmp_db):
        alert_id = tmp_db.add_alert(
            Alert(
                alert_type="price_drop",
                severity="info",
                title="Test",
                message="Test",
            )
        )
        tmp_db.mark_alert_notified(alert_id, "telegram")

        # Should still show as pending (email not sent yet)
        pending = tmp_db.get_pending_alerts()
        assert len(pending) == 1
        assert pending[0].notified_telegram is True
        assert pending[0].notified_email is False

    def test_mark_alert_notified_email(self, tmp_db):
        alert_id = tmp_db.add_alert(
            Alert(
                alert_type="price_drop",
                severity="info",
                title="Test",
                message="Test",
            )
        )
        tmp_db.mark_alert_notified(alert_id, "email")

        pending = tmp_db.get_pending_alerts()
        assert len(pending) == 1
        assert pending[0].notified_email is True
        assert pending[0].notified_telegram is False

    def test_mark_both_channels_removes_from_pending(self, tmp_db):
        alert_id = tmp_db.add_alert(
            Alert(
                alert_type="price_drop",
                severity="info",
                title="Test",
                message="Test",
            )
        )
        tmp_db.mark_alert_notified(alert_id, "telegram")
        tmp_db.mark_alert_notified(alert_id, "email")

        pending = tmp_db.get_pending_alerts()
        assert len(pending) == 0

    def test_alert_with_booking_id(self, tmp_db):
        hotel_id = tmp_db.upsert_hotel(Hotel(name="Test", city="Tokyo"))
        booking_id = tmp_db.upsert_booking(
            Booking(
                hotel_id=hotel_id,
                check_in=date(2026, 1, 1),
                check_out=date(2026, 1, 3),
                booked_price=50000,
            )
        )
        tmp_db.add_alert(
            Alert(
                booking_id=booking_id,
                alert_type="price_drop",
                severity="info",
                title="Test",
                message="Test",
            )
        )
        pending = tmp_db.get_pending_alerts()
        assert pending[0].booking_id == booking_id

    def test_alert_created_at_set_automatically(self, tmp_db):
        tmp_db.add_alert(
            Alert(
                alert_type="price_drop",
                severity="info",
                title="Test",
                message="Test",
            )
        )
        pending = tmp_db.get_pending_alerts()
        assert pending[0].created_at is not None

    def test_multiple_pending_alerts(self, tmp_db):
        for i in range(5):
            tmp_db.add_alert(
                Alert(
                    alert_type="price_drop",
                    severity="info",
                    title=f"Alert {i}",
                    message=f"Message {i}",
                )
            )
        pending = tmp_db.get_pending_alerts()
        assert len(pending) == 5


# ── ScrapeRun ──────────────────────────────────────────────


class TestScrapeRun:
    """Tests for scrape run operations."""

    def test_start_scrape_run(self, tmp_db):
        run_id = tmp_db.start_scrape_run()
        assert run_id > 0

    def test_finish_scrape_run(self, tmp_db):
        run_id = tmp_db.start_scrape_run()
        tmp_db.finish_scrape_run(
            run_id,
            total=5,
            success=4,
            failed=1,
            errors=["timeout on hotel 3"],
            status="completed",
        )
        row = tmp_db.conn.execute("SELECT * FROM scrape_runs WHERE id=?", (run_id,)).fetchone()
        assert row["total_hotels"] == 5
        assert row["successful"] == 4
        assert row["failed"] == 1
        assert row["status"] == "completed"
        assert row["finished_at"] is not None
        errors = json.loads(row["errors"])
        assert errors == ["timeout on hotel 3"]

    def test_finish_scrape_run_failed_status(self, tmp_db):
        run_id = tmp_db.start_scrape_run()
        tmp_db.finish_scrape_run(
            run_id,
            total=3,
            success=0,
            failed=3,
            errors=["err1", "err2", "err3"],
            status="failed",
        )
        row = tmp_db.conn.execute("SELECT * FROM scrape_runs WHERE id=?", (run_id,)).fetchone()
        assert row["status"] == "failed"

    def test_finish_scrape_run_with_details(self, tmp_db):
        run_id = tmp_db.start_scrape_run()
        details = [
            {
                "hotel": "Hotel A",
                "prices": 5,
                "status": "ok",
                "sources": [
                    {
                        "platform": "booking.com",
                        "link": "https://...",
                        "price": 30000,
                        "currency": "JPY",
                    },
                ],
            },
            {"hotel": "Hotel B", "prices": 0, "status": "no prices"},
        ]
        tmp_db.finish_scrape_run(run_id, 2, 1, 1, ["Hotel B: no prices"], details=details)
        row = tmp_db.conn.execute("SELECT * FROM scrape_runs WHERE id=?", (run_id,)).fetchone()
        parsed_details = json.loads(row["details"])
        assert len(parsed_details) == 2
        assert parsed_details[0]["hotel"] == "Hotel A"
        assert parsed_details[0]["sources"][0]["platform"] == "booking.com"

    def test_get_all_scrape_runs(self, tmp_db):
        r1 = tmp_db.start_scrape_run()
        tmp_db.finish_scrape_run(r1, 1, 1, 0, [])
        r2 = tmp_db.start_scrape_run()
        tmp_db.finish_scrape_run(r2, 2, 2, 0, [], details=[{"hotel": "X", "prices": 3}])

        runs = tmp_db.get_all_scrape_runs()
        assert len(runs) == 2
        # Newest first
        assert runs[0]["id"] == r2
        assert runs[0]["details"] == [{"hotel": "X", "prices": 3}]
        assert isinstance(runs[1]["errors"], list)

    def test_get_all_scrape_runs_limit(self, tmp_db):
        for _ in range(5):
            rid = tmp_db.start_scrape_run()
            tmp_db.finish_scrape_run(rid, 1, 1, 0, [])
        runs = tmp_db.get_all_scrape_runs(limit=3)
        assert len(runs) == 3

    def test_get_scrape_run_by_id(self, tmp_db):
        run_id = tmp_db.start_scrape_run()
        details = [{"hotel": "Test", "prices": 2, "status": "ok"}]
        tmp_db.finish_scrape_run(run_id, 1, 1, 0, [], details=details)

        run = tmp_db.get_scrape_run_by_id(run_id)
        assert run is not None
        assert run["id"] == run_id
        assert run["details"] == details
        assert run["status"] == "completed"

    def test_get_scrape_run_by_id_not_found(self, tmp_db):
        assert tmp_db.get_scrape_run_by_id(9999) is None

    def test_get_stats_includes_details(self, tmp_db):
        run_id = tmp_db.start_scrape_run()
        details = [{"hotel": "A", "prices": 1}]
        tmp_db.finish_scrape_run(run_id, 1, 1, 0, [], details=details)
        stats = tmp_db.get_stats()
        assert stats["last_run"]["details"] == details


# ── Stats ──────────────────────────────────────────────────


class TestStats:
    """Tests for database stats."""

    def test_stats_empty_db(self, tmp_db):
        stats = tmp_db.get_stats()
        assert stats["hotels"] == 0
        assert stats["active_bookings"] == 0
        assert stats["price_snapshots"] == 0
        assert stats["total_alerts"] == 0
        assert stats["last_run"] is None

    def test_stats_with_data(self, tmp_db):
        # Add hotels
        h1 = tmp_db.upsert_hotel(Hotel(name="Hotel A", city="Tokyo"))
        h2 = tmp_db.upsert_hotel(Hotel(name="Hotel B", city="Osaka"))

        # Add bookings (1 active, 1 cancelled)
        tmp_db.upsert_booking(
            Booking(
                hotel_id=h1,
                check_in=date(2026, 1, 1),
                check_out=date(2026, 1, 3),
                booked_price=50000,
                status="active",
            )
        )
        tmp_db.upsert_booking(
            Booking(
                hotel_id=h2,
                check_in=date(2026, 2, 1),
                check_out=date(2026, 2, 3),
                booked_price=60000,
                status="cancelled",
            )
        )

        # Add snapshots
        tmp_db.add_snapshot(
            PriceSnapshot(
                hotel_id=h1,
                check_in=date(2026, 1, 1),
                check_out=date(2026, 1, 3),
                platform="Booking.com",
                price=45000,
                currency="JPY",
            )
        )

        # Add alerts
        tmp_db.add_alert(
            Alert(
                alert_type="price_drop",
                severity="info",
                title="Test",
                message="Test",
            )
        )

        # Add scrape run
        run_id = tmp_db.start_scrape_run()
        tmp_db.finish_scrape_run(run_id, 2, 2, 0, [], "completed")

        stats = tmp_db.get_stats()
        assert stats["hotels"] == 2
        assert stats["active_bookings"] == 1  # Only active ones counted
        assert stats["price_snapshots"] == 1
        assert stats["total_alerts"] == 1
        assert stats["last_run"] is not None
        assert stats["last_run"]["status"] == "completed"


# ── Edge Cases ─────────────────────────────────────────────


class TestEdgeCases:
    """Edge-case tests for the database."""

    def test_close_and_reopen(self, tmp_path):
        db_path = tmp_path / "test.db"
        db1 = Database(str(db_path))
        db1.upsert_hotel(Hotel(name="Persist Hotel", city="Tokyo"))
        db1.close()

        db2 = Database(str(db_path))
        hotels = db2.get_all_hotels()
        assert len(hotels) == 1
        assert hotels[0].name == "Persist Hotel"
        db2.close()

    def test_hotel_with_special_characters(self, tmp_db):
        hotel = Hotel(
            name="Hôtel de l'Étoile",
            city="Tōkyō",
            notes="5★ — great café!",
        )
        hotel_id = tmp_db.upsert_hotel(hotel)
        retrieved = tmp_db.get_hotel(hotel_id)
        assert retrieved.name == "Hôtel de l'Étoile"
        assert retrieved.city == "Tōkyō"
        assert retrieved.notes == "5★ — great café!"

    def test_snapshot_with_zero_price(self, tmp_db):
        hotel_id = tmp_db.upsert_hotel(Hotel(name="Free Hotel", city="Tokyo"))
        tmp_db.add_snapshot(
            PriceSnapshot(
                hotel_id=hotel_id,
                check_in=date(2026, 1, 1),
                check_out=date(2026, 1, 3),
                platform="Direct",
                price=0.0,
                currency="JPY",
            )
        )
        snaps = tmp_db.get_latest_snapshots(hotel_id, date(2026, 1, 1), date(2026, 1, 3))
        assert snaps[0].price == 0.0

    def test_watchlist_crud(self, tmp_db):
        hotel_id = tmp_db.upsert_hotel(Hotel(name="Watch Hotel", city="Kyoto"))
        entry = WatchlistEntry(
            hotel_id=hotel_id,
            check_in=date(2026, 5, 1),
            check_out=date(2026, 5, 5),
            max_price=100000,
            priority="high",
        )
        wl_id = tmp_db.add_watchlist(entry)
        assert wl_id > 0


class TestAlertExists:
    """Tests for the alert dedup method."""

    def test_no_matching_alert(self, tmp_db, sample_hotel, sample_snapshot):
        hotel_id = tmp_db.upsert_hotel(sample_hotel)
        sample_snapshot.hotel_id = hotel_id
        snap_id = tmp_db.add_snapshot(sample_snapshot)
        assert tmp_db.alert_exists(1, "price_drop", snap_id) is False

    def test_matching_alert_exists(self, tmp_db, sample_hotel, sample_booking, sample_snapshot):
        hotel_id = tmp_db.upsert_hotel(sample_hotel)
        sample_booking.hotel_id = hotel_id
        booking_id = tmp_db.upsert_booking(sample_booking)
        sample_snapshot.hotel_id = hotel_id
        snap_id = tmp_db.add_snapshot(sample_snapshot)

        from hotel_agent.models import Alert

        alert = Alert(
            booking_id=booking_id,
            snapshot_id=snap_id,
            alert_type="price_drop",
            severity="info",
            title="Test",
            message="Test alert",
        )
        tmp_db.add_alert(alert)
        assert tmp_db.alert_exists(booking_id, "price_drop", snap_id) is True

    def test_different_alert_type_not_matched(
        self, tmp_db, sample_hotel, sample_booking, sample_snapshot
    ):
        hotel_id = tmp_db.upsert_hotel(sample_hotel)
        sample_booking.hotel_id = hotel_id
        booking_id = tmp_db.upsert_booking(sample_booking)
        sample_snapshot.hotel_id = hotel_id
        snap_id = tmp_db.add_snapshot(sample_snapshot)

        from hotel_agent.models import Alert

        alert = Alert(
            booking_id=booking_id,
            snapshot_id=snap_id,
            alert_type="price_drop",
            severity="info",
            title="Test",
            message="Test",
        )
        tmp_db.add_alert(alert)
        # Different alert_type should not match
        assert tmp_db.alert_exists(booking_id, "upgrade", snap_id) is False


class TestGetSeenPlatforms:
    """Tests for the get_seen_platforms query."""

    def _insert_hotel(self, db):
        from hotel_agent.models import Hotel

        return db.upsert_hotel(Hotel(name="Test Hotel", city="Tokyo"))

    def test_empty_db_returns_empty(self, tmp_db):
        assert tmp_db.get_seen_platforms() == []

    def test_returns_distinct_platforms(self, tmp_db, sample_snapshot):
        hotel_id = self._insert_hotel(tmp_db)
        sample_snapshot.hotel_id = hotel_id
        sample_snapshot.platform = "booking.com"
        tmp_db.add_snapshot(sample_snapshot)

        from hotel_agent.models import PriceSnapshot

        snap2 = PriceSnapshot(
            hotel_id=hotel_id,
            check_in=sample_snapshot.check_in,
            check_out=sample_snapshot.check_out,
            platform="agoda",
            price=90000,
            currency="JPY",
        )
        tmp_db.add_snapshot(snap2)
        # Add duplicate platform
        snap3 = PriceSnapshot(
            hotel_id=hotel_id,
            check_in=sample_snapshot.check_in,
            check_out=sample_snapshot.check_out,
            platform="booking.com",
            price=95000,
            currency="JPY",
        )
        tmp_db.add_snapshot(snap3)

        seen = tmp_db.get_seen_platforms()
        assert sorted(seen) == ["agoda", "booking.com"]
