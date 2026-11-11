"""Read-only JSON API and Swagger UI docs, on http.server, for this computer only.

- Binds 127.0.0.1 (hard-coded; there is no host option) and answers only requests
  whose Host header is 127.0.0.1:<port> or localhost:<port>, which stops DNS rebinding.
- No CORS headers, so other browser origins can't read responses.
- Every response has X-Content-Type-Options: nosniff and Cache-Control: no-store.
- Responses come from an immutable Snapshot; the app swaps in a new one after each save.
"""

from __future__ import annotations

import datetime as dt
import functools
import importlib.resources
import json
import logging
import socketserver
import sys
from dataclasses import dataclass, replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable
from urllib.parse import parse_qs, unquote, urlsplit

from jamstockex.config import JAMAICA
from jamstockex.store import State, action_sort_key, utc_timestamp

log = logging.getLogger(__name__)

API_VERSION = "v2"
SOURCE = ("Data: Jamaica Stock Exchange Limited (jamstockex.com). "
          "All rights in the data belong to the JSE Group.")
NOTICE = "Personal, noncommercial use only. Not financial advice."
LICENSE = "Code: PolyForm Noncommercial 1.0.0"
DOCS_CSP = "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'"

# Every path the router answers. tests/test_server.py checks this against openapi.json.
ROUTES = (
    "/", "/docs", "/docs/assets/{file}", "/openapi.json",
    "/v2/", "/v2/status", "/v2/stocks", "/v2/stocks/{instrument_code}",
    "/v2/indices", "/v2/corporate-actions", "/v2/dividends",
)
FILTERS = {
    "/v2/stocks": ("symbol", "market", "listed"),
    "/v2/corporate-actions": ("symbol", "type"),
    "/v2/dividends": ("symbol", "upcoming"),
}
ASSETS = {
    "swagger-ui-bundle.js": ("static/swagger/swagger-ui-bundle.js", "text/javascript; charset=utf-8"),
    "swagger-ui.css": ("static/swagger/swagger-ui.css", "text/css; charset=utf-8"),
    "docs-init.js": ("static/docs-init.js", "text/javascript; charset=utf-8"),
}
ENDPOINTS = {
    "status": "/v2/status",
    "stocks": "/v2/stocks",
    "stock": "/v2/stocks/{instrument_code}",
    "indices": "/v2/indices",
    "corporate_actions": "/v2/corporate-actions",
    "dividends": "/v2/dividends",
    "docs": "/docs",
    "openapi": "/openapi.json",
}


@functools.lru_cache(maxsize=None)
def resource(name: str) -> bytes:
    """A packaged file; works from the source tree, a .pyz and a PyInstaller build."""
    return importlib.resources.files("jamstockex").joinpath(name).read_bytes()


def encode_json(doc: Any) -> bytes:
    return json.dumps(doc, separators=(",", ":"), sort_keys=True, ensure_ascii=False).encode("utf-8")


# --- snapshot ------------------------------------------------------------------


@dataclass(frozen=True)
class Snapshot:
    """Everything the API serves, precomputed from one saved State. Treat as read-only."""

    stocks: tuple[dict[str, Any], ...]               # sorted by instrument_code, each with "quote"
    actions: tuple[dict[str, Any], ...]              # sorted by record_date, then symbol
    indices: tuple[dict[str, Any], ...]
    status: dict[str, Any]                           # the four datasets, as /v2/status shows them
    stock_meta: dict[str, tuple[str | None, bool]]   # instrument_code -> (as_of, stale)
    saved_at: str | None
    data_file: str
    blocked: bool
    refreshing: bool = False
    next_check_at: str | None = None

    @classmethod
    def from_state(cls, state: State, *, data_file: str) -> Snapshot:
        companies = sorted(state.companies.values(), key=lambda c: c.instrument_code)
        status = {name: s.to_json() for name, s in state.status.items()}
        status["listings"]["markets"] = {label: m.to_json() for label, m in sorted(state.markets.items())}
        status["listings"]["unmatched_codes"] = sorted(state.unmatched)
        stock_meta = {}
        for company in companies:
            market = state.markets.get(company.market, state.status["listings"])
            as_of = company.quote.date if company.quote else market.as_of
            stock_meta[company.instrument_code] = (
                as_of.isoformat() if as_of else None,
                state.status["quotes"].stale or market.stale,
            )
        return cls(
            stocks=tuple(c.to_json() for c in companies),
            actions=tuple(a.to_json() for a in sorted(state.actions, key=action_sort_key)),
            indices=tuple(i.to_json() for i in sorted(state.indices, key=lambda i: i.name)),
            status=status,
            stock_meta=stock_meta,
            saved_at=utc_timestamp(state.saved_at) if state.saved_at else None,
            data_file=data_file,
            blocked=state.blocked_close is not None,
        )

    def with_runtime(self, *, refreshing: bool, next_check_at: dt.datetime | None) -> Snapshot:
        return replace(self, refreshing=refreshing,
                       next_check_at=utc_timestamp(next_check_at) if next_check_at else None)


# --- HTTP ------------------------------------------------------------------------


class HttpError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def match_route(path: str) -> tuple[str, dict[str, str]] | None:
    if path in ROUTES and "{" not in path:
        return path, {}
    for prefix, template, name in (("/v2/stocks/", "/v2/stocks/{instrument_code}", "instrument_code"),
                                   ("/docs/assets/", "/docs/assets/{file}", "file")):
        rest = path[len(prefix):]
        if path.startswith(prefix) and rest and "/" not in rest:
            return template, {name: unquote(rest)}
    return None


def _bool(name: str, value: str) -> bool:
    lowered = value.lower()
    if lowered not in ("true", "false"):
        raise HttpError(400, f"Invalid value for {name}: {value!r} (use true or false)")
    return lowered == "true"


def _same(a: Any, b: str) -> bool:
    return isinstance(a, str) and a.casefold() == b.casefold()


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True
    # On Windows SO_REUSEADDR would let a second server bind a port that is already in use.
    allow_reuse_address = sys.platform != "win32"

    def __init__(self, port: int, snapshot_provider: Callable[[], Snapshot],
                 today: Callable[[], dt.date]) -> None:
        self.snapshot_provider = snapshot_provider
        self.today = today
        super().__init__(("127.0.0.1", port), _Handler)

    def server_bind(self) -> None:
        socketserver.TCPServer.server_bind(self)  # skip HTTPServer's reverse DNS lookup
        self.server_name = "127.0.0.1"
        self.server_port = self.server_address[1]

    @property
    def port(self) -> int:
        return self.server_address[1]


def make_server(port: int, snapshot_provider: Callable[[], Snapshot], *,
                today: Callable[[], dt.date] | None = None) -> LocalServer:
    """A server bound to 127.0.0.1:<port> (0 picks a free port). Raises OSError if the port is in use."""
    return LocalServer(port, snapshot_provider, today or (lambda: dt.datetime.now(JAMAICA).date()))


class _Handler(BaseHTTPRequestHandler):
    server: LocalServer
    server_version = "jamstockex"
    sys_version = ""

    def log_message(self, format: str, *args: Any) -> None:
        log.debug("%s - %s", self.address_string(), format % args)

    # -- responses --

    def _send(self, status: int, body: bytes, content_type: str, extra: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        for name, value in (extra or {}).items():
            self.send_header(name, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status: int, doc: Any, extra: dict[str, str] | None = None) -> None:
        self._send(status, encode_json(doc), "application/json; charset=utf-8", extra)

    def _error(self, status: int, message: str, extra: dict[str, str] | None = None) -> None:
        self._json(status, {"error": {"status": status, "message": message}}, extra)

    def _host_ok(self) -> bool:
        port = self.server.port
        if self.headers.get("Host") in (f"127.0.0.1:{port}", f"localhost:{port}"):
            return True
        body = (f"Forbidden: this API only answers requests addressed to 127.0.0.1:{port} "
                f"or localhost:{port}.\n").encode("utf-8")
        self._send(403, body, "text/plain; charset=utf-8")
        return False

    # -- methods --

    def do_GET(self) -> None:
        if not self._host_ok():
            return
        try:
            self._route()
        except HttpError as exc:
            self._error(exc.status, exc.message)
        except Exception:
            log.exception("Unhandled error for GET %s", self.path)
            self._error(500, "Internal server error")

    def _not_allowed(self) -> None:
        if self._host_ok():
            self._error(405, f"Method {self.command} not allowed; this API is read-only", {"Allow": "GET"})

    do_HEAD = do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = _not_allowed

    # -- routing --

    def _route(self) -> None:
        parts = urlsplit(self.path)
        matched = match_route(parts.path)
        if matched is None:
            raise HttpError(404, f"No such endpoint: {parts.path}")
        route, params = matched
        query = parse_qs(parts.query, keep_blank_values=True)
        allowed = FILTERS.get(route, ())
        unknown = sorted(set(query) - set(allowed))
        if unknown:
            hint = f"; allowed: {', '.join(allowed)}" if allowed else "; this endpoint takes none"
            raise HttpError(400, f"Unknown filter(s): {', '.join(unknown)}{hint}")
        repeated = sorted(name for name, values in query.items() if len(values) > 1)
        if repeated:
            raise HttpError(400, f"Filter(s) given more than once: {', '.join(repeated)}")
        filters = {name: values[0] for name, values in query.items()}

        if route == "/":
            self._send(302, b"", "text/plain; charset=utf-8", {"Location": "/docs"})
        elif route == "/docs":
            self._send(200, resource("static/docs.html"), "text/html; charset=utf-8",
                       {"Content-Security-Policy": DOCS_CSP})
        elif route == "/docs/assets/{file}":
            if params["file"] not in ASSETS:
                raise HttpError(404, f"No such asset: {params['file']}")
            name, content_type = ASSETS[params["file"]]
            self._send(200, resource(name), content_type)
        elif route == "/openapi.json":
            self._send(200, resource("openapi.json"), "application/json; charset=utf-8")
        else:
            self._api(route, params, filters, self.server.snapshot_provider())

    def _envelope(self, snap: Snapshot, as_of: str | None, stale: bool, data: Any) -> dict[str, Any]:
        return {
            "meta": {
                "api_version": API_VERSION,
                "as_of": as_of,
                "saved_at": snap.saved_at,
                "stale": stale,
                "source": SOURCE,
                "notice": NOTICE,
                "license": LICENSE,
            },
            "data": data,
        }

    def _api(self, route: str, params: dict[str, str], filters: dict[str, str], snap: Snapshot) -> None:
        status = snap.status

        def dataset(name: str) -> tuple[str | None, bool]:
            return status[name]["as_of"], status[name]["stale"]

        stocks_meta = (status["quotes"]["as_of"] or status["listings"]["as_of"],
                       status["quotes"]["stale"] or status["listings"]["stale"])
        overall = (stocks_meta[0], any(status[name]["stale"] for name in ("listings", "quotes", "indices",
                                                                         "corporate_actions")))
        if route == "/v2/":
            data = {"name": "jamstockex", "api_version": API_VERSION, "endpoints": ENDPOINTS,
                    "notice": NOTICE, "source": SOURCE, "license": LICENSE}
            doc = self._envelope(snap, *overall, data)
        elif route == "/v2/status":
            data = {**status, "refreshing": snap.refreshing, "blocked": snap.blocked,
                    "next_check_at": snap.next_check_at, "data_file": snap.data_file}
            doc = self._envelope(snap, *overall, data)
        elif route == "/v2/stocks":
            stocks = list(snap.stocks)
            if "symbol" in filters:
                stocks = [s for s in stocks if _same(s["symbol"], filters["symbol"])]
            if "market" in filters:
                stocks = [s for s in stocks if _same(s["market"], filters["market"])]
            if "listed" in filters:
                listed = _bool("listed", filters["listed"])
                stocks = [s for s in stocks if s["listed"] is listed]
            doc = self._envelope(snap, *stocks_meta, stocks)
        elif route == "/v2/stocks/{instrument_code}":
            code = params["instrument_code"]
            entry = next((s for s in snap.stocks if s["instrument_code"] == code), None)
            if entry is None:
                raise HttpError(404, f"Unknown instrument_code: {code}")
            own = [a for a in snap.actions if a["instrument_code"] == code]
            data = {**entry, "corporate_actions": own, "dividends": [a for a in own if a["type"] == "dividend"]}
            doc = self._envelope(snap, *snap.stock_meta[code], data)
        elif route == "/v2/indices":
            doc = self._envelope(snap, *dataset("indices"), list(snap.indices))
        else:  # /v2/corporate-actions and /v2/dividends
            actions = list(snap.actions)
            if route == "/v2/dividends":
                actions = [a for a in actions if a["type"] == "dividend"]
                if "upcoming" in filters:
                    upcoming = _bool("upcoming", filters["upcoming"])
                    today = self.server.today().isoformat()
                    actions = [a for a in actions
                               if (a["payment_date"] is not None and a["payment_date"] >= today) is upcoming]
            if "symbol" in filters:
                actions = [a for a in actions if _same(a["symbol"], filters["symbol"])]
            if "type" in filters:
                actions = [a for a in actions if _same(a["type"], filters["type"])]
            doc = self._envelope(snap, *dataset("corporate_actions"), actions)
        self._json(200, doc)
