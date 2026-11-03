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

*Changed 2026-11-03 (T392, the cycle's Tier 2 review):* the date is the day the record's review
showed the finding, by the record's own clock, and the folder's older records are read too; an
earlier finding gives none once a component it names is another part's here; the match reads
oldest first, within a budget; and a review started unticked in another configuration counts.

*Changed 2026-11-03 (cycle 21, T394; roadmap hole H-d-009):* a date is never another subject's.
An earlier record of another dump than this review's has each id its key holds matched by the
stable name its own dump gives it, read from the package in its folder - a component by its full
instance path, an entity by its name in its document - so an instance or entity an edit renumbered
names none, one whose id moved keeps its date, and an id with no stable name gives none; a record
of this review's own dump keeps its ids as they are. Cycle 17's cases are of that one dump.
"""

from __future__ import annotations

import itertools
import json
import re
import shutil
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from starlette.testclient import TestClient

from swreview.agent import runner
from swreview.agent.events import EventSink
from swreview.agent.providers import AgentEvent
from swreview.agent.providers.fake import FakeProvider
from swreview.benchmark.origins import finding_origin
from swreview.findings import MODEL_FINDING_CHECK, Finding, SubjectKey, finding_subject_key
from swreview.ir.loader import PACKAGE_FILE_NAME, load_package, save_package
from swreview.ir.models import (
    ComponentInstance,
    CosmeticThread,
    DisplayDimensionRecord,
    Document,
    DrawingAnnotation,
    DrawingRecord,
    DrawingSheetRecord,
    DrawingView,
    EvidencePackage,
    Feature,
    Hole,
    ManifestEntry,
    SourceRef,
)
from swreview.report import first_shown
from swreview.report.first_shown import document_name, first_shown_dates
from swreview.report.markdown import render_report
from swreview.report.names import component_names
from swreview.report.session import (
    ORIGIN_MARKS_VERSION,
    SESSION_FILE_NAME,
    InvestigationStep,
    ModelStatus,
    ReviewedDocument,
    ReviewSession,
    StepMark,
    load_session,
    save_session,
)
from swreview.report.snapshot import review_snapshot, root_document
from swreview.report.titles import pane_finding
from swreview.tools.context import context_for, new_session
from tests.support.contracts import contract_validator
from tests.support.findings import make_finding
from tests.support.packages import build_package, persist_ref
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
    *findings: Finding,
    package: Any = PACKAGE,
    document: ReviewedDocument | None = None,
    started: datetime | None = None,
) -> ReviewSession:
    """An earlier review's record of `findings`. With `document`, a review started unticked,
    whose record names its document and configuration (`model_status.document`).

    *Changed 2026-11-03 (T392, the Tier 2 review's must-fix):* started at `started`, a local wall
    clock, when it is given, since a record now dates its findings by its own clock rather than
    its folder's name; otherwise now, as `new_session` starts one."""
    session = new_session(package).model_copy(update={"findings": list(findings)})
    if started is not None:
        session.started_at = started.astimezone(UTC)
    if document is not None:
        session.model_status = ModelStatus(
            state="not_sent", document=document, checked_at=datetime(2026, 9, 1, tzinfo=UTC)
        )
    return session


def earlier(root: Path, name: str, *findings: Finding, **options: Any) -> Path:
    """A review folder `name` under `root`, holding the record of `findings`.

    *Changed 2026-11-03 (T392, the Tier 2 review's must-fix):* the record started when the name's
    stamp says, as a review the add-in named that day did, unless `started` says otherwise; a name
    with no stamp, which the match never opens, keeps now."""
    folder = root / name
    options.setdefault("started", stamped(name))
    save_session(record(*findings, **options), folder / SESSION_FILE_NAME)
    return folder


def stamped(name: str) -> datetime | None:
    """The local wall clock a folder's name begins with, `yyyyMMdd-HHmmss`, or `None`."""
    try:
        return datetime.strptime(name[:15], "%Y%m%d-%H%M%S")
    except ValueError:
        return None


WAITING: ReviewedDocument = {"path": "native/cover-assy.SLDASM", "configuration": "Default"}
"""The document a review of `PACKAGE` started unticked names."""


def step(index: int, mark: StepMark | None) -> InvestigationStep:
    """A recorded call: the pre-run's or code's re-grade, by its `mark`, or the model's with
    none."""
    return InvestigationStep(
        index=index,
        tool="FICT_check",
        arguments={},
        result_summary="FICT",
        status="ok",
        error=None,
        elapsed_s=0.0,
        origin_mark=mark,
    )


PRERUN, TURN, REGRADE = step(0, "prerun"), step(1, None), step(2, "regrade")
"""The pre-run's call, a call the model asked for in a turn, and code's re-grade after an answer."""


def citing(finding: Finding, *steps: InvestigationStep) -> Finding:
    """`finding` as `steps` recorded it, citing them by their indexes (`tool_result_ids`)."""
    return finding.model_copy(update={"tool_result_ids": [one.index for one in steps]})


def sent(session: ReviewSession, at: datetime, *steps: InvestigationStep) -> ReviewSession:
    """`session`, a review started unticked, as its engineer sent it at `at`, a local wall clock,
    with `steps` recorded and marked as every session `start_review` begins marks them."""
    assert session.model_status is not None
    session.model_status.state = "sent"
    session.model_status.sent_at = at.astimezone()
    session.steps = list(steps)
    session.origin_marks = ORIGIN_MARKS_VERSION
    return session


def dates(root: Path, package: EvidencePackage = PACKAGE, **options: Any) -> dict[SubjectKey, str]:
    """`first_shown_dates` for a review of `package` in a folder of its own, started at `BEFORE`.

    *Changed 2026-11-03 (cycle 21, T394):* of `package`, `PACKAGE` unless a test names another
    dump."""
    own = root / f"20261103-090000-{LABEL}"
    own.mkdir(parents=True, exist_ok=True)
    return first_shown_dates(root, own, package, before=BEFORE, **options)


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
    record already there is not an earlier review's.

    *Changed 2026-11-03 (T392, the Tier 2 review's must-fix):* nor is a record a Retry in the same
    folder moved aside, `session.<n>.json`: it is this review's own failed attempt, where an
    earlier folder's are read."""
    own = earlier(tmp_path, f"20260918-090000-{LABEL}", ON_ONE)
    save_session(record(ON_TWO, started=datetime(2026, 9, 18, 8, 0)), own / "session.1.json")

    assert first_shown_dates(tmp_path, own, PACKAGE, before=BEFORE) == {}
    assert reads == []


def test_a_check_agains_earlier_record_counts(tmp_path: Path, reads: list[Path]) -> None:
    """A Check again re-runs a waiting review in its own folder: the earlier record the re-run
    holds counts, dated by the day it started, and is not read again.

    *Changed 2026-11-03 (T392, the Tier 2 review's must-fix):* dated by its own start, which is
    the folder's day here, not by the folder's name."""
    own = earlier(tmp_path, f"20260918-090000-{LABEL}", ON_ONE)
    held = record(ON_ONE, ON_TWO, started=datetime(2026, 9, 18, 9, 0))

    assert first_shown_dates(tmp_path, own, PACKAGE, before=BEFORE, earlier=held) == {
        key(ON_ONE): "2026-09-18",
        key(ON_TWO): "2026-09-18",
    }
    assert reads == []


def test_a_send_after_a_restart_dates_what_its_turn_raised_by_the_day_it_was_sent(
    tmp_path: Path,
) -> None:
    """The Tier 2 review's must-fix: Send on a waiting review restored after a restart re-runs it
    in its folder, keeping the waiting record as `session.<n>.json` and replacing `session.json`
    (015 `contracts/recheck.md` sections 1 and 4). A finding the re-run's turn raised after the
    Send is dated by the day it was sent, not by the folder's name; one the waiting record showed
    keeps that record's day, though the re-run's checks raised it again a week later."""
    folder = earlier(tmp_path, f"20260918-100000-{LABEL}", ON_ONE, document=WAITING)
    waiting = load_session(folder / SESSION_FILE_NAME)
    (folder / SESSION_FILE_NAME).replace(folder / "session.1.json")
    rerun = record(
        citing(ON_ONE, PRERUN),
        citing(ON_TWO, TURN),
        document=WAITING,
        started=datetime(2026, 9, 25, 10, 0),
    )
    assert rerun.model_status is not None
    rerun.model_status.rechecked_from = waiting.session_id
    sent(rerun, datetime(2026, 9, 25, 10, 5), PRERUN, TURN)
    save_session(rerun, folder / SESSION_FILE_NAME)

    assert dates(tmp_path) == {key(ON_ONE): "2026-09-18", key(ON_TWO): "2026-09-25"}


@pytest.mark.parametrize(
    ("finding", "day"),
    [
        (citing(ON_TWO, PRERUN), "2026-09-18"),
        (make_finding(check="provenance.FICT_modified", component_ids=["cmp:0002"]), "2026-09-18"),
        (
            citing(ON_TWO, step(7, None)).model_copy(update={"carried_over_from": UUID(int=7)}),
            "2026-09-18",
        ),
        (citing(ON_TWO, TURN), "2026-09-25"),
        (ON_TWO, "2026-09-25"),
        (citing(ON_TWO, REGRADE), "2026-09-25"),
    ],
    ids=[
        "the pre-run's",
        "a set-up record",
        "carried from an earlier run",
        "a call of the model's",
        "a check the model set up",
        "a re-grade after an answer",
    ],
)
def test_a_send_on_a_later_day_dates_only_what_a_turn_raised_by_it(
    tmp_path: Path, finding: Finding, day: str
) -> None:
    """The Tier 2 review's must-fix: a waiting review its engineer sent live a week after its
    checks ran is one record. What the checks raised before any turn - the pre-run's, a set-up
    record, a finding carried from an earlier run (`benchmark/origins.finding_origin`'s `prerun`,
    `setup` and `carried`) - keeps the day the review started; what a turn raised after the Send
    - a call of the model's, a check it set up, code's re-grade after an answer - takes the day
    it was sent. The match reads those origins itself, since `finding_origin` cannot be imported
    there, so each case's day is held to `finding_origin`'s reading too."""
    session = record(finding, document=WAITING, started=datetime(2026, 9, 18, 9, 0))
    sent(session, datetime(2026, 9, 25, 9, 0), PRERUN, TURN, REGRADE)
    save_session(session, tmp_path / f"20260918-090000-{LABEL}" / SESSION_FILE_NAME)

    assert dates(tmp_path) == {key(finding): day}
    before_any_turn = finding_origin(finding, session) in {"carried", "setup", "prerun"}
    assert before_any_turn == (day == "2026-09-18")


def test_a_check_agains_earlier_records_are_each_dated_by_the_day_they_ran(
    tmp_path: Path, reads: list[Path]
) -> None:
    """The Tier 2 review's must-fix: a Check again of a record that was itself a re-run holds that
    record, dated by the day it ran, and reads the older one its folder keeps as
    `session.<n>.json`, dated by its own: a finding the first showed keeps the first's day, and
    one only the re-run raised takes the re-run's. The folder's `session.json`, the record held,
    is not read again."""
    own = earlier(tmp_path, f"20260918-090000-{LABEL}", ON_ONE)
    (own / SESSION_FILE_NAME).replace(own / "session.1.json")
    held = record(ON_ONE, ON_TWO, started=datetime(2026, 9, 25, 9, 0))
    save_session(held, own / SESSION_FILE_NAME)

    assert first_shown_dates(tmp_path, own, PACKAGE, before=BEFORE, earlier=held) == {
        key(ON_ONE): "2026-09-18",
        key(ON_TWO): "2026-09-25",
    }
    assert reads == [own / "session.1.json"]


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
    folder of this one's name - its design, or the document a review started unticked names - is
    read and ignored. The path is compared ignoring case (`PageDocument.IsSameDocument`).

    *Changed 2026-11-03 (T392, the Tier 2 review's should-fix 5):* a review started unticked in
    another configuration is no longer another document's, so its case moved to
    `test_a_review_in_another_configuration_counts_as_one_sent_at_once_always_has`: its findings
    match by their own configuration, as a review sent at once's always have."""
    other = PACKAGE.model_copy(
        update={"design": PACKAGE.design.model_copy(update={"design_id": "dsn:FICT-other"})}
    )
    counted = [
        earlier(tmp_path, f"20260912-090000-{LABEL}", ON_ONE, package=other),
        earlier(tmp_path, f"20260915-090000-{LABEL}", ON_ONE,
                document={"path": "native/FICT-other.SLDASM", "configuration": "Default"}),
        earlier(tmp_path, f"20260919-090000-{LABEL}", ON_ONE,
                document={"path": "NATIVE/Cover-Assy.SLDASM", "configuration": "Default"}),
    ]
    earlier(tmp_path, "20260913-090000-housing", ON_ONE)

    assert dates(tmp_path) == {key(ON_ONE): "2026-09-19"}
    assert sorted(reads) == sorted(folder / SESSION_FILE_NAME for folder in counted)


def test_a_review_in_another_configuration_counts_as_one_sent_at_once_always_has(
    tmp_path: Path,
) -> None:
    """The Tier 2 review's should-fix 5, the default taken: however an earlier review of the
    document was started, its findings match by each one's own configuration, the last part of
    its subject key. A review started unticked in another configuration gives its date to a
    finding raised in this review's configuration, as a review sent at once has always given it,
    and a finding raised in the other configuration gives one only to a finding raised there."""
    elsewhere = ON_TWO.model_copy(update={"configuration": "FICT-other"})
    other: ReviewedDocument = {"path": "native/cover-assy.SLDASM", "configuration": "FICT-other"}
    earlier(tmp_path, f"20260914-090000-{LABEL}", ON_ONE, elsewhere, document=other)
    earlier(tmp_path, f"20260915-090000-{LABEL}", ON_ONE, elsewhere)

    shown = dates(tmp_path)

    assert shown == {key(ON_ONE): "2026-09-14", key(elsewhere): "2026-09-14"}
    assert key(ON_TWO) not in shown


def test_an_earlier_finding_on_another_part_under_the_same_number_gives_no_date(
    tmp_path: Path,
) -> None:
    """The Tier 2 review's should-fix 1, the default taken: a component's id is its place in each
    dump's numbering, so an earlier finding gives its date only while each component it names is,
    in this review's package, an instance of a document the finding drew on (`provenance`). A
    finding on another part, which an edit to the tree has since renumbered so that housing-1 has
    its number, gives none; one on the housing does."""
    bracket = ON_ONE.provenance[0].model_copy(
        update={"document_id": "doc:FICT-bracket", "vault_path": "native/FICT-bracket.SLDPRT"}
    )
    moved = ON_ONE.model_copy(update={"provenance": [bracket]})
    earlier(tmp_path, f"20260916-090000-{LABEL}", moved)
    earlier(tmp_path, f"20260918-090000-{LABEL}", ON_ONE)

    assert key(moved) == key(ON_ONE)
    assert dates(tmp_path) == {key(ON_ONE): "2026-09-18"}


@pytest.mark.parametrize(
    "finding",
    [
        make_finding(
            check=MODEL_FINDING_CHECK,
            component_ids=[],
            drawing_locations=[SourceRef(document_id="doc:1", sheet="Sheet1", view="FICT View1")],
            numeric=False,
            source="model",
        ),
        make_finding(check="FICT.check.document", component_ids=[], document_ids=["doc:2"]),
    ],
    ids=["a drawing's", "a document-scoped one"],
)
def test_an_earlier_finding_naming_no_component_keeps_its_date(
    tmp_path: Path, finding: Finding
) -> None:
    """The read-only check's should-fix 2 (T392): the part guard asks only of the components a
    finding names, so one naming none - a drawing's, which `record_drawing_finding` places by its
    sheet and view alone, or a document-scoped one - keeps its date."""
    earlier(tmp_path, f"20260916-090000-{LABEL}", finding)

    assert dates(tmp_path) == {key(finding): "2026-09-16"}


def test_an_earlier_finding_on_two_parts_gives_none_once_the_second_is_another_parts(
    tmp_path: Path,
) -> None:
    """The read-only check's should-fix 2 (T392): each component a finding names must still be an
    instance of a document it drew on, not just one of them. A finding on both housings keeps
    its date while the tree is as it was, and gives none once an edit has given the second
    housing's number to a bracket."""
    both = make_finding(component_ids=["cmp:0001", "cmp:0002"])
    earlier(tmp_path, f"20260916-090000-{LABEL}", both)
    assembly, housing = PACKAGE.documents
    bracket = housing.model_copy(
        update={"document_id": "doc:FICT-bracket", "file_name": "FICT-bracket.SLDPRT",
                "path": "native/FICT-bracket.SLDPRT"}
    )
    first, second = PACKAGE.components
    edited = PACKAGE.model_copy(
        update={
            "documents": [assembly, housing, bracket],
            "components": [first, second.model_copy(update={"document_id": bracket.document_id})],
        }
    )

    assert dates(tmp_path) == {key(both): "2026-09-16"}
    own = tmp_path / f"20261103-090000-{LABEL}"
    assert first_shown_dates(tmp_path, own, edited, before=BEFORE) == {}


def test_the_match_reads_the_oldest_reviews_first_and_stops_at_its_budget(
    tmp_path: Path, reads: list[Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Tier 2 review's should-fix 2, the default taken: however many earlier reviews of the
    document the seat keeps, the match spends at most `READ_BUDGET_S` opening them, oldest first,
    so a review's start never waits on it longer; a finding only a review it did not reach showed
    names no date, never a later one. Here each folder costs a second of a two-second budget."""
    clock = itertools.count(0.0, 1.0)
    monkeypatch.setattr(first_shown, "monotonic", lambda: next(clock), raising=False)
    monkeypatch.setattr(first_shown, "READ_BUDGET_S", 2.0, raising=False)
    newest = earlier(tmp_path, f"20260918-090000-{LABEL}", make_finding(check="FICT.check.new"))
    middle = earlier(tmp_path, f"20260917-090000-{LABEL}", ON_ONE, ON_TWO)
    oldest = earlier(tmp_path, f"20260916-090000-{LABEL}", ON_ONE)

    assert dates(tmp_path) == {key(ON_ONE): "2026-09-16", key(ON_TWO): "2026-09-17"}
    assert reads == [oldest / SESSION_FILE_NAME, middle / SESSION_FILE_NAME]
    assert newest / SESSION_FILE_NAME not in reads


def test_a_check_agains_own_folder_counts_however_long_the_older_reviews_took(
    tmp_path: Path, reads: list[Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The read-only check's should-fix 1 (T392): the budget bounds the other reviews, not the
    review's own folder, the document's newest and so the first it would cut. A Check again's
    earlier record is already held, and the records its folder moved aside are this review's
    own few, so what they showed keeps its day however long the older reviews took: here a
    finding the waiting record showed on 09-20 and its re-run again on 09-25, and one only the
    re-run showed. Each other folder costs a second of a two-second budget."""
    clock = itertools.count(0.0, 1.0)
    monkeypatch.setattr(first_shown, "monotonic", lambda: next(clock), raising=False)
    monkeypatch.setattr(first_shown, "READ_BUDGET_S", 2.0, raising=False)
    oldest = earlier(tmp_path, f"20260916-090000-{LABEL}", ON_ONE)
    middle = earlier(tmp_path, f"20260917-090000-{LABEL}", ON_ONE)
    earlier(tmp_path, f"20260918-090000-{LABEL}", make_finding(check="FICT.check.cut"))
    own = earlier(tmp_path, f"20260920-090000-{LABEL}", ON_TWO)
    (own / SESSION_FILE_NAME).replace(own / "session.1.json")
    rerun_only = make_finding(check="FICT.check.rerun")
    held = record(ON_TWO, rerun_only, started=datetime(2026, 9, 25, 9, 0))
    save_session(held, own / SESSION_FILE_NAME)

    assert first_shown_dates(tmp_path, own, PACKAGE, before=BEFORE, earlier=held) == {
        key(ON_ONE): "2026-09-16",
        key(ON_TWO): "2026-09-20",
        key(rerun_only): "2026-09-25",
    }
    assert reads == [oldest / SESSION_FILE_NAME, middle / SESSION_FILE_NAME, own / "session.1.json"]


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


DOCUMENT_NAMES = (
    Path(__file__).resolve().parents[1] / "fixtures" / "run-folders" / "document-names.json"
)
"""`RunFolders.DocumentName`'s cases: one table, which the add-in's own test reads too
(`RunFoldersNotSentTests.TheDocumentNameIsTheOneTheBackendFindsReviewsBy`), so the two rules
cannot part."""

ADD_IN = Path(__file__).resolve().parents[3] / "extractor" / "SwReview.AddIn"

RUN_FOLDERS = ADD_IN / "Review" / "RunFolders.cs"
"""The add-in's rules for a run folder's name, which `report/first_shown` copies."""


@pytest.mark.parametrize(
    ("path", "name"),
    [(row["path"], row["name"]) for row in json.loads(DOCUMENT_NAMES.read_text(encoding="utf-8"))],
)
def test_a_documents_folder_name_is_the_add_ins(path: str, name: str) -> None:
    """`RunFolders.DocumentName`: the file name without its extension, each character Windows
    refuses in a file name a dash, spaces, periods and dashes trimmed from both ends, cut to 48
    and trimmed again, and `document` when nothing is left.

    *Changed 2026-11-03 (T392, the Tier 2 review's should-fix 4):* the cases are `DOCUMENT_NAMES`,
    which the add-in's test reads too, with one more: every character Windows refuses in a file
    name but the two separators."""
    assert document_name(path) == name


def test_the_folder_rules_are_the_add_ins() -> None:
    """The Tier 2 review's should-fix 4: what `report/first_shown` copies of `RunFolders.cs` is
    pinned to it - the stamp's format (`TimestampFormat`), the name's budget (`MaxNameLength`)
    and the suffixes `FindNotSentReview` skips - so a change there fails here, rather than
    silently ending the dates or letting another run's folders in."""
    source = RUN_FOLDERS.read_text(encoding="utf-8")

    def constant(name: str) -> str:
        found = re.search(rf'\b{name} = "?([^";]+)"?;', source)
        assert found is not None, name
        return found.group(1)

    finder = source[source.index("SessionRecord? FindNotSentReview(") :]
    finder = finder[: finder.index("ReadSessionHead(")]
    skipped = re.findall(r"CarriesSuffix\(name, (\w+Suffix)\)", finder)

    assert (constant("TimestampFormat"), first_shown.STAMP_FORMAT) == (
        "yyyyMMdd-HHmmss",
        "%Y%m%d-%H%M%S",
    )
    assert first_shown.STAMP.fullmatch(datetime(2026, 9, 18).strftime(first_shown.STAMP_FORMAT))
    assert int(constant("MaxNameLength")) == first_shown.NAME_LENGTH
    assert skipped == ["CheckSuffix", "StandardsSuffix", "RemodelSuffix"]
    assert tuple(constant(name) for name in skipped) == first_shown.OTHER_RUNS


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


# --- across two dumps (cycle 21; roadmap hole H-d-009) -----------------------------------------

BOLT, SPACER, DRAWING = "doc:3", "doc:4", "doc:5"
"""Three more documents of `DESIGN`: a bolt and a spacer, parts of the assembly, and its
drawing."""

SHEET, VIEW = "Sheet1", "FICT View1"
"""The drawing's one sheet, and the view a drawing's entities are read from."""

ASSEMBLY, HOUSING = PACKAGE.documents
HOUSING_ENTRY = PACKAGE.manifest.entries[1]


def part(document_id: str, file_name: str, kind: str = "part") -> tuple[Document, ManifestEntry]:
    """The document `document_id`, `file_name`, with its manifest entry."""
    return (
        HOUSING.model_copy(
            update={"document_id": document_id, "kind": kind, "file_name": file_name,
                    "path": f"native/{file_name}"}
        ),
        HOUSING_ENTRY.model_copy(
            update={"document_id": document_id, "vault_path": f"/Designs/{file_name}"}
        ),
    )


ADDED = [
    part(BOLT, "FICT-bolt.SLDPRT"),
    part(SPACER, "FICT-spacer.SLDPRT"),
    part(DRAWING, "cover-assy.SLDDRW", "drawing"),
]

DESIGN = PACKAGE.model_copy(
    update={
        "documents": [*PACKAGE.documents, *(document for document, _ in ADDED)],
        "manifest": PACKAGE.manifest.model_copy(
            update={"entries": [*PACKAGE.manifest.entries, *(entry for _, entry in ADDED)]}
        ),
    }
)
"""`PACKAGE`'s assembly with a bolt, a spacer and a drawing among its documents: what each dump
below reads, numbering its entities as each test says."""


def dumped_as(number: int, **numbered: Any) -> EvidencePackage:
    """`DESIGN` as dump `number` read it - its own package id, as every extraction makes one - with
    the entities it numbered, `numbered`."""
    return DESIGN.model_copy(update={"package_id": UUID(int=number), **numbered})


def dumped(root: Path, name: str, dump: EvidencePackage, *findings: Finding) -> Path:
    """A review folder `name` under `root` as the add-in leaves one: the package it dumped, `dump`,
    beside the record of `findings` its review raised on it."""
    folder = earlier(root, name, *findings, package=dump)
    save_package(dump, folder)
    return folder


def instance(number: int, path: str, document_id: str = HOUSING.document_id) -> ComponentInstance:
    """The component `cmp:<number>`, the instance `path` of `document_id`."""
    return PACKAGE.components[0].model_copy(
        update={"id": f"cmp:{number:04d}", "persist_ref": persist_ref(path), "name": path,
                "full_path": path, "document_id": document_id}
    )


def hole(number: int, name: str) -> Hole:
    """`hol:<number>`, the Hole Wizard feature `name` of housing-1."""
    return PACKAGE.holes[0].model_copy(
        update={"id": f"hol:{number:04d}", "persist_ref": persist_ref(name), "feature_name": name}
    )


def feature(number: int, name: str) -> Feature:
    """`feat:<number>`, the feature `name` of the housing's tree."""
    return Feature(
        id=f"feat:{number:04d}",
        persist_ref=persist_ref(name),
        persist_ref_scope=HOUSING.document_id,
        document_id=HOUSING.document_id,
        configuration="Default",
        name=name,
        type_name="FICT",
        description=None,
        index=number - 1,
        depth=0,
        folder_id=None,
        suppressed=False,
        error_code=None,
        child_ids=None,
        parent_ids=None,
        sketch=None,
        fillet=None,
    )


def drawing(
    views: list[str] | None = None,
    dimensions: list[str] | None = None,
    annotations: list[str] | None = None,
) -> DrawingRecord:
    """The drawing's one sheet, `SHEET`: an empty view for each of `views`; or, with none named,
    `VIEW` alone, holding a display dimension for each of `dimensions` and an annotation for each
    of `annotations`. Each is named so and numbered from 1 in that order, as the extractor
    numbers them."""
    sheet = "dsh:0001"
    if views is not None:
        shown = [
            DrawingView(id=f"dvw:{number:04d}", sheet_id=sheet, name=name)
            for number, name in enumerate(views, start=1)
        ]
    else:
        shown = [
            DrawingView(
                id="dvw:0001",
                sheet_id=sheet,
                name=VIEW,
                display_dimensions=[
                    DisplayDimensionRecord(id=f"ddm:{number:04d}", view_id="dvw:0001", name=name)
                    for number, name in enumerate(dimensions or [], start=1)
                ],
                annotations=[
                    DrawingAnnotation(id=f"dan:{number:04d}", owner_id="dvw:0001", name=name)
                    for number, name in enumerate(annotations or [], start=1)
                ],
            )
        ]
    return DrawingRecord(
        document_id=DRAWING,
        sheets=[DrawingSheetRecord(id=sheet, name=SHEET, index=0, was_active=True, views=shown)],
    )


def renumbered(kind: str, number: int, names: list[str]) -> EvidencePackage:
    """Dump `number` of `DESIGN` with an entity of `kind` for each of `names`, in that order, so
    numbered from 1: holes of housing-1, features of the housing, or the drawing's views,
    display dimensions or annotations."""
    if kind == "hol":
        return dumped_as(number, holes=[hole(index, name) for index, name in enumerate(names, 1)])
    if kind == "feat":
        return dumped_as(
            number, features=[feature(index, name) for index, name in enumerate(names, 1)]
        )
    entities = {"dvw": "views", "ddm": "dimensions", "dan": "annotations"}
    return dumped_as(number, drawing_records=[drawing(**{entities[kind]: names})])


def citing_entity(kind: str, package: EvidencePackage, number: int) -> Finding:
    """A flagged finding of `package` about the entity `<kind>:<number>`, named where the checks
    name one: a hole among its inputs, on housing-1; a feature among its inputs, the housing's;
    a view as a drawing finding's place; a display dimension or an annotation as the annotation
    of its place on the sheet."""
    entity = f"{kind}:{number:04d}"
    if kind == "hol":
        return make_finding(package=package, inputs=[entity])
    if kind == "feat":
        return make_finding(
            package=package, component_ids=[], document_ids=[HOUSING.document_id], inputs=[entity]
        )
    if kind == "dvw":
        place = SourceRef(document_id=DRAWING, sheet=SHEET, view=entity)
    else:
        place = SourceRef(document_id=DRAWING, sheet=SHEET, view=VIEW, annotation=entity)
    return make_finding(
        package=package,
        check=MODEL_FINDING_CHECK,
        component_ids=[],
        drawing_locations=[place],
        numeric=False,
        source="model",
    )


def test_of_two_instances_of_one_part_the_renumbered_second_names_no_date(tmp_path: Path) -> None:
    """Roadmap hole H-d-009's case (`docs/review-backlog.md`, cycle 17): an earlier review flagged
    the first of two instances of one bolt, `cmp:0003` beside `cmp:0004`; a spacer removed before
    them makes the second bolt `cmp:0003`, the earlier finding's very key, and the first
    `cmp:0002`. Each instance is matched by its full path: the second, a new problem, names no
    date, and the first, its id moved, names the earlier review's."""
    before_edit = dumped_as(
        1,
        components=[
            instance(1, "housing-1"),
            instance(2, "FICT-spacer-1", SPACER),
            instance(3, "FICT-bolt-1", BOLT),
            instance(4, "FICT-bolt-2", BOLT),
        ],
    )
    after_edit = dumped_as(
        2,
        components=[
            instance(1, "housing-1"),
            instance(2, "FICT-bolt-1", BOLT),
            instance(3, "FICT-bolt-2", BOLT),
        ],
    )
    shown = make_finding(package=before_edit, component_ids=["cmp:0003"])
    first = make_finding(package=after_edit, component_ids=["cmp:0002"])
    second = make_finding(package=after_edit, component_ids=["cmp:0003"])
    dumped(tmp_path, f"20260918-090000-{LABEL}", before_edit, shown)

    assert key(second) == key(shown)
    assert dates(tmp_path, after_edit) == {key(first): "2026-09-18"}


def test_a_part_whose_old_number_another_part_now_holds_keeps_its_date(tmp_path: Path) -> None:
    """Cycle 21's gain over cycle 17's guard: a second housing added before the bolt gives the bolt
    `cmp:0003` and the new housing the bolt's old `cmp:0002`. The bolt's finding is matched by its
    full path and keeps its date, the part guard asked of the bolt as this review numbers it;
    the housing's finding of the same check, a new problem on another part, names none."""
    before_edit = dumped_as(
        1, components=[instance(1, "housing-1"), instance(2, "FICT-bolt-1", BOLT)]
    )
    after_edit = dumped_as(
        2,
        components=[
            instance(1, "housing-1"),
            instance(2, "housing-2"),
            instance(3, "FICT-bolt-1", BOLT),
        ],
    )
    shown = make_finding(package=before_edit, component_ids=["cmp:0002"])
    bolt = make_finding(package=after_edit, component_ids=["cmp:0003"])
    housing = make_finding(package=after_edit, component_ids=["cmp:0002"])
    dumped(tmp_path, f"20260918-090000-{LABEL}", before_edit, shown)

    assert key(housing) == key(shown)
    assert dates(tmp_path, after_edit) == {key(bolt): "2026-09-18"}


@pytest.mark.parametrize(
    "kind",
    ["hol", "feat", "dvw", "ddm", "dan"],
    ids=["a hole", "a feature", "a drawing view", "a drawing dimension", "a drawing annotation"],
)
def test_an_entity_renumbered_in_an_edited_document_is_matched_by_its_name(
    tmp_path: Path, kind: str
) -> None:
    """Roadmap hole H-d-009: an edit adds an entity before two others of its document - a hole
    to the housing, a feature to its tree, a view, a dimension or an annotation to the drawing -
    and each id after it moves up one. An earlier review flagged the second; this review's
    finding under that id is the first's, a new problem, and names no date, and its finding on
    the second, under its new id, names the earlier review's: each is matched by the name the
    dump gives it in its document - the hole's feature, the feature's, the view's, the
    dimension's full name, the annotation's."""
    before_edit = renumbered(kind, 1, ["FICT one", "FICT two"])
    after_edit = renumbered(kind, 2, ["FICT new", "FICT one", "FICT two"])
    shown = citing_entity(kind, before_edit, 2)
    moved_onto = citing_entity(kind, after_edit, 2)
    moved = citing_entity(kind, after_edit, 3)
    dumped(tmp_path, f"20260918-090000-{LABEL}", before_edit, shown)

    assert key(moved_onto) == key(shown)
    assert dates(tmp_path, after_edit) == {key(moved): "2026-09-18"}


NEEDS_A_NAME = make_finding(package=dumped_as(1))
"""A flagged finding on housing-1, `cmp:0001`, raised on dump 1: matched by the name of its part."""

NEEDS_NONE = [
    make_finding(
        package=dumped_as(1),
        check="FICT.check.document",
        component_ids=[],
        document_ids=[HOUSING.document_id],
    ),
    make_finding(
        package=dumped_as(1),
        check=MODEL_FINDING_CHECK,
        component_ids=[],
        drawing_locations=[SourceRef(document_id=DRAWING, sheet=SHEET, view=VIEW)],
        numeric=False,
        source="model",
    ),
]
"""Flagged findings whose keys hold no id: a document-scoped one, and a drawing's placed by the
names of its sheet and view."""


@pytest.mark.parametrize("left", ["gone", "cut off", "another dump's"])
def test_a_folder_without_its_records_package_gives_no_date_to_a_finding_needing_a_name(
    tmp_path: Path, left: str
) -> None:
    """The route's "older record without the names" (roadmap hole H-d-009): the names come from
    the package in the earlier review's folder, the dump its record's ids number. A folder whose
    package is gone, cut off, or another dump's than its record's - checked by the package id the
    record names - gives no date to a finding naming a component, and keeps it for a finding
    whose key holds no id."""
    folder = dumped(tmp_path, f"20260918-090000-{LABEL}", dumped_as(1), NEEDS_A_NAME, *NEEDS_NONE)
    package = folder / PACKAGE_FILE_NAME
    if left == "gone":
        package.unlink()
    elif left == "cut off":
        whole = package.read_bytes()
        package.write_bytes(whole[: len(whole) // 2])
    else:
        save_package(dumped_as(3), folder)

    assert dates(tmp_path, dumped_as(2)) == {key(finding): "2026-09-18" for finding in NEEDS_NONE}


def test_the_design_dumped_again_keeps_a_named_ids_date_and_gives_none_for_an_unnamed_one(
    tmp_path: Path,
) -> None:
    """The design dumped again, unchanged, is numbered as before, but across two dumps only a
    stable name says so. A finding on a component, matched by its full path, keeps its date, and
    so does one holding a document's id, a path hash (`DocumentIds`) the same in every dump; one
    naming a cosmetic thread, which the dump keeps no name for, or a hole instance the joint map
    numbers by its faces, `hol:0001#2`, though its hole is named, names none: lost, never
    another subject's."""
    thread = CosmeticThread(
        id="thr:0001",
        persist_ref=persist_ref("thr:0001"),
        persist_ref_scope=HOUSING.document_id,
        component_id="cmp:0001",
        face_id="fac:0001",
        designation="M6x1.0",
        depth=None,
        is_external=False,
    )
    entities = {"threads": [thread], "holes": [hole(1, "FICT Hole1")]}
    then, now = dumped_as(1, **entities), dumped_as(2, **entities)
    on_component = make_finding(package=then)
    on_document = make_finding(
        package=then,
        check="FICT.check.document",
        component_ids=[],
        document_ids=[HOUSING.document_id],
        inputs=["doc:123456789012"],
    )
    on_thread = make_finding(package=then, check="FICT.check.thread", inputs=["thr:0001"])
    on_instance = make_finding(package=then, check="FICT.check.joint", inputs=["hol:0001#2"])
    dumped(tmp_path, f"20260918-090000-{LABEL}", then, on_component, on_document, on_thread,
           on_instance)

    assert key(on_document)[3] == ("doc:123456789012",)
    assert dates(tmp_path, now) == {key(on_component): "2026-09-18", key(on_document): "2026-09-18"}


def test_a_name_two_entities_share_gives_no_date(tmp_path: Path) -> None:
    """A name is stable only while one entity of its kind holds it in its dump. Two display
    dimensions of one view under one name - a full name read back as the bare `Name`, say - leave
    neither a stable name, so a finding on either names no date across two dumps though the
    drawing is unchanged, where the dimension named once keeps its date."""
    names = ["FICT D1", "FICT D1", "FICT D2"]
    then = dumped_as(1, drawing_records=[drawing(dimensions=names)])
    now = dumped_as(2, drawing_records=[drawing(dimensions=names)])
    shared, alone = citing_entity("ddm", then, 1), citing_entity("ddm", then, 3)
    dumped(tmp_path, f"20260918-090000-{LABEL}", then, shared, alone)

    assert dates(tmp_path, now) == {key(alone): "2026-09-18"}


def test_a_record_of_this_reviews_own_dump_keeps_its_ids_as_they_are(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A record of the very dump this review reads - a Check again's earlier record in its folder,
    or a package copied whole - numbers it as this review does, so its ids are matched as they
    are, one the dump names no stable way among them, and its folder's package is not read."""
    on_thread = make_finding(check="FICT.check.thread", inputs=["thr:0001"])
    earlier(tmp_path, f"20260918-090000-{LABEL}", ON_ONE, on_thread)

    def unread(directory: Path | str) -> None:
        raise AssertionError(f"read {directory}")

    monkeypatch.setattr(first_shown, "load_package", unread, raising=False)

    assert dates(tmp_path) == {key(ON_ONE): "2026-09-18", key(on_thread): "2026-09-18"}


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


def started_as_named(folder: Path) -> None:
    """The record in `folder` started when the folder's name says, as a review the add-in named
    that day did, though this one ran today: a record dates its findings by its own clock (T392,
    the Tier 2 review's must-fix)."""
    path = folder / SESSION_FILE_NAME
    started = stamped(folder.name)
    assert started is not None
    session = load_session(path)
    session.started_at = started.astimezone(UTC)
    save_session(session, path)


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
    restore after a backend restart keep it.

    *Changed 2026-11-03 (T392, the Tier 2 review's must-fix):* the first record is given the start
    its folder's name says (`started_as_named`), since a record is now dated by its own clock."""
    pane_review(client, run_root / FIRST, tmp_package_dir)
    started_as_named(run_root / FIRST)
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
    did, two turns of them, and no request names the date.

    *Changed 2026-11-03 (T392, the Tier 2 review's must-fix):* the first record is given the start
    its folder's name says (`started_as_named`), since a record is now dated by its own clock."""
    first = recorded_review(app, client, run_root / FIRST, tmp_package_dir)
    started_as_named(run_root / FIRST)
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


def test_a_date_matched_by_name_adds_nothing_to_what_the_model_is_sent(
    app: Any, client: TestClient, run_root: Path, tmp_package_dir: Path, tmp_path: Path
) -> None:
    """Cycle 21 (roadmap hole H-d-009): a review of the design dumped again - another package id,
    so the first review's ids are matched by their stable names - names the first's date on each
    finding, and sends the model every request byte for byte as the same dump reviewed with no
    earlier review does, two turns of them, none naming the date. The review alone runs first,
    in a folder stamped after the others' starts, so neither counts it."""
    again, later = tmp_path / "dumped-again", run_root / f"20991231-090000-{LABEL}"
    save_package(PACKAGE.model_copy(update={"package_id": UUID(int=21)}), again)
    alone = recorded_review(app, client, later, again)
    recorded_review(app, client, run_root / FIRST, tmp_package_dir)
    started_as_named(run_root / FIRST)
    second = recorded_review(app, client, run_root / SECOND, again)

    bodies = finding_bodies(run_root / SECOND)
    assert bodies and [body.get("first_shown") for body in bodies] == [SHOWN] * len(bodies)
    assert all("first_shown" not in body for body in finding_bodies(later))
    assert len(alone) == len(second) == 2
    for one, two in zip(alone, second, strict=True):
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
    record, in the same folder, raised flagged name that folder's date; the others name none.

    *Changed 2026-11-03 (T392, the Tier 2 review's must-fix):* the earlier record is given the
    start its folder's name says (`started_as_named`), since a record is now dated by its own
    clock: the folder's date here."""
    folder = run_root / "20260918-090000-FICT-7000"
    held = recheck.earlier_review(app, client, folder)
    started_as_named(folder)
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
