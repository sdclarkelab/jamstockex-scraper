import datetime as dt
import json
import os
from decimal import Decimal

import pytest

from jamstockex import store
from jamstockex.models import Company, CorporateAction, Index, Quote

DAY = dt.date(2026, 11, 9)
NOW = dt.datetime(2026, 11, 9, 22, 30, 5, tzinfo=dt.timezone.utc)


def sample_state() -> store.State:
    state = store.State()
    state.companies = {
        "9001": Company(instrument_code="9001", symbol="ACME", name="Acme Holdings Limited",
                            market="Main Market", currency="JMD", listed_since=DAY,
                            quote=Quote(date=DAY, close=Decimal("12.50"), change=Decimal("-0.25"),
                                        change_pct=Decimal("-1.96"), volume=48213)),
        "9002": Company(instrument_code="9002", symbol="BETA", name="Beta Capital Limited",
                            market="USD Market", currency="USD", listed_since=DAY),
    }
    state.indices = [Index(name="JSE Main Index", date=DAY, value=Decimal("325456.78"), change=None,
                           change_pct=None, volume=None)]
    state.actions = [  # in saved order: by record_date
        CorporateAction(symbol="ZZZ", type="dividend", amount=Decimal("1"), currency="JMD",
                        record_date=dt.date(2026, 5, 1), ex_date=None, payment_date=None),
        CorporateAction(symbol="ACME", type="dividend", amount=Decimal("0.75"), currency="JMD",
                        record_date=dt.date(2026, 11, 20), ex_date=None, payment_date=None,
                        instrument_code="9001"),
    ]
    state.status["quotes"] = store.DatasetStatus(as_of=DAY, fetched_at=NOW, no_data_days=2)
    state.status["corporate_actions"] = store.DatasetStatus(stale=True, last_error="FetchError: boom")
    state.markets = {"Main Market": store.DatasetStatus(as_of=DAY, fetched_at=NOW)}
    state.unmatched = {"9003"}
    state.blocked_close = dt.datetime(2026, 11, 6, 22, 30, tzinfo=dt.timezone.utc)
    state.last_failure_at = NOW
    return state


def test_missing_file_gives_empty_state(tmp_path):
    state = store.load(tmp_path / "jse-data.json")
    assert state.companies == {} and state.indices == [] and state.actions == []
    assert state.markets == {} and state.unmatched == set()
    assert set(state.status) == set(store.DATASETS)
    assert all(s == store.DatasetStatus() for s in state.status.values())
    assert state.saved_at is None and state.blocked_close is None and state.last_failure_at is None


def test_save_then_load_round_trips(tmp_path):
    path = tmp_path / "data" / "jse-data.json"  # parent folder is created
    original = sample_state()
    store.save(original, path, now=NOW)
    assert original.saved_at == NOW
    loaded = store.load(path)
    assert loaded == original


def test_saved_file_is_sorted_utf8_json_with_a_format_version(tmp_path):
    path = tmp_path / "jse-data.json"
    store.save(sample_state(), path, now=NOW)
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert doc["format"] == store.FORMAT_VERSION
    assert doc["saved_at"] == "2026-11-09T22:30:05Z"
    assert [c["instrument_code"] for c in doc["companies"]] == ["9001", "9002"]
    assert [a["symbol"] for a in doc["corporate_actions"]] == ["ZZZ", "ACME"]  # by record_date
    assert doc["unmatched_codes"] == ["9003"]
    assert doc["blocked_close"] == "2026-11-06T22:30:00Z"
    assert doc["status"]["quotes"]["no_data_days"] == 2
    assert "no_data_days" not in doc["status"]["indices"]  # written only when > 0


@pytest.mark.parametrize("step", ["fsync", "replace"])
def test_a_crash_before_the_replace_leaves_the_old_file_intact(tmp_path, monkeypatch, step):
    path = tmp_path / "jse-data.json"
    store.save(sample_state(), path, now=NOW)
    before = path.read_bytes()

    def crash(*args, **kwargs):
        raise OSError("simulated crash")

    monkeypatch.setattr(store.os, step, crash)
    changed = sample_state()
    changed.companies.clear()
    with pytest.raises(OSError, match="simulated crash"):
        store.save(changed, path, now=NOW + dt.timedelta(days=1))
    assert path.read_bytes() == before
    assert [p.name for p in tmp_path.iterdir()] == ["jse-data.json"]  # temp file removed
    assert changed.saved_at is None


@pytest.mark.parametrize("text", [
    "{not json",
    '{"format": 1, "companies": "nope"}',
    '{"format": 99}',
    "[]",
])
def test_corrupt_file_raises_store_error_and_is_untouched(tmp_path, text):
    path = tmp_path / "jse-data.json"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(store.StoreError) as caught:
        store.load(path)
    assert str(path) in str(caught.value)
    assert "left untouched" in str(caught.value)
    assert path.read_text(encoding="utf-8") == text


def test_lock_is_exclusive_and_released(tmp_path):
    path = tmp_path / "jse-data.lock"
    with store.RefreshLock(path):
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["pid"] == os.getpid()
        with pytest.raises(store.LockHeld, match="another refresh is running"):
            store.RefreshLock(path).acquire()
    assert not path.exists()


def test_stale_lock_is_taken_over(tmp_path):
    path = tmp_path / "jse-data.lock"
    path.write_text(json.dumps({"pid": 1, "time": 1_000.0}), encoding="utf-8")
    with pytest.raises(store.LockHeld):
        store.RefreshLock(path, clock=lambda: 1_000.0 + 599).acquire()
    lock = store.RefreshLock(path, clock=lambda: 1_000.0 + 601)
    lock.acquire()
    assert json.loads(path.read_text(encoding="utf-8"))["time"] == 1_601.0
    lock.release()


def test_unreadable_lock_falls_back_to_its_modification_time(tmp_path):
    path = tmp_path / "jse-data.lock"
    path.write_text("garbage", encoding="utf-8")
    os.utime(path, (5_000.0, 5_000.0))
    with pytest.raises(store.LockHeld):
        store.RefreshLock(path, clock=lambda: 5_000.0 + 60).acquire()
    with store.RefreshLock(path, clock=lambda: 5_000.0 + 601):
        assert path.exists()


def test_non_numeric_decimal_raises_store_error_and_is_untouched(tmp_path):
    path = tmp_path / "jse-data.json"
    store.save(sample_state(), path, now=NOW)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["indices"][0]["value"] = "abc"
    text = json.dumps(data)
    path.write_text(text, encoding="utf-8")
    with pytest.raises(store.StoreError, match="left untouched"):
        store.load(path)
    assert path.read_text(encoding="utf-8") == text


def test_deeply_nested_json_raises_store_error(tmp_path):
    path = tmp_path / "jse-data.json"
    path.write_text("[" * 100_000, encoding="utf-8")
    with pytest.raises(store.StoreError):
        store.load(path)


def _stale_lock(path):
    path.write_text(json.dumps({"pid": 1, "time": 1_000.0}), encoding="utf-8")


def test_fresh_lock_created_before_the_retry_is_left_intact(tmp_path, monkeypatch):
    path = tmp_path / "jse-data.lock"
    _stale_lock(path)
    real_unlink = os.unlink

    def unlink_then_other_process_locks(target, *args, **kwargs):
        real_unlink(target, *args, **kwargs)
        monkeypatch.setattr(os, "unlink", real_unlink)
        path.write_text(json.dumps({"pid": 4242, "time": 1_000.0 + 601}), encoding="utf-8")

    def no_link(*args, **kwargs):
        raise AssertionError("os.link must not be used")

    monkeypatch.setattr(os, "unlink", unlink_then_other_process_locks)
    monkeypatch.setattr(os, "link", no_link)
    lock = store.RefreshLock(path, clock=lambda: 1_000.0 + 601)
    with pytest.raises(store.LockHeld):
        lock.acquire()
    assert not lock.held
    assert json.loads(path.read_text(encoding="utf-8"))["pid"] == 4242
    assert [p.name for p in tmp_path.iterdir()] == ["jse-data.lock"]


def test_takeover_permission_error_is_lock_held(tmp_path, monkeypatch):
    path = tmp_path / "jse-data.lock"
    _stale_lock(path)

    def denied(target, *args, **kwargs):
        raise PermissionError("in use")

    monkeypatch.setattr(os, "unlink", denied)
    with pytest.raises(store.LockHeld):
        store.RefreshLock(path, clock=lambda: 1_000.0 + 601).acquire()


def test_failed_lock_write_removes_the_lock_file(tmp_path, monkeypatch):
    path = tmp_path / "jse-data.lock"

    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(store.json, "dump", boom)
    lock = store.RefreshLock(path)
    with pytest.raises(OSError, match="disk full"):
        lock.acquire()
    assert not path.exists()
    assert not lock.held
