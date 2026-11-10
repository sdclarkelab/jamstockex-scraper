# v2: Local-First JSE Data App: Design

- **Date:** 2026-11-10
- **Status:** Approved in brainstorming, pending spec review
- **Supersedes:** `2026-11-09-v2-static-api-design.md` (static public API on GitHub Pages). That design was halted on 2026-11-10, when its gate failed: GitHub Actions got CloudFront `403 Request blocked` on its first request to jamstockex.com.
- **Release:** `v2.0.0` (the existing `v1.0` tag is untouched)

## 1. Goal

Replace the MongoDB-backed scraper with a **single-user, local-first app**. It keeps Jamaica Stock Exchange end-of-day data in a local file and serves it to its user through a JSON API with Swagger docs, reachable only from that user's own computer. It must:

- **run only on the user's own machine:** never as a hosted or public service, and with no cloud scraping;
- **need no setup:** a downloaded executable for Windows, macOS or Linux runs as is, and a `.pyz` runs with an existing Python 3.11+;
- **cost nothing:** free GitHub Actions builds, unsigned binaries;
- **keep requests to jamstockex.com minimal:** typically 2 per trading day, only when the stored data is out of date;
- **keep working when automated requests are blocked,** by importing pages the user saved from their browser;
- **adopt and improve on the parsing in** `sdclarkelab/jamstock-portfolio-tracker` `backend/app/scraper/jse_scraper.py`: header-matched columns, real types, failed versus empty;
- **relicense the code (v2 onward) under PolyForm Noncommercial 1.0.0,** and state clearly that the data belongs to the JSE Group.

### Non-goals

- A public or hosted API, GitHub Pages, scheduled cloud scraping, or multi-user access.
- A web UI beyond Swagger UI.
- Write endpoints. The API is read-only; refresh is automatic or via the CLI.
- Price history, real-time or intraday data.
- Code signing.
- Backward compatibility with the v1 MongoDB schema or `jamstockex-api`.

## 2. Legal and behavioural constraints

From the JSE Terms & Conditions (text supplied by the user on 2026-11-09) and the Disclaimer page:

| Clause | Constraint on this project |
|---|---|
| §11 Intellectual property: the JSE Group claims "any other data or information contained on the Site" | The data is not ours. Every API response carries a JSE ownership notice, and the app is for the user's personal, noncommercial use. It is never republished by this project. |
| §8.2 Acceptable use: no circumventing, impairing or overloading systems | **One honest User-Agent, no rotation and no browser imitation. Never work around a block.** Requests are minimal and spaced out. |
| §8.3 The JSE may monitor and terminate access | A block is expected and handled: stored data is kept, the user is told, and import is offered (§6). |
| §8.5.3 No linking to the Site without prior written consent | **No links to jamstockex.com in API output or docs.** The source is named in plain text. |
| §6 No recommendation or advice | Every response and the README say: not financial advice. |
| §11 Trademarks | No JSE logos. The name is used descriptively only, with no implied endorsement. |

**Local only:**
- **Technical enforcement:** the server binds to `127.0.0.1` (hard-coded, with no host option) and rejects any non-local `Host` header (§5.4).
- **Documentation:** NOTICE and the README state that the app is intended for local personal use and not for hosting.
- **Limits:** the code is source-available, so this deters but cannot technically stop someone who edits the source. PolyForm Noncommercial already prohibits commercial use.

**Expected block:** automated requests from the development machine were already blocked on 2026-11-09 and 2026-11-10. The honest User-Agent may well be blocked from the user's own connection too. Import (§6.3) is therefore a first-class path, not a fallback afterthought.

## 3. Architecture

```
                      ┌──────────────── jamstockex (one process) ────────────────┐
JSE website ◄─ fetch ─┤ refresh (background, ≤ once per trading day)              │
                      │      │ parse → merge → atomic save                         │
saved pages ─ import ─┤      ▼                                                     │
                      │ jse-data.json ──load──► in-memory snapshot ──► HTTP server │──► 127.0.0.1:8765
                      └────────────────────────────────────────────────────────────┘     /v2/…  /docs
```

### 3.1 Repository layout

```
jamstockex/
  __init__.py      # __version__ = "2.0.0"
  __main__.py      # CLI (§3.3)
  config.py        # built-in defaults + optional config.toml override (tomllib)
  fetch.py         # honest HTTP client on urllib.request; BlockedError / FetchError
  html.py          # minimal html.parser-based table extractor
  parse.py         # header-matched page parsers + value parsers; ParseError
  models.py        # dataclasses: Company, Quote, Index, CorporateAction (+ JSON)
  store.py         # State, load / merge / atomic save of jse-data.json, lock file
  refresh.py       # due logic, refresh run, import run, Report
  server.py        # http.server routes, Host check, envelope, filters, docs
  openapi.json     # hand-written OpenAPI 3.1 description
  static/swagger/  # vendored swagger-ui-dist files + their Apache-2.0 LICENSE
tests/             # pytest, offline; fixtures/ (synthetic, committed), fixtures/real/ (gitignored)
.github/workflows/ ci.yml  release.yml
requirements-dev.txt   # pytest only
LICENSE  NOTICE  README.md  CLAUDE.md
```

**Removed:**
- **v1 code and deployment files:** `database.py`, `scheduler.py`, `main.py`, `helper.py`, `urls.py`, `constants.py`, `custom_logger.py`, `services/`, `ua_file.txt`, `Procfile`, `Procfile.windows` and the root `__init__.py`.
- **Dependencies:** `requirements.txt` goes, because there are no runtime dependencies.
- **Earlier v2 design:** `TERMS.md`, the Pages and `data`-branch publishing, and `scrape.yml` are not created.

**Runtime:** standard library only, Python 3.11+ (3.11 is the `tomllib` floor). A test enforces that `jamstockex/` imports nothing outside `sys.stdlib_module_names`.

### 3.2 Module responsibilities

- **`config.py`:**
  - `load_config(data_dir) -> Config` uses built-in defaults (§4) and overlays `<data_dir>/config.toml` if it exists.
  - It validates types and ranges and fails fast with `ConfigError` naming the key.
  - Users don't need a config file at all.
- **`fetch.py`:** `Fetcher(source)` with `get(path) -> str`, on `urllib.request`.
  - It sends the configured User-Agent, a timeout, and a random `delay_s` pause before every request except the first.
  - Retries, up to `retries` attempts in total with exponential backoff, cover connection errors, timeouts and 5xx responses.
  - A 403, a 429 or a CloudFront "Request blocked" body raises `BlockedError` immediately. After that, every later `get` in the same `Fetcher` raises `BlockedError` without a request.
  - Error messages contain the request **path**, never the host or URL, because they are shown in `/v2/status`.
  - It counts the requests it makes.
- **`html.py`:** `extract_tables(html) -> list[Table]`. Each `Table` has `rows: list[Row]`, and each `Row` has `cells: list[Cell]` with `text` (whitespace-collapsed) and `hrefs`.
  - Rows from `<thead>`/`<tbody>`/`<tfoot>` come in document order.
  - It tolerates unclosed `<td>`/`<tr>`.
  - Nested tables are extracted as separate tables.
  - It replaces BeautifulSoup.
- **`parse.py`:** the same rules as the superseded spec §3.2, on `html.Table`:
  - **Header matching:** columns are matched by normalized header name through alias tables. A required table or header that is missing raises `ParseError(page, problem)`.
  - **Quotes table is required:** the trade-quotes page needs its quotes table. On a holiday it shows the header with no rows. A missing indices table only warns.
  - **Warnings and skipped rows:** an unmatched optional column logs one warning per page. Skipped rows are counted once per page. Rows missing `instrument_code` or `symbol` (listings, quotes), or `symbol` or `type` (actions), are skipped.
  - **Original case kept.** Value parsers return `None` for anything unparseable, never 0.
  - **Page parsers:** `parse_listed_companies(html, market_label) -> list[Company]`, `parse_trade_quotes(html, trade_date) -> (dict[str, Quote], list[Index])`, `parse_corporate_actions(html) -> list[CorporateAction]`.
  - **Import helpers:** `detect_page(html) -> "listings" | "quotes" | "corporate_actions" | None`, `detect_market(html, markets) -> int | None`, `detect_trade_date(html) -> date | None`.
- **`models.py`:** plain dataclasses with `Decimal`/`date` fields, and `to_json`/`from_json`.
- **`store.py`:**
  - `load(path) -> State` returns an empty state if the file is missing. If the file is corrupt, it raises `StoreError` and never overwrites the file.
  - `merge(state, result, *, today, now, settings) -> list[str]` applies §6.2 and returns warnings.
  - `save(state, path)` writes atomically: temp file in the same folder, `fsync`, then `os.replace`.
  - `RefreshLock(path)` is an exclusive lock file (`O_CREAT | O_EXCL`) holding the PID and time. A lock older than 10 minutes is taken over.
- **`refresh.py`:**
  - `latest_close(now)` and `due(state, now, settings) -> Due` (§6.1).
  - `run_refresh(state, fetcher, now, settings, force_listings=False) -> Report` does what is due: fetch, parse, merge.
  - `run_import(state, folder, now, settings) -> Report`.
  - `Report` holds the requests made, per-dataset outcome (updated, stale or skipped), counts, warnings and errors.
- **`server.py`:**
  - `make_server(port, snapshot_provider)` returns a `ThreadingHTTPServer` bound to `127.0.0.1`.
  - It has a read-only router (§5), the Host check, the envelope, filters, error JSON and static docs files.
  - Responses are served from an immutable in-memory snapshot, which is replaced atomically after each save.
- **`__main__.py`:** the CLI (§3.3), data-folder resolution, startup messages, and the background refresh thread with its timer.

### 3.3 CLI

| Command | Does |
|---|---|
| `jamstockex` (or `jamstockex serve`) | Loads data, starts the API at `http://127.0.0.1:8765`, refreshes in the background when due, and runs until Ctrl+C |
| `jamstockex refresh [--listings]` | Runs one refresh of what's due now (`--listings` forces all markets) and prints the report. Exit 0 = ok, 1 = a dataset failed or was blocked |
| `jamstockex import <folder>` | Imports saved pages (§6.3) and prints the report. Exit 0 = ok, 1 = no usable page found |
| `jamstockex --version` | Prints the version |

**Common options:**
- `--data-dir <path>`: the default is the per-user data folder (below).
- `--port <n>`: the default is 8765, and `serve` only.
- `--offline`: `serve` without refreshing.

There is **no** host option.

**Per-user data folder:**
- macOS: `~/Library/Application Support/jamstockex/`
- Windows: `%APPDATA%\jamstockex\`
- Linux: `$XDG_DATA_HOME/jamstockex/`, or `~/.local/share/jamstockex/`

It holds `jse-data.json`, `jse-data.lock` while a refresh is running, and an optional `config.toml`.

**Startup output:**

```
JSE data API running at http://127.0.0.1:8765/v2/   docs: http://127.0.0.1:8765/docs
Data: <data folder>/jse-data.json (as of 2026-11-09)
Refreshing in background… (Ctrl+C to stop)
```

If the port is in use, the app exits with code 2: "Port 8765 is in use; try --port 8766". A config or store error also exits 2, naming the file and problem.

## 4. Configuration

Built-in defaults. Any subset can be overridden in `<data_dir>/config.toml`:

```toml
[source]
base_url   = "https://www.jamstockex.com"
user_agent = "jamstockex/2.0 (+https://github.com/sdclarkelab/jamstockex-scraper)"
timeout_s  = 20
retries    = 3          # attempts per request; blocks are never retried
delay_s    = [2, 5]

[markets]               # listed-companies market code = label
31 = "Main Market"
22 = "Junior Market"
51 = "Bond Market"
49 = "USD Market"

[quotes]
combined_market = 50

[refresh]
close_time                   = "17:30"   # America/Jamaica
check_every_minutes          = 15
retry_after_failure_minutes  = 60
listings_every_days          = 7
corporate_actions_window     = 30
corporate_actions_forward    = 365
backfill_from                = 2026-01-01
max_listing_drop_pct         = 20

[server]
port = 8765
```

The timezone is fixed to `America/Jamaica`; it is not configurable.

## 5. API

Everything is GET only, and the base is `http://127.0.0.1:<port>`.

### 5.1 Routes

| Path | Returns |
|---|---|
| `/` | `302` → `/docs` |
| `/docs` | Swagger UI page; assets at `/docs/assets/<file>` |
| `/openapi.json` | The OpenAPI 3.1 document |
| `/v2/status` | Per dataset (`listings`, `quotes`, `indices`, `corporate_actions`): `{as_of, fetched_at, stale, last_error, source}`, where `source` is `"fetch"` or `"import"`. `listings` also has `markets` (the same fields per market label) and `unmatched_codes`. Top level: `refreshing`, `blocked`, `next_check_at`, `data_file` |
| `/v2/stocks` | Array of stock entries with `quote`. Filters: `symbol`, `market`, `listed` (`true`/`false`) |
| `/v2/stocks/{instrument_code}` | One stock entry plus `dividends` and `corporate_actions`; 404 if unknown |
| `/v2/indices` | Array of `{name, date, value, change, change_pct, volume}` |
| `/v2/corporate-actions` | All corporate actions. Filters: `symbol`, `type` |
| `/v2/dividends` | `type == "dividend"` actions. Filters: `symbol`, `upcoming` (`true` = payment date ≥ today in Jamaica) |

Filters are exact, case-insensitive matches. An unknown filter name or an invalid boolean returns 400. Results are sorted: stocks by `instrument_code`, actions by `record_date` and then `symbol`.

### 5.2 Envelope and data shapes

```json
{
  "meta": {
    "api_version": "v2",
    "as_of": "2026-11-09",
    "saved_at": "2026-11-09T22:31:04Z",
    "stale": false,
    "source": "Data: Jamaica Stock Exchange Limited (jamstockex.com). All rights in the data belong to the JSE Group.",
    "notice": "Personal, noncommercial use only. Not financial advice.",
    "license": "Code: PolyForm Noncommercial 1.0.0"
  },
  "data": {}
}
```

**`meta` fields:**
- **`as_of`:** the trading date of the data in that response.
- **`saved_at`:** when `jse-data.json` was last saved.
- **`stale`:** true if the relevant dataset's latest due fetch failed. Per-stock responses use `quotes.stale OR <stock's market>.stale`.

**Data shapes:** stock entries, corporate actions and indices keep the superseded spec's §5 shapes and conventions:
- keyed by `instrument_code`;
- `snake_case` keys, original letter case kept in values;
- ISO dates, UTC `Z` timestamps;
- JSON numbers from `Decimal`, and `null` never `0`;
- `change_pct` taken from the page, otherwise computed;
- corporate-action `type` is lowercase snake_case;
- symbol → `instrument_code` mapping for actions: currency breaks ties, and an ambiguous or unknown symbol gives `null`.

**No `jamstockex.com` links in any response.** The company's own `website` is kept.

### 5.3 Errors

`{"error": {"status": <code>, "message": "<text>"}}`, used for 400, 404 and 405 (with an `Allow: GET` header). An unhandled exception returns 500 with a generic message, and the traceback goes to the console only.

### 5.4 Local-only protections

- **Binding:** the server binds `127.0.0.1` only.
- **`Host` header:** it must be exactly `127.0.0.1:<port>` or `localhost:<port>`. Anything else gets a `403` with a plain-text explanation. This stops DNS rebinding.
- **No CORS headers.** Other browser origins can't read responses; non-browser clients aren't affected.
- **Headers on every response:** `X-Content-Type-Options: nosniff` and `Cache-Control: no-store`. The docs page also gets `Content-Security-Policy: default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'`, the minimum Swagger UI needs.
- JSON is minified UTF-8 with sorted keys.

### 5.5 Docs

- **Swagger UI:** the pinned `swagger-ui-dist` (`swagger-ui-bundle.js`, `swagger-ui.css`, plus its `LICENSE` and any `NOTICE`) is vendored into `jamstockex/static/swagger/`. Its version is recorded in `jamstockex/static/swagger/VERSION`.
- **`/docs`:** a small static HTML page that loads those assets and `/openapi.json`. Its init script is a separate static file, so the CSP needs no `unsafe-inline` for scripts.
- **Packaging:** files are read with `importlib.resources`, so they work from the source tree, the `.pyz` and the PyInstaller build.
- **`openapi.json`:** written by hand. Every route, filter, response envelope and error is described, with examples.

## 6. Refresh, block handling and import

### 6.1 When a refresh is due

- **`latest_close(now)`:** the most recent weekday `D` (in America/Jamaica) whose `D close_time` is ≤ `now`. Before 17:30 on a weekday, that is the previous weekday. On a weekend, it is Friday. The trade date requested is `D`.
- **Quotes, indices and corporate actions** are due when `status.quotes.fetched_at < latest_close`. A holiday counts as a successful fetch (zero rows), so there is at most one successful refresh per trading day.
- **Listings** (per market), as in the superseded spec §3.3:
  - all markets: `--listings`, no stored listings, an unknown quote code not already in `unmatched_codes`, or the market's last refresh ≥ `listings_every_days` ago;
  - one market alone: its last fetch failed.
- **Corporate-actions window:**
  - normal: `max(backfill_from, corporate_actions.as_of − window)` → `today + forward`;
  - until the first success: `backfill_from` → `today + forward`.
- **While serving:**
  - **Timing:** a check runs at startup and then every `check_every_minutes`. A check is a clock comparison, with no network traffic.
  - **Transient failure:** after a failed refresh, the next attempt waits at least `retry_after_failure_minutes`.
  - **Block:** after one, there is no automatic attempt until the next `latest_close` advances.
  - **`--offline`:** disables all of this.
- **Locking:** every refresh and import holds `RefreshLock`. If it is held, `serve` skips that check, while `refresh`/`import` exit 1 with "another refresh is running".

### 6.2 Merge rules and failure classes

These are unchanged from the superseded spec §6.1–§6.2:
- failure classes: blocked, transient, layout change, optional header unmatched, holiday;
- the per-market delisting guard, with integer comparison `found × 100 ≥ (100 − max_listing_drop_pct) × previous`, plus non-empty page and relisting;
- quotes replace and keep;
- indices replaced only when non-empty;
- `unmatched_codes` accumulate and leave when found;
- the corporate-actions union with dedupe key `(symbol, type, record_date, ex_date, payment_date, amount, currency)`, never deleting;
- `last_error` set and cleared.

Reports count companies added, updated and delisted, and actions added.

### 6.3 Blocked: what the user sees

- **Console (serve):** "The JSE site is blocking automated requests from this computer. Your stored data is still served. To update it, save the pages from your browser (see README) and run: jamstockex import <folder>".
- **`/v2/status`:** `blocked: true`, and each affected dataset gets `stale: true` with its `last_error`.
- **Never** a retry with different headers or identity.

### 6.4 Import

`jamstockex import <folder>` reads every `*.htm`/`*.html` in the folder, non-recursively:

1. **Page type:** `detect_page` identifies each page from its table headers. Unrecognized files are listed and skipped.
2. **Listings:** the market comes from `detect_market`, using the page's selected market option or heading text matched against the configured labels. If that fails, the filename pattern `listed-companies-<code>.html` is used. If neither works, the file is skipped with: "Can't tell which market this is; rename it listed-companies-<code>.html".
3. **Quotes:** the trade date comes from `detect_trade_date` (the page's date field or heading). If that fails, it uses `latest_close(now)`'s date and warns.
4. **Merge:** pages are merged in the order listings → quotes → corporate actions, using the same merge as a fetch. Statuses record `source: "import"`. Import never contacts the JSE.

Exactly which markup `detect_market` and `detect_trade_date` read is confirmed against the user's real saved pages (§9, step 1).

## 7. Distribution and workflows

**`release.yml`,** on push of a `v*` tag:
- **Build matrix:** PyInstaller one-file (`pyinstaller==6.10.0`, build-time only, Python 3.12) on `windows-latest`, `macos-14` (Apple Silicon), an Intel macOS runner (label confirmed at implementation), and `ubuntu-22.04`. The oldest supported Ubuntu is used for glibc compatibility.
- **Asset names:**
  - `jamstockex-windows-x64.exe`
  - `jamstockex-macos-arm64`
  - `jamstockex-macos-x64`
  - `jamstockex-linux-x64`
- **Bundled data:** `openapi.json` and `static/` are included via `--add-data`.
- **`.pyz`:** built with `python -m zipapp` (stdlib) as `jamstockex.pyz`, with shebang `/usr/bin/env python3`.
- **Smoke test, for each artifact on its own OS:**
  1. start it with `--offline --data-dir <temp> --port 8765`;
  2. wait for the port;
  3. GET `/v2/status`, `/docs` and `/openapi.json` over 127.0.0.1 and expect 200;
  4. stop it.

  The `.pyz` is smoke-tested on Python 3.11. No contact with the JSE.
- **Upload:** every artifact and a `SHA256SUMS` file go to the GitHub Release.

**`ci.yml`,** on push to `main`/`develop` and on PRs to those branches: pytest on Python 3.11 and 3.12, ubuntu-latest, offline.

**First run on each OS (README):**
- **macOS:** allow once in System Settings → Privacy & Security → Open Anyway; on Linux and macOS, `chmod +x` first.
- **Windows:** SmartScreen → More info → Run anyway.

## 8. Legal files

- **`LICENSE`:** the verbatim PolyForm Noncommercial 1.0.0 text, with `Required Notice: Copyright (c) 2022-2026 Stephen Clarke (https://github.com/sdclarkelab)`, checksum-verified against the official text.
- **`NOTICE`:**
  - copyright and reservation of rights;
  - source-available, not OSI open source;
  - commercial licensing via a GitHub issue (no email published);
  - releases up to and including `v1.0` remain MIT;
  - the market data is property of Jamaica Stock Exchange Limited / JSE Group and is not covered by the license;
  - no affiliation or endorsement; JSE marks used descriptively;
  - **intended for local, personal use on your own computer, not for hosting as a service;**
  - **not financial advice;**
  - third-party notice: Swagger UI (Apache-2.0), with its license file location.
- **`README.md`:**
  - what it is;
  - download and first run per OS;
  - using the API and `/docs`;
  - automatic refresh and what "blocked" means;
  - how to save pages and run `import`;
  - configuration;
  - development (pytest);
  - **License and data** (LICENSE, NOTICE, personal use, not advice).
  - It contains no links to jamstockex.com.
- These documents are drafted from standard templates and are not legal advice.

## 9. Implementation order, testing and risks

**Order:**
1. **The user saves real pages** from a browser into the gitignored `tests/fixtures/real/`:
   - listed companies for all four markets;
   - combined trade quotes for a trading day and for a public holiday;
   - corporate actions with a `thruDate` a year ahead.

   This confirms the header names, the `instrument_code` format, the absence of pagination, holiday behaviour, and the markup for `detect_market`/`detect_trade_date`. Pagination, or a holiday answered with the previous session's data, is a stop-and-redesign point.
2. TDD in this order: `config`, `models`, `fetch`, `html`, `parse`, `store`, `refresh` (with import), `server` with `openapi.json` and the docs, then `__main__`.
3. `ci.yml`, `release.yml`, legal files, README, CLAUDE.md; remove the v1 files.
4. **Live check by the user:** `jamstockex refresh` from their own computer. Either result is acceptable: success, or a clear blocked message followed by a successful `import`.
5. PR to `main`, tag `v2.0.0`, and the release builds and publishes.

**Testing:** pytest, offline. Tests may open sockets on 127.0.0.1 only.
- **Carried over** from the superseded spec §9, adapted:
  - parser, merge and store tests;
  - the fetch tests against a fake opener (no network);
  - "no `jamstockex.com` URL in output" checks.
- **`html.py`:**
  - thead/tbody/tfoot order;
  - unclosed cells and rows;
  - nested tables;
  - hrefs collected per cell;
  - whitespace collapsing.
- **`store.py`:**
  - atomic save, including a simulated crash between the temp write and the replace, after which the old file is intact;
  - a corrupt file gives `StoreError` and the file is untouched;
  - lock acquire, refusal and takeover of a stale lock.
- **`refresh.py`** (fake clock and fake fetcher):
  - `latest_close` across weekday before and after 17:30, Friday night, Saturday, Sunday and Monday morning;
  - at most one successful refresh per close;
  - holiday;
  - the retry wait after failure;
  - no retry after a block until the next close;
  - per-market listings and `unmatched_codes`;
  - the corporate-actions catch-up window.
- **Import** (synthetic saved pages):
  - type detection;
  - market detection from markup and from the filename, and the rename message;
  - trade-date detection and its fallback warning;
  - `source: "import"`;
  - no fetcher calls.
- **`server.py`** (a real server on a random 127.0.0.1 port):
  - every route, filter and sort;
  - 400, 404, 405 and 500 shapes;
  - Host check (403);
  - no CORS headers;
  - security headers and the docs CSP;
  - assets served;
  - snapshot swap while serving;
  - **parity: every route the router answers is in `openapi.json`, and every `openapi.json` path is answered.**
- **CLI:**
  - default data folder per OS (patched `sys.platform`/env);
  - port-in-use exit 2;
  - `--offline` makes no fetcher calls;
  - `--version`.
- **Standard library only:** an `ast` scan of `jamstockex/` imports against `sys.stdlib_module_names`.
- **Real-page checks** (`tests/test_parse_real.py`, local only, skipped when the pages are absent): every alias matches, holiday → zero quotes, detection helpers work on every saved page, market labels match the config.

**Risks:**
- **Automated refresh blocked from the user's connection.** Likely, given the 2026-11-09/10 results. Handled by §6.3–§6.4, with no circumvention.
- **JSE layout changes.** These surface as a `ParseError` naming the page and header; the fix is usually an alias in `parse.py`.
- **Unsigned binaries.** One-time OS approval, documented in the README.
- **Intel macOS runner availability** on GitHub Actions. If no Intel runner is offered, publish only the arm64 build and point Intel Mac users to the `.pyz`.
