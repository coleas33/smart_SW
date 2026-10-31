"""Every standards golden, precomputed under each settled polarity (006 T111; decision 172A).

`TRANSPARENCY_POLARITY` is `unsettled` until PROBE-2 answers at the seat (006 T102, research R2.8).
Flipping it changes every standards golden whose package carries an assembly with components, and
not only the three T102 names: so each `standards-*` case is run here under both settled values and
pinned in `test_transparency_polarity/<polarity>/<case>.yml`, the same callable and the same dump
`test_golden.py` uses. After the sitting the flip is mechanical (research R11): the one edit, then
those files copied over `test_golden/`.

No golden outside `standards-*` may depend on the polarity; the last case here says so of every one.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic_core import to_jsonable_python
from pytest_regressions.data_regression import DataRegressionFixture

from swreview.checks.standards import assembly
from swreview.ir.loader import load_package
from tests.golden.test_golden import FIXTURE_DIRS, WRITTEN_AT_1_4_0, resolve_callable

SETTLED = (assembly.ZERO_IS_OPAQUE, assembly.ONE_IS_OPAQUE)
STANDARDS_DIRS = [path for path in FIXTURE_DIRS if path.name.startswith(WRITTEN_AT_1_4_0)]


def graded(fixture_dir: Path, polarity: str, monkeypatch: pytest.MonkeyPatch) -> Any:
    """One golden case under `polarity`, exactly as `test_golden.test_golden_case` runs it."""
    monkeypatch.setattr(assembly, "TRANSPARENCY_POLARITY", polarity)
    case = json.loads((fixture_dir / "case.json").read_text(encoding="utf-8"))
    function = resolve_callable(case["callable"])
    result = function(load_package(fixture_dir).package, **case.get("kwargs", {}))
    return to_jsonable_python(result)


def test_the_standards_goldens_are_the_ones_the_prefix_names() -> None:
    assert len(STANDARDS_DIRS) >= 13
    assert {"standards-seeded", "standards-compliant", "standards-compliant-flat"} <= {
        path.name for path in STANDARDS_DIRS
    }


@pytest.mark.parametrize("polarity", SETTLED)
@pytest.mark.parametrize("fixture_dir", STANDARDS_DIRS, ids=lambda path: path.name)
def test_each_standards_golden_under_each_settled_polarity(
    fixture_dir: Path,
    polarity: str,
    monkeypatch: pytest.MonkeyPatch,
    data_regression: DataRegressionFixture,
) -> None:
    result = graded(fixture_dir, polarity, monkeypatch)

    data_regression.check({"result": result}, basename=f"{polarity}/{fixture_dir.name}")


def test_the_three_goldens_t102_names_change_with_the_flip(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("standards-seeded", "standards-compliant", "standards-compliant-flat"):
        fixture_dir = next(path for path in STANDARDS_DIRS if path.name == name)
        unsettled = graded(fixture_dir, assembly.UNSETTLED, monkeypatch)
        for polarity in SETTLED:
            assert graded(fixture_dir, polarity, monkeypatch) != unsettled, (name, polarity)


@pytest.mark.parametrize(
    "fixture_dir",
    [path for path in FIXTURE_DIRS if path not in STANDARDS_DIRS],
    ids=lambda path: path.name,
)
def test_no_other_golden_depends_on_the_polarity(
    fixture_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    unsettled = graded(fixture_dir, assembly.UNSETTLED, monkeypatch)
    for polarity in SETTLED:
        assert graded(fixture_dir, polarity, monkeypatch) == unsettled, polarity
