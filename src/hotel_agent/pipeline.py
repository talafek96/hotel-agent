"""Shared pipeline engine: scrape -> analyze -> notify.

Both the web UI 'Run Now' button and the CLI 'run' command call
``run_pipeline()`` so the logic is never duplicated.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import AppConfig
    from .db import Database

log = logging.getLogger(__name__)

# ── Result dataclass ────────────────────────────────────


@dataclass
class PipelineResult:
    """Summary returned after a full pipeline run."""

    scrape_total: int = 0
    scrape_success: int = 0
    scrape_failed: int = 0
    new_alerts: int = 0
    notifications_sent: int = 0
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


# ── Preflight checks ───────────────────────────────────


def preflight_check(config: AppConfig, db: Database) -> list[str]:
    """Return a list of warning strings. Empty list = all clear."""
    warnings: list[str] = []

    if not config.serpapi_key.get_secret_value():
        warnings.append("SERPAPI_KEY not configured — scraping will be skipped.")

    bookings = db.get_active_bookings()
    if not bookings:
        warnings.append("No active bookings to track.")
        return warnings

    missing_dates = sum(1 for b in bookings if not b.check_in or not b.check_out)
    if missing_dates:
        warnings.append(f"{missing_dates} booking(s) missing check-in/check-out dates.")

    if config.notifications.telegram.enabled and (
        not config.telegram_bot_token.get_secret_value()
        or not config.telegram_chat_id.get_secret_value()
    ):
        warnings.append("Telegram enabled but token/chat_id missing — notifications will fail.")

    return warnings


# ── Global pipeline lock ────────────────────────────────

pipeline_lock = threading.Lock()


# ── Progress callback type ──────────────────────────────

# step is one of: "preflight" | "scraping" | "analyzing" | "notifying" | "done"
ProgressCallback = Callable[[str, dict], None]


# ── Core pipeline ───────────────────────────────────────


def run_pipeline(
    config: AppConfig,
    get_db: Callable[[], AbstractContextManager[Database]],
    *,
    hotel_filter: str = "",
    on_progress: ProgressCallback | None = None,
) -> PipelineResult:
    """Full pipeline: scrape all hotels -> analyse prices -> send notifications.

    Parameters
    ----------
    config:
        Application configuration (with secrets loaded).
    get_db:
        Context-manager factory that yields a ``Database`` instance.
    hotel_filter:
        Optional substring to restrict which hotels are scraped.
    on_progress:
        Called with ``(step_name, detail_dict)`` so the UI can poll progress.

    Returns
    -------
    PipelineResult with stats about the run.
    """
    from .analysis.comparator import run_analysis
    from .api.serpapi_client import SerpAPIError, search_hotel_prices
    from .llm.hotel_matcher import verify_hotel_match
    from .notifications.email import notify_alerts_email
    from .notifications.telegram import notify_alerts

    result = PipelineResult()

    def _progress(step: str, detail: dict | None = None) -> None:
        if on_progress:
            on_progress(step, detail or {})

    # ── Step 1: Preflight ───────────────────────────────
    _progress("preflight")

    with get_db() as db:
        warnings = preflight_check(config, db)
        result.warnings = warnings

    # ── Step 2: Scrape ──────────────────────────────────
    _progress("scraping", {"completed": 0, "total": 0})

    if not config.serpapi_key.get_secret_value():
        result.errors.append("SERPAPI_KEY not configured — scraping skipped.")
    else:
        with get_db() as db:
            all_bookings = db.get_active_bookings()

            if hotel_filter:
                filtered = []
                for b in all_bookings:
                    hotel = db.get_hotel(b.hotel_id)
                    if hotel and hotel_filter.lower() in hotel.name.lower():
                        filtered.append(b)
                all_bookings = filtered

            result.scrape_total = len(all_bookings)
            run_id = db.start_scrape_run()

            scrape_results: list[dict] = []
            errors: list[str] = []

            for i, booking in enumerate(all_bookings):
                hotel = db.get_hotel(booking.hotel_id)
                if not hotel:
                    _progress(
                        "scraping",
                        {
                            "completed": i + 1,
                            "total": result.scrape_total,
                            "current_hotel": "?",
                        },
                    )
                    continue

                _progress(
                    "scraping",
                    {
                        "completed": i,
                        "total": result.scrape_total,
                        "current_hotel": hotel.name,
                    },
                )

                if not booking.check_in or not booking.check_out:
                    errors.append(f"{hotel.name}: missing dates")
                    scrape_results.append(
                        {
                            "hotel": hotel.name,
                            "provider": "serpapi",
                            "prices": 0,
                            "status": "missing dates",
                        }
                    )
                    result.scrape_failed += 1
                    continue

                try:
                    api_result = search_hotel_prices(
                        api_key=config.serpapi_key.get_secret_value(),
                        hotel=hotel,
                        check_in=booking.check_in,
                        check_out=booking.check_out,
                        travelers=booking.travelers,
                        currency=booking.currency,
                    )

                    # LLM verification for first-time matches
                    if (
                        not api_result.used_cached_token
                        and api_result.matched_name
                        and api_result.property_token
                    ):
                        is_match = verify_hotel_match(
                            config,
                            our_name=hotel.name,
                            our_city=hotel.city,
                            candidate_name=api_result.matched_name,
                            candidate_address=api_result.matched_address,
                        )
                        if is_match:
                            hotel.serpapi_property_token = api_result.property_token
                            db.upsert_hotel(hotel)
                        else:
                            msg = f"Google returned '{api_result.matched_name}' (not a match)"
                            errors.append(f"{hotel.name}: {msg}")
                            scrape_results.append(
                                {
                                    "hotel": hotel.name,
                                    "provider": "serpapi",
                                    "prices": 0,
                                    "status": msg,
                                }
                            )
                            result.scrape_failed += 1
                            continue

                    snapshots = api_result.snapshots
                    for snap in snapshots:
                        db.add_snapshot(snap)

                    sources_detail = []
                    for s in sorted(snapshots, key=lambda x: x.price):
                        sources_detail.append(
                            {
                                "platform": s.platform,
                                "link": s.link,
                                "price": s.price,
                                "currency": s.currency,
                            }
                        )
                    source_names = sorted({s.platform for s in snapshots}) if snapshots else []
                    scrape_results.append(
                        {
                            "hotel": hotel.name,
                            "provider": (", ".join(source_names) if source_names else "serpapi"),
                            "prices": len(snapshots),
                            "sources": sources_detail,
                            "status": "ok" if snapshots else "no prices",
                        }
                    )
                    result.scrape_success += 1

                except SerpAPIError as e:
                    errors.append(f"{hotel.name}: {str(e)[:100]}")
                    scrape_results.append(
                        {
                            "hotel": hotel.name,
                            "provider": "serpapi",
                            "prices": 0,
                            "status": f"error: {str(e)[:80]}",
                        }
                    )
                    result.scrape_failed += 1

            _progress(
                "scraping",
                {
                    "completed": result.scrape_total,
                    "total": result.scrape_total,
                    "current_hotel": "",
                },
            )

            db.finish_scrape_run(
                run_id,
                result.scrape_total,
                result.scrape_success,
                result.scrape_failed,
                errors,
                details=scrape_results,
            )
            result.errors.extend(errors)

    # ── Step 3: Analyze ─────────────────────────────────
    _progress("analyzing")

    with get_db() as db:
        new_alerts = run_analysis(db, config)
        result.new_alerts = len(new_alerts)

    # ── Step 4: Notify ──────────────────────────────────
    _progress("notifying")

    with get_db() as db:
        pending = db.get_pending_alerts()

        # Telegram
        tg_sent = notify_alerts(config, pending)
        for a in pending:
            if a.id and not a.notified_telegram:
                db.mark_alert_notified(a.id, "telegram")

        # Email (triggered)
        em_sent = notify_alerts_email(config, pending)
        for a in pending:
            if a.id and not a.notified_email:
                db.mark_alert_notified(a.id, "email")

        result.notifications_sent = tg_sent + em_sent

    _progress(
        "done",
        {
            "scrape_total": result.scrape_total,
            "scrape_success": result.scrape_success,
            "new_alerts": result.new_alerts,
            "notifications_sent": result.notifications_sent,
        },
    )

    return result
