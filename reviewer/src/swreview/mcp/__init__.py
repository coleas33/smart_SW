"""The stdio MCP server general chat reaches the package through (`contracts/mcp-toolset.md`).

`server.py` is the server itself and `chat_log.py` is the sink every call is written to.
There is deliberately **no** `__main__.py`: the generated CLI profiles invoke the documented
subcommand `swreview mcp --run-dir ... --bridge-pipe ... --bridge-secret-env ...`, and a
second spelling (`python -m swreview.mcp`) would be a second thing to keep in step with
`contracts/cli-profiles.md`.

Nothing is imported here, so `import swreview.mcp` does not pull the `mcp` SDK into a
process that only wanted the package name - `cli.py` imports `server` inside the command.
"""

from __future__ import annotations

__all__: tuple[str, ...] = ()
