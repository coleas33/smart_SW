"""A finding's triage beside its decision (feature 002 FR-031, owner decision 185A).

A disposition holds the engineer's decision and, beside it, one of four outcomes - new and real,
real but already known, wrong, or true but not worth flagging - optional, independent of the
decision and never inferred from it (002 research, 185A). What this pins:

- **the record** (002 T308): `set_disposition` and `apply_disposition` record one of `TRIAGES`
  and refuse anything else, naming the four, before anything changes; the triage moves no
  decision and no rank; a disposition without one keeps its bytes in `session.json`, in the
  model's dump and in the `disposition` event, and a session written before the field loads and
  keeps its bytes; a deferred finding keeps its triage unless the later decision names another;
  and an Accept or Reject recorded without one takes one once - the same decision sent again
  with a triage records the triage and nothing else - while a second triage or another decision
  is refused as before.
- **the report** (002 T314): `report.md` shows a finding's triage in the words file's words under
  its decision and, once any finding records one, counts the four and the findings that record
  none, right after "By severity", read from the triage alone; a session with no triage renders
  as before.

Every fixture is fictional: FICT names, and an explicit `by` on every record.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from swreview.agent import runner
from swreview.agent.providers import AgentEvent
from swreview.agent.providers.fake import FakeProvider, ScriptedToolCall, ScriptedTurn
from swreview.chat.sessions import record_disposition
from swreview.findings import TRIAGES, Disposition
from swreview.report.attention import rank
from swreview.report.dispositions import apply_disposition, find_finding, set_disposition
from swreview.report.markdown import render_report
from swreview.report.session import ReviewSession, Timing, load_session, save_session
from swreview.report.summary import load_words
from tests.support.contracts import contract_validator
from tests.support.findings import PACKAGE, make_finding
from tests.unit.test_chat_sessions import DRAWING_FINDING_ARGUMENTS

BY = "FICT-ENG"
OTHER_BY = "FICT-ENG-2"
FIRST_AT = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)
LATER_AT = datetime(2026, 11, 1, 9, 30, tzinfo=UTC)
TERMINAL = "terminal disposition"
"""The refusal of any change to an accepted or rejected finding (`report/dispositions.py`)."""

BEFORE_THE_FIELD = (
    Path(__file__).resolve().parents[1] / "fixtures" / "attention" / "session-20260918-review.json"
)
"""A committed session written before the field: eight findings, none decided."""

DISPOSITION_KEYS = ["decision", "note", "by", "at"]
"""A disposition's keys as every build before 185A wrote them, in their order."""


def triage_session(count: int) -> ReviewSession:
    """A fictional finished session holding `count` undecided findings, F-001 onwards."""
    severities = ("high", "medium", "low", "info")
    return ReviewSession(
        session_id=UUID("0f1c7a2e-0000-4000-8000-000000000185"),
        package_id=PACKAGE.package_id,
        design_id="FICT-triage",
        started_at=FIRST_AT,
        model="FICT-model",
        findings=[
            make_finding(
                finding_id=f"F-{index:03d}",
                check=f"fastener.fict_{index}",
                title=f"FICT finding {index}",
                severity=severities[index % len(severities)],
            )
            for index in range(1, count + 1)
        ],
        timing=Timing(
            baseline_minutes=None,
            assisted_supervision_minutes=0.0,
            assisted_verification_minutes=0.0,
            false_alarm_handling_minutes=0.0,
            unattended_runtime_minutes=0.0,
        ),
    )


def run_folder(tmp_path: Path, count: int = 4) -> Path:
    """A run folder holding `triage_session(count)` as its `session.json`, and nothing else."""
    run_dir = tmp_path / "FICT-run"
    save_session(triage_session(count), run_dir / "session.json")
    return run_dir


def recorded(run_dir: Path, finding_id: str) -> Disposition:
    """The disposition the folder's `session.json` holds for `finding_id`, read from the file."""
    disposition = find_finding(load_session(run_dir / "session.json"), finding_id).disposition
    assert disposition is not None
    return disposition


def folder_bytes(run_dir: Path) -> dict[str, bytes]:
    """Every file the run folder holds, by name: what a refusal must leave as it was."""
    return {path.name: path.read_bytes() for path in sorted(run_dir.iterdir())}


@pytest.fixture
def live_run(
    tmp_package_dir: Path, tmp_path: Path
) -> Iterator[tuple[runner.ReviewRun, list[dict[str, Any]]]]:
    """A played review holding one finding, and the body of every `disposition` event it emits."""
    run = runner.start_review(
        tmp_package_dir,
        tmp_path / "FICT-live",
        provider=FakeProvider(
            script=[
                ScriptedTurn(
                    text="One finding.",
                    tool_calls=(
                        ScriptedToolCall("record_drawing_finding", DRAWING_FINDING_ARGUMENTS),
                    ),
                )
            ],
            model="fake-1",
        ),
        effort="high",
    )
    bodies: list[dict[str, Any]] = []

    def keep(event: AgentEvent) -> None:
        if event.type == "disposition":
            bodies.append(dict(event.body))

    run.sink.add_listener(keep)
    run.start()
    yield run, bodies
    run.close()


# --- the record (002 T308) -----------------------------------------------------------------------


@pytest.mark.parametrize("triage", TRIAGES)
def test_a_disposition_records_one_of_the_four_outcomes(tmp_path: Path, triage: str) -> None:
    run_dir = run_folder(tmp_path)

    apply_disposition(run_dir, "F-001", "accepted", "FICT note", BY, at=FIRST_AT, triage=triage)

    assert recorded(run_dir, "F-001") == Disposition(
        decision="accepted", note="FICT note", by=BY, at=FIRST_AT, triage=triage
    )
    written = json.loads((run_dir / "session.json").read_text(encoding="utf-8"))
    assert written["findings"][0]["disposition"]["triage"] == triage


@pytest.mark.parametrize(
    "triage",
    ["maybe", "Wrong", "", "new and real", 3, True, []],
    ids=["another-word", "another-case", "empty", "the-words", "a-number", "true", "a-list"],
)
def test_a_disposition_refuses_an_outcome_outside_the_four(tmp_path: Path, triage: Any) -> None:
    run_dir = run_folder(tmp_path)
    before = folder_bytes(run_dir)

    with pytest.raises(ValueError, match="triage") as refused:
        apply_disposition(run_dir, "F-001", "accepted", "FICT note", BY, triage=triage)

    assert [token for token in TRIAGES if token in str(refused.value)] == list(TRIAGES)
    assert folder_bytes(run_dir) == before


def test_the_triage_is_independent_of_the_decision() -> None:
    """Any of the four goes with any decision, and none of them moves a rank: the ranking reads
    the decision alone (007 FR-008), so a session with the twelve pairs ranks as the same
    session with the same decisions and no triage."""
    pairs = [
        (decision, triage)
        for decision in ("accepted", "rejected", "deferred")
        for triage in TRIAGES
    ]
    triaged, plain = triage_session(len(pairs)), triage_session(len(pairs))

    for index, (decision, triage) in enumerate(pairs, start=1):
        finding_id = f"F-{index:03d}"
        set_disposition(triaged, finding_id, decision, "FICT note", BY, at=FIRST_AT, triage=triage)
        set_disposition(plain, finding_id, decision, "FICT note", BY, at=FIRST_AT)

    assert [
        (finding.disposition.decision, finding.disposition.triage)
        for finding in triaged.findings
        if finding.disposition is not None
    ] == pairs
    assert rank(triaged) == rank(plain)


def test_a_disposition_without_a_triage_keeps_its_bytes(
    tmp_path: Path, live_run: tuple[runner.ReviewRun, list[dict[str, Any]]]
) -> None:
    """No `triage` key anywhere a disposition recorded without one is written: `session.json`,
    the model's dump in both modes, and the live `disposition` event's body."""
    run_dir = run_folder(tmp_path)

    apply_disposition(run_dir, "F-001", "accepted", "FICT note", BY, at=FIRST_AT)

    disposition = recorded(run_dir, "F-001")
    assert disposition.triage is None
    assert '"triage"' not in (run_dir / "session.json").read_text(encoding="utf-8")
    assert list(disposition.model_dump()) == DISPOSITION_KEYS
    assert list(disposition.model_dump(mode="json")) == DISPOSITION_KEYS
    assert disposition.model_dump_json() == (
        '{"decision":"accepted","note":"FICT note","by":"FICT-ENG","at":"2026-11-01T09:00:00Z"}'
    )
    run, bodies = live_run
    record_disposition(
        run, run.session.findings[0].id, decision="rejected", note="FICT note", by=BY
    )
    assert [list(body["disposition"]) for body in bodies] == [DISPOSITION_KEYS]


def _decided_before_the_field(decision: str) -> str:
    """A disposition as the tree before 185A wrote it into a finding of `BEFORE_THE_FIELD`."""
    return "".join(
        [
            '      "disposition": {\n',
            f'        "decision": "{decision}",\n',
            '        "note": "FICT note",\n',
            f'        "by": "{BY}",\n',
            '        "at": "2026-11-01T09:00:00Z"\n',
            "      },\n",
        ]
    )


def test_a_session_written_before_the_field_loads_and_keeps_its_bytes(tmp_path: Path) -> None:
    """The committed pre-008 session with its first two findings decided, as the tree before
    185A wrote a decision: it loads with no triage, and saving it again writes its own bytes."""
    undecided = '      "disposition": null,\n'
    text = BEFORE_THE_FIELD.read_text(encoding="utf-8")
    assert text.count(undecided) == 8
    for decision in ("accepted", "deferred"):
        text = text.replace(undecided, _decided_before_the_field(decision), 1)
    path = tmp_path / "session.json"
    path.write_text(text, encoding="utf-8")
    before = path.read_bytes()

    session = load_session(path)
    save_session(session, path)

    assert [
        (finding.disposition.decision, finding.disposition.triage)
        for finding in session.findings
        if finding.disposition is not None
    ] == [("accepted", None), ("deferred", None)]
    assert path.read_bytes() == before


def test_a_session_with_a_triage_validates_against_the_contract() -> None:
    session = triage_session(len(TRIAGES))
    for index, triage in enumerate(TRIAGES, start=1):
        set_disposition(session, f"F-{index:03d}", "deferred", "FICT note", BY, triage=triage)
    payload = session.model_dump(mode="json")
    validator = contract_validator("review-session.schema.json")

    assert [error.message for error in validator.iter_errors(payload)] == []
    payload["findings"][0]["disposition"]["triage"] = "maybe"
    assert not validator.is_valid(payload)


@pytest.mark.parametrize(
    ("decision", "named", "kept"),
    [
        ("accepted", None, "wrong"),
        ("rejected", None, "wrong"),
        ("accepted", "already_known", "already_known"),
        ("rejected", "not_worth_flagging", "not_worth_flagging"),
    ],
    ids=[
        "accept-naming-none",
        "reject-naming-none",
        "accept-naming-another",
        "reject-naming-another",
    ],
)
def test_a_deferred_findings_triage_is_kept_unless_the_decision_names_another(
    tmp_path: Path, decision: str, named: str | None, kept: str
) -> None:
    run_dir = run_folder(tmp_path)
    apply_disposition(
        run_dir, "F-001", "deferred", "FICT first note", BY, at=FIRST_AT, triage="wrong"
    )

    apply_disposition(
        run_dir, "F-001", decision, "FICT later note", OTHER_BY, at=LATER_AT, triage=named
    )

    assert recorded(run_dir, "F-001") == Disposition(
        decision=decision, note="FICT later note", by=OTHER_BY, at=LATER_AT, triage=kept
    )


@pytest.mark.parametrize("decision", ["accepted", "rejected"])
def test_a_decided_finding_without_a_triage_takes_one_once(tmp_path: Path, decision: str) -> None:
    """185A's late triage: the decision, note, `by` and `at` stay as first recorded, whatever
    note and `by` the second call carries; only the triage is added."""
    run_dir = run_folder(tmp_path)
    apply_disposition(run_dir, "F-001", decision, "FICT first note", BY, at=FIRST_AT)

    session = apply_disposition(
        run_dir, "F-001", decision, "FICT later note", OTHER_BY, at=LATER_AT, triage="already_known"
    )

    expected = Disposition(
        decision=decision, note="FICT first note", by=BY, at=FIRST_AT, triage="already_known"
    )
    assert find_finding(session, "F-001").disposition == expected
    assert recorded(run_dir, "F-001") == expected


@pytest.mark.parametrize(
    ("first", "then", "refusal"),
    [
        ([("accepted", "wrong")], ("accepted", "wrong"), TERMINAL),
        ([("accepted", "wrong")], ("accepted", "already_known"), TERMINAL),
        ([("accepted", "wrong")], ("accepted", None), TERMINAL),
        ([("rejected", None), ("rejected", "wrong")], ("rejected", "already_known"), TERMINAL),
        ([("rejected", None)], ("accepted", "wrong"), TERMINAL),
        ([("accepted", None)], ("rejected", None), TERMINAL),
        ([("accepted", None)], ("accepted", None), TERMINAL),
        ([("deferred", None)], ("deferred", "wrong"), "is deferred"),
    ],
    ids=[
        "the-same-triage-again",
        "another-triage",
        "the-same-decision-with-none",
        "a-second-late-triage",
        "another-decision-with-a-triage",
        "another-decision",
        "the-same-decision-with-no-triage",
        "a-defer-again-with-a-triage",
    ],
)
def test_a_second_triage_or_another_decision_is_still_refused(
    tmp_path: Path,
    first: list[tuple[str, str | None]],
    then: tuple[str, str | None],
    refusal: str,
) -> None:
    """A second triage, the same or another, a different decision and the same decision with no
    triage are refused as any change to a settled finding is, with nothing changed; a Defer is
    not settled, and is refused a second Defer as before - the late triage is Accept's and
    Reject's alone."""
    run_dir = run_folder(tmp_path)
    for decision, triage in first:
        apply_disposition(run_dir, "F-001", decision, "FICT note", BY, at=FIRST_AT, triage=triage)
    before = folder_bytes(run_dir)

    decision, triage = then
    with pytest.raises(ValueError, match=refusal):
        apply_disposition(
            run_dir, "F-001", decision, "FICT later note", OTHER_BY, at=LATER_AT, triage=triage
        )

    assert folder_bytes(run_dir) == before


# --- the report (002 T314) -----------------------------------------------------------------------

REPORTED: tuple[tuple[str, str, str | None], ...] = (
    ("F-001", "accepted", "new_and_real"),
    ("F-002", "deferred", "new_and_real"),
    ("F-003", "rejected", "wrong"),
    ("F-004", "accepted", None),
)
"""Four of five findings' records - new and real accepted and deferred, wrong rejected, an Accept
with no triage - and F-005 undecided."""

BY_TRIAGE = (
    "- By triage: new and real: 2, real but already known: 0, wrong: 1, "
    "true but not worth flagging: 0, not recorded: 2"
)
"""`REPORTED`'s count: the four in their order, then every finding without a triage, decided or
not."""


def reported_session(records: tuple[tuple[str, str, str | None], ...] = REPORTED) -> ReviewSession:
    """`triage_session(5)` with `records` set on it, each as `(finding, decision, triage)`."""
    session = triage_session(5)
    for finding_id, decision, triage in records:
        set_disposition(session, finding_id, decision, "FICT note", BY, at=FIRST_AT, triage=triage)
    return session


def by_triage_lines(report: str) -> list[str]:
    return [line for line in report.splitlines() if line.startswith("- By triage:")]


def after_the_decision(report: str, finding_id: str) -> str:
    """The line after the decision line of `finding_id`'s disposition in `report`."""
    lines = report.splitlines()
    heading = lines.index(next(line for line in lines if line.startswith(f"#### {finding_id}:")))
    decision = next(
        index for index in range(heading, len(lines)) if lines[index].startswith("  - decision: ")
    )
    return lines[decision + 1]


def test_the_report_counts_findings_by_outcome() -> None:
    lines = render_report(reported_session()).splitlines()

    [severity] = [index for index, line in enumerate(lines) if line.startswith("- By severity:")]
    assert lines[severity + 1] == BY_TRIAGE
    assert by_triage_lines(render_report(reported_session())) == [BY_TRIAGE]


def test_a_finding_shows_its_triage_under_its_decision(tmp_path: Path) -> None:
    """Through the folder's own re-render, as `swreview disposition` writes it: each of the four
    in the words file's words on the line after the decision, and no triage line where a
    disposition records none."""
    run_dir = run_folder(tmp_path, len(TRIAGES) + 1)
    for index, triage in enumerate((*TRIAGES, None), start=1):
        apply_disposition(
            run_dir, f"F-{index:03d}", "accepted", "FICT note", BY, at=FIRST_AT, triage=triage
        )
    report = (run_dir / "report.md").read_text(encoding="utf-8")
    words = load_words().labels.triage

    assert [
        after_the_decision(report, f"F-{index:03d}") for index in range(1, len(TRIAGES) + 2)
    ] == [*(f"  - triage: {words[triage]}" for triage in TRIAGES), f"  - by: {BY}"]


def test_the_count_never_reads_the_decision() -> None:
    """The same triages under other decisions count the same, and an Accept with none is not
    recorded like an undecided finding: the line reads the triage alone."""
    shuffled: tuple[tuple[str, str, str | None], ...] = (
        ("F-001", "deferred", "new_and_real"),
        ("F-002", "rejected", "new_and_real"),
        ("F-003", "accepted", "wrong"),
        ("F-004", "rejected", None),
    )

    assert by_triage_lines(render_report(reported_session(shuffled))) == [BY_TRIAGE]


def test_a_session_without_a_triage_renders_as_before() -> None:
    """A guard, green before T315 and after: with no triage recorded, decided or not, the report
    carries no "By triage" line and no triage line, so every committed golden keeps its bytes."""
    plain = tuple((finding_id, decision, None) for finding_id, decision, _ in REPORTED)

    report = render_report(reported_session(plain))

    assert by_triage_lines(report) == []
    assert "- triage:" not in report
