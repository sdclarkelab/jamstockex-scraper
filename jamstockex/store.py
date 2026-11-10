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
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
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
                with contextlib.suppress(FileNotFoundError):
                    os.unlink(self.path)
                continue
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump({"pid": os.getpid(), "time": self.clock()}, handle)
            self.held = True
            return
        raise LockHeld(f"{self.path}: another refresh is running")

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
