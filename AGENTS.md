# Development Rules

## Quality Checks (run after every code change)
```bash
python -m uv run ruff check src/ tests/
python -m uv run ruff format --check src/ tests/
python -m uv run mypy src/hotel_agent/
python -m uv run pytest
```

## Non-Obvious Constraints
- `PYTHONIOENCODING=utf-8` required on Windows for CLI commands (Hebrew/Japanese text).
- Project path contains spaces — always use `pathlib.Path`, never hardcode separators.
- Every new module must have corresponding tests. Mock LLM calls, use temp DBs.
- Rule-based logic for comparisons/alerts — do NOT use LLM where deterministic rules suffice.
- Keep AGENTS.md files short. Only document things not obvious from reading the code.
- Update this file when the user corrects you about something.

## User Preferences
- Cares about: low cost, reliability, easy maintenance, clear alerts.
- Does NOT want: fancy UI, over-engineered frameworks, AI for AI's sake.
- Wants to switch between LLM providers easily.
- Update README.md when adding features or changing setup.
