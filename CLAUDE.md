# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

`jamstockex` is a single-user, local-first app. It keeps Jamaica Stock Exchange end-of-day data in a local
`jse-data.json` and serves it read-only on `127.0.0.1` as a JSON API (`/v2/…`) with Swagger docs (`/docs`).
It uses only the Python 3.11+ standard library. Spec: `docs/superpowers/specs/2026-11-10-v2-local-app-design.md`.

## Commands

```shell
/opt/homebrew/bin/python3.12 -m venv --clear .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest -q                                          # offline suite
.venv/bin/pytest tests/test_server.py::test_status -q        # single test
.venv/bin/python -m jamstockex --offline --data-dir /tmp/jse # serve without refreshing
.venv/bin/python -m jamstockex refresh                       # one real refresh (contacts the JSE site)
```

## Architecture

- `config.py`: built-in defaults plus an optional `<data_dir>/config.toml`. `JAMAICA` is a fixed UTC-05:00 offset.
- `fetch.py`: `Fetcher` sends one honest User-Agent, pauses between requests, and retries only 5xx and
  connection errors. On 403/429 or a CloudFront page it raises `BlockedError` and refuses all further requests.
- `html.py`: `extract_tables` on `html.parser` (no BeautifulSoup).
- `parse.py`: columns are matched by **normalised header name** through alias tuples (`LISTING_COLUMNS`,
  `QUOTE_COLUMNS`, `INDEX_COLUMNS`, `ACTION_COLUMNS`). Value parsers return `None`, never 0. A missing
  required table or header raises `ParseError`; the fix is usually a new alias. A trade-quotes page without a
  quotes table is a day without trading only if it has the site's "no data" message (`NO_DATA_MARKER`).
- `store.py`: `State`, `load` and atomic `save` of `jse-data.json`, `RefreshLock`, and `merge` (per-market
  delisting guard, `unmatched_codes`, corporate-action dedupe, symbol → `instrument_code` mapping, and the
  no-data safety net: 3 trading days in a row without quotes mark quotes and indices stale).
- `refresh.py`: `latest_close`/`due` (at most one successful refresh per weekday close, a retry wait after
  failure, and none after a block until the next close), then `run_refresh` → `Report`.
- `server.py`: `Snapshot` and `make_server`. It binds 127.0.0.1 only, checks the Host header, sends no CORS
  headers and serves from `openapi.json` and `static/`. `ROUTES` must match `openapi.json` (a test checks this).
- `__main__.py`: CLI (`serve`, `refresh`, `--version`), data-folder resolution, and `Service` (the background
  refresh thread).
- `.github/`: `build_pyz.py`, `smoke_test.py`, `pyinstaller_entry.py`; `ci.yml` and `release.yml`.

## Rules

- **Standard library only** in `jamstockex/` (`tests/test_stdlib_only.py`). pytest is dev-only.
- **Never rotate or spoof the User-Agent, and never work around a block** (JSE T&C §8.2).
- **No `jamstockex.com` URLs** in API output, `openapi.json`, docs, README or NOTICE (JSE T&C §8.5.3).
  Error messages name request paths, never hosts.
- **Bind 127.0.0.1 only; there is no host option.**
- **Never commit real JSE pages.** `tests/fixtures/real/` is gitignored; committed fixtures are synthetic.
- **Tests stay offline** (127.0.0.1 sockets only).
- **License:** code is PolyForm Noncommercial 1.0.0; the data belongs to the JSE Group (see NOTICE).
