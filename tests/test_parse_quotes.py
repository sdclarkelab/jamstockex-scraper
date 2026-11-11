import datetime as dt
from decimal import Decimal

import pytest

from jamstockex.models import Index, Quote
from jamstockex.parse import ParseError, compute_change_pct, is_no_data_page, parse_trade_quotes
from tests.helpers import fixture_html

DAY = dt.date(2026, 11, 9)


def test_parses_quotes_across_tables_keyed_by_instrument_code():
    quotes, _ = parse_trade_quotes(fixture_html("trade-quotes.html"), DAY)
    assert set(quotes) == {"9001", "9002"}  # row without link skipped
    assert quotes["9001"] == Quote(date=DAY, close=Decimal("12.50"), change=Decimal("-0.25"),
                                       change_pct=Decimal("-1.96"), volume=48213)
    assert quotes["9002"] == Quote(date=DAY, close=Decimal("0.0850"), change=Decimal("0.0050"),
                                       change_pct=Decimal("6.25"), volume=1000)


def test_parses_indices():
    _, indices = parse_trade_quotes(fixture_html("trade-quotes.html"), DAY)
    assert indices == [
        Index(name="JSE Main Index", date=DAY, value=Decimal("325456.78"), change=Decimal("-1234.56"),
              change_pct=Decimal("-0.38"), volume=12345678),
        Index(name="JSE Junior Market Index", date=DAY, value=Decimal("3901.12"), change=Decimal("10.50"),
              change_pct=Decimal("0.27"), volume=2000000),
    ]


def test_inserted_and_reordered_columns_still_parse_and_page_pct_is_used(caplog):
    quotes, indices = parse_trade_quotes(fixture_html("trade-quotes-extra-column.html"), DAY)
    assert indices == []
    assert "trade-quotes: no indices table (with 'index' and 'value' columns) found" in caplog.messages
    assert quotes["9001"] == Quote(date=DAY, close=Decimal("12.50"), change=Decimal("-0.25"),
                                       change_pct=Decimal("-1.95"), volume=48213)


def test_no_data_page_is_a_day_without_trading(caplog):
    with caplog.at_level("INFO", logger="jamstockex.parse"):
        assert parse_trade_quotes(fixture_html("trade-quotes-holiday.html"), DAY) == ({}, [])
    assert caplog.messages == ["trade-quotes: the site reports no data for 2026-11-09 (no trading that day)"]


def test_page_without_tables_and_without_the_no_data_message_raises():
    html = fixture_html("trade-quotes-holiday.html").replace("Looks like there is no data coming back.",
                                                             "Something else went wrong.")
    with pytest.raises(ParseError, match="no quotes table"):
        parse_trade_quotes(html, DAY)
    with pytest.raises(ParseError, match="trade-quotes"):
        parse_trade_quotes("<html><body>Down for maintenance</body></html>", DAY)


def test_no_data_message_ignores_case_and_line_breaks():
    assert is_no_data_page("<p>LOOKS like there is\n   no data coming back.</p>")
    assert not is_no_data_page("<p>Looks like there is data coming back.</p>")


def test_renamed_price_header_raises_even_when_indices_parse():
    html = (fixture_html("trade-quotes.html")
            .replace("Closing <br />Price <br />($)", "Close ($)").replace("Last <br />Traded <br />Price <br />($)", "Last ($)"))
    with pytest.raises(ParseError, match="no quotes table"):
        parse_trade_quotes(html, DAY)


def test_renamed_optional_header_is_warned(caplog):
    html = fixture_html("trade-quotes.html").replace("<th>Closing<br />Ask ($)</th><th>Volume</th>",
                                                     "<th>Closing<br />Ask ($)</th><th>Shares</th>")
    quotes, _ = parse_trade_quotes(html, DAY)
    assert quotes["9001"].volume is None
    assert "trade-quotes: column(s) not found, values will be null: volume" in caplog.messages


def test_rows_without_a_link_or_symbol_are_skipped_and_counted_once(caplog):
    html = fixture_html("trade-quotes.html").replace('title="Beta Capital Limited">BETA</a>',
                                                     'title="Beta Capital Limited"></a>')
    quotes, _ = parse_trade_quotes(html, DAY)
    assert set(quotes) == {"9001"}  # BETA has a link but no symbol; ZZZ has a symbol but no link
    assert caplog.messages == ["trade-quotes: skipped 2 row(s) without an instrument link or symbol"]


@pytest.mark.parametrize("close, change, expected", [
    (Decimal("12.50"), Decimal("-0.25"), Decimal("-1.96")),
    (Decimal("10"), Decimal("0"), Decimal("0.00")),
    (Decimal("1"), Decimal("1"), None),  # previous price 0
    (None, Decimal("1"), None),
    (Decimal("1"), None, None),
])
def test_compute_change_pct(close, change, expected):
    assert compute_change_pct(close, change) == expected
