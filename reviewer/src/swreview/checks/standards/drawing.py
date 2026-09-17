"""The four drawing-scope checks (T066).

One pure function per check of `specs/006-standards-check/contracts/rules.md`, each
decorated `@bind("<check id>")` and returning `list[RuleResult]`, exactly as `assembly.py`
and `part.py` do. What is different here is the evidence: a drawing is graded from the
**native** drawing record (`EvidencePackage.drawing_records`), and the PDF ingest's
`drawings[]` sheets are not evidence these checks may fail a drawing on.

Five rules shape the module, and the first three are stated **once**, in `_evaluate`,
because `contracts/rules.md` states them once for all four checks rather than per check:

- **native sheets only, decided per sheet** (FR-024). A drawing with no native sheet is
  `unresolved` for all four checks naming the evidence source - a parser with known limits
  may not produce a demonstrated finding - and a drawing whose sheets came from **both**
  paths is graded on its native sheets and carries one additional `unresolved` row per
  check naming the PDF-ingested ones, so a mixed drawing is never reported as fully checked
  and never refused outright;
- **every sheet is read** (difference q), and **no sheet is activated to read it**
  (FR-044). A sheet whose contents the dump could not enumerate carries a
  `drawing_sheet_views` gap, and every check is `unresolved` for that sheet and grades
  nothing on it - the alternative, grading half a sheet, would report a drawing as checked
  on evidence that is known to be incomplete;
- **one finding per drawing** (FR-003), carrying every subject that failed the check. Six
  overridden dimensions are six subjects inside one finding and one error, not six errors -
  which is the macro's own inflation (SC-006);
- **a reading that was not made is unresolved**, naming the gap the dump recorded beside it
  (FR-029). An unread flag, an unread note and an unread cell are each a gap; **an unread
  cell is never an empty string**, because an empty revision cell is a real mismatch and
  confusing the two would turn a defect into a pass;
- **an empty profile setting that selects what to check is a skip**, never a pass
  (`revision.property`, `export_control.phrase`), phrased the way `report.py`'s
  `EMPTY_SETTING` reads it so the headline can count it (FR-032).

FR-005's document-evidence half is asked for here as it is everywhere else, and answers
`None` for every drawing: a drawing is never instantiated as a component, so it is never
reached only through unresolved instances. It is asked rather than assumed, so that the one
condition lives in `results.py` for all sixteen checks.

The subject constructors for the drawing rows live here rather than in `results.py`,
following that module's own rule: what all four evaluators need lives there, and a
dimension, an annotation and a note are this scope's alone. Their `type_name` labels are
the ones `checks/standards/report.py`'s `KIND_BY_TYPE_NAME` holds, which is what turns them
into a `Subject.kind`.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from swreview.checks.standards.document import read_card
from swreview.checks.standards.profile import StandardsProfile
from swreview.checks.standards.registry import RULES, StandardsRule, bind
from swreview.checks.standards.results import (
    RuleResult,
    Subject,
    document_evidence_unresolved,
    document_subject,
    find_gap,
    finding,
    gap_note,
    outcome,
    passed,
    properties_gap,
    properties_gap_note,
    skipped,
    subject_reasons,
    unresolved,
)
from swreview.checks.standards.traversal import CheckedDocument
from swreview.ir.models import (
    Angle,
    DisplayDimensionRecord,
    Document,
    DrawingAnnotation,
    DrawingNote,
    DrawingRecord,
    DrawingSheet,
    DrawingSheetRecord,
    DrawingView,
    EvidencePackage,
    Quantity,
    RevisionTable,
)

__all__ = [
    "ANNOTATION_TYPE_NAMES",
    "SHEET_FORMAT_VIEW",
    "Drawing",
    "annotations_not_dangling",
    "dimensions_not_overridden",
    "drawing_scope",
    "evaluate_drawing",
    "no_itar_statement",
    "revision_matches",
]

SCOPE = "drawing"

DIMENSIONS_NOT_OVERRIDDEN = "standards.drawing.dimensions_not_overridden"
ANNOTATIONS_NOT_DANGLING = "standards.drawing.annotations_not_dangling"
REVISION_MATCHES = "standards.drawing.revision_matches"
NO_ITAR_STATEMENT = "standards.drawing.no_itar_statement"

SHEET_FORMAT_VIEW = 1
"""`swDrawingViewTypes_e` 1, the sheet-format pseudo-view (research R3.3, VERIFIED).

The only place the macro ever found the export-control statement, which is why a sheet that
records no view of this type makes `standards.drawing.no_itar_statement` unresolved for that
sheet rather than checked: "zero notes" must not read as "the phrase appears nowhere" on the
one check whose defect is a presence.
"""

ANNOTATION_TYPE_NAMES: dict[int, str] = {4: "display dimension", 6: "note"}
"""The two `swAnnotationType_e` values `research.md` R3.3 records as VERIFIED.

Any other type is named by its number alone: a made-up name for a constant this build has
not verified would be worse than the number an engineer can look up.
"""

NO_DIMENSIONS = "the drawing's native sheets record no display dimension"
NO_ANNOTATIONS = "the drawing's native sheets record no annotation"
NO_NOTES = (
    "the drawing's native sheets record no note, and every one of them recorded a "
    "sheet-format view, so the absence of notes is a real absence rather than an unread one"
)

NO_NATIVE_SHEET = (
    "{name} carries no natively dumped sheet, so these checks have no evidence to grade: "
    "the drawing checks read native sheets only, because a parser with known limits may not "
    "produce a demonstrated finding (FR-024)"
)
INGESTED_SHEETS = (
    "{name} also carries {count} sheet(s) of PDF-ingested evidence ({sheets}), which this "
    "check does not grade: it is graded on its native sheets alone, so this drawing is not "
    "reported as fully checked (FR-024)"
)
NON_ENUMERABLE_SHEET = (
    "the contents of sheet {sheet} of {name} could not be enumerated, so nothing on it was "
    "graded; the sheet was not activated to read it (FR-044); {why}"
)

CELL = "the cell revision.cell names (row {row} from the end, column {column})"
"""How every revision reading says where it was read from, so a surprising answer can be
traced to the profile line that selected it rather than to this module."""


# --- the subjects the drawing checks name ---------------------------------------------------


def _label(sheet: DrawingSheetRecord, view: DrawingView, name: str | None, row_id: str) -> str:
    """One drawing row, located: its sheet, its view and its own name or package id."""
    return f"{sheet.name}/{view.name or view.id}/{name or row_id}"


SCOPE_IS_A_DOCUMENT = """A subject's `persist_ref_scope` is the **document** its reference
resolves against - that is what `Dump/DrawingDumper` writes (`ScopedPersistRef.ScopeDocumentId`)
and what the report layer turns into a `SourceRef.document_id` and looks up in the manifest.
So a record whose scope the dump did not record falls back to the drawing document, never to
its sheet: a sheet id there is not a document any manifest entry names, and a finding cannot
cite a document it cannot get the version, revision and configuration of."""


def dimension_subject(
    dimension: DisplayDimensionRecord,
    sheet: DrawingSheetRecord,
    view: DrawingView,
    configuration: str,
    document_id: str,
) -> Subject:
    """One display dimension, labelled by the sheet and view it was read from."""
    return Subject(
        id=dimension.id,
        name=_label(sheet, view, dimension.name, dimension.id),
        type_name="dimension",
        persist_ref=dimension.persist_ref,
        persist_ref_scope=dimension.persist_ref_scope or document_id,
        suppressed=False,
        configuration=configuration,
    )


def annotation_subject(
    annotation: DrawingAnnotation,
    sheet: DrawingSheetRecord,
    view: DrawingView,
    configuration: str,
    document_id: str,
) -> Subject:
    """One annotation of any type; an unnamed one is identified by its package id."""
    return Subject(
        id=annotation.id,
        name=_label(sheet, view, annotation.name, annotation.id),
        type_name="annotation",
        persist_ref=annotation.persist_ref,
        persist_ref_scope=annotation.persist_ref_scope or document_id,
        suppressed=False,
        configuration=configuration,
    )


def note_subject(
    note: DrawingNote,
    sheet: DrawingSheetRecord,
    view: DrawingView,
    configuration: str,
    document_id: str,
) -> Subject:
    """One note; the IR carries no note name, so its package id is its identity."""
    return Subject(
        id=note.id,
        name=_label(sheet, view, None, note.id),
        type_name="note",
        persist_ref=note.persist_ref,
        persist_ref_scope=note.persist_ref_scope or document_id,
        suppressed=False,
        configuration=configuration,
    )


# --- the document one set of checks is evaluated over -----------------------------------------


@dataclass(frozen=True)
class Drawing:
    """One graded drawing document and everything the four checks read about it."""

    document: CheckedDocument
    row: Document
    package: EvidencePackage
    profile: StandardsProfile
    record: DrawingRecord | None

    native: tuple[DrawingSheetRecord, ...]
    """Every natively dumped sheet the package records for this drawing."""

    sheets: tuple[DrawingSheetRecord, ...]
    """The native sheets whose contents the dump could enumerate - the ones graded."""

    unreadable: tuple[tuple[DrawingSheetRecord, str], ...]
    """The native sheets whose contents it could not, each with the gap that says so."""

    ingested: tuple[DrawingSheet, ...]
    """The PDF ingest's sheet evidence for this drawing, which is never graded here."""

    @property
    def document_id(self) -> str:
        return self.document.document_id

    @property
    def name(self) -> str:
        return self.document.file_name or self.document.document_id

    @property
    def configuration(self) -> str:
        return self.document.configuration or ""

    def itself(self) -> Subject:
        return document_subject(self.document)

    def why(self, entity_id: str, *kinds: str) -> str:
        """The gap the dump recorded for `entity_id`, or that it recorded none."""
        return gap_note(self.package, entity_id, *kinds)

    def views(self) -> Iterator[tuple[DrawingSheetRecord, DrawingView]]:
        """Every view of every graded sheet, in sheet and view order."""
        for sheet in self.sheets:
            yield from ((sheet, view) for view in sheet.views)

    def dimensions(
        self,
    ) -> Iterator[tuple[DrawingSheetRecord, DrawingView, DisplayDimensionRecord]]:
        for sheet, view in self.views():
            yield from ((sheet, view, row) for row in view.display_dimensions)

    def annotations(
        self,
    ) -> Iterator[tuple[DrawingSheetRecord, DrawingView, DrawingAnnotation]]:
        for sheet, view in self.views():
            yield from ((sheet, view, row) for row in view.annotations)

    def notes(self) -> Iterator[tuple[DrawingSheetRecord, DrawingView, DrawingNote]]:
        for sheet, view in self.views():
            yield from ((sheet, view, row) for row in view.notes)

    def tables(self) -> Iterator[tuple[DrawingSheetRecord, RevisionTable]]:
        """Every revision table on every graded sheet, not only the active sheet's
        (difference y)."""
        for sheet in self.sheets:
            yield from ((sheet, table) for table in sheet.revision_tables)

    def sheets_without_format_view(self) -> tuple[DrawingSheetRecord, ...]:
        """The graded sheets that recorded no type-1 sheet-format pseudo-view."""
        return tuple(
            sheet
            for sheet in self.sheets
            if not any(view.view_type_raw == SHEET_FORMAT_VIEW for view in sheet.views)
        )

    def referenced_documents(self) -> tuple[Document, ...]:
        """Each document a view on a graded sheet references, once, in traversal order."""
        wanted: dict[str, None] = {}
        for _, view in self.views():
            if view.referenced_document_id is not None:
                wanted.setdefault(view.referenced_document_id, None)
        by_id = {row.document_id: row for row in self.package.documents}
        return tuple(by_id[document_id] for document_id in wanted if document_id in by_id)

    def unreadable_references(self) -> tuple[tuple[DrawingSheetRecord, DrawingView], ...]:
        """Each view on a graded sheet whose referenced model was **not loaded**.

        `contracts/ir-additions.md` section 3.3: a null `referenced_document_id` beside a
        recorded `referenced_model_path` is that case, and the path is recorded precisely so
        the row can name the model that was not loaded (FR-025). A view whose path is null
        too references nothing, which is a real absence and not a gap.
        """
        return tuple(
            (sheet, view)
            for sheet, view in self.views()
            if view.referenced_document_id is None and view.referenced_model_path is not None
        )

    def property_of(self, row: Document) -> str | None:
        """`row`'s revision property, or `None` when the card does not carry it at all.

        Read through `checks/standards/document.py`'s card reader, so the case-insensitive
        lookup SOLIDWORKS custom properties need is written once. An empty value stays the
        empty string: a blank revision is a real mismatch, not an absence.
        """
        field = read_card(row.custom_properties, [self.profile.revision.property])[0]
        return None if field.state == "absent" else field.resolved_value


def drawing_scope(
    document: CheckedDocument, package: EvidencePackage, profile: StandardsProfile
) -> Drawing:
    """Everything the four checks read about `document`, gathered once."""
    if document.kind != SCOPE:
        raise ValueError(
            f"{document.document_id} is a {document.kind} document; the drawing checks grade "
            f"a {SCOPE} document"
        )
    row = next(item for item in package.documents if item.document_id == document.document_id)
    record = next(
        (
            item
            for item in package.drawing_records
            if item.document_id == document.document_id
        ),
        None,
    )
    native = tuple(record.sheets) if record is not None else ()
    unreadable = tuple(
        (sheet, gap_note(package, sheet.id, "drawing_sheet_views"))
        for sheet in native
        if find_gap(package, sheet.id, "drawing_sheet_views") is not None
    )
    lost = {sheet.id for sheet, _ in unreadable}
    return Drawing(
        document=document,
        row=row,
        package=package,
        profile=profile,
        record=record,
        native=native,
        sheets=tuple(sheet for sheet in native if sheet.id not in lost),
        unreadable=unreadable,
        ingested=tuple(
            sheet for sheet in package.drawings if sheet.document_id == document.document_id
        ),
    )


def evaluate_drawing(
    document: CheckedDocument, package: EvidencePackage, profile: StandardsProfile
) -> list[RuleResult]:
    """Every drawing check over one graded drawing document, in catalogue order."""
    scope = drawing_scope(document, package, profile)
    results: list[RuleResult] = []
    for rule in RULES.values():
        if rule.scope == SCOPE:
            assert rule.fn is not None, f"{rule.id} has no evaluator"
            results.extend(_evaluate(scope, rule))
    return results


def _evaluate(scope: Drawing, rule: StandardsRule) -> list[RuleResult]:
    """One check over one drawing, with the three rows every check shares.

    The contract states them once for all four checks rather than per check, so they are
    written once here: FR-005's document-evidence half, the native-sheet rule, and the
    per-sheet rows for evidence this check may not grade.
    """
    missing = document_evidence_unresolved(scope.document)
    if missing is not None:
        return [unresolved(rule, scope.document_id, missing)]
    if not scope.native:
        return [unresolved(rule, scope.document_id, _no_native_reason(scope))]

    results = list(rule.fn(scope)) if scope.sheets and rule.fn is not None else []
    results.extend(
        unresolved(
            rule,
            scope.document_id,
            NON_ENUMERABLE_SHEET.format(sheet=repr(sheet.name), name=scope.name, why=why),
        )
        for sheet, why in scope.unreadable
    )
    if scope.ingested:
        results.append(
            unresolved(
                rule,
                scope.document_id,
                INGESTED_SHEETS.format(
                    name=scope.name,
                    count=len(scope.ingested),
                    sheets=_ingested_sheets(scope),
                ),
            )
        )
    return results


def _no_native_reason(scope: Drawing) -> str:
    """Why a drawing with no native sheet is unresolved, naming the evidence there is."""
    reason = NO_NATIVE_SHEET.format(name=scope.name)
    if scope.ingested:
        return f"{reason}; the sheet evidence it does carry is {_ingested_sheets(scope)}"
    return f"{reason}; {scope.why(scope.document_id, 'drawing_sheet')}"


def _ingested_sheets(scope: Drawing) -> str:
    """The PDF-ingested sheets and the source each of them records.

    A sheet written before the stamp existed records none, and is read exactly as one
    stamped `pdf_ingest` (`contracts/ir-additions.md` section 4) - said out loud, because a
    reader has to be able to tell a stamped sheet from an unstamped one.
    """
    return ", ".join(
        f"{sheet.sheet_name} (source {sheet.source!r})"
        if sheet.source is not None
        else f"{sheet.sheet_name} (source not recorded, read as 'pdf_ingest')"
        for sheet in scope.ingested
    )


# --- standards.drawing.dimensions_not_overridden ---------------------------------------------


@bind(DIMENSIONS_NOT_OVERRIDDEN)
def dimensions_not_overridden(scope: Drawing) -> list[RuleResult]:
    """No display dimension carries a manual override (FR-018).

    A dimension owned by the model rather than by the drawing is **not** excluded: an
    overridden model-item dimension is the defect being hunted.
    """
    rule = RULES[DIMENSIONS_NOT_OVERRIDDEN]
    dimensions = list(scope.dimensions())
    if not dimensions:
        return [skipped(rule, scope.document_id, NO_DIMENSIONS)]

    offenders: list[Subject] = []
    observed: list[str] = []
    passing: list[Subject] = []
    unknown: list[tuple[Subject, str]] = []
    for sheet, view, dimension in dimensions:
        subject = dimension_subject(
            dimension, sheet, view, scope.configuration, scope.document_id
        )
        where = _where(sheet, view)
        if dimension.is_overridden is None:
            unknown.append(
                (
                    subject,
                    f"whether it carries a manual override was not read ({where}); "
                    + scope.why(dimension.id, "dimension_override"),
                )
            )
            continue
        if not dimension.is_overridden:
            passing.append(subject)
            continue
        if dimension.override_value is None:
            unknown.append(
                (
                    subject,
                    f"it carries a manual override whose unit could not be determined "
                    f"({where}), so its value is reported unresolved rather than rendered "
                    "with a guessed unit (difference p); "
                    + scope.why(dimension.id, "dimension_unit"),
                )
            )
            continue
        offenders.append(subject)
        observed.append(
            f"{dimension.name or dimension.id} ({where}) is overridden to "
            f"{_measure(dimension.override_value)}"
            + (
                ""
                if dimension.value is None
                else f", where the model computes {_measure(dimension.value)}"
            )
        )

    violation = (
        finding(
            rule,
            scope.document_id,
            offenders,
            observed=(
                f"{len(offenders)} display dimension(s) of {scope.name} carry a manual "
                "override, so the drawing states a value the geometry does not: "
                + "; ".join(observed)
            ),
            recommended_action=(
                "Remove the manual override in SOLIDWORKS so the dimension reports the "
                "modelled value, or change the model."
            ),
        )
        if offenders
        else None
    )
    return outcome(
        rule, scope.document_id, violation=violation, passing=passing, unknown=unknown
    )


def _measure(value: Quantity | Angle) -> str:
    """One recorded value in the unit the package recorded it in, and no other.

    The macro multiplied by a thousand "blindly assuming the system units are in metres"
    and then assigned a formatted string back into a number (difference p); here the record
    carries its own unit and nothing converts it.
    """
    return f"{value.value:g} {value.unit}"


def _where(sheet: DrawingSheetRecord, view: DrawingView) -> str:
    """Where on the drawing a subject sits, as a finding says it."""
    return f"sheet {sheet.name!r}, view {(view.name or view.id)!r}"


# --- standards.drawing.annotations_not_dangling ----------------------------------------------


@bind(ANNOTATIONS_NOT_DANGLING)
def annotations_not_dangling(scope: Drawing) -> list[RuleResult]:
    """No annotation is dangling, whatever its type (FR-019)."""
    rule = RULES[ANNOTATIONS_NOT_DANGLING]
    annotations = list(scope.annotations())
    if not annotations:
        return [skipped(rule, scope.document_id, NO_ANNOTATIONS)]

    offenders: list[Subject] = []
    observed: list[str] = []
    passing: list[Subject] = []
    unknown: list[tuple[Subject, str]] = []
    for sheet, view, annotation in annotations:
        subject = annotation_subject(
            annotation, sheet, view, scope.configuration, scope.document_id
        )
        where = _where(sheet, view)
        if annotation.is_dangling is None:
            unknown.append(
                (
                    subject,
                    f"whether it is dangling was not read ({where}); "
                    + scope.why(annotation.id, "annotation_dangling"),
                )
            )
            continue
        if not annotation.is_dangling:
            passing.append(subject)
            continue
        offenders.append(subject)
        observed.append(
            f"{annotation.name or annotation.id} ({_annotation_type(annotation.type_raw)}, "
            f"{where}) is dangling"
        )

    violation = (
        finding(
            rule,
            scope.document_id,
            offenders,
            observed=(
                f"{len(offenders)} annotation(s) of {scope.name} are dangling, so they no "
                "longer attach to the geometry they describe: " + "; ".join(observed)
            ),
            recommended_action=(
                "Reattach each dangling annotation in SOLIDWORKS, or delete it if what it "
                "described is gone."
            ),
        )
        if offenders
        else None
    )
    return outcome(
        rule, scope.document_id, violation=violation, passing=passing, unknown=unknown
    )


def _annotation_type(type_raw: int | None) -> str:
    """One annotation type, named where research R3.3 verified the constant."""
    if type_raw is None:
        return "an unrecorded annotation type"
    name = ANNOTATION_TYPE_NAMES.get(type_raw)
    return f"type {type_raw}" if name is None else f"type {type_raw} ({name})"


# --- standards.drawing.revision_matches ------------------------------------------------------


@bind(REVISION_MATCHES)
def revision_matches(scope: Drawing) -> list[RuleResult]:
    """The table, the drawing's property and every referenced model's agree (FR-020).

    One finding for the drawing naming **every** disagreement it found, in three cases: no
    revision table on any sheet, a table disagreeing with the drawing's revision property,
    and the drawing's property disagreeing with a referenced document's. The first of those
    is claimed only when **every** native sheet could be enumerated: where one could not, the
    table may sit on it, so the absence is unresolved rather than a warning (FR-029). A view
    whose referenced model was not loaded is unresolved naming the model, for the same
    reason: an absent comparison is never a silent one. The revision is
    read from the cell `revision.cell` names, and where `IRevisionTableAnnotation`'s own
    `CurrentRevision` disagrees with that cell the **cell is normative** (RK-4): both
    readings are named with their source, which is a warning and not a data gap, because
    the macro's author recorded that reading coming back empty under the vault.
    """
    rule = RULES[REVISION_MATCHES]
    revision = scope.profile.revision
    if not revision.property:
        return [
            skipped(
                rule,
                scope.document_id,
                "the profile's revision.property is empty, so there is no revision property "
                "to compare the drawing's revision table and its referenced models against",
            )
        ]
    if properties_gap(scope.package, scope.document_id) is not None:
        return [
            unresolved(
                rule,
                scope.document_id,
                f"the custom properties of {scope.name} were not read, so neither its "
                "revision table nor its referenced models can be compared against its "
                f"{revision.property} property; "
                + properties_gap_note(scope.package, scope.document_id),
            )
        ]

    stated = scope.property_of(scope.row)
    disagreements: list[str] = []
    unknown: list[str] = []
    compared = False

    tables = list(scope.tables())
    if not tables:
        searched = (
            f"no revision table was found on the {len(scope.sheets)} native sheet(s) of "
            f"{scope.name} that could be enumerated"
        )
        if scope.unreadable:
            # The table may sit on the very sheet the dump could not enumerate, so the
            # absence is unresolved rather than a warning finding (FR-029).
            unknown.append(
                f"{searched}, and the contents of {len(scope.unreadable)} further native "
                f"sheet(s) could not be read, so whether {scope.name} carries a revision "
                "table at all is not something this package can state"
            )
        else:
            disagreements.append(
                f"{searched}, so the revision it shows cannot be compared with its "
                f"{revision.property} property, which states {_says(stated, revision.property)}"
            )
    for sheet, table in tables:
        reading, why = _cell_reading(table, scope.profile)
        if why is not None:
            unknown.append(
                f"the revision table {table.id} on sheet {sheet.name!r} could not be read: "
                f"{why}; " + scope.why(table.id, "revision_table_read")
            )
            continue
        compared = True
        if not _agree(reading, stated):
            disagreements.append(
                f"the revision table {table.id} on sheet {sheet.name!r} states "
                f"{_says(reading, revision.property)} in "
                + CELL.format(row=revision.cell.row_from_end, column=revision.cell.column)
                + f", and the {revision.property} property of {scope.name} states "
                + _says(stated, revision.property)
            )
        if table.current_revision_raw is not None and not _agree(
            table.current_revision_raw, reading
        ):
            disagreements.append(
                f"the revision table {table.id} on sheet {sheet.name!r} states "
                f"{_says(reading, revision.property)} in "
                + CELL.format(row=revision.cell.row_from_end, column=revision.cell.column)
                + f" and {_says(table.current_revision_raw, revision.property)} in "
                "IRevisionTableAnnotation.CurrentRevision; the cell revision.cell names is "
                "the normative reading and both are reported"
            )

    referenced = scope.referenced_documents()
    unread_references = scope.unreadable_references()
    if not referenced and not unread_references:
        unknown.append(
            f"{scope.name} references no document on any of its native sheets, so its "
            f"{revision.property} property could not be compared with a model's; its own "
            "revision table was compared"
        )
    for sheet, view in unread_references:
        unknown.append(
            f"the model {view.referenced_model_path} that {_where(sheet, view)} references "
            "was not loaded, so it is not a document of this package and its "
            f"{revision.property} property could not be compared with the drawing's; "
            + scope.why(view.id, "drawing_referenced_document")
        )
    for model in referenced:
        if properties_gap(scope.package, model.document_id) is not None:
            unknown.append(
                f"the custom properties of {model.file_name or model.document_id} were not "
                f"read, so its {revision.property} property could not be compared with the "
                "drawing's; "
                + properties_gap_note(scope.package, model.document_id)
            )
            continue
        compared = True
        theirs = scope.property_of(model)
        if not _agree(theirs, stated):
            disagreements.append(
                f"the {revision.property} property of {scope.name} states "
                + _says(stated, revision.property)
                + f", and {model.file_name or model.document_id}, which it references, "
                "states " + _says(theirs, revision.property)
            )

    results: list[RuleResult] = []
    if disagreements:
        results.append(
            finding(
                rule,
                scope.document_id,
                [scope.itself()],
                observed=(
                    f"the revision {scope.name} shows does not agree everywhere: "
                    + "; ".join(disagreements)
                ),
                recommended_action=(
                    "Bring the revision table, the drawing's revision property and the "
                    "revision property of every model it references into agreement."
                ),
            )
        )
    elif compared:
        results.append(passed(rule, scope.document_id, [scope.itself()]))
    if unknown:
        results.append(unresolved(rule, scope.document_id, "; ".join(unknown)))
    return results


def _cell_reading(
    table: RevisionTable, profile: StandardsProfile
) -> tuple[str | None, str | None]:
    """The revision `table` states, or why it could not be read.

    Two profile questions and no extractor opinion (`contracts/ir-additions.md` section 3):
    which row is the revision row (`revision.cell.row_from_end`, counted from the end) and
    which column carries it (`revision.cell.column`). A table whose selected row is still
    its **header** row - its first cell is `revision.header_text` - has no revision entry
    yet and is read as `revision.initial`.

    A **null** cell is unread and is reported as such; an **empty** cell is the empty
    string, which is compared as empty and reported as a mismatch (FR-029).
    """
    cell = profile.revision.cell
    where = CELL.format(row=cell.row_from_end, column=cell.column)
    if not table.rows:
        return None, f"it records no row, so {where} could not be read"
    index = len(table.rows) - 1 - cell.row_from_end
    if index < 0:
        return None, f"{where} is outside the {len(table.rows)} row(s) it records"
    row = table.rows[index]
    first = row.cells[0] if row.cells else None
    if first is not None and first.casefold() == profile.revision.header_text.casefold():
        return profile.revision.initial, None
    if cell.column >= len(row.cells):
        return None, f"{where} is outside the {len(row.cells)} cell(s) that row records"
    if row.cells[cell.column] is None:
        return None, f"{where} was not read"
    return row.cells[cell.column], None


def _agree(left: str | None, right: str | None) -> bool:
    """Whether two revision readings agree, case-insensitively.

    `None` is a property the card does not carry at all, which agrees with nothing but
    another absence - it is not the empty string, which is a value that was read and is
    compared as empty.
    """
    if left is None or right is None:
        return left is None and right is None
    return left.casefold() == right.casefold()


def _says(value: str | None, property_name: str) -> str:
    """One revision reading as a finding says it, absence and emptiness distinguished."""
    if value is None:
        return f"no {property_name} property"
    if not value:
        return "'' (an empty cell)"
    return repr(value)


# --- standards.drawing.no_itar_statement -----------------------------------------------------


@bind(NO_ITAR_STATEMENT)
def no_itar_statement(scope: Drawing) -> list[RuleResult]:
    """No export-control statement appears in the drawing's notes (FR-021).

    **Presence is the defect.** The phrase is looked for as a case-insensitive substring in
    every note of every view of every native sheet, and a drawing that carries it anywhere
    is one finding naming every sheet and note that did.

    The absence is only claimable when it was possible to look: a note whose text was not
    read cannot be shown not to carry the statement, and a sheet that recorded no type-1
    sheet-format view was not looked at where the macro always found the statement. Either
    leaves the check unresolved rather than checked - **including beside a finding**, because
    a phrase read on one note says nothing about the note or the sheet that was not read, and
    a drawing must not read as fully covered on evidence known to be incomplete (FR-029).
    """
    rule = RULES[NO_ITAR_STATEMENT]
    phrase = scope.profile.export_control.phrase
    if not phrase:
        return [
            skipped(
                rule,
                scope.document_id,
                "the profile's export_control.phrase is empty, so there is no "
                "export-control statement to look for",
            )
        ]

    notes = list(scope.notes())
    carrying: list[Subject] = []
    observed: list[str] = []
    unknown: list[tuple[Subject, str]] = []
    for sheet, view, note in notes:
        subject = note_subject(note, sheet, view, scope.configuration, scope.document_id)
        if note.text is None:
            unknown.append(
                (
                    subject,
                    f"its text was not read ({_where(sheet, view)}), and an unread note "
                    "cannot be shown not to carry the export-control statement; "
                    + scope.why(note.id, "note_text"),
                )
            )
            continue
        if phrase.casefold() in note.text.casefold():
            carrying.append(subject)
            observed.append(f"note {note.id} ({_where(sheet, view)})")

    blind = [
        (
            _sheet_subject(sheet, scope.configuration, scope.document_id),
            "it recorded no type-1 sheet-format view, which is where the export-control "
            "statement is found, so the absence of the phrase on it is not something this "
            f"package can state; {scope.why(sheet.id, 'drawing_sheet_views', 'drawing_view')}",
        )
        for sheet in scope.sheets_without_format_view()
    ]
    # The coverage row is built before the finding and stands beside it: the statement being
    # present on one note does not make an unread note readable or an unlooked-at sheet
    # looked at, and this check's unresolved column is unconditional (FR-029).
    coverage = (
        [
            unresolved(
                rule,
                scope.document_id,
                subject_reasons([*unknown, *blind]),
                [row for row, _ in (*unknown, *blind)],
            )
        ]
        if unknown or blind
        else []
    )

    if carrying:
        return [
            finding(
                rule,
                scope.document_id,
                carrying,
                observed=(
                    f"{len(carrying)} note(s) of {scope.name} carry the export-control "
                    "phrase the profile's export_control.phrase names: " + "; ".join(observed)
                ),
                recommended_action=(
                    "Remove the export-control statement from the drawing's notes, or "
                    "confirm with the release process that this drawing should carry it."
                ),
            ),
            *coverage,
        ]
    if coverage:
        return coverage
    if not notes:
        return [skipped(rule, scope.document_id, NO_NOTES)]
    return [passed(rule, scope.document_id)]


def _sheet_subject(
    sheet: DrawingSheetRecord, configuration: str, document_id: str
) -> Subject:
    """One sheet, for the row that says what could not be looked at on it."""
    return Subject(
        id=sheet.id,
        name=sheet.name,
        type_name="sheet",
        persist_ref=sheet.persist_ref,
        persist_ref_scope=sheet.persist_ref_scope or document_id,
        suppressed=False,
        configuration=configuration,
    )
