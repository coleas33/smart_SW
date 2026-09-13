# Generated CLI Restriction Profiles

`CliProfileWriter` writes these on every terminal start, under `<run_dir>/.swreview-cli/`,
and passes them explicitly. Engineer edits are overwritten; a missing or changed restriction
key found in the previous file is reported on the Terminal tab. The MCP server command is
the backend interpreter running `swreview mcp --run-dir <run_dir> --bridge-pipe <pipe>
--bridge-secret-env SWREVIEW_BRIDGE_SECRET`; the secret is passed through the server's
environment block, never on the command line.

## Codex

Written to `<run_dir>/.swreview-cli/codex.toml`, merged into the user config as a profile
by invoking Codex with `--profile swreview` plus `-c` overrides for each key, so the values
below win regardless of the engineer's `~/.codex/config.toml` (research R4: project config
loads only for trusted directories, so it is not relied on).

```toml
[profiles.swreview]
sandbox_mode = "read-only"
approval_policy = "never"
web_search = "disabled"
model_instructions_file = "<run_dir>/.swreview-cli/codex-instructions.md"

[features]
shell_tool = true            # read-only shell inside the sandbox, for reading the run folder

[windows]
sandbox = "unelevated"       # native Windows sandbox; overrides any WSL routing in user config

[mcp_servers.swreview]
command = "<python>"
args = ["-m", "swreview.mcp", "--run-dir", "<run_dir>", "--bridge-pipe", "<pipe>", "--bridge-secret-env", "SWREVIEW_BRIDGE_SECRET"]
startup_timeout_sec = 30
tool_timeout_sec = 120
enabled_tools = ["get_package_summary", "list_components", "get_component", "find_components", "list_mates", "list_holes", "list_fasteners", "list_interferences", "get_drawing_sheet", "find_dimensions", "list_gaps", "get_exceptions", "measure_axis_distance", "measure_face_gap", "check_tool_envelope", "bounding_box", "request_capture", "bridge_capture", "bridge_measure"]

[mcp_servers.swreview.env]
SWREVIEW_BRIDGE_SECRET = "<secret>"
```

Launch: `codex --profile swreview -c 'sandbox_mode="read-only"' -c 'approval_policy="never"'
-c 'features.shell_tool=true' -c 'windows.sandbox="unelevated"' -C <run_dir>` with the
profile file appended to the user config through `-c` keys rather than editing the file.
`apply_patch` cannot be disabled; the read-only sandbox refuses its writes (accepted risk).

`codex-instructions.md` is a complete system prompt (Codex replaces, not appends): the
general-chat persona, the read-only rule, the tool list, and the run folder layout.

## Gemini

Written to `<run_dir>/.swreview-cli/gemini/settings.json` and
`<run_dir>/.swreview-cli/gemini/policies/00-swreview.toml`; launched with
`GEMINI_CLI_HOME=<run_dir>/.swreview-cli/gemini` (or the documented equivalent for a
settings directory override) and `--approval-mode plan`, working directory `<run_dir>`.

```json
{
  "mcpServers": {
    "swreview": {
      "command": "<python>",
      "args": ["-m", "swreview.mcp", "--run-dir", "<run_dir>", "--bridge-pipe", "<pipe>", "--bridge-secret-env", "SWREVIEW_BRIDGE_SECRET"],
      "cwd": "<run_dir>",
      "env": { "SWREVIEW_BRIDGE_SECRET": "<secret>" },
      "timeout": 120000,
      "trust": false,
      "includeTools": ["get_package_summary", "list_components", "get_component", "find_components", "list_mates", "list_holes", "list_fasteners", "list_interferences", "get_drawing_sheet", "find_dimensions", "list_gaps", "get_exceptions", "measure_axis_distance", "measure_face_gap", "check_tool_envelope", "bounding_box", "request_capture", "bridge_capture", "bridge_measure"]
    }
  },
  "mcp": { "allowed": ["swreview"] },
  "security": { "disableYoloMode": true },
  "general": { "defaultApprovalMode": "plan" },
  "context": { "fileName": ["GEMINI.md"] }
}
```

```toml
[[rule]]
toolName = "*"
decision = "deny"
priority = 1

[[rule]]
toolName = "read_file"
decision = "allow"
priority = 50

[[rule]]
toolName = "list_directory"
decision = "allow"
priority = 50

[[rule]]
mcpName = "swreview"
decision = "allow"
priority = 100
```

`GEMINI.md` in the run folder carries the same persona text as the Codex instructions; the
system prompt is not replaced for Gemini in v1 (`GEMINI_SYSTEM_MD` is reserved for later).

## Verification on first launch (both)

The Terminal tab runs the CLI's tool listing (`/mcp` in Gemini; Codex's startup tool list)
and shows a warning if any tool from the allowlist is missing or any tool outside it is
present. The `chat-log.jsonl` count confirms calls are flowing through our server.
