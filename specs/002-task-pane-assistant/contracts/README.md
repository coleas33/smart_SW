# Contracts: Task Pane Assistant

| Contract | File | Producer → Consumer |
|----------|------|---------------------|
| Chat backend HTTP + SSE | `chat-api.md` | Python `swreview chat serve` → add-in Review page |
| Chat event stream | `chat-events.schema.json` | Runner and tools → `events.jsonl`, SSE, CLI |
| Page ↔ host messages | `pane-host-messages.md` | WebView2 pages ↔ add-in host |
| CLI restriction profiles | `cli-profiles.md` | Add-in `CliProfileWriter` → Codex / Gemini |
| MCP toolset | `mcp-toolset.md` | Python `swreview mcp` → CLI |
| Settings file | `settings.schema.json` | Add-in ↔ per-user settings |
| Tool service protocol | feature 001 `extractor/.../Serve/PROTOCOL.md` v1.0 plus the `secret` field below | Add-in in-process server ↔ Python bridge client and MCP server |

Tool service addition: every request line carries `"secret": "<per-launch>"`; a wrong or
missing secret returns `status: "error"` with `error: "unauthorized"` and is logged. The
protocol version stays 1.0 because clients that omit the field simply fail on the in-process
host and still work against the console host.
