"""The open seat tasks of features 008 to 011, and the task ids a document names (011 T099, T100).

`docs/workstation-handover-2026-09-23.md` (T099) and `docs/workstation-test-plan-2026-09-23.md`
(T100) each name every open `[W]` task of the four packages, so a seat result maps back to its row
of a `tasks.md`. One reader of the task lists and one reader of a document's ids serve both tests.

Task ids repeat across packages (`008 T101` and `011 T101` are different tasks), so the plan is
read with the package in front of each id (`qualified_tasks`); the handover's older, unqualified
reading (`named_tasks`) is kept as it was.
"""

from __future__ import annotations

import re
from pathlib import Path

__all__ = [
    "PACKAGES",
    "REPO",
    "named_tasks",
    "open_seat_tasks",
    "qualified_tasks",
]

REPO = Path(__file__).resolve().parents[3]
PACKAGES = (
    "008-checks-first-review",
    "009-engineer-workspace",
    "010-mechanical-checks",
    "011-drawing-context",
)
OPEN_SEAT_TASK = re.compile(r"^- \[ \] (T\d{3}) \[W\]", re.MULTILINE)
TASK_ID = re.compile(r"\bT(\d{3})\b")
TASK_RANGE = re.compile(r"\bT(\d{3}) to T(\d{3})\b")
QUALIFIED_ID = re.compile(r"\b(\d{3}) T(\d{3})\b")
QUALIFIED_RANGE = re.compile(r"\b(\d{3}) T(\d{3}) to T(\d{3})\b")


def open_seat_tasks(package: str) -> list[str]:
    """The ids of `package`'s open `[W]` tasks, in the order its `tasks.md` lists them."""
    text = (REPO / "specs" / package / "tasks.md").read_text(encoding="utf-8")
    return OPEN_SEAT_TASK.findall(text)


def named_tasks(text: str) -> set[str]:
    """Every task id the text names, a range `T103 to T106` counting each id in it."""
    named = {f"T{number}" for number in TASK_ID.findall(text)}
    for first, last in TASK_RANGE.findall(text):
        named |= {f"T{number:03d}" for number in range(int(first), int(last) + 1)}
    return named


def qualified_tasks(text: str) -> set[tuple[str, str]]:
    """Every `(package number, task id)` the text names as `011 T062`, a range `010 T103 to T106`
    counting each id in it. An id with no package number in front of it names nothing here."""
    named = {(package, f"T{number}") for package, number in QUALIFIED_ID.findall(text)}
    for package, first, last in QUALIFIED_RANGE.findall(text):
        named |= {(package, f"T{number:03d}") for number in range(int(first), int(last) + 1)}
    return named
