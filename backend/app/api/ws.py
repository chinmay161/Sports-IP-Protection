# app/api/ws.py
"""WebSocket endpoint for the real-time alert feed."""
from __future__ import annotations

import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.services.broadcaster import manager

logger = logging.getLogger(__name__)
router = APIRouter()


@router.websocket("/ws/events")
async def event_stream(websocket: WebSocket) -> None:
    """Subscribe a client to the live alert stream.

    The client does not need to send anything. The server pushes JSON payloads
    whenever the alert subscriber broadcasts. On disconnect we clean up.

    Auth note: intentionally unauthenticated for dev. In prod, require a JWT
    via a `?token=` query param and call `verify_token` before `manager.connect`.
    """
    await manager.connect(websocket)
    try:
        # Keep-alive loop. We block on recv() so we notice disconnects immediately.
        while True:
            # Client may send pings or any text; we ignore the content.
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("ws_unexpected_error")
    finally:
        await manager.disconnect(websocket)