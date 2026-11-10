"""Plain dataclasses for JSE data, with JSON (de)serialisation."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from typing import Any


def num(value: Decimal | None) -> int | float | None:
    """Decimal -> JSON number. Integral values become ints (12, not 12.0)."""
    if value is None:
        return None
    if value == value.to_integral_value():
        return int(value)
    return float(value)


def dec(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def isodate(value: dt.date | None) -> str | None:
    return None if value is None else value.isoformat()


def parse_iso(value: str | None) -> dt.date | None:
    return None if value is None else dt.date.fromisoformat(value)


@dataclass
class Quote:
    date: dt.date
    close: Decimal | None
    change: Decimal | None
    change_pct: Decimal | None
    volume: int | None

    def to_json(self) -> dict[str, Any]:
        return {
            "date": self.date.isoformat(),
            "close": num(self.close),
            "change": num(self.change),
            "change_pct": num(self.change_pct),
            "volume": self.volume,
        }

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> Quote:
        return cls(
            date=dt.date.fromisoformat(d["date"]),
            close=dec(d.get("close")),
            change=dec(d.get("change")),
            change_pct=dec(d.get("change_pct")),
            volume=d.get("volume"),
        )


@dataclass
class Company:
    instrument_code: str
    symbol: str
    name: str
    market: str
    currency: str | None = None
    sector: str | None = None
    type: str | None = None
    website: str | None = None
    listed: bool = True
    listed_since: dt.date | None = None
    delisted_on: dt.date | None = None
    quote: Quote | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "instrument_code": self.instrument_code,
            "symbol": self.symbol,
            "name": self.name,
            "market": self.market,
            "currency": self.currency,
            "sector": self.sector,
            "type": self.type,
            "website": self.website,
            "listed": self.listed,
            "listed_since": isodate(self.listed_since),
            "delisted_on": isodate(self.delisted_on),
            "quote": self.quote.to_json() if self.quote else None,
        }

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> Company:
        quote = d.get("quote")
        return cls(
            instrument_code=d["instrument_code"],
            symbol=d["symbol"],
            name=d["name"],
            market=d["market"],
            currency=d.get("currency"),
            sector=d.get("sector"),
            type=d.get("type"),
            website=d.get("website"),
            listed=bool(d.get("listed", True)),
            listed_since=parse_iso(d.get("listed_since")),
            delisted_on=parse_iso(d.get("delisted_on")),
            quote=Quote.from_json(quote) if quote else None,
        )


@dataclass
class Index:
    name: str
    date: dt.date
    value: Decimal | None
    change: Decimal | None
    change_pct: Decimal | None
    volume: int | None

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "date": self.date.isoformat(),
            "value": num(self.value),
            "change": num(self.change),
            "change_pct": num(self.change_pct),
            "volume": self.volume,
        }

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> Index:
        return cls(
            name=d["name"],
            date=dt.date.fromisoformat(d["date"]),
            value=dec(d.get("value")),
            change=dec(d.get("change")),
            change_pct=dec(d.get("change_pct")),
            volume=d.get("volume"),
        )


@dataclass(frozen=True)
class CorporateAction:
    symbol: str
    type: str
    amount: Decimal | None
    currency: str | None
    record_date: dt.date | None
    ex_date: dt.date | None
    payment_date: dt.date | None
    instrument_code: str | None = None

    def key(self) -> tuple:
        """Identity for de-duplication. Excludes instrument_code, which is derived."""
        return (self.symbol, self.type, self.record_date, self.ex_date, self.payment_date, self.amount, self.currency)

    def to_json(self) -> dict[str, Any]:
        return {
            "instrument_code": self.instrument_code,
            "symbol": self.symbol,
            "type": self.type,
            "amount": num(self.amount),
            "currency": self.currency,
            "record_date": isodate(self.record_date),
            "ex_date": isodate(self.ex_date),
            "payment_date": isodate(self.payment_date),
        }

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> CorporateAction:
        return cls(
            symbol=d["symbol"],
            type=d["type"],
            amount=dec(d.get("amount")),
            currency=d.get("currency"),
            record_date=parse_iso(d.get("record_date")),
            ex_date=parse_iso(d.get("ex_date")),
            payment_date=parse_iso(d.get("payment_date")),
            instrument_code=d.get("instrument_code"),
        )
