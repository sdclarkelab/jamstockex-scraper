"""When a refresh is due, and one refresh run: fetch, parse, merge.

Times are compared in America/Jamaica (config.JAMAICA). `latest_close(now)` is
the most recent weekday market close at or before `now`; its date is the trade
date requested. Each dataset is fetched at most once per close: quotes (with
indices) when `quotes.fetched_at` is before the latest close, and corporate
actions likewise on their own `fetched_at`. A day without trading (the site's
"no data" page) is a successful fetch with zero rows; store.merge marks quotes
stale after 3 of them in a row.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass, field

from jamstockex import store
from jamstockex.config import JAMAICA, Config
from jamstockex.fetch import FetchError
from jamstockex.models import Quote
from jamstockex.parse import ParseError, parse_corporate_actions, parse_listed_companies, parse_trade_quotes

log = logging.getLogger(__name__)

QUOTES_PATH = "/trading/trade-quotes/?market={market}&date={date}"
LISTINGS_PATH = "/listings/listed-companies/?market={market}"
ACTIONS_PATH = "/trading/corporate-actions/?instrumentCode=all-stocks&fromDate={from_date}&thruDate={thru_date}"


def latest_close(now: dt.datetime, close_time: dt.time = dt.time(17, 30)) -> dt.datetime:
    """The most recent weekday D whose `D close_time` (Jamaica) is <= now."""
    local = now.astimezone(JAMAICA)
    day = local.date()
    if local.time() < close_time:
        day -= dt.timedelta(days=1)
    while day.weekday() >= 5:  # Saturday, Sunday
        day -= dt.timedelta(days=1)
    return dt.datetime.combine(day, close_time, tzinfo=JAMAICA)


def next_close_after(close: dt.datetime, close_time: dt.time = dt.time(17, 30)) -> dt.datetime:
    day = close.astimezone(JAMAICA).date() + dt.timedelta(days=1)
    while day.weekday() >= 5:
        day += dt.timedelta(days=1)
    return dt.datetime.combine(day, close_time, tzinfo=JAMAICA)


def listings_due(state: store.State, quotes: dict[str, Quote] | None, markets: dict[int, str],
                 today: dt.date, every_days: int, force: bool) -> tuple[list[int], str | None]:
    """Which listing markets to fetch, and why. ([], None) means none."""
    everything = list(markets)
    if force:
        return everything, "requested"
    if not state.companies:
        return everything, "no stored listings"
    # Codes a full refresh already failed to explain (state.unmatched) don't trigger another one.
    unknown = set(quotes or {}) - set(state.companies) - state.unmatched
    if unknown:
        return everything, f"{len(unknown)} unknown instrument(s) in quotes"

    def status(label: str) -> store.DatasetStatus:
        return state.markets.get(label, store.DatasetStatus())

    retry = [code for code, label in markets.items() if status(label).stale]
    aged = [
        code for code, label in markets.items()
        if code not in retry and (status(label).as_of is None or (today - status(label).as_of).days >= every_days)
    ]
    reasons = []
    if aged:
        oldest = min((status(markets[c]).as_of for c in aged if status(markets[c]).as_of), default=None)
        reasons.append(f"last refresh {oldest.isoformat() if oldest else 'never'}")
    if retry:
        reasons.append("retrying failed market(s): " + ", ".join(markets[c] for c in retry))
    due_codes = [code for code in markets if code in retry or code in aged]
    return due_codes, "; ".join(reasons) or None


def actions_window(status: store.DatasetStatus, today: dt.date, settings: Config) -> tuple[dt.date, dt.date]:
    """Corporate-actions query range.

    Backfill from `backfill_from` until the first success. After that, look back
    `corporate_actions_window` days from the last success, so an outage of any length is
    caught up on the next good run. Always reaches `corporate_actions_forward` days ahead.
    """
    backfill = settings.refresh.backfill_from
    thru = today + dt.timedelta(days=settings.refresh.corporate_actions_forward)
    if status.as_of is None:
        return backfill, thru
    return max(backfill, status.as_of - dt.timedelta(days=settings.refresh.corporate_actions_window)), thru


@dataclass(frozen=True)
class Due:
    close: dt.datetime                  # latest_close(now)
    today: dt.date                      # today in Jamaica
    quotes: bool                        # quotes and indices
    corporate_actions: bool
    listings: tuple[int, ...]           # market codes due before this run's quotes are known
    listings_reason: str | None
    not_before: dt.datetime | None      # automatic attempts wait until then (failure wait, block)

    @property
    def trade_date(self) -> dt.date:
        return self.close.date()

    @property
    def anything(self) -> bool:
        return self.quotes or self.corporate_actions or bool(self.listings)

    def automatic_allowed(self, now: dt.datetime) -> bool:
        return self.anything and (self.not_before is None or now >= self.not_before)


def due(state: store.State, now: dt.datetime, settings: Config, *, force_listings: bool = False) -> Due:
    close_time = settings.refresh.close_time
    close = latest_close(now, close_time)
    today = now.astimezone(JAMAICA).date()

    def before_close(name: str) -> bool:
        fetched = state.status[name].fetched_at
        return fetched is None or fetched < close

    codes, reason = listings_due(state, None, settings.markets, today, settings.refresh.listings_every_days,
                                 force_listings)
    waits = []
    if state.blocked_close is not None and close <= state.blocked_close:
        waits.append(next_close_after(state.blocked_close, close_time))
    if state.last_failure_at is not None:
        retry_at = state.last_failure_at + dt.timedelta(minutes=settings.refresh.retry_after_failure_minutes)
        if now < retry_at:
            waits.append(retry_at)
    return Due(
        close=close,
        today=today,
        quotes=before_close("quotes"),
        corporate_actions=before_close("corporate_actions"),
        listings=tuple(codes),
        listings_reason=reason,
        not_before=max(waits) if waits else None,
    )
