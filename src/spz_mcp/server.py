"""MCP server for StableProjectorz.

This server holds no knowledge of what StableProjectorz can do. It asks the
running app for its tool catalogue ('describe') and republishes it as MCP tools.
Adding a tool to the app therefore never requires releasing a new version of
this server, which is what lets the two repositories evolve independently.

Targets MCP revision 2026-07-28: tool annotations, structured content and
isError all come from that revision.
"""

from __future__ import annotations

import json
from typing import Any

import mcp.types as types
from mcp.server import MCPServer

from . import __version__
from .bridge import BridgeError, BridgeUnavailable, SpzBridge

SERVER_NAME = "spz-mcp"
STATUS_TOOL = "spz_bridge_status"

# Types the bridge may declare, mapped onto JSON Schema.
_JSON_TYPES = {"string", "number", "integer", "boolean", "array", "object"}

# Recommended by the spec for a tool that takes no arguments: accept only {}.
_NO_PARAMS_SCHEMA: dict[str, Any] = {"type": "object", "additionalProperties": False}

INSTRUCTIONS = """\
Drives a running StableProjectorz instance: read its state, look at the 3D viewport, \
and trigger UI actions. The tool list is published by the app itself, so it reflects \
whatever version is running. If the tools seem missing, call spz_bridge_status.\
"""


def _input_schema(tool: dict[str, Any]) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    required: list[str] = []
    for param in tool.get("params") or []:
        name = param.get("name")
        if not name:
            continue
        declared = str(param.get("type", "string"))
        schema: dict[str, Any] = {"type": declared if declared in _JSON_TYPES else "string"}
        if description := param.get("description"):
            schema["description"] = description
        properties[name] = schema
        if param.get("required"):
            required.append(name)

    if not properties:
        return dict(_NO_PARAMS_SCHEMA)
    out: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        out["required"] = required
    return out


def _annotations(tool: dict[str, Any]) -> types.ToolAnnotations:
    """Behaviour hints, as declared by the app.

    Defaults are deliberately conservative: a tool that says nothing is treated as
    one that writes, so a client errs towards asking the user first.
    """
    read_only = bool(tool.get("read_only", False))
    return types.ToolAnnotations(
        title=tool.get("title") or None,
        read_only_hint=read_only,
        destructive_hint=bool(tool.get("destructive", not read_only)),
        idempotent_hint=bool(tool.get("idempotent", False)),
        # Reading local app state is a closed domain; anything that writes may reach
        # the external WebUIs the app talks to.
        open_world_hint=not read_only,
    )


def _status_tool() -> types.Tool:
    return types.Tool(
        name=STATUS_TOOL,
        title="Check the StableProjectorz bridge",
        description=(
            "Check whether StableProjectorz is reachable and report how to enable the "
            "agent bridge. Use this when the other tools are missing or failing."
        ),
        input_schema=dict(_NO_PARAMS_SCHEMA),
        annotations=types.ToolAnnotations(
            title="Check the StableProjectorz bridge",
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
    )


def _text(payload: str) -> types.TextContent:
    return types.TextContent(type="text", text=payload)


def _error_result(message: str) -> types.CallToolResult:
    """A tool execution error: reported in-band so the model can react to it."""
    return types.CallToolResult(content=[_text(message)], is_error=True)


def _success_result(name: str, result: Any, tool: dict[str, Any]) -> types.CallToolResult:
    # An image is the payload, not a data structure. Keep the base64 out of
    # structuredContent so it is not carried twice.
    if isinstance(result, dict) and tool.get("returns_image"):
        data = result.get("image_png_base64")
        if isinstance(data, str) and data:
            meta = {k: v for k, v in result.items() if k != "image_png_base64"}
            width, height = meta.get("width"), meta.get("height")
            caption = f"{name}: {width}x{height} PNG" if width and height else name
            return types.CallToolResult(
                content=[
                    types.ImageContent(type="image", data=data, mime_type="image/png"),
                    _text(caption),
                ],
                structured_content=meta or None,
            )

    if isinstance(result, str):
        return types.CallToolResult(content=[_text(result)])

    # The spec allows any JSON value in structuredContent, and asks that the
    # serialized form also appear as text for clients that do not read it.
    rendered = json.dumps(result, indent=2, ensure_ascii=False)
    return types.CallToolResult(
        content=[_text(rendered)],
        structured_content=result if result is not None else None,
    )


class SpzServer(MCPServer):
    """MCPServer whose tool list is fetched from the app instead of being declared."""

    def __init__(self, bridge: SpzBridge) -> None:
        super().__init__(
            name=SERVER_NAME,
            title="StableProjectorz",
            version=__version__,
            instructions=INSTRUCTIONS,
        )
        self._bridge = bridge
        # Kept so a call can tell whether a tool returns an image, and so a brief
        # disconnection does not blank out the tool list.
        self._catalogue: dict[str, dict[str, Any]] = {}

    async def list_tools(self) -> list[types.Tool]:
        try:
            described = await self._bridge.describe()
        except BridgeError:
            # The app is down. Publish only the diagnostic tool, so the agent can find
            # out why instead of facing an unexplained empty toolbox.
            if not self._catalogue:
                return [_status_tool()]
        else:
            self._catalogue = {
                tool["name"]: tool for tool in (described.get("tools") or []) if tool.get("name")
            }

        # Sorted: the spec asks for a deterministic order so clients can cache.
        tools = [
            types.Tool(
                name=name,
                title=tool.get("title") or None,
                description=tool.get("description") or "",
                input_schema=_input_schema(tool),
                output_schema=tool.get("output_schema") or None,
                annotations=_annotations(tool),
            )
            for name, tool in sorted(self._catalogue.items())
        ]
        tools.append(_status_tool())
        return tools

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        context: Any | None = None,
    ) -> types.CallToolResult:
        if name == STATUS_TOOL:
            return types.CallToolResult(content=[_text(await self._status_text())])

        try:
            result = await self._bridge.call(name, arguments or {})
        except BridgeUnavailable as exc:
            return _error_result(f"StableProjectorz is unreachable.\n\n{exc}")
        except BridgeError as exc:
            return _error_result(f"'{name}' failed: {exc}")

        return _success_result(name, result, self._catalogue.get(name, {}))

    async def _status_text(self) -> str:
        try:
            described = await self._bridge.describe()
        except BridgeError as exc:
            return (
                f"Not connected to StableProjectorz at {self._bridge.address}.\n\n"
                f"{exc}\n\n"
                "To enable it, add this line to spz.config next to the executable "
                "(or at the project root when running from the Unity Editor), then "
                "restart the app:\n"
                "    --agent-bridge\n"
            )
        tools = described.get("tools") or []
        return (
            f"Connected to {described.get('app', 'StableProjectorz')} "
            f"v{described.get('app_version', '?')} at {self._bridge.address}.\n"
            f"Protocol version {described.get('protocol_version', '?')}, "
            f"{len(tools)} tools available."
        )


async def run(bridge: SpzBridge) -> None:
    await SpzServer(bridge).run_stdio_async()
