# Data Model: Checks-First Review and the Token Budget

**Feature**: `008-checks-first-review` | **Date**: 2026-09-23 | **Spec**: [spec.md](spec.md)

No IR schema change: the interference rows the pre-run persists use the `interferences` and
`gaps` arrays `ir.schema.json` already has. The review-session contract gains three optional
properties and no required one: `folded_families` and `model_view` on `ReviewSession`, and
`result_bytes`/`result_tokens` on `InvestigationStep` (research R2.48). No event type is added;
`chat-events.schema.json` does not move. The replay's report, the check digest, the stub and the
stored result are new shapes outside the session; each is normative in `contracts/`.

---

## 1. The recording (`benchmark/recording.py`, read-only)

`read_recording(run_dir) -> Recording`, or `RecordingRefused` carrying one sentence
(`contracts/replay.md` section 2).

### `Recording`

| Field | Type | Rules |
|---|---|---|
| `run_dir` | Path | |
| `session` | ReviewSession | Loaded through `run_folder_session`, so a missing session and a benchmark root are refused with its own sentences |
| `package_path` | Path | `run_dir/package.json`; refused when absent |
| `provider` | str | From the session's provider record; `gemini` makes the comparison a shape comparison |
| `turns` | list[RecordedTurn] | In recorded order |
| `findings` | list[RecordedFinding] | Every session finding with the step that produced it |
| `setup_steps` | list[int] | Steps written before the first `usage` event (a recorded pre-run); never scripted |

### `RecordedTurn`

| Field | Type | Rules |
|---|---|---|
| `index` | int | 0-based |
| `kind` | `Literal["opening", "follow_up", "answer"]` | `answer` when `evidence.answered` events precede it |
| `answers` | list[tuple[str, str]] | `(request_id, answer)` from the `evidence.answered` events before the turn; several are one batch (research R2.42) |
| `rounds` | list[RecordedRound] | |
| `end_reason` | str | From `turn.ended`; `stopped` turns drop their dangling call |
| `user_tokens` | int \| None | *Landed as* (T016): a later turn's engineer message sized from the recorded growth (first input minus the previous committed turn's last main round and its output); `None` for the opening turn and when the previous round asked for calls |

`Recording.growth_after(round)` (*landed as*, T016) is the next main round's input minus this
round's input and output, or `None` when not observable (the last main round of a turn, a
presentation round, a negative difference); the replay's estimation and the fixture generator
both read it.

### `RecordedRound`

| Field | Type | Rules |
|---|---|---|
| `turn`, `index` | int | `index` counts main rounds in the turn |
| `kind` | `Literal["main", "presentation"]` | `presentation` for a `usage` after the turn's `text.done` |
| `usage` | TokenUsage | As recorded |
| `calls` | list[RecordedCall] | The `tool.started` events after this round's `usage` and before the next |

### `RecordedCall`

| Field | Type | Rules |
|---|---|---|
| `step` | int | The session step index |
| `tool` | str | |
| `arguments` | dict | As the model sent them |
| `status` | `Literal["ok", "error"]` | From `tool.finished` |
| `summary` | str | The recorded 200-character `result_summary` |

`RecordedFinding = (finding: Finding, step: int | None)`, the step being the
`tool.started`/`tool.finished` bracket the `finding` event falls in.

## 2. The replay report (`benchmark/replay.py`, pydantic)

`contracts/replay.md` section 5 is normative; this is the model.

| Field | Type | Rules |
|---|---|---|
| `run_dir` | str | |
| `provider` | str | |
| `tokenizer` | str | `o200k_base` |
| `comparison` | `Literal["exact", "shape"]` | `shape` for a Gemini recording |
| `framing_tokens` | int | 12 |
| `settings` | `{as_recorded, requested}` | Each `{efficiency, model_view}` |
| `rounds` | list[ReplayRound] | |
| `totals` | ReplayTotals | |
| `regrouped` | Regrouped \| None | From User Story 4; None when neither rule applies |
| `findings` | ReplayFindings | |

`ReplayRound`: `turn`, `round`, `kind`, `recorded_input`, `as_recorded_input`,
`requested_input`, `estimated: bool`, `lower_bound: bool`, `calls: [{step, tool, class, reason}]`,
where `class` is one of `reproduced`, `changed`, `estimated`, `carried`, `answered_from_checks`
(User Story 2), `stored` (User Story 3), and `reason` is a sentence for every class but
`reproduced`.

`ReplayTotals`: `recorded`, `as_recorded`, `requested`, `difference` (`requested - recorded`),
`estimated_rounds`, `lower_bound_rounds`, `carried_rounds`.

`Regrouped`: `assumption` (the sentence of research R2.43), `rules` (subset of `["R", "M"]`),
`rounds`, `total`.

`ReplayFindings`: `recorded: int`, `replayed: int`, `lost: [{check, subject}]`,
`added: [{check, subject}]`, `not_replayable: [{check, subject, step, reason}]`,
`reclassified: [{check, subject, step, group_key, contact_id}]` (feature 010 T094: a recorded
`interference.static` whose group key and configuration equal a contact the requested pass
recorded; neither lost nor not replayable),
`narrowed: [{check, subject, step, removed_locations}]` (owner decision 23A, 2026-09-25: a
recorded `rms.*` finding whose key, less the drawing locations that name only rows the current
type table does not count as content, equals a requested-pass finding nothing else matched, one
to one; neither lost nor added; `contracts/replay.md` section 5). `subject` is the printable form
of `finding_subject_key` minus the check (since owner decision 25A, each location with its
`persist_ref`, `contracts/replay.md` section 7).

## 3. The scripted provider (`agent/providers/fake.py`, test-facing)

| Type | Change |
|---|---|
| `ScriptedRound` | NEW frozen dataclass: `calls: tuple[ScriptedToolCall, ...]`, `usage: TokenUsage \| None = None` |
| `ScriptedTurn.rounds` | NEW optional `tuple[ScriptedRound, ...] = ()`. With rounds set: one assistant message per round holding its calls, then its tool messages; one `usage` event per round (`round_index` 0..n) when the round has usage; the closing text uses `turn.usage`. `tool_calls` and `rounds` both set raises `ValueError` |

## 4. Finding identity (`findings.py`)

| Name | Definition |
|---|---|
| `ENTITY_ID` | `re.compile(r"^[a-z]{3,4}:[0-9]{4,}$")` |
| `finding_subject_key(finding)` | `(check, tuple(sorted(component_ids)), tuple(sorted((document_id, sheet, view, annotation, page, persist_ref) for each drawing location)), tuple(sorted(s for s in inputs if ENTITY_ID.match(s))), configuration)`, sorted with `None` last; ignores `id`, `tool_result_ids` and `capture_ids`. *Amended 2026-09-25 (owner decision 25A, T128):* each location keeps its `persist_ref` (`None` where it has none), which the key ignored before; compared only between a recording and its replay or its fixture, never across two dumps (research R2.8) |

## 5. The tokenizer (`tokens.py`)

| Name | Value |
|---|---|
| `TOKENIZER_NAME` | `"o200k_base"` |
| `VOCABULARY_FILE_NAME` | `"fb374d419588a4632f3f557e76b4b70aebbca790"` (tiktoken's cache key for the encoding's URL) |
| `tokenizer_dir()` | the per-user cache (`SWREVIEW_TOKENIZER_DIR`, else `%LOCALAPPDATA%\SwReview\tokenizer` on Windows, else the XDG or `~/.cache` folder); the file is 3,613,922 bytes and is never in the repository (`contracts/tokenizer.md`, amended 2026-09-23) |
| `ENCODING_SHA256` | the `expected_hash` tiktoken itself carries for `o200k_base` |
| `count_tokens(text) -> int` | `len(encoding.encode(text, disallowed_special=()))`; the encoding loaded once |
| `TokenizerUnavailable` | `RuntimeError`; one sentence naming the folder, the expected hash and `swreview tokenizer fetch` |

## 6. Settings (`agent/settings.py`)

| Name | Story | Definition |
|---|---|---|
| `checks_first(efficiency) -> bool` | US2 | `efficiency is not None and (efficiency.prerun_checks or efficiency.procedural_gate)` |
| `pane_efficiency(provider) -> EfficiencySettings` | US2, US4 | `EfficiencySettings(prerun_checks=True, parallel_tool_calls=provider is ProviderName.OPENAI)`; US2 lands the first field, US4 the second |
| `ModelViewSettings` | US3 | frozen, `extra="forbid"`: `payload_slimming: bool`, `history_pruning: bool` (no defaults), `prune_after_rounds: int = Field(2, ge=1)` |
| `MODEL_VIEW_OFF` | US3 | `ModelViewSettings(payload_slimming=False, history_pruning=False)` |
| `MODEL_VIEW_PANE` | US3 | `ModelViewSettings(payload_slimming=True, history_pruning=True)` |
| `PaneDefaults` | US3 | frozen dataclass `(efficiency: EfficiencySettings, model_view: ModelViewSettings)` |
| `pane_defaults(provider) -> PaneDefaults` | US3 | `PaneDefaults(pane_efficiency(provider), MODEL_VIEW_PANE)`; read by the pane, `swreview review --pane-defaults` and the replay |

`EfficiencySettings` keeps its twelve fields and their off defaults; `prerun_checks`'s docstring
names it checks first. `LEVER_NAMES` and `GATED_ALONE` do not change.

*Amendment 2026-09-23 (FR-030, research R2.53):* one field is appended, so there are thirteen.

| Name | Definition |
|---|---|
| `EfficiencySettings.withhold_prerun_tools: bool = False` | Lever 13: the tools checks first ran to completion leave the array (`contracts/checks-first.md` section 7). Optional in `review-session.schema.json` and not in `required`; `ReviewSession`'s serializer writes it only when on, so every older session keeps its bytes and loads with it off (*landed as*, T108) |
| `pane_efficiency(provider)` | also sets `withhold_prerun_tools=True`, for every provider |
| `efficiency_from_levers` | refuses `withhold_prerun_tools` without `prerun_checks` or `procedural_gate`; `GATED_ALONE` does not change |

## 7. The session (`report/session.py`, contract in lockstep)

| Model | Field | Story | Rules |
|---|---|---|---|
| `ReviewSession` | `folded_families: list[str] = []` | US2 | `["rms"]` when checks first ran; omitted from `session.json` when empty |
| `ReviewSession` | `model_view: ModelViewSettings \| None = None` | US3 | Always written by `start_review` (off when not given); absent on older sessions, which means off |
| `InvestigationStep` | `result_bytes: int \| None = None` | US5 | `ge=0`; bytes of `tool_result_text(payload)` in UTF-8; omitted when null |
| `InvestigationStep` | `result_tokens: int \| None = None` | US5 | `ge=0`; `count_tokens` of the same text; null when the tokenizer failed; omitted when null |

## 8. The tool layer

| Type | Field | Story | Rules |
|---|---|---|---|
| `ToolCallResult` (`agent/providers/__init__.py`) | `view: dict \| None = None` | US3 | What the model reads, set at `RecordedTool._finish` with slimming on; `payload` stays the tool's return |
| `model_payload(result)` | function | US3 | `result.view if result.view is not None else result.payload`; the only content the adapters put into history |
| `tool_result_text(payload, *, compact=False)` | function | Setup, US3 | `json.dumps(payload)`; `separators=(",", ":")` when compact |
| `ModelViewAware` | Protocol | US3 | `use_model_view(settings: ModelViewSettings) -> None`; OpenAI and Gemini implement it |
| `ToolCallRecord` (`tools/registry.py`) | `payload: Mapping \| None = None` (`compare=False`) | US3 | Handed to `SessionSink.record` for the stored result |
| `ToolCallRecord` | `result_bytes`, `result_tokens: int \| None = None` | US5 | Measured in `record_call` |
| `ToolContext` (`tools/context.py`) | `tool_results_dir: Path \| None = None` | US3 | Set only by `start_review` to `out/"tool-results"` |
| `PrerunCall` (`prerun.py`) | `payload: Mapping \| None = None` | US2 | The pre-run call's payload, for the guard's answer; defaulted so direct constructors stay valid |
| `PrerunResult` | `live: LiveOutcome \| None = None` | US2 | |
| `PrerunResult` | `withheld: tuple[str, ...] = ()` | Amendment 2026-09-23 | The tools lever 13 took off the array, in pre-run order; empty with the flag off. Not recorded on the session: the setting is, and the rule re-derives the set from the pre-run's steps |
| `LiveOutcome` | NEW frozen dataclass | US2 | `step_index`, `configuration`, `settings`, `groups`, `rows_detected`, `rows_added`, `rows_collided`, `error: str \| None`, `persist_error: str \| None` |
| `PrerunGuard` | NEW `ToolSet` wrapper | US2 | Ledger `repeat_key -> (step_index, outcome)`; `contracts/checks-first.md` section 5 |

## 9. The check digest (`tools/model_view.py`)

`check_digest(payload, *, counts_only=False) -> dict` over a check tool's payload (an envelope
with `findings`, or one `finding`). `count_findings(rows: Iterable[tuple[str, str, str]]) ->
FindingCounts` over `(check, status, severity)` triples.

| Field | Type | Rules |
|---|---|---|
| `status` | str | The payload's own status |
| `findings` | int | |
| `rules` | int | Distinct check ids |
| `by_status`, `by_severity` | dict[str, int] | Keys sorted |
| `rows` | list[{id, check, status, severity, title}] | At most `ROW_CAP = 25`, in payload order; absent when `counts_only` |
| `rows_omitted` | int | Absent when `counts_only` |
| `finding_ids` | list[str] | At most `ID_CAP = 200`; absent when `counts_only` |
| `finding_ids_omitted` | int | Absent when `counts_only` |
| `subjects` | int | Sum of the payload's `subjects` map when present, else distinct component ids |
| `coverage` | dict[str, int] \| int | Bucket counts, or the integer as given |
| other top-level scalars | as given | e.g. `group_key`, `configuration`, `members` |
| `detail` | str | Added by `MODEL_VIEWS` only (US3): "get_finding(finding_id) returns one finding in full" |

A payload with neither `findings` nor `finding` (an error, `out_of_scope`) passes through
unchanged (and stripped, in the view).

## 10. The grouped gaps (`tools/model_view.grouped_gaps`, US3)

`{groups: [{kind, entity_kind, reason, rows, entity_ids, entity_ids_omitted}], rows}`; key
`(kind, entity_kind, reason with each single-quoted substring replaced by "…")`; `reason` is the
first row's full text; `entity_ids` the first five (a `None` entity id counted, not listed);
groups in first-appearance order; an empty list gives `{groups: [], rows: 0}`.

## 11. The result stub (`agent/providers/pruning.result_stub`, US3)

| Field | Rules |
|---|---|
| `pruned` | `"shown in full earlier; summarised here"` |
| `tool` | |
| `arguments` | As the model sent them |
| `counts` | `{key: len(value)}` for each top-level list of the content the model read |
| `ids` | The `id` of every object in those lists, then `finding_ids` when present; at most 20 |
| `ids_omitted` | int |
| `refetch` | `"call <tool> again with these arguments to read it in full"`, plus `" or get_finding(<id>) for one finding"` when the content carries finding ids; for a tool the adapter does not offer (`prune_history(..., offered=...)`, amendment 2026-09-23) `"<tool> is not offered this session, so it cannot be called again"`, plus `"; get_finding(<id>) reads one finding"` |

Deterministic in `(name, arguments, content)`: identical bytes on every call and across processes.

## 12. The stored tool result (`<out>/tool-results/step-<index>.json`, US3)

| Field | Rules |
|---|---|
| `session_id` | The session that recorded the step; a file naming another session is stale |
| `step` | The `InvestigationStep.index` |
| `tool`, `arguments` | As recorded |
| `status` | `ok` or `error`, as on the step |
| `payload` | The tool's full return, never the view |

`indent=2`, `ensure_ascii=False`, trailing newline. Written for every recorded step of a review,
before the adapter's next request. A pane retry rotates the folder to `tool-results.<n>` beside
`session.<n>.json`.

## 13. The folded rule group (`report/attention.py`, US2)

| Type | Change |
|---|---|
| `FAMILY_TITLES` | `{"rms": "Modelling practice"}` |
| `family_of(check, families) -> str \| None` | The folded family a check id belongs to (`rms.` prefix for `rms`), or None |
| `AttentionRow.family` | `str \| None = None`; omitted when None |
| `AttentionRow.rule_count` | `int \| None = None`; omitted when None |
| the family row | `check = "rms"`, `title = "Modelling practice: N findings across M rules"`, `member_finding_ids` = every family finding id sorted, representative = the member whose own key sorts first, `component_ids` = the union |

The report renders `### Modelling practice: N findings across M rules` then
`<details><summary>…counts by rule…</summary>` holding every family finding as the severity
sections render it, then `</details>`, after the severity sections; those findings are left out of
the severity sections.

## 14. The answer batch (`agent/runner.py`, `chat/server.py`, US4)

| Name | Definition |
|---|---|
| `ReviewRun.answer_evidence_batch(answers: Sequence[tuple[str, str]]) -> ReviewSession` | Validates every id, then marks each answered with one `evidence.answered` event in submission order, then one `_ask`, one `_reconcile_reruns`, one finalize |
| `answerable(session, request_id) -> EvidenceRequest` | The one validator; raises `UnknownEvidenceRequestError` or `EvidenceAlreadyAnsweredError` (`ValueError` subclasses, today's messages) |
| `ANSWERS_MESSAGE` | The resumed turn's user message for two or more answers, one `- <request_id>: <answer>` line each; one answer sends `ANSWER_MESSAGE` byte for byte |
| `POST /sessions/{chat_id}/evidence` body | `{answers: [{request_id: str, answer: str}]}`, non-empty, no repeated id |

## 15. The pane usage line (`render.js` `usageLine`, US5)

Reads only `input_tokens`, `cached_input_tokens`, `total_tokens` and `latency_s` from the usage
events. `U = sum(input) - sum(cached)` when every round reported both and `sum(cached) <=
sum(input)`; otherwise the split is "not reported". No percentage.

## 16. Relationships

```
recorded run folder ──read_recording──▶ Recording ──replay (pass A: as recorded, pass B: requested)──▶ ReplayReport
                                                        │  start_review + FakeProvider rounds in a temporary folder
                                                        │  prune_history + tool_result_text + count_tokens (the adapters' own functions)
                                                        └─ finding_subject_key multisets ─▶ lost / added / not replayable

start_review ──pane_defaults(provider)──▶ efficiency (checks first, parallel) + model_view (slimming, pruning)
   ├─ prerun_checks: bridge_interference (live) ─▶ append_interference_run ─▶ <out>/package.json
   │                 check_rms_* , check_interference_group × groups, check_standards ─▶ steps, findings, coverage
   │                 ─▶ opening digest (counts; folded family as one line) ─▶ first user message
   ├─ PrerunGuard(dispatch) ─▶ a repeat answers {already_run, outcome: check_digest(payload)}
   └─ session.folded_families = ["rms"] ─▶ rank() one family row ─▶ report subsection, attention.json

RecordedTool._finish ─▶ ToolCallResult(payload, view=model_view(name, payload)) ─▶ history content = model_payload
record_call ─▶ ToolCallRecord(payload, result_bytes, result_tokens) ─▶ SessionSink.record ─▶ InvestigationStep + tool-results/step-<n>.json
adapter request ◀── _encode_history(prune_history(history, N), compact) ◀── the neutral history (append-only)
```
