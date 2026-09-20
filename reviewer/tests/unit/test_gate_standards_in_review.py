"""The gate's standards half: a release grading inside a review (T048, FR-027, FR-028).

Until now the sixteen release checks ran only from `swreview check standards` and the
Standards tab - their own entry point, their own folder, their own verdict. A review never
saw them, because `ToolRegistry._offered` registers `check_standards` only when the context
carries a `StandardsRun`, and nothing in `start_review` ever attached one.

`start_review(standards_profile=...)` attaches it, **between** `build_context` and the
dispatch, because the tool array is decided once at dispatch-build time and never changes
afterwards (lever 3's whole prefix guarantee). With it attached the pre-run plans a fifth
call and the standards family lands in the review's own session: real findings, real
coverage, and the family's summary item closing `standards.release`.

**Every failure on that path is a line, never a refusal.** `run_standards_check` refuses a
package whose phases did not run, and rightly: a release gate must not grade an extract that
never read the evidence. A *review* has fifteen other things to do, so the three things that
stop the standards half - no profile, a profile that cannot be loaded, a package dumped
without the `cutlist` phase - each become one `NotEvaluated`: a line in the brief and a
`coverage.prerun.standards` skipped item beside it, and the review starts anyway
(`contracts/gate.md` section 2).

No company value appears here. The profile is `tests/fixtures/standards/profile-a.yaml`,
fictional in every field, and the package is the pre-run fixture with a part named for that
profile's invented part-number convention.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from swreview import cli
from swreview.agent.checklist import COVERAGE_BUCKETS, FINDING_BUCKET, load_checklist
from swreview.agent.providers.fake import FakeProvider, ScriptedTurn
from swreview.agent.runner import ReviewRun, start_review
from swreview.agent.settings import EfficiencySettings, ProviderSettings
from swreview.checks.rms.registry import RMS_FAMILY
from swreview.checks.standards.registry import CHECK_TOOL, STANDARDS_FAMILY
from swreview.ir.loader import save_package
from swreview.ir.models import EvidencePackage
from swreview.prerun import (
    GATE_BLIND_SPOT_HEADER,
    PRERUN_CHECK_PREFIX,
    STANDARDS_FAMILY_NAME,
    STANDARDS_NO_PROFILE,
    STANDARDS_NOT_DUMPED,
    STANDARDS_UNREADABLE,
)
from swreview.report.session import ReviewSession
from tests.support.console import plain_one_line
from tests.support.prerun import (
    GATE_ON,
    MODEL_DRIVEN_CALLS,
    STANDARDS_PROFILE,
    prerun_package,
    standards_prerun_package,
)
from tests.unit.test_prerun_digest import opening_of

CHECKLIST = load_checklist()
STANDARDS_ITEM = STANDARDS_FAMILY.summary_check
RMS_ITEM = RMS_FAMILY.summary_check
STANDARDS_CHECK = f"{PRERUN_CHECK_PREFIX}{STANDARDS_FAMILY_NAME}"
STANDARDS_PREFIX = "standards."

runner = CliRunner()


# --- running one gated review ------------------------------------------------------------


def gated_review(
    tmp_path: Any,
    out: str,
    *,
    package: EvidencePackage | None = None,
    standards_profile: Path | None = None,
    efficiency: EfficiencySettings = GATE_ON,
) -> tuple[ReviewRun, ReviewSession]:
    """One scripted review, played, with the run kept so its first message can be read."""
    package_dir = Path(tmp_path) / out / "package"
    save_package(package if package is not None else standards_prerun_package(), package_dir)
    run = start_review(
        package_dir,
        Path(tmp_path) / out / "run",
        provider=FakeProvider(script=[ScriptedTurn(text="done")], model="fake-scripted"),
        efficiency=efficiency,
        standards_profile=standards_profile,
    )
    return run, run.start()


def bucket_of(session: ReviewSession, item_id: str) -> str:
    item = next(one for one in CHECKLIST.items if one.id == item_id)
    return CHECKLIST.bucket_of(item, session)


def coverage_checks(session: ReviewSession, bucket: str) -> list[str]:
    return [item.check for item in getattr(session.coverage, bucket)]


def skipped_reason(session: ReviewSession, check: str) -> str:
    return next(item.reason for item in session.coverage.skipped if item.check == check)


def standards_findings(session: ReviewSession) -> list[Any]:
    return [one for one in session.findings if one.check.startswith(STANDARDS_PREFIX)]


def blind_spot_lines(run: ReviewRun) -> list[str]:
    """The brief's "Not visible to any rule" block, as the model reads it."""
    lines = opening_of(run).splitlines()
    start = lines.index(GATE_BLIND_SPOT_HEADER) + 1
    end = next((one for one in range(start, len(lines)) if not lines[one]), len(lines))
    return lines[start:end]


# --- 1. the happy path: a release grading inside the review --------------------------------


@pytest.fixture(scope="module")
def graded(tmp_path_factory: pytest.TempPathFactory) -> tuple[ReviewRun, ReviewSession]:
    """One gated review of a standards-dumped package against the fictional profile."""
    return gated_review(
        tmp_path_factory.mktemp("graded"), "gated", standards_profile=STANDARDS_PROFILE
    )


def test_the_gate_runs_check_standards_as_a_real_step(
    graded: tuple[ReviewRun, ReviewSession],
) -> None:
    _, session = graded

    assert [step.tool for step in session.steps] == [
        *(call.name for call in MODEL_DRIVEN_CALLS),
        CHECK_TOOL,
    ]
    assert [step.index for step in session.steps] == list(range(len(session.steps)))
    assert session.steps[-1].status == "ok"


def test_standards_findings_are_recorded_in_the_reviews_own_session(
    graded: tuple[ReviewRun, ReviewSession],
) -> None:
    _, session = graded

    findings = standards_findings(session)
    assert findings
    cited = [step_id for finding in findings for step_id in finding.tool_result_ids]
    assert cited and all(0 <= step_id < len(session.steps) for step_id in cited)


def test_the_standards_checklist_item_is_closed_by_a_finding(
    graded: tuple[ReviewRun, ReviewSession],
) -> None:
    """By prefix, which is the first thing `bucket_of` looks at."""
    _, session = graded

    assert bucket_of(session, STANDARDS_ITEM) == FINDING_BUCKET


def test_the_families_summary_item_closes_the_same_item_by_id(
    graded: tuple[ReviewRun, ReviewSession],
) -> None:
    """The other of the two closures, asserted over the same session with its standards
    findings taken out, so it is the summary coverage item doing the work and not a finding
    riding in front of it."""
    _, session = graded
    without = session.model_copy(deep=True)
    without.findings[:] = [
        one for one in without.findings if not one.check.startswith(STANDARDS_PREFIX)
    ]

    assert STANDARDS_ITEM in coverage_checks(session, "unresolved") + coverage_checks(
        session, "checked"
    )
    assert bucket_of(without, STANDARDS_ITEM) in COVERAGE_BUCKETS


def test_the_rms_summary_item_is_unaffected(graded: tuple[ReviewRun, ReviewSession]) -> None:
    """The two families are disjoint: a standards grading closes `standards.release` and
    leaves `modeling.resilience` to the rms rules that were pre-run beside it."""
    _, session = graded

    summaries = coverage_checks(session, "checked") + coverage_checks(session, "unresolved")
    assert STANDARDS_ITEM != RMS_ITEM
    assert summaries.count(STANDARDS_ITEM) == 1
    assert summaries.count(RMS_ITEM) == 1
    assert bucket_of(session, RMS_ITEM) == FINDING_BUCKET


def test_a_family_that_was_evaluated_is_not_a_blind_spot(
    graded: tuple[ReviewRun, ReviewSession],
) -> None:
    run, session = graded

    assert STANDARDS_CHECK not in coverage_checks(session, "skipped")
    assert not [line for line in blind_spot_lines(run) if line.startswith("  standards:")]


# --- 2. the three not-evaluated cases -------------------------------------------------------


NOT_EVALUATED_CASES: tuple[tuple[str, str], ...] = (
    ("no-profile", STANDARDS_NO_PROFILE),
    ("unreadable", "could not be loaded"),
    ("not-dumped", "was not dumped with the standards profile"),
)
"""The three of `contracts/gate.md` section 2, by case name and by what its line says."""

CASE_IDS: list[str] = [name for name, _ in NOT_EVALUATED_CASES]


def case_review(tmp_path: Any, case: str) -> tuple[ReviewRun, ReviewSession]:
    """One gated review per case, built the way that case is reached in real life."""
    if case == "no-profile":
        return gated_review(tmp_path, case, standards_profile=None)
    if case == "unreadable":
        return gated_review(
            tmp_path, case, standards_profile=Path(tmp_path) / "no-such-profile.yaml"
        )
    return gated_review(
        tmp_path,
        case,
        package=standards_prerun_package(cutlist=False),
        standards_profile=STANDARDS_PROFILE,
    )


@pytest.mark.parametrize(("case", "words"), NOT_EVALUATED_CASES, ids=CASE_IDS)
def test_each_case_writes_its_line_and_its_skipped_item(
    tmp_path: Any, case: str, words: str
) -> None:
    run, session = case_review(tmp_path, case)

    reason = skipped_reason(session, STANDARDS_CHECK)
    assert words in reason
    assert f"  {STANDARDS_FAMILY_NAME}: {reason}" in opening_of(run).splitlines()


@pytest.mark.parametrize("case", CASE_IDS)
def test_the_line_is_said_once_as_a_digest_line_and_once_as_a_blind_spot(
    tmp_path: Any, case: str
) -> None:
    """One family, two renderings, and the second is the policy file's sentence rather than
    a second copy of the first - the reason the run gives and the reason no rule can ever
    reach it are different claims about the same gap."""
    run, session = case_review(tmp_path, case)

    reason = skipped_reason(session, STANDARDS_CHECK)
    blind = [line for line in blind_spot_lines(run) if line.startswith("  standards:")]
    assert len(blind) == 1
    assert reason not in blind[0]


@pytest.mark.parametrize("case", CASE_IDS)
def test_the_review_still_starts_and_finishes(tmp_path: Any, case: str) -> None:
    """A refusal here would lose a whole review over one family of sixteen; the line is what
    the model gets instead, and the other four pre-run calls still ran."""
    _, session = case_review(tmp_path, case)

    assert session.ended_at is not None
    assert [step.tool for step in session.steps] == [call.name for call in MODEL_DRIVEN_CALLS]
    assert not standards_findings(session)


@pytest.mark.parametrize("case", CASE_IDS)
def test_the_standards_item_is_not_closed_by_the_skipped_item(tmp_path: Any, case: str) -> None:
    """`coverage.prerun.standards` says the family was **not** evaluated. Closing the item
    on it would answer the very sentence it is asking the model to work on, which is what
    `PRERUN_CHECK_PREFIX` exists to prevent."""
    _, session = case_review(tmp_path, case)

    assert STANDARDS_CHECK in coverage_checks(session, "skipped")
    assert STANDARDS_ITEM in coverage_checks(session, "unresolved")
    assert "the review ended without a finding" in next(
        item.reason for item in session.coverage.unresolved if item.check == STANDARDS_ITEM
    )


def test_the_unreadable_case_names_the_path_it_tried(tmp_path: Any) -> None:
    missing = Path(tmp_path) / "no-such-profile.yaml"

    _, session = gated_review(tmp_path, "unreadable", standards_profile=missing)

    assert str(missing) in skipped_reason(session, STANDARDS_CHECK)


def test_an_invalid_profile_is_the_same_case_as_an_unreadable_one(tmp_path: Any) -> None:
    """`ProfileInvalid` and `ProfileUnreadable` are one line here: both mean the review has
    no standard to grade against, and the error text says which it was."""
    broken = Path(tmp_path) / "broken.yaml"
    broken.write_text("version: 99\n", encoding="utf-8")

    _, session = gated_review(tmp_path, "invalid", standards_profile=broken)

    reason = skipped_reason(session, STANDARDS_CHECK)
    assert reason.startswith(STANDARDS_UNREADABLE.split("{")[0])
    assert str(broken) in reason


def test_the_not_dumped_case_names_the_missing_phase(tmp_path: Any) -> None:
    """The one `run_standards_check` refuses outright: a review dumped with the
    `model_check` profile reaches it, and a review may not be lost to it."""
    _, session = gated_review(
        tmp_path,
        "not-dumped",
        package=standards_prerun_package(cutlist=False),
        standards_profile=STANDARDS_PROFILE,
    )

    reason = skipped_reason(session, STANDARDS_CHECK)
    assert reason.startswith(STANDARDS_NOT_DUMPED.split("{")[0])
    assert "cutlist" in reason


# --- 3. the profile is an argument to the review, not to the lever ---------------------------


def test_with_the_gate_off_and_no_profile_nothing_about_standards_is_written(
    tmp_path: Any,
) -> None:
    """FR-030 from this side: lever 5's arm must not grow the line lever 11 added."""
    run, session = gated_review(
        tmp_path,
        "lever5",
        package=prerun_package(),
        efficiency=EfficiencySettings(prerun_checks=True),
    )

    assert STANDARDS_CHECK not in coverage_checks(session, "skipped")
    assert STANDARDS_FAMILY_NAME not in opening_of(run)


def test_a_profile_given_with_the_gate_off_still_attaches_the_run(tmp_path: Any) -> None:
    """With lever 5 alone the tool is offered and the pre-run calls it, because the context
    carries the run: `_offered` asks the context, and so does `planned_calls`."""
    run, session = gated_review(
        tmp_path,
        "lever5-profile",
        standards_profile=STANDARDS_PROFILE,
        efficiency=EfficiencySettings(prerun_checks=True),
    )

    assert [step.tool for step in session.steps][-1] == CHECK_TOOL
    assert CHECK_TOOL in [tool.name for tool in run.tools]
    assert standards_findings(session)


def test_an_unusable_profile_with_every_lever_off_records_the_missing_standard(
    tmp_path: Any,
) -> None:
    """A configured standard that cannot load remains visible with all levers off.

    No check runs and no unusable tool is offered, but the review must not silently
    appear to have evaluated the engineer's configured standard.
    """
    run, session = gated_review(
        tmp_path,
        "levers-off",
        standards_profile=Path(tmp_path) / "missing.yaml",
        efficiency=EfficiencySettings(),
    )

    assert session.ended_at is not None
    assert session.steps == []
    assert CHECK_TOOL not in [tool.name for tool in run.tools]
    assert STANDARDS_CHECK in coverage_checks(session, "skipped")
    assert "missing.yaml" in skipped_reason(session, STANDARDS_CHECK)
    assert "configured standards profile could not be loaded" in opening_of(run)


# --- 4. the command line ----------------------------------------------------------------------


class RecordingProvider(FakeProvider):
    """The scripted fake, keeping the tool names each turn was handed."""

    def __init__(self, settings: ProviderSettings, script: Sequence[ScriptedTurn]) -> None:
        super().__init__(script=script, model=settings.model)
        self.name = settings.provider
        self.tool_names: tuple[str, ...] = ()

    def run(self, **kwargs: Any) -> Any:
        self.tool_names = tuple(tool.name for tool in kwargs["tools"])
        return super().run(**kwargs)


@pytest.fixture
def fake_provider(monkeypatch: pytest.MonkeyPatch) -> list[RecordingProvider]:
    """Swap `cli.provider_factory` for one that scripts whatever adapter the CLI asks for."""
    built: list[RecordingProvider] = []

    def factory(settings: ProviderSettings, efficiency: Any = None) -> RecordingProvider:
        provider = RecordingProvider(settings, [ScriptedTurn(text="done")])
        built.append(provider)
        return provider

    monkeypatch.setattr(cli, "provider_factory", factory)
    return built


def test_swreview_review_passes_the_standards_profile_through(
    tmp_path: Any, fake_provider: list[RecordingProvider]
) -> None:
    """`--standards-profile <yaml>` reaches `start_review`, and the session is the proof: a
    `check_standards` step and a standards finding exist only if the run was attached."""
    package_dir = Path(tmp_path) / "package"
    save_package(standards_prerun_package(), package_dir)
    out = Path(tmp_path) / "run"

    result = runner.invoke(
        cli.app,
        [
            "review",
            str(package_dir),
            "--out",
            str(out),
            "--provider",
            "fake",
            "--lever",
            "procedural_gate",
            "--standards-profile",
            str(STANDARDS_PROFILE),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout
    session = json.loads((out / "session.json").read_text(encoding="utf-8"))
    assert [step["tool"] for step in session["steps"]][-1] == CHECK_TOOL
    assert [one for one in session["findings"] if one["check"].startswith(STANDARDS_PREFIX)]
    assert CHECK_TOOL in fake_provider[0].tool_names


def test_swreview_review_without_the_option_offers_no_standards_tool(
    tmp_path: Any, fake_provider: list[RecordingProvider]
) -> None:
    """The default is unchanged: no profile, no run attached, no `check_standards`."""
    package_dir = Path(tmp_path) / "package"
    save_package(standards_prerun_package(), package_dir)

    result = runner.invoke(
        cli.app,
        ["review", str(package_dir), "--out", str(Path(tmp_path) / "run"), "--provider", "fake"],
    )

    assert result.exit_code == 0, result.stdout
    assert CHECK_TOOL not in fake_provider[0].tool_names


def test_the_option_is_on_the_review_commands_help() -> None:
    result = runner.invoke(cli.app, ["review", "--help"])

    assert result.exit_code == 0
    assert "--standards-profile" in plain_one_line(result.stdout)
