"""The live SOLIDWORKS bridge: a named pipe to the C# console host (research R3).

`PROTOCOL.md` beside this file is the wire format. `client.BridgeClient` is the only way
into it; `swreview.tools.bridge` wraps it in the three tools `--bridge` adds.
"""

from swreview.bridge.client import BridgeClient, BridgeError, BridgeOpenError

__all__ = ["BridgeClient", "BridgeError", "BridgeOpenError"]
