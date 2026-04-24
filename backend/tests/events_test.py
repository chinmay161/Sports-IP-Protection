import asyncio
import json
import websockets  # already installed

async def main():
    uri = "ws://127.0.0.1:8001/ws/events"
    async with websockets.connect(uri) as ws:
        print(f"connected to {uri}")
        while True:
            msg = await ws.recv()
            parsed = json.loads(msg)
            print(f"[{parsed.get('type')}]", json.dumps(parsed, indent=2))

asyncio.run(main())