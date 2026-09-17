# Standards Check Catalogue

Check ids are stable and appear verbatim in findings (`check`), coverage, exceptions, waiver
files and the report. Sixteen ids: seven assembly-scope, four part-scope, four drawing-scope,
one document-scope.

**`standards.release` is not a seventeenth check.** It is the family's **summary item**
(`STANDARDS_FAMILY.summary_check`, the standards counterpart of feature 003's
`modeling.resilience`): one aggregated `CoverageItem` per run carrying the verdict state and
the counts per bucket. It is **coverage only** - it has no scope, no severity, no fail
condition and no subjects; it is **excluded from the sixteen-row `checks[]` array**, from
every waiver file and from every acceptance; and no document is ever graded against it.
"No seventeenth result" in SC-001 and in `quickstart.md` means no seventeenth **check**
result: the summary item is always present and is not counted.

**Severity** is the macro's: **error** for fourteen, **warning** for
`standards.drawing.revision_matches` and `standards.drawing.no_itar_statement`. `error` maps
to a `demonstrated` finding, `warning` to a `suspected` one (`data-model.md` section 3).

**Granularity, stated once and never restated per check** (FR-003): every check is evaluated
**once per graded document**, and a failing check produces **exactly one finding for that
document**, carrying every subject that failed it and naming every component instance through
which the document is reached. A finding contributes **one** to its severity count regardless
of how many subjects it carries or how many instances reach it. A check may land in more than
one bucket for one document - a finding for two subjects, skipped coverage for a third,
unresolved for a fourth - and every check lands in at least one bucket for every document it
applies to.

**Unresolved instances, stated once and cited** (FR-005): a component instance that is
suppressed, lightweight, unloaded or otherwise unresolved is handled by FR-005 and by nothing
in this file. Each check's row says only which half of FR-005 applies to it - **document
evidence** (the instance produces an *unresolved* row naming the component, its state and the
evidence that was missing) or **instance signal** (the instance is not a subject and is named
in *skipped* coverage with its state as the reason; where the signal itself could not be read
the row is unresolved instead). The reviewer never resolves, loads or opens an instance to
obtain the evidence.

**Out of scope by document kind** (spec Edge Cases): a check whose scope does not match a
graded document's kind is `out_of_scope` coverage for that document, naming the kind - never
a pass and never an absence. All sixteen checks therefore appear on every run.

**Profile values** are named here by their profile field, never by value. An **empty** profile
setting has two opposite meanings and the rule follows which of the two it is:

- A setting that **selects what to check** - `data_card.properties`, `part_number.pattern`,
  `revision.property`, `export_control.phrase` - leaves nothing to test when it is empty, so
  its check is `skipped` coverage naming the empty setting and that count travels on the
  headline (FR-032). This is what keeps an unconfigured profile from silently **passing** a
  document.
- A list that **exempts or reclassifies** - `library.skip_prefixes`,
  `library.sketch_exempt_prefixes`, `library.one_mate_prefixes`, `library.two_mate_prefixes` -
  exempts and reclassifies nothing when it is empty, so the check **runs on every document it
  applies to**. This is what keeps an unconfigured profile from silently **grading nothing**.

An empty exemption list is not a reason to skip a check; it is a statement that no document is
exempt.

---

## Assembly scope

Evaluated for every **assembly** document the traversal reaches - the root assembly and every
sub-assembly - not only the root. The macro dropped the exploded and rebuild checks for
sub-assemblies although its top-level versions already scanned every component at every level;
making the checks document-scoped removes that inconsistency without removing coverage
(difference v).

| Check id | Severity | Statement | Evidence read | Fail condition | Checked | Skipped | Unresolved |
|---|---|---|---|---|---|---|---|
| `standards.assembly.not_exploded` | error | An assembly is not left in an exploded state. | `Document.is_exploded` | `is_exploded` is true; subject is the document | `is_exploded` is false | never | `is_exploded` is null and an `assembly_exploded` gap is recorded, naming the reason. **FR-005: document evidence** - a sub-assembly reached only through unresolved instances is unresolved, naming the component and its state |
| `standards.assembly.rebuild_errors` | error | An assembly carries no rebuild errors. | `Document.rebuild_error_count` | `rebuild_error_count > 0`; subject is the document, and the finding names the count **and states that the count is what the document carried as it stood and that nothing was rebuilt** (difference g) | `rebuild_error_count == 0` | never | `rebuild_error_count` is null. **Per-feature error codes are not substituted for it**, because the document count also covers mate errors that no feature carries. **FR-005: document evidence** |
| `standards.assembly.mate_references` | error | No mate has lost a reference. | `Mate[]` of the document, `MateEntity.resolution_status` | Any mate whose count of entities with `resolution_status == "resolved"` is **less than** its count of entities; subjects are those mates, each named with both counts and the entities that did not resolve | Every mate of the document resolves every entity | The document records **no mates**, reason `no mates`. This is difference e: the macro dereferences a null mate-group feature and raises a run-time error here | Per mate with any entity whose `resolution_status` is `"unknown"` or null, naming the mate. **And once per sub-assembly**, naming it and the missing sub-assembly mate data: the package walks only the root assembly's mate group (difference h) |
| `standards.assembly.one_fixed` | error | At most one component of an assembly is fixed. | `ComponentInstance.is_fixed`, `.parent_id` | The document's **immediate child** components include **more than one** whose `is_fixed` is true; subjects are every fixed component | Zero or one fixed immediate child | The document has no immediate child components | Per component whose `is_fixed` could not be read. **FR-005: instance signal** |
| `standards.assembly.fully_mated` | error | Every under-constrained component is fully mated, or carries the minimum mates its library class requires. | `ComponentInstance.constrained_status_raw`, `.is_pattern_instance`, `.pattern_id`, `.document_id` -> `Document.path`, `Mate[]` and `Mate.suppressed`, profile `library.one_mate_prefixes` / `two_mate_prefixes` | For each immediate child component whose derived constrained status is **under-constrained**: with `PrefixMatch.mate_requirement == 0`, it fails; with `1` or `2`, it fails when its count of **unsuppressed** mates is below that minimum, and the finding names the component, the requirement and the count found (difference s: a suppressed mate constrains nothing, which the macro's own note records as a known limitation) | The component's status is fully or over constrained | Per component whose `is_pattern_instance` is true, naming the pattern from `pattern_id` where it is known (difference t). The root component, and the synthesized root of a part opened alone, have no constrained status by design and are **not subjects**. The whole check is skipped for a document with no immediate child components | Per component whose `constrained_status_raw` maps to unknown or unavailable, or whose `is_pattern_instance` is null. **And, for a sub-assembly, per under-constrained component whose path matches a one-mate or two-mate prefix**, naming that sub-assembly and the missing mate data - every other component of a sub-assembly is decided on its constrained status exactly as in the root. **FR-005: instance signal** |
| `standards.assembly.not_transparent` | error | No component is left in a transparent state. | `ComponentInstance.has_appearance_override`, `.transparency_raw`, and the module constant `TRANSPARENCY_POLARITY` | With the polarity settled: each immediate child whose `has_appearance_override` is true and whose `transparency_raw` means transparent under the settled polarity; subjects are those components | `has_appearance_override` is false, or the value means opaque under the settled polarity - **after PROBE-2 has settled the polarity** (the broad reading of FR-012, resolved in `research.md` R2.8: the polarity decides how the recorded value is read for **every** component, including one with no override, so no component can be checked coverage while it is unsettled) | never | **Every component of every assembly, on every run, while `TRANSPARENCY_POLARITY` is `unsettled`**, reason naming the unsettled polarity and PROBE-2 (FR-012, difference d, SC-014). After it is settled: per component whose `has_appearance_override` or `transparency_raw` could not be read. **FR-005: instance signal** - which differs from the macro, whose transparency check did not skip suppressed components (difference c) |
| `standards.assembly.not_hidden` | error | No component is left hidden. | `ComponentInstance.visibility_raw` | Each immediate child whose `visibility_raw` names hidden; subjects are those components | `visibility_raw` names visible | never | Per component whose `visibility_raw` is null or names unknown. **Suppression is never treated as hidden** (difference c): a suppressed instance is FR-005's skipped row, not a finding of this check. **FR-005: instance signal** |

---

## Part scope

Evaluated for every **part** document the traversal reaches.

| Check id | Severity | Statement | Evidence read | Fail condition | Checked | Skipped | Unresolved |
|---|---|---|---|---|---|---|---|
| `standards.part.sketches_fully_defined` | error | Every sketch is fully defined. | `Feature.sketch.raw_status`, `.text_segment_count`, `Feature.name`, `.folder_id`, `Feature.sketch.consumer_ids`, profile `library.sketch_exempt_prefixes` | Any sketch whose derived constrained status is **under-defined**; subjects are those sketch features, each naming the **chain of parent features that reaches it** and, where the sketch belongs to a hole-wizard feature, that feature too (difference z). **Every sketch the package records is a subject, at any depth** | Every sketch is fully defined, over-defined or exempt | Per sketch whose `text_segment_count > 0`, reason naming the sketch-text exemption (the macro's rationale: connector-label text cannot easily be fully defined). Whole check skipped when the part's path matches a `library.skip_prefixes` entry (reason naming the matched prefix, FR-006); when the part's path matches a `sketch_exempt_prefixes` entry, naming the matched prefix; and when the part records **no sketches**. An **empty** `sketch_exempt_prefixes` exempts nothing and is never itself a skip | Per sketch whose `raw_status` is null or maps to unknown (for example automatic solving off), and per sketch whose `text_segment_count` is null, because the text exemption can then neither be applied nor ruled out. **FR-005: document evidence** |
| `standards.part.rebuild_errors` | error | A part carries no rebuild errors. | `Feature.error_code`, `Feature.name`, `.folder_id`, `Document.rebuild_error_count` | Any feature with a **non-zero** `error_code`, **or** `rebuild_error_count > 0`; subjects are every such feature with its code and its chain of parent features, plus the document when the count is non-zero. **Every feature the package records is a subject, at any depth** (difference z). The finding and the report state that the counts are as the document stood and that nothing was rebuilt | Every feature's code is zero **and** the document count is zero | The part's path matches a `library.skip_prefixes` entry (reason naming the matched prefix, FR-006); otherwise never | Per feature whose `error_code` is null, and once for the document when `rebuild_error_count` is null. The macro ignores `GetErrorCode2`'s warning out-parameter, so feature *warnings* count as errors; this feature keeps that condition (any non-zero code) and **names the code**, so an engineer can tell them apart (difference u). **FR-005: document evidence** |
| `standards.part.material_assigned` | error | A part has a material assigned, or a deliberately overridden mass - and not both. | `Document.material`, `.material_configuration`, `.mass_overridden`, profile `material.configuration` | Two of the four cells below. The finding names **which** of the two conditions held | Two of the four cells below | The part's path matches a `library.skip_prefixes` entry (reason naming the matched prefix, FR-006); otherwise never, because a part always has a material state | `material_configuration` is not the profile's `material.configuration`, or the document has no such configuration - naming **both** configurations; or `material` could not be read; or `mass_overridden` is null. Pass and fail differ only by those two signals, so either being unknown makes the answer unknown. **FR-005: document evidence** |
| `standards.part.cut_list_excluded` | error | Every cut-list item is excluded from the cut list. | `CutListItem.excluded_from_cut_list`, `.body_count`, `.folder_name`, `.name` | Any cut-list item whose `excluded_from_cut_list` is **false**; subjects are those items with their folder | Every recorded item is excluded | The part's path matches a `library.skip_prefixes` entry (reason naming the matched prefix, FR-006); or the document records **no cut-list items**, reason naming that (difference aa: the macro prints nothing here, which reads as a pass). Items in a folder whose `body_count` is `0` are **not subjects** at all - SOLIDWORKS does not display such a folder - and the reason says how many folders were seen and how many were displayable | Per item whose `excluded_from_cut_list` is null, and once per folder whose `body_count` is null. **FR-005: document evidence** |

### `standards.part.material_assigned` truth table

The macro's version of this check sets its status flag without its error flag in the
headline case, so its reporter drops the row and **"part has no material" is never reported**
(difference b, limitation L1). All four cells below are live here.

| `material` | `mass_overridden` | Outcome | Observed text |
|---|---|---|---|
| null | false | **fail** | no material assigned in `<configuration>` and the mass is not overridden |
| null | true | checked | no material assigned, mass deliberately overridden |
| set | false | checked | material `<name>` assigned in `<configuration>` |
| set | true | **fail** | material `<name>` assigned **and** the mass overridden; the recorded mass is not computed from the geometry |

---

## Drawing scope

Evaluated for every **drawing** document in the package. **Native sheets only, decided per
sheet**: every sheet record carries its own `source` - `DrawingSheetRecord.source` is the
constant `"native"`, and the PDF ingest's `DrawingSheet.source` is `"pdf_ingest"` (or null in a
sheet written before 1.4.0, read the same way). A drawing with **no** native sheet makes all
four checks `unresolved` coverage naming the evidence source, because a parser with known
limits may not produce a demonstrated finding (FR-024). A drawing whose sheets came from
**both** paths is graded on its native sheets and carries, for each of the four checks, an
additional `unresolved` row naming the PDF-ingested sheets and their source - so a mixed
drawing is never reported as fully checked and never refused outright.

**The export-control note lives on the sheet-format pseudo-view**, which is the only place the
macro ever found it (`DrawingView.view_type_raw == 1`). A sheet whose record carries **no
type-1 view** therefore makes `standards.drawing.no_itar_statement` **unresolved** for that
sheet, naming the missing sheet-format view - not `checked`, which would be a silent pass on
the one check whose defect is a presence. PROBE-5 and PROBE-7 settle whether `ISheet.GetViews()`
returns that pseudo-view at all; if it does not, `IDrawingDoc.GetFirstView()` /
`IView.GetNextView()` is the named fallback enumeration (`research.md` R3.3).

**Every sheet is read** (difference q). The macro reads the current sheet's revision table only
and scans notes only in the first view of the current sheet, so a multi-sheet drawing is
under-checked. Where PROBE-7 shows a non-active sheet's contents cannot be enumerated without
activating it, the dump records a gap **per non-active sheet** and each affected check is
`unresolved` for those sheets - the sheet is **not** activated (FR-044).

| Check id | Severity | Statement | Evidence read | Fail condition | Checked | Skipped | Unresolved |
|---|---|---|---|---|---|---|---|
| `standards.drawing.dimensions_not_overridden` | **error** | No display dimension carries a manual override. | `DisplayDimensionRecord.is_overridden`, `.override_value`, `.name`, its view and sheet | Any display dimension whose `is_overridden` is true; subjects name the sheet, the view, the dimension and **its override value rendered with the unit the package recorded it in** - whichever of `Quantity` (a length) or `Angle` (an angle) the record carries, decided by `dimension_type_raw` (difference p). Ownership of the dimension by the model rather than by the drawing does **not** exclude it - an overridden model-item dimension is the defect being hunted | No display dimension is overridden | The drawing records no display dimensions | Per dimension whose `is_overridden` is null, and **per dimension whose `is_overridden` is true but whose `override_value` unit could not be determined** - a number with a guessed unit is the macro's bug, so the dimension is reported unresolved naming it rather than rendered. Per non-enumerable sheet (PROBE-7) |
| `standards.drawing.annotations_not_dangling` | **error** | No annotation is dangling. | `DrawingAnnotation.is_dangling`, `.type_raw`, `.name`, its view and sheet | Any annotation of **any** type whose `is_dangling` is true; subjects name the sheet, the view, the annotation **type and identity** (difference o: the macro emits the same unidentifiable sentence for every occurrence). An annotation whose `name` is null is still a subject, identified by its package id, its sheet and its view | No annotation is dangling | The drawing records no annotations | Per annotation whose `is_dangling` is null; per non-enumerable sheet |
| `standards.drawing.revision_matches` | **warning** | The revision table, the drawing's revision property and every referenced model's revision property agree. | `RevisionTable.rows`, `.current_revision_raw`, `Document.custom_properties[profile.revision.property]` for the drawing and for each referenced document, profile `revision.*` | One finding for the drawing naming **every** disagreement it found, in three cases: (1) **no revision table on any sheet**; (2) a revision read from a table disagrees with the drawing's revision property; (3) the drawing's revision property disagrees with a referenced document's revision property. Each disagreement names **both values and their source**. The revision is read from the cell `revision.cell` names (a row selector counted from the end and a column index). A table whose last data row is still its header row (cell 0 equals `revision.header_text`) is read as `revision.initial`. Comparison is **case-insensitive**. An empty cell is compared as empty and reported as a mismatch naming the empty cell, never normalized into a pass. **Every sheet's revision tables and every referenced document are compared** (difference y). Where `current_revision_raw` and the cell reading disagree, the **cell reading named by `revision.cell` is normative** (RK-4) and the observed text names both values with their source, so the disagreement is visible without blocking the verdict - the macro's author recorded that the interop's own current-revision reading comes back empty under the vault, so a disagreement is the expected case there, not a data gap | A revision table exists, every table agrees with the drawing property, and every referenced document's property agrees with it | `revision.property` is empty in the profile, naming the empty setting | Per table whose cells could not be read (`revision_table_read` gap), including when the runtime cast to the table interface failed (RK-4); when the drawing's or a referenced document's custom properties could not be read; and **for the model comparison when the drawing references no document at all** - the drawing's own table-versus-property comparison still runs, and nothing crashes (difference f: the macro dereferences the second view of the current sheet and raises a run-time error here). A disagreement between `current_revision_raw` and the cell reading is **not** unresolved - see the Fail condition: the cell is normative and both readings are reported |
| `standards.drawing.no_itar_statement` | **warning** | No export-control statement appears in the drawing's notes. | `DrawingNote.text`, its view and sheet, profile `export_control.phrase` | The phrase appears as a **case-insensitive substring** in any note's text, anywhere on any sheet, in any view or sheet format; one finding naming every sheet and note that carried it. Presence is the defect | The phrase appears in no readable note, **and every sheet recorded a type-1 sheet-format view** | `export_control.phrase` is empty in the profile, naming the empty setting; or the drawing records no notes **and** every sheet recorded a type-1 view (so the absence of notes is a real absence rather than an unread one) | Per note whose `text` is null, **because an unread note cannot be shown not to carry the statement**; per sheet that recorded **no type-1 sheet-format view**, naming it; per non-enumerable sheet |

---

## Document scope (all three kinds)

| Check id | Severity | Statement | Evidence read | Fail condition | Checked | Skipped | Unresolved |
|---|---|---|---|---|---|---|---|
| `standards.document.data_card_complete` | error | The data card is complete on every document whose file name follows the part-number convention. | `Document.file_name`, `.custom_properties` (the configuration-independent set), profile `part_number.pattern` and `data_card.properties` | Any profile property that is **absent** or resolves to a value that is **empty or whitespace only**; subjects are those property names, **each saying whether it was absent or blank** (difference m). The finding is one per document whatever the number of blank fields (difference n: the macro counts four for a blank card) | Every profile property is present and non-blank | The file name does **not** match `part_number.pattern` (reason naming the convention); the pattern is empty (reason naming the empty setting); `data_card.properties` is empty (same); or the document's path matches a `library.skip_prefixes` entry **and the document is a part** (reason naming the prefix) | The document's custom properties could not be read. **FR-005: document evidence** |

**Matching the pattern.** `#` is one digit, `?` is one character, every other character is
literal; the match is **whole-string** and **case-insensitive**, against the **file name
including its extension**, taken from `Document.path`. It is not matched against the window
title: SOLIDWORKS can be configured to hide extensions in titles, and the macro's version of
this check then switches itself off entirely (difference l, limitation L9).

**Which property set.** The configuration-independent custom properties, as the macro reads
them. A field that carries a value only in a configuration-specific property is reported as
absent or blank, and the observed text names that scope so the engineer can see why
(spec Edge Cases; extracting configuration-specific data-card properties is named as out of
scope).

---

## Library prefix effects (normative)

One table, because these are four independent questions about the same path and the macro's
own bug was letting one answer cancel another (FR-006).

| Profile list | Applies to | Effect |
|---|---|---|
| `library.skip_prefixes` | **part documents only** | `standards.part.sketches_fully_defined`, `standards.part.rebuild_errors`, `standards.part.material_assigned`, `standards.part.cut_list_excluded` and `standards.document.data_card_complete` become **skipped** coverage naming the matched prefix. An **assembly** document under the same prefix is graded normally, as the macro graded it |
| `library.sketch_exempt_prefixes` | part documents | `standards.part.sketches_fully_defined` becomes skipped coverage naming the prefix. **No other check is affected** |
| `library.one_mate_prefixes` | components, via their referenced document's path | Changes only `standards.assembly.fully_mated`'s requirement for that component, to one unsuppressed mate. Skips nothing |
| `library.two_mate_prefixes` | components, via their referenced document's path | Changes only `standards.assembly.fully_mated`'s requirement for that component, to two unsuppressed mates. Skips nothing |

Matching is **case-insensitive, path-normalized and anchored at the start of the path**. A
prefix is a prefix **whether or not it ends in a path separator**, so an entry naming a single
file matches that file and any path that starts with it. Within **one** list the **longest**
matching prefix decides, and **every** match in that list is named in the coverage reason. The
four lists are matched **independently**; a match in one never cancels a match in another.
**Across the two mate-count lists the longest matching prefix decides, and on an exact tie the
one-mate requirement wins** (`contracts/profile.md`, prefix semantics rule 6) - one rule rather
than two, and not, as in the macro, whichever list happened to be tested first.

## Unresolved documents (normative)

A document the traversal reached whose **kind or path the package does not record** - a
virtual component, a library-feature part, a kind that is not a part, an assembly or a drawing
- is `unresolved` coverage for **every check that would have applied to it**, once per
document, naming the document and the component instances that reach it. It never refuses the
whole run.

Only the **root** document can refuse a run: a root whose kind the package does not record, a
root with no path, or a root that has never been saved (FR-004). The macro is silent in every
one of these cases, because it decides document kind from the last three characters of the
path everywhere except its entry point (difference k, limitation L17).

A document reached through at least one **resolved** instance is graded normally, with the
unresolved instances named in the finding's `coverage_limits`.

## Waivable checks

Only **error**-severity checks are acceptable as exceptions. A waiver naming
`standards.drawing.revision_matches` or `standards.drawing.no_itar_statement` is reported
`invalid (warning check)` and changes nothing, and the Accept control is **absent** for those
two rather than disabled - a disabled control invites a request to enable it; an absent one
states the rule.

An acceptance waives the **check for that document**, never a check on one subject. The
exception is bound to the check id, the document, its component instances (where it has any),
the configuration and a fingerprint of every input the check read, so a newly appearing
subject re-opens the finding for re-review rather than being silenced.
