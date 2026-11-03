"""When an earlier review of the same document first showed a finding (002 FR-031, cycle 17).

Owner decision 188A keeps a real finding SwReview first showed at an earlier sitting "new and
real", with that sitting's date in its note; roadmap hole H-a-009 found nothing showed which
findings an earlier review showed, so the date rested on recall. `first_shown_dates` reads it when
a review starts: for each subject key a flagged finding of an earlier review of this document held
(`findings.finding_subject_key`, the key Check again's carry matches a decision by, 015
`contracts/recheck.md` section 4), the date of the earliest such review. `ToolContext.finding_body`
names it on the `finding` event as `first_shown`; the snapshots and `report.md` read it back from
the stream (`report/snapshot.shown_dates`), so `Finding` gains no field and the model never reads
it.

The earlier reviews are the add-in's for a document (`RunFolders.FindNotSentReview`), named before
anything is opened: the run root's folders called `<yyyyMMdd-HHmmss>-<document name>`, with or
without a `-N` collision suffix, none a Model check's, a Standards check's or a re-modeler's. Then
each one's `session.json`, read once, must name this review's document. The review's own folder is
never read; a Check again's earlier record, which the re-run already holds, is passed in instead.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path

from swreview.findings import SubjectKey, finding_subject_key
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
    started unticked names (`model_status.document`) is this one by `PageDocument.IsSameDocument`,
    the path ignoring case and the configuration exactly. A review sent at once names no
    configuration; the subject key ends with the one each finding was raised in."""
    if record.design_id != package.design.design_id:
        return False
    status = record.model_status
    return status is None or (
        status.document["path"].casefold() == document["path"].casefold()
        and status.document["configuration"] == document["configuration"]
    )


def first_shown_dates(
    run_root: Path | str,
    run_dir: Path | str,
    package: EvidencePackage,
    *,
    before: datetime,
    earlier: ReviewSession | None = None,
) -> dict[SubjectKey, str]:
    """For each subject key a flagged finding of an earlier review of `package`'s document held,
    the date of the earliest such review, `YYYY-MM-DD`.

    The earlier reviews are the folders of `run_root` named for the document (`_stamp`) and
    stamped no later than `before`, this review's start in the same local wall clock, whose
    `session.json` is of the document (`_names`). Each is read once; one that cannot be read,
    is cut off or is no review is skipped, and so is a run root that cannot be listed, so the
    review is never failed over an earlier one. The review's own folder, `run_dir`, is not read:
    its record is `earlier`, a Check again's, or none. A date is the folder's stamp, the day the
    review in it started, so a Check again's earlier record is dated by the review it re-ran.

    A pass gives none (owner decision 187A), and a finding the record no longer holds - one its
    review withdrew - gives none: the record is what the review raised.
    """
    document = root_document(package)
    if document is None:
        return {}
    label = document_name(document["path"])
    root, own = Path(run_root).resolve(), Path(run_dir).resolve()
    try:
        names = [child.name for child in root.iterdir()]
    except OSError:
        return {}
    dates: dict[SubjectKey, str] = {}
    for name in names:
        stamp = _stamp(name, label)
        if stamp is None or stamp > before:
            continue
        folder = root / name
        record: ReviewSession | None = earlier
        if folder != own:
            try:
                record = load_session(folder / SESSION_FILE_NAME)
            except (OSError, ValueError):
                continue
        if record is None or not _names(record, package, document):
            continue
        day = stamp.date().isoformat()
        for finding in record.findings:
            if finding.status == SUPPRESSED_STATUS:
                continue
            key = finding_subject_key(finding)
            if key not in dates or day < dates[key]:
                dates[key] = day
    return dates
