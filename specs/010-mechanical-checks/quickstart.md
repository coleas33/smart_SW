# Quickstart: Validating the Automatic Mechanical Checks

**Feature**: `010-mechanical-checks` | **Plan**: [plan.md](plan.md) | **Contracts**: [contracts/](contracts/)

Scenarios 0 to 11 run **offline**, with no SOLIDWORKS licence and no key. Scenario 12 needs
feature 008 on main. Scenarios 13 and 14 are marked **[W]** and need the licensed seat of the next
sitting.

## Prerequisites

Features 001 to 007 on main. The committed fixtures `reviewer/tests/fixtures/mechanical/
big-assembly/` (shaped like 830-02342) and `small-assembly/` (shaped like 810-11249), and, from
US8, `tolerances/`; the vector table `specs/010-mechanical-checks/contracts/fastener-name-vectors.json`;
the two version 2 test profiles under `reviewer/tests/fixtures/standards/`.

```powershell
cd reviewer
$big = "tests/fixtures/mechanical/big-assembly"
$small = "tests/fixtures/mechanical/small-assembly"
```

## Scenario 0 (Foundational): what must not move

```powershell
uv run pytest tests/unit/test_report_tokens.py tests/golden -q
uv run pytest tests/unit/test_prerun_digest.py tests/unit/test_code_first_registration.py -q
```

Expected: every golden of `render_report` byte-identical; every fastener golden byte-identical
except the three whose engagement cites the owner's rule (`joint-ok`, `joint-bottoming`,
`thread-mismatch`, diff limited to the `source` string); with `CODE_FIRST_CHECKS` empty the
opening digest is byte-identical to the tree before this feature.

## Scenario 1 (Setup): the fixtures are reproducible and fictional

```powershell
uv run pytest tests/unit/test_support_mechanical.py tests/unit/test_mechanical_fixtures_are_fictional.py tests/unit/test_standards_no_company_values.py -q
```

Expected: the generator reproduces every committed byte; every path is under `C:\Fictional\`;
the denylist scan passes, or is skipped naming the missing local file.

## Scenario 2 (US2): the joint map

```powershell
uv run python -c "from swreview.ir.loader import load_package; from swreview.checks.joints import build_joint_map; m = build_joint_map(load_package('$big').package); print(len(m.joints), [c.reason for c in m.candidates], len(m.gaps))"
uv run pytest tests/unit/test_joint_map.py tests/unit/test_joint_map_acceptance.py tests/unit/test_tools_check_joints.py -q
```

Expected: the first line prints `50 ['overlap_near', 'assigned_elsewhere']` and the gap count,
the joint numbers of `contracts/joint-map.md` section 9: 132 instances, 50 joints in 11 pattern groups (47 screw, the two dowel
joints at 0.000 and 0.750 mm, one unclassified), one `overlap_near` and one `assigned_elsewhere`
candidate; the first-instance pairs 1.576 and 3.950 mm apart absent. The small fixture: one pin joint, no hole pair. Shuffling the package
arrays changes nothing.

## Scenario 3 (US1): contacts

```powershell
uv run pytest tests/unit/test_interference_contacts.py tests/unit/test_session_contacts.py tests/unit/test_report_contacts.py tests/unit/test_contacts_acceptance.py -q
```

Expected: on the big fixture all 113 groups judged - 8 findings, 105 contacts; no contact in
"Start here"; the report's `## Contacts` table lists them; a session written before this feature
round-trips to its own bytes. On the small fixture the two zero-volume rows are one contact linked
to the pin joint.

## Scenario 4 (US3): alignment and the stack-up

```powershell
uv run pytest tests/unit/test_checks_hole_alignment.py tests/unit/test_joint_alignment.py tests/unit/test_joint_stack.py -q
```

Expected: the 0.750 mm dowel offset demonstrated against 0.050 mm allowed (floating: 0.05 +
0); the small fixture's pin passes with a zero budget and the line-to-line limit; a joint with no
tolerance source leaves the stack unresolved naming the contributor and the sources searched; with
the fake lookup, the three verdicts land where `contracts/alignment.md` section 4 says;
`hole.coaxiality` compares with half the zone (0.15 mm against a 0.2 mm zone is demonstrated).

## Scenario 5 (US4): fasteners

```powershell
uv run pytest tests/unit/test_fastener_names.py tests/unit/test_fastener_identity.py tests/unit/test_placed_screw.py tests/unit/test_engagement_rules.py tests/unit/test_thread_model_contacts.py -q
cd ..\extractor; dotnet test SwReview.sln -c Release --filter "FullyQualifiedName~FastenerNameParser|FullyQualifiedName~FastenerCandidate" --nologo; cd ..\reviewer
```

Expected: 68 of 68 named screws recognised; one `fastener.thread_match` finding for the two
M4-in-M5 joints (SC-002); the M10 (10.225 against 15.0), M2 (2.205 against 3.0) and M3 (1.394
against 4.5, derived through-tapped length) engagements demonstrated short; the M8 and the two M3
passes; the screw named M5 with a 3.3 mm shank suspected; both parsers agree on every row of the
vector table.

## Scenario 6 (US5): tool access

```powershell
uv run pytest tests/unit/test_head_dimensions.py tests/unit/test_tool_envelopes.py tests/unit/test_tool_access.py -q
```

Expected: the covered head is `fastener.head_clearance` demonstrated naming the overhanging part;
the clear head passes; the 12.0 mm counterbore under an M8 socket head is `fastener.head_fit`
demonstrated; `FHT` heads are unresolved naming the missing drive.

## Scenario 7 (US6): mass and material

```powershell
uv run pytest tests/unit/test_material_classes.py tests/unit/test_mass.py tests/unit/test_tools_check_mass_material.py -q
cd ..\extractor; dotnet test SwReview.sln -c Release --filter "FullyQualifiedName~PropertyDumper" --nologo; cd ..\reviewer
```

Expected: 2700 kg/m3 aluminium passes; 1000 kg/m3 demonstrated; the 2.000 kg sub-assembly
suspected; the unread and surface-only parts counted; the override read answers through the fake
`IMassProperty` and falls back to the fake `GetOverrideOptions`.

## Scenario 8 (US7): hygiene

```powershell
uv run pytest tests/unit/test_hygiene.py tests/unit/test_standards_document_rule.py tests/unit/test_tools_check_hygiene.py -q
```

Expected: the part-number mismatch, the shared description and the missing revision are findings;
the lightweight component is a finding; with a version 1 profile the two property checks are
skipped naming the setting; a pattern matching none of the graded documents is unresolved as a
likely profile error.

## Scenario 9 (US8): tolerances

```powershell
uv run pytest tests/unit/test_ir_tolerances.py tests/unit/test_schema_sync.py tests/unit/test_iso286.py tests/unit/test_general_tolerance.py tests/unit/test_tolerances.py -q
cd ..\extractor; dotnet test SwReview.sln -c Release --filter "FullyQualifiedName~IrSerializer|FullyQualifiedName~HoleWizardReader|FullyQualifiedName~ToleranceDumper|FullyQualifiedName~Denylist|FullyQualifiedName~RemodelGuard" --nologo; cd ..\reviewer
```

Expected: a 1.4.0 package round-trips to its own bytes; `H7` on the dowel hole binds from the
Hole Wizard; the model dimension binds by unique value and the ambiguous pair binds nothing; the
general block applies only where nothing else does and never to a position; the tolerances
fixture's joint gets a size-only worst case citing each source; the readers write what the fakes
return and a gap for every read that throws.

## Scenario 10 (FR-026): every check joins the pre-run

```powershell
uv run pytest tests/unit/test_code_first_registration.py tests/unit/test_prerun_digest.py tests/unit/test_prerun_same_session.py -q
```

Expected: with lever 5 on, the plan holds `check_joints`, `check_mass_material` and
`check_hygiene` after the interference groups and before `check_standards`; each is a real step
with its events before the first provider request; the fastener and hole-alignment lines state
what the joint map could not reach.

## Scenario 11: the catalogue and the ranking

```powershell
uv run pytest tests/unit/test_attention_catalogue.py tests/unit/test_attention.py -q
```

Expected: every one of the twelve new ids is classed; no contact reaches a ranking.

## Scenario 12 (after 008): the replay

```powershell
uv run swreview benchmark replay <008 big-assembly replay fixture> --json
uv run pytest tests/unit/test_joint_map_on_replay_fixture.py -q
```

Expected: the three recorded touching-group findings reported as reclassified as contacts (3, 2
and 0 on the three replay fixtures, 008 `contracts/replay.md` section 9), none lost;
the three new pre-run steps and no added model round (SC-006); the joint map over the replay
fixture reproduces research R3's counts.

## Scenario 13 [W]: the extractor reads on the seat (SC-008)

Dump 810-11249 and 830-02342 with the new build. Expected: `mass_overridden` present on every
document with no `mass_override` tool-error gap; `Hole.wizard` filled on the Hole Wizard holes;
`model_dimensions` present where feature dimensions carry tolerances (and an empty member with no
gap where none do); the 68 named screws emitted as fasteners with a shank face each.

## Scenario 14 [W]: a review of 830-02342

With checks first on, expected: every interference group judged, contacts in their own list and
not in "Start here"; the joint findings of Scenario 5 present, now with engagement computed for
the screws whose shank faces the widened extractor requested; no model round spent on these checks.

## Regression gate

```powershell
cd reviewer; uv run pytest -q; uv run ruff check src tests
uv run pytest -q -m perf tests/perf/test_joint_map_perf.py -s   # build_joint_map < 200 ms, check_joints < 2 s
cd ..\extractor; dotnet build SwReview.sln -c Release; dotnet test SwReview.sln -c Release
```
