# Research: Checks-First Review and the Token Budget

**Feature**: `008-checks-first-review` | **Date**: 2026-09-23 | **Plan**: [plan.md](plan.md)

Phase 0 output from: the spec; the owner's decisions of 2026-09-22 recorded in
`docs/roadmap-2026-09-22.md`; the pilot workstation's evening packet
(`docs/pane-findings-2026-09-20-review-gui.md`) and its recorded run folders; and three design
passes run on 2026-09-22 and 2026-09-23 against commit `43e9b15`, each by an analyst who opened
the code and wrote down facts with `path:line`, decisions with rejected alternatives, file
changes, tests and the tests that go red by design:

| Pass | Covered | Called below |
|---|---|---|
| Replay | User Story 1 (the replay), User Story 5 (cost), the fixtures, the tokenizer | the replay pass |
| View | User Story 3 (the model's view, pruning, the stored results), parallel calls, the settings | the view pass |
| Checks | User Story 2 (checks first, live interference, the re-call guard, the folded group), the answer batch | the checks pass |

The three passes were written independently and overlap in six places (who owns the pane
defaults, what the command line defaults to, the digest shape, the serializer, where stubs are
priced, the fixtures' standards profile) and disagree in two (SC-003, and the usage line's
wording). Every overlap is reconciled below in a decision marked **Reconciled**, with the
reason; no decision of any pass is dropped silently - a superseded one is named with what
replaced it.

Where this document says **VERIFIED**, a design pass opened the file at `43e9b15` and, where the
claim is behavioural, ran it; this pass re-opened on 2026-09-23 every fact a reconciliation
turns on (listed in R3). Main moved to `5530e22` during this pass (feature 009's first three
increments and the 009 and 010 spec packages); `git diff 43e9b15 5530e22 -- reviewer/` is empty, so
every `reviewer/` line reference holds, and the one page reference that moved is noted in R2.46. Numbers read off the recorded runs were computed on 2026-09-23 from
the dumps at `%LOCALAPPDATA%\SwReview\handover\2026-09-20-gui\dumps`, which stay on the
development machine and never enter this repository. Line numbers drift; every task
re-verifies before editing.

---

## R1. What the sources are, and what is normative

| Source | What it is | Authority here |
|---|---|---|
| `spec.md` | Five user stories, FR-001 to FR-029, SC-001 to SC-010 | Normative for what is built; amended in the places R4 names, each with its reason |
| `docs/roadmap-2026-09-22.md` | The owner's four decisions of 2026-09-22 and the feature order | Normative for the decisions: all four changes pane defaults gated by the replay; one folded modelling-practice group; the model reads counts only |
| The three design passes | Facts, decisions, file changes, tests, red-by-design lists | Normative for how each change is made, as reconciled here |
| The constitution | Principles I to VI and the technical constraints | The gate every decision is checked against in `plan.md` |
| The recorded dumps | Four review folders and two check folders of 2026-09-20 | Evidence only; the fixtures are shaped like them, never copied |

The recorded runs, as measured on 2026-09-23:

| Run | Usage rounds | Input tokens | Cached | Uncached | Tool calls | Findings | Answers |
|---|---|---|---|---|---|---|---|
| `20260920-192014-830-02342` | 41 (turn 0: 40, of which the last is the presentation request; turn 1: 1) | 12,395,545 (12,393,671 without the presentation request) | 11,988,157 | 407,388 | 38 | 99 | 0 |
| `20260920-191314-810-11249` | 39 | 1,569,692 | 1,501,667 | 68,025 | 36 | 13 | 0 |
| `20260920-190840-810-11249` | 37 | 1,464,288 | 1,413,047 | 51,241 | 32 | 7 | 0 |
| `20260920-190758-810-11249` | 2 (stopped) | 19,528 | 9,656 | 9,872 | 2 | 0 | 0 |

No recording carries an answered evidence request, so the answer paths of the replay are proven
on scripted recordings only (R2.2, R2.42).

## R2. Decisions, alternatives and rationale

### The replay (User Story 1)

#### R2.1 One command in the benchmark group, two modules behind it

**Decision**: `swreview benchmark replay RUN_DIR`, a thin shell in `cli.py`. The logic lives in
`benchmark/recording.py` (reads a run folder into a `Recording`) and `benchmark/replay.py`
(drives the review, counts tokens, compares findings, builds a pydantic `ReplayReport`). Exit 0;
exit 1 for a refusal (one sentence) or for any lost finding (after printing); exit 2 for a usage
error. `--json` prints the report model and nothing else.

**Why**: VERIFIED the benchmark sub-app's conventions - a thin shell, one-line errors through
`_errors_as_exit_1` (`cli.py:380-392`), `--json` through `_emit` (`:395-401`), and exit 1 after
printing when a gate fails (`:2301-2302`) - and that the benchmark group already owns offline
measurement (`benchmark_app`, `:171`). A separate reader can be tested against the refusal cases
alone.

**Alternatives**: a top-level command (rejected: the benchmark group owns measurement); one
module (rejected: too large, and the reader's refusals could not be tested alone).

#### R2.2 What a recording is, and how it is read

**Decision**: `read_recording(run_dir)` refuses a missing `session.json` through
`run_folder_session` (which already names a benchmark run root in one sentence), and a missing
`events.jsonl`, a log with no `usage` event, or a missing `package.json` each with one sentence
naming what is missing. Rounds are rebuilt as each `usage` event plus the `tool.started` events
that follow it. A `usage` event after the turn's `text.done` and before `turn.ended` is a
**presentation** round, carried at its recorded size and labelled. A follow-up turn's user text
is sized from the recorded growth. An answer turn is replayed from its `evidence.answered`
event. A dangling `tool.started` in a stopped turn is not replayed. Setup steps written before
the first `usage` event (a pre-run in the recording) are left out of the script. Each recorded
finding is tied to its producing step by the `tool.started`/`tool.finished` bracket its
`finding` event falls in. The replay writes nothing into the run folder.

**Why**: VERIFIED these are the only markers the recordings carry: every review dump holds
`attention.json`, `events.jsonl`, `package.json`, `report.md` and `session.json`, and the
`-standards`/`-check` folders hold `check.json` and no `events.jsonl`; each adapter emits a
round's `usage` before it runs that round's calls (`openai_provider.py:390-400`,
`fake.py:246-255`); the presentation request's `round_index` follows on from the main rounds
(`runner.py:745-756`, `events.py:162-164`), so only position tells it apart - true in all four
dumps; `evidence.answered` carries `request_id` and `answer` (`runner.py:720`); the 190758 dump
ends `stopped` with a `tool.started` and no `tool.finished`. `tool_result_ids` is empty on all
nine interference and hole findings of the 830 run, so the event bracket is the only tie from a
finding to its step, and it ties all 99.

**Alternatives**: telling presentation rounds apart by `round_index` (rejected: it follows on);
by input below half the maximum (rejected: breaks once pruning can shrink input).

**Edge named for the contract**: a turn that ends with no text would have its presentation
round counted as a main round; `contracts/replay.md` states it.

#### R2.3 Rounds in the scripted provider, not a second provider

**Decision**: `ScriptedRound(calls, usage=None)` and an optional `ScriptedTurn.rounds`. With
`rounds` set, each round is one assistant message holding its calls, followed by its tool
messages, with one usage event per round (`round_index` 0..n) when usage is given; the closing
text uses `turn.usage`. Setting both `tool_calls` and `rounds` raises `ValueError`. Existing
behaviour is unchanged.

**Why**: VERIFIED `FakeProvider` plays one `ScriptedTurn` per `run()` and emits one usage event
per turn, and `one_round` puts every call of the turn into one assistant message
(`fake.py:90-124`, `:153-172`, `:228-274`), so it cannot replay a turn whose recorded rounds have
different groupings. One optional field keeps every existing fake test green.

**Alternatives**: a separate `ReplayProvider` (rejected: a second copy of `fake.run` and
`_append_round`); `one_round` per turn (rejected: all or nothing).

#### R2.4 Two passes, and a class for every recorded call

**Decision**: pass A replays with the recording's own settings (`session.efficiency`, and
`session.model_view`, absent meaning off) and measures fidelity; pass B replays with the
requested settings and measures the change. Each recorded model call is classified from pass A:
**reproduced** (same status and same `summarize_result`), **changed** (same status, different
summary, no estimated call before it: replayed at the current code's size and listed),
**estimated** (a tool not offered offline or unknown to the current code, a status mismatch, or
a divergence after an estimated call), **carried** (the presentation round). Pass B reuses the
classification. User Story 2 adds **answered_from_checks** (R2.19) and User Story 3 adds
**stored** (R2.39).

**Why**: keeps the gaps of the offline replay apart from the changes being priced. VERIFIED that
divergence after an estimated call is exactly the `bridge_interference` case: the live call
added its rows to the in-memory package only (`tools/bridge.py:438-450`), the run folder's
package has 0 interferences, and `list_interferences` and `get_package_summary` read
`context.ir.interferences` (`tools/query.py:78, 600`), so a simple offline replay missed the 1%
target (2.38% worst round on 830, 6.57% on 191314) until that rule was added. It needs no
hand-kept list of bridge-dependent tools.

**Alternatives**: one pass (rejected: a checks-first digest would read as a divergence); a
fixed list of bridge-dependent tools (rejected: drifts as tools are added).

#### R2.5 The accounting model, and the twelve framing tokens

**Decision**: `replay_in[t,k] = R0 + dP + (recorded output tokens before (t,k)) + (recorded
user-message growth) + sum over the results visible at (t,k) of (T(text of the result as the
model reads it) + 12)`. `R0` is the recorded input of the first round; `dP` is
`T(system + tool-schema JSON + opening message)` under pass B minus the same under pass A; `T` is
the one tokenizer (R2.7); `FRAMING_TOKENS = 12` is named in code with its measurement. Every
round prints three numbers - recorded, pass A, pass B - with its class.

**Why**: VERIFIED the provider bills a constant wrapper per tool result: recorded growth minus
the replayed `json.dumps` count is 11 to 14 tokens (median 12) on all 87 replayable results
across the three OpenAI runs; with 12 framing tokens and the divergence rule, the replay matches
every recorded round within 0.023% (worst: 0.008% on 830, 0.015% on 191314, 0.023% on 190840)
against the 1% target. The provider renders tool schemas and reasoning items in ways the replay
cannot see - counting the literal request is about 20% high at round 0 (13,151 counted against
11,006 billed) - so the prefix is calibrated to the recording and only results are counted
exactly. Output tokens are unknowable offline, so input is priced with output held at the
recorded values.

#### R2.6 Sizing a call the replay cannot reproduce

**Decision**: an estimated call's size is the recorded growth: the next main round's input,
minus this round's input, minus this round's output, minus the other calls in the round (each
with framing), minus framing. Several estimated calls in one round share the rest equally. When
the growth cannot be observed (the last round of a stopped, truncated or max-steps turn, or a
negative growth in a recording made with pruning on), the size is the tokens of the recorded
200-character summary, labelled **lower bound**.

**Why**: FR-004 and User Story 1 scenario 2. It is exact for serial rounds (the check
reproduces the main line within 13 tokens). User Story 3's stored results remove most lower
bounds for recordings made after this feature (R2.39).

**Alternatives**: the summary size always (rejected: understates up to 200 times); refusing the
replay (rejected: the spec says estimate and label).

#### R2.7 One tokenizer, fetched once into a per-user cache, no network at run time

**Decision** (amended 2026-09-23; the design pass had proposed vendoring): `tiktoken>=0.9,<1`
becomes a runtime dependency. The `o200k_base` vocabulary file is **not** committed. It lives in a
per-user cache (`SWREVIEW_TOKENIZER_DIR`, else `%LOCALAPPDATA%\SwReview\tokenizer` on Windows,
else `$XDG_CACHE_HOME/swreview/tokenizer` or `~/.cache/swreview/tokenizer`) under its tiktoken
cache-key name, put there once by `swreview tokenizer fetch` (tiktoken's own loader into a
temporary folder, then our own sha256 check, then a copy; `--from <file>` for a machine without
network). A new `reviewer/src/swreview/tokens.py` checks the file's sha256 itself, then calls
`tiktoken.get_encoding` with `TIKTOKEN_CACHE_DIR` set to that folder and restored afterwards; it
exposes `TOKENIZER_NAME = "o200k_base"`, `tokenizer_dir()`, `count_tokens(text)` and
`TokenizerUnavailable`, whose message names the fetch command. `update-workstation.ps1` and the
reviewer CI workflow run the fetch; tests needing exact counts skip with the fetch command in the
reason unless `SWREVIEW_REQUIRE_TOKENIZER=1`, which CI and the update script set, so a missing file
fails there instead of passing silently.

**Why**: FR-026 needs token counts at run time and FR-002/FR-003 need one named tokenizer with no
network during a replay. The vocabulary is published by OpenAI with no stated redistribution
terms and this repository is public, so vendoring it was the one licensing question the design
left open; a per-user cache removes it at the cost of one fetch per machine, and the loader is the
same either way. VERIFIED: tiktoken is not a dependency today (`reviewer/pyproject.toml:8-24`); the
vocabulary was downloaded once to `%TEMP%\data-gym-cache\fb374d419588a4632f3f557e76b4b70aebbca790`
(3,613,922 bytes; its sha256 equals the `expected_hash` in `tiktoken_ext.openai_public.o200k_base`);
with `TIKTOKEN_CACHE_DIR` pointing at a folder holding it and `requests.get` patched to raise, the
encoding loads in 0.13 s and "hello world" encodes to `[24912, 2375]`; the workstation installs
every dependency and runs the update script (`update-workstation.ps1:117-120`), which is where the
one fetch goes.

**Alternatives**: vendor the file with a `-text` attribute (the design pass's proposal; rejected
for the redistribution question and 3.6 MB in every clone); let tiktoken download on first use in
the pane process (rejected: a replay must make no network call, and the pane would reach the
internet from inside SOLIDWORKS); count bytes instead of tokens (rejected: the recorded bills are
tokens, and SC-001's 1% agreement needs the same tokenizer).

#### R2.8 The finding subject key

**Decision**: `finding_subject_key(finding)` in `findings.py`: `(check, sorted component_ids,
drawing locations as (document_id, sheet, view, annotation, page) without persist_ref, sorted
Finding.inputs strings matching ENTITY_ID = ^[a-z]{3,4}:[0-9]{4,}$, configuration)`. It leaves
out `id`, `tool_result_ids` and `capture_ids`. Findings are compared as multisets. A recorded
finding is **lost** only when its producing step was reproduced, changed or (from User Story 2)
answered from checks and the replay does not produce its key; findings of estimated steps are
listed as **not replayable offline** with the step and the reason, never counted lost or kept.

**Why**: VERIFIED unique on every recorded session (99/99 on 830); `check + component_ids` gives
98/99 because two `hole.coaxiality` findings share both components and differ only by hole ids
(`checks/hole_alignment.py:78-83, 105`), and `check + title` gives 47/99; every IR entity id has
the `^<prefix>:[0-9]{4,}$` shape (`ir/models.py:367, 487, 865, 911, 933, 973, 1020, 1066,
1139`). The key is stable when checks first renumbers steps.

**Alternatives**: `runner._verdict_key` (rejected: the same hole-pair collision,
`runner.py:531-552`; that existing defect in `_reconcile_reruns` is an R5 item, not fixed here);
whole-finding equality (rejected: a changed field would read as one lost and one added).

#### R2.9 One serialization of a tool result

**Decision**: `tool_result_text(payload) -> str` in `agent/providers/__init__.py`, equal to
`json.dumps(payload)` today. `openai_provider._encode_history` (`:643`) calls it; the replay and
the step sizes call it. A Gemini recording is counted over the same text and labelled **shape
comparison**. User Story 3 gives it the keyword `compact` (R2.34).

**Why**: one place holds "what the model reads of a result", so the adapter and the replay
cannot drift. VERIFIED the OpenAI adapter serializes each result with default separators inside
a `function_call_output` item (`openai_provider.py:624-652`), and Gemini sends a
`function_response` part whose serialization is the SDK's (`gemini_provider.py:720-746`).

**Alternatives**: a text function per adapter (rejected: Gemini has none of its own).

#### R2.10 Fixtures: full size, generated, fictional - and graded with the example profile (Reconciled)

**Decision**: three full-size fixtures under `reviewer/tests/fixtures/replay/` - `big-assembly`
(shaped like 830-02342), `small-assembly-a` (191314) and `small-assembly-b` (190840) - each with
`package.json`, `session.json` and `events.jsonl`, written by a committed generator
`reviewer/tests/fixtures/replay/generate_fixtures.py` that is given the path of a recording and
never contains a recorded string. It (1) replaces the identifying package strings with fictional
tokens assigned in first-seen order, keeping length and character class, with no secret and no
output derived from content (`tests/support/scramble.py`), keeping ids, SOLIDWORKS type names,
the generic feature vocabulary and property keys; (2) applies the same map to the model's prose
in recorded arguments; (3) adds to the package the interference rows the live call had found, in
the shape FR-009 persists (the six judged groups plus fictional rows up to the recorded 113), and
answers the recording's one `bridge_interference` call during generation with those rows through
`tests/support/review_bridge.ScriptedReviewBridge`; (4) drives the current code with the
recorded call script through `FakeProvider` rounds (`tests/support/replay.record_scripted_review`),
each round's usage being the recorded usage plus the running sum of (fixture minus original)
result tokens, and carries the presentation usage; (5) checks itself before writing - the
finding-key set equals the recording's, every result of 5k tokens or more is within 5% of its
recorded tokens, and no identifying token of the recording (three characters or more, minus a
generic allowlist) remains - and refuses to write otherwise.

**Reconciled - the standards profile**: the replay pass proposed a new fictional
`reviewer/tests/fixtures/replay/standards-profile.yaml`. VERIFIED that
`tests/unit/test_standards_no_company_values.py` pins the set of files that may carry a
populated `vault_root:` line to exactly four (`PROFILE_SOURCES`, `:67-75`; census regex `:348`;
`test_only_the_documented_files_carry_a_populated_standards_profile`, `:457-465`), so a fifth
profile would turn it red, and widening a leak guard to admit a new file is the wrong direction.
The pilot workstation ran the **example** profile on 2026-09-20 (the owner's note of
2026-09-22: "the workstation still runs the EXAMPLE standards profile"), so the five recorded
standards findings were graded against `config/standards.example.yaml`, which is already in the
census set. The replay therefore grades standards with `--standards-profile
config/standards.example.yaml`, and no new profile file is added.

**Reconciled - the interference rows**: the checks pass noted that the 830 recording persisted
no rows, so its interference findings would have to be estimated or carried. The fixture package
carries the rows as FR-009 would have written them, so pass A reproduces every call but
`bridge_interference` (which stays estimated: the replay has no bridge), and pass B under checks
first judges every one of the 113 groups offline - an offline acceptance for SC-006.

**Why**: FR-007. VERIFIED the budgets are absolute and the fixed prefix of about 9.7k to 11k
tokens per round does not scale, so a scaled-down fixture cannot carry SC-002 or SC-003. The
payload shapes the fixtures keep (830 package: 1,153 features, 89 components, 26 documents, 55
mates with 110 mate entities whose persist refs total 85,868 characters, mean 781, max 1,656)
are what make the model-view savings measurable. Regenerating session and events with current
code avoids hunting names embedded in the model's prose. The convention for committed fixtures is
a generator beside them, run once from `reviewer/` (`tests/golden/fixtures/rms-part/generate_package.py:1-20`).
About 4.0 MB raw across the three.

**Alternatives**: a scaled-down fixture with ratios asserted (rejected: the prefix-to-results
ratio is not scale-invariant); scrambling the recorded session and events text in place
(rejected: names embedded in prose); a hashed denylist in the repository (rejected: names can be
guessed against the hashes).

#### R2.11 Fixture hygiene, and the owner's denylist

**Decision**: the committed hygiene test always checks structure: every document and vault path
starts with the fictional root; no string is a drive path outside it, an email address, an
http(s) URL or a copyright sign; no recorded design id (830-02342, 810-11249, 810-11281)
appears. It also reads an owner-kept denylist outside the repository,
`%LOCALAPPDATA%\SwReview\fixture-denylist.txt`, and skips that part, saying why, when the file is
absent. The generator writes that file (outside the repository) from the tokens it replaced, so
the thorough check exists on the machine that holds the recordings.

**Why**: a list of real names cannot live in a public repository, in plain text or as hashes.

**Alternatives**: a salted denylist (rejected: CI would need the secret); structural checks only
(rejected: weaker on the owner's machine).

#### R2.12 SC-001 on the real recordings is a local integration test

**Decision**: `tests/integration/test_replay_recorded_runs.py`, under the existing
`integration` marker and skipped when the dumps are absent, checks pass A within 1% on every
round of the three recorded reviews and that replayed plus not-replayable findings equal the
recorded key set (on 830: 88 replayed plus 11 not replayable - 6 interference, 5 standards
without a profile - equals 99). The fixture tests are regression locks that always run.

**Why**: only the real recordings measure fidelity independently; the fixtures' usage is derived
by the same method. FR-007 forbids committing the recordings.

### Checks first (User Story 2)

#### R2.13 Checks first is lever 5; both lever fields stay; one helper decides

**Decision**: keep all twelve `EfficiencySettings` fields. `prerun_checks` is the checks-first
switch (docstring: "Checks first, lever 5, pane default since 2026-09-22"). Add
`checks_first(efficiency) -> bool` (`prerun_checks or procedural_gate`) in `agent/settings.py`
and use it at `prerun.py:603` and at the standards-attach condition (`runner.py:1031-1032`).
`procedural_gate` stays a command-line study variant that implies checks first and opens on the
brief. `GATED_ALONE` is unchanged.

**Why**: FR-013 folds the former pre-run settings into one; FR-028 requires older sessions to
load, and removing a field breaks them (`EfficiencySettings` is `extra="forbid"`,
`settings.py:419`; every recorded pane session serializes all twelve names). VERIFIED the lever
tests and the benchmark ledger key on these names (`benchmark/compare.py:104-131`), and the two
places that repeat the "or" test are exactly the two above.

**Alternatives**: removing or renaming the fields (rejected: FR-028); a thirteenth
`checks_first` field (rejected: two flags with one meaning, and every lever-count pin red);
aliasing lever 11 to lever 5 (rejected: rewrites 007's brief contract for no US2 benefit).

#### R2.14 The pane defaults are one function of the provider (Reconciled)

**Decision**: `pane_efficiency(provider: ProviderName) -> EfficiencySettings` in
`agent/settings.py` is the one place the pane's levers are decided. User Story 2 introduces it
returning `EfficiencySettings(prerun_checks=True)`; User Story 4 adds
`parallel_tool_calls=(provider is ProviderName.OPENAI)`. User Story 3 adds `MODEL_VIEW_PANE` and
`pane_defaults(provider) -> PaneDefaults(efficiency, model_view)`, which the pane, the command
line's `--pane-defaults` and the replay's pass B all read. `EfficiencySettings`'s class defaults
and `cli.provider_factory`'s default stay off.

**Reconciled**: the checks pass proposed a constant `PANE_EFFICIENCY =
EfficiencySettings(prerun_checks=True)`; the view pass proposed a function
`pane_efficiency(provider)` "to which US2 adds its checks-first field". A constant cannot say
"parallel calls for OpenAI only": VERIFIED the lever path refuses `parallel_tool_calls` with
`--provider gemini` because Gemini already issues parallel calls (`settings.py:591-596`). The
function wins; the constant's name is not introduced.

**Why**: FR-013, FR-023 and FR-024 are pane defaults; VERIFIED the pane passes no efficiency
today, so every pane review runs every lever off (`chat/server.py:1836-1852`); and
`test_no_lever_in_pane_settings` scans only `settings.schema.json` and `UserSettings.cs`, with a
docstring that allows an adopted lever to become a code default (`:12-23`), so a code default
keeps it green unedited.

#### R2.15 The command line defaults stay off; one flag reproduces the pane (Reconciled)

**Decision**: the pane is the only surface where the four changes default on. `start_review`,
`run_review`, `swreview review` and `swreview benchmark run` default every change off. Each is
turned on explicitly on `swreview review`: `--lever prerun_checks`, `--lever
parallel_tool_calls`, `--payload-slimming`, `--history-pruning`, `--prune-after N` (which
requires pruning to be on); `--pane-defaults` turns on exactly `pane_defaults(provider)`, and
explicit options may add to it (`--prune-after 1`, or another lever, subject to `GATED_ALONE`).
One resolver in `cli.py`, `_review_settings(...)`, serves `review` and `benchmark replay`, so the
two commands cannot read the same flags differently. The replay's pass B defaults to the pane
defaults (R2.4), because pricing the pane is what it is for.

**Reconciled**: the checks pass kept the command line all-off ("the command line's way to turn
it off is its existing default", flagged for the owner); the view pass made `swreview review`
default to slimming and pruning on with `--no-...` switches ("the wording implies the command
line defaults on"). Both are defensible readings of FR-013/FR-023; mixing them - model view on,
levers off - would make `swreview review` neither the pane nor the pre-008 baseline. One rule for
all four was chosen, and the off rule because: VERIFIED `GATED_ALONE` refuses `coverage_stop`
with `prerun_checks` (`settings.py:540-543`), so a command line defaulting checks first on would
refuse `--lever coverage_stop` alone; the benchmark ledger's off arms must stay comparable with
every recorded row; a command-line `--bridge` run with checks first writes interference rows
(R2.18), which should be asked for; and none of the existing `swreview review` tests move. The
spec wording is amended to say so (R4).

**Alternatives**: the command line equal to the pane with four `--no-...` switches (rejected for
the reasons above); two different defaults on one set of flags without `--pane-defaults`
(rejected: a paid command-line run could not reproduce the pane in one flag).

#### R2.16 Live interference is the first pre-run call, through the same dispatch

**Decision**: when `context.bridge` is set, the root document is an assembly and the package has
at least two components, `prerun_checks` first calls `bridge_interference` through the same
`ToolDispatch`, once: `component_ids=[]`, `configuration=package.design.active_configuration`,
`settings=PRERUN_INTERFERENCE_SETTINGS`. Before the call it removes the package's rows for that
configuration (the rule the C# console already applies) and restores them if the call fails.
It then computes `planned_calls`, which is unchanged, so `groups_of` sees the live rows and every
group is judged by `check_interference_group`. A part root or fewer than two components gives a
not-evaluated line naming why; rows that collide with another configuration's ids give an
unresolved line with the count.

**Why**: FR-009 and SC-006 (6 of 113 groups judged on the recorded run). Going through the
dispatch keeps real steps, events, failed coverage and provenance (`prerun.py:10-17`). VERIFIED
superseding is required because the host allocates interference ids from `int:0001` on every
request (`BridgeDispatcher.cs:500`, `InterferenceRunner.cs:515`) and `bridge_interference` drops
any returned row whose id the package already holds (`tools/bridge.py:438-440`), while the pane's
Retry reuses the same `package.json`; the console's own merge replaces rows of the same
configuration and appends gaps (`PackageAppender.cs:66-110`).

**Alternatives**: calling `context.bridge.interference` directly (rejected: no step, no event,
no coverage); changing `bridge_interference`'s own merge rule (rejected: a model-facing tool and
the subset-run semantics `test_tools_bridge.py:332-337` pins); detecting only when the package
has no rows (rejected: Retry would judge stale rows).

#### R2.17 The detection settings are the recorded run's

**Decision**: `PRERUN_INTERFERENCE_SETTINGS`: `treat_coincident_as_interference=true`,
`treat_subassemblies_as_components=true`, `include_multibody=true`, `ignore_hidden=false`,
`fastener_folder_treatment="include"`. The digest line states them and every row carries them.

**Why**: VERIFIED these are exactly what the model chose on the recorded 830 run (step 12, 4.44 s,
113 groups); they reproduce the recorded groups and keep SC-010's "at least the recorded
findings" reachable, including the zero-volume F-092, F-095 and F-096. The constitution wants
the engineering judgement stated, not assumed (`tools/bridge.py:389-395`).

**Consequence stated plainly**: VERIFIED any row with a non-null volume, including 0.0 mm³, is
reported `demonstrated` (`checks/interference.py:361-376`), so judging all 113 groups reports
every zero-volume contact as a demonstrated interference until feature 010's contact rule lands
(the roadmap's next wave). Accepted for 008; an R5 item.

**Alternatives**: `coincident=false` (rejected: hides zero-volume contacts and line-to-line
press fits, and loses recorded findings); the protocol defaults, all false (rejected: reports
interferences inside sub-assemblies the recorded run never saw).

#### R2.18 The detected rows are written into the run folder's package (Reconciled)

**Decision**: a new `ir/loader.append_interference_run(source_dir, target_dir, configuration,
rows, gaps) -> Path` reads the raw `source_dir/package.json` with `json.loads` (keeping key order
and the exact `created_at` text), replaces the rows of that configuration, appends the new rows
and any gaps not already present, re-validates the text as an `EvidencePackage` that must equal
the in-memory package, writes a temporary file in `target_dir` and `os.replace`s it onto
`target_dir/package.json`. The pre-run passes `source_dir = package_dir` and
`target_dir = out`. In the pane they are the same folder, so the file is updated in place; on a
command-line run they differ, so a merged copy is written into the output folder and **the input
folder is never written**. Any `OSError` or validation mismatch leaves every file untouched and
becomes an unresolved coverage item `coverage.prerun.interference_rows` naming the error; the
review continues.

**Reconciled**: the checks pass wrote into `<package_dir>/package.json` and flagged that a
command-line `--bridge --lever prerun_checks` run would then write into an input dump folder.
Writing into the run folder - which in the pane is the package folder, and on the command line is
`--out` - honours FR-009's "the run folder's package" literally, never writes a folder the
command was only asked to read, and makes a command-line run folder replayable (the replay needs
`package.json` in `RUN_DIR`, R2.2).

**Why**: VERIFIED nothing in the product hashes `package.json` bytes (the reuse key covers
parsed parts, not interferences, `benchmark/reuse.py:18-26, 169-198`; the package index reads
`reuse_key` by regex in the first 8 KiB, `package_index.py:54-57`); a raw round trip reloads to
an equal `EvidencePackage` with key order kept, while a pydantic `save_package` round trip
changes `created_at`'s value (a 7-digit fraction truncated); the atomic replace matches
`write_attention_record` (`report/attention_record.py:124-145`); no review-path code writes
`package.json` today (`save_package` is used only by the PDF ingest and the remodel work
directory). The bytes change (CRLF to LF, .NET 17-digit floats to Python's repr) while values and
key order are kept.

**Alternatives**: pydantic `save_package` (rejected: changes a value); a sidecar file (rejected:
contradicts FR-009 and pushes merge logic into every reader); a textual splice (rejected:
fragile); persisting inside `bridge_interference` for every call (rejected: subset-run
semantics).

#### R2.19 The re-call guard

**Decision**: a `ToolSet` wrapper `PrerunGuard` in `prerun.py`, wrapped directly around the
dispatch in `start_review` when a pre-run ran (innermost, before `CoverageStopTools`). It holds
a ledger keyed by `repeat_key(tool, arguments)`: `check_rms_part` and `check_rms_equations` map
to `(tool,)` whatever the `document_id`; `check_rms_assembly` and `check_standards` to `(tool,)`;
`check_interference_group` to `(tool, group_key)`; `bridge_interference` to
`(tool, configuration, sorted-JSON settings)` only when `component_ids` is empty. Only
successful pre-run calls enter the ledger. A hit records one real step through
`registry.record_call` (status ok, no coverage) and returns `{status: "already_run", ran_at_step,
note, outcome}`, where `outcome` is `check_digest(recorded payload, counts_only=<family is
folded>)` for a check tool (R2.20) and `{groups, rows, configuration, settings}` for
`bridge_interference`. `PrerunCall` gains a defaulted `payload` field so the guard has the
recorded payload in memory.

**Why**: FR-012 and the "model that asks anyway" edge case. VERIFIED a second `check_rms_part`
over a graded document appends a second finding per condition (`tools/rms_checks.py:80-88`), so
a `document_id` subset must be caught; recording a step keeps `tool.started` step indices aligned
with the session (`runner.py:1049-1055`, `test_prerun_same_session.py:137-169`); none of the
guarded tools takes an input an evidence answer could supply, so answering a repeat with the
recorded outcome loses nothing on an answer turn. `CoverageStopTools` and `StoppableTools`
already use the wrapper pattern. With checks first off there is no wrapper.

**Alternatives**: a ledger on `ToolContext` checked in `RecordedTool.call` (rejected: every tool
path - MCP chat, check folders - would carry it, and it forces a prerun/registry import cycle);
hashing the full argument set (rejected: misses `check_rms_part(document_id=X)`).

#### R2.20 The opening digest, and the one check digest (Reconciled)

**Decision - the opening digest (FR-011)**: lever 5's headers stay. A tool called once renders
exactly today's `PrerunCall.line()`. A tool called several times collapses to one line
(`check_interference_group x113 -> 113 ok, 113 findings`, errors named and capped). The findings
of a folded family become one counts-only line: `modelling practice: 85 findings across 7 rules
(51 demonstrated, 34 suspected); counts only - the findings are in the session and the report`.
Other `(check, status)` id lists are capped at `DIGEST_ID_CAP = 20` with `and N more`. Under
checks first the standards "no profile" family is attached and printed (US2 scenario 3). The
live-interference call has its own line and `not_evaluated_families` gains three interference
sentences (SOLIDWORKS not attached; detection failed, with the reason; rows colliding with
another configuration's ids). A successful live run that found nothing writes a `checked` item
for checklist id `interference`, scoped to the configuration, with `STATIC_SCOPE_LIMIT` and the
settings.

**Decision - the check digest (FR-018)**: one function, `check_digest(payload, *,
counts_only=False)` in a new `tools/model_view.py`, with one counting helper
`count_findings(rows) -> FindingCounts(findings, rules, by_status, by_severity)` that the opening
digest's family line also calls. Shape: `{status, findings, rules, by_status, by_severity, rows
(id, check, status, severity, title; at most 25) with rows_omitted, finding_ids (at most 200)
with finding_ids_omitted, subjects, coverage, plus the payload's other top-level scalars}`;
`counts_only` drops `rows` and `finding_ids` and their omitted counts. User Story 2 creates it
for the guard; User Story 3 adds the rest of the module and registers `check_digest` (with the
`detail` sentence naming `get_finding`) as the view of every check tool.

**Reconciled**: the checks pass answered a repeat with "the same lines the opening digest printed
for that call"; the view pass asked that "US2's answer with the recorded digest reuse
`check_digest` on the recorded step payload", and the checks pass itself listed "one renderer
shared with US3 FR-018" as a risk. A text line carries no finding ids for one call (the id lines
are aggregated per check and status), while the guard must name the finding of a repeated
`check_interference_group(K)`; the dict does both and is the shape the model reads from any
slimmed check result. So the guard answers with `check_digest`, and the opening digest keeps its
lines. The two caps differ on purpose: the opening message sits in the fixed prefix and is never
pruned, so it caps ids at 20; a tool digest is pruned after two rounds, so it caps rows at 25 and
ids at 200.

**Why**: FR-011, FR-012, FR-014 (the model reads counts only), FR-018, the thousands-of-groups
edge case and US2 scenario 3. VERIFIED: on 830 the lever-5 opening message is 2,810 tokens over
77 lines, of which the seven per-rule RMS id lines cost 431 tokens and one counts line about 41,
bringing it to about 2,420; the current digest lists every finding id per check and status with
no cap (`prerun.py:279-304`), which at 113 groups the edge case forbids; a clean live result is a
result within scope, not a gap, and `STATIC_SCOPE_LIMIT` exists for that sentence
(`checks/interference.py:79-82`).

**Alternatives**: opening on the gate brief (rejected: its judgement list is uncapped,
`prerun.py:346-354`); a new per-family renderer (rejected: more churn for the same content);
leaving the interference item open on a clean live run (rejected: finalize would record "ended
without a finding" for work that was done).

#### R2.21 The fold: one row and one report subsection per folded family

**Decision**: a new optional `ReviewSession.folded_families: list[str]` (default empty, omitted
when empty). `start_review` sets it to `["rms"]` when `checks_first(efficiency)`. `rank()` reads
it: every finding of a folded family (suppressed and decided ones included) forms one row whose
representative is the member whose own key sorts first, so a rebuild-breaker or high-severity
member lifts the group; reach is the union. `AttentionRow` gains optional `family` and
`rule_count`, omitted when absent; the row's `check` is `rms` and its title `Modelling practice:
N findings across M rules`; `start_here_lines` shows the title. The report renders a folded
family's findings once, in one `### Modelling practice: N findings across M rules` subsection
wrapped in `<details>`, after the severity sections, and leaves them out of those sections.

**Why**: FR-014 and the roadmap's single folded group. VERIFIED the existing fold already
collapses RMS findings to one row per rule id (the 830 ranking has 18 rows, 7 of them RMS,
`report/attention.py:335-377`), so "one group per rule family" can only mean one row per
`CheckFamily`, whose RMS name is `rms` (`checks/rms/registry.py:356-384`). The 830 session holds
85 RMS findings across **7** rules (51 demonstrated/medium, 34 suspected/low), not the roadmap
example's 12. Simulated on the three recordings: 830 goes from 18 to 12 rows with Start here
unchanged (five interference rows) and the family row tenth; 191314 from 10 to 4; 190840 from 7
to 2; the relative order of non-family rows is unchanged in all three. `report/attention.py` must
import no settings module (`:27-35`, `test_attention.py:914`), so the fold reads a plain session
value. `AttentionRow` already omits a missing optional field (`:248-270`), so an unfolded
session's `attention.json` keeps its bytes. Check folders never fold.

**Alternatives**: deriving the fold from `session.efficiency` (rejected: the rule duplicated
inside `attention.py`, and every feature-005 lever-5 session would silently re-fold); folding
every review (rejected: moves the owner-agreed 2026-09-18 order and its golden); per rule id
(today's behaviour); per two-segment prefix (rejected: five groups, not one).

#### R2.22 The explanation pass skips family rows

**Decision**: `ReviewRun.finalize` passes only non-family rows to `generate_explanations` and
`fill_fallbacks`.

**Why**: VERIFIED the explanation pass sends the top rows' finding payloads to the provider
(`runner.py:738-765`, `report/explanations.py:198-214`); a family row there would send RMS
detail to the model, breaking FR-014's counts only.

#### R2.23 The pre-run stays in setup, and no read timeout is added

**Decision**: the pre-run stays in `start_review`, before `POST /sessions` returns 201; the
digest is still built there.

**Why**: the smallest change; the lever tests and the replay read `run.opening_message` and
`session.steps` straight after `start_review`. Live detection took 4.44 s on 830.

**Consequence stated plainly**: VERIFIED the named-pipe transport reads with no timeout
(`bridge/client.py:150-199`; the module docstring names it a known limitation and leaves a read
timeout to an optional `pywin32` transport, `:33-36`), and the host enforces no interference
deadline, so a hung detection blocks session creation. Every failure the transport **can**
report - a closed pipe, a host error, the open circuit, a closed document - becomes a failed
coverage row and a not-evaluated line, and the review starts. A hang is not detectable without a
new transport, which is outside this feature; the spec's "or times out" is amended (R4) and the
hang is an R5 item. Running the call in a watchdog thread was considered and rejected: an
abandoned blocked read leaves the next response on the pipe for the wrong request, and the step
would be recorded after later steps.

**Alternatives**: moving the pre-run into `ReviewRun.start()` so 201 returns at once (rejected
for now: moves where the opening message is built and rewrites prerun and gate tests; Stop could
not interrupt a blocked read either). Offered to the owner in R5 if larger assemblies make setup
latency matter.

### The model's view (User Story 3)

#### R2.24 The view is computed once, beside the payload

**Decision**: the model's view is computed at `RecordedTool._finish` and carried beside the
record: `ToolCallResult` gains an optional `view: dict | None = None`; `payload` stays the full
tool return. `providers.model_payload(result)` (the view when not None, else the payload) is the
only thing the three adapters put into history content (`openai_provider.py:438`,
`gemini_provider.py:454` and `_tool_content`, `fake.py:148`).

**Why**: VERIFIED findings reach the session through `ToolContext.record_finding` while the tool
runs, never from what the model reads (`tools/context.py:219-228`, `tools/recording.py:94-121`),
so changing the view cannot change findings; `RecordedTool.call/_finish` is the single choke
point where every call becomes a `ToolCallResult` (`registry.py:423-483`); the `tool.finished`
summary is built from the full payload (`providers/__init__.py:566`); the Model check route
consumes the check envelope through the dispatch (`checks/rms/run.py:310-324`); the golden
fixtures call tool callables directly (`tests/golden/test_golden.py:1-8`). A view at the
boundary leaves every one of them byte-identical, and a view of None is today's bytes, so the
all-off replay still reproduces the recording.

**Alternatives**: rewriting the check tools' envelope into a digest (rejected: breaks the Model
check route, the goldens and MCP); making `payload` the view (rejected: summaries in events and
session would diverge); computing the view in the adapters (rejected: providers must not import
tool knowledge - `tools/registry.py` imports providers, not the reverse).

#### R2.25 One module owns the view

**Decision**: `reviewer/src/swreview/tools/model_view.py` (created in User Story 2 with
`check_digest` and `count_findings`) gains `strip_references` (drops the keys `persist_ref`,
`persist_ref_scope`, `persist_ref_scopes` and `component_persist_refs` at any depth and removes
the inline token ` persist_ref=<base64|none>` from strings with one documented regex, keeping
`scope=<id>`), `grouped_gaps` (R2.36), a name-keyed table `MODEL_VIEWS` (every check tool ->
`check_digest` plus the `detail` sentence; `list_gaps` -> `grouped_gaps`) and
`model_view(tool_name, payload) = strip_references(MODEL_VIEWS.get(tool_name, identity)(payload))`.
It never mutates its input.

**Why**: FR-015, FR-017, FR-018, FR-019. VERIFIED model-facing references sit under those four
keys and inline inside finding input strings in both the RMS and the standards formats
(`ir/models.py:212, 368-370, 488-490, …`, `exceptions.py:152-153`,
`checks/rules/results.py:159`, `checks/standards/report.py:229-239`, `tools/bridge.py:195,
372-378`), so key-only stripping would leave refs that `get_finding` would then hand the model.
One table is readable by the owner and lets a test prove no check tool escapes the digest. A
value-based sweep (no package persist-ref value appears in any view) is stronger than a key-based
one. Measured on 830 with a prototype: `check_rms_part` view 738 tokens against 204,857;
`list_mates` 4,402 against 55,464; `list_gaps` 6,249 against 15,582.

**Alternatives**: per-tool view callables on `ToolSpec` (rejected: the spec cache is
process-global and keyed by function, `registry.py:338-351`); key-only stripping (rejected
above).

#### R2.26 `get_finding` is offered only with payload slimming

**Decision**: a new tool `get_finding(finding_id)` in `tools/session.py`, reading
`ToolContext.session.findings` and returning `{"finding": as_json(finding)}`; an unknown id is an
`unknown_id` error naming it. It is appended in `ToolRegistry._offered` when payload slimming is
on (like `compact_query`, `registry.py:770-771`), never in `MCP_TOOL_FUNCTIONS` or
`CliProfileWriter.EnabledTools`.

**Why**: with slimming off the model already has full findings, and the tool array stays
byte-identical (32 tools; the `test_tool_payload.py` pins at `:299-330` untouched; the all-off
prefix exact). General chat has no session (`mcp/server.py:1-35`). Always registering it would
add about 100 tokens to every all-off request, about 0.9% of round 0 against SC-001's 1%.

**Consequence stated plainly**: beyond 200 findings in one check call, the omitted ids cannot be
fetched because the model never saw them; the digest states the omitted count (FR-018's
"capped with the omitted count stated").

#### R2.27 The bridge tools take entity ids, always

**Decision**: `bridge_capture(entity_id, view)` and `bridge_measure(entity_id_a, entity_id_b)`
take package entity ids whatever the slimming setting. A new pure resolver
`resolve_entity_ref(package, entity_id) -> (persist_ref, scope)` in `tools/refs.py` searches
components, features, mates, holes, threads, fasteners, faces, bodies, cut-list items and
captures, and refuses an unknown id, an entity whose reference is null, and an id found under two
kinds with different references, each with a sentence naming the id. `bridge_measure`'s payload
names `entity_id_a`/`entity_id_b` instead of echoing references; `capture_through_bridge` takes a
`subject` label so its error text names the id. Only the Args lines of both docstrings change.

**Why**: FR-016. VERIFIED only these two tools take a reference from the model
(`tools/bridge.py:332-378`), and `request_capture` already resolves an entity id server-side for
three kinds (`tools/session.py:386-436`); the docstring no-loss pin covers description and notes,
not Args (`test_docstring_split.py:49-51, 209-231, 603-615`). One signature is explicit; a
flag-dependent schema is not.

**Alternatives**: accepting either a reference or an id (rejected: FR-016 requires an
unresolvable id to be an error naming it); a resolver on `ToolContext` (rejected: a pure function
over the package is testable without a context); moving `request_capture` onto the resolver now
(rejected: widens the kinds it captures; an R5 follow-up).

#### R2.28 The development probe uses interference

**Decision**: the pane's development probe (`chat/server.py:521-544`) switches from
`bridge_measure` on made-up references to `bridge_interference(component_ids=[],
configuration="probe", settings=<all five stated>)`.

**Why**: with entity ids, `probe-N` would be refused before reaching the bridge, so
`--fail-bridge` would no longer exercise forced failures and the circuit breaker;
`bridge_interference` validates only listed component ids, so an empty list reaches the bridge in
any package. Its configuration `probe` never matches the guard's key (R2.19).

#### R2.29 Pruning is a pure per-request view

**Decision**: `reviewer/src/swreview/agent/providers/pruning.py`: `prune_history(messages,
prune_after_rounds) -> list[dict]` returns a new list where a `tool` message is replaced by
`result_stub(...)` when (a) its age >= N, age being the number of assistant messages after it;
(b) it is not an error; (c) its compact stub is shorter than its compact content; and (d) its
arguments are known by position from the preceding assistant message's `tool_calls`. User
messages (the opening digest, the engineer's text, the answer message) and assistant messages are
never touched; the input is never mutated. OpenAI applies it before `_encode_history` every
round; Gemini rebuilds `contents = _to_contents(prune_history(history, N))` at the top of every
round instead of appending incrementally. `runner.py:851` is unchanged.

**Why**: FR-020 and FR-022: one helper, both adapters, and between turns for free, because each
turn's first request is built by the adapter from the same neutral history. VERIFIED the runner's
history is append-only and pinned so (`test_prefix_stability.py:232-248`), the OpenAI adapter
re-encodes the whole history every round and never prunes (`openai_provider.py:361, 433-439, 464,
624-648`), Gemini builds `contents` once per turn and appends (`gemini_provider.py:389-459`),
and Gemini sends empty call ids (`:19-21`), which is why arguments are mapped by position. Tiny
session-tool results (`request_evidence`, `mark_coverage`) have stubs larger than themselves and
stay in full.

**Alternatives**: mutating `ReviewRun.messages` (rejected: breaks the append-only invariant and
double-counts age); a round counter on each tool message (rejected: adapter counters reset per
turn, `openai_provider.py:364`); pruning Gemini's `contents` directly (rejected: two
implementations); rebuilding Gemini only when pruning is on (rejected: two code paths; a
characterization test and the existing cross-turn thought-signature test,
`test_gemini_provider.py:786-809`, prove the rebuild equivalent).

#### R2.30 The stub

**Decision**: `{pruned: "shown in full earlier; summarised here", tool, arguments (as the model
sent them), counts: {key: len} for each top-level list, ids: the id of every object in the
top-level lists plus finding_ids when present, capped at 20 with ids_omitted, refetch: "call
<tool> again with these arguments to read it in full" + " or get_finding(<id>) for one finding"
when the content carries finding ids}`. No step number: the model cannot read files.

**Why**: FR-020 names exactly tool, arguments, counts, returned ids and how to fetch; Principle I
wants the omission said, which `pruned`, `ids_omitted` and `refetch` do. Measured 48 to 159
tokens on the recorded run. Deterministic from `(name, arguments, content)`, so the cached prefix
up to the previous result survives (the stub-determinism edge case).

#### R2.31 Every result is stored in the run folder

**Decision**: `SessionSink.record` writes `<run_dir>/tool-results/step-<index>.json` as
`{session_id, step, tool, arguments, status, payload}` (`indent=2`, `ensure_ascii=False`,
trailing newline) for every recorded call - ok, error, withheld, unknown name, pre-run, guard
answer - whatever the settings. `ToolCallRecord` gains `payload`; `ToolContext` gains
`tool_results_dir`, set only by `start_review` to `out/"tool-results"`. An `OSError` becomes a
`failed` coverage item naming the step and never raises. The pane rotates `tool-results/` to
`tool-results.<n>` beside `session.<n>.json`, and `_next_free_index` considers it.

**Why**: FR-021 and SC-008 say every result of every review; `SessionSink` decides the step index
(`registry.py:310-320`), so the file name and the step cannot disagree; check runs and MCP never
set the folder, so their folder-listing tests stay green (`test_rms_run.py:279`,
`test_cli.py:1996`). The `session_id` makes stale files from a reused command-line `--out`
folder detectable. The files also give the replay real payloads for calls it cannot reproduce
(R2.39). VERIFIED two pane-route tests snapshot a run folder with `read_bytes()` on every entry
(`test_chat_timing_route.py:73-74`, `test_chat_attention_route.py:91-92`), so a sub-folder makes
them raise; they are rewritten as a recursive walk keyed by relative path (stronger, not looser).

**Alternatives**: writing only with pruning on (rejected: the spec is unconditional); writing in
`RecordedTool` (rejected: withheld and unknown-name results would be missed); folders named by
session id (rejected: the spec names the step).

#### R2.32 Model-view settings are settings, not levers

**Decision**: a frozen, `extra="forbid"` `ModelViewSettings(payload_slimming: bool,
history_pruning: bool, prune_after_rounds: int = Field(2, ge=1))` in `agent/settings.py`, no
defaults on the two booleans, with named values `MODEL_VIEW_OFF` and `MODEL_VIEW_PANE`; recorded
as the optional `ReviewSession.model_view` (FR-028). `start_review(model_view=None)` records
`MODEL_VIEW_OFF`, following the codebase's "None predates the feature" convention.

**Why**: VERIFIED `EfficiencySettings` is twelve booleans resolved from `--lever` as
`{name: True}` (`settings.py:400-459, 608`), so an integer cannot be a lever, and the count 12 and
the names are pinned (`test_efficiency_settings.py:92-96`, `test_no_lever_in_pane_settings.py:45-49`).
Not being levers keeps `LEVER_NAMES` at twelve and the study machinery untouched. `benchmark
run` keeps `MODEL_VIEW_OFF`: its ledger rows were all recorded with today's view.

**Superseded from the view pass**: the command-line default of `MODEL_VIEW_PANE` and the
`--no-payload-slimming`/`--no-history-pruning` switches, replaced by R2.15's single rule.

#### R2.33 The adapters learn the settings once

**Decision**: an optional port extension `ModelViewAware.use_model_view(settings)` beside
`PromptCacheAware` (`providers/__init__.py:461-479`), called once by `start_review`; OpenAI
stores the prune age (or None) and compact; Gemini stores the prune age; the fake does not
implement it. A test asserts both real adapters implement it.

**Why**: settings are read once per session where they are recorded; the port's `run()` does not
change (`test_parallel_tool_calls.py:161-165` pins that style); test doubles are unaffected.
VERIFIED the pane's injected provider factory takes one argument (`chat/server.py:1831`), so
constructor parameters would decide the recorded settings somewhere else.

#### R2.34 Compact JSON on OpenAI through the one serializer (Reconciled)

**Decision**: `tool_result_text(payload, *, compact=False)` uses `separators=(",", ":")` when
compact; `_encode_history(messages, *, compact=False)` passes it through for
`function_call_output` items. Gemini's SDK serializes `FunctionResponse` itself; nothing changes
there.

**Reconciled**: the replay pass introduced `tool_result_text` as the one serialization; the view
pass put `compact` on `_encode_history` with its own `json.dumps` call. Two serializations of one
thing would let the adapter and the replay drift, which is exactly what R2.9 exists to prevent;
the keyword lives on the one function.

**Why**: FR-017; separators alone measured -8.5% on 830; the keyword-only default keeps
`test_prefix_stability.py:147` and the all-off bytes unchanged.

#### R2.35 Lever 7's stop sentence reaches the view

**Decision**: `CoverageStopTools` (`runner.py:509-525`) annotates `view` as well as `payload` when
a view is present.

**Why**: VERIFIED lever 7 annotates `result.payload` after the call; under slimming the sentence
would silently stop reaching the model.

#### R2.36 Gap rows grouped by reason template

**Decision**: in the view only, `grouped_gaps` keys rows by `(kind, entity_kind, reason with
single-quoted substrings replaced by "…")`; each group is `{kind, entity_kind, reason (the first
row's full text), rows: n, entity_ids: first 5, entity_ids_omitted}`, in first-appearance order,
under `{groups, rows}`.

**Why**: FR-019; measured 15,582 to 6,249 tokens on 830; the model still reads one verbatim reason
per group; MCP and the package keep every row. Grouping by literal reason groups little, because
reasons embed document names.

#### R2.37 The default prune age is two rounds

**Decision**: `prune_after_rounds = 2` in `MODEL_VIEW_PANE`, as the spec's assumption records;
`--prune-after 1` exists and the replay prints both for the owner.

**Why**: the spec chose two as the safer. VERIFIED under the prompt-cache model a result is billed
uncached once per round it sits in front of a changed stub, so N=2 bills each result uncached
twice and N=1 once (830 serial with slimming: 137,065 uncached at N=2 against 77,577 at N=1;
totals 0.72M against 0.67M). Which to prefer is the owner's call (R5).

#### R2.38 MCP general chat is not slimmed in this feature

**Decision**: `mcp/server.py` payloads are unchanged.

**Why**: 008 prices the review; MCP output is feature 002's contract and has no session for
`get_finding`. A command-line model can still see persist references while the bridge tools now
want ids and will get an error naming the id; R5 follow-up.

#### R2.39 The replay prices views and stubs with the same functions, and reads stored results (Reconciled)

**Decision**: the replay reconstructs each round's request from the scripted review's own neutral
history (`ReviewRun.messages` truncated at that round), applies `prune_history(..., N)` when the
pass's settings prune, and counts `tool_result_text(model_payload, compact=payload_slimming) +
FRAMING_TOKENS` for each visible tool message. Pass A reads the recording's `session.model_view`
(absent = off). For a call it cannot reproduce, when the run folder holds
`tool-results/step-<n>.json` whose `session_id` matches, the replay sizes the call from that
stored payload as the recorded settings would have shown it and classes it **stored**, not
estimated.

**Reconciled**: the replay pass's accounting summed "results visible at (t,k)" without saying
how visibility is decided once pruning exists; the view pass asked that the replay "apply
`prune_history` and `_encode_history(compact=...)`" and "may read tool-results files". Using the
same two functions the adapters use is the only way the replay's stubs and ages equal what the
adapters send. Stored results remove the lower-bound estimates for any recording made after this
feature, including those made with pruning on, where growth can be negative (R2.6).

### Asking and answering (User Story 4)

#### R2.40 Parallel tool calls: the pane default for OpenAI; the dispatch stays serial

**Decision**: `pane_efficiency(provider)` sets `parallel_tool_calls = provider is OPENAI`
(R2.14); `build_provider` passes it to `provider_factory` at construction, and
`ChatServer._start_review` passes the same settings to `start_review`, so the session records
what the adapter was built with. Local dispatch stays serial in response order; no loop change.

**Why**: FR-024. VERIFIED lever 6 reaches the adapter at construction and nowhere else
(`cli.py:262-301`, `test_parallel_tool_calls.py:227-235`); both adapters already dispatch a
response's calls serially in response order (`openai_provider.py:433-438`,
`gemini_provider.py:445-447`), which keeps SOLIDWORKS calls one at a time into the one STA worker
(`bridge/client.py:4, 433-434`); the step recorder and finding-id allocation are not thread-safe,
so a pooled dispatch is out. Gemini records False because the lever path refuses that arm, and
the session's provider says which provider did what. VERIFIED the lever-6 study on the one real
design: -67.5% tokens, same findings (`docs/llm-efficiency-options.md`, "Measurements outside the
ledger").

**Alternatives**: flipping the class default (rejected: every CLI arm and the default pins);
setting the flag after construction (rejected: contradicts the pinned construction-time design);
thread-pooled dispatch (rejected above).

#### R2.41 The answer batch

**Decision**: `ReviewRun.answer_evidence_batch(answers)` with one shared validator
`answerable()` raising `UnknownEvidenceRequestError` or `EvidenceAlreadyAnsweredError` (both
`ValueError` subclasses keeping today's message text); duplicate ids in one submission are
refused; everything is validated before anything changes; then each request is marked answered
with one `evidence.answered` event in submission order, followed by one `_ask`, one
`_reconcile_reruns` and one finalize. A batch of one sends `ANSWER_MESSAGE` byte for byte; more
than one sends `ANSWERS_MESSAGE` with a `- ER-00n: answer` line each. `answer_evidence` delegates
to the batch. A new route `POST /sessions/{chat_id}/evidence` with `{answers: [{request_id,
answer}]}`: shape first (400 `InvalidRequest` naming the index or the duplicate id), then idle
(409 `TurnRunning` or `SessionFailed`), then ids (404 `UnknownEvidenceRequest` or 409
`AlreadyAnswered` naming the first failing id); 202 on success. The single-answer route stays and
uses the same validator.

**Why**: FR-025, SC-005 and the one-bad-id edge case. VERIFIED the single route and the runner
each carry their own copy of the same lookup (`chat/server.py:1216-1225`, `runner.py:708-715`), so
one validator also removes an existing duplicate. No new event type; the add-in's proxy forwards
any `__backend/<path>` (`docs/pane-backend-proxy.md:142`), so no add-in change; the page wiring is
feature 009's.

**Alternatives**: looping the single route (rejected: N turns); server-side queueing (rejected:
the contract refuses with 409, `chat-api.md:50`); accepting the valid part (rejected: FR-025).

#### R2.42 The replay reads a batched answer as one resumed turn

**Decision**: consecutive `evidence.answered` events before one resumed turn are replayed through
`answer_evidence_batch`; a single one through `answer_evidence`.

**Why**: a recording made after this feature carries batches; replaying them as N turns would
over-price every answer. No recording of 2026-09-20 carries an answer (R1), so this is proven on
scripted recordings.

#### R2.43 SC-003 and the regrouped estimate (Reconciled)

**Decision**: the replay keeps FR-001's recorded rounds for its strict figure, and from User Story
4 also prints a labelled **regrouped estimate** built by two deterministic rules applied to pass
B's script: rule R, when pass B runs checks first, drops every recorded model call classed
`answered_from_checks` (the digest already told the model); rule M, when pass B has parallel
calls, merges each run of consecutive recorded rounds of one turn whose calls all name the same
tool (none estimated or carried) into one round holding those calls in recorded order. A round
left empty disappears. The label says what it assumes: "the model does not repeat a check the
digest reported, and batches consecutive calls to one tool". **SC-003 is gated on the regrouped
estimate** (under 0.3M for each small fixture) with the strict figure required below the recorded
total, and SC-010 measures real behaviour at the next sitting.

**Reconciled**: the replay pass found SC-003 unreachable under recorded rounds - modelled defaults
give 0.56M to 0.59M for each 810 run, because the fixed prefix of about 9.66k tokens times 36 to
38 recorded rounds is 350k to 367k on its own - and offered (a) amend SC-003, (b) a labelled
regrouped estimate, (c) leave it red. The view pass reached the same conclusion from its own
model (0.45M to 0.51M with slimming and pruning alone; the difference is the checks-first digest
riding in the prefix of every round, about 2.4k tokens times 38). The owner's gate (the roadmap:
"the same findings and a token cut on every recorded run") is met by the strict figure; the 0.3M
target is the owner's, and the parallel-call study that justified adopting lever 6 measured the
round collapse rule M models (35 rounds to 11 on the real design). Keeping the target and gating
it on a labelled, deterministic model of that behaviour honours both, with the assumption printed
next to the number. The spec is amended (R4).

**Consequence stated plainly**: the replay pass modelled 0.29M to 0.30M for the regrouped
estimate - a thin margin. If the acceptance is red after User Story 4, the replay's `--prune-after
1` figure (cheaper by R2.37's measurement) is the first thing the owner is shown; an R5 item.

**Alternatives**: amending SC-003 to the strict figure's reach (rejected: gives up the owner's
target without trying the behaviour the owner adopted); regrouping silently inside FR-001's figure
(rejected: the gate would rest on an unstated assumption).

### Cost (User Story 5)

#### R2.44 Step sizes at the one recording funnel

**Decision**: `result_bytes: int | None` and `result_tokens: int | None` on `InvestigationStep`
and `ToolCallRecord`; `record_call` measures `len(tool_result_text(payload).encode("utf-8"))` and
`count_tokens` of the same text - the full payload in the pre-008 serialization, so sizes compare
across settings and with the recordings; a tokenizer failure records `result_tokens = None` and
never raises (tools must never raise). Omitted when null through `omit_when_null`. The contract is
edited before the model writes the fields.

**Why**: FR-026 and FR-028. VERIFIED every recorded step passes through `record_call`, which has
five callers, and `SessionSink.record` is the only `InvestigationStep` constructor in `src`
(`registry.py:253-274, 308-331, 475, 486-515, 651, 720`, `checks/rules/run.py:208`,
`mcp/server.py:232`); the chat log writes explicit fields pinned by its test
(`mcp/chat_log.py:54-62`, `test_mcp_server.py:112-121, 431`), so a new record field moves no
chat-log line; `InvestigationStep` has seven fields and the contract forbids extras
(`report/session.py:53-62`, `review-session.schema.json:108-117`), and two tests validate freshly
written sessions against it (`test_runner_provider.py:783`, `test_carry_over_guards.py:535`).
User Story 3's `ToolCallRecord.payload` and this share the seam, as the view pass asked.

**Alternatives**: sizes on the `tool.finished` event (rejected: an event contract change with no
reader in 008); measuring in `call_tool` (rejected: the step is written inside `tools.call`,
before it returns).

#### R2.45 The report: one new line and one new section, nothing renamed

**Decision**: the report keeps its existing `Cached input tokens` and `Uncached input tokens`
lines byte for byte; they already show the split. It adds `- Cache split not reported: the
provider sent no cached-input count` only when the cached total is null, and a `## Largest tool
results` table (step, tool, bytes, tokens estimated with o200k_base; the top five by tokens, then
bytes, then index) only when `session.usage` is present and at least one step carries sizes,
between `## Tokens` and the Investigation Trace.

**Why**: FR-027 without breaking FR-029. VERIFIED the Tokens section already prints both numbers,
and only when `session.usage` is present (`report/markdown.py:100-102, 613-637`); the one golden
with a Tokens section renders a committed session with the split reported and no step sizes
(`test_report_start_here/test_the_ranked_report_matches_the_golden.md:378-400`), so both goldens
keep their bytes. Check folders have no usage and gain no table.

**Alternatives**: renaming "Uncached" to "New" (rejected: moves the golden FR-029 pins); size
columns in the Investigation Trace (rejected: changes every trace).

#### R2.46 The pane's usage line uses the report's words (Reconciled)

**Decision**: `usageLine` still reads only the existing usage-event fields. It shows `<U>
uncached + <C> cached input - <T> tokens in all - <K> round trips - last round <S>` when every
round reported both input and cached input and the summed cached does not exceed the summed
input, `U` being summed input minus summed cached (the rule `TokenUsage.uncached_input_tokens`
applies, over totals); otherwise `<I> input (cache split not reported) - …`. The share
percentage is dropped. The change stays inside `usageLine`, lands last, and is rebased onto the
concurrent page work first.

**Reconciled**: the replay pass wrote the pane line as "N new + M cached" while keeping the
report's "Uncached" (its own D11, flagged for the owner). User Story 5 says the pane and the
report "say the same thing"; FR-029 forbids renaming the report's line in this feature; so the
pane takes the report's word. If the owner prefers "new", both surfaces change together in
feature 009's plain-language increment, where the golden can move (R5).

**Why**: VERIFIED the line today prints the total, a cached share, the round trips and the last
latency, pinned by C# tests (`render.js:766-791` at `43e9b15`, `:731-751` on main after feature
009's increments, its body unchanged; `ReviewPageUsageLineTests.cs:130-186`, unchanged); the
pilot's 12.4M headline hid that 407k tokens were new; all 119 recorded OpenAI rounds satisfy
probe L1's three relations (cached <= input, reasoning <= output, total = input + output), but L1
is not recorded, so `CACHED_SHARE_PUBLISHABLE` stays False and the report still calls the share
unknown - showing a percentage in the pane beside that would be a second, contradicting number.

### Cross-cutting reconciliations

#### R2.47 Tool and lever count pins

No thirteenth lever (R2.13, R2.32), so `LEVER_NAMES`, `test_efficiency_settings.py:92-96` and
`test_no_lever_in_pane_settings.py:45-49` stay as they are; only additive tests join
`test_efficiency_settings.py`. `get_finding` is conditional (R2.26), so the `TOOL_FUNCTIONS` pins
(32 tools, 34,065 bytes) stay; the bridge array pins move by design because two bridge schemas
change parameter names (R2.27: `test_tool_payload.py:309` and `:364-372`, regenerated with
`python -m tests.unit.test_tool_payload --write`, `REVIEW_BRIDGE_TOOL_COUNT` still 35), and a new
pin covers the slimmed review array (33 tools). The guard registers no tool.

#### R2.48 `review-session.schema.json` changes three times, each in lockstep

`folded_families` (User Story 2), `model_view` with `$defs.ModelViewSettings` (User Story 3), and
`InvestigationStep.result_bytes`/`result_tokens` (User Story 5). Each lands in the same task as its
model field, never in `required`: VERIFIED a contract test pins schema properties equal to model
fields (`test_usage_contracts.py:221`) and the contract rejects unknown properties
(`review-session.schema.json:7`). The three tasks touch one file and run in story order.

#### R2.49 One pane test is edited twice, deliberately

`test_chat_main.py::test_fail_bridge_makes_the_fourth_bridge_call_the_circuit_open_one`
(`:310-341`) is predicted red twice: in User Story 2, if its package qualifies for live detection,
the pre-run's `bridge_interference` takes the first forced failure (forced failures are per
transport request, `chat/server.py:612-628`); in User Story 3 the probe itself becomes
`bridge_interference` (R2.28). Each task re-derives the counts from the breaker rule and keeps the
behaviour under test - three forced failures, then the open circuit - rather than loosening it.

#### R2.50 Two pieces move to Setup

The recording reader (`benchmark/recording.py`) and the scripted review bridge
(`tests/support/review_bridge.py`) were placed in the replay's and the checks' own phases by their
passes. The fixture generator reads the recordings through the reader and answers the recording's
live call through the scripted bridge, and Setup commits the fixtures, so both move there: one
reader and one bridge double, not a second copy in the generator.

#### R2.51 The follow-up budget is reachable, narrowly

Computed on 2026-09-23 from the 830 recording: `R0` = 11,006; turn 0's output tokens total 8,054,
of which 519 are the presentation request's, so 7,535 ride in the conversation; the checks-first
opening is about 2,420 (R2.20); 38 results as stubs of 48 to 159 tokens plus 12 framing each is
about 2.3k to 6.5k; the follow-up text is 13 tokens. The follow-up request is therefore about 23k
to 28k against SC-004's 30k (405,397 recorded). The margin rests on the stub caps (20 ids), which
the pruning tests pin.

#### R2.52 What feature 010 needs from this

`specs/010-mechanical-checks/spec.md` (written while this pass ran) requires every 010 check to run
in "feature 008's code-first pass" (its FR-026) and the replay to show no additional model rounds for
them (its SC-006). The extension points are therefore named here so 010 adds entries rather than
mechanisms: a new argument-free check joins `planned_calls` (and `PRERUN_TOOLS`), gets a
`repeat_key` row in the guard's table (`contracts/checks-first.md` section 5), is collapsed by the
digest like any repeated call, is viewed through `check_digest` when its payload is a findings
envelope (a `MODEL_VIEWS` entry), and is priced by the replay's `answered_from_checks` class with no
replay change.

## R3. Verified facts the plan relies on

Re-opened on 2026-09-23 at `43e9b15` for this reconciliation (the rest are the design passes'):

- `agent/settings.py`: `EfficiencySettings` at `:400`, `prerun_checks` `:433`, `parallel_tool_calls`
  `:436`, `procedural_gate` `:451`, `LEVER_NAMES` `:514`, `GATED_ALONE` `:540-543` (including
  `coverage_stop` with `prerun_checks`), the Gemini refusal `:591-596`.
- `prerun.py`: `PrerunCall` `:246-265` holds findings and an error, not the payload; `digest`
  `:279-304`; `planned_calls` `:377-410`; `attach_standards` `:427-471`; `not_evaluated_families`
  `:483-566`; the lever test `:603`.
- `agent/runner.py`: `session.efficiency` `:987`; the standards attach condition `:1031-1032`;
  the dispatch `:1035`; the pre-run call `:1040`; `CoverageStopTools` `:1061-1062`;
  `answer_evidence` `:701`; `finalize` `:728-765`; `_verdict_key` `:531`.
- `chat/server.py`: the fake chat probe `:521-544` (`bridge_measure` on `probe-N`);
  `build_provider` `:547-561`; the forced-failure transport `:612-628` (a real
  `NamedPipeTransport` behind it); `_start_review` `:1822-1864`, which calls
  `self.provider_factory(settings)` with one argument and `start_review` with no efficiency; the
  route table `:2141-2170`.
- `cli.py`: `provider_factory(settings, efficiency=None)` `:262-301`, `parallel_tool_calls` read
  at construction; `_efficiency` `:317-342`.
- `agent/providers/`: `CACHED_SHARE_PUBLISHABLE = False` `__init__.py:224`; `ToolCallResult`
  `:253`; `PromptCacheAware` `:462`; `summarize_result` `:517`; `fake.py` `ScriptedTurn`
  `:90-124`; `openai_provider._encode_history` `:624-643`.
- `tools/registry.py`: `ToolCallRecord` `:253`, `SessionSink` `:290`, `RecordedTool` `:376`,
  `_finish` `:467`, `record_call` `:486`, `_offered` `:757`, `dispatch` `:780`.
- `bridge/client.py:33-36, 150-199`: no read timeout on the pipe transport.
- `tests/unit/test_standards_no_company_values.py`: `PROFILE_SOURCES` `:67-75` (four files),
  census regex `:348`, the census test `:457-465`; `.claude` is pruned from the walk (`:273-277`).
- `tests/unit/test_chat_main.py:310-341`: four `bridge_measure` starts, three forced failures,
  then `BridgeOpenError`.
- `specs/001-agentic-design-review/contracts/review-session.schema.json:108-117`:
  `InvestigationStep`, seven required fields, `status` in `{ok, error}`, no extras.
- `.gitattributes`: `* text=auto`; the vendored npm rule `extractor/SwReview.AddIn/Terminal/TerminalPage/vendor/* -text`.
- `reviewer/pyproject.toml:44-45`: hatchling packages `src/swreview` whole.
- The recorded totals in R1, and R2.51's follow-up arithmetic.
- Feature 009's increments 1 to 3 landed on main while this pass ran (2026-09-23: `2c48e2b`,
  `cf3c66e`, `b5cfcb4`); they edit `Review/ReviewPage/render.js`, `app.js`, `index.html`, a new
  shared attention script, and `specs/007-attention-policy-gate/contracts/attention.md` section 4.
  Its package (`specs/009-engineer-workspace/spec.md`) renders 008's folded group and answer batch
  ("built by feature 008; this feature renders them") and titles the group "Modelling practice: N
  findings across M rules", as here. The two 008 tasks that edit `render.js` and that contract
  start from main's latest page work and rebase before landing.
- The owner decided on 2026-09-23 that size-for-size contacts are one folded list apart from the
  findings (`specs/009-engineer-workspace/spec.md` FR-011; feature 010 owns the rule).

## R4. Amendments to the spec made by this pass

| Where | Was | Now | Why |
|---|---|---|---|
| SC-003 | under 0.3M for each 810-shaped fixture | under 0.3M on the replay's labelled regrouped estimate, with the strict recorded-rounds figure reported and below the recorded total; real behaviour measured by SC-010 | R2.43 |
| FR-013, FR-023 | "the command line keeps a way to turn it off" | the command line defaults every change off and turns each on explicitly, or all four with `--pane-defaults` | R2.15 |
| FR-009, US2 scenario 2 | "written into the run folder's package" | into `<out>/package.json`: in place in the pane, where the run folder is the package folder; a merged copy on a command-line run, whose input folder is never written | R2.18 |
| Edge case "Live detection fails or times out" | "or times out" | fails in any way the transport can report; a hang is not detectable by the pipe transport and is an R5 item | R2.23 |
| FR-027, US5 | "new and cached input" | the report's existing `Uncached input tokens` and `Cached input tokens` are the two numbers, and the pane line uses the same words | R2.46 |
| FR-014 (007 `contracts/attention.md` section 2) | 007: the Findings section is byte-identical under folding | for a session naming a folded family, that family's findings render once, in one collapsed subsection | R2.21 |
| US2 scenario 3 (007 FR-030) | 007: lever 5 writes nothing about standards without a profile | under checks first the standards family is reported with its reason; lever 5's digest and the gate's differ only by parts 2 to 6 | R2.20 |
| FR-007 | fictional fixtures (the replay pass added a fictional profile) | the replay grades standards with `config/standards.example.yaml`, the profile the pilot ran; no new profile file | R2.10 |
| FR-014 example (roadmap) | "85 findings across 12 rules" | 7 rules on the recording | R2.21 |

## R5. Open items that stay open

| Item | Owner | Blocks |
|---|---|---|
| Settled 2026-09-23: the o200k_base vocabulary has no stated redistribution terms, so it is not vendored; each machine fetches it once into a per-user cache (R2.7) | owner | nothing; T002 proceeds as amended |
| Zero-volume contacts are judged `demonstrated` until feature 010's contact rule; with all groups judged, many more appear (R2.17). The owner's 2026-09-23 decision (contacts as a separate folded list, not findings) is delivered by features 010 and 009, not here | feature 010 | the reading of SC-006 results at the sitting |
| Prune age one or two rounds; the replay prints both (R2.37) | owner | nothing |
| A hung live detection blocks session creation; no read timeout without a new transport; moving the pre-run into `ReviewRun.start()` is the alternative (R2.23) | owner | nothing in 008; latency measured at the sitting (T104) |
| "uncached" or "new" on both surfaces (R2.46) | owner, feature 009 | nothing |
| Record probe L1 from the 119 recorded rounds and flip `CACHED_SHARE_PUBLISHABLE` | owner | nothing (the pane no longer shows a share) |
| SC-003's regrouped margin is thin (0.29M to 0.30M modelled, R2.43) | owner, after T087 | SC-003 |
| `runner._verdict_key` ignores hole ids, so `_reconcile_reruns` can fold two hole-pair findings (existing, R2.8) | backlog | nothing |
| Move `request_capture` onto `resolve_entity_ref` (R2.27) | follow-up | nothing |
| MCP general chat still shows persist references while the bridge tools want ids (R2.38) | follow-up | nothing |
| `benchmark compare` ignores `model_view`, so a comparison across builds would not be refused | follow-up | nothing |
| A reused command-line `--out` folder can keep stale higher-numbered `tool-results` files; the `session_id` identifies them | follow-up | nothing |
| The explanation request sends the top rows' finding inputs, which can carry inline persist references; not a tool result, outside FR-015 | follow-up | nothing |
| `groups_of` is recomputed per group call, quadratic in groups; the perf test in T041 guards 1,000 groups | T041 | nothing unless red |
| An earlier scratch estimate put mate persist references at about 1,284 characters each; measured mean 781, max 1,656; no budget here uses the old figure | none | nothing |
| SC-010: a licensed seat, the real standards profile placed first (006 T100), a paid review of each recorded assembly | owner | Phase 8 |
