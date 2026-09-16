"""Unit tests for `derive_undo`, one per change kind (feature 004 T076).

`derive_undo` is the whole of tier 1 of the undo story: the per-change forward inverse,
which is what lets a run continue past one bad change instead of throwing the copy away.
It is **pure** - a `ChangeRecord` in, a `UndoCommand` or `None` out, no bridge, no clock,
no seat - so every inverse in `data-model.md` section 2.1 is table-testable here.

The rules each test below pins, and why each is a rule rather than a preference:

- an inverse is derived from **what was recorded**, never from what was intended. The
  bridge returns the previous name, the previous anchor and the previous text precisely so
  that the inverse is a reading and not a guess;
- **`describe` with a `before` of `null` is refused.** `null` is "unreadable", `""` is
  "read, and empty", and writing `""` over something unreadable is a silent edit with no
  way back. The planner refuses such a feature up front; this refuses it again here, so
  the rule holds even if a record for one is somehow built;
- **`equation.edit` inverts to another in-place `set`**, never to a delete plus an add: a
  delete removes a referenced global and puts every dependent equation into an error state
  that does not clear when the global returns (research.md R3.5, FR-029);
- **`equation.add` inverts to a delete of the index the add landed at**, applied in reverse
  order of addition so the earlier indexes are still the equations they were;
- **`folder.create` has no forward inverse in v1.** Dissolving needs `IModelDoc2.EditDelete`,
  which the owner kept off the stage-1 allowlist, so a failed creation escalates to the
  catastrophic replay. `None` is that answer, and it is a deliberate value;
- **`save` has no inverse** because the copy is saved once, at the end, only after the gate
  passes;
- **`EditUndo2` is never produced by anything.** It returns void, so a caller cannot tell
  whether it did anything, and it shares the UI undo stack the engineer can also touch.

Offline: no SOLIDWORKS, no bridge, no provider.
"""

from __future__ import annotations

import inspect
from typing import Any

import pytest

from swreview.bridge.remodel_client import (
    EQUATION_OPS,
    FOLDER_OPS,
    REMODEL_COMMANDS,
    REORDER_LOCATIONS,
    RemodelClient,
)
from swreview.remodel.apply_log import (
    ESCALATES_TO_REPLAY,
    RECORD_KINDS,
    ChangeRecord,
    RecordKind,
    UndoCommand,
    derive_undo,
)
from swreview.remodel.plan import ChangeSubject

COPY_PATH = r"C:\runs\20260916-142201-bracket-remodel\copy\bracket-RMS.SLDPRT"
FEATURE_REF = "<b64 feature>"


def applied(
    kind: RecordKind,
    before: dict[str, Any],
    after: dict[str, Any] | None = None,
    *,
    subject: ChangeSubject | None = None,
    seq: int = 1,
) -> ChangeRecord:
    """A change that landed, with the state the bridge reported around it."""
    return ChangeRecord(
        seq=seq,
        at="2026-09-16T14:22:31.481Z",
        kind=kind,
        subject=(
            subject
            if subject is not None or kind == "save"
            else ChangeSubject(feature_id="feat:0042", name="Fillet3", persist_ref=FEATURE_REF)
        ),
        before=before,
        after={} if after is None else after,
        undo=None,
        rebuild_errors_before=0,
        rebuild_errors_after=0,
        status="applied",
        error_code=None,
        error=None,
        target_path=COPY_PATH,
        elapsed_ms=310,
    )


def client_arguments(method: str) -> set[str]:
    """The keyword names one `RemodelClient` command takes, `self` aside.

    An inverse is applied by handing `params` to the client, so the two are asserted to be
    the same set: a params dict the client cannot be called with is not an inverse.
    """
    names = inspect.signature(getattr(RemodelClient, method)).parameters
    return {name for name in names if name != "self"}


# --- 1. rename ----------------------------------------------------------------------


def test_rename_inverts_to_the_recorded_previous_name() -> None:
    """`Fillet1` became `Fillet1_2`; the inverse writes `Fillet1` back to the same object."""
    change = applied("rename", before={"name": "Fillet1"}, after={"name": "Fillet1_2"})

    undo = derive_undo(change)

    assert undo == UndoCommand(
        command="remodel.rename",
        params={"persist_ref": FEATURE_REF, "new_name": "Fillet1"},
    )
    assert set(undo.params) == client_arguments("rename")


def test_a_rename_with_no_recorded_previous_name_is_refused() -> None:
    """The bridge returns `previous_name` so nothing has to guess it; a record without it
    has no inverse, and inventing one would rename a feature to something it never was."""
    with pytest.raises(ValueError, match="previous name"):
        derive_undo(applied("rename", before={}, after={"name": "Fillet1_2"}))


# --- 2. reorder ---------------------------------------------------------------------


def test_reorder_inverts_to_the_recorded_anchor_and_location() -> None:
    """Back to the anchor it sat beside, on the side it sat on - not to an index."""
    change = applied(
        "reorder",
        before={"index": 42, "anchor_persist_ref": "<b64 Cut-Extrude2>", "location": "after"},
        after={"index": 61, "anchor_persist_ref": "<b64 Chamfer1>", "location": "after"},
    )

    undo = derive_undo(change)

    assert undo == UndoCommand(
        command="remodel.reorder",
        params={
            "feature_persist_ref": FEATURE_REF,
            "anchor_persist_ref": "<b64 Cut-Extrude2>",
            "location": "after",
        },
    )
    assert set(undo.params) == client_arguments("reorder")
    assert undo.params["location"] in REORDER_LOCATIONS


def test_a_reorder_inverse_never_carries_a_location_outside_the_closed_pair() -> None:
    """`ToEnd`, `ToTop` and `ToFolder` are forbidden by the guard's own composition test."""
    with pytest.raises(ValueError, match="location"):
        derive_undo(
            applied(
                "reorder",
                before={"anchor_persist_ref": "<b64>", "location": "to_end"},
            )
        )


def test_a_reorder_with_no_recorded_anchor_is_refused() -> None:
    with pytest.raises(ValueError, match="anchor"):
        derive_undo(applied("reorder", before={"index": 42, "location": "after"}))


# --- 3. folder.create ---------------------------------------------------------------


def test_folder_create_has_no_forward_inverse_and_escalates_to_the_replay() -> None:
    """The owner kept `IModelDoc2.EditDelete` off the stage-1 allowlist, so there is no
    dissolve to invert with. `None` is the recorded answer, and the kind is named as the
    one that escalates to the catastrophic fallback rather than leaving that implicit."""
    change = applied(
        "folder.create",
        before={},
        after={"name": "3-Core", "folder_persist_ref": "<b64 folder>"},
        subject=None,
    )

    assert derive_undo(change) is None
    assert set(ESCALATES_TO_REPLAY) == {"folder.create"}
    assert "save" not in ESCALATES_TO_REPLAY


def test_no_inverse_anywhere_asks_the_host_to_dissolve_a_folder() -> None:
    """`dissolve` is a v1 refusal on the host; nothing here may compose one."""
    assert "dissolve" in FOLDER_OPS
    for undo in every_inverse():
        assert undo.params.get("op") != "dissolve"


# --- 4. folder.rename ---------------------------------------------------------------


def test_folder_rename_inverts_to_the_previous_folder_name() -> None:
    """Addressed by the folder's persistent reference, because the `___EndTag___` marker
    keeps the folder's default name after a rename and a name would be ambiguous."""
    folder = ChangeSubject(feature_id="feat:0100", name="3-Core", persist_ref="<b64 folder>")
    change = applied(
        "folder.rename",
        before={"name": "Folder1"},
        after={"name": "3-Core"},
        subject=folder,
    )

    undo = derive_undo(change)

    assert undo == UndoCommand(
        command="remodel.folder",
        params={
            "op": "rename",
            "name": "Folder1",
            "member_persist_refs": [],
            "folder_persist_ref": "<b64 folder>",
        },
    )
    assert set(undo.params) == client_arguments("folder")


# --- 5. describe --------------------------------------------------------------------


def test_describe_inverts_to_the_recorded_previous_text() -> None:
    change = applied(
        "describe",
        before={"text": "Mounting slot"},
        after={"text": "Mounting slot for the bracket"},
    )

    undo = derive_undo(change)

    assert undo == UndoCommand(
        command="remodel.describe",
        params={"persist_ref": FEATURE_REF, "text": "Mounting slot"},
    )
    assert set(undo.params) == client_arguments("describe")


def test_describe_inverts_an_absent_description_to_the_empty_string() -> None:
    """`""` means "read, and empty", so writing it back is exact and not a default."""
    undo = derive_undo(applied("describe", before={"text": ""}, after={"text": "Mounting slot"}))

    assert undo.params["text"] == ""


def test_describe_with_an_unreadable_previous_text_is_refused_up_front() -> None:
    """`null` is "unreadable", which `""` is not, and the two are never collapsed.

    A feature whose description reads back `null` is refused by the planner and never
    described; the refusal is repeated here so the change can never be attempted with no
    way back from it.
    """
    with pytest.raises(ValueError, match="unreadable"):
        derive_undo(applied("describe", before={"text": None}, after={"text": "Mounting slot"}))

    with pytest.raises(ValueError, match="unreadable"):
        derive_undo(applied("describe", before={}, after={"text": "Mounting slot"}))


# --- 6. equation.add ----------------------------------------------------------------


def test_equation_add_inverts_to_a_delete_of_the_index_it_landed_at() -> None:
    """`IEquationMgr.Delete(index)`; `which_configs` is null on a delete, which addresses
    an equation that already exists and changes no configuration scope."""
    change = applied(
        "equation.add",
        before={},
        after={"index": 7, "equation_text": '"shell_thickness" = 3'},
        subject=None,
    )

    undo = derive_undo(change)

    assert undo == UndoCommand(
        command="remodel.equation",
        params={"op": "delete", "index": 7, "text": None, "which_configs": None},
    )
    assert set(undo.params) == client_arguments("equation")
    assert undo.params["op"] in EQUATION_OPS


def test_equation_adds_are_deleted_in_reverse_order_of_addition() -> None:
    """Deleting the lower index first would renumber the higher one, so the run walks its
    own `applied` adds backwards and every delete addresses the equation it meant to."""
    adds = [
        applied("equation.add", before={}, after={"index": index}, subject=None, seq=index)
        for index in (7, 8, 9)
    ]

    indexes = [derive_undo(change).params["index"] for change in reversed(adds)]

    assert indexes == [9, 8, 7]


def test_an_add_with_no_recorded_index_is_refused() -> None:
    """Only ever the inverse of an add this run made: the index comes from that add's own
    record, so there is no path by which a guessed index deletes a pre-existing global."""
    with pytest.raises(ValueError, match="index"):
        derive_undo(applied("equation.add", before={}, after={}, subject=None))


# --- 7. equation.edit ---------------------------------------------------------------


def test_equation_edit_inverts_to_an_in_place_set_of_the_recorded_text() -> None:
    """An in-place repair is its own inverse (FR-029). A delete-and-re-add would remove a
    referenced global, and every dependent equation would enter an error state that does
    not clear when it returns (research.md R3.5)."""
    change = applied(
        "equation.edit",
        before={"index": 3, "equation_text": '"shell_thickness" = 3', "which_configs": 2},
        after={"index": 3, "equation_text": '"shell_thickness" = 4'},
        subject=None,
    )

    undo = derive_undo(change)

    assert undo == UndoCommand(
        command="remodel.equation",
        params={
            "op": "set",
            "index": 3,
            "text": '"shell_thickness" = 3',
            "which_configs": 2,
        },
    )
    assert set(undo.params) == client_arguments("equation")


def test_no_inverse_of_an_edit_is_ever_a_delete() -> None:
    """The one property FR-029 rests on, asserted as a property and not as an example."""
    change = applied(
        "equation.edit",
        before={"index": 3, "equation_text": '"t" = 3', "which_configs": 1},
        subject=None,
    )

    assert derive_undo(change).params["op"] != "delete"


def test_an_edit_with_no_recorded_previous_text_is_refused() -> None:
    """`SetEquationVerified` reads and returns the previous text *before* writing, and an
    unreadable one fails the change there rather than being written over here."""
    with pytest.raises(ValueError, match="previous"):
        derive_undo(
            applied(
                "equation.edit",
                before={"index": 3, "equation_text": None, "which_configs": 1},
                subject=None,
            )
        )


def test_an_edit_with_no_recorded_configuration_scope_is_refused() -> None:
    """`which_configs` is engineering data the run read from the document, never a default."""
    with pytest.raises(ValueError, match="which_configs"):
        derive_undo(
            applied(
                "equation.edit",
                before={"index": 3, "equation_text": '"t" = 3'},
                subject=None,
            )
        )


# --- 8. save ------------------------------------------------------------------------


def test_save_has_no_inverse() -> None:
    """The copy is saved once, at the end, only after the gate passes; there is nothing
    before it to go back to and nothing after it to undo."""
    assert derive_undo(applied("save", before={}, after={"path": COPY_PATH})) is None
    assert "save" not in ESCALATES_TO_REPLAY


# --- 9. what no inverse may ever be -------------------------------------------------


def one_record_per_kind() -> dict[RecordKind, ChangeRecord]:
    """A landed change of every kind, so the properties below are over all eight."""
    folder = ChangeSubject(feature_id="feat:0100", name="3-Core", persist_ref="<b64 folder>")
    return {
        "rename": applied("rename", before={"name": "Fillet1"}),
        "describe": applied("describe", before={"text": ""}),
        "reorder": applied(
            "reorder", before={"anchor_persist_ref": "<b64 a>", "location": "before"}
        ),
        "folder.create": applied(
            "folder.create", before={}, after={"name": "3-Core"}, subject=None
        ),
        "folder.rename": applied("folder.rename", before={"name": "Folder1"}, subject=folder),
        "equation.edit": applied(
            "equation.edit",
            before={"index": 3, "equation_text": '"t" = 3', "which_configs": 1},
            subject=None,
        ),
        "equation.add": applied("equation.add", before={}, after={"index": 7}, subject=None),
        "save": applied("save", before={}, after={"path": COPY_PATH}),
    }


def every_inverse() -> list[UndoCommand]:
    """Every inverse there is, for the properties that hold across all of them."""
    return [
        undo
        for undo in (derive_undo(change) for change in one_record_per_kind().values())
        if undo is not None
    ]


def test_every_kind_is_answered_and_exactly_two_have_no_inverse() -> None:
    """No kind falls off the end of the table into a `None` that means "not handled"."""
    records = one_record_per_kind()

    assert set(records) == set(RECORD_KINDS)
    assert {kind for kind, change in records.items() if derive_undo(change) is None} == {
        "folder.create",
        "save",
    }
    assert len(every_inverse()) == len(RECORD_KINDS) - 2


def test_an_unknown_kind_is_refused_rather_than_answered_with_none() -> None:
    """A kind with no inverse and a kind nobody has heard of are different answers."""
    with pytest.raises(ValueError, match="folder.dissolve"):
        derive_undo(
            applied("rename", before={"name": "Fillet1"}).model_copy(
                update={"kind": "folder.dissolve"}
            )
        )


def test_every_inverse_is_a_command_the_remodel_secret_authorizes() -> None:
    for undo in every_inverse():
        assert undo.command in REMODEL_COMMANDS
        assert undo.command.startswith("remodel.")


def test_no_inverse_names_a_document_or_a_path() -> None:
    """No `remodel.*` command that writes takes a document, and an inverse is a write."""
    for undo in every_inverse():
        assert not {"path", "document", "source_path", "copy_path"} & set(undo.params)


def test_edit_undo_2_is_never_produced_by_any_inverse() -> None:
    """`IModelDoc2.EditUndo2` returns void, so a caller cannot tell whether it did
    anything, and it shares the UI undo stack the engineer can also touch. It is not on
    the allowlist, it is not a bridge command, and no inverse composes one."""
    assert not [command for command in REMODEL_COMMANDS if "Undo" in command]
    for undo in every_inverse():
        assert "EditUndo2" not in undo.command
        assert "EditUndo2" not in repr(undo.params)
