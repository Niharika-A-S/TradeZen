"""
Standalone test, no database, no frontend:   python -m app.live.check [seconds]
Connects to Upstox with your token and prints the prices it receives. If this works, the
platform will work. If not, the printed reason tells you what to fix.
"""
import asyncio
import logging
import sys

from .feed import LiveFeedService


async def main(seconds: int) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    svc = LiveFeedService(store=None)
    await svc.start()
    for _ in range(seconds):
        await asyncio.sleep(1)
        s = svc.status()
        line = " | ".join(f"{k} {v['ltp']} ({v['source']})" for k, v in s["symbols"].items()) or "waiting..."
        print(f"[{s['state']:<10}] market={s['market_status']:<12} ticks={s['ticks_total']:<5} {line}")
        if s["last_error"]:
            print("   last_error:", s["last_error"])
    await svc.stop()


if __name__ == "__main__":
    asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 20))
