# Contract: Benchmark Run, Attempts and Run Status

Normative for FR-011, FR-012, FR-015, FR-036 to FR-043, FR-047 (with SC-012: every test here is
offline, and section 15's tokenizer test pins D14.6), FR-050 and FR-057; User Story 2 scenarios 1,
2 and 7, and User Story 7. Research D2, D10, D11, D16, PP-1, PP-2, PP-5, PP-6 and
§8.10, and owner decisions 34A (section 4's one writer) and 36A (section 5.4, packages at once). This is the run-status layer `scripted-answers.md` sections 3 and 4 hand classification
to. What the provenance record holds, what must match across a study, the pane study's rules
and the location-free paths are `provenance.md`'s. Line numbers are at `be01974`; paths are
under `reviewer/src/swreview/` unless another root is given. Every example value is fictional.

Amends: feature 005 `contracts/ab-harness.md` sections 2 and 10.1 (the provenance record is
written before any review, not after; a failed package no longer stops the set); feature 008
`contracts/cli.md` and feature 001 `contracts/cli.md:37` (`--pane-defaults` includes the
explanation pass, PP-1); feature 002 `contracts/chat-events.schema.json` (optional fields on
the `usage` and `error` bodies, sections 6 to 8: `served_model` and `stop_reason` written on every
stream, the pane's included, `retries` only under a retry policy; plan decision RF-32).

## 1. What is reused

| Piece | Where | Used as |
|---|---|---|
| The one resolver | `cli.py:407-452` `_review_settings`, shared by `review` and `benchmark replay` | FR-011: `benchmark run` resolves through it and nothing else |
| The pane's settings | `agent/settings.py:502-521` `pane_efficiency`, `:550-556` the two model views, `:559-570` `PaneDefaults`, `pane_defaults` | The pane study's on arm and the pane baseline |
| The pane's start | `chat/server.py:2103-2152` `_start_review` (the `start_review` call `:2119-2139`, explanations `:2138`) | The parity reference of section 5.1 (FR-012, SC-003) |
| Stopping a turn | `chat/server.py:434-466` `TurnStopped`, `StoppableTools`; `:2145-2151` their use; `:2283-2290` `_end_stopped`; the replay's copy, `benchmark/replay.py:253-259` `_Stop` and `:452-455` | The wall-clock stop, moved to `agent/runner.py` and shared by the pane, the attempt and the replay (section 5.1) |
| A worker per turn | `chat/server.py:2176-2184` (the pane plays turns on an executor's worker thread) | Precedent for section 5.3, whose worker is a daemon thread instead (plan decision RF-50) |
| The event-line reader | `chat/sessions.py:106-129` `replay_events`, moved beside `EVENTS_FILE_NAME` in `agent/events.py` with an `on_unreadable` hook (plan decision RF-29) | `attempt_facts` (section 10) |
| A review held open | `agent/runner.py:1497` `start_review`, `:1113` `start`, `:1138` `answer_evidence_batch`, `:1399-1402` `_ask` | The attempt body; `run_review` (`:1815-1848`) stays the `review` command's |
| The event stream | `agent/events.py:106-131` (`emit`: written, then fanned out to listeners), `:134-192` `UsageLedger`, `:219-235` `emit_turn_failed` | The attempt's listener (section 5.2) and every count this contract reads back |
| How a turn ends | `agent/providers/__init__.py:121` `TurnEndReason`; `report/session.py:314-331` `cut_short_reason` | Behavioural classes (section 9) |
| Provider errors | `agent/providers/openai_provider.py:137-150`, `:574-580`, `:638-654`, `:708-740`; `agent/providers/gemini_provider.py:127-145`, `:152-190`, `:578-589`, `:853-864` | Retries, stops and failures (sections 6 to 9) |
| The profile loader | `checks/standards/profile.py:153` (`ProfileError(Exception)`), `:617-634` `load_profile` | PP-5's preflight |
| The adapter factory | `cli.py:325-363` `provider_factory`, the one place an SDK client is built | Unchanged, signature included; the attempt body calls `use_retry` on the adapter it returns (section 6) |
| The adapters' optional extensions | `agent/providers/__init__.py:501` `use_prompt_cache`, `:518` `use_model_view`, called once by `start_review` | The shape of `use_retry` (section 6) |
| The scripted provider | `agent/providers/fake.py:97-160` (`ScriptedRound`, `ScriptedTurn`), `:220-...` `FakeProvider` | Every test below; gains section 15's affordances |

## 2. Options and how they resolve

`_review_settings` resolves three things instead of two and returns one frozen value,
`ResolvedReview(efficiency, model_view, explain_findings)` (FR-011, FR-015, PP-1):

- **Explanations.** A typed `--explain-findings` or `--no-explain-findings` wins; otherwise the
  base's value; the base is `pane_defaults(provider)` with `--pane-defaults`, else the all-off
  base (`cli.py:432-435`). `PaneDefaults` (`agent/settings.py:559-563`) gains
  `explain_findings: bool`, `True` in `pane_defaults`, `False` in the all-off base, and the chat
  server reads `defaults.explain_findings` where it passes the literal `True` today
  (`chat/server.py:2138`), so the pane's value is decided in one place.
- The option becomes tri-state (default: not typed) on `review` (`cli.py:709-717`) and
  `benchmark run` (`:2258-2265`). So `review --pane-defaults` runs the explanation pass,
  `review --pane-defaults --no-explain-findings` does not and the session records it off
  (US2-7), and `review` with neither keeps today's default off.
- `benchmark replay` reads the efficiency and model view of the result, as it reads the tuple
  today (`cli.py:2484-2494`).
- **What `benchmark run` needs of the resolver** (plan decision RF-19). `benchmark run` resolves
  through `_efficiency(lever, provider=..., study=..., arm=..., allow_workstation_levers=False)`
  today (`cli.py:2289-2295`), which refuses a workstation lever and checks the typed study and arm;
  `_review_settings` calls `_efficiency` with neither (`cli.py:437`). So `_review_settings` gains
  keyword parameters `explain_findings: bool | None = None`, `study: str = NO_STUDY`,
  `arm: str | None = None` and `allow_workstation_levers: bool = True`, the defaults being today's
  behaviour, and passes the last three to `_efficiency`. `check_study_arm` (`agent/settings.py:730`)
  gains the typed markers `provenance.md` 3.2's rules read: `pane_defaults`, the levers typed,
  whether a model-view switch was typed (`--payload-slimming`, `--history-pruning`,
  `--prune-after`) and whether an explanation setting was typed. `benchmark run` passes
  `allow_workstation_levers=False` with its study and arm; `review` and `benchmark replay` keep
  today's call, so the replay's spy test (`tests/unit/test_cli_benchmark_replay.py:171-200`) and the
  workstation-lever test (`tests/unit/test_efficiency_settings.py:535-556`, "workstation harness",
  exit 2) pass unchanged.
- `--pane-defaults`' help (`cli.py:456-461`) names the explanation pass, and 008's and 001's
  `cli.md` (`specs/001-agentic-design-review/contracts/cli.md:37`) say so.

`benchmark run`'s options (new rows marked):

| Option | Meaning | Recorded (`provenance.md` section 1) |
|---|---|---|
| `--pane-defaults` (new) | start from `pane_defaults(provider)`; the typed marker PP-3 reads | `pane_defaults` |
| `--payload-slimming`, `--history-pruning`, `--prune-after N` (new) | exactly as `review` (008 `contracts/cli.md`) | `model_view` |
| `--lever` | unchanged | `efficiency` |
| `--explain-findings/--no-explain-findings` | tri-state, as above | `explanations_enabled` |
| `--standards-profile PATH` (new) | graded in every review; loaded once before the set (section 3) | `profile_digest`, `profile_is_example`; never the path |
| `--study`, `--arm`, `--rep`, `--i-know-the-set-is-too-small` | unchanged, plus the pane study and the pane baseline (`provenance.md` section 3) | as today |
| `--max-answer-turns N` (new) | `scripted-answers.md` section 4 | `max_answer_turns` |
| `--package-time-limit MINUTES` (new) | one attempt's wall clock (section 5.3); an integer of 1 or more, default 60 | `package_time_limit_s` |
| `--jobs N` (new; owner decision 36A) | up to N packages at once (section 5.4); an integer of 1 or more, default 1 | `jobs`, record-only (`provenance.md` section 4) |

The retry policy, the stream-activity window and the stop grace are constants, recorded, not
options (sections 5.3 and 6): nothing has asked to vary them, and a study that did would be
refused for it anyway (`provenance.md` section 4).

## 3. Refusals before any review

Usage errors first, exit 2, one line naming the flags, raised by `_review_settings` and
`check_study_arm` (`agent/settings.py:730-783`) before an adapter is built: every existing
lever and `--prune-after` refusal; the pane-study and baseline rules of `provenance.md`
section 3 (an arm missing, an explanation setting not typed, an arm that is not exactly
`--pane-defaults` or exactly all off); `--package-time-limit` below 1; `--jobs` below 1; `--max-answer-turns`
below 0 (`scripted-answers.md` section 4).

Then, inside `_errors_as_exit_1` (`cli.py:530-545`), in this order, each exit 1 with one line,
nothing written and no review started:

| # | Refused | Message gist |
|---|---|---|
| 1 | `--out` exists and holds anything | "{out} is not empty; choose a new folder". Today a second run into one folder appends a second session with duplicate sequence numbers (rerun-appends-events, research §2), and a promotion (section 4) needs its target free. The robustness slice, which adds `benchmark resume`, adds the pointer: "{out} is not empty; resume a run with `swreview benchmark resume {out}`, or choose a new folder", pinned by its own test; the parity slice's message names no command that does not exist yet |
| 2 | The profile (PP-5, FR-050, US2-2): `load_profile` raises `ProfileUnreadable` or `ProfileInvalid` | the class and its message. Both are passed to `_errors_as_exit_1` by name, because `ProfileError` subclasses `Exception`, not `ValueError` (`checks/standards/profile.py:153`), and is in no shared list. Loaded here, in `benchmark_run`, not in the shared resolver: `review` and the pane keep recording the refusal and going on (`agent/runner.py:427-437`) |
| 3 | The provider does not resolve: `ProviderSettings.from_env`, one adapter built through `provider_factory`, and `effort_mapping(effort)`, which sends nothing. That adapter is not an extra one: `benchmark_run` hands it to the run's first attempt through a one-shot holder bound into the review function it passes `run_benchmark`, and that attempt uses it instead of building its own, every later attempt building its own. An adapter that has served no turn holds no per-turn state, so `_review_fn`'s "a fresh adapter per package" (`cli.py:2204-2205`) holds, and a run builds exactly one adapter per attempt, as today (plan decision RF-60) | the adapter's own refusal (no key, an effort the model does not offer). Once, here, rather than as the same `internal_error` on every package |
| 4 | The set and its case files | the set loader's refusals (`cases.md` 4.3), every missing `package.json` and key named at once (`cases.md` 4.4, keys stat-ed, never opened) and `scripted-answers.md` section 2.3; also a package id equal to `attempts` ignoring case, which would collide with section 4's folder, since Windows and macOS fold case (owner decision 48A). These run in one function, `benchmark/runner.preflight_set(set, profile, checklist) -> PreflightedSet`, which `run_benchmark` requires as an argument, so a library caller gets the same refusals before any review and the command line can write the provenance record between them and the first review (plan decision INT-14) |
| 5 | A committable run folder over private data | `provenance.md` section 6.4 |
| 6 | The pane study's file rules | `provenance.md` section 3.2's run-time table, which holds each message: the example profile, no private package, a known commit, a clean tree, no carriage return in a digested input, and, from the robustness slice, which adds the price table (section 13), a requested model the table can price by section 13's lookup, for `pane_defaults` and `pane_defaults_private` alike (plan decision RF-79) |
| 7 | P-3 (`cli.py:2226-2246`) | unchanged; PP-6: `--pane-defaults`, `--payload-slimming` and `--history-pruning` now declare a study as `--lever` does (`cli.py:2288`), so a pane smoke run over a set with nothing held out needs the recorded override. `--standards-profile` alone declares nothing |

Then the provenance record and the saved set are written (`provenance.md` sections 1 and 6.1),
**before** any review rather than after the set as today (`cli.py:2313-2333`): a run that stops
part way is still attributable and resumable.

## 4. The run folder

```text
<run>/
  run-provenance.json         what was typed and resolved; written once, before any review
  benchmark-set.json          the saved set, location-free (provenance.md 6.1); once, before any review
  run-status.json             every package's attempts and outcome (section 10); the driver only
  <package_id>/               the kept attempt, promoted (below): session.json, events.jsonl,
                              attention.json, tool-results/, prompts.json, answer-log.json
  attempts/<package_id>/<n>/  every attempt runs here; an infrastructure failure stays here
  event-streams.json          once packed: each stream's digest; every events.jsonl then
                              events.jsonl.gz (provenance.md 6.7; owner decision 28A)
```

A run writes and reads its streams plain; `benchmark pack` compresses them once the run is final,
before its folder is committed (`provenance.md` 6.7), and every reader of a run's stream finds it,
plain or packed, through `agent/events.event_stream` (plan decision RF-83).

- **One writer per file**, as today: `cli.py` writes the first two, the driver's one scheduling thread the status (section 5.4), the
  review its attempt folder, `benchmark pack` the packed streams and `event-streams.json`.
- **Every record is written atomically**, through the one helper `write_atomic(path, data: bytes)`
  in `swreview/atomic.py` (plan decision RF-31): a temporary file in the same folder, `os.replace`,
  the temporary removed in a `finally`, the bytes UTF-8 with `\n` line endings (never `write_text`,
  which writes `\r\n` on Windows and would move a digest). It serves every record this feature
  writes: `run-provenance.json`, the saved set, `run-status.json`, `prompts.json`,
  `answer-log.json`, `pilot-measurement.json`, `noise-floor.json`, `event-streams.json`, and each
  packed stream, whose compressed bytes it writes as given. It is the product's only atomic
  writer (owner decision 34A; plan decision RF-88): the three older copies of the rule
  (`report/attention_record.py:126-145`, `tokens.py:221-226`, `ir/loader.py:177-195`) move onto it in
  Phase 2, each with its failing-first test; the vocabulary's and the package's bytes do not move,
  and the attention record's, written in text mode at `be01974`, are LF on Windows after it, which no
  reader sees (each parses JSON). Its temporary is `tempfile.NamedTemporaryFile(dir=path.parent,
  prefix=f".{path.name}.", suffix=".tmp", delete=False)`, the attention record writer's naming, so
  that record's tests keep their glob.
- **Promotion.** An attempt that ends completed or as a behavioural stop is kept: its outcome is
  recorded in `run-status.json` first, then its folder is renamed to `<run>/<package_id>/` in
  one rename on the same volume. Every reader keeps reading `<run>/<package_id>/session.json`
  (`benchmark/scorecard.py:489`, `benchmark/compare.py:310-313`) and never learns about attempts.
  A recorded kept attempt whose folder is still under `attempts/` is a promotion a crash
  interrupted, or one whose rename failed: `benchmark resume` completes the rename, and a reader that
  meets it (the scorer, through `package_outcome`) refuses with "promotion incomplete: run
  `swreview benchmark resume <run>`".
- **A rename that fails** (on Windows another process may hold a file of the folder open): the
  attempt stays recorded as kept under `attempts/`, the driver prints one line naming it and goes on
  to the next package, and the run exits 1 after the set naming `swreview benchmark resume {run}`,
  which completes the promotion. The paid attempt is never re-run for it (plan decision RF-22).
- An attempt is promoted only after its worker returned, so a worker that never returned
  (section 5.3) never writes into a folder anything reads.
- `unattended_runtime_minutes` (`benchmark/runner.py:187-198`) is written on the kept attempt's
  session, from the kept attempt's span.

## 5. One attempt

### 5.1 The body: what the pane does

`cli._review_fn` (`cli.py:2192-2223`) becomes the attempt body. It calls `start_review` with
what the pane's `_start_review` passes, then plays the review through `scripted-answers.md`'s
`drive_review`.

**What reaches the body** (plan decision RF-44). `run_benchmark` calls the review function as today,
`review_fn(package_dir, out_dir, *, provider, model, effort, efficiency)` with `explain_findings`
forwarded only when true (`benchmark/runner.py:243-251`), plus one new keyword, `attempt`: a frozen
`AttemptRequest` in `benchmark/runner.py` carrying what the call does not. Its fields land with their
slices: `model_view` and `standards_profile` (the parity slice, so `_review_fn` passes both to the
review and SC-003's parity test compares like with like), `case_file` (the `CaseFile`
`preflight_set` loaded, or `None`) and `max_answer_turns` (the scripted-answers slice), and `stop`
(the robustness slice: the attempt's stop event, read by `use_retry` and `drive_review`).
`run_benchmark` gains the matching keyword parameters. Each new input is one field of one value, so
an injected review function needs one keyword more, whatever the values; forwarding each only when it
differed from a default would pass the stop and the bound on every benchmark run anyway, and hide
which keywords a function receives behind their values.

| `start_review` argument | The pane (`chat/server.py:2119-2139`) | A benchmark attempt | Kind |
|---|---|---|---|
| `provider` | `provider_factory(settings, pane_efficiency(provider))` (`:619-637`) | `provider_factory(settings, efficiency)`, or, for the run's first attempt, the adapter section 3 row 3 built (RF-60); then `use_retry(BENCHMARK_RETRY, stop_requested=attempt.stop.is_set)` on it | transport: the retry policy (section 6) |
| `model`, `effort` | the add-in's settings | `--model`, `--effort` | recorded, equal when the same values are typed |
| `efficiency`, `model_view` | `pane_defaults(provider)` | `ResolvedReview` | equal under `--pane-defaults` |
| `explain_findings` | `defaults.explain_findings` | `ResolvedReview` | equal under `--pane-defaults` with nothing typed |
| `standards_profile` | the add-in's profile | `--standards-profile` | equal when the same file is named |
| `engineering_context` (016) | default `None` | default `None` | compared semantic input; neither surface automatically attaches a context. Explicit attachment initially belongs to the offline `review` CLI, outside pane/benchmark parity. |
| `max_steps` | default (`DEFAULT_MAX_STEPS`) | default | equal |
| `package_dir`, `out_dir` (positional) | `chat.run_dir` for both (`:2121-2123`): the pane reviews in place | the package folder and `attempts/<package>/<n>/` | transport: reviewing in place and reviewing into another folder behave the same offline, with no bridge and so no live-row write-back into the package |
| `key_source`, `retry_of`, `bridge`, `pipe_name`, `bridge_secret`, `bridge_factory`, `callbacks`, `redact` | the pane's | the benchmark's; `bridge=False` always; `redact` the key redactor composed with `without_local_paths` (section 10) | transport; `bridge` is recorded as `live_tools` and shown, never must-match (PP-9) |

Then, as the pane does after its call (`chat/server.py:2145-2151`): `run.tools =
StoppableTools(run.tools, attempt.stop)`, and `run.check_presentation_cancelled` raises
`TurnStopped` when the stop is set. `TurnStopped` and `StoppableTools` move from
`chat/server.py:434-466` to `agent/runner.py`, imported back by the chat server; the two review
lines of `_end_stopped` (`chat/server.py:2283-2290`: `turn.ended {reason: "stopped"}`, then
`cancel_presentation` and `finalize`, `:2253-2257`) become `ReviewRun.end_stopped()`, which the pane,
the attempt and the replay call. The replay's `_RecordingTools.call` raises the shared `TurnStopped`
in place of its `_Stop` (`benchmark/replay.py:253-259`), and its `_drive` closes a stopped turn with
`run.end_stopped()` in place of its own two lines (`:452-455`), which skip `cancel_presentation`;
it does so unconditionally (plan decisions RF-3, RF-33). No replay fixture ends a turn stopped (the
three `events.jsonl` hold only `turn.ended` with `"reason":"end"`: 2, 2 and 4), so the change cannot
move their bytes, and its replay tests pin that nothing else changes. One stop mechanism, not three.

**The wrapper keeps lever 7.** Both adapters decide lever 7's withdrawal through
`tools_withdrawn(tools)`, `isinstance(tools, WithdrawableTools) and tools.tools_withdrawn()`
(`agent/providers/__init__.py:539-567`; `openai_provider.py:444`, `gemini_provider.py:439`), a
runtime-checkable protocol a set without the method fails. `StoppableTools` defines only
`__iter__`, `__len__` and `call` today, so a wrapped `CoverageStopTools` would never send
`tool_choice: none` or `FunctionCallingConfig(mode=NONE)`, while the runner still reopens its own
latch (`agent/runner.py:1057, 1420-1424`), and nothing would fail. `StoppableTools` therefore gains
`tools_withdrawn()`, returning `tools_withdrawn(self.tools)`: the inner set's answer, `False` for one
that does not implement the protocol. `reopen` needs nothing: the run holds the inner set itself
(plan decision RF-18). The pane's wrapper, which has the same gap today, gets it with the move.

In order: write `prompts.json` (section 12) with the system prompt and the opening message; call
`drive_review(run, attempt.case_file, max_answer_turns=attempt.max_answer_turns,
stop_requested=attempt.stop.is_set)`; on
`TurnStopped`, `run.end_stopped()`; finally rewrite `prompts.json` with every user message and
`run.close()`.

**The one seam this needs from `scripted-answers.md` section 3**: `drive_review` takes
`stop_requested`, checks it at each answer point before sending, and a set stop ends the loop
with `ended: "stopped"`. Without it a review whose turns call no tool would keep taking answer
turns after its wall clock.

### 5.2 The control: what an attempt listens to

A listener on the attempt's sink (`callbacks`; listeners run after each event is written,
`agent/events.py:115-119`) keeps: the monotonic time of the last event of any type; the tool
calls in progress (`tool.started` without its `tool.finished`); each `turn.ended` reason; the
first `error` event carrying `stop_reason` (section 8); each `usage` event's `served_model`
(section 7), the first of which also shows that a round was answered (section 8's inference). It never raises: a listener's exception would surface inside the adapter's round
loop. A served model outside the requested model's aliases, or on resume outside the run's
(section 11), is recorded and sets the stop. "The stop" is one `threading.Event` per attempt,
`AttemptRequest.stop` (section 5.1): the listener and the wall clock set it, and the retry loop,
`StoppableTools` and `drive_review` read it.

### 5.3 The worker and the wall clock (FR-037)

The body runs on a `threading.Thread(daemon=True)`, which hands its result or its exception back
through a `queue.Queue`; the driver's thread waits for it with a timeout, so the limit holds whatever
the stream does. Not the pane's executor (`chat/server.py:2176-2184`): an executor's workers are not
daemon threads, and `concurrent.futures` joins them at interpreter exit, so an abandoned attempt
blocked in a read (Gemini's client sets no timeout of its own) would hang the process at exit (plan
decision RF-50). The driver waits in slices of about 1 s (`queue.get(timeout=...)`), re-checking the
clock each time, never in one long `join` or `Future.result(timeout)`: on Windows a long wait of that
kind is not reliably interrupted by Ctrl-C (CPython bpo-29971), so an interrupt could otherwise go
unseen until W (plan decision RF-22).

- **W**, `--package-time-limit`, bounds the whole attempt: setup, the opening turn, every answer
  turn and the explanation pass.
- At W the driver records `stream_active_at_limit`: **active** when the sink wrote an event of
  any type within the last **A** seconds, or a tool call is in progress (a running tool is the
  arm's own work); **silent** otherwise. It then sets the stop, so the next tool boundary raises
  `TurnStopped`. Nothing closes the adapter's client: no adapter has a close seam (the SDK client is
  private, `openai_provider.py:290`, `gemini_provider.py:312`, and shared with the adapter's
  `for_presentation` copy, `openai_provider.py:316-331`), and a read blocked in a silent stream is
  bounded by G and the daemon worker below (plan decision RF-71).
- It then waits up to **G** more. A worker that returns is classified (section 9). One that does
  not is `abandoned`: recorded, left running as the daemon thread it is, which dies with the process
  and never holds it at exit, its folder never promoted.
- **A = 600 s** (`STREAM_ACTIVITY_WINDOW_S`): the OpenAI library's own read timeout
  (`openai` 3.13.0 `_constants.py:7`, 600 s between bytes), the provider library's judgement of a
  dead stream; a reasoning pause shorter than that is activity. **G = 900 s** (`STOP_GRACE_S`):
  one response at the output ceiling (32,000 tokens, `agent/settings.py:114-118`) finishes
  within it. Both are recorded (`provenance.md` section 1) and injectable in tests.
- Ctrl-C while an attempt runs: the attempt is recorded `interrupted`, the stop is set, and the
  interrupt propagates (click exits 1). Resume re-runs it.

- **Start and poll** (owner decision 36A; plan decision RF-90): the worker and the wait are two
  calls, `start_attempt(...) -> RunningAttempt`, which starts the daemon worker, and
  `RunningAttempt.poll(now) -> AttemptOutcome | None`, which applies W, A and G at each call without
  blocking; `run_attempt` is the two in a loop of `WAIT_SLICE_S` slices, so one attempt behaves as
  above, and section 5.4's scheduler polls several.

This resolves research §8.10's open point: stream activity is any event on the attempt's stream
within A, or a tool in progress, at the moment W is reached.

### 5.4 Packages at once (`--jobs`; owner decision 36A)

`benchmark run --jobs N` (default 1) reviews up to N packages of the set at once; at the default it
reviews them one at a time, as `run_benchmark` does today (`benchmark/runner.py:236`). One scheduler
in `benchmark/runner.py`, which `run_benchmark` and `resume_benchmark` both call, runs on the calling
thread only (plan decision RF-90):

- It re-hashes the standards profile (section 14) and starts an attempt for the next package in set
  order whenever fewer than N are in flight. A package waiting for a slot is not timed: each
  attempt's W runs from its own start.
- It polls every attempt in flight in slices of `WAIT_SLICE_S`; when one ends it records the outcome
  in `run-status.json`, promotes a kept attempt (section 4) and prints the package's line (section
  14). Every write of the run's shared records is this thread's, so no two interleave and the record
  needs no lock; `run-status.json` lists the packages in set order whatever order they end in
  (section 10).
- Each package keeps its own attempt folders, stream, listener, adapter, retry loop (section 6) and
  daemon worker (section 5.3). The one value two attempt bodies share, the run-start adapter's
  one-shot holder (section 3 row 3; plan decision RF-60), is taken under a `threading.Lock`, so
  exactly one attempt uses it.
- An abandoned attempt frees its slot; its daemon worker runs on, never read again (section 5.3).
- A moved profile starts no further attempt; the attempts in flight end as they would; then the run
  exits 1 as section 14 says.
- Ctrl-C reaches the scheduling thread: every stop in flight is set, each attempt is recorded
  `interrupted`, and the interrupt propagates (plan decision RF-22).
- N is recorded as `jobs` in `run-provenance.json` and is record-only: it changes no review's inputs,
  only when each starts, so it changes nothing measured and is exempt from must-match
  (`provenance.md` section 4). A rate limit that concurrency provokes is retried and counted on its
  own stream as any other (section 6); an exhausted one is an infrastructure failure, re-run by
  resume and never scored (plan risk RK-18).
- `benchmark resume` runs at the recorded N, 1 for a record without it, and takes no `--jobs`
  (section 11).

## 6. Retries (FR-038)

**The layer is the request, inside the adapter.** A request is retried only while it has emitted
no `text.delta`; after a text delta has streamed, a retry would send it twice, so a later failure
ends the turn. That is also all the libraries' own retries cover (the response's start). A package
is never re-run inside a run: an exhausted request is an infrastructure failure, re-run from the
start by `benchmark resume` (section 11).

**Where the loop sits** (plan decision RF-20). Several of today's failure paths emit an `error`
event before they raise: OpenAI's `response.failed` through `_failed` and `_raise_error`, inside
`_stream` (`openai_provider.py:597-598, 725-740`); the stream that ended without a final response
(`:573-579`); every mapped library error through `_mapped` (`:708-723`); and Gemini's mapped errors
through `_report` and `_emit`, inside its own `try` (`gemini_provider.py:564-565, 574-591`). A loop
wrapped around `_stream` would retry those and leave an `error` event, with no `retries`, on the
stream of a request that then succeeded, breaking "counted exactly" and feeding the attempt's
listener a failure that did not happen. So, in each adapter:

- the loop wraps the raw request and the iteration of its stream, and retries only while no
  `text.delta` has been emitted for the request;
- `_failed`, the no-final-response check, `_mapped` and Gemini's `_report` build their error
  without emitting it; the adapter emits the one `error` event, carrying `retries` under a policy,
  after the final failure, so the adapter emits exactly one `error` through its `on_event` per
  failed request and none for a request that succeeded on a retry; with no policy the emission is
  where and what it is today. When the failure then escapes `provider.run`,
  `ReviewRun._run_turn`'s `emit_turn_failed` (`agent/events.py:219-235`) adds its generic body after
  the adapter's (`error_class`, `message`, `retryable: true`, no `stop_reason`, no `retries`), as it
  does today, so the stream holds two `error` events per raised failure. Classification and
  `attempt_facts` read `stop_reason` and `retries` from the bodies that carry them, the adapter's,
  and never count `error` events (plan decision RF-52);
- Gemini's transient transport errors, which the adapter does not map today (it catches
  `errors.APIError` only, `gemini_provider.py:564`), are the SDK's `httpx.TimeoutException`,
  `httpx.NetworkError` and `httpx.RemoteProtocolError`: retryable under a policy, new behaviour; with
  no policy they propagate as today.

- `agent/providers/retry.py` (new): `RetryPolicy(retries, initial_delay_s, max_delay_s)` and the
  one retry loop both adapters call as above (`openai_provider.py` inside `_respond` and `_stream`,
  `:560-598`; `gemini_provider.py` `_stream`, `:523-571`).
- **How a policy reaches an adapter**: an optional extension, `RetryAware` with
  `use_retry(policy: RetryPolicy, *, stop_requested: Callable[[], bool]) -> None`, beside
  `PromptCacheAware` and `ModelViewAware` (`agent/providers/__init__.py:501, 518`), implemented by
  `OpenAIProvider`, `GeminiProvider` and the scripted provider and carried by their
  `for_presentation` copies. The attempt body calls it on the adapter `provider_factory` returns;
  nothing else does. `provider_factory`'s signature does not change, so the test fakes that patch it
  as `factory(settings, efficiency=None)` (`tests/unit/test_cli.py:170-185`) and every fixture built
  on them are untouched. **Not calling it keeps today's behaviour byte for byte**: the OpenAI
  library's two retries (`openai` 3.13.0 `_constants.py:8`), Gemini's single attempt
  (`google-genai` 2.23.0 `_api_client.py:572-573`); the pane and `review` never call it. A policy
  turns the library's retries off (the OpenAI client replaced by `with_options(max_retries=0)`, the
  client built at `openai_provider.py:290`; Gemini's default already makes one attempt) and the
  adapter retries.
- **The stop before each retry**: the loop asks `stop_requested()` before every retry, the backoff's
  sleep included, and once the attempt's stop is set it retries nothing and raises the failure as
  it is. After W a rate limit would otherwise buy up to five backed-off, paid re-requests, pushing
  the worker toward `abandoned`.
- **Retryable** is each adapter's existing judgement (`retryable` on the error it builds): OpenAI
  connection errors (timeouts included), rate limits, status 500 and above, a failed response whose
  error code is `server_error` or `rate_limit_exceeded` or that carries no code, and a stream that
  ended without one (`openai_provider.py:574-580`, `:708-730`); Gemini 429 and 5xx
  (`gemini_provider.py:853-864`); and, new and only under a policy, the three Gemini transport
  errors named above. Never a provider stop (section 8), a failed response with any other code
  among them, an authentication error or another 4xx: the loop retries no error carrying
  `stop_reason`, whatever its `retryable`, which stays what the pane is offered today (plan
  decision RF-76).
- **Backoff with full jitter**: before retry k (1-based), sleep a uniform draw on
  `[0, min(max_delay_s, initial_delay_s × 2^(k-1))]`, raised to the delay a `Retry-After` the
  error carries, capped at `max_delay_s`. The random source and the sleep are injectable.
- `BENCHMARK_RETRY = RetryPolicy(retries=5, initial_delay_s=2.0, max_delay_s=60.0)`: rate limits
  are per minute, and five capped doublings span one. Recorded as `retry_policy`.
- **Counted exactly**, on the stream: the `usage` body gains `retries`, the failed tries before
  this round's request succeeded, and the adapter's `error` body gains `retries`, those made for the
  request that failed. Both are written only when a policy is set, so a pane stream never carries
  `retries`. An attempt's retry count is their sum (section 10's reader).
- **Why not the libraries' own retries, counted** (plan decision RF-35). FR-038 allows "library
  retries off or counted"; keeping each library's jittered retries (the OpenAI client's;
  google-genai 2.23's `HttpRetryOptions`) and counting them through each client's HTTP hook was
  weighed and rejected: those retries cannot ask `stop_requested()` after the wall clock; they do not
  retry OpenAI's `response.failed` or a stream that ended with no response, which reach the adapter
  as events inside an HTTP exchange that succeeded; and a count made in a transport hook cannot be
  tied to the round's `usage` body, where "counted exactly" reads it.

## 7. The served model (FR-039)

- **Read**: OpenAI `Response.model` (`openai` 3.13.0 `types/responses/response.py:291`), Gemini
  the stream's last `model_version` (`google-genai` 2.23.0 `types.py:8600`), the scripted
  provider `ScriptedTurn.served_model` when scripted. Carried on the round's `usage` body as
  `served_model`, omitted when the provider reported none. Today the body names only the
  requested id (`openai_provider.py:458-465`, `gemini_provider.py:460-466`). It is written on every
  stream, the pane's and `review`'s included: which model answered is evidence (Principle I), and
  feature 002's `chat-events.schema.json` is amended for it (plan decision RF-32). The replay
  fixtures do not move: the scripted provider reports a served model only when a turn scripts one,
  and no replay turn does.
- **Documented aliasing**, one table in `benchmark/served.py` (new): OpenAI serves the requested
  id or a dated snapshot of it (`<requested>-YYYY-MM-DD`); Gemini the requested id or a numbered
  version of it (`<requested>-NNN`). One function, `aliases(provider, requested, served)`, also
  used by the price lookup (section 13). An id the table does not cover fails safe (below); a
  commit that extends the table carries the test of the new form.
- **A round served outside the aliases** is recorded by the listener, which sets the stop; the
  attempt ends at the next tool boundary as the infrastructure failure `wrong_model`, naming both
  ids (US7-3). One round is spent, not a review.
- **Not reported** is recorded as not reported and fails nothing: an unknown is not a mismatch
  (Principle I). SC-008 requires it reported on every completed package of a paid run.

## 8. Provider stops (FR-040)

The `error` body gains an optional `stop_reason`, set only for a stop the provider itself
reports, on every stream, the pane's included (plan decision RF-32). It is the signal the
classification reads, on either provider, whether the adapter raised or returned, beside the one
inference below:

| Provider | Signal | `stop_reason` | The turn, unchanged for the pane |
|---|---|---|---|
| Gemini | a finish reason outside `FINISH_REASONS` (`gemini_provider.py:127-145`) | its value: `SAFETY`, `RECITATION`, `BLOCKLIST`, `OTHER`, or any reason added later | reported and returned, the turn ending `error` (`:470-481`, `:578-589`) |
| OpenAI | `incomplete` for a reason other than `max_output_tokens` (`openai_provider.py:638-654`) | the reason: `content_filter`, or any other, or `unset` | raised, as today |
| OpenAI | a `response.failed` event (`openai_provider.py:597-598`) whose `response.error.code` is neither `server_error` nor `rate_limit_exceeded`: a policy code, `invalid_prompt`, `bio_policy`, `misalignment_policy_violation` or `image_content_policy_violation` (`openai` 3.13.0 `types/responses/response_error.py`), or any other code, which FR-040 makes a provider stop too; `_failed` (`:725-729`) reads the code | the code | raised, as today |
| OpenAI | a 400 whose code (`APIError.code`, `openai` 3.13.0 `_exceptions.py:61`) is one of those four policy codes, read by `_mapped` (`:708-723`) | the code | raised, as today |
| OpenAI | a 400 whose code is `context_length_exceeded` | `context_length_exceeded` | raised, as today |
| Gemini | a 400 whose message states the input token limit (one named pattern, pinned by a test on the documented message) | `input_token_limit` | raised, as today |

A failed response with `server_error`, `rate_limit_exceeded` or no code stays a retryable failure
(section 6), and a 400 with any other code but `context_length_exceeded` stays the non-retryable
`provider_error` it is today: a request the service refuses for its shape, not a stop (plan decision
RF-76).

The last two rows read an overflowing context as the arm's own outcome, as D2 reads the step and
output limits: a history lever that lets a review overflow must not have that run removed and
re-run. Owner decision 26A settles it: a context overflow is the behavioural stop `provider_stop`
with its reason, never an infrastructure failure (the spec's US7 list).

**An overflow the Gemini pattern misses** (the message is unverified without a key, plan RK-7) must
not become a `provider_error` that resume re-runs until the package drops out of its arm. So the
classification (section 9) infers it: a `GeminiRequestError` (a 4xx other than 401, 403 and 429,
`gemini_provider.py:170-173, 853-864`) without `stop_reason` that escapes an attempt after at least
one of its rounds was answered (the listener saw a `usage` event, section 5.2) is `provider_stop`
with the reason `input_token_limit_inferred`. Its request was one the service had accepted plus the
review's own grown history, so its refusal is the arm's outcome whatever the wording; the reason
names the inference on every page that shows it, and the attempt's `message` in `run-status.json`
keeps the service's own words for the owner to read when the run is scored. A refusal before any
answered round (a key, a model or a request shape every package would meet) stays `provider_error`.
OpenAI needs no inference: its overflow is an exact code (plan decision RF-77).

**The error is recognised by its type**: `isinstance(error, GeminiRequestError)` on the exception
that escaped the review, which is the adapter's own object, since the runner records a failed turn
and re-raises it unchanged (`agent/runner.py:1434-1442`); never by its message, its `error_class`
text or the run's provider. `benchmark/attempt.py` imports `GeminiRequestError` from
`agent/providers/gemini_provider.py` inside that branch, not at module level, so a run that never
reaches it never loads `google-genai` (the adapters are imported lazily,
`agent/providers/__init__.py:661-670`). **The scripted provider builds the case** for section 15's
tests through `ScriptedTurn.fails`, the `ProviderError` instance a turn raises once it has played
its scripted `rounds`: a turn whose one `ScriptedRound` calls a tool with `usage` set (so the
listener sees a `usage` event) and whose `fails` is `GeminiRequestError("gemini 400 FICT request
refused")`, built from its message alone as `_map_error` builds it (`gemini_provider.py:853-864`;
plan decision RF-72), ends `provider_stop` `input_token_limit_inferred`; the same turn with no
rounds fails before any `usage` event and ends `provider_error`. The message names no token limit
on purpose: the inference must not depend on it.

A common base, `ProviderError(RuntimeError)` in `agent/providers/__init__.py`, carries
`error_class`, `retryable` and `stop_reason`, each with a class-level default so both families keep
constructing as they do today (plan decision RF-72): `retryable` a class attribute an instance may
override (`OpenAIProviderError` sets it per instance from its keyword, `openai_provider.py:146-150`;
the Gemini classes per class, `gemini_provider.py:152-190`); `error_class` the instance's value
where one is given (OpenAI's keyword), else `type(self).__name__`, the name Gemini's `_emit`
already writes (`:591-600`); and `stop_reason: str | None = None`, set on the instance for a
reported stop. The base adds no `__init__`, so `GeminiAuthError(msg)`, `_map_error`'s
`failure(mask(...))` (`gemini_provider.py:853-864`) and `OpenAIProviderError(msg, error_class=...,
retryable=...)` construct unchanged. `OpenAIProviderError` (`openai_provider.py:137`) and
`GeminiProviderError` (`gemini_provider.py:152`) subclass it, and the scripted provider raises it.
Messages and classes are unchanged.

## 9. Classification (FR-036, FR-041; D2, D16)

Every attempt ends with one kind and, unless completed, one class:

| Kind | Class | When | On resume |
|---|---|---|---|
| infrastructure | `provider_error` | a `ProviderError` without `stop_reason` escaped the review, after its request's retries, and is not section 8's inferred overflow | re-run |
| infrastructure | `wrong_model` | section 7 | re-run |
| infrastructure | `served_model_changed` | section 11 | re-run; the resume stops |
| infrastructure | `wall_clock_silent` | W reached with the stream silent (section 5.3) | re-run |
| infrastructure | `abandoned` | the worker did not return within G after the stop | re-run |
| infrastructure | `internal_error` | any other exception escaped the review | re-run |
| infrastructure | `interrupted` | the operator stopped the run, or the process ended, during the attempt | re-run |
| behavioural | `max_steps` | a turn ended at its step limit | never |
| behavioural | `truncated` | a turn ended on the output ceiling, or on Gemini's malformed or unexpected tool call (`gemini_provider.py:127-133`) | never |
| behavioural | `provider_stop` | an `error` event carried `stop_reason` (section 8), recorded with it; or section 8's inferred Gemini overflow, recorded `input_token_limit_inferred` | never |
| behavioural | `wall_clock` | W reached with the stream active, and the review returned | never |
| completed | none | every turn ended normally; bound-reached is read from `answer-log.json` (`scripted-answers.md` section 4) | never |

**Precedence**: any infrastructure condition wins, the first recorded; then the first
behavioural stop to occur; else completed. So a wrong model found in round one is a failure
whatever the turn did next, and a review cut at its step limit and later stopped by its clock is
`max_steps`. A behavioural stop ends the review: `drive_review` answers after no turn that ended
otherwise than normally (`scripted-answers.md` section 3), the stop's session is finalized
(`agent/runner.py:1434-1442`, or `end_stopped`), and its state up to the stop is kept and
graded (FR-041).

Never a failure: reaching the answer-turn bound (D16), an unscripted question, a turn ending
`end` with open questions.

## 10. The run-status record

`<run>/run-status.json`, written by the driver's one scheduling thread only (section 5.4), rewritten atomically when an attempt starts
and when it ends:

```json
{
  "run_status_version": 1,
  "packages": {
    "fict-r3-press-fit-a": {
      "kept_attempt": 2,
      "attempts": [
        {"attempt": 1, "started_at": "2026-10-01T09:00:00Z", "ended_at": "2026-10-01T09:04:10Z",
         "resumed": false, "kind": "infrastructure", "class": "provider_error",
         "stop_reason": null, "error_class": "RateLimitError",
         "message": "Rate limit reached for requests", "stream_active_at_limit": null,
         "folder": "attempts/fict-r3-press-fit-a/1"},
        {"attempt": 2, "started_at": "2026-10-02T08:00:00Z", "ended_at": "2026-10-02T08:21:37Z",
         "resumed": true, "kind": "completed", "class": null, "stop_reason": null,
         "error_class": null, "message": null, "stream_active_at_limit": null,
         "folder": "fict-r3-press-fit-a"}
      ]
    }
  }
}
```

| Field | Rule |
|---|---|
| `packages` | every package the run has attempted, in set order whatever order they ended in (section 5.4); a package never reached has no entry |
| `kept_attempt` | the attempt promoted to `<run>/<package_id>/`, or `null`: every attempt so far failed |
| `attempts[].resumed` | `true` for an attempt `benchmark resume` made |
| `attempts[].kind` | `completed`, `behavioural` or `infrastructure`; `null` while running. A `null` on a folder no process is running is read `interrupted` by resume |
| `attempts[].class`, `stop_reason` | section 9; `stop_reason` only for `provider_stop` |
| `attempts[].error_class`, `message` | the escaped exception's class and its one-line message, redacted by the run's redactor (FR-015), then passed through `without_local_paths` (below) |
| `attempts[].stream_active_at_limit` | `true` or `false` when W was reached, else `null` |
| `attempts[].folder` | run-relative, `/`-separated; never absolute (FR-051) |

**No local path** (FR-051's writer half; plan decision RF-41). `benchmark/scrub.py`
`without_local_paths(text, *, run_dir, root=REPO_ROOT) -> str` replaces the run folder, the checkout
root, the temporary folder and the home folder, longest first, case-insensitively, in their
forward-slash, backslash and doubled-backslash spellings (an `OSError`'s text quotes its path
through `repr`), with `<run>`, `<repo>`, `<tmp>` and `<home>`. The driver passes every `message`
through it before recording it, so a `PermissionError` on a file of an attempt folder (the Windows
lock of section 4) records `<run>/attempts/...`; and the attempt body composes it after the run's
key redactor as the review's `redact`, so the runner's generic error body in the attempt's
`events.jsonl` (`emit_error`, `agent/events.py:195-216`) is scrubbed the same way. That is the
whole claim (plan decision RF-73): an adapter emits its own `error` body through `on_event` with key
redaction only (`openai_provider.py:731-740`, `gemini_provider.py:591-600`), and a tool's failure
text reaches `session.json` through the registry (the stored-result failure row names the
tool-results folder, `tools/registry.py:421-431`); neither passes through `redact`. The
committable-folder scanner (`provenance.md` 6.6) is the detector over those and everything else,
and a paid folder it flags is fixed before its commit.

The record holds only what the driver alone knows. What the attempt's stream already records is
read from the attempt folder's stream, `events.jsonl` or, once packed, `events.jsonl.gz`, found by
`agent/events.event_stream` (owner decision 28A; plan decision RF-83), by one function,
`attempt_facts(folder)`, and nowhere else, through the one event-line reader `replay_events` (plan
decision RF-29): each event
goes into a `UsageLedger` (`agent/events.py:158-163`), as `generate_pane_fixture.py:75-77` replays a
log into one, whose new public `rounds()` hands `price_rounds` each round's usage; in the same pass
each `usage` body's `served_model` and `retries`, and each adapter `error` body's `stop_reason` and
`retries` (section 6), are kept beside the round of the same index. It gives the rounds and their
usage, the served ids, the retries, and whether any round was paid for (a failure before the first
round has no usage, FR-034). The billed usage of a failed attempt (D2) is therefore its events', read
by `UsageLedger`'s own rule, not a restatement of it. Readers classify through
`package_outcome(run, package_id)`: the
kept attempt's kind and class, with bound-reached from its answer log, or the last attempt's
failure when nothing is kept. The scorer calls these two functions and copies what they return
into the scorecard (`PackageScore.run_status`, `cost` and `served_models`,
`Scorecard.unscored_packages` and `failed_attempts`, each failed attempt's row with its
run-relative `folder`, `scoring.md` section 7; plan decisions INT-9, RF-16, RF-17), as it copies
`session.usage` today; compare, the verdict and the report read the scorecard, and nothing reads the
file's fields itself. The report opens a failed attempt's stream through that `folder`, plain or
packed (`report.md` 2).

## 11. Resume (FR-043)

`swreview benchmark resume RUN [--standards-profile PATH] [--json]`. Every setting comes from
the run's own records; nothing that changes a review can be typed. It runs at the run's recorded
`jobs` (1 when not recorded) through section 5.4's scheduler, and `--jobs` typed is a usage error,
exit 2: "resume runs at the run's recorded --jobs" (owner decision 36A).

Refused before any review, exit 1, one line:

| Refused | Gist |
|---|---|
| no `run-provenance.json`, or a provenance record older than this feature (`provenance_schema` 1), or packages with a session and no `run-status.json` | "made before runs recorded their status; start a new run" |
| an attempt with no outcome that started less than W + G ago | "may still be running; wait until {time}" |
| the checkout's commit differs from the record's, or either is unknown; the checklist or prompt digest differs | names the field and both values |
| the saved set's digest differs from `set_digest`, or a case file's bytes from their digest in the saved set | names the file by its saved-set path |
| the profile: none recorded but one named; one recorded but none named, or its sha256 differs | names `display_digest` of the recorded digest (`checks/standards/profile.py`; plan decision RF-5), never a path in any written file |
| a `pane_defaults` or `pane_defaults_private` run whose checkout now has a dirty tracked tree, or a digested input holding a carriage return: `provenance.md` 3.2's run-time rules, applied again (plan decision RF-51) | names the rule and, for a carriage return, the file |
| the provider does not resolve (section 3 row 3) | as there; the adapter it builds is the first re-run attempt's (RF-60) |

Then, per package in set order: a kept attempt (completed or behavioural) is skipped and never
appended to; a recorded kept attempt still under `attempts/` is promoted; an attempt without an
outcome is recorded `interrupted`; a package whose last attempt is an infrastructure failure,
or that has none, gets a new attempt, numbered after the last, in a new folder, from the start.
Every earlier attempt and its folder stay (US7-5).

**A differing responding model is refused** (FR-043, S4): on resume the listener also records a
round served by an id that none of the run's kept attempts was served by; the attempt ends at
its next tool boundary as `served_model_changed`, and the resume stops with exit 1 naming both
ids, since every further attempt would measure another model. With no kept attempt there is
nothing to differ from.

## 12. The prompts record (D11, FR-057)

`prompts.json` in the attempt folder, written by the attempt body only:

```json
{"prompts_version": 1,
 "system": "<the system prompt, as sent>",
 "user_messages": ["<the opening message>", "<answer turn 1's message>"]}
```

- `system` is `ReviewRun.system` (built at `agent/runner.py:1756-1767`, sent unchanged by every
  adapter); `user_messages` is every `role: user` entry of `ReviewRun.messages`, in order: the
  opening message first (`:1768-1774`), then one per answer turn.
- Every user message, not only the opening one: an answer turn's message is composed by code,
  the drawing outcome lines above `answers_message` and the regrade line below it
  (`agent/runner.py:1186-1195`), so the recording's `evidence.answered` events do not hold it
  byte for byte. This refines D11's parenthesis; the recording still holds each answer.
- Written before the first turn and again when the body ends, so an abandoned or interrupted
  attempt still records what it sent first.
- Written by the benchmark attempt, through `write_atomic` (section 4), not by `start_review`: the
  pane's run folders do not gain it, and no event carries it. A folder without it reads "not
  recorded" (US6-3).
- Holds no path: neither the census (`tools/query.py:79-107`) nor the package brief
  (`agent/package_brief.py:77-80`, "without exposing a full filesystem path") prints one, and
  the committable-folder test covers the file (`provenance.md` section 6.6).

## 13. Cost (FR-042; D10)

**The table.** `benchmark/prices.yaml` (new), loaded by a strict model (an unknown field is
refused):

```yaml
prices_version: 1
currency: USD
per_tokens: 1000000
models:
  - provider: openai
    model: fict-model-a
    input:        {price: 0.00, source: "<the provider's public pricing page>", date: 2026-10-01}
    cached_input: {price: 0.00, source: "...", date: 2026-10-01}
    output:       {price: 0.00, source: "...", date: 2026-10-01}
```

Every price has its source and date. Prices are filled from the providers' public pages when
the table lands, never guessed; a model with no entry reads cost unknown. Three prices per model,
as FR-042 fixes, and no tiers: no default model (`agent/settings.py:103-107`) is shown to need
them, and a model whose public price is tiered gets no entry, so its cost reads unknown naming it,
until a commit adds tiers with their test (plan decision RF-8). *Amended 2026-10-15 (owner decisions 102A, 103A):* an entry may carry `short_context_max_input_tokens`, the last input count its prices apply to; a round whose input exceeds it is cost unknown, named "`<model>`: long-context tier, not priced". The OpenAI default `gpt-5.6` is not on the pricing page, so the table enters its variants `gpt-5.6-sol`, `-terra` and `-luna` at their short-context prices with 272000, and a round is priced by the variant its served id names. Gemini has no entry (94A). **Cache-write tokens**
(`TokenUsage.cache_write_tokens`, OpenAI only, `agent/providers/__init__.py:167`) have no price of
the three: they are shown as a count and never priced, and the cost's basis says so whenever a round
reports a non-zero count. This settles D10's open column (plan decision INT-5,
research §9, with `report.md` section 4): a fourth price column is configurability FR-042 does not
ask for, and the pane study has no cost threshold (D1).

**Pricing** is per round, from the attempt's `usage` events, not from the session's totals
(`SessionUsage`, `report/session.py:404-421`), for three reasons: the model priced is the one each
round's served id aliases (section 7), which a total cannot carry; Gemini's zero-omission rule below
reads each round's reported total against its addends; and a failed attempt has no session total,
only its events (D2's "the usage it billed"). One function, `price_rounds`, over one provider's
nesting (`agent/providers/__init__.py:149-171`):

| Provider | Rule |
|---|---|
| scripted | never priced: "synthetic" (the null, oracle and scripted runs) |
| OpenAI | input × input price, with cached input priced apart only when `CACHED_SHARE_PUBLISHABLE` (`agent/providers/__init__.py:233`) records the containment verified, otherwise all input at the input price and the cost says "cached input priced as uncached: containment unverified (probe L1)"; output × output price (reasoning is inside output and never added); a non-zero cache-write count is named in the basis, "cache-write tokens counted, not priced" |
| Gemini | (input - cached) × input + cached × cached-input price, or all input at the input price when the cached count is not reported, said so; tool-use prompt tokens × input price; (output + thoughts) × output price. A missing addend reads 0 only when the round's reported total equals the sum of the addends it reported (the service omits zero counts), otherwise unknown, naming it |

- The model priced is the one the served id aliases (section 7); an unreported served model is
  cost unknown, "responding model not reported".
- **Unknown, never 0 and never a scoring failure**: any unpriceable round makes the attempt's
  cost unknown, naming each missing thing once (a model with no entry, a count not reported, no
  usage at all). Compare does not refuse an unknown cost.
- **Package cost** prices the kept attempt's rounds; **run spend** prices every attempt's, the
  failures' included (D2's "the usage it billed"). Both call `price_rounds`; the scorer and the
  report render them.
- **What the page names.** The scorer copies the source and date of each price of every table
  entry a run's rounds were priced by into `Scorecard.price_table` (`scoring.md` 7; plan decision
  RF-45), which the report's head prints; `null` when no round was priced.

## 14. Output and exits

- `benchmark run` and `benchmark resume` attempt every package, whatever an earlier one did
  (FR-036), printing one whole line per package as it ends (in set order at the default N; in
  the order packages end above it, section 5.4): its kind and class, a provider stop's reason, a
  failure's error class and retries.
- Exit 0 when every package has a promoted kept attempt; exit 1 after the set when any package's
  last attempt is an infrastructure failure or its promotion failed (section 4), naming each and
  `swreview benchmark resume {run}`; exit 1 at once for section 3's and section 11's refusals, and
  when the standards profile's bytes change during the run (re-hashed before each attempt), naming
  `display_digest` of the recorded and of the current digest; exit 2 for usage errors.
- `--json` carries the same, per package, in set order: `kind`, `class`, `stop_reason`, `attempts`.

## 15. Tests

Every test fails before its behaviour exists (constitution III). Offline, no key, no seat
(FR-047), but for the one live test below, run on demand with a key (owner decision 35A). Each test is the gate of the slice that lands its behaviour (the plan's delivery order):
a file or bullet below marked with a later slice is that slice's, and every unmarked one is the
parity slice's. The tests under `reviewer/tests/integration/` below are **not** marked `integration`,
which `reviewer/tests/conftest.py:72-82` skips wherever the native package is absent; they need
none, as `tests/integration/test_coverage_stop.py` documents (plan decision RF-26). The scripted
provider gains, for these tests only and with the robustness slice: `ScriptedTurn.fails`, the
`ProviderError` instance the turn raises, of whichever subclass the test builds (a `GeminiRequestError`
for section 8's inferred overflow): the turn plays its scripted `rounds` first, each emitting its
`usage`, then emits an `error` body with the instance's `error_class`, `retries` and `stop_reason`
and raises the instance in place of its closing text, whose `usage` it does not emit;
`ScriptedTurn.hang` (a `threading.Event` it waits on, emitting nothing); `ScriptedTurn.stop_reason`
with `end_reason="error"` (Gemini's reported stop); `ScriptedTurn.served_model`;
`ScriptedTurn.delta_interval_s` (text streamed slowly, so a clock fires mid-stream); and `use_retry`,
so a scripted `fails` is retried by the one loop. Without them the scripted provider's bytes are
unchanged.

**Existing tests this contract moves**, each named with the slice that changes it:
`tests/unit/test_model_view_settings.py:70` compares `pane_defaults(provider)` with
`PaneDefaults(pane_efficiency(provider), MODEL_VIEW_PANE)`; `PaneDefaults` is a positional frozen
dataclass (`agent/settings.py:559-563`) gaining `explain_findings`, so the parity slice rewrites the
expected value with `explain_findings=True`, and `cli.py:434`'s all-off base with `False`. The six
`run_benchmark(...)` calls (`tests/unit/test_answer_key_isolation.py`, two;
`tests/integration/test_answer_key_isolation.py`, `tests/unit/test_benchmark_presentation.py`,
`tests/unit/test_benchmark_runner.py` and `tests/unit/test_efficiency_settings.py`, one each) pass
the `PreflightedSet` that `run_benchmark` requires from the scripted-answers slice
(`preflight_set`, section 3 row 4). The three injected fakes that accept exactly today's four
keywords (`tests/unit/test_answer_key_isolation.py:118-127`, `tests/unit/test_efficiency_settings.py:
365-374`, `tests/integration/test_answer_key_isolation.py:56-64`) take the `attempt` keyword from the
parity slice (section 5.1; RF-44), and `tests/unit/test_answer_key_isolation.py:109-110`'s `pkg-1`,
a folder with no `package.json`, is given one in the generator slice, whose existence check
(`cases.md` 4.4) would refuse it. The `fake_provider` fixture (`tests/unit/test_cli.py:163-185`)
and everything built on it stay as they are: `provider_factory`'s signature does not change, and a
run builds one adapter per attempt, the first attempt's being section 3 row 3's (RF-60), so
`test_benchmark_run_passes_the_provider_and_model_to_every_package` and
`test_benchmark_run_without_a_model_takes_the_providers_default` (`:2438-2485`) still read one
adapter for their one-package set. `test_benchmark_run_on_a_missing_set_exits_1` (`:2488-2493`)
passes no `--provider`, so once row 3 runs before the set the default, OpenAI (`cli.py:2254`,
`agent/settings.py:97`), would stop it at row 3 on a machine without `OPENAI_API_KEY`
(`openai_provider.py:282-283`) and it would pin nothing about the set: the parity slice passes
`--provider fake` and asserts that the one line names the missing set file. In the parity slice `run_benchmark` gains `root: Path =
REPO_ROOT`, forwarded to `load_set`, which `tests/unit/test_answer_key_isolation.py`'s call over a
set under a temporary `benchmarks/sets/` passes, its smuggle test's `load_set` stub taking the
keyword; the scripted-answers slice's `PreflightedSet` argument replaces the set path and the root
(`cases.md` 9; RF-61).

`reviewer/tests/unit/test_review_settings.py`:
- `test_pane_defaults_include_the_explanation_pass` (PP-1, FR-015, US2-1);
- `test_no_explain_findings_overrides_pane_defaults_and_the_session_records_it_off` (US2-7);
- `test_untyped_explanations_stay_off_without_pane_defaults`;
- `test_the_chat_server_reads_explanations_from_pane_defaults` (one decision, PP-1);
- `test_benchmark_replay_still_resolves_levers_and_model_view`.

`reviewer/tests/unit/test_benchmark_run_options.py`:
- `test_benchmark_run_resolves_pane_defaults_model_view_and_profile_through_review_settings`
  (FR-011; a spy on `_review_settings` is the only resolver called, once, with
  `allow_workstation_levers=False` and the typed study and arm, RF-19);
- `test_benchmark_run_still_refuses_a_workstation_lever_and_a_study_arm_contradiction` (exit 2,
  "workstation harness", through `_review_settings`; RF-19);
- each section 3 refusal before any review, in order, a spy body never called and no folder
  written: `test_a_non_empty_out_folder_is_refused` (the parity slice's message, naming no command),
  `test_an_unreadable_profile_stops_the_benchmark_with_one_line` and
  `test_an_invalid_profile_stops_the_benchmark_with_one_line` (US2-2, FR-050),
  `test_review_still_records_a_profile_refusal_and_goes_on` (FR-050),
  `test_an_unresolvable_effort_is_refused_once` (one adapter built, no review), and
  `test_a_package_id_attempts_is_refused` (the scripted-answers slice: row 4 runs in
  `preflight_set`, lane A3's);
- `test_a_pane_study_refuses_a_model_the_price_table_cannot_price` (the robustness slice: row 6's
  price entry, for `pane_defaults` and `pane_defaults_private`, naming the provider and model; a
  lever study over the same model is not refused; RF-79);
- `test_a_package_time_limit_below_one_is_a_usage_error` (exit 2) and
  `test_the_typed_package_time_limit_is_recorded_as_package_time_limit_s` (the robustness slice,
  with the option);
- `test_pane_defaults_and_model_view_switches_declare_a_study_for_p3` and
  `test_a_profile_alone_declares_no_study` (PP-6);
- `test_provenance_and_saved_set_exist_before_the_first_review` (a body that fails reading them);
- `test_run_benchmark_hands_the_review_function_the_model_view_and_the_profile` (the parity slice;
  `attempt` carries them, and `_review_fn` passes them to the review), grown by the scripted-answers
  slice with the case file and the bound and by the robustness slice with the stop (RF-44);
- `test_a_non_empty_out_folder_names_resume` (the robustness slice: row 1's pointer).

`reviewer/tests/unit/test_cli.py`, beside the two adapter-count tests (`:2438-2485`), since the
`fake_provider` fixture (`:162-185`) and its `RecordingProvider` (`:109-138`) are that module's and
no conftest's (plan decision RF-81): `test_the_run_start_adapter_is_the_first_attempts`, a
two-package set building exactly two adapters through `fake_provider`, the first before any folder
is written and used by the first package's review; its resume half, a resume building one per
re-run attempt the same way, lands with the robustness slice (RF-60).

`reviewer/tests/unit/test_benchmark_pane_parity.py`:
- `test_a_pane_defaults_attempt_starts_reviews_as_the_pane_does` (FR-012, SC-003; the parity
  slice's gate): the `start_review` arguments of `chat/server._start_review` and of a
  `--pane-defaults` benchmark review on one package, captured by a spy, differ only in section
  5.1's transport rows, `package_dir` and `out_dir` among them; the two sessions' `efficiency`,
  `model_view`, `explanations_enabled` and
  `provider_info` (less `key_source`) are equal. In the parity slice the benchmark still reviews
  through `_review_fn` and `run_review`, which wrap nothing;
- `test_benchmark_and_pane_attempts_wrap_tools_in_the_one_stoppable_tools` (the robustness slice's
  gate, when the attempt body and the moved classes land): both runs' `tools` are
  `agent.runner.StoppableTools`, and the replay's stopped turn ends through `end_stopped`,
  unconditionally, its close-out calling `cancel_presentation` and `finalize` as the pane's does
  (RF-3, RF-33).

`reviewer/tests/unit/test_benchmark_attempts.py` (the robustness slice; SC-007's pieces, each alone):
- `test_a_provider_error_after_retries_is_an_infrastructure_failure_with_its_exact_retry_count`
  (US7-1) and `test_the_other_packages_complete`;
- `test_a_gemini_safety_stop_is_a_behavioural_provider_stop_with_its_reason` and
  `test_an_openai_content_filter_stop_is_a_behavioural_provider_stop_with_its_reason` (US7-2,
  FR-040), neither a provider error nor a completed review;
- `test_an_unnamed_stop_reason_on_either_provider_is_a_provider_stop_with_its_reason` (FR-040);
- `test_an_openai_policy_failure_is_a_provider_stop_and_never_retried` (FR-040, RF-76): a
  `response.failed` with `invalid_prompt` and a 400 with `bio_policy`, each under the benchmark's
  policy, send one request, retry nothing and end `provider_stop` with the code; a `response.failed`
  with `server_error` is retried and, exhausted, is a `provider_error`;
- `test_a_context_overflow_is_a_provider_stop` (section 8);
- `test_an_unrecognised_gemini_request_error_after_an_answered_round_is_an_inferred_overflow` (26A,
  RF-77), scripted as section 8 says (one answered round, then `fails=GeminiRequestError(...)`):
  kept and promoted as `provider_stop` with `input_token_limit_inferred`, the service's message in
  `run-status.json`; and `test_a_gemini_request_error_before_any_answered_round_stays_a_provider_error`
  (the same turn with no rounds);
- `test_the_inferred_overflow_is_recognised_by_type` (section 8): after an answered round, an
  `OpenAIProviderError(msg, error_class="GeminiRequestError", retryable=False)` stays
  `provider_error`, and a `GeminiRequestError` whose message names no token limit is inferred;
- `test_a_served_model_outside_the_aliases_fails_the_attempt_at_the_next_tool_boundary` and
  `test_a_dated_snapshot_is_within_the_aliases` and
  `test_an_unreported_served_model_fails_nothing` (US7-3, FR-039);
- `test_a_silent_stream_at_the_wall_clock_is_an_infrastructure_failure` and
  `test_an_active_stream_at_the_wall_clock_is_a_behavioural_stop_not_re_run` (US7-4, FR-037);
- `test_a_tool_in_progress_at_the_wall_clock_counts_as_activity`;
- `test_a_worker_that_does_not_return_within_the_grace_is_abandoned_and_never_promoted`;
- `test_a_hung_attempt_is_abandoned_and_the_process_still_exits`: a subprocess runs a set whose
  scripted turn hangs, with W and G injected short, and ends within G plus a margin; the attempt is
  `abandoned` (RF-50);
- `test_an_internal_error_naming_a_local_path_records_no_local_path`: a body raising a
  `PermissionError` that names a file of its attempt folder; `run-status.json`'s `message` and the
  attempt's `error` bodies read `<run>/attempts/...`, and `provenance.md` 6.6's scanner finds nothing
  in the run folder (RF-41);
- `test_attempt_facts_reads_through_replay_events_into_the_usage_ledger` (a spy on both; the rounds
  `price_rounds` receives are `UsageLedger.rounds()`'s; RF-29);
- `test_an_adapter_error_naming_a_local_path_is_found_by_the_scanner`: an adapter-emitted `error`
  body naming the attempt folder is written as the adapter wrote it, and `provenance.md` 6.6's
  scanner flags the run folder (RF-73);
- `test_classification_reads_the_adapters_error_body_not_the_runners` (a raised `ProviderError` with
  `stop_reason`: two `error` events on the stream, one `provider_stop` with its reason, and the
  retries counted once; RF-52);
- `test_the_wall_clock_stops_answer_turns` (the `stop_requested` seam);
- `test_the_stop_wrapper_forwards_tools_withdrawn`: `providers.tools_withdrawn(StoppableTools(tools,
  stop))` follows the inner set's `tools_withdrawn()`, and is false for an inner set without it
  (fails at `be01974`, where the wrapper has no such method; RF-18). The scripted provider never
  reads `tools_withdrawn` (`agent/providers/fake.py` has no reference to it), so the round-level
  half is `reviewer/tests/integration/test_coverage_stop.py`'s (below; RF-63);
- `test_a_profile_changed_between_attempts_stops_the_run_with_exit_1_naming_both_digests` (the
  profile re-hashed before each attempt, RUN-04; section 14);
- `test_a_reader_meeting_an_incomplete_promotion_refuses_naming_resume` (`score` over a run whose
  status records a kept attempt still under `attempts/`; section 4);
- `test_a_failed_promotion_rename_leaves_the_attempt_for_resume` (the rename patched to raise:
  one line, the next package runs, exit 1 naming resume, and resume promotes it; RF-22);
- `test_the_driver_waits_in_short_slices_so_an_interrupt_is_seen` (the wait's slices recorded
  through the injectable clock; RF-22);
- `test_unattended_runtime_is_the_kept_attempts_span` (a package with a failed first attempt: the
  kept attempt's session carries its own span, section 4);
- `test_a_step_limit_is_a_behavioural_stop_and_its_session_is_finalized` (US7-7);
- `test_reaching_the_answer_turn_bound_is_completed` (D16);
- `test_infrastructure_wins_over_a_later_behavioural_stop` and
  `test_the_first_behavioural_stop_wins` (section 9's precedence);
- `test_an_internal_error_is_an_infrastructure_failure_and_the_set_goes_on`;
- `test_ctrl_c_records_the_attempt_interrupted`;
- `test_a_kept_attempt_is_promoted_by_one_rename_and_a_failed_one_stays`;
- `test_status_is_recorded_before_promotion` (a crash between the two is completed by resume);
- `test_every_record_is_written_atomically_with_lf_bytes` (each through `write_atomic`, a spy
  naming every record of section 4 and, since owner decision 34A, the review's own `attention.json`;
  RF-31);
- `test_an_offline_run_without_the_tokenizer_vocabulary_refuses_nothing_and_counts_read_unknown`
  (FR-047, D14.6): the vocabulary made unavailable (`tokens.TokenizerUnavailable`), a scripted set
  runs, scores and reports; every stored `result_tokens` is `null` (`tools/registry.py:646-657`),
  never 0, and nothing is refused.

`reviewer/tests/unit/test_provider_retry.py` (the robustness slice):
- `test_full_jitter_backoff_draws_within_the_capped_doubling` (seeded random, recorded sleeps);
- `test_retry_after_raises_the_delay_up_to_the_cap`;
- `test_a_request_is_retried_only_before_its_first_delta` (a stub stream that fails after one
  delta is not retried: no delta twice);
- in the tests below, "exactly one `error` event" counts the adapter's `on_event` emissions, the
  runner's generic body after an escaped failure being `test_benchmark_attempts.py`'s (RF-52);
- `test_a_failed_response_before_any_delta_is_retried_with_no_error_event_on_the_stream` (its code
  `server_error`, `rate_limit_exceeded` or none; RF-76) and
  `test_a_stream_that_ended_without_a_response_is_retried_with_no_error_event_on_the_stream`: under a
  policy, a first try failing so and a second succeeding leave no `error` event and one `usage` with
  `retries: 1`; with every try failing, exactly one `error` event, carrying `retries` (RF-20);
- `test_gemini_transient_transport_errors_are_retried_only_under_a_policy` (the three `httpx`
  classes; without a policy they propagate as today);
- `test_no_request_is_retried_after_the_attempt_stop_is_set` (`stop_requested` true before the first
  retry: no second request, no sleep, the failure raised as it is; RF-20);
- `test_retries_are_counted_on_the_usage_and_error_bodies`;
- `test_no_policy_keeps_the_library_defaults_and_writes_no_retries_field` (no `use_retry` call, as
  the pane and `review` make none: no `retries` field on any body, the `error` event emitted where it
  is today; `served_model` and `stop_reason` are written whatever the policy, RF-32);
- `test_a_policy_turns_the_openai_library_retries_off` (`max_retries=0`) and
  `test_for_presentation_keeps_the_policy`;
- `test_provider_stops_and_non_retryable_errors_are_never_retried`, a failed response and a 400
  carrying a policy code among them (RF-76).

`reviewer/tests/unit/test_openai_provider.py` and `test_gemini_provider.py` (additions, the robustness
slice):
- the served id on every `usage` body, from a stub response's `model` and `model_version`;
- `stop_reason` on the `error` body for every row of section 8's table, messages unchanged, the
  OpenAI policy rows included; none on a failed response with `server_error`, `rate_limit_exceeded`
  or no code, or on a 400 with another code (RF-76);
- both error classes are `ProviderError`s and construct as before: `GeminiAuthError(msg)`, a
  `_map_error` result and `OpenAIProviderError(msg, error_class=..., retryable=...)` each expose
  `error_class`, `retryable` and `stop_reason` (`None` until a stop sets it; RF-72).

`reviewer/tests/integration/test_coverage_stop.py` (addition, the robustness slice, without the
`integration` marker like the file; RF-63):
`test_the_stop_wrapper_keeps_the_withdrawal`: the file's `respx` replay of the Responses endpoint
(its `Service`, which honours `tool_choice: "none"`) with the run's tools wrapped in
`agent.runner.StoppableTools`, once as an attempt wraps them and once as the pane does: the round
after the checklist closes goes out with `tool_choice: "none"` (`service.tool_choices == [*[None] *
ITEMS, "none"]`), as the unwrapped test at `:218-227` reads, and the wrapper's stop, never set,
changes nothing.

`reviewer/tests/unit/test_events_schema.py` (the robustness slice): the `usage` body's optional `served_model` and
`retries` and the `error` body's optional `stop_reason` and `retries` validate; an event without
them still validates.

`reviewer/tests/unit/test_chat_server.py` (the robustness slice):
`test_the_pane_stream_carries_the_served_model` (a stub
response's model reaches the pane's `usage` event as `served_model`, and no `retries` field is
written; RF-32).

`reviewer/tests/unit/test_atomic.py` (RF-31): `write_atomic` writes the bytes given, LF kept; it
replaces an existing file; the temporary sits in the target's folder, named `.{name}.<random>.tmp`;
with `os.replace` patched to raise, the target keeps its old bytes and no temporary remains.

The migrated writers (owner decision 34A; the parity slice's Phase 2 tasks; plan decision RF-88), one
test in each writer's own file, each through a spy on `swreview.atomic.write_atomic` and with
`os.replace` patched through `swreview.atomic.os`, each red at `be01974` for want of the call: one
call with the exact bytes, an existing file replaced whole, and on a failed replace the old bytes
kept and no temporary left:
- `reviewer/tests/unit/test_attention_record.py`:
  `test_the_record_is_written_through_the_one_atomic_writer_with_lf_bytes` (no `\r` on any
  platform);
- `reviewer/tests/unit/test_tokens.py`: `test_fetch_writes_the_vocabulary_through_the_one_atomic_writer`;
- `reviewer/tests/unit/test_ir_loader_append.py`:
  `test_the_merged_package_is_written_through_the_one_atomic_writer` (the bytes `be01974` writes).
The three existing failure tests (`test_attention_record.py:168-188`, `test_ir_loader_append.py:182-198`,
`test_checks_first_interference.py:306-331`) patch `os.replace` through `swreview.atomic.os` from the
migration on, what they assert unchanged.

`reviewer/tests/unit/test_benchmark_resume.py` (the robustness slice):
- `test_resume_re_runs_only_infrastructure_failures_from_the_start_keeping_their_attempts`
  (US7-5, FR-043);
- `test_resume_never_appends_to_a_completed_or_stopped_package`;
- `test_resume_refuses_a_differing_responding_model_and_stops` (FR-043);
- each section 11 refusal, including `test_resume_refuses_an_attempt_that_may_still_be_running`
  and `test_resume_refuses_a_changed_case_file`;
- `test_resume_runs_packages_the_run_never_reached`;
- `test_resume_of_a_pane_study_refuses_a_dirty_tree_and_a_carriage_return` (RF-51), and a lever
  study's resume applies neither rule;
- `test_resume_completes_an_interrupted_promotion`.

`reviewer/tests/unit/test_benchmark_jobs.py` (the robustness slice; owner decision 36A; section 5.4),
over the scripted provider, or an injected review function where a test holds a review open, the
clocks injected:
- `test_packages_run_at_once_up_to_n_and_never_more` (at `--jobs 3` over five packages, never more
  than 3 in flight and 3 while three are held; packages start in set order);
- `test_jobs_one_runs_one_package_at_a_time_as_before` (at `--jobs 1` and with `jobs` not passed: each
  attempt starts after the one before it ended; the lines, the `--json` payload and `run-status.json`'s
  bytes equal those `test_run_prints_one_line_per_package_and_json_carries_each_outcome` pins);
- `test_the_run_status_record_stays_valid_under_concurrency` (every write by the scheduling thread,
  each parsing and keeping every row before it, the final record in set order, each failure's
  retries the scripted count);
- `test_each_package_keeps_its_own_folder_stream_and_worker`;
- `test_the_run_start_adapter_serves_exactly_one_attempt_under_concurrency` (RF-60);
- `test_lines_print_whole_as_packages_end_and_json_keeps_set_order`;
- `test_a_silent_package_holds_only_its_own_slot` (abandoned, the others complete, the process
  exits; RF-50);
- `test_ctrl_c_under_concurrency_records_every_running_attempt_interrupted` (RF-22);
- `test_a_profile_changed_under_concurrency_starts_no_further_attempt`;
- `test_jobs_below_one_is_a_usage_error` (exit 2, no folder written);
- `test_resume_runs_at_the_recorded_jobs_and_takes_no_jobs_option`.

`reviewer/tests/live/test_benchmark_live_attempt.py` (the robustness slice; owner decision 35A; plan
decision RF-89), marked `live`, skipped without a provider key, run on demand only and first green at
quickstart P0: `test_one_real_benchmark_attempt_records_every_field_of_its_row`, one real attempt of
`kalo-fit-1` (the anchor with a case file) through `benchmark run`, `score` and `report` from a
one-entry set under `tmp_path` naming the committed files by absolute path: the package completed
and promoted; `served_models` non-empty and within the requested model's aliases; input and output
tokens above 0; a priced cost (`missing` empty, not synthetic) and the price table named; every final
finding's origin known; `prompts.json` and `answer-log.json` present; the report's transcript page
linked and opening with the recorded system prompt. An authentication, rate-limit or 5xx refusal
skips, naming it, as the other live tests treat one; it counts as green only on `1 passed, 0 skipped`.

`reviewer/tests/integration/test_benchmark_failures.py` (SC-007; the robustness slice): one set, the scripted provider
failing on the first package, hanging silently on the second and safety-stopping the third: the
set completes; the first two are infrastructure failures and appear in no score (the scorer's
test reads the same folder); a resume re-runs exactly those two; the third is a behavioural stop
whose re-asks and forbidden hits are counted.

`reviewer/tests/unit/test_prompts_record.py` (the report slice, which writes `prompts.json`, but for
its one test marked below):
- `test_the_system_prompt_and_opening_message_are_recorded_as_sent` (equal to what the scripted
  provider received, FR-057);
- `test_every_answer_turn_message_is_recorded_byte_for_byte` (with a drawing outcome and a
  regrade line);
- `test_an_abandoned_attempt_still_records_its_opening` (the robustness slice, whose worker it
  needs);
- `test_the_pane_writes_no_prompts_record`.

`reviewer/tests/unit/test_prices.py` (the robustness slice):
- `test_the_committed_table_loads_and_every_price_has_a_source_and_a_date`;
- `test_every_default_non_scripted_model_has_an_entry` (`agent/settings.py:103-107`);
- `test_openai_cached_input_is_priced_as_uncached_until_probe_l1_and_says_so`;
- `test_gemini_cached_input_is_priced_apart` and `test_gemini_thoughts_and_tool_use_are_added`;
- `test_a_missing_gemini_addend_reads_zero_only_when_the_total_agrees`;
- `test_a_cache_write_count_is_named_in_the_basis_and_never_priced` (INT-5);
- `test_the_table_refuses_a_fourth_price_field_and_a_tiers_block` (the strict model; FR-042's three
  prices, RF-8);
- `test_a_model_without_an_entry_is_cost_unknown_naming_it` and
  `test_no_usage_is_cost_unknown_never_zero` (US7-6);
- `test_a_served_snapshot_is_priced_by_its_base_model`;
- `test_scripted_runs_are_synthetic_and_unpriced`;
- `test_run_spend_includes_failed_attempts` (D2);
- `test_recorded_responses_price_every_round` (SC-008 offline: recorded response shapes of both
  providers, a served model, non-zero usage and a priced cost);
- `test_the_scorecard_records_the_price_tables_sources_and_dates` (`Scorecard.price_table` names
  each entry a round was priced by, and is `null` for a scripted run; RF-45).
