"""Generate the `standards-profile-a` golden: half of SC-005's matched pair (T098).

Run once, from `reviewer/`, and commit what it writes:

    uv run python tests/golden/fixtures/standards-profile-a/generate_package.py

The design lives in `tests/checks/matched_pair.py` and is built twice, once for each
fictional profile; this script says which profile this package is written for and nothing
else. Graded against `profile-a.yaml`, it must produce the same sixteen coverage rows and
the same findings by check id as `standards-profile-b` graded against `profile-b.yaml`
(quickstart Scenario 6, `tests/golden/test_standards_goldens.py`).
"""

from __future__ import annotations

import sys
from pathlib import Path

FIXTURE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(FIXTURE_DIR.parents[3]))

from tests.checks.matched_pair import matched_package  # noqa: E402
from tests.checks.standards_fixtures import fixture_profile, write_fixture  # noqa: E402

PROFILE_NAME = "profile-a"


def main() -> None:
    write_fixture(FIXTURE_DIR, matched_package(fixture_profile(PROFILE_NAME)), PROFILE_NAME)


if __name__ == "__main__":
    main()
