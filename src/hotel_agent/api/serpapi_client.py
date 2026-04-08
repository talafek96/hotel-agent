"""SerpAPI Google Hotels client for fetching hotel prices."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from urllib.parse import urlencode

import requests

from hotel_agent.models import Hotel, PriceSnapshot, TravelerComposition
from hotel_agent.utils import normalize_currency

logger = logging.getLogger(__name__)

SERPAPI_BASE = "https://serpapi.com/search"

# Country name → Google gl parameter (ISO 3166-1 alpha-2).
# Covers common tourism destinations; unknown countries fall back to "us".
_COUNTRY_GL: dict[str, str] = {
    "japan": "jp",
    "sri lanka": "lk",
    "india": "in",
    "austria": "at",
    "germany": "de",
    "france": "fr",
    "italy": "it",
    "spain": "es",
    "united kingdom": "gb",
    "uk": "gb",
    "united states": "us",
    "usa": "us",
    "thailand": "th",
    "australia": "au",
    "south korea": "kr",
    "korea": "kr",
    "china": "cn",
    "taiwan": "tw",
    "indonesia": "id",
    "vietnam": "vn",
    "malaysia": "my",
    "singapore": "sg",
    "philippines": "ph",
    "turkey": "tr",
    "greece": "gr",
    "portugal": "pt",
    "netherlands": "nl",
    "switzerland": "ch",
    "czech republic": "cz",
    "czechia": "cz",
    "hungary": "hu",
    "poland": "pl",
    "croatia": "hr",
    "mexico": "mx",
    "brazil": "br",
    "argentina": "ar",
    "canada": "ca",
    "new zealand": "nz",
    "egypt": "eg",
    "morocco": "ma",
    "south africa": "za",
    "israel": "il",
    "united arab emirates": "ae",
    "uae": "ae",
    "maldives": "mv",
    "nepal": "np",
    "cambodia": "kh",
    "myanmar": "mm",
    "laos": "la",
    "ireland": "ie",
    "belgium": "be",
    "denmark": "dk",
    "sweden": "se",
    "norway": "no",
    "finland": "fi",
    "iceland": "is",
    "romania": "ro",
    "bulgaria": "bg",
    "colombia": "co",
    "peru": "pe",
    "chile": "cl",
    "jordan": "jo",
    "kenya": "ke",
    "tanzania": "tz",
}


def _country_to_gl(country: str) -> str:
    """Map a hotel's country name to Google's ``gl`` parameter.

    Falls back to ``"us"`` for unrecognised names.
    """
    if not country:
        return "us"
    return _COUNTRY_GL.get(country.strip().lower(), "us")


class SerpAPIError(Exception):
    """Raised when a SerpAPI request fails."""


@dataclass
class SerpAPIResult:
    """Result of a SerpAPI hotel price search."""

    snapshots: list[PriceSnapshot] = field(default_factory=list)
    matched_name: str = ""
    matched_address: str = ""
    property_token: str = ""
    used_cached_token: bool = False


NO_RESULTS_MSG = "Google Hotels hasn't returned any results"


def search_hotel_prices(
    api_key: str,
    hotel: Hotel,
    check_in: date,
    check_out: date,
    travelers: TravelerComposition | None = None,
    currency: str = "JPY",
    gl: str | None = None,
    hl: str = "en",
) -> SerpAPIResult:
    """Query SerpAPI Google Hotels and return price snapshots + property info.

    If the hotel has a cached ``serpapi_property_token``, uses it directly.
    Otherwise searches by name and takes the first result.

    Parameters
    ----------
    gl:
        Google geo-location code.  When ``None`` (default), derived
        automatically from ``hotel.country``.

    Retry chain when 0 results are returned:
    1. Original params (children + full query)
    2. Children counted as adults + full query
    3. Simplified query (hotel name only, no city/country)
    """
    if not api_key:
        raise SerpAPIError("SERPAPI_KEY is not configured")

    if gl is None:
        gl = _country_to_gl(hotel.country)

    travelers = travelers or TravelerComposition()

    # Build query variations: full (name+city+country) and simple (name only)
    full_query = _build_query(hotel)
    simple_query = hotel.name

    result = _do_search(
        api_key, hotel, check_in, check_out, travelers, currency, gl, hl, full_query
    )
    if result.snapshots:
        return result

    # Retry 1: children counted as adults (Google Hotels often lacks child pricing)
    retry_travelers = travelers
    if travelers.children_ages:
        total = travelers.adults + travelers.children_count
        logger.info(
            "No prices with children for %s, retrying with %d adults",
            hotel.name,
            total,
        )
        retry_travelers = TravelerComposition(adults=total)
        result = _do_search(
            api_key, hotel, check_in, check_out, retry_travelers, currency, gl, hl, full_query
        )
        if result.snapshots:
            for snap in result.snapshots:
                snap.travelers = travelers
            return result

    # Retry 2: simplified query (hotel name only, no city/country)
    if simple_query != full_query:
        logger.info("Retrying %s with simplified query: %r", hotel.name, simple_query)
        result = _do_search(
            api_key, hotel, check_in, check_out, retry_travelers, currency, gl, hl, simple_query
        )
        if result.snapshots:
            for snap in result.snapshots:
                snap.travelers = travelers

    return result


def _build_query(hotel: Hotel) -> str:
    """Build the SerpAPI search query from hotel name + city + country."""
    parts = [hotel.name]
    if hotel.city:
        parts.append(hotel.city)
    if hotel.country:
        parts.append(hotel.country)
    return " ".join(parts)


def _do_search(
    api_key: str,
    hotel: Hotel,
    check_in: date,
    check_out: date,
    travelers: TravelerComposition,
    currency: str,
    gl: str,
    hl: str,
    query: str,
) -> SerpAPIResult:
    """Execute a single SerpAPI Google Hotels search."""
    # Normalise currency to a valid ISO 4217 code (handles symbols, names, None)
    currency = normalize_currency(currency)

    params: dict[str, str | int] = {
        "engine": "google_hotels",
        "check_in_date": check_in.isoformat(),
        "check_out_date": check_out.isoformat(),
        "adults": travelers.adults,
        "currency": currency,
        "gl": gl,
        "hl": hl,
        "api_key": api_key,
        "q": query,
    }

    if travelers.children_ages:
        params["children"] = travelers.children_count
        params["children_ages"] = ",".join(str(a) for a in travelers.children_ages)

    # Use cached property_token if available for direct property detail
    if hotel.serpapi_property_token:
        params["property_token"] = hotel.serpapi_property_token
        logger.info("Using cached property_token for %s", hotel.name)

    url = f"{SERPAPI_BASE}?{urlencode(params)}"
    logger.info("SerpAPI request: %s", url.replace(api_key, "***"))

    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise SerpAPIError(f"SerpAPI request failed: {exc}") from exc

    data = resp.json()

    if "error" in data:
        # "No results" is retryable — return empty result instead of raising
        if NO_RESULTS_MSG in data["error"]:
            logger.info("No results for %s with query %r", hotel.name, query)
            return SerpAPIResult()
        raise SerpAPIError(f"SerpAPI error: {data['error']}")

    if hotel.serpapi_property_token:
        return _parse_property_detail(data, hotel, check_in, check_out, travelers, currency)
    return _parse_first_property(data, hotel, check_in, check_out, travelers, currency)


def _parse_property_detail(
    data: dict,
    hotel: Hotel,
    check_in: date,
    check_out: date,
    travelers: TravelerComposition,
    currency: str,
) -> SerpAPIResult:
    """Parse response when using a property_token (detail view).

    In this mode SerpAPI returns top-level ``prices`` for the specific hotel.
    """
    now = datetime.now()
    result = SerpAPIResult(
        used_cached_token=True,
        property_token=hotel.serpapi_property_token,
    )

    for price_info in data.get("prices", []):
        snap = _price_info_to_snapshot(
            price_info, hotel, check_in, check_out, travelers, currency, now
        )
        if snap:
            result.snapshots.append(snap)

    logger.info("Parsed %d snapshots for %s (cached token)", len(result.snapshots), hotel.name)
    return result


def _parse_first_property(
    data: dict,
    hotel: Hotel,
    check_in: date,
    check_out: date,
    travelers: TravelerComposition,
    currency: str,
) -> SerpAPIResult:
    """Parse SerpAPI response by taking the first property result.

    Extracts the property_token so the caller can cache it after verification.
    """
    now = datetime.now()
    result = SerpAPIResult()

    properties = data.get("properties", [])
    if not properties:
        # SerpAPI sometimes returns a direct property detail page instead of
        # a search results list (hotels_results_state == "Showing results for
        # property details").  In that case the property_token and name are
        # top-level keys and prices (if any) are also top-level.
        result.matched_name = data.get("name", "")
        result.matched_address = data.get("address", "")
        result.property_token = data.get("property_token", "")

        for price_info in data.get("prices", []):
            snap = _price_info_to_snapshot(
                price_info, hotel, check_in, check_out, travelers, currency, now
            )
            if snap:
                result.snapshots.append(snap)
        logger.info(
            "Direct property detail for %s, parsed %d prices (token: %s)",
            hotel.name,
            len(result.snapshots),
            "yes" if result.property_token else "no",
        )
        return result

    # Take the first property — Google's ranking is our best bet
    prop = properties[0]
    result.matched_name = prop.get("name", "")
    result.matched_address = prop.get("hotel_address", "") or prop.get("address", "")
    result.property_token = prop.get("property_token", "")

    # Extract prices from this property
    for price_info in prop.get("prices", []):
        snap = _price_info_to_snapshot(
            price_info, hotel, check_in, check_out, travelers, currency, now
        )
        if snap:
            result.snapshots.append(snap)

    # NOTE: We intentionally do NOT fall back to the property-level
    # rate_per_night summary.  That value is a per-night display estimate
    # from Google (not a real OTA price), has no booking link, and was
    # stored as a total-stay price — producing phantom 70%+ "savings" alerts.

    logger.info(
        "Parsed %d snapshots for %s (matched: '%s', token: %s)",
        len(result.snapshots),
        hotel.name,
        result.matched_name,
        "yes" if result.property_token else "no",
    )
    return result


def _price_info_to_snapshot(
    price_info: dict,
    hotel: Hotel,
    check_in: date,
    check_out: date,
    travelers: TravelerComposition,
    currency: str,
    now: datetime,
) -> PriceSnapshot | None:
    """Convert a single SerpAPI price entry to a PriceSnapshot."""
    source = price_info.get("source", "unknown")
    link = price_info.get("link", "")
    rate = price_info.get("rate_per_night", {})
    # SerpAPI uses "total_rate" for property detail and "total" for property list
    total = price_info.get("total_rate") or price_info.get("total", {})

    # Prefer total stay price, fall back to nightly rate
    price_val = (
        total.get("extracted_lowest")
        or total.get("extracted_price")
        or rate.get("extracted_lowest")
        or rate.get("extracted_price")
    )
    if price_val is None:
        raw = total.get("lowest") or total.get("price") or rate.get("lowest") or rate.get("price")
        if raw:
            price_val = _extract_number(raw)

    if price_val is None:
        return None

    nights = (check_out - check_in).days or 1

    # If we only got a nightly rate, multiply to get total
    has_total = bool(total.get("extracted_lowest") or total.get("extracted_price"))
    final_price = float(price_val) if has_total else float(price_val) * nights

    room_type = price_info.get("room_type", "")
    is_cancellable = None
    breakfast = None

    # Check boolean flags (property detail view)
    if price_info.get("free_cancellation") is True:
        is_cancellable = True
    if price_info.get("free_breakfast") is True:
        breakfast = True

    # Parse amenities/features if available
    amenities: list[str] = []
    for feat in price_info.get("amenities", []):
        amenities.append(feat)
    for feat in price_info.get("features", []):
        if isinstance(feat, str):
            feat_lower = feat.lower()
            if "free cancellation" in feat_lower:
                is_cancellable = True
            if "breakfast" in feat_lower:
                breakfast = True
            amenities.append(feat)

    # Cancellation deadline
    cancel_deadline = None
    cancel_until = price_info.get("free_cancellation_until_date")
    if cancel_until and is_cancellable:
        try:
            from datetime import datetime as dt

            parsed = dt.strptime(f"{cancel_until} {check_in.year}", "%b %d %Y")
            cancel_deadline = parsed.date()
        except ValueError:
            pass

    return PriceSnapshot(
        hotel_id=hotel.id or 0,
        check_in=check_in,
        check_out=check_out,
        travelers=travelers,
        room_type=room_type,
        platform=source.lower().replace(" ", "_"),
        source_display=source,
        price=final_price,
        currency=currency,
        is_cancellable=is_cancellable,
        breakfast_included=breakfast,
        cancellation_deadline=cancel_deadline,
        amenities=amenities,
        link=link,
        scraped_at=now,
    )


def _extract_number(raw: str) -> float | None:
    """Extract a numeric value from a price string like '¥12,345'."""
    cleaned = ""
    for ch in raw:
        if ch.isdigit() or ch == ".":
            cleaned += ch
    if cleaned:
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None
