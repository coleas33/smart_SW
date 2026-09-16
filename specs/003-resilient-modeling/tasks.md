---

description: "Task list for the Resilient Modeling checks"
---

# Tasks: Resilient Modeling Checks

**Input**: Design documents from `/specs/003-resilient-modeling/` (revision 3)

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md; features 001 and 002 complete.

**Tests**: REQUIRED. Tests precede implementation in every phase; feature 001 and 002 golden baselines must stay byte-identical, with one authorized exception: `cover-blind-tap.yml` snapshots the review checklist, so T028's `modeling.resilience` item adds exactly that block (10 lines) to it and nothing else; the feature 001 finding contract is unchanged.

**Organization**: Setup, Foundational (IR, table, groups, registry, indexer, exceptions, recording), then US1 part rules, US2 assembly rules, US3 equations, US5 exceptions and advisory coverage, US4 suppressibility test, then polish.

## Format: `[ID] [P?] [Story] Description`

## Path Conventions

- Python: `reviewer/src/swreview/`, tests in `reviewer/tests/`
- C#: `extractor/SwReview.Extractor/`, `extractor/SwReview.Extractor.Console/`, tests in `extractor/SwReview.Extractor.Tests/`

---

## Phase 1: Setup

- [x] T001 `git mv specs/003-resilient-modeling/contracts/rms-types.yaml reviewer/src/swreview/checks/rms_types.yaml` and update `contracts/README.md` to point at it as the single normative file
- [x] T002 [P] Update `NOTICE.md`: credit the Resilient Modeling Strategy (Richard Gebhard, 2013); record that rule semantics, type tables, and API notes from `LifeDay/Solidworks-Resilient-Modeling-Skill` (commit `df49e6d`, unlicensed) are reused with the author's permission granted to the project owner on 2026-09-15, no code copied; note the request for an upstream license
- [x] T003 [P] Add `reviewer/tests/support/features.py`: builders for `Feature` rows (nested and flat traversal shapes, folders, end-tags, sketches with raw status and consumers, fillets with radii, suppressed features, null children), `Equation` rows, `SuppressTestRun`, and `rms_package(parts=..., assembly=...)` on top of `tests/support/packages.py` that emits, per part document, one manifest entry and one or more `ComponentInstance`s (root `cmp:0001` for assemblies, `is_fixed`, `constrained_status_raw`, `suppression` including non-resolved instances with their `feature_tree_unavailable` gap, mates with entity kinds and `suppressed`, a subassembly document); with `tests/unit/test_support_features.py` asserting the built package validates and round-trips through the IR models
- [x] T004 [P] Add `benchmarks/native/rms-part/RECIPE.md` (two hand-built parts: A with the six groups in order and one seeded violation per part rule reachable with correct folders, listing every rule id with its seed feature; B with `5-Modify` missing and `3-Core` after `4-Detail` for `rms.folders.present` and `rms.folders.ordered`; A also carries a Detail feature whose suppression breaks a later feature and one pre-suppressed Detail feature for US4) and `benchmarks/answer_keys/rms-part.json` in the existing `AnswerKey` shape (`package_id`, `known_defects[]` with `check` = rule id, `correct_conditions[]` for the rules that must pass)

---

## Phase 2: Foundational

- [x] T005 Write `reviewer/tests/unit/test_ir_features.py`: `Feature` (no `is_folder`/`is_end_tag`), `SketchInfo` (`raw_status: int | null`, `consumer_ids: list | null`), `FilletInfo`, `Equation` (`is_global: bool | null`), `SuppressTestRun`/`SuppressTestRow` (all six outcomes, `baseline_whats_wrong_count`, `plan_file`, `group`, `messages_truncated`, `restore_verified`), `ComponentInstance.constrained_status_raw` default null, the new gap `entity_kind` values validate per data-model section 1; `schema_version` `1.1.0` loads; `1.0.0` packages without the new members still load (defaults); `2.0.0` still raises
- [x] T006 Implement the models in `reviewer/src/swreview/ir/models.py`, bump `SCHEMA_VERSION` to 1.1.0, regenerate `specs/001-agentic-design-review/contracts/ir.schema.json` via `python -m swreview.ir.schema --write` and keep `test_schema_sync` green; add the C# DTOs `extractor/SwReview.Extractor/Ir/{Feature,Equation,SuppressTestRun}.cs`, `ConstrainedStatusRaw` on `Ir/ComponentInstance.cs` and on `ComponentNode` in `Dump/DumpContracts.cs`, and the members on `EvidencePackage.cs`; extend `IrSerializerTests.cs` with a package carrying all of them validated against the contract; read `IComponent2.GetConstrainedStatus` through the gate in `Dump/ComponentTreeDumper.cs` (null plus a `component_constrained_status` gap on failure) and pin the field end to end through `PackageWriterTests`' fake `IComponentTreeSource` the way `IsFixed` and `IsToolbox` are; read the mate feature's `IsSuppressed2` into `Mate.suppressed` in `Dump/MateDumper.cs` (`false` plus a `mate_suppression` gap on failure), pinned through the same writer tests
- [x] T007 [P] Write `reviewer/tests/unit/test_rms_type_table.py`: loads the shipped YAML; class sets are pairwise disjoint; `classify` returns each class for its members, `ambiguous` for `ICE`, `unknown` for an unlisted name; `is_folder`, `is_end_tag` (folder type plus suffix; a non-folder named `X___EndTag___` is not an end-tag), `is_content` (excludes tolerated, folders, end-tags, and the four default names; an `unknown` class is content); `constrained_status` maps 1..6 per the table, 7 to `unknown`, unlisted raw values to `unknown`, null to `unavailable`; `calibrated_version`, assembly entity-kind lists and the depth limit are exposed; `unknown(<n>)` is in neither list
- [x] T008 [P] Implement `reviewer/src/swreview/checks/rms_types.py` (`RmsTypeTable`, `FeatureClass`, `load_table()` cached by resolved path, one `class_of(feature)` helper the class-dependent rules use)
- [x] T009 [P] Write `reviewer/tests/unit/test_rms_groups.py` over the T003 builder: sticky semantics per `contracts/rules.md` in both the nested and the flat shape; features before the first group have no group; end-tags never change the group and are never subjects; a nested non-group subfolder inherits the group and yields a derived subfolder id for its members in both shapes (flat: until its own end-tag); a group folder nested inside another folder opens the group; a duplicate group name re-opens the group and is recorded in `duplicates`; content after a group's end-tag stays in the group; `order_ok` false when groups are out of order
- [x] T010 [P] Implement `reviewer/src/swreview/checks/rms/groups.py` (`assign_groups(features, table) -> GroupAssignment`)
- [x] T011 [P] Write `reviewer/tests/unit/test_rms_registry.py`: exactly the 34 ids of `contracts/rules.md` are registered with the contract's scope; every evaluable rule has a severity, a non-empty statement, and a function; every data-gap and out-of-scope rule has no severity, no function, and a `(bucket, reason)` coverage entry matching the contract; the invariant of data-model section 2 holds for every rule; `by_scope` partitions them
- [x] T012 [P] Implement `reviewer/src/swreview/checks/rms/registry.py` (`RmsRule`, `RULES`, `by_scope`, `evaluable`, `coverage_only`) and `checks/rms/__init__.py`
- [x] T013 [P] Write `extractor/SwReview.Extractor.Tests/FeatureTreeIndexerTests.cs`: over fake feature sequences in both shapes (a folder with sub-features; a flat walk where the folder has no sub-features and its contents follow it) the indexer yields rows with correct `Index`, `Depth`, `FolderId`; it inspects no names and no type names (a folder named `Folder1___EndTag___` and a feature of type `FtrFolder` are treated like any other feature); ids `feat:NNNN` in traversal order
- [x] T014 [P] Implement `extractor/SwReview.Extractor/Dump/FeatureTreeIndexer.cs` (pure)
- [x] T015 [P] Write `reviewer/tests/unit/test_exceptions_feature_tree.py`: `ReviewException.fingerprint_kind` defaults to `geometry` and existing `exceptions.json` records load unchanged; `fingerprint(package, component_ids, kind="feature_tree")` hashes the document's feature rows in order over every field listed in data-model section 3 plus the equations, and ignores the description text; `accept` on an `rms.*` finding chooses `feature_tree`; `match(..., check)` is required and an `rms.*` exception with identical bindings and configuration is never returned for an `interference.static` query; two RMS exceptions with the same bindings and different checks resolve correctly; `refresh` moves a `feature_tree` exception to `needs_review` when a feature is inserted, renamed, moved, suppressed, loses its description, changes sketch status or consumer count, or when an equation changes, and leaves it `active` when only a description's text changes; geometry exceptions behave exactly as before
- [x] T016 Implement the extension in `reviewer/src/swreview/exceptions.py` and pass `check=interference.CHECK` at the two interference call sites (`checks/interference.py`, `tools/checks_interference.py`); existing `test_exceptions.py` stays green
- [x] T017 [P] Write tests in `reviewer/tests/unit/test_recording.py` and `test_tool_context.py`: `result_to_finding` and `record_results` accept `tool_result_ids` and forward them to `build_finding` (a `demonstrated` result with `calculation=None` builds when a step id is given and still fails without one); `ToolContext.current_step_id` equals the index the next recorded step takes; `ToolContext.replace_coverage(check, bucket, item)` removes the session's items with that check in that bucket, appends the new one, and emits the coverage event once; existing recording tests unchanged
- [x] T018 Implement the additions in `reviewer/src/swreview/tools/recording.py` and `tools/context.py`

**Checkpoint**: IR 1.1.0 round-trips in both languages; table, groups, registry, indexer, exceptions, recording tested.

---

## Phase 3: User Story 1 - Part Feature-Tree Findings (Priority: P1)

- [x] T019 [P] [US1] Write `reviewer/tests/unit/test_rms_part_rules.py`: one test class per part rule in `contracts/rules.md` (17 rules; `individually_suppressible` is US4) covering pass, fail/warn, every skip condition, and every unresolved condition with subjects and observed text asserted, one `RuleResult` per outcome reached, including: a part with no groups fails `grouping` listing every content feature and skips the per-group rules; an `unknown`-class feature is content for `grouping` and `every_feature_described` and unresolved for `no_solids`, `holes_last`, and `only_fillets_and_chamfers`; `ambiguous` counts as material for `no_solids` and is unresolved for `holes_last`; the sketch carve-out and the derived-subfolder coupled pair for `no_internal_references` in both shapes; a sketch with zero consumers passes `one_sketch_per_feature` and null `consumer_ids` is unresolved; `unknown` (including raw 7) and `unavailable` sketch status is unresolved and only `under_defined` fails `fully_defined`; the four Quarantine rules skip with `no Quarantine group`; duplicate group folders fail `folders.ordered`; sketches ignored by `holes_last`; end-tags excluded everywhere; suppressed features evaluated as present with the `suppressed in <configuration>` marker; a part document with no rows and no resolved instance is unresolved for every rule with the component state in the reason, while a document with one resolved and one lightweight instance evaluates normally
- [x] T020 [US1] Implement `reviewer/src/swreview/checks/rms/part.py`: one pure function per rule returning `list[RuleResult]` (one per outcome reached, wrapping `CheckResult` for fail and warn), class-dependent rules consulting `class_of`; `evaluate_part(document_id, features, table, assignment, package) -> list[RuleResult]` including the unresolved-document case
- [x] T021 [P] [US1] Write `reviewer/tests/unit/test_rms_report.py`: `RuleResult` → findings and coverage per data-model section 2: `component_ids` are every instance of the document (root instance for the assembly), a document with no instance yields an unresolved item and no finding; one `inputs` string per subject with id, name, type, persist ref, scope; `tool_result_ids` carries `current_step_id`; severities per rule; `waived` becomes `checked_within_scope` with `exception:` limit and `exception_id`; `needs_review` leaves the finding with the marker; aggregated coverage is one item per rule per bucket with `document_ids` and per-document reasons written through `replace_coverage`, so a second evaluation replaces rather than duplicates; the `modeling.resilience` summary lands in `checked` or `unresolved`; `rms.types.unknown` lists names and counts; the four data-gap items (with `rms.assembly.subassemblies` naming the subassembly documents) and six out-of-scope items are written once per session and skipped when present; the unresolved document appears in every part- and equation-scope rule's unresolved item; the `other configurations not read` limit appears when the gap exists
- [x] T022 [US1] Implement `reviewer/src/swreview/checks/rms/report.py` reusing `findings.build_finding` through `tools/recording.py` and `ToolContext.replace_coverage`
- [x] T023 [P] [US1] Write `extractor/SwReview.Extractor.Tests/FeatureDumperTests.cs` over an `IFeatureSource` fake: rows per document once, not per instance; `Configuration` recorded; children and parents as ids, null plus gap when unavailable; `RawStatus` recorded verbatim as an int and null plus `sketch_status` gap on failure; `ConsumerIds` null plus gap when children fail; description null plus gap; `DefaultRadius` as meters from the simple-fillet data object and null plus gap for a variable fillet, with the recorded member names containing `GetDefinition` and none of `AccessSelections`, `ModifyDefinition`, `ReleaseSelectionAccess`; suppression per configuration; `ErrorCode`; a lightweight, suppressed, or unloaded component yields a `feature_tree_unavailable` gap and no resolve call; a document used under two configurations yields a `feature_tree_configuration` gap; no mutating member ever passes through the gate; `TypeNameCensus` receives no pass from this dumper
- [x] T024 [US1] Implement `extractor/SwReview.Extractor/Dump/FeatureDumper.cs` (walk via the indexer, `GetChildren`, `GetParents`, `GetSpecificFeature2` → `GetConstrainedStatus`, `Description`, `GetDefinition` → `ISimpleFilletFeatureData2.DefaultRadius`, per-configuration `IsSuppressed2`, `GetErrorCode2`) and wire it into `PackageWriter` as the `feature` phase behind `--features tree|none` (default tree); `CommandLineOptionsTests` cover the flag
- [x] T025 [P] [US1] Write `reviewer/tests/unit/test_tools_rms_query.py`: `list_features` (folder filter by group name or folder id, `include_suppressed`), `get_feature` (derived fields, resolved names), unknown ids as error results, step recording; and extend `reviewer/tests/unit/test_mcp_server.py`: add `rms_query` to `TOOL_MODULES` and the three names to `QUERY_TOOLS` (from which `OFFLINE_TOOLS` is composed), plus a new test asserting `[f.__name__ for f in MCP_TOOL_FUNCTIONS + MCP_BRIDGE_TOOL_FUNCTIONS]` equals the `enabled_tools` list parsed from `specs/002-task-pane-assistant/contracts/cli-profiles.md`
- [x] T026 [US1] Implement `reviewer/src/swreview/tools/rms_query.py` (`list_features`, `get_feature`; `list_equations` arrives in T042), register in `query_tools()`; in the same change add the rows to `specs/001-agentic-design-review/contracts/agent-tools.md` and bump the curated count asserted in `reviewer/tests/unit/test_provider_schema.py`, update `specs/002-task-pane-assistant/contracts/mcp-toolset.md`, `CliProfileWriter.EnabledTools` in `extractor/SwReview.AddIn/Terminal/CliProfileWriter.cs`, the `enabled_tools` line in `specs/002-task-pane-assistant/contracts/cli-profiles.md`, and `CliProfileWriterTests`
- [x] T027 [P] [US1] Write `reviewer/tests/unit/test_tools_rms_checks.py`: `check_rms_part` for one document and for all (including an unresolved document), unknown document id as an error result, findings and aggregated coverage written to the session, exceptions consulted with `check=` for `fail` outcomes only, step recording, a second call replaces coverage
- [x] T028 [US1] Implement `reviewer/src/swreview/tools/rms_checks.py` (`check_rms_part`), register in `check_tools()`, add its `agent-tools.md` row and bump the curated count; add the `modeling.resilience` item to `agent/checklist_v1.yaml` and a paragraph to `agent/prompts/system_v1.md`; extend the checklist test
- [x] T029 [US1] Add `swreview check rms` (`--package`, `--document`, `--scope`, `--json`) to `reviewer/src/swreview/cli.py` reusing the other `check` commands' output shape, with tests in `tests/unit/test_cli.py`
- [x] T030 [US1] Create golden fixture `reviewer/tests/golden/fixtures/rms-part/` generated by the T003 builder (three parts: fully compliant; one violation per reachable rule; one with null children, an unlisted type, and an `ICE` feature) with `checks/golden_rms.py` adapter `part_case(package, exceptions=())`; generate the baseline once and hand-check every expected rule id against `contracts/rules.md`
- [x] T031 [US1] Add `probe rms` to `extractor/SwReview.Extractor.Console/Program.cs` per `contracts/cli.md` (read-only guard; prints the traversal shape and raw values, the current `GetWhatsWrongCount`, and mate feature suppression) with `CommandLineOptionsTests` coverage

**Checkpoint**: `swreview check rms --scope part` on the fixture reproduces the expected rule ids.

---

## Phase 4: User Story 2 - Assembly Rules (Priority: P2)

- [x] T032 [P] [US2] Write `reviewer/tests/unit/test_rms_assembly_rules.py`: reference-geometry rule over entity kinds (reference passes, geometry incl. vertices fails, `unknown(<n>)` and sketch kinds unresolved, no mates skips); first component = first child of `cmp:0001` in package order (fixed passes; not fixed and fully constrained passes; not fixed and under/over constrained or solver error fails; not fixed and unknown/unavailable unresolved; no children skips); `MateGraph` over every instance with root-mate edges, breadth-first from the first fixed child with the configured limit, a second fixed child named, a disconnected component unresolved, a suppressed mate not an edge, a mate with a `mate_suppression` gap unresolved, no fixed child unresolved, no mates skips; Toolbox-as-configurations detection, and unresolved for a component with a Toolbox-identity gap; the evaluable rules run for the root document only and the subassembly document appears in `rms.assembly.subassemblies`; the data-gap rules are coverage-only (registry) and never dispatched
- [x] T033 [US2] Implement `reviewer/src/swreview/checks/rms/assembly.py` (`MateGraph`, `evaluate_assembly(package, table)`)
- [x] T034 [P] [US2] Write tests for `check_rms_assembly` (root only, subassemblies named, coverage written, step recording) in `test_tools_rms_checks.py` and for `--scope assembly` in `test_cli.py`
- [x] T035 [US2] Implement the tool in `tools/rms_checks.py`, its `agent-tools.md` row and count bump, and the CLI scope
- [x] T036 [US2] Golden fixture `reviewer/tests/golden/fixtures/rms-assembly/` from the builder (face mate; unfixed under-constrained first child with a later fixed component; four-deep chain from that root; a suppressed mate; Toolbox configurations; one component with a Toolbox-identity gap; one subassembly document) with adapter `assembly_case`

---

## Phase 5: User Story 3 - Equation Rules (Priority: P3)

- [x] T037 [P] [US3] Write `extractor/SwReview.Extractor.Tests/EquationDumperTests.cs` over an `IEquationSource` fake: text, lhs parsing (quotes stripped, first `=`), `IsGlobal` from the source's global flag (null plus `equations` gap when it throws), value or null, manager unavailable → empty list plus gap, once per document
- [x] T038 [US3] Implement `extractor/SwReview.Extractor/Dump/EquationDumper.cs` (`GetEquationMgr`, `GetCount`, `Equation(i)`, `GlobalVariable(i)`, `Value(i)`) wired into `PackageWriter` as the `equation` phase behind `--equations on|off`
- [x] T039 [P] [US3] Write `reviewer/tests/unit/test_rms_equation_rules.py`: globals present (fail when none, unresolved when the gap exists, any `is_global` is null, or the document is unresolved), dimensions driven (warn when none)
- [x] T040 [US3] Implement `reviewer/src/swreview/checks/rms/equations.py`
- [x] T041 [P] [US3] Write tests for `list_equations` (`test_tools_rms_query.py`), `check_rms_equations` (`test_tools_rms_checks.py`), and `--scope equations` (`test_cli.py`)
- [x] T042 [US3] Implement `list_equations` in `tools/rms_query.py` (in `query_tools()`, therefore in the MCP list and the profile: update `QUERY_TOOLS`, `mcp-toolset.md`, `EnabledTools`, `cli-profiles.md`, `CliProfileWriterTests` as in T026), `check_rms_equations` in `tools/rms_checks.py`, both `agent-tools.md` rows and the count bump, and the CLI scope
- [x] T043 [US3] Golden fixture `reviewer/tests/golden/fixtures/rms-equations/` from the builder with adapter `equations_case`

---

## Phase 6: User Story 5 - Exceptions and Advisory Coverage (Priority: P5)

- [ ] T044 [P] [US5] Write `reviewer/tests/unit/test_cli_exceptions_accept_rms.py`: the flat file accepts every `demonstrated` finding of a listed `fail` rule with `fingerprint_kind: feature_tree` and the reason as note, writes `exceptions.json`, sets `exception_id` on the findings, and re-renders the report; the four per-id statuses `accepted <n>`, `would accept <n>`, `unused`, `invalid (warn rule)` / `invalid (unknown rule)` are printed and carried in `--json`; any invalid id makes exit 1 and writes nothing; and `reviewer/tests/unit/test_cli_rms_types.py` for `swreview rms types`
- [ ] T045 [US5] Implement `swreview exceptions accept-rms` and `swreview rms types` in `cli.py`
- [ ] T046 [P] [US5] Golden fixture `reviewer/tests/golden/fixtures/rms-exceptions/` from the builder, exceptions passed inline through `case.json` `kwargs.exceptions` (one `active` for `rms.core.shell_last`, one `needs_review`), adapter `part_case`
- [ ] T047 [US5] Run quickstart Scenario 5 end to end on the fixtures and fix discrepancies

---

## Phase 7: User Story 4 - Suppressibility Test (Priority: P4)

- [ ] T048 [P] [US4] Write tests in `extractor/SwReview.Extractor.Tests/GuardTests.cs` and `SwGateTests.cs`: `ReadOnlyGuard` now denies `SetSuppression2`, `SetSuppression`, `ForceRebuildAll`, `AccessSelections`, `EditRollback`, `SetSaveFlag` (new `InlineData` rows); `new SwGate()` and every existing construction site still refuse `ForceRebuild3` and `SetSuppression2`; a gate built with a custom `ICallGuard` consults it and still reports to the observer and the breaker
- [ ] T049 [US4] Implement `extractor/SwReview.Extractor/Guard/ICallGuard.cs`, the read-only instance form, the six denied members, and the `SwGate` constructor parameter defaulting to read-only; `BridgeDispatcher` and every other caller unchanged
- [ ] T050 [P] [US4] Write `extractor/SwReview.Extractor.Tests/SuppressTestGuardTests.cs`: allows exactly `SetSuppression2` and `ForceRebuild3` beyond what the read-only guard allows; still denies `Save3`, `SaveAs3`, `EditDelete`, `ForceRebuildAll`, `EditRollback`, feature creation
- [ ] T051 [US4] Implement `extractor/SwReview.Extractor/Guard/SuppressTestGuard.cs` as the read-only guard minus the exemption set
- [ ] T052 [P] [US4] Write `reviewer/tests/unit/test_rms_suppress_plan.py`: `swreview rms suppress-plan` writes the plan per data-model section 2 (`document_id`, `configuration`, `group`, Detail content features in tree order with persistent refs, names, types) from the group assigner and the type table; exit 1 with a message when the document has no rows or no Detail group; `--json`
- [ ] T053 [US4] Implement `reviewer/src/swreview/checks/rms/plan.py` and the `rms suppress-plan` command in `cli.py`
- [ ] T054 [P] [US4] Write `extractor/SwReview.Extractor.Tests/SuppressTestTests.cs` over an `ISuppressTarget` fake and a plan file: refuses without acknowledgement, on unsaved changes (with the reopen message), on a rolled-back feature, on a differing active configuration, on a non-zero baseline `GetWhatsWrongCount` (naming the errors), when the live walk differs from the package rows (count, order, type name, name, depth, suppression), and when a planned feature fails `IsSamePersistentID`; records the baseline; snapshots the whole tree; skips pre-suppressed features with `already_suppressed`; records `not_applied` without rebuilding when the suppression returns false or the state did not change; suppresses one feature at a time, rebuilds, records the count and up to 20 messages with `messages_truncated`, `rebuild_errors` only above the baseline; restores dependents the suppression also suppressed by comparing to the snapshot; verifies and sets `restore_verified`; on a throwing rebuild the restore runs, the breaker is reset first, `CircuitOpenError` per feature is caught, unrestored features are named and the exit code is non-zero; `--limit` and `--timeout-seconds` yield `truncated` rows so `len(rows) == features_present`; `elapsed_ms` per row; never calls a save member (asserted on recorded member names); the recording observer's distinct member names land in `suppress-test.log`; appends through `PackageAppender.AppendSuppressTest` and prints the closing "modified in memory" message
- [ ] T055 [US4] Implement `extractor/SwReview.Extractor/Rms/SuppressTest.cs`, `PackageAppender.AppendSuppressTest` with a `PackageAppenderTests` case, and the console `suppress-test` command (builds its gate with `SuppressTestGuard` and a recording observer; `--plan` required) with `CommandLineOptionsTests` coverage
- [ ] T056 [P] [US4] Write `reviewer/tests/unit/test_rms_suppress_rule.py`: every row of the outcome table in `contracts/rules.md` (`ok` pass, `rebuild_errors` fail with counts and messages in observed, `already_suppressed` and `truncated` skip, `not_applied` and `aborted` unresolved, missing row unresolved with `not tested`, run for another document, run configuration differs from the review's, a row for a feature that is not Detail content reported unused, `restore_verified` false makes every row unresolved, coverage reason `<tested>/<present>`)
- [ ] T057 [US4] Implement `rms.detail.individually_suppressible` in `checks/rms/part.py` reading `package.rms_suppress_test`; extend the `rms-part` golden with a run on the seeded-violation part carrying one `rebuild_errors` row, `ok` rows, one `already_suppressed` row, and one Detail content feature with no row; regenerate that golden's baseline and hand-check it

---

## Phase 8: Polish

- [ ] T058 [P] Update `specs/001-agentic-design-review/contracts/cli.md` with the new commands (the `agent-tools.md` rows were added by the registering tasks), `README.md` with the family, and `benchmarks/README.md` with the plan and suppress-test workflow
- [ ] T059 Run quickstart Scenarios 1 and 2 (no SOLIDWORKS); fix discrepancies
- [ ] T060 [P] Add `reviewer/tests/perf/test_rms_perf.py` (marker `perf`, excluded from the default and CI runs): `check rms` over a builder-generated 100-part package completes under 2 s
- [ ] T061 DRY and constitution review across `checks/rms/`, `tools/rms_*.py`, `exceptions.py`, `tools/recording.py`, `tools/context.py`, `Dump/FeatureDumper.cs`, `Rms/SuppressTest.cs`, the guard seam; confirm no code was copied from the source repo's Python; confirm feature 001 and 002 goldens are byte-identical
- [ ] T062 Workstation: quickstart Scenarios 3 and 4 on the fixture parts; time the dump with and without the new phases on a 200-component assembly and record it; record the traversal shape, `GetChildren`/`GetParents` behavior, mate suppression reads, and every unknown type name in `benchmarks/native/rms-part/notes.md`; add the confirmed weldment, sheet-metal, derived-part, and Origin-mate names to `rms_types.yaml` and update `calibrated_version`

---

## Dependencies & Execution Order

- Phase 1 → Phase 2 → US1 → US2 → US3 → US5 → US4 → Polish
- US2 and US3 rules can be written in parallel with US1's dumper; US4's Python rule and plan depend on US1's part evaluation and groups; US5's import depends on US1's tools and T016
- Workstation task T062 is the only step needing SOLIDWORKS; T024, T031, T038, and T055 are compiled and fake-tested here

### Parallel Opportunities

- Phase 1: T002, T003, T004 after T001
- Phase 2: T007/T008, T009/T010, T011/T012, T013/T014, T015/T016, T017/T018 in parallel after T006
- Phase 3: T019, T021, T023, T025, T027 in parallel; T020 after T019; T022 after T021; T024 after T023; T026 after T025; T028 after T027
- Phases 4 and 5 in parallel with each other; Phase 7's C# tasks in parallel with Phase 6

## Notes

- Never classify an unknown or ambiguous type; class-dependent rules consult the one `class_of` helper; unknown types are still content.
- The suppress-test command is the only mutation path; the exemption set is exactly two members; its tests assert the recorded member names; the plan comes from the reviewer.
- Feature 001 and 002 goldens must remain byte-identical except the checklist block in `cover-blind-tap.yml` (T028); the IR bump adds optional members only; the finding contract is unchanged.
