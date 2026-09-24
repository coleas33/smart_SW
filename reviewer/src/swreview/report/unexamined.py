"""Which component instances a run never read, said once and said early.

The pilot workstation graded the small assembly, the dowel-pin one, three times on 2026-09-19
with both pins lightweight. Live interference found nothing where the day before it had
found two clashes, twenty coverage rows said "lightweight; tree not read", and no headline
said that the two components the assembly exists to locate had never been examined
(`docs/feature-request-resolve-lightweight.md`). The extractor never resolves an instance -
resolving changes the engineer's session, and the reviewer reads the session as found - so
the honest answer is to say so where it will be read: the report's Summary, both check
bodies, and the pane's status line before a review spends a token.

This module is the one place the sentence is composed, so the three surfaces cannot drift.
It reads the package alone: `ComponentInstance.suppression` is what the extractor recorded,
and an instance in any state but `resolved` contributed no geometry, no holes, no feature
tree and no Toolbox identity to the run.
"""

from __future__ import annotations

from swreview.findings import ReviewModel
from swreview.ir.models import ComponentInstance, EvidencePackage
from swreview.report.names import and_list

__all__ = [
    "CANNOT_SEE",
    "READ_STATE",
    "NotExamined",
    "UnexaminedInstance",
    "not_examined",
    "unexamined_instances",
]

READ_STATE = "resolved"
"""The one suppression state under which the extractor read the instance's document."""

CANNOT_SEE = "Interference, fit and the feature-tree rules cannot see them."
"""What the reader loses, in the families' own names, so the sentence says the cost and
not only the fact."""


class UnexaminedInstance(ReviewModel):
    """One instance the run did not read: which, called what, and in which state."""

    id: str
    name: str
    state: str


class NotExamined(ReviewModel):
    """The sentence every surface prints, and the instances behind it in package order.

    `headline` is the same fact with names and no ids, for the Review tab's warning
    (feature 009 research R2.8); `sentence` keeps the ids for `report.md` and both check
    bodies, which print it.
    """

    sentence: str
    headline: str
    instances: list[UnexaminedInstance]


def unexamined_instances(package: EvidencePackage) -> list[ComponentInstance]:
    """The instances whose suppression state is anything but `resolved`, in package order.

    Package order rather than any sort: the list restates what the extractor recorded and
    puts nothing before anything.
    """
    return [instance for instance in package.components if instance.suppression != READ_STATE]


def not_examined(package: EvidencePackage) -> NotExamined | None:
    """The block the surfaces print, or `None` when every instance was read.

    `None` rather than an empty block, because a run that read everything has nothing to
    warn about and a surface that printed "0 of 4 were not read" would be a line the eye
    learns to skip. Each instance is named with its state, since a suppressed instance is a
    choice the engineer made and a lightweight one is usually not.
    """
    instances = unexamined_instances(package)
    if not instances:
        return None

    total = len(package.components)
    count = len(instances)
    named = ", ".join(
        f"{instance.name} {instance.id} ({instance.suppression})" for instance in instances
    )
    verb = "was" if count == 1 else "were"
    sentence = f"{count} of {total} component instances {verb} not read: {named}. {CANNOT_SEE}"
    headline = (
        f"{count} of {total} parts {verb} not loaded: {_names_by_state(instances)}. {CANNOT_SEE}"
    )
    return NotExamined(
        sentence=sentence,
        headline=headline,
        instances=[
            UnexaminedInstance(id=instance.id, name=instance.name, state=instance.suppression)
            for instance in instances
        ],
    )


def _names_by_state(instances: list[ComponentInstance]) -> str:
    """Names only, one group per state in the order the states first appear, each group's
    names in package order: `Pin-A-1 and Pin-B-1 (lightweight), Plate-1 (suppressed)`."""
    by_state: dict[str, list[str]] = {}
    for instance in instances:
        by_state.setdefault(instance.suppression, []).append(instance.name)
    return ", ".join(f"{and_list(names)} ({state})" for state, names in by_state.items())
