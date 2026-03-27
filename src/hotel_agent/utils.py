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


# Canonical platform metadata for the config UI checklist.
# key = normalised slug (matches price_snapshots.platform), value = (display, group).
KNOWN_PLATFORMS: dict[str, tuple[str, str]] = {
    # ── Major OTAs ──
    "booking.com": ("Booking.com", "Major OTAs"),
    "agoda": ("Agoda", "Major OTAs"),
    "expedia": ("Expedia", "Major OTAs"),
    "hotels.com": ("Hotels.com", "Major OTAs"),
    "trip.com": ("Trip.com", "Major OTAs"),
    "priceline": ("Priceline", "Major OTAs"),
    # ── Aggregators & Metasearch ──
    "trivago": ("Trivago", "Aggregators"),
    "trivago_deals": ("Trivago DEALS", "Aggregators"),
    "kayak": ("Kayak", "Aggregators"),
    "orbitz": ("Orbitz", "Aggregators"),
    "travelocity": ("Travelocity", "Aggregators"),
    "hostelworld": ("Hostelworld", "Aggregators"),
    "vrbo": ("VRBO", "Aggregators"),
    "tripadvisor": ("TripAdvisor", "Aggregators"),
    "skyscanner": ("Skyscanner", "Aggregators"),
    "momondo": ("Momondo", "Aggregators"),
    "cheaptickets": ("CheapTickets", "Aggregators"),
    "hotwire": ("Hotwire", "Aggregators"),
    "wego": ("Wego", "Aggregators"),
    "snaptravel": ("SnapTravel", "Aggregators"),
    "hopper": ("Hopper", "Aggregators"),
    # ── Hotel Chains ──
    "marriott.com": ("Marriott", "Hotel Chains"),
    "hilton.com": ("Hilton", "Hotel Chains"),
    "ihg.com": ("IHG", "Hotel Chains"),
    "hyatt.com": ("Hyatt", "Hotel Chains"),
    "accor.com": ("Accor", "Hotel Chains"),
    "wyndham.com": ("Wyndham", "Hotel Chains"),
    "bestwestern.com": ("Best Western", "Hotel Chains"),
    "radissonhotels.com": ("Radisson", "Hotel Chains"),
    "choicehotels.com": ("Choice Hotels", "Hotel Chains"),
    "nh-hotels.com": ("NH Hotels", "Hotel Chains"),
    # ── Japan ──
    "rakuten_travel": ("Rakuten Travel", "Japan"),
    "jalan": ("Jalan", "Japan"),
    "japanican": ("Japanican", "Japan"),
    "ikyu.com": ("Ikyu", "Japan"),
    "rurubu_travel": ("Rurubu Travel", "Japan"),
    # ── India ──
    "makemytrip": ("MakeMyTrip", "India"),
    "goibibo": ("Goibibo", "India"),
    "yatra": ("Yatra", "India"),
    "cleartrip": ("Cleartrip", "India"),
    "easemytrip": ("EaseMyTrip", "India"),
    "oyo": ("OYO", "India"),
    # ── China ──
    "ctrip": ("Ctrip", "China"),
    "qunar": ("Qunar", "China"),
    "fliggy": ("Fliggy", "China"),
    "elong": ("eLong", "China"),
    "meituan": ("Meituan", "China"),
    "tongcheng": ("Tongcheng", "China"),
    # ── Southeast Asia ──
    "traveloka": ("Traveloka", "Southeast Asia"),
    "pegipegi": ("PegiPegi", "Southeast Asia"),
    "tiket.com": ("Tiket.com", "Southeast Asia"),
    "reddoorz": ("RedDoorz", "Southeast Asia"),
    "zenrooms": ("ZenRooms", "Southeast Asia"),
    # ── South Korea ──
    "yanolja": ("Yanolja", "South Korea"),
    "goodchoice": ("Goodchoice", "South Korea"),
    # ── Middle East ──
    "almosafer": ("Almosafer", "Middle East"),
    "rehlat": ("Rehlat", "Middle East"),
    "tajawal": ("Tajawal", "Middle East"),
    # ── Europe ──
    "lastminute.com": ("Lastminute.com", "Europe"),
    "edreams": ("eDreams", "Europe"),
    "opodo": ("Opodo", "Europe"),
    "hrs": ("HRS", "Europe"),
    "secret_escapes": ("Secret Escapes", "Europe"),
    "laterooms": ("Laterooms", "Europe"),
    # ── Latin America ──
    "despegar": ("Despegar", "Latin America"),
    "decolar": ("Decolar", "Latin America"),
    "bestday": ("BestDay", "Latin America"),
    # ── Niche / Other ──
    "travelup": ("TravelUp", "Niche"),
    "prestigia": ("Prestigia", "Niche"),
    "destinia": ("Destinia", "Niche"),
    "zenhotels": ("ZenHotels", "Niche"),
    "getaroom": ("Getaroom", "Niche"),
}

# Ordered group list — global groups first, then regional (collapsed by default in UI).
PLATFORM_GROUPS: list[str] = [
    "Major OTAs",
    "Aggregators",
    "Hotel Chains",
    "Japan",
    "India",
    "China",
    "Southeast Asia",
    "South Korea",
    "Middle East",
    "Europe",
    "Latin America",
    "Niche",
    "Other",
]

# Groups that should be expanded by default in the UI.
PLATFORM_GROUPS_EXPANDED: set[str] = {"Major OTAs", "Aggregators", "Hotel Chains"}


def build_platform_list(
    seen_platforms: list[str],
) -> list[dict[str, str]]:
    """Return a combined list of known + seen platforms with display name and group.

    Each entry: {"slug": "booking.com", "display": "Booking.com", "group": "Major OTAs"}
    Platforms in *seen_platforms* that aren't in KNOWN_PLATFORMS are added under "Other".
    """
    result: dict[str, dict[str, str]] = {}
    for slug, (display, group) in KNOWN_PLATFORMS.items():
        result[slug] = {"slug": slug, "display": display, "group": group}
    for slug in seen_platforms:
        if slug not in result:
            display = slug.replace("_", " ").title()
            result[slug] = {"slug": slug, "display": display, "group": "Other"}
    return list(result.values())
