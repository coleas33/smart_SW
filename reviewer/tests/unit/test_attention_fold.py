"""The fold: one row for a repeated condition, and nothing written to the session (T018).

Twelve parts with the same feature outside a group is one condition, not twelve findings
to read; the "Start here" section would otherwise be five rows of the same sentence. So
before ranking, findings that share `check`, `status` and `severity` and name **disjoint**
subjects collapse into one row that lists every member (`contracts/attention.md` section 2,
FR-012).

Three rules make the collapse safe, and each has its own case below:

- **A shared subject is never a repetition.** Two findings that both name `cmp:0003` are
  two things about one part; folding them would hide one of them.
- **A needs-judgement check never folds.** Two press fits may be two different intents, and
  collapsing them would be a judgement the policy made silently (research R2.2).
- **The fold writes nothing.** `session.findings` and every `Finding.group` are equal
  before and after `rank()`, compared as model dumps rather than by identity, because a
  mutation that happened to produce an equal-looking object is still a rendering pass that
  wrote to the session (research R2.2, and `report/markdown.py`'s own docstring).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID, uuid5

import pytest

from swreview.findings import Finding
from swreview.ir.models import ComponentInstance, EvidencePackage
from swreview.report.attention import fold, rank
from swreview.report.session import ReviewSession, load_session
from tests.support.attention import (
    PART_COMPONENT,
    PIN_ONE,
    PIN_TWO,
    REVIEW_SESSION_FILE,
    CoverageSpec,
    FindingSpec,
    attention_package,
    build_attention_session,
)
from tests.support.packages import IDENTITY_TRANSFORM, build_package, persist_ref

NAMESPACE = UUID("7a1e6d64-1f2b-4c3a-9d5e-000000000018")

GROUPING = "rms.grouping.all_features_in_a_group"
"""A discipline rule: not in the needs-judgement set, so its findings may fold."""

INTERFERENCE = "interference.static"
"""A needs-judgement check: its findings never fold, however disjoint their subjects."""

TWELVE = 12
PART_IDS: tuple[str, ...] = tuple(f"cmp:1{number:03d}" for number in range(1, TWELVE + 1))
"""Twelve parts of one document, so a twelve-way fold has twelve disjoint subjects."""


def wide_package() -> EvidencePackage:
    """`build_package`'s minimal package with twelve instances of the housing document.

    `tests/support/attention.py`'s four-component assembly is the shape the two committed
    fixtures are written against and is not widened here: a thirteenth component would
    change every fixture byte. This package exists only for the fold's own arithmetic.
    """
    return build_package(
        components=[
            ComponentInstance(
                id=component_id,
                persist_ref=persist_ref(component_id),
                persist_ref_scope="doc:1",
                name=f"housing-{number}",
                full_path=f"housing-{number}",
                document_id="doc:2",
                parent_id=None,
                referenced_configuration="Default",
                transform=IDENTITY_TRANSFORM,
                suppression="resolved",
                is_fixed=number == 1,
                pattern_id=None,
                is_toolbox=False,
            )
            for number, component_id in enumerate(PART_IDS, start=1)
        ],
        holes=[],
        fasteners=[],
        gaps=[],
    )


def spec(check: str, components: Sequence[str], **fields: Any) -> FindingSpec:
    fields.setdefault("tool_result_ids", (0,))
    fields.setdefault("coverage_limits", ("measured in the Default configuration only.",))
    return FindingSpec(check=check, component_ids=tuple(components), **fields)


def session_of(
    name: str, specs: Sequence[FindingSpec], package: EvidencePackage | None = None
) -> ReviewSession:
    return build_attention_session(
        session_id=uuid5(NAMESPACE, name),
        findings=specs,
        coverage=CoverageSpec(),
        steps=("check_rms_part",),
        package=package if package is not None else attention_package(),
    )


def groups_of(session: ReviewSession) -> list[list[str]]:
    return [[finding.id for finding in group] for group in fold(session.findings)]


# --- 1. what folds ---------------------------------------------------------------------------


def test_twelve_equal_findings_on_twelve_parts_fold_into_one_row() -> None:
    session = session_of(
        "twelve-parts",
        [spec(GROUPING, (component_id,)) for component_id in PART_IDS],
        wide_package(),
    )

    ranking = rank(session)

    assert len(ranking.rows) == 1
    row = ranking.rows[0]
    assert row.finding_id == "F-001", "the survivor is the lowest finding id"
    assert row.member_finding_ids == [f"F-{number:03d}" for number in range(1, TWELVE + 1)]
    assert row.component_ids == sorted(PART_IDS)
    assert row.key.finding_id == "F-001"
    assert row.key.reach == 0, "twelve distinct components is the top of key 6, capped at three"


def test_a_single_finding_is_a_row_of_one() -> None:
    session = session_of("single", [spec(GROUPING, (PART_COMPONENT,))])

    ranking = rank(session)

    assert [row.member_finding_ids for row in ranking.rows] == [["F-001"]]


def test_the_survivors_title_is_the_rows_title() -> None:
    session = session_of(
        "titles",
        [
            spec(GROUPING, (PART_IDS[1],), title="the second part"),
            spec(GROUPING, (PART_IDS[0],), title="the first part"),
        ],
        wide_package(),
    )

    ranking = rank(session)

    assert ranking.rows[0].finding_id == "F-001"
    assert ranking.rows[0].title == "the second part", "F-001 is the survivor, title and all"


# --- 2. what does not fold ----------------------------------------------------------------


def test_one_differing_severity_makes_two_rows() -> None:
    session = session_of(
        "differing-severity",
        [
            *(spec(GROUPING, (component_id,)) for component_id in PART_IDS[:3]),
            spec(GROUPING, (PART_IDS[3],), severity="low"),
        ],
        wide_package(),
    )

    ranking = rank(session)

    assert [row.member_finding_ids for row in ranking.rows] == [
        ["F-001", "F-002", "F-003"],
        ["F-004"],
    ]


def test_one_differing_status_makes_two_rows() -> None:
    session = session_of(
        "differing-status",
        [
            *(spec(GROUPING, (component_id,)) for component_id in PART_IDS[:3]),
            spec(GROUPING, (PART_IDS[3],), status="suspected"),
        ],
        wide_package(),
    )

    ranking = rank(session)

    assert [row.member_finding_ids for row in ranking.rows] == [
        ["F-001", "F-002", "F-003"],
        ["F-004"],
    ]


def test_two_findings_sharing_a_component_never_fold() -> None:
    session = session_of(
        "shared-subject",
        [spec(GROUPING, (PART_COMPONENT,)), spec(GROUPING, (PART_COMPONENT, PIN_ONE))],
    )

    ranking = rank(session)

    assert [row.member_finding_ids for row in ranking.rows] == [["F-002"], ["F-001"]]


def test_a_shared_component_splits_a_run_of_otherwise_disjoint_findings() -> None:
    """The third finding reaches back to the first part, so it starts its own row."""
    session = session_of(
        "shared-in-the-middle",
        [
            spec(GROUPING, (PART_IDS[0],)),
            spec(GROUPING, (PART_IDS[1],)),
            spec(GROUPING, (PART_IDS[0],)),
            spec(GROUPING, (PART_IDS[2],)),
        ],
        wide_package(),
    )

    assert groups_of(session) == [["F-001", "F-002", "F-004"], ["F-003"]]


def test_two_interference_findings_with_disjoint_subjects_never_fold() -> None:
    """FR-012: two press fits may be two intents, so a needs-judgement check never folds."""
    session = session_of(
        "two-interferences",
        [
            spec(INTERFERENCE, (PART_COMPONENT, PIN_ONE)),
            spec(INTERFERENCE, (PIN_TWO,)),
        ],
    )

    ranking = rank(session)

    assert [row.member_finding_ids for row in ranking.rows] == [["F-001"], ["F-002"]]


def test_twelve_needs_judgement_findings_on_twelve_parts_stay_twelve_rows() -> None:
    session = session_of(
        "twelve-interferences",
        [spec(INTERFERENCE, (component_id,)) for component_id in PART_IDS],
        wide_package(),
    )

    assert groups_of(session) == [[f"F-{number:03d}"] for number in range(1, TWELVE + 1)]


def test_two_different_checks_never_fold() -> None:
    session = session_of(
        "two-checks",
        [
            spec(GROUPING, (PART_IDS[0],)),
            spec("rms.folders.present", (PART_IDS[1],)),
        ],
        wide_package(),
    )

    assert groups_of(session) == [["F-001"], ["F-002"]]


# --- 3. the fold is reproducible from the session alone --------------------------------------


def test_the_fold_is_the_same_whatever_order_the_findings_arrived_in() -> None:
    """FR-014: `fold` sorts by finding id, so the survivor cannot depend on arrival order.

    The same eight findings, re-ordered in place: a greedy fold that walked the list as it
    found it would put a different member first and hand the row a different title.
    """
    package = wide_package()
    specs = [
        *(spec(GROUPING, (component_id,)) for component_id in PART_IDS[:4]),
        spec(GROUPING, (PART_IDS[0],)),
        *(spec(INTERFERENCE, (component_id,)) for component_id in PART_IDS[4:6]),
        spec("rms.folders.present", (PART_IDS[6],), status="suspected", severity="low"),
    ]
    forward = session_of("arrival-order", specs, package)
    shuffled = session_of("arrival-order", specs, package)
    shuffled.findings = [shuffled.findings[index] for index in (5, 0, 7, 2, 6, 1, 4, 3)]

    assert groups_of(forward) == groups_of(shuffled)
    assert rank(forward).model_dump_json() == rank(shuffled).model_dump_json()


# --- 4. the fold writes nothing ----------------------------------------------------------------


def dumps(findings: Sequence[Finding]) -> list[dict[str, Any]]:
    return [finding.model_dump(mode="json") for finding in findings]


FOLDING_CASES: tuple[tuple[str, int, list[FindingSpec]], ...] = (
    (
        "a twelve-way fold",
        1,
        [spec(GROUPING, (component_id,)) for component_id in PART_IDS],
    ),
    (
        "a fold split by a shared subject",
        2,
        [spec(GROUPING, (PART_IDS[0],)), spec(GROUPING, (PART_IDS[0], PART_IDS[1]))],
    ),
    (
        "two needs-judgement findings that may not fold",
        2,
        [spec(INTERFERENCE, (PART_IDS[0],)), spec(INTERFERENCE, (PART_IDS[1],))],
    ),
)
"""`(what the case is, how many rows it must produce, the findings)`.

Each one exercises a different branch of the fold, and each must leave the session it was
ranked from untouched - which is the only assertion below.
"""


@pytest.mark.parametrize(
    ("what", "rows", "specs"), FOLDING_CASES, ids=[case[0] for case in FOLDING_CASES]
)
def test_ranking_leaves_the_sessions_findings_deeply_equal(
    what: str, rows: int, specs: list[FindingSpec]
) -> None:
    session = session_of(what, specs, wide_package())
    before = dumps(session.findings)

    ranking = rank(session)

    assert len(ranking.rows) == rows, what
    assert dumps(session.findings) == before
    assert [finding.group for finding in session.findings] == [None] * len(specs)


def test_ranking_the_committed_review_leaves_its_findings_and_its_file_alone() -> None:
    """The fixture is the real shape, and `attention.json` is written beside `session.json`."""
    session = load_session(REVIEW_SESSION_FILE)
    before = dumps(session.findings)
    ids_before = [finding.id for finding in session.findings]
    file_before = REVIEW_SESSION_FILE.read_bytes()

    rank(session)

    assert dumps(session.findings) == before
    assert [finding.id for finding in session.findings] == ids_before
    assert all(finding.group is None for finding in session.findings)
    assert REVIEW_SESSION_FILE.read_bytes() == file_before, "ranking wrote to the session file"


def test_fold_returns_the_findings_themselves_and_not_copies() -> None:
    """A row built from a copy could drift from the session it claims to describe, and the
    deep-equality assertions above would go on passing while it did."""
    session = session_of("identity", [spec(GROUPING, (PART_COMPONENT,))])

    groups = fold(session.findings)

    assert groups[0][0] is session.findings[0]


def test_every_finding_appears_in_exactly_one_group() -> None:
    session = session_of(
        "partition",
        [
            *(spec(GROUPING, (component_id,)) for component_id in PART_IDS[:4]),
            spec(GROUPING, (PART_IDS[0],)),
            spec(INTERFERENCE, (PART_IDS[5], PART_IDS[6])),
            spec("rms.folders.present", (PART_IDS[7],), status="suspected", severity="low"),
        ],
        wide_package(),
    )

    groups = fold(session.findings)

    members = [finding.id for group in groups for finding in group]
    assert sorted(members) == sorted(finding.id for finding in session.findings)
    assert len(members) == len(set(members))
