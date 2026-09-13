# MCP Toolset for General Chat

`swreview mcp --run-dir <dir> --bridge-pipe <name> --bridge-secret-env <VAR>` runs a stdio
MCP server named `swreview` (no underscores: Gemini names tools `mcp_swreview_<tool>`).
Tool names and schemas are the canonical schemas from `providers/schema.py`; descriptions
come from the tool docstrings. Every call is appended to `<run_dir>/chat-log.jsonl`.

Exposed (read-only subset of feature 001 `contracts/agent-tools.md`):

| Group | Tools |
|-------|-------|
| Package query | `get_package_summary`, `list_components`, `get_component`, `find_components`, `list_mates`, `list_holes`, `list_fasteners`, `list_interferences`, `get_drawing_sheet`, `find_dimensions`, `list_gaps`, `get_exceptions` |
| Measurement | `measure_axis_distance`, `measure_face_gap`, `check_tool_envelope`, `bounding_box` |
| Captures | `request_capture` (returns an existing capture or, with the bridge, a new one) |
| Live bridge | `bridge_capture`, `bridge_measure` (only when a bridge pipe is configured) |

Not exposed, by construction: `check_fit`, `check_axial_stack`, `check_fastener_joint`,
`check_hole_alignment`, `check_interference_group`, `record_drawing_finding`,
`request_evidence`, `mark_coverage`, `get_review_checklist`, `bridge_interference`. General
chat cannot create findings, coverage, or evidence requests (FR-025), and cannot start an
interference run (it is long and writes into `package.json`).

Session context: the server loads `<run_dir>/package.json` at startup and exposes it as the
tool context; there is no review session, so tools that would record steps write to the chat
log instead. If `package.json` is absent the server starts with an empty package and every
query returns an error result naming the missing file, so the CLI can tell the engineer to
press Review or Dump IR first.

Resources: `swreview://package/summary` (text) and `swreview://report` (the latest
`report.md`, if any) are offered as MCP resources for CLIs that support them. Prompts: none
in v1.
