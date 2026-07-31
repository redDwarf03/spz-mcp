"""MCP server for StableProjectorz."""

from .bridge import BridgeError, BridgeUnavailable, SpzBridge

__version__ = "0.1.0"
__all__ = ["SpzBridge", "BridgeError", "BridgeUnavailable", "__version__"]
