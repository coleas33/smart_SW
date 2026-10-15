# Contract: The Report Page and the Record of What Was Sent

Normative for FR-034, FR-035, FR-057, SC-009 and User Story 6; D10's page columns and its open
cache-write point; D11; research §8.13's reader. Line numbers are at `be01974`; paths are under
`reviewer/src/swreview/` unless another root is given. Every example value is fictional.

What this contract fixes: one offline command that builds one static page, with a transcript page
per package repetition, from run folders as `benchmark run` writes them; how it finds each package;
what each column shows and where each number comes from; what a transcript holds and in what order;
how it reads the record of the system prompt and every user message a run sent (FR-057; the
record itself is `benchmark-run.md` section 12's); the output folder's
rules; refusals; the performance budget. It computes no number: every count, status, grading and
cost is the scorecard's (the scorecard and run-status contracts), rendered.

## 1. Shape

`swreview benchmark report <run dirs...> --out <folder>`

| Contacts a provider | Reads | Writes |
|---|---|---|
| no | each run folder's files (section 2) and each package's `package.json` through the saved set | `<folder>/index.html` and `<folder>/transcripts/...` only |

It takes the run directories `compare` takes (`cli.py:2501-2508`), refused the same way when one is
named twice (`benchmark/compare.py:749-766`, shared, not copied). It reads no answer key and takes no
key option; the page shows the tags the scorecard carries.

**Python, one module, no script in the page.** `benchmark/report_page.py` writes HTML with
`html.escape` and plain string building, one inline style block, no JavaScript, no external
resource. Three designs were weighed:

| Design | Why not, or why |
|---|---|
| Emit `results.jsonl` and `traces/` in an eval tool's shape, plus a small committed JavaScript renderer | A second serialization of the scorecard, a second writer of every number (the drift ab-harness section 4 exists to prevent). A renderer that fetches JSON does not run from `file://` in current browsers, and the pilot workstation cannot serve pages over loopback HTTP, so the data would be inlined anyway. Testing it needs Node, or the add-in's C# page harness (`extractor/SwReview.AddIn.Tests/PageScripts.cs`), which is Windows-only; the reviewer's Python side has no Node, and a runtime added for one page is complexity the constitution asks to justify |
| Extend `report/markdown.py` | The review report is plain Markdown by rule (`report/markdown.py:4`); Markdown is a page only inside a viewer, while a browser opens HTML and its relative links straight from `file://`, with no viewer installed |
| **A Python module writing static HTML** (taken) | Reads the scorecard models directly, so the page cannot disagree with them; tested by pytest with the standard library's `html.parser`; runs wherever the reviewer runs, offline, with no key and no licence (FR-047) |

## 2. What it reads

A run folder is a folder holding `scorecard.json`, as `recorded_runs` defines one
(`benchmark/compare.py:769-779`).

| File | Used for | When absent |
|---|---|---|
| `<run>/scorecard.json` | every number, status, tag and grading | refused (section 7) |
| `<run>/run-provenance.json` (`benchmark/runner.py:47`) | study, arm, repetition, provider, model, commit, start | those cells read `unknown` |
| `<run>/benchmark-set.json` (`cli.py:2313-2314`) | where each package is | component names not shown; one line says why |
| `<run>/<package>/session.json` | the final state: findings, requests, answers | "no session was recorded" (a failure before the session was written) |
| `<run>/<package>/events.jsonl`, or `events.jsonl.gz` in a packed folder (owner decision 28A), found by `agent/events.event_stream` and read through `agent/events.replay_events` (plan decisions RF-29, RF-83) | the transcript's order | "no events were recorded" |
| `<run>/<package>/tool-results/step-<n>.json` (`tools/registry.py:287, 394-419`), through `tools/registry.read_stored_result` (plan decision RF-30) | each call's full result | "full result not stored" |
| `<run>/<package>/prompts.json` (section 3) | the system prompt and each user message as sent | "not recorded" (US6-3) |
| `<run>/<package>/answer-log.json` (`scripted-answers.md` section 5) | the questions given nothing at each answer point, and why | not shown |
| the scorecard's `unscored_packages` and `failed_attempts` (`scoring.md` section 7, copied there from `run-status.json` through `package_outcome` and `attempt_facts`, `benchmark-run.md` section 10) | each failed attempt: kind, class, retries, billed usage and cost, and its run-relative `folder` (plan decision RF-17) | none shown |
| the stream of `<run>/<folder>` for each failed attempt, plain or packed, found the same way, `folder` as its scorecard row names it (`attempts/<package>/<n>/`) | the failed attempt's own transcript page, walked as section 5 walks a kept one | "no events were recorded" (a failure before the first event) |

**Finding each package** (FR-034). A run folder holds no `package.json`: only the replay copies one
(`benchmark/replay.py:323-325`), and `read_recording` refuses a folder without it
(`benchmark/recording.py:168-173`). The page finds each package through the saved set's entry for
its id. A repository-relative path (the benchmark-set contract, research §8.8) resolves against this
checkout's root (`benchmark/runner.py:52`), so a page built in another checkout finds the same
package; an absolute path, a private entry or a folder saved before that change
(`benchmark/sets.py:51-58`), is used as written. The package is loaded with `ir/loader.load_package`,
so the key guard applies (`ir/loader.py:46-62`). It is used for one thing: a legend of component ids
and names (`report/names.py:33`, `component_names`) at the top of each transcript. Recorded text is
never rewritten; a transcript shows what was sent and received. A package that is missing or does
not load leaves the legend out, with one line naming the path as saved; it is never a refusal.

**Tags** (US6): as the scorecard records them per item (`graded_items`, `scoring.md` section 6):
held out or tuned-on with counts and producer; the anchor or analyst-found label from the saved
set entry's `represents` (`cases.md` section 4.1).

## 3. The record of what was sent (FR-057, D11)

The system prompt is built in memory (`agent/runner.py:1756-1762`) and no event carries it or any
user message (`agent/providers/__init__.py:101-118`). A benchmark attempt now writes
`<package folder>/prompts.json`. **Its writer and format are `benchmark-run.md` section 12's**; this
contract reads it:

```json
{"prompts_version": 1,
 "system": "You review SOLIDWORKS evidence packages ...",
 "user_messages": ["Pre-run digest ...\n\nReview the evidence package described ...",
                   "The engineer answered ER-002: press fit ..."]}
```

- `system` is `ReviewRun.system` byte for byte; `user_messages` is every `role: user` entry of
  `ReviewRun.messages` in order (`agent/runner.py:1399-1402`, `_ask`, is the one place one enters the
  history, and the history is never pruned in place, `:1444-1447`): the opening message first, then
  one per answer turn, as sent (`answers_message` with any drawing-outcome and regrade lines,
  `:1180-1196`). Message `k` opens turn `k` (0 is the opening turn); the page places them by index.
- The explanation pass's request is not a user turn and is not recorded; its usage appears in the
  log as a presentation round.
- Only benchmark attempts write it; the pane's and `review`'s folders are unchanged (plan decision
  INT-1, research §9). The handoff export carries it when present (`provenance.md` section 7).
- A folder written before this record shows "not recorded" for the system prompt and the opening
  message, and for each later user message (US6-3).

## 4. The page: `index.html`

**Head.** One line per run folder: its path relative to the common parent of the run folders
given, study, arm, repetition, provider, model, commit and start time. The price table's sources and
dates as the scorecards record them in `Scorecard.price_table` (`scoring.md` 7; D10; plan decision
RF-45), each priced model with its three prices' source and date; nothing when no round was priced
(a scripted run). No build time is written, so two builds over the same folders are byte-identical.

**Totals per run folder.** Package runs completed, bound-reached, stopped (by class) and failed (by
kind and class); total tokens; cost, summed only when every package run's cost is known, else
`unknown` with the number unknown, the scorecard's rule (`benchmark/scorecard.py:410-420`); the
failed attempts' billed cost on its own line, "billed by failed attempts, in no score"; wall clock.

**One section per case**, in saved-set order (the first run folder's, then any package only a later
one holds): the package id, its tags, and one row per run folder, ordered by study, arm and
repetition:

| Column | Shows |
|---|---|
| run | the folder, arm and repetition |
| status | `completed`, `bound-reached`, `stopped: <class>` or `failed: <kind>, <class>` (FR-035) |
| held-out model-produced | detected of keyed; flagged below expected; cleared (the headline, 3A) |
| code-produced | detected of keyed |
| tuned-on | detected of keyed |
| false alarms | the deciding model-origin count (17A, D15), then the other origins' |
| tokens | input, cached input, output, reasoning or thoughts (named per provider, ab-harness 10.8), cache-write |
| cost | the priced cost and its basis, `unknown (<what is missing>)`, or `synthetic, not priced` |
| wall clock s | the session's own (`benchmark/scorecard.py:169-173`) |
| transcript | a relative link |

- A failed repetition's outcome cells read `not scored: failed`, never 0; its tokens and cost are its
  failed attempts', labelled so (FR-035, US6-1). A repetition that failed before its first round, with
  no usage and perhaps no events, still has its row and its transcript page (FR-034).
- A column the keys do not grade reads `not assessed` (FR-021); an absent number reads `unknown`
  (`benchmark/scorecard.py:59`); nothing reads 0 or blank unless it was measured as 0.
- **Cost** (D10, FR-042): the run-status contract's per-package cost record, rendered: its basis says
  "cached input priced apart" or "input priced as uncached" where the provider's containment is
  unverified (`agent/providers/__init__.py:233`); unknown names the model with no price or the missing
  usage; scripted, oracle and null runs read synthetic. **Cache-write tokens**
  (`agent/providers/__init__.py:167`, OpenAI only) are shown as a count and never priced: FR-042's
  table holds three prices per model, and the pane study has no cost threshold (D1). This settles
  D10's open point.
- Numbers are formatted by the ledger's rule (`benchmark/compare.py:806-810`, promoted to a public
  name and imported, not restated).

## 5. A transcript page

`<folder>/transcripts/<run folder relative path>/<package id>.html`. In order:

1. **Header**: run, package, arm, repetition, status, requested and responding model, usage, cost,
   wall clock, and a link back to the index.
2. **The system prompt as sent**, then the component legend (section 2). A folder with no
   `prompts.json` reads "not recorded" in its place and in each user message's; one whose
   `prompts.json` does not validate reads "the prompts record is unreadable" in the same
   places, and is not refused (owner decision 85A).
3. **The log, in its own order**, grouped into turns at each `turn.ended`:
   - before the first `usage`: "Code before the first turn": the pre-run's and set-up's calls;
   - each turn opens with its user message as sent (the opening message first); an answer turn also
     lists, as the engineer's turn and in order, each `evidence.answered` with its request's question
     from the session and the answer, and the questions the driver gave nothing at that point, with
     the reason (`answer-log.json`) (US6-2);
   - `usage`: a round marker with its tokens, the presentation round named "explanation pass";
   - `tool.started` and `tool.finished`: tool, arguments, status and summary, the full result from
     its file in a collapsed block, and the `finding` and `finding.withdrawn` events inside its
     bracket listed under it;
   - calls between turns, the part-roles regrade's restated calls (`agent/runner.py:1180-1193`),
     where the log puts them;
   - `text.done`: the model's text (`text.delta` is skipped, being the same text in pieces);
   - `evidence.requested`: the question as recorded; `coverage` rows, one line each, collapsed per
     turn; `error`; each turn's end reason.
4. **The final state**: every finding of `session.json` with the scorecard's grading of it (the
   defect it credits or flags, flagged below expected, false alarm with its origin, confirmation,
   contradiction, forbidden hit), read from the scorecard's id lists, never re-derived; the withdrawn
   findings with their reason.
5. **Failed attempts**: each with kind, class, retry count, billed usage and cost, and a link to its
   own transcript page, built from the stream `event_stream` finds in `<run>/<folder>`, through the
   row's `folder`, never a guessed path; a package whose every attempt failed has its section and its pages from these rows
   alone.

**Why the page walks the log** rather than the replay's `_EventReader` (`benchmark/recording.py:222`,
research §8.13's starting design): that reader interprets rounds for pricing and drops a call made
outside a round (`:267-274`), which loses the regrade's restated calls; extending it would change the
replay's parser for a display need. What is shared is the line reader: the product's own
`replay_events` (`chat/sessions.py:106-129`, which the pane's reconnect and remodel already use),
moved beside `EVENTS_FILE_NAME` in `agent/events.py` with an `on_unreadable` hook in the
key-extensions slice, and read by the scorer and `attempt_facts` too (plan decision RF-29). In this
slice `recording._events` (`:194-212`) is replaced by it: `read_recording` still refuses a malformed
line, raising `RecordingRefused` on the line the hook reports, and hands `_EventReader.read`, which
indexes dicts (`event.get("type")`, `event["body"]`), each event as `event.model_dump(mode="json")`,
the shape `_events` handed it. The reader is stricter than `_events`: a line that is JSON with a body
but not an `AgentEvent` (`seq` at least 1, `at` a datetime, a known `type`, no extra field) is now
refused there too. The page stops at such a line and says
"the event log is unreadable from line N" (a process stopped mid-write), showing everything before
it. A line the reader reads whose body the walk cannot (a call's step that is not an integer, a
round whose counts do not read, a coverage row whose item is not an object) stops the page the same
way: "<run>/<package>: the event log is unreadable from seq N" (owner decision 83A). Each recorded
user message past the log's last turn is still shown, under its turn: "this turn is not in the
event log" when the log ended there, "not shown: the log is unreadable before this turn" when it
stopped early (83A, 91A).

**Full results** are read through `tools/registry.read_stored_result(run_dir, session_id, step)`,
the one reader beside the one writer, which the replay and the questions reader call too (plan
decision RF-30): its `text`, the file's raw text, is embedded escaped, not parsed and re-indented. An
`Unstored` answer is named, never guessed: `missing` reads "full result not stored", `other_session`
(a file whose `session_id` differs from the session's, `tools/registry.py:407-414`) "a stale result
from another session in this folder", `unreadable` "the stored result is unreadable", and
`other_call` (an envelope naming another step) "a result recorded for another call" (owner decision
85A). Every recorded string is escaped; a finding text holding markup renders as text.

## 6. The output folder

- `--out` is required. Absent or empty: created and written. Holding a previous report, whose
  `index.html` carries `<meta name="generator" content="swreview benchmark report">`: replaced
  whole. Holding anything else: refused.
- The build is written into a new sibling folder of `--out`, `.<name>.<random>.building`, made with
  `Path.mkdir`, and put in place once every page is written: the previous report moved aside as
  `.<name>.<random>.previous`, the build moved in, the previous report removed. A build that fails
  part-way leaves the previous report as it was (owner decision 83A). Where `--out` is or holds the
  working folder (`--out .`), or is a junction or a symbolic link, or a move fails (a folder another
  process holds), the build is copied into `--out` in place instead, replacing its report, so a
  link's target is the one updated (owner decision 91A). The build therefore needs write access to
  `--out`'s parent.
- Removing the previous report, and this build's own folder after an in-place copy, is best effort,
  read-only flags cleared: one that cannot be removed is named on one warning line, and the command
  still exits 0, its report being in place. Siblings of either kind a killed build left are removed
  first, best effort, each named (91A).
- Every link is relative; run folders are named relative to their common parent. The page holds no
  local absolute path, and FR-051's committable-folder test runs over a page built from committed
  studies. A page built over private runs carries private paths and data and stays outside the
  repository (D12). Pages are not committed: at SC-009's size they are hundreds of megabytes.
- Reading writes nothing into any run folder.

## 7. Refusals

| When | The message says |
|---|---|
| A run folder holds no `scorecard.json` | run `swreview benchmark score` on it first, as `compare` says (`benchmark/compare.py:300-306`) |
| A run folder is named twice | as `compare`'s (`:749-766`) |
| A run folder or package path lies under a key path | the key guard's own message (`ir/loader.py:46-62`) |
| `--out` holds files this command did not write | the folder, and to choose an empty one |
| A package or attempt folder holds both `events.jsonl` and `events.jsonl.gz`, a pack that did not finish | `event_stream`'s message: the folder, and to run `swreview benchmark pack` on its run again (`provenance.md` 6.7) |
| Two or more run folders, one in the home folder, whose common parent is the home folder or above it, so their names would carry the home folder's own folders (owner decisions 84A, 92A: a lone run folder is named by its own name and never refused for it, and where the platform names no home folder there is none to guard) | the run folder, the common parent, and to copy the run folders under one study folder |
| `--out` is a run folder or lies in one (84A) | the folder, the run folder, and to choose a folder outside it |
| The run folders lie on different drives, so they have no common parent to be named relative to (owner decision 85A) | that, and to copy them under one folder |
| A scored package's id cannot name a file: empty, a path separator, `.` or `..`, a character or a device name Windows refuses, a trailing dot or space; or two ids are one file name when case-folded (84A) | the run folder, the id or ids, and why |

Not refused, each shown as section 4 or 5 says: a folder written before `prompts.json`, missing
usage, a failed repetition, a missing package, an unreadable tail of the event log (a truncated or
corrupt packed stream included) or a body the walk cannot read, each shown as "unreadable from
line N" or "from seq N"; a recorded message past the log's end ("this turn is not in the event
log", or "not shown: the log is unreadable before this turn"); a missing or stale tool result; a
folder with no provenance; a previous report or a killed build's sibling that cannot be removed,
named on a warning line (section 6). A packed folder is read as its plain form was (owner decision
28A).

## 8. Performance (SC-009)

The budget: SC-009 names 40 cases at 10 repetitions in both arms, 800 transcripts, in under 60
seconds on the development machine, every link resolving. The test builds the committed set's worst
case instead, 47 cases at 10 repetitions in both arms, 940 transcripts, under the same 60 seconds,
which implies SC-009's 800 (plan decision RF-46), each stream packed (`events.jsonl.gz`), the form a
committed study at the cap takes, so the budget includes their decompression (owner decision 28A); a report over the paid pilot's folders is its own,
smaller build. "Pilot-size" is fixed for the test as 40 calls per transcript with 16 KB full results,
3 answer turns and a 30 KB system prompt: about 0.7 MB per transcript, about 660 MB in all. One pass per file; results written as escaped text, no parse beyond the
envelope; no templating library. Should the pilot's real sizes break the budget, the alternative is
linking each result to its file in the run folder rather than embedding it, which the owner decides
(it moves the page away from "one self-contained transcript").

Owner decision 82A (2026-10-14) kept embedding: the budget measures the report's own work. On the
development machine the first open of each freshly written file costs about 6.6 ms under Windows
Defender real-time scanning, so a build at once over the freshly written fixture took 242.7 s for
its about 37,600 stored results; the perf fixture therefore opens each stored result once before
the timed build, and R-18 measured about 26 s. A first build over freshly written run folders on
that machine still pays the scanning on top.

## 9. Tests

`reviewer/tests/unit/test_benchmark_report_page.py`, over run folders written by the scripted
provider (`agent/providers/fake.py`) and scored:

- R-1 a scripted run of three cases: every count on the page equals its scorecard's, and every row
  links to a transcript file that exists and whose first content section is the recorded system
  prompt (User Story 6's independent test; SC-009's link half).
- R-2 run folders of a baseline and a variant both appear, each with its study, arm and repetition
  (US6-1).
- R-3 a failed repetition reads `failed: <kind>, <class>`, its outcome cells `not scored: failed`,
  never 0; one that failed before its first round, with no usage and no events, still has its row and
  its page (FR-034, FR-035); a failed attempt's page is built from the events its scorecard row's
  `folder` names, and the page opens no other attempt folder (RF-17).
- R-4 a model with no price reads `unknown (<model> has no price)`; missing usage reads
  `unknown (no usage)`; a scripted run reads `synthetic, not priced`; cache-write tokens appear as a
  count with no price; a total with one unknown reads `unknown` and says how many.
- R-5 a transcript with two answer turns: system prompt, opening message, then each turn's message
  as sent and its answers as the engineer's turn, in order; the regrade's restated calls between
  turns appear where the log puts them; an unscripted question is listed at its point (US6-2).
- R-6 a folder written before `prompts.json`: "not recorded" for the system prompt and every user
  message (US6-3).
- R-7 packages through the saved set: a repository-relative entry resolves against the checkout
  root; an absolute entry is used as written; a missing package leaves out the legend, names the
  path, and refuses nothing (FR-034).
- R-8 the command opens no file under any key path the sets name (asserted over every path opened,
  as `test_benchmark_compare.py:443-465` does).
- R-9 the output holds no path under the checkout, the user profile or the temp folder (FR-051's
  test).
- R-10 the output folder: empty is written; a previous report is replaced; foreign files refuse;
  nothing is written into a run folder.
- R-11 an unscored run folder and a folder named twice are refused with section 7's messages.
- R-12 a tool result whose `session_id` differs is not embedded and is named stale; a missing one
  reads "full result not stored"; an unreadable one is named so; each through `read_stored_result`
  (a spy; RF-30); an event log with a truncated last line shows everything before it and says from
  which line it is unreadable, read through `replay_events` and its `on_unreadable` hook (RF-29); a
  packed stream truncated mid-archive does the same (RF-83).
- R-13 a finding and a model text holding `<script>` render as text.
- R-14 building twice over the same folders gives identical bytes.

The record's writer is pinned by `benchmark-run.md` section 15's `test_prompts_record.py`; this
contract adds, in `reviewer/tests/unit/test_benchmark_report_page.py`:

- R-15 a transcript opens with `prompts.json`'s `system` and places `user_messages[k]` at turn `k`,
  the answer turns' messages byte for byte (regrade line included).
- R-16 a folder whose `prompts.json` holds only the opening message (an abandoned attempt) shows it
  and reads "not recorded" for each later turn's message.
- R-17 `read_recording` still refuses a malformed line, naming it, a folder with no usage event and
  one with no `package.json` (`benchmark/recording.py:163-173`), now reading through
  `replay_events` (a spy); every committed replay fixture's events read through it with no
  unreadable line (RF-29); and `reviewer/tests/integration/test_replay_recorded_runs.py` (unmarked;
  the development machine, which holds the three recordings) passes unchanged, 88 reproduced and 11
  not replayable on the big run (`:152-155`), so a real recording the stricter reader refuses is
  caught in this slice's gate.
- R-19 (the robustness slice, which adds `benchmark pack`; 28A, RF-83) the report over one scored
  run folder, built before and after `benchmark pack`, gives identical bytes, a failed attempt's page
  included; a package folder holding both forms is refused with section 7's message.

`reviewer/tests/perf/test_benchmark_report_perf.py`, collected only with `-m perf`
(`reviewer/tests/conftest.py:39-66`):

- R-18 section 8's 940 transcripts, their streams packed, build in under 60 seconds and every link on
  the index resolves to a page (SC-009; RF-46; 28A). The perf fixture writes each stream packed with
  `gzip.compress(data, compresslevel=9, mtime=0)`, `provenance.md` 6.7's rule, since `benchmark pack`
  lands after this slice, and opens each stored result once before the timed build (owner decision
  82A, section 8).

## 10. Defaults this contract takes

Each is reversible; plan.md records it with its alternatives.

- **Static HTML from Python, no script, no Node** (section 1).
- **Transcripts walk the log** through the product's one event-line reader, `replay_events`, not the
  replay's round reader (section 5; RF-29).
- **`prompts.json` beside the session, written by the benchmark attempt only** (`benchmark-run.md`
  section 12; plan decision INT-1 superseded this contract's first draft, which wrote it from `_ask`
  on every review with a `coverage.prompts` row on a failed write: that changed the pane's run
  folders and added a coverage row to every product review for a record only the eval reads).
  Alternatives: an event type, which changes the chat-events schema the pane replays and streams a
  30 KB prompt to the pane; the `_ask` writer.
- **Full results embedded**, with linking as the fallback if the budget breaks (section 8).
- **Cache-write tokens counted, never priced** (section 4). Alternative: a fourth price column per
  model in the price table.
- **A package's use is the legend only**; recorded text is never rewritten with names.
