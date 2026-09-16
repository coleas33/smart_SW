"""Hand-built A/B studies: scorecards, sessions and whole run directories (T039-T043).

Two test modules read this one. `test_adoption_rule.py` wants **scorecards and nothing
else**, because that is where the adoption rule's edge cases live and where they are
cheapest; `test_benchmark_compare.py` wants the run directories those scorecards sit in,
because `compare`'s job is reading N of them and refusing the ones that disagree with
themselves.

The aggregate here is built **by hand**, deliberately: a builder that called the
scorer's own `_aggregate` would assert the code against itself. The null rule it applies
is stated once in `_sum_or_none` below and is the same rule the scorer applies - any null
in any package makes that total null, never a partial sum.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from swreview.agent.providers import EffortMapping, TokenUsage
from swreview.agent.settings import EfficiencySettings
from swreview.benchmark.adoption import ArmRun
from swreview.benchmark.runner import RunProvenance, sha256_of, write_provenance
from swreview.benchmark.scorecard import Aggregate, PackageScore, Scorecard
from swreview.report.session import (
    Coverage,
    CoverageItem,
    CoverageScope,
    InvestigationStep,
    ProviderInfo,
    ReviewSession,
    SessionUsage,
    Timing,
    save_session,
)
from tests.support.packages import build_package

PACKAGE = build_package()

STARTED_AT = datetime(2026, 9, 16, 9, 0, tzinfo=UTC)
SCORED_AT = datetime(2026, 9, 16, 10, 0, tzinfo=UTC)
COMMIT = "5733efd"
CHECKLIST_DIGEST = "c" * 64
SET_DIGEST = "5" * 64
SET_NAME = "study"


@dataclass(frozen=True)
class PackageSpec:
    """One package of one run: what it cost and what it found."""

    package_id: str = "rms-part"
    held_out: bool = True
    matched: tuple[str, ...] = ("D-1", "D-2")
    missed: tuple[str, ...] = ()
    valid_findings: int = 2
    false_alarms: int = 1
    unresolved: int = 3
    input_tokens: int | None = 400_000
    cached_input_tokens: int | None = 320_000
    cache_write_tokens: int | None = None
    output_tokens: int | None = 18_000
    reasoning_tokens: int | None = 16_000
    tool_result_input_tokens: int | None = None
    total_tokens: int | None = 418_000
    rounds: int | None = 9
    tool_calls: int = 31
    tool_names: tuple[str, ...] = ("list_holes",)
    """The tools the steps cycle through, so the tool-name histogram has something to
    count. One name reproduces the single-tool sessions every earlier study built."""
    wall_clock_s: float | None = 500.0
    seconds_to_first_finding: float | None = 44.0
    coverage_checked: int = 2
    coverage_unresolved: int = 3
    coverage_withheld: int = 0
    """How many of `coverage_unresolved` a withheld tool wrote (lever 4, FR-054). The
    session names those checks in `withheld_checks` and the score splits on them, so the
    two artifacts agree about the same items rather than holding two opinions."""

    def usage(self) -> TokenUsage | None:
        if self.total_tokens is None and self.input_tokens is None:
            return None
        return TokenUsage(
            input_tokens=self.input_tokens,
            cached_input_tokens=self.cached_input_tokens,
            cache_write_tokens=self.cache_write_tokens,
            output_tokens=self.output_tokens,
            reasoning_tokens=self.reasoning_tokens,
            tool_result_input_tokens=self.tool_result_input_tokens,
            total_tokens=self.total_tokens,
            latency_s=12.5,
        )


@dataclass(frozen=True)
class RunSpec:
    """One run folder of one arm."""

    run: str
    arm: str = "off"
    rep: int = 1
    lever: str = "parallel_tool_calls"
    packages: tuple[PackageSpec, ...] = (PackageSpec(),)
    efficiency: EfficiencySettings | None = None
    commit: str | None = COMMIT
    provider: str = "openai"
    model: str = "gpt-5.6"
    effort: str = "high"
    checklist_digest: str = CHECKLIST_DIGEST
    set_digest: str | None = None
    """`None` means "the digest of the saved set copy", which is what the CLI records."""
    set_too_small_override: bool = False
    other_levers: tuple[str, ...] = ()

    def settings(self) -> EfficiencySettings:
        """What the runner would have resolved, unless the spec overrode it."""
        if self.efficiency is not None:
            return self.efficiency
        on = {name: True for name in self.other_levers}
        if self.arm == "on" and self.lever != "none":
            on[self.lever] = True
        return EfficiencySettings(**on)

    def provenance(self) -> RunProvenance:
        return RunProvenance(
            commit=self.commit,
            lever=self.lever,
            arm=self.arm,
            rep=self.rep,
            provider=self.provider,
            model=self.model,
            effort=self.effort,
            max_steps=200,
            checklist_digest=self.checklist_digest,
            set_digest=self.set_digest or SET_DIGEST,
            started_at=STARTED_AT,
            set_too_small_override=self.set_too_small_override,
            efficiency=self.settings(),
        )


def step_tools(spec: PackageSpec) -> list[str]:
    """The tool each of this package's steps called: `tool_names`, cycled.

    Read by both the session and its score, so the histogram in `scorecard.json` is the
    histogram of the steps in `session.json` rather than a second opinion about them.
    """
    return [spec.tool_names[index % len(spec.tool_names)] for index in range(spec.tool_calls)]


def _sum_or_none(values: Iterable[int | None]) -> int | None:
    collected = list(values)
    return None if any(value is None for value in collected) else sum(collected)  # type: ignore[arg-type]


def package_score(spec: PackageSpec) -> PackageScore:
    usage = spec.usage()
    return PackageScore(
        package_id=spec.package_id,
        held_out=spec.held_out,
        session_id=str(uuid5(NAMESPACE_URL, spec.package_id)),
        valid_findings=spec.valid_findings,
        missed_known_defects=len(spec.missed),
        false_alarms=spec.false_alarms,
        unresolved_count=spec.unresolved,
        baseline_minutes=None,
        assisted_minutes=0.0,
        unattended_runtime_minutes=9.0,
        net_saved_minutes=None,
        usage=usage,
        round_trips=spec.rounds,
        cached_input_share=usage.cached_input_share if usage is not None else None,
        wall_clock_s=spec.wall_clock_s,
        seconds_to_first_finding=spec.seconds_to_first_finding,
        unresolved_because_withheld=spec.coverage_withheld,
        unresolved_other=spec.coverage_unresolved - spec.coverage_withheld,
        tool_calls_by_name=dict(
            sorted(Counter(step_tools(spec)).items(), key=lambda item: (-item[1], item[0]))
        ),
        matched_defect_ids=list(spec.matched),
        missed_defect_ids=list(spec.missed),
        false_alarm_finding_ids=[f"F-{index:03d}" for index in range(spec.false_alarms)],
    )


def scorecard(spec: RunSpec) -> Scorecard:
    """The `scorecard.json` `benchmark score` would have written for this run."""
    per_package = [package_score(package) for package in spec.packages]
    held_out = [score for score in per_package if score.held_out]
    matched = sum(len(score.matched_defect_ids) for score in held_out)
    known = matched + sum(len(score.missed_defect_ids) for score in held_out)
    valid = sum(score.valid_findings for score in per_package)
    false_alarms = sum(score.false_alarms for score in per_package)
    return Scorecard(
        run_id=spec.run,
        benchmark_set=SET_NAME,
        scored_at=SCORED_AT,
        per_package=per_package,
        aggregate=Aggregate(
            packages=len(per_package),
            held_out_packages=len(held_out),
            valid_findings=valid,
            missed_known_defects=sum(score.missed_known_defects for score in per_package),
            false_alarms=false_alarms,
            unresolved_count=sum(score.unresolved_count for score in per_package),
            recall=(matched / known) if known else None,
            false_alarm_rate=(
                false_alarms / (valid + false_alarms) if (valid + false_alarms) else None
            ),
            median_net_saved_minutes=None,
            packages_with_timing=0,
            input_tokens=_sum_or_none(package.input_tokens for package in spec.packages),
            cached_input_tokens=_sum_or_none(
                package.cached_input_tokens for package in spec.packages
            ),
            output_tokens=_sum_or_none(package.output_tokens for package in spec.packages),
            reasoning_tokens=_sum_or_none(package.reasoning_tokens for package in spec.packages),
            total_tokens=_sum_or_none(package.total_tokens for package in spec.packages),
            round_trips=_sum_or_none(package.rounds for package in spec.packages),
            median_seconds_to_first_finding=None,
            packages_with_usage=sum(1 for score in per_package if score.usage is not None),
        ),
        distribution=[None for _ in per_package],
    )


def arm_run(spec: RunSpec) -> ArmRun:
    """What `compare` hands the adoption rule, built without a run directory."""
    return ArmRun(
        run=spec.run,
        scorecard=scorecard(spec),
        tool_calls=sum(package.tool_calls for package in spec.packages),
        set_too_small_override=spec.set_too_small_override,
    )


def arm(
    arm_name: str, count: int = 3, *, lever: str = "parallel_tool_calls", **overrides: Any
) -> list[ArmRun]:
    """`count` repetitions of one arm, all alike unless an override says otherwise."""
    return [
        arm_run(RunSpec(run=f"{arm_name}-{rep}", arm=arm_name, rep=rep, lever=lever, **overrides))
        for rep in range(1, count + 1)
    ]


def _withheld_checks(package: PackageSpec) -> list[str]:
    """The first `coverage_withheld` unresolved checks, named as the session names them."""
    return [f"open-{index}" for index in range(package.coverage_withheld)]


def _coverage_item(check: str) -> CoverageItem:
    return CoverageItem(check=check, scope=CoverageScope(), reason="r", error=None)


def session_of(spec: RunSpec, package: PackageSpec) -> ReviewSession:
    """The `session.json` beside one package's score."""
    return ReviewSession(
        session_id=uuid5(NAMESPACE_URL, f"{spec.run}/{package.package_id}"),
        package_id=PACKAGE.package_id,
        design_id=PACKAGE.design.design_id,
        started_at=STARTED_AT,
        ended_at=(
            STARTED_AT + timedelta(seconds=package.wall_clock_s)
            if package.wall_clock_s is not None
            else None
        ),
        model=spec.model,
        provider_info=ProviderInfo(
            provider=spec.provider,
            model=spec.model,
            effort_mapping=EffortMapping(
                requested=spec.effort,  # type: ignore[arg-type]
                provider_param="reasoning.effort",
                provider_value=spec.effort,
            ),
            key_source="env",
        ),
        efficiency=spec.settings(),
        usage=(
            SessionUsage(
                rounds=package.rounds,
                turns=1,
                totals=package.usage(),  # type: ignore[arg-type]
                by_turn=[],
            )
            if package.usage() is not None and package.rounds is not None
            else None
        ),
        steps=[
            InvestigationStep(
                index=index,
                tool=tool,
                arguments={},
                result_summary="ok",
                status="ok",
                error=None,
                elapsed_s=0.1,
            )
            for index, tool in enumerate(step_tools(package))
        ],
        withheld_checks=_withheld_checks(package),
        coverage=Coverage(
            checked=[
                _coverage_item(f"item-{index}") for index in range(package.coverage_checked)
            ],
            unresolved=[
                _coverage_item(f"open-{index}") for index in range(package.coverage_unresolved)
            ],
        ),
        timing=Timing(
            baseline_minutes=None,
            assisted_supervision_minutes=0.0,
            assisted_verification_minutes=0.0,
            false_alarm_handling_minutes=0.0,
            unattended_runtime_minutes=9.0,
        ),
    )


def write_events(package_dir: Path, package: PackageSpec) -> None:
    events: list[dict[str, Any]] = [
        {"seq": 1, "at": STARTED_AT.isoformat(), "type": "session.started", "body": {}}
    ]
    if package.seconds_to_first_finding is not None:
        events.append(
            {
                "seq": 2,
                "at": (
                    STARTED_AT + timedelta(seconds=package.seconds_to_first_finding)
                ).isoformat(),
                "type": "finding",
                "body": {"id": "F-001"},
            }
        )
    (package_dir / "events.jsonl").write_text(
        "".join(json.dumps(event) + "\n" for event in events), encoding="utf-8"
    )


def write_run(
    root: Path,
    spec: RunSpec,
    *,
    with_provenance: bool = True,
    with_saved_set: bool = True,
    session_edit: dict[str, Any] | None = None,
) -> Path:
    """One complete run directory, of the shape `benchmark run` and `score` leave behind.

    `session_edit` patches the written `session.json` **after** it was serialized, which
    is how a run whose two records disagree is built: nothing in the runner can produce
    one, and the disagreement is exactly what `compare` exists to catch.
    """
    run_dir = root / spec.run
    for package in spec.packages:
        package_dir = run_dir / package.package_id
        session = session_of(spec, package)
        save_session(session, package_dir / "session.json")
        if session_edit is not None:
            payload = json.loads((package_dir / "session.json").read_text(encoding="utf-8"))
            for key, value in session_edit.items():
                if value is None and key in payload:
                    payload.pop(key)
                else:
                    payload[key] = value
            (package_dir / "session.json").write_text(
                json.dumps(payload, indent=2) + "\n", encoding="utf-8"
            )
        write_events(package_dir, package)

    (run_dir / "scorecard.json").write_text(
        scorecard(spec).model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    recorded = spec
    if with_saved_set:
        saved = run_dir / "benchmark-set.json"
        saved.write_text(
            json.dumps({"name": SET_NAME, "packages": []}, indent=2) + "\n", encoding="utf-8"
        )
        if spec.set_digest is None:
            recorded = replace(spec, set_digest=sha256_of(saved))
    if with_provenance:
        write_provenance(run_dir, recorded.provenance())
    return run_dir


def write_study(root: Path, specs: Sequence[RunSpec], **kwargs: Any) -> list[Path]:
    """Every run folder of one study, in the order the arms were alternated."""
    return [write_run(root, spec, **kwargs) for spec in specs]


def study_specs(
    *,
    lever: str = "parallel_tool_calls",
    reps: int = 3,
    off: dict[str, Any] | None = None,
    on: dict[str, Any] | None = None,
) -> list[RunSpec]:
    """Three off runs and three on runs, alternated, with per-arm overrides."""
    specs: list[RunSpec] = []
    for rep in range(1, reps + 1):
        specs.append(
            RunSpec(run=f"off-{rep}", arm="off", rep=rep, lever=lever, **(off or {}))
        )
        specs.append(RunSpec(run=f"on-{rep}", arm="on", rep=rep, lever=lever, **(on or {})))
    return specs
