# Hotel Price Tracker

A cost-efficient hotel price tracking system that monitors booking prices across platforms and alerts you to savings opportunities.

## Features

- **LLM-powered Excel import** — Reads your hotel bookings from any Excel format using AI. No rigid column requirements.
- **SerpAPI hotel price fetching** — Queries Google Hotels via SerpAPI to get prices from Booking.com, Agoda, Expedia, and more in a single API call. No browser scraping, no CAPTCHAs.
- **Smart price alerts** — Detects price drops, upgrade opportunities, and new cancellable options using configurable rule-based logic.
- **Multi-provider LLM support** — Switch between OpenAI, Google Gemini, and Anthropic Claude via config.
- **Web dashboard** — FastAPI-based dashboard for managing hotels, bookings, snapshots, and alerts.
- **Telegram & Email notifications** — Get instant alerts on your phone or daily email digests.
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

# Install dependencies
python -m uv sync
```

### Configuration

1. Copy the example env file and add your API key:
```bash
cp .env.example .env
# Edit .env and set your LLM API key
```

2. Edit `config.yaml` to set your preferences:
   - Traveler composition (adults, children ages)
   - LLM provider and model
   - Currency settings
   - Alert thresholds
   - Notification preferences

### Usage

```bash
# Import bookings from Excel
hotel-agent import "data/hotels.xlsx" --sheet "Sheet1" --table "Hotels"

# Check what was imported
hotel-agent bookings

# Scrape current prices (via SerpAPI)
hotel-agent scrape

# Run price analysis and generate alerts
hotel-agent check

# Full pipeline: scrape + analyze + notify
hotel-agent run

# View system status
hotel-agent status
```

On Windows, prefix commands with `PYTHONIOENCODING=utf-8` for proper Unicode support:
```bash
PYTHONIOENCODING=utf-8 hotel-agent import "data/hotels.xlsx" -s "Sheet1" -t "Hotels"
```

## Architecture

```
Excel File (any format)
    |
    v  LLM parses
SQLite Database
    |
    v  For each booking:
SerpAPI Google Hotels -> Price Snapshots (multi-OTA)
    |
    v  Rule engine compares
Alerts -> Telegram / Email
```

- **LLM is used for**: Excel parsing (any format)
- **SerpAPI is used for**: Hotel price data from multiple OTAs in one call
- **LLM is NOT used for**: Price comparisons, alert rules, notifications (all deterministic)

## Project Structure

```
hotel-agent/
├── AGENTS.md              # Development rules
├── config.yaml            # User configuration
├── pyproject.toml         # Project & tool config
├── src/hotel_agent/
│   ├── cli.py             # CLI commands (typer)
│   ├── config.py          # Config loading
│   ├── db.py              # SQLite database
│   ├── models.py          # Data models
│   ├── api/
│   │   └── serpapi_client.py # SerpAPI Google Hotels client
│   ├── llm/
│   │   ├── client.py      # Multi-provider LLM client
│   │   └── excel_parser.py # LLM-based Excel parsing
│   ├── analysis/
│   │   └── comparator.py  # Price comparison rules
│   ├── web/
│   │   ├── app.py         # FastAPI web dashboard
│   │   └── templates/     # Jinja2 HTML templates
│   └── notifications/
│       └── telegram.py    # Telegram bot alerts
├── tests/                 # Test suite
└── data/                  # Database (gitignored)
```

## Development

```bash
# Install with dev tools
python -m uv sync --group dev

# Run linter
python -m uv run ruff check src/ tests/

# Run type checker
python -m uv run mypy src/hotel_agent/

# Run tests
python -m uv run pytest

# Auto-format code
python -m uv run ruff format src/ tests/
```

## License

Private project.
