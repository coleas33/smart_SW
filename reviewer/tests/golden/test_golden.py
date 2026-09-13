"""Golden fixtures: one directory per case (T019, research R9).

Each `fixtures/<case>/` holds a hand-curated `package.json` and a `case.json` naming the
callable to run over it:

    {"callable": "swreview.tools.query:list_holes", "kwargs": {"component_id": "cmp:0001"}}

The callable takes the loaded `EvidencePackage` as its first argument. Its JSON form is
compared with `pytest-regressions`; regenerate intentionally with `--force-regen`. A case
whose module does not exist yet is skipped, so a fixture can be committed with the test
that motivates it.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

import pytest
from pydantic_core import to_jsonable_python
from pytest_regressions.data_regression import DataRegressionFixture

from swreview.ir.loader import load_package

FIXTURES_DIR = Path(__file__).parent / "fixtures"
FIXTURE_DIRS = sorted(path for path in FIXTURES_DIR.iterdir() if path.is_dir())


def resolve_callable(spec: str) -> Any:
    """Import `module:attribute`, skipping the test when it has not been written yet."""
    module_name, separator, attribute = spec.partition(":")
    if not separator:
        raise ValueError(f"case callable {spec!r} must be written as 'module:attribute'")
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError:
        pytest.skip(f"{module_name} does not exist yet")
    function = getattr(module, attribute, None)
    if function is None:
        pytest.skip(f"{module_name} has no {attribute} yet")
    return function


def test_a_case_for_an_unwritten_module_is_skipped() -> None:
    with pytest.raises(pytest.skip.Exception):
        resolve_callable("swreview.not_written_yet:list_holes")


def test_a_case_for_an_unwritten_function_is_skipped() -> None:
    with pytest.raises(pytest.skip.Exception):
        resolve_callable("swreview.ir.summary:not_written_yet")


def test_a_case_callable_must_name_an_attribute() -> None:
    with pytest.raises(ValueError, match="module:attribute"):
        resolve_callable("swreview.ir.summary")


@pytest.mark.parametrize("fixture_dir", FIXTURE_DIRS, ids=lambda path: path.name)
def test_golden_case(fixture_dir: Path, data_regression: DataRegressionFixture) -> None:
    case = json.loads((fixture_dir / "case.json").read_text(encoding="utf-8"))
    function = resolve_callable(case["callable"])

    loaded = load_package(fixture_dir)
    result = function(loaded.package, **case.get("kwargs", {}))

    data_regression.check({"result": to_jsonable_python(result)}, basename=fixture_dir.name)
