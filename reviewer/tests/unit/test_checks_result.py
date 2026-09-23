"""The zone rule every position and coaxiality comparison shares (feature 010 T030, FR-009).

A position or coaxiality tolerance of `t` is a zone the axis may occupy: a cylinder of
diameter `t`, or a band of width `t`, centred on true position. Either way the axis may move
`t / 2` from where it should be, so the permitted radial offset is half the zone value -
whether or not a diameter symbol was read (research R2.8). One function says so, and both
`hole.coaxiality` and the joint stack call it.
"""

from __future__ import annotations

import pytest

from swreview.checks.result import permitted_radial_offset_mm


@pytest.mark.parametrize(
    ("zone", "permitted"), [(0.2, 0.1), (0.05, 0.025), (0.0, 0.0), (0.3, 0.15)]
)
def test_the_permitted_radial_offset_is_half_the_zone(zone: float, permitted: float) -> None:
    assert permitted_radial_offset_mm(zone) == permitted


def test_a_negative_zone_is_refused() -> None:
    with pytest.raises(ValueError, match="zone"):
        permitted_radial_offset_mm(-0.2)
