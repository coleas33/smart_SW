"""Unit tests for the scorecard's usage columns (T023, contracts/usage.md 9).

What a run cost belongs beside what it found, because every adoption decision in this
feature reads both: a lever that halves the token bill and loses a known defect is not
adopted. `PackageScore` therefore gains `usage`, `round_trips`, `cached_input_share`,
`wall_clock_s` and `seconds_to_first_finding`, and `Aggregate` gains the summed counts
under the same any-null-makes-the-sum-null rule `SessionUsage.summed` already applies one
level down.

Three rules decide the tests here.

**No new recording.** `seconds_to_first_finding` comes from the `at` stamps that
`session.started` and the first `finding` event already carry, read from the
`events.jsonl` sitting beside the `session.json` the scorer already opens. `score_run`
gains one file read per package and **no answer-key contact**, so Principle VI and FR-025
are untouched, and a run directory with no `events.jsonl` scores with a null rather than
raising.

**Unknown stays unknown.** A session with no usage scores to nulls, never to zeroes, and
one package contributing a null makes that aggregate total null rather than a partial sum
that silently understates.

**The cached share is computed from the start and published only once probe L1 is
recorded** (FR-047): the share is well defined only if cached input is contained in
input, which is VERIFIED for Gemini and UNVERIFIED for OpenAI until L1 runs. `PackageScore`
carries the number; `render_scorecard_md` prints `unknown` until `CACHED_SHARE_PUBLISHABLE`
says the containment was measured.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

import pytest
from jsonschema import Draft202012Validator

from swreview.agent.providers import TokenUsage
from swreview.benchmark.answer_key import AnswerKey, KnownDefect
from swreview.benchmark.scorecard import Scorecard, render_scorecard_md, score_run
from swreview.benchmark.sets import BenchmarkPackageRef, BenchmarkSet
from swreview.findings import build_finding
from swreview.report.session import ReviewSession, SessionUsage, Timing, save_session
from tests.support.contracts import load_contract
from tests.support.packages import build_package

PACKAGE = build_package()

STARTED_AT = datetime(2026, 9, 12, 9, 0, tzinfo=UTC)
ENDED_AT = datetime(2026, 9, 12, 9, 30, tzinfo=UTC)
WALL_CLOCK_S = 1_800.0
"""`STARTED_AT` to `ENDED_AT`. Deliberately not `unattended_runtime_minutes`, which the
benchmark runner overwrites with its own `perf_counter` span (contracts/usage.md 9)."""


def make_usage(**overrides: object) -> TokenUsage:
    """One round trip, fully reported, with cached inside input and reasoning inside
    output, so the derived share and uncached count have numbers that actually add up.
    """
    fields: dict[str, object] = {
        "input_tokens": 12_043,
        "cached_input_tokens": 10_240,
        "cache_write_tokens": 1_803,
        "output_tokens": 512,
        "reasoning_tokens": 448,
        "tool_result_input_tokens": None,
        "total_tokens": 12_555,
        "latency_s": 4.31,
    }
    fields.update(overrides)
    return TokenUsage(**fields)  # type: ignore[arg-type]


def write_events(package_dir: Path, *, first_finding_after_s: float | None) -> None:
    """The two events the scorer reads: `session.started`, and the first `finding`.

    Written as `EventSink` writes them, one JSON object per line with `seq`, `at`, `type`
    and `body`, with a `tool.started` in between so the scorer has to find the *first*
    finding rather than the second line.
    """
    events: list[dict[str, Any]] = [
        {"seq": 1, "at": STARTED_AT.isoformat(), "type": "session.started", "body": {}},
        {
            "seq": 2,
            "at": (STARTED_AT + timedelta(seconds=1)).isoformat(),
            "type": "tool.started",
            "body": {"step_index": 0, "tool": "list_holes"},
        },
    ]
    if first_finding_after_s is not None:
        for offset, seq in ((first_finding_after_s, 3), (first_finding_after_s + 60.0, 4)):
            events.append(
                {
                    "seq": seq,
                    "at": (STARTED_AT + timedelta(seconds=offset)).isoformat(),
                    "type": "finding",
                    "body": {"id": f"F-{seq:03d}"},
                }
            )
    (package_dir / "events.jsonl").write_text(
        "".join(json.dumps(event) + "\n" for event in events), encoding="utf-8"
    )


def write_package(
    run_dir: Path,
    answer_keys_dir: Path,
    package_id: str,
    *,
    usage: SessionUsage | None,
    with_findings: bool = True,
    first_finding_after_s: float | None = 42.0,
    with_events: bool = True,
    ended_at: datetime | None = ENDED_AT,
) -> BenchmarkPackageRef:
    """One scored package: its answer key, its `session.json` and its `events.jsonl`."""
    answer_key = AnswerKey(
        package_id=package_id,
        known_defects=[
            KnownDefect(
                id=f"{package_id}-D-1",
                check="fastener.bottoming",
                component_ids=["cmp:0001"],
                description="d1",
            )
        ],
        correct_conditions=[],
    )
    (answer_keys_dir / f"{package_id}.json").write_text(
        answer_key.model_dump_json(), encoding="utf-8"
    )

    findings = (
        [
            build_finding(
                finding_id="F-001",
                check="fastener.bottoming",
                title="t",
                status="demonstrated",
                severity="high",
                package=PACKAGE,
                configuration="Default",
                observed="o",
                requirement="r",
                recommended_action="a",
                component_ids=["cmp:0001"],
                tool_result_ids=[0],
            )
        ]
        if with_findings
        else []
    )
    session = ReviewSession(
        session_id=uuid5(NAMESPACE_URL, package_id),
        package_id=PACKAGE.package_id,
        design_id=PACKAGE.design.design_id,
        started_at=STARTED_AT,
        ended_at=ended_at,
        model="gpt-5.6",
        findings=findings,
        timing=Timing(
            baseline_minutes=90.0,
            assisted_supervision_minutes=10.0,
            assisted_verification_minutes=8.0,
            false_alarm_handling_minutes=2.0,
            unattended_runtime_minutes=25.0,
        ),
        usage=usage,
    )
    package_dir = run_dir / package_id
    save_session(session, package_dir / "session.json")
    if with_events:
        write_events(
            package_dir,
            first_finding_after_s=first_finding_after_s if with_findings else None,
        )
    return BenchmarkPackageRef(package_id=package_id, path=Path("unused"), held_out=True)


def build_run(tmp_path: Path, **kwargs: object) -> tuple[Path, Path, BenchmarkSet]:
    """A one-package run, fully reported unless a keyword says otherwise."""
    run_dir = tmp_path / "run"
    answer_keys_dir = tmp_path / "benchmarks" / "answer_keys"
    answer_keys_dir.mkdir(parents=True)
    defaults: dict[str, object] = {"usage": SessionUsage.summed([make_usage()], [1])}
    defaults.update(kwargs)
    ref = write_package(run_dir, answer_keys_dir, "pkg-a", **defaults)  # type: ignore[arg-type]
    return run_dir, answer_keys_dir, BenchmarkSet(name="pilot", packages=[ref])


def score(tmp_path: Path, **kwargs: object) -> Scorecard:
    run_dir, answer_keys_dir, benchmark_set = build_run(tmp_path, **kwargs)
    return score_run(run_dir, answer_keys_dir, benchmark_set)


# --- PackageScore: what one package cost ----------------------------------------------


def test_package_score_copies_the_session_totals_verbatim(tmp_path: Path) -> None:
    """`usage` is the session's own `usage.totals`, not a re-sum: two writers of one
    number is how the ledger and the session come to disagree.
    """
    usage = SessionUsage.summed([make_usage(), make_usage()], [2])

    scorecard = score(tmp_path, usage=usage)

    assert scorecard.per_package[0].usage == usage.totals


def test_package_score_round_trips_come_from_the_session(tmp_path: Path) -> None:
    """Round trips, not tool calls: the two diverge by exactly what lever 6 saves."""
    usage = SessionUsage.summed([make_usage(), make_usage(), make_usage()], [2])

    scorecard = score(tmp_path, usage=usage)

    assert scorecard.per_package[0].round_trips == 3


def test_package_score_derives_the_cached_input_share(tmp_path: Path) -> None:
    scorecard = score(tmp_path)

    assert scorecard.per_package[0].cached_input_share == pytest.approx(10_240 / 12_043)


def test_the_cached_share_is_null_when_either_count_is_unknown(tmp_path: Path) -> None:
    usage = SessionUsage.summed([make_usage(cached_input_tokens=None)], [1])

    scorecard = score(tmp_path, usage=usage)

    assert scorecard.per_package[0].cached_input_share is None


def test_the_cached_share_of_zero_input_is_null_and_not_zero(tmp_path: Path) -> None:
    """A share of nothing is not zero (data-model section 2.1)."""
    usage = SessionUsage.summed(
        [make_usage(input_tokens=0, cached_input_tokens=0, total_tokens=512)], [1]
    )

    scorecard = score(tmp_path, usage=usage)

    assert scorecard.per_package[0].cached_input_share is None


def test_a_run_reporting_more_cached_than_input_still_scores(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The containment probe L1 settles is UNVERIFIED for OpenAI (FR-047), so a run may
    report `cached > input`. Scoring it MUST NOT raise: an unverified fact would
    otherwise make the whole benchmark run unscoreable, which is the one outcome the
    FR-047 gating exists to avoid. The share is unknown, the raw counts are kept, and the
    column says `unknown` even with the share published.
    """
    usage = SessionUsage.summed(
        [make_usage(input_tokens=1_000, cached_input_tokens=1_200)], [1]
    )

    scorecard = score(tmp_path, usage=usage)

    score_row = scorecard.per_package[0]
    assert score_row.cached_input_share is None
    assert score_row.usage is not None
    assert (score_row.usage.input_tokens, score_row.usage.cached_input_tokens) == (1_000, 1_200)

    monkeypatch.setattr("swreview.benchmark.scorecard.CACHED_SHARE_PUBLISHABLE", True)
    cells = row_cells(render_scorecard_md(scorecard), "pkg-a")
    assert "unknown" in cells
    assert not any("%" in cell for cell in cells)


def test_wall_clock_is_started_to_ended_and_not_the_runners_own_span(tmp_path: Path) -> None:
    scorecard = score(tmp_path)

    score_row = scorecard.per_package[0]
    assert score_row.wall_clock_s == pytest.approx(WALL_CLOCK_S)
    assert score_row.unattended_runtime_minutes == pytest.approx(25.0)


def test_wall_clock_is_null_on_a_session_that_never_ended(tmp_path: Path) -> None:
    scorecard = score(tmp_path, ended_at=None)

    assert scorecard.per_package[0].wall_clock_s is None


# --- seconds to the first finding, read from the event stream -------------------------


def test_seconds_to_first_finding_is_read_from_the_event_stream(tmp_path: Path) -> None:
    scorecard = score(tmp_path, first_finding_after_s=42.0)

    assert scorecard.per_package[0].seconds_to_first_finding == pytest.approx(42.0)


def test_seconds_to_first_finding_is_null_when_the_run_found_nothing(tmp_path: Path) -> None:
    scorecard = score(tmp_path, with_findings=False)

    assert scorecard.per_package[0].seconds_to_first_finding is None


def test_a_run_directory_with_no_event_stream_scores_with_a_null(tmp_path: Path) -> None:
    """A run made before the stream was kept is still a real run, not an error."""
    scorecard = score(tmp_path, with_events=False)

    assert scorecard.per_package[0].seconds_to_first_finding is None
    assert scorecard.per_package[0].valid_findings == 1


def test_a_truncated_event_stream_scores_with_a_null(tmp_path: Path) -> None:
    """A process killed mid-review leaves a half-written last line. The session is still
    the record, so the run is still scored and only this one column is unknown.
    """
    run_dir, answer_keys_dir, benchmark_set = build_run(tmp_path)
    events_path = run_dir / "pkg-a" / "events.jsonl"
    kept = events_path.read_text(encoding="utf-8").splitlines()[:2]
    truncated = '{"seq": 3, "at": "2026-'
    events_path.write_text("\n".join([*kept, truncated]), encoding="utf-8")

    scorecard = score_run(run_dir, answer_keys_dir, benchmark_set)

    assert scorecard.per_package[0].seconds_to_first_finding is None
    assert scorecard.per_package[0].valid_findings == 1


# --- a session with no usage at all ----------------------------------------------------


def test_a_session_without_usage_scores_to_nulls_and_does_not_raise(tmp_path: Path) -> None:
    scorecard = score(tmp_path, usage=None)

    score_row = scorecard.per_package[0]
    assert score_row.usage is None
    assert score_row.round_trips is None
    assert score_row.cached_input_share is None
    assert score_row.valid_findings == 1


# --- Aggregate: summed over packages, any null makes the sum null ---------------------


def build_two_package_run(
    tmp_path: Path, *, second_usage: SessionUsage | None
) -> tuple[Path, Path, BenchmarkSet]:
    run_dir = tmp_path / "run"
    answer_keys_dir = tmp_path / "benchmarks" / "answer_keys"
    answer_keys_dir.mkdir(parents=True)
    first = write_package(
        run_dir,
        answer_keys_dir,
        "pkg-a",
        usage=SessionUsage.summed([make_usage()], [1]),
        first_finding_after_s=42.0,
    )
    second = write_package(
        run_dir,
        answer_keys_dir,
        "pkg-b",
        usage=second_usage,
        first_finding_after_s=108.0,
    )
    return run_dir, answer_keys_dir, BenchmarkSet(name="pilot", packages=[first, second])


def test_aggregate_sums_the_token_counts_over_packages(tmp_path: Path) -> None:
    run_dir, keys, benchmark_set = build_two_package_run(
        tmp_path, second_usage=SessionUsage.summed([make_usage()], [1])
    )

    aggregate = score_run(run_dir, keys, benchmark_set).aggregate

    assert aggregate.input_tokens == 24_086
    assert aggregate.cached_input_tokens == 20_480
    assert aggregate.output_tokens == 1_024
    assert aggregate.reasoning_tokens == 896
    assert aggregate.total_tokens == 25_110
    assert aggregate.round_trips == 2
    assert aggregate.packages_with_usage == 2


def test_one_package_without_usage_makes_every_aggregate_total_null(tmp_path: Path) -> None:
    """Not a partial sum: a partial sum silently understates and no reader can tell."""
    run_dir, keys, benchmark_set = build_two_package_run(tmp_path, second_usage=None)

    aggregate = score_run(run_dir, keys, benchmark_set).aggregate

    assert aggregate.input_tokens is None
    assert aggregate.total_tokens is None
    assert aggregate.round_trips is None
    assert aggregate.packages_with_usage == 1


def test_one_null_sub_count_leaves_the_other_aggregate_totals_summed(tmp_path: Path) -> None:
    run_dir, keys, benchmark_set = build_two_package_run(
        tmp_path, second_usage=SessionUsage.summed([make_usage(reasoning_tokens=None)], [1])
    )

    aggregate = score_run(run_dir, keys, benchmark_set).aggregate

    assert aggregate.reasoning_tokens is None
    assert aggregate.input_tokens == 24_086
    assert aggregate.packages_with_usage == 2


def test_median_seconds_to_first_finding_covers_the_packages_that_found_something(
    tmp_path: Path,
) -> None:
    run_dir, keys, benchmark_set = build_two_package_run(
        tmp_path, second_usage=SessionUsage.summed([make_usage()], [1])
    )

    aggregate = score_run(run_dir, keys, benchmark_set).aggregate

    assert aggregate.median_seconds_to_first_finding == pytest.approx(75.0)


def test_median_seconds_to_first_finding_is_null_when_nothing_was_found(
    tmp_path: Path,
) -> None:
    scorecard = score(tmp_path, with_findings=False)

    assert scorecard.aggregate.median_seconds_to_first_finding is None


def test_packages_with_usage_is_zero_when_no_session_carried_any(tmp_path: Path) -> None:
    scorecard = score(tmp_path, usage=None)

    assert scorecard.aggregate.packages_with_usage == 0
    assert scorecard.aggregate.total_tokens is None


# --- the markdown gains three columns, not seven --------------------------------------


def header_cells(rendered: str) -> list[str]:
    header = next(line for line in rendered.splitlines() if line.startswith("| package "))
    return [cell.strip() for cell in header.strip("|").split("|")]


def row_cells(rendered: str, package_id: str) -> list[str]:
    row = next(line for line in rendered.splitlines() if line.startswith(f"| {package_id} "))
    return [cell.strip() for cell in row.strip("|").split("|")]


def test_the_markdown_gains_exactly_three_usage_columns(tmp_path: Path) -> None:
    """The markdown is a scan; `scorecard.json` holds the other four counts."""
    rendered = render_scorecard_md(score(tmp_path))

    cells = header_cells(rendered)
    assert "total tokens" in cells
    assert "cached share" in cells
    assert "round trips" in cells
    assert "input" not in cells
    assert "reasoning" not in cells
    assert "cache write" not in cells
    assert "output" not in cells


def test_the_markdown_prints_the_totals_and_round_trips(tmp_path: Path) -> None:
    usage = SessionUsage.summed([make_usage(), make_usage()], [2])

    rendered = render_scorecard_md(score(tmp_path, usage=usage))

    cells = row_cells(rendered, "pkg-a")
    assert "25110" in cells
    assert "2" in cells


def test_the_cached_share_column_is_unknown_until_probe_l1_is_recorded(
    tmp_path: Path,
) -> None:
    """FR-047 as a behaviour, not a footnote: the number is computed and carried in
    `scorecard.json`, and the published column says `unknown` until L1 has recorded that
    cached input is contained in input.
    """
    scorecard = score(tmp_path)

    rendered = render_scorecard_md(scorecard)

    cells = row_cells(rendered, "pkg-a")
    assert "unknown" in cells
    assert not any("%" in cell for cell in cells)
    assert scorecard.per_package[0].cached_input_share is not None


def test_the_cached_share_column_is_a_percentage_once_probe_l1_is_recorded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("swreview.benchmark.scorecard.CACHED_SHARE_PUBLISHABLE", True)

    rendered = render_scorecard_md(score(tmp_path))

    assert "85%" in row_cells(rendered, "pkg-a")


def test_an_unknown_count_renders_as_unknown_and_never_as_zero(tmp_path: Path) -> None:
    rendered = render_scorecard_md(score(tmp_path, usage=None))

    cells = row_cells(rendered, "pkg-a")
    assert cells.count("unknown") == 3, cells
    assert "0" not in cells[-3:]


def test_the_aggregate_block_states_how_many_packages_carried_usage(tmp_path: Path) -> None:
    rendered = render_scorecard_md(score(tmp_path))

    assert "- total tokens (1 packages with usage): 12555" in rendered
    assert "- round trips: 1" in rendered
    assert "- median seconds to first finding: 42.0 s" in rendered


# --- the contract --------------------------------------------------------------------


def test_a_scorecard_with_usage_validates_against_the_contract(tmp_path: Path) -> None:
    payload = score(tmp_path).model_dump(mode="json")

    validator = Draft202012Validator(
        load_contract("scorecard.schema.json"), format_checker=Draft202012Validator.FORMAT_CHECKER
    )
    errors = sorted(validator.iter_errors(payload), key=lambda e: list(e.absolute_path))

    assert errors == [], [f"{list(e.absolute_path)}: {e.message}" for e in errors]


def test_a_scorecard_without_usage_validates_against_the_contract(tmp_path: Path) -> None:
    payload = score(tmp_path, usage=None, ended_at=None, with_events=False).model_dump(mode="json")

    validator = Draft202012Validator(
        load_contract("scorecard.schema.json"), format_checker=Draft202012Validator.FORMAT_CHECKER
    )
    errors = sorted(validator.iter_errors(payload), key=lambda e: list(e.absolute_path))

    assert errors == [], [f"{list(e.absolute_path)}: {e.message}" for e in errors]
