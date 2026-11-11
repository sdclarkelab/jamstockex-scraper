"""The local data file (jse-data.json): state, load, atomic save and the refresh lock.

- `load` returns an empty State when the file is missing. A corrupt file raises
  StoreError and is never overwritten.
- `save` writes a temp file in the same folder, fsyncs it, then os.replace()s it
  over the old file, so a crash leaves either the old or the new file intact.
- `RefreshLock` is an exclusive lock file (O_CREAT | O_EXCL) holding the PID and
  time; a lock older than 10 minutes is taken over.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import json
import logging
import os
import tempfile
import time
from dataclasses import dataclass, field, replace
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

from jamstockex.config import Config
from jamstockex.models import Company, CorporateAction, Index, Quote, isodate, parse_iso

log = logging.getLogger(__name__)

DATA_FILE = "jse-data.json"
LOCK_FILE = "jse-data.lock"
FORMAT_VERSION = 1
DATASETS = ("listings", "quotes", "indices", "corporate_actions")
LOCK_STALE_AFTER_S = 10 * 60


class StoreError(Exception):
    """The data file can't be read. It is left untouched."""


class LockHeld(Exception):
    """Another refresh holds the lock."""


def utc_timestamp(moment: dt.datetime) -> str:
    return moment.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_timestamp(text: str | None) -> dt.datetime | None:
    if text is None:
        return None
    return dt.datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(dt.timezone.utc)


def _timestamp_or_none(moment: dt.datetime | None) -> str | None:
    return utc_timestamp(moment) if moment else None


@dataclass
class DatasetStatus:
    as_of: dt.date | None = None
    fetched_at: dt.datetime | None = None
    stale: bool = False
    last_error: str | None = None
    # Quotes only: trading-day refreshes in a row that returned no quotes. Written only when > 0.
    no_data_days: int = 0

    def to_json(self) -> dict[str, Any]:
        doc = {
            "as_of": isodate(self.as_of),
            "fetched_at": _timestamp_or_none(self.fetched_at),
            "stale": self.stale,
            "last_error": self.last_error,
        }
        if self.no_data_days:
            doc["no_data_days"] = self.no_data_days
        return doc

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> DatasetStatus:
        return cls(
            as_of=parse_iso(d.get("as_of")),
            fetched_at=parse_timestamp(d.get("fetched_at")),
            stale=bool(d.get("stale", False)),
            last_error=d.get("last_error"),
            no_data_days=int(d.get("no_data_days", 0)),
        )


def _empty_status() -> dict[str, DatasetStatus]:
    return {name: DatasetStatus() for name in DATASETS}


@dataclass
class State:
    companies: dict[str, Company] = field(default_factory=dict)
    indices: list[Index] = field(default_factory=list)
    actions: list[CorporateAction] = field(default_factory=list)
    status: dict[str, DatasetStatus] = field(default_factory=_empty_status)
    # Per listings market, keyed by market label (the value of Company.market).
    markets: dict[str, DatasetStatus] = field(default_factory=dict)
    # Quote codes that a full listings refresh didn't explain. They don't trigger another refresh.
    unmatched: set[str] = field(default_factory=set)
    saved_at: dt.datetime | None = None
    # The market close at which the site last blocked us; no automatic attempt until a later close.
    blocked_close: dt.datetime | None = None
    # When the last refresh had a (non-block) failure; automatic retries wait after it.
    last_failure_at: dt.datetime | None = None


def action_sort_key(action: CorporateAction) -> tuple:
    return (action.record_date or dt.date.min, action.symbol, action.type,
            action.payment_date or dt.date.min, action.ex_date or dt.date.min)


def state_to_json(state: State) -> dict[str, Any]:
    return {
        "format": FORMAT_VERSION,
        "saved_at": _timestamp_or_none(state.saved_at),
        "companies": [c.to_json() for c in sorted(state.companies.values(), key=lambda c: c.instrument_code)],
        "indices": [i.to_json() for i in sorted(state.indices, key=lambda i: i.name)],
        "corporate_actions": [a.to_json() for a in sorted(state.actions, key=action_sort_key)],
        "status": {name: s.to_json() for name, s in state.status.items()},
        "markets": {label: m.to_json() for label, m in sorted(state.markets.items())},
        "unmatched_codes": sorted(state.unmatched),
        "blocked_close": _timestamp_or_none(state.blocked_close),
        "last_failure_at": _timestamp_or_none(state.last_failure_at),
    }


def state_from_json(doc: dict[str, Any]) -> State:
    if doc.get("format") != FORMAT_VERSION:
        raise ValueError(f"unsupported format {doc.get('format')!r} (expected {FORMAT_VERSION})")
    state = State(
        companies={d["instrument_code"]: Company.from_json(d) for d in doc["companies"]},
        indices=[Index.from_json(d) for d in doc["indices"]],
        actions=[CorporateAction.from_json(d) for d in doc["corporate_actions"]],
        markets={label: DatasetStatus.from_json(d) for label, d in doc["markets"].items()},
        unmatched=set(doc["unmatched_codes"]),
        saved_at=parse_timestamp(doc.get("saved_at")),
        blocked_close=parse_timestamp(doc.get("blocked_close")),
        last_failure_at=parse_timestamp(doc.get("last_failure_at")),
    )
    for name, data in doc["status"].items():
        if name in state.status:
            state.status[name] = DatasetStatus.from_json(data)
    return state


def load(path: str | Path) -> State:
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return State()
    except (OSError, UnicodeDecodeError) as exc:
        raise StoreError(f"{path}: can't read the data file ({type(exc).__name__}: {exc}); it was left untouched") from exc
    try:
        return state_from_json(json.loads(text, parse_float=Decimal))
    except (ValueError, KeyError, TypeError, AttributeError, ArithmeticError, RecursionError) as exc:
        raise StoreError(f"{path}: not a valid jamstockex data file ({type(exc).__name__}: {exc}); "
                         "it was left untouched") from exc


def save(state: State, path: str | Path, *, now: dt.datetime) -> None:
    """Write atomically: temp file in the same folder, fsync, then os.replace."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = state_to_json(replace(state, saved_at=now))
    text = json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        raise
    state.saved_at = now


class RefreshLock:
    """Exclusive lock file. Use as a context manager; raises LockHeld if another refresh holds it."""

    def __init__(self, path: str | Path, *, stale_after_s: float = LOCK_STALE_AFTER_S,
                 clock: Callable[[], float] = time.time) -> None:
        self.path = Path(path)
        self.stale_after_s = stale_after_s
        self.clock = clock
        self.held = False

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(2):
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            except FileExistsError:
                if not self._is_stale():
                    raise LockHeld(f"{self.path}: another refresh is running") from None
                log.warning("Taking over a stale lock: %s", self.path)
                self._take_over()
                continue
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump({"pid": os.getpid(), "time": self.clock()}, handle)
            except BaseException:
                with contextlib.suppress(OSError):
                    os.unlink(self.path)
                raise
            self.held = True
            return
        raise LockHeld(f"{self.path}: another refresh is running")

    def _take_over(self) -> None:
        # Accepted residual race: two processes that both judge the same >10-minute-old lock stale
        # at the same instant can both end up holding it. Fine for a single-user local app.
        try:
            os.unlink(self.path)
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise LockHeld(f"{self.path}: stale lock can't be removed ({exc})") from exc

    def _is_stale(self) -> bool:
        try:
            started = float(json.loads(self.path.read_text(encoding="utf-8"))["time"])
        except (OSError, ValueError, KeyError, TypeError):
            try:
                started = self.path.stat().st_mtime
            except FileNotFoundError:
                return True
        return self.clock() - started > self.stale_after_s

    def release(self) -> None:
        if self.held:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(self.path)
            self.held = False

    def __enter__(self) -> RefreshLock:
        self.acquire()
        return self

    def __exit__(self, *exc: object) -> None:
        self.release()


# --- merge ----------------------------------------------------------------


NO_DATA_STALE_DAYS = 3  # trading days in a row without quotes before quotes and indices are marked stale


@dataclass
class ScrapeResult:
    """What one refresh fetched. A field left as None (and absent from errors) was not attempted."""

    trade_date: dt.date
    listings: dict[str, list[Company]] | None = None  # market label -> companies, for pages that loaded
    listing_errors: dict[str, str] = field(default_factory=dict)  # market label -> error
    listings_full: bool = False  # every configured market was requested this run
    quotes: dict[str, Quote] | None = None
    indices: list[Index] | None = None
    actions: list[CorporateAction] | None = None
    errors: dict[str, str] = field(default_factory=dict)


@dataclass
class MergeStats:
    """What a merge changed, for the run summary."""

    companies_added: int = 0
    companies_updated: int = 0
    companies_delisted: int = 0
    actions_added: int = 0


def merge(
    state: State,
    result: ScrapeResult,
    *,
    today: dt.date,
    now: dt.datetime,
    settings: Config,
    stats: MergeStats | None = None,
) -> list[str]:
    """Fold a scrape into `state`. Returns warnings; fills `stats` (if given) with change counts."""
    warnings: list[str] = []
    errors = result.errors
    if stats is None:
        stats = MergeStats()

    if result.listings is not None or result.listing_errors:
        warnings += _merge_listings(state, result.listings or {}, result.listing_errors, today=today, now=now,
                                    max_drop_pct=settings.refresh.max_listing_drop_pct, stats=stats)
        if result.listings_full and result.quotes is not None:
            # Whatever a full refresh couldn't explain won't trigger another refresh tomorrow. Codes
            # already recorded stay until a listings refresh finds them (a holiday has no quotes).
            state.unmatched = (state.unmatched | set(result.quotes)) - set(state.companies)

    if result.quotes is not None or "quotes" in errors:
        if result.quotes is not None:
            warnings += _merge_quotes(state, result.quotes)
        _mark(state.status["quotes"], errors.get("quotes"), now, as_of=result.trade_date if result.quotes else None)

    if result.indices is not None or "indices" in errors:
        if result.indices:
            state.indices = list(result.indices)
        _mark(state.status["indices"], errors.get("indices"), now,
              as_of=result.trade_date if result.indices else None)

    if result.quotes is not None and "quotes" not in errors:
        warning = _count_no_data_days(state, quotes_found=bool(result.quotes))
        if warning:
            warnings.append(warning)

    if result.actions is not None or "corporate_actions" in errors:
        if result.actions is not None:
            stats.actions_added += _merge_actions(state, result.actions)
        _mark(state.status["corporate_actions"], errors.get("corporate_actions"), now, as_of=result.trade_date)

    state.unmatched -= set(state.companies)
    _assign_instrument_codes(state)
    for warning in warnings:
        log.warning(warning)
    return warnings


def _mark(status: DatasetStatus, error: str | None, now: dt.datetime, *, as_of: dt.date | None) -> None:
    if error:
        status.stale = True
        status.last_error = error
        return
    status.stale = False
    status.last_error = None
    status.fetched_at = now
    if as_of is not None:
        status.as_of = as_of


def _count_no_data_days(state: State, *, quotes_found: bool) -> str | None:
    """Safety net for the holiday rule: a "no data" page every trading day may be a site change.

    Counts successful quotes refreshes in a row that returned no quotes; any quote resets it.
    At NO_DATA_STALE_DAYS, quotes and indices are marked stale. That is not a failure: there is
    no failure wait, and the next close is fetched as usual.
    """
    status = state.status["quotes"]
    status.no_data_days = 0 if quotes_found else status.no_data_days + 1
    if status.no_data_days < NO_DATA_STALE_DAYS:
        return None
    message = (f"No trade data for {status.no_data_days} trading days in a row; "
               "the site may have changed")
    for name in ("quotes", "indices"):
        state.status[name].stale = True
        state.status[name].last_error = message
    return message


def _merge_listings(state: State, pages: dict[str, list[Company]], failed: dict[str, str], *,
                    today: dt.date, now: dt.datetime, max_drop_pct: int, stats: MergeStats) -> list[str]:
    warnings: list[str] = []
    seen = {c.instrument_code for companies in pages.values() for c in companies}
    listed_before = {
        label: {code for code, c in state.companies.items() if c.listed and c.market == label} for label in pages
    }
    for companies in pages.values():
        for new in companies:
            old = state.companies.get(new.instrument_code)
            if old is None:
                new.listed, new.listed_since, new.delisted_on = True, today, None
                state.companies[new.instrument_code] = new
                stats.companies_added += 1
                continue
            before = (old.symbol, old.name, old.market, old.currency, old.sector, old.type, old.website,
                      old.listed, old.delisted_on)
            old.symbol, old.name, old.market = new.symbol, new.name, new.market
            old.currency, old.sector, old.type, old.website = new.currency, new.sector, new.type, new.website
            old.listed, old.delisted_on = True, None
            after = (old.symbol, old.name, old.market, old.currency, old.sector, old.type, old.website,
                     old.listed, old.delisted_on)
            if after != before:
                stats.companies_updated += 1

    # Delist per market, and only for markets whose page loaded. Each market has its own guard,
    # so an empty or truncated page for a small market can't delist it wholesale.
    for label in sorted(pages):
        previous = listed_before[label]
        missing = previous - seen
        if missing:
            found = len({c.instrument_code for c in pages[label]})
            if found == 0 or found * 100 < (100 - max_drop_pct) * len(previous):  # integer-safe
                warnings.append(
                    f"Delisting held for {label}: {found} instrument(s) on the page vs {len(previous)} "
                    f"previously listed (max drop {max_drop_pct}%)"
                )
            else:
                for code in sorted(missing):
                    state.companies[code].listed = False
                    state.companies[code].delisted_on = today
                stats.companies_delisted += len(missing)
                log.info("Delisted %d %s instrument(s): %s", len(missing), label, ", ".join(sorted(missing)))
        _mark(state.markets.setdefault(label, DatasetStatus()), None, now, as_of=today)

    for label, error in failed.items():
        _mark(state.markets.setdefault(label, DatasetStatus()), error, now, as_of=None)

    # The listings dataset summarises its markets. as_of is the oldest successful refresh.
    summary = state.status["listings"]
    stale = sorted(label for label, m in state.markets.items() if m.stale)
    summary.stale = bool(stale)
    summary.last_error = "; ".join(f"{label}: {state.markets[label].last_error}" for label in stale) or None
    if pages:
        summary.fetched_at = now
    dates = [m.as_of for m in state.markets.values() if m.as_of]
    summary.as_of = min(dates) if dates else None
    return warnings


def _merge_quotes(state: State, quotes: dict[str, Quote]) -> list[str]:
    unknown = []
    for code, new_quote in quotes.items():
        company = state.companies.get(code)
        if company is None:
            unknown.append(code)
            continue
        company.quote = new_quote
    if unknown:
        return [f"Quotes skipped for {len(unknown)} unknown instrument(s): {', '.join(sorted(unknown))}"]
    return []


def _merge_actions(state: State, actions: list[CorporateAction]) -> int:
    """Union with the stored actions. Returns how many were new."""
    existing = {a.key() for a in state.actions}
    added = 0
    for new in actions:
        if new.key() not in existing:
            state.actions.append(new)
            existing.add(new.key())
            added += 1
    return added


def _assign_instrument_codes(state: State) -> None:
    by_symbol: dict[str, list[Company]] = {}
    for company in state.companies.values():
        by_symbol.setdefault(company.symbol.upper(), []).append(company)
    state.actions = [
        a if a.instrument_code else replace(a, instrument_code=_match_code(a, by_symbol))
        for a in state.actions
    ]


def _match_code(action: CorporateAction, by_symbol: dict[str, list[Company]]) -> str | None:
    candidates = by_symbol.get(action.symbol.upper(), [])
    if len(candidates) == 1:
        return candidates[0].instrument_code
    if action.currency:
        same_currency = [c for c in candidates if (c.currency or "").upper() == action.currency.upper()]
        if len(same_currency) == 1:
            return same_currency[0].instrument_code
    return None
