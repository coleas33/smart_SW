# Research: Standards Check

**Feature**: `006-standards-check` | **Date**: 2026-09-17 | **Plan**: [plan.md](plan.md)

Phase 0 output from: the owner's handover of the owner's release-checklist macro (a 2017 VBA
release-checklist macro) and its description document on 2026-09-16; a full
reverse-engineering of that macro (entry, traversal, one section per check with the exact API
members, conditions, severities and skips, forty-three constants, twenty-two stated or
discovered limitations, and the report format), which is **normative for what each check
means**; a signal-by-signal coverage audit of the current extractor and IR against those
sixteen checks; the design conversation recorded in the feature's design brief; and a
**reflection pass over the SOLIDWORKS 2024 SP5 interop assemblies installed on the pilot
machine** on 2026-09-16, by the same method that produced feature 004's frozen interop
manifest.

Where this document says a member is VERIFIED, it means: present, with that signature, on
`SolidWorks.Interop.sldworks` / `SolidWorks.Interop.swconst` version **32.5.0.48**
(SOLIDWORKS 2024 SP5), confirmed by reflection on 2026-09-16. It does **not** mean the member
behaves as documented at runtime; that is what R4's ten probes are for, and no rule is trusted
on a real document before its probe has answered.

---

## R1. What the source material is, and what is normative

| Source | What it is | Authority here |
|---|---|---|
| the macro (an olevba dump, 1866 lines) reverse-engineered into a check table | Entry point, traversal, sixteen check functions with their exact API members, conditions, severities and skips, forty-three constants, the report format, and twenty-two limitations - four the author stated and eighteen found by reading | **Normative for what each check means.** **Held with the owner, not in this repository, and cited by no path**: it reproduces all forty-three constants verbatim, so committing it would publish exactly the values FR-001 keeps out. The spec's Appendix A cites it by section name and number and states enough of each condition to stand alone; R5 below carries the only values from it this repository needs |
| its description document | The owner's plain-language description of the standard | The intent behind each check, and the tie-breaker where the macro's code and its description disagree |
| The coverage audit of the extractor and IR | Which of the sixteen checks' signals the package already carries, which are partial, which are missing, and what the tab and rule machinery to reuse is | Where each signal comes from today and what must be added |
| The design brief | Ten binding decisions taken with the owner on 2026-09-16 | Recorded in the spec; not re-opened here |

**Where the macro is buggy, this feature follows the documented intent and records the
deviation.** The spec's "Differences from the Macro" table (rows a to bb) is the single list;
this document does not restate it and instead records, in R2, only the *implementation
consequence* of the rows that shape a design decision.

**The macro is the owner's company's own work**, handed to this project by the owner for this
purpose. No code is reused - the macro is VBA and this implementation is C# and Python - and
what is reused is the meaning of sixteen checks. The company's **values** are deliberately not
reused into this repository at all; see R6 and R5.

---

## R2. Decisions, alternatives and rationale

Ten decisions. Each records what was chosen, what else was weighed, and why.

### R2.1 The checks run over the evidence package, not live

**Decision**: the sixteen checks are pure functions over `package.json` plus the profile.
Signals the package lacks are added to the dump; nothing is read from SOLIDWORKS by the
reasoning side.

**Alternatives**: (a) a Python-plus-pywin32 checker that walks the live session, which is what
the macro does and what would have needed no IR work at all; (b) a C# in-process checker in
the add-in that both reads and grades.

**Why**: (a) violates Principle II's separation and the constitution's "reasoning-side code
MUST run without a SolidWorks license", and it makes every check untestable without a seat -
sixteen checks with roughly seventy named edge cases between them would then have no unit
tests at all. (b) puts the grading where a mechanical engineer cannot read or test it, and
duplicates the rule machinery feature 003 already has in Python. The cost of the chosen path
is real and is this feature's largest: a whole new drawing extraction phase. It is paid once,
and the drawing evidence is then available to every other check and to the review loop.

### R2.2 Each document is graded once; one finding per failing check per document

**Decision**: deduplicate by `document_id`. A failing check produces exactly one finding for
that document, naming every subject that failed it and every component instance through which
the document is reached, and contributing **one** to its severity count.

**Alternatives**: (a) reproduce the macro - check each component **instance**, so a part used
twenty times is checked and counted twenty times; (b) one finding per subject.

**Why**: the macro declares a `processedFiles` collection, clears it in `main`, and never
reads or writes it again - deduplication is the author's unfinished intent, and this is it,
finished. Its consequence is that the macro's error count measures assembly size rather than
defect count (twenty instances count twenty; a blank data card counts four; a part with twelve
bad features counts one), which cannot be a release gate. (b) was weighed and rejected because
the release verdict is "how many checks failed", and a per-subject finding count makes a
drawing with six overridden dimensions look six times worse than one with one - the same
failure the macro has, in a different coordinate system. Subjects live **inside** the finding
and are never counted (difference n). SC-006 is the test.

### R2.3 One rule for suppressed, lightweight and unloaded instances

**Decision**: FR-005 splits on **where the check's evidence lives**. A check whose evidence
comes from the instance's *referenced document* is **unresolved** for that instance, naming
the component, its state and the evidence that was therefore missing. A check whose subject is
the *instance itself*, and whose signal the package records on the instance, does not take it
as a subject at all and names it in **skipped** coverage with its state as the reason.

**Alternatives**: (a) the macro's - skip silently; (b) unresolved for everything; (c) skipped
for everything.

**Why**: (a) is the constitution's forbidden case, and it has a concrete cost the macro's
author did not see: a lightweight-loaded assembly produces far fewer findings with no
indication that it did (limitation L15). (b) would make an assembly with one suppressed
component report four unresolved rows about a component that is deliberately not part of the
configuration being graded - noise that trains an engineer to ignore unresolved rows, which is
how a real gap gets lost. (c) hides a genuine data loss: a suppressed component's *document*
was never read, and every check that needed that document's evidence genuinely does not know.
The split is stated once in FR-005 and **cited** per check in `contracts/rules.md` rather than
restated, so the two halves cannot drift apart.

### R2.4 Company values live in a profile file outside this repository

**Decision**: a YAML **standards profile**, validated by one pydantic model on the reasoning
side, holding the vault root, four library prefix lists, the data-card property names, the
part-number file-name pattern, the revision property name, the initial-revision value, the
revision-table header text, the revision-table cell location, the material configuration name
and the export-control phrase. The repository ships `config/standards.example.yaml` with
fictional placeholder values; tests use two fictional fixtures; the owner writes the real file
on the workstation. **There is no built-in fallback.**

**Alternatives**: (a) constants in the Python source, as the macro has them in VBA; (b) a
committed profile in this repository; (c) environment variables; (d) a profile with built-in
defaults so a missing file still runs.

**Why**: this repository is public. (a) and (b) publish the company's vault layout, its
library folder names, its data-card schema, its part-number convention and its export-control
phrase, which is a disclosure the owner did not ask for and cannot undo. (c) scatters a
thirteen-field schema across thirteen names with no validation and no single file to review.
(d) is the dangerous one, and it is the reason FR-001 says "no built-in fallback": a fallback
value grades a document against the *wrong* standard and reports a clean result, which is
worse than refusing. A missing, unreadable or schema-invalid profile refuses the run.

YAML rather than JSON because a human writes it and it wants comments; pydantic rather than a
JSON Schema file because the reasoning side already validates every other input that way and a
second validation technology is a second thing to keep in step.

### R2.5 The profile has exactly one schema owner

**Decision**: `checks/standards/profile.py`. The **host** checks only that a path is
configured and the file is readable, and refuses before it creates a run folder or dumps
anything. The **backend** validates the schema and returns the named schema error.

**Alternatives**: (a) validate in the host too, so the engineer learns about a bad field
before a dump runs; (b) validate only in the host and pass the parsed values to the backend.

**Why**: (a) is the schema expressed twice, in two languages, with no mechanism keeping them
in step - the classic drift. The cost of not doing it is one wasted dump on a
schema-invalid profile, and FR-002 turns that into a stated outcome: the run folder created
before the refusal is reported as an **empty run**, not as a result. (b) would put company
values into a `postMessage` payload and into the host's memory, which FR-034 forbids (the
check record identifies the profile by **path and content hash** and copies no value into the
record, the session, the report or any message to the page).

### R2.6 A sibling rule family, with feature 003's machinery generalized

**Decision**: move `RuleResult`, the outcome and severity mapping, `report_results`, the
coverage aggregation, `carry_forward` and the run-folder and check-record skeleton out of
`checks/rms/` into a family-neutral `checks/rules/`, parameterized by a `CheckFamily`
descriptor (name, summary check id, rules version, scope vocabulary, tool names). `checks/rms`
keeps its module paths as shims that bind `RMS_FAMILY` - thin for `results.py`, `run.py` and
`registry.py`, and **not** thin for `report.py`, which keeps the RMS feature-group subject
decorator and its two extra-coverage steps and supplies them to the moved layer (R7).

**Alternatives**: (a) copy the machinery into `checks/standards/`; (b) have
`checks/standards/` import directly from `checks/rms/`; (c) leave feature 003 alone and give
the standards family a simpler, different result model.

**Why**: (a) is roughly 700 lines of duplication of exactly the logic that decides whether an
unknown is reported as unresolved - the one place in this codebase where a divergence between
two copies would be a silent correctness bug rather than a cosmetic one, and the constitution's
DRY rule names this case. (b) makes one family depend on the other's name for no reason and
leaves the three hard-codings (`SUMMARY_CHECK = "modeling.resilience"`, `RuleScope =
Literal["part", "assembly", "equations", "drawing", "advisory"]`, `RULES_VERSION = "1"`) still
hard-coded. (c) gives the two tabs two different answers to "what does unresolved mean", which
is precisely what an engineer must not have to hold in their head.

The move's correctness is proved by feature 003's own tests: after the move, **every
`checks/rms` unit test and every `rms-*` golden passes with no edits**. That gate is its own
task, with none of this feature's code in it. If a test needs an edit, the move was not a move.

### R2.7 Read as it stands: no rebuild, and no sheet activation

**Decision**: `ForceRebuild3` stays on the read-only denylist and this feature adds no
exception. Rebuild-error counts are read as the documents stand and the report says so.
Sheets are read through `ISheet.GetViews()` without activating them, and `ActivateSheet` joins
the denylist along with the other mutating and view-changing members enumerated in R8.

**Alternatives**: (a) reproduce the macro's `ForceRebuild3(false)` on drawings under a bounded
exception like feature 003's suppress-test; (b) activate each sheet and restore the original,
as the macro does.

**Why**: (a) would be a **third** constitution exception, needing an amendment, for a
behaviour whose only effect is to make a rebuild-error count fresher. The honest alternative
is to say what was read: the finding and the report both state that the count is what the
document carried as it stood and that nothing was rebuilt (difference g). An engineer who
wants a fresh count rebuilds in SOLIDWORKS and presses Standards again - one click, no
exception. (b) is a display-state mutation the constitution's read-only rule covers, and it is
also the macro's most visible side effect (the sheet flickers through every sheet in the
drawing). `ISheet.GetViews()` is VERIFIED present and is the reason (b) is avoidable; whether
it returns populated contents for a **non-active** sheet is PROBE-7, and if it does not, the
phase records a gap per non-active sheet and the affected checks are unresolved for those
sheets. It does not activate the sheet.

### R2.8 The transparency polarity is a probe answer in one named constant

**Decision**: the extractor records the raw transparency slot and whether the component
carries a component-level appearance override at all. Python holds one module constant,
`TRANSPARENCY_POLARITY`, whose value is `unsettled` until PROBE-2 answers; while it is
`unsettled` the check reports **unresolved** on fixtures and on the workstation alike.

**Alternatives**: (a) follow the macro - treat the recorded value `1` as acceptable and
everything else as transparent; (b) follow the SDK - treat `0` as opaque and anything greater
as transparent; (c) put the polarity in the profile.

**Resolution of FR-012's two halves, recorded here because the contract implements it**: while
`TRANSPARENCY_POLARITY` is `unsettled`, **every** component of every assembly is unresolved -
including a component whose `has_appearance_override` is false. The polarity question decides
how the recorded value is read for every component, so "no override" cannot be graded as
checked coverage against a rule nobody has yet fixed; FR-012's first sentence describes the
**settled** state, and `contracts/rules.md` says so in the row's Checked column. SC-002 and
`quickstart.md` scenarios 2 and 3 take the broad reading.

**Why**: (a) and (b) are opposite guesses, and the macro's own author left a comment that does
not explain the choice. Guessing either way silently mislabels **every component that carries
an appearance override**: (a) flags every one of them, (b) clears every one that is only
slightly translucent. Neither failure is visible to an engineer reading the result - which is
exactly the class of error Principle I exists to prevent. (c) is wrong because the polarity is
a fact about SOLIDWORKS, not about the company; putting it in the profile would ask the owner
to answer a question they cannot answer and would let two machines disagree about physics.

### R2.9 Grading a drawing means grading what it references

**Decision**: when the root document is a drawing, the dump also runs the model phases over
each document any view on any sheet references, and over everything reachable through a
referenced assembly's component tree - **using only what is already loaded in the session**.
It opens, loads and resolves nothing. Every document is graded once, whether it is reached
from the root or from a drawing's reference.

**Alternatives**: (a) grade the drawing only, and leave the model checks to a separate run on
the model; (b) open the referenced documents so the fan-out is complete.

**Why**: (a) loses the owner's stated workflow - the macro's description says running on a
drawing checks the parent and then all associated children - and it loses the one check that
*needs* both (`standards.drawing.revision_matches` compares the drawing's revision property
against the referenced model's). (b) is the read-only rule: opening a document changes the
session, can trigger a rebuild, and can load a file the engineer did not ask for. The macro
never opens a document either (there is no `OpenDoc` call anywhere in it), so this is not even
a deviation - it is the macro's own behaviour, made visible: a referenced document that is not
loaded is a gap naming it, and its checks are unresolved (FR-025, difference j).

### R2.10 A third verdict state, and no letter grade

**Decision**: `not_ready` when the error count is above zero; `ready` when it is zero and no
check has an unresolved row; `ready_coverage_incomplete` when it is zero and one or more
checks do. The unresolved check ids travel with the verdict in **every** state, and the counts
in every bucket - error, warning, checked, skipped, unresolved, out of scope and waived - are
rendered beside it in every state.

**Alternatives**: (a) two states, the owner's "ready to release only with zero errors"; (b)
a percentage or a letter.

**Why**: (a) has to put unresolved coverage somewhere, and both places it can go are wrong:
folding it into `ready` claims a clean release over coverage that is unknown, and folding it
into `not_ready` tells an engineer their model is broken when the truth is that four checks
never ran. (b) is the confident-but-unsupported artefact Principle I exists to prevent, and
feature 003 already refused it for the same reason. The spec's Assumptions record that the
owner may collapse the third state either way; the decision is recorded so that it is a choice
rather than an accident.

---

## R3. API members each new signal needs

Reflection over `SolidWorks.Interop.sldworks` and `SolidWorks.Interop.swconst`
**32.5.0.48** (SOLIDWORKS 2024 SP5), 2026-09-16. "VERIFIED" = present with that signature.
"UNVERIFIED" = the signature question is settled but a runtime question remains; the probe
column names it, and the mitigation column says what the dump records when the answer is no.

### R3.1 Enum values the macro left unverified, now settled

The macro's reverse-engineering marked **two** enum values as believed or unasserted
(`swSelectType_e.swSelCOMPONENTS`, "believed 20", and `swAnnotationType_e.swDisplayDimension`,
not asserted); the rest were VERIFIED or SDK-standard. Both are now settled, and seven further
values this feature needs are confirmed on the pilot interop:

| Enum member | Value | Status | Used for |
|---|---|---|---|
| `swSelectType_e.swSelCOMPONENTS` | **20** | VERIFIED (was "believed 20") | Not used - the feature-tree walk it served is replaced by the component tree the package already carries |
| `swAnnotationType_e.swDisplayDimension` | **4** | VERIFIED (was unasserted) | `DrawingAnnotation.type_raw`; the dimension walk itself uses `IView.GetDisplayDimensions()` |
| `swAnnotationType_e.swNote` | **6** | VERIFIED | `DrawingAnnotation.type_raw` |
| `swInConfigurationOpts_e.swThisConfiguration` | **1** | VERIFIED (already verified in this repo) | `GetMaterialPropertyValues2` |
| `swDocumentTypes_e` part / assembly / drawing | **1 / 2 / 3** | VERIFIED | The dump's document-kind branch |
| `swComponentVisibilityState_e` hidden / visible / unknown | **0 / 1 / -1** | VERIFIED | `ComponentInstance.visibility_raw`; Python names the number |
| `swConstrainedStatus_e` unknown..autosolve-off | **1..7** | VERIFIED (matches the 2026 values feature 003 calibrated against) | `standards.assembly.fully_mated`, `standards.part.sketches_fully_defined` |
| `swDrawingViewTypes_e.swDrawingSheet` | **1** | VERIFIED | Identifies the sheet-format pseudo-view, which is the view the macro scanned for the export-control note |
| `swCustomInfoGetResult_e` cached / not-present / resolved | **0 / 1 / 2** | VERIFIED | Not needed: `GetAll3` returns only present properties, so **absent** is "not in the names list" and **blank** is an empty resolved value (difference m costs zero new interop) |

### R3.2 Assembly and part signals (User Story 1)

| Signal | IR field | Interop member(s) | Status | Runtime question | If the answer is no |
|---|---|---|---|---|---|
| Assembly exploded state | `Document.is_exploded` | `IModelDoc2.IsExploded()` -> `bool`; also `IModelDocExtension.IsExploded(out string)` | **VERIFIED** (both) | Does it report the **reviewed configuration**'s state, and does it answer for a sub-assembly's `ModelDoc2` rather than only the active document? (PROBE-1) | null plus an `assembly_exploded` gap; `standards.assembly.not_exploded` unresolved naming the document |
| Document rebuild-error count | `Document.rebuild_error_count` | `IModelDocExtension.GetWhatsWrongCount`; `GetWhatsWrong` for the messages | **VERIFIED**, and already called elsewhere in this repository (the 004 bridge, the 003 suppress-test) | None outstanding: the macro read exactly this and the repository already reads it on another path | null plus a `rebuild_error_count` gap; the check's document-level half unresolved. Per-feature error codes are **not** substituted, because the document count also covers mate errors no feature carries |
| Mass override | `Document.mass_overridden` | `IModelDocExtension.CreateMassProperty()` -> `MassProperty` (whose declared interface **is** `IMassProperty`) -> `IMassProperty.OverrideMass` (get) | **VERIFIED**, typed end to end: reflection on 32.5.0.48 shows `CreateMassProperty()` returns `SolidWorks.Interop.sldworks.MassProperty`, `MassProperty : IMassProperty`, and `IMassProperty` declares `get_OverrideMass()`. **No runtime COM cast is involved.** `CreateMassProperty2()` returns `object` and `IMassProperty2` exposes no `OverrideMass`, so it is used for mass and volume only, as it is today | None outstanding for the read itself | null plus a `mass_override` gap; `standards.part.material_assigned` unresolved, which is the spec's own edge case. **Fallback**: when the read fails, `mass_overridden` is derived from `IMassProperty2.GetOverrideOptions()` (VERIFIED, already called) being non-zero, with a gap recording that the coarser reading was used - it answers "any of mass, centre of mass or moments is overridden", which is broader than wanted but is a real answer rather than an unresolved row on every part. **The existing `GetOverrideOptions` gap stays**: `PropertyDumper.ReadMass` writes a `GapKind.Unsupported` gap on the document today when any override option is non-zero, and it is neither removed nor duplicated, so the gap set of a `full` or `model_check` dump does not move on this account |
| The configuration the material was read in | `Document.material_configuration` | none - `PropertyDumper.ReadMaterial` already passes the configuration to `IPartDoc.GetMaterialPropertyName2(config, out db)` and discards it | **VERIFIED** (`IPartDoc.GetMaterialPropertyName2`; note it is **not** on `IModelDoc2`, which is what the macro's late-bound call hid) | None | Not applicable: the value is already in hand |
| Component transparency | `ComponentInstance.transparency_raw`, `.has_appearance_override` | `IComponent2.GetMaterialPropertyValues2(1, null)` -> `object` (a `double[9]`); `IComponent2.HasMaterialPropertyValues()` -> `bool` | **VERIFIED** (both) | Which recorded value means transparent, and is slot 7 the transparency slot on this build? (PROBE-2) | null plus a `component_transparency` gap. While `TRANSPARENCY_POLARITY` is `unsettled` the check is unresolved regardless of what was read (SC-014) |
| Component visibility | `ComponentInstance.visibility_raw` | `IComponent2.Visible` (get) -> `int` in `swComponentVisibilityState_e` | **VERIFIED** | What does it return for a component hidden in a display state rather than in the configuration? (PROBE-3) | null plus a `component_visibility` gap; `standards.assembly.not_hidden` unresolved naming the component. `IComponent2.IsHidden(bool)` is VERIFIED and deliberately **not called**: with `ConsiderSuppressed = true` it is the macro's difference-c bug, and with `false` it answers the same question `Visible` does with one fewer state |
| Component pattern origin | `ComponentInstance.is_pattern_instance` (new) beside the existing `pattern_id` | `IComponent2.IsPatternInstance()` -> `bool` | **VERIFIED** | None | null plus a `component_pattern` gap; `standards.assembly.fully_mated` unresolved for that component. The existing `pattern_id` is kept for the **name** of the pattern in the reason text; it is not sufficient on its own, because a null `pattern_id` today conflates "not in a pattern" with "the pattern map was never built" |
| Mate entity reference | `MateEntity.resolution_status` | `IMateEntity2.Reference` (already read by `MateDumper`), `IMateEntity2.ReferenceType2` (already read) | **VERIFIED** | None | The change is to distinguish a **null reference** (`unresolved`) from a **throwing read** (`unknown` plus a gap); today both produce a null `persist_ref` and are indistinguishable. No new interop call |
| Sketch text segments | `SketchInfo.text_segment_count` | `ISketch.GetSketchTextSegments()` -> `object` (array) or empty | **VERIFIED** | Does it answer for a sketch consumed by a hole-wizard feature, and does an empty sketch return an empty array or null? (PROBE-9) | null plus a `sketch_text` gap; `standards.part.sketches_fully_defined` unresolved for that sketch, because the text exemption can then neither be applied nor ruled out |
| Cut-list items | `CutListItem[]` | `IModelDoc2.FirstFeature`, `IFeature.GetNextFeature`, `GetFirstSubFeature`, `GetNextSubFeature`, `GetTypeName2`, `Name`, `GetSpecificFeature2` -> `IBodyFolder`; `IBodyFolder.GetBodyCount()`; `IFeature.ExcludeFromCutList()` | **VERIFIED** (all) | Which type names do the folders carry on 2024 SP5, and does `ExcludeFromCutList` read without activating the body folder? (PROBE-8) | An unreadable exclusion flag is null plus a `cut_list_exclusion` gap and the item is unresolved; a part with no cut-list records is **skipped with a reason**, never a silent pass (difference aa), so a missed folder type shows up on a part the engineer knows is a weldment |

### R3.3 Drawing signals (User Story 2)

There is no drawing extraction today at all, so every row here is new.

| Signal | IR field | Interop member(s) | Status | Runtime question | If the answer is no |
|---|---|---|---|---|---|
| Sheets | `DrawingRecord.sheets[]` | `IDrawingDoc.GetSheetNames()`, `GetSheetCount()`, `Sheet[name]` (indexer); `ISheet.GetName()`, `GetSheetFormatName()` | **VERIFIED** (all) | None for enumeration | A sheet that cannot be reached is a gap naming it; its checks are unresolved for that sheet |
| Views, without activating a sheet | `DrawingSheetRecord.views[]` | `ISheet.GetViews()` -> `object`; `IDrawingDoc.GetViews()` -> `object` (per-sheet arrays); `IView.GetName2()`, `IView.Type` | **VERIFIED** (all) | **Do a non-active sheet's views - and their dimensions, annotations and notes - come back populated without activating the sheet?** (PROBE-7) | A gap **per non-active sheet**, and every affected drawing check unresolved for those sheets. The phase does **not** activate the sheet, and `ActivateSheet` is on the denylist so it cannot (R8) |
| The document a view references | `DrawingView.referenced_document_id`, `.referenced_model_path` | `IView.ReferencedDocument` -> `ModelDoc2`; `IView.GetReferencedModelName()` -> `string` | **VERIFIED** (both) | Does `ReferencedDocument` return null for a model that is referenced but not loaded, while `GetReferencedModelName` still names it? | Both are recorded: the name is what lets the gap **name** the missing model (FR-025), and the null handle is why its checks are unresolved rather than absent |
| Display dimensions and overrides | `DisplayDimensionRecord` | `IView.GetDisplayDimensions()`; `IDisplayDimension.GetOverride()` -> `bool`, `GetOverrideValue()` -> `double`, `GetDimension2(0)` -> `IDimension`, `Type2`, `GetAnnotation()`; `IDimension.Name`, `FullName`, `GetSystemValue3(1, null)` | **VERIFIED** (all) | What unit is `GetOverrideValue` in, and does `Type2` distinguish a length from an angle so the unit can be recorded? (PROBE-6) | `override_value` (and `value`) is recorded as **null** plus a `dimension_unit` gap, and the check is **unresolved** for that dimension - never rendered with a guessed unit. The number is not recorded without a unit: `Quantity.unit` is a required non-nullable `LengthUnit` and `Angle.unit` a required `AngleUnit`, so a null unit would mean changing an existing IR model, which is not an additive change and would move the goldens this feature promises to keep byte-identical. Both fields are typed `Quantity | Angle | null` for the same reason - `Quantity` alone cannot carry an angle. This is difference p, which exists because the macro multiplied by one thousand "blindly assuming the system units are in meters" and then lost its own formatting |
| Dangling annotations | `DrawingAnnotation.is_dangling` | `IView.GetAnnotations()`; `IAnnotation.GetName()`, `GetType()`, `IsDangling()`; `GetAnnotationCount()`, `GetFirstAnnotation3()` / `GetNext3()` for the comparison (**VERIFIED**) | **VERIFIED** (all) | Does `GetName()` return a usable identity for every annotation type, and **does `GetAnnotations()` return the same set the macro's `GetFirstAnnotation3`/`GetNext3` walk returns** - display-dimension annotations included? (PROBE-6) | `name` null plus an `annotation_identity` gap; the annotation is still a subject, identified by its package id, its sheet and its view - which is already more than the macro's unidentifiable "Dangling annotation found." (difference o) |
| Notes | `DrawingNote` | `IView.GetNotes()`; `INote.GetText()`, `GetAnnotation()`; fallback enumeration `IDrawingDoc.GetFirstView()` / `IView.GetNextView()` (**VERIFIED**, and the macro's own walk) | **VERIFIED** (all) | **Does `ISheet.GetViews()` return the sheet-format (type 1) pseudo-view at all**, are its notes reachable as that view's notes, and what does a multi-line note's text look like? (PROBE-5, PROBE-7) | A note whose text could not be read is a gap naming it and `standards.drawing.no_itar_statement` is **unresolved**, because an unread note cannot be shown not to carry the statement. **And a sheet that records no type-1 view is unresolved for that check**, naming the missing sheet-format view: the pseudo-view is the only place the macro ever found the statement, so "zero notes" must not read as "the phrase appears nowhere", which would be a silent pass on a check whose defect is a presence. If PROBE-5/7 show `GetViews()` omits it, the phase enumerates views with `GetFirstView`/`GetNextView` instead - still activating nothing |
| Revision tables | `RevisionTable`, `RevisionTableRow` | **Enumeration**: `IView.GetTableAnnotations()` filtered on `ITableAnnotation.Type == swTableAnnotationType_e.swTableAnnotation_RevisionBlock` (3) (**VERIFIED**; `GetFirstTableAnnotation` also present), because `ISheet.RevisionTable` is **single-valued** (`get_RevisionTable` returns one `RevisionTableAnnotation`) and a sheet carrying two tables would yield one record and silently lose the other - a silent miss in the one check whose purpose is coverage. `ISheet.RevisionTable` is still read as a **cross-check** (**VERIFIED**); `IRevisionTableAnnotation.CurrentRevision` (**VERIFIED**); `ITableAnnotation.RowCount`, `ColumnCount`, `Text[row, col]`, `DisplayedText[row, col]`, `TotalRowCount`, `TotalColumnCount` (**VERIFIED**) | **VERIFIED** members, **UNVERIFIED** composition: `IRevisionTableAnnotation` declares **no base interface** in this interop, so reading cells requires a runtime COM cast of the revision table to `ITableAnnotation` | Does the cast succeed, what does `CurrentRevision` return under EPDM, and which row is the header? (PROBE-4) | The dumper records **both** readings: `current_revision_raw` from `CurrentRevision`, and the rows when the cast succeeds. A failed cast is a gap naming the table and `standards.drawing.revision_matches` is unresolved. The macro's author recorded that `CurrentRevision` "is pulling an empty string ... Possibly due to EPDM fighting for the current revision", which is exactly why both are recorded and why the finding names both values **with their source** rather than letting the dumper pick |
| Drawing custom properties | `Document.custom_properties` for the drawing | `IModelDocExtension.CustomPropertyManager("")`, `ICustomPropertyManager.GetAll3(...)` | **VERIFIED**, and already called by `PropertyDumper` | None | Existing behaviour |
| Persistent references for the new entity kinds | `persist_ref` / `persist_ref_scope` on every new record | `IModelDocExtension.GetPersistReference3(object)`, `GetPersistReferenceCount3(object)` | **VERIFIED** (generic, object-typed) | **Which of sheet, view, display dimension, annotation, revision-table row, note and cut-list item does SOLIDWORKS actually give a reference for?** (PROBE-10) | `persist_ref` is null, and the record's package id is its identity. A null `persist_ref` is the statement FR-026 requires - a consumer can tell a persistent reference from a within-dump identity - and the page renders **no** Show control for such a subject rather than one that always fails |

### R3.4 Members deliberately not called

| Member | Why not |
|---|---|
| `IModelDoc2.ForceRebuild3` | Difference g. Stays denied; nothing here rebuilds |
| `IDrawingDoc.ActivateSheet`, `ActivateView` | R2.7. A display-state mutation; joins the denylist |
| `IComponent2.IsHidden(bool)` | With `ConsiderSuppressed = true` it is the macro's difference-c bug; `Visible` answers the question with one fewer conflated state |
| `IAssemblyDoc.GetComponents(false)` | The package's component tree already carries every instance at every level, with suppression, transform and configuration; re-walking it would be a second traversal that could disagree with the first |
| `IFeature.GetTypeName2` against a nine-name mate whitelist | Difference r. The whitelist was the macro's workaround for `GetNextSubFeature` returning derived hole patterns; `MateDumper` already records mates as mates |
| `IAssemblyDoc.FeatureByName` + `IFeature.GetParents` for pattern origin | Difference t. `IsPatternInstance()` answers it in one call and cannot raise the macro's error 91 (limitation L5) |
| `ICustomPropertyManager.Get4` / `Get5` / `Get6` | `GetAll3` is already called once per document and distinguishes absent from blank by itself; a per-property call would be four extra interop calls per document for no new information |

---

## R4. The workstation probes

Ten, exactly the ten the spec's Assumptions name. `swreview-extract probe standards --doc
<document>` prints all ten in one read-only run under the read-only guard; the answers are
pasted into the **Answer** column on the test day and the rules that depend on them are
trusted only then. The documents each probe needs are named in `quickstart.md`.

| # | Probe | What it prints | What it settles | Answer (test day) |
|---|---|---|---|---|
| PROBE-1 | Assembly exploded state | `IModelDoc2.IsExploded()` and `IModelDocExtension.IsExploded(out name)` for the open assembly, for the same assembly in a second configuration, and for each sub-assembly's `ModelDoc2` | Which interface answers on the pilot build; whether the answer is per-configuration; whether a sub-assembly document answers at all | *(unrecorded)* |
| PROBE-2 | Transparency-override polarity | `HasMaterialPropertyValues()` and all nine slots of `GetMaterialPropertyValues2(1, null)` for a component the engineer has made **visibly transparent**, one they have given an opaque appearance override, and one with no override | Which recorded value means transparent, and whether slot 7 is the transparency slot on this build | *(unrecorded)* |
| PROBE-3 | Component visibility | `Visible` and `GetVisibility(1, null)` for a visible component, a hidden one, a suppressed one, and one hidden in a display state | Which read answers "hidden" without conflating suppression; what a display-state hide looks like | *(unrecorded)* |
| PROBE-4 | Revision-table read | Per sheet: every table from `IView.GetTableAnnotations()` with its `ITableAnnotation.Type`, **counted against** `ISheet.RevisionTable` (which returns at most one); whether casting a revision table to `ITableAnnotation` succeeds; `CurrentRevision`; `RowCount`, `ColumnCount`, `TotalRowCount` and every cell of `Text` and `DisplayedText` | Whether the cells are reachable at all; **whether a sheet can carry more than one revision table and whether the filtered walk finds them all**; what `CurrentRevision` returns under EPDM; which row is the header and whether the header is inside `RowCount` or outside it | *(unrecorded)* |
| PROBE-5 | Note walk | For every sheet and every view, the view type and the text of every note from `GetNotes()`, with the sheet-format pseudo-view (`Type == 1`) marked - **and, per sheet, whether a type-1 view appears in `ISheet.GetViews()` at all**, compared against the `IDrawingDoc.GetFirstView()` / `IView.GetNextView()` walk | **Whether the type-1 pseudo-view is returned by `GetViews()`**, which is what decides whether the fallback enumeration is needed; whether the sheet format's notes are reachable as that view's notes; what a multi-line note's text looks like | *(unrecorded)* |
| PROBE-6 | Drawing-view and annotation walk | Per view: `GetName2`, `Type`, `GetReferencedModelName`, whether `ReferencedDocument` is non-null, the count and identity of `GetAnnotations()` (name, type, `IsDangling`) **compared line for line against `GetAnnotationCount()` and the `GetFirstAnnotation3()`/`GetNext3()` walk, with the types of any annotation present in one and not the other listed**, and per display dimension `GetOverride`, `GetOverrideValue`, `Type2`, `GetDimension2(0).FullName` and `GetSystemValue3(1, null)` | View enumeration; annotation identity; **whether `GetAnnotations()` returns the same set the macro's walk did, since a smaller set is a silent under-report rather than an unresolved row (SC-016)**; the dangling flag; the override flag and value; **the unit the override value is reported in** | *(unrecorded)* |
| PROBE-7 | Non-active sheet enumeration | The same walk as PROBE-6, run over **every** sheet while sheet 1 stays active, with the counts per sheet compared against a second run in which the engineer activates each sheet by hand first | Whether a non-active sheet's views, dimensions, annotations, revision tables and notes come back **without** activating it, and **whether the type-1 sheet-format pseudo-view is among the views returned for each sheet**. FR-024's fallback and the export-control check's unresolved rule both depend on the answer | *(unrecorded)* |
| PROBE-8 | Cut-list walk | For a weldment part and a sheet-metal part: every feature's `GetTypeName2` and `Name` at every depth, with `GetSpecificFeature2` object type, `GetBodyCount()` and `ExcludeFromCutList()` printed for each body folder | Which type names the cut-list folders carry on 2024 SP5; whether the exclusion flag reads without activating a body folder | *(unrecorded)* |
| PROBE-9 | Sketch text-segment read | `GetSketchTextSegments()` for a plain sketch, a sketch containing text, an empty sketch, and a sketch consumed by a hole-wizard feature - printing null, empty and length distinctly | Whether text segments are readable, including inside a hole-wizard feature; whether empty is null or a zero-length array | *(unrecorded)* |
| PROBE-10 | Persistent references for the new entity kinds | `GetPersistReference3` and `GetPersistReferenceCount3` for one sheet, one view, one display dimension, one annotation, one note, one revision table and one cut-list item body folder, printing byte length or the failure | Which of the seven kinds SOLIDWORKS gives a persistent reference for - and therefore which finding subjects the page renders a Show control for (FR-026, FR-031) | *(unrecorded)* |

---

## R5. The values the macro carried

> **No company value is written down anywhere in this repository**, this section included.
> The repository is public, so the concrete values the macro carried - the vault root, the
> library folder names, the data-card property names, the part-number convention, the
> revision-table conventions and the export-control phrase - were handed to the owner
> separately as a ready-to-use `standards.yaml` on 2026-09-17, to be placed at the path
> `contracts/profile.md` names on the workstation (FR-001, SC-005). What this section
> records is the **shape** of each value and which macro constant it came from, so a reader
> can see that the profile covers everything the macro hard-coded. The constant ids (C1 to
> C43) refer to the reverse-engineering table kept with the owner's copy of the macro, which
> is likewise not in this repository. The macro's own file names are omitted for the same
> reason; `plan.md` says "the owner's release-checklist macro".

Grouped by the profile field each one feeds. `contracts/profile.md` is the schema; the
placeholder example in `config/standards.example.yaml` uses fictional values in every field.

| Profile field | Shape of the value the macro carried | Macro constant | Note |
|---|---|---|---|
| `vault_root` | one absolute vault root, the common prefix of every path below | C1-C21 | Every path below is written relative to it in the profile |
| `library.skip_prefixes` (part documents only) | three library subfolders (adhesives, electrical, and one hardware family the description document does not mention) | C3, C4, C5 | The third is in the code and not in the document. Assemblies under these prefixes were still graded (FR-006) |
| `library.sketch_exempt_prefixes` | the whole library folder | C2 | Exempts every library part from the sketch check, and nothing else |
| `library.one_mate_prefixes` | three flat-head-cap-screw subfolders | C6, C7, C8 | Flat-head cap screws |
| `library.two_mate_prefixes` | thirteen entries: eleven library hardware subfolders, one vendor folder, and **one single part file** under the jobs tree | C9-C21 | The catch-all fasteners folder is on this list while the FHCS subfolders are on the one-mate list; the macro tested the one-mate list first, and the profile keeps that precedence (FR-001) |
| `data_card.properties` | four property names: a company-suffixed part-number property, a description, a finish and a material | C22-C25 | Read from the configuration-independent property tab |
| `part_number.pattern` | three digits, a hyphen, five digits, then `.SLD` and any three characters | C29 | `#` is one digit, `?` is one character - the macro's own vocabulary, kept (FR-001). Matched against the **file name including its extension**, not the window title (difference l) |
| `revision.property` | the vault-written revision property name | C26 | An ordinary custom property that EPDM writes into the file; no vault API is used anywhere |
| `revision.initial` | a one-character placeholder revision | C32 | What a table holding only its header row means |
| `revision.header_text` | the header row's identifying word | C31 | The first cell of the header row |
| `revision.cell` | last row, column 0 | C33 | In the profile a **row selector counted from the end** and a **column index**, so a different drawing template does not silently read the wrong cell (FR-001) |
| `material.configuration` | the SOLIDWORKS default configuration name | C28 | The configuration whose material is inspected |
| `export_control.phrase` | one hyphenated two-word export-control phrase | C30 | Presence is the defect; matched case-insensitively as a substring |
| `general_tolerance.linear` | not carried by the macro | none | Profile version 2 (feature 010 research R2.19): the title block's general tolerance by decimal places, owner answer 2026-09-23; the owner supplies the bands with the regenerated profile |
| `general_tolerance.angular_deg` | not carried by the macro | none | Profile version 2: the title block's general angular tolerance, or null when the company declares none |
| `hygiene.part_number_property` | not carried by the macro | none | Profile version 2: the property feature 010's hygiene checks compare with the file name |
| `hygiene.description_property` | not carried by the macro | none | Profile version 2: the property two documents must not share, read by feature 010's hygiene checks |
| `drawing.sheet_formats` | not carried by the macro | none | Profile version 3 (feature 011, 2026-09-23): the sheet format names a drawing's sheets may use, compared by feature 011's conformance finding; the owner supplies them with the version 3 profile |
| `drawing.drafting_standard` | not carried by the macro | none | Profile version 3: the drawing's dimensioning standard name, compared ignoring case and surrounding spaces |
| `drawing.projection` | not carried by the macro | none | Profile version 3: an enumeration (`first_angle`, `third_angle` or empty), not a secret; every shipped profile carries a different member |
| `drawing.dimension_unit` | not carried by the macro | none | Profile version 3: an enumeration (`mm`, `in` or empty), not a secret; the unit `general_tolerance`'s decimal places are counted in, and every shipped profile carries a different member |
| `drawing.drawing_template` | not carried by the macro | none | Profile version 3: recorded for drawing creation (feature 012) and not compared |
| `drawing.bom_template` | not carried by the macro | none | Profile version 3: recorded for drawing creation (feature 012) and not compared |
**Not company-specific, and therefore not in the profile**: the configuration-independent
property tab (C27, the empty configuration name), the cut-list item name prefix (C34 -
replaced by structural identification, difference bb), the document-kind extensions (C35 -
replaced by the package's recorded kind, difference k), the mate type-name whitelist (C36 -
not reproduced, difference r), the pattern feature type names (C37 - replaced by
`IsPatternInstance`, difference t), the sketch and hole-wizard feature type names (C38), the
mate-group feature type name (C39), the body-folder type names (C40 - PROBE-8 records what
they are on 2024 SP5), the metres-to-millimetres conversion and format string (C41 - replaced
by recording the unit, difference p), the transparency slot index (C42 - PROBE-2), and the
result window's minimum size (C43).

**No EPDM API is used**, because the macro uses none: there is no `EdmLib`, `IEdmVault5`,
`IEdmFile5` or vault-variable call anywhere in it. Every "EPDM revision" is the ordinary
SOLIDWORKS custom property the vault writes into the file, which is what the repository
already reads (`ManifestBuilder`).

---

## R6. The profile: schema shape and why each field exists

The full schema is `contracts/profile.md`; this records the three shape decisions.

1. **Four prefix lists, not one with a kind tag.** The skip list, the sketch-exempt list, the
   one-mate list and the two-mate list answer four different questions about the same path,
   and a path may legitimately be in more than one. One list with a per-entry kind would make
   "which rule wins" a question at all, and the macro's own accident (the one-mate list winning
   because it was tested first) is the evidence that it is a question nobody should have to
   answer. Four lists, matched **independently**, longest match within each (FR-006).
2. **The revision-table cell is a row selector and a column index**, not "the last row".
   The macro hard-codes `Text(RowCount - 1, 0)`, which reads the wrong cell the moment a
   drawing template puts revisions in a different order or the header at the bottom. Making it
   two profile numbers costs one line in the schema and removes a silent wrong answer.
3. **Empty lists and empty strings are valid, and what "empty" means depends on what the
   setting does.** A setting that **selects what to check** - `data_card.properties`,
   `part_number.pattern`, `revision.property`, `export_control.phrase` - leaves nothing to
   test when it is empty, so its check reports **skipped** coverage naming the empty setting,
   with the skipped count on the headline (FR-032). An unconfigured profile therefore never
   silently **passes** a document, and the owner can adopt the tab one selecting setting at a
   time. A list that **exempts or reclassifies** - the four `library.*` lists - exempts and
   reclassifies nothing when it is empty, so its checks **run on every document they apply
   to**; an empty exemption list is a statement that nothing is exempt, and treating it as a
   skip would let an unconfigured profile silently **grade nothing**, which is the same
   failure in the other direction.

**Where the file lives**: a setting, `StandardsProfilePath`, with the documented default
`%LOCALAPPDATA%\SwReview\standards.yaml`. That directory is per-user, outside every repository
and outside the vault, and it is where this add-in's other user settings already live. The
`--profile` argument overrides it for the command line, which is what lets CI grade a package
against a fictional profile fixture.

---

## R7. Generalizing feature 003's machinery: what moves and what does not

| Today | After | Why |
|---|---|---|
| `checks/rms/results.py`: `RuleOutcome`, `RuleResult` and its six constructors | `checks/rules/results.py`, re-exported from the old path | **Not family-neutral today**, in three ways that the move has to answer rather than assume: it holds `HIGH_SEVERITY_RULE_PREFIX = "rms.refs."` and `HIGH_SEVERITY_RULES`, its `severity_of(rule: RmsRule)` maps on those ids, and it **imports `RmsRule`**. What moves is `RuleOutcome`, `RuleResult`, the outcome invariant and the six constructors; what becomes a fact on `CheckFamily` is the **severity vocabulary** (`{"fail","warn"}` for rms, `{"error","warning"}` here - they do not share one, and `_STATUS_BY_OUTCOME` keys on the outcome names), its map to a `FindingStatus` and a `Severity`, and the family's **high-severity subject test** (an id set or a predicate). `checks/rules/results.py` imports **no** family's rule type: importing `RmsRule` there would be the `checks/standards` -> `checks/rms` dependency R2.6 rejects, in the other direction. This is the **fourth** generalized hard-coding, beside the summary check id, the scope vocabulary and the rules version |
| `checks/rms/report.py`: `report_results`, the subject builder, the coverage aggregation | `checks/rules/report.py` taking a `CheckFamily` | Coupled to `rms` in **five** places, not two, and three of them are behaviour rather than a name. Each is decided explicitly: (1) `SUMMARY_CHECK = "modeling.resilience"` becomes `family.summary_check` (`"standards.release"` here). (2) `_groups_by_document` and the RMS feature **`group` stamp** on every subject (via `checks/rms/groups.py` and the calibrated type table) become an **optional per-family subject decorator**, default none. (3) `_write_unknown_types`, which reads that type table, and (4) `_write_undispatched`, which iterates `coverage_only()` over the RMS catalogue and special-cases `rms.assembly.subassemblies`, become an **optional per-family "extra coverage" step supplied by the family module** - not by the frozen `CheckFamily`, which carries facts and no callables beyond the maps above. (5) `_split_by_reportability` turns a finding-shaped result whose document has no `ComponentInstance` into unresolved coverage, and a **drawing** has none, so it must admit a document-scoped result (empty `component_ids`, bound by `document_id`) and `_record` must build one - with a regression that an rms result with no instance still lands in unresolved coverage. Consequence: `checks/rms/report.py` keeps real logic (2), (3) and (4) and is **not** a thin shim |
| `checks/rms/registry.py`: `RmsRule`, `bind`, `by_scope`, `evaluable`, `coverage_only`, `RULES_VERSION`, `RuleScope` | `checks/rules/registry.py` with `Rule`, and `RuleScope` becoming a per-family `frozenset[str]` on `CheckFamily`; `RULES_VERSION` becoming `family.rules_version` | The three hard-codings the coverage audit named. `RULES` (the catalogue of 34 `rms.*` ids) stays in `checks/rms` where it belongs |
| `checks/rms/run.py`: `carry_forward`, the run-folder creation, the tool dispatch through `ToolRegistry` with a `SessionSink`, `_write_check_record`, `read_rms_check` | `checks/rules/run.py` with the family in the record and in the dispatch | The skeleton is identical; what differs is which tools are dispatched, which scopes exist and which family the record names. **One rename goes with the move**: `checks/rms/run.py` calls its three rule **scopes** "families" throughout (`for family in runs:`, `_dispatch(..., family: RmsScope, ...)`, "Run one rule family as one recorded call"), and `family` is about to mean rms-versus-standards in the same file. The rms local and parameter are renamed to `scope`, which is what `RmsScope` and `RULES.scope` already call it. The rename is internal to `run.py`, so the "every rms test passes unedited" gate still holds; it is named in the move task so it is not discovered |
| `checks/rms/{part,assembly,equations,groups,plan,grade}.py` | unchanged | RMS-specific by nature |
| `report/session.py`, `tools/registry.py`, `tools/context.py`, `exceptions.py`'s machinery | unchanged (`exceptions.py` gains one optional field) | Already family-neutral |

`CheckFamily` carries: `name` (`"rms"` / `"standards"`), `summary_check`
(`"modeling.resilience"` / `"standards.release"`), `rules_version`, `scopes` (the scope
vocabulary), `tools` (scope to tool name), `check_file_family` (the value written into
`check.json`), `severities` (the family's severity vocabulary), `status_by_severity` (its map to
a `FindingStatus` and a `Severity`), `high_severity` (the family's own test for a `high`
subject) and the per-family waiver **status labels** the command line prints. It is a frozen
dataclass with no behaviour - explicit over clever: a family is a list of facts, not a base
class with hooks. The two **optional callables** the report layer needs - a subject decorator
and an extra-coverage step - are supplied by the family **module** at registration, not carried
on the frozen descriptor, so the descriptor stays data.

**The gate**: after the move, every `checks/rms` unit test and every `rms-*` golden passes
**with no edits**. Its task contains none of this feature's own code.

---

## R8. Read-only: the members that join the denylist

`ReadOnlyGuard` is a denylist, and it grows the moment a phase touches an API family that can
write - feature 003's rule, followed here. These are the mutating and view-changing members
that sit beside the reads the new phases perform; none of them is called by this feature, and
adding them is a **narrowing**, so no constitution exception arises and the SC-003-style gate
audit is unaffected.

**Bare member names.** `ReadOnlyGuard.DeniedMemberSet` stores unqualified names, matched
case-insensitively, because `SwGate.Call("<member>")` names them that way. The interface
qualifiers in the table below are for the reader; the guard entry is the bare name, and
`SetText` is therefore **one** entry covering both `IDisplayDimension.SetText` and
`INote.SetText`.

**This table is the count.** No other file in this package states how many members are added;
they cite R8 instead, and the guard test derives its expected set from **this table's
membership** rather than from a hand-typed number, so a future row cannot silently leave a
member ungated.

| Member | The family it guards |
|---|---|
| `IDrawingDoc.ActivateSheet`, `IDrawingDoc.ActivateView` | Sheet and view activation - the macro's side effect, and the one SC-010 asserts is absent from the gate log |
| `IAssemblyDoc.ShowExploded`, `ShowExploded2`, `CreateExplodedView`, `AutoExplode` | Exploded-state writes, beside the exploded read |
| `IComponent2.SetVisibility`, `SetVisibilityInAsmDisplayStates`, `set_Visible` | Visibility writes, beside the visibility read |
| `IComponent2.SetMaterialPropertyValues2`, `RemoveMaterialProperty`, `RemoveMaterialProperty2` | Appearance writes, beside the transparency read |
| `ITableAnnotation.set_Text`, `ITableAnnotation.set_Text2` | Table-cell writes, beside the revision-table read |
| `IRevisionTableAnnotation.AddRevision`, `DeleteRevision` | Revision writes |
| `ISheet.InsertRevisionTable`, `InsertRevisionTable2` | Revision-table creation |
| `IBodyFolder.SetAutomaticCutList`, `UpdateCutList`, `SortCutList`, `SetAutomaticUpdate` | Cut-list writes, beside the cut-list read |
| `IMassProperty.set_OverrideMass`, `SetOverrideMassValue` | Mass-override writes, beside the mass-override read |
| `IDisplayDimension.SetOverride`, `IDisplayDimension.SetText` | Display-dimension writes, beside the new `GetOverride` / `GetOverrideValue` reads |
| `IDimension.SetSystemValue3`, `set_SystemValue`, `set_Value` | Dimension-value writes, beside the new `GetSystemValue3` read |
| `INote.SetText` | Note writes, beside the new `GetText` read (same bare name as the display-dimension entry) |
| `IAnnotation.SetName` | Annotation-identity writes, beside the new `GetName` read |
| `IFeature.set_ExcludeFromCutList` | Cut-list exclusion writes, beside the new `ExcludeFromCutList` read |

**Thirty-one distinct bare member names** are added by this table (`SetText` counted once).
All thirty-one are VERIFIED present on `SolidWorks.Interop.sldworks` 32.5.0.48 by reflection.
`ForceRebuild3` and `ForceRebuildAll` are already denied by feature 003 and stay denied.

**Adding any member breaks an existing feature 004 test, and that is named work.**
`extractor/SwReview.Extractor.Tests/RemodelGuardTests.cs` asserts **set equality** on the whole
denied surface (`ExpectedDeniedMembers` at :57, asserted at :341-352 with the message
"re-read contracts/guard-allowlist.md before touching the stage-1 allowlist"). The task that
grows the denylist updates `ExpectedDeniedMembers` and feature 004's
`specs/004-resilient-remodeler/contracts/guard-allowlist.md` **in the same commit**; both are
named in `plan.md`'s file list.

---

## R9. The drawing phase

**Shape**: `DrawingDumper : IDrawingSource` reads one drawing document into one
`DrawingRecord`; `DrawingTraversal` is a pure class that decides sheet, view and entity order
and allocates package ids, with no interop in its signature, so the ordering rules are unit
tested without a seat. The phase runs for a drawing root under the `Standards` profile and
under `Full`; it does not run for a part or assembly root, and the standing gap the extractor
writes today ("drawing sheets come from the PDF ingest") becomes **conditional** on the phase
not having run, naming the profile that skipped it (FR-024).

**Coexistence with the PDF ingest.** `DrawingSheet` already exists in the IR and is filled
only by the Python PDF path (PyMuPDF, with a `parse_status` and a `parser` name and a
deliberately empty `views` list). The native phase does **not** reuse that model: a native
sheet has no `page`, no `parse_status` and no parser, and filling those in would be a fiction.
Instead the new records live in `EvidencePackage.drawing_records[]` (a new member beside the PDF ingest's `drawings[]`, which keeps its `DrawingSheet` rows and its always-written form), each **sheet record** carrying
`source: "native"` (the per-sheet half of FR-024, beside the constant on `DrawingRecord`), and
the existing `DrawingSheet` gains an optional `source` that the ingest stamps `"pdf_ingest"` -
in the Python model **and in the C# DTO**, which has no such property today and whose serializer
refuses unknown members, so without it an ingest-written package would throw wherever the add-in
or the reuse path reads one. The four drawing checks evaluate **native** sheets only; a drawing
with no native sheet is unresolved coverage naming the source, and a drawing whose sheets came
from both paths is graded on its native sheets with an unresolved row naming the ingested ones,
because a parser with known limits may not produce a demonstrated finding (FR-024). The alternative - one array
with a discriminator - was rejected because it would make three of `DrawingSheet`'s required
fields meaningless for half its rows.

**Identity.** Every new record carries a package id in the existing style (`dsh:NNNN`,
`dvw:NNNN`, `ddm:NNNN`, `dan:NNNN`, `drv:NNNN`, `dnt:NNNN`, `cut:NNNN`) allocated in traversal
order, plus `persist_ref` and `persist_ref_scope` when SOLIDWORKS gives one. A null
`persist_ref` is the statement FR-026 requires: the package id is a within-dump identity, and
the page renders no Show control for such a subject. PROBE-10 records which kinds get one.

**The drawing-rooted traversal.** `ComponentTreeDumper` gains a drawing branch: for each
document a view references and that is loaded, it walks that document's component tree exactly
as it walks an assembly root today, producing one subtree per referenced model under a
synthesized forest root. `PackageWriter.DocumentPaths` gains the drawing's own path and the
referenced model paths; `BuildDesign` populates `design.drawing_document_ids`, which exists in
the IR today and has never been set. `design.root_assembly_document_id` holds the **root
document's** id whatever its kind - already true for a part opened alone since feature 003 -
and for a drawing root it is the drawing's id. The field's name is a misnomer that feature 003
made and this feature does not rename, because renaming a required IR field is a breaking
change and the value is unambiguous.

---

## R10. Findings, coverage, waivers and the run folder

- **Findings** reuse feature 001's `Finding` contract **unchanged**. Subjects are inputs on
  the finding *and* a structured array beside it in the route's response keyed by finding id,
  exactly as feature 003 does, so the page acts on a subject without parsing a display string
  (FR-031). The profile is identified on every finding by **path and content hash** in
  `coverage_limits`, never by value.
- **Coverage** is one aggregated item per check per bucket per run, replaced rather than
  duplicated on a re-run, through the existing `ToolContext.replace_coverage`. All sixteen
  checks appear on every run; where one line must stand for a check, the worst bucket decides
  it in the order unresolved, failed, warned, skipped, checked, out of scope, so no summary
  line claims coverage that is partly unknown (FR-033).
- **Waivers** are `ReviewException`s with one additive field: `document_id`, optional with a
  default so every existing record loads. It exists because a **drawing** finding has no
  component instances, and an exception with no bindings would be the blanket exclusion the
  constitution prohibits. `fingerprint_kind` gains `"standards"`, hashing every input the
  check read for that document, so a newly appearing subject re-opens the finding for
  re-review rather than being silenced (FR-041, SC-008).
- **The run folder** is `<run_root>/<yyyyMMdd-HHmmss>-<doc>-standards`, created by
  `RunFolders.CreateForStandards` beside `CreateForCheck`, registered as the pane's latest run
  so `entity.show` and the Ask tab read the same evidence, holding `package.json`,
  `exceptions.json`, `session.json`, `report.md` and `check.json`.
- **The newest-run scan is new work.** `ModelCheckHost.LatestCheck` is in-process state today -
  set by `TrackCheck`, nulled in `Dispose` - and nothing in the add-in enumerates the run root
  at all, so a check cannot be read back after a restart as things stand. This feature **adds**
  `RunFolders.NewestCheckFolder(runRoot, suffix)`, called on `init` by `StandardsHost`
  (`-standards`) and by `ModelCheckHost` (`-check`). Given that scan, the suffix is how each
  host finds its **own** newest run from the folder names alone, without opening a file in every
  sibling folder; the `family` field in `check.json` is how the backend answers a read by id for
  a folder it was handed. Two mechanisms, two questions; the alternative (one suffix plus a file
  read per sibling on every `init`) is rejected because `init` runs on every tab activation.
