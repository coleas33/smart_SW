# Data Model: Engineer-First Review

**Feature**: `013-engineer-first-review` | **Date**: 2026-09-26 | **Plan**: [plan.md](plan.md)

Every new field is optional and additive (FR-053): sessions, packages and events written before this
feature load and round-trip to their own bytes. Values below are fictional.

## 1. The standards profile, version 4

`checks/standards/profile.py`. `PROFILE_VERSION = 4`, `KNOWN_VERSIONS = (1, 2, 3, 4)`,
`VERSION_4_SECTIONS = ("part_roles",)`, `SECTIONS_BY_VERSION[4] = v3 + ("part_roles",)`.

**PartRolesSection** (frozen, `extra="forbid"`)

| Field | Type | Validation |
|---|---|---|
| `bought_prefixes` | `list[str]` | no blank entry (by position); library prefix semantics |
| `purchased_property` | `str` | may be empty; non-empty requires `purchased_values` |
| `purchased_values` | `list[str]` | no blank entry; no value twice ignoring case; non-empty requires `purchased_property` |
| `bought_name_patterns` | `list[str]` | no blank entry; not made only of `*`, `?` and `@` |

`StandardsProfile.part_roles: PartRolesSection | None` - required at version 4, refused at 1 to 3.
Contract: `contracts/part-roles-profile.md`.

**Shared matchers** (`checks/standards/library.py`, `traversal.py`): `PrefixList.from_entries(entries,
root)` with `.matches(path)` and `.longest(path)`; `PrefixMatcher` holds four of them (no behaviour
change). `name_matches(pattern, file_name, *, wildcards: bool) -> bool`; `part_number_matches` calls it
with `wildcards=False`.

## 2. Part roles

`checks/part_roles.py`. Contract: `contracts/part-roles.md`.

| Entity | Fields |
|---|---|
| `Role` | `"custom" \| "bought" \| "unclear"` |
| `State` | `"configured" \| "convention_only" \| "absent"` |
| `PartRole` | `document_id`, `role`, `rule` (`"A"`..`"J"`), `reason` (words, no profile value), `graded: bool`, `label: str \| None` |
| `PartRoles` | `state`, `state_reason: str \| None`, `by_document: Mapping[str, PartRole]`, `guard_fired: bool`; `graded(id)` (True for an unknown id), `bought()`, `unclear()`, `note_for(id)` |
| `RolesQuestionSpec` | the `QuestionSpec` of `part-roles.md` section 8 (`checks/questions.py`) |

State transitions of one document within a session: `unclear` → `custom` or `bought` by the answer
(rule A); no other transition. In a live review the roles are computed at `start_review` from the
package, the profile and any answered request, and again after an answer; nothing about them is
stored except the question, its answer and the coverage rows of `contracts/part-roles.md` section 7,
which every reader outside a live review (the disk route, the re-render) reads instead of
classifying again.

**Invariants**: the root's `graded` is true; `graded` is false exactly for bought documents other than
the root; no reason contains a profile value (a test scans every reason against the profile's
distinctive values).

## 3. Session records (`report/session.py`, `findings.py`)

| Record | New field | Type | Omitted from the dump when |
|---|---|---|---|
| `EvidenceRequest` | `allow_text` | `bool = False` | false |
| `EvidenceRequest` | `source` | `"code" \| "model" = "model"` | `model` |
| `Finding` | `source` | `"code" \| "model" = "code"` | `code` |
| `CoverageItem` | `source` | `"code" \| "model" = "code"` | `code` |
| `ReviewSession` | `drawing_read` | `"none" \| "open_only" \| "opens_closed" \| None = None` | `None` |

`review-session.schema.json` gains the four properties (optional, descriptions naming the omit rule
and why the defaults differ) in the same change (`test_schema_sync.py`). A tool result that echoes a
record (`mark_coverage`, `record_drawing_finding`) echoes it without `source`
(`contracts/sources.md` section 1).

**Functions**: `covering_requests(session, blocks, entity_ids) -> CoveringRequests {answered:
EvidenceRequest | None, open: EvidenceRequest | None}`, over model-written requests only, never for
a question with no checklist item and no ids (`contracts/re-ask-guard.md` section 3).

## 4. The checklist

`agent/checklist.py` `ChecklistItem.owner: Literal["model", "code"] = "model"`; `checklist_v1.yaml`
gives `owner: code` to `provenance` and `coverage.closeout`. Version stays 1.
`Checklist.open_items(review, *, owner="model")` answers the model-owned ids only when asked.

## 5. Tool results (no signature change)

| Status | Shape | Written by |
|---|---|---|
| `closed_by_code` | `{status, check, reason}`; for the drawing item also `drawings: [{document_id, state, reason}]`, `attached: [ids]` | `mark_coverage`, `request_evidence` |
| `already_answered` | `{status, evidence_request: {id, question \| what, answer, answered_at, blocks, entity_ids}, note}` | `request_evidence` |
| `already_asked` | the same shape, the open request, its note | `request_evidence` |
| `open_items` | `list[str]` on every `mark_coverage` and `request_evidence` result | both |

`check_drawings`' payload: `candidates` counts files; `states: {attached, candidate, absent,
bought}`.

## 6. The grouped view (`report/finding_groups.py`)

Contract: `contracts/grouped-list.md` section 3.

| Entity | Fields |
|---|---|
| `FindingsByType` | `version: 1`, `groups: list[TypeGroup]` (every group with a row or a goal, in order), `checked: CheckedFold \| None` |
| `TypeGroup` | `id`, `title`, `open`, `findings`, `decided`, `text`, `rows: list[GroupRow]`, `goals: list[GoalLine]` |
| `GroupRow` | `AttentionRow` + `source`, `tail_text: str \| None` ("×3"), `reach_text: str \| None` ("reaches 2 components"), `hide_card_title: bool`, `chip: str \| None` (the source word for model rows, null for code rows) - every word the page prints, built by the backend |
| `CheckedFold` | `title`, `open`, `findings`, `text`, `rows` |
| `ReviewRanking.groups` | `FindingsByType` |
| `Goal.group` | a `finding_groups` id (words file) |

`ReviewSummary` changes: `headline` counts passes as checked; `tally: {text}`; `not_reached: {titles,
text} | None`; `bought_parts: {count, names, maybe_count, maybe_names, text} | None`; removed
`SummaryGroup.by_goal`, `modelling_practice`, top-level `goals` (now in `groups`). `bought_parts`
is read from the persisted `coverage.prerun.bought_parts` and `coverage.prerun.maybe_bought` rows,
never classified again. `QuestionView`
gains `allow_text` and `source`. `Ranking.top_n` = `min(TOP_N, rows not suppressed)`.

## 7. Words (`report/review_words_v1.yaml`)

New blocks: `finding_groups`, `finding_group_other`, `finding_group_checked`, `finding_group_text`
(with `fold_tail`, `reach_one` and `reach_many` for the rows' words),
`bought_parts.heading` (the report's "Bought parts"; the part-roles reasons, sentences and question
words reach the model and are constants of `checks/part_roles.py`, `contracts/part-roles.md` section
3), `answer_basis`, `labels.source`, `questions.text_placeholder`, `not_reached`, `tally`,
`drawings.open_then_review_one`, `drawings.open_then_review_many`. Changed: `within_scope.label`
"Checked, no issue"; every goal gains `group`; the `standards` goal is new; `hygiene` loses
`standards.release`, `coverage.prerun.standards` and `standards.`. The `Words` model refuses unknown
keys, so the words file and the model land together. `errors` stays the last block.

## 8. Events (`chat-events.schema.json`)

| Event | Change |
|---|---|
| `text.done` | body gains optional `basis: str` |
| `finding.withdrawn` | new: `{finding_id: str, reason: str}` |

## 9. The drawing capability

C#: `IConfirmedDrawingSource.OpensClosedDrawings: bool`; `PingResult.DrawingRead: string` (`none`,
`open_only`, `opens_closed`); `DrawingOpenScope` exposes its switch value; the protocol's minor version
plus one. Python: `bridge/client.DrawingReadMode`, `BridgeClient.drawing_read_mode()`,
`ToolContext.drawing_read_mode()`.

`checks/drawing_context.py`: `DrawingState = "attached" | "candidate" | "absent" | "bought"`;
`DocumentDrawingState {document_id, state, reason, maybe_bought: bool}`; `CandidateFile {key,
file_name, document_ids}`. `drawings/evidence.file_key(path)` (moved from `report/summary.py`).

## 10. Efficiency

`EfficiencySettings.drop_prior_reasoning: bool = False` (lever 14, appended last); `LEVER_NAMES` gains
it; `pane_efficiency` gains it only by the adoption commit (`contracts/tokens.md` section 4).

## 11. The feature tree

`checks/feature_nodes.py`: `tree_nodes(features) -> tuple[FeatureNode, ...]`, `MergedRow`,
`CarriedRow` (moved from `remodel/nodes.py`, which re-exports them). `PartTree.content` and `rows` read
nodes, not raw rows.

## 12. Explanations

`parse_explanations(text, rows) -> ParsedExplanations {accepted: dict[str, str], rejected:
list[Rejection]}`; `Rejection {finding_id: str | None, position: int | None, rule: "unknown_id" |
"repeated_id" | "too_long" | "not_json" | "not_a_list"}`. `keep_explained(session, rows)` replaces
`fill_fallbacks`. `EXPLANATION_UNAVAILABLE` remains as a legacy constant, filtered on read.

## 13. The extractor

`DrawingDumper`: `IDrawingReader.SheetViews(document)`; a gap of entity kind `drawing_sheet_view`
(kind `not_extracted`) on a mismatch; revision tables through `TableSeen`. `ManifestBuilder.RecordGaps`: no unconditional local-modification gap and
no vault-version gap when the build reads no vault. `RemodelProbeWatchdog.Run(call, deadline,
startBound)`; `RemodelProbeContext` deadline factory. No evidence schema version change: the sheet view
is one more `DrawingView` of type 1, and a gap's `entity_kind` is a free string (`Gap.kind` keeps its
four values).
