# Contract: Interference Outcomes and the Contact List

Normative for FR-001 to FR-003, SC-001 and the thread-model edge case.

## 1. The decision order for one group

`classify_group(group, package, exceptions, joint_map=None) -> GroupOutcome`, in this order,
first match wins:

| # | Condition | Outcome |
|---|---|---|
| 1 | any member `status != "computed"` | finding, `unresolved` (today's `_unresolved_group`) |
| 2 | an `active` exception matches | finding, `checked_within_scope`, exception cited (today) |
| 3 | a `needs_review` exception matches | finding, `suspected` (today) |
| 4 | every member has `volume_mm3 <= CONTACT_VOLUME_MM3` or (`volume is None` and `is_possible`) | **contact**, `zero_volume` if any member has a volume, else `possible_only` |
| 5 | a `joint_map` is given, the group's two components are a screw joint's screw and tapped part, and the largest member volume is at most `π/4 · (d² - D²) · L` | **contact**, `thread_model`, linked to the joint (from US4) |
| 6 | otherwise | finding, today's `_reported` (positive volume `demonstrated`, no volume and not possible `suspected`) |

`CONTACT_VOLUME_MM3 = 1e-6`. In rule 5, `d` is the recognised screw's nominal major diameter,
`D` the tapped instance's bore and `L` their axial overlap, all in mm. A mixed group (some members
positive) is rule 6 and lists every member, zero-volume ones included, in its inputs.

## 2. `Contact`

As `data-model.md` section 9. The `reason` is one sentence:
`"<cmp A> and <cmp B> touch at nominal in configuration <c>: SOLIDWORKS reported <0.0 mm3 | no
overlap volume, only a possible interference> (<n> pairs); this is a contact, not an
interference."` and, for `thread_model`, `"... overlap <v> mm3 is within the <b> mm3 a thread
modelled as a cylinder explains in joint <jnt>"`.

## 3. The tool

`check_interference_group(group_key)` keeps its signature. For a contact it calls
`ToolContext.record_contact(contact)` instead of `record_result`, writes no finding and no
`finding` event, and returns:

```json
{"status": "contact", "contact": {"id": "C-003", "kind": "zero_volume", "...": "..."},
 "group_key": "...", "configuration": "...", "members": 2, "pairs": [["cmp:0003", "cmp:0004"]]}
```

The pre-run's `PrerunCall` counts contacts beside findings: `check_interference_group(group_key=
'k') -> ok, 1 contact`. After 008 aggregates repeated calls the line reads
`check_interference_group x113 -> 113 ok, 8 findings, 105 contacts`.

## 4. The session and the report

`ReviewSession.contacts: list[Contact]`, optional, omitted when empty (`data-model.md` section 9).
`report/markdown.py` renders, after `## Findings` and only when the list is non-empty:

```markdown
## Contacts

<n> contacts and <m> interference findings from <g> detected groups. A contact is two parts
touching at nominal size; it is listed so a line-to-line fit stays visible, and it is not an
interference finding.

| Contact | Parts | Configuration | Kind | Volume | Joint |
|---|---|---|---|---|---|
| C-001 | cmp:0003, cmp:0004 | Default | zero volume | 0.0 mm3 | jnt:0001 |
```

`report/attention.py` never reads `contacts`: a contact cannot take a Start-here slot (SC-001).

## 5. Counting every group

`interference_outcomes(session, package) -> {"groups": g, "findings": m, "contacts": n,
"unresolved": u, "excepted": x}` is the one count, used by the report's sentence and by the
acceptance tests. `g` equals `len(groups_of(package))` when every group was judged.

## 6. Feature 008's replay

A recorded `interference.static` finding whose group key and configuration equal a replayed
contact's is reported as **reclassified as contact** and is not counted as lost, so the replay's
"no recorded finding lost" gate (008 FR-005) stays meaningful: the five 0.0 mm3 findings of the two
evenings move to contacts by design.
