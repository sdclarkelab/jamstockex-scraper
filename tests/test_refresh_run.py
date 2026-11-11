import datetime as dt

from jamstockex import refresh, store
from jamstockex.config import JAMAICA, default_config
from jamstockex.fetch import BlockedError, FetchError
from tests.fakes import FakeFetcher, pages
from tests.helpers import JSE_URL, fixture_html

SETTINGS = default_config()
NOV_9 = dt.datetime(2026, 11, 9, 18, 0, tzinfo=JAMAICA)    # Monday, after the close
NOV_10 = dt.datetime(2026, 11, 10, 18, 0, tzinfo=JAMAICA)
NOV_11 = dt.datetime(2026, 11, 11, 18, 0, tzinfo=JAMAICA)
NOV_12 = dt.datetime(2026, 11, 12, 18, 0, tzinfo=JAMAICA)
NOV_13 = dt.datetime(2026, 11, 13, 18, 0, tzinfo=JAMAICA)
NOV_16 = dt.datetime(2026, 11, 16, 18, 0, tzinfo=JAMAICA)
DEC_24 = dt.datetime(2026, 12, 24, 18, 0, tzinfo=JAMAICA)


def run(state, now, overrides=None, **kwargs):
    fetcher = FakeFetcher(pages(overrides))
    report = refresh.run_refresh(state, fetcher, now, SETTINGS, **kwargs)
    return report, fetcher


def test_first_run_fetches_everything():
    state = store.State()
    report, fetcher = run(state, NOV_9)
    assert fetcher.paths == [
        "/trading/trade-quotes/?market=50&date=2026-11-09",
        "/listings/listed-companies/?market=31",
        "/listings/listed-companies/?market=22",
        "/listings/listed-companies/?market=51",
        "/listings/listed-companies/?market=49",
        "/trading/corporate-actions/?instrumentCode=all-stocks&fromDate=2026-01-01&thruDate=2027-11-09",
    ]
    assert report.exit_code == 0 and report.errors == {} and report.requests == 6
    assert report.listings_reason == "no stored listings"
    assert report.datasets == {"listings": "updated", "quotes": "updated", "indices": "updated",
                               "corporate_actions": "updated"}
    assert state.companies["9001"].quote.close == 12.5
    assert len(state.indices) == 2
    assert {a.instrument_code for a in state.actions} == {"9001", "9002"}
    assert state.status["quotes"].as_of == dt.date(2026, 11, 9)


def test_before_the_close_requests_the_previous_trading_day():
    state = store.State()
    _, fetcher = run(state, dt.datetime(2026, 11, 9, 9, 0, tzinfo=JAMAICA))  # Monday morning
    assert fetcher.paths[0] == "/trading/trade-quotes/?market=50&date=2026-11-06"


def test_same_close_again_makes_no_requests():
    state = store.State()
    run(state, NOV_9)
    report, fetcher = run(state, NOV_9 + dt.timedelta(hours=3))
    assert fetcher.paths == [] and not report.attempted
    assert report.text().endswith("Nothing is due: the stored data is up to date.")


def test_next_day_needs_only_two_requests():
    state = store.State()
    run(state, NOV_9)
    report, fetcher = run(state, NOV_10)
    assert fetcher.paths == [
        "/trading/trade-quotes/?market=50&date=2026-11-10",
        "/trading/corporate-actions/?instrumentCode=all-stocks&fromDate=2026-10-10&thruDate=2027-11-10",
    ]
    assert report.requests == 2 and report.listings_reason is None
    assert report.datasets["listings"] == "skipped"


def test_listings_refresh_when_due_by_age():
    state = store.State()
    run(state, NOV_9)
    report, fetcher = run(state, NOV_16)
    assert sum(p.startswith("/listings/") for p in fetcher.paths) == 4
    assert report.listings_reason.startswith("last refresh")


def test_unknown_instrument_in_quotes_triggers_listings_refresh_once():
    state = store.State()
    run(state, NOV_9)
    gamma = fixture_html("trade-quotes.html").replace("instrument=9002", "instrument=9003")
    report, fetcher = run(state, NOV_10, {"/trading/trade-quotes/": gamma})
    assert sum(p.startswith("/listings/") for p in fetcher.paths) == 4
    assert "unknown instrument" in report.listings_reason
    assert any("9003" in w for w in report.warnings)
    assert state.unmatched == {"9003"}
    report, fetcher = run(state, NOV_11, {"/trading/trade-quotes/": gamma})
    assert report.requests == 2 and report.listings_reason is None


def test_force_listings():
    state = store.State()
    run(state, NOV_9)
    report, fetcher = run(state, NOV_10, force_listings=True)
    assert sum(p.startswith("/listings/") for p in fetcher.paths) == 4
    assert report.listings_reason == "requested"


def test_failed_dataset_keeps_the_rest_and_waits_before_retrying():
    state = store.State()
    report, _ = run(state, NOV_9, {"/trading/corporate-actions/": FetchError("Gave up after 3 attempts")})
    assert report.exit_code == 1
    assert report.errors["corporate_actions"] == "FetchError: Gave up after 3 attempts"
    assert report.datasets["corporate_actions"] == "stale"
    assert state.status["corporate_actions"].stale is True
    assert state.status["quotes"].stale is False
    assert state.last_failure_at == NOV_9
    plan = refresh.due(state, NOV_9 + dt.timedelta(minutes=30), SETTINGS)
    assert plan.corporate_actions and not plan.quotes
    assert not plan.automatic_allowed(NOV_9 + dt.timedelta(minutes=30))
    report, fetcher = run(state, NOV_9 + dt.timedelta(minutes=60))
    assert [p.split("?")[0] for p in fetcher.paths] == ["/trading/corporate-actions/"]
    assert report.exit_code == 0 and state.last_failure_at is None


def test_failed_market_is_retried_alone():
    state = store.State()
    report, _ = run(state, NOV_9, {"/listings/listed-companies/?market=51": FetchError("boom")})
    assert report.errors["listings"] == "Bond Market: FetchError: boom"
    assert state.markets["Bond Market"].stale is True
    report, fetcher = run(state, NOV_10)
    assert [p for p in fetcher.paths if p.startswith("/listings/")] == ["/listings/listed-companies/?market=51"]
    assert report.listings_reason == "retrying failed market(s): Bond Market"
    assert report.exit_code == 0 and state.status["listings"].stale is False


def test_quotes_layout_change_is_an_error():
    state = store.State()
    run(state, NOV_9)
    renamed = fixture_html("trade-quotes.html").replace("Closing <br />Price <br />($)", "Close ($)").replace(
        "Last <br />Traded <br />Price <br />($)", "Last ($)")
    report, _ = run(state, NOV_10, {"/trading/trade-quotes/": renamed})
    assert report.exit_code == 1
    assert report.errors["quotes"].startswith("ParseError: trade-quotes: no quotes table")
    assert state.status["quotes"].stale is True


def test_holiday_counts_as_a_successful_fetch():
    state = store.State()
    run(state, NOV_9)
    report, _ = run(state, NOV_10, {"/trading/trade-quotes/": fixture_html("trade-quotes-holiday.html")})
    assert report.exit_code == 0
    assert state.status["quotes"].as_of == dt.date(2026, 11, 9)  # previous quotes kept
    assert state.status["quotes"].fetched_at == NOV_10
    assert state.companies["9001"].quote.date == dt.date(2026, 11, 9)
    assert not refresh.due(state, NOV_10 + dt.timedelta(hours=1), SETTINGS).anything


def test_three_trading_days_without_data_mark_quotes_stale_but_keep_trying():
    state = store.State()
    run(state, NOV_9)
    no_data = {"/trading/trade-quotes/": fixture_html("trade-quotes-holiday.html")}
    run(state, NOV_10, no_data)
    run(state, NOV_11, no_data)
    assert state.status["quotes"].no_data_days == 2 and state.status["quotes"].stale is False
    report, _ = run(state, NOV_12, no_data)
    message = "No trade data for 3 trading days in a row; the site may have changed"
    assert report.exit_code == 0 and message in report.warnings
    assert state.status["quotes"].stale is True and state.status["indices"].last_error == message
    assert state.last_failure_at is None and state.blocked_close is None  # not a failure, not a block
    plan = refresh.due(state, NOV_13, SETTINGS)
    assert plan.quotes and plan.automatic_allowed(NOV_13)
    run(state, NOV_13)
    assert state.status["quotes"].stale is False and state.status["quotes"].no_data_days == 0


def test_missing_optional_column_is_reported():
    no_volume = fixture_html("trade-quotes.html").replace("<th>Closing<br />Ask ($)</th><th>Volume</th>",
                                                         "<th>Closing<br />Ask ($)</th><th>Shares</th>")
    report, _ = run(store.State(), NOV_9, {"/trading/trade-quotes/": no_volume})
    assert report.exit_code == 0
    assert "trade-quotes: column(s) not found, values will be null: volume" in report.warnings
    assert "Warnings:" in report.text()


def test_corporate_actions_catch_up_after_an_outage():
    state = store.State()
    run(state, NOV_9)
    _, fetcher = run(state, DEC_24)  # 45 days later, longer than the 30-day window
    assert fetcher.paths[-1] == (
        "/trading/corporate-actions/?instrumentCode=all-stocks&fromDate=2026-10-10&thruDate=2027-12-24"
    )


def test_block_stops_all_requests_and_waits_for_the_next_close():
    state = store.State()
    report, fetcher = run(state, NOV_9, {"/trading/trade-quotes/": BlockedError("HTTP 403 for /x")})
    assert fetcher.request_count == 1
    assert report.blocked and report.exit_code == 1
    assert set(report.errors) == {"quotes", "indices", "listings", "corporate_actions"}
    assert all(s.stale for s in state.status.values())
    assert state.blocked_close == refresh.latest_close(NOV_9)
    assert refresh.BLOCKED_MESSAGE in report.text()
    assert not JSE_URL.search(report.text())
    plan = refresh.due(state, NOV_9 + dt.timedelta(hours=5), SETTINGS)
    assert not plan.automatic_allowed(NOV_9 + dt.timedelta(hours=5))
    report, _ = run(state, NOV_10)  # next close: tried again, and it works
    assert report.exit_code == 0 and state.blocked_close is None


def test_report_text():
    report, _ = run(store.State(), NOV_9, {"/trading/corporate-actions/": FetchError("boom")})
    text = report.text()
    assert text.startswith("JSE refresh for trading day 2026-11-09")
    assert "Requests to the JSE site: 6" in text
    assert "Datasets: corporate_actions stale, indices updated, listings updated, quotes updated" in text
    assert "Instruments: added 2, updated 0, delisted 0 (2 stored, 2 listed)" in text
    assert "Corporate actions added: 0 (0 stored)" in text
    assert "Errors:\n  - corporate_actions: FetchError: boom" in text


def test_unexpected_parser_exception_is_recorded_as_a_failure_and_waits():
    state = store.State()
    report, fetcher = run(state, NOV_9, {"/trading/trade-quotes/": "<![foo[ x ]]>"})
    assert sum(p.startswith("/trading/trade-quotes/") for p in fetcher.paths) == 1
    assert report.exit_code == 1 and "AssertionError" in report.errors["quotes"]
    assert state.status["quotes"].stale and "AssertionError" in state.status["quotes"].last_error
    assert state.last_failure_at == NOV_9
    soon = NOV_9 + dt.timedelta(minutes=SETTINGS.refresh.retry_after_failure_minutes - 1)
    assert not refresh.due(state, soon, SETTINGS).automatic_allowed(soon)
    later = NOV_9 + dt.timedelta(minutes=SETTINGS.refresh.retry_after_failure_minutes)
    assert refresh.due(state, later, SETTINGS).automatic_allowed(later)
