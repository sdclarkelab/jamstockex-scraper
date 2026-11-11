import datetime as dt

import pytest

from jamstockex import refresh, store
from jamstockex.config import JAMAICA, default_config
from jamstockex.models import Company

SETTINGS = default_config()


def jm(year, month, day, hour=0, minute=0):
    return dt.datetime(year, month, day, hour, minute, tzinfo=JAMAICA)


@pytest.mark.parametrize("now, expected", [
    (jm(2026, 11, 10, 17, 29), jm(2026, 11, 9, 17, 30)),   # Tuesday before the close -> Monday
    (jm(2026, 11, 10, 17, 30), jm(2026, 11, 10, 17, 30)),  # Tuesday at the close
    (jm(2026, 11, 10, 23, 0), jm(2026, 11, 10, 17, 30)),   # Tuesday evening
    (jm(2026, 11, 13, 22, 0), jm(2026, 11, 13, 17, 30)),   # Friday night
    (jm(2026, 11, 14, 12, 0), jm(2026, 11, 13, 17, 30)),   # Saturday -> Friday
    (jm(2026, 11, 15, 20, 0), jm(2026, 11, 13, 17, 30)),   # Sunday -> Friday
    (jm(2026, 11, 16, 8, 0), jm(2026, 11, 13, 17, 30)),    # Monday morning -> Friday
])
def test_latest_close(now, expected):
    assert refresh.latest_close(now) == expected


def test_latest_close_accepts_utc_and_a_custom_close_time():
    now = dt.datetime(2026, 11, 10, 21, 0, tzinfo=dt.timezone.utc)  # 16:00 in Jamaica
    assert refresh.latest_close(now, dt.time(15, 0)) == jm(2026, 11, 10, 15, 0)
    assert refresh.latest_close(now) == jm(2026, 11, 9, 17, 30)


def test_next_close_after_skips_the_weekend():
    assert refresh.next_close_after(jm(2026, 11, 13, 17, 30)) == jm(2026, 11, 16, 17, 30)
    assert refresh.next_close_after(jm(2026, 11, 10, 17, 30)) == jm(2026, 11, 11, 17, 30)


def listed_state():
    state = store.State()
    for code, label in SETTINGS.markets.items():
        state.companies[f"{code}00"] = Company(instrument_code=f"{code}00", symbol=f"C{code}",
                                                  name="X", market=label)
        state.markets[label] = store.DatasetStatus(as_of=dt.date(2026, 11, 9), fetched_at=jm(2026, 11, 9, 18))
    return state


def fetched(state, moment, *names):
    for name in names:
        state.status[name] = store.DatasetStatus(as_of=moment.date(), fetched_at=moment)


def test_first_run_everything_is_due():
    plan = refresh.due(store.State(), jm(2026, 11, 10, 18), SETTINGS)
    assert plan.quotes and plan.corporate_actions
    assert plan.listings == (31, 22, 51, 49) and plan.listings_reason == "no stored listings"
    assert plan.trade_date == dt.date(2026, 11, 10)
    assert plan.not_before is None and plan.automatic_allowed(jm(2026, 11, 10, 18))


def test_at_most_one_successful_refresh_per_close():
    state = listed_state()
    fetched(state, jm(2026, 11, 10, 18), "quotes", "corporate_actions")
    for later in (jm(2026, 11, 10, 23), jm(2026, 11, 11, 9), jm(2026, 11, 11, 17, 29)):
        plan = refresh.due(state, later, SETTINGS)
        assert not plan.anything
        assert not plan.automatic_allowed(later)
    assert refresh.due(state, jm(2026, 11, 11, 17, 30), SETTINGS).quotes


def test_a_holiday_fetch_counts_as_the_fetch_for_that_close():
    state = listed_state()
    state.status["quotes"] = store.DatasetStatus(as_of=dt.date(2026, 10, 16), fetched_at=jm(2026, 10, 19, 18))
    state.status["corporate_actions"] = store.DatasetStatus(as_of=dt.date(2026, 10, 19), fetched_at=jm(2026, 10, 19, 18))
    assert not refresh.due(state, jm(2026, 10, 19, 20), SETTINGS).anything


def test_corporate_actions_are_due_on_their_own():
    state = listed_state()
    fetched(state, jm(2026, 11, 10, 18), "quotes")
    plan = refresh.due(state, jm(2026, 11, 10, 20), SETTINGS)
    assert not plan.quotes and plan.corporate_actions


def test_retry_waits_after_a_failure():
    state = listed_state()
    state.last_failure_at = jm(2026, 11, 10, 18)
    plan = refresh.due(state, jm(2026, 11, 10, 18, 30), SETTINGS)
    assert plan.quotes and plan.not_before == jm(2026, 11, 10, 19)
    assert not plan.automatic_allowed(jm(2026, 11, 10, 18, 30))
    assert refresh.due(state, jm(2026, 11, 10, 19), SETTINGS).automatic_allowed(jm(2026, 11, 10, 19))


def test_no_automatic_attempt_after_a_block_until_the_next_close():
    state = listed_state()
    state.blocked_close = jm(2026, 11, 13, 17, 30)  # blocked on Friday evening
    for moment in (jm(2026, 11, 13, 22), jm(2026, 11, 14, 12), jm(2026, 11, 16, 17, 29)):
        plan = refresh.due(state, moment, SETTINGS)
        assert plan.quotes and plan.not_before == jm(2026, 11, 16, 17, 30)
        assert not plan.automatic_allowed(moment)
    assert refresh.due(state, jm(2026, 11, 16, 17, 30), SETTINGS).automatic_allowed(jm(2026, 11, 16, 17, 30))


def test_listings_due_by_age_and_for_a_failed_market_alone():
    state = listed_state()
    fetched(state, jm(2026, 11, 10, 18), "quotes", "corporate_actions")
    state.markets["Bond Market"].stale = True
    plan = refresh.due(state, jm(2026, 11, 10, 20), SETTINGS)
    assert plan.listings == (51,) and plan.listings_reason == "retrying failed market(s): Bond Market"
    state.markets["Bond Market"].stale = False
    plan = refresh.due(state, jm(2026, 11, 16, 20), SETTINGS)  # 7 days after 2026-11-09
    assert plan.listings == (31, 22, 51, 49) and plan.listings_reason == "last refresh 2026-11-09"


def test_listings_due_for_unknown_quote_codes_but_not_unmatched_ones():
    state = listed_state()
    today = dt.date(2026, 11, 10)
    codes, reason = refresh.listings_due(state, {"9006": None}, SETTINGS.markets, today, 7, False)
    assert codes == [31, 22, 51, 49] and reason == "1 unknown instrument(s) in quotes"
    state.unmatched = {"9006"}
    assert refresh.listings_due(state, {"9006": None}, SETTINGS.markets, today, 7, False) == ([], None)
    assert refresh.listings_due(state, None, SETTINGS.markets, today, 7, True) == ([31, 22, 51, 49], "requested")


def test_corporate_actions_window_backfills_then_catches_up():
    today = dt.date(2026, 12, 24)
    first = refresh.actions_window(store.DatasetStatus(), today, SETTINGS)
    assert first == (dt.date(2026, 1, 1), dt.date(2027, 12, 24))
    after_outage = refresh.actions_window(store.DatasetStatus(as_of=dt.date(2026, 11, 9)), today, SETTINGS)
    assert after_outage == (dt.date(2026, 10, 10), dt.date(2027, 12, 24))
    early = refresh.actions_window(store.DatasetStatus(as_of=dt.date(2026, 1, 15)), today, SETTINGS)
    assert early[0] == dt.date(2026, 1, 1)  # never before backfill_from
