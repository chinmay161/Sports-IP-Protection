import asyncio, json, websockets
async def main():
    async with websockets.connect('ws://127.0.0.1:8001/ws/events') as ws:
        print('connected')
        while True:
            msg = await ws.recv()
            parsed = json.loads(msg)
            print(f"[{parsed.get('type')}]", parsed.get('alert', {}).get('status') or parsed.get('asset', {}).get('status') or '')
asyncio.run(main())
