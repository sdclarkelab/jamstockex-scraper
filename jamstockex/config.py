"""Settings: built-in defaults, optionally overridden by <data_dir>/config.toml.

No config file is needed. A config.toml may override any subset of the keys in
DEFAULTS; a [markets] table replaces the default markets as a whole, so a
market can be removed. Unknown sections or keys are errors, so a typo can't be
silently ignored.
"""

from __future__ import annotations

import copy
import datetime as dt
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CONFIG_FILE = "config.toml"

# America/Jamaica has been UTC-05:00 all year since 1983 (no daylight saving time). A fixed
# offset gives the same answers as the tz database, which Windows doesn't ship and which the
# standard library can't provide there without the third-party `tzdata` package.
JAMAICA = dt.timezone(dt.timedelta(hours=-5), "America/Jamaica")

USER_AGENT = "jamstockex/2.0 (+https://github.com/sdclarkelab/jamstockex-scraper)"

DEFAULTS: dict[str, dict[str, Any]] = {
    "source": {
        "base_url": "https://www.jamstockex.com",
        "user_agent": USER_AGENT,
        "timeout_s": 20,
        "retries": 3,
        "delay_s": [2, 5],
    },
    "markets": {"31": "Main Market", "22": "Junior Market", "51": "Bond Market", "49": "USD Market"},
    "quotes": {"combined_market": 50},
    "refresh": {
        "close_time": "17:30",
        "check_every_minutes": 15,
        "retry_after_failure_minutes": 60,
        "listings_every_days": 7,
        "corporate_actions_window": 30,
        "corporate_actions_forward": 365,
        "backfill_from": dt.date(2026, 1, 1),
        "max_listing_drop_pct": 20,
    },
    "server": {"port": 8765},
}


class ConfigError(ValueError):
    """config.toml is malformed or has an invalid value. The message names the file and key."""


@dataclass(frozen=True)
class SourceConfig:
    base_url: str
    user_agent: str
    timeout_s: float
    retries: int
    delay_s: tuple[float, float]


@dataclass(frozen=True)
class RefreshConfig:
    close_time: dt.time
    check_every_minutes: int
    retry_after_failure_minutes: int
    listings_every_days: int
    corporate_actions_window: int
    corporate_actions_forward: int
    backfill_from: dt.date
    max_listing_drop_pct: int


@dataclass(frozen=True)
class Config:
    source: SourceConfig
    markets: dict[int, str]  # listed-companies market code -> label
    combined_market: int
    refresh: RefreshConfig
    port: int


def load_config(data_dir: str | Path) -> Config:
    """Defaults, overlaid with <data_dir>/config.toml when that file exists."""
    path = Path(data_dir) / CONFIG_FILE
    raw = copy.deepcopy(DEFAULTS)
    if path.exists():
        try:
            with path.open("rb") as handle:
                user = tomllib.load(handle)
        except tomllib.TOMLDecodeError as exc:
            raise ConfigError(f"{path}: invalid TOML: {exc}") from exc
        _overlay(raw, user, path)
    return _build(raw, path)


def default_config() -> Config:
    return _build(copy.deepcopy(DEFAULTS), Path("<built-in defaults>"))


def _overlay(raw: dict[str, dict[str, Any]], user: dict[str, Any], path: Path) -> None:
    for section, values in user.items():
        if section not in DEFAULTS:
            raise ConfigError(f"{path}: unknown section [{section}]")
        if not isinstance(values, dict):
            raise ConfigError(f"{path}: {section} must be a table ([{section}])")
        if section == "markets":
            raw["markets"] = dict(values)
            continue
        for key, value in values.items():
            if key not in DEFAULTS[section]:
                raise ConfigError(f"{path}: unknown key {section}.{key}")
            raw[section][key] = value


class _Reader:
    def __init__(self, raw: dict[str, dict[str, Any]], path: Path) -> None:
        self.raw = raw
        self.path = path

    def fail(self, key: str, problem: str) -> ConfigError:
        return ConfigError(f"{self.path}: {key}: {problem}")

    def int(self, section: str, key: str, minimum: int, maximum: int | None = None) -> int:
        value = self.raw[section][key]
        name = f"{section}.{key}"
        if isinstance(value, bool) or not isinstance(value, int):
            raise self.fail(name, f"must be an integer (got {value!r})")
        if value < minimum or (maximum is not None and value > maximum):
            limit = f">= {minimum}" if maximum is None else f"between {minimum} and {maximum}"
            raise self.fail(name, f"must be {limit} (got {value})")
        return value

    def number(self, section: str, key: str, value: Any = None) -> float:
        value = self.raw[section][key] if value is None else value
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise self.fail(f"{section}.{key}", f"must be a number (got {value!r})")
        return float(value)

    def text(self, section: str, key: str) -> str:
        value = self.raw[section][key]
        if not isinstance(value, str) or not value.strip():
            raise self.fail(f"{section}.{key}", f"must be a non-empty string (got {value!r})")
        return value.strip()


def _build(raw: dict[str, dict[str, Any]], path: Path) -> Config:
    read = _Reader(raw, path)

    base_url = read.text("source", "base_url").rstrip("/")
    if not base_url.startswith("https://"):
        raise read.fail("source.base_url", "must start with https://")
    delay = raw["source"]["delay_s"]
    if not isinstance(delay, list) or len(delay) != 2:
        raise read.fail("source.delay_s", f"must be [low, high] (got {delay!r})")
    low, high = (read.number("source", "delay_s", value) for value in delay)
    if not 0 <= low <= high:
        raise read.fail("source.delay_s", "must be [low, high] with 0 <= low <= high")
    timeout = read.number("source", "timeout_s")
    if timeout <= 0:
        raise read.fail("source.timeout_s", "must be > 0")
    source = SourceConfig(
        base_url=base_url,
        user_agent=read.text("source", "user_agent"),
        timeout_s=timeout,
        retries=read.int("source", "retries", 1, 10),
        delay_s=(low, high),
    )

    markets: dict[int, str] = {}
    for code, label in raw["markets"].items():
        if not str(code).isdigit():
            raise read.fail(f"markets.{code}", "market codes must be whole numbers")
        if not isinstance(label, str) or not label.strip():
            raise read.fail(f"markets.{code}", "the label must be a non-empty string")
        markets[int(code)] = label.strip()
    if not markets:
        raise read.fail("markets", "must list at least one market")
    if len(set(markets.values())) != len(markets):
        raise read.fail("markets", "labels must be unique")

    close_raw = raw["refresh"]["close_time"]
    if isinstance(close_raw, dt.time):
        close_time = close_raw.replace(second=0, microsecond=0)
    elif isinstance(close_raw, str) and re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", close_raw):
        close_time = dt.time.fromisoformat(close_raw)
    else:
        raise read.fail("refresh.close_time", f'must be "HH:MM" (got {close_raw!r})')

    backfill = raw["refresh"]["backfill_from"]
    if isinstance(backfill, str):
        try:
            backfill = dt.date.fromisoformat(backfill)
        except ValueError:
            raise read.fail("refresh.backfill_from", f"must be a date like 2026-01-01 (got {backfill!r})") from None
    if isinstance(backfill, dt.datetime) or not isinstance(backfill, dt.date):
        raise read.fail("refresh.backfill_from", f"must be a date like 2026-01-01 (got {backfill!r})")

    refresh = RefreshConfig(
        close_time=close_time,
        check_every_minutes=read.int("refresh", "check_every_minutes", 1),
        retry_after_failure_minutes=read.int("refresh", "retry_after_failure_minutes", 1),
        listings_every_days=read.int("refresh", "listings_every_days", 1),
        corporate_actions_window=read.int("refresh", "corporate_actions_window", 0),
        corporate_actions_forward=read.int("refresh", "corporate_actions_forward", 0),
        backfill_from=backfill,
        max_listing_drop_pct=read.int("refresh", "max_listing_drop_pct", 0, 100),
    )

    return Config(
        source=source,
        markets=markets,
        combined_market=read.int("quotes", "combined_market", 1),
        refresh=refresh,
        port=read.int("server", "port", 1, 65535),
    )
