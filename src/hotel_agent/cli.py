"""CLI entry point for the hotel price tracker."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

# Fix Windows console encoding for Hebrew/Japanese characters
if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except Exception:
        pass

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(
    name="hotel-agent",
    help="Cost-efficient hotel price tracking system",
    no_args_is_help=True,
)
console = Console(force_terminal=True)


def _setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    # Quiet noisy libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("litellm").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)


@app.command(name="import")
def import_excel(
    file: str = typer.Argument(..., help="Path to the Excel file"),
    sheet: str = typer.Option(..., "--sheet", "-s", help="Sheet/tab name"),
    table: str = typer.Option(None, "--table", "-t", help="Named table within the sheet"),
    config_path: str = typer.Option("config.yaml", "--config", "-c", help="Config file path"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Parse and show results without saving to DB"
    ),
):
    """Import hotel bookings from an Excel file using LLM parsing."""
    _setup_logging(verbose)

    from .config import load_config
    from .db import Database
    from .llm.excel_parser import excel_to_models, parse_excel_with_llm

    config = load_config(config_path)

    if not Path(file).exists():
        console.print(f"[red]File not found: {file}[/red]")
        raise typer.Exit(1)

    console.print(f"Parsing Excel: [bold]{file}[/bold]")
    console.print(f"  Sheet: [cyan]{sheet}[/cyan], Table: [cyan]{table or '(entire sheet)'}[/cyan]")
    console.print(f"  LLM: [cyan]{config.llm.provider}/{config.llm.model}[/cyan]")
    console.print()

    try:
        parsed = parse_excel_with_llm(config, file, sheet, table)
    except Exception as e:
        console.print(f"[red]Error parsing Excel: {e}[/red]")
        raise typer.Exit(1) from e

    pairs = excel_to_models(parsed, config.travelers)

    if not pairs:
        console.print("[yellow]No hotel bookings found in the data.[/yellow]")
        raise typer.Exit(0)

    # Display results
    tbl = Table(title=f"Parsed {len(pairs)} Hotel Bookings")
    tbl.add_column("#", style="dim")
    tbl.add_column("Hotel", style="bold")
    tbl.add_column("City")
    tbl.add_column("Check-in")
    tbl.add_column("Check-out")
    tbl.add_column("Nights", justify="right")
    tbl.add_column("Price", justify="right")
    tbl.add_column("Platform")
    tbl.add_column("Cancellable")

    for i, (hotel, booking) in enumerate(pairs, 1):
        cancel = "[green]Yes[/green]" if booking.is_cancellable else "[red]No[/red]"
        deadline = ""
        if booking.cancellation_deadline:
            deadline = f" (until {booking.cancellation_deadline})"
        tbl.add_row(
            str(i),
            hotel.name,
            hotel.city,
            str(booking.check_in or "?"),
            str(booking.check_out or "?"),
            str(booking.nights),
            f"{booking.booked_price:,.0f} {booking.currency}",
            booking.platform,
            cancel + deadline,
        )

    console.print(tbl)

    if dry_run:
        console.print("\n[yellow]Dry run — not saving to database.[/yellow]")
        raise typer.Exit(0)

    # Save to database
    db = Database(config.db_path)
    saved = 0
    updated = 0
    for hotel, booking in pairs:
        hotel_id = db.upsert_hotel(hotel)
        booking.hotel_id = hotel_id
        # Check if booking already exists before upserting
        existing = db.get_bookings_for_hotel(hotel_id)
        booking_id = db.upsert_booking(booking)
        if any(b.id == booking_id for b in existing):
            updated += 1
        else:
            saved += 1

    db.close()
    parts = []
    if saved:
        parts.append(f"{saved} new")
    if updated:
        parts.append(f"{updated} updated")
    console.print(f"\n[green]Saved {' + '.join(parts or ['0'])} bookings to database.[/green]")


@app.command()
def status(
    config_path: str = typer.Option("config.yaml", "--config", "-c"),
):
    """Show database statistics and system status."""
    _setup_logging()

    from .config import load_config
    from .db import Database

    config = load_config(config_path)
    db = Database(config.db_path)
    stats = db.get_stats()

    console.print("\n[bold]Hotel Price Tracker - Status[/bold]\n")
    console.print(f"  Hotels tracked:    [cyan]{stats['hotels']}[/cyan]")
    console.print(f"  Active bookings:   [cyan]{stats['active_bookings']}[/cyan]")
    console.print(f"  Price snapshots:   [cyan]{stats['price_snapshots']}[/cyan]")
    console.print(f"  Alerts generated:  [cyan]{stats['total_alerts']}[/cyan]")

    if stats["last_run"]:
        run = stats["last_run"]
        console.print(f"\n  Last scrape run:   {run.get('started_at', 'N/A')}")
        console.print(f"    Status: {run.get('status', 'N/A')}")
        console.print(
            f"    Hotels: {run.get('successful', 0)}/{run.get('total_hotels', 0)} successful"
        )
    else:
        console.print("\n  [dim]No scrape runs yet.[/dim]")

    # Show config summary
    tg_status = (
        "[green]enabled[/green]" if config.notifications.telegram_enabled else "[dim]disabled[/dim]"
    )
    em_status = (
        "[green]enabled[/green]" if config.notifications.email_enabled else "[dim]disabled[/dim]"
    )
    console.print(f"\n  LLM provider:      [cyan]{config.llm.provider}[/cyan]")
    console.print(f"  Model:             [cyan]{config.llm.model}[/cyan]")
    console.print(f"  Travelers:         [cyan]{config.travelers}[/cyan]")
    console.print(f"  Base currency:     [cyan]{config.currency.base}[/cyan]")
    console.print(f"  Telegram:          {tg_status}")
    console.print(f"  Email:             {em_status}")
    console.print()

    db.close()


@app.command()
def hotels(
    config_path: str = typer.Option("config.yaml", "--config", "-c"),
):
    """List all tracked hotels and their bookings."""
    _setup_logging()

    from .config import load_config
    from .db import Database

    config = load_config(config_path)
    db = Database(config.db_path)

    all_hotels = db.get_all_hotels()
    if not all_hotels:
        console.print("[yellow]No hotels in database. Use 'hotel-agent import' first.[/yellow]")
        db.close()
        return

    tbl = Table(title=f"{len(all_hotels)} Hotels")
    tbl.add_column("ID", style="dim")
    tbl.add_column("Hotel", style="bold")
    tbl.add_column("City")
    tbl.add_column("Bookings", justify="right")
    tbl.add_column("Platform")

    for h in all_hotels:
        bookings = db.get_bookings_for_hotel(h.id) if h.id is not None else []
        active = [b for b in bookings if b.status == "active"]
        tbl.add_row(
            str(h.id),
            h.name,
            h.city,
            str(len(active)),
            h.platform,
        )

    console.print(tbl)
    db.close()


@app.command()
def bookings(
    config_path: str = typer.Option("config.yaml", "--config", "-c"),
):
    """List all active bookings with details."""
    _setup_logging()

    from .config import load_config
    from .db import Database

    config = load_config(config_path)
    db = Database(config.db_path)

    active = db.get_active_bookings()
    if not active:
        console.print("[yellow]No active bookings.[/yellow]")
        db.close()
        return

    tbl = Table(title=f"{len(active)} Active Bookings")
    tbl.add_column("#", style="dim")
    tbl.add_column("Hotel", style="bold")
    tbl.add_column("Check-in")
    tbl.add_column("Check-out")
    tbl.add_column("Nights", justify="right")
    tbl.add_column("Price", justify="right")
    tbl.add_column("Per Night", justify="right")
    tbl.add_column("Platform")
    tbl.add_column("Source")
    tbl.add_column("Cancel")

    for i, b in enumerate(active, 1):
        hotel = db.get_hotel(b.hotel_id)
        name = hotel.name if hotel else f"Hotel #{b.hotel_id}"
        cancel = "[green]Yes[/green]" if b.is_cancellable else "[red]No[/red]"
        # Determine source: imported bookings have no scrape snapshots yet
        source = "[cyan]imported[/cyan]"
        if b.check_in and b.check_out:
            snaps = db.get_latest_snapshots(b.hotel_id, b.check_in, b.check_out)
            if snaps:
                providers = sorted({s.platform for s in snaps if s.platform})
                source = (
                    f"[green]scraped ({', '.join(providers)})[/green]"
                    if providers
                    else "[green]scraped[/green]"
                )
        tbl.add_row(
            str(i),
            name,
            str(b.check_in or "?"),
            str(b.check_out or "?"),
            str(b.nights),
            f"{b.booked_price:,.0f} {b.currency}",
            f"{b.price_per_night:,.0f} {b.currency}",
            b.platform,
            source,
            cancel,
        )

    console.print(tbl)
    db.close()


@app.command()
def scrape(
    hotel_name: str | None = typer.Argument(
        None, help="Scrape a specific hotel by name (or all if omitted)"
    ),
    config_path: str = typer.Option("config.yaml", "--config", "-c"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """Fetch current prices for tracked hotels via SerpAPI Google Hotels."""
    _setup_logging(verbose)

    from .api.serpapi_client import SerpAPIError, search_hotel_prices
    from .config import load_config
    from .db import Database
    from .llm.hotel_matcher import verify_hotel_match

    config = load_config(config_path)

    if not config.serpapi_key:
        console.print(
            "[red]SERPAPI_KEY not configured. Set it in .env or as an environment variable.[/red]"
        )
        raise typer.Exit(1)

    db = Database(config.db_path)
    all_bookings = db.get_active_bookings()

    if not all_bookings:
        console.print(
            "[yellow]No active bookings to scrape. Use 'hotel-agent import' first.[/yellow]"
        )
        db.close()
        return

    # Filter by hotel name if specified
    if hotel_name:
        filtered = []
        for b in all_bookings:
            hotel = db.get_hotel(b.hotel_id)
            if hotel and hotel_name.lower() in hotel.name.lower():
                filtered.append(b)
        if not filtered:
            console.print(f"[yellow]No bookings found matching '{hotel_name}'.[/yellow]")
            db.close()
            return
        all_bookings = filtered

    total = len(all_bookings)
    console.print(f"Fetching prices for [bold]{total}[/bold] bookings via SerpAPI...")
    console.print()

    run_id = db.start_scrape_run()
    success = 0
    failed = 0
    errors: list[str] = []

    for i, booking in enumerate(all_bookings, 1):
        hotel = db.get_hotel(booking.hotel_id)
        if not hotel:
            continue

        console.print(
            f"[{i}/{total}] [bold]{hotel.name}[/bold] ({hotel.city})...",
            end=" ",
        )

        if not booking.check_in or not booking.check_out:
            console.print("[yellow]missing dates, skipped[/yellow]")
            errors.append(f"{hotel.name}: missing check-in/check-out dates")
            failed += 1
            continue

        try:
            result = search_hotel_prices(
                api_key=config.serpapi_key,
                hotel=hotel,
                check_in=booking.check_in,
                check_out=booking.check_out,
                travelers=booking.travelers,
                currency=booking.currency,
            )

            # LLM verification for first-time matches
            if not result.used_cached_token and result.matched_name and result.property_token:
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
                    console.print(
                        f"[dim](verified: '{result.matched_name}')[/dim]",
                        end=" ",
                    )
                else:
                    console.print(
                        f"[yellow]LLM rejected match: '{result.matched_name}', skipped[/yellow]"
                    )
                    errors.append(
                        f"{hotel.name}: Google returned '{result.matched_name}' (not a match)"
                    )
                    failed += 1
                    continue

            snapshots = result.snapshots

            for snap in snapshots:
                db.add_snapshot(snap)

            if snapshots:
                sources = sorted({s.platform for s in snapshots})
                console.print(f"[green]{len(snapshots)} prices ({', '.join(sources)})[/green]")
            else:
                console.print("[yellow]no prices found[/yellow]")

            success += 1

        except SerpAPIError as e:
            console.print(f"[red]error: {e}[/red]")
            errors.append(f"{hotel.name}: {str(e)[:100]}")
            failed += 1

    db.finish_scrape_run(run_id, total, success, failed, errors)
    db.close()

    console.print()
    console.print(
        f"[bold]Scrape complete:[/bold] {success}/{total} hotels successful, {failed} failed"
    )


@app.command()
def snapshots(
    hotel_name: str = typer.Argument(None, help="Filter snapshots by hotel name"),
    config_path: str = typer.Option("config.yaml", "--config", "-c"),
    limit: int = typer.Option(50, "--limit", "-n", help="Max snapshots to show"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """View scraped price snapshots."""
    _setup_logging(verbose)

    from .config import load_config
    from .db import Database

    config = load_config(config_path)
    db = Database(config.db_path)

    all_snaps = db.get_all_snapshots(limit=limit)

    if hotel_name:
        filtered = []
        for snap in all_snaps:
            hotel = db.get_hotel(snap.hotel_id)
            if hotel and hotel_name.lower() in hotel.name.lower():
                filtered.append(snap)
        all_snaps = filtered

    if not all_snaps:
        console.print("[yellow]No snapshots found.[/yellow]")
        db.close()
        return

    table = Table(title="Price Snapshots")
    table.add_column("ID", style="dim")
    table.add_column("Hotel")
    table.add_column("Platform")
    table.add_column("Room Type")
    table.add_column("Price", justify="right")
    table.add_column("Dates")
    table.add_column("Scraped At")

    for snap in all_snaps:
        hotel = db.get_hotel(snap.hotel_id)
        hotel_display = hotel.name[:25] if hotel else f"#{snap.hotel_id}"
        dates = ""
        if snap.check_in and snap.check_out:
            dates = f"{snap.check_in.strftime('%m/%d')}-{snap.check_out.strftime('%m/%d')}"
        scraped = snap.scraped_at.strftime("%Y-%m-%d %H:%M") if snap.scraped_at else ""
        table.add_row(
            str(snap.id),
            hotel_display,
            snap.platform,
            snap.room_type[:30] if snap.room_type else "",
            f"{snap.price:,.0f} {snap.currency}",
            dates,
            scraped,
        )

    console.print(table)
    db.close()


@app.command()
def snapshot(
    snapshot_id: int = typer.Argument(..., help="Snapshot ID to view details"),
    config_path: str = typer.Option("config.yaml", "--config", "-c"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """View detailed info for a single price snapshot."""
    _setup_logging(verbose)

    from .config import load_config
    from .db import Database

    config = load_config(config_path)
    db = Database(config.db_path)

    snap = db.get_snapshot_by_id(snapshot_id)
    if not snap:
        console.print(f"[red]Snapshot #{snapshot_id} not found.[/red]")
        db.close()
        return

    hotel = db.get_hotel(snap.hotel_id)
    hotel_name_display = hotel.name if hotel else f"Hotel #{snap.hotel_id}"

    console.print(f"\n[bold]Snapshot #{snap.id}[/bold]")
    console.print(f"  Hotel:       {hotel_name_display}")
    if hotel and hotel.city:
        console.print(f"  City:        {hotel.city}")
    console.print(f"  Platform:    {snap.platform}")
    console.print(f"  Room Type:   {snap.room_type}")
    console.print(f"  Price:       {snap.price:,.0f} {snap.currency}")
    if snap.check_in and snap.check_out:
        nights = (snap.check_out - snap.check_in).days
        console.print(f"  Dates:       {snap.check_in} to {snap.check_out} ({nights} nights)")
        if nights > 0:
            console.print(f"  Per Night:   {snap.price / nights:,.0f} {snap.currency}")
    console.print(f"  Adults:      {snap.travelers.adults}")
    if snap.travelers.children_ages:
        console.print(f"  Children:    {snap.travelers.children_ages}")

    if snap.is_cancellable is not None:
        console.print(f"  Cancellable: {'Yes' if snap.is_cancellable else 'No'}")
    if snap.cancellation_deadline:
        console.print(f"  Cancel by:   {snap.cancellation_deadline}")
    if snap.breakfast_included is not None:
        console.print(f"  Breakfast:   {'Included' if snap.breakfast_included else 'Not included'}")
    if snap.bathroom_type:
        console.print(f"  Bathroom:    {snap.bathroom_type}")
    if snap.amenities:
        console.print(f"  Amenities:   {', '.join(snap.amenities)}")
    if snap.screenshot_path:
        console.print(f"  Screenshot:  {snap.screenshot_path}")
    if snap.scraped_at:
        console.print(f"  Scraped at:  {snap.scraped_at}")

    db.close()


@app.command()
def check(
    config_path: str = typer.Option("config.yaml", "--config", "-c"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """Run price analysis and generate alerts."""
    _setup_logging(verbose)

    from .analysis.comparator import run_analysis
    from .config import load_config
    from .db import Database

    config = load_config(config_path)
    db = Database(config.db_path)

    console.print("Running price analysis...")
    alerts = run_analysis(db, config)

    if not alerts:
        console.print("[dim]No new alerts.[/dim]")
    else:
        tbl = Table(title=f"{len(alerts)} New Alerts")
        tbl.add_column("Type", style="bold")
        tbl.add_column("Severity")
        tbl.add_column("Title")
        tbl.add_column("Savings", justify="right")

        for a in alerts:
            sev_color = {"urgent": "red", "important": "yellow", "info": "blue"}.get(
                a.severity, "white"
            )
            tbl.add_row(
                a.alert_type,
                f"[{sev_color}]{a.severity}[/{sev_color}]",
                a.title,
                f"{a.price_diff:,.0f} ({a.percentage_diff:.1f}%)" if a.price_diff else "",
            )

        console.print(tbl)

    db.close()


@app.command()
def run(
    config_path: str = typer.Option("config.yaml", "--config", "-c"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """Full pipeline: fetch prices, analyze, and notify."""
    _setup_logging(verbose)

    from .config import load_config
    from .db import Database
    from .pipeline import run_pipeline

    config = load_config(config_path)

    console.print("[bold]Hotel Price Tracker - Full Run[/bold]\n")

    def _cli_progress(step: str, detail: dict) -> None:
        if step == "scraping":
            done = detail.get("completed", 0)
            total = detail.get("total", 0)
            hotel = detail.get("current_hotel", "")
            if hotel:
                console.print(f"  [{done}/{total}] {hotel}...", end=" ")
        elif step == "analyzing":
            console.print("\n[bold]Step 2/3: Analyzing prices...[/bold]")
        elif step == "notifying":
            console.print("\n[bold]Step 3/3: Sending notifications...[/bold]")

    console.print("[bold]Step 1/3: Fetching prices...[/bold]")
    result = run_pipeline(
        config,
        lambda: Database(config.db_path),
        on_progress=_cli_progress,
    )

    if result.new_alerts:
        console.print(f"  Found [bold]{result.new_alerts}[/bold] new alerts")
    else:
        console.print("  [dim]No alerts to send.[/dim]")

    if result.notifications_sent:
        console.print(f"  Sent {result.notifications_sent} Telegram notifications")
    elif result.new_alerts:
        console.print("  [dim]No notifications sent (Telegram not configured)[/dim]")

    if result.errors:
        console.print(f"  [yellow]{len(result.errors)} error(s)[/yellow]")

    console.print("\n[green]Done![/green]")


@app.command(name="fix-travelers")
def fix_travelers(
    config_path: str = typer.Option("config.yaml", "--config", "-c"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """Update all active bookings to use the default travelers from config.

    Useful after importing bookings from Excel when the wrong default was used.
    """
    _setup_logging(verbose)

    from .config import load_config
    from .db import Database

    config = load_config(config_path)
    db = Database(config.db_path)

    bookings = db.get_active_bookings()
    updated = 0
    for b in bookings:
        if (
            b.travelers.adults != config.travelers.adults
            or b.travelers.children_ages != config.travelers.children_ages
        ):
            b.travelers = config.travelers
            db.update_booking(b)
            hotel = db.get_hotel(b.hotel_id)
            name = hotel.name if hotel else f"hotel_id={b.hotel_id}"
            console.print(f"  Updated [bold]{name}[/bold] -> {config.travelers}")
            updated += 1

    db.close()
    console.print(
        f"\n[green]Updated {updated}/{len(bookings)} bookings to {config.travelers}[/green]"
    )


@app.command()
def serve(
    config_path: str = typer.Option("config.yaml", "--config", "-c"),
    port: int = typer.Option(8000, "--port", "-p", help="Port to run the web server on"),
    host: str = typer.Option("127.0.0.1", "--host", "-h", help="Host to bind to"),
    reload: bool = typer.Option(False, "--reload", "-r", help="Auto-reload on code changes"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """Start the web dashboard."""
    _setup_logging(verbose)

    import os

    import uvicorn

    log_level = "info" if verbose else "warning"
    console.print(f"Starting web dashboard at [bold]http://{host}:{port}[/bold]")
    if reload:
        console.print("[dim]Auto-reload enabled — changes take effect automatically.[/dim]")
    console.print("Press Ctrl+C to stop.\n")

    if reload:
        os.environ["HOTEL_AGENT_CONFIG"] = config_path
        src_dir = str(Path(__file__).resolve().parent)
        uvicorn.run(
            "hotel_agent.web.app:create_app",
            factory=True,
            host=host,
            port=port,
            log_level=log_level,
            reload=True,
            reload_dirs=[src_dir],
        )
    else:
        from .web.app import create_app

        web_app = create_app(config_path)
        uvicorn.run(web_app, host=host, port=port, log_level=log_level)


@app.command(name="scheduler")
def scheduler_cmd(
    action: str = typer.Argument("status", help="status | start | stop | config"),
    config_path: str = typer.Option("config.yaml", "--config", "-c"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """View or control the pipeline scheduler."""
    _setup_logging(verbose)

    from .config import load_config
    from .scheduler import Scheduler

    config = load_config(config_path)
    state_path = Path(config.db_path).parent / "scheduler_state.json"

    # For status/config we just read the JSON file — no thread needed
    if action == "status":
        sched = Scheduler(config, lambda: __import__("contextlib").nullcontext(), state_path)
        cfg = sched.schedule_config
        active_str = "[green]Active[/green]" if cfg.active else "[yellow]Paused[/yellow]"
        console.print(f"Scheduler: {active_str}")
        console.print(f"  Mode: {cfg.mode}")
        if cfg.mode == "interval":
            console.print(f"  Every {cfg.interval_value} {cfg.interval_unit}")
        elif cfg.mode == "daily":
            console.print(f"  Daily at {cfg.daily_time}")
        elif cfg.mode == "weekly":
            console.print(f"  Weekly on {', '.join(cfg.weekly_days)} at {cfg.weekly_time}")
        if cfg.next_run_at:
            console.print(f"  Next run: {cfg.next_run_at[:19]}")
        if cfg.last_run_at:
            console.print(f"  Last run: {cfg.last_run_at[:19]}")

    elif action == "start":
        sched = Scheduler(config, lambda: __import__("contextlib").nullcontext(), state_path)
        cfg = sched.schedule_config
        cfg.active = True
        sched.schedule_config = cfg
        console.print("[green]Scheduler marked active.[/green]")
        console.print("The scheduler runs inside the web server (`hotel-agent serve`).")

    elif action == "stop":
        sched = Scheduler(config, lambda: __import__("contextlib").nullcontext(), state_path)
        cfg = sched.schedule_config
        cfg.active = False
        sched.schedule_config = cfg
        console.print("[yellow]Scheduler marked inactive.[/yellow]")

    elif action == "config":
        if state_path.exists():
            console.print(state_path.read_text(encoding="utf-8"))
        else:
            console.print("[dim]No scheduler state file found.[/dim]")
            console.print(f"Expected at: {state_path}")

    else:
        console.print(f"[red]Unknown action: {action}[/red]")
        console.print("Valid actions: status, start, stop, config")
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
