import pytest

from jamstockex.parse import ParseError, parse_listed_companies
from tests.helpers import fixture_html


def test_parses_companies_and_dedupes_duplicate_tables():
    companies = parse_listed_companies(fixture_html("listed-companies.html"), "Main Market")
    by_code = {c.instrument_code: c for c in companies}
    assert set(by_code) == {"9001", "9002"}

    acme = by_code["9001"]
    assert acme.symbol == "ACME"
    assert acme.name == "Acme Holdings Limited"  # original case kept
    assert acme.market == "Main Market"
    assert acme.currency == "JMD"
    assert acme.sector == "Manufacturing"
    assert acme.type == "Ordinary"
    assert acme.website == "https://www.acme.example"
    assert acme.listed is True and acme.quote is None

    assert by_code["9002"].website is None


def test_header_only_table_gives_empty_list():
    assert parse_listed_companies(fixture_html("listed-companies-empty.html"), "Bond Market") == []


def test_missing_table_raises_parse_error():
    with pytest.raises(ParseError, match="listed-companies"):
        parse_listed_companies("<html><body><p>Maintenance</p></body></html>", "Main Market")


def test_jse_links_are_never_used_as_website():
    html = fixture_html("listed-companies.html").replace(
        "https://www.acme.example", "https://www.jamstockex.com/somewhere"
    )
    companies = {c.instrument_code: c for c in parse_listed_companies(html, "Main Market")}
    assert companies["9001"].website is None


def test_skipped_rows_and_missing_columns_are_warned_once(caplog):
    html = fixture_html("listed-companies.html").replace("<th>Sector</th>", "<th>Industry Group</th>")
    parse_listed_companies(html, "Main Market")
    assert caplog.messages == [
        "listed-companies (Main Market): column(s) not found, values will be null: sector",
        "listed-companies (Main Market): skipped 1 row(s) without an instrument link or symbol",
    ]
