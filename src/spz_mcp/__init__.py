"""MCP server for StableProjectorz."""

from .bridge import BridgeError, BridgeUnavailable, SpzBridge

__version__ = "0.1.0"
__all__ = ["BridgeError", "BridgeUnavailable", "SpzBridge", "__version__"]
