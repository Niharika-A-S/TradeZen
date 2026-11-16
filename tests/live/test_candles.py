from app.live import parsing as P
from live_helpers import ms


def tick(ltp, h, m, s=0, ltq=10, vtt=None, sym="INFY"):
    return P.Tick(sym, ltp, 100.0, ms(h, m, s), ltq, vtt)


def test_minute_candle_ohlc_and_volume_from_vtt_delta():
    b = P.CandleBuilder()
    assert b.update(tick(100, 10, 0, 5, ltq=10, vtt=1000)) == []
    assert b.update(tick(103, 10, 0, 20, vtt=1040)) == []
    assert b.update(tick(99, 10, 0, 40, vtt=1100)) == []
    done = b.update(tick(101, 10, 1, 2, vtt=1150))
    assert len(done) == 1
    c = done[0]
    assert (c.open, c.high, c.low, c.close) == (100, 103, 99, 99)
    assert c.volume == 1100 - (1000 - 10)  # everything traded since just before the first tick
    nxt = b.forming("INFY")
    assert nxt.minute.minute == 1 and nxt.open == 101 and nxt.volume == 1150 - 1100


def test_late_and_out_of_order_ticks_are_ignored_not_invented():
    b = P.CandleBuilder()
    b.update(tick(100, 10, 5, 10))
    assert b.update(tick(90, 10, 4, 59)) == []           # older minute than the forming one
    assert b.forming("INFY").low == 100
    closed = b.flush(P.ms_to_ist(ms(10, 6, 10)))          # minute over + grace
    assert len(closed) == 1 and b.forming("INFY") is None
    assert b.update(tick(95, 10, 5, 58)) == []            # straggler for an already-closed minute


def test_outside_session_ticks_do_not_make_candles():
    b = P.CandleBuilder()
    assert b.update(tick(100, 9, 10)) == [] and b.forming("INFY") is None      # pre-open
    assert b.update(tick(100, 15, 35)) == [] and b.forming("INFY") is None     # closing auction


def test_flush_waits_for_grace_period():
    b = P.CandleBuilder()
    b.update(tick(100, 10, 0, 5))
    assert b.flush(P.ms_to_ist(ms(10, 1, 1))) == []
    assert len(b.flush(P.ms_to_ist(ms(10, 1, 4)))) == 1


def test_new_trading_day_resets_volume_base():
    b = P.CandleBuilder()
    b.update(tick(100, 15, 29, 0, ltq=5, vtt=900_000))
    b.update(P.Tick("INFY", 100, 100.0, ms(10, 0, 0, day=16), 7, 300))  # next Monday
    assert b.forming("INFY").volume == 7  # vtt went down -> new day -> base = vtt - ltq
