"""The release helpers in .github/, run locally against the source tree (offline)."""

import socket
import subprocess
import sys
import zipfile

from tests.helpers import ROOT


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def smoke(*command):
    return subprocess.run(
        [sys.executable, str(ROOT / ".github" / "smoke_test.py"), "--port", str(free_port()), "--timeout", "30",
         "--", *command],
        capture_output=True, text=True, timeout=90,
    )


def test_smoke_test_passes_against_the_source_tree():
    result = smoke(sys.executable, "-m", "jamstockex")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "/v2/status -> 200" in result.stdout
    assert "/docs -> 200" in result.stdout
    assert "/openapi.json -> 200" in result.stdout
    assert "/docs/assets/swagger-ui-bundle.js -> 200" in result.stdout


def test_smoke_test_fails_when_the_app_exits_early():
    result = smoke(sys.executable, "-c", "import sys; sys.exit(3)")
    assert result.returncode != 0
    assert "exited early with code 3" in result.stdout + result.stderr


def test_pyz_builds_runs_and_keeps_exit_codes(tmp_path):
    target = tmp_path / "jamstockex.pyz"
    subprocess.run([sys.executable, str(ROOT / ".github" / "build_pyz.py"), str(target)], check=True,
                   capture_output=True)
    names = zipfile.ZipFile(target).namelist()
    assert "__main__.py" in names
    assert "jamstockex/openapi.json" in names
    assert "jamstockex/static/swagger/swagger-ui-bundle.js" in names
    assert not [n for n in names if "__pycache__" in n]
    assert target.read_bytes().startswith(b"#!/usr/bin/env python3\n")

    version = subprocess.run([sys.executable, str(target), "--version"], capture_output=True, text=True)
    assert version.returncode == 0 and version.stdout.strip() == "jamstockex 2.0.0"

    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "config.toml").write_text("[server]\nport = 0\n", encoding="utf-8")
    bad = subprocess.run([sys.executable, str(target), "refresh", "--data-dir", str(tmp_path / "data")],
                         capture_output=True, text=True)
    assert bad.returncode == 2  # exit codes survive the zipapp entry point

    result = smoke(sys.executable, str(target))
    assert result.returncode == 0, result.stdout + result.stderr
