from __future__ import annotations

import argparse
import asyncio
import os
import sys

from .bridge import DEFAULT_HOST, DEFAULT_PORT, SpzBridge
from .server import run


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="spz-mcp",
        description="MCP server exposing a running StableProjectorz instance to an LLM agent.",
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("SPZ_HOST", DEFAULT_HOST),
        help=f"Agent bridge host (default: {DEFAULT_HOST}, env: SPZ_HOST).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("SPZ_PORT", DEFAULT_PORT)),
        help=f"Agent bridge port (default: {DEFAULT_PORT}, env: SPZ_PORT).",
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("SPZ_TOKEN"),
        help="Shared secret, if the app was started with --agent-bridge-token (env: SPZ_TOKEN).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    bridge = SpzBridge(host=args.host, port=args.port, token=args.token)
    try:
        asyncio.run(run(bridge))
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
