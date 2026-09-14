"""SOLIDWORKS agentic design review: IR models, deterministic checks, report."""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _installed_version

try:
    __version__ = _installed_version("swreview")
except PackageNotFoundError:  # pragma: no cover - a source tree nothing installed from
    # `GET /health` and the MCP `serverInfo` both report this, so an unknown build says so
    # rather than repeating a literal that would go stale the way the last one did.
    __version__ = "0+unknown"
