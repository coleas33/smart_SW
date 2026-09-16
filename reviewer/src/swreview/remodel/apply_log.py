"""`changes.jsonl`: the `ChangeRecord`, the append-only writer, and `derive_undo` (T075).

This is the run's undo record and the change list the pane shows, and it is one file
written by one writer. `data-model.md` section 2 is normative for every field name here
and this module spells none of its own.

Three properties live in the types rather than at the call sites:

- **two lines per change.** One goes out *before* the bridge call with
  `status: "attempting"` and one after it with a terminal status, so a hard crash
  mid-change leaves exactly one `attempting` line naming what was in flight. The model
  refuses an `attempting` line carrying an outcome and a terminal line missing one, and
  `ApplyLog` refuses a second `attempting` while one is still in flight, so "exactly one"
  is a property of the writer and not of the caller's discipline;
- **append-only, monotonic `seq`.** A line never rewrites an earlier one. A re-opened log
  reads what is already on disk and continues from it rather than truncating, because the
  run folder is the unit and the file is the only record of what the run touched;
- **five statuses, and the fifth is not a dressed-up `failed`.** `failed` means the change
  never landed and the tree is where it was; `rollback_failed` means it landed, raised the
  rebuild-error count and could **not** be undone. Only `rollback_failed` ends the run, so
  `ENDS_THE_RUN` says which one here rather than in the executor's control flow.

`rebuild_errors_after` and `elapsed_ms` are `null` on the `attempting` line because neither
has been read yet, and writing `0` into a reading that has not happened is exactly the
default over engineering data the constitution forbids (Principle I).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, model_validator

from swreview.remodel.plan import CHANGE_ORDER, ChangeKind, ChangeSubject

__all__ = [
    "CHANGES_FILE_NAME",
    "ENDS_THE_RUN",
    "ESCALATES_TO_REPLAY",
    "RECORD_KINDS",
    "STATUSES",
    "TERMINAL_STATUSES",
    "ApplyLog",
    "ChangeRecord",
    "RecordKind",
    "Status",
    "UndoCommand",
    "changes_path",
    "derive_undo",
    "in_flight",
    "read_changes",
]

CHANGES_FILE_NAME = "changes.jsonl"
"""The file, in the run folder (`contracts/run-artifacts.md`). One spelling, here."""

RecordKind = ChangeKind | Literal["save"]
"""Every kind the planner emits, plus the one it never does.

`save` is not a `PlannedChange`: the copy is saved once, at the end, only after the gate
passes, so it is a change the run records and never a change the plan proposes.
`folder.dissolve` is reserved for stage 2 and is written by nothing in v1."""

RECORD_KINDS: tuple[str, ...] = (*CHANGE_ORDER, "save")
"""The eight, in the plan's fixed order with `save` last, which is when it happens."""

Status = Literal["attempting", "applied", "failed", "rolled_back", "rollback_failed"]

STATUSES: tuple[str, ...] = get_args(Status)

TERMINAL_STATUSES: frozenset[str] = frozenset(STATUSES) - {"attempting"}
"""What may follow an `attempting` line and close a change out."""

ENDS_THE_RUN: frozenset[str] = frozenset({"rollback_failed"})
"""The one outcome the run cannot continue past (T080).

A `failed` change never landed, so the tree is where it was and the next change is safe to
attempt. A `rollback_failed` change landed, raised the error count above the run's baseline
and could not be undone, so nothing after it can be attributed to anything."""

ESCALATES_TO_REPLAY: frozenset[str] = frozenset({"folder.create"})
"""The kind with no forward inverse whose failure goes straight to the tier-2 fallback.

Dissolving a folder needs `IModelDoc2.EditDelete`, which the owner kept off the stage-1
allowlist, so a folder creation that has to be taken back is taken back by deleting the
copy, re-copying the source and replaying `changes.jsonl` up to the last `applied` line.
`save` also has no inverse and is **not** here: the copy is saved once, at the end, only
after the gate passes, so there is nothing after it to take back."""

_MODEL = ConfigDict(strict=True, extra="forbid", frozen=True)


class _Model(BaseModel):
    """Strict, frozen, closed: an unexpected field is a defect, not something to carry."""

    model_config = _MODEL


class UndoCommand(_Model):
    """The exact inverse: a `remodel.*` command and the parameters it takes.

    `params` is the command's whole payload, keyed exactly as `bridge/remodel_client.py`
    names its arguments, so the caller applies an inverse by calling the client with it
    and never by composing a second idea of the operation.
    """

    command: str
    params: dict[str, Any]


class ChangeRecord(_Model):
    """One line of `changes.jsonl` (`data-model.md` section 2).

    The field order is the document's, so the file an engineer opens reads as documented.
    """

    seq: int = Field(ge=1)
    at: str
    kind: RecordKind
    subject: ChangeSubject | None
    before: dict[str, Any]
    after: dict[str, Any]
    undo: UndoCommand | None
    rebuild_errors_before: int = Field(ge=0)
    rebuild_errors_after: int | None = Field(ge=0)
    status: Status
    error_code: str | None
    error: str | None
    target_path: str
    elapsed_ms: int | None = Field(ge=0)

    @model_validator(mode="after")
    def _outcome_matches_the_status(self) -> ChangeRecord:
        if self.status == "attempting":
            unknown = {
                "rebuild_errors_after": self.rebuild_errors_after,
                "elapsed_ms": self.elapsed_ms,
                "error_code": self.error_code,
                "error": self.error,
                "undo": self.undo,
            }
            carried = sorted(name for name, value in unknown.items() if value is not None)
            if carried:
                raise ValueError(
                    f"change {self.seq} is attempting and carries {carried}; the line is "
                    "written before the bridge call, so nothing about the outcome has "
                    "been read yet and null is what that is"
                )
            return self
        for name in ("rebuild_errors_after", "elapsed_ms"):
            if getattr(self, name) is None:
                raise ValueError(
                    f"change {self.seq} is {self.status} with no {name}; a terminal line "
                    "records the reading the status was reached from"
                )
        if self.status == "applied" and (self.error_code or self.error):
            raise ValueError(
                f"change {self.seq} applied and carries an error; `error_code` is the "
                "bridge's token when the change failed, and null when it did not"
            )
        return self

    @model_validator(mode="after")
    def _save_names_nothing(self) -> ChangeRecord:
        if self.kind == "save" and self.subject is not None:
            raise ValueError(
                f"change {self.seq} is a save and names {self.subject.name!r}; the copy is "
                "saved once, at the end, and there is no feature for that record to name"
            )
        return self


def changes_path(run_dir: Path | str) -> Path:
    """Where the change log of `run_dir` lives."""
    return Path(run_dir) / CHANGES_FILE_NAME


def read_changes(path: Path | str) -> tuple[ChangeRecord, ...]:
    """Every line of a change log, in the order it was written.

    A file that is not there yet is a run that has changed nothing, which is `()` and not
    an error: the writer creates the file on its first line.
    """
    file = Path(path)
    if not file.exists():
        return ()
    return tuple(
        ChangeRecord.model_validate(json.loads(line))
        for line in file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )


def in_flight(records: tuple[ChangeRecord, ...]) -> ChangeRecord | None:
    """The `attempting` line with no terminal partner, or `None`.

    This is what a reader recovering a crashed run finds. It is the change that was in
    flight when the process died, and it is **never** treated as applied: whether the
    write landed is exactly what the missing second line does not say.
    """
    pending: ChangeRecord | None = None
    for record in records:
        if record.status == "attempting":
            pending = record
        elif pending is not None and record.seq == pending.seq:
            pending = None
    return pending


class ApplyLog:
    """The append-only writer for one run's `changes.jsonl`.

    Opened and closed per line, in append mode, for the reason `mcp/chat_log.py` gives:
    the pane and a text editor can read a complete file at any moment rather than whatever
    happened to have been flushed, and the cost of a handle per change is nothing beside a
    rebuild. A write that fails is not swallowed, because a change nothing recorded is a
    change nothing can undo.
    """

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        written = read_changes(self.path)
        self._last_seq = written[-1].seq if written else 0
        self._in_flight = in_flight(written)

    def append(self, record: ChangeRecord) -> None:
        """Write one line, or refuse it. Never rewrites a line already on disk."""
        self._admissible(record)
        line = json.dumps(record.model_dump(mode="json"), ensure_ascii=False)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(line + "\n")
        self._in_flight = record if record.status == "attempting" else None
        self._last_seq = record.seq

    def _admissible(self, record: ChangeRecord) -> None:
        """The two rules the file's shape rests on: the pair, and a monotonic `seq`."""
        if self._in_flight is not None:
            if record.seq != self._in_flight.seq or record.status == "attempting":
                raise ValueError(
                    f"change {self._in_flight.seq} is in flight and {record.seq} "
                    f"({record.status}) was written; one attempting line at a time is "
                    "what makes a crashed run's last line unambiguous"
                )
            return
        if record.status != "attempting":
            raise ValueError(
                f"change {record.seq} is {record.status} and was never attempting; every "
                "change is announced before the bridge call and closed out after it"
            )
        if record.seq <= self._last_seq:
            raise ValueError(
                f"change {record.seq} follows {self._last_seq}; `seq` is monotonic within "
                "a run and the file is append-only, so a line never revisits an earlier one"
            )


# --- the inverse, one pure function ------------------------------------------------


def _persist_ref(change: ChangeRecord) -> str:
    """The object the inverse acts on, addressed the only way v1 addresses anything."""
    if change.subject is None or not change.subject.persist_ref:
        raise ValueError(
            f"change {change.seq} is a {change.kind} with no persistent reference; an "
            "inverse addresses the same object the change did, never a name or an index "
            "the change itself may have moved"
        )
    return change.subject.persist_ref


def _recorded(change: ChangeRecord, side: str, key: str, what: str) -> Any:
    """One value the bridge reported, or a refusal naming what is missing.

    Every inverse is built from a reading. A missing reading has no inverse, and a value
    invented in its place would write something the part never carried.
    """
    value = getattr(change, side).get(key)
    if value is None:
        raise ValueError(
            f"change {change.seq} is a {change.kind} whose {side}.{key} is unreadable, so "
            f"{what} cannot be inverted; the bridge returns this reading precisely so the "
            "inverse is never a guess"
        )
    return value


def _rename(change: ChangeRecord) -> UndoCommand:
    """Rename back to the name the bridge reported as `previous_name`."""
    return UndoCommand(
        command="remodel.rename",
        params={
            "persist_ref": _persist_ref(change),
            "new_name": _recorded(change, "before", "name", "a previous name"),
        },
    )


def _reorder(change: ChangeRecord) -> UndoCommand:
    """Reorder back to the anchor it sat beside, on the side it sat on."""
    location = _recorded(change, "before", "location", "a previous location")
    if location not in _LOCATIONS:
        raise ValueError(
            f"change {change.seq} recorded location {location!r}; the set is closed at "
            f"{sorted(_LOCATIONS)} and the guard refuses every other composition"
        )
    return UndoCommand(
        command="remodel.reorder",
        params={
            "feature_persist_ref": _persist_ref(change),
            "anchor_persist_ref": _recorded(
                change, "before", "anchor_persist_ref", "a previous anchor"
            ),
            "location": location,
        },
    )


def _folder_rename(change: ChangeRecord) -> UndoCommand:
    """Rename the folder back, addressed by its own reference: the `___EndTag___` marker
    keeps the folder's default name after a rename, so a name would be ambiguous."""
    return UndoCommand(
        command="remodel.folder",
        params={
            "op": "rename",
            "name": _recorded(change, "before", "name", "a previous name"),
            "member_persist_refs": [],
            "folder_persist_ref": _persist_ref(change),
        },
    )


def _describe(change: ChangeRecord) -> UndoCommand:
    """Write the previous text back, the empty string included.

    `""` is "read, and empty" and is written back exactly. `null` is "unreadable", and a
    feature carrying one is refused by the planner before the change is attempted; the
    refusal is repeated here so no path exists by which `""` is written over something
    nobody could read.
    """
    text = change.before.get("text")
    if not isinstance(text, str):
        raise ValueError(
            f"change {change.seq} describes a feature whose previous description is "
            "unreadable; an empty description is a reading and a missing one is not, so "
            "writing one over the other is a silent edit with no way back"
        )
    return UndoCommand(
        command="remodel.describe",
        params={"persist_ref": _persist_ref(change), "text": text},
    )


def _equation_add(change: ChangeRecord) -> UndoCommand:
    """`IEquationMgr.Delete(index)` at the index this add landed at.

    Only ever the inverse of an add this run made: the index is read from that add's own
    record, so nothing here can address an equation the part already had. The executor
    applies these in reverse order of addition, because deleting a lower index first
    renumbers every higher one. `which_configs` is null on a delete, which addresses an
    equation that already exists and changes no configuration scope.
    """
    return UndoCommand(
        command="remodel.equation",
        params={
            "op": "delete",
            "index": _recorded(change, "after", "index", "the equation this run added"),
            "text": None,
            "which_configs": None,
        },
    )


def _equation_edit(change: ChangeRecord) -> UndoCommand:
    """An in-place `set` back to the previous text: the inverse of an edit is another edit.

    A delete plus an add would remove a referenced global, and every equation depending on
    it enters an error state that does not clear when it returns (research.md R3.5), which
    is exactly why FR-029's repair is its own kind.
    """
    return UndoCommand(
        command="remodel.equation",
        params={
            "op": "set",
            "index": _recorded(change, "before", "index", "an equation position"),
            "text": _recorded(
                change, "before", "equation_text", "a previous equation text"
            ),
            "which_configs": _recorded(
                change, "before", "which_configs", "a configuration scope"
            ),
        },
    )


_LOCATIONS: frozenset[str] = frozenset({"before", "after"})
"""`swMoveLocation_e.Before = 2` and `After = 3`, the only two v1 composes."""

_INVERSE: Mapping[str, Callable[[ChangeRecord], UndoCommand] | None] = {
    "rename": _rename,
    "describe": _describe,
    "reorder": _reorder,
    "folder.create": None,
    "folder.rename": _folder_rename,
    "equation.edit": _equation_edit,
    "equation.add": _equation_add,
    "save": None,
}
"""Every kind, including the two whose inverse is `None`, so nothing falls off the end.

`data-model.md` section 2.1 is this table in prose; a kind missing from here would be
answered "no inverse" by a `dict.get`, and "there is no inverse" and "this module has not
heard of that kind" are different answers."""


def derive_undo(change: ChangeRecord) -> UndoCommand | None:
    """The exact inverse of one recorded change, or `None` where v1 has none.

    Pure: a record in, a command out. It reads nothing but the record, so every row of
    `data-model.md` section 2.1 is table-testable with no seat, and the executor applies
    an inverse by handing `params` to `RemodelClient` rather than composing a second idea
    of the operation.

    `None` is a deliberate value and means "no in-place inverse exists": `folder.create`,
    whose dissolve is not allowlisted in v1 and which therefore escalates to the tier-2
    replay (`ESCALATES_TO_REPLAY`), and `save`, which is the last thing the run does.
    `IModelDoc2.EditUndo2` is produced by nothing here: it returns void, so a caller cannot
    tell whether it did anything, and it shares the UI undo stack the engineer can touch.
    """
    if change.kind not in _INVERSE:
        raise ValueError(
            f"{change.kind!r} is not a change kind this version writes; the kinds are "
            f"{list(RECORD_KINDS)} and a dissolve is reserved for stage 2"
        )
    inverse = _INVERSE[change.kind]
    return None if inverse is None else inverse(change)
