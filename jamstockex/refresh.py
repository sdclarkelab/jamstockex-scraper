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


# --- one refresh run --------------------------------------------------------

BLOCKED_MESSAGE = (
    "The JSE site is blocking automated requests from this computer. Your stored data is still served; "
    "automatic refresh will try again after the next market close."
)


class _WarningCollector(logging.Handler):
    """Copies parser warnings (missing columns, skipped rows) into the report."""

    def __init__(self) -> None:
        super().__init__(logging.WARNING)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


@dataclass
class Report:
    trade_date: dt.date
    requests: int = 0
    datasets: dict[str, str] = field(default_factory=dict)  # dataset -> updated | stale | skipped
    errors: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    listings_reason: str | None = None
    stats: store.MergeStats = field(default_factory=store.MergeStats)
    counts: dict[str, int] = field(default_factory=dict)
    blocked: bool = False

    @property
    def attempted(self) -> bool:
        return any(outcome != "skipped" for outcome in self.datasets.values())

    @property
    def exit_code(self) -> int:
        return 1 if self.errors else 0

    def text(self) -> str:
        lines = [f"JSE refresh for trading day {self.trade_date.isoformat()}"]
        if not self.attempted:
            lines.append("Nothing is due: the stored data is up to date.")
            return "\n".join(lines)
        lines += [
            f"Requests to the JSE site: {self.requests}",
            "Datasets: " + ", ".join(f"{name} {outcome}" for name, outcome in sorted(self.datasets.items())),
            f"Listings refreshed: {self.listings_reason or 'no'}",
            f"Instruments: added {self.stats.companies_added}, updated {self.stats.companies_updated}, "
            f"delisted {self.stats.companies_delisted} ({self.counts.get('instruments', 0)} stored, "
            f"{self.counts.get('listed', 0)} listed)",
            f"Quotes in this refresh: {self.counts.get('quotes', 0)}",
            f"Corporate actions added: {self.stats.actions_added} ({self.counts.get('corporate_actions', 0)} stored)",
        ]
        if self.errors:
            lines += ["Errors:", *(f"  - {name}: {message}" for name, message in sorted(self.errors.items()))]
        if self.warnings:
            lines += ["Warnings:", *(f"  - {warning}" for warning in self.warnings)]
        if self.blocked:
            lines.append(BLOCKED_MESSAGE)
        return "\n".join(lines)


def _describe(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"


def _get(fetcher, path: str) -> str:
    """fetcher.get, with any unexpected exception turned into a FetchError naming only the path."""
    try:
        return fetcher.get(path)
    except FetchError:
        raise
    except Exception as exc:
        raise FetchError(f"{path}: {_describe(exc)}") from exc


def _parse(page: str, parse, *args):
    """Run a parser; an unexpected exception becomes a ParseError so the normal retry wait applies."""
    try:
        return parse(*args)
    except (FetchError, ParseError):
        raise
    except Exception as exc:
        raise ParseError(page, _describe(exc)) from exc


def run_refresh(state: store.State, fetcher, now: dt.datetime, settings: Config,
                force_listings: bool = False) -> Report:
    """Fetch, parse and merge whatever is due now. Mutates `state`; the caller saves it.

    `fetcher` is a fetch.Fetcher (or a test double with `get`, `request_count`, `blocked`).
    """
    collector = _WarningCollector()
    parse_log = logging.getLogger("jamstockex.parse")
    parse_log.addHandler(collector)
    try:
        report = _run(state, fetcher, now, settings, force_listings)
    finally:
        parse_log.removeHandler(collector)
    report.warnings = collector.messages + report.warnings
    return report


def _run(state: store.State, fetcher, now: dt.datetime, settings: Config, force_listings: bool) -> Report:
    plan = due(state, now, settings, force_listings=force_listings)
    for label in set(state.markets) - set(settings.markets.values()):
        del state.markets[label]  # market removed from config.toml
    result = store.ScrapeResult(trade_date=plan.trade_date)

    # 1. Quotes first, so an unknown instrument can trigger a listings refresh in the same run.
    if plan.quotes:
        try:
            html = _get(fetcher, QUOTES_PATH.format(market=settings.combined_market, date=plan.trade_date.isoformat()))
            result.quotes, result.indices = _parse("trade quotes", parse_trade_quotes, html, plan.trade_date)
        except (FetchError, ParseError) as exc:
            log.error("Trade quotes failed: %s", exc)
            result.errors["quotes"] = result.errors["indices"] = _describe(exc)

    # 2. Listings, only the markets that are due.
    codes, reason = listings_due(state, result.quotes, settings.markets, plan.today,
                                 settings.refresh.listings_every_days, force_listings)
    if codes:
        log.info("Refreshing listings for %d market(s): %s", len(codes), reason)
        result.listings = {}
        result.listings_full = len(codes) == len(settings.markets)
        for code in codes:
            label = settings.markets[code]
            try:
                html = _get(fetcher, LISTINGS_PATH.format(market=code))
                result.listings[label] = _parse(f"listings for {label}", parse_listed_companies, html, label)
            except (FetchError, ParseError) as exc:
                log.error("Listings for %s failed: %s", label, exc)
                result.listing_errors[label] = _describe(exc)
        if result.listing_errors:
            result.errors["listings"] = "; ".join(f"{label}: {e}" for label, e in result.listing_errors.items())

    # 3. Corporate actions: backfill until the first success, then from the last success minus the window.
    if plan.corporate_actions:
        from_date, thru_date = actions_window(state.status["corporate_actions"], plan.today, settings)
        try:
            html = _get(fetcher, ACTIONS_PATH.format(from_date=from_date.isoformat(), thru_date=thru_date.isoformat()))
            result.actions = _parse("corporate actions", parse_corporate_actions, html)
        except (FetchError, ParseError) as exc:
            log.error("Corporate actions failed: %s", exc)
            result.errors["corporate_actions"] = _describe(exc)

    attempted = {
        "listings": result.listings is not None,
        "quotes": result.quotes is not None or "quotes" in result.errors,
        "indices": result.indices is not None or "indices" in result.errors,
        "corporate_actions": result.actions is not None or "corporate_actions" in result.errors,
    }
    stats = store.MergeStats()
    warnings = store.merge(state, result, today=plan.today, now=now, settings=settings, stats=stats)

    blocked = bool(getattr(fetcher, "blocked", False))
    if blocked:
        state.blocked_close = plan.close
    elif result.errors:
        state.blocked_close = None
        state.last_failure_at = now
    elif any(attempted.values()):
        state.blocked_close = None
        state.last_failure_at = None

    return Report(
        trade_date=plan.trade_date,
        requests=fetcher.request_count,
        datasets={
            name: "stale" if name in result.errors else ("updated" if done else "skipped")
            for name, done in attempted.items()
        },
        errors=dict(result.errors),
        warnings=warnings,
        listings_reason=reason,
        stats=stats,
        counts={
            "instruments": len(state.companies),
            "listed": sum(1 for c in state.companies.values() if c.listed),
            "quotes": len(result.quotes or {}),
            "corporate_actions": len(state.actions),
        },
        blocked=blocked,
    )
