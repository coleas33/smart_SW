"""The catastrophic fallback: delete the copy, re-copy the source, replay (T085).

`data-model.md` section 2.2 names three undo tiers and this module is the second. Tier 1 is
the per-change forward inverse in `apply.py`, which is the primary because it lets a run
carry on past one bad change. Tier 2 is here, for the change kinds tier 1 has no inverse
for - `folder.create`, because dissolving a folder needs `IModelDoc2.EditDelete` and the
owner kept it off the stage-1 allowlist. **Tier 3 does not exist**: the document's own undo
member returns void, so a caller cannot tell whether it did anything, and it shares the undo
stack the engineer can also touch. Nothing here reaches for it, and one test scans the whole
stage-1 surface to say so.

Four properties, each a test:

1. **it is refused, not attempted, when the source moved.** The attestation is re-checked
   *before* the copy is deleted, because a replay re-copies the source and a source that is
   not the attested one would make a copy this run cannot claim anything about. The
   refusal leaves the copy and the log exactly where they were;
2. **it is deterministic.** Every change is addressed by persistent reference, and the
   persistent references of a byte-for-byte re-copy are the ones the original copy had, so
   replaying the applied changes reproduces the tree the run had reached;
3. **it replays what landed.** The changes whose record says `applied`, in `seq` order. A
   change that failed or was rolled back left no mark on the tree, and the change that
   triggered the fallback is not re-attempted - re-attempting the thing that broke the tree
   is the loop this tier exists to avoid;
4. **it never loops.** `replay_run` calls nothing that could call it again. If the replayed
   pass stops the same way - a change that landed, raised the error count and had no inverse
   - the result says so in `escalated_again` and the run finalizes and reports. Twice is
   where it stops.

A replayed change is a **new attempt** and takes the next free `seq`, because
`changes.jsonl` is append-only and a line never rewrites an earlier one. The file therefore
records both attempts, which is what happened; the pair is read by kind and subject, and the
original attempt keeps its own outcome rather than being edited into a lie.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from swreview.bridge.remodel_client import CircuitOpen, RemodelClient
from swreview.remodel.apply import ApplyResult, apply_changes, utc_now
from swreview.remodel.apply_log import ApplyLog, ChangeRecord, changes_path, read_changes
from swreview.remodel.attestation import recheck, require_source_unchanged
from swreview.remodel.plan import Limits, PlannedChange, SourceAttestation

__all__ = [
    "ReplayResult",
    "ReplayUnavailable",
    "applied_changes",
    "replay_run",
]


class ReplayUnavailable(RuntimeError):
    """The fallback could not be started, and nothing was deleted.

    Raised where the bridge refuses to close or to re-open before a single change has been
    replayed. It is distinct from a replay that ran and stopped: this one leaves the run
    exactly as the executor left it, and the caller discards the copy and reports.
    """


@dataclass(frozen=True)
class ReplayResult:
    """What the fallback did.

    `status` is `replayed` when every applied change came back, and `stopped` otherwise.
    `escalated_again` is the one flag worth its own field: the replayed pass ended the way
    the pass that triggered it did, which is the signal to finalize and report rather than
    to fall back a second time.
    """

    status: Literal["replayed", "stopped"]
    replayed: tuple[int, ...]
    apply: ApplyResult
    escalated_again: bool


def applied_changes(
    changes: Sequence[PlannedChange], records: Sequence[ChangeRecord]
) -> tuple[PlannedChange, ...]:
    """The planned changes whose record says `applied`, in `seq` order.

    That set is exactly the tree the run had reached: a `failed` change never landed, a
    `rolled_back` change landed and was taken back, and a `rollback_failed` change is the
    one the fallback exists because of and is never re-attempted.

    Matched by `seq`, which is the plan's `seq` for every line the original pass wrote. A
    replayed line takes a fresh `seq` and therefore matches nothing here, which is correct:
    this is read from the log of the pass that is being replayed, and a replay is never
    itself replayed.
    """
    landed = {record.seq for record in records if record.status == "applied"}
    return tuple(change for change in changes if change.seq in landed)


def replay_run(
    *,
    client: RemodelClient,
    run_dir: Path | str,
    changes: Sequence[PlannedChange],
    attestation: SourceAttestation,
    run_id: str,
    probe_id: str,
    baseline: int,
    limits: Limits,
    now: Callable[[], datetime] = utc_now,
) -> ReplayResult:
    """Delete the copy, re-copy the source, and replay the changes that had landed.

    The order is the whole point. The source is re-checked first, so a source that moved
    refuses the fallback while the copy and the log are still intact; only then is the copy
    discarded and re-made, and only then is anything written to it.

    Args:
        client: The `remodel.*` bridge. `remodel.close` with `discard_copy` deletes the
            copy, and `remodel.open` makes the new one - the copy is always made by a
            filesystem copy that refuses to overwrite, before any document handle exists.
        run_dir: The run folder, which already carries the change log this reads.
        changes: The plan's change list, whose `params` carry the persistent references
            that make the replay deterministic.
        attestation: The source attestation recorded at copy time. Its `path` and
            `copy_path` are the two paths this uses, so the file that is re-copied is the
            file the run attested and not one a caller named again.
        run_id: This run's id, for the new document's session tag.
        probe_id: The scope probe this bridge session performed on this source;
            `remodel.open` refuses without one.
        baseline: The run's rebuild-error count, which a fresh copy of an unchanged source
            reads back at.
        limits: The three bounds, which the replayed pass is under exactly as the first
            pass was: a fallback is not a licence to run longer.
        now: The clock, injected as everywhere else.

    Raises:
        SourceChanged: The source is not what it was. Nothing was deleted.
        ReplayUnavailable: The bridge would not close or re-open the document.
    """
    require_source_unchanged(recheck(attestation, at=now()))

    log_path = changes_path(run_dir)
    replaying = applied_changes(changes, read_changes(log_path))

    closed = client.close_document(discard_copy=True)
    if isinstance(closed, CircuitOpen):
        raise ReplayUnavailable(
            f"the bridge stopped answering at {closed.command}, so the copy was not "
            "discarded; the run finalizes with the copy and the log as they are"
        )
    opened = client.open(attestation.path, attestation.copy_path, run_id, probe_id)
    if isinstance(opened, CircuitOpen):
        raise ReplayUnavailable(
            f"the bridge stopped answering at {opened.command}, so the copy was discarded "
            "and not re-made; the run finalizes and reports that it has no copy"
        )

    applied = apply_changes(
        client=client,
        log=ApplyLog(log_path),
        changes=replaying,
        target_path=attestation.copy_path,
        baseline=baseline,
        limits=limits,
        now=now,
    )
    return ReplayResult(
        status="replayed" if applied.status == "complete" else "stopped",
        replayed=tuple(change.seq for change in replaying),
        apply=applied,
        escalated_again=bool(applied.rollback_failed),
    )
