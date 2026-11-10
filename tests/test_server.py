import datetime as dt
import http.client
import importlib.resources
import inspect
import json
import threading
from decimal import Decimal

import pytest

from jamstockex import server, store
from jamstockex.models import Company, CorporateAction, Index, Quote
from tests.helpers import JSE_URL

DAY = dt.date(2026, 11, 9)
NOW = dt.datetime(2026, 11, 9, 22, 31, 4, tzinfo=dt.timezone.utc)
TODAY = dt.date(2026, 11, 25)
META_KEYS = {"api_version", "as_of", "saved_at", "stale", "source", "notice", "license"}


def action(symbol, code, type_="dividend", record=None, payment=None, amount="0.75", currency="JMD"):
    return CorporateAction(symbol=symbol, type=type_, amount=Decimal(amount) if amount else None,
                           currency=currency, record_date=record, ex_date=None, payment_date=payment,
                           instrument_code=code)


def sample_state():
    state = store.State(saved_at=NOW)
    quote = Quote(date=DAY, close=Decimal("12.50"), change=Decimal("-0.25"), change_pct=Decimal("-1.96"),
                  volume=48213)
    state.companies = {
        "9001": Company(instrument_code="9001", symbol="ACME", name="Acme Holdings Limited",
                            market="Main Market", currency="JMD", website="https://www.acme.example",
                            listed_since=DAY, quote=quote),
        "9002": Company(instrument_code="9002", symbol="BETA", name="Beta Capital Limited",
                            market="USD Market", currency="USD", listed_since=DAY),
        "9005": Company(instrument_code="9005", symbol="OLD", name="Old Co", market="Main Market",
                           listed=False, delisted_on=DAY),
    }
    state.indices = [Index(name="JSE Main Index", date=DAY, value=Decimal("325456.78"), change=None,
                           change_pct=None, volume=None)]
    state.actions = [
        action("BETA", "9002", record=dt.date(2026, 11, 20), payment=dt.date(2026, 12, 4), currency="USD"),
        action("ACME", "9001", record=dt.date(2026, 11, 20), payment=dt.date(2026, 11, 24)),
        action("ACME", "9001", type_="stock_split", record=dt.date(2026, 4, 14), amount=None),
        action("ZZZ", None, record=dt.date(2026, 5, 1), payment=dt.date(2026, 5, 15)),
    ]
    fresh = store.DatasetStatus(as_of=DAY, fetched_at=NOW)
    state.status = {"listings": store.DatasetStatus(as_of=DAY, fetched_at=NOW, stale=True,
                                                    last_error="USD Market: FetchError: x"),
                    "quotes": fresh, "indices": fresh,
                    "corporate_actions": store.DatasetStatus(as_of=DAY, fetched_at=NOW)}
    state.markets = {"Main Market": store.DatasetStatus(as_of=DAY, fetched_at=NOW),
                     "USD Market": store.DatasetStatus(as_of=DAY, stale=True, last_error="FetchError: x")}
    state.unmatched = {"9003"}
    return state


class Holder:
    def __init__(self, snapshot):
        self.snapshot = snapshot

    def __call__(self):
        return self.snapshot


@pytest.fixture
def api():
    holder = Holder(server.Snapshot.from_state(sample_state(), data_file="/data/jse-data.json"))
    srv = server.make_server(0, holder, today=lambda: TODAY)
    thread = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    yield srv, holder
    srv.shutdown()
    srv.server_close()


def request(srv, path, method="GET", host=None, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=5)
    all_headers = {"Host": host or f"127.0.0.1:{srv.port}", **(headers or {})}
    conn.request(method, path, headers=all_headers)
    response = conn.getresponse()
    body = response.read()
    conn.close()
    return response, body


def get_json(srv, path):
    response, body = request(srv, path)
    return response.status, json.loads(body), response


def test_binds_127_0_0_1_only_and_has_no_host_option(api):
    srv, _ = api
    assert srv.server_address[0] == "127.0.0.1"
    assert "host" not in inspect.signature(server.make_server).parameters


def test_status(api):
    srv, _ = api
    status, doc, _ = get_json(srv, "/v2/status")
    assert status == 200
    assert set(doc) == {"meta", "data"} and set(doc["meta"]) == META_KEYS
    data = doc["data"]
    assert set(data) == {"listings", "quotes", "indices", "corporate_actions", "refreshing", "blocked",
                         "next_check_at", "data_file"}
    assert data["quotes"] == {"as_of": "2026-11-09", "fetched_at": "2026-11-09T22:31:04Z", "stale": False,
                              "last_error": None}
    assert data["listings"]["markets"]["USD Market"]["last_error"] == "FetchError: x"
    assert data["listings"]["unmatched_codes"] == ["9003"]
    assert data["refreshing"] is False and data["blocked"] is False and data["next_check_at"] is None
    assert data["data_file"] == "/data/jse-data.json"
    assert doc["meta"]["stale"] is True  # listings is stale
    assert doc["meta"]["saved_at"] == "2026-11-09T22:31:04Z"


def test_index_lists_endpoints(api):
    status, doc, _ = get_json(api[0], "/v2/")
    assert status == 200
    assert doc["data"]["endpoints"]["stock"] == "/v2/stocks/{instrument_code}"


def test_stocks_sorted_with_quotes_and_meta(api):
    status, doc, _ = get_json(api[0], "/v2/stocks")
    assert status == 200
    assert [s["instrument_code"] for s in doc["data"]] == ["9001", "9002", "9005"]
    assert doc["data"][0]["quote"] == {"date": "2026-11-09", "close": 12.5, "change": -0.25,
                                       "change_pct": -1.96, "volume": 48213}
    assert doc["meta"]["as_of"] == "2026-11-09" and doc["meta"]["stale"] is True


@pytest.mark.parametrize("query, codes", [
    ("symbol=acme", ["9001"]),
    ("market=usd%20market", ["9002"]),
    ("listed=true", ["9001", "9002"]),
    ("listed=FALSE", ["9005"]),
    ("market=Main+Market&listed=true", ["9001"]),
    ("symbol=nope", []),
])
def test_stock_filters(api, query, codes):
    status, doc, _ = get_json(api[0], f"/v2/stocks?{query}")
    assert status == 200
    assert [s["instrument_code"] for s in doc["data"]] == codes


def test_one_stock_with_actions_and_per_market_stale(api):
    status, doc, _ = get_json(api[0], "/v2/stocks/9001")
    assert status == 200
    assert [a["type"] for a in doc["data"]["corporate_actions"]] == ["stock_split", "dividend"]
    assert [a["type"] for a in doc["data"]["dividends"]] == ["dividend"]
    assert doc["meta"] == {**doc["meta"], "as_of": "2026-11-09", "stale": False}  # Main Market is fine
    _, beta, _ = get_json(api[0], "/v2/stocks/9002")
    assert beta["meta"]["stale"] is True  # USD Market failed
    assert beta["meta"]["as_of"] == "2026-11-09"  # no quote: its market's as_of


def test_unknown_stock_is_404(api):
    status, doc, _ = get_json(api[0], "/v2/stocks/9099")
    assert status == 404
    assert doc == {"error": {"status": 404, "message": "Unknown instrument_code: 9099"}}


def test_indices(api):
    status, doc, _ = get_json(api[0], "/v2/indices")
    assert status == 200 and [i["name"] for i in doc["data"]] == ["JSE Main Index"]


def test_corporate_actions_sorted_by_record_date_then_symbol(api):
    status, doc, _ = get_json(api[0], "/v2/corporate-actions")
    assert status == 200
    assert [(a["record_date"], a["symbol"]) for a in doc["data"]] == [
        ("2026-04-14", "ACME"), ("2026-05-01", "ZZZ"), ("2026-11-20", "ACME"), ("2026-11-20", "BETA")]


@pytest.mark.parametrize("path, symbols", [
    ("/v2/corporate-actions?type=STOCK_SPLIT", ["ACME"]),
    ("/v2/corporate-actions?symbol=acme&type=dividend", ["ACME"]),
    ("/v2/dividends", ["ZZZ", "ACME", "BETA"]),
    ("/v2/dividends?upcoming=true", ["BETA"]),      # payment 2026-12-04 >= 2026-11-25
    ("/v2/dividends?upcoming=false", ["ZZZ", "ACME"]),
    ("/v2/dividends?symbol=Beta", ["BETA"]),
])
def test_action_filters(api, path, symbols):
    status, doc, _ = get_json(api[0], path)
    assert status == 200
    assert [a["symbol"] for a in doc["data"]] == symbols


@pytest.mark.parametrize("path, message", [
    ("/v2/stocks?sort=name", "Unknown filter(s): sort; allowed: symbol, market, listed"),
    ("/v2/status?x=1", "Unknown filter(s): x; this endpoint takes none"),
    ("/v2/stocks?listed=yes", "Invalid value for listed: 'yes' (use true or false)"),
    ("/v2/dividends?upcoming=", "Invalid value for upcoming: '' (use true or false)"),
    ("/v2/stocks?symbol=A&symbol=B", "Filter(s) given more than once: symbol"),
])
def test_bad_requests(api, path, message):
    status, doc, _ = get_json(api[0], path)
    assert status == 400
    assert doc == {"error": {"status": 400, "message": message}}


def test_unknown_path_is_404(api):
    status, doc, _ = get_json(api[0], "/v3/stocks")
    assert status == 404 and doc["error"]["message"] == "No such endpoint: /v3/stocks"


@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"])
def test_other_methods_are_405_with_allow_get(api, method):
    response, body = request(api[0], "/v2/stocks", method=method)
    assert response.status == 405
    assert response.getheader("Allow") == "GET"
    if method != "HEAD":
        assert json.loads(body)["error"]["status"] == 405


def test_unhandled_error_is_a_generic_500(api, caplog):
    srv, holder = api

    def broken():
        raise RuntimeError("secret detail")

    srv.snapshot_provider = broken
    status, doc, _ = get_json(srv, "/v2/stocks")
    assert status == 500
    assert doc == {"error": {"status": 500, "message": "Internal server error"}}
    assert "RuntimeError: secret detail" in caplog.text  # traceback on the console only


@pytest.mark.parametrize("host", ["evil.example:{port}", "127.0.0.1", "localhost:1", "127.0.0.1:{port}.evil"])
def test_other_host_headers_are_403(api, host):
    srv, _ = api
    response, body = request(srv, "/v2/status", host=host.format(port=srv.port))
    assert response.status == 403
    assert response.getheader("Content-Type") == "text/plain; charset=utf-8"
    assert b"127.0.0.1:" in body


def test_missing_host_header_is_403(api):
    srv, _ = api
    conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=5)
    conn.putrequest("GET", "/v2/status", skip_host=True)
    conn.endheaders()
    assert conn.getresponse().status == 403
    conn.close()


def test_localhost_host_header_is_allowed(api):
    srv, _ = api
    response, _ = request(srv, "/v2/status", host=f"localhost:{srv.port}")
    assert response.status == 200


@pytest.mark.parametrize("path", ["/v2/stocks", "/v2/nope", "/docs", "/", "/openapi.json"])
def test_security_headers_and_no_cors(api, path):
    response, _ = request(api[0], path, headers={"Origin": "https://evil.example"})
    assert response.getheader("X-Content-Type-Options") == "nosniff"
    assert response.getheader("Cache-Control") == "no-store"
    assert not [name for name, _ in response.getheaders() if name.lower().startswith("access-control-")]


def test_403_also_has_security_headers(api):
    response, _ = request(api[0], "/v2/stocks", host="evil.example")
    assert response.getheader("X-Content-Type-Options") == "nosniff"
    assert response.getheader("Cache-Control") == "no-store"


def test_docs_page_and_csp(api):
    response, body = request(api[0], "/docs")
    assert response.status == 200
    assert response.getheader("Content-Type") == "text/html; charset=utf-8"
    assert response.getheader("Content-Security-Policy") == (
        "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'")
    assert b"/docs/assets/swagger-ui-bundle.js" in body


@pytest.mark.parametrize("name, content_type, resource", [
    ("swagger-ui-bundle.js", "text/javascript; charset=utf-8", "static/swagger/swagger-ui-bundle.js"),
    ("swagger-ui.css", "text/css; charset=utf-8", "static/swagger/swagger-ui.css"),
    ("docs-init.js", "text/javascript; charset=utf-8", "static/docs-init.js"),
])
def test_docs_assets_are_served(api, name, content_type, resource):
    response, body = request(api[0], f"/docs/assets/{name}")
    assert response.status == 200
    assert response.getheader("Content-Type") == content_type
    assert body == importlib.resources.files("jamstockex").joinpath(resource).read_bytes()


@pytest.mark.parametrize("name", ["LICENSE", "..%2Fopenapi.json", "nope.js"])
def test_other_assets_are_404(api, name):
    response, _ = request(api[0], f"/docs/assets/{name}")
    assert response.status == 404


def test_root_redirects_to_docs(api):
    response, _ = request(api[0], "/")
    assert response.status == 302 and response.getheader("Location") == "/docs"


def test_openapi_json_is_served(api):
    response, body = request(api[0], "/openapi.json")
    assert response.status == 200
    assert response.getheader("Content-Type") == "application/json; charset=utf-8"
    assert body == importlib.resources.files("jamstockex").joinpath("openapi.json").read_bytes()


def test_json_is_minified_sorted_utf8(api):
    response, body = request(api[0], "/v2/stocks")
    assert response.getheader("Content-Type") == "application/json; charset=utf-8"
    doc = json.loads(body)
    assert body == json.dumps(doc, separators=(",", ":"), sort_keys=True, ensure_ascii=False).encode("utf-8")


def test_snapshot_swap_while_serving(api):
    srv, holder = api
    state = sample_state()
    del state.companies["9002"]
    state.blocked_close = NOW
    holder.snapshot = server.Snapshot.from_state(state, data_file="/data/jse-data.json").with_runtime(
        refreshing=True, next_check_at=NOW)
    _, doc, _ = get_json(srv, "/v2/stocks")
    assert [s["instrument_code"] for s in doc["data"]] == ["9001", "9005"]
    _, status, _ = get_json(srv, "/v2/status")
    assert status["data"]["refreshing"] is True and status["data"]["blocked"] is True
    assert status["data"]["next_check_at"] == "2026-11-09T22:31:04Z"


def test_empty_state_is_served(api):
    srv, holder = api
    holder.snapshot = server.Snapshot.from_state(store.State(), data_file="x")
    _, doc, _ = get_json(srv, "/v2/stocks")
    assert doc["data"] == [] and doc["meta"]["as_of"] is None and doc["meta"]["saved_at"] is None


def example_path(path):
    return path.replace("{instrument_code}", "9001").replace("{file}", "swagger-ui.css")


def test_every_route_is_documented_and_every_documented_path_is_answered(api):
    openapi = json.loads(importlib.resources.files("jamstockex").joinpath("openapi.json").read_text("utf-8"))
    assert set(openapi["paths"]) == set(server.ROUTES)
    for path, item in openapi["paths"].items():
        documented = {p["name"] for p in item["get"].get("parameters", []) if p["in"] == "query"}
        assert documented == set(server.FILTERS.get(path, ())), path
        response, _ = request(api[0], example_path(path))
        assert response.status in (200, 302), path


def test_no_jse_links_in_any_response(api):
    for path in server.ROUTES:
        if path.startswith("/v2/"):
            _, body = request(api[0], example_path(path))
            assert not JSE_URL.search(body.decode("utf-8")), path
