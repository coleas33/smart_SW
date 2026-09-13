"""Unit tests for BOM ingest (T024).

The BOM states how many of each document the design uses. When that count disagrees
with the component instances in the package, or names a document the package does not
hold, the disagreement becomes a `Gap` rather than a silent choice between the two
(constitution Principle I).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from swreview.ingest.bom import BOM_COLUMNS, BomRow, bom_gaps, read_bom
from swreview.ir.models import EvidencePackage

REPO_ROOT = Path(__file__).resolve().parents[3]
BENCHMARK_BOM = REPO_ROOT / "benchmarks" / "packages" / "cover-blind-tap" / "bom.csv"

HEADER = "item,part_number,document_id,description,quantity,configuration"


def write_bom(directory: Path, *lines: str) -> Path:
    """Write a `bom.csv` with the standard header and `lines`, and return its path."""
    path = directory / "bom.csv"
    path.write_text("\n".join((HEADER, *lines)) + "\n", encoding="utf-8")
    return path


# --- read_bom --------------------------------------------------------------------


def test_read_bom_parses_every_column(tmp_path: Path) -> None:
    path = write_bom(tmp_path, "1,P-1,doc:2,Housing 6061-T6,2,Default")

    rows = read_bom(path)

    assert rows == [
        BomRow(
            item=1,
            part_number="P-1",
            document_id="doc:2",
            description="Housing 6061-T6",
            quantity=2,
            configuration="Default",
        )
    ]


def test_read_bom_reads_the_benchmark_package() -> None:
    rows = read_bom(BENCHMARK_BOM)

    assert [row.document_id for row in rows] == ["PRT-1001", "PRT-1002", "PRT-1003"]
    screws = rows[2]
    assert screws.quantity == 4
    assert screws.configuration == "M6 x 20"
    assert screws.description == "Socket head cap screw M6 x 20 ISO 4762"


def test_read_bom_keeps_surrounding_whitespace_out_of_values(tmp_path: Path) -> None:
    path = write_bom(tmp_path, " 1 , P-1 , doc:2 , Housing , 2 , Default ")

    row = read_bom(path)[0]

    assert row.part_number == "P-1"
    assert row.document_id == "doc:2"
    assert row.quantity == 2


def test_read_bom_rejects_a_missing_column(tmp_path: Path) -> None:
    path = tmp_path / "bom.csv"
    path.write_text("item,part_number,document_id,description,quantity\n1,P-1,doc:2,H,2\n", "utf-8")

    with pytest.raises(ValueError, match="configuration"):
        read_bom(path)


def test_read_bom_rejects_a_non_integer_quantity(tmp_path: Path) -> None:
    """A quantity that is not a whole number is never rounded or dropped."""
    path = write_bom(tmp_path, "1,P-1,doc:2,Housing,two,Default")

    with pytest.raises(ValueError, match="quantity"):
        read_bom(path)


def test_read_bom_rejects_a_negative_quantity(tmp_path: Path) -> None:
    path = write_bom(tmp_path, "1,P-1,doc:2,Housing,-1,Default")

    with pytest.raises(ValueError, match="quantity"):
        read_bom(path)


def test_read_bom_rejects_an_empty_document_id(tmp_path: Path) -> None:
    path = write_bom(tmp_path, "1,P-1,,Housing,1,Default")

    with pytest.raises(ValueError, match="document_id"):
        read_bom(path)


def test_bom_columns_are_the_documented_ones() -> None:
    assert BOM_COLUMNS == (
        "item",
        "part_number",
        "document_id",
        "description",
        "quantity",
        "configuration",
    )


# --- bom_gaps --------------------------------------------------------------------


def test_no_gap_when_the_quantity_matches_the_component_count(
    tmp_path: Path, make_package: Callable[..., EvidencePackage]
) -> None:
    package = make_package()
    rows = read_bom(write_bom(tmp_path, "1,P-1,doc:2,Housing,2,Default"))

    assert bom_gaps(rows, package) == []


def test_quantity_mismatch_becomes_a_gap(
    tmp_path: Path, make_package: Callable[..., EvidencePackage]
) -> None:
    package = make_package()
    rows = read_bom(write_bom(tmp_path, "1,P-1,doc:2,Housing,3,Default"))

    gaps = bom_gaps(rows, package)

    assert len(gaps) == 1
    gap = gaps[0]
    assert gap.kind == "not_extracted"
    assert gap.entity_kind == "bom"
    assert gap.entity_id == "doc:2"
    assert "3" in gap.reason
    assert "2" in gap.reason
    assert gap.error is None


def test_a_document_absent_from_the_package_becomes_a_gap(
    tmp_path: Path, make_package: Callable[..., EvidencePackage]
) -> None:
    package = make_package()
    rows = read_bom(
        write_bom(
            tmp_path,
            "1,P-1,doc:2,Housing,2,Default",
            "2,P-9,doc:9,Gasket,1,Default",
        )
    )

    gaps = bom_gaps(rows, package)

    assert [gap.entity_id for gap in gaps] == ["doc:9"]
    assert gaps[0].entity_kind == "bom"
    assert gaps[0].kind == "not_extracted"
    assert "not in the package" in gaps[0].reason


def test_a_document_with_no_component_instances_becomes_one_gap(
    tmp_path: Path, make_package: Callable[..., EvidencePackage]
) -> None:
    """`doc:1` is the root assembly: a document of the package with no instance of its own."""
    package = make_package()
    rows = read_bom(write_bom(tmp_path, "1,P-0,doc:1,Cover assembly,1,Default"))

    gaps = bom_gaps(rows, package)

    assert [gap.entity_id for gap in gaps] == ["doc:1"]
    assert "0 component instance" in gaps[0].reason


def test_gaps_follow_bom_order(
    tmp_path: Path, make_package: Callable[..., EvidencePackage]
) -> None:
    package = make_package()
    rows = read_bom(
        write_bom(
            tmp_path,
            "1,P-9,doc:9,Gasket,1,Default",
            "2,P-1,doc:2,Housing,5,Default",
            "3,P-8,doc:8,Shim,1,Default",
        )
    )

    assert [gap.entity_id for gap in bom_gaps(rows, package)] == ["doc:9", "doc:2", "doc:8"]
