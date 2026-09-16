"""Unit tests for `swreview remodel plan` (T028).

The dry run is Phase 0's deliverable and runs **before any C# write code exists**
(`plan.md` point 10): it prints, per part, how many features reach their target group, how
many are pinned and by which dependency edge, which groups come out non-contiguous and
what splits them, and the rebuild list with a reason each. Those five numbers are what the
owner decides on, so each of them is asserted here rather than left to the human line.

Three properties beyond the numbers:

- **the fraction is a measurement, not a grade.** It is printed with its numerator, its
  denominator and the sentence that says what it counts, and it is `null` - never `0.0`
  and never `1.0` - when there is nothing to count. A bare 0.82 with no denominator is
  exactly the confident-but-unsupported artifact Principle I exists to prevent;
- **a refusal exits 1 and names every reason.** A part the scope gate refuses, a part
  already carrying a group-named folder with the wrong members, and a part whose dependency
  graph has a cycle all stop the dry run, and the message names each reason rather than the
  first one;
- **nothing is written and no provider is constructed.** The command reads a package and
  prints. The package directory is hashed before and after, and both provider factories are
  monkeypatched to raise, so a command that quietly built an adapter would fail here rather
  than on the workstation.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from swreview.agent import providers
from swreview.checks.rms_types import load_table
from swreview.ir.loader import save_package
from swreview.remodel.feasibility import REBUILD_REASONS
from tests.support.features import PartSpec, folder, rms_package
from tests.support.remodel import (
    MODEL_CHECK_PROFILE,
    dependency_chain_features,
    mis_membered_group_folder_features,
    remodel_package,
)
from tests.unit.test_cli import invoke, payload

TABLE = load_table()
REF, CONSTRUCTION, CORE, DETAIL, MODIFY, QUARANTINE = TABLE.groups
DOCUMENT = "doc:1"


# --- fixtures ---------------------------------------------------------------------


def pinned_features() -> list[Any]:
    """A `3-Core` chamfer cut on an edge a `4-Detail` cut made.

    `dependency_chain_features` is that tree: the type table sends a chamfer to `3-Core`,
    and this one depends on `Cut-Extrude1`, which the method puts after it. So the chamfer
    is **pinned** by a named edge, and it lands inside the Detail span while the Detail
    features land inside the Core span, which is two groups neither of which can be folded.
    One tree, and all five of the dry run's numbers are non-zero on it.
    """
    return dependency_chain_features()


def written(tmp_path: Path, features: list[Any], name: str = "bracket") -> Path:
    """One package written to disk, as the command reads it."""
    directory = tmp_path / name
    save_package(remodel_package(features, name=name), directory)
    return directory


def digest(directory: Path) -> dict[str, str]:
    """Every file under `directory` with its content hash, so a write cannot hide."""
    return {
        str(path.relative_to(directory)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


@pytest.fixture
def package_dir(tmp_path: Path) -> Path:
    return written(tmp_path, pinned_features())


@pytest.fixture
def no_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every route to an adapter raises: the dry run talks to no model at all."""

    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("the dry-run planner must construct no provider")

    monkeypatch.setattr(providers, "get", refuse)
    monkeypatch.setattr("swreview.cli.provider_factory", refuse)


def part(body: dict[str, Any], document_id: str = DOCUMENT) -> dict[str, Any]:
    return next(row for row in body["parts"] if row["document_id"] == document_id)


# --- the five numbers ---------------------------------------------------------------


def test_the_command_prints_one_row_per_part_naming_the_document_it_planned(
    package_dir: Path, no_provider: None
) -> None:
    body = payload(invoke("remodel", "plan", "--package", str(package_dir), "--json"))

    assert body["package"] == str(package_dir.resolve())
    assert [row["document_id"] for row in body["parts"]] == [DOCUMENT]
    assert part(body)["file_name"].endswith(".SLDPRT")
    assert part(body)["state"] == "planned"


def test_features_reaching_their_target_group_are_counted_against_the_content_features(
    package_dir: Path, no_provider: None
) -> None:
    row = part(payload(invoke("remodel", "plan", "--package", str(package_dir), "--json")))

    assert row["content_features"] > 0
    assert 0 <= row["reaching_target_group"] <= row["content_features"]
    fraction = row["reorganizable_fraction"]
    assert fraction["reaching"] == row["reaching_target_group"]
    assert fraction["of"] == row["content_features"]
    assert fraction["value"] == pytest.approx(
        fraction["reaching"] / fraction["of"], abs=1e-9
    )
    assert "reach their target group" in fraction["measurement"]


def test_the_fraction_is_null_rather_than_a_number_when_there_is_nothing_to_count(
    tmp_path: Path, no_provider: None
) -> None:
    directory = written(tmp_path, [folder("Empty")], name="hollow")

    row = part(payload(invoke("remodel", "plan", "--package", str(directory), "--json")))

    assert row["content_features"] == 0
    assert row["reorganizable_fraction"]["value"] is None


def test_every_pin_names_the_dependency_edge_that_holds_it(
    package_dir: Path, no_provider: None
) -> None:
    row = part(payload(invoke("remodel", "plan", "--package", str(package_dir), "--json")))

    assert row["pins"], "this tree is built so that at least one feature is pinned"
    for pin in row["pins"]:
        assert pin["blocking_edge"]["parent_id"].startswith("feat:")
        assert pin["blocking_edge"]["child_id"] == pin["feature_id"]
        assert pin["desired_index"] != pin["achievable_index"]
        assert pin["reason"]


def test_every_non_contiguous_group_names_the_features_that_split_it(
    package_dir: Path, no_provider: None
) -> None:
    row = part(payload(invoke("remodel", "plan", "--package", str(package_dir), "--json")))

    assert row["non_contiguous"], "the Core chamfer and the Detail cuts split each other"
    for item in row["non_contiguous"]:
        assert item["group"] in TABLE.groups
        assert item["interloper_feature_ids"]
        assert item["reason"]


def test_the_rebuild_list_is_counted_by_reason_over_the_whole_closed_taxonomy(
    package_dir: Path, no_provider: None
) -> None:
    row = part(payload(invoke("remodel", "plan", "--package", str(package_dir), "--json")))

    assert tuple(row["rebuild_by_reason"]) == REBUILD_REASONS
    assert sum(row["rebuild_by_reason"].values()) == len(row["rebuild"])
    for entry in row["rebuild"]:
        assert entry["reason"] in REBUILD_REASONS
        assert entry["detail"]


def test_the_move_count_and_the_change_count_are_both_reported(
    package_dir: Path, no_provider: None
) -> None:
    row = part(payload(invoke("remodel", "plan", "--package", str(package_dir), "--json")))

    assert row["move_count"] >= 0
    assert row["changes"] >= row["move_count"]


def test_the_human_output_names_the_document_the_fraction_and_the_reasons(
    package_dir: Path, no_provider: None
) -> None:
    result = invoke("remodel", "plan", "--package", str(package_dir))

    assert result.exit_code == 0
    assert DOCUMENT in result.stdout
    assert "reach their target group" in result.stdout
    assert "pinned" in result.stdout


# --- document selection --------------------------------------------------------------


def test_a_named_document_is_the_only_one_planned(tmp_path: Path, no_provider: None) -> None:
    package = rms_package(
        parts=[
            PartSpec(document_id="doc:1", name="a", features=pinned_features()),
            PartSpec(document_id="doc:2", name="b", features=pinned_features()),
        ]
    )
    directory = tmp_path / "two-parts"
    save_package(
        package.model_copy(
            update={
                "extractor": package.extractor.model_copy(
                    update={"profile": MODEL_CHECK_PROFILE}
                )
            }
        ),
        directory,
    )

    every = payload(invoke("remodel", "plan", "--package", str(directory), "--json"))
    one = payload(
        invoke(
            "remodel", "plan", "--package", str(directory), "--document", "doc:2", "--json"
        )
    )

    assert [row["document_id"] for row in every["parts"]] == ["doc:1", "doc:2"]
    assert [row["document_id"] for row in one["parts"]] == ["doc:2"]


def test_a_document_the_package_does_not_carry_exits_1_naming_it(
    package_dir: Path, no_provider: None
) -> None:
    result = invoke(
        "remodel", "plan", "--package", str(package_dir), "--document", "doc:404"
    )

    assert result.exit_code == 1
    assert "doc:404" in result.stdout + getattr(result, "stderr", "")


# --- refusals --------------------------------------------------------------------------


def test_a_part_whose_group_named_folder_holds_the_wrong_members_exits_1_with_the_reason(
    tmp_path: Path, no_provider: None
) -> None:
    directory = written(tmp_path, mis_membered_group_folder_features(), name="legacy")

    result = invoke("remodel", "plan", "--package", str(directory))

    assert result.exit_code == 1
    output = result.stdout + getattr(result, "stderr", "")
    assert "rms_named_folder_wrong_members" in output


def test_a_refused_part_still_prints_its_numbers_as_json_before_exiting_1(
    tmp_path: Path, no_provider: None
) -> None:
    directory = written(tmp_path, mis_membered_group_folder_features(), name="legacy")

    result = invoke("remodel", "plan", "--package", str(directory), "--json")

    assert result.exit_code == 1
    body = json.loads(result.stdout)
    row = part(body)
    assert row["state"] == "failed"
    assert row["refusals"]
    assert row["changes"] == 0


def test_a_package_with_no_part_document_exits_1_rather_than_printing_nothing(
    tmp_path: Path, no_provider: None
) -> None:
    from tests.support.features import AssemblySpec

    directory = tmp_path / "assembly-only"
    save_package(
        rms_package(parts=[], assembly=AssemblySpec(document_id="doc:1", name="assy")),
        directory,
    )

    result = invoke("remodel", "plan", "--package", str(directory))

    assert result.exit_code == 1
    assert "part" in (result.stdout + getattr(result, "stderr", "")).lower()


# --- the command writes nothing and talks to no model ------------------------------------


def test_the_command_writes_nothing_under_the_package_directory(
    package_dir: Path, no_provider: None
) -> None:
    before = digest(package_dir)

    assert invoke("remodel", "plan", "--package", str(package_dir), "--json").exit_code == 0

    assert digest(package_dir) == before


def test_the_command_constructs_no_provider(
    package_dir: Path, no_provider: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = invoke("remodel", "plan", "--package", str(package_dir), "--json")

    assert result.exit_code == 0
    assert "provider" not in json.loads(result.stdout)
