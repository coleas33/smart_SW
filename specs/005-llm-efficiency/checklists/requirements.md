# Specification Quality Checklist: LLM Efficiency, Speed, and Token Usage

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

- Validation iteration 1 (2026-09-16): every item passes with the accepted deviations below, each
  evaluated rather than waved through.

**Accepted deviations from "no implementation details"**

- **Provider field names are the requirement, not incidental detail.** FR-001 through FR-008 exist
  because the two providers report different quantities under similar names: on OpenAI the reasoning
  count is a subset of the output count, on Gemini the thoughts count is a separate addend of the
  total; on Gemini the cached-content count is inside the prompt count while the tool-result count is
  outside it. A spec that said only "record token usage" would license the exact arithmetic error
  RK-3 names. The fields are named at the level of what they mean, and the file and line where each
  was read is cited so a reader can check.
- **Two SDK behaviours are named because a design decision rests on them.** The omitted-field case
  (FR-002) is the whole reason every token field is nullable, and it was reproduced against the
  installed package rather than inferred. The absence of any validation of the Gemini cached-content
  request shape (FR-045) is the reason one function must build both shapes, because the failure is a
  service error that kills a review rather than a type error a test would catch.
- **Every such claim carries VERIFIED or UNVERIFIED with the meaning the design brief gives.**
  VERIFIED means read in this tree or in the installed package at the cited file and line on
  2026-09-16; it never means an API was observed behaving a certain way. Behaviour questions carry
  the probe id that settles them (L1, L2, L3, L3b, L5, G1 through G5, P1 through P8), so the spec
  does not read as if they were settled.
- **The measured baseline numbers appear in the spec** (32 tools, 34,065 bytes, the 23.8 percent
  tier, the 8,093-byte withheld set) because the adoption rule is a comparison against a number, and a
  spec that states the target without the baseline cannot be gated. FR-015 makes those numbers a
  test output rather than prose, for the reason that the input document's transcribed versions of
  them are already wrong.
- **The lever numbers (2, 3, 4, 5, 6, 7, 8, 9, 10a, 11a, 12) are the engineer-facing vocabulary** of
  `docs/llm-efficiency-options.md` and of the results ledger, exactly as the rule ids are in feature
  003's spec. Renaming them in the spec would break the link to the ledger and to the input document.

**Departures from the design brief, with reasons**

- **The A/B "command" is a procedure plus one reader, not a single command that runs six times.** The
  feature request asks for "an A/B command that runs the benchmark set on and off three times and
  writes the results ledger". FR-022 through FR-024 instead specify six separate benchmark runs into
  six run folders plus one compare command that renders the ledger from the scorecards. This follows
  the design brief section 5.2, whose argument is that a repetition loop inside the benchmark runner
  would have to invent a nested folder layout and an aggregation that is already the scorecard's job,
  and that separate folders are what make re-running one flaky package possible. **The cost:** the
  engineer types six commands rather than one, and the alternation of the arms is a discipline the
  procedure states rather than something the code enforces. If the owner prefers the single command,
  the change is a thin wrapper that shells the six runs and then the compare, and it should be argued
  on its own rather than assumed here.
- **The Decision column is computed and the owner's approval is a second, separate field.** The
  design brief says the adoption decision is the owner's and that the ledger has a Decision column
  rather than a list of winners. FR-027 and SC-009 make the column itself **computed** by the
  FR-028 rule and forbid it being free text, and record the owner's act beside it as
  `owner_signed_off` with a date, which the compare command never writes and without which no flag
  default changes. **The reason:** a column that is both the audited number and a typeable field
  cannot be regenerated from the run folders, which is the one property this whole feature exists
  to buy. **The cost:** the owner cannot overrule the rule by editing the cell; overruling means
  changing the rule in FR-028, in writing, and re-rendering. That is the intended friction, but it
  is friction, and if the owner wants a typeable override the place to argue it is FR-027.
- **The spec does not carry section 3.3's interaction matrix as a table.** Its content is distributed
  into the requirements that act on it (FR-037 for levers 2 and 3, FR-048 for 4 and 3, FR-064 for 5
  with 6 and 7, FR-076 for 6 with 7) and into the "other levers on" column of FR-026. The matrix
  itself belongs in the plan, where a reader deciding an order needs it in one place.
- **Nothing else departs.** The scope exclusions (lever 8, the fastener-joint enumerator, lazy faces,
  per-check input digests, concurrent local execution) are the brief's, with the brief's reasons.

**Honest notes on what this spec does not settle**

- **The spec gates on a benchmark set that does not exist yet.** Today's set is one package with two
  known defects, no held-out package, and a package with zero geometry, features, and equations, so
  recall never computes and one lost defect is a 50 percent swing. FR-029 and SC-011 make the harness
  refuse to render a decision in that state rather than produce one that means nothing, but growing
  the set is a scheduling decision outside this spec's control and it is the precondition most likely
  to be skipped under time pressure.
- **No agent review has ever been run against any package in this tree.** The first measurement of
  this feature is therefore its own baseline, and it may surface defects in paths that have never
  executed end to end. The spec says this in the Assumptions rather than writing as if a baseline
  existed.
- **Twenty-plus behaviours are UNVERIFIED and several are blocking.** Whether our prefix hits the
  cache at all (L2) decides whether lever 3 on OpenAI has anything to win beyond observability;
  whether the diagnostics option is accepted on our seat (L3b) decides whether the miss reason is
  available at all; whether Gemini's implicit caching already delivers (G4) decides whether any
  explicit-cache code is written; whether the mesh phase dominates the dump (P1) is lever 10a's
  entire premise. SC-024 forbids adopting a lever on an unanswered probe, which means an unanswerable
  probe removes a lever rather than softening a claim.
- **Three UNVERIFIED items would change the shape of the code, not just the numbers.** If Gemini's
  streamed usage turns out to be per-chunk deltas (G3), the last-chunk-wins rule is wrong and the
  adapter must accumulate. If the manifest cannot gain a modification time and a size (Q6 in the
  brief), lever 9 is dropped rather than keyed on path and configuration. If the diagnostics option
  is refused, FR-041's miss reason is simply unavailable and lever 4 loses the instrument that would
  have priced it before it was written.
- **The 20 percent adoption threshold is a judgement, not a measurement.** FR-028 fixes it, along
  with the asymmetric treatment of lost defects (worst case) against false alarms (median), before
  the first run, because those four answers argued after a result is in hand are not a gate. They are
  the brief's recommendation and the owner should confirm them explicitly; they are the one part of
  this spec that no test can validate.
- **Lever 2's two arms are one commit, like every other lever's.** FR-035 rejects run-time
  truncation, so the trim is a docstring split; but FR-033 makes the flag-off path hand over the
  **rejoined** description, which FR-039 pins byte-equal to the pre-split text, so the off arm is
  recoverable by flipping the boolean after all and SC-007 holds at the wire level. FR-032 still
  requires both commits in the row for a lever whose arms really were two commits; this feature has
  no such lever, and `compare`'s same-commit refusal therefore has no declared exception. The
  alternative, a run-time cap, would have made the A/B a flag toggle at the price of measuring an
  amputation we would never ship.
- **Lever 6 is measured on one provider only.** FR-068 states why: Gemini already batches in
  production and the installed package offers no way to turn that off, so the "off" arm would be a
  new capability built only to be measured. The row says so rather than presenting half a comparison.
- **The pane surface in FR-014 is the least specified part of the measurement layer.** The spec fixes
  what is shown and where it comes from (the existing stream) and deliberately leaves the layout to
  the plan. The one thing it forbids is a third copy of the numbers on another endpoint.
- **Lever 8's exclusion is a scope judgement, not a measured result,** and FR-077 says so in those
  words. If the owner wants it, the narrow version and the test that matters for it are named in the
  edge cases so the deferral can be revisited without re-deriving the argument.
- Items marked incomplete would require spec updates before `/speckit-clarify` or `/speckit-plan`;
  none are marked incomplete.
