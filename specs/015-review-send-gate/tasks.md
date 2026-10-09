---

description: "Task list for the send-to-model checkbox"
---

# Tasks: Send the Review to the Model Only When the Engineer Wants It

**Input**: Design documents from `/specs/015-review-send-gate/` (`spec.md`, `plan.md`, `research.md`, `data-model.md`, `contracts/`, `quickstart.md`)

**Prerequisites**: features 001 to 013 on main (`838b66b`; this branch's product code is equal to it until the first task below that edits `reviewer/src/`). Feature 014 is not merged: its branch stood at `28d7ae9` on 2026-10-09, which adds a benchmark design and its own tasks to `45b5076`, the head research R3 intersected, and touches none of R3's files. No licence and no key are needed before Phase W; the tokenizer vocabulary is fetched once (quickstart, Prerequisites). No run folder, recording or real profile is read by a test or enters the repository; every new fixture is fictional (`FICT-`, paths under `C:\Fictional\`).

**Tests**: REQUIRED, and **strictly test-first** (62A, Principle III): every implementation task follows the test task that must be written and must fail first ("Acceptance: red for want of ..."), and names it ("Acceptance: Txxx green"). Two pins come before everything else and are committed **green on the pre-feature code**: the characterization golden of a ticked review (T007) and the prefix characterization (T008) (research R2.28). Every later commit keeps both byte-equal, and no task regenerates them. One task, T074, is a refactor with no new test: T007 pins its path, and it says so. Four tasks are acceptance tests written after the code they check, and pass with no further code (T052, T069, T072, T100; 009's precedent). The tests that go red **by design** are named, with their file, in the task that moves them (research R4.3), and are edited deliberately there, never loosened. What must not move: T007's golden, T008's values, the pane fixture's snapshot part (its labels block gains keys only, in T028), every replay fixture, every check golden (`reviewer/tests/golden`), `test_no_lever_in_pane_settings.py`, `test_session.py`, `test_runner_provider.py`, `test_part_roles.py`, `test_confirmed_drawing_read.py`, `test_answer_batch_roles.py`, `test_replay_fixtures.py`, `test_cli.py` (the command-line review gains nothing, FR-037; T032 pins its printed lines), `PageRuleScanTests.cs`, `ReviewPageSessionsTests.cs`, `ReviewPageQuestionsTests.cs`, `ReviewPagePreparationTests.cs`, `ReviewPageSummaryAcceptanceTests.cs` and `ReviewPageNarrowLayoutTests.cs` (each of the last two runs with the box in place, unedited).

**Gates before every commit** (quickstart, "The gate"). From `reviewer/`, run `SWREVIEW_REQUIRE_TOKENIZER=1 uv run pytest -q -p no:warnings -o addopts="" -m "not live"` and `uv run ruff check src tests`. From the repository root, run `dotnet build extractor/SwReview.sln -c Release --nologo -v q` (zero warnings) and `dotnet test extractor/SwReview.sln -c Release --no-build --nologo`. The add-in tests are part of the gate (62A). Each story phase ends with a gate task that adds research R2.28's replay regeneration step (T031, T053, T073, T083, T101, T109).

**Organization**: Setup (the amendment notes). Foundational: the two pins first, then the shared pieces. Then one phase per story in priority order: US1 checks only (P1, the MVP); US2 Send (P2); US3 work while it waits (P3); US4 a waiting review survives a restart (P3). Then Polish, which holds the adversarial review and the final gate, and Phase W for the pilot workstation.

## Format: `[ID] [P?] [Story] [kind] Lane. Description`

- **[P]**: can run in parallel (different files, no dependency on another unfinished task)
- **[Story]**: `US1` to `US4`; Setup, Foundational, Polish and Workstation tasks carry none
- **[py]**, **[C#]**, **[page]**, **[doc]**: the kind of file the task touches (the Python reviewer; the add-in's C# and its C# tests; the Review page and its C# page tests; documents only)
- **Lane B, R, H, W, C, G, S**: the lane that owns the files the task edits (`plan.md`, "Lanes and file ownership"). Where a task edits one line in another lane's file, it says so.
- **Cause**: file:line at `838b66b`, re-verified on 2026-10-09 (research's VERIFIED entries). Line numbers drift; re-verify before editing.
- **Amends NNN**: the other feature's contract or requirement the task changes. The task writes the amendment text in the same commit as the code; T001 places the one-line note pointing here first.
- **[W]**: needs the licensed SOLIDWORKS seat on the pilot workstation

## Path Conventions

- Python: `reviewer/src/swreview/`, tests in `reviewer/tests/`; commands run from `reviewer/` with `uv run`
- C#: `extractor/SwReview.AddIn/`, tests in `extractor/SwReview.AddIn.Tests/` (the offscreen WebView2 page suites included)
- Page: `extractor/SwReview.AddIn/Review/ReviewPage/` (`index.html`, `app.js`, `render.js`, `app.css`)
- Contracts: `specs/015-review-send-gate/contracts/` (written by the plan; a task whose code had to differ reconciles its contract, T106); other features' contracts are edited by the task that changes their shape

---

## Phase 1: Setup

**Purpose**: before any code, every contract this feature amends carries a dated note saying so.

- [ ] T001 [doc] Lane C. Add a one-line amendment note to each contract feature 015 amends (`contracts/README.md`, "Contracts of other features this feature amends"). Date it 2026-10-08 and point it at the 015 contract that holds the text. The contracts are:
  - 001: `contracts/README.md`, for `review-session.schema.json`
  - 002: `contracts/README.md` (for `settings.schema.json` and `chat-events.schema.json`), `contracts/chat-api.md`, `contracts/pane-host-messages.md`, `contracts/handoff-export.md`, and `data-model.md` sections 3 and 4
  - 008: `contracts/checks-first.md`, `contracts/answer-batch.md`, `contracts/cost.md`, `contracts/tokenizer.md` and `contracts/replay.md`
  - 009: `contracts/sessions.md`, `contracts/views.md`, `contracts/questions.md` and `contracts/review-summary.md`
  - 011: `contracts/confirmed-open.md`
  - 013: `contracts/drawing-capability.md` and `contracts/part-roles.md`

  Also add a one-line pointer above the Functional Requirements of four specs, naming the requirements amended: 002 (FR-006), 008 (FR-008, FR-009, FR-030), 009 (FR-015, FR-021) and 013 (FR-040). Documents only. JSON schemas carry no comment, so their notes sit in the owning README. No amended text moves here: each "Amends" task below writes its text with its code (FR-038).
- [x] T002 [doc] Lane C. `.specify/feature.json` names `specs/015-review-send-gate`. *Done with the spec, 2026-10-08.*

**Checkpoint**: every amended contract says so.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: first, the two pins of a ticked review on the code as it was (research R2.28). Then the shared pieces two or more stories build on, each one reading of one thing.

### The pins, first, on the pre-feature code

- [ ] T003 [P] [py] Lane G. Write `reviewer/tests/unit/test_recording_provider.py` (research R2.28, "One recording provider"):
  - `tests/support/recording_provider.RecordingProvider` records each `run()` input into one ordered log, **before** its scripted turn runs: the system prompt, and the tools and history encoded as the OpenAI adapter encodes them. A turn that raises has still contributed its input.
  - `for_presentation(max_output_tokens)` returns a provider that records each presentation request into the same log in the same way, marked as a presentation.
  - Two runs of one script give equal logs.

  Acceptance: red for want of the module.
- [ ] T004 [py] Lane G. Move `RecordingProvider` from `reviewer/tests/unit/test_prefix_stability.py:113-156` to `reviewer/tests/support/recording_provider.py`, and add `for_presentation`. **Moved**: `test_prefix_stability.py` now imports it; only its import line changes, every assertion is unedited. The six other recorders research R2.28 names stay where they are: `test_cli.py:109`, `test_gate_standards_in_review.py:385`, `test_tool_tiers.py:271` and the three `SpyProvider`s. 015 adds no other recorder. Acceptance: T003 green; `test_prefix_stability.py` green.
- [ ] T005 [P] [py] Lane G. Write `reviewer/tests/unit/test_questions_package.py` for the fictional questions package (research R2.25, R4.1). `tests/support/questions_package.py` builds a package, graded with fictional profile A at version 3 as `tests/support/roles_review.py` writes it, such that:
  - A checks-first review under the pane defaults raises two questions, both `source: "code"`: the part-roles question (an unclear part, the `convention_only` state), and one drawing-candidate question (a part with a same-name drawing that is not open).
  - The seat is a `ScriptedReviewBridge` (`tests/support/review_bridge.py`) that reads drawings: `drawing_read: "opens_closed"`.
  - "All bought" withdraws at least one **named** finding of the unclear part (a hygiene finding), besides the folded RMS findings the digest counts and never names (`PrerunResult._finding_lines`, `prerun.py:582-598`).
  - Building twice gives byte-identical packages.
  - Every path is under `C:\Fictional\` and every name is `FICT-`. The owner's denylist scan runs through `tests/support/fixture_denylist.py`, skipped (naming the file) where the denylist is absent.

  Acceptance: red for want of the module.
- [ ] T006 [py] Lane G. Implement `reviewer/tests/support/questions_package.py` over existing builders, imported, never copied (DRY): `tests/support/roles_review.py`'s profile and package builders, `tests/support/drawings.py`'s candidate rows and `tests/support/review_bridge.ScriptedReviewBridge`. Extend `roles_review.py` (lane B's helper, in this task) only if its unclear part raises no named finding for the answer to withdraw, keeping `test_answer_batch_roles.py` and `test_runner_part_roles.py` green and unedited. Acceptance: T005 green.
- [ ] T007 [py] Lane G. **The characterization of a ticked review, on the pre-feature code** (research R2.28 item 1; FR-035, SC-003). Write `reviewer/tests/unit/test_ticked_review_golden.py` and commit its golden under `reviewer/tests/unit/test_ticked_review_golden/` (`pytest-regressions`, `reviewer/pyproject.toml:36`).
  - **The run**: a ticked `POST /sessions` (no `send_when_checked` in the body) on T006's package and seat, through `test_chat_server.py`'s `app` and `client` fixtures, imported as `test_chat_timing_route.py` imports them. T004's `RecordingProvider` is scripted to play, in order: the opening turn; one answer to the part-roles question that resumes the model (the path `_apply_answers` will hold, with `REGRADED_LINE`); one follow-up; and the explanation pass after each turn that ends `end`.
  - **The golden** holds every `run()` and presentation input, in order; `events.jsonl`; and `session.json`, `report.md` and `attention.json`. Times, durations and UUIDs are replaced by placeholders numbered in order of first appearance.
  - **The scenario** is one function, `play_ticked_review`, in this test module, returning the run folder before anything is normalized. T011 imports it (DRY), as `test_chat_timing_route.py` imports `test_chat_server.py`'s fixtures.
  - **When**: written and committed green **before any task below edits `reviewer/src/`**.

  Acceptance: green on the pre-feature code, and byte-equal on a second run. From here on every commit keeps it byte-equal, and no task in this list regenerates it; only the 014 merge may (T108).
- [ ] T008 [P] [py] Lane G. **The prefix characterization, before `_prefix` moves** (research R2.28 item 2, R2.9; `contracts/estimate.md` section 7). Write `reviewer/tests/unit/test_request_prefix_characterization.py` (`data_regression`) and commit its values under `reviewer/tests/unit/test_request_prefix_characterization/`. For each committed replay fixture (`reviewer/tests/fixtures/replay/{big-assembly,small-assembly-a,small-assembly-b}/`) under the pane defaults, it records the sha256 and the length of the first pass's `PlayedReview.prefix` (`benchmark/replay.py:244`, filled from `_prefix(run)` at `:368`). Committed green on the pre-feature code. Acceptance: green on the pre-feature code and byte-equal on a second run. T022's move keeps it green, unedited.

**Checkpoint (the pins)**: T007 and T008 are committed on the pre-feature code, and nothing in `reviewer/src/` has changed.

### The shared pieces

- [ ] T009 [P] [py] Lane R. **Only while feature 014 is not on `main`** (research R3, the add/add row; `contracts/records.md` section 8). Write `reviewer/tests/unit/test_atomic.py` with the exact content of branch `014-design-review-eval`'s file of that name. Its eleven tests cover: the bytes as given, with `\n` kept; nothing translated; an empty file; a whole replace; the temporary in the target's folder, named `.{name}.<random>.tmp`; no debris after a success; a failed replace keeping the old bytes and removing the temporary; a clean-up failure never hiding the error; a failed replace over no file; a failed write; and a missing folder, not made. When 014 is on `main` first, skip T009 and T010 and import its `swreview.atomic`. Acceptance: red for want of `swreview.atomic`.
- [ ] T010 [py] Lane R. Add `reviewer/src/swreview/atomic.py`, copied whole from 014: its exact name, signature and body, `write_atomic(path: Path, data: bytes) -> None`. The 014 merge keeps one copy. Acceptance: T009 green; T007 byte-equal.
- [ ] T011 [P] [py] Lane R. Write `reviewer/tests/unit/test_session_fields_015.py` (data-model section 4; `contracts/records.md` sections 1 and 8; FR-032, FR-036). It pins:
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
  - **The write**: `save_session` writes through `atomic.write_atomic` with the bytes unchanged. With `os.replace` patched to raise through `swreview.atomic.os`, the previous `session.json` stays whole.

  Acceptance: red for want of the fields.
- [ ] T012 [py] Lane R. Add `ModelStatus`, `SendFailure`, `SendEstimate`, `LiveDetectionRecord`, `DrawingOutcome` and the three `ReviewSession` fields to `report/session.py`. Each is dropped by the serializer at its default, following the pattern of `_omit_empty_finding_explanations` (`report/session.py:582-608`). Also:
  - Make `save_session` (`:650-655`) write through `atomic.write_atomic`.
  - Add `LiveOutcome.as_record` and `from_record` to `prerun.py` (`:461`). These are two methods in lane B's file, added in this task, before lane B starts.
  - In the same commit, edit `specs/001-agentic-design-review/contracts/review-session.schema.json` with `contracts/records.md` section 1's five `$defs` and three properties, none in `required`. `test_session_fields_013.py::test_the_contract_names_exactly_the_sessions_fields` reads both the model and the schema, so they must land together.

  **Amends 001** `review-session.schema.json` and `contracts/README.md`. Acceptance: T011 green; `test_session.py`, `test_session_fields_013.py` and `test_schema_sync.py` green and unedited; T007 byte-equal.
- [ ] T013 [P] [py] Lane B. Start `reviewer/tests/unit/test_runner_send.py` with `agent/events.local_now()` (research R2.15, R2.25). It returns an aware `datetime`, equal to `datetime.now(UTC).astimezone()` to the second and carrying the machine's UTC offset. Every caller reads it through the module, so one `monkeypatch.setattr(events, "local_now", ...)` pins every model-status time. Acceptance: red for want of the name.
- [ ] T014 [py] Lane B. Add `local_now()` beside `utc_now()` in `agent/events.py` (`:67`). Acceptance: T013 green.
- [ ] T015 [P] [py] Lane B. Extend `reviewer/tests/unit/test_chat_sessions.py` (`contracts/review-flow.md` section 2; data-model section 2):
  - `ChatState.AWAITING_SEND == "awaiting_send"`.
  - Four moves are allowed: `extracting -> awaiting_send`, `awaiting_send -> running`, `running -> awaiting_send` and `awaiting_send -> failed`. Every other move out of `awaiting_send` raises `InvalidTransitionError`.
  - `finished` is false in `awaiting_send`, so a waiting chat holds its folder.
  - `public()` reports the state.

  **Moved, red by design and edited deliberately here** (research R4.3): `test_every_state_can_fail` (a path through `awaiting_send` joins its parameters) and `test_a_transition_the_table_does_not_name_raises` (its refused moves gain those of `awaiting_send`). `test_failed_is_terminal` iterates `ChatState` and passes unedited. Acceptance: red for want of the state.
- [ ] T016 [py] Lane B. Add `AWAITING_SEND` and its four moves to `chat/sessions.py` (`ChatState`, `TRANSITIONS`, `:68-90`). **Amends 002** `data-model.md` section 3 (the state table). Acceptance: T015 green; T007 byte-equal.
- [ ] T017 [P] [py] Lane B. Write `reviewer/tests/unit/test_deferred_provider.py` (`contracts/review-flow.md` section 8; research R2.5):
  - For OpenAI, Gemini and the scripted provider, at every effort level and for a model with no table row, `DeferredProvider.for_settings(settings)` has the real adapter's `name`, `model` and `effort_mapping(effort)`.
  - An effort the model refuses raises the adapter's own error. `start_steps_at` is accepted.
  - `run` and `for_presentation` raise `ProviderNotSent`.
  - Building one reads no key and imports no SDK: a subprocess import of `swreview.agent.providers.deferred` leaves `openai` and `google.genai` out of `sys.modules`.
  - It is not `ModelViewAware`, `PromptCacheAware` or `PriorReasoningAware`.
  - Each adapter's `effort_mapping` method returns exactly its module's `effort_mapping_for(model, effort)`.

  Acceptance: red for want of the module.
- [ ] T018 [py] Lane B. Add `effort_mapping_for(model, effort)` to three provider modules, each adapter method becoming a one-line delegation: `agent/providers/openai_provider.py` (`:389-407`), `gemini_provider.py` (`:382-406`) and `fake.py` (`:254-256`). Create `agent/providers/deferred.py` (`ProviderNotSent`, and `DeferredProvider` with `for_settings`). Acceptance: T017 green; `test_runner_provider.py` and every provider test green and unedited; T007 byte-equal.
- [ ] T019 [py] Lane B. Extend `reviewer/tests/unit/test_runner_send.py` with `configure_provider(provider, session)` (`contracts/review-flow.md` section 8). In this order, it calls:
  - `use_model_view(session.model_view)`, on a `ModelViewAware` provider;
  - `use_prompt_cache(str(session.session_id))`, when lever 3 is on and the provider is `PromptCacheAware`;
  - `drop_prior_reasoning()`, when lever 14 is on and the provider is `PriorReasoningAware`.

  It calls nothing on a `DeferredProvider`. `start_review` makes exactly the hook calls it made before, checked against a spy provider's call log under each lever setting. Acceptance: red for want of the name.
- [ ] T020 [py] Lane B. Extract `configure_provider` from `start_review`'s three hooks (`agent/runner.py:1622-1646`) and call it there. Acceptance: T019 green; `test_runner_provider.py` green and unedited; T007 byte-equal.
- [ ] T021 [P] [py] Lane B. Start `reviewer/tests/unit/test_send_estimate.py`. `agent.runner.request_prefix(system, tools, opening)` exists, and `benchmark.replay._prefix(run)` returns it called as `request_prefix(run.system, run.tools, run.opening_message)` (checked with a spy). The bytes are proven by T008's characterization: never by comparing the function with the code that now calls it, and never by `test_replay_fixtures.py`'s totals, which read no prefix (research R2.9; `contracts/estimate.md` section 7). Acceptance: red for want of the name.
- [ ] T022 [py] Lane B. Move `_prefix`'s body (`benchmark/replay.py:350-361`) into `agent/runner.request_prefix`, with `_prefix` calling it (one function body in lane R's file, in this task). One commit, made after T008 is committed. Acceptance: T021 green; T008 green and **unedited** (the move is byte for byte); `test_replay_fixtures.py` green and unedited; T007 byte-equal.
- [ ] T023 [P] [py] Lane B. Write `reviewer/tests/unit/test_questions_identity.py` (`contracts/recheck.md` section 4 step 1; research R2.17). `checks/questions.asks_same(earlier, new)` is true exactly when `question`, `options` and `entity_ids` are equal, in order. Every case that `part_roles.answered_roles` and `drawings._is_confirmed_candidate` decide today gives the same answer when driven through `asks_same`. Acceptance: red for want of the name.
- [ ] T024 [py] Lane B. Add `asks_same` to `checks/questions.py`, and make `answered_roles` (`checks/part_roles.py:902-917`) and `_is_confirmed_candidate` (`tools/drawings.py:248-258`) call it. No behaviour change; this is the third use of the rule, so Principle V makes the extraction due. Acceptance: T023 green; `test_part_roles.py`, `test_confirmed_drawing_read.py` and `test_answer_batch_roles.py` green and unedited; T007 byte-equal.
- [ ] T025 [P] [py] Lane B. Start `reviewer/tests/unit/test_send_gate_server.py`, importing `test_chat_server.py`'s fixtures and helpers as `test_chat_timing_route.py` does (`contracts/review-flow.md` section 1 step 4; research R2.6). For the same ticked chat, `ChatServer._render_run(run, report_path, run_dir)` writes `report.md` and `attention.json` byte-identical to what `_render_report(chat)` wrote. A ranking or a write that raises is logged and never raises. Acceptance: red for want of the name.
- [ ] T026 [py] Lane B. Extract `_render_run` from `_render_report` (`chat/server.py:2259-2281`). `_render_report` still returns at once while `chat.run` is `None`, and otherwise calls it. Acceptance: T025 green; T007 byte-equal.
- [ ] T027 [P] [py] Lane R. Extend `reviewer/tests/unit/test_review_words.py` and `test_pane_fixture.py` (`contracts/words.md` section 1; research R2.22, R2.25):
  - **The `send` block** of the words file holds exactly `first_request`, `first_request_approximate`, `without`, `restored`, `failed`, `not_started`, `apply_answers`, `restored_line` and `rerun_failed`. Each sentence and its placeholders are as `words.md` section 1 fixes them (`{tokens}`; `{reason}` and `{time}`; `{when}`). The block is read by `SendWords` (`Words.send`), and a missing or misspelt key refuses the file.
  - **The labels**: `labels.errors` gains `NoCredential`, `NotSent`, `NotWaiting`, `ReviewNotActive` and `SettingNotSaved`, with `words.md`'s sentences.
  - **The pane fixture**: its labels block equals `load_words().labels` (`test_pane_fixture.py:73`), and its snapshot part (every key but `labels`) is byte-identical to the committed one.

  **Moved, red by design**: whatever `test_review_words.py` pins of the file's block list gains `send`. `test_pane_fixture.py`'s fresh-generation check (`:49`) fails until the fixture is regenerated, which T028 does in the same commit. Acceptance: red for want of the block.
- [ ] T028 [py] Lane R. Add the `send:` block and the five `labels.errors` keys to `report/review_words_v1.yaml`, and `SendWords` to `report/summary.py`'s `Words`. **In the same commit** (lane G's file, in this task), regenerate `extractor/SwReview.AddIn.Tests/Fixtures/review-big-assembly.json` with `uv run python tests/fixtures/pane/generate_pane_fixture.py --write`, so every commit passes the gate. The commit's review confirms the fixture's diff is the five added label keys only (FR-035). No later task changes the words file. Acceptance: T027 green; `ErrorLabelsCoverTheHostTests.EveryClassTheReviewTabCanShowHasASentenceInTheWordsFile` green; every page test green; T007 byte-equal.
- [ ] T029 [P] [C#] Lane H. Extend `extractor/SwReview.AddIn.Tests/UserSettingsTests.cs` (`contracts/pane.md` section 1; data-model section 1; FR-002, FR-036):
  - A file without `send_when_checked`, or with JSON `null`, a string or a number for it, reads ticked (`SendsWhenChecked` true).
  - The string and the number each add exactly one load problem, "send_when_checked '{token}' is not true or false; ticked is in use.". The provider, model, run root and stored key still load as today, and the next save drops the bad token.
  - `false` round-trips. A file written before this feature saves to its own bytes. `Clone` keeps the held token.
  - The settings schema validates a file with `true`, with `false` and without the key, and refuses a string.

  **Moved**: `RoundTripsEveryFieldThroughATempFileAndSatisfiesTheContract` is edited deliberately so the new field round-trips. Acceptance: red for want of the property.
- [ ] T030 [C#] Lane H. In `extractor/SwReview.AddIn/Settings/UserSettings.cs`, add:
  - `[JsonPropertyName("send_when_checked")] JsonElement? SendWhenCheckedValue`, held raw, written back as held, and omitted while none is held;
  - `[JsonIgnore] bool? SendWhenChecked`, derived from it; its setter stores a boolean, and `null` clears it;
  - `SendsWhenChecked => SendWhenChecked != false`;
  - `Normalize`'s one load problem, and its clearing of a bad token (`UserSettings.cs:400-445`).

  Add `pane.md` section 1's property to `specs/002-task-pane-assistant/contracts/settings.schema.json`, not in `required`, with a description that names no lever. **Amends 002** `settings.schema.json` and `data-model.md` section 4. Acceptance: T029 green; `reviewer/tests/unit/test_no_lever_in_pane_settings.py` green and **unedited** (FR-004); zero warnings.
- [ ] T031 [py] Lane G. **Foundational gate**. Run the gate's commands (quickstart, "The gate"), then research R2.28's replay regeneration step, since a provider and the records moved: 008 `contracts/replay.md` section 8's three generator commands, then `git diff --exit-code -- reviewer/tests/fixtures/replay`. Skip the step where the owner's recordings mapping is absent, and record why. Nothing is committed: a difference is a defect of the task that caused it, never a fixture to regenerate. T109 records the outcome in `specs/015-review-send-gate/quickstart.md`'s Results.

**Checkpoint**: the pins hold. In place: one atomic writer, the session fields, one clock, one new state, one deferred provider, one provider setup, one prefix, one question identity, one render, the words and the setting.

---

## Phase 3: User Story 1 - Review Without Sending Anything to the Model (Priority: P1) 🎯 MVP

**Goal**: with the box unticked, Review runs every code check, saves a whole checks-only review, and waits, with no provider set up, no key needed and nothing sent. The page shows the box, the waiting status, no Stop, the follow-up box off and the Send block's sentence.

**Independent Test**: spec.md User Story 1; quickstart Scenarios 1 and 5, and Scenario 6's US1 cases.

### The backend

- [ ] T032 [P] [US1] [py] Lane B. Extend `reviewer/tests/unit/test_runner_send.py` and `test_events_schema.py` (`contracts/review-flow.md` sections 1 and 7; `contracts/records.md` sections 1 to 3; FR-006, FR-009 to FR-011, FR-037).
  - **The checks only**: `start_review(..., send_when_checked=False)` with a `DeferredProvider` on T006's package runs exactly what a ticked review runs before its first request: the part roles and their question, the checks-first pre-run, and the drawing questions. Its findings, questions and coverage equal a ticked review's at that review's first `run()`, read from T004's recorder. It makes no provider call.
  - **What it records**:
    - It emits `session.started` with `send_when_checked: false`.
    - It records `model_status {state: "not_sent", document, profile}`. `document` comes from `report/snapshot.root_document` (made public, research R2.15). `profile` is the identity `{path, sha256}` of the Standards profile it graded with (`ProfileIdentity`, `checks/standards/profile.py:183-188`), omitted when there is none.
    - When the pre-run ran, it records `live_detection` (`LiveOutcome.as_record()`).
    - The run keeps `_prerun` and `_standards_gap`.
  - **The defaults**: `earlier` with `send_when_checked=True` raises `ValueError`. With neither argument, `start_review` and `run_review` are today's, so the command-line review gains nothing (FR-037; T007 byte-equal).
  - **The command-line review's output** (FR-037; `cli.py:758-780`; T007 drives `POST /sessions` and never the command). `swreview review` runs on the shared `tmp_package_dir` (`tests/conftest.py:146`) with `test_cli.py`'s fake provider, through its `invoke` (`:227`) and `fake_provider` (`:163`), imported as `test_chat_timing_route.py` imports `test_chat_server.py`'s fixtures. Asserted:
    - It prints exactly today's four lines, each as a literal with the values read from the session it wrote: `reviewed {design_id} with {provider} {model}`, `{n} findings, {n} evidence requests, {n} tool calls`, `session: {path}` and `report: {path}`.
    - Its `--json` payload has exactly today's ten keys.
    - `review --help` names no option containing `send` or `recheck`.

    This case is a pin: it is green on the code before T033 and stays green at every later commit. `test_cli.py` itself is not edited.
  - **The finalization of a session not sent**:
    - Each open model-owned checklist item reads `NOT_SENT_ITEM`. One left open after its blocking question was answered keeps 013's `ANSWERED_BUT_OPEN` and adds `NOT_SENT_SUFFIX`.
    - A code-owned item closes by code as today, and nothing is marked checked.
    - No `turn.ended` is written.
    - `checked_at` is stamped by `local_now` at the finalization's end, and `unattended_runtime_minutes` is `checked_at - started_at`, so a patched clock that waits an hour adds nothing.
  - **`test_events_schema.py` rows**: an unticked `session.started` with `send_when_checked: false` validates; one with `true` is refused (`const`); a ticked one without the key validates as today; any other new key is still refused.

  Acceptance: red for want of the arguments.
- [ ] T033 [US1] [py] Lane B. Implement in `agent/runner.py`:
  - `start_review(..., send_when_checked: bool = True, earlier: ReviewSession | None = None)` (`:1497`). `earlier` is accepted but refused with `True`, and is carried from T085.
  - `ReviewRun.awaiting_send`, `_prerun` and `_standards_gap`, the model-status and live-detection writes, and the event field.
  - `NOT_SENT_ITEM`, `NOT_SENT_SUFFIX` and the running time in `finalize_session` (`:597-678`).

  Also rename `report/snapshot._root_document` to `root_document` (`:79`; one name in lane R's file, in this task). Add the field inside the `session.started` branch's `body.properties` in `specs/002-task-pane-assistant/contracts/chat-events.schema.json` (`review-flow.md` section 7's JSON, not in `required`). **Amends 002** `chat-events.schema.json`; **008** `contracts/checks-first.md` section 1 (unticked: no provider is set up, and no first request follows the pre-run). Acceptance: T032 green; T007 byte-equal.
- [ ] T034 [US1] [py] Lane B. Extend `reviewer/tests/unit/test_runner_send.py` and `test_send_estimate.py` with the Send cache (`contracts/review-flow.md` section 5; `contracts/estimate.md` sections 1 to 4; data-model sections 3 and 7; FR-012, FR-013):
  - **The cache**: `build_send_cache()` sets `_send_cache` `{opening, estimate, named_ids}` in one assignment.
  - **The opening**: with nothing applied, it **is** the frozen `opening_message`, byte for byte. It also equals the opening built again after the finalization (the order pin, research R2.8).
  - **The named ids**: `named_ids` is `PrerunResult.named_finding_ids()`, the ids the digest's lines name, in order, from the loop `_finding_lines` renders, under `DIGEST_ID_CAP`. A folded family names none.
  - **The estimate** is `SendEstimate {input_tokens: count_tokens(request_prefix(system, tools, opening)), encoding: "o200k_base", approximate: provider == "gemini"}`, where `self.tools` is the offered tools less what lever 13 withheld. `input_tokens` is `None`, never zero, when `tokens.encoding` is patched to raise `TokenizerUnavailable` (the precedent is `test_step_sizes.py:166-171`; the vocabulary is cached per process, so an empty `SWREVIEW_TOKENIZER_DIR` would not take effect).

  Acceptance: red for want of the cache.
- [ ] T035 [US1] [py] Lane B. Implement `SendCache`, `ReviewRun.build_send_cache()`, `opening_at_send()` and `first_request_estimate()` in `agent/runner.py`. `opening_at_send()` has only its frozen branch here; T078 adds the rebuilt one. Add `PrerunResult.named_finding_ids()` in `prerun.py` (`:522`, beside `_finding_lines`). Acceptance: T034 green; T007 byte-equal.
- [ ] T036 [P] [US1] [py] Lane R. Write `reviewer/tests/unit/test_report_model_status.py` (`contracts/records.md` section 4; FR-032, SC-009). The header reads, by model status:
  - `not_sent`: "- Model: not sent to the model (checked by code only)", and no Provider line.
  - `send_failed`: "- Model: not sent to the model; the last attempt failed at {at}: {reason}".
  - `sent`: today's Model and Provider lines, then "- Sent to the model: {sent_at} (checks finished {checked_at})", and, when there were failed attempts, "- Earlier attempts that failed: {n}".
  - `rechecked_from` adds "- Checked again from session: {id}" beside today's "- Retry of session:".
  - Every time prints as its stored wall clock: a `+05:30` time prints its own clock whatever the test's zone (research R2.15).
  - A session with no `model_status` renders today's header (T007's `report.md` byte-equal).

  Acceptance: red for want of the lines.
- [ ] T037 [US1] [py] Lane R. Implement the model-status lines in `_render_title` (`report/markdown.py:146-180`). It lands before the unticked start (T038-T039), whose test reads this header in the `report.md` on disk at the 201, so that commit holds no red test. Acceptance: T036 green; every `.md` golden and T007 byte-equal.
- [ ] T038 [P] [US1] [py] Lane B. Extend `reviewer/tests/unit/test_send_gate_server.py` with the unticked start (`contracts/review-flow.md` sections 1, 2, 4 and 9; FR-006 to FR-010, FR-019, FR-025, FR-035; SC-001, SC-002). Every case asserts `ProviderControl.built == []`.
  - **The start**: with no key in settings or the environment, `POST /sessions` with `send_when_checked: false` answers `201 {chat_id, review_session_id, not_examined}`, with the chat `awaiting_send`.
  - **What is on disk when the 201 arrives**:
    - `events.jsonl` ends at `session.ended`, with no `turn.started` or `turn.ended`.
    - `session.json` says `not_sent`.
    - `report.md` is on disk, reading T037's "- Model: not sent to the model (checked by code only)".
    - The coverage is a ticked review's at its first request, plus exactly: the close-out row, one unresolved row per open question, and one "not reviewed, because the review was not sent to the model" row per open model-owned item (SC-002).
  - **Refusals and failures**:
    - A `send_when_checked` that is not a boolean is `400 InvalidRequest`, naming the field.
    - A ticked start with no key is still `502 ProviderFailed`, before any check (FR-035).
    - An unticked start on an unreadable package answers `InvalidPackage` as today, and registers no chat.
    - A cache build or a finalization that raises (`write_atomic` patched to raise) answers the error body any unexpected failure answers, registers no chat, and leaves the folder free (a following claim meets no `RunDirInUse`).
  - **While it waits**:
    - `POST /messages` is `409 NotSent`.
    - `POST /stop` writes no event, leaves the chat `awaiting_send`, and leaves `chat.stop_requested` unset.
    - A graceful shutdown writes nothing for it.
    - Two reviews waiting at once each keep their own state.

  Acceptance: red for want of the field.
- [ ] T039 [US1] [py] Lane B. Implement the unticked branch of `create_session` (`chat/server.py:1230-1262`), in this order:
  1. `_start_review` (`:2111-2114`) builds `DeferredProvider.for_settings(...)` in place of the factory when `send_when_checked` is false.
  2. On the thread pool, before the chat is attached and registered: `build_send_cache()`, `finalize()`, and `_render_run(run, chat.report_path, chat.run_dir)`. A raise moves the unregistered chat `extracting -> failed` and answers the error body.
  3. Attach, register, move `extracting -> awaiting_send`, and answer 201.

  Also validate the body's `send_when_checked`, and add `NotSent` (409), refusing `POST /messages` while `run.awaiting_send`. **Amends 002** `contracts/chat-api.md` (the `POST /sessions` field; "starts the review turn immediately" holds only with the box ticked; `POST /messages`' `NotSent`) and spec FR-006. Acceptance: T038 green; T025 and T036 green; T007 byte-equal.
- [ ] T040 [P] [US1] [py] Lane R. Write `reviewer/tests/unit/test_send_block.py` (data-model section 6; `contracts/pane.md` section 3; `contracts/words.md` section 1; `contracts/estimate.md` section 3; FR-012, FR-034).
  - `review_ranking(session, package, *, usage=None, send=None)` omits `summary.send` when `send` is `None`, keeping the pane fixture's bytes (`test_pane_fixture.py` green and unedited).
  - From `send_input` `{state, input_tokens, provider, send_error}` it builds `SendBlock {state, session_id, input_tokens, approximate, text, failure, restored_text, rerun_failed_text}`.
  - **`waiting`**:
    - With a count, it prints `send.first_request`, with `{tokens}` written as `13,151`.
    - With `None`, it prints `send.without` and no number.
    - With Gemini, it prints `send.first_request_approximate` and sets `approximate: true`. The scripted provider is counted and not approximate.
  - **`failure`**: from `send_error` (`send.not_started`), else from the last recorded failed request of a `send_failed` record (`send.failed`). `{time}` is the stored wall clock's `HH:MM`.
  - **`restored`**: prints `send.restored`. `restored_text` is `send.restored_line`, with `{when}` the stored `checked_at` as `YYYY-MM-DD HH:MM`, never converted (research R2.15). `rerun_failed_text` is set.
  - `session_id` is the session's.
  - `resume_text` is `send.apply_answers` while a `send` block is present, else today's.
  - Every sentence comes from the words file.

  Acceptance: red for want of the block.
- [ ] T041 [US1] [py] Lane R. Implement `SendBlock`, `ReviewSummary.send` (omitted when `None`), `review_ranking(send=)` and `resume_text` while waiting, in `report/summary.py`. **Amends**:
  - **009** `contracts/review-summary.md` section 1 (the `send` block) and `contracts/views.md` section 2 (the Send block's count, a second exception to "Results shows no token count");
  - **008** `contracts/cost.md` (a new surface, the Send sentence) and `contracts/tokenizer.md` section 1 (the pane sentence names no encoding, and a Gemini figure is called approximate).

  Acceptance: T040 green; `test_pane_fixture.py` green and unedited.
- [ ] T042 [US1] [py] Lane B. Extend `reviewer/tests/unit/test_send_gate_server.py` (`contracts/estimate.md` section 2; research R2.8):
  - For a waiting chat, `GET /sessions/{id}/attention` and the snapshot answer `summary.send {state: "waiting", input_tokens: <the cache's count>, ...}` and `chat_state: "awaiting_send"`.
  - With `_opening_message` and `count_tokens` patched to raise once the cache exists, both routes still answer `200` with the cached figure: no route builds an opening or counts a token.
  - A ticked chat's answers carry no `send`.

  Acceptance: red for want of the block on the routes.
- [ ] T043 [US1] [py] Lane B. Add `ReviewRun.send_input()`, which reads `_send_cache` and `_send_error` and computes nothing, and pass it from the attention and snapshot routes while `run.awaiting_send` (`chat/server.py:1267-1318`). Acceptance: T042 green; T007 byte-equal.

### The host

- [ ] T044 [P] [US1] [C#] Lane H. Extend `extractor/SwReview.AddIn.Tests/PageMessageTests.cs` (`contracts/pane.md` sections 1 and 12; FR-002, FR-027):
  - The `init` and `settings` views carry `send_when_checked` (true when unset).
  - `send_when_checked.save {send_when_checked: false}`:
    - writes the file and answers `send_when_checked.saved {send_when_checked: false}`;
    - leaves `Backend.Restarts` unchanged, and keeps every other field;
    - is accepted while the fake backend reports a turn `running`.
  - A missing or non-boolean value is `InvalidRequest`. A write that fails is `SettingNotSaved`, and the stored value stands.
  - `settings.save` keeps the value. It is accepted while the fake backend reports the review's chat `awaiting_send`, and refused while it reports `running` (`BackendClient.cs:118-122`).

  **Moved**: `ReadyIsAnsweredWithInitCarryingTheBackendOriginAndNoKey` asserts the view's new key (additive). `ErrorLabelsCoverTheHostTests.TheScanFindsTheClassesTheHostAndThePageMake`'s expected list gains `SettingNotSaved`. Acceptance: red for want of the message.
- [ ] T045 [US1] [C#] Lane H. Implement the view's key (`ReviewHost.View`) and `send_when_checked.save` in `extractor/SwReview.AddIn/Review/ReviewHost.cs`: clone the settings, set the value, `UserSettings.Save`, replace; no restart and no turn check. Add `PagePayload.Flag` in `Review/PaneActions.cs`. **Amends 002** `contracts/pane-host-messages.md` (the `ready`/`init`, `settings.save` and `settings.get` replies carry the value), and `contracts/chat-api.md`'s "Shutdown and settings changes" (`review-flow.md` section 2: a save is accepted while a review waits, since `awaiting_send` is not a running turn, and refused while the chat is `running`, which an apply, a Send and a re-run each are). **The new row `send_when_checked.save` waits for T051**: a Review page row lands in the commit where the page first posts it, because `ReviewPageContractTests.EveryPageToHostRowIsExercisedByThePage` (`:81-99`) fails on a row the page does not post, and `EveryTypeThePageSendsIsARowOfTheContract` (`:55-76`) on a type it posts with no row. No host test parses the Review rows. Acceptance: T044 green; zero warnings.
- [ ] T046 [P] [US1] [C#] Lane H. Extend `extractor/SwReview.AddIn.Tests/ReviewHostTests.cs`, and write `BackendClientSessionBodyTests.cs` with an in-process `HttpListener` on 127.0.0.1, as `RemodelBackendClientTests.cs` uses (`contracts/pane.md` section 2; `contracts/review-flow.md` section 1, "The host's timeout"; FR-002, FR-003).
  - **The host**:
    - `review.start` passes the value stored when it is handled, as `NewSessionRequest.SendWhenChecked`.
    - `review.started` carries `send_when_checked`.
    - Unticked, the ready status reads "Checked {n} components by code; nothing was sent to the model.".
  - **Message order**:
    - After a `review.start` then a box change, the start passes the old value and the change is written after it.
    - A Retry after a box change passes the new value.
    - A `CreateSession` that times out on an unticked start is today's failure, and keeps no record.
  - **The client**:
    - The body always carries `send_when_checked` and `recheck`.
    - `BackendClient.TimeoutFor(request)` is 10 minutes whenever `SendWhenChecked` is false, and the 30 s `CallTimeout` for a ticked start and every other call. It is checked directly, with no waiting.

  **Moved**:
  - The `review.start` test that asserts every `NewSessionRequest` field (`ReviewHostTests.cs:322-370`), and `FakeBackend.CreateSession` (`:2123`), gain `SendWhenChecked` and `Recheck`.
  - `ReviewPageContractTests.TheReviewStartRowsReplyNamesTheDocumentItReviewed` (`:178-186`; one string in lane W's file, in this task) asserts "review.started {chat_id, run_dir, not_examined, document, send_when_checked}".

  Acceptance: red for want of the fields.
- [ ] T047 [US1] [C#] Lane H. Add `SendWhenChecked` (default `true`) and `Recheck` (default `false`) to `NewSessionRequest` in `Review/IBackendClient.cs`. Write both fields in `BackendClient.CreateSession`, and add `TimeoutFor` (`Review/BackendClient.cs:39`, `:131-150`, `:299-300`). In `ReviewHost.cs` (`:1295-1305`), pass the value, carry it in `review.started`, and set the ready status. **Amends 002** `contracts/pane-host-messages.md` (the `review.start` row and its reply). Acceptance: T046 green; the six `IBackendClient` fakes compile unchanged (research R4.2); zero warnings.

### The waiting fixtures

- [ ] T048 [P] [US1] [py] Lane G. Write `reviewer/tests/unit/test_pane_waiting_fixtures.py` (research R2.25; `contracts/pane.md` section 13), on the precedent of `test_pane_drawing_fixture.py`. Two files, `extractor/SwReview.AddIn.Tests/Fixtures/review-waiting.json` (from T006's package) and `review-waiting-big-assembly.json` (from the big-assembly replay fixture's package):
  - each equals a fresh generation byte for byte, the failure naming the `--write` command;
  - each holds a `waiting` snapshot (the live snapshot of an unticked review, its size sentence counted) and the words file's labels block;
  - every clock value in them is the pinned fictional time, and no provider was built.

  `review-waiting.json`'s `waiting` holds the part-roles question and a drawing-candidate question, both `source: "code"`. **Moved**: `test_replay_fixture_hygiene.py`'s list of committed fixtures gains both files (FR-039). Acceptance: red for want of the files.
- [ ] T049 [US1] [py] Lane G. Write `reviewer/tests/fixtures/pane/generate_waiting_fixtures.py` (run from `reviewer/` with `--write`), and commit the two files it writes. It pins every clock: the runner's `datetime` and `utc_now` as `test_finding_explanations.py:366` pins them, and `local_now`. It runs with the box unticked, and sets up no provider before a Send. Acceptance: T048 green; `test_replay_fixture_hygiene.py` green.

### The page

- [ ] T050 [US1] [page] Lane W. Write `extractor/SwReview.AddIn.Tests/ReviewPageSendGateTests.cs` (offscreen WebView2, `review-waiting.json`; `contracts/pane.md` sections 1 to 4, 6 and 8 to 10; FR-001 to FR-003, FR-019, FR-025 to FR-027, FR-033, FR-034; SC-001). As test infrastructure, make `ReviewPageDriver.cs` answer `send_when_checked.save` with `send_when_checked.saved`, with an error mode `SettingNotSaved`.
  - **The box**:
    - `label.check.send-when-checked` sits in `#session`, directly after the buttons' `.row`, set from `init`.
    - A change posts `send_when_checked.save` at once and keeps the new value shown.
    - A refused write puts the box back and prints the label in `#send-when-checked-note`, cleared at the next change.
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
    - Its chip carries " · not sent".
    - Review and Clear review keep the waiting chip, marked (FR-026).
    - After Review is pressed again, and after Clear review, choosing the waiting chip shows it waiting: the status line "Checked by code. Not sent to the model.", the Send block shown, no turn running and Stop off (FR-026, FR-033).
    - Zero proxy calls to `/send`, `/messages` or `/evidence` are made across Clear review, a document switch and Review again (SC-001).
  - **Around it**:
    - With the box unticked, "Before this review" still reads "No review tokens have been used.".
    - An unticked start refused `InvalidPackage` shows today's error card and Retry, and no Send block.
    - The Settings section's no-key note is `words.md` section 2's new sentence. While a review waits, the line "Saving restarts the backend. ..." shows under Save (FR-027).

  **Moved**:
  - `ReviewPageViewsTests.TheStatusLineReadsEachOfItsFourSentencesInItsState` (`:107-118`) gains the waiting row. It is renamed `TheStatusLineReadsEachOfItsSentencesInItsState`, without a count, so T098 adds its row without a second rename.
  - `ReviewPageDefaultViewScanTests.NoRawStatusOrBucketTokenIsVisible` (`:55-65`) adds `awaiting_send`, `not_sent` and `send_failed` to its token list (`:60`), and runs on `review-waiting.json` too.

  Acceptance: red for want of the box.
- [ ] T051 [US1] [page] Lane W. Implement in `extractor/SwReview.AddIn/Review/ReviewPage/`:
  - `index.html`: the box and its note in `#session`, after the `.row`; and `<section id="send" class="send-panel" aria-label="Send to model" hidden>` after `#summary`.
  - `app.css`: `.send-panel` and the box line, with tokens only.
  - `render.js`: `render.sendBlock(send, extras)`, setting text with `textContent` only.
  - `app.js`:
    - `state.notSent`, the box's message and its revert, and the waiting status-line state;
    - Stop and the follow-up box off while waiting (`app.js:1695-1704`, `:1864-1872`);
    - the Transcript lines and the chip mark;
    - the Settings lines and `describeKeySource('none')` (`:2484-2492`).

  The button is drawn here and posts nothing until T068. **Amends 002** `contracts/pane-host-messages.md`: the new row `send_when_checked.save`, with its reply `send_when_checked.saved`, in this commit, where the page first posts it (T045 says why). **Amends 009** `contracts/views.md` section 3 (the waiting state) and `contracts/sessions.md` section 5 (the chip mark). Acceptance: T050 green; `ReviewPageSummaryAcceptanceTests` and `ReviewPageNarrowLayoutTests` green and **unedited** with the box in place (research R2.21: about 21 px of 226 px); `PageRuleScanTests` green with no new allowlist entry; `ReviewPageInjectionTests.ThePageStylesheetNamesNoLiteralColour` green.
- [ ] T052 [US1] [page] Lane W. Write `extractor/SwReview.AddIn.Tests/ReviewPageSendLayoutTests.cs` on `review-waiting-big-assembly.json` (`contracts/pane.md` section 11; FR-005, SC-007). It is an acceptance test that passes with no further page code (009's precedent):
  - At 300 by 600 in `waiting`, the summary's headline, tally and not-reached line, and the Send to model button, are inside the viewport.
  - At 260, 300 and 420 px the session buttons wrap as today (two rows at 300 px), with the box directly under them.

  Record the measured slack in research R2.21. If SC-007 fails, the page work stops and the owner is asked (research R2.21, "The end state"); no page-only fallback is tried. Acceptance: green.
- [ ] T053 [US1] [py] Lane G. **US1 gate**: T031's commands (from `reviewer/`, and `extractor/SwReview.sln` from the root) and the replay regeneration step over `reviewer/tests/fixtures/replay` (the runner and the records moved). Nothing is committed; T109 records the outcome.

**Checkpoint**: an unticked review runs the checks, saves itself, and waits, with no provider and no key. The Review tab, the report and the Transcript each say so. The box is remembered, and changing it never restarts the backend.

---

## Phase 4: User Story 2 - Send the Review When Ready, Knowing Its Size (Priority: P2)

**Goal**: Send to model resumes the same review, with the counted size of its first request beside it. The first request is a ticked review's, byte for byte. A Send that fails, before or at its first request, leaves the review waiting with the reason beside Send.

**Independent Test**: spec.md User Story 2; quickstart Scenario 2, and Scenario 6's Send cases.

- [ ] T054 [P] [US2] [py] Lane B. Extend `reviewer/tests/unit/test_provider_settings.py` (`contracts/review-flow.md` section 3, order 5; FR-016). `ProviderSettings.has_credential` is:
  - true for a key from the settings, a key from the environment, the scripted provider, and Gemini with an enterprise project and no key;
  - false with no key anywhere and, for Gemini, no enterprise project.

  Acceptance: red for want of the property.
- [ ] T055 [US2] [py] Lane B. Add `has_credential` to `ProviderSettings` in `agent/settings.py` (`:194-215`), the one place the rule lives. Acceptance: T054 green.
- [ ] T056 [P] [US2] [py] Lane B. Extend `reviewer/tests/unit/test_send_gate_server.py` with the route (`contracts/review-flow.md` sections 2, 3 and 9; FR-016, FR-018).
  - **Refusals**: `POST /sessions/{id}/send` refuses, in this order and changing nothing, each leaving the chat `awaiting_send`:
    1. `404 UnknownChat`;
    2. `409 SessionFailed`;
    3. `409 TurnRunning`, for a Send already in flight;
    4. `409 NotWaiting`, for a ticked review or a sent one;
    5. `409 NoCredential`, with no key (never for an environment key, a Gemini enterprise project or the scripted provider);
    6. `502` with the provider's own class, when the factory raises.
  - **The build**: the adapter is built off the event loop, and a factory that records its thread never sees the loop's. The chat is already `running` while it builds, so a second Send, or an answer sent while a held factory builds, is `409 TurnRunning`. A factory that raises leaves `awaiting_send` and the `502`.
  - **A stop during the build** (FR-025; `contracts/review-flow.md` sections 3 and 4; research R2.12). With the factory held, `POST /stop` answers `202` and writes no event, although the chat reads `running`.
    - When the held factory then raises, the `502` leaves the chat `awaiting_send` with `chat.stop_requested` unset. A following Send, whose scripted first turn makes a tool call, runs to `end`: no `stopped` turn, and exactly one presentation request.
    - When the held factory instead returns, the Send is in flight and the stop is today's: the first turn ends `stopped` at its first tool call (default, research R2.12).
  - **The answer**: `202`, with the public view.

  **Moved**: `test_chat_server.py`'s `ROUTES` (`:279-296`) gains `POST /sessions/{chat}/send`, so its door tests (no token, wrong token, preflight) cover it. Acceptance: red for want of the route.
- [ ] T057 [US2] [py] Lane B. Add the route, `NotWaiting` and `NoCredential` (409) to `chat/server.py`:
  1. Checks 1 to 5 and the move `awaiting_send -> running` run on the loop, with no `await` between them.
  2. Then `await run_in_threadpool(self.provider_factory, settings)`, using the chat's `_settings({provider, model, effort})` (`:1996-2010`). If the build fails, clear `chat.stop_requested` and move back to `awaiting_send`, with no `await` between, before the `502`. The stop route sets the flag whenever the chat reads `running` (`:1497-1498`), and only `_play`'s `finally` clears it (`:2201`), so a failed build that kept it would stop the next Send's first turn at its first tool call (`StoppableTools`, `:2145`).
  3. Then `run.send(adapter)` on the chat's worker.

  `_play` settles `awaiting_send` while `run.awaiting_send` (`:2186-2208`). **Amends 002** `contracts/chat-api.md` (the Send row; `NotWaiting`, `NoCredential`). Acceptance: T056's refusal and build cases green. Its `202` case and its two stop cases each end in a Send that runs, which needs `run.send`; T060 adds it in the same commit (C29). So no commit holds a route that calls a method not yet written, and the `202` case is never green only because `_play` swallowed an `AttributeError`. T007 byte-equal.
- [ ] T058 [P] [US2] [py] Lane B. Extend `reviewer/tests/unit/test_runner_send.py` with `ReviewRun.send` (`contracts/review-flow.md` section 6; `contracts/records.md` sections 1 and 3; research R2.10, R2.11, R2.27; FR-011, FR-014, FR-032):
  - **The prepare half** changes nothing: the session is deep-equal, nothing changes on disk, and no event is written.
  - **The commit half**, in order:
    1. The pre-write: `send_failed` with the `Interrupted` entry (`INTERRUPTED_SEND`), saved.
    2. `session.sent`.
    3. The withdrawal of the previous finalization's rows, by identity. `_finalized` is empty after it, and rows anything else wrote (the part-roles row) are kept.
  - `attach_provider` numbers steps from the session's count.
  - **The first `usage`** sets `sent`, with `sent_at`, the estimate and `opening_finding_ids`; drops the `Interrupted` entry; and saves the session as it stands.
  - **Crashes**:
    - A crash simulated after the first `usage` leaves `session.json` `sent`, with `ended_at` null and no row of the checks' finalization. `GET /reviews` reads it read-only, as a sent review.
    - A crash simulated before the first `usage` leaves `send_failed`, with "the backend stopped before the model answered" (RK-7).
  - **Running time**: once sent, `unattended_runtime_minutes` is `(checked_at - started_at) + (ended_at - sent_at)`.

  Acceptance: red for want of `send`.
- [ ] T059 [US2] [py] Lane B. Extend `reviewer/tests/unit/test_send_gate_server.py` and `test_events_schema.py` with a Send that works (US2 scenarios 2, 3 and 6; FR-014, FR-015, FR-019; SC-004; research R2.14, R2.27).
  - **Byte-identical**: with nothing answered while waiting, **every** request of Send's first turn is byte-identical to a ticked review's of the same package, read from T004's recorder. The first turn is scripted to call `mark_coverage`, `request_evidence` and `get_review_checklist`, and the comparison includes the tool results.
  - **After the first turn**:
    - After a turn ending `end`, exactly one presentation request is made.
    - `POST /messages` is `202` after the first `usage`.
    - An answer to a question the model asked after Send resumes the model with today's `ANSWER_MESSAGE` and `REGRADED_LINE`, byte for byte against the same answer in a ticked review.
  - **Records**:
    - `session.sent` carries `{provider, model, effort_mapping, estimate}`.
    - The report adds "- Sent to the model: ...".
  - Two waiting reviews each send alone.
  - `test_events_schema.py`: `session.sent` validates.

  **Moved, red by design and edited deliberately here** (research R4.3): each goes red when T060 adds `session.sent` to the event-type enum.
  - `test_events_schema.py::test_a_full_run_emits_every_event_type_the_runner_and_tools_can_emit` now includes an unticked review sent after waiting, so `session.sent` and `send_when_checked` are emitted.
  - `test_gate_same_session.py::test_a_gated_run_emits_no_event_type_outside_the_sixteen` (`:201-214`) asserts `len(SCHEMA_EVENT_TYPES) == 16`. It becomes `test_a_gated_run_emits_no_event_type_outside_the_seventeen`, with the count 17 and a dated docstring line naming 015 T060 (`session.sent` is Send's record, not the gate's), as 011 T092 and 013 T038 each renamed it.
  - `test_provider_protocol.py::test_every_schema_event_type_has_a_case` (`:184-186`) needs `valid_bodies()` (`:112`) to cover the whole enum. `valid_bodies()` gains a `session.sent` body, `{provider, model, effort_mapping, estimate}`, as `review-flow.md` section 7 fixes it, so `test_agent_event_validates_against_the_contract` validates it too; the test itself is unedited.

  Acceptance: red for want of `send`.
- [ ] T060 [US2] [py] Lane B. Implement in `agent/runner.py`: `ReviewRun.attach_provider`; `send` with its prepare and commit halves, without the guard (T062 adds it); `_send_in_flight`; and the first-`usage` mark and its save in `_emit_turn_event` (`:1460-1473`). Add `"session.sent"` to `EventType` (`agent/providers/__init__.py`), and its branch to `specs/002-task-pane-assistant/contracts/chat-events.schema.json` (`review-flow.md` section 7's JSON; the `type` enum gains it). **Amends 002** `chat-events.schema.json`. Acceptance: T056 green, its `202` and stop cases included; T058 and T059 green, the three moved tests included; `test_provider_protocol.py::test_event_type_literal_matches_the_schema` green and unedited; T007 byte-equal.
- [ ] T061 [US2] [py] Lane B. Extend `test_runner_send.py` and `test_send_gate_server.py` with a Send that fails (`contracts/review-flow.md` section 6; FR-016, FR-017; research R2.10; RK-13).
  - **A first request that raises before any round** (the round count is read before `emit_turn_failed`):
    - The `Interrupted` entry is replaced with the provider's class and redacted reason.
    - The history is emptied, `awaiting_send` is set, and a `DeferredProvider` of the same settings is put back.
    - `error` and `turn.ended {error}` are written; the streamed text stays in the stream.
    - A second Send carries the opening once, and every request of its first turn is byte-identical to a ticked review's of the same package, tool results included (T059's comparison, with the same scripted first turn). The session at that first request holds no row of the finalization the failure ran (research R2.27, RK-11).
  - **A failure after a round** is today's: `failed`, with the error card.
  - **The box ticked** (the spec's edge case "A failed first request with the box ticked"; FR-035): a ticked review whose first request raises before any round ends as today. The chat is `failed`; `error`, `turn.ended {reason: "error"}` and `session.ended` are written; `session.json` has no `model_status`; and `POST /send` is `409 SessionFailed`, changing nothing. T007's golden pins only the success path, and T062 rewrites the except branch this path runs through (`runner.py:1434-1442`), so this case pins that a ticked failure never falls into `awaiting_send`. It passes before T062.
  - **The guard, at five points**: `configure_provider` raising; the effort mapping raising; the pre-write's `save_session` raising; the `session.sent` emit raising; and the undo save raising after a failed emit. At each point:
    - no provider `run()` is recorded;
    - one `error` is written, and no `turn.ended` or `session.ended`;
    - the chat is `awaiting_send`;
    - `session.json` is byte-equal to the record before Send, with no `Interrupted` entry. In the undo-save case, the file keeps the pre-write while the run holds the record before it, and the next Send's pre-write replaces the file;
    - the summary's `send.failure` comes from `send.not_started`;
    - a second Send succeeds.

  Acceptance: red for want of the guard.
- [ ] T062 [US2] [py] Lane B. Implement the failure branch in `_run_turn` (`agent/runner.py:1434-1442`), the guard over `send`'s steps 1 to 7, `_send_error`, and `INTERRUPTED_SEND`. The state and the failure are set before the `error` is emitted. Acceptance: T061 green; T058 and T059 green; T007 byte-equal.
- [ ] T063 [US2] [py] Lane B. Extend `reviewer/tests/unit/test_send_gate_server.py` with the hold (`contracts/review-flow.md` section 4; research R2.12; RK-14):
  - With `record_disposition` held in the thread pool on a waiting chat, `GET` reads `running`, and `POST /send` and `POST /evidence` are `409 TurnRunning`.
  - On release, the decision is saved, the chat is `awaiting_send` again, and Send succeeds.
  - The same holds for `record_timing_live` and the timing route.
  - **A stop during the hold** (FR-025; the spec's edge case "Stop while a review waits"): with `record_disposition` held, and again with `record_timing_live` held, `POST /stop` answers `202` and writes no event. After the release the chat is `awaiting_send` with `chat.stop_requested` unset. A following Send, whose scripted first turn makes a tool call, runs to `end`: no `stopped` turn, and exactly one presentation request. The same holds when the held write then raises.
  - A ticked chat's two routes take today's path, with no move.

  Acceptance: red for want of the hold.
- [ ] T064 [US2] [py] Lane B. Hold a waiting chat `running` in `disposition` and `timing` (`chat/server.py:1444-1483`): move it right after `_require_idle`, with no `await` between. In a `finally`, clear `chat.stop_requested` and move it back, with no `await` between, as `_play`'s `finally` clears the flag (`:2201`). A stop sent during the hold sets the flag (`:1497-1498`), and a flag left set would stop the next Send's first turn at its first tool call. Acceptance: T063 green; `test_chat_timing_route.py` green and unedited; T007 byte-equal.
- [ ] T065 [P] [US2] [py] Lane G. Extend `reviewer/tests/unit/test_pane_waiting_fixtures.py`: `review-waiting.json` and `review-waiting-big-assembly.json` each gain `failed_send`, the live snapshot after a Send whose scripted first request failed, with the `send.failed` line as its `send.failure`. Acceptance: red for want of the snapshot.
- [ ] T066 [US2] [py] Lane G. Extend `generate_waiting_fixtures.py` to play that Send and write `failed_send`; regenerate both files. Acceptance: T065 green; the hygiene test green.
- [ ] T067 [US2] [page] Lane W. Extend `ReviewPageSendGateTests.cs` with Send (`contracts/pane.md` sections 3, 6 and 10; FR-017 to FR-019, FR-035).
  - **Send**:
    - It posts `/send`. On `202` the block hides, the turn is marked running, and the stream reopens.
    - The first `usage` clears the not-sent mark and enables the follow-up box.
    - Once a Send is in flight, Stop is today's.
    - `session.sent` writes "Sent to {provider} {model} ({requested} -> {param}={value}) - first request {n} input tokens".
  - **Failures**:
    - On `failed_send`, no error card is drawn: the failure line shows, Send is offered again, and the text the failed round streamed stays in the Transcript.
    - A Send that fails before any request (one `error`, no `usage`, no `session.ended`) draws no error card, unmarks the turn, prints the failure line, and offers Send again.
    - `NoCredential` prints its label beside Send. A `409 TurnRunning` prints as any refusal does.
    - A ticked review whose first request fails (`error`, `turn.ended {error}`, `session.ended`) shows today's error card and Retry, and no Send block: the rule for an `error` while sending never applies, since a ticked review never sets `state.sending` (FR-035).
  - **The document binding**: Send is disabled while another document or a drawing is active, and offered again on return.
  - **Two waiting reviews**: with two waiting chips, Send posts `/send` for the chip on screen only, and the other chip stays waiting, with its mark.

  Acceptance: red for want of the press.
- [ ] T068 [US2] [page] Lane W. Implement Send in `app.js`: `state.sending`; the press; the rule for an `error` while sending, which re-reads the attention; the enabling rule; and the Transcript line, which shares `describeStart`'s effort part. Add the failure line to `render.sendBlock`. **Amends 009** `contracts/views.md` section 2 (the block sits under the summary). Acceptance: T067 green; `PageRuleScanTests` green.
- [ ] T069 [US2] [page] Lane W. Extend `ReviewPageSendLayoutTests.cs` with `failed_send` and its failure line: the headline, tally and not-reached line, and the Send to model button, are inside 300 by 600 (SC-007). This is an acceptance test. Acceptance: green.
- [ ] T070 [P] [US2] [py] Lane R. Extend `reviewer/tests/unit/test_recording.py` and `test_cli_benchmark_replay.py` (`contracts/records.md` section 6; FR-040). Before it reads the events, `read_recording` refuses, with one `RecordingRefused` sentence each:
  - a never-sent or send-failed session: "{RUN_DIR} was never sent to the model, so it has no model turn to replay";
  - a session sent after waiting: "{RUN_DIR} was sent to the model after waiting for Send; the replay reads only reviews sent when their checks finished".

  A review sent at once reads as today. **Moved**: the refusal tables of `test_recording.py` and `test_cli_benchmark_replay.py` gain the two rows ahead of the event read. Acceptance: red for want of the refusals.
- [ ] T071 [US2] [py] Lane R. Implement the two refusals in `benchmark/recording.py` (`read_recording`, `:149`), placed before the existing no-usage refusal (`:163-167`). **Amends 008** `contracts/replay.md` section 2. Acceptance: T070 green; every replay test green and unedited.
- [ ] T072 [P] [US2] [py] Lane B. Add `test_the_estimate_bounds_each_recordings_billed_first_round` to `reviewer/tests/unit/test_send_estimate.py` (`contracts/estimate.md` section 6; SC-006), an acceptance test over existing code. For each real OpenAI recording the replay reads, through `tests/support/recordings.recording_folder` and the vocabulary fixture, the count of the first request the replay rebuilds is at least the recording's billed first-round input and at most 25% above it. Each gap is printed as a percentage only. The test is skipped, naming why, where the mapping or a folder is absent. Acceptance: green where the recordings are; skipped, naming why, elsewhere.
- [ ] T073 [US2] [py] Lane G. **US2 gate**: T031's commands (from `reviewer/`, and `extractor/SwReview.sln` from the root) and the replay regeneration step over `reviewer/tests/fixtures/replay` (the runner and the replay reader moved). Nothing is committed; T109 records the outcome.

**Checkpoint**: Send states its size, sends a ticked review's first request byte for byte, and leaves the review waiting with the reason beside Send whenever it fails before the model answers.

---

## Phase 5: User Story 3 - The Engineer's Work While It Waits Is Kept (Priority: P3)

**Goal**: answers and decisions made while a review waits are applied by code and kept at Send. The model's opening says what code applied, and names nothing that code withdrew.

**Independent Test**: spec.md User Story 3; quickstart Scenario 3.

- [ ] T074 [US3] [py] Lane B. **Refactor**: extract `ReviewRun._apply_answers(answers, *, read_drawings=True)` from `answer_evidence_batch` (`agent/runner.py:1138-1202`), and have `answer_evidence_batch` call it before `_ask` (`contracts/review-flow.md` section 4; DRY). It holds the batch's steps 1, 2 and 2a: validate; mark each answer with `evidence.answered`; `read_confirmed_candidates`; the part-roles regrade; one `_restate`; and the bought-parts and unmatched-piece rows. A refactor under existing pins, with no new test: T007's resumed answer pins every request, event and record of this path. Acceptance: T007 byte-equal; `test_answer_batch_roles.py`, `test_confirmed_drawing_read.py` and `test_part_roles.py` green and unedited.
- [ ] T075 [P] [US3] [py] Lane B. Write `reviewer/tests/unit/test_waiting_answers.py` over T006's package (`contracts/review-flow.md` section 4; FR-020 to FR-022, FR-024; US3 scenarios 1 to 3; SC-001).
  - **"All bought"** through `POST /evidence` on a waiting chat:
    - withdraws the unclear part's findings, with `finding.withdrawn` events;
    - makes no provider request and builds no provider, and writes no `turn.*` event;
    - settles `awaiting_send`.
  - **What it changes**:
    - The session is finalized again, so `session.json`, `report.md`, `attention.json` and the summary show the regraded review.
    - The Send cache is rebuilt once, on the worker: a new `SendCache`, never built on the event loop. Its count is checked in T077, once T078 rebuilds the opening it counts.
    - `resume_text` is `send.apply_answers`.
  - **Refusals**: an answered question cannot be answered again. Send while an apply is held is `409 TurnRunning`, and an answer while a Send is in flight is `409`.
  - **A confirmed drawing read** while waiting, with the scripted seat, appends `{file, outcome}` to `session.drawing_outcomes` (a refusal's outcome too), and starts no turn (FR-021).
  - **Decisions and timing**: a Reject while waiting is saved at once, is still on its finding after Send, and from then on is treated as a decision made between turns (FR-024). A timing input made while waiting is kept at Send.

  Acceptance: red for want of the waiting branch.
- [ ] T076 [US3] [py] Lane B. Implement the waiting branch of `answer_evidence_batch`. After `_apply_answers`:
  1. append each `ConfirmedRead` to `drawing_outcomes`;
  2. set `_opening_changed`;
  3. `build_send_cache()`;
  4. finalize.

  No `_ask`, no `REGRADED_LINE` and no turn event. The step `review-flow.md` section 4 places between 1 and 2, replacing the restated tools' calls in `_prerun`, needs `prerun.restated` and lands with it in T078; until then `opening_at_send()` has only its frozen branch (T035), so the cache this task rebuilds still holds the frozen opening. T078 completes the branch. **Amends 008** `contracts/answer-batch.md` section 1 step 3; **009** spec FR-015; **011** `contracts/confirmed-open.md` section 1. Acceptance: T075 green; T007 byte-equal.
- [ ] T077 [US3] [py] Lane B. Extend `reviewer/tests/unit/test_waiting_answers.py` and `test_runner_send.py` with the opening at Send (`contracts/review-flow.md` section 5; FR-013, FR-014, FR-023; SC-004, SC-005; research R2.27).
  - **The count** (FR-013): after "All bought" while waiting, the Send cache's count changes, and equals the count of the new prefix, `request_prefix(system, tools, <the rebuilt opening>)`.
  - **`prerun.restated(prerun, context, calls, standards)`** returns its input when nothing was restated. Otherwise it replaces each restated tool's calls in place, re-reading their findings from the standing findings that cite the call's step, and recomputes `not_evaluated` with the current roles.
  - **The frozen pin**: the builder `_opening_message` reproduces the frozen opening byte for byte when nothing was applied.
  - **After "All bought" while waiting, then Send**, the first request's opening:
    - names no withdrawn named finding, and names every standing one;
    - has a folded-family counts line equal to the regraded session's counts;
    - after the digest and before `OPENING_MESSAGE`, carries one `DRAWING_OUTCOME_LINE` per drawing outcome, in order, then one `WAIT_ANSWER_LINE` per answered question, in answer order;
    - has no "withdrew" line, and no instruction to re-run, replace or continue.
  - With no wait line, the separator is absent.
  - `opening_finding_ids` names none of the findings the answer withdrew (SC-010's fixture half).
  - **The coverage at Send after an apply** (research R2.27, RK-11): at Send's first request the session holds no row of any earlier finalization, neither the unticked start's nor the apply's (no close-out row, no unresolved row of an open question or item), so `get_review_checklist` and every `open_items` show each model-owned item with no finding as open. Rows the apply's own code wrote (the part-roles row, the bought-parts rows) stay.
  - A failed Send, then an apply, then Send sends the rebuilt opening once (FR-017).
  - **Never sent again** (FR-023, last sentence; `review-flow.md` section 5). After a part-roles answer and a confirmed drawing read while waiting, then Send, the scripted first turn asks a question. The engineer answers it, then sends a follow-up. Asserted:
    - The message the answer adds, and the follow-up's, carry no `WAIT_ANSWER_LINE` and no `DRAWING_OUTCOME_LINE` of the wait.
    - Every later request, the presentation requests included, carries each of the wait's lines at most once, inside the opening it already holds.

  Acceptance: red for want of the rebuild.
- [ ] T078 [US3] [py] Lane B. Implement `prerun.restated` in `prerun.py`. In `agent/runner.py`, complete T076's waiting branch with the step `review-flow.md` section 4 places between the outcomes and `_opening_changed`: replace the restated tools' calls in `_prerun` through `prerun.restated`. Add the rebuilt branch of `opening_at_send` and `WAIT_ANSWER_LINE`. **Amends 008** `contracts/checks-first.md` section 4 (the opening rebuilt after a regrade; the wait's lines); **013** spec FR-040, `contracts/drawing-capability.md` section 6 and `contracts/part-roles.md` section 9. Acceptance: T077 green; T007 byte-equal.
- [ ] T079 [US3] [py] Lane B. Extend `reviewer/tests/unit/test_waiting_answers.py` with an apply that fails (`contracts/review-flow.md` section 4, "An apply that fails"; FR-020; research R2.13; RK-12).
  - **Before the save**: `classify_part_roles`, the confirmed read, the Send cache's build and the finalization's `save_session` (`write_atomic`) each raising give:
    - one `error` event, and no `turn.ended` or `session.ended`;
    - the chat `failed`;
    - `session.json` and `report.md` holding the record before the apply, with its answers open;
    - the provider factory never called.
  - **After the save**: `write_attention_record` raising gives `session.json` as the applied record, with its answers answered.
  - Either way, the failed chat no longer holds the folder.
  - **Shutdown during an apply** (FR-010; research R4.1): with an apply held on the chat's worker (`classify_part_roles` patched to block on an event), `ChatServer.shutdown()` writes no `turn.ended`, no `error` and no second `session.ended`, although the chat reads `running`: the session's `ended_at` is still the unticked start's, so `_finalize_on_exit` (`chat/server.py:2327-2334`) skips it through `_already_ended` (`:2337-2345`). Checked when `shutdown()` returns, before the apply is released: `session.json` is the record before the apply. This case pins today's skip and may pass before T080; it fails any later change that clears `ended_at` in the waiting branch.

  Acceptance: red for want of the failure path.
- [ ] T080 [US3] [py] Lane B. Implement the waiting branch's failure path in `agent/runner.py`: `context.session = load_session(session_path)`, one `error` (`retryable: true`), then re-raise. Acceptance: T079 green.
- [ ] T081 [P] [US3] [page] Lane W. Extend `ReviewPageSendGateTests.cs` (`contracts/pane.md` sections 4 to 6; FR-020, FR-033):
  - While the summary has a `send` block, the questions panel's button reads "Apply answers", and its sentence is the summary's `resume_text`.
  - Applying posts `POST /evidence` and locks the panel. Until the stream settles, the status line stays "Checked by code. Not sent to the model.", Stop stays off and Send is disabled.
  - A reload during an apply shows the review waiting.

  Acceptance: red for want of the label.
- [ ] T082 [US3] [page] Lane W. Implement the "Apply answers" label and the apply's state rule in `render.js` (`:682-685`) and `app.js`. **Amends 009** `contracts/questions.md` sections 4 and 5. Acceptance: T081 green; `ReviewPageQuestionsTests` green and unedited.
- [ ] T083 [US3] [py] Lane G. **US3 gate**: T031's commands (from `reviewer/`, and `extractor/SwReview.sln` from the root) and the replay regeneration step over `reviewer/tests/fixtures/replay` (the runner and the pre-run moved). Nothing is committed; T109 records the outcome.

**Checkpoint**: an answer made while a review waits regrades it by code and changes the size sentence. A decision made while it waits stays on its finding. At Send, the model reads what code applied and nothing that code withdrew.

---

## Phase 6: User Story 4 - A Waiting Review Survives a Restart (Priority: P3)

**Goal**: after a Settings save, a crash or SOLIDWORKS reopening, a waiting review comes back with its questions, decisions and Send still usable. Its first action re-runs the checks from the same folder, carrying everything by identity and naming what does not carry, and nothing is sent.

**Independent Test**: spec.md User Story 4; quickstart Scenario 4, and Scenario 6's restored cases.

### The backend

- [ ] T084 [P] [US4] [py] Lane B. Write `reviewer/tests/unit/test_recheck.py` with the carried live step (`contracts/recheck.md` section 3; FR-028; SC-008; research R2.17).
  - **No new bridge call**: `prerun_checks(..., carried_live=LiveOutcome.from_record(...))` makes no `bridge_interference` call with SOLIDWORKS attached. The seat is a `ScriptedReviewBridge` whose `calls` stay empty before the first request.
  - **One carried step**, recorded through `registry.record_call` at the first run's `live_detection.step_index`, with the payload `{"status": "carried", "note": CARRIED_LIVE_NOTE, "outcome": ...}` and the first run's arguments:
    - every later step index and finding citation equals the first run's;
    - a repeated live call is answered with `ran_at_step` naming the carried step;
    - `tool-results/step-N.json` holds the carried payload.
  - **Every outcome carried**: the digest's interference line, the coverage rows (a clean detection's checked item in its bucket) and the withheld tools equal the first run's for each of: clean; rows found; rows collided; failed (carried as failed with the first run's `failed` row, and not retried); no bridge (no step); not an assembly (no step).
  - **Rows the first run could not write** (`persist_error`), with the dump's stale rows for that configuration still in `package.json`: no finding cites one, and the family row is `INTERFERENCE_ROWS_NOT_CARRIED`.
  - **The drawing-read capability**: `ToolContext.carry_drawing_read` sets the cache and `session.drawing_read`, so no ping is made, and a second re-run of that record makes zero bridge calls.

  Acceptance: red for want of `carried_live`.
- [ ] T085 [US4] [py] Lane B. Implement:
  - in `prerun.py`: `prerun_checks(carried_live=)` (`:1052`); the carried step and its `PrerunCall`; the removal of the reviewed configuration's rows when `persist_error` is set, as `_live_interference` removes them (`:1280-1281`); `CARRIED_LIVE_NOTE`; and `INTERFERENCE_ROWS_NOT_CARRIED`;
  - in `tools/context.py` (`:403-419`): `ToolContext.carry_drawing_read`;
  - `start_review(earlier=)`, passing both.

  **Amends 008** spec FR-008, FR-009 and FR-030, and `contracts/checks-first.md` section 2 row 1 and sections 3 and 7. Acceptance: T084 green; T007 byte-equal.
- [ ] T086 [US4] [py] Lane B. Extend `reviewer/tests/unit/test_recheck.py` with the claim and the rotation (`contracts/recheck.md` sections 2, 6 and 7; FR-041; RK-4).
  - **A re-run**: `POST /sessions` with `recheck: true` and `send_when_checked: false`, on a folder whose `session.json` is a not-sent record:
    - copies `session.json` and `attention.json` to index N, and moves `events.jsonl` and `tool-results/`;
    - registers its chat only after its finalization, `awaiting_send`;
    - answers `201` with `carried`, whose maps are empty here: nothing is carried until T089.
  - **Refusals**:
    - `recheck: true` with `send_when_checked: true` is `400 InvalidRequest`.
    - A folder with no readable `session.json`, or a deleted folder, is `404 UnknownReview`.
    - A record with no `model_status`, or one that is `sent`, is `409 NotWaiting`.
    - A live chat on the folder that is `running` is `409 RunDirInUse`.
  - **Adoption**: a second re-run sent while the first is held in the backend is `409 RunDirInUse` and starts nothing. One sent after the first answers **adopts** it: the same chat id and `carried`, nothing run again, and the factory never called.
  - **Failure and cut-off**: a re-run that fails (an unreadable package), or is cut off after the rotation, after `start_review` and before the finalization, or inside the finalization's `write_atomic`, leaves `session.json` byte-equal to the earlier record, with the provider factory never called. A second re-run then succeeds at the next index.
  - **The indexes**: two failed re-runs then one that succeeds leave every index either a session with the stream it wrote, or a failed attempt's stream alone; the earlier record is copied once.
  - **Nothing written early**: with nothing carried, the carry writes nothing. `session.json`, `report.md` and `attention.json` are unchanged on disk from the claim until the finalization.

  Acceptance: red for want of `recheck`.
- [ ] T087 [US4] [py] Lane B. Implement in `chat/server.py`:
  - the `recheck` field;
  - `_claim_run_dir(..., recheck=True)` (`:2025-2060`), with the adoption and `ChatServer._rechecking`;
  - `_rotate_previous(chat, keep_record=True)` (`:2062-2099`), deciding by what the canonical stream is;
  - the re-run path of `create_session`: `start_review` with the earlier record, `build_send_cache`, `finalize` through `write_atomic`, `_render_run`, then register; and its `201` with `carried` as empty maps, which T089 fills.

  **Amends 002** `contracts/chat-api.md` (`POST /sessions`' `recheck`, and its `carried`). Acceptance: T086 green; T007 byte-equal.
- [ ] T088 [US4] [py] Lane B. Extend `reviewer/tests/unit/test_recheck.py` with the carry (`contracts/recheck.md` sections 4, 5 and 7; FR-021, FR-029, FR-032; SC-008; the US4 independent test).
  - **The independent test's record** holds a part-roles answer, a drawing answer whose read moved the finding and question numbers, and a Reject. Its re-run:
    - makes no extraction, and zero bridge calls before the first request;
    - puts each answer and the Reject on its own item, matched by `asks_same` and `findings.finding_subject_key`, never by number;
    - carries the outcome line;
    - fills the `carried` maps with each move.
  - **Matching cases**:
    - Two `hole.coaxiality` findings on one pair of components, one of them Rejected: the Reject is carried onto its own finding, and nothing is named.
    - An unmatched answer, an ambiguous answer, an unmatched decision and an ambiguous decision are each named once, in one `coverage.recheck` row (`NOT_CARRIED`).
  - **Records**:
    - The four timing inputs are carried.
    - A `send_failed` record's re-run stays `send_failed` with its failures, and its report keeps the failure line. A Send that then succeeds reports "Earlier attempts that failed: 1".
  - **The Standards profile**: when it has changed (to another file, or the same file edited), the re-run grades with the profile in effect, records its identity on `model_status.profile`, and names the change and any decision whose finding the new profile no longer raises. An unchanged profile names nothing.
  - **What T079's failures leave**:
    - An earlier open drawing-candidate question whose drawing an unfinished read merged is not asked again and carries no outcome line, and the loss is named once.
    - An apply that failed after its write has its answers carried.
  - **SC-008**: with nothing answered, the same provider and model, and SOLIDWORKS attached as at the first run, every request of Send's first turn after the re-run is byte-identical to the live waiting review's.
  - The carry writes nothing before the finalization.

  Acceptance: red for want of `carry_from`.
- [ ] T089 [US4] [py] Lane B. Implement `ReviewRun.carry_from(earlier)`, `ReviewRun.carried`, `NOT_CARRIED` and the `coverage.recheck` row in `agent/runner.py`. The carry works in memory only, never calling `record_disposition`, `record_timing_live` or `save_session`. The answers go through `_apply_answers(..., read_drawings=False)`; the opening is rebuilt when anything was carried; the Send cache is built last. `create_session` (one line in `chat/server.py`, in this task) answers the run's `carried` in place of T087's empty maps. Acceptance: T088 green; T007 byte-equal.
- [ ] T090 [US4] [py] Lane R. Extend `reviewer/tests/unit/test_chat_review_routes.py` and `test_review_snapshot.py` (`contracts/recheck.md` section 8; FR-031, FR-041):
  - `GET /reviews/{run_id}` answers a `not_sent` or `send_failed` record with `read_only: false`, no `read_only_reason`, and `summary.send {state: "restored", session_id: <the record's>, input_tokens: null, text: send.restored, restored_text, rerun_failed_text, failure}`, where `restored_text` names `checked_at`'s stored wall clock.
  - A sent record, and one with no `model_status`, are read-only as today.
  - After T086's failed and cut-off re-runs, the folder answers its earlier record this way.
  - The route writes nothing.

  Acceptance: red for want of the restored block.
- [ ] T091 [US4] [py] Lane R. Implement the restored block in `_read_review` (`chat/server.py:1660-1682`; one branch in lane B's file, in this task) and in `report/snapshot.py`. **Amends 002** `contracts/chat-api.md` (`GET /reviews`); **009** spec FR-021 and `contracts/sessions.md` section 4. Acceptance: T090 green.

### The restored fixtures

- [ ] T092 [P] [US4] [py] Lane G. Extend `reviewer/tests/unit/test_pane_waiting_fixtures.py`, with every clock pinned:
  - `extractor/SwReview.AddIn.Tests/Fixtures/review-waiting-restored.json`, from T006's package, holds three snapshots:
    - `restored`: the run-folder snapshot of the record, with nothing answered;
    - `restored_answered`: the same after a part-roles answer, a confirmed drawing read and a Reject, all made while it waited. The generator plays the read's merge into the folder's package as the host would;
    - `rechecked`: the re-run's `POST /sessions` answer with its `carried` maps, and the re-run's live snapshot. `rechecked.carried` maps at least one id to a different one.
  - `review-waiting-big-assembly.json` gains `restored`.
  - `extractor/SwReview.AddIn.Tests/Fixtures/review-not-sent-session.json` is the earlier record's `session.json`, as `save_session` wrote it, for the host's cross-language head-reader case (research R4.2). Its name matches the test project's `Fixtures\review-*.json` Content glob (`SwReview.AddIn.Tests.csproj:180`), so it is copied to the output folder the add-in tests read from (`ReviewFixture.cs:189`), and the project file is not edited. As `test_pane_drawing_fixture.py:105-111` does, the test asserts each generated file's path ends `SwReview.AddIn.Tests/Fixtures/review-*.json`.

  **Moved**: the hygiene list gains `review-waiting-restored.json` and `review-not-sent-session.json`. Acceptance: red for want of the files.
- [ ] T093 [US4] [py] Lane G. Extend `generate_waiting_fixtures.py` to write them, `review-not-sent-session.json` included, into `extractor/SwReview.AddIn.Tests/Fixtures/`; regenerate. Acceptance: T092 green; the hygiene test green; after `dotnet build`, `review-not-sent-session.json` is in the test project's output `Fixtures` folder.

### The host

- [ ] T094 [P] [US4] [C#] Lane H. Extend `ReviewHostTests.cs` and `BackendClientSessionBodyTests.cs` (`contracts/recheck.md` sections 1 and 7; FR-028, FR-041).
  - **Refusals**: `review.recheck {chat_id}` is refused, changing nothing, with `InvalidRequest` (no id), `UnknownChat`, `DrawingActive`, `ReviewNotActive` (another document; the path compared ignoring case, the configuration exactly) or `BackendUnavailable`.
  - **Otherwise**, the host:
    1. posts `status {stage: "checking", message: "Checking the saved evidence again..."}`;
    2. calls `POST /sessions` with the record's own folder, the settings in effect, the bridge, `send_when_checked: false` and `recheck: true`, making no folder and dumping nothing;
    3. replaces the record: the same folder and document, the new chat id, and the time now;
    4. posts `status {stage: "ready", message: "Checked the saved evidence again; nothing was sent to the model."}` and answers `review.rechecked {chat_id, previous_chat_id, run_dir, not_examined, document, carried, review_session_id}`.

    Each status's stage and message are asserted, the message as a literal (`contracts/words.md` section 5).
  - A backend refusal is rethrown with its class.
  - The call is made with `Recheck` set, so `TimeoutFor` gives the long timeout.
  - The 201's `carried` reaches `ChatSessionHandle.Carried`.

  **Moved**: `ErrorLabelsCoverTheHostTests.TheScanFindsTheClassesTheHostAndThePageMake`'s expected list gains `ReviewNotActive`. Acceptance: red for want of the message.
- [ ] T095 [US4] [C#] Lane H. Implement `review.recheck` in `ReviewHost.cs`, and `ChatSessionHandle.Carried` in `Review/IBackendClient.cs` and `BackendClient.cs` as an optional constructor parameter, so no fake changes. **Amends 002** `contracts/pane-host-messages.md` (the `status` stage `checking`). **The new row `review.recheck` waits for T099**, the commit where the page first posts it, by the rule T045 states. Acceptance: T094 green; zero warnings.
- [ ] T096 [US4] [C#] Lane H. Write `extractor/SwReview.AddIn.Tests/RunFoldersNotSentTests.cs` over fictional folders, and extend `ReviewHostTests.cs` (`contracts/recheck.md` section 9; FR-030; RK-6).
  - **Offered** when the newest same-name folder's `session.json` head says `not_sent` or `send_failed` and names this path and configuration.
  - **Not offered**:
    - behind a newer sent review;
    - behind a check run that failed with no `session.json`;
    - for another path with the same file name, or another configuration;
    - when the host already holds a review of the document;
    - when a head has no `model_status` within 64 KiB;
    - when the root or the file is unreadable (and nothing throws).
  - **Folder names**: `-check`, `-standards` and `-remodel` folders are skipped, and the `-N` collision suffix is read.
  - **The cross-language case**: T093's `Fixtures/review-not-sent-session.json`, written by the backend's own `save_session`, is read by the head reader from the test output folder.
  - **The found item**: its chat id is its `session_id`, and its time is `checked_at`'s stored wall clock.
  - **The bound**: a 500-folder root is searched within 2 s. It is a `[Fact]` timed with `Stopwatch`; the add-in tests carry no perf category, so it runs in the gate.
  - **`ReviewHostTests.cs`**:
    - `sessions.list` runs the search first, and its item carries `model_status`.
    - **A found review can be re-run** (FR-030; the US4 Independent Test's last sentence; `contracts/recheck.md` sections 1 and 9). After `sessions.list` offers a found review, `review.recheck {chat_id: <its session_id>}` is accepted, not refused `UnknownChat`. The host posts `status {stage: "checking"}` and calls `POST /sessions` with the found folder, `recheck: true`, `send_when_checked: false` and no dump. It then answers `review.rechecked`, whose `previous_chat_id` is the found `session_id`.
    - A second `sessions.list` tracks the same record: one item, the same chat id.

  Acceptance: red for want of the search.
- [ ] T097 [US4] [C#] Lane H. Implement `RunFolders.FindNotSentReview` in `Review/RunFolders.cs`: names first (`DocumentName`, `TimestampOf`, `CarriesSuffix`), then one `Utf8JsonReader` head read of at most 64 KiB, stopping at `model_status`. Add `SessionRecord.ModelStatus`, and the search in `sessions.list` in `ReviewHost.cs`. A found review is tracked as a review record that `review.recheck` accepts (data-model section 9): its folder, the document its `model_status.document` names (path and configuration), its chat id its `session_id`, and its time its `checked_at`. **Amends 002** `contracts/pane-host-messages.md` (`sessions.list`); **009** `contracts/sessions.md` sections 5 and 6. Acceptance: T096 green; zero warnings.

### The page

- [ ] T098 [US4] [page] Lane W. Write `extractor/SwReview.AddIn.Tests/ReviewPageRecheckTests.cs` on `review-waiting-restored.json` (`contracts/pane.md` sections 4, 5 and 7 to 9; `contracts/recheck.md` sections 7 and 10; FR-027, FR-030, FR-031, FR-033, FR-041, FR-042). As test infrastructure, make `ReviewPageDriver.cs`:
  - answer `review.recheck` with the fixture's `rechecked` body, with an error mode taking a given class;
  - offer `HoldReviewRecheck` and `ReleaseReviewRecheck`. A held re-run queues every later page message and answers them in order on release, as the host's one pump does.

  The tests:
  - **A restored review** shows the restored line in `#read-only` and the sentence without a number. Its questions, decisions and Send are enabled, the follow-up box is off, and feature 009's read-only sentence is not shown. The Settings section shows `pane.md` section 9's line "Saving restarts the backend. The waiting review stays, and its next answer, decision or Send checks its saved evidence again first." under Save, as for a live waiting review (T050; FR-027, "live or restored").
  - **Found after SOLIDWORKS reopens** (FR-030; US4 scenario 5 and the US4 Independent Test's last sentence; `contracts/recheck.md` section 9; `pane.md` section 8). Today the page asks `sessions.list` after `init` (`app.js:2611`) and after a start (`:1678`); its `document.changed` case does not ask (`:238-244`).
    1. `init` arrives with no document open, and the driver answers `sessions.list` with no items.
    2. A `document.changed` to the reviewed document makes the page post `sessions.list` again. The driver (its existing `Sessions` list, filled between the two asks) answers with one item carrying `model_status`, its `started_at` (the record's `checked_at`, data-model section 9) on another day.
    3. The page shows the found chip, dated "{YYYY-MM-DD} {HH:MM}" and marked " · not sent".
    4. No review of the document is on screen, so the page follows with the new list (009 section 6's rule) and restores the review from its folder: the restored line, Send enabled.
    5. Pressing Send posts `review.recheck` with the found item's `chat_id`, then `/send`.

    A `document.changed` while a review of that document is on screen asks again and leaves that review shown.
  - **Its first action**:
    - Send, an answer and a decision each post `review.recheck` first, then the live route, with ids re-keyed by `rechecked.carried`.
    - An answer naming the record already shown (`review_session_id` equal to `send.session_id`) re-keys nothing.
    - A pending decision whose finding is not carried says "This decision no longer applies: its finding is not raised again.".
  - **While a re-run is held**:
    - The status line reads "Checking the saved evidence again.", and the Settings line switches to "Checking the saved evidence again; save when it is done.".
    - Save, Review, the chips, answers, decisions and Send are refused, and there is no Stop.
    - On release, the review is live and waiting, and the Settings line is the waiting one again.
  - **When it fails**:
    - A failed re-run prints `rerun_failed_text` with its class in a fold, keeps Send offered, and offers no Retry.
    - `UnknownReview` prints feature 009's "This review can no longer be restored.".
  - **Restarts and reloads**:
    - A backend restart (an `init` naming another backend) with a live waiting review on screen restores it at once (FR-042).
    - A found chip names its date when that is not today.
    - A reload while a re-run is held shows nothing of the review until the release, then shows it waiting: never running, and never being checked again.
  - **An apply that fails** (an `error` during an apply, with no `turn.ended`): no error card, the panel unlocked, and the review restored from its folder with the error's label in the Send block's failure line (`pane.md` section 5). This case moved here from US3 because it reads this fixture.

  **Moved**:
  - `ReviewPageViewsTests.TheStatusLineReadsEachOfItsSentencesInItsState` gains the re-run row.
  - `ReviewPageDefaultViewScanTests.NoRawStatusOrBucketTokenIsVisible` runs on `review-waiting-restored.json` too.

  Acceptance: red for want of the restored flow.
- [ ] T099 [US4] [page] Lane W. Implement in `app.js` and `render.js`:
  - `state.rechecking` and `recheckThen(action)`;
  - the re-keying by `carried`;
  - the restored line, the re-run's status-line state, and the refusals while a re-run runs;
  - the restart rule after `init`, and the apply-failure restore;
  - the dated found chip; and `sessions.list` asked again on `document.changed`, after following with the list the page holds, then followed again with its answer by the same rule (`requestSessions(true)`, as after `init`).

  **Amends 002** `contracts/pane-host-messages.md`: the new row `review.recheck`, with its reply `review.rechecked`, in this commit, where the page first posts it (T045 says why). **Amends 009** `contracts/views.md` section 3 (the re-run state) and `contracts/sessions.md` sections 5 and 6. Acceptance: T098 green; `ReviewPageContractTests` green with the row in place; `ReviewPageSessionsTests` and `ReviewPagePreparationTests` green and unedited; `PageRuleScanTests` green.
- [ ] T100 [US4] [page] Lane W. Extend `ReviewPageSendLayoutTests.cs` with two cases: `restored`, with its restored line and sentence; and `restored` after a failed re-run, with the `rerun_failed` line. In each, the headline, tally and not-reached line, and the Send to model button, are inside 300 by 600 (SC-007). Record the measured figure in research R2.21. An acceptance test. Acceptance: green; if it fails, the owner question of research R2.21's end state.
- [ ] T101 [US4] [py] Lane G. **US4 gate**: T031's commands (from `reviewer/`, and `extractor/SwReview.sln` from the root) and the replay regeneration step over `reviewer/tests/fixtures/replay` (the runner, the pre-run and the records moved). Nothing is committed; T109 records the outcome.

**Checkpoint**: a waiting review survives a Settings save, a crash and SOLIDWORKS reopening. Its first action re-runs the checks from its own folder, with zero extractions and zero bridge calls. Everything is carried by identity, what is not carried is named, and nothing is sent.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: the last record that names a provider, the seat's step, the contracts as landed, the adversarial review, and the final gate.

- [ ] T102 [P] [py] Lane R. Extend `reviewer/tests/unit/test_handoff.py` (`contracts/records.md` section 7; research R2.24). The handoff bundle's session summary gains `model_status` (its state) when the session carries one, beside `provider_info`, and nothing else in the export moves. A ticked session's bundle is unchanged. Acceptance: red for want of the key.
- [ ] T103 [py] Lane R. Implement it in `_session_summary` in `handoff.py` (`:360-401`). **Amends 002** `contracts/handoff-export.md`. Acceptance: T102 green.
- [ ] T104 [P] [py] Lane S. Add `"015-review-send-gate"` to `PACKAGES` in `reviewer/tests/support/seat_tasks.py`, and to its docstring. `test_workstation_test_plan.py` and `test_workstation_handover.py` go red, naming 015 T110 as unplaced. Acceptance: red for want of the step.
- [ ] T105 [doc] Lane S. Place T110 in the sitting's three documents:
  - `docs/test-plan-2026-09-27/workstation-test-plan.md` gains step 4.10, "A, unticked, then Send [015 T110]", with quickstart Scenario 8's six steps (no design name or number);
  - `workstation-results.md` gains its row, shipped blank;
  - `workstation-handover.md` gives T110 its place in the sitting.

  Acceptance: T104 green.
- [ ] T106 [doc] Lane C. Reconcile the contracts with what landed:
  - Where code had to differ, each 015 contract in `specs/015-review-send-gate/contracts/` gets a dated "*Landed as*" note.
  - Each row of `contracts/README.md`'s amendments table now has its amendment text in place, not only T001's note.
  - Research R2.21 holds the measured figures from T052, T069 and T100.

  Documents only.
- [ ] T107 Adversarial review (62A). An Opus reviewer who wrote none of the code reads the branch's whole diff against `spec.md`, the contracts and this list. The reviewer hunts for:
  - any path that reaches a provider before Send (SC-001);
  - any byte a ticked review changes (FR-035);
  - any record that says sent or not sent wrongly (FR-032);
  - any carry by number (FR-029);
  - anything the re-run writes before its finalization (FR-041);
  - any page word or colour outside the design system (FR-005);
  - any company value or local path (FR-039).

  Each finding is either fixed test-first in the task that owns the file (one commit each, every commit passing the gate), or recorded in `research.md` as a default the owner may revise. Acceptance: the review's findings are each fixed or recorded.
- [ ] T108 [py] Lane G. **Only when feature 014 is on `main` before this branch merges** (research R3; RK-8). In the merge commit:
  - classify `send_when_checked` and `earlier` as `COMPARED` in 014's `reviewer/tests/unit/test_benchmark_pane_parity.py`;
  - pass `mark` on every 015 call of `recorded_call`, and stamp the carried live step `origin_mark: "prerun"`, with the assertion added to `test_recheck.py`;
  - keep 014's `atomic.py` and `test_atomic.py`, one copy each;
  - regenerate `review-big-assembly.json`, checking that its snapshot part is 014's and its labels block 015's;
  - regenerate T007's golden on the first-merged side alone, and check that the merged code passes it unchanged.

  Then, where the recordings are, run research R2.28's replay regeneration step against 014's regenerated fixtures. A difference is a defect for the branch that caused it to explain or fix, never a fixture to regenerate in the merge. Acceptance: the gate green on the merge commit.
- [ ] T109 [py] Lane G. **Final gate** (quickstart, "The gate"; 62A). From `reviewer/`, run `SWREVIEW_REQUIRE_TOKENIZER=1 uv run pytest -q -p no:warnings -o addopts="" -m "not live"` and `uv run ruff check src tests`. From the repository root, run `dotnet build extractor/SwReview.sln -c Release --nologo -v q` (zero warnings) and `dotnet test extractor/SwReview.sln -c Release --no-build --nologo`. Then:
  - run research R2.28's replay regeneration step, expecting no difference, or skip it, naming why;
  - run quickstart Scenarios 1 to 7 by their commands.

  Record each outcome, with the outcomes of the phase gates (T031, T053, T073, T083, T101), in `specs/015-review-send-gate/quickstart.md`'s Results, in counts and words only. Acceptance: every command green.

**Checkpoint**: every record says whether its review was sent, the seat's step is placed, the contracts say what landed, the review is answered, and the gate is green.

---

## Phase W: The pilot workstation

**Purpose**: what only the seat can show (62A, SC-010). The result goes into the sitting's results sheet and its findings document, outside the repository; nothing from the seat is committed but the results' words.

- [ ] T110 [W] Lane S. Run quickstart Scenario 8 on the small assembly with the build of this feature and the owner's key stored (SC-010).
  1. Untick the box, then close and reopen SOLIDWORKS: the box is still unticked.
  2. Press Review. Record the waiting status, no Stop, and `not_sent` in the run folder's `session.json`.
  3. If the checks raise the part-roles question, answer it while the review waits. If they raise none, record that. If every finding the answer withdrew is in a folded family, record that too: the named-ids check then proves nothing about them.
  4. Press Send to model.
  5. Record:
     - zero model rounds before Send (every `usage` event follows `session.sent`);
     - one extraction in total;
     - that `model_status.opening_finding_ids` names none of the findings the answer withdrew;
     - whether the sentence carried a number (RK-9: whether `swreview tokenizer fetch` ran on the seat).
  6. Record two timings, from which RK-10's 10-minute bound is later set:
     - how long step 2's unticked `POST /sessions` took;
     - how long a re-run takes. Press Review again with the box still unticked, and wait until it waits. Save Settings, which restarts the backend. Press Send to model, and record how long the re-run before the first request took (between the host's "checking" and "ready" statuses, or from the backend log), and that the run folder still holds one extraction.

  Record no design name, number or path.

---

## Commit groups

Each group is one commit (two for T107's fixes if it has two findings). Each passes the gate on its own and is verified by the acceptance lines of its tasks. Test and implementation tasks share a commit, so no commit holds a red test. The two pins are committed alone, first, green on the pre-feature code. The gate tasks (T031, T053, T073, T083, T101) commit nothing.

| Group | Tasks | What lands |
|---|---|---|
| C01 | T001 | the amendment notes |
| C02 | T003-T004 | one recording provider |
| C03 | T005-T006 | the fictional questions package |
| C04 | T007 | the characterization of a ticked review (pre-feature code) |
| C05 | T008 | the prefix characterization (pre-feature code) |
| C06 | T009-T010 | `atomic.py` (only while 014 is not on `main`) |
| C07 | T011-T012 | the session fields and the 001 schema |
| C08 | T013-T014 | `local_now` |
| C09 | T015-T016 | `awaiting_send` |
| C10 | T017-T018 | `DeferredProvider` and `effort_mapping_for` |
| C11 | T019-T020 | `configure_provider` |
| C12 | T021-T022 | `request_prefix` moved |
| C13 | T023-T024 | `asks_same` |
| C14 | T025-T026 | `_render_run` |
| C15 | T027-T028 | the words and the pane fixture's labels |
| C16 | T029-T030 | the setting and its schema |
| C17 | T032-T033 | `start_review` unticked and its finalization |
| C18 | T034-T035 | the Send cache and the estimate |
| C19 | T036-T037 | the report header |
| C20 | T038-T039 | the unticked `POST /sessions` and `NotSent` |
| C21 | T040-T041 | the summary's `send` block |
| C22 | T042-T043 | the routes carry the block |
| C23 | T044-T045 | the box's host message |
| C24 | T046-T047 | `review.start` passes the value; the long timeout |
| C25 | T048-T049 | the two waiting fixtures |
| C26 | T050-T051 | the page: box, waiting state, Send block |
| C27 | T052 | the layout acceptance |
| C28 | T054-T055 | `has_credential` |
| C29 | T056-T060 | the Send route, Send, the first round, `session.sent` (one commit: the route's success path calls `run.send`, which T060 adds) |
| C30 | T061-T062 | a failed Send and the guard |
| C31 | T063-T064 | the decision and timing hold |
| C32 | T065-T066 | `failed_send` in the fixtures |
| C33 | T067-T068 | the page's Send |
| C34 | T069 | the layout with a failure line |
| C35 | T070-T071 | the replay's refusals |
| C36 | T072 | SC-006 over the recordings |
| C37 | T074 | `_apply_answers` (refactor) |
| C38 | T075-T076 | answers while waiting |
| C39 | T077-T078 | the restated pre-run and the opening rebuilt |
| C40 | T079-T080 | an apply that fails |
| C41 | T081-T082 | "Apply answers" on the page |
| C42 | T084-T085 | the carried live step |
| C43 | T086-T087 | the claim, the rotation, the adoption |
| C44 | T088-T089 | the carry |
| C45 | T090-T091 | the restored block |
| C46 | T092-T093 | the restored fixtures |
| C47 | T094-T095 | `review.recheck` in the host |
| C48 | T096-T097 | the found review after a reopen |
| C49 | T098-T099 | the page's restored flow |
| C50 | T100 | the layout of a restored review |
| C51 | T102-T103 | the handoff's model status |
| C52 | T104-T105 | the seat step placed |
| C53 | T106 | the contracts as landed |
| C54 | T107 | the adversarial review's fixes |
| C55 | T108 | the 014 merge (conditional) |
| C56 | T109 | the gate's Results |

---

## Dependencies & Execution Order

### Phase dependencies

- **Setup** (T001; T002 done): no dependency.
- **Foundational** (T003-T031): T007 and T008 are committed first, on the pre-feature code, before any task edits `reviewer/src/`. The phase blocks every story.
- **US1** (T032-T053): needs the Foundational phase. This is the MVP.
- **US2** (T054-T073): needs US1 (a waiting review to send).
- **US3** (T074-T083): needs US1. Its "kept at Send" and opening cases need US2's `send` (T060, T062).
- **US4** (T084-T101): needs US1 to US3. The carry reuses `_apply_answers` (T074) and reads what an apply failure leaves (T079-T080).
- **Polish** (T102-T109): after the stories. T108 only when 014 is on `main` first.
- **Workstation** (T110): after T109, on a build of this branch on the seat.

### User story dependencies

- **US1 (P1)**: independent once the Foundational phase is done.
- **US2 (P2)**: builds on US1's waiting review, and is testable on its own: Send a fixture review.
- **US3 (P3)**: builds on US1, and on US2 for the cases that press Send.
- **US4 (P3)**: builds on US1 to US3. Both P3 stories are in this order because the carry needs US3's apply.

### Task-level dependencies

- T004 and T006 come before T007. T007 and T008 are committed before T010 and every later task that edits `reviewer/src/`.
- **Foundational pieces before their users**:
  - T008 before T022.
  - T010 before T012.
  - T012 before T033, T060 and T089 (the writers of the fields).
  - T014 before T033 and T060.
  - T016 before T039.
  - T018 before T020 and T039.
  - T020 before T060.
  - T022 before T035.
  - T024 before T089.
  - T026 before T039.
  - T028 before T041 and every page task.
  - T030 before T045 and T047.
- **US1**:
  - T033 before T035, T035 before T039, and T039 before T043 and T057.
  - T037 before T039: T038 reads the report header T037 renders, so C19 (the header) lands before C20 (the unticked start).
  - T041 and T043 before T049; T049 before T050-T052.
- **US2**:
  - T055 before T057, and T057 before T060, in one commit (C29: the route calls `run.send`, which T060 adds).
  - T060 before T062; T062 before T066; T066 before T067-T069.
- **US3**:
  - T074 before T076 and T089; T076 before T078 and T080.
  - T078 completes the waiting branch T076 starts (the restated `_prerun` and the rebuilt opening), so T078 before T089, whose carry rebuilds the opening.
  - T080 before T088 (it reads what an apply failure leaves).
- **US4**:
  - T085 before T087, and T087 before T089.
  - T087 before T090 (its failed re-runs).
  - T091 before T093; T093 before T096 (`review-not-sent-session.json`) and T098.

### Parallel opportunities, by lane

| Lane | Tasks | Runs beside |
|---|---|---|
| G (pins, fixtures, gates) [py] | T003-T008, T031, T048-T049, T053, T065-T066, T073, T083, T092-T093, T101, T108, T109 | its pins first and alone; its fixtures once the backend they play has landed |
| R (records, report, words) [py] | T009-T012, T027-T028, T036-T037, T040-T041, T070-T071, T090-T091, T102-T103 | B, H, W |
| B (backend, runner) [py] | T013-T026, T032-T035, T038-T039, T042-T043, T054-T064, T072, T074-T089 | R, H, W; its hot files edited in task order |
| H (host, settings) [C#] | T029-T030, T044-T047, T094-T097 | every lane |
| W (page) [page] | T050-T052, T067-T069, T081-T082, T098-T100 | the backend lanes, once the fixture it reads exists |
| C (contracts) [doc] | T001, T106 | none: first and last |
| S (seat) [py] [doc] | T104-T105, T110 | every lane |

**Hot files, edited in this order and never in parallel**:
- `agent/runner.py`: T020, T022, T033, T035, T043, T060, T062, T074, T076, T078, T080, T085, T089.
- `chat/server.py`: T026, T039, T043, T057, T064, T087, T089, T091.
- `app.js`: T051, T068, T082, T099.
- `ReviewHost.cs`: T045, T047, T095, T097.
- `test_runner_send.py`: T013, T019, T032, T034, T058, T061, T077.
- `test_send_gate_server.py`: T025, T038, T042, T056, T059, T061, T063.
- `test_recheck.py`: T084, T086, T088.

### Parallel examples by story

- **Foundational**: T003, T005 and T008 are written together. After T007, T009, T011, T013, T015, T017, T021, T023, T025, T027 and T029 are all separate files and can be written together. Their implementations follow in commit-group order.
- **US1**: T032, T036, T038, T040, T044, T046 and T048 together (seven files across lanes B, R, H and G). Then T050 once T049 is in.
- **US2**: T054, T056, T058, T065, T070 and T072 together; the lane B implementations are serial. Then T067 once T066 is in.
- **US3**: T075 and T081 together.
- **US4**: T084, T092 and T094 together. T090 after T087 (it reads T086's failed re-runs); T096 and T098 after T093.

---

## Implementation Strategy

### MVP first (User Story 1)

1. Setup (T001), then the two pins on the pre-feature code (T003-T008).
2. The rest of the Foundational phase (T009-T031).
3. US1 (T032-T053).
4. **Stop and validate**: on a fictional fixture with no key, an unticked review runs the checks, saves itself, shows its findings and waits, and nothing reaches a provider (quickstart Scenarios 1 and 5). The engineer already has the option the owner asked for, whose fallback is to press Review again with the box ticked.

### Incremental delivery

1. US2 adds the approval: Send, and its size.
2. US3 keeps the work done while the review waits.
3. US4 makes the wait survive a restart, including the Settings save that enters the key Send needs.
4. Polish closes it with the review and the gate, and T110 checks it on the seat.

Each story ends with its gate and leaves a ticked review byte-identical to the pre-feature code (T007).

---

## Requirement coverage

| Requirement | Tasks |
|---|---|
| FR-001 | T050-T052 |
| FR-002 | T029-T030, T044-T047, T050-T051 |
| FR-003 | T046-T047, T050-T051 |
| FR-004 | T030 (the lever guard unedited) |
| FR-005 | T050-T052, T069, T100 |
| FR-006 | T032-T033, T038-T039 |
| FR-007 | T017-T018, T038-T039 |
| FR-008 | T034-T035, T038-T039, T042-T043 |
| FR-009 | T032-T033 |
| FR-010 | T032-T033, T038-T039, T079-T080 |
| FR-011 | T032-T033, T058, T060 |
| FR-012 | T034-T035, T040-T041, T050-T051, T072 |
| FR-013 | T021-T022, T034-T035, T075-T078 |
| FR-014 | T058-T060, T077-T078 |
| FR-015 | T059-T060 |
| FR-016 | T054-T057, T061-T062 |
| FR-017 | T061-T062, T065-T068, T077 |
| FR-018 | T056-T057, T063-T064, T067-T068 |
| FR-019 | T038-T039, T050-T051, T059-T060, T067-T068 |
| FR-020 | T074-T076, T079-T082 |
| FR-021 | T075-T078, T088-T089 |
| FR-022 | T075-T076 |
| FR-023 | T077-T078 (its last sentence included: none of the wait's lines sent again) |
| FR-024 | T063-T064, T075-T076, T088-T089 |
| FR-025 | T038-T039, T050-T051, T056-T057 and T063-T064 (a stop during a held write or a failed build leaves no stop behind) |
| FR-026 | T050-T051 |
| FR-027 | T044-T045, T050-T051 (the line, live), T098-T099 (the line, restored, and the re-run's line) |
| FR-028 | T084-T089, T094-T095 |
| FR-029 | T023-T024, T088-T089 |
| FR-030 | T096-T097 (the search; a found review that `review.recheck` accepts), T098-T099 (`sessions.list` asked again on `document.changed`; the found review restored and sent) |
| FR-031 | T090-T091, T098-T099 |
| FR-032 | T011-T012, T036-T037, T058-T062, T088-T089 |
| FR-033 | T050-T051, T081-T082, T098-T099 |
| FR-034 | T027-T028, T040-T041, T050-T052 |
| FR-035 | T007, T008, T027-T028, T038, T059, T061 (a ticked first request that fails), T067, every task's "T007 byte-equal", T109 |
| FR-036 | T011-T012, T029-T030, T032-T033 |
| FR-037 | T032 (the defaults, and the command-line review's printed lines), T007, `test_cli.py` unedited |
| FR-038 | T001, every "Amends" task, T106 |
| FR-039 | T005-T006, T048-T049, T092-T093, T105, T107, T110 |
| FR-040 | T070-T071 |
| FR-041 | T086-T087, T090-T091, T098-T099 |
| FR-042 | T098-T099 |
| SC-001 | T038, T050, T075, T086, T088, T107 |
| SC-002 | T038 |
| SC-003 | T007, T027-T028, T048-T049, T109 |
| SC-004 | T034, T059, T061, T077 |
| SC-005 | T077-T078 |
| SC-006 | T072 |
| SC-007 | T052, T069, T100 |
| SC-008 | T084-T089 |
| SC-009 | T036-T037 |
| SC-010 | T077 (the fixture half), T110 |

---

## Notes

- **Where these tasks depart from the plan's delivery order** (defaults taken 2026-10-09; the owner may revise each):
  - `ReviewPageDriver.cs`'s two replies land with the first page test that reads each one (T050 and T098), not as a Foundational task of their own.
  - `PrerunResult.named_finding_ids()` lands in US1, with the Send cache that holds it (T035), not in US3.
  - `model_status.profile` is recorded by the first run (T033), so every waiting record carries what a re-run compares.
  - The backend's `NotSent` refusal of a follow-up lands in US1 (T039), since FR-019 is US1's acceptance.
  - `recheck` is parsed, and its `400`, tested only in US4 (T086).
  - The page's restore after a failed apply is tested in US4 (T098), because it reads the restored fixture.
  - The status-line test is renamed once, without a count (T050).
  - One more generated file, `Fixtures/review-not-sent-session.json` (T092), is the backend-written record for the host's cross-language head read (research R4.2).
  - The 2 s bound on the found-review search is a plain `[Fact]`, since the add-in tests carry no perf trait (T096).
  - The phase gates commit nothing.
- **Between T039 and T076**, an answer to a waiting review reaches `_ask`, and the deferred provider refuses it (`ProviderNotSent`). That fails the chat, with nothing sent, so SC-001 holds at every commit. The branch is not released between stories, and US3 closes the gap.
- **Between T076 and T078**, an answer applied while a review waits rebuilds the Send cache from the frozen opening, and `_prerun` is not yet restated, so a Send in that window would send an opening that may name a finding code withdrew, and a size that does not count the regrade. Nothing is sent before Send, so SC-001 holds; T078 closes the window inside US3, before its gate (T083).
- A task's "Cause" is file:line at `838b66b`, which equals this branch's product code until the first task that edits `reviewer/src/` (T010, or T012 when 014's `atomic.py` is on `main` first); re-verify before editing.
- "Amends NNN" means the task writes that contract's amendment text in the same commit as the code. T001 placed the one-line note first.
- No task reads a run folder, a recording (T072 and the regeneration step read them only where the owner's mapping is, and print percentages and pass/fail only), a real profile, or the seat's results. Every committed fixture is generated from fictional builders.
- Merge note with feature 014: research R3's table, and T108 when 014 is on `main` first. Otherwise 014's branch reconciles at its own merge, using the same table.
