"""The bought-parts line (feature 013 T033), against its `contracts/part-roles.md` section 7.

A bought part is not graded for modelling practice or hygiene, and the review says so once: in
one summary line and one `report.md` section, both **read from the persisted coverage rows** the
pre-run writes - `coverage.prerun.bought_parts` (skipped) and `coverage.prerun.maybe_bought`
(unresolved) - and never classified again. The routes that build the summary have no profile and
no roles (`chat/server.py`'s attention route, `report/snapshot.py`, the disk route), so reading
the rows is what makes the live review, the disk route and the re-render say the same line.

The rows are lane P's (013 T030); these tests write them as the contract states them, with
fictional file names, so they hold before that lane lands and pin what it must write.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from uuid import UUID, uuid5

import pytest

from swreview.ir.models import EvidencePackage
from swreview.report.attention import rank
from swreview.report.markdown import render_report
from swreview.report.session import ReviewSession, load_session, save_session
from swreview.report.summary import (
    BOUGHT_PARTS_CHECK,
    MAYBE_BOUGHT_CHECK,
    BoughtParts,
    bought_parts_of,
    goal_of,
    load_words,
    review_ranking,
)
from tests.support.attention import (
    ASSEMBLY_DOCUMENT,
    PART_DOCUMENT,
    PIN_DOCUMENT,
    CoverageRow,
    CoverageSpec,
    FindingSpec,
    attention_package,
    build_attention_session,
)
from tests.unit.test_attention import STEPS, spec

NAMESPACE = UUID("7a1e6d64-1f2b-4c3a-9d5e-00000000013b")

BOUGHT_SENTENCE = (
    "1 parts not graded for modelling practice or hygiene (bought): dowel-pin.SLDPRT "
    "(a bought-parts folder)"
)
"""The first row's sentence as `part-roles.md` section 7 words it, over the attention package's
pin document (its file name is the package's own)."""

MAYBE_SENTENCE = (
    "housing.SLDPRT graded; each finding says it may be bought; asked in ER-001; do not ask "
    "for their drawings"
)
ABSENT_SENTENCE = (
    "Bought parts were not told apart: no standards profile is configured; Toolbox parts were "
    "not graded: dowel-pin.SLDPRT"
)


def bought_row(sentence: str = BOUGHT_SENTENCE, documents: Sequence[str] = (PIN_DOCUMENT,)):
    return CoverageRow(check=BOUGHT_PARTS_CHECK, reason=sentence, document_ids=tuple(documents))


def maybe_row(sentence: str = MAYBE_SENTENCE, documents: Sequence[str] = (PART_DOCUMENT,)):
    return CoverageRow(check=MAYBE_BOUGHT_CHECK, reason=sentence, document_ids=tuple(documents))


def session_with(
    name: str,
    *,
    skipped: Sequence[CoverageRow] = (),
    unresolved: Sequence[CoverageRow] = (),
    findings: Sequence[FindingSpec] = (),
) -> ReviewSession:
    return build_attention_session(
        session_id=uuid5(NAMESPACE, name),
        findings=findings,
        coverage=CoverageSpec(skipped=list(skipped), unresolved=list(unresolved)),
        steps=STEPS,
    )


def file_name_of(package: EvidencePackage, document_id: str) -> str:
    return next(one.file_name for one in package.documents if one.document_id == document_id)


def test_the_check_ids_are_the_contracts() -> None:
    assert (BOUGHT_PARTS_CHECK, MAYBE_BOUGHT_CHECK) == (
        "coverage.prerun.bought_parts",
        "coverage.prerun.maybe_bought",
    )


def test_neither_row_is_nothing_to_say() -> None:
    session = session_with("nothing", findings=[spec("rms.folders.present")])

    assert bought_parts_of(session, attention_package()) is None
    assert review_ranking(session, attention_package()).summary.bought_parts is None


def test_the_bought_row_names_its_documents_by_file_name_and_says_its_sentence() -> None:
    package = attention_package()
    session = session_with("bought", skipped=[bought_row()])

    line = bought_parts_of(session, package)

    assert line == BoughtParts(
        count=1,
        names=[file_name_of(package, PIN_DOCUMENT)],
        maybe_count=0,
        maybe_names=[],
        text=BOUGHT_SENTENCE,
    )


def test_the_maybe_row_names_the_unclear_documents() -> None:
    package = attention_package()
    session = session_with("maybe", unresolved=[maybe_row()])

    line = bought_parts_of(session, package)

    assert line is not None
    assert (line.count, line.names) == (0, [])
    assert (line.maybe_count, line.maybe_names) == (1, [file_name_of(package, PART_DOCUMENT)])
    assert line.text == MAYBE_SENTENCE


def test_both_rows_give_both_sentences_in_one_line() -> None:
    package = attention_package()
    session = session_with("both", skipped=[bought_row()], unresolved=[maybe_row()])

    line = bought_parts_of(session, package)

    assert line is not None
    assert (line.count, line.maybe_count) == (1, 1)
    assert line.text == f"{BOUGHT_SENTENCE}. {MAYBE_SENTENCE}"


def test_the_absent_state_is_said_in_its_own_words() -> None:
    """With no profile only Toolbox tells a bought part (`part-roles.md` section 7): the row's
    sentence says why the others were not told apart, and names the Toolbox parts."""
    session = session_with("absent", skipped=[bought_row(ABSENT_SENTENCE)])

    line = bought_parts_of(session, attention_package())

    assert line is not None
    assert (line.count, line.text) == (1, ABSENT_SENTENCE)


def test_a_document_the_package_does_not_hold_is_named_by_its_id() -> None:
    session = session_with("unknown-doc", skipped=[bought_row(documents=("doc:99",))])

    line = bought_parts_of(session, attention_package())

    assert line is not None
    assert line.names == ["doc:99"]


def test_with_no_package_every_document_is_named_by_its_id() -> None:
    session = session_with(
        "no-package", skipped=[bought_row(documents=(PIN_DOCUMENT, ASSEMBLY_DOCUMENT))]
    )

    line = bought_parts_of(session, None)

    assert line is not None
    assert (line.count, line.names) == (2, [PIN_DOCUMENT, ASSEMBLY_DOCUMENT])


def test_a_restated_row_supersedes_the_one_before_it() -> None:
    """After an answer regrades the review the row is restated (`part-roles.md` section 9); the
    summary reads the last row of each check, so an older row never speaks for the review."""
    older = bought_row("0 parts not graded for modelling practice or hygiene (bought)", ())
    session = session_with("restated", skipped=[older, bought_row()])

    line = bought_parts_of(session, attention_package())

    assert line is not None
    assert (line.count, line.text) == (1, BOUGHT_SENTENCE)


def test_the_rows_are_read_from_any_bucket() -> None:
    """The line reads what the rows say, not which bucket holds them: the pre-run writes the
    bought row skipped and the maybe row unresolved, and a later writer moving one must not
    silently drop the line."""
    session = session_with("buckets", unresolved=[bought_row()])

    line = bought_parts_of(session, attention_package())

    assert line is not None and line.count == 1


def test_the_line_is_counted_in_no_group_goal_or_headline() -> None:
    specs = [spec("interference.static"), spec("rms.folders.present")]
    plain = session_with("uncounted-plain", findings=specs)
    with_rows = session_with(
        "uncounted-rows", findings=specs, skipped=[bought_row()], unresolved=[maybe_row()]
    )
    package = attention_package()

    before = review_ranking(plain, package).summary
    after = review_ranking(with_rows, package).summary

    assert after.bought_parts is not None
    assert (after.headline, after.groups, after.tally) == (
        before.headline,
        before.groups,
        before.tally,
    )
    assert goal_of(BOUGHT_PARTS_CHECK, load_words().goals) is None
    assert goal_of(MAYBE_BOUGHT_CHECK, load_words().goals) is None


def test_a_session_loaded_from_disk_says_the_same_line(tmp_path: Path) -> None:
    """The disk route and the re-render read `session.json` with no profile and no roles."""
    session = session_with("disk", skipped=[bought_row()], unresolved=[maybe_row()])
    save_session(session, tmp_path / "session.json")

    loaded = load_session(tmp_path / "session.json")

    assert bought_parts_of(loaded, attention_package()) == bought_parts_of(
        session, attention_package()
    )


# --- report.md ---------------------------------------------------------------------------------


def test_the_report_renders_one_bought_parts_section_after_the_summary() -> None:
    session = session_with("report", skipped=[bought_row()], unresolved=[maybe_row()])

    text = render_report(session, attention_package(), ranking=rank(session))
    lines = text.splitlines()

    heading = f"## {load_words().bought_parts.heading}"
    assert heading == "## Bought parts"
    assert lines.count(heading) == 1
    assert lines.index("## Summary") < lines.index(heading) < lines.index("## Findings")
    start = lines.index(heading)
    assert lines[start : start + 4] == [heading, "", f"- {BOUGHT_SENTENCE}", f"- {MAYBE_SENTENCE}"]


def test_a_report_with_nothing_to_say_has_no_section() -> None:
    session = session_with("report-none", findings=[spec("rms.folders.present")])

    text = render_report(session, attention_package(), ranking=rank(session))

    assert "## Bought parts" not in text


@pytest.mark.parametrize("ranked", [True, False], ids=["ranked", "unranked"])
def test_the_section_does_not_need_a_ranking(ranked: bool) -> None:
    session = session_with("report-unranked", skipped=[bought_row()])

    text = render_report(session, attention_package(), ranking=rank(session) if ranked else None)

    assert text.count("## Bought parts") == 1


def test_a_root_that_looks_bought_is_said_once_and_counted_as_no_bought_part() -> None:
    """The review of 2026-09-27 (FR-008): a persisted bought-parts row that names no document and
    says the root looks bought gives the line its sentence, with nothing counted."""
    sentence = (
        "fict-drive.SLDASM looks bought (a vendor property); graded because it is the document "
        "under review"
    )
    session = session_with("root-looks-bought", skipped=[bought_row(sentence, documents=())])

    line = bought_parts_of(session, attention_package())

    assert line is not None
    assert (line.count, line.names, line.text) == (0, [], sentence)
    assert sentence in render_report(session, attention_package(), ranking=rank(session))
