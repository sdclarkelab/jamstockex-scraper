import datetime as dt
from decimal import Decimal

import pytest

from jamstockex.models import CorporateAction
from jamstockex.parse import ParseError, parse_corporate_actions
from tests.helpers import fixture_html


def test_parses_dedupes_and_normalises(caplog):
    actions = parse_corporate_actions(fixture_html("corporate-actions.html"))
    assert actions == [
        CorporateAction(symbol="ACME", type="dividend", amount=Decimal("0.7500"), currency="JMD",
                        record_date=dt.date(2026, 11, 20), ex_date=dt.date(2026, 11, 18),
                        payment_date=dt.date(2026, 12, 4), instrument_code="9001"),
        CorporateAction(symbol="BETA", type="dividend", amount=Decimal("0.0100"), currency="USD",
                        record_date=dt.date(2026, 3, 2), ex_date=dt.date(2026, 2, 26),
                        payment_date=dt.date(2026, 3, 16), instrument_code="9002"),
        CorporateAction(symbol="ACME", type="stock_split", amount=None, currency=None,
                        record_date=dt.date(2026, 4, 14), ex_date=dt.date(2026, 4, 14),
                        payment_date=None, instrument_code="9001"),
    ]
    assert caplog.messages == []  # the mobile copy of the table adds nothing


def test_execution_date_header_is_an_ex_date_alias():
    html = fixture_html("corporate-actions.html").replace("<th>Ex-Date</th>", "<th>Execution Date</th>")
    assert parse_corporate_actions(html)[0].ex_date == dt.date(2026, 11, 18)


def test_missing_table_raises():
    with pytest.raises(ParseError, match="corporate-actions"):
        parse_corporate_actions("<html><body><table><tr><th>Foo</th></tr></table></body></html>")


def test_renamed_action_header_raises():
    html = fixture_html("corporate-actions.html").replace("<th>Action</th>", "<th>Kind</th>")
    with pytest.raises(ParseError, match="corporate-actions"):
        parse_corporate_actions(html)


def test_rows_without_an_action_type_are_skipped_and_counted(caplog):
    html = fixture_html("corporate-actions.html").replace("<td>Stock Split</td>", "<td></td>")
    actions = parse_corporate_actions(html)
    assert [a.type for a in actions] == ["dividend", "dividend"]
    assert caplog.messages == ["corporate-actions: skipped 1 row(s) without an instrument or action type"]
