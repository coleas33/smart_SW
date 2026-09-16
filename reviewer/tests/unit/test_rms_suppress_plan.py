"""Unit tests for the suppress-test plan and `swreview rms suppress-plan` (T052).

The plan is the contract between the reviewer and the extractor: the C# `suppress-test`
command decides nothing about folders, groups or content features, it suppresses exactly
the features this file names, in this order (`contracts/cli.md`). So the two things these
tests pin are the two the extractor cannot re-derive:

- **what is in the plan** - the Detail *content* features of one document, in tree order,
  with the persistent reference the extractor resolves them by. Folders, end-tag markers
  and every other group are out, and both traversal shapes of `contracts/rules.md`
  ("Group assignment") produce the same plan, because the plan comes from `assign_groups`
  and `RmsTypeTable` rather than from names and depths;
- **when there is no plan** - a document whose tree was never dumped, and a document with
  no Detail group, are errors with a message, not empty plans. An empty plan file would
  read to the extractor like "nothing to test" and to the rule like a clean part.

The rms-part golden fixture is the end-to-end case: its `frame` part (`doc:2`) is the
compliant tree, so the plan over it is exactly the three Detail features the generator
put there.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from swreview.checks.rms.plan import PLAN_FILE_NAME, SuppressPlan, build_plan
from swreview.checks.rms_types import RmsTypeTable, load_table
from swreview.ir.loader import save_package
from swreview.ir.models import EvidencePackage
from tests.support.features import (
    AssemblySpec,
    PartSpec,
    feature,
    folder,
    rms_package,
    sketch_feature,
)
from tests.unit.test_cli import invoke, payload

RMS_PART_FIXTURE = Path(__file__).resolve().parents[1] / "golden" / "fixtures" / "rms-part"

FRAME = "doc:2"
"""The compliant part of the rms-part fixture; its Detail group holds three features."""

ASSEMBLY = "doc:1"
"""The fixture's assembly document: no `features[]` rows at all."""


@pytest.fixture
def table() -> RmsTypeTable:
    return load_table()


def detail_part(**kwargs: Any) -> PartSpec:
    """One part whose Detail group holds a sketch, a cut and a hole, plus other groups."""
    return PartSpec(
        document_id="doc:2",
        name="frame",
        features=(
            folder("1-Ref", feature("Axis1", "RefAxis")),
            folder(
                "3-Core",
                sketch_feature("Sketch2", consumers=("Boss-Extrude1",)),
                feature("Boss-Extrude1", "Extrusion", parent_names=("Sketch2",)),
            ),
            folder(
                "4-Detail",
                sketch_feature("Sketch3", consumers=("Cut-Extrude1",)),
                feature("Cut-Extrude1", "Cut", parent_names=("Sketch3",)),
                feature("Hole1", "HoleWzd"),
            ),
            folder("6-Quarantine", feature("Chamfer1", "Chamfer")),
        ),
        **kwargs,
    )


def one_part(part: PartSpec) -> EvidencePackage:
    """`part` under the rms-part assembly, so the review configuration is the design's."""
    return rms_package(parts=[part], assembly=AssemblySpec(document_id="doc:1", name="assy"))


def names(plan: SuppressPlan) -> list[str]:
    return [planned.name for planned in plan.features]


# --- 1. the builder ---------------------------------------------------------------


def test_plan_names_the_document_the_review_configuration_and_the_detail_group(
    table: RmsTypeTable,
) -> None:
    package = one_part(detail_part())

    plan = build_plan(package, "doc:2", table)

    assert plan.document_id == "doc:2"
    assert plan.configuration == package.design.active_configuration
    assert plan.group == "4-Detail"


def test_plan_carries_the_detail_content_features_in_tree_order(
    table: RmsTypeTable,
) -> None:
    """Tree order, not id order: the extractor suppresses them in the order it is given."""
    package = one_part(detail_part())

    plan = build_plan(package, "doc:2", table)

    assert names(plan) == ["Sketch3", "Cut-Extrude1", "Hole1"]


def test_each_planned_feature_carries_its_persistent_reference_name_and_type(
    table: RmsTypeTable,
) -> None:
    """The five fields of `data-model.md` section 2, copied from the row and not invented."""
    package = one_part(detail_part())
    rows = {row.name: row for row in package.features}

    plan = build_plan(package, "doc:2", table)

    assert [
        (item.feature_id, item.persist_ref, item.persist_ref_scope, item.name, item.type_name)
        for item in plan.features
    ] == [
        (
            rows[name].id,
            rows[name].persist_ref,
            rows[name].persist_ref_scope,
            name,
            rows[name].type_name,
        )
        for name in ("Sketch3", "Cut-Extrude1", "Hole1")
    ]


def test_plan_excludes_folders_end_tags_and_every_other_group(table: RmsTypeTable) -> None:
    package = one_part(detail_part())

    planned = set(names(build_plan(package, "doc:2", table)))

    assert planned.isdisjoint({"1-Ref", "3-Core", "4-Detail", "6-Quarantine"})
    assert planned.isdisjoint({"Axis1", "Sketch2", "Boss-Extrude1", "Chamfer1"})


def test_the_flat_traversal_shape_plans_the_same_features(table: RmsTypeTable) -> None:
    """The plan comes from the group assigner, so end-tag markers change nothing."""
    nested = build_plan(one_part(detail_part(shape="nested")), "doc:2", table)
    flat = build_plan(one_part(detail_part(shape="flat")), "doc:2", table)

    assert names(flat) == names(nested)
    assert all(not item.name.endswith("___EndTag___") for item in flat.features)


def test_groups_are_sticky_so_a_feature_after_the_detail_folder_is_planned(
    table: RmsTypeTable,
) -> None:
    """`rules.md` ("Group assignment"): a group folder opens a group, it does not close it."""
    package = one_part(
        PartSpec(
            document_id="doc:2",
            name="frame",
            features=(
                folder("4-Detail", feature("Hole1", "HoleWzd")),
                feature("Cut-Extrude1", "Cut"),
            ),
        )
    )

    assert names(build_plan(package, "doc:2", table)) == ["Hole1", "Cut-Extrude1"]


def test_plan_ignores_the_features_of_other_documents(table: RmsTypeTable) -> None:
    package = rms_package(
        parts=[
            detail_part(),
            PartSpec(
                document_id="doc:3",
                name="bracket",
                features=(folder("4-Detail", feature("Hole9", "HoleWzd")),),
            ),
        ],
        assembly=AssemblySpec(document_id="doc:1", name="assy"),
    )

    assert "Hole9" not in names(build_plan(package, "doc:2", table))


def test_the_detail_group_name_comes_from_the_table(table: RmsTypeTable) -> None:
    """`rms_types.yaml` may be recalibrated to other spellings; nothing here hard-codes one."""
    recalibrated = replace(
        table, groups=("1-Ref", "2-Construction", "3-Core", "Detalj", "5-Modify", "6-Quarantine")
    )
    package = one_part(
        PartSpec(
            document_id="doc:2",
            name="frame",
            features=(folder("Detalj", feature("Hole1", "HoleWzd")),),
        )
    )

    plan = build_plan(package, "doc:2", recalibrated)

    assert plan.group == "Detalj"
    assert names(plan) == ["Hole1"]


def test_an_empty_detail_group_plans_no_features_rather_than_failing(
    table: RmsTypeTable,
) -> None:
    """The group exists and holds nothing: an honest empty plan, not an error."""
    package = one_part(
        PartSpec(document_id="doc:2", name="frame", features=(folder("4-Detail"),))
    )

    plan = build_plan(package, "doc:2", table)

    assert plan.group == "4-Detail"
    assert plan.features == ()


def test_a_document_with_no_feature_rows_is_an_error_naming_the_ones_that_have_them(
    table: RmsTypeTable,
) -> None:
    package = one_part(detail_part())

    with pytest.raises(ValueError, match="doc:1") as caught:
        build_plan(package, "doc:1", table)

    assert "doc:2" in str(caught.value)


def test_a_document_the_package_does_not_carry_is_the_same_error(
    table: RmsTypeTable,
) -> None:
    package = one_part(detail_part())

    with pytest.raises(ValueError, match="doc:99"):
        build_plan(package, "doc:99", table)


def test_a_document_with_no_detail_group_is_an_error_naming_the_group(
    table: RmsTypeTable,
) -> None:
    package = one_part(
        PartSpec(
            document_id="doc:2",
            name="frame",
            features=(folder("3-Core", feature("Boss-Extrude1", "Extrusion")),),
        )
    )

    with pytest.raises(ValueError, match="4-Detail") as caught:
        build_plan(package, "doc:2", table)

    assert "doc:2" in str(caught.value)


# --- 2. the command ---------------------------------------------------------------


@pytest.fixture
def package_dir(tmp_path: Path) -> Path:
    """The rms-part golden package, copied so a test can never edit the fixture."""
    directory = tmp_path / "package"
    shutil.copytree(RMS_PART_FIXTURE, directory)
    return directory


@pytest.fixture
def plain_dir(tmp_path: Path) -> Path:
    """A package built here, so a test can shape the tree it plans over."""
    directory = tmp_path / "plain"
    save_package(one_part(detail_part()), directory)
    return directory


def test_suppress_plan_writes_the_plan_beside_the_package_by_default(
    package_dir: Path,
) -> None:
    result = invoke(
        "rms", "suppress-plan", "--package", str(package_dir), "--document", FRAME
    )
    written = json.loads((package_dir / PLAN_FILE_NAME).read_text(encoding="utf-8"))

    assert result.exit_code == 0
    assert written["document_id"] == FRAME
    assert written["configuration"] == "Default"
    assert written["group"] == "4-Detail"
    assert [item["name"] for item in written["features"]] == [
        "Sketch3",
        "Cut-Extrude1",
        "Hole1",
    ]


def test_the_written_plan_carries_the_five_fields_the_extractor_resolves_features_by(
    package_dir: Path,
) -> None:
    invoke("rms", "suppress-plan", "--package", str(package_dir), "--document", FRAME)
    written = json.loads((package_dir / PLAN_FILE_NAME).read_text(encoding="utf-8"))
    rows = {
        row["name"]: row
        for row in json.loads((package_dir / "package.json").read_text(encoding="utf-8"))[
            "features"
        ]
        if row["document_id"] == FRAME
    }

    for item in written["features"]:
        row = rows[item["name"]]
        assert item == {
            "feature_id": row["id"],
            "persist_ref": row["persist_ref"],
            "persist_ref_scope": row["persist_ref_scope"],
            "name": row["name"],
            "type_name": row["type_name"],
        }


def test_suppress_plan_json_reports_the_plan_and_where_it_was_written(
    package_dir: Path, tmp_path: Path
) -> None:
    out = tmp_path / "plans" / "frame.json"

    body = payload(
        invoke(
            "rms",
            "suppress-plan",
            "--package",
            str(package_dir),
            "--document",
            FRAME,
            "--out",
            str(out),
            "--json",
        )
    )

    assert body["package"] == str(package_dir.resolve())
    assert body["out"] == str(out.resolve())
    assert body["document_id"] == FRAME
    assert body["group"] == "4-Detail"
    assert len(body["features"]) == 3
    assert json.loads(out.read_text(encoding="utf-8")) == {
        key: body[key] for key in ("document_id", "configuration", "group", "features")
    }
    assert not (package_dir / PLAN_FILE_NAME).exists()


def test_suppress_plan_human_output_names_the_file_the_group_and_the_features(
    package_dir: Path,
) -> None:
    result = invoke(
        "rms", "suppress-plan", "--package", str(package_dir), "--document", FRAME
    )

    assert result.exit_code == 0
    assert str(package_dir / PLAN_FILE_NAME) in result.stdout
    assert "4-Detail" in result.stdout
    for name in ("Sketch3", "Cut-Extrude1", "Hole1"):
        assert name in result.stdout


def test_suppress_plan_leaves_the_package_byte_for_byte(package_dir: Path) -> None:
    before = (package_dir / "package.json").read_bytes()

    invoke("rms", "suppress-plan", "--package", str(package_dir), "--document", FRAME)

    assert (package_dir / "package.json").read_bytes() == before


def test_a_document_with_no_rows_exits_1_with_a_message_and_writes_nothing(
    package_dir: Path,
) -> None:
    result = invoke(
        "rms", "suppress-plan", "--package", str(package_dir), "--document", ASSEMBLY
    )

    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr.startswith("error: ")
    assert ASSEMBLY in result.stderr
    assert "Traceback" not in result.stderr
    assert not (package_dir / PLAN_FILE_NAME).exists()


def test_a_document_with_no_detail_group_exits_1_with_a_message(tmp_path: Path) -> None:
    directory = tmp_path / "no-detail"
    save_package(
        one_part(
            PartSpec(
                document_id="doc:2",
                name="frame",
                features=(folder("3-Core", feature("Boss-Extrude1", "Extrusion")),),
            )
        ),
        directory,
    )

    result = invoke("rms", "suppress-plan", "--package", str(directory), "--document", "doc:2")

    assert result.exit_code == 1
    assert "4-Detail" in result.stderr
    assert not (directory / PLAN_FILE_NAME).exists()


def test_an_unreadable_package_exits_1(tmp_path: Path) -> None:
    result = invoke(
        "rms", "suppress-plan", "--package", str(tmp_path / "nowhere"), "--document", FRAME
    )

    assert result.exit_code == 1
    assert result.stderr.startswith("error: ")
    assert "Traceback" not in result.stderr


def test_an_out_path_that_is_a_directory_exits_1_without_a_traceback(
    package_dir: Path, tmp_path: Path
) -> None:
    """A write that cannot happen is input the command can describe, not a crash.

    `--out` naming an existing directory is the ordinary typo (`--out <folder>` instead
    of `--out <folder>/plan.json`), and every other error path of this command answers it
    with one `error:` line. The write is the only step that can fail after the plan is
    built, so it belongs inside the same guard.
    """
    out = tmp_path / "existing-directory"
    out.mkdir()

    result = invoke(
        "rms",
        "suppress-plan",
        "--package",
        str(package_dir),
        "--document",
        FRAME,
        "--out",
        str(out),
    )

    assert result.exit_code == 1
    assert result.stderr.startswith("error: ")
    assert str(out) in result.stderr
    assert "Traceback" not in result.stderr
    assert not isinstance(result.exception, OSError)


def test_suppress_plan_without_a_document_is_a_usage_error(plain_dir: Path) -> None:
    assert invoke("rms", "suppress-plan", "--package", str(plain_dir)).exit_code == 2


def test_suppress_plan_without_a_package_is_a_usage_error() -> None:
    assert invoke("rms", "suppress-plan", "--document", FRAME).exit_code == 2
