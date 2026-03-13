"""Tests for hotel_agent.analysis.comparator module."""

from datetime import date

import pytest

from hotel_agent.analysis.comparator import (
    _describe_upgrade,
    _is_upgrade,
    _price_drop_severity,
    compare_booking_to_snapshots,
    run_analysis,
)
from hotel_agent.config import (
    AlertThresholds,
    AppConfig,
    CurrencyConfig,
    PriceDropThresholds,
    UpgradeThresholds,
)
from hotel_agent.models import Booking, Hotel, PriceSnapshot, TravelerComposition

# ── Helpers ────────────────────────────────────────────────


def _make_booking(**kwargs):
    """Create a booking with sensible defaults."""
    defaults = dict(
        id=1,
        hotel_id=1,
        check_in=date(2026, 8, 31),
        check_out=date(2026, 9, 3),
        travelers=TravelerComposition(adults=2),
        room_type="Standard Double",
        booked_price=100000,
        currency="JPY",
        is_cancellable=False,
        breakfast_included=False,
        bathroom_type="private",
        platform="Agoda",
        status="active",
    )
    defaults.update(kwargs)
    return Booking(**defaults)


def _make_snapshot(**kwargs):
    """Create a snapshot with sensible defaults."""
    defaults = dict(
        id=10,
        hotel_id=1,
        check_in=date(2026, 8, 31),
        check_out=date(2026, 9, 3),
        travelers=TravelerComposition(adults=2),
        room_type="Standard Double",
        platform="Booking.com",
        price=90000,
        currency="JPY",
        is_cancellable=False,
        breakfast_included=False,
        bathroom_type="private",
    )
    defaults.update(kwargs)
    return PriceSnapshot(**defaults)


def _make_hotel(**kwargs):
    defaults = dict(id=1, name="Test Hotel", city="Tokyo", country="Japan")
    defaults.update(kwargs)
    return Hotel(**defaults)


def _make_config(**kwargs):
    cfg = AppConfig(_env_file=None)
    cfg.currency = CurrencyConfig(
        base="ILS",
        rates={"JPY_to_ILS": 0.0196008, "USD_to_ILS": 3.0912},
    )
    cfg.alerts = AlertThresholds(
        price_drop=PriceDropThresholds(min_absolute=10.0, min_percentage=5.0),
        upgrade=UpgradeThresholds(max_extra_cost=50.0, max_extra_percentage=10.0),
    )
    for k, v in kwargs.items():
        setattr(cfg, k, v)
    return cfg


# ── Price Drop Severity ───────────────────────────────────


class TestPriceDropSeverity:
    """Tests for _price_drop_severity helper."""

    def test_urgent_above_20_percent(self):
        assert _price_drop_severity(25.0) == "urgent"

    def test_urgent_exactly_20_percent(self):
        assert _price_drop_severity(20.0) == "urgent"

    def test_important_between_10_and_20(self):
        assert _price_drop_severity(15.0) == "important"

    def test_important_exactly_10_percent(self):
        assert _price_drop_severity(10.0) == "important"

    def test_info_below_10_percent(self):
        assert _price_drop_severity(5.0) == "info"

    def test_info_zero_percent(self):
        assert _price_drop_severity(0.0) == "info"


# ── Is Upgrade ─────────────────────────────────────────────


class TestIsUpgrade:
    """Tests for _is_upgrade helper."""

    def test_cancellable_upgrade(self):
        booking = _make_booking(is_cancellable=False)
        snap = _make_snapshot(is_cancellable=True)
        assert _is_upgrade(booking, snap) is True

    def test_breakfast_upgrade(self):
        booking = _make_booking(breakfast_included=False)
        snap = _make_snapshot(breakfast_included=True)
        assert _is_upgrade(booking, snap) is True

    def test_bathroom_upgrade(self):
        booking = _make_booking(bathroom_type="shared")
        snap = _make_snapshot(bathroom_type="private")
        assert _is_upgrade(booking, snap) is True

    def test_multiple_upgrades(self):
        booking = _make_booking(
            is_cancellable=False,
            breakfast_included=False,
            bathroom_type="shared",
        )
        snap = _make_snapshot(
            is_cancellable=True,
            breakfast_included=True,
            bathroom_type="private",
        )
        assert _is_upgrade(booking, snap) is True

    def test_no_upgrade_same_features(self):
        booking = _make_booking(
            is_cancellable=True,
            breakfast_included=True,
            bathroom_type="private",
        )
        snap = _make_snapshot(
            is_cancellable=True,
            breakfast_included=True,
            bathroom_type="private",
        )
        assert _is_upgrade(booking, snap) is False

    def test_no_upgrade_downgrade(self):
        """A snapshot with fewer features is not an upgrade."""
        booking = _make_booking(is_cancellable=True, breakfast_included=True)
        snap = _make_snapshot(is_cancellable=False, breakfast_included=False)
        assert _is_upgrade(booking, snap) is False


# ── Describe Upgrade ──────────────────────────────────────


class TestDescribeUpgrade:
    """Tests for _describe_upgrade helper."""

    def test_cancellable_description(self):
        booking = _make_booking(is_cancellable=False)
        snap = _make_snapshot(is_cancellable=True)
        desc = _describe_upgrade(booking, snap)
        assert "free cancellation" in desc

    def test_breakfast_description(self):
        booking = _make_booking(breakfast_included=False)
        snap = _make_snapshot(breakfast_included=True)
        desc = _describe_upgrade(booking, snap)
        assert "breakfast included" in desc

    def test_bathroom_description(self):
        booking = _make_booking(bathroom_type="shared")
        snap = _make_snapshot(bathroom_type="private")
        desc = _describe_upgrade(booking, snap)
        assert "private bathroom" in desc

    def test_multiple_improvements(self):
        booking = _make_booking(
            is_cancellable=False,
            breakfast_included=False,
        )
        snap = _make_snapshot(
            is_cancellable=True,
            breakfast_included=True,
        )
        desc = _describe_upgrade(booking, snap)
        assert "free cancellation" in desc
        assert "breakfast included" in desc

    def test_no_improvements_returns_default(self):
        booking = _make_booking(is_cancellable=True, breakfast_included=True)
        snap = _make_snapshot(is_cancellable=True, breakfast_included=True)
        desc = _describe_upgrade(booking, snap)
        assert desc == "better room type"


# ── Price Drop Detection ──────────────────────────────────


class TestPriceDropDetection:
    """Tests for price drop detection in compare_booking_to_snapshots."""

    def test_price_drop_above_threshold(self):
        """A significant price drop should generate an alert."""
        booking = _make_booking(booked_price=100000)
        snap = _make_snapshot(price=85000)  # 15% drop = 15000 JPY
        hotel = _make_hotel()
        config = _make_config()

        alerts = compare_booking_to_snapshots(booking, hotel, [snap], config)
        price_drops = [a for a in alerts if a.alert_type == "price_drop"]
        assert len(price_drops) >= 1
        assert price_drops[0].price_diff == 15000
        assert price_drops[0].percentage_diff == pytest.approx(15.0)
        assert price_drops[0].severity == "important"

    def test_price_drop_below_absolute_threshold(self):
        """A price drop below min_absolute should NOT generate an alert."""
        booking = _make_booking(booked_price=100000)
        # Drop of 5 JPY, which is < min_absolute of 10
        snap = _make_snapshot(price=99995)
        hotel = _make_hotel()
        config = _make_config()

        alerts = compare_booking_to_snapshots(booking, hotel, [snap], config)
        price_drops = [a for a in alerts if a.alert_type == "price_drop"]
        assert len(price_drops) == 0

    def test_price_drop_below_percentage_threshold(self):
        """A price drop below min_percentage should NOT generate an alert."""
        booking = _make_booking(booked_price=100000)
        # Drop of 4% = 4000 JPY (above absolute 10 but below 5%)
        snap = _make_snapshot(price=96000)
        hotel = _make_hotel()
        config = _make_config()

        alerts = compare_booking_to_snapshots(booking, hotel, [snap], config)
        price_drops = [a for a in alerts if a.alert_type == "price_drop"]
        assert len(price_drops) == 0

    def test_price_drop_exact_threshold(self):
        """A price drop at exactly the threshold should generate an alert."""
        booking = _make_booking(booked_price=100000)
        # Exactly 5% = 5000 JPY drop, and 5000 >= 10 (min_absolute)
        snap = _make_snapshot(price=95000)
        hotel = _make_hotel()
        config = _make_config()

        alerts = compare_booking_to_snapshots(booking, hotel, [snap], config)
        price_drops = [a for a in alerts if a.alert_type == "price_drop"]
        assert len(price_drops) == 1
        assert price_drops[0].percentage_diff == pytest.approx(5.0)

    def test_price_drop_urgent_severity(self):
        """A 20%+ drop should be urgent."""
        booking = _make_booking(booked_price=100000)
        snap = _make_snapshot(price=75000)  # 25% drop
        hotel = _make_hotel()
        config = _make_config()

        alerts = compare_booking_to_snapshots(booking, hotel, [snap], config)
        price_drops = [a for a in alerts if a.alert_type == "price_drop"]
        assert price_drops[0].severity == "urgent"

    def test_price_drop_info_severity(self):
        """A 5-10% drop should be info severity."""
        booking = _make_booking(booked_price=100000)
        snap = _make_snapshot(price=93000)  # 7% drop
        hotel = _make_hotel()
        config = _make_config()

        alerts = compare_booking_to_snapshots(booking, hotel, [snap], config)
        price_drops = [a for a in alerts if a.alert_type == "price_drop"]
        assert price_drops[0].severity == "info"

    def test_price_drop_alert_message_content(self):
        """Price drop alert message should contain key details."""
        booking = _make_booking(booked_price=100000, currency="JPY")
        snap = _make_snapshot(price=80000, platform="Booking.com")
        hotel = _make_hotel(name="Grand Hotel", city="Tokyo")
        config = _make_config()

        alerts = compare_booking_to_snapshots(booking, hotel, [snap], config)
        price_drops = [a for a in alerts if a.alert_type == "price_drop"]
        msg = price_drops[0].message
        assert "Grand Hotel" in msg
        assert "Tokyo" in msg
        assert "Booking.com" in msg
        assert "100,000" in msg
        assert "80,000" in msg


# ── Only Cancellable Filter ───────────────────────────────


class TestOnlyCancellableFilter:
    """Tests for the only_cancellable config flag."""

    def test_only_cancellable_skips_non_cancellable(self):
        """With only_cancellable=True, non-cancellable snapshots are ignored."""
        booking = _make_booking(booked_price=100000)
        snap = _make_snapshot(price=80000, is_cancellable=False)
        hotel = _make_hotel()
        config = _make_config()
        config.alerts.only_cancellable = True

        alerts = compare_booking_to_snapshots(booking, hotel, [snap], config)
        assert alerts == []

    def test_only_cancellable_keeps_cancellable(self):
        """With only_cancellable=True, cancellable snapshots are kept."""
        booking = _make_booking(booked_price=100000)
        snap = _make_snapshot(price=80000, is_cancellable=True)
        hotel = _make_hotel()
        config = _make_config()
        config.alerts.only_cancellable = True

        alerts = compare_booking_to_snapshots(booking, hotel, [snap], config)
        price_drops = [a for a in alerts if a.alert_type == "price_drop"]
        assert len(price_drops) >= 1

    def test_only_cancellable_skips_none_cancellable(self):
        """With only_cancellable=True, snapshots with is_cancellable=None are skipped."""
        booking = _make_booking(booked_price=100000)
        snap = _make_snapshot(price=80000, is_cancellable=None)
        hotel = _make_hotel()
        config = _make_config()
        config.alerts.only_cancellable = True

        alerts = compare_booking_to_snapshots(booking, hotel, [snap], config)
        assert alerts == []

    def test_only_cancellable_false_keeps_all(self):
        """With only_cancellable=False (default), all snapshots are considered."""
        booking = _make_booking(booked_price=100000)
        snaps = [
            _make_snapshot(id=10, price=80000, is_cancellable=False),
            _make_snapshot(id=11, price=75000, is_cancellable=True),
        ]
        hotel = _make_hotel()
        config = _make_config()
        config.alerts.only_cancellable = False

        alerts = compare_booking_to_snapshots(booking, hotel, snaps, config)
        price_drops = [a for a in alerts if a.alert_type == "price_drop"]
        assert len(price_drops) == 1
        # Both snapshots should appear in the consolidated details
        assert len(price_drops[0].details) == 2

    def test_only_cancellable_mixed_snapshots(self):
        """With only_cancellable=True, only cancellable snapshots generate alerts."""
        booking = _make_booking(booked_price=100000)
        snaps = [
            _make_snapshot(id=10, price=80000, is_cancellable=False),
            _make_snapshot(id=11, price=75000, is_cancellable=True),
            _make_snapshot(id=12, price=70000, is_cancellable=None),
        ]
        hotel = _make_hotel()
        config = _make_config()
        config.alerts.only_cancellable = True

        alerts = compare_booking_to_snapshots(booking, hotel, snaps, config)
        price_drops = [a for a in alerts if a.alert_type == "price_drop"]
        assert len(price_drops) == 1
        # Only the cancellable snapshot should be in details
        assert len(price_drops[0].details) == 1
        assert price_drops[0].details[0]["snapshot_id"] == 11


# ── No Alert When Prices Are Higher ───────────────────────


class TestNoAlertHigherPrices:
    """Tests that no alerts are generated when snapshot is more expensive."""

    def test_higher_price_no_price_drop(self):
        booking = _make_booking(booked_price=100000)
        snap = _make_snapshot(price=110000)  # More expensive
        hotel = _make_hotel()
        config = _make_config()

        alerts = compare_booking_to_snapshots(booking, hotel, [snap], config)
        price_drops = [a for a in alerts if a.alert_type == "price_drop"]
        assert len(price_drops) == 0

    def test_same_price_no_price_drop(self):
        booking = _make_booking(booked_price=100000)
        snap = _make_snapshot(price=100000)
        hotel = _make_hotel()
        config = _make_config()

        alerts = compare_booking_to_snapshots(booking, hotel, [snap], config)
        price_drops = [a for a in alerts if a.alert_type == "price_drop"]
        assert len(price_drops) == 0

    def test_empty_snapshots_no_alerts(self):
        booking = _make_booking()
        hotel = _make_hotel()
        config = _make_config()

        alerts = compare_booking_to_snapshots(booking, hotel, [], config)
        assert alerts == []


# ── Upgrade Detection ─────────────────────────────────────


class TestUpgradeDetection:
    """Tests for upgrade detection in compare_booking_to_snapshots."""

    def test_cancellable_upgrade_at_same_price(self):
        booking = _make_booking(
            booked_price=100000,
            is_cancellable=False,
        )
        snap = _make_snapshot(
            price=100000,
            is_cancellable=True,
        )
        hotel = _make_hotel()
        config = _make_config()

        alerts = compare_booking_to_snapshots(booking, hotel, [snap], config)
        upgrades = [a for a in alerts if a.alert_type == "upgrade"]
        assert len(upgrades) >= 1
        assert "free cancellation" in upgrades[0].message

    def test_breakfast_upgrade_within_cost(self):
        booking = _make_booking(
            booked_price=100000,
            breakfast_included=False,
        )
        # Snap is 30 more, within upgrade_max_extra_cost of 50
        snap = _make_snapshot(
            price=100030,
            breakfast_included=True,
        )
        hotel = _make_hotel()
        config = _make_config()

        alerts = compare_booking_to_snapshots(booking, hotel, [snap], config)
        upgrades = [a for a in alerts if a.alert_type == "upgrade"]
        assert len(upgrades) >= 1
        assert "breakfast included" in upgrades[0].message

    def test_upgrade_too_expensive(self):
        """An upgrade that costs more than the threshold should not alert."""
        booking = _make_booking(
            booked_price=100000,
            breakfast_included=False,
            is_cancellable=True,  # Already cancellable, so no cancellable upgrade
        )
        # snap is 100 more, exceeds upgrade_max_extra_cost of 50
        snap = _make_snapshot(
            price=100100,
            breakfast_included=True,
            is_cancellable=True,
        )
        hotel = _make_hotel()
        config = _make_config()

        alerts = compare_booking_to_snapshots(booking, hotel, [snap], config)
        upgrades = [a for a in alerts if a.alert_type == "upgrade"]
        assert len(upgrades) == 0

    def test_no_upgrade_when_already_has_features(self):
        booking = _make_booking(
            booked_price=100000,
            is_cancellable=True,
            breakfast_included=True,
            bathroom_type="private",
        )
        snap = _make_snapshot(
            price=100000,
            is_cancellable=True,
            breakfast_included=True,
            bathroom_type="private",
        )
        hotel = _make_hotel()
        config = _make_config()

        alerts = compare_booking_to_snapshots(booking, hotel, [snap], config)
        upgrades = [a for a in alerts if a.alert_type == "upgrade"]
        assert len(upgrades) == 0

    def test_upgrade_exceeds_percentage_threshold(self):
        """Upgrade within absolute cost but over percentage threshold should not alert."""
        # With a low booking price, even a small absolute cost exceeds 10%
        booking = _make_booking(
            booked_price=100,
            breakfast_included=False,
        )
        # snap is 15 more: 15 < 50 (absolute ok), but 15% > 10% (percentage exceeded)
        snap = _make_snapshot(
            price=115,
            breakfast_included=True,
        )
        hotel = _make_hotel()
        config = _make_config()

        alerts = compare_booking_to_snapshots(booking, hotel, [snap], config)
        upgrades = [a for a in alerts if a.alert_type == "upgrade"]
        assert len(upgrades) == 0


# ── Currency Mismatch ─────────────────────────────────────


class TestCurrencyMismatch:
    """Tests for handling different currencies."""

    def test_different_currency_with_conversion_rate(self):
        """When a conversion rate exists, comparison should work."""
        booking = _make_booking(booked_price=100000, currency="JPY")
        # JPY 100000 at default rate = 1960.08 ILS
        # USD 50 at default rate = 154.56 ILS
        # Diff in base = 1960.08 - 154.56 = 1805.52 ILS (92% drop)
        snap = _make_snapshot(price=50, currency="USD")
        hotel = _make_hotel()
        config = _make_config()

        alerts = compare_booking_to_snapshots(booking, hotel, [snap], config)
        price_drops = [a for a in alerts if a.alert_type == "price_drop"]
        assert len(price_drops) >= 1

    def test_different_currency_no_conversion_rate(self):
        """When no conversion rate exists, the snapshot should be skipped."""
        booking = _make_booking(booked_price=100000, currency="JPY")
        snap = _make_snapshot(price=500, currency="EUR")
        hotel = _make_hotel()
        config = _make_config()

        alerts = compare_booking_to_snapshots(booking, hotel, [snap], config)
        assert alerts == []

    def test_same_currency_no_conversion_needed(self):
        """Same currency should compare directly without conversion."""
        booking = _make_booking(booked_price=100000, currency="JPY")
        snap = _make_snapshot(price=85000, currency="JPY")
        hotel = _make_hotel()
        config = _make_config()

        alerts = compare_booking_to_snapshots(booking, hotel, [snap], config)
        price_drops = [a for a in alerts if a.alert_type == "price_drop"]
        assert len(price_drops) >= 1
        assert price_drops[0].price_diff == 15000


# ── Edge Cases ────────────────────────────────────────────


class TestEdgeCases:
    """Edge case tests for comparator."""

    def test_zero_booking_price(self):
        """Zero booking price should not cause division by zero."""
        booking = _make_booking(booked_price=0)
        snap = _make_snapshot(price=50000)
        hotel = _make_hotel()
        config = _make_config()

        # Should not raise
        alerts = compare_booking_to_snapshots(booking, hotel, [snap], config)
        # No price drop since diff is negative (snap more expensive)
        price_drops = [a for a in alerts if a.alert_type == "price_drop"]
        assert len(price_drops) == 0

    def test_zero_snapshot_price(self):
        """Zero snapshot price (free room) should detect as a price drop."""
        booking = _make_booking(booked_price=100000)
        snap = _make_snapshot(price=0)
        hotel = _make_hotel()
        config = _make_config()

        alerts = compare_booking_to_snapshots(booking, hotel, [snap], config)
        price_drops = [a for a in alerts if a.alert_type == "price_drop"]
        assert len(price_drops) >= 1
        assert price_drops[0].price_diff == 100000

    def test_multiple_snapshots(self):
        """Multiple qualifying snapshots produce one consolidated alert."""
        booking = _make_booking(booked_price=100000, is_cancellable=True)
        snaps = [
            _make_snapshot(id=10, price=85000),  # 15% drop -> qualifies
            _make_snapshot(id=11, price=99000),  # 1% drop -> no alert
            _make_snapshot(id=12, price=75000),  # 25% drop -> qualifies
        ]
        hotel = _make_hotel()
        config = _make_config()

        alerts = compare_booking_to_snapshots(booking, hotel, snaps, config)
        price_drops = [a for a in alerts if a.alert_type == "price_drop"]
        assert len(price_drops) == 1
        # 2 qualifying snapshots consolidated into one alert
        assert len(price_drops[0].details) == 2
        # Best saving first (75000 = 25% drop)
        assert price_drops[0].details[0]["snapshot_id"] == 12
        assert price_drops[0].details[1]["snapshot_id"] == 10

    def test_booking_and_snapshot_ids_propagated(self):
        """Alert should reference the correct booking and snapshot IDs."""
        booking = _make_booking(id=42, booked_price=100000)
        snap = _make_snapshot(id=99, price=80000)
        hotel = _make_hotel()
        config = _make_config()

        alerts = compare_booking_to_snapshots(booking, hotel, [snap], config)
        price_drops = [a for a in alerts if a.alert_type == "price_drop"]
        assert price_drops[0].booking_id == 42
        assert price_drops[0].snapshot_id == 99


# ── run_analysis Integration ──────────────────────────────


class TestRunAnalysis:
    """Integration tests for run_analysis with a real database."""

    def test_run_analysis_empty_db(self, tmp_db, config):
        """No bookings -> no alerts."""
        alerts = run_analysis(tmp_db, config)
        assert alerts == []

    def test_run_analysis_no_snapshots(self, tmp_db, config):
        """Bookings but no snapshots -> no alerts."""
        hotel_id = tmp_db.upsert_hotel(Hotel(name="Test Hotel", city="Tokyo"))
        tmp_db.upsert_booking(
            Booking(
                hotel_id=hotel_id,
                check_in=date(2026, 8, 31),
                check_out=date(2026, 9, 3),
                booked_price=100000,
                currency="JPY",
            )
        )
        alerts = run_analysis(tmp_db, config)
        assert alerts == []

    def test_run_analysis_with_price_drop(self, tmp_db, config):
        """Full flow: booking + cheaper snapshot -> price_drop alert persisted."""
        hotel_id = tmp_db.upsert_hotel(Hotel(name="Test Hotel", city="Tokyo"))
        tmp_db.upsert_booking(
            Booking(
                hotel_id=hotel_id,
                check_in=date(2026, 8, 31),
                check_out=date(2026, 9, 3),
                booked_price=100000,
                currency="JPY",
            )
        )
        tmp_db.add_snapshot(
            PriceSnapshot(
                hotel_id=hotel_id,
                check_in=date(2026, 8, 31),
                check_out=date(2026, 9, 3),
                platform="Booking.com",
                price=80000,
                currency="JPY",
            )
        )

        alerts = run_analysis(tmp_db, config)
        assert len(alerts) >= 1
        price_drops = [a for a in alerts if a.alert_type == "price_drop"]
        assert len(price_drops) >= 1

        # Alerts should be persisted in the database
        db_alerts = tmp_db.get_pending_alerts()
        assert len(db_alerts) >= 1

    def test_run_analysis_skips_booking_without_dates(self, tmp_db, config):
        """Bookings without check-in/out dates should be skipped."""
        hotel_id = tmp_db.upsert_hotel(Hotel(name="Test Hotel", city="Tokyo"))
        # Insert directly via SQL to bypass NOT NULL — simulates legacy/corrupt data
        tmp_db.conn.execute(
            "INSERT INTO bookings (hotel_id, check_in, check_out, booked_price, currency, status)"
            " VALUES (?, '', '', 100000, 'JPY', 'active')",
            (hotel_id,),
        )
        tmp_db.conn.commit()
        alerts = run_analysis(tmp_db, config)
        assert alerts == []

    def test_run_analysis_skips_missing_hotel(self, tmp_db, config):
        """Booking for a deleted hotel should be skipped gracefully."""
        hotel_id = tmp_db.upsert_hotel(Hotel(name="Ghost Hotel", city="Tokyo"))
        tmp_db.upsert_booking(
            Booking(
                hotel_id=hotel_id,
                check_in=date(2026, 8, 31),
                check_out=date(2026, 9, 3),
                booked_price=100000,
                currency="JPY",
            )
        )
        # Disable FK checks to simulate an orphaned booking
        tmp_db.conn.execute("PRAGMA foreign_keys=OFF")
        tmp_db.conn.execute("DELETE FROM hotels WHERE id=?", (hotel_id,))
        tmp_db.conn.commit()
        tmp_db.conn.execute("PRAGMA foreign_keys=ON")

        alerts = run_analysis(tmp_db, config)
        assert alerts == []

    def test_run_analysis_multiple_bookings(self, tmp_db, config):
        """Multiple bookings should all be analyzed."""
        h1 = tmp_db.upsert_hotel(Hotel(name="Hotel A", city="Tokyo"))
        h2 = tmp_db.upsert_hotel(Hotel(name="Hotel B", city="Osaka"))

        tmp_db.upsert_booking(
            Booking(
                hotel_id=h1,
                check_in=date(2026, 8, 31),
                check_out=date(2026, 9, 3),
                booked_price=100000,
                currency="JPY",
            )
        )
        tmp_db.upsert_booking(
            Booking(
                hotel_id=h2,
                check_in=date(2026, 9, 10),
                check_out=date(2026, 9, 13),
                booked_price=120000,
                currency="JPY",
            )
        )

        # Add a cheap snapshot for each
        tmp_db.add_snapshot(
            PriceSnapshot(
                hotel_id=h1,
                check_in=date(2026, 8, 31),
                check_out=date(2026, 9, 3),
                platform="Booking.com",
                price=70000,
                currency="JPY",
            )
        )
        tmp_db.add_snapshot(
            PriceSnapshot(
                hotel_id=h2,
                check_in=date(2026, 9, 10),
                check_out=date(2026, 9, 13),
                platform="Booking.com",
                price=90000,
                currency="JPY",
            )
        )

        alerts = run_analysis(tmp_db, config)
        assert len(alerts) >= 2

    def test_run_analysis_cancelled_bookings_excluded(self, tmp_db, config):
        """Cancelled bookings should not be analyzed."""
        hotel_id = tmp_db.upsert_hotel(Hotel(name="Test Hotel", city="Tokyo"))
        tmp_db.upsert_booking(
            Booking(
                hotel_id=hotel_id,
                check_in=date(2026, 8, 31),
                check_out=date(2026, 9, 3),
                booked_price=100000,
                currency="JPY",
                status="cancelled",
            )
        )
        tmp_db.add_snapshot(
            PriceSnapshot(
                hotel_id=hotel_id,
                check_in=date(2026, 8, 31),
                check_out=date(2026, 9, 3),
                platform="Booking.com",
                price=50000,
                currency="JPY",
            )
        )
        alerts = run_analysis(tmp_db, config)
        assert alerts == []

    def test_run_analysis_alerts_have_ids(self, tmp_db, config):
        """Persisted alerts should have database IDs assigned."""
        hotel_id = tmp_db.upsert_hotel(Hotel(name="Test Hotel", city="Tokyo"))
        tmp_db.upsert_booking(
            Booking(
                hotel_id=hotel_id,
                check_in=date(2026, 8, 31),
                check_out=date(2026, 9, 3),
                booked_price=100000,
                currency="JPY",
            )
        )
        tmp_db.add_snapshot(
            PriceSnapshot(
                hotel_id=hotel_id,
                check_in=date(2026, 8, 31),
                check_out=date(2026, 9, 3),
                platform="Booking.com",
                price=70000,
                currency="JPY",
            )
        )

        alerts = run_analysis(tmp_db, config)
        for alert in alerts:
            assert alert.id is not None
            assert alert.id > 0


# ── Consolidated Alert Details ────────────────────────────


class TestConsolidatedAlertDetails:
    """Tests for the consolidated alert detail structure."""

    def test_price_drop_details_structure(self):
        """Details list should contain structured info for each snapshot."""
        booking = _make_booking(booked_price=100000, currency="JPY")
        snap = _make_snapshot(
            id=10,
            price=80000,
            platform="Booking.com",
            room_type="Deluxe",
            is_cancellable=True,
            breakfast_included=True,
        )
        hotel = _make_hotel()
        config = _make_config()

        alerts = compare_booking_to_snapshots(booking, hotel, [snap], config)
        price_drops = [a for a in alerts if a.alert_type == "price_drop"]
        assert len(price_drops) == 1
        assert len(price_drops[0].details) == 1

        d = price_drops[0].details[0]
        assert d["snapshot_id"] == 10
        assert d["platform"] == "Booking.com"
        assert d["price"] == 80000
        assert d["currency"] == "JPY"
        assert d["room_type"] == "Deluxe"
        assert d["is_cancellable"] is True
        assert d["breakfast_included"] is True
        assert d["price_diff"] == 20000
        assert d["percentage_diff"] == 20.0

    def test_consolidated_alert_uses_best_saving(self):
        """The alert's price_diff/percentage_diff reflect the best option."""
        booking = _make_booking(booked_price=100000)
        snaps = [
            _make_snapshot(id=10, price=85000),  # 15% drop
            _make_snapshot(id=11, price=70000),  # 30% drop
        ]
        hotel = _make_hotel()
        config = _make_config()

        alerts = compare_booking_to_snapshots(booking, hotel, snaps, config)
        price_drops = [a for a in alerts if a.alert_type == "price_drop"]
        assert len(price_drops) == 1
        assert price_drops[0].price_diff == 30000
        assert price_drops[0].percentage_diff == 30.0
        assert price_drops[0].snapshot_id == 11

    def test_details_sorted_by_savings(self):
        """Details should be sorted by price_diff, biggest first."""
        booking = _make_booking(booked_price=100000)
        snaps = [
            _make_snapshot(id=10, price=90000),  # 10%
            _make_snapshot(id=11, price=70000),  # 30%
            _make_snapshot(id=12, price=80000),  # 20%
        ]
        hotel = _make_hotel()
        config = _make_config()

        alerts = compare_booking_to_snapshots(booking, hotel, snaps, config)
        price_drops = [a for a in alerts if a.alert_type == "price_drop"]
        details = price_drops[0].details
        assert len(details) == 3
        assert details[0]["snapshot_id"] == 11  # 30% first
        assert details[1]["snapshot_id"] == 12  # 20% second
        assert details[2]["snapshot_id"] == 10  # 10% third

    def test_upgrade_consolidated_with_details(self):
        """Upgrade alert should consolidate multiple upgrade snapshots."""
        booking = _make_booking(
            booked_price=100000,
            is_cancellable=False,
            breakfast_included=False,
        )
        snaps = [
            _make_snapshot(id=10, price=100000, is_cancellable=True),
            _make_snapshot(id=11, price=100020, breakfast_included=True),
        ]
        hotel = _make_hotel()
        config = _make_config()

        alerts = compare_booking_to_snapshots(booking, hotel, snaps, config)
        upgrades = [a for a in alerts if a.alert_type == "upgrade"]
        assert len(upgrades) == 1
        assert len(upgrades[0].details) == 2
        # Each detail should include the improvements
        for d in upgrades[0].details:
            assert "improvements" in d

    def test_price_drop_and_upgrade_separate_alerts(self):
        """A snapshot can trigger both a price drop and an upgrade alert."""
        booking = _make_booking(
            booked_price=100000,
            is_cancellable=False,
        )
        snap = _make_snapshot(
            price=80000,  # 20% cheaper
            is_cancellable=True,  # Also an upgrade
        )
        hotel = _make_hotel()
        config = _make_config()

        alerts = compare_booking_to_snapshots(booking, hotel, [snap], config)
        price_drops = [a for a in alerts if a.alert_type == "price_drop"]
        upgrades = [a for a in alerts if a.alert_type == "upgrade"]
        assert len(price_drops) == 1
        assert len(upgrades) == 1
