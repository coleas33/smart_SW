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


def test_the_shipped_table_covers_the_three_contracted_tools() -> None:
    envelopes = load_envelopes()

    assert set(envelopes.tools) == {"hex_key", "socket", "screwdriver"}
    assert envelopes.tools["hex_key"].envelope_diameter_ratio == 0.6
    assert envelopes.tools["socket"].envelope_diameter_ratio == 1.6
    assert envelopes.tools["screwdriver"].envelope_diameter_ratio == 1.2


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
    path = tmp_path / "bad.yaml"
    path.write_text(
        "version: 1\nclearance_mm: 0.5\ntools:\n"
        "  socket:\n    envelope_diameter_ratio: 0\n    source: made up\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="envelope_diameter_ratio"):
        load_envelopes(path)
