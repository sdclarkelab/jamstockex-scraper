import datetime as dt
from decimal import Decimal

from jamstockex.models import Company, CorporateAction, Index, Quote, dec, num

DAY = dt.date(2026, 11, 9)


def test_num_and_dec():
    assert num(None) is None
    assert num(Decimal("12.00")) == 12 and isinstance(num(Decimal("12.00")), int)
    assert num(Decimal("0.7500")) == 0.75
    assert dec(None) is None
    assert dec(0.75) == Decimal("0.75")
    assert dec(12) == Decimal("12")
    assert dec(Decimal("1.5")) == Decimal("1.5")


def test_quote_round_trip():
    quote = Quote(date=DAY, close=Decimal("12.50"), change=Decimal("-0.25"), change_pct=Decimal("-1.96"), volume=48213)
    data = quote.to_json()
    assert data == {"date": "2026-11-09", "close": 12.5, "change": -0.25, "change_pct": -1.96, "volume": 48213}
    assert Quote.from_json(data) == quote


def test_company_round_trip_with_quote_and_nulls():
    company = Company(
        instrument_code="9001", symbol="ACME", name="Acme Holdings Limited", market="Main Market",
        currency="JMD", sector=None, type="Ordinary", website=None, listed=True,
        listed_since=DAY, delisted_on=None,
        quote=Quote(date=DAY, close=None, change=None, change_pct=None, volume=None),
    )
    data = company.to_json()
    assert data["sector"] is None and data["website"] is None
    assert data["listed_since"] == "2026-11-09"
    assert data["quote"] == {"date": "2026-11-09", "close": None, "change": None, "change_pct": None, "volume": None}
    assert set(data) == {
        "instrument_code", "symbol", "name", "market", "currency", "sector", "type",
        "website", "listed", "listed_since", "delisted_on", "quote",
    }
    assert Company.from_json(data) == company


def test_company_without_quote():
    company = Company(instrument_code="9002", symbol="BETA", name="Beta", market="USD Market")
    assert company.to_json()["quote"] is None
    assert Company.from_json(company.to_json()) == company


def test_index_round_trip():
    index = Index(name="JSE Main Index", date=DAY, value=Decimal("325456.78"),
                  change=Decimal("-1234.56"), change_pct=Decimal("-0.38"), volume=12345678)
    assert Index.from_json(index.to_json()) == index


def test_corporate_action_round_trip_and_key_ignores_scale_and_code():
    action = CorporateAction(symbol="ACME", type="dividend", amount=Decimal("0.7500"), currency="JMD",
                             record_date=dt.date(2026, 11, 20), ex_date=dt.date(2026, 11, 18),
                             payment_date=dt.date(2026, 12, 4), instrument_code=None)
    data = action.to_json()
    assert data == {
        "instrument_code": None, "symbol": "ACME", "type": "dividend", "amount": 0.75, "currency": "JMD",
        "record_date": "2026-11-20", "ex_date": "2026-11-18", "payment_date": "2026-12-04",
    }
    loaded = CorporateAction.from_json({**data, "instrument_code": "9001"})
    assert loaded.amount == Decimal("0.75")
    assert loaded.key() == action.key()
