"""When an earlier review of the same document first showed a finding (002 FR-031, cycle 17).

Owner decision 188A keeps a real finding SwReview first showed at an earlier sitting "new and
real", with that sitting's date in its note; roadmap hole H-a-009 found nothing showed which
findings an earlier review showed, so the date rested on recall. `first_shown_dates` reads it when
a review starts: for each subject key a flagged finding of an earlier review of this document held
(`findings.finding_subject_key`, the key Check again's carry matches a decision by, 015
`contracts/recheck.md` section 4), the earliest day such a review showed one.
`ToolContext.finding_body` names it on the `finding` event as `first_shown`; the snapshots and
`report.md` read it back from the stream (`report/snapshot.shown_dates`), so `Finding` gains no
field and the model never reads it.

The earlier reviews are the add-in's for a document (`RunFolders.FindNotSentReview`), named before
anything is opened: the run root's folders called `<yyyyMMdd-HHmmss>-<document name>`, with or
without a `-N` collision suffix, none a Model check's, a Standards check's or a re-modeler's, read
oldest first. Then each one's records - its `session.json` and those a Retry or a re-run moved
aside beside it - each read once, must name this review's document, and each is dated by its own
clock (`_day`), since a folder can hold findings shown on several days. The review's own
`session.json` is never read; a Check again's earlier record, which the re-run already holds, is
passed in instead.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from time import monotonic

from swreview.checks.provenance import PROVENANCE_CHECK
from swreview.findings import Finding, SubjectKey, finding_subject_key
from swreview.ir.models import EvidencePackage
from swreview.report.attention import SUPPRESSED_STATUS
from swreview.report.session import SESSION_FILE_NAME, ReviewSession, load_session
from swreview.report.snapshot import root_document

__all__ = ["document_name", "first_shown_dates"]

STAMP = re.compile(r"[0-9]{8}-[0-9]{6}")
"""The stamp a run folder's name begins with: `RunFolders.TimestampFormat`, `yyyyMMdd-HHmmss`, the
add-in's local wall clock when the run started (`RunFolders.Create`)."""

STAMP_FORMAT = "%Y%m%d-%H%M%S"

OTHER_RUNS = ("-check", "-standards", "-remodel")
"""The suffixes of the folders that hold no review: `RunFolders.CheckSuffix`, `StandardsSuffix` and
`RemodelSuffix`."""

NAME_LENGTH = 48
"""`RunFolders.MaxNameLength`: how much of a document's name its folders spend."""

REFUSED = frozenset('"<>|:*?\\/') | frozenset(chr(code) for code in range(32))
"""`Path.GetInvalidFileNameChars()` on Windows, each of which `RunFolders.DocumentName` makes a
dash."""

MOVED_ASIDE = re.compile(r"session\.[0-9]+\.json")
"""A record a Retry or a re-run moved aside in its folder, `session.<n>.json`
(`ChatServer._rotate_previous` and `_rotate_kept`): an attempt the Retry replaced, or the waiting
record a re-run - Send after a restart, or Check again - replaced."""

SET_UP = f"{PROVENANCE_CHECK}."
"""What the checks of the set-up records begin with, the findings code writes before any step
(`benchmark/origins.SETUP_CHECK_PREFIXES`)."""

READ_BUDGET_S = 2.0
"""How long the match may spend opening the other reviews' records, so a review's start, which
also runs the checks first inside the add-in's 30 s call, never waits on them longer however many
reviews of the document the seat keeps. The review's own folder is read whatever the time: a
re-run's earlier record is already held, and the few records its folder moved aside are this
review's own. The folders are read oldest first, so a finding only a review past the budget showed
names no date; but each record is dated by its own clock, so one read within the budget can name a
later day than a review past it showed - a review sent after a restart days after its folder was
named, say. The match took about 10 ms a record of the big-assembly replay fixture (002
research.md, cycle 17)."""


def document_name(path: str) -> str:
    """`RunFolders.DocumentName`: what a review folder of the document at `path` is called after its
    stamp - its file name without the extension, each character Windows refuses in a file name a
    dash, spaces, periods and dashes trimmed from both ends, cut to 48 and trimmed again, and
    `document` when nothing is left."""
    name = path[max(path.rfind("\\"), path.rfind("/")) + 1 :]
    dot = name.rfind(".")
    if dot >= 0:
        name = name[:dot]
    name = "".join("-" if character in REFUSED else character for character in name)
    name = name.strip(" .-")
    if len(name) > NAME_LENGTH:
        name = name[:NAME_LENGTH].strip(" .-")
    return name or "document"


def _carries(name: str, suffix: str) -> bool:
    """`RunFolders.CarriesSuffix`: `name` ends with `suffix`, or does before a collision suffix."""
    folded = name.casefold()
    head, dash, tail = folded.rpartition("-")
    return folded.endswith(suffix) or (bool(dash) and tail.isdecimal() and head.endswith(suffix))


def _stamp(name: str, label: str) -> datetime | None:
    """The stamp of `name` when it names a review folder of the document `label` names, by
    `FindNotSentReview`'s rule - the stamp, then `-<label>` ignoring case, then nothing or a
    collision suffix - or `None`."""
    if not STAMP.match(name) or any(_carries(name, suffix) for suffix in OTHER_RUNS):
        return None
    stem = f"{name[:15]}-{label}"
    rest = name[len(stem) :]
    if name[: len(stem)].casefold() != stem.casefold() or (
        rest and not (rest[0] == "-" and rest[1:].isdecimal())
    ):
        return None
    try:
        return datetime.strptime(name[:15], STAMP_FORMAT)
    except ValueError:
        return None


def _names(record: ReviewSession, package: EvidencePackage, document: Mapping[str, str]) -> bool:
    """Whether `record` is of this review's document: its design is this one's - the root
    document's path ignoring case, as the extractor names a design - and the document a review
    started unticked names (`model_status.document`) has this one's path, ignoring case, as
    `PageDocument.IsSameDocument` compares paths. The configuration is each finding's own, the
    last part of its subject key, however the earlier review was started: a review sent at once
    names none."""
    if record.design_id != package.design.design_id:
        return False
    status = record.model_status
    return status is None or status.document["path"].casefold() == document["path"].casefold()


def _records(folder: Path, *, own: bool) -> list[ReviewSession]:
    """The records of `folder` that can be read: its `session.json`, unless it is the review's own
    folder (`own`), and those a Retry or a re-run moved aside beside it (`MOVED_ASIDE`). One that
    cannot be read, is cut off or is no review is skipped, so the review is never failed over it."""
    try:
        paths = sorted(path for path in folder.iterdir() if MOVED_ASIDE.fullmatch(path.name))
    except OSError:
        paths = []
    if not own:
        paths.insert(0, folder / SESSION_FILE_NAME)
    records: list[ReviewSession] = []
    for path in paths:
        try:
            records.append(load_session(path))
        except (OSError, ValueError):
            continue
    return records


def _before_any_turn(finding: Finding, prerun: set[int]) -> bool:
    """Whether the checks raised `finding` before any turn of the model: carried from an earlier
    run, the pre-run's - the highest step it cites marked `prerun` - or a set-up record, which
    cites none. `benchmark/origins.finding_origin` reads these three origins, `carried`, `prerun`
    and `setup`, the same way; it is not imported, since its imports reach the runner, which
    imports this module."""
    if finding.carried_over_from is not None:
        return True
    if finding.tool_result_ids:
        return max(finding.tool_result_ids) in prerun
    return finding.check.startswith(SET_UP)


def _day(finding: Finding, record: ReviewSession, prerun: set[int]) -> str:
    """The day `record`'s review showed `finding`, `YYYY-MM-DD` in this machine's local clock, the
    clock the add-in names folders by: the day the review started, or, for a finding a turn raised
    after a review started unticked was sent (`model_status.sent_at`), the day it was sent. A
    record's own clock and not its folder's name, since Send - live, or after a restart, whose
    re-run replaces the folder's `session.json` - can come days after the folder was named. A
    re-grade from an answer given while the review waited (`regrade`) takes the Send's day too,
    though it was shown before the Send: the record names no step's time."""
    status = record.model_status
    sent = status.sent_at if status is not None else None
    shown = record.started_at if sent is None or _before_any_turn(finding, prerun) else sent
    return shown.astimezone().date().isoformat()


def _same_parts(finding: Finding, parts: Mapping[str, str]) -> bool:
    """Whether each component `finding` names is, in this review's package (`parts`, component id
    to document id), an instance of a document the finding drew on (its `provenance`). A
    component's id is its place in each dump's numbering, so after an edit to the tree an earlier
    finding of another part can hold this review's number for a part; it gives no date. A finding
    naming no component, a component renumbered onto another instance of the same document, or an
    entity renumbered within one document, is not told apart."""
    drew_on = {entry.document_id for entry in finding.provenance}
    return all(parts.get(component) in drew_on for component in finding.component_ids)


def first_shown_dates(
    run_root: Path | str,
    run_dir: Path | str,
    package: EvidencePackage,
    *,
    before: datetime,
    earlier: ReviewSession | None = None,
) -> dict[SubjectKey, str]:
    """For each subject key a flagged finding of an earlier review of `package`'s document held,
    the earliest day such a review showed one, `YYYY-MM-DD`.

    The earlier reviews are the folders of `run_root` named for the document (`_stamp`) and
    stamped no later than `before`, this review's start in the same local wall clock, read oldest
    first until `READ_BUDGET_S` is spent; their records (`_records`) that are of the document
    (`_names`). Each is read once; one that cannot be read, is cut off or is no review is skipped,
    and so is a run root that cannot be listed, so the review is never failed over an earlier one.
    In the review's own folder, `run_dir`, read whatever the time, the record is `earlier`, a
    Check again's, beside the records the folder moved aside; with none, a first review's or a
    Retry's, nothing there is read. Each record is dated by its own clock (`_day`).

    A pass gives none (owner decision 187A), and a finding the record no longer holds - one its
    review withdrew - gives none: the record is what the review raised. Nor does a finding on a
    part another part's number now names (`_same_parts`).
    """
    document = root_document(package)
    if document is None:
        return {}
    label = document_name(document["path"])
    parts = {component.id: component.document_id for component in package.components}
    root, own = Path(run_root).resolve(), Path(run_dir).resolve()
    try:
        names = sorted(child.name for child in root.iterdir())
    except OSError:
        return {}
    started = monotonic()
    dates: dict[SubjectKey, str] = {}
    for name in names:
        stamp = _stamp(name, label)
        if stamp is None or stamp > before:
            continue
        folder = root / name
        if folder == own:
            if earlier is None:
                continue
            records = [earlier, *_records(folder, own=True)]
        elif monotonic() - started > READ_BUDGET_S:
            continue
        else:
            records = _records(folder, own=False)
        for record in records:
            if not _names(record, package, document):
                continue
            prerun = {step.index for step in record.steps if step.origin_mark == "prerun"}
            for finding in record.findings:
                if finding.status == SUPPRESSED_STATUS or not _same_parts(finding, parts):
                    continue
                key = finding_subject_key(finding)
                day = _day(finding, record, prerun)
                if key not in dates or day < dates[key]:
                    dates[key] = day
    return dates
