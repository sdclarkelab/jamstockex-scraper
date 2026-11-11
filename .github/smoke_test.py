"""Start a built artifact offline, check three URLs on 127.0.0.1, stop it.

Usage: python .github/smoke_test.py [--port 8765] [--timeout 90] -- <command...>
e.g.   python .github/smoke_test.py -- dist/jamstockex-linux-x64
       python .github/smoke_test.py -- python dist/jamstockex.pyz

Never contacts the JSE: the artifact runs with --offline and an empty temp data folder.
"""

import argparse
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

PATHS = ("/v2/status", "/docs", "/openapi.json")


def wait_for_port(port: int, process: subprocess.Popen, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise SystemExit(f"FAIL: the app exited early with code {process.returncode}")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return
        except OSError:
            time.sleep(0.5)
    raise SystemExit(f"FAIL: nothing listening on 127.0.0.1:{port} after {timeout:.0f}s")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--timeout", type=float, default=90)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("give the command to start after --")
    with tempfile.TemporaryDirectory() as data_dir:
        process = subprocess.Popen([*command, "--offline", "--data-dir", data_dir, "--port", str(args.port)])
        try:
            wait_for_port(args.port, process, args.timeout)
            for path in PATHS:
                with urllib.request.urlopen(f"http://127.0.0.1:{args.port}{path}", timeout=10) as response:
                    print(f"{path} -> {response.status}")
                    if response.status != 200:
                        raise SystemExit(f"FAIL: {path} returned {response.status}")
        finally:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
    print("smoke test passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
