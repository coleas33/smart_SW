"""The open seat tasks of every feature package, and the task ids a document names (011 T099,
T100; 013 T138; 014 T221; 015 T113; 004 T360).

`docs/test-plan-2026-09-27/workstation-handover.md` (T099) and
`docs/test-plan-2026-09-27/workstation-test-plan.md`
(T100) each name every open `[W]` task of the seven packages, so a seat result maps back to its row
of a `tasks.md`; feature 013 joined them on 2026-09-27 (013 T138), with its four seat tasks, 013
T141 to T144, and a fifth, 013 T153, with its follow-ups the same day. Feature 015 joined them on
2026-10-14 (015 T113), with its seat task, 015 T119. Feature 014 joined them on 2026-10-17
(014 T221's development-machine half), with its seat task, 014 T221. One reader of the task
lists and one reader of a document's ids serve both tests.

Task ids repeat across packages (`008 T101` and `011 T101` are different tasks), so the plan is
read with the package in front of each id (`qualified_tasks`). *Changed 2026-10-31 on review (004
T373):* so is the handover; its older, unqualified reading (`named_tasks`) let 001 T103 leave it
with its pin green, since `008 T102 and T103` names a T103 too, and is gone.

*Widened 2026-10-31 (owner decision 166A; 004 T360):* every feature package is read, since 004
T303 (`[W]`) drifted out of the plan while 004 was not among the seven. A seat task is an open
task tagged `[W]` among its leading tags (005's `[P] [W]`, `[W] [K]`), or one whose text after its
tags begins `Workstation`, the way features 003 and 004 say it; and an id may end in one letter
(`005 T085a`, `004 T303a`), read whole.
"""

from __future__ import annotations

import re
from pathlib import Path

__all__ = [
    "PACKAGES",
    "REPO",
    "open_seat_tasks",
    "qualified_tasks",
    "seat_tasks_in",
]

REPO = Path(__file__).resolve().parents[3]
PACKAGES = (
    "001-agentic-design-review",
    "002-task-pane-assistant",
    "003-resilient-modeling",
    "004-resilient-remodeler",
    "005-llm-efficiency",
    "006-standards-check",
    "007-attention-policy-gate",
    "008-checks-first-review",
    "009-engineer-workspace",
    "010-mechanical-checks",
    "011-drawing-context",
    "013-engineer-first-review",
    "014-design-review-eval",
    "015-review-send-gate",
    "016-engineering-context",
)
OPEN_TASK = re.compile(r"^- \[ \] (T\d{3}[a-z]?)((?: \[[^\]\n]*\])*) ?(.*)$", re.MULTILINE)
"""An open task: its id, its leading tags (` [P] [W] [L9]`) and the text after them."""
QUALIFIED_ID = re.compile(r"\b(\d{3}) T(\d{3}[a-z]?)\b")
QUALIFIED_RANGE = re.compile(r"\b(\d{3}) T(\d{3}) to T(\d{3})\b")


def seat_tasks_in(text: str) -> list[str]:
    """The ids of the open seat tasks of a `tasks.md` text, in its order: `[W]` among a task's
    leading tags, or its text after them beginning `Workstation`."""
    return [
        task
        for task, tags, rest in OPEN_TASK.findall(text)
        if "[W]" in tags.split() or rest.startswith("Workstation")
    ]


def open_seat_tasks(package: str) -> list[str]:
    """The ids of `package`'s open seat tasks, in the order its `tasks.md` lists them."""
    return seat_tasks_in((REPO / "specs" / package / "tasks.md").read_text(encoding="utf-8"))


def qualified_tasks(text: str) -> set[tuple[str, str]]:
    """Every `(package number, task id)` the text names as `011 T062`, a range `010 T103 to T106`
    counting each id in it. An id with no package number in front of it names nothing here."""
    named = {(package, f"T{number}") for package, number in QUALIFIED_ID.findall(text)}
    for package, first, last in QUALIFIED_RANGE.findall(text):
        named |= {(package, f"T{number:03d}") for number in range(int(first), int(last) + 1)}
    return named
