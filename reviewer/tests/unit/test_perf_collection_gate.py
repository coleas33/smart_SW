"""`tests/perf/` stays out of the default and CI runs (T060).

T060's one behavioural sentence is that the wall-clock budgets are "excluded from the
default and CI runs". `tests/conftest.py::pytest_ignore_collect` is what enforces it, and
until this module existed the only evidence it worked was that a default run happened to
stay green - which is also what a gate that had stopped firing would look like, right up
to the first red build on a loaded runner with no commit at fault.

So the hook is called here directly, with the marker expressions the three real runs pass:
the default `-m "not live"`, a bare run with no `-m` at all, and the deliberate `-m perf`.
The unresolved-path case is the one that is easy to lose: `collection_path` is whatever
pytest hands the hook, and a symlinked checkout, a differing drive-letter case, or a
rootdir that is not itself resolved all produce a path that names `tests/perf` without
being `==` to it.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import PERF_DIR, SIMULATION_DIR, pytest_ignore_collect


class _Config:
    """The one thing the hook asks of `pytest.Config`: the run's `-m` expression."""

    def __init__(self, markexpr: str) -> None:
        self._markexpr = markexpr

    def getoption(self, name: str) -> Any:
        assert name == "markexpr", f"unexpected option read by the hook: {name}"
        return self._markexpr


@pytest.mark.parametrize(
    "markexpr",
    [
        pytest.param("", id="bare-run"),
        pytest.param("not live", id="default-run"),
        pytest.param("not live and not raycast", id="ci-run"),
    ],
)
def test_perf_directory_is_ignored_when_the_marker_expression_does_not_name_perf(
    markexpr: str,
) -> None:
    assert pytest_ignore_collect(PERF_DIR, _Config(markexpr)) is True


def test_perf_directory_is_collected_when_the_run_asks_for_the_marker() -> None:
    # `None`, not `False`: the hook declines to decide, leaving other plugins and the
    # normal collection rules in charge. Returning `False` would *force* collection.
    assert pytest_ignore_collect(PERF_DIR, _Config("perf")) is None


def test_an_unresolved_path_to_the_perf_directory_is_still_ignored() -> None:
    """The gate must not depend on pytest handing it an already-resolved path."""
    unresolved = PERF_DIR.parent / "support" / ".." / "perf"
    assert unresolved != PERF_DIR, "the case under test needs a path that is not `==`"
    assert unresolved.resolve() == PERF_DIR

    assert pytest_ignore_collect(unresolved, _Config("not live")) is True


@pytest.mark.parametrize(
    "relative",
    [
        pytest.param("unit", id="sibling-directory"),
        pytest.param("perf/test_rms_perf.py", id="file-inside-perf"),
    ],
)
def test_other_paths_are_left_alone(relative: str) -> None:
    """The hook ignores the perf *directory* and decides nothing else.

    The file case is deliberate: naming a perf module explicitly
    (`uv run pytest tests/perf/test_rms_perf.py`) is neither the default run nor CI, so it
    keeps working; it is the directory walk that the default run must never descend.
    """
    path = Path(PERF_DIR.parent / relative)
    assert pytest_ignore_collect(path, _Config("not live")) is None


def test_simulation_directory_is_resolved() -> None:
    assert SIMULATION_DIR == Path(__file__).resolve().parents[1] / "simulation"
    assert SIMULATION_DIR == SIMULATION_DIR.resolve()


@pytest.mark.parametrize(
    "markexpr",
    [
        pytest.param("", id="bare-run"),
        pytest.param("not live", id="default-run"),
        pytest.param("not live and not raycast", id="ci-run"),
        pytest.param("perf", id="perf-run"),
    ],
)
def test_simulation_directory_is_ignored_when_the_marker_expression_does_not_name_simulation(
    markexpr: str,
) -> None:
    assert pytest_ignore_collect(SIMULATION_DIR, _Config(markexpr)) is True


def test_simulation_directory_is_collected_when_the_run_asks_for_the_marker() -> None:
    assert pytest_ignore_collect(SIMULATION_DIR, _Config("simulation")) is None


def test_an_unresolved_path_to_the_simulation_directory_is_still_ignored() -> None:
    unresolved = SIMULATION_DIR.parent / "support" / ".." / "simulation"
    assert unresolved != SIMULATION_DIR, "the case under test needs a path that is not `==`"
    assert unresolved.resolve() == SIMULATION_DIR

    assert pytest_ignore_collect(unresolved, _Config("not live")) is True


def test_perf_directory_is_still_ignored_when_the_run_asks_for_simulation() -> None:
    assert pytest_ignore_collect(PERF_DIR, _Config("simulation")) is True


def test_simulation_marker_is_registered_once() -> None:
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    with pyproject.open("rb") as stream:
        markers = tomllib.load(stream)["tool"]["pytest"]["ini_options"]["markers"]
    assert len([marker for marker in markers if marker.startswith("simulation:")]) == 1
