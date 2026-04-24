# app/services/broadcaster.py
"""In-process WebSocket broadcaster.

Converts one Redis pub/sub message into N WebSocket pushes (one per connected
dashboard tab). Single-worker-safe; for multi-worker deployment, swap this for
a Redis-backed broadcaster.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections.add(websocket)
        logger.info("ws_connected total=%d", len(self._connections))

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._connections.discard(websocket)
        logger.info("ws_disconnected total=%d", len(self._connections))

    async def broadcast(self, payload: dict[str, Any]) -> int:
        """Send payload as JSON to every live connection. Returns count reached.

        Dead connections are silently dropped so one bad client can't stall others.
        """
        async with self._lock:
            targets = list(self._connections)

        if not targets:
            return 0

        dead: list[WebSocket] = []
        reached = 0
        for ws in targets:
            try:
                await ws.send_json(payload)
                reached += 1
            except Exception as exc:
                logger.warning("ws_send_failed error=%s", exc)
                dead.append(ws)

        if dead:
            async with self._lock:
                for ws in dead:
                    self._connections.discard(ws)

        return reached

    def connection_count(self) -> int:
        return len(self._connections)


# Process-wide singleton. Imported by both the subscriber task and the ws endpoint.
manager = ConnectionManager()