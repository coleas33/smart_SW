"""Unit tests for `changes.jsonl` and its writer (feature 004 T074).

`changes.jsonl` is both the undo record and the change list the pane shows, so its line
format is pinned against the two documents that describe it rather than against this
module's own idea of it: `data-model.md` section 2 is normative, `contracts/run-artifacts.md`
restates it verbatim, and the field lists of the model and of both documents are compared as
**sets**, so a field that lives in one of the three and not the others fails here.

What else is pinned:

- **the attempting and terminal pair.** One line goes out *before* the bridge call with
  `status: "attempting"` and a second after it with a terminal status, so a hard crash
  mid-change leaves exactly one `attempting` line naming what was in flight. A reader
  recovering such a run finds that line and never treats it as applied;
- **five statuses, not four.** `failed` means the change never landed; `rollback_failed`
  means it landed, raised the rebuild-error count and could not be undone. Only the second
  ends the run (T080), which is the whole reason the fifth value exists;
- **append-only, monotonic `seq`.** A line never rewrites an earlier one, and a `seq` that
  goes backwards is refused at the writer rather than discovered by a reader;
- **`target_path` per change (FR-041).** The path `VerifyTarget` confirmed for this write,
  which must agree with the `target=` the host wrote into `remodel.log` for the same
  request. That agreement is what makes FR-041 checkable per change rather than per run.

Offline: no SOLIDWORKS, no bridge, no provider. The `remodel.log` line this file compares
against is composed exactly as `ToolServiceRequestLogger.Format` composes it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, get_args

import pytest
from pydantic import ValidationError

from swreview.remodel.apply_log import (
    CHANGES_FILE_NAME,
    ENDS_THE_RUN,
    RECORD_KINDS,
    STATUSES,
    TERMINAL_STATUSES,
    ApplyLog,
    ChangeRecord,
    RecordKind,
    Status,
    UndoCommand,
    changes_path,
    in_flight,
    read_changes,
)
from swreview.remodel.plan import CHANGE_ORDER, ChangeSubject

REPO_ROOT = Path(__file__).resolve().parents[3]
SPEC_DIR = REPO_ROOT / "specs" / "004-resilient-remodeler"
DATA_MODEL = SPEC_DIR / "data-model.md"
RUN_ARTIFACTS = SPEC_DIR / "contracts" / "run-artifacts.md"

COPY_PATH = r"C:\runs\20260916-142201-bracket-remodel\copy\bracket-RMS.SLDPRT"

DOCUMENTED_FIELDS: tuple[str, ...] = (
    "seq",
    "at",
    "kind",
    "subject",
    "before",
    "after",
    "undo",
    "rebuild_errors_before",
    "rebuild_errors_after",
    "status",
    "error_code",
    "error",
    "target_path",
    "elapsed_ms",
)
"""The fields of `data-model.md` section 2, in the order the example line carries them."""


# --- reading the two documents -----------------------------------------------------


def section(path: Path, start: str, end: str) -> str:
    """The text of one markdown section, from its heading up to the next named one."""
    text = path.read_text(encoding="utf-8")
    first = text.index(start)
    return text[first : text.index(end, first + len(start))]


def table_fields(body: str) -> tuple[str, ...]:
    """The backticked names in the first column of a markdown field table.

    Two shorthands the documents use are expanded rather than tolerated, because both are
    a pair of real field names written short: `` `before`, `after` `` and `` `before` /
    `after` `` are two fields, and a token beginning with `_` (`` `rebuild_errors_before`
    / `_after` ``) is the previous name's suffix replaced, not a field called `_after`.
    """
    names: list[str] = []
    for line in body.splitlines():
        if not line.startswith("|"):
            continue
        cell = line.split("|")[1].strip()
        for token in re.findall(r"`([^`]+)`", cell):
            if token.startswith("_") and names:
                stem = names[-1].rsplit("_", 1)[0]
                names.append(stem + token)
            else:
                names.append(token)
    return tuple(names)


def example_line() -> dict[str, Any]:
    """The `changes.jsonl` example of `contracts/run-artifacts.md`, as a dict."""
    body = section(RUN_ARTIFACTS, "## `changes.jsonl`", "### The inverse per kind")
    block = body.split("```jsonc", 1)[1].split("```", 1)[0]
    return json.loads(block)


def remodel_log_line(request_id: str, command: str, target: str) -> str:
    """One `remodel.log` line, composed exactly as `ToolServiceRequestLogger.Format` does.

    The host writes the target of every mutating call; this is the other half of FR-041's
    pair and the test below asserts the two halves name the same file.
    """
    return (
        "[2026-09-16T14:22:31.4810000+00:00] "
        f"id={request_id} command={command} status=ok elapsed_ms=310 "
        f"gated=IModelDocExtension.ReorderFeature target={target}"
    )


def logged_target(line: str) -> str:
    """The ` target=` field of a `remodel.log` line, to the end of the field."""
    match = re.search(r" target=(.*?)(?: refused=| error=|$)", line)
    assert match is not None, line
    return match.group(1)


# --- records the tests write -------------------------------------------------------


def subject(name: str = "Fillet3") -> ChangeSubject:
    return ChangeSubject(feature_id="feat:0042", name=name, persist_ref="<b64>")


def attempting(seq: int = 1, kind: RecordKind = "reorder", **over: Any) -> ChangeRecord:
    """The line written before the bridge call: what is in flight, and no outcome."""
    fields: dict[str, Any] = {
        "seq": seq,
        "at": "2026-09-16T14:22:31.481Z",
        "kind": kind,
        "subject": subject(),
        "before": {},
        "after": {},
        "undo": None,
        "rebuild_errors_before": 0,
        "rebuild_errors_after": None,
        "status": "attempting",
        "error_code": None,
        "error": None,
        "target_path": COPY_PATH,
        "elapsed_ms": None,
    }
    fields.update(over)
    return ChangeRecord(**fields)


def terminal(
    seq: int = 1, status: Status = "applied", kind: RecordKind = "reorder", **over: Any
) -> ChangeRecord:
    """The line written after it: the outcome, the readings around it, and the inverse."""
    fields: dict[str, Any] = {
        "seq": seq,
        "at": "2026-09-16T14:22:31.791Z",
        "kind": kind,
        "subject": subject(),
        "before": {"anchor_persist_ref": "<b64 anchor>", "location": "after"},
        "after": {"anchor_persist_ref": "<b64 new anchor>", "location": "after"},
        "undo": UndoCommand(
            command="remodel.reorder",
            params={
                "feature_persist_ref": "<b64>",
                "anchor_persist_ref": "<b64 anchor>",
                "location": "after",
            },
        ),
        "rebuild_errors_before": 0,
        "rebuild_errors_after": 0,
        "status": status,
        "error_code": None,
        "error": None,
        "target_path": COPY_PATH,
        "elapsed_ms": 310,
    }
    fields.update(over)
    return ChangeRecord(**fields)


# --- 1. the field list is the documents' field list --------------------------------


def test_the_model_and_both_documents_carry_one_field_list() -> None:
    """Set equality across three places, so a field in one of them and not the others fails.

    `data-model.md` section 2 is normative and `contracts/run-artifacts.md` restates it;
    the model is what the run actually writes. Nothing here allows one of the three to
    gain a field quietly.
    """
    normative = table_fields(
        section(DATA_MODEL, "## 2. `ChangeRecord`", "### 2.1 Inverses")
    )
    restated = table_fields(
        section(RUN_ARTIFACTS, "## `changes.jsonl`", "### The inverse per kind")
    )
    model = set(ChangeRecord.model_fields)

    assert set(normative) == model
    assert set(restated) == model
    assert model == set(DOCUMENTED_FIELDS)
    assert len(model) == 14


def test_the_written_line_reads_in_the_documented_order() -> None:
    """The file an engineer opens in a text editor reads as the document does."""
    assert tuple(ChangeRecord.model_fields) == DOCUMENTED_FIELDS


def test_the_subject_is_addressed_by_persistent_reference() -> None:
    """`{feature_id, name, persist_ref}`, and `name` is for the report only."""
    assert set(ChangeSubject.model_fields) == {"feature_id", "name", "persist_ref"}
    assert set(UndoCommand.model_fields) == {"command", "params"}


def test_the_contracts_example_line_loads_into_the_model() -> None:
    """The example in `run-artifacts.md` is a `ChangeRecord` and not prose beside one."""
    record = ChangeRecord.model_validate(example_line())

    assert record.seq == 17
    assert record.kind == "reorder"
    assert record.status == "applied"
    assert record.undo is not None
    assert record.undo.command == "remodel.reorder"
    assert record.target_path == COPY_PATH


def test_an_unknown_field_is_refused_rather_than_carried() -> None:
    with pytest.raises(ValidationError):
        ChangeRecord.model_validate(dict(example_line(), dimension="D1@Sketch1"))


# --- 2. the closed sets ------------------------------------------------------------


def test_kind_is_the_closed_set_of_eight_and_folder_dissolve_is_not_in_it() -> None:
    """The seven planned kinds plus `save`; `folder.dissolve` is reserved for stage 2."""
    assert set(RECORD_KINDS) == {
        "rename",
        "describe",
        "reorder",
        "folder.create",
        "folder.rename",
        "equation.add",
        "equation.edit",
        "save",
    }
    assert "folder.dissolve" not in set(RECORD_KINDS)
    # One vocabulary: every kind the planner emits is a kind the log can record, and the
    # log adds exactly one - `save`, which no planner ever emits.
    assert set(RECORD_KINDS) == set(CHANGE_ORDER) | {"save"}


def test_status_is_the_closed_set_of_five() -> None:
    assert set(get_args(Status)) == {
        "attempting",
        "applied",
        "failed",
        "rolled_back",
        "rollback_failed",
    }
    assert set(STATUSES) == set(get_args(Status))
    assert set(TERMINAL_STATUSES) == set(STATUSES) - {"attempting"}


def test_failed_and_rollback_failed_are_distinct_outcomes() -> None:
    """`failed`: the change never landed. `rollback_failed`: it landed and could not be
    undone. Both are terminal, they are not the same value, and only the second ends the
    run (T080) - which is the entire reason the fifth status exists rather than four."""
    assert "failed" in TERMINAL_STATUSES
    assert "rollback_failed" in TERMINAL_STATUSES
    assert set(ENDS_THE_RUN) == {"rollback_failed"}
    assert "failed" not in ENDS_THE_RUN

    never_landed = terminal(status="failed", error_code="reorder_refused", error="refused")
    landed = terminal(status="rollback_failed", rebuild_errors_after=3)
    assert never_landed.status != landed.status


def test_an_unknown_status_is_refused() -> None:
    with pytest.raises(ValidationError):
        terminal(status="rolledback")  # type: ignore[arg-type]


# --- 3. the attempting and terminal pair -------------------------------------------


def test_the_attempting_line_is_written_before_the_call_and_records_no_outcome(
    tmp_path: Path,
) -> None:
    """A crash between the two writes leaves one line, and it names what was in flight."""
    log = ApplyLog(tmp_path / CHANGES_FILE_NAME)

    log.append(attempting(seq=17))
    # The bridge call happens here. Nothing else has been written.
    crashed = read_changes(tmp_path / CHANGES_FILE_NAME)

    assert len(crashed) == 1
    assert crashed[0].status == "attempting"
    assert crashed[0].seq == 17
    assert crashed[0].subject is not None
    assert crashed[0].subject.persist_ref == "<b64>"
    assert crashed[0].elapsed_ms is None
    assert crashed[0].rebuild_errors_after is None
    assert crashed[0].undo is None


def test_an_attempting_line_carrying_an_outcome_is_refused() -> None:
    """The outcome fields are unknown before the call, and `null` says so.

    Writing `0` into `rebuild_errors_after` before the rebuild that produces it would be a
    default written over a reading, which is the one thing this feature never does.
    """
    for outcome in (
        {"elapsed_ms": 310},
        {"rebuild_errors_after": 0},
        {"error_code": "reorder_refused"},
        {"error": "the reorder was refused"},
        {"undo": UndoCommand(command="remodel.reorder", params={})},
    ):
        with pytest.raises(ValidationError):
            attempting(**outcome)


def test_a_terminal_line_records_the_reading_and_the_elapsed_time() -> None:
    """A terminal line without them would be a status with nothing behind it."""
    for missing in ({"rebuild_errors_after": None}, {"elapsed_ms": None}):
        with pytest.raises(ValidationError):
            terminal(**missing)


def test_applied_carries_no_error_code_and_no_error() -> None:
    for wrong in ({"error_code": "reorder_refused"}, {"error": "refused"}):
        with pytest.raises(ValidationError):
            terminal(status="applied", **wrong)

    failed = terminal(status="failed", error_code="reorder_refused", error="refused")
    assert failed.error_code == "reorder_refused"


def test_a_save_record_names_nothing_and_every_other_kind_may() -> None:
    """The copy is saved once, at the end; there is no feature for that record to name."""
    with pytest.raises(ValidationError):
        terminal(kind="save")

    saved = terminal(kind="save", subject=None, undo=None)
    assert saved.subject is None


def test_the_pair_is_written_around_the_call_and_the_terminal_line_ends_it(
    tmp_path: Path,
) -> None:
    path = tmp_path / CHANGES_FILE_NAME
    log = ApplyLog(path)

    log.append(attempting(seq=1))
    log.append(terminal(seq=1))
    log.append(attempting(seq=2))
    log.append(terminal(seq=2, status="rolled_back"))

    records = read_changes(path)
    assert [(item.seq, item.status) for item in records] == [
        (1, "attempting"),
        (1, "applied"),
        (2, "attempting"),
        (2, "rolled_back"),
    ]
    assert in_flight(records) is None


def test_a_reader_recovering_a_crashed_run_never_treats_the_line_as_applied(
    tmp_path: Path,
) -> None:
    """Exactly one line has no terminal partner, and that is the change that was in flight."""
    path = tmp_path / CHANGES_FILE_NAME
    log = ApplyLog(path)
    log.append(attempting(seq=1))
    log.append(terminal(seq=1))
    log.append(attempting(seq=2, kind="folder.create", subject=None))

    records = read_changes(path)
    pending = in_flight(records)

    assert pending is not None
    assert pending.seq == 2
    assert pending.kind == "folder.create"
    assert pending.status == "attempting"
    assert [item for item in records if item.status == "applied"] == [records[1]]


# --- 4. append-only, monotonic seq -------------------------------------------------


def test_the_writer_appends_and_never_rewrites_an_earlier_line(tmp_path: Path) -> None:
    path = tmp_path / CHANGES_FILE_NAME
    log = ApplyLog(path)

    log.append(attempting(seq=1))
    first = path.read_text(encoding="utf-8")
    log.append(terminal(seq=1))

    grown = path.read_text(encoding="utf-8")
    assert grown.startswith(first)
    assert grown.count("\n") == 2


def test_a_seq_that_goes_backwards_is_refused(tmp_path: Path) -> None:
    log = ApplyLog(tmp_path / CHANGES_FILE_NAME)
    log.append(attempting(seq=2))
    log.append(terminal(seq=2))

    with pytest.raises(ValueError, match="monotonic"):
        log.append(attempting(seq=1))


def test_a_second_attempting_line_while_one_is_in_flight_is_refused(
    tmp_path: Path,
) -> None:
    """One `attempting` line at a time is what makes the crash recovery unambiguous."""
    log = ApplyLog(tmp_path / CHANGES_FILE_NAME)
    log.append(attempting(seq=1))

    with pytest.raises(ValueError, match="in flight"):
        log.append(attempting(seq=2))


def test_a_terminal_line_for_a_change_that_was_never_attempted_is_refused(
    tmp_path: Path,
) -> None:
    log = ApplyLog(tmp_path / CHANGES_FILE_NAME)

    with pytest.raises(ValueError, match="attempting"):
        log.append(terminal(seq=1))


def test_a_terminal_line_naming_another_change_is_refused(tmp_path: Path) -> None:
    log = ApplyLog(tmp_path / CHANGES_FILE_NAME)
    log.append(attempting(seq=1))

    with pytest.raises(ValueError, match="in flight"):
        log.append(terminal(seq=2))


def test_a_reopened_log_keeps_appending_where_the_file_left_off(tmp_path: Path) -> None:
    """The run folder is the unit: a second writer continues the file, never truncates it."""
    path = tmp_path / CHANGES_FILE_NAME
    first = ApplyLog(path)
    first.append(attempting(seq=1))
    first.append(terminal(seq=1))

    second = ApplyLog(path)
    second.append(attempting(seq=2))

    second.append(terminal(seq=2))

    assert [item.seq for item in read_changes(path)] == [1, 1, 2, 2]
    with pytest.raises(ValueError, match="monotonic"):
        second.append(attempting(seq=1))


def test_one_line_per_record_in_the_documented_field_order(tmp_path: Path) -> None:
    path = tmp_path / CHANGES_FILE_NAME
    ApplyLog(path).append(attempting(seq=1))

    line = path.read_text(encoding="utf-8").splitlines()[0]
    assert tuple(json.loads(line)) == DOCUMENTED_FIELDS
    assert "\n" not in line


def test_the_file_lives_in_the_run_folder_under_one_name(tmp_path: Path) -> None:
    assert CHANGES_FILE_NAME == "changes.jsonl"
    assert changes_path(tmp_path) == tmp_path / CHANGES_FILE_NAME


# --- 5. target_path, per change (FR-041) -------------------------------------------


def test_target_path_agrees_with_the_remodel_log_line_for_the_same_request() -> None:
    """FR-041 checkable per change, not per run.

    The record carries the path `VerifyTarget` confirmed for this write and the host's
    `remodel.log` carries the target it observed for the same request. The report cites
    both; here they are asserted to name one file.
    """
    record = terminal(seq=17)
    line = remodel_log_line("17", "remodel.reorder", COPY_PATH)

    assert logged_target(line) == record.target_path
    assert record.target_path.endswith(".SLDPRT")


def test_a_record_without_a_target_path_is_refused() -> None:
    """Every line says where the write went; there is no line that does not."""
    with pytest.raises(ValidationError):
        terminal(target_path=None)
    with pytest.raises(ValidationError):
        ChangeRecord.model_validate(
            {key: value for key, value in example_line().items() if key != "target_path"}
        )


def test_every_record_of_one_run_names_the_same_copy(tmp_path: Path) -> None:
    """The run's own assertion, from the artifact rather than from intent."""
    path = tmp_path / CHANGES_FILE_NAME
    log = ApplyLog(path)
    for seq in (1, 2):
        log.append(attempting(seq=seq))
        log.append(terminal(seq=seq))

    assert {item.target_path for item in read_changes(path)} == {COPY_PATH}
