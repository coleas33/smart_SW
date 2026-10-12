"""Thread pitch on the committed fixtures (feature 010 amendment 2026-10-08, T118;
`contracts/fasteners.md` section 8.11, SC-010).

No replay or mechanical fixture states a fine thread, so `run_thread_checks` records no finding
on any of them, and each gives exactly section 8.11's rows: its coarse tapped holes and screws
counted in the checked row, the big replay fixture's Hole Wizard pipe tap `3/8` listed as
unreadable, and the `hole` gaps that name no hole listed as not read. No fixture has a `thread`
or `fastener` gap that names no row, and every one is a `full` package whose hole and fastener
phases ran, so none has a phases row or a "nothing at all" row. The figures were counted on
2026-10-08 (research R2.26).
"""

from __future__ import annotations

import re
from functools import cache
from pathlib import Path

import pytest

from swreview.checks.thread_pitch import ThreadChecks, run_thread_checks
from swreview.ir.loader import load_package
from swreview.ir.models import EvidencePackage

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"

FIXTURE_ROWS: dict[str, tuple[int, int, int]] = {
    "replay/big-assembly": (11, 0, 3),
    "replay/small-assembly-a": (1, 0, 0),
    "replay/small-assembly-b": (1, 0, 2),
    "mechanical/big-assembly": (12, 68, 1),
    "mechanical/small-assembly": (1, 0, 0),
}
"""Each fixture's coarse tapped holes, coarse screws named by their parts, and `hole` gaps
that name no hole row (section 8.11)."""

ID = re.compile(r"(?:hol|thr|fas|cmp):[0-9]{4,}")
NOT_READ = (
    "{gaps} left holes, cosmetic threads or fasteners unread, so their pitch was not checked: "
)


@cache
def package(name: str) -> EvidencePackage:
    return load_package(FIXTURES / name).package


@cache
def checks(name: str) -> ThreadChecks:
    return run_thread_checks(package(name))


def listed_ids(reason: str) -> list[str]:
    return ID.findall(reason)


@pytest.mark.parametrize("name", FIXTURE_ROWS)
def test_no_committed_fixture_states_a_fine_or_non_standard_thread(name: str) -> None:
    assert checks(name).findings == ()


@pytest.mark.parametrize("name", FIXTURE_ROWS)
def test_every_coarse_thread_is_counted_in_one_checked_row(name: str) -> None:
    holes, screws, _ = FIXTURE_ROWS[name]
    [row] = checks(name).checked

    ids = listed_ids(row.reason)
    assert row.reason.startswith(f"{holes + screws} thread")
    assert "no pitch written" not in row.reason
    assert len([item for item in ids if item.startswith("hol:")]) == holes
    assert len([item for item in ids if item.startswith("cmp:")]) == screws
    assert len(ids) == len(set(ids)) == holes + screws
    assert (checks(name).coarse, checks(name).threads) == (
        holes + screws,
        holes + screws + (1 if name == "replay/big-assembly" else 0),
    )


@pytest.mark.parametrize("name", FIXTURE_ROWS)
def test_only_the_big_replay_fixtures_pipe_tap_is_unreadable(name: str) -> None:
    expected = []
    if name == "replay/big-assembly":
        expected = [
            "1 thread could not be read for pitch, so their pitch was not checked: '3/8' on "
            "hol:0009"
        ]

    assert [row.reason for row in checks(name).unresolved] == expected


@pytest.mark.parametrize("name", FIXTURE_ROWS)
def test_the_only_skipped_row_lists_the_hole_gaps_that_name_no_hole(name: str) -> None:
    """No suppressed row, no phases row, no "nothing at all" row: on the replay fixtures every
    tapped hole's feature row is read not suppressed (the next test), and the mechanical
    fixtures carry no feature rows, so whether a hole is suppressed is not read at all."""
    _, _, gaps = FIXTURE_ROWS[name]
    pkg = package(name)
    holes = {item.id for item in pkg.holes}
    named_none = sorted(
        (gap for gap in pkg.gaps if gap.entity_kind == "hole" and gap.entity_id not in holes),
        key=lambda gap: (gap.entity_id is not None, gap.entity_id or "", gap.reason),
    )
    # The fixtures carry no cosmetic thread and no fastener row, so any such gap would name none.
    thread_or_fastener_gaps = [
        gap for gap in pkg.gaps if gap.entity_kind in ("thread", "fastener")
    ]

    assert (pkg.threads, pkg.fasteners, thread_or_fastener_gaps) == ([], [], [])
    assert len(named_none) == gaps
    if not gaps:
        assert checks(name).skipped == ()
        return
    [row] = checks(name).skipped
    noun = "extractor gap" if gaps == 1 else "extractor gaps"
    assert row.reason == NOT_READ.format(gaps=f"{gaps} {noun}") + "; ".join(
        gap.reason for gap in named_none
    )


def test_the_mechanical_fixtures_gap_is_its_generators_component_gap() -> None:
    [row] = checks("mechanical/big-assembly").skipped

    assert row.reason.endswith(": no Hole Wizard feature of this component could be read")
    assert row.scope.component_ids == ["cmp:0010"]


def test_the_replay_fixtures_not_read_gaps_name_no_component() -> None:
    """Section 8.11: two lightweight components and one suppressed on the big fixture, two
    lightweight on small-assembly-b, each a gap with a null id, which no scope can carry."""
    for name in ("replay/big-assembly", "replay/small-assembly-b"):
        [row] = checks(name).skipped
        assert row.scope.component_ids == []


@pytest.mark.parametrize(
    "name", ["replay/big-assembly", "replay/small-assembly-a", "replay/small-assembly-b"]
)
def test_every_replay_tapped_hole_joins_a_feature_row_read_not_suppressed(name: str) -> None:
    """With every tapped hole made fine, each finding carries the drawings limit alone: no
    hole's suppression went unread, so the coarse holes above were joined and kept."""
    pkg = package(name)
    fine = pkg.model_copy(
        update={
            "holes": [
                hole.model_copy(update={"thread_designation": "M8x1"})
                if hole.hole_type == "tapped"
                else hole
                for hole in pkg.holes
            ]
        }
    )

    found = run_thread_checks(fine).findings
    tapped = [hole for hole in pkg.holes if hole.hole_type == "tapped"]

    assert sum(len(listed_ids(item.result.observed)) for item in found) == len(tapped)
    for item in found:
        assert item.result.coverage_limits == [
            "thread callouts on drawings were not read for pitch"
        ]
