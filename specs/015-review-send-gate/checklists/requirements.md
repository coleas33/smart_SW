# Specification Quality Checklist: Send the Review to the Model Only When the Engineer Wants It

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-10-08
**Feature**: [spec.md](../spec.md)

## Content Quality

- [x] No implementation details (languages, frameworks, APIs)
- [x] Focused on user value and business needs
- [x] Written for non-technical stakeholders
- [x] All mandatory sections completed

## Requirement Completeness

- [x] No [NEEDS CLARIFICATION] markers remain
- [x] Requirements are testable and unambiguous
- [x] Success criteria are measurable
- [x] Success criteria are technology-agnostic (no implementation details)
- [x] All acceptance scenarios are defined
- [x] Edge cases are identified
- [x] Scope is clearly bounded
- [x] Dependencies and assumptions identified

## Feature Readiness

- [x] All functional requirements have clear acceptance criteria
- [x] User scenarios cover primary flows
- [x] Feature meets measurable outcomes defined in Success Criteria
- [x] No implementation details leak into specification

## Notes

- Validated 2026-10-08 in two passes. The first pass found three faults, all fixed in the spec:
  - FR-005 and SC-007 said "session controls" for the two-row rule. 60A's budget is the session *buttons*, and the box takes a line of its own directly under them (FR-001 defines "beside"), so both now say buttons.
  - The "sent" model status implied a new field on every review. A ticked review must record nothing new, or the pane fixture would move (SC-003), so the entity and FR-032 now say so.
  - SC-006 did not say which recordings it is measured on. It now names the real OpenAI recordings the replay reads, which are held outside the repository, with gaps recorded as percentages only.
- Revised 2026-10-08 after an adversarial review of the first draft. Every finding was checked against the code before it was fixed:
  - **Question 3's default changed what a ticked review does.** That contradicted 59A ("today's behaviour unchanged"), and its stated reason was false. Today a failed first request settles the chat to failed, and a failed chat refuses follow-ups. The opening is also already in the history before the request is made. The default is now today's behaviour (FR-035), and falling back to waiting is question 3's alternative. The Settings no-key note is reworded so it stays true with the box unticked.
  - **A restored not-sent review was read-only except for Send.** That froze the answers 61A says are regraded by code while the review waits, on the most common path into Send. The new default (question 4, FR-031) re-runs the review by code on its first answer, decision or Send.
  - **"No key stored" became "no usable credential"** (FR-016). It now covers a key from the environment, a Gemini enterprise project with no key, and the scripted provider. A checks-only review sets up no provider client at all (FR-007).
  - **The opening leaves out the line naming withdrawn findings** (FR-023, SC-005). Today's resumed message names them, and reusing it unchanged would break SC-005.
  - **The coverage comparison** of SC-002 and User Story 1 now expects the rows the end of the checks adds.
  - **SC-003 and FR-035 now cover the labels block.** The pane fixture carries the words file's whole labels block, so a new refusal's sentence adds keys there. Only the snapshot part stays byte-identical; the labels block may gain keys only, in a commit of its own.
  - **Drawing answers are carried across a restart** with their outcome lines (FR-029, SC-008). A re-run reads SOLIDWORKS no further (FR-028).
  - **The status-line state is page words**, and it takes precedence over "Waiting for your answers." (FR-033). FR-034 is scoped to the Send block and the summary.
  - **The Send sentence names the first request only.** Gemini shows no number, and the departure from feature 008's tokenizer contract is recorded (FR-012, FR-013).
  - **A Settings save is refused while answers are applied or a Send is in flight** (FR-027).
  - **"Answered" is defined** as one completed model round (FR-017).
  - **The replay refuses reviews that waited** (FR-040).
  - **The contract list is open-ended**, with the missing contracts added (FR-038).
  - **SC-001 excludes the Settings model-list check**, which carries no review content.
  - **SC-006 measures each recording's own first request.**
  - **SC-010 is observed through the Send record** (FR-032), and says what happens if no part-roles question is raised.
  - **Wording.** The backend is called "the backend", the pane's own word, and CAD is "the SOLIDWORKS model". "The model" means the LLM throughout.
- Revised again 2026-10-08 after a second adversarial review of the revision. Every finding was checked against the code before it was fixed (`prerun.py`, `chat/server.py`, `agent/runner.py`, `ReviewHost.cs`, `UserSettings.cs`, `TaskPaneControl.cs`, `app.js`, and the 008, 009, 011 and 013 contracts):
  - **The re-run after a restart had no defined live-detection outcome.** Under checks first, a session with SOLIDWORKS attached detects live as the pre-run's first call, and one without falls into the "not attached" row, which would be false for a review whose first run did detect. The re-run now carries the first run's outcome from the earlier record (line, coverage row, bucket, withheld tools), never detects again, and the review it sends has the live tools attached as any review of the active document does. A first run whose rows could not be written is said so, unresolved. 008 FR-008, FR-009, FR-030 and checks-first section 2 row 1 are named as departures (FR-028, FR-038, SC-008).
  - **The opening reused today's resumed-turn words**, which tell the model to re-run a check it never named and replace an entry it never made. The wait's lines now state each answer as already applied by code, keep 013's drawing outcome lines, and give no instruction; the exact words go to the plan's contract. One order is stated: brief, digest, the wait's lines, the usual opening (FR-014, FR-023, SC-005, Key Entities).
  - **Departures from earlier features were not all named.** FR-038 now lists, each with its departure: 001's session schema; 002 FR-006; 008 answer-batch section 1, checks-first sections 1, 2 and 7, cost, tokenizer and replay; 009 FR-015, FR-021, sessions section 5 and views sections 2 and 3; 011 confirmed-open section 1; 013 FR-040, drawing-capability section 6 and part-roles section 9. The "at least" hedge is gone.
  - **FR-019 covered ticked reviews**, whose failed first request would have shown a disabled follow-up box with a false sentence. It now covers only a review started unticked.
  - **Carried answers and decisions were matched by nothing stated.** Ids are sequential per session, and a drawing read before a restart moves both finding and question numbers in the re-run. Answers are now matched by what the question asks, decisions by what the finding says (check, parts, drawing places, configuration), never by number; ambiguous matches are named (FR-029, SC-008).
  - **A re-run was not work in flight.** A save could restart the backend part way through it, and a failed or cut-off re-run would have left a folder the pane can no longer restore, because today's retry moves the old record aside before any check runs. FR-041 refuses the save and every action while a re-run runs, adds a status-line state, and keeps the earlier record as the restored one when the re-run fails.
  - **A waiting review on screen at a restart** would have answered its next action with an unknown-chat error. FR-042 moves it to the restored state at once.
  - **Gemini showed no number.** 59A makes no exception and 008 labels a Gemini count rather than hiding it, so the number is shown and called approximate (FR-012).
  - **Smaller fixes:** "beside" is defined so a test can check it (FR-001); a box change during a review's checks is saved when the host is next free, because the host handles messages one at a time (FR-002, US1-5); a bad box value no longer costs the rest of the settings file (FR-002); the restored line and the chip name the date the checks ran (FR-030, FR-031); the Send block's place in Results and its exception to "no token count" are stated (FR-034); the lookup after SOLIDWORKS reopens has a bound and a test (FR-030); SC-009 keeps a ticked review's report as today's; Remodel can use a model (its start is off in this build) and the tab is "Ask", not "Terminal", and the Ask tab is stated to be outside Send.
- No [NEEDS CLARIFICATION] marker was written. The run had no interactive owner, so every open question is settled by a default taken 2026-10-08, listed in Assumptions as one the owner may revise. Three defaults change what gets built and were put to the owner, each marked where it applies:
  - question 2: how a not-sent review comes back after SOLIDWORKS reopens (FR-030; 61A requires that it can);
  - question 3: whether a ticked review keeps today's failures or falls back to waiting (FR-035);
  - question 4: whether a restored not-sent review stays usable through a code-only re-run or is read-only until Send (FR-031).
  Question 1 of the first draft (carrying answers and decisions across a restart) is withdrawn because 61A decides it.
- Every edge case the brief named is in Edge Cases with its behaviour decided:
  - no usable credential, with the box ticked and with it unticked, and what counts as usable (an environment key, a Gemini enterprise project);
  - the box changed while a review runs, including while the host is busy with its checks;
  - Stop while a review waits;
  - Send with no usable credential, and a provider error at Send;
  - the follow-up box and question answers while a review waits;
  - Accept, Reject and Defer while a review waits;
  - a Settings save while a review waits (allowed; refusing it would leave no way to enter the key Send needs), and refused while answers are applied or a Send is in flight;
  - a backend crash, a crash while answers are applied, and SOLIDWORKS closed;
  - a restart with the waiting review on screen, a re-run running, and a re-run that fails or is cut off;
  - live interference across a re-run, and finding and question numbers that move across one;
  - switching documents;
  - Retry;
  - restoring a waiting review from its run folder, a snapshot or a reload;
  - Review pressed again;
  - the explanation pass;
  - the report and the saved record;
  - the replay and the recording reader;
  - the command-line review (unchanged, recorded as decided);
  - the pane and replay fixtures, including the labels block.
- On "implementation details": the spec names the product's own vocabulary where the engineer or the owner meets it. That covers the Review tab and its status line, the kept reviews and their chips, the questions panel, the run folder, the pre-run digest, the pane and replay fixtures, and the contracts FR-038 says must move. These are the feature's subject, as in features 008 to 013, not a choice of technology. Modules, routes, states and file paths belong in `plan.md` and `research.md`.
- When each criterion is measured: SC-001 to SC-005 and SC-007 to SC-009 on fixtures, with no licence and no network; SC-006 on the replay's real recordings on the development machine; SC-010 at the pilot workstation sitting (the [W] task of 62A).
- Scope: the Review tab's send decision only. Model check, Standards, Remodel and the Ask tab are out of scope, and so is the command-line review. What a sent review carries is unchanged, and the parked question of what may leave the machine stays open.
