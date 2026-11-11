import datetime as dt

import pytest

from jamstockex.config import JAMAICA, USER_AGENT, ConfigError, default_config, load_config


def write(tmp_path, text):
    (tmp_path / "config.toml").write_text(text, encoding="utf-8")
    return tmp_path


def test_defaults_need_no_config_file(tmp_path):
    config = load_config(tmp_path)
    assert config.source.base_url == "https://www.jamstockex.com"
    assert config.source.user_agent == "jamstockex/2.0 (+https://github.com/sdclarkelab/jamstockex-scraper)"
    assert config.source.user_agent == USER_AGENT
    assert config.source.timeout_s == 20.0
    assert config.source.retries == 3
    assert config.source.delay_s == (2.0, 5.0)
    assert config.markets == {31: "Main Market", 22: "Junior Market", 51: "Bond Market", 49: "USD Market"}
    assert config.combined_market == 50
    assert config.refresh.close_time == dt.time(17, 30)
    assert config.refresh.check_every_minutes == 15
    assert config.refresh.retry_after_failure_minutes == 60
    assert config.refresh.listings_every_days == 7
    assert config.refresh.corporate_actions_window == 30
    assert config.refresh.corporate_actions_forward == 365
    assert config.refresh.backfill_from == dt.date(2026, 1, 1)
    assert config.refresh.max_listing_drop_pct == 20
    assert config.port == 8765
    assert config == default_config()


def test_config_file_overrides_a_subset(tmp_path):
    config = load_config(write(tmp_path, """
[source]
retries = 5
base_url = "https://www.example.test/"

[refresh]
close_time = "16:45"
backfill_from = 2026-03-01

[server]
port = 9000
"""))
    assert config.source.retries == 5
    assert config.source.base_url == "https://www.example.test"
    assert config.source.timeout_s == 20.0  # untouched default
    assert config.refresh.close_time == dt.time(16, 45)
    assert config.refresh.backfill_from == dt.date(2026, 3, 1)
    assert config.refresh.listings_every_days == 7
    assert config.port == 9000


def test_markets_table_replaces_the_defaults(tmp_path):
    config = load_config(write(tmp_path, '[markets]\n31 = "Main Market"\n'))
    assert config.markets == {31: "Main Market"}


def test_backfill_from_accepts_a_string(tmp_path):
    config = load_config(write(tmp_path, '[refresh]\nbackfill_from = "2026-02-01"\n'))
    assert config.refresh.backfill_from == dt.date(2026, 2, 1)


@pytest.mark.parametrize("text, key", [
    ("[source]\nretries = 0", "source.retries"),
    ('[source]\nretries = "3"', "source.retries"),
    ("[source]\ndelay_s = [5, 2]", "source.delay_s"),
    ("[source]\ndelay_s = [1]", "source.delay_s"),
    ("[source]\ntimeout_s = 0", "source.timeout_s"),
    ('[source]\nbase_url = "http://www.example.test"', "source.base_url"),
    ('[source]\nuser_agent = " "', "source.user_agent"),
    ("[refresh]\nmax_listing_drop_pct = 120", "refresh.max_listing_drop_pct"),
    ("[refresh]\nlistings_every_days = 0", "refresh.listings_every_days"),
    ("[refresh]\ncheck_every_minutes = true", "refresh.check_every_minutes"),
    ('[refresh]\nclose_time = "25:00"', "refresh.close_time"),
    ('[refresh]\nbackfill_from = "soon"', "refresh.backfill_from"),
    ("[server]\nport = 70000", "server.port"),
    ('[markets]\nmain = "Main Market"', "markets.main"),
    ("[markets]", "markets"),
    ('[markets]\n31 = "Main Market"\n22 = "Main Market"', "markets"),
    ("[bogus]\nx = 1", "unknown section [bogus]"),
    ("[source]\ncolour = 1", "unknown key source.colour"),
])
def test_invalid_values_name_the_file_and_key(tmp_path, text, key):
    with pytest.raises(ConfigError) as caught:
        load_config(write(tmp_path, text))
    assert key in str(caught.value)
    assert str(tmp_path / "config.toml") in str(caught.value)


def test_bad_toml_names_the_file(tmp_path):
    with pytest.raises(ConfigError, match="invalid TOML"):
        load_config(write(tmp_path, "[source\n"))


def test_jamaica_is_utc_minus_five_all_year():
    for month in (1, 7):
        moment = dt.datetime(2026, month, 1, 12, tzinfo=JAMAICA)
        assert moment.utcoffset() == dt.timedelta(hours=-5)
