"""T066's flip of `DRAWING_BINDING_VALIDATED` is one edit and one pin (feature 011 T096).

The seat task T066 ends with the switch set true on the development machine, in a commit of its
own. That commit can pass the gate only if exactly one test reads the shipped value -
`test_drawing_binding.test_the_switch_ships_off`, which the commit edits deliberately - and every
test of the switch-off behaviour sets the switch off itself (the `not_validated` fixture in
`tests/conftest.py`) rather than relying on the default. The review of 2026-09-23 found thirteen
that relied on it.

So this runs, in a child pytest with the switch turned on for the whole run
(`tests/support/flip_binding.py`), every unit test module that names the switch or its sentence,
and expects that one failure and no other. A new switch-off test that reads the shipped value
fails here, before the seat's flip does.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

REVIEWER = Path(__file__).resolve().parents[2]
UNIT = REVIEWER / "tests" / "unit"

THE_PIN = "tests/unit/test_drawing_binding.py::test_the_switch_ships_off"
"""The one test that reads the shipped value: T066's red-by-design edit."""

NAMES = ("DRAWING_BINDING_VALIDATED", "NOT_VALIDATED", "not_validated")


def modules_naming_the_switch() -> list[str]:
    """Every unit test module that names the switch, its sentence or its fixture, this one aside."""
    this = Path(__file__).resolve()
    return sorted(
        path.relative_to(REVIEWER).as_posix()
        for path in UNIT.glob("test_*.py")
        if path.resolve() != this
        and any(name in path.read_text(encoding="utf-8") for name in NAMES)
    )


def test_the_modules_that_name_the_switch_are_found() -> None:
    found = modules_naming_the_switch()

    assert "tests/unit/test_drawing_binding.py" in found
    assert "tests/unit/test_tools_native_drawing.py" in found
    assert len(found) >= 6


def test_with_the_switch_flipped_only_the_pin_fails() -> None:
    environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    completed = subprocess.run(
        [
            sys.executable, "-m", "pytest", "-q", "-rf", "-p", "no:cacheprovider",
            "-p", "no:warnings", "-o", "addopts=", "-p", "tests.support.flip_binding",
            *modules_naming_the_switch(),
        ],
        cwd=REVIEWER,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
        check=False,
    )
    failed = sorted(set(re.findall(r"^FAILED (\S+?)(?: - |$)", completed.stdout, re.MULTILINE)))
    errors = re.findall(r"^ERROR (\S+)", completed.stdout, re.MULTILINE)

    assert errors == [], completed.stdout[-4000:]
    assert failed == [THE_PIN], completed.stdout[-4000:]
