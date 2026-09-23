"""SC-006 on the replay (feature 010 T097): the three mechanical checks cost no model round.

`check_joints`, `check_mass_material` and `check_hygiene` take no argument and join checks
first through `CODE_FIRST_CHECKS` (010 FR-026). Replaying a recorded review with checks first
requested (008 `contracts/replay.md`) must show each of them as a **pre-run step** - a real
step of the session, ok, with its line under "Evaluated:" in the opening digest, numbered
before the model's first call - and the model's rounds exactly as the recording's: the same
rounds are played whether or not the three ran, the report prices no call to any of them, and
none of their results rides in any request as a tool message. What they find is reported as
added, which is how the replay shows a finding the recording could not have had.

The recordings predate feature 010 and were made with every lever off, so as recorded (pass A)
nothing runs before the first turn and none of the three runs at all.

The big assembly is the acceptance (010 quickstart Scenario 12); the two small runs say the
same on a package with two interference groups and one with none. No finding count is pinned:
what the checks find is their own tests' business, and this module is about where they run.
Every replay of a committed fixture is graded with `config/standards.example.yaml`, as 008's
acceptance is (`test_replay_fixtures.py`).
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from swreview.agent.settings import MODEL_VIEW_OFF, EfficiencySettings
from swreview.benchmark.recording import read_recording
from swreview.benchmark.replay import (
    ReplayPasses,
    ReplayReport,
    replay_passes,
    report_of,
    subject_of,
)
from swreview.findings import Finding, finding_subject_key
from swreview.prerun import EVALUATED_HEADER, NOT_EVALUATED_HEADER

pytestmark = pytest.mark.usefixtures("vocabulary")

REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLE_PROFILE = REPO_ROOT / "config" / "standards.example.yaml"
FIXTURES = REPO_ROOT / "reviewer" / "tests" / "fixtures" / "replay"
NAMES = ("big-assembly", "small-assembly-a", "small-assembly-b")

MECHANICAL_CHECKS = ("check_joints", "check_mass_material", "check_hygiene")
"""The three feature 010 adds, in `CODE_FIRST_CHECKS` order; named, because they are what
SC-006 is about."""

CHECKS_FIRST = EfficiencySettings(prerun_checks=True)
"""Checks first alone, model view off: the arm that isolates what the pre-run adds."""


@pytest.fixture(scope="module", params=NAMES)
def passes(
    request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory
) -> ReplayPasses:
    """Both passes of one recorded run, checks first requested, played once per module."""
    name = request.param
    return replay_passes(
        read_recording(FIXTURES / name),
        tmp_path_factory.mktemp(name),
        requested=(CHECKS_FIRST, MODEL_VIEW_OFF),
        standards_profile=EXAMPLE_PROFILE,
    )


@pytest.fixture(scope="module")
def report(passes: ReplayPasses) -> ReplayReport:
    """The same two passes priced and compared, once per recorded run."""
    return report_of(passes)


def mechanical_steps(passes: ReplayPasses) -> list[int]:
    """The requested pass's steps that called one of the three, wherever they fell."""
    return [s.index for s in passes.second.session.steps if s.tool in MECHANICAL_CHECKS]


def findings_of(passes: ReplayPasses, steps: list[int]) -> list[Finding]:
    return [
        finding
        for finding in passes.second.session.findings
        if set(finding.tool_result_ids) & set(steps)
    ]


# --- as recorded: nothing before the first turn ------------------------------------------


def test_as_recorded_none_of_the_three_runs(passes: ReplayPasses) -> None:
    assert passes.as_recorded == EfficiencySettings(), (
        "the fixtures were recorded with every lever off; a fixture recorded otherwise "
        "needs this module's baseline restated"
    )
    assert passes.first.setup_steps == 0
    assert not [s for s in passes.first.session.steps if s.tool in MECHANICAL_CHECKS]


# --- checks first: three pre-run steps ------------------------------------------------------


def test_each_check_is_one_ok_pre_run_step_in_registration_order(passes: ReplayPasses) -> None:
    second = passes.second
    setup = second.session.steps[: second.setup_steps]
    tools = [step.tool for step in setup]
    ours = [step for step in setup if step.tool in MECHANICAL_CHECKS]

    assert [step.tool for step in ours] == list(MECHANICAL_CHECKS)
    assert [step.status for step in ours] == ["ok"] * len(MECHANICAL_CHECKS)
    assert [step.error for step in ours] == [None] * len(MECHANICAL_CHECKS)
    first = ours[0].index
    assert [step.index for step in ours] == list(range(first, first + len(MECHANICAL_CHECKS)))
    groups = [i for i, tool in enumerate(tools) if tool == "check_interference_group"]
    assert all(i < first for i in groups), "they run after every interference group"
    assert first + len(MECHANICAL_CHECKS) <= tools.index("check_standards")
    assert mechanical_steps(passes) == [step.index for step in ours], "and never again"


def test_the_opening_digest_lists_each_as_evaluated(passes: ReplayPasses) -> None:
    opening = passes.second.opening
    evaluated = opening.split(EVALUATED_HEADER, 1)[1].split(NOT_EVALUATED_HEADER, 1)[0]

    for tool in MECHANICAL_CHECKS:
        lines = [line for line in evaluated.splitlines() if line.startswith(f"  {tool}(")]
        assert len(lines) == 1, (tool, lines)
        assert lines[0].startswith(f"  {tool}() -> ok, "), lines[0]


# --- and no model round ---------------------------------------------------------------------


def test_the_model_plays_exactly_the_recorded_rounds(passes: ReplayPasses) -> None:
    first, second = passes.first, passes.second

    assert [(r.turn, r.index) for r in second.rounds] == [(r.turn, r.index) for r in first.rounds]
    assert [[(c.tool, c.arguments) for c in r.calls] for r in second.rounds] == [
        [(c.tool, c.arguments) for c in r.calls] for r in first.rounds
    ]


def test_no_model_call_is_one_of_them_and_every_model_call_follows_them(
    passes: ReplayPasses,
) -> None:
    second = passes.second
    calls = [call for played in second.rounds for call in played.calls]

    assert calls, "a recording with no model call would say nothing here"
    assert not [call for call in calls if call.tool in MECHANICAL_CHECKS]
    assert calls[0].step == second.setup_steps
    assert all(step < second.setup_steps for step in mechanical_steps(passes))


def test_no_request_carries_their_results_as_a_tool_message(passes: ReplayPasses) -> None:
    """They reach the model through the opening digest only, never as a round's result."""
    carried = [
        (played.turn, played.index, message["name"])
        for played in passes.second.rounds
        for message in played.history
        if message.get("role") == "tool" and message.get("name") in MECHANICAL_CHECKS
    ]

    assert carried == []


def test_the_report_prices_no_call_to_them_and_no_extra_round(
    passes: ReplayPasses, report: ReplayReport
) -> None:
    recorded_main = sum(len(turn.main_rounds) for turn in passes.recording.turns)
    priced_main = sum(1 for r in report.rounds if r.kind == "main")

    assert not [c for r in report.rounds for c in r.calls if c.tool in MECHANICAL_CHECKS]
    assert priced_main == recorded_main == len(passes.second.rounds)


def test_what_they_record_is_reported_added(passes: ReplayPasses, report: ReplayReport) -> None:
    """The replay shows their verdicts, as findings the recording could not have had."""
    theirs = Counter(
        (finding.check, subject_of(finding_subject_key(finding)))
        for finding in findings_of(passes, mechanical_steps(passes))
    )
    added = Counter((item.check, item.subject) for item in report.findings.added)

    assert theirs, "each recorded run gives the three something to find (hygiene at least)"
    assert theirs - added == Counter()
    assert report.findings.lost == []
