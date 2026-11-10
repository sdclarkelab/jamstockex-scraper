"""Parsing of JSE website pages.

Columns are located by normalised header text, not position, so an inserted
or reordered column doesn't break parsing. When the site renames a header,
add the new normalised name to the relevant alias tuple. Value parsers
return None for anything they can't parse; they never invent a 0.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
from decimal import Decimal, InvalidOperation
from urllib.parse import parse_qs, urlparse

from jamstockex.html import Cell, Row, Table, extract_tables
from jamstockex.models import Company, CorporateAction, Index, Quote

log = logging.getLogger(__name__)

Columns = dict[str, int | None]
Aliases = dict[str, tuple[str, ...]]

_EMPTY = {"", "-", "--", "n/a", "na", "nil"}
_DATE_FORMATS = ("%a %d %b %Y", "%d %b %Y", "%Y-%m-%d", "%A %d %B %Y", "%d %B %Y")


class ParseError(Exception):
    """A page doesn't have the structure we expect (usually a site layout change)."""

    def __init__(self, page: str, problem: str) -> None:
        super().__init__(f"{page}: {problem}")
        self.page = page
        self.problem = problem


# --- table helpers -------------------------------------------------------


def normalize_header(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower().replace("%", "pct"))


def header_index(table: Table) -> dict[str, int]:
    """Normalised header text -> column position, from the table's first row."""
    if not table.rows:
        return {}
    index: dict[str, int] = {}
    for position, cell in enumerate(table.rows[0].cells):
        index.setdefault(normalize_header(cell.text), position)
    return index


def resolve_columns(header: dict[str, int], aliases: Aliases) -> Columns:
    return {field: next((header[name] for name in names if name in header), None) for field, names in aliases.items()}


def matching_tables(tables: list[Table], aliases: Aliases, required: tuple[str, ...]) -> list[tuple[Table, Columns]]:
    matches = []
    for table in tables:
        columns = resolve_columns(header_index(table), aliases)
        if all(columns[field] is not None for field in required):
            matches.append((table, columns))
    return matches


def data_rows(table: Table) -> list[Row]:
    """Rows after the header that have <td> cells and some text (blank spacer rows are dropped)."""
    return [
        row for row in table.rows[1:]
        if any(not cell.header for cell in row.cells) and any(cell.text for cell in row.cells)
    ]


def warn_missing_columns(page: str, column_sets: list[Columns], ignore: tuple[str, ...] = ()) -> None:
    """Warn once per page about optional fields whose header matched no alias.

    Required fields raise ParseError instead. Without this warning, a renamed optional
    header would silently turn every value in that column into null.
    """
    missing = sorted({f for cols in column_sets for f, idx in cols.items() if idx is None} - set(ignore))
    if missing:
        log.warning("%s: column(s) not found, values will be null: %s", page, ", ".join(missing))


def cell_text(cells: list[Cell], idx: int | None) -> str:
    if idx is None or idx >= len(cells):
        return ""
    return cells[idx].text


def cell_href(cells: list[Cell], idx: int | None) -> str | None:
    if idx is None or idx >= len(cells) or not cells[idx].hrefs:
        return None
    return cells[idx].hrefs[0]


def instrument_code_from_href(href: str | None) -> str | None:
    if not href:
        return None
    values = parse_qs(urlparse(href).query).get("instrument")
    if not values:
        return None
    return values[0].strip() or None


def row_instrument_code(row: Row) -> str | None:
    for cell in row.cells:
        for href in cell.hrefs:
            code = instrument_code_from_href(href)
            if code:
                return code
    return None


# --- value parsers -------------------------------------------------------


def to_decimal(text: str | None) -> Decimal | None:
    if text is None:
        return None
    cleaned = text.strip().replace(",", "").replace("$", "").replace("%", "").replace(" ", "")
    negative = cleaned.startswith("(") and cleaned.endswith(")")
    if negative:
        cleaned = cleaned[1:-1]
    if cleaned.lower() in _EMPTY:
        return None
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        return None
    if not value.is_finite():
        return None
    return -value if negative else value


def to_int(text: str | None) -> int | None:
    value = to_decimal(text)
    if value is None or value != value.to_integral_value():
        return None
    return int(value)


def parse_date(text: str | None) -> dt.date | None:
    cleaned = " ".join((text or "").split())
    for fmt in _DATE_FORMATS:
        try:
            return dt.datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    return None


def parse_amount(text: str | None) -> tuple[str | None, Decimal | None]:
    """'JMD 0.7500' -> ('JMD', Decimal('0.7500')); '0.12' -> (None, Decimal('0.12'))."""
    parts = (text or "").split()
    if not parts:
        return None, None
    if len(parts) >= 2 and parts[0].isalpha():
        return parts[0].upper(), to_decimal(parts[-1])
    return None, to_decimal(parts[-1])


def normalize_action_type(text: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")


# --- listed companies ----------------------------------------------------

LISTING_COLUMNS: Aliases = {
    "name": ("security", "instrument", "instrumentname", "company", "name"),
    "symbol": ("symbol", "ticker"),
    "currency": ("currency",),
    "sector": ("sector",),
    "type": ("type", "instrumenttype", "securitytype"),
    "website": ("website", "url"),
}


def _website(cells: list[Cell], idx: int | None) -> str | None:
    href = cell_href(cells, idx)
    if not href or not href.startswith(("http://", "https://")):
        return None
    if "jamstockex.com" in urlparse(href).netloc.lower():
        return None
    return href


def parse_listed_companies(html: str, market_label: str) -> list[Company]:
    page = extract_tables(html)
    tables = matching_tables(page, LISTING_COLUMNS, ("name", "symbol"))
    if not tables:
        raise ParseError("listed-companies", "no table with 'security' and 'symbol' columns")
    warn_missing_columns(f"listed-companies ({market_label})", [cols for _, cols in tables])
    companies: dict[str, Company] = {}
    skipped: set[tuple[str, ...]] = set()  # a row repeated in the mobile copy counts once
    for table, cols in tables:
        for row in data_rows(table):
            cells = row.cells
            code = row_instrument_code(row)
            symbol = cell_text(cells, cols["symbol"])
            if not code or not symbol:
                skipped.add(tuple(cell.text for cell in cells))
                continue
            companies.setdefault(code, Company(
                instrument_code=code,
                symbol=symbol,
                name=cell_text(cells, cols["name"]),
                market=market_label,
                currency=cell_text(cells, cols["currency"]) or None,
                sector=cell_text(cells, cols["sector"]) or None,
                type=cell_text(cells, cols["type"]) or None,
                website=_website(cells, cols["website"]),
            ))
    if skipped:
        log.warning("listed-companies (%s): skipped %d row(s) without an instrument link or symbol",
                    market_label, len(skipped))
    return list(companies.values())


# --- trade quotes and indices ---------------------------------------------

QUOTE_COLUMNS: Aliases = {
    "symbol": ("symbol",),
    "close": ("closingprice", "closeprice", "lasttradedprice", "lastprice"),
    "change": ("pricechange", "change", "changes"),
    "change_pct": ("pctchange", "changepct", "percentchange"),
    "volume": ("volume", "volumetraded"),
}

INDEX_COLUMNS: Aliases = {
    "name": ("index", "indexname"),
    "value": ("value", "indexvalue", "closingvalue"),
    "change": ("change", "pointchange", "valuechange"),
    "change_pct": ("pctchange", "changepct", "percentchange"),
    "volume": ("volume",),
}


# The site's message for a date with no trade data. Matched on squashed, lower-cased page text.
NO_DATA_MARKER = "looks like there is no data coming back"


def is_no_data_page(html: str) -> bool:
    return NO_DATA_MARKER in " ".join(html.lower().split())


def compute_change_pct(close: Decimal | None, change: Decimal | None) -> Decimal | None:
    if close is None or change is None:
        return None
    previous = close - change
    if previous == 0:
        return None
    return (change / previous * 100).quantize(Decimal("0.01"))


def parse_trade_quotes(html: str, trade_date: dt.date) -> tuple[dict[str, Quote], list[Index]]:
    page = extract_tables(html)
    quote_tables = matching_tables(page, QUOTE_COLUMNS, ("symbol", "close"))
    index_tables = [
        (table, cols)
        for table, cols in matching_tables(page, INDEX_COLUMNS, ("name", "value"))
        if "symbol" not in header_index(table)
    ]
    # A date with no trading (holiday) gets a page with no tables and the site's "no data" message.
    # No quotes table without that message means the layout changed, which must fail loudly
    # rather than look like a holiday.
    if not quote_tables:
        if is_no_data_page(html):
            log.info("trade-quotes: the site reports no data for %s (no trading that day)", trade_date.isoformat())
            return {}, []
        raise ParseError("trade-quotes", "no quotes table with 'symbol' and 'closing price' columns")
    if not index_tables:
        log.warning("trade-quotes: no indices table (with 'index' and 'value' columns) found")
    warn_missing_columns("trade-quotes", [cols for _, cols in quote_tables], ignore=("change_pct",))
    warn_missing_columns("trade-quotes (indices)", [cols for _, cols in index_tables])

    quotes: dict[str, Quote] = {}
    skipped: set[tuple[str, ...]] = set()  # a row repeated in the mobile copy counts once
    for table, cols in quote_tables:
        for row in data_rows(table):
            cells = row.cells
            code = row_instrument_code(row)
            if not code or not cell_text(cells, cols["symbol"]):
                skipped.add(tuple(cell.text for cell in cells))
                continue
            close = to_decimal(cell_text(cells, cols["close"]))
            change = to_decimal(cell_text(cells, cols["change"]))
            change_pct = to_decimal(cell_text(cells, cols["change_pct"]))
            if change_pct is None:
                change_pct = compute_change_pct(close, change)
            quotes.setdefault(code, Quote(
                date=trade_date,
                close=close,
                change=change,
                change_pct=change_pct,
                volume=to_int(cell_text(cells, cols["volume"])),
            ))

    if skipped:
        log.warning("trade-quotes: skipped %d row(s) without an instrument link or symbol", len(skipped))

    indices: dict[str, Index] = {}
    for table, cols in index_tables:
        for row in data_rows(table):
            cells = row.cells
            name = cell_text(cells, cols["name"])
            if not name:
                continue
            indices.setdefault(name, Index(
                name=name,
                date=trade_date,
                value=to_decimal(cell_text(cells, cols["value"])),
                change=to_decimal(cell_text(cells, cols["change"])),
                change_pct=to_decimal(cell_text(cells, cols["change_pct"])),
                volume=to_int(cell_text(cells, cols["volume"])),
            ))
    return quotes, list(indices.values())
