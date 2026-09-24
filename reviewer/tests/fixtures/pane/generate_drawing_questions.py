"""Write the Review tab's drawing-questions fixture from a scripted backend review (feature 011).

Run from `reviewer/` and commit what it writes:

    uv run python tests/fixtures/pane/generate_drawing_questions.py --write

It plays one review of a fictional package built here by code - an assembly whose plate is
shown by two open drawings, whose long-named part is shown by five, and whose three blocks
each have a same-name drawing beside them and not open - through the real runner, the real
`check_drawings`, the real session writer and the real `BridgeClient`. The one thing played
is the add-in on the far end of the pipe: `HostLines` answers each `drawing.read` line with a
line of the host's own shape (`extractor/SwReview.Extractor/Bridge/BridgeDispatcher.cs`,
`ConfirmedDrawingResult`, and a refusal's `error`), so the first block is read and closed, the
second is refused with the host's not-validated sentence (`Sw/DrawingOpenScope.cs`) and the
third was already open. The host's merge into the run folder is not played: the package is
reloaded as it stands, so the drawing check the runner restates after a read (one recorded step
before the resumed turn) repeats the first turn's `drawing.context` reasons.

It writes, to `extractor/SwReview.AddIn.Tests/Fixtures/review-drawing-questions.json`:

- `questions_asked`: the summary's `questions` block after the first turn, as the attention
  route answers it (`report/summary.review_ranking`): the candidate question, the plate's
  governing question with its offered file names, and the long-named part's governing question
  with its stem shortened and no offered answers;
- `summary_drawings`: the summary's `drawings` block after the first turn (decision 10A): the
  seven drawings read and the three same-name drawings found but not open, and the one line the
  page prints - the drawing line of the add-in tests' `SummarySample` (feature 011 T090, T091);
- `answers`: the batch the engineer sends - the candidate question confirmed with
  `CANDIDATE_CONFIRM` and the plate's question answered `They all apply` - each the offered
  words exactly;
- `coverage_events`: every `coverage` and `coverage.withdrawn` event of the review, each its
  `type` and `body`, in the order the backend emitted them, both turns - the confirmed opens,
  then the drawing check's withdrawal of its items and its restated items (feature 011 T092);
- `questions_open_after`: the summary's `questions` block after the resumed turn.

`extractor/SwReview.AddIn.Tests/ReviewPageDrawingQuestionsTests.cs` loads it, so the page is
tested against what the backend produces (research R2.24), and
`tests/unit/test_pane_drawing_fixture.py` fails when the committed file differs from a fresh
generation; the fix is this command, never a hand edit. Every string is fictional (feature
011's drawing vocabulary, `tests/support/drawings.py`).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

FIXTURE_ROOT = Path(__file__).resolve().parent
REVIEWER = FIXTURE_ROOT.parents[2]
sys.path.insert(0, str(REVIEWER))

from tests.support.drawings import DrawingBuilder  # noqa: E402
from tests.support.mechanical import PackageBuilder  # noqa: E402

from swreview.agent.providers.fake import FakeProvider, ScriptedToolCall, ScriptedTurn  # noqa: E402
from swreview.agent.runner import start_review  # noqa: E402
from swreview.bridge.client import BridgeClient  # noqa: E402
from swreview.checks.drawing_context import ALL_APPLY, CANDIDATE_CONFIRM  # noqa: E402
from swreview.ir.loader import save_package  # noqa: E402
from swreview.ir.models import DrawingCandidate, EvidencePackage  # noqa: E402
from swreview.report.summary import review_ranking  # noqa: E402

COVERAGE_EVENT_TYPES = ("coverage", "coverage.withdrawn")
"""The two events the page's coverage panel is built from (002 `chat-events.schema.json`)."""

TARGET = (
    REVIEWER.parent
    / "extractor"
    / "SwReview.AddIn.Tests"
    / "Fixtures"
    / "review-drawing-questions.json"
)
WRITE_COMMAND = "uv run python tests/fixtures/pane/generate_drawing_questions.py --write"
RUN_ID = "fict-drawing-review"
"""The run folder's name, which `drawing.read` carries as its `run_id`."""

PLATE = "FICT-TULMKALO-7001"
PLATE_DRAWINGS = (PLATE, f"{PLATE}-B")
"""Two open drawings of the plate: a governing question that offers both by file name."""
LONG_PART = (
    "FICT-OKTAKALO-7002-TESSABRUN-DAVORUSK-LORIVENTA-QUILLSORN-HASKFENN-ARVOTULM-ZEPHOMBRA-"
    "NIXAKALO-MIRVEN-OKTAPELIN"
)
"""A stem longer than a five-drawing governing question has room for, so the backend shortens it."""
LONG_PART_DRAWINGS = tuple(f"FICT-OKTAKALO-7002-{letter}" for letter in "ABCDE")
"""More drawings than a question offers buttons for (`MAX_OPTIONS` less "They all apply")."""
BLOCKS = ("FICT-TULMSORN-7003", "FICT-TULMSORN-7004", "FICT-TULMSORN-7005")
"""Three blocks, each with a same-name drawing beside it and not open: the candidates."""

NOT_VALIDATED = (
    "the read-only open of a confirmed drawing is not yet validated on a seat (feature 011 "
    "probe D14)"
)
"""`DrawingOpenScope`'s refusal while `SeatValidated` is false (`contracts/confirmed-open.md`
section 4), word for word; the test finds it in the C# source."""


def drawing_review_package() -> EvidencePackage:
    """The fictional assembly the review is of (see the module docstring)."""
    base = PackageBuilder(design_stem="FICT-OKTAVEN-7000", schema_version="1.6.0")
    plate = base.document(PLATE, "part")
    long_part = base.document(LONG_PART, "part")
    blocks = [base.document(stem, "part") for stem in BLOCKS]
    for document in (plate, long_part, *blocks):
        base.component(document)
    builder = DrawingBuilder(base.build().package)
    shown_by = [(stem, plate) for stem in PLATE_DRAWINGS]
    shown_by += [(stem, long_part) for stem in LONG_PART_DRAWINGS]
    for stem, shown in shown_by:
        record = builder.drawing(builder.drawing_document(stem))
        builder.view(builder.sheet(record, "Sheet1"), "Drawing View1", references=shown)
    for block in blocks:
        builder.candidate(block)
    return builder.build()


def host_document_id(path: str) -> str:
    """The `doc:` id the host gives a drawing it reads: `DocumentIds.For(path)`, the first 12
    hex digits of SHA-1 over the lower-cased, backslash-separated path."""
    normalized = path.strip().replace("/", "\\").lower()
    return "doc:" + hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:12]


def host_answers(package: EvidencePackage) -> dict[str, tuple[str, Any]]:
    """`{document id: (status, result or error)}`: what the add-in answers for each candidate,
    in the candidates' order - read and closed, refused while the seam is off, already open."""
    first, second, third = package.drawing_candidates

    def read(candidate: DrawingCandidate, opened: bool, sheets: int) -> tuple[str, Any]:
        return "ok", {
            "document_id": candidate.document_id,
            "drawing_document_id": host_document_id(candidate.path),
            "opened": opened,
            "closed": opened,
            "sheets": sheets,
            "gaps": 0,
        }

    return {
        first.document_id: read(first, opened=True, sheets=1),
        second.document_id: ("error", NOT_VALIDATED),
        third.document_id: read(third, opened=False, sheets=2),
    }


class HostLines:
    """The add-in on the far end of the pipe: one `drawing.read` answer line per request line."""

    def __init__(self, answers: Mapping[str, tuple[str, Any]]) -> None:
        self.answers = dict(answers)
        self.requests: list[dict[str, Any]] = []

    def request(self, line: str) -> str:
        request = json.loads(line)
        self.requests.append(request)
        if request["command"] != "drawing.read":
            raise AssertionError(f"the scripted host answers drawing.read only, not {line}")
        status, body = self.answers[request["params"]["document_id"]]
        reply: dict[str, Any] = {"id": request["id"], "status": status}
        reply["result" if status == "ok" else "error"] = body
        return json.dumps(reply)

    def close(self) -> None:
        pass


def summary_block(run: Any, block: str) -> Any:
    """One block of the summary - `questions` or `drawings` - as the attention route answers it
    right now."""
    return review_ranking(run.session, run.context.ir).summary.model_dump(mode="json")[block]


def drawing_questions_fixture() -> dict[str, Any]:
    """Play the review and return what the page is given (see the module docstring)."""
    package = drawing_review_package()
    host = HostLines(host_answers(package))
    events: list[tuple[str, dict[str, Any]]] = []
    with tempfile.TemporaryDirectory() as temporary:
        folder = Path(temporary) / RUN_ID
        save_package(package, folder)
        run = start_review(
            folder,
            folder,
            provider=FakeProvider(
                script=[
                    ScriptedTurn(text="asked", tool_calls=(ScriptedToolCall("check_drawings"),)),
                    ScriptedTurn(text="resumed"),
                ],
                model="fake-scripted",
            ),
            callbacks=[lambda event: events.append((event.type, dict(event.body)))],
            bridge=True,
            bridge_factory=lambda pipe, secret: BridgeClient(pipe, secret, transport=host),
        )
        run.start()
        asked = summary_block(run, "questions")
        drawings = summary_block(run, "drawings")
        candidate, plate, _ = asked["items"]
        answers = [[candidate["id"], CANDIDATE_CONFIRM], [plate["id"], ALL_APPLY]]
        run.answer_evidence_batch([(request_id, answer) for request_id, answer in answers])
        after = summary_block(run, "questions")
    return {
        "run_id": RUN_ID,
        "questions_asked": asked,
        "summary_drawings": drawings,
        "answers": answers,
        "coverage_events": [
            {"type": kind, "body": body} for kind, body in events if kind in COVERAGE_EVENT_TYPES
        ],
        "questions_open_after": after,
    }


def render(fixture: dict[str, Any]) -> str:
    """The file's text: indented, key order kept, non-ASCII kept as written."""
    return json.dumps(fixture, indent=2, ensure_ascii=False) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--write", action="store_true", help=f"write {TARGET.name}")
    options = parser.parse_args(argv)
    if not options.write:
        print(f"usage: {WRITE_COMMAND}", file=sys.stderr)
        return 2
    TARGET.write_text(render(drawing_questions_fixture()), encoding="utf-8")
    print(f"wrote {TARGET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
