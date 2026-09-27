"""The answer basis: one line, computed by code, before every model answer (feature 013 US5).

The sitting's follow-up turn called no tool, yet its answer read as a drawing review (013 research
R2.30). A page cannot tell an answer grounded in results from general guidance, and the model's
text is never parsed, so the backend says which it was, from the steps the turn recorded:
`answer_basis(steps, package, words)` counts the results the answer's turn read and says whether
the review read any drawing (013 `contracts/sources.md` section 3). The runner wraps the provider's
events so every `text.done` carries the line as `basis`; the page prints it after the "AI
guidance" chip, before the answer.

**A read is a result the model could reason from**: a step whose status is `ok` and whose tool is
not a writer or bookkeeping tool of `session_tools()` - asking the engineer, marking coverage,
recording a drawing finding or reading the checklist hand the model no evidence.

Pure: it reads its arguments, imports no provider and no settings, and writes nothing; the step
and words types are type-checking imports only (`report/session.py` pulls the provider port in).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from swreview.ir.models import EvidencePackage
from swreview.report.summary import drawings_of

if TYPE_CHECKING:  # pragma: no cover - imported for annotations only, never at run time
    from swreview.report.session import InvestigationStep
    from swreview.report.summary import Words

__all__ = ["READ_EXCLUDED", "answer_basis", "reads_of"]

READ_EXCLUDED: frozenset[str] = frozenset(
    {"request_evidence", "mark_coverage", "record_drawing_finding", "get_review_checklist"}
)
"""The writers and bookkeeping tools of `tools/registry.session_tools()`: steps that read no
evidence, however many a turn makes. `tests/unit/test_answer_basis.py` asserts the set is the
registry's own session tools."""


def reads_of(steps: Sequence[InvestigationStep]) -> int:
    """How many of `steps` read a result: status `ok`, and a tool outside `READ_EXCLUDED`."""
    return sum(1 for step in steps if step.status == "ok" and step.tool not in READ_EXCLUDED)


def answer_basis(
    steps: Sequence[InvestigationStep], package: EvidencePackage | None, words: Words
) -> str:
    """The basis line of one answer: how many results its turn read, and - when the review read
    no drawing at all - that no drawing was read (013 `contracts/sources.md` section 3).

    `steps` are the turn's own steps (the runner's marker picks them), `package` the review's
    package, whose drawings read are the summary's drawings line's; with no package, no drawing
    was read.
    """
    basis = words.answer_basis
    reads = reads_of(steps)
    if reads == 0:
        line = basis.none
    else:
        line = basis.one if reads == 1 else basis.many.format(n=reads)
    drawings = drawings_of(package)
    if drawings is None or not drawings.read:
        line += basis.no_drawing
    return line
