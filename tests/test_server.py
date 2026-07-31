"""Schema translation, annotations, and the MCP result contract (revision 2026-07-28)."""

from __future__ import annotations

import json

from conftest import PNG_B64

from spz_mcp.bridge import SpzBridge
from spz_mcp.server import STATUS_TOOL, SpzServer, _input_schema


# ---------------- input schema ----------------


def test_schema_marks_required_and_keeps_descriptions():
    schema = _input_schema(
        {
            "params": [
                {"name": "id", "type": "string", "required": True, "description": "Event id."},
                {"name": "min_x", "type": "number", "required": False, "description": "Left edge."},
            ]
        }
    )
    assert schema["properties"]["id"] == {"type": "string", "description": "Event id."}
    assert schema["properties"]["min_x"]["type"] == "number"
    assert schema["required"] == ["id"]


def test_schema_without_params_rejects_extra_keys():
    # The spec recommends this exact shape for a no-argument tool.
    assert _input_schema({"params": []}) == {"type": "object", "additionalProperties": False}


def test_schema_falls_back_for_unknown_types():
    assert _input_schema({"params": [{"name": "x", "type": "Vector2"}]})["properties"]["x"]["type"] == "string"


def test_schema_skips_unnamed_params():
    assert _input_schema({"params": [{"type": "string"}]}) == {
        "type": "object",
        "additionalProperties": False,
    }


# ---------------- list_tools ----------------


async def test_list_tools_publishes_the_apps_catalogue(fake):
    server = SpzServer(SpzBridge(port=fake.port))
    names = [t.name for t in await server.list_tools()]
    assert names == ["get_app_state", "get_viewport_screenshot", "invoke_event", STATUS_TOOL]
    await server._bridge.close()


async def test_list_tools_is_deterministically_ordered(fake):
    server = SpzServer(SpzBridge(port=fake.port))
    first = [t.name for t in await server.list_tools()]
    second = [t.name for t in await server.list_tools()]
    assert first == second
    await server._bridge.close()


async def test_read_only_tool_is_annotated_as_such(fake):
    server = SpzServer(SpzBridge(port=fake.port))
    tools = {t.name: t for t in await server.list_tools()}
    state = tools["get_app_state"].annotations
    assert state.read_only_hint is True
    assert state.destructive_hint is False
    assert state.idempotent_hint is True
    assert state.open_world_hint is False
    await server._bridge.close()


async def test_writing_tool_is_annotated_destructive(fake):
    server = SpzServer(SpzBridge(port=fake.port))
    tools = {t.name: t for t in await server.list_tools()}
    invoke = tools["invoke_event"].annotations
    assert invoke.read_only_hint is False
    assert invoke.destructive_hint is True
    assert invoke.open_world_hint is True
    await server._bridge.close()


async def test_screenshot_is_read_only_but_not_idempotent(fake):
    server = SpzServer(SpzBridge(port=fake.port))
    tools = {t.name: t for t in await server.list_tools()}
    shot = tools["get_viewport_screenshot"].annotations
    assert shot.read_only_hint is True
    assert shot.idempotent_hint is False
    await server._bridge.close()


async def test_titles_are_forwarded(fake):
    server = SpzServer(SpzBridge(port=fake.port))
    tools = {t.name: t for t in await server.list_tools()}
    assert tools["invoke_event"].title == "Fire a UI event"
    await server._bridge.close()


async def test_only_the_status_tool_is_published_when_app_is_down():
    server = SpzServer(SpzBridge(port=1))  # nothing listens on port 1
    tools = await server.list_tools()
    assert [t.name for t in tools] == [STATUS_TOOL]


async def test_catalogue_survives_a_disconnection(fake):
    bridge = SpzBridge(port=fake.port)
    server = SpzServer(bridge)
    await server.list_tools()
    await fake.stop()  # app goes away
    names = [t.name for t in await server.list_tools()]
    assert "invoke_event" in names  # last known catalogue is kept
    await bridge.close()


# ---------------- call_tool ----------------


async def test_result_carries_structured_content(fake):
    server = SpzServer(SpzBridge(port=fake.port))
    await server.list_tools()
    result = await server.call_tool("get_app_state", {})
    assert result.is_error in (False, None)
    assert result.structured_content == {"app_version": "2.4.5", "sd_connected": True}
    # The spec asks for the serialized form as text too.
    assert json.loads(result.content[0].text) == result.structured_content
    await server._bridge.close()


async def test_image_result_is_image_content(fake):
    server = SpzServer(SpzBridge(port=fake.port))
    await server.list_tools()
    result = await server.call_tool("get_viewport_screenshot", {})
    assert result.content[0].type == "image"
    assert result.content[0].mime_type == "image/png"
    assert result.content[0].data == PNG_B64
    await server._bridge.close()


async def test_image_base64_is_not_duplicated_into_structured_content(fake):
    server = SpzServer(SpzBridge(port=fake.port))
    await server.list_tools()
    result = await server.call_tool("get_viewport_screenshot", {})
    assert result.structured_content == {"width": 8, "height": 4}
    await server._bridge.close()


async def test_app_side_failure_sets_is_error(fake):
    server = SpzServer(SpzBridge(port=fake.port))
    result = await server.call_tool("boom", {})
    assert result.is_error is True
    assert "it exploded" in result.content[0].text
    await server._bridge.close()


async def test_unreachable_app_sets_is_error():
    server = SpzServer(SpzBridge(port=1))
    result = await server.call_tool("get_app_state", {})
    assert result.is_error is True
    assert "--agent-bridge" in result.content[0].text


async def test_status_tool_reports_connection(fake):
    server = SpzServer(SpzBridge(port=fake.port))
    result = await server.call_tool(STATUS_TOOL, {})
    assert result.is_error in (False, None)
    assert "2.4.5" in result.content[0].text
    await server._bridge.close()


async def test_status_tool_explains_how_to_enable_when_down():
    server = SpzServer(SpzBridge(port=1))
    result = await server.call_tool(STATUS_TOOL, {})
    assert "--agent-bridge" in result.content[0].text


async def test_arguments_reach_the_app(fake):
    server = SpzServer(SpzBridge(port=fake.port))
    await server.call_tool("echo", {"id": "Settings:OpenSettingsPanel"})
    assert fake.seen[-1]["params"]["id"] == "Settings:OpenSettingsPanel"
    await server._bridge.close()
