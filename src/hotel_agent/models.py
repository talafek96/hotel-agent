"""Data models for the hotel price tracking system."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime


@dataclass
class TravelerComposition:
    """Room/family composition for hotel searches."""

    adults: int = 2
    children_ages: list[int] = field(default_factory=list)

    @property
    def children_count(self) -> int:
        return len(self.children_ages)

    @property
    def total_guests(self) -> int:
        return self.adults + self.children_count

    def to_dict(self) -> dict:
        return {"adults": self.adults, "children_ages": self.children_ages}

    @classmethod
    def from_dict(cls, data: dict) -> TravelerComposition:
        return cls(
            adults=data.get("adults", 2),
            children_ages=data.get("children_ages") or data.get("children", []),
        )

    def __str__(self) -> str:
        parts = [f"{self.adults} adult{'s' if self.adults != 1 else ''}"]
        if self.children_ages:
            ages = ", ".join(str(a) for a in self.children_ages)
            parts.append(
                f"{self.children_count} child{'ren' if self.children_count != 1 else ''} (ages {ages})"
            )
        return " + ".join(parts)


@dataclass
class Hotel:
    """A hotel being tracked."""

    id: int | None = None
    name: str = ""
    city: str = ""
    country: str = ""
    address: str = ""
    stars: int | None = None
    url: str = ""
    platform: str = ""
    notes: str = ""
    serpapi_property_token: str = ""
    added_at: datetime | None = None


@dataclass
class Booking:
    """An existing hotel booking (track for rebooking opportunities)."""

    id: int | None = None
    hotel_id: int = 0
    check_in: date | None = None
    check_out: date | None = None
    travelers: TravelerComposition = field(default_factory=TravelerComposition)
    room_type: str = ""
    booked_price: float = 0.0
    currency: str = "JPY"
    is_cancellable: bool = False
    cancellation_deadline: date | None = None
    breakfast_included: bool = False
    dinner_included: bool = False
    bathroom_type: str = "private"
    platform: str = ""
    booking_reference: str = ""
    booking_url: str = ""
    extras: str = ""
    status: str = "active"  # active | cancelled | completed
    created_at: datetime | None = None
    notes: str = ""

    @property
    def nights(self) -> int:
        if self.check_in and self.check_out:
            return (self.check_out - self.check_in).days
        return 0

    @property
    def price_per_night(self) -> float:
        if self.nights > 0:
            return self.booked_price / self.nights
        return self.booked_price


@dataclass
class WatchlistEntry:
    """A hotel being watched (not yet booked)."""

    id: int | None = None
    hotel_id: int = 0
    check_in: date | None = None
    check_out: date | None = None
    travelers: TravelerComposition = field(default_factory=TravelerComposition)
    max_price: float | None = None
    currency: str = "JPY"
    priority: str = "normal"
    created_at: datetime | None = None
    notes: str = ""


@dataclass
class PriceSnapshot:
    """A single price observation from scraping."""

    id: int | None = None
    hotel_id: int = 0
    check_in: date | None = None
    check_out: date | None = None
    travelers: TravelerComposition = field(default_factory=TravelerComposition)
    room_type: str = ""
    platform: str = ""
    source_display: str = ""  # original OTA name from SerpAPI (e.g. "Booking.com")
    price: float = 0.0
    currency: str = "JPY"
    is_cancellable: bool | None = None
    cancellation_deadline: date | None = None
    breakfast_included: bool | None = None
    bathroom_type: str = ""
    amenities: list[str] = field(default_factory=list)
    link: str = ""
    raw_llm_response: str = ""
    screenshot_path: str = ""
    scraped_at: datetime | None = None


@dataclass
class Alert:
    """A generated alert about a price opportunity."""

    id: int | None = None
    booking_id: int | None = None
    watchlist_id: int | None = None
    snapshot_id: int | None = None
    alert_type: str = ""  # price_drop | better_deal | upgrade
    severity: str = "info"  # info | important | urgent
    title: str = ""
    message: str = ""
    price_diff: float = 0.0
    percentage_diff: float = 0.0
    details: list[dict] = field(default_factory=list)
    notified_telegram: bool = False
    notified_email: bool = False
    notified_digest: bool = False
    created_at: datetime | None = None


@dataclass
class ScrapeRun:
    """Metadata about a scraping run."""

    id: int | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    total_hotels: int = 0
    successful: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)
    status: str = "running"  # running | completed | failed
