"""The folded family in `report.md`: one collapsed subsection, every finding still there
(feature 008 T033, FR-014, `contracts/checks-first.md` section 6).

The report is the record an engineer reproduces a finding from, so folding is presentation
only: a folded family's findings render once, in full, after the severity sections, under
one `### Modelling practice: N findings across M rules` heading wrapped in `<details>`, and
are left out of the severity sections. A session that names no family renders exactly as
before; the existing goldens (`test_report_tokens.py`, `test_report_start_here.py`) are not
touched by this module.
"""

from __future__ import annotations

import re

from swreview.report.attention import family_title, rank
from swreview.report.markdown import render_report
from swreview.report.session import ReviewSession, load_session
from tests.support.attention import REVIEW_SESSION_FILE, attention_package
from tests.unit.test_report_start_here import section_of

HEADING = "### Modelling practice: 6 findings across 6 rules"
FINDING_HEADING = re.compile(r"^#### (F-\d+):")


def folded() -> ReviewSession:
    return load_session(REVIEW_SESSION_FILE).model_copy(update={"folded_families": ["rms"]})


def rendered(session: ReviewSession) -> str:
    return render_report(session, attention_package(), ranking=rank(session))


def findings_section(report: str) -> list[str]:
    return section_of(report, "## Findings")


def ids_in(lines: list[str]) -> list[str]:
    return [match.group(1) for line in lines if (match := FINDING_HEADING.match(line))]


def family_block(lines: list[str]) -> list[str]:
    """From the family heading to its `</details>`, both included."""
    start = lines.index(HEADING)
    end = lines.index("</details>", start)
    return lines[start : end + 1]


def test_one_family_subsection_holds_a_details_block() -> None:
    lines = findings_section(rendered(folded()))

    assert lines.count(HEADING) == 1
    block = family_block(lines)
    assert block[2].startswith("<details><summary>")
    assert block[2].endswith("</summary>")
    assert block[-1] == "</details>"
    assert HEADING == f"### {family_title('rms', 6, 6)}"


def test_the_summary_counts_each_rule_once() -> None:
    session = folded()
    summary = family_block(findings_section(rendered(session)))[2]

    for check in {f.check for f in session.findings if f.check.startswith("rms.")}:
        assert f"{check} (1)" in summary


def test_every_family_finding_is_inside_it_once_and_in_no_severity_section() -> None:
    session = folded()
    lines = findings_section(rendered(session))
    block = family_block(lines)
    outside = lines[: lines.index(HEADING)] + lines[lines.index(HEADING) + len(block) :]

    family_ids = [f.id for f in session.findings if f.check.startswith("rms.")]
    assert ids_in(block) == family_ids
    assert not set(ids_in(outside)) & set(family_ids)


def test_every_finding_id_still_appears_under_findings_exactly_once() -> None:
    session = folded()
    ids = ids_in(findings_section(rendered(session)))

    assert sorted(ids) == sorted(f.id for f in session.findings)


def test_the_family_renders_after_the_severity_sections() -> None:
    lines = findings_section(rendered(folded()))

    severity_headings = [i for i, line in enumerate(lines) if line in {"### High", "### Medium"}]
    assert severity_headings
    assert max(severity_headings) < lines.index(HEADING)


def test_a_family_finding_renders_as_the_severity_sections_render_it() -> None:
    session = folded()
    unfolded_report = rendered(session.model_copy(update={"folded_families": []}))
    folded_report = rendered(session)

    for finding in session.findings:
        heading = f"#### {finding.id}: {finding.title}"
        assert _finding_lines(folded_report, heading) == _finding_lines(unfolded_report, heading)


def _finding_lines(report: str, heading: str) -> list[str]:
    lines = report.splitlines()
    start = lines.index(heading)
    end = lines.index("", start + 2)
    return lines[start:end]


def test_start_here_and_the_summary_agree_with_the_fold() -> None:
    report = rendered(folded())

    summary = section_of(report, "## Summary")
    start_here = section_of(report, "## Start here")
    assert "- Total findings: 8" in summary
    assert any("Modelling practice: 6 findings across 6 rules" in line for line in start_here)
    numbered = [line for line in start_here if re.match(r"^\d+\. ", line)]
    assert len(numbered) == 3


def test_an_unfolded_session_renders_exactly_as_before() -> None:
    session = load_session(REVIEW_SESSION_FILE)
    explicit = session.model_copy(update={"folded_families": []})

    before = render_report(session, attention_package(), ranking=rank(session))
    assert render_report(explicit, attention_package(), ranking=rank(explicit)) == before
    assert "<details>" not in before
    assert "Modelling practice" not in before


def test_a_family_with_no_findings_renders_no_subsection() -> None:
    session = load_session(REVIEW_SESSION_FILE)
    no_rms = session.model_copy(
        update={
            "folded_families": ["rms"],
            "findings": [f for f in session.findings if not f.check.startswith("rms.")],
        }
    )

    assert "<details>" not in rendered(no_rms)


def test_a_session_of_nothing_but_family_findings_has_no_severity_section() -> None:
    session = folded()
    only_rms = session.model_copy(
        update={"findings": [f for f in session.findings if f.check.startswith("rms.")]}
    )
    lines = findings_section(rendered(only_rms))

    assert not [line for line in lines if line in {"### High", "### Medium", "### Low"}]
    assert lines.count(HEADING) == 1


def test_no_percent_sign_in_the_folded_report() -> None:
    lines = findings_section(rendered(folded()))

    assert "%" not in "\n".join(family_block(lines))
