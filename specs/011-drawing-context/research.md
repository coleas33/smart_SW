# Research: Drawing Context, Read Only

**Feature**: `011-drawing-context` | **Date**: 2026-09-23 | **Plan**: [plan.md](plan.md)

Phase 0 output from: the owner's direction of 2026-09-22 and the roadmap written from it
(`docs/history/roadmap-2026-09-22.md`); the ADR-001 amendment of the same day
(`docs/adr/0001-agentic-review-architecture.md`); a reading pass on 2026-09-23 at tip `287d4c3` over every
module the plan names - the extractor's drawing phase (`DrawingDumper`, `DrawingTraversal`,
`SwDrawingReader`), the attach (`SwSession`), the phase orchestration (`PackageWriter`), the
drawing-rooted traversal (`ComponentTreeDumper`), the read-only guard, the IR's drawing models in
both languages, feature 006's four drawing checks and its traversal, feature 010's tolerance
resolver, and the model-facing drawing tools; and a reflection pass on the same day over the
SOLIDWORKS 2024 SP5 interop assemblies installed on the development machine
(`SolidWorks.Interop.sldworks` 32.5.0.48 and `swconst`), read as metadata only - SOLIDWORKS was not
started, and has no licence on this machine. Where this document says VERIFIED, the file was
opened on 2026-09-23 or the interop member was reflected; VERIFIED never means a call behaves on a
seat - that is what section R4's probes are for. Line numbers are as of `287d4c3` and will drift;
every task re-verifies before editing.

No recorded package carries a drawing (the attach refusal, R3), so nothing in this feature is
measured against a recorded review; its fixtures are synthetic (R2.21).

---

## R1. What the sources are, and what is normative

| Source | What it is | Authority here |
|---|---|---|
| `spec.md` | Seven user stories, FR-001 to FR-052, SC-001 to SC-010 | Normative for what is built |
| The owner's direction, 2026-09-22 | Read-only drawing context before the next test: the attach fix, open drawings attached, native dimensions, tolerances, notes and tables, a per-part brief, pane questions; creation (012) after seat probes and a constitution amendment, from the owner's base repository | The scope; nothing outside it is built |
| The roadmap's feature 011 section | The six bullets, including the guard "hardened against every drawing and tolerance setter first", the same-name drawing "offered as a question, never opened silently; the vault never walked", and the profile's `drawing` section | The design intent the stories trace to |
| ADR-001 amendment 2026-09-22 | Layer 3 in two stages; SOLIDWORKS 2024 SP5 has no auto-generate drawing API | Stage one is this feature; nothing here creates a drawing |
| Feature 006 (`specs/006-standards-check/`) | The native drawing phase, the drawing-rooted traversal, the four drawing checks, FR-024, FR-025, FR-044 | Reused unchanged except where R2.3 amends FR-025 for the review extraction |
| Feature 010 (`specs/010-mechanical-checks/`) | The resolver's five sources with the drawing slot (`contracts/tolerances.md` section 6), profile version 2's general tolerance by decimal places (research R5), the joint map, the position budget callout | The consumer; 011 fills the slot and changes nothing else in 010's checks |
| Features 008 and 009 | The code-first pass, the re-call guard, the answer batch, the replay; the "Questions for you" panel | The routes 011's questions and check use unchanged |
| The constitution 1.1.0 | Principles I to VI; "Documents are read, not written" with two exceptions | The gate; this feature adds no exception |

## R2. Decisions, alternatives and rationale

### R2.1 The attach: a dump accepts a drawing; everything that needs a model still declines it

**Decision**: `SwSession.Attach` keeps its meaning - a session bound to a model and its active
configuration, refusing a drawing by name - for every caller that needs a model: the tool
service and its bridge, the terminal, the review's reuse probe, interference, suppress test,
remodel. A second entry point, `SwSession.AttachForDump`, used by the extraction paths only
(`SwDump.Run`, the add-in's `SwReviewDump.Run`, the console's `dump` command and `probe
standards`), accepts a part, an assembly or a drawing. A drawing session binds **no
configuration**: `ISwSession.Configuration` becomes nullable and `ISwSession.ConfigurationName`
(the configuration's name, or null for a drawing) is what every extraction consumer reads. The
refusal sentence becomes `SwSession.AttachRefusal(kind, path, purpose)`, pure, with the purpose
`Model` or `Dump`, so the rule and both sentences are testable with no SOLIDWORKS. A drawing path
that is not open is declined by `AttachForDump` with its own sentence (FR-003): the extractor's one
file-opening call (`OpenReadOnly`) opens models only, because opening a drawing loads every model
its views reference, which is exactly the session change FR-044 forbids.

**Why**: VERIFIED `Attach` calls `AttachRefusal(KindOf(document), path)` at
`extractor/SwReview.Extractor/Sw/SwSession.cs:78` before `ActiveConfiguration` at `:84`, and the
refusal (`:113`) returns a sentence for every drawing. That refusal (commit `96785d1`, 2026-09-18)
fixed a real failure - a drawing active at add-in load took the whole tool service down - and it
must stay for the tool service. But every extraction path goes through the same `Attach`:
`SwReviewDump.Run` (`extractor/SwReview.AddIn/Review/SwReviewDump.cs:67`), which the Standards tab
calls for a drawing (`StandardsHost.cs:127` lists `drawing` as gradable), `SwDump.Run`
(`SwDump.cs:78`) and `probe standards` (`Program.cs:1792`). Before 2026-09-18 the same attach failed
on `ActiveConfiguration` instead, so **no drawing has ever been extracted live** - feature 006's
PROBE-4 to PROBE-7 and PROBE-10 (006 tasks T103, T105) and its drawing scenario (T107) have been
unreachable, not merely unrun. VERIFIED the consumers of the session's configuration:
`ComponentTreeDumper.Traverse` reads `Configuration.Name` (`ComponentTreeDumper.cs:111`) before it
branches on the root kind (`:136`), so the order must change for a drawing root; `SwScope`, the
console's logging and `SwReviewDump` read `Configuration.Name` for display and for
`DumpOptions.Configuration`. The drawing-rooted forest already reads each referenced model's own
configuration (`AddReferencedSubtree`, `:560-563`), which is the configuration that matters.

**Alternatives**: removing the refusal (rejected: brings back the 2026-09-18 failure in the tool
service); binding a drawing session to its first view's configuration (rejected: a drawing has
none, and a guessed one would stamp the design with a configuration nobody chose); a boolean
`allowDrawing` parameter on `Attach` (rejected: a call site reading `Attach(app, null, null,
true)` says nothing; two named entry points say what each caller needs); opening a closed drawing
read-only from the console (rejected: FR-044).

### R2.2 The guard is hardened first, mechanically, from the interop itself

**Decision**: before any new drawing read lands, `ReadOnlyGuard` refuses:

1. **Every writer of the 24 drawing families** - `IDrawingDoc`, `ISheet`, `IView`,
   `IDisplayDimension`, `IDimension`, `IDimensionTolerance`, `IAnnotation`, `INote`, `IGtol`,
   `IGtolFrame`, `IDatumTag`, `ISFSymbol`, `ITableAnnotation`, `IBomTableAnnotation`,
   `IBomFeature`, `IRevisionTableAnnotation`, `IGeneralTableFeature`, `ITitleBlockTableFeature`,
   `ITitleBlock`, `IDatumTargetSym`, `ICenterMark`, `IWeldSymbol`, `IDowelSymbol`,
   `IMultiJogLeader` - where a writer is a public method whose name matches the writer grammar of
   `contracts/guard.md` section 2 (setters, adders, inserters, deleters, editors, activators,
   selectors, openers, closers, reloaders, savers and the like) and does not start with `get_`,
   `Get`, `IGet` or `Is`;
2. **The named members of the shared families** a drawing read touches: the application's
   document activation, visibility, closing, creation, opening and macro members, and the
   document extension's `SetUserPreference*` writers beside the `GetUserPreference*` reads.

Two exclusions, each named: the bare names of feature 004's stage-1 allowlist keys (on these
families: `set_Name` and `Select2`; on the shared ones `CloseDoc` and `SetUserPreferenceToggle`),
because a bare denial of them would make a re-modeler key override a read-only denial and move
feature 004's pinned five; and `OpenDoc6`, the extractor's one sanctioned read-only open. The
membership is **generated, never transcribed**: a reflection script prints it as the "Feature 011"
table of `specs/004-resilient-remodeler/contracts/guard-allowlist.md`; one test parses the table and
asserts every member refused, and one test reflects the interop at test time and asserts the table
is complete for the 24 families. *Corrected 2026-09-23 on review*: 28 families - the hole callout's
four variable interfaces (`ICalloutVariable`, `ICalloutLengthVariable`, `ICalloutAngleVariable`,
`ICalloutStringVariable`), which T026's hole-callout read touches, joined the list, and the
regenerated table denies twelve more of their writers (`contracts/guard.md` section 1).

**Why**: the roadmap asks for the guard "hardened against every drawing and tolerance setter
first", and feature 012 will need a gated creator whose allowlist overrides exactly the members
it uses - so every drawing writer must be refused by default before any drawing-writing code
exists. VERIFIED by reflection on 32.5.0.48: the grammar matches 621 distinct names across the 24
families (*landed as 633 by the generator, T004; the generated table in 004's `guard-allowlist.md`
is the count*) (`IDrawingDoc` 216, `IView` 81, `IDisplayDimension` 73, `ITableAnnotation` 50,
`IAnnotation` 39, `INote` 34, `IGtol` 26, `ISheet` 22, `IDimension` 19, `IBomFeature` 17,
`ICenterMark` 10, `ISFSymbol` 10, `IDimensionTolerance` 9, `IBomTableAnnotation` 9, `IDatumTag` 6,
`IDatumTargetSym` 6, `IWeldSymbol` 6, `IGtolFrame` 5, `IRevisionTableAnnotation` 3, `ITitleBlock` 1,
`IDowelSymbol` 1, three with none); 39 of them are already denied by features 001, 006 and 010,
`set_Name` and `Select2` are the two re-modeler exclusions, and **580 are new**. VERIFIED no bare
name the extractor passes to `SwGate.Call` today collides with a new denial (183 gated names;
the only matches are `ActivateSheet` and `ActivateView`, already denied and named in tests, and the
re-modeler's `Feature.Select2` write site, excluded). *Corrected 2026-09-23 by T003's read audit*:
feature 004 gates `OpenDoc7` and `NewDocument` by bare name through constants, which the literal
scan missed; both are excluded from the shared row with that reason (`contracts/guard.md`
section 3). A hand list of 580 names would be a
transcription that drifts; the tolerance lesson of feature 005's figures ("regenerated, never
transcribed") applies. The guard stores bare names (`ReadOnlyGuard.cs:35`), so the families are
denied by name; an interface-qualified guard is feature 004's pattern for writes and is not needed
for denials.

**Alternatives**: only the setters beside each read, as features 006 and 010 did (rejected: the
roadmap says every setter, and a partial list is what 012 would have to audit); a `set_` prefix
denial (rejected: it denies `set_Name`, `set_Description` and `set_Equation` and so moves feature
004's allowlist, and it misses `Insert*`, `Delete*`, `Activate*`); a hand-typed table (rejected:
580 names).

### R2.3 Which drawings are attached, and when

**Decision**: a review extraction (`DumpProfile.Full`) of a part or assembly root **discovers**
the drawings open in SOLIDWORKS between the traversal and the document phase: it enumerates the
application's open documents (`ISldWorks.GetDocuments`), keeps those of type drawing, and for each
reads the path of the document every view references (`IDrawingDoc.GetViews` - every sheet's
views, no activation - then `IView.GetReferencedModelName`). A drawing is **attached** when any
referenced path equals, compared case-insensitively after `Path.GetFullPath` normalisation, the
path of a document the traversal reached. Attached drawings are read by the existing `drawing`
phase, in order: drawings showing the root document first, then by the traversal position of the
first document they show, then by path; at most **ten** per extraction, every further one named
in one `drawing_attachment_limit` gap. Their paths join `DocumentPaths(tree)`, so they enter
`documents[]` and the manifest; `design.drawing_document_ids` lists them. Discovery is **not a
phase row** (the phase list stays the same twelve names), runs in the reuse probe too (the key is
taken over the manifest, which now includes the drawings, FR-010), and records its failures as
`drawing_discovery` gaps. Under the `Standards` and `ModelCheck` profiles nothing is discovered:
feature 006's FR-025 stands for grading (FR-011), amended for the review extraction only - the
amendment is recorded in 006's spec before any code (T001).

**Why**: VERIFIED the drawing phase runs only for a drawing root
(`PackageWriter.cs:282-296`, the comment "The dump does not go looking for the drawings of an open
model") and `design.drawing_document_ids` "carries the drawing root and nothing else"
(`:596-607`); VERIFIED 006 FR-025's last sentence forbids discovery. The owner's 2026-09-22
decision reverses it for reviews. Discovery must precede the document phase because the drawing's
own document row (properties, revision) is read there and the manifest is built from it
(`:193-203`). The Standards tab's graded set is left alone because a release verdict that depends
on which windows happen to be open is not reproducible; a review's evidence may depend on it, and
says so. Ten drawings bounds the dump: 006's SC-013 budgets a six-sheet drawing at 10 s, and an
engineer with thirty drawings open should not wait five minutes for a review to start. Matching by
full path, never by file name, follows the traversal's own rule that file base names collide
(`ComponentTreeDumper.cs:345-352`: a drawing is named after its model).

**Alternatives**: attaching in the Standards extraction too (rejected: reproducibility of the
release verdict; an owner question, R5); matching by file name (rejected: collisions); reading
every open drawing (rejected: unbounded dump time and evidence about documents outside the review);
a new `drawing_discovery` phase row (rejected: every package's phase list and the reuse-key
goldens would move for a step that is milliseconds).

### R2.4 A drawing file beside a reviewed document is a candidate, never opened

**Decision**: for every reviewed part or assembly document with no attached drawing, the
extraction asks whether `<folder>\<file stem>.SLDDRW` exists - one `File.Exists` per document,
behind a seam - and records each that does as a `DrawingCandidate`. It never opens, lists, fetches
or reads the file, never looks at another name, and never looks in another folder ("the vault
never walked"). A check that throws is a `drawing_candidate` gap. The candidate is offered to the
engineer as a question (R2.15).

**Why**: the owner's wording: "a same-name drawing next to the part offered as a question, never
opened silently; the vault never walked". The existence check is a filesystem metadata read; in an
EPDM vault view a file not cached locally is a placeholder whose existence answers without a
download - which is probe D13, so until it answers, a thrown or slow check is a gap and not a
guess. Only one exact name is tried: numbering conventions (`-SHT1`, a revision suffix) are the
company's and would be a guessed pattern.

**Alternatives**: opening the candidate read-only when found (rejected: nothing is opened without
the engineer's word; *amended 2026-09-23*: the owner answered R5 Q2 yes, so a candidate the
engineer **confirms** is opened read-only, R2.23); searching the folder for any drawing (rejected:
the vault is not walked); checking in Python (rejected: the reviewer may run on a machine that
cannot see the vault; the extractor runs where the files are).

### R2.5 Several drawings in one package: one set of identifiers, one reader per drawing

**Decision**: the six drawing id allocators (`dsh`, `dvw`, `ddm`, `dan`, `dnt`, `drv`) and the new
`dtb` (tables) move from `DrawingTraversal` to `DumpScope`, beside `cut:` and `mdm:`, so ids are
unique across every drawing a package reads; a drawing root's single record numbers exactly as
today (it is the first and only drawing). `IDrawingReader` gains the drawing document as an
argument where it read the session's document - `Drawing(object document)` and
`PersistRef(object document, object entity)` - so one reader serves the root and every attached
drawing, and each record's persistent references are scoped to its own drawing.

**Why**: VERIFIED the allocators live on the traversal instance "because one package carries at
most one drawing record" (`DrawingTraversal.cs:30-41`), and `SwDrawingReader` reads the session's
document for both the drawing handle and the persistent-reference scope
(`SwDrawingReader.cs:47`, `:193`). Feature 006's checks already key everything by id - a sheet's
`drawing_sheet_views` gap is found by the sheet id (`checks/standards/drawing.py:354-356`) - so two
drawings numbering their sheets `dsh:0001` would attach one drawing's gap to the other's sheet.
VERIFIED feature 006's Python already handles several records: `drawing_scope` and
`_referenced_documents` filter `drawing_records` by document id (`drawing.py:343-351`,
`traversal.py:221-236`).

### R2.6 What a view knows about itself

**Decision**: each `DrawingView` gains `referenced_configuration` (`IView.ReferencedConfiguration`),
`is_model_out_of_date` (`IView.IsModelOutOfDate`), `is_model_loaded` (`IView.IsModelLoaded`),
`scale_decimal` and `orientation_name`; each `DrawingRecord` gains `is_detailing_mode`
(`IDrawingDoc.IsDetailingMode`). A view's evidence binds a subject only when its configuration is
the one the package recorded for the subject's component and it is read as not out of date (R2.8).

**Why**: FR-017 and the edge cases. A drawing view of another configuration shows other dimensions;
an out-of-date view shows geometry the model no longer has; detailing mode loads no model. VERIFIED
all five members exist on 32.5.0.48 (reflection); their answers on a seat are probe D12.

### R2.7 What a drawing dimension carries

**Decision**: `DisplayDimensionRecord` gains, each optional and omitted when null:
`text_prefix`, `text_suffix`, `text_above`, `text_below` (`IDisplayDimension.GetText` with
`swDimensionTextParts_e` 1 to 4, VERIFIED values); `precision_raw`, `tolerance_precision_raw`
(`GetPrimaryPrecision2`, `GetPrimaryTolPrecision2`), `uses_document_precision`
(`GetUseDocPrecision`), `units_raw` and `uses_document_units` (`GetUnits`, `GetUseDocUnits`);
`tolerance`, `tolerance_type_raw`, `fit_hole_class`, `fit_shaft_class` (`IDimension.Tolerance`,
read and mapped by **the same code** feature 010's `ToleranceDumper.KindOf` and `IsFitType` use for a
model dimension); `is_reference` (`IsReferenceDim`), `driven_state_raw` (`IDimension.DrivenState`),
`is_hole_callout` (`IsHoleCallout`), `hole_callout_variables_raw` (`GetHoleCalloutVariables`,
verbatim); and `attached_faces` (R2.8). Each `DrawingRecord` gains the document-level settings the
precision reading needs: `length_unit_raw` (`swUnitsLinear`, 47), `dimension_precision_raw`
(`swDetailingLinearDimPrecision`, 24), `units_decimal_places_raw` (`swUnitsLinearDecimalPlaces`,
49), `tolerance_precision_raw` (`swDetailingLinearTolPrecision`, 25) and `drafting_standard_name`
(`swDetailingDimensionStandardName`, string 65), read with
`IModelDocExtension.GetUserPreference*`; each `DrawingSheetRecord` gains `sheet_format_path`
(`ISheet.GetTemplateName`), `scale_numerator`, `scale_denominator` and `first_angle`
(`ISheet.GetProperties2` items 2, 3 and 4).

**Why**: FR-018 and FR-019. The general tolerance goes by decimal places (owner, 2026-09-23) and
only a drawing records how many decimals a dimension is written to; VERIFIED feature 010 left
`ToleranceSubject.decimal_places` waiting (`checks/tolerances.py:100`) and its general source
binds nothing without it (`:316-320`). VERIFIED every member and enum value above on 32.5.0.48;
what `GetPrimaryPrecision2` answers when `GetUseDocPrecision` is true, and which of
`swDetailingLinearDimPrecision` and `swUnitsLinearDecimalPlaces` (49) governs a document-precision
dimension, is probe D4 - both are recorded until it answers, and a precision that cannot be
decided is unknown. The display text is recorded as its parts plus the value and precision, and
composed in Python for the brief and labelled composed; whether an annotation's rendered text is
readable whole is probe D7. One tolerance mapping for model and drawing dimensions is DRY across
the two languages' readers: a drawing's model-item dimension is the same `IDimension`, with the
same tolerance.

### R2.8 Binding a drawing dimension to a subject, and why it ships disabled

**Decision**: a drawing dimension or annotation is evidence about a subject (a hole instance's
size or position, a pin's size, feature 010's `ToleranceSubject`) only when **all** of these hold:
it sits in a view whose `referenced_document_id` is the subject's document; the view's
`referenced_configuration` equals the configuration the package recorded for the subject's
component; the view reads `is_model_out_of_date == false`; a display dimension reads
`is_overridden == false` (an overridden value is not the model's, the defect feature 006's
`dimensions_not_overridden` reports); and **either** its `attached_faces`
include one of the subject's face persistent references (scoped to the subject's part document),
**or** it is a model-item dimension whose name identifies the one `ModelDimension` feature 010's
source 3 would bind to the subject (unique by value in the document). A size subject binds only a
diameter or radius dimension or a hole callout; a position subject only a geometric tolerance
(R2.13). The attachment is read as `IAnnotation.GetAttachedEntities3` on the dimension's
annotation, each original entity's part owner resolved before it is mapped to the model through
that owner's `IModelDocExtension.GetCorrespondingEntity2`, a face kept, an
edge replaced by its two adjacent faces (`IEdge.GetTwoAdjacentFaces2`, recorded `via: edge`), and
the model entity's persistent reference taken from its owning part document - the path is probe D6,
and for an assembly drawing the part context is reached through the entity's component, which is
probe D6's second half. The model-item identity is `IDimension.FullName` against feature 010's
`ModelDimension.name`, compared on the part before the document suffix, because a drawing may
spell the document differently (probe D8).

**The binding ships disabled.** `drawings/binding.py` holds one constant,
`DRAWING_BINDING_VALIDATED = False`; while it is false the resolver's drawing source binds nothing
and supplies no precision, and `resolve_dimension` refuses a native reference (R2.11), with the
reason "drawing callouts are read but not yet validated on a
seat against a drawing whose callouts are known (feature 011 research R2.8)". Every test of the
binding sets it; the seat task that records probe D6's and D8's pass on a known drawing (T066)
flips it, one constant and one edit, as feature 006's `TRANSPARENCY_POLARITY` is flipped after
PROBE-2.

**Why**: FR-020, FR-024 and Principle III ("Findings from tool output whose correctness is
unverified on the pilot workstation MUST NOT enter a calculation until a test against a known case
passes"). A binding that attaches a Ø3.1 H7 to the wrong hole is an authoritative-looking wrong
stack-up; nothing in the repository has ever seen a drawing's attached entities or its persistent
references. The two routes cover the two ways a drawing dimension exists: a model item imported
from the part (whose tolerance is the model's, the RMS rule "drawings use model items") and a
reference dimension the drafter added in the drawing (whose only tie to the model is what it is
attached to). VERIFIED every member named exists on 32.5.0.48, including
`IView.GetCorrespondingEntity(Object)` and `IModelDocExtension.GetCorrespondingEntity(Object)`.

**Alternatives**: binding by value alone, as source 3 does (rejected for the drawing: a drawing
shows many equal diameters, and a drawing's value is the model's, so value adds nothing source 3
lacks); binding by view proximity or position on the sheet (rejected: the PDF ingest's heuristic,
`tools/query._near_view`, is a layout guess, not evidence); enabling the source when the tests pass
(rejected: fakes prove the code, not SOLIDWORKS' answers).

### R2.9 Written precision and the general tolerance

**Decision**: a subject's `decimal_places` is the written precision of the drawing dimension that
binds it (R2.8): `precision_raw` when `uses_document_precision` is false, the drawing's
`dimension_precision_raw` when it is true (or `swUnitsLinearDecimalPlaces` if probe D4 says that is
what governs), unknown when either needed read is missing. The dimension's unit is `units_raw` when
`uses_document_units` is false, else the drawing's `length_unit_raw`. The general source binds only
when the dimension's tolerance type is `NONE` (0) or `BLOCK` (10) - "no tolerance of its own" - the
profile has a band for those decimal places, and the dimension's unit is the profile's
`drawing.dimension_unit` (R2.17). A `GENERAL` (11) dimension is governed by SOLIDWORKS' general
tolerance table (an ISO 2768 class); it supplies nothing, and the reason names the table.
Disagreeing precisions for one subject (two drawings, or two dimensions) bind nothing and say so.

**Why**: FR-021, FR-022 and FR-023. VERIFIED `swTolType_e` on 32.5.0.48: `NONE` 0, `BASIC` 1,
`BILAT` 2, `LIMIT` 3, `SYMMETRIC` 4, `MIN` 5, `MAX` 6, `FIT` 7, `FITWITHTOL` 8, `FITTOLONLY` 9,
`BLOCK` 10, `GENERAL` 11 - feature 010's mapping already reads `BLOCK` and `GENERAL` as "no IR kind"
(`ModelDimension.tolerance` docstring). `BLOCK` is SOLIDWORKS' name for the tolerance by decimal
places; `GENERAL` points at a general-tolerance table (`swTableAnnotation_GeneralTolerance` 9,
VERIFIED). Converting an ISO 2768 class to limits is a standard table in code, which feature 010
R2.18 rejected. The unit rule closes a real gap in profile version 2: its bands are `plus_minus_mm`
by decimal places, but ".XX" means hundredths of a millimetre on a metric drawing and hundredths of
an inch on an inch one; the profile does not say which, so version 3 does (R2.17).

### R2.10 The resolver's drawing source

**Decision**: `drawing_tolerance(package, subject)` (feature 010's slot, `checks/tolerances.py:350`)
becomes `drawing_answer(package, subject) -> DrawingAnswer`, carrying the bound `Dimension` or
`None`, the citation, the `decimal_places` and unit it read, the alternatives it saw and the reason
when nothing bound. `resolve_tolerance` walks the sources as today; when the drawing binds no limit
but supplies a precision, the general source is asked about a copy of the subject with
`decimal_places` set - nothing else changes in 010's precedence, conflict and `also_found` rules.
Candidate drawing evidence for a subject is ordered by drawing document id, sheet index, view id,
dimension id; the first that binds wins, and a later one with different limits is a conflict of the
drawing source itself, reported in the same `conflict` sentence. `ResolverLookup.holds_any_source()`
is true also when some drawing dimension could bind - a toleranced one, or an untoleranced one with
a recorded precision under a profile with bands - and only while `DRAWING_BINDING_VALIDATED`.

**Why**: FR-020 to FR-023 and feature 010 `contracts/tolerances.md` section 6: "011 fills it and the
stack-up and `refs.resolve_dimension` read the same records under the same citation rules". VERIFIED
`DRAWING_NOT_AVAILABLE` (`:341`) is the reason the slot returns today and `resolve_tolerance`
consumes it at `:535-537`; VERIFIED `holds_any_source` (`:594-617`) says the general block binds
nothing "because no subject's written precision is recorded before feature 011". The return type
changes because a precision without a limit is an answer the old signature cannot carry; the slot
has one caller.

### R2.11 Native dimensions through the tools the model already has

**Decision**: one conversion, `drawings/native.py native_dimension(record, view, sheet, drawing) ->
Dimension`, builds the IR `Dimension` (nominal from `value` in its unit, the tolerance, a
`SourceRef` of the drawing document, the sheet name and the `ddm:` id, and `text_as_read` composed
from the text parts and the precision). `refs.resolve_dimension`, `query.find_dimensions` and
`query.get_drawing_sheet` read native sheets through it beside the PDF-ingested ones; a native
sheet wins over an ingested sheet of the same name and both are listed with their source. The three
tools' docstrings do not change; their payloads change only for a package that has native sheets.

**Why**: FR-025. VERIFIED all three read `package.drawings` only (`tools/refs.py:47-67`,
`tools/query.py:628-661`, `:680-722`), so a live drawing would be invisible to `check_fit` and
`check_axial_stack`, whose references are resolved by `resolve_dimension`. The docstrings stay
because each is pinned to the byte in the tool array (`test_tool_payload.py`), and a package with
no native sheet must replay byte-identically (FR-037).

**Corrected 2026-09-23 on review: a native dimension enters no calculation before T066.** As first
written, `resolve_dimension` resolved a native `ddm:` reference with no gate, so `check_fit`,
`check_axial_stack` and `check_hole_alignment`'s `tolerance` would have computed with a drawing's
value, tolerance and unit before probes D4, D5 and D7 confirmed them - while FR-024, the plan's
constraints, the tasks' Notes and Principle III ("a drawing reader with known unit bugs") forbid
exactly that. So `resolve_dimension` reads R2.8's `DRAWING_BINDING_VALIDATED`: while it is false, a
reference that resolves to a native dimension is refused with a `LookupError` carrying R2.8's
reason, and each check returns the error result it already returns for an unresolvable reference,
recording no finding. `find_dimensions` and `get_drawing_sheet` still return native records -
showing a value is not computing with one - and a PDF-ingested dimension resolves as today. One
switch rather than two, because T066 already waits on T064 and T065, which record D4, D5 and D7;
T066 now also confirms those answers against `native_dimension` before it sets the switch. No owner
decision was needed: FR-024 and Principle III had already decided it, and the correction brings US3
acceptance 5, FR-025, T036 and T037 into line with them.

### R2.12 Annotations and tables: enrich the records feature 006 already writes

**Decision**: a `DrawingAnnotation` of type geometric tolerance (5) gains `gtol_frames`
(feature 010's `GtolFrame`, reused) and `datum_identifier_raw`; of type datum tag (2) `datum_label`;
of type surface finish (7) `surface_finish_symbol_raw` (`ISFSymbol.GetSymbol`) and
`surface_finish_texts_raw` (`GetTextAtIndex` for `GetTextCount` slots); every typed annotation
`attached_faces`. The reads reuse feature 010's `IModelAnnotationReader` members (`FrameCount`,
`FrameValues`, `FrameSymbols`, `FrameXml`, `DatumIdentifier`, `DatumLabel`). Tables other than
revision tables become `DrawingTable` records on the sheet (`dtb:`), with `table_type_raw`,
`title`, `row_count`, `column_count` and `rows` of feature 006's `RevisionTableRow` (reused), and for
a bill of materials `bom_rows` - per row the documents it stands for
(`IBomTableAnnotation.GetModelPathNames`, resolved to package document ids, unresolved paths kept).
The per-view table walk feature 006 wrote for revision tables (`DrawingDumper.ReadRevisionTables`)
becomes the walk for every table, filtering revision tables into their existing list unchanged.
Notes stay `DrawingNote` with their text.

**Why**: FR-027 to FR-031. Enriching the existing annotation record rather than adding a second
walk keeps one enumeration of `IView.GetAnnotations` and one identity per annotation (VERIFIED
`DrawingDumper.ReadAnnotations`, `:614-657`); a separate GTol list would give one annotation two
ids. VERIFIED `swAnnotationType_e` on 32.5.0.48: `swDatumTag` 2, `swDisplayDimension` 4, `swGTol` 5,
`swNote` 6, `swSFSymbol` 7, `swTableAnnotation` 14; `swTableAnnotationType_e`: General 0, HoleChart
1, BillOfMaterials 2, RevisionBlock 3, WeldmentCutList 4, TitleBlock 5, WeldTable 6, BendTable 7,
PunchTable 8, GeneralTolerance 9. VERIFIED the revision-table filter is `RevisionBlockTableType = 3`
(`DrawingDumper.cs:205`) and the cell loop (`:762-794`) is exactly the loop every table needs.

### R2.13 A drawing's position tolerance, and its unit

**Decision**: a position or coaxiality frame on a drawing annotation, bound to a hole instance as
R2.8 requires, is source 1 for that instance's `hole_position` subject, read by feature 010's
`_frame_zone` generalised to take frames. A zone value written without a unit is read in the
drawing's recorded length unit (`length_unit_raw`), and the citation says "read in the drawing's
unit, mm"; with the unit unread, it binds nothing.

**Why**: FR-029. Feature 010 declined a unitless model-annotation zone because "the part's length
unit is not in the package" (010 `contracts/tolerances.md` section 4, as built). A drawing states
its unit; a number written on a drawing without a unit is in that unit by the drawing's own
declaration, which is evidence, not inference. An owner question confirms the reading (R5).

### R2.14 The drawing check joins the pre-run the way the standards check does

**Decision**: one argument-free tool, `check_drawings()`, and one query tool,
`get_drawing_brief(document_id)`, form a new **drawing family** in `tools/drawings.py`, offered by
`ToolRegistry._offered` only when the package carries drawing evidence - a drawing record or a
drawing candidate - exactly as the standards, bridge and remodel families are offered on their
conditions. `prerun.planned_calls` plans `check_drawings` after the `CODE_FIRST_CHECKS` and before
`check_standards`, under the same condition, as it plans `check_standards` today; 008's re-call guard
keys it `(tool,)`. `check_drawings` records per reviewed document one `drawing.context` coverage row
(what drawing evidence was read and what was not usable, and why), raises the questions of R2.15,
and, from US7, the conformance findings of R2.18; it returns counts. The digest line reads
`check_drawings() -> ok, <n> drawings, <m> candidates, <q> questions`.

**Why**: FR-032 to FR-037. VERIFIED `planned_calls` already has one conditional branch, the
standards check (`prerun.py:706-707`), and the three conditional families exist in `_offered`.
`CODE_FIRST_CHECKS` is the wrong hook: feature 010's contract section 1 makes every name in it an
unconditional tool of `check_tools()`, and a test asserts it. Offering the family only with drawing
evidence is what keeps every recorded review - none has a drawing - byte-identical in its tool array
and digest, so feature 008's replay figures and the pinned array bytes do not move (FR-037, SC-007);
the drawing arm is pinned separately (R2.20).

**Alternatives**: adding `check_drawings` to `CODE_FIRST_CHECKS` and always offering the brief
(rejected: every recorded review's tool array grows by about a kilobyte per round, the slim array
reaches the ceiling, R2.20, and 008's recorded figures move for packages that have no drawing); a
predicate table beside `CODE_FIRST_CHECKS` (rejected: a second registration mechanism for one tool).

### R2.15 The questions

**Decision**: `check_drawings` raises at most:

- **one candidate question** when the package has drawing candidates: question "A drawing with the
  same name sits beside {n} reviewed file(s) but is not open. Should the review read it?", options
  `Yes, open it read-only and read it`, `Review without it`, `It is not the right drawing`
  (*amended 2026-09-23*, owner, R5 Q2: the first option was `I will open it and review again`;
  the confirmation now has the product open the candidate read-only, R2.23); `what` names the
  candidate files (first ten, then a count); `why` says fits, stacks and callouts stay unresolved
  without a drawing and that the review opens a file only read-only and only when the engineer
  confirms it; `entity_ids` the documents' ids;
- **one governing-drawing question per document shown by two or more attached drawings**, three
  at most, in traversal order: question "{k} open drawings show {file stem}. Which one governs it?"
  truncated to 140 characters by shortening the stem, options each drawing's file name when there
  are at most four and each fits in 60 characters, plus `They all apply`; otherwise no options.

Each is an ordinary `EvidenceRequest` written through the writer `request_evidence` uses, extracted
into `tools/session.record_evidence_request` (the tool keeps its refusals; the writer allocates the
id, validates through the model and emits the event), so the pane's panel and 008's batch route
serve them unchanged. `blocks` is `drawing.manufacturing_inputs` for the candidate question and
unset for the governing one.

**Why**: FR-033 to FR-036 and SC-008. VERIFIED `EvidenceRequest` enforces a question of at most 140
characters, at most five options of at most 60, distinct (`report/session.py:88-133`), and
`request_evidence` accepts document ids (`tools/session.py:92-94`). One aggregated candidate
question, not one per part: in an assembly most parts may have a drawing beside them, and thirty
questions would bury the panel. The governing question matters because two open drawings of one
part can disagree, and only the engineer knows which is released. A configuration mismatch or an
out-of-date view is **not** a question: the engineer cannot change what was extracted by answering,
and coverage says it.

### R2.16 The brief

**Decision**: `drawings/brief.py build_brief(package, session, profile, document_id) -> DrawingBrief`,
served by `get_drawing_brief(document_id)` and `swreview drawing brief`, with `brief_version: 1` and
five sections in fixed order - `document`, `assembly`, `interfaces`, `drawing`, `answers` - plus
`conformance` (from US7) and `omitted` (per list, what was left out). It reuses feature 010's
`build_joint_map` through `tools/joint_context.py` (cached per session), `check_nominal_alignment`'s
`callout` output, and `ResolverLookup`, and never recomputes them. Bounds: 20 joints (folded by
pattern group, as 010 folds findings), 20 interface subjects, 10 notes of at most 200 characters
each, 5 tables of at most 10 rows, 10 answers, 10 candidate files; the whole compact JSON at most
**6,000 bytes**, trimmed deterministically from the end of the longest list when a pathological
package exceeds it, every trim counted in `omitted`. No persistent reference and no profile value
appears in it.

**Why**: FR-038 to FR-043. 6,000 bytes is about 1,500 tokens (o200k): cheap to resend under 008's
history pruning, where one unbounded RMS result was once half a review's bill. VERIFIED 010's
position budget callout is computed in `checks/joint_alignment.py` (`_callout`, `:251`, carried as
`callout` in the result, `:329`), and the joint map is shared through `tools/joint_context.py`
(`joint_analysis`, `:32`). The profile identity rule is 006's FR-034: no profile value leaves
`checks/standards/profile.py` except where a comparison is the point; the brief states conformance
instead of the settings. `brief_version` lets feature 012 add what the owner's base repository turns
out to need without breaking 011's consumers (R5).

### R2.17 Standards profile version 3: the drawing section

**Decision**: `PROFILE_VERSION` becomes 3, the loader reads 1, 2 and 3, and version 3 requires a
`drawing` section - `sheet_formats` (list of accepted sheet format names), `drafting_standard`,
`projection` (`first_angle`, `third_angle` or empty), `dimension_unit` (`mm`, `in` or empty),
`drawing_template`, `bom_template` - every key required and every value possibly empty, as the
profile's own rule says. The general tolerance stays in version 2's `general_tolerance`, not
restated; `dimension_unit` is the unit its decimal places are counted in. The example profile, the
two fixture profiles, 006's contract block and 006's R5 rows change together, as 010 did for
version 2.

**Why**: FR-044 and FR-045; feature 010 R2.19 ("Feature 011 also plans a `drawing` profile section
with a general tolerance; it should reference this section rather than restate it") and R5 (011
takes the next version). VERIFIED the profile's rules - strict, closed, every key required, empty
means skip (`checks/standards/profile.py:10-16`, `KNOWN_VERSIONS`, `VERSION_2_SECTIONS`) - and the
five-file lockstep `test_standards_no_company_values.py` enforces.

### R2.18 Conformance: one finding per drawing, outside the release verdict

**Decision**: `drawing_profile.conformance`, one finding per attached or root drawing that differs
from a non-empty compared setting: each sheet's format name against `sheet_formats`, the drawing's
`drafting_standard_name`, each sheet's `first_angle` against `projection`, the drawing's
`length_unit_raw` against `dimension_unit`; status demonstrated, severity medium, class
`manufacturing`; the finding names every difference with the drawing's own value and the setting's
name, never the profile's value (006 FR-034). An unread value is unresolved coverage; an empty
setting is skipped coverage. The templates are recorded for feature 012 and not compared - a
finished drawing does not record the template it was made from.

**Why**: FR-046 and FR-047. The id's prefix is `drawing_profile.`, not `drawing.`: VERIFIED the
checklist item `drawing.manufacturing_inputs` closes on any finding whose check starts with
`drawing.` (`agent/checklist_v1.yaml:13-19`), and a sheet-format finding must not close the item
that asks for material, general tolerance, surface finish and thread callouts. It is a review
finding, not a Standards check, so the sixteen-check release verdict and its pins do not move; an
owner question asks whether it should become one (R5).

### R2.19 Evidence schema 1.6.0, additive

**Decision**: every field of R2.6, R2.7, R2.12 and the `DrawingCandidate` array is optional,
omitted when null or empty through `omit_additive`, in both languages; `SCHEMA_VERSION = "1.6.0"`;
`ir.schema.json` regenerated. A 1.5.0 package loads and serializes to its own bytes; a 1.6.0 package
with none of the new members is byte-identical to a 1.5.0 build's output except `schema_version`.

**Why**: FR-048 and Principle IV. VERIFIED the additivity helper and the precedents
(`ir/models.py:92-117`, the 1.4.0 drawing models `:908-1219`, the 1.5.0 members `:1266-1425`).

### R2.20 The token budget: the drawing arm is pinned separately

**Decision**: the drawing family is outside `REGISTRATIONS`, so `TOOL_FUNCTIONS` and every pin of
`test_tool_payload.py` stay; the file gains a **drawing arm** - the slim and pre-run arrays with the
family offered - pinned by `--write` in a commit of its own and asserted under `ARRAY_CEILING`
(38,000, unchanged); the bridged slim array with the family is pinned in the same rows and not
asserted, because it is over the ceiling already without the family (below). Budget: `check_drawings` at most 450 bytes and `get_drawing_brief` at most 650
bytes per encoding; the slim Gemini array with both is then at most about 37,320 bytes.

**Why**: FR-050. VERIFIED on 2026-09-23 with the payload module's own measure: the review array is
35,844 bytes (OpenAI) and 35,915 (Gemini), the slim array 36,200 and 36,220, the ceiling 38,000
(`test_tool_payload.py:381-441`); the argument-free `check_hygiene`, `check_mass_material` and
`check_joints` objects are 414, 376 and 429 bytes and the one-argument `get_drawing_sheet` 627 bytes
with lever 2 off. The headroom is 1,780 bytes on the tightest array the ceiling is asserted on (the
slim Gemini array); two tools of the sizes above fit with about 680 to spare, and a longer docstring
would not.

**Corrected 2026-09-23 on review: the bridged arrays are already over the ceiling.** Measured the
same day with the same `measure`: `review+bridge` is 39,542 bytes (OpenAI) and 39,431 (Gemini), and
the slimmed review with a bridge - what a bridged pane review offers before its pre-run completes,
or with checks first off - 39,898 and 39,736. `test_tool_payload.py` asserts the ceiling on the
review, slim and two pre-run arrays only (`test_the_bridge_array_is_pinned_in_both_arms` pins
39,542 and asserts no ceiling), so "the tightest array" was the tightest *asserted* array, and a
bridged review of a package with drawing evidence whose pre-run has not completed would offer about
1,100 bytes more again. This feature neither causes that nor can fix it within its budget, and
`ARRAY_CEILING` stays 38,000: FR-050 is scoped to the arrays the ceiling is asserted on, the bridged
slim arm is pinned without the assertion so its growth shows, and whether the ceiling is meant to
hold the bridged arrays is the owner's question (R5 Q9).

**Corrected again 2026-09-23 on review: two unbridged arrays cross the ceiling because of the
family.** A review run with a standards profile offers `check_standards` (`ToolRegistry._offered`
appends it, then the drawing family), and `DRAWING_ARMS` does not model it. Measured with the
payload module's own `measure` and `ENCODINGS`: the review array with `check_standards` is 37,332
bytes (OpenAI) and 37,352 (Gemini) before the family and **38,058** and 37,976 with it; the slimmed
review with `check_standards` is 37,688 and 37,657 before and **38,414** and **38,281** with it
(the `check_standards` object alone 1,487 and 1,436 bytes). These are the arrays `swreview review
RUN --standards-profile P` sends on a package with drawing evidence when checks first is off - the
command line's default; the pane's checks first and lever 13 take both `check_standards` and
`check_drawings` off once the pre-run completes, which is the pre-run arm, under the ceiling. So the
sentence above, "this feature neither causes that", holds for the bridged arrays only: for these two
the family is what crosses 38,000. Neither is pinned or asserted today. Whether the ceiling holds a
standards run's arrays, as Q9 asked for the bridged ones, is the owner's question (R5 Q10);
`ARRAY_CEILING` stays 38,000 and no array was trimmed to fit (tool docstrings do not move).

**Answered 2026-09-23 (owner decision 9A, R5 Q10; T084, T085).** The ceiling is asserted only on
the arrays the pane sends by default: payload slimming, checks first and lever 13 (`pane_defaults`),
the pre-run having completed, with and without a bridge and drawing evidence - 29,217, 34,145,
29,651 and 34,579 bytes on OpenAI, 29,552, 34,247, 29,935 and 34,630 on Gemini. A standards profile
leaves the same four arrays, since lever 13 withholds `check_standards` once it ran. Every other
array a review can send is pinned per provider, so its growth shows in review, and not asserted:
checks first off, a standards run with checks first off (38,058 and 37,976 bytes with the family),
the bridged arrays (40,268 and 40,624 on OpenAI with it) and the pre-run without payload slimming.
`test_tool_payload.py` now enumerates the space rather than listing arrays by hand: five switches
(slimming, a bridge, a standards run, drawing evidence, a completed pre-run) make thirty-two shapes
and twenty-four arrays (`REVIEW_ARRAYS`), each shape's offered half is checked against
`ToolRegistry.functions_for`, and `ARRAY_KINDS` says which kind each array is, so an array a new
switch or group makes fails a test until it is classified. What stays out of the space, each for its
reason, is in `ArrayShape`'s docstring: lever 2 (descriptions, not membership), lever 4's tier (its
own delta), lever 12's experimental compact queries, the remodel tools, and a pre-run that completed
only some tools (bounded by the shape's two arms). This scopes FR-050 (amended) and
`contracts/questions.md` section 7; `ARRAY_CEILING` stays 38,000 and no docstring moves.

### R2.21 Fixtures: synthetic, built by code, fictional

**Decision**: `reviewer/tests/support/drawings.py` builds drawing records on top of feature 010's
`tests/support/mechanical.py` builders, and `reviewer/tests/fixtures/drawings/generate_fixtures.py`
writes three packages at IR 1.6.0: `plate-drawing` (feature 010's `tolerances` assembly with a
drawing of the plate and a second drawing of it in another configuration, a candidate beside the
block, and every callout kind), `drawing-root` (a drawing root shaped like feature 006's drawing
fixtures), and `assembly-drawings` (an assembly drawing with a bill of materials, and a part shown
by two drawings). Every path under `C:\Fictional\`, every string from the fictional vocabulary, the
denylist scan over the tree; the generator reproduces every byte. The pathological package for the
brief bound is built in its test, not committed.

**Why**: no recorded package has a drawing (R3); the fixtures must still exercise every binding and
every refusal. Reusing the `tolerances` assembly means the joints, faces, persistent references and
model dimensions the resolver needs already exist with known answers.

### R2.22 What this feature does not do

- **Create, modify or save a drawing.** Feature 012, after seat probes, a constitution amendment
  and an evaluation of the owner's base repository (roadmap, "Start from the existing
  drawing-creation base").
- **Convert an ISO 2768 class**, or parse a general tolerance note (R2.9, spec Assumptions).
- **Grade attached drawings in the Standards tab** (R2.3).
- **Review a drawing root in the Review tab** (spec Assumptions); the refusal sentence gains "its
  open drawing is read with it" (T016).
- **Evaluate `rms.drawing.model_items_preferred`**, which stays out of scope "advisory by decision"
  (`checks/rms/registry.py:315`) although 011 now records whether a drawing dimension is a model
  item; turning it on is the owner's decision (R5).
- **Add a finding for an interface with no drawing callout.** The brief lists each interface's
  binding; a finding waits until the binding is validated on a seat and the owner asks for it.

### R2.23 A confirmed candidate is opened read-only, read, and closed (owner, 2026-09-23, R5 Q2)

**Decision**: the candidate question's first option becomes "Yes, open it read-only and read it".
When the engineer sends it, the **backend** - which wrote the question and owns its strings, so the
page compares nothing - asks the add-in over the bridge, once per confirmed candidate, with a new
review-scope command `drawing.read {document_id}` (protocol 1.3). The **host** resolves everything
from its own records: the chat's run folder (as `report.open` does), that package's
`documents[]` row and `drawing_candidates[]` row for the id, and the candidate path recomputed as
discovery computes it; no path ever travels in a request. It then opens the drawing through a
**guarded seam** of its own - `DrawingOpenGuard`, an allowlist of exactly three interface-qualified
keys (`ISldWorks.DocumentVisible`, `ISldWorks.OpenDoc6`, `ISldWorks.CloseDoc`), recorded as one
entry in `004-resilient-remodeler/contracts/guard-allowlist.md` - with `OpenDoc6(path, drawing,
ReadOnly | Silent = 3)` between `DocumentVisible(false, drawing)` and its restore in a `finally`,
so the drawing is not shown and takes no focus. It reads the drawing with the existing drawing
phase, ids continuing the package's sequences, appends it to the run's `package.json` through
`PackageAppender` (the extractor still writes every package byte), and closes it in a `finally`
**only when the seam opened it**, after checking that the path answers the same COM identity. A
drawing the engineer opened in the meantime is read as it stands and never closed. The backend
reloads the package before the resumed turn, so the turn sees the drawing.

**Why**: the owner's answer to Q2, and every rule the answer states. The bridge is the only channel
from the reasoning side to SOLIDWORKS, and it is already authenticated and scoped (feature 002);
`tessellate` is the precedent of a review-scope command that names a package id and has the host
choose every path. A dedicated allowlist guard, as feature 004's `RemodelGuard` is, makes "the one
read-only open" a closed set a test can pin rather than a bare name riding on the read-only
denylist's exclusion of `OpenDoc6`. The add-in's bridge runs on the SOLIDWORKS thread, so the
engineer cannot touch the drawing between the open and the close; "close only what we opened" is
decidable from one read before the open. `DocumentVisible` is the documented way to open a
document without showing it; it is session state, not a saved preference, and is restored in a
`finally`.

**Alternatives**: re-running the whole review extraction with the drawing open (rejected: minutes
on a large assembly, and a second package mid-review renumbers every attached drawing); returning
the record over the bridge for the backend to merge (rejected: the backend would write
`package.json`, which only the extractor writes, and would re-implement the path matching); a page
message after the answer (rejected: the page would have to recognise the answer's words, and the
page compares nothing); riding on the bare `OpenDoc6` exclusion (rejected: the owner asked for an
allowlist entry of its own, and a bare name cannot tell the model open from the drawing open in the
gate log).

**What the seat must confirm** (probe D14, T077): the open-mode flags as composed; that the drawing
never becomes the active document and the engineer's window keeps focus; that views of the hidden
drawing read; that the file's size, write time and hash are unchanged and no save flag rises; that
the file is not locked for the engineer after the close; and whether the models the drawing loaded
stay loaded after it closes. Until then the seam ships **off**, as the drawing binding does (R2.8):
`DrawingOpenScope.SeatValidated = false`, and while it is false `drawing.read` opens nothing and
answers "the read-only open of a confirmed drawing is not yet validated on a seat (feature 011
probe D14)", which the review records; the probe itself runs the seam from the console with the
switch overridden for that one command. T077 sets it true in a commit of its own citing the probe
record, or leaves it false and records why.

## R3. Verified facts the plan relies on

- **No drawing has been extracted live.** `SwSession.Attach` refuses a drawing (`SwSession.cs:78`,
  `:113`) on every path that extracts, including the Standards tab's (`SwReviewDump.cs:67`) and
  `probe standards` (`Program.cs:1792`); before `96785d1` the same path failed on the missing
  configuration. Feature 006's T103, T105 and T107 are therefore unreachable, not only unrun.
- **The drawing phase reads one drawing, the root.** `PackageWriter.cs:282-296`; ids are allocated
  per traversal "because one package carries at most one drawing record" (`DrawingTraversal.cs:30`);
  the reader is bound to the session's document (`SwDrawingReader.cs:47`, `:193`).
- **The standing drawing gap names the profile.** `PackageWriter.cs:390-399`: "Drawing sheets were
  not read natively: the drawing phase did not run under the '{profile}' profile" - true today for a
  `full` part or assembly dump and false after this feature, whose review extraction may run the
  phase; FR-014 rewrites it for that case.
- **Feature 010 waits in three places.** The source slot (`checks/tolerances.py:350-356`), the
  subject's `decimal_places` (`:100`), and `holds_any_source`'s general-block sentence (`:594-617`).
- **The model-facing drawing tools read PDF sheets only** (`tools/refs.py:47-67`,
  `tools/query.py:628-722`); the opening brief counts only PDF sheets
  (`agent/package_brief.py:256`, `:291-292`).
- **The checklist's drawing item closes on the prefix `drawing.`** (`agent/checklist_v1.yaml:13-19`),
  and the model's drawing finding is `drawing.manufacturing_inputs` (`tools/session.py:52`).
- **The tool array's headroom is 1,780 bytes** on the slim Gemini array, the tightest the ceiling
  is asserted on; the bridged arrays are over it already, unasserted (R2.20).
- **The interop members this feature reads exist on 32.5.0.48** (reflection, 2026-09-23):
  `ISldWorks.GetDocuments`, `GetDocumentCount`; `IDrawingDoc.GetViews`, `GetSheetNames`,
  `GetCurrentSheet`, `IsDetailingMode`; `ISheet.GetTemplateName`, `GetProperties2`,
  `GetSheetFormatName`; `IView.ReferencedConfiguration`, `IsModelOutOfDate`, `IsModelLoaded`,
  `ScaleDecimal`, `GetOrientationName`, `GetDisplayDimensions`,
  `GetAnnotations`, `GetTableAnnotations`; `IDisplayDimension.GetText(Int32)`,
  `GetPrimaryPrecision2`, `GetPrimaryTolPrecision2`, `GetUseDocPrecision`, `GetUnits`,
  `GetUseDocUnits`, `IsReferenceDim`, `IsHoleCallout`, `GetHoleCalloutVariables`;
  `IDimension.Tolerance`, `DrivenState`, `FullName`; `IAnnotation.GetAttachedEntities3`;
  `IEdge.GetTwoAdjacentFaces2`; `ISFSymbol.GetSymbol`, `GetTextCount`, `GetTextAtIndex`;
  `ITableAnnotation.Type`, `Title`, `RowCount`, `ColumnCount`, `Text`;
  `IBomTableAnnotation.GetModelPathNames`; `IModelDocExtension.GetUserPreferenceInteger` and
  `GetUserPreferenceString`, `GetCorrespondingEntity2`; and the enum values quoted in
  R2.7, R2.9 and R2.12. The `GetCorrespondingEntity2` ownership/direction correction was compiled
  and tested against the same 32.5.0.48 interop on 2026-10-14 (see the correction below).
- **The writers**: 621 grammar matches on the 24 families, 39 denied today, 2 re-modeler
  exclusions, 580 new; no collision with a gated read (R2.2). *Landed and regenerated on review
  (2026-09-23)*: 646 matches on the 28 families, 41 already denied, 2 excluded, 603 new, and the
  shared rows' 30, for 633 new names; the generated table is the count.

**The tests that go red by design**, each named in the task that lands it and edited deliberately,
never loosened: `SwSessionAttachTests` (the refusal gains a purpose, T013); the drawing-phase and
traversal tests that construct `DrawingTraversal` with its own allocators and read `Drawing()` with
no argument (T009, T010); `PackageWriterTests` asserting the drawing gap's profile sentence for a
`full` part or assembly dump (T020); the IR serializer, contract and `test_schema_sync.py` pins of
1.5.0 (T005 to T008); `test_tolerances.py`'s "not available before feature 011" rows (T034);
`test_standards_profile.py` and `test_standards_no_company_values.py` field tests, 006's R5 rows and
the standards goldens that record a fixture profile's `sha256` (T028, T029); `RemodelGuardTests`
lists and the guard-allowlist table counts (T003, T004); the add-in's test of the Review tab's
drawing refusal sentence (T015); `test_attention_catalogue.py` for the one new id (T056).

**What does not move**: every tool's signature and docstring; `TOOL_FUNCTIONS`, every existing pin of
`test_tool_payload.py` and the byte counts in feature 005's `levers.md`; the MCP function list and
the terminal profile; `Finding`, `CoverageItem`, `EvidenceRequest`, `InvestigationStep`, the event
schema; feature 006's sixteen checks and their verdict; every golden of `render_report`; feature
010's joint map, checks and goldens (its `tolerances` fixture is read, not regenerated); a replay of
every recorded review.

## R4. Seat probes

Each is a section of `swreview-extract probe drawings` (`contracts/probes.md`), read-only, printing
ids, counts, member answers and millimetres - never a name, path or property value, except the
dimension names, view names and values of D6's and D8's dimension lines (amended 2026-09-24), which
stay in the report: only its ids, counts and answers are recorded here. The four
feature 006 probes the attach made unreachable run at the same sitting, unchanged (006 T103, T105,
T107).

| Probe | Question | Settles |
|---|---|---|
| D1 | `AttachForDump` on an open multi-sheet drawing: does the Standards extraction complete, with every sheet read or named? | US1, SC-001 |
| D2 | `GetDocuments` with three drawings open (one hidden behind another window): are all three returned, and is any model returned twice? | R2.3 |
| D3 | `IDrawingDoc.GetViews` on a six-sheet drawing: are a non-active sheet's views returned without activation, and is the sheet-format view among them? (006 PROBE-7, from the document instead of the sheet) | R2.3, R2.5 |
| D4 | On dimensions with their own precision and with the document's: what `GetPrimaryPrecision2` and `GetPrimaryTolPrecision2` return; whether `swDetailingLinearDimPrecision` or `swUnitsLinearDecimalPlaces` is the displayed default | R2.9 |
| D5 | `IDimension.Tolerance` on a model-item dimension and on a drawing reference dimension: the type and limits, compared with the part's own reading | R2.7 |
| D6 | `GetAttachedEntities3` on a diameter dimension, a hole callout and a GTol, then the owning part's `IModelDocExtension.GetCorrespondingEntity2` and `GetPersistReference3`: equal to the face phase's reference for that face, for a part drawing and for an assembly drawing | R2.8, SC-010 |
| D7 | `IsHoleCallout`, `GetHoleCalloutVariables` and `GetText` 1 to 4 on a counterbore callout; whether any member returns the rendered text whole | R2.7 |
| D8 | `IDimension.FullName` of a model item in the drawing against the same dimension's `FullName` read in the part | R2.8 |
| D9 | GTol frames, datum labels and surface-finish texts through the 010 reader members on drawing annotations | R2.12 |
| D10 | Tables of each kind: type, title, cells; `GetModelPathNames` on bill-of-materials rows | R2.12 |
| D11 | `GetProperties2` (projection, scale), `GetTemplateName`, and the document's unit, precision and standard name on a drawing | R2.7, R2.18 |
| D12 | `ReferencedConfiguration`, `IsModelOutOfDate`, `IsModelLoaded` on an up-to-date view, a view left out of date after a model edit, and a drawing in detailing mode | R2.6 |
| D13 | `File.Exists` on a vault-view path whose file is not cached locally: the answer, the time taken, and whether the file was fetched | R2.4 |
| D14 | The confirmed candidate's read-only open (R2.23): the open-mode integer, the active document and focus before, during and after, the hidden drawing's views, the file's size, write time and hash and every save flag before and after, the file's lock after the close, and the open-document set before and after | R2.23, SC-011 |

## R5. Owner decisions recorded here, and the questions still open

**Recorded** (owner, 2026-09-22 unless dated): drawings are read-only context before the next test;
the attach is fixed; the drawings already open are attached to part and assembly reviews; native
dimensions, tolerances, notes and tables are extracted; a per-part drawing brief; questions in the
pane; creation is feature 012, specified only after seat probes and a constitution amendment and
starting from the owner's base repository; tolerances come from four sources, drawing callouts one
of them; the general tolerance goes by decimal places (2026-09-23, 010 R5); feature 010 takes IR
1.5.0 and profile version 2 and 011 the next versions (2026-09-23, 010 R5).

**Answered by the owner on 2026-09-23** (Q2 to Q9). Q2 is the only answer that differs from the
default this package shipped; it is designed in R2.23 and specified in `contracts/confirmed-open.md`,
and its tasks are Phase 7B (T069 to T077). Every other answer confirms the shipped default, so no
requirement or task moves for it.

| # | Question | Answer (owner, 2026-09-23) | Moves |
|---|---|---|---|
| Q2 | Should a candidate drawing be opened read-only when the engineer answers "yes"? | **Yes, the product opens it.** When the engineer confirms that a same-name drawing which is not open is this part's drawing, the product opens it read-only itself - overriding the shipped default ("the engineer opens it and reviews again"). It never changes or saves the drawing, never activates it or takes focus from the engineer's window if the API allows that, and closes it again when the product opened it; it never closes a drawing the engineer had open. The one read-only open goes through the guarded seam with its own allowlist entry; a seat probe verifies the open-mode flags, that the file is not locked for the engineer, and that nothing is written | FR-015, FR-036, US5, `contracts/confirmed-open.md`, T069 to T077 |
| Q3 | Should the Standards tab, or a review's standards run, grade the drawings attached to a part or assembly? | **No.** A drawing is graded only when it is itself open | nothing (FR-011 as shipped) |
| Q4 | The drawing section's values | **The profile version 3 drawing values stay fictional placeholders** in the repository; the owner writes the real ones with the version 3 profile | nothing (T029 as shipped) |
| Q5 | Is a drawing that differs from the drawing section a review finding only, or also a Standards check in the release verdict? | **A review finding only** (manufacturing class), never a release-verdict failure | nothing (FR-047 as shipped) |
| Q6 | A geometric tolerance value written on a drawing with no unit: read in the drawing's unit? | **Yes** (the default accepted): read in the drawing's unit and cited so | nothing (FR-029 as shipped) |
| Q7 | Does the company use SOLIDWORKS' general tolerance table (an ISO 2768 class), or only the decimal-place convention? | **Decimal places only.** A dimension governed by the ISO 2768 table is recorded word for word and binds nothing. The real band values are still to come; `config/standards.example.yaml` keeps its clearly labelled example bands | nothing (FR-021, R2.9 as shipped) |
| Q8 | Should `rms.drawing.model_items_preferred` be evaluated now that the extraction records model items? | **No** (the default accepted): it stays out of scope | nothing |
| Q9 | Does `ARRAY_CEILING` hold the bridged review arrays? | **No** (the default accepted): the bridged arrays are pinned and not asserted. *Follow-up 2026-09-23 (decision 9A, Q10)*: every bridged array is now pinned for both providers - the bridged review array's Gemini figure (39,431) and the bridged slim array without the family (39,898 / 39,736), which had no pin, included - and none is asserted | nothing (FR-050, T054 as shipped); T084, T085 |

**Answered by the owner on 2026-09-23, after the review** (Q10, decision 9A):

| # | Question | Answer (owner, 2026-09-23) | Moves |
|---|---|---|---|
| Q10 | Does `ARRAY_CEILING` hold a standards run's review arrays (`--standards-profile` with checks first off), which the drawing family takes to 38,058 / 37,976 bytes (review) and 38,414 / 38,281 (slim), OpenAI / Gemini (R2.20)? *Raised 2026-09-23 on review* | **No, and the ceiling holds only the pane's defaults** (decision 9A): `ARRAY_CEILING` (38,000) is asserted only on the arrays the pane sends by default. Every other array is pinned, so growth is visible in review, but not asserted: checks first off, a standards run with checks first off (38,058 and 37,976 bytes with the drawing family), and the bridged arrays (40,268 and 40,624). The standards arrays are pinned beside the bridged ones, as the default foresaw, and so is every other array a review can send, each named with its kind | FR-050 (amended), `contracts/questions.md` section 7, R2.20, T084, T085; feature 005's `contracts/levers.md` and feature 008's research R2.57 record the decision and the ceiling's history |

**Still open:**

| # | Question | Default | Blocks |
|---|---|---|---|
| Q1 | Where is the drawing-creation base repository? | The brief ships the roadmap's five sections at `brief_version: 1`; when the location is given, its expected inputs are evaluated (T061) and the brief is extended additively, in 012 if not before | the brief's final content, feature 012 |

## R6. Relation to the features around it

- **006**: 011 makes its drawing reading reachable (US1) and amends FR-025 for the review
  extraction (T001); its four checks, its traversal and its verdict are unchanged.
- **008**: 011's check joins the pre-run under 008's pane default and re-call guard; its questions
  use 008's answer batch; the replay of recorded reviews is unchanged by construction (R2.14).
- **009**: the "Questions for you" panel shows 011's questions with no page change.
- **010**: 011 fills the resolver's drawing slot, supplies `decimal_places` to the general source,
  generalises `_frame_zone` to frames, and reuses the joint map and the alignment callout; 010's
  `contracts/tolerances.md` section 6 gains the decision record (T002).
- **012**: 011's guard hardening is the default-deny 012's creator will allowlist against; 011's
  brief is the input 012's drawing plan will extend; 011 creates nothing.

## R7. Defaults taken 2026-09-28: the Review tab and an active drawing (U25)

**Sources.** The sitting of 2026-09-28 (the handoff packet's U25: after an assembly review the
engineer activated its drawing, and the pane said "Press Review to review {drawing}", which the host
then refused), the follow-up on `codex/testing-feedback-2026-09-28` (`f421225`), and the drawing
lens's review of it the same day. **Each item is a default taken 2026-09-28, the owner may revise;
none is the owner's own words.** SOLIDWORKS was not started; the guard's denied set and the local API
help were read.

### R7.1 The host decides "drawing", composes the sentence once, and names the model

**Decision**: the Review page's `init` and `document.changed` carry `kind` (the check tabs' payload,
`CheckPaneHost.DocumentPayload`) and, for a drawing, `drawing_guidance`, the sentence
`ReviewHost.DrawingSentence` composes. The page decides "drawing" from `kind` only and prints the
sentence as sent - in its banner, and on an error card's status line when Retry is pressed with a
drawing active - and sends nothing for either press. The host's `DrawingActive` refusal from
`review.prepare` and `review.start` carries the same sentence. The sentence names the model the
drawing's views show when they say which: the first, in sheet-then-view order, by file name, the
others counted; "open or switch to" it. The models come from the walk open-drawing discovery makes
(`SwOpenDrawingReader.ViewPaths`, made public and static, and `OpenDrawingDiscovery.ModelsShown`,
matching by discovery's path key), read only for a drawing, through a gate with the read-only guard,
on the application thread, and never from `CurrentDocument`; any failure names no model.

**Why**: the follow-up fixed the misleading invitation with a page-written sentence and a `.slddrw`
regex - a second extension table beside `PageDocument.Kind`, contradicting 002's contract, which said
the Review page gets no `kind` because it decides nothing with it - and re-typed the backend's
`DrawingActive` label with nothing tying the two. The engineer's report asked to review from the
drawing; the product cannot switch documents (`ActivateDoc`, `ActivateDoc2`, `ActivateDoc3` are
denied), but the review's own report already says "Open {drawing}, then press Review again with
{model} active". Naming the model closes that gap with reads the guard already allows.

**Alternatives weighed**: keep the regex and amend the contract (not taken: two tables); build the
banner from the backend's label on the page (not taken: the label cannot name the model, and the
page would still word the drawing itself); name the model only from the review's candidate pairs
(not taken: no help for a drawing opened first, or with no review).

### R7.2 Recorded for the seat

The view walk now runs inside the active-document event for a drawing. The next sitting checks it on
a drawing opened on its own, one opened after its model, and a multi-sheet drawing, with no refused
member in the add-in log (`docs/history/testing-feedback-2026-09-28.md`, retest step 1).

### 2026-10-14 attachment direction correction

The original attachment path used `IView.GetCorrespondingEntity` in the inverse direction.
SOLIDWORKS documents that member as model-to-drawing and identifies the owning model extension's
`GetCorrespondingEntity2` as the drawing/assembly-to-part mapping. The adapter now resolves the
part document from the original attachment and keeps that scope through mapping and adjacent
face reads. `IEntity.GetComponent` cannot recover a component from an underlying part-context
entity, so ownership is read before that context is lost. Unloaded or non-part owners and null
mappings produce the existing attachment gap. These software corrections do not establish the
cause of a native crash; D6 and D8 workstation validation and the binding gate remain pending.

Sources: [IView.GetCorrespondingEntity](https://help.solidworks.com/2022/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IView~GetCorrespondingEntity.html),
[IModelDocExtension.GetCorrespondingEntity2](https://help.solidworks.com/2019/English/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IModelDocExtension~GetCorrespondingEntity2.html),
and [IEntity.GetComponent](https://help.solidworks.com/2019/English/api/sldworksapi/SOLIDWORKS.Interop.sldworks~SOLIDWORKS.Interop.sldworks.IEntity~GetComponent.html).

## R8. Decision 136A: the read-only guard's three gaps closed (owner, 2026-10-19)

**Source.** Checking the draft constitution amendment of decision 134A against the code found three
gaps in the read-only guard. The owner's decision 136A of 2026-10-19 (the sixth round's 1A, "Fix
all three") closes them, test first, under this feature; decision 137A (the same round's 2A) has
two stale comments corrected with them (R8.4). The tasks are T111 to T119 (Phase 10C). SOLIDWORKS
was not started: the C# tests run over fakes and the interop stand-in, and the interop
(`SolidWorks.Interop.sldworks` 32.5.0.48) was read as metadata only. Measured on the development
machine: `SwReview.Extractor.Tests` 9,138 tests before and 9,353 after, `SwReview.AddIn.Tests`
2,456 before and after, all green, the build at zero warnings.

*Amended on the branch's review, the same day*: an independent adversarial review of the branch
found no seat breakage and no new write path and confirmed the tests load-bearing. What it found is
fixed by T120 to T128, each recorded in the subsection it amends, and the host's `PROTOCOL.md` now
lists `drawing.read`'s refusals as this decision left them (T128, commit `ab623aa`). Measured after:
`SwReview.Extractor.Tests` 9,374 tests and `SwReview.AddIn.Tests` 2,456, all green, the build at
zero warnings. The questions it raised that are the owner's are R8.5's.

*On a second review, the same day*: it verified T120 to T128 and found what T129 to T134 fix,
recorded in R8.1: D14's reading passed a drawing the seam opened and never asked, and nothing at the
seat could show whether SOLIDWORKS sets an already-open bit; R8.1's reason for honouring both bits
is corrected, and the host's `PROTOCOL.md` now says what a failed visibility restore does (T134,
commit `ef42c34`). Measured after: `SwReview.Extractor.Tests` 9,387 tests and `SwReview.AddIn.Tests`
2,456, all green, the build at zero warnings.

### R8.1 Each read-only open is checked read-only (T111, T112, T113, T114)

**Decision**: after a successful `OpenDoc6`, the confirmed drawing's open (`DrawingOpenScope`) and
the console attach's open of a part or assembly (`SwSession.OpenReadOnly`) ask the document
`IModelDoc2.IsOpenedReadOnly()` through their gate, under the bare name. A false answer, or a call
that throws (it fails closed), refuses the read with a sentence that names why and the open's load
errors and warnings, and closes the document that open opened - only after
`GetOpenDocumentByName(path)` answers the very COM object the open returned - unread; a close
refused or failed is named in the refusal, never hidden. A document open before the call is neither
asked nor closed. The rule is written once, `Sw/ReadOnlyOpen.cs`, and the seam's existing close now
goes through it too, its sentences unchanged. Probe D14 prints what the opened drawing answered
(`IsOpenedReadOnly: true`, `false`, `failed (<type> 0x<HRESULT>)` or `not called`), and its own
reading names `the read-only state` when a drawing the open returned did not answer true.

**Why**: both opens ask for ReadOnly | Silent, and nothing but the document says whether SOLIDWORKS
honoured that. The console attach leaves its document open on purpose, so that a later `resolve` or
`capture` finds its persistent references, so a document it had opened for writing would stay open
for writing in the engineer's session. The check is a read: `DrawingOpenGuard` hands the bare name to
`ReadOnlyGuard`, which allows it, so the confirmed open's allowlist stays three keys; the qualified
`IModelDoc2.IsOpenedReadOnly` would be refused by that guard, which is why the seam names it bare.

**Evidence**: commit `68f4427` (the check, with 19 new tests: nine of `DrawingOpenScopeTests`, one
of `DrawingOpenGuardTests`, one of `ConfirmedDrawingReadTests`, eight of the new
`SwSessionReadOnlyOpenTests` over the interop stand-in). Red before the change: on the seam's side
twelve, nine new and three edited, and seven of the console's eight; the three that passed are pins
of what must not change (a drawing or part already open, and the guards' answer to the bare read).
Commit `dd16745` (D14's line, three new tests and two edited, all five red before). Edited deliberately, for the
new step in the call order and the gate log: `DrawingOpenScopeTests`' order and gate-log tests,
D14's seam order and its two full reports, and the add-in's `gated=` line test. The contracts
(`confirmed-open.md` section 3, `attach.md` section 4, `guard.md` sections 6 and 7, `probes.md`) and
the seat plan's step 3.9 say so.

*Amended on the branch's review, the same day (T121, T122, T125, T126)*: **a document the open
itself says was already open is not the call's.** `OpenDoc6` can answer with a document SOLIDWORKS
already had open - the engineer opened it between the lookup and the open, an open assembly holds
it, or it is open under another spelling of its path - and says so in its warnings,
`swFileLoadWarning_AlreadyOpen` (128). Such a document is the engineer's, perhaps open for writing
with unsaved changes: it answered "not read-only", SOLIDWORKS answered its path with it, so the
identity check passed and the refusal closed it; the review reproduced that with a throwaway test of
the console attach. Both opens now treat it exactly as one the lookup found: used as it stands,
never asked `IsOpenedReadOnly`, never closed; the seam reads it with `OpenedByReview` false and, if
the restore failed too, refuses it unread and leaves it open. `FileLoadErrors.SayAlreadyOpen` also
honours the errors enum's older twin, `swFileAlreadyOpenWarn` (512), and the identity-checked close
stays for what the call really opened. That also settles the case the first version of R8.5 left
open, a document open under another spelling of its path (a mapped drive against its UNC path): the
console attach attaches to it as it stands, as it did before this decision, instead of refusing it.

*Corrected on the second review, the same day (T133)*: this record said that honouring either bit
"can only keep a close from happening". That is not the whole of it. Honouring a bit can never close
the engineer's document, but it also skips the read-only check: should SOLIDWORKS ever set either
bit on a fresh open, the console attach would use the document that open opened unchecked, and the
seam would read the hidden drawing that open opened unchecked and leave it open - though it would
close nothing against the engineer's will. Probe D14 is how the seat confirms what SOLIDWORKS sets:
its `OpenDoc6` line now ends with the codes the open answered (T131, T132). Commit `6396a2a`.

**The seat should confirm** two things about these bits. That SOLIDWORKS sets neither on a fresh
open: the first D14 run of the seat plan's step 3.9 now shows the open's codes on its `OpenDoc6`
line. And that it sets `swFileLoadWarning_AlreadyOpen` for a document already open under another
spelling of its path: a D14 run with the drawing opened by one spelling (its UNC path, say) and
`--doc` naming the part by another (a mapped drive) would show it; that is not yet a step of the
plan. If SOLIDWORKS does not set the bit then, the identity check still guards the close as long as
SOLIDWORKS answers that spelling after the open as it did before it, with no document, so nothing is
closed; and the console attach refuses the document, naming the open's warnings.

D14's reading names `the read-only state` only on an answer. When the restore of new drawings'
visibility failed, the seam refused before it asked, yet the reading named the read-only state
because a drawing had been returned; it now judges only the answers the check gave, any that is not
true failing it, and a check never asked is not judged. *On the second review*: a drawing the seam
opened and read must still have answered. With the seam's check removed, D14 printed
`IsOpenedReadOnly: not called` beside `opened by the probe and closed` and still read `every answer
as required`, and no test's reading caught it. The rule is now
`DrawingOpenProbe.ReadOnlyAsRequired`: every answer true, and at least one for a drawing the seam
opened (T129, T130).

Evidence: commit `4375b8a`, tests first - nine new test methods, nineteen cases, across
`FileLoadErrorsTests`, `DrawingOpenScopeTests`, `ConfirmedDrawingReadTests`,
`SwSessionReadOnlyOpenTests` and D14's; eight red before the change and D14's red against the old
seam - with the two tests whose premise was warning 128 edited deliberately to warning 32, their
assertions kept; and commit `b06ee7f`, one new D14 test, red before. `confirmed-open.md` section 3,
`attach.md` section 4, `guard.md` section 7, `probes.md` and 004's `guard-allowlist.md` say so. On
the second review: commit `044c35a` (T129, T130), a theory of the rule whose row for an opened
drawing with no answer was red before, and under a throwaway mutation removing the seam's check
`D14_EveryWayTheOpenCanMisbehaveIsNamedAndTheModelsItLoadedAreRecorded`, green before the change and
red after it, its reading naming the read-only state; and commit `ddb2424` (T131, T132), six D14
tests red before - among them the full report, edited deliberately for the `OpenDoc6` line's new
end - and the seat plan's pin of that end, red until the plan said it.

### R8.2 Every spelling of the open, activate, new, load, close and quit families (T115, T116)

**Decision**: section 1 of `contracts/guard.md` named the shared families' members by hand, and the
interop declares other spellings of them that the guard let through: the COM twins `IOpenDoc` to
`IOpenDoc5`, `IOpenDocSilent`, `IActivateDoc` to `IActivateDoc3`, `INewDocument`, `INewDocument2`,
`INewDrawing`, `INewDrawing2`, `INewPart` and `INewAssembly`, and bare `LoadFile`, `LoadAddIn` and
`LoadAdminSettingsFile`. `DocumentLifecycleFamilyTests` now reflects `ISldWorks`, `IModelDoc2` and
`IModelDocExtension` and applies a family grammar - a name belongs when one of its words is `Open`,
`Reopen`, `Activate`, `Deactivate`, `New`, `Load`, `Reload`, `Unload`, `Close`, `Quit` or `Exit` -
and holds every member it finds to one of three answers: a reader by section 2's prefixes, which
stays allowed; an exclusion it names with its reason; or refused, bare and interface-qualified, by
`ReadOnlyGuard` and by every gate the product builds. A member a later interop adds fails the test
until someone decides. The denials stay generated: `list-writer-members.ps1`'s shared rows name the
members, a third row is `IModelDoc2`'s, and `ReadOnlyGuard.Drawing.cs` and the "Feature 011" table of
004's `guard-allowlist.md` are regenerated from one run.

**Why**: FR-005 asks for the application's document activation, closing, creation and macro members
to be refused and the membership checked mechanically for completeness; a hand-named row cannot be,
and a spelling missed once would be missed again. The grammar's compounds are there because their
members are what the families do: `ExitApp` quits SOLIDWORKS, and `FileReload` and `ReloadOrReplace`
reload a document, discarding its changes.

**Evidence**: on 32.5.0.48 the grammar matches 61 names on `ISldWorks` (seven readers, such as
`GetOpenDocumentByName`), 15 on `IModelDoc2` and 4 on `IModelDocExtension`. Before the change 43 of
them were callable (the test's red list). Beyond the eighteen spellings above, it found 22 more,
now refused: on `ISldWorks` `UnloadAddIn`, `ExitApp`, `ActivateTaskPane`, `CloseUserNotification`,
`CreateNewWindow`, `PresetNewDrawingParameters`, `SetNewFilename`, `AddFileOpenItem` to
`AddFileOpenItem3`, `RemoveFileOpenItem` and `RemoveFileOpenItem2`; on `IModelDoc2` `Quit`,
`FileReload`, `ReloadOrReplace`, `CloseFamilyTable`, `ClosePrintPreview`, `ActivateSelectedFeature`,
`ActivateFeatureMgrView` and `DeActivateFeatureMgrView`; on `IModelDocExtension`
`LoadDraftingStandard` and `CloseMessageBar` (with `ReloadOrReplace` and `CloseUserNotification`,
which `IModelDocExtension` shares). That is 40 new names; the table denies 673 new names in all. The
`IModelDoc2` creators the grammar also reaches (`InsertBendTableNew`, `InsertFamilyTableOpen`,
`InsertNewNote3`, `SplitOpenSegment` and their kind) were refused by decision 21A's table already.
Five members stay allowed, each named in the test and in the generated "Not denied" table with its
reason: `OpenDoc6`, `OpenDoc7`, `CloseDoc` and `NewDocument` (section 3 of the contract, unchanged),
and `IModelDoc2.Close`. `Close` was denied first and the remodel tests went red: `BridgeDispatcher`
hands every command name to `ReadOnlyGuard`, which judges `remodel.close` by its member half, so the
bare name `Close` cannot be denied while that command exists; no product path calls
`IModelDoc2.Close`, and `RemodelGuard` and `DrawingOpenGuard` refuse its qualified spelling. A new
test keeps every bridge command name off the denials. The drawing table regenerates byte for byte,
and decision 21A's creation table, which reads this one's names as already denied, regenerates
unchanged. Edited deliberately: `DrawingFamilyCompletenessTests.SharedFamilies` (with `IModelDoc2`)
and `EveryExclusionHasOneOfTheContractsReasons` (a bridge command's member half). Commit `072473e`.

*Amended on the branch's review, the same day (T120)*: editing
`EveryExclusionHasOneOfTheContractsReasons` to accept any bridge command's member half loosened an
existing test (AGENTS.md rule 4): a later exclusion of `Save` or `Rebuild` would have passed it
unexamined. It now accepts exactly one more exclusion, `Close`, asserted to be `remodel.close`'s
half, and went red under a throwaway mutation adding `Save` to the "Not denied" table.
`NoCommandTheBridgeAnswersIsRefusedByTheReadOnlyGuard` stays and says it pins today's dispatcher
(R8.5, the second question). Tests only; commit `b83a751`.

### R8.3 Every attempted open counts toward the ten (T117, T118)

**Decision**: the confirmed read refused a request once the package held ten drawing records, and a
refused read leaves no record - an open SOLIDWORKS refused or did not make read-only, a read that
threw after the open, a merge or save that did not land. Every open the seam begins now counts:
`DrawingOpenScope.OpensAttempted` counts the opens it begins, and `ConfirmedDrawingRead` counts each
one that left no record, per run folder, and refuses once those and the records together reach ten,
naming both counts; the sentence for ten records is unchanged. Only an open counts: a refusal before
the seam, the not-validated refusal and a read of a drawing already open open nothing.

**Why**: the backend asks once per candidate file and counts only reads that landed, and a large
assembly can have hundreds of candidates; with every open refused, nothing bounded how many drawings
the host would open and close. The count lives for the life of the add-in process, not of the source:
the tool service builds a source on every attach, and a run id resolves only in the process that
started its review (`ReviewHost.ReviewRunDirectory`).

**Evidence**: commit `4916998`, with seven new tests of `ConfirmedDrawingReadTests` - among them 25
failing requests, each through a source built anew, bounded at the nine opens the package left - and
one of `DrawingOpenScopeTests`; five of them red before the change. `test_confirmed_drawing_read.py`,
which pins the ten-records sentence on both sides, passes unedited. FR-056, its edge case and
`confirmed-open.md` section 2 item 5 are amended.

*Amended on the branch's review, the same day (T123, T124)*: the check of the opens that left no
record came after the package was loaded, so every request past the limit still loaded the whole
package on SOLIDWORKS's thread before it was refused. Once those opens reach ten on their own, a
request is refused as soon as the run folder is resolved: "the limit of ten drawings for this review
is reached: {m} opens that were refused or failed, so this one was not opened"; below that the bound
is as above, and the ten-records sentence is untouched. Commit `d3bc6ff`; its test, which makes the
package unloadable after ten failed opens, threw the load's `JsonException` before the change. When
the count resets is the owner's question (R8.5, the first).

### R8.4 Decision 137A: the two comments (T119)

Two doc comments in `Sw/SwSession.cs`, on `Attach` and on `OpenReadOnly`, called `OpenReadOnly` the
only file-opening call the extractor makes. That has been untrue since this feature's read-only open
of a confirmed drawing (`DrawingOpenScope`, which probe D14 also runs) and feature 004's `OpenDoc7`
opens of the re-modeler's own copy and of `probe remodel`'s throwaway part. They now name those
calls. Commit `dc6f410`. The amendment's own text, the other half of 137A, is the constitution
pull request's.

*Amended on the branch's review, the same day (T127)*: the same claim was still in four comments of
`Program.cs`, `SuppressTest`'s doc comment, two test comments and the `OpenDoc6` row of section 3 of
`contracts/guard.md`, each now corrected. Comments and docs only; commit `bc19ec2`. What is left is
R8.5's sixth item.

### R8.5 Found on the way, and left for the owner

*Rewritten on the branch's review, the same day*: of the list this section first held, the open that
answers with a document already open is settled (R8.1) and the other stale wording corrected (R8.4);
`IModelDoc2.Close` is now part of the second question below. Nothing here changes without the
owner's decision.

*Amended 2026-10-19 (owner decision 140A)*: the second and third questions are answered - the
bridge judges its own commands and `Close`, `Save` and `Rebuild` are refused (R10.1), and so is
every unused writer the third names, with the families it belongs to (R10.3). The items stay below
as the record of what was asked. *On merging decision 141A, the same day*: the first is settled and
the fourth decided by 141A (R9), each with its line below; the fifth and sixth are unchanged.
*On merging decision 147A, the same day*: the sixth is settled by 147A, with its line below; the
fifth is unchanged.

1. **When the count of ten resets.** The opens that left no record are counted per run folder for
   the life of the add-in process (R8.3). A review's Retry and Recheck run in the same folder -
   `ReviewHost.RetryContextReview` and `ReviewHost.RecheckReview` hand the record's run folder to
   `CreateReviewSession` (`extractor/SwReview.AddIn/Review/ReviewHost.cs`, lines 1668 and 1697) - so
   they inherit a spent count until SOLIDWORKS is restarted. And the bound is checked before the
   seam asks whether the drawing is already open, so once the count is spent even a drawing the
   engineer has open, whose read would open nothing, is refused. Whether the count belongs to the
   run folder, the session or the package, and the sentence that tells the engineer how to recover,
   are the owner's call. Nothing moves until T077 turns the open on: while the switch is off no open
   is attempted, so the count stays at zero.
   *Settled by decision 141A (2026-10-19), R9*: the count is the review session's, a drawing
   already open is never refused because of failed opens, and the refusal says how to go on.
2. **Denying `Close`, `Save` and `Rebuild` needs the dispatcher changed.** *Resolved 2026-10-19
   (owner decision 140A, R10.1).*
   `BridgeDispatcher.Dispatch` hands every command name to `ReadOnlyGuard`, which judges
   `remodel.close`, `remodel.save` and `remodel.rebuild` by the part after the dot, so the bare
   names `Close`, `Save` and `Rebuild` cannot be denied while those commands pass through it:
   `IModelDoc2.Close` stays callable by its bare name through a read-only gate (R8.2), and so do
   `Save` and `Rebuild`. The way out is a dispatcher that checks its known command names without
   handing them to `ReadOnlyGuard`; the three names could then be denied, and
   `NoCommandTheBridgeAnswersIsRefusedByTheReadOnlyGuard`, which pins today's dispatcher, would give
   way to a test of the dispatcher's own check. That reshapes a guard, so it waits for the owner.
3. **Bare writers still allowed, unused today.** *Resolved 2026-10-19 (owner decision 140A, R10.3):
   every one is refused but `SaveBMP`, the capture's.* Measured on 32.5.0.48 by reflecting the interop's
   metadata against the built guard, SOLIDWORKS not started, `ReadOnlyGuard` still lets these
   through by their bare names, and no product path calls any of them through a read-only gate: the
   save family - `IModelDoc2`'s `Save`, `Save2`, `SaveAs`, `SaveAs2`, `SaveAs4`, `SaveAsSilent` and
   `SaveSilent`, `IModelDocExtension`'s `SaveAs`, `SaveAs2`, `SaveDeFeaturedFile`,
   `SaveDraftingStandard`, `SaveTo3DExperience` and `SaveViewToSolidworks`, and
   `ISldWorks.SaveSettings` - and `SetReadOnlyState`, `ForceReleaseLocks`, `SavePackAndGo`,
   `RenameDocument`, `MoveDocument` and `ReplaceReferencedDocument`. `Save3`, `SaveAs3` and
   `SaveSelection` are denied, and `SaveBMP`, also allowed, is the capture's (`SwCaptureView`),
   which writes an image. Denying them is a guard change; `Save` waits on the second question.
4. **The backend's bound** (`tools/drawings.read_confirmed_candidates`) still counts only reads that
   landed, so it goes on asking after refused ones; the host now answers each request past the ten
   with a refusal that opens nothing. Counting refusals there too would be a backend task.
   *Decided with 141A (2026-10-19), R9.4*: the backend goes on asking, since a later candidate the
   engineer has open is still read; nothing changes there.
5. **A hide that throws.** In the seam, a `DocumentVisible(false, 3)` that throws escapes as it
   came, before the open and with no restore; it predates this decision and is unchanged.
6. **What stays of the stale wording.** The suppress-test refusal message
   (`SuppressTest.DocumentNotOpenMessage`) still tells the engineer that "the extractor's only open
   path is read-only": it is product output, which T127 left as it is (comments and docs only), and
   `SuppressTestTests` pins its words "write access" and "read-only". And R2.2 still calls
   `OpenDoc6` "the extractor's one sanctioned read-only open": that is the record of its day, and
   section 3 of `contracts/guard.md` carries the correction.
   *Settled by decision 147A (2026-10-19), 002 `research.md` 147A*: the message now says the
   extractor opens the engineer's documents only read-only, which is true of every path by which
   it opens them, and `SuppressTestTests` pins its words exactly. R2.2 stays as the record of its
   day.

## R9. Decision 141A: the limit of ten counts failed opens per review session (owner, 2026-10-19)

**Source.** The owner's decision 141A of 2026-10-19 (the seventh round's 2A, "Per review session")
answers R8.5's first question: feature 011's limit of ten counts failed opens per review session, a
Retry or Recheck in the same run folder starts its own count, a drawing already open is never
refused because of failed opens, since reading it opens nothing, and the refusal says how to go
on. The tasks are T135 to T144 (Phase 10D). SOLIDWORKS was not started: the C# tests run over
fakes. Measured on the development machine: `SwReview.Extractor.Tests` 9,387 tests before and
9,412 after, `SwReview.AddIn.Tests` 2,472 before and 2,479 after, all green, the build at zero
warnings. Nothing changed on the backend (R9.4). As with decision 136A, nothing changes for an
engineer until T077 turns the open on: while the switch is off no open is attempted, so no count
grows.

*Amended on the branch's review, the same day*: a check of the branch before its review found that
the early refusal asked about another spelling of the drawing than the seam reads, fixed by T142 and
T143 (R9.2). An independent adversarial review of the branch then found no fault in the code,
confirmed no test was loosened, and found what T144 puts right: a sentence each of this record, the
code and the contract that said a run folder holds one review session at a time, which a context
review's Retry belies (R9.1); two limits of the refusal's first way on, now in the contract (R9.5,
item 4); and three flows that no test pinned. Measured after: `SwReview.Extractor.Tests` 9,413 tests
and `SwReview.AddIn.Tests` 2,482, all green, the build at zero warnings.

### R9.1 The count is the review session's (T135, T136)

**Decision**: `ConfirmedDrawingSession` (`Dump/ConfirmedDrawingSession.cs`) holds what the confirmed
read keeps for one review session: its run folder and the opens it attempted that left no record.
Each `SessionRecord` holds its own (`ConfirmedDrawings`), and `ConfirmedDrawingRead` takes the
session in place of the run folder, so the process-wide dictionary decision 136A kept is gone. A
Recheck, or a context review's Retry, which is a new record in the same folder, starts its own
count; two sessions never share one; and a count lives as long as its record - a Recheck replaces
the record, the chip's Remove forgets it, the host's dispose clears it, and one never removed keeps
its count until SOLIDWORKS closes - so memory stays bounded by the records the host keeps anyway.

**How the host knows the session.** A `drawing.read` names `run_id` and `document_id` and nothing
else: the dispatcher refuses any other parameter (`Bridge/BridgeDispatcher.cs`,
`DrawingReadParameters`, line 736). The run id resolves to a run folder by
`ReviewHost.ReviewRunDirectory`'s rules (`Review/ReviewHost.cs` line 600: a review record's folder
name, ignoring case, never read as a path, null when ambiguous), and `ReviewHost.DrawingReadSession`
(line 641) answers the latest review the host started in that folder and still tracks. A new session
in a folder takes over its reads from the earlier one: an ordinary Retry makes a new folder
(`StartReview`, line 1661), while a context review's Retry (`RetryContextReview`, lines 1704 and
1716) and a Recheck (`RecheckReview`, lines 1729 and 1745) start a new session in the same folder
through `CreateReviewSession`, which publishes a new record (line 1821) - appended for the Retry,
which leaves the failed review tracked beside it (`Publish` drops only a record of the same chat id,
line 493), and in the replaced record's place for the Recheck. "Latest" is the order records were
made in (`SessionRecord.Sequence`, line 115), not the list's, because of that in-place replacement.
*Corrected on the branch's review, the same day*: R9 first said a run folder holds one review
session at a time, which a context review's Retry belies. And a session asks for drawings only after
the host has tracked its record: the backend calls `drawing.read` only when an answer batch confirms
the candidate question (`agent/runner.py` line 1425), which the engineer answers after
`review.started` or `review.rechecked`, and a Recheck's carried answers read no drawing
(`carry_from`, line 1480, `read_drawings=False`). So the count is keyed by a session the host
resolves from its own records, and nothing a request supplies but the run id can choose or reset it.

**Evidence**: commit `f6cb5c5`, tests first, red for want of `ConfirmedDrawingSession` and
`ReviewHost.DrawingReadSession`: three new tests of `ConfirmedDrawingReadTests`, four cases of
`ReviewHostTests`, one of `EngineeringContextHostTests` and one of `ToolServiceWiringTests` through
the real review host and pipe. Under a throwaway mutant counting per run folder as 136A did, exactly
the three per-session tests failed (two of the extractor's and the wiring test); under one taking
the last record in list order, exactly the case of a Recheck that a later session of the folder
follows.

### R9.2 A drawing already open is never refused because of failed opens (T137, T138)

**Decision**: the ten-records check stays before the seam and bounds every read, a drawing already
open included. The failed opens now bound only an open: when the records and the session's failed
opens together reach ten, `ConfirmedDrawingRead` hands the seam the limit's sentence, and
`DrawingOpenScope.Read(path, read, openRefusal)` refuses with it at its own lookup - after the
not-validated sentence, before anything is hidden or opened, no open begun - while a drawing that
lookup finds open is still read. 136A's early refusal is kept: once a session's failed opens alone
reach ten, a request is refused before the package is loaded, after one call,
`DrawingOpenScope.IsOpen` - the read's own lookup, through the same gate, and nothing else - of the
document's candidate drawing, by the very path the seam would look up, its first candidate row's,
as the session last loaded or merged its package (`ConfirmedDrawingSession.Remember`). A drawing
found open goes on to be read, and a document the session knows no candidate for goes on to every
rule. *Corrected on the branch's review, the same day (T142, T143)*: the early look first asked
about discovery's rule applied to the document's path. That is the row's path in every package
the extractor writes, but a row may spell the same file otherwise, as the read accepts, and then
the early look asked about another spelling than the seam reads, and could refuse a drawing the
seam would have read; it also called `OpenDrawingDiscovery.CandidatePath`, which can throw.

**Why**: the decision's own reason - reading a drawing already open opens nothing - and 136A's
review's: the backend asks once per candidate file, and a large assembly can have hundreds, so a
spent session must keep costing SOLIDWORKS's thread almost nothing; one lookup instead of a
package load per request does that. The early refusal needs the candidate's path, which only the
package holds, hence the session's memory of it: its candidate rows only ever go and its drawings
only ever come, so what it remembers can only send a request on to the full rules, never past
them. Deciding at the seam's lookup, rather than at the look before the package is loaded, means a
drawing the engineer closes in between is refused, never opened, so no race can overrun the
bound.

**Evidence**: commit `e78b9b7`, tests first. Red for want of `IsOpen` and `Read`'s refusal
parameter; with them added, thirteen cases of `ConfirmedDrawingReadTests` and the new wiring test
were red. The seam's own new tests passed once its members existed; one expectation of the
`IsOpen` test was corrected first, since the gate's recording observer lists each member once.
Edited deliberately: four of 136A's bound tests and its before-the-package test now assert exactly
one lookup where they asserted none, nothing opened, their sentences unchanged. Throwaway mutants
dropping the early refusal (four failed) and never handing the seam the refusal (seven failed) were
each caught. The correction: commit `88d84d8`, test first - with the housing's candidate row
spelled through `sub\..\` and the drawing open under that spelling, a spent session's request
was refused before the change and is read after it, SOLIDWORKS asked only the seam's own lookup,
twice.

### R9.3 The refusal says how to go on (T139, T140)

**Decision**: both limit sentences end "; a drawing already open in SOLIDWORKS is still read, since
reading it opens nothing, and a new review session (Retry or Recheck) starts its own count", made by
the one helper they share (`ConfirmedDrawingRead.LimitReached`). The ten-records sentence is
unchanged and names neither, since a new session keeps the package's drawings; the backend pins it.

**Why**: both ways on are true of the host as R9.1 and R9.2 left it, and the words are the
decision's. For the first to be true whenever it is said, the limit's sentence is said only while the
package holds fewer than ten drawings: the full rules check the ten records first, and the early
refusal's memory is brought up to date after the session's own merge and holds nothing once the
package holds ten, so a request then meets the ten-records sentence.

**Evidence**: commit `d29f2d9`, tests first, red for want of the words: five cases of
`ConfirmedDrawingReadTests` (both forms in three counts, the ten-drawings case, and 136A's
before-the-package test, edited deliberately for its exact sentence) and the wiring test, which now
asserts the full sentence as the backend receives it; the ten-records pin passed before and after.
Throwaway mutants skipping the memory's update after a merge, or remembering candidates in a package
holding ten drawings, each failed the ten-drawings test. `test_confirmed_drawing_read.py` passes
unedited.

### R9.4 The backend's loop is unchanged

**Decision**: `tools/drawings.read_confirmed_candidates` goes on asking once per candidate file
after the host refuses one for the limit, and gains no recognised form of that refusal.

**Why**: under decision 141A the limit's refusal is no longer final for the batch. A later
candidate the engineer has open is still read, and only the host can tell which, by asking
SOLIDWORKS; a backend that stopped at the first such refusal would refuse exactly what the decision
says must not be refused. What stopping would have saved, the host's answers to the rest, is one
lookup each (R9.2), and the backend's own bound still stops at ten drawing records. With nothing to
act on, the refusal needs no form the backend recognises beyond the sentence it already records,
word for word, as each candidate's reason.

### R9.5 Found on the way, and left for the owner

1. **What a Recheck re-reads.** The sentence names a Recheck because it starts a new count, which is
   true. But a Recheck carries an earlier confirmed answer onto the same candidate question with no
   new read (015 `contracts/recheck.md` section 4), so after a read refused for every candidate it
   reads nothing again; it asks again, and so can read, only when part of the earlier read merged
   (90A). A new Review reads a drawing the engineer has open natively, and a context review's Retry
   asks the question afresh. Whether the sentence should name a Recheck at all, or name a new
   Review, the surest way on, which it does not; and whether a Recheck should ask a refused
   candidate question again, are the owner's call; neither changes here. (Retry is offered only
   on an error card, and a Recheck only as the Send of a restored waiting review.)
   *Settled by decision 147A (2026-10-19)*: the sentence names a new review first, and no Retry
   or Recheck - both limit sentences end "; a new review (press Review) starts its own count, and
   a drawing already open in SOLIDWORKS is still read, since reading it opens nothing"
   (`contracts/confirmed-open.md` section 2 item 5; 002 `research.md`, 147A). Whether a Recheck
   should ask a refused candidate question again is not part of 147A and stays the owner's call.
2. **Two sessions of one folder at once.** A request is counted for the latest session of its run
   folder, since the request names no session. An older session of the same folder that still asked
   - a context review's failed chat, whose chip is still shown - would count against the latest's.
   It could not reset that count, so the bound holds; telling the two apart would need the request
   to name its session, which the host could not trust. *On the branch's review*: and should the
   engineer remove the latest with the chip's Remove while its chat still asks, its requests reach
   the earlier record's session, with that session's own count and memory
   (`RemovingTheLatestSessionOfAFolderLeavesTheEarlierOnesOwnSession` pins which session answers).
3. **The early refusal's sentence** omits the package's drawings, as 136A's did: the package is not
   loaded. The full rules' sentence names both counts.
4. **Found on the branch's review: where the first way on overclaims.** "A drawing already open in
   SOLIDWORKS is still read" holds for a drawing the lookup finds by the candidate's path. One
   SOLIDWORKS has open only under another spelling of that path (a mapped drive against its UNC
   path) is found only by `OpenDoc6`'s already-open warning (R8.1), and once the bound is spent no
   open is made to learn it, since that same call would open a drawing that is not open; such a
   drawing is refused. Whether SOLIDWORKS's lookup itself matches the other spelling is the seat's
   to show (R8.1). And the early refusal knows the package as its own session last loaded or merged
   it: should another session of the folder have brought it to ten drawings since (item 2's case),
   its limit sentence stands where the full rules would give the ten-records one - a refusal
   either way, and the backend stops asking at ten drawings. `contracts/confirmed-open.md` section
   2 item 5 says both.
5. **Also on the review, accepted as they are.** The early look asks SOLIDWORKS about the path the
   candidate row names before rule 4 has checked it against discovery's rule: a read-only lookup,
   and only ever of a `.SLDDRW` path. And a spent session now asks SOLIDWORKS one thing, so a lookup
   that throws there answers as a failure rather than as a refusal, as the seam's own lookup always
   has.

## R10. Decision 140A: the bridge judges its own commands, and the guard's unused writers are refused (owner, 2026-10-19)

**Source.** R8.5 left two of decision 136A's findings to the owner: refusing `Close`, `Save` and
`Rebuild` needed the bridge's dispatcher changed (its second question), and `ReadOnlyGuard` still
let through bare writers that no product path calls (its third). The owner's decision 140A of
2026-10-19 ("Both, test first") answers both under this feature: the dispatcher judges the commands
it knows without handing their names to the read-only guard, the three members are refused, and so
are the unused writers "and the others the interop holds", with the save, rename, move, replace and
release-lock families proved complete by reflection. The tasks are T145 to T153 (Phase 10E).
SOLIDWORKS was not started: the C# tests run over fakes and the interop stand-in, and the interop
(`SolidWorks.Interop.sldworks` 32.5.0.48) was read as metadata only. Measured on the development
machine: `SwReview.Extractor.Tests` 9,387 tests before and 9,705 after, `SwReview.AddIn.Tests` 2,472
before and after, all green, the build at zero warnings.

*Amended on a review of the branch the same day, before it was handed on*: the review found no
blocker - no request reaches anything it could not before, the generated tables match their
generators, and the new tests fail when the change is reverted - and found what T149 to T153 fix:
the families read over six of the 34 interfaces the generated tables are written against (R10.2,
R10.3), the family sweeps written three times, an exception's staleness check satisfied by another
guard's call, the creation read audit still keyed in any case, and comments left wrong. R10.4 holds
what it measured beyond the decision.

*Amended on a second, independent and adversarial review the same day (R10.5)*: it found no seat
breakage, no new write path and no test loosened, and found what T154 to T158 put right - a named
literal that exempted its spelling anywhere in the product, a dispatcher check no test could see
removed, sentences that said the wrong thing of the capture's write and the remodel commands, and a
miscount - with two questions for the owner (R10.4, items 4 and 5). Decision 141A reached main first
and took R9, Phase 10D and T135 to T144, so this section, its phase and its tasks were renumbered
past them before main was merged in (R10.5). *And on that review's second pass, at `44db63e`*: the
fixes hold, and T159 to T162 answer four nits and record a third question for the owner (R10.4,
item 6).

### R10.1 The bridge judges its own commands; `Close`, `Save` and `Rebuild` refused (T145, T146)

**Decision**: `SwBridgeDispatcher.Dispatch` no longer hands the request's command name to
`ReadOnlyGuard`. After the secret policy it asks `SwBridgeDispatcher.Answers(command)` - an exact,
ordinal match against `AnsweredCommands`, the bridge's own fixed set of eighteen: the six of
`BridgeCommands.All` and the twelve of `RemodelCommands.All` - and answers any other name
`Unknown command '<name>'. This bridge answers ...`, with no result, before a handler is looked up.
`Run`'s switch is unchanged; its own unknown branch, which only a command added to the set without a
case could now reach, shares that refusal. *Changed 2026-10-19 on the decision's second review
(`7ee2fee`, R10.5)*: that branch throws `InvalidOperationException` now, the dispatcher's own
mistake, so `Dispatch`'s check is the only refusal of an unknown name. With command names no
longer judged as members,
`list-writer-members.ps1` names `IModelDoc2`'s `Close`, `Save` and `Rebuild` and
`IModelDocExtension`'s `Rebuild`, and 136A's `Close` exclusion is gone.

**Why the name check was there, and what it gave**: defence in depth, written with the bridge's
first commands (feature 001's T072, "ReadOnlyGuard on every request"): "the guard sees the command name itself, so "command": "Save3" cannot
reach a handler even if one were ever added for it". It never refused a name the dispatcher would
otherwise have answered. What refuses an unknown command is `Run`'s default branch, and on the
add-in's host, before it, `ScopedSecretPolicy`, which authorizes no name outside its scopes
(`unauthorized`). All eighteen known names passed the check - 136A's pin,
`NoCommandTheBridgeAnswersIsRefusedByTheReadOnlyGuard`, held it - so its one effect on a known
command was the one R8.5 found: the guard judges a qualified name by the part after the dot, so
`remodel.close`, `remodel.save` and `remodel.rebuild` were judged as `Close`, `Save` and `Rebuild`,
and none of those members could be denied. A command name is not an interop member.

**No command reaches anything new.** (1) The commands answered are the same eighteen:
`TheBridgeAnswersExactlyItsOwnFixedSet` pins the list literally, so a nineteenth is a deliberate
edit there as in the secret scopes, and every one of the eighteen passed the old check. (2) Every
other name is refused before anything runs, as it was, by the guard or by the default branch:
`ANameOutsideTheSet_IsRefusedAsUnknownBeforeAnythingRuns` tries 29 - mutating members' names bare
and qualified, the commands' member halves, other cases, spaces, `remodel.` alone and with an
unknown member, empty and blank - and `ANullCommand_IsRefusedAsUnknownToo` a null one, and nothing
behind the dispatcher is touched. (3) The handlers are unchanged, and every SOLIDWORKS call under
them goes through a gate whose guard is unchanged and is never chosen by the request: the session's
read-only gate for the review commands, `DrawingOpenGuard` for `drawing.read`'s open, and for the
`remodel.*` family `RemodelGuard`, the 004 exception (the host's `RemodelGate`, or the dispatcher's
own, both built with `new RemodelGuard()`).
`TheCommandsNamedForADeniedMemberAnswer_AndTheirWritesAreTheRemodelGuardsToJudge` drives
`remodel.rebuild`, `remodel.save` and `remodel.close` through a run: each answers, nothing is
refused, and their writes were the stage-1 keys `IModelDoc2.ForceRebuild3`, `IModelDoc2.Save3` and
`ISldWorks.CloseDoc`, the first two refused by the read-only guard, so only `RemodelGuard` lets them
through. (4) The secret policy runs first, unchanged. What changed is the answer to a refused name:
"Unknown command" with `result: null`, where a name the guard denied was answered as a member that
modifies the model - with `error_code: guard_refused` when it began `remodel.` - and, from a caller
in process only, an empty name with an `ArgumentException`: on the wire `BridgeCodec.ReadRequest`
refuses an empty or blank command before the dispatcher. No client sends such a name: `client.py`
and `remodel_client.py` send only the commands of their own allowlists. The console's `PROTOCOL.md`
says so.

**The read audit**: refusing the three names - in any case, as the guard matches - made
`DrawingFamilyReadAuditTests` find literals that are no member the product gates. It now skips a
line that is a comment and nothing else: a word quoted in a comment (`"rebuild"` in a sentence,
`<see cref="Close"/>` naming a C# method, `<paramref name="close"/>`) is no string the program
holds, and a comment after code on the same line is still read. The rest are named literals, each
with its reason: the three bridge commands, judged as qualified keys by the part after the dot, with
the session-end reason spelled `remodel.close` and the frozen interop manifest's `used_by` column,
which names the commands; the label `close` that `CloseCopyUnsaved` gives its clean-up step, gated
as `ISldWorks.CloseDoc`; the plan's JSON member `rebuild`; and the Review page's message types
`events.close`, `send_when_checked.save` and `settings.save` (`ReviewHost`). The named literals are
now matched exactly rather than in any case: keyed in any case, the lower-case `close` would have
exempted a gated `Close`, the very member the decision refuses. Every earlier key was already a
literal spelled exactly, so this exempts less; on the review, decision 21A's audit
(`CreationFamilyReadAuditTests`, whose `scale` would have exempted a gated `Scale`) was keyed
exactly too. The staleness check judges a named literal as the audit judges any, so a qualified one
is refused when its member half is. `OnlyAWholeLineCommentIsSkipped` pins the skip.

**Evidence**: commit `7a6eeda`. Red against the old dispatcher and denials, 17: the dispatcher's own
rule, the three members in every spelling by every gate
(`CloseSaveAndRebuildAreRefusedInEverySpellingByEveryGate`, which replaces the pin), `IModelDoc2.Close`
out of 136A's exclusions, the narrowed exclusion test, and the named literals' staleness check. With
the three denials applied and the old dispatcher, 64, among them 41 existing remodel tests - every
one that dispatches `remodel.close`, `remodel.save` or `remodel.rebuild` - and
`Dispatch_UnknownCommand_ListsTheOnesItAnswers`, which sends `rebuild`: what 136A found, measured.
Edited deliberately: `Dispatch_CommandNamedAfterAMutatingApi_IsRefusedAsUnknownBeforeAnythingRuns`
(the refusal kept and nothing touched; its sentence changed), `DrawingRead_IsOneOfTheCommandsTheBridgeAnswers`
(answered, where it passed the read-only guard), and `EveryExclusionHasOneOfTheContractsReasons`,
narrowed back to the contract's reasons. The table denies 676 new names; the creation table
regenerates unchanged. `PROTOCOL.md`, `contracts/guard.md` sections 1, 2, 3 and 5 and 004's
`guard-allowlist.md` say so. On the review: commit `2712b16` (the creation audit keyed exactly, the
command names' reasons completed) and `dc064e1` (the comments the decision left wrong, among them
`PROTOCOL.md`'s sentence on the empty name, and `ReadOnlyGuard.cs`'s two calling a capture image
`SaveAs3`'s one legitimate use - the capture writes with `SaveBMP`).

### R10.2 The families the unused writers belong to: the decision

**Decision**: `DocumentWriteFamilyTests` reflects the 34 interfaces the generated tables are
written against: `ISldWorks`, `IModelDoc2` and `IModelDocExtension` - 136A's three - and the
document types a model document also
is, `IPartDoc` and `IAssemblyDoc`, whose saves, replaces and rebuilds act on that same document
(004's `guard-allowlist.md` had recorded `IPartDoc.SaveToFile` to `SaveToFile3` as open); and every
interface one of the guard's generated tables reflects - decision 21A's creation interfaces,
`IFeatureManager` among them, and this feature's 28 drawing families, `IDrawingDoc` among them: 34
interfaces. *Widened on the review*: the test first read the six, and the review found three
members of the words on `IFeatureManager` that the guard let through. A member belongs to the
families when one of its words, read as 136A's grammar reads them - the verb with its capital,
starting the name, following a COM twin's `I` or starting a later word, and ending where the name or
the word does - is one of these:

| Word | Why it is a family |
|---|---|
| `Save` | the members named for saving: the document, a file made from it (`SaveToFile`, `SaveDeFeaturedFile`), or what the save dialog offers (`AddFileSaveAsItem`). A file written under another word, an export or a publish, is R10.4's |
| `Rename`, `Move`, `Copy` | the document's file renamed, moved or copied, and the references other documents hold to it updated. `Copy` because `ISldWorks.CopyDocument` is `MoveDocument`'s twin - the same arguments and options - and the word's other members copy the document's contents (`CopyWithMates`, `CopyDraftingStandard`) or its selection (`EditCopy`) |
| `Replace` | a referenced document or a component swapped for another |
| `Release`, `Lock`, `Unlock` | the release-lock family: the locks SOLIDWORKS holds on the file released (`ForceReleaseLocks`, which lets another process change it), the storage streams it opens in the file closed (`IRelease3rdPartyStorage`, `IRelease3rdPartyStorageStore`, `ReleaseStream`), and the locks on the document's references and on the application's commands (`LockAllExternalReferences`, `Lock`) |
| `ReadOnly` | the read-only state: `SetReadOnlyState` would undo, behind the engineer, what decision 136A's `IsOpenedReadOnly` check reads |
| `Rebuild` | the rebuilds, which change the model and can resolve lightweight components (`ReadOnlyGuard`'s first denial) |

Whole words keep reads out: `HasRenamedDocuments`, a read whose prefix is none of
`contracts/guard.md` section 2's, `IsLightLockedToModel` and `ApplySavedSortScheme` are of none.
Every member is held to one of three answers: a reader by section 2's prefixes, allowed in both
spellings; a member left allowed with its reason, which must stay a literal of the product file
whose call needs it; or refused bare and qualified with its interface by `ReadOnlyGuard`, and by
every gate the product builds except exactly the exceptions the test names, each with its reason
and the file whose call needs it. A member a later interop adds fails the test until someone decides
which it is, and so does a guard that comes to let another member through, or a member left allowed
or an exception whose call has gone.

**Why named rows, and these interfaces**: the denials stay generated, as 136A's: the shared rows of
`list-writer-members.ps1` name the members, three rows more (`IPartDoc`, `IAssemblyDoc`,
`IFeatureManager`), and the test reflects the interop with its own copy of the grammar to prove the
rows complete, the independent check `DrawingFamilyCompletenessTests` is for the drawing table. The
drawing families' members of the words are writers of their family rows already. The same words on
the interop's other interfaces are R10.4's. Because the guard matches bare names, a refused name is
refused on every interface that declares it - `IBody2.Save`, which writes a body to a stream, and
`ISketchBlockDefinition.Save` among them; no product path calls either. *On the review* the family
sweeps of 136A's class and this one share one helper, `GuardSweep` (commit `e2b148f`): the guards the
product builds its gates with, a grammar read over interfaces, the members to refuse, the two
spellings of a key, and what each guard lets through of them. A throwaway mutation letting
`SuppressTestGuard` through `Close` and `SaveAs` turned all three of its sweeps red.

### R10.3 The families: the members and their classification (T147, T148, T150, T151)

**Evidence**: on 32.5.0.48 the grammar finds 129 members on the 34 interfaces: 94 on the six it first
read, 13 on `IFeatureManager` and 22 on the drawing families other than `IDrawingDoc`. Before the decision
64 of them were callable, 61 names (`Rebuild`, `SaveAs` and `SaveAs2` are each on two interfaces). Now
15 are readers, 2 are left allowed and 112 are refused, 62 of them, 59 names, by this decision; with
`Close` (R10.1) the table's new names go from 673 to 733. *Corrected on the decision's review*: this
said 63 callable and 60 names, missing `Rebuild` on two interfaces; measured again against `ca7a720`'s
guard, the 64 are the 62 this decision refuses and the two it leaves allowed:

| Interface | Refused by decision 140A | Refused before, and by what | Left allowed | Readers |
|---|---|---|---|---|
| `ISldWorks` | `AddFileSaveAsItem`, `AddFileSaveAsItem2`, `CopyAppearance`, `CopyDocument`, `ICopyDocument`, `IMoveDocument`, `MoveDocument`, `RemoveFileSaveAsItem`, `RemoveFileSaveAsItem2`, `ReplaceReferencedDocument`, `RunBatchSaveProcess`, `SaveSettings`, `ShowBatchSaveTo3DExperienceDlg` | - | - | `GetLastSaveError`, `GetSaveTo3DExperienceOptions` |
| `IModelDoc2` | `EditCopy`, `ForceReleaseLocks`, `IRelease3rdPartyStorage`, `Lock`, `LockAllExternalReferences`, `LockFramePoint`, `LockLightToModel`, `Rebuild` (R10.1), `Save` (R10.1), `Save2`, `SaveAs`, `SaveAs2`, `SaveAs4`, `SaveAsSilent`, `SaveSilent`, `SetReadOnlyState`, `SetSaveAsFileName`, `UnLock`, `UnlockAllExternalReferences`, `UnlockFramePoint` | `EditRebuild3`, `ForceRebuild3`, `Save3`, `SaveAs3`, `SetSaveFlag` (`ReadOnlyGuard.cs`); `InsertFeatureReplaceFace` (the `InsertFeature` prefix); `ReloadOrReplace` (136A) | `SaveBMP` | `GetSaveFlag`, `IsOpenedReadOnly` |
| `IModelDocExtension` | `CopyDraftingStandard`, `EditRebuildAll`, `IRelease3rdPartyStorageStore`, `MoveDecal`, `Rebuild` (R10.1), `ReleaseStream`, `RenameDocument`, `RenameDraftingStandard`, `SaveAs`, `SaveAs2`, `SaveDeFeaturedFile`, `SaveDraftingStandard`, `SavePackAndGo`, `SaveTo3DExperience`, `SaveViewToSolidworks`, `set_ShowPartRebuildIndicators` | `ForceRebuildAll`, `SaveAs3` (`ReadOnlyGuard.cs`); `ReloadOrReplace` (136A); `MoveOrCopy`, `RotateOrCopy`, `ScaleOrCopy`, `SaveSelection` (decision 21A) | - | `GetAdvancedSaveAsOptions`, `get_NeedsRebuild`, `get_NeedsRebuild2`, `get_ShowPartRebuildIndicators` |
| `IPartDoc` | `SaveToFile`, `SaveToFile2`, `SaveToFile3` | `EditRebuild`, `ForceRebuild` (feature 011, the bare names `IDrawingDoc` shares) | - | - |
| `IAssemblyDoc` | `CopyWithMates`, `CopyWithMates2`, `ForceRebuild2`, `ReplaceComponents`, `ReplaceComponents2`, `ReplacePLMComponents`, `SaveIsolate`, `set_EnableAssemblyRebuild` | `EditRebuild`, `ForceRebuild` (feature 011) | - | `get_EnableAssemblyRebuild` |
| `IFeatureManager` (on the review) | `MoveRotateLiveSectionPlane`, `set_MoveSizeFeatures` | `CreateSaveBodyFeature`, `InsertSaveOutBodies`, `InsertMoveCopyBody`, `InsertMoveCopyBody2`, `InsertMoveFace`, `InsertMoveFace2`, `InsertMoveFace3`, `IInsertMoveFace2` (decision 21A); `InsertFeatureLock` (the `InsertFeature` prefix) | `MoveToFolder` | `get_MoveSizeFeatures` |
| `IDrawingDoc` and the other 27 drawing families | - | all 23 members of the words that are not readers (feature 011's family rows): `EditRebuild`, `ForceRebuild`, `ReplaceViewModel`, `SaveBlock`, `SaveCustomSymbol`, `SaveLineStyles`, `ISheet.SaveFormat`, `IView.MoveViewArrow`, `ReplaceViewWithBlock`, `ReplaceViewWithSketch`, `IDimension.set_ReadOnly`, `IAnnotation.SaveStyle`, `INote.set_LockPosition`, `set_ReadOnly`, `ITableAnnotation`'s `MoveColumn`, `MoveRow`, `SaveAsPDF`, `SaveAsTemplate`, `SaveAsText`, `SaveAsText2`, `SetLockColumnWidth`, `SetLockRowHeight`, and `IBomTableAnnotation.SaveAsExcel` | - | `IDimension.get_ReadOnly`, `INote.get_LockPosition`, `INote.get_ReadOnly`, `ITableAnnotation.GetLockColumnWidth`, `GetLockRowHeight` |

The exceptions, each a guard written for one and nothing more: `SuppressTestGuard` lets the bare
`ForceRebuild3` through (feature 003's suppress-test, `SuppressTest.cs`), `RemodelProbeGuard` the
bare `ForceRebuild3` and `SaveAs3` (`probe remodel`'s throwaway part, `SwRemodelProbeHost.cs`), and
`RemodelGuard` `IModelDoc2.ForceRebuild3` and `IModelDoc2.Save3` (the re-modeler's one rebuild and
one save of its own copy, `BridgeDispatcher.cs`); `ReadOnlyCallGuard` and `DrawingOpenGuard` let
none through. `EveryExceptionIsStillNamedByTheProduct` checks each key in its own file, so one
guard's exception cannot be kept alive by another's call of the same member.

**What stays allowed, and the search that shows nothing else is called.** Every name newly refused
was searched for in the product (`SwReview.Extractor`, `SwReview.AddIn`, `SwReview.Extractor.Console`):
as a literal or a qualified literal - the read audit's scan, which reaches every gated call, every
constant a call site names a member through, the bridge, the probes and the console - and as a
direct interop call (`.Save(`, `.Close(`, `.Rebuild(` and each other name followed by a parenthesis).
None is named, and none is called on an interop object: the only `.Save(` calls are
`PackageAppender.Save`, the settings', a bitmap's and the re-modeler's `IRemodelDocument.Save`,
which is `Save3` under its qualified key; the only `.Close(` calls are the C# methods
`ReadOnlyOpen.Close` and `EventStreamPump.Close` and the remodel backend's; the one `.Rebuild(` is
the suppress-test's target, gated as `ForceRebuild3`. Two members of the families are called by a
product path, and stay allowed with their reasons on the generated "Not denied" table:
`SaveBMP` - `SwCaptureView.SaveImage` gates the bare name on the session's read-only gate and has it
write a bitmap of the graphics window beside the capture's PNG, at the PNG's name with `.bmp`;
`SaveBMP` writes to whatever path it is handed, a document's included, and a guard judges names,
never paths, so what keeps this path an image is the capture's own code, which names the PNG under
the `captures` folder of the directory the host chose and checks its extension with
`ReadOnlyGuard.AssertSaveAs` first; `SaveAs3` stays refused (corrected on the decision's review:
this said `SaveBMP` cannot write a document) - and `MoveToFolder` -
`probe remodel`'s PROBE-5 moves a feature of its throwaway part into a folder, gated bare under
`RemodelProbeGuard`, which hands it to the read-only guard, as it does `NewDocument`; never the
engineer's document, which `probe remodel` refuses to run beside. `RemodelGuardTests` keeps
`MoveToFolder` as its example of a bare writer the denylist misses, the reason the re-modeler's
writes are interface-qualified. The test requires each to stay a literal of its file
(`SwCaptureView.cs`, `SwRemodelProbeHost.cs`), so an entry goes stale loudly.

**`SetReadOnlyState` and the re-modeler**: `RemodelGuard` refused `SetReadOnlyState` itself, as one of
its `ExcludedMembers`, because `ReadOnlyGuard` did not. Now that the table refuses it, it left that
list rather than be refused in two places, as
`RemodelExclusions_AreOnlyMembersTheReadOnlyGuardDoesNotAlreadyRefuse` asks, and the generator, which
excludes `RemodelGuard`'s own refusals, could name it. `RemodelGuard` answers it as before: refused,
qualified by its rule for a key off the allowlist and bare by the read-only guard's answer
(`Assert_ExcludedMember_IsRefused`, unedited). The stage-1 allowlist and its five keys that override
a read-only denial do not move, and neither does any write of the re-modeler, the suppress-test or
`probe remodel`.

Commit `b8d0ad9`, tests first: three of `DocumentWriteFamilyTests` red (57 members callable, 55
names), with `TheSharedRowsAreDeclaredOnTheirInterfacesAndRefused` (no `IPartDoc` or `IAssemblyDoc`
row) and `RemodelExclusions_AreOnlyMembersTheReadOnlyGuardDoesNotAlreadyRefuse`. Edited
deliberately: `DrawingFamilyCompletenessTests.SharedFamilies` (`IPartDoc`, `IAssemblyDoc`),
`RemodelGuardTests.ExpectedRemodelExclusions` (`SetReadOnlyState` out), and
`EveryExclusionHasOneOfTheContractsReasons` and `TheSanctionedCallsStayAllowed` (`SaveBMP`, a call the
capture makes). The table denied 731 new names. On the review, commit `8c4780e`, tests first: four
red (`MoveRotateLiveSectionPlane` and `set_MoveSizeFeatures` callable, `MoveToFolder` not on the
"Not denied" table, no `IFeatureManager` row); `SharedFamilies` gained `IFeatureManager`, and the
two exclusion tests `MoveToFolder`, edited deliberately. The table regenerates byte for byte, 733 new
names; the creation table regenerates unchanged, and the read audit finds no product literal among
the new names. `contracts/guard.md` sections 1, 2, 3 and 5 and 004's `guard-allowlist.md` say so.

### R10.4 Found on the way, and left for the owner

Each of these is beyond what decision 140A names, so nothing here was changed. Each was measured on
32.5.0.48 by reflecting the interop's metadata against the built guard, and no product path names
or calls any of them: a search of the product for each as a literal and as a call found only
`System.IO`'s `File.Copy` and `File.Move` and `Marshal.Copy`.

*Amended 2026-10-19 (owner decision 144A, R11)*: items 1, 2, 5 and 6 are settled, each with its
line below; items 3 and 4 stay recorded as they are.

1. **The lifecycle families on `IAssemblyDoc`.** 136A's grammar (`Open`, `Activate`, `New`, `Load`,
   `Reload`, `Close`, `Quit`, `Exit` ...) reads three interfaces. On `IAssemblyDoc` it would find
   members the guard lets through: `OpenCompFile` and `SelectiveOpen`, which open component
   documents; `ComponentReload`, `ComponentReload2`, `IComponentReload2` and `IComponentReload3`;
   `InsertNewPart`, `InsertNewPart2`, `InsertNewAssembly`, `InsertNewVirtualPart`,
   `InsertNewVirtualAssembly` and `InsertLoadReference`; `ActivateGroundPlane`, `ExitIsolate` and
   `TemporaryFixGroupExit`. Refusing them would be 136A's rows and test extended to a fourth interface.
   *Settled 2026-10-19 by decision 144A (R11.3)*: the fifteen are refused, and
   `DocumentLifecycleFamilyTests` reads `IAssemblyDoc` as a fourth interface.
2. **The drawing writer grammar's gaps.** Section 2 of `contracts/guard.md` gives the `I` twin to four
   verbs (`ISet`, `IAdd`, `IInsert`, `ICreate`), so five twins of other verbs on the drawing families
   pass: `IDrawingDoc.IEditSelectedGtol`, `IMakeCustomSymbol2`, `INewGtol` and `IReorderSheets`, and
   `IView.ISelectEntity`. And its reader prefix `Is` takes in two writers by their first letters:
   `IDrawingDoc.IsolateChangedDimensions`, and on a document type `IAssemblyDoc.Isolate`.
   *Settled 2026-10-19 by decision 144A (R11.4)*: the grammar gives the twin's `I` to every verb,
   `Isolate` is a verb, and the reader prefixes are whole words; all seven are refused.
3. **Writers of other words on the covered interfaces.** The guard is a denylist (R2.2), and the
   families are chosen words. Among the writers of other words that pass: `IModelDoc2.BreakAllExternalReferences`
   (its twin `IModelDocExtension.BreakAllExternalFileReferences2` is refused by decision 21A's table),
   `IModelDocExtension.UpdateExternalFileReferences` and `ISldWorks.SetMissingReferencePathName`; the
   settings writers `ISldWorks.RestoreSettings` and `DownloadFromMySolidWorksSettings` (`SaveSettings`
   is refused); `IModelDoc2.SetBlockingState` and `ResetBlockingState`, which block commands as the
   refused `Lock` and `UnLock` do; the exports and publishes `IPartDoc.ExportToDWG`, `ExportToDWG2`,
   `IExportToDWG`, `IExportToDWG2` and `ExportFlatPatternView` and `IModelDocExtension.PublishSTEP242File`
   and `PublishTo3DPDF`, which write a file made from the document; and the `Delete`, `Purge` and `Set`
   members neither grammar reads, such as `IModelDoc2.DeleteConfiguration2` and
   `IModelDocExtension.PurgeDisplayState`.
4. **The same words on the interop's other interfaces.** Outside the 34 the grammar finds 186 members,
   54 names, on 153 interfaces, the event interfaces aside, that pass a read-only gate. On 117 of those
   interfaces the only one is `ReleaseSelectionAccess`, a feature data's release of the selection
   access `AccessSelections` takes, which is refused. The rest are `IComponent2.ReplaceReference` and
   `SaveVirtualComponent`; `IConfiguration.CopyDisplayStateFromConfiguration`, `RenameDisplayState`,
   `set_AddRebuildSaveMark` and `set_Lock` and `IConfigurationManager.AddRebuildSaveMark`;
   `IFeature.MoveFreezeBarTo` and `MoveFreezeBarTo2`; `ISketchManager.SketchReplace`, `SketchReplace2`,
   `RotateOrCopy3DAboutVector` and `RotateOrCopy3DAboutXYZ` and `ISketchRelation.ReplaceEntity`;
   `IDesignTable.SaveAsExcelFile`; `IBody2.ISave` (the COM twin of the refused `IBody2.Save`), `Copy`,
   `Copy2` and `ICopy`, `IBody`'s `ISave` and copies, and `ICurve`'s and `ISurface`'s copies; `IModeler`'s
   `ReplaceSurfaces`, `IReplaceSurfaces`, `IReplaceSurfaces2`, `CopyWizardHole` and `ICopyWizardHole`;
   `IPackAndGo`'s and `IAdvancedSaveAsOptions`' setters, which shape the refused `SavePackAndGo` and
   `SaveAs`; feature data setters (`set_Copy`, `set_LockAngle`, `set_LockRotation`, `set_MoveType`,
   `set_ReplaceFileLocations`, `set_CopyCustomProperties`, `AddSaveBodies`, `RemoveSaveBodies`),
   which take effect only through the refused `ModifyDefinition`; `IFreePointCurveFeatureData`'s and
   `ITablePatternFeatureData`'s `SavePointsToFile` and `IRoutingSettings.SaveRoutingSettingsToFile`;
   the camera's, the magnetic mate's and the sketch block instance's locks
   (`ICamera.set_LockCameraPosition`, `IMate2.set_LockMagneticMate`, `ISketchBlockInstance.set_LockAngle`);
   `IEquationMgr.set_AutomaticRebuild`; `IAdvancedSelectionCriteria.SaveCriteria`;
   `IBomTableSortData.set_SaveCurrentSortParameters`; and the user
   interface's `IFrame.RenameMenu`, `IFlyoutGroup.ReplaceCommandItem`, `IModelView.MoveMagnifyingGlass`,
   `IAnnotationView.MoveAnnotations`, `IMouse.Move` and `MoveXYZ`; and `IModelDoc.SaveBMP`, the old
   interface's capture call. Reading the whole interop would be a decision of its own: the generator
   names its rows interface by interface, and some of the bare names are words the product uses for
   something else - `File.Copy` is a step label of `remodel.open`. *The second review (R10.5) asks the
   owner*: whether the families are to be read over the whole interop, rather than the 34 interfaces
   the generated tables are written against; nothing was widened.
5. **`MoveToFolder` is allowed by the read-only guard itself.** *Added on the second review
   (R10.5).* Its one reason is `probe remodel`'s PROBE-5, which moves a feature of the throwaway part
   into a folder, but it is left allowed in `ReadOnlyGuard`, so every read-only gate lets it through,
   and so does `RemodelGuard`'s branch for a bare name, which asks the read-only guard. The probe's
   other writes stand differently: `ForceRebuild3` and `SaveAs3` stay refused by the read-only guard,
   and `RemodelProbeGuard` alone exempts them. The alternative is that treatment: deny `MoveToFolder`
   in the generator, add it to `RemodelProbeGuard`'s run-scoped member set (`RunScopedMemberSet`),
   and move it in `DocumentWriteFamilyTests` from `Allowed` to `Exceptions`; `RemodelGuardTests`'
   example of a bare writer the denylist misses
   (`Assert_BareWriterTheDenylistMisses_PassesWhichIsWhyWritesAreQualified`) would then need another
   member. `NewDocument` stands as `MoveToFolder` does: the probe creates its throwaway part with it
   under `RemodelProbeGuard`, which hands it to the read-only guard, and the read-only guard leaves it
   allowed (section 3 of `contracts/guard.md`), so every read-only gate lets it through too. Which way
   each goes is the owner's call; nothing was changed.
   *Settled 2026-10-19 by decision 144A (R11.2)*: the second way - both are refused by the read-only
   guard, and `RemodelProbeGuard`'s run-scoped members exempt the bare names its host gates.
6. **The re-modeler's pane seat calls SOLIDWORKS through no gate.** *Added on the second review's
   second pass (R10.5).* `extractor/SwReview.AddIn/Remodel/SwRemodelSeat.cs` calls the interop
   directly, on the application thread. `remodel.open_copy` (`ActivateOrOpen`) looks the copy up
   with `GetOpenDocumentByName` and, when SOLIDWORKS has it open, activates it with
   `ActivateDoc3(title, false, swDontRebuildActiveDoc)`; otherwise it opens it with `OpenDoc7`,
   `Silent` and `LoadModel` and never `ReadOnly` or `ViewOnly`, so the copy opens writable, for the
   engineer's Save As. Before each dump of `remodel.plan` and `remodel.start` (`ActivateOpenCopy`,
   004 T159) it activates the copy the same way and reads `ActiveDoc`'s `GetPathName`. It predates
   this decision: the seat came with feature 004 (`5d93f92`, 2026-09-16), and its activation before
   each dump and its frozen-manifest rows on 2026-09-27 (`0b04c8e`, `4c06b29`). It opens no write
   path: the copy's path derives from a run folder the host already holds. But the read-only guard
   never sees these calls - `ActivateDoc3` among them, which the guard has refused since feature
   011's T004 (`1a5a6a8`, 2026-09-23) and decision 136A's lifecycle family pins - and no gate log
   records them; the writable open, `ActivateOrOpen`, has no seat-level test (`SwRemodelSeatTests`
   covers `ActivateOpenCopy`); and on this path the constitution's "Documents are read, not
   written", whose "`ReadOnlyGuard` is the enforcement point", is not met. The owner's options: put
   the seat behind a gate whose guard is an allowlist shaped like `DrawingOpenGuard` -
   `ISldWorks.ActivateDoc3` and `ISldWorks.OpenDoc7` allowed by their qualified keys, every other
   qualified key refused, and every bare read handed to `ReadOnlyGuard` - with a seat-level test
   pinning `ActivateOrOpen`'s calls and its open options; or record the convention as accepted.
   Nothing was changed.
   *Settled 2026-10-19 by decision 144A (R11.1)*: the first option, with the seat scoped to the
   run's copy and its gate log in the run's `remodel.log`.

### R10.5 The second review: what it found and what changed (T154 to T162)

**Source.** An independent, adversarial review of the branch at `bf9da8c`, the same day, found no
seat breakage, no new write path and no test loosened. Its findings, and what each became:

- **A named literal exempted its spelling anywhere** (finding 4). With
  `_session.Gate.Call("close", () => 0)` added to `SwCaptureView.cs`, all fifteen read-audit tests
  passed: `close` was named for the clean-up label in `BridgeDispatcher.cs`, and the key was the
  literal alone. Both read audits now key each named literal by the literal and the file it stands
  in, as `DocumentWriteFamilyTests` keys its own (T154, `9724bd8`); with the same mutation the drawing
  audit fails on `"close" in SwCaptureView.cs`, and reverted it passes. The keying found a place the
  old key had covered unsaid: `ActivateDoc3` is a literal of `RemodelInteropSurface.cs`, the frozen
  manifest's row for the pane seat's direct call (feature 004 T181), as well as of `Program.cs`, the
  only file its reason named; it is named now with its own reason. A new fact checks that no two
  product files share a name, so a key by file name is one place: a second `Program.cs` fails it.
  *Replaced on the second pass (below)*: each file is named by its path under the extractor folder,
  and the fact is gone.
- **The dispatcher's own check was load-bearing for no test** (finding 5). `Run`'s default answered
  as an unknown command, the answer `Dispatch`'s check gives, so with the check removed all 9,706
  extractor tests passed. `Run`'s default now throws `InvalidOperationException`, since a name that
  reaches it is the dispatcher's mistake (T156, `7ee2fee`): with the check removed, 33 tests fail -
  the 29 cases of `ANameOutsideTheSet_IsRefusedAsUnknownBeforeAnythingRuns`, the null command,
  `Save3` and the two unknown-command sentences - each answered "InvalidOperationException: No handler
  for the bridge command ..." where it expects "Unknown command"; restored, they pass.
  `EveryAnsweredCommandReachesItsHandler` (T155) sees the other side: with the `tessellate` case
  dropped from `Run`, it fails. *Widened on the second pass (below)*: it reads the remodel family's
  own default too.
- **`UnknownCommand`'s summary** (finding 9) said only the remodel scope reaches the `remodel.*`
  family. The console host, whose `NoSecretPolicy` lets every name through, answers the family too,
  and the family refuses each command there: a change command first while Start is switched off, and
  every one for want of a seat. Corrected with T156.
- **Sentences the change left wrong** (findings 7 and 8; T157, `4448742`). `PROTOCOL.md` said "the
  five below" of six commands, and that the read-only guard refuses the `remodel.*` commands: no
  guard judges a command's name, and their writes go through feature 004's allowlist guard, the
  read-only guard refusing some of those writes (`Save3`, `ForceRebuild3`) and missing others.
  `AssertSaveAs`'s extension list, its summary and its refusal sentence said `SaveAs3` may write a
  capture image, and `CaptureService` called the capture the read-only guard's single exception;
  `SaveAs3` is refused outright, and the refusal now reads "A capture image may only be written as
  .png, .bmp or .jpg" (its member name stays `SaveAs3`, which `AssertSaveAs_ModelExtension_Throws`
  pins; no test pinned the sentence). And `SaveBMP`'s reason said it cannot write a document: it
  writes to whatever path it is handed, and a guard judges names, never paths. What keeps the path an
  image is the capture's own code: `CaptureService` names the PNG under the `captures` folder of the
  directory the host chose and checks it with `AssertSaveAs`, and `SwCaptureView` writes the bitmap
  beside it, at the same name with `.bmp`. The reason is corrected in the generator, so in 004's
  `guard-allowlist.md`, and in section 3 of `contracts/guard.md`, `DocumentWriteFamilyTests` and
  R10.3.
- **The records** (findings 3 and 6; T158, `939346d`). "Every interface the guard covers" said more
  than the sweep reads: the guard judges a name on any interface, and the test reflects the 34 the
  generated tables are written against (R10.2; item 4 above counts the rest). And R10.3 said 63
  members, 60 names, were callable before the decision: measured again, by reflecting the 34
  interfaces of 32.5.0.48 against `ca7a720`'s guard, it is 64 and 61 - the 62 members (59 names) the
  decision refuses and the two it leaves allowed, with `Rebuild` on two interfaces as well as `SaveAs`
  and `SaveAs2`.
- **`MoveToFolder`'s standing** (finding 2) and the sweep's scope are the owner's: items 4 and 5
  above.

**Renumbered, and main merged.** Decision 141A reached main first (PR #12) and took this feature's
R9, Phase 10D and T135 to T144. Decision 140A's records moved past them before main was merged in
(`da4b4dc`): this section was R9, Phase 10E was Phase 10D, and T145 to T153 were T135 to T143, the
numbers the commit messages before `da4b4dc` still carry. Main was merged (`d84a896`),
not this branch rebased, so every hash these records cite stays valid. In R8.5, 141A settled the
first item and decided the fourth, 140A answered the second and third, and the fifth and sixth are
unchanged.

**Measured after the merge**: `SwReview.Extractor.Tests` 9,733 (9,705 at `bf9da8c`; the rest are
this review's two and decision 141A's) and `SwReview.AddIn.Tests` 2,482, all green; the build at zero
warnings; the read audit reads 141A's new files (a `"SaveAs"` literal put in
`ConfirmedDrawingSession.cs` fails it, and reverted it passes); no broken link. SOLIDWORKS was not
started, and the interop was read as metadata only.

**The second pass** (2026-10-19, at `44db63e`). A second adversarial pass confirmed that all eight
fixes hold and that the mutations reproduce - 33 red without `Dispatch`'s check, the `close` literal
in `SwCaptureView.cs` caught, and `Run`'s throw caught by `Dispatch` on both hosts - with zero
warnings, 9,733 and 2,482. It found four nits and one question for the owner, which T159 to T162
answer:

- **A fact wider than its reason.** `NoTwoFilesOfTheProductSourceShareAName` failed for any two
  product files of one name, whether or not a key named either, and its advice, to key by more of
  the path, could not make it pass. The scan names each file by its path under the extractor folder
  now (`SwReview.Extractor/Capture/SwCaptureView.cs`), every key with it, and the fact is gone (T159,
  `381a900`). An unrelated second `Program.cs`, which failed the fact, fails nothing: the 630 audit,
  family and exemption tests pass. A `"close"` literal in a second `BridgeDispatcher.cs`, elsewhere,
  which the audit had exempted by its name and only the fact caught, fails the audit by its path.
- **A handler test blind to half its name.** `EveryAnsweredCommandReachesItsHandler` looked for
  `Run`'s mistake only: with `remodel.geometry`'s case gone from the remodel family's own switch, 55
  behaviour tests failed and it passed, the family answering "has no handler for it". It reads that
  answer too, with Start switched on so the six change commands reach the switch rather than being
  refused before it (T160, `19d8813`): with the geometry and describe cases dropped, it fails naming
  both, where it had passed (the suite failing 57 elsewhere).
- **Two sentences** (T161, `c38e493`). `PROTOCOL.md` said every `remodel.*` command writes, and on no
  document but the copy: `RemodelCommandTable` marks `probe_scope`, `snapshot` and `geometry` as
  writing nothing, and `probe_scope` and `open` read the engineer's source. And R10.1 still said
  `Run`'s unknown branch shares the dispatcher's refusal; it points to this section now.
- **The pane seat's direct calls**, which pass no gate, are R10.4 item 6, for the owner; the read
  audit's reason for `ActivateDoc3` in the frozen manifest points there (T162). Nothing in the seat
  was changed.

**Measured after the second pass**, on a build from scratch (`--no-incremental`: for the reviewer,
an incremental build after a revert had kept a mutant compiled): `SwReview.Extractor.Tests` 9,732,
one fact fewer, and `SwReview.AddIn.Tests` 2,482, all green; zero warnings; no broken link.

## R11. Decision 144A: the read-only guard's remaining concrete gaps closed (owner, 2026-10-19)

**Source.** Decision 140A's reviews left six findings beyond that decision for the owner (R10.4).
The owner's decision 144A of 2026-10-19 closes the four concrete ones, test first, with an
adversarial review: the re-modeler's pane seat calls SOLIDWORKS through a gate of its own (item 6,
R11.1); `MoveToFolder` and `NewDocument` move from the read-only guard's allowed names to the
probe's own guard (item 5, R11.2); and the lifecycle families on `IAssemblyDoc` (item 1, R11.3) and
the drawing grammar's gaps - the `I` twins it missed and the writers its `Is` reader prefix let in
(item 2, R11.4) - are refused. **Items 3 and 4 stay recorded**: the writers of other words on the
covered interfaces, and the families on the interop's other interfaces, are as R10.4 leaves them;
nothing was widened to read the whole interop. The tasks are T163 to T177 (Phase 10F), with T171
for the next sitting. SOLIDWORKS was not started: the C# tests run over fakes and the interop
stand-ins, and the interop (`SolidWorks.Interop.sldworks` 32.5.0.48) was read as metadata only.
Measured on the development machine: `SwReview.Extractor.Tests` 9,732 tests before and 9,913
after, `SwReview.AddIn.Tests` 2,608 before and 2,670 after, all green, the build at zero warnings
from scratch (`--no-incremental`).

### R11.1 The pane seat calls SOLIDWORKS through a gate of its own (T163, T164)

**Decision**: `extractor/SwReview.AddIn/Remodel/SwRemodelSeat.cs` makes every interop call through a
gate, the machinery every other path of the product uses (`SwGate`, an `ICallGuard`, an
`ISwGateObserver`). Each action builds its own (`SwRemodelSeat.Gate`): a breaker of its own, so one
press's failures count toward no later one, and `Guard/RemodelSeatGuard.cs`, an allowlist in
`DrawingOpenGuard`'s shape - `ISldWorks.ActivateDoc3` and `ISldWorks.OpenDoc7` allowed by their
qualified keys, matched ordinally; every other qualified key refused, naming it; every bare name
handed to `ReadOnlyGuard` unchanged. The seat names its two keys as its own literals, as
`BridgeDispatcher` spells `RemodelGuard`'s, and its reads by the bare names every read call site
gives them: `GetOpenDocumentByName`, `GetPathName`, `GetTitle`, `ActiveDoc` and `GetOpenDocSpec`. The
open request's five property sets - `CopyOpenSpecification.For`, unchanged and shared with the bridge
seat - are made inside the `GetOpenDocSpec` gate entry, and its load bits read back inside the open's:
they set and read a throwaway request, not a document, as the bridge makes them inside its own open
and as the frozen manifest records them, and gated on their own they could not pass (the read-only
guard refuses the bare `set_ReadOnly`, the drawing families' writer of that name, and the seat's guard
any qualified key but its two). Of the two keys only `ActivateDoc3` overrides a read-only denial;
`OpenDoc7` is an exclusion of `contracts/guard.md` section 3. The seat is the guard's one
construction site. `contracts/guard.md` section 8 and 004's `contracts/guard-allowlist.md` ("The
re-modeler's pane seat") record the entry.

**The gate log.** Each action writes one line (and, since the review, a begin line before it and its
outcome in it, R11.7) to the run folder's `remodel.log` (`Remodel/RemodelSeatGateLog.cs`, through
`RemodelRunLog`), on the application thread, after its calls, whatever they did: `seat=open_copy`
for `remodel.open_copy` and `seat=activate_before_dump` for
the activation before each dump, then `status=ok` or `status=error`, `gated=` the distinct members the
gate was asked about in the order it first saw them (the set the tool service's request lines hold),
`refused=` when the guard refused any, and `error=` the exception's type alone - a message can quote
a path, and the run folder's log names no document. A log that cannot be written fails nothing. The
report reads only `remodel.log`'s `target=` field (`read_log_targets`), which a seat line never
carries, so its count of writes is unchanged. 004's `contracts/run-artifacts.md` says so.

**The copy's path, decided: the seat is scoped to the run's copy.** The constitution's bounded
exception lets the re-modeler "create and modify exactly one document, a copy it created during this
session, and no other", has "any write to any document that is not this run's copy" refused "by the
guard, not by convention", and puts its writes behind a document-scoped guard that allowlists the
members and re-verifies the target document before each write. Every exception the product builds
is scoped so: `RemodelGuard`'s allowlist is the first layer and `RemodelScope.VerifyTarget` the
second, re-checking the copy's path, session tag, COM identity and descent from the run folder
before every write; the bridge seat opens and closes only a path inside a run folder's `copy/`
(`RemodelCopy.RunDirectoryOf`); `RemodelProbeGuard`'s run-scoped members serve only the parts `probe
remodel` creates, in a gate that refuses to run while any document is open, its save behind
`RemodelProbe.AssertPartSavePath`; and the confirmed drawing's scope opens only a `.SLDDRW` and closes
only what it opened, by COM identity. So the seat's two keys are scoped to the run's copy too. A
guard sees member names, never documents, so the scope is the seat's own second layer:

1. before any call, a path that is not rooted, or not a part (`.SLDPRT`) inside a run folder's
   `copy/` (`RunDirectoryOf`'s rule), is refused as an argument error - the pipeline resolves the
   copy from a run this host made, so reaching the refusal is the caller's mistake, as the bridge
   seat's is - with no hop onto the application thread and no log line;
2. a document the lookup answers is asked its own path, and is asked its title and activated only if
   that path is the copy's (`OpenDrawingDiscovery.SamePath`, the product's one rule for the same
   document, which the pipeline already applies to the active document after each activation);
   otherwise `remodel.open_copy` refuses and the activation before a dump answers null, as for a
   copy SOLIDWORKS does not have open;
3. a document the open answers - one SOLIDWORKS already had open under the copy's title, say - is
   taken as the copy only if its own path is the copy's; otherwise the open is refused and that
   document, perhaps the engineer's, is left as it is: not activated, not closed, not named.

Not taken: the session tag, which `VerifyTarget` checks before each write, and the pane seat writes
nothing; and a COM identity check, since the seat holds no handle from before to compare. The title
`ActivateDoc3` is handed is asked of a document already shown to be the copy.

*Tightened on the decision's review, the same day (R11.7)*: the path must be a full path, a drive's
or a share's, with no `..`, its run folder not a root, and the seat hands SOLIDWORKS the canonical
form it checked (`Remodel/RemodelSeatCopyPath.cs`); `remodel.open_copy` asks the document the
activation answers for its path too, since `ActivateDoc3` activates by title; and each action
writes a begin line before its first call and names its outcome on its closing line.

**What the seat's gate does not stop.** The read-only guard leaves the bare names `OpenDoc6`,
`OpenDoc7` and `CloseDoc` allowed (section 3's exclusions), so the seat's guard, as `DrawingOpenGuard`
does, lets those bare spellings through: a guard judges the name a call site gives it. What keeps the
seat to its two keys is that its call sites name them qualified, which `SwRemodelSeatTests` pins call
by call. R11.8 records `OpenDoc7`'s standing, and a closed allowlist, for the owner.

**Tests.** `SwRemodelSeatTests` (add-in) places every interop call of both actions under the gate
entry it is made under - a journal that notes, at each entry, how many calls each stand-in had
recorded - so a call made outside the gate, or one more than listed, fails there; it pins
`ActivateOrOpen`'s two ways, the activation by title without a rebuild and the writable open through
the one request (`Silent | LoadModel = 17`, never `ReadOnly` or `ViewOnly`, asserted as the values set
and as the integer they compose); an open that answers no document, refused naming the load errors
read inside the open's entry; a document that is not at the copy's path, from the lookup or the open,
neither activated nor kept, and not named; eight paths that are not a run's copy (fourteen since
the review, R11.7) refused by both actions before any call; an activation SOLIDWORKS refuses; one
hop onto the application thread, the log line inside it; the seat's own gate refusing any call off
its allowlist; and the log line, which a write that fails cannot turn into a failure.
`RemodelSeatGuardTests` (extractor) pins the allowlist, the refusals, the bare reads, the one
overriding key, that it widens no other guard, and its one construction site.
`RemodelPlanEndToEndTests` reads the plan's activation line from a real
`remodel.log`, and a new case opens the copy after a plan through the production wiring - host,
pipeline, seat and log - and reads its line. The family sweeps read the new guard:
`GuardSweep.ProductGates` gains it, and `GuardSweepTests` holds that list to every `ICallGuard` the
product defines (none may be declared outside the extractor's `Guard` folder); decision 21A's,
decision 17A's and the confirmed open's lists of the product's gates read it; and
`DocumentLifecycleFamilyTests` gains the named exceptions `DocumentWriteFamilyTests` has, its first
`RemodelSeatGuard ISldWorks.ActivateDoc3`, with the same staleness check (the two classes share both
checks through `GuardSweep` now). The read audit judged the new guard's two keys whole, as it judges
the other allowlist guards' (`DrawingFamilyReadAuditTests.Judged`) - in every file, which the review
found too wide: it judges them whole in the seat's own file alone now (R11.7).

**Edited deliberately**: `SwRemodelSeatTests.TheOpenCopyIsActivatedByItsTitleWithNoRebuildAndTheActivePathIsAnswered`
(the copy is asked its path before its title); `DocumentLifecycleFamilyTests.EveryGateTheProductBuildsRefusesThem`,
now `...LetsThroughOnlyTheNamedExceptions` (the seat's `ActivateDoc3` its one exception, with its
file and reason, and any other member a gate lets through failing it as before); `Judged` (a third
allowlist guard; undone on the review, R11.7); and three hand-written lists of the product's gates -
`GuardAnswers.EveryGateTheProductBuilds`, `DrawingOpenGuardTests.TheReadOnlyCheckIsABareReadEveryGuardAllows`
and `ImportRepairDenylistTests.EveryGateTheProductBuildsRefusesThem` - which read
`GuardSweep.ProductGates` now, each sweeping more guards than it did. No assertion was weakened.

**Evidence**: commit `8e54c67`. Twelve throwaway mutations, each red (R11.5).

### R11.2 `MoveToFolder` and `NewDocument` move to the probe's own guard (T165, T166)

**Decision**: `IFeatureManager.MoveToFolder` (PROBE-5's move into a folder) and
`ISldWorks.NewDocument` (the throwaway part's creation, and PROBE-8's and PROBE-21's parts) were left
allowed by the read-only guard itself, so every read-only gate let them through, though only `probe
remodel` calls them. They stand now as `ForceRebuild3` and `SaveAs3` do: `list-writer-members.ps1` no
longer excludes them, so the shared `ISldWorks` and `IFeatureManager` rows refuse them, and
`RemodelProbeGuard`'s run-scoped members exempt the bare names its host gates, for the one gate built
with that guard, which refuses to run while any document is open. The qualified spellings stay
refused by every gate. A search of the product for each name, as a literal, a qualified key, a
`nameof` and a call, finds only `probe remodel`'s own: `SwRemodelProbeHost.cs`'s gate keys and calls,
its interface's method of that name and PROBE-5's executor and question (`RemodelProbe.cs`,
`RemodelProbeExecutors.cs`), and the swconst member `swMoveLocation_e.swMoveToFolder`, another name.

`RemodelGuardTests`' example of a bare writer the denylist misses, the reason the re-modeler's writes
are interface-qualified, is `IModelDoc2.DeleteConfiguration2` now - R10.4 item 3's - and the same test
asserts `MoveToFolder` refused bare and qualified. `RemodelGuard`'s comment and 004's
`guard-allowlist.md` say so.

**The read audit**: `NewDocument` and `MoveToFolder` are literals of the probe host, so refusing them
made `DrawingFamilyReadAuditTests` find them. A literal of the probe host that `RemodelProbeGuard`
lets through is the probe's own call, judged by its own gate - the rule decision 21A's audit already
applies to the probe's creation calls - and
`TheProbesOwnCallsAreExactlyItsTwoWritersAndOnlyItsGuardLetsThemThrough` pins which: exactly these
two, each let through by its guard, so a later literal of the probe host the table refuses fails until
someone decides what it is.

**Evidence**: commit `26cd1b2`, tests first - nine red before the change: the two family sweeps (the
members callable, and every gate letting them through), `EveryExclusionHasOneOfTheContractsReasons`,
the new theory `TheProbesTwoWritersAreRefusedByEveryGateButTheProbesOwnBare` (both cases), the new
audit fact, and the bare-writer example. Edited deliberately: `DocumentWriteFamilyTests` (`MoveToFolder`
from `Allowed` to `Exceptions`), `DocumentLifecycleFamilyTests` (`NewDocument` from `Allowed` to
`Exceptions`), `EveryExclusionHasOneOfTheContractsReasons` and `TheSanctionedCallsStayAllowed` (both
names out, narrowed), and the bare-writer example. The table and `ReadOnlyGuard.Drawing.cs`
regenerated from one run, 735 new names; the creation table unchanged.

### R11.3 The lifecycle families on `IAssemblyDoc` (T167, T168)

**Decision**: decision 136A's grammar reads `IAssemblyDoc` as a fourth interface. On 32.5.0.48 it
finds fifteen members there, none a reader and none the product names or calls (searched as above):
`OpenCompFile` and `SelectiveOpen`, which open component documents; `ComponentReload`,
`ComponentReload2`, `IComponentReload2` and `IComponentReload3`; `InsertNewPart`, `InsertNewPart2`,
`InsertNewAssembly`, `InsertNewVirtualPart`, `InsertNewVirtualAssembly` and `InsertLoadReference`;
`ActivateGroundPlane`, `ExitIsolate` and `TemporaryFixGroupExit`. The `IAssemblyDoc` row names them;
each name is declared on `IAssemblyDoc` alone in the interop, so no other interface's member is
refused with it.

**Evidence**: commit `4846206`, test first: `DocumentLifecycleFamilyTests.Interfaces` gains
`IAssemblyDoc`, the floor pins the fifteen and no other, and the grammar theory reads them; two red
before the change, naming exactly the fifteen. The table regenerated, 750 new names; the creation
table unchanged. Edited deliberately: the class's `Interfaces`.

### R11.4 The drawing grammar's gaps (T169, T170)

**Decision**: section 2's grammar is fixed rather than names listed. It gave the COM twin's `I` to
four verbs (`ISet`, `IAdd`, `IInsert`, `ICreate`), so five twins of other verbs passed on the drawing
families: `IDrawingDoc.IEditSelectedGtol`, `IMakeCustomSymbol2`, `INewGtol` and `IReorderSheets`, and
`IView.ISelectEntity`. The twin's `I` may come before every verb now. And it read its reader prefixes
by their letters, so `Is` took in two writers, `IDrawingDoc.IsolateChangedDimensions` and
`IAssemblyDoc.Isolate`: a prefix is a whole word now - followed by the end of the name or by anything
but a lowercase letter, `get_` ending a word itself - and `Isolate`, the display writer beside `Hide`
and `Show`, is a verb. The reader rule is the one `guard-table-helpers.ps1` shares, so decision 21A's
creation grammar applies it first too; no name of its four interfaces starts with a reader prefix
that is not a word, and its table regenerates unchanged. `IAssemblyDoc` is no drawing family and no
grammar of the shared interfaces reads its display writers, so the rule cannot reach
`IAssemblyDoc.Isolate`: its row names it by hand, and a reflection test classifies it.

Measured on the 34 interfaces the generated tables are written against: the twins of other verbs
are exactly the five above, and the names a reader prefix starts by its letters only are exactly
the two; each of the seven is declared on one interface alone.

**Evidence**: commit `0dc09d5`, tests first: the test's own copy of the grammar reads the twins and
whole words, a theory pins section 2 case by case (the twins, `Isolate`, the readers, and names a
prefix starts by its letters only), and
`EveryNameTheReaderPrefixesTookOnlyByTheirLettersIsRefusedByEveryGate` reflects the 34 interfaces and
holds each such name to a refusal, bare and qualified, by every gate; two red before the change,
naming exactly the six drawing writers and the two `Is` names. The table regenerated: 652 grammar
matches on the 28 families and 757 new names; the creation table unchanged. Edited deliberately: the
test's reader prefixes and writer grammar.

### R11.5 The mutations

Each fix taken out once, by an exact replacement in one file, the suite built and the named tests
run, then the file restored byte for byte; the build at the end is from scratch.

| Id | Taken out | Red |
|---|---|---|
| M1 | the seat's gate built on the read-only guard, not RemodelSeatGuard | 21 cases of 18 tests: `ALogThatCannotBeWrittenFailsNothing`, `APlanRunsThroughTheSeatAdapterAndEndsItsSessionStartIsRefusedByTheSwitchAndDiscardDeletesTheCopy`, `APlanWhoseClosingLeavesSettingsChangedTellsThePageBeforeItIsAnswered` and 15 more |
| M2 | the title read made outside the gate | 5 cases of 4 tests: `APlanRunsThroughTheSeatAdapterAndEndsItsSessionStartIsRefusedByTheSwitchAndDiscardDeletesTheCopy`, `ActivateOpenCopy_EveryCallGoesThroughTheSeatsGateAndTheLogSaysSo`, `ActivateOrOpen_AnActivationThatFailsIsAnErrorNamingWhatSolidworksReported` and 1 more |
| M3 | open_copy: no check that the document found is the copy | 4 cases of 3 tests: `ActivateOrOpen_ALookupThatAnswersAnotherDocumentIsRefusedAndNothingIsActivatedOrOpened`, `ActivateOrOpen_AnActivationThatFailsIsAnErrorNamingWhatSolidworksReported`, `ActivateOrOpen_AnOpenCopyIsActivatedByItsTitleWithNoRebuildAndNothingIsOpened` |
| M4 | activation before a dump: no check that the document found is the copy | 4 cases of 4 tests: `APlanRunsThroughTheSeatAdapterAndEndsItsSessionStartIsRefusedByTheSwitchAndDiscardDeletesTheCopy`, `ActivateOpenCopy_ADocumentThatIsNotTheCopyIsNeitherActivatedNorAskedItsTitle`, `ActivateOpenCopy_EveryCallGoesThroughTheSeatsGateAndTheLogSaysSo` and 1 more |
| M5 | open_copy: no check that the document opened is the copy | 3 cases of 3 tests: `ActivateOrOpen_AClosedCopyIsOpenedAgainThroughTheOneOpenRequest`, `ActivateOrOpen_AnOpenThatAnswersAnotherDocumentIsRefusedAndThatDocumentIsLeftAlone`, `OpenCopyAfterAPlanOpensTheCopyAgainWritableThroughThePaneSeatsGate` |
| M6 | the copy's scope: no part-extension check | 4 cases of 1 test: `APathThatIsNotARunsCopyIsRefusedBeforeAnyCall` |
| M7 | the copy's scope: no run folder copy/ rule | 9 cases of 4 tests: `APathThatIsNotARunsCopyIsRefusedBeforeAnyCall`, `ActivateOpenCopy_EveryCallGoesThroughTheSeatsGateAndTheLogSaysSo`, `ActivateOrOpen_AClosedCopyIsOpenedAgainThroughTheOneOpenRequest` and 1 more |
| M8 | the copy's scope: no rooted-path check | 2 cases of 1 test: `APathThatIsNotARunsCopyIsRefusedBeforeAnyCall` |
| M9 | RemodelSeatGuard: another qualified key handed to the read-only guard | 8 cases of 2 tests: `AnyOtherQualifiedKeyIsRefusedNamingIt`, `TheSeatsGateAllowsItsTwoKeysAndTheReadsAndRefusesAnyOtherCall` (renamed by T176) |
| M10 | RemodelSeatGuard: keys matched in any case | 4 cases of 2 tests: `AnyOtherQualifiedKeyIsRefusedNamingIt`, `TheSeatsGateAllowsItsTwoKeysAndTheReadsAndRefusesAnyOtherCall` (renamed by T176) |
| M11 | the sweeps' list of the product's gates without RemodelSeatGuard (test side) | 2 cases of 2 tests: `EveryGateTheProductBuildsLetsThroughOnlyTheNamedExceptions`, `TheProductsGatesHoldOneOfEveryGuardTheProductDefines` |
| M12 | the gate-log line never written | 13 cases of 11 tests: `APlanRunsThroughTheSeatAdapterAndEndsItsSessionStartIsRefusedByTheSwitchAndDiscardDeletesTheCopy`, `ActivateOpenCopy_ADocumentThatIsNotTheCopyIsNeitherActivatedNorAskedItsTitle`, `ActivateOpenCopy_EveryCallGoesThroughTheSeatsGateAndTheLogSaysSo` and 8 more |
| M13 | NewDocument dropped from RemodelProbeGuard's run-scoped set | 5 cases of 5 tests: `EveryGateTheProductBuildsLetsThroughOnlyTheNamedExceptions`, `EveryProbeHostCallTheReadOnlyGuardRefusesPassesTheProbesGuard`, `NoLiteralOfTheProductSourceIsRefusedByTheTableExceptTheNamedOnes` and 2 more |
| M14 | MoveToFolder dropped from RemodelProbeGuard's run-scoped set | 5 cases of 5 tests: `EveryGateTheProductBuildsLetsThroughOnlyTheNamedExceptions`, `EveryProbeHostCallTheReadOnlyGuardRefusesPassesTheProbesGuard`, `NoLiteralOfTheProductSourceIsRefusedByTheTableExceptTheNamedOnes` and 2 more |
| M15 | the generated denial of NewDocument removed from ReadOnlyGuard.Drawing.cs | 9 cases of 9 tests: `EveryFamilyMemberIsAReader_ANamedExclusion_OrRefusedBareAndQualified`, `EveryGateTheProductBuildsLetsThroughOnlyTheNamedExceptions`, `EveryMemberOfTheTableIsRefused` and 6 more |
| M16 | the generated denial of MoveToFolder removed from ReadOnlyGuard.Drawing.cs | 10 cases of 10 tests: `Assert_BareWriterTheDenylistMisses_PassesWhichIsWhyWritesAreQualified`, `EveryFamilyMemberIsAReader_ANamedExclusion_OrRefusedBareAndQualified`, `EveryGateTheProductBuildsLetsThroughOnlyTheNamedExceptions` and 7 more |
| M17 | the generated denial of IAssemblyDoc's OpenCompFile removed | 8 cases of 8 tests: `EveryFamilyMemberIsAReader_ANamedExclusion_OrRefusedBareAndQualified`, `EveryGateTheProductBuildsLetsThroughOnlyTheNamedExceptions`, `EveryMemberOfTheTableIsRefused` and 5 more |
| M18 | the generated denial of IAssemblyDoc's ExitIsolate removed | 8 cases of 8 tests: `EveryFamilyMemberIsAReader_ANamedExclusion_OrRefusedBareAndQualified`, `EveryGateTheProductBuildsLetsThroughOnlyTheNamedExceptions`, `EveryMemberOfTheTableIsRefused` and 5 more |
| M19 | the generated denial of the twin IDrawingDoc.INewGtol removed | 6 cases of 6 tests: `EveryMemberOfTheTableIsRefused`, `EveryMemberOfTheTableIsRefusedQualifiedWithItsInterface`, `EveryMemberOfTheTableIsRefusedWhateverItsCase` and 3 more |
| M20 | the generated denial of IDrawingDoc.IsolateChangedDimensions removed | 7 cases of 7 tests: `EveryMemberOfTheTableIsRefused`, `EveryMemberOfTheTableIsRefusedQualifiedWithItsInterface`, `EveryMemberOfTheTableIsRefusedWhateverItsCase` and 4 more |
| M21 | the generated denial of IAssemblyDoc.Isolate removed | 7 cases of 7 tests: `EveryMemberOfTheTableIsRefused`, `EveryMemberOfTheTableIsRefusedQualifiedWithItsInterface`, `EveryMemberOfTheTableIsRefusedWhateverItsCase` and 4 more |
| M22 | the test's reader rule read by letters again (test side) | 6 cases of 3 tests: `EveryFamilyRowNamesOnlyGrammarMatchesOfItsInterface`, `EveryNameTheReaderPrefixesTookOnlyByTheirLettersIsRefusedByEveryGate`, `TheGrammarReadsEveryVerbsTwinAndTheReaderPrefixesAsWholeWords` |
| M23 | the read audit without the seat's per-file key rule | 1 case of 1 test: `NoLiteralOfTheProductSourceIsRefusedByTheTableExceptTheNamedOnes` |
| M24 | the seat's ActivateDoc3 key carried to another product file as a literal | 2 cases of 2 tests: `NoLiteralOfTheProductSourceIsRefusedByTheTableExceptTheNamedOnes`, `TheSeatsOwnKeysAreLiteralsOfItsOwnFileAlone` |
| M25 | the seat's gate built by another add-in file | 1 case of 1 test: `OnlyThePaneSeatNamesTheGuardOrItsGate` |
| M26 | a guard of the add-in's own | 2 cases of 2 tests: `TheAddInDefinesNoGuardOfItsOwn`, `TheProductsGatesHoldOneOfEveryGuardTheProductDefines` |
| M27 | the copy path: no full-path check | 8 cases of 1 test: `APathThatIsNotARunsCopyIsRefusedBeforeAnyCall` |
| M28 | the copy path: no '..' check | 2 cases of 1 test: `APathThatIsNotARunsCopyIsRefusedBeforeAnyCall` |
| M29 | the copy path: no check that the run folder is not a drive's or a share's root | 4 cases of 1 test: `APathThatIsNotARunsCopyIsRefusedBeforeAnyCall` |
| M30 | open_copy hands SOLIDWORKS the path as given, not its checked form | 1 case of 1 test: `APathIsHandedToSolidworksInTheFormItWasCheckedIn` |
| M31 | open_copy: no check that the document activated is the copy | 2 cases of 2 tests: `ActivateOrOpen_AnActivationThatAnswersAnotherDocumentIsRefused`, `ActivateOrOpen_AnOpenCopyIsActivatedByItsTitleWithNoRebuildAndNothingIsOpened` |
| M32 | no begin line | 19 cases of 14 tests: `ACallThatThrowsReachesTheCallerUnchangedAndTheLogNamesItsType`, `APlanRunsThroughTheSeatAdapterAndEndsItsSessionStartIsRefusedByTheSwitchAndDiscardDeletesTheCopy`, `ActivateOpenCopy_ADocumentThatIsNotTheCopyIsNeitherActivatedNorAskedItsTitle` and 11 more |
| M33 | no outcome on the closing line | 11 cases of 8 tests: `APlanRunsThroughTheSeatAdapterAndEndsItsSessionStartIsRefusedByTheSwitchAndDiscardDeletesTheCopy`, `ActivateOpenCopy_ADocumentThatIsNotTheCopyIsNeitherActivatedNorAskedItsTitle`, `ActivateOpenCopy_EachWayItEndsIsTheLinesOutcome` and 5 more |

### R11.6 The next sitting (T171)

The seat runs only on the pilot workstation, so T171 runs the remodel flow once there, on the
throwaway box of the test plan's step 5.3 (item B): Remodel a copy, Open copy, and Start, which this
build refuses by its switch before the seat is asked. The run's `remodel.log` must hold exactly four
seat lines - the begin and outcome lines of the plan's activation and of the open - with nothing
refused (`contracts/guard.md` section 8). The test plan, its results sheet and the handover name it;
its five minutes join step 5's estimate, which `test_workstation_test_plan.py` pins (edited
deliberately, with the button label **Open copy** among the product words the plan quotes).

### R11.7 The adversarial review: what it found and what changed (T173 to T177)

**Source.** An independent, adversarial review of the four commits at `0dc09d5`, the same day, read
only - no build, no edit - found no blocker: no new write path, no seat breakage at the pilot (the
seat's path checks are the comparison the pipeline already makes before every dump), no product read
refused, the generated files reproducing byte for byte from both generators and the two copies of
the grammar character for character the same, and no test loosened but the one its second finding
names. Its findings, and what each became:

- **The records were not yet in** (finding 1): R11, `contracts/guard.md` sections 1, 2, 3, 5 and 8,
  004's entry for the seat's guard and Phase 10F were in flight; they land with T172 and T177.
- **The seat's key could be carried to another gate with every test green** (finding 2, should-fix).
  `Judged` had come to exempt the seat guard's two keys in every product file, where a qualified
  `ISldWorks.ActivateDoc3` had failed the read audit anywhere before - a loosening beyond its reason
  - and the seat's gate factory, `SwRemodelSeat.Gate`, was reachable from any add-in file, which the
  construction test did not read. `Judged` is back to the two guards it named before the decision;
  the audit exempts the seat's keys in the seat's own file alone (`IsTheSeatsOwnKey`), and
  `TheSeatsOwnKeysAreLiteralsOfItsOwnFileAlone` pins them there; `OnlyThePaneSeatNamesTheGuardOrItsGate`
  replaces the construction test, reading any naming of the guard, `new()` included, and any use of
  the gate factory outside the seat (T173).
- **The guard does not allow only the seat's own calls** (finding 3, the owner's): it hands every bare
  name to the read-only guard, as the decision's chosen option and `DrawingOpenGuard` do, so bare
  `CloseDoc`, `OpenDoc6` and `OpenDoc7` pass it. The test that said it "refuses any other call" is
  renamed `TheSeatsGateAllowsItsTwoKeysAndHandsEveryBareNameToTheReadOnlyGuard` and pins those three
  passing (T176); the closed allowlist the review prefers is R11.8's question.
- **The gate log was hard to audit** (finding 4): an activation that activated nothing logged
  `status=ok` as one that did, and an action SOLIDWORKS never returned from left no line. Each action
  now writes a begin line before its first call, as every bridge request does since U27, and its
  closing line names the outcome - `activated`, `opened`, `not_open`, `not_the_copy` or
  `not_activated` (T174, T175).
- **`open_copy` never checked what was activated** (finding 5): `ActivateDoc3` activates by title, so
  the document it answers is asked its path too, and one that is not the copy is refused unnamed
  (T174, T175). Its question - that `open_copy` refuses an activation answered with error bits, a
  rebuild warning among them, where the dump treats the same warning as success - is R11.8's.
- **The copy path was weaker than the records said** (finding 6): `Path.IsPathRooted` took a path
  relative to a drive's folder or to the current drive's root, a `copy/` folder at a drive's root
  passed with the drive for its run folder, and SOLIDWORKS was handed the path as given while the
  checks read its trimmed, canonical form. The rule is its own file now,
  `Remodel/RemodelSeatCopyPath.cs` (its `Split` is an interop member name, which the manifest audit
  would read in the seat's file): a full path, a drive's or a share's, never a device path, with no
  `..`, the run folder not a root; and the seat uses the canonical form it checked for every call and
  comparison (T174, T175). It still cannot tell which run's copy it is handed, which the pipeline
  resolves; one rule for both seats is R11.8's.
- **Repetition** (finding 7): `RemodelSeatGuardTests` uses `GuardSweep.Refuses` (T176); a shared
  allowlist guard is R11.8's.
- **`GuardSweepTests`' blind spots** (finding 8): it read the extractor's assembly alone, and the read
  audit's files, which skip every folder named `Guard`. It reads the console's assembly as well, and
  every source file of the three projects outside the extractor's `Guard` folder for a class, a
  struct or a record that implements the interface, generic or not; and the add-in suite's
  `TheAddInDefinesNoGuardOfItsOwn` reads the assembly this suite cannot load (T173).
- **Comments now untrue** (finding 9): `ReadOnlyGuard.Assert`'s and `ReadOnlyGuardTests`' "two
  allowlist guards", "three interfaces" twice, the seat's "one rule in the product" for `SamePath`
  (`RemodelHost` keeps its own), `ICallGuard`'s "exactly one alternative" and `SwGate`'s "null
  everywhere but the suppress-test", stale before the decision and further off with it; and the
  probe's-own-calls test, whose name said "only its guard" and whose body did not check it, does now
  (T176).
- **Missing seat tests** (finding 10): a COM failure reaching the caller unchanged, the same instance,
  with its type in the log; a request SOLIDWORKS will not describe; and the paths finding 6 names
  (T174).
- **Questions for the owner** (findings 11 and 12): whether the constitution's 2(b) - the target's
  path, session tag and COM identity re-verified before each write - applies to an activation and a
  writable open, and `OpenDoc7`'s standing; R11.8.

**Evidence**: commit `a096bae`, with M23 to M33 of R11.5. The tests were written before the code
they pin, and each change was then taken out once: every mutation is red.

### R11.8 Found on the way, and left for the owner

Nothing here was changed; each is the owner's call.

1. **`OpenDoc7` stands as `NewDocument` did** (the review's finding 12 too). The read-only guard
   leaves the bare name allowed (section 3), for `remodel.open`, which gates it bare under
   `RemodelGuard` - whose bare branch asks the read-only guard - and for `probe remodel`'s reopen of its
   throwaway part; so every read-only gate lets a bare `OpenDoc7`, a writable open, through, though no
   read-only path calls it. The same treatment as `NewDocument`'s would deny it in the generator,
   qualify the bridge's call as `ISldWorks.OpenDoc7` on `RemodelGuard`'s stage-1 allowlist - the
   twenty keys 004's contract fixes, and the five that override a read-only denial would become six -
   and add the bare name to `RemodelProbeGuard`'s run-scoped members.
2. **A closed allowlist for the seat** (the review's finding 3). The register reads "a gate whose
   guard allows only the seat's own calls"; the option it chose (R10.4 item 6) hands every bare name
   to the read-only guard, as `DrawingOpenGuard` does, so the seat's guard lets through bare
   `CloseDoc`, `OpenDoc6`, `OpenDoc7` and any writer the denylist misses. The seat's surface is closed
   - its two keys and five bare reads, pinned call by call - so an allowlist of those seven names
   would be strictly narrower at no cost. The guard keeps the chosen shape until the owner says.
3. **Does the constitution's 2(b) reach the seat?** (the review's finding 11). 2(b) has the target
   document's path, session tag and COM identity re-verified before each write. The seat activates a
   document and opens one writable, and writes nothing to either; it checks the path, and after the
   session ends the copy carries no tag (`RemodelCopy.Untag`), so 2(b) as written could not be met
   there. R11.1 treats an activation and a writable open as no writes; if they are writes, the seat
   falls short of 2(b).
4. **An activation answered with a rebuild warning** (the review's finding 5). `remodel.open_copy`
   refuses an activation `ActivateDoc3` answers with any error bit, `swDocNeedsRebuildWarning` among
   them, though it activated the copy; the activation before a dump takes the same warning as success
   (004 T159). The seat-level tests pin each existing choice.
5. **One rule for the copy's path, and its run** (the review's finding 6). The bridge seat checks
   `RunDirectoryOf` only, the pane seat its stricter rule; neither ties the run folder to the host's
   run root, as `RemodelHost.IsRemodelCopy` does, so neither can tell this run's copy from another's -
   the callers resolve that. One `RemodelCopy` rule that returns the canonical path, for both seats,
   would be DRY.
6. **The allowlist guards, written three times** (the review's finding 7). `DrawingOpenGuard`,
   `RemodelSeatGuard` and, with a fourth answer, `RemodelGuard` write the same three answers, and the
   read audit's `Judged` and the creation tests' `AllowlistsByName` name the guards by type. A shared
   base, which the tests could query, would hold the rule once; and `Judged` could key each guard's
   keys by its builder's file, as the seat's are now, which would narrow the audit for `RemodelGuard`'s
   and `DrawingOpenGuard`'s keys too.
7. **The lifecycle grammar over the 34 interfaces.** Measured on 32.5.0.48, the grammar finds on the
   30 interfaces it does not read only members already refused - `IPartDoc`'s `CreateNewBody` twins by
   decision 21A, the drawing families' by their rows or feature 006's table, and
   `IDrawingDoc.INewGtol` by R11.4 - so `DocumentLifecycleFamilyTests.Interfaces` could read all 34, as
   `DocumentWriteFamilyTests` does, at no cost, and would catch a later interop's member there. The
   decision names `IAssemblyDoc`, so it reads four.
8. **`RemodelGuardTests`' example is R10.4 item 3's.** Should the owner refuse the writers of other
   words, `IModelDoc2.DeleteConfiguration2` among them, the example needs another member again.
