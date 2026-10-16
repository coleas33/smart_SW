"""Hand-built A/B studies: scorecards, sessions and whole run directories (T039-T043).

Two test modules read this one. `test_adoption_rule.py` wants **scorecards and nothing
else**, because that is where the adoption rule's edge cases live and where they are
cheapest; `test_benchmark_compare.py` wants the run directories those scorecards sit in,
because `compare`'s job is reading N of them and refusing the ones that disagree with
themselves.

The aggregate here is built **by hand**, deliberately: a builder that called the
scorer's own `_aggregate` would assert the code against itself. The null rule it applies
is the scorer's own `sum_or_none`, imported rather than restated (feature 014 owner decision
85A) - any null in any package makes that total null, never a partial sum.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import median
from typing import TYPE_CHECKING, Any, Literal, get_args
from uuid import NAMESPACE_URL, uuid5

from swreview.agent.providers import EffortMapping, ProviderName, TokenUsage
from swreview.agent.providers.retry import BENCHMARK_RETRY, RetryPolicy
from swreview.agent.settings import (
    DEFAULT_MODELS,
    INERT_SETTINGS,
    LEVER_NAMES,
    MODEL_VIEW_OFF,
    MODEL_VIEW_PANE,
    NO_STUDY,
    PANE_STUDY,
    PRIVATE_PANE_STUDY,
    EfficiencySettings,
    ModelViewSettings,
    pane_efficiency,
)
from swreview.benchmark.adoption import ArmRun
from swreview.benchmark.origins import Origin
from swreview.benchmark.prices import SYNTHETIC_COST
from swreview.benchmark.questions import (
    NO_ANSWER_LOG,
    NO_QUESTION_COUNT_RULE,
    NO_UNANSWERABLE_REQUEST,
)
from swreview.benchmark.runner import (
    PROVENANCE_SCHEMA,
    RunProvenance,
    sha256_of,
    write_provenance,
)
from swreview.benchmark.scorecard import (
    NO_CORRECT_CONDITION,
    NO_EXPECTED_COVERAGE,
    NO_FORBIDDEN_ENTRY,
    SCORING_RULES_VERSION,
    Aggregate,
    GradedItem,
    PackageScore,
    RecallByProducer,
    RecallByTag,
    Scorecard,
    sum_or_none,
)
from swreview.checks.standards.document import DATA_CARD_COMPLETE
from swreview.checks.standards.report import PROFILE_LIMIT
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
from tests.support.findings import make_finding
from tests.support.packages import build_package

if TYPE_CHECKING:
    from swreview.benchmark import verdict

PACKAGE = build_package()

STARTED_AT = datetime(2026, 9, 16, 9, 0, tzinfo=UTC)
SCORED_AT = datetime(2026, 9, 16, 10, 0, tzinfo=UTC)
COMMIT = "5733efd"
CHECKLIST_DIGEST = "c" * 64
PROMPT_DIGEST = "d" * 64
SET_DIGEST = "5" * 64
SET_NAME = "study"
KEY_SHA256 = "e" * 64

EXAMPLE_PROFILE_DIGEST = "b" * 64
"""The digest a run graded against the checkout's example profile records, as a `pane_defaults`
run must (feature 014 `contracts/provenance.md` 3.2)."""

PRIVATE_PROFILE_DIGEST = "a" * 64
"""A real profile's digest, the private pane study's."""

PANE_PROFILES: dict[str, tuple[str, bool]] = {
    PANE_STUDY: (EXAMPLE_PROFILE_DIGEST, True),
    PRIVATE_PANE_STUDY: (PRIVATE_PROFILE_DIGEST, False),
}
"""Each pane study's `profile_digest` and `profile_is_example`: the example profile for the
committed study, a real one for the private study (owner decision 23A)."""


@dataclass(frozen=True)
class PackageSpec:
    """One package of one run: what it cost and what it found.

    Its known defects, `matched` and `missed`, are graded as model-produced items tagged by
    `held_out`, which is what the scorer requires the flag to be derived from (feature 014), and
    its key holds no correct condition and none of the four extension lists, so every column they
    grade reads not assessed, as does every answer-log column, with no answer log beside it; its
    request calls read, there being none. Its false alarms read `unknown`: the session written
    beside it holds no finding and no origin-marks record.
    """

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

    baseline_minutes: float | None = None
    assisted_minutes: float = 0.0
    """The engineer's minutes on this package, as `swreview timing` would have recorded
    them. `None` is the default because no run has ever carried timing, which is what the
    ledger's median column has to report as `unknown` rather than as a number. `Timing`
    derives the net from them, here and in the session below, so the score and the session
    cannot hold two opinions about what was saved."""

    def timing(self) -> Timing:
        """This package's `Timing`, with the net derived by the model as everywhere else."""
        return Timing(
            baseline_minutes=self.baseline_minutes,
            assisted_supervision_minutes=self.assisted_minutes,
            assisted_verification_minutes=0.0,
            false_alarm_handling_minutes=0.0,
            unattended_runtime_minutes=9.0,
        )

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
    """One run folder of one arm.

    Its record is what `benchmark run` writes (feature 014 `contracts/provenance.md` 1): schema
    2, every lever and the model view as resolved, no profile, no live tools, a clean tree. The
    session beside it carries the same efficiency, model view and explanation setting, so the
    two writers agree unless a test makes them disagree.
    """

    run: str
    arm: str | None = "off"
    rep: int | None = 1
    lever: str = "parallel_tool_calls"
    packages: tuple[PackageSpec, ...] = (PackageSpec(),)
    efficiency: EfficiencySettings | None = None
    commit: str | None = COMMIT
    provider: str = "openai"
    model: str = "gpt-5.6"
    served_models: tuple[str, ...] = ()
    effort: str = "high"
    checklist_digest: str = CHECKLIST_DIGEST
    set_digest: str | None = None
    """`None` means "the digest of the saved set copy", which is what the CLI records."""
    set_too_small_override: bool = False
    other_levers: tuple[str, ...] = ()
    key_sha256: str = KEY_SHA256
    """The digest of the key every package of this run was scored against, as the scorecard
    records it per package (feature 014 INT-16)."""
    max_steps: int = 200
    started_at: datetime = STARTED_AT
    """The record's; every session starts at `STARTED_AT` whatever this says."""
    explanations_enabled: bool = False
    provenance_schema: int = PROVENANCE_SCHEMA
    pane_defaults: bool = False
    model_view: ModelViewSettings | None = MODEL_VIEW_OFF
    profile_digest: str | None = None
    profile_is_example: bool | None = None
    live_tools: bool | None = False
    inert_settings: tuple[str, ...] | None = ()
    prompt_digest: str | None = PROMPT_DIGEST
    tree_dirty: bool | None = False
    max_answer_turns: int | None = 3
    """The answer-turn bound, `benchmark run`'s default; `None` writes a record older than the
    field, which holds none (feature 014 T096, on lane A3's behalf)."""
    package_time_limit_s: int | None = 3600
    stream_activity_window_s: int | None = 600
    stop_grace_s: int | None = 900
    retry_policy: RetryPolicy | None = BENCHMARK_RETRY
    jobs: int | None = 1
    standards_stamps: tuple[str, ...] = ()
    """The profile stamps this run's standards findings carry (`profile_stamp`): one
    `standards.*` finding per stamp in every package's session."""

    def settings(self) -> EfficiencySettings:
        """What the runner would have resolved, unless the spec overrode it."""
        if self.efficiency is not None:
            return self.efficiency
        on = {name: True for name in self.other_levers}
        if self.arm == "on" and self.lever in LEVER_NAMES:
            on[self.lever] = True
        return EfficiencySettings(**on)

    def provenance(self) -> RunProvenance:
        return RunProvenance(
            commit=self.commit,
            lever=self.lever,
            arm=self.arm,  # type: ignore[arg-type]
            rep=self.rep,
            provider=self.provider,
            model=self.model,
            effort=self.effort,
            max_steps=self.max_steps,
            checklist_digest=self.checklist_digest,
            set_digest=self.set_digest or SET_DIGEST,
            started_at=self.started_at,
            set_too_small_override=self.set_too_small_override,
            efficiency=self.settings(),
            explanations_enabled=self.explanations_enabled,
            provenance_schema=self.provenance_schema,
            pane_defaults=self.pane_defaults,
            model_view=self.model_view,
            profile_digest=self.profile_digest,
            profile_is_example=self.profile_is_example,
            live_tools=self.live_tools,
            inert_settings=self.inert_settings,
            prompt_digest=self.prompt_digest,
            tree_dirty=self.tree_dirty,
            max_answer_turns=self.max_answer_turns,
            package_time_limit_s=self.package_time_limit_s,
            stream_activity_window_s=self.stream_activity_window_s,
            stop_grace_s=self.stop_grace_s,
            retry_policy=self.retry_policy,
            jobs=self.jobs,
        )


OLD_FORM_PROFILE = "..\\config\\standards.example.yaml"
"""The profile as the path-bearing stamp named it before feature 014's D12: the folder too."""


def profile_stamp(digest: str, *, old_form: bool = False) -> str:
    """A standards finding's profile stamp of `digest`: the file-name form `PROFILE_LIMIT`
    writes, or, with `old_form`, the path-bearing one findings carried before D12, which
    `stamped_profile_digest` still reads (`contracts/provenance.md` 6.2)."""
    if old_form:
        return f"profile:{OLD_FORM_PROFILE} sha256:{digest}"
    return PROFILE_LIMIT.format(name="standards.example.yaml", sha256=digest)


def _provider_fields(provider: str) -> dict[str, Any]:
    """The provider, its default model and the settings it records inert (FR-052)."""
    name = ProviderName(provider)
    return {
        "provider": provider,
        "model": DEFAULT_MODELS[name],
        "inert_settings": INERT_SETTINGS[name],
    }


def _pane_settings(provider: str) -> dict[str, Any]:
    """Exactly `--pane-defaults`: the marker, and the pane's levers and model view."""
    return {
        "pane_defaults": True,
        "efficiency": pane_efficiency(ProviderName(provider)),
        "model_view": MODEL_VIEW_PANE,
    }


def pane_run_spec(
    run: str,
    arm: str,
    rep: int,
    *,
    study: str = PANE_STUDY,
    provider: str = "openai",
    explanations: bool = True,
    **overrides: Any,
) -> RunSpec:
    """One run of a pane study, as `benchmark run --study <study>` writes it.

    The on arm is exactly `--pane-defaults`, the off arm every change off; the explanation
    setting is typed, and equal in both unless a test says otherwise; the profile is the one the
    study requires (`PANE_PROFILES`), and the inert settings the provider's.
    """
    profile_digest, profile_is_example = PANE_PROFILES[study]
    fields: dict[str, Any] = {
        "lever": study,
        "explanations_enabled": explanations,
        "profile_digest": profile_digest,
        "profile_is_example": profile_is_example,
        **_provider_fields(provider),
        **(_pane_settings(provider) if arm == "on" else {}),
        **overrides,
    }
    return RunSpec(run=run, arm=arm, rep=rep, **fields)


def pane_study_specs(
    *,
    study: str = PANE_STUDY,
    provider: str = "openai",
    reps: int = 3,
    off: dict[str, Any] | None = None,
    on: dict[str, Any] | None = None,
) -> list[RunSpec]:
    """A pane study's off and on runs, alternated, with per-arm overrides: `study_specs`'s
    shape for `pane_run_spec`."""
    specs: list[RunSpec] = []
    for rep in range(1, reps + 1):
        for arm, overrides in (("off", off), ("on", on)):
            specs.append(
                pane_run_spec(
                    f"{arm}-{rep}", arm, rep, study=study, provider=provider, **(overrides or {})
                )
            )
    return specs


def pane_baseline_spec(
    run: str, rep: int, *, provider: str = "openai", **overrides: Any
) -> RunSpec:
    """`--study none --arm baseline --pane-defaults` and nothing else (PP-4): the pane's levers,
    model view and explanations, the marker set, any profile."""
    fields: dict[str, Any] = {
        "lever": NO_STUDY,
        "explanations_enabled": True,
        **_provider_fields(provider),
        **_pane_settings(provider),
        **overrides,
    }
    return RunSpec(run=run, arm="baseline", rep=rep, **fields)


def step_tools(spec: PackageSpec) -> list[str]:
    """The tool each of this package's steps called: `tool_names`, cycled.

    Read by both the session and its score, so the histogram in `scorecard.json` is the
    histogram of the steps in `session.json` rather than a second opinion about them.
    """
    return [spec.tool_names[index % len(spec.tool_names)] for index in range(spec.tool_calls)]


def package_score(spec: PackageSpec, *, served_models: Sequence[str] = ()) -> PackageScore:
    usage = spec.usage()
    timing = spec.timing()
    tag = "held_out" if spec.held_out else "tuned_on"
    false_alarm_ids = [f"F-{index:03d}" for index in range(spec.false_alarms)]
    return PackageScore(
        package_id=spec.package_id,
        held_out=spec.held_out,
        session_id=str(uuid5(NAMESPACE_URL, spec.package_id)),
        run_status={"kind": "completed", "class": None, "stop_reason": None},
        cost=SYNTHETIC_COST,
        served_models=list(served_models),
        valid_findings=spec.valid_findings,
        missed_known_defects=len(spec.missed),
        false_alarms=spec.false_alarms,
        unresolved_count=spec.unresolved,
        baseline_minutes=timing.baseline_minutes,
        assisted_minutes=spec.assisted_minutes,
        unattended_runtime_minutes=timing.unattended_runtime_minutes,
        net_saved_minutes=timing.net_saved_minutes,
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
        flagged_defect_ids=[],
        status_mismatch_defect_ids=[],
        flagged_below_expected_defect_ids=[],
        cleared_defect_ids=[],
        missed_defect_ids=list(spec.missed),
        contradicted_condition_ids=None,
        confirmed_condition_ids=None,
        false_alarm_finding_ids=false_alarm_ids,
        forbidden_hit_finding_ids=None,
        withdrawn_forbidden_hit_finding_ids=None,
        tuned_on_false_alarm_finding_ids=[],
        coverage_mismatches=None,
        finding_origins=dict.fromkeys(false_alarm_ids, "unknown"),
        graded_items=[
            GradedItem(
                id=defect_id,
                kind="known_defect",
                tag=tag,
                producer="model",
                expected_status="suspected",
            )
            for defect_id in (*spec.matched, *spec.missed)
        ],
        re_asks=[],
        open_repeats=[],
        unanswerable_requests=None,
        unmatched_requests=[],
        question_counts=None,
        unscripted_questions=None,
        bound_reached=None,
        not_assessed={
            "contradicted_condition_ids": NO_CORRECT_CONDITION,
            "confirmed_condition_ids": NO_CORRECT_CONDITION,
            "forbidden_hit_finding_ids": NO_FORBIDDEN_ENTRY,
            "withdrawn_forbidden_hit_finding_ids": NO_FORBIDDEN_ENTRY,
            "coverage_mismatches": NO_EXPECTED_COVERAGE,
            "unanswerable_requests": NO_UNANSWERABLE_REQUEST,
            "question_counts": NO_QUESTION_COUNT_RULE,
            "unscripted_questions": NO_ANSWER_LOG,
            "bound_reached": NO_ANSWER_LOG,
        },
    )


def _recall(scores: Sequence[PackageScore]) -> float | None:
    """Detected over all, over these packages' known defects; `None` with none."""
    matched = sum(len(score.matched_defect_ids) for score in scores)
    known = matched + sum(len(score.missed_defect_ids) for score in scores)
    return matched / known if known else None


def scorecard(spec: RunSpec) -> Scorecard:
    """The `scorecard.json` `benchmark score` would have written for this run."""
    per_package = [
        package_score(package, served_models=spec.served_models) for package in spec.packages
    ]
    held_out = [score for score in per_package if score.held_out]
    tuned_on = [score for score in per_package if not score.held_out]
    valid = sum(score.valid_findings for score in per_package)
    false_alarms = sum(score.false_alarms for score in per_package)
    timed = [
        score.net_saved_minutes
        for score in per_package
        if score.net_saved_minutes is not None
    ]
    by_origin = {origin: 0 for origin in get_args(Origin)} | {"unknown": false_alarms}
    return Scorecard(
        scoring_rules_version=SCORING_RULES_VERSION,
        run_id=spec.run,
        benchmark_set=SET_NAME,
        scored_at=SCORED_AT,
        per_package=per_package,
        unscored_packages=[],
        failed_attempts=[],
        price_table=None,
        aggregate=Aggregate(
            packages=len(per_package),
            cost=SYNTHETIC_COST,
            failed_attempts_cost=SYNTHETIC_COST,
            held_out_packages=len(held_out),
            valid_findings=valid,
            missed_known_defects=sum(score.missed_known_defects for score in per_package),
            false_alarms=false_alarms,
            unresolved_count=sum(score.unresolved_count for score in per_package),
            recall=_recall(held_out),
            false_alarm_rate=(
                false_alarms / (valid + false_alarms) if (valid + false_alarms) else None
            ),
            median_net_saved_minutes=median(timed) if timed else None,
            packages_with_timing=len(timed),
            input_tokens=sum_or_none(package.input_tokens for package in spec.packages),
            cached_input_tokens=sum_or_none(
                package.cached_input_tokens for package in spec.packages
            ),
            output_tokens=sum_or_none(package.output_tokens for package in spec.packages),
            reasoning_tokens=sum_or_none(package.reasoning_tokens for package in spec.packages),
            total_tokens=sum_or_none(package.total_tokens for package in spec.packages),
            round_trips=sum_or_none(package.rounds for package in spec.packages),
            median_seconds_to_first_finding=None,
            packages_with_usage=sum(1 for score in per_package if score.usage is not None),
            detected=sum(len(score.matched_defect_ids) for score in per_package),
            flagged=0,
            status_mismatches=0,
            flagged_below_expected=0,
            cleared=0,
            contradictions=None,
            confirmations=None,
            forbidden_hits=None,
            withdrawn_forbidden_hits=None,
            tuned_on_false_alarms=0,
            coverage_mismatches=None,
            findings_by_origin=by_origin,
            false_alarms_by_origin=by_origin,
            recall_by_producer=RecallByProducer(
                model=RecallByTag(held_out=_recall(held_out), tuned_on=_recall(tuned_on)),
                code=RecallByTag(held_out=None, tuned_on=None),
            ),
            held_out_model_defects=sum(
                len(score.matched_defect_ids) + len(score.missed_defect_ids) for score in held_out
            ),
            re_asks=0,
            open_repeats=0,
            unanswerable_requests=None,
            unmatched_requests=0,
            unscripted_questions=None,
            question_count_misses=None,
            bound_reached=None,
        ),
        distribution=[score.net_saved_minutes for score in per_package],
        key_sha256={package.package_id: spec.key_sha256 for package in spec.packages},
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
        explanations_enabled=spec.explanations_enabled,
        model_view=spec.model_view,
        findings=[
            make_finding(
                finding_id=f"F-{index:03d}", check=DATA_CARD_COMPLETE, coverage_limits=[stamp]
            )
            for index, stamp in enumerate(spec.standards_stamps, start=1)
        ],
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
        timing=package.timing(),
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


def saved_set_entries(spec: RunSpec) -> list[dict[str, Any]]:
    """The saved set's entries `benchmark run` would have written for this run: one per package,
    its id, a repository-relative path, and the `held_out` flag its graded items derive, true
    exactly when one is tagged held out (feature 014 `contracts/provenance.md` 2, 6.1)."""
    return [
        {
            "package_id": package.package_id,
            "path": f"benchmarks/packages/{package.package_id}",
            "held_out": any(item.tag == "held_out" for item in package_score(package).graded_items),
        }
        for package in spec.packages
    ]


def write_run(
    root: Path,
    spec: RunSpec,
    *,
    with_provenance: bool = True,
    with_saved_set: bool = True,
    session_edit: dict[str, Any] | None = None,
    saved_packages: Sequence[dict[str, Any]] | None = None,
) -> Path:
    """One complete run directory, of the shape `benchmark run` and `score` leave behind.

    `session_edit` patches the written `session.json` **after** it was serialized, which
    is how a run whose two records disagree is built: nothing in the runner can produce
    one, and the disagreement is exactly what `compare` exists to catch. `saved_packages`
    replaces the saved set's entries (`saved_set_entries`) the same way, the record's
    `set_digest` still taken over the bytes written.
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
        packages = saved_set_entries(spec) if saved_packages is None else list(saved_packages)
        saved.write_text(
            json.dumps({"name": SET_NAME, "packages": packages}, indent=2) + "\n",
            encoding="utf-8",
        )
        if spec.set_digest is None:
            recorded = replace(spec, set_digest=sha256_of(saved))
    if with_provenance:
        written = write_provenance(run_dir, recorded.provenance())
        if spec.max_answer_turns is None:
            # A record older than the field holds no `max_answer_turns` at all, not a null.
            payload = json.loads(written.read_text(encoding="utf-8"))
            del payload["max_answer_turns"]
            written.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
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


@dataclass(frozen=True)
class PanePackage:
    """One pane-study package run, with its fictional key's tags and scored outcomes.

    Infrastructure outcomes become `unscored_packages`; every other outcome is built
    through `PackageScore`. This builder neither reads a key nor writes a run folder.
    """

    package_id: str
    model_held_out: tuple[str, ...] = ("D-1", "D-2")
    model_tuned_on: tuple[str, ...] = ()
    code_held_out: tuple[str, ...] = ()
    code_tuned_on: tuple[str, ...] = ()
    matched: tuple[str, ...] = ("D-1",)
    flagged: tuple[str, ...] = ()
    cleared: tuple[str, ...] = ()
    false_alarms: tuple[tuple[str, Origin], ...] = ()
    tuned_on_false_alarms: tuple[str, ...] = ()
    status: Literal["completed", "behavioural", "infrastructure"] = "completed"
    bound_reached: bool = False
    tool_calls_by_name: tuple[tuple[str, int], ...] = (("check_fit", 1),)
    score_overrides: dict[str, Any] | None = None


def pane_run(
    run: str, arm: Literal["off", "on"], packages: Sequence[PanePackage]
) -> verdict.StudyRun:
    """A `StudyRun` over hand-built pane scorecards, with no filesystem or provider."""
    from swreview.benchmark import verdict
    from swreview.benchmark.scorecard import UnscoredPackage

    specs = tuple(
        PackageSpec(
            package_id=package.package_id,
            matched=package.matched,
            missed=tuple(
                defect for defect in package.model_held_out if defect not in package.matched
            ),
            false_alarms=len(package.false_alarms),
        )
        for package in packages
    )
    base = scorecard(RunSpec(run=run, arm=arm, lever=PANE_STUDY, packages=specs))
    scored: list[PackageScore] = []
    unscored: list[UnscoredPackage] = []
    for package, spec in zip(packages, specs, strict=True):
        if package.status == "infrastructure":
            unscored.append(
                UnscoredPackage(
                    package_id=package.package_id,
                    kind="infrastructure",
                    class_="provider_error",
                    error_class="FictionalProviderError",
                    attempts=1,
                    folder=f"attempts/{package.package_id}/1",
                )
            )
            continue
        items = [
            GradedItem(
                id=defect,
                kind="known_defect",
                tag=tag,
                producer=producer,
                expected_status="suspected",
            )
            for producer, tag, ids in (
                ("model", "held_out", package.model_held_out),
                ("model", "tuned_on", package.model_tuned_on),
                ("code", "held_out", package.code_held_out),
                ("code", "tuned_on", package.code_tuned_on),
            )
            for defect in ids
        ]
        detected = set(package.matched) | set(package.flagged)
        missed = [item.id for item in items if item.id not in detected | set(package.cleared)]
        payload = package_score(spec).model_dump()
        payload.update(
            held_out=any(item.tag == "held_out" for item in items),
            run_status={
                "kind": package.status,
                "class": "max_steps" if package.status == "behavioural" else None,
                "stop_reason": "max_steps" if package.status == "behavioural" else None,
            },
            valid_findings=len(detected),
            missed_known_defects=len(missed),
            matched_defect_ids=list(package.matched),
            flagged_defect_ids=list(package.flagged),
            cleared_defect_ids=list(package.cleared),
            missed_defect_ids=missed,
            false_alarm_finding_ids=[finding for finding, _ in package.false_alarms],
            finding_origins=dict(package.false_alarms),
            tuned_on_false_alarm_finding_ids=list(package.tuned_on_false_alarms),
            graded_items=items,
            tool_calls_by_name=dict(package.tool_calls_by_name),
            bound_reached=package.bound_reached,
        )
        payload["not_assessed"].pop("bound_reached", None)
        payload.update(package.score_overrides or {})
        scored.append(PackageScore.model_validate(payload))

    def recall(producer: str, tag: str) -> float | None:
        known = [
            (score, item)
            for score in scored
            for item in score.graded_items
            if item.producer == producer and item.tag == tag
        ]
        return (
            sum(
                item.id in set(score.matched_defect_ids) | set(score.flagged_defect_ids)
                for score, item in known
            ) / len(known)
            if known else None
        )

    by_origin = dict.fromkeys(get_args(Origin), 0)
    for score in scored:
        for finding in score.false_alarm_finding_ids:
            by_origin[score.finding_origins[finding]] += 1
    aggregate = base.aggregate.model_dump()
    aggregate.update(
        packages=len(scored),
        held_out_packages=sum(score.held_out for score in scored),
        valid_findings=sum(score.valid_findings for score in scored),
        missed_known_defects=sum(score.missed_known_defects for score in scored),
        false_alarms=sum(score.false_alarms for score in scored),
        detected=sum(len(set(score.matched_defect_ids) | set(score.flagged_defect_ids))
                     for score in scored),
        flagged=sum(len(score.flagged_defect_ids) for score in scored),
        cleared=sum(len(score.cleared_defect_ids) for score in scored),
        tuned_on_false_alarms=sum(len(score.tuned_on_false_alarm_finding_ids) for score in scored),
        bound_reached=sum(bool(score.bound_reached) for score in scored),
        findings_by_origin=by_origin,
        false_alarms_by_origin=by_origin,
        recall_by_producer=RecallByProducer(
            model=RecallByTag(held_out=recall("model", "held_out"),
                              tuned_on=recall("model", "tuned_on")),
            code=RecallByTag(held_out=recall("code", "held_out"),
                             tuned_on=recall("code", "tuned_on")),
        ),
        held_out_model_defects=sum(len(package.model_held_out) for package in packages),
    )
    payload = base.model_dump()
    payload.update(per_package=scored, unscored_packages=unscored,
                   aggregate=Aggregate.model_validate(aggregate))
    return verdict.StudyRun(run=run, arm=arm, scorecard=Scorecard.model_validate(payload))
