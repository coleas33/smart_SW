"""The executor's equation step: C5, the in-place repair, and C6, the new globals.

`data-model.md` section 1.11 fixes six steps and puts equations last. C5 repairs an
existing global **in place** (FR-029) and C6 adds the new ones, "in `order_index` order,
each added after every global its expression names, each literal seeded from
`GlobalEvidence.value_document_units`"; research R3.5 adds the other half of the C6 rule:
they are **removed in reverse order**, because deleting a lower index renumbers every
higher one.

Three properties live here rather than at the call sites:

- **a repair is never a delete and an add.** Confirmed upstream failure (research R3.5):
  while a referenced global is missing, every equation that depends on it enters an error
  state that does **not** clear when the global returns. So the repair is its own change
  kind, `op: "set"` is its own inverse, and nothing on this path composes a `delete`. A
  repair whose previous text will not read is refused **before** the write, because an
  edit over something unreadable has no inverse.
- **the literal is re-derived from the metres the package carries**, through
  `remodel/units.py`, and the recorded `GlobalEvidence.equation_text` has to agree with
  it. The evidence row is the audit of the highest-risk single conversion in stage 1
  (research R3.6), and a row that no longer agrees with the reading behind it is a
  disagreement to stop on, not one to pick a side of.
- **the write is judged by the re-read, never by the answer.** FR-027's sequence is read
  the metres, convert, seed the exact value, assert it landed, rebuild, re-read and assert
  at the document's stored precision - `==`, not an epsilon. PROBE-6 observed an add
  answering and adding nothing; PROBE-2 leaves it unverified whether the value reads back
  in the document's unit, and this step fails the change rather than leaving a part a
  thousand times off behind it.

**There is no dimension step, in either direction.** The brief carried a dimension-rename
step between C1 and C2 and a dimension-equation step after the globals; FR-030 removes
both, because the IR carries no dimensions in v1, so the planner can neither name one nor
prove what an equation on it would drive. A v1 global names a value and drives nothing,
and no member of the dimension interface is read or written anywhere on this path.

This is the one module of `swreview.remodel` that names a bridge client: it is the
executor, and executing is calling. Everything it decides - the order, the text, the value,
what counts as landed - is decided in the pure functions above `apply_equation_change`,
which take no client at all.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from swreview.bridge.client import BridgeError
from swreview.bridge.remodel_client import (
    CircuitOpen,
    RemodelAddressError,
    RemodelChangeError,
    RemodelClient,
    RemodelContractError,
    RemodelError,
    RemodelLimitError,
    RemodelTargetError,
)
from swreview.remodel import units
from swreview.remodel.apply_log import (
    ESCALATES_TO_REPLAY,
    ApplyLog,
    ChangeRecord,
    RecordKind,
    UndoCommand,
    changes_path,
    derive_undo,
    read_changes,
)
from swreview.remodel.artifacts import GradedRun
from swreview.remodel.attestation import recheck, source_changed, write_attestation
from swreview.remodel.geometry import (
    GateResult,
    GeometryArtifact,
    GeometryReading,
    evaluate,
    reading_from_reply,
    write_geometry_json,
)
from swreview.remodel.plan import (
    GLOBAL_NAME_PATTERN,
    ChangeKind,
    ChangeSubject,
    GlobalProposal,
    Limits,
    PlannedChange,
    RemodelPlan,
    RunState,
    SourceAttestation,
    record_state,
)
from swreview.remodel.report import read_log_targets, write_report
from swreview.remodel.tolerances import ProfileName, Tolerances, require_calibrated

__all__ = [
    "BRIDGE_METHOD",
    "CIRCUIT_OPEN",
    "DISCARD_FAILED",
    "EQUATION_KINDS",
    "EXPECTATIONS",
    "EXPECT_UNMET",
    "EXPRESSION_FUNCTIONS",
    "FEATURE_ERRORS",
    "FEATURE_ERROR_NONE",
    "GATE_NOT_PASSED",
    "NOT_ADDRESSABLE",
    "NO_INVERSE_RECORDED",
    "REBUILD_ERRORS",
    "REBUILD_REGRESSED",
    "RUN_ABORTED",
    "RUN_IN_FLIGHT",
    "SAVE_FAILED",
    "TRUNCATING",
    "UNANSWERED",
    "VERIFY_CHECKS",
    "VERIFY_PROFILE",
    "ApplyResult",
    "EquationOutcome",
    "EquationRefused",
    "EquationStepError",
    "GlobalRepair",
    "ResumeRefused",
    "Stop",
    "StopReason",
    "UnknownExpectation",
    "Verification",
    "VerifyRefused",
    "apply_changes",
    "apply_equation_change",
    "equation_changes",
    "global_changes",
    "open_log",
    "referenced_globals",
    "removal_order",
    "renamed_global_text",
    "repair_changes",
    "utc_now",
    "verify",
]

EQUATION_KINDS: tuple[ChangeKind, ...] = ("equation.edit", "equation.add")
"""C5 then C6. A repair is ordered before every add so the two never compete for a name."""

EXPRESSION_FUNCTIONS: tuple[str, ...] = ("sin", "cos", "tan", "atn", "arcsin", "sqr")
"""The documented function set (`contracts/tools.md`), which reads **degrees**. Everything
else a bare word could be is a global reference somebody forgot to quote."""

UNVERIFIED = "equation_unverified"
"""The bridge's token for "this write could not be proven to have landed". The same token
is used when the executor's own re-read is what refuses it, so the record reads the same
whichever side noticed."""

BAD_REQUEST = "bad_request"
"""The token for a request the host could not honour as sent: a bug in the caller."""

_QUOTED = re.compile(r'"([^"]*)"')
_BARE_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_NAME = re.compile(GLOBAL_NAME_PATTERN)


class EquationStepError(ValueError):
    """This step cannot be composed, so it is not attempted.

    Every one of these is a plan this executor refuses to turn into a write: a cycle among
    the proposed globals, a reference to a name the plan does not add, an evidence row that
    no longer agrees with the metres behind it, a configuration scope nobody read. None of
    them is a condition of the part, and none of them has a sensible default.
    """


@dataclass(frozen=True)
class GlobalRepair:
    """One existing global to repair in place (FR-029).

    `index` is the row's position in the equation manager, which is how the manager
    addresses it; `text` is the whole replacement row. A rename-only repair composes that
    text with `renamed_global_text`, which carries the existing number across unchanged.
    """

    index: int
    text: str


@dataclass(frozen=True)
class EquationOutcome:
    """What one equation change did, and what the log records of it.

    `before` and `after` are the `ChangeRecord` fields: whatever the inverse needs, and
    nothing else. The readings beside them are the evidence the report cites.
    """

    kind: ChangeKind
    index: int
    count_before: int
    count_after: int
    previous_text: str | None
    round_trip_text: str
    helper_path: str
    rebuild_errors: int
    value: float
    before: dict[str, Any] = field(default_factory=dict)
    after: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EquationRefused:
    """One equation change the bridge **wrote** and this side would not accept.

    It is a different answer from a refusal, and the difference is the whole point: a
    refusal leaves the tree where it was and closes the change `failed`, which
    `contracts/run-artifacts.md` defines as "the change never landed". Everything this
    class carries happened after `remodel.equation` was sent, so the row is on the document
    and the run's ordinary inverse path has to take it off again.

    `before` and `after` are the `ChangeRecord` fields, populated exactly when the host's
    own equation count puts a row where this change names one. When the count contradicts
    the call it answered, no index is claimed and no inverse is recorded: `derive_undo` has
    nothing to invert from and the change closes `rollback_failed`, which is the honest
    reading of a document this run can no longer address.

    `in_flight` is the other post-write shape: the write went out and the reading after it
    never came back, so there is no error count to close the line with and the change keeps
    its `attempting` line while the run stops.
    """

    error_code: str
    error: str
    before: dict[str, Any]
    after: dict[str, Any]
    rebuild_errors: int | None
    in_flight: bool = False


# --- 1. what an expression names ---------------------------------------------------


def referenced_globals(expression: str) -> tuple[str, ...]:
    """Every global `expression` reads, in first-appearance order, without duplicates.

    A global is read by its **quoted** name; the documented function set is the only bare
    word an expression may carry. An unquoted word is refused rather than ignored, because
    ignoring it would order an add before the global it depends on and leave an equation
    naming something that does not exist yet.
    """
    names: list[str] = []
    for name in _QUOTED.findall(expression):
        if not _NAME.fullmatch(name):
            raise EquationStepError(
                f"{name!r} is quoted in {expression!r} but is not a global name this "
                f"product writes ({GLOBAL_NAME_PATTERN})"
            )
        if name not in names:
            names.append(name)
    for word in _BARE_WORD.findall(_QUOTED.sub(" ", expression)):
        if word not in EXPRESSION_FUNCTIONS:
            raise EquationStepError(
                f"{word!r} in {expression!r} is neither a quoted global name nor one of "
                f"the documented functions {list(EXPRESSION_FUNCTIONS)}; a reference "
                "SOLIDWORKS will not read is refused rather than silently dropped"
            )
    return tuple(names)


# --- 2. the order the new globals are added in -------------------------------------


def seed_order(globals_: Sequence[GlobalProposal]) -> tuple[GlobalProposal, ...]:
    """The proposed globals in the order they are added: `order_index`, then dependency.

    `order_index` is the plan's stated application order and it decides everything the
    dependency edges do not, so the change list is the same list on every run. A global is
    added after every global its expression names, because the equation manager has to
    know the name before it can read it.
    """
    proposals = _distinct(globals_)
    names = {item.name for item in proposals}
    references = {item.name: referenced_globals(item.expression) for item in proposals}
    for item in proposals:
        for reference in references[item.name]:
            if reference not in names:
                raise EquationStepError(
                    f"{item.name!r} reads {reference!r}, which this plan does not add; "
                    "the executor adds what the plan carries, and a global added before "
                    "the name it reads exists is a broken equation"
                )

    pending = sorted(proposals, key=lambda item: item.order_index)
    ordered: list[GlobalProposal] = []
    placed: set[str] = set()
    while pending:
        for position, item in enumerate(pending):
            if placed.issuperset(references[item.name]):
                ordered.append(pending.pop(position))
                placed.add(item.name)
                break
        else:
            raise EquationStepError(
                "the remaining globals are circular and none of them can be added first: "
                f"{sorted(item.name for item in pending)}"
            )
    return tuple(ordered)


def _distinct(globals_: Sequence[GlobalProposal]) -> tuple[GlobalProposal, ...]:
    """The proposals, with the two ambiguities that would make the order accidental."""
    proposals = tuple(globals_)
    names = [item.name for item in proposals]
    repeated = sorted({name for name in names if names.count(name) > 1})
    if repeated:
        raise EquationStepError(
            f"{repeated} appear twice among the proposed globals; one name is one global, "
            "and the second add would fail on a name the first already took"
        )
    indexes = [item.order_index for item in proposals]
    shared = sorted({index for index in indexes if indexes.count(index) > 1})
    if shared:
        raise EquationStepError(
            f"order_index {shared} is claimed by more than one global; it is the "
            "application order, and two globals in one position leave this step to decide "
            "by accident, which a replay could not reproduce"
        )
    return proposals


def removal_order(records: Sequence[ChangeRecord]) -> tuple[ChangeRecord, ...]:
    """The adds this run made, newest first: the order their inverses are applied in.

    `IEquationMgr.Delete(index)` renumbers every higher index, so an add is removed before
    every add that followed it and each recorded index is still the row's own. Only adds
    are here: an edit is undone by another edit, and a delete is never anything but the
    inverse of an add this run made and proved.
    """
    return tuple(
        reversed(
            [
                record
                for record in records
                if record.kind == "equation.add" and record.status == "applied"
            ]
        )
    )


# --- 3. the changes this step composes ---------------------------------------------


def global_changes(
    globals_: Sequence[GlobalProposal],
    *,
    document_length_unit: str | None,
    which_configs: int | None,
    first_seq: int = 1,
) -> tuple[PlannedChange, ...]:
    """C6: one `equation.add` per new global, in the seeding order.

    The literal is re-derived from `GlobalEvidence.value_m` - the metres the package
    carries - through the one unit module, and the recorded `equation_text` has to agree
    with what comes out. A global whose expression names other globals has no literal to
    seed: its text is the expression, whose numbers are already in the document's unit.
    """
    configs = _configuration_scope(which_configs)
    changes: list[PlannedChange] = []
    for offset, item in enumerate(seed_order(globals_)):
        text, value = _global_text(item, document_length_unit)
        expect: dict[str, Any] = {"equation_count_delta": 1, "rebuild_errors_delta": 0}
        if value is not None:
            expect["equation_value"] = value
        changes.append(
            PlannedChange(
                seq=first_seq + offset,
                kind="equation.add",
                subject_kind="equation",
                subject=None,
                params={
                    "op": "add",
                    "index": None,
                    "text": text,
                    "which_configs": configs,
                },
                expect=expect,
            )
        )
    return tuple(changes)


def repair_changes(
    repairs: Sequence[GlobalRepair],
    *,
    which_configs: int | None,
    first_seq: int = 1,
) -> tuple[PlannedChange, ...]:
    """C5: one `equation.edit` per existing global repaired in place.

    `op` is `set` and nothing on this path composes anything else, which is what makes
    delete-and-re-add unreachable from a repair rather than merely unused.
    """
    configs = _configuration_scope(which_configs)
    indexes = [repair.index for repair in repairs]
    repeated = sorted({index for index in indexes if indexes.count(index) > 1})
    if repeated:
        raise EquationStepError(
            f"equation {repeated} is repaired twice in one run; the second repair would "
            "record as its inverse a text the first has already overwritten"
        )
    return tuple(
        PlannedChange(
            seq=first_seq + offset,
            kind="equation.edit",
            subject_kind="equation",
            subject=None,
            params={
                "op": "set",
                "index": repair.index,
                "text": repair.text,
                "which_configs": configs,
            },
            expect={"equation_count_delta": 0, "rebuild_errors_delta": 0},
        )
        for offset, repair in enumerate(repairs)
    )


def equation_changes(
    *,
    repairs: Sequence[GlobalRepair],
    globals_: Sequence[GlobalProposal],
    document_length_unit: str | None,
    which_configs: int | None,
    first_seq: int = 1,
) -> tuple[PlannedChange, ...]:
    """The whole equation step, C5 then C6.

    Every repair comes before every add, so a repair never competes with an add for the
    same name: the name a repair frees is free before the add that wants it is sent.
    """
    repaired = repair_changes(repairs, which_configs=which_configs, first_seq=first_seq)
    added = global_changes(
        globals_,
        document_length_unit=document_length_unit,
        which_configs=which_configs,
        first_seq=first_seq + len(repaired),
    )
    return repaired + added


def renamed_global_text(previous_text: str, new_name: str) -> str:
    """The same row under a new name, with its right-hand side carried across **unchanged**.

    FR-029: unchanged, not recomputed. The number in the document is the number the part
    was built with, and re-deriving it from a package reading would silently move the part
    if the two ever disagreed. The text after the first `=` is carried byte for byte, its
    spacing included, because carrying it is the whole point.
    """
    if not _NAME.fullmatch(new_name):
        raise ValueError(
            f"{new_name!r} is not a global name this product writes "
            f"({GLOBAL_NAME_PATTERN}); the same rule the plan refuses a proposal by"
        )
    _, separator, right = previous_text.partition("=")
    if not separator or not right.strip():
        raise EquationStepError(
            f"{previous_text!r} has no right-hand side to carry across, so there is "
            "nothing to rename in place"
        )
    return f'"{new_name}" ={right}'


def _configuration_scope(which_configs: int | None) -> int:
    if which_configs is None:
        raise EquationStepError(
            "which_configs is unknown, so no equation may be written: it comes from the "
            "configuration count remodel.open recorded, and a global written into one "
            "configuration of several would be invisible in the others"
        )
    return which_configs


def _global_text(
    item: GlobalProposal, document_length_unit: str | None
) -> tuple[str, float | None]:
    """The row this global is written as, and the value to re-read it against.

    A derived global has no value here: there is no literal to seed, so there is no number
    this side computed to compare a reading with, and inventing one would be arithmetic
    nobody did.
    """
    if referenced_globals(item.expression):
        return f'"{item.name}" = {item.expression}', None
    if not item.evidence:
        raise EquationStepError(
            f"{item.name!r} names a literal and carries no evidence; the value has to come "
            "from a reading the package carries, never from the expression the model wrote"
        )
    texts: set[str] = set()
    values: set[float] = set()
    for row in item.evidence:
        value = units.document_length(row.value_m, document_length_unit)
        if row.document_length_unit != document_length_unit:
            raise units.DocumentUnitError(
                f"{item.name!r} was composed for a document kept in "
                f"{row.document_length_unit!r} and this one is kept in "
                f"{document_length_unit!r}; the plan and the write name one unit or the "
                "conversion has happened twice"
            )
        text = units.global_equation_text(item.name, value)
        if text != row.equation_text:
            raise EquationStepError(
                f"{item.name!r} records {row.equation_text!r}, which does not agree with "
                f"{text!r}, re-derived from the {row.value_m} m the package carries; the "
                "evidence row is the audit of that conversion and a row that disagrees "
                "with it is a disagreement to stop on"
            )
        texts.add(text)
        values.add(value)
    if len(texts) != 1:
        raise EquationStepError(
            f"{item.name!r} is justified by readings that do not agree: {sorted(texts)}"
        )
    return texts.pop(), values.pop()


# --- 4. one change, through the bridge ---------------------------------------------


def apply_equation_change(
    client: RemodelClient, change: PlannedChange
) -> EquationOutcome | EquationRefused | CircuitOpen:
    """Write one equation change and prove it landed, or say what happened instead.

    The FR-027 sequence, steps 3 to 6: seed the exact value (the text arrived composed),
    assert the write landed and evaluated, rebuild, re-read and assert the text and the
    value round-trip at the document's stored precision. A repair reads the row it is
    about to overwrite **first**, so the inverse is a reading and never a guess, and an
    unreadable row refuses the change before anything is written.

    The three answers are the three things that can happen, and they are distinct because
    `failed` means "the change never landed":

    - `EquationOutcome`: the write landed and every reading after it agreed;
    - `EquationRefused`: `remodel.equation` was **sent**, and either a reading refused what
      came back or a reading did not come back at all. The row is on the document either
      way, so the caller inverts it rather than recording a change that never happened;
    - `CircuitOpen`: the bridge stopped answering before the write was sent, so nothing was
      written. Returned, not raised, exactly as the client returns it.

    A `RemodelChangeError` still leaves this function by raising, and only from **before**
    the write: an unreadable row refuses the repair, and a plan made against a row the
    document does not carry is a bug in the caller.
    """
    if change.kind not in EQUATION_KINDS:
        raise EquationStepError(
            f"{change.kind!r} is not an equation change; this step writes "
            f"{list(EQUATION_KINDS)}"
        )
    params = dict(change.params)
    previous_text: str | None = None
    if change.kind == "equation.edit":
        before = client.snapshot()
        if isinstance(before, CircuitOpen):
            return before
        previous_text = _previous_text(before, params["index"])

    result = client.equation(**params)
    if isinstance(result, CircuitOpen):
        return result

    # From here the document has been written to, so nothing below may close the change
    # as one that never landed.
    index = int(result["index"])
    overwritten = result["previous_text"] if change.kind == "equation.edit" else None
    recorded = _recorded_states(change, result, index, overwritten)

    try:
        _landed(change, result, previous_text)
    except RemodelChangeError as exc:
        return _refused_after_the_write(client, exc, recorded)

    rebuilt = client.rebuild(force=False)
    if isinstance(rebuilt, CircuitOpen):
        return _unanswered_after_the_write(rebuilt, recorded)
    after = client.snapshot()
    if isinstance(after, CircuitOpen):
        return _unanswered_after_the_write(after, recorded)

    try:
        value = _re_read(change, index, after)
    except RemodelChangeError as exc:
        return EquationRefused(
            exc.error_code, str(exc), *recorded, int(rebuilt["rebuild_errors"])
        )
    return EquationOutcome(
        kind=change.kind,
        index=index,
        count_before=int(result["count_before"]),
        count_after=int(result["count_after"]),
        previous_text=previous_text,
        round_trip_text=params["text"],
        helper_path=str(result["helper_path"]),
        rebuild_errors=int(rebuilt["rebuild_errors"]),
        value=value,
        before=recorded[0],
        after=recorded[1],
    )


def _recorded_states(
    change: PlannedChange, result: Any, index: int, overwritten: Any
) -> tuple[dict[str, Any], dict[str, Any]]:
    """The `before` and `after` this write earns, which is what decides its inverse.

    The host's own equation count either side of its call is the evidence, and the return
    code is not: PROBE-6 observed `Add3` answering and adding nothing. An add that moved
    the count by one put its row at `index` and a `set` moved none and overwrote the row at
    `index`, so both are addressable and both have an inverse. Any other delta is a set of
    equations this run can no longer address, and it records no index rather than an index
    a later delete would act on blindly.

    `overwritten` is the bridge's **own** reading of the text it replaced, not the snapshot
    reading the plan was made against: an inverse writes back what was there.
    """
    delta = int(result["count_after"]) - int(result["count_before"])
    if delta != (1 if change.kind == "equation.add" else 0):
        return {}, {}
    text = overwritten if isinstance(overwritten, str) else None
    return _record_before(change, index, text), {"index": index}


def _refused_after_the_write(
    client: RemodelClient,
    refusal: RemodelChangeError,
    recorded: tuple[dict[str, Any], dict[str, Any]],
) -> EquationRefused:
    """A write the host answered and `_landed` would not accept, plus a fresh reading.

    The rebuild has not run yet on this path, so the error count is taken here: a change
    the run is about to invert is closed with a reading somebody took, never with the count
    it started from (Principle I).
    """
    rebuilt = client.rebuild(force=False)
    if isinstance(rebuilt, CircuitOpen):
        return _unanswered_after_the_write(rebuilt, recorded)
    return EquationRefused(
        refusal.error_code, str(refusal), *recorded, int(rebuilt["rebuild_errors"])
    )


def _unanswered_after_the_write(
    circuit: CircuitOpen, recorded: tuple[dict[str, Any], dict[str, Any]]
) -> EquationRefused:
    """The write went out and the reading after it did not come back."""
    return EquationRefused(
        CIRCUIT_OPEN, _unanswered(circuit), *recorded, None, in_flight=True
    )


def _previous_text(snapshot: Any, index: int) -> str:
    """The row a repair is about to overwrite, or a refusal naming why there is none.

    An index named in `unreadable_equation_indexes[]` is a row whose text will not read,
    and an edit over one has no inverse: writing something that cannot be put back is a
    silent edit. An index no row sits at is a plan made against a different tree, which is
    a bug in the caller rather than a row to create.
    """
    if index in set(snapshot["unreadable_equation_indexes"]):
        raise RemodelChangeError(
            f"equation {index} could not be read before the edit, so the edit would have "
            "no inverse; writing over something that cannot be put back is a silent edit",
            UNVERIFIED,
        )
    for row in snapshot["equations"]:
        if row["index"] == index:
            return str(row["text"])
    raise RemodelContractError(
        f"there is no equation at index {index}; this run planned a repair against a row "
        "the document does not carry, and a repair never creates one",
        BAD_REQUEST,
    )


def _landed(change: PlannedChange, result: Any, previous_text: str | None) -> None:
    """The write's own evidence: the count moved as expected and the row reads back.

    The member's return code is not the evidence (PROBE-6 observed an add answering and
    adding nothing), and neither is the host's word for it: the delta `expect` carries is
    asserted on this side too, because this side is what writes the record.
    """
    text = change.params["text"]
    expected = change.expect["equation_count_delta"]
    delta = int(result["count_after"]) - int(result["count_before"])
    if delta != expected:
        raise RemodelChangeError(
            f"change {change.seq} took the equation count from {result['count_before']} "
            f"to {result['count_after']}, a delta of {delta} where {expected} was "
            "expected; an in-place edit moves no row and an add moves exactly one",
            UNVERIFIED,
        )
    if result["round_trip_text"] != text:
        raise RemodelChangeError(
            f"change {change.seq} wrote {text!r} and the row answered "
            f"{result['round_trip_text']!r}",
            UNVERIFIED,
        )
    if previous_text is not None and result["previous_text"] != previous_text:
        raise RemodelChangeError(
            f"change {change.seq} planned to overwrite {previous_text!r} and the bridge "
            f"read {result['previous_text']!r} at that index; the inverse this run would "
            "record is not the text that was there",
            UNVERIFIED,
        )


def _re_read(change: PlannedChange, index: int, snapshot: Any) -> float:
    """Step 6: the row after the rebuild, at the document's stored precision.

    `==` on both the text and the number, not an epsilon: the text is the only carrier of
    the number once it reaches the equation manager, and a value that reads back in
    another unit is the thousandfold error research R3.6 exists to catch (PROBE-2 leaves
    that question open, and this is where an open question fails a change instead of
    passing one).
    """
    text = change.params["text"]
    for row in snapshot["equations"]:
        if row["index"] != index:
            continue
        if row["text"] != text:
            raise RemodelChangeError(
                f"change {change.seq} wrote {text!r} and after the rebuild the row reads "
                f"{row['text']!r}",
                UNVERIFIED,
            )
        value = row["value"]
        if value is None:
            raise RemodelChangeError(
                f"change {change.seq} wrote {text!r} and its value will not read; an "
                "equation nobody can evaluate is not evidence that the number landed",
                UNVERIFIED,
            )
        expected = change.expect.get("equation_value")
        if expected is not None and value != expected:
            raise RemodelChangeError(
                f"change {change.seq} seeded {expected} and the row evaluates to {value}; "
                "the number in an equation is in the document's length unit, and a "
                "reading in another one is a part built to the wrong size",
                UNVERIFIED,
            )
        return float(value)
    raise RemodelChangeError(
        f"change {change.seq} wrote {text!r} and no row sits at index {index} after the "
        "rebuild",
        UNVERIFIED,
    )


def _record_before(
    change: PlannedChange, index: int, previous_text: str | None
) -> dict[str, Any]:
    """The `ChangeRecord.before` fields: whatever the inverse needs, and nothing else.

    An add inverts to a delete at the index it landed at, which `after` carries, so its
    `before` is empty. An edit inverts to another edit, which needs the row, the text that
    was there and the configuration scope it was written with.
    """
    if previous_text is None:
        return {}
    return {
        "index": index,
        "equation_text": previous_text,
        "which_configs": change.params["which_configs"],
    }


# --- 5. The executor core: one change at a time, in the plan's order ----------------

BRIDGE_METHOD: Mapping[ChangeKind, str] = {
    "rename": "rename",
    "describe": "describe",
    "reorder": "reorder",
    "folder.create": "folder",
    "folder.rename": "folder",
    "equation.edit": "equation",
    "equation.add": "equation",
}
"""Every kind the plan emits, and the client method that sends it (`CHANGE_ORDER` order).

The executor is a translator: `PlannedChange.params` mirrors the command's payload exactly,
so a change is sent by handing that object to this method and never by composing a second
idea of the operation. `save` is not here, because the copy is saved once, at the end, by
the gate; and there is no dimension kind, because v1 addresses none (FR-030)."""

EXPECTATIONS: frozenset[str] = frozenset(
    {"rebuild_errors_delta", "folder_location", "equation_count_delta", "equation_value"}
)
"""Every `expect` key something asserts, checked before the run touches the document.

Each is asserted exactly once and in one place: `rebuild_errors_delta` by the ceiling this
module compares the rebuild reading against, `folder_location` by `_unmet` below, and
`equation_count_delta` and `equation_value` by `_landed` and `_re_read` above. A key nobody
asserts is an expectation nobody checks, so it is refused at the door rather than carried."""

TRUNCATING: frozenset[str] = frozenset({"max_changes", "max_minutes", "max_rebuild_seconds"})
"""The three bounds, and the only stop reasons that finalize a run as `truncated`."""

EXPECT_UNMET = "expect_unmet"
"""The one code in `changes.jsonl` that is not a bridge token, because the bridge cannot
raise it: it names a host that answered `ok` and did not do what the plan asked."""

REBUILD_REGRESSED = "rebuild_regressed"
"""The bridge's own token, reused where this side is what noticed: the count after the
change stands above the run's baseline."""

NOT_ADDRESSABLE = "not_addressable"
"""RK-13: a persistent reference that resolved at plan time and does not now. Recorded as
"could not be addressed after change N", never retried and never searched for."""

CIRCUIT_OPEN = "circuit_open"
"""The bridge stopped answering. Nothing was sent, and the run never auto-resumes."""

NO_INVERSE_RECORDED = "no_inverse_recorded"
"""A change that landed and whose recording carries nothing to invert from.

`derive_undo` returns `None` for a kind v1 has no inverse for and **raises** for a
recording it cannot invert, and the two are different answers: the first is a known gap in
this version, the second is a reading the document did not give up. A landed change with no
recorded inverse ends the run, because the alternative is carrying an un-undoable edit
forward as though it were ordinary."""


def utc_now() -> datetime:
    """The default clock. Injected everywhere so a test drives the bound without sleeping."""
    return datetime.now(UTC)


StopReason = Literal[
    "max_changes",
    "max_minutes",
    "max_rebuild_seconds",
    "rollback_failed",
    "not_addressable",
    "target_mismatch",
    "contract_violation",
    "circuit_open",
    "bridge_failed",
]
"""Why the loop ended early. The first three are bounds and finalize `truncated`; the rest
are aborts, and every one of them leaves the change log intact up to its last line."""


class ResumeRefused(RuntimeError):
    """This run folder already carries a change log, so the executor will not continue it.

    FR-031. After a lost session the copy and the log survive on disk and recovery is
    manual: a resumed run over a tree nobody re-verified is exactly the wrong risk, and the
    tree after a crash is whatever the change in flight left behind. The catastrophic replay
    is not a resume and does not come through here - it deletes the copy and makes a new one
    first, which is the re-verification this refusal is about.
    """


class UnknownExpectation(ValueError):
    """The plan carries an `expect` key nothing asserts. Raised before anything is written."""


@dataclass(frozen=True)
class Stop:
    """Why the run ended early, and on which change."""

    reason: StopReason
    seq: int | None
    detail: str


@dataclass(frozen=True)
class ApplyResult:
    """What the apply phase did, named change by change.

    `status` is `complete` (every planned change reached a terminal status), `truncated` (a
    bound stopped it) or `aborted`. `applied`, `rolled_back`, `failed`, `rollback_failed`,
    `not_attempted` and `in_flight` partition the planned changes, so "how many were applied
    and which were not" is read off this object rather than counted out of prose (FR-026). A
    truncated run is never a silent partial success: it says so here, in `plan.state`, and in
    the report's first line.

    `rollback_failed` is its own tuple and never folded into `failed` for the reason the data
    model gives: a `failed` change never landed and the tree is where it was, while a
    `rollback_failed` change landed, raised the error count and could not be undone. It holds
    at most one entry, because that outcome ends the run.
    """

    status: Literal["complete", "truncated", "aborted"]
    planned: tuple[int, ...]
    applied: tuple[int, ...]
    rolled_back: tuple[int, ...]
    failed: tuple[int, ...]
    rollback_failed: tuple[int, ...]
    not_attempted: tuple[int, ...]
    in_flight: int | None
    stop: Stop | None
    escalates_to_replay: bool


@dataclass(frozen=True)
class _Landed:
    """One change the bridge answered, and the error reading taken after it.

    `unverified` is the `(error_code, error)` pair of a write that went out and did not
    prove itself: the change landed, so it is settled through the ordinary inverse path
    rather than closed as one that never happened.
    """

    before: dict[str, Any]
    after: dict[str, Any]
    errors: int
    rebuild_ms: int | None
    unverified: tuple[str, str] | None = None


@dataclass(frozen=True)
class _Refused:
    """One change the bridge would not make, or could not be proven to have made.

    `stop` is the reason the run ends, or `None` where it carries on: a change that never
    landed leaves the tree where it was, so the next change is safe to attempt. `in_flight`
    is the one case neither of those covers - the call went out and the reading after it did
    not come back - and such a change keeps its `attempting` line rather than being closed
    out with a count nobody took.
    """

    error_code: str
    error: str
    stop: StopReason | None
    in_flight: bool = False


def open_log(run_dir: Path | str) -> ApplyLog:
    """The run's change log, or a refusal to continue one that already exists (FR-031)."""
    path = changes_path(run_dir)
    if read_changes(path):
        raise ResumeRefused(
            f"{path} already carries a change log, so this is not a new run; a run never "
            "auto-resumes, because the tree a crash left behind is exactly the tree nobody "
            "re-verified. Recovery is manual, and the catastrophic replay makes a fresh "
            "copy before it writes anything"
        )
    return ApplyLog(path)


def apply_changes(
    *,
    client: RemodelClient,
    log: ApplyLog,
    changes: Sequence[PlannedChange],
    target_path: str,
    baseline: int,
    limits: Limits,
    now: Callable[[], datetime] = utc_now,
) -> ApplyResult:
    """Apply every planned change to the copy, in the plan's order, to completion.

    One bridge call per change, then `ForceRebuild3(false)` and a `GetWhatsWrongCount()`
    reading compared against the run's **baseline**: a count above it means the change is
    inverted, the inversion is confirmed by a second rebuild, the pair is recorded and the
    run carries on. A count at or below the baseline is left alone, because a part that
    already carried errors at baseline is refused before the run starts.

    The run goes to completion and asks nobody anything: there is no approval parameter in
    this signature and no per-change prompt anywhere below it (FR-045).

    Args:
        client: The `remodel.*` bridge. Nothing else here reaches a document.
        log: The run's `changes.jsonl` writer, from `open_log`.
        changes: `RemodelPlan.changes`, already in the fixed C1 to C6 order that the plan
            model refuses to be out of. This loop preserves it and never re-sorts.
        target_path: The copy's path, as `VerifyTarget` confirms it per write (FR-041).
        baseline: The run's rebuild-error count, read at open before any change.
        limits: The three bounds. Enforced here, and nowhere the model can reach.
        now: The clock, injected so the wall-clock bound and `elapsed_ms` are readings of
            one clock and a test drives both without sleeping.
    """
    _assertable(changes)
    started_at = now()
    seq = _next_seq(log)
    errors = baseline
    applied: list[int] = []
    rolled_back: list[int] = []
    failed: list[int] = []
    beyond_undoing: list[int] = []
    stop: Stop | None = None
    in_flight: int | None = None
    escalates = False

    for taken, change in enumerate(changes):
        at = now()
        stop = _bound_reached(taken, at, started_at, limits)
        if stop is not None:
            break

        opened = _attempting(seq, at, change.kind, change.subject, errors, target_path)
        log.append(opened)
        outcome = _perform(client, change, after_change=applied[-1] if applied else 0)

        if isinstance(outcome, _Refused):
            if outcome.in_flight:
                in_flight = change.seq
                stop = Stop(outcome.stop or "bridge_failed", change.seq, outcome.error)
                break
            log.append(
                _closed(
                    opened,
                    now(),
                    at,
                    status="failed",
                    errors_after=errors,
                    error_code=outcome.error_code,
                    error=outcome.error,
                )
            )
            failed.append(change.seq)
            if outcome.stop is not None:
                stop = Stop(outcome.stop, change.seq, outcome.error)
                break
            seq += 1
            continue

        landed = _closed(
            opened,
            now(),
            at,
            status="applied",
            errors_after=outcome.errors,
            before=outcome.before,
            after=outcome.after,
        )
        record, confirmed = _settle(
            client, change, landed, baseline=baseline, unverified=outcome.unverified
        )
        log.append(record)
        errors = outcome.errors if confirmed is None else confirmed

        if record.status == "applied":
            applied.append(change.seq)
        elif record.status == "rolled_back":
            rolled_back.append(change.seq)
        else:
            beyond_undoing.append(change.seq)
            escalates = change.kind in ESCALATES_TO_REPLAY
            stop = Stop(
                "rollback_failed",
                change.seq,
                f"change {change.seq} ({change.kind}) landed, took the rebuild-error count "
                f"to {record.rebuild_errors_after} and could not be undone",
            )
            break

        over = _rebuild_bound(outcome.rebuild_ms, limits)
        if over is not None:
            stop = Stop("max_rebuild_seconds", change.seq, over)
            break
        seq += 1

    settled = {*applied, *rolled_back, *failed, *beyond_undoing}
    return ApplyResult(
        status=_status(stop),
        planned=tuple(change.seq for change in changes),
        applied=tuple(applied),
        rolled_back=tuple(rolled_back),
        failed=tuple(failed),
        rollback_failed=tuple(beyond_undoing),
        not_attempted=tuple(
            change.seq
            for change in changes
            if change.seq not in settled and change.seq != in_flight
        ),
        in_flight=in_flight,
        stop=stop,
        escalates_to_replay=escalates,
    )


# --- 5.1 one change, and what it cost ------------------------------------------------


def _perform(
    client: RemodelClient, change: PlannedChange, *, after_change: int
) -> _Landed | _Refused:
    """Send one change and read the tree after it, or name why neither happened.

    An equation change goes through `apply_equation_change`, which owns the FR-027 sequence
    and does its own rebuild; every other kind is one call plus the rebuild this loop needs
    for the baseline comparison. There is no second copy of either.
    """
    try:
        if change.kind in EQUATION_KINDS:
            outcome = apply_equation_change(client, change)
            if isinstance(outcome, CircuitOpen):
                return _Refused(CIRCUIT_OPEN, _unanswered(outcome), "circuit_open")
            if isinstance(outcome, EquationRefused):
                errors = outcome.rebuild_errors
                if outcome.in_flight or errors is None:
                    return _Refused(
                        outcome.error_code, outcome.error, "circuit_open", in_flight=True
                    )
                return _Landed(
                    outcome.before,
                    outcome.after,
                    errors,
                    None,
                    unverified=(outcome.error_code, outcome.error),
                )
            return _Landed(outcome.before, outcome.after, outcome.rebuild_errors, None)

        reply = getattr(client, BRIDGE_METHOD[change.kind])(**change.params)
        if isinstance(reply, CircuitOpen):
            return _Refused(CIRCUIT_OPEN, _unanswered(reply), "circuit_open")
        rebuilt = client.rebuild(force=False)
        if isinstance(rebuilt, CircuitOpen):
            return _Refused(CIRCUIT_OPEN, _unanswered(rebuilt), "circuit_open", in_flight=True)
        before, after = _states(change, reply)
        return _Landed(before, after, int(rebuilt["rebuild_errors"]), int(rebuilt["elapsed_ms"]))
    except RemodelTargetError as exc:
        return _Refused(exc.error_code, str(exc), "target_mismatch")
    except RemodelAddressError:
        return _Refused(
            NOT_ADDRESSABLE,
            f"could not be addressed after change {after_change}",
            "not_addressable",
        )
    except RemodelLimitError as exc:
        return _Refused(exc.error_code, str(exc), "max_rebuild_seconds", in_flight=True)
    except RemodelChangeError as exc:
        return _Refused(exc.error_code, str(exc), None)
    except RemodelError as exc:
        return _Refused(exc.error_code, str(exc), "contract_violation")
    except BridgeError as exc:
        return _Refused("bridge_failed", str(exc), "bridge_failed")


def _settle(
    client: RemodelClient,
    change: PlannedChange,
    landed: ChangeRecord,
    *,
    baseline: int,
    unverified: tuple[str, str] | None = None,
) -> tuple[ChangeRecord, int | None]:
    """Decide what the landed change is: applied, rolled back, or beyond undoing.

    Three things can make a landed change one to take back, in the order they are asked:
    the write's own verification refused it (`unverified`, which only a write that went out
    can carry), the rebuild-error count stands above the run's baseline plus the delta the
    plan permits, or an `expect` key did not hold. "Above the baseline" and
    `expect["rebuild_errors_delta"]` are one rule and not two that could disagree.

    Returns the record to write and the count the confirming rebuild read, or `None` where
    no inversion was attempted.
    """
    ceiling = baseline + int(change.expect.get("rebuild_errors_delta", 0))
    unmet = _unmet(change, landed)
    if unverified is not None:
        code, why = unverified
    elif landed.rebuild_errors_after is not None and landed.rebuild_errors_after > ceiling:
        code = REBUILD_REGRESSED
        why = (
            f"change {change.seq} took the rebuild-error count to "
            f"{landed.rebuild_errors_after}, above the run's baseline of {baseline}"
        )
    elif unmet is not None:
        code, why = EXPECT_UNMET, unmet
    else:
        code, why = None, None

    try:
        undo = derive_undo(landed)
    except ValueError as exc:
        # The recording cannot be inverted, which `derive_undo` says by raising and is a
        # different answer from the `None` it returns for a kind v1 has no inverse for.
        # The change landed, so it is not `failed`; nothing can take it back, so the run
        # stops here rather than carrying an un-undoable edit forward.
        return (
            _with(
                landed,
                status="rollback_failed",
                error_code=NO_INVERSE_RECORDED if code is None else code,
                error=str(exc) if why is None else f"{why}; {exc}",
            ),
            None,
        )
    if code is None:
        return _with(landed, undo=undo), None
    if undo is None:
        return (
            _with(landed, status="rollback_failed", error_code=code, error=why),
            None,
        )
    confirmed = _invert(client, undo)
    restored = confirmed == landed.rebuild_errors_before
    after = dict(landed.after)
    if isinstance(confirmed, int):
        after["rollback_rebuild_errors"] = confirmed
    return (
        _with(
            landed,
            status="rolled_back" if restored else "rollback_failed",
            undo=undo,
            after=after,
            error_code=code,
            error=why if restored else f"{why}; the inverse did not restore it",
        ),
        confirmed if isinstance(confirmed, int) else None,
    )


def _invert(client: RemodelClient, undo: UndoCommand) -> int | str:
    """Apply one recorded inverse and confirm it with a second rebuild.

    The inverse is applied by handing `params` to the client, exactly as `derive_undo`
    composed it, and it is believed only when the rebuild after it reads the count the
    change started from. `IModelDoc2.EditUndo2` is not reachable from here: it returns void,
    so a caller cannot tell whether it did anything, and it shares the engineer's own undo
    stack.
    """
    method = undo.command.removeprefix("remodel.")
    try:
        reply = getattr(client, method)(**undo.params)
        if isinstance(reply, CircuitOpen):
            return _unanswered(reply)
        rebuilt = client.rebuild(force=False)
    except BridgeError as exc:
        return str(exc)
    if isinstance(rebuilt, CircuitOpen):
        return _unanswered(rebuilt)
    return int(rebuilt["rebuild_errors"])


def _states(change: PlannedChange, reply: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    """`before` and `after` for one change: whatever the inverse needs, and nothing else.

    Every value is the bridge's own reading, because an inverse composed from the plan's
    intent would put back what the run meant to find rather than what was there. The one
    exception is a folder rename's previous name, which the command does not return: the
    `___EndTag___` marker keeps a folder's default name after a rename, so the name is read
    from the subject the dump of the copy recorded at open instead.
    """
    params = change.params
    if change.kind == "rename":
        return {"name": reply["previous_name"]}, {"name": reply["new_name"]}
    if change.kind == "describe":
        return {"text": reply["previous_text"]}, {"text": params["text"]}
    if change.kind == "reorder":
        return (
            {
                "index": reply["previous_index"],
                "anchor_persist_ref": reply["previous_anchor_persist_ref"],
                "location": reply["previous_location"],
            },
            {
                "index": reply["new_index"],
                "anchor_persist_ref": params["anchor_persist_ref"],
                "location": params["location"],
            },
        )
    after = {
        "folder_persist_ref": reply["folder_persist_ref"],
        "name": reply["name"],
        "member_persist_refs": list(reply["member_persist_refs"]),
    }
    if change.kind == "folder.create":
        return {}, after
    subject = change.subject
    return {"name": subject.name if subject is not None else None}, after


def _unmet(change: PlannedChange, landed: ChangeRecord) -> str | None:
    """The `expect` keys this loop is the one place to assert. `None` means all of them held.

    `folder_location` is the membership the host verified with
    `IFeatureManager.FeatureFolderLocation` per member, so **both** halves of it are
    asserted: the folder name the host echoed, and the members it reports the folder
    holding. The name alone is just `params["name"]` round-tripped, and a host that wrapped
    the wrong run and answered with the asked-for name would read as a success on it.

    The member lists are compared in order, because the plan proved the run contiguous
    before it asked for the folder, so the order it asked in is the order the tree carries.
    """
    wanted = change.expect.get("folder_location")
    if wanted is None:
        return None
    landed_in = landed.after.get("name")
    if landed_in != wanted:
        return (
            f"change {change.seq} expected the members to land in {wanted!r} and the "
            f"bridge reported {landed_in!r}"
        )
    asked = list(change.params["member_persist_refs"])
    held = list(landed.after.get("member_persist_refs") or ())
    if held != asked:
        return (
            f"change {change.seq} asked {wanted!r} to hold {asked} and the bridge read "
            f"back {held} with IFeatureManager.FeatureFolderLocation; a folder around "
            "another run of features is not the folder this plan proved contiguous"
        )
    return None


# --- 5.2 the three bounds -------------------------------------------------------------


def _bound_reached(
    taken: int, at: datetime, started_at: datetime, limits: Limits
) -> Stop | None:
    """The two bounds read before a change is attempted, or `None` to go ahead."""
    if taken >= limits.max_changes:
        return Stop(
            "max_changes",
            None,
            f"{taken} changes is this run's limit of {limits.max_changes}",
        )
    elapsed = (at - started_at).total_seconds()
    if elapsed >= limits.max_minutes * 60:
        return Stop(
            "max_minutes",
            None,
            f"{elapsed:.0f}s is past this run's limit of {limits.max_minutes} minutes",
        )
    return None


def _rebuild_bound(rebuild_ms: int | None, limits: Limits) -> str | None:
    """The bound on one rebuild, read from the seat's own elapsed reading.

    `None` for an equation change, whose rebuild belongs to `apply_equation_change`: that
    path is bounded by the host, which answers `rebuild_timeout` and reaches this loop as a
    limit refusal rather than as a reading.
    """
    if rebuild_ms is None or rebuild_ms <= limits.max_rebuild_seconds * 1000:
        return None
    return (
        f"the rebuild took {rebuild_ms / 1000:.0f}s, past this run's limit of "
        f"{limits.max_rebuild_seconds}s"
    )


def _status(stop: Stop | None) -> Literal["complete", "truncated", "aborted"]:
    if stop is None:
        return "complete"
    return "truncated" if stop.reason in TRUNCATING else "aborted"


# --- 5.3 the two lines per change ------------------------------------------------------


def _attempting(
    seq: int,
    at: datetime,
    kind: RecordKind,
    subject: ChangeSubject | None,
    errors: int,
    target_path: str,
) -> ChangeRecord:
    """The line written **before** the call, so a crash names what was in flight.

    It takes the kind and the subject rather than a `PlannedChange` because the save is a
    record the run writes and never a change the plan proposes, and one announcement is
    what makes "exactly one attempting line" a property of this module.
    """
    return ChangeRecord(
        seq=seq,
        at=_stamp(at),
        kind=kind,
        subject=subject,
        before={},
        after={},
        undo=None,
        rebuild_errors_before=errors,
        rebuild_errors_after=None,
        status="attempting",
        error_code=None,
        error=None,
        target_path=target_path,
        elapsed_ms=None,
    )


def _closed(
    opened: ChangeRecord,
    at: datetime,
    started: datetime,
    *,
    status: str,
    errors_after: int,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    error_code: str | None = None,
    error: str | None = None,
) -> ChangeRecord:
    """The line written after it, carrying the readings the status was reached from.

    `elapsed_ms` is the wall clock between the two lines, so a change that was applied and
    then inverted reports what the whole attempt cost rather than only its first call.
    """
    return ChangeRecord.model_validate(
        {
            **opened.model_dump(),
            "at": _stamp(at),
            "before": opened.before if before is None else before,
            "after": opened.after if after is None else after,
            "rebuild_errors_after": errors_after,
            "status": status,
            "error_code": error_code,
            "error": error,
            "elapsed_ms": max(int((at - started).total_seconds() * 1000), 0),
        }
    )


def _with(record: ChangeRecord, **fields: Any) -> ChangeRecord:
    """The same line with some fields decided, re-validated rather than patched in place."""
    return ChangeRecord.model_validate({**record.model_dump(), **fields})


def _assertable(changes: Sequence[PlannedChange]) -> None:
    """Refuse an expectation nothing asserts, before the run touches the document."""
    unknown = sorted({key for change in changes for key in change.expect} - EXPECTATIONS)
    if unknown:
        raise UnknownExpectation(
            f"the plan expects {unknown}, which nothing asserts; the executor asserts "
            f"{sorted(EXPECTATIONS)}, and an expectation nobody checks is one the report "
            "would print as if it had been"
        )


def _next_seq(log: ApplyLog) -> int:
    """The next free `seq`. A fresh run starts at 1; a replay continues the file."""
    written = read_changes(log.path)
    return written[-1].seq + 1 if written else 1


def _unanswered(circuit: CircuitOpen) -> str:
    return f"the bridge stopped answering at {circuit.command}: {circuit.last_error}"


def _stamp(at: datetime) -> str:
    return at.astimezone(UTC).isoformat().replace("+00:00", "Z")




# --- 6. VERIFY, and the SAVE it gates ------------------------------------------------

FEATURE_ERROR_NONE = 0
"""`swFeatureError_e.swFeatureErrorNone` (VERIFIED value). The only code a verified run
accepts from `IFeature.GetErrorCode2`, whatever its out Boolean says about it."""

VERIFY_PROFILE: ProfileName = "IDENTITY"
"""The one profile stage 1 decides under: nothing here creates geometry, so any measured
difference is a defect and not a tolerance question. `EQUIVALENCE` is stage 2's."""

VERIFY_CHECKS: tuple[str, ...] = ("rebuild_errors", "feature_errors", "geometry_gate")
"""The three readings the save is gated behind, in the order they are taken.

`feature_errors` is the **primary** one: `contracts/bridge-remodel.md` makes the
per-feature `GetErrorCode2` walk the reading verification is decided from and
`whats_wrong[]` corroborating only, because its out-array element type is UNVERIFIED
(PROBE-9) and re-joining it by name is fragile where two features in different folders
share a name. All three have to hold; none of them implies another."""

RUN_ABORTED = (
    "the apply phase aborted, and a run that aborted is not verified into a save: {detail}"
)
"""An abort leaves a tree nothing after it can be attributed to (see `ApplyResult`). The
three readings may still come back clean, and the run is failed anyway."""

RUN_IN_FLIGHT = (
    "change {seq} was in flight when the apply phase stopped and nothing read its outcome, "
    "so what it did to the copy is unknown and this run is not verified into a save"
)
"""The one change a bound can leave without a terminal line: the call went out and the
reading after it did not come back. Unknown is not unchanged, and the three readings this
phase takes cannot tell a change that half-landed from one that never did, so the run is
failed and the copy discarded rather than saved on readings that look clean."""

REBUILD_ERRORS = "the copy rebuilt with {count} rebuild error(s), and a verified run reads zero"

FEATURE_ERRORS = (
    "the feature walk found {count} feature(s) whose IFeature.GetErrorCode2 is not "
    "swFeatureErrorNone (0): {named}"
)

GATE_NOT_PASSED = "the geometry gate reported {verdict} under {profile}: {diagnosis}"

UNANSWERED = "verification could not read {command}: {error}"

SAVE_FAILED = "the copy was not saved: {code}: {error}"

DISCARD_FAILED = (
    "the copy could not be discarded: {error}. It is still on disk and this run did not "
    "save it; deleting it is manual"
)

_STATE_AFTER: Mapping[str, RunState] = {"complete": "saved", "truncated": "truncated"}
"""What a verified run's state is, by what the apply phase reported. `aborted` is not
here: it never reaches a pass, so it never reaches this mapping."""


class VerifyRefused(ValueError):
    """This run cannot be verified as asked, and nothing was read to find that out.

    A plan with no copy (the dry run) and a profile other than the one stage 1 decides
    under are both defects in the caller, not conditions of the part, so they are refused
    before a document is touched rather than reported as a failed verification.
    """


@dataclass(frozen=True)
class Verification:
    """What the VERIFY phase read, what it decided, and what it did about it.

    `reasons` is empty on a pass and otherwise names **every** check that failed, in
    `VERIFY_CHECKS` order: a run that failed two of them says so, because a reader
    repairing the part needs both. `passed` is derived from it rather than stored, so the
    two can never disagree.

    `report_path` is always a file: `report.md` is among the artifacts of every terminal
    state (`data-model.md` section 11), including the run whose geometry reading never came
    back. That run's report says the reading did not come back and names the command, which
    is what `reasons` names too.
    """

    state: RunState
    reasons: tuple[str, ...]
    rebuild_errors: int | None
    feature_errors: tuple[dict[str, Any], ...]
    gate: GateResult | None
    geometry_path: Path | None
    report_path: Path
    plan: RemodelPlan
    saved: bool
    copy_discarded: bool

    @property
    def passed(self) -> bool:
        """Whether all three checks held. The save happened if and only if this is true."""
        return not self.reasons


def verify(
    *,
    client: RemodelClient,
    log: ApplyLog,
    run_dir: Path | str,
    plan: RemodelPlan,
    applied: ApplyResult,
    before: GeometryReading,
    tolerances: Tolerances,
    graded: GradedRun,
    attestation: SourceAttestation,
    now: Callable[[], datetime] = utc_now,
) -> Verification:
    """Verify the copy, save it if it verified, discard it if it did not, and report.

    The three checks of `VERIFY_CHECKS` are all taken, always: a run whose rebuild reading
    already failed still takes the geometry reading, because a check nobody ran is a check
    nobody can read and the report is better for naming both. Only then does anything
    happen to the file.

    The source attestation is re-checked here too, after those three readings and before
    the save decision, and it is not one of them: the three are readings of the **copy**,
    and this is the claim that the engineer's file was never touched (FR-040, SC-001). It
    is taken in this phase because a difference is "a hard failure of the run … regardless
    of how well everything else went" (`contracts/run-artifacts.md`), which is a sentence
    about the save: a phase that re-checked after saving would put a `saved` `plan.json`
    beside a `report.md` whose first line says the run failed. `source-attestation.json` is
    rewritten with the completed record before the run fails on it, and the report is
    written from that record rather than from the one the plan carries.

    On a pass the copy is saved, once, through `remodel.save`, which is the only call in
    this product that writes a document to disk. The save lives inside this function
    rather than beside it because the constitution's mutation exception permits it "only
    after the geometry comparison has passed", and a gate the caller can step around is
    not a gate; the host checks the same clause again beside `Save3`.

    On a failure the copy is discarded - `copy/` and nothing else, so `plan.json`,
    `changes.jsonl`, `geometry.json`, the grades and the report all survive and "what did
    it propose" stays answerable - and nothing is saved.

    A failed **save** is a different thing from a failed verification and is not followed
    by a discard: `Save3` may have left an artifact on disk (a
    `swFileSaveWarning_RebuildError` warning is a failed run *with* a saved file), and
    whether the engineer has a file to look at is exactly what that distinction is for.

    Args:
        client: The `remodel.*` bridge.
        log: The run's `changes.jsonl` writer. The save is recorded in it as the same
            attempting-and-terminal pair every change is, because it is a write.
        run_dir: The run folder every artifact is written into.
        plan: The plan as the apply phase leaves it, in state `applying`.
        applied: What the apply phase reported. Its `status` decides whether a verified
            run is `saved` or `truncated`, and an `aborted` one never passes.
        before: The `copy_at_open` reading, taken after the baseline rollback and rebuild
            and before the first change. The source is never opened for this comparison in
            any mode (FR-037); this reading stands for it.
        tolerances: The profile the gate decides under: `IDENTITY`, calibrated.
        graded: Both grades of the run, for the report.
        attestation: The source attestation as `remodel.open` recorded it, before the copy
            was made. This phase re-checks it and writes the completed record; a caller
            that handed over an already-re-checked one would be handing over a verdict
            nothing in this run reached.
        now: The clock, injected so every stamp of one run comes from one clock.

    Raises:
        VerifyRefused: the plan records no copy, or the profile is not the one stage 1
            decides under. Nothing is read and nothing is written.
        UncalibratedProfileError: the profile has never been compared against a known
            answer (FR-036), so it may not decide a run.
    """
    folder = Path(run_dir)
    copy_path = _copy_path(plan)
    _stage_1_profile(tolerances)
    plan = record_state(folder, plan, "verifying", at=now())

    reasons: list[str] = []
    if applied.status == "aborted":
        detail = applied.stop.detail if applied.stop is not None else "no reason recorded"
        reasons.append(RUN_ABORTED.format(detail=detail))
    if applied.in_flight is not None:
        reasons.append(RUN_IN_FLIGHT.format(seq=applied.in_flight))

    errors, feature_errors, unread = _error_reading(client)
    if unread is not None:
        reasons.append(unread)
    else:
        if errors:
            reasons.append(REBUILD_ERRORS.format(count=errors))
        if feature_errors:
            reasons.append(
                FEATURE_ERRORS.format(
                    count=len(feature_errors), named=_named(feature_errors)
                )
            )

    gate, geometry_path, unread = _gate(client, folder, before, tolerances)
    if unread is not None:
        reasons.append(unread)
    elif gate is not None and gate.verdict != "pass":
        reasons.append(
            GATE_NOT_PASSED.format(
                verdict=gate.verdict, profile=tolerances.name, diagnosis=gate.diagnosis
            )
        )

    check = recheck(attestation, at=now())
    write_attestation(folder, check.attestation)
    if check.differences:
        reasons.append(source_changed(check))

    saved = False
    discarded = False
    if not reasons and gate is not None and errors is not None:
        saved, failure = _save(
            client, log, verdict=gate.verdict, copy_path=copy_path, errors=errors, now=now
        )
    else:
        discarded, failure = _discard(client)
    if failure is not None:
        reasons.append(failure)

    state: RunState = _STATE_AFTER[applied.status] if saved else "failed"
    plan = record_state(folder, plan, state, at=now())
    return Verification(
        state=state,
        reasons=tuple(reasons),
        rebuild_errors=errors,
        feature_errors=feature_errors,
        gate=gate,
        geometry_path=geometry_path,
        report_path=_report(folder, plan, log, geometry_path, graded, check.attestation),
        plan=plan,
        saved=saved,
        copy_discarded=discarded,
    )


# --- 6.1 what the phase refuses before it reads anything ------------------------------


def _copy_path(plan: RemodelPlan) -> str:
    """The copy this run verifies, or a refusal naming what the plan is instead."""
    if plan.copy_path is None:
        raise VerifyRefused(
            "this plan records no copy, so it is a dry run: the planner is a deliverable "
            "in its own right and runs over a package with no SOLIDWORKS, no copy and "
            "nothing to verify"
        )
    return plan.copy_path


def _stage_1_profile(tolerances: Tolerances) -> None:
    """Refuse a profile stage 1 does not decide under, or one nobody calibrated."""
    if tolerances.name != VERIFY_PROFILE:
        raise VerifyRefused(
            f"this run would be verified under {tolerances.name!r}; stage 1 creates no "
            f"geometry, so it decides under {VERIFY_PROFILE} alone and any measured "
            "difference is a defect rather than a tolerance question"
        )
    require_calibrated(tolerances)


# --- 6.2 the three readings -----------------------------------------------------------


def _error_reading(
    client: RemodelClient,
) -> tuple[int | None, tuple[dict[str, Any], ...], str | None]:
    """`ForceRebuild3(false)`, then both error readings of the tree it left.

    The count and the per-feature walk arrive in one reply, so they are one call here and
    two checks above: they answer different questions and neither implies the other.

    A reply that carries neither is the same failure as a bridge that did not answer at
    all, and it takes the same path: a reason, a discard and a report. A missing member is
    a reading the host did not take, and reading it as "none" would turn a reading nobody
    took into a clean one (Principle I).
    """
    reply, unread = _read(client.rebuild, force=False)
    if unread is not None:
        return None, (), UNANSWERED.format(command="remodel.rebuild", error=unread.message)
    missing = _missing_reading(reply)
    if missing is not None:
        return None, (), UNANSWERED.format(command="remodel.rebuild", error=missing)
    return int(reply["rebuild_errors"]), _feature_errors(reply), None


def _missing_reading(reply: Mapping[str, Any]) -> str | None:
    """The reading this reply says nothing about, or `None` where both are there."""
    if not isinstance(reply.get("rebuild_errors"), int):
        return "the reply carried no rebuild_errors reading"
    rows = reply.get("feature_errors")
    if not isinstance(rows, list):
        return "the reply carried no feature_errors[] reading"
    return None


def _feature_errors(reply: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    """Every `feature_errors[]` row that is not `swFeatureErrorNone`, as it arrived.

    A row is read by its `error_code` and never by `is_warning`: the out Boolean says
    whether a code is a warning, and `swFeatureErrorNone = 0` is the only acceptable value
    at verify time either way. Whether the member is there at all is `_missing_reading`'s
    question, asked before this one, so nothing here reads an absence as "none".
    """
    return tuple(
        dict(row)
        for row in reply["feature_errors"]
        if int(row["error_code"]) != FEATURE_ERROR_NONE
    )


def _named(rows: Sequence[Mapping[str, Any]]) -> str:
    """Every feature in error, by name and code. All of them: a truncated list of what is
    wrong with a part is a list somebody has to go back to the log for."""
    return ", ".join(f"{row['name']} (code {row['error_code']})" for row in rows)


def _gate(
    client: RemodelClient,
    run_dir: Path,
    before: GeometryReading,
    tolerances: Tolerances,
) -> tuple[GateResult | None, Path | None, str | None]:
    """Take the `copy_at_end` reading, decide the gate, and file `geometry.json`.

    Both readings are of the copy and the verdict is decided here, in Python, from what
    the bridge measured: `evaluate` has no COM in its signature. The artifact is written
    whatever the verdict, because a run that failed the gate is exactly the run whose
    measurements somebody will want to read.
    """
    reply, unread = _read(client.geometry)
    if unread is not None:
        return None, None, UNANSWERED.format(
            command="remodel.geometry", error=unread.message
        )
    after = reading_from_reply(reply)
    gate = evaluate(before, after, tolerances)
    path = write_geometry_json(
        run_dir, before=before, after=after, gate=gate, tolerances=tolerances
    )
    return gate, path, None


@dataclass(frozen=True)
class _Unread:
    """A call this phase made that did not answer: the bridge's token, and what it said."""

    code: str
    message: str


def _read(call: Callable[..., Any], **params: Any) -> tuple[Any, _Unread | None]:
    """One call, or the reason there is no answer to it.

    Every command this phase sends comes through here, so a refusal, a dead bridge and a
    host that answered nothing are one shape at three call sites. "Could not read" is
    never "unchanged" (Principle I): nothing below turns a missing answer into a reading.
    """
    try:
        reply = call(**params)
    except BridgeError as exc:
        code = exc.error_code if isinstance(exc, RemodelError) else "bridge_failed"
        return None, _Unread(code, str(exc))
    if isinstance(reply, CircuitOpen):
        return None, _Unread(CIRCUIT_OPEN, _unanswered(reply))
    return reply, None


# --- 6.3 the two things that can happen to the copy ------------------------------------


def _save(
    client: RemodelClient,
    log: ApplyLog,
    *,
    verdict: str,
    copy_path: str,
    errors: int,
    now: Callable[[], datetime],
) -> tuple[bool, str | None]:
    """Save the copy once, recording the same line pair every other write records.

    `rebuild_errors_after` is the reading the verification was decided from: nothing
    rebuilds between that reading and this save, so repeating it records the reading that
    was taken rather than a second one nobody took. The save has no inverse and the record
    carries none.
    """
    at = now()
    opened = _attempting(_next_seq(log), at, "save", None, errors, copy_path)
    log.append(opened)
    reply, unread = _read(client.save, verdict=verdict)
    if unread is not None:
        log.append(
            _closed(
                opened,
                now(),
                at,
                status="failed",
                errors_after=errors,
                error_code=unread.code,
                error=unread.message,
            )
        )
        return False, SAVE_FAILED.format(code=unread.code, error=unread.message)
    log.append(
        _closed(
            opened,
            now(),
            at,
            status="applied",
            errors_after=errors,
            after={
                "path": reply["path"],
                "errors": reply["errors"],
                "warnings": reply["warnings"],
                "save_flag_after": reply["save_flag_after"],
            },
        )
    )
    return True, None


def _discard(client: RemodelClient) -> tuple[bool, str | None]:
    """Close the copy and delete `copy/`, and nothing else.

    Every other artifact of the run stays on disk: deleting the run folder would lose the
    evidence Principle VI asks for, and "what did it propose" has to stay answerable after
    a run says no. A discard that did not happen is reported rather than assumed.
    """
    reply, unread = _read(client.close_document, discard_copy=True)
    if unread is not None:
        return False, DISCARD_FAILED.format(error=unread.message)
    return bool(reply["copy_deleted"]), None


# --- 6.4 the report --------------------------------------------------------------------


def _report(
    run_dir: Path,
    plan: RemodelPlan,
    log: ApplyLog,
    geometry_path: Path | None,
    graded: GradedRun,
    attestation: SourceAttestation,
) -> Path:
    """`report.md`, written for every terminal state, from the run folder's own files.

    The change list, the grades, the geometry and the targets every write went to are read
    back from disk rather than from this function's memory, which is what makes the report
    a second reader of the run's evidence and not a second account of it.

    A run whose geometry reading never came back has no `geometry.json` to read, and the
    report is written anyway with that section saying so: section 11 lists `report.md`
    among the artifacts of a failed run without exception, and an engineer left with a
    discarded copy and no account of why is what the report exists to prevent.
    """
    artifact = (
        None
        if geometry_path is None
        else GeometryArtifact.model_validate_json(
            geometry_path.read_text(encoding="utf-8")
        )
    )
    return write_report(
        run_dir,
        plan=plan,
        changes=read_changes(log.path),
        graded=graded,
        geometry=artifact,
        attestation=attestation,
        log_targets=read_log_targets(run_dir),
    )
