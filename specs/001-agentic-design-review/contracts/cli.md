# Command-Line Contracts

## `swreview` (Python, `reviewer/`)

Installed as a console script by `uv sync`. Exit code 0 on success, 1 on a validation or
runtime error, 2 on usage error. Every command that prints a result accepts `--json` to
print machine-readable output to stdout; human output goes to stdout otherwise,
diagnostics to stderr. Two commands own their stdout instead and take no `--json`:
`chat serve` prints one handshake line and nothing else, and `mcp` uses stdout as the MCP
transport.

The commands that run a model - `review` and `benchmark run` - share three options:

| Option | Values | Default |
|--------|--------|---------|
| `--provider` | `openai`, `gemini` (`fake` is the scripted provider the tests use) | `openai` |
| `--model` | any model id the provider serves | that provider's own default, from `reviewer/src/swreview/agent/settings.py` |
| `--effort` | `low`, `medium`, `high`, `xhigh` | `high` |

`--model` is deliberately optional and no command line carries a hard-coded model id: the
default belongs to the provider and lives in one module, so a run started without `--model`
cannot write the id of a model this product no longer serves into `session.json` (FR-026).
The API key is never an argument. Values saved in the pane's `settings.json` win over the
process environment (`OPENAI_API_KEY`; for Gemini `GOOGLE_API_KEY` ahead of
`GEMINI_API_KEY`), so a workstation that exports a personal key cannot quietly override the
key the engineer entered in the pane; a command line started outside the pane has only the
environment. Which of the two it came from is recorded on the session as `key_source`. The key itself never reaches a session file, a report, a run folder or a log
line (FR-015); `audit-secrets` is the check that says so.

| Command | Arguments | Effect |
|---------|-----------|--------|
| `swreview validate <package_dir>` | | Loads `package.json` against the IR schema and prints gaps and discrepancies. Fails on major version mismatch. |
| `swreview ingest <package_dir>` | `--pdf <file>...`, `--bom <csv>`, `--manifest <json>`, `--step <file>...` | Builds or augments `package.json` from exported files (drawing parse, BOM, manifest). Native data, when present, wins over exported data for the same entity. |
| `swreview review <package_dir>` | `--out <dir>`, `--provider`, `--model`, `--effort` (see the table above), `--bridge`, `--checklist <file>`, `--fail-tool <name>` (test hook), `--max-steps N` | Runs the agent loop; writes `session.json` and `report.md`. |
| `swreview report <session.json>` | `--out <file.md>` | Re-renders the Markdown report. |
| `swreview disposition <run_dir> <finding_id>` | `--decision accepted\|rejected\|deferred`, `--note`, `--by` | Records a disposition and re-renders. |
| `swreview exceptions accept <run_dir> <finding_id>` | `--note` | Creates an `Exception` bound to the finding's geometry fingerprint and configuration. |
| `swreview exceptions list <package_dir>` | | Shows active and needs-review exceptions. |
| `swreview check fit\|stack\|fastener\|alignment` | `--package <dir>` plus check-specific ids | Runs one deterministic check without the agent; prints the finding. |
| `swreview check interference` | `--package <dir>`, `--json` | Grades a dumped package's interference results without the agent: grouped conditions with status, exception statuses after refresh, unresolved coverage. Read-only; never writes `exceptions.json`. |
| `swreview benchmark run` | `--set <set.json>`, `--out <dir>`, `--provider`, `--model`, `--effort` | Reviews every package in the set with answer keys unreadable. |
| `swreview benchmark score <run_dir>` | `--answer-keys <dir>` | Produces `scorecard.json` and `scorecard.md`. |
| `swreview benchmark time <run_dir> <package_id>` | `--baseline M`, `--supervision M`, `--verification M`, `--false-alarms M` | Records timing for net-savings computation. |
| `swreview chat serve` | `--port N` (0 lets the OS pick), `--allow-origin <origin>`, `--run-root <dir>`, `--dev`, `--fail-bridge N` (test hook) | Serves the Task Pane chat backend on 127.0.0.1 and prints `{"port": N, "token": "..."}` as the first and only line on stdout. `python -m swreview.chat` is the same implementation with the same arguments. Wire shapes in `specs/002-task-pane-assistant/contracts/chat-api.md`. |
| `swreview mcp` | `--run-dir <dir>`, `--bridge-pipe <name>`, `--bridge-secret-env <var>` | Serves the read-only general-chat toolset on stdio for an external CLI (`specs/002-task-pane-assistant/contracts/mcp-toolset.md`). This is the only spelling: there is no `-m swreview.mcp`. stdout is the transport, so the command prints nothing of its own; a failure to start is one line on stderr and exit 1. The bridge secret is named by its environment variable, never passed as a value, because a command line is readable by every process on the workstation. |
| `swreview audit-secrets <path>...` | `--bridge-secret-env <var>`, `--detectors\|--no-detectors` (default on), `--json` | Reports any configured secret that reached a file under `path` (FR-015): exit 1 naming the file, the line and the source for every hit, exit 0 when there is none. A file it cannot read is a hit too - unread coverage reported as "none" is the false green the command exists to prevent - and so is having nothing to detect with (no key in the environment, no bridge secret, `--no-detectors`). Detectors flag provider-shaped keys (`sk-...`, `AIza...`), which is what carries the check on the workstation, where the key is DPAPI-protected and reaches only the backend child's environment. Neither the secret nor the line it sat on is ever printed. |

## `SwReview.Extractor.Console.exe` (C#, `extractor/`)

Out-of-process host around the same extraction library the add-in uses. Requires SOLIDWORKS
2024 installed. **Attach-only by default**: every command attaches to the running instance
and never starts one, because a started session holds a licence and has none of the
engineer's open documents, so it would describe a different model. When the attach fails the
host says which fact differs between SOLIDWORKS and itself (not running / different Windows
session / different integrity level) rather than listing guesses. Exit code 0 success,
1 error; always writes `extract.log` next to the output.

| Command | Arguments | Effect |
|---------|-----------|--------|
| `dump` | `--doc <path>` (or active document), `--config <name>`, `--out <dir>`, `--meshes glb\|stl\|none`, `--faces needed\|all` | Writes `package.json`, `meshes/`, and appends `gaps` for anything not extractable. |
| `interference` | `--config`, `--pairs all\|<id,id>...`, `--coincident-as-interference`, `--subassemblies-as-components`, `--fasteners include\|exclude\|only`, `--out <dir>`, `--truncate-after N` (test hook) | Appends `interferences` to `package.json` with per-pair status. |
| `capture` | `--ref <persist_ref>`, `--view iso\|front\|top\|right\|fit`, `--out <dir>` | Zooms to the entity and saves a PNG; appends a `Capture`. |
| `resolve` | `--ref <persist_ref>` | Prints the entity name and type the reference resolves to (round-trip test). |
| `serve` | `--pipe <name>` | Runs the bridge for the Python `--bridge` tools: one JSON request per line on a named pipe, one COM STA worker thread. |
| *(all of the above)* | `--allow-start` | Permits starting a SOLIDWORKS session when none is running. Off by default; for unattended scripts only. |

Add-in: the same library is loaded in-process by `SwReview.AddIn` and exposes Task Pane
buttons **Dump IR**, **Interference**, and **Capture selection** that call the same entry
points with the active document.
