# Tool listing fixtures (T061a)

What `ToolListingCheckTests` compares the first-launch gate against. The gate is the reason
they exist: a CLI that quietly loaded a different toolset than the generated profile asked for
is the failure the read-only guarantee exists to prevent, so the parser that spots it has to be
tested against listings the CLIs really produce, not against listings we wish they produced.

## `codex-startup-listing*.json` - captured, not written

Real responses from **codex-cli 0.115.0** on 2026-09-13, captured with a scratch `CODEX_HOME`
that registered a trivial stdio MCP server named `swreview` (Python, `mcp` 2.2.0,
`MCPServer`), one no-op tool per name. Nothing in them is redacted or edited; the schemas and
the `"<name>."` descriptions are what that trivial server declares.

How they were taken, so the capture can be repeated when Codex changes:

1. Write `<scratch>/codex-home/config.toml` with `[mcp_servers.swreview]` (`command`, `args`,
   `enabled_tools`) exactly as `contracts/cli-profiles.md` specifies, and copy
   `%USERPROFILE%\.codex\auth.json` into that home.
2. Start `codex app-server` with `CODEX_HOME` pointed at it and speak the app-server JSON-RPC
   protocol on stdio: `initialize`, the `initialized` notification, then
   `mcpServerStatus/list`. The `result` of that response is the fixture.

`mcpServerStatus/list` is the machine-readable form of what the interactive CLI prints at
startup: it is the CLI reporting the servers it actually connected to and the tools it
actually loaded from them, which is the only listing worth gating on. `codex mcp list` and
`codex mcp get` were tried first and rejected - both echo `config.toml` back without ever
starting the server, so they would pass a gate on a CLI whose MCP server never came up.

| File | What it is |
|------|------------|
| `codex-startup-listing.json` | the 22 allowlisted tools and nothing else |
| `codex-startup-listing-missing-tool.json` | the same server with `list_mates` never registered |
| `codex-startup-listing-extra-tool.json` | the same server plus a `write_file` tool, and an `enabled_tools` that admits it - a profile that was edited, or a server that grew a tool |

The `list_features`, `get_feature` and `list_equations` entries were **not** in the 2026-09-13
capture: the allowlist did not carry them yet (feature 003, T026 and T042). They were added by
hand in the shape the other entries have, which for this trivial server is mechanical - one
no-op tool per name - so the fixture still says what a re-capture would. Re-take the capture
the next time Codex changes rather than hand-adding a fourth one.

Note what a Codex listing does **not** contain: Codex's own built-in tools. The intended
built-in set is therefore permitted-if-present rather than required (see `ToolListingCheck`).

## `gemini-mcp-transcript*.txt` - hand-authored from the documentation

The Gemini terminal is deferred (decision 2026-09-13; spike T055a), and the CLI is not
installed on the development workstation, so these are written from the documented `/mcp`
output shape in `google-gemini/gemini-cli` `docs/tools/mcp-server.md` - the
`MCP Servers Status:` header, the `<emoji> <server> (CONNECTED)` line, the indented
`Command:` / `Working Directory:` / `Timeout:` / `Tools:` lines, and the closing
`Discovery State:`. They exercise the parser only. **Nothing here is evidence about the real
CLI**, and T055a must re-capture them from an installed Gemini CLI before anything Gemini-
specific is asserted beyond parsing.

Tool names carry the `mcp_<server>_` prefix the same document shows
(`mcp_dockerizedServer_docker_deploy`), because that prefix is precisely the plan's
"Gemini renames or truncates tool names" risk: a gate that compared prefixed names literally
would report all twenty-two tools missing on a perfectly good session.
