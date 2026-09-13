# Command-Line Contracts

## `swreview` (Python, `reviewer/`)

Installed as a console script by `uv sync`. Exit code 0 on success, 1 on a validation or
runtime error, 2 on usage error. All commands accept `--json` to print machine-readable
output to stdout; human output goes to stdout otherwise, diagnostics to stderr.

| Command | Arguments | Effect |
|---------|-----------|--------|
| `swreview validate <package_dir>` | | Loads `package.json` against the IR schema and prints gaps and discrepancies. Fails on major version mismatch. |
| `swreview ingest <package_dir>` | `--pdf <file>...`, `--bom <csv>`, `--manifest <json>`, `--step <file>...` | Builds or augments `package.json` from exported files (drawing parse, BOM, manifest). Native data, when present, wins over exported data for the same entity. |
| `swreview review <package_dir>` | `--out <dir>`, `--model <id>` (default `claude-opus-5`), `--effort low\|medium\|high\|xhigh`, `--bridge`, `--checklist <file>`, `--fail-tool <name>` (test hook), `--max-steps N` | Runs the agent loop; writes `session.json` and `report.md`. |
| `swreview report <session.json>` | `--out <file.md>` | Re-renders the Markdown report. |
| `swreview disposition <run_dir> <finding_id>` | `--decision accepted\|rejected\|deferred`, `--note`, `--by` | Records a disposition and re-renders. |
| `swreview exceptions accept <run_dir> <finding_id>` | `--note` | Creates an `Exception` bound to the finding's geometry fingerprint and configuration. |
| `swreview exceptions list <package_dir>` | | Shows active and needs-review exceptions. |
| `swreview check fit\|stack\|fastener\|alignment` | `--package <dir>` plus check-specific ids | Runs one deterministic check without the agent; prints the finding. |
| `swreview benchmark run` | `--set <set.json>`, `--out <dir>`, `--model`, `--effort` | Reviews every package in the set with answer keys unreadable. |
| `swreview benchmark score <run_dir>` | `--answer-keys <dir>` | Produces `scorecard.json` and `scorecard.md`. |
| `swreview benchmark time <run_dir> <package_id>` | `--baseline M`, `--supervision M`, `--verification M`, `--false-alarms M` | Records timing for net-savings computation. |

## `SwReview.Extractor.Console.exe` (C#, `extractor/`)

Out-of-process host around the same extraction library the add-in uses. Requires SOLIDWORKS
2024 installed; attaches to a running instance or starts one. Exit code 0 success, 1 error;
always writes `extract.log` next to the output.

| Command | Arguments | Effect |
|---------|-----------|--------|
| `dump` | `--doc <path>` (or active document), `--config <name>`, `--out <dir>`, `--meshes glb\|stl\|none`, `--faces needed\|all` | Writes `package.json`, `meshes/`, and appends `gaps` for anything not extractable. |
| `interference` | `--config`, `--pairs all\|<id,id>...`, `--coincident-as-interference`, `--subassemblies-as-components`, `--fasteners include\|exclude\|only`, `--out <dir>`, `--truncate-after N` (test hook) | Appends `interferences` to `package.json` with per-pair status. |
| `capture` | `--ref <persist_ref>`, `--view iso\|front\|top\|right\|fit`, `--out <dir>` | Zooms to the entity and saves a PNG; appends a `Capture`. |
| `resolve` | `--ref <persist_ref>` | Prints the entity name and type the reference resolves to (round-trip test). |
| `serve` | `--pipe <name>` | Runs the bridge for the Python `--bridge` tools: one JSON request per line on a named pipe, one COM STA worker thread. |

Add-in: the same library is loaded in-process by `SwReview.AddIn` and exposes Task Pane
buttons **Dump IR**, **Interference**, and **Capture selection** that call the same entry
points with the active document.
