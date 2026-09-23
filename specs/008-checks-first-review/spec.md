# Feature Specification: Checks-First Review and the Token Budget

**Feature Branch**: `008-checks-first-review`

**Created**: 2026-09-22

**Status**: Draft

**Input**: Owner direction of 2026-09-22 after the pilot workstation's evening packet (`docs/pane-findings-2026-09-20-review-gui.md`) and the analysis recorded in `docs/roadmap-2026-09-22.md`: "Token usage is way too high, we gotta get more efficient." Decided the same day: model-facing payload slimming, checks first, history pruning and parallel tool calls all become pane defaults, gated by an offline replay of the recorded runs; modelling-practice findings appear in Review as one folded group.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - The Owner Can Price a Review Before Anyone Pays for It (Priority: P1)

The owner wants to know what a change to the reviewer will do to the bill and to the findings before it reaches a workstation. They point one command at a run folder the workstation sent back, and it replays that review's calls through the current code, with no key and no SOLIDWORKS, and prints the tokens every round would cost now, the total, the findings the replay produced, and how both compare with what the recorded review actually spent and found.

**Why this priority**: every other story is a claim about tokens and findings. Without an offline price, each claim needs a licensed seat and a paid review to check, and neither is available on the development machine. The replay is the gate the owner chose for making the other changes defaults.

**Independent Test**: replay the committed fixture shaped like the recorded 830-02342 run with every change off: the per-round tokens match the recorded ones within 1%, and the finding set matches exactly. Replay it again with the changes on: the tokens fall and the finding set still contains every recorded finding.

**Acceptance Scenarios**:

1. **Given** a review run folder holding the session and its event log, **When** the owner replays it, **Then** the command prints, per round, the input tokens the recorded review billed and the input tokens the current code would send, the two totals, and the difference, and exits successfully without contacting any provider or SOLIDWORKS.
2. **Given** a recorded call whose result cannot be reproduced offline (a live SOLIDWORKS call, or a check that needed a profile the replay does not have), **When** it is replayed, **Then** its size is taken from the recorded round-over-round growth, the round is labelled estimated, and the total says how many rounds were estimated.
3. **Given** the replay produces the findings of the current code, **When** it finishes, **Then** it names every recorded finding the replay no longer produces and every new finding it produces, each by check and subject, and exits with failure when any recorded finding is lost.
4. **Given** a folder that is not a review (a check folder with no event log, or a folder with no session), **When** it is replayed, **Then** it refuses with one sentence naming what is missing.

---

### User Story 2 - Code Runs Every Check It Can Before the Model Speaks (Priority: P2)

An engineer presses Review. Before the first model turn, the checks that need no judgement to start have already run: the modelling-practice rules for every part, the equations, the assembly mates, the release standards when a profile is configured, and, when SOLIDWORKS is attached, the live interference detection with every detected group judged. The model opens on a short digest of what the checks found and what they could not evaluate, and spends its turns explaining, asking the engineer, and looking into what no check can scope. The modelling-practice findings appear in the review as one folded group per rule family rather than dozens of separate rows.

**Why this priority**: 90 of the 99 findings on the big assembly came from checks that take no arguments, and the model drove each of them one call at a time, reading payloads of up to 205k tokens. Running them in code costs no model rounds, produces the same findings every time, and is where the product's constitution says verdicts belong.

**Independent Test**: start a review on the fixture package with a fake bridge that returns interference rows: before the provider is asked anything, the session holds the modelling-practice, equation, assembly, standards and interference findings as real steps with real events; the model's first message contains the digest; the interference rows are in the run folder's package; and the modelling-practice findings appear as one group in the report and the ranking.

**Acceptance Scenarios**:

1. **Given** a review starts, **When** the first model turn begins, **Then** every argument-free check has already run through the same dispatch the model would use, each as a recorded step with its start and finish events, findings and coverage, before the first provider request.
2. **Given** SOLIDWORKS is attached, **When** the checks run first, **Then** the live interference detection runs once for the reviewed configuration, every detected group is judged, and the detected rows are written into the run folder's package so a re-render reproduces the same findings.
3. **Given** SOLIDWORKS is not attached, or no standards profile is configured, **When** the checks run first, **Then** the family that could not run appears in the digest and in coverage with the reason, and the review still starts.
4. **Given** the checks ran first, **When** the model is asked to check the same family again, **Then** it is answered with the recorded result's digest rather than a second run that would duplicate findings.
5. **Given** a review with modelling-practice findings, **When** its report and ranking are rendered, **Then** those findings appear as one group per rule family with the count of findings and rules, collapsed, with every finding still listed inside it, and the model is told only the counts.

---

### User Story 3 - The Model Reads a View; the Run Folder Keeps the Record (Priority: P3)

The engineer never sees a difference in what the review records: every finding carries the same references, inputs and evidence as today, and every tool result is kept in full in the run folder. What changes is what the model reads. Internal reference strings the model never uses are left out of its view; check results reach it as a digest with a way to fetch one finding in full; long lists of gaps are grouped by reason; and a tool result the model read one or two rounds ago is replaced in its view by a short stub that says what it was and how to fetch it again.

**Why this priority**: 95.7% of every request on the big assembly was earlier tool output resent in full. The model needs to have read a result once, not re-read it forty times.

**Independent Test**: replay the fixture with slimming and pruning on: every result older than the configured number of rounds appears to the model as a stub; the full payload of every result is in the run folder; the session's findings are byte-identical to a run with slimming and pruning off; and the replayed total falls by at least the amount stated in the success criteria.

**Acceptance Scenarios**:

1. **Given** a tool result carries internal reference strings, **When** it is shown to the model, **Then** they are absent from the model's view and present, unchanged, in the package, the session and the report.
2. **Given** the two bridge tools that act on an entity, **When** the model calls them, **Then** they accept the short entity id the model was shown, and resolve it to the internal reference without the model ever handling it.
3. **Given** a check tool runs, **When** its result reaches the model, **Then** the model reads a digest - how many findings of each status and severity, their ids, how many subjects - and can fetch any one finding's full detail by id, while the session records every finding in full exactly as before.
4. **Given** a tool result has been in the model's view for more than the configured number of rounds, **When** the next request is built, **Then** that result is replaced by a stub naming the tool, its arguments, its counts and the entity ids it returned, identical every time for the same result, and its full payload is in the run folder under the step's number.
5. **Given** a result was replaced by a stub, **When** the model needs its detail again, **Then** it can fetch it by calling the tool again or, for a finding, by fetching the finding, and the stub says so.

---

### User Story 4 - A Question or an Answer Costs One Small Turn (Priority: P4)

After a review, the engineer asks a follow-up question, or answers the questions the review asked. Today one short question on the big assembly resent 405k tokens, and each answer to each question was a separate turn of the same size. With this feature a follow-up carries the conversation's stubs rather than its payloads, several answers go back together as one turn, and the model issues independent calls together instead of one per round.

**Why this priority**: follow-ups and answers are how an engineer gets value after the first pass, and they are where a non-developer will spend most of their interaction. They must be cheap enough that nobody hesitates to ask.

**Independent Test**: on the replayed big-assembly fixture, a follow-up question's request is under the success-criteria budget; answering three open questions in one submission produces one resumed turn and three answered records; and a scripted model that issues four independent queries in one turn produces one round, not four.

**Acceptance Scenarios**:

1. **Given** a finished review, **When** the engineer asks a follow-up, **Then** the request carries the stubs of earlier results, not their payloads.
2. **Given** several open questions, **When** the engineer sends answers to some or all of them together, **Then** every id is validated before anything changes, all are recorded as answered, and the review resumes once; an unknown or already-answered id refuses the whole submission and changes nothing.
3. **Given** the model issues several independent calls, **When** the provider supports parallel calls, **Then** they run as one round and are recorded as separate steps in a deterministic order, while calls into SOLIDWORKS still run one at a time.

---

### User Story 5 - The Cost Is Reported Honestly (Priority: P5)

The engineer and the owner see what a review cost in terms they can act on: how many input tokens were new and how many were served from the cache, how many rounds, and which steps were the largest. The pane's usage line and the report say the same thing.

**Why this priority**: the pilot reports showed a headline of 12.4M tokens when 407k were new. A number that overstates cost by an order of magnitude drives the wrong decisions, and a number that hides where the cost went cannot be improved.

**Independent Test**: a scripted review whose provider reports cached and uncached input produces a session, report and usage line that state both, and a session whose steps record their result size in bytes and tokens.

**Acceptance Scenarios**:

1. **Given** the provider reports cached input, **When** usage is shown, **Then** new and cached input are shown as separate numbers, and a provider that does not report the split shows the total with "cache split not reported".
2. **Given** a review finishes, **When** its session is written, **Then** every step records the size of the result it produced, in bytes and in estimated tokens, and the report names the five largest.

---

### Edge Cases

- **A recorded run from older code.** Tool names or arguments in the recording that the current code does not know are replayed as estimated rounds from their recorded size and named in the output; the replay never fails silently on them.
- **Checks-first and a model that asks anyway.** A model that calls a check the pre-run already ran gets the recorded digest, never a second run, so findings are not duplicated.
- **Thousands of interference groups.** Live detection on a large assembly can return many groups; every group is judged in code, and the digest states the count by outcome rather than listing them.
- **Live detection fails or times out.** The failure becomes a failed coverage row naming the reason, the review starts, and the model is told interference was not evaluated.
- **A pruned result the model needs again.** The stub names how to fetch it; a re-fetch is an ordinary recorded step. Findings are never re-derived from a stub.
- **Stub determinism.** The same result always produces the same stub, so the cached part of the request up to the previous result is reused.
- **Pruning and the digest.** The opening digest and the engineer's own messages are never pruned; only tool results are.
- **Parallel calls into SOLIDWORKS.** Bridge calls run one at a time even when the model issues them together, because SOLIDWORKS answers on one thread.
- **Gemini and parallel calls.** Gemini already issues parallel calls; the setting changes nothing there, and the session records which provider did what.
- **A batched answer with one bad id.** The whole submission is refused and nothing is recorded; the engineer is told which id.
- **Sessions written before this feature.** New fields in the session are optional; older sessions load, render and replay.
- **The replay on a check folder.** Check folders have no event log and no provider rounds; the replay refuses them with that reason.
- **Token counting across providers.** The replay counts with one tokenizer; for a Gemini recording it compares shapes, not exact counts, and says so.

## Requirements *(mandatory)*

### Functional Requirements

**The replay**

- **FR-001**: The product MUST offer a command that replays a review run folder's recorded tool calls, in recorded order and grouped into the recorded rounds, through the current code and settings, with a scripted provider, and reports per-round and total input tokens for the recording and for the replay.
- **FR-002**: The replay MUST need no provider key, make no network call and require no SOLIDWORKS.
- **FR-003**: The replay MUST count tokens with one named tokenizer over exactly the serialization the adapters send, and state the tokenizer in its output.
- **FR-004**: A recorded call the replay cannot reproduce MUST be sized from the recorded round-over-round growth, labelled estimated, and counted in a total of estimated rounds.
- **FR-005**: The replay MUST report the finding set (check and subject) of the recording and of the replay, name every finding lost and every finding added, and exit with failure when any recorded finding is lost.
- **FR-006**: The replay MUST offer a machine-readable output alongside the human one, and refuse a folder that is not a review with one sentence naming what is missing.
- **FR-007**: Committed fixtures for the replay MUST be shaped like the recorded 810-11249 and 830-02342 runs with fictional names and paths; the recorded runs themselves never enter the repository.

**Checks first**

- **FR-008**: Before the first provider request of a review, the product MUST run every argument-free check - modelling practice for every part, equations, assembly, standards when a standards run is attached, and interference when a live SOLIDWORKS connection exists - through the same dispatch the model uses, producing recorded steps, start and finish events, findings and coverage.
- **FR-009**: With a live connection, the product MUST run interference detection once for the reviewed configuration, judge every detected group, and write the detected rows into the run folder's package.
- **FR-010**: A family that cannot run MUST appear in coverage and in the opening digest with its reason, and MUST NOT stop the review.
- **FR-011**: The model's first message MUST carry a digest of the checks' outcomes by family and of what could not be evaluated, and MUST NOT carry the checks' payloads.
- **FR-012**: A model call to a check family the pre-run already ran MUST be answered with the recorded digest and MUST NOT produce findings again.
- **FR-013**: Checks first MUST be the pane default; the former separate pre-run settings are folded into it, and the command line keeps a way to turn it off for comparison.
- **FR-014**: Modelling-practice findings MUST appear in the ranking and the report as one group per rule family with the counts of findings and rules, collapsed, with every finding still present; the model MUST be told only the counts.

**The model's view**

- **FR-015**: Internal reference strings MUST be omitted from every tool result the model reads and MUST remain unchanged in the package, the session and the report.
- **FR-016**: The bridge tools that act on an entity MUST accept the short entity id the model was shown and resolve it server-side; an id that does not resolve MUST be an error result naming the id.
- **FR-017**: Tool results MUST be serialized compactly for the model.
- **FR-018**: Check tools MUST return a digest to the model (counts by status and severity, finding ids, subject counts, capped with the omitted count stated), and the product MUST offer a tool that returns one finding's full detail by id. The session MUST record every finding in full exactly as before.
- **FR-019**: The gap listing MUST group rows by reason with counts and sample ids, stating how many rows each group holds.
- **FR-020**: A tool result that has been in the model's view for more than a configured number of rounds (default 2) MUST be replaced in the request by a deterministic stub naming the tool, its arguments, its counts and the entity ids it returned, and saying how to fetch the detail again.
- **FR-021**: The full payload of every tool result MUST be written to the run folder under the step's number, before any stub replaces it.
- **FR-022**: Pruning MUST apply identically in both provider adapters and between turns, and MUST NOT touch the system prompt, the opening digest or the engineer's messages.
- **FR-023**: Slimming and pruning MUST be pane defaults, each with a command-line way to turn it off for comparison.

**Asking and answering**

- **FR-024**: Parallel tool calls MUST be the pane default for providers that support them; calls into SOLIDWORKS MUST still run one at a time; parallel calls MUST be recorded as separate steps in a deterministic order.
- **FR-025**: The product MUST accept several answers to open evidence requests in one submission, validate every id before changing anything, record each answer separately, and resume the review once; an unknown or already-answered id MUST refuse the whole submission and change nothing. The single-answer route stays.

**Cost reporting**

- **FR-026**: Every recorded step MUST carry the size of its result in bytes and in estimated tokens.
- **FR-027**: The usage line and the report MUST show new and cached input separately when the provider reports the split, and say "cache split not reported" when it does not; the report MUST name the five largest steps.

**Compatibility**

- **FR-028**: Every new session field MUST be optional; sessions and packages written before this feature MUST load, render and replay.
- **FR-029**: No finding's content, and no ranking outside the folded modelling-practice group, may change as a result of this feature; the existing golden reports and rankings MUST stay byte-identical except where the folded group appears.

### Key Entities

- **Replay report**: one recorded review re-priced by current code - per round the recorded and replayed input tokens and whether the round was estimated; totals; the tokenizer; the recorded and replayed finding sets with the lost and added findings.
- **Check digest**: what the model reads from a check - family, counts by status and severity, finding ids, subject counts, omitted counts.
- **Result stub**: what replaces an older tool result in the model's view - tool, arguments, counts, returned entity ids, how to fetch again; deterministic for a given result.
- **Stored tool result**: the full payload of one step, kept in the run folder under the step's number.
- **Folded rule group**: the modelling-practice findings of one rule family, with the counts of findings and rules, collapsed, holding every finding.
- **Answer batch**: several answers to open evidence requests submitted together and recorded one by one, resuming one turn.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: With every change off, the replay of the fixtures shaped like the recorded runs reproduces the recorded per-round input tokens within 1% and the recorded finding set exactly.
- **SC-002**: With the pane defaults on, the replay of the 830-02342-shaped fixture sends under 1.0M input tokens in total, against 12.4M recorded, and loses no recorded finding.
- **SC-003**: With the pane defaults on, the replay of the 810-11249-shaped fixtures sends under 0.3M input tokens each, against about 1.5M recorded, and loses no recorded finding.
- **SC-004**: A follow-up question after the 830-02342-shaped review costs under 30k input tokens, against 405k recorded.
- **SC-005**: Answering three open questions together costs one resumed turn, not three.
- **SC-006**: On a review with a live connection, every detected interference group is judged, against 6 of 113 on the recorded run.
- **SC-007**: The session's findings are identical, finding by finding, with the changes on and with them off, apart from the folded modelling-practice group's presentation.
- **SC-008**: Every tool result of every review can be read in full from the run folder after the review, including those the model saw only as a stub.
- **SC-009**: The usage line and the report of a review on a provider that reports cached input show new and cached input as two numbers.
- **SC-010**: On the next workstation sitting, a paid review of each of the two recorded assemblies costs no more than 1.5 times the replay's estimate, and produces at least the findings of the recorded review.

## Assumptions

- The recorded evening dumps (`%LOCALAPPDATA%\SwReview\handover\2026-09-20-gui\dumps`) are the reference runs; committed fixtures are derived from their shapes and sizes with fictional names and paths, because the dumps carry document paths.
- One tokenizer (the one the OpenAI models in use count with) is close enough to price both providers' requests for a comparison; the replay states the tokenizer and treats Gemini recordings as shape comparisons.
- The default pruning age is two rounds, the safer of the one or two rounds the owner allowed; one round is a setting.
- Parallel tool calls become the pane default by owner decision on 2026-09-22, superseding the earlier rule that no pane default changes before a held-out design; the lever 6 study on the one real design (-67.5% tokens, same findings) is the evidence.
- The Task Pane changes that present these results (the summary, the folded group's controls, the questions panel) belong to feature 009, except the usage line.
- The model's cached-input price is unknown here; cost is reported in tokens, new and cached separately, not in currency.
- No licensed SOLIDWORKS seat is available on the development machine; everything here is verified with fake bridges, fake providers and the replay, and SC-010 waits for the next sitting.
