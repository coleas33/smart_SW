# Contract: The Drawing Check and Its Questions

Normative for FR-032 to FR-037, User Story 5, SC-007 and SC-008.

## 1. The drawing family

```python
# reviewer/src/swreview/tools/drawings.py
def check_drawings() -> ToolResult: ...                 # argument-free (this contract)
def get_drawing_brief(document_id: str) -> ToolResult:  # contracts/brief.md

def drawing_evidence(package: EvidencePackage) -> bool:
    return bool(package.drawing_records or package.drawing_candidates)
```

`tools/registry.py` gains `drawing_tools()` returning the two, **outside** `REGISTRATIONS`, and
`ToolRegistry._offered` adds them when `drawing_evidence(context.ir)`, as it adds the standards,
bridge and remodel families on their conditions. Neither is in `TOOL_FUNCTIONS`,
`MCP_TOOL_FUNCTIONS` or the terminal profile's `enabled_tools`; a test asserts all three.

| Tool | Docstring summary (the model's view) | Budget per encoding |
|---|---|---|
| `check_drawings()` | "Check what the open drawings show about each reviewed document and ask the engineer what only they know. (Notes: takes no argument.)" | at most 450 bytes |
| `get_drawing_brief(document_id)` | "A short brief of one part or assembly: what it is, its joints, the interfaces that need a callout, what its drawing covers, and the engineer's answers." | at most 650 bytes |

## 2. The plan

`prerun.planned_calls` plans `("check_drawings", {})` after every name of `CODE_FIRST_CHECKS` and
before `check_standards`, when `drawing_evidence(context.ir)` and the tool is not withheld - the
same shape as the `check_standards` branch (`prerun.py:706-707`). `CODE_FIRST_CHECKS` does not
change (its members are unconditional, feature 010 `contracts/code-first.md` section 1). Feature
008's re-call guard keys `check_drawings` as `(tool,)`: a repeat returns the recorded digest and
records nothing (008 `contracts/checks-first.md` section 5 gains the row). Under lever 13 the pane
withholds `check_drawings` once the pre-run ran it, like every pre-run tool.

With no drawing evidence nothing here happens: the plan, the digest, the offered tools and every
payload are byte-identical to the tree before this feature (FR-037).

## 3. The coverage

`checks/drawing_context.run_drawing_context(package, profile=None)` writes one `drawing.context`
coverage item per part or assembly document the package reviews, in traversal order:

| Status | When | Reason |
|---|---|---|
| `checked` | at least one usable view of an attached or root drawing shows it | "read from {drawing file names}; {k} views usable" plus every unusable view's reason (`drawing-source.md` section 1) |
| `unresolved` | drawings show it and none of their views is usable | each view's reason |
| `skipped` | no drawing shows it | "no open drawing shows it" plus, when there is one, "a drawing with its name sits beside it (candidate)" |

A drawing root's own document is not a subject of this coverage (it is graded by feature 006); its
referenced documents are.

## 4. The questions

Written through `tools/session.record_evidence_request(context, what, why, entity_ids,
question=None, options=None, blocks=None) -> EvidenceRequest`, the writer `request_evidence` now
delegates to after its refusals (the refusals and the tool's behaviour unchanged; every existing
`request_evidence` test unedited). Each is an ordinary `EvidenceRequest`: the pane's "Questions for
you" panel (009) shows it and 008's batch route answers it; nothing here changes either.

| Key | When | `question` (at most 140 characters) | `options` | `blocks` |
|---|---|---|---|---|
| `candidates` | `drawing_candidates` non-empty | "A drawing with the same name sits beside {n} reviewed file(s) but is not open. Should the review read it?" | `Yes, open it read-only and read it` (`CANDIDATE_CONFIRM`); `Review without it`; `It is not the right drawing` | `drawing.manufacturing_inputs` |
| `governing:<document id>` | a reviewed document shown by two or more attached drawings; at most three such questions, in traversal order | "{k} open drawings show {stem}. Which one governs it?" - `{stem}` shortened with an ellipsis until the question fits | each drawing's file name when there are at most four and each fits in 60 characters, then `They all apply`; otherwise none | none |

`what` for the candidates question names the candidate file names, the first ten, then "and {n}
more"; `why`: "Fits, stacks and callouts stay unresolved without a drawing. The review opens a file only
when you confirm it, read-only, and closes it again."; `entity_ids`: the candidates' document ids. For a governing question, `what` names the
drawings' document ids and file names; `why`: "Open drawings of one part can disagree; the review
uses them all, in a fixed order, until you say which governs."; `entity_ids`: the document id and
the drawings' ids.

No other question is raised by this feature. A configuration mismatch or an out-of-date view is
coverage, not a question: an answer cannot change what was extracted.

## 5. The payload and the digest line

```json
{"status": "recorded", "drawings": 2, "candidates": 3, "questions": 2,
 "findings": 0, "finding_ids": [], "coverage": {"checked": 3, "skipped": 21, "unresolved": 1}}
```

`findings` counts `drawing_profile.conformance` from US7 (`profile.md`). The digest renders
`PrerunCall.line()` unchanged: `check_drawings() -> ok, 2 drawings, 3 candidates, 2 questions`.

## 6. Answers

Answers change nothing already recorded; they are read by the brief (`brief.md` section 2,
`answers`). One answer acts: `CANDIDATE_CONFIRM` to the candidate question has the product open
each candidate read-only, read it into the package and close it again before the review resumes
(`confirmed-open.md`, FR-036, FR-053 to FR-056; *amended 2026-09-23*, owner, research R5 Q2 - the
first option was "I will open it and review again", the engineer's statement and not an action).
Every other answer opens nothing.

## 7. The drawing arm of the payload pins

`reviewer/tests/unit/test_tool_payload.py` gains the drawing arm: the slim array and the pre-run
array with the drawing family offered, per encoding, `DRAWING_ARM_*` constants printed by `--write`
in rows of their own, each asserted under `ARRAY_CEILING` (38,000), and each new tool object under
its budget of section 1. The bridged slim array with the family is pinned in the same rows and
**not** asserted under the ceiling: the bridged review arrays were over it before this feature
(research R2.20, R5 Q9; corrected 2026-09-23 on review). The constants are regenerated with `--write` in a commit of their own
(T055); every existing constant is untouched, which a test asserts by recomputing them with the
family absent.

*Found on review, 2026-09-23, and open (research R2.20, R5 Q10)*: the arm does not model a review
run with a standards profile, which offers `check_standards` before the family. With checks first
off - the command line's default - those arrays go over the ceiling because of the family: 38,058
and 37,976 bytes (review, OpenAI and Gemini), 38,414 and 38,281 (slim). They are neither pinned nor
asserted until the owner says whether the ceiling holds them; `ARRAY_CEILING` stays 38,000.

## 8. The tests

`test_drawing_context.py` (sections 3 and 4 as pure functions); `test_tools_check_drawings.py` (the
tool, the family offered only with drawing evidence and absent from the three lists, the plan
position and condition, the questions as `EvidenceRequest`s visible in 009's summary, a repeat
adding nothing under the re-call guard, the digest line, and with no drawing evidence the plan, the
digest and the offered array byte-identical); `test_session_writer.py` (the extracted writer, and
`request_evidence` unchanged); the replay test of SC-007 (T049).
