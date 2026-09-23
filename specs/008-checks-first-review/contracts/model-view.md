# Contract: The Model's View

Normative for what the model reads of a tool result, the bridge tools' entity ids, pruning, the
stub, the stored results and the settings that switch them (FR-015 to FR-023, SC-007, SC-008).

## 1. The rule this contract exists for

The model reads a **view**; the run folder keeps the **record**. A tool's return is
`ToolCallResult.payload`, unchanged, and is what the session's summary, the `tool.finished`
event, the Model check route, MCP and the golden fixtures read. The view is
`ToolCallResult.view`, computed once at `RecordedTool._finish` when payload slimming is on
(None otherwise), and `model_payload(result)` - the view when present, else the payload - is the
only content an adapter puts into its history. Findings are recorded while the tool runs, so no
view can change a finding (SC-007).

## 2. Reference stripping (FR-015)

`strip_references(value)` returns a copy with:

- the keys `persist_ref`, `persist_ref_scope`, `persist_ref_scopes` and `component_persist_refs`
  removed at any depth;
- the inline token ` persist_ref=<base64>` or ` persist_ref=none` removed from every string (the
  RMS and standards input formats), `scope=<id>` kept.

It never mutates its input. The package, the session, `report.md` and the stored results keep
every reference unchanged. Test rule: for every tool, called on a fixture package with slimming
on, no persist-reference **value** of that package appears anywhere in the serialized view.

## 3. The check digest (FR-018)

`check_digest(payload, *, counts_only=False)` is the view of every check tool (the names
`ToolRegistry.check_tools()` and `standards_tools()` return), with one `detail` sentence added by
the view table:

```json
{"status": "ok", "findings": 85, "rules": 7,
 "by_status": {"demonstrated": 51, "suspected": 34},
 "by_severity": {"low": 34, "medium": 51},
 "rows": [{"id": "F-001", "check": "rms.params.global_variables_present", "status": "demonstrated",
           "severity": "medium", "title": "…"}],
 "rows_omitted": 60,
 "finding_ids": ["F-001", "…"], "finding_ids_omitted": 0,
 "subjects": 26, "coverage": {"checked": 5, "skipped": 11},
 "detail": "get_finding(finding_id) returns one finding in full"}
```

`rows` holds at most 25 in payload order and `finding_ids` at most 200, each with its omitted
count; a finding past the 200th id cannot be fetched because the model never saw its id, and the
count says so. `by_status` and `by_severity` keys are sorted. `subjects` is the sum of the
payload's `subjects` map when present, else the distinct component ids. The payload's other
top-level scalars (`group_key`, `configuration`, `members`) are kept. `counts_only` drops `rows`,
`finding_ids` and both omitted counts; the re-call guard uses it for a folded family
(`checks-first.md` section 5). A payload with neither `findings` nor `finding` passes through.
The same bytes for the same payload in any process.

## 4. Grouped gaps (FR-019)

The view of `list_gaps`: `{groups, rows}`, each group `{kind, entity_kind, reason, rows,
entity_ids, entity_ids_omitted}`, keyed by `(kind, entity_kind, reason with every single-quoted
substring replaced by "…")`, the reason being the first row's full text, `entity_ids` the first
five, groups in first-appearance order.

## 5. `get_finding` and the bridge tools' ids (FR-016, FR-018)

| Tool | Contract |
|---|---|
| `get_finding(finding_id)` | Returns `{"finding": <the finding exactly as the session records it>}`; its view is stripped. An unknown id is an error result naming it (and a failed coverage item, as every tool error). Offered in a review **only with payload slimming**, appended like `compact_query`; never in MCP or the terminal profile |
| `bridge_capture(entity_id, view)` | Resolves `entity_id` through `tools/refs.resolve_entity_ref(package, entity_id)` and sends that entity's persist reference to the bridge; records the capture with it |
| `bridge_measure(entity_id_a, entity_id_b)` | Resolves both ids; the payload names `entity_id_a` and `entity_id_b` and carries no reference |

`resolve_entity_ref` searches components, features, mates, holes, threads, fasteners, faces,
bodies, cut-list items and captures, and refuses - as an error result naming the id, with no
bridge call - an unknown id, an entity whose reference is null, and an id found under two kinds
with different references. The bridge tools take ids whatever the settings, and in MCP general
chat too; their names do not change.

## 6. Compact JSON (FR-017)

`tool_result_text(payload, *, compact=False)` is the one serialization of a result: `json.dumps`
with default separators, or `separators=(",", ":")` when compact. The OpenAI adapter's
`_encode_history(messages, *, compact=False)` passes `compact` through for `function_call_output`;
compact is on exactly when payload slimming is on. Gemini's SDK serializes its own
`function_response`; nothing changes there.

## 7. Pruning and the stub (FR-020, FR-022)

`prune_history(messages, prune_after_rounds) -> list[dict]`, a pure function over the neutral
history, applied to every request by both adapters when history pruning is on (OpenAI before
`_encode_history`; Gemini by rebuilding `contents` from the pruned history each round). A `tool`
message is replaced by its stub when all hold:

1. its **age** - the number of assistant messages after it - is at least `prune_after_rounds`;
2. it is not an error result;
3. its compact stub is shorter than its compact content;
4. its arguments are known by position from the preceding assistant message's `tool_calls`.

User messages (the opening digest, the engineer's text, the answer message) and assistant
messages are never touched; nothing is mutated; an unmatched tool message is kept. The stub
(data-model section 11):

```json
{"pruned": "shown in full earlier; summarised here", "tool": "list_mates", "arguments": {},
 "counts": {"mates": 55}, "ids": ["mate:0001", "…"], "ids_omitted": 35,
 "refetch": "call list_mates again with these arguments to read it in full"}
```

`refetch` adds `" or get_finding(<id>) for one finding"` when the content carries finding ids.
The stub is deterministic in `(name, arguments, content)`. Because the runner's history stays
append-only and each turn's first request is built from it, pruning applies between turns with no
further code, and a follow-up carries stubs, not payloads.

## 8. The stored results (FR-021, SC-008)

`SessionSink.record` writes `<out>/tool-results/step-<index>.json` - `{session_id, step, tool,
arguments, status, payload}`, `indent=2`, `ensure_ascii=False`, trailing newline, `payload` the
full return - for **every** recorded step of a review: ok, error, withheld, unknown tool, pre-run,
guard answer, whatever the settings, before the adapter's next request. Only `start_review` sets
`ToolContext.tool_results_dir`, so check runs and MCP write none. An `OSError` becomes one
`failed` coverage item naming the step; the review continues. A pane retry moves `tool-results/`
to `tool-results.<n>` beside `session.<n>.json`, and `_next_free_index` skips an occupied one.

## 9. Settings

```python
class ModelViewSettings(BaseModel, frozen=True, extra="forbid"):
    payload_slimming: bool
    history_pruning: bool
    prune_after_rounds: int = Field(2, ge=1)

MODEL_VIEW_OFF  = ModelViewSettings(payload_slimming=False, history_pruning=False)
MODEL_VIEW_PANE = ModelViewSettings(payload_slimming=True,  history_pruning=True)
```

Not levers: `EfficiencySettings` and `LEVER_NAMES` do not change. `start_review(model_view=None)`
records `MODEL_VIEW_OFF`; the session records what ran (`ReviewSession.model_view`, absent on
older sessions = off). `start_review` calls `use_model_view(settings)` once on an adapter that
implements `ModelViewAware` (OpenAI stores the prune age and compact; Gemini the prune age). The
pane passes `pane_defaults(provider).model_view`; the command line is off unless asked
(`cli.md`); `benchmark run` stays off.

## 10. Lever 7 under slimming

`CoverageStopTools` annotates the view as well as the payload when a view is present, so its stop
sentence still reaches the model.

## 11. The development probe

`fake_chat_script(bridge_calls=n)` probes with `bridge_interference(component_ids=[],
configuration="probe", settings=<all five stated>)` instead of `bridge_measure` on made-up
references, so `--fail-bridge` still reaches the bridge now that the measure tool wants ids.
