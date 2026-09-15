# Data Model: Resilient Modeling Checks

**Feature**: `003-resilient-modeling` | **Date**: 2026-09-15 (revision 3) | **Spec**: [spec.md](spec.md)

Extends the feature 001 IR to `schema_version` 1.1.0 (minor: two new optional arrays, one
new optional object, one new optional field on `ComponentInstance`, new gap entity kinds).
Conventions from feature 001 apply: lengths are `Quantity` with unit, persistent refs are
base64 with a scope, absence is `null` plus a `Gap`. The feature 001 review-session schema
(`Finding`, `CoverageItem`) is not changed.

## 1. IR additions (schema 1.1.0)

### `Feature` (`EvidencePackage.features[]`, default empty)

| Field | Type | Rules |
|-------|------|-------|
| `id` | `feat:NNNN` | Allocated in traversal order across the package; stable within the package only. |
| `persist_ref`, `persist_ref_scope` | | Scope is the owning part document. |
| `document_id` | str | The part document that owns the tree. |
| `configuration` | str | The configuration the tree was read in (the document's active configuration as loaded). |
| `name` | str | `IFeature.Name`. |
| `type_name` | str | `GetTypeName2` verbatim; may be a name the tables do not know. |
| `description` | str \| null | `IFeature.Description`; null when unreadable (gap), empty string when blank. |
| `index` | int | Flat order within the document's tree (folders and their contents inline). |
| `depth` | int | 0 top level, 1 inside a folder, 2 inside a nested folder; from sub-feature structure only. |
| `folder_id` | str \| null | `id` of the nearest enclosing feature reached through sub-feature traversal. |
| `suppressed` | bool \| null | In `configuration`; null when unreadable. |
| `error_code` | int \| null | `GetErrorCode2`; null when unreadable. |
| `child_ids` | list[str] \| null | Dependents from `GetChildren`; null when unavailable (gap). |
| `parent_ids` | list[str] \| null | Dependencies from `GetParents`; null when unavailable (gap). |
| `sketch` | `SketchInfo \| null` | Present only for features `GetSpecificFeature2` returns an `ISketch` for. |
| `fillet` | `FilletInfo \| null` | Present only for features whose definition is a simple fillet. |

The extractor decides nothing about folders, end-tags, groups, or classes: `is_folder`,
`is_end_tag`, `group`, `subfolder`, and `class` are Python-derived (section 2).

`SketchInfo`: `raw_status: int | null` (`ISketch.GetConstrainedStatus` verbatim; null plus a
`sketch_status` gap on failure), `consumer_ids: list[str] | null` (the sketch's dependents
from `GetChildren`; null plus a `feature_children` gap when unavailable).

`FilletInfo`: `default_radius: Quantity | null` (`ISimpleFilletFeatureData2.DefaultRadius`
in meters; null plus a `fillet_radius` gap when unreadable or when the fillet is variable).

### `Equation` (`EvidencePackage.equations[]`, default empty)

| Field | Type | Rules |
|-------|------|-------|
| `document_id` | str | |
| `index` | int | Position in the equation manager. |
| `text` | str | Full equation text as read. |
| `lhs` | str | Left of the first `=`, quotes stripped; evidence only. |
| `is_global` | bool \| null | `IEquationMgr.GlobalVariable(i)`; null plus an `equations` gap when unreadable. |
| `value` | float \| null | `Value(i)`; null when unreadable. |

### `SuppressTestRun` (`EvidencePackage.rms_suppress_test`, default null)

Written only by the `suppress-test` console command through `PackageAppender`; a later
`dump` overwrites the package and drops it, exactly as interference results are dropped.

| Field | Type | Rules |
|-------|------|-------|
| `document_id` | str | From the plan. |
| `configuration` | str | From the plan; the command refuses when the active configuration differs. |
| `group` | str | The Detail group name from the plan. |
| `plan_file` | str | Path of the plan consumed. |
| `run_at` | ISO 8601 | |
| `acknowledged` | bool | Always true; the command refuses otherwise. |
| `baseline_whats_wrong_count` | int | Read before the first suppression; the command refuses when non-zero, so this is 0 in every written run and is recorded for audit. |
| `limit` | int | `--limit` in effect. |
| `timeout_seconds` | int | `--timeout-seconds` in effect. |
| `features_present` | int | Planned features (`len(plan.features)`). |
| `restore_verified` | bool | The post-run tree matched the pre-run snapshot. |
| `unrestored_feature_ids` | list[str] | Empty when `restore_verified`. |
| `rows` | list[`SuppressTestRow`] | One per planned feature, in plan order (`len(rows) == features_present`; untested ones are `truncated`). |

`SuppressTestRow`: `feature_id`, `persist_ref`, `persist_ref_scope`, `name`, `outcome:
"ok" | "rebuild_errors" | "already_suppressed" | "not_applied" | "truncated" | "aborted"`,
`whats_wrong_count: int | null`, `messages: list[str]` (at most 20), `messages_truncated:
int` (count dropped), `error: str | null`, `elapsed_ms: int | null`.

### `ComponentInstance.constrained_status_raw` (new, `int | null`, default null)

`IComponent2.GetConstrainedStatus` verbatim, carried through `ComponentNode` in the dump
contracts; null plus a `component_constrained_status` gap when unreadable. Mapped in Python
through the same `constrained_status` table as sketches.

### `Mate.suppressed` (existing field, now read)

`MateDumper` reads the mate feature's `IsSuppressed2` into the existing `suppressed` field
instead of writing `false` unconditionally; a failed read is `false` plus a `mate_suppression`
gap, and the chain-depth rule reports the mate unresolved.

### Gap `entity_kind` values added

`feature_tree_unavailable` (component lightweight, suppressed, or unloaded; reason names the
state; `entity_id` the component), `feature_tree_configuration` (the document is also used
under other configurations; reason lists them), `feature_children`, `feature_parents`,
`sketch_status`, `feature_description`, `fillet_radius`, `equations`,
`component_constrained_status`, `mate_suppression`. Each names one `entity_id`. Unknown type
names are not IR gaps (the extractor does not classify); see section 2.

## 2. Python derived types

| Type | Fields | Rules |
|------|--------|-------|
| `RmsTypeTable` | `groups`, `folder_type`, `end_tag_suffix`, disjoint class sets, `ambiguous`, `tolerated_loose`, `default_names_excluded`, `constrained_status`, `assembly`, `calibrated_version` | Loaded from `checks/rms_types.yaml`. `classify(type_name) -> FeatureClass \| "unknown" \| "ambiguous"` returns exactly one value; a rule needing a union names the classes. `is_folder(feature)`, `is_end_tag(feature)`, `is_content(feature)` (not folder, not end-tag, not an excluded default name, not tolerated; `unknown` class is content). `constrained_status(raw: int \| null) -> "unknown" \| "under_defined" \| "fully_defined" \| "over_defined" \| "solver_error" \| "unavailable"` (null → unavailable, unlisted → unknown, 7 → unknown). |
| `GroupAssignment` | `by_feature_id: dict[str, str \| null]`, `subfolder_by_feature_id: dict[str, str \| null]`, `groups_seen: list[(group, feature_id)]`, `duplicates: list[(group, feature_id)]`, `order_ok: bool` | Sticky semantics and derived subfolders per `contracts/rules.md`; supports the nested and the flat traversal shapes. |
| `RuleResult` | `rule_id`, `document_id`, `outcome: "pass" \| "fail" \| "warn" \| "skip" \| "unresolved" \| "waived"`, `subjects: list[str]` (feature, mate, or component ids sharing this outcome), `result: CheckResult \| null` (present for fail, warn, waived; `check` = rule id, `requirement` = statement), `reason: str \| null` (skip, unresolved, waived; joins the per-subject reasons with `; `) | One per rule per subject document per outcome reached; a rule's evaluator returns `list[RuleResult]`. |
| `RmsRule` | `id`, `scope: "part" \| "assembly" \| "equations" \| "drawing" \| "advisory"`, `severity: "fail" \| "warn" \| null`, `statement`, `fn: callable \| null`, `coverage: ("unresolved" \| "out_of_scope", reason) \| null` | Registry. Invariant: `fn` is present exactly when `severity` is present exactly when `coverage` is null. Rules with `coverage` are never dispatched and are emitted once per review as coverage items. |
| `SuppressPlan` | `document_id`, `configuration`, `group`, `features: list[{feature_id, persist_ref, persist_ref_scope, name, type_name}]` | Written by `swreview rms suppress-plan` from the group assigner and the type table; consumed by the C# command. |
| `MateGraph` | nodes = every component instance, edges = unsuppressed root mates (a mate's entities name the instances it joins); `root` (first fixed child of `cmp:0001`), `other_fixed`, `depth_from(root)`, `unreachable`, `unresolved_mates` (suppression gap) | For chain depth. |

### Severity, outcome, and finding mapping (FR-007)

| Outcome | Result |
|---|---|
| `fail` | `Finding` status `demonstrated`, severity `medium` (`high` for `rms.refs.*` and `rms.sketches.not_over_defined`) |
| `warn` | `Finding` status `suspected`, severity `low` |
| `waived` | `Finding` status `checked_within_scope`, `coverage_limits` includes `exception:<id>: <note>`, `exception_id` set |
| `pass` | aggregated `CoverageItem` in `checked` |
| `skip` | aggregated `CoverageItem` in `skipped` |
| `unresolved` | aggregated `CoverageItem` in `unresolved` |

### Subjects to Finding fields (no change to the feature 001 finding contract)

1. `Finding.component_ids` = the ids of every `ComponentInstance` whose `document_id` equals
   `RuleResult.document_id`, in package order (the root assembly's own instance is
   `cmp:0001`). Ids are never invented: a document with no instance in the package yields an
   unresolved coverage item with reason `no component instance for <document_id>` instead of
   a finding.
2. Feature, mate, and component subjects are strings in `Finding.inputs`, one per subject,
   formatted `<id> <name> [<type_name>] persist_ref=<ref> scope=<document_id>`, and are named
   in `observed`.
3. `demonstrated` and `checked_within_scope` need a `Calculation` or a `tool_result_ids`
   entry. Today `tools/recording.py` passes neither and the other check tools supply a
   `Calculation`; this feature adds a `tool_result_ids` argument to `result_to_finding` and
   `record_results`, and a `ToolContext.current_step_id` property (the index the recording
   step will take), and the RMS report layer passes it with `calculation` none.
4. A finding naming a suppressed feature carries `suppressed in <configuration>` in
   `observed` and in `coverage_limits`; a finding on a document with a
   `feature_tree_configuration` gap carries `other configurations not read: <names>` in
   `coverage_limits`.

### Coverage aggregation (FR-012)

Per review, one `CoverageItem` per rule per bucket: `check` = rule id, `scope.document_ids`
= the documents in that bucket, `scope.configuration` = the review configuration, `reason`
= `<n> document(s)` followed by the per-document reasons for skip and unresolved
(`doc:3: no shell; doc:5: children unavailable`). Items are written through the new
`ToolContext.replace_coverage(check, bucket, item)`, which removes the session's items with
that check in that bucket and appends the new one through the existing coverage event, so a
tool that runs twice replaces rather than duplicates. Plus:

- one `modeling.resilience` item: in `checked` when no rule was unresolved for any document,
  otherwise in `unresolved` with the count; its reason names the counts per bucket;
- one `rms.types.unknown` item in `unresolved` when any type name was unknown, reason listing
  `<type_name> x<count>` and the documents; absent otherwise;
- the six out-of-scope rules in `out_of_scope` and the four data-gap rules in `unresolved`
  (`rms.assembly.subassemblies` with `scope.document_ids` = the subassembly documents),
  written by the first `check_rms_*` call of the session and skipped by later calls when the
  session already holds them.

### Unresolved part documents

A part document with no `features[]` rows and no resolved instance (section "Unresolved
part documents" in `contracts/rules.md`) appears in every part-scope and equation-scope
rule's unresolved item with reason `component <full_path> <suppression>; tree not read` and
counts toward the `modeling.resilience` summary.

## 3. Exceptions (waivers)

`ReviewException` gains `fingerprint_kind: Literal["geometry", "feature_tree"] = "geometry"`.
Existing `exceptions.json` files load unchanged. For `rms.*` checks:

- `accept` binds to the component instances of the part document, the review configuration,
  and a `feature_tree` fingerprint: a hash over the document's `features[]` rows in order
  (`index`, `type_name`, `name`, `depth`, `folder_id`, `suppressed`, description present or
  not, `sketch.raw_status`, `len(sketch.consumer_ids)`, `fillet.default_radius`, `child_ids`)
  and its `equations[]` (`lhs`, `is_global`), so every input a rule reads is covered and a
  fixed violation elsewhere re-opens the exception; the description text itself is excluded.
- `ExceptionStore.match(package, component_ids, configuration, check)`: `check` becomes a
  required argument for every caller (the two interference call sites pass
  `interference.CHECK`), so an RMS exception can never be returned for an interference query
  that happens to share bindings, and several RMS rules on one document resolve correctly.
- `refresh` recomputes by `fingerprint_kind`; a changed fingerprint moves the exception to
  `needs_review`, and the finding then stands with `needs re-review: <id>` in its observed
  text (mirroring the interference check).
- Only `fail`-severity rules are acceptable through the import; `warn` outcomes are never
  matched against exceptions.

The checker's flat file `{ "<rule_id>": "<reason>" }` is an import input for
`swreview exceptions accept-rms <run_dir> --package <dir> --file <path>`: every
`demonstrated` finding of the run whose `check` is a listed `fail` rule is accepted with the
reason as note. Per rule id the command reports one of four statuses: `accepted <n>`,
`would accept <n>` (a matching `fail` rule on a run that exits 1 because another id is
invalid, so nothing was written), `unused` (no such finding), `invalid (warn rule)`,
`invalid (unknown rule)`. Any invalid id makes the command exit 1 and write nothing.

## 4. Relationships

```text
Document 1..* Feature ; Feature 0..1 enclosing Feature (folder_id) ; Feature 0..* child Feature
Document 0..* Equation ; EvidencePackage 0..1 SuppressTestRun ; SuppressTestRun 1..* SuppressTestRow -> Feature
SuppressPlan 1 per (Document, run) -> Feature* ; GroupAssignment 1 per Document (derived)
RuleResult * per Document per Rule (one per outcome reached)
ReviewException(feature_tree) -> (ComponentInstances of a Document, Rule, configuration)
MateGraph 1 per root assembly Document (derived from Mate and ComponentInstance)
```

## 5. State

Rule results are computed fresh each review; nothing is persisted except through findings
and coverage in `session.json` and exceptions in `exceptions.json`. The suppress-test run
lives in `package.json` from the command that appended it until the next `dump`; the plan
file is an input the engineer may delete after the run.
