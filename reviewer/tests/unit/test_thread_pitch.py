"""Fine and non-standard thread pitch (feature 010 amendment 2026-10-08, T116;
`contracts/fasteners.md` sections 8.1 to 8.6 and 8.10, research R2.26).

The owner's request: "Add check for fine pitch parts and threaded holes. Call out and flag to
user to make sure they mean to use it anywhere. We almost always use standard threads not
fine... so it's a common mistake." `run_thread_checks` reads four sources - Hole Wizard tapped
holes, cosmetic threads, fastener rows and screws named by their parts - puts each thread in
one class of section 8.1, and records one `thread.fine_pitch` or `thread.nonstandard_pitch`
finding per check and owning part (the owner's decision 57A), listing every designation with
its sources and its coarse alternative. Passes are counted in one checked row, and every
thread it could not judge is listed in a coverage row, never passed (50A).

The words below are section 8.5's and 8.6's, pinned literally: a sentence that moves here
moves in the contract first. The packages are built with `tests/support/mechanical.py`.
"""

from __future__ import annotations

import random
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from swreview.checks.fastener import ClampedLayer, check_fastener_joint
from swreview.checks.part_roles import PartRoles, classify_parts
from swreview.checks.result import DocumentResult
from swreview.checks.standards.profile import StandardsProfile, load_profile
from swreview.checks.thread_pitch import (
    CHECK_FINE_PITCH,
    CHECK_NONSTANDARD_PITCH,
    COVERAGE_CHECK,
    ThreadChecks,
    run_thread_checks,
)
from swreview.ir.models import DumpPhase, EvidencePackage, Quantity
from swreview.report.session import CoverageItem, CoverageScope
from tests.support.mechanical import Face, Instance, PackageBuilder

REVIEWER = Path(__file__).resolve().parents[1].parent
PROFILE_A = REVIEWER / "tests" / "fixtures" / "standards" / "profile-a.yaml"

FINE = "thread.fine_pitch"
NONSTANDARD = "thread.nonstandard_pitch"
ROW = "thread.pitch"
DRAWINGS = "thread callouts on drawings were not read for pitch"
COSMETIC = "a cosmetic thread carries no feature name, so whether it is suppressed was not read"
TABLE = "(coarse_pitch.yaml version 1)"
NO_PITCH = (
    "of them {verb} no pitch written, read as coarse because ISO 965-1 omits the coarse pitch "
    "from a designation"
)
REQUIREMENT_FINE = "threads use the coarse (standard) pitch unless a fine pitch is deliberate"
REQUIREMENT_NONSTANDARD = (
    "threads use the coarse (standard) pitch; no standard pitch of a size is coarser than it"
)
FACES = (Face(diameter_mm=6.8, lo_mm=-12.0, hi_mm=0.0),)
SUPPLIER = {"Meridian Supplier": "fict works"}
"""Profile A's vendor property: a strong bought vote (feature 013 `contracts/part-roles.md`)."""
CUSTOM = {"Meridian Part Ref": "MR-1002"}
"""With the stem `MR-1002`, the company prefix and few properties: custom by agreement."""


# --- builders ---------------------------------------------------------------------------------


def new_builder() -> PackageBuilder:
    return PackageBuilder(design_stem="FICT-KALO-0000")


def tapped(
    builder: PackageBuilder,
    component_id: str,
    thread: str | None,
    name: str = "Tapped Hole1",
    *,
    hole_type: str = "tapped",
    size: str = "M8",
) -> str:
    """One Hole Wizard feature on one component instance, as the extractor writes it."""
    return builder.hole(
        component_id,
        hole_type=hole_type,  # type: ignore[arg-type]
        size=size,
        end_condition="blind",
        instances=[Instance(origin_mm=(0.0, 0.0, 0.0), direction=(0.0, 0.0, 1.0), faces=FACES)],
        thread=thread,
        feature_name=name,
    )


def features(builder: PackageBuilder, document_id: str, *names: str) -> None:
    """The part's feature rows for `names`, read in its active configuration, not suppressed."""
    for name in names:
        builder.feature(document_id, name)


def part(
    builder: PackageBuilder, stem: str, *, properties: dict[str, str] | None = None
) -> tuple[str, str]:
    """A part document and one instance of it."""
    document = builder.document(stem, "part", properties=properties)
    return document, builder.component(document)


def run(package: EvidencePackage, roles: PartRoles | None = None) -> ThreadChecks:
    return run_thread_checks(package, roles)


def reasons(items: tuple[CoverageItem, ...]) -> list[str]:
    return [item.reason for item in items]


def every_row(checks: ThreadChecks) -> list[CoverageItem]:
    return [*checks.checked, *checks.unresolved, *checks.skipped]


def of(checks: ThreadChecks, check: str, document_id: str) -> DocumentResult:
    [found] = [
        item
        for item in checks.findings
        if item.result.check == check and item.documents == (document_id,)
    ]
    return found


def with_extractor(
    package: EvidencePackage,
    *,
    profile: str = "full",
    statuses: dict[str, str] | None = None,
    reused_from: str | None = None,
) -> EvidencePackage:
    """`package` written by another profile, or with some phases' rows in another state; a
    phase that did not run has no elapsed time."""
    statuses = statuses or {}
    phases = [
        DumpPhase(
            name=phase.name,
            elapsed_ms=None if statuses.get(phase.name, phase.status) == "skipped" else 1,
            status=statuses.get(phase.name, phase.status),  # type: ignore[arg-type]
        )
        for phase in package.extractor.phases
    ]
    extractor = package.extractor.model_copy(update={"profile": profile, "phases": phases})
    return package.model_copy(update={"extractor": extractor, "reused_from": reused_from})


@pytest.fixture(scope="module")
def profile() -> StandardsProfile:
    return load_profile(PROFILE_A)


# --- the examples of section 8.5, one package -------------------------------------------------


def examples_package() -> EvidencePackage:
    """Section 8.5's five examples, with the ids the contract prints: a base whose three
    coarse holes take `hol:0001` to `hol:0003`, the plate's three `M8x1` holes, its `M8x1.5`
    and its `M6x0.75`, a block used twice, a flange with `M8x1` and `M25x1.5`, and two
    `#10-32` screws. Every hole's feature row is read and not suppressed."""
    builder = new_builder()
    base, base_1 = part(builder, "BASE_FICT")
    plate, plate_1 = part(builder, "PLATE_FICT")
    block, block_1 = part(builder, "BLOCK_FICT")
    flange, flange_1 = part(builder, "FLANGE_FICT")
    block_2 = builder.component(block)
    screw = builder.document("SHC_10-32X0.5_FICT", "part")
    for name in ("Tapped Hole1", "Tapped Hole2", "Tapped Hole3"):
        tapped(builder, base_1, "M5x0.8", name)
    for name in ("Tapped Hole1", "Tapped Hole2", "Tapped Hole3"):
        tapped(builder, plate_1, "M8x1", name)
    tapped(builder, block_1, "M10x1.25", "Tapped Hole1")
    tapped(builder, plate_1, "M8x1.5", "Tapped Hole4")
    tapped(builder, plate_1, "M6x0.75", "Tapped Hole5")
    tapped(builder, flange_1, "M8x1", "Tapped Hole1")
    tapped(builder, block_2, "M10x1.25", "Tapped Hole1")
    tapped(builder, flange_1, "M25x1.5", "Tapped Hole2")
    for component_id in ("cmp:0012", "cmp:0013"):
        builder.component(screw, component_id=component_id)
        builder.fastener_row(component_id, designation="#10-32")
    features(builder, base, "Tapped Hole1", "Tapped Hole2", "Tapped Hole3")
    features(builder, plate, *(f"Tapped Hole{n}" for n in range(1, 6)))
    features(builder, block, "Tapped Hole1")
    features(builder, flange, "Tapped Hole1", "Tapped Hole2")
    return builder.build().package


@pytest.fixture(scope="module")
def examples() -> ThreadChecks:
    return run(examples_package())


def test_the_ids_of_the_examples_package_are_the_contracts(examples) -> None:
    package = examples_package()

    assert [(hole.id, hole.component_id, hole.feature_name) for hole in package.holes][3:] == [
        ("hol:0004", "cmp:0002", "Tapped Hole1"),
        ("hol:0005", "cmp:0002", "Tapped Hole2"),
        ("hol:0006", "cmp:0002", "Tapped Hole3"),
        ("hol:0007", "cmp:0003", "Tapped Hole1"),
        ("hol:0008", "cmp:0002", "Tapped Hole4"),
        ("hol:0009", "cmp:0002", "Tapped Hole5"),
        ("hol:0010", "cmp:0004", "Tapped Hole1"),
        ("hol:0011", "cmp:0005", "Tapped Hole1"),
        ("hol:0012", "cmp:0004", "Tapped Hole2"),
    ]
    assert [(item.documents, item.result.check) for item in examples.findings] == [
        (("doc:0003",), FINE),
        (("doc:0003",), NONSTANDARD),
        (("doc:0004",), FINE),
        (("doc:0005",), FINE),
        (("doc:0006",), FINE),
    ]


def test_two_designations_of_one_part_are_one_finding_its_clauses_in_hole_order(examples) -> None:
    """Section 8.5's first example, word for word (57A)."""
    found = of(examples, FINE, "doc:0003")

    assert found.result.observed == (
        "M8x1 is fine pitch (M8's coarse pitch is 1.25) on 3 tapped holes: Tapped Hole1 "
        "(hol:0004), Tapped Hole2 (hol:0005), Tapped Hole3 (hol:0006); M6x0.75 is fine pitch "
        "(M6's coarse pitch is 1) on 1 tapped hole: Tapped Hole5 (hol:0009) in PLATE_FICT.SLDPRT"
    )
    assert found.result.recommended_action == (
        "Confirm M8x1 and M6x0.75 are intended in PLATE_FICT.SLDPRT, or change them to the "
        "coarse M8x1.25 and M6x1."
    )
    assert found.result.requirement == REQUIREMENT_FINE
    assert found.component_ids == ("cmp:0002",)


def test_a_fine_and_a_non_standard_thread_of_one_part_are_two_findings(examples) -> None:
    """Section 8.5's second example: the plate's own `thread.nonstandard_pitch` finding."""
    found = of(examples, NONSTANDARD, "doc:0003")

    assert found.result.observed == (
        "M8x1.5 is coarser than the standard pitch (M8's coarse pitch is 1.25) on 1 tapped hole: "
        "Tapped Hole4 (hol:0008) in PLATE_FICT.SLDPRT"
    )
    assert found.result.recommended_action == (
        "Confirm M8x1.5 is intended in PLATE_FICT.SLDPRT, or change it to the coarse M8x1.25."
    )
    assert found.result.requirement == REQUIREMENT_NONSTANDARD
    assert found.result.inputs == ["hol:0008", f"ISO 261 coarse pitch of M8: 1.25 mm {TABLE}"]


def test_one_feature_of_a_part_used_twice_is_one_tapped_hole_listing_both_ids(examples) -> None:
    """Section 8.5's third example: a finding counts features, and lists every instance."""
    found = of(examples, FINE, "doc:0004")

    assert found.result.observed == (
        "M10x1.25 is fine pitch (M10's coarse pitch is 1.5) on 1 tapped hole: Tapped Hole1 "
        "(hol:0007, hol:0011) in BLOCK_FICT.SLDPRT"
    )
    assert found.result.inputs == [
        "hol:0007",
        "hol:0011",
        f"ISO 261 coarse pitch of M10: 1.5 mm {TABLE}",
    ]
    assert found.component_ids == ("cmp:0003", "cmp:0005")


def test_a_unified_fine_fastener_names_its_instances_in_its_own_file(examples) -> None:
    """Section 8.5's fourth example."""
    found = of(examples, FINE, "doc:0006")

    assert found.result.observed == (
        "#10-32 is fine pitch (#10's coarse thread is UNC, 24 threads per inch) on 2 fastener "
        "instances: cmp:0012, cmp:0013 in SHC_10-32X0.5_FICT.SLDPRT"
    )
    assert found.result.recommended_action == (
        "Confirm #10-32 is intended in SHC_10-32X0.5_FICT.SLDPRT, or change it to the coarse "
        "#10-24."
    )
    assert found.result.inputs == [
        "fas:0001",
        "fas:0002",
        f"ASME B1.1 UNC of #10: 24 threads per inch {TABLE}",
    ]
    assert found.component_ids == ("cmp:0012", "cmp:0013")


def test_a_coarse_and_a_fine_only_designation_take_the_both_kinds_action(examples) -> None:
    """Section 8.5's fifth example."""
    found = of(examples, FINE, "doc:0005")

    assert found.result.observed == (
        "M8x1 is fine pitch (M8's coarse pitch is 1.25) on 1 tapped hole: Tapped Hole1 "
        "(hol:0010); M25x1.5 is fine pitch (M25 has no coarse pitch in ISO 261) on 1 tapped "
        "hole: Tapped Hole2 (hol:0012) in FLANGE_FICT.SLDPRT"
    )
    assert found.result.recommended_action == (
        "Confirm M8x1 and M25x1.5 are intended in FLANGE_FICT.SLDPRT, or change M8x1 to the "
        "coarse M8x1.25, and M25x1.5 to a size that has a coarse thread."
    )
    assert found.result.inputs == [
        "hol:0010",
        "hol:0012",
        f"ISO 261 coarse pitch of M8: 1.25 mm {TABLE}",
        f"ISO 261: M25 has fine pitches only {TABLE}",
    ]


def test_every_finding_is_suspected_medium_with_no_calculation_and_the_drawings_limit(
    examples,
) -> None:
    for item in examples.findings:
        assert item.result.status == "suspected"
        assert item.result.severity == "medium"
        assert item.result.calculation is None
        assert item.result.coverage_limits == [DRAWINGS]


def test_no_finding_names_a_document_id_or_a_percent_sign(examples) -> None:
    for item in examples.findings:
        words = item.result.observed + item.result.recommended_action + item.result.requirement
        assert "doc:" not in words
        assert "%" not in words


def test_no_two_results_share_a_check_and_component_ids(examples) -> None:
    """The restate's verdict key is the check, the components, the drawing places, the entity
    ids among the inputs and the configuration (`runner._verdict_key`): one finding per check
    and part gives each its own."""
    keys = [(item.result.check, item.component_ids) for item in examples.findings]

    assert len(keys) == len(set(keys))


def test_the_examples_coarse_holes_are_counted_in_the_checked_row(examples) -> None:
    assert examples.checked == (
        CoverageItem(
            check=ROW,
            scope=CoverageScope(component_ids=["cmp:0001"], document_ids=["doc:0002"]),
            reason=(
                "3 threads have the coarse pitch: M5x0.8 (hol:0001, hol:0002, hol:0003)"
            ),
            error=None,
        ),
    )
    assert examples.unresolved == ()
    assert examples.skipped == ()
    assert (examples.threads, examples.coarse) == (14, 3)


# --- the classes of section 8.1, with section 8.9's first table as tapped holes ---------------

COARSE = (
    "M8x1.25",
    "M8 x 1.25",
    "M8x1.25-6g",
    "M8x1.25-6G",
    "M8x1,25",
    "M8-1.25",
    "M10-1.5-6H",
    "M4-0.7x12",
    "M8-1.25rh",
    "M8-6H",
    "M8-6g6h",
    "M8",
    "M6x1",
    "M7x1",
    "M3.5x0.6",
    "1/4-20",
    "1/4-20 UNC-2B",
    "1/4-20 UNF",
    "0.250-20",
    "#6-32",
    "#10-24",
    "1.000-8",
)
FINE_TEXTS = (
    "M8-1 x 20",
    "M10-1.25LH",
    "M8x1",
    "m8x1",
    "M8×1",
    "M8-1",
    "M8x1.0",
    "M8x0.75",
    "M10x1.25",
    "M12x1.5",
    "M25x1.5",
    "M25",
    "M5.5x0.5",
    "1/4-28",
    "1/4-28 UNF-2A",
    "1/4-32",
    "#10-32",
    "#10-32 UNF",
    "0.190-32",
    "1.125-8",
    "#0-80",
)
NONSTANDARD_TEXTS = ("M8x1.25 6H", "M8x1.5", "M10x35", "1/4-18", "1/8-27")
UNREADABLE = (
    "M8-1.25 6g",
    "M10-1.25G",
    "M8-1x",
    "M16xPh3P1.5",
    "M8x",
    "MF8x1",
    "3/8",
    "1-8",
    "1-1/8-7",
    "10-32",
    "No. 10-32",
)
UNKNOWN = ("M2.3x0.4", "M70")
PIPE = (
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
    "1/8-27 npt",
)
CLASSES = (
    [(text, "coarse") for text in COARSE]
    + [(text, "fine") for text in FINE_TEXTS]
    + [(text, "nonstandard") for text in NONSTANDARD_TEXTS]
    + [(text, "unreadable") for text in UNREADABLE]
    + [(text, "unknown") for text in UNKNOWN]
    + [(text, "pipe") for text in PIPE]
    + [("", "no designation"), (None, "no designation")]
)


def one_tapped_hole(thread: str | None) -> EvidencePackage:
    builder = new_builder()
    plate, component = part(builder, "PLATE_FICT")
    tapped(builder, component, thread)
    features(builder, plate, "Tapped Hole1")
    return builder.build().package


@pytest.mark.parametrize(("text", "landing"), CLASSES, ids=[repr(text) for text, _ in CLASSES])
def test_every_class_of_section_8_1_lands_where_it_says(text: str | None, landing: str) -> None:
    checks = run(one_tapped_hole(text))

    found = [(item.result.check, item.documents) for item in checks.findings]
    expected_rows: dict[str, list[str]] = {"checked": [], "unresolved": [], "skipped": []}
    expected_findings: list[Any] = []
    if landing == "coarse":
        assert text is not None
        no_pitch = ""
        if text in ("M8", "M8-6H", "M8-6g6h"):
            no_pitch = f"; 1 {NO_PITCH.format(verb='has')}"
        expected_rows["checked"] = [
            f"1 thread has the coarse pitch: {text.strip()} (hol:0001){no_pitch}"
        ]
    elif landing == "fine":
        expected_findings = [(FINE, ("doc:0002",))]
    elif landing == "nonstandard":
        expected_findings = [(NONSTANDARD, ("doc:0002",))]
    elif landing == "unreadable":
        expected_rows["unresolved"] = [
            "1 thread could not be read for pitch, so their pitch was not checked: "
            f"'{text}' on hol:0001"
        ]
    elif landing == "no designation":
        expected_rows["unresolved"] = [
            "1 thread could not be read for pitch, so their pitch was not checked: "
            "no designation on hol:0001"
        ]
    elif landing == "unknown":
        expected_rows["unresolved"] = [
            "1 thread has a size in no pitch table (ISO 261 to M68, ASME B1.1 UNC to 2 in), so "
            f"their pitch was not checked: '{text}' on hol:0001"
        ]
    else:
        expected_rows["skipped"] = [
            "1 pipe thread was not checked for pitch; a pipe thread has its own series: "
            f"'{text}' on hol:0001"
        ]

    assert found == expected_findings
    assert {
        "checked": reasons(checks.checked),
        "unresolved": reasons(checks.unresolved),
        "skipped": reasons(checks.skipped),
    } == expected_rows
    assert checks.threads == 1
    assert checks.coarse == (1 if landing == "coarse" else 0)


def test_a_fine_unified_clause_names_the_unc_threads_per_inch() -> None:
    [found] = run(one_tapped_hole("1/4-28")).findings

    assert found.result.observed == (
        "1/4-28 is fine pitch (1/4's coarse thread is UNC, 20 threads per inch) on 1 tapped hole: "
        "Tapped Hole1 (hol:0001) in PLATE_FICT.SLDPRT"
    )
    assert found.result.recommended_action == (
        "Confirm 1/4-28 is intended in PLATE_FICT.SLDPRT, or change it to the coarse 1/4-20."
    )
    assert found.result.inputs == ["hol:0001", f"ASME B1.1 UNC of 1/4: 20 threads per inch {TABLE}"]


def test_a_unified_fine_only_size_has_no_unc_thread() -> None:
    [found] = run(one_tapped_hole("#0-80")).findings

    assert found.result.observed == (
        "#0-80 is fine pitch (#0 has no UNC thread in ASME B1.1) on 1 tapped hole: Tapped Hole1 "
        "(hol:0001) in PLATE_FICT.SLDPRT"
    )
    assert found.result.recommended_action == (
        "Confirm #0-80 is intended in PLATE_FICT.SLDPRT, or change it to a size that has a "
        "coarse thread."
    )
    assert found.result.inputs == ["hol:0001", f"ASME B1.1: #0 has no UNC thread {TABLE}"]


def test_a_metric_fine_only_size_alone_takes_the_fine_only_action() -> None:
    [found] = run(one_tapped_hole("M25x1.5")).findings

    assert found.result.observed == (
        "M25x1.5 is fine pitch (M25 has no coarse pitch in ISO 261) on 1 tapped hole: Tapped "
        "Hole1 (hol:0001) in PLATE_FICT.SLDPRT"
    )
    assert found.result.recommended_action == (
        "Confirm M25x1.5 is intended in PLATE_FICT.SLDPRT, or change it to a size that has a "
        "coarse thread."
    )


def test_a_non_standard_unified_clause_names_the_unc_threads_per_inch() -> None:
    [found] = run(one_tapped_hole("1/4-18")).findings

    assert found.result.check == NONSTANDARD
    assert found.result.observed == (
        "1/4-18 is coarser than the standard pitch (1/4's coarse thread is UNC, 20 threads per "
        "inch) on 1 tapped hole: Tapped Hole1 (hol:0001) in PLATE_FICT.SLDPRT"
    )
    assert found.result.recommended_action == (
        "Confirm 1/4-18 is intended in PLATE_FICT.SLDPRT, or change it to the coarse 1/4-20."
    )


def test_two_fine_only_sizes_take_the_plural_fine_only_action() -> None:
    builder = new_builder()
    plate, component = part(builder, "PLATE_FICT")
    tapped(builder, component, "M25x1.5", "Tapped Hole1")
    tapped(builder, component, "M15x1", "Tapped Hole2")
    features(builder, plate, "Tapped Hole1", "Tapped Hole2")

    [found] = run(builder.build().package).findings

    assert found.result.recommended_action == (
        "Confirm M25x1.5 and M15x1 are intended in PLATE_FICT.SLDPRT, or change them to a size "
        "that has a coarse thread."
    )


def test_three_designations_are_listed_with_commas_and_a_final_and() -> None:
    builder = new_builder()
    plate, component = part(builder, "PLATE_FICT")
    tapped(builder, component, "M8x1", "Tapped Hole1")
    tapped(builder, component, "M6x0.75", "Tapped Hole2")
    tapped(builder, component, "M10x1.25", "Tapped Hole3")
    features(builder, plate, "Tapped Hole1", "Tapped Hole2", "Tapped Hole3")

    [found] = run(builder.build().package).findings

    assert found.result.recommended_action == (
        "Confirm M8x1, M6x0.75 and M10x1.25 are intended in PLATE_FICT.SLDPRT, or change them "
        "to the coarse M8x1.25, M6x1 and M10x1.5."
    )


# --- the sources of section 8.2 ----------------------------------------------------------------


def test_the_four_sources_are_read_and_nothing_else() -> None:
    """A tapped hole, a cosmetic thread, a fastener row and a screw named by its part are
    read; a counterbore's size, any other hole type's designation and a washer row with no
    designation are not sources."""
    builder = new_builder()
    plate, plate_1 = part(builder, "PLATE_FICT")
    tapped(builder, plate_1, "M8x1.25", "Tapped Hole1")
    tapped(builder, plate_1, None, "CBORE for M8x1", hole_type="counterbore", size="M8x1")
    tapped(builder, plate_1, "M6x0.5", "Clearance Hole1", hole_type="clearance", size="M6")
    builder.cosmetic_thread(plate_1, designation="M6x1")
    features(builder, plate, "Tapped Hole1", "CBORE for M8x1", "Clearance Hole1")
    nut, nut_1 = part(builder, "NUT_FICT")
    builder.fastener_row(nut_1, designation="M5x0.8", kind="nut")
    _, washer_1 = part(builder, "WASHER_FICT")
    builder.fastener_row(washer_1, designation=None, kind="washer")
    named = builder.screw_document("SHC", "M5-0.8", 12, serial=1)
    named_1 = builder.screw(named, bearing_mm=(40.0, 0.0, 0.0), direction=(0.0, 0.0, 1.0))
    package = builder.build().package

    checks = run(package)

    assert checks.findings == ()
    assert checks.checked == (
        CoverageItem(
            check=ROW,
            scope=CoverageScope(
                component_ids=sorted([plate_1, nut_1, named_1]),
                document_ids=sorted([plate, nut, named]),
            ),
            reason=(
                "4 threads have the coarse pitch: M8x1.25 (hol:0001), M6x1 (thr:0001), "
                f"M5x0.8 (fas:0001, {named_1})"
            ),
            error=None,
        ),
    )
    assert (checks.threads, checks.coarse) == (4, 4)
    assert (checks.unresolved, checks.skipped) == ((), ())


@pytest.mark.parametrize("kind", ["screw", "bolt", "nut"])
def test_a_screw_bolt_or_nut_row_with_no_designation_is_unreadable(kind: str) -> None:
    builder = new_builder()
    _, component = part(builder, "FASTENER_FICT")
    builder.fastener_row(component, designation=None, kind=kind)  # type: ignore[arg-type]

    checks = run(builder.build().package)

    assert reasons(checks.unresolved) == [
        "1 thread could not be read for pitch, so their pitch was not checked: "
        "no designation on fas:0001"
    ]


@pytest.mark.parametrize("kind", ["washer", "pin", "other"])
@pytest.mark.parametrize("designation", [None, "", "  "])
def test_a_washer_pin_or_other_row_with_no_designation_states_no_thread(
    kind: str, designation: str | None
) -> None:
    builder = new_builder()
    _, component = part(builder, "WASHER_FICT")
    builder.fastener_row(component, designation=designation, kind=kind)  # type: ignore[arg-type]

    checks = run(builder.build().package)

    assert checks.threads == 0
    assert reasons(checks.skipped) == [
        "no tapped hole, cosmetic thread or fastener in the package states a thread"
    ]


@pytest.mark.parametrize("kind", ["washer", "pin"])
def test_a_washer_or_pin_with_a_size_is_read_like_a_thread(kind: str) -> None:
    """D13: a pin named for a fine-only size is flagged and confirmed like any other."""
    builder = new_builder()
    pin, component = part(builder, "PIN_FICT")
    builder.fastener_row(component, designation="M25", kind=kind)  # type: ignore[arg-type]

    [found] = run(builder.build().package).findings

    assert (found.result.check, found.documents) == (FINE, (pin,))


@pytest.mark.parametrize("missing", ["components", "documents"])
def test_a_fastener_row_whose_part_is_not_in_the_package_is_unreadable(missing: str) -> None:
    builder = new_builder()
    screw, component = part(builder, "SCREW_FICT")
    builder.fastener_row(component, designation="M8x1")
    package = builder.build().package
    kept = {
        "components": [item for item in package.components if item.id != component],
        "documents": [item for item in package.documents if item.document_id != screw],
    }
    package = package.model_copy(update={missing: kept[missing]})

    checks = run(package)

    assert checks.findings == ()
    assert reasons(checks.unresolved) == [
        "1 thread could not be read for pitch, so their pitch was not checked: "
        "'M8x1' on fas:0001 (its part is not in the package)"
    ]


def test_a_tapped_hole_or_cosmetic_thread_whose_part_is_not_in_the_package_is_unreadable() -> None:
    """The fastener rule applied to the other sources: with no owning document a thread can be
    neither graded nor grouped, so it is listed, never passed."""
    builder = new_builder()
    _, component = part(builder, "PLATE_FICT")
    tapped(builder, component, "M8x1")
    builder.cosmetic_thread(component, designation="")
    package = builder.build().package
    package = package.model_copy(
        update={"components": [item for item in package.components if item.id != component]}
    )

    checks = run(package)

    assert checks.findings == ()
    assert reasons(checks.unresolved) == [
        "2 threads could not be read for pitch, so their pitch was not checked: "
        "'M8x1' on hol:0001 (its part is not in the package), "
        "no designation on thr:0001 (its part is not in the package)"
    ]


def name_parsed_screw_with_a_row(
    *, thread: str, suppression: str = "resolved"
) -> tuple[EvidencePackage, str, str]:
    """A screw named in the vendor shape that also has a fastener row whose size and length
    came from its name (`identity_source = "name_parse"`, `FastenerDumper.cs:153-155`)."""
    builder = new_builder()
    screw = builder.screw_document("SHC", thread, 20, serial=1)
    if suppression == "resolved":
        component = builder.screw(screw, bearing_mm=(0.0, 0.0, 0.0), direction=(0.0, 0.0, 1.0))
    else:
        component = builder.component(screw, suppression=suppression)  # type: ignore[arg-type]
    builder.fastener_row(
        component,
        designation=thread.replace("-", "x"),
        identity_source="name_parse",
        length_mm=20.0,
    )
    return builder.build().package, screw, component


def test_a_name_parse_fastener_row_is_read_once_as_a_row() -> None:
    """D23: told apart by its id, never by `identity_source`."""
    package, screw, component = name_parsed_screw_with_a_row(thread="M8-1")

    checks = run(package)

    [found] = checks.findings
    assert found.result.observed == (
        "M8x1 is fine pitch (M8's coarse pitch is 1.25) on 1 fastener instance: "
        f"{component} in SHC_M8-1X20_FICT-0001.SLDPRT"
    )
    assert found.result.inputs == ["fas:0001", f"ISO 261 coarse pitch of M8: 1.25 mm {TABLE}"]
    assert found.documents == (screw,)
    assert checks.threads == 1


def test_a_coarse_name_parse_fastener_row_is_counted_once() -> None:
    package, _, _ = name_parsed_screw_with_a_row(thread="M8-1.25")

    checks = run(package)

    assert reasons(checks.checked) == ["1 thread has the coarse pitch: M8x1.25 (fas:0001)"]
    assert (checks.threads, checks.coarse) == (1, 1)


def test_a_name_parse_fastener_row_on_a_suppressed_component_is_skipped() -> None:
    package, screw, component = name_parsed_screw_with_a_row(
        thread="M8-1", suppression="suppressed"
    )

    checks = run(package)

    assert checks.findings == ()
    assert checks.skipped == (
        CoverageItem(
            check=ROW,
            scope=CoverageScope(component_ids=[component], document_ids=[screw]),
            reason=(
                "1 thread on suppressed features or components was not checked for pitch: "
                f"fas:0001 ({component})"
            ),
            error=None,
        ),
    )


def test_a_screw_its_part_names_with_no_row_is_read_by_its_component_id() -> None:
    builder = new_builder()
    screw = builder.screw_document("SHC", "M8-1", 20, serial=1)
    component = builder.screw(screw, bearing_mm=(0.0, 0.0, 0.0), direction=(0.0, 0.0, 1.0))

    [found] = run(builder.build().package).findings

    assert found.result.inputs == [component, f"ISO 261 coarse pitch of M8: 1.25 mm {TABLE}"]
    assert found.component_ids == (component,)


# --- the grouping of section 8.5 ---------------------------------------------------------------


def test_three_features_of_one_designation_in_one_part_are_one_finding() -> None:
    builder = new_builder()
    plate, component = part(builder, "PLATE_FICT")
    for name in ("Tapped Hole1", "Tapped Hole2", "Tapped Hole3"):
        tapped(builder, component, "M8x1", name)
    features(builder, plate, "Tapped Hole1", "Tapped Hole2", "Tapped Hole3")

    [found] = run(builder.build().package).findings

    assert found.result.observed == (
        "M8x1 is fine pitch (M8's coarse pitch is 1.25) on 3 tapped holes: Tapped Hole1 "
        "(hol:0001), Tapped Hole2 (hol:0002), Tapped Hole3 (hol:0003) in PLATE_FICT.SLDPRT"
    )
    assert found.result.recommended_action == (
        "Confirm M8x1 is intended in PLATE_FICT.SLDPRT, or change it to the coarse M8x1.25."
    )


def test_one_coarse_feature_of_a_part_used_twice_counts_two_in_the_checked_row() -> None:
    """D24: a row counts hole rows, one per feature and component instance."""
    builder = new_builder()
    plate, first = part(builder, "PLATE_FICT")
    second = builder.component(plate)
    tapped(builder, first, "M5x0.8")
    tapped(builder, second, "M5x0.8")
    features(builder, plate, "Tapped Hole1")

    checks = run(builder.build().package)

    assert checks.checked == (
        CoverageItem(
            check=ROW,
            scope=CoverageScope(component_ids=[first, second], document_ids=[plate]),
            reason="2 threads have the coarse pitch: M5x0.8 (hol:0001, hol:0002)",
            error=None,
        ),
    )


def test_one_designation_written_two_ways_is_one_designation_with_a_written_as_input() -> None:
    builder = new_builder()
    plate, component = part(builder, "PLATE_FICT")
    tapped(builder, component, "M8x1", "Tapped Hole1")
    tapped(builder, component, " M8 x 1.0 ", "Tapped Hole2")
    features(builder, plate, "Tapped Hole1", "Tapped Hole2")

    [found] = run(builder.build().package).findings

    assert found.result.observed == (
        "M8x1 is fine pitch (M8's coarse pitch is 1.25) on 2 tapped holes: Tapped Hole1 "
        "(hol:0001), Tapped Hole2 (hol:0002) in PLATE_FICT.SLDPRT"
    )
    assert found.result.inputs == [
        "hol:0001",
        "hol:0002",
        f"ISO 261 coarse pitch of M8: 1.25 mm {TABLE}",
        "written as 'M8 x 1.0' on hol:0002",
    ]


def test_a_hole_and_a_cosmetic_thread_of_one_size_are_one_designation_listing_both() -> None:
    builder = new_builder()
    plate, component = part(builder, "PLATE_FICT")
    tapped(builder, component, "M8x1")
    builder.cosmetic_thread(component, designation="M8x1")
    features(builder, plate, "Tapped Hole1")

    [found] = run(builder.build().package).findings

    assert found.result.observed == (
        "M8x1 is fine pitch (M8's coarse pitch is 1.25) on 1 tapped hole and 1 cosmetic thread: "
        "Tapped Hole1 (hol:0001), cosmetic thread thr:0001 in PLATE_FICT.SLDPRT"
    )
    assert found.result.inputs == [
        "hol:0001",
        "thr:0001",
        f"ISO 261 coarse pitch of M8: 1.25 mm {TABLE}",
    ]
    assert found.result.coverage_limits == [DRAWINGS, COSMETIC]


def test_the_features_of_a_designation_are_listed_in_feature_name_order() -> None:
    builder = new_builder()
    plate, component = part(builder, "PLATE_FICT")
    tapped(builder, component, "M8x1", "Tapped Hole2")
    tapped(builder, component, "M8x1", "Tapped Hole1")
    features(builder, plate, "Tapped Hole2", "Tapped Hole1")

    [found] = run(builder.build().package).findings

    assert found.result.observed == (
        "M8x1 is fine pitch (M8's coarse pitch is 1.25) on 2 tapped holes: Tapped Hole1 "
        "(hol:0002), Tapped Hole2 (hol:0001) in PLATE_FICT.SLDPRT"
    )
    assert found.result.inputs[:2] == ["hol:0001", "hol:0002"]


def test_two_parts_are_two_findings() -> None:
    builder = new_builder()
    plate, first = part(builder, "PLATE_FICT")
    block, second = part(builder, "BLOCK_FICT")
    tapped(builder, first, "M8x1")
    tapped(builder, second, "M8x1")
    features(builder, plate, "Tapped Hole1")
    features(builder, block, "Tapped Hole1")

    checks = run(builder.build().package)

    assert [(item.result.check, item.documents) for item in checks.findings] == [
        (FINE, (plate,)),
        (FINE, (block,)),
    ]


def test_a_fine_screw_into_a_part_with_a_fine_hole_is_flagged_in_its_own_file() -> None:
    """D11: a fastener's part is its own document, never the part it goes into."""
    builder = new_builder()
    plate, plate_1 = part(builder, "PLATE_FICT")
    tapped(builder, plate_1, "M6x0.75")
    features(builder, plate, "Tapped Hole1")
    screw, screw_1 = part(builder, "SCREW_FICT")
    builder.fastener_row(screw_1, designation="M8x1")

    checks = run(builder.build().package)

    assert [
        (item.result.check, item.documents, item.component_ids) for item in checks.findings
    ] == [(FINE, (plate,), (plate_1,)), (FINE, (screw,), (screw_1,))]
    assert of(checks, FINE, screw).result.observed == (
        f"M8x1 is fine pitch (M8's coarse pitch is 1.25) on 1 fastener instance: {screw_1} in "
        "SCREW_FICT.SLDPRT"
    )


def test_the_inputs_begin_with_every_source_id_in_source_order() -> None:
    """Tapped holes by id, then cosmetic threads by id, then fasteners by component id; then
    each designation's table row, in designation order."""
    builder = new_builder()
    plate, component = part(builder, "PLATE_FICT")
    builder.cosmetic_thread(component, designation="M8x1")
    tapped(builder, component, "M6x0.75", "Tapped Hole2")
    tapped(builder, component, "M8x1", "Tapped Hole1")
    features(builder, plate, "Tapped Hole1", "Tapped Hole2")

    [found] = run(builder.build().package).findings

    assert found.result.inputs == [
        "hol:0001",
        "hol:0002",
        "thr:0001",
        f"ISO 261 coarse pitch of M6: 1 mm {TABLE}",
        f"ISO 261 coarse pitch of M8: 1.25 mm {TABLE}",
    ]
    assert found.result.observed.startswith("M6x0.75 is fine pitch")


# --- part roles (section 8.2, 52A) -------------------------------------------------------------


def roles_package() -> tuple[EvidencePackage, dict[str, str]]:
    """A bought part with a fine tapped hole and a fine cosmetic thread, a bought screw with a
    fine row, an unclear plate with a fine hole, an unclear screw with a fine row, and a
    custom block with a fine hole."""
    builder = new_builder()
    bought, bought_1 = part(builder, "FICT-VEN-0001", properties=SUPPLIER)
    tapped(builder, bought_1, "M8x1")
    builder.cosmetic_thread(bought_1, designation="M6x0.75")
    bought_screw, bought_screw_1 = part(builder, "FICT-VEN-0002", properties=SUPPLIER)
    builder.fastener_row(bought_screw_1, designation="M8x1")
    plate, plate_1 = part(builder, "PLATE_FICT")
    tapped(builder, plate_1, "M8x1")
    screw, screw_1 = part(builder, "SCREW_FICT")
    builder.fastener_row(screw_1, designation="M8x1")
    block, block_1 = part(builder, "MR-1002", properties=CUSTOM)
    tapped(builder, block_1, "M10x1.25")
    for document in (bought, plate, block):
        features(builder, document, "Tapped Hole1")
    ids = {
        "bought": bought,
        "bought_1": bought_1,
        "bought_screw": bought_screw,
        "plate": plate,
        "screw": screw,
        "block": block,
    }
    return builder.build().package, ids


def roles_of(
    package: EvidencePackage, profile: StandardsProfile, *, asked: bool = False
) -> PartRoles:
    roles = classify_parts(package, profile)
    return roles.asking("ER-001") if asked else roles


def test_the_roles_package_has_one_part_of_each_role(profile) -> None:
    package, ids = roles_package()
    roles = roles_of(package, profile)

    assert {key: roles.by_document[ids[key]].role for key in ids if not key.endswith("_1")} == {
        "bought": "bought",
        "bought_screw": "bought",
        "plate": "unclear",
        "screw": "unclear",
        "block": "custom",
    }


def test_a_bought_parts_tapped_hole_and_cosmetic_thread_are_listed_not_flagged(profile) -> None:
    package, ids = roles_package()

    checks = run(package, roles_of(package, profile))

    assert ids["bought"] not in {item.documents[0] for item in checks.findings}
    assert checks.skipped == (
        CoverageItem(
            check=ROW,
            scope=CoverageScope(component_ids=[ids["bought_1"]], document_ids=[ids["bought"]]),
            reason=(
                "2 threads in bought parts were not checked for pitch: FICT-VEN-0001.SLDPRT "
                "(hol:0001, thr:0001)"
            ),
            error=None,
        ),
    )


def test_the_bought_row_lists_each_part_once_in_the_order_of_its_first_thread(profile) -> None:
    """Two bought files of one name in two folders are two parts, each with its own ids."""
    builder = new_builder()
    first = builder.document("FICT-VEN-0001", "part", properties=SUPPLIER)
    second = builder.document("FICT-VEN-0001", "part", properties=SUPPLIER)
    first_1, second_1 = builder.component(first), builder.component(second)
    tapped(builder, first_1, "M8x1", "Tapped Hole1")
    tapped(builder, second_1, "M8x1", "Tapped Hole1")
    tapped(builder, first_1, "M6x0.75", "Tapped Hole2")
    package = builder.build().package

    checks = run(package, roles_of(package, profile))

    assert reasons(checks.skipped) == [
        "3 threads in bought parts were not checked for pitch: FICT-VEN-0001.SLDPRT (hol:0001, "
        "hol:0003), FICT-VEN-0001.SLDPRT (hol:0002)"
    ]


def test_a_bought_fastener_is_flagged_whatever_its_role(profile) -> None:
    package, ids = roles_package()

    checks = run(package, roles_of(package, profile, asked=True))

    found = of(checks, FINE, ids["bought_screw"])
    assert found.result.coverage_limits == [DRAWINGS]


def test_an_unclear_parts_hole_finding_carries_the_note_while_the_question_is_asked(
    profile,
) -> None:
    package, ids = roles_package()
    note = "may be a bought part: too little evidence: only few properties; asked in ER-001"

    asked = run(package, roles_of(package, profile, asked=True))
    not_yet = run(package, roles_of(package, profile))

    assert of(asked, FINE, ids["plate"]).result.coverage_limits == [DRAWINGS, note]
    assert of(not_yet, FINE, ids["plate"]).result.coverage_limits == [DRAWINGS]


def test_an_unclear_parts_fastener_finding_carries_no_note(profile) -> None:
    """D21: fasteners are classified whatever their role, so no answer withdraws one."""
    package, ids = roles_package()

    checks = run(package, roles_of(package, profile, asked=True))

    assert of(checks, FINE, ids["screw"]).result.coverage_limits == [DRAWINGS]


def test_a_custom_parts_hole_is_flagged_with_no_note(profile) -> None:
    package, ids = roles_package()

    checks = run(package, roles_of(package, profile, asked=True))

    assert of(checks, FINE, ids["block"]).result.coverage_limits == [DRAWINGS]


def test_an_id_the_roles_do_not_know_is_graded(profile) -> None:
    package, ids = roles_package()
    roles = roles_of(package, profile, asked=True)
    known = {key: value for key, value in roles.by_document.items() if key != ids["bought"]}
    unknown = replace(roles, by_document=known)

    checks = run(package, unknown)

    assert of(checks, FINE, ids["bought"]).result.coverage_limits == [DRAWINGS, COSMETIC]
    assert not [row for row in checks.skipped if "bought parts" in row.reason]


def test_without_roles_every_part_is_graded() -> None:
    package, ids = roles_package()

    checks = run(package)

    assert [item.documents[0] for item in checks.findings] == sorted(
        ids[key] for key in ("bought", "bought_screw", "plate", "screw", "block")
    )
    assert checks.skipped == ()


# --- suppression (section 8.2) ----------------------------------------------------------------


def test_a_hole_whose_feature_is_suppressed_in_its_configuration_is_skipped() -> None:
    builder = new_builder()
    plate, component = part(builder, "PLATE_FICT")
    tapped(builder, component, "M8x1")
    builder.feature(plate, "Tapped Hole1", suppressed=True)

    checks = run(builder.build().package)

    assert checks.findings == ()
    assert checks.skipped == (
        CoverageItem(
            check=ROW,
            scope=CoverageScope(component_ids=[component], document_ids=[plate]),
            reason=(
                "1 thread on suppressed features or components was not checked for pitch: "
                "Tapped Hole1 (hol:0001)"
            ),
            error=None,
        ),
    )


def suppression_case(case: str) -> EvidencePackage:
    builder = new_builder()
    plate = builder.document("PLATE_FICT", "part", configurations=("Default", "Fine"))
    referenced = "Fine" if case == "configuration" else "Default"
    component = builder.component(plate, configuration=referenced)
    tapped(builder, component, "M8x1")
    if case == "configuration":
        builder.feature(plate, "Tapped Hole1", configuration="Default")
    elif case == "name":
        builder.feature(plate, "Tapped Hole9")
    elif case == "null":
        builder.feature(plate, "Tapped Hole1", suppressed=None)
    return builder.build().package


@pytest.mark.parametrize(
    ("case", "reason"),
    [
        ("tree", "its part's feature tree was not read"),
        ("configuration", "the feature tree was read in configuration Default, not Fine"),
        ("name", "the feature tree holds no feature of that name"),
        ("null", "its suppression state could not be read"),
    ],
)
def test_a_hole_whose_suppression_was_not_read_is_kept_and_its_finding_says_why(
    case: str, reason: str
) -> None:
    [found] = run(suppression_case(case)).findings

    assert found.result.coverage_limits == [
        DRAWINGS,
        f"whether Tapped Hole1 (hol:0001) is suppressed was not read: {reason}",
    ]


def test_a_tree_read_in_two_other_configurations_names_both_ascending() -> None:
    builder = new_builder()
    plate = builder.document("PLATE_FICT", "part", configurations=("Wide", "Fine", "Narrow"))
    component = builder.component(plate, configuration="Fine")
    tapped(builder, component, "M8x1")
    builder.feature(plate, "Tapped Hole1", configuration="Wide")
    builder.feature(plate, "Tapped Hole1", configuration="Narrow")

    [found] = run(builder.build().package).findings

    assert found.result.coverage_limits[-1] == (
        "whether Tapped Hole1 (hol:0001) is suppressed was not read: the feature tree was read "
        "in configuration Narrow and Wide, not Fine"
    )


def test_the_suppression_limits_follow_the_source_order() -> None:
    builder = new_builder()
    plate, component = part(builder, "PLATE_FICT")
    tapped(builder, component, "M8x1", "Tapped Hole1")
    tapped(builder, component, "M6x0.75", "Tapped Hole2")
    builder.cosmetic_thread(component, designation="M6x0.75")

    [found] = run(builder.build().package).findings

    assert found.result.coverage_limits == [
        DRAWINGS,
        "whether Tapped Hole1 (hol:0001) is suppressed was not read: its part's feature tree "
        "was not read",
        "whether Tapped Hole2 (hol:0002) is suppressed was not read: its part's feature tree "
        "was not read",
        COSMETIC,
    ]


def test_a_fastener_row_on_a_suppressed_component_is_skipped() -> None:
    builder = new_builder()
    screw = builder.document("SCREW_FICT", "part")
    component = builder.component(screw, suppression="suppressed")
    builder.fastener_row(component, designation="M8x1")

    checks = run(builder.build().package)

    assert checks.findings == ()
    assert reasons(checks.skipped) == [
        "1 thread on suppressed features or components was not checked for pitch: "
        f"fas:0001 ({component})"
    ]


def test_a_lightweight_fastener_row_is_still_classified() -> None:
    builder = new_builder()
    screw = builder.document("SCREW_FICT", "part")
    component = builder.component(screw, suppression="lightweight")
    builder.fastener_row(component, designation="M8x1")

    [found] = run(builder.build().package).findings

    assert found.documents == (screw,)


# --- the coverage rows of section 8.6 ---------------------------------------------------------


def test_every_source_row_with_its_reason_and_scope() -> None:
    builder = new_builder()
    plate, plate_1 = part(builder, "PLATE_FICT")
    tapped(builder, plate_1, "M5x0.8", "Tapped Hole1")
    tapped(builder, plate_1, "M8", "Tapped Hole2")
    tapped(builder, plate_1, "3/8", "Tapped Hole3")
    tapped(builder, plate_1, None, "Tapped Hole4")
    tapped(builder, plate_1, "M2.3x0.4", "Tapped Hole5")
    tapped(builder, plate_1, "1/8-27 NPT", "Tapped Hole6")
    tapped(builder, plate_1, "M8x1", "Tapped Hole7")
    builder.cosmetic_thread(plate_1, designation="")
    builder.cosmetic_thread(plate_1, designation="G1/4")
    builder.feature(plate, "Tapped Hole1")
    builder.feature(plate, "Tapped Hole2")
    builder.feature(plate, "Tapped Hole3")
    builder.feature(plate, "Tapped Hole4")
    builder.feature(plate, "Tapped Hole5")
    builder.feature(plate, "Tapped Hole6")
    builder.feature(plate, "Tapped Hole7", suppressed=True)
    screw, screw_1 = part(builder, "SCREW_FICT")
    builder.fastener_row(screw_1, designation="M8x1.25")

    checks = run(builder.build().package)

    whole = CoverageScope(component_ids=[plate_1], document_ids=[plate])
    assert checks.findings == ()
    assert checks.checked == (
        CoverageItem(
            check=ROW,
            scope=CoverageScope(component_ids=[plate_1, screw_1], document_ids=[plate, screw]),
            reason=(
                "3 threads have the coarse pitch: M5x0.8 (hol:0001), M8 (hol:0002), M8x1.25 "
                f"(fas:0001); 1 {NO_PITCH.format(verb='has')}"
            ),
            error=None,
        ),
    )
    assert checks.unresolved == (
        CoverageItem(
            check=ROW,
            scope=whole,
            reason=(
                "3 threads could not be read for pitch, so their pitch was not checked: '3/8' on "
                "hol:0003, no designation on hol:0004, no designation on thr:0001"
            ),
            error=None,
        ),
        CoverageItem(
            check=ROW,
            scope=whole,
            reason=(
                "1 thread has a size in no pitch table (ISO 261 to M68, ASME B1.1 UNC to 2 in), "
                "so their pitch was not checked: 'M2.3x0.4' on hol:0005"
            ),
            error=None,
        ),
    )
    assert checks.skipped == (
        CoverageItem(
            check=ROW,
            scope=whole,
            reason=(
                "2 pipe threads were not checked for pitch; a pipe thread has its own series: "
                "'1/8-27 NPT' on hol:0006, 'G1/4' on thr:0002"
            ),
            error=None,
        ),
        CoverageItem(
            check=ROW,
            scope=whole,
            reason=(
                "1 thread on suppressed features or components was not checked for pitch: "
                "Tapped Hole7 (hol:0007)"
            ),
            error=None,
        ),
    )
    assert (checks.threads, checks.coarse) == (10, 3)


def test_every_row_is_the_coverage_only_id() -> None:
    package, _ = roles_package()

    checks = run(package)

    assert COVERAGE_CHECK == ROW
    assert (CHECK_FINE_PITCH, CHECK_NONSTANDARD_PITCH) == (FINE, NONSTANDARD)
    assert {item.check for item in every_row(checks)} <= {ROW}


def test_the_no_pitch_clause_agrees_with_its_count() -> None:
    builder = new_builder()
    plate, first = part(builder, "PLATE_FICT")
    second = builder.component(plate)
    tapped(builder, first, "M8")
    tapped(builder, second, "M8")
    features(builder, plate, "Tapped Hole1")

    checks = run(builder.build().package)

    assert reasons(checks.checked) == [
        "2 threads have the coarse pitch: M8 (hol:0001, hol:0002); "
        f"2 {NO_PITCH.format(verb='have')}"
    ]


def test_only_findings_and_a_checked_row_when_every_thread_is_judged() -> None:
    checks = run(one_tapped_hole("M8x1.25"))

    assert reasons(checks.checked) == ["1 thread has the coarse pitch: M8x1.25 (hol:0001)"]
    assert (checks.unresolved, checks.skipped) == ((), ())


def gap(kind: str, entity_id: str | None, reason: str) -> dict[str, Any]:
    return {
        "kind": "not_extracted",
        "entity_kind": kind,
        "entity_id": entity_id,
        "reason": reason,
        "error": None,
    }


def test_the_not_read_row_lists_every_gap_that_names_no_row_in_its_order() -> None:
    """D20: by kind, then id with null first, then reason - never the package's order; a gap
    about a row that was read is about a classified thread and is not one."""
    builder = new_builder()
    plate, plate_1 = part(builder, "PLATE_FICT")
    tapped(builder, plate_1, "M8x1.25")
    builder.cosmetic_thread(plate_1, designation="M6x1")
    features(builder, plate, "Tapped Hole1")
    screw, screw_1 = part(builder, "SCREW_FICT")
    builder.fastener_row(screw_1, designation="M5x0.8")
    _, shadow = part(builder, "SHADOW_FICT")
    for fields in (
        gap("fastener", None, "identifying a component threw"),
        gap("hole", shadow, "no Hole Wizard feature of this component could be read"),
        gap("thread", "thr:0009", "GetDefinition returned nothing for cosmetic thread 'X1'"),
        gap("hole", None, "'KALO-2' is lightweight; its holes were not read"),
        gap("hole", None, "'KALO-1' is lightweight; its holes were not read"),
        gap("fastener", "fas:0007", "the fastener read threw"),
        gap("hole", "hol:0009", "GetDefinition returned nothing for 'Tapped Hole9'"),
        gap("thread", None, "reading cosmetic thread 'X2' threw"),
        gap("hole", "hol:0001", "the axis of the hole could not be read"),
        gap("thread", "thr:0001", "the thread's hand could not be read"),
        gap("fastener", "fas:0001", "the length could not be read"),
        gap("face", None, "a face could not be read"),
    ):
        builder.gap(**fields)

    checks = run(builder.build().package)

    [row] = [item for item in checks.skipped if "extractor gap" in item.reason]
    assert row == CoverageItem(
        check=ROW,
        scope=CoverageScope(component_ids=[shadow]),
        reason=(
            "8 extractor gaps left holes, cosmetic threads or fasteners unread, so their pitch "
            "was not checked: 'KALO-1' is lightweight; its holes were not read; 'KALO-2' is "
            "lightweight; its holes were not read; no Hole Wizard feature of this component "
            "could be read; GetDefinition returned nothing for 'Tapped Hole9'; reading cosmetic "
            "thread 'X2' threw; GetDefinition returned nothing for cosmetic thread 'X1'; "
            "identifying a component threw; the fastener read threw"
        ),
        error=None,
    )


def nothing_package(**changes: Any) -> EvidencePackage:
    """A `full` package with documents and components but no source."""
    builder = new_builder()
    part(builder, "PLATE_FICT")
    for fields in changes.get("gaps", ()):
        builder.gap(**fields)
    package = builder.build().package
    if "statuses" in changes:
        package = with_extractor(package, statuses=changes["statuses"])
    return package


NOTHING = "no tapped hole, cosmetic thread or fastener in the package states a thread"
ABORTED_BEFORE_HOLES = {"cutlist": "aborted", "hole": "skipped", "fastener": "skipped"}


def test_a_full_package_with_no_source_and_nothing_unread_says_so() -> None:
    checks = run(nothing_package())

    assert checks.skipped == (
        CoverageItem(check=ROW, scope=CoverageScope(), reason=NOTHING, error=None),
    )
    assert (checks.findings, checks.checked, checks.unresolved) == ((), (), ())
    assert (checks.threads, checks.coarse) == (0, 0)


@pytest.mark.parametrize(
    ("changes", "row"),
    [
        (
            {"gaps": [gap("thread", None, "reading cosmetic thread 'X1' threw")]},
            "1 extractor gap left holes, cosmetic threads or fasteners unread, so their pitch "
            "was not checked: reading cosmetic thread 'X1' threw",
        ),
        (
            {"gaps": [gap("thread", "thr:0004", "GetDefinition returned nothing")]},
            "1 extractor gap left holes, cosmetic threads or fasteners unread, so their pitch "
            "was not checked: GetDefinition returned nothing",
        ),
        (
            {"gaps": [gap("fastener", None, "identifying a component threw")]},
            "1 extractor gap left holes, cosmetic threads or fasteners unread, so their pitch "
            "was not checked: identifying a component threw",
        ),
        (
            {"gaps": [gap("fastener", "fas:0004", "the fastener read threw")]},
            "1 extractor gap left holes, cosmetic threads or fasteners unread, so their pitch "
            "was not checked: the fastener read threw",
        ),
        (
            {"gaps": [gap("hole", None, "'KALO-1' is lightweight; its holes were not read")]},
            "1 extractor gap left holes, cosmetic threads or fasteners unread, so their pitch "
            "was not checked: 'KALO-1' is lightweight; its holes were not read",
        ),
        (
            {"statuses": ABORTED_BEFORE_HOLES},
            "tapped holes, cosmetic threads and fastener rows were not read for pitch: the hole "
            "and fastener phases did not run in this dump",
        ),
    ],
    ids=[
        "null thread gap",
        "thread gap naming no row",
        "null fastener gap",
        "fastener gap naming no row",
        "null hole gap",
        "hole phase skipped",
    ],
)
def test_with_no_source_anything_unread_is_said_instead_of_nothing(
    changes: dict[str, Any], row: str
) -> None:
    checks = run(nothing_package(**changes))

    assert reasons(checks.skipped) == [row]


def test_a_model_check_package_says_the_hole_and_fastener_phases_did_not_run() -> None:
    checks = run(with_extractor(nothing_package(), profile="model_check"))

    assert reasons(checks.skipped) == [
        "tapped holes, cosmetic threads and fastener rows were not read for pitch: the hole and "
        "fastener phases did not run (profile model_check)"
    ]


def test_a_model_check_package_still_checks_screws_named_by_their_parts() -> None:
    builder = new_builder()
    screw = builder.screw_document("SHC", "M8-1", 20, serial=1)
    builder.screw(screw, bearing_mm=(0.0, 0.0, 0.0), direction=(0.0, 0.0, 1.0))
    package = with_extractor(builder.build().package, profile="standards")

    checks = run(package)

    assert [item.documents for item in checks.findings] == [(screw,)]
    assert reasons(checks.skipped) == [
        "tapped holes, cosmetic threads and fastener rows were not read for pitch: the hole and "
        "fastener phases did not run (profile standards)"
    ]


def test_hole_and_fastener_phases_skipped_behind_an_aborted_one_are_named() -> None:
    checks = run(with_extractor(nothing_package(), statuses=ABORTED_BEFORE_HOLES))

    assert reasons(checks.skipped) == [
        "tapped holes, cosmetic threads and fastener rows were not read for pitch: the hole and "
        "fastener phases did not run in this dump"
    ]


def test_a_hole_phase_switched_off_alone_is_named_alone() -> None:
    """A phase the options switch off is `skipped` too (`DumpPhase.status`)."""
    checks = run(with_extractor(nothing_package(), statuses={"hole": "skipped"}))

    assert reasons(checks.skipped) == [
        "tapped holes and cosmetic threads were not read for pitch: the hole phase did not run "
        "in this dump"
    ]


def test_a_fastener_phase_skipped_alone_is_named_alone() -> None:
    """The hole phase aborted, recording its own null-id gap (`PackageWriter.cs:809-825`); the
    fastener phase behind it never ran."""
    package = nothing_package(
        gaps=[gap("hole", None, "the hole phase met an open circuit")],
        statuses={"hole": "aborted", "fastener": "skipped", "face": "skipped", "body": "skipped"},
    )

    checks = run(package)

    assert reasons(checks.skipped) == [
        "1 extractor gap left holes, cosmetic threads or fasteners unread, so their pitch was "
        "not checked: the hole phase met an open circuit",
        "fastener rows were not read for pitch: the fastener phase did not run in this dump",
    ]


def test_a_failed_hole_phase_is_in_the_not_read_row_and_gives_no_phases_row() -> None:
    package = nothing_package(
        gaps=[gap("hole", None, "the hole phase failed")], statuses={"hole": "failed"}
    )

    checks = run(package)

    assert reasons(checks.skipped) == [
        "1 extractor gap left holes, cosmetic threads or fasteners unread, so their pitch was "
        "not checked: the hole phase failed"
    ]


def test_a_reused_packages_skipped_phase_rows_are_not_read() -> None:
    package = nothing_package()
    every_phase = {phase.name: "skipped" for phase in package.extractor.phases}

    checks = run(with_extractor(package, statuses=every_phase, reused_from="run-0001"))

    assert reasons(checks.skipped) == [NOTHING]


def test_a_package_with_no_phase_rows_is_read_by_its_gaps_alone() -> None:
    package = nothing_package()
    package = package.model_copy(
        update={"extractor": package.extractor.model_copy(update={"phases": []})}
    )

    assert reasons(run(package).skipped) == [NOTHING]


# --- order: the result does not depend on the package's order ---------------------------------


def busy_package() -> EvidencePackage:
    """Every source, row and limit at once: the examples, an unreadable hole, a pipe thread,
    a suppressed feature, a cosmetic thread, a named screw and gaps."""
    builder = new_builder()
    plate, plate_1 = part(builder, "PLATE_FICT")
    plate_2 = builder.component(plate)
    for component in (plate_1, plate_2):
        tapped(builder, component, "M8x1", "Tapped Hole1")
        tapped(builder, component, "M6x0.75", "Tapped Hole2")
        tapped(builder, component, "M8", "Tapped Hole3")
        tapped(builder, component, "3/8", "Tapped Hole4")
        tapped(builder, component, "M8x1.5", "Tapped Hole5")
    builder.cosmetic_thread(plate_1, designation="G1/4")
    builder.cosmetic_thread(plate_2, designation="M8 x 1.0")
    features(builder, plate, "Tapped Hole1", "Tapped Hole2", "Tapped Hole3", "Tapped Hole4")
    builder.feature(plate, "Tapped Hole5", suppressed=True)
    block, block_1 = part(builder, "BLOCK_FICT")
    tapped(builder, block_1, "M10x1.25")
    screw = builder.screw_document("SHC", "M8-1", 20, serial=1)
    builder.screw(screw, bearing_mm=(0.0, 0.0, 0.0), direction=(0.0, 0.0, 1.0))
    builder.screw(screw, bearing_mm=(20.0, 0.0, 0.0), direction=(0.0, 0.0, 1.0))
    nut, nut_1 = part(builder, "NUT_FICT")
    builder.fastener_row(nut_1, designation="#10-32", kind="nut")
    builder.gap(**gap("hole", None, "'KALO-2' is lightweight; its holes were not read"))
    builder.gap(**gap("hole", None, "'KALO-1' is lightweight; its holes were not read"))
    builder.gap(**gap("thread", None, "reading cosmetic thread 'X2' threw"))
    return builder.build().package


def shuffled(package: EvidencePackage, seed: int) -> EvidencePackage:
    rng = random.Random(seed)
    updates: dict[str, Any] = {}
    for name in ("documents", "components", "holes", "threads", "fasteners", "faces", "bodies",
                 "features", "gaps"):
        items = list(getattr(package, name))
        rng.shuffle(items)
        updates[name] = items
    phases = list(package.extractor.phases)
    rng.shuffle(phases)
    updates["extractor"] = package.extractor.model_copy(update={"phases": phases})
    return package.model_copy(update=updates)


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_the_result_is_identical_whatever_the_order_of_the_package(seed: int) -> None:
    package = busy_package()
    expected = run(package)

    assert expected.findings and expected.unresolved and expected.skipped and expected.checked
    assert run(shuffled(package, seed)) == expected


# --- section 8.10: reported twice, on purpose --------------------------------------------------


def joint_package(screw_thread: str, hole_thread: str) -> tuple[EvidencePackage, str, str]:
    builder = new_builder()
    plate = builder.document("PLATE_FICT", "part", material="6061-T6")
    plate_1 = builder.component(plate)
    builder.hole(
        plate_1,
        hole_type="tapped",
        size="M8",
        end_condition="blind",
        instances=[Instance(origin_mm=(0.0, 0.0, 0.0), direction=(0.0, 0.0, 1.0), faces=FACES)],
        thread=hole_thread,
        thread_depth_mm=12.0,
        hole_depth_mm=15.0,
        feature_name="Tapped Hole1",
    )
    features(builder, plate, "Tapped Hole1")
    screw = builder.document("SCREW_FICT", "part", material="Alloy Steel")
    screw_1 = builder.component(screw)
    builder.fastener_row(screw_1, designation=screw_thread, length_mm=20.0)
    return builder.build().package, plate, screw


def thread_match(package: EvidencePackage) -> str:
    [fastener] = package.fasteners
    [hole] = package.holes
    layer = ClampedLayer(
        component_id="cmp:0099", thickness=Quantity(value=5.0, unit="mm"), material="6061-T6"
    )
    results = check_fastener_joint(fastener, hole, [layer], hole_material="6061-T6")
    [match] = [result for result in results if result.check == "fastener.thread_match"]
    return match.status


def test_a_fine_screw_in_a_coarse_hole_is_a_mismatch_and_a_fine_pitch_finding() -> None:
    package, _, screw = joint_package("M8x1", "M8x1.25")

    assert thread_match(package) == "demonstrated"
    assert [(item.result.check, item.documents) for item in run(package).findings] == [
        (FINE, (screw,))
    ]


def test_a_screw_with_no_pitch_in_a_fine_hole_passes_the_match_and_the_hole_is_flagged() -> None:
    package, plate, _ = joint_package("M8", "M8x1")

    checks = run(package)

    assert thread_match(package) == "checked_within_scope"
    assert [(item.result.check, item.documents) for item in checks.findings] == [(FINE, (plate,))]
    assert reasons(checks.checked) == [
        f"1 thread has the coarse pitch: M8 (fas:0001); 1 {NO_PITCH.format(verb='has')}"
    ]
