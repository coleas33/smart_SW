"""The per-part row of the plan summary, and the human lines that print it (T134b).

`swreview remodel plan --json` prints this row and `POST /remodel/plan` answers the pane
with it, so it is built once, here, and both callers import it. It lived in `cli.py` while
the CLI was its only caller; a copy for the backend would be a second answer to "what does
this part's row say", and the remodel-plan goldens pin only one of them.

Nothing here decides anything or reads anything: it is a pure rendering of a `RemodelPlan`
the planner already produced, which is why it writes no file, takes no clock and never
constructs a provider.
"""

from __future__ import annotations

from typing import Any

from swreview.remodel.feasibility import REBUILD_REASONS
from swreview.remodel.plan import RemodelPlan, non_contiguous_groups

__all__ = ["plan_lines", "plan_refusals", "plan_summary_row"]


def plan_refusals(plan: RemodelPlan) -> list[dict[str, str]]:
    """Every reason this part is refused, never only the first (`research.md` R4.1).

    Three sources, one vocabulary: the scope gate's own codes, the folder plan's
    `rms_named_folder_wrong_members`, and a dependency cycle, which has no legal order and
    is therefore a refusal rather than a plan with nothing in it.
    """
    refusals = [
        {"code": refusal.code, "signal": refusal.signal, "message": refusal.message}
        for refusal in plan.scope.refusals
        if refusal.code != "signal_unresolved"
    ]
    refusals += [
        {
            "code": refusal.reason,
            "signal": refusal.name,
            "message": (
                f"the folder {refusal.name} ({refusal.existing_folder_id}) holds "
                f"{len(refusal.actual_member_ids)} feature(s) where the method puts "
                f"{len(refusal.expected_member_ids)}; this version has no dissolve path, "
                "so the part is refused before anything is copied"
            ),
        }
        for refusal in plan.folders.refusals
    ]
    if plan.order.cycle is not None:
        refusals.append(
            {
                "code": "cycle",
                "signal": "parent_ids",
                "message": (
                    "the dependency graph has a cycle through "
                    f"{', '.join(plan.order.cycle)}, so no legal order exists"
                ),
            }
        )
    return refusals


def plan_summary_row(plan: RemodelPlan, document: Any, table: Any) -> dict[str, Any]:
    """One part's dry-run numbers, as `plan.md` point 10 asks for them.

    "Reaching its target group" is counted as: a content feature the planner resolved a
    group for, that no dependency edge pins away from the position the method wants, and
    that is on no rebuild list. Each of the three exclusions is a reason the report already
    prints, so the count can always be taken apart again - which is what makes it a
    measurement rather than a score.
    """
    pinned = {pin.feature_id for pin in plan.pins}
    rebuilt = {entry.feature_id for entry in plan.rebuild}
    content = [item for item in plan.targets if item.state != "not_content"]
    reaching = [
        item.feature_id
        for item in content
        if item.state == "resolved"
        and item.feature_id not in pinned
        and item.feature_id not in rebuilt
    ]
    by_reason = {reason: 0 for reason in REBUILD_REASONS}
    for entry in plan.rebuild:
        by_reason[entry.reason] += 1

    return {
        "document_id": plan.document_id,
        "file_name": document.file_name,
        "state": plan.state,
        "configuration": plan.configuration,
        "content_features": len(content),
        "reaching_target_group": len(reaching),
        "reorganizable_fraction": {
            "reaching": len(reaching),
            "of": len(content),
            "value": (len(reaching) / len(content)) if content else None,
            "measurement": (
                "content features that reach their target group: resolved, unpinned and "
                "not on the rebuild list. Null when this document has no content feature, "
                "because a fraction of nothing is not 1.0"
            ),
        },
        "move_count": plan.order.move_count,
        "changes": len(plan.changes),
        "renames": len(plan.renames),
        "pins": [
            {
                "feature_id": pin.feature_id,
                "desired_index": pin.desired_index,
                "achievable_index": pin.achievable_index,
                "blocking_edge": {
                    "parent_id": pin.blocking_edge.parent_id,
                    "child_id": pin.blocking_edge.child_id,
                },
                "reason": pin.reason,
            }
            for pin in plan.pins
        ],
        "non_contiguous": [
            {
                "group": item.item,
                "interloper_feature_ids": list(item.feature_ids),
                "reason": item.reason,
            }
            for item in non_contiguous_groups(plan, table)
        ],
        "rebuild": [
            {
                "feature_id": entry.feature_id,
                "name": entry.name,
                "reason": entry.reason,
                "detail": entry.detail,
                "blocking_edge": (
                    None
                    if entry.blocking_edge is None
                    else {
                        "parent_id": entry.blocking_edge.parent_id,
                        "child_id": entry.blocking_edge.child_id,
                    }
                ),
            }
            for entry in plan.rebuild
        ],
        "rebuild_by_reason": by_reason,
        "folders": {
            "create": len(
                [action for action in plan.folders.actions if action.status == "planned"]
            ),
            "no_op": len(
                [action for action in plan.folders.actions if action.status == "no_op"]
            ),
        },
        "scope": {
            "verdict": plan.scope.verdict,
            "notes": list(plan.scope.notes),
        },
        "refusals": plan_refusals(plan),
        "coverage": [
            {"item": item.item, "reason": item.reason, "feature_ids": list(item.feature_ids)}
            for item in plan.coverage
        ],
    }


def plan_lines(row: dict[str, Any]) -> list[str]:
    """One part's numbers as the engineer reads them, the fraction with its denominator."""
    fraction = row["reorganizable_fraction"]
    measured = "n/a" if fraction["value"] is None else f"{fraction['value']:.3f}"
    lines = [
        f"{row['document_id']} {row['file_name']}: {row['state']}",
        f"  {fraction['reaching']} of {fraction['of']} content features reach their "
        f"target group ({measured})",
        f"  {row['move_count']} move(s), {row['renames']} rename(s), "
        f"{row['folders']['create']} folder(s) to create, {row['changes']} change(s)",
        f"  {len(row['pins'])} pinned",
    ]
    lines += [
        f"    {pin['feature_id']}: {pin['reason']} "
        f"({pin['blocking_edge']['parent_id']} -> {pin['blocking_edge']['child_id']})"
        for pin in row["pins"]
    ]
    lines += [
        f"  non-contiguous {item['group']}: {item['reason']}"
        for item in row["non_contiguous"]
    ]
    lines.append(
        "  rebuild "
        + str(len(row["rebuild"]))
        + ": "
        + (
            ", ".join(
                f"{reason} x{count}"
                for reason, count in row["rebuild_by_reason"].items()
                if count
            )
            or "none"
        )
    )
    lines += [
        f"    {entry['name']}: {entry['reason']} - {entry['detail']}"
        for entry in row["rebuild"]
    ]
    lines += [
        f"  refused {refusal['code']} ({refusal['signal']}): {refusal['message']}"
        for refusal in row["refusals"]
    ]
    return lines
