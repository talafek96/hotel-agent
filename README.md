# Hotel Price Tracker

A cost-efficient hotel price tracking system that monitors booking prices across platforms and alerts you to savings opportunities scheduler based.

## Features

- **LLM-powered Excel import** — Reads hotel bookings from any Excel format using AI. No rigid column requirements.
- **SerpAPI hotel price fetching** — Queries Google Hotels via SerpAPI to get prices from Booking.com, Agoda, Expedia, and more in a single API call. No browser scraping, no CAPTCHAs.
- **Smart price alerts** — Detects price drops and upgrade opportunities (cancellable rooms, breakfast, etc.) using configurable rule-based logic.
- **Multi-provider LLM support** — Switch between OpenAI, Google Gemini, and Anthropic Claude via config. Uses [litellm](https://github.com/BerriAI/litellm) as abstraction layer.
- **LLM hotel identity verification** — After scraping, verifies that Google's result actually matches your hotel (handles transliterations, naming differences). Caches property tokens for faster subsequent lookups.
- **SerpAPI retry chain** — 3-step retry for reliability: original params, children counted as adults (Google Hotels limitation), simplified query (hotel name only).
- **Web dashboard** — FastAPI-based UI with 16 pages: dashboard, hotels, bookings, snapshots, alerts, trends, scrape (with live progress), scrape history, scheduler, config editor, and more.
- **Telegram notifications** — Consolidated alert messages with severity grouping, emoji indicators, and compact vendor listings. All alerts in a single message.
- **Email notifications** — Two modes: triggered (sends email on each pipeline run) and daily digest (LLM-summarized overview of recent deals). HTML-formatted with alert tables and booking links.
- **Currency conversion** — Configurable exchange rates for cross-currency price comparison.
- **Pydantic-settings config** — Type-safe configuration with pydantic models. Secrets auto-loaded from `.env` as `SecretStr` (never leak in logs). Editable from web UI with show/hide toggles.
- **One-click pipeline** — "Run Now" button on dashboard runs the full scrape→analyze→notify pipeline with live progress and preflight checks.
- **Configurable scheduler** — Run the pipeline automatically on interval (every N hours/days), daily, or weekly schedules. Persists across server restarts. Dedicated UI with countdown timer.
- **Parallel execution safety** — Pipeline lock prevents concurrent runs. Manual and scheduled runs cannot overlap.
- **Background scraping** — Scrape runs in a background thread with live progress polling via the web UI.
- **Alert deduplication** — Same alert (booking + type + snapshot) is never inserted twice, preventing spam on repeated runs.
- **CI pipeline** — GitHub Actions with linting (ruff), type checking (mypy), and tests (pytest).
- **Minimal cost** — SerpAPI free tier: 250 searches/month. LLM extraction costs ~$1-5/month.

## Quick Start

### Prerequisites

- Python 3.13+
- [uv](https://docs.astral.sh/uv/) package manager
- An OpenAI / Gemini / Anthropic API key
- A [SerpAPI](https://serpapi.com/) API key (free tier: 250 searches/month)

### Installation

```bash
git clone <repo-url>
cd hotel-agent
uv sync
```

### Configuration

1. Copy the example files:
```bash
cp .env.example .env
cp config.example.yaml config.yaml
```

2. Edit `.env` and set your API keys:
   - At least one LLM key (`OPENAI_API_KEY`, `GEMINI_API_KEY`, or `ANTHROPIC_API_KEY`)
   - `SERPAPI_KEY` for price fetching
   - `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` for notifications (optional)

3. Edit `config.yaml` to set your preferences:
   - Traveler composition (adults, children ages)
   - LLM provider and model
   - Base currency and exchange rates (e.g. `JPY_to_USD: 0.0067`)
   - Alert thresholds (minimum savings, upgrade cost limits)
   - Notification preferences

### Usage

```bash
# Import bookings from Excel
hotel-agent import "data/hotels.xlsx" --sheet "Sheet1" --table "Hotels"
hotel-agent import "data/hotels.xlsx" --dry-run   # Preview without saving

# View data
hotel-agent hotels        # List tracked hotels
hotel-agent bookings      # List active bookings
hotel-agent snapshots     # View scraped price snapshots
hotel-agent snapshot 42   # Detailed view of a single snapshot

# Scrape current prices (via SerpAPI)
hotel-agent scrape

# Run price analysis and generate alerts
hotel-agent check

# Full pipeline: scrape + analyze + notify
hotel-agent run

# Scheduler control
hotel-agent scheduler          # Show scheduler status
hotel-agent scheduler start    # Mark scheduler active (runs inside serve)
hotel-agent scheduler stop     # Mark scheduler inactive
hotel-agent scheduler config   # Show raw scheduler state JSON

# View system status
hotel-agent status

# Batch-update all bookings to use config travelers
hotel-agent fix-travelers

# Start the web dashboard
hotel-agent serve              # http://localhost:8000
hotel-agent serve --port 3000  # Custom port
```

All commands accept `--config / -c` to specify a config file (defaults to `config.yaml`).

## Architecture

```
Excel File (any format)
    |
    v  LLM parses
SQLite Database
    |
    v  For each booking:
SerpAPI Google Hotels -> LLM verifies hotel match -> Price Snapshots (multi-OTA)
    |
    v  Rule engine compares (deterministic, no LLM)
Alerts -> Telegram
```

- **LLM is used for**: Excel parsing (any format), hotel identity verification
- **SerpAPI is used for**: Hotel price data from multiple OTAs in one call
- **LLM is NOT used for**: Price comparisons, alert rules, notifications (all deterministic)

## Project Structure

```
hotel-agent/
├── .env.example           # API keys template
├── .github/workflows/     # CI pipeline (ruff, mypy, pytest)
├── AGENTS.md              # Development rules
├── config.example.yaml    # Config template
├── pyproject.toml         # Project & tool config
├── src/hotel_agent/
│   ├── cli.py             # CLI commands (typer)
│   ├── config.py          # Config loading & currency conversion
│   ├── db.py              # SQLite database
│   ├── models.py          # Data models
│   ├── pipeline.py        # Shared pipeline: scrape → analyze → notify
│   ├── scheduler.py       # Configurable scheduler with state persistence
│   ├── utils.py           # Platform URLs, date parsing helpers
│   ├── api/
│   │   └── serpapi_client.py  # SerpAPI client with retry chain
│   ├── llm/
│   │   ├── client.py          # Multi-provider LLM client (litellm)
│   │   ├── excel_parser.py    # LLM-based Excel parsing
│   │   └── hotel_matcher.py   # LLM hotel identity verification
│   ├── analysis/
│   │   └── comparator.py      # Price comparison rules + alert dedup
│   ├── web/
│   │   ├── app.py             # FastAPI web dashboard (16 pages)
│   │   └── templates/         # Jinja2 HTML templates
│   └── notifications/
│       ├── telegram.py        # Telegram bot alerts (consolidated)
│       └── email.py           # Email notifications (triggered + digest)
├── tests/                 # Test suite
└── data/                  # Database, screenshots, scheduler state (gitignored)
```

## Development

```bash
# Install with dev tools
uv sync --group dev

# Run linter
uv run ruff check src/ tests/

# Run type checker
uv run mypy src/hotel_agent/

# Run tests
uv run pytest

# Auto-format code
uv run ruff format src/ tests/
```

## License

Private project.
