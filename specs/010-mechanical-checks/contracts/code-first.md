# Contract: The Registration Point and the Three Tools

Normative for how every check in this feature joins the code-first pass (FR-026, SC-006).

## 1. The tuple

```python
# reviewer/src/swreview/tools/checks_mechanical.py
CODE_FIRST_CHECKS: tuple[str, ...] = ("check_joints", "check_mass_material", "check_hygiene")
```

The names, in the order the pre-run calls them. The tuple grows with the stories: `()` after the
foundational phase, `("check_joints",)` after US2, the other two as US6 and US7 land. A name in
the tuple is a tool in `check_tools()` that takes **no argument**; a test asserts both.

## 2. The plan

`prerun.planned_calls(context, tools)` returns, in order:

| # | Calls | Owner |
|---|---|---|
| 1 | `bridge_interference(...)` when a bridge is attached | feature 008 (absent before 008) |
| 2 | `check_rms_part`, `check_rms_equations`, `check_rms_assembly` | existing |
| 3 | `check_interference_group(group_key=K)` per group | existing |
| 4 | `(name, {})` for each name in `CODE_FIRST_CHECKS` not withheld | **this feature** |
| 5 | `check_standards()` when a standards run is attached | feature 007 |

`PRERUN_TOOLS` gains the tuple so a withheld name carries its tier's sentence. With the tuple
empty, `planned_calls` and the digest are byte-identical to the tree before this feature.

**Before 008**: the calls run under lever 5 (`prerun_checks`) or lever 11 (`procedural_gate`), and
the model can call each tool itself when neither is on. **After 008**: the same calls run under
the pane default. Nothing in this feature depends on which.

## 3. The tools

Each is an ordinary check tool through `ToolDispatch`: a real `InvestigationStep`, its events, its
findings through `record_result`/`record_results`, its coverage. Each returns counts, never a
payload the model has to page through:

```json
{"status": "recorded", "findings": 12, "by_status": {"demonstrated": 3, "suspected": 1,
 "unresolved": 4, "checked_within_scope": 4}, "finding_ids": ["F-101", "..."],
 "coverage": {"checked": 9, "skipped": 14, "unresolved": 0}}
```

`check_joints` adds `"joints": {"total": 59, "by_kind": {"screw": 57, "pin": 2}},
"pattern_groups": 13, "candidates": 2, "recognised_fasteners": 68, "unplaced_fasteners": 11`
(the big fixture's map with its recognised fasteners placed; the foundational map without
them is 50 joints in 11 pattern groups, pinned by its own golden). `check_mass_material` adds `"documents": 26`;
`check_hygiene` adds `"documents": 26, "profile": "attached" | "absent"`.

| Tool | Docstring summary (the model's view) | Families |
|---|---|---|
| `check_joints()` | Find every joint from the geometry and check it: alignment, stack-up, fastener identity, thread, engagement, bottoming, tool access and head fit. (Notes: takes no argument.) | US2 to US5, US8 |
| `check_mass_material()` | Check every part has a material or a deliberate mass override, that its density fits the material, and flag assembly mass overrides. (Notes: takes no argument.) | US6 |
| `check_hygiene()` | Check part numbers against file names, duplicate descriptions and part numbers, revisions, and suppressed or lightweight components. (Notes: takes no argument.) | US7 |

**As registered (T067, T075).** The summaries are the docstrings' first paragraphs verbatim,
each under lever 2's 160-character cap (`test_tool_notes_prompt.py`); the wording first
planned for `check_joints` was 191 characters and was shortened to the list above. The
`Notes:` blocks are one or two sentences each, because the three tools brought the curated
array to 35,844 bytes on OpenAI and 35,915 on Gemini against `ARRAY_CEILING` 36,000
(`test_tool_payload.py`): 85 bytes of headroom, which the next tool's docstring must respect or
the ceiling must be revisited deliberately.

A second call in one session records its findings again, exactly as a second `check_rms_part`
does today. Answering repeats is one mechanism in one place, feature 008's re-call guard
(section 5); a per-tool memory here would be a second copy of it.

## 4. The digest lines

A call renders `PrerunCall.line()` unchanged (`check_joints() -> ok, 12 findings`). When
`check_joints` ran, the two not-evaluated lines it replaces become statements of what the joint
map could not reach, each still a skipped `coverage.prerun.<family>` item:

| Family | Line when `check_joints` ran |
|---|---|
| `fastener_joint` | `<n> recognised fasteners were not placed in any joint; <m> placed screws enter a part whose tapped hole was not extracted.` |
| `hole_alignment` | `<n> hole instances have no cylinder face or belong to a component that was not read; they are in no joint.` |

A family with nothing to report renders no line. `fit` and `axial_stack` keep today's lines.
`prerun.coaxial_hole_pairs` has no caller left and is removed with its `__all__` entry (it has no
test of its own); a withheld `check_joints` makes the two families carry the tier's sentence.

## 5. With feature 008's re-call guard

`repeat_key` maps each name in `CODE_FIRST_CHECKS` to `(tool,)`. A repeat is answered with the
recorded digest and records nothing new (008 `contracts/checks-first.md` section 5).

*Landed as* (T092-T093): 008's T044 already read the tuple in `repeat_key`, so T093 adds no
code, only the three names to 008's table and to `agent-tools.md`. The tuple is read when the
key is asked for, so a later argument-free check joins the guard by joining `CODE_FIRST_CHECKS`
and one that leaves the tuple leaves the guard; arguments a model adds are ignored, as for
`check_rms_part`'s `document_id`. The answer's `outcome` is the recorded counts summary as
given (`check_digest` returns a payload that is not a findings envelope unchanged), and a
check whose pre-run call failed runs again (`test_prerun_repeat_guard.py`).

## 6. Callable as functions

Each family is also a plain function over the package, usable from a test or a script with no
session: `build_joint_map(package)`, `run_joint_checks(package, joint_map, profile=None,
lookup=None) -> list[JointResult]`, `run_mass_checks(package) -> list[CheckResult]`,
`run_hygiene_checks(package, profile=None) -> list[CheckResult]`. The tools are thin wrappers
that record what these return.
