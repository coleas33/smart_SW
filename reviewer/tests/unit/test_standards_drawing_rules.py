"""The four drawing-scope checks of `contracts/rules.md` (T065).

One class per check, each covering the four columns the contract gives it, plus a fifth
class for the preamble the contract states once for all four: **native sheets only, decided
per sheet**. Five rules run through every class:

- **every sheet is read** (difference q). The macro reads the current sheet's revision table
  only and scans notes in the first view of the current sheet only, so a defect on sheet 3
  is invisible to it. Nothing here activates a sheet to reach one (FR-044);
- **one finding per drawing**, carrying every subject that failed the check (FR-003): six
  overridden dimensions are six subjects inside one finding and one error, not six errors;
- **a reading that was not made is unresolved**, naming the gap the dump recorded beside it
  (FR-029) - an unread note, an unread cell and an unread flag are each a gap and never an
  empty string, a pass or a silent skip;
- **an empty profile setting that selects what to check is a skip**, phrased so the headline
  can count it (`checks/standards/report.py`'s `EMPTY_SETTING`), never a pass;
- **the two revision-and-notes checks are warnings** (`suspected` findings), and the two
  dimension-and-annotation checks are errors.

Every value-bearing string here comes from the fictional fixture profile (FR-001).
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from swreview.checks.standards.drawing import evaluate_drawing
from swreview.checks.standards.profile import StandardsProfile, load_profile
from swreview.checks.standards.results import RuleResult
from swreview.checks.standards.traversal import graded_documents
from swreview.ir.models import DrawingSheet, EvidencePackage, Gap
from tests.support.standards import (
    AnnotationSpec,
    AssemblySpec,
    DimensionSpec,
    DocumentSpec,
    DrawingSpec,
    NoteSpec,
    PartSpec,
    RevisionTableSpec,
    SheetSpec,
    ViewSpec,
    standards_package,
)

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "standards"
PROFILE = load_profile(FIXTURE_DIR / "profile-a.yaml")

DIMENSIONS_NOT_OVERRIDDEN = "standards.drawing.dimensions_not_overridden"
ANNOTATIONS_NOT_DANGLING = "standards.drawing.annotations_not_dangling"
REVISION_MATCHES = "standards.drawing.revision_matches"
NO_ITAR_STATEMENT = "standards.drawing.no_itar_statement"

DRAWING_CHECKS = (
    DIMENSIONS_NOT_OVERRIDDEN,
    ANNOTATIONS_NOT_DANGLING,
    REVISION_MATCHES,
    NO_ITAR_STATEMENT,
)

REVISION_PROPERTY = PROFILE.revision.property
HEADER_TEXT = PROFILE.revision.header_text
INITIAL = PROFILE.revision.initial
PHRASE = PROFILE.export_control.phrase

SHEET_FORMAT_VIEW = 1
"""`swDrawingViewTypes_e` 1, the sheet-format pseudo-view: the only place the macro ever
found the export-control statement (`contracts/rules.md`, research R3.3)."""

NOTE_ANNOTATION = 6
"""`swAnnotationType_e.swNote`, VERIFIED in research R3.3."""


# --- the fixtures -------------------------------------------------------------------------


def package_of(*documents: DocumentSpec, gaps: Sequence[Gap] = ()) -> EvidencePackage:
    return standards_package(documents=list(documents), profile=PROFILE, gaps=gaps)


def gap(entity_kind: str, entity_id: str | None, reason_text: str) -> Gap:
    return Gap(
        kind="not_extracted",
        entity_kind=entity_kind,
        entity_id=entity_id,
        reason=reason_text,
        error=None,
    )


def format_view(**kwargs: object) -> ViewSpec:
    """The sheet-format pseudo-view every compliant sheet records."""
    return ViewSpec(name="Sheet Format1", view_type_raw=SHEET_FORMAT_VIEW, **kwargs)  # type: ignore[arg-type]


def drawing(
    *sheets: SheetSpec, revision: str | None = "B", name: str = "MR-40000"
) -> DrawingSpec:
    """A drawing document carrying the profile's revision property, or none."""
    return DrawingSpec(
        name=name,
        properties={} if revision is None else {REVISION_PROPERTY: revision},
        active_sheet=sheets[0].name if sheets else None,
        sheets=sheets,
    )


def referenced_part(revision: str | None = "B", name: str = "MR-40021") -> PartSpec:
    return PartSpec(name, properties={} if revision is None else {REVISION_PROPERTY: revision})


def evaluate(
    package: EvidencePackage,
    document_id: str = "doc:1",
    profile: StandardsProfile = PROFILE,
) -> list[RuleResult]:
    """Every drawing check over one graded drawing document of `package`."""
    document = next(
        checked
        for checked in graded_documents(package, profile)
        if checked.document_id == document_id
    )
    return evaluate_drawing(document, package, profile)


def row(results: Sequence[RuleResult], check: str, outcome: str) -> RuleResult:
    found = [
        result for result in results if result.rule_id == check and result.outcome == outcome
    ]
    assert len(found) == 1, (
        f"expected one {outcome!r} result for {check}, got "
        f"{[(result.rule_id, result.outcome) for result in results if result.rule_id == check]}"
    )
    return found[0]


def rows(results: Sequence[RuleResult], check: str, outcome: str) -> list[RuleResult]:
    return [
        result for result in results if result.rule_id == check and result.outcome == outcome
    ]


def outcomes(results: Sequence[RuleResult], check: str) -> set[str]:
    return {result.outcome for result in results if result.rule_id == check}


def observed(results: Sequence[RuleResult], check: str, outcome: str = "fail") -> str:
    result = row(results, check, outcome)
    assert result.result is not None
    return result.result.observed


def reason(results: Sequence[RuleResult], check: str, outcome: str) -> str:
    found = row(results, check, outcome)
    assert found.reason is not None
    return found.reason


def reasons(results: Sequence[RuleResult], check: str, outcome: str) -> str:
    """Every reason of that bucket joined, for a check that lands in it more than once."""
    return " ".join(
        result.reason or "" for result in rows(results, check, outcome)
    )


def with_profile(**revision: object) -> StandardsProfile:
    """The fixture profile with one `revision.*` field replaced (FR-001: still fictional)."""
    return PROFILE.model_copy(
        update={"revision": PROFILE.revision.model_copy(update=revision)}
    )


def ingested_sheet(document_id: str, page: int, source: str | None) -> DrawingSheet:
    """One sheet as the PDF ingest writes it, stamped or written before the stamp existed."""
    return DrawingSheet(
        document_id=document_id,
        sheet_name=f"Sheet{page}",
        page=page,
        scale=None,
        units="unknown",
        general_notes=[],
        dimensions=[],
        views=[],
        parse_status="text",
        parser="pdf-text",
        source=source,  # type: ignore[arg-type]
    )


def with_ingested(
    package: EvidencePackage,
    document_id: str = "doc:1",
    pages: int = 1,
    source: str | None = "pdf_ingest",
) -> EvidencePackage:
    """`package` with PDF-ingested sheet evidence for `document_id` in `drawings[]`."""
    return package.model_copy(
        update={
            "drawings": [
                ingested_sheet(document_id, page, source) for page in range(1, pages + 1)
            ]
        }
    )


# --- standards.drawing.dimensions_not_overridden -------------------------------------------


class TestDimensionsNotOverridden:
    """FR-018: no display dimension carries a manual override."""

    def drawing_with(
        self, *dimensions: DimensionSpec, gaps: Sequence[Gap] = ()
    ) -> EvidencePackage:
        return package_of(
            drawing(
                SheetSpec(
                    name="Sheet1",
                    was_active=True,
                    views=(
                        format_view(),
                        ViewSpec(name="Drawing View1", dimensions=dimensions),
                    ),
                )
            ),
            gaps=gaps,
        )

    def test_an_overridden_dimension_fails_naming_sheet_view_dimension_and_value(
        self,
    ) -> None:
        package = self.drawing_with(
            DimensionSpec(
                name="D1@Sketch1", is_overridden=True, value_mm=10.0, override_mm=12.7
            )
        )
        results = evaluate(package)
        text = observed(results, DIMENSIONS_NOT_OVERRIDDEN)

        assert outcomes(results, DIMENSIONS_NOT_OVERRIDDEN) == {"fail"}
        assert "Sheet1" in text
        assert "Drawing View1" in text
        assert "D1@Sketch1" in text
        assert "12.7 mm" in text

    def test_an_angular_override_is_rendered_in_the_unit_the_package_recorded(self) -> None:
        """Difference p: the macro multiplied by a thousand assuming metres."""
        package = self.drawing_with(
            DimensionSpec(
                name="A1@Sketch1",
                is_overridden=True,
                dimension_type_raw=3,
                value_mm=None,
                value_degrees=30.0,
                override_degrees=45.0,
            )
        )

        assert "45 deg" in observed(evaluate(package), DIMENSIONS_NOT_OVERRIDDEN)

    def test_a_model_owned_dimension_is_not_excluded(self) -> None:
        """An overridden model-item dimension is the defect being hunted, not an exemption."""
        package = self.drawing_with(
            DimensionSpec(
                name="D1@Sketch1@MR-40021.SLDPRT", is_overridden=True, override_mm=8.0
            )
        )
        results = evaluate(package)

        assert outcomes(results, DIMENSIONS_NOT_OVERRIDDEN) == {"fail"}
        assert "D1@Sketch1@MR-40021.SLDPRT" in observed(results, DIMENSIONS_NOT_OVERRIDDEN)

    def test_six_overridden_dimensions_are_one_finding_with_six_subjects(self) -> None:
        """SC-006: one finding, six subjects, one error - not six errors (FR-003)."""
        package = self.drawing_with(
            *(
                DimensionSpec(name=f"D{number}", is_overridden=True, override_mm=number)
                for number in range(1, 7)
            )
        )
        results = evaluate(package)
        result = row(results, DIMENSIONS_NOT_OVERRIDDEN, "fail")

        assert len(result.subjects) == 6
        assert len(rows(results, DIMENSIONS_NOT_OVERRIDDEN, "fail")) == 1

    def test_a_dimension_on_a_later_sheet_is_read(self) -> None:
        """Difference q: every sheet is read, not only the active one."""
        package = package_of(
            drawing(
                SheetSpec(name="Sheet1", was_active=True, views=(format_view(),)),
                SheetSpec(
                    name="Sheet3",
                    views=(
                        format_view(),
                        ViewSpec(
                            name="Detail A",
                            dimensions=(
                                DimensionSpec(
                                    name="D9", is_overridden=True, override_mm=4.5
                                ),
                            ),
                        ),
                    ),
                ),
            )
        )

        assert "Sheet3" in observed(evaluate(package), DIMENSIONS_NOT_OVERRIDDEN)

    def test_no_override_passes(self) -> None:
        package = self.drawing_with(DimensionSpec(name="D1", is_overridden=False))

        assert outcomes(evaluate(package), DIMENSIONS_NOT_OVERRIDDEN) == {"pass"}

    def test_a_drawing_with_no_dimensions_is_skipped(self) -> None:
        package = self.drawing_with()
        results = evaluate(package)

        assert outcomes(results, DIMENSIONS_NOT_OVERRIDDEN) == {"skip"}
        assert "no display dimension" in reason(results, DIMENSIONS_NOT_OVERRIDDEN, "skip")

    def test_a_null_flag_is_unresolved_naming_the_gap(self) -> None:
        package = self.drawing_with(
            DimensionSpec(name="D1", is_overridden=None),
            DimensionSpec(name="D2", is_overridden=False),
            gaps=[gap("dimension_override", "ddm:0001", "GetOverride threw")],
        )
        results = evaluate(package)

        assert outcomes(results, DIMENSIONS_NOT_OVERRIDDEN) == {"pass", "unresolved"}
        unread = row(results, DIMENSIONS_NOT_OVERRIDDEN, "unresolved")
        assert unread.subjects == ["ddm:0001"]
        assert "GetOverride threw" in (unread.reason or "")

    def test_an_override_whose_unit_is_unknown_is_unresolved_not_rendered(self) -> None:
        """A number with a guessed unit is the macro's bug; the dimension is unresolved."""
        package = self.drawing_with(
            DimensionSpec(name="D1", is_overridden=True, override_mm=None),
            gaps=[gap("dimension_unit", "ddm:0001", "the dimension type was not read")],
        )
        results = evaluate(package)

        assert outcomes(results, DIMENSIONS_NOT_OVERRIDDEN) == {"unresolved"}
        text = reason(results, DIMENSIONS_NOT_OVERRIDDEN, "unresolved")
        assert "unit" in text
        assert "the dimension type was not read" in text

    def test_an_unread_flag_with_no_gap_still_says_so(self) -> None:
        package = self.drawing_with(DimensionSpec(name="D1", is_overridden=None))

        assert "no gap" in reason(evaluate(package), DIMENSIONS_NOT_OVERRIDDEN, "unresolved")


# --- standards.drawing.annotations_not_dangling --------------------------------------------


class TestAnnotationsNotDangling:
    """FR-019: no annotation is dangling, whatever its type."""

    def drawing_with(
        self, *annotations: AnnotationSpec, gaps: Sequence[Gap] = ()
    ) -> EvidencePackage:
        return package_of(
            drawing(
                SheetSpec(
                    name="Sheet1",
                    was_active=True,
                    views=(
                        format_view(),
                        ViewSpec(name="Drawing View1", annotations=annotations),
                    ),
                )
            ),
            gaps=gaps,
        )

    def test_a_dangling_annotation_fails_naming_sheet_view_type_and_identity(self) -> None:
        package = self.drawing_with(
            AnnotationSpec(name="Note1", type_raw=NOTE_ANNOTATION, is_dangling=True)
        )
        results = evaluate(package)
        text = observed(results, ANNOTATIONS_NOT_DANGLING)

        assert outcomes(results, ANNOTATIONS_NOT_DANGLING) == {"fail"}
        assert "Sheet1" in text
        assert "Drawing View1" in text
        assert "Note1" in text
        assert str(NOTE_ANNOTATION) in text

    def test_any_annotation_type_is_graded(self) -> None:
        package = self.drawing_with(
            AnnotationSpec(name="GTol1", type_raw=11, is_dangling=True)
        )

        assert outcomes(evaluate(package), ANNOTATIONS_NOT_DANGLING) == {"fail"}

    def test_an_unnamed_annotation_is_still_a_subject_by_its_package_id(self) -> None:
        """Difference o: the macro emits the same unidentifiable sentence every time."""
        package = self.drawing_with(
            AnnotationSpec(name=None, type_raw=NOTE_ANNOTATION, is_dangling=True),
            gaps=[gap("annotation_identity", "dan:0001", "GetName returned nothing")],
        )
        results = evaluate(package)
        result = row(results, ANNOTATIONS_NOT_DANGLING, "fail")

        assert result.subjects == ["dan:0001"]
        assert "dan:0001" in observed(results, ANNOTATIONS_NOT_DANGLING)

    def test_no_dangling_annotation_passes(self) -> None:
        package = self.drawing_with(AnnotationSpec(name="Note1", is_dangling=False))

        assert outcomes(evaluate(package), ANNOTATIONS_NOT_DANGLING) == {"pass"}

    def test_a_drawing_with_no_annotations_is_skipped(self) -> None:
        results = evaluate(self.drawing_with())

        assert outcomes(results, ANNOTATIONS_NOT_DANGLING) == {"skip"}
        assert "no annotation" in reason(results, ANNOTATIONS_NOT_DANGLING, "skip")

    def test_a_null_flag_is_unresolved_naming_the_gap(self) -> None:
        package = self.drawing_with(
            AnnotationSpec(name="Note1", is_dangling=None),
            AnnotationSpec(name="Note2", is_dangling=False),
            gaps=[gap("annotation_dangling", "dan:0001", "IsDangling threw")],
        )
        results = evaluate(package)

        assert outcomes(results, ANNOTATIONS_NOT_DANGLING) == {"pass", "unresolved"}
        unread = row(results, ANNOTATIONS_NOT_DANGLING, "unresolved")
        assert unread.subjects == ["dan:0001"]
        assert "IsDangling threw" in (unread.reason or "")

    def test_an_annotation_on_a_later_sheet_is_read(self) -> None:
        package = package_of(
            drawing(
                SheetSpec(name="Sheet1", was_active=True, views=(format_view(),)),
                SheetSpec(
                    name="Sheet2",
                    views=(
                        format_view(),
                        ViewSpec(
                            name="Section B-B",
                            annotations=(AnnotationSpec(name="Bal1", is_dangling=True),),
                        ),
                    ),
                ),
            )
        )

        assert "Sheet2" in observed(evaluate(package), ANNOTATIONS_NOT_DANGLING)


# --- standards.drawing.revision_matches ----------------------------------------------------


class TestRevisionMatches:
    """FR-020: the table, the drawing's property and every referenced model's agree."""

    def table(self, revision: str | None = "B", **kwargs: object) -> RevisionTableSpec:
        """A two-row table whose last row's column 1 is `revision` (profile `revision.cell`)."""
        return RevisionTableSpec(
            rows=((HEADER_TEXT, "REV", "DATE"), ("1", revision, "2026-01-02")),
            header_index=0,
            **kwargs,  # type: ignore[arg-type]
        )

    def package(
        self,
        *,
        table: RevisionTableSpec | None = None,
        drawing_revision: str | None = "B",
        model_revision: str | None = "B",
        gaps: Sequence[Gap] = (),
        referenced: bool = True,
    ) -> EvidencePackage:
        sheet = SheetSpec(
            name="Sheet1",
            was_active=True,
            views=(
                format_view(),
                ViewSpec(
                    name="Drawing View1",
                    references="MR-40021" if referenced else None,
                ),
            ),
            revision_tables=() if table is None else (table,),
        )
        documents: list[DocumentSpec] = [drawing(sheet, revision=drawing_revision)]
        if referenced:
            documents.append(referenced_part(model_revision))
        return package_of(*documents, gaps=gaps)

    def test_an_agreeing_drawing_passes(self) -> None:
        results = evaluate(self.package(table=self.table()))

        assert outcomes(results, REVISION_MATCHES) == {"pass"}

    def test_the_check_is_a_warning(self) -> None:
        """`contracts/rules.md`: warning severity, reported as a suspected finding."""
        results = evaluate(self.package(table=self.table("C")))
        result = row(results, REVISION_MATCHES, "warn")

        assert result.result is not None
        assert result.result.status == "suspected"

    def test_no_revision_table_on_any_sheet_is_a_disagreement(self) -> None:
        results = evaluate(self.package(table=None))

        assert outcomes(results, REVISION_MATCHES) == {"warn"}
        assert "no revision table" in observed(results, REVISION_MATCHES, "warn")

    def test_the_missing_table_claim_counts_the_sheets_it_could_enumerate(self) -> None:
        """The count and the noun agree: what was searched is the enumerable sheets."""
        text = observed(evaluate(self.package(table=None)), REVISION_MATCHES, "warn")

        assert "the 1 native sheet(s)" in text
        assert "that could be enumerated" in text

    def test_a_missing_table_is_not_claimed_when_a_sheet_could_not_be_enumerated(
        self,
    ) -> None:
        """FR-029: an absence read off evidence that is missing is not a defect.

        The revision table may sit on the very sheet the dump could not enumerate, so the
        claim "no revision table on any sheet" is unresolved rather than a warning.
        """
        package = package_of(
            drawing(
                SheetSpec(
                    name="Sheet1",
                    was_active=True,
                    views=(
                        format_view(),
                        ViewSpec(name="Drawing View1", references="MR-40021"),
                    ),
                ),
                SheetSpec(name="Sheet2", views=()),
            ),
            referenced_part("B"),
            gaps=[
                gap(
                    "drawing_sheet_views",
                    "dsh:0002",
                    "GetViews came back empty on a non-active sheet",
                )
            ],
        )
        results = evaluate(package)

        assert "warn" not in outcomes(results, REVISION_MATCHES)
        text = reasons(results, REVISION_MATCHES, "unresolved")
        assert "no revision table" in text
        assert "1 further native sheet(s)" in text

    def test_a_referenced_model_that_is_not_loaded_is_unresolved_naming_it(self) -> None:
        """`contracts/ir-additions.md` 3.3: a null `referenced_document_id` beside a recorded
        `referenced_model_path` is the **not-loaded** case, which FR-020 makes unresolved -
        never a comparison that silently did not happen."""
        package = package_of(
            drawing(
                SheetSpec(
                    name="Sheet1",
                    was_active=True,
                    views=(
                        format_view(),
                        ViewSpec(name="Drawing View1", references="MR-40021"),
                        ViewSpec(
                            name="Drawing View2",
                            referenced_model_path="/vault/jobs/MR-49999.SLDPRT",
                        ),
                    ),
                    revision_tables=(self.table("B"),),
                ),
            ),
            referenced_part("B"),
            gaps=[
                gap(
                    "drawing_referenced_document",
                    "dvw:0003",
                    "the referenced model is not loaded in this session",
                )
            ],
        )
        results = evaluate(package)

        assert outcomes(results, REVISION_MATCHES) == {"pass", "unresolved"}
        text = reasons(results, REVISION_MATCHES, "unresolved")
        assert "/vault/jobs/MR-49999.SLDPRT" in text
        assert "Drawing View2" in text
        assert "Sheet1" in text
        assert "not loaded in this session" in text

    def test_a_drawing_whose_only_reference_is_unread_is_not_called_reference_free(
        self,
    ) -> None:
        """"References no document" is a real absence; an unread reference is not one."""
        package = package_of(
            drawing(
                SheetSpec(
                    name="Sheet1",
                    was_active=True,
                    views=(
                        format_view(),
                        ViewSpec(
                            name="Drawing View1",
                            referenced_model_path="/vault/jobs/MR-49999.SLDPRT",
                        ),
                    ),
                    revision_tables=(self.table("B"),),
                ),
            ),
        )
        results = evaluate(package)

        text = reasons(results, REVISION_MATCHES, "unresolved")
        assert "references no document" not in text
        assert "/vault/jobs/MR-49999.SLDPRT" in text

    def test_a_table_disagreeing_with_the_drawing_property_names_both_and_their_source(
        self,
    ) -> None:
        results = evaluate(self.package(table=self.table("C"), drawing_revision="B"))
        text = observed(results, REVISION_MATCHES, "warn")

        assert "'C'" in text
        assert "'B'" in text
        assert REVISION_PROPERTY in text
        assert "revision.cell" in text

    def test_the_drawing_property_disagreeing_with_a_referenced_model_is_named(self) -> None:
        results = evaluate(
            self.package(table=self.table("B"), drawing_revision="B", model_revision="C")
        )
        text = observed(results, REVISION_MATCHES, "warn")

        assert "MR-40021" in text
        assert "'C'" in text

    def test_one_finding_names_every_disagreement_it_found(self) -> None:
        results = evaluate(
            self.package(table=self.table("C"), drawing_revision="B", model_revision="D")
        )
        text = observed(results, REVISION_MATCHES, "warn")

        assert len(rows(results, REVISION_MATCHES, "warn")) == 1
        assert "'C'" in text
        assert "'D'" in text

    def test_comparison_is_case_insensitive(self) -> None:
        results = evaluate(
            self.package(table=self.table("b"), drawing_revision="B", model_revision="B")
        )

        assert outcomes(results, REVISION_MATCHES) == {"pass"}

    def test_a_header_only_table_reads_as_the_profile_initial(self) -> None:
        """Its last data row is still its header row, so the drawing is at `revision.initial`."""
        package = self.package(
            table=RevisionTableSpec(rows=((HEADER_TEXT, "REV", "DATE"),), header_index=0),
            drawing_revision=INITIAL,
            model_revision=INITIAL,
        )

        assert outcomes(evaluate(package), REVISION_MATCHES) == {"pass"}

    def test_a_header_only_table_disagreeing_with_the_property_is_reported(self) -> None:
        package = self.package(
            table=RevisionTableSpec(rows=((HEADER_TEXT, "REV", "DATE"),), header_index=0),
            drawing_revision="B",
            model_revision="B",
        )
        results = evaluate(package)

        assert outcomes(results, REVISION_MATCHES) == {"warn"}
        assert repr(INITIAL) in observed(results, REVISION_MATCHES, "warn")

    def test_an_empty_cell_is_a_mismatch_and_is_never_normalized_into_a_pass(self) -> None:
        results = evaluate(self.package(table=self.table("")))
        text = observed(results, REVISION_MATCHES, "warn")

        assert outcomes(results, REVISION_MATCHES) == {"warn"}
        assert "empty" in text

    def test_an_unread_cell_is_unresolved_and_not_an_empty_cell(self) -> None:
        package = self.package(
            table=RevisionTableSpec(
                rows=((HEADER_TEXT, "REV", "DATE"), ("1", None, "2026-01-02")),
                header_index=0,
            ),
            gaps=[gap("revision_table_read", "drv:0001", "Text[1, 1] threw")],
        )
        results = evaluate(package)

        assert "warn" not in outcomes(results, REVISION_MATCHES)
        assert "Text[1, 1] threw" in reasons(results, REVISION_MATCHES, "unresolved")

    def test_a_table_whose_cells_could_not_be_read_is_unresolved(self) -> None:
        package = self.package(
            table=RevisionTableSpec(rows=()),
            gaps=[gap("revision_table_read", "drv:0001", "the cast to ITableAnnotation failed")],
        )
        results = evaluate(package)

        assert "warn" not in outcomes(results, REVISION_MATCHES)
        text = reasons(results, REVISION_MATCHES, "unresolved")
        assert "drv:0001" in text
        assert "the cast to ITableAnnotation failed" in text

    def test_a_cell_the_table_does_not_reach_is_unresolved(self) -> None:
        """A `revision.cell` no row answers is a gap, not a revision of its own."""
        profile = with_profile(cell=PROFILE.revision.cell.model_copy(update={"row_from_end": 4}))
        results = evaluate(self.package(table=self.table()), profile=profile)

        assert "warn" not in outcomes(results, REVISION_MATCHES)
        assert "revision.cell" in reasons(results, REVISION_MATCHES, "unresolved")

    def test_every_sheet_is_compared(self) -> None:
        """Difference y: the macro reads the current sheet's table only."""
        package = package_of(
            drawing(
                SheetSpec(
                    name="Sheet1",
                    was_active=True,
                    views=(format_view(), ViewSpec(name="View1", references="MR-40021")),
                    revision_tables=(self.table("B"),),
                ),
                SheetSpec(
                    name="Sheet3",
                    views=(format_view(),),
                    revision_tables=(self.table("E"),),
                ),
            ),
            referenced_part("B"),
        )
        results = evaluate(package)

        assert outcomes(results, REVISION_MATCHES) == {"warn"}
        assert "'E'" in observed(results, REVISION_MATCHES, "warn")

    def test_a_current_revision_disagreement_names_both_readings_and_is_not_unresolved(
        self,
    ) -> None:
        """RK-4: the cell named by `revision.cell` is normative and both are reported."""
        package = self.package(table=self.table("B", current_revision_raw=""))
        results = evaluate(package)
        text = observed(results, REVISION_MATCHES, "warn")

        assert "unresolved" not in outcomes(results, REVISION_MATCHES)
        assert "CurrentRevision" in text
        assert "revision.cell" in text

    def test_an_agreeing_current_revision_is_not_a_disagreement(self) -> None:
        package = self.package(table=self.table("B", current_revision_raw="B"))

        assert outcomes(evaluate(package), REVISION_MATCHES) == {"pass"}

    def test_an_empty_revision_property_setting_is_skipped(self) -> None:
        profile = with_profile(property="")
        results = evaluate(self.package(table=self.table()), profile=profile)

        assert outcomes(results, REVISION_MATCHES) == {"skip"}
        assert (
            "the profile's revision.property is empty"
            in reason(results, REVISION_MATCHES, "skip")
        )

    def test_unread_drawing_properties_are_unresolved(self) -> None:
        package = self.package(
            table=self.table(),
            gaps=[gap("document", "doc:1", "GetAll3 threw on the drawing")],
        )
        results = evaluate(package)

        assert outcomes(results, REVISION_MATCHES) == {"unresolved"}
        assert "GetAll3 threw on the drawing" in reasons(results, REVISION_MATCHES, "unresolved")

    def test_unread_model_properties_are_unresolved_for_that_model_alone(self) -> None:
        package = self.package(
            table=self.table(),
            gaps=[gap("document", "doc:2", "GetAll3 threw on the model")],
        )
        results = evaluate(package)

        assert "warn" not in outcomes(results, REVISION_MATCHES)
        text = reasons(results, REVISION_MATCHES, "unresolved")
        assert "MR-40021" in text
        assert "GetAll3 threw on the model" in text

    def test_a_drawing_referencing_no_document_is_unresolved_for_the_model_comparison(
        self,
    ) -> None:
        """Difference f: the macro raises a run-time error here."""
        results = evaluate(self.package(table=self.table("C"), referenced=False))

        assert outcomes(results, REVISION_MATCHES) == {"warn", "unresolved"}
        assert "references no document" in reasons(results, REVISION_MATCHES, "unresolved")
        assert "'C'" in observed(results, REVISION_MATCHES, "warn")

    def test_a_model_recording_no_revision_property_is_a_disagreement(self) -> None:
        results = evaluate(self.package(table=self.table(), model_revision=None))
        text = observed(results, REVISION_MATCHES, "warn")

        assert "MR-40021" in text
        assert REVISION_PROPERTY in text


# --- standards.drawing.no_itar_statement ---------------------------------------------------


class TestNoItarStatement:
    """FR-021: the presence of the export-control phrase is the defect."""

    def drawing_with(
        self,
        *notes: NoteSpec,
        format_view_type: int | None = SHEET_FORMAT_VIEW,
        gaps: Sequence[Gap] = (),
    ) -> EvidencePackage:
        return package_of(
            drawing(
                SheetSpec(
                    name="Sheet1",
                    was_active=True,
                    views=(
                        ViewSpec(
                            name="Sheet Format1",
                            view_type_raw=format_view_type,
                            notes=notes,
                        ),
                    ),
                )
            ),
            gaps=gaps,
        )

    def test_the_phrase_is_a_finding_naming_the_sheet_and_the_note(self) -> None:
        package = self.drawing_with(NoteSpec(text=f"CONTAINS {PHRASE} DATA"))
        results = evaluate(package)
        text = observed(results, NO_ITAR_STATEMENT, "warn")

        assert outcomes(results, NO_ITAR_STATEMENT) == {"warn"}
        assert "Sheet1" in text
        assert "dnt:0001" in text

    def test_the_check_is_a_warning(self) -> None:
        package = self.drawing_with(NoteSpec(text=PHRASE))
        result = row(evaluate(package), NO_ITAR_STATEMENT, "warn")

        assert result.result is not None
        assert result.result.status == "suspected"

    def test_the_match_is_a_case_insensitive_substring(self) -> None:
        package = self.drawing_with(NoteSpec(text=f"see {PHRASE.lower()} notice"))

        assert outcomes(evaluate(package), NO_ITAR_STATEMENT) == {"warn"}

    def test_a_note_on_any_sheet_and_any_view_is_read(self) -> None:
        """Difference q: the macro scans the first view of the current sheet only."""
        package = package_of(
            drawing(
                SheetSpec(name="Sheet1", was_active=True, views=(format_view(),)),
                SheetSpec(name="Sheet2", views=(format_view(),)),
                SheetSpec(
                    name="Sheet3",
                    views=(
                        format_view(),
                        ViewSpec(name="Drawing View4", notes=(NoteSpec(text=PHRASE),)),
                    ),
                ),
            )
        )
        results = evaluate(package)

        assert outcomes(results, NO_ITAR_STATEMENT) == {"warn"}
        assert "Sheet3" in observed(results, NO_ITAR_STATEMENT, "warn")

    def test_every_carrying_note_is_named(self) -> None:
        package = self.drawing_with(
            NoteSpec(text=PHRASE), NoteSpec(text="TITLE"), NoteSpec(text=f"{PHRASE} again")
        )
        result = row(evaluate(package), NO_ITAR_STATEMENT, "warn")

        assert result.subjects == ["dnt:0001", "dnt:0003"]

    def test_a_drawing_with_readable_notes_and_no_phrase_is_checked(self) -> None:
        package = self.drawing_with(NoteSpec(text="TITLE BLOCK"))

        assert outcomes(evaluate(package), NO_ITAR_STATEMENT) == {"pass"}

    def test_a_drawing_with_no_notes_is_skipped_when_every_sheet_has_a_format_view(
        self,
    ) -> None:
        results = evaluate(self.drawing_with())

        assert outcomes(results, NO_ITAR_STATEMENT) == {"skip"}
        assert "no note" in reason(results, NO_ITAR_STATEMENT, "skip")

    def test_an_empty_phrase_setting_is_skipped(self) -> None:
        profile = PROFILE.model_copy(
            update={"export_control": PROFILE.export_control.model_copy(update={"phrase": ""})}
        )
        results = evaluate(self.drawing_with(NoteSpec(text="TITLE")), profile=profile)

        assert outcomes(results, NO_ITAR_STATEMENT) == {"skip"}
        assert (
            "the profile's export_control.phrase is empty"
            in reason(results, NO_ITAR_STATEMENT, "skip")
        )

    def test_an_unread_note_is_unresolved_and_never_a_pass(self) -> None:
        """An unread note cannot be shown not to carry the statement."""
        package = self.drawing_with(
            NoteSpec(text="TITLE"),
            NoteSpec(text=None),
            gaps=[gap("note_text", "dnt:0002", "GetText returned nothing")],
        )
        results = evaluate(package)

        assert outcomes(results, NO_ITAR_STATEMENT) == {"unresolved"}
        text = reasons(results, NO_ITAR_STATEMENT, "unresolved")
        assert "dnt:0002" in text
        assert "GetText returned nothing" in text

    def test_an_unread_note_does_not_hide_a_phrase_that_was_read(self) -> None:
        package = self.drawing_with(NoteSpec(text=PHRASE), NoteSpec(text=None))
        results = evaluate(package)

        assert "warn" in outcomes(results, NO_ITAR_STATEMENT)

    def test_an_unread_note_beside_a_found_phrase_is_still_unresolved(self) -> None:
        """FR-029: the phrase being present does not make the unread note readable.

        `contracts/rules.md` states this check's unresolved column unconditionally, and the
        granularity paragraph permits a finding for one subject beside unresolved coverage
        for another; dropping the coverage row would make an incomplete reading invisible on
        exactly the drawings that already carry a defect.
        """
        package = self.drawing_with(
            NoteSpec(text=PHRASE),
            NoteSpec(text=None),
            gaps=[gap("note_text", "dnt:0002", "GetText returned nothing")],
        )
        results = evaluate(package)

        assert outcomes(results, NO_ITAR_STATEMENT) == {"warn", "unresolved"}
        text = reasons(results, NO_ITAR_STATEMENT, "unresolved")
        assert "dnt:0002" in text
        assert "GetText returned nothing" in text

    def test_a_sheet_with_no_sheet_format_view_is_unresolved(self) -> None:
        """Zero notes must not read as "the phrase appears nowhere" (`contracts/rules.md`)."""
        results = evaluate(self.drawing_with(format_view_type=2))

        assert outcomes(results, NO_ITAR_STATEMENT) == {"unresolved"}
        text = reasons(results, NO_ITAR_STATEMENT, "unresolved")
        assert "Sheet1" in text
        assert "sheet-format" in text

    def test_a_sheet_with_no_format_view_is_unresolved_beside_readable_notes(self) -> None:
        package = package_of(
            drawing(
                SheetSpec(
                    name="Sheet1",
                    was_active=True,
                    views=(format_view(notes=(NoteSpec(text="TITLE"),)),),
                ),
                SheetSpec(name="Sheet2", views=(ViewSpec(name="View2", view_type_raw=2),)),
            )
        )
        results = evaluate(package)

        assert outcomes(results, NO_ITAR_STATEMENT) == {"unresolved"}
        assert "Sheet2" in reasons(results, NO_ITAR_STATEMENT, "unresolved")

    def test_a_sheet_with_no_format_view_beside_a_found_phrase_is_still_unresolved(
        self,
    ) -> None:
        """A sheet that was never looked at is unresolved whether or not another sheet
        carried the phrase (FR-024, FR-029)."""
        package = package_of(
            drawing(
                SheetSpec(
                    name="Sheet1",
                    was_active=True,
                    views=(format_view(notes=(NoteSpec(text=PHRASE),)),),
                ),
                SheetSpec(name="Sheet2", views=(ViewSpec(name="View2", view_type_raw=2),)),
            )
        )
        results = evaluate(package)

        assert outcomes(results, NO_ITAR_STATEMENT) == {"warn", "unresolved"}
        assert "Sheet2" in reasons(results, NO_ITAR_STATEMENT, "unresolved")


# --- native sheets only, decided per sheet (the preamble all four share) --------------------


class TestNativeSheetsOnly:
    """FR-024: a parser with known limits may not produce a demonstrated finding."""

    def native(self) -> EvidencePackage:
        """A drawing every one of whose four checks lands in exactly one bucket."""
        return package_of(
            drawing(
                SheetSpec(
                    name="Sheet1",
                    was_active=True,
                    views=(
                        format_view(notes=(NoteSpec(text="TITLE"),)),
                        ViewSpec(
                            name="Drawing View1",
                            references="MR-40021",
                            dimensions=(DimensionSpec(name="D1", is_overridden=False),),
                            annotations=(AnnotationSpec(name="N1", is_dangling=False),),
                        ),
                    ),
                    revision_tables=(
                        RevisionTableSpec(
                            rows=((HEADER_TEXT, "REV"), ("1", "B")), header_index=0
                        ),
                    ),
                )
            ),
            referenced_part("B"),
        )

    def test_a_drawing_with_no_native_sheet_is_unresolved_for_every_check(self) -> None:
        package = with_ingested(package_of(drawing()))
        results = evaluate(package)

        for check in DRAWING_CHECKS:
            assert outcomes(results, check) == {"unresolved"}, check
            assert "pdf_ingest" in reason(results, check, "unresolved")

    def test_a_sheet_written_before_the_stamp_is_read_as_pdf_ingest(self) -> None:
        package = with_ingested(package_of(drawing()), source=None)
        results = evaluate(package)

        for check in DRAWING_CHECKS:
            assert outcomes(results, check) == {"unresolved"}, check
            assert "not recorded" in reason(results, check, "unresolved")

    def test_a_drawing_with_no_sheet_evidence_at_all_is_unresolved_naming_the_gap(
        self,
    ) -> None:
        package = package_of(
            drawing(), gaps=[gap("drawing_sheet", "doc:1", "GetSheetNames returned nothing")]
        )
        results = evaluate(package)

        for check in DRAWING_CHECKS:
            assert outcomes(results, check) == {"unresolved"}, check
            assert "GetSheetNames returned nothing" in reason(results, check, "unresolved")

    def test_a_mixed_drawing_is_graded_on_its_native_sheets(self) -> None:
        results = evaluate(with_ingested(self.native(), pages=2))

        assert "pass" in outcomes(results, DIMENSIONS_NOT_OVERRIDDEN)
        assert "pass" in outcomes(results, ANNOTATIONS_NOT_DANGLING)

    def test_a_mixed_drawing_carries_one_extra_unresolved_row_per_check(self) -> None:
        results = evaluate(with_ingested(self.native(), pages=2))

        for check in DRAWING_CHECKS:
            extra = rows(results, check, "unresolved")
            assert len(extra) == 1, check
            assert "pdf_ingest" in (extra[0].reason or "")
            assert "Sheet1" in (extra[0].reason or "")

    def test_a_native_only_drawing_carries_no_such_row(self) -> None:
        results = evaluate(self.native())

        for check in DRAWING_CHECKS:
            assert rows(results, check, "unresolved") == [], check

    def test_a_non_enumerable_sheet_is_unresolved_for_every_check_and_is_not_graded(
        self,
    ) -> None:
        package = package_of(
            drawing(
                SheetSpec(
                    name="Sheet1",
                    was_active=True,
                    views=(
                        format_view(),
                        ViewSpec(name="Drawing View1", references="MR-40021"),
                    ),
                    revision_tables=(
                        RevisionTableSpec(
                            rows=((HEADER_TEXT, "REV"), ("1", "B")), header_index=0
                        ),
                    ),
                ),
                SheetSpec(name="Sheet2", views=()),
            ),
            referenced_part("B"),
            gaps=[
                gap(
                    "drawing_sheet_views",
                    "dsh:0002",
                    "GetViews came back empty on a non-active sheet",
                )
            ],
        )
        results = evaluate(package)

        for check in DRAWING_CHECKS:
            unread = rows(results, check, "unresolved")
            assert len(unread) == 1, check
            assert "Sheet2" in (unread[0].reason or "")
            assert "GetViews came back empty" in (unread[0].reason or "")

    def test_nothing_is_graded_when_every_sheet_is_non_enumerable(self) -> None:
        package = package_of(
            drawing(SheetSpec(name="Sheet1", was_active=True, views=())),
            gaps=[gap("drawing_sheet_views", "dsh:0001", "GetViews threw")],
        )
        results = evaluate(package)

        for check in DRAWING_CHECKS:
            assert outcomes(results, check) == {"unresolved"}, check

    def test_a_part_document_is_refused(self) -> None:
        package = package_of(PartSpec("MR-40021"))
        document = next(iter(graded_documents(package, PROFILE)))

        with pytest.raises(ValueError, match="drawing"):
            evaluate_drawing(document, package, PROFILE)

    def test_a_drawing_reached_through_no_instance_is_graded(self) -> None:
        """A drawing is never instantiated as a component, so FR-005's document-evidence
        half never blocks it."""
        package = package_of(
            drawing(
                SheetSpec(
                    name="Sheet1",
                    was_active=True,
                    views=(format_view(), ViewSpec(name="View1", references="MR-40100")),
                )
            ),
            AssemblySpec(name="MR-40100"),
        )
        results = evaluate(package)

        assert outcomes(results, ANNOTATIONS_NOT_DANGLING) == {"skip"}
