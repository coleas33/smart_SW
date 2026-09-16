"""Unit tests for `swreview rms types` (T044).

The command is the calibration report for `rms_types.yaml`: it names every `GetTypeName2`
string the shipped table does not classify, how many content features carry it, and which
documents they are in, so an engineer can extend the table from evidence rather than from
memory. It decides nothing about those features - a type name the table does not know is
not a finding here, it is the input to a recalibration.

The rms-part golden fixture is the package under test because it already carries the two
cases that matter and is regenerated from the same builder the rules are tested with: the
`widget` part (`doc:4`) holds two features of `NoSuchType`, and every other type name in
the package is in the table.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from swreview.ir.loader import save_package
from tests.unit.test_cli import invoke, payload

RMS_PART_FIXTURE = Path(__file__).resolve().parents[1] / "golden" / "fixtures" / "rms-part"

UNKNOWN_TYPE = "NoSuchType"
"""The one type name the rms-part fixture carries that the table does not classify."""

WIDGET = "doc:4"
"""The fixture's unknown-data part; both `NoSuchType` features live there."""


@pytest.fixture
def package_dir(tmp_path: Path) -> Path:
    """The rms-part golden package, copied so a test can never edit the fixture."""
    directory = tmp_path / "package"
    shutil.copytree(RMS_PART_FIXTURE, directory)
    return directory


@pytest.fixture
def classified_dir(tmp_path: Path) -> Path:
    """A package whose every content feature carries a type name the table classifies."""
    from tests.support.features import AssemblySpec, PartSpec, feature, folder, rms_package

    package = rms_package(
        parts=[
            PartSpec(
                document_id="doc:2",
                name="frame",
                features=(
                    folder("3-Core", feature("Boss-Extrude1", "Extrusion")),
                    folder("4-Detail", feature("Hole1", "HoleWzd")),
                ),
            )
        ],
        assembly=AssemblySpec(document_id="doc:1", name="cover-assy"),
    )
    directory = tmp_path / "classified"
    save_package(package, directory)
    return directory


def test_rms_types_names_the_unclassified_type_with_its_count_and_documents(
    package_dir: Path,
) -> None:
    body = payload(invoke("rms", "types", "--package", str(package_dir), "--json"))

    assert body["package"] == str(package_dir.resolve())
    assert body["types"] == [{"type_name": UNKNOWN_TYPE, "count": 2, "documents": [WIDGET]}]


def test_rms_types_human_output_names_the_type_its_count_and_the_document(
    package_dir: Path,
) -> None:
    result = invoke("rms", "types", "--package", str(package_dir))

    assert result.exit_code == 0
    assert UNKNOWN_TYPE in result.stdout
    assert "x2" in result.stdout
    assert WIDGET in result.stdout


def test_rms_types_reports_nothing_when_every_type_name_is_in_the_table(
    classified_dir: Path,
) -> None:
    """An empty census is an answer, not silence: the count line still prints."""
    result = invoke("rms", "types", "--package", str(classified_dir))
    body = payload(invoke("rms", "types", "--package", str(classified_dir), "--json"))

    assert result.exit_code == 0
    assert result.stdout.strip() == "0 type name(s) the table does not classify"
    assert body["types"] == []


def test_rms_types_ignores_folders_and_end_tags(package_dir: Path) -> None:
    """Folders and end-tag markers are structure; the table classifies neither by class."""
    body = payload(invoke("rms", "types", "--package", str(package_dir), "--json"))

    assert "FtrFolder" not in {row["type_name"] for row in body["types"]}


def test_rms_types_leaves_the_package_byte_for_byte(package_dir: Path) -> None:
    before = (package_dir / "package.json").read_bytes()

    assert invoke("rms", "types", "--package", str(package_dir)).exit_code == 0
    assert (package_dir / "package.json").read_bytes() == before


def test_rms_types_on_an_unreadable_package_exits_1(tmp_path: Path) -> None:
    result = invoke("rms", "types", "--package", str(tmp_path / "nowhere"))

    assert result.exit_code == 1
    assert result.stderr.startswith("error: ")
    assert result.stdout == ""
    assert "Traceback" not in result.stderr


def test_rms_types_without_a_package_is_a_usage_error() -> None:
    assert invoke("rms", "types").exit_code == 2
