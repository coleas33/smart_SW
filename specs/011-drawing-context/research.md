# Research: Drawing Context, Read Only

**Feature**: `011-drawing-context` | **Date**: 2026-09-23 | **Plan**: [plan.md](plan.md)

Phase 0 output from: the owner's direction of 2026-09-22 and the roadmap written from it
(`docs/roadmap-2026-09-22.md`); the ADR-001 amendment of the same day
(`sw-review-architecture-proposal.md`); a reading pass on 2026-09-23 at tip `d47a91f` over every
module the plan names - the extractor's drawing phase (`DrawingDumper`, `DrawingTraversal`,
`SwDrawingReader`), the attach (`SwSession`), the phase orchestration (`PackageWriter`), the
drawing-rooted traversal (`ComponentTreeDumper`), the read-only guard, the IR's drawing models in
both languages, feature 006's four drawing checks and its traversal, feature 010's tolerance
resolver, and the model-facing drawing tools; and a reflection pass on the same day over the
SOLIDWORKS 2024 SP5 interop assemblies installed on the development machine
(`SolidWorks.Interop.sldworks` 32.5.0.48 and `swconst`), read as metadata only - SOLIDWORKS was not
started, and has no licence on this machine. Where this document says VERIFIED, the file was
opened on 2026-09-23 or the interop member was reflected; VERIFIED never means a call behaves on a
seat - that is what section R4's probes are for. Line numbers are as of `d47a91f` and will drift;
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
refusal (`:113`) returns a sentence for every drawing. That refusal (commit `7e700e4`, 2026-09-18)
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
annotation, each entity mapped to the model through `IView.GetCorrespondingEntity`, a face kept, an
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
  `probe standards` (`Program.cs:1792`); before `7e700e4` the same path failed on the missing
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
  `ScaleDecimal`, `GetOrientationName`, `GetCorrespondingEntity`, `GetDisplayDimensions`,
  `GetAnnotations`, `GetTableAnnotations`; `IDisplayDimension.GetText(Int32)`,
  `GetPrimaryPrecision2`, `GetPrimaryTolPrecision2`, `GetUseDocPrecision`, `GetUnits`,
  `GetUseDocUnits`, `IsReferenceDim`, `IsHoleCallout`, `GetHoleCalloutVariables`;
  `IDimension.Tolerance`, `DrivenState`, `FullName`; `IAnnotation.GetAttachedEntities3`;
  `IEdge.GetTwoAdjacentFaces2`; `ISFSymbol.GetSymbol`, `GetTextCount`, `GetTextAtIndex`;
  `ITableAnnotation.Type`, `Title`, `RowCount`, `ColumnCount`, `Text`;
  `IBomTableAnnotation.GetModelPathNames`; `IModelDocExtension.GetUserPreferenceInteger` and
  `GetUserPreferenceString`; and the enum values quoted in R2.7, R2.9 and R2.12.
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
| D6 | `GetAttachedEntities3` on a diameter dimension, a hole callout and a GTol, then `IView.GetCorrespondingEntity` and the part's `GetPersistReference3`: equal to the face phase's reference for that face, for a part drawing and for an assembly drawing | R2.8, SC-010 |
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
