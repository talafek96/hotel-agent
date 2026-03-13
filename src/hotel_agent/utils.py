"""Shared utility functions."""

from __future__ import annotations

from datetime import date, datetime


def parse_date(val: str | None) -> date | None:
    """Parse a date string (YYYY-MM-DD or longer), returning None on failure."""
    if not val:
        return None
    try:
        return date.fromisoformat(val[:10])
    except (ValueError, TypeError):
        return None


def parse_datetime(val: str | None) -> datetime | None:
    """Parse an ISO datetime string, returning None on failure."""
    if not val:
        return None
    try:
        return datetime.fromisoformat(val)
    except (ValueError, TypeError):
        return None


def date_to_str(d: date | None) -> str | None:
    """Convert a date to ISO string, or None."""
    return d.isoformat() if d else None


def strip_code_fences(text: str) -> str:
    """Remove markdown code fences (```json ... ```) from LLM output."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:]  # Remove opening ```json
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
    return text


# Platform name → booking-site homepage. Used for clickable source links.
PLATFORM_URLS: dict[str, str] = {
    "booking.com": "https://www.booking.com",
    "hotels.com": "https://www.hotels.com",
    "expedia": "https://www.expedia.com",
    "expedia.com": "https://www.expedia.com",
    "agoda": "https://www.agoda.com",
    "agoda.com": "https://www.agoda.com",
    "trip.com": "https://www.trip.com",
    "priceline": "https://www.priceline.com",
    "priceline.com": "https://www.priceline.com",
    "trivago": "https://www.trivago.com",
    "trivago.com": "https://www.trivago.com",
    "kayak": "https://www.kayak.com",
    "kayak.com": "https://www.kayak.com",
    "orbitz": "https://www.orbitz.com",
    "orbitz.com": "https://www.orbitz.com",
    "travelocity": "https://www.travelocity.com",
    "travelocity.com": "https://www.travelocity.com",
    "rakuten_travel": "https://travel.rakuten.co.jp",
    "jalan": "https://www.jalan.net",
    "jalan.net": "https://www.jalan.net",
    "japanican": "https://www.japanican.com",
    "japanican.com": "https://www.japanican.com",
    "hostelworld": "https://www.hostelworld.com",
    "hostelworld.com": "https://www.hostelworld.com",
    "vrbo": "https://www.vrbo.com",
    "vrbo.com": "https://www.vrbo.com",
    "marriott.com": "https://www.marriott.com",
    "hilton.com": "https://www.hilton.com",
    "ihg.com": "https://www.ihg.com",
}


def platform_url(platform: str) -> str:
    """Return the homepage URL for a booking platform, or empty string if unknown."""
    return PLATFORM_URLS.get(platform.lower().strip(), "")
