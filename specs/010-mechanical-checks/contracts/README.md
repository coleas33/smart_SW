# Contracts: Automatic Mechanical Checks

| Contract | File | Producer → Consumer |
|----------|------|---------------------|
| The registration point: `CODE_FIRST_CHECKS`, the three argument-free tools, their payloads, the pre-run plan and digest lines, the re-call guard keys | `code-first.md` | `tools/checks_mechanical.py`, `prerun.py` → the pre-run (lever 5/11 today, feature 008's pane default later), the model |
| Interference outcomes: finding or contact, the `Contact` record, `ReviewSession.contacts`, the report's Contacts section, thread-model contacts, the replay's reclassification | `contacts.md` | `checks/interference.py`, `tools/checks_interference.py` → `session.json`, `report.md`, feature 009's pane, feature 008's replay |
| The joint map: hole instances, gates, assignment, members, placement, kinds, candidates, coverage, ids, thresholds | `joint-map.md` | `checks/joints.py` → every joint check, `check_joints`, the report's coverage |
| Alignment and the stack-up: fixed and floating clearance, the position budget callout, the zone-radius rule, the stack models and verdicts | `alignment.md` | `checks/joint_alignment.py`, `checks/result.py`, `checks/hole_alignment.py` → `hole.nominal_alignment`, `hole.position_stack`, `hole.coaxiality` |
| Fasteners: the name grammar and the shared vector table, recognition, the shank band, placement, the placed screw, the engagement rule, the extractor candidate gate | `fasteners.md` | `checks/fastener_names.py`, `checks/fastener_identity.py`, `checks/fastener.py`, `FastenerNameParser.cs`, `FastenerDumper.cs` → `fastener.*` findings |
| Tool access: head plane and direction, tool choice, reach, the sweep, head fit | `tool-access.md` | `checks/tool_access.py` → `fastener.head_clearance`, `fastener.head_fit` |
| Mass and material: the material-class table, the three checks, the coverage count, the extractor override read | `mass-material.md` | `checks/material_classes.py`, `checks/mass.py`, `PropertyDumper.cs` → `mass.*` findings |
| Hygiene: the five checks, the profile names, the data card's zero-match profile error | `hygiene.md` | `checks/hygiene.py`, `checks/standards/document.py` → `hygiene.*` findings, the standards data card |
| Tolerances: IR 1.5.0, the extractor reads, profile version 2's general tolerance, the ISO 286 table, the resolver | `tolerances.md` | the extractor, `checks/standards/profile.py`, `checks/tolerances.py` → the stack-up, feature 011's drawing source |
| Fixtures: the two synthetic packages shaped like the recorded runs, their case table, the generator and the denylist test | `fixtures.md` | `tests/support/mechanical.py`, `tests/fixtures/mechanical/` → every acceptance test here |

## Versioning

The IR goes to 1.5.0 with three optional members, each omitted when empty, so a 1.4.0 package
loads and serializes to its own bytes. The review-session contract gains one optional property,
`contacts`, never in `required`. The standards profile gains version 2 and the loader still reads
version 1. The attention policy stays `attention_policy_v1`: twelve rows are added and none is
changed. `engagement_rules.yaml`, `tool_envelopes.yaml` and the new data files carry their own
`version`, and every finding cites the row it used.

## What this feature does *not* move

- **`Finding`, `CoverageItem`, `InvestigationStep`** and every existing tool's signature, including
  `check_fastener_joint`, `check_hole_alignment` (its comparison is corrected, its inputs are not),
  `check_tool_envelope` and `check_interference_group`.
- **`chat-events.schema.json`.** A contact rides the judging tool's own `tool.finished`; no event
  type is added.
- **The RMS and standards registries.** The standards data card's zero-match case changes inside
  its one rule; no standards check is added, so the release verdict's rule set is unchanged.
- **The MCP function list and the terminal profile.** Check tools are in neither.
- **Every golden of `report/markdown.render_report`.** The Contacts section renders only when a
  session has contacts.
- **The pane.** Presenting contacts, joints and the new findings is feature 009's.

## Where these contracts land in other features' packages

Feature 001's `contracts/agent-tools.md` gains the three tool rows and
`review-session.schema.json` the `contacts` property; its `ir.schema.json` is regenerated at
1.5.0. Feature 004's `contracts/guard-allowlist.md` records the denylist rows the tolerance and
Hole Wizard reads add. Feature 005's `contracts/levers.md` records the new tool-array byte counts.
Feature 006's `contracts/profile.md` carries the version 2 block and `research.md` R5 one row per
new field. Feature 007's `contracts/attention.md` notes the twelve classes. Feature 008's
`contracts/checks-first.md` section 2 gains the three calls after the interference groups, section
5 the three `(tool,)` keys, and its replay contract the contact reclassification (`contacts.md`
section 6).
