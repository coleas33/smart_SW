# Research: Resilient Modeling Checks

**Feature**: `003-resilient-modeling` | **Date**: 2026-09-15 (revision 3) | **Plan**: [plan.md](plan.md)

Phase 0 output from two Opus research passes over `LifeDay/Solidworks-Resilient-Modeling-Skill`
at commit `df49e6d` (cloned for inspection), the existing extractor and reviewer code, a
reflection pass over the SOLIDWORKS 2024 SP5 interop assemblies installed on this machine,
and two adversarial review rounds of the package.

## R1. What the source repository is, and what may be reused

A Claude Code plugin whose purpose is to *build* SOLIDWORKS parts under the Resilient
Modeling Strategy (RMS, Richard Gebhard, 2013). It contains prose instructions
(`skills/solidworks-rms/SKILL.md`), a pywin32 checker (`rms_check.py`, 21 rule ids), COM
helpers, a capability ledger (`capabilities.yaml`), and API notes verified on SOLIDWORKS
2026 SP1.1 only. It has no license file, so it is all-rights-reserved by default; the author
granted the project owner permission to reuse it on 2026-09-15 (personal communication).
RMS itself is a published method; the six group names and rule statements are used as the
method's vocabulary.

**Decision**: Reuse the checker's rule semantics, severities, type-name sets, folder and
end-tag handling, and API recipes as the specification of the family; implement in this
project's shape (C# read-only dump, Python pure rules, findings with evidence). Do not
vendor or copy its Python (it is pywin32, late-bound, mutating in one rule, and
2026-calibrated). Record the permission in NOTICE before any reused semantics ship (T002),
and ask the author to add an explicit license upstream.

## R2. Rule catalogue (from `rms_check.py`) and the deliberate deviations

| Rule id (ours) | Source severity | Source condition | Notes |
|---|---|---|---|
| `rms.folders.present` | WARN | any of the six group folders missing | never a failure |
| `rms.folders.ordered` | FAIL | group indices in tree order not sorted | dedupe end-tag duplicates |
| `rms.grouping.all_features_in_a_group` | FAIL | a content feature before the first group folder | `is_content` excludes only the folder type, tolerated loose types, and the three default planes plus Origin, so unrecognised types are content; with no folders at all every content feature is loose and the rule FAILs |
| `rms.groups.no_solids_in_ref_or_construction` | FAIL | a type in the union of the solid and cut sets inside `1-Ref` or `2-Construction` | the source reads the union, so `ICE` counts |
| `rms.core.shell_last` | FAIL / SKIP | the last Core feature is not the (last) shell | SKIP when no shell |
| `rms.detail.holes_last` | WARN / SKIP | hole features in Detail are not the trailing block (sketches ignored) | |
| `rms.modify.transform_before_replicate` | WARN / SKIP | a pattern precedes a draft in Modify | source SKIPs only on an empty Modify group |
| `rms.quarantine.chamfers_before_fillets` | FAIL | a fillet precedes a chamfer in Quarantine | |
| `rms.quarantine.largest_fillet_first` | FAIL / SKIP | fillet default radii not non-increasing | SKIP with fewer than two readable radii |
| `rms.quarantine.only_fillets_and_chamfers` | FAIL | anything else in Quarantine | end-tags excluded |
| `rms.refs.direction` | FAIL | a dependent (child from `GetChildren`) of a feature lives in an earlier group | |
| `rms.refs.quarantine_has_no_children` | FAIL | any dependent of a Quarantine feature | |
| `rms.detail.no_internal_references` | FAIL | a Detail feature depends on another Detail feature | skips a sketch with exactly one consumer; allows both inside the same nested subfolder |
| `rms.intent.every_feature_described` | FAIL | empty `Description` on a content feature | |
| `rms.sketches.fully_defined` | FAIL | constrained status unknown or under defined | |
| `rms.sketches.not_over_defined` | FAIL | constrained status over defined or solver error | |
| `rms.sketches.one_sketch_per_feature` | FAIL | a sketch with more than one named consumer | zero consumers passes |
| `rms.params.global_variables_present` | FAIL / SKIP | no equation whose left side lacks `@` | SKIP when the equation manager is unavailable |
| `rms.params.dimensions_driven_by_equations` | WARN | no equation whose left side contains `@` | |
| `rms.detail.individually_suppressible` | FAIL / SKIP | suppress, rebuild, count what's wrong, unsuppress, per Detail feature | mutating: engineer-run command only (US4) |
| (`quarantine.order`) | SKIP | the source's 21st id: one SKIP row when Quarantine is empty or absent | replaced by per-rule skipped coverage on the four Quarantine rules; no other source id is dropped |

Group semantics: `FtrFolder` features named exactly one of the six groups start a group;
membership is sticky until the next group folder (an end-tag never closes a group); folder
contents are read one level deep through `GetFirstSubFeature`/`GetNextSubFeature` (nested
subfolders only for the coupled pair exception). End-tag markers are `FtrFolder` features
named `...___EndTag___`.

Waivers: a flat `{rule_id: reason}` JSON turns a FAIL into WAIVED with the reason appended;
WARN is not waivable. Output of the source checker is stdout only; ours is findings and
coverage.

**Deliberate deviations from the source** (each is a decision, recorded so a later
recalibration does not restore the source behavior by accident):

| Where | Source | Ours | Why |
|---|---|---|---|
| sketch status `unknown` (raw 1), autosolve off (raw 7), or unmapped | FAIL | unresolved | FR-008 and Principle I: an uninterpreted or unsolved status is not evidence |
| `rms.folders.ordered` with fewer than two groups | PASS (vacuous) | skip, reason `fewer than two groups` | Principle I: nothing was evaluated |
| `rms.modify.transform_before_replicate` with no draft or no pattern | PASS (vacuous) | skip, reason names what is absent | same |
| `rms.refs.quarantine_has_no_children` with no Quarantine group | PASS (vacuous) | skip, reason `no Quarantine group` | same |
| `rms.assembly.mates_to_reference_geometry` and `mate_chain_depth` with no mates | (not in the checker) | skip | same |
| assembly rules on subassemblies | (SKILL.md prose, per assembly) | root assembly only; `rms.assembly.subassemblies` unresolved once per review naming them | subassembly mates are not extracted (`MateDumper` walks the root tree only) |
| `ICE` in the hole set | in both `cut` and `hole` | `ambiguous`: counts as material for the group-content rule, unresolved for `holes_last` | the source's recipe builds holes as cuts; a real part's `ICE` boss would be mis-read as a hole |
| `quarantine.order` | one SKIP row | per-rule skipped coverage | one bucket per rule per document |
| waivers | flat file, package-wide | exceptions bound to instances, configuration, and a tree-and-inputs fingerprint; the flat file is an import | Principle VI: no blanket exclusions |
| vertex mates | "planes, axes, points, coordinate systems" (SKILL.md) | vertices flagged with faces and edges | a vertex is model geometry |
| first component | "fix or fully constrain the first component" | fixed, or fully constrained per `IComponent2.GetConstrainedStatus`; unresolved when the status is unknown | the method's own alternative is accepted, from data |
| suppressibility baseline | counts `GetWhatsWrongCount` after each rebuild against zero | refuses a part with pre-existing rebuild errors; a row fails only above the recorded baseline | a pre-existing error would otherwise fail every feature |

## R3. Type-name sets (from the source, calibrated on 2026)

Shipped as `reviewer/src/swreview/checks/rms_types.yaml` (created by moving the draft in
`contracts/rms-types.yaml`; see contracts/README.md). Changes from the source lists:

- `Hole`, `HoleWzd`, `SimpleHole` are only in `hole`, not also in `cut`, so the class sets
  are disjoint and `classify` is single-valued; the group-content rule names
  `{solid, cut, hole, ambiguous}` explicitly.
- `ICE` is in `ambiguous`, not in `solid`, `cut`, or `hole` (see R2).
- The table carries `calibrated_version: "2026 SP1.1"`, a `constrained_status` mapping
  (7, autosolve off, maps to `unknown`), `end_tag_suffix`, `folder_type`, and the assembly
  entity-kind lists.
- 2026-only system folders (`CommentsFolder`, `SelectionSetFolder`, `InkMarkupFolder`) stay
  in `tolerated_loose`; 2024 folder types the probe reports (weldment cut lists, sheet-metal
  and flat-pattern folders, derived-part base features) are added by T062 once seen. Until
  then they are content of unknown class: grouped and described like any feature, unresolved
  for class-dependent rules, and named in `rms.types.unknown`.

The feature-type census in the extractor (`TypeNameCensus`) answers a different question
(which type names no dump pass consumed); the RMS unknown-type report (which type names the
rule tables do not classify) is computed in Python from `features[]` and recorded as one
unresolved coverage item per review. Both are kept; the feature dumper does not participate
in the census.

## R4. Assembly and advisory rules (from `SKILL.md`)

The extractor reads the root assembly's mates only (`MateDumper` walks the root document's
feature tree) and `Mate` has no owning-document field, so the evaluable assembly rules run on
the root assembly document only; subassemblies are covered by the data-gap rule
`rms.assembly.subassemblies`.

Deterministic from data we hold or add in this feature:

- `rms.assembly.mates_to_reference_geometry`: entity kinds in `reference_entity_kinds`
  (`swSelDATUMPLANES`, `swSelDATUMAXES`, `swSelDATUMPOINTS`, `swSelCOORDSYS`) pass;
  `geometry_entity_kinds` (`swSelFACES`, `swSelEDGES`, `swSelVERTICES`) fail; any other kind,
  including the dumper's `unknown(<n>)` fallback and sketch entities, is unresolved for that
  mate. The 2024 interop has no `swSelORIGINS` member; an Origin mate's kind is recorded by the
  probe and added to the table if it is a distinct member.
- `rms.assembly.first_component_fixed`: the subject is the first `ComponentInstance` whose
  `parent_id` is the root instance `cmp:0001`, in package order; passes when `is_fixed` or
  `constrained_status` maps to fully constrained; fails when not fixed and under or over
  constrained or in solver error; unresolved when the status is unknown or unreadable.
  `constrained_status_raw` is a new optional field on `ComponentInstance` read from
  `IComponent2.GetConstrainedStatus` (verified present on the 2024 interop, returns `int` in
  `swConstrainedStatus_e`).
- `rms.assembly.mate_chain_depth`: breadth-first over the mate graph whose nodes are every
  component instance and whose edges are the unsuppressed root mates (a mate's entities
  name the instances it joins), from the first fixed child of `cmp:0001` (further fixed
  children are named); unreachable components are unresolved; a mate whose suppression could
  not be read is unresolved; limit configurable, default 3. `Mate.suppressed` is today
  written `false` unconditionally by `MateDumper`; this feature reads the mate feature's
  `IsSuppressed2` into it.
- `rms.assembly.toolbox_parts_not_configurations`: a Toolbox document with several instances
  referencing different configurations; unresolved for any component whose Toolbox identity
  gap is recorded (`is_toolbox` is false-on-failure in the dumper).

Needs data not yet extracted (unresolved coverage, once per review, in this version):
`rms.assembly.no_sibling_in_context_refs` (external references),
`rms.assembly.positions_driven_by_globals` (assembly equations),
`rms.assembly.mates_described` (mate descriptions), `rms.assembly.subassemblies`
(subassembly mates).

Out of scope by decision (`out_of_scope` coverage, once per review): the drawing rule
`rms.drawing.model_items_preferred`, and the judgement-only rules
`rms.advisory.structural_vs_cosmetic_fillets`, `rms.advisory.core_shaping_cuts`,
`rms.advisory.description_quality`, `rms.advisory.sketch_plane_choice`,
`rms.advisory.avoid_multibody`.

## R5. SOLIDWORKS API for the dump: verified on the 2024 SP5 interop, and what the probe must still show

Verified by reflection over `SolidWorks.Interop.sldworks.dll` and `swconst.dll` (2024 SP5)
on 2026-09-15:

| Member | Present | Use |
|---|---|---|
| `IFeature.GetChildren`, `GetParents` | yes (both) | dependents and dependencies; the runtime content on 2024 is what the probe checks |
| `IFeature.GetFirstSubFeature`, `GetNextSubFeature`, `GetNextFeature`, `GetTypeName2`, `Description`, `GetErrorCode2`, `IsSuppressed2`, `IsRolledBack`, `GetSpecificFeature2`, `GetDefinition` | yes | tree walk, state, sketch and fillet data, rollback refusal, mate feature suppression |
| `ISketch.GetConstrainedStatus` | yes | raw status; `swConstrainedStatus_e` on 2024 is 1 unknown, 2 under, 3 fully, 4 over, 5 no solution, 6 invalid solution, 7 autosolve off (identical to the 2026 values the source used); 7 maps to `unknown`, not to an error |
| `ISimpleFilletFeatureData2.DefaultRadius` | yes | read off the object `GetDefinition` returns, without `AccessSelections` (`IFillet` does not exist on 2024); `IVariableFilletFeatureData2` fillets record null plus a gap |
| `IEquationMgr.GetCount`, `Equation(i)`, `Value(i)`, `GlobalVariable(i)` | yes | `is_global` comes from `GlobalVariable(i)`, not from parsing the text |
| `IComponent2.GetConstrainedStatus`, `IsFixed` | yes | first-component rule |
| `IModelDoc2.GetSaveFlag`, `ForceRebuild3`, `GetEquationMgr` | yes | suppress-test preconditions and rebuild |
| `IModelDocExtension.GetWhatsWrongCount`, `GetWhatsWrong`, `IsSamePersistentID`, `ForceRebuildAll` | yes | suppress-test baseline, results, and identity binding; `ForceRebuildAll` must be denied |
| `IFeature.SetSuppression2`, `SetSuppression` | yes | suppress-test only; both must be denied elsewhere; `swFeatureSuppressionAction_e` 0 suppress / 1 unsuppress, `swInConfigurationOpts_e` 1 this configuration |
| `IFeatureManager.EditRollback` | yes | never called; denied |
| `swSelectType_e` | no `swSelORIGINS` | see R4 |

Still to be shown by `swreview-extract probe rms` on the workstation (T062), because the
interop signature does not tell us the runtime behavior:

1. Whether folder contents come back through sub-feature traversal (nested shape) or as a
   flat walk between the folder and its end-tag (flat shape) on 2024; the indexer and the
   group assigner accept both.
2. Whether `GetChildren` and `GetParents` return values for ordinary features on 2024.
3. Whether `Description` reads without the tree-display option.
4. The type names of weldment cut-list folders, sheet-metal and flat-pattern features,
   derived-part base features, and an Origin mate entity.
5. Whether `ICE` occurs at all on 2024.
6. Whether a mate's feature reports `IsSuppressed2` for a suppressed mate.

**Decision**: The dumper records nulls plus gaps wherever a member fails; the rule layer
turns those into unresolved coverage (FR-003, FR-008). The probe prints the raw values for
one document so calibration is one run.

## R6. Suppressibility test design

The source rule suppresses each Detail feature, force-rebuilds, reads `GetWhatsWrongCount`,
and unsuppresses in a `finally`. This project's `ReadOnlyGuard` is a denylist; today it
denies `EditSuppress2`, `EditUnsuppress2`, `ForceRebuild3`, and `ModifyDefinition`, but not
`SetSuppression2`, `SetSuppression`, `ForceRebuildAll`, `AccessSelections`, `EditRollback`,
or `SetSaveFlag`, which this feature is the first to touch. `SwGate.Guard` calls the static
`ReadOnlyGuard.Assert` directly, so there is no seam for a second guard yet. The extractor
holds no RMS constant (R7), so it cannot decide which features are Detail content.

**Decision**:

- Add the six members above to `ReadOnlyGuard.DeniedMembers` with guard tests, in the same
  task that introduces the seam.
- Introduce `ICallGuard { void Assert(string member); }`; `SwGate` takes one in its
  constructor and defaults to the read-only guard, so the add-in, the bridge, and every other
  console command are unchanged and still refuse `ForceRebuild3` and `SetSuppression2`.
- `SuppressTestGuard` is the read-only guard minus the exemption set `{SetSuppression2,
  ForceRebuild3}`; nothing else changes, so the hundreds of getters need no enumeration.
- The reviewer writes the plan: `swreview rms suppress-plan --package <dir> --document <id>`
  emits the review configuration, the Detail group name, and the Detail content features
  (ids, persistent refs, names, types) from the group assigner and the type table.
- `swreview-extract suppress-test --doc <part> --plan <file> --acknowledge-rebuild --out
  <package dir>` refuses without the flag, when `GetSaveFlag` reports unsaved changes (the
  message explains that a previous run leaves the document modified), when any feature
  `IsRolledBack`, when the active configuration differs from the plan's, when
  `GetWhatsWrongCount` is already non-zero (naming the errors), and when the live walk
  differs from the package's `features[]` rows for the document (count, order, type names,
  names, depth, suppression) or any planned feature fails `IsSamePersistentID` (re-dump
  first). It records the baseline count, snapshots `IsSuppressed2` for every feature, tests
  the planned features in order, checks the `SetSuppression2` return value and re-reads the
  state (`not_applied` when it did not change), rebuilds with `ForceRebuild3(false)`, reads
  the count (a row is `rebuild_errors` only above the baseline) and up to 20 messages,
  restores by comparing the whole tree against the snapshot and unsuppressing every feature
  that differs (a suppression also suppresses dependents), verifies, and stops the run with
  `restore_verified = false` when it cannot. The restore path calls `CircuitBreaker.Reset()`
  first and catches `CircuitOpenError` per feature, naming every unrestored feature on stderr
  and in `suppress-test.log`, and exits non-zero. `--limit` (default 50) and
  `--timeout-seconds` (default 900) bound the run; untested features get `truncated` rows. A
  recording `ISwGateObserver` on the command's gate writes the distinct member names to the
  log (SC-003). Rows are appended through `PackageAppender` (as `interference` and `capture`
  are), never by `PackageWriter`; a later `dump` overwrites the package and the run with it,
  exactly as interference results are.
- It is a console command only: not in the add-in, the bridge, or the MCP toolset. Recorded
  as a documented exception in the plan's Complexity Tracking.

## R7. Where group assignment and classification live

**Decision**: The extractor dumps the raw tree (type names, names, index, depth, enclosing
folder from sub-feature structure only, no name knowledge); Python derives folders and
end-tags (`folder_type`, `end_tag_suffix` from the table), groups and subfolders (sticky
semantics, both traversal shapes), classes (type tables), and the suppress-test plan. The C#
indexer and the suppress-test command therefore hold no RMS constant, and recalibration for
2024 touches YAML and tests, not C#. `TypeNameCensus` is not fed by the feature dumper.

## R8. Findings, coverage, and exceptions reuse

- `RuleResult` wraps the existing `CheckResult` (`checks/result.py`) with the rule id, the
  document, the outcome, and the subject ids, one per outcome reached; `tools/recording.py`
  turns fail and warn results into findings exactly as the other check tools do, with one
  addition: `result_to_finding` and `record_results` gain a `tool_result_ids` argument and
  `ToolContext` a `current_step_id`, because today the recorder passes neither a step id nor
  a calculation and the other checks supply a `Calculation`, which a structural rule has no
  honest way to produce.
- `Finding.component_ids` are the instances of the part document; subjects are strings in
  `Finding.inputs`; the feature 001 finding contract is unchanged (see data-model section 2).
- Coverage is aggregated per rule per bucket per review through a new
  `ToolContext.replace_coverage`, with a `modeling.resilience` summary item so
  `Checklist.bucket_of` closes the item on a clean package.
- Waivers are `ReviewException`s: `ReviewException.fingerprint_kind` (`geometry` default,
  `feature_tree` for `rms.*` checks, hashing the tree and every rule input) is the only model
  change; `ExceptionStore.match` takes a required `check` (both interference call sites are
  updated); `swreview exceptions accept` works unchanged, and `swreview exceptions accept-rms`
  imports the checker's flat file against a run.

## R9. Testing

Unit tests per rule over synthetic feature lists from a builder (`tests/support/features.py`
on top of `tests/support/packages.py`), golden fixtures generated by the same builder
(`rms-part`, `rms-assembly`, `rms-equations`, `rms-exceptions`) each with manifest entries and
one component instance per part document, C# tests of the tree indexer over both traversal
shapes, of the dumpers over fakes, of the guard seam and denylist, and of the suppress-test
orchestration over a fake target. A perf test over a synthetic 100-part package, marked and
excluded from CI by default. Workstation: `probe rms`, a timed dump with and without the
new phases, `swreview check rms`, `swreview rms suppress-plan`, and `suppress-test` on the
fixture parts.

## R10. The Model check tab (User Story 6)

Phase 0 input for User Story 6 is the design brief at `%LOCALAPPDATA%\Temp\claude\C--Users-<you>-source-repos-smart-SW\ffaad261-c3fe-41db-902a-57b83fd7414b\scratchpad\research-004\design-brief.md`, Part B (sections B1 to B9) together with its cross-cutting
section 1 and its API ledger in sections D1 and D2. Six points the story rests on, each with
the section that argues it:

1. **A part opened alone dumps nothing today** (brief section 1, and B3 row 2).
   `ComponentTreeDumper.Traverse` takes the tree from
   `IConfiguration.GetRootComponent3(false)`, which is expected to return null for a part
   opened alone, so `scope.Components` is empty, `FeatureDumper.Dump` iterates nothing,
   `features[]` comes out empty, and all 34 rules report unresolved on exactly the document
   type the family was written for. The dumper synthesizes a part-root node from the document
   itself (FR-023, T064). The behavior on 2024 is recorded by PROBE-15 (brief D2), not
   assumed; without the fix feature 004 has no input at all.
2. **The `ModelCheck` dump profile** (brief B2 and B3 row 1). One `DumpProfile { Full,
   ModelCheck }` gates four phases in `PackageWriter.Build`: hole, fastener, face and body or
   mesh. That is most of a dump's cost, because the full dump also tessellates every body,
   writes GLB files and reads face geometry. The profile is recorded as
   `ExtractorInfo.profile`, optional with default `"full"`, so the IR step is minor (1.1.0 to
   1.2.0) and 1.1.0 packages still load (FR-022, T064 and T065). The arithmetic behind the
   "under 2 seconds on a 150-feature part" claim, and the 8 to 40 second estimate for a
   200-component assembly, are in brief B2 and are unverified until PROBE-14.
3. **One no-language-model evaluation entry point** (brief B3, "Where the rules run", and
   section 2.9 for the grade). `checks/rms/run.py::run_rms_check(package_dir, *, scope,
   document_id)` is the single path; `swreview check rms` (T029, refactored) and
   `POST /checks/rms` are its two callers. A `swreview check rms --json` subprocess launched
   by the add-in was weighed and rejected: `uv run` re-resolves the environment and imports
   `swreview`, pydantic, typer and PyYAML, 1 to 3 seconds of cold start on a path whose work
   is tens of milliseconds, and it would add a second transport exercised only when something
   is already broken (FR-024, T067). The grade is counts per bucket with the unresolved rule
   ids named, the fraction `checked / (checked + failed + warned)` secondary, and no letter
   (FR-025, T069).
4. **Exceptions must be carried forward** (brief B6.1). `ExceptionStore`'s path is always
   `<package dir>/exceptions.json` and every run creates a new folder, so User Story 5's
   promise that an acceptance survives the next review does not hold unless the engineer
   copies the file by hand, and a tab pressed after every edit makes that urgent. The newest
   `exceptions.json` under the run root whose package carries the same `design_id` is copied
   byte-identically into the new folder before the rules run, in Python inside `run_rms_check`
   so the command line gets it too. The four-case matrix (copied and byte-identical, different
   `design_id` not copied, no candidate is not an error, unreadable candidate refuses the run)
   is the test (FR-029, T066 and T067).
5. **Three defects the story fixes rather than works around** (brief B3.1), carried into the
   plan as D1 to D3: `tool_result_ids` names a step that was never recorded, because
   `ToolContext.current_step_id` is the index the next step will take and only
   `RecordedTool.call` makes that true; Show is dead for every RMS finding in the Review page
   today, because the page reads `finding.drawing_locations[].persist_ref` and RMS findings
   leave that array empty; and Show selects nothing when the part is reached through a
   component, because the resolver resolves against the scope document and then selects on the
   active one. The fixes are the registry dispatch with a session sink, a source reference per
   subject plus a structured `subjects` array beside the finding, and a pure `FeatureSelection`
   strategy (FR-024, FR-026, FR-027; T067, T071, T079). `IFeature.GetNameForSelection` and
   `IComponent2.GetSelectByIDString` are verified present on the 2024 SP5 interop (brief D1);
   whether their concatenation is the right composition on 2024 is PROBE-16 (brief D2).
6. **The partial-evidence trap** (brief B6.2). A model-check package has no faces, no holes,
   no fasteners and no meshes, so a step strip that lets the engineer press Review next would
   have the agent review a model it cannot see and read as a bad model rather than a missing
   extract. The recorded profile is what prevents it: the evidence step says "model check only
   (features and equations)" and offers Extract full evidence, `POST /sessions` records a
   coverage item naming the skipped phases, and `swreview check rms` refuses a package whose
   `features` array is empty (FR-022, T065 and T084).

The run folder, route, message and Accept contracts that follow from all of this are in
`contracts/model-check.md`; the brief's own statements of them are B7 (messages), B6 (run
artifacts) and B8 (the page and the Accept label).
