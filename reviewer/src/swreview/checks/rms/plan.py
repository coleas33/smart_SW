"""The suppress-test plan: which features the extractor may suppress (T053).

`specs/003-resilient-modeling/data-model.md` section 2 defines `SuppressPlan`, and
`contracts/cli.md` says why it exists: `suppress-test` is the one mutation path in this
product, so the decision *what to mutate* is made here, in the reviewer, from the group
assigner and the type table - the extractor never decides folders, groups or content.
It opens the features this file names, in this order, and nothing else.

Two consequences shape the module:

- **nothing is re-derived.** The Detail group and the content set come from
  `part.part_tree`, which is the same `assign_groups` plus `RmsTypeTable` pair every rule
  reads, so `rms.detail.individually_suppressible` grades exactly the set that was
  planned (`contracts/rules.md`, suppress-test outcome table) and the two can never drift
  apart. In particular the group is sticky, not structural, and both traversal shapes of
  `IFeatureManager` plan the same features;
- **there is no empty-plan-by-accident.** A document whose tree was never dumped, and a
  document with no Detail group, raise instead of writing a plan with no features: an
  empty plan reads to the extractor as "nothing to suppress" and to the rule as a part
  with nothing to test, and neither is what "we never looked" means (constitution
  Principle I). A Detail group that genuinely holds no content feature is a different
  statement and does write an empty plan.

`configuration` is the *review* configuration (`contracts/cli.md`), not the configuration
the document's own rows were read in. The extractor refuses to run when the open
document's active configuration differs from it, and the rule refuses to read a run whose
configuration differs from the review's - so writing the review's configuration here is
what makes a suppress-test either apply to the review that asked for it or be refused,
never quietly answer a question about some other configuration.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from swreview.checks.rms.groups import assign_groups
from swreview.checks.rms.part import DETAIL, part_tree
from swreview.checks.rms_types import RmsTypeTable
from swreview.ir.models import EvidencePackage

__all__ = ["PLAN_FILE_NAME", "PlannedFeature", "SuppressPlan", "build_plan"]

PLAN_FILE_NAME = "suppress-plan.json"
"""Where `swreview rms suppress-plan` writes by default: beside `package.json`."""


@dataclass(frozen=True)
class PlannedFeature:
    """One feature the extractor may suppress, in the five fields it resolves it by.

    `persist_ref` plus `persist_ref_scope` is the identity that survives a rebuild;
    `feature_id` is how the run's rows point back at the package, and `name` and
    `type_name` are what the extractor compares its live walk against before it touches
    anything (`contracts/cli.md`, `suppress-test`).
    """

    feature_id: str
    persist_ref: str
    persist_ref_scope: str
    name: str
    type_name: str


@dataclass(frozen=True)
class SuppressPlan:
    """The plan for one part document (`data-model.md` section 2)."""

    document_id: str
    configuration: str
    group: str
    """The Detail group's name as the type table spells it, e.g. `4-Detail`."""

    features: tuple[PlannedFeature, ...]
    """The Detail content features in tree order; the order the extractor tests them in."""

    def as_dict(self) -> dict[str, Any]:
        """The plan as the JSON file the C# command reads."""
        return asdict(self)


def build_plan(
    package: EvidencePackage, document_id: str, table: RmsTypeTable
) -> SuppressPlan:
    """The suppress-test plan for one part document of `package`.

    Raises:
        ValueError: when `document_id` has no `features[]` rows in this package (its tree
            was never dumped, or it is not a part), or when its tree has no Detail group.
    """
    rows = [row for row in package.features if row.document_id == document_id]
    if not rows:
        dumped = sorted({row.document_id for row in package.features})
        raise ValueError(
            f"{document_id} has no features[] rows in this package, so there is nothing "
            f"to plan; documents whose feature tree was read: {dumped or 'none'}"
        )

    tree = part_tree(document_id, rows, table, assign_groups(rows, table), package)
    group = tree.group_name(DETAIL)
    if not tree.has_group(DETAIL):
        raise ValueError(
            f"{document_id} has no {group} group folder, so the suppress-test has no "
            f"features to test; groups present: {sorted(tree.groups_present) or 'none'}"
        )

    return SuppressPlan(
        document_id=document_id,
        configuration=package.design.active_configuration,
        group=group,
        features=tuple(
            PlannedFeature(
                feature_id=row.id,
                persist_ref=row.persist_ref,
                persist_ref_scope=row.persist_ref_scope,
                name=row.name,
                type_name=row.type_name,
            )
            for row in tree.in_group(DETAIL)
        ),
    )
