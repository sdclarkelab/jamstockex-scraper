# v2 Static JSON API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the MongoDB scraper with a minimal, configurable Python 3.12 package. Once per trading day, from GitHub Actions, it scrapes jamstockex.com and publishes a free static JSON API (`/v2/`) on GitHub Pages. It also relicenses the code under PolyForm Noncommercial 1.0.0.

**Architecture:**
- **Scraping:** a `python -m jamstockex build --out site` command fetches only the datasets that are due (typically 2 requests a day). It parses tables by header name, merges the results into the previously published JSON (read back from the `data` branch, which acts as the store), and writes the v2 file tree.
- **Publishing:** a GitHub Actions cron job runs the build and commits `site/` to the `data` branch, which GitHub Pages serves.

**Tech Stack:** Python 3.12 (stdlib `tomllib`, `zoneinfo`, `dataclasses`, `decimal`), `requests`, `beautifulsoup4` (`html.parser`), `pytest`, GitHub Actions, GitHub Pages.

**Spec:** `docs/superpowers/specs/2026-11-09-v2-static-api-design.md`

## Global Constraints

**Runtime and dependencies**
- Python **3.12**. Runtime dependencies are only `requests==2.32.3` and `beautifulsoup4==4.12.3`; the only dev dependency is `pytest==8.3.3`. No lxml, no jsonschema, no extra mocking libraries.

**Behaviour towards the JSE site**
- **One honest User-Agent:** `jamstockex-scraper/2.0 (+https://github.com/sdclarkelab/jamstockex-scraper)`. **Never rotate User-Agents, and never retry or work around a block (403/429/CloudFront page).**
- **No URL containing `jamstockex.com`** in any API output file or in README/TERMS/NOTICE. Name the source in plain text only (JSE T&C §8.5.3).
- **Real JSE HTML pages are never committed.** They live in the gitignored `tests/fixtures/real/`. Committed fixtures are synthetic, with fake companies.

**API output**
- API version path `v2`, release tag `v2.0.0`. The existing `v1.0` tag is untouched.
- JSON: minified (`separators=(",", ":")`), `sort_keys=True`, UTF-8, `snake_case` keys, ISO dates `YYYY-MM-DD`, UTC timestamps `YYYY-MM-DDTHH:MM:SSZ`, missing values `null` (never `0`), original letter case kept in values.

**Tests**
- Fully offline. No test may make a network request.

**Process**
- **Outward-facing actions need explicit user approval at the time:** `git push`, opening PRs, merging, enabling Pages, and pushing tags.
- Every commit message ends with a blank line, then `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Work on branch `feat/v2-static-api`, which already exists and contains the spec.

**Deviations from the spec, decided while planning:**
1. Orchestration lives in `jamstockex/build.py`; `__main__.py` is a thin CLI.
2. `parse_trade_quotes` returns `dict[str, Quote]` keyed by `instrument_code`, plus `list[Index]`.
3. Committed fixtures are synthetic and real pages are gitignored, so JSE content isn't republished.
4. Decimals are emitted as JSON numbers via `float`/`int`. This is exact for values with 15 or fewer significant digits, which covers all JSE prices.

---

## File map

| File | Responsibility |
|---|---|
| `config.toml` | All tunables (spec §4) |
| `jamstockex/config.py` | Load and validate `config.toml` into frozen dataclasses |
| `jamstockex/models.py` | `Quote`, `Company`, `Index`, `CorporateAction` dataclasses plus JSON (de)serialisation |
| `jamstockex/fetch.py` | Polite HTTP client: `Fetcher`, `FetchError`, `BlockedError` |
| `jamstockex/parse.py` | Header-matched table helpers, value parsers, the 3 page parsers, `ParseError` |
| `jamstockex/store.py` | `State`/`DatasetStatus`/`ScrapeResult`, `load`, `merge`, `write` |
| `jamstockex/build.py` | `run()`: decide what's due, fetch, parse, merge, write; `Report` |
| `jamstockex/__main__.py` | CLI `python -m jamstockex build` |
| `tests/helpers.py` | Fixture loading, envelope assertion, JSE-URL regex |
| `tests/fixtures/*.html` | Synthetic pages |
| `.github/workflows/scrape.yml`, `ci.yml` | Daily scrape and publish; offline tests |
| `LICENSE`, `NOTICE`, `TERMS.md`, `README.md`, `CLAUDE.md` | Legal and docs |

---

### Task 1: Gate — confirm GitHub Actions can reach jamstockex.com

**Why:** the JSE site returns CloudFront `403 Request blocked` to automated requests from the dev machine. If GitHub's runners are blocked too, this hosting plan is dead. **Stop and report to the user**; never work around it.

**Files:**
- Create (on a throwaway branch only): `.github/workflows/probe-jse.yml`

**Interfaces:** none.

- [ ] **Step 1: Create the throwaway branch**

```bash
git switch feat/v2-static-api
git switch -c probe/jse-reachability
mkdir -p .github/workflows
```

- [ ] **Step 2: Write the probe workflow**

`.github/workflows/probe-jse.yml`:

```yaml
name: probe-jse
on:
  push:
    branches: [probe/jse-reachability]
jobs:
  probe:
    runs-on: ubuntu-latest
    steps:
      - name: One request to each JSE page type (3 requests, 5 s apart)
        run: |
          ua='jamstockex-scraper/2.0 (+https://github.com/sdclarkelab/jamstockex-scraper)'
          base='https://www.jamstockex.com'
          today=$(TZ=America/Jamaica date +%F)
          next_year=$(TZ=America/Jamaica date -d '+365 days' +%F)
          failed=0
          for path in \
            "/listings/listed-companies/?market=31" \
            "/trading/trade-quotes/?market=50&date=$(TZ=America/Jamaica date -d 'last friday' +%F)" \
            "/trading/corporate-actions/?instrumentCode=all-stocks&fromDate=${today:0:4}-01-01&thruDate=$next_year"
          do
            code=$(curl -s -o body.html -w '%{http_code}' -A "$ua" "$base$path")
            echo "$path -> HTTP status: $code; tables in raw HTML: $(grep -o '<table' body.html | wc -l)"
            if grep -q 'Request blocked' body.html; then echo "::error::BLOCKED by CloudFront"; exit 1; fi
            if [ "$code" != "200" ]; then failed=1; fi
            sleep 5
          done
          exit $failed
```

- [ ] **Step 3: Commit, then ask the user for approval to push**

```bash
git add .github/workflows/probe-jse.yml
git commit -m "ci: temporary JSE reachability probe" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Ask the user: "OK to push the throwaway branch `probe/jse-reachability`? It sends 3 requests to jamstockex.com from GitHub Actions, one per page type, 5 s apart." Push only after a yes:

```bash
git push -u origin probe/jse-reachability
gh run list --branch probe/jse-reachability --limit 1 --json databaseId,status   # repeat until a run appears
RUN_ID=$(gh run list --branch probe/jse-reachability --limit 1 --json databaseId -q '.[0].databaseId')
gh run watch "$RUN_ID" --exit-status
gh run view --log "$RUN_ID" | grep -E 'HTTP status|Tables in raw HTML|BLOCKED'
```

Expected: three lines (listed companies, trade quotes, corporate actions with a `thruDate` a year ahead), each with `HTTP status: 200` and `tables in raw HTML: ` followed by a number ≥ 1.

- [ ] **Step 4: Decide**

- **All three 200 with tables ≥ 1:** proceed.
- **Blocked (403, 429 or "BLOCKED"):** STOP. Report to the user and do not continue the plan.
- **200 with 0 tables:** the tables are rendered by JavaScript, so `requests` can't see them. STOP and report.
- **Corporate actions not 200, or 0 tables, while the others are fine:** the site may reject a future `thruDate`. STOP and report; `corporate_actions_forward` may need to become 0.

- [ ] **Step 5: Clean up (ask before deleting the remote branch)**

```bash
git switch feat/v2-static-api
git branch -D probe/jse-reachability
git push origin --delete probe/jse-reachability   # after user approval
```

---

### Task 2: Scaffold the package and config

**Files:**
- Create: `config.toml`, `jamstockex/__init__.py`, `jamstockex/config.py`, `requirements-dev.txt`, `pytest.ini`, `tests/__init__.py`, `tests/helpers.py`, `tests/test_config.py`
- Modify: `requirements.txt` (replace contents), `.gitignore` (append)
- Delete: `__init__.py` (repo root, empty)

**Interfaces:**
- Produces:
  - `load_config(path: str | Path = "config.toml") -> Config`
  - `ConfigError(ValueError)`
  - dataclasses `Config(source: SourceConfig, markets: dict[int, str], combined_market: int, refresh: RefreshConfig, output: OutputConfig)`
  - `SourceConfig(base_url: str, user_agent: str, timeout_s: float, retries: int, delay_s: tuple[float, float])`
  - `RefreshConfig(listings_every_days: int, corporate_actions_window: int, corporate_actions_forward: int, backfill_from: date, max_listing_drop_pct: float)`
  - `OutputConfig(api_version: str, timezone: str)`
  - `tests/helpers.py`: `ROOT`, `FIXTURES`, `JSE_URL`, `fixture_html(name)`, `read_json(path)`, `assert_envelope(doc, api_version="v2")`

- [ ] **Step 1: Recreate the virtualenv on Python 3.12 and set up dependencies**

The existing `.venv` is Python 3.8 with v1 dependencies; `--clear` replaces it. The empty repo-root `__init__.py` is also removed now: while it exists, pytest treats the repo itself as a package and resolves test modules under the wrong name.

```bash
/opt/homebrew/bin/python3.12 -m venv --clear .venv
git rm -q __init__.py
```

`requirements.txt` (replace the entire file):

```text
requests==2.32.3
beautifulsoup4==4.12.3
```

`requirements-dev.txt`:

```text
-r requirements.txt
pytest==8.3.3
```

```bash
.venv/bin/pip install -r requirements-dev.txt
```

`pytest.ini`:

```ini
[pytest]
pythonpath = .
testpaths = tests
```

Append to `.gitignore`, skipping any line that's already present:

```text
.venv/
site/
tests/fixtures/real/
```

- [ ] **Step 2: Create the test helpers and package marker files**

`jamstockex/__init__.py`:

```python
"""Scrape Jamaica Stock Exchange end-of-day data into a static JSON API."""

__version__ = "2.0.0"
```

`tests/__init__.py`: empty file.

`tests/helpers.py`:

```python
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"
JSE_URL = re.compile(r"https?://[^\s\"']*jamstockex\.com", re.IGNORECASE)


def fixture_html(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def read_json(path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def assert_envelope(doc: dict, api_version: str = "v2") -> None:
    assert set(doc) == {"meta", "data"}
    meta = doc["meta"]
    assert set(meta) == {"api_version", "as_of", "generated_at", "stale", "source", "terms", "license"}
    assert meta["api_version"] == api_version
    assert isinstance(meta["stale"], bool)
    assert "Jamaica Stock Exchange" in meta["source"]
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", meta["generated_at"])
    assert meta["as_of"] is None or re.fullmatch(r"\d{4}-\d\d-\d\d", meta["as_of"])
```

- [ ] **Step 3: Write the failing config tests**

`tests/test_config.py`:

```python
from datetime import date

import pytest

from jamstockex.config import ConfigError, load_config
from tests.helpers import ROOT

VALID = """
[source]
base_url = "https://www.example.test/"
user_agent = "agent/1.0"
timeout_s = 20
retries = 3
delay_s = [2, 5]

[markets]
31 = "Main Market"
22 = "Junior Market"

[quotes]
combined_market = 50

[refresh]
listings_every_days = 7
corporate_actions_window = 30
corporate_actions_forward = 365
backfill_from = 2026-01-01
max_listing_drop_pct = 20

[output]
api_version = "v2"
timezone = "America/Jamaica"
"""


def write(tmp_path, text):
    path = tmp_path / "config.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_loads_valid_config(tmp_path):
    config = load_config(write(tmp_path, VALID))
    assert config.source.base_url == "https://www.example.test"
    assert config.source.user_agent == "agent/1.0"
    assert config.source.timeout_s == 20.0
    assert config.source.retries == 3
    assert config.source.delay_s == (2.0, 5.0)
    assert config.markets == {31: "Main Market", 22: "Junior Market"}
    assert config.combined_market == 50
    assert config.refresh.listings_every_days == 7
    assert config.refresh.corporate_actions_window == 30
    assert config.refresh.corporate_actions_forward == 365
    assert config.refresh.backfill_from == date(2026, 1, 1)
    assert config.refresh.max_listing_drop_pct == 20.0
    assert config.output.api_version == "v2"
    assert config.output.timezone == "America/Jamaica"


def test_backfill_from_accepts_a_string(tmp_path):
    text = VALID.replace("backfill_from = 2026-01-01", 'backfill_from = "2026-01-01"')
    assert load_config(write(tmp_path, text)).refresh.backfill_from == date(2026, 1, 1)


def test_repo_config_loads():
    config = load_config(ROOT / "config.toml")
    assert config.output.api_version == "v2"
    assert set(config.markets) == {31, 22, 51, 49}
    assert config.combined_market == 50
    assert config.source.user_agent.startswith("jamstockex-scraper/2.0 ")


@pytest.mark.parametrize(
    "old, new",
    [
        ("retries = 3", "retries = 0"),
        ("delay_s = [2, 5]", "delay_s = [5, 2]"),
        ("timeout_s = 20", "timeout_s = 0"),
        ('timezone = "America/Jamaica"', 'timezone = "Mars/Olympus"'),
        ('base_url = "https://www.example.test/"', 'base_url = "http://www.example.test/"'),
        ("max_listing_drop_pct = 20", "max_listing_drop_pct = 120"),
        ("listings_every_days = 7", "listings_every_days = 0"),
        ("combined_market = 50", ""),
    ],
)
def test_invalid_config_raises(tmp_path, old, new):
    with pytest.raises(ConfigError):
        load_config(write(tmp_path, VALID.replace(old, new)))


def test_missing_file_raises(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "nope.toml")


def test_bad_toml_raises(tmp_path):
    with pytest.raises(ConfigError, match="Invalid TOML"):
        load_config(write(tmp_path, "[source\n"))
```

- [ ] **Step 4: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_config.py -q`
Expected: collection error `ModuleNotFoundError: No module named 'jamstockex.config'`.

- [ ] **Step 5: Write `config.toml` and `jamstockex/config.py`**

`config.toml`:

```toml
# jamstockex-scraper configuration. The cron schedule lives in .github/workflows/scrape.yml.

[source]
base_url   = "https://www.jamstockex.com"
user_agent = "jamstockex-scraper/2.0 (+https://github.com/sdclarkelab/jamstockex-scraper)"
timeout_s  = 20
retries    = 3          # attempts per request (blocks are never retried)
delay_s    = [2, 5]     # random pause between requests, seconds

[markets]               # listed-companies market code = label
31 = "Main Market"
22 = "Junior Market"
51 = "Bond Market"
49 = "USD Market"

[quotes]
combined_market = 50    # trade-quotes page covering every instrument

[refresh]
listings_every_days       = 7     # also refreshed immediately when quotes show an unknown instrument
corporate_actions_window  = 30    # days back on normal runs
corporate_actions_forward = 365   # days ahead, for announced actions
backfill_from             = 2026-01-01   # first run only
max_listing_drop_pct      = 20    # hold delistings if the listed count drops more than this

[output]
api_version = "v2"
timezone    = "America/Jamaica"
```

`jamstockex/config.py`:

```python
"""Load and validate config.toml."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class ConfigError(ValueError):
    """config.toml is missing, malformed, or has an invalid value."""


@dataclass(frozen=True)
class SourceConfig:
    base_url: str
    user_agent: str
    timeout_s: float
    retries: int
    delay_s: tuple[float, float]


@dataclass(frozen=True)
class RefreshConfig:
    listings_every_days: int
    corporate_actions_window: int
    corporate_actions_forward: int
    backfill_from: date
    max_listing_drop_pct: float


@dataclass(frozen=True)
class OutputConfig:
    api_version: str
    timezone: str


@dataclass(frozen=True)
class Config:
    source: SourceConfig
    markets: dict[int, str]
    combined_market: int
    refresh: RefreshConfig
    output: OutputConfig


def load_config(path: str | Path = "config.toml") -> Config:
    path = Path(path)
    try:
        with path.open("rb") as handle:
            raw = tomllib.load(handle)
    except FileNotFoundError as exc:
        raise ConfigError(f"Config file not found: {path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"Invalid TOML in {path}: {exc}") from exc
    try:
        return _build(raw)
    except (KeyError, TypeError, ValueError) as exc:
        raise ConfigError(f"Invalid config in {path}: {exc!r}") from exc


def _build(raw: dict) -> Config:
    src = raw["source"]
    low, high = (float(value) for value in src["delay_s"])
    source = SourceConfig(
        base_url=str(src["base_url"]).rstrip("/"),
        user_agent=str(src["user_agent"]),
        timeout_s=float(src["timeout_s"]),
        retries=int(src["retries"]),
        delay_s=(low, high),
    )
    _check(source.base_url.startswith("https://"), "source.base_url must start with https://")
    _check(source.user_agent.strip() != "", "source.user_agent must not be empty")
    _check(source.timeout_s > 0, "source.timeout_s must be > 0")
    _check(source.retries >= 1, "source.retries must be >= 1")
    _check(0 <= low <= high, "source.delay_s must be [low, high] with 0 <= low <= high")

    markets = {int(code): str(label) for code, label in raw["markets"].items()}
    _check(len(markets) > 0, "markets must not be empty")

    ref = raw["refresh"]
    backfill = ref["backfill_from"]
    refresh = RefreshConfig(
        listings_every_days=int(ref["listings_every_days"]),
        corporate_actions_window=int(ref["corporate_actions_window"]),
        corporate_actions_forward=int(ref["corporate_actions_forward"]),
        backfill_from=backfill if isinstance(backfill, date) else date.fromisoformat(str(backfill)),
        max_listing_drop_pct=float(ref["max_listing_drop_pct"]),
    )
    _check(refresh.listings_every_days >= 1, "refresh.listings_every_days must be >= 1")
    _check(refresh.corporate_actions_window >= 0, "refresh.corporate_actions_window must be >= 0")
    _check(refresh.corporate_actions_forward >= 0, "refresh.corporate_actions_forward must be >= 0")
    _check(0 <= refresh.max_listing_drop_pct <= 100, "refresh.max_listing_drop_pct must be 0-100")

    out = raw["output"]
    output = OutputConfig(api_version=str(out["api_version"]), timezone=str(out["timezone"]))
    try:
        ZoneInfo(output.timezone)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"unknown output.timezone {output.timezone!r}") from exc

    return Config(
        source=source,
        markets=markets,
        combined_market=int(raw["quotes"]["combined_market"]),
        refresh=refresh,
        output=output,
    )


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_config.py -q`
Expected: `13 passed`.

- [ ] **Step 7: Commit**

```bash
git add -A __init__.py config.toml jamstockex/__init__.py jamstockex/config.py requirements.txt requirements-dev.txt pytest.ini .gitignore tests/__init__.py tests/helpers.py tests/test_config.py
git commit -m "feat: add v2 package scaffold and validated config.toml" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Data models

**Files:**
- Create: `jamstockex/models.py`, `tests/test_models.py`

**Interfaces:**
- Produces:
  - helpers `num(Decimal | None) -> int | float | None`, `dec(value) -> Decimal | None`, `isodate(date | None) -> str | None`, `parse_iso(str | None) -> date | None`
  - `Quote(date, close, change, change_pct, volume)`
  - `Company(instrument_code, symbol, name, market, currency=None, sector=None, type=None, website=None, listed=True, listed_since=None, delisted_on=None, quote=None)`
  - `Index(name, date, value, change, change_pct, volume)`
  - frozen `CorporateAction(symbol, type, amount, currency, record_date, ex_date, payment_date, instrument_code=None)` with `.key()`
  - each class has `.to_json() -> dict` and `@classmethod from_json(d) -> Self`

- [ ] **Step 1: Write the failing tests**

`tests/test_models.py`:

```python
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
        instrument_code="ACME-JMD", symbol="ACME", name="Acme Holdings Limited", market="Main Market",
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
    company = Company(instrument_code="BETA-USD", symbol="BETA", name="Beta", market="USD Market")
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
    loaded = CorporateAction.from_json({**data, "instrument_code": "ACME-JMD"})
    assert loaded.amount == Decimal("0.75")
    assert loaded.key() == action.key()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_models.py -q`
Expected: `ModuleNotFoundError: No module named 'jamstockex.models'`.

- [ ] **Step 3: Implement `jamstockex/models.py`**

```python
"""Plain dataclasses for scraped JSE data, with JSON (de)serialisation."""

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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_models.py -q`
Expected: `6 passed`.

- [ ] **Step 5: Commit**

```bash
git add jamstockex/models.py tests/test_models.py
git commit -m "feat: add v2 data models with JSON serialisation" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Polite fetcher

**Files:**
- Create: `jamstockex/fetch.py`, `tests/test_fetch.py`, `tests/fixtures/cloudfront-blocked.html`

**Interfaces:**
- Consumes: `SourceConfig` (Task 2).
- Produces:
  - `FetchError(Exception)` and `BlockedError(FetchError)`
  - `is_block_page(text: str) -> bool`
  - `Fetcher(source: SourceConfig, session=None, sleep=time.sleep)` with `get(path: str) -> str` and attributes `request_count: int` and `blocked: bool`

- [ ] **Step 1: Create the block-page fixture**

`tests/fixtures/cloudfront-blocked.html` (the real CloudFront page observed on 2026-11-09, request ID removed):

```html
<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.01 Transitional//EN" "http://www.w3.org/TR/html4/loose.dtd">
<HTML><HEAD><META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=iso-8859-1">
<TITLE>ERROR: The request could not be satisfied</TITLE>
</HEAD><BODY>
<H1>403 ERROR</H1>
<H2>The request could not be satisfied.</H2>
<HR noshade size="1px">
Request blocked.
We can't connect to the server for this app or website at this time. There might be too much traffic or a configuration error. Try again later, or contact the app or website owner.
<BR clear="all">
<HR noshade size="1px">
<PRE>
Generated by cloudfront (CloudFront)
</PRE>
</BODY></HTML>
```

- [ ] **Step 2: Write the failing tests**

`tests/test_fetch.py`:

```python
import pytest
import requests

from jamstockex.config import SourceConfig
from jamstockex.fetch import BlockedError, FetchError, Fetcher, is_block_page
from tests.helpers import fixture_html

SOURCE = SourceConfig(
    base_url="https://www.example.test",
    user_agent="test-agent/1.0",
    timeout_s=7,
    retries=3,
    delay_s=(2.0, 2.0),
)


class FakeResponse:
    def __init__(self, status_code, text=""):
        self.status_code = status_code
        self.text = text


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, headers=None, timeout=None):
        self.calls.append({"url": url, "headers": headers, "timeout": timeout})
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def make(responses):
    session = FakeSession(responses)
    sleeps = []
    return Fetcher(SOURCE, session=session, sleep=sleeps.append), session, sleeps


def test_returns_body_and_sends_user_agent_and_timeout():
    fetcher, session, sleeps = make([FakeResponse(200, "<html>ok</html>")])
    assert fetcher.get("/path/?x=1") == "<html>ok</html>"
    assert session.calls == [
        {"url": "https://www.example.test/path/?x=1", "headers": {"User-Agent": "test-agent/1.0"}, "timeout": 7}
    ]
    assert sleeps == []
    assert fetcher.request_count == 1


def test_delays_between_requests_but_not_before_the_first():
    fetcher, _, sleeps = make([FakeResponse(200, "a"), FakeResponse(200, "b")])
    fetcher.get("/a")
    fetcher.get("/b")
    assert sleeps == [2.0]
    assert fetcher.request_count == 2


def test_retries_5xx_with_backoff_then_succeeds():
    fetcher, _, sleeps = make([FakeResponse(502), FakeResponse(200, "ok")])
    assert fetcher.get("/a") == "ok"
    assert fetcher.request_count == 2
    assert sleeps == [2.0, 2]  # politeness delay, then backoff 2**1


@pytest.mark.parametrize("error", [requests.ConnectionError("boom"), requests.Timeout("slow")])
def test_retries_connection_errors_and_timeouts(error):
    fetcher, _, _ = make([error, FakeResponse(200, "ok")])
    assert fetcher.get("/a") == "ok"


def test_gives_up_after_configured_attempts():
    fetcher, _, _ = make([FakeResponse(500), FakeResponse(503), FakeResponse(500)])
    with pytest.raises(FetchError, match="after 3 attempts"):
        fetcher.get("/a")
    assert fetcher.request_count == 3


def test_404_is_a_fetch_error_without_retry():
    fetcher, session, _ = make([FakeResponse(404)])
    with pytest.raises(FetchError, match="HTTP 404"):
        fetcher.get("/missing")
    assert len(session.calls) == 1


@pytest.mark.parametrize("status", [403, 429])
def test_block_status_raises_immediately_and_refuses_further_requests(status):
    fetcher, session, _ = make([FakeResponse(status)])
    with pytest.raises(BlockedError):
        fetcher.get("/a")
    assert fetcher.blocked is True
    with pytest.raises(BlockedError, match="refusing"):
        fetcher.get("/b")
    assert len(session.calls) == 1
    assert fetcher.request_count == 1


def test_cloudfront_block_page_is_blocked_even_with_200():
    fetcher, _, _ = make([FakeResponse(200, fixture_html("cloudfront-blocked.html"))])
    with pytest.raises(BlockedError):
        fetcher.get("/a")


def test_is_block_page():
    assert is_block_page(fixture_html("cloudfront-blocked.html"))
    assert not is_block_page("<html><table></table></html>")


def test_blocked_error_is_a_fetch_error():
    assert issubclass(BlockedError, FetchError)
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_fetch.py -q`
Expected: `ModuleNotFoundError: No module named 'jamstockex.fetch'`.

- [ ] **Step 4: Implement `jamstockex/fetch.py`**

```python
"""Polite HTTP client for the JSE website.

One honest User-Agent, a timeout, a random pause between requests, and
retries only for transient failures. A block (403/429 or a CloudFront block
page) is never retried, and after one the fetcher refuses all further
requests for the rest of the run (JSE Terms & Conditions §8.2).
"""

from __future__ import annotations

import logging
import random
import time
from typing import Callable
from urllib.parse import urljoin

import requests

from jamstockex.config import SourceConfig

log = logging.getLogger(__name__)

BLOCK_STATUSES = frozenset({403, 429})


class FetchError(Exception):
    """A page could not be fetched (after retries, or a non-retryable status)."""


class BlockedError(FetchError):
    """The site is blocking this client. Never retried or worked around."""


def is_block_page(text: str) -> bool:
    return "Request blocked" in text and "cloudfront" in text.lower()


class Fetcher:
    def __init__(
        self,
        source: SourceConfig,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.source = source
        self.session = session if session is not None else requests.Session()
        self.sleep = sleep
        self.request_count = 0
        self.blocked = False

    def get(self, path: str) -> str:
        if self.blocked:
            raise BlockedError("An earlier request was blocked; refusing to send more requests this run")
        url = urljoin(self.source.base_url + "/", path.lstrip("/"))
        problem = "no attempts made"
        for attempt in range(self.source.retries):
            if self.request_count:
                self.sleep(random.uniform(*self.source.delay_s))
            if attempt:
                self.sleep(2**attempt)
            self.request_count += 1
            log.info("GET %s", url)
            try:
                response = self.session.get(
                    url,
                    headers={"User-Agent": self.source.user_agent},
                    timeout=self.source.timeout_s,
                )
            except requests.RequestException as exc:
                problem = f"{type(exc).__name__}: {exc}"
                log.warning("Request failed (attempt %d/%d): %s", attempt + 1, self.source.retries, problem)
                continue
            if response.status_code in BLOCK_STATUSES or is_block_page(response.text):
                self.blocked = True
                raise BlockedError(f"HTTP {response.status_code} from {url}: the site is blocking this client")
            if response.status_code >= 500:
                problem = f"HTTP {response.status_code}"
                log.warning("Server error (attempt %d/%d): %s", attempt + 1, self.source.retries, problem)
                continue
            if response.status_code != 200:
                raise FetchError(f"HTTP {response.status_code} from {url}")
            return response.text
        raise FetchError(f"Gave up on {url} after {self.source.retries} attempts: {problem}")
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_fetch.py -q`
Expected: `12 passed`.

- [ ] **Step 6: Commit**

```bash
git add jamstockex/fetch.py tests/test_fetch.py tests/fixtures/cloudfront-blocked.html
git commit -m "feat: add polite fetcher that never retries a block" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Table helpers and value parsers

**Files:**
- Create: `jamstockex/parse.py`, `tests/test_parse_values.py`

**Interfaces:**
- Consumes: the models from Task 3. They're imported now so later tasks only append to this file.
- Produces:
  - `ParseError(page: str, problem: str)`
  - table helpers: `normalize_header(text) -> str`, `header_index(table) -> dict[str, int]`, `resolve_columns(header, aliases) -> dict[str, int | None]`, `matching_tables(soup, aliases, required) -> list[tuple[Tag, dict[str, int | None]]]`, `data_rows(table) -> list[Tag]`
  - cell helpers: `cell_text(cells, idx) -> str`, `cell_href(cells, idx) -> str | None`, `instrument_code_from_href(href) -> str | None`, `row_instrument_code(row) -> str | None`
  - `warn_missing_columns(page, column_sets, ignore=()) -> None`: logs one warning per page naming optional fields whose header matched no alias. `data_rows` also drops blank spacer rows.
  - value parsers: `to_decimal(text) -> Decimal | None`, `to_int(text) -> int | None`, `parse_date(text) -> date | None`, `parse_amount(text) -> tuple[str | None, Decimal | None]`, `normalize_action_type(text) -> str`

- [ ] **Step 1: Write the failing tests**

`tests/test_parse_values.py`:

```python
import datetime as dt
from decimal import Decimal

import pytest
from bs4 import BeautifulSoup

from jamstockex.parse import (
    cell_href, cell_text, data_rows, header_index, instrument_code_from_href, matching_tables,
    normalize_action_type, normalize_header, parse_amount, parse_date, resolve_columns,
    row_instrument_code, to_decimal, to_int, warn_missing_columns,
)


@pytest.mark.parametrize("text, expected", [
    ("Closing Price ($)", "closingprice"),
    ("% Change", "pctchange"),
    ("Change (%)", "changepct"),
    ("  Ex-Date ", "exdate"),
    ("Dividend\n Amount", "dividendamount"),
])
def test_normalize_header(text, expected):
    assert normalize_header(text) == expected


@pytest.mark.parametrize("text, expected", [
    ("1,234.50", Decimal("1234.50")),
    ("$12.5", Decimal("12.5")),
    ("(1.25)", Decimal("-1.25")),
    ("-0.25", Decimal("-0.25")),
    ("1.10%", Decimal("1.10")),
    (" 7 ", Decimal("7")),
    ("", None), ("-", None), ("n/a", None), ("abc", None), ("NaN", None), ("Infinity", None), (None, None),
])
def test_to_decimal(text, expected):
    assert to_decimal(text) == expected


@pytest.mark.parametrize("text, expected", [
    ("48,213", 48213), ("1000.0", 1000), ("0", 0), ("12.5", None), ("", None), ("x", None),
])
def test_to_int(text, expected):
    assert to_int(text) == expected


@pytest.mark.parametrize("text, expected", [
    ("Fri 20 Nov 2026", dt.date(2026, 11, 20)),
    ("  Fri  20 Nov 2026 ", dt.date(2026, 11, 20)),
    ("20 Nov 2026", dt.date(2026, 11, 20)),
    ("2026-11-20", dt.date(2026, 11, 20)),
    ("Friday 20 November 2026", dt.date(2026, 11, 20)),
    ("20 November 2026", dt.date(2026, 11, 20)),
    ("", None), ("soon", None),
])
def test_parse_date(text, expected):
    assert parse_date(text) == expected


@pytest.mark.parametrize("text, expected", [
    ("JMD 0.7500", ("JMD", Decimal("0.7500"))),
    ("usd 0.01", ("USD", Decimal("0.01"))),
    ("0.12", (None, Decimal("0.12"))),
    ("1:2", (None, None)),
    ("", (None, None)),
])
def test_parse_amount(text, expected):
    assert parse_amount(text) == expected


@pytest.mark.parametrize("text, expected", [
    ("Dividend", "dividend"), ("Stock Split", "stock_split"), ("Bonus Issue", "bonus_issue"),
    ("Rights  Issue!", "rights_issue"), ("", "dividend"),
])
def test_normalize_action_type(text, expected):
    assert normalize_action_type(text) == expected


@pytest.mark.parametrize("href, expected", [
    ("/market-data/instruments/?instrument=ACME-JMD", "ACME-JMD"),
    ("https://example.test/x/?a=1&instrument=BETA-USD", "BETA-USD"),
    ("/x/?a=1", None), ("/x/?instrument=", None), ("", None), (None, None),
])
def test_instrument_code_from_href(href, expected):
    assert instrument_code_from_href(href) == expected


TABLE_HTML = """
<table>
  <tr><th>Symbol</th><th>Closing Price ($)</th><th>Website</th></tr>
  <tr><td><a href="/i/?instrument=ACME-JMD">ACME</a></td><td> 12.50 </td><td><a href="https://acme.example">Visit</a></td></tr>
  <tr><td colspan="3">Footnote</td></tr>
  <tr><td> </td><td></td><td></td></tr>
</table>
<table><tr><th>Other</th></tr><tr><td>x</td></tr></table>
"""


def test_table_helpers():
    soup = BeautifulSoup(TABLE_HTML, "html.parser")
    first = soup.find("table")
    assert header_index(first) == {"symbol": 0, "closingprice": 1, "website": 2}

    aliases = {"symbol": ("symbol",), "close": ("closingprice", "lasttradedprice"), "volume": ("volume",)}
    assert resolve_columns(header_index(first), aliases) == {"symbol": 0, "close": 1, "volume": None}

    matches = matching_tables(soup, aliases, ("symbol", "close"))
    assert len(matches) == 1 and matches[0][0] is first

    rows = data_rows(first)
    assert len(rows) == 2
    cells = rows[0].find_all("td")
    assert cell_text(cells, 0) == "ACME"
    assert cell_text(cells, 1) == "12.50"
    assert cell_text(cells, None) == ""
    assert cell_text(cells, 9) == ""
    assert cell_href(cells, 2) == "https://acme.example"
    assert cell_href(cells, 1) is None
    assert row_instrument_code(rows[0]) == "ACME-JMD"
    assert row_instrument_code(rows[1]) is None


def test_warn_missing_columns(caplog):
    cols = [{"symbol": 0, "close": None, "volume": None}, {"symbol": 0, "close": None, "volume": 3}]
    warn_missing_columns("trade-quotes", cols, ignore=("volume",))
    assert caplog.messages == ["trade-quotes: column(s) not found, values will be null: close"]
    caplog.clear()
    warn_missing_columns("trade-quotes", [{"symbol": 0}])
    assert caplog.messages == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_parse_values.py -q`
Expected: `ModuleNotFoundError: No module named 'jamstockex.parse'`.

- [ ] **Step 3: Implement the first part of `jamstockex/parse.py`**

```python
"""HTML parsing for JSE website pages.

Columns are located by normalised header text, not position, so an inserted
or reordered column doesn't break parsing. When the site renames a header,
add the new normalised name to the relevant alias tuple. Value parsers
return None for anything they can't parse; they never invent a 0.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
from decimal import Decimal, InvalidOperation
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup, Tag

from jamstockex.models import Company, CorporateAction, Index, Quote

log = logging.getLogger(__name__)

Columns = dict[str, int | None]
Aliases = dict[str, tuple[str, ...]]

_EMPTY = {"", "-", "--", "n/a", "na", "nil"}
_DATE_FORMATS = ("%a %d %b %Y", "%d %b %Y", "%Y-%m-%d", "%A %d %B %Y", "%d %B %Y")


class ParseError(Exception):
    """A page doesn't have the structure we expect (usually a site layout change)."""

    def __init__(self, page: str, problem: str) -> None:
        super().__init__(f"{page}: {problem}")
        self.page = page
        self.problem = problem


# --- table helpers -------------------------------------------------------


def normalize_header(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower().replace("%", "pct"))


def header_index(table: Tag) -> dict[str, int]:
    rows = table.find_all("tr")
    if not rows:
        return {}
    index: dict[str, int] = {}
    for position, cell in enumerate(rows[0].find_all(["th", "td"])):
        index.setdefault(normalize_header(cell.get_text()), position)
    return index


def resolve_columns(header: dict[str, int], aliases: Aliases) -> Columns:
    return {field: next((header[name] for name in names if name in header), None) for field, names in aliases.items()}


def matching_tables(soup: BeautifulSoup, aliases: Aliases, required: tuple[str, ...]) -> list[tuple[Tag, Columns]]:
    matches = []
    for table in soup.find_all("table"):
        columns = resolve_columns(header_index(table), aliases)
        if all(columns[field] is not None for field in required):
            matches.append((table, columns))
    return matches


def data_rows(table: Tag) -> list[Tag]:
    """Rows after the header that have cells and some text (blank spacer rows are dropped)."""
    return [row for row in table.find_all("tr")[1:] if row.find_all("td") and row.get_text(strip=True)]


def warn_missing_columns(page: str, column_sets: list[Columns], ignore: tuple[str, ...] = ()) -> None:
    """Warn once per page about optional fields whose header matched no alias.

    Required fields raise ParseError instead. Without this warning, a renamed optional
    header would silently turn every value in that column into null.
    """
    missing = sorted({f for cols in column_sets for f, idx in cols.items() if idx is None} - set(ignore))
    if missing:
        log.warning("%s: column(s) not found, values will be null: %s", page, ", ".join(missing))


def cell_text(cells: list[Tag], idx: int | None) -> str:
    if idx is None or idx >= len(cells):
        return ""
    return " ".join(cells[idx].get_text(" ").split())


def cell_href(cells: list[Tag], idx: int | None) -> str | None:
    if idx is None or idx >= len(cells):
        return None
    link = cells[idx].find("a", href=True)
    return link["href"].strip() if link else None


def instrument_code_from_href(href: str | None) -> str | None:
    if not href:
        return None
    values = parse_qs(urlparse(href).query).get("instrument")
    if not values:
        return None
    return values[0].strip() or None


def row_instrument_code(row: Tag) -> str | None:
    for link in row.find_all("a", href=True):
        code = instrument_code_from_href(link["href"])
        if code:
            return code
    return None


# --- value parsers -------------------------------------------------------


def to_decimal(text: str | None) -> Decimal | None:
    if text is None:
        return None
    cleaned = text.strip().replace(",", "").replace("$", "").replace("%", "").replace(" ", "")
    negative = cleaned.startswith("(") and cleaned.endswith(")")
    if negative:
        cleaned = cleaned[1:-1]
    if cleaned.lower() in _EMPTY:
        return None
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        return None
    if not value.is_finite():
        return None
    return -value if negative else value


def to_int(text: str | None) -> int | None:
    value = to_decimal(text)
    if value is None or value != value.to_integral_value():
        return None
    return int(value)


def parse_date(text: str | None) -> dt.date | None:
    cleaned = " ".join((text or "").split())
    for fmt in _DATE_FORMATS:
        try:
            return dt.datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    return None


def parse_amount(text: str | None) -> tuple[str | None, Decimal | None]:
    """'JMD 0.7500' -> ('JMD', Decimal('0.7500')); '0.12' -> (None, Decimal('0.12'))."""
    parts = (text or "").split()
    if not parts:
        return None, None
    if len(parts) >= 2 and parts[0].isalpha():
        return parts[0].upper(), to_decimal(parts[-1])
    return None, to_decimal(parts[-1])


def normalize_action_type(text: str | None) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")
    return normalized or "dividend"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_parse_values.py -q`
Expected: `50 passed`.

- [ ] **Step 5: Commit**

```bash
git add jamstockex/parse.py tests/test_parse_values.py
git commit -m "feat: add header-matched table helpers and null-safe value parsers" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Listed-companies parser

**Files:**
- Modify: `jamstockex/parse.py` (append)
- Create: `tests/fixtures/listed-companies.html`, `tests/fixtures/listed-companies-empty.html`, `tests/test_parse_listings.py`

**Interfaces:**
- Consumes: the Task 5 helpers and `Company`.
- Produces: `LISTING_COLUMNS: Aliases` and `parse_listed_companies(html: str, market_label: str) -> list[Company]`, which raises `ParseError` when no listings table is present. It logs one warning per page for unmatched optional columns and one for skipped rows (never one per row), because parser warnings are copied into the run summary (Task 12).

- [ ] **Step 1: Create the fixtures**

`tests/fixtures/listed-companies.html` (synthetic; the second table mimics the site's duplicated responsive table):

```html
<!doctype html>
<html><body>
<h1>Listed Companies</h1>
<table class="table">
  <thead><tr><th>Security</th><th>Symbol</th><th>Currency</th><th>Sector</th><th>Type</th><th>Website</th></tr></thead>
  <tbody>
    <tr>
      <td><a href="/market-data/instruments/?instrument=ACME-JMD">Acme Holdings Limited</a></td>
      <td><a href="/market-data/instruments/?instrument=ACME-JMD">ACME</a></td>
      <td>JMD</td><td>Manufacturing</td><td>Ordinary</td>
      <td><a href="https://www.acme.example">Visit</a></td>
    </tr>
    <tr>
      <td><a href="/market-data/instruments/?instrument=BETA-USD">Beta Capital Limited</a></td>
      <td>BETA</td><td>USD</td><td>Finance</td><td>Ordinary</td><td></td>
    </tr>
    <tr>
      <td>Row Without Link Limited</td><td>NOLINK</td><td>JMD</td><td>Other</td><td>Ordinary</td><td></td>
    </tr>
  </tbody>
</table>
<table class="table mobile">
  <thead><tr><th>Security</th><th>Symbol</th><th>Currency</th><th>Sector</th><th>Type</th><th>Website</th></tr></thead>
  <tbody>
    <tr>
      <td><a href="/market-data/instruments/?instrument=ACME-JMD">Acme Holdings Limited</a></td>
      <td>ACME</td><td>JMD</td><td>Manufacturing</td><td>Ordinary</td><td></td>
    </tr>
  </tbody>
</table>
</body></html>
```

`tests/fixtures/listed-companies-empty.html`:

```html
<!doctype html>
<html><body>
<table class="table">
  <thead><tr><th>Security</th><th>Symbol</th><th>Currency</th><th>Sector</th><th>Type</th><th>Website</th></tr></thead>
  <tbody></tbody>
</table>
</body></html>
```

- [ ] **Step 2: Write the failing tests**

`tests/test_parse_listings.py`:

```python
import pytest

from jamstockex.parse import ParseError, parse_listed_companies
from tests.helpers import fixture_html


def test_parses_companies_and_dedupes_duplicate_tables():
    companies = parse_listed_companies(fixture_html("listed-companies.html"), "Main Market")
    by_code = {c.instrument_code: c for c in companies}
    assert set(by_code) == {"ACME-JMD", "BETA-USD"}

    acme = by_code["ACME-JMD"]
    assert acme.symbol == "ACME"
    assert acme.name == "Acme Holdings Limited"  # original case kept
    assert acme.market == "Main Market"
    assert acme.currency == "JMD"
    assert acme.sector == "Manufacturing"
    assert acme.type == "Ordinary"
    assert acme.website == "https://www.acme.example"  # first table wins
    assert acme.listed is True and acme.quote is None

    assert by_code["BETA-USD"].website is None


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
    assert companies["ACME-JMD"].website is None


def test_skipped_rows_and_missing_columns_are_warned_once(caplog):
    html = fixture_html("listed-companies.html").replace("<th>Sector</th>", "<th>Industry Group</th>")
    parse_listed_companies(html, "Main Market")
    assert caplog.messages == [
        "listed-companies (Main Market): column(s) not found, values will be null: sector",
        "listed-companies (Main Market): skipped 1 row(s) without an instrument link or symbol",
    ]
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_parse_listings.py -q`
Expected: `ImportError: cannot import name 'parse_listed_companies'`.

- [ ] **Step 4: Append the parser to `jamstockex/parse.py`**

```python


# --- listed companies ----------------------------------------------------

LISTING_COLUMNS: Aliases = {
    "name": ("security", "instrument", "instrumentname", "company", "name"),
    "symbol": ("symbol", "ticker"),
    "currency": ("currency",),
    "sector": ("sector",),
    "type": ("type", "instrumenttype", "securitytype"),
    "website": ("website", "url"),
}


def _website(cells: list[Tag], idx: int | None) -> str | None:
    href = cell_href(cells, idx)
    if not href or not href.startswith(("http://", "https://")):
        return None
    if "jamstockex.com" in urlparse(href).netloc.lower():
        return None
    return href


def parse_listed_companies(html: str, market_label: str) -> list[Company]:
    soup = BeautifulSoup(html, "html.parser")
    tables = matching_tables(soup, LISTING_COLUMNS, ("name", "symbol"))
    if not tables:
        raise ParseError("listed-companies", "no table with 'security' and 'symbol' columns")
    warn_missing_columns(f"listed-companies ({market_label})", [cols for _, cols in tables])
    companies: dict[str, Company] = {}
    skipped = 0
    for table, cols in tables:
        for row in data_rows(table):
            cells = row.find_all("td")
            code = row_instrument_code(row)
            symbol = cell_text(cells, cols["symbol"])
            if not code or not symbol:
                skipped += 1
                continue
            companies.setdefault(code, Company(
                instrument_code=code,
                symbol=symbol,
                name=cell_text(cells, cols["name"]),
                market=market_label,
                currency=cell_text(cells, cols["currency"]) or None,
                sector=cell_text(cells, cols["sector"]) or None,
                type=cell_text(cells, cols["type"]) or None,
                website=_website(cells, cols["website"]),
            ))
    if skipped:
        log.warning("listed-companies (%s): skipped %d row(s) without an instrument link or symbol",
                    market_label, skipped)
    return list(companies.values())
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_parse_listings.py -q`
Expected: `5 passed`.

- [ ] **Step 6: Commit**

```bash
git add jamstockex/parse.py tests/test_parse_listings.py tests/fixtures/listed-companies.html tests/fixtures/listed-companies-empty.html
git commit -m "feat: parse listed companies by header name" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Trade-quotes and indices parser

**Files:**
- Modify: `jamstockex/parse.py` (append)
- Create: `tests/fixtures/trade-quotes.html`, `tests/fixtures/trade-quotes-extra-column.html`, `tests/fixtures/trade-quotes-holiday.html`, `tests/test_parse_quotes.py`

**Interfaces:**
- Consumes: the Task 5 helpers, `Quote` and `Index`.
- Produces:
  - `QUOTE_COLUMNS` and `INDEX_COLUMNS`
  - `compute_change_pct(close, change) -> Decimal | None`
  - `parse_trade_quotes(html: str, trade_date: date) -> tuple[dict[str, Quote], list[Index]]`. A holiday page (a quotes table with a header but no rows) returns empty results. A page with **no quotes table** raises `ParseError`, even if the indices table parses, so a renamed price header fails the run instead of looking like a holiday. A missing indices table only logs a warning.

- [ ] **Step 1: Create the fixtures**

`tests/fixtures/trade-quotes.html`:

```html
<!doctype html>
<html><body>
<h2>Indices</h2>
<table>
  <tr><th>Index</th><th>Value</th><th>Volume</th><th>Change</th><th>% Change</th></tr>
  <tr><td>JSE Main Index</td><td>325,456.78</td><td>12,345,678</td><td>-1,234.56</td><td>-0.38</td></tr>
  <tr><td>JSE Junior Market Index</td><td>3,901.12</td><td>2,000,000</td><td>10.50</td><td>0.27</td></tr>
</table>
<h2>Ordinary Shares</h2>
<table>
  <tr><th>Security</th><th>Symbol</th><th>Last Traded Price ($)</th><th>Closing Price ($)</th><th>Price Change ($)</th><th>Volume</th></tr>
  <tr>
    <td><a href="/market-data/instruments/?instrument=ACME-JMD">Acme Holdings Limited</a></td>
    <td><a href="/market-data/instruments/?instrument=ACME-JMD">ACME</a></td>
    <td>12.40</td><td>12.50</td><td>-0.25</td><td>48,213</td>
  </tr>
</table>
<h2>USD Equities</h2>
<table>
  <tr><th>Security</th><th>Symbol</th><th>Last Traded Price ($)</th><th>Closing Price ($)</th><th>Price Change ($)</th><th>Volume</th></tr>
  <tr>
    <td><a href="/market-data/instruments/?instrument=BETA-USD">Beta Capital Limited</a></td>
    <td><a href="/market-data/instruments/?instrument=BETA-USD">BETA</a></td>
    <td>0.0850</td><td>0.0850</td><td>0.0050</td><td>1,000</td>
  </tr>
  <tr><td>No Link Limited</td><td>ZZZ</td><td>1</td><td>1</td><td>0</td><td>1</td></tr>
</table>
</body></html>
```

`tests/fixtures/trade-quotes-extra-column.html` (an inserted ISIN column, a reordered layout, and a `% Change` column):

```html
<!doctype html>
<html><body>
<table>
  <tr><th>Symbol</th><th>ISIN</th><th>Security</th><th>Volume</th><th>Closing Price ($)</th><th>Price Change ($)</th><th>% Change</th></tr>
  <tr>
    <td><a href="/market-data/instruments/?instrument=ACME-JMD">ACME</a></td>
    <td>JMXX00000001</td><td>Acme Holdings Limited</td><td>48,213</td><td>12.50</td><td>-0.25</td><td>-1.95</td>
  </tr>
</table>
</body></html>
```

`tests/fixtures/trade-quotes-holiday.html`:

```html
<!doctype html>
<html><body>
<table><tr><th>Index</th><th>Value</th><th>Volume</th><th>Change</th><th>% Change</th></tr></table>
<table><tr><th>Security</th><th>Symbol</th><th>Last Traded Price ($)</th><th>Closing Price ($)</th><th>Price Change ($)</th><th>Volume</th></tr></table>
<p>No trades for the selected date.</p>
</body></html>
```

- [ ] **Step 2: Write the failing tests**

`tests/test_parse_quotes.py`:

```python
import datetime as dt
from decimal import Decimal

import pytest

from jamstockex.models import Index, Quote
from jamstockex.parse import ParseError, compute_change_pct, parse_trade_quotes
from tests.helpers import fixture_html

DAY = dt.date(2026, 11, 9)


def test_parses_quotes_across_tables_keyed_by_instrument_code():
    quotes, _ = parse_trade_quotes(fixture_html("trade-quotes.html"), DAY)
    assert set(quotes) == {"ACME-JMD", "BETA-USD"}  # row without link skipped
    assert quotes["ACME-JMD"] == Quote(date=DAY, close=Decimal("12.50"), change=Decimal("-0.25"),
                                       change_pct=Decimal("-1.96"), volume=48213)
    assert quotes["BETA-USD"] == Quote(date=DAY, close=Decimal("0.0850"), change=Decimal("0.0050"),
                                       change_pct=Decimal("6.25"), volume=1000)


def test_parses_indices():
    _, indices = parse_trade_quotes(fixture_html("trade-quotes.html"), DAY)
    assert indices == [
        Index(name="JSE Main Index", date=DAY, value=Decimal("325456.78"), change=Decimal("-1234.56"),
              change_pct=Decimal("-0.38"), volume=12345678),
        Index(name="JSE Junior Market Index", date=DAY, value=Decimal("3901.12"), change=Decimal("10.50"),
              change_pct=Decimal("0.27"), volume=2000000),
    ]


def test_inserted_and_reordered_columns_still_parse_and_page_pct_is_used(caplog):
    quotes, indices = parse_trade_quotes(fixture_html("trade-quotes-extra-column.html"), DAY)
    assert indices == []
    assert "trade-quotes: no indices table (with 'index' and 'value' columns) found" in caplog.messages
    assert quotes["ACME-JMD"] == Quote(date=DAY, close=Decimal("12.50"), change=Decimal("-0.25"),
                                       change_pct=Decimal("-1.95"), volume=48213)


def test_holiday_page_returns_empty_results():
    assert parse_trade_quotes(fixture_html("trade-quotes-holiday.html"), DAY) == ({}, [])


def test_page_without_tables_raises():
    with pytest.raises(ParseError, match="trade-quotes"):
        parse_trade_quotes("<html><body>Down for maintenance</body></html>", DAY)


def test_renamed_price_header_raises_even_when_indices_parse():
    html = (fixture_html("trade-quotes.html")
            .replace("Closing Price ($)", "Close ($)").replace("Last Traded Price ($)", "Last ($)"))
    with pytest.raises(ParseError, match="no quotes table"):
        parse_trade_quotes(html, DAY)


def test_renamed_optional_header_is_warned(caplog):
    html = fixture_html("trade-quotes.html").replace("<th>Price Change ($)</th><th>Volume</th>",
                                                     "<th>Price Change ($)</th><th>Shares</th>")
    quotes, _ = parse_trade_quotes(html, DAY)
    assert quotes["ACME-JMD"].volume is None
    assert "trade-quotes: column(s) not found, values will be null: volume" in caplog.messages


@pytest.mark.parametrize("close, change, expected", [
    (Decimal("12.50"), Decimal("-0.25"), Decimal("-1.96")),
    (Decimal("10"), Decimal("0"), Decimal("0.00")),
    (Decimal("1"), Decimal("1"), None),  # previous price 0
    (None, Decimal("1"), None),
    (Decimal("1"), None, None),
])
def test_compute_change_pct(close, change, expected):
    assert compute_change_pct(close, change) == expected
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_parse_quotes.py -q`
Expected: `ImportError: cannot import name 'compute_change_pct'`.

- [ ] **Step 4: Append the parser to `jamstockex/parse.py`**

```python


# --- trade quotes and indices ---------------------------------------------

QUOTE_COLUMNS: Aliases = {
    "symbol": ("symbol",),
    "close": ("closingprice", "closeprice", "lasttradedprice", "lastprice"),
    "change": ("pricechange", "change", "changes"),
    "change_pct": ("pctchange", "changepct", "percentchange"),
    "volume": ("volume", "volumetraded"),
}

INDEX_COLUMNS: Aliases = {
    "name": ("index", "indexname"),
    "value": ("value", "indexvalue", "closingvalue"),
    "change": ("change", "pointchange", "valuechange"),
    "change_pct": ("pctchange", "changepct", "percentchange"),
    "volume": ("volume",),
}


def compute_change_pct(close: Decimal | None, change: Decimal | None) -> Decimal | None:
    if close is None or change is None:
        return None
    previous = close - change
    if previous == 0:
        return None
    return (change / previous * 100).quantize(Decimal("0.01"))


def parse_trade_quotes(html: str, trade_date: dt.date) -> tuple[dict[str, Quote], list[Index]]:
    soup = BeautifulSoup(html, "html.parser")
    quote_tables = matching_tables(soup, QUOTE_COLUMNS, ("symbol", "close"))
    index_tables = [
        (table, cols)
        for table, cols in matching_tables(soup, INDEX_COLUMNS, ("name", "value"))
        if "symbol" not in header_index(table)
    ]
    # A holiday page still has the quotes table header, just no rows. No quotes table at all
    # means the layout changed, which must fail loudly rather than look like a holiday.
    if not quote_tables:
        raise ParseError("trade-quotes", "no quotes table with 'symbol' and 'closing price' columns")
    if not index_tables:
        log.warning("trade-quotes: no indices table (with 'index' and 'value' columns) found")
    warn_missing_columns("trade-quotes", [cols for _, cols in quote_tables], ignore=("change_pct",))
    warn_missing_columns("trade-quotes (indices)", [cols for _, cols in index_tables])

    quotes: dict[str, Quote] = {}
    skipped = 0
    for table, cols in quote_tables:
        for row in data_rows(table):
            cells = row.find_all("td")
            code = row_instrument_code(row)
            if not code:
                skipped += 1
                continue
            close = to_decimal(cell_text(cells, cols["close"]))
            change = to_decimal(cell_text(cells, cols["change"]))
            change_pct = to_decimal(cell_text(cells, cols["change_pct"]))
            if change_pct is None:
                change_pct = compute_change_pct(close, change)
            quotes.setdefault(code, Quote(
                date=trade_date,
                close=close,
                change=change,
                change_pct=change_pct,
                volume=to_int(cell_text(cells, cols["volume"])),
            ))

    if skipped:
        log.warning("trade-quotes: skipped %d row(s) without an instrument link", skipped)

    indices: dict[str, Index] = {}
    for table, cols in index_tables:
        for row in data_rows(table):
            cells = row.find_all("td")
            name = cell_text(cells, cols["name"])
            if not name:
                continue
            indices.setdefault(name, Index(
                name=name,
                date=trade_date,
                value=to_decimal(cell_text(cells, cols["value"])),
                change=to_decimal(cell_text(cells, cols["change"])),
                change_pct=to_decimal(cell_text(cells, cols["change_pct"])),
                volume=to_int(cell_text(cells, cols["volume"])),
            ))
    return quotes, list(indices.values())
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_parse_quotes.py -q`
Expected: `12 passed`.

- [ ] **Step 6: Commit**

```bash
git add jamstockex/parse.py tests/test_parse_quotes.py tests/fixtures/trade-quotes*.html
git commit -m "feat: parse trade quotes and indices by header name" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Corporate-actions parser

**Files:**
- Modify: `jamstockex/parse.py` (append)
- Create: `tests/fixtures/corporate-actions.html`, `tests/test_parse_actions.py`

**Interfaces:**
- Consumes: the Task 5 helpers and `CorporateAction`.
- Produces: `ACTION_COLUMNS` and `parse_corporate_actions(html: str) -> list[CorporateAction]`. The result is deduplicated by `.key()`, symbols are upper-cased, `instrument_code` comes from a row link when one exists (otherwise `None`), and a missing table raises `ParseError`. `execution date` (the v1 name) is an alias for `ex_date`.

- [ ] **Step 1: Create the fixture**

`tests/fixtures/corporate-actions.html`:

```html
<!doctype html>
<html><body>
<table>
  <thead><tr><th>Record Date</th><th>Instrument</th><th>Action</th><th>Ex-Date</th><th>Payment Date</th><th>Dividend Amount</th></tr></thead>
  <tbody>
    <tr><td>Fri 20 Nov 2026</td><td>ACME</td><td>Dividend</td><td>Wed 18 Nov 2026</td><td>Fri 4 Dec 2026</td><td>JMD 0.7500</td></tr>
    <tr><td>Mon 2 Mar 2026</td><td><a href="/market-data/instruments/?instrument=BETA-USD">BETA</a></td><td>Dividend</td><td>Thu 26 Feb 2026</td><td>Mon 16 Mar 2026</td><td>USD 0.0100</td></tr>
    <tr><td>Tue 14 Apr 2026</td><td>acme</td><td>Stock Split</td><td>Tue 14 Apr 2026</td><td></td><td></td></tr>
    <tr><td>Fri 20 Nov 2026</td><td>ACME</td><td>Dividend</td><td>Wed 18 Nov 2026</td><td>Fri 4 Dec 2026</td><td>JMD 0.7500</td></tr>
    <tr><td></td><td></td><td></td><td></td><td></td><td></td></tr>
  </tbody>
</table>
</body></html>
```

- [ ] **Step 2: Write the failing tests**

`tests/test_parse_actions.py`:

```python
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
                        payment_date=dt.date(2026, 12, 4), instrument_code=None),
        CorporateAction(symbol="BETA", type="dividend", amount=Decimal("0.0100"), currency="USD",
                        record_date=dt.date(2026, 3, 2), ex_date=dt.date(2026, 2, 26),
                        payment_date=dt.date(2026, 3, 16), instrument_code="BETA-USD"),
        CorporateAction(symbol="ACME", type="stock_split", amount=None, currency=None,
                        record_date=dt.date(2026, 4, 14), ex_date=dt.date(2026, 4, 14),
                        payment_date=None, instrument_code=None),
    ]
    assert caplog.messages == []  # the blank spacer row is dropped silently


def test_execution_date_header_is_an_ex_date_alias():
    html = fixture_html("corporate-actions.html").replace("<th>Ex-Date</th>", "<th>Execution Date</th>")
    assert parse_corporate_actions(html)[0].ex_date == dt.date(2026, 11, 18)


def test_missing_table_raises():
    with pytest.raises(ParseError, match="corporate-actions"):
        parse_corporate_actions("<html><body><table><tr><th>Foo</th></tr></table></body></html>")
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_parse_actions.py -q`
Expected: `ImportError: cannot import name 'parse_corporate_actions'`.

- [ ] **Step 4: Append the parser to `jamstockex/parse.py`**

```python


# --- corporate actions ----------------------------------------------------

ACTION_COLUMNS: Aliases = {
    "symbol": ("instrument", "symbol", "security"),
    "type": ("action", "corporateaction", "actiontype"),
    "amount": ("dividendamount", "amount", "rate"),
    "record_date": ("recorddate",),
    "ex_date": ("exdate", "exdividenddate", "executiondate"),  # v1 called this column "execution date"
    "payment_date": ("paymentdate", "paymentduedate", "paymentdue", "payabledate"),
}


def parse_corporate_actions(html: str) -> list[CorporateAction]:
    soup = BeautifulSoup(html, "html.parser")
    tables = matching_tables(soup, ACTION_COLUMNS, ("symbol", "amount"))
    if not tables:
        raise ParseError("corporate-actions", "no table with 'instrument' and 'dividend amount' columns")
    warn_missing_columns("corporate-actions", [cols for _, cols in tables])
    actions: dict[tuple, CorporateAction] = {}
    skipped = 0
    for table, cols in tables:
        for row in data_rows(table):
            cells = row.find_all("td")
            symbol = cell_text(cells, cols["symbol"]).upper()
            if not symbol:
                skipped += 1
                continue
            currency, amount = parse_amount(cell_text(cells, cols["amount"]))
            action = CorporateAction(
                symbol=symbol,
                type=normalize_action_type(cell_text(cells, cols["type"])),
                amount=amount,
                currency=currency,
                record_date=parse_date(cell_text(cells, cols["record_date"])),
                ex_date=parse_date(cell_text(cells, cols["ex_date"])),
                payment_date=parse_date(cell_text(cells, cols["payment_date"])),
                instrument_code=row_instrument_code(row),
            )
            actions.setdefault(action.key(), action)
    if skipped:
        log.warning("corporate-actions: skipped %d row(s) without an instrument", skipped)
    return list(actions.values())
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_parse_actions.py -q`, then the full suite with `.venv/bin/pytest -q`.
Expected: `3 passed`, and the full suite all green.

- [ ] **Step 6: Commit**

```bash
git add jamstockex/parse.py tests/test_parse_actions.py tests/fixtures/corporate-actions.html
git commit -m "feat: parse dividends and other corporate actions" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Verify the parsers against real JSE pages

**Why:** the synthetic fixtures use the header names the portfolio-tracker verified in June 2026, but the live site may differ. This task confirms the parsers against real pages and records the real `instrument_code` format. It also checks four assumptions the build depends on:
- every market's listings page has the same layout;
- no page is paginated;
- a no-trading day returns an empty quotes table rather than an error page or the previous session's data;
- the corporate-actions page accepts a `thruDate` in the future.

**Files:**
- Create: `tests/test_parse_real.py`, `tests/fixtures/README.md`
- Possibly modify: the alias tuples in `jamstockex/parse.py` and the header text in the synthetic fixtures

**Interfaces:** none new.

- [ ] **Step 1: Ask the user to save three pages from their browser**

Ask the user: "Please open these pages in your browser and save each with **Save Page As → Webpage, HTML Only** into `tests/fixtures/real/`, which is gitignored and never committed. The site paths are the ones the scraper uses (see `jamstockex/build.py`); you can type them after the site's address:
1. `/listings/listed-companies/?market=31` (Main Market) → `listed-companies-31.html`
2. `/listings/listed-companies/?market=22` (Junior Market) → `listed-companies-22.html`
3. `/listings/listed-companies/?market=51` (Bond Market) → `listed-companies-51.html`
4. `/listings/listed-companies/?market=49` (USD Market) → `listed-companies-49.html`
5. `/trading/trade-quotes/?market=50&date=<a recent trading day>` → `trade-quotes-combined.html`
6. `/trading/trade-quotes/?market=50&date=2026-10-19` (National Heroes Day, no trading) → `trade-quotes-holiday.html`
7. `/trading/corporate-actions/?instrumentCode=all-stocks&fromDate=2026-01-01&thruDate=<today + 1 year>` → `corporate-actions.html`

While you're on each page, please tell me if it shows page numbers or a 'next page' link, and whether the market labels (Main Market, Junior Market, Bond Market, USD Market) match what the site shows for codes 31, 22, 51 and 49."

Wait until the files exist:

```bash
ls -la tests/fixtures/real/
```

- [ ] **Step 2: Write the real-page tests (they skip when the files are absent, e.g. in CI)**

`tests/test_parse_real.py`:

```python
"""Checks against real JSE pages saved locally in tests/fixtures/real/ (gitignored).

Skipped when the files are absent (e.g. in CI). See tests/fixtures/README.md.
"""

import datetime as dt
import re

import pytest
from bs4 import BeautifulSoup

from jamstockex.parse import (
    ACTION_COLUMNS, INDEX_COLUMNS, LISTING_COLUMNS, QUOTE_COLUMNS, matching_tables,
    parse_corporate_actions, parse_listed_companies, parse_trade_quotes,
)
from tests.helpers import FIXTURES, ROOT

REAL = FIXTURES / "real"
MARKETS = {31: "Main Market", 22: "Junior Market", 51: "Bond Market", 49: "USD Market"}
PAGES = [f"listed-companies-{code}.html" for code in MARKETS] + [
    "trade-quotes-combined.html", "trade-quotes-holiday.html", "corporate-actions.html",
]
PAGINATION = re.compile(r"[?&](page|paged|offset|start)=\d|class=\"[^\"]*pagination|rel=\"next\"", re.IGNORECASE)


def real(name: str) -> str:
    path = REAL / name
    if not path.exists():
        pytest.skip(f"real fixture {name} not present (see tests/fixtures/README.md)")
    return path.read_text(encoding="utf-8", errors="replace")


@pytest.mark.parametrize("code, label", MARKETS.items())
def test_real_listed_companies(code, label):
    companies = parse_listed_companies(real(f"listed-companies-{code}.html"), label)
    assert companies, f"{label}: no companies parsed"
    assert all(c.instrument_code and c.symbol and c.name for c in companies)
    assert sum(1 for c in companies if c.currency) >= 0.9 * len(companies)


def test_real_trade_quotes():
    quotes, indices = parse_trade_quotes(real("trade-quotes-combined.html"), dt.date(2026, 11, 9))
    assert len(quotes) > 20
    for field in ("close", "change", "volume"):
        assert sum(1 for q in quotes.values() if getattr(q, field) is not None) >= 0.9 * len(quotes), field
    assert len(indices) >= 1
    assert all(i.value is not None for i in indices)


def test_real_holiday_page_is_empty_not_an_error():
    """Also catches the site answering a holiday date with the previous session's quotes."""
    quotes, _ = parse_trade_quotes(real("trade-quotes-holiday.html"), dt.date(2026, 10, 19))
    assert quotes == {}


def test_real_corporate_actions():
    actions = parse_corporate_actions(real("corporate-actions.html"))
    dividends = [a for a in actions if a.type == "dividend"]
    assert dividends
    assert sum(1 for a in dividends if a.amount is not None and a.currency) >= 0.9 * len(dividends)
    for field in ("record_date", "ex_date", "payment_date"):
        assert sum(1 for a in dividends if getattr(a, field) is not None) >= 0.9 * len(dividends), field


@pytest.mark.parametrize("name, aliases, required, may_be_missing", [
    *[(f"listed-companies-{code}.html", LISTING_COLUMNS, ("name", "symbol"), {"website"}) for code in MARKETS],
    ("trade-quotes-combined.html", QUOTE_COLUMNS, ("symbol", "close"), {"change_pct"}),
    ("trade-quotes-combined.html", INDEX_COLUMNS, ("name", "value"), set()),
    ("corporate-actions.html", ACTION_COLUMNS, ("symbol", "amount"), set()),
])
def test_real_every_column_resolves(name, aliases, required, may_be_missing):
    """A field whose header matches no alias would be silently null on every row."""
    tables = matching_tables(BeautifulSoup(real(name), "html.parser"), aliases, required)
    assert tables
    unresolved = {f for _, cols in tables for f, idx in cols.items() if idx is None} - may_be_missing
    assert unresolved == set(), f"{name}: add the real header names to the alias tuples for {unresolved}"


@pytest.mark.parametrize("name", PAGES)
def test_real_pages_are_not_paginated(name):
    """The scraper reads one page per request. Pagination would silently drop rows."""
    assert not PAGINATION.search(real(name)), f"{name} looks paginated; STOP and tell the user"


def test_real_listing_and_quote_codes_line_up():
    listed = {c.instrument_code for c in parse_listed_companies(real("listed-companies-31.html"), "Main Market")}
    quotes, _ = parse_trade_quotes(real("trade-quotes-combined.html"), dt.date(2026, 11, 9))
    assert len(listed & set(quotes)) >= 0.5 * len(listed)


def test_real_market_labels_match_config():
    text = (ROOT / "config.toml").read_text(encoding="utf-8")
    for code, label in MARKETS.items():
        assert f'{code} = "{label}"' in text
```

- [ ] **Step 3: Run them**

Run: `.venv/bin/pytest tests/test_parse_real.py -v`
Expected: all 23 tests pass (most are parametrised). If any fail, go to Step 4; otherwise skip to Step 5.

**Stop conditions. Report to the user before changing any code:**
- `test_real_pages_are_not_paginated` fails, or the user saw page numbers: the scraper would need to follow pages, which changes the request budget.
- `test_real_holiday_page_is_empty_not_an_error` fails because quotes came back: the site answers a holiday date with the previous session's data, so `Quote.date` would be wrong. The parser would need to read the trading date from the page.
- The holiday page raises `ParseError`: real holiday pages have no quotes table, so the holiday rule in `parse_trade_quotes` needs a page-specific "no trades" marker.
- A market's labels or codes differ from `config.toml`.

- [ ] **Step 4: If a test fails, inspect the real headers and fix the aliases**

Print the normalised headers and an example instrument link for each table:

```bash
.venv/bin/python - <<'EOF'
from pathlib import Path
from bs4 import BeautifulSoup
from jamstockex.parse import header_index, row_instrument_code, data_rows
for path in sorted(Path("tests/fixtures/real").glob("*.html")):
    soup = BeautifulSoup(path.read_text(encoding="utf-8", errors="replace"), "html.parser")
    print(f"== {path.name}")
    for n, table in enumerate(soup.find_all("table")):
        rows = data_rows(table)
        code = next((c for c in map(row_instrument_code, rows) if c), None)
        print(f"  table {n}: rows={len(rows)} headers={list(header_index(table))} sample_code={code!r}")
EOF
```

For each field that didn't resolve (`test_real_every_column_resolves` names them), add the printed normalised header name to that field's alias tuple in `jamstockex/parse.py` (`LISTING_COLUMNS`, `QUOTE_COLUMNS`, `INDEX_COLUMNS` or `ACTION_COLUMNS`). If a field genuinely doesn't exist on a page, add it to that page's `may_be_missing` set in the test, with a comment. Then change the matching `<th>` text in the synthetic fixture, so the committed tests reflect the real layout. Re-run `.venv/bin/pytest -q` until it's all green.

If the corporate-actions instrument cell contains more than the symbol (e.g. a company name), adjust `parse_corporate_actions` to take the first whitespace-separated token: `cell_text(...).split()[0].upper()` guarded for empty. Add a fixture row and a test for it.

- [ ] **Step 5: Record the findings (no JSE content, just structure)**

`tests/fixtures/README.md`. Fill in the bracketed values from the Step 4 output, or run it now if Step 3 passed:

```markdown
# Test fixtures

- `*.html` in this folder are **synthetic** pages with fake companies. Their table
  headers mirror the real JSE site layout, so the committed tests exercise the real
  structure without republishing JSE content.
- `real/` is **gitignored**. Save real pages there from a browser (Save Page As →
  HTML only) to run `tests/test_parse_real.py` locally:
  - `listed-companies-31.html`: Listed Companies, Main Market
  - `trade-quotes-combined.html`: Trade Quotes, Combined Market
  - `corporate-actions.html`: Corporate Actions, all stocks, a date range

## Real layout, verified [DATE OF VERIFICATION]

- Listed companies headers: [normalised header list]
- Trade quotes headers: [list]; indices headers: [list]
- Corporate actions headers: [list]
- `instrument_code` format (from `?instrument=`): [e.g. `NCBFG-JMD`]
```

Replace every bracketed value with the actual output before committing; no brackets may remain.

- [ ] **Step 6: Commit**

```bash
git add tests/test_parse_real.py tests/fixtures/README.md jamstockex/parse.py tests/fixtures/*.html tests/test_parse_*.py
git status --short tests/fixtures/real   # must print nothing (gitignored)
git commit -m "test: verify parsers against real JSE page layouts" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: Store — state, load, write

**Files:**
- Create: `jamstockex/store.py`, `tests/test_store_io.py`

**Interfaces:**
- Consumes: the models (Task 3).
- Produces:
  - `DATASETS`, `SOURCE`, `TERMS_URL`, `LICENSE`, `ATTRIBUTION`
  - `DatasetStatus(as_of=None, fetched_at=None, stale=False, last_error=None)` with `to_json`/`from_json`
  - `State(companies: dict[str, Company], indices: list[Index], actions: list[CorporateAction], status: dict[str, DatasetStatus], markets: dict[str, DatasetStatus], unmatched: set[str])`. `markets` is keyed by market label; `unmatched` holds quote codes that a full listings refresh didn't explain. Both are persisted in `status.json` under `data.listings.markets` and `data.listings.unmatched_codes`.
  - functions:
    - `utc_timestamp(datetime) -> str`
    - `safe_filename(code) -> str`
    - `load(site_dir: Path, api_version: str) -> State`
    - `write(state: State, site_dir: Path, *, api_version: str, now: datetime) -> None`. A per-stock file's `stale` is `quotes.stale OR <its market>.stale`. A file is **not rewritten** if only `generated_at` would change, so `generated_at` means "content last changed" and holidays don't churn the data branch.

- [ ] **Step 1: Write the failing tests**

`tests/test_store_io.py`:

```python
import datetime as dt
import json
from decimal import Decimal

from jamstockex import store
from jamstockex.models import Company, CorporateAction, Index, Quote
from tests.helpers import JSE_URL, assert_envelope, read_json

DAY = dt.date(2026, 11, 9)
NOW = dt.datetime(2026, 11, 9, 22, 30, 5, tzinfo=dt.timezone.utc)


def sample_state() -> store.State:
    state = store.State()
    state.companies = {
        "ACME-JMD": Company(instrument_code="ACME-JMD", symbol="ACME", name="Acme Holdings Limited",
                            market="Main Market", currency="JMD", listed_since=DAY,
                            quote=Quote(date=DAY, close=Decimal("12.50"), change=Decimal("-0.25"),
                                        change_pct=Decimal("-1.96"), volume=48213)),
        "BETA/USD": Company(instrument_code="BETA/USD", symbol="BETA", name="Beta Capital Limited",
                            market="USD Market", currency="USD", listed_since=DAY),
    }
    state.indices = [Index(name="JSE Main Index", date=DAY, value=Decimal("325456.78"), change=None,
                           change_pct=None, volume=None)]
    state.actions = [
        CorporateAction(symbol="ACME", type="dividend", amount=Decimal("0.75"), currency="JMD",
                        record_date=dt.date(2026, 11, 20), ex_date=None, payment_date=None,
                        instrument_code="ACME-JMD"),
        CorporateAction(symbol="ACME", type="stock_split", amount=None, currency=None,
                        record_date=dt.date(2026, 4, 14), ex_date=None, payment_date=None,
                        instrument_code="ACME-JMD"),
        CorporateAction(symbol="ZZZ", type="dividend", amount=Decimal("1"), currency="JMD",
                        record_date=dt.date(2026, 5, 1), ex_date=None, payment_date=None,
                        instrument_code=None),
    ]
    state.status["listings"] = store.DatasetStatus(as_of=DAY, fetched_at=NOW, stale=True,
                                                   last_error="USD Market: FetchError: x")
    state.markets = {
        "Main Market": store.DatasetStatus(as_of=DAY, fetched_at=NOW),
        "USD Market": store.DatasetStatus(as_of=DAY, fetched_at=NOW, stale=True, last_error="FetchError: x"),
    }
    state.unmatched = {"GAMMA-JMD"}
    state.status["quotes"] = store.DatasetStatus(as_of=DAY, fetched_at=NOW)
    state.status["indices"] = store.DatasetStatus(as_of=DAY, fetched_at=NOW)
    state.status["corporate_actions"] = store.DatasetStatus(as_of=None, stale=True, last_error="FetchError: boom")
    return state


def test_load_from_empty_dir_gives_empty_state(tmp_path):
    state = store.load(tmp_path / "site", "v2")
    assert state.companies == {} and state.indices == [] and state.actions == []
    assert state.markets == {} and state.unmatched == set()
    assert set(state.status) == set(store.DATASETS)
    assert all(s == store.DatasetStatus() for s in state.status.values())


def test_write_creates_the_v2_tree_with_envelopes(tmp_path):
    store.write(sample_state(), tmp_path, api_version="v2", now=NOW)
    base = tmp_path / "v2"
    names = sorted(str(p.relative_to(base)) for p in base.rglob("*.json"))
    assert names == [
        "corporate-actions.json", "dividends.json", "index.json", "indices.json", "status.json",
        "stocks.json", "stocks/ACME-JMD.json", "stocks/BETA-USD.json",
    ]
    for path in base.rglob("*.json"):
        doc = read_json(path)
        assert_envelope(doc)
        assert doc["meta"]["generated_at"] == "2026-11-09T22:30:05Z"
        assert not JSE_URL.search(path.read_text(encoding="utf-8"))


def test_meta_as_of_and_stale_follow_dataset_status(tmp_path):
    store.write(sample_state(), tmp_path, api_version="v2", now=NOW)
    base = tmp_path / "v2"
    assert read_json(base / "stocks.json")["meta"]["stale"] is True  # listings stale: one market failed
    assert read_json(base / "stocks.json")["meta"]["as_of"] == "2026-11-09"
    assert read_json(base / "corporate-actions.json")["meta"]["stale"] is True
    assert read_json(base / "corporate-actions.json")["meta"]["as_of"] is None
    assert read_json(base / "status.json")["meta"]["stale"] is True  # any dataset stale
    beta = read_json(base / "stocks" / "BETA-USD.json")
    assert beta["meta"]["as_of"] == "2026-11-09"  # no quote -> its market's as_of
    assert beta["meta"]["stale"] is True  # USD Market failed
    assert read_json(base / "stocks" / "ACME-JMD.json")["meta"]["stale"] is False  # Main Market is fine


def test_per_stock_file_has_actions_and_dividends(tmp_path):
    store.write(sample_state(), tmp_path, api_version="v2", now=NOW)
    acme = read_json(tmp_path / "v2" / "stocks" / "ACME-JMD.json")["data"]
    assert acme["symbol"] == "ACME" and acme["quote"]["close"] == 12.5
    assert [a["type"] for a in acme["corporate_actions"]] == ["stock_split", "dividend"]  # sorted by record_date
    assert [a["type"] for a in acme["dividends"]] == ["dividend"]


def test_aggregate_files(tmp_path):
    store.write(sample_state(), tmp_path, api_version="v2", now=NOW)
    base = tmp_path / "v2"
    assert [s["instrument_code"] for s in read_json(base / "stocks.json")["data"]] == ["ACME-JMD", "BETA/USD"]
    assert len(read_json(base / "corporate-actions.json")["data"]) == 3
    assert {a["symbol"] for a in read_json(base / "dividends.json")["data"]} == {"ACME", "ZZZ"}
    status = read_json(base / "status.json")["data"]
    assert status["corporate_actions"] == {"as_of": None, "fetched_at": None, "stale": True,
                                           "last_error": "FetchError: boom"}
    assert status["listings"]["markets"]["USD Market"]["last_error"] == "FetchError: x"
    assert status["listings"]["markets"]["Main Market"]["stale"] is False
    assert status["listings"]["unmatched_codes"] == ["GAMMA-JMD"]
    index = read_json(base / "index.json")["data"]
    assert index["endpoints"]["stock"] == "stocks/{instrument_code}.json"
    assert index["attribution_required"] == store.ATTRIBUTION


def test_output_is_minified_and_deterministic(tmp_path):
    store.write(sample_state(), tmp_path / "a", api_version="v2", now=NOW)
    store.write(sample_state(), tmp_path / "b", api_version="v2", now=NOW)
    for path in (tmp_path / "a" / "v2").rglob("*.json"):
        text = path.read_text(encoding="utf-8")
        compact = json.dumps(json.loads(text), separators=(",", ":"), sort_keys=True, ensure_ascii=False) + "\n"
        assert text == compact
        assert text == (tmp_path / "b" / "v2" / path.relative_to(tmp_path / "a" / "v2")).read_text(encoding="utf-8")


def test_write_then_load_round_trips(tmp_path):
    original = sample_state()
    store.write(original, tmp_path, api_version="v2", now=NOW)
    loaded = store.load(tmp_path, "v2")
    assert loaded.companies == original.companies
    assert loaded.indices == original.indices
    assert sorted(loaded.actions, key=lambda a: a.key()) == sorted(original.actions, key=lambda a: a.key())
    assert loaded.status == original.status
    assert loaded.markets == original.markets
    assert loaded.unmatched == original.unmatched


def test_unchanged_files_keep_their_generated_at(tmp_path):
    store.write(sample_state(), tmp_path, api_version="v2", now=NOW)
    changed = sample_state()
    changed.companies["ACME-JMD"].quote.close = Decimal("13")
    store.write(changed, tmp_path, api_version="v2", now=NOW + dt.timedelta(days=1))
    base = tmp_path / "v2"

    def generated_at(name):
        return read_json(base / name)["meta"]["generated_at"]

    assert generated_at("indices.json") == "2026-11-09T22:30:05Z"
    assert generated_at("stocks/BETA-USD.json") == "2026-11-09T22:30:05Z"
    assert generated_at("stocks.json") == "2026-11-10T22:30:05Z"
    assert generated_at("stocks/ACME-JMD.json") == "2026-11-10T22:30:05Z"


def test_safe_filename():
    assert store.safe_filename("ACME-JMD") == "ACME-JMD"
    assert store.safe_filename("BETA/USD ord") == "BETA-USD-ord"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_store_io.py -q`
Expected: `ImportError: cannot import name 'store'`.

- [ ] **Step 3: Implement `jamstockex/store.py`**

```python
"""Persistent state. The previously published JSON *is* the store.

`load` reads the v2 tree from the site directory (a checkout of the `data`
branch), `merge` folds in a new scrape, and `write` emits the tree again.
A file whose content hasn't changed is left untouched (it keeps its old
`generated_at`), so the data branch only records real changes.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import re
from dataclasses import dataclass, field, replace
from decimal import Decimal
from pathlib import Path
from typing import Any

from jamstockex.models import Company, CorporateAction, Index, Quote, isodate, parse_iso

log = logging.getLogger(__name__)

DATASETS = ("listings", "quotes", "indices", "corporate_actions")
SOURCE = (
    "Data: Jamaica Stock Exchange Limited (jamstockex.com). "
    "All rights in the data belong to the JSE Group."
)
TERMS_URL = "https://github.com/sdclarkelab/jamstockex-scraper/blob/main/TERMS.md"
LICENSE = "Code: PolyForm Noncommercial 1.0.0"
ATTRIBUTION = "Data: Jamaica Stock Exchange, via jamstockex-scraper"


def utc_timestamp(moment: dt.datetime) -> str:
    return moment.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def safe_filename(code: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "-", code)


@dataclass
class DatasetStatus:
    as_of: dt.date | None = None
    fetched_at: dt.datetime | None = None
    stale: bool = False
    last_error: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "as_of": isodate(self.as_of),
            "fetched_at": utc_timestamp(self.fetched_at) if self.fetched_at else None,
            "stale": self.stale,
            "last_error": self.last_error,
        }

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> DatasetStatus:
        fetched_at = d.get("fetched_at")
        return cls(
            as_of=parse_iso(d.get("as_of")),
            fetched_at=dt.datetime.fromisoformat(fetched_at) if fetched_at else None,
            stale=bool(d.get("stale", False)),
            last_error=d.get("last_error"),
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


# --- load -----------------------------------------------------------------


def load(site_dir: Path, api_version: str) -> State:
    base = Path(site_dir) / api_version
    state = State()
    stocks = _read_data(base / "stocks.json")
    if stocks:
        state.companies = {d["instrument_code"]: Company.from_json(d) for d in stocks}
    indices = _read_data(base / "indices.json")
    if indices:
        state.indices = [Index.from_json(d) for d in indices]
    actions = _read_data(base / "corporate-actions.json")
    if actions:
        state.actions = [CorporateAction.from_json(d) for d in actions]
    status = _read_data(base / "status.json")
    if status:
        for name, data in status.items():
            if name in state.status:
                state.status[name] = DatasetStatus.from_json(data)
        listings = status.get("listings", {})
        state.markets = {label: DatasetStatus.from_json(d) for label, d in listings.get("markets", {}).items()}
        state.unmatched = set(listings.get("unmatched_codes", []))
    return state


def _read_data(path: Path) -> Any:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"), parse_float=Decimal)["data"]


# --- write ----------------------------------------------------------------


def write(state: State, site_dir: Path, *, api_version: str, now: dt.datetime) -> None:
    base = Path(site_dir) / api_version
    (base / "stocks").mkdir(parents=True, exist_ok=True)
    status = state.status
    generated_at = utc_timestamp(now)
    any_stale = any(s.stale for s in status.values())
    stock_stale = status["listings"].stale or status["quotes"].stale
    stock_as_of = status["quotes"].as_of or status["listings"].as_of
    actions_status = status["corporate_actions"]

    def meta(as_of: dt.date | None, stale: bool) -> dict[str, Any]:
        return {
            "api_version": api_version,
            "as_of": isodate(as_of),
            "generated_at": generated_at,
            "stale": stale,
            "source": SOURCE,
            "terms": TERMS_URL,
            "license": LICENSE,
        }

    companies = sorted(state.companies.values(), key=lambda c: c.instrument_code)
    actions = sorted(state.actions, key=_action_sort_key)

    status_data = {n: s.to_json() for n, s in status.items()}
    status_data["listings"]["markets"] = {label: m.to_json() for label, m in sorted(state.markets.items())}
    status_data["listings"]["unmatched_codes"] = sorted(state.unmatched)

    _dump(base / "index.json", meta(stock_as_of, any_stale), _index_data())
    _dump(base / "status.json", meta(stock_as_of, any_stale), status_data)
    _dump(base / "stocks.json", meta(stock_as_of, stock_stale), [c.to_json() for c in companies])
    _dump(
        base / "indices.json",
        meta(status["indices"].as_of, status["indices"].stale),
        [i.to_json() for i in sorted(state.indices, key=lambda i: i.name)],
    )
    _dump(base / "corporate-actions.json", meta(actions_status.as_of, actions_status.stale),
          [a.to_json() for a in actions])
    _dump(base / "dividends.json", meta(actions_status.as_of, actions_status.stale),
          [a.to_json() for a in actions if a.type == "dividend"])

    by_code: dict[str, list[CorporateAction]] = {}
    for action in actions:
        if action.instrument_code:
            by_code.setdefault(action.instrument_code, []).append(action)
    for company in companies:
        own = by_code.get(company.instrument_code, [])
        entry = company.to_json()
        entry["corporate_actions"] = [a.to_json() for a in own]
        entry["dividends"] = [a.to_json() for a in own if a.type == "dividend"]
        # A failing market only marks its own instruments stale.
        market = state.markets.get(company.market, status["listings"])
        as_of = company.quote.date if company.quote else market.as_of
        stale = status["quotes"].stale or market.stale
        _dump(base / "stocks" / f"{safe_filename(company.instrument_code)}.json", meta(as_of, stale), entry)


def _action_sort_key(action: CorporateAction) -> tuple:
    return (action.record_date or dt.date.min, action.symbol, action.type, action.payment_date or dt.date.min)


def _index_data() -> dict[str, Any]:
    return {
        "name": "jamstockex-scraper",
        "description": "Unofficial end-of-day Jamaica Stock Exchange data as static JSON. Not financial advice.",
        "endpoints_relative_to": "this file's directory",
        "endpoints": {
            "status": "status.json",
            "stocks": "stocks.json",
            "stock": "stocks/{instrument_code}.json",
            "indices": "indices.json",
            "corporate_actions": "corporate-actions.json",
            "dividends": "dividends.json",
        },
        "attribution_required": ATTRIBUTION,
        "updated": "Mon-Fri at about 17:30 America/Jamaica; check status.json for freshness",
    }


def _encode(doc: dict[str, Any]) -> str:
    return json.dumps(doc, separators=(",", ":"), sort_keys=True, ensure_ascii=False) + "\n"


def _dump(path: Path, meta: dict[str, Any], data: Any) -> bool:
    """Write the file unless only `generated_at` would change. Returns True if written."""
    if path.exists():
        old_text = path.read_text(encoding="utf-8")
        try:
            old_generated_at = json.loads(old_text)["meta"]["generated_at"]
        except (ValueError, KeyError, TypeError):
            old_generated_at = None
        if old_generated_at and _encode({"meta": {**meta, "generated_at": old_generated_at}, "data": data}) == old_text:
            return False
    path.write_text(_encode({"meta": meta, "data": data}), encoding="utf-8")
    return True
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_store_io.py -q`
Expected: `9 passed`.

- [ ] **Step 5: Commit**

```bash
git add jamstockex/store.py tests/test_store_io.py
git commit -m "feat: load and write the v2 JSON tree as the persistent store" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: Store — merge rules

**Files:**
- Modify: `jamstockex/store.py` (append)
- Create: `tests/test_store_merge.py`

**Interfaces:**
- Consumes: `State`, `DatasetStatus` (Task 10) and the models.
- Produces:
  - `ScrapeResult(trade_date, listings=None, listing_errors={}, listings_full=False, quotes=None, indices=None, actions=None, errors={})`. `listings` maps market label → companies for the pages that loaded, `listing_errors` maps label → error, and `listings_full` means every configured market was requested.
  - `merge(state: State, result: ScrapeResult, *, today: date, now: datetime, max_listing_drop_pct: float) -> list[str]` (returns warnings and mutates `state`)
- Convention for callers: a dataset was **attempted** if its field is not `None` **or** its name is in `errors`. For listings, the caller sets `listings` to a dict (possibly empty) whenever any market was due.
- Listings rules:
  - **Per-market delisting guard:** delist only within markets whose page loaded, and hold a market's delistings (with a warning) if its page is empty or below `(1 − max_drop/100) ×` its previous listed count.
  - **Status:** each market gets its own status. The `listings` status summarises them: stale if any market is stale, `as_of` = the oldest market refresh.
  - **Unmatched codes:** after a full refresh, `unmatched = quote codes − known codes`.

- [ ] **Step 1: Write the failing tests**

`tests/test_store_merge.py`:

```python
import datetime as dt
from decimal import Decimal

from jamstockex import store
from jamstockex.models import Company, CorporateAction, Index, Quote
from jamstockex.store import ScrapeResult, State

TODAY = dt.date(2026, 11, 9)
NOW = dt.datetime(2026, 11, 9, 22, 30, tzinfo=dt.timezone.utc)
EARLIER = dt.date(2026, 11, 2)


def company(code, symbol=None, currency="JMD", market="Main Market", **kw):
    return Company(instrument_code=code, symbol=symbol or code.split("-")[0], name=f"{code} Limited",
                   market=market, currency=currency, **kw)


def quote(close, day=TODAY):
    return Quote(date=day, close=Decimal(close), change=Decimal("0"), change_pct=Decimal("0"), volume=100)


def action(symbol, amount="0.75", currency="JMD", type_="dividend", code=None, record=dt.date(2026, 11, 20)):
    return CorporateAction(symbol=symbol, type=type_, amount=Decimal(amount) if amount else None,
                           currency=currency, record_date=record, ex_date=None, payment_date=None,
                           instrument_code=code)


def merge(state, result, drop=20):
    return store.merge(state, result, today=TODAY, now=NOW, max_listing_drop_pct=drop)


def refresh(pages, errors=None, full=True, **kw):
    """A ScrapeResult for a listings refresh. pages: market label -> companies."""
    return ScrapeResult(trade_date=TODAY, listings=pages, listing_errors=errors or {}, listings_full=full, **kw)


def listed_state(*companies):
    state = State()
    for c in companies:
        c.listed_since = EARLIER
        state.companies[c.instrument_code] = c
        state.markets[c.market] = store.DatasetStatus(as_of=EARLIER)
    state.status["listings"] = store.DatasetStatus(as_of=EARLIER)
    return state


def main_market(*codes):
    return [company(code) for code in codes]


# --- listings -------------------------------------------------------------

def test_new_listings_get_listed_since_today_and_status_updates():
    state = State()
    merge(state, refresh({"Main Market": main_market("ACME-JMD")}))
    assert state.companies["ACME-JMD"].listed_since == TODAY
    fresh = store.DatasetStatus(as_of=TODAY, fetched_at=NOW, stale=False, last_error=None)
    assert state.status["listings"] == fresh
    assert state.markets == {"Main Market": fresh}


def test_listing_update_keeps_listed_since_and_quote():
    state = listed_state(*main_market("ACME-JMD"))
    state.companies["ACME-JMD"].quote = quote("10")
    renamed = company("ACME-JMD", sector="Retail")
    renamed.name = "Acme Group Limited"
    merge(state, refresh({"Main Market": [renamed]}))
    acme = state.companies["ACME-JMD"]
    assert acme.name == "Acme Group Limited" and acme.sector == "Retail"
    assert acme.listed_since == EARLIER
    assert acme.quote == quote("10")


def test_missing_instrument_is_delisted():
    state = listed_state(*main_market(*[f"C{i}-JMD" for i in range(10)]))
    warnings = merge(state, refresh({"Main Market": main_market(*[f"C{i}-JMD" for i in range(9)])}))
    gone = state.companies["C9-JMD"]
    assert gone.listed is False and gone.delisted_on == TODAY
    assert warnings == []


def test_failed_market_keeps_its_instruments_and_only_it_goes_stale():
    state = listed_state(company("ACME-JMD"), company("BETA-JMD", market="Junior Market"))
    merge(state, refresh({"Main Market": main_market("ACME-JMD")},
                         errors={"Junior Market": "FetchError: boom"}))
    assert state.companies["BETA-JMD"].listed is True
    assert state.markets["Main Market"].stale is False and state.markets["Main Market"].as_of == TODAY
    assert state.markets["Junior Market"].stale is True
    assert state.markets["Junior Market"].as_of == EARLIER  # not advanced -> retried next run
    assert state.status["listings"].stale is True
    assert state.status["listings"].last_error == "Junior Market: FetchError: boom"
    assert state.status["listings"].as_of == EARLIER  # oldest market refresh


def test_market_recovers_and_listings_stop_being_stale():
    state = listed_state(company("ACME-JMD"), company("BETA-JMD", market="Junior Market"))
    merge(state, refresh({"Main Market": main_market("ACME-JMD")}, errors={"Junior Market": "FetchError: boom"}))
    merge(state, refresh({"Junior Market": [company("BETA-JMD", market="Junior Market")]}, full=False))
    assert state.status["listings"] == store.DatasetStatus(as_of=TODAY, fetched_at=NOW, stale=False, last_error=None)


def test_delisting_held_when_a_market_drops_too_far():
    state = listed_state(*main_market(*[f"C{i}-JMD" for i in range(10)]))
    warnings = merge(state, refresh({"Main Market": main_market(*[f"C{i}-JMD" for i in range(7)])}))  # 7 < 8
    assert all(c.listed for c in state.companies.values())
    assert any("Delisting held for Main Market" in w for w in warnings)


def test_empty_page_for_a_small_market_does_not_delist_it():
    mains = main_market(*[f"M{i}-JMD" for i in range(100)])
    usd = [company(f"U{i}-USD", currency="USD", market="USD Market") for i in range(10)]
    state = listed_state(*mains, *usd)
    warnings = merge(state, refresh({"Main Market": main_market(*[f"M{i}-JMD" for i in range(100)]),
                                     "USD Market": []}))
    assert all(c.listed for c in state.companies.values())
    assert warnings == ["Delisting held for USD Market: 0 instrument(s) on the page vs 10 previously listed "
                        "(max drop 20%)"]


def test_instrument_moving_market_is_not_delisted():
    state = listed_state(company("ACME-JMD", market="Junior Market"))
    merge(state, refresh({"Main Market": main_market("ACME-JMD"), "Junior Market": []}))
    assert state.companies["ACME-JMD"].listed is True
    assert state.companies["ACME-JMD"].market == "Main Market"


def test_relisting_clears_delisted_on():
    state = listed_state(*main_market("ACME-JMD"))
    state.companies["ACME-JMD"].listed = False
    state.companies["ACME-JMD"].delisted_on = EARLIER
    merge(state, refresh({"Main Market": main_market("ACME-JMD")}))
    assert state.companies["ACME-JMD"].listed is True
    assert state.companies["ACME-JMD"].delisted_on is None
    assert state.companies["ACME-JMD"].listed_since == EARLIER


def test_listings_not_attempted_leaves_status_alone():
    state = listed_state(*main_market("ACME-JMD"))
    merge(state, ScrapeResult(trade_date=TODAY))
    assert state.status["listings"] == store.DatasetStatus(as_of=EARLIER)
    assert state.markets == {"Main Market": store.DatasetStatus(as_of=EARLIER)}


def test_full_refresh_remembers_unmatched_quote_codes_until_they_appear():
    state = listed_state(*main_market("ACME-JMD"))
    merge(state, refresh({"Main Market": main_market("ACME-JMD")},
                         quotes={"ACME-JMD": quote("1"), "GAMMA-JMD": quote("2")}, indices=[]))
    assert state.unmatched == {"GAMMA-JMD"}
    merge(state, refresh({"Main Market": main_market("ACME-JMD", "GAMMA-JMD")}, full=False))
    assert state.unmatched == set()


def test_partial_refresh_does_not_record_unmatched_codes():
    state = listed_state(*main_market("ACME-JMD"))
    merge(state, refresh({"Main Market": main_market("ACME-JMD")}, full=False,
                         quotes={"GAMMA-JMD": quote("2")}, indices=[]))
    assert state.unmatched == set()


# --- quotes and indices ---------------------------------------------------

def test_quotes_replace_present_and_keep_absent():
    state = listed_state(*main_market("ACME-JMD", "BETA-JMD"))
    state.companies["BETA-JMD"].quote = quote("5", day=EARLIER)
    merge(state, ScrapeResult(trade_date=TODAY, quotes={"ACME-JMD": quote("12")}, indices=[]))
    assert state.companies["ACME-JMD"].quote == quote("12")
    assert state.companies["BETA-JMD"].quote == quote("5", day=EARLIER)
    assert state.status["quotes"].as_of == TODAY and state.status["quotes"].stale is False


def test_unknown_quote_is_skipped_with_warning():
    state = listed_state(*main_market("ACME-JMD"))
    warnings = merge(state, ScrapeResult(trade_date=TODAY, quotes={"GAMMA-JMD": quote("1")}, indices=[]))
    assert "GAMMA-JMD" not in state.companies
    assert any("GAMMA-JMD" in w for w in warnings)


def test_holiday_keeps_quotes_indices_and_as_of():
    state = listed_state(*main_market("ACME-JMD"))
    state.companies["ACME-JMD"].quote = quote("10", day=EARLIER)
    old_index = Index(name="JSE Main Index", date=EARLIER, value=Decimal("1"), change=None, change_pct=None, volume=None)
    state.indices = [old_index]
    state.status["quotes"] = store.DatasetStatus(as_of=EARLIER)
    state.status["indices"] = store.DatasetStatus(as_of=EARLIER)
    merge(state, ScrapeResult(trade_date=TODAY, quotes={}, indices=[]))
    assert state.companies["ACME-JMD"].quote.date == EARLIER
    assert state.indices == [old_index]
    assert state.status["quotes"].as_of == EARLIER and state.status["quotes"].stale is False
    assert state.status["quotes"].fetched_at == NOW


def test_indices_replaced_when_present():
    state = State()
    new_index = Index(name="JSE Main Index", date=TODAY, value=Decimal("2"), change=None, change_pct=None, volume=None)
    merge(state, ScrapeResult(trade_date=TODAY, quotes={}, indices=[new_index]))
    assert state.indices == [new_index]
    assert state.status["indices"].as_of == TODAY


def test_failure_marks_stale_then_success_clears():
    state = listed_state(*main_market("ACME-JMD"))
    state.status["quotes"] = store.DatasetStatus(as_of=EARLIER, fetched_at=NOW - dt.timedelta(days=7))
    merge(state, ScrapeResult(trade_date=TODAY, errors={"quotes": "BlockedError: 403", "indices": "BlockedError: 403"}))
    assert state.status["quotes"].stale is True
    assert state.status["quotes"].last_error == "BlockedError: 403"
    assert state.status["quotes"].as_of == EARLIER
    merge(state, ScrapeResult(trade_date=TODAY, quotes={"ACME-JMD": quote("1")}, indices=[]))
    assert state.status["quotes"] == store.DatasetStatus(as_of=TODAY, fetched_at=NOW, stale=False, last_error=None)


# --- corporate actions ----------------------------------------------------

def test_actions_union_without_duplicates_across_decimal_scale():
    state = listed_state(*main_market("ACME-JMD"))
    state.actions = [action("ACME", amount="0.75")]
    merge(state, ScrapeResult(trade_date=TODAY, actions=[action("ACME", amount="0.7500"),
                                                         action("ACME", amount="0.80")]))
    assert len(state.actions) == 2
    assert state.status["corporate_actions"].as_of == TODAY


def test_actions_are_never_deleted():
    state = listed_state(*main_market("ACME-JMD"))
    state.actions = [action("ACME", record=dt.date(2026, 1, 15))]
    merge(state, ScrapeResult(trade_date=TODAY, actions=[]))
    assert len(state.actions) == 1


def test_action_mapping_rules():
    state = State()
    state.companies = {
        "ACME-JMD": company("ACME-JMD"),
        "DUAL-JMD": company("DUAL-JMD", symbol="DUAL", currency="JMD"),
        "DUAL-USD": company("DUAL-USD", symbol="DUAL", currency="USD"),
        "TWIN-A": company("TWIN-A", symbol="TWIN", currency="JMD"),
        "TWIN-B": company("TWIN-B", symbol="TWIN", currency="JMD"),
    }
    merge(state, ScrapeResult(trade_date=TODAY, actions=[
        action("ACME"),                                # unique symbol
        action("DUAL", currency="USD"),                # currency disambiguates
        action("TWIN"),                                # still ambiguous
        action("NOPE"),                                # unknown
        action("LINKED", code="LINKED-JMD"),           # code from page link kept
    ]))
    codes = {a.symbol: a.instrument_code for a in state.actions}
    assert codes == {"ACME": "ACME-JMD", "DUAL": "DUAL-USD", "TWIN": None, "NOPE": None, "LINKED": "LINKED-JMD"}


def test_stored_unmapped_actions_get_mapped_once_listings_arrive():
    state = State()
    state.actions = [action("ACME")]
    merge(state, refresh({"Main Market": main_market("ACME-JMD")}))
    assert state.actions[0].instrument_code == "ACME-JMD"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_store_merge.py -q`
Expected: `ImportError: cannot import name 'ScrapeResult'`.

- [ ] **Step 3: Append the merge logic to `jamstockex/store.py`**

```python


# --- merge ----------------------------------------------------------------


@dataclass
class ScrapeResult:
    """What one run fetched. A field left as None (and absent from errors) was not attempted."""

    trade_date: dt.date
    listings: dict[str, list[Company]] | None = None  # market label -> companies, for pages that loaded
    listing_errors: dict[str, str] = field(default_factory=dict)  # market label -> error
    listings_full: bool = False  # every configured market was requested this run
    quotes: dict[str, Quote] | None = None
    indices: list[Index] | None = None
    actions: list[CorporateAction] | None = None
    errors: dict[str, str] = field(default_factory=dict)


def merge(
    state: State,
    result: ScrapeResult,
    *,
    today: dt.date,
    now: dt.datetime,
    max_listing_drop_pct: float,
) -> list[str]:
    warnings: list[str] = []
    errors = result.errors

    if result.listings is not None or result.listing_errors:
        warnings += _merge_listings(state, result.listings or {}, result.listing_errors, today=today, now=now,
                                    max_drop_pct=max_listing_drop_pct)
        if result.listings_full and result.quotes is not None:
            # Whatever a full refresh couldn't explain won't trigger another refresh tomorrow.
            state.unmatched = set(result.quotes) - set(state.companies)

    if result.quotes is not None or "quotes" in errors:
        if result.quotes is not None:
            warnings += _merge_quotes(state, result.quotes)
        _mark(state.status["quotes"], errors.get("quotes"), now, as_of=result.trade_date if result.quotes else None)

    if result.indices is not None or "indices" in errors:
        if result.indices:
            state.indices = list(result.indices)
        _mark(state.status["indices"], errors.get("indices"), now,
              as_of=result.trade_date if result.indices else None)

    if result.actions is not None or "corporate_actions" in errors:
        if result.actions is not None:
            _merge_actions(state, result.actions)
        _mark(state.status["corporate_actions"], errors.get("corporate_actions"), now, as_of=today)

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


def _merge_listings(state: State, pages: dict[str, list[Company]], failed: dict[str, str], *,
                    today: dt.date, now: dt.datetime, max_drop_pct: float) -> list[str]:
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
                continue
            old.symbol, old.name, old.market = new.symbol, new.name, new.market
            old.currency, old.sector, old.type, old.website = new.currency, new.sector, new.type, new.website
            old.listed, old.delisted_on = True, None

    # Delist per market, and only for markets whose page loaded. Each market has its own guard,
    # so an empty or truncated page for a small market can't delist it wholesale.
    for label in sorted(pages):
        previous = listed_before[label]
        missing = previous - seen
        if missing:
            found = len({c.instrument_code for c in pages[label]})
            floor = (1 - max_drop_pct / 100) * len(previous)
            if found == 0 or found < floor:
                warnings.append(
                    f"Delisting held for {label}: {found} instrument(s) on the page vs {len(previous)} "
                    f"previously listed (max drop {max_drop_pct:g}%)"
                )
            else:
                for code in sorted(missing):
                    state.companies[code].listed = False
                    state.companies[code].delisted_on = today
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


def _merge_actions(state: State, actions: list[CorporateAction]) -> None:
    existing = {a.key() for a in state.actions}
    for new in actions:
        if new.key() not in existing:
            state.actions.append(new)
            existing.add(new.key())


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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_store_merge.py -q`, then the full suite with `.venv/bin/pytest -q`.
Expected: `21 passed`, and the full suite all green.

- [ ] **Step 5: Commit**

```bash
git add jamstockex/store.py tests/test_store_merge.py
git commit -m "feat: merge scrapes into stored state with delisting guard and stale tracking" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 12: Build orchestration and CLI

**Files:**
- Create: `jamstockex/build.py`, `jamstockex/__main__.py`, `tests/test_build.py`

**Interfaces:**
- Consumes:
  - `Config`/`load_config` (Task 2)
  - `Fetcher`, `FetchError`, `BlockedError` (Task 4)
  - the three parsers and `ParseError` (Tasks 6–8)
  - `store.load`, `store.merge`, `store.write`, `store.ScrapeResult` (Tasks 10–11)
- Produces:
  - path templates `QUOTES_PATH`, `LISTINGS_PATH`, `ACTIONS_PATH`
  - `trading_day(day: date) -> date`
  - `listings_due(state, quotes, markets, today, every_days, force) -> tuple[list[int], str | None]`. Returns every market for `--refresh-listings`, no stored listings, or a quote code that is neither known nor in `state.unmatched`. Otherwise it returns only the markets that are stale (retried alone, daily) or older than `every_days`.
  - `actions_from_date(status, window_days, backfill_from) -> date`: `backfill_from` until the first success, then `max(backfill_from, last success − window_days)`, so an outage is caught up.
  - `Report(trade_date, requests, errors, warnings, listings_refresh, counts)` with `.exit_code` and `.summary_markdown()`
  - `run(config, site_dir, fetcher, *, now, refresh_listings=False) -> Report`. Warnings logged by `jamstockex.parse` during the run are copied into `Report.warnings`, so they appear in the GitHub step summary.
  - `main(argv=None) -> int` in `__main__.py`, which returns 0 on success, 1 if any dataset failed, and 2 on a config error

- [ ] **Step 1: Write the failing tests**

`tests/test_build.py`:

```python
import datetime as dt

import pytest

from jamstockex import build
from jamstockex.__main__ import main
from jamstockex.config import load_config
from jamstockex.fetch import BlockedError, FetchError
from tests.helpers import JSE_URL, ROOT, assert_envelope, fixture_html, read_json

NOV_9 = dt.datetime(2026, 11, 9, 22, 30, tzinfo=dt.timezone.utc)   # Monday 17:30 in Jamaica
NOV_10 = dt.datetime(2026, 11, 10, 22, 30, tzinfo=dt.timezone.utc)
NOV_11 = dt.datetime(2026, 11, 11, 22, 30, tzinfo=dt.timezone.utc)
NOV_16 = dt.datetime(2026, 11, 16, 22, 30, tzinfo=dt.timezone.utc)
DEC_24 = dt.datetime(2026, 12, 24, 22, 30, tzinfo=dt.timezone.utc)


class FakeFetcher:
    """Serves pages by path prefix; mimics Fetcher's block behaviour and request count."""

    def __init__(self, pages):
        self.pages = pages
        self.paths = []
        self.request_count = 0
        self.blocked = False

    def get(self, path):
        if self.blocked:
            raise BlockedError("refusing after block")
        self.paths.append(path)
        self.request_count += 1
        for prefix, page in self.pages.items():
            if path.startswith(prefix):
                if isinstance(page, BlockedError):
                    self.blocked = True
                if isinstance(page, Exception):
                    raise page
                return page
        raise AssertionError(f"unexpected request: {path}")


def pages(overrides=None):
    empty = fixture_html("listed-companies-empty.html")
    result = {
        "/trading/trade-quotes/": fixture_html("trade-quotes.html"),
        "/listings/listed-companies/?market=31": fixture_html("listed-companies.html"),
        "/listings/listed-companies/?market=22": empty,
        "/listings/listed-companies/?market=51": empty,
        "/listings/listed-companies/?market=49": empty,
        "/trading/corporate-actions/": fixture_html("corporate-actions.html"),
    }
    result.update(overrides or {})
    return result


@pytest.fixture
def config():
    return load_config(ROOT / "config.toml")


def run(config, site, now, page_map=None, **kwargs):
    fetcher = FakeFetcher(pages(page_map))
    report = build.run(config, site, fetcher, now=now, **kwargs)
    return report, fetcher


@pytest.mark.parametrize("day, expected", [
    (dt.date(2026, 11, 9), dt.date(2026, 11, 9)),    # Monday
    (dt.date(2026, 11, 13), dt.date(2026, 11, 13)),  # Friday
    (dt.date(2026, 11, 14), dt.date(2026, 11, 13)),  # Saturday -> Friday
    (dt.date(2026, 11, 15), dt.date(2026, 11, 13)),  # Sunday -> Friday
])
def test_trading_day(day, expected):
    assert build.trading_day(day) == expected


def test_first_run_fetches_everything_and_writes_the_tree(config, tmp_path):
    report, fetcher = run(config, tmp_path, NOV_9)
    assert fetcher.paths == [
        "/trading/trade-quotes/?market=50&date=2026-11-09",
        "/listings/listed-companies/?market=31",
        "/listings/listed-companies/?market=22",
        "/listings/listed-companies/?market=51",
        "/listings/listed-companies/?market=49",
        "/trading/corporate-actions/?instrumentCode=all-stocks&fromDate=2026-01-01&thruDate=2027-11-09",
    ]
    assert report.exit_code == 0 and report.errors == {}
    assert report.requests == 6
    assert report.listings_refresh == "no stored listings"

    base = tmp_path / "v2"
    for path in base.rglob("*.json"):
        assert_envelope(read_json(path))
        assert not JSE_URL.search(path.read_text(encoding="utf-8"))
    acme = read_json(base / "stocks" / "ACME-JMD.json")["data"]
    assert acme["quote"]["close"] == 12.5
    assert [a["type"] for a in acme["corporate_actions"]] == ["stock_split", "dividend"]
    assert read_json(base / "stocks" / "BETA-USD.json")["data"]["dividends"][0]["currency"] == "USD"
    assert len(read_json(base / "indices.json")["data"]) == 2


def test_next_day_needs_only_two_requests(config, tmp_path):
    run(config, tmp_path, NOV_9)
    report, fetcher = run(config, tmp_path, NOV_10)
    assert fetcher.paths == [
        "/trading/trade-quotes/?market=50&date=2026-11-10",
        "/trading/corporate-actions/?instrumentCode=all-stocks&fromDate=2026-10-10&thruDate=2027-11-10",
    ]
    assert report.requests == 2 and report.listings_refresh is None
    assert read_json(tmp_path / "v2" / "status.json")["data"]["quotes"]["as_of"] == "2026-11-10"


def test_listings_refresh_when_due_by_age(config, tmp_path):
    run(config, tmp_path, NOV_9)
    report, fetcher = run(config, tmp_path, NOV_16)
    assert sum(p.startswith("/listings/") for p in fetcher.paths) == 4
    assert report.listings_refresh.startswith("last refresh")


def test_unknown_instrument_in_quotes_triggers_listings_refresh(config, tmp_path):
    run(config, tmp_path, NOV_9)
    gamma = fixture_html("trade-quotes.html").replace("BETA-USD", "GAMMA-JMD")
    report, fetcher = run(config, tmp_path, NOV_10, {"/trading/trade-quotes/": gamma})
    assert sum(p.startswith("/listings/") for p in fetcher.paths) == 4
    assert "unknown instrument" in report.listings_refresh
    assert any("GAMMA-JMD" in w for w in report.warnings)  # still unknown after refresh

    # The refresh couldn't explain GAMMA-JMD, so it doesn't trigger another one the next day.
    report, fetcher = run(config, tmp_path, NOV_11, {"/trading/trade-quotes/": gamma})
    assert report.requests == 2 and report.listings_refresh is None
    status = read_json(tmp_path / "v2" / "status.json")["data"]
    assert status["listings"]["unmatched_codes"] == ["GAMMA-JMD"]


def test_refresh_flag_forces_listings(config, tmp_path):
    run(config, tmp_path, NOV_9)
    report, fetcher = run(config, tmp_path, NOV_10, refresh_listings=True)
    assert sum(p.startswith("/listings/") for p in fetcher.paths) == 4
    assert report.listings_refresh == "requested"


def test_failed_dataset_publishes_the_rest_and_exits_1(config, tmp_path):
    report, _ = run(config, tmp_path, NOV_9, {"/trading/corporate-actions/": FetchError("Gave up after 3 attempts")})
    assert report.exit_code == 1
    assert report.errors["corporate_actions"] == "FetchError: Gave up after 3 attempts"
    status = read_json(tmp_path / "v2" / "status.json")["data"]
    assert status["corporate_actions"]["stale"] is True
    assert status["quotes"]["stale"] is False
    assert read_json(tmp_path / "v2" / "stocks.json")["data"][0]["quote"] is not None


def test_failed_market_is_retried_alone_and_only_its_stocks_go_stale(config, tmp_path):
    report, _ = run(config, tmp_path, NOV_9, {"/listings/listed-companies/?market=51": FetchError("boom")})
    assert report.exit_code == 1
    assert report.errors["listings"] == "Bond Market: FetchError: boom"
    assert read_json(tmp_path / "v2" / "stocks" / "ACME-JMD.json")["meta"]["stale"] is False  # Main Market
    assert read_json(tmp_path / "v2" / "status.json")["data"]["listings"]["markets"]["Bond Market"]["stale"] is True

    report, fetcher = run(config, tmp_path, NOV_10)
    assert [p for p in fetcher.paths if p.startswith("/listings/")] == ["/listings/listed-companies/?market=51"]
    assert report.requests == 3 and report.listings_refresh == "retrying failed market(s): Bond Market"
    assert report.exit_code == 0
    assert read_json(tmp_path / "v2" / "status.json")["data"]["listings"]["stale"] is False


def test_quotes_layout_change_fails_the_run(config, tmp_path):
    run(config, tmp_path, NOV_9)
    renamed = fixture_html("trade-quotes.html").replace("Closing Price ($)", "Close ($)").replace(
        "Last Traded Price ($)", "Last ($)")
    report, _ = run(config, tmp_path, NOV_10, {"/trading/trade-quotes/": renamed})
    assert report.exit_code == 1
    assert report.errors["quotes"].startswith("ParseError: trade-quotes: no quotes table")
    assert read_json(tmp_path / "v2" / "status.json")["data"]["quotes"]["stale"] is True


def test_missing_optional_column_is_reported(config, tmp_path):
    no_volume = fixture_html("trade-quotes.html").replace("<th>Price Change ($)</th><th>Volume</th>",
                                                         "<th>Price Change ($)</th><th>Shares</th>")
    report, _ = run(config, tmp_path, NOV_9, {"/trading/trade-quotes/": no_volume})
    assert report.exit_code == 0
    assert "trade-quotes: column(s) not found, values will be null: volume" in report.warnings
    assert "### Warnings" in report.summary_markdown()


def test_corporate_actions_catch_up_after_an_outage(config, tmp_path):
    run(config, tmp_path, NOV_9)
    _, fetcher = run(config, tmp_path, DEC_24)  # 45 days later, longer than the 30-day window
    assert fetcher.paths[-1] == (
        "/trading/corporate-actions/?instrumentCode=all-stocks&fromDate=2026-10-10&thruDate=2027-12-24"
    )


def test_holiday_rewrites_only_files_whose_content_changed(config, tmp_path):
    run(config, tmp_path, NOV_9)
    base = tmp_path / "v2"
    before = {p: p.read_text(encoding="utf-8") for p in base.rglob("*.json")}
    run(config, tmp_path, NOV_10, {"/trading/trade-quotes/": fixture_html("trade-quotes-holiday.html")})
    changed = sorted(str(p.relative_to(base)) for p, text in before.items() if p.read_text(encoding="utf-8") != text)
    # status.json is the heartbeat (fetched_at); corporate actions were re-fetched (as_of advances).
    assert changed == ["corporate-actions.json", "dividends.json", "status.json"]


def test_block_stops_all_requests_and_marks_everything_stale(config, tmp_path):
    report, fetcher = run(config, tmp_path, NOV_9, {"/trading/trade-quotes/": BlockedError("HTTP 403")})
    assert fetcher.request_count == 1
    assert report.exit_code == 1
    assert set(report.errors) == {"quotes", "indices", "listings", "corporate_actions"}
    status = read_json(tmp_path / "v2" / "status.json")["data"]
    assert all(s["stale"] for s in status.values())


def test_summary_markdown(config, tmp_path):
    report, _ = run(config, tmp_path, NOV_9, {"/trading/corporate-actions/": FetchError("boom")})
    text = report.summary_markdown()
    assert text.startswith("## JSE scrape for 2026-11-09")
    assert "Requests to the JSE site: 6" in text
    assert "### Errors" in text and "corporate_actions" in text


def test_main_runs_build_and_writes_step_summary(tmp_path, monkeypatch):
    monkeypatch.setattr("jamstockex.__main__.Fetcher", lambda source: FakeFetcher(pages()))
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    code = main(["build", "--out", str(tmp_path / "site"), "--config", str(ROOT / "config.toml")])
    assert code == 0
    assert (tmp_path / "site" / "v2" / "stocks.json").exists()
    assert "## JSE scrape for" in summary.read_text(encoding="utf-8")


def test_main_returns_2_on_config_error(tmp_path):
    assert main(["build", "--out", str(tmp_path / "site"), "--config", str(tmp_path / "missing.toml")]) == 2
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_build.py -q`
Expected: `ImportError: cannot import name 'build'`.

- [ ] **Step 3: Implement `jamstockex/build.py`**

```python
"""One build run: decide what's due, fetch, parse, merge into the store, write."""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo

from jamstockex import store
from jamstockex.config import Config
from jamstockex.fetch import FetchError, Fetcher
from jamstockex.models import Quote
from jamstockex.parse import ParseError, parse_corporate_actions, parse_listed_companies, parse_trade_quotes

log = logging.getLogger(__name__)

QUOTES_PATH = "/trading/trade-quotes/?market={market}&date={date}"
LISTINGS_PATH = "/listings/listed-companies/?market={market}"
ACTIONS_PATH = "/trading/corporate-actions/?instrumentCode=all-stocks&fromDate={from_date}&thruDate={thru_date}"


def trading_day(day: dt.date) -> dt.date:
    """The most recent weekday on or before `day` (the JSE doesn't trade at weekends)."""
    if day.weekday() == 5:
        return day - dt.timedelta(days=1)
    if day.weekday() == 6:
        return day - dt.timedelta(days=2)
    return day


def listings_due(state: store.State, quotes: dict[str, Quote] | None, markets: dict[int, str],
                 today: dt.date, every_days: int, force: bool) -> tuple[list[int], str | None]:
    """Which listing markets to fetch this run, and why. ([], None) means none."""
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
    due = [code for code in markets if code in retry or code in aged]
    return due, "; ".join(reasons) or None


def actions_from_date(status: store.DatasetStatus, window_days: int, backfill_from: dt.date) -> dt.date:
    """Start of the corporate-actions query.

    Backfill until the first successful fetch. After that, look back `window_days` from the last
    successful fetch, so an outage of any length is caught up on the next good run.
    """
    if status.as_of is None:
        return backfill_from
    return max(backfill_from, status.as_of - dt.timedelta(days=window_days))


class _WarningCollector(logging.Handler):
    """Copies parser warnings (missing columns, skipped rows) into the run report."""

    def __init__(self) -> None:
        super().__init__(logging.WARNING)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


@dataclass
class Report:
    trade_date: dt.date
    requests: int
    errors: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    listings_refresh: str | None = None
    counts: dict[str, int] = field(default_factory=dict)

    @property
    def exit_code(self) -> int:
        return 1 if self.errors else 0

    def summary_markdown(self) -> str:
        lines = [
            f"## JSE scrape for {self.trade_date.isoformat()}",
            "",
            f"- Requests to the JSE site: {self.requests}",
            f"- Listings refreshed: {self.listings_refresh or 'no'}",
            f"- Instruments: {self.counts.get('instruments', 0)} ({self.counts.get('listed', 0)} listed)",
            f"- Quotes in this run: {self.counts.get('quotes', 0)}",
            f"- Corporate actions stored: {self.counts.get('corporate_actions', 0)}",
        ]
        if self.errors:
            lines += ["", "### Errors", *(f"- **{name}**: {message}" for name, message in sorted(self.errors.items()))]
        if self.warnings:
            lines += ["", "### Warnings", *(f"- {warning}" for warning in self.warnings)]
        return "\n".join(lines)


def _describe(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"


def run(config: Config, site_dir: Path, fetcher: Fetcher, *, now: dt.datetime,
        refresh_listings: bool = False) -> Report:
    collector = _WarningCollector()
    parse_log = logging.getLogger("jamstockex.parse")
    parse_log.addHandler(collector)
    try:
        return _run(config, site_dir, fetcher, now=now, refresh_listings=refresh_listings, collector=collector)
    finally:
        parse_log.removeHandler(collector)


def _run(config: Config, site_dir: Path, fetcher: Fetcher, *, now: dt.datetime, refresh_listings: bool,
         collector: _WarningCollector) -> Report:
    today = now.astimezone(ZoneInfo(config.output.timezone)).date()
    trade_date = trading_day(today)
    state = store.load(site_dir, config.output.api_version)
    for label in set(state.markets) - set(config.markets.values()):
        del state.markets[label]  # market removed from config.toml
    result = store.ScrapeResult(trade_date=trade_date)

    # 1. Quotes first, so an unknown instrument can trigger a listings refresh in the same run.
    try:
        html = fetcher.get(QUOTES_PATH.format(market=config.combined_market, date=trade_date.isoformat()))
        result.quotes, result.indices = parse_trade_quotes(html, trade_date)
    except (FetchError, ParseError) as exc:
        log.error("Trade quotes failed: %s", exc)
        result.errors["quotes"] = result.errors["indices"] = _describe(exc)

    # 2. Listings, only the markets that are due.
    due, reason = listings_due(state, result.quotes, config.markets, today,
                               config.refresh.listings_every_days, refresh_listings)
    if due:
        log.info("Refreshing listings for %d market(s): %s", len(due), reason)
        result.listings = {}
        result.listings_full = len(due) == len(config.markets)
        for code in due:
            label = config.markets[code]
            try:
                result.listings[label] = parse_listed_companies(fetcher.get(LISTINGS_PATH.format(market=code)), label)
            except (FetchError, ParseError) as exc:
                log.error("Listings for market %s failed: %s", code, exc)
                result.listing_errors[label] = _describe(exc)
        if result.listing_errors:
            result.errors["listings"] = "; ".join(f"{label}: {e}" for label, e in result.listing_errors.items())

    # 3. Corporate actions: backfill until the first success, then from the last success minus the window.
    from_date = actions_from_date(state.status["corporate_actions"], config.refresh.corporate_actions_window,
                                  config.refresh.backfill_from)
    thru_date = today + dt.timedelta(days=config.refresh.corporate_actions_forward)
    try:
        html = fetcher.get(ACTIONS_PATH.format(from_date=from_date.isoformat(), thru_date=thru_date.isoformat()))
        result.actions = parse_corporate_actions(html)
    except (FetchError, ParseError) as exc:
        log.error("Corporate actions failed: %s", exc)
        result.errors["corporate_actions"] = _describe(exc)

    warnings = store.merge(state, result, today=today, now=now,
                           max_listing_drop_pct=config.refresh.max_listing_drop_pct)
    store.write(state, site_dir, api_version=config.output.api_version, now=now)

    return Report(
        trade_date=trade_date,
        requests=fetcher.request_count,
        errors=dict(result.errors),
        warnings=collector.messages + warnings,
        listings_refresh=reason,
        counts={
            "instruments": len(state.companies),
            "listed": sum(1 for c in state.companies.values() if c.listed),
            "quotes": len(result.quotes or {}),
            "corporate_actions": len(state.actions),
        },
    )
```

- [ ] **Step 4: Implement `jamstockex/__main__.py`**

```python
"""CLI: python -m jamstockex build --out site [--config config.toml] [--refresh-listings]"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import os
import sys
from pathlib import Path

from jamstockex.build import run
from jamstockex.config import ConfigError, load_config
from jamstockex.fetch import Fetcher

log = logging.getLogger("jamstockex")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m jamstockex",
                                     description="Scrape JSE end-of-day data into a static JSON API.")
    commands = parser.add_subparsers(dest="command", required=True)
    build_cmd = commands.add_parser("build", help="fetch what's due, merge into --out, write the v2 tree")
    build_cmd.add_argument("--out", required=True, type=Path, help="site directory (a checkout of the data branch)")
    build_cmd.add_argument("--config", default=Path("config.toml"), type=Path)
    build_cmd.add_argument("--refresh-listings", action="store_true", help="refresh listed companies now")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        config = load_config(args.config)
    except ConfigError as exc:
        log.error("%s", exc)
        return 2

    report = run(config, args.out, Fetcher(config.source), now=dt.datetime.now(dt.timezone.utc),
                 refresh_listings=args.refresh_listings)
    summary = report.summary_markdown()
    print(summary)
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as handle:
            handle.write(summary + "\n")
    return report.exit_code


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_build.py -q`, then the full suite with `.venv/bin/pytest -q`.
Expected: `19 passed`, and the full suite all green.

- [ ] **Step 6: Commit**

```bash
git add jamstockex/build.py jamstockex/__main__.py tests/test_build.py
git commit -m "feat: add build orchestration and python -m jamstockex CLI" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 13: GitHub Actions workflows

**Files:**
- Create: `.github/workflows/scrape.yml`, `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: the CLI from Task 12 (exit codes 0, 1 and 2).

- [ ] **Step 1: Write `.github/workflows/ci.yml`**

```yaml
name: ci
on:
  push:
    branches: [main, develop]
  pull_request:
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
      - run: pip install -r requirements-dev.txt
      - run: pytest -q
```

- [ ] **Step 2: Write `.github/workflows/scrape.yml`**

```yaml
name: scrape
on:
  schedule:
    - cron: "30 22 * * 1-5"   # 17:30 America/Jamaica (UTC-5, no DST), Mon-Fri
  workflow_dispatch:
    inputs:
      refresh_listings:
        description: "Force a listed-companies refresh"
        type: boolean
        default: false
concurrency:
  group: scrape
  cancel-in-progress: false
permissions:
  contents: write
jobs:
  scrape:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
      - run: pip install -r requirements.txt
      - name: Check out the data branch into site/
        run: |
          if git ls-remote --exit-code --heads origin data > /dev/null; then
            git fetch --depth=1 origin data
            git worktree add -B data site origin/data
          else
            git worktree add --orphan -b data site
            touch site/.nojekyll
          fi
      - name: Build
        id: build
        continue-on-error: true
        run: python -m jamstockex build --out site ${{ inputs.refresh_listings && '--refresh-listings' || '' }}
      - name: Commit and push data
        if: always()
        working-directory: site
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git add -A
          if git diff --cached --quiet; then
            echo "No changes to publish"
            exit 0
          fi
          git commit -m "data: $(TZ=America/Jamaica date +%F)"
          git push origin data
      - name: Fail if the build reported errors
        if: steps.build.outcome == 'failure'
        run: |
          echo "::error::The build reported errors. See the Build step log and the run summary."
          exit 1
```

- [ ] **Step 3: Validate the YAML syntax**

PyYAML is installed into the local venv only for this check; it is not added to any requirements file.

```bash
.venv/bin/pip install -q pyyaml
.venv/bin/python -c "import sys, yaml; [print('ok', f) for f in sys.argv[1:] if yaml.safe_load(open(f))]" .github/workflows/ci.yml .github/workflows/scrape.yml
```

Expected: `ok .github/workflows/ci.yml` and `ok .github/workflows/scrape.yml`.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/ci.yml .github/workflows/scrape.yml
git commit -m "ci: add offline test workflow and daily scrape-and-publish workflow" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 14: License, notices, README, CLAUDE.md, and removing v1

**Files:**
- Replace: `LICENSE`, `README.md`, `CLAUDE.md`
- Create: `NOTICE`, `TERMS.md`
- Delete: `database.py`, `scheduler.py`, `main.py`, `helper.py`, `urls.py`, `constants.py`, `custom_logger.py`, `services/`, `ua_file.txt`, `Procfile`, `Procfile.windows` (the root `__init__.py` was removed in Task 2)

**Interfaces:** none.

- [ ] **Step 1: Write `LICENSE` from the official PolyForm text and verify it**

```bash
{
  echo "Required Notice: Copyright (c) 2022-2026 Stephen Clarke (https://github.com/sdclarkelab)"
  echo
  gh api repos/polyformproject/polyform-licenses/contents/PolyForm-Noncommercial-1.0.0.md -H "Accept: application/vnd.github.raw"
} > LICENSE
tail -n +3 LICENSE | shasum -a 256
head -3 LICENSE
```

Expected checksum: `c0ea4a896d2c8c394b29f9427589996db826cd501c512279ff0ed3ef48fabbe5` (verified 2026-11-09). The first line must be the `Required Notice:` line, and the third must be `# PolyForm Noncommercial License 1.0.0`. If the checksum differs, stop and show the diff to the user. The license text must be unmodified.

- [ ] **Step 2: Write `NOTICE`**

```text
jamstockex-scraper
Copyright (c) 2022-2026 Stephen Clarke (https://github.com/sdclarkelab)
All rights not expressly granted by the license are reserved.

SOFTWARE LICENSE

From version 2.0.0, the source code is licensed under the PolyForm
Noncommercial License 1.0.0 (see LICENSE). The code is source-available,
not open source: you may use, copy, modify and share it for noncommercial
purposes only. Commercial use requires a separate written license from the
copyright holder. To ask for one, open an issue at
https://github.com/sdclarkelab/jamstockex-scraper/issues

Versions up to and including the v1.0 tag were released under the MIT
License and remain available under it.

MARKET DATA

The market data that this software collects and publishes is the property
of the Jamaica Stock Exchange Limited and its subsidiaries (the "JSE
Group") and their licensors. It is not covered by the license above, and
no rights in it are granted. Use of the published data is governed by
TERMS.md.

NO AFFILIATION

This project is independent. It is not affiliated with, endorsed by, or
sponsored by the JSE Group. "Jamaica Stock Exchange" and "JSE" are marks
of the JSE Group and are used here only to describe the source of the data.

Required Notice: Copyright (c) 2022-2026 Stephen Clarke (https://github.com/sdclarkelab)
```

- [ ] **Step 3: Write `TERMS.md`**

```markdown
# API Terms of Use

_Last updated: 9 November 2026_

These terms apply to the data published by **jamstockex-scraper** at
`https://sdclarkelab.github.io/jamstockex-scraper/` (the "Service"), run by
Stephen Clarke ("I", "me"). By using the Service you agree to these terms.
If you don't agree, don't use the Service.

1. **Noncommercial use only.** You may use the Service only for personal,
   educational, research or other noncommercial purposes, including within
   noncommercial organisations such as charities, schools and public bodies.
   Commercial use is not permitted. That includes use in, or to support, a
   product, a paid service or a for-profit business. Commercial use of Jamaica
   Stock Exchange market data needs a licence from the Jamaica Stock Exchange.

2. **The data belongs to the JSE Group.** All market data on the Service is
   collected from the public website of the Jamaica Stock Exchange Limited.
   All rights in it belong to the Jamaica Stock Exchange Limited, its
   subsidiaries (the "JSE Group") and their licensors. The Service grants you
   no rights in the data, and you are responsible for complying with the JSE
   Group's own terms.

3. **Attribution.** If you display or share data from the Service, credit it
   as: "Data: Jamaica Stock Exchange, via jamstockex-scraper".

4. **No affiliation.** The Service is independent. It is not affiliated with,
   endorsed by or sponsored by the JSE Group. "Jamaica Stock Exchange" and
   "JSE" are used only to describe the source of the data.

5. **End-of-day data, provided as is.** The data is end-of-day only, not
   real-time. It may be late, incomplete or wrong, and the Service may be
   unavailable at any time. Check `status.json` for freshness. The Service is
   provided "as is" and "as available", without warranty of any kind, express
   or implied, including warranties of accuracy, timeliness, merchantability,
   fitness for a particular purpose and non-infringement.

6. **Not financial advice.** Nothing on the Service is investment, financial,
   legal or tax advice, or a recommendation, offer or solicitation to buy or
   sell any security. You use the data at your own risk.

7. **Fair use.** Cache responses, and don't request any endpoint more than once
   an hour. The data changes once per trading day. Don't use the Service, or
   this project's code, in a way that overloads or disrupts the JSE website.

8. **Changes and withdrawal.** I may change the Service, its data format or
   these terms, or suspend or withdraw the Service, at any time without
   notice. Where practical, breaking format changes are published under a new
   version path (for example `/v3/`).

9. **Limitation of liability.** To the maximum extent permitted by law, I am
   not liable for any direct, indirect, incidental, special, consequential or
   punitive damages, or for any loss of profits, data or opportunity, arising
   from your use of, or inability to use, the Service or the data, even if I
   have been told such damages are possible.

10. **Governing law.** These terms are governed by the laws of Jamaica.

11. **Contact.** Open an issue at
    https://github.com/sdclarkelab/jamstockex-scraper/issues

The source code is licensed separately; see `LICENSE` and `NOTICE`.
```

- [ ] **Step 4: Replace `README.md`**

````markdown
# jamstockex-scraper

Free, unofficial **end-of-day data from the Jamaica Stock Exchange (JSE)**, published as static JSON.

A scheduled GitHub Actions job scrapes the JSE website once per trading day and publishes the results
to GitHub Pages. There's no server and no database, and your requests never reach the JSE.

> **Not affiliated with or endorsed by the Jamaica Stock Exchange.** The data belongs to the JSE Group.
> Not financial advice. Noncommercial use only. See [License and data](#license-and-data).

## API

Base URL: `https://sdclarkelab.github.io/jamstockex-scraper/v2/`

| Endpoint | Contents |
|---|---|
| `index.json` | Endpoint list, attribution, license and terms |
| `status.json` | Freshness of each dataset: `as_of`, `fetched_at`, `stale`, `last_error` |
| `stocks.json` | All listed instruments with company details and latest quote |
| `stocks/{instrument_code}.json` | One instrument, with its `dividends` and `corporate_actions` |
| `indices.json` | Market indices |
| `corporate-actions.json` | All corporate actions (dividends, splits, bonus issues, …) with a `type` |
| `dividends.json` | Dividends only |

```shell
curl -s https://sdclarkelab.github.io/jamstockex-scraper/v2/stocks.json | python3 -m json.tool | head -40
```

Every file has the same envelope:

```json
{ "meta": { "api_version": "v2", "as_of": "2026-11-09", "generated_at": "2026-11-09T22:31:04Z",
            "stale": false, "source": "Data: Jamaica Stock Exchange Limited …", "terms": "…", "license": "…" },
  "data": … }
```

Conventions:
- **Keys:** files are keyed by `instrument_code`. A company listed in JMD and USD has one symbol but two instruments.
- **Formats:** keys are `snake_case`; dates are `YYYY-MM-DD`; timestamps are UTC. Unknown values are `null`, never `0`.
- **Freshness:** data updates Monday–Friday at about 17:30 Jamaica time. If a fetch fails, the last good data stays and `stale` becomes `true`.
- **Versioning:** new fields may appear in `v2`. Breaking changes will go to `/v3/`.
- **Fair use:** please cache responses and poll at most once an hour.

## How it works

```
JSE website ──► GitHub Actions (Mon–Fri 17:30) ──► JSON on the `data` branch ──► GitHub Pages ──► you
                  └─ reads the previous JSON back as its store, merges, validates, writes
```

A typical day makes **2 requests** to the JSE site: trade quotes and corporate actions. Listed companies
(4 requests) are refreshed weekly, or straight away if a new instrument appears in the quotes. The scraper
uses one honest User-Agent, waits between requests, and never retries when the site blocks it.

## Run locally

```shell
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
pytest                                   # offline; never contacts the JSE
python -m jamstockex build --out site    # real run: makes requests to the JSE site
```

Settings live in `config.toml`: source URL, User-Agent, timeouts and retries, markets, refresh windows,
and the delisting guard. The schedule is in `.github/workflows/scrape.yml`.

Exit codes: `0` = everything that was due updated; `1` = at least one dataset failed (the rest were still
published, and `status.json` says what failed); `2` = invalid config.

## Operations

- **Manual run:** Actions → scrape → Run workflow (tick *refresh_listings* to force a listings refresh).
- **Failures:** a failed run turns red and GitHub emails the repository owner. The run summary lists errors.
- **Site layout changes** show up as a `ParseError` naming the page and header. Add the new header name
  to the alias table in `jamstockex/parse.py`.
- **Takedown:** delete the `data` branch and disable GitHub Pages.

## License and data

- **Code:** [PolyForm Noncommercial 1.0.0](LICENSE). Copyright (c) 2022-2026 Stephen Clarke. It's free for
  noncommercial use; commercial use needs a separate license, so open an issue to ask.
  Versions up to `v1.0` were MIT and remain so. See [NOTICE](NOTICE).
- **Data:** the property of the Jamaica Stock Exchange Limited / JSE Group. It is not covered by the code license.
  Use of the API is governed by the [API Terms of Use](TERMS.md).
````

- [ ] **Step 5: Replace `CLAUDE.md`**

````markdown
# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Scrapes Jamaica Stock Exchange end-of-day data and publishes it as a static JSON API (`/v2/`) on GitHub
Pages. There's no server and no database: a GitHub Actions cron job runs the build and commits its
output to the `data` branch, and the previously published JSON on that branch is the persistent store.

Spec: `docs/superpowers/specs/2026-11-09-v2-static-api-design.md`.

## Commands

```shell
python3.12 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest -q                                   # offline test suite
.venv/bin/pytest tests/test_build.py::test_trading_day -q   # single test
.venv/bin/python -m jamstockex build --out site       # real run against the JSE site
```

## Architecture

- `config.py`: loads `config.toml` (every tunable lives there; the cron schedule is in `scrape.yml`).
- `fetch.py`: `Fetcher` sends one honest User-Agent, waits between requests, and retries 5xx and timeouts.
  On 403/429 or a CloudFront page it raises `BlockedError` and refuses all further requests that run.
- `parse.py`: finds tables by **normalised header name** through alias tuples (`LISTING_COLUMNS`,
  `QUOTE_COLUMNS`, `INDEX_COLUMNS`, `ACTION_COLUMNS`). Value parsers return `None`, never 0.
- `store.py`: `load` → `merge` → `write` of the v2 tree, plus the delisting guard, stale tracking,
  corporate-action dedupe, and symbol → instrument_code mapping.
- `build.py`: `run()` fetches quotes first, then listings only if they're due (weekly, an unknown
  instrument, or `--refresh-listings`), then corporate actions (a backfill on the first run, then a
  short window). Failed datasets keep their stored data and are marked stale. Exit code 1 if any failed.

## Rules

- **Never rotate User-Agents or work around a block** (JSE T&C §8.2).
- **No `jamstockex.com` URLs** in API output or docs (JSE T&C §8.5.3). Name the source in plain text.
- **Never commit real JSE pages.** `tests/fixtures/real/` is gitignored; committed fixtures are synthetic.
- **Tests must stay offline.**
- **JSON output:** minified, sorted keys, `null` for unknown values. Breaking changes go to `/v3/`.
- **License:** code is PolyForm Noncommercial 1.0.0; the data belongs to the JSE Group (see NOTICE, TERMS.md).
````

- [ ] **Step 6: Delete the v1 files and check nothing still references them**

```bash
git rm -q -r database.py scheduler.py main.py helper.py urls.py constants.py custom_logger.py services ua_file.txt Procfile Procfile.windows
rm -rf __pycache__
grep -rn -E "pymongo|apscheduler|ua_file|custom_logger|scraper_factory" --include='*.py' --include='*.md' --include='*.txt' --include='*.yml' . \
  | grep -v -E '^\./(\.venv|docs/superpowers)/' || echo "no stale references"
.venv/bin/pytest -q
```

Expected: `no stale references`, and the full suite all green.

- [ ] **Step 7: Check that the docs contain no JSE links**

```bash
grep -n -i -E "https?://[^ )]*jamstockex\.com" README.md TERMS.md NOTICE CLAUDE.md || echo "no JSE links"
```

Expected: `no JSE links`.

- [ ] **Step 8: Commit**

```bash
git add LICENSE NOTICE TERMS.md README.md CLAUDE.md
git commit -m "feat!: relicense v2 under PolyForm Noncommercial, add data notices, remove v1 MongoDB scraper" \
  -m "BREAKING CHANGE: MongoDB output, scheduler.py and the Procfile are removed. Data is now published as static JSON under /v2/." \
  -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 15: Go live (soft launch)

**Every step here is outward-facing. Ask the user for approval before each one.**

**Files:** none.

- [ ] **Step 1: Final local verification**

```bash
.venv/bin/pytest -q
git status --short          # expect only untracked jamstockex.log (if present)
git log --oneline main..HEAD
```

- [ ] **Step 2: Push the branch and open a PR into `main` (after approval)**

Scheduled workflows only run from the default branch, so v2 has to land on `main`. If the user prefers to go through `develop` first, follow their flow.

```bash
git push -u origin feat/v2-static-api
gh pr create --base main --head feat/v2-static-api --title "v2: static JSON API on GitHub Pages" --body "$(cat <<'EOF'
## Summary
- Replaces the MongoDB scraper with `python -m jamstockex build`, which publishes a static `/v2/` JSON API to GitHub Pages via a weekday GitHub Actions job (~2 requests/day to the JSE site).
- Header-name table parsing, null-safe values, a delisting guard, stale tracking, and corporate-action dedupe; no User-Agent rotation, and a block is never retried.
- Relicenses the code (v2+) under PolyForm Noncommercial 1.0.0; adds NOTICE and TERMS.md stating the data belongs to the JSE Group. v1.0 stays MIT.

## Test plan
- [ ] `pytest -q` passes in CI (offline)
- [ ] Real-page parser tests pass locally (`tests/test_parse_real.py`)
- [ ] After merge: manual `scrape` run succeeds and Pages serves `/v2/index.json`

Spec: `docs/superpowers/specs/2026-11-09-v2-static-api-design.md`

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
gh pr checks --watch
```

Expected: the `ci` check passes. The user reviews and merges the PR.

- [ ] **Step 3: Run the first scrape manually after the merge (with approval)**

```bash
gh workflow run scrape.yml --ref main -f refresh_listings=true
gh run list --workflow scrape.yml --limit 1 --json databaseId,status,event   # repeat until the workflow_dispatch run appears
RUN_ID=$(gh run list --workflow scrape.yml --limit 1 --json databaseId -q '.[0].databaseId')
gh run watch "$RUN_ID" --exit-status
git fetch origin data && git ls-tree -r --name-only origin/data | head -20
```

Expected: the run is green, and `origin/data` contains `.nojekyll` and `v2/*.json`. If the run is red, read the run summary. A `BlockedError` means STOP and tell the user; a `ParseError` means go back to Task 9 Step 4.

- [ ] **Step 4: Enable GitHub Pages from the `data` branch (with approval)**

```bash
gh api -X POST repos/sdclarkelab/jamstockex-scraper/pages -f "source[branch]=data" -f "source[path]=/"
gh api repos/sdclarkelab/jamstockex-scraper/pages -q .status   # repeat until it prints "built"
for f in index status stocks indices corporate-actions dividends; do
  printf '%-20s ' "$f"; curl -s -o /dev/null -w '%{http_code}\n' "https://sdclarkelab.github.io/jamstockex-scraper/v2/$f.json"
done
curl -s https://sdclarkelab.github.io/jamstockex-scraper/v2/status.json | python3 -m json.tool
```

Expected: every endpoint returns `200`, and every dataset in `status.json` has `"stale": false`. Pages may take a few minutes on first deploy; retry before concluding anything.

- [ ] **Step 5: Tag `v2.0.0` on the merge commit (with approval)**

```bash
git fetch origin main
git tag -a v2.0.0 origin/main -m "v2.0.0: static JSON API, PolyForm Noncommercial license"
git push origin v2.0.0
```

- [ ] **Step 6: Soft-launch reminders for the user**

Tell the user:
- **Soft launch:** the API is live but should **not be announced** until the JSE question is settled.
- **Watch the scheduled run** on the next weekday at 17:30 Jamaica time.
- **Check after 60 days (by 2027-01-08)** that scheduled runs are still enabled. GitHub disables them after 60 days without repository activity. If they've stopped, add a monthly keepalive workflow.
- **Takedown:** delete the `data` branch and disable Pages.

---

## Self-review notes

**Spec coverage:**

| Spec section | Task |
|---|---|
| §2 legal constraints (honest UA, no block circumvention, no JSE links, notices) | Tasks 4, 6, 10, 14 |
| §3.1 layout and removals | Tasks 2, 14 |
| §3.2 modules | Tasks 2–12 |
| §3.3 due logic | Task 12 |
| §4 config | Task 2 |
| §5 API contract | Tasks 3, 10 |
| §6.1 failure classes | Tasks 4, 12 |
| §6.2 merge rules | Task 11 |
| §6.3 logging and summary | Task 12 |
| §7 workflows and Pages | Tasks 13, 15 |
| §8 legal files | Task 14 |
| §9 testing | each task, plus Task 9 for real pages |
| §10 gate and risks | Tasks 1, 15 |

**Review revision (2026-11-09):** fixes 1–8 from the plan review. The plan's code was extracted and run: 151 passed, 22 real-page tests skipped.
- Fix 1, quotes ParseError: Task 7.
- Fix 2, unmatched codes: Tasks 10–12.
- Fixes 3 and 4, per-market status and delisting guard: Tasks 10–12.
- Fix 5, column warnings in the summary: Tasks 5–8 and 12.
- Fix 6, corporate-actions catch-up: Task 12.
- Fix 7, unchanged files not rewritten: Task 10.
- Fix 8, broader probe and real-page checks: Tasks 1 and 9.

**Type consistency:** checked across tasks.
- `ScrapeResult` fields (`listings` dict, `listing_errors`, `listings_full`), `merge(..., today, now, max_listing_drop_pct)`, `write(..., api_version, now)` and `load(site_dir, api_version)` are used identically in Tasks 10, 11 and 12.
- `Fetcher.request_count` and `blocked` are mirrored by `FakeFetcher`.
- `parse_trade_quotes` returns a `(dict, list)` tuple everywhere it's used.
