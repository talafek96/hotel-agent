"""LLM-based Excel parser that handles any format."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import openpyxl
from openpyxl.utils import range_boundaries

from ..config import AppConfig
from ..models import Booking, Hotel, TravelerComposition
from ..utils import parse_date
from .client import call_llm_json

log = logging.getLogger(__name__)


def _read_cell_value(cell: Any) -> str:
    """Read a cell's value, appending its hyperlink target if present."""
    val = cell.value
    if cell.hyperlink and cell.hyperlink.target:
        link = cell.hyperlink.target
        val = f"{val} [link: {link}]" if val else f"[link: {link}]"
    return str(val).strip() if val is not None else ""


def _read_excel_table(
    file_path: str | Path,
    sheet_name: str,
    table_name: str | None = None,
) -> tuple[list[str], list[list[Any]]]:
    """Read an Excel table and return (headers, rows) as raw strings.

    If table_name is provided, reads only the range defined by that
    named Excel table. Otherwise reads the entire sheet.
    """
    wb = openpyxl.load_workbook(str(file_path), data_only=True)
    ws = wb[sheet_name]

    if table_name and table_name in ws.tables:
        table = ws.tables[table_name]
        ref = table.ref
        min_col, min_row, max_col, max_row = range_boundaries(ref)

        # Also check column A for hyperlinks (often outside the table)
        include_col_a = (min_col or 1) > 1

        if_rows_data: list[list[str]] = []
        for _row_idx, row in enumerate(
            ws.iter_rows(
                min_row=min_row,
                max_row=max_row,
                min_col=1 if include_col_a else min_col,
                max_col=max_col,
                values_only=False,
            )
        ):
            if_rows_data.append([_read_cell_value(cell) for cell in row])

        # First row = headers
        headers = if_rows_data[0] if if_rows_data else []
        data_rows = if_rows_data[1:] if len(if_rows_data) > 1 else []

        # Filter out completely empty rows and the totals row
        data_rows = [r for r in data_rows if any(v for v in r)]

        wb.close()
        return headers, data_rows
    else:
        # Read the entire sheet
        rows_data: list[list[str]] = []
        for raw_row in ws.iter_rows(values_only=False):
            rows_data.append([_read_cell_value(cell) for cell in raw_row])

        # Try to find header row (first row with multiple non-empty cells)
        header_idx = 0
        for i, parsed_row in enumerate(rows_data):
            non_empty = sum(bool(v) for v in parsed_row)
            if non_empty >= 3:
                header_idx = i
                break

        headers = rows_data[header_idx]
        data_rows = [r for r in rows_data[header_idx + 1 :] if any(v for v in r)]
        wb.close()
        return headers, data_rows


def _format_table_for_llm(headers: list[str], rows: list[list[Any]]) -> str:
    """Format an Excel table as a readable text table for the LLM."""
    lines = []

    # Header line with column indices
    header_line = " | ".join(f"[{i}] {h}" for i, h in enumerate(headers))
    lines.append(f"HEADERS: {header_line}")
    lines.append("-" * 80)

    for row_idx, row in enumerate(rows):
        parts = []
        for col_idx, val in enumerate(row):
            if val:
                col_name = headers[col_idx] if col_idx < len(headers) else f"col{col_idx}"
                parts.append(f"{col_name}: {val}")
        if parts:
            lines.append(f"ROW {row_idx + 1}: {' | '.join(parts)}")

    return "\n".join(lines)


PARSE_SYSTEM_PROMPT = """You are a data extraction assistant. You parse hotel booking data from Excel spreadsheets.

IMPORTANT RULES:
- Extract ALL hotel entries from the data, do not skip any rows
- Dates must be in YYYY-MM-DD format
- Prices should be numeric (no currency symbols)
- Identify the currency from context (column headers, symbols like ¥, $, ₪, €)
- If a booking reference or order number is present, extract it
- If cancellation info is present, extract the deadline date
- Platform names should be normalized: "Agoda", "Booking.com", "Hotels.com", "Expedia", "Direct"
- Extract hyperlinks/URLs if present — they may be booking confirmation links
- If a row seems like notes/comments rather than a hotel entry, skip it
- The data might be in Hebrew, Japanese, or English — handle all languages

Return a JSON object with this exact structure:
{
  "hotels": [
    {
      "name": "Hotel Name",
      "city": "City",
      "country": "Country (if known, infer from context)",
      "address": "Full address if available",
      "url": "Hotel page URL if found",
      "booking_url": "Booking confirmation link if found (different from hotel URL)",
      "check_in": "YYYY-MM-DD",
      "check_out": "YYYY-MM-DD",
      "room_type": "room type if available (e.g. Deluxe Twin, Standard Double)",
      "price": 12345,
      "currency": "JPY",
      "platform": "Agoda",
      "booking_reference": "reference number if found",
      "is_cancellable": true,
      "cancellation_deadline": "YYYY-MM-DD or null",
      "breakfast_included": false,
      "dinner_included": false,
      "extras": "any extras noted",
      "notes": "any relevant notes"
    }
  ],
  "inferred_context": {
    "trip_destination": "country/region",
    "trip_dates": "overall date range",
    "currency_primary": "primary currency used",
    "notes": "any other observations about the data"
  }
}"""


def parse_excel_with_llm(
    config: AppConfig,
    file_path: str | Path,
    sheet_name: str,
    table_name: str | None = None,
) -> list[dict]:
    """Parse an Excel file using LLM to extract hotel bookings.

    Returns a list of parsed hotel booking dicts.
    """
    log.info(f"Reading Excel: {file_path}, sheet={sheet_name}, table={table_name}")

    headers, rows = _read_excel_table(file_path, sheet_name, table_name)
    table_text = _format_table_for_llm(headers, rows)

    log.info(f"Table has {len(headers)} columns, {len(rows)} data rows")
    log.info(f"Table text size: {len(table_text)} chars")

    prompt = f"""Parse the following hotel booking data from an Excel spreadsheet.

EXCEL DATA:
{table_text}

Extract every hotel booking entry and return as JSON following the schema in your instructions."""

    result = call_llm_json(
        config=config,
        prompt=prompt,
        system_prompt=PARSE_SYSTEM_PROMPT,
    )

    hotels: list[dict[Any, Any]] = result.get("hotels", [])
    context = result.get("inferred_context", {})

    log.info(f"LLM extracted {len(hotels)} hotels")
    if context:
        log.info(f"Inferred context: {context}")

    return hotels


def excel_to_models(
    parsed: list[dict],
    default_travelers: TravelerComposition | None = None,
) -> list[tuple[Hotel, Booking]]:
    """Convert LLM-parsed dicts to Hotel + Booking model pairs."""
    travelers = default_travelers or TravelerComposition()
    results = []

    for entry in parsed:
        hotel = Hotel(
            name=entry.get("name", ""),
            city=entry.get("city", ""),
            country=entry.get("country", ""),
            address=entry.get("address", ""),
            url=entry.get("url", ""),
            platform=entry.get("platform", ""),
        )

        booking = Booking(
            check_in=parse_date(entry.get("check_in")),
            check_out=parse_date(entry.get("check_out")),
            travelers=travelers,
            room_type=entry.get("room_type", ""),
            booked_price=float(entry.get("price", 0)),
            currency=entry.get("currency", "JPY"),
            is_cancellable=bool(entry.get("is_cancellable", False)),
            cancellation_deadline=parse_date(entry.get("cancellation_deadline")),
            breakfast_included=bool(entry.get("breakfast_included", False)),
            dinner_included=bool(entry.get("dinner_included", False)),
            platform=entry.get("platform", ""),
            booking_reference=entry.get("booking_reference", ""),
            booking_url=entry.get("booking_url", "") or entry.get("url", ""),
            extras=entry.get("extras", ""),
            notes=entry.get("notes", ""),
        )

        results.append((hotel, booking))

    return results
