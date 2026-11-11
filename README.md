# jamstockex

A small app that keeps **Jamaica Stock Exchange (JSE) end-of-day data** in a file on your computer and
serves it to you as a JSON API with Swagger docs, at `http://127.0.0.1:8765`. Only your own computer can
reach it.

> **Not affiliated with or endorsed by the Jamaica Stock Exchange.** The data belongs to the JSE Group.
> Personal, noncommercial use only. Not financial advice. See [License and data](#license-and-data).

## Download and first run

Download the file for your computer from the latest GitHub Release, plus `SHA256SUMS` if you want to check it:

| System | File |
|---|---|
| Windows (64-bit) | `jamstockex-windows-x64.exe` |
| macOS, Apple Silicon | `jamstockex-macos-arm64` |
| macOS, Intel | `jamstockex-macos-x64` |
| Linux (x86-64) | `jamstockex-linux-x64` |
| Any system with Python 3.11+ | `jamstockex.pyz` (run `python3 jamstockex.pyz`) |

Downloaded files may not keep their "executable" permission, and your system may stop the first run
with a warning about an unidentified app. Approve it once:
- **macOS:** `chmod +x jamstockex-macos-*`, run it once, then open System Settings → Privacy & Security and
  click **Open Anyway**.
- **Linux:** `chmod +x jamstockex-linux-x64`, then run `./jamstockex-linux-x64`.
- **Windows:** when SmartScreen appears, click **More info → Run anyway**.

When it starts you'll see:

```
JSE data API running at http://127.0.0.1:8765/v2/   docs: http://127.0.0.1:8765/docs
Data: <data folder>/jse-data.json (as of 2026-11-09)
Refreshing in background… (Ctrl+C to stop)
```

## Using the API

Open `http://127.0.0.1:8765/docs` for interactive docs. Everything is read-only GET:

| Path | Returns |
|---|---|
| `/v2/status` | Freshness of each dataset (`as_of`, `fetched_at`, `stale`, `last_error`), `blocked`, `next_check_at`, `data_file` |
| `/v2/stocks` | Every instrument with its latest quote. Filters: `symbol`, `market`, `listed=true/false` |
| `/v2/stocks/{instrument_code}` | One instrument with its `dividends` and `corporate_actions` |
| `/v2/indices` | Market indices |
| `/v2/corporate-actions` | All corporate actions. Filters: `symbol`, `type` |
| `/v2/dividends` | Dividends. Filters: `symbol`, `upcoming=true/false` |

```shell
curl -s "http://127.0.0.1:8765/v2/stocks?market=Main%20Market" | python3 -m json.tool | head -40
```

Every response has a `meta` block (`as_of`, `saved_at`, `stale`, source, notice, license) and a `data` block.
Instruments are keyed by `instrument_code`: a company listed in JMD and USD has one symbol and two instruments.
Unknown values are `null`, never `0`. Dates are `YYYY-MM-DD` and timestamps are UTC.

## Refresh, and what "blocked" means

The app fetches new data at most once per trading day, after the 17:30 Jamaica-time close, and only when
the stored data is out of date. A typical day needs 2 requests to the JSE site; listed companies are
refreshed weekly. It uses one honest User-Agent and waits between requests. You can change that
User-Agent with `user_agent` under `[source]` in `config.toml`, but it should keep identifying this app
honestly rather than imitating a browser.

- `jamstockex refresh` runs one refresh now and prints a report (`--listings` also refreshes every market).
- `jamstockex --offline` serves the stored data without refreshing.

On a day without trading (a public holiday) the JSE site has no trade data, and the previous quotes are kept.
If it reports no trade data for 3 trading days in a row, `/v2/status` marks quotes and indices stale, because
the site may have changed; the app still tries again after each close.

If the JSE site blocks automated requests from your connection, the app says so plainly:

> The JSE site is blocking automated requests from this computer. Your stored data is still served;
> automatic refresh will try again after the next market close.

`/v2/status` then shows `"blocked": true`. The app never retries with a different identity or works around a
block. On a first run with no stored data, there is nothing to serve until a refresh gets through.

## Configuration

Data lives in your per-user data folder (change it with `--data-dir`):
- **macOS:** `~/Library/Application Support/jamstockex/`
- **Windows:** `%APPDATA%\jamstockex\`
- **Linux:** `$XDG_DATA_HOME/jamstockex/`, or `~/.local/share/jamstockex/`

No configuration is needed. To change a setting, create `config.toml` in that folder with only the keys you
want to override. For example:

```toml
[refresh]
check_every_minutes = 30

[server]
port = 8766
```

The sections are `[source]`, `[markets]`, `[quotes]`, `[refresh]` and `[server]`; the defaults are in
`jamstockex/config.py`. Unknown keys and invalid values stop the app with a message naming the key.
`--port <n>` overrides the port for one run. If the port is taken, the app exits and suggests another one.

Exit codes: `0` ok; `1` a dataset failed or was blocked, or another refresh is running; `2` a config,
data-file or port problem.

## Development

```shell
python3.12 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest -q              # offline; never contacts the JSE site
.venv/bin/python -m jamstockex --offline
```

The app uses only the Python standard library (3.11+). Releases are built by `.github/workflows/release.yml`
when a `v*` tag is pushed.

## License and data

- **Code:** [PolyForm Noncommercial 1.0.0](LICENSE). Copyright (c) 2022-2026 Stephen Clarke. It is free for
  noncommercial use; commercial use needs a separate license, so open an issue to ask. Versions up to `v1.0`
  were MIT and remain so. See [NOTICE](NOTICE).
- **Data:** the property of Jamaica Stock Exchange Limited / the JSE Group, and not covered by the code license.
- **Use:** intended for local, personal use on your own computer, not for hosting as a service or
  republishing the data.
- **Not financial advice.** The data may be late, incomplete or wrong.
- **Third-party:** Swagger UI (Apache-2.0), in `jamstockex/static/swagger/`.
