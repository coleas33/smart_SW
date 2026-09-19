# Feature Specification: Attention Policy and Procedural Gate

**Feature Branch**: `007-attention-policy-gate`

**Created**: 2026-09-18

**Status**: Draft

**Input**: User description: "We need to make decisions about which details are worth amplifying in priority from the reviewer and checks. How can we agentically review the assembly after the procedural reviews? When should we implement this? What is next steps and implementation order?" (owner, 2026-09-18), against the workstation record `docs/pane-findings-2026-09-18.md` and the review, model-check and extract results it reports. The design was decided in conversation on 2026-09-18: the owner chose a judgement-first ranking over consequence-first and over no judgement key; chose to build the gate as an eleventh efficiency lever rather than a plain switch or a change to lever 5; chose to claim, at the 2026-10-03 pilot checkpoint, the pane working end to end, timing recorded on every run and the ranking on the report and the two keyless tabs, and not to claim the gate or the model brief; and chose this spec package as the next artifact, after the two pane bugs the record names were fixed as their own commits. The event-stream bug is fixed (`b3cb948`); the drawing-attach bug is being fixed in parallel and is a dependency of User Story 4 only.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Engineer Minutes Are Recordable on Every Real Run (Priority: P1)

The pilot is judged on net engineer minutes saved per design. Today no real run can record them: the only writer of the four human inputs - baseline minutes, assisted supervision minutes, assisted verification minutes, false-alarm handling minutes - resolves a run folder layout that only the benchmark harness produces, so every report from the pane or the command line prints "Net saved minutes: unknown", and the adoption ledger has no column for the median. After this story the engineer records the four inputs for any run folder - a pane review, a command-line review, a model check, a standards check - from the command line, and for a review the pane started also through the backend (check runs register no chat, so they are timed from the command line); the report's Timing section prints the derived net figure, and the ledger reports the median as a column that is read, not gated on.

**Why this priority**: It is half a day, it depends on nothing else in this feature, and it is the only work in the package that touches the number the pilot is judged on. Until it lands, every claim that a better-ordered report saved engineer minutes is unfalsifiable, and the checkpoint is fifteen days out. It is deliberately first and alone.

**Independent Test**: Record four inputs against a committed fixture run folder from the command line and confirm the re-rendered report prints a real net figure; record the same four through the backend route against a pane-shaped folder and confirm the same; attempt to record a negative minute count and confirm the refusal names the field; attempt to supply the net figure directly and confirm it is refused because it is derived; confirm the benchmark harness's existing timing path still passes unchanged through the shared writer; confirm the ledger row carries the median column and that the adoption decision is unchanged by it. No SOLIDWORKS licence and no key are needed.

**Acceptance Scenarios**:

1. **Given** a review run folder written by the pane, **When** the engineer records baseline 45, supervision 6, verification 9 and false alarms 2 from the command line, **Then** the run's session records those four values, `report.md` is re-rendered and its Timing section prints the derived net saved minutes, and the value is not accepted as an input anywhere.
2. **Given** the same folder, **When** the four inputs are recorded through the backend route, **Then** the outcome is identical to scenario 1, byte for byte in the session and the report.
3. **Given** any input below zero, **When** it is recorded, **Then** the recording is refused with a message naming the field and no file is changed.
4. **Given** a folder that holds no session, **When** the engineer records timing against it, **Then** the recording is refused naming the folder, and nothing is created.
5. **Given** a run whose four inputs were already recorded, **When** they are recorded again, **Then** the new values replace the old ones and the report is re-rendered; the earlier values are not silently kept.
6. **Given** the adoption ledger, **When** a row is computed over runs of which some carry timing and some do not, **Then** the median net saved minutes column is computed over the runs that carry it, states how many were counted, and never turns an adoption decision by itself.

---

### User Story 2 - The Engineer Reads the Right Findings First (Priority: P2)

A review of a four-component dowel-pin assembly on 2026-09-18 produced eight findings, six at medium and two at low, and the report showed the six mediums in the order the tools happened to run. The two interference findings - the only rows on that assembly no tool can close, because a pin in a reamed hole is often an intended press fit that only the engineer can confirm - sat third and fourth. The 39 unresolved and 11 skipped coverage items, the larger fact of that run, were a paragraph. After this story every report opens with a "Start here" section: the top five findings by one explicit, deterministic attention policy, each with the reason it ranks where it does; a line accounting for what was not amplified; and a coverage block stating what the run could not reach. The order is reproducible from the recorded session alone, and a record beside the session says which version of the policy produced it. A keyless command prints the same ranking for any existing run folder without writing, so the owner can argue with the policy against real findings before it ships anywhere.

The policy is a total order with no weights and no scores. In order: findings that are suppressed sort last (a status of checked within scope, which is what a live waiver rewrites a finding to and what a clean numeric pass carries, or a disposition of accepted or rejected; they are rendered in full, never removed); among the rest, findings that need the engineer's judgement sort first (the interference, fit, fastener and hole check families, a declared set); then a consequence class from a checked-in, versioned table that maps every check the product can emit to exactly one of `rebuild_breaker`, `interface`, `manufacturing`, `unclassified`, `discipline`, `hygiene` (a check the table does not name sorts as `unclassified`, in the middle, and is printed by name so the omission is visible); then status (demonstrated before suspected before unresolved); then severity; then reach (the count of distinct components a row names, capped, more first); then a finding carried over from a previous session sorts below an otherwise identical fresh one; then the check id and the finding id, so two rankings of the same session are identical whatever order the findings were recorded in. A finding whose disposition is deferred, and a finding whose waiver is marked for re-review because its fingerprint moved, keep competing for attention: neither has been decided.

Before ranking, repeated conditions fold into one row: findings that share check, status and severity and name disjoint subjects become one row listing every member, except that a check in the needs-judgement set never folds, because two press fits may be two different intents and collapsing them would be a judgement the policy made silently. The fold is recorded in the ranking and in the record beside the session; it writes nothing to the session's findings, which are byte-identical before and after.

**Why this priority**: It is the owner's question. It is pure reasoning-side code, competes with no pane fix for files, and its value is observable this week on the report every surface already writes. It is second only because a better-ordered report whose minutes are not measured cannot be claimed.

**Independent Test**: Rank a committed session shaped like the 2026-09-18 review and confirm the top five are the two interference rows, mates to reference geometry, the under-defined sketch and the grouping rule, in that order, with the missing-folders row last of eight; rank the same session with its findings shuffled and confirm the rendered section is byte-identical; rank a session shaped like the 2026-09-18 model check and confirm the under-defined sketch leads; confirm the two existing golden reports are byte-identical when no ranking is supplied; confirm the catalogue test fails when a check id the product emits has no consequence class; confirm the policy module imports no provider, no settings and no network code. No licence, no key.

**Acceptance Scenarios**:

1. **Given** the 2026-09-18 review session (two interference findings on two pins, five RMS rule findings at medium, two at low), **When** it is ranked, **Then** "Start here" lists interference on pin A, interference on pin B, mates to reference geometry, the under-defined sketch, and the grouping rule, each with a one-line reason naming the key that placed it, and the missing-folders row is last of the eight.
2. **Given** the same session with its findings in reverse order, **When** it is ranked, **Then** the rendered section and the record are byte-identical to scenario 1.
3. **Given** the 2026-09-18 model-check session (three findings, all RMS rules), **When** it is ranked, **Then** the under-defined sketch leads, then grouping, then missing folders, and the section says the run graded a part with no assembly checks in scope.
4. **Given** a session with an accepted finding, a rejected finding, a waived finding and a deferred finding, **When** it is ranked, **Then** the first three sort below every undecided finding and are still rendered in full in the Findings section, and the deferred finding competes on its own keys.
5. **Given** two interference findings with disjoint subjects, **When** the session is ranked, **Then** they are two rows, never one group; **Given** twelve grouping findings on twelve different parts with equal status and severity, **Then** they are one row listing twelve members, and the session's findings are byte-identical to before.
6. **Given** a finding whose check id appears in no consequence-class table, **When** it is ranked, **Then** it sorts as `unclassified` between `manufacturing` and `discipline`, its reason line names the check id and says it is unclassified, and the catalogue test that enumerates every emittable check id fails until the table names it.
7. **Given** a session with zero findings, **When** it is ranked, **Then** the section says in words that there is nothing to start with and the coverage block still states what was and was not reached; **Given** a session whose every finding is informational, **Then** the section lists no rows and the not-amplified line counts them.
8. **Given** a finished session's record of the ranking, **When** the ranking is recomputed from the session alone, **Then** it reproduces the record exactly, including the policy version.
9. **Given** any existing run folder, **When** the keyless attention command is run against it, **Then** it prints the policy table and the ranked rows, constructs no provider, reads no key and writes no file.
10. **Given** the report is rendered with no ranking, **When** it is compared with the two golden reports, **Then** both are byte-identical to today.
11. **Given** a report rendered with a ranking, **When** it is compared with its own golden fixture, **Then** the "Start here" section's wording, row format, reason lines, not-amplified line and coverage block match it byte for byte, and no finding is absent from the severity sections below.

---

### User Story 3 - The Ranking Reaches Every Surface the Engineer Reads (Priority: P3)

The report is rendered from eight places: the review command line, the pane after every turn and after a stop, after every disposition, after every waiver, the model check, the standards check, the session store and the extract path. A "Start here" section written by one of them and erased by the next turn is worse than none. After this story every render carries the ranking, the record beside the session is written on the review path (including a run that failed) and on both check paths without changing how a check folder is told apart from a review folder, the check and standards results the backend returns carry the ranking so the two keyless tabs can show it, the contracts that define those results are amended, and the pane renders the ranking above the bucket chips on the Model check and Standards tabs and as a pinned panel above the Review transcript when the session ends - fetched from the backend and computed nowhere in the page. A Review panel for a session that failed before its first finding says so rather than showing an empty list.

**Why this priority**: The two keyless tabs work today, produced three of the day's eleven findings, and are not behind any pane bug; the Review panel is behind the event-stream fix, which has landed. This is the slice of the checkpoint claim the engineer sees without opening a file.

**Independent Test**: Render a fixture session through each of the eight paths and confirm the section is present and identical after each; disposition a finding and confirm the re-rendered report still opens with the section; run a model check and a standards check on fixture packages and confirm both results carry the ranking and neither path constructs a provider; load each page offscreen with a scripted host and confirm the ranking rows appear in the order the backend supplied and that no page script contains a severity order or a band rule; end a session that produced no findings and confirm the Review panel states it. No licence; no key for any check-tab path.

**Acceptance Scenarios**:

1. **Given** a pane review that has produced findings, **When** the next turn ends, a stop is requested, a finding is dispositioned or a waiver is accepted, **Then** the re-rendered report opens with the same "Start here" section, recomputed over the session as it now stands.
2. **Given** a review that fails after recording some findings, **When** it is finalized, **Then** the report and the ranking record are both written over the findings that exist, and the record says the session was cut short.
3. **Given** a model check or a standards check run from its tab, **When** the result is returned, **Then** it carries the ranking, the contract for that result names the field, and the path constructs no provider and reads no key.
4. **Given** the Model check tab or the Standards tab showing a result, **When** the page renders, **Then** the ranked rows appear above the bucket chips in the order supplied, each with its reason line, and the page scripts contain no rule that could reorder them.
5. **Given** the Review tab, **When** the session ends, **Then** a pinned panel above the transcript shows the ranking fetched from the backend; **Given** the session ended before its first finding, **Then** the panel says there is nothing to start with and why.
6. **Given** an RMS check folder that a review later claims, **When** the review writes its ranking record, **Then** the check's record is rotated aside with the check's session rather than overwritten, and the folder is still recognised as a review folder.
7. **Given** any check-tab path, **When** the provider factories are made to fail, **Then** the tab's result is unchanged, proving the ranking touched no provider.

---

### User Story 4 - The Procedural Gate: The Model Starts Where the Checks Stopped (Priority: P4)

Today the model chooses what to investigate from a system prompt and a checklist, and rediscovers what the deterministic checks already know: on the 2026-09-18 run it reached the same three RMS conclusions the model check reached in one tool call, then found interference and the equation rules. An existing pre-run (feature 005, lever 5, off by default, never measured) runs the RMS and interference families before the first model turn and prepends a digest. After this story a new lever, `procedural_gate`, default off, widens that pre-run to run the standards checks too when a profile is configured, ranks the results with the User Story 2 policy, and makes the ranked top five plus three lists the first message the model reads: the findings that need the engineer's judgement, what the run could not reach, and what the rules structurally cannot see (one line per family the pre-run could not evaluate, backed by a skipped coverage item). The message carries one instruction: these verdicts are computed from checked code; do not re-derive them; spend your rounds on what was not reached. The model contributes prose and targeted tool calls into the families no enumerator can scope - fasteners, hole alignment, fit, axial stack; it contributes nothing to the rank, and no tool accepts one. No new event type is added; the gate's tool calls, findings and coverage arrive on the stream as they already do. Adoption follows feature 005's ledger: six alternated runs off and on, the named regression that the per-run counts of fit and axial-stack calls must not fall between arms, and nothing becomes a default until the benchmark set has held-out packages.

Two guards land with it. The number guard: the one path on which the model authors text that becomes a claim in the report - a drawing finding - refuses, as an error the model may answer once, an observed or required value containing a number-like token that appears in none of the cited tool results, inputs or drawing locations. And the anti-drift test: the message the model receives and the report's "Start here" section name the same finding ids in the same order for one fixture session.

Written beside the policy are the preconditions for ever adding an agentic triage pass, so the question is answered by a rule rather than re-argued: only when the deterministic top five misses the finding that received the first accepted disposition in 30% or more of reviews over five designs, and the miss cannot be expressed as a new consequence class or rule, and assisted verification minutes exceed about ten per design, and net saved minutes is already positive.

**Why this priority**: It is the "agentically review after the procedural reviews" the owner asked for, built at zero extra provider round trips by reshaping a message that is already sent. It is last because its value is only judgeable in a pane that shows a finished review, because its standards half waits on the real profile (feature 006 T100) and on the drawing-attach fix, and because nothing about it can be claimed at the checkpoint on a one-package benchmark set. It is built now and shipped to no one.

**Independent Test**: Start a review with the gate on against a fixture package with a scripted provider and confirm the first user message holds the ranked rows, the three lists and the instruction; confirm the same run with the gate off produces the lever-5 digest byte for byte as today; confirm the anti-drift assertion; run with no profile and confirm a not-evaluated line and a skipped coverage item for standards; run with a profile and confirm standards findings close the standards checklist item and share the session with the RMS findings without contaminating either family's summary; confirm a drawing finding carrying "0.05 mm" is refused when no cited result carries it and accepted when one does; confirm the lever count assertions were updated in the same change; confirm no event type was added. No licence, no key.

**Acceptance Scenarios**:

1. **Given** the gate lever on and a package with RMS and interference evidence, **When** the review starts, **Then** the pre-run's tool calls, findings and coverage are recorded as real steps and events before the first model text, and the first user message opens with the ranked top five and the three lists, capped at five rows, five coverage prefixes and one reason clause per row.
2. **Given** the gate lever off, **When** the review starts, **Then** the first user message is exactly what lever 5 produces today, byte for byte, and lever 5's own arm is unchanged.
3. **Given** a standards profile configured, **When** the gate runs, **Then** the standards checks run in the same session, their findings close a standards checklist item, and the RMS and standards summary items do not contaminate one another; **Given** no profile, **Then** the message carries a not-evaluated line for standards backed by a skipped coverage item, and the review closes out honestly.
4. **Given** one fixture session, **When** the gate's message and the report's "Start here" section are compared, **Then** they name the same finding ids in the same order.
5. **Given** the model records a drawing finding whose observed value contains a number no cited tool result, input or drawing location carries, **When** the tool is called, **Then** it is refused as an error result naming the rule; **Given** the same text with a cited result carrying the number, **Then** it is accepted; **Given** a component id or a feature id in the text, **Then** it is accepted.
6. **Given** the lever is added, **When** the settings tests run, **Then** every place that pins the lever count was updated in the same change, the default is off, the lever is recorded whole on the session, and the pane exposes no control for it.
7. **Given** six alternated runs off and on over the benchmark set, **When** the ledger row is computed, **Then** the per-run counts of fit and axial-stack calls did not fall between arms, the count of gate-family tool calls the model made after the gate is recorded rather than assumed, and the row computes rather than being typed.
8. **Given** the provider fails partway through the first turn with the gate on, **When** the run finalizes, **Then** the gate's findings and coverage stand in the session and the report, and the ranking record is written.

---

### Edge Cases

**Ranking inputs**

- A session with zero findings and zero coverage (a setup failure): the section says nothing was evaluated, in words, and the record is still written.
- A session whose every finding is informational or suppressed: no rows in "Start here", a not-amplified line that counts them, and the coverage block.
- A finding with no component ids (a drawing finding names a sheet, not a component): reach is zero; it competes on the other keys and is never dropped.
- A finding that is both in the needs-judgement set and waived: suppressed, last; the waiver wins because the engineer already decided it.
- A finding carried over from a previous session that is otherwise identical to a fresh one: the fresh one first.
- A check id the table does not name: `unclassified`, printed by name; the catalogue test is the guard, not the report.
- Run-to-run variance: an earlier 77-second run on the same assembly produced six findings without the interference pair. The ranking never invents a row for a finding the run did not make; the variance belongs to measurement, and the coverage block states what was not reached so an absent row is visible as a gap rather than as a clean bill.
- Severity is not uniform across families: the rule families map every failure to medium and every warning to low, while the interference family assigns high above a volume threshold. The policy reads severity as recorded and never recomputes it.
- The Model check tab offers no assembly scope, so a model-check session never contains a needs-judgement finding; on that surface the consequence class is the leading key, and the spec says so rather than pretending the judgement key is exercised there.

**Folding**

- A needs-judgement check never folds, whatever the subject sets.
- Two findings that share a subject never fold.
- A single-occurrence condition gets no group.
- Folding buys nothing on the 2026-09-18 data, because the rule families emit one finding per rule per document however many subjects it names; its value appears on a multi-part assembly. The spec states this so no one illustrates the fold with a row it does not fold.

**Surfaces**

- A report rendered with no ranking is byte-identical to today; both golden reports prove it.
- Every one of the eight render paths carries the ranking; a test enumerates the call sites so a ninth cannot land unwired.
- A run that failed before its first finding: report and record are written over nothing; the Review panel says so.
- An RMS check folder later claimed by a review: the check's ranking record rotates aside with its session; the folder-kind rule is unchanged and tested. A standards check folder cannot be claimed by a review today (the folder-kind reader is RMS-only), and this feature leaves that as it is.
- A disposition or a waiver recorded from the command line against a standards folder: the re-render keeps the verdict header and uses the package beside the session, which the command-line disposition loses today.
- Both check families in one folder (a standards check after an RMS check, or the gate): one session, one ranking, each family's summary intact.
- No standards profile on a workstation: the Standards tab and the gate both say so up front; the profile-missing message itself is a pane fix outside this feature.
- The report opened from the pane is the pane's own render, so it opens with "Start here" too.

**Timing**

- A negative input is refused naming the field; a missing input leaves the previous value; the net figure is derived and refused as an input; a folder with no session is refused naming the folder; re-recording replaces.
- The benchmark harness's existing timing path is a thin wrapper over the shared writer and its tests pass unchanged.

**The gate**

- No key: the gate is off by default and is never reached from a keyless tab; when on, it needs the review's own provider and nothing else.
- The provider fails mid-turn: the gate's findings and coverage stand; the record is written on the failure path.
- The pre-run produces zero findings: the message says so and lists what was not reached; the model is still told not to re-derive.
- The message would exceed its cap: rows beyond five and prefixes beyond five are counted in the not-amplified line, never silently dropped.
- The model tries to re-derive a verdict in prose: the prose never enters the report, so it is not guarded; the guard is on the drawing-finding tool, the one path where model text becomes a claim, and the spec says the guard covers exactly that.
- The number guard and legitimate tokens: component ids, feature ids, sheet names and dates are accepted; the rule targets number-like measurements absent from every cited source.
- The gate's added wall clock before the first model token has never been measured on a large assembly; it is measured before the gate reaches the pane.

## Requirements *(mandatory)*

### Functional Requirements

**Timing (User Story 1)**

- **FR-001**: The engineer MUST be able to record baseline, assisted supervision, assisted verification and false-alarm handling minutes against any run folder that holds a session from the command line, and against a review the pane started through the backend.
- **FR-002**: Net saved minutes MUST be derived from the four inputs and MUST NOT be accepted as an input on any path.
- **FR-003**: A negative input MUST be refused naming the field; a folder without a session MUST be refused naming the folder; nothing is written on refusal.
- **FR-004**: Recording MUST re-render the report so its Timing section prints the derived figure; re-recording MUST replace the earlier values.
- **FR-005**: The benchmark harness's timing path MUST share one writer with FR-001 and its existing behaviour MUST be unchanged.
- **FR-006**: The adoption ledger MUST report median net saved minutes as a column stating how many runs carried timing, and MUST NOT gate an adoption decision on it.

**The attention policy (User Story 2)**

- **FR-007**: The product MUST rank a finished session's findings by a total order with no weights or scores: suppressed last; needs-judgement first; consequence class; status; severity; reach; carried-over last; check id; finding id.
- **FR-008**: Suppressed MUST mean a status of checked within scope (which is what a live waiver rewrites a finding to, and also what a clean numeric pass carries) or a disposition of accepted or rejected, and nothing else; suppressed findings MUST still be rendered in full. Deferred dispositions and waivers marked for re-review MUST NOT be suppressed, and the exception reference on a finding MUST NOT be read for this purpose, because it cannot tell the two apart.
- **FR-009**: The needs-judgement set MUST be declared in one place and MUST initially hold the interference, fit, fastener and hole check families.
- **FR-010**: The consequence-class table MUST be checked in, versioned, and map every check id the product can emit to exactly one of `rebuild_breaker`, `interface`, `manufacturing`, `unclassified`, `discipline`, `hygiene`; an unnamed id MUST sort as `unclassified` and be printed by name.
- **FR-011**: A catalogue test MUST enumerate every emittable check id from the product's own registries, including every constant of the fastener family, and fail when one has no class.
- **FR-012**: Repeated conditions MUST fold into one attention row listing every member when they share check, status and severity and name disjoint subjects; a needs-judgement check MUST never fold; folding MUST write nothing to the session's findings.
- **FR-013**: The report MUST carry a "Start here" section of at most five rows immediately above the Findings section, each row with a one-line reason naming the key that placed it, followed by a not-amplified line (counting checked within scope, already decided, informational, and beyond the top five) and a coverage block stating the bucket counts and the families most left unreached; no line of the section MUST contain a percent sign.
- **FR-014**: Ranking the same session twice, or with its findings shuffled, MUST produce byte-identical output.
- **FR-015**: The policy MUST live in one module that imports no provider, settings or network code, and MUST perform no I/O beyond loading its own table once.
- **FR-016**: The model MUST contribute nothing to the rank and no tool MUST accept a rank; no rank, score or confidence field MUST be added to a finding.
- **FR-017**: A keyless command MUST print the policy table and the ranked rows for any existing run folder without writing.
- **FR-018**: A golden fixture of a report rendered with a ranking MUST be kept; rendering with no ranking MUST leave the existing golden of the report renderer byte-identical.

**Surfaces (User Story 3)**

- **FR-019**: Every production render of the report MUST carry the ranking, and a test MUST enumerate the render call sites so a new one cannot land unwired.
- **FR-020**: A ranking record naming the policy version, the per-row key values, the groups, the not-amplified counts and the coverage block MUST be written beside the session on the review path, including a run that failed, and on both check paths.
- **FR-021**: Writing the record MUST NOT change how a check folder is told apart from a review folder, and a review that claims an RMS check folder MUST rotate the check's record aside with the check's session.
- **FR-022**: The model-check and standards results the backend returns MUST carry the ranking, and the contracts defining those results MUST be amended.
- **FR-023**: The Model check and Standards tabs MUST render the ranking above the bucket chips from the result they already hold, and the Review tab MUST render it as a pinned panel above the transcript when the session ends, fetched from a read-only session route that computes it from the live session and writes nothing; no page script MUST contain a severity order or a ranking rule.
- **FR-024**: The Review panel MUST state, for a session that ended before its first finding, that there is nothing to start with and why.
- **FR-025**: No check-tab path MUST construct a provider or read a key.

**The procedural gate (User Story 4)**

- **FR-026**: The gate MUST be an eleventh efficiency lever, `procedural_gate`, default off, and every place that pins the lever count MUST be updated in the same change; the pane MUST expose no control for it.
- **FR-027**: With the gate on, the pre-run MUST run the RMS, interference and, when a profile is configured, the standards families through the same tools the model receives, recording real steps, findings, coverage and stream events; without a profile it MUST emit a not-evaluated line backed by a skipped coverage item.
- **FR-028**: A checklist item for standards MUST exist so standards findings close something.
- **FR-029**: The first user message MUST hold the ranked top five, the three lists (needs judgement; not reached; structurally unseen, one line per not-evaluated family) and the do-not-re-derive instruction, capped at five rows and five prefixes with the remainder counted; it MUST NOT be placed in the system prompt.
- **FR-030**: With the gate off, lever 5's message MUST be byte-identical to today.
- **FR-031**: The message the model receives and the report's "Start here" section MUST name the same finding ids in the same order for one fixture session.
- **FR-032**: No new event type MUST be added.
- **FR-033**: The drawing-finding tool MUST refuse, as an error result the model may answer, an observed or required value containing a number-like token absent from the drawing evidence the cited locations name (dimension text, notes and annotations of the cited sheets), and MUST accept component ids, feature ids, sheet names, dates and values a cited sheet carries.
- **FR-034**: The gate MUST NOT be adopted as a default until six alternated runs are recorded on the ledger, the per-run fit and axial-stack call counts have not fallen between arms, and the benchmark set holds held-out packages.
- **FR-035**: The four preconditions for an agentic triage pass MUST be recorded beside the policy.

### Key Entities

- **Attention policy**: the versioned rule - the needs-judgement set, the consequence-class table, the key order and the fold rule - that produces a ranking from a session; one artifact with a version.
- **Attention row**: one ranked finding or group, with the values of each key that placed it and a one-line reason.
- **Ranking**: the top rows, the folded groups, the not-amplified counts and the coverage block for one session; what the report renders and the pane fetches.
- **Attention record**: the ranking as written beside the session, naming the policy version, reproducible from the session alone.
- **Timing inputs**: the four human minute counts recorded against a run; net saved minutes is derived from them.
- **Gate brief**: the first user message with the gate on - the ranked rows, the three lists and the instruction - derived from the session the pre-run wrote, never recomputed.
- **Consequence class**: one of six named classes assigned to every emittable check id.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: After landing, 100% of pilot runs can carry the four timing inputs and print a net saved minutes figure, and the ledger reports the median across designs.
- **SC-002**: The 2026-09-18 review session ranks with the two interference rows first, and the 2026-09-18 model-check session ranks with the under-defined sketch first, in committed tests.
- **SC-003**: Ranking a session and its shuffled copy produces byte-identical output in 100% of cases in the test suite.
- **SC-004**: The existing golden of the report renderer is byte-identical with no ranking; a golden report with a ranking is kept.
- **SC-005**: Every emittable check id has a consequence class; the catalogue test passes.
- **SC-006**: After a turn, a stop, a disposition and a waiver, the re-rendered report still opens with "Start here" in 100% of the fixture cases.
- **SC-007**: The keyless tabs construct no provider and read no key on any path with the ranking present, proven by tests that make the provider factories fail.
- **SC-008**: With the gate on, the number of provider round trips per turn is unchanged from the gate off.
- **SC-009**: The gate's message and the report's "Start here" section name the same finding ids in the same order for the fixture session.
- **SC-010**: Across six alternated runs, per-run fit and axial-stack call counts do not fall with the gate on.
- **SC-011**: At the 2026-10-03 checkpoint the pane works end to end, timing is recorded on every run, and the ranking is shipped on the report and the two keyless tabs; the gate and the brief are not claimed.

## Assumptions

- The event-stream bug is fixed (`b3cb948`); the Review tab's pinned panel depends on it. The drawing-attach bug is being fixed in parallel; only the standards half of the gate depends on it, because a standards run rooted on a drawing goes through the same attach.
- The 2026-09-18 run folders are not in the repository. They are copied off the pilot workstation before the policy read-through, and committed fixture sessions are shaped like them for the tests; the read-through with the owner against real findings happens before any surface ships the ranking.
- The owner records the four timing inputs from the command line after each pilot run for the checkpoint; a pane control for entering minutes is a follow-on, not part of this feature.
- The Model check tab offers no assembly scope, so it cannot exercise the judgement key; the report and the Standards tab can.
- Feature 006 T100, the real standards profile, is authored by the owner in parallel; until it lands, the gate reports standards as not evaluated and the Standards tab's verdicts mean nothing.
- The benchmark set holds one package with no held-out entry, so no adoption decision can be gated before the checkpoint; the gate is built behind its lever and measured later.
- The reach key is inert on a four-component assembly and is kept for larger ones; it is one lookup and one test.
- Prerequisite messages on the Standards and Remodel tabs, and the profile-missing wording, are pane fixes made outside this feature.
- Lever 5's own experiment (feature 005 T078/T079) has never been run; the gate gets its own lever precisely so that experiment is not redefined before it is performed.
- Severity is read as recorded; the policy never recomputes it, and the interference family's volume threshold and the rule families' high-severity override (every `rms.refs.*` rule and the over-defined sketch rule are already high) stay where they are. The committed fixture that pins the top five is built on rules outside that override, so the consequence key is proved on its own.
- The gate's standards half has three ways to be not evaluated, each a line and a skipped coverage item: no profile configured, a profile that cannot be loaded, and a package dumped without the standards phases. The spec's acceptance scenario names the first; the other two are tested alongside it.
