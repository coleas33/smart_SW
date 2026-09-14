"""One build, one version number (constitution V, DRY).

The version was written down three times - `pyproject.toml`, `swreview.__version__`, and
`mcp/server.py`'s `SERVER_VERSION` - and two of them had already drifted: the distribution
said 0.2.0 while `GET /health` told the Task Pane 0.1.0 and the MCP `serverInfo` said
0.2.0. A version the pane and the CLI report is a fact about the build an engineer reads
off a support ticket, so the three spellings have to be one.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from swreview import __version__
from swreview.mcp.server import SERVER_VERSION

PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"


def declared_version() -> str:
    return str(tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]["version"])


def test_the_package_version_is_the_one_pyproject_declares() -> None:
    """`GET /health` reports `__version__`; a stale literal there misnames the build."""
    assert __version__ == declared_version()


def test_the_mcp_server_reports_the_package_version() -> None:
    """`serverInfo.version` is what a tool-listing check names; it is the same build."""
    assert SERVER_VERSION == __version__
