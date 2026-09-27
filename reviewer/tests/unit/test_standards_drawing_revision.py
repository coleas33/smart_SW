"""The revision check stays honest about a revision table the dump did not read (013 T128).

Feature 013's `contracts/readings.md` section 2 (FR-050): `standards.drawing.revision_matches`
claims "no revision table was found" - a warning finding - only when every graded sheet was
fully walked, each recorded its own (type 1) view, and none carries a `revision_table_read`
gap. A sheet the extractor flagged (its `ISheet.RevisionTable` cross-check: the sheet reports a
table its view walk did not find) or a sheet that recorded no view of its own - the view a
revision table is anchored on, which `ISheet.GetViews` leaves out - makes the absence
**unresolved**, citing the gap, and never a finding. The property-to-model comparison still
runs beside it and can pass on its own.

The seat's case (2026-09-26): a plate drawing's sheet reported a revision table, none of its 14
views was the sheet's own, and the check asserted absence against the extractor's own warning.

Every value here is fictional (`FICT-`), and the profile is the fixture profile.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from swreview.checks.standards.drawing import evaluate_drawing
from swreview.checks.standards.profile import load_profile
from swreview.checks.standards.results import NO_GAP, RuleResult
from swreview.checks.standards.traversal import graded_documents
from swreview.ir.models import EvidencePackage, Gap
from tests.support.standards import (
    DrawingSpec,
    PartSpec,
    RevisionTableSpec,
    SheetSpec,
    ViewSpec,
    standards_package,
)

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "standards"
PROFILE = load_profile(FIXTURE_DIR / "profile-a.yaml")
REVISION_PROPERTY = PROFILE.revision.property
REVISION_MATCHES = "standards.drawing.revision_matches"

SHEET_OWN_VIEW = 1
"""`swDrawingViewTypes_e.swDrawingSheet`: the sheet's own view, where a revision table sits."""

CROSS_CHECK = (
    "Sheet 'Sheet1' reports a revision table that the view walk did not find, so its rows "
    "were not read and the revision check is unresolved for it."
)
"""The extractor's own cross-check gap (`DrawingDumper.CrossCheckRevisionTable`), verbatim."""

FALLBACK = (
    "The first view the drawing's GetViews gave for sheet 'Sheet1' is of type 4, not the "
    "sheet's own view (type 1); so the views of sheet 'Sheet1' were read through "
    "ISheet.GetViews, which leaves out the sheet's own view and whatever is on it."
)
"""The extractor's `drawing_sheet_view` gap for a sheet read on the fallback (013 T127)."""


# --- the fixtures -------------------------------------------------------------------------


def own_view() -> ViewSpec:
    return ViewSpec(name="Sheet1", view_type_raw=SHEET_OWN_VIEW)


def drawing_view() -> ViewSpec:
    return ViewSpec(name="Drawing View1", references="FICT-PLATE")


def table(revision: str = "B") -> RevisionTableSpec:
    header = PROFILE.revision.header_text
    return RevisionTableSpec(rows=((header, "REV", "DATE"), ("1", revision, "2026-01-02")))


def package(
    *views: ViewSpec,
    tables: Sequence[RevisionTableSpec] = (),
    gaps: Sequence[tuple[str, str, str]] = (),
    model_revision: str = "B",
) -> EvidencePackage:
    """One drawing of one active sheet, referencing one part; `gaps` name the sheet's own
    gaps as (entity kind, gap kind, reason), attached to the sheet's id."""
    sheet = SheetSpec(name="Sheet1", was_active=True, views=views, revision_tables=tables)
    documents = [
        DrawingSpec(
            name="FICT-PLATE-DRW",
            properties={REVISION_PROPERTY: "B"},
            active_sheet="Sheet1",
            sheets=(sheet,),
        ),
        PartSpec("FICT-PLATE", properties={REVISION_PROPERTY: model_revision}),
    ]
    built = standards_package(documents=documents, profile=PROFILE)
    sheet_id = built.drawing_records[0].sheets[0].id
    return built.model_copy(
        update={
            "gaps": [
                *built.gaps,
                *(
                    Gap(
                        kind=kind,
                        entity_kind=entity_kind,
                        entity_id=sheet_id,
                        reason=reason,
                        error=None,
                    )
                    for entity_kind, kind, reason in gaps
                ),
            ]
        }
    )


def evaluate(built: EvidencePackage) -> list[RuleResult]:
    document = next(
        checked for checked in graded_documents(built, PROFILE) if checked.document_id == "doc:1"
    )
    return [
        result
        for result in evaluate_drawing(document, built, PROFILE)
        if result.rule_id == REVISION_MATCHES
    ]


def outcomes(results: Sequence[RuleResult]) -> list[str]:
    return sorted(result.outcome for result in results)


def only(results: Sequence[RuleResult], outcome: str) -> RuleResult:
    [found] = [result for result in results if result.outcome == outcome]
    return found


def unresolved_reason(results: Sequence[RuleResult]) -> str:
    reason = only(results, "unresolved").reason
    assert reason is not None
    return reason


# --- the absence is claimed only over a complete walk ---------------------------------------


def test_the_cross_check_gap_and_no_table_is_unresolved_citing_it_and_no_finding() -> None:
    results = evaluate(
        package(
            own_view(), drawing_view(), gaps=[("revision_table_read", "not_extracted", CROSS_CHECK)]
        )
    )

    assert "warn" not in outcomes(results)
    reason = unresolved_reason(results)
    assert "no revision table was found" in reason
    assert "revision_table_read" in reason
    assert CROSS_CHECK in reason
    assert "'Sheet1'" in reason


def test_a_sheet_with_no_own_view_and_no_table_is_unresolved() -> None:
    """Before 013's extractor no sheet recorded its own view at all, so a package dumped then
    never supports the absence: its revision table may sit on the view that was not read."""
    results = evaluate(package(drawing_view()))

    assert "warn" not in outcomes(results)
    reason = unresolved_reason(results)
    assert "no revision table was found" in reason
    assert "recorded no view of its own (type 1)" in reason
    assert NO_GAP in reason


def test_a_sheet_read_on_the_fallback_cites_its_sheet_view_gap() -> None:
    view = ViewSpec(name="Drawing View1", view_type_raw=4, references="FICT-PLATE")
    results = evaluate(package(view, gaps=[("drawing_sheet_view", "not_extracted", FALLBACK)]))

    assert "warn" not in outcomes(results)
    reason = unresolved_reason(results)
    assert "recorded no view of its own (type 1)" in reason
    assert "drawing_sheet_view" in reason
    assert FALLBACK in reason


def test_a_complete_walk_with_the_sheets_own_view_and_no_table_is_the_warning() -> None:
    results = evaluate(package(own_view(), drawing_view()))

    assert outcomes(results) == ["warn"]
    finding = only(results, "warn").result
    assert finding is not None
    assert "no revision table was found on the 1 native sheet(s)" in finding.observed


def test_the_property_comparison_passing_beside_an_unresolved_table_gives_both_rows() -> None:
    """The drawing's property agrees with the model's, which is a pass of its own; the table
    that was not read is an unresolved row beside it, not a reason to drop the pass."""
    results = evaluate(
        package(
            own_view(), drawing_view(), gaps=[("revision_table_read", "not_extracted", CROSS_CHECK)]
        )
    )

    assert outcomes(results) == ["pass", "unresolved"]


def test_a_disagreeing_property_beside_an_unresolved_table_is_the_finding_and_the_row() -> None:
    """A real disagreement between the drawing and its model is still a finding; only the
    absence of a table is withheld."""
    results = evaluate(
        package(
            own_view(),
            drawing_view(),
            gaps=[("revision_table_read", "not_extracted", CROSS_CHECK)],
            model_revision="C",
        )
    )

    assert outcomes(results) == ["unresolved", "warn"]
    finding = only(results, "warn").result
    assert finding is not None
    assert "no revision table" not in finding.observed
    assert "FICT-PLATE" in finding.observed


def test_an_unenumerable_sheet_and_an_unread_table_are_both_named() -> None:
    """Every reason the absence is withheld is said, the old one in its old words."""
    sheets = (
        SheetSpec(name="Sheet1", was_active=True, views=(drawing_view(),)),
        SheetSpec(name="Sheet2", views=()),
    )
    built = standards_package(
        documents=[
            DrawingSpec(
                name="FICT-PLATE-DRW",
                properties={REVISION_PROPERTY: "B"},
                active_sheet="Sheet1",
                sheets=sheets,
            ),
            PartSpec("FICT-PLATE", properties={REVISION_PROPERTY: "B"}),
        ],
        profile=PROFILE,
    )
    second = built.drawing_records[0].sheets[1].id
    built = built.model_copy(
        update={
            "gaps": [
                *built.gaps,
                Gap(
                    kind="not_extracted",
                    entity_kind="drawing_sheet_views",
                    entity_id=second,
                    reason="Sheet 'Sheet2' was not the active sheet and listed no drawing views.",
                    error=None,
                ),
            ]
        }
    )

    reasons = " ".join(
        result.reason or "" for result in evaluate(built) if result.outcome == "unresolved"
    )

    assert "the contents of 1 further native sheet(s) could not be read" in reasons
    assert "sheet 'Sheet1' may carry one that was not read" in reasons


def test_the_export_control_check_cites_the_fallback_gap_for_a_sheet_with_no_own_view() -> None:
    """The one explanation of a missing own view, shared by both checks that need it."""
    view = ViewSpec(name="Drawing View1", view_type_raw=4, references="FICT-PLATE")
    built = package(view, gaps=[("drawing_sheet_view", "not_extracted", FALLBACK)])
    document = next(
        checked for checked in graded_documents(built, PROFILE) if checked.document_id == "doc:1"
    )

    [blind] = [
        result
        for result in evaluate_drawing(document, built, PROFILE)
        if result.rule_id == "standards.drawing.no_itar_statement"
        and result.outcome == "unresolved"
    ]

    assert blind.reason is not None
    assert FALLBACK in blind.reason


def test_a_table_that_was_read_is_compared_as_before() -> None:
    """A table on the sheet's own view that was read is the reading the check compares."""
    results = evaluate(package(own_view(), drawing_view(), tables=[table("B")]))

    assert outcomes(results) == ["pass"]
