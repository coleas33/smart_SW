# Feature Specification: The Engineer's Workspace

**Feature Branch**: `009-engineer-workspace`

**Created**: 2026-09-23

**Status**: Draft (User Stories 1 and 2 landed on main 2026-09-23)

**Amended**: 2026-09-23 by the owner (decision 2A): a finding's title is whole and names its parts only where a person reads it; the title the model reads in every tool result is unchanged (FR-027, research R2.28).

**Input**: Owner direction of 2026-09-22: "We also need to improve the UI and make this easier for a non developer user to gain value from. The goal is to get all the critical details to the user as fast and clear as possible." Evidence: the pilot workstation's evening sitting (`docs/pane-findings-2026-09-20-review-gui.md`, asks U8 to U16) and `docs/roadmap-2026-09-22.md`. Owner decisions: modelling-practice findings as one folded group (2026-09-22); size-for-size contacts as a separate list, not findings; summary wording "Decide / Fix / Verify" (both 2026-09-23).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - The Review on Screen Is the Model on Screen (Priority: P1) - LANDED

An engineer reviews an assembly, then opens one of its parts. The assembly's findings no longer stay painted under the part's name: the review hides itself, its report and folder buttons and the follow-up are disabled, and one line says which document it belongs to. Returning to the assembly brings it back. A Clear review control empties the pane without opening anything. The header shows the file name rather than a clipped path. Model check and Standards follow the same rule. The Remodel tab says in plain words that Remodel is not in this build yet, instead of naming a console command.

**Why this priority**: accepting, rejecting or showing a finding against the wrong model is worse than showing nothing.

**Independent Test**: landed in commit `2c48e2b` with `ReviewPageDocumentBindingTests` and `CheckPageDocumentBindingTests`: review A, activate B - results hidden and actions disabled; back to A - restored; Clear review empties the pane and is refused while a turn runs.

**Acceptance Scenarios**:

1. **Given** a finished review of document A, **When** document B becomes active, **Then** A's results are hidden, Open report, Open run folder and the follow-up are disabled, and the pane says "This review is of A [configuration]. Press Review to review B [configuration]."
2. **Given** results hidden for another document, **When** A becomes active again, **Then** the results and actions return unchanged.
3. **Given** any finished review, **When** the engineer presses Clear review, **Then** the pane is empty and nothing was opened or started; while a turn runs, Clear review is refused.
4. **Given** the Remodel tab on a build without the remodel capability, **When** it opens, **Then** it says "Remodel is not in this build yet. This tab will not change the open part." and names no command.

---

### User Story 2 - Findings Read as a List, and Every One Is Reachable (Priority: P1) - LANDED

After a review the engineer sees each finding as one headline - its id and title - with the evidence, the explanation and the actions in its fold. Clicking a Start-here row scrolls to the finding without opening it. Collapse all closes every fold. Past the top five, every other issue is one click away in policy order behind "Show all N issues (M findings)", and a count line says how many issues and findings are not in Start here.

**Why this priority**: on the big assembly 94 of 99 findings had no path to them, and the five that did were paragraphs.

**Independent Test**: landed in commits `cf3c66e` and `b5cfcb4`: a finding card's head holds only its id line and title; a Start-here click leaves the fold closed and flashes the card; the sixth and later rows appear only after "Show all", in the supplied order.

**Acceptance Scenarios**:

1. **Given** a review with findings, **When** Results is shown, **Then** each finding is one headline and its evidence is inside the fold.
2. **Given** a ranking of 18 issues holding 99 findings, **When** Start here renders, **Then** it shows five issues, a count line "Start here: 5 of 18 issues" with the findings not in Start here, and a "Show all" control listing the other 13 in the supplied order.

---

### User Story 3 - The Engineer Knows What Matters in Ten Seconds (Priority: P2)

At the top of the results the engineer reads one short summary, in plain words, before any list: how many findings in how many issues; how many **need your decision** (only an engineer can settle them, such as a possible press fit), how many are **to fix** (shown by the checks), how many are **to verify** (suspected, or evidence missing); how many questions the review has for them; how many parts were not loaded; and, for each check goal - interference, fasteners, hole alignment, fits and stacks, tool access, mass and material, hygiene, drawings - whether it was checked with no issue, found issues, or was not reached, and why in a few words. Modelling-practice findings appear as one collapsed group with their counts, and size-for-size contacts as one folded contact list. Wherever a part has a name, the name is shown instead of an internal id.

**Why this priority**: a non-developer engineer needs the verdict and the decisions that are theirs before anything else. Everything below the summary is detail they can open.

**Independent Test**: render a review of the fixture shaped like the 830-02342 run: the summary reads, in order, the finding and issue counts, the three groups with their counts, the questions, the parts not loaded, and one line per check goal with its state; the modelling-practice findings are one collapsed group; the zero-volume contacts are one folded list; no component id appears where a component name exists.

**Acceptance Scenarios**:

1. **Given** a finished review, **When** Results opens, **Then** the summary is the first block and states the counts the backend computed, in the backend's words, with no count computed by the page.
2. **Given** findings the ranking marks as needing judgement, demonstrated, and suspected or unresolved, **When** the summary renders, **Then** they are counted under "Decide", "Fix" and "Verify" respectively, and already-decided findings are counted separately.
3. **Given** a check goal whose family produced no coverage and no finding, **When** the summary renders, **Then** that goal reads "not reached" with the reason recorded for it, never "checked".
4. **Given** modelling-practice findings, **When** Results renders, **Then** they are one collapsed group reading "Modelling practice: N findings across M rules", and opening it lists every one.
5. **Given** size-for-size contacts, **When** Results renders, **Then** they are one folded list apart from the findings, each naming the two parts.

---

### User Story 4 - Questions for You (Priority: P3)

When the review needs something only the engineer knows - which drawing governs a part, whether a pin is meant to be a press fit, which surface is the datum - the question appears above Start here as one short question at a time, with fixed answers to pick from when the review offered them, a free-text answer otherwise, and "Skip for now". The engineer answers some or all and sends them together; the pane says before sending what resuming the review will cost. A skipped question stays unresolved and nothing is filled in for it.

**Why this priority**: every evening review asked for drawings and fit intent in long paragraphs nobody answered, and each answer would have cost a full turn. Questions are how the review reaches what it cannot see.

**Independent Test**: a scripted review with three open questions shows "Question 1 of 3" above Start here; answering two, skipping one and sending posts one submission and resumes one turn; the skipped question remains open; the pane showed the estimated cost before sending.

**Acceptance Scenarios**:

1. **Given** open questions, **When** Results renders, **Then** the first appears above Start here as a short question with its offered answers or a text box, and a pager says which of how many it is.
2. **Given** the engineer answers some questions and skips others, **When** they send, **Then** one submission carries only the answered ones, the review resumes once, and the skipped ones stay open and unresolved.
3. **Given** answers are ready, **When** the send control is shown, **Then** it states the approximate cost of resuming, from the last round's measured size.
4. **Given** the submission is refused because a question was answered meanwhile, **When** the refusal arrives, **Then** nothing is recorded and the pane says which question.

---

### User Story 5 - Results or Transcript, Not Both (Priority: P4)

A two-way switch at the top of the Review tab chooses what owns the pane. **Results** shows the summary, the questions, the findings index and headlines, the not-loaded warning, what was not reached, and the follow-up box. **Transcript** shows the chronological record: the reviewer's prose and every tool call with its detail, and the round and token counts. A follow-up answer appears in Results as a pinned answer block, so the engineer never has to switch to read it.

**Why this priority**: results answer "what is wrong"; the transcript answers "how the reviewer got there". Stacked in a 300 px strip, each makes the other worse, and the transcript is where developer vocabulary belongs.

**Independent Test**: a scripted review renders Results by default with no tool card or prose visible; switching to Transcript shows every tool card and prose block in order and hides the results; a follow-up answer appears in Results as a pinned block without switching.

**Acceptance Scenarios**:

1. **Given** a review, **When** Results is selected, **Then** no tool call, JSON argument or token count is visible.
2. **Given** Transcript is selected, **When** it renders, **Then** every tool call and prose block appears in the order it happened, with the round and call counts.
3. **Given** a follow-up question, **When** the answer arrives, **Then** it is pinned in Results under the question that produced it.

---

### User Story 6 - One Review per Model, Kept (Priority: P5)

A normal session is an assembly, then a pin, then a plate. Each review is kept as a chip under the header naming its document, configuration and time. Choosing a chip brings that review back as it was, without a new review and without spending tokens. After the backend restarts, a review is brought back from its run folder, marked read-only when its live conversation is gone. Switching configuration inside one document also hides a review of another configuration.

**Why this priority**: without it, starting the second review throws the first away, or the first haunts the second.

**Independent Test**: review A, then B; the chips name both; choosing A restores A's summary, ranking and findings exactly; restarting the backend and choosing A restores it read-only with the reason shown; changing configuration inside A hides A's results.

**Acceptance Scenarios**:

1. **Given** two finished reviews in this session, **When** the engineer chooses one chip, **Then** that review's results render exactly as they were, and actions act on its model.
2. **Given** a review whose live conversation is gone, **When** its chip is chosen, **Then** it renders from its run folder, the follow-up and dispositions are disabled, and the pane says why.
3. **Given** a review of configuration X, **When** configuration Y of the same document becomes active, **Then** the review hides as it does for another document.

---

### User Story 7 - Plain Words Everywhere the Engineer Looks (Priority: P6)

Everywhere in the engineer's default view, internal vocabulary gives way to words: status, bucket and reason words come from labels the backend supplies; check ids and component ids move into the fold as "rule …" and "part …"; errors say what to do rather than naming an error class; titles are no longer cut at 80 characters but wrap to two lines, and name parts rather than ids (the title the model reads stays as recorded, owner decision 2A of 2026-09-23); Model check shows rule statements rather than a fraction and rule ids. Nothing is lost - every id and number is still in the fold, the transcript and the report.

**Why this priority**: it is what makes the rest usable by someone who is not a developer, and it is done inside the stories above rather than as a separate pass.

**Independent Test**: a scan of the default Results view of the fixture review finds no component id where a name exists, no raw status token, no check id outside a fold, and no error class name.

**Acceptance Scenarios**:

1. **Given** the default Results view, **When** it is scanned, **Then** it holds no raw status token, no check id outside a fold and no component id where the part has a name.
2. **Given** a backend error, **When** it is shown, **Then** it says what the engineer can do next.

---

### Edge Cases

- **An older backend.** A result without the summary, labels or questions renders exactly as today, with no empty block.
- **A review with no findings.** The summary says so in words and still lists which goals were checked and which were not reached.
- **Hundreds of findings.** The summary counts them all; the findings index is virtualised or paged so the pane stays responsive, in the supplied order.
- **Questions with no offered answers.** A text box is shown; an empty answer cannot be sent.
- **A question answered from another window.** The submission is refused atomically and the pane says which question.
- **A chip whose run folder is gone.** The chip says the review can no longer be restored and offers to remove it.
- **Configuration switch while a turn runs.** The review hides but Stop stays enabled, as for a document switch.
- **The summary wording.** "Decide", "Fix" and "Verify" come from the backend's labels, so a later wording change is a data change.
- **No page-side ranking.** Every count, group and order in these stories comes from the backend; the page prints and slices, never sorts or compares.

## Requirements *(mandatory)*

### Functional Requirements

**Landed (User Stories 1 and 2)**

- **FR-001**: The Review tab MUST hide a finished review, disable its report, folder and follow-up actions, and name the reviewed document when a different document is active, and restore it when the reviewed document is active again. *(landed)*
- **FR-002**: The Review tab MUST offer Clear review, refused while a turn runs. *(landed)*
- **FR-003**: Model check and Standards MUST apply the same document binding to their results. *(landed)*
- **FR-004**: The Remodel tab MUST describe an unavailable capability in plain words and name no command. *(landed)*
- **FR-005**: Each finding MUST default to a one-line headline with its evidence, explanation and actions in its fold; a Start-here click MUST scroll to the finding without opening it; Collapse all MUST close every fold. *(landed)*
- **FR-006**: Every issue in the ranking MUST be reachable in the supplied order, the first five as Start here and the rest behind a "Show all" control, with a count line of issues and findings not in Start here. *(landed)*

**The summary (User Story 3)**

- **FR-007**: The backend MUST compute a review summary: finding and issue counts; counts of findings needing the engineer's decision, to fix, to verify, and already decided, by the ranking's own keys; open questions; parts not loaded; and one state per check goal (checked, issues found, not reached, not applicable) with a short reason.
- **FR-008**: The summary's group labels MUST be supplied by the backend, reading "Decide", "Fix" and "Verify" (owner decision 2026-09-23).
- **FR-009**: The page MUST render the summary first in Results and compute no count, group or order itself.
- **FR-010**: Modelling-practice findings MUST render as one collapsed group with the counts of findings and rules, listing every finding when opened.
- **FR-011**: Size-for-size contacts MUST render as one folded list separate from the findings, each naming both parts (owner decision 2026-09-23).
- **FR-012**: Wherever a component has a name, the default view MUST show the name rather than the component id.

**Questions (User Story 4)**

- **FR-013**: The review MUST be able to ask a question in a short form (at most 140 characters), with up to five offered answers and the check goal it blocks, in addition to today's longer description.
- **FR-014**: Open questions MUST appear above Start here one at a time with a pager, their offered answers or a text box, and "Skip for now".
- **FR-015**: Answers MUST be sent together as one submission that resumes the review once; skipped questions MUST stay open and unresolved; nothing may be filled in for an unanswered question.
- **FR-016**: Before sending, the pane MUST state the approximate cost of resuming, from the last round's measured input size.

**Results or Transcript (User Story 5)**

- **FR-017**: The Review tab MUST offer a two-way switch between Results and Transcript, each owning the pane.
- **FR-018**: Results MUST show no tool call, argument or token count; Transcript MUST show every prose block and tool call in order with the round and call counts.
- **FR-019**: A follow-up answer MUST be pinned in Results under its question.

**Sessions (User Story 6)**

- **FR-020**: Every finished review in the SOLIDWORKS session MUST be kept as a chip naming its document, configuration and time, and choosing it MUST restore its results without a new review.
- **FR-021**: A review whose live conversation is gone MUST be restorable read-only from its run folder, with the reason shown and follow-up and dispositions disabled.
- **FR-022**: A configuration switch within the reviewed document MUST hide a review of another configuration.
- **FR-023**: Show in SOLIDWORKS MUST resolve against the review currently shown, never against whichever run happened to be latest.

**Plain words (User Story 7)**

- **FR-024**: Status, bucket and reason words in the default view MUST come from backend-supplied labels.
- **FR-025**: Check ids and component ids MUST appear only inside folds, the transcript and the report.
- **FR-026**: Errors MUST say what the engineer can do next.
- **FR-027**: Finding titles as the engineer reads them - on the Review tab, in the check tabs' Start here and in `report.md` - MUST not be truncated at a fixed character count and MUST name a part rather than its id where the part has a name; the page clamps them to two lines. The title the model reads in every tool result MUST stay as recorded, so no tool result and no replayed round changes (owner decision 2A, 2026-09-23, research R2.28).
- **FR-028**: Model check MUST show rule statements rather than the verdict fraction and rule-id lists.

**Constraints**

- **FR-029**: Every page colour, face and size MUST come from the shared token stylesheet; no page script may sort or compare severities or statuses; every string MUST reach the page through the shared text helper.
- **FR-030**: A result from a backend without the new fields MUST render as it did before this feature.

### Key Entities

- **Review summary**: counts of findings and issues; the Decide, Fix, Verify and decided groups with their counts and top checks; open questions; parts not loaded; one state and reason per check goal; component names by id.
- **Check goal**: one of the owner's goals (interference, fasteners, hole alignment, fits and stacks, tool access, mass and material, hygiene, drawings), mapped to the checklist items and check families that serve it.
- **Question**: a short question, offered answers, the goal it blocks, the longer description, and its state (open, answered, skipped).
- **Review chip**: document, configuration, time, the conversation it belongs to, and whether it can resume or is read-only.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: On the fixture shaped like the 830-02342 review, the summary, the three decision groups and the not-reached goals are readable without scrolling in a 300 by 600 pane.
- **SC-002**: A non-developer engineer shown that review can say, within ten seconds, how many decisions are theirs and which check goals were not reached.
- **SC-003**: The default Results view of that review contains no component id where a name exists, no raw status token, no check id outside a fold, and no error class name.
- **SC-004**: Answering three questions costs one resumed review turn.
- **SC-005**: Returning to an earlier review in the same session takes one click and spends no tokens.
- **SC-006**: Every finding of a 99-finding review is reachable in at most two clicks from the top of Results.
- **SC-007**: On the next workstation sitting, the engineer confirms the summary names the decisions that were theirs and the goals the review did not reach, on both recorded assemblies.

## Assumptions

- The backend computes every count, group, label and order; the page renders them verbatim, consistent with the rule that no page script ranks or compares.
- The answer batch and the modelling-practice folded group are built by feature 008; this feature renders them.
- The size-for-size contact list is produced by feature 010's interference change; this feature renders it when present.
- The check goals are the owner's list of 2026-09-22; mapping each goal to checklist items and check families is a backend table, so a goal added later is a data change.
- Restoring after a backend restart reads the run folder on disk and writes nothing to it.
- The pane is 260 to 420 px wide and loads no webfont; the design system's three tiers of ink apply.
