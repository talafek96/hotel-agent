"""FastAPI web dashboard for hotel price tracker."""

from __future__ import annotations

import contextlib
import json as json_mod
import logging
import os
import shutil
import tempfile
import threading
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import SecretStr

from ..config import load_config, save_config, save_secrets
from ..db import Database
from ..models import Booking, Hotel, TravelerComposition
from ..utils import PLATFORM_URLS, platform_url

log = logging.getLogger(__name__)

TEMPLATE_DIR = Path(__file__).parent / "templates"


def create_app(config_path: str | None = None) -> FastAPI:
    """Create and configure the FastAPI application."""
    from ..logging_setup import setup_logging

    setup_logging()

    if config_path is None:
        config_path = os.environ.get("HOTEL_AGENT_CONFIG", "config.yaml")
    app = FastAPI(title="Hotel Price Tracker")
    templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
    templates.env.globals["platform_url"] = platform_url
    templates.env.globals["platform_urls_json"] = json_mod.dumps(PLATFORM_URLS)
    config = load_config(config_path)

    def get_db() -> Database:
        return Database(config.db_path)

    # ── Dashboard ──────────────────────────────────
    @app.get("/", response_class=HTMLResponse)
    async def dashboard(request: Request):
        with get_db() as db:
            stats = db.get_stats()
            alerts = db.get_recent_alerts(limit=10)
            bookings = db.get_active_bookings()
            # Enrich bookings with hotel names
            booking_data = []
            for b in bookings:
                hotel = db.get_hotel(b.hotel_id)
                snapshot_count = 0
                if b.check_in and b.check_out:
                    snaps = db.get_latest_snapshots(b.hotel_id, b.check_in, b.check_out)
                    snapshot_count = len(snaps)
                booking_data.append(
                    {
                        "booking": b,
                        "hotel": hotel,
                        "snapshot_count": snapshot_count,
                    }
                )
        return templates.TemplateResponse(
            request,
            "dashboard.html",
            {
                "stats": stats,
                "alerts": alerts,
                "bookings": booking_data[:10],
            },
        )

    # ── Hotels ─────────────────────────────────────
    @app.get("/hotels", response_class=HTMLResponse)
    async def hotels_page(request: Request):
        with get_db() as db:
            hotels = db.get_all_hotels()
            hotel_data = []
            for h in hotels:
                bookings = db.get_bookings_for_hotel(h.id) if h.id is not None else []
                active = [b for b in bookings if b.status == "active"]
                hotel_data.append({"hotel": h, "active_bookings": len(active)})
        return templates.TemplateResponse(
            request,
            "hotels.html",
            {
                "hotels": hotel_data,
            },
        )

    # ── Bookings ───────────────────────────────────
    @app.get("/bookings", response_class=HTMLResponse)
    async def bookings_page(request: Request):
        with get_db() as db:
            active = db.get_active_bookings()
            booking_data = []
            for b in active:
                hotel = db.get_hotel(b.hotel_id)
                snapshot_count = 0
                if b.check_in and b.check_out:
                    snaps = db.get_latest_snapshots(b.hotel_id, b.check_in, b.check_out)
                    snapshot_count = len(snaps)
                booking_data.append(
                    {
                        "booking": b,
                        "hotel": hotel,
                        "snapshot_count": snapshot_count,
                    }
                )
        return templates.TemplateResponse(
            request,
            "bookings.html",
            {
                "bookings": booking_data,
            },
        )

    # ── Booking Edit ────────────────────────────────
    @app.get("/bookings/new", response_class=HTMLResponse)
    async def booking_new_page(request: Request):
        with get_db() as db:
            hotels = db.get_all_hotels()
        blank = Booking(travelers=config.travelers)
        return templates.TemplateResponse(
            request,
            "booking_edit.html",
            {
                "booking": blank,
                "hotel": None,
                "hotels": hotels,
                "is_new": True,
                "saved": False,
                "error": None,
            },
        )

    @app.post("/bookings/new", response_class=HTMLResponse)
    async def booking_new_save(
        request: Request,
        hotel_id: int = Form(0),
        new_hotel_name: str = Form(""),
        new_hotel_city: str = Form(""),
        check_in: str = Form(""),
        check_out: str = Form(""),
        room_type: str = Form(""),
        booked_price: float = Form(0.0),
        currency: str = Form("JPY"),
        platform: str = Form(""),
        booking_reference: str = Form(""),
        booking_url: str = Form(""),
        status: str = Form("active"),
        adults: int = Form(2),
        children_ages: str = Form(""),
        is_cancellable: str = Form(""),
        cancellation_deadline: str = Form(""),
        breakfast_included: str = Form(""),
        bathroom_type: str = Form("private"),
        notes: str = Form(""),
    ):
        from datetime import date as date_cls

        error = None
        booking = None
        hotel = None
        try:
            with get_db() as db:
                # Resolve hotel: existing or new
                if hotel_id:
                    h = db.get_hotel(hotel_id)
                    if not h:
                        raise ValueError(f"Hotel #{hotel_id} not found")
                    resolved_hotel_id = hotel_id
                    hotel = h
                elif new_hotel_name.strip():
                    new_h = Hotel(name=new_hotel_name.strip(), city=new_hotel_city.strip())
                    resolved_hotel_id = db.upsert_hotel(new_h)
                    hotel = db.get_hotel(resolved_hotel_id)
                else:
                    raise ValueError("Select an existing hotel or enter a new hotel name")

                ages: list[int] = []
                if children_ages.strip():
                    ages = [int(a.strip()) for a in children_ages.split(",") if a.strip()]

                booking = Booking(
                    hotel_id=resolved_hotel_id,
                    check_in=date_cls.fromisoformat(check_in) if check_in else None,
                    check_out=date_cls.fromisoformat(check_out) if check_out else None,
                    travelers=TravelerComposition(adults=adults, children_ages=ages),
                    room_type=room_type,
                    booked_price=booked_price,
                    currency=currency,
                    platform=platform,
                    booking_reference=booking_reference,
                    booking_url=booking_url,
                    status=status,
                    notes=notes,
                    is_cancellable=is_cancellable == "1",
                    cancellation_deadline=(
                        date_cls.fromisoformat(cancellation_deadline)
                        if cancellation_deadline
                        else None
                    ),
                    breakfast_included=breakfast_included == "1",
                    bathroom_type=bathroom_type,
                )
                booking_id = db.upsert_booking(booking)
                booking.id = booking_id
        except Exception as e:
            log.exception("Failed to create booking")
            error = str(e)

        if error:
            with get_db() as db:
                hotels = db.get_all_hotels()
            if not booking:
                booking = Booking(travelers=config.travelers)
            return templates.TemplateResponse(
                request,
                "booking_edit.html",
                {
                    "booking": booking,
                    "hotel": hotel,
                    "hotels": hotels,
                    "is_new": True,
                    "saved": False,
                    "error": error,
                },
            )

        return RedirectResponse(f"/bookings/{booking.id}/edit", status_code=303)  # type: ignore[union-attr]

    @app.get("/bookings/{booking_id}/edit", response_class=HTMLResponse)
    async def booking_edit_page(request: Request, booking_id: int):
        with get_db() as db:
            booking = db.get_booking_by_id(booking_id)
            hotel = db.get_hotel(booking.hotel_id) if booking else None
        if not booking:
            return HTMLResponse("Booking not found", status_code=404)
        return templates.TemplateResponse(
            request,
            "booking_edit.html",
            {
                "booking": booking,
                "hotel": hotel,
                "hotels": [],
                "is_new": False,
                "saved": False,
                "error": None,
            },
        )

    @app.post("/bookings/{booking_id}/edit", response_class=HTMLResponse)
    async def booking_edit_save(
        request: Request,
        booking_id: int,
        check_in: str = Form(""),
        check_out: str = Form(""),
        room_type: str = Form(""),
        booked_price: float = Form(0.0),
        currency: str = Form("JPY"),
        platform: str = Form(""),
        booking_reference: str = Form(""),
        booking_url: str = Form(""),
        status: str = Form("active"),
        adults: int = Form(2),
        children_ages: str = Form(""),
        is_cancellable: str = Form(""),
        cancellation_deadline: str = Form(""),
        breakfast_included: str = Form(""),
        bathroom_type: str = Form("private"),
        notes: str = Form(""),
    ):
        from datetime import date as date_cls

        with get_db() as db:
            booking = db.get_booking_by_id(booking_id)
            if not booking:
                return HTMLResponse("Booking not found", status_code=404)

            error = None
            try:
                booking.check_in = date_cls.fromisoformat(check_in) if check_in else None
                booking.check_out = date_cls.fromisoformat(check_out) if check_out else None
                booking.room_type = room_type
                booking.booked_price = booked_price
                booking.currency = currency
                booking.platform = platform
                booking.booking_reference = booking_reference
                booking.booking_url = booking_url
                booking.status = status
                booking.notes = notes

                # Travelers
                ages: list[int] = []
                if children_ages.strip():
                    ages = [int(a.strip()) for a in children_ages.split(",") if a.strip()]
                booking.travelers = TravelerComposition(adults=adults, children_ages=ages)

                # Booleans (checkboxes only submit value when checked)
                booking.is_cancellable = is_cancellable == "1"
                booking.cancellation_deadline = (
                    date_cls.fromisoformat(cancellation_deadline) if cancellation_deadline else None
                )
                booking.breakfast_included = breakfast_included == "1"
                booking.bathroom_type = bathroom_type

                db.update_booking(booking)
            except Exception as e:
                log.exception("Failed to update booking %s", booking_id)
                error = str(e)

            hotel = db.get_hotel(booking.hotel_id)
        return templates.TemplateResponse(
            request,
            "booking_edit.html",
            {
                "booking": booking,
                "hotel": hotel,
                "hotels": [],
                "is_new": False,
                "saved": error is None,
                "error": error,
            },
        )

    # ── Snapshots ──────────────────────────────────
    @app.get("/snapshots", response_class=HTMLResponse)
    async def snapshots_page(request: Request):
        with get_db() as db:
            snaps = db.get_all_snapshots(limit=200)
            snap_data = []
            for s in snaps:
                hotel = db.get_hotel(s.hotel_id)
                snap_data.append({"snapshot": s, "hotel": hotel})
        return templates.TemplateResponse(
            request,
            "snapshots.html",
            {
                "snapshots": snap_data,
            },
        )

    @app.post("/snapshots/wipe", response_class=HTMLResponse)
    async def wipe_snapshots(request: Request):
        with get_db() as db:
            count = db.wipe_snapshots()
        return templates.TemplateResponse(
            request,
            "snapshots.html",
            {
                "snapshots": [],
                "wiped": count,
            },
        )

    @app.post("/snapshots/{snapshot_id}/delete", response_class=HTMLResponse)
    async def delete_snapshot(request: Request, snapshot_id: int):
        with get_db() as db:
            db.delete_snapshot(snapshot_id)
            snaps = db.get_all_snapshots(limit=200)
            snap_data = []
            for s in snaps:
                hotel = db.get_hotel(s.hotel_id)
                snap_data.append({"snapshot": s, "hotel": hotel})
        return templates.TemplateResponse(
            request,
            "snapshots.html",
            {
                "snapshots": snap_data,
                "deleted": snapshot_id,
            },
        )

    @app.get("/snapshots/{snapshot_id}", response_class=HTMLResponse)
    async def snapshot_detail(request: Request, snapshot_id: int):
        with get_db() as db:
            snap = db.get_snapshot_by_id(snapshot_id)
            hotel = db.get_hotel(snap.hotel_id) if snap else None
        return templates.TemplateResponse(
            request,
            "snapshot_detail.html",
            {
                "snapshot": snap,
                "hotel": hotel,
            },
        )

    # ── Alerts ─────────────────────────────────────
    @app.get("/alerts", response_class=HTMLResponse)
    async def alerts_page(request: Request):
        with get_db() as db:
            alerts = db.get_recent_alerts(limit=200)
            alert_data = []
            for a in alerts:
                hotel = None
                booking = None
                if a.booking_id:
                    for b in db.get_active_bookings():
                        if b.id == a.booking_id:
                            booking = b
                            hotel = db.get_hotel(b.hotel_id)
                            break
                snap = db.get_snapshot_by_id(a.snapshot_id) if a.snapshot_id else None
                alert_data.append(
                    {
                        "alert": a,
                        "hotel": hotel,
                        "booking": booking,
                        "snapshot": snap,
                    }
                )
        return templates.TemplateResponse(
            request,
            "alerts.html",
            {
                "alerts": alert_data,
            },
        )

    # ── Import ─────────────────────────────────────
    @app.get("/import", response_class=HTMLResponse)
    async def import_page(request: Request):
        return templates.TemplateResponse(
            request,
            "import.html",
            {
                "result": None,
            },
        )

    @app.post("/import", response_class=HTMLResponse)
    async def import_upload(
        request: Request,
        file: UploadFile = File(...),  # noqa: B008
        sheet: str = Form(...),
        table: str = Form(""),
    ):
        from ..llm.excel_parser import excel_to_models, parse_excel_with_llm

        # Save uploaded file to temp
        suffix = Path(file.filename or "upload.xlsx").suffix
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            shutil.copyfileobj(file.file, tmp)
            tmp_path = tmp.name

        try:
            records = parse_excel_with_llm(config, tmp_path, sheet, table or None)
            pairs = excel_to_models(records, config.travelers)

            with get_db() as db:
                saved = 0
                updated = 0
                for hotel, booking in pairs:
                    hotel_id = db.upsert_hotel(hotel)
                    booking.hotel_id = hotel_id
                    existing = db.get_bookings_for_hotel(hotel_id)
                    booking_id = db.upsert_booking(booking)
                    if any(b.id == booking_id for b in existing):
                        updated += 1
                    else:
                        saved += 1

            parts = []
            if saved:
                parts.append(f"{saved} new")
            if updated:
                parts.append(f"{updated} updated")
            result = {
                "success": True,
                "message": f"Imported {' + '.join(parts or ['0'])} bookings.",
                "pairs": pairs,
            }
        except Exception as e:
            log.exception("Import failed")
            result = {"success": False, "message": str(e), "pairs": []}
        finally:
            Path(tmp_path).unlink(missing_ok=True)

        return templates.TemplateResponse(
            request,
            "import.html",
            {
                "result": result,
            },
        )

    # ── Scrape Runs History ─────────────────────────
    @app.get("/scrapes", response_class=HTMLResponse)
    async def scrapes_page(request: Request):
        with get_db() as db:
            runs = db.get_all_scrape_runs(limit=50)
        return templates.TemplateResponse(
            request,
            "scrapes.html",
            {"runs": runs},
        )

    @app.get("/scrapes/{run_id}", response_class=HTMLResponse)
    async def scrape_detail_page(request: Request, run_id: int):
        with get_db() as db:
            run = db.get_scrape_run_by_id(run_id)
        if not run:
            return templates.TemplateResponse(
                request, "scrapes.html", {"runs": [], "error": "Run not found"}
            )
        return templates.TemplateResponse(
            request,
            "scrape_detail.html",
            {"run": run},
        )

    # ── Scrape (background execution) ────────────────
    scrape_state: dict = {
        "running": False,
        "run_id": None,
        "total": 0,
        "completed": 0,
        "successful": 0,
        "failed": 0,
        "current_hotel": "",
        "results": [],
        "errors": [],
    }

    def _run_scrape_background(hotel_filter: str) -> None:
        from ..api.serpapi_client import SerpAPIError, search_hotel_prices
        from ..llm.hotel_matcher import verify_hotel_match

        try:
            with get_db() as db:
                all_bookings = db.get_active_bookings()

                if hotel_filter:
                    filtered = []
                    for b in all_bookings:
                        hotel = db.get_hotel(b.hotel_id)
                        if hotel and hotel_filter.lower() in hotel.name.lower():
                            filtered.append(b)
                    all_bookings = filtered

                run_id = db.start_scrape_run()
                scrape_state["run_id"] = run_id
                scrape_state["total"] = len(all_bookings)

                if not config.serpapi_key.get_secret_value():
                    scrape_state["errors"].append("SERPAPI_KEY not configured")
                else:
                    for booking in all_bookings:
                        hotel = db.get_hotel(booking.hotel_id)
                        if not hotel:
                            scrape_state["completed"] += 1
                            continue

                        scrape_state["current_hotel"] = hotel.name

                        if not booking.check_in or not booking.check_out:
                            scrape_state["errors"].append(f"{hotel.name}: missing dates")
                            scrape_state["results"].append(
                                {
                                    "hotel": hotel.name,
                                    "provider": "serpapi",
                                    "prices": 0,
                                    "status": "missing dates",
                                }
                            )
                            scrape_state["failed"] += 1
                            scrape_state["completed"] += 1
                            continue

                        try:
                            result = search_hotel_prices(
                                api_key=config.serpapi_key.get_secret_value(),
                                hotel=hotel,
                                check_in=booking.check_in,
                                check_out=booking.check_out,
                                travelers=booking.travelers,
                                currency=booking.currency,
                            )

                            # LLM verification for first-time matches
                            if (
                                not result.used_cached_token
                                and result.matched_name
                                and result.property_token
                            ):
                                is_match = verify_hotel_match(
                                    config,
                                    our_name=hotel.name,
                                    our_city=hotel.city,
                                    candidate_name=result.matched_name,
                                    candidate_address=result.matched_address,
                                )
                                if is_match:
                                    hotel.serpapi_property_token = result.property_token
                                    db.upsert_hotel(hotel)
                                else:
                                    msg = f"Google returned '{result.matched_name}' (not a match)"
                                    scrape_state["errors"].append(f"{hotel.name}: {msg}")
                                    scrape_state["results"].append(
                                        {
                                            "hotel": hotel.name,
                                            "provider": "serpapi",
                                            "prices": 0,
                                            "status": msg,
                                        }
                                    )
                                    scrape_state["failed"] += 1
                                    scrape_state["completed"] += 1
                                    continue

                            snapshots = result.snapshots
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
                            source_names = (
                                sorted({s.platform for s in snapshots}) if snapshots else []
                            )
                            scrape_state["results"].append(
                                {
                                    "hotel": hotel.name,
                                    "provider": (
                                        ", ".join(source_names) if source_names else "serpapi"
                                    ),
                                    "prices": len(snapshots),
                                    "sources": sources_detail,
                                    "status": "ok" if snapshots else "no prices",
                                }
                            )
                            scrape_state["successful"] += 1

                        except SerpAPIError as e:
                            scrape_state["errors"].append(f"{hotel.name}: {str(e)[:100]}")
                            scrape_state["results"].append(
                                {
                                    "hotel": hotel.name,
                                    "provider": "serpapi",
                                    "prices": 0,
                                    "status": f"error: {str(e)[:80]}",
                                }
                            )
                            scrape_state["failed"] += 1

                        scrape_state["completed"] += 1

                db.finish_scrape_run(
                    run_id,
                    scrape_state["total"],
                    scrape_state["successful"],
                    scrape_state["failed"],
                    scrape_state["errors"],
                    details=scrape_state["results"],
                )
        except Exception as exc:
            scrape_state["errors"].append(f"Scrape crashed: {str(exc)[:200]}")
            log.exception("Background scrape crashed")
        finally:
            scrape_state["running"] = False
            scrape_state["current_hotel"] = ""

    @app.get("/scrape", response_class=HTMLResponse)
    async def scrape_page(request: Request):
        with get_db() as db:
            hotels = db.get_all_hotels()
        return templates.TemplateResponse(
            request,
            "scrape.html",
            {"hotels": hotels},
        )

    @app.post("/scrape")
    async def scrape_run(hotel_filter: str = Form("")):
        if scrape_state["running"] or pipeline_state["running"]:
            return RedirectResponse("/scrape", status_code=303)

        scrape_state.update(
            {
                "running": True,
                "run_id": None,
                "total": 0,
                "completed": 0,
                "successful": 0,
                "failed": 0,
                "current_hotel": "",
                "results": [],
                "errors": [],
            }
        )
        thread = threading.Thread(target=_run_scrape_background, args=(hotel_filter,), daemon=True)
        thread.start()
        return RedirectResponse("/scrape", status_code=303)

    @app.get("/api/scrape/status")
    async def scrape_status():
        return JSONResponse(
            {
                "running": scrape_state["running"],
                "run_id": scrape_state["run_id"],
                "total": scrape_state["total"],
                "completed": scrape_state["completed"],
                "successful": scrape_state["successful"],
                "failed": scrape_state["failed"],
                "current_hotel": scrape_state["current_hotel"],
                "results": scrape_state["results"],
                "errors": scrape_state["errors"],
            }
        )

    # ── Pipeline (full run: scrape + analyze + notify) ──
    from ..pipeline import pipeline_lock, preflight_check, run_pipeline

    pipeline_state: dict = {
        "running": False,
        "step": "",
        "detail": {},
        "result": None,
        "warnings": [],
        "errors": [],
        "source": "",  # "manual" | "scheduler"
        "finished_at": "",
    }

    def _pipeline_progress(step: str, detail: dict) -> None:
        pipeline_state["step"] = step
        pipeline_state["detail"] = detail

    def _run_pipeline_background(hotel_filter: str, source: str = "manual") -> None:
        try:
            pipeline_state["source"] = source
            result = run_pipeline(
                config,
                get_db,
                hotel_filter=hotel_filter,
                on_progress=_pipeline_progress,
            )
            pipeline_state["result"] = {
                "scrape_total": result.scrape_total,
                "scrape_success": result.scrape_success,
                "scrape_failed": result.scrape_failed,
                "new_alerts": result.new_alerts,
                "notifications_sent": result.notifications_sent,
                "warnings": result.warnings,
                "errors": result.errors,
            }
            pipeline_state["errors"] = result.errors
        except Exception as exc:
            pipeline_state["errors"].append(f"Pipeline crashed: {str(exc)[:200]}")
            log.exception("Background pipeline crashed")
        finally:
            pipeline_state["running"] = False
            pipeline_state["step"] = "done"
            pipeline_state["finished_at"] = datetime.now().isoformat(timespec="seconds")
            pipeline_lock.release()

    @app.get("/api/pipeline/preflight")
    async def pipeline_preflight():
        with get_db() as db:
            warnings = preflight_check(config, db)
        return JSONResponse({"warnings": warnings})

    @app.post("/pipeline/run")
    async def pipeline_run(hotel_filter: str = Form("")):
        if not pipeline_lock.acquire(blocking=False):
            return JSONResponse(
                {"error": "Pipeline already running", "source": pipeline_state.get("source", "")},
                status_code=409,
            )

        pipeline_state.update(
            {
                "running": True,
                "step": "starting",
                "detail": {},
                "result": None,
                "warnings": [],
                "errors": [],
                "source": "manual",
            }
        )
        thread = threading.Thread(
            target=_run_pipeline_background,
            args=(hotel_filter,),
            daemon=True,
        )
        thread.start()
        return RedirectResponse("/", status_code=303)

    @app.get("/api/pipeline/status")
    async def pipeline_status():
        return JSONResponse(
            {
                "running": pipeline_state["running"],
                "step": pipeline_state["step"],
                "detail": pipeline_state["detail"],
                "result": pipeline_state["result"],
                "warnings": pipeline_state["warnings"],
                "errors": pipeline_state["errors"],
                "source": pipeline_state["source"],
                "finished_at": pipeline_state["finished_at"],
            }
        )

    # ── Scheduler ──────────────────────────────────
    from ..scheduler import ScheduleConfig, Scheduler

    state_path = Path(config.db_path).parent / "scheduler_state.json"
    scheduler = Scheduler(config, get_db, state_path)

    # Wire scheduler to update pipeline_state when it runs
    def _sched_run_start() -> None:
        pipeline_state.update(
            {
                "running": True,
                "step": "starting",
                "detail": {},
                "result": None,
                "warnings": [],
                "errors": [],
                "source": "scheduler",
            }
        )

    def _sched_run_end(summary: dict) -> None:
        pipeline_state["running"] = False
        pipeline_state["step"] = "done"
        pipeline_state["result"] = summary
        pipeline_state["finished_at"] = datetime.now().isoformat(timespec="seconds")

    scheduler._on_run_start = _sched_run_start
    scheduler._on_run_end = _sched_run_end
    scheduler._on_progress = _pipeline_progress

    # Auto-resume if scheduler was active before shutdown
    if scheduler.schedule_config.active:
        scheduler.start()

    @app.get("/scheduler", response_class=HTMLResponse)
    async def scheduler_page(request: Request):
        return templates.TemplateResponse(
            request,
            "scheduler.html",
            {"sched": scheduler.schedule_config, "saved": False, "error": None},
        )

    @app.post("/scheduler/config", response_class=HTMLResponse)
    async def scheduler_config_save(
        request: Request,
        mode: str = Form("interval"),
        interval_value: int = Form(12),
        interval_unit: str = Form("hours"),
        daily_time: str = Form("08:00"),
        weekly_time: str = Form("08:00"),
    ):
        form_data = await request.form()
        weekly_days = form_data.getlist("weekly_days")
        error = None
        try:
            new_cfg = ScheduleConfig(
                mode=mode,
                interval_value=max(1, interval_value),
                interval_unit=interval_unit if interval_unit in ("hours", "days") else "hours",
                daily_time=daily_time,
                weekly_days=[str(d) for d in weekly_days],
                weekly_time=weekly_time,
            )
            scheduler.update_config(new_cfg)
        except Exception as exc:
            error = str(exc)

        return templates.TemplateResponse(
            request,
            "scheduler.html",
            {"sched": scheduler.schedule_config, "saved": error is None, "error": error},
        )

    @app.post("/scheduler/start")
    async def scheduler_start():
        scheduler.start()
        return RedirectResponse("/scheduler", status_code=303)

    @app.post("/scheduler/stop")
    async def scheduler_stop():
        scheduler.stop()
        return RedirectResponse("/scheduler", status_code=303)

    @app.get("/api/scheduler/status")
    async def scheduler_status():
        cfg = scheduler.schedule_config
        digest_cfg = config.notifications.email
        next_digest = None
        if scheduler.is_active and digest_cfg.digest_enabled:
            ndt = scheduler._next_digest_time()
            if ndt:
                next_digest = ndt.isoformat(timespec="seconds")
        return JSONResponse(
            {
                "active": scheduler.is_active,
                "mode": cfg.mode,
                "next_run_at": cfg.next_run_at,
                "last_run_at": cfg.last_run_at,
                "interval_value": cfg.interval_value,
                "interval_unit": cfg.interval_unit,
                "daily_time": cfg.daily_time,
                "weekly_days": cfg.weekly_days,
                "weekly_time": cfg.weekly_time,
                "digest_enabled": digest_cfg.digest_enabled,
                "digest_time": digest_cfg.digest_time,
                "last_digest_at": cfg.last_digest_at,
                "next_digest_at": next_digest,
                "last_digest_status": cfg.last_digest_status,
                "last_digest_alerts": cfg.last_digest_alerts,
            }
        )

    @app.post("/api/scheduler/test-digest")
    async def scheduler_test_digest():
        """Send a test digest email immediately (ignores timing/enabled checks)."""
        from ..notifications.email import send_digest_email

        with get_db() as db:
            alerts = db.get_undigested_alerts()
            # Fall back to recent alerts if all have been digested (for testing)
            if not alerts:
                alerts = db.get_recent_alerts(limit=20)

        if not alerts:
            return JSONResponse(
                {
                    "success": False,
                    "error": "No alerts found to include in test digest",
                },
            )

        # Generate summary
        summary = ""
        with contextlib.suppress(Exception):
            summary = scheduler._generate_digest_summary(alerts)

        recipients = config.notifications.email.recipients
        gmail_user = config.gmail_user.get_secret_value()
        gmail_pass = config.gmail_app_password.get_secret_value()

        if not gmail_user or not gmail_pass:
            return JSONResponse(
                {
                    "success": False,
                    "error": "Gmail credentials not configured (set GMAIL_USER and GMAIL_APP_PASSWORD in Config > Secrets)",
                },
            )
        if not recipients:
            return JSONResponse(
                {
                    "success": False,
                    "error": "No email recipients configured (set in Config > Notifications > Recipients)",
                },
            )

        ok = send_digest_email(config, alerts, summary=summary)
        if ok:
            return JSONResponse({"success": True, "alerts": len(alerts), "recipients": recipients})
        return JSONResponse(
            {"success": False, "error": "Email send failed (check server logs for SMTP details)"},
        )

    # ── Check (price comparison) ───────────────────
    @app.get("/check", response_class=HTMLResponse)
    async def check_page(request: Request):
        return templates.TemplateResponse(
            request,
            "check.html",
            {
                "result": None,
            },
        )

    @app.post("/check", response_class=HTMLResponse)
    async def check_run(request: Request):
        from ..analysis.comparator import run_analysis

        with get_db() as db:
            new_alerts = run_analysis(db, config)
            alerts = db.get_pending_alerts()

            alert_data = []
            for a in alerts:
                hotel = None
                booking = None
                if a.booking_id:
                    for b in db.get_active_bookings():
                        if b.id == a.booking_id:
                            booking = b
                            hotel = db.get_hotel(b.hotel_id)
                            break
                alert_data.append({"alert": a, "hotel": hotel, "booking": booking})

        return templates.TemplateResponse(
            request,
            "check.html",
            {"result": {"new_alerts": new_alerts, "all_alerts": alert_data}},
        )

    # ── Config Editor ─────────────────────────────
    @app.get("/config", response_class=HTMLResponse)
    async def config_page(request: Request):
        return templates.TemplateResponse(
            request,
            "config_edit.html",
            {"config": config, "saved": False, "error": None},
        )

    @app.post("/config", response_class=HTMLResponse)
    async def config_save(
        request: Request,
        travelers_adults: int = Form(2),
        travelers_children: str = Form(""),
        llm_provider: str = Form("openai"),
        llm_model: str = Form(""),
        currency_base: str = Form("USD"),
        currency_rates: str = Form(""),
        alert_price_drop_min_absolute: float = Form(0),
        alert_price_drop_min_percentage: float = Form(0),
        alert_upgrade_max_extra_cost: float = Form(0),
        alert_upgrade_max_extra_percentage: float = Form(0),
        alert_only_cancellable: str = Form(""),
        notif_telegram: str = Form(""),
        notif_email_triggered: str = Form(""),
        notif_email_digest: str = Form(""),
        notif_digest_time: str = Form("08:00"),
        notif_email_recipients: str = Form(""),
        db_path: str = Form("hotel_tracker.db"),
        secret_openai_api_key: str = Form(""),
        secret_gemini_api_key: str = Form(""),
        secret_anthropic_api_key: str = Form(""),
        secret_serpapi_key: str = Form(""),
        secret_telegram_bot_token: str = Form(""),
        secret_telegram_chat_id: str = Form(""),
        secret_gmail_user: str = Form(""),
        secret_gmail_app_password: str = Form(""),
    ):
        nonlocal config

        error = None
        try:
            # Travelers
            ages: list[int] = []
            if travelers_children.strip():
                ages = [int(a.strip()) for a in travelers_children.split(",") if a.strip()]
            config.travelers = TravelerComposition(adults=travelers_adults, children_ages=ages)

            # LLM
            config.llm.provider = llm_provider
            config.llm.model = llm_model

            # Currency
            config.currency.base = currency_base
            rates: dict[str, float] = {}
            for line in currency_rates.strip().splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    rates[k.strip()] = float(v.strip())
            config.currency.rates = rates

            # Alerts
            config.alerts.price_drop.min_absolute = alert_price_drop_min_absolute
            config.alerts.price_drop.min_percentage = alert_price_drop_min_percentage
            config.alerts.upgrade.max_extra_cost = alert_upgrade_max_extra_cost
            config.alerts.upgrade.max_extra_percentage = alert_upgrade_max_extra_percentage
            config.alerts.only_cancellable = alert_only_cancellable == "1"

            # Notifications
            config.notifications.telegram.enabled = notif_telegram == "1"
            config.notifications.email.triggered_enabled = notif_email_triggered == "1"
            config.notifications.email.digest_enabled = notif_email_digest == "1"
            config.notifications.email.digest_time = notif_digest_time
            config.notifications.email.recipients = [
                r.strip() for r in notif_email_recipients.splitlines() if r.strip()
            ]

            # Database
            config.db_path = db_path

            # Secrets — only update if the user typed a new value (browsers
            # clear password fields, so empty means "don't change")
            secrets_changed = False
            for attr, form_val in [
                ("openai_api_key", secret_openai_api_key),
                ("gemini_api_key", secret_gemini_api_key),
                ("anthropic_api_key", secret_anthropic_api_key),
                ("serpapi_key", secret_serpapi_key),
                ("telegram_bot_token", secret_telegram_bot_token),
                ("telegram_chat_id", secret_telegram_chat_id),
                ("gmail_user", secret_gmail_user),
                ("gmail_app_password", secret_gmail_app_password),
            ]:
                if form_val:  # non-empty = user typed something
                    setattr(config, attr, SecretStr(form_val))
                    secrets_changed = True

            save_config(config, config_path)
            if secrets_changed:
                save_secrets(config)
        except Exception as e:
            log.exception("Failed to save config")
            error = str(e)

        return templates.TemplateResponse(
            request,
            "config_edit.html",
            {"config": config, "saved": error is None, "error": error},
        )

    # ── Trends ────────────────────────────────────
    @app.get("/trends", response_class=HTMLResponse)
    async def trends_page(request: Request):
        with get_db() as db:
            bookings = db.get_active_bookings()
            charts: list[dict] = []
            for b in bookings:
                hotel = db.get_hotel(b.hotel_id)
                if not hotel or not b.check_in or not b.check_out:
                    continue
                history = db.get_price_history(hotel.id or 0, b.check_in, b.check_out, days=90)
                if not history:
                    continue
                # Latest best price per platform
                latest = db.get_latest_snapshots(hotel.id or 0, b.check_in, b.check_out)
                best_price = min((s.price for s in latest), default=None)
                charts.append(
                    {
                        "hotel": hotel,
                        "booking": b,
                        "history": history,
                        "latest": latest,
                        "best_price": best_price,
                    }
                )
        return templates.TemplateResponse(request, "trends.html", {"charts": charts})

    # ── API: Trends data ──────────────────────────
    @app.get("/api/trends/{booking_id}")
    async def api_trends_data(booking_id: int):
        with get_db() as db:
            booking = db.get_booking_by_id(booking_id)
            if not booking or not booking.check_in or not booking.check_out:
                return JSONResponse({"error": "Booking not found"}, 404)
            history = db.get_price_history(
                booking.hotel_id, booking.check_in, booking.check_out, days=90
            )
            # Group by platform
            platforms: dict[str, list[dict]] = {}
            for s in history:
                ts = s.scraped_at.isoformat() if s.scraped_at else ""
                entry = {"t": ts, "y": s.price}
                platforms.setdefault(s.platform, []).append(entry)
        return {
            "booked_price": booking.booked_price,
            "currency": booking.currency,
            "platforms": platforms,
        }

    # ── API: Fetch available models ────────────────
    @app.get("/api/models")
    async def api_list_models(provider: str = "openai"):
        """Fetch available text models from the selected LLM provider."""
        import requests as req

        try:
            if provider == "openai":
                key = config.openai_api_key.get_secret_value()
                if not key:
                    return JSONResponse({"error": "No OpenAI API key configured"}, 400)
                resp = req.get(
                    "https://api.openai.com/v1/models",
                    headers={"Authorization": f"Bearer {key}"},
                    timeout=10,
                )
                resp.raise_for_status()
                data = resp.json()
                skip = {"whisper", "tts", "dall-e", "embedding", "moderation", "realtime", "audio"}
                models = sorted(
                    m["id"]
                    for m in data.get("data", [])
                    if not any(s in m["id"].lower() for s in skip)
                )

            elif provider == "gemini":
                key = config.gemini_api_key.get_secret_value()
                if not key:
                    return JSONResponse({"error": "No Gemini API key configured"}, 400)
                resp = req.get(
                    f"https://generativelanguage.googleapis.com/v1beta/models?key={key}&pageSize=1000",
                    timeout=10,
                )
                resp.raise_for_status()
                data = resp.json()
                models = sorted(
                    m["name"].split("/", 1)[1]
                    for m in data.get("models", [])
                    if "generateContent" in m.get("supportedGenerationMethods", [])
                )

            elif provider == "anthropic":
                key = config.anthropic_api_key.get_secret_value()
                if not key:
                    return JSONResponse({"error": "No Anthropic API key configured"}, 400)
                resp = req.get(
                    "https://api.anthropic.com/v1/models?limit=100",
                    headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
                    timeout=10,
                )
                resp.raise_for_status()
                data = resp.json()
                models = sorted(m["id"] for m in data.get("data", []))

            else:
                return JSONResponse({"error": f"Unknown provider: {provider}"}, 400)

            return {"models": models}

        except req.RequestException as e:
            log.warning("Failed to fetch models for %s: %s", provider, e)
            return JSONResponse({"error": str(e)}, 502)

    return app
