"""The "Start here" section of `report.md` (T025, contracts/attention.md section 3).

`render_report(session, package=None, *, ranking=None)` grew one keyword-only parameter and
one section. Four rules decide every test here.

**With no ranking the report is what it was.** The parameter defaults to `None` and the
section is guarded exactly as `## Tokens` is guarded on `session.usage`
(`report/markdown.py:74-76`), so a caller that has not been wired yet - six of the eight,
until T032 - renders byte for byte what it rendered before. Two tests pin that from
different directions: an equality against the un-ranked call on two different sessions, and
`test_report_tokens.py`'s one golden of this renderer, which is left untouched (research
R2.6).

**Amplify, never filter.** The section is an index, not a selection: every finding it does
not name still renders in full below, in its severity section, in recording order. The test
that matters most here is the one that asserts every finding id appears under `## Findings`
whatever the ranking said about it.

**The section is rendered, never re-derived.** `attention.start_here_lines` and
`attention.coverage_line` produce the rows, the not-amplified line and the coverage block;
this module owns the heading, the blank lines and the footer only, and the footer names
`ranking.policy_version` rather than a literal. A test that restated a reason sentence here
would pin the same words in two files.

**No percent sign anywhere.** The Standards page's body scan forbids one (research R2.14),
so the whole rendered report is scanned rather than the section alone.

The new golden `test_the_ranked_report_matches_the_golden.md` pins the ranked shape of the
2026-09-18 review fixture rendered with its package, which is the only place the section's
exact bytes are written down.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pytest_regressions.file_regression import FileRegressionFixture

from swreview.ir.loader import load_package
from swreview.report.attention import TOP_N, Ranking, coverage_line, rank, start_here_lines
from swreview.report.markdown import render_report
from swreview.report.session import ReviewSession, load_session
from tests.support.attention import REVIEW_FOLDER, REVIEW_SESSION_FILE
from tests.unit.test_attention import REVIEW_ORDER, disposition, session_of, spec
from tests.unit.test_report import PACKAGE as REPORT_PACKAGE
from tests.unit.test_report import build_session

TOKENS_GOLDEN = (
    Path(__file__).parent
    / "test_report_tokens"
    / "test_a_session_without_usage_matches_the_golden.md"
)
"""The one golden of this renderer that existed before this feature (research R2.6)."""

FOOTER = "Ranked by attention_policy_v1; the rule is in reviewer/src/swreview/report/attention.py."
"""What the footer reads on every fixture here, all of which rank under `attention_policy_v1`.
The renderer builds it from `ranking.policy_version`; `test_the_footer_names_the_policy_the
_ranking_carries` is what proves it is not this literal."""


@pytest.fixture(scope="module")
def review_session() -> ReviewSession:
    """The 2026-09-18 review: eight findings, seven close-out rows, three open requests."""
    return load_session(REVIEW_SESSION_FILE)


@pytest.fixture(scope="module")
def review_package():
    """The fixture package beside that session, so component names render rather than ids."""
    return load_package(REVIEW_FOLDER).package


def section_of(text: str, heading: str) -> list[str]:
    """The lines of one `## ` section, heading included, up to the next `## ` heading."""
    lines = text.splitlines()
    start = lines.index(heading)
    for offset in range(start + 1, len(lines)):
        if lines[offset].startswith("## "):
            return lines[start:offset]
    return lines[start:]


def start_here_of(session: ReviewSession, package, ranking: Ranking | None = None) -> list[str]:
    """The "Start here" section of one rendered report, sliced out of the whole thing.

    The section is always read back out of the full report rather than from
    `_render_start_here`, so what these tests assert is what an engineer opens.
    """
    ranking = ranking if ranking is not None else rank(session)
    return section_of(render_report(session, package, ranking=ranking), "## Start here")


# --- 1. with no ranking, the report is byte-identical to today -------------------------


def test_passing_ranking_none_renders_the_review_fixture_byte_for_byte(
    review_session: ReviewSession, review_package
) -> None:
    with_keyword = render_report(review_session, review_package, ranking=None)

    assert with_keyword == render_report(review_session, review_package)
    assert "## Start here" not in with_keyword


def test_passing_ranking_none_renders_the_report_fixture_byte_for_byte() -> None:
    """`build_session` is what every other test of this renderer is written against, so the
    default has to be identical there too and not only on the new fixture."""
    session = build_session()

    with_keyword = render_report(session, REPORT_PACKAGE, ranking=None)

    assert with_keyword == render_report(session, REPORT_PACKAGE)
    assert with_keyword == render_report(session, package=REPORT_PACKAGE)
    assert "Start here" not in with_keyword


def test_the_tokens_golden_of_this_renderer_still_passes() -> None:
    """The one golden that covers `render_report` (research R2.6), read from here so the
    byte-identity claim fails in this module rather than only in its own.

    The comparison is line by line: the checked-in file's line endings are the working
    tree's business (`.gitattributes`), and what this asserts is the report's text.
    """
    from tests.unit.test_report_tokens import PACKAGE as TOKENS_PACKAGE
    from tests.unit.test_report_tokens import make_session

    golden = TOKENS_GOLDEN.read_text(encoding="utf-8")

    assert render_report(make_session(usage=None), TOKENS_PACKAGE).splitlines() == (
        golden.splitlines()
    )


# --- 2. where the section sits -----------------------------------------------------------


def test_the_section_sits_between_summary_and_findings(
    review_session: ReviewSession, review_package
) -> None:
    text = render_report(review_session, review_package, ranking=rank(review_session))

    assert text.index("## Summary") < text.index("## Start here")
    assert text.index("## Start here") < text.index("## Findings")


def test_the_section_is_rendered_exactly_once(
    review_session: ReviewSession, review_package
) -> None:
    text = render_report(review_session, review_package, ranking=rank(review_session))

    assert text.count("## Start here") == 1
    assert text.count(FOOTER) == 1


def test_a_session_rendered_with_no_package_still_carries_the_section(
    review_session: ReviewSession,
) -> None:
    """Two of the eight call sites pass no package; the section does not read one."""
    text = render_report(review_session, ranking=rank(review_session))

    assert "not supplied" in text.lower()
    assert section_of(text, "## Start here") == start_here_of(
        review_session, load_package(REVIEW_FOLDER).package
    )


# --- 3. what the section says -------------------------------------------------------------


def test_the_section_is_the_two_renderers_verbatim_under_a_heading_and_a_footer(
    review_session: ReviewSession, review_package
) -> None:
    """DRY: the rows, the not-amplified line and the coverage block are `attention.py`'s
    words, and this renderer adds a heading, three blank lines and one footer."""
    ranking = rank(review_session)

    lines = start_here_of(review_session, review_package, ranking)

    assert lines == [
        "## Start here",
        "",
        *start_here_lines(ranking),
        "",
        *coverage_line(ranking),
        "",
        FOOTER,
        "",
    ]


def test_the_section_lists_exactly_top_n_rows_in_the_ranked_order(
    review_session: ReviewSession, review_package
) -> None:
    ranking = rank(review_session)
    assert len(ranking.rows) > TOP_N, "the fixture must have rows the section leaves out"

    lines = start_here_of(review_session, review_package, ranking)
    numbered = [line for line in lines if line[:1].isdigit()]

    assert len(numbered) == TOP_N
    for number, (line, row) in enumerate(zip(numbered, ranking.rows, strict=False), start=1):
        assert line.startswith(f"{number}. **{row.finding_id}** `{row.check}` - ")
        assert row.reason in line


def test_the_not_amplified_line_and_the_coverage_block_are_present(
    review_session: ReviewSession, review_package
) -> None:
    lines = start_here_of(review_session, review_package)

    assert "Not amplified: 3 findings (0 checked within scope, 0 already decided, " in "\n".join(
        lines
    )
    assert (
        "What this run could not reach: 39 unresolved, 11 skipped, 0 failed, 7 out of scope."
        in lines
    )
    assert sum(1 for line in lines if line.startswith("- ")) == 6, (
        "five close-out bullets and the tail bullet"
    )


def test_the_footer_names_the_policy_the_ranking_carries(
    review_session: ReviewSession, review_package
) -> None:
    """The version is read from the ranking, never spelled into the renderer."""
    ranking = rank(review_session).model_copy(update={"policy_version": "attention_policy_v9"})

    text = render_report(review_session, review_package, ranking=ranking)

    assert (
        "Ranked by attention_policy_v9; the rule is in "
        "reviewer/src/swreview/report/attention.py." in text
    )
    assert "attention_policy_v1" not in text


# --- 4. the empty cases ---------------------------------------------------------------------


def test_a_session_with_no_findings_prints_its_sentence_and_the_coverage_block() -> None:
    session = session_of("report-no-findings", [])
    ranking = rank(session)

    lines = start_here_of(session, None, ranking)

    assert lines == [
        "## Start here",
        "",
        "Nothing to start with: no findings were recorded.",
        "",
        *coverage_line(ranking),
        "",
        FOOTER,
        "",
    ]
    assert "No findings." in render_report(session, ranking=ranking)


def test_an_all_informational_session_prints_its_sentence_and_counts_them() -> None:
    session = session_of(
        "report-all-informational",
        [
            spec("rms.grouping.all_features_in_a_group", severity="info"),
            spec("rms.folders.present", severity="info"),
        ],
    )
    lines = start_here_of(session, None)

    assert lines[2] == "Nothing to start with: every finding is informational or already decided."
    assert "Not amplified: 2 findings (0 checked within scope, 0 already decided, " in lines[4]
    assert lines[-2] == FOOTER


def test_an_all_decided_session_still_renders_every_finding_below() -> None:
    session = session_of(
        "report-all-decided",
        [
            spec("rms.grouping.all_features_in_a_group", disposition=disposition("accepted")),
            spec("rms.folders.present", disposition=disposition("rejected")),
        ],
    )

    text = render_report(session, ranking=rank(session))

    assert "Nothing to start with: every finding is informational or already decided." in text
    for finding in session.findings:
        assert f"#### {finding.id}: {finding.title}" in text


# --- 5. amplify, never filter --------------------------------------------------------------


@pytest.mark.parametrize("with_package", [True, False], ids=["with-package", "no-package"])
def test_no_finding_is_absent_from_the_severity_sections_below(
    review_session: ReviewSession, review_package, with_package: bool
) -> None:
    """FR-013's other half: the section names five of eight, and all eight still render."""
    package = review_package if with_package else None

    text = render_report(review_session, package, ranking=rank(review_session))
    findings = section_of(text, "## Findings")

    assert len(review_session.findings) == 8
    for finding in review_session.findings:
        assert f"#### {finding.id}: {finding.title}" in findings


def test_the_findings_section_is_byte_identical_ranked_or_not(
    review_session: ReviewSession, review_package
) -> None:
    """The ranking is a view; it writes nothing to the session and reorders no section."""
    ranked = render_report(review_session, review_package, ranking=rank(review_session))
    plain = render_report(review_session, review_package)

    assert section_of(ranked, "## Findings") == section_of(plain, "## Findings")
    assert section_of(ranked, "## Summary") == section_of(plain, "## Summary")
    assert section_of(ranked, "## Coverage") == section_of(plain, "## Coverage")


# --- 6. no percent sign ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    ["review", "no-findings", "all-informational"],
    ids=["review", "no-findings", "all-informational"],
)
def test_no_percent_sign_anywhere_in_a_ranked_report(
    review_session: ReviewSession, review_package, name: str
) -> None:
    """The Standards page's body scan forbids one, so the whole report is scanned."""
    if name == "review":
        session, package = review_session, review_package
    elif name == "no-findings":
        session, package = session_of("percent-no-findings", []), None
    else:
        session, package = (
            session_of("percent-informational", [spec("rms.folders.present", severity="info")]),
            None,
        )

    text = render_report(session, package, ranking=rank(session))

    assert "%" not in text


# --- 7. the golden ------------------------------------------------------------------------------


def test_the_ranked_report_matches_the_golden(
    review_session: ReviewSession, review_package, file_regression: FileRegressionFixture
) -> None:
    """The second golden of this renderer (research R2.6): the 2026-09-18 review with its
    package, ranked. Regenerate with `uv run pytest tests/unit/test_report_start_here.py
    --force-regen` and read the "Start here" block before committing it."""
    report = render_report(review_session, review_package, ranking=rank(review_session))

    file_regression.check(report, extension=".md", encoding="utf-8", newline="")


def test_the_ranking_the_golden_pins_is_the_one_the_policy_produces(
    review_session: ReviewSession,
) -> None:
    """The golden is a rendering of `rank()`; this is the assertion that says so in words,
    so a golden regenerated against a broken ranking fails here."""
    ranking = rank(review_session)

    assert isinstance(ranking, Ranking)
    assert [row.finding_id for row in ranking.rows[:TOP_N]] == list(REVIEW_ORDER[:TOP_N])
    assert [row.reason for row in ranking.rows[:TOP_N]] == [
        "needs your judgement",
        "needs your judgement",
        "rebuild breaker, demonstrated",
        "rebuild breaker, demonstrated",
        "discipline, demonstrated",
    ]
