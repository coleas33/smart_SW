# Feature Specification: SOLIDWORKS Agentic Design Review Pilot

**Feature Branch**: `001-agentic-design-review`

**Created**: 2026-09-12

**Status**: Draft

**Input**: User description: "SOLIDWORKS agentic design review pilot: an assistant that investigates assemblies and drawings, gathers engineering evidence, and reports verifiable fit-up, tolerance, fastener, and drawing findings." Derived from `README-complete.md` (pilot definition, ROI ranking, review boundaries) and `sw-review-architecture-proposal.md` (ADR-001, v1 check list).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Evidence-Linked Review of a Design Package (Priority: P1)

A mechanical engineer hands the reviewer a design package for one design (an assembly or subassembly plus its drawing package): drawing PDFs, a bill of materials, a manifest of vault file versions, revisions and configurations, and any exported geometry. The reviewer investigates the package, identifies suspicious interfaces and missing manufacturing inputs, requests specific missing evidence when it needs it, and produces a review report. Every finding names the affected component instances or drawing location, the governing requirement, the source inputs with units and tolerances, the tool result or calculation with its assumptions, a status, and a recommended next action. The engineer reads the report, jumps to each finding, and records a disposition.

**Why this priority**: This is the highest-ROI capability in the pilot ranking and the only one that works on day one with exported files alone. Every later story feeds evidence into this loop.

**Independent Test**: Give the reviewer one real package (PDFs, BOM, manifest) with at least one known defect and one deliberately missing tolerance. Confirm the report contains an evidence-linked finding or a precise missing-input request for each, that no finding clears a check on an inferred value, and that the coverage section lists what was not checked.

**Acceptance Scenarios**:

1. **Given** a package with drawings, BOM and manifest, **When** the engineer starts a review, **Then** the reviewer produces a report in which every finding carries component instances or drawing location, governing requirement, source inputs with units and tolerances, calculation or tool result with assumptions, a status from {demonstrated, suspected, unresolved, checked-within-scope}, and a recommended action.
2. **Given** a blind tapped hole whose drawing specifies only drill depth, **When** the reviewer evaluates screw bottoming, **Then** the finding is reported as `unresolved` with a request for usable thread depth, and the check is not cleared.
3. **Given** a package where a drawing PDF has no machine-readable dimensions, **When** the reviewer needs a dimension, **Then** it records the dimension as unavailable, asks the engineer for it or for native access, and lists the affected checks under unresolved coverage.
4. **Given** a completed report, **When** the engineer opens a finding, **Then** they can navigate to the named component instance or drawing sheet and view within one action and record a disposition (accepted, rejected, deferred) with a note.
5. **Given** a review that hit a tool failure mid-investigation, **When** the report is generated, **Then** the failed step appears in coverage as failed, with the error, rather than being omitted.

---

### User Story 2 - Native Evidence Extraction from the Workstation (Priority: P2)

On the SOLIDWORKS 2024 workstation, the engineer opens an assembly from the EPDM working copy and runs an extraction that produces an evidence package: component tree with transforms, configurations and suppression state; mates; holes and threads; fastener identities; materials and mass properties; custom properties; the face geometry needed by checks; screenshots of requested views; and a persistent reference for every entity, bound to the exact vault file version and configuration. The reviewer can consume this package instead of, or in addition to, exported files.

**Why this priority**: Exported files drop threads, fastener identity, mates and configurations. Native extraction is what makes the interface, fit and fastener stories reliable, and the pilot plan targets a first native connection within the first week.

**Independent Test**: Run the extraction on a known assembly and compare the evidence package against a hand-built answer key: component instance count and identities, hole and thread data for a chosen part, fastener size and length for a chosen screw, and the vault version and configuration stamp. Confirm every entity has a persistent reference that resolves back to the same entity when reopened.

**Acceptance Scenarios**:

1. **Given** an assembly open on the workstation, **When** the engineer runs extraction, **Then** an evidence package is written that lists every component instance with its transform, referenced configuration and suppression state, and the manifest records vault file, version, revision, and configuration for each document.
2. **Given** a Hole Wizard tapped hole and a Toolbox screw, **When** extraction runs, **Then** the package records thread specification and depth for the hole and size, length and head type for the screw.
3. **Given** a package from extraction, **When** the reviewer later requests a screenshot of a finding, **Then** the persistent reference resolves to the same entity and the capture shows it.
4. **Given** an assembly with lightweight or suppressed components, **When** extraction runs, **Then** those components are listed with their state and any checks that need them are reported as unresolved rather than silently skipped.
5. **Given** an assembly that references a file not at the manifest's vault version, **When** extraction runs, **Then** the discrepancy is recorded and surfaced in the report.

---

### User Story 3 - Interference and Clearance Review (Priority: P3)

The engineer selects component pairs or whole subassemblies and one or more configurations. The reviewer reports interferences with their volumes and the entities involved, groups repeated findings (the same fastener pattern hitting the same feature), retains previously reviewed exceptions tied to the geometry and configuration they were accepted for, and flags any exception whose underlying condition has changed.

**Why this priority**: Interference checking is one of the three named time sinks, and it becomes cheap once native extraction exists.

**Independent Test**: Run the review on an assembly with three seeded interferences, one repeated across six instances, and one previously accepted exception. Confirm all three appear, the repeated one is grouped, the exception is retained, and modifying the excepted geometry causes the exception to be flagged as needing re-review.

**Acceptance Scenarios**:

1. **Given** selected pairs and a configuration, **When** the review runs, **Then** each interference lists the two component instances, the overlap volume with units, the configuration, and the settings used (coincident-face handling, fastener treatment).
2. **Given** the same interference repeated across instances of a pattern, **When** the report is produced, **Then** it is shown as one grouped finding with the instance list.
3. **Given** an accepted exception, **When** the geometry or configuration it was bound to is unchanged, **Then** the finding is shown as excepted with the original disposition; **When** it has changed, **Then** it is shown as needing re-review.
4. **Given** an interference computation that was truncated or failed for some pairs, **When** the report is produced, **Then** those pairs are listed as unresolved and the overall result is not reported as a pass.
5. **Given** a mechanism reviewed at selected positions, **When** the report is produced, **Then** it states the positions checked and that clearance across the full motion path was not established.

---

### User Story 4 - Guided Fit and Tolerance Checks (Priority: P4)

The engineer points the reviewer at an interface (a shaft in a bore, an axial stack, a gap) and confirms which drawing dimensions and tolerances govern it. The reviewer evaluates the limiting conditions with a checked calculation, states the calculation model used and what it excludes, and reports the result with its inputs. If a governing input is missing, the result stays unresolved.

**Why this priority**: Assembly fit-up and tolerance problems are the main quality problem named in the pilot goals, but the check depends on evidence from the earlier stories and on knowing where tolerances are stored.

**Independent Test**: Provide a shaft/bore pair with explicit limits and a bolted plate stack with one missing tolerance. Confirm the shaft/bore result matches a hand calculation to the stated precision and the stack is reported unresolved naming the missing tolerance.

**Acceptance Scenarios**:

1. **Given** a diameter fit with both limits specified, **When** the check runs, **Then** it reports minimum and maximum clearance or interference with units, the inputs used with their source locations, and the calculation model ("size only").
2. **Given** an axial stack with one dimension lacking a tolerance and no applicable general note, **When** the check runs, **Then** the result is `unresolved`, names the missing tolerance, and does not substitute a default.
3. **Given** dimensions in mixed units (inch drawing, millimeter model), **When** the check runs, **Then** all values are converted explicitly and the report shows both the source value and the value used.
4. **Given** an angular dimension in the inputs, **When** the check runs, **Then** it is not treated as a length.

---

### User Story 5 - Fastener and Hole Compatibility (Priority: P5)

For each supported joint type, the reviewer checks that the screw does not bottom before the joint clamps, that usable thread engagement meets the rule for the tapped material, that the screw thread matches the hole thread, and that the head and washer clear neighboring geometry. Results cite the fastener identity, the hole specification, the clamped stack, and the engagement rule applied.

**Why this priority**: Fastener problems are frequent and are trivial once native hole and fastener data exist, but they require the extraction story to be reliable first.

**Independent Test**: Provide a joint with a screw that is 2 mm too long for its blind hole and a second joint with correct engagement. Confirm the first is flagged as bottoming with the computed margin and the second is reported checked-within-scope with its engagement ratio.

**Acceptance Scenarios**:

1. **Given** a screw, a clamped stack, and a blind tapped hole with usable thread depth, **When** the check runs, **Then** it reports the bottoming margin and the engagement length against the rule for the hole material.
2. **Given** a screw thread that does not match the hole thread, **When** the check runs, **Then** the mismatch is reported as demonstrated with both specifications.
3. **Given** a joint type the pilot does not support, **When** the check runs, **Then** the joint is listed as out of scope, not as passed.

---

### User Story 6 - Benchmark Evaluation and Scorecard (Priority: P6)

The engineer runs the reviewer across a set of benchmark packages (5 to 10 representative designs with known defects and correct designs, some held out from development) and receives a scorecard: valid findings, known defects missed, false alarms, unresolved coverage, and net time saved per design against a recorded human baseline. The scorecard supports a continue, narrow, revise, or stop decision.

**Why this priority**: The pilot's outcome is a measured decision at the four-week checkpoint. Without the scorecard, none of the other stories can be judged.

**Independent Test**: Run the reviewer on two held-out packages with a withheld answer key. Confirm the scorecard reports per-package and aggregate counts and the time comparison, and that the answer key was not readable by the reviewer during the run.

**Acceptance Scenarios**:

1. **Given** a benchmark set with an answer key, **When** the evaluation runs, **Then** the scorecard lists, per package, valid findings, missed known defects, false alarms, and unresolved coverage.
2. **Given** recorded baseline and assisted review times for a package, **When** the scorecard is produced, **Then** net time saved is computed as baseline minus assisted effort (including supervision, verification and false-alarm handling), with unattended runtime shown separately.
3. **Given** the scorecard, **When** the engineer reviews it, **Then** the distribution across packages is shown, not only the best case.

---

### Edge Cases

- Drawing specifies drill depth but not usable thread depth: the fastener check stays unresolved and asks for the missing input.
- A tolerance is absent from the drawing and no general note applies: the affected check stays unresolved; no default tolerance is substituted.
- Drawing PDF has no machine-readable text (scanned or flattened): dimensions are recorded as unavailable and the checks depending on them are listed as unresolved.
- Mixed units within one package (inch drawings, millimeter model, angular dimensions): every value is converted explicitly and shown with its source value; angles are never treated as lengths.
- Component instances repeated in patterns: findings are grouped by pattern with the instance list; each instance retains its own identity.
- Multiple configurations: every finding is bound to the configuration reviewed; a finding in one configuration is not assumed to hold in another.
- Suppressed, lightweight, or unresolved components: listed with state; dependent checks reported as unresolved.
- Local modifications or files not at the manifest's vault version: recorded as a provenance discrepancy and surfaced at the top of the report.
- Interference computation truncated or failed for some pairs: those pairs reported as unresolved; overall verdict is not a pass.
- An accepted interference exception whose geometry or configuration has since changed: flagged for re-review rather than silently retained.
- Mechanism reviewed at discrete positions: report states positions checked and that full motion clearance was not established.
- Tool failure mid-investigation (crash, timeout, unsupported document): the step is recorded as failed with the error; the reviewer continues with what it can and lists the rest as unresolved.
- Reviewer requests evidence the engineer cannot provide: the request stays open in the report and the dependent checks remain unresolved.
- A joint or interface type the pilot does not support: listed as out of scope, never as passed.
- Third-party tool output with known unit or precision bugs: excluded from calculations until validated against a known case.

## Requirements *(mandatory)*

### Functional Requirements

**Review package and provenance**

- **FR-001**: The system MUST accept a review package for one design consisting of drawing PDFs, a bill of materials, a manifest of vault file, version, revision and configuration per document, and optionally exported geometry and a native evidence package.
- **FR-002**: The system MUST record the provenance of every input (source file, vault version, revision, configuration, export method) and bind every finding to it.
- **FR-003**: The system MUST surface any discrepancy between the manifest and the files actually reviewed (local modifications, version mismatch, missing document) at the top of the report.

**Investigation and evidence**

- **FR-004**: The system MUST let the reviewer choose what to investigate next, guided by the functional requirements of the design and a mandatory review checklist, and MUST record the sequence of investigation steps taken.
- **FR-005**: The system MUST obtain measurements, unit conversions, interference results and fit calculations only from checked, tested functions, never from free-form reasoning.
- **FR-006**: The system MUST expose only a curated set of inspection operations to the reviewer; no general-purpose code execution with application or operating-system access.
- **FR-007**: The system MUST let the reviewer request specific missing evidence from the engineer and MUST keep the request open in the report until answered.
- **FR-008**: The system MUST treat any missing, ambiguous, or unvalidated input as unknown; it MUST NOT infer a favorable value to clear a check.

**Findings and report**

- **FR-009**: Every finding MUST include: affected component instances and/or drawing sheet, view or annotation; file version, revision and configuration; observed condition; governing requirement; source dimensions with units and tolerances; tool result or calculation with assumptions and coverage limits; status from {demonstrated, suspected, unresolved, checked-within-scope}; recommended next action; and a disposition field for the engineer.
- **FR-010**: The report MUST include a coverage section listing what was checked, skipped, unresolved, failed, and out of scope, including tool failures with their errors.
- **FR-011**: The report MUST group repeated findings (same condition across pattern instances) into one finding with the instance list.
- **FR-012**: The engineer MUST be able to navigate from a finding to the named component instance or drawing location in one action and to record a disposition (accepted, rejected, deferred) with a note.
- **FR-013**: The system MUST retain dispositions and accepted exceptions bound to the geometry and configuration they were made for, and MUST flag them for re-review when that geometry or configuration changes.

**Native evidence extraction**

- **FR-014**: The system MUST extract from an open SOLIDWORKS 2024 assembly: component tree with transforms, referenced configurations and suppression state; mates; hole type, standard, size, thread specification and depth; cosmetic threads; fastener type, size, length and head; materials and mass properties; custom and configuration-specific properties; and the face-level geometry required by the checks (cylinder axes and radii, plane normals and origins, bounding boxes).
- **FR-015**: Every extracted entity MUST carry a persistent reference that resolves back to the same entity when the document is reopened.
- **FR-016**: The evidence package MUST carry a schema version, and consumers MUST refuse a package whose major version they do not support.
- **FR-017**: The system MUST capture screenshots of a requested entity or finding on demand, keyed by persistent reference.

**Interference and clearance**

- **FR-018**: The system MUST run interference detection for selected component pairs, subassemblies, or the whole assembly in a named configuration and report, per interference, the two component instances, overlap volume with units, and the detection settings used.
- **FR-019**: The system MUST report truncated or failed interference computations as unresolved and MUST NOT report an overall pass when any pair is unresolved.
- **FR-020**: When a mechanism is reviewed at selected positions, the report MUST state the positions checked and that clearance across the full motion path was not established.

**Fit, tolerance, fastener checks**

- **FR-021**: The system MUST evaluate diameter fits, axial stacks and gaps from explicit limits, reporting minimum and maximum condition with units, the inputs and their source locations, and the calculation model used and excluded effects.
- **FR-022**: The system MUST convert units explicitly, show both source and converted values, and MUST NOT treat angular dimensions as lengths.
- **FR-023**: For supported joint types the system MUST check screw bottoming, usable thread engagement against a per-material rule, thread compatibility, and head or washer clearance, citing fastener identity, hole specification, clamped stack, and rule applied.
- **FR-024**: Unsupported joint or interface types MUST be reported as out of scope, never as passed.

**Evaluation**

- **FR-025**: The system MUST run against a benchmark set with an answer key withheld from the reviewer and produce a scorecard of valid findings, missed known defects, false alarms, and unresolved coverage per package and in aggregate.
- **FR-026**: The system MUST record baseline and assisted review effort per design and compute net time saved, with unattended runtime reported separately.

**Boundaries**

- **FR-027**: The system MUST NOT create GD&T, place general drawing dimensions, or issue structural approval in this feature.
- **FR-028**: The system MUST NOT use third-party tool output known to have unit or precision defects in any calculation until a validation test against a known case passes.

### Key Entities

- **Design**: One assembly or subassembly and its drawing package; the unit of review and of time measurement.
- **Review Package**: The inputs for one design: documents, manifest, optional exported geometry, optional native evidence package.
- **Document**: A drawing, part, or assembly file with vault path, version, revision, and active configuration.
- **Component Instance**: One occurrence of a part or subassembly in the assembly tree, with transform, referenced configuration, suppression state, and persistent reference; distinct from the part definition.
- **Interface**: A pairing of component instances or features under review (bore/shaft, bolted joint, stack, gap, clearance pair).
- **Evidence Item**: A measurement, dimension, tolerance, note, screenshot, or tool result, with provenance, units, and the persistent reference it came from.
- **Calculation**: A checked evaluation with named model, inputs, assumptions, excluded effects, units, and result.
- **Finding**: An observed condition with governing requirement, evidence, calculation, status, recommended action, and disposition.
- **Coverage Record**: What was checked, skipped, unresolved, failed, or out of scope for a review, with reasons.
- **Exception**: An engineer-accepted deviation bound to specific geometry and configuration, with re-review trigger.
- **Disposition**: The engineer's decision on a finding (accepted, rejected, deferred) with a note and timestamp.
- **Review Session**: One run of the reviewer over one package, with investigation steps, elapsed and supervised time.
- **Benchmark Package**: A review package with a withheld answer key of known defects and correct conditions.
- **Scorecard**: Per-package and aggregate results of a benchmark run plus time comparison.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: On the benchmark set, median net engineering effort saved per design is at least 60 minutes, measured as recorded baseline effort minus assisted effort (including supervision, verification and false-alarm handling).
- **SC-002**: The first real package yields, within one working day, at least one evidence-linked finding or precise missing-input request and at least one numerical check the engineer reproduces by hand with matching result.
- **SC-003**: 100% of findings in every report contain all required fields (FR-009); an audit of the report finds no finding cleared on an inferred or defaulted input.
- **SC-004**: On held-out benchmark packages, the reviewer surfaces at least 80% of seeded known defects as demonstrated or suspected findings, and no more than 30% of findings are false alarms.
- **SC-005**: 100% of tool failures, truncated computations and unsupported document types encountered during a review appear in the coverage section.
- **SC-006**: An engineer can go from any finding to the referenced component instance or drawing location and record a disposition in under 30 seconds.
- **SC-007**: Native extraction of a representative assembly matches its hand-built answer key for component instance identity, hole and thread data, and fastener identity with zero mismatches.
- **SC-008**: Review quality does not degrade: on the benchmark set the count of known defects missed with the assistant is no greater than the count missed in the human baseline.

## Assumptions

- The pilot workstation runs SOLIDWORKS 2024 with EPDM, as stated in the pilot README. SOLIDWORKS 2026 features referenced in the architecture proposal (Auto-Generate Drawing, automatic fastener recognition) are not assumed available.
- "One design" means an assembly or subassembly plus its drawing package; this definition is used for every time measurement and must be confirmed with the team before results are reported.
- Automated drawing creation and drawing finishing (ADR-001 layer 3) are a separate future feature and are excluded here; the pilot produces review findings only.
- Engineering change impact analysis and tool-access/insertion-path checks (ROI ranks 6 and 7) are deferred to a later feature.
- Manufacturing tolerances are found on drawings, in general notes, or in a confirmed manifest; where they are stored and how consistently is an open question the first investigation must answer, and until answered missing tolerances stay unresolved.
- One reviewer agent is used; a second critique agent is added only if it measurably improves quality.
- The engineer reads reports and records dispositions through whatever client is chosen in planning; no specific user interface is required beyond one-action navigation and disposition entry.
- Benchmark packages number 5 to 10, include known defects and correct designs, and some are held out from development. The 80% recall and 30% false-alarm ceilings in SC-004 are pilot targets set here because the source documents give none; the team may revise them before the four-week checkpoint.
- Reuse of third-party repositories follows their licenses: SwpilotCLI is internal-use only; GPL-3.0 components are not linked into distributed code.
- The four-week pilot checkpoint already scheduled for 2026-10-03 is the decision point for continue, narrow, revise, or stop.
