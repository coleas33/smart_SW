"""What the four standards goldens are written by (T053 to T056).

Each `tests/golden/fixtures/standards-*/generate_package.py` says what its own package
contains and nothing else; the three things all four of them do - read the fictional
profile, fill a data card from it, and write `package.json` beside a `case.json` pointing
at `golden_standards:standards_case` - are here once (constitution Principle V).

**No company value is written here or in any generator.** Every data-card property name,
the part-number convention, the revision property and the export-control phrase are read
off the fixture profile, which is fictional in every field (FR-001, T002). A fixture that
spelled one of them out would be a second copy of the profile, free to disagree with it.

`card` is written in `tests/support/standards.py` since feature 014 (GN-3) and re-exported
here, so no generator changed: this module imports the standards check run through
`golden_standards`, which the benchmark case generator, also a `card` caller, may not load.
"""

from __future__ import annotations

import json
from pathlib import Path

from swreview.checks.standards.profile import StandardsProfile, load_profile
from swreview.ir.loader import save_package
from swreview.ir.models import EvidencePackage
from tests.checks.golden_standards import DEFAULT_PROFILE, PROFILE_DIR
from tests.support.standards import card

__all__ = ["CASE_CALLABLE", "card", "fixture_profile", "write_fixture"]

CASE_CALLABLE = "tests.checks.golden_standards:standards_case"
"""What every `standards-*` case runs: the one evaluation entry point, through its adapter."""


def fixture_profile(name: str = DEFAULT_PROFILE) -> StandardsProfile:
    """The fictional profile a fixture is written for and graded against."""
    return load_profile(PROFILE_DIR / f"{name}.yaml")


def write_fixture(
    directory: Path, package: EvidencePackage, profile_name: str = DEFAULT_PROFILE
) -> None:
    """Write `package.json` and the `case.json` the golden harness reads beside it."""
    save_package(package, directory)
    case = {"callable": CASE_CALLABLE, "kwargs": {"profile": profile_name}}
    (directory / "case.json").write_text(json.dumps(case, indent=2) + "\n", encoding="utf-8")
    print(f"wrote package.json and case.json in {directory}")
