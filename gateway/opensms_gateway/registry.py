import asyncio
from typing import Optional

from fastapi import WebSocket


class ConnectionRegistry:
    def __init__(self):
        self._connections: dict[str, WebSocket] = {}
        self._lock = asyncio.Lock()

    async def register(self, device_id: str, websocket: WebSocket) -> None:
        old: Optional[WebSocket] = None
        async with self._lock:
            old = self._connections.get(device_id)
            self._connections[device_id] = websocket
        if old is not None and old is not websocket:
            try:
                await old.close(code=1012)
            except Exception:
                pass

    async def unregister(self, device_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            if self._connections.get(device_id) is websocket:
                self._connections.pop(device_id, None)

    async def is_online(self, device_id: str) -> bool:
        async with self._lock:
            return device_id in self._connections

    async def disconnect(self, device_id: str, code: int = 4003) -> bool:
        async with self._lock:
            websocket = self._connections.pop(device_id, None)
        if websocket is None:
            return False
        try:
            await websocket.close(code=code)
        except Exception:
            pass
        return True

    async def enqueue(self, device_id: str, job: dict) -> bool:
        async with self._lock:
            websocket = self._connections.get(device_id)
        if websocket is None:
            return False
        try:
            await websocket.send_json(job)
            return True
        except Exception:
            await self.unregister(device_id, websocket)
            return False
