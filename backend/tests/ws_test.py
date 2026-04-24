# ws_test.py — temporary test client. Delete after we're done.
import asyncio
import json
import websockets  # already installed via uvicorn[standard]

async def main():
    uri = "ws://127.0.0.1:8001/ws/alerts"
    async with websockets.connect(uri) as ws:
        print(f"connected to {uri}")
        while True:
            msg = await ws.recv()
            print("received:", json.dumps(json.loads(msg), indent=2))

asyncio.run(main())