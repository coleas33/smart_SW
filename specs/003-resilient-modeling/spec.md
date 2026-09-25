# Feature Specification: Resilient Modeling Checks

**Feature Branch**: `003-resilient-modeling`

**Created**: 2026-09-15

**Status**: Draft (revision 4, after two adversarial spec review rounds on 2026-09-15; User Story 6, the Model check tab, was added on 2026-09-16)

**Amended**: 2026-09-25 by the owner (decision 20A): the system rows a real 2024 SP5 dump lists - the annotations container's folders and view, the scene's lights, a derived part's body and reference folders, the cosmetic thread - are tolerated loose types, not content, so the checks and the Model check stop counting them loose or asking them for a description; one list of tolerated types serves this feature's rules and feature 004's planner alike (Edge Cases, Key Entities, research R3, `contracts/rules.md` "Content features", tasks T090 to T092). Feature 008's replay reads a recorded finding this narrows as narrowed, not lost (its decision 23A).

**Input**: User description: "Resilient Modeling checks: dump part feature trees and equations into the IR and evaluate the Resilient Modeling Strategy rules (part, assembly, equation, drawing) as deterministic review findings, with an engineer-run suppressibility test." Design approved in conversation on 2026-09-15. Rule semantics come from the Resilient Modeling Strategy (Richard Gebhard, 2013) and from the checker in `LifeDay/Solidworks-Resilient-Modeling-Skill` (commit `df49e6d`), reused with its author's permission; the normative rule list is `contracts/rules.md`.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Part Feature-Tree Hygiene Findings in a Review (Priority: P1)

When an engineer reviews an assembly, the reviewer also grades every part's feature tree against the Resilient Modeling Strategy: the six group folders present and in order (Reference, Construction, Core, Detail, Modify, Quarantine); every content feature inside a group; no solids, cuts, or holes in Reference or Construction; a shell last in Core; holes last in Detail; drafts before patterns in Modify; chamfers before fillets, largest fillet first, and nothing but fillets and chamfers in Quarantine; references that only point backward; nothing depending on a Quarantine feature; no Detail feature depending on another Detail feature (except a consumed sketch or a coupled pair in one subfolder); sketches fully defined and not over defined; no sketch shared by two features; and a description on every content feature. Each violation is a finding naming the part, the features, the rule, and what was observed. Rules that pass are checked coverage. Rules that cannot run (no Quarantine group, no shell, fewer than two fillet radii) are skipped coverage with the reason. Rules whose inputs are missing or ambiguous are unresolved coverage, never a pass or a fail; a rule may land in more than one bucket for one part when its features differ.

**Why this priority**: It is the whole request: the method's part rules are the bulk of the checker and the source of most modeling debt.

**Independent Test**: Extract a part that violates six rules (a cut in Construction, an undescribed boss, an under-defined sketch, a hole before a boss in Detail, a smaller fillet before a larger one in Quarantine, a Detail feature depending on a Modify feature) and confirm six findings with the right rule ids and feature names, checked coverage for the rules that pass, and skipped coverage for the rules with nothing to evaluate.

**Acceptance Scenarios**:

1. **Given** a part whose feature tree is grouped in the six folders in order, **When** the review runs, **Then** `rms.folders.ordered` and `rms.grouping.all_features_in_a_group` appear as checked coverage for that part and no finding is raised for them.
2. **Given** a part with a content feature outside every group, or with no group folders at all, **When** the review runs, **Then** one `rms.grouping.all_features_in_a_group` finding names every loose content feature.
3. **Given** a Modify feature whose dependents (children) include a feature in Detail, **When** the review runs, **Then** a `rms.refs.direction` finding names both features and their groups.
4. **Given** a sketch whose constrained status is under defined, **When** the review runs, **Then** a `rms.sketches.fully_defined` finding names the sketch and the feature that consumes it.
5. **Given** a part with no Quarantine group, **When** the review runs, **Then** the four Quarantine rules (`rms.quarantine.chamfers_before_fillets`, `rms.quarantine.largest_fillet_first`, `rms.quarantine.only_fillets_and_chamfers`, `rms.refs.quarantine_has_no_children`) appear as skipped coverage with the reason "no Quarantine group", not as findings and not as passes.
6. **Given** a feature whose type name is not in the rule tables, **When** the review runs, **Then** the feature is still listed, it is still graded for grouping and description, every rule that needed its class is unresolved for that feature, and the type name is reported once per review in the unresolved coverage.
7. **Given** the extractor could not read dependents for a part, **When** the review runs, **Then** every reference rule for that part is unresolved with the gap named.
8. **Given** a part reached only through lightweight, suppressed, or unloaded components, **When** the review runs, **Then** every part-scope and equation-scope rule for that part is unresolved coverage naming the component state, and the extractor never resolved the component.

---

### User Story 2 - Assembly Discipline Findings from Mates (Priority: P2)

The review grades the root assembly against the method's assembly rules using the mates and components already extracted: mates that attach to faces, edges, or vertices instead of planes, axes, points, or coordinate systems; a first component that is neither fixed nor fully constrained; mate chains deeper than a configured limit; Toolbox fasteners inserted as configurations of one file rather than as parts. Four assembly rules whose data is not yet extracted (sibling in-context references, positions driven by assembly global variables, mate descriptions, and the rules for subassemblies, whose mates are not extracted) are reported as unresolved coverage with the missing data named.

**Why this priority**: The data already exists in the IR, so the cost is low and the findings are common causes of fragile assemblies.

**Independent Test**: A fixture with one face-to-face mate, an unfixed and under-constrained first component while a later component is fixed, and a four-deep mate chain from that fixed component yields three findings naming the offending mate and components; a version with the first component fixed and plane mates yields checked coverage.

**Acceptance Scenarios**:

1. **Given** a mate whose entities are faces, edges, or vertices, **When** the review runs, **Then** a `rms.assembly.mates_to_reference_geometry` finding names the mate, its entity kinds, and the two components.
2. **Given** the first child component of the root assembly is not fixed and its constrained status is under or over constrained, **When** the review runs, **Then** a `rms.assembly.first_component_fixed` finding names it; **Given** it is not fixed and its constrained status is unknown or unreadable, **Then** the rule is unresolved for it.
3. **Given** a mate graph whose longest distance from the fixed root exceeds the limit, **When** the review runs, **Then** a `rms.assembly.mate_chain_depth` finding lists the chain.
4. **Given** an assembly with no mates, **When** the review runs, **Then** the reference-geometry and chain-depth rules are skipped coverage, not passes.
5. **Given** any review, **When** it runs, **Then** `rms.assembly.no_sibling_in_context_refs`, `rms.assembly.positions_driven_by_globals`, `rms.assembly.mates_described`, and `rms.assembly.subassemblies` (naming the subassembly documents) are unresolved coverage naming the missing data, recorded once per review.

---

### User Story 3 - Equation and Global Variable Findings (Priority: P3)

Each part's equations are extracted and graded: a part with no global variables is a finding; a part whose dimensions are not driven by equations is a warning-level finding; the equation text is shown as evidence.

**Why this priority**: The method's parametric rules are cheap to evaluate once equations are in the IR, but they matter less than tree structure.

**Independent Test**: A part with two globals and three driven dimensions passes; a part with no equations yields the global-variables finding; a part whose equation manager could not be read yields unresolved coverage.

**Acceptance Scenarios**:

1. **Given** a part with no global variables, **When** the review runs, **Then** a `rms.params.global_variables_present` finding lists the equations found.
2. **Given** a part with globals but no dimension equations, **When** the review runs, **Then** a `rms.params.dimensions_driven_by_equations` finding at warning level appears.
3. **Given** the equation manager was unavailable, **When** the review runs, **Then** both rules are unresolved coverage for that part.

---

### User Story 4 - Engineer-Run Suppressibility Test (Priority: P4)

The method's rule that every Detail feature can be suppressed alone without rebuild errors requires suppressing, rebuilding, and unsuppressing features, which the read-only reviewer must never do. The engineer first asks the reviewer for a plan (the Detail content features of one part, decided by the same group and type tables the rules use), then runs a separate console command on that saved part, after acknowledging that it rebuilds the model. The command checks that the open document still matches the package, records the model's baseline rebuild-error count, snapshots the suppression state of the whole tree, tests each planned feature in turn, restores the tree to the snapshot after each one and verifies it, records per-feature results into the package, and tells the engineer to close the document without saving. The next review reports the results as `rms.detail.individually_suppressible` findings or checked coverage. Without results for a Detail feature the rule is unresolved for it.

**Why this priority**: It is the only rule that needs a mutation, and it is valuable; isolating it keeps the reviewer's read-only guarantee intact and keeps every folder, group, and content decision in the reviewer.

**Independent Test**: Plan and run the command on a part with one Detail feature whose suppression breaks a later feature: the command restores the tree, writes one `rebuild_errors` row and N `ok` rows, and the review shows one finding naming the feature and the rebuild errors; running it on an unsaved part, on a rolled-back part, on a part that already has rebuild errors, in another configuration, against a stale package, or without the acknowledgement flag is refused before anything is touched.

**Acceptance Scenarios**:

1. **Given** a plan, a saved part with no rolled-back feature and no rebuild errors, the same active configuration as the plan, a package that matches the open document, and the acknowledgement flag, **When** the command runs, **Then** each planned feature that is not already suppressed is suppressed, the model rebuilt, the rebuild error count and messages recorded against the baseline, and the whole tree restored to the snapshot and verified, and the command ends by saying the document is modified in memory and must be closed without saving.
2. **Given** a part with unsaved changes, a rolled-back feature, pre-existing rebuild errors, a different active configuration, or no acknowledgement flag, **When** the command runs, **Then** it refuses before touching anything, and the refusal for unsaved changes says that a previous suppress-test run leaves the document modified and it must be closed and reopened.
3. **Given** a suppression call that SOLIDWORKS refuses or does not apply, **When** it occurs, **Then** the row is `not_applied`, no rebuild is performed, and the review reports the feature unresolved.
4. **Given** an exception or a lost SOLIDWORKS session mid-test, **When** it occurs, **Then** the restore path still runs with the circuit breaker reset, every feature it could not restore is named on stderr and in the log, the command exits non-zero, and the partial results are recorded with the error.
5. **Given** results in the package, **When** the review runs, **Then** each `rebuild_errors` row is a finding, each `ok` row is checked coverage, each `already_suppressed` or `truncated` row is skipped coverage, each `not_applied` or `aborted` row is unresolved, and every Detail content feature without a row is unresolved; **Given** the run's restore could not be verified or its configuration differs from the review's, **Then** every row of that run is unresolved.
6. **Given** a package whose feature rows differ from the open document in count, order, names, types, depth, suppression state, or identity, **When** the command runs, **Then** it refuses and tells the engineer to dump again.

---

### User Story 5 - Accepted Exceptions and Advisory Rules (Priority: P5)

An engineer can accept a failing RMS finding as an exception with a reason, through the same exception mechanism the interference check uses (bound to the part's instances, its configuration, and a fingerprint of its feature tree and rule inputs), or import the checker's flat waiver file, which accepts every matching finding of the last run. An accepted finding is reported as checked within scope with the exception noted, never hidden; an exception whose feature tree or rule inputs have changed since is flagged for re-review and no longer silences anything; waiver rule ids that match no finding are reported as unused, and unknown or warning-level rule ids as invalid. The method's drawing rule and the judgement-only rules are listed in the review checklist as advisory and appear as out-of-scope coverage with the reason in this version.

**Why this priority**: Exceptions make the family usable on real models with deliberate deviations; advisory rules keep coverage honest about what the method asks that the tool cannot yet decide.

**Independent Test**: Accepting the `rms.core.shell_last` finding on one part turns the next review's result for that part into checked coverage carrying the exception id and reason; importing a waiver file naming that rule plus a rule that did not fail reports one accepted finding and one unused waiver; the drawing rule appears as out-of-scope coverage on every review.

**Acceptance Scenarios**:

1. **Given** an active exception for a rule on a part, **When** the review runs, **Then** the violation is reported as checked within scope with the exception id and reason in its coverage limits.
2. **Given** the part's feature tree or the rule's inputs changed since the exception was accepted, **When** the review runs, **Then** the finding stands and names the exception as needing re-review.
3. **Given** a waiver file naming a rule that did not fail, a warning-level rule, and an unknown rule id, **When** it is imported, **Then** the three are reported as `unused`, `invalid (warn rule)`, and `invalid (unknown rule)`, the import exits non-zero, nothing is written, and nothing is silently ignored.
4. **Given** any review, **When** it runs, **Then** `rms.drawing.model_items_preferred` and the five advisory rules appear once as `out_of_scope` coverage with their reasons.

---

### User Story 6 - Model Check Tab (Priority: P6)

An engineer with a part open in SOLIDWORKS presses **Model check** in the task pane and gets that part graded against the Resilient Modeling Strategy rules in seconds, with no language model, no API key, and no network. The tab extracts the open document with a reduced dump profile (features and equations only, no faces, holes, fasteners or meshes), runs the same rule evaluation the review and the command line run, and shows three stacked regions: a grade header (document, configuration, extraction timestamp, and the counts per bucket: failed, warned, checked, skipped, unresolved, out of scope, with the fraction secondary and the unresolved rule ids always named), a rule list grouped by bucket carrying each rule's id, its statement, the observed condition and the reason for a skip or an unresolved, and a per-subject line naming the feature with a **Show in SOLIDWORKS** button and its exception state. Accepting a rule records an exception with a required note, and that acceptance survives the next run even though the next run writes into a new folder. The tab is read-only: it is not a constitution exception and it adds no mutating call.

**Why this priority**: It is the fastest feedback loop the family can offer, it is the only surface where an engineer sees the rules while they are still modeling rather than at review time, and it is a hard prerequisite for feature 004, whose subject is always a part opened alone. A part opened alone currently dumps zero features, so without this story the whole family reports 34 unresolved rules on exactly the document type it was written for.

**Independent Test**: Open one part alone in SOLIDWORKS, press Model check, and confirm the package has a non-empty `features` array and every rule resolves to a real bucket; press Show on a failing rule's subject and confirm the feature is selected in the tree; accept one failing rule with a note; edit the part, press Model check again, and confirm the acceptance still applies and the new run wrote a new folder.

**Acceptance Scenarios**:

1. **Given** a part opened alone (no assembly), **When** the engineer presses Model check, **Then** the dump yields one component instance for the part root and that document's feature rows, and the part-scope and equation-scope rules are evaluated rather than reported unresolved for a missing tree.
2. **Given** a Model check run, **When** the dump runs, **Then** the document, manifest, mate, feature and equation phases run and the hole, fastener, face and body or mesh phases do not, and the package records `extractor.profile: "model_check"`.
3. **Given** a completed run, **When** the page renders, **Then** the grade header shows the count in every bucket and names every unresolved rule id, and no single letter and no single percentage stands alone as the headline.
4. **Given** the provider factories are unavailable (no API key, or monkeypatched to raise), **When** the check runs, **Then** it completes and produces the same result: no provider is ever constructed on this path.
5. **Given** a failing rule with feature subjects, **When** the engineer presses Show on a subject, **Then** that feature is selected in SOLIDWORKS and the view zooms to it; **Given** the subject resolves to a folder, **Then** it is selected in the feature tree, the view does not zoom, and the message says so.
6. **Given** the part is open inside an active assembly rather than alone, **When** the engineer presses Show, **Then** the selection is made in the active document through the component, and if the composition fails the component alone is selected and the reply is `ok: false` naming the feature that could not be reached; nothing silently selects nothing.
7. **Given** a part reached through more than one component instance, **When** the page renders a subject, **Then** the button reads "Show (instance 1 of N)" and clicking the label cycles to the next instance.
8. **Given** a failing rule of severity `fail`, **When** the engineer presses Accept, **Then** the button reads "Accept this rule for this part", a note is required, an empty note is refused, and the recorded exception is bound to the part's component instances, its configuration and its feature-tree fingerprint; **Given** a rule of severity `warn`, **Then** no Accept button is rendered at all.
9. **Given** a previous check or review run under the same run root whose package has the same `design_id`, **When** a new check run folder is created, **Then** that run's `exceptions.json` is copied into the new folder byte-identically before the rules run, so an acceptance made yesterday still silences the same rule today; **Given** no candidate exists, **Then** the run proceeds with no exceptions and says so; **Given** the newest candidate cannot be read, **Then** the run is refused rather than proceeding with an empty store.
10. **Given** a completed run, **When** `session.json` is written, **Then** every finding's `tool_result_ids` names a step that is actually in the file, and `report.md` cites no step that does not exist.
11. **Given** a `model_check` package, **When** it is handed to a review, **Then** the review records a coverage item naming the phases the profile skipped, the pane's evidence step reads "Evidence: model check only (features and equations)" and offers **Extract full evidence**, and `swreview check rms` refuses a package whose `features` array is empty rather than reporting 34 unresolved rules that read as a broken part.
12. **Given** no document is open, a document that is not a part, or a document the add-in is not attached to, **When** the engineer presses Model check, **Then** the tab refuses with the reason named and writes no run folder.
13. **Given** a feature named `<img src=x onerror=alert(1)>` or an observed string containing `</script>`, **When** the page renders it, **Then** it appears as text and executes nothing.
14. **Given** a check run folder, **When** it is created, **Then** it is registered as the pane's latest run so `entity.show` resolves `document_id` to a full path and the Ask (Terminal) tab opens in the same folder, and the host does not ask the backend about a chat id for a check record.

---

### Edge Cases

- A part with no group folders at all: every content feature is loose; one `rms.grouping.all_features_in_a_group` finding lists them; `rms.folders.present` warns; the per-group rules (shell last, holes last, drafts before patterns, the four Quarantine rules) are skipped with the reason "no <group> group".
- Group folders present but out of order, or with extra folders: `rms.folders.ordered` fails; a folder that is not a group is not a group, and its contents inherit the current group.
- A group folder nested inside another folder sets the current group exactly as a top-level one does.
- A group name appearing a second time re-opens that group and makes `rms.folders.ordered` fail naming both occurrences.
- Content features after a group's end-tag marker still belong to that group until the next group folder.
- End-tag markers are never content, never subjects, and never change the current group.
- A feature type the tables do not classify: listed with its raw type name; it is content, so it must be grouped and described; every rule that needs its class is unresolved for it; the type name is reported once per review with its count. Weldment cut-list folders, sheet-metal folders, flat-pattern features, and derived-part base features fall here until the workstation probe names them and they are added to the tables.
- A system row a real 2024 SP5 dump lists, above the first group or inside one - an annotation folder or view, a light, a derived part's body or reference folder, a cosmetic thread - is a tolerated type (*added 2026-09-25, the owner's decision 20A*): not content, so never loose, never asked for a description, and never named in `rms.types.unknown`. Only the eleven types the census of three real dumps found are tolerated this way (research R3); any other system type still falls under the previous case until a dump shows it.
- The type name `ICE` (reported for cuts and some bosses on newer versions): material of unknown kind. It counts as a solid-or-cut for `rms.groups.no_solids_in_ref_or_construction` and is unresolved for `rms.detail.holes_last`.
- Dependents unavailable (`GetChildren` returns nothing for a version): every reference rule and `rms.sketches.one_sketch_per_feature` unresolved with the gap named.
- A sketch with no consumer: passes `rms.sketches.one_sketch_per_feature` (the rule is about sharing) and is exempt from `rms.detail.no_internal_references`.
- A sketch consumed by two features: one finding naming the sketch and both consumers.
- A sketch with autosolve off: its status is unknown, so both sketch rules are unresolved for it.
- Fillet radius unreadable or variable: `rms.quarantine.largest_fillet_first` skips when fewer than two radii are readable and names the unreadable fillets.
- Suppressed features in the reviewed configuration: evaluated as present in the tree; every finding naming one carries "suppressed in <configuration>" in its observed text and coverage limits.
- A part used under two configurations in the assembly: the tree is dumped once in the configuration the document was loaded with; the other configurations are named in a gap and in every finding's coverage limits for that part.
- A part reached only through lightweight, suppressed, or unloaded components: no tree is read, and every part-scope and equation-scope rule is unresolved for it with the component state as the reason; a part with one resolved instance and one lightweight instance is evaluated normally.
- Assemblies containing subassemblies: part rules run on every part document once, not once per instance; the evaluable assembly rules run on the root assembly document only, and the subassembly documents are named in the `rms.assembly.subassemblies` unresolved item until their mates are extracted.
- A mate whose entity kind is unknown (the dumper's `unknown(<n>)` spelling, or a kind in neither list): the reference-geometry rule is unresolved for that mate.
- Several fixed components: the first fixed child of the root is the chain root; the others are named in the observed text.
- A component unreachable from the fixed root (no mates, or a disconnected mate graph): `rms.assembly.mate_chain_depth` is unresolved for it; suppressed mates are not edges.
- A component whose Toolbox identity could not be read (lightweight or suppressed): `rms.assembly.toolbox_parts_not_configurations` is unresolved for it.
- Waiver naming an unknown rule, a warning-level rule, or a rule that did not fail: reported as invalid or unused, never silently ignored.
- The suppressibility command aborted by SOLIDWORKS: the restore path runs with the breaker reset; unrestored features are named; rows are `aborted`.
- A feature already suppressed before the suppressibility test: skipped with an `already_suppressed` row; never unsuppressed by the restore pass.
- Suppressing a feature suppresses its dependents: the restore compares the whole tree against the snapshot, not just the tested feature.
- A part that already has rebuild errors before the suppressibility test: refused, naming the errors, because a rebuild-error row could not be attributed to the suppression.
- A plan whose feature is no longer a Detail content feature in the package the review reads: the row is ignored and reported as unused.

**Model check tab**

- A part opened alone: the component tree has exactly one node, the part root, and it carries that document's features. This is the tab's headline case and the case that is broken today.
- A genuinely empty part (a new document with no features): reported as an empty tree with that reason, never as 34 unresolved rules.
- Assembly scope in the tab: the first increment is part-only. An assembly open when Model check is pressed is reported as out of scope for the tab with the reason, and the assembly rules stay reachable through a review; the tab's assembly section is added when the assembly rules of User Story 2 have landed and been calibrated.
- A part with several component instances in the loaded assembly: the finding names every instance, and the Show button acts on one at a time and says which.
- A check run folder becoming the pane's latest run while the engineer also has a review open: the profile recorded in the package is what tells the review its evidence is partial, and the evidence step offers the full extract rather than silently reviewing a thin package.
- No `exceptions.json` candidate anywhere under the run root: not an error; the run says "no exceptions carried forward".
- A candidate `exceptions.json` that exists but cannot be parsed: the run is refused, because a silently empty store turns a waived rule back into a finding and, worse, turns a real finding into a waived one the next time the file is written.
- A candidate whose package has a different `design_id`: not copied, and the run says so.
- Folder proliferation: one folder per check, and a check is pressed after every edit. No automatic sweep of old check folders is built in this version; the run root grows and the engineer deletes folders by hand.
- The backend is not running (Python missing, port refused): the tab reports it and offers the log, the same way every other pane surface does. There is no second transport.
- A rule whose subjects include an end-tag marker or a folder: end-tag markers are never subjects, and a folder subject is selected without a zoom.

## Requirements *(mandatory)*

### Functional Requirements

**Extraction**

- **FR-001**: The extractor MUST dump, for every part document that is resolved in the reviewed configuration, its feature tree: name, type name, description, flat order, depth, enclosing folder, suppression state, error code, dependents (children), dependencies (parents) where available, raw constrained status and consumers for sketches, default radius for fillets, and the configuration the tree was read in, each feature with a persistent reference scoped to its document.
- **FR-002**: The extractor MUST dump each resolved part's equations with their text, left-hand side, the global-variable flag as SOLIDWORKS reports it, and their value.
- **FR-003**: The extractor MUST record a gap for every part where the tree, dependents, dependencies, sketch status, descriptions, fillet radii, or equations could not be read, naming what was unavailable, and MUST record a gap for every part reachable only through a lightweight, suppressed, or unloaded component instead of resolving it. The extractor MUST also record each root mate's suppression state and each component's raw constrained status.
- **FR-004**: The feature-tree and equation dump MUST be read-only; the extractor MUST NOT suppress, rebuild, resolve components, access feature definitions for editing, or otherwise change any document to obtain it.

**Rules**

- **FR-005**: The review MUST evaluate every part-scope and equation-scope rule in `contracts/rules.md` for every part document (reporting every rule unresolved, with the component state as the reason, for a part that no resolved component instance reaches) and every evaluable assembly-scope rule for the root assembly document, producing findings for failing and warning results, checked coverage for passing results, skipped coverage with a reason for results with nothing to evaluate, and unresolved coverage with a reason for results whose inputs are missing or ambiguous.
- **FR-006**: Group membership MUST follow the method's sticky semantics as written in `contracts/rules.md`: a feature belongs to the most recent group folder above it in the tree, features before the first group folder belong to no group, and end-tag markers never change the group.
- **FR-007**: Rule severities MUST map as: `fail` results to `demonstrated` findings, `warn` results to `suspected` findings, per the table in `data-model.md`; skipped and unresolved results MUST be coverage, never findings with a verdict.
- **FR-008**: Any rule whose inputs are missing, unreadable, or ambiguous for a feature, mate, or component MUST report unresolved for that subject rather than pass or fail it; an unknown or ambiguous feature type is never classified, though it is still content for the rules that need no class.
- **FR-009**: Rules whose data is not yet extracted (sibling in-context references, assembly global variables driving positions, mate descriptions, subassembly mates) MUST be recorded as unresolved coverage naming the missing data, once per review.
- **FR-010**: The type-name classification tables MUST be data in one file, MUST carry the SOLIDWORKS version they were calibrated against, MUST keep the class sets disjoint so every type name has at most one class, and MUST treat unlisted types as unknown and listed ambiguous types as material of unknown kind.
- **FR-011**: Every finding MUST name the rule id as its check, the part's component instances as its components, each subject feature or mate as an input string carrying its id, name, and persistent reference, the observed condition, the rule statement as its requirement, the recommended change, and the recording tool step as its tool result, and MUST carry the standard evidence fields of feature 001 without changing the feature 001 finding contract.
- **FR-012**: Coverage MUST be recorded per rule per bucket per review as one aggregated item naming the documents it covers and the per-document reasons, replaced rather than duplicated when a check tool runs again, plus one `modeling.resilience` summary item so the checklist item closes on a fully compliant package.

**Suppressibility test**

- **FR-013**: The reviewer MUST write a suppress-test plan for one part (its review configuration, Detail group, and Detail content features with persistent references) so the console command never decides folders, groups, or content. The console command MUST perform the suppressibility test only with an explicit acknowledgement flag, only on a saved document with no rolled-back feature and no pre-existing rebuild errors, only in the plan's configuration, only when the live feature walk matches the package's rows and every planned feature matches by persistent identity; MUST record the baseline rebuild-error count; MUST snapshot every feature's suppression state before the first mutation; MUST skip features already suppressed; MUST check that each suppression was applied before rebuilding; MUST count a rebuild as failed only when the error count exceeds the baseline; MUST restore the whole tree to the snapshot after every feature and verify it; MUST bound the run by a feature limit and a time limit; MUST write per-feature results into the package through the package appender; MUST write the distinct interop member names it called into its log; and MUST tell the engineer, on stdout and in its log, that the document is modified in memory and must be closed without saving.
- **FR-014**: The suppressibility command MUST be the only path that may suppress or rebuild. It MUST run under a guard that exempts exactly the suppression and rebuild members from the read-only denylist; the read-only guard MUST deny those members everywhere else, including the add-in, the bridge, the chat, and every other console command.
- **FR-015**: The review MUST report suppressibility results per feature as findings, checked, skipped, or unresolved coverage per the outcome table in `contracts/rules.md`, MUST report every Detail content feature without a result as unresolved, and MUST report every row of a run whose restore was not verified or whose configuration differs from the review's as unresolved.

**Exceptions and advisory rules**

- **FR-016**: A failing RMS finding MUST be acceptable as an exception through the existing exception store, bound to the part's component instances, configuration, and a fingerprint of its feature tree and rule inputs; an active exception turns the result into checked coverage carrying the exception id and reason; an exception whose fingerprint has changed is flagged for re-review and no longer silences the finding. Warning-level rules are not acceptable. Exception matching MUST be by check as well as by bindings, for every check.
- **FR-017**: The checker's flat waiver file MUST be importable against a review run, accepting every matching failing finding; unused, warning-level, and unknown rule ids MUST be reported, and an invalid id MUST make the import write nothing.
- **FR-018**: The review checklist MUST gain a modeling-resilience item covering the family, and the drawing and judgement-only rules MUST appear once per review as out-of-scope coverage with reasons.

**Surfaces**

- **FR-019**: The reviewer MUST expose feature listing, single-feature, and equation listing tools to the model and to general chat, and the part, assembly, and equation checks as review-only tools; the general-chat terminal profile and the MCP server MUST list the same tool set, checked by a test.
- **FR-020**: The command line MUST offer the family as a standalone check over a package with human and JSON output, a listing of type names the tables do not classify, the suppress-test plan, and the waiver import.

**Attribution**

- **FR-021**: The project MUST credit the Resilient Modeling Strategy and record the reuse of the checker's semantics with its author's permission before any reused semantics ship.

**Model check tab**

- **FR-022**: The extractor MUST support a reduced dump profile that runs the document, manifest, mate, feature and equation phases and skips the hole, fastener, face and body or mesh phases, selectable from the console command line and from the add-in, and the package MUST record which profile produced it (`extractor.profile`, optional with default `"full"`, IR 1.2.0, so 1.1.0 packages still load).
- **FR-023**: The component-tree dump MUST yield a root node for a part document opened alone, so that the part's feature rows are dumped. `IConfiguration.GetRootComponent3(false)` (verified present on the 2024 SP5 interop) is expected to return null for a part; the dumper MUST synthesize the part root from the document itself rather than emitting an empty tree, and the behavior on 2024 is recorded by the workstation probe rather than assumed.
- **FR-024**: There MUST be exactly one no-language-model evaluation entry point for the RMS rules, used by the command line and by the backend route alike. It MUST dispatch the check tools through the tool registry with a session sink, so every finding's recorded tool step exists in the session it cites, and it MUST NOT construct a provider, read an API key, or make a network call on any path.
- **FR-025**: The grade MUST be reported as counts per bucket with the unresolved rule ids named beside them; a fraction MAY be shown as a secondary number; a single letter grade MUST NOT be produced, and neither the fraction nor any other single number may stand alone as the result.
- **FR-026**: Every RMS finding MUST carry, for each subject, a structured reference the pane can act on without parsing a display string: a source reference carrying the subject's persistent reference and its scope on the finding, and a structured subject array beside the finding in the route's response carrying the feature id, name, type name, group, persistent reference and scope. The feature 001 finding contract MUST NOT change.
- **FR-027**: Selecting an entity MUST work when the feature's scope document is not the active document. The selection strategy MUST be a pure function of the scope document, the active document, the component and the resolved object, MUST select through the component when they differ, MUST select a folder without zooming, and MUST fall back to selecting the component alone and reporting `ok: false` naming the feature rather than selecting nothing silently.
- **FR-028**: Each check MUST write its own run folder with a `-check` suffix through the same run-folder helper the review and the terminal use, and that folder MUST be registered as the pane's latest run so entity resolution and the Ask tab read the same evidence. A check record MUST be distinguishable from a chat record so the host never asks the backend about a chat id that does not exist.
- **FR-029**: Accepted exceptions MUST survive the next run without the engineer copying a file: at run-folder creation the newest `exceptions.json` under the run root whose package carries the same `design_id` MUST be copied byte-identically into the new folder before the rules run. A missing candidate is not an error; an unreadable candidate MUST refuse the run.
- **FR-030**: The Accept control MUST state the granularity it has: an accepted exception waives a rule for a part, not for one feature. The label MUST say so, the note MUST be required, and the control MUST be absent (not disabled) for warning-level rules, which FR-016 already makes unacceptable.
- **FR-031**: The tab MUST NOT write to any document, MUST NOT register any tool, and MUST NOT change the MCP function list or the terminal profile's `enabled_tools`; the existing tests that pin those two lists MUST pass unedited.
- **FR-032**: The backend MUST expose the check as routes the page calls directly with the token and origin it already holds: start a check over a run directory, read a check's result, and accept an exception for one finding. The route set MUST obey the existing token, origin, run-root path and error-shape rules of the chat backend.
- **FR-033**: Both pages MUST render every untrusted string through one shared set of DOM helpers that insert text with `textContent`, served from the same virtual host, so the security rule exists in exactly one place.

### Key Entities

- **Feature**: One node of a part's feature tree with identity (id, persistent reference, document, configuration), raw classification inputs (type name, name, description), structure (index, depth, enclosing folder, dependents, dependencies), state (suppressed, error code), and rule data (raw sketch status and consumers, fillet radius).
- **Equation**: One equation of a part with its text, left-hand side, global-variable flag, and value.
- **Rule**: A registered check with a scope (part, assembly, equations, drawing, advisory), a severity for evaluable rules (`fail` or `warn`) and a coverage reason for the rest, a statement, and one result per outcome it reaches on a document, each naming its subjects.
- **Group Assignment**: The derived mapping of features to the six groups following sticky semantics, plus derived subfolders, the order, and duplicate observations.
- **Suppress-Test Plan**: The reviewer's list of Detail content features for one part, with configuration and persistent references.
- **Suppress-Test Run**: One run of the suppressibility command: plan, configuration, baseline error count, limits, restore verification, and one row per planned feature with its outcome.
- **Exception**: The existing review exception, extended with a feature-tree fingerprint kind.
- **Type Table**: The disjoint classification of type names into sketch, solid, cut, hole, fillet, chamfer, shell, draft, pattern, reference, and construction, plus ambiguous types, tolerated loose types, excluded default names, the constrained-status mapping, and the mate entity-kind lists, with the calibrated version. *Amended 2026-09-25 (owner decision 20A):* the tolerated loose types are one list, read by this feature's rules and by feature 004's planner alike; the table carries no second, planner-only list of types that are not content.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: On the fixture package seeded with one violation per reachable rule, every violated rule produces exactly one finding naming the right feature, every rule appears in at least one coverage bucket per document, and no rule is missing from coverage.
- **SC-002**: Extracting feature trees and equations adds under 20 seconds to the dump of a 200-component assembly on the pilot workstation, measured by timing the dump with and without the two phases.
- **SC-003**: Zero suppressions or rebuilds occur during a review or a dump, verified by the dumper and suppress-test unit tests asserting the recorded interop member names and by the add-in tool-service gate log for review-time calls; the suppressibility command never calls a save member, logs every member it did call, and leaves the file on disk unchanged.
- **SC-004**: Every unknown type name encountered is reported once per review with its count; no rule that needs a class passes or fails a feature whose class is unknown.
- **SC-005**: An engineer can accept a failing rule on a part, or import a waiver file, and see it reflected in the next review without any other change.
- **SC-006**: Feature 001 and 002 golden baselines remain byte-identical, except that `cover-blind-tap.yml` snapshots the review checklist and therefore gains exactly the new `modeling.resilience` checklist block and nothing else; the IR bump adds optional arrays and fields only.
- **SC-007**: A part opened alone and checked yields a package with a non-empty feature array, and no rule is unresolved for the reason "no features"; on the fixture part every part-scope and equation-scope rule lands in a bucket that reflects the part rather than the dump.
- **SC-008**: On the pilot workstation the Model check of a 150-feature part (extraction plus rule evaluation) completes in under 2 seconds, measured; the same measurement on the 200-component pilot assembly is recorded against the existing 20 second budget of SC-002, and the tab's speed claim in the user interface is scoped to parts.
- **SC-009**: Every subject of every finding on the fixture part has a Show button that either selects the entity or reports `ok: false` naming what it could not reach; no button reports success while selecting nothing.
- **SC-010**: An engineer accepts a failing rule with a note, edits the part, presses Model check again, and the rule is reported as checked within scope carrying the exception id, with no file copied by hand.
- **SC-011**: Zero providers are constructed and zero mutating interop members pass the gate during a check, asserted by the provider factories raising in the test and by the gate log of the check's dump.

## Assumptions

- Rule semantics follow the checker at commit `df49e6d` of `LifeDay/Solidworks-Resilient-Modeling-Skill`, reused with the author's permission granted to the project owner on 2026-09-15; the deliberate deviations are listed in `research.md` R2; the project asks the author to add an explicit license upstream.
- The checker was calibrated on SOLIDWORKS 2026 SP1.1. The interop member names and enum values the family relies on were verified on the 2024 SP5 interop on 2026-09-15 (`research.md` R5); their runtime behavior (folder traversal shape, `GetChildren` and `GetParents` content, type names of weldment and sheet-metal folders) is re-verified by the workstation probe before any rule is trusted on a real part.
- Group folder names default to `1-Ref`, `2-Construction`, `3-Core`, `4-Detail`, `5-Modify`, `6-Quarantine` and are configurable in the type table.
- The mate-chain depth limit defaults to 3 and is configurable in the type table.
- External references, assembly equations, mate descriptions, subassembly mates, drawing-owned versus model dimensions, and rollback state are not extracted by the dump in this version; the rules that need them stay unresolved or out of scope. The suppressibility command reads rollback state and the rebuild-error count itself to refuse unsuitable parts. A package produced by the reduced model-check profile also carries no faces, holes, fasteners, or meshes, and the profile it was produced with is recorded in the package so that a consumer can tell a partial extract from a complete one.
- The suppressibility command is run by an engineer on a saved part they choose, typically a copy; it never saves, and it leaves the document modified in memory.
