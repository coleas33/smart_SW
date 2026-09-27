"""Generate the sitting-shaped fixture feature 013 reads (T012).

Run from `reviewer/` and commit what it writes:

    uv run python tests/fixtures/sitting/generate_fixture.py

`tests/unit/test_sitting_fixture_is_fictional.py` re-runs `render()` and compares every byte
with the tree, so the fixture is changed in `tests/support/sitting.py`, regenerated and
committed - never edited by hand. Nothing here comes from a recorded package: the builder
composes fictional strings in the shape the 2026-09-26 sitting showed.
"""

from __future__ import annotations

import sys
from pathlib import Path

FIXTURE_DIR = Path(__file__).resolve().parent / "small-assembly"
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tests.support.sitting import render  # noqa: E402


def main() -> None:
    for relative, content in render().items():
        path = FIXTURE_DIR / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        print(f"wrote {path.relative_to(FIXTURE_DIR.parents[2])} ({len(content)} bytes)")


if __name__ == "__main__":
    main()
