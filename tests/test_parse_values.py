import datetime as dt
from decimal import Decimal

import pytest

from jamstockex.html import extract_tables
from jamstockex.parse import (
    cell_href, cell_text, data_rows, header_index, instrument_code_from_href, matching_tables,
    normalize_action_type, normalize_header, parse_amount, parse_date, resolve_columns,
    row_instrument_code, to_decimal, to_int, warn_missing_columns,
)


@pytest.mark.parametrize("text, expected", [
    ("Closing Price ($)", "closingprice"),
    ("% Change", "pctchange"),
    ("Change (%)", "changepct"),
    ("  Ex-Date ", "exdate"),
    ("Dividend\n Amount", "dividendamount"),
])
def test_normalize_header(text, expected):
    assert normalize_header(text) == expected


@pytest.mark.parametrize("text, expected", [
    ("1,234.50", Decimal("1234.50")),
    ("$12.5", Decimal("12.5")),
    ("(1.25)", Decimal("-1.25")),
    ("-0.25", Decimal("-0.25")),
    ("1.10%", Decimal("1.10")),
    (" 7 ", Decimal("7")),
    ("", None), ("-", None), ("n/a", None), ("abc", None), ("NaN", None), ("Infinity", None), (None, None),
])
def test_to_decimal(text, expected):
    assert to_decimal(text) == expected


@pytest.mark.parametrize("text, expected", [
    ("48,213", 48213), ("1000.0", 1000), ("0", 0), ("12.5", None), ("", None), ("x", None),
])
def test_to_int(text, expected):
    assert to_int(text) == expected


@pytest.mark.parametrize("text, expected", [
    ("Fri 20 Nov 2026", dt.date(2026, 11, 20)),
    ("  Fri  20 Nov 2026 ", dt.date(2026, 11, 20)),
    ("20 Nov 2026", dt.date(2026, 11, 20)),
    ("2026-11-20", dt.date(2026, 11, 20)),
    ("Friday 20 November 2026", dt.date(2026, 11, 20)),
    ("20 November 2026", dt.date(2026, 11, 20)),
    ("", None), ("soon", None),
])
def test_parse_date(text, expected):
    assert parse_date(text) == expected


@pytest.mark.parametrize("text, expected", [
    ("JMD 0.7500", ("JMD", Decimal("0.7500"))),
    ("usd 0.01", ("USD", Decimal("0.01"))),
    ("0.12", (None, Decimal("0.12"))),
    ("1:2", (None, None)),
    ("", (None, None)),
])
def test_parse_amount(text, expected):
    assert parse_amount(text) == expected


@pytest.mark.parametrize("text, expected", [
    ("Dividend", "dividend"), ("Stock Split", "stock_split"), ("Bonus Issue", "bonus_issue"),
    ("Rights  Issue!", "rights_issue"), ("", ""), (None, ""),
])
def test_normalize_action_type(text, expected):
    assert normalize_action_type(text) == expected


@pytest.mark.parametrize("href, expected", [
    ("/trading/instruments/?instrument=9001", "9001"),
    ("https://example.test/trading/instruments/?a=1&instrument=9002", "9002"),
    ("/x/?a=1", None), ("/x/?instrument=", None), ("", None), (None, None),
])
def test_instrument_code_from_href(href, expected):
    assert instrument_code_from_href(href) == expected


TABLE_HTML = """
<table>
  <tr><th>Symbol</th><th>Closing Price ($)</th><th>Website</th></tr>
  <tr><td><a href="/i/?instrument=9001">ACME</a></td><td> 12.50 </td><td><a href="https://acme.example">Visit</a></td></tr>
  <tr><td colspan="3">Footnote</td></tr>
  <tr><td> </td><td></td><td></td></tr>
</table>
<table><tr><th>Other</th></tr><tr><td>x</td></tr></table>
"""


def test_table_helpers():
    tables = extract_tables(TABLE_HTML)
    first = tables[0]
    assert header_index(first) == {"symbol": 0, "closingprice": 1, "website": 2}

    aliases = {"symbol": ("symbol",), "close": ("closingprice", "lasttradedprice"), "volume": ("volume",)}
    assert resolve_columns(header_index(first), aliases) == {"symbol": 0, "close": 1, "volume": None}

    matches = matching_tables(tables, aliases, ("symbol", "close"))
    assert len(matches) == 1 and matches[0][0] is first

    rows = data_rows(first)
    assert len(rows) == 2
    cells = rows[0].cells
    assert cell_text(cells, 0) == "ACME"
    assert cell_text(cells, 1) == "12.50"
    assert cell_text(cells, None) == ""
    assert cell_text(cells, 9) == ""
    assert cell_href(cells, 2) == "https://acme.example"
    assert cell_href(cells, 1) is None
    assert cell_href(cells, None) is None
    assert row_instrument_code(rows[0]) == "9001"
    assert row_instrument_code(rows[1]) is None


def test_header_index_of_an_empty_table():
    assert header_index(extract_tables("<table></table>")[0]) == {}


def test_warn_missing_columns(caplog):
    cols = [{"symbol": 0, "close": None, "volume": None}, {"symbol": 0, "close": None, "volume": 3}]
    warn_missing_columns("trade-quotes", cols, ignore=("volume",))
    assert caplog.messages == ["trade-quotes: column(s) not found, values will be null: close"]
    caplog.clear()
    warn_missing_columns("trade-quotes", [{"symbol": 0}])
    assert caplog.messages == []
