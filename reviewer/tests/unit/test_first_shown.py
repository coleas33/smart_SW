"""002 T388 (cycle 17; FR-031; roadmap hole H-a-009): the card names when an earlier review first
showed its finding, so owner decision 188A's date is read, not recalled.

When a review starts, the backend reads the earlier reviews of the same document still in the run
root - the folders the add-in tells a document's reviews by (`RunFolders.FindNotSentReview`: the
name first, then the record's document), a Check again's earlier record in the same folder among
them, the review's own record never - and, for each flagged finding it raises, finds the earliest
whose record holds a flagged finding with the same subject key (`findings.finding_subject_key`, as
Check again's carry matches, 015 `contracts/recheck.md` section 4). That review's folder date is
named on the `finding` body as `first_shown`; both snapshots and `report.md` read it back from the
stream; and the model is sent nothing of it. Every record here is fictional.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from starlette.testclient import TestClient

from swreview.agent import runner
from swreview.agent.events import EventSink
from swreview.agent.providers import AgentEvent
from swreview.agent.providers.fake import FakeProvider
from swreview.findings import Finding, SubjectKey, finding_subject_key
from swreview.ir.loader import load_package
from swreview.report import first_shown
from swreview.report.first_shown import document_name, first_shown_dates
from swreview.report.markdown import render_report
from swreview.report.names import component_names
from swreview.report.session import (
    SESSION_FILE_NAME,
    ModelStatus,
    ReviewedDocument,
    ReviewSession,
    save_session,
)
from swreview.report.snapshot import review_snapshot, root_document
from swreview.report.titles import pane_finding
from swreview.tools.context import context_for, new_session
from tests.support.contracts import contract_validator
from tests.support.findings import make_finding
from tests.support.packages import build_package
from tests.support.recording_provider import RecordedRequest, RecordingProvider
from tests.support.restart import restarted_app
from tests.unit import test_chat_server as chat
from tests.unit import test_recheck as recheck
from tests.unit.test_runner_provider import judged

app = chat.app
client = chat.client
models = chat.models
provider_control = chat.provider_control
run_root = chat.run_root

PACKAGE = build_package()
"""The fictional assembly every review here is of, unless a test names another."""

LABEL = "cover-assy"
"""What the add-in calls a review folder of `PACKAGE` after its stamp: its root document,
`native/cover-assy.SLDASM`, as `RunFolders.DocumentName` reduces it."""

BEFORE = datetime(2026, 11, 3, 9, 0)
"""This review's start, the local wall clock the folder names are compared with."""

ON_ONE = make_finding(component_ids=["cmp:0001"])
"""A flagged finding on housing-1."""

ON_TWO = make_finding(component_ids=["cmp:0002"])
"""The same check on housing-2: another subject key."""

PASS = ON_ONE.model_copy(update={"status": "checked_within_scope", "severity": "info"})
"""A pass, 'Checked, no issue', with `ON_ONE`'s subject key (owner decision 187A)."""

SHOWN = "2026-09-18"
"""The date of the earlier review the route tests run, in `FIRST` below."""

FIRST = f"20260918-090000-{LABEL}"
"""The earlier review's folder, as the add-in names it."""

SECOND = f"20260920-093000-{LABEL}"
"""The later review's folder."""


def key(finding: Finding) -> SubjectKey:
    return finding_subject_key(finding)


def record(
    *findings: Finding, package: Any = PACKAGE, document: ReviewedDocument | None = None
) -> ReviewSession:
    """An earlier review's record of `findings`. With `document`, a review started unticked,
    whose record names its document and configuration (`model_status.document`)."""
    session = new_session(package).model_copy(update={"findings": list(findings)})
    if document is not None:
        session.model_status = ModelStatus(
            state="not_sent", document=document, checked_at=datetime(2026, 9, 1, tzinfo=UTC)
        )
    return session


def earlier(root: Path, name: str, *findings: Finding, **options: Any) -> Path:
    """A review folder `name` under `root`, holding the record of `findings`."""
    folder = root / name
    save_session(record(*findings, **options), folder / SESSION_FILE_NAME)
    return folder


def dates(root: Path, **options: Any) -> dict[SubjectKey, str]:
    """`first_shown_dates` for a review of `PACKAGE` in a folder of its own, started at `BEFORE`."""
    own = root / f"20261103-090000-{LABEL}"
    own.mkdir(parents=True, exist_ok=True)
    return first_shown_dates(root, own, PACKAGE, before=BEFORE, **options)


@pytest.fixture
def reads(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[Path]]:
    """Every record the match opens, in order: names decide before anything is opened."""
    opened: list[Path] = []
    load = first_shown.load_session

    def counted(path: Path | str) -> ReviewSession:
        opened.append(Path(path))
        return load(path)

    monkeypatch.setattr(first_shown, "load_session", counted)
    yield opened


# --- the match ---------------------------------------------------------------------------------


def test_an_earlier_reviews_flagged_finding_names_its_folders_date(tmp_path: Path) -> None:
    """The same subject key gives the earlier review's date, `YYYY-MM-DD`, the stamp the add-in
    named its folder with; another key gives none."""
    earlier(tmp_path, f"20260918-101500-{LABEL}", ON_ONE)

    shown = dates(tmp_path)

    assert shown == {key(ON_ONE): "2026-09-18"}
    assert key(ON_TWO) not in shown


def test_the_earliest_review_that_raised_it_gives_the_date(tmp_path: Path) -> None:
    """Of several earlier reviews, the earliest whose record holds the key, whatever the id, the
    title, the status and the severity it was raised with there: a date is no decision, so 194A's
    condition on carrying one is not this match's."""
    restated = ON_ONE.model_copy(
        update={"id": "F-009", "title": "FICT another title", "status": "demonstrated",
                "severity": "high"}
    )
    earlier(tmp_path, f"20260925-080000-{LABEL}", restated, ON_TWO)
    earlier(tmp_path, f"20260920-170000-{LABEL}", ON_ONE)
    earlier(tmp_path, f"20260918-101500-{LABEL}", ON_TWO)
    earlier(tmp_path, f"20260916-090000-{LABEL}")

    assert dates(tmp_path) == {key(ON_ONE): "2026-09-20", key(ON_TWO): "2026-09-18"}


def test_the_reviews_own_record_never_counts(tmp_path: Path, reads: list[Path]) -> None:
    """The review's own folder is never read: at a start it holds no record of this review, and a
    record already there is not an earlier review's."""
    own = earlier(tmp_path, f"20260918-090000-{LABEL}", ON_ONE)

    assert first_shown_dates(tmp_path, own, PACKAGE, before=BEFORE) == {}
    assert reads == []


def test_a_check_agains_earlier_record_counts(tmp_path: Path, reads: list[Path]) -> None:
    """A Check again re-runs a waiting review in its own folder: the earlier record the re-run
    holds counts, dated by the folder, and is not read again."""
    own = earlier(tmp_path, f"20260918-090000-{LABEL}", ON_ONE)
    held = record(ON_ONE, ON_TWO)

    assert first_shown_dates(tmp_path, own, PACKAGE, before=BEFORE, earlier=held) == {
        key(ON_ONE): "2026-09-18",
        key(ON_TWO): "2026-09-18",
    }
    assert reads == []


def test_an_unreadable_partial_or_empty_folder_is_skipped(tmp_path: Path) -> None:
    """A folder with no record, a record cut off, one that is not JSON, JSON that is no review,
    an empty file and a folder where the record should be are each skipped, and the review is
    not failed; nor is a run root that cannot be listed."""
    good = earlier(tmp_path, f"20260920-090000-{LABEL}", ON_ONE)
    whole = (good / SESSION_FILE_NAME).read_bytes()
    (tmp_path / f"20260910-090000-{LABEL}").mkdir()
    for name, content in (
        (f"20260911-090000-{LABEL}", whole[: len(whole) // 2]),
        (f"20260912-090000-{LABEL}", b"FICT not a record"),
        (f"20260913-090000-{LABEL}", b'{"FICT": 1}'),
        (f"20260914-090000-{LABEL}", b""),
    ):
        folder = tmp_path / name
        folder.mkdir()
        (folder / SESSION_FILE_NAME).write_bytes(content)
    (tmp_path / f"20260915-090000-{LABEL}" / SESSION_FILE_NAME).mkdir(parents=True)

    assert dates(tmp_path) == {key(ON_ONE): "2026-09-20"}
    gone = tmp_path / "FICT-no-root"
    assert first_shown_dates(gone, gone / LABEL, PACKAGE, before=BEFORE) == {}


def test_another_documents_reviews_are_ignored(tmp_path: Path, reads: list[Path]) -> None:
    """Another document's folder is never opened, by its name; a record of another document in a
    folder of this one's name - its design, or the document or configuration a review started
    unticked names - is read and ignored. The path is compared ignoring case and the
    configuration exactly (`PageDocument.IsSameDocument`)."""
    other = PACKAGE.model_copy(
        update={"design": PACKAGE.design.model_copy(update={"design_id": "dsn:FICT-other"})}
    )
    path = "native/cover-assy.SLDASM"
    counted = [
        earlier(tmp_path, f"20260912-090000-{LABEL}", ON_ONE, package=other),
        earlier(tmp_path, f"20260914-090000-{LABEL}", ON_ONE,
                document={"path": path, "configuration": "FICT-other"}),
        earlier(tmp_path, f"20260915-090000-{LABEL}", ON_ONE,
                document={"path": "native/FICT-other.SLDASM", "configuration": "Default"}),
        earlier(tmp_path, f"20260919-090000-{LABEL}", ON_ONE,
                document={"path": "NATIVE/Cover-Assy.SLDASM", "configuration": "Default"}),
    ]
    earlier(tmp_path, "20260913-090000-housing", ON_ONE)

    assert dates(tmp_path) == {key(ON_ONE): "2026-09-19"}
    assert sorted(reads) == sorted(folder / SESSION_FILE_NAME for folder in counted)


def test_a_pass_neither_gets_nor_gives_a_date(tmp_path: Path) -> None:
    """Owner decision 187A: a pass takes no triage but the miss, so 188A's date is not its. An
    earlier pass gives no date, and a pass of a key an earlier flagged finding gave one gets none,
    where a flagged finding of that key gets it."""
    earlier(tmp_path, f"20260918-090000-{LABEL}", PASS)
    assert dates(tmp_path) == {}

    context = context_for(PACKAGE)
    context.first_shown = {key(ON_ONE): SHOWN}
    assert context.finding_body(ON_ONE)["first_shown"] == SHOWN
    assert "first_shown" not in context.finding_body(PASS)


def test_an_earlier_finding_later_withdrawn_gives_no_date(tmp_path: Path) -> None:
    """The default taken: a finding an earlier review showed and then withdrew - an answer said
    its check did not apply - gives no date. The record, which no longer holds it, is what a
    review is taken to have raised; its stream, which showed it, is not read."""
    folder = earlier(tmp_path, f"20260918-090000-{LABEL}", ON_TWO)
    stream = EventSink(folder / "events.jsonl")
    stream.emit("session.started", {"session_id": "00000000-0000-0000-0000-0000000000f1"})
    stream.emit("finding", pane_finding(ON_ONE, {}))
    stream.emit("finding.withdrawn", {"finding_id": ON_ONE.id, "reason": "FICT bought part"})

    assert dates(tmp_path) == {key(ON_TWO): "2026-09-18"}


@pytest.mark.parametrize(
    ("path", "name"),
    [
        ("C:\\FICT\\Designs\\cover-assy.SLDASM", "cover-assy"),
        ("native/cover-assy.SLDASM", "cover-assy"),
        ("C:\\FICT\\a:b*c?d.SLDPRT", "a-b-c-d"),
        ("C:\\FICT\\ .-trimmed-. .SLDASM", "trimmed"),
        ("C:\\FICT\\name.with.dots.SLDASM", "name.with.dots"),
        ("C:\\FICT\\tab\there.SLDPRT", "tab-here"),
        ("C:\\FICT\\" + "x" * 60 + ".SLDASM", "x" * 48),
        ("C:\\FICT\\" + "y" * 47 + " z.SLDASM", "y" * 47),
        ("C:\\FICT\\.SLDPRT", "document"),
        ("", "document"),
    ],
)
def test_a_documents_folder_name_is_the_add_ins(path: str, name: str) -> None:
    """`RunFolders.DocumentName`: the file name without its extension, each character Windows
    refuses in a file name a dash, spaces, periods and dashes trimmed from both ends, cut to 48
    and trimmed again, and `document` when nothing is left."""
    assert document_name(path) == name


def test_only_the_documents_review_folders_are_read(tmp_path: Path, reads: list[Path]) -> None:
    """`RunFolders.FindNotSentReview`'s names: the stamp, then the document's name, ignoring case,
    with or without a collision suffix, and none of a Model check's, a Standards check's or a
    re-modeler's folders; a folder stamped after this review's start is no earlier review. Only
    the folders those names count are opened, each once."""
    counted = {
        f"20260901-090000-{LABEL}": "2026-09-01",
        f"20260902-090000-{LABEL}-2": "2026-09-02",
        "20260903-090000-COVER-ASSY": "2026-09-03",
        f"20261103-085959-{LABEL}": "2026-11-03",
    }
    skipped = [
        f"20260904-090000-{LABEL}-check",
        f"20260905-090000-{LABEL}-check-2",
        f"20260906-090000-{LABEL}-standards",
        f"20260907-090000-{LABEL}-remodel",
        f"20260908-090000-{LABEL}-x",
        f"20260909-090000-{LABEL}x",
        f"20260910-090000-{LABEL}-2-3",
        "20260911-090000-terminal",
        f"2026091-090000-{LABEL}",
        f"20261399-090000-{LABEL}",
        f"20261103-090001-{LABEL}",
        LABEL,
    ]
    findings = {
        name: make_finding(check=f"FICT.check.{index}")
        for index, name in enumerate([*counted, *skipped])
    }
    for name, finding in findings.items():
        earlier(tmp_path, name, finding)

    assert dates(tmp_path) == {key(findings[name]): day for name, day in counted.items()}
    assert sorted(reads) == sorted(tmp_path / name / SESSION_FILE_NAME for name in counted)


# --- the body, the fold, the snapshot and report.md ---------------------------------------------


def test_a_folds_finding_body_keeps_the_date(tmp_package_dir: Path, tmp_path: Path) -> None:
    """A re-run's fold announces its finding again through the one builder (`finding_body`), so
    the body keeps the date, where the withdrawal of the id it was first announced under names
    none."""
    root = tmp_path / "runs"
    earlier(root, f"20260918-090000-{LABEL}", judged("F-004"))
    run = runner.start_review(
        tmp_package_dir,
        root / f"20261103-090000-{LABEL}",
        provider=FakeProvider(script=[chat.turn("FICT nothing yet")], model=chat.MODEL),
        run_root=root,
    )
    run.start()
    run.session.findings[:] = [judged("F-001"), judged("F-002")]
    mark = len(stream_of(run.events_path))

    run._reconcile_restated(1, {}, [], {})

    after = stream_of(run.events_path)[mark:]
    assert [(event["type"], event["body"].get("first_shown")) for event in after[:2]] == [
        ("finding.withdrawn", None),
        ("finding", SHOWN),
    ]


def stream_of(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


AT = datetime(2026, 11, 3, 9, 0, tzinfo=UTC)


def event(seq: int, kind: str, body: dict[str, Any]) -> AgentEvent:
    return AgentEvent(seq=seq, at=AT, type=kind, body=body)  # type: ignore[arg-type]


def test_the_snapshot_and_report_md_read_the_date_back_from_the_stream() -> None:
    """Both snapshots and `report.md` name the date the last `finding` body of each finding the
    session holds names: none where that body names none - here F-002's later body, as a fold onto
    a pass sends one - nor for a finding the session no longer holds (F-003), and none from a
    stream that does not start this session; `report.md` as the first line under the finding's
    heading, in the words file's words. A record with no date keeps its bytes."""
    on_two = ON_TWO.model_copy(update={"id": "F-002"})
    session = record(ON_ONE, on_two)
    names = component_names(PACKAGE)
    stream = [
        event(1, "session.started", {"session_id": str(session.session_id)}),
        event(2, "finding", {**pane_finding(ON_ONE, names), "first_shown": SHOWN}),
        event(3, "finding", {**pane_finding(on_two, names), "first_shown": SHOWN}),
        event(4, "finding", pane_finding(on_two, names)),
        event(5, "finding", {**pane_finding(ON_TWO.model_copy(update={"id": "F-003"}), names),
                             "first_shown": SHOWN}),
    ]

    for read_only in (None, "FICT restarted"):
        snapshot = review_snapshot(
            session, PACKAGE, run_id=SECOND, read_only_reason=read_only, events=stream
        )
        assert [body.get("first_shown") for body in snapshot["findings"]] == [SHOWN, None]
        assert snapshot["findings"][1] == pane_finding(on_two, names)
    report = render_report(session, PACKAGE, events=stream)
    heading = f"#### F-001: {snapshot['findings'][0]['title']}\n\n"
    assert f"{heading}- First shown in the review of {SHOWN}.\n- Check:" in report
    assert report.count("First shown") == 1

    elsewhere = [event(1, "session.started", {"session_id": "FICT-another"}), *stream[1:]]
    assert render_report(session, PACKAGE, events=elsewhere) == render_report(session, PACKAGE)
    assert "first_shown" not in str(
        review_snapshot(session, PACKAGE, run_id=SECOND, events=elsewhere)
    )


# --- through the routes -------------------------------------------------------------------------


def pane_review(client: TestClient, folder: Path, package_dir: Path, **body: Any) -> str:
    """A ticked review of the fixture package in `folder`, as the pane starts one; its chat id."""
    shutil.copytree(package_dir, folder)
    chat_id = str(chat.start_session(client, folder, **body)["chat_id"])
    chat.settle(client, chat_id)
    return chat_id


def finding_bodies(folder: Path) -> list[dict[str, Any]]:
    return [event["body"] for event in chat.events_of(folder) if event["type"] == "finding"]


def without_date(body: dict[str, Any]) -> str:
    return json.dumps({name: value for name, value in body.items() if name != "first_shown"})


def test_a_second_review_names_the_first_ones_date_and_keeps_it_through_a_restart(
    app: Any,
    client: TestClient,
    run_root: Path,
    provider_control: chat.ProviderControl,
    models: chat.Models,
    tmp_package_dir: Path,
) -> None:
    """Two pane reviews of the same document: each `finding` body of the second is the first's,
    byte for byte, with `first_shown` the first's date, which the first's bodies do not name;
    the second's `report.md` names it under each finding, and its live snapshot and its read-only
    restore after a backend restart keep it."""
    pane_review(client, run_root / FIRST, tmp_package_dir)
    second = pane_review(client, run_root / SECOND, tmp_package_dir)

    before, after = finding_bodies(run_root / FIRST), finding_bodies(run_root / SECOND)
    assert before and [body["id"] for body in after] == [body["id"] for body in before]
    validator = contract_validator("chat-events.schema.json")
    for event in chat.events_of(run_root / SECOND):
        validator.validate(event)
    assert all("first_shown" not in body for body in before)
    assert [body["first_shown"] for body in after] == [SHOWN] * len(after)
    assert [without_date(body) for body in after] == [json.dumps(body) for body in before]

    report = (run_root / SECOND / "report.md").read_text(encoding="utf-8")
    for body in after:
        heading = f"#### {body['id']}: {body['title']}\n\n"
        assert f"{heading}- First shown in the review of {SHOWN}.\n" in report, body["id"]
    assert "First shown" not in (run_root / FIRST / "report.md").read_text(encoding="utf-8")

    live = client.get(f"/sessions/{second}/snapshot")
    assert live.status_code == 200, live.text
    assert [body.get("first_shown") for body in live.json()["findings"]] == [SHOWN] * len(after)

    settings = {
        "token": chat.TOKEN,
        "allow_origin": chat.ORIGIN,
        "provider_factory": provider_control.factory,
        "list_models": models,
    }
    with restarted_app(run_root, settings) as fresh:
        restored = fresh.get(f"/reviews/{SECOND}")
        first = fresh.get(f"/reviews/{FIRST}")
    assert restored.status_code == 200, restored.text
    assert restored.json()["read_only"] is True
    assert [body.get("first_shown") for body in restored.json()["findings"]] == [SHOWN] * len(after)
    assert all("first_shown" not in body for body in first.json()["findings"])


def recorded_review(
    app: Any, client: TestClient, folder: Path, package_dir: Path
) -> list[RecordedRequest]:
    """A pane review in `folder` and one follow-up, with every request it sends to the model. The
    first turn reads F-001 whole (`get_finding`), so a finding's fields reach the second request:
    the digest names the fixture's findings by their count alone."""
    provider = RecordingProvider(
        [chat.turn("FICT checked", chat.call("get_finding", finding_id="F-001")),
         chat.turn("FICT again")]
    )
    app.state.server.provider_factory = lambda settings: provider
    chat_id = pane_review(client, folder, package_dir)
    response = client.post(f"/sessions/{chat_id}/messages", json={"text": "FICT and the rest?"})
    assert response.status_code == 202, response.text
    chat.settle(client, chat_id)
    return provider.log


def test_the_date_adds_nothing_to_what_the_model_is_sent(
    app: Any, client: TestClient, run_root: Path, tmp_package_dir: Path
) -> None:
    """The date is the engineer's, for 188A's note, never the model's: a review whose findings an
    earlier review first showed sends the model every request byte for byte as the earlier one
    did, two turns of them, and no request names the date."""
    first = recorded_review(app, client, run_root / FIRST, tmp_package_dir)
    second = recorded_review(app, client, run_root / SECOND, tmp_package_dir)

    assert [body["first_shown"] for body in finding_bodies(run_root / SECOND)]
    assert len(first) == len(second) == 2
    for one, two in zip(first, second, strict=True):
        assert (two.system, two.encoded_tools, two.encoded_history) == (
            one.system,
            one.encoded_tools,
            one.encoded_history,
        )
        sent = two.system.encode("utf-8") + two.encoded_tools + b"".join(two.encoded_history)
        assert SHOWN.encode("utf-8") not in sent


def test_a_check_again_names_its_earlier_records_date(
    app: Any,
    client: TestClient,
    run_root: Path,
    provider_control: chat.ProviderControl,
    models: chat.Models,
) -> None:
    """Check again after a restart (feature 015): the re-run's flagged findings that its earlier
    record, in the same folder, raised flagged name that folder's date; the others name none."""
    folder = run_root / "20260918-090000-FICT-7000"
    held = recheck.earlier_review(app, client, folder)
    document = root_document(load_package(folder).package)
    assert document is not None and document_name(document["path"]) == "FICT-7000"
    flagged = {key(finding) for finding in held.record.findings if finding.status != PASS.status}

    seat = recheck.server_settings(provider_control, models, recheck.silent_seat())
    with restarted_app(run_root, seat) as fresh:
        rerun = recheck.rerun_of(fresh, folder)

    last = {body["id"]: body for body in finding_bodies(folder)}
    expected = {
        finding.id: SHOWN if finding.status != PASS.status and key(finding) in flagged else None
        for finding in rerun.session.findings
    }
    assert SHOWN in expected.values()
    assert {finding_id: last[finding_id].get("first_shown") for finding_id in expected} == expected
