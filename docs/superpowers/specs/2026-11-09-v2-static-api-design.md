# v2: Static JSON API for JSE Market Data — Design

- **Date:** 2026-11-09
- **Status:** Approved in brainstorming, pending spec review
- **Release:** `v2.0.0` (the existing `v1.0` tag is untouched)

## 1. Goal

Replace the MongoDB-backed scraper with a minimal, configurable scraper that publishes a **free, always-available, public static JSON API** of Jamaica Stock Exchange end-of-day data. It must:

- cost $0 to host and never cold-start;
- keep traffic to jamstockex.com to the minimum (typically 2 requests per trading day);
- be easy to maintain (one entry point, one config file, offline tests);
- adopt and improve on the parsing approach in `sdclarkelab/jamstock-portfolio-tracker` `backend/app/scraper/jse_scraper.py`;
- relicense the code (v2 onward) under PolyForm Noncommercial 1.0.0 and state clearly that the data belongs to the JSE Group.

### Non-goals

- Server-side querying, filtering or search. Clients filter the published files.
- Daily history endpoints. The `data` branch's git history keeps past snapshots, so history can be added later.
- Real-time or intraday data.
- Backward compatibility with the old MongoDB schema or `jamstockex-api`. There are no known users; both are retired.
- Drafting the permission email to the JSE. Deferred at the user's request.

## 2. Legal and launch constraints

Findings from the JSE Terms & Conditions (text supplied by the user, 2026-11-09) and Disclaimer page:

| Clause | Constraint on this project |
|---|---|
| §11 Intellectual Property: JSE Group claims "any other data or information contained on the Site" | The data is not ours and cannot be licensed by us. Every output file carries a JSE ownership notice. |
| Disclaimer: no license to content without express written permission | Republishing is in a gray zone, hence a **soft launch** (below). |
| §8.2 Acceptable Use: no circumventing, impairing or overloading systems | Minimal request volume, delays between requests, **one honest User-Agent (no rotation)**, and **never work around a block**. |
| §8.3: the JSE may monitor and terminate access | Blocks must degrade gracefully: keep last good data and mark it stale. |
| §8.5.3: no linking to the Site without prior written consent | **No links to jamstockex.com in API output.** The source is named in plain text only. |
| §6: no recommendation or advice | TERMS.md repeats the not-financial-advice notice. |
| §11 Trademarks | No JSE logos; name used descriptively only; no implied endorsement. |

**Launch mode: soft launch.** Deploy v2 with all notices in place but do not announce or promote the URL. (GitHub Pages on a public repo is publicly reachable; it is simply not advertised.) If the JSE objects, delete the `data` branch and disable Pages.

## 3. Architecture

```
JSE site ──► GitHub Actions (cron, ~2 req/day) ──► JSON on `data` branch ──► GitHub Pages CDN ──► API users
                     ▲                                     │
                     └──── previous data read back as the store ┘
```

User traffic never reaches the JSE. The previously published JSON on the `data` branch is the persistent store: each run loads it, merges in the new scrape, validates, and writes it back.

### 3.1 Repository layout (main branch)

```
jamstockex/
  __init__.py
  __main__.py    # CLI: python -m jamstockex build --out site [--refresh-listings]
  config.py      # loads config.toml (tomllib) into a frozen dataclass
  fetch.py       # polite HTTP client; raises BlockedError / FetchError
  parse.py       # header-matched table helpers, value parsers, 3 page parsers; raises ParseError
  models.py      # dataclasses: Company, Quote, Index, CorporateAction
  store.py       # load previous JSON, merge, validate, write the v2 file tree
config.toml
requirements.txt        # requests, beautifulsoup4
requirements-dev.txt    # pytest
tests/
  fixtures/             # saved HTML pages
  test_parse.py  test_store.py  test_fetch.py  test_build.py
.github/workflows/
  scrape.yml  ci.yml
LICENSE  NOTICE  TERMS.md  README.md  CLAUDE.md
```

**Removed:** `database.py`, `scheduler.py`, `main.py`, `helper.py`, `urls.py`, `constants.py`, `custom_logger.py`, `services/`, `ua_file.txt`, `Procfile`, `Procfile.windows`, root `__init__.py`, and all unused packages in `requirements.txt` (pymongo, APScheduler, selenium, trio, random-user-agent, pytz, python-dotenv, etc.). `CLAUDE.md` is updated to describe v2.

**Runtime:** Python 3.12. Dependencies: `requests` and `beautifulsoup4` (`html.parser`; no lxml).

### 3.2 Module responsibilities

- **`config.py`:** `load_config(path="config.toml") -> Config`. A frozen dataclass whose fields mirror §4. It validates types and ranges and fails fast on bad config.
- **`fetch.py`:** `Fetcher(config)` with `get(path) -> str`.
  - Sends the configured User-Agent and timeout.
  - Sleeps a random `delay_s` interval before every request except the first.
  - Retries `retries` times with exponential backoff on connection errors, timeouts and 5xx responses, then raises `FetchError`.
  - On 403 or 429, or a CloudFront "Request blocked" body, raises `BlockedError` immediately, without retrying.
  - After any `BlockedError` the fetcher refuses all further requests in that process.
  - Counts the requests it makes, for the run summary.
- **`parse.py`:**
  - **Helpers:** `normalize_header`, `header_index(table)`, `find_table(soup, required_headers)`, `cell_text`, `cell_href`, `instrument_code_from_href`.
  - **Value parsers:** `to_decimal`, `to_int`, `parse_date` (formats `%a %d %b %Y`, `%d %b %Y`, `%Y-%m-%d`), `parse_amount` (`"JMD 0.1200"` → `("JMD", Decimal("0.12"))`). Invalid input returns `None`, never 0.
  - **Page parsers:** `parse_listed_companies(html, market_label) -> list[Company]`, `parse_trade_quotes(html, date) -> (list[Quote], list[Index])`, `parse_corporate_actions(html) -> list[CorporateAction]`.
  - Columns are matched by normalized header name, with a small alias table per field. A required table or header that is missing raises `ParseError(page, missing)`.
  - Original letter case is kept (v1 lowercased everything).
- **`models.py`:** plain dataclasses with `Decimal`/`date` fields and a `to_json()` method for each.
- **`store.py`:**
  - `load(site_dir) -> State` reads the previous v2 files; an empty or missing directory gives an empty state.
  - `merge(state, scrape_result, config, today) -> State` applies the rules in §6.
  - `write(state, site_dir)` emits the file tree in §5.
  - JSON is minified, UTF-8, with sorted keys for stable diffs.
- **`__main__.py`:**
  - Orchestration: load config and state, decide what is due (§3.3), fetch and parse each due dataset independently, merge, write.
  - Logs a summary and appends it to `$GITHUB_STEP_SUMMARY` when that is set.
  - Exits `0` if every due dataset succeeded, `1` if any failed or was blocked.

### 3.3 What is fetched when

| Dataset | Due when | Requests |
|---|---|---|
| Trade quotes + indices (`/trading/trade-quotes/?market=50&date=<trading day>`) | every run | 1 |
| Corporate actions (`/trading/corporate-actions/?instrumentCode=all-stocks&fromDate=&thruDate=`) | every run | 1 |
| Listed companies (`/listings/listed-companies/?market=<code>` × 4) | last refresh ≥ `listings_every_days` ago, **or** quotes contain an unknown `instrument_code`, **or** `--refresh-listings`, **or** no stored listings | 4 |

- **Order:** quotes are fetched first, so an unknown instrument can trigger the listings refresh in the same run.
- **Corporate-actions window:**
  - normal run: `today − corporate_actions_window` through `today + corporate_actions_forward`
  - first run, or no stored actions: `backfill_from` through `today + corporate_actions_forward`
- **Trading day:** today in `America/Jamaica` (`zoneinfo`), moved back to Friday on a weekend. This fixes v1's mislabelling of local time as UTC.

## 4. Configuration (`config.toml`)

```toml
[source]
base_url   = "https://www.jamstockex.com"
user_agent = "jamstockex-scraper/2.0 (+https://github.com/sdclarkelab/jamstockex-scraper)"
timeout_s  = 20
retries    = 3
delay_s    = [2, 5]

[markets]                 # listing market code = label
31 = "Main Market"
22 = "Junior Market"
51 = "Bond Market"
49 = "USD Market"

[quotes]
combined_market = 50

[refresh]
listings_every_days       = 7
corporate_actions_window  = 30    # days back on normal runs
corporate_actions_forward = 365   # days ahead (announced actions)
backfill_from             = "2026-01-01"
max_listing_drop_pct      = 20

[output]
api_version = "v2"
timezone    = "America/Jamaica"
```

The output directory is passed on the CLI (`--out`). The cron schedule lives only in `scrape.yml`.

## 5. API contract

**Base URL:** `https://sdclarkelab.github.io/jamstockex-scraper/v2/`

| Path | `data` |
|---|---|
| `/v2/index.json` | object: endpoint list, attribution, license, terms URL |
| `/v2/status.json` | object keyed by dataset (`listings`, `quotes`, `indices`, `corporate_actions`): `{as_of, fetched_at, stale, last_error}` |
| `/v2/stocks.json` | array of stock entries (with `quote`) |
| `/v2/stocks/{instrument_code}.json` | one stock entry plus `dividends` and `corporate_actions` arrays |
| `/v2/indices.json` | array of `{name, date, value, change, change_pct, volume}` |
| `/v2/corporate-actions.json` | array of all corporate actions |
| `/v2/dividends.json` | the `type == "dividend"` subset |

**Envelope (every file):**

```json
{
  "meta": {
    "api_version": "v2",
    "as_of": "2026-11-09",
    "generated_at": "2026-11-09T22:31:04Z",
    "stale": false,
    "source": "Data: Jamaica Stock Exchange Limited (jamstockex.com). All rights in the data belong to the JSE Group.",
    "terms": "https://github.com/sdclarkelab/jamstockex-scraper/blob/main/TERMS.md",
    "license": "Code: PolyForm Noncommercial 1.0.0"
  },
  "data": {}
}
```

- `as_of` is the trading date of that file's data.
- `stale` is true if the dataset's latest due fetch failed.
- Aggregate files use their dataset's status.
- Per-stock files use `stale = listings.stale OR quotes.stale` and `as_of = quote date`, or the listings `as_of` if the instrument has no quote yet.

**Stock entry:**

```json
{
  "instrument_code": "NCBFG-JMD", "symbol": "NCBFG",
  "name": "NCB Financial Group Limited", "market": "Main Market",
  "currency": "JMD", "sector": "Finance", "type": "Ordinary",
  "website": "https://www.myncb.com",
  "listed": true, "listed_since": "2026-11-09", "delisted_on": null,
  "quote": { "date": "2026-11-09", "close": 112.50, "change": -1.25, "change_pct": -1.10, "volume": 48213 }
}
```

**Corporate action:**

```json
{ "instrument_code": "NCBFG-JMD", "symbol": "NCBFG", "type": "dividend",
  "amount": 0.75, "currency": "JMD",
  "record_date": "2026-11-20", "ex_date": "2026-11-18", "payment_date": "2026-12-05" }
```

**Conventions:**

- **Identifiers:** entries are keyed by `instrument_code` (dual listings share a symbol). Its real format is confirmed against live HTML during implementation; the example is illustrative. File names use the code with characters outside `[A-Za-z0-9._-]` replaced by `-`.
- **Corporate actions → instruments:** the corporate-actions page gives a symbol. It is mapped to an `instrument_code` through the listings; if one symbol maps to several codes, the action's currency picks the code; if it is still ambiguous or unknown, `instrument_code` is `null` and the action appears only in the aggregate files.
- **Field names and values:** `snake_case` keys; values keep their original case. Corporate-action `type` is normalized to lowercase snake_case (e.g. `dividend`, `stock_split`, `bonus_issue`).
- **Dates and numbers:** dates are ISO `YYYY-MM-DD`; timestamps are UTC `Z`. Numbers are JSON numbers written exactly from `Decimal`.
- **Missing values:** `null`, never `0`. `change_pct` is taken from the page if present, otherwise computed as `change / (close − change) × 100`, or `null` if that denominator is 0 or missing.
- **No links to jamstockex.com** anywhere in the output. The company `website` (the company's own site) is kept.
- **Versioning:** additive fields are allowed within v2; breaking changes go to `/v3/`.

## 6. Merge, validation and error handling

### 6.1 Failure classes

| Failure | Signal | Behaviour |
|---|---|---|
| Blocked (403/429, CloudFront block page) | `BlockedError` | No retry; no further JSE requests this run; stored data kept; every not-yet-fetched due dataset marked stale; exit 1 |
| Transient (timeout, connection, 5xx) | `FetchError` after retries | That dataset stale, stored data kept, other datasets continue; exit 1 |
| Layout change (table or required header missing) | `ParseError` | That dataset stale, stored data kept, message names page and header; exit 1 |
| No data (holiday) | parsed, zero quote rows | Not a failure; previous quotes and their `as_of` kept; `stale` false |

`status.json` records `last_error` (class and message) for each failed dataset and clears it on the next success.

### 6.2 Merge rules

- **Listings (only when refreshed):**
  - companies are upserted by `instrument_code`, and new ones get `listed_since = today`;
  - companies absent from the refresh get `listed = false` and `delisted_on = today`, **only if** all four market pages loaded successfully **and** the new count ≥ `(1 − max_listing_drop_pct/100) ×` the previous listed count;
  - otherwise delistings are held and logged as a warning, not a failure.
  - A previously delisted code that reappears is relisted (`listed = true`, `delisted_on = null`).
- **Quotes:** replace each instrument's `quote` when its row is present; instruments without a row keep their previous quote. Unknown codes trigger the listings refresh (§3.3). If they are still unknown afterwards, they are logged and skipped.
- **Indices:** replaced wholesale when quotes succeed with rows.
- **Corporate actions:** union with the stored set, deduplicated on `(symbol, type, record_date, ex_date, payment_date, amount, currency)`. Nothing is deleted.
- **Validation:** rows missing `instrument_code` or `symbol` (listings, quotes) or `symbol` or `type` (actions) are skipped with a warning.

### 6.3 Logging

Standard `logging` to stdout at INFO. The run summary covers requests made, datasets updated, stale or skipped, and counts added, updated and delisted.

## 7. Workflows

**`scrape.yml`:**

```yaml
on:
  schedule: [{ cron: "30 22 * * 1-5" }]   # 17:30 America/Jamaica (UTC-5, no DST)
  workflow_dispatch:
    inputs:
      refresh_listings: { type: boolean, default: false }
concurrency: { group: scrape, cancel-in-progress: false }
permissions: { contents: write }
```

Steps:
1. Check out `main`.
2. `actions/setup-python` 3.12 with pip cache, then `pip install -r requirements.txt`.
3. Check out the `data` branch into `site/`. If it doesn't exist, create an orphan branch containing `.nojekyll`.
4. Run `python -m jamstockex build --out site [--refresh-listings]`, recording its exit code.
5. Commit and push `site/` to `data` as `data: <trading day>` (github-actions bot), only if files changed. This step runs even if step 4 failed.
6. Fail the job if step 4 exited non-zero. GitHub then emails the repo owner.

**GitHub Pages:** configured once (manually) to deploy from branch `data`, root.

**`ci.yml`:** on push or PR to `main` and `develop`, it installs the dev requirements and runs `pytest`. The tests make no network calls.

## 8. Legal files

- **`LICENSE`:**
  - verbatim PolyForm Noncommercial 1.0.0
  - `Required Notice: Copyright (c) 2022-2026 Stephen Clarke (https://github.com/sdclarkelab)`
- **`NOTICE`:**
  - copyright and reservation of rights not granted;
  - source-available, not OSI open source;
  - commercial licensing via GitHub profile or issue (no email published);
  - releases up to and including `v1.0` remain MIT;
  - the market data is property of Jamaica Stock Exchange Limited / JSE Group and is not covered by the license;
  - no affiliation with or endorsement by the JSE;
  - "Jamaica Stock Exchange" and "JSE" are JSE Group marks, used descriptively.
- **`TERMS.md` (API Terms of Use):**
  1. noncommercial use only (commercial use requires a JSE data license);
  2. data rights belong to the JSE Group and no rights are granted;
  3. attribution required: "Data: Jamaica Stock Exchange, via jamstockex-scraper";
  4. end-of-day only, may be late, incomplete or wrong, provided as is without warranty;
  5. not financial advice, offer or solicitation;
  6. fair use: cache responses, poll at most hourly;
  7. may change or be withdrawn at any time;
  8. limitation of liability;
  9. governing law: Jamaica.
- **`README.md`:** rewritten for v2:
  - what it is, endpoints, example `curl`;
  - local run (`pip install -r requirements.txt && python -m jamstockex build --out site`);
  - configuration and tests;
  - a "License and Data" section linking LICENSE, NOTICE and TERMS.md.
  - The old `jamstockexapi.stockwatchja.com` link and `.env` instructions are removed.

These documents are drafted from standard templates and are not legal advice.

## 9. Testing

pytest, fully offline. TDD: a failing test before each parser and merge rule.

- **Fixtures:**
  - real HTML pages saved by the user from a browser (automated fetches from the dev environment are blocked): listed companies (one market), combined trade quotes, corporate actions;
  - variants made from them: a holiday quotes page with no rows, a quotes page with an inserted extra column, and a CloudFront block page.
- **`test_parse.py`:**
  - each page parser against its fixture;
  - header matching still works with an inserted or reordered column;
  - missing table or required header → `ParseError`;
  - value parsers: commas, `$`, currency prefixes, every date format, garbage → `None`;
  - original case preserved.
- **`test_store.py`:**
  - first-run load from an empty directory;
  - listings upsert, `listed_since`, delisting, and relisting;
  - the delisting guard (count drop, and a failed market);
  - quotes replace and keep;
  - holiday handling;
  - corporate-action deduplication and symbol → code mapping (including ambiguous and unknown);
  - stale and `last_error` set and cleared;
  - minified, deterministic output.
- **`test_fetch.py`** (fake session via `monkeypatch`):
  - User-Agent and timeout are sent;
  - delay between requests;
  - 5xx and timeouts retried, then `FetchError`;
  - 403, 429 and the CloudFront body → `BlockedError` with no retry, and later calls refused;
  - request count.
- **`test_build.py`:** end-to-end with a fake fetcher serving fixtures:
  - the full `v2/` tree and envelope on every file;
  - no `jamstockex.com` URL in any output;
  - the due-dataset logic (listings refresh by age, unknown code, flag);
  - exit codes, including one dataset failing while others publish.
- **Format checks:** plain assertion helpers (no `jsonschema` dependency).

The live check is a manual `workflow_dispatch` run. It is not part of CI.

## 10. Implementation order and risks

1. **Gate: confirm GitHub Actions can reach jamstockex.com.** A temporary `workflow_dispatch` job makes one request with the configured User-Agent and reports the status code. If it is blocked, **stop and revisit hosting**; never work around the block.
2. User saves the HTML fixtures; confirm the real `instrument_code` format and the header names.
3. Build the package by TDD in this order: `config`, `fetch`, `parse`, `store`, `__main__`.
4. Workflows, legal files, README and CLAUDE.md; remove the v1 files.
5. First manual run (backfill), enable Pages, verify the endpoints; tag `v2.0.0`. Soft launch.

**Other risks:**
- **GitHub disables scheduled workflows after 60 days without repository activity.** Daily data commits are expected to count; verify within the first 60 days. If they don't, add a monthly keepalive.
- **JSE layout changes.** These surface as a failed run with a `ParseError` naming the header; the fix is usually a header alias in `parse.py`.
- **The JSE objects to republishing.** Delete the `data` branch and disable Pages (§2).
