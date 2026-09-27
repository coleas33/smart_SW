# Feature Specification: Engineer-First Review

**Feature Branch**: `013-engineer-first-review` (worked on `main`)

**Created**: 2026-09-26

**Status**: Draft. Every question the analysts raised is settled by a default taken on 2026-09-26, which the owner may revise (research R2; none is the owner's own words).

**Numbering**: this feature is numbered 013 on purpose. Number 012 stays reserved for drawing creation, as `docs/roadmap-2026-09-22.md` ("012 Drawing creation (later)") and feature 011 (`specs/011-drawing-context/spec.md`, Input and FR-043) say; nothing in this package creates, changes or prepares to write a drawing.

**Input**: The 2026-09-26 sitting on the pilot workstation - the first on the checks-first build (features 008 to 011) - and its debrief, which is held outside this repository because it carries company data (items F1 to F8 and the update table U17 to U24; nothing is copied from it here). Six analysts read the sitting's run folders against the code the same day (research R1). The engineer's findings, in role terms: the review graded a vendor dowel pin for modelling practice and put it first in Start here; two of the five Start-here rows were passes and four carried a "no model explanation" line; the review asked twice for vault versions after the engineer answered "latest"; it offered to open the custom plate's same-name drawing read-only, the engineer said yes, and the seat refused the open, which the model never learned; it then asked for drawings of the assembly, the plate and the vendor pin; and the model's closing "drawing feedback" read like a review of a drawing nobody had read, with nothing marking it as advice. The standards profile on the seat was the repository's fictional example until that day. The owner asked on 2026-09-26 to proceed without questions unless blocked. The remodeler items of the same day (feature 004) are out of this package, and `specs/004-resilient-remodeler/` is not touched.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Bought Parts Are Not Graded for How They Were Modelled (Priority: P1)

An engineer reviews an assembly that holds custom parts and bought parts: vendor CAD downloaded for dowel pins, screws and bearings, and Toolbox hardware. The review tells the two apart from the company's standards profile - the folders bought parts live in, a property that marks a part purchased, vendor catalogue name patterns, the company's part-number convention - and from what SOLIDWORKS itself says (Toolbox). Modelling-practice and hygiene checks grade custom parts only. Bought parts are named once, in one line, as "not graded: bought part". Interference, fits, fasteners and mass still include them, and a mate to a bought part's face is not held against the assembly's modelling. When a part is neither clearly custom nor clearly bought, the review asks one question listing all such parts, answerable with "All bought", "None bought" or by naming the bought ones; the answer regrades the review at once. Until it is answered, those parts are graded and each finding says the part may be bought. The document the engineer is reviewing is always graded, with a label when it looks bought.

**Why this priority**: the first thing the engineer was told to look at was how a vendor modelled a dowel pin, and the custom plate's real modelling defects were pushed down by it. On a large assembly with dozens of bought parts, vendor noise buries every custom-part issue.

**Independent Test**: on a fictional fixture shaped like the sitting (an assembly, a custom plate that follows the part-number convention, a vendor pin with two instances under a fictional bought-parts folder, and one unclear part), a version 4 profile yields no modelling-practice or hygiene finding on the pin, one "not graded: bought part" line naming it, one question naming the unclear part, and every custom-part finding the review raised before; answering "All bought" withdraws the unclear part's modelling findings in the same session.

**Acceptance Scenarios**:

1. **Given** a version 4 profile naming a bought-parts folder, **When** a part under that folder is in the review, **Then** no modelling-practice or hygiene finding is raised on it and it is named once as not graded, with the reason ("a bought-parts folder").
2. **Given** a Toolbox part and no profile at all, **When** the review runs, **Then** the Toolbox part is not graded for modelling practice or hygiene, every other part is graded, no question is asked, and one line says bought parts were not told apart and why.
3. **Given** a version 1, 2 or 3 profile, **When** a part neither follows the part-number convention nor is Toolbox, **Then** it is unclear and the one question lists it; the profile's library skip list is never read as "bought".
4. **Given** unclear parts and no answer yet, **When** the review finishes, **Then** they are graded and each of their modelling-practice and hygiene findings says the part may be bought and names the question.
5. **Given** the one question, **When** the engineer answers "All bought", "None bought", or types the bought ones' names, **Then** before the review resumes the named parts' modelling-practice and hygiene findings are withdrawn, the rest keep their ids without the "may be bought" note, and the bought-parts line names them.
6. **Given** the reviewed document looks bought by every signal, **When** the review runs, **Then** it is still graded, with a label saying it looks bought and why it was graded anyway; the Model check tab behaves the same for its open part.
7. **Given** a mate between a custom part's plane and a bought part's face, **When** the assembly's mates are graded, **Then** only the custom side is required to be reference geometry.
8. **Given** the owner's version 3 profile on the seat, **When** the owner runs the upgrade helper, **Then** it writes a proposed version 4 profile whose bought-parts section is empty or pre-filled only as commented proposals from the library skip list, and nothing is treated as bought until the owner confirms it.

---

### User Story 2 - Every Finding, Grouped by Type, No Pass Amplified (Priority: P1)

The Review tab shows every finding, not five. Findings are grouped by type in a fixed order - Interference and fit, Fasteners, Drawings, Standards, Modelling practice, Hygiene, Mass and material - each group collapsible, each row a one-line headline, each group sorted by criticality in the attention policy's own order. Passes are never in a type group: they sit in one "Checked, no issue" fold at the end. The check goals' state lines sit under their group. The report carries the same "Findings by type". No surface ever amplifies a pass; the Model check and Standards tabs keep their five-row preview, now free of passes. Every group, order and word comes from the backend; the page never sorts.

**Why this priority**: two of the sitting's five Start-here rows were passes, and a list that short told the engineer the design's biggest problems were how a pin was modelled and that it weighs what steel weighs.

**Independent Test**: on the sitting-shaped fixture (after User Story 1) and on the big-assembly pane fixture, every finding is in exactly one row of one group or of the "Checked, no issue" fold; no pass is in a type group; each group's rows are in the ranking's order; the Review page renders the groups in the supplied order and sorts nothing; the check tabs show no pass in their preview.

**Acceptance Scenarios**:

1. **Given** a finished review, **When** its Results view opens, **Then** one grouped findings section replaces Start here, "Show all" and the flat card list, groups in the fixed order, each row one line.
2. **Given** a review with fewer than five undecided findings, **When** any surface shows its amplified rows (Start here on the check tabs, the gate brief, the explanation pass), **Then** no pass is among them and the not-amplified count includes the passes.
3. **Given** a group with no finding, **When** it renders, **Then** it shows its goals' state (checked, not reached, not applicable) instead of rows.
4. **Given** the report of a review, **When** it is rendered, **Then** "Findings by type" lists the same groups and rows in the same order as the pane.
5. **Given** a `standards.drawing.*` finding, **When** it is grouped, **Then** it is under Drawings; any other `standards.*` finding is under Standards.
6. **Given** the modelling-practice family that feature 008 folds into one row, **When** the grouped list renders, **Then** the Modelling practice group is that fold, arriving collapsed.

---

### User Story 3 - The Review Never Asks What It Can Know or Has Been Told (Priority: P1)

The review treats the files open in SOLIDWORKS as the latest: provenance is closed by code from the package before the first turn, and nobody is asked for a vault version or whether a file is modified locally. An engineer's answer is final: a question that repeats an answered one - the same checklist item and the same parts, including a follow-up such as "press fit answered, now give numeric limits" - is not asked; the answer stands and the check stays unresolved, quoting it. Ids the tools hand the model (joints, features, drawing entities) can be named in a question. The extractor stops writing the per-document vault-version and local-modified gaps, as a separate change.

**Why this priority**: the engineer said "latest version", the model refused the answer and asked again, and three of the sitting's eight questions re-asked answered ones; each cost a round trip and the engineer's attention and changed nothing.

**Independent Test**: on the sitting-shaped script with fictional ids, the review raises no vault or local-modification question and records provenance as checked by code; replaying the sitting's eight question calls, the three re-asks come back "already answered", citing the answer they repeat, and nothing new is recorded; a question naming a joint id from the joint check is recorded.

**Acceptance Scenarios**:

1. **Given** any review, **When** it starts, **Then** provenance is recorded once, checked by code, saying the open files are reviewed as the latest and that vault version and local modification are not read and never asked.
2. **Given** a package with manifest discrepancies (an ingested package), **When** the review starts, **Then** each discrepancy is a finding at the top of the report and still no question is asked.
3. **Given** the model asks about provenance or marks it, **When** the tool answers, **Then** it says provenance is closed by code and records nothing.
4. **Given** an answered question, **When** the model asks again on the same item about the same or fewer parts, **Then** the tool answers "already answered" with the earlier answer, records nothing, and at the end of the review the item, if still open, is unresolved with the answer quoted.
5. **Given** a question the model asks naming a joint, feature or drawing entity id a tool gave it, **When** it is asked, **Then** it is recorded; an id no tool gave is refused as today.
6. **Given** the opening brief, **When** a document's vault version or local-modified state is unknown, **Then** neither field is printed.

---

### User Story 4 - Drawings: Offer Only What the Seat Can Do, for Custom Documents Only (Priority: P1)

Drawings exist for custom parts and custom assemblies only, in the same folder, with the same name. The review looks for drawings of custom documents only and never asks for a bought part's drawing or a drawing's version. The add-in reports whether this seat may open a closed drawing read-only. While it may not (today: probe D14 has not passed), the review asks nothing and says, once per drawing file, "Open {drawing} in SOLIDWORKS, then press Review again with {model} active". Once the seat is validated, the existing read-only offer returns by itself, once per drawing file, and one read happens per distinct file. A custom document with no same-name drawing is an unresolved coverage item, not a finding. When the model asks for a drawing, code answers from what the package holds; when a code-run read is refused, the reason reaches the model.

**Why this priority**: the engineer was offered a choice this build cannot honour, said yes, and got nothing; the model then asked for drawings of a vendor pin, which can never be answered, and advised on a drawing it never saw.

**Independent Test**: with fakes, a host whose switch is off reports "open only" on ping; a package with an assembly and a custom plate sharing a stem, one candidate drawing file for both and a vendor pin produces no drawing question, one instruction line naming the file once, no candidate for the pin, and the pin's drawing state "bought: no drawing expected"; with the switch on, one question names the file once and a confirmation makes one read; a model drawing request on the pin and the plate is answered by code with each document's drawing state.

**Acceptance Scenarios**:

1. **Given** a seat whose read-only open is not validated, **When** a custom document has a same-name drawing that is not open, **Then** no question is asked and the review's drawings line and coverage say to open it in SOLIDWORKS and press Review again.
2. **Given** a validated seat, **When** one drawing file sits beside two reviewed documents of one stem, **Then** one question names the file once, and a confirmation asks the host to read it once and records the outcome for both documents.
3. **Given** a bought part, **When** the drawing check runs, **Then** it is not a drawing subject, no candidate, and no governing question; its drawing state says no drawing is expected.
4. **Given** a custom document with no same-name drawing and no open drawing, **When** the review runs, **Then** its drawing coverage is unresolved naming the missing file, and no finding is raised.
5. **Given** the model asks for drawings of documents none of whose drawings is attached, **When** the tool answers, **Then** code answers with each document's drawing state and how to include it, and records nothing.
6. **Given** a confirmed read the host refuses, **When** the review resumes, **Then** the resumed message and the drawing brief carry the refusal's reason.

---

### User Story 5 - Every Surface Says Where It Came From (Priority: P2)

Every finding, question, coverage sentence and answer carries its source, supplied by the backend: "Checked by code" for what a tool measured or a check decided, "AI guidance" for what the model wrote. Every model answer opens with one deterministic line, built from the tools that ran in its turn - for example "No evidence was read for this answer: this is general guidance." - never from the model's own text. The "No model explanation was generated" line is gone; only real explanations show, labelled as AI guidance. The explanation pass keeps every valid explanation it receives and logs why any was rejected.

**Why this priority**: the engineer could not tell a measured result from the model's advice, and advice that sounded like a drawing review, about a drawing nobody read, is worse than silence.

**Independent Test**: on fixtures, a code finding and a model-recorded drawing finding carry their two labels on the pane and in the report; the drawing check's question and the model's question show their two labels; a turn with no evidence call opens with the general-guidance line; an explanation batch with one oversized item keeps the others and logs the rejected id without the model's text.

**Acceptance Scenarios**:

1. **Given** a finding produced by a check tool, **When** it is shown anywhere, **Then** it is labelled "Checked by code"; a finding the model recorded is labelled "AI guidance".
2. **Given** a question written by code (the drawing check, the part-roles question) and one written by the model, **When** the panel shows them, **Then** each carries its own label.
3. **Given** a model answer whose turn read no evidence, **When** it is shown, **Then** its first line is "No evidence was read for this answer: this is general guidance.", followed, when no drawing was read in the review, by "No drawing was read in this review."
4. **Given** a finding with no explanation, **When** it is shown, **Then** nothing stands in for one.
5. **Given** an explanation batch with one invalid item, **When** it is parsed, **Then** the valid items are kept and the backend log names the rejected finding id and the rule it broke, never the text.
6. **Given** a session written before this feature, **When** it is opened, **Then** it loads, a legacy fallback line is not shown, and a record without a source shows the safe label for its kind.

---

### User Story 6 - Answer Turns Cost Only What They Need (Priority: P2)

After the first pass, answer turns re-sent the whole conversation for rounds that only re-read the checklist, marked the close-out, or re-asked answered questions. Code now closes the coverage close-out item itself; recording coverage returns the checklist items still open, so the model never re-reads the checklist to find them; the re-ask guard (User Story 3) and the refusal reasons (User Story 4) remove whole rounds. A new efficiency lever drops earlier turns' reasoning items from the request the model receives at the turn boundary; it becomes a pane default only if the replay shows no lost finding and a cut, and otherwise stays off with the reason recorded. Every change here that moves what a tool returns or what the prompt says passes the replay gate.

**Why this priority**: the sitting's first pass met its budget (199,139 against 300,000), but the whole review cost 590,498 input tokens, most of it after the first pass, on rounds that added under 3% new evidence.

**Independent Test**: runner and tool tests with the scripted provider show the close-out row written once by code and refused to the model, and `open_items` on every coverage result; the adapter drops only earlier turns' reasoning items with the lever on; the replay of every recorded review under the new code loses no finding and prices the lever's cut.

**Acceptance Scenarios**:

1. **Given** any review, **When** it finalizes, **Then** the coverage close-out item is closed by code exactly once, counting the open requests and the package's gaps; the model's attempt to mark it is answered "closed by code" and records nothing.
2. **Given** the model records coverage, **When** the tool answers, **Then** the answer lists the checklist items still open.
3. **Given** the new lever on, **When** a later turn's request is built, **Then** reasoning items from earlier turns are absent and the current turn's are present; the stored history is unchanged.
4. **Given** the replay of the recorded reviews with the lever off and on, **When** no finding is lost and the requested input falls, **Then** the lever becomes a pane default in a commit of its own; otherwise it stays off and the replay figures and reason are recorded.

---

### User Story 7 - Drawings and Feature Trees Are Read as SOLIDWORKS Holds Them (Priority: P2)

A drawing's revision table, bill of materials and hole tables live on each sheet's own view, which the sheet enumeration on this SOLIDWORKS release does not return; the drawing phase now reads each sheet's own view, and a revision check never claims a table is absent when the extractor recorded that it could not read one. Every check reads a part's feature tree one way: an absorbed sketch listed twice is one feature, and a sketch that moves with the feature consuming it is not a loose row of its own. The remodel planner already reads the tree this way; the grading checks now share its reading.

**Why this priority**: the Standards run on the plate's drawing said "no revision table found" although SOLIDWORKS reported one, and the Model check counted 48 loose features on a plate with 22; both are false findings an engineer has to disprove.

**Independent Test**: a dumper fake whose sheet enumeration lacks the sheet view but whose document views carry it, with a revision table and a bill of materials, records both tables and no cross-check gap; a package with the cross-check gap and no tables makes the revision check unresolved citing the gap; on the absorbed-sketches fixture the sketch rules name each sketch once and grouping lists each feature once; the remodel planner's output is byte-identical.

**Acceptance Scenarios**:

1. **Given** a drawing whose sheet views are returned without the sheet's own view, **When** it is extracted, **Then** the sheet's own view is read from the document's per-sheet view list, its tables recorded once each, and a mismatch between the two lists is a named gap with today's reading kept.
2. **Given** a sheet with the extractor's revision-table cross-check gap, **When** the revision check runs, **Then** "no revision table" is unresolved citing the gap, and the property-to-model comparison still runs on its own.
3. **Given** a part whose absorbed sketches are listed at two depths, **When** the modelling-practice and standards sketch checks run, **Then** each sketch is named once, and grouping reports each feature once, the absorbed sketch moving with its consumer.
4. **Given** the remodel planner over the same fixtures, **When** it plans, **Then** its output is unchanged byte for byte.

---

### Edge Cases

- **No standards profile, or an unreadable or invalid one**: only Toolbox parts are skipped; every other part is graded with no "may be bought" note; no question; one line says bought parts were not told apart and why. The existing standards refusal reasons are unchanged.
- **A version 1 to 3 profile with an empty part-number pattern**: treated as no profile for part roles (no convention to tell custom parts by), so no question listing every part is asked.
- **The part-number convention matches no document of the review at all** (root included) and nothing else decides one: the question is not asked; one unresolved coverage line says the convention matched none of the N documents, likely a profile error (feature 006's zero-match precedent).
- **A bought-parts folder and the part-number convention disagree** (a vendor file renamed to a company number, or a company file saved in the library): the folder decides bought, and the reason says the name follows the convention; a vendor name pattern and the convention both matching make the part unclear.
- **A part inside a bought assembly** that follows no custom rule is bought ("inside a bought assembly"); one that follows the part-number convention stays custom.
- **A part whose properties were not read**: the purchased-property signal is unknown, never a match; the other signals decide.
- **A part with no recorded path**: the folder signal cannot match; the reason says the path was not recorded.
- **The engineer names a part the question did not list**, or a name matching nothing: quoted back in one coverage line; nothing changes for it; the named listed parts still become bought.
- **The engineer answers after the review regraded once already** (a second answer is refused as today: an answered question cannot be answered again).
- **The model asks to grade a bought part by id**: the modelling check refuses it, naming the reason, so a bought part cannot be graded by hand.
- **A mate between two bought parts**: not graded against the assembly's modelling; a mate with an unclear side grades that side, with the note.
- **Findings withdrawn by a regrade**: the page drops their cards and reloads the summary; the finding ids leave gaps; events keep the history.
- **A group with hundreds of findings** (the big assembly): rows are one line and collapsible; the Modelling practice group arrives collapsed.
- **A check id no group names**: it lands in an "Other checks" group appended last, never dropped; the catalogue test keeps that group unreachable for every known check.
- **A pass under an accepted exception**: it sits in the "Checked, no issue" fold with a tail saying it is within an accepted exception.
- **A folded row titled after one member** (three hygiene findings on three documents): the one-line headline keeps its "xN" tail and reach, so it never reads as if one part were affected.
- **A re-ask with more parts than the answered question**: it is not a repeat and is recorded; a re-ask with the same parts but no checklist item repeats one that also had none.
- **A question that repeats one still open**: answered "already asked", naming it; nothing is recorded.
- **The seat switch is set while a review is open**: the capability is read once per review; the next review offers the question.
- **A host that does not report the capability** (an older add-in, the console host): treated as unable to open, so the instruction line is shown.
- **One drawing file beside a custom plate and its assembly of one stem**: one candidate file, one question or instruction, one read, the outcome recorded for both documents; the host's merge removes every candidate row of that path, so no second read is refused.
- **A drawing request naming a component or hole**: mapped to its document before the drawing state is read.
- **A model answer in a turn that only wrote bookkeeping** (questions, coverage): counts as reading no evidence.
- **A stopped turn**: its steps count towards the next answer's basis line.
- **An explanation batch that is not valid JSON, or a provider error**: nothing is stored, the reason is logged, the rows show no explanation.
- **A sheet whose own view does not match its name or type**: a named gap; today's sheet enumeration is kept for that sheet.
- **A revision table returned by the sheet view and a drawing view**: recorded once.
- **The remodel planner's tree reading moving to a shared module**: the planner keeps importing the same names from its own module; its output and feature 004's contract text stay true.
- **A recorded review replayed after these changes**: no recorded finding lost or unreplayable (absolute); the fixtures regenerated when a tool's return or the prompt moves (008 decision 3A).

## Requirements *(mandatory)*

### Functional Requirements

**Custom and bought parts (US1)**

- **FR-001**: The standards profile MUST gain a version 4 whose one new section, `part_roles`, names the bought-part path prefixes, a purchased property with its purchased values, and vendor name patterns; every key required, every value possibly empty; versions 1 to 3 MUST keep loading unchanged, and a version 1 to 3 file carrying the section MUST be refused naming it as a version 4 section.
- **FR-002**: Name patterns MUST use the part-number pattern's vocabulary (`#` a digit, `?` any one character, every other character literal, whole file name with extension, case-insensitive) extended with `@` for one letter and `*` for any run; the part-number check itself MUST keep the vocabulary it has.
- **FR-003**: The profile validator MUST refuse a blank pattern or prefix (named by position), a vendor pattern made only of wildcards (it would mark every part bought), a purchased property with no purchased values or values with no property, and unknown keys.
- **FR-004**: An upgrade helper MUST write a proposed version 4 profile from a version 1 to 3 file for the owner to confirm, never overwriting its input; it MAY copy the library skip list into the bought prefixes only as commented proposals, so nothing is treated as bought until the owner uncomments it.
- **FR-005**: One pure function MUST classify every part and assembly document of a package as custom, bought or unclear, each with a reason naming the rule that decided it and never a profile value; it MUST be computed once per review and read by every consumer.
- **FR-006**: The classification MUST apply, first match winning: the engineer's answer to the part-roles question in this session; Toolbox (bought); a bought-part prefix (bought); the purchased property holding a purchased value (bought); a vendor name pattern together with the part-number convention (unclear); a vendor name pattern (bought); the part-number convention (custom); a same-name drawing beside it (custom); inside a bought assembly (bought); otherwise unclear.
- **FR-007**: With a version 1 to 3 profile the bought-part rules that need the version 4 section MUST not exist, and the library skip list MUST NOT be read as bought; with no profile, or one that cannot be read, only Toolbox MUST decide, and no question MUST be asked.
- **FR-008**: The reviewed document MUST always be graded; when the rules say bought, it MUST carry a label saying it looks bought and why it was graded.
- **FR-009**: Modelling-practice (RMS part and equation) and hygiene property checks MUST grade custom and unclear documents only; bought documents MUST be listed once as "not graded: bought part" in one summary line counted in no group, goal or headline, and in one coverage row whose sentence is the same.
- **FR-010**: Interference, fit, fastener, mass, component-resolution and assembly checks MUST keep including bought parts; `rms.assembly.mates_to_reference_geometry` MUST require reference geometry only on the custom (or unclear) side of a mate, and MUST NOT grade a mate between two bought parts.
- **FR-011**: When unclear documents exist and the classification is not in its no-profile state, the review MUST record exactly one code-written question listing them (at most ten file names, then a count), offering "All bought" and "None bought" and a text box for naming the bought ones; the question blocks no checklist item.
- **FR-012**: An answer MUST regrade in the same session before the review resumes: modelling-practice, hygiene, assembly and drawing checks restated once each; a finding judged again keeps its id; a finding no longer produced is withdrawn with an event naming it and why; the answer is kept for this session only.
- **FR-013**: Unanswered, unclear documents MUST be graded, and each of their modelling-practice and hygiene findings MUST say the part may be bought, naming the question.
- **FR-014**: A modelling check asked by id to grade a bought document MUST refuse, naming the reason.

**Findings grouped by type (US2)**

- **FR-015**: The Review tab MUST show one grouped findings list in place of its Start here, "Show all" and flat card list: every finding in exactly one row of one group, or in the "Checked, no issue" fold.
- **FR-016**: The groups MUST be, in this order: Interference and fit, Fasteners, Drawings, Standards, Modelling practice, Hygiene, Mass and material; plus "Other checks", last and only when it holds something.
- **FR-017**: A finding's group MUST come from one prefix-to-group table shared with feature 009's goals (each goal names its group; Standards becomes a goal of its own, split from Hygiene); `standards.drawing.*` MUST be under Drawings; each goal's state line MUST sit under its group.
- **FR-018**: Within a group, rows MUST follow the attention policy's order; rows MUST be one-line headlines carrying their fold count; groups MUST be collapsible, Modelling practice arriving collapsed; accepted and rejected rows MUST sit at the end of their group.
- **FR-019**: A pass (`checked_within_scope`) MUST never be in a type group and MUST never be amplified on any surface: the number of amplified rows is at most five and at most the number of rows that are not suppressed.
- **FR-020**: The Model check and Standards tabs MUST keep their five-row preview, pass-free by FR-019.
- **FR-021**: The report MUST carry "Findings by type" with the same groups and rows in the same order as the pane; the model-facing five-row Start here (the gate brief and the attention command) MUST be unchanged except by FR-019.
- **FR-022**: The backend MUST supply every group, order, count and word; the page MUST NOT sort, compare or count.
- **FR-023**: The summary block MUST keep the headline (counting passes as checked, not as issues), one tally line, the questions, the parts not loaded, the drawings line, the bought-parts line, and one line naming the goals not reached.

**Questions the review never asks (US3)**

- **FR-024**: Code MUST close provenance from the package at the start of every review, whatever levers are on: checked, saying the open files are reviewed as the latest and that vault version and local modification are not read and never asked; each manifest discrepancy, where a package has them, MUST be a finding.
- **FR-025**: The provenance checklist item MUST be code-owned: rendered to the model as closed by code; `mark_coverage` and `request_evidence` naming it MUST answer "closed by code" without recording anything and without writing a failed row.
- **FR-026**: The opening brief MUST print a document's vault version and local-modified state only when they are known.
- **FR-027**: `request_evidence` MUST answer "already answered", with the earlier request and its answer, a question whose checklist item equals an answered question's (no item matching no item) and whose parts are a non-empty subset of it, or equal to an empty set of it; the most recent answer wins; nothing is recorded, no id is allocated, no event is written.
- **FR-028**: A question repeating one still open MUST be answered "already asked", naming it, and recorded nothing.
- **FR-029**: At finalization, a checklist item still open whose blocking question was answered MUST be unresolved with the answer quoted.
- **FR-030**: `request_evidence` MUST accept every id a tool hands the model: joints from the joint check, features, and drawing sheets, views, dimensions, annotations and notes from the package.
- **FR-031**: The extractor MUST stop writing the per-document vault-version and local-modified gaps (a separate change), keeping every other manifest gap.
- **FR-032**: The system prompt MUST say that an engineer's answer is final.

**Drawings (US4)**

- **FR-033**: The add-in MUST report on the bridge's ping whether it can read a confirmed drawing and whether it may open a closed one, read from the object that answers the read, backed by the seat switch; a host that does not report it MUST count as unable.
- **FR-034**: One function MUST decide each reviewed part or assembly document's drawing state: attached, candidate, absent or bought; unclear documents are treated as custom, noted as possibly bought.
- **FR-035**: Drawings MUST be looked for only for custom (and unclear) documents, as the same-name drawing in the same folder; a bought document MUST NOT be a drawing subject, a candidate, or the subject of a governing question.
- **FR-036**: While the seat may not open a closed drawing, the review MUST ask no candidate question; the drawings line and the candidate's coverage MUST say "Open {drawing} in SOLIDWORKS, then press Review again with {model} active", once per drawing file.
- **FR-037**: Candidates MUST be grouped by drawing file; one question and one read MUST cover every document a file sits beside, and the host's merge MUST remove every candidate row of the path it read.
- **FR-038**: A custom document with no same-name drawing and none attached MUST be unresolved drawing coverage naming the missing file, not a finding.
- **FR-039**: `request_evidence` for the drawing checklist item MUST be answered by code with each named document's drawing state when any of them has no attached drawing, recording nothing; when no attached drawing shows any custom document, the drawing check MUST close the item by code (unresolved with a candidate or absent document, skipped when every subject is bought), and `mark_coverage` on it MUST answer "closed by code" in that state.
- **FR-040**: The outcome of every code-run drawing read, refusals included, MUST reach the model: in the resumed turn's message and in the drawing brief.

**Sources (US5)**

- **FR-041**: Every finding, evidence request and coverage item MUST carry a backend-supplied source, "code" or "model", shown as "Checked by code" or "AI guidance"; the field MUST be omitted from the session at its kind's usual author, so no byte the model reads moves.
- **FR-042**: Every model answer MUST carry a deterministic first line computed from the tools that ran in its turn and whether any drawing was read, never from the model's text.
- **FR-043**: The "No model explanation was generated" fallback MUST NOT be stored or shown; a legacy one in an older session MUST be filtered out when read; real explanations MUST be labelled "AI guidance".
- **FR-044**: The explanation pass MUST keep each valid item of a batch and MUST log, for each rejected item, its finding id or position and the rule it broke, never the model's text.

**Tokens (US6)**

- **FR-045**: The coverage close-out checklist item MUST be code-owned and closed by finalization exactly once, its reason counting the open requests and the package's gaps by kind.
- **FR-046**: The results of `mark_coverage` and `request_evidence` MUST list the model-owned checklist items still open.
- **FR-047**: A new lever MUST drop reasoning items of earlier turns from the request view at the turn boundary, leaving the stored history untouched; it MUST default off, and MUST become a pane default only if the replay shows no lost finding and a cut in requested input; otherwise it stays off with the replay figures and reason recorded.
- **FR-048**: Every change that moves what a tool returns, the system prompt, the checklist, the opening message or a resumed message MUST pass the replay gate: the fixtures regenerated by the current code (008 decision 3A), no recorded finding lost or unreplayable, the recorded contacts reproduced, and the real recordings' residual zero on every round.

**Readings (US7)**

- **FR-049**: The drawing phase MUST read each sheet's own view from the document's per-sheet view list, confirm it by index, type and name, record its tables once each, and record a named gap and keep today's reading on a mismatch.
- **FR-050**: The revision check MUST NOT report a revision table as absent on a sheet where the extractor recorded a revision-table read gap or no sheet view; that case is unresolved citing the gap.
- **FR-051**: One shared reading of a part's feature tree MUST serve the modelling-practice checks, the standards sketch check and the remodel planner; an absorbed sketch listed twice MUST be one feature, and a sketch consumed by a feature MUST NOT be its own loose row for grouping.

**Test debt**

- **FR-052**: The remodel probe watchdog MUST decide "blocked" from a deadline that starts only once the call has started, on a thread of its own, with the deadline a signal the tests control; probe 1 MUST run its flag-set attempt first; the host's own exception message MUST reach the ledger.

**Integration**

- **FR-053**: Every new session, event and evidence field MUST be optional and additive; sessions and packages written before this feature MUST load and round-trip to their own bytes.
- **FR-054**: No tool signature or docstring MUST change; the payload pins MUST not move unless regenerated in a commit of their own with the reason.
- **FR-055**: The repository MUST carry no company value: every example and fixture uses fictional values, and the standards-profile census and the tracked-files guard pass.

### Key Entities

- **Part roles section**: the version 4 profile section naming what makes a part bought.
- **Part role**: one document's custom, bought or unclear, with the rule that decided it, its reason, and whether it is graded.
- **Part roles**: the review's classification, with its state (configured, convention only, absent).
- **Part-roles question**: the one code-written question listing unclear documents, answerable by two buttons or a text box.
- **Findings by type**: the grouped view of a review's findings: groups, their rows and goal lines, and the "Checked, no issue" fold.
- **Source**: who wrote a record - code or the model.
- **Answer basis**: the deterministic first line of a model answer.
- **Code-owned checklist item**: an item the model cannot mark or ask about, closed by code.
- **Drawing read capability**: what the add-in reports about opening confirmed and closed drawings.
- **Drawing state**: one reviewed document's attached, candidate, absent or bought.
- **Feature node**: one position in a part's feature tree as every check reads it.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: On the next sitting's re-review of the small assembly with the real profile upgraded to version 4, zero modelling-practice or hygiene findings are on a bought part, and the bought part is named exactly once as not graded.
- **SC-002**: On the sitting-shaped fixture, every custom-part finding raised before this feature is still raised, and the modelling-practice group's first row is a custom part's.
- **SC-003**: On every fixture, every finding is in exactly one group row or in the "Checked, no issue" fold, and no pass is amplified on any surface.
- **SC-004**: On the next sitting's re-review, zero questions ask for a vault version or local-modified state, and zero questions repeat an answered one.
- **SC-005**: While the seat switch is off, zero read-only-open questions are asked, and each same-name drawing file of a custom document is named in exactly one instruction line.
- **SC-006**: Every finding, question and model answer the Review tab and the report show carries its source label, and every model answer's first line is its basis line.
- **SC-007**: Replaying every recorded review after each change of this feature loses no finding, leaves none unreplayable, reproduces each fixture's recorded contact groups exactly, and keeps the real recordings' residual at zero on every round.
- **SC-008**: On the next sitting, the small assembly's review run as the 2026-09-26 sitting ran it (first pass, one batch of answers, one follow-up) uses at most 400,000 input tokens in total (590,498 on 2026-09-26), and no answer-turn round's only calls are checklist or gap re-reads.
- **SC-009**: On the next sitting, Standards on the custom plate's open drawing reads its revision table and bill of materials, and reports no "no revision table" warning.
- **SC-010**: On the absorbed-sketches fixture, each sketch is named once in every sketch finding, and the loose-feature count equals the features an engineer can move.

## Assumptions

- **Defaults, not the owner's words.** Every design question the analysts raised is settled by a default taken on 2026-09-26 (research R2), which the owner may revise; each is recorded with its alternatives.
- **The owner writes the version 4 section.** The repository ships only fictional values; the upgrade helper proposes, the owner confirms on the seat (a seat task), and the real profile never enters the repository.
- **Answers to the part-roles question last one session.** Carrying answers - to that question or to any other - into the next review of the same document is a later, separate item (research R2.23).
- **The seat switch belongs to feature 011.** This feature reports it and follows it; setting it stays 011's probe D14 and task T077, run at the next sitting.
- **Mass and material is a seventh group** by default; the owner may fold it into Hygiene with a one-line change of the words file.
- **Model-facing surfaces keep their five-row Start here**: the gate brief and the attention command are the model's budgeted view (feature 007 FR-029); only FR-019 changes them.
- **The new lever is measured on the replay only** by default; a seat A/B is not required to set it.
- **The fixtures follow the code** (feature 008 decision 3A); a regeneration is part of the change that needs it and a commit of its own.
- **The remodeler is out of scope**: its defaults of the same day belong to feature 004; the probe 1 watchdog is in scope only as test debt in its C# code, and 004's documents are not edited here.
- **Findings of the analysts not settled by a default** (research R6) are recorded for the owner and not built.
