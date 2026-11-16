from app.live import parsing as P
from app.live.instruments import KEY_TO_SYMBOL, resolve_symbol
from live_helpers import make_frame, ms

INFY = "NSE_EQ|INE009A01021"
TCS = "NSE_EQ|INE467B01029"


def test_symbol_resolution_and_aliases():
    assert resolve_symbol("infy") == "INFY"
    assert resolve_symbol("HDFC") == "HDFCBANK"
    assert resolve_symbol("sbi") == "SBIN"
    assert resolve_symbol("NSE:RELIANCE") == "RELIANCE"
    assert resolve_symbol("RELIANCE.NS") == "RELIANCE"
    assert resolve_symbol(INFY) == "INFY"
    assert resolve_symbol("WIPRO") is None and resolve_symbol("") is None and resolve_symbol(None) is None


def test_decode_full_and_ltpc_modes():
    full = P.extract_ticks(P.parse_frame(make_frame({INFY: (1500.5, ms(10, 0), 10, 1490.0, 5000)})), KEY_TO_SYMBOL)
    assert full[0].symbol == "INFY" and full[0].ltp == 1500.5 and full[0].prev_close == 1490.0 and full[0].vtt == 5000
    lt = P.extract_ticks(P.parse_frame(make_frame({TCS: (3900.0, ms(10, 0), 5, 3890.0, 0)}, full=False)), KEY_TO_SYMBOL)
    assert lt[0].symbol == "TCS" and lt[0].vtt is None


def test_bad_or_unknown_ticks_are_skipped():
    frame = make_frame({INFY: (0.0, ms(10, 0), 1, 0.0, 0), "NSE_EQ|INE000000000": (10.0, ms(10, 0), 1, 9.0, 1), TCS: (3900.0, ms(10, 0), 1, 0.0, 1)})
    ticks = P.extract_ticks(P.parse_frame(frame), KEY_TO_SYMBOL)
    assert [t.symbol for t in ticks] == ["TCS"] and ticks[0].prev_close is None


def test_market_info_and_garbage():
    resp = P.parse_frame(make_frame({}, type_="market_info", status={"NSE_EQ": "NORMAL_OPEN", "NSE_FO": "NORMAL_CLOSE"}))
    assert P.extract_market_status(resp) == {"NSE_EQ": "NORMAL_OPEN", "NSE_FO": "NORMAL_CLOSE"}
    import pytest
    with pytest.raises(P.DecodeError):
        P.parse_frame(b"\xff\xff\xff not protobuf")
