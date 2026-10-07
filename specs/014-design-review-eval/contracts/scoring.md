# Contract: Scoring - the Matcher, the Outcomes, Origins and the Scoring-Rules Version

Normative for FR-001 to FR-008, FR-017, FR-018, FR-021 for the columns below, FR-049, FR-061,
SC-001, SC-002, SC-013, User Story 1 and User Story 3 scenarios 1 to 4. Research D6, D7, D9,
D14.2, D14.4, D15, §4 SP-1 to SP-14 and the cross-check, §8.4, §8.5, §8.12, §8.15; owner decisions
4A, 13A, 15A, 16A, 17A, 19A, 20A. The key's format and its load-time refusals are `answer-key.md`;
the question columns are `questions.md`, which this contract embeds and does not restate; the answer
log is `scripted-answers.md`.

Amends feature 001's `contracts/review-session.schema.json` (`InvestigationStep.origin_mark`,
`ReviewSession.origin_marks`), `contracts/scorecard.schema.json` and `data-model.md` section 3 (the
scorecard), and `contracts/agent-tools.md` (the `check_fastener_joint` result); feature 005's
`contracts/ab-harness.md` sections 4 and 9 (the fields a ledger row reads, compare's version
refusal); feature 008's `contracts/checks-first.md` (the pre-run's step mark) and
`contracts/replay.md` (the replay fixtures regenerate); feature 010's `contracts/fasteners.md` and
`contracts/alignment.md` (section 10's references). Each amendment's text lands with the task that
changes the code.

Line numbers are at `be01974`; paths are under `reviewer/src/swreview/` unless another root is
given. Every example value is fictional.

## 1. What the scorer reads, and the modules

`score_run` (`benchmark/scorecard.py:477-508`) scores each package of the set from:

| Input | Read for |
|---|---|
| `<run>/<package>/session.json` | the final state: findings, coverage, steps, requests (FR-026) |
| `<run>/<package>/events.jsonl`, or `events.jsonl.gz` in a packed folder (owner decision 28A), found by `agent/events.event_stream` (plan decision RF-83) | withdrawn findings (section 3.3) and time to first finding (`seconds_to_first_finding`, `:311-353`), in one pass through the product's one event-line reader, `agent/events.replay_events` (moved there from `chat/sessions.py:106-129` in the key-extensions slice; plan decision RF-29), whose `on_unreadable` hook names the line where it stops; `seconds_to_first_finding`'s own loop goes |
| `<run>/<package>/answer-log.json` | the question columns (`questions.md` section 6) |
| `<run>/run-status.json` and each attempt's stream, plain or packed, only through `package_outcome` and `attempt_facts` (`benchmark-run.md` section 10), from the robustness slice | `run_status`, `cost`, `served_models`, `unscored_packages`, `failed_attempts` with their `folder`, and `price_table` (section 7; plan decisions INT-9, RF-16, RF-17, RF-45) |
| the key the set names | `answer-key.md`; loaded with the package the saved set names |
| the words file | the report's goals (section 4), `report.summary.load_words()` (`report/summary.py:351-353`) |

It never calls a provider and never re-runs a review: re-scoring needs the run folder, the key and
the package (US1-11). Modules:

| Module | Holds |
|---|---|
| `benchmark/matching.py` (new) | section 2: the one matcher, used by the scorer, the key's overlap test (`answer-key.md` section 5) and the oracle builder |
| `benchmark/origins.py` (new) | section 5: the origin of a finding |
| `benchmark/answer_key_model.py` | the key's format, data only: entries, patterns, reference kinds (`answer-key.md` 1; plan decision RF-1); `matching.py` reads its pattern grammar and reference kinds from here |
| `benchmark/answer_key.py` | the key's loader and its load-time refusals (`answer-key.md` 1, 4) |
| `benchmark/questions.py` | the question columns (`questions.md`) |
| `benchmark/scorecard.py` | sections 3, 4, 6, 7 and 8 |

`classify_match`, `check_prefix` and `MatchRule` (`benchmark/scorecard.py:57, 122-140`) go: the
prefix rule they implement is the sibling credit 4A removes (research §2 prefix-sibling-credit).
The matching loop written twice (`:267-271`, `:303-307`) becomes one pass.

## 2. The matcher

A finding **matches** an entry (known defect, correct condition or forbidden entry) when all three
of 2.1 to 2.3 hold.

### 2.1 Checks (FR-001, SP-10)

The finding's `check` equals the entry's exact check, or starts with a family's id and a dot
(`answer-key.md` section 3). A forbidden entry's `checks` match when any one does. Nothing else:
`fastener.thread_match` never matches a `fastener.bottoming` entry, and `rms.folders.present`
never matches `rms.folders.ordered` (US1-1, US1-8).

### 2.2 Targets (FR-003, SP-4 B)

The finding's **parts** are its `component_ids`. Its **documents** are the `document_id`s of its
`drawing_locations`, and, only when it names no component id and no drawing location, the
`document_id`s of its `provenance` (a document-scoped finding, `findings.py:338-343`). They
**overlap** the entry when the parts intersect the entry's `component_ids` or the documents
intersect its `document_ids`. A component finding's provenance, which holds its part document
(`findings.py:273-290`), is never read, so a hygiene finding on a part does not reach a key entry
on a drawing of that part. The model's drawing finding (`tools/session.py:456-531`) names its
drawing locations, so it overlaps an entry on its drawing document (US1-6); a standards finding on
a drawing, bound through `document_ids` with no location, overlaps through its provenance (US1-7).

### 2.3 References (FR-003, FR-061, 19A)

For a reference-keyed check (`answer-key.md` section 2.5) the entry names covered items; the
finding must name one of them **exactly**. The finding's references are read from its `inputs`
(`findings.py:119`) and nothing else, by the kind of the finding's check:

| Kind | Read from `inputs` |
|---|---|
| joint | the `str` entries without `#`: the fastener id and the hole id |
| hole pair | the `str` entries without `#`: the two hole ids |
| recess, joint instances | the `str` entries with `#`: hole instances (`checks/joints.py:649`) |
| fit, stack | each `Dimension` entry's `(document_id, sheet, annotation)` |

The finding matches the entry when that set **equals** the set of one covered item's references.

- **One field.** After section 10, every result of these checks carries its references in `inputs`
  on every path: the four fastener rules lead with the fastener and hole ids; `hole.coaxiality`
  writes both hole ids (`checks/hole_alignment.py:108, 140`); the joint map's alignment checks the
  joint's instances (`checks/joint_alignment.py:236, 399, 520, 643`); `fastener.head_fit` the recess
  instance beside the fastener's component (`checks/tool_access.py:409`), which the recess kind
  does not read; a fit its bore and shaft (`checks/fit.py:121, 170`); a stack its contributors and
  target (`checks/stack.py:86`). `calculation.inputs` and `drawing_locations` repeat what `inputs`
  holds and are not read. Plan decision SR-3.
- **Equality, not "names all those of one".** For the fixed-size kinds the two are the same. For a
  stack, equality keeps a chain with an extra or a missing contributor from crediting or clearing
  the planted stack; for joint instances, it keeps an entry naming part of a joint from matching the
  joint's finding beside another entry naming the rest. Both would otherwise let one finding match
  two entries (SC-002).
- **Roles are not compared.** A fit called with bore and shaft swapped names the same pair; its
  verdict is what the report shows the engineer about that pair, so a swapped interference fit
  reading as clearance clears the planted defect (section 3.1), and a swapped clearance fit reading
  as interference contradicts a correct condition. The same holds for a stack's signs.
- **What does not match** (US5-16): another fit on the same sheet, the bore against itself, another
  hole pair between the same plates, another screw between the same parts. Each names another set,
  and neither credits nor clears the planted entry.
- **A folded joint-map finding** names its first joint only (`checks/joints.py:1185-1226`); it
  matches an entry whose covered items include that joint (`answer-key.md` section 2.5).

## 3. Outcomes

Every rule reads the final state: the session's findings after the last answer turn (FR-026).

### 3.1 Known defects (FR-002, FR-005, 13A, SP-6, SP-7, SP-8)

For each known defect, of the findings that match it:

| Matching findings | Expected unresolved | Expected demonstrated or suspected |
|---|---|---|
| some demonstrated or suspected | credited, and a **status mismatch** | credited |
| none of those; some unresolved | **flagged** | **flagged below expected** |
| none of those | **missed** when no finding matched at all | the same |

Independently, any `checked_within_scope` match puts the defect in **cleared**, whatever the row.
**Detected** is credited or flagged. A defect whose only matches clear it is cleared, not detected
and not missed (US1-9; the spec's Terms). Demonstrated against suspected is never a mismatch
(SP-8). Order never matters: an unresolved and a demonstrated finding on a defect expected
unresolved credit it with a mismatch either way round (spec Edge Cases).

`PackageScore` lists, each in key order:

| Field | Holds |
|---|---|
| `matched_defect_ids` | detected: credited or flagged. The name is kept so adoption's rules (`benchmark/adoption.py:210, 220, 236`) read detection unchanged |
| `flagged_defect_ids` | detected through an unresolved finding only; a subset of matched |
| `status_mismatch_defect_ids` | credited with a status mismatch; in matched, not in flagged |
| `flagged_below_expected_defect_ids` | not detected; in no recall figure and never a false alarm (13A, C-5) |
| `cleared_defect_ids` | any clearing match; may meet any list but missed |
| `missed_defect_ids` | no finding matched |

Invariants, asserted on every scorecard the tests build: matched, flagged below expected and
missed are disjoint; every defect outside the three is in cleared; flagged is within matched;
mismatches are within matched and outside flagged; missed and cleared are disjoint. Credited is
matched less flagged, derived where rendered (SP-14). `valid_findings` (demonstrated or suspected
findings that credit a defect), `missed_known_defects` (`len(missed_defect_ids)`) and
`unresolved_count` keep their fields and meanings (`benchmark/scorecard.py:147-150`).

### 3.2 Correct conditions (FR-004, SP-5)

A condition is **contradicted** when a demonstrated or suspected finding matches it, and
**confirmed** when a `checked_within_scope` finding does; an unresolved match counts in neither.
`contradicted_condition_ids` and `confirmed_condition_ids`, in key order, `null` when the key has no
condition. A contradicting finding is a false alarm (3.3): the key's overlap refusal means it can
credit no defect (`answer-key.md` section 5), so today's excuse (`benchmark/scorecard.py:274-276`)
goes.

### 3.3 False alarms, forbidden entries and withdrawn findings (FR-017, D14.4, CL-09)

- A **false alarm** is a demonstrated or suspected finding of the final state that credits no known
  defect. One finding is at most one false alarm, whatever it also hits. `false_alarm_finding_ids`,
  session order. A key with no known defect makes every such finding one (spec Edge Cases).
- A **forbidden hit** is a false alarm that matches a forbidden entry: `forbidden_hit_finding_ids`,
  `null` when the key has no forbidden entry. Beside a contradicted condition it is still one false
  alarm (US3-1).
- A **withdrawn forbidden hit** is a finding that left the session before the end and, as last
  announced, was demonstrated or suspected and matched a forbidden entry. It is not a false alarm
  (US3-2). The session holds no withdrawn finding (`tools/context.py:316-335`), so it is read from
  `events.jsonl` through `replay_events` (section 1; plan decision RF-29): each `finding.withdrawn
  {finding_id}` whose id is not in the final state, and the last `finding` event for that id before
  it, whose body validates as a `Finding` (`report/titles.py:84-95`).
  `withdrawn_forbidden_hit_finding_ids`, `null` when the key has no forbidden entry, the stream is
  missing, or `replay_events` reports a line it cannot read (a withdrawal could lie after it), the
  reason in `not_assessed` (section 7), naming the line: unknown is never 0 (Principle I). The same
  pass gives time to first finding: the first computed finding before any unreadable line, else
  `None`, as today.
- A false alarm is **tuned-on** when it matches any tuned-on forbidden entry or tuned-on correct
  condition: `tuned_on_false_alarm_finding_ids`, a subset of the false alarms. The verdict leaves
  them out of its deciding figure (D15); a false alarm that hits nothing, or only held-out items,
  stays in. A finding hitting a tuned-on and a held-out item is tuned-on: it is a behaviour the
  prompt was written around. Plan decision SR-10.

Every finding of the final state and every withdrawn forbidden hit is scored whatever its origin,
carried findings included (lever 11a); section 5 says where each came from.

## 4. Expected coverage (FR-018, D6)

Each expected-coverage entry is read through the report's own reader: `finding_groups.goal_of` of
the entry's item picks the goal, and that goal's reading is taken from the state decision the
report's goal lines are built from (`report/finding_groups.py:167-181, 186-204, 207-247`).

**The reading, not the line** (plan decision RF-23). `GoalLine.reason` holds the words file's
display text, `words.goal_reasons[reason]` (`:226`; "evidence missing", "a check failed",
`report/review_words_v1.yaml:115-120`), not the `GoalReason` key this table maps from. The state
decision of `_goal_line` (`:207-247`) is therefore extracted as `finding_groups.goal_readings(session,
words) -> list[GoalReading]`, one `GoalReading(goal, state, reason, row)` per goal with `reason` the
`GoalReason` key; `goal_lines` builds each `GoalLine` from its reading, so the pane's bytes do not
move, and the scorer reads `state` and `reason` from it. Matching display text would tie scoring to
the words file's wording; re-deriving the key would be a second reader.

| Goal reading (`state`, `reason`) | Read as |
|---|---|
| `issues`: a finding in the goal other than a pass (`:214, 231-232`) | `checked` |
| `checked` | `checked` |
| `not_reached`, `unresolved` or `failed` | `unresolved` |
| `not_reached`, `skipped` | `skipped` |
| `not_reached`, `no_check` | not reported: always a mismatch |
| `not_applicable` (`out_of_scope`) | `out_of_scope` |

A reading outside the entry's `statuses` is a mismatch: `coverage_mismatches: [{"entry": "CV-1",
"item": "interference", "read": "checked"}]`, key order, `null` when the key has no entry. R-5 on
the off arm, where the model marks interference checked, reads `checked`, one mismatch naming the
item; the on arm's skipped pre-run row or finalization's unresolved row reads within
`["unresolved", "skipped"]` (US3-3). An item whose only row failed reads `unresolved` (US3-4).

- No second reader and no change to which rows a goal reads: of the pre-run's
  `coverage.prerun.<family>` rows only interference and standards are goal items
  (`report/review_words_v1.yaml:134, 171`); the rest reach no goal line, and no key may expect a
  status only they would give (research §8.4).
- `issues` reads `checked` because the item was examined. The cost: a goal whose only finding is
  unresolved also reads `checked`. `answer-key.md` row 10 refuses the one key this would make
  unsatisfiable. Alternative kept: `issues` as a status a key may list (research §8.4). Plan decision
  SR-11.
- One expectation per goal (`answer-key.md` row 9): `interfaces.fit` and `interfaces.stack` share
  the fits-and-stacks goal, so an expectation on either reads the goal's one state.

## 5. Origins (FR-007, D9, 17A, 20A)

### 5.1 The values

`benchmark/origins.Origin` has eight values for FR-007's seven origins, the third split by kind:

| Value | The finding |
|---|---|
| `prerun` | cites a step the pre-run made before the first turn |
| `regrade` | cites a step code re-ran after an answer: the part-roles regrade and the drawing check restated after a confirmed read, both through `_restate` (`agent/runner.py:1178-1185, 1227-1263`) |
| `code_only_call` | cites an unmarked step of a code-only tool: one the pre-run can call, or a check with no required parameter (spec Terms, 20A) |
| `configured_check` | a check the model set up: today the four argument-taking check tools, whose findings cite no step (`tools/checks_fastener.py:283, 373`; `tools/checks_fit.py:67, 109`) |
| `model` | written by the model (`source` `model`: `record_drawing_finding`, `findings.py:146-149`) |
| `carried` | carried from an earlier review (`carried_over_from`, `findings.py:129`) |
| `setup` | written by code while preparing every review, citing no step: the provenance family (`agent/runner.py:401-424`) |
| `unknown` | in a session without the origin-marks record |

**Model origin** is `model` and `configured_check` (17A, 20A); `MODEL_ORIGINS` names them once.
Every other value but `unknown` is code origin.

*Amended 2026-10-07 (owner decision 40A; research SP-3): every finding writer that cites no step.*
At `be01974` `check_interference_group` was one (`tools/checks_interference.py:120`), although its
contacts cite their step (`:161`), so a pre-run interference finding would have read
`configured_check` by 5.3's rule 5. It now cites its step on every finding, as on every contact: a
pre-run interference finding reads `prerun`, a model-called one `code_only_call`. After it, a finding
citing no step is written by one of: `check_fastener_joint` and `check_hole_alignment`
(`tools/checks_fastener.py:283, 373`) and `check_fit` and `check_axial_stack`
(`tools/checks_fit.py:67, 109`), the four argument-taking check tools (`configured_check`);
`record_drawing_finding` (`tools/session.py:512`; `model`, by its `source`); or the provenance set-up
records (`agent/runner.py:414`; `setup`). A carried finding keeps its earlier review's ids (`carried`,
by rule 1). Every other finding writer cites the step in flight.

### 5.2 The step mark and the session record (the product change of SP-2)

```python
# reviewer/src/swreview/report/session.py
StepMark = Literal["prerun", "regrade"]
ORIGIN_MARKS_VERSION = 1

class InvestigationStep(ReviewModel):
    ...
    origin_mark: StepMark | None = None      # omitted when None

class ReviewSession(ReviewModel):
    ...
    origin_marks: int | None = None          # omitted when None
```

- `prerun.recorded_call` (`prerun.py:1201-1236`) gains a required keyword `mark: StepMark`. After
  `call_tool` returns, each step appended from `step_index` on is replaced in `session.steps` by a
  copy carrying the mark. `_prerun_call` passes `prerun` (`:1190-1198`, called at `:1099, 1284`);
  `_restate` passes `regrade` (`agent/runner.py:1258`). No other caller exists. Plan decision SR-13.
- `start_review` sets `session.origin_marks = ORIGIN_MARKS_VERSION` beside `session.efficiency`
  (`agent/runner.py:1620`), on every new session, whatever the levers. It is a value written on
  every new session, not a flag dropped when false, because the session omits false and null fields
  so that older sessions keep their bytes (`report/session.py:73-75, 582-608`); a session written
  before it loads with `None` and round-trips to its own bytes.
- The events are unchanged: `tool.started` and `tool.finished` carry no mark (feature 002's
  `chat-events.schema.json`), and the stored `tool-results/step-<n>.json` does not either. Only
  `session.json` gains the fields, and feature 001's session schema with them.
- **Its commit** (plan decision RF-27) lands in the scorer slice after 19A's (section 10), and
  regenerates the replay fixtures on the development machine, since `start_review` writes their
  `session.json` (`tests/fixtures/replay/generate_fixtures.py:162`; `tests/support/replay.py:109-153`
  plays the recording through `benchmark/replay.play_review`, which calls `start_review` at
  `benchmark/replay.py:337`). Its gate: the only difference under `reviewer/tests/fixtures/replay/` is
  one `"origin_marks": 1` in each of the three `session.json` files; every `events.jsonl` and
  `package.json` is byte-identical (the `session.started` body names no session field, and no step is
  marked: none of the three recordings runs the pre-run or answers a question); and
  `test_pane_fixture.py` passes unchanged, since the pane fixture is `review_snapshot`, which carries
  no session-level field. It takes no freeze: nothing the model reads moves.
- Compare's tool-call count (`benchmark/compare.py:293-295`, `len(session.steps)`) is not split by
  the mark in this feature: the ledger's closing notes say it counts the pre-run's and the regrade's
  steps with the model's (plan decision INT-10, research §4 cross-check "tool calls on the pane
  row"). The pane study's call measure is FR-016's fit and axial-stack calls, which the pre-run never
  makes.

### 5.3 The derivation

`finding_origin(finding, session)`, first rule winning; no second stored field (C-17):

1. `carried_over_from` is set: `carried`.
2. `source` is `model`: `model`.
3. `session.origin_marks` is `None`: `unknown`. Every other code finding of such a session reads
   unknown, `setup` and `configured_check` included, because US1-12 says its code findings' origin
   is unknown; carried and model-written findings are read from their own fields, not from a mark,
   and keep their origins. Plan decision SR-14.
4. `tool_result_ids` is non-empty: the step with the highest index it cites. No such step in the
   session: `unknown`, never guessed, in a session with the record too (FR-007): the folder was
   altered or written by something other than the review. Compare refuses the verdict of a pane
   study holding such a false alarm (section 5.5; plan decision SR-25). Marked `prerun` or `regrade`: that value. Unmarked: its
   `tool` in `CODE_ONLY_TOOLS`, `code_only_call`; otherwise `configured_check`.
5. It cites no step: its check starts with a prefix in `SETUP_CHECK_PREFIXES` (`("provenance.",)`),
   `setup`; otherwise `configured_check`.

A regrade that re-produces an earlier finding keeps the earlier id and cites the restated step
(`agent/runner.py:1293-1297`), so a finding that survives a scripted "All bought" reads `regrade`
(US1-13). An off-arm session with the record and no marked step reads its code findings as checks
the model called (US1-12).

### 5.4 The code-only tool set

```python
CODE_ONLY_TOOLS = frozenset({
    *prerun.prerun_tools(),          # RMS_PRERUN_TOOLS, INTERFERENCE_TOOL, CODE_FIRST_CHECKS (prerun.py:144-156, 209-213)
    prerun.LIVE_INTERFERENCE_TOOL,   # "bridge_interference" (prerun.py:159)
    drawings.DRAWINGS_TOOL,          # "check_drawings" (tools/drawings.py:67)
    standards_registry.CHECK_TOOL,   # "check_standards" (checks/standards/registry.py:98)
})
```

`CODE_ONLY_TOOLS` is built from the constants that already name those tools, so a pre-run change
moves it with no second edit (plan decision RF-6). Every other check tool is a configured check by
rule 4's "otherwise"; no second set names them, since only the structural test would read it (plan
decision RF-68). Read by tool, not by exact call: a model's `check_rms_part(document_id=...)`
narrows the rules the pre-run's call grades and gives the same findings, so it is code-only
(research §8.5, D15).

**The signature rule** is the spec's Terms: a code-only call is "any tool the pre-run calls, or a
check with no required parameter". So every `CODE_ONLY_TOOLS` tool is in `prerun.prerun_tools()`, is
`LIVE_INTERFERENCE_TOOL`, `DRAWINGS_TOOL` or `CHECK_TOOL`, or has no required parameter; and every
check tool outside it has a required parameter and is not a pre-run tool. Two pre-run tools
take arguments, and are the named exceptions: `check_interference_group(group_key)`
(`tools/checks_interference.py:69`), which the pre-run calls once per group (`prerun.py:737-739`),
and `bridge_interference(component_ids, configuration, settings)` (`tools/bridge.py:397-399`), its
live call (`prerun.py:159`). A structural test (S-5.4) holds this rule over every check tool (plan
decisions RF-38, RF-68).

### 5.5 Who refuses what

The scorer never refuses on origin. Compare refuses the verdict of a pane study holding a session
whose `origin_marks` is `None`, or a false alarm whose origin is `unknown` (rule 4's missing step,
SR-25), naming the session, the finding where there is one, and the command that re-runs it
(`verdict.md` 7, refusal 3); lever studies and re-scoring read such findings as `unknown` (FR-007,
US1-12). That refusal is the compare contract's;
it reads the session, which compare already loads (`benchmark/compare.py:310-316`).

`finding_origins: {finding id: Origin}` on `PackageScore` covers every final-state finding and
every withdrawn forbidden hit. Findings and false alarms by origin are derived from it where
rendered (SP-14); the aggregate stores the summed counts.

## 6. Producers, tags and recall (FR-006, FR-031, FR-032)

- **Graded items.** `PackageScore.graded_items` copies, for every key entry, `id`, `kind`, `tag`,
  and for a known defect `producer` and `expected_status`. Compare reads no key (feature 005's
  `ab-harness.md` section 3), so the verdict splits recall and false alarms from this list.
- **Recall.** Over known defects, detected over all. `Aggregate.recall` keeps its field and becomes
  held-out items of both producers, read from the tags: the package-flag filter
  (`benchmark/scorecard.py:431-435`) goes (research §8.7). `Aggregate.recall_by_producer` holds
  `{"model": {"held_out": r, "tuned_on": r}, "code": {...}}`. A group with no defect is `null`, not
  computable (SC-001).
- **The held-out count.** `Aggregate.held_out_model_defects` is the number of held-out
  model-produced defects the keys of every package of the set name
  (`AnswerKey.held_out_model_defect_ids()`, `answer-key.md` 1; plan decision RF-67), counted from
  the keys whether or not the package's session scored (FR-032: before failures). Counts after failures are the
  verdict's (FR-058).
- **The set's flag.** For each package, the saved set's `held_out` (`benchmark/sets.py:27, 59`) must
  equal `AnswerKey.holds_held_out()`, "the key holds a held-out item" (RF-67). A mismatch refuses
  the score: "{package}: the set marks it
  held_out={flag}, but its key holds {n} held-out items; the flag is derived from the key" (US5-12).
  Compare, which reads no key, makes the same check from the scorecard: each scored package's flag
  against "some `graded_items` entry has tag `held_out`" (`provenance.md` 2; plan decision RF-39).
- A set naming a key-only key is refused (`answer-key.md` section 6).

## 7. The scorecard

`PackageScore` and `Aggregate` gain these fields, each required: a scorecard missing one is refused
as malformed after the version check (section 8), never defaulted. Lists only, counts derived where
rendered (SP-14); the aggregate stores summed integers.

| `PackageScore` field | Section |
|---|---|
| `flagged_defect_ids`, `status_mismatch_defect_ids`, `flagged_below_expected_defect_ids`, `cleared_defect_ids` | 3.1 |
| `contradicted_condition_ids`, `confirmed_condition_ids` | 3.2 |
| `forbidden_hit_finding_ids`, `withdrawn_forbidden_hit_finding_ids`, `tuned_on_false_alarm_finding_ids` | 3.3 |
| `coverage_mismatches` | 4 |
| `finding_origins` | 5.5 |
| `graded_items` | 6 |
| `re_asks`, `open_repeats`, `unanswerable_requests`, `unmatched_requests`, `question_counts`, `unscripted_questions`, `bound_reached` | `questions.md` section 6 |
| `not_assessed` | `{column: reason}` for every `null` column above |
| `run_status` | `{"kind": "completed" or "behavioural" or "not_recorded", "class": ..., "stop_reason": ...}` from `package_outcome` (`benchmark-run.md` sections 9 and 10); `not_recorded` for a run folder with no `run-status.json` (made before feature 014's robustness slice), never guessed completed |
| `cost` | the kept attempt's cost record from `price_rounds` (`benchmark-run.md` section 13): amount or `null`, what is missing, basis notes, `synthetic` |
| `served_models` | the distinct served ids the kept attempt's rounds reported, in first-seen order, from `attempt_facts`; `[]` when no round reported one (not reported, never a mismatch, `benchmark-run.md` 7). Compare's served-model re-check reads it (`provenance.md` 2; plan decision RF-16) |

`Scorecard` gains `scoring_rules_version` (section 8); `key_sha256: {package id: hex}`, the raw
bytes' `sha256_of` of each key read (compare refuses a study whose runs name two digests for one
package's key, naming it: an arm scored against an edited key measures the edit; plan decision
INT-16); `unscored_packages`, one row per package whose outcome is an infrastructure failure
(`package_id`, `kind`, `class`, `error_class`, `attempts`, and `folder`, the run-relative folder
of its last attempt), which has no session and no
`PackageScore`, so compare, which loads one session per `PackageScore` (`benchmark/compare.py:
310-316`), never meets a missing one; and `failed_attempts`, every infrastructure attempt of the run,
kept packages' earlier ones included (`package_id`, `attempt`, `class`, `retries`, `cost`, and
`folder`, run-relative, `/`-separated, copied through `attempt_facts`), the usage D2 says a failure
billed. The report opens a failed attempt's `events.jsonl` through `folder` (`report.md` 2; plan
decision RF-17). And `price_table`: `null` when no round was priced, else `{"prices_version",
"models": [{"provider", "model", "input": {"source", "date"}, "cached_input": {...}, "output":
{...}}]}` for every entry of `benchmark/prices.yaml` a round of the run was priced by, which the
report's head prints (`report.md` 4); a `Scorecard`-level field, outside the golden view (plan
decisions RF-21, RF-45). `Aggregate.packages` becomes `ge=0` and `Scorecard.per_package` loses its
`min_length=1`: a run whose every package failed still scores (`benchmark/scorecard.py:212, 244`
require one today). `run_status`, `cost`, `served_models`, `unscored_packages`, `failed_attempts`
and `price_table` land with the robustness slice (plan, delivery order 6), which bumps the version
for them (section 8); until then a scorecard carries none of them.

`Aggregate` gains `detected`, `flagged`, `status_mismatches`, `flagged_below_expected`, `cleared`,
`contradictions`, `confirmations`, `forbidden_hits`, `withdrawn_forbidden_hits`,
`tuned_on_false_alarms`, `coverage_mismatches`, `findings_by_origin`, `false_alarms_by_origin`,
`recall_by_producer`, `held_out_model_defects`, the question columns' sums, and, with the
robustness slice, `cost` (summed only when every package's is known) and `failed_attempts_cost`. A
column no package assesses sums to `null`; a column some packages assess sums over those, and the
rendering says how many of how many.

**Not assessed** (FR-021, US3-8): a column tied to a key list is `null` when the key has no entry of
that list, and renders "not assessed", never 0; `withdrawn_forbidden_hit_finding_ids` is also `null`
when the events stream cannot be read, and renders "unknown". One map, `not_assessed`, holds the
reason for every `null` column, the question columns' included (`questions.md` section 6 uses it;
plan decision INT-2). The defect, false-alarm, origin and coverage-row columns are always assessed.

**Rendering.** `render_scorecard_md` (`benchmark/scorecard.py:528-586`) adds per package: detected,
flagged, below expected, cleared, false alarms and those of model origin, contradictions, forbidden
hits, coverage mismatches; and to the aggregate: recall by producer and tag, false alarms by origin,
the held-out model-produced count, and each question column. `benchmark score`'s summary
(`cli.py:2393-2398`) becomes, pinned by a test:

```
scored {packages} packages of set {name} (scoring rules version {v})
detected: {detected} of {known} (flagged {flagged}; below expected {below}), cleared: {cleared}, false alarms: {fa} ({model} of model origin), unresolved: {unresolved}
wrote {scorecard.json} and {scorecard.md}
```

The ledger's columns are the compare contract's (SP-13); a ledger schema bump for this contract's
fields and parity's is one bump, and the committed header is regenerated once, with the final
column order fixed up front (research §4 cross-check). Plan decision SR-20; the order itself is
`provenance.md` section 5's (plan decision INT-10).

## 8. The scoring-rules version (FR-008, SP-11, D14.2)

- `benchmark/scorecard.SCORING_RULES_VERSION = 2`, written as `Scorecard.scoring_rules_version`. A
  scorecard without the field was scored under version 1.
- Any change to matching or counting, here or in `questions.md`, and any new required scorecard
  field, bumps it; section 9.4 makes a golden change without a bump fail the tests, and a bump
  without a golden change fail them unless its row declares `"goldens_unchanged": true` with its
  reason, which only a bump adding or changing fields outside the golden view may do (a field in
  `GOLDEN_EXCLUDED`, or a `Scorecard`-level field; SC-013; plan decision RF-21). **Across this feature's slices** (plan, delivery order): the scorer
  slice writes 2; the key-extensions slice, which adds the forbidden, coverage and question columns,
  writes 3; the goldens and the record (section 9.4) arrive with the validation slice, whose first
  row carries the version then current; the robustness slice's `run_status` (section 7) moves every
  golden and writes the next version with a row of its own. Until the record exists a slice that
  changes scoring bumps the constant, pinned by a test of its value, so a scorecard scored at an
  earlier slice meets the re-score line, never a silent difference (plan decision INT-11).
- `read_scorecard(run_dir) -> Scorecard` is the one reader. It parses the JSON, reads the version
  **before** validating the model, and refuses:
  - a lower version: "{run dir}: scorecard.json was scored under scoring rules version {v}; this
    build scores under {V}. Re-score it: swreview benchmark score {run dir} (add --answer-keys <dir>
    when its set names no keys; it reads the saved session; nothing is re-run)". The line is fixed
    text, so the refusal reads no second file (plan decision RF-4);
  - a higher one: "{run dir}: scorecard.json was scored by a newer build (version {v}); compare it
    with that build, or re-score it with this one".
  Then it validates, and a validation error is re-raised naming the folder and the first field (an
  unknown field today surfaces as a bare validation error, `cli.py:530-542`). Both are
  `ValueError`s: one line, exit 1.
- Compare's `_load_run` (`benchmark/compare.py:300-307`) calls `read_scorecard` in place of
  `Scorecard.model_validate_json`, before it loads sessions and before parity's cross-checks, so a
  folder scored before this feature meets the re-score line and not a validation error (research §4
  cross-check, refusal order). Study fixtures (`reviewer/tests/support/studies.py:230-253`) write
  the new fields and the version.
- Re-scoring overwrites `scorecard.json` and `scorecard.md` with the current version; compare
  accepts the result. An old checks-first session re-scores with its code findings `unknown`
  (section 5.3).

## 9. Golden scorecards and probes (FR-049, SC-001, SC-002, SC-013)

The validation over the committed set (FR-054; its own contract) builds the oracle, null and probe
reviews as package folders (9.2) and writes and checks their goldens. The generator cannot: the scorer imports agent
code (`benchmark/scorecard.py:50-51`). This section fixes the scoring halves; the question halves
are `questions.md` section 8.

### 9.1 The golden view and files

A golden is `PackageScore` less the fields no scoring rule writes: `session_id`, the four timing
minutes, `usage`, `round_trips`, `cached_input_share`, `wall_clock_s`, `seconds_to_first_finding`,
`tool_calls_by_name`, `cost` and `served_models` (`GOLDEN_EXCLUDED`, one tuple): a price-table edit,
or a provider's snapshot name, moves no golden.
`run_status` is in the view: which figure a package run enters is the scorer's reading, and a probe
with a behavioural stop moves it alone (9.3). **`GOLDEN_IDENTITY`**, `("package_id", "held_out",
"graded_items")`, names the view's fields no behaviour can move: they say which package and which
items a golden grades, and are exempt from 9.3's "every field has a probe" (plan decision RF-43). The validation passes the synthetic reviews'
`run_status` (`completed`) to the scorer's per-package function directly. Goldens are
`reviewer/tests/golden/test_golden_scorecards/<case>--<review>.yml`, written and compared with
pytest-regressions' `data_regression` and regenerated with `--force-regen`, as the check goldens are
(`reviewer/tests/golden/test_golden.py:9, 108-115`).

### 9.2 The oracle's findings and coverage, and the null review

- **The builder**: `oracle_review(key, package, folder)` in
  `reviewer/tests/support/scoring_probes.py`, the one oracle builder (the golden scorecards, the
  validation and `test_committed_answer_keys.py` call it). For a key-only key (`answer-key.md` 6), which has no package, it builds against
  `stand_in_package(key)`: `tests/support/packages.build_package` with one component instance per
  component id the key names and one document, with its manifest entry, per document id, so
  `build_finding` can attach provenance; nothing else about the stand-in is read, and the ids stay
  unchecked, as the key's are (US1-16). The oracle and null reviews are scored through the scorer's
  per-package function (`_score_package`, `benchmark/scorecard.py:363`, which `score_run` calls per
  package), since `score_run` refuses a set naming a key-only key (plan decision RF-15).
- **A package folder, as a run leaves one** (plan decision RF-58). Each review is written into
  `folder` in the shape the scorer reads: `session.json`; `events.jsonl` holding the one
  `session.started` event, written through the product's `EventSink` (`agent/events.py:76-119`), so
  the withdrawn-hit pass (3.3) reads a stream, not a missing file; and each of the oracle's request
  calls (`questions.md` 8) made through the real `request_evidence` tool with a `ToolContext` whose
  `tool_results_dir` is `folder/tool-results/`, so `SessionSink.record` writes its step and its
  stored result (`tools/registry.py:362-432`) and every call reads as readable (`questions.md` 1).
  No answer log. The per-package function reads the folder as `score_run` reads each package of a
  run.
- **One finding per known defect**, built with `build_finding` against the package (or the
  stand-in) so its provenance is real: its check is the entry's (a family's id with `.oracle`
  appended); its status the expected status; `source` `model`; its parts the entry's component
  ids; for a reference-keyed entry,
  `inputs` holding the first covered item's references (ids as strings, dimensions resolved with
  `resolve_dimension`, and those dimensions' sources as its drawing locations); for an entry on
  documents only, those documents bound through `document_ids`. A demonstrated status cites one
  synthetic step, since a numeric status needs a calculation or a tool result (`findings.py:356-359`);
  an unresolved one carries a coverage limit (`:360-361`).
- **No finding** for a correct condition or a forbidden entry: a correct condition asks for nothing.
- **One coverage row per expected-coverage entry**, check the entry's item, in the bucket of its
  first listed status. `answer-key.md` row 10 makes that read back as expected.
- The oracle session carries `origin_marks`.
- **The null review** is an empty session carrying `origin_marks`: no step, finding, coverage row
  or request, and no answer log.

SC-001 is then asserted over every committed key, `rms-part` through its stand-in, column by column
against the key: the oracle detects every known defect, and every failure column the key grades
reads zero (an empty list, no miss): false alarms, contradictions, forbidden and withdrawn forbidden
hits, coverage mismatches, flagged below expected, status mismatches, cleared defects and every
question column; a column reads `null`, its reason in `not_assessed`, exactly when the key has no
entry of the list it reads, and `unscripted_questions` and `bound_reached` always, since they read
an answer log, which no oracle has and no key grades (`questions.md` 8). `not_assessed` names no
other column, so a stream or a stored result the builder failed to write fails the test instead of
reading "not assessed". The null detects none and raises no false alarm; with no known defect both
read recall `null`. SC-002: each oracle finding matches its own defect and no other.

### 9.3 The probes this contract requires

Each probe starts from a committed case's oracle or null review, adds or changes one behaviour, and
declares the columns it moves **with the delta of each**; its test asserts that its golden differs
from the base's in exactly those columns and by exactly those deltas (US3's Independent Test: "by
one each"), so a probe that counts one behaviour twice fails. A probe that adds a tool call makes it through the
real tool, as the oracle does (9.2), so the base's readable columns stay readable. The delta is 1 per column for a count
or an id list, and the named change for a status or a mix (an origin moving from one value to
another). Some behaviours move two columns by definition, 1 in each: a forbidden hit is a false
alarm, a contradiction is a false alarm.

- **Columns**: credited; flagged; credited with a status mismatch; flagged below expected; cleared,
  alone and beside a credit; missed; a plain false alarm; a contradiction; a confirmation; a forbidden
  hit; a withdrawn forbidden hit; a tuned-on false alarm; a coverage mismatch of each reading; each of
  the eight origins; the unresolved coverage split (`unresolved_other`, `unresolved_because_withheld`);
  the event stream unreadable from line N, on a case whose key has forbidden entries
  (`withdrawn_forbidden_hit_finding_ids` to `null` and its reason into `not_assessed`, RF-70); and,
  with the robustness slice, a behavioural stop (`run_status` alone).
- **Matching rules** (`MATCHING_RULES`, kept beside the probes in
  `reviewer/tests/support/scoring_probes.py`): exact check; family at depth; the family boundary
  (`x`, `xs.y`); a sibling rule on the same part; part overlap; drawing-location overlap;
  provenance-document overlap, and a component finding's provenance not read; each reference kind of
  section 2.3 but the recess, on a resolved and on an unresolved result; a role-swapped fit; a stack
  with an extra contributor; another pair between the same parts; a withdrawn finding read from the
  stream; one false alarm for a finding hitting a condition and a forbidden entry. The recess kind
  (`fastener.head_fit`) and a folded joint-map finding are left to `test_benchmark_matching.py` 4
  and 5, which build them from the real checks: a probe starts from a committed case, and no
  committed case keys a recess or is designed to fold joints (plan decision RF-70).

**The derived fields** move with the behaviours that define them, and the probe that moves each
declares it: `valid_findings` the credited probe, `missed_known_defects` the missed probe,
`false_alarms` the plain false-alarm probe, `unresolved_count` the flagged probe (an unresolved
finding), `carried_findings` the `carried` origin probe, and `coverage_bucket_mix` each
coverage-mismatch probe and the unresolved-coverage split probe (plan decision RF-43). `not_assessed`
is declared, with the reasons it gains or loses, by every probe that moves a column between `null` and
assessed: the stream-unreadable probe and `questions.md` 8's answer-log probes (plan decision RF-70).

A structural test fails when a field of the golden view outside `GOLDEN_IDENTITY`, or a name in
`MATCHING_RULES`, has no probe declaring it, so a new column or rule arrives with one; a probe whose
case or entry has gone fails naming both. A second test fails when any probe's golden differs from
its base's in a `GOLDEN_IDENTITY` field.

### 9.4 The version record

`reviewer/tests/golden/scoring_rules_versions.json`, rows appended, never edited:

```json
[{"version": 3, "goldens_sha256": "<hex>", "reason": "feature 014: exact and family matching, references, 13A statuses, origins, forbidden entries, coverage, questions"}]
```

`goldens_sha256` is the sha256 over every golden file of 9.1, in sorted path order, each as its
relative path, a NUL, its bytes as git stores them and a NUL. "As git stores them" is
`tests/support/mechanical.as_committed` (moved there once by `generator.md` 11 from both of its
copies, `reviewer/tests/unit/test_support_mechanical.py:266` and `test_support_drawings.py:253`; plan
decision RF-55), CRLF read as LF: `data_regression` writes the
files in binary with LF (`pytest_regressions/data_regression.py:79`, `open("wb")`) while a Windows
checkout under `*.yml text` and `core.autocrlf` hands them back CRLF (`git ls-files --eol` reads
`w/crlf` for `test_golden/joint-ok.yml` at `be01974`), so a raw digest would differ between a fresh
regeneration and a checkout on one machine (plan decision INT-12). The record starts with the
validation slice at version 3 (plan decision INT-11): versions 1 and 2 were never goldened. The
tests fail when: the last row's version is not `SCORING_RULES_VERSION`; the goldens' digest is not
the last row's (a golden change without a bump); two rows share a digest (a bump with no golden
change), unless the later row declares `"goldens_unchanged": true` with a non-blank `reason`; a row
declaring it whose digest differs from the previous row's; or versions do not rise by one. An edited
committed row is left to review, which sees it in the diff: a check of the record at `HEAD` or at
the merge base with `main` would depend on git history and a branch name to show what the diff
already shows (plan decision RF-69). This settles research §8.15's open point. Plan decision SR-19.

## 10. 19A: references on every path (FR-061)

A product change, in one commit with the fixtures it moves (feature 008's decision 3A):

| Where | Change |
|---|---|
| `checks/fastener.py` `_Stack` (`:221-244`) | gains `refs: list[str]`, set to `[fastener.id, hole.id]` by `_build_stack` (`:267-268`) and `_placed_stack` (`:809-810`), beside the `fastener_id` and `hole_id` they already put in `stack.inputs` |
| every result of the four rules | `inputs` becomes `[*stack.refs, *stack.sources]` at each of the thirteen sites that pass `stack.sources` today (`:347, 365, 374, 391, 476, 496, 524, 538, 563, 612, 650, 668, 679`): unresolved paths (bottoming `:362, 371`, engagement `:467-477`, thread match `:521, 535`, head clearance `:609`) and resolved ones alike, through one helper. `calculation.inputs` is unchanged |
| `_unsupported` (`:689-701`) | takes the hole; `inputs` `[fastener.id, hole.id]`; both callers name one (`:730`, `:904`) |
| `checks/joint_alignment.py` `_unknown_role` (`:222-233`) | its `inputs` name every instance of the joint, not only those of unknown role; its callers (`:291, 508`) pass the joint beside the unknown instances, whose hole ids its `observed` and `recommended_action` still name, so the text does not change. `_no_fastener` (`:236`) and the missing-tolerance result (`:520`) already do |
| `checks/golden_fastener.py` | gains `alignment_case(package)`, the golden adapter for the new `joint-unknown-role` case: `build_joint_map` and `run_joint_checks` over the fixture with its tolerance sources read as `check_joints` reads them (`ResolverLookup`, `tools/checks_mechanical.py:311-313`), the results as JSON-ready data like `joint_case`'s |
| `checks/hole_alignment.py`, `checks/tool_access.py`, `checks/fit.py`, `checks/stack.py` | unchanged: their results already carry their references on every path |

Resolved paths change too, which research §8.12's starting design did not ask: with the ids in
`inputs` on every path, section 2.3 reads one field instead of `calculation.inputs` on one path and
`inputs` on the other. Plan decision SR-5.

**Consequences.** The tool results the model reads grow by two ids per fastener result, moving token
measurements slightly. `finding_subject_key` (`findings.py:234-263`) gains those ids where they have
the entity-id shape. In the same commit (plan decision RF-2):

- **five check goldens regenerate**: `reviewer/tests/golden/test_golden/joint-bottoming.yml`,
  `joint-ok.yml`, `joint-unsupported.yml` (it pins `fastener.unsupported` with `inputs: [fst:1]`,
  `:3-7`, which `_unsupported` changes, `checks/fastener.py:700`), `thread-mismatch.yml` and
  `tool-envelope.yml`;
- **one check golden is added**, `joint-unknown-role`: a fictional package in
  `reviewer/tests/golden/fixtures/joint-unknown-role/` with one joint, one of whose instances has a
  hole type the map cannot classify, and no tolerance source (owner decision 39A): its
  `schema_version` is one the golden corpus allows, 1.0.0 to 1.3.0, and every source the joint
  map's resolver reads is a 1.4.0 or 1.5.0 member. The golden pins `hole.nominal_alignment`'s
  unknown-role result, naming every instance of the joint, and the stack check's "no tolerance
  source" skipped coverage row, as `alignment_case` returns them; `hole.position_stack`'s
  unknown-role result, the same `_unknown_role`, is pinned by the unit test
  (`test_joint_alignment.py`). No check golden pins a joint-map
  alignment result today (the joint map's regression file,
  `reviewer/tests/unit/test_joint_map_acceptance/big-assembly.yml`, pins the map, not check results), and Principle III asks a changed check for one;
- **the replay fixtures are regenerated only to assert they are byte-identical**, by
  `generate_fixtures.py` from the recordings (feature 008 SC-001), whose mapping file and three
  recording folders are present on the development machine (checked 2026-09-29, existence only):
  their recordings call no fastener rule and no joint map (their fastener and alignment tools are
  `list_fasteners` and `check_hole_alignment`), so 19A moves none of their bytes, and it takes no
  freeze. 19A's commit lands before origin marks' (section 5.2), whose regeneration then adds one
  `"origin_marks": 1` to each `session.json`, and D12 is the change that moves their text
  (`provenance.md` 6.2): the order is 19A, origin marks, D12 (plan decisions RF-27, RF-28).

The findings' text does not change.

## 11. Tests

Each fails before its behaviour exists (constitution III). Sessions are built as data unless a test
says it runs a tool; a finding a tool writes is built by that tool, never by hand, where the test
says "real" (research §2 d2-model-finding-unmatchable: no scoring test built a finding the way the
tool does).

`reviewer/tests/unit/test_benchmark_matching.py`:
1. check matching: US1-1's sibling `fastener.thread_match` on one of four keyed screws matches
   nothing, and the defect is missed; `rms.folders.present` does not match `rms.folders.ordered`;
   a family at depth; `fastener.*` against `fastener` and `fasteners.x` (refined: research section
   1, 37A) (US1-1, US1-2, SC-002);
2. targets: parts; drawing locations; provenance documents only with no parts and no locations; a
   component finding's provenance not read (US1-7, FR-003);
3. real: `record_drawing_finding` on a drawing document matches an entry keyed to that document and
   no part-keyed entry (US1-6);
4. references, one test per kind, on results the real checks return: a joint (resolved and
   unresolved), a recess, a hole pair, joint instances, a fit, a stack; each against a covered item
   it equals, a sibling item between the same parts, and, for fits, the bore against itself and a
   swapped pair; for stacks, an extra and a missing contributor (US5-16, FR-003);
5. a folded joint-map finding matches an entry through its first joint;
6. `answer-key.md`'s overlap test uses these primitives: its overlap table (section 5) evaluated
   through `benchmark/matching.py` alone.

`reviewer/tests/unit/test_scorecard.py` (rewritten; the prefix tests at `:74-105` go with the rule):
1. the 13A table, row by row, with a defect expected unresolved and one expected demonstrated
   (US1-3, US1-4, FR-002);
2. two findings on one defect in both orders; cleared alone, cleared beside a credit, cleared beside
   an unresolved match on a defect expected demonstrated (spec Edge Cases, US1-9, FR-005);
3. the section 3.1 invariants on every scorecard this file builds;
4. a correct condition contradicted by a demonstrated finding beside a known defect of its family on
   that part: one false alarm, one contradiction, the defect missed; confirmed by a pass; an
   unresolved match counts nothing (US1-8, FR-004);
5. a forbidden hit is one false alarm; with a contradicted condition, still one (US3-1, FR-017);
6. a withdrawn forbidden hit read from a stream the real regrade wrote (`scripted-answers.md`'s
   "All bought" fixture): counted, not a false alarm; a withdrawn finding matching no forbidden entry
   counts nothing; a missing stream reads `null` with its reason; a stream unreadable from line N
   reads `null` naming line N, and time to first finding is the first computed finding before it;
   both columns come from one pass through `replay_events`, a spy counting one call per package
   (US3-2, D14.4; RF-29);
7. tuned-on false alarms: a hit on a tuned-on entry, on a held-out one, on both, on nothing (D15);
8. an empty key: every demonstrated or suspected finding a false alarm, recall `null`; a key with
   only conditions: recall `null`, no false alarm from the null review (SC-001);
9. recall per producer and tag from item tags, the package flag ignored; the held-out count names
   every package's key (US1-10, FR-006, FR-032). A package whose session is absent is test 16's, in
   the robustness slice: until `package_outcome` exists a missing `session.json` stops `score_run`
   (`benchmark/scorecard.py:489`; plan decision RF-59);
10. a set flag that disagrees with its key is refused naming the package (US5-12);
11. a set naming a key-only key is refused (D7);
12. not assessed: a key with no forbidden entry, condition or expected coverage reads `null` in those
    columns with reasons, and the markdown says "not assessed", never 0 (US3-8, FR-021);
13. the summary line of `benchmark score` (section 7), pinned in `reviewer/tests/unit/test_cli.py`;
14. the scorecard validates against the amended `scorecard.schema.json` (`:359-370` today);
15. `key_sha256` names each key's raw-bytes digest; in `reviewer/tests/unit/test_benchmark_compare.py`,
    two runs of one study whose scorecards name different digests for one package's key are refused
    naming the package (INT-16);
16. with the robustness slice: a package whose outcome is an infrastructure failure is in
    `unscored_packages`, not in `per_package`, and its key's held-out items still count in
    `held_out_model_defects`; a behavioural stop is scored from its finalized session with
    `run_status` `behavioural` and its class; a run folder with no `run-status.json` reads
    `not_recorded`; a run whose every package failed scores with `per_package` empty (INT-9);
    `served_models` holds the kept attempt's distinct served ids, `[]` when none was reported; each
    `failed_attempts` and `unscored_packages` row carries its attempt's run-relative `folder`, which
    exists (RF-16, RF-17).

`reviewer/tests/unit/test_event_lines.py` (the one event-line reader, RF-29; the key-extensions
slice, each later caller adding its own row):
1. `replay_events` yields every event of a well-formed log, stops at the first line that is not JSON
   or not an `AgentEvent`, and calls `on_unreadable` with that line's 1-based number; without the
   hook it behaves as at `be01974`, and the pane's reconnect and remodel tests pass unchanged;
2. `chat.sessions.replay_events` is `agent.events.replay_events` (the re-export, not a copy);
3. every committed replay fixture's `events.jsonl` reads through it with no unreadable line;
4. a spy on it sees exactly one call per package from `score_run` (this slice), one per transcript
   from the report and one per `read_recording` (the report slice), and one per attempt from
   `attempt_facts` (the robustness slice), each row landing with its caller; and, from the report
   slice, where `recording._events` (`benchmark/recording.py:194-212`) goes, no other reader of
   `events.jsonl` exists under `benchmark/` (a structural test over `EVENTS_FILE_NAME`'s readers;
   plan decision RF-59), but `benchmark/streams.py`'s packing, which copies a stream's bytes and
   parses no event (the robustness slice; plan decision RF-83);
5. a packed stream reads as its plain form: `replay_events` over `events.jsonl.gz` yields the events
   it yields over the same bytes plain; a packed stream truncated mid-archive, and one whose bytes
   are corrupt, stop at the line being read and call `on_unreadable` with its number, as a malformed
   line does (28A; RF-83);
6. `event_stream(folder)` returns `events.jsonl` when it exists, else `events.jsonl.gz`, else the
   plain path, which reads as an empty stream; a folder holding both raises `ValueError` naming the
   folder and `swreview benchmark pack`; a spy sees `score_run` resolve each package's stream through
   it (RF-83). That a packed run scores to the same bytes is `provenance.md` 8's
   `test_a_packed_run_scores_as_before` (the robustness slice, with `benchmark pack`).

`reviewer/tests/unit/test_scoring_coverage.py`, through `goal_lines` on sessions built as data:
R-5 marked checked: one mismatch naming `interference`; the pre-run's skipped row and
finalization's unresolved row: none (US3-3); an item whose only row failed reads unresolved (US3-4);
no row: not reported, a mismatch; out of scope; a goal with a finding reads checked;
`interfaces.fit` read through the fits-and-stacks goal; a `coverage.prerun.fastener_joints` row read
by no goal (FR-018, D6); every `GoalReason` (`unresolved`, `skipped`, `failed`, `out_of_scope`,
`no_check`) reads as section 4's table says, through `goal_readings`, and `goal_lines`' output is
unchanged by the extraction (the report's own tests pass as they are; RF-23).

`reviewer/tests/unit/test_finding_origins.py`:
1. each of the eight values from a session built as data, including a cited step missing from the
   session (`unknown`) and a finding citing two steps (the later decides) (FR-007);
2. no record: every code finding but a carried one reads `unknown`, a model-written one `model`;
   the record with no marked step: `code_only_call` or `configured_check` by tool (US1-12);
3. S-5.4 structural, over every tool of `tools/registry.check_tools()` (`:120-134`) and the two
   offered on condition (`check_drawings`, `check_standards`): every tool of `CODE_ONLY_TOOLS` is in
   `prerun.prerun_tools()`, is `LIVE_INTERFERENCE_TOOL`, `DRAWINGS_TOOL` or `CHECK_TOOL`, or has no
   required parameter by signature; every other has a required parameter and is not a pre-run tool
   (RF-68); and the two
   argument-taking pre-run tools, `check_interference_group` and `bridge_interference`, are exactly
   the code-only tools with a required parameter, named in the test, so a check added to the
   pre-run, or given a required parameter, lands in the right set or fails here (RF-6, RF-38);
4. every finding the pre-run writes cites its own step (SP-3); with every lever off and no model
   call, every finding `start_review` writes is `setup`;
5. end to end, on `reviewer/tests/support/prerun.py`'s scripted checks-first review: every pre-run
   step is marked `prerun`, the model's scripted calls are unmarked, the session records
   `origin_marks: 1`, and the findings read `prerun`, `code_only_call` (a scripted `check_hygiene`)
   and `configured_check` (a scripted `check_hole_alignment` on `hole:1` and `hole:2`, the package's
   coaxial pair, which records its `hole.coaxiality` finding unresolved with no tolerance, as
   `tests/unit/test_runner_model_view.py:48` already scripts it; not `check_fit`, which records
   nothing on `prerun_package`, whose package holds no drawing sheet for `resolve_dimension`,
   `tools/checks_fit.py:58-61`) (research §4 cross-check);
6. a scripted "All bought": the restated steps are marked `regrade`, and a finding that survives the
   regrade reads `regrade` (US1-13);
7. a session loaded without the record and a step without a mark round-trip to their bytes;
   feature 001's session schema accepts both fields.

`reviewer/tests/unit/test_scoring_rules_version.py`:
1. `score_run` writes `SCORING_RULES_VERSION`;
2. compare refuses a byte-level scorecard written before this feature with the re-score line, not a
   validation error, and before any session or parity check (research §4 cross-check);
3. compare refuses a newer version;
4. an unknown field is refused naming the folder;
5. re-scoring such a folder writes the current version, compare accepts it, and its checks-first
   session reads `unknown` origins (US1-11).

**Existing tests this contract moves**, in the scorer slice (plan decision RF-49): every key a test
writes goes through one helper, `reviewer/tests/support/answer_keys.py` `write_key`, which builds
through `AnswerKey` (format 2, `D-<n>` ids, tags) and which `test_scorecard.py`, `test_cli.py`'s
`answer_keys` fixture (SR-23) and the two files below share. `reviewer/tests/unit/test_scorecard_usage.py`
(its `write_package`, `:121-199`, and its ten `score_run` calls, `:215-491`) and
`reviewer/tests/unit/test_carry_over_guards.py:759-803` are rewritten to format-2 keys, a support
package saved at each set entry's path (`tests/support/packages.build_package` and
`ir/loader.save_package`, since the loader refuses a key whose package is missing and not
key-only), and `held_out=False` over tuned-on items; what each asserts is unchanged.

`reviewer/tests/golden/test_golden_scorecards.py` (with the validation of FR-054):
1. the oracle and null goldens of every committed case, and SC-001 and SC-002 over them;
2. each probe's golden, and its difference from its base in exactly the columns it declares, by
   exactly the delta it declares for each (US3's Independent Test, FR-049); a probe planted to count
   its behaviour twice fails;
3. the structural tests of 9.3, and every `PackageScore` field either in the golden view or in
   `GOLDEN_EXCLUDED`; `test_golden_identity_never_moves` (every probe equals its base in
   `GOLDEN_IDENTITY`), and every view field outside it declared by some probe (RF-43);
4. section 9.4's checks, `goldens_unchanged` included (a declared row sharing the previous digest
   passes, one whose digest differs fails, a shared digest without the declaration fails) (US1-14,
   SC-013; RF-21).

19A (section 10), before the product change:
- `reviewer/tests/unit/test_checks_fastener.py`: each unresolved path of the four rules (bottoming's
  end condition and missing inputs, engagement's, thread match's two, head clearance's) and each
  resolved one leads `inputs` with the fastener and hole ids, for `check_fastener_joint` and
  `check_placed_screw` alike; `fastener.unsupported` names the hole (FR-061, US1-17);
- `reviewer/tests/unit/test_joint_alignment.py`: an unknown-role result names every instance of the
  joint in `inputs`, and its text names the unknown-role holes only, as today;
- US1-17: four screws in one plate, each joint's `fastener.bottoming` keyed on its own, one joint's
  thread depth missing: its unresolved finding flags that defect only, through the real joint check;
- the five check goldens regenerated and `joint-unknown-role` added (`reviewer/tests/golden/
  test_golden.py`'s `test_golden_case`); the replay fixtures regenerated byte-identical, and the
  replay tests (`reviewer/tests/unit/test_replay_findings.py`) passing on them;
- then origin marks' commit (section 5.2; RF-27): the replay fixtures regenerated, differing only by
  one `"origin_marks": 1` in each `session.json`, and `test_pane_fixture.py` and the replay tests
  passing unchanged.
