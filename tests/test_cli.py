import datetime as dt
import http.client
import json
import queue
import socket
import threading
from pathlib import Path

import pytest

import jamstockex.__main__ as cli
from jamstockex import store
from jamstockex.config import JAMAICA, default_config
from jamstockex.fetch import BlockedError
from jamstockex.refresh import BLOCKED_MESSAGE
from tests.fakes import FakeFetcher, pages

NOW = dt.datetime(2026, 11, 9, 18, 0, tzinfo=JAMAICA)  # Monday, after the close


@pytest.fixture
def fake_site(monkeypatch):
    """Patches the CLI's Fetcher and clock. Returns the list of fetchers the CLI created."""
    created = []

    def factory(source, page_map=None):
        fetcher = FakeFetcher(pages(page_map))
        created.append(fetcher)
        return fetcher

    monkeypatch.setattr(cli, "Fetcher", factory)
    monkeypatch.setattr(cli, "utcnow", lambda: NOW)
    return created


@pytest.fixture
def no_network(monkeypatch):
    def refuse(source):
        raise AssertionError("no Fetcher may be created")

    monkeypatch.setattr(cli, "Fetcher", refuse)
    monkeypatch.setattr(cli, "utcnow", lambda: NOW)


@pytest.mark.parametrize("platform, env, expected", [
    ("darwin", {}, "/home/u/Library/Application Support/jamstockex"),
    ("win32", {"APPDATA": "/appdata"}, "/appdata/jamstockex"),
    ("win32", {}, "/home/u/AppData/Roaming/jamstockex"),
    ("linux", {"XDG_DATA_HOME": "/xdg"}, "/xdg/jamstockex"),
    ("linux", {"XDG_DATA_HOME": "relative/path"}, "/home/u/.local/share/jamstockex"),
    ("linux", {}, "/home/u/.local/share/jamstockex"),
])
def test_default_data_dir(platform, env, expected):
    assert cli.default_data_dir(platform=platform, env=env, home=Path("/home/u")) == Path(expected)


def test_version(capsys):
    with pytest.raises(SystemExit) as caught:
        cli.main(["--version"])
    assert caught.value.code == 0
    assert capsys.readouterr().out.strip() == "jamstockex 2.0.0"


def test_there_is_no_host_option(capsys):
    with pytest.raises(SystemExit) as caught:
        cli.main(["--host", "0.0.0.0"])
    assert caught.value.code == 2


def test_config_error_exits_2_naming_the_file(tmp_path, capsys, no_network):
    (tmp_path / "config.toml").write_text("[server]\nport = 0\n", encoding="utf-8")
    assert cli.main(["refresh", "--data-dir", str(tmp_path)]) == 2
    err = capsys.readouterr().err
    assert str(tmp_path / "config.toml") in err and "server.port" in err


def test_corrupt_data_file_exits_2(tmp_path, capsys, no_network):
    (tmp_path / "jse-data.json").write_text("{oops", encoding="utf-8")
    assert cli.main(["--offline", "--data-dir", str(tmp_path), "--port", "0"]) == 2
    assert "left untouched" in capsys.readouterr().err
    assert (tmp_path / "jse-data.json").read_text(encoding="utf-8") == "{oops"


def test_refresh_saves_and_prints_the_report(tmp_path, capsys, fake_site):
    assert cli.main(["refresh", "--data-dir", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "JSE refresh for trading day 2026-11-09" in out and "Requests to the JSE site: 6" in out
    state = store.load(tmp_path / "jse-data.json")
    assert set(state.companies) == {"9001", "9002"}
    assert not (tmp_path / "jse-data.lock").exists()

    assert cli.main(["refresh", "--data-dir", str(tmp_path)]) == 0  # same close: nothing due
    assert "Nothing is due" in capsys.readouterr().out
    assert fake_site[-1].paths == []


def test_refresh_listings_flag_forces_all_markets(tmp_path, capsys, fake_site):
    cli.main(["refresh", "--data-dir", str(tmp_path)])
    cli.main(["refresh", "--listings", "--data-dir", str(tmp_path)])
    assert [p for p in fake_site[-1].paths if p.startswith("/listings/")] == [
        f"/listings/listed-companies/?market={code}" for code in (31, 22, 51, 49)]


def test_refresh_blocked_exits_1_with_the_blocked_message(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(cli, "Fetcher", lambda source: FakeFetcher(pages({"/trading/trade-quotes/": BlockedError("HTTP 403")})))
    monkeypatch.setattr(cli, "utcnow", lambda: NOW)
    assert cli.main(["refresh", "--data-dir", str(tmp_path)]) == 1
    assert BLOCKED_MESSAGE in capsys.readouterr().out
    assert store.load(tmp_path / "jse-data.json").blocked_close is not None


def test_refresh_exits_1_when_another_refresh_holds_the_lock(tmp_path, capsys, no_network):
    with store.RefreshLock(tmp_path / "jse-data.lock"):
        assert cli.main(["refresh", "--data-dir", str(tmp_path)]) == 1
    assert "another refresh is running" in capsys.readouterr().err


def test_port_in_use_exits_2(tmp_path, capsys, no_network):
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        port = busy.getsockname()[1]
        assert cli.main(["--offline", "--data-dir", str(tmp_path), "--port", str(port)]) == 2
    assert f"Port {port} is in use; try --port {port + 1}" in capsys.readouterr().err


def start_serving(argv):
    """Runs cli.main(argv) in a thread; returns (server, thread, result queue)."""
    ready, result = queue.Queue(), queue.Queue()
    thread = threading.Thread(target=lambda: result.put(cli.main(argv, on_ready=ready.put)), daemon=True)
    thread.start()
    return ready.get(timeout=10), thread, result


def get(server, path):
    conn = http.client.HTTPConnection("127.0.0.1", server.port, timeout=5)
    conn.request("GET", path)
    response = conn.getresponse()
    body = response.read()
    conn.close()
    return response.status, body


def test_serve_offline_makes_no_fetcher_calls(tmp_path, capsys, no_network):
    server, thread, result = start_serving(["--offline", "--data-dir", str(tmp_path), "--port", "0"])
    status, body = get(server, "/v2/status")
    assert status == 200
    assert json.loads(body)["data"]["data_file"] == str(tmp_path / "jse-data.json")
    server.shutdown()
    thread.join(timeout=10)
    assert result.get(timeout=1) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0] == f"JSE data API running at http://127.0.0.1:{server.port}/v2/   docs: http://127.0.0.1:{server.port}/docs"
    assert out[1] == f"Data: {tmp_path / 'jse-data.json'} (as of no data yet)"
    assert out[2] == "Offline: not refreshing (Ctrl+C to stop)"


def test_serve_refreshes_in_the_background(tmp_path, capsys, fake_site):
    server, thread, result = start_serving(["serve", "--data-dir", str(tmp_path), "--port", "0"])
    deadline = dt.datetime.now() + dt.timedelta(seconds=10)
    while True:
        status, body = get(server, "/v2/stocks")
        if json.loads(body)["data"] or dt.datetime.now() > deadline:
            break
        threading.Event().wait(0.05)
    assert [s["instrument_code"] for s in json.loads(body)["data"]] == ["9001", "9002"]
    server.shutdown()
    thread.join(timeout=10)
    assert result.get(timeout=1) == 0
    out = capsys.readouterr().out
    assert "Refreshing in background… (Ctrl+C to stop)" in out
    assert "Refreshed: data as of 2026-11-09 (6 request(s) to the JSE site)." in out
    assert store.load(tmp_path / "jse-data.json").status["quotes"].as_of == dt.date(2026, 11, 9)


def test_service_check_is_a_clock_comparison_when_nothing_is_due(tmp_path, fake_site):
    service = cli.Service(default_config(), tmp_path, store.State())
    assert service.check() is not None  # first check refreshes
    assert service.check() is None      # same close: no fetcher created
    assert len(fake_site) == 1


def test_service_does_not_retry_after_a_block_until_the_next_close(tmp_path, capsys, monkeypatch):
    created = []
    monkeypatch.setattr(cli, "Fetcher", lambda source: created.append(1) or FakeFetcher(
        pages({"/trading/trade-quotes/": BlockedError("HTTP 403")})))
    clock = [NOW]
    monkeypatch.setattr(cli, "utcnow", lambda: clock[0])
    service = cli.Service(default_config(), tmp_path, store.State())
    assert service.check().blocked
    assert BLOCKED_MESSAGE in capsys.readouterr().out
    clock[0] = NOW + dt.timedelta(hours=20)  # Tuesday 14:00, before the next close
    assert service.check() is None
    assert len(created) == 1
    clock[0] = dt.datetime(2026, 11, 10, 17, 30, tzinfo=JAMAICA)
    assert service.check() is not None
    assert len(created) == 2


def test_service_skips_a_check_while_another_refresh_holds_the_lock(tmp_path, capsys, no_network):
    service = cli.Service(default_config(), tmp_path, store.State())
    with store.RefreshLock(tmp_path / "jse-data.lock"):
        assert service.check() is None
    assert "Another refresh is running" in capsys.readouterr().err


class BlockingFetcher(FakeFetcher):
    """Blocks the first request until released, so a refresh can be caught in flight."""

    def __init__(self, started, release):
        super().__init__(pages())
        self.started, self.release = started, release

    def get(self, path):
        self.started.set()
        assert self.release.wait(10)
        return super().get(path)


def test_ctrl_c_during_a_background_refresh_leaves_no_lock_behind(tmp_path, capsys, monkeypatch):
    started, release = threading.Event(), threading.Event()
    monkeypatch.setattr(cli, "Fetcher", lambda source: BlockingFetcher(started, release))
    monkeypatch.setattr(cli, "utcnow", lambda: NOW)
    monkeypatch.setattr(cli, "SHUTDOWN_JOIN_TIMEOUT_S", 0.1)
    store.save(store.State(), tmp_path / "jse-data.json", now=NOW)
    before = (tmp_path / "jse-data.json").read_bytes()

    def interrupt(server):
        assert started.wait(10)
        assert (tmp_path / "jse-data.lock").exists()
        raise KeyboardInterrupt

    try:
        assert cli.main(["serve", "--data-dir", str(tmp_path), "--port", "0"], on_ready=interrupt) == 0
        assert not (tmp_path / "jse-data.lock").exists()
        assert (tmp_path / "jse-data.json").read_bytes() == before
        assert "refresh was interrupted" in capsys.readouterr().out
    finally:
        release.set()
    for t in threading.enumerate():
        if t.name == "refresh":
            t.join(timeout=10)
    assert (tmp_path / "jse-data.json").read_bytes() == before  # the abandoned refresh saves nothing


def test_service_reloads_state_after_taking_the_lock(tmp_path, fake_site, monkeypatch):
    service = cli.Service(default_config(), tmp_path, store.State())
    real_acquire = store.RefreshLock.acquire

    done = []

    def acquire_after_concurrent_save(lock):
        if not done:
            done.append(1)
            assert cli.main(["refresh", "--data-dir", str(tmp_path)]) == 0  # another process refreshes first
        real_acquire(lock)

    monkeypatch.setattr(store.RefreshLock, "acquire", acquire_after_concurrent_save)
    assert service.check() is None  # the concurrent save made it current: nothing left to fetch
    assert len(fake_site) == 1      # only the concurrent refresh created a fetcher
    assert service.state.status["quotes"].as_of == dt.date(2026, 11, 9)


def test_refresh_save_failure_exits_2_naming_the_data_file(tmp_path, capsys, fake_site, monkeypatch):
    def boom(*args, **kwargs):
        raise PermissionError("disk full")

    monkeypatch.setattr(store, "save", boom)
    assert cli.main(["refresh", "--data-dir", str(tmp_path)]) == 2
    err = capsys.readouterr().err
    assert str(tmp_path / "jse-data.json") in err and len(err.strip().splitlines()) == 1
    assert not (tmp_path / "jse-data.lock").exists()
