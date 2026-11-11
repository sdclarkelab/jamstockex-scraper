import http.client
import io
import socket
import threading
import urllib.error
from email.message import Message
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

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
    def __init__(self, status, body="", charset="utf-8"):
        self.status = status
        self._body = body.encode(charset)
        self.headers = Message()
        self.headers["Content-Type"] = f"text/html; charset={charset}"

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def http_error(status, body=""):
    return urllib.error.HTTPError("https://www.example.test/x", status, "error", Message(), io.BytesIO(body.encode()))


class FakeOpener:
    """Stands in for urllib's opener: returns or raises the queued outcomes in order."""

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def __call__(self, request, timeout=None):
        self.calls.append({"url": request.full_url, "user_agent": request.get_header("User-agent"),
                           "timeout": timeout})
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def make(outcomes, source=SOURCE):
    opener = FakeOpener(outcomes)
    sleeps = []
    return Fetcher(source, opener=opener, sleep=sleeps.append), opener, sleeps


def test_returns_body_and_sends_user_agent_and_timeout():
    fetcher, opener, sleeps = make([FakeResponse(200, "<html>ok</html>")])
    assert fetcher.get("/path/?x=1") == "<html>ok</html>"
    assert opener.calls == [{"url": "https://www.example.test/path/?x=1", "user_agent": "test-agent/1.0",
                             "timeout": 7}]
    assert sleeps == []
    assert fetcher.request_count == 1


def test_decodes_with_the_declared_charset():
    fetcher, _, _ = make([FakeResponse(200, "café", charset="iso-8859-1")])
    assert fetcher.get("/a") == "café"


def test_delays_between_requests_but_not_before_the_first():
    fetcher, _, sleeps = make([FakeResponse(200, "a"), FakeResponse(200, "b")])
    fetcher.get("/a")
    fetcher.get("/b")
    assert sleeps == [2.0]
    assert fetcher.request_count == 2


def test_retries_5xx_with_backoff_then_succeeds():
    fetcher, _, sleeps = make([http_error(502), FakeResponse(200, "ok")])
    assert fetcher.get("/a") == "ok"
    assert fetcher.request_count == 2
    assert sleeps == [2.0, 2]  # politeness delay, then backoff 2**1


@pytest.mark.parametrize("error", [
    urllib.error.URLError(ConnectionRefusedError("refused")),
    TimeoutError("timed out"),
    http.client.RemoteDisconnected("closed"),
    ConnectionResetError("reset"),
])
def test_retries_connection_errors_and_timeouts(error):
    fetcher, _, _ = make([error, FakeResponse(200, "ok")])
    assert fetcher.get("/a") == "ok"


def test_gives_up_after_configured_attempts():
    fetcher, _, _ = make([http_error(500), http_error(503), http_error(500)])
    with pytest.raises(FetchError, match="after 3 attempts: HTTP 500"):
        fetcher.get("/a")
    assert fetcher.request_count == 3


def test_404_is_a_fetch_error_without_retry():
    fetcher, opener, _ = make([http_error(404)])
    with pytest.raises(FetchError, match="HTTP 404"):
        fetcher.get("/missing")
    assert len(opener.calls) == 1


@pytest.mark.parametrize("status", [403, 429])
def test_block_status_raises_immediately_and_refuses_further_requests(status):
    fetcher, opener, _ = make([http_error(status)])
    with pytest.raises(BlockedError):
        fetcher.get("/a")
    assert fetcher.blocked is True
    with pytest.raises(BlockedError, match="earlier request was blocked"):
        fetcher.get("/b")
    assert len(opener.calls) == 1
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


JSE = SourceConfig(base_url="https://www.jamstockex.com", user_agent="test-agent/1.0", timeout_s=7,
                   retries=2, delay_s=(0.0, 0.0))
HOST_IN_MESSAGE = socket.gaierror(8, "nodename nor servname provided for www.jamstockex.com")


@pytest.mark.parametrize("outcomes", [
    [http_error(500), http_error(503)],
    [http_error(403)],
    [http_error(404)],
    [urllib.error.URLError(HOST_IN_MESSAGE), urllib.error.URLError(HOST_IN_MESSAGE)],
], ids=["5xx-give-up", "403", "404", "dns-error"])
def test_error_messages_never_contain_the_site_host(outcomes):
    """Messages are shown in /v2/status, which must not link to the JSE site."""
    fetcher, _, _ = make(outcomes, source=JSE)
    with pytest.raises(FetchError) as caught:
        fetcher.get("/trading/trade-quotes/?market=50")
    assert "jamstockex.com" not in str(caught.value)
    assert "/trading/trade-quotes/?market=50" in str(caught.value)


# --- the real urllib path, against a local server on 127.0.0.1 -----------------


class _Handler(BaseHTTPRequestHandler):
    seen: list = []

    def do_GET(self):
        _Handler.seen.append((self.path, self.headers.get("User-Agent")))
        if self.path == "/ok":
            body = "<html>ok é</html>".encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
        elif self.path == "/blocked":
            body = b"Forbidden"
            self.send_response(403)
        else:
            body = b"busy"
            self.send_response(503)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def local_server():
    _Handler.seen = []
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def test_real_urllib_requests_against_a_local_server(local_server):
    source = SourceConfig(base_url=local_server, user_agent="test-agent/1.0", timeout_s=5, retries=2,
                          delay_s=(0.0, 0.0))
    fetcher = Fetcher(source, sleep=lambda seconds: None)
    assert fetcher.get("/ok") == "<html>ok é</html>"
    with pytest.raises(FetchError, match="after 2 attempts: HTTP 503"):
        fetcher.get("/busy")
    with pytest.raises(BlockedError):
        fetcher.get("/blocked")
    assert _Handler.seen == [("/ok", "test-agent/1.0"), ("/busy", "test-agent/1.0"),
                             ("/busy", "test-agent/1.0"), ("/blocked", "test-agent/1.0")]


def test_non_text_charset_falls_back_to_utf8():
    from jamstockex.fetch import _decode
    for charset in ("base64", "rot13", "zlib_codec"):
        assert _decode("café".encode("utf-8"), charset) == "café"
