"""The wall-clock budget for `swreview check rms` (T060).

SC-008 says a Model check answers in seconds, not minutes, and the one number behind that
claim should not need a SOLIDWORKS seat to reproduce: this module builds a 100-part
package with the same builders the unit tests use and times the command end to end.

Why it is not in the default run. A timing assertion is a statement about the machine as
much as about the code - a loaded laptop or a shared CI runner makes it red without any
commit being at fault - so `tests/perf/` is *not collected* unless the run asks for the
`perf` marker (`tests/conftest.py::pytest_ignore_collect`). Not collecting is deliberate
rather than skipping the way `integration` and `live` do: those two skip because the
checkout is missing an input, and their skip line is the useful report that it is; a perf
test that reported "skipped" on every run would be noise claiming a measurement was
considered. Run them with:

    uv run pytest -m perf -s

`-s` because the measured seconds are printed: an assertion that only says "under 2 s"
hides the trend that says the budget is about to be missed.

The budget covers the whole command - load, validate, all three rule families, coverage,
and JSON rendering - because that is what the engineer waits for. Fixture construction is
outside the timer for the same reason: nobody waits for `save_package` in the product.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from typer.testing import CliRunner

from swreview.cli import app
from swreview.ir.loader import save_package
from tests.support.features import (
    AssemblySpec,
    PartSpec,
    equation,
    feature,
    fillet_feature,
    folder,
    rms_package,
    sketch_feature,
)

pytestmark = pytest.mark.perf

PART_COUNT = 100
"""Parts in the package - the pilot assembly's order of magnitude (SC-002 names 200
components), so the number is a real workload rather than a microbenchmark."""

BUDGET_SECONDS = 2.0
"""What `check rms` must stay under for the whole package (T060)."""

VIOLATION_EVERY = 10
"""One part in ten seeds violations, so the finding path - fingerprint, exception refresh,
rendering - is inside the timer too and the budget is not a measurement of the clean path
alone."""

runner = CliRunner()


def _part(index: int) -> PartSpec:
    """One part: the six groups in order, 20 or 21 rows, two equations.

    Mostly compliant. A rule that finds an offender usually stops there, so a package of
    clean parts is the slower path through the rules themselves; every tenth part seeds
    two failures so the finding path is timed as well (`VIOLATION_EVERY`).
    """
    seeded = index % VIOLATION_EVERY == 0
    loose = (feature("Axis1", "RefAxis"),) if seeded else ()
    return PartSpec(
        document_id=f"doc:{index + 2}",
        name=f"part-{index:03d}",
        equations=(
            equation('"thickness" = 3mm', is_global=True, value=0.003),
            equation('"D1@Sketch2" = "thickness" * 2', value=0.006),
        ),
        features=(
            # A content feature above the first group folder: no group owns it
            # (`rms.grouping.all_features_in_a_group`).
            *loose,
            folder("1-Ref", feature("Plane1", "RefPlane")),
            folder(
                "2-Construction",
                sketch_feature("Sketch1", consumers=("Surface1",)),
                feature("Surface1", "SurfaceExtrude", parent_names=("Sketch1",)),
            ),
            folder(
                "3-Core",
                sketch_feature("Sketch2", consumers=("Boss-Extrude1",)),
                feature("Boss-Extrude1", "Extrusion", parent_names=("Sketch2",)),
                # Blank description on a seeded part
                # (`rms.intent.every_feature_described`).
                feature(
                    "Shell1",
                    "Shell",
                    parent_names=("Boss-Extrude1",),
                    description="" if seeded else "CORE wall thickness",
                ),
            ),
            folder(
                "4-Detail",
                sketch_feature("Sketch3", consumers=("Cut-Extrude1",)),
                feature("Cut-Extrude1", "Cut", parent_names=("Sketch3",)),
                feature("Hole1", "HoleWzd"),
            ),
            folder(
                "5-Modify",
                feature("Draft1", "Draft"),
                feature("LPattern1", "LPattern"),
            ),
            folder(
                "6-Quarantine",
                feature("Chamfer1", "Chamfer"),
                fillet_feature("Fillet1", radius_m=0.006),
                fillet_feature("Fillet2", radius_m=0.003),
            ),
        ),
    )


@pytest.fixture
def hundred_part_package_dir(tmp_path: Path) -> Path:
    """A written package: one root assembly and `PART_COUNT` part documents."""
    package = rms_package(
        parts=[_part(index) for index in range(PART_COUNT)],
        assembly=AssemblySpec(document_id="doc:1", name="perf-assy"),
    )
    directory = tmp_path / "rms-perf-package"
    save_package(package, directory)
    return directory


def test_check_rms_grades_a_hundred_part_package_within_the_budget(
    hundred_part_package_dir: Path,
) -> None:
    started = time.perf_counter()
    result = runner.invoke(
        app, ["check", "rms", "--package", str(hundred_part_package_dir), "--json"]
    )
    elapsed = time.perf_counter() - started

    assert result.exit_code == 0, result.stderr
    # The budget means nothing without the workload: a command that graded nothing, or
    # that found nothing to report, would come in under two seconds as well.
    body = json.loads(result.stdout)
    assert len(body["documents"]) == PART_COUNT
    assert body["assembly_document"] == "doc:1"
    assert len(body["findings"]) == 2 * (PART_COUNT // VIOLATION_EVERY)

    print()
    print(f"check rms over {PART_COUNT} parts: {elapsed:.3f} s, budget {BUDGET_SECONDS} s")
    assert elapsed < BUDGET_SECONDS, (
        f"check rms over {PART_COUNT} parts took {elapsed:.3f} s, "
        f"over the {BUDGET_SECONDS} s budget"
    )
