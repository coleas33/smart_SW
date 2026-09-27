"""The "Findings by type" section of `report.md` (feature 013 T051; "Start here" before it).

`render_report(session, package=None, *, ranking=None)` renders one section above Findings when
it is given a ranking. Feature 007 made that section "Start here", the first five rows; feature
013 made it "Findings by type" (its `contracts/grouped-list.md` section 6): every finding in one
row of one group or of the "Checked, no issue" fold, the same groups, rows and order as the
Review tab. Five rules decide every test here.

**With no ranking the report is what it was.** The parameter defaults to `None` and the
section is guarded exactly as `## Tokens` is guarded on `session.usage`, so a caller that
renders without one gets byte for byte what it got before either section existed. Two tests pin
that from different directions: an equality against the un-ranked call on two different
sessions, and `test_report_tokens.py`'s one golden of this renderer, left untouched (research
R2.6 of 007).

**Every finding is listed, and still renders in full below.** The index names every finding
once - as a row, or as a folded row's member - and every finding still renders under
`## Findings`, in its severity section, whatever the index said about it.

**The section is rendered from the grouped view, never re-derived.** The groups, rows, counts
and words are `report/finding_groups.findings_by_type`'s, the one function the pane's routes
call; the coverage block is `attention.coverage_line`'s; this module owns the heading, the line
shapes, the blank lines and the footer, and the footer names `ranking.policy_version` rather than
a literal.

**The gate brief keeps its Start here, and the two agree.** The model-facing five rows stay in
the gate brief; the parity rule that replaced 007's anti-drift test (each of the brief's ids in
this index, in order within its group) is `test_prerun_digest.py`'s.

**No percent sign anywhere.** The Standards page's body scan forbids one (research R2.14 of 007),
so the whole rendered report is scanned rather than the section alone.

The golden `test_the_ranked_report_matches_the_golden.md` pins the ranked shape of the 2026-09-18
review fixture rendered with its package, which is the only place the section's exact bytes are
written down.

Section 8 is the enumeration (007 T031, FR-019). A section that one render site writes and the
next erases is worse than none, so the production render sites are counted rather than trusted:
the source tree is parsed and every call of *this* renderer has to be one of the seven named
below and has to pass a ranking.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest
from pytest_regressions.file_regression import FileRegressionFixture

import swreview
from swreview.ir.loader import load_package
from swreview.report.attention import TOP_N, Ranking, coverage_line, load_policy, rank
from swreview.report.finding_groups import findings_by_type
from swreview.report.markdown import render_report
from swreview.report.session import ReviewSession, load_session
from swreview.report.summary import load_words
from tests.support.attention import PIN_ONE, PIN_TWO, REVIEW_FOLDER, REVIEW_SESSION_FILE
from tests.unit.test_attention import REVIEW_ORDER, disposition, session_of, spec
from tests.unit.test_report import PACKAGE as REPORT_PACKAGE
from tests.unit.test_report import build_session

TOKENS_GOLDEN = (
    Path(__file__).parent
    / "test_report_tokens"
    / "test_a_session_without_usage_matches_the_golden.md"
)
"""The one golden of this renderer that existed before feature 007 (research R2.6)."""

HEADING = "## Findings by type"

FOOTER = "Ranked by attention_policy_v1; the rule is in reviewer/src/swreview/report/attention.py."
"""What the footer reads on every fixture here, all of which rank under `attention_policy_v1`.
The renderer builds it from `ranking.policy_version`; `test_the_footer_names_the_policy_the
_ranking_carries` is what proves it is not this literal."""

ROW = re.compile(r"^- \*\*(F-\d+)\*\* ")
MEMBERS = re.compile(r"^   - Members: (.+)$")


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


def index_of(session: ReviewSession, package, ranking: Ranking | None = None) -> list[str]:
    """The "Findings by type" section of one rendered report, sliced out of the whole thing,
    so what these tests assert is what an engineer opens."""
    ranking = ranking if ranking is not None else rank(session)
    return section_of(render_report(session, package, ranking=ranking), HEADING)


def listed_ids(lines: list[str]) -> list[str]:
    """Every finding id the index names, a row's id then its other members, in order."""
    ids: list[str] = []
    for line in lines:
        if row := ROW.match(line):
            ids.append(row.group(1))
        elif members := MEMBERS.match(line):
            ids.extend(one for one in members.group(1).split(", ") if one not in ids)
    return ids


# --- 1. with no ranking, the report is byte-identical to today -------------------------


def test_passing_ranking_none_renders_the_review_fixture_byte_for_byte(
    review_session: ReviewSession, review_package
) -> None:
    with_keyword = render_report(review_session, review_package, ranking=None)

    assert with_keyword == render_report(review_session, review_package)
    assert HEADING not in with_keyword


def test_passing_ranking_none_renders_the_report_fixture_byte_for_byte() -> None:
    """`build_session` is what every other test of this renderer is written against, so the
    default has to be identical there too and not only on the new fixture."""
    session = build_session()

    with_keyword = render_report(session, REPORT_PACKAGE, ranking=None)

    assert with_keyword == render_report(session, REPORT_PACKAGE)
    assert with_keyword == render_report(session, package=REPORT_PACKAGE)
    assert "Findings by type" not in with_keyword


def test_the_tokens_golden_of_this_renderer_still_passes() -> None:
    """The one golden that covers `render_report` with no ranking (research R2.6), read from
    here so the byte-identity claim fails in this module rather than only in its own."""
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
    lines = text.splitlines()

    assert lines.index("## Summary") < lines.index(HEADING) < lines.index("## Findings")


def test_the_section_is_rendered_exactly_once_and_start_here_is_gone(
    review_session: ReviewSession, review_package
) -> None:
    text = render_report(review_session, review_package, ranking=rank(review_session))

    assert text.count(HEADING) == 1
    assert text.count(FOOTER) == 1
    assert "## Start here" not in text
    assert "Not amplified:" not in text, "every row is listed, so nothing is left unamplified"


def test_a_session_rendered_with_no_package_still_carries_the_section(
    review_session: ReviewSession,
) -> None:
    """A folder holding no package renders with none (`render_folder_report`): the rows are
    then titled with the recorded ids, and the same findings are listed in the same order."""
    text = render_report(review_session, ranking=rank(review_session))

    assert "not supplied" in text.lower()
    assert listed_ids(section_of(text, HEADING)) == listed_ids(
        index_of(review_session, load_package(REVIEW_FOLDER).package)
    )


# --- 3. what the section says -------------------------------------------------------------


def test_the_section_is_the_grouped_view_then_the_coverage_block_and_the_footer(
    review_session: ReviewSession, review_package
) -> None:
    ranking = rank(review_session)
    view = findings_by_type(review_session, review_package, load_words(), load_policy())

    lines = index_of(review_session, review_package, ranking)

    headings = [line for line in lines if line.startswith("### ")]
    assert headings == [f"### {group.title}: {group.text}" for group in view.groups]
    assert lines[-(len(coverage_line(ranking)) + 3) :] == [
        *coverage_line(ranking),
        "",
        FOOTER,
        "",
    ]


def test_every_finding_is_listed_once(review_session: ReviewSession, review_package) -> None:
    ids = listed_ids(index_of(review_session, review_package))

    assert sorted(ids) == sorted(finding.id for finding in review_session.findings)
    assert len(ids) == len(set(ids))


def test_each_row_line_names_its_finding_its_reason_and_its_title(
    review_session: ReviewSession, review_package
) -> None:
    view = findings_by_type(review_session, review_package, load_words(), load_policy())
    rows = [row for group in view.groups for row in group.rows]

    lines = [line for line in index_of(review_session, review_package) if ROW.match(line)]

    assert lines == [f"- **{row.finding_id}** {row.reason} - {row.title}" for row in rows]


def test_the_rows_keep_the_rankings_order_within_their_group(
    review_session: ReviewSession, review_package
) -> None:
    """The index is the ranking's order cut into groups: within each group, its ids in rank
    order (REVIEW_ORDER is the order the owner agreed on 2026-09-19)."""
    lines = index_of(review_session, review_package)
    groups: dict[str, list[str]] = {}
    current = ""
    for line in lines:
        if line.startswith("### "):
            current = line
            groups[current] = []
        elif row := ROW.match(line):
            groups[current].append(row.group(1))

    for ids in groups.values():
        assert ids == [one for one in REVIEW_ORDER if one in ids]


def test_a_folded_row_names_its_members_its_count_and_its_reach() -> None:
    specs = [
        spec("rms.folders.present", component_ids=(PIN_ONE,)),
        spec("rms.folders.present", component_ids=(PIN_TWO,)),
    ]
    session = session_of("report-folded", specs)

    lines = index_of(session, None)

    [row] = [line for line in lines if ROW.match(line)]
    assert row.endswith(" · ×2 · reaches 2 components")
    assert "   - Members: F-001, F-002" in lines


def test_each_group_lists_its_goal_lines_after_its_rows(
    review_session: ReviewSession, review_package
) -> None:
    lines = index_of(review_session, review_package)
    start = lines.index(next(line for line in lines if line.startswith("### Interference")))
    block = lines[start : lines.index("", start)]

    assert block[-1].startswith("Goals: Interference - issues found; Hole alignment - ")
    assert "; Fits and stacks - " in block[-1]


def test_a_pass_is_listed_in_the_checked_fold_last() -> None:
    specs = [
        spec("interference.static"),
        spec("rms.folders.present", status="checked_within_scope"),
    ]
    session = session_of("report-pass", specs)

    lines = index_of(session, None)

    headings = [line for line in lines if line.startswith("### ")]
    assert headings[-1] == "### Checked, no issue: 1 finding"
    fold = lines[lines.index(headings[-1]) :]
    assert fold[1] == (
        "- **F-002** checked within scope - "
        + session.findings[1].title
    )


def test_a_persisted_explanation_is_printed_under_its_row() -> None:
    session = session_of("report-explained", [spec("interference.static")])
    session.finding_explanations = {"F-001": "why the overlap matters"}

    lines = index_of(session, None)

    row = next(index for index, line in enumerate(lines) if ROW.match(line))
    assert lines[row + 1] == "   - AI guidance: why the overlap matters"


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


def test_a_session_with_no_findings_lists_each_group_by_its_goals_then_the_coverage() -> None:
    session = session_of("report-no-findings", [])
    ranking = rank(session)

    lines = index_of(session, None, ranking)

    assert [line for line in lines if line.startswith("### ")] == [
        f"### {group.title}: not reached (no check ran)" for group in load_words().finding_groups
    ]
    assert listed_ids(lines) == []
    assert lines[-(len(coverage_line(ranking)) + 3) :] == [
        *coverage_line(ranking),
        "",
        FOOTER,
        "",
    ]
    assert "No findings." in render_report(session, ranking=ranking)


def test_an_all_decided_session_lists_every_finding_and_renders_each_below() -> None:
    session = session_of(
        "report-all-decided",
        [
            spec("rms.grouping.all_features_in_a_group", disposition=disposition("accepted")),
            spec("rms.folders.present", disposition=disposition("rejected")),
        ],
    )

    text = render_report(session, ranking=rank(session))

    assert "### Modelling practice: 2 findings · 2 decided" in text
    assert listed_ids(section_of(text, HEADING)) == ["F-001", "F-002"]
    for finding in session.findings:
        assert f"#### {finding.id}: {finding.title}" in text


# --- 5. every finding still renders below ------------------------------------------------------


@pytest.mark.parametrize("with_package", [True, False], ids=["with-package", "no-package"])
def test_no_finding_is_absent_from_the_severity_sections_below(
    review_session: ReviewSession, review_package, with_package: bool
) -> None:
    package = review_package if with_package else None

    text = render_report(review_session, package, ranking=rank(review_session))
    findings = section_of(text, "## Findings")

    assert len(review_session.findings) == 8
    for finding in review_session.findings:
        assert f"#### {finding.id}: {finding.title}" in findings


def test_the_findings_section_is_byte_identical_ranked_or_not(
    review_session: ReviewSession, review_package
) -> None:
    """The index is a view; it writes nothing to the session and reorders no section."""
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
    """The second golden of this renderer (research R2.6 of 007): the 2026-09-18 review with
    its package, ranked. Regenerate with `uv run pytest tests/unit/test_report_start_here.py
    --force-regen` and read the "Findings by type" block before committing it."""
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


# --- 8. the enumeration of the production render sites (T031, FR-019) -----------------------

SOURCE_ROOT = Path(swreview.__file__).resolve().parent
"""`reviewer/src/swreview`: every production module, and no test module."""

RENDERER_MODULE = "swreview.report.markdown"
"""The import a site is matched on.

Matched on the **import** and not on the bare name, because `remodel/report.py` defines a
`render_report` of its own for the re-modeller's report - a different renderer, with a
different golden, that never calls this one (research R2.6). A scan keyed on the name
would count its calls and demand a ranking the re-modeller has no session to compute.
"""

RENDER_SITES: frozenset[str] = frozenset(
    {
        "chat/server.py::_render_report",
        "chat/sessions.py::record_disposition",
        "chat/sessions.py::record_timing_live",
        "checks/rules/run.py::write_report",
        "checks/standards/run.py::_write_report",
        "cli.py::review",
        "report/rerender.py::render_folder_report",
    }
)
"""Every production call of `swreview.report.markdown.render_report`, by path and function.

The eight places a `report.md` an engineer opens is written from (research R3) reach the
renderer through these seven calls: the review command line, the pane after every turn and
after a stop, a disposition recorded on a live review, minutes recorded on a live review, the
Model check, the standards check, and `render_folder_report`, which both `swreview report` and
the one offline folder re-render call (`FOLDER_RENDER_SITES`; since 2026-09-23, when `swreview
report` stopped rendering from the session alone). Each must pass `ranking=`; an eighth call
fails the first test below and a call that renders without a ranking fails the second.
"""

FOLDER_RENDER_SITES: frozenset[str] = frozenset({"cli.py::report"})
"""The importers of `render_folder_report`, which reads the folder's package and a standards
folder's verdict header: `swreview report`, which writes no record. The re-render, which
writes one, is its other caller and sits in the module that defines it, which the scan does not
read (it matches imports); that it renders the same text is `test_rerender.py`'s. A writer that
went back to rendering from the session alone would become an eighth entry in `RENDER_SITES`
and fail there; one that stopped rendering through the folder fails here.
"""

RERENDER_SITES: frozenset[str] = frozenset(
    {
        "cli.py::_save_run",
        "cli.py::timing",
        "report/dispositions.py::apply_disposition",
    }
)
"""The offline writers that render through `rerender_run_folder` rather than themselves.

They are pinned for the same reason the seven are: each of them *used* to call the
renderer directly with nothing but the session, which is how a run folder lost its package
and a standards folder lost its verdict header (research R2.7). A function that went back
to rendering its own report would become an eighth entry in `RENDER_SITES` and fail there;
one that stopped re-rendering at all fails here.
"""


def _module_key(path: Path) -> str:
    return path.relative_to(SOURCE_ROOT).as_posix()


def _parsed_sources() -> list[tuple[str, ast.Module]]:
    """Every production module under `swreview`, parsed, keyed by its relative path."""
    return [
        (_module_key(path), ast.parse(path.read_text(encoding="utf-8"), filename=str(path)))
        for path in sorted(SOURCE_ROOT.rglob("*.py"))
    ]


def _names_imported_from(tree: ast.Module, module: str, name: str) -> set[str]:
    """What `name` is bound to by `from <module> import name [as alias]`, if at all."""
    return {
        alias.asname or alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == module
        for alias in node.names
        if alias.name == name
    }


def _calls_of(module: str, name: str) -> dict[str, list[ast.Call]]:
    """`path::function` -> the call nodes, for every call of `name` imported from `module`.

    The walk is hand-rolled rather than `ast.walk`, because the answer is *which function*
    holds the call and `ast` records no parent link. A module that does not import the
    name is skipped whole, which is what keeps the re-modeller's own renderer out.
    """
    calls: dict[str, list[ast.Call]] = {}

    def walk(node: ast.AST, key: str, bound: set[str], enclosing: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                walk(child, key, bound, child.name)
                continue
            if (
                isinstance(child, ast.Call)
                and isinstance(child.func, ast.Name)
                and child.func.id in bound
            ):
                calls.setdefault(f"{key}::{enclosing}", []).append(child)
            walk(child, key, bound, enclosing)

    for key, tree in _parsed_sources():
        bound = _names_imported_from(tree, module, name)
        if bound:
            walk(tree, key, bound, "<module>")
    return calls


def test_the_production_render_sites_are_exactly_the_seven_named_here() -> None:
    """FR-019: a new render site cannot land unwired, because an eighth fails here.

    Add the site to `RENDER_SITES` *and* make it pass a ranking; a site that renders a
    report an engineer opens without the section is the drift this test exists to stop.
    """
    found = set(_calls_of(RENDERER_MODULE, "render_report"))

    assert found == RENDER_SITES, (
        "the production calls of report.markdown.render_report have moved.\n"
        f"new: {sorted(found - RENDER_SITES)}\n"
        f"gone: {sorted(RENDER_SITES - found)}"
    )


def test_every_production_render_passes_a_ranking() -> None:
    """Each of the seven hands the renderer a `ranking=`; none renders the default shape."""
    unranked = [
        site
        for site, calls in sorted(_calls_of(RENDERER_MODULE, "render_report").items())
        for call in calls
        if not any(keyword.arg == "ranking" for keyword in call.keywords)
    ]

    assert unranked == [], (
        "these production render sites call render_report without ranking=, so the report "
        f"they write has no 'Start here' section: {unranked}"
    )


def test_the_folder_writers_render_through_the_one_folder_function() -> None:
    """`swreview report` renders through the half of the re-render that reads the folder, so
    it cannot render a folder's report without its package or its verdict header."""
    found = set(_calls_of("swreview.report.rerender", "render_folder_report"))

    assert found == FOLDER_RENDER_SITES, (
        "the folder render sites have moved.\n"
        f"new: {sorted(found - FOLDER_RENDER_SITES)}\n"
        f"gone: {sorted(FOLDER_RENDER_SITES - found)}"
    )


def test_the_offline_writers_re_render_through_the_one_folder_function() -> None:
    """The three commands that re-render a folder they did not run share one writer.

    A fourth writer that rendered without the folder's package, or without a standards
    folder's verdict header, is the defect feature 007 removes (research R2.7).
    """
    found = set(_calls_of("swreview.report.rerender", "rerender_run_folder"))

    assert found == RERENDER_SITES, (
        "the offline re-render sites have moved.\n"
        f"new: {sorted(found - RERENDER_SITES)}\n"
        f"gone: {sorted(RERENDER_SITES - found)}"
    )


def test_the_re_modellers_own_renderer_is_not_counted() -> None:
    """The scan matches the import, so `remodel/report.py`'s own `render_report` is out.

    It defines and calls a renderer of the same name that never calls this one; counting
    it would demand a ranking of a module that holds no review session (research R2.6).
    """
    remodel = ast.parse(
        (SOURCE_ROOT / "remodel" / "report.py").read_text(encoding="utf-8"),
    )

    assert _names_imported_from(remodel, RENDERER_MODULE, "render_report") == set()
    assert any(
        isinstance(node, ast.FunctionDef) and node.name == "render_report"
        for node in ast.walk(remodel)
    ), "remodel/report.py no longer defines a renderer of its own; drop this test"
    assert not any(site.startswith("remodel/") for site in RENDER_SITES)
