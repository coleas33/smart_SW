# Contract: The Replay

Normative for `swreview benchmark replay`, `benchmark/recording.py`, `benchmark/replay.py`, the
`ReplayReport` model and the committed replay fixtures (FR-001 to FR-007, SC-001 to SC-005).

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
5. Output tokens are held at the recorded values; the replay prices input only.
6. A Gemini recording is counted over the same text and labelled `comparison: "shape"`.
7. *Reconciled with the code (T016, T023).* A turn that ended `stopped` or `error` keeps no
   history (the runner assigns none when a turn raises), so its outputs and results are in no
   later round; its engineer message is. A follow-up's words are the recorded growth
   (`RecordedTurn.user_tokens`); when that growth is not observable - the previous round asked
   for calls - they count as zero and the turn's rounds are flagged `lower_bound`. Before User
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
`--json`.

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

## 9. The acceptance each story cites

| Story | Acceptance on the fixtures |
|---|---|
| US1 | Pass A within 1% of the recorded input on every round of every fixture; the finding set exact - since feature 010, recorded = replayed + reclassified, with 3, 2 and 0 touching groups reclassified as contacts on `big-assembly`, `small-assembly-a` and `small-assembly-b`; the big fixture: four estimated rounds - `bridge_interference`, and since feature 010 the three touching groups judged after it, whose contact results a replay cannot separate from the live call's effect - and one carried round; its recorded total 12.4M within 1% (SC-001) |
| US2 | Checks first alone (requested efficiency `prerun_checks=True`, model view off; on the command line `--lever prerun_checks`, or `--no-pane-defaults --lever prerun_checks` once US3 has landed): no recorded finding lost on any fixture; on the big fixture the requested total below pass A's, every one of the 113 groups judged, one interference finding per group (SC-006 offline); the recorded RMS and assembly calls classed `answered_from_checks` |
| US2 *landed as* (T049, T050, 2026-09-23) | `--lever prerun_checks --standards-profile ../config/standards.example.yaml`: `big-assembly` recorded 12,456,095, as recorded 12,456,346, requested 4,216,180 (-66.2%); `small-assembly-a` 1,619,376 / 1,619,476 / 1,236,021 (-23.7%); `small-assembly-b` 1,497,696 / 1,497,774 / 1,132,636 (-24.4%). No recorded finding lost and none not replayable on any fixture; 3, 2 and 0 reclassified as contacts; 9, 1 and 0 added (feature 010's `hole.nominal_alignment` from the pre-run's `check_joints`). Every one of the 113 groups judged - since feature 010, one finding or one contact each; every recorded `check_rms_*` call `answered_from_checks`; the RMS verdict multiset equal to the recording's |
| US3 | `--pane-defaults` on the big fixture under 1,000,000 requested input tokens with no loss (SC-002); the session's findings identical with the model-view settings on and off (SC-007); every step of the requested pass stored under `tool-results/` (SC-008); every result older than the prune age a stub in every reconstructed request |
| US4 | The regrouped estimate under 300,000 for each small fixture, with the strict figure below the recorded total (SC-003, amended); the big fixture's follow-up round under 30,000 (SC-004); three answers in one batch replay as one resumed turn (SC-005, scripted) |
| US5 | Every step's `result_tokens` in the requested pass's session equals the replay's count of that call's full payload (one tokenizer, one serialization) |

## 10. Real recordings

`reviewer/tests/integration/test_replay_recorded_runs.py` (skipped when
`%LOCALAPPDATA%\SwReview\handover\2026-09-20-gui\dumps` is absent; *landed without* the
`integration` marker, which `tests/conftest.py` skips whole when no native evidence package is
present - as it is not on the machine holding the recordings) checks pass A within 1% on every
round of the three recorded reviews (observed at most 0.023%) and that replayed plus
not-replayable findings equal the recorded key set (830: 88 + 11 = 99).
