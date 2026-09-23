"""Unit tests for the tool-envelope table (T090).

The radii a driving tool sweeps are data, not code, for the same reason the engagement
ratios are: a finding has to cite the number that cleared or failed it, and an engineer
has to be able to change it. The table ships as pilot defaults and says so in every row.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from swreview.checks.tool_envelopes import (
    DEFAULT_ENVELOPES_PATH,
    envelope_radius_mm,
    load_envelopes,
)


def test_the_shipped_table_covers_the_contracted_tools() -> None:
    """Edited deliberately by feature 010 T056: the three tools `check_tool_envelope` offers,
    and the Torx key the owner named for flat and button head Torx screws (research R5)."""
    envelopes = load_envelopes()

    assert set(envelopes.tools) == {"hex_key", "torx_key", "socket", "screwdriver"}
    assert envelopes.tools["hex_key"].envelope_diameter_ratio == 0.6
    assert envelopes.tools["torx_key"].envelope_diameter_ratio == 1.0
    assert envelopes.tools["socket"].envelope_diameter_ratio == 1.6
    assert envelopes.tools["screwdriver"].envelope_diameter_ratio == 1.2


def test_every_tool_carries_a_positive_reach_labelled_a_pilot_default() -> None:
    for tool in load_envelopes().tools.values():
        assert tool.reach_diameter_ratio > 0.0
        assert tool.source.startswith("pilot default")
        assert "reach" in tool.source


def test_the_reach_is_the_ratio_times_d() -> None:
    envelopes = load_envelopes()

    assert envelopes.reach_mm("hex_key", 8.0) == pytest.approx(5.0 * 8.0)
    with pytest.raises(KeyError, match="hex_key"):
        envelopes.reach_mm("spanner", 8.0)
    with pytest.raises(ValueError, match="positive"):
        envelopes.reach_mm("hex_key", 0.0)


def test_the_drives_and_heads_map_to_tools_the_table_carries() -> None:
    """`contracts/tool-access.md` section 2: the drive first, the head type second."""
    envelopes = load_envelopes()

    assert envelopes.drive_tools == {
        "hex_socket": "hex_key",
        "torx": "torx_key",
        "hex_head": "socket",
    }
    assert envelopes.head_tools == {
        "socket head cap": "hex_key",
        "button head": "hex_key",
        "socket countersunk head": "hex_key",
        "hex head": "socket",
    }


def test_the_driving_tool_the_model_offers_is_unchanged() -> None:
    """The Torx key is the joint checks' own; `check_tool_envelope`'s argument is not widened
    (the model-facing tool array does not move)."""
    from swreview.tools.measure import DRIVING_TOOLS

    assert DRIVING_TOOLS == ("hex_key", "socket", "screwdriver")


def test_every_row_cites_a_source() -> None:
    for tool in load_envelopes().tools.values():
        assert tool.source


def test_the_radius_is_half_the_envelope_diameter_plus_clearance() -> None:
    envelopes = load_envelopes()

    radius = envelope_radius_mm("socket", 6.0, envelopes)

    assert radius == pytest.approx(1.6 * 6.0 / 2.0 + envelopes.clearance_mm)


def test_an_unknown_tool_raises_naming_the_ones_that_exist() -> None:
    with pytest.raises(KeyError, match="hex_key"):
        envelope_radius_mm("spanner", 6.0)


def test_a_non_positive_diameter_raises() -> None:
    with pytest.raises(ValueError, match="positive"):
        envelope_radius_mm("socket", 0.0)


def test_the_default_path_is_the_shipped_yaml() -> None:
    assert DEFAULT_ENVELOPES_PATH.name == "tool_envelopes.yaml"
    assert DEFAULT_ENVELOPES_PATH.is_file()


def test_a_table_with_an_unusable_ratio_is_refused(tmp_path: Path) -> None:
    """Edited deliberately by feature 010 T056: a row now carries a reach as well."""
    path = tmp_path / "bad.yaml"
    path.write_text(
        "version: 1\nclearance_mm: 0.5\ntools:\n"
        "  socket:\n    envelope_diameter_ratio: 0\n    reach_diameter_ratio: 4\n"
        "    source: made up\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="envelope_diameter_ratio"):
        load_envelopes(path)


def test_a_tool_without_a_reach_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "no-reach.yaml"
    path.write_text(
        "version: 1\nclearance_mm: 0.5\ntools:\n"
        "  socket:\n    envelope_diameter_ratio: 1.6\n    source: made up\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="reach_diameter_ratio"):
        load_envelopes(path)


def test_a_head_mapped_to_a_tool_the_table_lacks_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "bad-map.yaml"
    path.write_text(
        "version: 1\nclearance_mm: 0.5\ntools:\n"
        "  socket:\n    envelope_diameter_ratio: 1.6\n    reach_diameter_ratio: 4\n"
        "    source: made up\n"
        "head_tools:\n  hex head: spanner\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="spanner"):
        load_envelopes(path)
