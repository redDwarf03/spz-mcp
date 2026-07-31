"""Exercises SpzBridge against a fake agent bridge on a real TCP socket."""

from __future__ import annotations

import asyncio

import pytest
from conftest import DESCRIBE_RESULT

from spz_mcp.bridge import BridgeError, BridgeUnavailable, SpzBridge


async def test_call_returns_result(fake):
    bridge = SpzBridge(port=fake.port)
    assert await bridge.describe() == DESCRIBE_RESULT
    await bridge.close()


async def test_failure_becomes_bridge_error(fake):
    bridge = SpzBridge(port=fake.port)
    with pytest.raises(BridgeError, match="it exploded"):
        await bridge.call("boom")
    await bridge.close()


async def test_unknown_tool_is_reported(fake):
    bridge = SpzBridge(port=fake.port)
    with pytest.raises(BridgeError, match="unknown tool"):
        await bridge.call("nope")
    await bridge.close()


async def test_token_is_attached_to_every_request(fake):
    bridge = SpzBridge(port=fake.port, token="s3cret")
    await bridge.call("echo", {"a": 1})
    await bridge.call("echo", {"b": 2})
    assert [r["params"]["token"] for r in fake.seen] == ["s3cret", "s3cret"]
    await bridge.close()


async def test_no_token_means_no_token_field(fake):
    bridge = SpzBridge(port=fake.port)
    await bridge.call("echo", {"a": 1})
    assert "token" not in fake.seen[0]["params"]
    await bridge.close()


async def test_requests_get_distinct_ids(fake):
    bridge = SpzBridge(port=fake.port)
    await bridge.call("echo")
    await bridge.call("echo")
    assert fake.seen[0]["id"] != fake.seen[1]["id"]
    await bridge.close()


async def test_concurrent_calls_are_serialised(fake):
    """The app handles one request per connection; overlapping calls must queue."""
    bridge = SpzBridge(port=fake.port)
    results = await asyncio.gather(*(bridge.call("echo", {"i": i}) for i in range(8)))
    assert [r["i"] for r in results] == list(range(8))
    await bridge.close()


async def test_app_not_running_is_unavailable():
    # Port 1 is reserved and nothing listens there.
    bridge = SpzBridge(port=1)
    with pytest.raises(BridgeUnavailable, match="--agent-bridge"):
        await bridge.call("describe")


async def test_connection_dropped_is_unavailable(fake):
    fake.close_immediately = True
    bridge = SpzBridge(port=fake.port)
    with pytest.raises(BridgeUnavailable):
        await bridge.call("describe")
    await bridge.close()


async def test_reconnects_after_a_drop(fake):
    bridge = SpzBridge(port=fake.port)
    await bridge.call("echo")
    await bridge.close()          # simulate a lost connection
    assert await bridge.describe() == DESCRIBE_RESULT
    await bridge.close()
