"""Interactive WebSocket client to test real-time alert streaming from TradeZen."""
import asyncio
import json
import websockets
import sys

USER_ID = int(sys.argv[1]) if len(sys.argv) > 1 else 1
WS_URI = f"ws://127.0.0.1:8000/ws/alerts/{USER_ID}"


async def listen_alerts():
    print(f"Connecting to TradeZen Alert Stream at {WS_URI}...")
    try:
        async with websockets.connect(WS_URI) as ws:
            print("Connected! Waiting for real-time behavioral alerts (Press Ctrl+C to exit)...")
            async for message in ws:
                data = json.loads(message)
                print("\n" + "!" * 70)
                print(f"ALERT RECEIVED: [{data.get('severity')}] {data.get('alert_type')}")
                print(f"Message: {data.get('message')}")
                print(f"Context: {json.dumps(data.get('context_json'), indent=2)}")
                print("!" * 70 + "\n")
    except Exception as e:
        print(f"Connection closed: {e}")


if __name__ == "__main__":
    try:
        asyncio.run(listen_alerts())
    except KeyboardInterrupt:
        print("\nExited alert listener.")
