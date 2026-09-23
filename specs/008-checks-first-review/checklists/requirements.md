# Specification Quality Checklist: Checks-First Review and the Token Budget

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-09-22
**Feature**: [spec.md](../spec.md)

## Content Quality

- [x] No implementation details (languages, frameworks, APIs) - one exception, FR-030 (see Notes)
- [x] Focused on user value and business needs
- [x] Written for non-technical stakeholders
- [x] All mandatory sections completed

## Requirement Completeness

- [x] No [NEEDS CLARIFICATION] markers remain
- [x] Requirements are testable and unambiguous
- [x] Success criteria are measurable
- [x] Success criteria are technology-agnostic (no implementation details)
- [x] All acceptance scenarios are defined
- [x] Edge cases are identified
- [x] Scope is clearly bounded
- [x] Dependencies and assumptions identified

## Feature Readiness

- [x] All functional requirements have clear acceptance criteria
- [x] User scenarios cover primary flows
- [x] Feature meets measurable outcomes defined in Success Criteria
- [x] No implementation details leak into specification - one exception, FR-030 (see Notes)

## Notes

- Validated 2026-09-22. The owner's decisions of the same day (all four efficiency changes as pane defaults gated by the replay; modelling-practice findings folded; the replay as the gate) left no clarification open.
- The spec names product vocabulary the owner reads - run folder, session, report, ranking, standards profile, the two recorded assemblies - and no language, module or function. The replay command's name appears in the Input line only, quoted from the owner's direction.
- The tokenizer is named as "one named tokenizer" in the requirements; the plan picks it.
- Re-validated 2026-09-23 (T100) against the spec as amended by the planning pass (research R4: SC-003's regrouped estimate, the command line off unless asked, `<out>/package.json`, a hang not detectable, the report's uncached and cached words, the family fold, the standards family's reason, the pilot's profile, 7 rules) and by the owner's amendment of the same day (FR-030, lever 13). Every item holds, with one exception recorded rather than rewritten, since the text is the owner's: FR-030 and its edge case ("A model that calls a withheld tool anyway") name the setting `withhold_prerun_tools`, the `--pane-defaults` switch, the tools `check_interference_group`, `check_standards` and `get_finding`, the dispatch and the re-call guard. The rule differs tool by tool, so the tool names are the requirement's subject; the setting, the switch and the dispatch are implementation words a later edit could replace with "the pane default", "the switch that applies every pane default" and "the product".
- Every acceptance scenario and success criterion that can be measured offline has a test or a replay figure behind it (quickstart Scenarios 0 to 10, run for T099). SC-006 and SC-009 are proven offline - a scripted bridge, scripted cached counts - and confirmed on the seat; SC-010 needs the next workstation sitting (Phase 8).
