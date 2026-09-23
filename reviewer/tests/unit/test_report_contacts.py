"""The report's Contacts section and the one count of every interference group (feature 010
T023, `contracts/contacts.md` sections 4 and 5).

A contact is listed in `report.md` in its own section after the findings, so a line-to-line
fit stays visible without reading as an interference. The section renders only when the
session holds a contact, so every report of a session written before this feature renders
byte for byte as it did (`test_report_tokens.py`'s golden and every `render_report` golden).
"""

from __future__ import annotations

from swreview.checks.interference import interference_outcomes
from swreview.findings import build_finding
from swreview.ir.models import Interference, InterferenceSettings, Volume
from swreview.report.markdown import render_report
from swreview.report.session import Contact, ReviewSession
from tests.support.packages import build_package
from tests.unit.test_report_tokens import make_session

SETTINGS = InterferenceSettings(
    treat_coincident_as_interference=True,
    treat_subassemblies_as_components=True,
    include_multibody=False,
    ignore_hidden=True,
    fastener_folder_treatment="include",
)


def row(
    interference_id: str,
    group_key: str,
    volume: float | None,
    *,
    possible: bool = False,
    status: str = "computed",
) -> Interference:
    return Interference(
        id=interference_id,
        configuration="Default",
        component_ids=["cmp:0001", "cmp:0002"],
        volume=None if volume is None else Volume(value=volume, unit="mm3"),
        settings=SETTINGS,
        status=status,  # type: ignore[arg-type]
        error=None,
        group_key=group_key,
        is_fastener=False,
        is_possible=possible,
    )


PACKAGE = build_package(
    interferences=[
        row("int:1", "boss/screws", 6.0),
        row("int:2", "pin/plate", 0.0),
        row("int:3", "rim/lid", None, possible=True),
        row("int:4", "flange/cover", None, status="truncated"),
    ]
)


def contact(identifier: str, kind: str, volume: float | None, joint: str | None) -> Contact:
    return Contact(
        id=identifier,
        kind=kind,  # type: ignore[arg-type]
        group_key="pin/plate" if kind == "zero_volume" else "rim/lid",
        configuration="Default",
        interference_ids=["int:2"] if kind == "zero_volume" else ["int:3"],
        component_ids=["cmp:0001", "cmp:0002"],
        volume_mm3=volume,
        joint_id=joint,
        reason="cmp:0001 and cmp:0002 touch at nominal in configuration Default.",
        tool_result_ids=[1],
    )


def interference_finding(identifier: str, status: str) -> object:
    return build_finding(
        finding_id=identifier,
        check="interference.static",
        title="Static interference",
        status=status,  # type: ignore[arg-type]
        severity="high" if status == "demonstrated" else "medium",
        package=PACKAGE,
        configuration="Default",
        observed="Static interference between cmp:0001 and cmp:0002",
        requirement="No unintended static interference",
        recommended_action="Confirm",
        component_ids=["cmp:0001", "cmp:0002"],
        tool_result_ids=[0],
        coverage_limits=["pair not evaluated"] if status == "unresolved" else [],
    )


def with_contacts() -> ReviewSession:
    base = make_session(usage=None)
    return base.model_copy(
        update={
            "findings": [
                *base.findings,
                interference_finding("F-101", "demonstrated"),
                interference_finding("F-102", "unresolved"),
            ],
            "contacts": [
                contact("C-001", "zero_volume", 0.0, "jnt:0001"),
                contact("C-002", "possible_only", None, None),
            ],
        }
    )


def section_of(report: str, heading: str) -> list[str]:
    lines = report.splitlines()
    start = lines.index(heading)
    end = next(
        (index for index in range(start + 1, len(lines)) if lines[index].startswith("## ")),
        len(lines),
    )
    return lines[start:end]


def test_interference_outcomes_counts_every_group_once() -> None:
    assert interference_outcomes(with_contacts(), PACKAGE) == {
        "groups": 4,
        "findings": 2,
        "contacts": 2,
        "unresolved": 1,
        "excepted": 0,
    }


def test_interference_outcomes_without_a_package_counts_what_was_judged() -> None:
    outcomes = interference_outcomes(with_contacts(), None)

    assert outcomes["groups"] == 4, "two findings and two contacts"


def test_a_session_with_contacts_renders_the_section_after_the_findings() -> None:
    report = render_report(with_contacts(), PACKAGE)
    headings = [line for line in report.splitlines() if line.startswith("## ")]

    assert headings.index("## Contacts") == headings.index("## Findings") + 1
    assert headings[headings.index("## Contacts") + 1] == "## Evidence Requests"


def test_the_section_states_the_counts_and_tables_every_contact() -> None:
    lines = section_of(render_report(with_contacts(), PACKAGE), "## Contacts")

    assert lines[:6] == [
        "## Contacts",
        "",
        "2 contacts and 2 interference findings from 4 detected groups. A contact is two parts "
        "touching at nominal size; it is listed so a line-to-line fit stays visible, and it is "
        "not an interference finding.",
        "",
        "| Contact | Parts | Configuration | Kind | Volume | Joint |",
        "|---|---|---|---|---|---|",
    ]
    assert lines[6:8] == [
        "| C-001 | cmp:0001, cmp:0002 | Default | zero volume | 0.0 mm3 | jnt:0001 |",
        "| C-002 | cmp:0001, cmp:0002 | Default | possible only | no volume | none |",
    ]


def test_the_contact_rows_carry_no_percent_sign() -> None:
    assert "%" not in "\n".join(section_of(render_report(with_contacts(), PACKAGE), "## Contacts"))


def test_a_session_without_contacts_renders_no_section() -> None:
    report = render_report(make_session(usage=None), PACKAGE)

    assert "## Contacts" not in report
    assert "contact" not in report.lower()


def test_one_contact_and_one_finding_are_spelled_in_the_singular() -> None:
    session = make_session(usage=None).model_copy(
        update={
            "findings": [interference_finding("F-101", "demonstrated")],
            "contacts": [contact("C-001", "zero_volume", 0.0, None)],
        }
    )
    package = build_package(
        interferences=[row("int:1", "boss/screws", 6.0), row("int:2", "pin/plate", 0.0)]
    )

    lines = section_of(render_report(session, package), "## Contacts")

    assert lines[2].startswith("1 contact and 1 interference finding from 2 detected groups. ")
