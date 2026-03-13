"""SQLite database layer for hotel price tracking."""

from __future__ import annotations

import json
import sqlite3
from datetime import date
from pathlib import Path

from .models import (
    Alert,
    Booking,
    Hotel,
    PriceSnapshot,
    TravelerComposition,
    WatchlistEntry,
)
from .utils import date_to_str, parse_date, parse_datetime

SCHEMA = """
CREATE TABLE IF NOT EXISTS hotels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    city TEXT DEFAULT '',
    country TEXT DEFAULT '',
    address TEXT DEFAULT '',
    stars INTEGER,
    url TEXT DEFAULT '',
    platform TEXT DEFAULT '',
    notes TEXT DEFAULT '',
    serpapi_property_token TEXT DEFAULT '',
    added_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS bookings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hotel_id INTEGER NOT NULL REFERENCES hotels(id),
    check_in TEXT NOT NULL,
    check_out TEXT NOT NULL,
    adults INTEGER NOT NULL DEFAULT 2,
    children_ages TEXT DEFAULT '[]',
    room_type TEXT DEFAULT '',
    booked_price REAL NOT NULL,
    currency TEXT NOT NULL DEFAULT 'JPY',
    is_cancellable INTEGER NOT NULL DEFAULT 0,
    cancellation_deadline TEXT,
    breakfast_included INTEGER NOT NULL DEFAULT 0,
    bathroom_type TEXT DEFAULT 'private',
    platform TEXT DEFAULT '',
    booking_reference TEXT DEFAULT '',
    booking_url TEXT DEFAULT '',
    extras TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    notes TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS watchlist (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hotel_id INTEGER NOT NULL REFERENCES hotels(id),
    check_in TEXT NOT NULL,
    check_out TEXT NOT NULL,
    adults INTEGER NOT NULL DEFAULT 2,
    children_ages TEXT DEFAULT '[]',
    max_price REAL,
    currency TEXT NOT NULL DEFAULT 'JPY',
    priority TEXT NOT NULL DEFAULT 'normal',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    notes TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS price_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hotel_id INTEGER NOT NULL REFERENCES hotels(id),
    check_in TEXT NOT NULL,
    check_out TEXT NOT NULL,
    adults INTEGER NOT NULL DEFAULT 2,
    children_ages TEXT DEFAULT '[]',
    room_type TEXT DEFAULT '',
    platform TEXT NOT NULL,
    price REAL NOT NULL,
    currency TEXT NOT NULL,
    is_cancellable INTEGER,
    cancellation_deadline TEXT,
    breakfast_included INTEGER,
    bathroom_type TEXT DEFAULT '',
    amenities TEXT DEFAULT '[]',
    link TEXT DEFAULT '',
    raw_llm_response TEXT DEFAULT '',
    screenshot_path TEXT DEFAULT '',
    scraped_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    booking_id INTEGER REFERENCES bookings(id),
    watchlist_id INTEGER REFERENCES watchlist(id),
    snapshot_id INTEGER REFERENCES price_snapshots(id),
    alert_type TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'info',
    title TEXT NOT NULL,
    message TEXT NOT NULL,
    price_diff REAL DEFAULT 0,
    percentage_diff REAL DEFAULT 0,
    details TEXT DEFAULT '[]',
    notified_telegram INTEGER NOT NULL DEFAULT 0,
    notified_email INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS scrape_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    total_hotels INTEGER DEFAULT 0,
    successful INTEGER DEFAULT 0,
    failed INTEGER DEFAULT 0,
    errors TEXT DEFAULT '[]',
    details TEXT DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'running'
);

CREATE INDEX IF NOT EXISTS idx_snapshots_hotel_date
    ON price_snapshots(hotel_id, check_in, scraped_at);
CREATE INDEX IF NOT EXISTS idx_alerts_created
    ON alerts(created_at);
CREATE INDEX IF NOT EXISTS idx_bookings_status
    ON bookings(status);
CREATE INDEX IF NOT EXISTS idx_bookings_hotel
    ON bookings(hotel_id);
"""


class Database:
    """SQLite database for hotel price tracking."""

    def __init__(self, path: str | Path = "data/hotel_tracker.db"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path), timeout=10)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema()

    def _init_schema(self):
        self.conn.executescript(SCHEMA)
        self._migrate()
        self.conn.commit()

    def _migrate(self):
        """Add columns that may be missing in older databases."""
        cursor = self.conn.execute("PRAGMA table_info(hotels)")
        hotel_cols = {row[1] for row in cursor.fetchall()}
        if "serpapi_property_token" not in hotel_cols:
            self.conn.execute(
                "ALTER TABLE hotels ADD COLUMN serpapi_property_token TEXT DEFAULT ''"
            )

        cursor = self.conn.execute("PRAGMA table_info(alerts)")
        alert_cols = {row[1] for row in cursor.fetchall()}
        if "details" not in alert_cols:
            self.conn.execute("ALTER TABLE alerts ADD COLUMN details TEXT DEFAULT '[]'")

        cursor = self.conn.execute("PRAGMA table_info(price_snapshots)")
        snap_cols = {row[1] for row in cursor.fetchall()}
        if "link" not in snap_cols:
            self.conn.execute("ALTER TABLE price_snapshots ADD COLUMN link TEXT DEFAULT ''")

        cursor = self.conn.execute("PRAGMA table_info(scrape_runs)")
        run_cols = {row[1] for row in cursor.fetchall()}
        if "details" not in run_cols:
            self.conn.execute("ALTER TABLE scrape_runs ADD COLUMN details TEXT DEFAULT '[]'")

        cursor = self.conn.execute("PRAGMA table_info(bookings)")
        booking_cols = {row[1] for row in cursor.fetchall()}
        if "booking_url" not in booking_cols:
            self.conn.execute("ALTER TABLE bookings ADD COLUMN booking_url TEXT DEFAULT ''")

    def close(self):
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # ── Hotels ──────────────────────────────────────────────

    @staticmethod
    def _normalize(text: str) -> str:
        """Normalize text for comparison (lowercase, collapse whitespace)."""
        return " ".join(text.lower().split())

    def upsert_hotel(self, hotel: Hotel) -> int:
        """Insert or update a hotel. Returns the hotel ID."""
        if hotel.id:
            self.conn.execute(
                """UPDATE hotels SET name=?, city=?, country=?, address=?,
                   stars=?, url=?, platform=?, notes=?,
                   serpapi_property_token=? WHERE id=?""",
                (
                    hotel.name,
                    hotel.city,
                    hotel.country,
                    hotel.address,
                    hotel.stars,
                    hotel.url,
                    hotel.platform,
                    hotel.notes,
                    hotel.serpapi_property_token,
                    hotel.id,
                ),
            )
            self.conn.commit()
            return hotel.id

        # Try to find existing by name + city (case/whitespace insensitive)
        rows = self.conn.execute("SELECT id, name, city FROM hotels").fetchall()
        norm_name = self._normalize(hotel.name)
        norm_city = self._normalize(hotel.city or "")
        for row in rows:
            if (
                self._normalize(row["name"]) == norm_name
                and self._normalize(row["city"] or "") == norm_city
            ):
                hotel.id = row["id"]
                return self.upsert_hotel(hotel)

        cur = self.conn.execute(
            """INSERT INTO hotels (name, city, country, address, stars, url, platform, notes,
                                   serpapi_property_token)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                hotel.name,
                hotel.city,
                hotel.country,
                hotel.address,
                hotel.stars,
                hotel.url,
                hotel.platform,
                hotel.notes,
                hotel.serpapi_property_token,
            ),
        )
        self.conn.commit()
        return cur.lastrowid or 0

    def _row_to_hotel(self, r: sqlite3.Row) -> Hotel:
        return Hotel(
            id=r["id"],
            name=r["name"],
            city=r["city"],
            country=r["country"],
            address=r["address"],
            stars=r["stars"],
            url=r["url"],
            platform=r["platform"],
            notes=r["notes"],
            serpapi_property_token=r["serpapi_property_token"] or "",
            added_at=parse_datetime(r["added_at"]),
        )

    def get_hotel(self, hotel_id: int) -> Hotel | None:
        row = self.conn.execute("SELECT * FROM hotels WHERE id=?", (hotel_id,)).fetchone()
        if not row:
            return None
        return self._row_to_hotel(row)

    def get_all_hotels(self) -> list[Hotel]:
        rows = self.conn.execute("SELECT * FROM hotels ORDER BY id").fetchall()
        return [self._row_to_hotel(r) for r in rows]

    # ── Bookings ────────────────────────────────────────────

    def upsert_booking(self, booking: Booking) -> int:
        """Insert or update a booking. Deduplicates by booking_reference
        or by (hotel_id, check_in, check_out, platform). Returns booking ID."""
        existing_id = None

        # 1. Match by booking_reference if available
        if booking.booking_reference:
            row = self.conn.execute(
                "SELECT id FROM bookings WHERE booking_reference=? AND booking_reference != ''",
                (booking.booking_reference,),
            ).fetchone()
            if row:
                existing_id = row["id"]

        # 2. Match by (hotel_id, check_in, check_out, platform)
        if not existing_id:
            row = self.conn.execute(
                """SELECT id FROM bookings
                   WHERE hotel_id=? AND check_in=? AND check_out=? AND platform=?""",
                (
                    booking.hotel_id,
                    date_to_str(booking.check_in),
                    date_to_str(booking.check_out),
                    booking.platform,
                ),
            ).fetchone()
            if row:
                existing_id = row["id"]

        params = (
            booking.hotel_id,
            date_to_str(booking.check_in),
            date_to_str(booking.check_out),
            booking.travelers.adults,
            json.dumps(booking.travelers.children_ages),
            booking.room_type,
            booking.booked_price,
            booking.currency,
            int(booking.is_cancellable),
            date_to_str(booking.cancellation_deadline),
            int(booking.breakfast_included),
            booking.bathroom_type,
            booking.platform,
            booking.booking_reference,
            booking.booking_url,
            booking.extras,
            booking.status,
            booking.notes,
        )

        if existing_id:
            self.conn.execute(
                """UPDATE bookings SET
                   hotel_id=?, check_in=?, check_out=?, adults=?, children_ages=?,
                   room_type=?, booked_price=?, currency=?, is_cancellable=?,
                   cancellation_deadline=?, breakfast_included=?, bathroom_type=?,
                   platform=?, booking_reference=?, booking_url=?, extras=?, status=?, notes=?
                   WHERE id=?""",
                (*params, existing_id),
            )
            self.conn.commit()
            return int(existing_id)

        cur = self.conn.execute(
            """INSERT INTO bookings
               (hotel_id, check_in, check_out, adults, children_ages,
                room_type, booked_price, currency, is_cancellable,
                cancellation_deadline, breakfast_included, bathroom_type,
                platform, booking_reference, booking_url, extras, status, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            params,
        )
        self.conn.commit()
        return cur.lastrowid or 0

    def get_active_bookings(self) -> list[Booking]:
        rows = self.conn.execute(
            "SELECT * FROM bookings WHERE status='active' ORDER BY check_in"
        ).fetchall()
        return [self._row_to_booking(r) for r in rows]

    def get_bookings_for_hotel(self, hotel_id: int) -> list[Booking]:
        rows = self.conn.execute(
            "SELECT * FROM bookings WHERE hotel_id=? ORDER BY check_in",
            (hotel_id,),
        ).fetchall()
        return [self._row_to_booking(r) for r in rows]

    def _row_to_booking(self, r: sqlite3.Row) -> Booking:
        return Booking(
            id=r["id"],
            hotel_id=r["hotel_id"],
            check_in=parse_date(r["check_in"]),
            check_out=parse_date(r["check_out"]),
            travelers=TravelerComposition(
                adults=r["adults"],
                children_ages=json.loads(r["children_ages"] or "[]"),
            ),
            room_type=r["room_type"],
            booked_price=r["booked_price"],
            currency=r["currency"],
            is_cancellable=bool(r["is_cancellable"]),
            cancellation_deadline=parse_date(r["cancellation_deadline"]),
            breakfast_included=bool(r["breakfast_included"]),
            bathroom_type=r["bathroom_type"],
            platform=r["platform"],
            booking_reference=r["booking_reference"],
            booking_url=r["booking_url"] or "",
            extras=r["extras"],
            status=r["status"],
            created_at=parse_datetime(r["created_at"]),
            notes=r["notes"],
        )

    def get_booking_by_id(self, booking_id: int) -> Booking | None:
        """Get a single booking by its ID."""
        row = self.conn.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)).fetchone()
        return self._row_to_booking(row) if row else None

    def update_booking(self, booking: Booking) -> None:
        """Update an existing booking by ID. Raises ValueError if no ID."""
        if not booking.id:
            raise ValueError("Cannot update booking without an ID")
        self.conn.execute(
            """UPDATE bookings SET
               hotel_id=?, check_in=?, check_out=?, adults=?, children_ages=?,
               room_type=?, booked_price=?, currency=?, is_cancellable=?,
               cancellation_deadline=?, breakfast_included=?, bathroom_type=?,
               platform=?, booking_reference=?, booking_url=?, extras=?, status=?, notes=?
               WHERE id=?""",
            (
                booking.hotel_id,
                date_to_str(booking.check_in),
                date_to_str(booking.check_out),
                booking.travelers.adults,
                json.dumps(booking.travelers.children_ages),
                booking.room_type,
                booking.booked_price,
                booking.currency,
                int(booking.is_cancellable),
                date_to_str(booking.cancellation_deadline),
                int(booking.breakfast_included),
                booking.bathroom_type,
                booking.platform,
                booking.booking_reference,
                booking.booking_url,
                booking.extras,
                booking.status,
                booking.notes,
                booking.id,
            ),
        )
        self.conn.commit()

    # ── Watchlist ───────────────────────────────────────────

    def add_watchlist(self, entry: WatchlistEntry) -> int:
        cur = self.conn.execute(
            """INSERT INTO watchlist
               (hotel_id, check_in, check_out, adults, children_ages,
                max_price, currency, priority, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                entry.hotel_id,
                date_to_str(entry.check_in),
                date_to_str(entry.check_out),
                entry.travelers.adults,
                json.dumps(entry.travelers.children_ages),
                entry.max_price,
                entry.currency,
                entry.priority,
                entry.notes,
            ),
        )
        self.conn.commit()
        return cur.lastrowid or 0

    # ── Price Snapshots ─────────────────────────────────────

    def add_snapshot(self, snap: PriceSnapshot) -> int:
        cur = self.conn.execute(
            """INSERT INTO price_snapshots
               (hotel_id, check_in, check_out, adults, children_ages,
                room_type, platform, price, currency, is_cancellable,
                cancellation_deadline, breakfast_included, bathroom_type,
                amenities, link, raw_llm_response, screenshot_path)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                snap.hotel_id,
                date_to_str(snap.check_in),
                date_to_str(snap.check_out),
                snap.travelers.adults,
                json.dumps(snap.travelers.children_ages),
                snap.room_type,
                snap.platform,
                snap.price,
                snap.currency,
                int(snap.is_cancellable) if snap.is_cancellable is not None else None,
                date_to_str(snap.cancellation_deadline),
                int(snap.breakfast_included) if snap.breakfast_included is not None else None,
                snap.bathroom_type,
                json.dumps(snap.amenities),
                snap.link,
                snap.raw_llm_response,
                snap.screenshot_path,
            ),
        )
        self.conn.commit()
        return cur.lastrowid or 0

    def get_latest_snapshots(
        self, hotel_id: int, check_in: date, check_out: date
    ) -> list[PriceSnapshot]:
        """Get the most recent snapshot per platform for a hotel+dates combo.

        Deduplicates by platform so that only the newest scrape result for each
        provider is returned (avoids stale duplicates from repeated scrapes).
        """
        rows = self.conn.execute(
            """SELECT ps.* FROM price_snapshots ps
               INNER JOIN (
                   SELECT platform, MAX(id) AS max_id
                   FROM price_snapshots
                   WHERE hotel_id=? AND check_in=? AND check_out=?
                   GROUP BY platform
               ) latest
               ON ps.id = latest.max_id
               ORDER BY ps.price ASC""",
            (
                hotel_id,
                date_to_str(check_in),
                date_to_str(check_out),
            ),
        ).fetchall()
        return [self._row_to_snapshot(r) for r in rows]

    def get_price_history(
        self, hotel_id: int, check_in: date, check_out: date, days: int = 30
    ) -> list[PriceSnapshot]:
        """Get price history for a hotel+dates combo."""
        rows = self.conn.execute(
            """SELECT * FROM price_snapshots
               WHERE hotel_id=? AND check_in=? AND check_out=?
                 AND scraped_at >= datetime('now', ?)
               ORDER BY scraped_at""",
            (hotel_id, date_to_str(check_in), date_to_str(check_out), f"-{days} days"),
        ).fetchall()
        return [self._row_to_snapshot(r) for r in rows]

    def _row_to_snapshot(self, r: sqlite3.Row) -> PriceSnapshot:
        return PriceSnapshot(
            id=r["id"],
            hotel_id=r["hotel_id"],
            check_in=parse_date(r["check_in"]),
            check_out=parse_date(r["check_out"]),
            travelers=TravelerComposition(
                adults=r["adults"],
                children_ages=json.loads(r["children_ages"] or "[]"),
            ),
            room_type=r["room_type"],
            platform=r["platform"],
            price=r["price"],
            currency=r["currency"],
            is_cancellable=bool(r["is_cancellable"]) if r["is_cancellable"] is not None else None,
            cancellation_deadline=parse_date(r["cancellation_deadline"]),
            breakfast_included=bool(r["breakfast_included"])
            if r["breakfast_included"] is not None
            else None,
            bathroom_type=r["bathroom_type"] or "",
            amenities=json.loads(r["amenities"] or "[]"),
            link=r["link"] or "",
            raw_llm_response=r["raw_llm_response"] or "",
            screenshot_path=r["screenshot_path"] or "",
            scraped_at=parse_datetime(r["scraped_at"]),
        )

    def get_all_snapshots(self, limit: int = 200) -> list[PriceSnapshot]:
        """Get all recent snapshots (newest first)."""
        rows = self.conn.execute(
            "SELECT * FROM price_snapshots ORDER BY scraped_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [self._row_to_snapshot(r) for r in rows]

    def get_snapshot_by_id(self, snapshot_id: int) -> PriceSnapshot | None:
        """Get a single snapshot by ID."""
        row = self.conn.execute(
            "SELECT * FROM price_snapshots WHERE id=?", (snapshot_id,)
        ).fetchone()
        return self._row_to_snapshot(row) if row else None

    def delete_snapshot(self, snapshot_id: int) -> bool:
        """Delete a snapshot and its corresponding alerts. Returns True if found."""
        row = self.conn.execute(
            "SELECT id FROM price_snapshots WHERE id=?", (snapshot_id,)
        ).fetchone()
        if not row:
            return False
        self.conn.execute("DELETE FROM alerts WHERE snapshot_id=?", (snapshot_id,))
        self.conn.execute("DELETE FROM price_snapshots WHERE id=?", (snapshot_id,))
        self.conn.commit()
        return True

    def wipe_snapshots(self) -> int:
        """Delete all rows from the price_snapshots table. Returns count deleted."""
        cur = self.conn.execute("SELECT COUNT(*) FROM price_snapshots")
        count: int = cur.fetchone()[0]
        self.conn.execute("DELETE FROM alerts")
        self.conn.execute("DELETE FROM price_snapshots")
        self.conn.commit()
        return count

    # ── Alerts ──────────────────────────────────────────────

    def add_alert(self, alert: Alert) -> int:
        cur = self.conn.execute(
            """INSERT INTO alerts
               (booking_id, watchlist_id, snapshot_id, alert_type,
                severity, title, message, price_diff, percentage_diff, details)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                alert.booking_id,
                alert.watchlist_id,
                alert.snapshot_id,
                alert.alert_type,
                alert.severity,
                alert.title,
                alert.message,
                alert.price_diff,
                alert.percentage_diff,
                json.dumps(alert.details),
            ),
        )
        self.conn.commit()
        return cur.lastrowid or 0

    def alert_exists(self, booking_id: int, alert_type: str, snapshot_id: int) -> bool:
        """Check if an equivalent alert already exists for this booking+type+snapshot."""
        row = self.conn.execute(
            """SELECT 1 FROM alerts
               WHERE booking_id=? AND alert_type=? AND snapshot_id=?
               LIMIT 1""",
            (booking_id, alert_type, snapshot_id),
        ).fetchone()
        return row is not None

    def get_pending_alerts(self) -> list[Alert]:
        """Get alerts that haven't been sent yet."""
        rows = self.conn.execute(
            """SELECT * FROM alerts
               WHERE notified_telegram=0 OR notified_email=0
               ORDER BY created_at DESC"""
        ).fetchall()
        return [self._row_to_alert(r) for r in rows]

    def get_alerts_since(self, since_iso: str) -> list[Alert]:
        """Get all alerts created since the given ISO datetime string."""
        rows = self.conn.execute(
            """SELECT * FROM alerts
               WHERE created_at >= ?
               ORDER BY created_at DESC""",
            (since_iso,),
        ).fetchall()
        return [self._row_to_alert(r) for r in rows]

    def mark_alert_notified(self, alert_id: int, channel: str):
        _VALID_CHANNELS = {"telegram", "email"}
        if channel not in _VALID_CHANNELS:
            raise ValueError(f"Invalid channel '{channel}', must be one of {_VALID_CHANNELS}")
        col = f"notified_{channel}"
        self.conn.execute(f"UPDATE alerts SET {col}=1 WHERE id=?", (alert_id,))
        self.conn.commit()

    def _row_to_alert(self, r: sqlite3.Row) -> Alert:
        return Alert(
            id=r["id"],
            booking_id=r["booking_id"],
            watchlist_id=r["watchlist_id"],
            snapshot_id=r["snapshot_id"],
            alert_type=r["alert_type"],
            severity=r["severity"],
            title=r["title"],
            message=r["message"],
            price_diff=r["price_diff"],
            percentage_diff=r["percentage_diff"],
            details=json.loads(r["details"] or "[]"),
            notified_telegram=bool(r["notified_telegram"]),
            notified_email=bool(r["notified_email"]),
            created_at=parse_datetime(r["created_at"]),
        )

    # ── Scrape Runs ─────────────────────────────────────────

    def start_scrape_run(self) -> int:
        cur = self.conn.execute("INSERT INTO scrape_runs (started_at) VALUES (datetime('now'))")
        self.conn.commit()
        return cur.lastrowid or 0

    def finish_scrape_run(
        self,
        run_id: int,
        total: int,
        success: int,
        failed: int,
        errors: list[str],
        details: list[dict] | None = None,
        status: str = "completed",
    ):
        self.conn.execute(
            """UPDATE scrape_runs SET finished_at=datetime('now'),
               total_hotels=?, successful=?, failed=?, errors=?, details=?, status=?
               WHERE id=?""",
            (
                total,
                success,
                failed,
                json.dumps(errors),
                json.dumps(details or []),
                status,
                run_id,
            ),
        )
        self.conn.commit()

    def get_all_scrape_runs(self, limit: int = 50) -> list[dict]:
        """Return recent scrape runs, newest first, with parsed JSON fields."""
        rows = self.conn.execute(
            "SELECT * FROM scrape_runs ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["errors"] = json.loads(d.get("errors") or "[]")
            d["details"] = json.loads(d.get("details") or "[]")
            result.append(d)
        return result

    def get_scrape_run_by_id(self, run_id: int) -> dict | None:
        """Return a single scrape run by id with parsed JSON fields."""
        row = self.conn.execute("SELECT * FROM scrape_runs WHERE id=?", (run_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["errors"] = json.loads(d.get("errors") or "[]")
        d["details"] = json.loads(d.get("details") or "[]")
        return d

    # ── Stats ───────────────────────────────────────────────

    def get_stats(self) -> dict:
        hotels = self.conn.execute("SELECT COUNT(*) FROM hotels").fetchone()[0]
        bookings = self.conn.execute(
            "SELECT COUNT(*) FROM bookings WHERE status='active'"
        ).fetchone()[0]
        snapshots = self.conn.execute("SELECT COUNT(*) FROM price_snapshots").fetchone()[0]
        alerts = self.conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0]
        last_run = self.conn.execute(
            "SELECT * FROM scrape_runs ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
        last_run_data = None
        if last_run:
            last_run_data = dict(last_run)
            last_run_data["errors"] = json.loads(last_run_data.get("errors") or "[]")
            last_run_data["details"] = json.loads(last_run_data.get("details") or "[]")
        return {
            "hotels": hotels,
            "active_bookings": bookings,
            "price_snapshots": snapshots,
            "total_alerts": alerts,
            "last_run": last_run_data,
        }
