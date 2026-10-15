---

description: "Task list for the send-to-model checkbox"
---

# Tasks: Send the Review to the Model Only When the Engineer Wants It

**Input**: Design documents from `/specs/015-review-send-gate/` (`spec.md`, `plan.md`, `research.md`, `data-model.md`, `contracts/`, `quickstart.md`). Amended on 2026-10-09 for the owner's plan review, decisions 68A to 80A (research R7): nine tasks added (T011-T012, T042-T043, T069-T070, T073-T074 and T098), the tasks each decision moves rewritten test-first, and the list renumbered in execution order, every reference with it.

**Prerequisites**: features 001 to 013 on main. The original code map used `838b66b`, which equals this branch's product code at the reviewed docs-only head `8347827`. Before T007-T008, integrate the accepted 010-fine-pitch change from `main` into this branch, record the exact resulting pre-015 commit in `review-2026-10-12.md`, refresh research R3's shared-file intersection and re-verify the cited code paths. The baseline gate must pass before the characterization goldens are captured; they preserve this integrated baseline, not the historical `838b66b`. The current accepted baseline `c93c86a` includes main `017ba0ac`, with both 010 and 014 slice 4 accepted. Its exact merge, intersection and gate/deferred status guard are recorded in `review-2026-10-12.md`; research R3 retains the historical `45b5076`/`ee6571c` map and adds this actual integration. Reuse 014's atomic writer and tests for T009-T010. No licence and no key are needed before Phase W; the tokenizer vocabulary is fetched once (quickstart, Prerequisites). No run folder, recording or real profile is read by a test or enters the repository; every new fixture is fictional (`FICT-`, paths under `C:\Fictional\`).

**Tests**: REQUIRED, and **strictly test-first** (62A, Principle III): every implementation task follows the test task that must be written and must fail first ("Acceptance: red for want of ..."), and names it ("Acceptance: Txxx green"). Two pins come before everything else and are committed **green on the pre-feature code**: the characterization of a ticked review, five scenarios each with its golden, its failures included (T007; owner decision 75A), and the prefix characterization (T008) (research R2.28). Every later commit keeps both byte-equal, and no task regenerates them. One task, T082, is a refactor with no new test: T007 pins its path, and it says so. Five tasks are acceptance tests written after the code they check, and pass with no further code (T056, T077, T080, T098, T109; 009's precedent); T098 is the opt-in measurement of owner decision 70A. The tests that go red **by design** are named, with their file, in the task that moves them (research R4.3), and are edited deliberately there, never loosened. What must not move: T007's five goldens, T008's values, the pane fixture's snapshot part (its labels block gains keys only, in T030), every replay fixture, every check golden (`reviewer/tests/golden`), `test_no_lever_in_pane_settings.py`, `test_session.py`, `test_runner_provider.py`, `test_part_roles.py`, `test_confirmed_drawing_read.py`, `test_answer_batch_roles.py`, `test_replay_fixtures.py`, `test_cli.py` (the command-line review gains nothing, FR-037; T034 pins its printed lines), `PageRuleScanTests.cs`, `ReviewPageSessionsTests.cs`, `ReviewPageQuestionsTests.cs`, `ReviewPagePreparationTests.cs`, `ReviewPageSummaryAcceptanceTests.cs` and `ReviewPageNarrowLayoutTests.cs` (each of the last two runs with the box in place, unedited).

**Gates before every commit** (quickstart, "The gate"). From `reviewer/`, run `SWREVIEW_REQUIRE_TOKENIZER=1 uv run pytest -q -p no:warnings -o addopts="" -m "not live"` and `uv run ruff check src tests`. From the repository root, run `dotnet build extractor/SwReview.sln -c Release --nologo -v q` (zero warnings) and `dotnet test extractor/SwReview.sln -c Release --no-build --nologo`. The add-in tests are part of the gate (62A). Each story phase ends with a gate task that adds research R2.28's replay regeneration step (T033, T057, T081, T091, T110, T118).

**Organization**: Setup (the amendment notes). Foundational: the two pins first, then the shared pieces. Then one phase per story in priority order: US1 checks only (P1, the MVP); US2 Send (P2); US3 work while it waits (P3); US4 a waiting review survives a restart (P3). Then Polish, which holds the adversarial review and the final gate, and Phase W for the pilot workstation.

## Format: `[ID] [P?] [Story] [kind] Lane. Description`

- **[P]**: can run in parallel (different files, no dependency on another unfinished task)
- **[Story]**: `US1` to `US4`; Setup, Foundational, Polish and Workstation tasks carry none
- **[py]**, **[C#]**, **[page]**, **[doc]**: the kind of file the task touches (the Python reviewer; the add-in's C# and its C# tests; the Review page and its C# page tests; documents only)
- **Lane B, R, H, W, C, G, S**: the lane that owns the files the task edits (`plan.md`, "Lanes and file ownership"). Where a task edits one line in another lane's file, it says so.
- **Cause**: historical file:line at `838b66b`, re-verified on 2026-10-09 (research's VERIFIED entries). The pre-015 baseline now includes accepted 010 before the pins; re-verify each cause against that recorded commit before editing. Line numbers drift.
- **Amends NNN**: the other feature's contract or requirement the task changes. The task writes the amendment text in the same commit as the code; T001 places the one-line note pointing here first.
- **[W]**: needs the licensed SOLIDWORKS seat on the pilot workstation

## Path Conventions

- Python: `reviewer/src/swreview/`, tests in `reviewer/tests/`; commands run from `reviewer/` with `uv run`
- C#: `extractor/SwReview.AddIn/`, tests in `extractor/SwReview.AddIn.Tests/` (the offscreen WebView2 page suites included)
- Page: `extractor/SwReview.AddIn/Review/ReviewPage/` (`index.html`, `app.js`, `render.js`, `app.css`)
- Contracts: `specs/015-review-send-gate/contracts/` (written by the plan; a task whose code had to differ reconciles its contract, T115); other features' contracts are edited by the task that changes their shape

---

## Phase 1: Setup

**Purpose**: before any code, every contract this feature amends carries a dated note saying so.

- [x] T001 [doc] Lane C. Add a one-line amendment note to each contract feature 015 amends (`contracts/README.md`, "Contracts of other features this feature amends"). Date it 2026-10-08 and point it at the 015 contract that holds the text. The contracts are:
  - 001: `contracts/README.md`, for `review-session.schema.json`
  - 002: `contracts/README.md` (for `settings.schema.json` and `chat-events.schema.json`), `contracts/chat-api.md`, `contracts/pane-host-messages.md`, `contracts/handoff-export.md`, and `data-model.md` sections 3 and 4
  - 008: `contracts/checks-first.md`, `contracts/answer-batch.md`, `contracts/cost.md`, `contracts/tokenizer.md` and `contracts/replay.md`
  - 009: `contracts/sessions.md`, `contracts/views.md`, `contracts/questions.md`, `contracts/review-summary.md` and `data-model.md` (the words table's `read_only` row, owner decision 73A)
  - 011: `contracts/confirmed-open.md`
  - 013: `contracts/drawing-capability.md` and `contracts/part-roles.md`

  Also add a one-line pointer above the Functional Requirements of four specs, naming the requirements amended: 002 (FR-006), 008 (FR-008, FR-009, FR-030), 009 (FR-015, FR-021) and 013 (FR-040). Documents only. JSON schemas carry no comment, so their notes sit in the owning README. No amended text moves here: each "Amends" task below writes its text with its code (FR-038).
- [x] T002 [doc] Lane C. `.specify/feature.json` names `specs/015-review-send-gate`. *Done with the spec, 2026-10-08.*

**Checkpoint**: every amended contract says so.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: first, the two pins of a ticked review on the code as it was (research R2.28). Then the shared pieces two or more stories build on, each one reading of one thing.

### The pins, first, on the pre-feature code

- [x] T003 [P] [py] Lane G. Write `reviewer/tests/unit/test_recording_provider.py` (research R2.28, "One recording provider"):
  - `tests/support/recording_provider.RecordingProvider` records each `run()` input into one ordered log, **before** its scripted turn runs: the system prompt, and the tools and history encoded as the OpenAI adapter encodes them. A turn that raises has still contributed its input.
  - Beside the encoded bytes, each `run()` entry keeps its raw inputs: the system prompt string, the tool specs (`name`, `description`, `parameters`) and the first message of the history, so a test can count `agent.runner.request_prefix(...)` of what the provider received (owner decision 78A).
  - `for_presentation(max_output_tokens)` returns a provider that records each presentation request into the same log in the same way, marked as a presentation.
  - Two runs of one script give equal logs.

  Acceptance: red for want of the module.
- [x] T004 [py] Lane G. Move `RecordingProvider` and its shared `encoded_tools` function from `reviewer/tests/unit/test_prefix_stability.py` to `reviewer/tests/support/recording_provider.py`, and add `for_presentation` and the raw inputs each `run()` entry keeps (owner decision 78A). **Moved**: `test_prefix_stability.py` imports both names from the helper and drops their old definitions; every assertion is unedited. The encoding rule remains in one place. The six other recorders research R2.28 names stay where they are: `test_cli.py:109`, `test_gate_standards_in_review.py:385`, `test_tool_tiers.py:271` and the three `SpyProvider`s. 015 adds no other recorder. Acceptance: T003 green; `test_prefix_stability.py` green.
- [x] T005 [P] [py] Lane G. Write `reviewer/tests/unit/test_questions_package.py` for the fictional questions package (research R2.25, R4.1). `tests/support/questions_package.py` builds a package, graded with fictional profile A at version 3 as `tests/support/roles_review.py` writes it, such that:
  - A checks-first review under the pane defaults raises two questions, both `source: "code"`: the part-roles question (an unclear part, the `convention_only` state), and one drawing-candidate question (a part with a same-name drawing that is not open).
  - The seat is a `ScriptedReviewBridge` (`tests/support/review_bridge.py`) that reads drawings: `drawing_read: "opens_closed"`.
  - "All bought" withdraws at least one **named** finding of the unclear part (a hygiene finding), besides the folded RMS findings the digest counts and never names (`PrerunResult._finding_lines`, `prerun.py:582-598`).
  - Building twice gives byte-identical packages.
  - Every path is under `C:\Fictional\` and every name is `FICT-`. The owner's denylist scan runs through `tests/support/fixture_denylist.py`, skipped (naming the file) where the denylist is absent.

  Acceptance: red for want of the module.
- [x] T006 [py] Lane G. Implement `reviewer/tests/support/questions_package.py` over existing builders, imported, never copied (DRY): `tests/support/roles_review.py`'s profile and package builders, `tests/support/drawings.py`'s candidate rows and `tests/support/review_bridge.ScriptedReviewBridge`. Extend `roles_review.py` (lane B's helper, in this task) only if its unclear part raises no named finding for the answer to withdraw, keeping `test_answer_batch_roles.py` and `test_runner_part_roles.py` green and unedited. Acceptance: T005 green.
- [x] T007 [py] Lane G. **The characterization of a ticked review, on the pre-feature code** (research R2.28 item 1; FR-035, SC-003; owner decision 75A). Write `reviewer/tests/unit/test_ticked_review_golden.py` and commit its five goldens, one per scenario, under `reviewer/tests/unit/test_ticked_review_golden/` (`pytest-regressions`, `reviewer/pyproject.toml:36`).
  - **The runs**: ticked `POST /sessions` on T006's package and seat, through `test_chat_server.py`'s `app` and `client` fixtures, imported as `test_chat_timing_route.py` imports them, with T004's `RecordingProvider` scripted. Five scenarios, each against its own golden:
    1. **Success**: the opening turn; one answer to the part-roles question that resumes the model (the path `_apply_answers` will hold, with `REGRADED_LINE`); one follow-up; and the explanation pass after each turn that ends `end`. It is posted twice - once with no `send_when_checked` or `recheck` in the body, and once with the body the host will send, `{send_when_checked: true, recheck: false}` (the pre-feature server reads the body with `.get` and ignores keys it does not know, `chat/server.py:1230-1236`) - and both runs equal the one golden.
    2. **A ticked start whose factory raises** (no key): the status, the body and the run folder's listing.
    3. **A first request that raises before any round**.
    4. **A failure after one completed round**, through a small raising wrapper over T004's recorder.
    5. **Stop at the first tool boundary**.
  - **Each golden** holds every `run()` and presentation input, in order; `events.jsonl`; and `session.json`, `report.md` and `attention.json` where the scenario writes them. Times, durations and UUIDs are replaced by placeholders numbered in order of first appearance.
  - **The scenarios** are functions in this test module, each returning the run folder before anything is normalized; T013 imports the success scenario, `play_ticked_review` (DRY), as `test_chat_timing_route.py` imports `test_chat_server.py`'s fixtures.
  - **When**: all five written and committed green, in one commit, **before any task below edits `reviewer/src/`**. They replace the ticked shape checks a later task would otherwise write on changed code: T040 writes no ticked no-key case, and T065 no ticked failed-request case.

  Acceptance: green on the pre-feature code, and byte-equal on a second run. From here on every commit keeps all five byte-equal, and no task in this list regenerates them; only the 014 merge may (T117).
- [x] T008 [P] [py] Lane G. **The prefix characterization, before `_prefix` moves** (research R2.28 item 2, R2.9; `contracts/estimate.md` section 7). Write `reviewer/tests/unit/test_request_prefix_characterization.py` (`data_regression`) and commit its values under `reviewer/tests/unit/test_request_prefix_characterization/`. For each committed replay fixture (`reviewer/tests/fixtures/replay/{big-assembly,small-assembly-a,small-assembly-b}/`) under the pane defaults, it records the sha256 and the length of the first pass's `PlayedReview.prefix` (`benchmark/replay.py:244`, filled from `_prefix(run)` at `:368`). Committed green on the pre-feature code. Acceptance: green on the pre-feature code and byte-equal on a second run. T024's move keeps it green, unedited.

**Checkpoint (the pins)**: T007 and T008 are committed on the pre-feature code, and nothing in `reviewer/src/` has changed.

### The shared pieces

**T009-T010 reused, 2026-10-12:** accepted main already supplies `atomic.py` and its eleven tests. No duplicate helper or red task is written; the integrated baseline gate covers them.

- [x] T009 [P] [py] Lane R. **Only while feature 014 is not on `main`** (research R3, the add/add row; `contracts/records.md` section 8). Write `reviewer/tests/unit/test_atomic.py` with the exact content of branch `014-design-review-eval`'s file of that name. Its eleven tests cover: the bytes as given, with `\n` kept; nothing translated; an empty file; a whole replace; the temporary in the target's folder, named `.{name}.<random>.tmp`; no debris after a success; a failed replace keeping the old bytes and removing the temporary; a clean-up failure never hiding the error; a failed replace over no file; a failed write; and a missing folder, not made. When 014 is on `main` first, skip T009 and T010 and import its `swreview.atomic`. Acceptance: red for want of `swreview.atomic`.
- [x] T010 [py] Lane R. Add `reviewer/src/swreview/atomic.py`, copied whole from 014: its exact name, signature and body, `write_atomic(path: Path, data: bytes) -> None`. The 014 merge keeps one copy. Acceptance: T009 green; T007 byte-equal.
- [x] T011 [P] [py] Lane G. Write `reviewer/tests/unit/test_restart_support.py` (owner decision 76A; research R4.1; `contracts/recheck.md` section 11). `tests/support/restart.py` is the one way a test stands for a restart, a crash or a kill:
  - `restarted_app(run_root, settings)` returns a fresh `create_app` over the same run root, as `test_chat_review_routes.py:205-225` builds a restarted backend: it holds no chat of the first app, and `GET /reviews` of a folder the first app wrote answers from disk.
  - `disk_at(folder, hook)` copies the run folder to a scratch folder when the point `hook` names is reached, as `test_remodel_apply_log.py:307-324` reads the disk at the crash point: it raises nothing and lets the code carry on; the test reads the copy. A test names a point of its own by placing the callable `disk_at` returns where a crash would cut (inside a scripted provider, or in a patched step).
  - The module names one point itself, `BEFORE_REPLACE`: inside `swreview.atomic.write_atomic`, after the temporary is written and before `os.replace`, which `disk_at(folder, BEFORE_REPLACE)` installs. The copy holds the old file and the `.{name}.<random>.tmp` beside it, as a kill there leaves them. It is a point of `disk_at`, not a third helper (owner decision 76A names two).
  - The module's docstring says why a raise inside the same app is neither: it runs code a kill skips (`write_atomic`'s clean-up, `_run_turn`'s `except`, `_play`'s render), and the app still holds the earlier chat, which a restarted backend does not.

  Acceptance: red for want of the module.
- [x] T012 [py] Lane G. Implement `reviewer/tests/support/restart.py` (`restarted_app`, and `disk_at` with its one named point `BEFORE_REPLACE`) over the two precedents, imported, never copied (DRY). `BEFORE_REPLACE` patches `os.replace` through `swreview.atomic.os`, as T013 patches it, copying first and then replacing. Every crash, kill and restart case below uses this module (T062, T087, T094, T096, T098, T099). Acceptance: T011 green.
- [x] T013 [P] [py] Lane R. Write `reviewer/tests/unit/test_session_fields_015.py` (data-model section 4; `contracts/records.md` sections 1 and 8; FR-032, FR-036). It pins:
  - **`ModelStatus`** (`extra="forbid"`):
    - `state` is one of `"not_sent"`, `"send_failed"` and `"sent"`.
    - `document {path, configuration}` and `checked_at` are required.
    - `profile {path, sha256: str | None} | None` and `rechecked_from: UUID | None` are each omitted when `None`.
    - `failures: list[SendFailure]` is omitted when empty.
    - `sent_at`, `estimate` and `opening_finding_ids` are written once sent; each id matches `^F-[0-9]+$`, and the list is omitted when empty.
  - **The other new models**:
    - `SendFailure {at, error_class, reason}`.
    - `SendEstimate {input_tokens: int | None (minimum 0), encoding: "o200k_base", approximate: bool}`.
    - `DrawingOutcome {file, outcome}`.
    - `LiveDetectionRecord` has exactly `prerun.LiveOutcome`'s fields. `LiveOutcome.as_record()` and `from_record()` round-trip every dataclass field; a field added to the dataclass and not carried fails the test.
  - **The session fields**:
    - `ReviewSession.model_status` is declared directly after `provider_info`, so its key precedes `findings` in the written file and the host's 64 KiB head read reaches it (`contracts/recheck.md` section 9).
    - `live_detection` and `drawing_outcomes` join it; each of the three is omitted at its default.
  - **Round-trips and validation**:
    - A session written before this feature, and every committed session (the golden, replay and pane fixtures), round-trips to its own bytes.
    - So does the `session.json` that T007's scenario writes, read from the run folder `play_ticked_review` returns, before normalization. T007's committed golden is not round-tripped: its placeholders stand in for times and UUIDs, so it does not validate as a `ReviewSession`, and the golden is never edited to make it.
    - Each new value validates against the amended `review-session.schema.json`.
  - **The write**: capture `save_session`'s actual baseline output bytes before T014, including its platform newline output. On Windows, today's `Path.write_text(... + "\n", encoding="utf-8")` translates newlines to CRLF; `read_text` must not hide that difference. `save_session` writes through `atomic.write_atomic` with those bytes unchanged, preserving CRLF on Windows and LF where that was the baseline. With `os.replace` patched to raise through `swreview.atomic.os`, the previous `session.json` stays whole (independent US1 byte audit, 2026-10-12).

  Acceptance: red for want of the fields.
- [x] T014 [py] Lane R. Add `ModelStatus`, `SendFailure`, `SendEstimate`, `LiveDetectionRecord`, `DrawingOutcome` and the three `ReviewSession` fields to `report/session.py`. Each is dropped by the serializer at its default, following the pattern of `_omit_empty_finding_explanations` (`report/session.py:582-608`). Also:
  - Make `save_session` (`:650-655`) write through `atomic.write_atomic`. Preserve the old platform newline translation in this caller before encoding the bytes; leave the shared byte-only `atomic.write_atomic` unchanged, and keep T013's captured byte pin and T007's raw-file golden equal.
  - Add `LiveOutcome.as_record` and `from_record` to `prerun.py` (`:461`). These are two methods in lane B's file, added in this task, before lane B starts.
  - In the same commit, edit `specs/001-agentic-design-review/contracts/review-session.schema.json` with `contracts/records.md` section 1's five `$defs` and three properties, none in `required`. `test_session_fields_013.py::test_the_contract_names_exactly_the_sessions_fields` reads both the model and the schema, so they must land together.

  **Amends 001** `review-session.schema.json` and `contracts/README.md`. Acceptance: T013 green; `test_session.py`, `test_session_fields_013.py` and `test_schema_sync.py` green and unedited; T007 byte-equal.
- [x] T015 [P] [py] Lane B. Start `reviewer/tests/unit/test_runner_send.py` with `agent/events.local_now()` (research R2.15, R2.25). It returns an aware `datetime`, equal to `datetime.now(UTC).astimezone()` to the second and carrying the machine's UTC offset. Every caller reads it through the module, so one `monkeypatch.setattr(events, "local_now", ...)` pins every model-status time. Acceptance: red for want of the name.
- [x] T016 [py] Lane B. Add `local_now()` beside `utc_now()` in `agent/events.py` (`:67`). Acceptance: T015 green.
- [x] T017 [P] [py] Lane B. Extend `reviewer/tests/unit/test_chat_sessions.py` (`contracts/review-flow.md` section 2; data-model section 2):
  - `ChatState.AWAITING_SEND == "awaiting_send"`.
  - Four moves are allowed: `extracting -> awaiting_send`, `awaiting_send -> running`, `running -> awaiting_send` and `awaiting_send -> failed`. Every other move out of `awaiting_send` raises `InvalidTransitionError`.
  - `finished` is false in `awaiting_send`, so a waiting chat holds its folder.
  - `public()` reports the state.

  **Moved, red by design and edited deliberately here** (research R4.3): `test_every_state_can_fail` (a path through `awaiting_send` joins its parameters) and `test_a_transition_the_table_does_not_name_raises` (its refused moves gain those of `awaiting_send`). `test_failed_is_terminal` iterates `ChatState` and passes unedited. Acceptance: red for want of the state.
- [x] T018 [py] Lane B. Add `AWAITING_SEND` and its four moves to `chat/sessions.py` (`ChatState`, `TRANSITIONS`, `:68-90`). **Amends 002** `data-model.md` section 3 (the state table). Acceptance: T017 green; T007 byte-equal.
- [x] T019 [P] [py] Lane B. Write `reviewer/tests/unit/test_deferred_provider.py` (`contracts/review-flow.md` section 8; research R2.5):
  - For OpenAI, Gemini and the scripted provider, at every effort level and for a model with no table row, `DeferredProvider.for_settings(settings)` has the real adapter's `name`, `model` and `effort_mapping(effort)`.
  - An effort the model refuses raises the adapter's own error. `start_steps_at` is accepted.
  - `run` and `for_presentation` raise `ProviderNotSent`.
  - **No key read and no SDK client built** (owner decision 74A): with `openai.OpenAI` and `google.genai.Client` patched to raise, and settings whose key raises when read, `for_settings(...)` and `effort_mapping(...)` succeed for every effort. The provider's SDK module may be imported - the effort rule lives in the adapter module, which imports its SDK at its top, and `start_review` calls `effort_mapping` at setup (`runner.py:1581`) - and the test asserts nothing about module imports.
  - It is not `ModelViewAware`, `PromptCacheAware` or `PriorReasoningAware`.
  - Each adapter's `effort_mapping` method returns exactly its module's `effort_mapping_for(model, effort)`.

  Acceptance: red for want of the module.
- [x] T020 [py] Lane B. Add `effort_mapping_for(model, effort)` to three provider modules, each adapter method becoming a one-line delegation: `agent/providers/openai_provider.py` (`:389-407`), `gemini_provider.py` (`:382-406`) and `fake.py` (`:254-256`). Create `agent/providers/deferred.py` (`ProviderNotSent`, and `DeferredProvider` with `for_settings`). Acceptance: T019 green; `test_runner_provider.py` and every provider test green and unedited; T007 byte-equal.
- [x] T021 [py] Lane B. Extend `reviewer/tests/unit/test_runner_send.py` with `configure_provider(provider, session)` (`contracts/review-flow.md` section 8). In this order, it calls:
  - `use_model_view(session.model_view)`, on a `ModelViewAware` provider;
  - `use_prompt_cache(str(session.session_id))`, when lever 3 is on and the provider is `PromptCacheAware`;
  - `drop_prior_reasoning()`, when lever 14 is on and the provider is `PriorReasoningAware`.

  It calls nothing on a `DeferredProvider`. `start_review` makes exactly the hook calls it made before, checked against a spy provider's call log under each lever setting. Acceptance: red for want of the name.
- [x] T022 [py] Lane B. Extract `configure_provider` from `start_review`'s three hooks (`agent/runner.py:1622-1646`) and call it there. Acceptance: T021 green; `test_runner_provider.py` green and unedited; T007 byte-equal.
- [x] T023 [P] [py] Lane B. Start `reviewer/tests/unit/test_send_estimate.py`. `agent.runner.request_prefix(system, tools, opening)` exists, and `benchmark.replay._prefix(run)` returns it called as `request_prefix(run.system, run.tools, run.opening_message)` (checked with a spy). The bytes are proven by T008's characterization: never by comparing the function with the code that now calls it, and never by `test_replay_fixtures.py`'s totals, which read no prefix (research R2.9; `contracts/estimate.md` section 7). Acceptance: red for want of the name.
- [x] T024 [py] Lane B. Move `_prefix`'s body (`benchmark/replay.py:350-361`) into `agent/runner.request_prefix`, with `_prefix` calling it (one function body in lane R's file, in this task). One commit, made after T008 is committed. Acceptance: T023 green; T008 green and **unedited** (the move is byte for byte); `test_replay_fixtures.py` green and unedited; T007 byte-equal.
- [x] T025 [P] [py] Lane B. Write `reviewer/tests/unit/test_questions_identity.py` (`contracts/recheck.md` section 4 step 1; research R2.17). `checks/questions.asks_same(earlier, new)` is true exactly when `question`, `options` and `entity_ids` are equal, in order. Every case that `part_roles.answered_roles` and `drawings._is_confirmed_candidate` decide today gives the same answer when driven through `asks_same`. Acceptance: red for want of the name.
- [x] T026 [py] Lane B. Add `asks_same` to `checks/questions.py`, and make `answered_roles` (`checks/part_roles.py:902-917`) and `_is_confirmed_candidate` (`tools/drawings.py:248-258`) call it. No behaviour change; this is the third use of the rule, so Principle V makes the extraction due. Acceptance: T025 green; `test_part_roles.py`, `test_confirmed_drawing_read.py` and `test_answer_batch_roles.py` green and unedited; T007 byte-equal.
- [x] T027 [P] [py] Lane B. Start `reviewer/tests/unit/test_send_gate_server.py`, importing `test_chat_server.py`'s fixtures and helpers as `test_chat_timing_route.py` does (`contracts/review-flow.md` section 1 step 4; research R2.6). For the same ticked chat, `ChatServer._render_run(run, report_path, run_dir)` writes `report.md` and `attention.json` byte-identical to what `_render_report(chat)` wrote. A ranking or a write that raises is logged and never raises. Acceptance: red for want of the name.
- [x] T028 [py] Lane B. Extract `_render_run` from `_render_report` (`chat/server.py:2259-2281`). **Moved, red by design:** `test_report_start_here.py`'s exact seven-site registry changes only the extracted chat renderer's locator from `_render_report` to `_render_run`; every site must still pass its ranking. `_render_report` still returns at once while `chat.run` is `None`, and otherwise calls it. Acceptance: T027 green; T007 byte-equal.
- [x] T029 [P] [py] Lane R. Extend `reviewer/tests/unit/test_review_words.py` and `test_pane_fixture.py` (`contracts/words.md` section 1; research R2.22, R2.25):
  - **The `send` block** of the words file holds exactly `first_request`, `first_request_approximate`, `without`, `restored`, `failed`, `not_started`, `apply_answers`, `restored_line` and `rerun_failed`. Each sentence and its placeholders are as `words.md` section 1 fixes them (`{tokens}`; `{reason}` and `{time}`; `{when}`). `restored_line` is only the dated Send sentence that follows `read_only_lead`, and repeats none of it (owner decision 73A). The block is read by `SendWords` (`Words.send`), and a missing or misspelt key refuses the file.
  - **The read-only lead key** (owner decision 73A): the file holds `read_only_lead` ("The backend restarted, so this review is shown from its run folder.") and `read_only_off` ("Follow-ups, decisions and answers are off."), and no `read_only` key: a file that still holds one is refused, as any unknown key is. `load_words().read_only` is the two composed with a space between, equal word for word to feature 009's sentence, so `test_chat_review_routes.py` and `test_review_snapshot.py`, which read it, pass unedited. A missing `read_only_lead` or `read_only_off` refuses the file.
  - **The labels**: `labels.errors` gains `NoCredential`, `NotSent`, `NotWaiting`, `ReviewNotActive` and `SettingNotSaved`, with `words.md`'s sentences (`SettingNotSaved` worded for both settings writers, 73A).
  - **The pane fixture**: its labels block equals `load_words().labels` (`test_pane_fixture.py:73`), and its snapshot part (every key but `labels`) is byte-identical to the committed one.

  **Moved, red by design**: whatever `test_review_words.py` pins of the file's block list gains `send`. `test_pane_fixture.py`'s fresh-generation check (`:49`) fails until the fixture is regenerated, which T030 does in the same commit. Acceptance: red for want of the block.
- [x] T030 [py] Lane R. Add the `send:` block and the five `labels.errors` keys to `report/review_words_v1.yaml`, and split its `read_only` key into `read_only_lead` and `read_only_off` (owner decision 73A). In `report/summary.py`'s `Words`, add `SendWords`, replace the `read_only: str` field with the two keys' fields, and add a `read_only` property that composes them with a space between, so `chat/server.py:1681` and every reader of `load_words().read_only` get 009's sentence unchanged. **Amends 009** `data-model.md` (the words table's `read_only` row: two keys, composed). **In the same commit** (lane G's file, in this task), regenerate `extractor/SwReview.AddIn.Tests/Fixtures/review-big-assembly.json` with `uv run python tests/fixtures/pane/generate_pane_fixture.py --write`, so every commit passes the gate. The commit's review confirms the fixture's diff is the five added label keys only (FR-035): the split key is not in the labels block, and the pane fixture's live snapshot has no read-only reason. No later task changes the words file. **Moved, red by design:** `test_workstation_test_plan.py`'s quoted composed read-only row checks `load_words().read_only` against the unchanged literal, rather than searching the split keys' raw YAML for a complete sentence. Every other quoted row remains a raw-source pin, and `test_binding_switch_flip.py` remains unedited. Acceptance: T029 green; `test_chat_review_routes.py` and `test_review_snapshot.py` green and unedited; `ErrorLabelsCoverTheHostTests.EveryClassTheReviewTabCanShowHasASentenceInTheWordsFile` green; every page test green; T007 byte-equal.
- [x] T031 [P] [C#] Lane H. Extend `extractor/SwReview.AddIn.Tests/UserSettingsTests.cs` (`contracts/pane.md` section 1; data-model section 1; FR-002, FR-036):
  - A file without `send_when_checked`, or with JSON `null`, a string or a number for it, reads ticked (`SendsWhenChecked` true).
  - The string and the number each add exactly one load problem, "send_when_checked '{token}' is not true or false; ticked is in use.". The provider, model, run root and stored key still load as today, and the next save drops the bad token.
  - `false` round-trips. A file written before this feature saves to its own bytes. `Clone` keeps the held token.
  - **Two members** (owner decision 73A): the setting is `SendWhenCheckedValue`, the held token, and a settable `bool SendsWhenChecked`; setting it `false` and `true` writes the boolean token, and no `bool?` member exists.
  - The settings schema validates a file with `true`, with `false` and without the key, and refuses a string.

  **Moved**: `RoundTripsEveryFieldThroughATempFileAndSatisfiesTheContract` is edited deliberately so the new field round-trips. Acceptance: red for want of the property.
- [x] T032 [C#] Lane H. In `extractor/SwReview.AddIn/Settings/UserSettings.cs`, add:
  - `[JsonPropertyName("send_when_checked")] JsonElement? SendWhenCheckedValue`, held raw, written back as held, and omitted while none is held;
  - `[JsonIgnore] bool SendsWhenChecked`: `false` exactly for a held JSON `false`, else `true`; its setter stores the boolean as a token (two members, owner decision 73A);
  - `Normalize`'s one load problem, and its clearing of a bad token (`UserSettings.cs:400-445`).

  Add `pane.md` section 1's property to `specs/002-task-pane-assistant/contracts/settings.schema.json`, not in `required`, with a description that names no lever. **Amends 002** `settings.schema.json` and `data-model.md` section 4. Acceptance: T031 green; `reviewer/tests/unit/test_no_lever_in_pane_settings.py` green and **unedited** (FR-004); zero warnings.
- [x] T033 [py] Lane G. **Foundational gate**. Run the gate's commands (quickstart, "The gate"), then research R2.28's replay regeneration step, since a provider and the records moved: 008 `contracts/replay.md` section 8's unchanged-fixture verification recipe: from `reviewer/`, `uv run python tests/fixtures/replay/verify_regeneration.py` (only runtime producer inputs seeded; unchanged generators/self-checks), then from the root the literal `git diff --exit-code -- reviewer/tests/fixtures/replay`, with raw fixture bytes held to the committed baseline. An unseeded direct generator run is not a byte-equality check. Skip the step where the owner's recordings mapping is absent, and record why. Nothing is committed: a difference is a defect of the task that caused it, never a fixture to regenerate. T118 records the outcome in `specs/015-review-send-gate/quickstart.md`'s Results.

**Checkpoint**: the pins hold. In place: one atomic writer, one restart and crash helper, the session fields, one clock, one new state, one deferred provider, one provider setup, one prefix, one question identity, one render, the words and the setting.

---

## Phase 3: User Story 1 - Review Without Sending Anything to the Model (Priority: P1) 🎯 MVP

**Goal**: with the box unticked, Review runs every code check, saves a whole checks-only review, and waits, with no provider set up, no key needed and nothing sent. The page shows the box, the waiting status, no Stop, the follow-up box off and the Send block's sentence.

**Independent Test**: spec.md User Story 1; quickstart Scenarios 1 and 5, and Scenario 6's US1 cases.

### The backend

- [x] T034 [P] [US1] [py] Lane B. Extend `reviewer/tests/unit/test_runner_send.py` and `test_events_schema.py` (`contracts/review-flow.md` sections 1 and 7; `contracts/records.md` sections 1 to 3; FR-006, FR-009 to FR-011, FR-037).
  - **The checks only**: `start_review(..., send_when_checked=False)` with a `DeferredProvider` on T006's package runs exactly what a ticked review runs before its first request: the part roles and their question, the checks-first pre-run, and the drawing questions. Its findings, questions and coverage equal a ticked review's at that review's first `run()`, read from T004's recorder. It makes no provider call.
  - **What it records**:
    - It emits `session.started` with `send_when_checked: false`.
    - It records `model_status {state: "not_sent", document, checked_at: local_now(), profile}`. The required time is initialized after setup's checks and replaced by the first finalization's end before any record is saved; a later waiting apply must keep that first end (2026-10-12 re-check). `document` comes from `report/snapshot.root_document` (made public, research R2.15). `profile` is the identity `{path, sha256}` of the Standards profile it graded with (`ProfileIdentity`, `checks/standards/profile.py:183-188`), omitted when there is none.
    - When the pre-run ran, it records `live_detection` (`LiveOutcome.as_record()`).
    - The run keeps `_prerun` and `_standards_gap`.
  - **The defaults**: `earlier` with `send_when_checked=True` raises `ValueError`. With neither argument, `start_review` and `run_review` are today's, so the command-line review gains nothing (FR-037; T007 byte-equal).
  - **The command-line review's output** (FR-037; `cli.py:758-780`; T007 drives `POST /sessions` and never the command). `swreview review` runs on the shared `tmp_package_dir` (`tests/conftest.py:146`) with `test_cli.py`'s fake provider, through its `invoke` (`:227`) and `fake_provider` (`:163`), imported as `test_chat_timing_route.py` imports `test_chat_server.py`'s fixtures. Asserted:
    - It prints exactly today's four lines, each as a literal with the values read from the session it wrote: `reviewed {design_id} with {provider} {model}`, `{n} findings, {n} evidence requests, {n} tool calls`, `session: {path}` and `report: {path}`.
    - Its `--json` payload has exactly today's ten keys.
    - `review --help` names no option containing `send` or `recheck`.

    This case is a pin: it is green on the code before T035 and stays green at every later commit. `test_cli.py` itself is not edited.
  - **The finalization of a session not sent**:
    - Each open model-owned checklist item reads `NOT_SENT_ITEM`. One left open after its blocking question was answered keeps 013's `ANSWERED_BUT_OPEN` and adds `NOT_SENT_SUFFIX`.
    - A code-owned item closes by code as today, and nothing is marked checked.
    - No `turn.ended` is written.
    - `checked_at` is stamped by `local_now` at the finalization's end, and `unattended_runtime_minutes` is `checked_at - started_at`, so a patched clock that waits an hour adds nothing.
  - **`test_events_schema.py` rows**: an unticked `session.started` with `send_when_checked: false` validates; one with `true` is refused (`const`); a ticked one without the key validates as today; any other new key is still refused.

  **Moved, red by design on the 014-first baseline**: `test_benchmark_pane_parity.py` adds `send_when_checked` and `earlier` to `COMPARED`. Its signature remains exhaustively classified, and the ticked pane and benchmark compare the defaults `True` and `None`. This classification lands with T035, not in a later conditional merge.

  Acceptance: red for want of the arguments.
- [x] T035 [US1] [py] Lane B. Implement in `agent/runner.py`:
  - `start_review(..., send_when_checked: bool = True, earlier: ReviewSession | None = None)` (`:1497`). `earlier` is accepted but refused with `True`, and is carried from T093.
  - `ReviewRun.awaiting_send`, `_prerun` and `_standards_gap`, the model-status and live-detection writes, and the event field.
  - `NOT_SENT_ITEM`, `NOT_SENT_SUFFIX` and the running time in `finalize_session` (`:597-678`).

  Keep T034's 014 parity classification in this same commit: `send_when_checked` and `earlier` are `COMPARED`, and `test_benchmark_pane_parity.py` passes on the integrated baseline.

  Also rename `report/snapshot._root_document` to `root_document` (`:79`; one name in lane R's file, in this task). Add the field inside the `session.started` branch's `body.properties` in `specs/002-task-pane-assistant/contracts/chat-events.schema.json` (`review-flow.md` section 7's JSON, not in `required`). **Amends 002** `chat-events.schema.json`; **008** `contracts/checks-first.md` section 1 (unticked: no provider is set up, and no first request follows the pre-run). Acceptance: T034 green; T007 byte-equal.
- [x] T036 [US1] [py] Lane B. Extend `reviewer/tests/unit/test_runner_send.py` and `test_send_estimate.py` with the Send cache (`contracts/review-flow.md` section 5; `contracts/estimate.md` sections 1 to 4; data-model sections 3 and 7; FR-012, FR-013):
  - **The cache**: `build_send_cache()` sets `_send_cache` `{opening, estimate, named_ids}` in one assignment.
  - **One caller** (owner decision 71A): `close_waiting()` calls `build_send_cache()` and then `finalize()`, in that order, and is the only caller of `build_send_cache` (a spy counts one build per call; nothing else in `agent/runner.py` or `chat/server.py` calls it).
  - **The opening**: with nothing applied, it **is** the frozen `opening_message`, byte for byte. It also equals the opening built again after the finalization (the order pin, research R2.8).
  - **The named ids**: `named_ids` is `PrerunResult.named_finding_ids()`, the ids the digest's lines name, in order, from the loop `_finding_lines` renders, under `DIGEST_ID_CAP`. A folded family names none.
  - **The estimate** is `SendEstimate {input_tokens: count_tokens(request_prefix(system, tools, opening)), encoding: "o200k_base", approximate: provider == "gemini"}`, where `self.tools` is the offered tools less what lever 13 withheld. `input_tokens` is `None`, never zero, when `tokens.encoding` is patched to raise `TokenizerUnavailable` (the precedent is `test_step_sizes.py:166-171`; the vocabulary is cached per process, so an empty `SWREVIEW_TOKENIZER_DIR` would not take effect).

  Acceptance: red for want of the cache.
- [x] T037 [US1] [py] Lane B. Implement `SendCache`, `ReviewRun.build_send_cache()`, `close_waiting()` (its one caller: the cache, then the finalization; owner decision 71A), `opening_at_send()` and `first_request_estimate()` in `agent/runner.py`. `opening_at_send()` has only its frozen branch here; T086 adds the rebuilt one. Add `PrerunResult.named_finding_ids()` in `prerun.py` (`:522`, beside `_finding_lines`). Acceptance: T036 green; T007 byte-equal.
- [x] T038 [P] [US1] [py] Lane R. Write `reviewer/tests/unit/test_report_model_status.py` (`contracts/records.md` section 4; FR-032, SC-009). The header reads, by model status:
  - `not_sent`: "- Model: not sent to the model (checked by code only)", and no Provider line.
  - `send_failed`: "- Model: not sent to the model; the last attempt failed at {at}: {reason}".
  - `sent`: today's Model and Provider lines, then "- Sent to the model: {sent_at} (checks finished {checked_at})", and, when there were failed attempts, "- Earlier attempts that failed: {n}".
  - `rechecked_from` adds "- Checked again from session: {id}" beside today's "- Retry of session:".
  - Every time prints as its stored wall clock: a `+05:30` time prints its own clock whatever the test's zone (research R2.15).
  - A session with no `model_status` renders today's header (T007's `report.md` byte-equal).

  Acceptance: red for want of the lines.
- [x] T039 [US1] [py] Lane R. Implement the model-status lines in `_render_title` (`report/markdown.py:146-180`). It lands before the unticked start (T040-T041), whose test reads this header in the `report.md` on disk at the 201, so that commit holds no red test. Acceptance: T038 green; every `.md` golden and T007 byte-equal.
- [x] T040 [P] [US1] [py] Lane B. Extend `reviewer/tests/unit/test_send_gate_server.py` with the unticked start (`contracts/review-flow.md` sections 1, 2, 4 and 9; FR-006 to FR-010, FR-019, FR-025; SC-001, SC-002). Every unticked case asserts `ProviderControl.built == []`; the ticked overlap case permits the legitimate start's existing provider build and asserts no build for the refused duplicate.
  - **The start**: with no key in settings or the environment, `POST /sessions` with `send_when_checked: false` answers `201 {chat_id, review_session_id, not_examined}`, with the chat `awaiting_send`. The Send cache is built once per start, by `close_waiting` (owner decision 71A).
  - **What is on disk when the 201 arrives**:
    - `events.jsonl` ends at `session.ended`, with no `turn.started` or `turn.ended`.
    - `session.json` says `not_sent`.
    - `report.md` is on disk, reading T039's "- Model: not sent to the model (checked by code only)".
    - The coverage is a ticked review's at its first request, plus exactly: the close-out row, one unresolved row per open question, and one "not reviewed, because the review was not sent to the model" row per open model-owned item (SC-002).
  - **Refusals and failures**:
    - A `send_when_checked` that is not a boolean is `400 InvalidRequest`, naming the field.
    - An unticked start on an unreadable package answers `InvalidPackage` as today, and registers no chat.
    - A cache build or a finalization that raises (`write_atomic` patched to raise) answers the same 500 response as an unexpected failure today, registers no chat, and leaves the folder free (a following claim meets no `RunDirInUse`).
    - A ticked start's own paths, its no-key `502` among them, are T007's goldens (owner decision 75A), not a case here.
  - **Overlapping starts** (independent US1 lifecycle audit, 2026-10-12): hold the first folder's setup before registration, and issue a second start for that same otherwise-empty folder. The second is `409 RunDirInUse`, with no second provider build or check setup; a different folder still starts. Cover ticked and unticked starts. A setup, cache-build or finalization failure releases the pending reservation and registers no chat, so a following claim meets no stale `RunDirInUse` (existing on-disk retry rules still apply); successful registration also releases the reservation while the registered chat keeps the folder claimed.
  - **While it waits**:
    - `POST /messages` is `409 NotSent`.
    - `POST /stop` writes no event, leaves the chat `awaiting_send`, and leaves `chat.stop_requested` unset.
    - A graceful shutdown writes nothing for it.
    - Two reviews waiting at once each keep their own state.

  Acceptance: red for want of the field.
- [x] T041 [US1] [py] Lane B. Implement the unticked branch of `create_session` (`chat/server.py:1230-1262`), in this order:
  1. `_start_review` (`:2111-2114`) builds `DeferredProvider.for_settings(...)` in place of the factory when `send_when_checked` is false.
  2. `ChatServer._open_waiting(chat, run)` (owner decision 71A), the tail T095's re-run shares: on the thread pool, before the chat is attached and registered, `run.close_waiting()` and `_render_run(run, chat.report_path, chat.run_dir)`; a raise moves the unregistered chat `extracting -> failed` and answers the error body. Then attach, register and move `extracting -> awaiting_send`.
  3. Answer 201.

  Before the first await, reserve the resolved folder on the event loop. `_claim_run_dir` checks this pending-folder set as well as registered chats and files; a second start is `RunDirInUse`. Release the reservation on every setup/finalization failure and after successful registration, using one `finally` around the claimed start. Failed starts stay unregistered, and unrelated folders remain independent (2026-10-12 lifecycle audit).

  Also validate the body's `send_when_checked`, and add `NotSent` (409), refusing `POST /messages` while `run.awaiting_send`. **Amends 002** `contracts/chat-api.md` (the `POST /sessions` field; "starts the review turn immediately" holds only with the box ticked; `POST /messages`' `NotSent`) and spec FR-006. Acceptance: T040 green; T027 and T038 green; T007 byte-equal.
- [x] T042 [US1] [py] Lane B. Extend `reviewer/tests/unit/test_send_gate_server.py` with the SOLIDWORKS pipe of a waiting review (owner decision 79A; research R2.29; `contracts/review-flow.md` section 8; the spec's edge case "Several reviews waiting at once"). The seat is a real `BridgeClient(pipe, secret, transport=<a counting transport>)`, built through the app's `bridge_factory` as `tests/fixtures/pane/generate_drawing_questions.py:217` and `test_confirmed_drawing_read.py:677-689` build one; `ScriptedReviewBridge` has no transport, so it cannot show a pipe closed and opened again. The counting transport answers on the wire, as `test_bridge_client.py`'s `FakeTransport` does, the interference results T006's script gives (and, for T083, the confirmed read's); like `NamedPipeTransport` (`bridge/client.py:256-261`, `:288-291`), it opens its pipe on its first request after construction or after a `close()`, and it counts the pipes open (opened less closed):
  - Five unticked assembly reviews started in one backend, each with SOLIDWORKS attached (so the pre-run's live detection opens the pipe), hold zero open pipes once each `201` arrives.
  - `ReviewRun.release_bridge()` closes only the transport and keeps the client: the run's `BridgeClient` is the same object after it, and a later call through it opens the pipe again. With no bridge (`no_bridge`), it does nothing.
  - A ticked review's transport is not closed by the start (T007 byte-equal).
  - **A start that fails** (`contracts/review-flow.md` section 1 step 4): an unticked assembly start, SOLIDWORKS attached, whose finalization raises answers today's error body, registers no chat, and leaves zero pipes open: `_open_waiting`'s failure branch closes the run (`run.close()`).

  Acceptance: red for want of `release_bridge`.
- [x] T043 [US1] [py] Lane B. Add `ReviewRun.release_bridge()` to `agent/runner.py` (closing the context's bridge transport through `BridgeClient.close()`, `bridge/client.py:569-571`, which closes only the transport) and call it in `ChatServer._open_waiting` after the render and before the chat is registered (`chat/server.py`); in `_open_waiting`'s failure branch, close the run instead (`run.close()`, `agent/runner.py:1386-1390`) before the chat moves `extracting -> failed`. T066 adds its second call, in `_play`'s settle. Acceptance: T042 green; T040 green; T007 byte-equal.
- [x] T044 [P] [US1] [py] Lane R. Write `reviewer/tests/unit/test_send_block.py` (data-model section 6; `contracts/pane.md` section 3; `contracts/words.md` section 1; `contracts/estimate.md` section 3; FR-012, FR-034).
  - `review_ranking(session, package, *, usage=None, send=None)` omits `summary.send` when `send` is `None`, keeping the pane fixture's bytes (`test_pane_fixture.py` green and unedited).
  - From `send_input` `{state, input_tokens, provider, send_error}` it builds `SendBlock {state, input_tokens, approximate, text, failure, rerun_failed_text}`, with no `session_id` and no restored line (owner decisions 68A and 73A).
  - **`waiting`**:
    - With a count, it prints `send.first_request`, with `{tokens}` written as `13,151` by `summary.tokens_text`, the one formatter `ResumeWords.of` calls too: a patched `tokens_text` moves both sentences (owner decision 73A).
    - With `None`, it prints `send.without` and no number.
    - With Gemini, it prints `send.first_request_approximate` and sets `approximate: true`. The scripted provider is counted and not approximate.
  - **`failure`**: from `send_error` (`send.not_started`), else from the last recorded failed request of a `send_failed` record (`send.failed`). `{time}` is the stored wall clock's `HH:MM`.
  - **`restored`**: prints `send.restored`; `rerun_failed_text` is set.
  - `resume_text` is `send.apply_answers` while a `send` block is present, else today's.
  - Every sentence comes from the words file.

  Acceptance: red for want of the block.
- [x] T045 [US1] [py] Lane R. Implement `SendBlock`, `ReviewSummary.send` (omitted when `None`), `review_ranking(send=)`, `resume_text` while waiting and `tokens_text` (extracted from `ResumeWords.of`, which now calls it; `report/summary.py:279-284`) in `report/summary.py`. **Amends**:
  - **009** `contracts/review-summary.md` section 1 (the `send` block) and `contracts/views.md` section 2 (the Send block's count, a second exception to "Results shows no token count");
  - **008** `contracts/cost.md` (a new surface, the Send sentence) and `contracts/tokenizer.md` section 1 (the pane sentence names no encoding, and a Gemini figure is called approximate).

  Acceptance: T044 green; `test_pane_fixture.py` green and unedited.
- [x] T046 [US1] [py] Lane B. Extend `reviewer/tests/unit/test_send_gate_server.py` (`contracts/estimate.md` section 2; research R2.8):
  - For a waiting chat, `GET /sessions/{id}/attention` and the snapshot answer `summary.send {state: "waiting", input_tokens: <the cache's count>, ...}` and `chat_state: "awaiting_send"`.
  - With `_opening_message` and `count_tokens` patched to raise once the cache exists, both routes still answer `200` with the cached figure: no route builds an opening or counts a token.
  - A ticked chat's answers carry no `send`.

  Acceptance: red for want of the block on the routes.
- [x] T047 [US1] [py] Lane B. Add `ReviewRun.send_input()`, which reads `_send_cache` and `_send_error` and computes nothing, and pass it from the attention and snapshot routes while `run.awaiting_send` (`chat/server.py:1267-1318`). Acceptance: T046 green; T007 byte-equal.

### The host

- [x] T048 [P] [US1] [C#] Lane H. Extend `extractor/SwReview.AddIn.Tests/PageMessageTests.cs` (`contracts/pane.md` sections 1 and 12; FR-002, FR-027):
  - The `init` and `settings` views carry `send_when_checked` (true when unset).
  - `send_when_checked.save {send_when_checked: false}`:
    - writes the file and answers `send_when_checked.saved {send_when_checked: false}`;
    - leaves `Backend.Restarts` unchanged, and keeps every other field;
    - is accepted while the fake backend reports a turn `running`.
  - A missing or non-boolean value is `InvalidRequest`. A write that fails is `SettingNotSaved`, and the stored value stands.
  - **One persist step** (owner decision 73A): a box save on a settings file with a load problem writes what a Settings save writes and clears the load problem, so `ReportSettingsProblems` (`ReviewHost.cs:937-956`) posts none after it; a `settings.save` whose write fails answers `SettingNotSaved` (today `HostError`, through `Receive`'s catch-all, `:596-599`), and the stored settings stand.
  - `settings.save` keeps the value. It is accepted while the fake backend reports the review's chat `awaiting_send`, and refused while it reports `running` (`BackendClient.cs:118-122`).

  **Moved**: `ReadyIsAnsweredWithInitCarryingTheBackendOriginAndNoKey` asserts the view's new key (additive). `ErrorLabelsCoverTheHostTests.TheScanFindsTheClassesTheHostAndThePageMake`'s expected list gains `SettingNotSaved`. Acceptance: red for want of the message.
- [x] T049 [US1] [C#] Lane H. In `extractor/SwReview.AddIn/Review/ReviewHost.cs`: extract `PersistSettings(next)` from `settings.save`'s persist step (`:879-910`) - write the file (`UserSettings.Save`), replace `_settings`, clear `_settingsError`, and turn a failed write into `SettingNotSaved` - and call it from `settings.save` (which then restarts the backend, as today) and from the new `send_when_checked.save` (clone the settings, set `SendsWhenChecked`, persist; no restart and no turn check) (owner decision 73A). Add the view's key (`ReviewHost.View`) and `PagePayload.Flag` in `Review/PaneActions.cs`. **Amends 002** `contracts/pane-host-messages.md` (the `ready`/`init`, `settings.save` and `settings.get` replies carry the value, and a failed `settings.save` write is `SettingNotSaved`), and `contracts/chat-api.md`'s "Shutdown and settings changes" (`review-flow.md` section 2: a save is accepted while a review waits, since `awaiting_send` is not a running turn, and refused while the chat is `running`, which an apply, a Send and a re-run each are). **The new row `send_when_checked.save` waits for T055**: a Review page row lands in the commit where the page first posts it, because `ReviewPageContractTests.EveryPageToHostRowIsExercisedByThePage` (`:81-99`) fails on a row the page does not post, and `EveryTypeThePageSendsIsARowOfTheContract` (`:55-76`) on a type it posts with no row. No host test parses the Review rows. Acceptance: T048 green; zero warnings.
- [x] T050 [P] [US1] [C#] Lane H. Extend `extractor/SwReview.AddIn.Tests/ReviewHostTests.cs`, and write `BackendClientSessionBodyTests.cs` with an in-process `HttpListener` on 127.0.0.1, as `RemodelBackendClientTests.cs` uses (`contracts/pane.md` sections 2 and 8; `contracts/review-flow.md` section 1, "The host's timeout"; data-model section 9; FR-002, FR-003, FR-026).
  - **The host**:
    - `review.start` passes the value stored when it is handled, as `NewSessionRequest.Mode` (`ReviewMode.Send` ticked, `ReviewMode.Wait` unticked), through `CreateReviewSession(document, runDirectory, retryOf, mode)` (owner decision 71A).
    - `review.started` carries `send_when_checked`.
    - Unticked, the ready status reads "Checked {n} components by code; nothing was sent to the model.".
    - **The mark** (owner decision 73A): an unticked start's record has `ModelStatus` `not_sent`, and its `sessions.list` item carries `model_status: "not_sent"`; a ticked start's has neither.
  - **Message order**:
    - After a `review.start` then a box change, the start passes the old value and the change is written after it.
    - A Retry after a box change passes the new value.
    - A `CreateSession` that times out on an unticked start is today's failure, and keeps no record.
  - **The client**:
    - The body always carries `send_when_checked` and `recheck`, written from the mode: `true, false` for `Send`, `false, false` for `Wait`, `false, true` for `Recheck`. No mode writes `send_when_checked: true` with `recheck: true` (71A).
    - `BackendClient.TimeoutFor(request)` is `ChecksOnlyTimeout` for `Wait` and `Recheck`, and the 30 s `CallTimeout` for `Send` and every other call; `ChecksOnlyTimeout` equals `CallTimeout` until T098 measures it (owner decision 70A). Checked directly, with no waiting.

  **Moved**:
  - The `review.start` test that asserts every `NewSessionRequest` field (`ReviewHostTests.cs:322-370`), and `FakeBackend.CreateSession` (`:2123`), gain `Mode`.
  - `ReviewPageContractTests.TheReviewStartRowsReplyNamesTheDocumentItReviewed` (`:178-186`; one string in lane W's file, in this task) asserts "review.started {chat_id, run_dir, not_examined, document, send_when_checked}".

  Acceptance: red for want of the fields.
- [x] T051 [US1] [C#] Lane H. Add `ReviewMode { Send, Wait, Recheck }` and `NewSessionRequest.Mode` (optional, default `Send`) to `Review/IBackendClient.cs`. In `Review/BackendClient.cs` (`:39`, `:131-150`, `:299-300`), write the two body fields from the mode, and add `TimeoutFor` and `ChecksOnlyTimeout`, set to `CallTimeout` until T098's measurement. In `ReviewHost.cs`, extract `CreateReviewSession(document, runDirectory, retryOf, mode)` from `StartReview` (`:1198-1331`: the drawing refusal, the backend check, the request built from the settings, the catch and its status and rethrow, the record kept, the ready status and the reply), so `review.start` and T104's `review.recheck` share one body (owner decision 71A; T104 adds, for `ReviewMode.Recheck` only, the document binding between its drawing refusal and its backend check, data-model section 9); pass the stored value as the mode, carry it in `review.started`, set the ready status, and add `SessionRecord.ModelStatus`, set to `not_sent` for an unticked start, with the `sessions.list` item's `model_status` (owner decision 73A). **Amends 002** `contracts/pane-host-messages.md` (the `review.start` row and its reply). Acceptance: T050 green; every existing `ReviewHostTests` case green, the moved ones as T050 edits them; the six `IBackendClient` fakes compile unchanged (research R4.2); zero warnings.

### The waiting fixtures

- [x] T052 [P] [US1] [py] Lane G. Write `reviewer/tests/unit/test_pane_waiting_fixtures.py` (research R2.25; `contracts/pane.md` section 13), on the precedent of `test_pane_drawing_fixture.py`. Two files, `extractor/SwReview.AddIn.Tests/Fixtures/review-waiting.json` (from T006's package) and `review-waiting-big-assembly.json` (from the big-assembly replay fixture's package):
  - each equals a fresh generation byte for byte, the failure naming the `--write` command;
  - each holds a `waiting` snapshot (the live snapshot of an unticked review, its size sentence counted) and the words file's labels block;
  - every clock value in them is the pinned fictional time, and no provider was built.

  `review-waiting.json`'s `waiting` holds the part-roles question and a drawing-candidate question, both `source: "code"`. **Moved**: `test_replay_fixture_hygiene.py`'s list of committed fixtures gains both files (FR-039). The existing `scramble.REVIEWER_OWN_TEXT` mechanism gains only the exact public drawing-candidate reason and fit/joint clauses already present in the real snapshots; three counterexample tests preserve scanning of changed clauses and unrelated text. The denylist and all existing hygiene assertions stay unchanged (T053 owning 008 amendment). Acceptance: red for want of the files.
- [x] T053 [US1] [py] Lane G. Write `reviewer/tests/fixtures/pane/generate_waiting_fixtures.py` (run from `reviewer/` with `--write`), and commit the two files it writes. It pins every clock: the runner's `datetime` and `utc_now` as `test_finding_explanations.py:366` pins them, and `local_now`. It runs with the box unticked, and sets up no provider before a Send. Acceptance: T052 green; `test_replay_fixture_hygiene.py` green.

### The page

- [x] T054 [US1] [page] Lane W. Write `extractor/SwReview.AddIn.Tests/ReviewPageSendGateTests.cs` (offscreen WebView2, `review-waiting.json`; `contracts/pane.md` sections 1 to 4, 6 and 8 to 10; FR-001 to FR-003, FR-019, FR-025 to FR-027, FR-033, FR-034; SC-001). As test infrastructure, make `ReviewPageDriver.cs` answer `send_when_checked.save` with `send_when_checked.saved`, with an error mode `SettingNotSaved`, and answer `sessions.list` with items that may carry `model_status`.
  - **The box**:
    - `label.check.send-when-checked` sits in `#session`, directly after the buttons' `.row`, set from `init`.
    - A change posts `send_when_checked.save` at once and keeps the new value shown.
    - A refused write puts the box back and prints the label in `#send-when-checked-note`, cleared at the next change.
    - Rapid changes use the latest confirmed stored value: starting true, hold the false save, change back to true, let false succeed, then fail the true save. The box rolls back to the confirmed false, never the stale true captured before the first reply. An earlier success updates the confirmed value without replacing a newer optimistic choice (independent US1 reply-order audit, 2026-10-12).
    - The box is never disabled: not while a start is held, a turn runs or a review waits.
    - With `HoldReviewStart`, a box change shows at once and its save is posted after the `review.start`. On release, the waiting state follows `review.started.send_when_checked`, not the box.
  - **An unticked start**:
    - No turn is marked running, and Stop is disabled.
    - The status line reads "Checked by code. Not sent to the model." even with code questions open, ahead of "Waiting for your answers.".
    - `#send` sits directly after `#summary` and before `#questions`, with the "Send to model" button and the summary's `send.text`.
    - The follow-up box is disabled, with the placeholder "Not sent to the model yet: press Send to model first".
    - The Transcript's first line is "Checked by code only: nothing is sent to the model until Send to model is pressed.", and at `session.ended` it adds "The checks ended at {ended_at}. Nothing was sent to the model.".
  - **While it waits**:
    - A reload shows the review waiting, never running.
    - Its chip carries " · not sent", from its `sessions` item's `model_status`, the host's record (owner decision 73A).
    - **The mark after a reload** (owner decision 77A's fourth case): after a second `ready`, the waiting review's chip carries " · not sent" from the driver's item before it is chosen, and a ticked review's chip never carries it.
    - Review and Clear review keep the waiting chip, marked (FR-026).
    - After Review is pressed again, and after Clear review, choosing the waiting chip shows it waiting: the status line "Checked by code. Not sent to the model.", the Send block shown, no turn running and Stop off (FR-026, FR-033).
    - Zero proxy calls to `/send`, `/messages` or `/evidence` are made across Clear review, a document switch and Review again (SC-001).
  - **Around it**:
    - With the box unticked, "Before this review" still reads "No review tokens have been used.".
    - An unticked start refused `InvalidPackage` shows today's error card and Retry, and no Send block.
    - The Settings section's no-key note is `words.md` section 2's new sentence. While a review waits, the line "Saving restarts the backend. ..." shows under Save (FR-027).

  **Moved**:
  - `ReviewPageViewsTests.TheStatusLineReadsEachOfItsFourSentencesInItsState` (`:107-118`) gains the waiting row. It is renamed `TheStatusLineReadsEachOfItsSentencesInItsState`, without a count, so T107 adds its row without a second rename.
  - `ReviewPageDefaultViewScanTests.NoRawStatusOrBucketTokenIsVisible` (`:55-65`) adds `awaiting_send`, `not_sent` and `send_failed` to its token list (`:60`), and runs on `review-waiting.json` too.

  Acceptance: red for want of the box.
- [x] T055 [US1] [page] Lane W. Implement in `extractor/SwReview.AddIn/Review/ReviewPage/`:
  - `index.html`: the box and its note in `#session`, after the `.row`; and `<section id="send" class="send-panel" aria-label="Send to model" hidden>` after `#summary`.
  - `app.css`: `.send-panel` and the box line, with tokens only.
  - `render.js`: `render.sendBlock(send, extras)`, setting text with `textContent` only.
  - `app.js`:
    - the box's message and its revert, tracking the latest confirmed stored value from init/settings and successful save replies, so a refused latest save reverts to that value even across rapid changes; keep newer optimistic choices visible and never disable the box; and the waiting status-line state, read from `review.started` until the summary arrives;
    - Stop and the follow-up box off while waiting (`app.js:1695-1704`, `:1864-1872`);
    - the Transcript lines, and the chip mark from the `sessions` item's `model_status` (no page-side map of waiting reviews; owner decision 73A);
    - the Settings lines and `describeKeySource('none')` (`:2484-2492`).

  The button is drawn here and posts nothing until T076. **Amends 002** `contracts/pane-host-messages.md`: the new row `send_when_checked.save`, with its reply `send_when_checked.saved`, in this commit, where the page first posts it (T049 says why). **Amends 009** `contracts/views.md` section 3 (the waiting state) and `contracts/sessions.md` section 5 (the chip mark). Acceptance: T054 green; `ReviewPageSummaryAcceptanceTests` and `ReviewPageNarrowLayoutTests` green and **unedited** with the box in place (research R2.21: about 21 px of 226 px); `PageRuleScanTests` green with no new allowlist entry; `ReviewPageInjectionTests.ThePageStylesheetNamesNoLiteralColour` green.
- [x] T056 [US1] [page] Lane W. Write `extractor/SwReview.AddIn.Tests/ReviewPageSendLayoutTests.cs` on `review-waiting-big-assembly.json` (`contracts/pane.md` section 11; FR-005, SC-007). It is an acceptance test that passes with no further page code (009's precedent):
  - At 300 by 600 in `waiting`, the summary's headline, tally and not-reached line, and the Send to model button, are inside the viewport.
  - At 260, 300 and 420 px the session buttons wrap as today (two rows at 300 px), with the box directly under them.

  Record the measured slack in research R2.21. If SC-007 fails, the page work stops and the owner is asked (research R2.21, "The end state"); no page-only fallback is tried. Acceptance: green.
- [x] T057 [US1] [py] Lane G. **US1 gate**: T033's commands (from `reviewer/`, and `extractor/SwReview.sln` from the root) and the replay regeneration step over `reviewer/tests/fixtures/replay` (the runner and the records moved). Nothing is committed; T118 records the outcome.

**Checkpoint**: an unticked review runs the checks, saves itself, and waits, with no provider and no key. The Review tab, the report and the Transcript each say so. The box is remembered, and changing it never restarts the backend.

---

## Phase 4: User Story 2 - Send the Review When Ready, Knowing Its Size (Priority: P2)

**Goal**: Send to model resumes the same review, with the counted size of its first request beside it. The first request is a ticked review's, byte for byte. A Send that fails, before or at its first request, leaves the review waiting with the reason beside Send.

**Independent Test**: spec.md User Story 2; quickstart Scenario 2, and Scenario 6's Send cases.

- [x] T058 [P] [US2] [py] Lane B. Extend `reviewer/tests/unit/test_provider_settings.py` (`contracts/review-flow.md` section 3, order 5; FR-016). `ProviderSettings.has_credential` is:
  - true for a key from the settings, a key from the environment, the scripted provider, and Gemini with an enterprise project and no key;
  - false with no key anywhere and, for Gemini, no enterprise project.

  Acceptance: red for want of the property.
- [x] T059 [US2] [py] Lane B. Add `has_credential` to `ProviderSettings` in `agent/settings.py` (`:194-215`), the one place the rule lives. Acceptance: T058 green.
- [x] T060 [P] [US2] [py] Lane B. Extend `reviewer/tests/unit/test_send_gate_server.py` with the route (`contracts/review-flow.md` sections 2, 3 and 9; FR-016, FR-018; owner decision 69A).
  - **Refusals**: `POST /sessions/{id}/send` refuses, in this order and changing nothing, each leaving the chat `awaiting_send`:
    1. `404 UnknownChat`;
    2. `409 SessionFailed`;
    3. `409 TurnRunning`, for a Send already in flight;
    4. `409 NotWaiting`, for a ticked review or a sent one;
    5. `409 NoCredential`, with no key (never for an environment key, a Gemini enterprise project or the scripted provider).
  - **The build inside Send**: the route answers `202` before the factory runs; the factory runs on the chat's worker (a factory that records its thread sees the worker's, never the event loop's); the chat is `running` from the route's move, so a second Send, or an answer, sent while a held factory builds is `409 TurnRunning`. A factory that raises is no refusal of the route: the `202` stands, and T065 pins the guard's handling of it.
  - **A stop during the build** (FR-025; `contracts/review-flow.md` section 4; research R2.12). With the factory held, `POST /stop` answers `202` and writes no event; the chat reads `running`, so the flag is set. When the held factory then returns, the Send is in flight and the stop is today's: the first turn ends `stopped` at its first tool call (default, research R2.12). A held factory that raises instead needs the guard, so that case is T065's.
  - **The answer**: `202`, with the public view.

  **Moved**: `test_chat_server.py`'s `ROUTES` (`:279-296`) gains `POST /sessions/{chat}/send`, so its door tests (no token, wrong token, preflight) cover it. Acceptance: red for want of the route.
- [x] T061 [US2] [py] Lane B. Add the route, `NotWaiting` and `NoCredential` (409) to `chat/server.py` (owner decision 69A):
  1. Checks 1 to 5, the move `awaiting_send -> running`, setting the run's `_send_in_flight`, and `_submit(chat, partial(run.send, build_adapter))` run on the event loop, with no `await` between them; `build_adapter` is `partial(self.provider_factory, settings)`, with the chat's `_settings({provider, model, effort})` (`:1996-2010`).
  2. The route answers `202`. It builds nothing, refuses nothing after the move, and touches no stop flag: `_play`'s `finally` (`:2201`) stays the only place it is cleared.

  `_play` settles `awaiting_send` while `run.awaiting_send` (`:2186-2208`). **Amends 002** `contracts/chat-api.md` (the Send row; `NotWaiting`, `NoCredential`). Acceptance: T060's refusal cases green. Its build, `202` and successful-build stop cases each end in a Send that runs, which needs `run.send`; T064 adds it in the same commit (C31), so no commit holds a route that submits a method not yet written, and the `202` case is never green only because `_play` swallowed an `AttributeError`. T007 byte-equal.
- [x] T062 [P] [US2] [py] Lane B. Extend `reviewer/tests/unit/test_runner_send.py` with `ReviewRun.send(build_adapter)` (`contracts/review-flow.md` section 6; `contracts/records.md` sections 1 and 3; research R2.10, R2.11, R2.27; FR-011, FR-014, FR-032):
  - **The prepare half** changes nothing, the adapter's build included (owner decision 69A): the session is deep-equal, nothing changes on disk, and no event is written.
  - **The commit half**, in order (owner decision 72A):
    1. `session.sent`.
    2. The pre-write: `send_failed` with the `Interrupted` entry (`INTERRUPTED_SEND`), saved.
    3. The withdrawal of the previous finalization's rows, by identity, through `withdraw_finalization(session, _finalized)`. `_finalized` is empty after it, and rows anything else wrote (the part-roles row) are kept.
  - **One withdrawal** (72A): `withdraw_finalization` is the body `finalize_session` runs at its start; `finalize_session` calls it (T007 byte-equal), and Send's commit half calls it in place, with no precompute of its own.
  - `attach_provider` numbers steps from the session's count.
  - **The first `usage`** sets `sent`, with `sent_at`, the estimate and `opening_finding_ids`; drops the `Interrupted` entry; clears `_send_in_flight`; and saves the session as it stands.
  - **Crashes, as the folder a crash leaves** (owner decision 76A; T012's `disk_at` and `restarted_app`):
    - The folder copied inside the scripted provider before its first `usage` says `send_failed`, with "the backend stopped before the model answered" (RK-7).
    - The folder copied after the first `usage`'s save says `sent`, with `ended_at` null and no row of the checks' finalization; `GET /reviews` of a restarted app reads it read-only, as a sent review.
  - **Running time**: once sent, `unattended_runtime_minutes` is `(checked_at - started_at) + (ended_at - sent_at)`.

  Acceptance: red for want of `send`.
- [x] T063 [US2] [py] Lane B. Extend `reviewer/tests/unit/test_send_gate_server.py` and `test_events_schema.py` with a Send that works (US2 scenarios 2, 3 and 6; FR-014, FR-015, FR-019; SC-004; research R2.14, R2.27).
  - **Byte-identical**: with nothing answered while waiting, **every** request of Send's first turn is byte-identical to a ticked review's of the same package, read from T004's recorder. The first turn is scripted to call `mark_coverage`, `request_evidence` and `get_review_checklist`, and the comparison includes the tool results.
  - **The size shown is the size sent** (owner decision 78A): `count_tokens(request_prefix(<the recorded raw system prompt, tool specs and first message>))` equals `summary.send.input_tokens` read before Send, `session.sent`'s `estimate.input_tokens` and `model_status.estimate.input_tokens`.
  - **The pipe**: with T042's counting transport, Send's first live tool opens the pipe the start released (owner decision 79A).
  - **After the first turn**:
    - After a turn ending `end`, exactly one presentation request is made.
    - `POST /messages` is `202` after the first `usage`.
    - An answer to a question the model asked after Send resumes the model with today's `ANSWER_MESSAGE` and `REGRADED_LINE`, byte for byte against the same answer in a ticked review.
  - **Records**:
    - `session.sent` carries `{provider, model, effort_mapping, estimate}`.
    - The report adds "- Sent to the model: ...".
  - Two waiting reviews each send alone.
  - `test_events_schema.py`: `session.sent` validates.

  **Moved, red by design and edited deliberately here** (research R4.3): each goes red when T064 adds `session.sent` to the event-type enum.
  - `test_events_schema.py::test_a_full_run_emits_every_event_type_the_runner_and_tools_can_emit` now includes an unticked review sent after waiting, so `session.sent` and `send_when_checked` are emitted.
  - `test_gate_same_session.py::test_a_gated_run_emits_no_event_type_outside_the_sixteen` (`:201-214`) asserts `len(SCHEMA_EVENT_TYPES) == 16`. It becomes `test_a_gated_run_emits_no_event_type_outside_the_seventeen`, with the count 17 and a dated docstring line naming 015 T064 (`session.sent` is Send's record, not the gate's), as 011 T092 and 013 T038 each renamed it.
  - `test_provider_protocol.py::test_every_schema_event_type_has_a_case` (`:184-186`) needs `valid_bodies()` (`:112`) to cover the whole enum. `valid_bodies()` gains a `session.sent` body, `{provider, model, effort_mapping, estimate}`, as `review-flow.md` section 7 fixes it, so `test_agent_event_validates_against_the_contract` validates it too; the test itself is unedited.

  Acceptance: red for want of `send`.
- [x] T064 [US2] [py] Lane B. Implement in `agent/runner.py`: `ReviewRun.attach_provider`; `send(build_adapter)` with its prepare half (the build, the configuration, the cache read, the `session.sent` body) and its commit half (`session.sent`, the pre-write, the withdrawal), without the guard (T066 adds it); `withdraw_finalization(session, written)`, extracted from `finalize_session`'s start (`:619-627`), which now calls it (owner decision 72A); `_send_in_flight` and its clear at the first `usage`; and the first-`usage` mark and its save in `_emit_turn_event` (`:1460-1473`). Add `"session.sent"` to `EventType` (`agent/providers/__init__.py`), and its branch to `specs/002-task-pane-assistant/contracts/chat-events.schema.json` (`review-flow.md` section 7's JSON; the `type` enum gains it). **Amends 002** `chat-events.schema.json`. Acceptance: T060 green, its build, `202` and successful-build stop cases included (a stop during a build that fails is T065's, green with the guard in T066); T062 and T063 green, the three moved tests included; `test_provider_protocol.py::test_event_type_literal_matches_the_schema` green and unedited; T007 byte-equal.
- [x] T065 [US2] [py] Lane B. Extend `test_runner_send.py` and `test_send_gate_server.py` with a Send that fails (`contracts/review-flow.md` section 6; FR-016, FR-017; research R2.10; RK-13).
  - **A first request that raises before any round** (the round count is read before `emit_turn_failed`):
    - The `Interrupted` entry is replaced with the provider's class and redacted reason.
    - The history is emptied, `awaiting_send` is set, `_send_in_flight` is cleared, and a `DeferredProvider` of the same settings is put back, all before the `error`.
    - `error` and `turn.ended {error}` are written; the streamed text stays in the stream.
    - A second Send carries the opening once, and every request of its first turn is byte-identical to a ticked review's of the same package, tool results included (T063's comparison, with the same scripted first turn). The session at that first request holds no row of the finalization the failure ran (research R2.27, RK-11).
  - **A failure after a round** is today's: `failed`, with the error card.
  - A ticked review's failures are T007's goldens (owner decision 75A), not a case here.
  - **The guard, at its five points** (owner decisions 69A and 72A): the factory raising; `configure_provider` raising; the effort mapping raising; the `session.sent` emit raising; and the pre-write's `save_session` raising. Capture the rollback snapshot before the factory is called, including when the prior model status already carries a failed attempt; a factory failure must not become an unbound rollback-variable error (2026-10-12 re-check). At each point:
    - no provider `run()` is recorded;
    - one `error` is written, and no `turn.ended` or `session.ended`;
    - the chat is `awaiting_send`, and `_send_in_flight` is cleared before the `error`;
    - `session.json` is byte-equal to the record before Send, with no `Interrupted` entry, and the guard saved nothing (a spy on `save_session` counts no call from it);
    - the summary's `send.failure` comes from `send.not_started`;
    - `_play`'s settle releases the pipe: T042's counting transport reads zero open (owner decision 79A);
    - a second Send succeeds.
  - **The guard's own `error` emit raising too** (72A): the failure is logged and not raised, the chat settles `awaiting_send` (not `failed`), and a second Send succeeds.
  - **A stop during a build that fails** (FR-025; `contracts/review-flow.md` section 4; research R2.12; moved here from T060, since it needs the guard). With the factory held, `POST /stop` answers `202` and writes no event. When the held factory then raises, the guard returns the run to waiting and `_play`'s `finally` clears the flag: the chat is `awaiting_send` with `chat.stop_requested` unset, and a following Send, whose scripted first turn makes a tool call, runs to `end`, with no `stopped` turn and exactly one presentation request.

  Acceptance: red for want of the guard.
- [x] T066 [US2] [py] Lane B. Implement the failure branch in `_run_turn` (`agent/runner.py:1434-1442`), the guard over `send`'s steps 1 to 7 - snapshotting the model status before the factory can raise, restoring it in memory, never writing, logging rather than raising when its own `error` emit fails (owner decision 72A) - `_send_error`, and `INTERRUPTED_SEND`. The state, `_send_in_flight` and the failure are set before the `error` is emitted. In `chat/server.py`, `_play` calls `run.release_bridge()` when it settles `awaiting_send` (owner decision 79A). Acceptance: T065 green; T062 and T063 green; T007 byte-equal.
- [x] T067 [US2] [py] Lane B. Extend `reviewer/tests/unit/test_send_gate_server.py` with the queue on the chat's worker (`contracts/review-flow.md` section 4; research R2.12; RK-14; owner decision 69A):
  - With `record_disposition` held on a waiting chat's worker, the write itself never moves the chat: `GET` reads `awaiting_send` during the write until `POST /send` is accepted (`202`), and `running` after it. The queued Send runs only after the write returns: in the recorded order, the decision's save comes before `session.sent`.
  - In another case, `POST /evidence` sent during the held write is accepted and applied after it.
  - On release, the decision is saved and kept at Send.
  - The same holds for `record_timing_live` and the timing route.
  - A held write that raises answers its error, and a Send queued behind it still runs.
  - **A stop during a held write** (FR-025; the spec's edge case "Stop while a review waits"): `POST /stop` answers `202`, writes no event and sets no flag, since the chat reads `awaiting_send`; a following Send, whose scripted first turn makes a tool call, runs to `end`, with no `stopped` turn and exactly one presentation request.
  - A ticked chat's two routes take today's path (`run_in_threadpool`), with no worker.

  Acceptance: red for want of the queue.
- [x] T068 [US2] [py] Lane B. Add `ChatServer._on_worker(chat, call)` to `chat/server.py` - submit `call` to the chat's one-thread worker (the executor `_submit` makes, `:2176-2184`) and await it - and use it in `disposition` and `timing` (`:1444-1483`) when the chat is `awaiting_send`, leaving the chat's state and stop flag untouched; any other chat keeps today's `run_in_threadpool` (owner decision 69A). Acceptance: T067 green; `test_chat_timing_route.py` green and unedited; T007 byte-equal.
- [x] T069 [US2] [py] Lane B. Extend `reviewer/tests/unit/test_send_gate_server.py` and `test_review_snapshot.py` with the snapshot's `send_in_flight` (owner decision 77A; research R2.30; `contracts/pane.md` section 3; data-model section 6):
  - The snapshot route answers `send_in_flight: true` from the send route's `202` to the first `usage`; and from the `202` to the guard's return to waiting, and to the failure branch's - each clearing it before its `error`.
  - It omits the key otherwise: an idle waiting chat's snapshot, a ticked chat's, and `review_snapshot`'s output with the parameter at its default, so the pane fixture is unchanged (`test_pane_fixture.py` green and unedited).

  Acceptance: red for want of the key.
- [x] T070 [US2] [py] Lane B. Add `send_in_flight: bool = False` to `review_snapshot` in `report/snapshot.py` (one parameter in lane R's file, in this task), written only when true, and pass `run._send_in_flight` from the snapshot route in `chat/server.py`. **Amends 009** `contracts/sessions.md` (the snapshot's optional key). Acceptance: T069 green; T007 byte-equal.
- [x] T071 [P] [US2] [py] Lane G. Extend `reviewer/tests/unit/test_pane_waiting_fixtures.py`: `review-waiting.json` and `review-waiting-big-assembly.json` each gain `failed_send`, the live snapshot after a Send whose scripted first request failed, with the `send.failed` line as its `send.failure`. `review-waiting.json` also gains `sending`, the live snapshot as the snapshot route answers it while a Send is held - taken inside the scripted provider's first request, before its `usage` - so it carries `send_in_flight: true` (owner decision 77A; research R2.25: page tests read backend-made snapshots, never hand-built ones). Acceptance: red for want of the snapshots.
- [x] T072 [US2] [py] Lane G. Extend `generate_waiting_fixtures.py` to play that Send and write `sending` and `failed_send`; regenerate both files. Acceptance: T071 green; the hygiene test green.
- [x] T073 [P] [US2] [C#] Lane H. Write `extractor/SwReview.AddIn.Tests/RunFoldersModelStatusTests.cs`, and extend `ReviewHostTests.cs` (owner decisions 73A and 80A; data-model section 9; `contracts/recheck.md` section 9; FR-026):
  - **The head reader**: `RunFolders.ReadModelStatus(runDirectory, openHead)` reads the top-level `model_status` of `session.json` within its first 64 KiB with `Utf8JsonReader` and stops there; none within the cap, no file, or an unreadable one is `null`, and nothing throws.
  - **The cap**: a stream that throws past 65,536 bytes is never read past it.
  - **The sharing**: the default opener opens a `FileStream` with `FileShare.ReadWrite | FileShare.Delete`, so a `File.Replace` of the file while the reader holds it succeeds; `PackageIndex.FillHead` is the one bounded fill loop, which `HeadOf` and `ReadModelStatus` both call, `HeadOf`'s own tests unchanged.
  - **The marks** (`ReviewHostTests.cs`): `sessions.list` refreshes only the records whose `ModelStatus` is set, one head read each through a counting opener, and none for a ticked review's record; a record whose `session.json` now says `sent` loses its mark, and one that says `send_failed` keeps it; a record whose head read is `null` - no `session.json` (the fake backend writes none), an unreadable file, or no `model_status` within 64 KiB - keeps its `ModelStatus`, so only a head that says `sent` clears a mark; after a second `ready` (a page reload), the list still carries every waiting record's mark.

  Acceptance: red for want of the reader.
- [x] T074 [US2] [C#] Lane H. Extract `PackageIndex.FillHead(stream, maxBytes)` from `HeadOf`'s fill loop (`extractor/SwReview.Extractor/Dump/PackageIndex.cs:266-291`; one helper in the extractor's file, in this task), which `HeadOf` now calls. Add `RunFolders.ReadModelStatus(runDirectory, openHead)` in `Review/RunFolders.cs`, its default opener `FileShare.ReadWrite | FileShare.Delete`, and the refresh of the marked records in `sessions.list` in `ReviewHost.cs`, where only a head that says `sent` clears a mark and a `null` read keeps it. **Amends 002** `contracts/pane-host-messages.md` (`sessions.list` refreshes the marked records; owner decision 73A). Acceptance: T073 green; T050's mark case green and unedited (its fake backend writes no `session.json`, a `null` read, which keeps the mark); `PackageIndex`'s tests green and unedited; zero warnings.
- [x] T075 [US2] [page] Lane W. Extend `ReviewPageSendGateTests.cs` with Send (`contracts/pane.md` sections 3, 6, 8 and 10; FR-017 to FR-019, FR-033, FR-035).
  - **Send**:
    - It posts `/send`. On `202` the block hides, the turn is marked running, and the stream reopens.
    - The first `usage` clears the waiting guard and placeholder and drops the chip's mark at once (`state.sentSeen`), until the next `sessions` answer agrees (owner decision 73A). Follow-up controls then use today's turn, document and read-only guards: they enable when that turn ends, not while it still runs (`pane.md` section 6; contract clarification 2026-10-12).
    - Once a Send is in flight, Stop is today's.
    - `session.sent` writes "Sending to {provider} {model} ({requested} -> {param}={value}) - first request {n} input tokens" (owner decision 72A).
  - **Failures**:
    - On `failed_send`, no error card is drawn: the failure line shows, Send is offered again, and the text the failed round streamed stays in the Transcript.
    - A Send that fails before any request (one `error`, no `usage`, no `session.ended`) draws no error card, unmarks the turn, prints the failure line, and offers Send again.
    - `NoCredential` prints its label beside Send. A `409 TurnRunning` prints as any refusal does.
    - A ticked review whose first request fails (`error`, `turn.ended {error}`, `session.ended`) shows today's error card and Retry, and no Send block: the rule for an `error` while sending never applies, since a ticked review never sets `state.sending` (FR-035).
  - **A reload while a Send is held** (owner decision 77A; research R2.30): the page reloads while the driver holds a Send in flight and restores from `review-waiting.json`'s `sending` snapshot (`send_in_flight: true`, T071); the restore sets `state.sending`, and `failed_send`'s events played after it draw no error card and no Retry, the failure line and Send coming back.
  - **The same with one `error` and nothing after it** (from the same `sending` snapshot, a Send that failed before any request, after the reload): no error card, no Retry, the Send block back with its failure line.
  - **The document binding**: Send is disabled while another document or a drawing is active, and offered again on return.
  - **Two waiting reviews**: with two waiting chips, Send posts `/send` for the chip on screen only, and the other chip stays waiting, with its mark.

  Acceptance: red for want of the press.
- [x] T076 [US2] [page] Lane W. Implement Send in `app.js`: `state.sending`, set by the press and by a restore whose snapshot carries `send_in_flight` (owner decision 77A); `state.sentSeen`; the press; the rule for an `error` while sending, which re-reads the attention; the enabling rule; and the Transcript line, "Sending to ...", which shares `describeStart`'s effort part. Add the failure line to `render.sendBlock`. **Amends 009** `contracts/views.md` section 2 (the block sits under the summary). Acceptance: T075 green; `PageRuleScanTests` green.
- [x] T077 [US2] [page] Lane W. Extend `ReviewPageSendLayoutTests.cs` with `failed_send` and its failure line: the headline, tally and not-reached line, and the Send to model button, are inside 300 by 600 (SC-007). This is an acceptance test. Acceptance: green.
- [x] T078 [P] [US2] [py] Lane R. Extend `reviewer/tests/unit/test_replay_recording.py` and `test_cli_benchmark_replay.py` (`contracts/records.md` section 6; FR-040). Before it reads the events, `read_recording` refuses, with one `RecordingRefused` sentence each:
  - a never-sent or send-failed session: "{RUN_DIR} was never sent to the model, so it has no model turn to replay";
  - a session sent after waiting: "{RUN_DIR} was sent to the model after waiting for Send; the replay reads only reviews sent when their checks finished".

  A review sent at once reads as today. **Moved**: the refusal tables of `test_replay_recording.py` and `test_cli_benchmark_replay.py` gain the two rows ahead of the event read. Acceptance: red for want of the refusals.
- [x] T079 [US2] [py] Lane R. Implement the two refusals in `benchmark/recording.py` (`read_recording`, `:149`), placed before the existing no-usage refusal (`:163-167`). **Amends 008** `contracts/replay.md` section 2. Acceptance: T078 green; every replay test green and unedited.
- [x] T080 [P] [US2] [py] Lane B. Add `test_the_estimate_bounds_each_recordings_billed_first_round` to `reviewer/tests/unit/test_send_estimate.py` (`contracts/estimate.md` section 6; SC-006), an acceptance test over existing code. For each real OpenAI recording the replay reads, through `tests/support/recordings.recording_folder` and the vocabulary fixture, the count of the first request the replay rebuilds is at least the recording's billed first-round input and at most 35% above it. Each gap is printed as a percentage only. The test is skipped, naming why, where the mapping or a folder is absent. Acceptance: green where the recordings are; skipped, naming why, elsewhere.
- [x] T081 [US2] [py] Lane G. **US2 gate**: T033's commands (from `reviewer/`, and `extractor/SwReview.sln` from the root) and the replay regeneration step over `reviewer/tests/fixtures/replay` (the runner and the replay reader moved). Nothing is committed; T118 records the outcome.

**Checkpoint**: Send states its size, sends a ticked review's first request byte for byte, and leaves the review waiting with the reason beside Send whenever it fails before the model answers.

---

## Phase 5: User Story 3 - The Engineer's Work While It Waits Is Kept (Priority: P3)

**Goal**: answers and decisions made while a review waits are applied by code and kept at Send. The model's opening says what code applied, and names nothing that code withdrew.

**Independent Test**: spec.md User Story 3; quickstart Scenario 3.

- [x] T082 [US3] [py] Lane B. **Refactor**: extract `ReviewRun._apply_answers(answers, *, read_drawings=True)` from `answer_evidence_batch` (`agent/runner.py:1138-1202`), and have `answer_evidence_batch` call it before `_ask` (`contracts/review-flow.md` section 4; DRY). It holds the batch's steps 1, 2 and 2a: validate; mark each answer with `evidence.answered`; `read_confirmed_candidates`; the part-roles regrade; one `_restate`; and the bought-parts and unmatched-piece rows. A refactor under existing pins, with no new test: T007's resumed answer pins every request, event and record of this path. Acceptance: T007 byte-equal; `test_answer_batch_roles.py`, `test_confirmed_drawing_read.py` and `test_part_roles.py` green and unedited.
- [x] T083 [P] [US3] [py] Lane B. Write `reviewer/tests/unit/test_waiting_answers.py` over T006's package (`contracts/review-flow.md` section 4; FR-020 to FR-022, FR-024; US3 scenarios 1 to 3; SC-001).
  - **"All bought"** through `POST /evidence` on a waiting chat:
    - withdraws the unclear part's findings, with `finding.withdrawn` events;
    - makes no provider request and builds no provider, and writes no `turn.*` event;
    - settles `awaiting_send`.
  - **What it changes**:
    - The session is finalized again, so `session.json`, `report.md`, `attention.json` and the summary show the regraded review.
    - The Send cache is rebuilt once, on the worker, by `close_waiting` (owner decision 71A): a new `SendCache`, never built on the event loop. Its count is checked in T085, once T086 rebuilds the opening it counts.
    - `resume_text` is `send.apply_answers`.
  - **Refusals**: an answered question cannot be answered again. Send while an apply is held is `409 TurnRunning`, and an answer while a Send is in flight is `409`.
  - **A confirmed drawing read** while waiting, with the scripted seat, appends `{file, outcome}` to `session.drawing_outcomes` (a refusal's outcome too), and starts no turn (FR-021). With T042's seat - a real `BridgeClient` over the counting transport, answering the read on the wire - the read opens the pipe and the apply's settle closes it again (owner decision 79A).
  - **Decisions and timing**: a Reject while waiting is saved at once, is still on its finding after Send, and from then on is treated as a decision made between turns (FR-024). A timing input made while waiting is kept at Send.

  Acceptance: red for want of the waiting branch.
- [x] T084 [US3] [py] Lane B. Implement the waiting branch of `answer_evidence_batch`. After `_apply_answers` it ends in the two helpers T097's carry shares (owner decision 71A):
  1. `_settle_waiting(applied)`: append each `ConfirmedRead` to `drawing_outcomes`, and set `_opening_changed`;
  2. `close_waiting()`: `build_send_cache()`, then finalize.

  No `_ask`, no `REGRADED_LINE` and no turn event. The step `review-flow.md` section 4 places inside `_settle_waiting` between the two, replacing the restated tools' calls in `_prerun`, needs `prerun.restated` and lands with it in T086; until then `opening_at_send()` has only its frozen branch (T037), so the cache this task rebuilds still holds the frozen opening. T086 completes `_settle_waiting`. **Amends 008** `contracts/answer-batch.md` section 1 step 3; **009** spec FR-015; **011** `contracts/confirmed-open.md` section 1. Acceptance: T083 green; T007 byte-equal.
- [x] T085 [US3] [py] Lane B. Extend `reviewer/tests/unit/test_waiting_answers.py` and `test_runner_send.py` with the opening at Send (`contracts/review-flow.md` section 5; FR-013, FR-014, FR-023; SC-004, SC-005; research R2.27).
  - **The count** (FR-013): after "All bought" while waiting, the Send cache's count changes, and equals the count of the new prefix, `request_prefix(system, tools, <the rebuilt opening>)`.
  - **The size shown is the size sent** (owner decision 78A): after the apply, then Send, `count_tokens(request_prefix(<the recorded raw system prompt, tool specs and first message>))` equals `summary.send.input_tokens` read before Send, `session.sent`'s `estimate.input_tokens` and `model_status.estimate.input_tokens`.
  - **`prerun.restated(prerun, context, calls, standards)`** returns its input when nothing was restated. Otherwise it replaces each restated tool's calls in place, re-reading their findings from the standing findings that cite the call's step, and recomputes `not_evaluated` with the current roles.
  - **The frozen pin**: the builder `_opening_message` reproduces the frozen opening byte for byte when nothing was applied.
  - **After "All bought" while waiting, then Send**, the first request's opening:
    - names no withdrawn named finding, and names every standing one;
    - has a folded-family counts line equal to the regraded session's counts;
    - after the digest and before `OPENING_MESSAGE`, carries one `DRAWING_OUTCOME_LINE` per drawing outcome, in order, then one `WAIT_ANSWER_LINE` per answered question, in answer order;
    - has no "withdrew" line, and no instruction to re-run, replace or continue.
  - With no wait line, the separator is absent.
  - `opening_finding_ids` names none of the findings the answer withdrew (SC-010's fixture half).
  - **The coverage at Send after an apply** (research R2.27, RK-11): at Send's first request the session holds no row of any earlier finalization, neither the unticked start's nor the apply's (no close-out row, no unresolved row of an open question or item), so `get_review_checklist` and every `open_items` show each otherwise-open model-owned item with no matching standing finding and no surviving coverage row that places its checklist id as open (contract clarification 2026-10-13; failed, nonmatching and per-rule rows do not place it). Rows the apply's own code wrote (the part-roles row, the bought-parts rows) stay.
  - A failed Send, then an apply, then Send sends the rebuilt opening once (FR-017).
  - **Never sent again** (FR-023, last sentence; `review-flow.md` section 5). After a part-roles answer and a confirmed drawing read while waiting, then Send, the scripted first turn asks a question. The engineer answers it, then sends a follow-up. Asserted:
    - The message the answer adds, and the follow-up's, carry no `WAIT_ANSWER_LINE` and no `DRAWING_OUTCOME_LINE` of the wait.
    - Every later request, the presentation requests included, carries each of the wait's lines at most once, inside the opening it already holds.

  Acceptance: red for want of the rebuild.
- [x] T086 [US3] [py] Lane B. Implement `prerun.restated` in `prerun.py`. In `agent/runner.py`, complete T084's `_settle_waiting` with the step `review-flow.md` section 4 places between the outcomes and `_opening_changed`: replace the restated tools' calls in `_prerun` through `prerun.restated` (so T097's carry, which ends with `_settle_waiting`, restates too; owner decision 71A). Add the rebuilt branch of `opening_at_send` and `WAIT_ANSWER_LINE`. **Amends 008** `contracts/checks-first.md` section 4 (the opening rebuilt after a regrade; the wait's lines); **013** spec FR-040, `contracts/drawing-capability.md` section 6 and `contracts/part-roles.md` section 9. Acceptance: T085 green; T007 byte-equal.
- [x] T087 [US3] [py] Lane B. Extend `reviewer/tests/unit/test_waiting_answers.py` with an apply that fails (`contracts/review-flow.md` section 4, "An apply that fails"; FR-020; research R2.13; RK-12).
  - **Before the save**: `classify_part_roles`, the confirmed read, the Send cache's build and the finalization's `save_session` (`write_atomic`) each raising give:
    - one `error` event, and no `turn.ended` or `session.ended`;
    - the chat `failed`;
    - `session.json` and `report.md` holding the record before the apply, with its answers open;
    - the provider factory never called.
  - **After the save**: `write_attention_record` raising gives `session.json` as the applied record, with its answers answered.
  - Either way, the failed chat no longer holds the folder.
  - **A crash during an apply** (owner decision 76A): the folder T012's `disk_at` copies inside the apply, after the regrade and before the finalization's save, holds the record before the apply, its answers open and no turn event; T099 restores that copy with a restarted app.
  - **Shutdown during an apply** (FR-010; research R4.1): with an apply held on the chat's worker (`classify_part_roles` patched to block on an event), `ChatServer.shutdown()` writes no `turn.ended`, no `error` and no second `session.ended`, although the chat reads `running`: the session's `ended_at` is still the unticked start's, so `_finalize_on_exit` (`chat/server.py:2327-2334`) skips it through `_already_ended` (`:2337-2345`). Checked when `shutdown()` returns, before the apply is released: `session.json` is the record before the apply. This case pins today's skip and may pass before T088; it fails any later change that clears `ended_at` in the waiting branch.

  Acceptance: red for want of the failure path.
- [x] T088 [US3] [py] Lane B. Implement the waiting branch's failure path in `agent/runner.py`: `context.session = load_session(session_path)`, one `error` (`retryable: true`), then re-raise. Release a reopened confirmed-read pipe on the failed waiting settle. Bring forward only the read-only disk Send-state forwarding prerequisite for pane section 5 (unknown count, current generic reason); full T099/T100 and the recheck action stay pending. Acceptance: T087 green; the additional disk-view cases green.
- [x] T089 [P] [US3] [page] Lane W. Extend `ReviewPageSendGateTests.cs` (`contracts/pane.md` sections 4 to 6; FR-020, FR-033):
  - While the summary has a `send` block, the questions panel's button reads "Apply answers", and its sentence is the summary's `resume_text`.
  - Applying posts `POST /evidence` and locks the panel. Until the stream settles, the status line stays "Checked by code. Not sent to the model.", Stop stays off and Send is disabled.
  - A reload during an apply shows the review waiting.
  - **Apply settle and failure coverage** (contract clarification, 2026-10-13): Send stays disabled until the post-apply attention is accepted; an older attention cannot restore the pre-apply size or findings. A genuine apply failure before or after the session write, including a reload during the apply, draws no error card and restores the actual disk record read-only with its local failure beside Send. An older live attention, reopening the chip and a fresh failed snapshot cannot restore the failed live cache. A held disk restore keeps the waiting follow-up guard disabled in both the display and submit handler. A failed final attention read keeps Send locked until a fresh snapshot is loaded. Use actual backend captures; the read-only Send recheck action remains disabled until US4.

  Acceptance: red for want of the label.
- [x] T090 [US3] [page] Lane W. Implement the "Apply answers" label and the apply's state rule in `render.js` (`:682-685`) and `app.js`. **Amends 009** `contracts/questions.md` sections 4 and 5. Acceptance: T089 green; `ReviewPageQuestionsTests` green and unedited.
- [x] T091 [US3] [py] Lane G. **US3 gate**: T033's commands (from `reviewer/`, and `extractor/SwReview.sln` from the root) and the replay regeneration step over `reviewer/tests/fixtures/replay` (the runner and the pre-run moved). Nothing is committed; T118 records the outcome.

**Checkpoint**: an answer made while a review waits regrades it by code and changes the size sentence. A decision made while it waits stays on its finding. At Send, the model reads what code applied and nothing that code withdrew.

---

## Phase 6: User Story 4 - A Waiting Review Survives a Restart (Priority: P3)

**Goal**: after a Settings save, a crash or SOLIDWORKS reopening, a waiting review comes back read-only, as feature 009 restores any review, with Send offered (owner decision 68A). Send re-runs the checks from the same folder, carrying everything by identity and naming what does not carry, and then sends; nothing else re-runs them.

**Independent Test**: spec.md User Story 4; quickstart Scenario 4, and Scenario 6's restored cases.

### The backend

- [x] T092 [P] [US4] [py] Lane B. Write `reviewer/tests/unit/test_recheck.py` with the carried live step (`contracts/recheck.md` section 3; FR-028; SC-008; research R2.17).
  - **No new bridge call**: `prerun_checks(..., carried_live=LiveOutcome.from_record(...))` makes no `bridge_interference` call with SOLIDWORKS attached. The seat is a `ScriptedReviewBridge` whose `calls` stay empty before the first request.
  - **One carried step**, recorded through `registry.record_call` at the first run's `live_detection.step_index`, with the payload `{"status": "carried", "note": CARRIED_LIVE_NOTE, "outcome": ...}` and the first run's arguments:
    - every later step index and finding citation equals the first run's;
    - a repeated live call is answered with `ran_at_step` naming the carried step;
    - `tool-results/step-N.json` holds the carried payload.
  - **Every outcome carried**: the digest's interference line, the coverage rows (a clean detection's checked item in its bucket) and the withheld tools equal the first run's for each of: clean; rows found; rows collided; failed (carried as failed with the first run's `failed` row, and not retried); no bridge (no step); not an assembly (no step).
  - **Rows the first run could not write** (`persist_error`), with the dump's stale rows for that configuration still in `package.json`: no finding cites one, and the family row is `INTERFERENCE_ROWS_NOT_CARRIED`.
  - **The drawing-read capability**: `ToolContext.carry_drawing_read` sets the cache and `session.drawing_read`, so no ping is made, and a second re-run of that record makes zero bridge calls.

  Acceptance: red for want of `carried_live`.
- [x] T093 [US4] [py] Lane B. Implement:
  - in `prerun.py`: `prerun_checks(carried_live=)` (`:1052`); the carried step and its `PrerunCall`; the removal of the reviewed configuration's rows when `persist_error` is set, as `_live_interference` removes them (`:1280-1281`); `CARRIED_LIVE_NOTE`; and `INTERFERENCE_ROWS_NOT_CARRIED`;
  - in `tools/context.py` (`:403-419`): `ToolContext.carry_drawing_read`;
  - `start_review(earlier=)`, passing both.

  **Amends 008** spec FR-008, FR-009 and FR-030, and `contracts/checks-first.md` section 2 row 1 and sections 3 and 7. Acceptance: T092 green; T007 byte-equal. Review follow-up 2026-10-14 (owner decision 87A, research R8): `_carried_interference` refuses, with a `RuntimeError` and before the carried step is recorded or the seat asked (`session.started` and the pre-run's coverage and provenance events are already written), a carried step that would not land at `live.step_index`; `test_recheck.py` pins it.
- [x] T094 [US4] [py] Lane B. Extend `reviewer/tests/unit/test_recheck.py` with the claim and the rotation (`contracts/recheck.md` sections 2, 6 and 7; FR-041; RK-4). Every case that stands for a restart starts from T012's `restarted_app`, and every cut-off is a folder T012's `disk_at` copied, with nothing raised (owner decision 76A).
  - **A re-run**: `POST /sessions` with `recheck: true` and `send_when_checked: false`, from a restarted app, on a folder whose `session.json` is a not-sent record:
    - copies `session.json` and `attention.json` to index N, and moves `events.jsonl` and `tool-results/`;
    - registers its chat only after its finalization, `awaiting_send`, through the same `_open_waiting` as the unticked start (owner decision 71A);
    - answers `201 {chat_id, review_session_id, not_examined}`, as an unticked start does, with no id maps (owner decision 68A).
  - **Refusals**:
    - `recheck: true` with `send_when_checked: true` is `400 InvalidRequest`.
    - A folder with no readable `session.json`, or a deleted folder, is `404 UnknownReview`.
    - A record with no `model_status`, or one that is `sent`, is `409 NotWaiting`.
    - A live chat on the folder that is `running` is `409 RunDirInUse`.
  - **Adoption** (the same app, which is what a host that gave up meets): a second re-run sent while the first is held in the backend is `409 RunDirInUse` and starts nothing. One sent after the first answers **adopts** it: the same chat id, nothing run again, and the factory never called.
  - **Failure and cut-off**: a re-run that fails (an unreadable package, raised: FR-041's other half) leaves `session.json` byte-equal to the earlier record. So does a re-run cut off at each of three points, each copied with `disk_at`: after the rotation; after `start_review` and the carry and before the finalization; and inside `write_atomic` once its temporary is written and before `os.replace` (`disk_at(folder, BEFORE_REPLACE)`). Each copy, read by a restarted app, holds the earlier record whole; the leftover `.session.json.<random>.tmp` is passed over by `GET /reviews`, the rotation and the next re-run; the provider factory is never called; and a second re-run then succeeds at the next index.
  - **The indexes**: two failed re-runs then one that succeeds leave every index either a session with the stream it wrote, or a failed attempt's stream alone; the earlier record is copied once.
  - **Nothing written early**: with nothing carried, the carry writes nothing. `session.json`, `report.md` and `attention.json` are unchanged on disk from the claim until the finalization.

  Acceptance: red for want of `recheck`.
- [x] T095 [US4] [py] Lane B. Implement in `chat/server.py`:
  - the `recheck` field;
  - `_claim_run_dir(..., recheck=True)` (`:2025-2060`), with the adoption and `ChatServer._rechecking`;
  - `_rotate_previous(chat, keep_record=True)` (`:2062-2099`), deciding by what the canonical stream is, and passing over a leftover `write_atomic` temporary;
  - the re-run path of `create_session`: `start_review` with the earlier record, then T041's `_open_waiting` (`close_waiting` through `write_atomic`, `_render_run`, `release_bridge`, then register), and its `201` as an unticked start's.

  **Amends 002** `contracts/chat-api.md` (`POST /sessions`' `recheck`). Acceptance: T094 green; T007 byte-equal.
- [x] T096 [US4] [py] Lane B. Extend `reviewer/tests/unit/test_recheck.py` with the carry (`contracts/recheck.md` sections 4 and 5; FR-021, FR-023, FR-029, FR-032; SC-005, SC-008; the US4 independent test). Every case starts from T012's `restarted_app` (owner decision 76A).
  - **The independent test's record** holds a part-roles answer, a drawing answer whose read moved the finding and question numbers, and a Reject. Its re-run:
    - makes no extraction, and zero bridge calls before the first request;
    - puts each answer and the Reject on its own item, matched by `asks_same` and `findings.finding_subject_key`, never by number;
    - carries the outcome line.
  - **The opening after a carried answer** (owner decision 71A; FR-023, SC-005 on the restart path): after the re-run carries the part-roles answer and Send is pressed, the first request's opening names no finding the answer withdrew and names every standing one, because the carry ends with `_settle_waiting` and `prerun.restated`.
  - **Matching cases**:
    - Two `hole.coaxiality` findings on one pair of components, one of them Rejected: the Reject is carried onto its own finding, and nothing is named.
    - Each carried decision goes through `set_disposition(..., at=earlier.at)`, keeping the time it was first made, with one `disposition` event each from the function `record_disposition` emits through (owner decision 72A).
    - **Two earlier decisions that meet one re-run finding** (a profile change merges their findings): neither is carried, and each is named once, "the {decision} of {id} (another decision matches the same finding)" (72A; that neither is carried is a default the owner may revise, research R7).
    - An unmatched answer, an ambiguous answer, an unmatched decision and an ambiguous decision are each named once, in one `coverage.recheck` row (`NOT_CARRIED`).
  - **Records**:
    - The four timing inputs are carried.
    - A `send_failed` record's re-run stays `send_failed` with its failures, and its report keeps the failure line. A Send that then succeeds reports "Earlier attempts that failed: 1".
  - **The Standards profile**: when it has changed - to another file, the same file edited, a profile added where the earlier record had none, or one removed (the new settings have none) (owner decision 78A) - the re-run grades with the profile in effect, records its identity on `model_status.profile` (omitted when it has none), and names the change and any decision whose finding the new profile no longer raises. An unchanged profile names nothing.
  - **What T087's failures leave**:
    - An earlier open drawing-candidate question whose drawing an unfinished read merged is not asked again and carries no outcome line, and the loss is named once.
    - An apply that failed after its write has its answers carried.
  - **SC-008**: with nothing answered, the same provider and model, and SOLIDWORKS attached as at the first run, every request of Send's first turn after the re-run is byte-identical to the live waiting review's.
  - **The size shown is the size sent** (owner decision 78A): after the re-run, then Send, `count_tokens(request_prefix(<the recorded raw system prompt, tool specs and first message>))` equals `summary.send.input_tokens` read before Send, `session.sent`'s `estimate.input_tokens` and `model_status.estimate.input_tokens`.
  - The carry writes nothing before the finalization.

  Acceptance: red for want of `carry_from`. Review follow-up 2026-10-14 (owner decision 87A, research R8; not a new task): the worked review's merged drawing now raises a conformance finding the re-run numbers ahead of the others, so the numbers move and the test shows the Reject and the answers land on their own items; a bare-runner case carries ER-005's answer onto the re-run's ER-001; and SC-008 compares the two provider logs of Send, entry by entry, not the prepared cache. Review follow-up 2026-10-14 (owner decisions 87A and 89A): a carry that raises leaves the chat `failed` and unregistered, `session.json` byte-equal and the pane's bare 500, and the next re-run succeeds; two earlier answers that match one question carry neither and name each. Review follow-up 2026-10-14 (owner decisions 87A and 90A): the another-file and edited profile cases carry a Reject of the data-card finding, which the new profile (a data card asking for no property) no longer raises, named not carried with the profile; and cases for a profile path spelled with other capitals, a drawing read that merged some drawings and was refused for the rest, one drawing index per carry and the earlier record read off the event loop.
- [x] T097 [US4] [py] Lane B. Implement `ReviewRun.carry_from(earlier)`, `NOT_CARRIED` and the `coverage.recheck` row in `agent/runner.py`. The carry works in memory only, never calling `record_disposition`, `record_timing_live` or `save_session`. The answers go through `_apply_answers(..., read_drawings=False)`; each decision through `report/dispositions.set_disposition(..., at=earlier.at)`, announced by the `disposition` event `record_disposition` emits, extracted into one function both call (`chat/sessions.py:364`; owner decision 72A); two earlier decisions that meet one finding are named and neither carried; and the carry ends with `_settle_waiting(applied)` (owner decision 71A), so the restated pre-run and the rebuilt opening follow; `_open_waiting` then builds the Send cache. In `chat/server.py`, the re-run path of `create_session` (T095's branch) calls `run.carry_from(earlier)` on the thread pool, after `_start_review` returns and before `_open_waiting` (`contracts/recheck.md` section 4). Acceptance: T096 green; T007 byte-equal. Review follow-up 2026-10-14 (owner decision 88A, research R8): the carry ends with `_settle_waiting(applied)` only when it carried answers or drawing outcome lines; a test pins that a Reject carried alone leaves Send's requests the live waiting review's; T115 reconciles the contracts. Review follow-up 2026-10-14 (owner decisions 87A and 89A): the server runs `carry_from` inside `_open_waiting`'s thread function, before `close_waiting`, so one failure path serves the carry and the finalization (`_carry` is gone); two earlier answers that match one question carry neither, each named "the answer to {id} (another answer matches the same question)" (`NOT_CARRIED_ANSWER_SHARED`). Review follow-up 2026-10-14 (owner decision 90A): the profile paths compare through `drawings.evidence.file_key`, the digest exactly; `carry_from` builds the drawing index once; an answer whose drawing read merged some of its documents' drawings and was refused or failed for the rest is named "the answer to {id} (part of its drawing read was refused or failed, so its question is asked again)" (`NOT_CARRIED_ANSWER_PARTIAL`), and an open question such a read left is named by R2.13's lost-outcome item; `_waiting_record` runs on the thread pool, with the folder held in `_pending_run_dirs` from the claim on, so a second claim while the read awaits is `RunDirInUse`.
- [x] T098 [US4] [py] Lane B. Write `reviewer/tests/perf/test_send_gate_perf.py` under the repository's opt-in `perf` marker (`tests/conftest.py`: collected only when `-m` names it; owner decision 70A; research R2.17, RK-10). On `test_prerun_perf.py`'s thousand-group package (`thousand_group_package()`, imported), it times a ticked start, an unticked start and a re-run with a carry (from a restarted app, a Reject made while the first run waited carried onto its finding, and any answer its record holds), prints the seconds, and asserts that the unticked start's added work - the cache, the finalization and the render - stays a small fraction of the pre-run both starts share. It is an acceptance test over landed code (009's precedent). Run it with `uv run pytest -m perf -s tests/perf/test_send_gate_perf.py`, and record in research R2.17 and RK-10 the seconds and what they set: when the larger measured re-run fits inside 30 s, say so: one 30 s rule then covers every call, and `TimeoutFor` and `ChecksOnlyTimeout` go; otherwise `ChecksOnlyTimeout` is that re-run times three, rounded up to the next 30 s, the stated margin (its value a default the owner may revise, R2.17). Acceptance: green under `-m perf`; not collected by the gate's default run (`test_perf_collection_gate.py` green and unedited); the figures recorded. Review follow-up 2026-10-14 (owner decision 87A): the test asserts the re-run fits inside `ONE_RULE_S`, the measurement T104 relies on.
- [x] T099 [US4] [py] Lane R. Extend `reviewer/tests/unit/test_chat_review_routes.py` and `test_review_snapshot.py` (`contracts/recheck.md` section 8; FR-031, FR-041; owner decisions 68A and 73A):
  - `GET /reviews/{run_id}` answers a `not_sent` or `send_failed` record read-only, as every record today, with `read_only_reason` the words file's `read_only_lead`, a space, and `send.restored_line` with `{when}` the stored `checked_at` wall clock (`YYYY-MM-DD HH:MM`, never converted) - never `read_only_off` (owner decision 73A) - and with `summary.send {state: "restored", input_tokens: null, text: send.restored, rerun_failed_text, failure}` - no `session_id` and no restored line in the block.
  - A sent record, and one with no `model_status`, are read-only as today, with today's sentence (`load_words().read_only`, the two keys composed).
  - From a restarted app (T012), the folders T094's failed and cut-off re-runs left, the copy T087 took during an apply, and the `send_failed` copy T062 took before a Send's first `usage`, each answer their earlier record this way.
  - The route writes nothing.

  Acceptance: red for want of the restored block.
- [x] T100 [US4] [py] Lane R. Implement the restored block and the composed `read_only_reason` in `_read_review` (`chat/server.py:1660-1682`; one branch in lane B's file, in this task) and in `report/snapshot.py`. **Amends 002** `contracts/chat-api.md` (`GET /reviews`); **009** spec FR-021 and `contracts/sessions.md` section 4. Acceptance: T099 green.

### The restored fixtures

- [x] T101 [P] [US4] [py] Lane G. Extend `reviewer/tests/unit/test_pane_waiting_fixtures.py`, with every clock pinned:
  - `extractor/SwReview.AddIn.Tests/Fixtures/review-waiting-restored.json`, from T006's package, holds two snapshots:
    - `restored`: the run-folder snapshot of the record, with nothing answered: read-only, its `read_only_reason` the composed restored line (`read_only_lead`, a space, the dated `send.restored_line`; owner decision 73A), and the `restored` Send block;
    - `rechecked`: the re-run's `POST /sessions` answer and the re-run's live snapshot, which the page shows before it posts Send. No id maps and no snapshot of an answered record: the page re-keys nothing (owner decision 68A).
  - `review-waiting-big-assembly.json` gains `restored`.
  - `extractor/SwReview.AddIn.Tests/Fixtures/review-not-sent-session.json` is the earlier record's `session.json`, as `save_session` wrote it, for the host's cross-language head-reader case (research R4.2). Its name matches the test project's `Fixtures\review-*.json` Content glob (`SwReview.AddIn.Tests.csproj:180`), so it is copied to the output folder the add-in tests read from (`ReviewFixture.cs:189`), and the project file is not edited. As `test_pane_drawing_fixture.py:105-111` does, the test asserts each generated file's path ends `SwReview.AddIn.Tests/Fixtures/review-*.json`.

  **Moved**: the hygiene list gains `review-waiting-restored.json` and `review-not-sent-session.json`. Acceptance: red for want of the files.
- [x] T102 [US4] [py] Lane G. Extend `generate_waiting_fixtures.py` to write them, `review-not-sent-session.json` included, into `extractor/SwReview.AddIn.Tests/Fixtures/`; regenerate. Acceptance: T101 green; the hygiene test green; after `dotnet build`, `review-not-sent-session.json` is in the test project's output `Fixtures` folder.

### The host

- [ ] T103 [US4] [C#] Lane H. Extend `ReviewHostTests.cs` and `BackendClientSessionBodyTests.cs` (`contracts/recheck.md` sections 1 and 7; FR-028, FR-041).
  - **Refusals**: `review.recheck {chat_id}` is refused, changing nothing, with `InvalidRequest` (no id), `UnknownChat`, `DrawingActive`, `ReviewNotActive` (another document; the path compared ignoring case, the configuration exactly) or `BackendUnavailable`.
  - **Their order** (`contracts/recheck.md` section 1; data-model section 9): a drawing active on a re-run of a review of another document answers `DrawingActive`, not `ReviewNotActive`; another document with the backend stopped answers `ReviewNotActive`, not `BackendUnavailable`; the review's own document with the backend stopped answers `BackendUnavailable`.
  - **Otherwise**, the host, through `CreateReviewSession(..., ReviewMode.Recheck)` (owner decision 71A):
    1. posts `status {stage: "checking", message: "Checking the saved evidence again..."}`;
    2. calls `POST /sessions` with the record's own folder, the settings in effect, the bridge, `send_when_checked: false` and `recheck: true`, making no folder and dumping nothing;
    3. replaces the record: the same folder and document, the new chat id, the time now, and its `ModelStatus` kept (owner decision 73A);
    4. posts `status {stage: "ready", message: "Checked the saved evidence again; nothing was sent to the model."}` and answers `review.rechecked {chat_id, previous_chat_id, run_dir, not_examined, document}`.

    Each status's stage and message are asserted, the message as a literal (`contracts/words.md` section 5).
  - A backend refusal is rethrown with its class.
  - **The timeout** (owner decision 70A): where research R2.17 says T098's larger measured re-run fits inside 30 s, every mode's timeout is the 30 s `CallTimeout` and `TimeoutFor` and `ChecksOnlyTimeout` are gone (T050's client case moved with them); otherwise `TimeoutFor` of the `Recheck` mode, and of the `Wait` mode, is the `ChecksOnlyTimeout` literal R2.17 records.

  **Moved**: `ErrorLabelsCoverTheHostTests.TheScanFindsTheClassesTheHostAndThePageMake`'s expected list gains `ReviewNotActive`. Acceptance: red for want of the message.
- [ ] T104 [US4] [C#] Lane H. Implement `review.recheck` in `ReviewHost.cs` through T051's `CreateReviewSession(..., ReviewMode.Recheck)`, keeping the record's `ModelStatus`, and add to `CreateReviewSession`, for `ReviewMode.Recheck` only, the document binding (`ReviewNotActive`) between its drawing refusal and its backend check (data-model section 9). In `Review/BackendClient.cs`, where research R2.17 says T098's larger measured re-run fits inside 30 s, remove `ChecksOnlyTimeout` and `TimeoutFor` so every call keeps `CallTimeout`; otherwise set `ChecksOnlyTimeout` to the value R2.17 records (owner decision 70A). **Amends 002** `contracts/pane-host-messages.md` (the `status` stage `checking`). **The new row `review.recheck` waits for T108**, the commit where the page first posts it, by the rule T049 states. Acceptance: T103 green; T050's client cases green as T103 leaves them; zero warnings.
- [ ] T105 [US4] [C#] Lane H. Write `extractor/SwReview.AddIn.Tests/RunFoldersNotSentTests.cs` over fictional folders, and extend `ReviewHostTests.cs` (`contracts/recheck.md` section 9; FR-030; RK-6).
  - **Offered** when the newest same-name folder's `session.json` head says `not_sent` or `send_failed` and names this path and configuration.
  - **Not offered**:
    - behind a newer sent review;
    - behind a check run that failed with no `session.json`;
    - for another path with the same file name, or another configuration;
    - from a newest folder whose name is another document's, even when its record names this document (names come first; owner decision 78A);
    - when the host already holds a review of the document;
    - when a head has no `model_status` within 64 KiB;
    - when the root or the file is unreadable (and nothing throws).
  - **Folder names**: `-check`, `-standards` and `-remodel` folders are skipped, and the `-N` collision suffix is read.
  - **The cross-language case**: T102's `Fixtures/review-not-sent-session.json`, written by the backend's own `save_session`, is read by the head reader from the test output folder.
  - **The found item**: its chat id is its `session_id`, its time is `checked_at`'s stored wall clock, and its record's `ModelStatus` is the head's state.
  - **The access pattern** (owner decision 80A): `FindNotSentReview` takes T074's injectable head opener; over a root of 500 folders of the same document, each with a `session.json`, a counting opener is called exactly once, for the newest folder's file.
  - **The bound**: the same 500-folder root is searched within 2 s. It is a plain `[Fact]` timed with `Stopwatch`: the add-in tests carry no perf category, so it runs in the gate (precedent `ReviewPageScaleTests.cs:85`).
  - **`ReviewHostTests.cs`**:
    - `sessions.list` runs the search first, and its item carries `model_status`.
    - **A found review can be re-run** (FR-030; the US4 Independent Test's last sentence; `contracts/recheck.md` sections 1 and 9). After `sessions.list` offers a found review, `review.recheck {chat_id: <its session_id>}` is accepted, not refused `UnknownChat`. The host posts `status {stage: "checking"}` and calls `POST /sessions` with the found folder, `recheck: true`, `send_when_checked: false` and no dump. It then answers `review.rechecked`, whose `previous_chat_id` is the found `session_id`.
    - A second `sessions.list` tracks the same record: one item, the same chat id.

  Acceptance: red for want of the search.
- [ ] T106 [US4] [C#] Lane H. Implement `RunFolders.FindNotSentReview` in `Review/RunFolders.cs`: names first (`DocumentName`, `TimestampOf`, `CarriesSuffix`), then one `ReadModelStatus` head read (T074) of the newest folder only, through the injectable opener (owner decision 80A). Add the search in `sessions.list` in `ReviewHost.cs`. A found review is tracked as a review record that `review.recheck` accepts (data-model section 9): its folder, the document its `model_status.document` names (path and configuration), its chat id its `session_id`, its time its `checked_at`, and its `ModelStatus` the head's state (owner decision 73A). **Amends 002** `contracts/pane-host-messages.md` (`sessions.list`); **009** `contracts/sessions.md` sections 5 and 6. Acceptance: T105 green; zero warnings.

### The page

- [ ] T107 [US4] [page] Lane W. Write `extractor/SwReview.AddIn.Tests/ReviewPageRecheckTests.cs` on `review-waiting-restored.json` (`contracts/pane.md` sections 4, 5 and 7 to 9; `contracts/recheck.md` sections 7 and 10; FR-027, FR-030, FR-031, FR-033, FR-041, FR-042; owner decision 68A). As test infrastructure, make `ReviewPageDriver.cs`:
  - answer `review.recheck` with the fixture's `rechecked` body, with an error mode taking a given class;
  - offer `HoldReviewRecheck` and `ReleaseReviewRecheck`. A held re-run queues every later page message and answers them in order on release, as the host's one pump does.

  The tests:
  - **A restored review** is read-only: `#read-only` shows the snapshot's `read_only_reason` (the first sentence of feature 009's read-only line, then the dated Send sentence, and not 009's "Follow-ups, decisions and answers are off.": owner decision 73A), the sentence beside Send has no number, the questions panel, the decision buttons and the follow-up box are off as on any read-only restore, and Send alone is enabled. The Settings section shows `pane.md` section 9's line "Saving restarts the backend. The waiting review stays, and its Send checks its saved evidence again first." under Save, as for a live waiting review (T054; FR-027, "live or restored").
  - **Its Send**: posts `review.recheck` first, then `POST /sessions/{chat_id}/send` with the `rechecked` chat id; nothing is re-keyed. A Send refused after the re-run (`NoCredential`) leaves the review live and waiting, with its questions and decisions usable and the refusal beside Send.
  - **Found after SOLIDWORKS reopens** (FR-030; US4 scenario 5 and the US4 Independent Test's last sentence; `contracts/recheck.md` section 9; `pane.md` section 8). Today the page asks `sessions.list` after `init` (`app.js:2611`) and after a start (`:1678`); its `document.changed` case does not ask (`:238-244`).
    1. `init` arrives with no document open, and the driver answers `sessions.list` with no items.
    2. A `document.changed` to the reviewed document makes the page post `sessions.list` again. The driver (its existing `Sessions` list, filled between the two asks) answers with one item carrying `model_status`, its `started_at` (the record's `checked_at`, data-model section 9) on another day.
    3. The page shows the found chip, dated "{YYYY-MM-DD} {HH:MM}" and marked " · not sent".
    4. No review of the document is on screen, so the page follows with the new list (009 section 6's rule) and restores the review from its folder: read-only, the restored line, Send enabled.
    5. Pressing Send posts `review.recheck` with the found item's `chat_id`, then `/send`.

    A `document.changed` while a review of that document is on screen asks again and leaves that review shown.
  - **While a re-run is held**:
    - The status line reads "Checking the saved evidence again.", and the Settings line switches to "Checking the saved evidence again; save when it is done.".
    - Save, Review, the chips and Send are refused, and there is no Stop.
    - On release, the review is live and waiting, and the Settings line is the waiting one again.
  - **When it fails**:
    - A failed re-run prints `rerun_failed_text` with its class in a fold, keeps the review read-only with Send offered, and offers no Retry.
    - `UnknownReview` prints feature 009's "This review can no longer be restored.".
  - **Restarts and reloads**:
    - A backend restart (an `init` naming another backend) with a live waiting review on screen restores it at once, read-only with Send (FR-042).
    - A found chip names its date when that is not today.
    - A reload while a re-run is held shows nothing of the review until the release, then shows it: never running, and never being checked again.
  - **An apply that fails** (an `error` during an apply, with no `turn.ended`): no error card, the panel unlocked, and the review restored from its folder, read-only with Send offered, with the error's label in the Send block's failure line (`pane.md` section 5). US3 T089-T090 already covers the minimal disk restore and failure display from genuine apply-failure captures; this later fixture still covers the full recheck and restart flow.
  - **A reload during an apply that then fails** (owner decision 77A; research R2.30): the page reloads while the apply runs (the snapshot's summary has the `send` block and `send_in_flight` is absent), then the apply's `error` arrives: the same as above, no error card, the rule keyed on the summary's `send` block.

  **Moved**:
  - `ReviewPageViewsTests.TheStatusLineReadsEachOfItsSentencesInItsState` gains the re-run row.
  - `ReviewPageDefaultViewScanTests.NoRawStatusOrBucketTokenIsVisible` runs on `review-waiting-restored.json` too.

  Acceptance: red for want of the restored flow.
- [ ] T108 [US4] [page] Lane W. Implement in `app.js` and `render.js`:
  - the restored review: read-only, as feature 009 shows a restored review, with the Send block's Send enabled (owner decision 68A);
  - `state.rechecking`, and a restored review's Send: `review.recheck`, then the new chat shown and `POST /sessions/{chat_id}/send`, with no re-keying;
  - the re-run's status-line state, and the refusals while a re-run runs;
  - the restart rule after `init`, and the apply-failure restore, keyed on the summary's `send` block with no Send in flight (owner decision 77A);
  - the dated found chip; and `sessions.list` asked again on `document.changed`, after following with the list the page holds, then followed again with its answer by the same rule (`requestSessions(true)`, as after `init`).

  **Amends 002** `contracts/pane-host-messages.md`: the new row `review.recheck`, with its reply `review.rechecked`, in this commit, where the page first posts it (T049 says why). **Amends 009** `contracts/views.md` section 3 (the re-run state) and `contracts/sessions.md` sections 5 and 6. Acceptance: T107 green; `ReviewPageContractTests` green with the row in place; `ReviewPageSessionsTests` and `ReviewPagePreparationTests` green and unedited; `PageRuleScanTests` green.
- [ ] T109 [US4] [page] Lane W. Extend `ReviewPageSendLayoutTests.cs` with two cases: `restored`, with its restored line and sentence; and `restored` after a failed re-run, with the `rerun_failed` line. In each, the headline, tally and not-reached line, and the Send to model button, are inside 300 by 600 (SC-007). Record the measured figure in research R2.21. An acceptance test. Acceptance: green; if it fails, the owner question of research R2.21's end state.
- [ ] T110 [US4] [py] Lane G. **US4 gate**: T033's commands (from `reviewer/`, and `extractor/SwReview.sln` from the root) and the replay regeneration step over `reviewer/tests/fixtures/replay` (the runner, the pre-run and the records moved). Nothing is committed; T118 records the outcome.

**Checkpoint**: a waiting review survives a Settings save, a crash and SOLIDWORKS reopening, read-only with Send. Its Send re-runs the checks from its own folder, with zero extractions and zero bridge calls, and only then sends. Everything is carried by identity, what is not carried is named, and nothing is sent before Send.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: the last record that names a provider, the seat's step, the contracts as landed, the adversarial review, and the final gate.

- [x] T111 [P] [py] Lane R. Extend `reviewer/tests/unit/test_handoff.py` (`contracts/records.md` section 7; research R2.24; owner decision 73A, this plan's question 2 kept). The handoff bundle's session summary gains `model_status` (its state) when the session carries one, beside `provider_info`, and nothing else in the export moves. A ticked session's bundle is unchanged. Acceptance: red for want of the key.
- [x] T112 [py] Lane R. Implement it in `_session_summary` in `handoff.py` (`:360-401`). **Amends 002** `contracts/handoff-export.md`. Acceptance: T111 green.
- [x] T113 [P] [py] Lane S. Add `"015-review-send-gate"` to `PACKAGES` in `reviewer/tests/support/seat_tasks.py`, and to its docstring. `test_workstation_test_plan.py` and `test_workstation_handover.py` go red, naming 015 T119 as unplaced. Acceptance: red for want of the step.
- [x] T114 [doc] Lane S. Place T119 in the sitting's three documents:
  - `docs/test-plan-2026-09-27/workstation-test-plan.md` gains step 4.10, "A, unticked, then Send [015 T119]", with quickstart Scenario 8's seven steps (no design name or number), the reopen of SOLIDWORKS while a review waits and the big assembly's timings included;
  - `workstation-results.md` gains its row, shipped blank;
  - `workstation-handover.md` gives T119 its place in the sitting.

  Acceptance: T113 green.
- [ ] T115 [doc] Lane C. Reconcile the contracts with what landed:
  - Where code had to differ, each 015 contract in `specs/015-review-send-gate/contracts/` gets a dated "*Landed as*" note.
  - Each row of `contracts/README.md`'s amendments table now has its amendment text in place, not only T001's note.
  - Research R2.21 holds the measured figures from T056, T077 and T109.

  Documents only.
- [ ] T116 [doc] Lane C. Adversarial review (62A). An Opus reviewer who wrote none of the code reads the branch's whole diff against `spec.md`, the contracts and this list. The reviewer hunts for:
  - any path that reaches a provider before Send (SC-001);
  - any byte a ticked review changes (FR-035);
  - any record that says sent or not sent wrongly (FR-032);
  - any carry by number (FR-029);
  - anything the re-run writes before its finalization (FR-041);
  - anything but Send that starts a re-run, or anything usable on a restored review but Send (owner decision 68A);
  - any write to a waiting session outside the chat's worker, or any clear of the stop flag outside `_play` (owner decision 69A);
  - any page word or colour outside the design system (FR-005);
  - any company value or local path (FR-039).

  Each finding is either fixed test-first in the task that owns the file (one commit each, every commit passing the gate), or recorded in `research.md` as a default the owner may revise. Acceptance: the review's findings are each fixed or recorded.
- [ ] T117 [py] Lane G. **Only when feature 014 is on `main` before this branch merges** (research R3; RK-8). In the merge commit:
  - classify `send_when_checked` and `earlier` as `COMPARED` in 014's `reviewer/tests/unit/test_benchmark_pane_parity.py`;
  - pass `mark` on every 015 call of `recorded_call`, and stamp the carried live step `origin_mark: "prerun"`, with the assertion added to `test_recheck.py`;
  - keep 014's `atomic.py` and `test_atomic.py`, one copy each;
  - regenerate `review-big-assembly.json`, checking that its snapshot part is 014's and its labels block 015's;
  - regenerate T007's five goldens on the first-merged side alone, and check that the merged code passes them unchanged.

  Then, where the recordings are, run research R2.28's replay regeneration step against 014's regenerated fixtures. A difference is a defect for the branch that caused it to explain or fix, never a fixture to regenerate in the merge. Acceptance: the gate green on the merge commit.
- [ ] T118 [py] Lane G. **Final gate** (quickstart, "The gate"; 62A). From `reviewer/`, run `SWREVIEW_REQUIRE_TOKENIZER=1 uv run pytest -q -p no:warnings -o addopts="" -m "not live"` and `uv run ruff check src tests`. From the repository root, run `dotnet build extractor/SwReview.sln -c Release --nologo -v q` (zero warnings) and `dotnet test extractor/SwReview.sln -c Release --no-build --nologo`. Then:
  - run research R2.28's replay regeneration step, expecting no difference, or skip it, naming why;
  - run quickstart Scenarios 1 to 7 by their commands, the opt-in `uv run pytest -m perf -s tests/perf/test_send_gate_perf.py` of Scenario 4 included, and check its figures against research R2.17's.

  Record each outcome, with the outcomes of the phase gates (T033, T057, T081, T091, T110), in `specs/015-review-send-gate/quickstart.md`'s Results, in counts and words only. Acceptance: every command green.

**Checkpoint**: every record says whether its review was sent, the seat's step is placed, the contracts say what landed, the review is answered, and the gate is green.

---

## Phase W: The pilot workstation

**Purpose**: what only the seat can show (62A, SC-010). The result goes into the sitting's results sheet and its findings document, outside the repository; nothing from the seat is committed but the results' words.

- [ ] T119 [W] Lane S. Run quickstart Scenario 8 on the small assembly, and its timings on the big assembly too, with the build of this feature and the owner's key stored (SC-010).
  1. Untick the box, then close and reopen SOLIDWORKS: the box is still unticked.
  2. Press Review. Record the waiting status, no Stop, and `not_sent` in the run folder's `session.json`.
  3. If the checks raise the part-roles question, answer it while the review waits. If they raise none, record that. If every finding the answer withdrew is in a folded family, record that too: the named-ids check then proves nothing about them.
  4. Press Send to model.
  5. Record:
     - zero model rounds before Send (every `usage` event follows `session.sent`);
     - one extraction in total;
     - that `model_status.opening_finding_ids` names none of the findings the answer withdrew;
     - whether the sentence carried a number (RK-9: whether `swreview tokenizer fetch` ran on the seat).
  6. **Close SOLIDWORKS while a review waits** (owner decision 78A): press Review again with the box still unticked and wait until the review waits; close SOLIDWORKS; reopen it and open the small assembly. Record that the review comes back from its run folder, read-only, its chip dated and marked not sent, with Send offered.
  7. Record the timings, against the bound research R2.17 records (owner decision 70A):
     - how long step 2's unticked `POST /sessions` took (from the backend log, or else between the host's last "Extracting" status and its ready status: an unticked start posts no "checking" status);
     - how long the re-run takes: press Send to model on the review step 6 brought back, and record how long the re-run before the first request took (between the host's "checking" and "ready" statuses, or from the backend log), and that the run folder still holds one extraction;
     - the same two on the big assembly: an unticked review of it, then SOLIDWORKS closed and reopened (or Settings saved, which restarts the backend), then Send.

     A seat re-run longer than 30 s where the one 30 s rule applies, or longer than a third of `ChecksOnlyTimeout` where it does not, is reported to the owner, and the bound is set again from it by research R2.17's rule in a follow-up, recorded in R2.17 and RK-10. The unticked-start timings are recorded for information only: 70A sets the bound from the re-run (R2.17).

  Record no design name, number or path.

---

## Commit groups

The table names the ordered task groups. In the authorized 2026-10-12 US1 execution, C08–C17 (T013–T032), C18–C24 (T034–T047), and C25–C29 (T048–T056) each form one cohesive commit. Every task pair still proves its prescribed red first, becomes green in task order, and satisfies its acceptance lines and same-commit source, schema, fixture and owning-contract amendments. Each actual commit passes the full gate on its exact candidate; combined gate receipts name every included group. Later groups remain one commit each (two for T116's fixes if it has two findings). Test and implementation tasks share a commit, so no commit holds a red test. The two pins are committed alone, first, green on the pre-feature code. The gate tasks (T033, T057, T081, T091, T110) commit nothing.

| Group | Tasks | What lands |
|---|---|---|
| C01 | T001 | the amendment notes |
| C02 | T003-T004 | one recording provider |
| C03 | T005-T006 | the fictional questions package |
| C04 | T007 | the characterization of a ticked review (pre-feature code) |
| C05 | T008 | the prefix characterization (pre-feature code) |
| C06 | T009-T010 | `atomic.py` (only while 014 is not on `main`) |
| C07 | T011-T012 | the restart and crash helper (owner decision 76A) |
| C08 | T013-T014 | the session fields and the 001 schema |
| C09 | T015-T016 | `local_now` |
| C10 | T017-T018 | `awaiting_send` |
| C11 | T019-T020 | `DeferredProvider` and `effort_mapping_for` |
| C12 | T021-T022 | `configure_provider` |
| C13 | T023-T024 | `request_prefix` moved |
| C14 | T025-T026 | `asks_same` |
| C15 | T027-T028 | `_render_run` |
| C16 | T029-T030 | the words and the pane fixture's labels |
| C17 | T031-T032 | the setting (two members) and its schema |
| C18 | T034-T035 | `start_review` unticked and its finalization |
| C19 | T036-T037 | the Send cache, `close_waiting` and the estimate |
| C20 | T038-T039 | the report header |
| C21 | T040-T041 | the unticked `POST /sessions` through `_open_waiting`, and `NotSent` |
| C22 | T042-T043 | the pipe released while waiting (owner decision 79A) |
| C23 | T044-T045 | the summary's `send` block and the one token formatter |
| C24 | T046-T047 | the routes carry the block |
| C25 | T048-T049 | the box's host message and the one persist step |
| C26 | T050-T051 | `review.start` through `CreateReviewSession`; the mark; `TimeoutFor`'s seam |
| C27 | T052-T053 | the two waiting fixtures |
| C28 | T054-T055 | the page: box, waiting state, Send block, the chip mark |
| C29 | T056 | the layout acceptance |
| C30 | T058-T059 | `has_credential` |
| C31 | T060-T064 | the Send route, Send, the first round, `session.sent` (one commit: the route submits `run.send`, which T064 adds) |
| C32 | T065-T066 | a failed Send, the guard, and the pipe released at the settle |
| C33 | T067-T068 | the decision and timing writes queued on the worker |
| C34 | T069-T070 | the snapshot's `send_in_flight` |
| C35 | T071-T072 | `sending` and `failed_send` in the fixtures |
| C36 | T073-T074 | the host's head reader and the marks refreshed |
| C37 | T075-T076 | the page's Send, after a reload too |
| C38 | T077 | the layout with a failure line |
| C39 | T078-T079 | the replay's refusals |
| C40 | T080 | SC-006 over the recordings |
| C41 | T082 | `_apply_answers` (refactor) |
| C42 | T083-T084 | answers while waiting |
| C43 | T085-T086 | the restated pre-run and the opening rebuilt |
| C44 | T087-T088 | an apply that fails |
| C45 | T089-T090 | "Apply answers" on the page |
| C46 | T092-T093 | the carried live step |
| C47 | T094-T095 | the claim, the rotation, the adoption |
| C48 | T096-T097 | the carry |
| C49 | T098 | the re-run measured (opt-in) and its figures recorded |
| C50 | T099-T100 | the restored block and the composed line |
| C51 | T101-T102 | the restored fixtures |
| C52 | T103-T104 | `review.recheck` in the host, and the measured timeout |
| C53 | T105-T106 | the found review after a reopen |
| C54 | T107-T108 | the page's restored flow |
| C55 | T109 | the layout of a restored review |
| C56 | T111-T112 | the handoff's model status |
| C57 | T113-T114 | the seat step placed |
| C58 | T115 | the contracts as landed |
| C59 | T116 | the adversarial review's fixes |
| C60 | T117 | the 014 merge (conditional) |
| C61 | T118 | the gate's Results |

---

## Dependencies & Execution Order

### Phase dependencies

- **Setup** (T001; T002 done): no dependency.
- **Foundational** (T003-T033): the accepted upstream baseline is integrated, recorded and verified first; then T007 and T008 are committed on that pre-feature code before any task edits `reviewer/src/`. The phase blocks every story.
- **US1** (T034-T057): needs the Foundational phase. This is the MVP.
- **US2** (T058-T081): needs US1 (a waiting review to send).
- **US3** (T082-T091): needs US1. Its "kept at Send" and opening cases need US2's `send` (T064, T066).
- **US4** (T092-T110): needs US1 to US3. The carry reuses `_apply_answers` (T082) and reads what an apply failure leaves (T087-T088).
- **Polish** (T111-T118): after the stories. T117 only when 014 is on `main` first.
- **Workstation** (T119): after T118, on a build of this branch on the seat.

### User story dependencies

- **US1 (P1)**: independent once the Foundational phase is done.
- **US2 (P2)**: builds on US1's waiting review, and is testable on its own: Send a fixture review.
- **US3 (P3)**: builds on US1, and on US2 for the cases that press Send.
- **US4 (P3)**: builds on US1 to US3. Both P3 stories are in this order because the carry needs US3's apply.

### Task-level dependencies

- T004 and T006 come before T007. T007 and T008 are committed before T010 and every later task that edits `reviewer/src/`.
- T012 (the restart helper) before T062, T087, T094, T096, T098 and T099, which stand for a restart, a crash or a kill with it.
- **Foundational pieces before their users**:
  - T008 before T024.
  - T010 before T014.
  - T014 before T035, T064 and T097 (the writers of the fields).
  - T016 before T035 and T064.
  - T018 before T041.
  - T020 before T022 and T041.
  - T022 before T064.
  - T024 before T037.
  - T026 before T097.
  - T028 before T041.
  - T030 before T045 and every page task.
  - T032 before T049 and T051.
- **US1**:
  - T035 before T037, T037 before T041, and T041 before T047 and T061.
  - T039 before T041: T040 reads the report header T039 renders, so C20 (the header) lands before C21 (the unticked start).
  - T041 before T043 (`_open_waiting`, where the pipe is released); T043 before T066 (the second call).
  - T051 before T074 and T106 (`SessionRecord.ModelStatus`).
  - T045 and T047 before T053; T053 before T054-T056.
- **US2**:
  - T059 before T061, and T061 before T064, in one commit (C31: the route submits `run.send`, which T064 adds).
  - T064 before T066; T066 before T070 (the guard and the failure branch clear `_send_in_flight`) and T072; T072 before T075-T077.
  - T074 before T106 (the search reads through its head reader).
- **US3**:
  - T082 before T084 and T097; T084 before T086 and T088.
  - T086 completes the waiting branch T084 starts (the restated `_prerun` and the rebuilt opening), so T086 before T097, whose carry rebuilds the opening.
  - T088 before T096 (it reads what an apply failure leaves).
- **US4**:
  - T093 before T095, and T095 before T097.
  - T097 before T098 (the re-run with a carry), and T098 before T103-T104 (the measured value they set).
  - T095 before T099 (its failed re-runs), T088 before T099 (the copy T087 takes), and T064 before T099 (the copy T062 takes).
  - T100 before T102; T102 before T105 (`review-not-sent-session.json`) and T107.

### Parallel opportunities, by lane

| Lane | Tasks | Runs beside |
|---|---|---|
| G (pins, fixtures, gates) [py] | T007-T008, T011-T012, T033, T052-T053, T057, T071-T072, T081, T091, T101-T102, T110, T117, T118 | its pins first and alone; its fixtures once the backend they play has landed |
| R (records, report, words) [py] | T009-T010, T013-T014, T029-T030, T038-T039, T044-T045, T078-T079, T099-T100, T111-T112 | B, H, W |
| B (backend, runner) [py] | T015-T028, T034-T037, T040-T043, T046-T047, T058-T070, T080, T082-T088, T092-T098 | R, H, W; its hot files edited in task order |
| H (host, settings) [C#] | T031-T032, T048-T051, T073-T074, T103-T106 | every lane |
| W (page) [page] | T054-T056, T075-T077, T089-T090, T107-T109 | the backend lanes, once the fixture it reads exists |
| C (contracts) [doc] | T001, T115 | none: first and last |
| S (seat) [py] [doc] | T113-T114, T119 | every lane |

**Hot files, edited in this order and never in parallel**:
- `agent/runner.py`: T022, T024, T035, T037, T043, T047, T064, T066, T082, T084, T086, T088, T093, T097.
- `chat/server.py`: T028, T041, T043, T047, T061, T066, T068, T070, T095, T097, T100.
- `app.js`: T055, T076, T090, T108.
- `ReviewHost.cs`: T049, T051, T074, T104, T106.
- `test_runner_send.py`: T015, T021, T034, T036, T062, T065, T085.
- `test_send_gate_server.py`: T027, T040, T042, T046, T060, T063, T065, T067, T069.
- `test_recheck.py`: T092, T094, T096.

### Parallel examples by story

- **Foundational**: T003, T005 and T008 are written together. After T007, T009, T011, T013, T015, T017, T019, T023, T025, T027, T029 and T031 are all separate files and can be written together. Their implementations follow in commit-group order.
- **US1**: T034, T038, T040, T044, T048, T050 and T052 together (seven files across lanes B, R, H and G). Then T054 once T053 is in.
- **US2**: T058, T060, T062, T071, T073, T078 and T080 together; the lane B implementations are serial. Then T075 once T072 is in.
- **US3**: T083 and T089 together.
- **US4**: T092 and T101 together. T099 after T095 (it reads T094's failed re-runs); T103 after T098 (the measured value); T105 and T107 after T102.

---

## Implementation Strategy

### MVP first (User Story 1)

Before step 1, integrate and verify the accepted 010 baseline, and record its commit in
`review-2026-10-12.md`. The review's open FR-041 finding must be resolved before US4, not before
this US1 milestone; no promise of US4 failure recovery is changed by this review.

1. Setup (T001), then the two pins on the pre-feature code (T007-T008).
2. The rest of the Foundational phase (T009-T033).
3. US1 (T034-T057).
4. **Stop and validate**: on a fictional fixture with no key, an unticked review runs the checks, saves itself, shows its findings and waits, and nothing reaches a provider (quickstart Scenarios 1 and 5). The engineer already has the option the owner asked for, whose fallback is to press Review again with the box ticked.

### Incremental delivery

1. US2 adds the approval: Send, and its size.
2. US3 keeps the work done while the review waits.
3. US4 makes the wait survive a restart, including the Settings save that enters the key Send needs.
4. Polish closes it with the review and the gate, and T119 checks it on the seat.

Each story ends with its gate and leaves a ticked review byte-identical to the pre-feature code (T007).

---

## Requirement coverage

| Requirement | Tasks |
|---|---|
| FR-001 | T054-T056 |
| FR-002 | T031-T032, T048-T051, T054-T055 |
| FR-003 | T050-T051, T054-T055 |
| FR-004 | T032 (the lever guard unedited) |
| FR-005 | T054-T056, T077, T109 |
| FR-006 | T034-T035, T040-T041 |
| FR-007 | T019-T020, T040-T041 |
| FR-008 | T036-T037, T040-T041, T046-T047 |
| FR-009 | T034-T035 |
| FR-010 | T034-T035, T040-T041, T087-T088 |
| FR-011 | T034-T035, T062, T064 |
| FR-012 | T036-T037, T044-T045, T054-T055, T080 |
| FR-013 | T023-T024, T036-T037, T083-T086 |
| FR-014 | T062-T064, T085-T086 |
| FR-015 | T063-T064 |
| FR-016 | T058-T061, T065-T066 |
| FR-017 | T065-T066, T069-T070, T071-T072, T075-T076 (a failure after a reload too), T085 |
| FR-018 | T060-T061, T067-T068, T075-T076 |
| FR-019 | T040-T041, T054-T055, T063-T064, T075-T076 |
| FR-020 | T082-T084, T087-T090, T107-T108 (a failed apply restores the review read-only with Send) |
| FR-021 | T083-T086, T096-T097 |
| FR-022 | T083-T084 |
| FR-023 | T085-T086 (its last sentence included: none of the wait's lines sent again), T096-T097 (on the restart path: the opening after a carried answer) |
| FR-024 | T067-T068, T083-T084, T096-T097 |
| FR-025 | T040-T041, T054-T055, T060-T061, T065-T066 (a stop during a build that fails) and T067-T068 (a stop during a held write): no stop is left behind |
| FR-026 | T050-T051 (the host's mark), T073-T074 (the marks refreshed, exact after a reload), T054-T055 |
| FR-027 | T048-T049, T054-T055 (the line, live), T107-T108 (the line, restored, and the re-run's line) |
| FR-028 | T092-T097, T098 (the re-run's measured wait), T103-T104 |
| FR-029 | T025-T026, T096-T097 |
| FR-030 | T073-T074 (the bounded head reader, opened so the backend can still write), T105-T106 (the search, one file opened; a found review that `review.recheck` accepts), T107-T108 (`sessions.list` asked again on `document.changed`; the found review restored and sent) |
| FR-031 | T029-T030 (the read-only lead key), T099-T100, T107-T108 |
| FR-032 | T013-T014, T038-T039, T062-T066, T096-T097 |
| FR-033 | T054-T055, T069-T072 and T075-T076 (a reload during a Send), T089-T090, T107-T108 (a reload during a re-run, and during an apply that fails) |
| FR-034 | T029-T030, T044-T045, T054-T056 |
| FR-035 | T007 (five scenarios, the ticked failures included), T008, T029-T030, T063, T075, every task's "T007 byte-equal", T118 |
| FR-036 | T013-T014, T031-T032, T034-T035, T069-T070 (`send_in_flight`, present only while true) |
| FR-037 | T034 (the defaults, and the command-line review's printed lines), T007, `test_cli.py` unedited |
| FR-038 | T001, every "Amends" task, T115 |
| FR-039 | T005-T006, T052-T053, T101-T102, T114, T116, T119 |
| FR-040 | T078-T079 |
| FR-041 | T011-T012 (a kill as the folder it leaves, a restart as a backend started afresh), T094-T095, T099-T100, T103-T104 (the host's refusals and its timeout), T107-T108 |
| FR-042 | T107-T108 |
| SC-001 | T040, T054, T083, T094, T096, T116 |
| SC-002 | T040 |
| SC-003 | T007, T029-T030, T052-T053, T118 |
| SC-004 | T036, T063, T065, T085 |
| SC-005 | T085-T086, T096-T097 (on the restart path) |
| SC-006 | T080 |
| SC-007 | T056, T077, T109 |
| SC-008 | T092-T097 |
| SC-009 | T038-T039 |
| SC-010 | T085 (the fixture half), T119 |

---

## Notes

- **Where these tasks depart from the plan's delivery order** (defaults taken 2026-10-09; the owner may revise each):
  - `ReviewPageDriver.cs`'s two replies land with the first page test that reads each one (T054 and T107), not as a Foundational task of their own.
  - `PrerunResult.named_finding_ids()` lands in US1, with the Send cache that holds it (T037), not in US3.
  - `model_status.profile` is recorded by the first run (T035), so every waiting record carries what a re-run compares.
  - The backend's `NotSent` refusal of a follow-up lands in US1 (T041), since FR-019 is US1's acceptance.
  - `recheck` is parsed, and its `400`, tested only in US4 (T094).
  - **Contract clarification, 2026-10-13:** US3 T089-T090 covers the disk restore and local failure display after a failed apply, including a reload during it. The minimal disk Send view is forwarded in US3; its full composed read-only reason, carry, recheck trigger and restart flow remain pending in US4 T099-T108.
  - The status-line test is renamed once, without a count (T054).
  - One more generated file, `Fixtures/review-not-sent-session.json` (T101), is the backend-written record for the host's cross-language head read (research R4.2).
  - `SessionRecord.ModelStatus` lands in US1 (T051), and the host's head reader with the marks' refresh in US2 (T073-T074), before the search that reuses the reader (T105-T106): the chip's mark is the host's record from the first unticked start (owner decision 73A).
  - The re-run's wait is measured in US4 (T098) and set by T104 - one 30 s rule, `TimeoutFor` removed, when the re-run fits inside 30 s; until then every call keeps 30 s (owner decision 70A).
  - The phase gates commit nothing.
- **Between T041 and T084**, an answer to a waiting review reaches `_ask`, and the deferred provider refuses it (`ProviderNotSent`). That fails the chat, with nothing sent, so SC-001 holds at every commit. The branch is not released between stories, and US3 closes the gap.
- **Between T064 and T068** (C31 to C33), a decision or timing write accepted on a waiting chat still runs on the thread pool (`run_in_threadpool`), so a Send accepted while it writes can run beside it on the chat's worker: RK-14's two writers on one session. Nothing is sent early, so SC-001 holds; T068 closes the window inside US2, before its gate (T081).
- **Between T084 and T086**, an answer applied while a review waits rebuilds the Send cache from the frozen opening, and `_prerun` is not yet restated, so a Send in that window would send an opening that may name a finding code withdrew, and a size that does not count the regrade. Nothing is sent before Send, so SC-001 holds; T086 closes the window inside US3, before its gate (T091).
- A task's "Cause" is historical file:line at `838b66b`. Before T007-T008, the baseline integration above records the accepted pre-015 code (including 010); every cause is re-verified against it before editing. No 015 product change precedes the characterizations.
- "Amends NNN" means the task writes that contract's amendment text in the same commit as the code. T001 placed the one-line note first.
- No task reads a run folder, a recording (T080 and the regeneration step read them only where the owner's mapping is, and print percentages and pass/fail only), a real profile, or the seat's results. Every committed fixture is generated from fictional builders.
- Merge note with feature 014: research R3's table, and T117 when 014 is on `main` first. Otherwise 014's branch reconciles at its own merge, using the same table.
- **Owner decisions 68A to 80A** (2026-10-09, research R7) were applied to this list test-first: 68A (Send the only re-run trigger; a restored review read-only) in T094-T097 and T099-T108; 69A (the worker queue; the build inside Send) in T060-T068; 70A (the measured wait) in T050-T051, T098 and T103-T104; 71A (the shared tails) in T036-T041, T050-T051, T084-T086, T094-T097 and T103-T104; 72A (the commit order, one withdrawal, one disposition writer, two decisions on one finding) in T062-T066 and T096-T097; 73A (one settings write, two members, the host's marks, the handoff, the read-only lead key and the composed line, one token formatter) in T001, T029-T032, T044-T051, T054-T055, T073-T074, T099-T101, T107 and T111; 74A (what an unticked start loads) in T019; 75A (five characterization scenarios) in T007, T040 and T065; 76A (the restart helper) in T011-T012 and every crash and restart case; 77A (a reload during a Send or an apply) in T069-T070, T075-T076 and T107-T108; 78A (the size held to the request sent; the search's name case; the seat's reopen; two profile cases) in T003-T004, T063, T085, T096, T105 and T119; 79A (the pipe released) in T042-T043, T063, T065-T066 and T083; 80A (the search's access pattern) in T073-T074 and T105-T106.
