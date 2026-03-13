"""Tests for hotel_agent.models module."""

from datetime import date

import pytest

from hotel_agent.models import (
    Alert,
    Booking,
    Hotel,
    PriceSnapshot,
    ScrapeRun,
    TravelerComposition,
    WatchlistEntry,
)

# ── TravelerComposition ────────────────────────────────────


class TestTravelerComposition:
    """Tests for TravelerComposition dataclass."""

    def test_default_creation(self):
        tc = TravelerComposition()
        assert tc.adults == 2
        assert tc.children_ages == []

    def test_custom_creation(self):
        tc = TravelerComposition(adults=3, children_ages=[4, 7, 12])
        assert tc.adults == 3
        assert tc.children_ages == [4, 7, 12]

    def test_children_count_no_children(self):
        tc = TravelerComposition(adults=2)
        assert tc.children_count == 0

    def test_children_count_with_children(self):
        tc = TravelerComposition(adults=2, children_ages=[4, 7])
        assert tc.children_count == 2

    def test_total_guests_adults_only(self):
        tc = TravelerComposition(adults=1)
        assert tc.total_guests == 1

    def test_total_guests_with_children(self):
        tc = TravelerComposition(adults=2, children_ages=[4, 7])
        assert tc.total_guests == 4

    def test_str_single_adult(self):
        tc = TravelerComposition(adults=1)
        assert str(tc) == "1 adult"

    def test_str_multiple_adults(self):
        tc = TravelerComposition(adults=2)
        assert str(tc) == "2 adults"

    def test_str_with_one_child(self):
        tc = TravelerComposition(adults=2, children_ages=[5])
        assert str(tc) == "2 adults + 1 child (ages 5)"

    def test_str_with_multiple_children(self):
        tc = TravelerComposition(adults=2, children_ages=[4, 7])
        assert str(tc) == "2 adults + 2 children (ages 4, 7)"

    def test_to_dict(self):
        tc = TravelerComposition(adults=2, children_ages=[4, 7])
        d = tc.to_dict()
        assert d == {"adults": 2, "children_ages": [4, 7]}

    def test_to_dict_no_children(self):
        tc = TravelerComposition(adults=1)
        d = tc.to_dict()
        assert d == {"adults": 1, "children_ages": []}

    def test_from_dict(self):
        data = {"adults": 3, "children_ages": [2, 10]}
        tc = TravelerComposition.from_dict(data)
        assert tc.adults == 3
        assert tc.children_ages == [2, 10]

    def test_from_dict_with_children_key(self):
        """from_dict supports 'children' as an alias for 'children_ages'."""
        data = {"adults": 2, "children": [5, 8]}
        tc = TravelerComposition.from_dict(data)
        assert tc.children_ages == [5, 8]

    def test_from_dict_defaults(self):
        tc = TravelerComposition.from_dict({})
        assert tc.adults == 2
        assert tc.children_ages == []

    def test_from_dict_none_children(self):
        data = {"adults": 2, "children_ages": None}
        tc = TravelerComposition.from_dict(data)
        assert tc.children_ages == []

    def test_roundtrip_to_from_dict(self):
        original = TravelerComposition(adults=3, children_ages=[1, 5, 9])
        restored = TravelerComposition.from_dict(original.to_dict())
        assert restored.adults == original.adults
        assert restored.children_ages == original.children_ages


# ── Hotel ──────────────────────────────────────────────────


class TestHotel:
    """Tests for Hotel dataclass."""

    def test_default_creation(self):
        h = Hotel()
        assert h.id is None
        assert h.name == ""
        assert h.city == ""
        assert h.country == ""
        assert h.stars is None
        assert h.url == ""
        assert h.platform == ""
        assert h.added_at is None

    def test_creation_with_values(self, sample_hotel):
        assert sample_hotel.name == "Namba Oriental Hotel"
        assert sample_hotel.city == "Osaka"
        assert sample_hotel.country == "Japan"
        assert sample_hotel.address == "2-10 Nanbasennichimae, Chuo Ward"
        assert sample_hotel.platform == "Booking.com"

    def test_creation_with_stars(self):
        h = Hotel(name="Grand Hotel", stars=5)
        assert h.stars == 5

    def test_creation_with_notes(self):
        h = Hotel(name="Test Hotel", notes="Great location")
        assert h.notes == "Great location"


# ── Booking ────────────────────────────────────────────────


class TestBooking:
    """Tests for Booking dataclass."""

    def test_default_creation(self):
        b = Booking()
        assert b.id is None
        assert b.hotel_id == 0
        assert b.booked_price == 0.0
        assert b.currency == "JPY"
        assert b.status == "active"
        assert b.bathroom_type == "private"

    def test_creation_with_values(self, sample_booking):
        assert sample_booking.check_in == date(2026, 8, 31)
        assert sample_booking.check_out == date(2026, 9, 3)
        assert sample_booking.booked_price == 135833
        assert sample_booking.room_type == "Standard Double"
        assert sample_booking.booking_reference == "628875015"
        assert sample_booking.platform == "Agoda"

    def test_nights_calculation(self, sample_booking):
        assert sample_booking.nights == 3

    def test_nights_one_night(self):
        b = Booking(check_in=date(2026, 1, 1), check_out=date(2026, 1, 2))
        assert b.nights == 1

    def test_nights_same_day(self):
        """Same day check-in and check-out results in 0 nights."""
        b = Booking(check_in=date(2026, 1, 1), check_out=date(2026, 1, 1))
        assert b.nights == 0

    def test_nights_no_dates(self):
        b = Booking()
        assert b.nights == 0

    def test_nights_no_check_out(self):
        b = Booking(check_in=date(2026, 1, 1))
        assert b.nights == 0

    def test_nights_no_check_in(self):
        b = Booking(check_out=date(2026, 1, 5))
        assert b.nights == 0

    def test_price_per_night(self, sample_booking):
        # 135833 / 3 nights
        assert sample_booking.price_per_night == pytest.approx(45277.67, rel=0.01)

    def test_price_per_night_one_night(self):
        b = Booking(
            check_in=date(2026, 1, 1),
            check_out=date(2026, 1, 2),
            booked_price=50000,
        )
        assert b.price_per_night == 50000

    def test_price_per_night_zero_nights(self):
        """When nights is 0, price_per_night returns the booked_price."""
        b = Booking(booked_price=10000)
        assert b.price_per_night == 10000

    def test_price_per_night_zero_price(self):
        b = Booking(
            check_in=date(2026, 1, 1),
            check_out=date(2026, 1, 3),
            booked_price=0,
        )
        assert b.price_per_night == 0.0

    def test_travelers_default(self):
        b = Booking()
        assert b.travelers.adults == 2
        assert b.travelers.children_ages == []

    def test_cancellable_booking(self):
        b = Booking(
            is_cancellable=True,
            cancellation_deadline=date(2026, 8, 29),
        )
        assert b.is_cancellable is True
        assert b.cancellation_deadline == date(2026, 8, 29)

    def test_status_values(self):
        for status in ["active", "cancelled", "completed"]:
            b = Booking(status=status)
            assert b.status == status


# ── PriceSnapshot ──────────────────────────────────────────


class TestPriceSnapshot:
    """Tests for PriceSnapshot dataclass."""

    def test_default_creation(self):
        ps = PriceSnapshot()
        assert ps.id is None
        assert ps.hotel_id == 0
        assert ps.price == 0.0
        assert ps.currency == "JPY"
        assert ps.amenities == []
        assert ps.is_cancellable is None
        assert ps.breakfast_included is None

    def test_creation_with_values(self, sample_snapshot):
        assert sample_snapshot.check_in == date(2026, 8, 31)
        assert sample_snapshot.check_out == date(2026, 9, 3)
        assert sample_snapshot.price == 120000
        assert sample_snapshot.platform == "Booking.com"
        assert sample_snapshot.is_cancellable is True
        assert sample_snapshot.breakfast_included is False

    def test_amenities_list(self):
        ps = PriceSnapshot(amenities=["wifi", "pool", "gym"])
        assert len(ps.amenities) == 3
        assert "pool" in ps.amenities

    def test_scraped_at_default_none(self):
        ps = PriceSnapshot()
        assert ps.scraped_at is None

    def test_with_screenshot(self):
        ps = PriceSnapshot(screenshot_path="/data/screenshots/hotel1.png")
        assert ps.screenshot_path == "/data/screenshots/hotel1.png"


# ── Alert ──────────────────────────────────────────────────


class TestAlert:
    """Tests for Alert dataclass."""

    def test_default_creation(self):
        a = Alert()
        assert a.id is None
        assert a.booking_id is None
        assert a.watchlist_id is None
        assert a.snapshot_id is None
        assert a.alert_type == ""
        assert a.severity == "info"
        assert a.title == ""
        assert a.message == ""
        assert a.price_diff == 0.0
        assert a.percentage_diff == 0.0
        assert a.notified_telegram is False
        assert a.notified_email is False

    def test_price_drop_alert(self):
        a = Alert(
            booking_id=1,
            snapshot_id=5,
            alert_type="price_drop",
            severity="urgent",
            title="Price drop: Grand Hotel",
            message="Price dropped by 20%",
            price_diff=15000,
            percentage_diff=20.0,
        )
        assert a.alert_type == "price_drop"
        assert a.severity == "urgent"
        assert a.price_diff == 15000

    def test_upgrade_alert(self):
        a = Alert(
            alert_type="upgrade",
            severity="important",
            title="Upgrade available",
        )
        assert a.alert_type == "upgrade"


# ── WatchlistEntry ─────────────────────────────────────────


class TestWatchlistEntry:
    """Tests for WatchlistEntry dataclass."""

    def test_default_creation(self):
        w = WatchlistEntry()
        assert w.id is None
        assert w.hotel_id == 0
        assert w.max_price is None
        assert w.currency == "JPY"
        assert w.priority == "normal"

    def test_creation_with_values(self):
        w = WatchlistEntry(
            hotel_id=1,
            check_in=date(2026, 9, 1),
            check_out=date(2026, 9, 5),
            max_price=100000,
            priority="high",
        )
        assert w.hotel_id == 1
        assert w.max_price == 100000
        assert w.priority == "high"


# ── ScrapeRun ──────────────────────────────────────────────


class TestScrapeRun:
    """Tests for ScrapeRun dataclass."""

    def test_default_creation(self):
        sr = ScrapeRun()
        assert sr.id is None
        assert sr.total_hotels == 0
        assert sr.successful == 0
        assert sr.failed == 0
        assert sr.errors == []
        assert sr.status == "running"

    def test_creation_with_values(self):
        sr = ScrapeRun(
            total_hotels=10,
            successful=8,
            failed=2,
            errors=["timeout on hotel 3", "404 on hotel 7"],
            status="completed",
        )
        assert sr.total_hotels == 10
        assert sr.successful == 8
        assert sr.failed == 2
        assert len(sr.errors) == 2
        assert sr.status == "completed"

    def test_errors_independent_instances(self):
        """Each ScrapeRun should have its own errors list."""
        sr1 = ScrapeRun()
        sr2 = ScrapeRun()
        sr1.errors.append("error1")
        assert sr2.errors == []
