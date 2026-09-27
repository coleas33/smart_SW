"""The one shape of a question code asks, and the one test that it is already asked (013 T005).

Two checks ask the engineer something: feature 011's drawing check (the candidate and governing
questions) and feature 013's part-roles question (`contracts/part-roles.md` section 8). Both are
specified as a `QuestionSpec` before anything is written, and both go through the one writer,
`tools/session.record_evidence_request`, so the pane's panel and feature 008's batch route serve
them alike (research R3 C10).

`already_asked` is the duplicate test for **code** questions, moved here unchanged from
`tools/drawings.py`: an exact match on the question, the `what` and the entity ids in order. It
stays exact because a code question can trigger an action - an answered candidate question opens
a drawing (`tools/drawings._is_confirmed_candidate`) - so a question that differs in any of them
is a different question. The model's questions are guarded by a looser rule, the subset rule of
`report/session.covering_requests` (`contracts/re-ask-guard.md` section 3), which never reads
code questions.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from swreview.report.session import EvidenceRequest

__all__ = ["QuestionSpec", "already_asked"]


@dataclass(frozen=True)
class QuestionSpec:
    """One question a check writes through `tools/session.record_evidence_request`."""

    key: str
    """What the question is about, for its asker: `candidates`, `governing:<document id>`, or
    the part-roles question's key."""
    what: str
    why: str
    entity_ids: tuple[str, ...]
    question: str
    options: tuple[str, ...]
    blocks: str | None
    allow_text: bool = False
    """Whether the pane offers a text box beside the options (`EvidenceRequest.allow_text`):
    true for the part-roles question only, whose answer may name the bought parts."""


def already_asked(requests: Iterable[EvidenceRequest], spec: QuestionSpec) -> bool:
    """Whether a request on the session already asks exactly `spec`, answered or not."""
    return any(
        request.question == spec.question
        and request.what == spec.what
        and tuple(request.entity_ids) == spec.entity_ids
        for request in requests
    )
