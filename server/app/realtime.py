import asyncio
from collections import defaultdict
from typing import Any

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self):
        self.connections: dict[str, set[WebSocket]] = defaultdict(set)
        self.lock = asyncio.Lock()

    async def connect(self, device_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self.lock:
            self.connections[device_id].add(websocket)

    async def disconnect(self, device_id: str, websocket: WebSocket) -> None:
        async with self.lock:
            self.connections[device_id].discard(websocket)
            if not self.connections[device_id]:
                self.connections.pop(device_id, None)

    async def broadcast(self, message: dict[str, Any], exclude_device: str | None = None) -> None:
        async with self.lock:
            targets = [
                (device_id, websocket)
                for device_id, sockets in self.connections.items()
                if device_id != exclude_device
                for websocket in sockets
            ]
        stale: list[tuple[str, WebSocket]] = []
        for device_id, websocket in targets:
            try:
                await websocket.send_json(message)
            except Exception:
                stale.append((device_id, websocket))
        for device_id, websocket in stale:
            await self.disconnect(device_id, websocket)

    async def send_to(self, device_id: str, message: dict[str, Any]) -> None:
        async with self.lock:
            targets = list(self.connections.get(device_id, set()))
        for websocket in targets:
            try:
                await websocket.send_json(message)
            except Exception:
                await self.disconnect(device_id, websocket)

    def online_ids(self) -> set[str]:
        return {device_id for device_id, sockets in self.connections.items() if sockets}

