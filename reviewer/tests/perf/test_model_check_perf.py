"""The wall-clock budget for one Model check (T086).

The tab's claim is that a part grades "in seconds, not minutes" (SC-008, FR-024) with no
provider and no key, and the number behind that claim should not need a SOLIDWORKS seat to
reproduce: this module builds a part with `FEATURE_ROWS` feature rows out of the same
builders the unit tests use and times `run_rms_check` end to end - the same entry point
`POST /checks/rms` and `swreview check rms` call, so what is measured is what the engineer
waits for after pressing the button, minus the dump.

Why it is not in the default run, and how to run it: see `test_rms_perf.py` (T060), whose
conventions this module follows rather than restating - `tests/conftest.py` does not
collect `tests/perf/` unless the run's `-m` names the marker:

    uv run pytest -m perf -s

Fixture construction and the package write are outside the timer, for the reason T060
gives: nobody waits for `save_package` in the product. `session.json` and `report.md` are
written *inside* it, because `run_rms_check` writes them before it returns and the page
cannot render until it does.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from swreview.checks.rms.run import RmsScope, run_rms_check
from swreview.ir.loader import save_package
from tests.support.features import (
    FeatureSpec,
    PartSpec,
    equation,
    feature,
    fillet_feature,
    folder,
    rms_package,
    sketch_feature,
)

pytestmark = pytest.mark.perf

PART_DOCUMENT = "doc:2"

FEATURE_ROWS = 150
"""Feature rows in the part, folders included - the size T086 names.

A tree this size is a large real part rather than a microbenchmark: the pilot parts run
40 to 80 rows, and a 150-row part is the one an engineer is most likely to be waiting on.
"""

GROUP_SIZES: tuple[tuple[str, int], ...] = (
    ("1-Ref", 12),
    ("2-Construction", 24),
    ("3-Core", 36),
    ("4-Detail", 36),
    ("5-Modify", 24),
    ("6-Quarantine", 12),
)
"""The six RMS groups in order and how many content features each one holds.

They sum with their own folder rows to `FEATURE_ROWS`, and the shape is deliberately
front-heavy on Core and Detail, which is where the rules that walk parents and consumers
do their work.
"""

VIOLATION_EVERY = 8
"""One content feature in eight is seeded to fail a rule, so the finding path - the
subject builder, the fingerprint, the exception refresh and the report - is inside the
timer too and the budget is not a measurement of the clean path alone."""

BUDGET_SECONDS = 2.0
"""What one Model check of `FEATURE_ROWS` rows must stay under (T086, SC-008)."""


def _content(group: str, index: int, position: int) -> FeatureSpec:
    """One content feature of `group`. Every eighth one is seeded to fail a rule."""
    seeded = position % VIOLATION_EVERY == 0
    name = f"{group}-{index:02d}"

    if group == "1-Ref":
        return feature(name, "RefPlane", description="" if seeded else "REF datum plane")
    if group == "2-Construction":
        # A sketch and the surface that consumes it, alternating, so the consumer walk
        # has something to follow rather than a flat list of leaves.
        if index % 2 == 0:
            return sketch_feature(name, consumers=(f"{group}-{index + 1:02d}",))
        return feature(
            name,
            "SurfaceExtrude",
            parent_names=(f"{group}-{index - 1:02d}",),
            description="" if seeded else "CONSTRUCTION reference surface",
        )
    if group == "3-Core":
        if index % 3 == 0:
            return sketch_feature(name, consumers=(f"{group}-{index + 1:02d}",))
        return feature(
            name,
            "Extrusion" if index % 3 == 1 else "Shell",
            parent_names=(f"{group}-{index - (index % 3):02d}",),
            description="" if seeded else "CORE material",
        )
    if group == "4-Detail":
        if index % 2 == 0:
            return feature(name, "HoleWzd", description="" if seeded else "DETAIL fastener hole")
        return feature(name, "Cut", description="" if seeded else "DETAIL clearance cut")
    if group == "5-Modify":
        return feature(
            name,
            "Draft" if index % 2 == 0 else "LPattern",
            description="" if seeded else "MODIFY draft for moulding",
        )
    return fillet_feature(
        name,
        radius_m=0.003 if seeded else 0.006,
        description="" if seeded else "QUARANTINE cosmetic fillet",
    )


def _tree() -> tuple[FeatureSpec, ...]:
    """The six group folders and their contents, `FEATURE_ROWS` rows in all."""
    position = 0
    groups: list[FeatureSpec] = []
    for group, count in GROUP_SIZES:
        contents: list[FeatureSpec] = []
        for index in range(count):
            position += 1
            contents.append(_content(group, index, position))
        groups.append(folder(group, *contents))
    return tuple(groups)


@pytest.fixture
def check_dir(tmp_path: Path) -> Path:
    """A check run folder inside a run root, holding the part package and nothing else."""
    package = rms_package(
        parts=[
            PartSpec(
                document_id=PART_DOCUMENT,
                name="perf-part",
                equations=(
                    equation('"thickness" = 3mm', is_global=True, value=0.003),
                    equation('"D1@Sketch2" = "thickness" * 2', value=0.006),
                ),
                features=_tree(),
            )
        ]
    )
    assert len(package.features) == FEATURE_ROWS, (
        f"the builder produced {len(package.features)} feature rows, not {FEATURE_ROWS}; "
        "the budget below would be measuring a different workload"
    )

    directory = tmp_path / "runs" / "20260916-101532-perf-part-check"
    save_package(package, directory)
    return directory


def test_a_model_check_of_a_hundred_and_fifty_features_is_within_the_budget(
    check_dir: Path,
) -> None:
    started = time.perf_counter()
    run = run_rms_check(check_dir, scope=RmsScope.part)
    elapsed = time.perf_counter() - started

    # The budget means nothing without the workload: a run that graded nothing, or that
    # found nothing to report, would come in under two seconds as well.
    assert run.documents == [PART_DOCUMENT]
    assert run.findings
    assert run.session_file.is_file()
    assert run.report_file.is_file()

    print()
    print(
        f"run_rms_check over {FEATURE_ROWS} feature rows: "
        f"{elapsed:.3f} s, budget {BUDGET_SECONDS} s"
    )
    assert elapsed < BUDGET_SECONDS, (
        f"a Model check of {FEATURE_ROWS} feature rows took {elapsed:.3f} s, "
        f"over the {BUDGET_SECONDS} s budget"
    )
