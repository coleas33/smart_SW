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
missing secret returns `status: "error"` with `error: "unauthorized"` and is logged (never
with the secret in the log line). The protocol version stays 1.0 because clients that omit
the field simply fail on the in-process host and still work against the console host.

The host issues **two** secrets per launch. The review-session secret accepts
`ping | capture | measure | interference`. The general-chat secret handed to the CLI profile
accepts `ping | capture | measure` only; `interference` with that secret returns
`status: "error"`, `error: "unauthorized"`. A single shared secret would authenticate without bounding what it authorizes, and the CLI
can read its own generated profile, so scoping is what makes the read-only subset promised by
FR-022 an enforced boundary at the dispatcher rather than an MCP-allowlist convention.

Transport access control: the in-process pipe is created with an explicit `PipeSecurity`
granting `ReadWrite` to the current user's SID and nothing to anyone else. .NET Framework
4.8 has no `PipeOptions.CurrentUserOnly`, and a named pipe created with the default security
descriptor is readable by any local process, so the GUID in the pipe name is not an access
control.

Path arguments: every path a caller supplies (`run_dir` in `chat-api.md`, any path reaching
a host-side `ShellExecute`) is canonicalized and must resolve to a descendant of the
configured `run_root` (or the log folder); UNC and device paths are refused.
