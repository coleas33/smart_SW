# Contract: Part Roles - Custom, Bought or Unclear

Normative for FR-005 to FR-014 and User Story 1. Research R2.3 to R2.11, R3 C4, C6, C10.
Amends feature 003's `contracts/rules.md` (grading scope; the mates rule) and `contracts/tools.md`;
feature 008's `contracts/checks-first.md` sections 1 and 4 and `contracts/answer-batch.md` section 1;
feature 009's `contracts/questions.md` sections 1 to 4 and `contracts/review-summary.md` section 4;
feature 010's `contracts/hygiene.md` section 1 and `contracts/code-first.md`; feature 002's
`chat-events.schema.json` (`finding.withdrawn`).

## 1. The function and its states

*Amended 2026-09-26, before any code, from the owner's guidance and the local census of that day
(research R2.4, "Revised"; `part-roles-profile.md`'s note): with a version 4 profile a part is
decided by **votes** - each signal votes custom or bought with a strength - where the first
version of this contract read a first-match table. The states, the root rule, the zero-match
guard, the question and the regrade are unchanged in purpose; sections 5 to 9 keep their
numbers, which other documents cite.*

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
and refused, so the no-profile line can say why. *Amended 2026-09-27 (T154-T155, research R2.45;
default taken 2026-09-27, the owner may revise):* that reason names no path - not the profile's,
not its folder, not its file name - because the line rides the bought-parts row into the digest,
the summary and the report. It is `ProfileError.reason` (`checks/standards/profile.py`), the
refusal's kind and cause ("no file at the configured path; the setting is StandardsProfilePath",
"the file is a version 99 standards profile; this build knows versions 1, 2, 3 and 4", ...), read by
`runner.profile_refusal_of`; the loader's whole message, which names the file, is still what the
Standards tab and the standards family's line show the engineer.

| State | When | What decides (section 2) |
|---|---|---|
| `configured` | a version 4 profile | the answer, then the votes of every signal of section 2.1 by the decision of section 2.2, then the inheritance of section 2.3 |
| `convention_only` | a version 1 to 3 profile with a non-empty `part_number.pattern` | the table of section 2.4 only (research R2.5): the answer, Toolbox, the part-number convention; every other document is `unclear` and listed in the question, even beside a same-name drawing or inside a vendor assembly |
| `absent` | no profile, an unreadable or invalid one, or a version 1 to 3 profile with an empty pattern | the answer (never populated: no question is asked) and Toolbox; every other document is `unclear` with the state's reason, graded, **with no note** and no question |

*Amended 2026-09-27 (the review of that day):* a version 4 profile whose `part_roles` section has
**every signal unused** - `PartRolesSection.signals_unused`: no bought prefix or folder name, no
switch property, no vendor, distributor or detail property, no catalogue shape, no custom or bought
number prefix; what `swreview profile upgrade` writes before the owner fills it in
(`part-roles-profile.md` section 5) - is read as the version 3 profile it was proposed from:
`convention_only` with a non-empty `part_number.pattern`, `absent` with an empty one. With every
signal off only Toolbox and the same-name drawing could vote, so the zero-match guard fired on the
sitting's package and no part-roles question was asked, where the version 3 file asked about the
unclear parts; the unfilled file now decides exactly what its input decides, and `configured`
means a version 4 section with at least one signal in use.

## 2. How a document is decided

### 2.1 The signals (the `configured` state)

Each signal casts at most one vote per role. Its strength is fixed here, not in the profile; the
profile names only what each signal looks for (`part-roles-profile.md` section 1), and an empty entry
turns the signal off.

| Signal | Votes | Strength | The document votes when | Words |
|---|---|---|---|---|
| `toolbox` | bought | strong | any instance of it has `is_toolbox` true (false is never evidence: a lightweight or suppressed instance records false with a gap) | "a Toolbox part" |
| `bought_path` | bought | strong | its path is under a `bought_prefixes` entry (the library prefix rules), or one of its folders is named like a `bought_folder_names` entry | "a bought-parts folder" |
| `switch` | bought | strong | the switch property holds one of `switch.bought_values` | "marked bought by its make-or-buy property" |
| `switch` | custom | **weak** | the switch property holds one of `switch.custom_values` | "marked made here by its make-or-buy property" |
| `vendor_property` | bought | strong | any of `vendor_properties` carries a non-blank value | "a vendor property" |
| `distributor_block` | bought | strong | at least `distributor_block.min_valued` of its properties carry a non-blank value | "a distributor's property block" |
| `catalogue_number` | bought | medium | a `catalogue_numbers.shapes` entry matches a whole token of its file name, one of its configuration names, or the whole value of one of `catalogue_numbers.properties` | "a catalogue number" |
| `bought_number` | bought | medium | one of its numbers starts with a `bought_number_prefixes` entry | "a bought part-number range" |
| `custom_prefix` | custom | medium | one of its numbers starts with a `custom_prefixes` entry | "the company's part-number prefix" |
| `sparse` | custom | weak | its properties were read, and none of `vendor_properties`, `distributor_block.properties` or `detail_properties` is present, valued or not (off when all three lists are empty: with nothing to be missing, every part would be sparse) | "few properties" |
| `same_name_drawing` | custom | weak | a `drawing_candidates` row names it, or a drawing document of the package has its folder and stem (compared ignoring case and separators: an open same-name drawing is recorded as attached, not as a candidate) | "a drawing of the same name beside it" |

**What the signals read.**

- **The file name** is the last segment of the document's path. A document with no path has no file
  name, no folders and no tokens: `bought_path`, the file-name half of `catalogue_number`,
  `bought_number` and `custom_prefix`, and `same_name_drawing` cannot vote for it.
- **Tokens** are the file name without its extension, split at commas and whitespace.
- **Configuration names** are the document's own configurations and every configuration a component
  instance of it references.
- **Properties** are read from the configurations the document is used in - the configurations its
  instances reference, in package order, each once, or its active configuration when no instance
  references it - then from the document's own properties. The switch reads those configurations'
  values, and the document's only when none of them carries the property, so a configuration's value
  wins; each distinct value found votes (two configurations that disagree cast both votes). Every
  other property signal reads every level. Names are
  compared ignoring case and every space (`property_key`, `part-roles-profile.md` section 2), values
  ignoring case and surrounding spaces; a blank value is no value.
- **A document's numbers** are its file name, when `part_number.pattern` is empty or the file name
  follows it, and the value of the part-number property (`hygiene.part_number_property`, when it is
  named) at any level. So a custom prefix is found in either the custom-prefix file name or the
  custom-prefix part number, and a part number in a bought range is found even under a file name that
  follows the convention.
- **A document whose properties were not read** (a lightweight or suppressed placeholder: the
  `document` not-extracted gap, `properties_gap`) is decided only from its path, its name, its
  configuration names, its same-name drawing and Toolbox: `switch`, `vendor_property`,
  `distributor_block` and `sparse` cannot vote, nor the property halves of `catalogue_number`,
  `bought_number` and `custom_prefix`. Its reason says so.

Unknown inputs are never matches.

### 2.2 The decision

For each document, in order:

1. **The answer decides.** The engineer's answer to the part-roles question in this session names
   it: as answered (decision `answer`).
2. **Strong votes.** When any strong vote was cast: if every strong vote names one role and no medium
   vote names the other, that role wins (`strong`); a weak vote against it does not count.
   Otherwise the document is unclear (`conflict`), and asked.
3. **No strong vote.** A role needs at least two agreeing votes, at least one of them medium, and no
   vote for the other role (`agreement`). Otherwise the document is unclear: `conflict` when both
   roles were voted, `too_little` when only one was.
4. **No vote at all**: unclear (`no_evidence`), and asked.

### 2.3 Inheritance

After every document is decided on its own votes, a document **not** decided by an answer, whose
decision is not `custom` and which carries no medium or strong custom vote, and every instance of
which sits under an instance of a bought document, is bought (`inherited`). It is applied from the
root down, so a vendor sub-assembly's role passes through every level beneath it. A child whose own
evidence says custom keeps its own decision.

### 2.4 The `convention_only` table

First match wins:

| Rule | Test | Role | Decision |
|---|---|---|---|
| A | the engineer's answer names it | as answered | `answer` |
| B | any instance of it has `is_toolbox` true | bought | `toolbox` |
| G | its file name matches `part_number.pattern` | custom | `convention` |
| J | otherwise | unclear | `no_evidence` |

The `absent` state reads rows A and B, and every other document is unclear with decision
`not_told_apart`.

### The root rule

The review's root document is always graded. When it is decided bought, its role stays bought for the
bought-parts line's wording, `graded` is true, and its label is "looks bought ({reason}); graded
because it is the document under review".

*Amended 2026-09-27 (the review of that day, FR-008):* the label reaches the engineer and the model
through the bought-parts line (section 7): `bought_parts_sentence` appends "{file} looks bought
({reason}); graded because it is the document under review" after the parts not graded, joined by
"; " (before a regrade's "; withdrew ..." tail), and writes the row with that clause alone when the
root is the only document the rules call bought. The row's `scope.document_ids` stay the parts not
graded, so the summary counts none for the root; the digest line, `session.json`, the summary's
`bought_parts.text` and `report.md`'s "Bought parts" section print it. The Model check tab grades
its open part always - it attaches no roles, so nothing is exempt - but does not print the label:
its route (`POST /checks/rms`) takes no standards profile to classify with, which is a
`model-check.md` interface change left for the owner (see the review's deferrals).

### The zero-match guard

In `configured`: when no document of the package, the root included, is decided custom or bought by
anything but an answer, no question is asked and one unresolved coverage row
`coverage.prerun.part_roles` says "no part-role rule decided any of the {n} documents; check the
profile's part_roles section". In `convention_only`: when `part_number.pattern` matches no document
and Toolbox decides none, the row says "the part-number convention matched none of the {n}
documents; check part_number.pattern" (feature 006's zero-match precedent,
`checks/standards/document.py:171`). Either way the documents stay graded as unclear with no note.

## 3. Reasons

Reasons name the signal, never a profile value (FR-034 of feature 006): these words reach the model
provider through the digest and the brief. A reason is built from the signals' words (section 2.1),
joined as a list ("a, b and c"):

| Decision | Reason |
|---|---|
| `answer` | "you answered it is bought" / "you answered it is ours" |
| `strong`, `agreement` | the winning role's signal words; when the other role voted too (only weak votes can, under `strong`), "; against it: {their words}" |
| `inherited` | "inside a bought assembly" |
| `conflict` | "the signals disagree: bought - {bought words}; custom - {custom words}" |
| `too_little` | "too little evidence: only {words}" |
| `no_evidence` (`configured`) | "no signal decides it" |
| `toolbox` | "a Toolbox part" |
| `convention` | "follows the part-number convention" |
| `no_evidence` (`convention_only`) | "neither the part-number convention nor a bought-part rule decides it" |
| `not_told_apart` | the state's reason |

Tails, in this order: "; no path was recorded" for a document with no path, and "; its properties
were not read" for a document whose properties were not read (section 2.1).

Every model-facing sentence of this contract - the signal words and decision reasons above, the root
label, `note_for`'s note, the section 7 sentences and the section 8 question's words - is a constant
of `checks/part_roles.py`, one table beside the classifier, pinned by `test_part_roles.py` and
`test_prerun_digest.py`, so lanes P and S need no words-file change before they land. They reach the
model, so editing one moves what the model reads and passes the replay gate (`tokens.md` section 5).
The words file (lane R) carries only pane words: the text box's `questions.text_placeholder` and the
report's "Bought parts" heading, `bought_parts.heading`. *Settled on review, 2026-09-26, where the
words had been placed in the words file, which lanes P and S could not read before lane R's T034
landed.*

## 4. The API

```python
Role = Literal["custom", "bought", "unclear"]
State = Literal["configured", "convention_only", "absent"]
Strength = Literal["strong", "medium", "weak"]
Signal = Literal[
    "toolbox", "bought_path", "switch", "vendor_property", "distributor_block",
    "catalogue_number", "bought_number", "custom_prefix", "sparse", "same_name_drawing",
]
Decision = Literal[
    "answer", "strong", "agreement", "inherited", "conflict", "too_little", "no_evidence",
    "toolbox", "convention", "not_told_apart",
]

@dataclass(frozen=True)
class Vote:
    signal: Signal
    role: Literal["custom", "bought"]
    strength: Strength

@dataclass(frozen=True)
class PartRole:
    document_id: str
    role: Role
    decision: Decision
    votes: tuple[Vote, ...]   # the configured state's votes, in section 2.1's order; () otherwise
    properties_read: bool     # False for a document with the properties gap
    reason: str
    graded: bool              # role != "bought", or the document is the root
    label: str | None         # the root rule's label, else None

@dataclass(frozen=True)
class PartRoles:
    state: State
    state_reason: str | None      # why absent, in words
    by_document: Mapping[str, PartRole]
    guard_fired: bool             # the zero-match guard
    asked_in: str | None = None   # the question's ER id once recorded (lane S, T032)

    def graded(self, document_id: str) -> bool: ...   # True for an unknown id: errors fail toward grading
    def bought(self) -> tuple[PartRole, ...]: ...      # not graded, package order
    def unclear(self) -> tuple[PartRole, ...]: ...     # package order
    def asking(self, request_id: str) -> PartRoles: ...  # a copy with asked_in set
    def note_for(self, document_id: str) -> str | None:
        """'may be a bought part: {reason}; asked in {ER id}' for an unclear document while the
        question is open (asked_in set), and None otherwise (absent state, guard fired, custom,
        bought, answered, or not yet asked)."""
```

`note_unclear(result, note)` is the one helper the RMS and hygiene consumers use to append the note
to a fail or warn result's coverage limits. `roles_question(roles, package)` builds section 8's
question as a `QuestionSpec` (key `part_roles`), or `None` when none is asked; `answered_roles(request,
spec, package)` reads section 9's answer.

## 5. Where it is computed

`start_review` loads the profile **once** (`load_review_profile(path)` in
`checks/standards/profile.py`, which never raises: a `ReviewProfile {path, profile, refusal}`),
classifies right after `build_context`, before `carry_over_findings` (`agent/runner.py:1242`) and
before the pre-run, and attaches the roles to the context with `attach_part_roles(context, roles)`
under `PART_ROLES_ATTRIBUTE`. The attribute's name is defined in `checks/part_roles.py` and
re-exported by `tools/registry.py` beside `STANDARDS_RUN_ATTRIBUTE` (lane S, T022), so lane P's
readers and lane S's writer cannot disagree about it; `review_roles(context)`
(`tools/checks_mechanical.py`) reads it, `None` when nothing is attached, and every consumer grades
everything then, exactly as before this feature. *Placed on the amendment of 2026-09-26, so that the
consumers (lane P) need nothing from lane S's files before they land.*
`attach_standards` (`prerun.py:742`) takes the loaded `ReviewProfile` instead of reloading it (a
path is still accepted and loaded there, the call form before T022); the four standards refusal
reasons stay byte-identical. It records the loaded profile on the context whether or not the
standards run attaches. `_attached_profile` (`tools/checks_mechanical.py:173`) becomes
`review_profile(context)`, which returns that loaded profile even when the standards phases were
not dumped (fixing the latent coupling the analysts found: a valid profile made hygiene say "no
standards profile is attached" when the phases were not dumped). Its import and two calls in `tools/drawings.py` (`:37`, `:85`, `:179`) move with it, so the
drawing check also receives that profile, and `drawing_profile.conformance` is compared on a review
whose standards phases were not dumped. `ToolContext.reload_package` keeps the roles (document ids
are stable).

## 6. The consumers

| Consumer | Rule |
|---|---|
| `part_documents` (`tools/rms_checks.py:253`) | with no ids, the graded part documents only; an explicit bought id is an error result naming the reason ("a bought part: not graded for modelling practice") |
| `run_part_checks`, `run_equation_checks` | `note_unclear` on the fail and warn results of unclear documents |
| `check_rms_assembly`, `rms.assembly.mates_to_reference_geometry` | a mate entity on a bought component is exempt; a mate is graded on its custom and unclear sides; a mate with every side bought is not graded (one skipped subject line "mates between bought parts are not graded") |
| `run_hygiene_checks(package, profile, roles)` (`checks/hygiene.py:309`) | the four property checks over graded documents; duplicates compared among graded documents only; `hygiene.component_not_resolved` over every document; `note_unclear` on unclear documents; property names compared through `property_key` (ignoring case and every space, `part-roles-profile.md` section 2), so a part-number property spelled without its space is found |
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
| `question` | "Are these bought parts? Until you answer, they are graded for modelling practice and hygiene." (93 characters) |
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

*Amended 2026-09-27 (the review of that day):* an answer is either option when the **whole**
answer equals it ignoring case, runs of spaces and a closing full stop or exclamation mark, so
"all bought." typed into the text box is the "All bought" button; before, it was read as a name
that matched nothing and graded every listed part custom, on a question that cannot be answered
twice. A longer answer that contains the words is a list of names, as the table's last row reads it.

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
sub-assembly, and table-driven packages): each signal voting and not voting, and each unknown input
failing it (no path, the properties gap, a blank value, a Toolbox false); the switch's bought value
strong and its custom value weak, a configuration's value winning over the document's, two
disagreeing configurations casting both votes; property names matched ignoring case and spaces; the
distributor block at, below and above `min_valued`; a catalogue shape on a file-name token, a
configuration name, a referenced configuration and a property value, and not on a part of a token;
the numbers from the file name only when it follows the convention; each row of the decision (the
answer over everything; strong agreeing; strong with a weak vote against; strong with a medium vote
against; strong votes that conflict; two agreeing votes with one medium; two weak votes; one medium
vote; votes both ways without a strong one; no vote); inheritance through two levels, blocked by a
child's custom decision and by its medium custom vote, and not applied over an answer; the unread
placeholder decided from its path, name, configurations and Toolbox, saying so; every reason and the
question's words pinned as `checks/part_roles.py`'s constants; no reason contains any distinctive
profile value; the root rule and its label; Toolbox with no profile; each state; an unknown id
graded; the zero-match guard in both states; in the `convention_only` state a document with a
same-name drawing and one inside a Toolbox assembly both `unclear` and listed; `note_for` only while
the question is open; `answered_roles` for "All bought", "None bought", a text list, an unmatched
piece, and a look-alike request that is not the spec. `test_tools_rms_checks.py`: the bought part
leaves the null selection; an explicit bought id refused; unclear results noted; the mates rule's
custom side and the bought-bought mate. `test_hygiene.py`: no revision, part-number or duplicate
finding on the bought pin; `component_not_resolved` still raised for a lightweight bought part; a
custom and a bought part sharing a description raise no duplicate; a part-number property spelled
without its space found. `test_prerun_digest.py`: both lines equal their rows; no question when
absent, when nothing is unclear, or when the guard fired; asked once across a Retry.
`test_answer_batch_roles.py`: all, none, a text list, an unmatched piece; withdrawn ids and events;
kept ids; an "All bought" batch that withdraws at least one finding while another graded part's
finding is restated leaves no two findings sharing a verdict key and every kept id unchanged; one
batch that answers the part-roles question and confirms a candidate reads the candidate first and
restates `check_drawings` once; the model's look-alike question does nothing; the drawing restate's
existing tests pass. `test_attention_family_fold.py`: after classification the family's
representative is the plate's finding. `test_review_summary.py`: the line in each state, counted
nowhere.
