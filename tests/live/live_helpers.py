from datetime import datetime

from app.live import parsing as P  # noqa: E402

pb = P.pb


def ms(h: int, m: int, s: int = 0, day: int = 13) -> int:
    """Epoch ms for a Friday 2026-11-13 IST time (market hours)."""
    return int(datetime(2026, 11, day, h, m, s, tzinfo=P.IST).timestamp() * 1000)


def make_frame(ticks: dict, type_="live_feed", full=True, status=None) -> bytes:
    """ticks: {instrument_key: (ltp, ltt_ms, ltq, cp, vtt)} -> serialized FeedResponse (what Upstox sends)."""
    fr = pb.FeedResponse()
    fr.type = getattr(pb.Type, type_)
    fr.currentTs = 1
    for key, (ltp, ltt, ltq, cp, vtt) in ticks.items():
        f = fr.feeds[key]
        l = f.fullFeed.marketFF.ltpc if full else f.ltpc
        l.ltp, l.ltt, l.ltq, l.cp = ltp, ltt, ltq, cp
        if full:
            f.fullFeed.marketFF.vtt = vtt
    if status:
        for seg, st in status.items():
            fr.marketInfo.segmentStatus[seg] = getattr(pb.MarketStatus, st)
    return fr.SerializeToString()
