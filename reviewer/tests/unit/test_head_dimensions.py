"""The standard head table (feature 010 T054, `contracts/tool-access.md` section 4).

Head fit compares a counterbore or countersink with the largest head the screw's standard
allows, and a screw with no mesh gets its head plane from its shank face plus the head
height. Both read `checks/head_dimensions.yaml`: rows by head type and size, each standard
citing itself, and a head type or size the table lacks is `None` - never approximated.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from swreview.checks.tool_access import (
    DEFAULT_HEADS_PATH,
    HeadDimensions,
    load_head_dimensions,
)


@pytest.fixture(scope="module")
def heads() -> HeadDimensions:
    return load_head_dimensions()


@pytest.mark.parametrize(
    ("head_type", "designation", "standard", "dk", "k"),
    [
        ("socket head cap", "M2x0.4", "ISO 4762", 3.8, 2.0),
        ("socket head cap", "M8x1.25", "ISO 4762", 13.0, 8.0),
        ("socket head cap", "M12", "ISO 4762", 18.0, 12.0),
        ("button head", "M5x0.8", "ISO 7380-1", 9.5, 2.75),
        ("button head", "M12x1.75", "ISO 7380-1", 21.0, 6.6),
        ("socket countersunk head", "M3x0.5", "ISO 10642", 6.72, 1.86),
        ("socket countersunk head", "M8", "ISO 10642", 17.92, 4.96),
        ("hex head", "M6x1.0", "ISO 4017/4014", 11.55, 4.15),
    ],
)
def test_rows_load_by_head_type_and_size(
    heads: HeadDimensions, head_type: str, designation: str, standard: str, dk: float, k: float
) -> None:
    row = heads.row(head_type, designation)

    assert row is not None
    assert (row.standard, row.dk_max_mm, row.k_max_mm) == (standard, dk, k)
    assert row.source.startswith(standard.split("/")[0])


def test_every_standard_covers_its_sizes_from_its_first_up_to_m12(heads: HeadDimensions) -> None:
    """ISO 4762 and the hex heads from M2; ISO 7380-1 and ISO 10642 start at M3."""
    sizes: dict[str, list[str]] = {}
    for (head_type, size), _row in heads.rows.items():
        sizes.setdefault(head_type, []).append(size)
    metric = ["M3", "M4", "M5", "M6", "M8", "M10", "M12"]
    assert sizes["socket head cap"] == ["M2", "M2.5", *metric]
    assert sizes["hex head"] == ["M2", "M2.5", *metric]
    assert sizes["button head"] == metric
    assert sizes["socket countersunk head"] == metric


def test_only_the_countersunk_standard_carries_a_head_angle(heads: HeadDimensions) -> None:
    angles = {row.head_type: row.countersink_angle_deg for row in heads.rows.values()}

    assert angles == {
        "socket head cap": None,
        "button head": None,
        "socket countersunk head": 90.0,
        "hex head": None,
    }


@pytest.mark.parametrize(
    ("size", "s_max"),
    [("M2", 4), ("M2.5", 5), ("M3", 5.5), ("M4", 7), ("M5", 8), ("M6", 10), ("M8", 13),
     ("M10", 16), ("M12", 18)],
)
def test_the_hex_head_diameter_is_the_across_corners_of_s_max_rounded_up(
    heads: HeadDimensions, size: str, s_max: float
) -> None:
    """The standard tabulates only a minimum across corners, so the table derives the bound
    a head can reach, s max / cos 30 degrees, and says so; rounded up so it stays a bound."""
    row = heads.rows[("hex head", size)]

    assert row.dk_max_mm == math.ceil(s_max / math.cos(math.radians(30.0)) * 100.0) / 100.0
    assert "s max / cos 30 degrees" in row.source


@pytest.mark.parametrize(
    ("head_type", "designation"),
    [
        ("flat head", "M3x0.5"),
        ("socket head cap", "M16x2.0"),
        ("button head", "M2x0.4"),
        ("socket head cap", "1/4-20"),
        (None, "M6"),
        ("socket head cap", None),
        ("socket head cap", "garbage"),
    ],
)
def test_an_unknown_head_type_or_size_is_none(
    heads: HeadDimensions, head_type: str | None, designation: str | None
) -> None:
    assert heads.row(head_type, designation) is None


def test_the_default_path_is_the_yaml_beside_the_loader() -> None:
    assert DEFAULT_HEADS_PATH.name == "head_dimensions.yaml"
    assert load_head_dimensions().version == 1


def _write(tmp_path: Path, row: str) -> Path:
    path = tmp_path / "heads.yaml"
    path.write_text(
        "version: 1\nstandards:\n  FICT 1:\n    head_type: socket head cap\n"
        f"    source: made up\n    rows:\n      M3: {row}\n",
        encoding="utf-8",
    )
    return path


@pytest.mark.parametrize(
    "row", ["{dk_max_mm: 0, k_max_mm: 3.0}", "{dk_max_mm: 5.5, k_max_mm: -1}", "{dk_max_mm: 5.5}"]
)
def test_a_non_positive_or_missing_value_is_refused(tmp_path: Path, row: str) -> None:
    with pytest.raises(ValueError, match="FICT 1 M3"):
        load_head_dimensions(_write(tmp_path, row))


def test_a_standard_without_a_source_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "heads.yaml"
    path.write_text(
        "version: 1\nstandards:\n  FICT 1:\n    head_type: socket head cap\n"
        "    rows:\n      M3: {dk_max_mm: 5.5, k_max_mm: 3.0}\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="source"):
        load_head_dimensions(path)
