# Generated CLI Restriction Profiles

`CliProfileWriter` writes these on every terminal start, under `<run_dir>/.swreview-cli/`,
and passes them explicitly. Engineer edits are overwritten; a missing or changed restriction
key found in the previous file is reported on the Terminal tab.

**MCP server command (both CLIs).** The server is started as the documented subcommand
`swreview mcp --run-dir <run_dir> --bridge-pipe <pipe> --bridge-secret-env
SWREVIEW_BRIDGE_SECRET` (`mcp-toolset.md`, `contracts/README.md`). There is no
`swreview.mcp.__main__`, so `-m swreview.mcp` is not a valid spelling. `CliProfileWriter`
resolves the settings `python` field into a command line before writing the profile:

| settings `python` | `command` | leading `args` |
|-------------------|-----------|----------------|
| a `python.exe` | that path | `["-m", "swreview.cli", "mcp", ...]` |
| a `uv.exe` | that path | `["run", "--project", "<reviewer>", "swreview", "mcp", ...]` |
| null (auto-located) | whichever of the two is found, same rule | as above |

Below, `<mcp-command>` and `<mcp-args-prefix>` stand for the resolved pair. The bridge
secret is passed through the MCP server's environment block, never on a command line.

**Secret scope.** The general-chat secret handed to the CLI is scoped by the in-process
host to `ping`, `capture` and `measure`; `interference` is refused for it with
`unauthorized` (`contracts/README.md`). The CLI process can read its own profile, so the
secret must not be the only thing standing between general chat and a command the MCP
allowlist withholds.

## Codex

Codex resolves `--profile <name>` against `$CODEX_HOME/config.toml` (default
`~/.codex/config.toml`) and has no flag that points it at an arbitrary config file, so a
TOML file merely sitting in the run folder is never read, and `-c key=value` overrides
cannot register an MCP server table. The generated home **is** the config home:

- write `<run_dir>/.swreview-cli/codex-home/config.toml` (below) and
  `<run_dir>/.swreview-cli/codex-home/codex-instructions.md`;
- launch with `CODEX_HOME=<run_dir>/.swreview-cli/codex-home` in the child environment.

`CODEX_HOME` also relocates `auth.json`, and the engineer signs in with an organization
account that the pane never re-authenticates (spec Assumptions). The writer therefore copies
`%USERPROFILE%\.codex\auth.json` into the generated home at every launch (and refuses to
start with an explanatory message when it is absent) so the existing sign-in survives.
Verified on Codex CLI 0.115.0: with `CODEX_HOME` pointed at a scratch home containing
`[profiles.swreview]`, `codex exec --profile swreview` resolves the profile and starts; the
same run fails `401 Unauthorized` when `auth.json` is not present in that home. Without
`CODEX_HOME`, `codex exec --profile swreview` on a machine whose user config has no such
profile fails with `Error: config profile 'swreview' not found`.

```toml
# <run_dir>/.swreview-cli/codex-home/config.toml - the whole config, not a fragment.
# Top-level keys are the defaults; the profile repeats the restriction keys so they win
# whichever level Codex reads.
sandbox_mode = "read-only"
approval_policy = "never"
web_search = "disabled"
model_instructions_file = "<run_dir>/.swreview-cli/codex-home/codex-instructions.md"

[features]
shell_tool = true            # read-only shell inside the sandbox; see plan.md Complexity Tracking

[windows]
sandbox = "unelevated"       # native Windows sandbox; overrides any WSL routing in user config

[profiles.swreview]
sandbox_mode = "read-only"
approval_policy = "never"
web_search = "disabled"
model_instructions_file = "<run_dir>/.swreview-cli/codex-home/codex-instructions.md"

[mcp_servers.swreview]
command = "<mcp-command>"
args = [<mcp-args-prefix>, "--run-dir", "<run_dir>", "--bridge-pipe", "<pipe>", "--bridge-secret-env", "SWREVIEW_BRIDGE_SECRET"]
startup_timeout_sec = 30
tool_timeout_sec = 120
enabled_tools = ["get_package_summary", "list_components", "get_component", "find_components", "list_mates", "list_holes", "list_fasteners", "list_interferences", "get_drawing_sheet", "find_dimensions", "list_gaps", "get_exceptions", "measure_axis_distance", "measure_face_gap", "check_tool_envelope", "bounding_box", "request_capture", "bridge_capture", "bridge_measure"]

[mcp_servers.swreview.env]
SWREVIEW_BRIDGE_SECRET = "<secret>"
```

Launch (this is the complete, normative argument list; T056 asserts exactly it):

```text
env CODEX_HOME=<run_dir>/.swreview-cli/codex-home
codex --profile swreview
  -c 'sandbox_mode="read-only"'
  -c 'approval_policy="never"'
  -c 'web_search="disabled"'
  -c 'features.shell_tool=true'
  -c 'windows.sandbox="unelevated"'
  -C <run_dir>
```

The `-c` overrides are belt and braces for the five scalar restriction keys; the MCP server
table, `enabled_tools` and `model_instructions_file` are carried by the generated
`config.toml` alone, because `-c` cannot express them. `apply_patch` cannot be disabled; the
read-only sandbox refuses its writes (accepted risk).

`codex-instructions.md` is a complete system prompt (Codex replaces, not appends): the
general-chat persona, the read-only rule, the tool list, and the run folder layout.

## Gemini

Written to `<settings-home>/settings.json` and `<settings-home>/policies/00-swreview.toml`
where `<settings-home>` is `<run_dir>/.swreview-cli/gemini`; launched with
`--approval-mode plan` and working directory `<run_dir>`.

**Unverified - resolve in spike task T055a before T056/T057 (research open risk 5).** The settings-home
override variable is written here as `GEMINI_CLI_HOME=<settings-home>`, but Gemini CLI is not
installed on the development workstation and the name is not established by research. The
spike task verifies the exact variable (or flag) on the installed CLI, records the CLI
version it was verified against in this file, and removes this paragraph. Until then the
byte-for-byte test may not assert the launch environment. Two further points must be settled
by T055a: whether the override also relocates the CLI's credential store (as
`CODEX_HOME` does - if so, the same auth passthrough applies), and whether `mcp.allowed`,
`security.disableYoloMode`, `general.defaultApprovalMode`, `context.fileName`, the per-server
`trust` key and the `toolName = "*"` wildcard deny rule below are spelled as written; only
`mcpServers.swreview` (`command`/`args`/`cwd`/`env`/`timeout`/`includeTools`), the
deny-all-plus-`mcpName`-allow policy shape and `--approval-mode plan` come from R4.

```json
{
  "mcpServers": {
    "swreview": {
      "command": "<mcp-command>",
      "args": [<mcp-args-prefix>, "--run-dir", "<run_dir>", "--bridge-pipe", "<pipe>", "--bridge-secret-env", "SWREVIEW_BRIDGE_SECRET"],
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
and compares it with two lists: the MCP `enabled_tools` allowlist above, and the CLI's own
built-in tools the profile intends to leave enabled (Codex: the read-only shell and
`apply_patch`; Gemini: `read_file`, `list_directory`). This check **gates the session**: if
any allowlisted `swreview` tool is missing, or any tool outside both lists is present, the
tab shows the difference and the terminal does not start. Falling back to an unrestricted
CLI is the failure the read-only guarantee exists to prevent, so it is never a warning.

A scripted refusal probe runs in quickstart Scenario 3 for both CLIs: a write into
`<run_dir>` (`write_file` / `apply_patch`) and a shell command outside the sandbox must both
be refused, and the result is recorded in the notes file. The `chat-log.jsonl` count confirms
calls are flowing through our server.
