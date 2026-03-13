"""Price comparison logic for hotel bookings."""

from __future__ import annotations

import logging

from ..config import AppConfig
from ..db import Database
from ..models import Alert, Booking, Hotel, PriceSnapshot

log = logging.getLogger(__name__)


def _snap_detail(snap: PriceSnapshot, price_diff: float, pct_diff: float) -> dict:
    """Build a structured detail dict for one snapshot."""
    return {
        "snapshot_id": snap.id,
        "platform": snap.platform,
        "price": snap.price,
        "currency": snap.currency,
        "room_type": snap.room_type or "",
        "is_cancellable": snap.is_cancellable,
        "cancellation_deadline": str(snap.cancellation_deadline)
        if snap.cancellation_deadline
        else "",
        "breakfast_included": snap.breakfast_included,
        "bathroom_type": snap.bathroom_type or "",
        "amenities": snap.amenities or [],
        "link": snap.link or "",
        "price_diff": price_diff,
        "percentage_diff": round(pct_diff, 1),
    }


def compare_booking_to_snapshots(
    booking: Booking,
    hotel: Hotel,
    snapshots: list[PriceSnapshot],
    config: AppConfig,
) -> list[Alert]:
    """Compare a booking against recent price snapshots and generate alerts.

    Produces at most one price_drop alert and one upgrade alert per booking,
    each consolidating all qualifying snapshots.
    """
    if not snapshots:
        return []

    thresholds = config.alerts
    price_drop_details: list[dict] = []
    upgrade_details: list[dict] = []

    for snap in snapshots:
        # Skip non-cancellable snapshots when only_cancellable is set
        if thresholds.only_cancellable and not snap.is_cancellable:
            continue

        # Skip if different currency (would need conversion)
        if snap.currency != booking.currency:
            try:
                snap_price_base = config.currency.convert(snap.price, snap.currency)
                booking_price_base = config.currency.convert(booking.booked_price, booking.currency)
            except ValueError:
                log.warning(f"Cannot compare currencies: {snap.currency} vs {booking.currency}")
                continue
        else:
            snap_price_base = snap.price
            booking_price_base = booking.booked_price

        price_diff = booking_price_base - snap_price_base
        pct_diff = (price_diff / booking_price_base * 100) if booking_price_base > 0 else 0

        # 1. Price drop
        if (
            price_diff >= thresholds.price_drop_min_absolute
            and pct_diff >= thresholds.price_drop_min_percentage
        ):
            price_drop_details.append(_snap_detail(snap, price_diff, pct_diff))

        # 2. Upgrade available (better room at similar price)
        extra_cost = snap_price_base - booking_price_base
        extra_pct = (extra_cost / booking_price_base * 100) if booking_price_base > 0 else 0
        if (
            extra_cost <= thresholds.upgrade_max_extra_cost
            and extra_pct <= thresholds.upgrade_max_extra_percentage
            and _is_upgrade(booking, snap)
        ):
            detail = _snap_detail(snap, -extra_cost, -extra_pct)
            detail["improvements"] = _describe_upgrade(booking, snap)
            upgrade_details.append(detail)

    alerts: list[Alert] = []

    # Consolidated price drop alert
    if price_drop_details:
        # Sort by biggest savings first
        price_drop_details.sort(key=lambda d: d["price_diff"], reverse=True)
        best = price_drop_details[0]
        severity = _price_drop_severity(best["percentage_diff"])

        lines = [
            f"{hotel.name} ({hotel.city})",
            f"Your price: {booking.booked_price:,.0f} {booking.currency} ({booking.platform})",
            f"Dates: {booking.check_in} to {booking.check_out}",
        ]
        if booking.booking_reference:
            lines.append(f"Booking ref: {booking.booking_reference}")
        if booking.room_type:
            lines.append(f"Room: {booking.room_type}")
        lines.append("")
        lines.append(
            f"{len(price_drop_details)} cheaper option{'s' if len(price_drop_details) != 1 else ''}:"
        )
        for d in price_drop_details:
            cancel = "Free cancel" if d["is_cancellable"] else ""
            bfast = "Breakfast" if d["breakfast_included"] else ""
            extras = ", ".join(filter(None, [cancel, bfast]))
            extras_str = f" | {extras}" if extras else ""
            room = d["room_type"] or "Standard"
            line = (
                f"  - {d['platform']}: {d['price']:,.0f} {d['currency']}"
                f" (-{d['percentage_diff']:.1f}%) | {room}{extras_str}"
            )
            if d.get("link"):
                line += f"\n    {d['link']}"
            lines.append(line)

        alerts.append(
            Alert(
                booking_id=booking.id,
                snapshot_id=best["snapshot_id"],
                alert_type="price_drop",
                severity=severity,
                title=f"Price drop: {hotel.name}",
                message="\n".join(lines),
                price_diff=best["price_diff"],
                percentage_diff=best["percentage_diff"],
                details=price_drop_details,
            )
        )

    # Consolidated upgrade alert
    if upgrade_details:
        upgrade_details.sort(key=lambda d: d["price_diff"], reverse=True)
        best_up = upgrade_details[0]

        lines = [
            f"{hotel.name} ({hotel.city})",
            f"Current room: {booking.room_type or 'Standard'}",
            f"Your price: {booking.booked_price:,.0f} {booking.currency} ({booking.platform})",
        ]
        if booking.booking_reference:
            lines.append(f"Booking ref: {booking.booking_reference}")
        lines.append("")
        lines.append(
            f"{len(upgrade_details)} upgrade option{'s' if len(upgrade_details) != 1 else ''}:"
        )
        for d in upgrade_details:
            room = d["room_type"] or "Better room"
            extra = -d["price_diff"]
            cost_str = f"+{extra:,.0f}" if extra > 0 else f"{extra:,.0f}"
            line = (
                f"  - {d['platform']}: {room} ({cost_str} {d['currency']})"
                f" | {d.get('improvements', '')}"
            )
            if d.get("link"):
                line += f"\n    {d['link']}"
            lines.append(line)

        alerts.append(
            Alert(
                booking_id=booking.id,
                snapshot_id=best_up["snapshot_id"],
                alert_type="upgrade",
                severity="important",
                title=f"Upgrade available: {hotel.name}",
                message="\n".join(lines),
                price_diff=best_up["price_diff"],
                percentage_diff=best_up["percentage_diff"],
                details=upgrade_details,
            )
        )

    return alerts


def _price_drop_severity(pct_diff: float) -> str:
    if pct_diff >= 20:
        return "urgent"
    elif pct_diff >= 10:
        return "important"
    return "info"


def _is_upgrade(booking: Booking, snap: PriceSnapshot) -> bool:
    """Check if the snapshot represents an upgrade over the booking."""
    upgrades = 0

    # Cancellable is better than non-cancellable
    if not booking.is_cancellable and snap.is_cancellable:
        upgrades += 1

    # Breakfast included is better than not
    if not booking.breakfast_included and snap.breakfast_included:
        upgrades += 1

    # Private bathroom beats shared
    if booking.bathroom_type == "shared" and snap.bathroom_type == "private":
        upgrades += 1

    return upgrades > 0


def _describe_upgrade(booking: Booking, snap: PriceSnapshot) -> str:
    """Describe what makes the snapshot an upgrade."""
    improvements = []
    if not booking.is_cancellable and snap.is_cancellable:
        improvements.append("free cancellation")
    if not booking.breakfast_included and snap.breakfast_included:
        improvements.append("breakfast included")
    if booking.bathroom_type == "shared" and snap.bathroom_type == "private":
        improvements.append("private bathroom")
    return ", ".join(improvements) if improvements else "better room type"


def run_analysis(db: Database, config: AppConfig) -> list[Alert]:
    """Run price comparison analysis for all active bookings.

    Compares each booking against the latest scraped prices and generates alerts.
    """
    bookings = db.get_active_bookings()
    all_alerts = []

    for booking in bookings:
        hotel = db.get_hotel(booking.hotel_id)
        if not hotel or hotel.id is None:
            continue

        if not booking.check_in or not booking.check_out:
            continue

        snapshots = db.get_latest_snapshots(hotel.id, booking.check_in, booking.check_out)

        if not snapshots:
            log.debug(f"No snapshots for {hotel.name} ({booking.check_in} to {booking.check_out})")
            continue

        alerts = compare_booking_to_snapshots(booking, hotel, snapshots, config)

        for alert in alerts:
            alert_id = db.add_alert(alert)
            alert.id = alert_id
            all_alerts.append(alert)
            log.info(f"Alert: [{alert.severity}] {alert.title}")

    return all_alerts
