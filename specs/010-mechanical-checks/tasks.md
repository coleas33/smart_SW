---

description: "Task list for the automatic mechanical checks"
---

# Tasks: Automatic Mechanical Checks

**Input**: Design documents from `/specs/010-mechanical-checks/` (`spec.md`, `plan.md`, `research.md`, `data-model.md`, `contracts/`, `quickstart.md`)

**Prerequisites**: features 001 to 007 on main. **Feature 008 is not a prerequisite** for Phases 1 to 10 and 12: every check here is a plain function over the package and an argument-free tool, and joins the pre-run through `CODE_FIRST_CHECKS` (T014), which lever 5 and lever 11 already run today and 008 makes the pane default. Phase 11 lands only after the named 008 task. Phase 13 needs the licensed seat of the next sitting. The recorded packages are never read by a test and never enter the repository.

**Tests**: REQUIRED, and **strictly test-first**: every implementation task below is preceded by the test task that must be written and must fail first. Every golden of `report/markdown.render_report`, every existing check golden except the three engagement goldens T042 names, `Finding`, `CoverageItem`, `InvestigationStep`, `chat-events.schema.json`, the MCP function list and the terminal profile do not move. The tests that go red **by design** when a change lands are named in the task that lands it (research R3) and each is edited deliberately in that task, never loosened.

**Organization**: Setup (the synthetic fixtures), Foundational (the joint map, the registration point, profile version 2), US1 contacts, US2 the joint map as a check, US3 alignment and the stack-up, US4 fasteners, US5 tool access, US6 mass and material, US7 hygiene, US8 tolerances, the integration with feature 008, Polish, and the workstation sitting.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on another unfinished task)
- **[Story]**: `US1` to `US8`; Setup, Foundational, Integration and Polish tasks carry no story tag
- **[W]**: needs the licensed SOLIDWORKS seat of the next sitting; the code and fake-reader tests of every [W] read land earlier with no seat
- **[008]**: lands only after the named feature 008 task is on main

## Path Conventions

- Python: `reviewer/src/swreview/`, tests in `reviewer/tests/`
- C#: `extractor/SwReview.Extractor/`, tests in `extractor/SwReview.Extractor.Tests/`
- Contracts: `specs/010-mechanical-checks/contracts/`; other features' contracts are edited in the task that changes their shape

---

## Phase 1: Setup

**Purpose**: the fixtures every acceptance test reads, built by code from fictional strings and the geometry research R3 verified, so no recorded byte enters the repository (`contracts/fixtures.md`).

- [x] T001 [P] Write `reviewer/tests/unit/test_support_mechanical.py`: the builders produce packages that validate as `EvidencePackage` at 1.4.0; a hole feature is one `Hole` row whose `face_ids` hold N cylinder faces on N distinct axes (the feature shape of research R2.1), a counterbore instance two diameters; a screw is a component whose document `file_name` is `<HEAD>_M<d>-<p>X<L>_FICT-<nnnn>.SLDPRT` and whose `Description` is `<KIND>, <abbr> M<d>-<p> X <L> MM, FICTIONAL`, with a body mesh and optionally a shank face; interference rows carry a volume, `is_possible` and settings; STL meshes are tiny closed boxes and cylinders written by `trimesh`; **re-running the generator reproduces every committed fixture byte for byte**; the big fixture carries exactly the counts of `contracts/fixtures.md` section 2 (26 documents, 23 parts, 3 assemblies, 89 components of which 2 lightweight and 1 suppressed, 27 hole rows with 132 instances, two rows with no cylinder face, 68 named screws over 9 documents, 113 interference groups of which 8 carry a positive volume) and every case row; the small fixture 3 documents, 4 components, 4 hole rows with 16 instances, one 3.0 mm pin in a 3.0 mm hole, two zero-volume rows
- [x] T002 Implement `reviewer/tests/support/mechanical.py` on top of `tests/support/packages.py build_package` (hole features with instances, free cylinder faces, screws in the vendor shape, pins, interference rows, documents with material, mass, volume and properties, meshes), every string from one fictional syllable vocabulary and every path under `C:\Fictional\`. Acceptance: T001's builder assertions green
- [x] T003 Write `reviewer/tests/fixtures/mechanical/generate_fixtures.py` (run from `reviewer/`; reads nothing but the T002 builders; module docstring naming what each fixture reproduces and that it holds no recorded string) and commit `reviewer/tests/fixtures/mechanical/big-assembly/` and `small-assembly/` (`package.json` plus `meshes/*.stl`). Acceptance: T001 green including the regeneration assertion
- [x] T004 [P] Write `reviewer/tests/unit/test_mechanical_fixtures_are_fictional.py`: over `tests/fixtures/mechanical/` every `path`, `vault_path` and `full_path` starts with `C:\Fictional\`; every `file_name`, `Description`, component `name` and property value is built from the T002 vocabulary or is a size, an id or a library material name already used by a committed golden (`6061-T6`, `Alloy Steel`); when `%LOCALAPPDATA%\SwReview\fixture-denylist.txt` exists, no token of three or more characters from it appears in any fixture file or in `specs/010-mechanical-checks/contracts/fastener-name-vectors.json` once it exists, and the test is skipped naming the missing file where it does not
- [x] T005 Implement `reviewer/tests/support/fixture_denylist.py` (`load_denylist() -> frozenset[str] | None`, `offending_tokens(text, denylist)`) over the same `%LOCALAPPDATA%\SwReview\fixture-denylist.txt` feature 008's T018 refreshes; if 008's T010 (`tests/support/scramble.py`) or T017 (`test_replay_fixture_hygiene.py`) is already on main with a reader of that file, import it instead of writing a second one. Acceptance: T004 green; `test_standards_no_company_values.py` green

**Checkpoint**: two committed packages shaped like the recorded runs, reproducible by code, fictional by test.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: the joint map US2 to US5 run on; the one hook into the pre-run every story registers through; profile version 2, which US7 and US8 read.

- [x] T006 [P] Extend `reviewer/tests/unit/test_geometry.py`: `axial_extent(boxes, axis) -> tuple[float, float]` returns the min and max projection of the eight corners of every box on the unit axis relative to `axis.origin`, in metres; exact for an axis-aligned box; `is_axis_aligned(direction, deg)` true within the angle of a coordinate axis and false at 30 degrees; a zero-length direction raises `ValueError` naming it; and `tools/checks_fastener._bbox_extent_mm` returns the numbers it returns today (the existing `test_tools_checks_fastener.py` assertions unchanged)
- [x] T007 Implement `axial_extent` and `is_axis_aligned` in `reviewer/src/swreview/geometry/axis.py`; make `reviewer/src/swreview/tools/checks_fastener.py _bbox_extent_mm` delegate to `axial_extent` (research R2.13, DRY). Acceptance: T006 green; `test_tools_checks_fastener.py` unchanged and green
- [x] T008 [P] Write `reviewer/tests/unit/test_joint_rules.py`: `checks/joint_rules.yaml` loads to `JointRules` with the values of `contracts/joint-map.md` section 8 and a `source` for each; a negative value, an angle of 90 degrees or more, and a missing key are each refused naming the key; the loader caches per resolved path like `engagement_rules.load_rules`
- [x] T009 Implement `reviewer/src/swreview/checks/joint_rules.yaml` and `load_joint_rules` in `reviewer/src/swreview/checks/joints.py`. Acceptance: T008 green
- [x] T010 [P] Write `reviewer/tests/unit/test_joint_instances.py`: a `Hole` with 15 cylinder faces on 15 axes is 15 instances named `#1` to `#15` in order of smallest face id; a counterbore with bore and counterbore faces on each of four axes is four instances each with two diameters; a hole with no cylinder face, one on a lightweight component, and one whose face axis is zero-length each give a `JointMapGap` and no instance; `bore_mm` is the smallest diameter and `size_source` is `face`; a `Hole.diameter` present wins with `size_source = "hole_wizard"`; `axis_aligned` is false for a 30-degree axis and the `r sin θ` bound is recorded
- [x] T011 [P] Write `reviewer/tests/unit/test_joint_map.py` with small hand-built packages (`tests/support/mechanical.py`): each gate of `contracts/joint-map.md` section 2 passes and fails at its boundary; same-component pairs are never considered; the one-partner rule keeps the smaller offset and lists the loser as `assigned_elsewhere`; a near miss on exactly one gate within the margin is `angle_near`, `overlap_near` or `gap_near`, and a miss on two gates is nothing; a screw-through-two-plates stack is one joint of three instances; every rule of section 4 (a screw at its minor diameter and at its major diameter in a tapped bore; a head in a counterbore; a face on a part with holes is a gap, not a member; a member coaxial with two instances counted once) and every kind rule of section 6 in order; joint ids, instance ids and the JSON of the whole map are byte-identical when every array of the package is shuffled; a package with no holes and a `model_check` package give an empty map with one gap each; the pairing of 30-degree axes works (the gates use extents on any axis) and marks the joint not `axis_aligned`
- [x] T012 Implement `reviewer/src/swreview/checks/joints.py` per `contracts/joint-map.md` sections 1 to 6 and `data-model.md` section 1: `HoleInstance`, `CylinderMember`, `Joint`, `Candidate`, `JointMapGap`, `JointMap`, `build_joint_map(package, rules=None, fasteners=None)` (the `fasteners` argument accepted and unused until T041), and `fold_by_pattern(results)` (research R2.21, used from US3). Acceptance: T010 and T011 green
- [x] T013 [P] Write `reviewer/tests/unit/test_code_first_registration.py`: with `CODE_FIRST_CHECKS` monkeypatched to a fake argument-free tool registered in a test dispatch, `prerun.planned_calls` returns it with `{}` after every interference group and before `check_standards`; a withheld name is not planned and its tier sentence reaches the digest through `PRERUN_TOOLS`; every name in the real tuple is a tool in `check_tools()` whose signature takes no parameter; and with the real tuple empty the opening message of `test_prerun_digest.py`'s fixture is **byte-identical** to today's (its existing assertions unedited)
- [x] T014 Create `reviewer/src/swreview/tools/checks_mechanical.py` holding `CODE_FIRST_CHECKS: tuple[str, ...] = ()` and its docstring (`contracts/code-first.md` section 1); in `reviewer/src/swreview/prerun.py` make `planned_calls` append `(name, {})` for each name not withheld after the interference groups and add the tuple to `PRERUN_TOOLS`. **Shared with 008** (`prerun.py`). Acceptance: T013 green; `test_prerun_digest.py`, `test_prerun_same_session.py`, `test_gate_same_session.py` unchanged and green
- [x] T015 [P] Extend `reviewer/tests/unit/test_standards_profile.py`: a version 2 profile with `general_tolerance` (contiguous ordered bands, `angular_deg` optional) and `hygiene` loads; a version 2 profile missing either section is refused naming it; overlapping or unordered bands are refused naming them; a version 1 profile still loads with both sections absent; version 3 is refused naming both; and **edit deliberately** the field tests of `test_standards_no_company_values.py` that go red when the example, the two fixtures and 006's contract block gain the fields (research R2.19): they must still carry exactly the same fields and differ in every value-bearing field, and `specs/006-standards-check/research.md` R5 must name each new field; and name the ten standards goldens under `tests/golden/test_golden/standards-*.yml` that record a fixture profile's `sha256`, which T016 regenerates
- [x] T016 Implement version 2 in `reviewer/src/swreview/checks/standards/profile.py` (`PROFILE_VERSION = 2`, versions 1 and 2 accepted, `LinearBand`, `GeneralToleranceSection`, `HygieneSection`, optional on version 1 and required on version 2); move `config/standards.example.yaml`, `reviewer/tests/fixtures/standards/profile-a.yaml`, `profile-b.yaml` and the block in `specs/006-standards-check/contracts/profile.md` to version 2 with fictional values that agree nowhere; add one R5 row per new value-bearing field to `specs/006-standards-check/research.md` ("not carried by the macro"). Regenerate the standards goldens T015 names with `--force-regen` and confirm each diff is the profile `sha256` line only. Acceptance: T015 green; `test_standards_no_company_values.py`, `test_standards_run.py` and `tests/golden/test_standards_goldens.py` green

**Checkpoint**: the joint map exists as a pure function, the pre-run reads a tuple nothing is in yet, and the profile can declare a general tolerance.

---

## Phase 3: User Story 1 - Every Detected Interference Is Judged, and Contacts Are Not Clashes (Priority: P1) 🎯 MVP

**Goal**: a zero-volume or possible-only group is a contact on its own list; positive volumes stay findings; every group is judged and counted.

**Independent Test**: judging the big fixture's 113 groups yields 8 findings and 105 contacts, none of the contacts in "Start here"; the small fixture's two zero-volume rows are one contact; a positive-volume group is the finding it is today. No licence, no key.

- [x] T017 [P] [US1] Write `reviewer/tests/unit/test_interference_contacts.py` for `classify_group` (`contracts/contacts.md` section 1): rules 1 to 4 and 6 each fire on their own and in precedence (uncomputed beats an exception beats a contact; rule 5 is T048's); a volume of exactly `CONTACT_VOLUME_MM3` is a contact and just above is a finding; `0.0 m3`, `0.0 in3` and `0.0 mm3` are all contacts; volume `None` with `is_possible` is `possible_only`, without it the suspected finding of today; a mixed group is a finding whose inputs list the zero-volume member; the `Contact` names both components, the configuration, the group key, the member ids and the volume in mm3; and **edit deliberately** `test_checks_interference.py:314-320` (`test_a_possible_interference_without_a_volume_is_suspected`) to expect a contact, the only existing assertion this moves
- [x] T018 [US1] Implement `classify_group`, `GroupOutcome` and `CONTACT_VOLUME_MM3` in `reviewer/src/swreview/checks/interference.py`, keeping `check_interference_group`'s decision order for rules 1 to 3 and 6 byte-identical in its results (rule 5 arrives in T049). Acceptance: T017 green; `bracket-assy-interference` golden unchanged
- [x] T019 [P] [US1] Write `reviewer/tests/unit/test_session_contacts.py`: `Contact` validates and refuses an unknown field; `ReviewSession.contacts` defaults to empty and is **omitted** from `session.json` when empty, so every committed session fixture round-trips to its own bytes; a session with contacts validates against `review-session.schema.json` (`contract_validator`), where `contacts` is in `properties` and not in `required`; contact ids are allocated `C-001` onward
- [x] T020 [US1] Implement `Contact`, its id allocator and `ReviewSession.contacts` in `reviewer/src/swreview/report/session.py` (omitted when empty, in the manner of `ir/models.omit_additive`); add the property to `specs/001-agentic-design-review/contracts/review-session.schema.json`. **Shared with 008** (`report/session.py`, the schema). Acceptance: T019 green; `test_session.py` and `test_usage_contracts.py` green
- [x] T021 [P] [US1] Extend `reviewer/tests/unit/test_tools_checks_interference.py`: a zero-volume group returns `{"status": "contact", ...}` (`contracts/contacts.md` section 3), appends one `Contact` whose `tool_result_ids` name the current step, records no finding, emits no `finding` event and writes no coverage beyond today's; a positive-volume group returns exactly today's payload; an excepted zero-volume group is still the excepted finding; `ToolContext.record_contact` refuses outside a review session
- [x] T022 [US1] Implement the contact path in `reviewer/src/swreview/tools/checks_interference.py` and `record_contact` in `reviewer/src/swreview/tools/context.py`. Acceptance: T021 green
- [x] T023 [P] [US1] Write `reviewer/tests/unit/test_report_contacts.py`: a session with contacts renders `## Contacts` after `## Findings` with the sentence and table of `contracts/contacts.md` section 4, counts from `interference_outcomes`; a session without contacts renders byte-identically to today (`test_report_tokens.py`'s golden and every `render_report` golden unchanged); the contact rows carry no `%`
- [x] T024 [US1] Implement `interference_outcomes(session, package)` in `reviewer/src/swreview/checks/interference.py` and the section in `reviewer/src/swreview/report/markdown.py`. **Shared with 008** (`report/markdown.py`). Acceptance: T023 green
- [x] T025 [P] [US1] Write `reviewer/tests/unit/test_contacts_acceptance.py` over the fixtures: a session that calls `check_interference_group` for every key `groups_of` enumerates judges 113 of 113 groups - 8 findings, 105 contacts, `interference_outcomes` equal - and `attention.rank` over it places no contact and no zero-volume group in its rows (SC-001); the small fixture yields one contact naming the pin and the plate; with lever 5 on, `PrerunCall.line()` reads `ok, 1 contact` for a contact group and `ok, 1 finding` for a finding
- [x] T026 [US1] Make `PrerunCall` in `reviewer/src/swreview/prerun.py` carry the contacts a call recorded and count them in `line()`. **Shared with 008** (`prerun.py`; when 008's aggregated line exists, the contact count joins it as `contracts/contacts.md` section 3 shows). Acceptance: T025 green; `test_prerun_digest.py` unchanged (its fixture has no contact)

**Checkpoint**: every group judged, contacts listed apart, the ranking untouched by them.

---

## Phase 4: User Story 2 - The Assembly's Joints Are Found by Code (Priority: P1)

**Goal**: `check_joints()`, argument-free, records the joint map as coverage and joins the pre-run.

**Independent Test**: on the big fixture the map holds 50 joints in 11 pattern groups with the two candidates, the 0.750 mm dowel joint among them, and none of the 49 mm-apart first-instance pairs; on the small fixture one pin joint; with lever 5 on, `check_joints` is a pre-run step. No licence, no key.

- [x] T027 [P] [US2] Write `reviewer/tests/unit/test_tools_check_joints.py`: `check_joints()` takes no argument; records one `checked` `joint.map` item per pattern group, one `skipped` per candidate and per gap, and the two package-level `skipped` rows of `contracts/joint-map.md` section 7; returns the counts of `contracts/code-first.md` section 3; `CODE_FIRST_CHECKS == ("check_joints",)`; and **edit deliberately** the pins that move when a tool registers: `test_provider_schema.py:148` (32 to 33, with the row added to `specs/001-agentic-design-review/contracts/agent-tools.md`), `test_tool_payload.py`'s `REVIEW_TOOL_COUNT` and its array byte constants (regenerated in T028, never hand-typed), and every parametrized docstring and schema test over `TOOL_FUNCTIONS`, which the new tool must pass unedited
- [x] T028 [US2] Implement `check_joints` in `reviewer/src/swreview/tools/checks_mechanical.py` (the map and its coverage; no finding yet), add it to `check_tools()` in `reviewer/src/swreview/tools/registry.py`, set `CODE_FIRST_CHECKS = ("check_joints",)`, add the tool row to `specs/001-agentic-design-review/contracts/agent-tools.md`, regenerate the byte constants in `reviewer/tests/unit/test_tool_payload.py` and the tool-array byte counts quoted in `specs/005-llm-efficiency/contracts/levers.md`. **Shared with 008** (`tools/registry.py`, `test_tool_payload.py`, `levers.md`, `agent-tools.md`). Acceptance: T027 green; `test_mcp_server.py` unchanged (check tools are not in the MCP list)
- [x] T029 [P] [US2] Write `reviewer/tests/unit/test_joint_map_acceptance.py`: the big fixture's foundational map equals `contracts/joint-map.md` section 9 exactly and matches a golden `test_joint_map_acceptance/big-assembly.yml` through `file_regression`; `hol:0004`/`hol:0010` are three joints at 0.000 mm, `hol:0017`/`hol:0027` one, `hol:0010`/`hol:0024` none (research R4); the small fixture holds one pin joint at 0.000 mm; with lever 5 on, `check_joints` is a real step after the interference groups (FR-004 to FR-006, SC-003 in part). Acceptance: green on the T012 and T028 code with no edit to it

**Checkpoint**: the joints are found by code and the review records them before the first turn.

---

## Phase 5: User Story 3 - Holes Line Up, and the Stack-Up Is Computed (Priority: P2)

**Goal**: nominal alignment and the budget callout for every joint; the worst-case stack with a declared model; `hole.coaxiality` compares with half the zone.

**Independent Test**: the 0.750 mm dowel offset is demonstrated against 0.050 mm allowed; the small fixture's pin passes with a zero budget; with no tolerance source one skipped item covers every stack; with a fake lookup the three verdicts fall where `contracts/alignment.md` says. No licence, no key.

- [x] T030 [P] [US3] Write the zone rule tests: `reviewer/tests/unit/test_checks_result.py` (or the module that covers `checks/result.py`) - `permitted_radial_offset_mm(0.2) == 0.1`, a negative zone raises; extend `reviewer/tests/unit/test_checks_hole_alignment.py` with the boundary row 0.15 mm against a 0.2 mm zone, **within before and demonstrated after**, and assert `zone_mm` and `permitted_offset_mm` in the result; the existing rows at `:67-80` and `:82-92` stay unedited and green (research R2.8)
- [x] T031 [US3] Implement `permitted_radial_offset_mm` in `reviewer/src/swreview/checks/result.py` and use it in `reviewer/src/swreview/checks/hole_alignment.py` (the comparison, the two result keys, the assumption line of `contracts/alignment.md` section 3). Acceptance: T030 green; FR-009
- [x] T032 [P] [US3] Write `reviewer/tests/unit/test_joint_alignment.py` for `hole.nominal_alignment`: the fixed and floating sums with every `F` source of research R2.5 in precedence; a tapped term of 0; a negative term demonstrated naming the fastener and the hole; `offset > allowed` demonstrated with both numbers and `offset == allowed` checked within scope; `F` or `H` unknown unresolved naming it; the callout text of both fixtures; a line-to-line pass carries the no-clearance limit; oblique axes are measured (`axis_distance` works at any angle); mixed-unit sizes (an inch clearance hole for a metric screw) are compared in mm with the conversion in `inputs`; and the fold: 15 identical joints of one pattern group are one finding naming 15 joints
- [x] T033 [US3] Implement the nominal half of `reviewer/src/swreview/checks/joint_alignment.py` (`ClearanceTerm`, `NominalAlignment`, `check_nominal_alignment(joint, package) -> CheckResult`). Acceptance: T032 green
- [x] T034 [P] [US3] Write `reviewer/tests/unit/test_joint_stack.py` against a fake `ToleranceLookup`: the `size_and_position` model when every contributor resolves, `size_only` with each unresolved position in `excluded_effects` with its `searched` list, unresolved naming the size contributor and `searched`; the three verdicts at their boundaries (`max(0, e - z) > c_max`; `e + z <= c_min`; between); a screw's `F_max = F_min =` its nominal with no tolerance needed; every `ResolvedTolerance.cited` in `inputs` and `limits_mm` the only limit reader; a conflict becomes a coverage limit; with `NoSources`, the tool path writes one `skipped` `hole.position_stack` item for all joints and no finding
- [x] T035 [US3] Create `reviewer/src/swreview/checks/tolerances.py` with `ToleranceSubject`, `SourceKind`, `ResolvedTolerance`, `UnresolvedTolerance`, the `ToleranceLookup` protocol and `NoSources` (`data-model.md` section 5), and implement `check_position_stack(joint, package, lookup)` in `reviewer/src/swreview/checks/joint_alignment.py`. Acceptance: T034 green
- [x] T036 [US3] Extend `reviewer/tests/unit/test_tools_check_joints.py`: on the big fixture the dowel joint is `hole.nominal_alignment` demonstrated (0.750 against 0.050, floating) and the screw pattern groups pass or are unresolved as their sizes allow, folded one finding per identical result per pattern group; the stack is the one skipped item; and **edit deliberately**: `test_attention_catalogue.py:72,74` gains `joint_alignment` as a source (two ids), and `test_prerun_digest.py:124-135` expects the rewritten `hole_alignment` line of `contracts/code-first.md` section 4 instead of "1 coaxial hole pair" (SC-003)
- [x] T037 [US3] Wire both checks into `check_joints` (`reviewer/src/swreview/tools/checks_mechanical.py`, through `run_joint_checks`); classify `hole.nominal_alignment` and `hole.position_stack` as `interface` in `reviewer/src/swreview/report/attention_policy_v1.yaml`; rewrite the `hole_alignment` not-evaluated line in `reviewer/src/swreview/prerun.py` when `check_joints` is planned and remove `coaxial_hole_pairs` and its `__all__` entry, which nothing else calls (it has no test of its own; when `check_joints` is withheld the family carries the tier's sentence instead) (**shared with 008**: `prerun.py`, `attention_policy_v1.yaml`, `test_prerun_digest.py`). Acceptance: T036 green; `test_gate_brief.py` green (the blind-spot sentence for `hole_alignment` is still printed when the family is not evaluated)

**Checkpoint**: every joint's alignment is judged at nominal size with a callout, and the stack says what it would need.

---

## Phase 6: User Story 4 - Fasteners Are Recognised and Their Threads Checked (Priority: P2)

**Goal**: screws recognised by name and cross-checked; thread match, engagement and bottoming from the placed geometry against 1.5 x d; the thread-model contact; then the extractor's parser and candidate gate.

**Independent Test**: 68 of 68 named screws recognised; one thread-match finding for the two M4-in-M5 joints; the M10, M2 and M3 engagements demonstrated short; the screw named M5 with a 3.3 mm shank suspected. No licence, no key (the extractor half is tested with fakes).

- [x] T038 [P] [US4] Write `reviewer/tests/unit/test_fastener_names.py`: every row of `specs/010-mechanical-checks/contracts/fastener-name-vectors.json` parses to its expected answer; the vendor file name and description forms, the Toolbox forms `FastenerNameParser` reads today, the unified inch forms, a hyphen pitch, a bare integer length, an unknown head code (size still read, kind null), `FHT` and `BHT` with a null drive, and text with no size (`None`); the order file name, description, configuration and the cross-check between them (FR-011)
- [x] T039 [US4] Implement `reviewer/src/swreview/checks/fastener_names.py` and `reviewer/src/swreview/checks/fastener_names.yaml` (head codes, kinds, heads; `SHC` with `drive: hex_socket`, `BHT` and `FHT` with `drive: torx` - flat and button head Torx, owner answer 2026-09-23, research R5), and create `specs/010-mechanical-checks/contracts/fastener-name-vectors.json` with fictional strings only (`contracts/fasteners.md` section 2). Acceptance: T038 green; T004's scan covers the vector file
- [x] T040 [P] [US4] Write `reviewer/tests/unit/test_fastener_identity.py`: a `Fastener` row wins and its name cross-checks; a named component becomes a `RecognisedFastener` per instance with an in-memory `Fastener` that validates; the shank band of research R2.12 (8.5 mm for M10x1.5, 3.3 mm for M4-0.7, 6.75 mm for M8x1.25 and 3.0 mm for M3 agree; 3.3 mm for M5x0.8 disagrees; no shank is `unmeasured`); placement by face, then by origin (on the axis within 0.2 mm **and** a basis vector parallel), a screw on two joints' axes unplaced with both named; the mesh extent used only without a face and labelled `mesh`; and `build_joint_map(..., fasteners=...)` forms a one-instance joint for a screw placed on a lone instance, pinned by a golden `test_fastener_identity/big-assembly-with-fasteners.yml`
- [x] T041 [US4] Implement `reviewer/src/swreview/checks/fastener_identity.py` (`recognise_fasteners`, `CHECK_IDENTITY`, the `fastener.identity` check) and the `fasteners` argument of `build_joint_map` in `reviewer/src/swreview/checks/joints.py`. Acceptance: T040 green; T029's foundational golden unchanged
- [x] T042 [P] [US4] Write the engagement rule change: extend `reviewer/tests/unit/test_engagement_rules.py` (steel resolves to 1.5 citing the owner decision, aluminium 1.5 citing it, cast iron and plastic unchanged, the header records the "1.td" reading) and **edit deliberately** `test_engagement_rules.py:42-43` (steel 1.0) and `test_checks_fastener.py:229-254` (the class-choice test re-expressed with a contrast the new table still has: steel against plastic at 2.0 x d), naming the three goldens T043 regenerates (research R2.14)
- [x] T043 [US4] Edit `reviewer/src/swreview/checks/engagement_rules.yaml` per `contracts/fasteners.md` section 5; regenerate `reviewer/tests/golden/test_golden/joint-ok.yml`, `joint-bottoming.yml` and `thread-mismatch.yml` with `--force-regen` and confirm the diff is only the aluminium `source` string. Acceptance: T042 green; every other golden unchanged
- [x] T044 [P] [US4] Write `reviewer/tests/unit/test_placed_screw.py` for `check_placed_screw` (`contracts/fasteners.md` section 4): the protrusion from the tip below the entry; a blind hole's usable thread from `thread_depth` measured inward from the tapped face's entry, a through-tapped hole's from its face extent labelled derived, and `hole_depth` never read (a package whose `hole_depth` would clear the joint still fails); a blind hole with no `thread_depth` and an `unknown` end condition unresolved naming it; an oblique axis unresolved when the extent comes from faces and computed when it comes from a mesh; a `disagrees` screw unresolved; bottoming at its boundary; a through-tapped part thinner than 1.5 x d gives `fastener.engagement` at severity `low` carrying the sheet thickness, and a blind or thicker part short of the rule gives the normal severity (owner answer 2026-09-23, research R5); thread match reused byte-for-byte from `_thread_match`; every result carries the derivation lines; and `check_fastener_joint`'s tests and goldens are unedited and green
- [x] T045 [US4] Implement `check_placed_screw`, `Placement` and `UsableThread` in `reviewer/src/swreview/checks/fastener.py`, the four rule functions taking their derivation lines from the stack. Acceptance: T044 green; `test_checks_fastener.py` (apart from T042's edit) and the fastener goldens unchanged
- [x] T046 [US4] Extend `reviewer/tests/unit/test_tools_check_joints.py` with the fastener block over the big fixture: 68 of 68 named screws recognised (SC-004); one `fastener.thread_match` finding, demonstrated, naming both M4-in-M5 joints (SC-002); the engagement table of research R2.13 (M10 10.225 against 15.0, M2 2.205 against 3.0, M3 1.394 against 4.5 with the derived label, the M8 and two M3 passes); the screw named M5 with a 3.3 mm shank one `fastener.identity` suspected finding; unplaced screws are skipped `joint.map` rows; and **edit deliberately** `test_attention_catalogue.py` (the identity id) and `test_prerun_digest.py:124-135` (the rewritten `fastener_joint` line instead of "1 fastener")
- [x] T047 [US4] Wire recognition, placement and `check_placed_screw` into `check_joints` (`reviewer/src/swreview/tools/checks_mechanical.py`); classify `fastener.identity` as `interface`; rewrite the `fastener_joint` not-evaluated line in `reviewer/src/swreview/prerun.py` (**shared with 008**). Acceptance: T046 green; FR-012, FR-013
- [x] T048 [P] [US4] Write `reviewer/tests/unit/test_thread_model_contacts.py`: a positive-volume group between a screw and its tapped part at or below `π/4 · (d² - D²) · L` is a `thread_model` contact linked to the joint; one above it stays a finding; a group between a screw and a part it is not jointed with stays a finding; a screw modelled at its minor diameter never reaches the rule
- [x] T049 [US4] Implement rule 5 of `contracts/contacts.md` section 1 in `reviewer/src/swreview/checks/interference.py`, with `tools/checks_interference.py` passing the joint map built from the context's package (built once per session and cached on the context). Acceptance: T048 green; T025 still green
- [x] T050 [P] [US4] Extend `extractor/SwReview.Extractor.Tests/FastenerNameParserTests.cs` to read every row of `fastener-name-vectors.json` whose `csharp` is not false and assert `FastenerNameParser.Parse(configurationName, description, fileName)`, and add `FastenerCandidateTests.cs` for `FastenerNameParser.IsCandidate(fileName, description, configuration)` (a kind and a size from any source; Toolbox-only today's behaviour unchanged); the existing parser tests unedited
- [x] T051 [US4] Extend `extractor/SwReview.Extractor/Fasteners/FastenerNameParser.cs` with the vendor forms, the file-name source, the hyphen pitch and `IsCandidate`. Acceptance: T050 green
- [x] T052 [P] [US4] Extend `FastenerCandidateTests.cs` with the dumper's gate as a pure static `FastenerDumper.IsFastenerCandidate(isToolbox, fileName, description, configuration)`: a Toolbox component always; a non-Toolbox component whose file name parses; one whose description parses; one whose configuration name parses; a plate named with no size never
- [x] T053 [US4] Replace the Toolbox-only gate at `extractor/SwReview.Extractor/Dump/FastenerDumper.cs:53-58` with `IsFastenerCandidate` and pass the file name to the parser; the shank-face request is unchanged and now reaches every candidate. Acceptance: T052 green; `dotnet test` green; the seat run is T106

**Checkpoint**: the screws are known, their threads matched, their engagement measured where the geometry allows and unresolved where it does not.

---

## Phase 7: User Story 5 - A Tool Can Reach Every Screw Head (Priority: P3)

**Goal**: the head from the joint, the tool and reach from tables, the sweep against every other body, head fit against the head table.

**Independent Test**: the covered head is demonstrated naming the overhanging part; the clear head passes; the 12.0 mm counterbore under an M8 socket head is demonstrated. No licence, no key.

- [x] T054 [P] [US5] Write `reviewer/tests/unit/test_head_dimensions.py`: `checks/head_dimensions.yaml` loads rows by head type and size with `dk_max_mm`, `k_max_mm` and, for countersunk heads, the angle, each standard with a source; an unknown head type or size is `None`; a non-positive value is refused
- [x] T055 [US5] Implement `reviewer/src/swreview/checks/head_dimensions.yaml` (ISO 4762, 7380, 10642, 4017/4014 for M2 to M12, entered from the standards with the source line) and its loader in `reviewer/src/swreview/checks/tool_access.py`. Acceptance: T054 green
- [x] T056 [P] [US5] Extend `reviewer/tests/unit/test_tool_envelopes.py`: every tool carries a positive `reach_diameter_ratio` with its pilot-default source; `head_tools` maps the head types of `contracts/tool-access.md` section 2; a tool without a reach is refused; **edit deliberately** the shape rows that pin the table's keys; `check_tool_envelope`'s tests unedited
- [x] T057 [US5] Add `reach_diameter_ratio`, `head_tools` and a Torx key envelope (for the `torx` drive of `FHT` and `BHT`, pilot default, research R5) to `reviewer/src/swreview/checks/tool_envelopes.yaml` and `reach_mm` to `reviewer/src/swreview/checks/tool_envelopes.py`. Acceptance: T056 green
- [x] T058 [P] [US5] Write `reviewer/tests/unit/test_tool_access.py` with synthetic meshes: the outward direction away from the tapped instance; the head plane from the mesh, else the shank face plus `k_max` labelled derived, else unresolved; the tool from the drive, else the head type, else unresolved naming the head code; the raycast from the head plane outward over every other component's mesh, the screw's own excluded; a blocking body named with its distance; an unloadable mesh unresolved naming it; no mesh in the package one skipped `fastener.head_clearance` item for all joints; lazy meshes (lever 10a) name the unfetched components
- [x] T059 [US5] Implement `HeadGeometry`, `ToolChoice` and the sweep in `reviewer/src/swreview/checks/tool_access.py`, passing the envelope into `check_placed_screw`. Acceptance: T058 green
- [x] T060 [US5] Extend `reviewer/tests/unit/test_tools_check_joints.py` and `test_tool_access.py` with head fit (`contracts/tool-access.md` section 4: counterbore diameter and depth against `dk_max` and `k_max`, a countersink unresolved until US8's diameter exists, an oblique counterbore unresolved) and the acceptance rows of section 5 on the big fixture; **edit deliberately** `test_attention_catalogue.py` (the head-fit id); FR-014, FR-015
- [x] T061 [US5] Implement `fastener.head_fit` in `reviewer/src/swreview/checks/tool_access.py`, wire tool access and head fit into `check_joints`, classify `fastener.head_fit` as `interface`. Acceptance: T060 green

**Checkpoint**: head clearance stops being always unresolved.

---

## Phase 8: User Story 6 - Every Part Has a Believable Mass and a Material (Priority: P3)

**Goal**: one material-class table; the three mass checks and the coverage count; `check_mass_material`; the override read fixed in the extractor.

**Independent Test**: 2700 kg/m3 aluminium passes; 1000 kg/m3 demonstrated; the 2.000 kg sub-assembly suspected; unread parts counted; the override read answers through the fakes. No licence, no key.

- [x] T062 [P] [US6] Write `reviewer/tests/unit/test_material_classes.py`: `material_classes.yaml` loads; every token today's `engagement_rules.yaml` carries resolves to the same class as today (a table-driven comparison against the current classes, so the move changes no classification); density ranges and the no-material density with sources; the default class carries no range; and **edit deliberately** the shape rows of `test_engagement_rules.py` that read `matches` from the engagement file, which now reads ratios by class name
- [x] T063 [US6] Create `reviewer/src/swreview/checks/material_classes.yaml` and `material_classes.py`; move the match tokens out of `reviewer/src/swreview/checks/engagement_rules.yaml` and make `engagement_rules.py for_material` resolve through `material_classes.for_material`. Acceptance: T062 green; `test_checks_fastener.py`, the fastener goldens and T042's rows unchanged
- [x] T064 [P] [US6] Write `reviewer/tests/unit/test_mass.py` for every row of `contracts/mass-material.md` section 2 (each override state, each density case including within 2 percent of 1000, an overridden part given no density verdict, each assembly case including the sum within 0.1 percent and the round-grams case) and the coverage count of section 3 from `document` and `body` gaps; the standards family's `material_assigned` tests unedited
- [x] T065 [US6] Implement `reviewer/src/swreview/checks/mass.py` (`run_mass_checks(package)`). Acceptance: T064 green
- [x] T066 [US6] Write `reviewer/tests/unit/test_tools_check_mass_material.py`: the tool takes no argument, returns the counts, records passes of `mass.material_assigned` as one `checked` item and density passes as findings (research R2.21); on the big fixture every part with a mass and a volume has a verdict (SC-005) and the section 5 rows hold; `CODE_FIRST_CHECKS` gains `"check_mass_material"`; and **edit deliberately** `test_attention_catalogue.py` (three ids), `test_provider_schema.py:148` and `agent-tools.md` (one more tool), and `test_tool_payload.py`'s constants
- [ ] T067 [US6] Implement `check_mass_material` in `reviewer/src/swreview/tools/checks_mechanical.py`, register it in `tools/registry.py`, append it to `CODE_FIRST_CHECKS`, classify the three ids as `manufacturing`, regenerate the payload constants and the `levers.md` byte counts. **Shared with 008** (`tools/registry.py`, `test_tool_payload.py`, `levers.md`, `agent-tools.md`, `attention_policy_v1.yaml`). Acceptance: T066 green
- [x] T068 [P] [US6] Extend `extractor/SwReview.Extractor.Tests/PropertyDumperTests.cs`: the override is read from the object `CreateMassProperty()` returns through the `IMassProperty` delegate; when that read throws, from `CreateMassProperty2()` through the `GetOverrideOptions` delegate; when both throw, null plus one `mass_override` gap naming both paths; the observer records exactly the members read; the existing tests unedited
- [x] T069 [US6] Implement the two-path read at `extractor/SwReview.Extractor/Dump/PropertyDumper.cs:128-140` per `contracts/mass-material.md` section 4; `ReadMassOverridden` keeps its signature. Acceptance: T068 green; the seat run is T103

**Checkpoint**: every part with a mass has a verdict, assemblies' overrides are flagged, and the read is ready for the seat.

---

## Phase 9: User Story 7 - The House Rules Are Checked (Priority: P4)

**Goal**: the five hygiene checks, the data card's zero-match profile error, `check_hygiene`.

**Independent Test**: the part-number mismatch, the shared description, the missing revision and the lightweight component are findings; with a version 1 profile the property checks are skipped naming the setting; a zero-match pattern is a likely profile error. No licence, no key.

- [x] T070 [P] [US7] Write `reviewer/tests/unit/test_hygiene.py` for every row of `contracts/hygiene.md` section 2 with a version 2 fictional profile: the configuration property before the custom one; case-insensitive stripped comparisons; one duplicate finding per value naming every document and never the same document twice; `unloaded` left to coverage; with a version 1 profile, an empty setting, and no profile, the skipped items naming the setting; passes counted in one `checked` item per check; unread documents in `hygiene.coverage`; no property name in `reviewer/src/` (the no-company-values scan)
- [x] T071 [US7] Implement `reviewer/src/swreview/checks/hygiene.py` (`run_hygiene_checks(package, profile=None)`). Acceptance: T070 green
- [x] T072 [P] [US7] Extend `reviewer/tests/unit/test_standards_document_rule.py`: a non-empty pattern matching none of the graded documents makes each document's data-card result unresolved with the reason of `contracts/hygiene.md` section 4; a pattern matching one document keeps today's skip for the others; matching semantics unchanged; and **edit deliberately** every standards golden whose pattern matches no graded document (the task greps `tests/golden/fixtures/standards-*` and lists them in its commit message)
- [x] T073 [US7] Implement the zero-match rule in `reviewer/src/swreview/checks/standards/document.py`. Acceptance: T072 green; FR-020
- [x] T074 [US7] Write `reviewer/tests/unit/test_tools_check_hygiene.py`: no argument; the profile read from the attached standards run and never loaded by the tool; the section 5 rows on the big fixture; `CODE_FIRST_CHECKS` gains `"check_hygiene"`; and **edit deliberately** `test_attention_catalogue.py` (five ids), `test_provider_schema.py:148` and `agent-tools.md`, and `test_tool_payload.py`'s constants
- [ ] T075 [US7] Implement `check_hygiene` in `reviewer/src/swreview/tools/checks_mechanical.py`, register it, append it to `CODE_FIRST_CHECKS`, classify the five ids as `hygiene`, regenerate the payload constants and the `levers.md` byte counts. **Shared with 008** (as T067). Acceptance: T074 green; FR-019

**Checkpoint**: the house rules read like findings a non-developer can act on.

---

## Phase 10: User Story 8 - Tolerances Are Read Wherever the Team Puts Them (Priority: P2)

**Goal**: IR 1.5.0; the ISO 286 table and the general block; the resolver feeding the stack-up; the guard; the Hole Wizard, dimension and annotation readers with fakes.

**Independent Test**: the tolerances fixture's joint gets a size-only worst case citing each source; a subject no source binds stays unresolved naming every source searched; a 1.4.0 package round-trips to its own bytes; the readers write what the fakes return and a gap for every read that throws. No licence, no key.

- [x] T076 [P] [US8] Write `reviewer/tests/unit/test_ir_tolerances.py`: `HoleWizardData`, `ModelDimension`, `ModelAnnotation` validate and refuse unknown fields and bad id patterns; `Hole.wizard` omitted when null and the two arrays omitted when empty, so every committed 1.4.0 package (the golden fixtures and `tests/fixtures/mechanical/`) round-trips to its own bytes; a 1.5.0 package with the members round-trips; and **edit deliberately** `test_schema_sync.py`'s expectation of the regenerated `ir.schema.json` and the tests that pin `SCHEMA_VERSION`
- [x] T077 [US8] Implement the three models and `SCHEMA_VERSION = "1.5.0"` in `reviewer/src/swreview/ir/models.py`; regenerate `specs/001-agentic-design-review/contracts/ir.schema.json` with `ir.schema.export_schema()`. Acceptance: T076 green; `test_ir_*` green
- [x] T078 [P] [US8] Extend `extractor/SwReview.Extractor.Tests/IrSerializerTests.cs` and `IrContract.cs`: the C# mirrors serialize the members with the Python names, omit them when null or empty, and `CurrentSchemaVersion == "1.5.0"`; a 1.4.0 fixture round-trips
- [x] T079 [US8] Implement `extractor/SwReview.Extractor/Ir/ModelDimension.cs` (with `ModelAnnotation` and `HoleWizardData`), the `Hole.Wizard` member, the two arrays on `EvidencePackage.cs` and their omission in `PackageSerializer.cs`. Acceptance: T078 green
- [x] T080 [P] [US8] Write `reviewer/tests/unit/test_iso286.py` (`H7` on 10 mm is `+0.015/0`, `h6` on 10 mm `0/-0.009`, the range boundaries, a class outside the table binds nothing) and `reviewer/tests/unit/test_general_tolerance.py` (a nominal selects the band with `over < nominal <= up_to`; outside every band nothing; a version 1 profile nothing; the `Dimension` built is `symmetric` citing the profile identity and never a profile value)
- [x] T081 [US8] Implement `reviewer/src/swreview/checks/iso286.yaml` (entered from ISO 286-1 with the source line) and the table and general-block readers in `reviewer/src/swreview/checks/tolerances.py`. Acceptance: T080 green
- [x] T082 [P] [US8] Write `reviewer/tests/unit/test_tolerances.py` for `resolve_tolerance` over small 1.5.0 packages built by `tests/support/mechanical.py` (extended in this task with `wizard`, `ModelDimension` and `ModelAnnotation` builders, which T084 then uses for the committed fixture): each source of `contracts/tolerances.md` section 4 binds on its own; precedence when several bind, with `also_found`; a conflict; the model dimension that binds by unique value and the equal pair that binds nothing; the annotation bound by face persist ref and one attached elsewhere not bound; `hole_position` never bound by the general block; the drawing slot returning "not available before feature 011"; an unresolved subject naming every source and why; no path that returns a limit without a bound source (SC-007)
- [x] T083 [US8] Implement `resolve_tolerance` and the resolver lookup in `reviewer/src/swreview/checks/tolerances.py`, with `drawing_tolerance` as the slot of section 6. Acceptance: T082 green; FR-021 to FR-025 on the Python side
- [x] T084 [US8] Generate `reviewer/tests/fixtures/mechanical/tolerances/package.json` with the T002 builders (extended for 1.5.0; `contracts/fixtures.md` section 2) and extend `reviewer/tests/unit/test_tools_check_joints.py`: with the version 2 fictional profile the dowel joint's stack is `size_only` with `H7` from the Hole Wizard (as built: from the hole's model dimension, where a hole's ISO class arrives - the Hole Wizard's `HoleFit` is a screw clearance fit, the C# lane found; `contracts/fixtures.md` section 2) and the pin size from the model dimension, a figure and a verdict, each source cited; with a version 1 profile the general source is listed as searched; with no source anywhere the one skipped item remains (US8 Independent Test)
- [x] T085 [US8] Make the resolver the default lookup of `check_joints` (`reviewer/src/swreview/tools/checks_mechanical.py`), the profile from the attached standards run; `NoSources` stays for tests. Acceptance: T084 green; T034 and T036 green
- [x] T086 [P] [US8] Extend `extractor/SwReview.Extractor.Tests/GuardTests.cs` (`StandardsDenylistTests`) and `RemodelGuardTests.cs`: every setter `contracts/tolerances.md` section 2 lists is refused; **edit deliberately** the membership counts both classes pin, and record the rows in `specs/004-resilient-remodeler/contracts/guard-allowlist.md`
- [x] T087 [US8] Add the setters to `extractor/SwReview.Extractor/Guard/ReadOnlyGuard.cs` under a "feature 010" block. Acceptance: T086 green
- [x] T088 [P] [US8] Write `extractor/SwReview.Extractor.Tests/HoleWizardReaderTests.cs` with a fake `IHoleWizardReader` in `Fakes/`: every field written as the fake returns it, in metres or degrees; a field whose read throws is null with one `hole_wizard` gap naming it; the hole's other fields unchanged; `thread_depth` still written only for a tapped blind hole
- [x] T089 [US8] Introduce `IHoleWizardReader` (the interop implementation reading `IWizardHoleFeatureData2`) and fill `Hole.Wizard` in `extractor/SwReview.Extractor/Dump/HoleDumper.cs`. Acceptance: T088 green; the seat run is T104
- [x] T090 [P] [US8] Write `extractor/SwReview.Extractor.Tests/ToleranceDumperTests.cs` with fake `IDimensionToleranceReader` and `IModelAnnotationReader`: a diameter dimension with a bilateral tolerance becomes a `ModelDimension` with the kind and limits and its persist ref; a fit tolerance records both classes; a `gtol` records symbols, values, datums and attached face persist refs; a datum tag its label; each throwing read a gap; the `tolerance` phase row written, and skipped by the `model_check` and `standards` profiles (**edit deliberately** the phase-list tests that pin the phase names)
- [x] T091 [US8] Implement `extractor/SwReview.Extractor/Dump/ToleranceDumper.cs` with the two reader seams and their interop implementations, and the `tolerance` phase in `Dump/PackageWriter.cs`. Acceptance: T090 green; the seat run is T105

**Checkpoint**: every tolerance source the owner named has a place to arrive, and the stack-up uses whatever arrives, citing it.

---

## Phase 11: Integration with Feature 008 [008]

**Purpose**: the three pieces that depend on 008's code. Each lands only after the named 008 task.

- [ ] T092 [008] Extend `reviewer/tests/unit/test_prerun_repeat_guard.py` (008 T043): `repeat_key` maps `check_joints`, `check_mass_material` and `check_hygiene` to `(tool,)`; a repeat after the pre-run records one step, no finding, and returns the recorded digest. After 008 T044
- [ ] T093 [008] Add the three keys to `repeat_key` in `reviewer/src/swreview/prerun.py` and document them in `specs/008-checks-first-review/contracts/checks-first.md` section 5 and `specs/001-agentic-design-review/contracts/agent-tools.md`. Acceptance: T092 green
- [x] T094 [008] Extend `reviewer/tests/unit/test_replay_findings.py` (008 T021): a recorded `interference.static` finding whose group key and configuration equal a replayed contact's is reported as reclassified as contact and not counted as lost, and the exit stays 0 when that is the only difference (`contracts/contacts.md` section 6). After 008 T023
- [x] T095 [008] Implement the reclassification in `reviewer/src/swreview/benchmark/replay.py` and record it in 008's `contracts/replay.md`. Acceptance: T094 green
- [x] T096 [008] Write `reviewer/tests/unit/test_joint_map_on_replay_fixture.py`: the foundational joint map over 008's big-assembly replay fixture reproduces research R3's counts (132 instances, 47 kept pairs, 50 joints, 11 pattern groups, the two candidates) - geometry survives 008's scrambling, which renames strings only (RK-1). Test only. After 008 T018
- [ ] T097 [008] Write the SC-006 acceptance beside 008's replay tests (`reviewer/tests/unit/test_replay_code_first_checks.py`): replaying the big-assembly fixture with checks first shows `check_joints`, `check_mass_material` and `check_hygiene` as pre-run steps and no added model round. Test only. After 008 T023 and 008's checks-first tasks, and after T075

---

## Phase 12: Polish

- [ ] T098 Extend `reviewer/tests/unit/test_checklist.py`: two items `mass.material` (`check_prefix: mass.`) and `hygiene` (`check_prefix: hygiene.`) load and close on their findings and on their summary coverage; and **edit deliberately** `tests/integration/test_coverage_stop.py`'s round counts and spare call indices, the `cover-blind-tap` golden (regenerated for a diff of exactly two more open checklist items) and `report/attention.py CHECKLIST_ITEM_IDS`' guard in `test_attention.py`. After T067 and T075
- [ ] T099 Add the two items to `reviewer/src/swreview/agent/checklist_v1.yaml` and to `CHECKLIST_ITEM_IDS` in `reviewer/src/swreview/report/attention.py` (**shared with 008**). Acceptance: T098 green; `test_prefix_stability.py` green
- [ ] T100 [P] Update `README.md` (the three checks in the review section; the owner's engagement rule; profile version 2 for the owner's real profile) and `specs/007-attention-policy-gate/contracts/attention.md` (the twelve classes)
- [ ] T101 [P] Run `quickstart.md` Scenarios 0 to 11 and the regression gate (`uv run pytest -q`, `uv run ruff check src tests`, `dotnet build`/`dotnet test SwReview.sln -c Release`), including `reviewer/tests/perf/test_joint_map_perf.py` (`-m perf`: `build_joint_map` under 200 ms, `check_joints` under 2 s on the big fixture); fix anything they surface in the task that owns it
- [ ] T102 [P] Re-validate `specs/010-mechanical-checks/checklists/requirements.md` against the amended spec (research R4); reconcile `plan.md`'s Source Code block with what landed

---

## Phase 13: The next workstation sitting

- [ ] T103 [W] Dump 810-11249 and 830-02342 with the new build: `mass_overridden` present on every document and no `mass_override` tool-error gap; record which read path answered in `research.md` (SC-008)
- [ ] T104 [W] The same dumps: `Hole.wizard` filled on every Hole Wizard hole, every field or a named gap; record the raw fit and thread classes seen, so `iso286.yaml`'s coverage and `fastener_names.yaml` can be checked against them (SC-008)
- [ ] T105 [W] The same dumps: `model_dimensions` and `model_annotations` present where the models carry them, or empty with no gap where they do not; record whether the team uses DimXpert or MBD (research R5) (SC-008)
- [ ] T106 [W] The same dumps: the 68 named screws emitted as fasteners, each with a shank face; the joint checks then compute engagement for screws that had no face before; no non-fastener emitted (RK-10)
- [ ] T107 [W] With feature 008 on main: a pane review of 830-02342 with checks first judges every interference group, lists contacts apart and outside "Start here", records the joint, mass and hygiene findings before the first model turn, and spends no model round on them (SC-001, SC-006); the result is recorded in the next handover document

---

## Dependencies & Execution Order

### Phase dependencies

- **Setup (Phase 1)**: no dependencies
- **Foundational (Phase 2)**: T006-T012 after Setup; T013-T014 and T015-T016 independent of the joint map and of each other
- **US1 (Phase 3)**: after Setup; independent of the joint map until T049 (in US4)
- **US2 (Phase 4)**: after T012 and T014
- **US3 (Phase 5)**: after US2
- **US4 (Phase 6)**: after US2; T049 also after US1; the C# tasks T050-T053 after T039 (the vector table)
- **US5 (Phase 7)**: after US4 (placed screws)
- **US6 (Phase 8)**: after Setup and T014; independent of the joint map
- **US7 (Phase 9)**: after Setup, T014 and T016
- **US8 (Phase 10)**: T076-T079 and T086-T091 after Setup; T080-T085 after T016 and US3
- **Integration (Phase 11)**: each task after the 008 task it names and after the 010 tool it keys
- **Polish (Phase 12)**: after every story chosen for the checkpoint; T098 after T067 and T075
- **Workstation (Phase 13)**: T103 after T069; T104 after T089; T105 after T091; T106 after T053; T107 after US1 to US7 and 008

### Task-level dependencies

- T002 after T001; T003 after T002; T005 after T004
- T007 after T006; T009 after T008; T012 after T010, T011, T009 and T007; T014 after T013; T016 after T015
- T018 after T017; T020 after T019; T022 after T021, T018 and T020; T024 after T023 and T020; T026 after T025 and T022
- T028 after T027, T012 and T014; T029 after T028
- T031 after T030; T033 after T032 and T012; T035 after T034 and T033; T036 after T035 and T031; T037 after T036
- T039 after T038; T041 after T040 and T039; T043 after T042; T045 after T044; T046 after T045, T043 and T041; T047 after T046; T049 after T048, T047 and T022; T051 after T050 and T039; T053 after T052 and T051
- T055 after T054; T057 after T056; T059 after T058, T055, T057 and T047; T061 after T060 and T059
- T063 after T062; T065 after T064 and T063; T067 after T066 and T065; T069 after T068
- T071 after T070 and T016; T073 after T072; T075 after T074 and T071
- T077 after T076; T079 after T078; T081 after T080 and T016; T083 after T082 and T081; T084 after T082 and T077; T085 after T084, T083 and T037; T087 after T086; T089 after T088 and T087; T091 after T090, T087 and T079
- T093 after T092; T095 after T094; T099 after T098

### Parallel opportunities, by file ownership

- **Phase 1**: T001 and T004 together (two new test files).
- **Phase 2**: T006, T008, T010, T011, T013, T015 are six test files that can be written together; the implementations touch disjoint files - `geometry/axis.py` and `tools/checks_fastener.py` (T007), `checks/joints.py` and `joint_rules.yaml` (T009, then T012), `tools/checks_mechanical.py` and `prerun.py` (T014), `checks/standards/profile.py` and the five profile files (T016) - so T007, T014 and T016 can land in parallel.
- **US1, US6 and US7 in parallel with the joint-map line** (US2 to US5): US1 owns `checks/interference.py`, `tools/checks_interference.py`, `tools/context.py`, `report/session.py`, `report/markdown.py`; US6 owns `checks/material_classes.*`, `checks/mass.py`, `checks/engagement_rules.*` (after T043), `PropertyDumper.cs`; US7 owns `checks/hygiene.py`, `checks/standards/document.py`. None of them touches `checks/joints.py`, `joint_alignment.py`, `fastener*.py` or `tool_access.py`.
- **The files several stories edit, sequentially and never in parallel**: `tools/checks_mechanical.py` (T014, T028, T037, T047, T061, T067, T075, T085), `tools/registry.py` and `test_tool_payload.py` (T028, T067, T075), `test_attention_catalogue.py` and `attention_policy_v1.yaml` (T036-T037, T046-T047, T060-T061, T066-T067, T074-T075), `prerun.py` (T014, T026, T037, T047, T093), `test_tools_check_joints.py` (T027, T036, T046, T060, T084), `checks/interference.py` (T018, T024, T049).
- **US8's extractor half in parallel with everything Python**: T078-T079, T086-T091 own `extractor/` files only (with T050-T053 and T068-T069 the other extractor tasks, on disjoint files: `FastenerNameParser.cs`, `FastenerDumper.cs`, `PropertyDumper.cs`, `HoleDumper.cs`, `ToleranceDumper.cs`, `Ir/*`, `ReadOnlyGuard.cs`).
- **Test files per story that can be written together**: US3 T030, T032, T034; US4 T038, T040, T042, T044, T048, T050, T052; US5 T054, T056, T058; US6 T062, T064, T068; US7 T070, T072; US8 T076, T078, T080, T082, T086, T088, T090.

### Files shared with feature 008's likely changes

Sequenced so no file is edited by both features at once; when both are in flight, the 010 task waits for the 008 task that touches the same file to merge, then rebases:

| File | 010 tasks | 008's change there |
|---|---|---|
| `reviewer/src/swreview/prerun.py` | T014, T026, T037, T047, T093 | live interference call, `PrerunGuard`/`repeat_key`, aggregated digest lines |
| `reviewer/src/swreview/tools/registry.py` | T028, T067, T075 | step sizes in `record_call`, `get_finding` under slimming |
| `reviewer/src/swreview/report/session.py`, `review-session.schema.json` | T020 | `folded_families`, `model_view`, step sizes |
| `reviewer/src/swreview/report/markdown.py` | T024 | the folded group section, the cache-split line, the largest steps |
| `reviewer/src/swreview/report/attention.py` | T099 (`CHECKLIST_ITEM_IDS` only) | the family fold in `rank()` |
| `reviewer/src/swreview/report/attention_policy_v1.yaml` | T037, T047, T061, T067, T075 | none planned; listed because the fold may add a row |
| `specs/001-agentic-design-review/contracts/agent-tools.md` | T028, T067, T075, T093 | `get_finding`, entity ids on the bridge tools, `already_run` |
| `reviewer/tests/unit/test_tool_payload.py`, `specs/005-llm-efficiency/contracts/levers.md` | T028, T067, T075 | slimmed-array constants; levers 5 and 6 adopted |
| `reviewer/tests/unit/test_prerun_digest.py` | T036, T046 | the digest's new lines |
| `reviewer/tests/support/fixture_denylist.py` | T005 | the denylist reader of 008 T010/T017 (one reader of `fixture-denylist.txt`, whoever lands first) |
| `reviewer/src/swreview/benchmark/replay.py` | T095 | 008's module |

010 does not touch any provider module or `agent/runner.py`.

---

## Requirement coverage

Every functional requirement and success criterion has at least one task whose acceptance would fail if it were not met.

| FR | Tasks | FR | Tasks |
|---|---|---|---|
| FR-001 | T017, T024, T025 | FR-015 | T054, T055, T060, T061 |
| FR-002 | T017, T018, T019, T020, T021, T022 | FR-016 | T062 to T065 |
| FR-003 | T017, T018, T021 | FR-017 | T064, T065 |
| FR-004 | T010 to T012, T027 to T029 | FR-018 | T064, T065, T068, T069, T103 |
| FR-005 | T010, T012, T032 | FR-019 | T070, T071, T074, T075 |
| FR-006 | T011, T012, T027, T029 | FR-020 | T072, T073 |
| FR-007 | T032, T033, T036 | FR-021 | T076 to T079, T088, T089, T104 |
| FR-008 | T032, T033 | FR-022 | T076, T090, T091, T105 |
| FR-009 | T030, T031 | FR-023 | T015, T016, T080, T081 |
| FR-010 | T034, T035, T084, T085 | FR-024 | T082, T083 (the drawing slot) |
| FR-011 | T038 to T041, T050 to T053, T106 | FR-025 | T034, T082, T083 |
| FR-012 | T044 to T047 | FR-026 | T013, T014, T028, T067, T075, T092, T093, T097 |
| FR-013 | T042 to T047 | FR-027 | T036, T046, T060, T066, T074 |
| FR-014 | T056 to T061 | FR-028 | T019, T020, T076, T077, T015, T016 |

| SC | Tasks | SC | Tasks |
|---|---|---|---|
| SC-001 | T025, T107 | SC-005 | T066 |
| SC-002 | T046 | SC-006 | T097, T107 |
| SC-003 | T029, T036 | SC-007 | T034, T044, T082 |
| SC-004 | T046 | SC-008 | T103 to T106 |

---

## Notes

- **Instances, not rows.** A task that reads `Hole.axis` as a hole's axis has misread the feature: a `Hole` is a Hole Wizard feature with up to 16 instances, and the joint map works on instances from the faces (research R2.1). The existing `hole.coaxiality` keeps its model-chosen pair and gains only the zone fix.
- **No number the evidence does not contain.** A tolerance comes through `resolve_tolerance` or not at all; a thread depth from `thread_depth` or a labelled through-tapped length, never `hole_depth` and never a blind face's extent; a drive or a reach from a data file that says it is a pilot default or stays unknown. A task that adds a fallback value has broken Principle I, and SC-007 is the test.
- **Contacts are a list, never findings, never coverage.** The ranking never reads them; the replay reclassifies rather than losing them.
- **The registration tuple is the only hook into the pre-run.** A check that needs its own pre-run branch, or a per-tool repeat memory, is a second copy of something 008 owns.
- **Fold patterns, keep calculations.** One finding per identical result per pattern group; a pass with a calculation is a finding, a pass of a rule is a count.
- **The owner's rule is visible.** 1.5 x d into steel and aluminium, read from "1.td"; the file header, the spec, research R2.14 and the three regenerated goldens all say so.
- **Fixtures are code.** Nothing from the recorded packages is committed; the probes that verified research R3 read them outside the repository and printed ids and millimetres only.
- **Every extractor read has a fake before it has a seat,** and none feeds a calculation before T103 to T106 pass.
