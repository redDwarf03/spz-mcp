"""Async client for the StableProjectorz agent bridge.

Wire format is one JSON object per line over TCP:

    ->  {"id":"1","tool":"describe","params":{}}
    <-  {"id":"1","ok":true,"result":{...}}

The Unity side serves one request at a time per connection, so calls are
serialised behind a lock rather than multiplexed by id.
"""

from __future__ import annotations

import asyncio
import itertools
import json
from typing import Any

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765

# A tool may legitimately take a while: a screenshot waits on an async GPU
# readback. Stay above the bridge's own 30 s command timeout so that its error
# message reaches us instead of being masked by ours.
DEFAULT_TIMEOUT = 45.0
CONNECT_TIMEOUT = 5.0


class BridgeError(RuntimeError):
    """The app answered, but the command failed."""


class BridgeUnavailable(BridgeError):
    """The app could not be reached at all."""


class SpzBridge:
    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        token: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self.host = host
        self.port = port
        self.token = token
        self.timeout = timeout
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._lock = asyncio.Lock()
        self._ids = itertools.count(1)

    @property
    def address(self) -> str:
        return f"{self.host}:{self.port}"

    async def _connect(self) -> None:
        if self._writer is not None and not self._writer.is_closing():
            return
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port),
                timeout=CONNECT_TIMEOUT,
            )
        except (OSError, asyncio.TimeoutError) as exc:
            self._reader = self._writer = None
            raise BridgeUnavailable(
                f"No agent bridge at {self.address}. Start StableProjectorz with "
                f"'--agent-bridge' in spz.config, and check the port matches. ({exc})"
            ) from exc

    async def call(self, tool: str, params: dict[str, Any] | None = None) -> Any:
        async with self._lock:
            await self._connect()
            assert self._reader is not None and self._writer is not None

            payload: dict[str, Any] = dict(params or {})
            if self.token:
                payload["token"] = self.token
            request = {"id": str(next(self._ids)), "tool": tool, "params": payload}

            try:
                self._writer.write(
                    (json.dumps(request, separators=(",", ":")) + "\n").encode("utf-8")
                )
                await self._writer.drain()
                raw = await asyncio.wait_for(self._reader.readline(), timeout=self.timeout)
            except (OSError, asyncio.TimeoutError) as exc:
                await self.close()
                raise BridgeUnavailable(f"Lost the connection to {self.address}: {exc}") from exc

            if not raw:
                await self.close()
                raise BridgeUnavailable(f"{self.address} closed the connection.")

            try:
                response = json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError as exc:
                raise BridgeError(f"Malformed answer from the app: {exc}") from exc

            if not response.get("ok"):
                raise BridgeError(
                    response.get("error") or "The app reported an unspecified failure."
                )
            return response.get("result")

    async def describe(self) -> dict[str, Any]:
        result = await self.call("describe")
        if not isinstance(result, dict):
            raise BridgeError("'describe' did not return an object.")
        return result

    async def close(self) -> None:
        writer, self._writer, self._reader = self._writer, None, None
        if writer is None:
            return
        try:
            writer.close()
            await writer.wait_closed()
        except (OSError, RuntimeError):
            pass
