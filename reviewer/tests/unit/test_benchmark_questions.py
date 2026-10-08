"""The questions reader's tests (feature 014, `contracts/questions.md` section 9).

This half holds the product-side bullets (T073; plan decisions RF-6, QA-11, QA-13): the two
product rules the eval's one matcher is built on, made callable without moving anything the
model reads.

- `report.session.covers` is the covering test `covering_requests` wrote inline (`questions.md`
  3): tested here on its four cases, and a spy shows the guard asking it once per model-written
  request. The guard's own tests (`test_tools_session.py`, `test_questions.py`) pass unchanged
  after the extraction.
- `tools.session.documents_named` is the drawing guard's document rule made public
  (`questions.md` 2): a document names itself, a component instance its document, a hole and a
  fastener their component's document, and any other id nothing, first-named first.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from swreview.findings import Source
from swreview.ir.models import EvidencePackage
from swreview.report import session as report_session
from swreview.report.session import EvidenceRequest, ReviewSession
from swreview.tools import session as tools_session
from swreview.tools.context import context_for, new_session
from tests.support.packages import build_package

FIT = "interfaces.fit"
FASTENERS = "fasteners"


def ids(*values: str) -> frozenset[str]:
    return frozenset(values)


# --- covers: the product's covering test, extracted (questions.md 3; RF-6) -----------------------


@pytest.mark.parametrize(
    ("later", "earlier", "covered"),
    [
        (ids("cmp:0002"), ids("cmp:0002", "hol:0001"), True),
        (ids("hol:0001", "cmp:0002"), ids("cmp:0002", "hol:0001"), True),
        (ids("cmp:0002", "hol:0001"), ids("cmp:0002"), False),
        (ids("cmp:0002", "hol:0001"), ids("cmp:0002", "cmp:0003"), False),
    ],
    ids=["subset", "same-ids", "superset", "partial-overlap"],
)
def test_an_item_and_ids_are_covered_by_an_earlier_question_holding_the_ids_on_that_item(
    later: frozenset[str], earlier: frozenset[str], covered: bool
) -> None:
    assert report_session.covers(FIT, later, FIT, earlier) is covered


def test_an_item_and_ids_are_not_covered_under_another_item() -> None:
    assert report_session.covers(FIT, ids("cmp:0002"), FASTENERS, ids("cmp:0002")) is False
    assert report_session.covers(FIT, ids("cmp:0002"), None, ids("cmp:0002")) is False


def test_an_item_alone_is_covered_only_by_an_earlier_question_on_it_naming_no_ids() -> None:
    assert report_session.covers(FIT, ids(), FIT, ids()) is True
    assert report_session.covers(FIT, ids(), FIT, ids("cmp:0002")) is False
    assert report_session.covers(FIT, ids(), FASTENERS, ids()) is False


def test_no_item_and_no_ids_is_covered_by_nothing() -> None:
    """`report/session.py:201-202`: nothing says two such questions are the same one."""
    assert report_session.covers(None, ids(), None, ids()) is False
    assert report_session.covers(None, ids(), None, ids("cmp:0002")) is False
    assert report_session.covers(None, ids(), FIT, ids()) is False


def test_a_null_item_with_ids_is_covered_by_a_null_item_question_holding_them() -> None:
    """`null` equals `null`, and only `null` (research R2.22's pinned case)."""
    assert report_session.covers(None, ids("cmp:0002"), None, ids("cmp:0002", "cmp:0003")) is True
    assert report_session.covers(None, ids("cmp:0002", "cmp:0003"), None, ids("cmp:0002")) is False
    assert report_session.covers(None, ids("cmp:0002"), FIT, ids("cmp:0002")) is False


def request(
    request_id: str,
    blocks: str | None,
    entity_ids: list[str],
    *,
    source: Source = "model",
    answered: bool = False,
) -> EvidenceRequest:
    return EvidenceRequest(
        id=request_id,
        what=f"The value {request_id} asks for",
        why="A check cannot be graded without it.",
        entity_ids=entity_ids,
        status="answered" if answered else "open",
        answer="press fit" if answered else None,
        answered_at=datetime(2026, 9, 26, 10, 0, tzinfo=UTC) if answered else None,
        blocks=blocks,
        source=source,
    )


def session_with(*requests: EvidenceRequest) -> ReviewSession:
    session = new_session(build_package())
    session.evidence_requests.extend(requests)
    return session


def spy_on_covers(
    monkeypatch: pytest.MonkeyPatch,
) -> list[tuple[str | None, frozenset[str], str | None, frozenset[str]]]:
    """Every call `covering_requests` makes to `covers`, answered by the real one."""
    asked: list[tuple[str | None, frozenset[str], str | None, frozenset[str]]] = []
    real = report_session.covers

    def spy(
        blocks: str | None,
        ids: frozenset[str],
        earlier_blocks: str | None,
        earlier_ids: frozenset[str],
    ) -> bool:
        asked.append((blocks, ids, earlier_blocks, earlier_ids))
        return real(blocks, ids, earlier_blocks, earlier_ids)

    monkeypatch.setattr(report_session, "covers", spy)
    return asked


def test_covering_requests_asks_covers_once_per_model_written_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The guard's predicate is `covers` and nothing else; a code-written request is never asked
    (it covers only itself, `report/session.py:194-199`)."""
    session = session_with(
        request("ER-001", FIT, ["cmp:0002", "hol:0001"], answered=True),
        request("ER-002", None, ["cmp:0002"], source="code"),
        request("ER-003", FASTENERS, ["cmp:0001"]),
        request("ER-004", FIT, ["cmp:0002"]),
    )
    asked = spy_on_covers(monkeypatch)

    covering = report_session.covering_requests(session, FIT, ["cmp:0002"])

    assert asked == [
        (FIT, ids("cmp:0002"), FIT, ids("cmp:0002", "hol:0001")),
        (FIT, ids("cmp:0002"), FASTENERS, ids("cmp:0001")),
        (FIT, ids("cmp:0002"), FIT, ids("cmp:0002")),
    ]
    assert all(type(call[1]) is frozenset and type(call[3]) is frozenset for call in asked)
    assert covering.answered is not None and covering.answered.id == "ER-001"
    assert covering.open is not None and covering.open.id == "ER-004"


def test_covering_requests_asks_nothing_for_a_question_with_no_item_and_no_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The early return stays (`report/session.py:201-202`)."""
    session = session_with(request("ER-001", None, [], answered=True), request("ER-002", None, []))
    asked = spy_on_covers(monkeypatch)

    covering = report_session.covering_requests(session, None, [])

    assert asked == []
    assert covering == report_session.CoveringRequests(answered=None, open=None)


# --- documents_named: the drawing guard's document rule, public (questions.md 2; QA-11) -----------

ROOT = "doc:1"
PLATE = "doc:2"
PLATE_1 = "cmp:0001"
HOLE = "hole:1"
SCREW = "fst:1"


def plate_package() -> EvidencePackage:
    """`build_package`'s fictional package cut to one part instance: its part `doc:2`, the plate
    here, has the one instance `cmp:0001`, holding the hole `hole:1` and, moved onto it, the
    fastener `fst:1`; the root assembly `doc:1` has no instance."""
    base = build_package()
    plate_1 = base.components[0]
    return build_package(
        components=[plate_1],
        fasteners=[base.fasteners[0].model_copy(update={"component_id": plate_1.id})],
    )


def test_documents_named_is_public_and_the_private_name_is_gone() -> None:
    assert callable(tools_session.documents_named)
    assert not hasattr(tools_session, "_documents_named")


@pytest.mark.parametrize(
    ("entity_ids", "documents"),
    [
        ([PLATE], [PLATE]),
        ([ROOT], [ROOT]),
        ([PLATE_1], [PLATE]),
        ([HOLE], [PLATE]),
        ([SCREW], [PLATE]),
        (["fea:0001"], []),
        (["dsn:1"], []),
        ([], []),
    ],
    ids=["document", "root-document", "instance", "hole", "fastener", "feature", "design", "none"],
)
def test_documents_named_names_each_id_s_document_as_the_drawing_guard_reads_it(
    entity_ids: list[str], documents: list[str]
) -> None:
    """`tools/session.py:280-298`: a document is itself, a component its document, a hole or a
    fastener its component's document; any other id names none."""
    context = context_for(plate_package())

    assert context.hole(HOLE) is not None and context.fastener(SCREW) is not None
    assert tools_session.documents_named(context, entity_ids) == documents


def test_documents_named_names_each_document_once_first_named_first() -> None:
    context = context_for(plate_package())

    named = tools_session.documents_named(
        context, [HOLE, "fea:0001", ROOT, SCREW, PLATE_1, PLATE, ROOT]
    )

    assert named == [PLATE, ROOT]
