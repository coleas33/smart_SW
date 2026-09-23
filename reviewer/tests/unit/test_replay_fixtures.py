"""The User Story 1 acceptance on the committed fixtures (008 T022, SC-001).

Each fixture is shaped like one recorded review - the big assembly and two runs of the small
one - and replaying it with the settings it was recorded with must reproduce every recorded
round within 1% and the finding set exactly: every recorded finding replayed, or - for a group
feature 010 judges touching - reclassified as a contact, counted per fixture. Every replay of a
committed fixture is graded with `config/standards.example.yaml`, the profile the pilot ran
(research R2.10). The payload shapes that make later savings measurable are pinned too: the
part check's 866 feature rows and the 110 mate entities with their persistent references.

User Story 2 (T049) and User Story 3 (T078) add their acceptance: checks first alone, then the
pane defaults - checks first, the slim view, stubs after two rounds - under a million requested
tokens on the big fixture with no recorded finding lost, the same findings with the view on and
off, every step's full result stored, and both prune ages priced for the owner.

User Story 4 (T086) adds the follow-up and the regrouped estimate, priced with the pane
defaults of the provider the recordings ran on (OpenAI, so parallel calls are on): the big
fixture's follow-up question under 30,000 input tokens (SC-004), and each small fixture's
labelled regrouped estimate under 300,000 with its strict figure below the recorded total
(SC-003 as amended).
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Mapping
from functools import cache
from pathlib import Path
from typing import Any

import pytest

from swreview.agent.providers import ProviderName
from swreview.agent.providers.pruning import PRUNED_NOTE, prunable, result_stub
from swreview.agent.settings import (
    MODEL_VIEW_OFF,
    EfficiencySettings,
    ModelViewSettings,
    pane_defaults,
)
from swreview.benchmark.recording import read_recording
from swreview.benchmark.replay import (
    ReplayPasses,
    ReplayReport,
    Requested,
    render_replay_lines,
    replay,
    replay_passes,
    report_of,
    request_messages,
)
from swreview.findings import finding_subject_key
from swreview.ir.loader import load_package
from swreview.prerun import DIGEST_HEADER
from swreview.tools.checks_interference import groups_of
from swreview.tools.context import context_for
from swreview.tools.registry import TOOL_RESULTS_DIR_NAME, ToolRegistry

pytestmark = pytest.mark.usefixtures("vocabulary")

REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLE_PROFILE = REPO_ROOT / "config" / "standards.example.yaml"
FIXTURES = REPO_ROOT / "reviewer" / "tests" / "fixtures" / "replay"
NAMES = ("big-assembly", "small-assembly-a", "small-assembly-b")
TOLERANCE = 0.01


@cache
def as_recorded(name: str) -> ReplayReport:
    """The fixture replayed with its recorded settings (all off), graded with the example."""
    return replay(
        FIXTURES / name,
        requested=(EfficiencySettings(), MODEL_VIEW_OFF),
        standards_profile=EXAMPLE_PROFILE,
    )


@pytest.mark.parametrize("name", NAMES)
def test_every_round_is_within_one_percent_of_the_recorded_input(name: str) -> None:
    report = as_recorded(name)

    worst = max(
        abs(r.as_recorded_input - r.recorded_input) / r.recorded_input for r in report.rounds
    )
    assert worst < TOLERANCE, f"{name}: worst round {worst:.4%}"
    assert abs(report.totals.as_recorded - report.totals.recorded) / report.totals.recorded < (
        TOLERANCE
    )


RECLASSIFIED = {"big-assembly": 3, "small-assembly-a": 2, "small-assembly-b": 0}
"""Recorded `interference.static` findings on touching groups (0.0 mm3), which feature 010
judges contacts: the replay names each one reclassified rather than lost (010 T094-T095)."""


@pytest.mark.parametrize("name", NAMES)
def test_the_finding_set_is_exact(name: str) -> None:
    findings = as_recorded(name).findings

    assert findings.lost == []
    assert findings.added == []
    assert findings.not_replayable == []
    assert len(findings.reclassified) == RECLASSIFIED[name]
    assert {item.check for item in findings.reclassified} <= {"interference.static"}
    assert findings.recorded == findings.replayed + RECLASSIFIED[name]


def test_the_big_assembly_has_the_live_call_and_three_touching_groups_estimated() -> None:
    """One estimated round was the live call alone until feature 010. The three touching
    groups judged after it are contacts now, so their results differ from the recording; a
    replay cannot tell that difference from anything the live call did, so each of their
    rounds is estimated too. Those are exactly the three reclassified findings' steps."""
    report = as_recorded("big-assembly")

    estimated = [r for r in report.rounds if r.estimated]
    assert len(estimated) == 4
    calls = [c for r in estimated for c in r.calls if c.class_ == "estimated"]
    assert [c.tool for c in calls] == ["bridge_interference", *["check_interference_group"] * 3]
    assert [c.step for c in calls[1:]] == [item.step for item in report.findings.reclassified]
    assert report.totals.estimated_rounds == 4
    assert report.totals.lower_bound_rounds == 0


def test_the_big_assembly_carries_one_presentation_round() -> None:
    report = as_recorded("big-assembly")

    assert report.totals.carried_rounds == 1
    assert [r.kind for r in report.rounds].count("presentation") == 1


def test_the_big_assembly_recorded_total_is_twelve_point_four_million() -> None:
    total = as_recorded("big-assembly").totals.recorded

    assert abs(total - 12_400_000) / 12_400_000 < TOLERANCE


# --- the User Story 2 acceptance: checks first alone (008 T049) ------------------------------

CHECKS_FIRST = EfficiencySettings(prerun_checks=True)


@cache
def checks_first(name: str) -> ReplayReport:
    """The fixture replayed with checks first alone requested (model view off)."""
    return replay(
        FIXTURES / name, requested=(CHECKS_FIRST, MODEL_VIEW_OFF), standards_profile=EXAMPLE_PROFILE
    )


@pytest.fixture(scope="module")
def big_checks_first(tmp_path_factory: pytest.TempPathFactory) -> ReplayPasses:
    """Both passes of the big fixture with checks first requested, the folders kept."""
    return replay_passes(
        read_recording(FIXTURES / "big-assembly"),
        tmp_path_factory.mktemp("big-checks-first"),
        requested=(CHECKS_FIRST, MODEL_VIEW_OFF),
        standards_profile=EXAMPLE_PROFILE,
    )


@pytest.mark.parametrize("name", NAMES)
def test_checks_first_alone_loses_no_recorded_finding(name: str) -> None:
    findings = checks_first(name).findings

    assert findings.lost == []
    assert findings.not_replayable == []


def test_checks_first_cuts_the_big_assembly() -> None:
    """The cut on every recorded run is asserted with the pane defaults (T078, T086):
    checks first alone adds its digest to every round's prefix, which a small run may not
    repay, but the big one resent a 205k-token check result about thirty times."""
    report = checks_first("big-assembly")

    assert report.totals.requested < report.totals.as_recorded


def test_the_recorded_rms_calls_are_answered_from_checks() -> None:
    report = checks_first("big-assembly")

    rms = [c for r in report.rounds for c in r.calls if c.tool.startswith("check_rms_")]
    assert rms
    assert {c.class_ for c in rms} == {"answered_from_checks"}
    assert all(c.reason and c.reason.startswith("the pre-run ran this call at step ") for c in rms)


def test_every_group_is_judged_once_offline(big_checks_first: ReplayPasses) -> None:
    """SC-006 offline: every group the package holds is judged - one finding or, since
    feature 010, one contact - against 6 of 113 on the recorded run."""
    session = big_checks_first.second.session
    groups = {g.group_key for g in groups_of(load_package(FIXTURES / "big-assembly").package)}
    judged = [
        f.calculation.inputs["group_key"]
        for f in session.findings
        if f.check == "interference.static" and f.calculation is not None
    ] + [c.group_key for c in session.contacts]

    assert len(groups) == 113
    assert sorted(judged) == sorted(groups)


def test_the_opening_is_the_digest_with_the_family_counted_and_no_rms_id(
    big_checks_first: ReplayPasses,
) -> None:
    opening = big_checks_first.second.opening
    session = big_checks_first.second.session

    assert DIGEST_HEADER in opening
    rms_ids = {f.id for f in session.findings if f.check.startswith("rms.")}
    assert rms_ids
    assert not rms_ids & set(re.findall(r"\bF-\d+\b", opening))
    [family_line] = [
        line for line in opening.splitlines() if line.startswith("  modelling practice:")
    ]
    assert f"{len(rms_ids)} findings across" in family_line


def test_the_rms_verdicts_equal_the_recordings(big_checks_first: ReplayPasses) -> None:
    recorded = Counter(
        finding_subject_key(item.finding)
        for item in big_checks_first.recording.findings
        if item.finding.check.startswith("rms.")
    )
    requested = Counter(
        finding_subject_key(finding)
        for finding in big_checks_first.second.session.findings
        if finding.check.startswith("rms.")
    )

    assert requested == recorded


def test_the_big_assembly_keeps_the_recorded_payload_shapes() -> None:
    package = load_package(FIXTURES / "big-assembly").package
    dispatch = ToolRegistry().dispatch(context_for(package))

    part = dispatch.call("check_rms_part", {"document_id": None}).payload
    mates = dispatch.call("list_mates", {"component_id": None}).payload

    assert sum(len(rows) for rows in part["subjects"].values()) == 866
    entities = [entity for mate in mates["result"] for entity in mate["entities"]]
    assert len(entities) == 110
    assert all(entity["persist_ref"] for entity in entities)


# --- the User Story 3 acceptance: the pane defaults (008 T078) -------------------------------

MILLION = 1_000_000
"""SC-002: the big fixture's requested input with the pane defaults stays below this."""


def pane_request(name: str, prune_after: int = 2) -> Requested:
    """What `swreview benchmark replay` requests by default for this fixture's provider."""
    pane = pane_defaults(ProviderName(read_recording(FIXTURES / name).provider))
    view = ModelViewSettings(
        payload_slimming=pane.model_view.payload_slimming,
        history_pruning=pane.model_view.history_pruning,
        prune_after_rounds=prune_after,
    )
    return pane.efficiency, view


@cache
def with_pane_defaults(name: str, prune_after: int = 2) -> ReplayReport:
    return replay(
        FIXTURES / name,
        requested=pane_request(name, prune_after),
        standards_profile=EXAMPLE_PROFILE,
    )


@pytest.fixture(scope="module")
def big_pane(tmp_path_factory: pytest.TempPathFactory) -> tuple[ReplayPasses, Path]:
    """Both passes of the big fixture with the pane defaults, and the folder they wrote."""
    scratch = tmp_path_factory.mktemp("big-pane")
    passes = replay_passes(
        read_recording(FIXTURES / "big-assembly"),
        scratch,
        requested=pane_request("big-assembly"),
        standards_profile=EXAMPLE_PROFILE,
    )
    return passes, scratch


@pytest.mark.parametrize("name", NAMES)
def test_the_pane_defaults_lose_no_recorded_finding(name: str) -> None:
    findings = with_pane_defaults(name).findings

    assert findings.lost == []
    assert findings.not_replayable == []
    assert len(findings.reclassified) == RECLASSIFIED[name]


@pytest.mark.parametrize("name", NAMES)
def test_the_pane_defaults_cut_every_fixture(name: str) -> None:
    report = with_pane_defaults(name)

    assert report.totals.requested < report.totals.as_recorded
    assert report.totals.requested < checks_first(name).totals.requested


def test_the_pane_defaults_bring_the_big_assembly_under_a_million(
    big_pane: tuple[ReplayPasses, Path],
) -> None:
    """SC-002, priced from the same played passes the other acceptance tests read."""
    passes, _ = big_pane
    report = report_of(passes)

    assert report.totals.requested < MILLION
    assert report.totals.requested == with_pane_defaults("big-assembly").totals.requested
    assert report.findings.lost == []


def test_the_view_changes_no_finding(
    big_pane: tuple[ReplayPasses, Path], tmp_path: Path
) -> None:
    """SC-007: the same requested levers with the model view off record the same findings
    and contacts - the view changes what the model reads, never what the checks record."""
    passes, _ = big_pane
    efficiency, _ = pane_request("big-assembly")
    off = replay_passes(
        passes.recording,
        tmp_path,
        requested=(efficiency, MODEL_VIEW_OFF),
        standards_profile=EXAMPLE_PROFILE,
    )

    def findings(session: Any) -> Counter[Any]:
        return Counter(finding_subject_key(finding) for finding in session.findings)

    assert findings(passes.second.session) == findings(off.second.session)
    assert sorted(c.group_key for c in passes.second.session.contacts) == sorted(
        c.group_key for c in off.second.session.contacts
    )


def test_every_step_of_the_requested_pass_is_stored(big_pane: tuple[ReplayPasses, Path]) -> None:
    """SC-008: one `tool-results/step-<n>.json` per recorded step, naming the session."""
    passes, scratch = big_pane
    session = passes.second.session
    folder = scratch / "requested" / TOOL_RESULTS_DIR_NAME

    assert session.steps
    for step in session.steps:
        stored = json.loads((folder / f"step-{step.index}.json").read_text(encoding="utf-8"))
        assert stored["session_id"] == str(session.session_id)
        assert (stored["step"], stored["tool"]) == (step.index, step.tool)
    assert len(list(folder.glob("step-*.json"))) == len(session.steps)


def test_every_result_past_the_prune_age_is_a_stub_in_every_request(
    big_pane: tuple[ReplayPasses, Path],
) -> None:
    """Every result two rounds old or older reaches the model as a stub - unless it is an
    error or its stub would be longer - and no younger result ever does."""
    passes, _ = big_pane
    view = passes.requested_view

    def compact(value: Any) -> int:
        return len(json.dumps(value, separators=(",", ":")))

    def stub(content: Mapping[str, Any]) -> bool:
        return content.get("pruned") == PRUNED_NOTE

    stubs = 0
    for played in passes.second.rounds:
        sent = request_messages(played.history, view)
        old = prunable(played.history, view.prune_after_rounds)
        for index, message in enumerate(sent):
            if message["role"] != "tool":
                continue
            content = message["content"]
            if index not in old:
                assert not stub(content), (played.turn, played.index, index)
                continue
            if stub(content):
                stubs += 1
                continue
            full = played.history[index]["content"]
            stubbed = result_stub(
                message["name"], old[index], full, finding_detail=view.payload_slimming
            )
            assert compact(stubbed) >= compact(full), (played.turn, played.index, index)
    assert stubs > 0


# --- the User Story 4 acceptance: follow-ups and the regrouped estimate (008 T086) -----------

SMALL = ("small-assembly-a", "small-assembly-b")
REGROUPED_TARGET = 300_000
"""SC-003 as amended (research R2.43, R4): each small fixture's regrouped estimate."""
FOLLOW_UP_TARGET = 30_000
"""SC-004: the big fixture's follow-up question, against 405k recorded."""


def openai_pane_request(prune_after: int = 2) -> Requested:
    """The pane defaults of the provider the recorded reviews ran on.

    The recordings the fixtures are shaped like were OpenAI reviews; the fixtures' sessions
    say `fake` only because the generator drove the scripted provider. The OpenAI pane adds
    parallel tool calls to what `pane_request` gives, which is what rule M models; on the
    command line it is `--lever parallel_tool_calls`.
    """
    pane = pane_defaults(ProviderName.OPENAI)
    return pane.efficiency, pane.model_view.model_copy(update={"prune_after_rounds": prune_after})


@cache
def with_openai_pane(name: str, prune_after: int = 2) -> ReplayReport:
    return replay(
        FIXTURES / name,
        requested=openai_pane_request(prune_after),
        standards_profile=EXAMPLE_PROFILE,
    )


def test_the_openai_pane_is_the_fixture_pane_plus_parallel_calls() -> None:
    efficiency, view = openai_pane_request()
    fixture_efficiency, fixture_view = pane_request("small-assembly-a")

    assert view == fixture_view
    assert efficiency == fixture_efficiency.model_copy(update={"parallel_tool_calls": True})


@pytest.mark.parametrize("name", NAMES)
def test_the_openai_pane_loses_no_recorded_finding(name: str) -> None:
    findings = with_openai_pane(name).findings

    assert findings.lost == []
    assert findings.not_replayable == []
    assert len(findings.reclassified) == RECLASSIFIED[name]


@pytest.mark.parametrize("name", NAMES)
def test_the_regrouped_estimate_applies_both_rules_with_its_assumption(name: str) -> None:
    report = with_openai_pane(name)

    assert report.regrouped is not None
    assert report.regrouped.rules == ["R", "M"]
    assert report.regrouped.assumption.startswith("the model does not repeat a check")
    assert report.regrouped.total < report.totals.requested
    assert report.regrouped.rounds < len(report.rounds)


@pytest.mark.parametrize("name", SMALL)
def test_each_small_fixture_is_cut_below_its_recorded_total(name: str) -> None:
    """SC-003's strict half: the recorded rounds, priced with the pane defaults."""
    report = with_openai_pane(name)

    assert report.totals.requested < report.totals.recorded


@pytest.mark.parametrize("name", SMALL)
def test_each_small_fixtures_regrouped_estimate_is_under_the_target(name: str) -> None:
    """SC-003 as amended: the labelled regrouped estimate under 300,000 input tokens."""
    report = with_openai_pane(name)

    assert report.regrouped is not None
    assert report.regrouped.total < REGROUPED_TARGET, (
        f"{name}: regrouped {report.regrouped.total:,}, strict {report.totals.requested:,}"
    )


def test_the_big_assemblys_follow_up_is_under_thirty_thousand() -> None:
    """SC-004: the follow-up question's request carries stubs, not payloads."""
    report = with_openai_pane("big-assembly")

    [follow_up] = [r for r in report.rounds if (r.turn, r.round) == (1, 0)]
    assert follow_up.kind == "main"
    assert follow_up.requested_input < FOLLOW_UP_TARGET
    assert follow_up.recorded_input > 400_000


def test_both_prune_ages_are_priced_for_the_owner() -> None:
    """Research R2.37: two rounds is the default, one is the owner's call; both are printed."""
    one, two = with_pane_defaults("big-assembly", 1), with_pane_defaults("big-assembly", 2)

    assert one.settings.requested.model_view.prune_after_rounds == 1
    assert two.settings.requested.model_view.prune_after_rounds == 2
    assert one.totals.requested <= two.totals.requested < MILLION
    assert one.findings.lost == []
    assert any(
        line.endswith("history pruning after 1 round") for line in render_replay_lines(one)
    )
    assert any(
        line.endswith("history pruning after 2 rounds") for line in render_replay_lines(two)
    )
