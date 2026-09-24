"""The runbook points at the current handover, which names every open seat task (011 T099).

The seat-readiness review of 2026-09-23 found the runbook sending the operator to the 2026-09-20
round while the seat tasks of features 008 to 011 sat in four `tasks.md` files with no ordered
script. `docs/workstation-handover-2026-09-23.md` is that script; these hold the runbook to the
newest handover in `docs/`, and that handover to every open `[W]` task of the four packages, so a
seat task added later fails here until the handover says where it goes in the sitting.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
DOCS = REPO / "docs"
PACKAGES = (
    "008-checks-first-review",
    "009-engineer-workspace",
    "010-mechanical-checks",
    "011-drawing-context",
)
OPEN_SEAT_TASK = re.compile(r"^- \[ \] (T\d{3}) \[W\]", re.MULTILINE)
TASK_ID = re.compile(r"\bT(\d{3})\b")
TASK_RANGE = re.compile(r"\bT(\d{3}) to T(\d{3})\b")


def newest_handover() -> Path:
    return max(DOCS.glob("workstation-handover-*.md"), key=lambda path: path.name)


def open_seat_tasks(package: str) -> list[str]:
    text = (REPO / "specs" / package / "tasks.md").read_text(encoding="utf-8")
    return OPEN_SEAT_TASK.findall(text)


def named_tasks(text: str) -> set[str]:
    """Every task id the text names, a range `T103 to T106` counting each id in it."""
    named = {f"T{number}" for number in TASK_ID.findall(text)}
    for first, last in TASK_RANGE.findall(text):
        named |= {f"T{number:03d}" for number in range(int(first), int(last) + 1)}
    return named


def test_the_runbook_points_at_the_newest_handover() -> None:
    runbook = (DOCS / "workstation-runbook.md").read_text(encoding="utf-8")
    pointer = runbook[runbook.index("**The current work for this machine**") :]
    pointer = pointer[: pointer.index("\n\n")]

    assert f"`docs/{newest_handover().name}`" in pointer
    assert newest_handover().name == "workstation-handover-2026-09-23.md"


def test_the_handover_names_every_open_seat_task_of_features_008_to_011() -> None:
    handover = newest_handover().read_text(encoding="utf-8")
    named = named_tasks(handover)

    for package in PACKAGES:
        tasks = open_seat_tasks(package)
        assert tasks, package
        missing = [task for task in tasks if task not in named]
        assert missing == [], f"{package}: {missing}"
        assert package[:3] in handover


def test_a_range_names_each_task_in_it() -> None:
    assert named_tasks("010 T103 to T106, and T079") == {"T103", "T104", "T105", "T106", "T079"}
