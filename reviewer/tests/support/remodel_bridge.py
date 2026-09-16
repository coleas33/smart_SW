"""A fake `remodel.*` bridge for the executor's tests (feature 004 T078).

The executor is the one module that talks to SOLIDWORKS, and it is offline-testable only
because everything it needs from the seat arrives through `bridge/remodel_client.py`'s
twelve methods. This module is the other end of those twelve: a small, honest model of a
part's feature tree that answers with the exact result shapes of
`specs/004-resilient-remodeler/contracts/bridge-remodel.md` and **scripts a failure at
change N**.

Three things it models rather than stubs, because the executor's behaviour turns on each:

1. **the tree.** A reorder really moves a persistent reference in `order`, a rename really
   changes the name the next call reads back, and a folder creation really refuses a
   non-contiguous member run. A stub that answered `ok` to everything would let a
   `derive_undo` that inverted to the wrong anchor pass;
2. **the rebuild-error count.** `Script.errors_after` says what the count reads **after**
   the n-th mutating call and every other call settles it back to the run's baseline, so
   "this change broke the tree and its inverse repaired it" is two lines of a fixture
   rather than a callback;
3. **the copy.** `open` re-creates the tree from the snapshot taken at construction, which
   is what a byte-for-byte re-copy of an unchanged source does, and `close_document` with
   `discard_copy` deletes it. The catastrophic replay is a real sequence here and not an
   assertion about intent.

Everything is keyed by the **mutating call ordinal**: `rename`, `reorder`, `folder`,
`describe` and `equation` each take one, `rebuild` takes none because it writes nothing.
A run with no rollback therefore makes ordinal N the N-th planned change, and a rollback
makes the inverse ordinal N+1, which is what lets a test say "the inverse itself fails"
without knowing anything about the executor's control flow.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from swreview.bridge.client import BridgeError
from swreview.bridge.remodel_client import (
    EQUATION_OPS,
    FOLDER_OPS,
    REORDER_LOCATIONS,
    CircuitOpen,
    RemodelAddressError,
    RemodelContractError,
    RemodelNotInV1Error,
)

__all__ = [
    "COPY_PATH",
    "DOCUMENT_ID",
    "SOURCE_PATH",
    "FakeRemodelBridge",
    "FakeTree",
    "Script",
    "StepClock",
    "tree",
]

SOURCE_PATH = r"C:\work\bracket.SLDPRT"
COPY_PATH = r"C:\runs\20260916-142201-bracket-remodel\copy\bracket-RMS.SLDPRT"


@dataclass
class FakeTree:
    """One part's tree, addressed the only way the protocol addresses anything.

    `folder_location` is `IFeatureManager.FeatureFolderLocation` as the host reads it back
    after a creation: member persistent reference to the folder name that now holds it.
    The host verifies it per member before answering `ok`, so a fake that did not record it
    would let a folder creation that wrapped nothing look like a success.
    """

    order: list[str]
    names: dict[str, str]
    descriptions: dict[str, str | None] = field(default_factory=dict)
    equations: list[str] = field(default_factory=list)
    folder_names: dict[str, str] = field(default_factory=dict)
    folder_members: dict[str, tuple[str, ...]] = field(default_factory=dict)
    folder_location: dict[str, str] = field(default_factory=dict)
    feature_errors: dict[str, int] = field(default_factory=dict)
    """`IFeature.GetErrorCode2` per feature, by persistent reference. A feature absent
    here reads `swFeatureErrorNone = 0`, which is the only value verification accepts."""

    feature_warnings: tuple[str, ...] = ()
    """The features whose error code comes back flagged as a warning by `GetErrorCode2`'s
    out Boolean. The flag is recorded and the **code** is what decides."""

    unreadable_equations: tuple[int, ...] = ()
    """The manager positions whose text reads back null. `Equation.text` is a string and
    `""` would be a default written over engineering data, so such a position carries no
    `equations[]` row and its index is named in `unreadable_equation_indexes[]` instead."""


def tree(*features: tuple[str, str], equations: Sequence[str] = ()) -> FakeTree:
    """A tree from `(persist_ref, name)` pairs in tree order, with no descriptions read.

    A description absent from `descriptions` reads back as `""` - absent, and readable -
    which is the only shape the planner lets a `describe` change reach the executor with.
    A test that wants "unreadable" writes `None` into `descriptions` by name.
    """
    return FakeTree(
        order=[ref for ref, _ in features],
        names={ref: name for ref, name in features},
        descriptions={ref: "" for ref, _ in features},
        equations=list(equations),
    )


@dataclass
class Script:
    """What the seat does, and at which mutating call. Every key is a call ordinal.

    `raises` and `rebuild_raises` carry the exception the bridge raises, already classified
    the way `bridge/remodel_client.py` classifies a host `error_code`, because that mapping
    is the client's job and this module is standing in for the host, not for the client.
    """

    raises: dict[int, BaseException] = field(default_factory=dict)
    """Ordinal to the refusal that call raises instead of doing anything."""

    rebuild_raises: dict[int, BaseException] = field(default_factory=dict)
    """Ordinal to the refusal the rebuild **after** that call raises."""

    errors_after: dict[int, int] = field(default_factory=dict)
    """Ordinal to the rebuild-error count the tree reads back at after that call. Every
    ordinal absent here settles back to the run's baseline, so a regression is one entry
    and its repair is the absence of the next one."""

    rebuild_ms_after: dict[int, int] = field(default_factory=dict)
    """Ordinal to the wall clock the rebuild after that call reports, in milliseconds."""

    circuit_open_at: int | None = None
    """The ordinal at which the bridge stops answering. The call is never sent."""

    circuit_open_on_rebuild_after: int | None = None
    """The mutating ordinal **after** which `remodel.rebuild` stops answering.

    The one case neither "refused" nor "landed" covers: the write went out and the reading
    after it did not come back. It is keyed by the ordinal of the write it follows, because
    that is the change the executor is in the middle of.
    """

    rebuild_omits: frozenset[str] = frozenset()
    """The members `remodel.rebuild` leaves out of its reply.

    A host that did not take a reading answers without it, and absent is not zero: every
    reader of this reply has to say it could not read rather than read a default.
    """

    equation_round_trip: dict[int, str] = field(default_factory=dict)
    """Ordinal to the `round_trip_text` the host answers with, whatever it wrote.

    PROBE-6 observed an add answering and adding nothing; this is the other half of the
    same doubt, a host that wrote one row and answered another, and it is what makes "the
    write is judged by the re-read, never by the answer" drivable from this end.
    """

    equation_wrote_nothing: frozenset[int] = frozenset()
    """The ordinals at which `remodel.equation` answers `ok` and writes nothing.

    PROBE-6 observed exactly this of `IEquationMgr.Add3`, and the count either side of the
    call is the only reading that catches it. Modelled for `op: "add"`, because that is the
    call the probe watched and the one whose delta says whether a row exists to undo.
    """

    folder_members_answered: dict[int, tuple[str, ...]] = field(default_factory=dict)
    """Ordinal to the members the host actually wraps, whatever the request asked for.

    A folder that wrapped a narrower run and answered with the asked-for name is exactly
    what `IFeatureManager.FeatureFolderLocation` is read per member to catch, so the fake
    has to be able to do it.
    """

    geometry_raises: dict[int, BaseException] = field(default_factory=dict)
    """Reading ordinal to the refusal that reading raises instead of measuring anything.

    `remodel.geometry` writes nothing, so it takes no mutating ordinal; it is keyed by its
    own, counted from 1, because a run takes exactly two - the copy at open and the copy
    at end - and which of the two failed is the whole question."""

    save_raises: BaseException | None = None
    """What `remodel.save` raises: `save_failed` for a non-zero `errors`, for a
    `swFileSaveWarning_RebuildError` warning and for a `GetSaveFlag()` still set
    afterwards. The copy is saved once, at the end, so one slot is enough."""


class StepClock:
    """A clock that advances a fixed number of seconds per reading.

    The executor's wall-clock limit and its `elapsed_ms` come from one injected clock, so a
    test drives both by counting readings rather than by sleeping.
    """

    def __init__(self, start: datetime, step_seconds: float) -> None:
        self._at = start
        self._step = step_seconds
        self.readings = 0

    def __call__(self) -> datetime:
        now = self._at
        self._at = self._at + timedelta(seconds=self._step)
        self.readings += 1
        return now


class FakeRemodelBridge:
    """The host end of `remodel.*`, offline: a tree, a rebuild count, and a script."""

    def __init__(
        self,
        part: FakeTree,
        *,
        baseline: int = 0,
        script: Script | None = None,
        rebuild_ms: int = 40,
        copy_path: str = COPY_PATH,
        source_path: str = SOURCE_PATH,
        readings: Sequence[Mapping[str, Any]] = (),
    ) -> None:
        self._opened_with = copy.deepcopy(part)
        self.tree = copy.deepcopy(part)
        self.baseline = baseline
        self.script = script or Script()
        self.default_rebuild_ms = rebuild_ms
        self.copy_path = copy_path
        self.source_path = source_path
        self.readings = [dict(row) for row in readings]
        """What `remodel.geometry` answers, in the order the run asks: the measurement
        only, because the subject is the host's to stamp."""

        self.rebuild_errors = baseline
        self.rebuild_ms = rebuild_ms
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.mutations = 0
        self.rebuilds = 0
        self.opens = 0
        self.discards = 0
        self.saves = 0
        self.geometry_readings = 0
        self.copy_exists = True
        self.closed = False

    # --- what a test reads back ---------------------------------------------------

    @property
    def commands(self) -> tuple[str, ...]:
        """Every command sent, in order, rebuilds included."""
        return tuple(command for command, _ in self.calls)

    @property
    def mutating_calls(self) -> tuple[tuple[str, dict[str, Any]], ...]:
        """Every call that writes, in order. One per change, plus one per inverse."""
        return tuple(call for call in self.calls if call[0] not in _READS)

    # --- the two commands that run before the scope exists -------------------------

    def open(
        self, source_path: str, copy_path: str, run_id: str, probe_id: str
    ) -> dict[str, Any]:
        """Copy the source and open the copy: the tree comes back as it was at open.

        That is what a byte-for-byte re-copy of an unchanged source produces, which is the
        property the catastrophic replay rests on. A copy that already exists is
        `copy_exists` on the wire; here it is an assertion, because a replay that did not
        delete the copy first is a defect in the caller and not a condition to model.
        """
        assert not self.copy_exists, "the copy was not deleted before it was re-made"
        self.calls.append(
            (
                "remodel.open",
                {
                    "source_path": source_path,
                    "copy_path": copy_path,
                    "run_id": run_id,
                    "probe_id": probe_id,
                },
            )
        )
        self.opens += 1
        self.tree = copy.deepcopy(self._opened_with)
        self.rebuild_errors = self.baseline
        self.rebuild_ms = self.default_rebuild_ms
        self.copy_exists = True
        self.closed = False
        return {
            "document_path": copy_path,
            "tag": f"{run_id}:{self.opens}",
            "feature_count": len(self.tree.order),
            "scope_signals": {},
            "configurations": ["Default"],
            "document_length_unit": "mm",
            "source_attestation": {},
        }

    def close_document(self, discard_copy: bool) -> dict[str, Any]:
        """Close the copy without saving; `discard_copy` deletes the part file."""
        self.calls.append(("remodel.close", {"discard_copy": discard_copy}))
        self.closed = True
        if discard_copy:
            self.discards += 1
            self.copy_exists = False
        return {"closed": True, "copy_deleted": discard_copy}

    # --- the five that write --------------------------------------------------------

    def rename(self, persist_ref: str, new_name: str) -> Any:
        sent = self._begin("remodel.rename", {"persist_ref": persist_ref, "new_name": new_name})
        if sent is not None:
            return sent
        previous = self._named(persist_ref)
        if persist_ref in self.tree.folder_names:
            self.tree.folder_names[persist_ref] = new_name
        else:
            self.tree.names[persist_ref] = new_name
        self._settle()
        return {"previous_name": previous, "new_name": new_name}

    def reorder(
        self, feature_persist_ref: str, anchor_persist_ref: str, location: str
    ) -> Any:
        params = {
            "feature_persist_ref": feature_persist_ref,
            "anchor_persist_ref": anchor_persist_ref,
            "location": location,
        }
        if location not in REORDER_LOCATIONS:
            raise BridgeError(
                f"location={location!r} is not one of {sorted(REORDER_LOCATIONS)}; "
                "swMoveLocation_e carries Before and After and v1 composes no third value"
            )
        sent = self._begin("remodel.reorder", params)
        if sent is not None:
            return sent
        order = self.tree.order
        moving = self._positioned(feature_persist_ref)
        self._positioned(anchor_persist_ref)
        previous_anchor, previous_location = self._neighbour(moving)
        previous_index = moving
        order.pop(moving)
        anchor = order.index(anchor_persist_ref)
        order.insert(anchor if location == "before" else anchor + 1, feature_persist_ref)
        self._settle()
        return {
            "previous_anchor_persist_ref": previous_anchor,
            "previous_location": previous_location,
            "previous_index": previous_index,
            "new_index": order.index(feature_persist_ref),
        }

    def folder(
        self,
        op: str,
        name: str | None = None,
        member_persist_refs: list[str] | None = None,
        folder_persist_ref: str | None = None,
    ) -> Any:
        members = tuple(member_persist_refs or ())
        params = {
            "op": op,
            "name": name,
            "member_persist_refs": list(members),
            "folder_persist_ref": folder_persist_ref,
        }
        if op not in FOLDER_OPS:
            raise BridgeError(f"op={op!r} is not one of {sorted(FOLDER_OPS)}")
        sent = self._begin("remodel.folder", params)
        if sent is not None:
            return sent
        if op == "dissolve":
            raise RemodelNotInV1Error(
                "dissolving a folder is reserved for stage 2", "not_in_v1", {}
            )
        if op == "create":
            ref = self._wrap(str(name), members)
        else:
            ref = str(folder_persist_ref)
            if ref not in self.tree.folder_names:
                raise RemodelAddressError(
                    f"{ref} does not resolve to a folder", "persist_ref_unresolved", {}
                )
            self.tree.folder_names[ref] = str(name)
            for member in self.tree.folder_members[ref]:
                self.tree.folder_location[member] = str(name)
        self._settle()
        return {
            "folder_persist_ref": ref,
            "name": self.tree.folder_names[ref],
            "member_persist_refs": list(self.tree.folder_members[ref]),
        }

    def describe(self, persist_ref: str, text: str) -> Any:
        sent = self._begin("remodel.describe", {"persist_ref": persist_ref, "text": text})
        if sent is not None:
            return sent
        self._positioned(persist_ref)
        previous = self.tree.descriptions.get(persist_ref, "")
        self.tree.descriptions[persist_ref] = text
        self._settle()
        return {"previous_text": previous}

    def equation(
        self,
        op: str,
        index: int | None = None,
        text: str | None = None,
        which_configs: int | None = None,
    ) -> Any:
        params = {"op": op, "index": index, "text": text, "which_configs": which_configs}
        if op not in EQUATION_OPS:
            raise BridgeError(f"op={op!r} is not one of {sorted(EQUATION_OPS)}")
        sent = self._begin("remodel.equation", params)
        if sent is not None:
            return sent
        equations = self.tree.equations
        count_before = len(equations)
        if self.mutations in self.script.equation_wrote_nothing:
            self._settle()
            return {
                "index": count_before if index is None else index,
                "count_before": count_before,
                "count_after": count_before,
                "previous_text": None,
                "round_trip_text": str(text),
                "helper_path": "add3",
            }
        if op == "add":
            at = count_before if index is None else index
            equations.insert(at, str(text))
            previous, round_trip, helper = None, equations[at], "add3"
        elif op == "set":
            at = self._equation(index)
            previous, equations[at] = equations[at], str(text)
            round_trip, helper = equations[at], "set_equation"
        else:
            at = self._equation(index)
            previous = equations.pop(at)
            round_trip, helper = None, "delete"
        self._settle()
        return {
            "index": at,
            "count_before": count_before,
            "count_after": len(equations),
            "previous_text": previous,
            "round_trip_text": self.script.equation_round_trip.get(
                self.mutations, round_trip
            ),
            "helper_path": helper,
        }

    # --- the two that read ----------------------------------------------------------

    def snapshot(self) -> Any:
        """`remodel.snapshot`: the tree as it stands, in the same shape before and after
        every change. It writes nothing, so it takes no ordinal.

        `equations[]` mirrors the IR `Equation` shape, and a position named in
        `unreadable_equations` carries **no** row: its index is reported in
        `unreadable_equation_indexes[]` instead, so the surviving rows keep the indexes the
        manager addresses them by and the list is shorter on exactly those positions.
        """
        self.calls.append(("remodel.snapshot", {}))
        literals = _literals(self.tree.equations)
        return {
            "order": list(self.tree.order),
            "names": dict(self.tree.names),
            "descriptions": dict(self.tree.descriptions),
            "equations": [
                {
                    "document_id": DOCUMENT_ID,
                    "index": index,
                    "text": text,
                    "lhs": text.split("=", 1)[0].strip().strip('"'),
                    "is_global": '"' in text.split("=", 1)[0] and "@" not in text,
                    "value": _value(text, literals),
                }
                for index, text in enumerate(self.tree.equations)
                if index not in self.tree.unreadable_equations
            ],
            "unreadable_equation_indexes": list(self.tree.unreadable_equations),
            "rebuild_errors": self.rebuild_errors,
            "feature_count": len(self.tree.order),
        }

    def rebuild(self, force: bool = False) -> Any:
        """`ForceRebuild3(force)` and the error reading. It writes nothing, so it takes no
        ordinal: a script names the change it follows, never a rebuild of its own."""
        self.calls.append(("remodel.rebuild", {"force": force}))
        self.rebuilds += 1
        if self.script.circuit_open_on_rebuild_after == self.mutations:
            return CircuitOpen(
                command="remodel.rebuild", last_error="the bridge stopped answering"
            )
        refusal = self.script.rebuild_raises.get(self.mutations)
        if refusal is not None:
            raise refusal
        reply = {
            "rebuild_errors": self.rebuild_errors,
            "whats_wrong": [f"error {n + 1}" for n in range(self.rebuild_errors)],
            "elapsed_ms": self.rebuild_ms,
            "feature_errors": [
                {
                    "persist_ref": ref,
                    "name": self.tree.names[ref],
                    "error_code": self.tree.feature_errors.get(ref, 0),
                    "is_warning": ref in self.tree.feature_warnings,
                }
                for ref in self.tree.order
            ],
        }
        return {
            key: value
            for key, value in reply.items()
            if key not in self.script.rebuild_omits
        }

    def geometry(self) -> Any:
        """One `GeometryReading` of the copy, with the **subject stamped by the host**.

        It takes no parameters because there is nothing to name: the first reading of a
        run is the copy at open and every later one is the copy at end, so a caller
        cannot ask for a reading of anything else - which is the whole property
        `contracts/bridge-remodel.md` gives this command.
        """
        self.calls.append(("remodel.geometry", {}))
        index = self.geometry_readings
        self.geometry_readings += 1
        refusal = self.script.geometry_raises.get(index + 1)
        if refusal is not None:
            raise refusal
        assert index < len(self.readings), (
            f"reading {index + 1} was asked for and this fake was built with "
            f"{len(self.readings)}; a measurement nobody configured is not a zero"
        )
        subject = "copy_at_open" if index == 0 else "copy_at_end"
        return {**self.readings[index], "subject": subject}

    def save(self, verdict: str) -> Any:
        """`Save3` behind the gate, which is checked here as well as by the caller.

        The host refuses `gate_not_passed` on anything but a `pass` **and** on a `pass`
        reported by a run it did not take both readings for; the constitution's mutation
        exception is enforced beside the save, because a clause checked solely by the
        caller is a clause the caller can skip.
        """
        self.calls.append(("remodel.save", {"verdict": verdict}))
        if verdict != "pass" or self.geometry_readings < 2:
            raise RemodelContractError(
                f"the copy is not saved: the reported verdict is {verdict!r} and this run "
                f"took {self.geometry_readings} geometry reading(s)",
                "gate_not_passed",
                {"verdict": verdict},
            )
        refusal = self.script.save_raises
        if refusal is not None:
            raise refusal
        self.saves += 1
        return {
            "path": self.copy_path,
            "errors": 0,
            "warnings": 0,
            "save_flag_after": False,
        }

    # --- the script -----------------------------------------------------------------

    def _begin(self, command: str, params: dict[str, Any]) -> CircuitOpen | None:
        """Take the next ordinal and let the script answer first.

        A refusal raises before the tree is touched and before `_settle`, so a change that
        the host refused leaves both the tree and the error count exactly where they were,
        which is what `status: "failed"` claims on the executor's side.
        """
        self.mutations += 1
        self.calls.append((command, dict(params)))
        if self.script.circuit_open_at == self.mutations:
            return CircuitOpen(command=command, last_error="the bridge stopped answering")
        refusal = self.script.raises.get(self.mutations)
        if refusal is not None:
            raise refusal
        return None

    def _settle(self) -> None:
        """What the tree reads back at after the call that just landed."""
        self.rebuild_errors = self.script.errors_after.get(self.mutations, self.baseline)
        self.rebuild_ms = self.script.rebuild_ms_after.get(
            self.mutations, self.default_rebuild_ms
        )

    # --- resolving, the only way v1 resolves ------------------------------------------

    def _positioned(self, persist_ref: str) -> int:
        if persist_ref not in self.tree.order:
            raise RemodelAddressError(
                f"{persist_ref} no longer resolves to a feature",
                "persist_ref_unresolved",
                {"persist_ref": persist_ref},
            )
        return self.tree.order.index(persist_ref)

    def _named(self, persist_ref: str) -> str:
        if persist_ref in self.tree.folder_names:
            return self.tree.folder_names[persist_ref]
        self._positioned(persist_ref)
        return self.tree.names[persist_ref]

    def _neighbour(self, position: int) -> tuple[str, str]:
        """The anchor the feature currently sits beside, and the side it sits on."""
        order = self.tree.order
        if len(order) < 2:
            raise ValueError("a tree of one feature has nothing to reorder against")
        if position > 0:
            return order[position - 1], "after"
        return order[position + 1], "before"

    def _equation(self, index: int | None) -> int:
        if index is None:
            raise RemodelContractError(
                "set and delete name the equation they change", "bad_request", {}
            )
        if not 0 <= index < len(self.tree.equations):
            raise RemodelContractError(
                f"there is no equation at {index}", "bad_request", {"index": index}
            )
        return index

    def _wrap(self, name: str, members: tuple[str, ...]) -> str:
        """Select a contiguous run, wrap it, name it, and record the folder location.

        Contiguity is proven by the planner and re-proven here, because the host refuses a
        non-contiguous request rather than attempting one: a selection that is not a run is
        a folder around the wrong features, and there is no inverse for that in v1.

        `folder_members_answered` is the host wrapping something other than what was asked
        for: the folder really holds those members and the reply really names the asked-for
        folder name, which is the shape a member-by-member reading has to catch.
        """
        members = self.script.folder_members_answered.get(self.mutations, members)
        positions = [self._positioned(member) for member in members]
        if not positions:
            raise RemodelContractError(
                "a folder wraps at least one feature", "bad_request", {}
            )
        if sorted(positions) != list(range(min(positions), min(positions) + len(positions))):
            raise RemodelContractError(
                f"{list(members)} is not a contiguous run of the current tree order",
                "folder_members_not_contiguous",
                {"member_persist_refs": list(members)},
            )
        ref = f"folder:{len(self.tree.folder_names) + 1}"
        self.tree.folder_names[ref] = name
        self.tree.folder_members[ref] = members
        for member in members:
            self.tree.folder_location[member] = name
        return ref


_READS: frozenset[str] = frozenset({"remodel.rebuild", "remodel.snapshot", "remodel.geometry"})
"""The commands that write nothing and therefore take no ordinal."""

DOCUMENT_ID = "doc:copy"
"""The copy's document id, as an `equations[]` row carries it: the only document a run
can reach, because `RemodelScope` holds the one handle that exists."""

_ARITHMETIC = frozenset("0123456789.+-*/() ")
"""Everything a right-hand side may still contain once its references are substituted."""


def _literals(equations: Sequence[str]) -> dict[str, float]:
    """Every row that declares a bare number, as its quoted name to that number."""
    values: dict[str, float] = {}
    for row in equations:
        name, _, expression = row.partition("=")
        try:
            values[name.strip()] = float(expression)
        except ValueError:
            continue
    return values


def _value(text: str, literals: dict[str, float]) -> float | None:
    """`IEquationMgr.get_Value(i)` as the manager would answer it, references resolved.

    One level of resolution, which is as far as a v1 global goes: a row whose right-hand
    side is a bare number is a value another row's expression may name. `None` is a value
    that will not evaluate, which the executor refuses rather than recording as a zero.
    """
    if "=" not in text:
        return None
    right = text.split("=", 1)[1]
    for name, value in literals.items():
        right = right.replace(name, repr(value))
    if not right.strip() or set(right) - _ARITHMETIC:
        return None
    try:
        return float(eval(right, {"__builtins__": {}}, {}))
    except (ArithmeticError, SyntaxError, TypeError, ValueError):
        return None
