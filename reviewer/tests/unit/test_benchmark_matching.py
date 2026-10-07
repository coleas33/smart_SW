"""The one matcher, `benchmark/matching.py` (T022, for T023; `scoring.md` 2 and 11).

A finding **matches** an answer-key entry when three things hold, and nothing else counts:

1. **Checks** (2.1, FR-001): the finding's check equals the entry's exact check, or starts with a
   family's id and a dot (`answer_key_model.pattern_covers`). A sibling rule never matches.
2. **Targets** (2.2, FR-003): the finding's parts (its `component_ids`) meet the entry's
   `component_ids`, or its documents meet the entry's `document_ids`. Its documents are its
   drawing locations', and its provenance's only when it names no part and no location: a
   component finding's provenance holds its part document and is never read.
3. **References** (2.3, FR-061): on a reference-keyed check, the finding's references, read from
   `inputs` alone by the kind of item the check names, equal one covered item's, roles never
   compared.

Findings on checks and targets are built as data (`make_finding`); "real" findings are recorded
by the tool that writes them (research §2 d2-model-finding-unmatchable), and the references of
test 4 are read off results the real checks return. The overlap test of `answer-key.md` 5 is
the same primitives (test 6). The joint kind, the unknown-role case and US1-17 read the results
owner decision 19A gives every path (T025); forbidden entries are US3's (T083). Every id and
description is fictional.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, get_args

import pytest

from swreview.benchmark import answer_key_model, matching
from swreview.benchmark.answer_key_model import CorrectCondition, KnownDefect, ReferenceKind
from swreview.checks.fastener import CHECK_BOTTOMING, check_fastener_joint
from swreview.checks.standards.profile import load_profile
from swreview.findings import MODEL_FINDING_CHECK, Calculation, Finding
from swreview.ir.loader import load_package
from swreview.ir.models import SourceRef
from swreview.tools import checks_fastener, checks_fit
from swreview.tools.context import ToolContext, context_for, use_context
from swreview.tools.recording import result_to_finding
from tests.golden.test_golden import FIXTURES_DIR
from tests.support.packages import build_package
from tests.unit.test_answer_key import (
    OTHER_DIMENSION,
    SHEET_DIMENSION,
    THIRD_DIMENSION,
    condition,
    defect,
)
from tests.unit.test_checks_fastener import layer, mm, screw, tapped_hole
from tests.unit.test_drawing_finding_number_guard import (
    FIRST,
    INGESTED,
    NATIVE,
    guarded_package,
    record,
)
from tests.unit.test_joint_alignment import (
    UNKNOWN_ROLE_INSTANCES,
    dowel_joint,
    pattern_of,
    unknown_role_joint,
)
from tests.unit.test_scorecard import make_finding
from tests.unit.test_tool_access import screw_over_plate
from tests.unit.test_tools_check_joints import PROFILE_A, run, with_profile
from tests.unit.test_tools_checks_fastener import (
    DRAWING,
    SHEET,
    TOLERANCE_DIMENSION,
    joint_package,
)

DRAWINGS = guarded_package(build_package)
"""`build_package`'s assembly, whose two components instantiate the housing part `doc:2`, with
two drawings beside it: `INGESTED` (`doc:3`) and `NATIVE` (`doc:4`)."""

PART_DOCUMENT = "doc:2"

Entry = KnownDefect | CorrectCondition

FOUR_SCREWS = [{"fastener": f"fst:000{n}", "hole": f"hol:000{n}"} for n in range(1, 5)]
"""Four screw joints in one plate, each a joint element (`answer-key.md` 2.5)."""

FIRST_JOINT = ["hol:0001#1", "hol:0002#1"]
SECOND_JOINT = ["hol:0001#2", "hol:0002#2"]
"""The two joints of `pattern_of(2)`, each a tapped instance and the countersink over it."""


def known_defect(**fields: Any) -> KnownDefect:
    """`test_answer_key.defect`'s well-formed known defect, with `fields` replacing its
    defaults, built through the model."""
    return KnownDefect.model_validate(defect(**fields))


def correct_condition(**fields: Any) -> CorrectCondition:
    """`test_answer_key.condition`'s well-formed correct condition, built through the model."""
    return CorrectCondition.model_validate(condition(**fields))


def joint_map_findings(context: ToolContext, check: str) -> list[Finding]:
    """The `check` findings `check_joints`, the joint map's tool, records over `context`."""
    run(context)
    return [finding for finding in context.require_session().findings if finding.check == check]


def golden(name: str) -> tuple[ToolContext, dict[str, Any]]:
    """A context over the golden fixture `name`'s package, and its case's kwargs: the
    references the golden checks the package with."""
    directory = FIXTURES_DIR / name
    case = json.loads((directory / "case.json").read_text(encoding="utf-8"))
    return context_for(load_package(directory).package), case["kwargs"]


def test_the_matcher_reads_the_grammar_and_the_kinds_from_the_key_model() -> None:
    """Plan "Phase 0 and Phase 1" point 1: one definition of each, never restated."""
    assert matching.pattern_covers is answer_key_model.pattern_covers
    assert matching.REFERENCE_KEYED_CHECKS is answer_key_model.REFERENCE_KEYED_CHECKS


# --- 1. checks (2.1; US1-1, US1-2, SC-002) -------------------------------------------------


def test_a_thread_match_finding_on_one_of_four_keyed_screws_matches_no_bottoming_entry() -> None:
    """US1-1: the four screws keyed together under `fastener.bottoming`; a thread-match finding
    on the first names that screw's joint exactly and is still another rule."""
    bottoming = known_defect(
        check="fastener.bottoming",
        component_ids=["cmp:0001", "cmp:0002"],
        references=FOUR_SCREWS,
    )
    on_the_first_screw = ["fst:0001", "hol:0001"]

    thread_match = make_finding(check="fastener.thread_match", inputs=on_the_first_screw)
    bottoming_finding = make_finding(check="fastener.bottoming", inputs=on_the_first_screw)

    assert not matching.matches(thread_match, bottoming)
    assert matching.matches(bottoming_finding, bottoming)


def test_rms_folders_present_does_not_match_rms_folders_ordered() -> None:
    ordered = known_defect(check="rms.folders.ordered")

    assert not matching.matches(make_finding(check="rms.folders.present"), ordered)
    assert matching.matches(make_finding(check="rms.folders.ordered"), ordered)


@pytest.mark.parametrize("check", ["rms.folders.present", "rms.sketches.profile.fully_defined"])
def test_a_family_covers_its_checks_at_any_depth(check: str) -> None:
    assert matching.matches(make_finding(check=check), known_defect(check="rms.*"))


@pytest.mark.parametrize(
    ("check", "covered"),
    [
        ("fastener.head.fit", True),
        ("fastener.head.recess.depth", True),
        ("fastener.head", False),
        ("fastener.heads.x", False),
        ("fastener.head_fit", False),
    ],
)
def test_the_family_fastener_head_covers_only_what_starts_with_its_id_and_a_dot(
    check: str, covered: bool
) -> None:
    """US1-2 and SC-002 on `fastener.head.*` (owner decision 37A): AK-4 refuses `fastener.*` on a
    known defect, and this family covers no reference-keyed check, `fastener.head_fit` included."""
    family = known_defect(check="fastener.head.*")

    assert matching.matches(make_finding(check=check), family) is covered


# --- 2. targets (2.2; US1-7, FR-003) -------------------------------------------------------

HYGIENE = "hygiene.revision_present"
"""The one check the target tests key and find on, so that only the targets differ."""


def hygiene_finding(**targets: Any) -> Finding:
    """A finding as data on `HYGIENE` over `DRAWINGS`, naming `targets`."""
    return make_finding(package=DRAWINGS, check=HYGIENE, **targets)


def hygiene_defect(**targets: Any) -> KnownDefect:
    """A known defect on `HYGIENE`, on `targets`."""
    return known_defect(check=HYGIENE, **targets)


@pytest.mark.parametrize(
    ("finding_parts", "entry_parts", "overlap"),
    [
        (["cmp:0001", "cmp:0002"], ["cmp:0002"], True),
        (["cmp:0001"], ["cmp:0001", "cmp:0002"], True),
        (["cmp:0001"], ["cmp:0002"], False),
    ],
)
def test_parts_overlap_when_they_intersect(
    finding_parts: list[str], entry_parts: list[str], overlap: bool
) -> None:
    finding = hygiene_finding(component_ids=finding_parts)
    entry = hygiene_defect(component_ids=entry_parts)

    assert matching.finding_parts(finding) == set(finding_parts)
    assert matching.targets_overlap(finding, entry) is overlap
    assert matching.matches(finding, entry) is overlap


def test_a_finding_s_documents_are_its_drawing_locations_documents() -> None:
    finding = hygiene_finding(
        component_ids=[],
        drawing_locations=[SourceRef(document_id=INGESTED, sheet=FIRST)],
    )
    on_the_drawing = hygiene_defect(component_ids=[], document_ids=[INGESTED])
    on_the_other_drawing = hygiene_defect(component_ids=[], document_ids=[NATIVE])

    assert matching.finding_documents(finding) == {INGESTED}
    assert matching.targets_overlap(finding, on_the_drawing)
    assert matching.matches(finding, on_the_drawing)
    assert not matching.targets_overlap(finding, on_the_other_drawing)
    assert not matching.matches(finding, on_the_other_drawing)


def test_either_list_suffices_a_shared_document_overlaps_an_entry_on_other_parts() -> None:
    finding = hygiene_finding(
        component_ids=[],
        drawing_locations=[SourceRef(document_id=INGESTED, sheet=FIRST)],
    )
    entry = hygiene_defect(component_ids=["cmp:0002"], document_ids=[INGESTED])

    assert matching.targets_overlap(finding, entry)
    assert matching.matches(finding, entry)


def test_a_document_scoped_finding_reaches_its_documents_through_its_provenance() -> None:
    """US1-7: a standards finding on a drawing, bound through `document_ids` with no location
    (`findings.py:338-343`), names its document only in its provenance."""
    finding = hygiene_finding(component_ids=[], document_ids=[NATIVE])
    entry = hygiene_defect(component_ids=[], document_ids=[NATIVE])

    assert [item.document_id for item in finding.provenance] == [NATIVE]
    assert matching.finding_documents(finding) == {NATIVE}
    assert matching.targets_overlap(finding, entry)
    assert matching.matches(finding, entry)


def test_a_finding_with_a_drawing_location_does_not_read_its_provenance() -> None:
    """The provenance's documents count only when the finding names no part and no location."""
    finding = hygiene_finding(
        component_ids=[],
        drawing_locations=[SourceRef(document_id=INGESTED, sheet=FIRST)],
        document_ids=[NATIVE],
    )
    entry = hygiene_defect(component_ids=[], document_ids=[NATIVE])

    assert {item.document_id for item in finding.provenance} == {INGESTED, NATIVE}
    assert matching.finding_documents(finding) == {INGESTED}
    assert not matching.targets_overlap(finding, entry)
    assert not matching.matches(finding, entry)


def test_a_component_finding_s_provenance_is_never_read() -> None:
    """FR-003: `findings.py:273-290` puts the part document in a component finding's
    provenance, so a hygiene finding on the housing would otherwise reach an entry on any
    drawing or document of that part."""
    finding = hygiene_finding(component_ids=["cmp:0001"])
    entry = hygiene_defect(component_ids=[], document_ids=[PART_DOCUMENT])

    assert [item.document_id for item in finding.provenance] == [PART_DOCUMENT]
    assert matching.finding_documents(finding) == set()
    assert not matching.targets_overlap(finding, entry)
    assert not matching.matches(finding, entry)


def test_references_alone_never_match_an_entry_on_other_parts() -> None:
    """All three conditions hold or none does: the screw's joint, named on another part."""
    entry = known_defect(
        check="fastener.bottoming",
        component_ids=["cmp:0001", "cmp:0002"],
        references=FOUR_SCREWS,
    )
    finding = make_finding(
        check="fastener.bottoming", component_ids=["cmp:0002"], inputs=["fst:0001", "hol:0001"]
    )
    elsewhere = make_finding(
        package=DRAWINGS,
        check="fastener.bottoming",
        component_ids=[],
        drawing_locations=[SourceRef(document_id=INGESTED, sheet=FIRST)],
        inputs=["fst:0001", "hol:0001"],
    )

    assert matching.matches(finding, entry)
    assert not matching.targets_overlap(elsewhere, entry)
    assert not matching.matches(elsewhere, entry)


# --- 3. real: the model's drawing finding (US1-6) ------------------------------------------


def test_the_model_s_drawing_finding_matches_an_entry_on_its_drawing_and_no_part_entry() -> None:
    """`record_drawing_finding` (`tools/session.py:456-531`) names its drawing locations, so it
    reaches an entry on that drawing, and no part reaches it."""
    context = context_for(DRAWINGS)
    with use_context(context):
        record()
    [finding] = context.require_session().findings

    def keyed(**targets: Any) -> KnownDefect:
        return known_defect(
            check=MODEL_FINDING_CHECK, producer="model", expected_status="suspected", **targets
        )

    assert (finding.check, finding.source, finding.component_ids) == (
        MODEL_FINDING_CHECK,
        "model",
        [],
    )
    assert matching.matches(finding, keyed(component_ids=[], document_ids=[INGESTED]))
    assert not matching.matches(finding, keyed(component_ids=["cmp:0001", "cmp:0002"]))
    assert not matching.matches(finding, keyed(component_ids=[], document_ids=[PART_DOCUMENT]))
    assert not matching.matches(finding, keyed(component_ids=[], document_ids=[NATIVE]))


# --- 4. references, one test per kind, on results the real checks return (2.3; US5-16) ---


def test_each_kind_reads_its_own_entries_of_inputs_and_nothing_else() -> None:
    """Section 2.3's table over one finding holding every shape of input: plain ids for the
    joint and hole-pair kinds, `#` instances for the recess and joint-instance kinds, each
    `Dimension`'s triple for fits and stacks. Its drawing locations and its calculation's
    inputs hold ids and a dimension's place too, and are never read."""
    calculation = Calculation(
        model="fictional.check",
        inputs={"hole_a": "hol:0009", "recess_instance": "hol:0009#1"},
        assumptions=[],
        excluded_effects=[],
        result={"ok": True},
        units_out="mm",
        function="fictional.check",
        function_version="1",
    )
    finding = make_finding(
        package=DRAWINGS,
        component_ids=[],
        drawing_locations=[SourceRef(document_id=INGESTED, sheet=FIRST, annotation="DIM-1")],
        inputs=["fst:0001", "hol:0001", "hol:0002#1", TOLERANCE_DIMENSION],
        calculation=calculation,
    )
    plain = {"fst:0001", "hol:0001"}
    instances = {"hol:0002#1"}
    dimensions = {(DRAWING, SHEET, "dim-1-1")}
    expected: dict[ReferenceKind, set[Any]] = {
        "joint": plain,
        "hole pair": plain,
        "recess": instances,
        "joint instances": instances,
        "fit": dimensions,
        "stack": dimensions,
    }

    assert set(expected) == set(get_args(ReferenceKind))
    for kind, references in expected.items():
        assert matching.finding_references(finding, kind) == references, kind


def test_covered_items_are_each_element_as_the_set_of_its_references() -> None:
    entry = known_defect(
        check="fastener.bottoming",
        component_ids=["cmp:0001", "cmp:0002"],
        references=FOUR_SCREWS[:2],
    )

    assert matching.covered_items(entry) == [
        {"fst:0001", "hol:0001"},
        {"fst:0002", "hol:0002"},
    ]
    assert matching.covered_items(known_defect()) == []


@pytest.mark.parametrize(
    ("hole", "status"),
    [("hole:tapped", "checked_within_scope"), ("hole:unknown-depth", "unresolved")],
    ids=["resolved", "unresolved"],
)
def test_a_joint_matches_its_bottoming_result_on_either_path_and_no_other_screw(
    hole: str, status: str
) -> None:
    """19A: `fastener.bottoming` leads its inputs with the fastener and hole ids on every path,
    so the joint kind reads them off a resolved and an unresolved result alike. `fst:no-length`
    is another screw between the same two parts, `hole:far` another hole of the joint's parts."""
    context = context_for(joint_package(build_package))
    with use_context(context):
        checks_fastener.check_fastener_joint("fst:screw", hole, ["cmp:0003"])
    [bottoming] = [
        finding
        for finding in context.require_session().findings
        if finding.check == CHECK_BOTTOMING
    ]

    def keyed(fastener: str, keyed_hole: str) -> KnownDefect:
        return known_defect(
            check=CHECK_BOTTOMING,
            component_ids=["cmp:0001", "cmp:0004"],
            references=[{"fastener": fastener, "hole": keyed_hole}],
        )

    assert bottoming.status == status
    assert matching.finding_references(bottoming, "joint") == {"fst:screw", hole}
    assert matching.matches(bottoming, keyed("fst:screw", hole))
    assert not matching.matches(bottoming, keyed("fst:no-length", hole))
    assert not matching.matches(bottoming, keyed("fst:screw", "hole:far"))


def test_a_recess_matches_through_its_hole_instance_and_never_the_screw_s_component() -> None:
    """`fastener.head_fit` writes the recess instance beside the screw's component
    (`checks/tool_access.py:409`); the recess kind reads the `#` instance alone."""
    package, _ = screw_over_plate(counterbore=(9.0, 5.5))
    [head_fit] = joint_map_findings(context_for(package), "fastener.head_fit")

    def keyed(recess: str) -> KnownDefect:
        return known_defect(
            check="fastener.head_fit", component_ids=["cmp:0003"], references=[{"recess": recess}]
        )

    assert head_fit.inputs == ["hol:0002#1", "cmp:0002"]
    assert matching.finding_references(head_fit, "recess") == {"hol:0002#1"}
    assert matching.matches(head_fit, keyed("hol:0002#1"))
    assert not matching.matches(head_fit, keyed("hol:0002#2"))


@pytest.mark.parametrize(
    "tolerance",
    [None, {"document_id": DRAWING, "sheet": SHEET, "annotation": "dim-1-1"}],
    ids=["no tolerance", "a drawn tolerance"],
)
def test_a_hole_pair_matches_through_its_two_hole_ids(tolerance: dict[str, str] | None) -> None:
    """`hole.coaxiality` writes both hole ids on both paths (`checks/hole_alignment.py:108,
    140`), the drawn tolerance's `Dimension` beside them on the second, which the hole-pair
    kind does not read. `hole:unknown-depth` is another hole between the same two parts."""
    context = context_for(joint_package(build_package))
    with use_context(context):
        checks_fastener.check_hole_alignment("hole:tapped", "hole:far", tolerance)
    [coaxiality] = context.require_session().findings

    def keyed(*holes: str) -> KnownDefect:
        return known_defect(
            check="hole.coaxiality",
            component_ids=["cmp:0001", "cmp:0003"],
            references=[{"holes": list(holes)}],
        )

    assert matching.finding_references(coaxiality, "hole pair") == {"hole:tapped", "hole:far"}
    assert matching.matches(coaxiality, keyed("hole:far", "hole:tapped"))
    assert not matching.matches(coaxiality, keyed("hole:unknown-depth", "hole:far"))


def test_joint_instances_match_the_no_fastener_result_exactly_never_part_of_the_joint() -> None:
    """The joint map's no-fastener result names every instance of its joint
    (`checks/joint_alignment.py:236`); an entry naming part of the joint is another set."""
    package = dowel_joint(3.0, 3.1, 0.0, size="FICT").build().package
    [alignment] = joint_map_findings(context_for(package), "hole.nominal_alignment")

    def keyed(*instances: str) -> KnownDefect:
        return known_defect(
            check="hole.nominal_alignment",
            component_ids=["cmp:0001", "cmp:0002"],
            references=[{"hole_instances": list(instances)}],
            expected_status="unresolved",
        )

    assert alignment.status == "unresolved"
    assert "the fastener size of the joint" in alignment.observed
    assert matching.matches(alignment, keyed("hol:0002#1", "hol:0001#1"))
    assert not matching.matches(alignment, keyed("hol:0001#1"))


def test_joint_instances_match_the_missing_tolerance_result_and_not_the_other_joint() -> None:
    """The tolerances fixture with profile A attached: its screw joint's stack is unresolved
    for a tolerance (`checks/joint_alignment.py:520`), and the dowel joint between the same
    two plates is the sibling."""
    context = with_profile("tolerances", load_profile(PROFILE_A))
    [stack] = [
        finding
        for finding in joint_map_findings(context, "hole.position_stack")
        if finding.status == "unresolved"
    ]

    def keyed(*instances: str) -> KnownDefect:
        return known_defect(
            check="hole.position_stack",
            component_ids=["cmp:0001", "cmp:0002"],
            references=[{"hole_instances": list(instances)}],
            expected_status="unresolved",
        )

    assert "a tolerance for the size of hol:0002#1 is unknown" in stack.observed
    assert matching.matches(stack, keyed("hol:0002#1", "hol:0004#1"))
    assert not matching.matches(stack, keyed("hol:0001#1", "hol:0003#1"))


def test_joint_instances_match_the_unknown_role_result_through_every_instance() -> None:
    """19A: the unknown-role result names every instance of its joint, not only the one whose
    hole type is unknown, so an entry on the whole joint matches it and an entry naming that
    instance alone is another set."""
    package = unknown_role_joint().build().package
    [alignment] = joint_map_findings(context_for(package), "hole.nominal_alignment")

    def keyed(*instances: str) -> KnownDefect:
        return known_defect(
            check="hole.nominal_alignment",
            component_ids=["cmp:0001", "cmp:0002", "cmp:0003"],
            references=[{"hole_instances": list(instances)}],
            expected_status="unresolved",
        )

    assert alignment.status == "unresolved"
    assert "the role of hol:0002 (its hole type is unknown)" in alignment.observed
    assert matching.finding_references(alignment, "joint instances") == set(
        UNKNOWN_ROLE_INSTANCES
    )
    assert matching.matches(alignment, keyed(*reversed(UNKNOWN_ROLE_INSTANCES)))
    assert not matching.matches(alignment, keyed("hol:0002#1"))


def test_a_fit_matches_its_pair_either_way_round_and_never_the_bore_against_itself() -> None:
    """Roles are not compared: a fit called with bore and shaft swapped names the same pair. The
    bore against itself, and another fit on the sheet sharing the bore, name other sets (the
    matcher never resolves a reference; the key loader's row 13 does)."""
    context, refs = golden("shaft-bore")
    bore, shaft = refs["bore_ref"], refs["shaft_ref"]
    with use_context(context):
        checks_fit.check_fit(bore, shaft)
        checks_fit.check_fit(shaft, bore)
        checks_fit.check_fit(bore, bore)
    as_drawn, swapped, against_itself = context.require_session().findings

    def keyed(other: dict[str, str]) -> KnownDefect:
        return known_defect(
            check="fit.size_only",
            component_ids=[],
            document_ids=[bore["document_id"]],
            references=[{"bore": bore, "shaft": other}],
        )

    assert matching.matches(as_drawn, keyed(shaft))
    assert matching.matches(swapped, keyed(shaft))
    assert not matching.matches(against_itself, keyed(shaft))
    assert not matching.matches(as_drawn, keyed({**shaft, "annotation": "DIM-PIN"}))


def test_a_stack_matches_its_contributors_and_target_exactly() -> None:
    """Equality, not "names all those of one": a chain missing a contributor, or holding one the
    entry does not, neither credits nor clears the planted stack."""
    context, refs = golden("plate-stack")
    contributors, signs, target = refs["dimension_refs"], refs["signs"], refs["target_gap_ref"]
    with use_context(context):
        checks_fit.check_axial_stack(contributors, signs, target)
        checks_fit.check_axial_stack(contributors[:-1], signs[:-1], target)
    whole, one_short = context.require_session().findings

    def keyed(chain: list[dict[str, str]]) -> KnownDefect:
        return known_defect(
            check="stack.worst_case",
            component_ids=[],
            document_ids=[target["document_id"]],
            references=[{"contributors": chain, "target": target}],
        )

    assert matching.matches(whole, keyed(contributors))
    assert not matching.matches(one_short, keyed(contributors))
    assert not matching.matches(whole, keyed(contributors[:-1]))
    assert matching.matches(one_short, keyed(contributors[:-1]))


def test_us1_17_one_joint_s_unresolved_bottoming_matches_its_own_entry_and_no_other() -> None:
    """US1-17 at the matcher: four screws in one plate, each joint's `fastener.bottoming` keyed
    as its own known defect, expected unresolved, and the third joint's thread depth missing.
    Each joint's finding, built through the real `check_fastener_joint` and `build_finding`
    (`tools/recording.result_to_finding`), matches its own joint's entry and no other; the third
    is the one unresolved (the scored half is T036's)."""
    context = context_for(build_package())
    entries = [
        known_defect(
            id=f"D-{number}",
            check=CHECK_BOTTOMING,
            component_ids=["cmp:0001", "cmp:0002"],
            references=[joint],
            expected_status="unresolved",
        )
        for number, joint in enumerate(FOUR_SCREWS, start=1)
    ]

    findings = []
    for number, joint in enumerate(FOUR_SCREWS, start=1):
        fastener = screw().model_copy(update={"id": joint["fastener"]})
        hole = tapped_hole(thread_depth=None if number == 3 else mm(12.0)).model_copy(
            update={"id": joint["hole"]}
        )
        [bottoming] = [
            result
            for result in check_fastener_joint(
                fastener, hole, [layer(mm(3.0))], hole_material="6061-T6"
            )
            if result.check == CHECK_BOTTOMING
        ]
        findings.append(
            result_to_finding(context, bottoming, component_ids=["cmp:0001", "cmp:0002"])
        )

    assert [finding.status for finding in findings] == [
        "demonstrated",
        "demonstrated",
        "unresolved",
        "demonstrated",
    ]
    assert "the usable thread depth of hole hol:0003" in findings[2].observed
    for finding, own in zip(findings, entries, strict=True):
        assert [entry.id for entry in entries if matching.matches(finding, entry)] == [own.id]


# --- 5. a folded joint-map finding (2.3; `checks/joints.py:1185-1226`) ---------------------


def test_a_folded_joint_map_finding_matches_through_its_first_joint() -> None:
    """Two joints of one pattern whose alignment results agree fold into one finding naming the
    first joint's instances; an entry covering both joints matches it, one naming only the
    second does not (`answer-key.md` 2.5: a folded condition is one entry)."""
    _, package = pattern_of(2)
    [folded] = joint_map_findings(context_for(package), "hole.nominal_alignment")

    def keyed(*joints: list[str]) -> CorrectCondition:
        return correct_condition(
            check="hole.nominal_alignment",
            component_ids=["cmp:0001", "cmp:0002"],
            references=[{"hole_instances": joint} for joint in joints],
        )

    assert folded.observed.startswith(
        "2 joints (jnt:0001 hol:0001#1+hol:0002#1, jnt:0002 hol:0001#2+hol:0002#2): "
    )
    assert matching.matches(folded, keyed(FIRST_JOINT, SECOND_JOINT))
    assert not matching.matches(folded, keyed(SECOND_JOINT))


# --- 6. `answer-key.md` 5's overlap table, through the matcher alone -----------------------


def assert_overlap(first: Entry, second: Entry, overlap: bool) -> None:
    """Overlap is symmetric: one finding could match both, whichever is named first."""
    assert matching.entries_overlap(first, second) is overlap
    assert matching.entries_overlap(second, first) is overlap


@pytest.mark.parametrize(
    ("first", "second", "overlap"),
    [
        ("rms.folders.present", "rms.folders.present", True),
        ("rms.*", "rms.folders.present", True),
        ("rms.*", "rms.sketches.*", True),
        ("rms.*", "rms.*", True),
        ("fastener.head", "fastener.head.*", False),
        ("rms.folders.present", "rms.folders.ordered", False),
        ("rms.sketches.*", "rms.folders.*", False),
        ("rms.*", "rmsx.folders.present", False),
    ],
)
def test_checks_overlap_when_equal_or_one_family_covers_the_other(
    first: str, second: str, overlap: bool
) -> None:
    assert_overlap(
        known_defect(id="D-1", check=first), known_defect(id="D-2", check=second), overlap
    )


@pytest.mark.parametrize(
    ("first", "second", "overlap"),
    [
        ({"component_ids": ["cmp:0001", "cmp:0002"]}, {"component_ids": ["cmp:0002"]}, True),
        (
            {"component_ids": [], "document_ids": ["doc:3"]},
            {"component_ids": [], "document_ids": ["doc:3", "doc:4"]},
            True,
        ),
        (
            {"component_ids": ["cmp:0001"], "document_ids": ["doc:3"]},
            {"component_ids": ["cmp:0002"], "document_ids": ["doc:3"]},
            True,
        ),
        (
            {"component_ids": ["cmp:0001"], "document_ids": ["doc:3"]},
            {"component_ids": ["cmp:0002"], "document_ids": ["doc:4"]},
            False,
        ),
        ({"component_ids": ["cmp:0001"]}, {"component_ids": [], "document_ids": ["doc:2"]}, False),
    ],
    ids=[
        "intersecting parts",
        "intersecting documents",
        "a shared document suffices",
        "disjoint parts and documents",
        "a part and its document are two targets",
    ],
)
def test_targets_overlap_when_parts_or_documents_intersect(
    first: dict[str, Any], second: dict[str, Any], overlap: bool
) -> None:
    assert_overlap(known_defect(id="D-1", **first), known_defect(id="D-2", **second), overlap)


def thread_match(entry_id: str, *joints: dict[str, str]) -> KnownDefect:
    """A `fastener.thread_match` defect between the plate and the cover on `joints`."""
    return known_defect(
        id=entry_id,
        check="fastener.thread_match",
        component_ids=["cmp:0001", "cmp:0002"],
        references=list(joints),
    )


def test_thread_match_entries_on_different_screws_between_the_same_parts_do_not_overlap() -> None:
    """US1-15: they load, since no one finding names both joints."""
    first, second, third = FOUR_SCREWS[:3]

    assert_overlap(thread_match("D-1", first), thread_match("D-2", second), False)
    assert_overlap(thread_match("D-1", first, second), thread_match("D-2", third), False)


def test_two_entries_covering_one_joint_overlap() -> None:
    """US1-15: one finding on the shared joint would match both, so the key refuses the pair."""
    first, second = FOUR_SCREWS[:2]

    assert_overlap(thread_match("D-1", first), thread_match("D-2", first), True)
    assert_overlap(thread_match("D-1", first, second), thread_match("D-2", second), True)


def test_a_fit_defect_and_a_fit_condition_on_one_sheet_overlap_only_on_one_pair() -> None:
    """Different dimension pairs on one sheet do not overlap; the same pair named either way
    round does, since a fit's roles are not compared."""

    def fit(entry: Callable[..., Entry], bore: dict[str, str], shaft: dict[str, str]) -> Entry:
        return entry(
            check="fit.size_only",
            component_ids=[],
            document_ids=[SHEET_DIMENSION["document_id"]],
            references=[{"bore": bore, "shaft": shaft}],
        )

    planted = fit(known_defect, SHEET_DIMENSION, OTHER_DIMENSION)

    assert_overlap(planted, fit(correct_condition, SHEET_DIMENSION, THIRD_DIMENSION), False)
    assert_overlap(planted, fit(correct_condition, OTHER_DIMENSION, SHEET_DIMENSION), True)
