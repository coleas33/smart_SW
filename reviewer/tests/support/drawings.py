"""Builders for the drawing-context fixtures of feature 011 (T012, `contracts/fixtures.md`).

No recorded package carries a drawing (the attach refused every one until feature 011), so
`tests/fixtures/drawings/generate_fixtures.py` builds three synthetic packages out of these
builders, and the unit tests of feature 011 build their small packages out of the same ones,
so there is one definition of what a drawing record looks like in a package.

**A drawing is added on top of a package that already exists** - feature 010's `tolerances`
assembly, a small assembly from `tests/support/mechanical.py`, or feature 006's drawing-rooted
standards package - because every binding case needs the joints, faces, persistent references
and model dimensions those packages already carry with known answers. `DrawingBuilder` never
changes a row of its base package; it adds drawing documents and their manifest entries,
drawing records, candidates and gaps, and restates the design's drawing list.

**The shapes are the extractor's** (`contracts/native-evidence.md`): drawing ids continue one
sequence across every drawing of the package (`dsh`, `dvw`, `ddm`, `dan`, `dnt`, `drv`, `dtb`,
T010); a drawing document has no configuration (`""`, `contracts/attach.md` section 2); a
display dimension's value is in SOLIDWORKS' system units, metres, as `DrawingDumper` writes
it, and a type that names no unit records no value and a `dimension_unit` gap; a tolerance is
mapped as feature 010's `ToleranceDumper` maps one - `NONE` is kind `none`, `BLOCK`, `GENERAL`
and a class-only fit have no IR kind and leave the tolerance null with the raw type kept; an
attached face carries the persistent reference of a face of the package, scoped to the part
document that owns it.

**Every string is fictional**: paths start with `FICTIONAL_ROOT`, names come from
`DRAWING_VOCABULARY` (feature 010's `VOCABULARY` extended with drawing words), and
`test_drawing_fixtures_are_fictional.py` holds the fixtures to that and to the owner's
denylist when it is on the machine.

The schema version is pinned to `DRAWING_FIXTURE_SCHEMA_VERSION`, never `SCHEMA_VERSION`: these
are 1.6.0 packages, and a later IR minor must load them unchanged (FR-048) rather than rewrite
them under the regeneration test.

**Feature 014 adds `SheetBuilder`** (`specs/014-design-review-eval/contracts/generator.md`
section 6, GN-7): PDF-ingested sheets (`package.drawings`), the only drawing dimensions
`check_fit`, `check_axial_stack` and a toleranced `check_hole_alignment` read while the native
binding is unvalidated (`tools/refs.resolve_dimension`). Its shapes are the PDF ingest's
(`ingest/pdf_drawing.py`): a drawing document with configuration `Default` and a `pdf` manifest
entry, written by `write_drawing_document`, the one function `DrawingBuilder` writes its drawing
documents with too; sheets in mm at 1:1; dimensions and notes annotated `dim-<page>-<n>` and
`note-<page>-<n>` in call order; a page with no text layer a `no_text` sheet that states nothing,
with the ingest's gap. It leaves the base's schema version alone: the case generator pins its own.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from swreview.ir.models import (
    AttachedFace,
    BomRow,
    Dimension,
    DisplayDimensionRecord,
    Document,
    DrawingAnnotation,
    DrawingCandidate,
    DrawingNote,
    DrawingRecord,
    DrawingSheet,
    DrawingSheetRecord,
    DrawingTable,
    DrawingView,
    DumpPhase,
    EvidencePackage,
    Gap,
    GtolFrame,
    ManifestEntry,
    Note,
    Quantity,
    RevisionTable,
    RevisionTableRow,
    SourceRef,
    Tolerance,
)
from tests.support.mechanical import FICTIONAL_ROOT, VOCABULARY, fictional_offences
from tests.support.packages import persist_ref

__all__ = [
    "DRAWING_FIXTURE_SCHEMA_VERSION",
    "DRAWING_VOCABULARY",
    "FULL_PHASES",
    "Attach",
    "DrawingBuilder",
    "Limits",
    "NoteKind",
    "SheetBuilder",
    "drawing_fictional_offences",
    "write_drawing_document",
]

DRAWING_FIXTURE_SCHEMA_VERSION = "1.6.0"

FULL_PHASES: tuple[str, ...] = (
    "document",
    "manifest",
    "mate",
    "feature",
    "equation",
    "cutlist",
    "drawing",
    "hole",
    "tolerance",
    "fastener",
    "face",
    "body",
)
"""`PackageWriter.PhaseOrder`: the twelve phase rows a review extraction writes."""

DRAWING_VOCABULARY: frozenset[str] = VOCABULARY | frozenset(
    {
        # what a drawing is made of
        "sheet",
        "drawing",
        "view",
        "front",
        "top",
        "right",
        "iso",
        "format",
        "standard",
        "note",
        "general",
        "tolerance",
        "table",
        "title",
        "block",
        "parts",
        "list",
        "item",
        "qty",
        "tag",
        "size",
        "loc",
        "rev",
        "description",
        "date",
        "release",
        "decimals",
        "break",
        "sharp",
        "edges",
        "datum",
        "sf",
        "symbol",
        "cb",
        # SOLIDWORKS' own callout and symbol tokens, as it writes them
        "mod",
        "diam",
        "thru",
        "cbore",
        "depth",
        "gtol",
        "posi",
        "igtol",
        "slddrw",
        "slddrt",
        # feature 006's fictional profile A, which the drawing root is graded against: its
        # export-control phrase and its initial revision
        "meridian",
        "embargo",
        "aa",
    }
)
"""Every word a drawing fixture string may contain; `drawing_fictional_offences` checks it."""


_WORD_NUMBER = re.compile(r"(?<=[A-Za-z])(?=[0-9])|(?<=[0-9])(?=[A-Za-z])")


def drawing_fictional_offences(text: str) -> list[str]:
    """Feature 010's vocabulary check, over the drawing vocabulary, with a word and the number
    run into it read apart: SOLIDWORKS names a drawing's things that way (`Sheet1`,
    `Drawing View2`, `GTol1`), and a fit class (`H7`) is a letter and a number."""
    return fictional_offences(_WORD_NUMBER.sub(" ", text), DRAWING_VOCABULARY)


@dataclass(frozen=True)
class Attach:
    """One face of the base package an annotation or dimension is attached to."""

    face_id: str
    via: Literal["face", "edge"] = "face"


ToleranceSpec = tuple[Literal["bilateral", "symmetric", "limits", "basic"], float, float | None]
"""`(kind, upper_mm, lower_mm)`, the limits as the signed deviations SOLIDWORKS reports."""

NO_UNIT_TYPES: frozenset[int] = frozenset({0, 13})
"""`swDimensionTypeUnknown` and `swScalarDimension`: types that name no unit, so the dumper
records no value (feature 006's difference p)."""

ANGULAR_TYPES: frozenset[int] = frozenset({3, 16})


def write_drawing_document(
    documents: list[Document],
    entries: list[ManifestEntry],
    stem: str,
    *,
    properties: Mapping[str, str] | None,
    configuration: str,
    export_method: Literal["native", "pdf"],
) -> str:
    """Append a drawing document, the next `doc:NNNN`, to `documents` and its manifest entry to
    `entries`; return its id. The path is `<stem>.SLDDRW` in the fictional vault.

    The one writer of a drawing document, which `DrawingBuilder` and `SheetBuilder` both call,
    so the two cannot disagree about what one is (feature 014 GN-7). `configuration` is `""`
    for a native drawing, which has none (`contracts/attach.md` section 2), and `"Default"` for
    a PDF-ingested one, as the ingest writes it."""
    document_id = f"doc:{len(documents) + 1:04d}"
    path = f"{FICTIONAL_ROOT}Vault\\{stem}.SLDDRW"
    documents.append(
        Document(
            document_id=document_id,
            kind="drawing",
            file_name=f"{stem}.SLDDRW",
            path=path,
            configurations=[configuration] if configuration else [],
            active_configuration=configuration,
            custom_properties=dict(properties or {}),
            config_properties={},
            material=None,
            mass=None,
        )
    )
    entries.append(
        ManifestEntry(
            document_id=document_id,
            vault_path=path,
            vault_version=1,
            revision=None,
            configuration=configuration,
            local_modified=False,
            export_method=export_method,
        )
    )
    return document_id


class DrawingBuilder:
    """Adds drawings to `base`, allocating every drawing id from one package-wide sequence."""

    def __init__(self, base: EvidencePackage, *, package_id: UUID | None = None) -> None:
        self._base = base
        self._package_id = package_id or base.package_id
        self._documents: list[Document] = list(base.documents)
        self._entries: list[ManifestEntry] = list(base.manifest.entries)
        self._drawing_ids: list[str] = list(base.design.drawing_document_ids)
        self._records: list[DrawingRecord] = []
        self._candidates: list[DrawingCandidate] = []
        self._gaps: list[Gap] = list(base.gaps)
        self._counters: dict[str, int] = {}
        self._sheet_of: dict[str, DrawingSheetRecord] = {}
        self._drawing_of: dict[str, DrawingRecord] = {}

    # --- ids ------------------------------------------------------------------------------

    def _next(self, prefix: str) -> str:
        self._counters[prefix] = self._counters.get(prefix, 0) + 1
        return f"{prefix}:{self._counters[prefix]:04d}"

    def _document(self, document_id: str) -> Document:
        for document in self._documents:
            if document.document_id == document_id:
                return document
        raise ValueError(f"{document_id} is not a document of this package")

    # --- documents --------------------------------------------------------------------------

    def drawing_document(self, stem: str, *, properties: Mapping[str, str] | None = None) -> str:
        """A drawing document beside the base's documents, with no configuration."""
        document_id = write_drawing_document(
            self._documents,
            self._entries,
            stem,
            properties=properties,
            configuration="",
            export_method="native",
        )
        self._drawing_ids.append(document_id)
        return document_id

    def drawing(
        self,
        document_id: str,
        *,
        active_sheet: str | None = "Sheet1",
        is_detailing_mode: bool | None = False,
        length_unit_raw: int | None = 0,
        dimension_precision_raw: int | None = 2,
        units_decimal_places_raw: int | None = 2,
        tolerance_precision_raw: int | None = 3,
        drafting_standard_name: str | None = "FICTIONAL-STANDARD",
    ) -> DrawingRecord:
        """One drawing record for `document_id`, which must be a drawing of the package."""
        if self._document(document_id).kind != "drawing":
            raise ValueError(f"{document_id} is not a drawing document")
        record = DrawingRecord(
            document_id=document_id,
            active_sheet_name=active_sheet,
            is_detailing_mode=is_detailing_mode,
            length_unit_raw=length_unit_raw,
            dimension_precision_raw=dimension_precision_raw,
            units_decimal_places_raw=units_decimal_places_raw,
            tolerance_precision_raw=tolerance_precision_raw,
            drafting_standard_name=drafting_standard_name,
        )
        self._records.append(record)
        return record

    def sheet(
        self,
        drawing: DrawingRecord,
        name: str,
        *,
        format_name: str | None = "FICTIONAL-FORMAT-A",
        format_path: str | None = f"{FICTIONAL_ROOT}Formats\\FICTIONAL-FORMAT-A.slddrt",
        scale: tuple[float, float] | None = (1.0, 1.0),
        first_angle: bool | None = False,
    ) -> DrawingSheetRecord:
        """One sheet, active when its name is the drawing's active sheet (T010's rule)."""
        sheet_id = self._next("dsh")
        sheet = DrawingSheetRecord(
            id=sheet_id,
            name=name,
            index=len(drawing.sheets),
            sheet_format_name=format_name,
            was_active=drawing.active_sheet_name == name,
            sheet_format_path=format_path,
            scale_numerator=None if scale is None else scale[0],
            scale_denominator=None if scale is None else scale[1],
            first_angle=first_angle,
            persist_ref=persist_ref(sheet_id),
            persist_ref_scope=drawing.document_id,
        )
        drawing.sheets.append(sheet)
        self._drawing_of[sheet_id] = drawing
        return sheet

    def view(
        self,
        sheet: DrawingSheetRecord,
        name: str,
        *,
        references: str | None = None,
        referenced_model_path: str | None = None,
        view_type_raw: int = 7,
        configuration: str | None = "Default",
        out_of_date: bool | None = False,
        loaded: bool | None = True,
        scale_decimal: float | None = 1.0,
        orientation: str | None = "*Front",
    ) -> DrawingView:
        """One view; `references` names a package document, `referenced_model_path` alone
        names a model outside the package (the caller adds the gap that says so)."""
        path = referenced_model_path
        if references is not None:
            path = path or self._document(references).path
        view_id = self._next("dvw")
        view = DrawingView(
            id=view_id,
            sheet_id=sheet.id,
            name=name,
            view_type_raw=view_type_raw,
            referenced_document_id=references,
            referenced_model_path=path,
            referenced_configuration=configuration,
            is_model_out_of_date=out_of_date,
            is_model_loaded=loaded,
            scale_decimal=scale_decimal,
            orientation_name=orientation,
            persist_ref=persist_ref(view_id),
            persist_ref_scope=self._drawing_of[sheet.id].document_id,
        )
        sheet.views.append(view)
        self._sheet_of[view_id] = sheet
        return view

    # --- what a view carries -----------------------------------------------------------------

    def _attached(self, attached: Sequence[Attach | AttachedFace]) -> list[AttachedFace]:
        faces = {face.id: face for face in self._base.faces}
        components = {component.id: component for component in self._base.components}
        rows: list[AttachedFace] = []
        for item in attached:
            if isinstance(item, AttachedFace):
                rows.append(item)
                continue
            face = faces.get(item.face_id)
            if face is None:
                raise ValueError(f"{item.face_id} is not a face of the base package")
            rows.append(
                AttachedFace(
                    persist_ref=face.persist_ref,
                    scope=components[face.component_id].document_id,
                    via=item.via,
                )
            )
        return rows

    def _where(self, view: DrawingView, annotation_id: str) -> SourceRef:
        sheet = self._sheet_of[view.id]
        return SourceRef(
            document_id=self._drawing_of[sheet.id].document_id,
            sheet=sheet.name,
            view=view.name,
            annotation=annotation_id,
        )

    def dimension(
        self,
        view: DrawingView,
        name: str,
        *,
        value_mm: float | None,
        type_raw: int = 6,
        tolerance: ToleranceSpec | None = None,
        tolerance_type_raw: int | None = 0,
        fit_hole_class: str | None = None,
        fit_shaft_class: str | None = None,
        precision: int | None = 2,
        tolerance_precision: int | None = 3,
        uses_document_precision: bool | None = False,
        units_raw: int | None = 0,
        uses_document_units: bool | None = True,
        prefix: str | None = "<MOD-DIAM>",
        suffix: str | None = "",
        above: str | None = "",
        below: str | None = "",
        overridden: bool | None = False,
        override_mm: float | None = None,
        is_reference: bool | None = False,
        driven_state_raw: int | None = 1,
        hole_callout: bool | None = False,
        callout_variables: Sequence[str] = (),
        attached: Sequence[Attach | AttachedFace] = (),
    ) -> DisplayDimensionRecord:
        """One display dimension, its value and override in metres as `DrawingDumper` writes
        them. `tolerance` states limits; with none, `tolerance_type_raw` 0 (`NONE`) is kind
        `none` and any other type (`BLOCK` 10, `GENERAL` 11, a class-only fit) no IR kind."""
        dimension_id = self._next("ddm")
        unit_known = type_raw not in NO_UNIT_TYPES
        if type_raw in ANGULAR_TYPES:
            raise ValueError("the drawing fixtures carry lengths only")
        where = self._where(view, dimension_id)
        built = None
        if tolerance is not None:
            kind, upper, lower = tolerance
            built = Tolerance(
                kind=kind,
                upper=Quantity(value=upper / 1000.0, unit="m"),
                lower=None if lower is None else Quantity(value=lower / 1000.0, unit="m"),
                source=where,
            )
        elif tolerance_type_raw == 0:
            built = Tolerance(kind="none", upper=None, lower=None, source=where)
        record = DisplayDimensionRecord(
            id=dimension_id,
            view_id=view.id,
            name=name,
            dimension_type_raw=type_raw,
            is_overridden=overridden,
            override_value=(
                Quantity(value=override_mm / 1000.0, unit="m")
                if overridden and override_mm is not None and unit_known
                else None
            ),
            value=(
                Quantity(value=value_mm / 1000.0, unit="m")
                if value_mm is not None and unit_known
                else None
            ),
            text_prefix=prefix,
            text_suffix=suffix,
            text_above=above,
            text_below=below,
            precision_raw=precision,
            tolerance_precision_raw=tolerance_precision,
            uses_document_precision=uses_document_precision,
            units_raw=units_raw,
            uses_document_units=uses_document_units,
            tolerance=built,
            tolerance_type_raw=tolerance_type_raw,
            fit_hole_class=fit_hole_class,
            fit_shaft_class=fit_shaft_class,
            is_reference=is_reference,
            driven_state_raw=driven_state_raw,
            is_hole_callout=hole_callout,
            hole_callout_variables_raw=list(callout_variables),
            attached_faces=self._attached(attached),
            persist_ref=persist_ref(dimension_id),
            persist_ref_scope=where.document_id,
        )
        if not unit_known and value_mm is not None:
            self._gaps.append(
                Gap(
                    kind="not_extracted",
                    entity_kind="dimension_unit",
                    entity_id=dimension_id,
                    reason=(
                        f"Dimension {dimension_id} reports type {type_raw}, which names no "
                        "unit, so its value was not recorded rather than recorded with a guessed "
                        "one."
                    ),
                    error=None,
                )
            )
        view.display_dimensions.append(record)
        return record

    def annotation(
        self,
        view: DrawingView,
        *,
        type_raw: int,
        name: str | None,
        gtol_frames: Sequence[GtolFrame] = (),
        datum_identifier: str | None = None,
        datum_label: str | None = None,
        surface_finish_symbol: int | None = None,
        surface_finish_texts: Sequence[str] = (),
        attached: Sequence[Attach | AttachedFace] = (),
        is_dangling: bool | None = False,
    ) -> DrawingAnnotation:
        annotation_id = self._next("dan")
        record = DrawingAnnotation(
            id=annotation_id,
            owner_id=view.id,
            name=name,
            type_raw=type_raw,
            is_dangling=is_dangling,
            gtol_frames=list(gtol_frames),
            datum_identifier_raw=datum_identifier,
            datum_label=datum_label,
            surface_finish_symbol_raw=surface_finish_symbol,
            surface_finish_texts_raw=list(surface_finish_texts),
            attached_faces=self._attached(attached),
            persist_ref=persist_ref(annotation_id),
            persist_ref_scope=self._where(view, annotation_id).document_id,
        )
        view.annotations.append(record)
        return record

    def note(self, view: DrawingView, text: str | None) -> DrawingNote:
        note_id = self._next("dnt")
        record = DrawingNote(
            id=note_id,
            owner_id=view.id,
            text=text,
            persist_ref=persist_ref(note_id),
            persist_ref_scope=self._where(view, note_id).document_id,
        )
        view.notes.append(record)
        return record

    # --- what a sheet carries ----------------------------------------------------------------

    def table(
        self,
        sheet: DrawingSheetRecord,
        owner: DrawingView,
        *,
        type_raw: int,
        title: str | None,
        rows: Sequence[Sequence[str | None]],
        bom_rows: Sequence[BomRow] = (),
    ) -> DrawingTable:
        """One table that is not a revision table, found on `owner`'s table walk."""
        table_id = self._next("dtb")
        record = DrawingTable(
            id=table_id,
            sheet_id=sheet.id,
            owner_view_id=owner.id,
            table_type_raw=type_raw,
            title=title,
            row_count=len(rows),
            column_count=max((len(row) for row in rows), default=0),
            rows=[RevisionTableRow(index=index, cells=list(row)) for index, row in enumerate(rows)],
            bom_rows=list(bom_rows),
            persist_ref=persist_ref(table_id),
            persist_ref_scope=self._drawing_of[sheet.id].document_id,
        )
        sheet.tables.append(record)
        return record

    def revision_table(
        self,
        sheet: DrawingSheetRecord,
        *,
        rows: Sequence[Sequence[str | None]],
        current_revision: str | None,
    ) -> RevisionTable:
        table_id = self._next("drv")
        record = RevisionTable(
            id=table_id,
            sheet_id=sheet.id,
            current_revision_raw=current_revision,
            row_count=len(rows),
            column_count=max((len(row) for row in rows), default=0),
            rows=[RevisionTableRow(index=index, cells=list(row)) for index, row in enumerate(rows)],
            persist_ref=persist_ref(table_id),
            persist_ref_scope=self._drawing_of[sheet.id].document_id,
        )
        sheet.revision_tables.append(record)
        return record

    # --- the package ---------------------------------------------------------------------------

    def candidate(self, document_id: str) -> DrawingCandidate:
        """The same-stem `.SLDDRW` beside `document_id` (`contracts/open-drawings.md` section 5)."""
        document = self._document(document_id)
        folder = document.path.rsplit("\\", 1)[0]
        stem = document.file_name.rsplit(".", 1)[0]
        candidate = DrawingCandidate(
            document_id=document_id,
            path=f"{folder}\\{stem}.SLDDRW",
            reason="same_name_beside_model",
        )
        self._candidates.append(candidate)
        return candidate

    def gap(self, **fields: object) -> None:
        self._gaps.append(Gap(**fields))  # type: ignore[arg-type]

    def build(self, *, profile: Literal["full", "standards"] = "full") -> EvidencePackage:
        """The base package with this builder's drawings. A record for a document the base
        already has one for replaces it: a drawing root's record is rebuilt whole here."""
        rebuilt = {record.document_id for record in self._records}
        kept = [
            record for record in self._base.drawing_records if record.document_id not in rebuilt
        ]
        phases = (
            [DumpPhase(name=name, elapsed_ms=1, status="ok") for name in FULL_PHASES]
            if profile == "full"
            else self._base.extractor.phases
        )
        return self._base.model_copy(
            update={
                "schema_version": DRAWING_FIXTURE_SCHEMA_VERSION,
                "package_id": self._package_id,
                "extractor": self._base.extractor.model_copy(update={"phases": phases}),
                "manifest": self._base.manifest.model_copy(update={"entries": self._entries}),
                "design": self._base.design.model_copy(
                    update={"drawing_document_ids": self._drawing_ids}
                ),
                "documents": self._documents,
                "drawing_records": kept + self._records,
                "drawing_candidates": self._candidates,
                "gaps": self._gaps,
            }
        )


# --- PDF-ingested sheets (feature 014, generator.md section 6) ---------------------------------

Limits = tuple[Literal["bilateral"], float, float] | tuple[Literal["symmetric"], float] | None
"""A drawn tolerance in mm: `("bilateral", upper, lower)`, the signed deviations from nominal;
`("symmetric", half_width)`; or `None`, a dimension drawn with no tolerance."""

NoteKind = Literal["general_tolerance", "material", "finish", "other"]
"""What a general note on an ingested sheet states (`Note.kind`)."""

INGESTED_PARSER = "pdf-text"
"""The parser an ingested sheet names: the fictional standards goldens' (`standards-drawings`),
never the ingest's own `pymupdf/<version>`, which would move with the installed library."""


def _mm(value: float) -> Quantity:
    return Quantity(value=value, unit="mm")


def _tolerance(limits: Limits, source: SourceRef) -> Tolerance:
    """`limits` as the `Tolerance` the dimension grammar writes, in mm: a symmetric half-width
    is the signed deviations either side (`ingest/dimension_grammar.py`)."""
    if limits is None:
        return Tolerance(kind="none", upper=None, lower=None, source=source)
    if limits[0] == "bilateral":
        _, upper, lower = limits
        if upper < lower:
            raise ValueError(f"limits {limits!r}: the upper deviation is below the lower")
        return Tolerance(kind="bilateral", upper=_mm(upper), lower=_mm(lower), source=source)
    if limits[0] == "symmetric":
        _, half_width = limits
        if half_width <= 0:
            raise ValueError(f"limits {limits!r}: a symmetric half-width must be above zero")
        return Tolerance(
            kind="symmetric", upper=_mm(half_width), lower=_mm(-half_width), source=source
        )
    raise ValueError(f"limits {limits!r} is not a Limits form")


class SheetBuilder:
    """Adds PDF-ingested drawing sheets on top of `base`; never changes a base row."""

    def __init__(self, base: EvidencePackage) -> None:
        self._base = base
        self._documents: list[Document] = list(base.documents)
        self._entries: list[ManifestEntry] = list(base.manifest.entries)
        self._drawing_ids: list[str] = list(base.design.drawing_document_ids)
        # The drawings this builder wrote, the only ones it adds sheets to.
        self._drawings: set[str] = set()
        # Each sheet by its drawing and name, in call order.
        self._sheets: dict[tuple[str, str], DrawingSheet] = {}
        self._gaps: list[Gap] = []

    def _check_drawing(self, drawing_id: str) -> None:
        if drawing_id not in self._drawings:
            raise ValueError(f"drawing_id {drawing_id!r} is not a drawing this builder wrote")

    def drawing(self, stem: str, *, properties: Mapping[str, str] | None = None) -> str:
        """A drawing document as the PDF ingest writes one: configuration `Default` and a `pdf`
        manifest entry."""
        document_id = write_drawing_document(
            self._documents,
            self._entries,
            stem,
            properties=properties,
            configuration="Default",
            export_method="pdf",
        )
        self._drawing_ids.append(document_id)
        self._drawings.add(document_id)
        return document_id

    def sheet(
        self,
        drawing_id: str,
        name: str = "Sheet1",
        *,
        page: int,
        readable: bool = True,
        notes: Sequence[tuple[str, NoteKind]] = (),
    ) -> None:
        """One sheet in mm at 1:1, its notes annotated `note-<page>-<n>` in the order given.
        `readable=False` is a page with no text layer: the ingest's `no_text` sheet, which
        states no unit, scale, note or dimension, and its gap."""
        self._check_drawing(drawing_id)
        if (drawing_id, name) in self._sheets:
            raise ValueError(f"name {name!r} is already a sheet of {drawing_id}")
        if notes and not readable:
            raise ValueError(f"notes on {name!r}: an unreadable sheet has no text, so no notes")
        self._sheets[(drawing_id, name)] = DrawingSheet(
            document_id=drawing_id,
            sheet_name=name,
            page=page,
            scale="1:1" if readable else None,
            units="mm" if readable else "unknown",
            general_notes=[
                Note(
                    text=text,
                    source=SourceRef(
                        document_id=drawing_id, sheet=name, annotation=f"note-{page}-{number}"
                    ),
                    kind=kind,
                )
                for number, (text, kind) in enumerate(notes, start=1)
            ],
            dimensions=[],
            views=[],
            parse_status="text" if readable else "no_text",
            parser=INGESTED_PARSER,
            source="pdf_ingest",
        )
        if not readable:
            self._gaps.append(
                Gap(
                    kind="no_text",
                    entity_kind="drawing_sheet",
                    entity_id=f"{drawing_id}:{page}",
                    reason=(
                        f"page {page} of {drawing_id} has no text layer; it was exported "
                        "flattened and nothing on it could be read"
                    ),
                    error=None,
                )
            )

    def dimension(
        self, drawing_id: str, sheet: str, nominal_mm: float, *, limits: Limits, text: str
    ) -> SourceRef:
        """One dimension on `sheet`, annotated `dim-<page>-<n>` in call order as the parser
        numbers them, `text` as read. Returns the document, sheet and annotation triple
        `resolve_dimension` matches, which is the dimension's source and its tolerance's."""
        self._check_drawing(drawing_id)
        written = self._sheets.get((drawing_id, sheet))
        if written is None:
            raise ValueError(f"sheet {sheet!r} is not a sheet of {drawing_id}")
        if written.parse_status != "text":
            raise ValueError(
                f"sheet {sheet!r} of {drawing_id} is unreadable ({written.parse_status}) and "
                "carries no dimension"
            )
        source = SourceRef(
            document_id=drawing_id,
            sheet=sheet,
            annotation=f"dim-{written.page}-{len(written.dimensions) + 1}",
        )
        tolerance = _tolerance(limits, source)
        written.dimensions.append(
            Dimension(
                nominal=_mm(nominal_mm), tolerance=tolerance, source=source, text_as_read=text
            )
        )
        return source

    def build(self) -> EvidencePackage:
        """The base with the drawing documents appended to `documents` and the design's drawing
        list, their entries to the manifest, the sheets to `drawings` and the gaps to `gaps`;
        nothing else changes. Every list is a copy, so the builder going on changes no package
        it built."""
        return self._base.model_copy(
            update={
                "manifest": self._base.manifest.model_copy(
                    update={"entries": list(self._entries)}
                ),
                "design": self._base.design.model_copy(
                    update={"drawing_document_ids": list(self._drawing_ids)}
                ),
                "documents": list(self._documents),
                "drawings": [
                    *self._base.drawings,
                    *(sheet.model_copy(deep=True) for sheet in self._sheets.values()),
                ],
                "gaps": [*self._base.gaps, *self._gaps],
            }
        )
