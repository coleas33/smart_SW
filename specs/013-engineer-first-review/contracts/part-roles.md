# Contract: Part Roles - Custom, Bought or Unclear

Normative for FR-005 to FR-014 and User Story 1. Research R2.3 to R2.11, R3 C4, C6, C10.
Amends feature 003's `contracts/rules.md` (grading scope; the mates rule) and `contracts/tools.md`;
feature 008's `contracts/checks-first.md` sections 1 and 4 and `contracts/answer-batch.md` section 1;
feature 009's `contracts/questions.md` sections 1 to 4 and `contracts/review-summary.md` section 4;
feature 010's `contracts/hygiene.md` section 1 and `contracts/code-first.md`; feature 002's
`chat-events.schema.json` (`finding.withdrawn`).

## 1. The function and its states

```python
# reviewer/src/swreview/checks/part_roles.py
def classify_parts(
    package: EvidencePackage,
    profile: StandardsProfile | None,
    answers: Mapping[str, Role] | None = None,
    *,
    profile_refusal: str | None = None,
) -> PartRoles: ...
```

Pure: it reads its arguments only. It covers every part and assembly document of the package;
drawings are never classified. `profile_refusal` is the loader's reason when a profile was configured
and refused, so the no-profile line can say why.

| State | When | Rules in force (section 2) |
|---|---|---|
| `configured` | a version 4 profile | all |
| `convention_only` | a version 1 to 3 profile with a non-empty `part_number.pattern` | A, B, G, J only (research R2.5): every document the convention and Toolbox do not decide is `unclear` and listed in the question, even beside a same-name drawing or inside a vendor assembly |
| `absent` | no profile, an unreadable or invalid one, or a version 1 to 3 profile with an empty pattern | A (never populated: no question is asked), B; every other document is `unclear` with the state's reason, graded, **with no note** and no question |

## 2. The decision table

For each document, first match wins; then the root rule.

| Rule | Test | Role | Reason (words) |
|---|---|---|---|
| A | the engineer's answer to the part-roles question in this session names it | as answered | "you answered it is bought" / "you answered it is ours" |
| B | any instance of it has `is_toolbox` true | bought | "a Toolbox part" |
| C | its path is under a `bought_prefixes` entry | bought | "a bought-parts folder" (+ "although its name follows the part-number convention" when G would match) |
| D | `purchased_property` holds one of `purchased_values` | bought | "marked purchased by its properties" (+ the same tail) |
| E | its file name matches a `bought_name_patterns` entry **and** `part_number.pattern` | unclear | "its name matches both the part-number convention and a vendor name pattern" |
| F | its file name matches a `bought_name_patterns` entry | bought | "a vendor catalogue name" |
| G | its file name matches `part_number.pattern` | custom | "follows the part-number convention" |
| H | a drawing of the same stem sits beside it (a `drawing_candidates` row for it, or an attached drawing of its folder and stem whose views show it) | custom | "a drawing of the same name sits beside it" |
| I | every instance of it sits under an assembly this table made bought | bought | "inside a bought assembly" |
| J | otherwise | unclear | "neither the part-number convention nor a bought-part rule decides it" (+ "; no path was recorded" when it has none) |

Unknown inputs are never matches: a document whose properties were not read (a properties gap) fails
D; a document with no path fails C and H.

**The root rule.** The review's root document is always graded. When the table says bought, its role
stays bought for the bought-parts line's wording, `graded` is true, and its label is "looks bought
({reason}); graded because it is the document under review".

**The zero-match guard** (`convention_only` and `configured`). When `part_number.pattern` matches no
document of the package, the root included, and rules B to F and I (those in force) decide none, no question is asked
and one unresolved coverage row `coverage.prerun.part_roles` says "the part-number convention matched
none of the {n} documents; check part_number.pattern" (feature 006's zero-match precedent,
`checks/standards/document.py:171`). The documents stay graded as unclear with no note.

## 3. Reasons

Reasons name the rule, never a profile value (FR-034 of feature 006): these words reach the model
provider through the digest and the brief. Every model-facing sentence of this contract - the rule
reasons of section 2, the root label, `note_for`'s note, the section 7 sentences and the section 8
question's words - is a constant of `checks/part_roles.py`, one table beside the classifier, pinned
by `test_part_roles.py` and `test_prerun_digest.py`, so lanes P and S need no words-file change
before they land. They reach the model, so editing one moves what the model reads and passes the
replay gate (`tokens.md` section 5). The words file (lane R) carries only pane words: the text box's
`questions.text_placeholder` and the report's "Bought parts" heading, `bought_parts.heading`.
*Settled on review, 2026-09-26, where the words had been placed in the words file, which lanes P and
S could not read before lane R's T034 landed.*

## 4. The API

```python
Role = Literal["custom", "bought", "unclear"]
State = Literal["configured", "convention_only", "absent"]

@dataclass(frozen=True)
class PartRole:
    document_id: str
    role: Role
    rule: Literal["A", "B", "C", "D", "E", "F", "G", "H", "I", "J"]
    reason: str
    graded: bool          # role != "bought", or the document is the root
    label: str | None     # the root rule's label, else None

@dataclass(frozen=True)
class PartRoles:
    state: State
    state_reason: str | None      # why absent, in words
    by_document: Mapping[str, PartRole]
    guard_fired: bool             # the zero-match guard

    def graded(self, document_id: str) -> bool: ...   # True for an unknown id: errors fail toward grading
    def bought(self) -> tuple[PartRole, ...]: ...      # not graded, package order
    def unclear(self) -> tuple[PartRole, ...]: ...     # package order
    def note_for(self, document_id: str) -> str | None:
        """'may be a bought part: {reason}; asked in {ER id}' for an unclear document while the
        question is open, and None otherwise (absent state, guard fired, custom, answered)."""
```

`note_unclear(result, note)` is the one helper the RMS and hygiene consumers use to append the note
to a fail or warn result's coverage limits.

## 5. Where it is computed

`start_review` loads the profile **once**, classifies right after `build_context`, before
`carry_over_findings` (`agent/runner.py:1242`) and before the pre-run, and attaches the roles to the
context under `PART_ROLES_ATTRIBUTE` (beside `STANDARDS_RUN_ATTRIBUTE` in `tools/registry.py`).
`attach_standards` (`prerun.py:742`) takes the loaded profile instead of reloading it; the four
standards refusal reasons stay byte-identical. `_attached_profile`
(`tools/checks_mechanical.py:173`) becomes `review_profile(context)`, which returns the loaded
profile even when the standards phases were not dumped (fixing the latent coupling the analysts
found: a valid profile made hygiene say "no standards profile is attached" when the phases were not
dumped). Its import and two calls in `tools/drawings.py` (`:37`, `:85`, `:179`) move with it, so the
drawing check also receives that profile, and `drawing_profile.conformance` is compared on a review
whose standards phases were not dumped. `ToolContext.reload_package` keeps the roles (document ids
are stable).

## 6. The consumers

| Consumer | Rule |
|---|---|
| `part_documents` (`tools/rms_checks.py:253`) | with no ids, the graded part documents only; an explicit bought id is an error result naming the reason ("a bought part: not graded for modelling practice") |
| `run_part_checks`, `run_equation_checks` | `note_unclear` on the fail and warn results of unclear documents |
| `check_rms_assembly`, `rms.assembly.mates_to_reference_geometry` | a mate entity on a bought component is exempt; a mate is graded on its custom and unclear sides; a mate with every side bought is not graded (one skipped subject line "mates between bought parts are not graded") |
| `run_hygiene_checks(package, profile, roles)` (`checks/hygiene.py:309`) | the four property checks over graded documents; duplicates compared among graded documents only; `hygiene.component_not_resolved` over every document; `note_unclear` on unclear documents |
| `carry_over.py` (lever 11a) | an RMS finding on a bought document is not carried |
| the drawing check | `drawing-capability.md` section 3 |
| `package_brief._document_line` | `role=custom|bought|unclear` |
| checklist `modeling.resilience` and `hygiene` | one added sentence: "Custom parts only; bought parts are listed once, not graded." |
| interference, fit, fasteners, mass and material, joints | unchanged: bought parts included |
| the attention ranking | unchanged (no key reads roles); a regression test proves the family's representative is a graded part's |

## 7. The bought-parts line

Two pre-run `NotEvaluated` lines (`prerun.py:798`), so each coverage row and its digest line come
from one sentence; with no pre-run the same rows are recorded directly (the `standards_gap`
precedent, `agent/runner.py:1281-1282`):

| Check | Bucket | Sentence |
|---|---|---|
| `coverage.prerun.bought_parts` | `skipped` | "{n} parts not graded for modelling practice or hygiene (bought): {file} ({reason}), ..." - up to ten files, then "and {k} more" |
| `coverage.prerun.maybe_bought` | `unresolved` | "{files} graded; each finding says it may be bought; asked in {ER id}; do not ask for their drawings" |

In the `absent` state the first row reads "Bought parts were not told apart: {state_reason}; Toolbox
parts were not graded" (and names them). Neither row maps to a goal.

`review_summary` gains `bought_parts: {count, names, maybe_count, maybe_names, text}`, counted in no
group, goal or headline, `None` when there is nothing to say; `report.md` renders it once as a
"Bought parts" section under the words file's `bought_parts.heading`. It is **read from the persisted
rows**, never classified again: `count` and `names` from `coverage.prerun.bought_parts`'
`scope.document_ids` (their file names from the package), `maybe_count` and `maybe_names` from
`coverage.prerun.maybe_bought`'s, and `text` the rows' sentences. The routes that build the summary
call `review_ranking(session, package, usage)` with no profile and no roles (`chat/server.py:1291`,
`report/snapshot.py:74`), so the live review, the disk route and the re-render all show the same
line. *Settled on review, 2026-09-26.*

## 8. The question

Recorded once by `start_review`, after the dispatch is built and before the pre-run, through
`record_evidence_request` (the one writer) with the shared duplicate test (`checks/questions.py`),
whether or not checks first is on, when the state is not `absent`, the guard did not fire, and
`unclear()` is non-empty:

| Field | Value |
|---|---|
| `question` | "Are these bought parts? Until you answer, they are graded for modelling practice and hygiene." (95 characters) |
| `options` | "All bought", "None bought" |
| `allow_text` | true |
| `what` | "Parts no rule tells apart: {file names}" - the first ten, then "and {n} more" |
| `why` | "Bought parts are not graded for modelling practice or hygiene. Answer to regrade this review now." |
| `entity_ids` | the unclear documents' ids, package order |
| `blocks` | none |
| `source` | `code` |

The page draws the two buttons and a text box whose placeholder is the words file's
`questions.text_placeholder` ("Or name the bought ones, separated by commas").

## 9. Answers and the regrade

In `answer_evidence_batch` (`agent/runner.py:864`), after the answers are marked (008
`answer-batch.md` step 2) and before the resumed turn, `answered_roles(request, spec, package)` reads
an answered request only when it **is** the part-roles question (its `question`, `options` and
`entity_ids` equal the spec's, as `_is_confirmed_candidate` matches, `tools/drawings.py:204`):

| Answer | Roles |
|---|---|
| "All bought" | every listed document bought |
| "None bought" | every listed document custom |
| text | split on commas, semicolons and line breaks; each piece trimmed and matched, ignoring case, to a listed document's file name or stem; matched ones bought, every other listed one custom; a piece that matches none is quoted in one `coverage.prerun.part_roles` row ("'{piece}' names none of the listed parts") and changes nothing |

**Order** (settled on review, 2026-09-26). In one batch: (1) the answers are marked; (2)
`read_confirmed_candidates` runs first, with the roles as they were when its question was built, so
the rebuilt candidate question still matches exactly and a confirmed read is never silently skipped;
(3) then `answered_roles` reads the part-roles answer and, when the roles changed, reclassifies with
the answers; (4) then one `ReviewRun._restate(tools)` (replacing `_restate_drawing_check`,
`agent/runner.py:902`) restates the union of what changed, each tool once: `check_rms_part`,
`check_rms_equations`, `check_rms_assembly`, `check_hygiene` and `check_drawings` when the roles
changed, and `check_drawings` when a read reloaded the package. Each is a recorded step through the
registry's dispatch and `PrerunGuard.answer_repeats_with`, superseding the findings of the call it
restates.

**`_restate` reconciles its own restated calls** before it returns. It takes its own mark (the
findings' count before its first call), runs the calls, and folds each finding they added onto the
earlier finding with the same verdict key, which keeps its id (the `_verdict_key` reconcile,
`agent/runner.py:623`, which ignores coverage limits, so the note drops in place). An earlier finding
of a restated tool is kept when a restated finding took its place or the restated call returned its
id (a check that de-duplicates, as `check_drawings`' conformance findings do,
`tools/drawings.py:120-143`); every other earlier finding of a restated tool is no longer produced
and is withdrawn by `ToolContext.withdraw_findings(ids, reason)`, the sibling of `withdraw_coverage`
(`tools/context.py:275`), which removes it from the session and emits `finding.withdrawn
{finding_id, reason}` with the reason "bought part (your answer to {ER id})". Only then does the batch
take the `before` index its resumed-turn reconcile uses (`_reconcile_reruns`, `agent/runner.py:647`),
so a withdrawal can never shift a restated finding into the list's earlier part, where it would stay
as a duplicate under a new id. The bought-parts row is restated naming the withdrawn ids.
`provider.start_steps_at` advances. The resumed message gains one line: "Checks first graded again
after your answer: withdrew {ids} (bought parts)."

Unanswered: nothing changes; the question stays open and finalization reports it as today.

## 10. Tests

`test_part_roles.py` (fictional fixtures only: an assembly, a custom plate following the convention,
a vendor pin with two instances under a fictional bought folder, an unclear part, a vendor
sub-assembly): one case per table row, the conflicts of rules C, D and E, the root rule, Toolbox with
no profile, each state, no path, a properties gap, an unknown id graded, the zero-match guard, answers
overriding every rule, rule H on and off, rule I with a convention-named child, and in the
`convention_only` state a document with a same-name drawing and one inside a Toolbox assembly both
`unclear` and listed (rules H and I not in force). `test_tools_rms_checks.py`:
the bought part leaves the null selection; an explicit bought id refused; unclear results noted; the
mates rule's custom side and the bought-bought mate. `test_hygiene.py`: no revision, part-number or
duplicate finding on the bought pin; `component_not_resolved` still raised for a lightweight bought
part; a custom and a bought part sharing a description raise no duplicate. `test_prerun_digest.py`:
both lines equal their rows; no question when absent, when nothing is unclear, or when the guard
fired; asked once across a Retry. `test_answer_batch_roles.py`: all, none, a text list, an unmatched
piece; withdrawn ids and events; kept ids; an "All bought" batch that withdraws at least one finding
while another graded part's finding is restated leaves no two findings sharing a verdict key and
every kept id unchanged; one batch that answers the part-roles question and confirms a candidate
reads the candidate first and restates `check_drawings` once; the model's look-alike question does
nothing; the drawing restate's existing tests pass. `test_attention_family_fold.py`: after classification the family's
representative is the plate's finding. `test_review_summary.py`: the line in each state, counted
nowhere.
