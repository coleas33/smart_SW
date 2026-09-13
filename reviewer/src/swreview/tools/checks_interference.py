"""The interference check tool (T068).

`list_interferences` and `get_exceptions` are query tools and live in
`swreview.tools.query`; this module holds the third tool of that group, the one that
produces a finding. SOLIDWORKS did the detection - nothing here recomputes an overlap -
so what the tool adds is the three things US3 asks of the reviewer:

- **one condition, one finding.** A screw pattern that interferes six times is one group
  and one finding naming all six pairs (FR-011). The grouping is
  `swreview.checks.interference.group_interferences`; the model addresses a group by the
  `group_key` `list_interferences` printed.
- **exceptions bind to geometry.** An `active` exception matching these components in
  this configuration makes the group `checked_within_scope` with the exception cited; one
  whose geometry has moved is `needs_review` and does not clear anything (FR-013).
- **an uncomputed pair is never a pass.** A `truncated` or `failed` member makes the
  finding `unresolved` *and* writes the unresolved coverage item for each such pair, so
  the pair shows up in the report's coverage as well as in the finding (FR-019).
"""

from __future__ import annotations

from swreview.checks import interference as interference_check
from swreview.checks.interference import InterferenceGroup
from swreview.ir.models import EvidencePackage
from swreview.tools.context import ToolContext, current_context, error_result
from swreview.tools.query import ToolResult, as_json
from swreview.tools.recording import record_result

__all__ = ["check_interference_group", "groups_of"]


def groups_of(package: EvidencePackage) -> list[InterferenceGroup]:
    """Every interference in `package`, collapsed into one group per condition."""
    return interference_check.group_interferences(package)


def _select(
    context: ToolContext, groups: list[InterferenceGroup], group_key: str
) -> InterferenceGroup | ToolResult:
    """The one group `group_key` names, or an error result explaining why it is not one.

    A group key can repeat across configurations - the same pair interfering in two of
    them is two conditions. The active configuration wins, because that is the one the
    review is running against; anything still ambiguous is refused rather than guessed.
    """
    matches = [group for group in groups if group.group_key == group_key]
    if not matches:
        known = sorted({group.group_key for group in groups})
        return error_result(
            f"no interference group {group_key!r} in this package; "
            f"`list_interferences` reports {known}"
        )
    if len(matches) == 1:
        return matches[0]

    active = context.ir.design.active_configuration
    in_active = [group for group in matches if group.configuration == active]
    if len(in_active) == 1:
        return in_active[0]
    return error_result(
        f"interference group {group_key!r} exists in more than one configuration "
        f"({sorted(group.configuration for group in matches)}); re-run detection per "
        "configuration so the finding can say which one it is about"
    )


def check_interference_group(group_key: str) -> ToolResult:
    """The verdict on one grouped interference condition, honoring retained exceptions.

    `group_key` is the key `list_interferences` prints. Every pair in the group is one
    condition: the finding names them all rather than repeating itself once per pair.

    A group with an overlap volume is `demonstrated` - the overlap is a fact SOLIDWORKS
    computed. A group SOLIDWORKS reported as coincident or touching, with no volume, is
    `suspected`. A group with a truncated or failed pair is `unresolved` and each such
    pair is also written into the session's unresolved coverage: nothing is known about
    them, and an exception cannot speak for a pair that was never evaluated.

    An exception accepted for exactly these components in this configuration clears the
    group and is cited on the finding; one whose geometry or configuration has since
    changed leaves the finding standing and says so.

    Args:
        group_key: The interference group to judge, from `list_interferences`.
    """
    context = current_context()
    selected = _select(context, groups_of(context.ir), group_key)
    if isinstance(selected, dict):
        return selected

    store = context.exception_store()
    result = interference_check.check_interference_group(selected, context.ir, store)

    exception = (
        None
        if store is None
        else store.match(context.ir, selected.component_ids, selected.configuration)
    )
    recorded = record_result(
        context,
        result,
        component_ids=selected.component_ids,
        exception_id=None if exception is None else exception.id,
    )
    if "error" in recorded:
        return recorded

    coverage = interference_check.run_coverage(context.ir, selected.interferences)
    context.session.coverage.unresolved.extend(coverage)
    return {
        **recorded,
        "group_key": selected.group_key,
        "configuration": selected.configuration,
        "members": len(selected.interferences),
        "pairs": selected.pairs,
        "coverage": len(coverage),
        "exception": None if exception is None else as_json(exception),
    }
