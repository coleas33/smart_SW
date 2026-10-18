# D0: the drawing-creation inventory

Status: first phase, 2026-10-18, on `main` after `3b4825d`. This is the inventory the
[future capabilities roadmap](future-capabilities-roadmap-2026-10-14.md) asks for before any
drawing-creation feature (reserved number 012) is specified. It changes no code, no capability
gate and no constitution rule.

## Inputs and the owner's decisions

| Question | Answer (2026-10-18) |
|---|---|
| Where is the owner's drawing-generation base repository? | It exists, but not on this machine. This phase proceeds without it; section 6 lists what its evaluation records when it is provided. |
| Which drawing family comes first? | Decided after this inventory, by section 8's criteria. |
| Where do private details go? | Split: this public document holds structure only (operations, APIs, gaps). Template and sheet-format identities, title and revision rules, hard-coded paths, company conventions and real drawings stay in a private file outside the repository. |

Public examples in this document are fictional.

## 1. What the repository reads from drawings today

Every drawing seat probe (D1 to D14, 011 T062 to T068 and T077) is still open, and both drawing
switches ship off: `DRAWING_BINDING_VALIDATED = False`
(`reviewer/src/swreview/drawings/binding.py:59`) and `DrawingOpenScope.SeatValidated => false`
(`extractor/SwReview.Extractor/Sw/DrawingOpenScope.cs:130`). Drawings are read only when already
open in SOLIDWORKS, at most 10 (`Dump/OpenDrawingDiscovery.cs:129`); a same-name `.SLDDRW` beside a
model is recorded as a candidate and not opened. Native evidence lives in
`EvidencePackage.drawing_records[]` (`reviewer/src/swreview/ir/models.py:1851-1860`). A view is
usable only when the drawing is not in detailing mode, its model is loaded, it is not out of date
and it shows a configuration the review read; an unread flag counts as a failure
(`drawings/evidence.py:85-158`).

| Item | Read? | Where | Trust today |
|---|---|---|---|
| Sheets | Yes: name, index, active flag, persistent reference | `Dump/DrawingDumper.cs:704-798`; `models.py:1374-1446` | Views on inactive sheets unconfirmed (D1, D3). |
| Views | Yes: name, type, referenced document, persistent reference | `DrawingDumper.cs:935-985`; `models.py:1317-1371` | Not read: position or outline on the sheet, base view, section line, detail circle, display mode, flat-pattern flag. |
| View configuration, out-of-date and loaded states | Yes | `DrawingDumper.cs:992-1011` | Feed the usability rule; D12 not run. |
| View scale and orientation | Yes | `DrawingDumper.cs:1005-1010`; `models.py:1352-1355` | No check or brief uses them. |
| Sheet scale and projection | Yes (sheet properties items 2 to 4) | `DrawingDumper.cs:446-450, 900-932` | Paper size and sheet width and height not recorded; D11 not run. Projection compared with the profile (`checks/drawing_context.py:654-667`). |
| Units and default precisions | Yes | `DrawingDumper.cs:422-431, 606-631`; `models.py:1475-1491` | Which default governs a "use document precision" dimension unconfirmed (D4); only mm and in bind. |
| Drafting standard, detailing mode | Yes | `DrawingDumper.cs:433-434`; `SwDrawingReader.cs:240` | Standard compared with the profile by name. |
| Dimensions | Yes: value, type, override, text parts, precision, tolerance and fits, reference and driven flags, attached faces | `DrawingDumper.cs:1175-1480`; `models.py:1204-1314` | Not usable numerically while binding is off (`binding.py:59, 213-214`); rendered text composed, not read (D7); units and precision need D4/D5, binding D6/D8. |
| Hole callouts | Partly: the callout variables, verbatim | `SwDrawingReader.cs:286-300` | Not parsed into a hole specification. |
| GTol and datums | Frames, datum tags and their faces; model-side DimXpert/MBD annotations | `DrawingDumper.cs:1675-1758`; `models.py:915-943, 1647` | Datums exist only as labels on existing drawings and models: **no engineer-confirmed datum concept exists**. |
| Surface finish | Yes, verbatim | `DrawingDumper.cs:1766-1789` | Only counted in the brief. |
| Notes | Yes, per view, the sheet-format view included | `DrawingDumper.cs:1792-1820` | Whether property-linked notes return evaluated text is unconfirmed. |
| Tables (general, hole chart, BOM, title block, general tolerance) | Yes: every cell | `DrawingDumper.cs:1828-1930`; `models.py:1027-1074` | Stored, not interpreted: no hole-chart or general-tolerance parser. |
| BOM | Rows mapped to package documents | `SwDrawingReader.cs:415-431` | Item and part numbers discarded; no balloon model. |
| Revision tables | Yes | `DrawingDumper.cs:2035-2120` | Compared with the revision property (006); not in the brief. |
| Title block and properties | Document and configuration custom properties | `Dump/PropertyDumper.cs:101, 126` | No field-level title-block model. |
| Sheet format and template | Format name and `.slddrt` path | `DrawingDumper.cs:756-759, 902-904` | **The drawing template is not read** (a finished drawing does not record it: `checks/standards/profile.py:287-289`); no version or hash. |
| Model-side context | Hole Wizard data, model dimensions with tolerances, faces with references and boxes (only those requested by default: `Dump/FaceDumper.cs:6-10`), cut-list items | `models.py:578, 651, 738-751, 1526, 1573` | **No flat-pattern or bend data in the IR.** |

## 2. What the drawing brief supplies

`build_brief` (`drawings/brief.py:498-549`; `BRIEF_VERSION = 1`, `BRIEF_MAX_BYTES = 6_000` at
`:75-79`), under `specs/011-drawing-context/contracts/brief.md` as 013 amended it. Its version's
docstring already reserves "feature 012 extends the brief additively under a new version".

In order: `brief_version`; `document` (id, file name, kind, configurations used, description,
material, mass, instance count); `assembly` (joints from the 010 joint map, contact count,
interference ids); `interfaces` (one per joint-derived tolerance subject: the resolved tolerance
with its cited source or what was searched, the bound drawing record or why not, and the position
callout `check_nominal_alignment` computes, which names **no datum reference frame**); `drawing`
(attached, candidate, absent or bought; per drawing the sheet and view counts, usable views,
counts of dimensions, toleranced dimensions, callouts, GTols and finishes, datum labels, notes and
tables); `answers` (the engineer's answers touching the document); `conformance` (setting names
that differ from the profile, never values); `omitted` (what was cut).

**Budget:** per-list caps (joints 20, interfaces 20, notes 10 and tables 5 per drawing, rows 10 per
table, candidates 10, answers 10), then trimming one item at a time from the longest list until the
compact JSON fits 6,000 bytes, every cut counted (`brief.py:84-93, 448-492`). The document section,
datum lists and table cells are never cut; table cells are not truncated, so long cells spend the
budget.

**Never in it:** persistent references, profile values, dimension values, units, sheet format,
scale, projection, view orientation or type, revision tables, the drawing's properties, and any
feature not part of a joint (outer profile, slots, thickness).

**Consumers:** the model, through `get_drawing_brief(document_id)` (`tools/drawings.py:213-234`),
offered only when the package carries drawing evidence; and `swreview drawing brief`
(`cli.py:1565-1604`).

## 3. What drawing creation would lack, by the D1 plan's field groups

| D1 group | Exists to reuse | Partial | Absent |
|---|---|---|---|
| Evidence binding | Package ids and persistent references on sheets, views, dimensions, annotations, notes, tables; `AttachedFace`; manifest size and write time; `reuse_key`; feature 016's `EvidenceBaseline` and `TargetAnchor` (`engineering_context/models.py:49-83`) | Drawing-to-model binding exists but is off until D6/D8; 016 matches saved targets without certifying live geometry | A content hash of model files; a staleness check of a plan against the live model |
| Sheet policy | The profile's `drawing` section (`sheet_formats`, `drafting_standard`, `projection`, `dimension_unit`, `drawing_template`, `bom_template`: `profile.py:280-322`); general-tolerance bands; revision section; conformance of existing drawings | `drawing_template` and `bom_template` are free strings "recorded for feature 012", never checked; units mm or in only | Template and format identity or version; paper size and scale policy; required title-block properties; a new drawing's initial revision rule |
| Views | The read-side vocabulary (type, orientation, configuration, scale); named-view capture | | Any rule for choosing views; section, detail or flat-pattern intent; layout (placement is never read); flat-pattern data in the IR |
| Annotations | The tolerance resolver and its source order (`checks/tolerances.py:88-100`), each answer cited or unresolved; Hole Wizard data; model dimensions and MBD annotations; existing drawings' callouts, notes and tables | Datums only as labels; callout variables and finish texts unparsed; the position callout has no datum reference; native values blocked by the binding switch | Finish, inspection and manufacturing-note sources beyond the material name and 016's free-text requirements; datum selection; a standard-notes library; a dimension-purpose model |
| Uncertainty | Gaps; unresolved coverage; code-asked questions; 016's provenance kinds including `ai_proposal` and `unknown` | | A register of unsupported creation operations; a record separating a proposed callout from an accepted one |
| Review | 016's `ConfirmationReceipt` (digests, actor, time, confirmed or rejected); evidence requests and answers; the re-modeler's reviewed-plan-then-executor pattern | Receipts cover only 016's records | A drawing-plan record and version; approval invalidation on input change; a separate engineering-acceptance record for a produced drawing |

## 4. Constraints a creator must respect

1. **Documents are read, not written**: two bounded exceptions exist, and "a third requires an
   amendment" (`.specify/memory/constitution.md:141-145`).
2. **Save is bound to the re-modeler's copy**: only `IModelDoc2.Save3`, which takes no file name
   (`constitution.md:160-164`; `Guard/RemodelGuard.cs:74`). A new drawing has no path until its
   first save, so that allowance cannot place one; the general guard denies `Save3` and `SaveAs3`
   (`Guard/ReadOnlyGuard.cs:44-45`) except image capture.
3. **The 011 guard refuses every drawing writer**: 28 drawing interface families, `NewDocument`
   and `NewDrawing` (`specs/011-drawing-context/contracts/guard.md:7-24`), including
   `AutoDimension`, `Create3rdAngleViews*`, `CreateDrawViewFromModelView*`, `InsertBomTable*`,
   `InsertModelAnnotations*` (`Guard/ReadOnlyGuard.Drawing.cs`).
4. **The one precedent for a narrow allowlist**: `DrawingOpenGuard`, three members, built only by
   `DrawingOpenScope`, shipped off (`Guard/DrawingOpenGuard.cs:6-23`).
5. **A write exception's shape**, from the re-modeler's: allowlisted members; target path, session
   tag and COM identity re-verified before each write; no model-facing tool names a document; each
   change logged with before, after and inverse; bounded count and time (`constitution.md:165-173`).
6. **The model proposes; a deterministic executor applies**; numbers come from tested software;
   output not verified on the pilot workstation enters no calculation (`constitution.md:39-70,
   174-184`).
7. **Scope**: "Autonomous GD&T creation, general drawing dimensioning, and structural approval are
   out of scope and require separate specification and validation" (`constitution.md:192-194`);
   every modelling dimension on a drawing is not a completeness test (`:122-123`).
8. **Amendment**: proposed with rationale, a MINOR version bump and a Sync Impact Report
   (`constitution.md:222-227`); the roadmap's D2 adds a fresh run-folder drawing only, refusal to
   overwrite, identity revalidation, logging, and cancel or discard without touching other
   documents.

## 5. Prior art: the owner's drawing macros

The owner's local SOLIDWORKS VBA macros were decoded read-only (55 projects, all decoded; SOLIDWORKS
was not started and no model or drawing was opened). Fourteen touch drawings:

| Kind | Macros |
|---|---|
| Create or annotate | a flat-pattern drawing generator (two versions), flat-pattern bounding dimensions, align all dimensions |
| Change an existing drawing | dimension numbering (inspection ids), sheet-format reload, BOM mass column |
| Read or check | a pre-release standards check, BOM export |
| Open or print | open drawing or its parent, batch print of child drawings |
| BOM and settings | an assembly BOM roll-up export, a select-all-dimensions helper (from a public sample), a settings macro for the default drawing template and the template and sheet-format folders |

**The only macro that creates a drawing is the flat-pattern generator.** No macro inserts model
items, runs `AutoDimension`, places balloons, writes title-block properties, or saves a drawing.

### 5.1 The flat-pattern generator (current version)

From a multibody sheet-metal part it creates a drawing: third-angle standard views and an
isometric on sheet 1, then sheets of flat-pattern views, one per group of identical bodies, each
with a label and scale note, and a summary table (part, quantity, material, thickness) on each
flat-pattern sheet.

- **Calls:** `SldWorks.NewDocument` (a hard-coded drawing template), `DrawingDoc.Create3rdAngleViews2`,
  `CreateDrawViewFromModelView3` (isometric), `NewSheet4` (built-in paper size, not the company
  sheet format), `PartDoc.GetBodies2`, `SheetMetalFeatureData.Thickness`,
  `CreateFlatPatternViewFromModelView3`, `View.ScaleDecimal` and `View.GetOutline` (auto-fit to a
  3-by-2 grid cell at 85%), `InsertNote` and `Annotation.SetPosition`, `InsertTableAnnotation`
  and `TableAnnotation.Text`. No dimensions; the drawing is left open, untitled and unsaved.
- **Inputs:** the active saved part and configuration; body names produced by a separate
  body-grouping macro it runs from a hard-coded path (its result unchecked); the part-level
  material property; two prompts (auto or fixed scale).
- **Binding and errors:** early-bound, no `Option Explicit`, no `On Error`; only three return
  values checked.
- **Defects found:**
  - a scale of 2:1 or larger divides by zero and crashes (only reductions are possible);
  - thickness is read from the wrong sheet-metal feature (body index used as feature index);
  - one part-level material for every row;
  - a body name without a space crashes the grouping split;
  - cancelling the scale prompt leaves a partial drawing and graphics updates off;
  - a failed body selection skips the view silently while the table still lists the part;
  - sheet activation assumes default sheet names;
  - sheet size and margins are passed as millimetres where the API takes metres;
  - mirrored bodies may be grouped as identical (left- and right-hand parts merged; to confirm).
- **Write behaviour:** one new unsaved drawing; the part is modified (bodies and flat-pattern
  features renamed by the helper) and left dirty; never overwrites a file.
- **Worth keeping:** grouping identical bodies into one view with a quantity, auto-fit scale per
  cell, the label and scale note, automatic sheet overflow, a summary table per sheet.

The earlier version has no grouping and no standard views, lays views out on a fixed 100 mm step
that runs off the sheet, and fills its table with placeholders; the current version supersedes it
except for `Option Explicit` and one return check.

**The body-grouping helper** renames bodies by cut-list folder (`BodyFolder.UpdateCutList`,
`CutListFolder.GetBodies`) or, without a cut list, by volume, area and face count
(`Body2.GetMassProperties`, `GetFaceCount`), and renames flat-pattern features
(`FlatPatternFeatureData.FixedFace2`). It cannot tell mirrored parts apart and modifies the part.

### 5.2 The other drawing macros

| Macro | What it does | Value to a creator |
|---|---|---|
| Flat-pattern bounding dimensions | On an existing drawing, adds overall width and height to each flat-pattern view through a bounding-box feature (`FeatureManager.InsertBoundingBox`, `View.SelectEntity`, `AddHorizontalDimension2` / `AddVerticalDimension2`). The box is per part, not per body, uses model axes, and modifies the referenced part. Uses unverified hand-coded enum numbers. | Requirements only: re-implement from the flat view's own geometry, without touching the part. |
| Align all dimensions | Selects every display dimension on the sheet and calls `ModelDocExtension.AlignDimensions(AutoArrange, 0.06)`. | Reuse the call as an optional tidy step, spacing from configuration. |
| Dimension numbering | Adds or removes a bordered inspection-id prefix on dimensions, GD&T frames and surface-finish symbols across sheets, continuing from the highest id; skips reference dimensions and hole callouts. Removal does not work for GD&T; an off-by-one strips a character. | Requirements source for an inspection-numbering rule. |
| Sheet-format reload | Re-applies the company sheet format per sheet (`SetupSheet5`), choosing first-sheet or continuation format by paper size (two sizes only), and moves datum tags, centre lines and revision symbols onto named layers. Forces third angle; an unsupported size stops part-way while saying nothing changed. | Requirements for template and sheet-format selection and layer rules. |
| Pre-release standards check | Report only: overridden dimensions, dangling annotations, revision-table against drawing and model revision properties, a prohibited-marking note, required data-card fields, and model checks. | Port to the review side as checks; it fits review better than creation. |
| Open drawing, batch print | Finds the drawing by the model's base name in its folder, with a fallback drawings folder; batch print walks an assembly's components and prints each same-name drawing. Its de-duplication by path prefix can skip a different drawing. | Requirements: the naming and location convention a creator must follow and check for collisions against. |
| BOM export, BOM mass, assembly BOM roll-up | Exports a drawing's BOM as tab text (silently overwriting); inserts a BOM and fills a mass column from each component's active configuration; the roll-up export uses structured error handling with a step log and timestamped files. | Requirements only; the roll-up's error handling is the collection's best pattern. |
| Settings | Sets the user's default drawing template and the template, sheet-format, BOM and title-block folders (global user settings). | A creator should read these locations, never hard-code them. |

### 5.3 Assessment

- **Binding:** almost all early-bound, depending on the SOLIDWORKS type library; enum numbers
  coded by hand in two places. Which API revisions to target on 2024 SP5 (`InsertTableAnnotation2`,
  later `NewSheet` and `SetupSheet` revisions) needs confirming at the seat.
- **Errors:** mostly no handling; a crash leaves graphics or feature-tree updates disabled; no
  rollback; message boxes as the only report.
- **Writes:** no macro saves a drawing; several modify referenced parts (renames, an inserted
  feature, configuration switches); one export overwrites silently.
- **Interactivity:** prompts and pre-selections throughout; none is fit for a headless, tested
  executor as it stands.

| Area | Recommendation |
|---|---|
| Flat-pattern sheet layout | Port the logic to C#, rewritten: cut-list grouping with a handedness check, scale from a standard-scale list in both directions, layout grid and template from a rule file, thickness and material per body from cut-list properties. |
| Standard and isometric views | Requirements only; template-driven placement, projection from the template. |
| Bounding dimensions | Requirements only; from the flat view's geometry, never modifying the part. |
| Align dimensions | Reuse the call as an optional tidy step. |
| Dimension numbering | Requirements for a future inspection-id rule. |
| Sheet format and layers | Requirements for format selection (first versus continuation sheet, by size) and layers. |
| Standards check (drawing) | Port to the review side as checks. |
| Naming, location, settings | Requirements: same base name beside the model (or the convention's folder); read template locations from user settings; refuse to overwrite an existing drawing. |
| BOM macros | Requirements only. |

Several macros carry other authors' headers (colleagues, an outside consultant, a public sample
library); their licence for porting is an open question (section 9).

## 6. The base repository: what its evaluation records

When the owner provides the repository, record, for each capability it has:

| Item | What to record |
|---|---|
| Operations | What it creates or changes: drawings, views, dimensions, annotations, tables, properties, exports. |
| Part families | Which part kinds it supports, and how it decides (sheet metal, machined, weldment, assembly). |
| Platform | Language, SOLIDWORKS API version and binding, add-in or standalone, other dependencies. |
| Inputs | What it needs from the model and the engineer: configuration, properties, prompts, files. |
| Rules | How it places views and dimensions, picks scale and sheet size, and where those rules live. |
| Errors | How it detects and reports failure, and what it leaves behind when it fails. |
| Writes | Which files it creates or modifies, whether it can overwrite, and how it names and saves. |
| Licence | Who owns it, and whether its code can be reused, ported or only read. |
| Tests | What tests or sample outputs exist, and how its results were accepted. |

The outcome is one of: reuse it, port its logic, or treat it as a requirements source only, with
the reason.

## 7. Requirements questionnaire: accepted drawings

For each accepted drawing the engineer nominates (two to five per candidate family), answer these
in the private file, never here. They define what a generated drawing must communicate; importing
every modelling dimension is not the goal.

1. **The part and its purpose.** What it does, what it mates with, and how it is made (cut,
   bent, machined, welded, purchased).
2. **Functional interfaces.** Which faces, holes and edges matter to fit or function, and why.
3. **Datums.** Which features are the datums, in what order, and who chose them (engineer,
   standard, inspection).
4. **Views.** Which views are required (standard, flat pattern, section, detail, isometric), at
   which orientation and configuration, and which are optional.
5. **Dimensions.** Which dimensions are meaningful to manufacture and inspect it, from which
   feature to which, and which are reference only.
6. **Tolerances.** For each toleranced dimension or feature, its source: a fit, a thread class, a
   functional need, the general tolerance block, or a standard.
7. **Hole and thread callouts.** Which holes get callouts, in what form, and which are covered by
   a table.
8. **Finish and material.** Surface finish, coating, heat treatment, and where each is stated.
9. **Notes.** The general notes used, which are standard and which are part-specific.
10. **Tables.** BOM, hole table, bend table, revision table: which appear and what columns.
11. **Title block and revision.** Which properties fill it, who sets each, and the revision rule.
12. **Sheet and template.** Which template and sheet format, sheet size and scale rules,
    projection (first or third angle), and units.
13. **Inspection.** What inspection checks, and which dimensions it reads.
14. **What is often wrong.** The usual review comments or rework on drawings of this kind.

## 8. Choosing the first family

Score each candidate family (for example sheet-metal flat patterns, machined plates and brackets,
weldments) on these, from this inventory and the questionnaire's answers:

| Criterion | What favours a family |
|---|---|
| Prior art | Working automation already exists for it (section 5, section 6). |
| Narrowness | Few view kinds, few datum and tolerance choices, repetitive layout. |
| Evidence available | What the repository already reads covers most of what its drawing needs (sections 1 and 3). |
| Engineering judgement | Little GD&T or datum choice that only an engineer can make; the plan can cite its sources. |
| Volume and value | How many such drawings are made, and how much time each takes by hand. |
| Risk | The cost of a wrong callout reaching manufacture, and how easily review catches it. |
| Fictional test packages | Whether fictional packages can exercise it offline (D1's first milestone needs no seat). |

The choice and its scores are recorded here, with the owner's decision.

## 9. Open questions for the owner

About the inputs:

1. The base repository's location and licence (section 6).
2. Which flat-pattern generator version is in use, and is its body-grouping helper always
   deployed with it?
3. May the macros that carry other authors' headers (colleagues, an outside consultant, a public
   sample library) be ported, or only read as requirements?

About the drawings a creator must make:

4. Projection: the macros force third angle on a metric template set; which does the company
   standard require? And the drafting standard, units, paper sizes and allowed scales for new
   drawings: the same values the conformance check uses?
5. What identifies a template and a sheet format (name, path, version, content hash), and what
   should the profile's free-text `drawing_template` and `bom_template` hold?
6. Which title-block fields are required, and which come from the model's properties and which
   from the drawing's? What initial revision and revision-table convention applies to a new
   drawing?
7. Who confirms datums, and how? Are DimXpert/MBD model annotations an accepted datum source? Does
   the company use them on parts?
8. Where does the general tolerance appear on a new drawing (note or table), and is the profile's
   band table its only source?
9. Which manufacturing requirements must a first drawing carry (finish, inspection, notes), and
   where are they sourced?
10. Should drawings take model annotations (`InsertModelAnnotations`) or be dimensioned
    drawing-side by rules? Should flat patterns carry overall bounding dimensions, as reference
    dimensions or a note? Is the inspection-id numbering convention still current?
11. Flat patterns: should their sheets use the company sheet format, and which paper size? Are
    mirrored (left- and right-hand) sheet-metal bodies common?
12. Which drawing location convention applies today: beside the model, or a drawings folder?

About the design:

13. Should brief version 2 grow into the plan's input, or should the plan get its own
    deterministic input, keeping the 6,000-byte brief for the model?
14. Are D4, D5, D6 and D8 (units, precision, entity binding) prerequisites for creation, or only
    for using existing drawings as evidence?
15. Should plan approvals and drawing acceptances reuse feature 016's confirmation receipts or
    have their own records, and who may approve?
16. Which first-save mechanism is acceptable for a new run-folder drawing, and should cancel
    delete the file or keep it?
17. Is SOLIDWORKS 2026's auto-generate path (D3) under consideration, or ruled out for the 2024
    SP5 seat?

## 10. Next steps

1. The owner provides the base repository; section 6's table is filled.
2. The engineer nominates accepted drawings and answers section 7 privately.
3. The first family is chosen by section 8.
4. D1: a reviewable drawing plan outside CAD is specified against fictional packages.
