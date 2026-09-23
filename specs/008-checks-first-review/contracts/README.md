# Contracts: Checks-First Review and the Token Budget

| Contract | File | Producer → Consumer |
|----------|------|---------------------|
| The replay: the command, the reading of a recording, the two passes, the call classes, the accounting and its constant, the finding comparison, the regrouped estimate, the report, the fixtures | `replay.md` | `benchmark/recording.py`, `benchmark/replay.py` → the owner, the acceptance tests of every story |
| The tokenizer: one named encoding, fetched once into a per-user cache, loaded with no network | `tokenizer.md` | `tokens.py` → the replay, the step sizes, the report |
| Checks first: the pre-run under the pane default, live interference and its persistence, the opening digest, the re-call guard, the folded modelling-practice group | `checks-first.md` | `prerun.py`, `agent/runner.py`, `ir/loader.py`, `report/attention.py`, `report/markdown.py` → the first user message, the session, `package.json`, the report, `attention.json` |
| The model's view: reference stripping, the check digest, grouped gaps, `get_finding`, entity ids on the bridge tools, compact JSON, pruning and the stub, the stored results, the settings | `model-view.md` | `tools/model_view.py`, `tools/refs.py`, `agent/providers/pruning.py`, the two adapters, `tools/registry.py` → what the model reads, the run folder |
| The answer batch: the runner method and the route | `answer-batch.md` | the pane (feature 009's page) → `chat/server.py` → `agent/runner.py` |
| Cost: step sizes, the report's cache-split line and largest results, the pane's usage line | `cost.md` | `tools/registry.py`, `report/markdown.py`, `render.js` → the engineer, the owner |
| Command lines | `cli.md` | Engineer → `swreview benchmark replay`, `swreview review --pane-defaults` and its four explicit switches |

## Versioning

The review-session contract gains three optional properties - `folded_families`, `model_view`
(with `$defs.ModelViewSettings`) and `InvestigationStep.result_bytes`/`result_tokens` - none in
`required`, each landed in the same change as its model field. Every session written before this
feature validates, loads, renders and replays. The IR schema, the event schema and the pane
settings schema do not move. The replay report carries its own `tokenizer` and `framing_tokens`,
so a report can say how it was counted.

## What this feature does *not* move

- **A finding's content.** Findings are recorded while the tool runs, never from what the model
  reads; the model's view is derived beside the payload and never replaces it (research R2.24).
- **The golden reports and rankings.** Byte-identical except where a session names a folded
  family, which no existing golden does (FR-029).
- **`EfficiencySettings`' twelve fields, `LEVER_NAMES`, `GATED_ALONE`** and every lever-count
  pin: checks first is lever 5, parallel calls are lever 6, and the model-view settings are not
  levers (research R2.13, R2.32, R2.47).
- **`TOOL_FUNCTIONS` and its pins** (32 tools): `get_finding` is offered only with payload
  slimming, and the guard registers no tool.
- **`chat-events.schema.json`**: no event type; the pre-run rides the four events it already
  emits, and a batch writes one `evidence.answered` per answer.
- **`ir.schema.json`**: persisted rows use the existing `interferences` and `gaps` arrays.
- **`settings.schema.json` and `UserSettings.cs`**: no pane control; the defaults are code
  (`test_no_lever_in_pane_settings.py` passes unedited).
- **The MCP function list, the terminal profile and MCP payloads**: general chat is not slimmed
  in this feature (research R2.38); the two bridge tools keep their names.
- **`Serve/PROTOCOL.md`** and every C# production file except the one function `usageLine` in
  `Review/ReviewPage/render.js`.

## Where these contracts land in other features' packages

Feature 001's `contracts/review-session.schema.json` gains the three optional properties;
`contracts/cli.md` gains the `benchmark replay` row and the four `review` switches, each
cross-referencing `cli.md` here; `contracts/agent-tools.md` records `bridge_capture(entity_id,
view)` and `bridge_measure(entity_id_a, entity_id_b)` with server-side resolution, the
`get_finding` row (review only, with payload slimming), and the `already_run` answer of the six
guarded calls. Feature 002's `contracts/chat-api.md` gains the `POST /sessions/{chat_id}/evidence`
row. Feature 005's `contracts/levers.md` records lever 5 and lever 6 adopted as pane defaults on
2026-09-22 (lever 5 now including live interference, the guard, the standards line and the fold
marker) and that the model-view settings are not levers; `contracts/usage.md` sections 5 and 8
record the pane line and the report's two additions. Feature 007's `contracts/attention.md`
sections 2 to 4 record the family fold, its Start-here line and the two optional row fields,
with the one exception to "Findings byte-identical"; `contracts/gate.md` FR-030 records that
lever 5's digest now carries the standards line too.
