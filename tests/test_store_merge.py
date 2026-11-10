import datetime as dt
from decimal import Decimal

from dataclasses import replace

from jamstockex import store
from jamstockex.config import default_config
from jamstockex.models import Company, CorporateAction, Index, Quote
from jamstockex.store import ScrapeResult, State

TODAY = dt.date(2026, 11, 9)
NOW = dt.datetime(2026, 11, 9, 22, 30, tzinfo=dt.timezone.utc)
EARLIER = dt.date(2026, 11, 2)


SYMBOLS = {"9001": "ACME", "9002": "BETA", "9003": "GAMMA"}  # instrument_code -> symbol, for the defaults


def company(code, symbol=None, currency="JMD", market="Main Market", **kw):
    return Company(instrument_code=code, symbol=symbol or SYMBOLS.get(code, f"S{code}"), name=f"{code} Limited",
                   market=market, currency=currency, **kw)


def quote(close, day=TODAY):
    return Quote(date=day, close=Decimal(close), change=Decimal("0"), change_pct=Decimal("0"), volume=100)


def action(symbol, amount="0.75", currency="JMD", type_="dividend", code=None, record=dt.date(2026, 11, 20)):
    return CorporateAction(symbol=symbol, type=type_, amount=Decimal(amount) if amount else None,
                           currency=currency, record_date=record, ex_date=None, payment_date=None,
                           instrument_code=code)


def settings(drop=20):
    defaults = default_config()
    return replace(defaults, refresh=replace(defaults.refresh, max_listing_drop_pct=drop))


def merge(state, result, drop=20):
    return store.merge(state, result, today=TODAY, now=NOW, settings=settings(drop))


def refresh(pages, errors=None, full=True, **kw):
    """A ScrapeResult for a listings refresh. pages: market label -> companies."""
    return ScrapeResult(trade_date=TODAY, listings=pages, listing_errors=errors or {}, listings_full=full, **kw)


def listed_state(*companies):
    state = State()
    for c in companies:
        c.listed_since = EARLIER
        state.companies[c.instrument_code] = c
        state.markets[c.market] = store.DatasetStatus(as_of=EARLIER)
    state.status["listings"] = store.DatasetStatus(as_of=EARLIER)
    return state


def main_market(*codes):
    return [company(code) for code in codes]


# --- listings -------------------------------------------------------------

def test_new_listings_get_listed_since_today_and_status_updates():
    state = State()
    merge(state, refresh({"Main Market": main_market("9001")}))
    assert state.companies["9001"].listed_since == TODAY
    fresh = store.DatasetStatus(as_of=TODAY, fetched_at=NOW, stale=False, last_error=None)
    assert state.status["listings"] == fresh
    assert state.markets == {"Main Market": fresh}


def test_listing_update_keeps_listed_since_and_quote():
    state = listed_state(*main_market("9001"))
    state.companies["9001"].quote = quote("10")
    renamed = company("9001", sector="Retail")
    renamed.name = "Acme Group Limited"
    merge(state, refresh({"Main Market": [renamed]}))
    acme = state.companies["9001"]
    assert acme.name == "Acme Group Limited" and acme.sector == "Retail"
    assert acme.listed_since == EARLIER
    assert acme.quote == quote("10")


def test_missing_instrument_is_delisted():
    state = listed_state(*main_market(*[f"{8000 + i}" for i in range(10)]))
    warnings = merge(state, refresh({"Main Market": main_market(*[f"{8000 + i}" for i in range(9)])}))
    gone = state.companies["8009"]
    assert gone.listed is False and gone.delisted_on == TODAY
    assert warnings == []


def test_failed_market_keeps_its_instruments_and_only_it_goes_stale():
    state = listed_state(company("9001"), company("9004", market="Junior Market"))
    merge(state, refresh({"Main Market": main_market("9001")},
                         errors={"Junior Market": "FetchError: boom"}))
    assert state.companies["9004"].listed is True
    assert state.markets["Main Market"].stale is False and state.markets["Main Market"].as_of == TODAY
    assert state.markets["Junior Market"].stale is True
    assert state.markets["Junior Market"].as_of == EARLIER  # not advanced -> retried next run
    assert state.status["listings"].stale is True
    assert state.status["listings"].last_error == "Junior Market: FetchError: boom"
    assert state.status["listings"].as_of == EARLIER  # oldest market refresh


def test_market_recovers_and_listings_stop_being_stale():
    state = listed_state(company("9001"), company("9004", market="Junior Market"))
    merge(state, refresh({"Main Market": main_market("9001")}, errors={"Junior Market": "FetchError: boom"}))
    merge(state, refresh({"Junior Market": [company("9004", market="Junior Market")]}, full=False))
    assert state.status["listings"] == store.DatasetStatus(as_of=TODAY, fetched_at=NOW, stale=False, last_error=None)


def test_delisting_held_when_a_market_drops_too_far():
    state = listed_state(*main_market(*[f"{8000 + i}" for i in range(10)]))
    warnings = merge(state, refresh({"Main Market": main_market(*[f"{8000 + i}" for i in range(7)])}))  # 7 < 8
    assert all(c.listed for c in state.companies.values())
    assert any("Delisting held for Main Market" in w for w in warnings)


def test_delisting_boundary_is_inclusive_and_exact():
    state = listed_state(*main_market(*[f"{8000 + i}" for i in range(90)]))
    merge(state, refresh({"Main Market": main_market(*[f"{8000 + i}" for i in range(63)])}), drop=30)  # exactly 70%
    assert sum(1 for c in state.companies.values() if not c.listed) == 27


def test_empty_page_for_a_small_market_does_not_delist_it():
    mains = main_market(*[f"{7000 + i}" for i in range(100)])
    usd = [company(f"{7500 + i}", currency="USD", market="USD Market") for i in range(10)]
    state = listed_state(*mains, *usd)
    warnings = merge(state, refresh({"Main Market": main_market(*[f"{7000 + i}" for i in range(100)]),
                                     "USD Market": []}))
    assert all(c.listed for c in state.companies.values())
    assert warnings == ["Delisting held for USD Market: 0 instrument(s) on the page vs 10 previously listed "
                        "(max drop 20%)"]


def test_instrument_moving_market_is_not_delisted():
    state = listed_state(company("9001", market="Junior Market"))
    merge(state, refresh({"Main Market": main_market("9001"), "Junior Market": []}))
    assert state.companies["9001"].listed is True
    assert state.companies["9001"].market == "Main Market"


def test_relisting_clears_delisted_on():
    state = listed_state(*main_market("9001"))
    state.companies["9001"].listed = False
    state.companies["9001"].delisted_on = EARLIER
    merge(state, refresh({"Main Market": main_market("9001")}))
    assert state.companies["9001"].listed is True
    assert state.companies["9001"].delisted_on is None
    assert state.companies["9001"].listed_since == EARLIER


def test_listings_not_attempted_leaves_status_alone():
    state = listed_state(*main_market("9001"))
    merge(state, ScrapeResult(trade_date=TODAY))
    assert state.status["listings"] == store.DatasetStatus(as_of=EARLIER)
    assert state.markets == {"Main Market": store.DatasetStatus(as_of=EARLIER)}


def test_full_refresh_remembers_unmatched_quote_codes_until_they_appear():
    state = listed_state(*main_market("9001"))
    merge(state, refresh({"Main Market": main_market("9001")},
                         quotes={"9001": quote("1"), "9003": quote("2")}, indices=[]))
    assert state.unmatched == {"9003"}
    merge(state, refresh({"Main Market": main_market("9001", "9003")}, full=False))
    assert state.unmatched == set()


def test_holiday_full_refresh_keeps_recorded_unmatched_codes():
    state = listed_state(*main_market("9001"))
    state.unmatched = {"9003"}
    merge(state, refresh({"Main Market": main_market("9001")}, quotes={}, indices=[]))
    assert state.unmatched == {"9003"}


def test_partial_refresh_does_not_record_unmatched_codes():
    state = listed_state(*main_market("9001"))
    merge(state, refresh({"Main Market": main_market("9001")}, full=False,
                         quotes={"9003": quote("2")}, indices=[]))
    assert state.unmatched == set()


# --- quotes and indices ---------------------------------------------------

def test_quotes_replace_present_and_keep_absent():
    state = listed_state(*main_market("9001", "9004"))
    state.companies["9004"].quote = quote("5", day=EARLIER)
    merge(state, ScrapeResult(trade_date=TODAY, quotes={"9001": quote("12")}, indices=[]))
    assert state.companies["9001"].quote == quote("12")
    assert state.companies["9004"].quote == quote("5", day=EARLIER)
    assert state.status["quotes"].as_of == TODAY and state.status["quotes"].stale is False


def test_unknown_quote_is_skipped_with_warning():
    state = listed_state(*main_market("9001"))
    warnings = merge(state, ScrapeResult(trade_date=TODAY, quotes={"9003": quote("1")}, indices=[]))
    assert "9003" not in state.companies
    assert any("9003" in w for w in warnings)


def test_holiday_keeps_quotes_indices_and_as_of():
    state = listed_state(*main_market("9001"))
    state.companies["9001"].quote = quote("10", day=EARLIER)
    old_index = Index(name="JSE Main Index", date=EARLIER, value=Decimal("1"), change=None, change_pct=None, volume=None)
    state.indices = [old_index]
    state.status["quotes"] = store.DatasetStatus(as_of=EARLIER)
    state.status["indices"] = store.DatasetStatus(as_of=EARLIER)
    merge(state, ScrapeResult(trade_date=TODAY, quotes={}, indices=[]))
    assert state.companies["9001"].quote.date == EARLIER
    assert state.indices == [old_index]
    assert state.status["quotes"].as_of == EARLIER and state.status["quotes"].stale is False
    assert state.status["quotes"].fetched_at == NOW


def test_indices_replaced_when_present():
    state = State()
    new_index = Index(name="JSE Main Index", date=TODAY, value=Decimal("2"), change=None, change_pct=None, volume=None)
    merge(state, ScrapeResult(trade_date=TODAY, quotes={}, indices=[new_index]))
    assert state.indices == [new_index]
    assert state.status["indices"].as_of == TODAY


def test_failure_marks_stale_then_success_clears():
    state = listed_state(*main_market("9001"))
    state.status["quotes"] = store.DatasetStatus(as_of=EARLIER, fetched_at=NOW - dt.timedelta(days=7))
    merge(state, ScrapeResult(trade_date=TODAY, errors={"quotes": "BlockedError: 403", "indices": "BlockedError: 403"}))
    assert state.status["quotes"].stale is True
    assert state.status["quotes"].last_error == "BlockedError: 403"
    assert state.status["quotes"].as_of == EARLIER
    merge(state, ScrapeResult(trade_date=TODAY, quotes={"9001": quote("1")}, indices=[]))
    assert state.status["quotes"] == store.DatasetStatus(as_of=TODAY, fetched_at=NOW, stale=False, last_error=None)


NO_DATA = "No trade data for 3 trading days in a row; the site may have changed"


def no_trading():
    return ScrapeResult(trade_date=TODAY, quotes={}, indices=[])


def test_days_without_quotes_are_counted_and_any_quote_resets_the_count():
    state = listed_state(*main_market("9001"))
    merge(state, no_trading())
    merge(state, no_trading())
    assert state.status["quotes"].no_data_days == 2
    assert state.status["quotes"].stale is False
    merge(state, ScrapeResult(trade_date=TODAY, quotes={"9001": quote("1")}, indices=[]))
    assert state.status["quotes"].no_data_days == 0


def test_a_failed_quotes_fetch_leaves_the_count_alone():
    state = listed_state(*main_market("9001"))
    state.status["quotes"].no_data_days = 2
    merge(state, ScrapeResult(trade_date=TODAY, errors={"quotes": "FetchError: x", "indices": "FetchError: x"}))
    assert state.status["quotes"].no_data_days == 2


def test_third_day_without_quotes_marks_quotes_and_indices_stale():
    state = listed_state(*main_market("9001"))
    warnings = [merge(state, no_trading()) for _ in range(3)]
    assert warnings == [[], [], [NO_DATA]]
    for name in ("quotes", "indices"):
        assert state.status[name].stale is True
        assert state.status[name].last_error == NO_DATA
    assert state.status["quotes"].fetched_at == NOW  # a successful fetch: the next close is fetched as usual
    merge(state, ScrapeResult(trade_date=TODAY, quotes={"9001": quote("1")}, indices=[]))
    assert state.status["quotes"] == store.DatasetStatus(as_of=TODAY, fetched_at=NOW)
    assert state.status["indices"].stale is False and state.status["indices"].last_error is None


# --- corporate actions ----------------------------------------------------

def test_actions_union_without_duplicates_across_decimal_scale():
    state = listed_state(*main_market("9001"))
    state.actions = [action("ACME", amount="0.75")]
    merge(state, ScrapeResult(trade_date=TODAY, actions=[action("ACME", amount="0.7500"),
                                                         action("ACME", amount="0.80")]))
    assert len(state.actions) == 2
    assert state.status["corporate_actions"].as_of == TODAY


def test_merge_stats_count_added_updated_delisted_and_new_actions():
    state = listed_state(*main_market("9011", "9012", "9013"))
    stats = store.MergeStats()
    page = [company("9011"), company("9012", sector="Retail"), company("9014")]
    store.merge(state, refresh({"Main Market": page}, actions=[action("A")]),
                today=TODAY, now=NOW, settings=settings(50), stats=stats)
    assert stats == store.MergeStats(companies_added=1, companies_updated=1, companies_delisted=1, actions_added=1)


def test_actions_are_never_deleted():
    state = listed_state(*main_market("9001"))
    state.actions = [action("ACME", record=dt.date(2026, 1, 15))]
    merge(state, ScrapeResult(trade_date=TODAY, actions=[]))
    assert len(state.actions) == 1


def test_action_mapping_rules():
    state = State()
    state.companies = {
        "9001": company("9001"),
        "9008": company("9008", symbol="DUAL", currency="JMD"),
        "9007": company("9007", symbol="DUAL", currency="USD"),
        "9015": company("9015", symbol="TWIN", currency="JMD"),
        "9016": company("9016", symbol="TWIN", currency="JMD"),
    }
    merge(state, ScrapeResult(trade_date=TODAY, actions=[
        action("ACME"),                                # unique symbol
        action("DUAL", currency="USD"),                # currency disambiguates
        action("TWIN"),                                # still ambiguous
        action("NOPE"),                                # unknown
        action("LINKED", code="9009"),           # code from page link kept
    ]))
    codes = {a.symbol: a.instrument_code for a in state.actions}
    assert codes == {"ACME": "9001", "DUAL": "9007", "TWIN": None, "NOPE": None, "LINKED": "9009"}


def test_stored_unmapped_actions_get_mapped_once_listings_arrive():
    state = State()
    state.actions = [action("ACME")]
    merge(state, refresh({"Main Market": main_market("9001")}))
    assert state.actions[0].instrument_code == "9001"
