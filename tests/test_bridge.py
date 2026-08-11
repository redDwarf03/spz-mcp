"""Exercises SpzBridge against a fake agent bridge on a real TCP socket."""

from __future__ import annotations

import asyncio

import pytest
from conftest import DESCRIBE_RESULT

from spz_mcp.bridge import (
    BridgeError,
    BridgeUnavailable,
    SpzBridge,
    default_token_path,
    read_token_file,
)


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


async def test_token_is_read_from_the_file_the_app_generates(fake, tmp_path):
    token_file = tmp_path / "agent-bridge.token"
    token_file.write_text("generated-secret\n", encoding="utf-8")

    bridge = SpzBridge(port=fake.port, token_file=token_file)
    await bridge.call("echo")
    assert fake.seen[-1]["params"]["token"] == "generated-secret"
    await bridge.close()


async def test_explicit_token_wins_over_the_file(fake, tmp_path):
    token_file = tmp_path / "agent-bridge.token"
    token_file.write_text("from-file", encoding="utf-8")

    bridge = SpzBridge(port=fake.port, token="pinned", token_file=token_file)
    await bridge.call("echo")
    assert fake.seen[-1]["params"]["token"] == "pinned"
    await bridge.close()


async def test_token_file_appearing_later_is_picked_up(fake, tmp_path):
    """This server usually starts before the app, so the file may not exist yet."""
    token_file = tmp_path / "agent-bridge.token"
    bridge = SpzBridge(port=fake.port, token_file=token_file)

    await bridge.call("echo")
    assert "token" not in fake.seen[-1]["params"]

    token_file.write_text("appeared-later", encoding="utf-8")
    await bridge.call("echo")
    assert fake.seen[-1]["params"]["token"] == "appeared-later"
    await bridge.close()


def test_missing_token_file_is_not_an_error(tmp_path):
    assert read_token_file(tmp_path / "nope.token") is None


def test_default_token_path_is_under_the_app_name():
    assert default_token_path().parent.name == "StableProjectorz"
    assert default_token_path().name == "agent-bridge.token"


async def test_response_larger_than_the_default_line_limit(fake):
    """Regression: a real screenshot overran asyncio's 64 KiB readline default.

    The whole answer arrives as a single line, so the stream limit has to be
    raised or readline() raises LimitOverrunError on anything sizeable.
    """
    bridge = SpzBridge(port=fake.port)
    result = await bridge.call("big")
    assert len(result["blob"]) == 200_000
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
    await bridge.close()  # simulate a lost connection
    assert await bridge.describe() == DESCRIBE_RESULT
    await bridge.close()
