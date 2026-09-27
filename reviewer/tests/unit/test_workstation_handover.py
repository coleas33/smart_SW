"""The runbook points at the current handover, which names every open seat task (011 T099).

The seat-readiness review of 2026-09-23 found the runbook sending the operator to the 2026-09-20
round while the seat tasks of features 008 to 011 sat in four `tasks.md` files with no ordered
script. `docs/test-plan-2026-09-27/workstation-handover.md` is that script; these hold the
runbook to the newest handover in `docs/`, and that handover to every open `[W]` task of
the four packages, so a seat task added later fails here until the handover says where it goes
in the sitting.
"""

from __future__ import annotations

from pathlib import Path

from tests.support.seat_tasks import PACKAGES, REPO, named_tasks, open_seat_tasks

DOCS = REPO / "docs"


def newest_handover() -> Path:
    """The handover of the newest dated test-plan folder (`docs/test-plan-<date>/`).

    Since 2026-09-27 each sitting's plan, results sheet and handover live together in one folder
    named by its date, so the testing machine finds the current one by the folder alone.
    """
    return max(DOCS.glob("test-plan-*/workstation-handover.md"), key=lambda path: path.parent.name)


def test_the_runbook_points_at_the_newest_handover() -> None:
    runbook = (DOCS / "workstation-runbook.md").read_text(encoding="utf-8")
    pointer = runbook[runbook.index("**The current work for this machine**") :]
    pointer = pointer[: pointer.index("\n\n")]

    relative = newest_handover().relative_to(REPO).as_posix()
    assert f"`{relative}`" in pointer
    assert relative == "docs/test-plan-2026-09-27/workstation-handover.md"


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
