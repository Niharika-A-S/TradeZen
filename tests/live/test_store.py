from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine, text

from app.live import parsing as P
from app.live.store import BarStore


@pytest.fixture
def store():
    eng = create_engine("sqlite://")
    with eng.begin() as c:
        c.execute(text('CREATE TABLE price_bars (instrument TEXT, ts TIMESTAMP, open REAL, high REAL, low REAL, close REAL, volume BIGINT)'))
    return BarStore(eng, ts_mode="ist_naive")


def candle(minute, o=100, h=105, l=99, c=102, v=50, sym="INFY"):
    return P.Candle(sym, minute, o, h, l, c, v)


def test_upsert_merges_instead_of_overwriting(store):
    m = datetime(2026, 11, 13, 10, 0, tzinfo=P.IST)
    store.upsert_many([candle(m)])
    store.upsert_many([candle(m, o=999, h=110, l=95, c=104, v=40)])     # partial bar after a restart
    bars = store.recent_bars("INFY", m - timedelta(hours=1))
    assert len(bars) == 1
    b = bars[0]
    assert (b["open"], b["high"], b["low"], b["close"], b["volume"]) == (100, 110, 95, 104, 50)
    assert b["time"] == m


def test_insert_missing_never_touches_existing(store):
    m = datetime(2026, 11, 13, 10, 0, tzinfo=P.IST)
    store.upsert_many([candle(m)])
    added = store.insert_missing([candle(m, c=1), candle(m + timedelta(minutes=1), c=103)])
    assert added == 1
    assert [b["close"] for b in store.recent_bars("INFY", m - timedelta(hours=1))] == [102, 103]


def test_old_replay_data_is_never_returned_as_live(store):
    old = datetime(2022, 3, 10, 10, 0, tzinfo=P.IST)
    store.upsert_many([candle(old)])
    assert store.latest_bar("INFY") is None
    fresh = P.floor_minute(P.now_ist()) - timedelta(minutes=5)
    store.upsert_many([candle(fresh, c=111)])
    assert store.latest_bar("INFY")["close"] == 111


def test_bad_config_is_rejected():
    with pytest.raises(ValueError):
        BarStore(create_engine("sqlite://"), table="price_bars; DROP TABLE x")
    with pytest.raises(ValueError):
        BarStore(create_engine("sqlite://"), ts_mode="local")
