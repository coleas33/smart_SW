# Feature Specification: Drawing Context, Read Only

**Feature Branch**: `011-drawing-context`

**Created**: 2026-09-23

**Status**: Draft; amended 2026-09-23 with the owner's answers to research R5 (Q2 to Q9). Q2 changes the spec: a candidate drawing the engineer confirms is opened read-only by the product, read and closed (User Story 5, FR-015, FR-036, FR-053 to FR-056, SC-011); the other answers confirm the defaults already written.

**Input**: The owner's direction of 2026-09-22 (`docs/roadmap-2026-09-22.md`, "Decisions taken 2026-09-22" and the feature 011 section): drawings are **read-only context before the next test** - fix the drawing attach refusal; attach the drawings already open in SOLIDWORKS to part and assembly reviews; extract their native dimensions, tolerances, notes and tables; a per-part drawing brief; questions in the pane. The architecture amendment of the same day (`sw-review-architecture-proposal.md`, "Amendment 2026-09-22: checks first, and drawings in two stages"): layer 3 is reached in two stages, and this is stage one; stage two, creating drawings, is feature 012, specified only after seat probes and a constitution amendment, and it starts from the owner's existing drawing-creation base repository, whose location has not been given yet. SOLIDWORKS 2024 has no programming interface that generates a drawing automatically. Tolerances come from four sources and drawing callouts are one of them (owner, 2026-09-22); feature 010's tolerance resolver already has that source's slot waiting. The general tolerance goes by decimal places (owner, 2026-09-23, feature 010 research R5), which needs the precision each dimension is written to, and only a drawing records that. Evidence: no review has yet seen a sheet - since 2026-09-18 the attach refuses a drawing before it asks for a configuration, so the drawing reading of feature 006 has only ever run under test fakes and the Standards tab fails on a drawing; every recorded evening review asked for drawings and left fits, stacks, alignment and manufacturing inputs unresolved.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A Drawing Opened on Its Own Can Be Read and Graded (Priority: P1)

An engineer opens a drawing in SOLIDWORKS and presses Standards, or extracts it from the command line. The drawing is read as it stands - every sheet, view, dimension, annotation, note and revision table the Standards checks were built for - together with the models its views show, and graded. Nothing is opened, activated, rebuilt or saved to do it. Tools that genuinely need a part or an assembly, such as the live measurement bridge, still decline a drawing and say which document to open instead.

**Why this priority**: the Standards tab has promised drawing grading since feature 006 and fails on every drawing today, because the attach step refuses the document before any of the drawing reading runs. Every other story in this feature reads drawings through the same attach.

**Independent Test**: with no licence, a fake session reports a drawing as the open document; the extraction accepts it, reads its sheets through the existing fake drawing reader, and the Standards run grades the drawing's four drawing checks; the same fake session handed to the live bridge is still declined with the sentence naming the model to open. On the next sitting, press Standards on a multi-sheet drawing.

**Acceptance Scenarios**:

1. **Given** a drawing is the open document, **When** the engineer presses Standards, **Then** the drawing and every model its views show are extracted and graded, and the report says the drawing was read as it stood.
2. **Given** a drawing is the open document, **When** a tool that needs a part or assembly (the live bridge, the terminal, a review) starts, **Then** it declines by name and tells the engineer which model to open, exactly as today.
3. **Given** a drawing path on the command line that is not open in SOLIDWORKS, **When** it is extracted, **Then** the extraction declines and asks for the drawing to be opened first, because opening a drawing loads every model it shows.

---

### User Story 2 - The Open Drawings of a Reviewed Part or Assembly Join Its Review (Priority: P1)

An engineer reviews an assembly with the drawings of two of its parts open in other SOLIDWORKS windows. The review reads those two drawings with the design, because their views show documents under review. A drawing open for something else is left alone. A part that has a drawing file of the same name beside it, not open, is not opened by the extraction and the folder is never searched beyond that one name; the review says the file is there, and asks (User Story 5). Which drawings were read, and which were not, is stated.

**Why this priority**: every recorded review asked for drawings and had none; this is how drawing evidence reaches a review without the engineer exporting anything.

**Independent Test**: with fakes, an assembly review with three open drawings - one showing the assembly, one showing one of its parts, one showing an unrelated part - reads the first two and not the third; a part with a same-name drawing file beside it, not open, is listed as a drawing candidate and nothing opens it; a part review with no drawing open says so in plain words.

**Acceptance Scenarios**:

1. **Given** an open drawing whose views show the reviewed document or any document in its tree, **When** the design is extracted for review, **Then** the drawing is read and named among the design's drawings.
2. **Given** an open drawing whose views show no document of the design, **When** the design is extracted, **Then** it is not read.
3. **Given** a reviewed document with no open drawing and a drawing file of the same name in its folder, **When** the design is extracted, **Then** the file is recorded as a candidate and is not opened; no other file or folder is looked at. (Only the engineer's confirmation opens it, User Story 5.)
4. **Given** no open drawing shows the design, **When** the review starts, **Then** the review states that no drawing was read and how to include one.
5. **Given** more open drawings than the extraction reads in one pass, **When** the design is extracted, **Then** the ones not read are named.

---

### User Story 3 - The Drawing's Dimensions, Tolerances and Written Precision Reach the Checks (Priority: P1)

The fit, stack-up and alignment checks of feature 010 read the drawing as their first tolerance source. A diameter with a tolerance on the drawing, attached to a hole that forms a joint, is the tolerance that joint's stack-up uses, cited by drawing, sheet, view and dimension. A dimension written without its own tolerance takes the general tolerance by the number of decimals it is written to, as the owner's convention says. A drawing view that shows another configuration, or that is out of date with the model, is not used for the reviewed configuration, and the review says so. The fit and stack tools the model can call find native drawing dimensions exactly as they find dimensions read from a PDF, and compute with them only once the seat has validated the drawing reading.

**Why this priority**: fits, stacks and alignment were unresolved in every recorded review for want of a tolerance; the general tolerance was declared by the owner and can bind nothing until a written precision is known.

**Independent Test**: on a synthetic package, the plate's dowel hole carries a bilateral diameter tolerance on the drawing; the joint's stack-up uses it, citing the drawing, with the model's own dimension listed as also found; a two-decimal untoleranced dimension on the pin binds the two-decimal general tolerance band; the same dimension in a view of another configuration binds nothing and names both configurations.

**Acceptance Scenarios**:

1. **Given** a toleranced drawing dimension attached to a subject's faces, or showing the model dimension that sizes it, in a view of the reviewed configuration that is up to date, **When** the subject's tolerance is resolved, **Then** the drawing binds first and is cited.
2. **Given** an untoleranced drawing dimension of a subject with a known written precision, **When** no other source binds, **Then** the general tolerance band for that number of decimals applies, cited as general, and only if the drawing is dimensioned in the unit the company's bands are counted in.
3. **Given** a drawing dimension in a view of another configuration, or in a view that is out of date, **When** a tolerance is resolved, **Then** it binds nothing and the reason names the view.
4. **Given** two drawings, or two dimensions, that disagree about one subject, **When** it is resolved, **Then** the first in a fixed order is used and the disagreement is reported.
5. **Given** the model asks for dimensions or a sheet of a drawing that was read natively, **When** the tool answers, **Then** it returns the native dimensions with their text parts and tolerances; a fit or stack check that names one of them computes with it once the seat has validated the drawing reading, and until then declines it, naming that validation (FR-024).

---

### User Story 4 - Every Callout on the Drawing Is Read (Priority: P2)

Beyond dimensions, the extraction reads what a drawing says about manufacturing: hole callouts with their text, datum labels, geometric tolerance frames, surface finish symbols, every note verbatim, and every table - bill of materials, hole table, general tolerance table and title block - cell by cell, beside the revision tables it already reads. Each is tied to the sheet and view it sits on, and, where SOLIDWORKS says so, to the model faces it is attached to. A position tolerance on a drawing attached to a hole is the position tolerance that joint's stack-up uses.

**Why this priority**: the checklist's "drawing manufacturing inputs" item - material, general tolerance note, surface finish, thread callouts with depth, critical fits - cannot be closed without them; it is P2 because the P1 stories already carry the numbers the checks compute with.

**Independent Test**: with fakes, a drawing carrying one of each - hole callout, datum, geometric tolerance, surface finish, a note, a bill of materials, a hole table, a general tolerance table and a title block table - produces one record each, with every unreadable value named as a gap; the position tolerance on the dowel hole's face binds that hole's position in the stack-up.

**Acceptance Scenarios**:

1. **Given** a drawing with hole callouts, datums, geometric tolerances and surface finish symbols, **When** it is extracted, **Then** each is recorded with its text as written and the faces it is attached to where they are known.
2. **Given** tables of any kind on a sheet, **When** it is extracted, **Then** each table is recorded with its kind, title and every cell; the revision tables stay exactly as feature 006 records them.
3. **Given** a value that could not be read, **When** it is extracted, **Then** it is a named gap, never an empty value.

---

### User Story 5 - Questions Only the Engineer Can Answer Reach the Pane (Priority: P2)

When the review cannot tell something about the drawings that the engineer knows at a glance, it asks one short question in the pane's "Questions for you" panel, with the answers offered as buttons: a drawing file of the same name sits beside reviewed parts but is not open - yes, it is the drawing, open it read-only and read it; review without it; or it is not the right drawing; two open drawings show the same part - which one governs it. When the engineer confirms a candidate, the product opens it read-only itself, without showing it or taking focus from the engineer's window, reads it into the review, and closes it again; it never changes or saves it, and never closes a drawing the engineer had open *(owner, 2026-09-23, research R5 Q2: this replaces "the engineer opens it and reviews again")*. The questions are few and never repeat within a review. Answers are recorded and become part of that part's drawing brief.

**Why this priority**: the owner asked for the same-name drawing to be offered as a question and never opened silently; the questions reuse the pane and the answer route features 008 and 009 built, so they cost no new screen.

**Independent Test**: on a synthetic package with three candidate drawings and one part shown by two open drawings, the review's code-first pass raises exactly two questions - one naming the three candidates, one asking which drawing governs the part - both answerable with one click; calling the check again raises none. With fakes, confirming the candidates opens each read-only and hidden, reads it into the package and closes it; a drawing the engineer had open is read and not closed; the other answers open nothing. On the next sitting, probe D14.

**Acceptance Scenarios**:

1. **Given** reviewed documents with a same-name drawing beside them and not open, **When** the review starts, **Then** one question names them and offers the three answers.
2. **Given** a reviewed document shown by two to four open drawings, **When** the review starts, **Then** one question asks which governs it, offering each drawing and "they all apply".
3. **Given** a design whose drawing evidence raises nothing to ask, **When** the review starts, **Then** no question is added.
4. **Given** the questions were asked, **When** the check runs again in the same review, **Then** no question is added twice.
5. **Given** the candidate question, **When** the engineer answers "yes, open it read-only and read it", **Then** before the review resumes each candidate is opened read-only without being shown or taking focus, read into the review with its sheets, views and callouts, and closed again, and the review says which it read; nothing is saved or changed.
6. **Given** a confirmed candidate that the engineer has opened in the meantime, **When** it is read, **Then** it is read as it stands and left open.
7. **Given** any other answer, or a review with no connection to SOLIDWORKS, **When** it is sent, **Then** nothing is opened, and in the second case the review says why the drawing was not read.

---

### User Story 6 - A Per-Part Drawing Brief, Bounded and on Demand (Priority: P2)

For any part or assembly in a review, the model - or the engineer from the command line - can ask for a short brief: what the part is; how it is assembled (its joints, partners and fasteners from feature 010's joint map); which interfaces need a callout and what tolerance each has now, from which source, or what is missing; what the existing drawing covers; and the engineer's confirmed answers. It is served only when asked for, and always short enough to resend cheaply.

**Why this priority**: it is what a model needs to explain a drawing's gaps, and it is the input feature 012's drawing plan will be built from; it follows the stories that supply its facts.

**Independent Test**: on the synthetic package, the plate's brief names the plate, its two joints and their partners, the dowel hole's size tolerance bound by the drawing and its position budget callout, the drawing's sheets and callouts, and the one answered question about it; a package with five hundred notes produces a brief under the size bound that says how many notes it left out.

**Acceptance Scenarios**:

1. **Given** a part in the review, **When** its brief is requested, **Then** the five sections come back in a fixed order, each bounded, each omission counted.
2. **Given** a part with no drawing read, **When** its brief is requested, **Then** the drawing section says so and names any candidate file beside it.
3. **Given** a drawing's own id, or an id not in the package, **When** a brief is requested, **Then** it is declined naming the documents that can be briefed.

---

### User Story 7 - The Company's Drawing Standard Is in the Profile, and Drawings Are Compared With It (Priority: P3)

The standards profile gains a drawing section: the accepted sheet formats, the drafting standard, the projection, the unit drawings are dimensioned in (the unit the general tolerance's decimal places are counted in), and the drawing and bill-of-materials templates. The general tolerance itself stays where feature 010 put it and is not restated. Each drawing read in a review is compared with the section, and one finding per drawing names every setting it differs in.

**Why this priority**: the owner supplies the values at the next sitting; the comparison is useful, not blocking.

**Independent Test**: with a fictional version 3 profile, a drawing in third-angle projection against a first-angle profile, with an unlisted sheet format, is one finding naming both; a version 2 profile compares nothing and says the section is absent.

**Acceptance Scenarios**:

1. **Given** a version 3 profile and a drawing that differs in any compared setting, **When** the review runs, **Then** one finding for that drawing names each difference with the drawing's own value.
2. **Given** a setting left empty in the profile, **When** the drawing is compared, **Then** that setting is skipped, never passed.
3. **Given** a version 1 or 2 profile, **When** the review runs, **Then** the comparison is skipped naming the missing section, and everything else behaves as today.

---

### Edge Cases

- **A drawing view shows another configuration** of a reviewed document: the view is recorded; its dimensions are not used for the reviewed configuration, and the reason names both configurations.
- **A drawing view is out of date** with its model, or whether it is up to date could not be read: its dimensions are not used as tolerances, and the view is named.
- **A drawing opened in detailing mode**, or a view whose model is not loaded: the annotations that answer are recorded; nothing that needs the model is guessed; the gap names the view.
- **A drawing shows the reviewed part and also parts outside the review**: it is read; views of outside documents are recorded with the path they reference and add nothing to the review's evidence about those documents.
- **One part used in two configurations** in the assembly: a drawing view binds only to the instances whose configuration it shows.
- **Two drawings, or two views, carry different tolerances** for one subject: the first in a fixed order is used and the conflict is reported; with different written precisions, the general tolerance binds nothing and says why.
- **A fit, stack or alignment check handed a native drawing dimension before the seat has validated the drawing reading**: the reference is declined with the reason naming the seat validation and no verdict is computed; a dimension read from a PDF is taken as today.
- **A drawing dimension whose displayed value is overridden** (the defect the Standards tab reports): it is never used as a tolerance or a precision for the model, because the number shown is not the model's.
- **A dimension uses the document's default precision**: the precision is the drawing's default, recorded as such; if the default could not be read, the precision is unknown.
- **A dimension written in inches on a drawing whose company bands are counted in millimetres**, or the reverse: the general tolerance binds nothing and names both units.
- **A dimension governed by SOLIDWORKS' general tolerance table** (an ISO 2768 class): recorded as such, verbatim; no class is converted to limits in this feature.
- **A geometric tolerance value with no unit written**: read in the drawing's recorded length unit and cited so; with the unit unread, it binds nothing.
- **Many open drawings**: at most ten are read per extraction, root document's drawings first; the rest are named.
- **A same-name drawing that is already open** is attached when it shows the document, and otherwise named as an open drawing that shows none of the design; it is never a candidate. A same-name file of another type is ignored.
- **A drawing in a vault view that is not cached locally**: whether it exists is asked without opening or fetching it; a failed check is a gap, never a guess.
- **An attached drawing whose sheet cannot be enumerated without activating it**: that sheet is named unresolved; no sheet or window is ever activated.
- **The same document shown by more than four open drawings**: the question offers no buttons and asks for the governing drawing's name.
- **A confirmed candidate that cannot be opened** (gone since the extraction, or refused by SOLIDWORKS): nothing is retried and nothing else is opened; the review names it and why. The product never falls back to another file name or folder.
- **A confirmed candidate that is already open** when the answer arrives (the engineer opened it): read as it stands and never closed.
- **More confirmed candidates than the room left under ten drawings**: the first in traversal order are read until the package holds ten drawings; the rest are named, never opened.
- **The read fails after the open**: the drawing is still closed, because the product opened it; what was not read is a named gap.
- **Models the drawing loads when it opens**: the product closes only the drawing, never a model; whether SOLIDWORKS unloads them with it is probe D14's to record.
- **A review started from the command line, or with no connection to SOLIDWORKS**: the confirmation is recorded and nothing is opened; the review says so.
- **Recorded reviews with no drawing**: they replay exactly as before - no new question, no new tool offered, no finding lost.
- **Checklist collision**: the conformance finding is named so that it cannot close the checklist's "drawing manufacturing inputs" item, which only an evaluation of those inputs may close.

## Requirements *(mandatory)*

### Functional Requirements

**Opening a drawing on its own (US1)**

- **FR-001**: Extraction for grading or evidence MUST accept a drawing as the open document, binding no configuration to it, and MUST read it with the models its views show exactly as feature 006 designed (006 FR-024, FR-025).
- **FR-002**: Every tool that needs a part or assembly - the live bridge, the terminal session, the review start, the model check - MUST keep declining a drawing by name, with the model to open instead.
- **FR-003**: The command-line extraction MUST NOT open a drawing that is not already open; it MUST decline naming why. (The one product path that opens a drawing is FR-036's, from the pane, on the engineer's confirmation.)
- **FR-004**: The Standards tab MUST grade a drawing that is the open document, live.

**The guard, first (Foundational)**

- **FR-005**: Before any new drawing read is added, the read-only guard MUST refuse every member that writes, creates, deletes, activates, selects, closes, opens or reloads anything in the drawing, sheet, view, dimension, annotation, note, symbol and table families this feature reads, and the document activation, closing, creation and macro members of the application; the membership MUST be derived mechanically from the SOLIDWORKS 2024 SP5 interop and checked for completeness by a test.
- **FR-006**: The hardening MUST NOT widen or narrow the re-modeler's write allowlist (feature 004) and MUST NOT refuse any read the extractor performs; the one sanctioned read-only open of a model stays permitted, and the read-only open of a confirmed drawing (FR-053) is permitted only through its own allowlist entry.
- **FR-007**: Every extraction that reads a drawing MUST show, in its gate log, no mutating member, no sheet, view or document activation member, and no open or close member; the read of a confirmed drawing (FR-053) shows exactly its allowlisted open, visibility and close keys and nothing else of the kind.

**Attaching open drawings (US2)**

- **FR-008**: A review extraction of a part or assembly MUST read every drawing already open in SOLIDWORKS whose views show a document of the design, and no other drawing.
- **FR-009**: A drawing MUST be matched by the full path of the document its views show, never by file name alone.
- **FR-010**: Attached drawings MUST enter the design's document list, its manifest and its list of drawings, so the design's identity - and therefore the reuse of an earlier extraction - changes when the set of open drawings changes.
- **FR-011**: The grading extraction (Standards) and the model check extraction MUST attach no drawing; the Standards tab grades a drawing only when the drawing itself is open and pressed (006 FR-025 amended for the review extraction only).
- **FR-012**: For each reviewed document with no attached drawing, the extraction MUST record a drawing file of the same name in the same folder, when one exists, as a candidate; it MUST NOT open, fetch or list anything else; a failed existence check is a gap.
- **FR-013**: At most ten drawings MUST be read per extraction, the root document's first, then in design order; every open drawing not read MUST be named in a gap.
- **FR-014**: A review extraction that attached no drawing MUST say that no open drawing showed the design and how to include one, replacing today's sentence about the extraction profile.
- **FR-015**: Nothing MUST be opened, activated, loaded, resolved, rebuilt or saved to attach or read a drawing (006 FR-044), except the read-only open of a candidate the engineer confirmed (FR-036, FR-053 to FR-056), which activates, rebuilds and saves nothing.
- **FR-016**: Every drawing record's identifiers MUST be unique within the package when several drawings are read.

**Dimensions, tolerances and written precision (US3)**

- **FR-017**: For each drawing view the extraction MUST record the configuration it shows, whether it is out of date with its model, and whether its model is loaded.
- **FR-018**: For each drawing dimension the extraction MUST record its text parts as written (prefix, suffix, above, below), its precision and tolerance precision and whether they are the document's defaults, its unit, its tolerance in the same form feature 010 records a model dimension's, whether it is a reference, driven or driving dimension, whether it is a hole callout, and the model faces it is attached to where SOLIDWORKS says so.
- **FR-019**: For each drawing the extraction MUST record its length unit, its default dimension and tolerance precisions and its drafting standard; for each sheet, its sheet format file, scale and projection.
- **FR-020**: The tolerance resolver's drawing source MUST bind a subject only through a dimension in an attached or root drawing, in a view of the subject's document and configuration that is up to date, that is attached to one of the subject's faces or shows the one model dimension that sizes the subject; nothing looser binds.
- **FR-021**: A toleranced drawing dimension that binds MUST supply its limits; an untoleranced or block-toleranced one MUST supply its written precision and unit to the general tolerance; one governed by SOLIDWORKS' general tolerance table MUST supply neither and say why.
- **FR-022**: The general tolerance MUST bind by decimal places only when the dimension's unit is the unit the profile declares the bands are counted in.
- **FR-023**: Disagreeing drawing evidence for one subject MUST resolve to the first in a fixed order - drawing, sheet, view, dimension - with the conflict reported as a coverage limit; disagreeing precisions MUST bind no general tolerance.
- **FR-024**: No drawing value MUST enter a calculation until the seat probes have confirmed, on a drawing whose callouts are known, that each dimension's value, tolerance and unit are read as written and that the binding attaches each callout to the right hole; until then the drawing source MUST bind nothing and say so, and a native drawing dimension named to a fit, stack or alignment check MUST be declined, naming the seat validation, with no verdict computed. One switch governs both. *(Corrected 2026-09-23 on review, research R2.11: the native references of FR-025 were first left ungated.)*
- **FR-025**: The dimension and sheet tools the model already has, and the reference a fit or stack check takes, MUST read native drawing sheets as well as PDF-ingested ones, through one conversion; a check computes with a native dimension only as FR-024 allows.
- **FR-026**: Every value the extraction could not read MUST be a named gap, never an omitted or empty value.

**Callouts, symbols, notes and tables (US4)**

- **FR-027**: For each geometric tolerance, datum tag and surface finish symbol on a drawing, the extraction MUST record its frames or text as written and the model faces it is attached to where known, on the annotation record feature 006 already writes.
- **FR-028**: For each table on a sheet other than a revision table, the extraction MUST record its kind, title, row and column counts and every cell, and for a bill of materials the documents each row stands for where SOLIDWORKS says so; revision tables MUST stay exactly as feature 006 records them.
- **FR-029**: A position or coaxiality tolerance on a drawing, attached to a hole's faces and bound as FR-020 and FR-024 require, MUST be that hole's position tolerance for the stack-up; a zone value written without a unit MUST be read in the drawing's recorded length unit and cited so.
- **FR-030**: Notes MUST be recorded verbatim; no note is parsed into a tolerance in this feature.
- **FR-031**: The model-facing sheet tool MUST return these records for a native sheet.

**Questions in the pane (US5)**

- **FR-032**: The review's code-first pass MUST run one argument-free drawing check whenever the package carries drawing evidence (an attached or root drawing, or a candidate), and not otherwise.
- **FR-033**: The check MUST record per reviewed document what drawing evidence was read and what was not usable, as coverage, and MUST raise at most one question about all candidate drawings and at most one question per document shown by two or more open drawings, three such at most, each at most 140 characters with at most five options of at most 60 characters.
- **FR-034**: The questions MUST be ordinary evidence requests, written through the same writer the model's own requests use, so the pane's existing panel shows them and the existing batch route answers them.
- **FR-035**: A repeat of the check within one review MUST add nothing (feature 008's re-call guard).
- **FR-036**: The product MUST open a candidate drawing only when the engineer confirms, in answer to the candidate question, that it is the document's drawing, and MUST NOT open anything on any other answer. *(Amended 2026-09-23, owner, research R5 Q2: first written "MUST NOT open a candidate drawing on any answer".)*
- **FR-037**: A review of a package with no drawing evidence MUST offer the same tools, plan the same calls, open with the same digest and receive the same tool payloads as the same review before this feature; its findings MUST differ at most in the words that say why the drawing source bound nothing.

**The drawing brief (US6)**

- **FR-038**: A brief MUST be available for every part and assembly document of a package, from a model-facing tool offered when the package carries drawing evidence and from the command line always.
- **FR-039**: The brief MUST carry, in fixed order: the document; how it is assembled (feature 010's joints, partners and fasteners); the interfaces needing a callout with each subject's current tolerance and source or what is missing, and the position budget callout feature 010 computes; what the attached drawings cover; the engineer's answered questions about the document.
- **FR-040**: The brief MUST be bounded to 6,000 bytes of compact text, with every omitted item counted, and deterministic for a package and session.
- **FR-041**: The brief MUST carry no persistent reference and no profile value; it names the profile by identity and states conformance, never the profile's settings.
- **FR-042**: The brief MUST reuse feature 010's joint map, alignment callout and tolerance resolver, never recompute them.
- **FR-043**: The brief MUST carry a version so feature 012 can extend it additively.

**The profile's drawing section (US7)**

- **FR-044**: The standards profile MUST gain a version 3 with a required drawing section - accepted sheet formats, drafting standard, projection, drawing unit, drawing template, bill-of-materials template - each possibly empty; versions 1 and 2 MUST still load with the section absent.
- **FR-045**: The general tolerance MUST NOT be restated in the drawing section; the drawing unit states the unit feature 010's decimal-place bands are counted in.
- **FR-046**: Each attached or root drawing MUST be compared with the section's sheet formats, drafting standard, projection and unit; one finding per drawing MUST name every difference with the drawing's own value; an empty setting is skipped, never passed; the templates are recorded for feature 012 and not compared.
- **FR-047**: The comparison's finding MUST NOT close the checklist's drawing manufacturing inputs item and MUST NOT enter the Standards tab's release verdict.

**The read-only open of a confirmed candidate (US5; owner, 2026-09-23)**

- **FR-053**: A confirmed candidate MUST be opened read-only, through a guarded seam whose allowlist names exactly the open, visibility and close members it uses and nothing else; the request MUST name the reviewed document, never a path, and the path MUST be the candidate the extraction recorded, recomputed and checked by the add-in from its own record of the review.
- **FR-054**: The open MUST NOT change or save the drawing or any model, and MUST NOT activate the drawing or take focus from the engineer's window as far as the SOLIDWORKS API allows (probe D14).
- **FR-055**: The product MUST close the drawing after reading it when, and only when, the product opened it, also when the read fails; it MUST NOT close a drawing that was already open, or any other document.
- **FR-056**: The confirmed drawing MUST be read into the review's evidence exactly as an attached drawing is, with identifiers unique in the package and the ten-drawing bound kept, before the review resumes; the evidence MUST record that the review opened it, and any confirmed candidate not read MUST be named with why. The open MUST stay disabled until probe D14 has passed on the seat, and while it is disabled the review MUST say so.

**Integration**

- **FR-048**: Every new evidence field MUST be additive (evidence schema 1.6.0); packages written before it MUST load and serialize to their own bytes, and every check MUST treat an absent field as unknown.
- **FR-049**: Every new finding MUST carry the evidence the existing findings carry and be classed in the attention policy in the change that emits it.
- **FR-050**: Every tool array the existing ceiling is asserted on today - the review array, the slimmed review array and the two pre-run arrays, with and without a bridge - MUST stay under it in both provider encodings with the drawing tools offered. The bridged review arrays of a review whose pre-run has not completed were over the ceiling before this feature and are not asserted on; with the drawing tools offered they MUST be measured and pinned so any growth shows, and whether the ceiling holds them is the owner's question (research R2.20, R5 Q9). *(Scoped 2026-09-23 on review: as first written, "the model-facing tool array" took in arrays the ceiling has never held.)* *(Amended 2026-09-23 by the owner's decision 9A, research R5 Q10: the ceiling is asserted only on the arrays the pane sends by default - the two pre-run arrays with payload slimming, with and without a bridge - and on those arrays with the drawing tools offered; every other array a review can send, the review and slimmed review arrays with the drawing tools included, is measured and pinned per provider, never asserted, and each array is classified in `test_tool_payload.py`'s `ARRAY_KINDS`.)*
- **FR-051**: A replay of every recorded review MUST lose no finding, keep every finding replayable, and keep the contacts as they are: every contact group a fixture records (3, 2 and 0 on feature 008's three replay fixtures, which record the recorded runs' touching groups as contacts since 008 decision 3A) reproduced exactly, and none reclassified.
- **FR-052**: This feature MUST NOT create, modify or save any drawing or model; it needs no constitution exception.

### Key Entities

- **Attached drawing**: an open drawing whose views show a document of the design, read with it; its sheets, views and records.
- **Drawing candidate**: a drawing file of the same name beside a reviewed document, not open, never opened by the extraction; opened read-only by the product only when the engineer confirms it (owner, 2026-09-23).
- **Native drawing dimension**: a dimension read from a drawing, with its text parts, written precision, unit, tolerance, kind and the model faces it is attached to.
- **Drawing binding**: why a drawing dimension or annotation is, or is not, evidence about one subject: the view's document and configuration, whether it is up to date, and the attachment or model dimension that ties them.
- **Drawing table**: a table on a sheet with its kind, title and cells.
- **Drawing question**: an evidence request the drawing check raises, with its short question and options.
- **Drawing brief**: the bounded summary of one part for a model or an engineer.
- **Drawing standard**: the profile's drawing section.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: On the next sitting, pressing Standards on a multi-sheet drawing grades it, where today it fails on every drawing; the extraction's gate log shows zero writing, activating, opening or closing members.
- **SC-002**: On the next sitting, a review of a part or assembly with its drawings open reads each drawing that shows the design and no other, in every attempt, and opens nothing before the engineer confirms a candidate.
- **SC-003**: On the synthetic package, every joint subject that carries a drawing tolerance is resolved from the drawing with the drawing, sheet, view and dimension cited; no subject is bound from a view of another configuration or an out-of-date view.
- **SC-004**: On the synthetic package, every untoleranced drawing dimension with a known written precision and a matching band and unit receives the general tolerance, and none with an unknown precision, another unit or no band does.
- **SC-005**: Every sheet of every read drawing is either read or named in a gap: no sheet silently absent.
- **SC-006**: Any part's brief is at most 6,000 bytes, carries all five sections, and counts everything it left out.
- **SC-007**: Replaying every recorded review loses no finding, leaves none unreplayable, reproduces each fixture's recorded contact groups exactly (3, 2 and 0) with none reclassified, and offers the model the same tools as before.
- **SC-008**: A review raises at most four drawing questions, each answerable with one click or one line.
- **SC-009**: The read-only guard refuses every writing member of the drawing families on the 2024 SP5 interop, checked mechanically, and still refuses nothing the extractor reads.
- **SC-010**: On the next sitting, on a drawing whose callouts are known, the binding attaches every checked callout to the right hole before any drawing value is allowed into a calculation.
- **SC-011**: On the next sitting, a confirmed candidate is opened read-only with the composed flags, never becomes the active document, is read and closed; afterwards its file is byte-identical and not locked, no save flag rose, and a drawing the engineer had open is still open (probe D14).

## Assumptions

- **The drawing source binds nothing until the seat confirms it** (FR-024): the binding by attached face and by model dimension is built and tested with fakes, and enabled by one recorded change after the seat probe passes on a known drawing - the same pattern as feature 006's transparency polarity. The same switch keeps native dimensions out of the fit, stack and alignment checks: the model can find them and name them, and the checks decline them with the seat's reason until the switch is set.
- **Only open drawings are read by the extraction.** The extraction never opens a drawing. A candidate the engineer confirms is opened read-only by the product, read and closed (owner, 2026-09-23, research R5 Q2), which replaces the first default, "the engineer opens it and extracts again".
- **The Standards tab's graded set does not change**: a review's standards run does not grade attached drawings, and the Standards extraction attaches none (006 FR-025 amended for the review extraction only). A drawing is graded only when it is itself open (owner, 2026-09-23, research R5 Q3).
- **A review of a drawing root in the Review tab stays out of scope**: the engineer opens the part or assembly and its open drawing is read with it; the refusal says so.
- **At most ten drawings are read per extraction**, a bound on dump time; the rest are named.
- **The general tolerance table of SOLIDWORKS** (an ISO 2768 class) is recorded word for word, not converted, and binds nothing, consistent with feature 010's decision to keep no standard tolerance table in code; the company goes by decimal places only (owner, 2026-09-23, research R5 Q7).
- **A geometric tolerance value written without a unit** is in the drawing's own unit, as drafting practice reads it; the citation says so (owner, 2026-09-23, research R5 Q6).
- **Notes are recorded verbatim**; a general tolerance written in a note is shown to the engineer and never parsed into a tolerance; the profile's bands are the general source.
- **The drawing tools are offered only when the package carries drawing evidence**, so recorded reviews are unchanged; the brief is always available from the command line.
- **The brief's sections follow the roadmap**; when the owner's drawing-creation base repository is supplied, its expected inputs are evaluated and the brief is extended additively under a new brief version, in feature 012 if not before.
- **The profile values of the drawing section are the owner's** and arrive with the regenerated profile at the next sitting; the repository ships fictional placeholders (owner, 2026-09-23, research R5 Q4). The drawing conformance finding is a review finding only, never a release-verdict failure (R5 Q5).
- **The attention class of the one new finding** (manufacturing) is a first opinion for the owner's read-through, as feature 010's were.
- **Evidence schema 1.6.0 and profile version 3** are this feature's: feature 010 took 1.5.0 and version 2 (010 research R5).
- **Seat-dependent reads** (every read listed in the probes contract) are built behind reader seams with fakes and validated at the next sitting; none is trusted on a real document before its probe passes.
