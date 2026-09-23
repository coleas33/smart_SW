# Contract: The Replay

Normative for `swreview benchmark replay`, `benchmark/recording.py`, `benchmark/replay.py`, the
`ReplayReport` model and the committed replay fixtures (FR-001 to FR-007, SC-001 to SC-005).
Amended 2026-09-23 by the owner's decision 3A - the fixtures follow the code - in sections 8, 9
and 10.

## 1. The command

```
swreview benchmark replay RUN_DIR
    [--pane-defaults | --no-pane-defaults]      # from User Story 3; default --pane-defaults
    [--lever NAME]...                           # adds a lever to the requested settings
    [--payload-slimming] [--history-pruning]    # from User Story 3
    [--prune-after N]                           # from User Story 3; N >= 1, requires pruning on
    [--standards-profile PATH]
    [--json]
```

| Exit | When |
|---|---|
| 0 | The replay ran and no recorded finding was lost |
| 1 | A refusal (one sentence on stderr, nothing on stdout), or at least one lost finding (after the whole report is printed) |
| 2 | A usage error: an unknown or refused lever (the `efficiency_from_levers` sentence), `--prune-after` below 1 or without pruning on |

The requested settings are resolved by the same `_review_settings` resolver `swreview review`
uses (`cli.md`): `pane_defaults(recorded provider)` when `--pane-defaults`, plus any explicit
switch. Before User Story 3 lands, the requested settings are the levers named by `--lever` and
nothing else. `--standards-profile` is passed to both passes' `start_review`; the fixtures use
`config/standards.example.yaml`, the profile the pilot ran (research R2.10).

*Landed as (T079).* `replay`, `replay_recording` and `replay_passes` take `requested:
tuple[EfficiencySettings, ModelViewSettings]` (`replay.Requested`), the pair `_review_settings`
returns. The recorded provider picks `pane_defaults(provider)`; a provider name the current code
does not know is read as `fake`, whose pane defaults are checks first and the pane's view.

The replay needs no key, makes no network call, constructs no provider SDK client and needs no
SOLIDWORKS (FR-002): both passes run `start_review` with `FakeProvider` in a
`TemporaryDirectory` holding a copy of `package.json`, with `bridge=False` and
`explain_findings=False`. **It writes nothing into `RUN_DIR`.**

## 2. Reading a recording

| Folder | Answer |
|---|---|
| no `session.json` | `run_folder_session`'s own sentence (and its benchmark-root sentence when a `<package_id>/session.json` sits below) |
| no `events.jsonl` | "`<RUN_DIR>` holds no events.jsonl: it is a check folder or was written before the event log, and a check has no provider rounds to replay" |
| an event log with no `usage` event | "`<RUN_DIR>/events.jsonl` records no usage event: no provider round was recorded, so there is nothing to price" |
| no `package.json` | "`<RUN_DIR>` holds no package.json: the replay re-runs the recorded calls against the package and cannot without it" |

Rounds are the `usage` events with the `tool.started` events that follow each. A `usage` after the
turn's `text.done` and before `turn.ended` is a **presentation** round, carried at its recorded
size (edge: a turn that ends with no text has its presentation round counted as a main round).
A turn preceded by `evidence.answered` events is an answer turn; consecutive ones form one batch
(`answer_evidence_batch`, from User Story 4). A follow-up's user text is sized from the recorded
growth (no event records the text). A stopped turn's dangling `tool.started` is not replayed.
Steps written before the first `usage` (a recorded pre-run) are not scripted. Each recorded
finding belongs to the step whose `tool.started`/`tool.finished` bracket its `finding` event falls
in.

## 3. Two passes and the call classes

**Pass A** (`as_recorded`) replays with the recording's own `session.efficiency` and
`session.model_view` (absent = off); **pass B** (`requested`) with the requested settings. Both
play the recorded rounds through `FakeProvider` `ScriptedRound`s. Every recorded model call is
classified from pass A, and pass B reuses the class:

| Class | When | Sized as |
|---|---|---|
| `reproduced` | same status and same `summarize_result` as recorded | the current code's result |
| `changed` | same status, different summary, no estimated call before it in the turn | the current code's result; listed with its reason |
| `estimated` | the tool is not offered offline or unknown to the current code; a status mismatch; or a divergence after an estimated call | section 4, rule 3 |
| `stored` (User Story 3) | would be estimated, but `RUN_DIR/tool-results/step-<n>.json` exists with the session's `session_id` | the stored payload as each pass's settings show it |
| `carried` | a presentation round | its recorded input, in every total |
| `answered_from_checks` (User Story 2) | pass B runs checks first and the pre-run already ran the call, so the guard answered | the guard's `already_run` answer |

*Reconciled with the code (T023).* "Same summary" compares finding and evidence-request ids
(`F-…`, `ER-…`) as ids rather than as numbers (`replay.same_summary`): a replay that cannot run
a recorded check skips that check's findings, so every later finding is numbered lower than it
was recorded, and on the big recording three hole-alignment results would otherwise read as
diverged. A summary cut at its 200-character limit is compared as far as both go. Which tool
was not offered offline is decided by name: a bridge tool needs the live bridge, a standards
tool needs `--standards-profile`, and a name no registry list holds is not known to the current
code; the reason says which. The fixture generator uses the same comparison.

*Reconciled with the code (T050).* `answered_from_checks` is recognised by the guard's own
answer in pass B (`status: "already_run"`), never by the tool's name, and its reason is "the
pre-run ran this call at step N". It is the class the report names and the class that decides
pass B's size and the finding rule, **whatever pass A's class was**: behind an estimated call
(the big fixture's three touching groups judged after the live call) the guard's answer is
still exactly what pass B sends, and the recorded findings of the step are still compared
against the requested session the pre-run wrote. Pass A keeps its own class for its own
sizing, so a round whose pass-A figure is an estimate stays flagged `estimated`. A call the
guard lets through keeps its pass-A class. `replay_passes(recording, scratch, ...)` plays both
passes into a folder the caller keeps (the acceptance tests read the requested session and its
opening message from it); `report_of(passes)` prices them; `replay_recording` does both over a
temporary folder.

*Reconciled with the code (T079).* A stored result is taken only when
`tool-results/step-<n>.json` parses, names the recording's `session_id`, the call's step, its
tool **and its arguments**, and carries a payload: a stale file from another review in a reused
folder, or one an edit broke (a rewritten event's arguments included), is ignored and the call
stays estimated. `stored` replaces `estimated` for any of the estimated reasons, which the
reason keeps ("…; sized from its stored result tool-results/step-N.json"). A stored call is
still one the replay could not run, so a later divergence in its turn is put down to it,
exactly as after an estimated call. Recordings written by `tests/support/replay` store every
step, so a test of the estimation rules removes the folder first (`without_stored_results`);
the committed fixtures, recorded before this feature, have none.

## 4. The accounting

```
input[t,k] = R0 + dP
           + (recorded output tokens of every earlier main round)
           + (recorded user-message growth before (t,k))
           + Σ over tool messages visible at (t,k) of ( T(tool_result_text(model_payload, compact=slimming)) + FRAMING_TOKENS )
```

1. `R0` is the recorded input of the first main round; `dP` is `T(system prompt + tool-schema JSON
   + opening message)` under the pass minus the same under pass A (0 for pass A).
2. `T` is `tokens.count_tokens` (`tokenizer.md`). `FRAMING_TOKENS = 12`, the per-result wrapper
   the provider bills, measured as recorded growth minus the replayed count (11 to 14, median 12,
   over 87 results of three runs).
3. An estimated call is sized from the recorded growth: the next main round's input, minus this
   round's input, minus this round's output, minus the other calls of the round (each with
   framing), minus framing; several estimated calls in one round share the rest equally. When the
   growth cannot be observed (the last round of a stopped, truncated or max-steps turn; a negative
   growth), the size is `T` of the recorded 200-character summary, flagged `lower_bound`.
4. "Visible" is decided by the adapters' own function: each round's tool messages are read from
   the scripted review's neutral history truncated at that round and passed through
   `prune_history(messages, N)` when the pass prunes (User Story 3), so stubs and ages equal what
   the adapters send.

   *Landed as (T079).* `PlayedRound.history` is that history, built in the adapters' shape as the
   script is played: the engineer's message the runner appends before each turn (and keeps when
   the turn does not return); one assistant message per round listing the calls it asked for;
   one tool message per call carrying `model_payload(result)` - the pass's own view when it
   slims; and, for a committed turn that did not end at its budget, the closing answer as an
   assistant message, which the recorded model's answer was whether or not the scripted text is
   empty. A stopped or failed turn adds only its engineer message. `request_messages(history,
   view)` is the request an adapter builds from it (`prune_history` with `finding_detail =
   payload_slimming`), and each result is counted as `T(tool_result_text(content, compact =
   payload_slimming)) + FRAMING_TOKENS`.

   A **stored** result is put in its tool message's place before pruning - the stored payload
   as the pass's settings show it (`tools.model_view.model_view` when slimming) with the stored
   status - and is then counted and pruned like a result the replay ran. An **estimated** result
   has no content: it is counted at its estimate (rule 3), whatever the view, until the
   adapters' rule would make it a stub - `pruning.prunable`, the three conditions that do not
   need the content (age, not an error by its **recorded** status, arguments known) - and from
   then on at the smaller of its estimate and the part of its stub the replay can know,
   `result_stub(tool, recorded arguments, {})`, without the counts and ids its payload would
   add. On the big fixture that is the one live call: its known stub is 103 tokens, its full
   stub (113 rows counted, 20 ids) would be about 211, so the requested figure is low by under
   3,000 tokens over the 25 rounds that carry the stub - where holding the 17k-token estimate in
   full for all 27 later rounds would have added about 424,000 tokens (measured before feature
   010's US4-US8 checks joined the pre-run: 1,155,567 against 731,592).
5. Output tokens are held at the recorded values; the replay prices input only.
6. A Gemini recording is counted over the same text and labelled `comparison: "shape"`.
7. *Reconciled with the code (T016, T023).* A turn that ended `stopped` or `error` keeps no
   history (the runner assigns none when a turn raises), so its outputs and results are in no
   later round; its engineer message is. A follow-up's words are the recorded growth
   (`RecordedTurn.user_tokens`); when that growth is not observable - the previous round asked
   for calls - they count as zero and the turn's rounds are flagged `lower_bound`.
   *Reconciled (T118, found by the drift rule):* that growth is measured from the last
   committed turn, so after a stopped or failed turn it already holds that turn's engineer
   message, which the runner keeps; a turn's words therefore replace what the turns since the
   last commit counted rather than add to it, and the stopped turn's question is counted once
   (`_Conversation`). No committed figure moved: neither the fixtures nor the recordings hold
   a turn after a stopped one. Before User
   Story 3 the prefix difference `dP` is counted over the system prompt, the tools' names,
   descriptions and canonical schemas, and the opening message, rendered the same way for both
   passes.

## 5. The finding comparison

Findings are compared as multisets of `finding_subject_key` (data-model section 4). A recorded
finding is **lost** when its step was `reproduced`, `changed` or `answered_from_checks` and the
requested pass's session does not hold its key; lost findings exit 1. A finding of an `estimated`
or `stored` step is **not replayable offline** and is listed with its step and reason, never
counted lost or kept. *Reconciled (T023):* a finding tied to no scripted step - a recorded
pre-run's, or one no event bracket holds - is compared as a reproduced step's is. A requested-pass finding with no recorded counterpart is **added** and
changes no exit code. The human output names every lost and every added finding by check and
subject.

*Added by feature 010 (T095):* a recorded `interference.static` finding whose group key (read
from its calculation's inputs) and configuration equal a contact the requested pass recorded
is **reclassified as contact**, listed with its step, the group key and the contact's id, and
never counted lost or not replayable: since feature 010 a touching group is a contact by design
(010 `contracts/contacts.md` section 6). This is decided before the step's class, because the
contact says what became of the finding even when its step was estimated. Each contact
reclassifies one recorded finding, so the comparison stays a multiset, and a reclassified
finding changes no exit code.

## 6. The regrouped estimate (from User Story 4)

Printed beside the strict figure whenever a rule applies, with its assumption: "the model does
not repeat a check the digest reported, and batches consecutive calls to one tool".

| Rule | Applies when | Does |
|---|---|---|
| R | the requested pass runs checks first | drops every recorded call classed `answered_from_checks` |
| M | the requested pass has `parallel_tool_calls` | merges each run of consecutive main rounds of one turn whose calls all name the same tool (none estimated, stored or carried) into one round holding those calls in recorded order |

A round left empty disappears. SC-003 is gated on this figure (research R2.43, R4).

*Landed as (T087).* The rules apply to pass B's script in the order R, then M, so two rounds of
one tool that a dropped check separated are consecutive for rule M (the model the estimate
assumes never made the call between them). A call is "estimated or stored" by its pass-A class;
a round that rule R only partly empties keeps its other calls and its whole output. The
regrouped script is played through the current code with the requested settings, like pass B,
into `scratch/regrouped` (`ReplayPasses.regrouped`: the rules, each turn's `RegroupedRound`s
with the recorded rounds they stand for, and the played review), and priced by the strict
figure's own accounting (one `_Conversation` walk for both): each regrouped round's output is
its recorded rounds' outputs together, a round rule R emptied is gone with its output, a call
the replay could not run keeps pass B's estimate or stored result under its new position, and
the closing round and every carried presentation round are priced as the strict figure prices
them - so when neither rule changes anything the estimate equals the strict figure. Every other
field of pass B's pricing carries over unchanged, its view and the tool array its stubs are
written against (lever 13, T114) included (*landed as*, review of `d805112..99269dd`; no
committed figure moved). `Regrouped`
is `{assumption, rules, rounds, total}`, `rounds` counting the regrouped main rounds and the
carried ones. The human output prints it on the line after the round counts: `regrouped
estimate (rule R, M): <total> over <rounds> rounds, assuming <assumption>`. A replay whose
requested settings meet neither condition plays no third pass and reports `regrouped: null`.

The recorded provider decides the default request, and the committed fixtures record `fake`
(their generator drove the scripted provider), whose pane runs checks first but not parallel
calls: `swreview benchmark replay <fixture>` therefore prints rule R alone, and `--lever
parallel_tool_calls` adds rule M - the request an OpenAI pane review makes, which is what the
recorded reviews were. The US4 acceptance prices the fixtures with `pane_defaults(openai)`.

## 7. The report

Human output, in order: the run, the provider, `tokens counted with o200k_base` and the
comparison kind; the two settings; one line per round (`turn`, `round`, `recorded`,
`as recorded`, `requested`, and `estimated`/`lower bound`/`carried`/`stored`/`answered from
checks` flags); the three totals and the difference; the count of estimated, lower-bound and
carried rounds; the regrouped estimate with its assumption, when present; then the findings -
recorded and replayed counts, every lost, added and not-replayable finding by check and subject
(and, from feature 010, the count of reclassified findings and each one with its contact).
*Landed as (T023):* after the round counts, one line per call that was not `reproduced`
(`step N tool: class - reason`), so every estimate and every change is named where it is
priced; `settings.*.model_view` is `null` until User Story 3 and `regrouped` `null` until User
Story 4. Before User Story 3 the command takes `RUN_DIR`, `--lever`, `--standards-profile` and
`--json`. *Landed as (T079):* `settings.*.model_view` is always the `ModelViewSettings` the pass
ran with (pass A: the recording's, `MODEL_VIEW_OFF` when it records none); each settings line
reads `as recorded: <levers>; model view off` or `requested: <levers>; model view payload
slimming, history pruning after N rounds`; a round holding a `stored` call is flagged `stored`.

`--json` prints exactly the `ReplayReport` model and nothing else:

```json
{
  "run_dir": "…", "provider": "openai", "tokenizer": "o200k_base", "comparison": "exact",
  "framing_tokens": 12,
  "settings": {"as_recorded": {"efficiency": {}, "model_view": null},
               "requested":   {"efficiency": {}, "model_view": {}}},
  "rounds": [{"turn": 0, "round": 0, "kind": "main", "recorded_input": 11006,
              "as_recorded_input": 11006, "requested_input": 13520,
              "estimated": false, "lower_bound": false,
              "calls": [{"step": 3, "tool": "check_rms_part", "class": "answered_from_checks",
                         "reason": "the pre-run ran this call at step 1"}]}],
  "totals": {"recorded": 0, "as_recorded": 0, "requested": 0, "difference": 0,
             "estimated_rounds": 0, "lower_bound_rounds": 0, "carried_rounds": 0},
  "regrouped": {"assumption": "…", "rules": ["R", "M"], "rounds": 0, "total": 0},
  "findings": {"recorded": 99, "replayed": 88, "lost": [], "added": [],
               "not_replayable": [{"check": "…", "subject": "…", "step": 12, "reason": "…"}],
               "reclassified": [{"check": "interference.static", "subject": "…", "step": 15,
                                 "group_key": "…", "contact_id": "C-001"}]}
}
```

## 8. The fixtures

`reviewer/tests/fixtures/replay/{big-assembly, small-assembly-a, small-assembly-b}/` each hold
`package.json`, `session.json` and `events.jsonl`, shaped like the recorded 830-02342 run and the
two 810-11249 runs, written once by `reviewer/tests/fixtures/replay/generate_fixtures.py` from a
recording on the machine that holds the dumps (`--recorded RUN_DIR --name NAME`). The generator
never contains a recorded string; it scrambles identifying strings through
`tests/support/scramble.FictionalMap` (first-seen order, length and character class kept, ids,
SOLIDWORKS type names, the generic feature vocabulary and property keys passed through), adds
the interference rows the live call found in FR-009's persisted shape, answers the one recorded
`bridge_interference` call with them through `tests/support/review_bridge.ScriptedReviewBridge`,
drives the current code through `tests/support/replay.record_scripted_review`, and refuses to
write unless the finding-key set equals the recording's, every result of 5k tokens or more is
within 5% of its recorded tokens, and no identifying token of the recording remains. It refreshes
the owner's denylist at `%LOCALAPPDATA%\SwReview\fixture-denylist.txt` outside the repository.
The recordings themselves never enter the repository (FR-007).

*Landed as (T018).* `--groups N` gives the live detection's group count when the model judged
fewer groups than it found (the big recording's count, 113, is recorded only in the model's own
prose); the fixture package persists the rows and the volume-unit gap together, as checks first
will. The generator runs from `reviewer/` and grades with the profile's path relative to it,
because the path is written into the standards findings and an absolute one would carry the
generating machine's folders. The package's own SOLIDWORKS type names are kept wherever they
are quoted (a gap listing skipped types). Paths and names are strict (the owner's review of
2026-09-23): every folder between the fictional root and the file is scrambled with no
allowlist; a file stem, a file name, a component's name and path and the design's name keep
only sizes (`M8-1.25X16`, `3MM`), one- or two-digit numbers and single characters; every word
of those fields, and every supplier code next to a catalogue number, is scrambled wherever else
it appears, so a component name and its file stem still agree (`scramble.strict_tokens`). The
recorded folder names go only to the owner's local denylist, which the hygiene test reads to
prove no fixture folder is named like one; the committed test also forbids a fixed list of
folder and supplier words (whole-word, case-insensitive in path values), after taking out the
reviewer's own sentences (`hole_alignment.EXCLUDED_EFFECTS` names "MMC" as a material
condition). A result is taken as reproduced only when its status
and summary match (`same_summary`) and its size sits within the framing noise of the recorded
growth; the generator's own leak check polices every replaced token of three characters or more
with a letter, and every replaced number of five digits or more.

The committed hygiene test checks every fixture file: document and vault paths under the
fictional root; no drive path outside it, no email, no http(s) URL, no copyright sign; none of
`830-02342`, `810-11249`, `810-11281`; and, when the denylist file exists, none of its lines (the
test says why it skipped that part when the file is absent).

*Amended 2026-09-23 (owner decision 3A; research R2.54, R2.56): the fixtures follow the code.*
When a change to what a tool returns, or to the system prompt or the checklist, is deliberate,
the three fixtures are regenerated, as part of that change, from `reviewer/`:

```
uv run python tests/fixtures/replay/generate_fixtures.py --recorded <dumps>\20260920-192014-830-02342 --name big-assembly --groups 113
uv run python tests/fixtures/replay/generate_fixtures.py --recorded <dumps>\20260920-191314-810-11249 --name small-assembly-a
uv run python tests/fixtures/replay/generate_fixtures.py --recorded <dumps>\20260920-190840-810-11249 --name small-assembly-b
```

(`<dumps>` is `%LOCALAPPDATA%\SwReview\handover\2026-09-20-gui\dumps`), and then the pane
fixture that reads `big-assembly` (feature 009, `tests/fixtures/pane/generate_pane_fixture.py
--write`). A fixture is never edited by hand; SC-001's 1% bar is kept against what the generator
writes, and every figure of section 9 that moves is re-measured and says why in its test.

The finding check is contact-aware. A recorded `interference.static` finding that a contact of
the fixture reclassifies - its group key and configuration, carried into the fixture's names
through the map the rows were built with (`fixture_group`), equal the contact's - is taken out of
the recorded side before the multisets are compared. The rule is the replay's own (section 5):
`benchmark/replay.judged_group` reads the finding's group from its calculation inputs,
`benchmark/replay.reclassifying_contacts` gives each recorded finding the contact that
reclassifies it, one contact to one finding in recorded order; the generator imports both and
copies neither. Every other self-check is unchanged: a recorded key still missing, or a new key,
refuses; so do a large result beyond 5%, a leaked token, a surviving property word and a
recorded folder name.

**Where the 3, 2 and 0 live** (settled 2026-09-23 as a consequence of decision 3A). The touching
groups of the three recordings are counted in three places, each pinned: the generator's
reclassification output (it prints 3, 2 and 0 reclassified as contacts on the three recordings),
the fixtures' recorded contacts (their sessions record 3, 2 and 0 groups as contacts, as the
current code does, `test_replay_fixtures.py`), and the replay reproducing those contacts exactly
(every pass with the recorded settings records the same contact groups). A replay of a
regenerated fixture therefore reclassifies 0, 0 and 0, under every requested setting (section
9). The replay's reclassification path (section 5) stays pinned where a recording made before
feature 010 is built on purpose: the scripted recordings of `test_replay_findings.py` (010 T094).
The rule that no recorded finding is lost or not replayable is unchanged, and absolute.

## 9. The acceptance each story cites

| Story | Acceptance on the fixtures |
|---|---|
| US1 | Pass A within 1% of the recorded input on every round of every fixture; the finding set exact - since feature 010, recorded = replayed + reclassified, with 3, 2 and 0 touching groups reclassified as contacts on `big-assembly`, `small-assembly-a` and `small-assembly-b` (on the fixtures before decision 3A; the amended row below states the invariant as it now reads); the big fixture: four estimated rounds - `bridge_interference`, and since feature 010 the three touching groups judged after it, whose contact results a replay cannot separate from the live call's effect - and one carried round; its recorded total 12.4M within 1% (SC-001) |
| US1 *amended* (2026-09-23, owner decision 3A; research R2.54, R2.56) | On the fixtures regenerated by the current code (section 8): pass A within 1% on every round of every fixture; the finding set exact, recorded = replayed, with 0, 0 and 0 reclassified - the 3, 2 and 0 touching groups live in the generator's reclassification output, the fixtures' recorded contacts and the replay reproducing those contacts exactly with the recorded settings (section 8), and the replay's reclassification path stays pinned on the scripted pre-010 recordings of `test_replay_findings.py`; the big fixture: one estimated round, `bridge_interference` (the three groups judged after it reproduce their recorded contacts), and one carried round; its recorded total 12.4M within 1% (SC-001). Under every requested setting of US2 to US4, no recorded finding lost or not replayable - an absolute rule, unchanged by decision 3A - and none reclassified; each fixture's recorded contacts among the requested pass's |
| US2 | Checks first alone (requested efficiency `prerun_checks=True`, model view off; on the command line `--lever prerun_checks`, or `--no-pane-defaults --lever prerun_checks` once US3 has landed): no recorded finding lost on any fixture; on the big fixture the requested total below pass A's, every one of the 113 groups judged, one interference finding per group (SC-006 offline); the recorded RMS and assembly calls classed `answered_from_checks` |
| US2 *landed as* (T049, T050, 2026-09-23; re-measured after the Phase 9 amendment, unchanged) | `--no-pane-defaults --lever prerun_checks --standards-profile ../config/standards.example.yaml` (before US3 made the pane request the default, `--lever prerun_checks` alone): `big-assembly` recorded 12,456,095, as recorded 12,455,282, requested 4,225,060 (-66.1%); `small-assembly-a` 1,619,376 / 1,619,532 / 1,236,667 (-23.6%); `small-assembly-b` 1,497,696 / 1,497,378 / 1,133,500 (-24.3%). No recorded finding lost and none not replayable on any fixture; 3, 2 and 0 reclassified as contacts on the fixtures before decision 3A (since, the 3, 2 and 0 are the fixtures' recorded contacts, replayed exactly, and none is reclassified (T121)); 62, 7 and 5 added (feature 010's checks in the pre-run: `check_joints`, `check_mass_material`, `check_hygiene`; measured after feature 010 US4-US8 landed). Every one of the 113 groups judged - since feature 010, one finding or one contact each; every recorded `check_rms_*` call `answered_from_checks`; the RMS verdict multiset equal to the recording's |
| US3 | `--pane-defaults` on the big fixture under 1,000,000 requested input tokens with no loss (SC-002); the session's findings identical with the model-view settings on and off (SC-007); every step of the requested pass stored under `tool-results/` (SC-008); every result older than the prune age a stub in every reconstructed request |
| US3 *landed as* (T078, T079, 2026-09-23; re-measured after the Phase 9 amendment) | The default request - `pane_defaults(fake)`: checks first, the tools it ran withheld (lever 13, since the Phase 9 amendment), payload slimming, history pruning after two rounds - with `--standards-profile ../config/standards.example.yaml`: `big-assembly` recorded 12,456,095, as recorded 12,455,282, requested **662,748 (-94.7%)**, and 618,244 (-95.0%) at `--prune-after 1`; `small-assembly-a` 1,619,376 / 1,619,532 / 457,686 (-71.7%), 444,040 (-72.6%) at 1; `small-assembly-b` 1,497,696 / 1,497,378 / 452,302 (-69.8%), 440,056 (-70.6%) at 1. Against checks first alone (US2's 4,225,060, 1,236,667 and 1,133,500) the view, the stubs and lever 13 take a further 84%, 63% and 60%. The view and the stubs alone, as US3 landed (lever 13 off: `--no-pane-defaults --lever prerun_checks --payload-slimming --history-pruning`): 740,472, 531,638 and 512,414, and 695,948, 517,966 and 500,142 at `--prune-after 1`, a further 82%, 57% and 55%. No recorded finding lost and none not replayable on any fixture, at either prune age; 3, 2 and 0 reclassified as contacts on the fixtures before decision 3A (since, the 3, 2 and 0 are the fixtures' recorded contacts, replayed exactly, and none is reclassified (T121)); 62, 7 and 5 added, as under checks first alone. The big fixture's requested session records the same findings and contacts with the view off (SC-007) and one stored result per step (SC-008); its four estimated rounds are the live call and the three touching groups judged after it, as under US1 (on the fixtures before decision 3A; since T121 one, `bridge_interference`: the three groups reproduce their recorded contacts, as under US1 amended) |
| US4 | The regrouped estimate under 300,000 for each small fixture, with the strict figure below the recorded total (SC-003, amended); the big fixture's follow-up round under 30,000 (SC-004); three answers in one batch replay as one resumed turn (SC-005, scripted) |
| US4 *landed as* (T086, T087, 2026-09-23; re-measured after the Phase 9 amendment) | `pane_defaults(openai)` - checks first, the tools it ran withheld (lever 13), parallel calls, payload slimming, history pruning after two rounds - with `--standards-profile ../config/standards.example.yaml` (on the command line `--lever parallel_tool_calls` on a fixture): regrouped estimate, rules R and M, `small-assembly-a` **244,167** over 21 rounds (strict 457,686 over 39, recorded 1,619,376), `small-assembly-b` **243,134** over 20 rounds (strict 452,302 over 37, recorded 1,497,696), `big-assembly` 276,620 over 16 rounds (strict 662,748 over 41); at `--prune-after 1` 231,020, 231,110 and 233,323. The margin under 300,000 is 18.6% and 19.0%. As US4 landed (lever 13 off: `--no-pane-defaults --lever prerun_checks --lever parallel_tool_calls --payload-slimming --history-pruning`): 283,163, 274,957 and 305,864 (margins 5.6% and 8.3%), and 269,998, 262,915 and 262,555 at `--prune-after 1`. With the fixtures' own `pane_defaults(fake)` (rule R alone) the regrouped estimates are 380,647, 387,998 and 486,094 (443,019, 441,570 and 544,558 with lever 13 off). The big fixture's follow-up round (turn 1, round 0): **22,534** requested against 407,399 recorded (22,073 at `--prune-after 1`; 24,480 and 24,013 with lever 13 off). No recorded finding lost on any fixture; 3, 2 and 0 reclassified on the fixtures before decision 3A (since, the 3, 2 and 0 are the fixtures' recorded contacts, replayed exactly, and none is reclassified (T121)); 62, 7 and 5 added, as under US3. A two-answer batch replays through `answer_evidence_batch` as one resumed turn in both passes (scripted) |
| US5 | Every step's `result_tokens` in the requested pass's session equals the replay's count of that call's full payload (one tokenizer, one serialization) |
| US1 to US4 *re-measured* (T121, 2026-09-23, decision 3A: the fixtures regenerated by the code that adds feature 010's two checklist items, T098-T099 and T108; *landed as*: measured again on main after the six commits were cherry-picked onto it and 010 T108's bucket amendment, every figure the same; and again after the three fixtures were regenerated on main, where only their finding events' titles moved, every figure the same) | All with `--standards-profile ../config/standards.example.yaml`; the worst as-recorded round 0.005%, 0.017% and 0.028% from its recorded input. `big-assembly` recorded 12,411,209, as recorded 12,411,080; pane defaults **663,902 (-94.7%)**, 619,092 (-95.0%) at `--prune-after 1`; `--no-pane-defaults --lever prerun_checks` 4,232,500 (-65.9%); the view and the stubs without lever 13 741,388 (696,546 at `--prune-after 1`). `small-assembly-a` 1,598,717 / 1,598,817; 459,000 (-71.3%), 444,881 (-72.2%); 1,244,479 (-22.2%); 532,886 (518,737). `small-assembly-b` 1,505,494 / 1,505,562; 453,564 (-69.9%), 440,841 (-70.7%); 1,141,684 (-24.2%); 513,676 (500,927). The OpenAI pane (`--lever parallel_tool_calls`), rules R and M: **245,289** over 21 rounds, **244,277** over 20 and 277,361 over 16 (231,665, 231,776 and 233,746 at `--prune-after 1`), margins under 300,000 of 18.2% and 18.6% (without lever 13: 284,285, 276,100 and 306,605); the fixtures' own pane, rule R alone: 381,853, 389,232 and 486,940. The big fixture's follow-up round: **22,719** requested against 405,280 recorded (22,099 at `--prune-after 1`, 24,653 without lever 13 and 24,027 without it at `--prune-after 1`). Every run: pass A within 1%, no recorded finding lost, none not replayable (absolute), 0, 0 and 0 reclassified; 62, 7 and 5 added; the 3, 2 and 0 are the generator's reclassification output and the fixtures' recorded contacts, replayed with the recorded settings exactly and held among every requested pass's. Against the figures above: the recorded totals move by -44,886, -20,659 and +7,798 - on the big fixture each touching group's result is now the current code's contact, 779, 893 and 794 tokens smaller than the finding recorded, each of the two `get_review_checklist` answers is 185 tokens larger with the two new items, and the live call's result 23 smaller, each carried by every later round - and the requested totals rise by 1,154, 1,314 and 1,262 with the pane defaults, the two items in the system prompt and in `get_review_checklist`'s answers |

## 10. Real recordings

`reviewer/tests/integration/test_replay_recorded_runs.py` (skipped when
`%LOCALAPPDATA%\SwReview\handover\2026-09-20-gui\dumps` is absent; *landed without* the
`integration` marker, which `tests/conftest.py` skips whole when no native evidence package is
present - as it is not on the machine holding the recordings) checks pass A within 1% on every
round of the three recorded reviews (observed at most 0.023%) and that replayed plus
not-replayable findings equal the recorded key set (830: 88 + 11 = 99).

*Amended 2026-09-23 (owner decision 3A; research R2.55): the recordings are held to their
drift.* The recordings can never be regenerated and the code they are replayed against changes
on purpose, so their rounds are no longer held to 1% of the bill. The finding checks stay. What
the test proves about the tokens is that every token by which pass A differs from the bill is a
change in a result the round carries.

**The terms.** The replay runs the recording as recorded - both passes with the recording's own
settings, no bridge and no standards profile. For a recorded main round `r` that asked for
calls and whose growth is observable (section 4, rule 3):

```
size_A(call) = T(tool_result_text(payload))   the current code's result, for a call pass A ran
                                               (class reproduced, changed or answered_from_checks)
             = its estimate                    for a call pass A could not run (class estimated:
                                               estimated_sizes over the round, the calls it ran
                                               known - the rest of the growth, or the summary's
                                               tokens as a lower bound)
change(r)    = Σ over r's calls of (size_A(call) + FRAMING_TOKENS) − growth(r)
```

`growth(r) − FRAMING_TOKENS × |calls of r|` is the size of `r`'s results as recorded, so
`change(r)` is the size change of `r`'s results between the recording and the current code. It
is measured against a bill that framed each result in 11 to 14 tokens rather than 12 (research
R2.5): a result the current code returns unchanged shows -2 to +1, and a changed one its own
growth within `FRAMING_NOISE`, 3 tokens a result (the generator's constant, section 8).
`size_A` is counted by the rule's own code from the played call, never read off the replay's
pricing.

**The rule.** For every round `q` of the recording:

```
drift(q)   = as_recorded_input(q) − recorded_input(q)
residual(q) = drift(q) − Σ over carried(q) of change(r) = 0
```

`carried(q)` is every recorded main round with calls whose results `q`'s recorded request
carried, read from the recording alone and never from the replay's history: the earlier rounds
of `q`'s turn, and the rounds of every earlier turn that committed (not `stopped` or `error`,
rule 7). A presentation round carries nothing of its own and is priced at its recorded size, so
its drift is zero. A round the replay flags lower bound is outside the rule - a follow-up whose
words the log does not show, or a round holding a call sized from its summary, has no recorded
size to compare with - and so is a round that carries one whose growth is not observable; each
is listed apart, with no change, so the test can say how many there are (none on the three
recordings). The rule is written for a recording made with every lever and the model view
off and storing no results - the three recorded reviews - replayed with those settings: a pruned
request's growth can be negative and a stub is not its result's size, so anything else is
refused, naming what.

**Why the residual is zero, not small.** Both sides frame each result with the same 12 tokens
and take the first round's input, every output and the engineer's words from the bill, so the
identity holds to the token whenever the replay rebuilds each request right: which results it
carried, which turn committed, which round was presentation, which call was estimated and how.
A deliberate change to what a tool returns moves `change(r)`, never the residual; a replay
defect moves the residual. The framing noise lives inside `change(r)`: each round's drift equals
the size change of the results it carries, within `FRAMING_NOISE` a carried result.

**Where it lives** (T117-T118): `reviewer/tests/support/drift.py` computes the rule
(`round_drifts(passes, report)`: one `RoundDrift` per round with its drift, its carried change -
`None` outside the rule - and its residual); `reviewer/tests/unit/test_replay_drift.py` pins it
on scripted recordings that always run; the integration test asserts a zero residual on every
round of the three recordings and that the rule covers every main round of each. Measured at
`d47a91f`, before feature 010's checklist items: residual zero everywhere; every carried round's
change between -2 and +1; drift at most 8 tokens.
