"""Unit tests for the grouped static interference check (T062).

These pin the four things US3 asks of the interference report and that nothing else in
the reviewer enforces: a repeated pattern condition is one finding with its member list
(FR-011); a truncated or failed pair is `unresolved` coverage so the run can never read
as a pass (FR-019); the overlap volume is reported in the unit the extractor verified,
with the millimetre-cubed value the threshold used alongside it (FR-018); and a
mechanism checked at positions says so in as many words (FR-020, constitution
Principle VI).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from swreview.checks.interference import (
    CHECK,
    check_interference_group,
    group_interferences,
    mechanism_positions_coverage,
    run_coverage,
)
from swreview.exceptions import ExceptionStore, fingerprint
from swreview.ir.loader import load_package
from swreview.ir.models import (
    ComponentInstance,
    EvidencePackage,
    Interference,
    InterferenceSettings,
    Volume,
)
from tests.support.packages import IDENTITY_TRANSFORM, build_package, persist_ref

FIXTURE_DIR = (
    Path(__file__).resolve().parents[1] / "golden" / "fixtures" / "bracket-assy-interference"
)

SETTINGS = InterferenceSettings(
    treat_coincident_as_interference=False,
    treat_subassemblies_as_components=True,
    include_multibody=False,
    ignore_hidden=True,
    fastener_folder_treatment="include",
)


def component(component_id: str, *, pattern_id: str | None = None) -> ComponentInstance:
    return ComponentInstance(
        id=component_id,
        persist_ref=persist_ref(component_id),
        persist_ref_scope="doc:1",
        name=component_id.replace("cmp:", "part-"),
        full_path=component_id.replace("cmp:", "part-") + "-1",
        document_id="doc:2",
        parent_id=None,
        referenced_configuration="Default",
        transform=IDENTITY_TRANSFORM,
        suppression="resolved",
        is_fixed=False,
        pattern_id=pattern_id,
        is_toolbox=False,
    )


def interference(
    interference_id: str,
    first: str,
    second: str,
    *,
    group_key: str = "",
    volume: Volume | None = None,
    status: str = "computed",
    error: str | None = None,
    is_fastener: bool = False,
    is_possible: bool = False,
    configuration: str = "Default",
) -> Interference:
    return Interference(
        id=interference_id,
        configuration=configuration,
        component_ids=[first, second],
        volume=volume,
        settings=SETTINGS,
        status=status,
        error=error,
        group_key=group_key,
        is_fastener=is_fastener,
        is_possible=is_possible,
    )


def package_with(
    interferences: list[Interference], components: list[ComponentInstance] | None = None
) -> EvidencePackage:
    ids = sorted({cid for item in interferences for cid in item.component_ids})
    return build_package(
        components=components if components is not None else [component(cid) for cid in ids],
        interferences=interferences,
    )


def mm3(value: float) -> Volume:
    return Volume(value=value, unit="mm3")


# --- grouping -------------------------------------------------------------------


def test_pattern_instances_collapse_into_one_group() -> None:
    members = [
        interference(f"int:{index}", "cmp:0001", f"cmp:001{index}", group_key="pat:A|pat:B")
        for index in range(1, 7)
    ]

    groups = group_interferences(package_with(members))

    assert len(groups) == 1
    assert groups[0].group_key == "pat:A|pat:B"
    assert len(groups[0].interferences) == 6


def test_a_group_lists_every_member_component() -> None:
    members = [
        interference("int:1", "cmp:0001", "cmp:0011", group_key="pat:A|pat:B"),
        interference("int:2", "cmp:0001", "cmp:0012", group_key="pat:A|pat:B"),
    ]

    group = group_interferences(package_with(members))[0]

    assert group.component_ids == ["cmp:0001", "cmp:0011", "cmp:0012"]


def test_pairs_without_a_group_key_fall_back_to_the_sorted_pattern_pair() -> None:
    components = [
        component("cmp:0001"),
        component("cmp:0011", pattern_id="pat:screws"),
        component("cmp:0012", pattern_id="pat:screws"),
    ]
    members = [
        interference("int:1", "cmp:0011", "cmp:0001"),
        interference("int:2", "cmp:0001", "cmp:0012"),
    ]

    groups = group_interferences(package_with(members, components))

    assert len(groups) == 1
    assert groups[0].group_key == "cmp:0001|pat:screws"


def test_the_fallback_uses_component_ids_when_there_is_no_pattern() -> None:
    members = [
        interference("int:1", "cmp:0002", "cmp:0001"),
        interference("int:2", "cmp:0001", "cmp:0003"),
    ]

    keys = [group.group_key for group in group_interferences(package_with(members))]

    assert keys == ["cmp:0001|cmp:0002", "cmp:0001|cmp:0003"]


def test_the_same_pair_in_two_configurations_is_two_groups() -> None:
    members = [
        interference("int:1", "cmp:0001", "cmp:0002", group_key="pat:A|pat:B"),
        interference(
            "int:2", "cmp:0001", "cmp:0002", group_key="pat:A|pat:B", configuration="Cold"
        ),
    ]

    groups = group_interferences(package_with(members))

    assert [group.configuration for group in groups] == ["Default", "Cold"]


def test_a_group_takes_the_worst_status_of_its_members() -> None:
    members = [
        interference("int:1", "cmp:0001", "cmp:0002", group_key="g", volume=mm3(1.0)),
        interference("int:2", "cmp:0001", "cmp:0003", group_key="g", status="truncated"),
    ]

    assert group_interferences(package_with(members))[0].status == "truncated"


def test_a_failed_member_outranks_a_truncated_one() -> None:
    members = [
        interference("int:1", "cmp:0001", "cmp:0002", group_key="g", status="truncated"),
        interference(
            "int:2", "cmp:0001", "cmp:0003", group_key="g", status="failed", error="COM error"
        ),
    ]

    assert group_interferences(package_with(members))[0].status == "failed"


# --- truncated and failed pairs -------------------------------------------------


def test_a_truncated_group_is_unresolved_and_names_the_pairs() -> None:
    members = [interference("int:1", "cmp:0001", "cmp:0002", status="truncated")]
    package = package_with(members)

    result = check_interference_group(group_interferences(package)[0], package)

    assert result.check == CHECK
    assert result.status == "unresolved"
    assert "cmp:0001" in result.observed
    assert "cmp:0002" in result.observed
    assert result.coverage_limits


def test_a_failed_group_keeps_the_extractor_error_in_the_coverage() -> None:
    members = [
        interference("int:1", "cmp:0001", "cmp:0002", status="failed", error="COM timeout")
    ]
    package = package_with(members)

    coverage = run_coverage(package)

    assert [item.error for item in coverage] == ["COM timeout"]
    assert coverage[0].scope.pairs == [["cmp:0001", "cmp:0002"]]
    assert coverage[0].scope.configuration == "Default"


def test_run_coverage_lists_every_truncated_or_failed_interference() -> None:
    members = [
        interference("int:1", "cmp:0001", "cmp:0002", volume=mm3(5.0)),
        interference("int:2", "cmp:0001", "cmp:0003", status="truncated"),
        interference("int:3", "cmp:0001", "cmp:0004", status="failed", error="boom"),
    ]

    coverage = run_coverage(package_with(members))

    assert len(coverage) == 2
    assert {item.check for item in coverage} == {CHECK}


def test_run_coverage_is_empty_when_every_pair_computed() -> None:
    members = [interference("int:1", "cmp:0001", "cmp:0002", volume=mm3(5.0))]

    assert run_coverage(package_with(members)) == []


def test_no_group_reads_as_a_pass_while_a_pair_is_unresolved() -> None:
    members = [
        interference("int:1", "cmp:0001", "cmp:0002", volume=mm3(5.0)),
        interference("int:2", "cmp:0003", "cmp:0004", status="truncated"),
    ]
    package = package_with(members)

    results = [
        check_interference_group(group, package) for group in group_interferences(package)
    ]

    assert all(result.status != "checked_within_scope" for result in results)
    assert any(result.status == "unresolved" for result in results)
    assert run_coverage(package)


# --- volumes --------------------------------------------------------------------


def test_the_volume_is_reported_in_the_unit_it_was_stored_in() -> None:
    members = [
        interference("int:1", "cmp:0001", "cmp:0002", volume=Volume(value=0.002, unit="in3"))
    ]
    package = package_with(members)

    result = check_interference_group(group_interferences(package)[0], package)

    assert result.calculation is not None
    assert result.calculation.inputs["int:1_volume_as_reported"] == "0.002 in3"
    assert result.calculation.inputs["int:1_volume_mm3"] == "32.774128 mm3"
    assert "0.002 in3" in result.observed


def test_a_cubic_metre_volume_converts_for_the_threshold() -> None:
    members = [
        interference("int:1", "cmp:0001", "cmp:0002", volume=Volume(value=2e-9, unit="m3"))
    ]
    package = package_with(members)

    result = check_interference_group(group_interferences(package)[0], package)

    assert result.calculation is not None
    assert result.calculation.result["max_volume_mm3"] == pytest.approx(2.0)
    assert result.severity == "high"


def test_an_overlap_at_or_below_one_cubic_millimetre_is_medium() -> None:
    members = [interference("int:1", "cmp:0001", "cmp:0002", volume=mm3(1.0))]
    package = package_with(members)

    result = check_interference_group(group_interferences(package)[0], package)

    assert result.status == "demonstrated"
    assert result.severity == "medium"


def test_a_measured_overlap_is_demonstrated() -> None:
    members = [interference("int:1", "cmp:0001", "cmp:0002", volume=mm3(12.5))]
    package = package_with(members)

    result = check_interference_group(group_interferences(package)[0], package)

    assert result.status == "demonstrated"
    assert result.severity == "high"
    assert result.calculation is not None
    assert result.calculation.units_out == "mm3"


def test_a_possible_interference_without_a_volume_is_suspected() -> None:
    members = [interference("int:1", "cmp:0001", "cmp:0002", is_possible=True)]
    package = package_with(members)

    result = check_interference_group(group_interferences(package)[0], package)

    assert result.status == "suspected"
    assert "coincident" in result.observed


def test_a_fastener_pair_is_named_in_the_observed_condition() -> None:
    members = [
        interference("int:1", "cmp:0001", "cmp:0002", volume=mm3(3.0), is_fastener=True)
    ]
    package = package_with(members)

    result = check_interference_group(group_interferences(package)[0], package)

    assert "fastener" in result.observed.lower()


def test_the_detection_settings_are_recorded_with_the_calculation() -> None:
    members = [interference("int:1", "cmp:0001", "cmp:0002", volume=mm3(3.0))]
    package = package_with(members)

    result = check_interference_group(group_interferences(package)[0], package)

    assert result.calculation is not None
    assert result.calculation.inputs["treat_coincident_as_interference"] == "False"
    assert result.calculation.inputs["fastener_folder_treatment"] == "include"


# --- exceptions -----------------------------------------------------------------


def accepted_store(package: EvidencePackage, tmp_path: Path, status: str) -> ExceptionStore:
    store = ExceptionStore(tmp_path / "exceptions.json")
    group = group_interferences(package)[0]
    accepted = store.accept(group, package, by="cole", note="press fit, intended")
    if status != "active":
        accepted.status = status  # type: ignore[assignment]
    return store


def test_an_active_exception_makes_the_group_checked_within_scope(tmp_path: Path) -> None:
    members = [interference("int:1", "cmp:0001", "cmp:0002", volume=mm3(3.0))]
    package = package_with(members)
    store = accepted_store(package, tmp_path, "active")

    result = check_interference_group(group_interferences(package)[0], package, store)

    assert result.status == "checked_within_scope"
    assert "excepted" in result.observed
    assert "exception:EX-001" in result.coverage_limits


def test_a_needs_review_exception_makes_the_group_suspected(tmp_path: Path) -> None:
    members = [interference("int:1", "cmp:0001", "cmp:0002", volume=mm3(3.0))]
    package = package_with(members)
    store = accepted_store(package, tmp_path, "needs_review")

    result = check_interference_group(group_interferences(package)[0], package, store)

    assert result.status == "suspected"
    assert "exception_needs_review:EX-001" in result.coverage_limits


def test_an_exception_never_clears_a_truncated_pair(tmp_path: Path) -> None:
    members = [interference("int:1", "cmp:0001", "cmp:0002", status="truncated")]
    package = package_with(members)
    store = accepted_store(package, tmp_path, "active")

    result = check_interference_group(group_interferences(package)[0], package, store)

    assert result.status == "unresolved"


# --- mechanism coverage ---------------------------------------------------------


def test_mechanism_positions_produce_the_required_statement() -> None:
    item = mechanism_positions_coverage(["fully open", "fully closed"])

    assert item.check == CHECK
    assert item.scope.positions == ["fully open", "fully closed"]
    assert item.reason == (
        "positions checked: fully open, fully closed; clearance across the full "
        "motion path was not established"
    )
    assert item.error is None


def test_mechanism_coverage_refuses_an_empty_position_list() -> None:
    with pytest.raises(ValueError, match="at least one position"):
        mechanism_positions_coverage([])


# --- the golden fixture keeps one copy of its exception -------------------------


def test_the_fixture_case_kwargs_match_its_exceptions_file() -> None:
    case: dict[str, Any] = json.loads((FIXTURE_DIR / "case.json").read_text(encoding="utf-8"))
    stored = json.loads((FIXTURE_DIR / "exceptions.json").read_text(encoding="utf-8"))

    assert case["kwargs"]["exceptions"] == stored["exceptions"]


def test_the_fixture_exception_fingerprint_still_matches_its_package() -> None:
    package = load_package(FIXTURE_DIR).package
    store = ExceptionStore(FIXTURE_DIR / "exceptions.json").load()
    stored_exception = store.exceptions[0]
    component_ids = [
        item.id
        for item in package.components
        if item.persist_ref in stored_exception.component_persist_refs
    ]

    assert fingerprint(package, component_ids) == stored_exception.geometry_fingerprint
