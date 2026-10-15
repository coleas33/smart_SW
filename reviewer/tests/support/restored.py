"""What `GET /reviews/{run_id}` answers for a record that waits for Send (feature 015 T099).

`contracts/recheck.md` section 8; owner decisions 68A and 73A. A `not_sent` or `send_failed`
record is restored read-only, as every record is, with two differences: its
`read_only_reason` is the words file's `read_only_lead`, a space, and `send.restored_line`
dated with the stored `checked_at` wall clock - never feature 009's second sentence,
`read_only_off` - and its summary carries the `restored` Send block, which holds no
`session_id` and no restored line.

The expected wall clock is derived here from `isoformat`, not from the `strftime` the
backend uses, so the oracle is not the implementation read back. Every test that restores
a waiting folder - the folders a failed or cut-off re-run left, an apply's crash copy and a
Send's pre-usage copy among them - asserts through this one function.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from swreview.report.session import ReviewSession
from swreview.report.summary import load_words

SEND_BLOCK_KEYS = ["state", "input_tokens", "approximate", "text", "failure", "rerun_failed_text"]


def stored_wall_clock(at: datetime) -> str:
    """`YYYY-MM-DD HH:MM` of the time as stored, its offset kept and never converted."""
    return at.isoformat(sep=" ", timespec="minutes")[:16]


def restored_reason(record: ReviewSession) -> str:
    """The composed line: 009's first sentence, a space, and the dated Send sentence."""
    words = load_words()
    assert record.model_status is not None
    when = stored_wall_clock(record.model_status.checked_at)
    return f"{words.read_only_lead} {words.send.restored_line.format(when=when)}"


def restored_failure(record: ReviewSession) -> str | None:
    """The failure line of a `send_failed` record's last recorded request, else none."""
    status = record.model_status
    assert status is not None
    if status.state != "send_failed" or not status.failures:
        return None
    last = status.failures[-1]
    return load_words().send.failed.format(
        reason=last.reason, time=stored_wall_clock(last.at)[-5:]
    )


def assert_restored_as_waiting(body: dict[str, Any], record: ReviewSession) -> None:
    """`body`, a `GET /reviews` answer, restores `record` read-only with Send offered."""
    words = load_words()
    status = record.model_status
    assert status is not None and status.state in ("not_sent", "send_failed"), status
    assert body["read_only"] is True
    assert (body["chat_state"], body["last_seq"]) == (None, None)
    reason = body["read_only_reason"]
    assert reason == restored_reason(record)
    assert reason.startswith(words.read_only_lead + " ")
    assert words.read_only_off not in reason
    assert reason != words.read_only
    send = body["ranking"]["summary"]["send"]
    assert list(send) == SEND_BLOCK_KEYS, "no session_id and no restored line (68A, 73A)"
    provider = record.provider_info.provider if record.provider_info else ""
    assert send == {
        "state": "restored",
        "input_tokens": None,
        "approximate": provider == "gemini",
        "text": words.send.restored,
        "failure": restored_failure(record),
        "rerun_failed_text": words.send.rerun_failed,
    }
    assert [finding["id"] for finding in body["findings"]] == [f.id for f in record.findings]
    assert body["evidence_requests"] == [item.pane_body() for item in record.evidence_requests]
