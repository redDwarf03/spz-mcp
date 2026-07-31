"""A fake agent bridge, served over a real TCP socket."""

from __future__ import annotations

import asyncio
import base64
import json

import pytest

PNG_B64 = base64.b64encode(b"\x89PNG\r\n\x1a\n fake").decode()

DESCRIBE_RESULT = {
    "protocol_version": 1,
    "app": "StableProjectorz",
    "app_version": "2.4.5",
    "tools": [
        {
            "name": "get_app_state",
            "title": "Read app state",
            "description": "Snapshot of the app.",
            "params": [],
            "read_only": True,
            "idempotent": True,
            "destructive": False,
        },
        {
            "name": "get_viewport_screenshot",
            "title": "Capture the viewport",
            "description": "PNG capture of the viewport.",
            "returns_image": True,
            "params": [
                {"name": "min_x", "type": "number", "required": False, "description": "Left edge."}
            ],
            "read_only": True,
            "idempotent": False,
        },
        {
            "name": "invoke_event",
            "title": "Fire a UI event",
            "description": "Fire a StaticEvents id.",
            "params": [
                {"name": "id", "type": "string", "required": True, "description": "Event id."},
                {"name": "args", "type": "array", "required": False, "description": "Arguments."},
            ],
            "read_only": False,
            "destructive": True,
            "idempotent": False,
        },
    ],
}


class FakeBridge:
    """Mimics the Unity side: one JSON object per line, one request at a time."""

    def __init__(self) -> None:
        self.server: asyncio.AbstractServer | None = None
        self.port = 0
        self.seen: list[dict] = []
        self.close_immediately = False
        self._writers: set[asyncio.StreamWriter] = set()

    async def start(self) -> None:
        self.server = await asyncio.start_server(self._serve, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        """Simulate the app going away, connected clients included.

        Open connections must be dropped explicitly: since Python 3.12,
        wait_closed() waits for every handler to finish, and a handler parked on
        readline() never would.
        """
        for writer in list(self._writers):
            writer.close()
        self._writers.clear()
        if self.server is not None:
            self.server.close()
            await self.server.wait_closed()
            self.server = None

    async def _serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        if self.close_immediately:
            writer.close()
            return
        self._writers.add(writer)
        try:
            while line := await reader.readline():
                request = json.loads(line.decode())
                self.seen.append(request)
                writer.write((json.dumps(self._answer(request)) + "\n").encode())
                await writer.drain()
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            self._writers.discard(writer)
            writer.close()

    def _answer(self, request: dict) -> dict:
        rid, tool = request.get("id"), request.get("tool")
        if tool == "describe":
            return {"id": rid, "ok": True, "result": DESCRIBE_RESULT}
        if tool == "get_app_state":
            return {"id": rid, "ok": True, "result": {"app_version": "2.4.5", "sd_connected": True}}
        if tool == "get_viewport_screenshot":
            return {
                "id": rid,
                "ok": True,
                "result": {"image_png_base64": PNG_B64, "width": 8, "height": 4},
            }
        if tool == "boom":
            return {"id": rid, "ok": False, "error": "it exploded"}
        if tool == "echo":
            return {"id": rid, "ok": True, "result": request.get("params")}
        return {"id": rid, "ok": False, "error": f"unknown tool '{tool}'"}


@pytest.fixture
async def fake():
    server = FakeBridge()
    await server.start()
    yield server
    await server.stop()
