"""CLI: `jamstockex [serve] [--port N] [--offline]`, `jamstockex refresh [--listings]`, `--version`.

Every command takes `--data-dir`; the default is the per-user data folder.
Exit codes: 0 ok; 1 a dataset failed, the site blocked us, or another refresh
holds the lock; 2 a config, data-file or port problem.
"""

from __future__ import annotations

import argparse
import datetime as dt
import errno
import logging
import os
import sys
import threading
from pathlib import Path
from typing import Callable

from jamstockex import __version__, store
from jamstockex.config import Config, ConfigError, load_config
from jamstockex.fetch import Fetcher
from jamstockex.refresh import BLOCKED_MESSAGE, Report, due, run_refresh
from jamstockex.server import LocalServer, Snapshot, make_server

log = logging.getLogger("jamstockex")


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def default_data_dir(platform: str | None = None, env: dict[str, str] | None = None,
                     home: Path | None = None) -> Path:
    platform = sys.platform if platform is None else platform
    env = dict(os.environ) if env is None else env
    home = Path.home() if home is None else home
    if platform == "darwin":
        return home / "Library" / "Application Support" / "jamstockex"
    if platform == "win32":
        appdata = env.get("APPDATA")
        return (Path(appdata) if appdata else home / "AppData" / "Roaming") / "jamstockex"
    xdg = env.get("XDG_DATA_HOME", "")
    if xdg and Path(xdg).is_absolute():
        return Path(xdg) / "jamstockex"
    return home / ".local" / "share" / "jamstockex"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jamstockex",
        description="Keeps JSE end-of-day data in a local file and serves it on http://127.0.0.1 only.",
    )
    parser.add_argument("--version", action="version", version=f"jamstockex {__version__}")
    parser.add_argument("--data-dir", help="data folder (default: the per-user data folder)")
    parser.add_argument("--port", type=int, help="serve: port on 127.0.0.1 (default 8765)")
    parser.add_argument("--offline", action="store_true", help="serve: don't refresh")
    commands = parser.add_subparsers(dest="command", metavar="{serve,refresh}")
    serve = commands.add_parser("serve", help="serve the API and refresh in the background (the default)")
    serve.add_argument("--data-dir", default=argparse.SUPPRESS)
    serve.add_argument("--port", type=int, default=argparse.SUPPRESS)
    serve.add_argument("--offline", action="store_true", default=argparse.SUPPRESS)
    refresh = commands.add_parser("refresh", help="refresh what is due now, print the report, and exit")
    refresh.add_argument("--data-dir", default=argparse.SUPPRESS)
    refresh.add_argument("--listings", action="store_true", help="also refresh every market's listings")
    return parser


def main(argv: list[str] | None = None, *, on_ready: Callable[[LocalServer], None] | None = None) -> int:
    args = build_parser().parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    data_dir = Path(args.data_dir) if args.data_dir else default_data_dir()
    try:
        config = load_config(data_dir)
    except ConfigError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2
    if args.command == "refresh":
        return cmd_refresh(config, data_dir, force_listings=args.listings)
    return cmd_serve(config, data_dir, port=config.port if args.port is None else args.port,
                     offline=args.offline, on_ready=on_ready)


def cmd_refresh(config: Config, data_dir: Path, *, force_listings: bool) -> int:
    data_file = data_dir / store.DATA_FILE
    try:
        with store.RefreshLock(data_dir / store.LOCK_FILE):
            state = store.load(data_file)
            report = run_refresh(state, Fetcher(config.source), utcnow(), config, force_listings=force_listings)
            if report.attempted:
                store.save(state, data_file, now=utcnow())
    except store.LockHeld:
        print("another refresh is running", file=sys.stderr)
        return 1
    except store.StoreError as exc:
        print(f"Data file error: {exc}", file=sys.stderr)
        return 2
    print(report.text())
    return report.exit_code


class Service:
    """Holds the served snapshot and runs automatic refreshes for `serve`."""

    def __init__(self, config: Config, data_dir: Path, state: store.State) -> None:
        self.config = config
        self.data_file = data_dir / store.DATA_FILE
        self.lock_file = data_dir / store.LOCK_FILE
        self.state = state
        self.refreshing = False
        self.next_check_at: dt.datetime | None = None
        self._snapshot = Snapshot.from_state(state, data_file=str(self.data_file))

    def snapshot(self) -> Snapshot:
        return self._snapshot

    def _publish(self) -> None:
        self._snapshot = Snapshot.from_state(self.state, data_file=str(self.data_file)).with_runtime(
            refreshing=self.refreshing, next_check_at=self.next_check_at)

    def check(self) -> Report | None:
        """One check: a clock comparison, then a refresh only if one is due and allowed."""
        now = utcnow()
        try:
            self.state = store.load(self.data_file)  # pick up a `jamstockex refresh` run meanwhile
        except store.StoreError as exc:
            print(f"Data file error: {exc}", file=sys.stderr)
            return None
        self._publish()
        if not due(self.state, now, self.config).automatic_allowed(now):
            return None
        lock = store.RefreshLock(self.lock_file)
        try:
            lock.acquire()
        except store.LockHeld:
            print("Another refresh is running; skipping this check.", file=sys.stderr)
            return None
        try:
            self.refreshing = True
            self._publish()
            report = run_refresh(self.state, Fetcher(self.config.source), now, self.config)
            if report.attempted:
                store.save(self.state, self.data_file, now=utcnow())
        finally:
            self.refreshing = False
            lock.release()
            self._publish()
        if report.blocked:
            print(BLOCKED_MESSAGE, flush=True)
        elif report.errors:
            print(f"Refresh failed for {', '.join(sorted(report.errors))}; will retry in "
                  f"{self.config.refresh.retry_after_failure_minutes} minutes.", flush=True)
        else:
            print(f"Refreshed: data as of {report.trade_date.isoformat()} "
                  f"({report.requests} request(s) to the JSE site).", flush=True)
        return report

    def run(self, stop: threading.Event) -> None:
        interval = self.config.refresh.check_every_minutes * 60
        while not stop.is_set():
            try:
                self.check()
            except Exception:
                log.exception("Background refresh failed")
            self.next_check_at = utcnow() + dt.timedelta(seconds=interval)
            self._publish()
            stop.wait(interval)


def cmd_serve(config: Config, data_dir: Path, *, port: int, offline: bool,
              on_ready: Callable[[LocalServer], None] | None = None) -> int:
    data_file = data_dir / store.DATA_FILE
    try:
        state = store.load(data_file)
    except store.StoreError as exc:
        print(f"Data file error: {exc}", file=sys.stderr)
        return 2
    service = Service(config, data_dir, state)
    try:
        server = make_server(port, service.snapshot)
    except OSError as exc:
        if exc.errno == errno.EADDRINUSE:
            print(f"Port {port} is in use; try --port {port + 1}", file=sys.stderr)
        else:
            print(f"Can't listen on 127.0.0.1:{port}: {exc}", file=sys.stderr)
        return 2
    base = f"http://127.0.0.1:{server.port}"
    as_of = state.status["quotes"].as_of or state.status["listings"].as_of
    print(f"JSE data API running at {base}/v2/   docs: {base}/docs")
    print(f"Data: {data_file} (as of {as_of.isoformat() if as_of else 'no data yet'})")
    print("Offline: not refreshing (Ctrl+C to stop)" if offline else "Refreshing in background… (Ctrl+C to stop)",
          flush=True)
    stop = threading.Event()
    worker = None
    if not offline:
        worker = threading.Thread(target=service.run, args=(stop,), name="refresh", daemon=True)
        worker.start()
    if on_ready is not None:
        on_ready(server)
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        print("Stopping.")
    finally:
        stop.set()
        if worker is not None:
            worker.join(timeout=5)
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
