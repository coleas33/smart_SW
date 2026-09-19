# Feature Specification: Resilient Re-modeler

**Feature Branch**: `004-resilient-remodeler`

**Created**: 2026-09-16

**Status**: Draft (revision 1, written from the design brief of 2026-09-16 and the owner decisions of the same day)

**Input**: Owner description (the feature directory carried an unfilled template, so the input is the owner decisions recorded on 2026-09-16): "Resilient re-modeler: given one part, produce a copy that is measurably more resilient under the Resilient Modeling Strategy, with the geometry proven unchanged. The reviewer and the Model check stay read-only; the re-modeler works on a copy it creates in the run folder and never saves over an existing file. Version 1 is staged and only stage 1 ships: stage 1 reorganizes (groups, folders, descriptions, global variables, geometry proven unchanged); stage 2 rebuilds what blocks the rules and is re-specified after stage 1 has run on real parts. The run goes to completion and then presents the change list, the before-and-after RMS grade, and the geometry comparison; there is no approve-each-change mode. Parts only. OpenAI (default) and Gemini through the existing provider layer, never Claude. A part that already carries a group-named folder holding the wrong members is refused in version 1. Exceptions are copied forward into each new run folder for the same design. Vault parts are copied out into the run folder and never refused for vault reasons. The copy lives only in the run folder, and Discard keeps every artifact except the part file. The dry-run planner is built and run over real parts before any write code exists." Technical claims, the staged flow, the write guard, the geometry gate, the artifacts, the host messages, the risks, and the phased plan come from the design brief of 2026-09-16, which is the authority for every API claim marked VERIFIED or UNVERIFIED below. The Resilient Modeling Strategy rule vocabulary, the six group names, the type table, and the grade come from feature 003.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Reorganize a Part into the Six Groups with Geometry Proven Unchanged (Priority: P1)

An engineer with a part open presses **Remodel**. The re-modeler copies the part into a new run folder, opens the copy, and reorganizes the copy only: it renames features that share a name, writes a description on every content feature, reorders features into the order closest to the method's group order that the dependency graph actually allows, and wraps each group's contiguous run of features in its group folder (`1-Ref`, `2-Construction`, `3-Core`, `4-Detail`, `5-Modify`, `6-Quarantine`). Nothing is created, nothing is deleted, and no feature definition is edited. After every change the copy is rebuilt and its rebuild-error count is compared against the run's baseline; a change that raises it is undone and recorded as undone. At the end the copy's mass properties are compared against the copy's own baseline reading taken at open, which stands for the source because the copy is a byte-for-byte filesystem copy whose hash was recorded first (FR-037); the source is never opened. The copy is saved only if that comparison passes and the tree has no rebuild errors. The engineer's file is never opened for writing.

**Why this priority**: it is the feature. Everything else in this spec exists to make this one operation safe, legible, or repeatable.

**Independent Test**: run stage 1 over a part whose features already stand in the method's order but are unfoldered: the copy comes back with the six folders, the same feature order, zero rebuild errors, an identity-profile geometry verdict of `pass`, and a change list of six folder creations plus the descriptions. Run it over a part with three movable features and one feature pinned by a backward reference: three reorder changes are applied, the pinned feature is on the rebuild list with reason `backward_reference` and the blocking edge named, and the geometry verdict is still `pass`.

**Acceptance Scenarios**:

1. **Given** a part that passes preflight, **When** the run starts, **Then** a copy is created in the run folder by a filesystem copy that refuses to overwrite, the copy is opened at its own path, tagged with the run id, and every subsequent write targets that document and no other.
2. **Given** the copy is open and rolled forward, **When** the baseline rebuild reports any rebuild error, **Then** the run stops before any change is attempted and reports that the part was already broken, because nothing after that point could be attributed.
3. **Given** a plan whose achievable order differs from the current order, **When** the executor applies it, **Then** the reorder changes applied are the minimal edit script for that order, each one is recorded with its previous anchor and its inverse, and the feature count and the persistent identity of every feature are unchanged.
4. **Given** a group whose members are contiguous in the achievable order, **When** the executor reaches the folder step, **Then** exactly one folder is created around that run of features, named for the group, and its membership is verified after creation.
5. **Given** a group whose members cannot be made contiguous, **When** the plan is built, **Then** no folder is created for that group, every member is listed on the rebuild list with the interloper named, and the run continues with the groups that can be folded.
6. **Given** a change that raises the rebuild-error count above the baseline, **When** it is detected, **Then** the recorded inverse is applied, the inverse is confirmed to have restored the count, the change is recorded as `rolled_back`, and the run continues with the next change.
7. **Given** every change has been applied or rolled back, **When** verification runs, **Then** the copy is saved only when the rebuild-error count is zero, every feature reports no feature error, and the geometry verdict is `pass`; a verdict of `fail` or `unresolved` discards the copy, keeps every other artifact, and reports the reason.
8. **Given** the run has finished, **When** the source file is re-checked, **Then** its byte length, last-write time, and content hash equal the values recorded before the run started; any difference is a hard failure of the run and is reported as one.

---

### User Story 2 - The Dry-Run Plan Report (Priority: P2)

Before any part is copied and before any write code exists, an engineer can ask "how re-modelable is this part?" and get an answer. The planner reads an extracted package and reports, per part: how many content features reach their target group, how many are pinned and by which dependency edge, which groups come out non-contiguous and because of which interloper, and the rebuild list with one reason per entry. It opens no document, writes to no document, calls no language model, and needs no SOLIDWORKS seat.

**Why this priority**: the single largest unknown in this feature is whether a real part can be reorganized in place at all, because SOLIDWORKS will not reorder a feature past a dependency. This report converts that unknown into a number before the expensive half of the work starts, and it is a deliverable in its own right. It is delivered **first** in implementation order even though User Story 1 is the headline value; User Story 1 cannot be planned without it.

**Independent Test**: run the planner over the benchmark packages and three to five real parts and read the per-part numbers. A part already in the method's order yields zero moves; a part with no group-crossing dependency yields a full reorder; a part whose Detail features depend on each other yields a rebuild list naming the cycle. No SOLIDWORKS process is started in any of these runs.

**Acceptance Scenarios**:

1. **Given** an extracted package containing one part, **When** the planner runs, **Then** it reports per feature the target group and the basis for it, and per unplaced feature exactly one reason from the reason taxonomy.
2. **Given** a part whose features are already in the achievable order, **When** the planner runs, **Then** the plan contains zero reorder changes and the report says so, rather than restating the existing order as work.
3. **Given** a part whose dependency graph has a cycle across groups, **When** the planner runs, **Then** the planner names the cycle and refuses to produce an order for it, and never loops and never invents a position.
4. **Given** a part with a fillet whose radius could not be read, **When** the planner runs, **Then** that fillet is on the rebuild list with reason `radius_unreadable` and is never given an arbitrary position among the other fillets.
5. **Given** a package whose features array is empty, or whose dependents and dependencies are both unavailable, **When** the planner runs, **Then** it refuses with the gap named and reports unresolved, never an empty plan that reads as "nothing to do".
6. **Given** any planner run, **When** it finishes, **Then** the fraction of features that reached their target group is **reported as a measurement**, and no threshold on that fraction decides whether the run succeeded.

---

### User Story 3 - Descriptions and Global Variables Proposed by the Model, Applied by the Executor (Priority: P3)

The parts of the method that need judgement are the parts a language model is good at: what a feature is for, what a parameter should be called, and whether an ambiguous fillet is structural or cosmetic. The model is given the plan and a small set of proposal tools. It writes text and names into the plan. It never moves a feature, never decides an order, never rolls anything back, and never issues a verdict. A deterministic executor then applies the plan. Every proposal is validated before it enters the plan, and a rejected proposal comes back to the model as an error it can correct.

**Why this priority**: descriptions and named parameters are two of the method's rules and they are most of what an engineer reads afterwards, but they are worth little on a tree that is still disorganized, so they follow the reorganize slice.

**Independent Test**: run the judgement phase with a scripted provider that proposes one good description, one description equal to the feature name, one global with an illegal name, one global whose expression references an undeclared name, and one Quarantine classification for a fillet that has dependents. The plan gains exactly one description and zero globals; four proposals come back as errors; the run continues and finishes.

**Acceptance Scenarios**:

1. **Given** a content feature with no description, **When** the model proposes one between 1 and 200 characters that is not the feature's name or its type name and contains no newline, **Then** it enters the plan and the executor writes it to the copy.
2. **Given** a proposal that fails any of those checks, **When** it is made, **Then** it is rejected with the reason, nothing enters the plan, and the rejection is a tool error the model can act on rather than an exception that ends the run.
3. **Given** a global variable proposal, **When** its name does not match the documented naming rule, or it duplicates an existing global, or its expression does not parse over the declared globals and the documented function set, **Then** it is rejected and the report lists it as a rejected proposal.
4. **Given** an existing global whose name is uninformative or whose equation is broken, **When** the plan repairs it, **Then** the repair edits the equation in place and never deletes a global that other equations reference in order to change it, and the numeric text of a rename-only repair is carried across unchanged rather than recomputed.
5. **Given** a fillet the type table cannot classify as structural or cosmetic, **When** the run is non-interactive, **Then** it is assigned to `3-Core` by default, it is applied without blocking the run, and the report lists it under "reviewed as structural; move to `6-Quarantine` if cosmetic".
6. **Given** a feature whose type name the table does not classify, **When** the model classifies it into one of the six groups, **Then** the classification is recorded as a deviation with the model's rationale and is reported as a deviation rather than as a table result.
7. **Given** the provider factories are unavailable or raise, **When** the apply phase runs, **Then** the executor still applies the plan's deterministic changes, because no part of the executor constructs a provider.

---

### User Story 4 - The Run-to-Completion Report (Priority: P4)

The run is unattended. When it ends, the pane shows three things and one decision. The **change list** is every change attempted, in order, with its subject, its before state, its after state, and its outcome (`applied`, `failed`, `rolled_back`), each row able to select its feature in SOLIDWORKS. The **grade** is the rule result before and after, as counts per bucket with the unresolved rule ids named beside them, plus the per-rule delta; there is no letter and no single-percentage headline. The **geometry comparison** is the measured values before and after, the tolerance profile used, the verdict, and what that verdict cannot cover. The decision is **Open copy** or **Discard**; Discard closes the copy without saving and deletes the part file, and keeps every other artifact of the run.

**Why this priority**: the product is the report. A copy on disk that the engineer cannot audit is not an engineering result, and the constitution says a copy that rebuilds cleanly is a proposal, not an acceptance.

**Independent Test**: complete a run on a part with twelve planned changes of which one is rolled back, then read the pane: twelve change rows with one `rolled_back`, a grade delta naming every rule that moved and every rule that stayed unresolved, a geometry section with the verdict and the coverage statement, and both buttons live. Press Discard and confirm the part file is gone while the plan, the change log, the report, the grades, and the geometry readings remain.

**Acceptance Scenarios**:

1. **Given** a finished run, **When** the report is read, **Then** every attempted change appears exactly once with its outcome, and the count of applied changes in the report equals the count of applied records in the change log.
2. **Given** a run that hit the change limit, the wall-clock limit, or the rebuild-time limit, **When** it finalizes, **Then** it is reported as `truncated`, the report says how many planned changes were applied and which were not, and it is never reported as a completed run.
3. **Given** a run whose geometry verdict is `unresolved`, **When** the report is read, **Then** the verdict is shown as `unresolved` with the reason, the copy is not saved, and no wording in the report implies the geometry was verified.
4. **Given** a change row, **When** the engineer presses Show, **Then** the change's subject is selected in SOLIDWORKS through the same resolver the Review and Model check tabs use, and a failure to select reports a state and a message rather than doing nothing.
5. **Given** a finished run, **When** the engineer presses Open copy, **Then** the copy in the run folder is opened or activated, and it is the only file the pane offers to open.
6. **Given** a finished run, **When** the engineer presses Discard, **Then** the copy is closed without saving, only the part file is deleted, every other artifact remains, and the run stays readable in the report afterwards.
7. **Given** a run in which the model proposed items that were rejected, **When** the report is read, **Then** the rejected proposals are listed with their rejection reasons rather than omitted.

---

### User Story 5 - The Source Is Never Touched (Priority: P5)

The engineer's file is the thing that must not be lost. The re-modeler records the source's byte length, last-write time, and content hash before the run, copies it with a filesystem copy that refuses to overwrite, and never obtains a writable SOLIDWORKS handle to it. Every write goes through a guard that allows only the specific interface-qualified interop members the run needs, and re-verifies the target document's path, run tag, and COM identity immediately before each write. No command in the bridge protocol and no tool exposed to the model names a document. A part that the run cannot handle safely is refused before anything is copied, with every reason named.

**Why this priority**: it is last as an independently demonstrable slice, not last in importance. Nothing in User Story 1 may ship without it, and the constitution amendment this feature carries exists to state exactly this boundary.

**Independent Test**: with fakes and no SOLIDWORKS, drive the guard and the document scope through their whole refusal table: a save path outside the run folder, a path containing `..`, the source path, another run's copy, a non-part extension, a changed run tag mid-run, a changed document path, a changed COM identity, and every interop member not on the allowlist. Each is refused, each names which check failed, and the happy path calls exactly the expected member sequence in order.

**Acceptance Scenarios**:

1. **Given** any run, **When** a write is attempted against a document that is not this run's copy, **Then** the write is refused by the guard before it reaches SOLIDWORKS and the run aborts with the change log intact.
2. **Given** any run, **When** a save is attempted, **Then** only the save member that takes no filename is permitted, the save-target assertion refuses any other path, and no save-as member is on the allowlist at all.
3. **Given** a source part that is open with unsaved changes, that has external file references, that is not a part, or that fails any scope signal, **When** the run is requested, **Then** it is refused before the copy is made and the refusal names every failing reason, not just the first.
4. **Given** a part that already carries a folder named for one of the six groups but holding members that do not belong to that group, **When** the run is requested, **Then** it is refused in this version with that folder and its unexpected members named, because deleting a folder is not in this version's write surface.
5. **Given** a run in progress, **When** a second run is requested on the same add-in instance, **Then** it is refused with a run-in-progress error and the first run is unaffected.
6. **Given** SOLIDWORKS dies mid-run, **When** the add-in recovers, **Then** the copy and the change log survive on disk, the system toggles the run changed are restored, and the run is **not** auto-resumed; resuming is refused and the recovery path is documented.
7. **Given** the engineer edits or closes the copy while a run is in progress, **When** the next write is attempted, **Then** the target verification fails, the change is abandoned, and the run aborts with the log intact.

---

### Edge Cases

**Preflight and scope**

- The source is not a part (an assembly, a drawing): refused before anything is copied.
- The source is open in SOLIDWORKS with unsaved changes: refused; the message says to save or close it first, because the copy on disk would not be the model the engineer is looking at.
- The source has external file references: refused; an in-context or derived part cannot be reorganized in isolation.
- More than one solid body: refused; the geometry gate cannot pair bodies within one reading unambiguously.
- Weldment, a sheet-metal folder present, a mesh or graphics body, or a 3D Interconnect feature: refused, each with its own reason, because the six groups do not model bends, K-factor, or flat patterns, a mesh body has no boundary representation to compare, and editing a 3D Interconnect part fights the live link.
- An imported dumb solid with no editable feature history: allowed, and the reorganize stage is reported as a no-op rather than as a success.
- Surface bodies present alongside the single solid: allowed, and the geometry gate reports its coverage of those bodies as **uncovered**, never as passed.
- More than one configuration: allowed; the count and the active configuration are recorded, and they decide the configuration scope of every equation written.
- A part in an EPDM vault: copied out into the run folder like any other part and never refused for vault reasons; the vault path and the revision are recorded in the plan.
- Two failing scope signals at once: the refusal message names both.
- The part already has rebuild errors before any change: the run stops after the baseline rebuild, because a later error could not be attributed to any change.
- A group-named folder holding the wrong members: refused in this version (User Story 5, scenario 4).
- A correct existing group folder: a no-op, not a re-creation. A derived subfolder inside a group is preserved and never dissolved.
- The copy cannot be made because SOLIDWORKS holds the file open: the copy is retried through a shared-read stream copy before the run is refused (PROBE-13).

**Planning**

- Two features share a name: the name-addressed reorder (`IModelDocExtension.ReorderFeature`, VERIFIED, takes feature and target **names**) is then ambiguous and SOLIDWORKS reports no error for it, so the planner either renames one first as a recorded, reversible change, or puts both on the rebuild list with reason `ambiguous_name`.
- A feature whose type name is not in the type table: `unclassified`; it is reported as unresolved and is never treated as movable.
- Dependents and dependencies both unavailable for a feature: `graph_unreadable`; the planner never moves a feature on an unknown graph.
- A sketch consumed by two features: `shared_sketch`; it can be contiguous with only one of them.
- A sketch with no consumer: it is not pinned by a consumer, and it is placed by its own class rather than by a consumer that does not exist.
- A feature that sits inside another group's span in the achievable order: `splits_group`, with the span named.
- A parent in a later group than its child: `backward_reference`, with the blocking edge named.
- A cycle in the condensed group graph: `cycle`, with the cycle named; the planner refuses an order rather than choosing one.
- A fillet whose default radius is unreadable, for example a variable-radius fillet: `radius_unreadable`; it is never ranked by a guessed radius.
- A part where the reorganizable fraction is small: reported as the honest first line of the report ("this part needs rebuilding"), never as a successful reorganization of three features out of two hundred.

**Applying changes**

- The order of operations is fixed and is itself a requirement: duplicate-name renames, then descriptions, then reorders, then folder creation, then in-place global repairs, then new globals. This version renames no dimension, so the rule that a dimension rename must precede every equation (renaming one afterwards breaks that equation, and the break is not recoverable by retrying) governs the later dimensions feature and is implemented by nothing here.
- A global variable that other equations reference is never deleted in order to change it; the equation is edited in place, because while the global is missing the dependent equations enter an error state that does not clear when the global returns.
- An equation add that reports success but adds nothing: the add is believed only when the equation count increments **and** the equation reads back; otherwise the documented fallback overload is tried, and a second failure fails the change (`IEquationMgr.Add3` and `Add2`, both VERIFIED present; whether `Add3` works on 2024 is UNVERIFIED, PROBE-6).
- The number in an equation is in the **document's** length unit, not metres, which is the opposite of the dimension value read from the API. A part in millimetres takes `120` for 120 mm. Getting this backwards produces a 120-metre part that rebuilds cleanly and passes every non-geometric check, so every value written is read back and compared at the document's stored precision, and a regression test pins that a 120 mm dimension never produces `0.12` (the unit the equation manager reports a value in is UNVERIFIED and blocking, PROBE-2).
- A reorder the dependency graph said was legal that SOLIDWORKS refuses anyway: the refusal is a contract violation, not a retry condition. The call returns a bare false with no code and no reason, so the run logs it, discards the copy, and stops. It never searches for another position.
- A folder creation that fails or raises the rebuild-error count: this version has no forward inverse for a folder creation, because folder deletion is not on the write surface. The run falls back to the recorded catastrophic path (delete the copy, re-copy the source, replay the applied changes up to that point) or, where that is refused, discards the copy and reports.
- A persistent reference that stops resolving after a change: the change is recorded as failed with "could not be addressed after change N", and the run aborts rather than addressing anything by name or by index.
- A limit reached mid-change: the change in flight finishes or is rolled back before the run finalizes; a limit never leaves a change half-applied and never reports a silent partial success.
- A hard crash between the two log lines of one change: the log carries an `attempting` line naming exactly what was in flight.
- The four system toggles the run changes (dimension value on create, show errors every rebuild, warn on save update errors, and the command-in-progress flag) are recorded and restored in a `finally`, including after a crashed previous run, because leaving the first of them on turns every dimension call into a modal dialog, and a modal dialog on the add-in's thread is a hang, not an error (UNVERIFIED that the command-in-progress flag suppresses the reorder refusal dialog, PROBE-1, blocking).
- The group-folder end marker keeps the folder's default name after a rename, so nothing in this feature matches a folder by its name where the marker is the reliable signal (PROBE-10).

**The gate and the report**

- A copy whose mass properties match but whose face count differs: a failure under this version's profile, because stage 1 creates no geometry and any measured difference is a defect.
- A mass difference with no volume difference: reported as a material change, never as a geometry change.
- A mass-properties reading whose status is not OK, or a baseline reading whose solid body count is not one: `unresolved`, never `pass`.
- A zero-volume baseline reading: `unresolved`, never a divide-by-zero.
- Principal moments returned in a different order: compared after sorting, so a permutation is a `pass`.
- The gate cannot detect a reflection, a rigid rotation about a symmetry axis, compensating add and remove pairs, or any difference occupying no volume (split faces, cosmetic threads, material, custom properties, configuration data), and it does not cover surface or wire bodies. Every one of these is stated in the report's coverage section on every run.
- The source attestation differs at report time: a hard failure of the run, reported as such, however well everything else went.
- A run whose grade got worse: reported as it is. The report never suppresses a negative delta.

## Requirements *(mandatory)*

### Functional Requirements

**Preflight and the copy**

- **FR-001**: The system MUST refuse a run, before any copy is made and before any SOLIDWORKS document handle to the source exists, when the source is not a part file, when the open source document has unsaved changes, when the source has any external file reference, or when any scope signal fails (more than one solid body, weldment, sheet-metal folder present, mesh or graphics body, 3D Interconnect feature). A refusal MUST name every failing reason, not the first one found, and MUST be reported as a coverage gap rather than a silent skip. The scope signals MUST be read from the source document the engineer already has open, through read members only, with no write-guarded call and no writable handle; a request made when the source is not open MUST be refused rather than answered by opening it. Pre-existing rebuild errors are the one preflight reading that cannot be taken this way, because it requires a rollback and a rebuild; it is therefore taken on the copy (FR-004) and its refusal deletes the copy.
- **FR-002**: The system MUST record the source file's path, byte length, last-write time, and content hash before the run starts, MUST re-check all three when the run reports, and MUST treat any difference as a hard failure of the run.
- **FR-003**: The system MUST create the working copy with a filesystem copy that refuses to overwrite, into this run's folder, before any document handle exists; MUST open the copy at its own path, not read-only and not view-only; MUST assert the opened document's path equals the copy path and differs from the source path; and MUST tag the copy with this run's id as a custom property that is read back after it is written (`ICustomPropertyManager.Add3` and `Get4`, VERIFIED present; the round trip on 2024 is UNVERIFIED and blocking, PROBE-12, because the tag is one of the four target checks).
- **FR-004**: The system MUST roll the copy forward to the end of its tree and assert no feature remains rolled back, MUST rebuild the copy, and MUST stop the run before any change when the resulting rebuild-error count is not zero, reporting that the part was already broken. This is the one refusal taken after the copy exists, so it MUST delete the copy and close the document before it reports.
- **FR-005**: The system MUST record and set the system toggles the run depends on, and MUST restore every one of them in a `finally`, including on the recovery path of a previous crashed run. Suppression of the reorder refusal message box is UNVERIFIED and blocking (PROBE-1); if it is not suppressed, stage 1 MUST NOT run unattended.
- **FR-006**: A part stored in a vault MUST be copied out into the run folder like any other part and MUST NOT be refused for vault reasons; its vault path and revision MUST be recorded in the plan.
- **FR-007**: The system MUST refuse, in this version, a part that carries a folder named for one of the six groups whose members do not match that group, naming the folder and the unexpected members, because folder deletion is not in this version's write surface. This refusal is decided from the same read-only scope probe as FR-001 and therefore happens before the copy is made.
- **FR-008**: The working copy MUST live only in this run's folder. The system MUST NOT write a copy beside the source or anywhere else.

**Planning**

- **FR-009**: The planner MUST be a pure function of an extracted package: it MUST open no document, write to no document, call no language model, and require no SOLIDWORKS seat, and it MUST be runnable as a standalone dry run over a package with human and JSON output.
- **FR-010**: The planner MUST assign each content feature a target group from the same classification data the checks use, so the checker and the planner cannot disagree about what the target is, and MUST record the basis of each assignment. A feature the data cannot classify MUST be reported unresolved and MUST NOT be treated as movable.
- **FR-011**: The planner MUST produce the legal order closest to the method's order, respecting every dependency edge, and MUST reduce it to the minimal set of moves that reaches it, so a 200-feature part is not moved 200 times to achieve 30 moves.
- **FR-012**: The planner MUST decide the legality of every move from the dependency graph **before** any move is attempted; a move refused by SOLIDWORKS that the planner had ruled legal MUST be treated as a contract violation that stops the run, never as a condition to retry or to search around.
- **FR-013**: The planner MUST assert feature-name uniqueness across the whole tree as a precondition of any name-addressed reorder, MUST plan a recorded, reversible rename for a duplicate it can repair, and MUST place both features on the rebuild list with reason `ambiguous_name` where it cannot.
- **FR-014**: The planner MUST produce a rebuild list in which every feature that could not be reorganized carries exactly one reason from the taxonomy `backward_reference`, `shared_sketch`, `splits_group`, `cycle`, `radius_unreadable`, `ambiguous_name`, `unclassified`, `graph_unreadable`, together with the blocking edge, interloper, span, or cycle that produced it.
- **FR-015**: The planner MUST plan a folder only for a group whose members are contiguous in the achievable order, MUST treat an already correct group folder as a no-op, and MUST preserve a derived subfolder inside a group. Whether folders require contiguous members on 2024 is UNVERIFIED and blocking (PROBE-4).
- **FR-016**: The plan MUST be a versioned, persisted artifact carrying the source attestation, the scope signals, the configuration count and active configuration, the vault path and revision where they apply, the target assignments with their bases, the achievable order, the ordered change list, the folder plan, the rebuild list, the deviations, and the rejected proposals.

**Judgement proposed by the model**

- **FR-017**: The language model MUST be able to propose only a description for a feature, a global variable with its expression and rationale, a group for an ambiguous fillet, and a group for an unclassified feature, plus a read-back of the plan. It MUST NOT decide an order, a move, a rollback, a save, or a verdict, and it MUST NOT hold any tool that reaches a document.
- **FR-018**: Every proposal MUST be validated before it enters the plan: a description MUST name an existing content feature, be 1 to 200 characters, contain no newline, and differ from the feature's name and its type name; a global MUST match the documented naming rule, be unique, not duplicate an existing global, and have an expression that parses over the declared globals and the documented function set with its documented angular unit; a fillet decision MUST classify a fillet, MUST choose `3-Core` or `6-Quarantine`, and MUST NOT put a fillet with dependents into `6-Quarantine`. A rejected proposal MUST return an error the model can act on and MUST NOT raise or end the run.
- **FR-019**: A fillet the data cannot classify as structural or cosmetic MUST default to `3-Core`, MUST NOT block the run, and MUST be listed in the report as reviewed as structural, with the note that it should move to `6-Quarantine` if it is cosmetic.
- **FR-020**: A group assigned to an unclassified feature by the model MUST be recorded as a deviation with the rationale and reported as a deviation, never as a table result.
- **FR-021**: The model MUST be reached through the existing provider layer with OpenAI as the default and Gemini as the alternative. No part of this feature may use or require Claude, and no part of the executor may construct a provider.

**The executor and its limits**

- **FR-022**: The executor MUST apply the plan deterministically in a fixed order: duplicate-name renames, then descriptions, then reorders, then folder creation, then equations. It MUST NOT reorder these phases. This version renames no dimension, because dimensions are not in the intermediate representation (FR-030); the rename-before-equations rule that a later dimensions feature will need is recorded in the research and is not implemented here.
- **FR-023**: The executor MUST write one record per attempted change **before** the call, naming the change kind, its subject by persistent reference, and its before state, and a second record after the call carrying the after state, the rebuild-error counts either side, the outcome, and the elapsed time. The log MUST be append-only, so a crash mid-change leaves a record naming exactly what was in flight.
- **FR-024**: Every change kind the executor applies MUST carry an exact inverse derived by a pure function from the change record. Where a change kind has no forward inverse in this version (folder creation, because folder deletion is not on the write surface), the executor MUST fall back to the recorded catastrophic path (delete the copy, re-copy the source, replay the applied changes) or, failing that, discard the copy and report; it MUST NOT leave such a change in place and continue. A description whose previous text was unreadable MUST be refused before it is attempted, because it has no inverse.
- **FR-025**: The executor MUST rebuild after every change and compare the rebuild-error count against the run's baseline; a change that raises it MUST be undone, the undo MUST be confirmed to have restored the count, the change MUST be recorded as rolled back, and the run MUST continue with the next change. The per-feature error code walk is the primary reading of rebuild errors and the whole-document error list is corroborating, because the element shape of that list on 2024 is UNVERIFIED (PROBE-9).
- **FR-026**: The executor MUST enforce a maximum change count, a maximum wall-clock duration, and a maximum rebuild duration. Reaching any of them MUST finalize the run as `truncated`, reporting how many planned changes were applied and which were not. The limits MUST be enforced by the executor and MUST NOT be enforced by, or negotiable by, the model.
- **FR-027**: Every value written into an equation MUST follow the documented unit sequence: read the value in metres from the feature data the package carries, convert it to the document's length unit, seed the equation with that exact value, assert the equation landed and evaluated, rebuild, re-read the equation's value, and assert equality at the document's stored precision rather than at a loose epsilon. A document whose length unit cannot be read MUST refuse the change rather than assume metres.
- **FR-028**: An equation add MUST be believed only when the equation count increments and the equation reads back; on failure the documented fallback overload MUST be tried and asserted again, and a second failure MUST fail the change. This assertion MUST live in one helper and MUST NOT be repeated at any call site.
- **FR-029**: The executor MUST repair an existing global by editing its equation in place. It MUST NOT delete a global that other equations reference in order to change it, and a rename-only repair MUST carry the existing numeric text across unchanged rather than recomputing it.
- **FR-030**: This version MUST NOT create a new equation that drives a sketch dimension, and MUST NOT rename a dimension, because the intermediate representation carries no dimensions in this version and an equation that drives a dimension the planner never saw is the units trap with no evidence behind it. Global variables added from feature data, and repairs to existing equations, are in scope; nothing in this version is rewired to a newly added global, so a new global names a value and drives nothing. Extracting dimensions is a separate later feature, and the report MUST say that the added globals drive nothing yet and which values remain hard-coded, rather than implying the part is parameterized.
- **FR-031**: The run MUST NOT auto-resume after a lost SOLIDWORKS session. The copy and the change log MUST survive on disk, the toggles MUST be restored, and a resume request MUST be refused.
- **FR-032**: The system MUST allow one remodel run per add-in instance and MUST refuse a second with a run-in-progress error of the same shape the product already uses for a busy turn.

**The geometry gate**

- **FR-033**: Geometric equivalence MUST be measured in the process that owns the API and decided by a pure function whose inputs are two readings and a named tolerance profile, so the verdict is testable without a SOLIDWORKS seat.
- **FR-034**: The verdict MUST be `pass`, `fail`, or `unresolved`, never a boolean, and MUST NOT be inferred from a successful rebuild.
- **FR-035**: The comparison MUST cover volume, surface area, centre of mass, principal moments compared after sorting, solid body count, face count, and edge count. Mass MUST be compared separately, and a mass-only difference MUST be reported as a material change, never as a geometry change.
- **FR-036**: Stage 1 MUST use the identity tolerance profile, under which any measured difference is a failure, because stage 1 creates no geometry. No tolerance profile may ship until its attained error has been measured against a part of exactly known analytic volume and recorded (PROBE-8, blocking for shipping the gate).
- **FR-037**: The baseline reading MUST be taken from the copy at open, before any change, and the final reading from the same copy after the last change. The source file MUST NOT be opened for the comparison, in any mode, and no reference body MUST be inserted into the copy's tree. The baseline reading is a reading of the source's geometry because the copy is a byte-for-byte filesystem copy whose content hash is recorded (FR-002) before any document handle exists, and the report MUST cite that hash as the reason the baseline stands in for the source.
- **FR-038**: Every run's report MUST state what the gate cannot detect (a reflection, a rigid rotation about a symmetry axis, compensating add and remove pairs, any difference occupying no volume, and surface or wire bodies) as coverage, not as a caveat that may be dropped.
- **FR-039**: The copy MUST be saved only after the tree has zero rebuild errors, every feature reports no feature error, and the verdict is `pass`. A save that reports an error MUST fail the run; a save that reports a rebuild-error warning MUST fail the run and MUST say that an artifact was nevertheless written.

**Run artifacts**

- **FR-040**: Each run MUST write, into one run folder created by the existing run-folder helper: the working copy, the plan, the append-only change log, the before and after extracted packages, the before and after rule results, the before and after grades with the per-rule delta, the geometry readings with the verdict, the source attestation, the engineer-facing report, the agent run's events and session, and a request log carrying, per request, the command, the elapsed time, the guarded members, and the **target path**.
- **FR-041**: The report MUST state, from the request log rather than from intent, that every write of the run went to the copy's path.
- **FR-042**: Accepted rule exceptions MUST be carried forward into each new run folder for the same design, copied from the newest same-design run before the run's rules are evaluated; the copy MUST be byte-identical, a design mismatch MUST mean not copied, no candidate MUST NOT be an error, and a candidate that cannot be read MUST be a refusal rather than a silently empty exception set.
- **FR-043**: The grade MUST be reported as counts per bucket with the unresolved rule ids named beside them and the per-rule delta; it MUST NOT be reduced to a letter or to a single-percentage headline.

**The pane**

- **FR-044**: The task pane MUST present the tabs Review, Ask, Extract, Model check, and Remodel, with a step strip above them. Remodel is the fifth tab and its view MUST be created lazily on first activation rather than at add-in load.
- **FR-045**: The pane MUST run the plan phase and the apply phase to completion without asking the engineer to approve individual changes, MUST report progress and the change list as it grows, and MUST offer a stop that finishes or rolls back the change in flight and then finalizes the run.
- **FR-046**: The pane MUST offer, after a run, exactly two dispositions: open the copy, or discard it. Discard MUST close the copy without saving and delete only the part file, keeping every other artifact of the run.
- **FR-047**: A change row MUST be able to select its subject in SOLIDWORKS through the same selection strategy and resolver the Review and Model check tabs use, and MUST report a state and a message when selection is not possible rather than appearing to do nothing.
- **FR-048**: Every string that came from a document, from a model proposal, or from a rule result MUST reach the page through the shared rendering helpers that insert text as text, so a feature named with markup renders as text and executes nothing.
- **FR-049**: The pane's host MUST own only its own messages and MUST delegate report, folder, log, and entity actions to the shared pane actions extracted in feature 003, with run-root containment and redaction unchanged. If the copy is closed or replaced mid-run, the run MUST abort.

**The write guard and the constitution**

- **FR-050**: Writes MUST pass an **allowlist** guard whose keys are interface-qualified member names, because bare member names collide across interfaces; anything not on the allowlist MUST fall through to the existing read-only denylist unchanged. The stage-1 allowlist MUST be exactly the members the stage-1 flow needs and MUST NOT include any save-as member, any suppression member, any undo or redo member, any undo-recording member, any feature-creation member, the save-flag member, the read-only-state member, or the folder-delete member.
- **FR-051**: Every write MUST be preceded, on every call and not once per run, by a verification that the target document's path is this run's copy, its run tag is this run's id, its COM identity is the same object the run opened, and its path is a canonicalized descendant of this run's folder. Any failure MUST abort the run naming which check failed, with the change log intact.
- **FR-052**: No command in the bridge protocol and no tool exposed to the model may take a document as a parameter; the run's copy MUST be the only reachable target, so the target is unreachable rather than validated. Every subject MUST be addressed by persistent reference, never by name and never by index, and a name-addressed API call MUST resolve the reference to a name immediately before the call.
- **FR-053**: The remodel commands MUST be authorized by their own bounded secret; the general-chat authorization MUST authorize none of them; and a test MUST assert that the remodel commands appear in neither the model-facing tool list nor the terminal profile's enabled tools.
- **FR-054**: The exact interop surface the re-modeler calls (interface, member, arity, ordered parameter names, return type) MUST be frozen as a checked-in fixture, with one test that the code's calls match the fixture and one test, skipped where the interop assembly is absent, that regenerates the fixture from the installed assembly and diffs it, so a SOLIDWORKS upgrade is a failed build rather than a runtime surprise.
- **FR-055**: The constitution MUST be amended, before this feature's write code ships, to state the read-only rule explicitly and to record this feature's bounded exception under it: the re-modeler MAY create and modify exactly one document, a copy it created during this session, and no other; it MUST NOT save over a file that already existed; writes go through a document-scoped allowlist guard; every applied change carries its inverse and a change that raises the rebuild-error count is undone; the run is bounded and a truncated run says so; the model proposes and a deterministic executor applies; and geometric equivalence is reported as `pass`, `fail`, or `unresolved`.

**Attribution**

- **FR-056**: The report MUST credit the Resilient Modeling Strategy as the source of the rules and the group vocabulary, MUST record the provider and the model that produced each judgement item, and MUST state that the copy is a proposal the engineer accepts or discards, not an engineering acceptance result.

### Out of Scope for This Version

Stage 2, the rebuild stage, does **not** ship in this version. It is re-specified after stage 1 has run on real parts, with the numbers from those runs in hand. What this version keeps so that stage 2 is an addition rather than a rewrite:

| Kept in stage 1 | So that stage 2 |
|---|---|
| The tri-state geometry verdict (`pass`, `fail`, `unresolved`) | adds a tier, not a new type |
| The named tolerance profile as a parameter of the pure decision function | adds an equivalence profile beside the identity profile |
| The rebuild list with exactly one reason per entry | has its input; stage 2 acts on exactly this list |
| The allowlist guard with interface-qualified keys | gets a second, additive allowlist reviewed on its own |
| The per-change record with a derived inverse and the append-only log | records created features the same way |
| The frozen interop-surface fixture | extends to the creation members |
| The report's coverage statement of what the gate cannot detect | states there why the boolean tier became mandatory |

Also out of scope in this version: assemblies, drawings, in-context and derived parts, multibody, sheet metal, weldments, mesh and graphics bodies, and 3D Interconnect, all refused at preflight; turning a literal sketch dimension into a named parameter, because the intermediate representation carries no dimensions and a separate feature extracts them; any interactive approve-each-change mode; a single-letter grade; dissolving or deleting any folder; and any write to the engineer's file for any reason.

**Back burner (owner decision 2026-09-19):** modelling a STEP or other dumb-solid import with the method. A native part carries a tree to repair; an import carries none, so that path needs feature recognition first (SOLIDWORKS FeatureWorks on a Professional or Premium seat, or a recogniser of our own) before stage 1 has anything to restructure. The re-modeler continues on SOLIDWORKS files only: the Phase 2 probes and the Phase 9 bring-up of this feature, then stage 2 and assemblies re-specified with those numbers. The import path is reopened only by the owner.

### Key Entities

- **Run**: one remodel attempt: its id, its folder, the source attestation, the scope signals, the configuration count and active configuration, the limits, the toggles it changed, the phases it completed, and its outcome (`completed`, `truncated`, `failed`, `discarded`).
- **Copy**: the working part file created in the run folder, its path and its run tag, and the fact that it is the only document any write of this run may reach.
- **Source Attestation**: the source's path, byte length, last-write time, and content hash, recorded before the run and re-checked at report time.
- **Scope Signals**: the measured facts preflight decides on (solid body count, weldment, sheet-metal folder, mesh or graphics body, 3D Interconnect, imported body, surface bodies, configuration names, external reference count) and the refusal reasons derived from them.
- **Target Assignment**: one feature's target group, the basis for it (type table class, sketch follows its consumer, model judgement), and whether it is resolved, needs judgement, or is not content.
- **Remodel Plan**: the versioned plan: the attestation, the scope signals, the target assignments, the achievable order, the ordered changes, the folder plan, the proposed descriptions and globals, the rebuild list, the deviations, and the rejected proposals.
- **Rebuild List Entry**: one feature that could not be reorganized, its single reason from the taxonomy, and the blocking edge, interloper, span, or cycle behind it.
- **Change Record**: one attempted change: sequence, kind, subject by persistent reference, before state, after state, the derived inverse, the rebuild-error counts either side, the outcome, the stable error code and its prose when it failed, the target path the write was verified against, and the elapsed time.
- **Geometry Reading**: one measurement of the copy, at open or at the end of the run, carrying volume, surface area, centre of mass, sorted principal moments, mass, solid body count, face count, and edge count, with the measurement status.
- **Tolerance Profile**: a named set of per-quantity bounds with its calibration record.
- **Gate Result**: the verdict, the per-quantity comparison, the profile used, and the coverage statement of what the gate cannot detect.
- **RMS Grade**: counts per bucket before and after, the per-rule delta, and the unresolved rule ids, reused unchanged from feature 003.
- **Proposal**: one model-authored description, global, or classification, with its rationale, its validation outcome, and the provider and model that produced it.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Across every run in the acceptance suite, including refused, failed, truncated, aborted, and discarded runs, the source file's byte length, last-write time, and content hash are unchanged, verified by the run's own attestation and by tests asserting that no write member was ever called against a path other than the copy's.
- **SC-002**: No copy is saved unless the tree has zero rebuild errors, every feature reports no feature error, and the geometry verdict is `pass`; a run whose verdict is `fail` or `unresolved` leaves no saved part file and says why.
- **SC-003**: The dry-run planner reports, for every benchmark package and for three to five real parts, the fraction of content features that reach their target group, the pinned features with their blocking edges, the non-contiguous groups with their interlopers, and the rebuild list. That fraction is **reported as a measurement and is not a pass threshold**; no success criterion of this feature depends on its value.
- **SC-004**: Every feature that is not reorganized carries exactly one reason from the taxonomy, and no feature appears both as reorganized and on the rebuild list.
- **SC-005**: The request log of every run shows that the set of guarded members called is a subset of the stage-1 allowlist, that the refused set is empty, and that every mutating call named the copy's path as its target.
- **SC-006**: Every change that raised the rebuild-error count above the baseline appears in the change log as rolled back with a confirmed restoration of the count; no change that raised it is left applied.
- **SC-007**: A run that reaches the change, wall-clock, or rebuild limit reports `truncated`, names the applied and the unapplied changes, and is never reported as complete.
- **SC-008**: The report shows the grade before and after as counts per bucket with the unresolved rule ids named beside them; no letter grade and no single-percentage headline appears anywhere in the product.
- **SC-009**: The apply phase completes with the provider factories replaced by factories that raise, proving no part of the executor constructs a language model; and a scripted provider that proposes invalid descriptions, globals, and classifications produces zero invalid entries in the plan and does not end the run.
- **SC-010**: A value of 120 mm never becomes 0.12 in an equation; every tolerance constant is in metres and every angle in radians; and no comparison in the gate mixes an absolute bound with a relative one, each pinned by a test that needs no SOLIDWORKS seat.
- **SC-011**: Discard leaves the run folder with every artifact except the part file, and the report remains readable afterwards.
- **SC-012**: Feature 001, 002, and 003 golden baselines remain byte-identical, and the model-facing tool list and the terminal profile's enabled tools gain no remodel entry.
- **SC-013**: Every blocking probe (the reorder behaviour and its refusal dialog, the equation unit, folder contiguity, the run-tag round trip, the part-root dump, and the tolerance calibration) is answered and recorded before the code that depends on it is trusted; an unanswered probe leaves its dependent behaviour reported as unresolved rather than assumed.

## Assumptions

- Feature 003 User Story 6 (the Model check tab) lands first and is a hard prerequisite. A part opened alone currently dumps zero features, and the re-modeler's entire subject is a part opened alone, so without the part-root fix and the model-check dump profile the planner has no input.
- This feature consumes, rather than re-creates, what feature 003 builds: the part-root node in the component tree dump and the model-check dump profile, the no-language-model rule evaluation entry point and the grade, the shared pane actions and the pure feature-selection strategy, and the shared page rendering helpers. Duplicating any of them is a defect in this feature.
- The pane's tabs are Review, Ask, Extract, Model check, and Remodel, with a step strip above them. Model check is tab 4 and Remodel is tab 5.
- The API members this feature names exist with the stated signatures on the SOLIDWORKS 2024 SP5 interop 32.5.0.48, re-verified by reflection on 2026-09-16. VERIFIED means exactly that the member exists with that signature, or that the enum constant has that value; it never means the call behaves. Behaviour is UNVERIFIED until the workstation probes answer it, and the probes that block are named in FR-003, FR-005, FR-015, FR-027, FR-036, and SC-013.
- No tolerance profile is calibrated yet. A tolerance that has never been compared against a known analytic answer does not ship.
- The intermediate representation carries equations but no sketch dimensions in this version, so global variables can be named, repaired, and added from feature data, and nothing more.
- The type table and the target-group table are one data source shared with feature 003's checks; the group names default to `1-Ref`, `2-Construction`, `3-Core`, `4-Detail`, `5-Modify`, `6-Quarantine` and are configurable there, and the table carries the SOLIDWORKS version it was calibrated against.
- The honest expectation for stage 1 on a part built without the method's discipline is that the reorganizable fraction may be small, because SOLIDWORKS will not reorder a feature past a dependency. Stage 1's product is a partition with reasons, and the report says so in its first line when the fraction is small.
- The engineer runs this on a part they chose, on the pilot workstation, with the vault available; the copy leaves the run folder only by the engineer opening it and saving it themselves from SOLIDWORKS.
- Two remodel runs never run at once on one add-in instance, and a run is never resumed after a lost session.
