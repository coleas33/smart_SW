# Contract: The Replay

*Amended 2026-09-26 by feature 013 (`specs/013-engineer-first-review/`), landed for User Stories 1 to 6 (013 T042, T058, T069, T095, T115, T124; section 9's rows "Feature 013 US1" to "Feature 013 US2") the follow-ups (013 T158, the row "Feature 013 follow-ups") and User Story 7 (013 T134, the row "Feature 013 US7"; its question T134-Q1 answered by a default taken 2026-09-27, section 5's tree-reading clause, built by 013 T145-T146; its question T134-Q2, the Standards sketch check's findings, answered by a default taken 2026-09-27, section 5's clause read for every check that reads the tree):* every change of feature 013 that moves what the model reads passes the replay gate and records a re-measured section 9 row; see 013 `contracts/tokens.md` section 5.

Normative for `swreview benchmark replay`, `benchmark/recording.py`, `benchmark/replay.py`, the
`ReplayReport` model and the committed replay fixtures (FR-001 to FR-007, SC-001 to SC-005).
Amended 2026-09-23 by the owner's decision 3A - the fixtures follow the code - in sections 8, 9
and 10. Amended 2026-09-25 by the owner's decision 23A - a recorded RMS finding the type table
narrowed - in sections 5, 7, 8 and 10. Amended 2026-09-27 by feature 013's default for T134-Q1
- a recorded RMS finding the tree reading narrowed - in sections 5, 7 and 8, and by its
default for T134-Q2 - the Standards sketch check read by the same clause - in sections 5 and 8.

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

*Amended 2026-09-25 (owner decision 23A; research R2.58): a finding the type table narrowed.* A
recorded `rms.*` finding is **narrowed** exactly when, after removing each drawing location whose
`(scope, persist_ref)` names only rows the current type table does not count as content, its key
equals the key of a finding in the requested pass that nothing else matched. Each term is
deliberate:

- *Scope* is the location's `document_id`, which for an RMS subject is the subject row's
  `persist_ref_scope` (a rule's finding carries one `SourceRef` per subject). The rows are the
  feature rows of the recording's own `package.json` carrying that `persist_ref_scope` and
  `persist_ref`; *content* is `RmsTypeTable.is_content` under the type table the current code
  ships.
- *Only*, because real packages share persistent references between system folders (on the three
  recordings up to nine system folder rows carry one reference). A location stays when any row
  its reference names is content, when its reference names no feature row at all (a mate, a
  component) and when it carries no reference.
- *Nothing else matched* is the added side of the comparison above: the requested pass's findings
  no recorded key equals. The matching is one-to-one, in recorded order: each narrowed key takes
  one such finding, so a second recorded finding narrowing onto the same current finding stays
  lost.
- Only a finding that would otherwise be lost is narrowed: one whose step was `reproduced`,
  `changed` or `answered_from_checks`, or that no scripted step holds, and that no requested-pass
  finding matches exactly (of several recorded findings with one key, the later ones in recorded
  order). It is decided after reclassification and the step's class. A finding still unmatched
  after narrowing stays **lost**, and a finding of another family is never narrowed.

A narrowed finding is neither lost nor added and changes no exit code; it is listed with its step
and the number of locations removed, like a reclassified finding (section 7). The rule is written
once, `benchmark/replay.compare_finding_keys` (with `narrowed_key`, the locations a finding loses,
and `not_content_locations`, the references that name only rows that are not content), and the
fixture generator imports it (section 8). *Why:* feature 003's decision 20A moves the eleven
system types of the real 2024 SP5 dumps into `tolerated_loose`, so the part check stops naming
those rows as loose subjects. On the three recordings 20, 2 and 1
`rms.grouping.all_features_in_a_group` findings keep their part and configuration and lose only
those subjects, and because `finding_subject_key` holds one drawing location per subject, each
read as a recorded finding lost and a new one added (003 T092).

*Amended 2026-09-25 on review (T128): what "its key equals" can see.* The key is
`finding_subject_key` exactly, and a key's drawing location carries no persistent reference
(data-model section 4, research R2.8). An RMS subject's location is its scope and its reference
alone, so after narrowing the remaining locations compare as a count per scope. A finding that
also lost or gained a content subject - the count in its scope moved - or moved its
configuration, components or entity inputs, is lost. One whose remaining content subject was
swapped for another in the same scope, at the same count, narrows: exactly as the exact
comparison above keeps a recorded finding whose one subject was swapped for another. Narrowing is
never stricter or looser about subjects than the key every other outcome is decided by.
`test_replay_narrowed.py` pins both. Whether narrowing should demand more - the remaining
locations' references equal to those of the current finding it takes - is the owner's question,
T128, not decided. On the three recordings every narrowed finding's current finding carries the
same references (20, 2 and 1 of 20, 2 and 1), so no figure depends on the answer.

*Amended 2026-09-25 (owner decision 25A; T128 decided): exact references.* This replaces the
paragraph above. A key's drawing location is `(document_id, sheet, view, annotation, page,
persist_ref)` (data-model section 4, research R2.8), so both comparisons hold each location's
exact reference:

- The exact comparison: a recorded finding whose subject was swapped for another - one location
  naming another reference, in the same scope, at the same count - is **lost**, and the
  requested pass's finding is **added**; the exit is 1.
- Narrowing: the remaining locations must be exactly the current finding's, reference by
  reference. A finding that lost only system subjects and also had a content subject swapped is
  lost, never narrowed. Narrowing stays exactly as strict about subjects as the exact comparison,
  now both by reference. *Corrected 2026-09-25 on review (T129):* about the locations that
  remain; the locations narrowing removes are compared with nothing (below).
- A key's locations are a multiset: the same locations in another order are the same finding, and
  a reference two locations name - real packages list one sketch twice, both rows carrying its
  reference - counts twice, so a recorded finding naming it once more or less than the current
  finding is lost.
- A location without a reference, and a finding with no location at all, are keyed as before.
- A reference several rows share names all of them, so which of them a location meant is not
  compared (R2.8 says where the recordings have such rows).

The references are safe to compare because the replay plays the recording's own package and
arguments, never a re-dump, and the generator carries each recorded reference into the fixture's
through the function that scrambled the package's (section 8; R2.8, kind by kind). Measured before
the code with the tightened key: the three recordings replayed as recorded lose none and narrow
20, 2 and 1, 106, 10 and 5 locations removed, as before; the three fixtures lose and narrow none.
`test_finding_subject_key.py`, `test_replay_narrowed.py` and `test_replay_generator_narrowed.py`
pin it.

*Amended 2026-09-25 on review of decision 25A (T129): a carried finding, and what narrowing does
not compare.*

- **A carried finding.** A finding lever 11a carried (`Finding.carried_over_from` set) keeps the
  drawing locations of the session it was carried from, and carry-over decides "unchanged" from a
  `feature_tree` fingerprint that hashes no reference (`exceptions._feature_row`), so its
  references can be an earlier dump's, which the recording's dump may have re-encoded: the one
  kind whose references are not the recording's own (R2.8). It is compared by reference first and
  narrowed like any other; still unmatched, it takes one requested-pass finding nothing else
  matched whose key equals its own with every reference left out on both sides - the comparison
  every finding had before decision 25A, its subjects counted per scope - one to one in recorded
  order, after every narrowing. It is then kept: neither lost nor added, nor listed. Once its
  references differ, a re-encoded reference and a swapped subject cannot be told apart, so
  neither is seen; a subject gained or lost in a scope, or a moved configuration or component,
  still is. `benchmark/replay.compare_finding_keys` holds the rule, so the generator applies it
  through `scrambled_key` too. Two limits stay on the safe side, lost and never slipped: the
  replay plays no previous session, so a carried finding that no requested pass computes again
  (checks first off) is lost, as it was before decision 25A; and a carried finding whose
  reference was re-encoded and which also lost a subject the table stopped counting is lost,
  because narrowing reads references in the recording's package. None of the three fixtures and
  none of the three recordings holds a carried finding. `test_replay_carried.py` pins it.
- **What narrowing does not compare.** Narrowing removes each location whose `(scope,
  persist_ref)` names only rows the current table does not count as content, whichever rows they
  are - a system row the table newly tolerates, one no table counts, a folder, an end tag, a
  default-named row - and `not_content_locations` reads every document's rows, so a location
  scoped to another document is removed on the same terms. The removed locations are compared
  with nothing: a recorded finding whose removed subject is another row that is not content
  narrows exactly as one whose removed subject is the row the table change took away. The
  remaining locations are compared exactly, reference by reference. `test_replay_narrowed.py` and
  `test_replay_generator_narrowed.py` pin both. Whether narrowing should demand more of a removed
  location is the owner's question (T129, research R5); on the three recordings every location it
  can remove names only rows of `tolerated_loose` types and lies in the scope of a location that
  remains, so no figure depends on the answer.

*Amended 2026-09-27 (feature 013 T134-Q1; default taken 2026-09-27, the owner may revise; 013
research R2.42, research R2.59; 013 T145-T146): a finding the tree reading narrowed.* Feature 013
T133 reads a part's tree the way feature 004's planner does, through
`checks/feature_nodes.tree_nodes`: an absorbed sketch the dump lists at depth 0 and again under
the feature consuming it, with one persistent reference, is its depth-0 row alone (the **second
listing** is merged into it), and a row listed only under the feature that owns it - the Hole
Wizard's profile sketch - is **carried** by its owner and holds no position of its own. A recorded
`rms.*` finding that named such rows keeps its part, configuration, components, inputs and
remaining subjects, and loses only those. So narrowing also reads the recording's own package
through the reading, one document at a time, under the table the current code ships, and a
location **may** be removed - it is removable - when:

- its `(scope, persist_ref)` names only rows the reading carries, merges as a second listing, or
  the table does not count as content: every occurrence of it may go - the type table's "only"
  above, with the reading's two shapes beside it. A reference any row the reading keeps as a
  position, and the table counts, also carries is not removable wholesale;
- it names a depth-0 row the reading keeps together with the second listing(s) merged into it:
  its occurrences beyond the number of rows the reading keeps there may go, at most one per second
  listing - the second listing's own occurrence, never the depth-0 row's. A recorded finding that
  named the pair twice may be de-duplicated to once; one that named it once keeps it; one whose
  current finding no longer names it at all is lost - the depth-0 row is a real position, and the
  reading never drops it;
- a location with no reference is never removable.

*May*, for both clauses: the recorded finding is narrowed onto a requested-pass finding nothing
else matched, with its check, components, entity inputs and configuration, whose locations lie
between the recorded finding's and the lowest it can narrow to - every removable occurrence
removed (`narrowed_key`) - as multisets: the recorded finding less some of its removable
locations, and nothing else. Of several such findings it takes the one keeping the most
locations, the first in the requested pass's order among equals; the count listed is the
locations it lost. A rule that still names a removable row keeps it: since T133 the sketch rules
grade a carried sketch as its owner's, and `rms.sketches.one_sketch_per_feature` still names rows
the table does not count (the hazard research R5 recorded for T129), so on the big recording two
of its findings would stay lost if every removable location had to go. For a recording decision
23A's clause alone narrows, the lowest key is the one the paragraphs above compare, and a current
finding that dropped every removable row - every recording and fixture so far - narrows as it
did.

Everything else is exactly as above: the family (`rms.*`; a `standards.*` finding is never
narrowed, although the Standards sketch check reads the same tree since T133), the one-to-one
matching in recorded order onto a finding nothing else matched, the remaining locations compared
reference by reference (decision 25A), the carried-finding comparison (T129), and the listing
with the locations removed, both clauses counted together. A package with neither shape folds
nothing. The rule is still written once: `benchmark/replay.folded_locations(package, table)`
gives each location the reading folds its `FoldedLocation` - the rows it names that the reading
keeps as a position and the table counts (`positions`) and its second listings (`listings`) -
beside `not_content_locations`; `narrowed_key(finding, not_content, folded=...)` gives the lowest
key, and `compare_finding_keys` reads both, only when an `rms.*` finding is unmatched, and narrows
onto a finding between (`_narrowed_onto`); the generator reuses it unchanged (section 8).

*Why, and measured.* On the three recordings with T133 applied (2026-09-27, a scratch copy of
`main` with 013 T132-T133's source; the recordings replayed as recorded), the strict comparison
loses 25, 3 and 2 `rms.*` findings - 19, 2 and 1 `rms.grouping.all_features_in_a_group`, 3, 1 and
1 `rms.sketches.fully_defined`, 3, 0 and 0 `rms.sketches.one_sketch_per_feature` - and each comes
back as one added finding on the same part, configuration, components and inputs, whose locations
are a sub-multiset of the recorded ones; every location dropped names only carried rows the table
does not count (101, 10 and 5 occurrences), only carried content rows (29, 4 and 4), or one depth-0
row and its one second listing, recorded twice and named once (148, 15 and 12), never both
occurrences dropped. With this rule the three replay none lost and none added, with 26, 3 and 2
findings narrowed (20, 2 and 1 grouping, 3, 1 and 1 fully defined, 3, 0 and 0 one sketch per
feature) and 283, 29 and 21 locations removed, and a zero residual on every round (section 10's
drift rule). `test_replay_narrowed_tree.py` pins the rule; `test_replay_narrowed.py` and
`test_replay_generator_narrowed.py` are unchanged but for the summary line's words (section 7).

*Amended 2026-09-27 (feature 013 T134-Q2; default taken 2026-09-27, the owner may revise; 013
research R2.47, research R2.60): every check that reads the tree.* The tree-reading clause above
applies to every check that reads the shared tree reading: the `rms.*` rules and
`standards.part.sketches_fully_defined`, which 013 T133 moves onto the same reading, named
explicitly by its check id - never the rest of `standards.*`, whose checks read the rows as dumped.
So the family sentence above reads, since this default: a `standards.*` finding other than
`standards.part.sketches_fully_defined` is never narrowed. For the Standards sketch check it is the
tree-reading clause alone:

- a location is removable only when it names a row the reading merges as a second listing or
  carries as a sub-feature (`folded_locations`): every occurrence of one naming no row the reading
  keeps as a position the table counts, and of a merged pair the occurrences beyond the rows the
  reading keeps there, at most one per second listing - the depth-0 row's occurrence never;
- decision 23A's clause (`not_content_locations`) never removes one of its locations: the type table
  decides what the RMS rules count as a subject, not what a Standards check names.

Everything else is as for `rms.*`: *may*; one to one in recorded order onto a finding nothing else
matched, whose locations lie between the recorded finding's and the lowest key; the remaining
locations compared reference by reference (decision 25A); the carried-finding comparison (T129);
listed as narrowed with the locations removed, in the same count. A sketch the current finding no
longer names at all is lost, and so is a remaining sketch subject swapped or dropped. The rule is
still written once: `narrowed_key` holds the family test - the `rms.*` prefix, and
`TREE_READING_STANDARDS_CHECKS` by name - and `compare_finding_keys` reads the recorded package when
a finding of either family is unmatched; the generator reuses both unchanged (section 8). *Why:* with
013 T133 the fixture generator loses 3, 1 and 1 `standards.part.sketches_fully_defined` findings on
the three recordings, each exactly one occurrence of a merged pair - the shape the clause narrows
for `rms.*`; the real recordings' replay runs with no standards profile, so it cannot see them.
`test_replay_narrowed_tree.py` pins it. *Landed (013 T134, 2026-09-27):* with T132-T133 on `main`
the generator narrows 29, 4 and 3 recorded findings - 26, 3 and 2 `rms.*` and 3, 1 and 1 Standards
sketch findings - loses none, and writes the three fixtures (section 9, row "Feature 013 US7").

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
*Amended 2026-09-25 (owner decision 23A):* the findings summary line ends `…, N reclassified as
contacts, M narrowed by the type table`, and after the reclassified lines each narrowed finding
has one, `narrowed: <check> - <subject> (<k> locations removed)` (`1 location removed`), its
subject the recorded finding's, as every other list's is. `findings.narrowed` is always present,
empty when nothing narrowed. *Amended 2026-09-27 (feature 013 T146):* the line ends `…, M narrowed by
the type table or the tree reading`, one count for both clauses of section 5, and a narrowed
finding's line counts every location either clause removed. *Amended 2026-09-25 (owner
decision 25A):* a subject prints each
location as `at <document_id>`, then `sheet`, `view`, `annotation`, `page` and `persist_ref`, each
with its value where it has one, so the lost line and the added line of a swapped subject differ
in the reference, as the findings do (section 5).

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
                                 "group_key": "…", "contact_id": "C-001"}],
               "narrowed": [{"check": "rms.grouping.all_features_in_a_group", "subject": "…",
                             "step": 4, "removed_locations": 5}]}
}
```

## 8. The fixtures

`reviewer/tests/fixtures/replay/{big-assembly, small-assembly-a, small-assembly-b}/` each hold
`package.json`, `session.json` and `events.jsonl`, shaped like the big assembly's recorded run
and the small assembly's two, written once by `reviewer/tests/fixtures/replay/generate_fixtures.py`
from a recording on the machine that holds the dumps (`--recorded RUN_DIR --name NAME`). The generator
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
fictional root; no drive path outside it, no email, no http(s) URL, no copyright sign; and, when
the denylist file exists, none of its lines (the test says why it skipped that part when the file
is absent).

*Amended 2026-09-24 (owner decision 11B): the design numbers leave the tree.* The design numbers
of the recorded assemblies appear in no tracked file, so the hygiene test no longer lists the
recorded design ids: they are denylist tokens like any other, checked where the denylist exists.
`reviewer/tests/unit/test_tracked_files_carry_no_recorded_number.py` fails when any denylist token
of five digits or more is a whole token of any file `git ls-files` lists (binaries skipped),
naming the file and line, never the token; for the two assemblies' numbers the owner's denylist
also holds the spelling with no separator, which is one longer token. Documents name the recordings in words: the big assembly's recording
(`big-assembly`), the small assembly's two (`small-assembly-a`, `small-assembly-b`).

**Where the recordings are.** Their folder names carry the design numbers, so the owner keeps a
mapping outside the repository, beside the denylist: `%LOCALAPPDATA%\SwReview\recordings.json`,
one JSON object whose keys are the three fixture names and whose values are the recorded run
folders' absolute paths:

```json
{"big-assembly": "<folder>", "small-assembly-a": "<folder>", "small-assembly-b": "<folder>"}
```

The generator takes the folder on its command line, as below; the real-recording test (section 10)
reads the mapping through `reviewer/tests/support/recordings.py`, skipping, saying why, where the
mapping or a mapped folder is absent, and failing where the mapping is there but gives no absolute
folder for a fixture. No message names a mapped folder.

*Amended 2026-09-24 (owner decision 13A): no design's number or folder name stays in the tree.*
Decision 13A extends 11B from the recorded assemblies to every design: no company part number
and no product or assembly folder name of any design is in a tracked file or path (git history
keeps the older mentions). The denylist holds only what the recordings carried, so the owner
keeps a second list beside it, `%LOCALAPPDATA%\SwReview\repo-identifiers.txt`, written by hand
and never committed. Its shape: UTF-8, one identifier per line - a design number in any
spelling, or a folder name, best listed as its words, which also catches it joined; blank
lines, lines starting with `#` and a byte-order mark are ignored.
`reviewer/tests/unit/test_tracked_files_carry_no_recorded_number.py` fails when an identifier's
letter-and-digit runs appear in order, each a whole token, joined by nothing or by up to three
other characters and ignoring case, in any tracked text file or in any tracked file's path. It
names the file and line, or the path with each identifier masked as `…`, never the identifier,
and skips, saying why, where the list is absent.

*Amended 2026-09-23 (owner decision 3A; research R2.54, R2.56): the fixtures follow the code.*
When a change to what a tool returns, or to the system prompt or the checklist, is deliberate,
the three fixtures are regenerated, as part of that change, from `reviewer/`:

```
uv run python tests/fixtures/replay/generate_fixtures.py --recorded <the big assembly's recording folder> --name big-assembly --groups 113
uv run python tests/fixtures/replay/generate_fixtures.py --recorded <the small assembly's recording folder A> --name small-assembly-a
uv run python tests/fixtures/replay/generate_fixtures.py --recorded <the small assembly's recording folder B> --name small-assembly-b
```

(each folder is the one the owner's mapping gives for that fixture name, above), and then the pane
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

*Amended 2026-09-25 (owner decision 23A; research R2.58): the finding check is narrowing-aware,
and the size bar measures the scramble.* The finding check applies section 5's narrowed outcome
through the replay's own function, `benchmark/replay.compare_finding_keys`, imported and never
copied: a recorded `rms.*` finding that no fixture finding matches is narrowed over the recorded
package, its narrowed key carried into the fixture's names by the map the rest of its key goes
through (`scrambled_key`), and matched one to one, in recorded order, to a fixture finding nothing
else matched. The generator prints how many it narrowed beside how many it reclassified. A
recorded key still missing after narrowing, or a new key, still refuses.

*Amended 2026-09-25 (owner decision 25A): references carried by the map.* A key's locations now
carry their references (section 5), and the fixture's references are the recorded ones scrambled -
the names and paths inside them replaced, every other byte kept. `scrambled_key` carries each
location's reference through `FictionalMap.persist_ref`, the function `FictionalMap.package`
scrambled the package's references with, beside the document id, sheet, view and annotation it
already carried through `FictionalMap.value`, and puts the carried locations back in the key's
order (`findings.subject_locations`, the order `finding_subject_key` sorts with), which a changed
reference can change; so a recorded finding and the fixture finding the current code makes on the
scrambled package compare exactly, reference by reference, narrowed or not. The recorded arguments are scrambled as text (`FictionalMap.arguments`), not as references:
none of the three recordings passes a reference as an argument, and a finding whose reference came
from one would be compared through two different scrambles, which can refuse the fixture but never
pass a mismatch.

The 5% bar for a result of 5,000 tokens or more compares each call's result on the fixture with
the same call's result on the raw recorded package, as the current code returns it (the play
`original_sizes` already makes), and no longer with the recorded size. The bar exists to catch the
scramble distorting a result, and a deliberate change to what the code returns is the
regeneration's reason, not a distortion: decision 20A's part check returns 182,865 and 15,548
tokens on the raw packages against 204,858 and 17,437 recorded (-10.7% and -10.8%), and the
fixtures' results, 182,848 and 15,892, are the scrambled form of the first figures, within 5% of
them, not of the second (*corrected 2026-09-25 on review:* this sentence first gave the fixtures'
figures as the raw packages', and -8.9%, which is the fixture's 15,892 against 17,437). It is
exactly as strict about the scramble as before: the same 5,000 tokens and 5%, measured against the
result it already measured against for every call the current code reproduced, and a call the
current code changed is now held to the same bar rather than excused or failed by its code change.
The recorded size still starts each round's usage adjustment, as above. Both are pinned
(`test_replay_generator_narrowed.py`, `test_replay_generator_size_bar.py`).

*Amended 2026-09-25 on review (T127): the live call is also held to its recorded size.* That
sentence held for every call but one. The live `bridge_interference` call's result is the
generator's own invention: `original_sizes` answers it on the raw recorded package with the same
fictional rows the fixture gets, so its raw result is those rows measured against themselves, and
a bar against it cannot see rows fitted short of the recorded result. The bar before decision 23A
saw them only because it compared with the recorded size: on the big recording without
`--groups 113` the rows come to 2,128 tokens raw and 2,129 on the fixture, against 17,015
recorded, and the bar as 23A landed it passed that fixture and it was written. So the live call is
held twice: against its raw result like every call, and, when its recorded result - the size the
generator fits the rows to, sized from the recorded growth - is 5,000 tokens or more, within 5% of
that on the fixture. With `--groups 113` it is 17,062 against 17,015. One function,
`generate_fixtures.live_target`, gives the call's place and recorded size, to the rows and to the
bar alike; `size_problems` names the recorded size in its refusal
(`test_replay_generator_size_bar.py`). The three committed fixtures pass it as written, so none is
regenerated: the generator, run again with the three commands above, writes them again with only
the ids and clocks every run mints moved, and without `--groups 113` it refuses the big one.

*Amended 2026-09-27 (feature 013 T146; the default for T134-Q1): the finding check reads the
tree-reading clause.* Through the same `compare_finding_keys`, imported and never copied, a
recorded `rms.*` finding that lost only the rows the shared tree reading folds over the recorded
package (section 5) narrows onto the fixture finding nothing else matched, its narrowed key
carried into the fixture's names by `scrambled_key` as before. The generator prints the count as
`N narrowed by the type table or the tree reading`. Every other self-check is unchanged: a
recorded key still missing, or a new key, refuses - a `standards.*` finding included, which is
never narrowed. *Amended 2026-09-27 (013 T134-Q2; default taken 2026-09-27, the owner may revise):*
but for `standards.part.sketches_fully_defined`, the one Standards check that reads the shared tree,
which narrows by the tree-reading clause alone (section 5), through the same `compare_finding_keys`,
and is counted in the same `N`; every other `standards.*` finding is still never narrowed.

## 9. The acceptance each story cites

| Story | Acceptance on the fixtures |
|---|---|
| US1 | Pass A within 1% of the recorded input on every round of every fixture; the finding set exact - since feature 010, recorded = replayed + reclassified, with 3, 2 and 0 touching groups reclassified as contacts on `big-assembly`, `small-assembly-a` and `small-assembly-b` (on the fixtures before decision 3A; the amended row below states the invariant as it now reads); the big fixture: four estimated rounds - `bridge_interference`, and since feature 010 the three touching groups judged after it, whose contact results a replay cannot separate from the live call's effect - and one carried round; its recorded total 12.4M within 1% (SC-001) |
| US1 *amended* (2026-09-23, owner decision 3A; research R2.54, R2.56) | On the fixtures regenerated by the current code (section 8): pass A within 1% on every round of every fixture; the finding set exact, recorded = replayed, with 0, 0 and 0 reclassified - the 3, 2 and 0 touching groups live in the generator's reclassification output, the fixtures' recorded contacts and the replay reproducing those contacts exactly with the recorded settings (section 8), and the replay's reclassification path stays pinned on the scripted pre-010 recordings of `test_replay_findings.py`; the big fixture: one estimated round, `bridge_interference` (the three groups judged after it reproduce their recorded contacts), and one carried round; its recorded total 12.4M within 1% (SC-001) (*amended 2026-09-25 on review (T127):* until decision 20A's regeneration, 003 T092; since then the recorded total follows the code, 11,732,561 on the fixtures of that row below, 5.4% under the recording's bill, and `test_replay_fixtures.py` pins it exactly, so a regeneration that moves it at all is re-pinned with its reason; SC-001's 1% on every round is unchanged). Under every requested setting of US2 to US4, no recorded finding lost or not replayable - an absolute rule, unchanged by decision 3A - and none reclassified; each fixture's recorded contacts among the requested pass's |
| US2 | Checks first alone (requested efficiency `prerun_checks=True`, model view off; on the command line `--lever prerun_checks`, or `--no-pane-defaults --lever prerun_checks` once US3 has landed): no recorded finding lost on any fixture; on the big fixture the requested total below pass A's, every one of the 113 groups judged, one interference finding per group (SC-006 offline); the recorded RMS and assembly calls classed `answered_from_checks` |
| US2 *landed as* (T049, T050, 2026-09-23; re-measured after the Phase 9 amendment, unchanged) | `--no-pane-defaults --lever prerun_checks --standards-profile ../config/standards.example.yaml` (before US3 made the pane request the default, `--lever prerun_checks` alone): `big-assembly` recorded 12,456,095, as recorded 12,455,282, requested 4,225,060 (-66.1%); `small-assembly-a` 1,619,376 / 1,619,532 / 1,236,667 (-23.6%); `small-assembly-b` 1,497,696 / 1,497,378 / 1,133,500 (-24.3%). No recorded finding lost and none not replayable on any fixture; 3, 2 and 0 reclassified as contacts on the fixtures before decision 3A (since, the 3, 2 and 0 are the fixtures' recorded contacts, replayed exactly, and none is reclassified (T121)); 62, 7 and 5 added (feature 010's checks in the pre-run: `check_joints`, `check_mass_material`, `check_hygiene`; measured after feature 010 US4-US8 landed). Every one of the 113 groups judged - since feature 010, one finding or one contact each; every recorded `check_rms_*` call `answered_from_checks`; the RMS verdict multiset equal to the recording's |
| US3 | `--pane-defaults` on the big fixture under 1,000,000 requested input tokens with no loss (SC-002); the session's findings identical with the model-view settings on and off (SC-007); every step of the requested pass stored under `tool-results/` (SC-008); every result older than the prune age a stub in every reconstructed request |
| US3 *landed as* (T078, T079, 2026-09-23; re-measured after the Phase 9 amendment) | The default request - `pane_defaults(fake)`: checks first, the tools it ran withheld (lever 13, since the Phase 9 amendment), payload slimming, history pruning after two rounds - with `--standards-profile ../config/standards.example.yaml`: `big-assembly` recorded 12,456,095, as recorded 12,455,282, requested **662,748 (-94.7%)**, and 618,244 (-95.0%) at `--prune-after 1`; `small-assembly-a` 1,619,376 / 1,619,532 / 457,686 (-71.7%), 444,040 (-72.6%) at 1; `small-assembly-b` 1,497,696 / 1,497,378 / 452,302 (-69.8%), 440,056 (-70.6%) at 1. Against checks first alone (US2's 4,225,060, 1,236,667 and 1,133,500) the view, the stubs and lever 13 take a further 84%, 63% and 60%. The view and the stubs alone, as US3 landed (lever 13 off: `--no-pane-defaults --lever prerun_checks --payload-slimming --history-pruning`): 740,472, 531,638 and 512,414, and 695,948, 517,966 and 500,142 at `--prune-after 1`, a further 82%, 57% and 55%. No recorded finding lost and none not replayable on any fixture, at either prune age; 3, 2 and 0 reclassified as contacts on the fixtures before decision 3A (since, the 3, 2 and 0 are the fixtures' recorded contacts, replayed exactly, and none is reclassified (T121)); 62, 7 and 5 added, as under checks first alone. The big fixture's requested session records the same findings and contacts with the view off (SC-007) and one stored result per step (SC-008); its four estimated rounds are the live call and the three touching groups judged after it, as under US1 (on the fixtures before decision 3A; since T121 one, `bridge_interference`: the three groups reproduce their recorded contacts, as under US1 amended) |
| US4 | The regrouped estimate under 300,000 for each small fixture, with the strict figure below the recorded total (SC-003, amended); the big fixture's follow-up round under 30,000 (SC-004); three answers in one batch replay as one resumed turn (SC-005, scripted) |
| US4 *landed as* (T086, T087, 2026-09-23; re-measured after the Phase 9 amendment) | `pane_defaults(openai)` - checks first, the tools it ran withheld (lever 13), parallel calls, payload slimming, history pruning after two rounds - with `--standards-profile ../config/standards.example.yaml` (on the command line `--lever parallel_tool_calls` on a fixture): regrouped estimate, rules R and M, `small-assembly-a` **244,167** over 21 rounds (strict 457,686 over 39, recorded 1,619,376), `small-assembly-b` **243,134** over 20 rounds (strict 452,302 over 37, recorded 1,497,696), `big-assembly` 276,620 over 16 rounds (strict 662,748 over 41); at `--prune-after 1` 231,020, 231,110 and 233,323. The margin under 300,000 is 18.6% and 19.0%. As US4 landed (lever 13 off: `--no-pane-defaults --lever prerun_checks --lever parallel_tool_calls --payload-slimming --history-pruning`): 283,163, 274,957 and 305,864 (margins 5.6% and 8.3%), and 269,998, 262,915 and 262,555 at `--prune-after 1`. With the fixtures' own `pane_defaults(fake)` (rule R alone) the regrouped estimates are 380,647, 387,998 and 486,094 (443,019, 441,570 and 544,558 with lever 13 off). The big fixture's follow-up round (turn 1, round 0): **22,534** requested against 407,399 recorded (22,073 at `--prune-after 1`; 24,480 and 24,013 with lever 13 off). No recorded finding lost on any fixture; 3, 2 and 0 reclassified on the fixtures before decision 3A (since, the 3, 2 and 0 are the fixtures' recorded contacts, replayed exactly, and none is reclassified (T121)); 62, 7 and 5 added, as under US3. A two-answer batch replays through `answer_evidence_batch` as one resumed turn in both passes (scripted) |
| US5 | Every step's `result_tokens` in the requested pass's session equals the replay's count of that call's full payload (one tokenizer, one serialization) |
| US1 to US4 *re-measured* (T121, 2026-09-23, decision 3A: the fixtures regenerated by the code that adds feature 010's two checklist items, T098-T099 and T108; *landed as*: measured again on main after the six commits were cherry-picked onto it and 010 T108's bucket amendment, every figure the same; and again after the three fixtures were regenerated on main, where only their finding events' titles moved, every figure the same) | All with `--standards-profile ../config/standards.example.yaml`; the worst as-recorded round 0.005%, 0.017% and 0.028% from its recorded input. `big-assembly` recorded 12,411,209, as recorded 12,411,080; pane defaults **663,902 (-94.7%)**, 619,092 (-95.0%) at `--prune-after 1`; `--no-pane-defaults --lever prerun_checks` 4,232,500 (-65.9%); the view and the stubs without lever 13 741,388 (696,546 at `--prune-after 1`). `small-assembly-a` 1,598,717 / 1,598,817; 459,000 (-71.3%), 444,881 (-72.2%); 1,244,479 (-22.2%); 532,886 (518,737). `small-assembly-b` 1,505,494 / 1,505,562; 453,564 (-69.9%), 440,841 (-70.7%); 1,141,684 (-24.2%); 513,676 (500,927). The OpenAI pane (`--lever parallel_tool_calls`), rules R and M: **245,289** over 21 rounds, **244,277** over 20 and 277,361 over 16 (231,665, 231,776 and 233,746 at `--prune-after 1`), margins under 300,000 of 18.2% and 18.6% (without lever 13: 284,285, 276,100 and 306,605); the fixtures' own pane, rule R alone: 381,853, 389,232 and 486,940. The big fixture's follow-up round: **22,719** requested against 405,280 recorded (22,099 at `--prune-after 1`, 24,653 without lever 13 and 24,027 without it at `--prune-after 1`). Every run: pass A within 1%, no recorded finding lost, none not replayable (absolute), 0, 0 and 0 reclassified; 62, 7 and 5 added; the 3, 2 and 0 are the generator's reclassification output and the fixtures' recorded contacts, replayed with the recorded settings exactly and held among every requested pass's. Against the figures above: the recorded totals move by -44,886, -20,659 and +7,798 - on the big fixture each touching group's result is now the current code's contact, 779, 893 and 794 tokens smaller than the finding recorded, each of the two `get_review_checklist` answers is 185 tokens larger with the two new items, and the live call's result 23 smaller, each carried by every later round - and the requested totals rise by 1,154, 1,314 and 1,262 with the pane defaults, the two items in the system prompt and in `get_review_checklist`'s answers |
| US1 to US4 *re-measured* (feature 011 integration, 2026-09-23: standards profile version 3 - 011 T028-T029 gave `config/standards.example.yaml` its drawing section - changes the profile's sha256, which each standards finding's provenance carries; the three fixtures regenerated with section 8's commands, 3, 2 and 0 reclassified as contacts by the generator, the packages byte-identical, then the pane fixture) | All with `--standards-profile ../config/standards.example.yaml`; the worst as-recorded round 0.005%, 0.017% and 0.028% from its recorded input. `big-assembly` recorded 12,412,329, as recorded 12,412,200; `small-assembly-a` 1,598,829 / 1,598,929; `small-assembly-b` 1,505,638 / 1,505,706. Every requested figure of the row above is unchanged: pane defaults **663,902 (-94.7%)**, 459,000 (-71.3%) and 453,564 (-69.9%), and 619,092, 444,881 and 440,841 at `--prune-after 1`; `--no-pane-defaults --lever prerun_checks` 4,232,500 (-65.9%), 1,244,479 (-22.2%) and 1,141,684 (-24.2%); the view and the stubs without lever 13 741,388, 532,886 and 513,676 (696,546, 518,737 and 500,927 at `--prune-after 1`); the OpenAI pane, rules R and M, **277,361** over 16 rounds, **245,289** over 21 and **244,277** over 20 (233,746, 231,665 and 231,776 at `--prune-after 1`; without lever 13 306,605, 284,285 and 276,100); the fixtures' own pane, rule R alone, 486,940, 381,853 and 389,232. The big fixture's follow-up round: **22,719** requested against 405,320 recorded (22,099 at `--prune-after 1`, 24,653 without lever 13 and 24,027 without it at `--prune-after 1`). Every run: pass A within 1%, no recorded finding lost, none not replayable (absolute), 0, 0 and 0 reclassified; 62, 7 and 5 added. Against the row above: the recorded and as-recorded totals move by +1,120, +112 and +144 - the new hash tokenizes 8 tokens longer, once per standards finding (5, 1 and 1), so each recording's one `check_standards` result is 40, 8 and 8 tokens larger, carried by the 28, 14 and 18 rounds after it - and the follow-up round's recorded input by +40. No requested figure moves: the requested pass answers that recorded call from checks first and withholds the tool. A fixture carries no drawing evidence, so feature 011's drawing family is neither offered nor planned in a replay |
| US1 to US4 *re-measured* (integration of the owner's decisions 20A, 21A and 22A, 2026-09-25: 21A's guard and 22A's add-in change no tool's return, and 20A lands as its package and three open tasks, its checker change waiting on the owner's question 20A-Q1 (003 T092); the fixtures not regenerated) | All with `--standards-profile ../config/standards.example.yaml`, on the committed fixtures; the worst as-recorded round 0.005%, 0.017% and 0.028% from its recorded input. Every figure of the row above is unchanged: `big-assembly` recorded 12,412,329, as recorded 12,412,200; `small-assembly-a` 1,598,829 / 1,598,929; `small-assembly-b` 1,505,638 / 1,505,706; pane defaults **663,902 (-94.7%)**, 459,000 (-71.3%) and 453,564 (-69.9%), and 619,092, 444,881 and 440,841 at `--prune-after 1`; `--no-pane-defaults --lever prerun_checks` 4,232,500 (-65.9%), 1,244,479 (-22.2%) and 1,141,684 (-24.2%); the view and the stubs without lever 13 741,388, 532,886 and 513,676 (696,546, 518,737 and 500,927 at `--prune-after 1`); the OpenAI pane, rules R and M, **277,361** over 16 rounds, **245,289** over 21 and **244,277** over 20 (233,746, 231,665 and 231,776 at `--prune-after 1`; without lever 13 306,605, 284,285 and 276,100); the fixtures' own pane, rule R alone, 486,940, 381,853 and 389,232. The big fixture's follow-up round: **22,719** requested against 405,320 recorded (22,099 at `--prune-after 1`, 24,653 without lever 13 and 24,027 without it at `--prune-after 1`). Every run: pass A within 1%, no recorded finding lost, none not replayable (absolute), 0, 0 and 0 reclassified; 62, 7 and 5 added. The real recordings (section 10) keep a zero residual on every round, and their replayed plus not-replayable findings are the recorded key set. Section 8's generator, run on main, writes fixtures that differ from the committed ones only in their event logs - 6, 4 and 6 `coverage.withdrawn` events (feature 011 T092-T093) the committed logs predate, and the ids and clocks every run mints - so no result, finding, round or figure moves |
| US1 to US4 *re-measured* (review of that integration, 2026-09-25: the three fixtures regenerated with section 8's commands, so their event logs carry feature 011 T092-T093's `coverage.withdrawn` events - 3, 2 and 0 reclassified as contacts by the generator, the packages byte-identical, the owner's denylist unchanged - then the pane fixture, whose `last_seq` alone moved; 21A's T169 denials and 22A's review tests change no tool's return) | All with `--standards-profile ../config/standards.example.yaml`, on the regenerated fixtures. Every configuration of the rows above gives a report identical to the one the committed fixtures gave, apart from the run folder, so every figure of the row above is unchanged: `big-assembly` recorded 12,412,329, as recorded 12,412,200; `small-assembly-a` 1,598,829 / 1,598,929; `small-assembly-b` 1,505,638 / 1,505,706; pane defaults **663,902 (-94.7%)**, 459,000 (-71.3%) and 453,564 (-69.9%), and 619,092, 444,881 and 440,841 at `--prune-after 1`; `--no-pane-defaults --lever prerun_checks` 4,232,500 (-65.9%), 1,244,479 (-22.2%) and 1,141,684 (-24.2%); the view and the stubs without lever 13 741,388, 532,886 and 513,676 (696,546, 518,737 and 500,927 at `--prune-after 1`); the OpenAI pane, rules R and M, **277,361** over 16 rounds, **245,289** over 21 and **244,277** over 20 (233,746, 231,665 and 231,776 at `--prune-after 1`; without lever 13 306,605, 284,285 and 276,100); the fixtures' own pane, rule R alone, 486,940, 381,853 and 389,232. The big fixture's follow-up round: **22,719** requested against 405,320 recorded (22,099 at `--prune-after 1`, 24,653 without lever 13 and 24,027 without it at `--prune-after 1`). Every run: pass A within 1% (the worst as-recorded round 0.005%, 0.017% and 0.028% from its recorded input), no recorded finding lost, none not replayable (absolute), 0, 0 and 0 reclassified; 62, 7 and 5 added. The real recordings (section 10) keep a zero residual on every round, and their replayed plus not-replayable findings are the recorded key set. 003 T092's regeneration now carries only its own change |
| US1 to US4 *re-measured* (the owner's decision 20A lands - feature 003 T090 to T092, 2026-09-25 - read by decision 23A: the eleven system types of the real dumps are `tolerated_loose`, so `check_rms_part` no longer names those rows; the three fixtures regenerated with section 8's commands, the generator reclassifying 3, 2 and 0 touching groups as contacts and narrowing 20, 2 and 1 `rms.grouping.all_features_in_a_group` findings by the type table, its size bar passed against the current code's raw results, the packages byte-identical and the owner's denylist unchanged; then the pane fixture) | All with `--standards-profile ../config/standards.example.yaml`, on the regenerated fixtures; the worst as-recorded round 0.005%, 0.017% and 0.028% from its recorded input, as before. The recorded and as-recorded totals fall: `big-assembly` 11,732,561 / 11,732,463 (from 12,412,329 / 12,412,200), `small-assembly-a` 1,566,206 / 1,566,323 (from 1,598,829 / 1,598,929), `small-assembly-b` 1,483,228 / 1,483,361 (from 1,505,638 / 1,505,706). Each fixture's part check result is its recorded one less the system-row subjects - 182,848 tokens on the big fixture (from 204,775, 760 feature rows from 866), 15,892 (from 17,810) and 11,637 (from 12,593) on the small ones, and `small-assembly-b`'s equations check 675 (from 692) - carried by every later round: 21,928 tokens fewer in each of the big fixture's 31 rounds after its part check, 1,919 in 17 on `small-assembly-a`, 957 in 2 and 976 in 21 on `small-assembly-b`. The big fixture's follow-up round records 383,392 (from 405,320), and its recorded total is no longer within 1% of the recording's 12.4M bill (US1's rows): it follows the code (`test_replay_fixtures.py`). **No requested figure moves**: under every requested setting the recorded part checks are answered from checks first (the guard's `already_run`, and with lever 13 the tool withheld), and what checks first puts in the conversation, the digest, counts findings rather than subjects. Pane defaults **663,902 (-94.3%)**, 459,000 (-70.7%) and 453,564 (-69.4%), and 619,092, 444,881 and 440,841 at `--prune-after 1`; `--no-pane-defaults --lever prerun_checks` 4,232,500 (-63.9%), 1,244,479 (-20.5%) and 1,141,684 (-23.0%); the view and the stubs without lever 13 741,388, 532,886 and 513,676 (696,546, 518,737 and 500,927 at `--prune-after 1`); the OpenAI pane, rules R and M, **277,361** over 16 rounds, **245,289** over 21 and **244,277** over 20 (233,746, 231,665 and 231,776 at `--prune-after 1`; without lever 13 306,605, 284,285 and 276,100), margins under 300,000 of 18.2% and 18.6%; the fixtures' own pane, rule R alone, 486,940, 381,853 and 389,232. The big fixture's follow-up round: **22,719** requested against 383,392 recorded (22,099 at `--prune-after 1`, 24,653 without lever 13 and 24,027 without it at `--prune-after 1`). The percentages are against the new recorded totals, so they read lower for the same requested figures. Every run: pass A within 1%, no recorded finding lost, none not replayable (absolute), none reclassified and none narrowed (the fixtures record what the current table counts); 62, 7 and 5 added. The real recordings (section 10): a zero residual on every round (40, 38 and 36 main rounds and one presentation round each, none outside the rule); none lost, none added; 20, 2 and 1 `rms.grouping.all_features_in_a_group` findings narrowed, 106, 10 and 5 locations removed; replayed plus not replayable the recorded count (88 + 11 = 99 on the big recording) |
| US1 to US4 *re-measured* (integration of the owner's decisions 23A and 24A with 20A's landing, 2026-09-25: 24A's plan-lost notice - feature 004 T170 - lives in the add-in and the Remodel page and changes no tool's return, and the `reviewer/` tree on main is the one 003 T092 regenerated the fixtures with, so the fixtures are not regenerated again) | All with `--standards-profile ../config/standards.example.yaml`, on the committed fixtures, measured on main after both lanes were cherry-picked onto it; ten configurations each - pane defaults, and at `--prune-after 1`; `--no-pane-defaults --lever prerun_checks`; the view and the stubs without lever 13, and at `--prune-after 1`; the OpenAI pane, at `--prune-after 1`, without lever 13, and without it at `--prune-after 1`; and `--no-pane-defaults`. Every figure of the row above is unchanged: `big-assembly` recorded 11,732,561, as recorded 11,732,463; `small-assembly-a` 1,566,206 / 1,566,323; `small-assembly-b` 1,483,228 / 1,483,361; pane defaults **663,902 (-94.3%)**, 459,000 (-70.7%) and 453,564 (-69.4%), and 619,092, 444,881 and 440,841 at `--prune-after 1`; `--no-pane-defaults --lever prerun_checks` 4,232,500 (-63.9%), 1,244,479 (-20.5%) and 1,141,684 (-23.0%); the view and the stubs without lever 13 741,388, 532,886 and 513,676 (696,546, 518,737 and 500,927 at `--prune-after 1`); the OpenAI pane, rules R and M, **277,361** over 16 rounds, **245,289** over 21 and **244,277** over 20 (233,746, 231,665 and 231,776 at `--prune-after 1`; without lever 13 306,605, 284,285 and 276,100), margins under 300,000 of 18.2% and 18.6%; the fixtures' own pane, rule R alone, 486,940, 381,853 and 389,232. The big fixture's follow-up round: **22,719** requested against 383,392 recorded (22,099 at `--prune-after 1`, 24,653 without lever 13 and 24,027 without it at `--prune-after 1`). Every run: pass A within 1% (the worst as-recorded round 0.005%, 0.017% and 0.028% from its recorded input, one estimated round each), no recorded finding lost, none not replayable (absolute), none reclassified and none narrowed; 62, 7 and 5 added (none with `--no-pane-defaults`, where the requested pass is the recorded one). The real recordings (section 10), replayed as recorded: none lost, none added; 20, 2 and 1 `rms.grouping.all_features_in_a_group` findings narrowed, 106, 10 and 5 locations removed; replayed plus not replayable the recorded count (88 + 11 = 99, 10 + 3 = 13 and 6 + 1 = 7); a zero residual on every round (40, 38 and 36 main rounds and one presentation round each) |
| Feature 013 US1 *re-measured* (013 T042, 2026-09-27: the replay gate of User Story 1, bought parts, on main after its model-read changes - lanes P and S - and nothing else that moves what the model reads; the three fixtures regenerated with section 8's commands, the generator reclassifying 3, 2 and 0 touching groups as contacts and narrowing 20, 2 and 1 findings by the type table as before, the packages byte-identical and the owner's denylist unchanged; then the pane fixture. The example profile, version 4 since 013 T014, decides no document of a scrambled fixture, so each review is in the configured state with the zero-match guard fired: every document `role=unclear` in the brief, one unresolved `coverage.prerun.part_roles` row and its digest line, and no part-roles question. 013 T133's tree reading is not on main (backed out at integration, 013 T134), so no part check result moves) | All with `--standards-profile ../config/standards.example.yaml`, on the regenerated fixtures, the ten configurations of the row above; the worst as-recorded round 0.005%, 0.017% and 0.028% from its recorded input, as before. The recorded and as-recorded totals rise: `big-assembly` 11,733,321 / 11,733,223 (from 11,732,561 / 11,732,463, +760), `small-assembly-a` 1,567,242 / 1,567,387 (+1,036 / +1,064), `small-assembly-b` 1,484,336 / 1,484,469 (+1,108): each `get_review_checklist` answer is 26 tokens larger (the modelling and hygiene items' "Custom parts only; bought parts are listed once, not graded."), carried by every later round, and the one `check_standards` result is 10, 4 and 2 tokens smaller (the version 4 example's sha256, carried by each of its 5, 1 and 1 findings, tokenizes shorter). The big fixture's follow-up round records 383,434 (from 383,392, +42: both checklist answers and the standards result). The requested figures rise by about 26 tokens in every requested round, what every round re-reads (the checklist in the system prompt, the brief's `role=` and the guard's digest line in the opening message): pane defaults **664,966 (-94.3%)**, 460,068 (-70.6%) and 454,584 (-69.4%), and 620,104, 445,871 and 441,783 at `--prune-after 1`; `--no-pane-defaults --lever prerun_checks` 4,234,500 (-63.9%), 1,246,483 (-20.5%) and 1,143,692 (-22.9%); the view and the stubs without lever 13 742,452, 533,954 and 514,696 (697,558, 519,727 and 501,869 at `--prune-after 1`); the OpenAI pane, rules R and M, **277,825** over 16 rounds, **245,925** over 21 and **244,889** over 20 (234,158, 232,223 and 232,310 at `--prune-after 1`; without lever 13 307,069, 284,921 and 276,712), margins under 300,000 of 18.0% and 18.4%; the fixtures' own pane, rule R alone, 487,764, 382,777 and 390,156. The big fixture's follow-up round: **22,769** requested against 383,434 recorded (22,123 at `--prune-after 1`, 24,703 without lever 13 and 24,051 without it at `--prune-after 1`). Every run: pass A within 1%, no recorded finding lost, none not replayable (absolute), none reclassified and none narrowed; 62, 7 and 5 added (none with `--no-pane-defaults`). The real recordings (section 10): a zero residual on every round; none lost, none added; 20, 2 and 1 findings narrowed with 106, 10 and 5 locations removed; replayed plus not replayable the recorded count. Pinned again with the reasons: `test_replay_fixtures.py`'s recorded total and follow-up round |
| Feature 013 US3 *re-measured* (013 T069, 2026-09-27: the replay gate of User Story 3, questions the review never asks, on main after lane S's T059-T068 - provenance closed by code at setup, the re-ask guard, the tools' own ids, the brief and the prompt no longer inviting the vault question - and nothing else that moves what the model reads; the three fixtures regenerated with section 8's commands, 3, 2 and 0 reclassified as contacts, 20, 2 and 1 narrowed by the type table, the packages byte-identical, the owner's denylist unchanged; then the pane fixture. The recorded `mark_coverage(provenance)` call is now answered `closed_by_code`, the replay's "changed" class (013 research R5), so the generator sizes one more call per fixture from the recorded growth; no recorded re-ask of the three recordings is one the guard answers) | All with `--standards-profile ../config/standards.example.yaml`, on the regenerated fixtures, the ten configurations; the worst as-recorded round 0.005%, 0.017% and 0.028% from its recorded input, as before. The recorded and as-recorded totals: `big-assembly` 11,733,699 / 11,733,601 (+378), `small-assembly-a` 1,567,614 / 1,567,759 (+372), `small-assembly-b` 1,484,498 / 1,484,631 (+162): the first `get_review_checklist` answer is 24 tokens larger and each later one 23 (the provenance item, code-owned, renders "Closed by code before your first turn"), and the `mark_coverage(provenance)` result is 58, 63 and 68 tokens smaller, each carried by every later round. The big fixture's follow-up round records 383,423 (-11). The requested figures fall, the brief no longer printing an unknown vault version or local modification and the checklist and prompt reworded: pane defaults **664,630 (-94.3%)**, 459,748 (-70.7%) and 454,061 (-69.4%), and 619,721, 445,481 and 441,190 at `--prune-after 1`; `--no-pane-defaults --lever prerun_checks` 4,234,878 (-63.9%), 1,246,855 (-20.5%) and 1,143,854 (-22.9%); the view and the stubs without lever 13 742,116, 533,634 and 514,173 (697,175, 519,337 and 501,276 at `--prune-after 1`); the OpenAI pane, rules R and M, **277,790** over 16 rounds, **245,835** over 21 and **244,672** over 20 (234,076, 232,063 and 232,023 at `--prune-after 1`; without lever 13 307,034, 284,831 and 276,495), margins under 300,000 of 18.1% and 18.4%; the fixtures' own pane, rule R alone, 487,428, 382,457 and 389,633. The big fixture's follow-up round: **22,749** requested against 383,423 recorded (22,080 at `--prune-after 1`, 24,683 without lever 13 and 24,008 without it at `--prune-after 1`). Every run: pass A within 1%, no recorded finding lost, none not replayable (absolute), none reclassified and none narrowed; 62, 7 and 5 added (none with `--no-pane-defaults`). The real recordings (section 10): a zero residual on every round; none lost, none added. Pinned again with the reasons: `test_replay_fixtures.py`'s recorded total and follow-up round; the big fixture's one estimated round, the live call, holds on the regenerated fixture (its strict xfail removed) |
| Feature 013 US4 *re-measured* (013 T095, 2026-09-27: the replay gate of User Story 4, drawings that follow the seat, on main after lanes D and S's US4 commits - the host's capability on ping, drawing states for custom documents only, one read per file, code answering drawing requests, the outcome lines - and nothing else that moves what the model reads; lane D merged before lane S's US4 commit at integration, which needs its functions. The fixtures carry no drawing evidence, so the drawing family is neither offered nor pinged and row 6 answers nothing; the checklist's drawing item and the prompt move. The three fixtures regenerated with section 8's commands, 3, 2 and 0 reclassified, 20, 2 and 1 narrowed by the type table, the packages byte-identical, the denylist unchanged; then the pane fixture) | All with `--standards-profile ../config/standards.example.yaml`, on the regenerated fixtures, the ten configurations; the worst as-recorded round 0.005%, 0.017% and 0.028%, as before. The recorded and as-recorded totals: `big-assembly` 11,734,099 / 11,734,001 (+400), `small-assembly-a` 1,568,034 / 1,568,179 (+420), `small-assembly-b` 1,484,938 / 1,485,071 (+440): each `get_review_checklist` answer is 10 tokens larger (the drawing item says `check_drawings` decides which drawings exist; never request a drawing or a drawing's version). The big fixture's follow-up round records 383,443 (+20). The requested figures rise by the checklist in every requested round: pane defaults **664,670 (-94.3%)**, 459,808 (-70.7%) and 454,121 (-69.4%), and 619,741, 445,511 and 441,220 at `--prune-after 1`; `--no-pane-defaults --lever prerun_checks` 4,235,278 (-63.9%), 1,247,275 (-20.5%) and 1,144,294 (-22.9%); the view and the stubs without lever 13 742,156, 533,694 and 514,233 (697,195, 519,367 and 501,306 at `--prune-after 1`); the OpenAI pane, rules R and M, **277,830** over 16 rounds, **245,895** over 21 and **244,732** over 20 (234,096, 232,093 and 232,053 at `--prune-after 1`; without lever 13 307,074, 284,891 and 276,555), margins under 300,000 of 18.0% and 18.4%; the fixtures' own pane, rule R alone, 487,468, 382,517 and 389,693. The big fixture's follow-up round: **22,759** requested against 383,443 recorded (22,080 at `--prune-after 1`, 24,693 without lever 13 and 24,008 without it at `--prune-after 1`). Every run: pass A within 1%, no recorded finding lost, none not replayable (absolute), none reclassified and none narrowed; 62, 7 and 5 added (none with `--no-pane-defaults`). The real recordings (section 10): a zero residual on every round; none lost, none added. Pinned again with the reasons: `test_replay_fixtures.py`'s recorded total and follow-up round |
| Feature 013 US6 *re-measured* (013 T124 and T125, 2026-09-27: the replay gate of User Story 6, answer turns that cost only what they need, on main after lanes S and E's T116-T123 - the close-out closed by code at finalization, `open_items` on every `mark_coverage` and `request_evidence` answer, lever 14 and its pricing - and nothing else that moves what the model reads; the three fixtures regenerated with section 8's commands, 3, 2 and 0 reclassified, 20, 2 and 1 narrowed by the type table, the packages byte-identical, the denylist unchanged; then the pane fixture. The recorded answers that now carry `open_items`, and the recorded `mark_coverage(coverage.closeout)` now answered `closed_by_code`, are the "changed" class, so the generator sizes 25, 16 and 18 calls from the recorded growth (14, 7 and 7 before). Replayed with lever 14 off and on; on T125's adoption lever 14 is a pane default, and the pane figures below are with it on) | All with `--standards-profile ../config/standards.example.yaml`, on the regenerated fixtures, the ten configurations; the worst as-recorded round 0.005%, 0.017% and 0.028%, as before. The recorded and as-recorded totals: `big-assembly` 11,736,483 / 11,736,385 (+2,384), `small-assembly-a` 1,570,535 / 1,570,680 (+2,501), `small-assembly-b` 1,488,891 / 1,489,024 (+3,953): each recorded coverage or request answer lists the items still open (33 to 42 tokens on the first, fewer as items close) and the close-out mark's answer is 110, 133 and 132 tokens smaller. The big fixture's follow-up round records 383,604 (+161). **Lever 14 off** (the rows as T124 measured them): pane defaults 665,795 (-94.3%), 460,822 (-70.7%) and 456,235 (-69.4%), and 620,867, 446,526 and 443,339 at `--prune-after 1`; the OpenAI pane, rules R and M, 278,003 over 16 rounds, 246,278 over 21 and 245,647 over 20 (234,270, 232,477 and 232,973 at `--prune-after 1`); the fixtures' own pane, rule R alone, 488,593, 383,531 and 391,807; the big follow-up round 22,791 requested (22,113 at `--prune-after 1`). **Lever 14 on**, an estimate (research R3 C13: each round of a later turn priced lower by the earlier turns' recorded reasoning output; 2, 2 and 4 estimated rounds): no recorded finding lost, none not replayable, reclassified or narrowed in any configuration, and the requested input lower in every one, so T125 adopts it (005 `contracts/levers.md`, lever 14). The pane defaults with it: **662,903 (-94.4%)**, 458,700 (-70.8%) and 450,298 (-69.8%), and 617,975, 444,404 and 437,402 at `--prune-after 1`; `--no-pane-defaults --lever prerun_checks` 4,236,762 (-63.9%), 1,248,640 (-20.5%) and 1,147,026 (-23.0%); the view and the stubs without lever 13 (and without lever 14) 743,281, 534,708 and 516,347 (698,321, 520,382 and 503,425 at `--prune-after 1`); the OpenAI pane, rules R and M, **276,246** over 16 rounds, **244,232** over 21 and **242,377** over 20 (232,513, 230,431 and 229,703 at `--prune-after 1`; without levers 13 and 14 307,247, 285,274 and 277,470), margins under 300,000 of 18.6% and 19.2%; the fixtures' own pane, rule R alone, 486,836, 381,485 and 388,537. The big fixture's follow-up round: **19,899** requested against 383,604 recorded (19,221 at `--prune-after 1`, 24,725 without levers 13 and 14 and 24,041 without them at `--prune-after 1`). Every run: pass A within 1%, no recorded finding lost, none not replayable (absolute), none reclassified and none narrowed; 62, 7 and 5 added (none with `--no-pane-defaults`). The real recordings (section 10): a zero residual on every round; none lost, none added. Pinned again with the reasons: `test_replay_fixtures.py`'s recorded total and follow-up round; the big fixture's one estimated round, the live call, holds with the recorded settings |
| Feature 013 US2 *re-measured* (013 T058, 2026-09-27: the replay gate of User Story 2, every finding grouped by type and no pass amplified, on main after lane R's T043-T052 and T057 - `top_n` no longer the constant five, the explanation pass never sent a pass, the grouped view, the summary block, `report.md`'s Findings by type - and nothing else that moves what the model reads. What US2 moves the model reads only through the gate brief (lever 11) and the explanation pass, neither of which a configuration of this section turns on, and each fixture has five or more undecided rows. The generator, run with section 8's commands, writes fixtures that differ from the committed ones only in the timings every run mints, so none is regenerated; the pane fixture's regeneration is 013 T056's, after the Review page (lane W) that reads its groups) | All with `--standards-profile ../config/standards.example.yaml`, on the committed fixtures, the ten configurations: every figure of the row "Feature 013 US6" is unchanged, with lever 14 on in the pane - pane defaults **662,903**, 458,700 and 450,298 (617,975, 444,404 and 437,402 at `--prune-after 1`); the OpenAI pane, rules R and M, **276,246**, **244,232** and **242,377**; the big fixture's follow-up round **19,899** against 383,604 recorded. Every run: pass A within 1% (worst 0.005%, 0.017% and 0.028%), no recorded finding lost, none not replayable (absolute), none reclassified and none narrowed; 62, 7 and 5 added. The real recordings (section 10): a zero residual on every round; none lost, none added |
| Feature 013 follow-ups *re-measured* (013 T158, 2026-09-27: the replay gate of 013 T157 - the checklist's code-owned line now "Closed by code; never ask about it or mark it.", true of both code-owned items, and the close-out's description saying when code closes it - with the other follow-ups beside it, none of which moves what the model reads on a fixture: T145-T146's tree-reading clause of section 5 (main's reading folds nothing a recorded finding lost, so no committed figure moves), T147-T150's Model check line, T151-T152's lever 14 fallback and T154-T155's refusal reason; the three fixtures regenerated with section 8's commands, the generator reclassifying 3, 2 and 0 touching groups as contacts and narrowing 20, 2 and 1 findings, the packages byte-identical and the owner's denylist unchanged; then the pane fixture) | All with `--standards-profile ../config/standards.example.yaml`, on the regenerated fixtures, the ten configurations; the worst as-recorded round 0.005%, 0.017% and 0.028% from its recorded input, as before. The recorded and as-recorded totals: `big-assembly` 11,736,827 / 11,736,729 (+344), `small-assembly-a` 1,570,895 / 1,571,040 (+360), `small-assembly-b` 1,489,283 / 1,489,416 (+392): each `get_review_checklist` answer, and the recorded `mark_coverage(coverage.closeout)` answer, whose `closed_by_code` reason quotes the close-out's description, is 8 tokens larger, carried by every later round; the rendered checklist in the system prompt is the same size (the code-owned line 4 tokens shorter on each of its two items, the description 8 longer). The big fixture's follow-up round records 383,628 (+24). The requested figures rise by the answers each requested round carries: pane defaults **662,959 (-94.4%)**, 458,772 (-70.8%) and 450,386 (-69.8%), and 618,015, 444,452 and 437,466 at `--prune-after 1`; `--no-pane-defaults --lever prerun_checks` 4,237,106 (-63.9%), 1,249,000 (-20.5%) and 1,147,418 (-23.0%); the view and the stubs without levers 13 and 14 743,337, 534,780 and 516,435 (698,361, 520,430 and 503,489 at `--prune-after 1`); the OpenAI pane, rules R and M, **276,302** over 16 rounds, **244,304** over 21 and **242,465** over 20 (232,553, 230,479 and 229,767 at `--prune-after 1`; without levers 13 and 14 307,303, 285,346 and 277,558), margins under 300,000 of 18.6% and 19.2%; the fixtures' own pane, rule R alone, 486,892, 381,557 and 388,625. The big fixture's follow-up round: **19,915** requested against 383,628 recorded (19,229 at `--prune-after 1`, 24,741 without levers 13 and 14 and 24,049 without them at `--prune-after 1`; with lever 14 alone off, 22,807 and 22,121, the pane defaults 665,851 and 620,907). Every run: pass A within 1%, no recorded finding lost, none not replayable (absolute), none reclassified and none narrowed; 62, 7 and 5 added (none with `--no-pane-defaults`). The real recordings (section 10): a zero residual on every round; none lost, none added; 20, 2 and 1 findings narrowed. Pinned again with the reasons: `test_replay_fixtures.py`'s recorded total and follow-up round; the big fixture's one estimated round, the live call, holds on the regenerated fixture (its strict xfail removed). The regenerated sessions no longer hold the legacy explanation line, which 013 `contracts/sources.md` section 4 kept the fixtures unedited for (amended: decision 3A first) |
| Feature 013 US7 *re-measured* (013 T134, 2026-09-27: the replay gate of User Story 7, one sketch, one row, on main after lane T's T132-T133 - the RMS part rules and the Standards sketch check read the tree one node per feature position (`checks/feature_nodes.tree_nodes`) - and nothing else that moves what the model reads; T132-T133 land with section 5's tree-reading clause (013 T145-T146, the default for T134-Q1) read for every check that reads the tree, the Standards sketch check included (the default for T134-Q2); the three fixtures regenerated with section 8's commands, the generator reclassifying 3, 2 and 0 touching groups as contacts and narrowing 29, 4 and 3 recorded findings - 26, 3 and 2 `rms.*` by the type table or the tree reading, 3, 1 and 1 `standards.part.sketches_fully_defined` by the tree reading alone - so none lost, its size bar passed, the packages byte-identical and the owner's denylist unchanged; then the pane fixture) | All with `--standards-profile ../config/standards.example.yaml`, on the regenerated fixtures, the ten configurations; the worst as-recorded round 0.005%, 0.017% and 0.028% from its recorded input, as before. The recorded and as-recorded totals fall: `big-assembly` 10,582,573 / 10,582,475 (-1,154,254), `small-assembly-a` 1,507,165 / 1,507,282 (-63,730 / -63,758), `small-assembly-b` 1,416,304 / 1,416,437 (-72,979): the part check names each absorbed sketch once, at its depth-0 row, and no carried row, so its result is 146,370 tokens on the big fixture (from 182,848; 583 feature rows from 760), 12,312 (from 15,892) and 8,626 (from 11,637) on the small ones, carried by the 31, 17 and 23 rounds after it; and the Standards sketch finding names each absorbed sketch once too, so the one `check_standards` result is 837, 207 and 207 tokens smaller (4,354, 1,257 and 1,378), carried by the 28, 14 and 18 rounds after it (on `small-assembly-a` the generator now sizes that call from the recorded growth - 17 calls from 16; on the other two it already did - so its recorded rounds move by 205 tokens where the replayed move by 207). The big fixture's follow-up round records 346,313 (-37,315). The requested figures barely move: every recorded part check is answered from checks first, whose re-call guard gives an RMS result's counts rather than its subjects, and only the guard's answer to the recorded `check_standards` call, which digests the standards result's subjects, is 16, 8 and 8 tokens smaller - carried by the 28, 14 and 18 later rounds under checks first alone, and in the pane for the two rounds before pruning stubs it (one at `--prune-after 1`). Pane defaults **662,927 (-93.7%)**, 458,756 (-69.6%) and 450,370 (-68.2%), and 617,999, 444,444 and 437,458 at `--prune-after 1`; `--no-pane-defaults --lever prerun_checks` 4,236,658 (-60.0%), 1,248,888 (-17.1%) and 1,147,274 (-19.0%); the view and the stubs without levers 13 and 14 743,305, 534,764 and 516,419 (698,345, 520,422 and 503,481 at `--prune-after 1`); the OpenAI pane, rules R and M, **276,302** over 16 rounds, **244,304** over 21 and **242,465** over 20, unchanged (232,553, 230,479 and 229,767 at `--prune-after 1`; without levers 13 and 14 307,303, 285,346 and 277,558), margins under 300,000 of 18.6% and 19.2%; the fixtures' own pane, rule R alone, 486,892, 381,557 and 388,625, unchanged. The big fixture's follow-up round: **19,915** requested against 346,313 recorded, unchanged (19,229 at `--prune-after 1`, 24,741 without levers 13 and 14 and 24,049 without them at `--prune-after 1`; with lever 14 alone off, 22,807 and 22,121, the pane defaults 665,819 and 620,891). The percentages are against the new recorded totals, so they read lower for nearly the same requested figures. Every run: pass A within 1%, no recorded finding lost, none not replayable (absolute), none reclassified and none narrowed; 62, 7 and 5 added (none with `--no-pane-defaults`). The real recordings (section 10), replayed as recorded: none lost, none added; 26, 3 and 2 findings narrowed (20, 2 and 1 `rms.grouping.all_features_in_a_group`, 3, 1 and 1 `rms.sketches.fully_defined`, 3, 0 and 0 `rms.sketches.one_sketch_per_feature`), 283, 29 and 21 locations removed; replayed plus not replayable the recorded count (88 + 11 = 99, 10 + 3 = 13 and 6 + 1 = 7); a zero residual on every round (40, 38 and 36 main rounds and one presentation round each). 008 T128's and T129's carried-finding comparisons, re-read against the regenerated fixtures: none of the three holds a carried finding, and neither does any recording, so neither moves a figure. Pinned again with the reasons: `test_replay_fixtures.py`'s recorded total, follow-up round and the part check's 583 rows; `test_replay_recorded_runs.py`'s narrowed findings and locations removed, by check; every strict `T134_PENDING` mark removed |

## 10. Real recordings

`reviewer/tests/integration/test_replay_recorded_runs.py` (skipped when the recordings are
absent - since 2026-09-24, when the owner's mapping of section 8 or a folder it names is; *landed
without* the
`integration` marker, which `tests/conftest.py` skips whole when no native evidence package is
present - as it is not on the machine holding the recordings) checks pass A within 1% on every
round of the three recorded reviews (observed at most 0.023%) and that replayed plus
not-replayable findings equal the recorded key set (the big assembly's: 88 + 11 = 99).

*Amended 2026-09-25 (owner decision 23A):* the finding check reads section 5's narrowed outcome.
None lost and none added, and the replayed plus not-replayable findings are still the recorded
count, each narrowed recorded finding matched to a replayed one: the recorded key set, less what
the current type table narrowed. The test pins the narrowed findings of each recording by check
and count, with the locations removed.

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
