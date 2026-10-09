"""Unit tests for the fastener joint checks (T083).

These pin FR-023 and FR-024 and the acceptance scenarios of US5: a bottoming margin and
an engagement ratio computed from the screw length, the clamped stack, the washers and
the usable thread depth; an unknown input that stays unknown; a thread mismatch reported
as demonstrated; and a joint kind the pilot does not support reported as out of scope,
never as passed.
"""

from __future__ import annotations

import pytest
from pint import DimensionalityError

from swreview.checks.engagement_rules import load_rules
from swreview.checks.fastener import (
    FUNCTION_VERSION,
    ClampedLayer,
    check_fastener_joint,
    is_pipe_thread,
    nominal_diameter,
    parse_thread,
)
from swreview.checks.result import CheckResult
from swreview.ir.models import Angle, Axis, Fastener, Hole, Quantity, Vec3
from tests.support.packages import persist_ref

AXIS = Axis(origin=Vec3(x=0.0, y=0.0, z=0.01), direction=Vec3(x=0.0, y=0.0, z=1.0))


def mm(value: float) -> Quantity:
    return Quantity(value=value, unit="mm")


M6X20 = mm(20.0)
THREAD_DEPTH_12 = mm(12.0)


def screw(
    *,
    kind: str = "screw",
    thread: str | None = "M6x1.0",
    length: Quantity | None = M6X20,
) -> Fastener:
    return Fastener(
        id="fst:1",
        persist_ref=persist_ref("fst:1"),
        persist_ref_scope="doc:1",
        component_id="cmp:0002",
        kind=kind,  # type: ignore[arg-type]
        identity_source="toolbox",
        thread_designation=thread,
        length=length,
        head_type="socket head cap",
        head_diameter=mm(10.0),
        head_height=mm(6.0),
        drive="hex",
        axis=AXIS,
        material="Alloy Steel",
    )


def tapped_hole(
    *,
    thread: str | None = "M6x1.0",
    thread_depth: Quantity | None = THREAD_DEPTH_12,
    end_condition: str = "blind",
) -> Hole:
    return Hole(
        id="hole:1",
        persist_ref=persist_ref("hole:1"),
        persist_ref_scope="doc:2",
        component_id="cmp:0001",
        feature_name="M6 Tapped Hole1",
        hole_type="tapped",
        standard="ISO",
        size="M6",
        thread_designation=thread,
        thread_depth=thread_depth,
        hole_depth=mm(15.0),
        end_condition=end_condition,  # type: ignore[arg-type]
        diameter=mm(5.0),
        axis=AXIS,
        face_ids=[],
    )


def layer(thickness: Quantity | None, component_id: str = "cmp:0003") -> ClampedLayer:
    return ClampedLayer(component_id=component_id, thickness=thickness, material="6061-T6")


def by_check(results: list[CheckResult]) -> dict[str, CheckResult]:
    assert len({result.check for result in results}) == len(results), "duplicate check name"
    return {result.check: result for result in results}


# --- thread designation parsing ---------------------------------------------------


@pytest.mark.parametrize(
    ("designation", "expected_mm"),
    [
        ("M6x1.0", 6.0),
        ("M6 x 1", 6.0),
        ("M6", 6.0),
        ("M3.5x0.6", 3.5),
        ("M10X1.5", 10.0),
        ("1/4-20", 6.35),
        ("1/4-20 UNC", 6.35),
        ("#10-32", 4.826),
        ("0.190-32", 4.826),
    ],
)
def test_nominal_diameter_is_parsed_from_the_designation(
    designation: str, expected_mm: float
) -> None:
    diameter = nominal_diameter(designation)

    assert diameter is not None
    assert diameter.unit == "mm"
    assert diameter.value == pytest.approx(expected_mm, abs=1e-3)


def test_an_unrecognised_designation_has_no_nominal_diameter() -> None:
    assert nominal_diameter("NPT 1/8") is None
    assert nominal_diameter("") is None


def test_the_same_thread_written_two_ways_parses_to_one_canonical_form() -> None:
    assert parse_thread("M6x1.0").normalized == parse_thread("m6 X 1").normalized


def test_a_thread_without_a_pitch_is_not_the_same_text_as_one_with_a_pitch() -> None:
    assert parse_thread("M6").normalized != parse_thread("M6x1.0").normalized


# The fine pitch amendment's vectors (contracts/fasteners.md 8.8 and 8.9, the "Read as" column).


@pytest.mark.parametrize(
    ("designation", "diameter_mm", "pitch_mm"),
    [
        ("M8x1.25", 8.0, 1.25),
        ("M8 x 1.25", 8.0, 1.25),
        ("M8x1.25-6g", 8.0, 1.25),
        ("M8x1.25-6G", 8.0, 1.25),
        # Whitespace is removed before reading, so a grade written after a space joins the
        # pitch: a known limit (research R2.26), flagged non-standard, never passed.
        ("M8x1.25 6H", 8.0, 1.256),
        # Rule 1: a comma between two digits is a decimal point.
        ("M8x1,25", 8.0, 1.25),
        ("M8-1,25", 8.0, 1.25),
        # Rule 3: a hyphen number is the pitch before the end, a separator, a length or the hand.
        ("M8-1.25", 8.0, 1.25),
        ("M10-1.5-6H", 10.0, 1.5),
        ("M4-0.7x12", 4.0, 0.7),
        ("M8-1 x 20", 8.0, 1.0),
        ("M8-1×20", 8.0, 1.0),
        ("M10-1.25LH", 10.0, 1.25),
        ("M8-1.25rh", 8.0, 1.25),
        ("M8-1", 8.0, 1.0),
        # ...and no pitch only before a tolerance class.
        ("M8-6H", 8.0, None),
        ("M8-6g", 8.0, None),
        ("M8-6g6h", 8.0, None),
        ("M8", 8.0, None),
        # Rule 2: the multiplication sign is a pitch marker like x and *.
        ("M8×1", 8.0, 1.0),
        ("M8*1.25", 8.0, 1.25),
        ("M6x1", 6.0, 1.0),
        ("M7x1", 7.0, 1.0),
        ("M3.5x0.6", 3.5, 0.6),
        ("M8x1", 8.0, 1.0),
        ("m8x1", 8.0, 1.0),
        ("M8x1.0", 8.0, 1.0),
        ("M8x0.75", 8.0, 0.75),
        ("M10x1.25", 10.0, 1.25),
        ("M12x1.5", 12.0, 1.5),
        ("M25x1.5", 25.0, 1.5),
        ("M25", 25.0, None),
        ("M5.5x0.5", 5.5, 0.5),
        ("M8x1.5", 8.0, 1.5),
        ("M10x35", 10.0, 35.0),
        ("M2.3x0.4", 2.3, 0.4),
        ("M70", 70.0, None),
    ],
)
def test_a_metric_designation_reads_its_diameter_and_pitch(
    designation: str, diameter_mm: float, pitch_mm: float | None
) -> None:
    thread = parse_thread(designation)

    assert thread.series == "metric"
    assert thread.nominal_diameter == Quantity(value=diameter_mm, unit="mm")
    if pitch_mm is None:
        assert thread.pitch_mm is None
    else:
        assert thread.pitch_mm == pytest.approx(pitch_mm, abs=1e-9)


@pytest.mark.parametrize(
    ("designation", "diameter_in", "threads_per_inch"),
    [
        ("1/4-20", 0.25, 20),
        ("1/4-20 UNC-2B", 0.25, 20),
        ("1/4-20 UNF", 0.25, 20),
        ("0.250-20", 0.25, 20),
        ("#6-32", 0.138, 32),
        ("#10-24", 0.190, 24),
        ("1.000-8", 1.0, 8),
        ("1/4-28", 0.25, 28),
        ("1/4-28 UNF-2A", 0.25, 28),
        ("1/4-32", 0.25, 32),
        ("#10-32", 0.190, 32),
        ("#10-32 UNF", 0.190, 32),
        ("0.190-32", 0.190, 32),
        ("1.125-8", 1.125, 8),
        ("#0-80", 0.060, 80),
        ("1/4-18", 0.25, 18),
        ("1/8-27", 0.125, 27),
        # parse_thread does not change for pipe text; is_pipe_thread is what tells it apart.
        ("1/8-27 NPT", 0.125, 27),
        ("1/2-14 NPTF", 0.5, 14),
    ],
)
def test_a_unified_designation_reads_as_it_did(
    designation: str, diameter_in: float, threads_per_inch: int
) -> None:
    thread = parse_thread(designation)

    assert thread.series == "unified"
    assert thread.nominal_diameter is not None
    assert thread.nominal_diameter.value == pytest.approx(diameter_in * 25.4, abs=1e-6)
    assert thread.pitch_mm == pytest.approx(25.4 / threads_per_inch, abs=1e-6)


@pytest.mark.parametrize(
    "designation",
    [
        # Read as M8-1.256G, and 1.256G is no tolerance class: a known limit (research R2.26).
        "M8-1.25 6g",
        # Rule 3: any other letter after a hyphen number.
        "M10-1.25G",
        "M8-1x",
        "M8-1.25×",
        # Rule 4: a pitch marker straight after the size with no number after it.
        "M16xPh3P1.5",
        "M8x",
        "M8*",
        "M8×",
        "MF8x1",
        "3/8",
        "1-8",
        "1-1/8-7",
        "10-32",
        "No. 10-32",
        "",
        # Pipe text parse_thread does not read, as before.
        "NPT 1/8",
        "3/4 NPSM",
        "1/2 NPS",
        "G1/4",
        "G 1/2 A",
        "R1/4",
        "Rc1/4",
        "Rp 1/2",
        "PT1/8",
        "PF1/4",
        "1/4 BSPP",
        "1/4 BSPT",
        "1/2 BSP",
    ],
)
def test_a_designation_whose_size_or_pitch_cannot_be_read_is_unrecognised(
    designation: str,
) -> None:
    thread = parse_thread(designation)

    assert thread.series is None
    assert thread.nominal_diameter is None
    assert thread.pitch_mm is None


PIPE_THREADS = [
    "1/8-27 NPT",
    "NPT 1/8",
    "1/2-14 NPTF",
    "3/4 NPSM",
    "1/2 NPS",
    "G1/4",
    "G 1/2 A",
    "R1/4",
    "Rc1/4",
    "Rp 1/2",
    "PT1/8",
    "PF1/4",
    "1/4 BSPP",
    "1/4 BSPT",
    "1/2 BSP",
]


@pytest.mark.parametrize(
    "designation",
    [*PIPE_THREADS, *(text.lower() for text in PIPE_THREADS), "  Rc 1/4  "],
)
def test_a_pipe_thread_is_recognised_by_its_token(designation: str) -> None:
    assert is_pipe_thread(designation) is True


@pytest.mark.parametrize(
    "designation",
    ["M8x1.25-6G", "M10x1.5-6g", "1/4-20 UNC-2B", "#10-32 UNF", "3/8", "M8", ""],
)
def test_a_screw_thread_or_a_bare_size_is_not_a_pipe_thread(designation: str) -> None:
    assert is_pipe_thread(designation) is False


# --- bottoming and engagement -----------------------------------------------------


def test_bottoming_margin_comes_from_length_stack_washer_and_thread_depth() -> None:
    # 20 - 1.5 - 1.6 = 16.9 mm into the hole; 12 - 16.9 = -4.9 mm of margin.
    results = by_check(
        check_fastener_joint(
            screw(length=mm(20.0)),
            tapped_hole(thread_depth=mm(12.0)),
            [layer(mm(1.5))],
            washers=[mm(1.6)],
            hole_material="6061-T6",
        )
    )
    bottoming = results["fastener.bottoming"]

    assert bottoming.status == "demonstrated"
    assert bottoming.severity == "high"
    assert bottoming.calculation is not None
    assert bottoming.calculation.model == "fastener.bottoming"
    assert bottoming.calculation.result["protrusion_mm"] == pytest.approx(16.9, abs=1e-9)
    assert bottoming.calculation.result["margin_mm"] == pytest.approx(-4.9, abs=1e-9)
    assert bottoming.calculation.units_out == "mm"
    assert bottoming.calculation.function_version == FUNCTION_VERSION


def test_a_screw_that_clamps_before_it_bottoms_is_checked_within_scope() -> None:
    results = by_check(
        check_fastener_joint(
            screw(length=mm(12.0)),
            tapped_hole(thread_depth=mm(12.0)),
            [layer(mm(3.0))],
            hole_material="6061-T6",
        )
    )
    bottoming = results["fastener.bottoming"]

    assert bottoming.status == "checked_within_scope"
    assert bottoming.calculation.result["margin_mm"] == pytest.approx(3.0, abs=1e-9)


def test_engagement_ratio_is_engagement_over_nominal_diameter() -> None:
    # protrusion 9 mm, thread depth 12 mm -> engagement 9 mm; 9 / 6 = 1.5 x d.
    results = by_check(
        check_fastener_joint(
            screw(length=mm(12.0)),
            tapped_hole(thread_depth=mm(12.0)),
            [layer(mm(3.0))],
            hole_material="6061-T6",
        )
    )
    engagement = results["fastener.engagement"]

    assert engagement.status == "checked_within_scope"
    assert engagement.calculation.result["engagement_mm"] == pytest.approx(9.0, abs=1e-9)
    assert engagement.calculation.result["ratio"] == pytest.approx(1.5, abs=1e-9)
    assert engagement.calculation.result["required_ratio"] == pytest.approx(1.5, abs=1e-9)


def test_engagement_is_capped_by_the_usable_thread_depth() -> None:
    """A screw that protrudes past the threads gains no engagement from the extra length."""
    results = by_check(
        check_fastener_joint(
            screw(length=mm(20.0)),
            tapped_hole(thread_depth=mm(8.0)),
            [layer(mm(1.5))],
            hole_material="AISI 1018 Steel",
        )
    )
    engagement = results["fastener.engagement"]

    assert engagement.calculation.result["engagement_mm"] == pytest.approx(8.0, abs=1e-9)
    # The ratio is rounded like every other reported number (`result.PLACES`).
    assert engagement.calculation.result["ratio"] == pytest.approx(8.0 / 6.0, abs=1e-6)


def test_engagement_below_the_material_rule_is_demonstrated() -> None:
    # protrusion 6 mm in aluminium: 6 / 6 = 1.0 x d against a 1.5 x d rule.
    results = by_check(
        check_fastener_joint(
            screw(length=mm(9.0)),
            tapped_hole(thread_depth=mm(12.0)),
            [layer(mm(3.0))],
            hole_material="6061-T6",
        )
    )
    engagement = results["fastener.engagement"]

    assert engagement.status == "demonstrated"
    assert engagement.severity == "high"
    assert engagement.calculation.result["ratio"] == pytest.approx(1.0, abs=1e-9)


def test_the_engagement_rule_is_chosen_by_the_hole_material_and_cited() -> None:
    """Edited deliberately by feature 010 T042: steel and aluminium are both 1.5 x d since the
    owner's decision of 2026-09-23, so the contrast is now steel (1.5) against plastic (2.5),
    on one joint engaging 12 mm of an M6 - 2.0 x d."""
    plastic = by_check(
        check_fastener_joint(
            screw(length=mm(15.0)),
            tapped_hole(thread_depth=mm(12.0)),
            [layer(mm(3.0))],
            hole_material="Nylon 6/6",
        )
    )["fastener.engagement"]
    steel = by_check(
        check_fastener_joint(
            screw(length=mm(15.0)),
            tapped_hole(thread_depth=mm(12.0)),
            [layer(mm(3.0))],
            hole_material="AISI 1018 Steel",
        )
    )["fastener.engagement"]

    assert plastic.calculation.result["ratio"] == pytest.approx(2.0, abs=1e-9)
    assert plastic.status == "demonstrated"
    assert steel.status == "checked_within_scope"

    rules = load_rules()
    assert rules.for_material("Nylon 6/6").source in " ".join(plastic.calculation.assumptions)
    assert plastic.calculation.inputs["material_class"] == "plastic"
    assert steel.calculation.inputs["material_class"] == "steel"
    assert rules.for_material("AISI 1018 Steel").source in " ".join(steel.calculation.assumptions)


def test_an_unknown_hole_material_leaves_engagement_unresolved() -> None:
    results = by_check(
        check_fastener_joint(
            screw(),
            tapped_hole(),
            [layer(mm(1.5))],
            hole_material="unobtainium",
        )
    )
    engagement = results["fastener.engagement"]

    assert engagement.status == "unresolved"
    assert any("material" in limit for limit in engagement.coverage_limits)
    # The measured engagement is still reported; only the verdict is withheld.
    assert engagement.calculation.result["engagement_mm"] == pytest.approx(12.0, abs=1e-9)


def test_a_missing_hole_material_leaves_engagement_unresolved() -> None:
    engagement = by_check(
        check_fastener_joint(screw(), tapped_hole(), [layer(mm(1.5))], hole_material=None)
    )["fastener.engagement"]

    assert engagement.status == "unresolved"


# --- unknown inputs stay unknown --------------------------------------------------


def test_an_unknown_thread_depth_leaves_bottoming_and_engagement_unresolved() -> None:
    results = by_check(
        check_fastener_joint(
            screw(),
            tapped_hole(thread_depth=None),
            [layer(mm(1.5))],
            hole_material="6061-T6",
        )
    )

    for name in ("fastener.bottoming", "fastener.engagement"):
        result = results[name]
        assert result.status == "unresolved", name
        assert any("usable thread depth" in limit for limit in result.coverage_limits), name


def test_a_missing_clamped_thickness_is_unresolved_and_names_the_component() -> None:
    results = by_check(
        check_fastener_joint(
            screw(),
            tapped_hole(),
            [layer(mm(1.5), "cmp:0003"), layer(None, "cmp:0004")],
            hole_material="6061-T6",
        )
    )
    bottoming = results["fastener.bottoming"]

    assert bottoming.status == "unresolved"
    assert any("cmp:0004" in limit for limit in bottoming.coverage_limits)
    assert not any("cmp:0003" in limit for limit in bottoming.coverage_limits)


def test_an_empty_clamped_stack_is_unresolved() -> None:
    """Zero clamped layers is not the same as a zero-thickness stack."""
    bottoming = by_check(
        check_fastener_joint(screw(), tapped_hole(), [], hole_material="6061-T6")
    )["fastener.bottoming"]

    assert bottoming.status == "unresolved"
    assert any("clamped" in limit for limit in bottoming.coverage_limits)


def test_an_unknown_screw_length_is_unresolved() -> None:
    bottoming = by_check(
        check_fastener_joint(
            screw(length=None), tapped_hole(), [layer(mm(1.5))], hole_material="6061-T6"
        )
    )["fastener.bottoming"]

    assert bottoming.status == "unresolved"
    assert any("length" in limit for limit in bottoming.coverage_limits)


def test_an_unknown_nominal_diameter_leaves_engagement_unresolved() -> None:
    engagement = by_check(
        check_fastener_joint(
            screw(thread="NPT 1/8"),
            tapped_hole(thread="NPT 1/8"),
            [layer(mm(1.5))],
            hole_material="6061-T6",
        )
    )["fastener.engagement"]

    assert engagement.status == "unresolved"
    assert any("nominal" in limit for limit in engagement.coverage_limits)


# --- through holes ----------------------------------------------------------------


def test_a_through_hole_cannot_bottom_and_is_checked_within_scope_with_a_note() -> None:
    bottoming = by_check(
        check_fastener_joint(
            screw(),
            tapped_hole(end_condition="through"),
            [layer(mm(1.5))],
            hole_material="6061-T6",
        )
    )["fastener.bottoming"]

    assert bottoming.status == "checked_within_scope"
    assert any("through" in limit for limit in bottoming.coverage_limits)


def test_an_unknown_end_condition_leaves_bottoming_unresolved() -> None:
    bottoming = by_check(
        check_fastener_joint(
            screw(),
            tapped_hole(end_condition="unknown"),
            [layer(mm(1.5))],
            hole_material="6061-T6",
        )
    )["fastener.bottoming"]

    assert bottoming.status == "unresolved"
    assert any("end condition" in limit for limit in bottoming.coverage_limits)


# --- thread match -----------------------------------------------------------------


def test_a_thread_mismatch_is_demonstrated_with_both_specifications() -> None:
    match = by_check(
        check_fastener_joint(
            screw(thread="M6x1.0"),
            tapped_hole(thread="M5x0.8"),
            [layer(mm(1.5))],
            hole_material="6061-T6",
        )
    )["fastener.thread_match"]

    assert match.status == "demonstrated"
    assert match.severity == "high"
    assert "M6x1.0" in match.observed
    assert "M5x0.8" in match.observed


def test_a_pitch_mismatch_at_the_same_diameter_is_demonstrated() -> None:
    match = by_check(
        check_fastener_joint(
            screw(thread="M6x1.0"),
            tapped_hole(thread="M6x0.75"),
            [layer(mm(1.5))],
            hole_material="6061-T6",
        )
    )["fastener.thread_match"]

    assert match.status == "demonstrated"


def test_a_matching_thread_is_checked_within_scope() -> None:
    match = by_check(
        check_fastener_joint(
            screw(thread="M6x1.0"),
            tapped_hole(thread="m6 X 1"),
            [layer(mm(1.5))],
            hole_material="6061-T6",
        )
    )["fastener.thread_match"]

    assert match.status == "checked_within_scope"


def test_a_pitch_known_on_only_one_side_does_not_manufacture_a_mismatch() -> None:
    match = by_check(
        check_fastener_joint(
            screw(thread="M6x1.0"),
            tapped_hole(thread="M6"),
            [layer(mm(1.5))],
            hole_material="6061-T6",
        )
    )["fastener.thread_match"]

    assert match.status == "checked_within_scope"


def test_a_missing_thread_designation_is_unresolved() -> None:
    for fastener_thread, hole_thread, expected in (
        (None, "M6x1.0", "fastener"),
        ("M6x1.0", None, "hole"),
    ):
        match = by_check(
            check_fastener_joint(
                screw(thread=fastener_thread),
                tapped_hole(thread=hole_thread),
                [layer(mm(1.5))],
                hole_material="6061-T6",
            )
        )["fastener.thread_match"]

        assert match.status == "unresolved"
        assert any(expected in limit for limit in match.coverage_limits)


def test_two_unrecognised_designations_are_unresolved_not_a_mismatch() -> None:
    match = by_check(
        check_fastener_joint(
            screw(thread="NPT 1/8"),
            tapped_hole(thread="BSPT 1/8"),
            [layer(mm(1.5))],
            hole_material="6061-T6",
        )
    )["fastener.thread_match"]

    assert match.status == "unresolved"


@pytest.mark.parametrize(
    ("screw_thread", "status"),
    [
        # Read pitch 1.0 before the fine pitch amendment: a false mismatch.
        ("M8x1,25", "checked_within_scope"),
        # Read no pitch before: matched on the diameter alone, with the one-sided-pitch limit.
        ("M8-1.25", "checked_within_scope"),
        # Read no pitch before: a missed mismatch.
        ("M8-1", "demonstrated"),
    ],
)
def test_the_parser_fixes_compare_the_pitch_of_the_thread_match(
    screw_thread: str, status: str
) -> None:
    match = by_check(
        check_fastener_joint(
            screw(thread=screw_thread),
            tapped_hole(thread="M8x1.25"),
            [layer(mm(1.5))],
            hole_material="6061-T6",
        )
    )["fastener.thread_match"]

    assert match.status == status
    assert match.calculation is not None
    assert match.calculation.result["pitch_compared"] is True
    assert match.calculation.result["matches"] is (status == "checked_within_scope")
    assert match.coverage_limits == []


def test_a_multi_start_thread_is_unresolved_in_the_thread_match_and_named() -> None:
    # Read as M16 with no pitch before the fine pitch amendment, a diameter-only match (D9).
    match = by_check(
        check_fastener_joint(
            screw(thread="M16xPh3P1.5"),
            tapped_hole(thread="M16x1.5"),
            [layer(mm(1.5))],
            hole_material="6061-T6",
        )
    )["fastener.thread_match"]

    assert match.status == "unresolved"
    assert match.calculation is None
    assert any("'M16xPh3P1.5'" in limit for limit in match.coverage_limits)


# --- head clearance ---------------------------------------------------------------


def test_head_clearance_is_unresolved_without_an_envelope_raycast() -> None:
    clearance = by_check(
        check_fastener_joint(screw(), tapped_hole(), [layer(mm(1.5))], hole_material="6061-T6")
    )["fastener.head_clearance"]

    assert clearance.status == "unresolved"
    assert any("envelope" in limit for limit in clearance.coverage_limits)


def test_head_clearance_is_demonstrated_when_the_envelope_raycast_hits() -> None:
    from swreview.geometry.envelope import EnvelopeHit, EnvelopeResult

    envelope = EnvelopeResult(
        hits=[EnvelopeHit(component_id="cmp:0009", first_hit_distance_m=0.010)],
        unresolved=[],
    )

    clearance = by_check(
        check_fastener_joint(
            screw(),
            tapped_hole(),
            [layer(mm(1.5))],
            hole_material="6061-T6",
            envelope=envelope,
        )
    )["fastener.head_clearance"]

    assert clearance.status == "demonstrated"
    assert "cmp:0009" in clearance.observed


def test_head_clearance_is_checked_within_scope_when_the_envelope_is_clear() -> None:
    from swreview.geometry.envelope import EnvelopeResult

    clearance = by_check(
        check_fastener_joint(
            screw(),
            tapped_hole(),
            [layer(mm(1.5))],
            hole_material="6061-T6",
            envelope=EnvelopeResult(hits=[], unresolved=[]),
        )
    )["fastener.head_clearance"]

    assert clearance.status == "checked_within_scope"


def test_head_clearance_stays_unresolved_when_a_mesh_was_missing() -> None:
    from swreview.geometry.envelope import EnvelopeResult

    clearance = by_check(
        check_fastener_joint(
            screw(),
            tapped_hole(),
            [layer(mm(1.5))],
            hole_material="6061-T6",
            envelope=EnvelopeResult(hits=[], unresolved=["missing mesh for component cmp:0009"]),
        )
    )["fastener.head_clearance"]

    assert clearance.status == "unresolved"
    assert any("cmp:0009" in limit for limit in clearance.coverage_limits)


# --- unsupported joint kinds ------------------------------------------------------


@pytest.mark.parametrize("kind", ["pin", "other", "nut", "washer"])
def test_an_unsupported_joint_kind_is_one_out_of_scope_result(kind: str) -> None:
    results = check_fastener_joint(
        screw(kind=kind), tapped_hole(), [layer(mm(1.5))], hole_material="6061-T6"
    )

    assert len(results) == 1
    assert results[0].check == "fastener.unsupported"
    assert results[0].status == "unresolved"
    assert results[0].coverage_limits == [f"out_of_scope: {kind}"]


def test_a_bolt_is_a_supported_joint_kind() -> None:
    results = check_fastener_joint(
        screw(kind="bolt"), tapped_hole(), [layer(mm(1.5))], hole_material="6061-T6"
    )

    assert "fastener.unsupported" not in by_check(results)


# --- units ------------------------------------------------------------------------


def test_inch_inputs_are_converted_and_both_values_are_recorded() -> None:
    results = by_check(
        check_fastener_joint(
            screw(thread="1/4-20", length=Quantity(value=0.75, unit="in")),
            tapped_hole(thread="1/4-20", thread_depth=Quantity(value=0.5, unit="in")),
            [layer(Quantity(value=0.125, unit="in"))],
            hole_material="AISI 1018 Steel",
        )
    )
    bottoming = results["fastener.bottoming"]

    # 0.75 in = 19.05 mm, 0.125 in = 3.175 mm -> protrusion 15.875 mm;
    # thread depth 0.5 in = 12.7 mm -> margin -3.175 mm.
    assert bottoming.status == "demonstrated"
    assert bottoming.calculation.result["margin_mm"] == pytest.approx(-3.175, abs=1e-9)
    assert bottoming.calculation.inputs["fastener_length"] == Quantity(value=0.75, unit="in")
    assert bottoming.calculation.inputs["fastener_length_mm"].value == pytest.approx(19.05)


def test_an_angle_where_a_length_belongs_raises_a_dimensionality_error() -> None:
    with pytest.raises(DimensionalityError):
        check_fastener_joint(
            screw(),
            tapped_hole(),
            [ClampedLayer(component_id="cmp:0003", thickness=Angle(value=5.0, unit="deg"))],
            hole_material="6061-T6",
        )
