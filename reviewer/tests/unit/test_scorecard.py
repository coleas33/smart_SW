"""Unit tests for T093: scoring a benchmark run against its answer keys.

Matching rule under test (see `swreview.benchmark.scorecard` module docstring): a finding
matches a known defect or correct condition when its `check` equals the target's `check`
(exact) or shares the same before-the-last-dot prefix (e.g. `fastener.bottoming` against
`fastener.*`), *and* `component_ids` intersect. `unresolved` findings are counted
separately and never as false alarms; `checked_within_scope` findings count nowhere.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from jsonschema import Draft202012Validator

from swreview.benchmark.answer_key import AnswerKey, CorrectCondition, KnownDefect
from swreview.benchmark.scorecard import (
    check_prefix,
    classify_match,
    render_scorecard_md,
    score_run,
)
from swreview.benchmark.sets import BenchmarkPackageRef, BenchmarkSet
from swreview.findings import build_finding
from swreview.report.session import ReviewSession, Timing, save_session
from tests.support.contracts import load_contract
from tests.support.packages import build_package

PACKAGE = build_package()


def make_finding(**overrides: object) -> object:
    fields: dict[str, object] = {
        "finding_id": "F-001",
        "check": "fastener.bottoming",
        "title": "t",
        "status": "suspected",
        "severity": "medium",
        "package": PACKAGE,
        "configuration": "Default",
        "observed": "o",
        "requirement": "r",
        "recommended_action": "a",
        "component_ids": ["cmp:0001"],
    }
    fields.update(overrides)
    return build_finding(**fields)  # type: ignore[arg-type]


def write_answer_key(answer_keys_dir: Path, answer_key: AnswerKey) -> None:
    payload = answer_key.model_dump_json()
    (answer_keys_dir / f"{answer_key.package_id}.json").write_text(payload, encoding="utf-8")


def make_session(session_id: UUID, findings: list[object], timing: Timing) -> ReviewSession:
    return ReviewSession(
        session_id=session_id,
        package_id=PACKAGE.package_id,
        design_id=PACKAGE.design.design_id,
        started_at=datetime(2026, 9, 12, 9, 0, tzinfo=UTC),
        ended_at=datetime(2026, 9, 12, 9, 30, tzinfo=UTC),
        model="claude-opus-5",
        findings=findings,
        timing=timing,
    )


# --- matching rule -----------------------------------------------------------------


def test_check_prefix_splits_on_the_last_dot() -> None:
    assert check_prefix("fastener.bottoming") == "fastener"
    assert check_prefix("fastener.*") == "fastener"
    assert check_prefix("fastener") == "fastener"


def test_classify_match_is_exact_when_checks_are_identical() -> None:
    finding = make_finding(check="fastener.bottoming", component_ids=["cmp:0001"])

    assert classify_match(finding, "fastener.bottoming", ["cmp:0001"]) == "exact"


def test_classify_match_is_prefix_for_a_wildcard_family() -> None:
    finding = make_finding(check="fastener.bottoming", component_ids=["cmp:0001"])

    assert classify_match(finding, "fastener.*", ["cmp:0001"]) == "prefix"


def test_classify_match_prefers_exact_over_prefix() -> None:
    finding = make_finding(check="fastener.bottoming", component_ids=["cmp:0001"])

    # Both would resolve to the same prefix; exact must be what is reported.
    assert classify_match(finding, "fastener.bottoming", ["cmp:0001"]) == "exact"


def test_classify_match_is_none_without_a_component_overlap() -> None:
    finding = make_finding(check="fastener.bottoming", component_ids=["cmp:0001"])

    assert classify_match(finding, "fastener.bottoming", ["cmp:0002"]) is None


def test_classify_match_is_none_for_an_unrelated_check() -> None:
    finding = make_finding(check="fastener.bottoming", component_ids=["cmp:0001"])

    assert classify_match(finding, "drawing.manufacturing_inputs", ["cmp:0001"]) is None


# --- score_run: one package exercising every classification ------------------------


def build_scoring_fixture(
    tmp_path: Path, *, held_out: bool = True
) -> tuple[Path, Path, BenchmarkSet]:
    run_dir = tmp_path / "run"
    answer_keys_dir = tmp_path / "benchmarks" / "answer_keys"
    answer_keys_dir.mkdir(parents=True)

    answer_key = AnswerKey(
        package_id="pkg-a",
        known_defects=[
            KnownDefect(
                id="D-1",
                check="fastener.bottoming",
                component_ids=["cmp:0001"],
                description="d1",
            ),
            KnownDefect(
                id="D-2",
                check="drawing.manufacturing_inputs",
                component_ids=["cmp:0002"],
                description="d2",
            ),
            KnownDefect(
                id="D-3", check="fastener.*", component_ids=["cmp:0002"], description="d3"
            ),
        ],
        correct_conditions=[
            CorrectCondition(check="fit.size_only", component_ids=["cmp:0001"], description="ok"),
        ],
    )
    write_answer_key(answer_keys_dir, answer_key)

    findings = [
        make_finding(
            finding_id="F-001",
            check="fastener.bottoming",
            status="suspected",
            component_ids=["cmp:0001"],
        ),
        make_finding(
            finding_id="F-002",
            check="fastener.thread_mismatch",
            status="suspected",
            component_ids=["cmp:0002"],
        ),
        make_finding(
            finding_id="F-003",
            check="tolerance.stack",
            status="demonstrated",
            component_ids=["cmp:0001"],
            tool_result_ids=[0],
        ),
        make_finding(
            finding_id="F-004",
            check="fit.size_only",
            status="suspected",
            component_ids=["cmp:0001"],
        ),
        make_finding(
            finding_id="F-005",
            check="fastener.engagement",
            status="unresolved",
            component_ids=["cmp:0002"],
            coverage_limits=["gap: usable thread depth unknown"],
        ),
        make_finding(
            finding_id="F-006",
            check="mate.alignment",
            status="checked_within_scope",
            component_ids=["cmp:0001"],
            tool_result_ids=[0],
        ),
    ]
    timing = Timing(
        baseline_minutes=90.0,
        assisted_supervision_minutes=10.0,
        assisted_verification_minutes=8.0,
        false_alarm_handling_minutes=2.0,
        unattended_runtime_minutes=25.0,
    )
    session = make_session(UUID("33333333-4444-4555-8666-777777777777"), findings, timing)
    save_package_dir = run_dir / "pkg-a"
    save_session(session, save_package_dir / "session.json")

    benchmark_set = BenchmarkSet(
        name="pilot",
        packages=[BenchmarkPackageRef(package_id="pkg-a", path=Path("unused"), held_out=held_out)],
    )
    return run_dir, answer_keys_dir, benchmark_set


def test_score_run_classifies_findings_by_the_matching_rule(tmp_path: Path) -> None:
    run_dir, answer_keys_dir, benchmark_set = build_scoring_fixture(tmp_path)

    scorecard = score_run(run_dir, answer_keys_dir, benchmark_set)

    score = scorecard.per_package[0]
    assert score.package_id == "pkg-a"
    assert score.valid_findings == 2  # F-001 (exact), F-002 (prefix)
    assert score.missed_known_defects == 1  # D-2
    assert score.matched_defect_ids == ["D-1", "D-3"]
    assert score.missed_defect_ids == ["D-2"]
    assert score.false_alarms == 1
    assert score.false_alarm_finding_ids == ["F-003"]
    assert score.unresolved_count == 1


def test_score_run_computes_timing_fields(tmp_path: Path) -> None:
    run_dir, answer_keys_dir, benchmark_set = build_scoring_fixture(tmp_path)

    scorecard = score_run(run_dir, answer_keys_dir, benchmark_set)

    score = scorecard.per_package[0]
    assert score.baseline_minutes == pytest.approx(90.0)
    assert score.assisted_minutes == pytest.approx(20.0)
    assert score.unattended_runtime_minutes == pytest.approx(25.0)
    assert score.net_saved_minutes == pytest.approx(70.0)


def test_score_run_recall_is_scoped_to_held_out_packages(tmp_path: Path) -> None:
    run_dir, answer_keys_dir, benchmark_set = build_scoring_fixture(tmp_path, held_out=True)

    scorecard = score_run(run_dir, answer_keys_dir, benchmark_set)

    # 2 matched of 3 known defects, all in the one held-out package.
    assert scorecard.aggregate.recall == pytest.approx(2 / 3)
    assert scorecard.aggregate.held_out_packages == 1


def test_score_run_recall_ignores_defects_from_non_held_out_packages(tmp_path: Path) -> None:
    run_dir, answer_keys_dir, benchmark_set = build_scoring_fixture(tmp_path, held_out=False)

    scorecard = score_run(run_dir, answer_keys_dir, benchmark_set)

    assert scorecard.aggregate.recall is None
    assert scorecard.aggregate.held_out_packages == 0


def test_score_run_false_alarm_rate(tmp_path: Path) -> None:
    run_dir, answer_keys_dir, benchmark_set = build_scoring_fixture(tmp_path)

    scorecard = score_run(run_dir, answer_keys_dir, benchmark_set)

    assert scorecard.aggregate.false_alarm_rate == pytest.approx(1 / 3)


def test_recall_is_none_when_a_held_out_package_has_no_known_defects(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    answer_keys_dir = tmp_path / "benchmarks" / "answer_keys"
    answer_keys_dir.mkdir(parents=True)
    answer_key = AnswerKey(package_id="pkg-b", known_defects=[], correct_conditions=[])
    write_answer_key(answer_keys_dir, answer_key)
    timing = Timing(
        baseline_minutes=None,
        assisted_supervision_minutes=0.0,
        assisted_verification_minutes=0.0,
        false_alarm_handling_minutes=0.0,
        unattended_runtime_minutes=1.0,
    )
    session = make_session(UUID("44444444-5555-4666-8777-888888888888"), [], timing)
    save_session(session, run_dir / "pkg-b" / "session.json")
    benchmark_set = BenchmarkSet(
        name="pilot",
        packages=[BenchmarkPackageRef(package_id="pkg-b", path=Path("unused"), held_out=True)],
    )

    scorecard = score_run(run_dir, answer_keys_dir, benchmark_set)

    assert scorecard.aggregate.recall is None
    assert scorecard.aggregate.false_alarm_rate is None


def test_false_alarm_rate_is_none_with_zero_findings(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    answer_keys_dir = tmp_path / "benchmarks" / "answer_keys"
    answer_keys_dir.mkdir(parents=True)
    answer_key = AnswerKey(package_id="pkg-c", known_defects=[], correct_conditions=[])
    write_answer_key(answer_keys_dir, answer_key)
    timing = Timing(
        baseline_minutes=30.0,
        assisted_supervision_minutes=5.0,
        assisted_verification_minutes=0.0,
        false_alarm_handling_minutes=0.0,
        unattended_runtime_minutes=1.0,
    )
    session = make_session(UUID("55555555-6666-4777-8888-999999999999"), [], timing)
    save_session(session, run_dir / "pkg-c" / "session.json")
    benchmark_set = BenchmarkSet(
        name="pilot",
        packages=[BenchmarkPackageRef(package_id="pkg-c", path=Path("unused"), held_out=False)],
    )

    scorecard = score_run(run_dir, answer_keys_dir, benchmark_set)

    assert scorecard.aggregate.false_alarm_rate is None


# --- distribution, median, and packages without timing ------------------------------


def test_distribution_matches_per_package_order(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    answer_keys_dir = tmp_path / "benchmarks" / "answer_keys"
    answer_keys_dir.mkdir(parents=True)
    session_ids = [
        UUID("66666666-7777-4888-8999-aaaaaaaaaaaa"),
        UUID("77777777-8888-4999-8aaa-bbbbbbbbbbbb"),
        UUID("88888888-9999-4aaa-8bbb-cccccccccccc"),
    ]
    packages: list[BenchmarkPackageRef] = []
    expected_net_saved: list[float | None] = []
    for (name, baseline), session_id in zip(
        (("pkg-x", 100.0), ("pkg-y", None), ("pkg-z", 40.0)), session_ids, strict=True
    ):
        answer_key = AnswerKey(package_id=name, known_defects=[], correct_conditions=[])
        write_answer_key(answer_keys_dir, answer_key)
        timing = Timing(
            baseline_minutes=baseline,
            assisted_supervision_minutes=5.0,
            assisted_verification_minutes=5.0,
            false_alarm_handling_minutes=0.0,
            unattended_runtime_minutes=1.0,
        )
        session = make_session(session_id, [], timing)
        save_session(session, run_dir / name / "session.json")
        packages.append(BenchmarkPackageRef(package_id=name, path=Path("unused"), held_out=False))
        expected_net_saved.append(None if baseline is None else baseline - 10.0)
    benchmark_set = BenchmarkSet(name="pilot", packages=packages)

    scorecard = score_run(run_dir, answer_keys_dir, benchmark_set)

    assert [p.package_id for p in scorecard.per_package] == ["pkg-x", "pkg-y", "pkg-z"]
    assert len(scorecard.distribution) == len(expected_net_saved)
    for actual, expected in zip(scorecard.distribution, expected_net_saved, strict=True):
        if expected is None:
            assert actual is None
        else:
            assert actual == pytest.approx(expected)
    assert scorecard.aggregate.packages_with_timing == 2
    assert scorecard.aggregate.median_net_saved_minutes == pytest.approx(60.0)  # median(90, 30)


# --- schema validation ---------------------------------------------------------------


def test_scorecard_validates_against_the_contract(tmp_path: Path) -> None:
    run_dir, answer_keys_dir, benchmark_set = build_scoring_fixture(tmp_path)

    scorecard = score_run(run_dir, answer_keys_dir, benchmark_set)
    payload = scorecard.model_dump(mode="json")

    validator = Draft202012Validator(
        load_contract("scorecard.schema.json"), format_checker=Draft202012Validator.FORMAT_CHECKER
    )
    errors = sorted(validator.iter_errors(payload), key=lambda e: list(e.absolute_path))

    assert errors == [], [f"{list(e.absolute_path)}: {e.message}" for e in errors]


def test_render_scorecard_md_lists_each_package_and_the_aggregate(tmp_path: Path) -> None:
    run_dir, answer_keys_dir, benchmark_set = build_scoring_fixture(tmp_path)
    scorecard = score_run(run_dir, answer_keys_dir, benchmark_set)

    rendered = render_scorecard_md(scorecard)

    assert "pkg-a" in rendered
    assert "## Aggregate" in rendered
    assert "recall" in rendered.lower()
    assert "false-alarm rate" in rendered.lower() or "false alarm" in rendered.lower()
