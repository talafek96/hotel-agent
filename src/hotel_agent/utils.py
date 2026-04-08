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


# ── Currency normalisation ──────────────────────────────────


# Maps symbols, common names, and non-standard codes to ISO 4217.
_CURRENCY_ALIASES: dict[str, str] = {
    # Symbols
    "¥": "JPY",
    "￥": "JPY",
    "$": "USD",
    "€": "EUR",
    "₪": "ILS",
    "£": "GBP",
    "₹": "INR",
    "₩": "KRW",
    "฿": "THB",
    "₫": "VND",
    "₱": "PHP",
    "₺": "TRY",
    "₴": "UAH",
    "₽": "RUB",
    "r$": "BRL",
    "rm": "MYR",
    "kr": "SEK",  # also NOK/DKK, but SEK is most common
    "kč": "CZK",
    "zł": "PLN",
    "ft": "HUF",
    "lei": "RON",
    "лв": "BGN",
    # Names / words
    "yen": "JPY",
    "dollar": "USD",
    "dollars": "USD",
    "euro": "EUR",
    "euros": "EUR",
    "shekel": "ILS",
    "shekels": "ILS",
    "pound": "GBP",
    "pounds": "GBP",
    "rupee": "INR",
    "rupees": "INR",
    "won": "KRW",
    "baht": "THB",
    "dong": "VND",
    "peso": "MXN",
    "pesos": "MXN",
    "real": "BRL",
    "reais": "BRL",
    "ringgit": "MYR",
    "krona": "SEK",
    "kronor": "SEK",
    "krone": "NOK",
    "kroner": "NOK",
    "franc": "CHF",
    "francs": "CHF",
    "lira": "TRY",
    # Non-standard abbreviations
    "nis": "ILS",
    "rmb": "CNY",
    "yuan": "CNY",
    "us$": "USD",
    "usd$": "USD",
    "a$": "AUD",
    "au$": "AUD",
    "c$": "CAD",
    "ca$": "CAD",
    "nz$": "NZD",
    "s$": "SGD",
    "hk$": "HKD",
    "nt$": "TWD",
}


def normalize_currency(raw: str | None) -> str:
    """Normalise a currency value to an ISO 4217 code.

    Handles symbols (¥, ₪, €), full names (``"euro"``), and non-standard
    abbreviations (``"NIS"``).  Returns ``"USD"`` when the input is empty,
    ``None``, or unrecognised.

    Already-valid 3-letter codes (``"JPY"``, ``"EUR"``) pass through unchanged.
    """
    if not raw:
        return "USD"

    cleaned = raw.strip()
    if not cleaned:
        return "USD"

    # Look up alias first (case-insensitive) — catches words like "yen", "won"
    alias = _CURRENCY_ALIASES.get(cleaned.lower())
    if alias:
        return alias

    # Already a valid-looking 3-letter ISO code?
    upper = cleaned.upper()
    if len(upper) == 3 and upper.isalpha():
        return upper

    # Single-char symbol lookup
    if len(cleaned) <= 2:
        alias = _CURRENCY_ALIASES.get(cleaned)
        if alias:
            return alias

    # Fallback
    return "USD"


# Canonical platform metadata for the config UI checklist.
# key = normalised slug (matches price_snapshots.platform), value = group name.
# Display names come from SerpAPI (source_display) — this dict only assigns groups.
KNOWN_PLATFORM_GROUPS: dict[str, str] = {
    # ── Major OTAs ──
    "booking.com": "Major OTAs",
    "agoda": "Major OTAs",
    "expedia": "Major OTAs",
    "hotels.com": "Major OTAs",
    "trip.com": "Major OTAs",
    "priceline": "Major OTAs",
    # ── Aggregators & Metasearch ──
    "trivago": "Aggregators",
    "trivago_deals": "Aggregators",
    "kayak": "Aggregators",
    "orbitz": "Aggregators",
    "travelocity": "Aggregators",
    "hostelworld": "Aggregators",
    "vrbo": "Aggregators",
    "tripadvisor": "Aggregators",
    "skyscanner": "Aggregators",
    "momondo": "Aggregators",
    "cheaptickets": "Aggregators",
    "hotwire": "Aggregators",
    "wego": "Aggregators",
    "snaptravel": "Aggregators",
    "hopper": "Aggregators",
    # ── Hotel Chains ──
    "marriott.com": "Hotel Chains",
    "hilton.com": "Hotel Chains",
    "ihg.com": "Hotel Chains",
    "hyatt.com": "Hotel Chains",
    "accor.com": "Hotel Chains",
    "wyndham.com": "Hotel Chains",
    "bestwestern.com": "Hotel Chains",
    "radissonhotels.com": "Hotel Chains",
    "choicehotels.com": "Hotel Chains",
    "nh-hotels.com": "Hotel Chains",
    # ── Japan ──
    "rakuten_travel": "Japan",
    "jalan": "Japan",
    "japanican": "Japan",
    "ikyu.com": "Japan",
    "rurubu_travel": "Japan",
    # ── India ──
    "makemytrip": "India",
    "goibibo": "India",
    "yatra": "India",
    "cleartrip": "India",
    "easemytrip": "India",
    "oyo": "India",
    # ── China ──
    "ctrip": "China",
    "qunar": "China",
    "fliggy": "China",
    "elong": "China",
    "meituan": "China",
    "tongcheng": "China",
    # ── Southeast Asia ──
    "traveloka": "Southeast Asia",
    "pegipegi": "Southeast Asia",
    "tiket.com": "Southeast Asia",
    "reddoorz": "Southeast Asia",
    "zenrooms": "Southeast Asia",
    # ── South Korea ──
    "yanolja": "South Korea",
    "goodchoice": "South Korea",
    # ── Middle East ──
    "almosafer": "Middle East",
    "rehlat": "Middle East",
    "tajawal": "Middle East",
    # ── Europe ──
    "lastminute.com": "Europe",
    "edreams": "Europe",
    "opodo": "Europe",
    "hrs": "Europe",
    "secret_escapes": "Europe",
    "laterooms": "Europe",
    # ── Latin America ──
    "despegar": "Latin America",
    "decolar": "Latin America",
    "bestday": "Latin America",
    # ── Niche / Other ──
    "travelup": "Niche",
    "prestigia": "Niche",
    "destinia": "Niche",
    "zenhotels": "Niche",
    "getaroom": "Niche",
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
    seen_platforms: list[tuple[str, str]],
) -> list[dict[str, str]]:
    """Build the platform checklist from DB-discovered platforms.

    *seen_platforms* is a list of ``(slug, display_name)`` tuples returned
    by ``db.get_seen_platforms()``.  The ``KNOWN_PLATFORM_GROUPS`` dict
    assigns a group; unknown slugs go to "Other".
    """
    result: list[dict[str, str]] = []
    for slug, display in seen_platforms:
        group = KNOWN_PLATFORM_GROUPS.get(slug, "Other")
        result.append({"slug": slug, "display": display, "group": group})
    return result
