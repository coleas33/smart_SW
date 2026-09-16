# Specification Quality Checklist: Resilient Re-modeler

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-09-16
**Feature**: [spec.md](../spec.md)

## Content Quality

- [x] No implementation details (languages, frameworks, APIs) (with the accepted deviations listed in Notes)
- [x] Focused on user value and business needs
- [x] Written for non-technical stakeholders
- [x] All mandatory sections completed

## Requirement Completeness

- [x] No [NEEDS CLARIFICATION] markers remain
- [x] Requirements are testable and unambiguous
- [x] Success criteria are measurable
- [x] Success criteria are technology-agnostic (no implementation details) (with the accepted deviations listed in Notes)
- [x] All acceptance scenarios are defined
- [x] Edge cases are identified
- [x] Scope is clearly bounded
- [x] Dependencies and assumptions identified

## Feature Readiness

- [x] All functional requirements have clear acceptance criteria
- [x] User scenarios cover primary flows
- [x] Feature meets measurable outcomes defined in Success Criteria
- [x] No implementation details leak into specification (with the accepted deviations listed in Notes)

## Notes

- Validation iteration 1 (2026-09-16): all items pass with the accepted deviations below, each
  evaluated rather than waved through.

**Accepted deviations from "no implementation details"**

- The six group names (`1-Ref` through `6-Quarantine`) and the reason taxonomy
  (`backward_reference`, `shared_sketch`, `splits_group`, `cycle`, `radius_unreadable`,
  `ambiguous_name`, `unclassified`, `graph_unreadable`) appear because they are the method's
  vocabulary and the engineer-facing names of what the report says, exactly as the rule ids are in
  feature 003's spec.
- A small number of SOLIDWORKS interop member names appear (the reorder member, the equation add
  overloads, the custom-property tag members). They are load-bearing rather than incidental: the
  write surface is specified as an **allowlist of exactly those members** (FR-050), the reorder
  member is name-addressed which is why FR-013 exists at all, and the equation add is the one call
  the product may not believe without an assertion (FR-028). Naming them is the requirement.
- Every such member carries VERIFIED or UNVERIFIED with the same meaning the design brief gives it:
  VERIFIED means the member exists with that signature on the 2024 SP5 interop, never that the call
  behaves. Behaviour questions are named as PROBE ids so the spec does not read as if they were
  settled.
- The run folder's artifact list (FR-040) is in the spec because the artifacts *are* the evidence
  the constitution's Principle VI requires, and Discard's semantics (FR-046) are defined over them.
- SC-012 names the golden baselines and the tool lists because the regression gate and the
  "no new model-facing tool" gate are stated success criteria of the constitution and of feature 003.
- FR-055 names the constitution amendment because the exception this feature needs does not exist
  yet; shipping the write code without it would leave the governing rule unwritten.

**Honest notes on what this spec does not settle**

- **The feature is blocked on another feature.** Feature 003 User Story 6 must land first
  (Assumptions, first bullet). This spec is reviewable now, but it is not implementable until the
  part-root dump fix and the model-check dump profile exist, because a part opened alone currently
  dumps zero features.
- **Six behaviours are UNVERIFIED and blocking** (FR-003, FR-005, FR-015, FR-027, FR-036, SC-013).
  If the reorder refusal dialog cannot be suppressed (PROBE-1), stage 1 cannot run unattended at
  all, and the answer changes the feature rather than the plan. The spec states this rather than
  assuming a favourable answer.
- **Stage 1's value is not asserted.** SC-003 deliberately reports the reorganizable fraction and
  sets no threshold on it. On a part built without the method's discipline that fraction may be
  small, and the spec says so (Assumptions) instead of promising a result the dependency graph may
  not allow. The dry-run planner (User Story 2) exists to turn this into a number before the
  expensive work starts.
- **Tolerances are not calibrated.** FR-036 forbids shipping a tolerance profile that has never
  been compared against a part of exactly known analytic volume, so the geometry gate is specified
  but not yet trustworthy, and the spec does not claim otherwise.
- **One internal tension in the design brief was resolved in the spec.** The brief's inverse table
  gives folder creation the inverse "dissolve that folder", which needs the folder-delete member;
  the owner's decision keeps that member off the stage-1 allowlist. FR-024 therefore routes a failed
  folder creation to the catastrophic replay path rather than to a forward inverse. This is a real
  cost (a folder failure is far more expensive to undo than a reorder failure) and the plan should
  weigh re-admitting the member behind the folder-selection assertion if real parts make folder
  failures common.
- **Dimension binding is narrower than the brief's flow, and the whole dimension path is out.**
  The brief's apply order opened with a dimension-rename step and ended with "dimension equations,
  seeded from the current value". The intermediate representation carries no dimensions in this
  version, so FR-030 forbids both: the planner cannot name a dimension and cannot prove what an
  equation on one would drive. FR-022's fixed order therefore has no dimension step,
  `IDimension.set_Name` is off the stage-1 allowlist, and `remodel.rename` has no dimension form.
  The unit sequence is kept (FR-027) and rewritten around the value the package carries, because it
  governs the literal of every global this version does write. The rename-before-equations ordering
  rule is preserved in research.md R3.5, unimplemented, for the later dimensions feature.
  **The visible cost:** a v1 global names a value and drives nothing, so the report has to say so
  in those words or a part with three new globals reads as parameterized when it is not.
- **The scope refusal had to move ahead of the copy, and that cost a command.** The brief read the
  scope signals at the end of the open sequence, after the copy was on disk and a document was
  open. FR-001 requires the refusal before either exists, so the signals are read by a separate
  read-only `remodel.probe_scope` on the source the engineer already has open, and `remodel.open`
  refuses unless it is handed that probe's id. **The cost:** the protocol now has two commands that
  name a path instead of one, and the run only works on a source SOLIDWORKS already has open. **The
  one refusal that could not move** is pre-existing rebuild errors, which needs a rollback and a
  rebuild; it is taken on the copy and its handler deletes the copy, and FR-004 says so.
- **The geometry baseline is the copy at open, not the source opened read-only.** FR-037 first said
  the comparison was made against the source file on disk, opened read-only. Nothing in the design
  could produce that reading: no command takes a document, and a second handle to the engineer's
  file is the thing the constitution exception exists to avoid. The baseline is therefore the
  copy's own reading at open, which is a reading of the source's geometry because the copy is a
  byte-for-byte copy whose hash was recorded first. **The cost:** a geometry difference produced by
  the baseline rollback and rebuild themselves sits inside the baseline; it is printed as a named
  coverage limit on every run rather than left unsaid.
- **User Story 5 is priority P5 and is not optional.** It is last as an independently demonstrable
  slice, not last in importance; its own "Why this priority" says so, and User Story 1 cannot ship
  without it.
- Items marked incomplete would require spec updates before `/speckit-clarify` or `/speckit-plan`;
  none are marked incomplete.
