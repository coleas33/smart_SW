# Implementation Plan: Automatic Mechanical Checks

**Branch**: `010-mechanical-checks` (worked on `main`) | **Date**: 2026-09-23 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/010-mechanical-checks/spec.md`, the analyst's
check-by-check findings of 2026-09-22, and the Phase 0 reading pass and probes in
[research.md](research.md).

## Summary

Turn the owner's goal list into checks code runs on every review, with no model choosing an
argument, in the order they can ship before the next workstation sitting:

1. **Fixtures first** (Setup): two synthetic packages built by code and shaped like the recorded
   830-02342 and 810-11249 runs - the same counts, the same geometry cases, fictional strings -
   with a generator that reproduces them byte for byte and a denylist test.
2. **The joint map** (Foundational): hole *instances* exploded from Hole Wizard features (a
   `Hole` row is a feature with up to 16 instances, research R2.1), paired across parts by three
   geometric gates with one partner per component, clustered into screw, pin and through-bolt
   joints, with screws and pins joining as cylinder members. Beside it, the registration point
   (`CODE_FIRST_CHECKS`, read by `prerun.planned_calls`) and standards profile version 2.
3. **Contacts** (US1): a zero-volume or possible-only interference group becomes a `Contact` on
   a new optional session list, rendered in its own report section, never ranked.
4. **The joint map as a check** (US2): `check_joints()`, argument-free, recording the map as
   coverage.
5. **Alignment and the stack-up** (US3): nominal alignment against the fixed- or
   floating-fastener clearance with the position budget as a callout; the worst-case stack with a
   declared model; the zone-radius correction in `hole.coaxiality`.
6. **Fasteners** (US4): screws recognised by name (68 of 68 on the shaped fixture) and
   cross-checked against their measured shank; thread match, engagement and bottoming from the
   placed geometry against the owner's 1.5 x d rule; then the extractor's candidate gate widened.
7. **Tool access** (US5): the head plane and direction from the joint, the tool from the head,
   the sweep against every other body, head fit against a standard head table.
8. **Mass and material** (US6): one material-class table for engagement and density, three
   checks, a coverage count, then the extractor's override read fixed.
9. **Hygiene** (US7): five checks reading their property names from the profile, and the data
   card's zero-match profile error.
10. **Tolerances** (US8): IR 1.5.0 with the Hole Wizard, model-dimension and annotation reads
    behind fakeable reader seams, the profile's general tolerance, an ISO 286 table, and one
    resolver with a fixed precedence feeding the stack-up.

Every Python-only piece (1 to 9, and US8's resolver, table and profile section) lands with no
seat. The extractor reads are built and tested with fakes and validated at the next sitting.

## Technical Context

**Language/Version**: Python 3.11+ for every check, the resolver, the tools, the report and the
fixtures; C# (.NET, the existing extractor projects) for the parser widening, the candidate gate,
the override read, the Hole Wizard and tolerance reads, the IR mirrors and the guard.

**Primary Dependencies**: no new packages. Python: `pydantic`, `pyyaml`, `numpy`, `trimesh` (the
mesh loader and raycast already in use). Reused rather than rebuilt: `geometry/axis.py`
(`axis_distance`, `unit_vector`, and a new `axial_extent` extracted from
`tools/checks_fastener._bbox_extent_mm`), `geometry/envelope.envelope_raycast`,
`geometry/mesh.load_mesh`, `checks/fastener.py` (`parse_thread`, the four rule functions),
`checks/result.py` (`unresolved`, `limits_mm`, `round_length`), `checks/interference.py`
(`group_interferences`, the decision order), `tools/recording.py` (`record_result`,
`record_results`, `out_of_scope`), `tools/standards_checks.standards_run`,
`checks/standards/profile.load_profile`, the `engagement_rules`/`tool_envelopes` loader pattern,
and `ir/models.omit_additive`.

**Storage**: files only. `session.json` gains the optional `contacts` list; `package.json` gains
three optional members at IR 1.5.0 (written by the extractor only); seven data files under
`checks/`. No new run-folder file.

**Testing**: pytest over the two committed synthetic fixtures and a third at IR 1.5.0 for US8;
golden joint maps and results through `file_regression`; the regeneration test for every fixture;
the denylist test; the catalogue test with the twelve new ids; the no-company-values test with
the version 2 profiles; offscreen nothing (no page changes). xUnit for the parser (the shared
vector table), the candidate predicate, the override read, the Hole Wizard and tolerance readers
(fakes), the IR serializer and the guard. The tests that go red by design are named in research
R3 and in the task that lands each change.

**Target Platform**: as features 001 to 008. Everything but the seat validation runs with no
SOLIDWORKS licence and no key.

**Project Type**: extends the reasoning side and the extractor; no pane page changes (feature 009
presents contacts and the new findings).

**Performance Goals**: `check_joints` on the big fixture, including the mesh loads for engagement
and tool access, under 2 s on the development machine (a marked perf test); `build_joint_map`
alone under 200 ms. The pairing is quadratic in instances (132 here, about 8,700 pairs) and is
measured, not optimized, until a package makes it matter.

**Constraints**: the constitution's Principles I to VI verbatim; no tolerance, thread depth,
drive or reach inferred - a missing one is unresolved or a stated pilot default; `hole_depth`
never read as thread depth; every derived value labelled in its calculation; every new package
and session field additive; every golden of `report/markdown.render_report` and every existing
check's golden byte-identical except the three engagement goldens R2.14 names; no new event
type; no model-chosen argument on any new tool; nothing in the repository from the recorded
packages.

**Scale/Scope**: assemblies to a few hundred hole instances and a hundred fasteners; eight user
stories; three new tools; twelve new finding ids; one new session list; three new IR members; one
profile version; seven data files; about 107 tasks.

## Constitution Check

*GATE: passed before Phase 0 research; re-checked after Phase 1 design (result at the end of
the table).*

| Principle | Gate | How this plan meets it | Status |
|---|---|---|---|
| I. Evidence before conclusions | Unknown stays unknown; no favourable value inferred | No tolerance is inferred: the resolver returns a limit only from a bound source and otherwise names every source it searched (R2.18); the general block applies only to size subjects with no explicit tolerance and never to position; the stack-up states its model and lists an unresolved position as an excluded effect rather than dropping it (R2.7). No thread depth is inferred: a blind hole's usable thread is its Hole Wizard `thread_depth` or nothing, a through-tapped length is the face's measured extent labelled derived, and `hole_depth` is never read (R2.13). No drive or tool reach is invented: the head code table leaves `FHT`/`BHT` drives null and the reach is a pilot default that says so. A contact is listed, not dropped; an unplaced screw, an instance with no face and a candidate pair are each a coverage row. A shank that disagrees with its name makes the screw suspected and its engagement unresolved. | PASS |
| II. Deterministic numerics, agentic investigation | The model computes no verdict | Every number comes from `checks/`; the three new tools take no argument (FR-026) and run before the first turn when checks first is on; the model's only role is to read the digest. The joint map, the placement and the stack-up are pure functions of the package and the profile, deterministic under any row order (a test shuffles). | PASS |
| III. Test-first with golden fixtures | Tests precede code; goldens for regression | Every task pair is test then implementation. Two synthetic fixtures shaped like the recorded runs, and a third for tolerances, each reproduced by its generator byte for byte; golden joint maps and results; every check has invalid-input, missing-input, unit and boundary tests, and every incomplete computation asserts `unresolved`. The extractor reads are tested with fakes before any seat sees them, and none enters a calculation until the seat run passes a known case (SC-008). | PASS |
| IV. Semantic fidelity and traceability | Persistent refs; versioned schemas; exported geometry supplementary | IR 1.5.0 is additive, versioned and omitted when empty; `ModelDimension` and `ModelAnnotation` carry persist refs, and annotations bind to holes only through face persist refs. Meshes enter one number - a screw's axial extent - only when the screw has no extracted face, labelled supplementary, and never a thread, a size or a tolerance (R2.13). | PASS |
| V. Engineered enough | DRY; explicit over clever; no speculative abstraction | One `axial_extent` replaces the fastener tool's private copy; one material-class table serves engagement and density; one zone-radius helper serves both alignment checks; one vector table tests two parsers; `check_placed_screw` shares the four rule functions with `check_fastener_joint`; one fold rule for patterned joints; one resolver for four sources. Thresholds, head codes, head dimensions, tool reach, densities and ISO 286 grades are data with sources. The one protocol (`ToleranceLookup`) has two real implementations. No per-tool repeat memory (008's guard is the one place). | PASS |
| VI. Findings inspectable, coverage tracked | Every finding reproducible; coverage on the report | Every finding cites its joint, instances, sizes with their sources, the rule row and the derivation; patterned joints fold into one finding that still names every joint; the joint map is coverage; contacts have their own section; unread components and body gaps are counted. Blanket exclusion is avoided: a thread-model contact is bounded by the annulus volume it can explain (R2.10). | PASS |
| Technical constraint: documents are read, not written | No mutation | Every extractor change is a read; the guard's denylist grows by the setters beside the tolerance and Hole Wizard families in the same change (R2.24). | PASS |
| Technical constraint: 2026 dependencies | None | Every interop member named exists in the 2024 SP5 interop by the analyst's metadata reflection; each is behind a reader seam and marked unverified until SC-008. | PASS |
| Technical constraint: no generic code execution exposed to the agent | Curated tools only | Three curated, argument-free check tools. | PASS |

**Post-design re-check**: no exception, no Complexity Tracking row.

## Project Structure

### Documentation (this feature)

```text
specs/010-mechanical-checks/
├── spec.md, plan.md, research.md, data-model.md, quickstart.md, tasks.md
├── contracts/{README.md, code-first.md, contacts.md, joint-map.md, alignment.md, fasteners.md,
│              tool-access.md, mass-material.md, hygiene.md, tolerances.md, fixtures.md}
├── contracts/fastener-name-vectors.json      # created by T039
└── checklists/requirements.md
```

### Source Code (repository root)

Every file this feature adds or changes, reconciled with what landed on 2026-09-23 (T102): a row
marked *landed as* is a file the tasks touched that this block did not name, a change it did not
describe, or a change it names that did not happen. A file not named here is not touched; in
particular `findings.py`, `checks/rms/*`, `checks/standards/*` other than `profile.py` and
`document.py`, every provider, `report/attention.py` other than `CHECKLIST_ITEM_IDS`, every page
script and every add-in file are **reused unchanged**. *Landed as*: `agent/runner.py` was changed
once, by the follow-up `7b63519` (feature 003's reduced-profile sentence ignores the new tolerance
phase), so it is listed below.

```text
reviewer/src/swreview/
├── geometry/axis.py                    # CHANGED: axial_extent(boxes, axis), is_axis_aligned(direction, deg)
├── checks/joints.py                    # NEW: HoleInstance, CylinderMember, Joint, Candidate, JointMapGap,
│                                       #      JointMap, build_joint_map, load_joint_rules, the fold helper
├── checks/joint_rules.yaml             # NEW: the thresholds (joint-map.md section 8)
├── checks/joint_alignment.py           # NEW: hole.nominal_alignment, hole.position_stack
├── checks/tolerances.py                # NEW: the subject and result types, NoSources (US3); the resolver (US8)
├── checks/iso286.yaml                  # NEW: IT grades, H and h classes
├── checks/fastener_names.py            # NEW: parse_fastener_name
├── checks/fastener_names.yaml          # NEW: head codes, kinds, heads
├── checks/fastener_identity.py         # NEW: recognise_fasteners, fastener.identity
├── checks/fastener.py                  # CHANGED: check_placed_screw, Placement, UsableThread; the four rule
│                                       #      functions take their derivation lines from the stack
├── checks/tool_access.py               # NEW: HeadGeometry, ToolChoice, HeadFit, fastener.head_fit
├── checks/head_dimensions.yaml         # NEW: ISO 4762, 7380, 10642, 4017/4014 dk and k
├── checks/tool_envelopes.yaml, .py     # CHANGED: reach_diameter_ratio per tool; head_tools
├── checks/material_classes.yaml, .py   # NEW: classes, match tokens, density ranges
├── checks/engagement_rules.yaml, .py   # CHANGED: steel 1.5; ratios by class name; tokens moved out
├── checks/mass.py                      # NEW: mass.material_assigned, mass.density, mass.assembly_override
├── checks/hygiene.py                   # NEW: the five hygiene.* checks
├── checks/documents.py                 # NEW, *landed as*: DocumentTree, the one walk the mass and hygiene
│                                       #      checks share (US6, US7)
├── checks/interference.py              # CHANGED: classify_group, CONTACT_VOLUME_MM3, thread-model rule (US4)
├── checks/result.py                    # CHANGED: permitted_radial_offset_mm
├── checks/hole_alignment.py            # CHANGED: compares with half the zone
├── checks/standards/profile.py         # CHANGED: version 2, GeneralToleranceSection, HygieneSection
├── checks/standards/document.py        # CHANGED: the data card's zero-match profile error
├── report/session.py                   # CHANGED: Contact, ReviewSession.contacts
├── report/markdown.py                  # CHANGED: ## Contacts when non-empty; interference_outcomes sentence
├── report/attention_policy_v1.yaml     # CHANGED: twelve classes
├── report/review_words_v1.yaml         # CHANGED, *landed as*: the joint map's coverage rows belong to the
│                                       #      hole-alignment goal (feature 009's words file)
├── report/attention.py                 # CHANGED (Polish): CHECKLIST_ITEM_IDS gains mass.material, hygiene
│                                       #      (*landed as*: not yet - T099 is open)
├── agent/checklist_v1.yaml             # CHANGED (Polish): two items (*landed as*: not yet - T099 is open)
├── agent/runner.py                     # CHANGED, *landed as*: FR-037's reduced-profile sentence ignores the
│                                       #      tolerance phase (`7b63519`)
├── tools/checks_mechanical.py          # NEW: CODE_FIRST_CHECKS, check_joints, check_mass_material, check_hygiene
├── tools/checks_interference.py        # CHANGED: the contact path
├── tools/checks_fastener.py            # CHANGED: _bbox_extent_mm delegates to geometry.axial_extent
├── tools/joint_context.py              # NEW, *landed as*: the one joint map and the mesh loading that
│                                       #      check_joints and the interference tool share (T049)
├── tools/measure.py                    # CHANGED, *landed as*: load_body_mesh, the one mesh reader (US4)
├── tools/context.py                    # CHANGED: record_contact
├── tools/registry.py                   # CHANGED: check_tools() gains the three tools
├── prerun.py                           # CHANGED: planned_calls reads CODE_FIRST_CHECKS; PRERUN_TOOLS; the two
│                                       #      rewritten not-evaluated lines; PrerunCall counts contacts;
│                                       #      coaxial_hole_pairs removed; (after 008) repeat_key entries
├── ir/models.py                        # CHANGED: 1.5.0 - HoleWizardData, ModelDimension, ModelAnnotation
└── benchmark/replay.py                 # CHANGED (after 008): reclassified-as-contact

reviewer/tests/
├── support/mechanical.py, support/fixture_denylist.py      # NEW (the latter shared with 008)
├── fixtures/mechanical/{generate_fixtures.py, big-assembly/, small-assembly/, tolerances/}  # NEW (each with
│                                                                  #      its `meshes/`)
├── fixtures/attention/{check-folder, review-folder}/package.json   # CHANGED, *landed as*: IR 1.5.0 (T077)
├── support/reuse.py                                        # CHANGED, *landed as*: IR 1.5.0 (T077)
├── unit/test_support_mechanical.py, test_mechanical_fixtures_are_fictional.py            # NEW
├── unit/test_joint_rules.py, test_joint_instances.py, test_joint_map.py,
│   test_joint_map_acceptance.py, test_code_first_registration.py                         # NEW
├── unit/test_interference_contacts.py, test_session_contacts.py, test_report_contacts.py,
│   test_contacts_acceptance.py                                                           # NEW
├── unit/test_tools_check_joints.py, test_joint_alignment.py, test_joint_stack.py         # NEW
├── unit/test_fastener_names.py, test_fastener_identity.py, test_placed_screw.py,
│   test_thread_model_contacts.py                                                         # NEW
├── unit/test_head_dimensions.py, test_tool_access.py                                     # NEW
├── unit/test_material_classes.py, test_mass.py, test_tools_check_mass_material.py        # NEW
├── unit/test_hygiene.py, test_tools_check_hygiene.py                                     # NEW
├── unit/test_ir_tolerances.py, test_iso286.py, test_general_tolerance.py, test_tolerances.py  # NEW
├── perf/test_joint_map_perf.py                                                            # NEW (*landed as*: in
│                                                                                          #      T101, which runs it)
├── unit/test_checks_result.py, test_ir_tolerances.py                                     # NEW, *landed as* (US3, US8)
├── unit/test_fastener_identity/big-assembly-with-fasteners.yml                           # NEW, *landed as*: a golden (US4)
├── unit/test_joint_map_on_replay_fixture.py, test_replay_code_first_checks.py             # NEW, *landed as* (T096, T097)
├── unit/test_ir_features.py, test_ir_phases.py, test_ir_profile.py, test_ir_reuse_fields.py,
│   test_ir_standards.py, test_remodel_intent.py, test_support_remodel.py                  # CHANGED, *landed as*: IR
│                                                                                          #      1.5.0 (T077, T086)
├── unit/test_docstring_split.py, test_tool_notes_prompt.py, test_tool_tiers.py           # CHANGED, *landed as*: the
│                                                                                          #      three new tools (US1-US7)
├── unit/test_code_first_registration/ (its opening-message golden)                       # CHANGED, *landed as* (US2)
├── unit/test_prerun_repeat_guard.py, test_replay_findings.py, test_replay_fixtures.py     # CHANGED, *landed as*
│                                                                                          #      (T092, T094)
├── unit/test_review_words.py, test_runner_reduced_profile.py                             # CHANGED, *landed as*
├── golden/test_golden/tool-envelope.yml, golden/test_standards_goldens.py                # CHANGED, *landed as* (US4, US7)
├── unit/test_geometry.py, test_checks_interference.py, test_tools_checks_interference.py,
│   test_checks_hole_alignment.py, test_engagement_rules.py, test_checks_fastener.py,
│   test_tool_envelopes.py, test_standards_profile.py, test_standards_no_company_values.py,
│   test_attention_catalogue.py, test_prerun_digest.py, test_provider_schema.py,
│   test_tool_payload.py, test_checklist.py, test_standards_document_rule.py, test_schema_sync.py  # CHANGED
│                                       #      (*landed as*: `test_checklist.py` waits for T098, open;
│                                       #      `test_schema_sync.py` passes unedited)
├── integration/test_coverage_stop.py                                                     # CHANGED (Polish;
│                                                                                          #      *landed as*: T098 open)
└── golden/test_golden/{joint-ok, joint-bottoming, thread-mismatch, cover-blind-tap}.yml  # CHANGED

extractor/SwReview.Extractor/
├── Fasteners/FastenerNameParser.cs     # CHANGED: vendor forms, file name, IsCandidate
├── Dump/FastenerDumper.cs              # CHANGED: the candidate gate
├── Dump/PropertyDumper.cs              # CHANGED: the override read
├── Dump/HoleDumper.cs                  # CHANGED: Hole Wizard reads through IHoleWizardReader
├── Dump/ToleranceDumper.cs             # NEW: model dimensions and annotations through their reader seams
├── Dump/SwHoleWizardReader.cs, Dump/SwToleranceReaders.cs   # NEW, *landed as*: the real readers behind the seams
├── Dump/DumpContracts.cs, Dump/SwDump.cs, Dump/SwDrawingReader.cs, Dump/GapCollector.cs   # CHANGED, *landed as*:
│                                       #      the seams' contracts, the phase wiring, the override gap (US6, US8)
├── Dump/PackageWriter.cs               # CHANGED: the tolerance phase row
├── Ir/Hole.cs, Ir/EvidencePackage.cs, Ir/ModelDimension.cs (NEW)   # CHANGED: 1.5.0
├── Ir/Enums.cs, Ir/Manifest.cs, Ir/Document.cs   # CHANGED, *landed as*: ModelDimensionType (T077), the
│                                       #      manifest (T086), the override read's documentation (T069);
│                                       #      `Ir/PackageSerializer.cs` needed no change
├── Guard/ReadOnlyGuard.cs              # CHANGED: the tolerance and Hole Wizard setters
└── Guard/CircuitBreaker.cs, Sw/SwGate.cs   # CHANGED, *landed as*: ExecuteOptional, a read whose failure is a
                                        #      gap and not a counted failure, through the gate (T086)
extractor/SwReview.Extractor.Tests/
├── FastenerNameParserTests.cs, PropertyDumperTests.cs, GuardTests.cs, RemodelGuardTests.cs,
│   IrSerializerTests.cs                                                                  # CHANGED (*landed as*:
│                                                                                          #      `IrContract.cs` needed no change)
├── PackageReuseTests.cs, PackageWriterTests.cs, SwGateTests.cs                          # CHANGED, *landed as* (T086)
├── FastenerCandidateTests.cs, HoleWizardReaderTests.cs, ToleranceDumperTests.cs          # NEW
├── FastenerNameVectors.cs                                                                # NEW, *landed as*: the vector
│                                                                                          #      table read by both parsers
└── Fakes/                              # CHANGED: the reader fakes (*landed as*: HoleWizardFakes.cs and
                                        #      ToleranceFakes.cs, new)

specs/
├── 001-agentic-design-review/contracts/{agent-tools.md, review-session.schema.json, ir.schema.json}
├── 004-resilient-remodeler/contracts/guard-allowlist.md
├── 005-llm-efficiency/contracts/levers.md
├── 006-standards-check/{contracts/profile.md, research.md (R5 rows)}
├── 007-attention-policy-gate/contracts/attention.md   # (*landed as*: the twelve classes, T100)
└── 008-checks-first-review/contracts/{checks-first.md, replay.md}   # CHANGED, *landed as*: the three repeat
                                                                    #      keys (T093), the reclassification (T095)
config/standards.example.yaml, reviewer/tests/fixtures/standards/profile-{a,b}.yaml   # CHANGED: version 2
docs/llm-efficiency-options.md          # CHANGED, *landed as*: the tool-array figures regenerated for the three
                                        #      new tools (US1, US2, T067, T075)
README.md                               # CHANGED, *landed as*: the three checks, the engagement rule, profile
                                        #      version 2 (T100)
```

**Structure Decision**: both trees extended in place, as every feature since 002. The joint map,
the alignment, the fastener identity, tool access, mass, hygiene and tolerances are modules under
`checks/` because each is a deterministic check or its input; the three tools share one module
because they share one registration tuple. Contacts live in `report/session.py` because they are
recorded on the session, like findings.

## Phase 0 and Phase 1

Research in [research.md](research.md) (R1 to R6). Design in [data-model.md](data-model.md) and
[contracts/](contracts/). Twelve points tasks must honour:

1. **Instances, not rows.** The joint map explodes each `Hole` into instances by face axis; no
   code in this feature reads `Hole.axis` as the axis of a hole (R2.1).
2. **Three gates, one partner per component, candidates listed.** The thresholds are data; a
   near miss and an assignment loser are coverage, never findings (R2.2).
3. **Placement by face, then by origin, never by box.** An unplaced fastener is counted (R2.3).
4. **No number the evidence does not contain.** Tolerances only through the resolver; thread
   depth only from `thread_depth` or a labelled through-tapped length; the mesh only for a screw
   extent with no face; a pilot default says so (R2.7, R2.13, R2.15, R2.18).
5. **One stack for the placed screw.** `check_placed_screw` reuses the four rule functions;
   `check_fastener_joint` and its goldens do not move (R2.13).
6. **Contacts are a list, not findings and not coverage.** The ranking never reads them; the
   replay reclassifies rather than losing them (R2.9).
7. **The registration tuple is the only hook into the pre-run.** Empty, it changes nothing;
   each story adds one name; 008's guard keys them `(tool,)` when it exists (R2.20).
8. **Fold patterns, keep passes where a calculation exists.** One finding per identical result in
   a pattern group; rule checks count passes in coverage (R2.21).
9. **The engagement rule is the owner's, and the change is visible.** Steel to 1.5, both rows
   citing the decision; the three goldens and two unit rows edited deliberately (R2.14).
10. **Profile version 2 lands once, in five files.** The loader reads 1 and 2; the example, two
    fixtures, 006's contract block and 006's R5 rows change together (R2.19).
11. **Every extractor read is behind a seam with a fake, and the guard grows with it.** None of
    them feeds a calculation before SC-008 (R2.24).
12. **Every new id is classed in the same change that emits it** (R2.22).

## Delivery order

| Order | Story | Deliverable | Needs SOLIDWORKS |
|---|---|---|---|
| 1 | Setup | the builders, the generator, the two shaped fixtures, the denylist test | No |
| 2 | Foundational | `axial_extent`; the joint rules and the joint map; the registration tuple; profile version 2 | No |
| 3 | **US1** (P1) | contacts: classification, the session list, the tool path, the report section, the counts | No |
| 4 | **US2** (P1) | `check_joints` recording the map; the acceptance numbers | No |
| 5 | **US3** (P2) | the zone-radius fix; nominal alignment and the budget; the stack-up against `NoSources` | No |
| 6 | **US4** (P2) | the Python parser and vectors; recognition and placement; the 1.5 x d rule; the placed screw; the thread-model contact; the C# parser and candidate gate (code and fakes) | Validation only |
| 7 | **US5** (P3) | the head table; reach and head tools; tool access; head fit | No |
| 8 | **US6** (P3) | material classes; the mass checks; `check_mass_material`; the override read (code and fakes) | Validation only |
| 9 | **US7** (P4) | hygiene; the data card's profile error; `check_hygiene` | No |
| 10 | **US8** (P2) | IR 1.5.0; the ISO 286 table and the general block; the resolver feeding the stack; the guard; the Hole Wizard and tolerance readers (code and fakes) | Validation only |
| 11 | 008 integration | repeat keys; the replay's contact reclassification; the joint map over 008's replay fixture; SC-006 | No, after the named 008 tasks |
| 12 | Polish | the two checklist items; docs; the quickstart | No |
| 13 | Workstation | SC-008 and a review of 830-02342 | Yes |

**Sequencing that is not negotiable.** The fixtures before any check, because every acceptance
test reads them. The joint map before US2 to US5. US3's stack-up before US8's resolver (the
resolver only replaces `NoSources`). Profile version 2 before US7 and US8. The C# parser after the
Python parser and its vector table. Every [W] task after its code task.

**Sequencing against the other features.** 010 can land entirely before 008: under lever 5 or 11
the pre-run already runs `CODE_FIRST_CHECKS`; 008 later makes that the pane default. The files
both features change - `prerun.py`, `tools/registry.py`, `report/session.py`,
`report/markdown.py`, `review-session.schema.json`, `specs/001/contracts/agent-tools.md`,
`test_tool_payload.py`, `test_prerun_digest.py`, `levers.md`, `report/attention.py` - are listed
per task in `tasks.md` so they are never edited by both at once; Phase 11 lands only after the 008
task it names. 010 changes no provider and not `agent/runner.py`. With feature 011: the IR minor
and the profile version go to whichever lands first (R5); 011 fills the resolver's drawing slot.
With feature 009: 010 supplies `contacts`, findings and coverage; 009 renders them.

**External dependencies**: feature 005's pre-run and levers; feature 006's standards profile and
run; feature 007's attention policy and catalogue test; feature 008 for the pane default, the
guard, the replay and live interference rows; the recorded packages for the probes (not for
tests).

## Risks and mitigations

| # | Risk | Mitigation |
|---|---|---|
| RK-1 | A wrong pairing produces an authoritative-looking wrong finding (the analyst's OQ-4 concern). | Three gates and one partner per component; the values each joint was judged on are recorded; near misses are candidates; golden joint maps on both fixtures; the joint map over 008's replay fixture must reproduce the verified counts (T096). |
| RK-2 | Placement by origin assigns a screw to the wrong joint on a vendor model whose origin is off-axis. | The origin must lie on an instance axis within 0.2 mm **and** a basis vector must be parallel; a screw on two axes is unplaced; the parsed size is cross-checked against the tapped thread by `thread_match` anyway. |
| RK-3 | The mesh-based screw extent is approximate. | Used only without a face; the tessellated end planes are flat, so the extent along the axis is exact to the chordal tolerance, which the calculation states; never used for a size. |
| RK-4 | Folding hides a joint that differs. | The fold key includes the calculation result, so differing joints are separate findings; every folded finding lists every joint id. |
| RK-5 | The 1.5 x d reading of "1.td" is wrong. | Recorded in the spec, the checklist, research R2.14 and the data file's header; a change is one data edit and three goldens. |
| RK-6 | The report grows long on a big assembly. | Patterned joints fold; rule checks count passes in coverage; unresolved-for-everyone cases are one coverage row; presentation is feature 009's. |
| RK-7 | Profile version 2 breaks the owner's real profile. | The loader keeps reading version 1; the new sources simply stay absent until the owner writes version 2. |
| RK-8 | 008 and 010 edit the same files. | The shared-file list in `tasks.md`; Phase 11 after the named 008 tasks; 010's prerun edits are three small hunks. |
| RK-9 | The seat reads return nothing useful (MBD not used, fit classes empty). | The resolver's other sources still work; the stack-up says which source was searched; SC-008 records what came back. |
| RK-10 | The extractor candidate gate emits non-fasteners as fasteners. | `IsCandidate` needs a kind and a size, is tested with the shared vectors, and the Python recognition still cross-checks the shank. |
| RK-11 | The thread-model rule hides a real screw interference. | Bounded by the annulus volume the thread model explains; anything larger stays a finding. |

## Complexity Tracking

None. No constitution exception, no mutation path, no new transport, provider or agent stage.
The one protocol has two implementations; the three tools share one registration tuple; the
profile version bump is forced by the profile's own every-key-required rule.
