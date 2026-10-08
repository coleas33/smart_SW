"""`benchmark run`'s options, its refusals before any review, and the attempt request (T048).

`specs/014-design-review-eval/contracts/benchmark-run.md` sections 2, 3 and 5.1 (RUN-03, RUN-04,
RUN-05, RUN-14, RUN-16, RF-19, RF-44, INT-14; FR-011, FR-050; US2-1, US2-2):

1. **One resolver.** `--pane-defaults`, the model-view switches and the explanation setting
   resolve through `cli._review_settings` alone, with `allow_workstation_levers=False` and the
   typed study and arm, so the workstation-lever refusal and the study checks still hold (RF-19).
2. **Refusals before any review**, in section 3's order, each one line and exit 1 with no review
   started and nothing written: a non-empty `--out`, a profile that cannot load (while `review`
   keeps recording the refusal and going on), and a provider or effort that does not resolve,
   refused once rather than on every package.
3. **P-3.** `--pane-defaults`, `--payload-slimming` and `--history-pruning` declare a study as
   `--lever` does; `--standards-profile` alone does not (PP-6).
4. **Provenance first.** The record and the saved set are on disk before the first review.
5. **The attempt request.** `run_benchmark` hands the review function `attempt`, an
   `AttemptRequest` carrying the model view and the profile, beside today's keywords, and
   `cli._review_fn` passes both to the review with the live tools off (RF-44). The
   scripted-answers slice (lane A3, T095) adds the case file `preflight_set` loaded for the
   package and the answer-turn bound.

The scripted-answers slice's tests (lane A3, T095): `test_a_package_id_attempts_is_refused` (row 4
in `preflight_set`, ignoring case, owner decision 48A), the attempt request grown by the case file
and the bound, and row 6's carriage return in a case file the set names. The price row, the
package time limit and the resume pointer are lane B6's (T201, T203). Offline: the scripted
provider, and a spy wherever a review would run.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from swreview import cli
from swreview.agent.checklist import load_checklist
from swreview.agent.providers import EffortLevel, ProviderName
from swreview.agent.providers.fake import FakeProvider, ScriptedTurn
from swreview.agent.settings import (
    MODEL_VIEW_OFF,
    MODEL_VIEW_PANE,
    PANE_STUDY,
    WORKSTATION_LEVERS,
    EfficiencySettings,
    ProviderSettings,
    pane_defaults,
)
from swreview.benchmark.case_file import CaseFile
from swreview.benchmark.runner import PROVENANCE_FILE, AttemptRequest, preflight_set, run_benchmark
from swreview.checks.standards.profile import ProfileInvalid, ProfileUnreadable, load_profile
from swreview.prerun import PRERUN_CHECK_PREFIX, STANDARDS_FAMILY_NAME
from swreview.report.session import load_session
from tests.unit.test_benchmark_case_file import PACKAGE_ID, case, case_file_set, item_answer
from tests.unit.test_run_provenance import example_profile_copy, one_package_set, read_record

SAVED_SET_FILE = "benchmark-set.json"
STANDARDS_CHECK = f"{PRERUN_CHECK_PREFIX}{STANDARDS_FAMILY_NAME}"

runner = CliRunner()


def invoke(*args: str) -> Any:
    return runner.invoke(cli.app, list(args))


def benchmark_run(set_path: Path, out: Path, *options: str) -> Any:
    """`swreview benchmark run --provider fake` of `set_path` into `out`, with `options`."""
    return invoke(
        "benchmark",
        "run",
        "--set",
        str(set_path),
        "--out",
        str(out),
        "--provider",
        "fake",
        *options,
    )


def one_line(result: Any) -> str:
    """The one line a refusal prints on stderr; fails unless it is exactly one."""
    lines = result.stderr.strip().splitlines()
    assert len(lines) == 1, result.stderr
    return lines[0]


def two_package_set(tmp_path: Path, package_dir: Path) -> Path:
    """A set of two packages, the second a copy of the first, both held out."""
    second = tmp_path / "second-package"
    shutil.copytree(package_dir, second)
    set_path = tmp_path / "sets" / "two.json"
    set_path.parent.mkdir(parents=True, exist_ok=True)
    set_path.write_text(
        json.dumps(
            {
                "name": "two",
                "packages": [
                    {"package_id": "cover", "path": str(package_dir), "held_out": True},
                    {"package_id": "cover-copy", "path": str(second), "held_out": True},
                ],
            }
        ),
        encoding="utf-8",
    )
    return set_path


@pytest.fixture
def reviews(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Swap `cli._review_fn` for a spy that records each call and reviews nothing."""
    calls: list[dict[str, Any]] = []

    def spy(package_dir: Path, session_out_dir: Path, **keywords: Any) -> None:
        calls.append({"package_dir": package_dir, "out_dir": session_out_dir, **keywords})

    monkeypatch.setattr(cli, "_review_fn", spy)
    return calls


# --- 1. one resolver (FR-011, RF-19) ---------------------------------------------


@pytest.fixture
def resolutions(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Watch `cli._review_settings` and `cli._efficiency`: each resolution's switches and its
    result or refusal, and every `_efficiency` call made outside a resolution."""
    resolver = cli._review_settings
    levers = cli._efficiency
    seen: list[dict[str, Any]] = []
    depth: list[int] = []

    def watched_resolver(provider: ProviderName, **switches: Any) -> Any:
        entry: dict[str, Any] = {"provider": provider, "switches": switches}
        seen.append(entry)
        depth.append(1)
        try:
            entry["result"] = resolver(provider, **switches)
        except BaseException as refusal:
            entry["refusal"] = refusal
            raise
        finally:
            depth.pop()
        return entry["result"]

    def watched_levers(*args: Any, **kwargs: Any) -> Any:
        if not depth:
            seen.append({"outside": (args, kwargs)})
        return levers(*args, **kwargs)

    monkeypatch.setattr(cli, "_review_settings", watched_resolver)
    monkeypatch.setattr(cli, "_efficiency", watched_levers)
    return seen


def test_benchmark_run_resolves_pane_defaults_model_view_and_profile_through_review_settings(
    tmp_path: Path,
    tmp_package_dir: Path,
    reviews: list[dict[str, Any]],
    resolutions: list[dict[str, Any]],
) -> None:
    """FR-011: the pane baseline (`--study none --arm baseline --pane-defaults`) with a typed
    `--no-explain-findings` and a profile is resolved by one call of `_review_settings`, and
    what it resolved is what the record says and what the review receives."""
    profile = example_profile_copy(tmp_path / "profiles")
    set_path = one_package_set(tmp_path, tmp_package_dir)
    out = tmp_path / "runs" / "pane-baseline"

    result = benchmark_run(
        set_path,
        out,
        "--study",
        "none",
        "--arm",
        "baseline",
        "--pane-defaults",
        "--no-explain-findings",
        "--standards-profile",
        str(profile),
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    [resolution] = resolutions
    assert resolution["provider"] == ProviderName.FAKE
    assert resolution["switches"] == {
        "pane_defaults": True,
        "lever": None,
        "payload_slimming": False,
        "history_pruning": False,
        "prune_after": None,
        "explain_findings": False,
        "study": "none",
        "arm": "baseline",
        "allow_workstation_levers": False,
    }
    pane = pane_defaults(ProviderName.FAKE)
    assert resolution["result"] == cli.ResolvedReview(pane.efficiency, pane.model_view, False)
    record = read_record(out)
    assert record["pane_defaults"] is True
    assert record["efficiency"] == pane.efficiency.model_dump(mode="json")
    assert record["model_view"] == pane.model_view.model_dump(mode="json")
    assert record["explanations_enabled"] is False
    [review] = reviews
    assert review["efficiency"] == pane.efficiency
    assert review["attempt"] == AttemptRequest(
        model_view=pane.model_view, standards_profile=profile, case_file=None, max_answer_turns=3
    )
    assert "explain_findings" not in review


@pytest.mark.parametrize(
    ("options", "words"),
    [
        (("--lever", WORKSTATION_LEVERS[0]), "workstation harness"),
        (("--study", "tool_tiers", "--arm", "on"), "tool_tiers"),
    ],
    ids=["workstation-lever", "study-arm-contradiction"],
)
def test_benchmark_run_still_refuses_a_workstation_lever_and_a_study_arm_contradiction(
    tmp_path: Path,
    tmp_package_dir: Path,
    reviews: list[dict[str, Any]],
    resolutions: list[dict[str, Any]],
    options: Sequence[str],
    words: str,
) -> None:
    """RF-19: exit 2, a usage error naming the rule, raised inside `_review_settings`."""
    set_path = one_package_set(tmp_path, tmp_package_dir)
    out = tmp_path / "runs" / "refused"

    result = benchmark_run(set_path, out, *options)

    assert result.exit_code == 2
    assert words in result.stdout + result.stderr
    [resolution] = resolutions
    assert "refusal" in resolution
    assert resolution["switches"]["allow_workstation_levers"] is False
    assert reviews == []
    assert not out.exists()


# --- 2. refusals before any review (section 3) -------------------------------------


def test_a_non_empty_out_folder_is_refused(
    tmp_path: Path, tmp_package_dir: Path, reviews: list[dict[str, Any]]
) -> None:
    """Row 1: a second run into one folder would append a second session with duplicate
    sequence numbers. The parity slice's message names no command: `benchmark resume` does not
    exist yet (its pointer is lane B6's). An empty folder, or none, is a fresh run."""
    set_path = one_package_set(tmp_path, tmp_package_dir)
    used = tmp_path / "runs" / "used"
    used.mkdir(parents=True)
    (used / "notes.txt").write_text("an earlier run's notes\n", encoding="utf-8")
    occupied = tmp_path / "runs" / "a-file"
    occupied.write_text("not a folder\n", encoding="utf-8")

    for out in (used, occupied):
        result = benchmark_run(set_path, out)

        assert result.exit_code == 1, out
        line = one_line(result)
        assert line.endswith(f"{out} is not empty; choose a new folder"), line
        assert "swreview" not in line and "resume" not in line
    assert reviews == []
    assert sorted(path.name for path in used.iterdir()) == ["notes.txt"]
    assert occupied.read_text(encoding="utf-8") == "not a folder\n"

    empty = tmp_path / "runs" / "empty"
    empty.mkdir()
    assert benchmark_run(set_path, empty).exit_code == 0
    assert len(reviews) == 1


def refusal_line(error: type[Exception], path: Path) -> str:
    """The line `_errors_as_exit_1` prints for `load_profile(path)`'s refusal."""
    with pytest.raises(error) as refused:
        load_profile(path)
    return f"error: {error.__name__}: {' '.join(str(refused.value).split())}"


def test_an_unreadable_profile_stops_the_benchmark_with_one_line(
    tmp_path: Path, tmp_package_dir: Path, reviews: list[dict[str, Any]]
) -> None:
    """Row 2 (US2-2, FR-050): the class and its message, before any review."""
    set_path = one_package_set(tmp_path, tmp_package_dir)
    missing = tmp_path / "profiles" / "absent.yaml"
    out = tmp_path / "runs" / "no-profile"

    result = benchmark_run(set_path, out, "--standards-profile", str(missing))

    assert result.exit_code == 1
    assert one_line(result) == refusal_line(ProfileUnreadable, missing)
    assert reviews == []
    assert not out.exists()


def broken_profile(tmp_path: Path) -> Path:
    """A profile file that reads but is no profile this build can use."""
    broken = tmp_path / "profiles" / "broken.yaml"
    broken.parent.mkdir(parents=True, exist_ok=True)
    broken.write_text("version: 99\n", encoding="utf-8")
    return broken


def test_an_invalid_profile_stops_the_benchmark_with_one_line(
    tmp_path: Path, tmp_package_dir: Path, reviews: list[dict[str, Any]]
) -> None:
    """Row 2 (US2-2, FR-050): a study graded against nothing would read as a study graded."""
    set_path = one_package_set(tmp_path, tmp_package_dir)
    broken = broken_profile(tmp_path)
    out = tmp_path / "runs" / "broken-profile"

    result = benchmark_run(set_path, out, "--standards-profile", str(broken))

    assert result.exit_code == 1
    assert one_line(result) == refusal_line(ProfileInvalid, broken)
    assert reviews == []
    assert not out.exists()


def test_review_still_records_a_profile_refusal_and_goes_on(
    tmp_path: Path, tmp_package_dir: Path
) -> None:
    """FR-050: the profile is loaded in `benchmark run`, never in the shared resolver, so
    `review` keeps recording the refusal as a skipped standards item and finishing."""
    broken = broken_profile(tmp_path)
    out = tmp_path / "review"

    result = invoke(
        "review",
        str(tmp_package_dir),
        "--out",
        str(out),
        "--provider",
        "fake",
        "--standards-profile",
        str(broken),
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    session = load_session(out / "session.json")
    assert session.ended_at is not None
    skipped = {item.check: item.reason for item in session.coverage.skipped}
    assert "broken.yaml" in skipped[STANDARDS_CHECK]


class EffortRefused(ValueError):
    """What an adapter raises for an effort its model does not offer."""


class NoSuchEffort(FakeProvider):
    """A scripted adapter whose model offers no effort at all."""

    def effort_mapping(self, effort: EffortLevel) -> Any:
        raise EffortRefused(f"model {self.model!r} does not offer effort {effort!r}")


def test_an_unresolvable_effort_is_refused_once(
    tmp_path: Path,
    tmp_package_dir: Path,
    reviews: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Row 3 (RUN-16): one adapter is built and its effort mapped before any review, so a
    two-package set is refused once rather than failing the same way on every package."""
    built: list[NoSuchEffort] = []

    def factory(
        settings: ProviderSettings, efficiency: EfficiencySettings | None = None
    ) -> NoSuchEffort:
        adapter = NoSuchEffort(script=[ScriptedTurn(text="done")], model=settings.model)
        built.append(adapter)
        return adapter

    monkeypatch.setattr(cli, "provider_factory", factory)
    set_path = two_package_set(tmp_path, tmp_package_dir)
    out = tmp_path / "runs" / "no-effort"

    result = benchmark_run(set_path, out, "--effort", "xhigh")

    assert result.exit_code == 1
    assert one_line(result).startswith("error: EffortRefused: model ")
    assert len(built) == 1
    assert reviews == []
    assert not out.exists()


def set_of(tmp_path: Path, package_dir: Path, package_id: str) -> Path:
    """A one-package set whose one entry has the id `package_id`."""
    set_path = tmp_path / "sets" / f"{package_id}.json"
    set_path.parent.mkdir(parents=True, exist_ok=True)
    entry = {"package_id": package_id, "path": str(package_dir), "held_out": True}
    set_path.write_text(json.dumps({"name": package_id, "packages": [entry]}), encoding="utf-8")
    return set_path


@pytest.mark.parametrize("package_id", ["attempts", "Attempts", "ATTEMPTS"])
def test_a_package_id_attempts_is_refused(
    tmp_path: Path, tmp_package_dir: Path, reviews: list[dict[str, Any]], package_id: str
) -> None:
    """Row 4, in `preflight_set` (lane A3): the package's folder would be the run's `attempts/`
    folder (section 4), and on Windows and macOS a name differing only in case is the same folder,
    so the id is refused ignoring case (owner decision 48A): exit 1, one line starting as every
    set refusal does and naming the id, no review and nothing written. An id that only begins with
    it runs."""
    set_path = set_of(tmp_path, tmp_package_dir, package_id)
    out = tmp_path / "runs" / "refused"

    result = benchmark_run(set_path, out)

    assert result.exit_code == 1
    line = one_line(result)
    assert line.startswith(f"error: SetError: benchmark set {set_path.name}: "), line
    assert f"package id {package_id} " in line, line
    assert reviews == []
    assert not out.exists()

    near_set = set_of(tmp_path, tmp_package_dir, "attempts-2")
    near = benchmark_run(near_set, tmp_path / "runs" / "near")

    assert near.exit_code == 0, near.stdout + near.stderr
    assert len(reviews) == 1


# --- 3. what declares a study for P-3 (PP-6) ----------------------------------------


@pytest.mark.parametrize("switch", ["--pane-defaults", "--payload-slimming", "--history-pruning"])
def test_pane_defaults_and_model_view_switches_declare_a_study_for_p3(
    tmp_path: Path, tmp_package_dir: Path, reviews: list[dict[str, Any]], switch: str
) -> None:
    """A pane smoke run over a set with nothing held out needs the recorded override, as a
    `--lever` run does."""
    set_path = one_package_set(tmp_path, tmp_package_dir, held_out=False)
    refused_out = tmp_path / "runs" / "refused"

    refused = benchmark_run(set_path, refused_out, switch)

    assert refused.exit_code == 2
    assert "held_out" in refused.stdout + refused.stderr
    assert reviews == []
    assert not refused_out.exists()

    smoke_out = tmp_path / "runs" / "smoke"
    smoke = benchmark_run(set_path, smoke_out, switch, "--i-know-the-set-is-too-small")

    assert smoke.exit_code == 0, smoke.stdout + smoke.stderr
    assert len(reviews) == 1
    assert read_record(smoke_out)["set_too_small_override"] is True


def test_a_profile_alone_declares_no_study(
    tmp_path: Path, tmp_package_dir: Path, reviews: list[dict[str, Any]]
) -> None:
    """Grading the standards checks changes what is graded, not which arm a run is."""
    set_path = one_package_set(tmp_path, tmp_package_dir, held_out=False)
    out = tmp_path / "runs" / "profile-only"

    result = benchmark_run(
        set_path, out, "--standards-profile", str(example_profile_copy(tmp_path / "profiles"))
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert len(reviews) == 1
    assert read_record(out)["set_too_small_override"] is False


# --- 4. provenance first (section 3's last paragraph) ---------------------------------


def test_provenance_and_saved_set_exist_before_the_first_review(
    tmp_path: Path, tmp_package_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A run that stops part way is still attributable: both files are on disk when the first
    package's review starts."""
    on_disk: list[tuple[bool, bool]] = []

    def review_reading_the_run_folder(
        package_dir: Path, session_out_dir: Path, **_keywords: Any
    ) -> None:
        run_dir = session_out_dir.parent
        on_disk.append(
            ((run_dir / PROVENANCE_FILE).is_file(), (run_dir / SAVED_SET_FILE).is_file())
        )

    monkeypatch.setattr(cli, "_review_fn", review_reading_the_run_folder)
    set_path = two_package_set(tmp_path, tmp_package_dir)

    result = benchmark_run(set_path, tmp_path / "runs" / "first")

    assert result.exit_code == 0, result.stdout + result.stderr
    assert on_disk[0] == (True, True), "a review started before the run's records were written"


# --- 5. the attempt request (RF-44) ----------------------------------------------------


def test_run_benchmark_hands_the_review_function_the_model_view_and_the_profile(
    tmp_path: Path, tmp_package_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`attempt` beside today's four keywords, `explain_findings` still forwarded only when
    true; and `cli._review_fn` passes the attempt's model view and profile to the review, with
    the live tools off. Grown by the scripted-answers slice (T095, RF-44): `attempt.case_file` is
    the `CaseFile` `preflight_set` loaded for an entry naming one and `None` for an entry naming
    none, and `attempt.max_answer_turns` the bound `run_benchmark` was given, 3 by default."""
    payload = case(item_answer())
    no_case_file = {"package_id": "cover", "path": str(tmp_package_dir), "held_out": True}
    preflighted = preflight_set(
        case_file_set(tmp_path, payload, no_case_file), None, load_checklist()
    )
    loaded = CaseFile.model_validate(payload)
    profile = example_profile_copy(tmp_path / "profiles")
    efficiency = EfficiencySettings(tool_tiers=True)
    calls: list[dict[str, Any]] = []

    def review_fn(package_dir: Path, session_out_dir: Path, **keywords: Any) -> None:
        calls.append(keywords)

    run_benchmark(
        preflighted,
        tmp_path / "with-attempt",
        provider="fake",
        model="fake-1",
        effort="high",
        review_fn=review_fn,
        efficiency=efficiency,
        model_view=MODEL_VIEW_PANE,
        standards_profile=profile,
        max_answer_turns=1,
    )
    run_benchmark(
        preflighted,
        tmp_path / "defaults",
        provider="fake",
        model="fake-1",
        effort="high",
        review_fn=review_fn,
        explain_findings=True,
    )

    typed: dict[str, Any] = {
        "provider": "fake",
        "model": "fake-1",
        "effort": "high",
        "efficiency": efficiency,
    }
    untyped: dict[str, Any] = {
        "provider": "fake",
        "model": "fake-1",
        "effort": "high",
        "efficiency": None,
        "explain_findings": True,
    }
    typed_attempt: dict[str, Any] = {
        "model_view": MODEL_VIEW_PANE,
        "standards_profile": profile,
        "max_answer_turns": 1,
    }
    untyped_attempt: dict[str, Any] = {
        "model_view": MODEL_VIEW_OFF,
        "standards_profile": None,
        "max_answer_turns": 3,
    }
    assert calls == [
        {**typed, "attempt": AttemptRequest(**typed_attempt, case_file=loaded)},
        {**typed, "attempt": AttemptRequest(**typed_attempt, case_file=None)},
        {**untyped, "attempt": AttemptRequest(**untyped_attempt, case_file=loaded)},
        {**untyped, "attempt": AttemptRequest(**untyped_attempt, case_file=None)},
    ]
    assert calls[0]["attempt"].case_file is preflighted.case_files[PACKAGE_ID]

    received: list[dict[str, Any]] = []

    def recording_run_review(package_dir: Path, out_dir: Path, **options: Any) -> None:
        received.append(options)

    monkeypatch.setattr(cli, "run_review", recording_run_review)

    cli._review_fn(
        tmp_package_dir,
        tmp_path / "cli-review",
        provider="fake",
        model="fake-1",
        effort="high",
        efficiency=efficiency,
        attempt=AttemptRequest(
            model_view=MODEL_VIEW_PANE,
            standards_profile=profile,
            case_file=None,
            max_answer_turns=0,
        ),
    )

    [options] = received
    assert options["model_view"] == MODEL_VIEW_PANE
    assert options["standards_profile"] == profile
    assert options["bridge"] is False
    assert options["efficiency"] == efficiency


# --- 6. a case file under row 6's carriage-return rule (`provenance.md` 3.2) ------------------


@pytest.mark.parametrize("arm", ["on", "off"])
def test_a_pane_study_refuses_a_case_file_holding_a_carriage_return(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, arm: str
) -> None:
    """Row 6's case-file half (INT-3): a case file the set names inside the repository is a
    digested input, its bytes reaching `set_digest` through the saved set, so in either arm of a
    pane study one holding a carriage return is refused naming it repository-relative, before any
    review and with nothing written."""
    # `test_benchmark_run_pane_study.py` imports this module, so its fictional checkout is
    # imported here, once both are loaded.
    from tests.unit.test_benchmark_run_pane_study import (
        ARMS,
        CASE_FILE,
        EOL_ADVICE,
        EXAMPLE,
        checkout,
        point_at,
        refused,
        watch_reviews,
    )

    root = tmp_path / "checkout"
    set_file = checkout(root, case_file=True, carriage_return_in=CASE_FILE)
    point_at(root, monkeypatch)
    reviewed = watch_reviews(monkeypatch)
    out = tmp_path / "runs" / arm

    result = benchmark_run(
        set_file,
        out,
        "--study",
        PANE_STUDY,
        *ARMS[arm],
        "--standards-profile",
        str(root / EXAMPLE),
    )

    line = refused(result, out, reviewed)
    assert line.endswith(f": check {CASE_FILE} {EOL_ADVICE}"), line
