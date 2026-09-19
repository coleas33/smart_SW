"""`attention.json`: the ranking a run was read with, written beside the session.

`report/attention.py` is the rule and stays pure. This module is the one place that puts a
`Ranking` on disk and reads it back, because the file answers a question the rule cannot:
**which order was this engineer actually shown?** A policy edited next month would rank the
same session differently, and the run folder has to keep saying what the run said
(`contracts/attention.md` section 4, FR-020).

Three properties the shape is chosen for:

- **reproducible from the session alone.** The record is the `Ranking` plus the id of the
  session it was computed from, and nothing else - no timestamp, no path, no fresh id - so
  `rank(load_session(...))` rebuilds it byte for byte. That is what makes it evidence
  rather than a cache, and it is why `GET /checks/{check_id}` recomputes in memory rather
  than refreshing the file (research R2.7);
- **stale when it names another session.** A review that claims an RMS check folder
  rotates the check's session aside; a record still naming that session describes a run
  the folder no longer holds. `read_attention_record` refuses it by name rather than
  answering with somebody else's ranking - the same rule `check.json` follows through
  `checks/rules/run.recorded_session`;
- **not a session file.** `ATTENTION_FILE_NAME` is deliberately absent from
  `chat/server.SESSION_FILES`, which is also the claim rule's truthiness test: a folder
  holding only a record must not read as "a folder that already holds a review".
  `ChatServer._rotate_previous` moves the record explicitly instead (FR-021).

`data-model.md` section 2 lists `AttentionRecord` among the types of `report/attention.py`.
It lives here instead, with the reader and the writer that give it its meaning, so that the
pure module keeps importing nothing that does I/O.
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from swreview.findings import ReviewModel
from swreview.report.attention import AttentionRow, CoverageBlock, NotAmplified, Ranking
from swreview.report.session import SESSION_FILE_NAME, load_session

__all__ = [
    "ATTENTION_FILE_NAME",
    "STALE_RECORD",
    "UNREADABLE_RECORD",
    "AttentionRecord",
    "StaleAttentionRecord",
    "read_attention_record",
    "write_attention_record",
]

ATTENTION_FILE_NAME = "attention.json"
"""The fourth file a run folder holds, beside `session.json`, `report.md` and `check.json`.

Owned here rather than in `report/rerender.py` with the other three, because that module
calls this one to write it and the reverse import would close a cycle. `rerender`
re-exports the name for the callers that already import their file names from it.
"""

STALE_RECORD = (
    "{path} was computed from session {recorded}, but {directory} now holds session "
    "{found}; the record is stale and re-ranking that session is what refreshes it"
)

UNREADABLE_RECORD = "{path} cannot be read as an attention record ({error})"


class AttentionRecord(ReviewModel):
    """`attention.json`: one `Ranking`, and the session it describes.

    The field order is the contract's, and `session_id` is second on purpose: the file is
    read by a person arguing about a placement, and the second line has to tell them which
    run they are looking at before they read a single row.
    """

    policy_version: str
    session_id: UUID
    rows: list[AttentionRow]
    top_n: int
    not_amplified: NotAmplified
    coverage: CoverageBlock
    empty_reason: str | None

    @classmethod
    def of(cls, ranking: Ranking, session_id: UUID) -> AttentionRecord:
        """The record for `ranking`, computed from the session `session_id` names.

        Spelled out field by field rather than by unpacking the ranking, so that a field
        added to `Ranking` for a surface that is not the record - the check bodies carry
        the same block - is a decision taken here rather than one that leaks into every
        run folder on the next release.
        """
        return cls(
            policy_version=ranking.policy_version,
            session_id=session_id,
            rows=ranking.rows,
            top_n=ranking.top_n,
            not_amplified=ranking.not_amplified,
            coverage=ranking.coverage,
            empty_reason=ranking.empty_reason,
        )


class StaleAttentionRecord(ValueError):
    """The record names a session that is not the one in the folder beside it."""


def write_attention_record(directory: Path | str, ranking: Ranking, session_id: UUID) -> Path:
    """Write `<directory>/attention.json` from `ranking` and return the file.

    Called from the same place, and with the same `Ranking` object, as the render of
    `report.md`: a record computed from a second `rank()` call would be reproducible and
    still not be the order the report printed, which is the one thing the record is for.

    `indent=2` and a trailing newline, as `save_session` writes `session.json`, so the two
    files beside each other read the same way in an editor and in a diff.
    """
    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)
    record_file = target / ATTENTION_FILE_NAME
    record = AttentionRecord.of(ranking, session_id)
    record_file.write_text(record.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return record_file


def read_attention_record(directory: Path | str) -> AttentionRecord:
    """The record `directory` holds, checked against the session beside it.

    Raises:
        OSError: the folder holds no `attention.json`, or no `session.json` to check it
            against - staleness is a comparison, and a record with nothing to compare
            against must not pass by default.
        ValueError: the record is not JSON, or not this build's shape.
        StaleAttentionRecord: the record names a session other than the folder's, so it
            describes a run this folder no longer holds.
    """
    folder = Path(directory)
    record_file = folder / ATTENTION_FILE_NAME
    text = record_file.read_text(encoding="utf-8")
    try:
        record = AttentionRecord.model_validate_json(text)
    except ValueError as exc:
        raise ValueError(UNREADABLE_RECORD.format(path=record_file, error=exc)) from exc

    session = load_session(folder / SESSION_FILE_NAME)
    if record.session_id != session.session_id:
        raise StaleAttentionRecord(
            STALE_RECORD.format(
                path=record_file,
                directory=folder,
                recorded=record.session_id,
                found=session.session_id,
            )
        )
    return record
