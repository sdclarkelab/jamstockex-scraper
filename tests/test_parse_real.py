"""Checks against real JSE pages saved by the user in tests/fixtures/real/ (gitignored, never committed).

Every test skips when its page is absent, so CI and fresh clones skip them all.
The file names are the ones Task 1 of the implementation plan asks the user to save.
"""

import datetime as dt
import logging
import re

import pytest

from jamstockex.config import default_config
from jamstockex.fetch import is_block_page
from jamstockex.html import extract_tables
from jamstockex.parse import (
    ACTION_COLUMNS, INDEX_COLUMNS, LISTING_COLUMNS, QUOTE_COLUMNS, is_no_data_page, matching_tables,
    parse_corporate_actions, parse_listed_companies, parse_trade_quotes,
)
from tests.helpers import FIXTURES

REAL = FIXTURES / "real"
MARKETS = default_config().markets  # market code -> label
TRADING_DAY = "trade-quotes-trading-day.html"  # saved for 2026-11-10
HOLIDAY = "trade-quotes-holiday.html"  # requested for 2026-10-19 (National Heroes Day)
ACTIONS = "corporate-actions.html"
PAGES = [f"listed-companies-{code}.html" for code in MARKETS] + [TRADING_DAY, HOLIDAY, ACTIONS]
PAGINATION = re.compile(r"[?&](page|paged|offset|start)=\d|class=\"[^\"]*pagination|rel=\"next\"", re.IGNORECASE)
NOT_FOUND = "column(s) not found"
SELECTED_MARKET = re.compile(r'id="selectedMarket"[^>]*>\s*([^<]*?)\s*<')


def real(name: str) -> str:
    path = REAL / name
    if not path.exists():
        pytest.skip(f"real page {name} not saved in tests/fixtures/real/")
    return path.read_text(encoding="utf-8", errors="replace")


@pytest.mark.parametrize("name", PAGES)
def test_real_page_is_not_a_block_page_and_not_paginated(name):
    html = real(name)
    assert not is_block_page(html), f"{name} is a CloudFront block page; save it again from a browser"
    assert not PAGINATION.search(html), f"{name} looks paginated: STOP and tell the user"


@pytest.mark.parametrize("code, label", MARKETS.items())
def test_real_listed_companies(code, label, caplog):
    with caplog.at_level(logging.WARNING, logger="jamstockex.parse"):
        companies = parse_listed_companies(real(f"listed-companies-{code}.html"), label)
    assert companies, f"{label}: no companies parsed"
    assert all(c.instrument_code and c.symbol and c.name for c in companies)
    assert not [m for m in caplog.messages if NOT_FOUND in m], caplog.messages


@pytest.mark.parametrize("code, label", MARKETS.items())
def test_real_market_label_appears_on_its_page(code, label):
    """Catches a market code that points at a differently named market.

    Every listings page names all markets in its dropdown, so the selected market is checked when
    the page marks it.
    """
    page = real(f"listed-companies-{code}.html")
    assert label.lower() in page.lower(), f"market {code}: the page never mentions {label!r}"
    selected = SELECTED_MARKET.findall(page)
    if selected:
        assert [s.lower() for s in selected] == [label.lower()], f"market {code}: the page selects {selected}"


def test_real_trade_quotes(caplog):
    with caplog.at_level(logging.WARNING, logger="jamstockex.parse"):
        quotes, indices = parse_trade_quotes(real(TRADING_DAY), dt.date(2026, 11, 10))
    assert quotes, "no quotes parsed from the trading-day page"
    assert indices, "no indices parsed from the trading-day page"
    assert sum(q.close is not None for q in quotes.values()) >= 0.9 * len(quotes)
    assert not [m for m in caplog.messages if NOT_FOUND in m], caplog.messages


def test_real_holiday_page_is_a_day_without_trading():
    """The site answers a date without trading with no tables and its "no data" message. A ParseError
    here means that message changed; quotes would mean it sent another session's data (STOP)."""
    html = real(HOLIDAY)
    assert is_no_data_page(html), "the holiday page no longer has the site's 'no data' message"
    assert not matching_tables(extract_tables(html), QUOTE_COLUMNS, ("symbol", "close"))
    assert parse_trade_quotes(html, dt.date(2026, 10, 19)) == ({}, [])


def test_real_trading_day_page_has_no_no_data_message():
    assert not is_no_data_page(real(TRADING_DAY))


def test_real_corporate_actions(caplog):
    with caplog.at_level(logging.WARNING, logger="jamstockex.parse"):
        actions = parse_corporate_actions(real(ACTIONS))
    assert actions, "no corporate actions parsed"
    assert all(re.fullmatch(r"[a-z0-9_]+", a.type) for a in actions)
    dividends = [a for a in actions if a.type == "dividend"]
    assert dividends, f"no dividends; types seen: {sorted({a.type for a in actions})}"
    assert sum(a.amount is not None for a in dividends) >= 0.9 * len(dividends)
    assert not [m for m in caplog.messages if NOT_FOUND in m], caplog.messages


@pytest.mark.parametrize("name, aliases, required", [
    *[(f"listed-companies-{code}.html", LISTING_COLUMNS, ("name", "symbol")) for code in MARKETS],
    (TRADING_DAY, QUOTE_COLUMNS, ("symbol", "close")),
    (TRADING_DAY, INDEX_COLUMNS, ("name", "value")),
    (ACTIONS, ACTION_COLUMNS, ("symbol", "type", "amount")),
])
def test_real_every_alias_table_matches(name, aliases, required):
    """Lists the fields whose header matched no alias, so the fix is obvious."""
    matches = matching_tables(extract_tables(real(name)), aliases, required)
    assert matches, f"{name}: no table has the required columns {required}"
    unresolved = {f for _, cols in matches for f, idx in cols.items() if idx is None}
    if aliases is QUOTE_COLUMNS:
        unresolved.discard("change_pct")  # computed when the page has no % column
    assert unresolved == set(), f"{name}: add the real header names to the aliases for {sorted(unresolved)}"


def test_real_quote_and_action_codes_match_listing_codes():
    """instrument_code must have one format on every page (a numeric ID), or quotes and
    actions never reach their company."""
    listed = {
        c.instrument_code
        for code, label in MARKETS.items()
        for c in parse_listed_companies(real(f"listed-companies-{code}.html"), label)
    }
    quotes, _ = parse_trade_quotes(real(TRADING_DAY), dt.date(2026, 11, 10))
    actions = {a.instrument_code for a in parse_corporate_actions(real(ACTIONS))}
    assert None not in actions, "a corporate-actions row has no ?instrument= link"
    assert all(code.isdigit() for code in listed | set(quotes) | actions), "instrument_code is no longer numeric"
    for name, codes in (("quote", set(quotes)), ("corporate-action", actions)):
        unknown = sorted(codes - listed)
        assert len(unknown) <= len(codes) // 10, f"{name} codes missing from every listings page: {unknown[:20]}"
