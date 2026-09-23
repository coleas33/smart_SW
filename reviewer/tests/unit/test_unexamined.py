"""The lightweight warning's one sentence (`report/unexamined.py`).

On 2026-09-19 the pilot workstation reviewed an assembly whose two dowel pins were
lightweight and nothing on the headline said so (`docs/feature-request-resolve-lightweight.md`).
These tests pin the sentence every surface prints: which instances, called what, in which
state, in package order, and nothing at all when every instance was read.
"""

from __future__ import annotations

from swreview.ir.models import ComponentInstance
from swreview.report.unexamined import (
    CANNOT_SEE,
    NotExamined,
    not_examined,
    unexamined_instances,
)
from tests.support.packages import IDENTITY_TRANSFORM, build_package, persist_ref


def instance(number: int, name: str, suppression: str) -> ComponentInstance:
    return ComponentInstance(
        id=f"cmp:{number:04d}",
        persist_ref=persist_ref(f"cmp:{number:04d}"),
        persist_ref_scope="doc:1",
        name=name,
        full_path=name,
        document_id="doc:2",
        parent_id=None,
        referenced_configuration="Default",
        transform=IDENTITY_TRANSFORM,
        suppression=suppression,
        is_fixed=False,
        pattern_id=None,
        is_toolbox=False,
    )


def test_a_package_whose_every_instance_was_read_has_nothing_to_warn_about() -> None:
    package = build_package()

    assert all(row.suppression == "resolved" for row in package.components)
    assert unexamined_instances(package) == []
    assert not_examined(package) is None


def test_two_lightweight_pins_are_named_in_package_order_with_their_state() -> None:
    package = build_package(
        components=[
            instance(1, "housing-1", "resolved"),
            instance(2, "DOWEL PIN-1", "lightweight"),
            instance(3, "bracket-1", "resolved"),
            instance(4, "DOWEL PIN-2", "lightweight"),
        ]
    )

    block = not_examined(package)

    assert isinstance(block, NotExamined)
    assert [row.id for row in block.instances] == ["cmp:0002", "cmp:0004"]
    assert [row.state for row in block.instances] == ["lightweight", "lightweight"]
    assert block.sentence == (
        "2 of 4 component instances were not read: DOWEL PIN-1 cmp:0002 (lightweight), "
        "DOWEL PIN-2 cmp:0004 (lightweight). " + CANNOT_SEE
    )


def test_one_instance_reads_in_the_singular() -> None:
    package = build_package(
        components=[instance(1, "housing-1", "resolved"), instance(2, "cover-1", "suppressed")]
    )

    block = not_examined(package)

    assert block is not None
    assert block.sentence.startswith(
        "1 of 2 component instances was not read: cover-1 cmp:0002 (suppressed)."
    )


def test_every_state_but_resolved_counts_and_is_named_as_recorded() -> None:
    package = build_package(
        components=[
            instance(1, "a", "lightweight"),
            instance(2, "b", "suppressed"),
            instance(3, "c", "unloaded"),
            instance(4, "d", "resolved"),
        ]
    )

    block = not_examined(package)

    assert block is not None
    assert [row.state for row in block.instances] == ["lightweight", "suppressed", "unloaded"]
    assert block.sentence.startswith("3 of 4 component instances were not read: ")


def test_the_sentence_names_the_families_that_lose_their_evidence() -> None:
    assert CANNOT_SEE == "Interference, fit and the feature-tree rules cannot see them."


def test_the_report_summary_names_what_was_not_read_when_it_has_the_package() -> None:
    from swreview.report.markdown import render_report
    from tests.unit.test_report import build_session

    session = build_session()
    package = build_package(
        components=[instance(1, "housing-1", "resolved"), instance(2, "DOWEL PIN-1", "lightweight")]
    )

    with_package = render_report(session, package=package)
    without_package = render_report(session)
    all_read = render_report(session, package=build_package())

    summary = with_package.split("## Summary", 1)[1].split("\n## ", 1)[0]
    assert "- Not examined: 1 of 2 component instances was not read: " in summary
    assert "DOWEL PIN-1 cmp:0002 (lightweight)." in summary
    assert "Not examined" not in without_package
    assert "Not examined" not in all_read


def test_the_block_round_trips_as_json() -> None:
    package = build_package(components=[instance(1, "a", "resolved"), instance(2, "b", "unloaded")])
    block = not_examined(package)
    assert block is not None

    again = NotExamined.model_validate_json(block.model_dump_json())

    assert again == block
    assert again.model_dump() == {
        "sentence": block.sentence,
        "headline": block.headline,
        "instances": [{"id": "cmp:0002", "name": "b", "state": "unloaded"}],
    }


# --- the headline: names only, for the Review tab (feature 009 T012, research R2.8) ----------


def test_the_headline_names_the_instances_without_their_ids_grouped_by_state() -> None:
    package = build_package(
        components=[
            instance(1, "housing-1", "resolved"),
            instance(2, "Pin-A-1", "lightweight"),
            instance(3, "bracket-1", "resolved"),
            instance(4, "Pin-B-1", "lightweight"),
        ]
    )

    block = not_examined(package)

    assert block is not None
    assert block.headline == (
        "2 of 4 parts were not loaded: Pin-A-1 and Pin-B-1 (lightweight). " + CANNOT_SEE
    )
    assert "cmp:" not in block.headline


def test_one_instance_heads_in_the_singular() -> None:
    package = build_package(
        components=[instance(1, "housing-1", "resolved"), instance(2, "cover-1", "suppressed")]
    )

    block = not_examined(package)

    assert block is not None
    assert block.headline == "1 of 2 parts was not loaded: cover-1 (suppressed). " + CANNOT_SEE


def test_several_states_are_grouped_in_the_order_they_first_appear() -> None:
    package = build_package(
        components=[
            instance(1, "Pin-A-1", "lightweight"),
            instance(2, "Plate-1", "suppressed"),
            instance(3, "Pin-B-1", "lightweight"),
            instance(4, "Cap-1", "unloaded"),
            instance(5, "Base-1", "resolved"),
        ]
    )

    block = not_examined(package)

    assert block is not None
    assert block.headline == (
        "4 of 5 parts were not loaded: Pin-A-1 and Pin-B-1 (lightweight), Plate-1 "
        "(suppressed), Cap-1 (unloaded). " + CANNOT_SEE
    )


def test_three_names_in_one_state_are_listed_with_a_final_and() -> None:
    package = build_package(
        components=[
            instance(1, "a-1", "lightweight"),
            instance(2, "b-1", "lightweight"),
            instance(3, "c-1", "lightweight"),
            instance(4, "d-1", "resolved"),
        ]
    )

    block = not_examined(package)

    assert block is not None
    assert block.headline.startswith(
        "3 of 4 parts were not loaded: a-1, b-1 and c-1 (lightweight)."
    )


def test_the_headline_leaves_the_sentence_and_the_instances_as_they_were() -> None:
    package = build_package(
        components=[instance(1, "housing-1", "resolved"), instance(2, "DOWEL PIN-1", "lightweight")]
    )

    block = not_examined(package)

    assert block is not None
    assert block.sentence == (
        "1 of 2 component instances was not read: DOWEL PIN-1 cmp:0002 (lightweight). " + CANNOT_SEE
    )
    assert [(row.id, row.name, row.state) for row in block.instances] == [
        ("cmp:0002", "DOWEL PIN-1", "lightweight")
    ]
