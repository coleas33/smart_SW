"""Resume the recorded run, preserving every earlier attempt (T203, for T204).

All run folders begin with the real CLI and the scripted provider. Clocks and retry
sleep are injected; no provider request leaves the process (94A: OpenAI settings
and the scripted adapter cover the provider-specific model-alias case).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from swreview import cli
from swreview.agent import checklist as agent_checklist
from swreview.agent.providers.fake import ScriptedToolCall, ScriptedTurn
from swreview.agent.settings import PANE_STUDY
from swreview.benchmark import runner, sets
from swreview.benchmark.digest import sha256_of
from swreview.checks.standards.profile import display_digest
from swreview.report.session import load_session
from tests.unit.test_benchmark_attempts import (
    TransientError,
    driver_events,
    driver_row,
    driver_status,
    install_driver_providers,
    prepare_driver_set,
)
from tests.unit.test_benchmark_attempts import (
    driver_sleeps as driver_sleeps,
)
from tests.unit.test_benchmark_run_pane_study import (
    CASE_FILE,
    EXAMPLE,
    IGNORED,
    checkout,
    point_at,
)
from tests.unit.test_run_provenance import example_profile_copy

pytestmark = pytest.mark.usefixtures("driver_sleeps")

IDS = ("fict-a", "fict-b", "fict-c")
NOW = datetime(2026, 10, 15, 12, tzinfo=UTC)


def scripts_with_a_failed_last_package() -> list[list[ScriptedTurn]]:
    return [
        [ScriptedTurn(text="First review completed.")],
        [ScriptedTurn(text="", stop_reason="SAFETY", end_reason="error")],
        [ScriptedTurn(text="", fails=TransientError("fict exhausted request"))],
    ]


def start_run(
    folder: Path,
    monkeypatch: pytest.MonkeyPatch,
    scripts: Sequence[Sequence[ScriptedTurn]],
    ids: Sequence[str] = IDS,
    *options: str,
    provider: str = "fake",
    model: str | None = None,
    set_file: Path | None = None,
    out: Path | None = None,
) -> tuple[Path, Any]:
    """Write an authentic run folder, including its provenance and saved set.

    Shared with T203's promotion tests through a local import, avoiding a module
    import cycle with the attempt helpers this file reuses.
    """
    if set_file is None:
        prepare_driver_set(folder, ids)
        set_file = folder / "set.json"
    install_driver_providers(monkeypatch, scripts)
    out = folder / "run" if out is None else out
    result = CliRunner().invoke(
        cli.app,
        [
            "benchmark", "run", "--set", str(set_file), "--out", str(out),
            "--provider", provider,
            *(["--model", model] if model is not None else []),
            *options,
        ],
    )
    return out, result


def resume_command(out: Path, *options: str) -> Any:
    return CliRunner().invoke(cli.app, ["benchmark", "resume", str(out), *options])


def snapshot(folder: Path) -> dict[str, bytes | None]:
    """Every directory and file, so a refusal cannot hide a newly created folder."""
    return {
        path.relative_to(folder).as_posix(): path.read_bytes() if path.is_file() else None
        for path in sorted(folder.rglob("*"))
    }


def rewrite_record(out: Path, **fields: Any) -> None:
    path = out / runner.PROVENANCE_FILE
    record = json.loads(path.read_bytes())
    record.update(fields)
    path.write_bytes((json.dumps(record, indent=2) + "\n").encode())


def write_status(out: Path, status: dict[str, Any]) -> None:
    (out / runner.RUN_STATUS_FILE).write_bytes((json.dumps(status, indent=2) + "\n").encode())


def forbid_review(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    reviewed: list[Path] = []

    def body(package_dir: Path, folder: Path, **options: Any) -> None:
        reviewed.append(package_dir)
        pytest.fail("a refused or already kept package was reviewed")

    monkeypatch.setattr(cli, "_review_fn", body)
    return reviewed


def refused(out: Path, monkeypatch: pytest.MonkeyPatch, *options: str) -> str:
    before = snapshot(out)
    reviewed = forbid_review(monkeypatch)
    result = resume_command(out, *options)
    assert result.exit_code == 1, result.stdout + result.stderr
    assert reviewed == []
    assert snapshot(out) == before
    assert result.stdout == ""
    lines = result.stderr.strip().splitlines()
    assert len(lines) == 1, result.stderr
    return lines[0]


@pytest.fixture
def recorded_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    out, result = start_run(tmp_path, monkeypatch, scripts_with_a_failed_last_package())
    assert result.exit_code == 1, result.stdout + result.stderr
    assert driver_row(out, "fict-a")["kind"] == "completed"
    assert driver_row(out, "fict-b")["kind"] == "behavioural"
    assert driver_row(out, "fict-c")["class"] == "provider_error"
    return out


def test_resume_re_runs_only_infrastructure_failures_from_the_start_keeping_their_attempts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    out, first = start_run(tmp_path, monkeypatch, scripts_with_a_failed_last_package())
    assert first.exit_code == 1, first.stdout + first.stderr
    prior = driver_status(out)["packages"]["fict-c"]["attempts"][0]
    failed = out / prior["folder"]
    prior_files = snapshot(failed)
    prior_session = load_session(failed / "session.json").session_id
    built = install_driver_providers(monkeypatch, [[ScriptedTurn(text="Fresh review.")]])

    result = resume_command(out)

    assert result.exit_code == 0, result.stdout + result.stderr
    assert f"swreview benchmark resume {out}" in first.stderr
    assert len(built) == 1
    package = driver_status(out)["packages"]["fict-c"]
    assert package["kept_attempt"] == 2
    assert package["attempts"][0] == prior
    assert snapshot(failed) == prior_files
    kept = out / "fict-c"
    assert driver_row(out, "fict-c")["resumed"] is True
    assert driver_row(out, "fict-c")["attempt"] == 2
    assert driver_row(out, "fict-c")["folder"] == "fict-c"
    assert not (out / "attempts/fict-c/2").exists()
    assert load_session(kept / "session.json").session_id != prior_session
    written = driver_events(kept)
    assert written[0].seq == 1
    assert written[0].type == "session.started"
    assert [event.body["session_id"] for event in written if event.type == "session.started"] == [
        str(load_session(kept / "session.json").session_id),
    ]


@pytest.mark.parametrize("json_output", [False, True])
def test_resume_prints_one_line_per_package_it_attempts_and_json_carries_each_outcome(
    recorded_run: Path, monkeypatch: pytest.MonkeyPatch, json_output: bool,
) -> None:
    install_driver_providers(monkeypatch, [[ScriptedTurn(text="Fresh last review.")]])
    result = resume_command(recorded_run, *(["--json"] if json_output else []))
    assert result.exit_code == 0, result.stdout + result.stderr
    assert result.stderr == ""
    if json_output:
        rows = json.loads(result.stdout)["packages"]
        assert len(rows) == 1
        assert {name: rows[0][name] for name in (
            "package_id", "kind", "class", "stop_reason", "attempts",
        )} == {
            "package_id": "fict-c", "kind": "completed", "class": None,
            "stop_reason": None, "attempts": 2,
        }
        assert rows[0]["out_dir"] == str(recorded_run / "fict-c")
    else:
        assert result.stdout.splitlines() == ["fict-c: completed"]


def test_resume_never_appends_to_a_completed_or_stopped_package(
    recorded_run: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    before = driver_status(recorded_run)["packages"]
    kept_files = {package_id: snapshot(recorded_run / package_id) for package_id in IDS[:2]}
    install_driver_providers(monkeypatch, [[ScriptedTurn(text="Fresh last review.")]])
    result = resume_command(recorded_run)
    assert result.exit_code == 0, result.stdout + result.stderr
    for package_id in IDS[:2]:
        assert snapshot(recorded_run / package_id) == kept_files[package_id]
        assert driver_status(recorded_run)["packages"][package_id] == before[package_id]

    # Provider resolution still occurs when everything is kept; no request is made.
    entire_run = snapshot(recorded_run)
    reviewed = forbid_review(monkeypatch)
    install_driver_providers(monkeypatch, [[ScriptedTurn(text="Never requested.")]])
    again = resume_command(recorded_run)
    assert again.exit_code == 0, again.stdout + again.stderr
    assert again.stdout == again.stderr == ""
    assert reviewed == []
    assert snapshot(recorded_run) == entire_run


@pytest.mark.parametrize("has_kept_attempt", [True, False])
def test_resume_refuses_a_differing_responding_model_and_stops(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, has_kept_attempt: bool,
) -> None:
    """94A: OpenAI aliases with a scripted adapter; Gemini's case is deferred."""
    old, new = "fict-model-a-2026-10-01", "fict-model-a-2026-11-01"
    monkeypatch.setenv("OPENAI_API_KEY", "fict-offline-key")
    failure = [ScriptedTurn(text="", fails=TransientError("fict unavailable"))]
    scripts = [
        [ScriptedTurn(text="Kept.", served_model=old)] if has_kept_attempt else failure,
        failure, failure,
    ]
    out, first = start_run(
        tmp_path, monkeypatch, scripts, provider="openai", model="fict-model-a",
    )
    assert first.exit_code == 1, first.stdout + first.stderr
    previous = driver_status(out)["packages"]
    first_files = snapshot(out / "fict-a") if has_kept_attempt else None
    final_files = snapshot(out / "attempts/fict-c/1")
    fresh = ScriptedTurn(
        text="After the boundary.", served_model=new,
        tool_calls=(ScriptedToolCall("list_components"),),
    )
    built = install_driver_providers(monkeypatch, [[fresh], [fresh], [fresh]])

    result = resume_command(out)

    if not has_kept_attempt:
        assert result.exit_code == 0, result.stdout + result.stderr
        assert len(built) == 3
        assert all(driver_row(out, package_id)["kind"] == "completed" for package_id in IDS)
        return
    assert result.exit_code == 1, result.stdout + result.stderr
    assert old in result.stdout + result.stderr and new in result.stdout + result.stderr
    assert len(built) == 1
    row = driver_row(out, "fict-b")
    assert (row["kind"], row["class"], row["attempt"], row["resumed"]) == (
        "infrastructure", "served_model_changed", 2, True,
    )
    assert old in row["message"] and new in row["message"]
    written = driver_events(out / row["folder"])
    assert len([event for event in written if event.type == "usage"]) == 1
    assert [event.body["tool"] for event in written if event.type == "tool.started"] == [
        "list_components",
    ]
    assert not [event for event in written if event.type == "tool.finished"]
    assert load_session(out / row["folder"] / "session.json").steps == []
    assert any(
        event.type == "turn.ended" and event.body["reason"] == "stopped" for event in written
    )
    assert "text.delta" not in [event.type for event in written]
    assert snapshot(out / "fict-a") == first_files
    assert snapshot(out / "attempts/fict-c/1") == final_files
    assert driver_status(out)["packages"]["fict-c"] == previous["fict-c"]


@pytest.mark.parametrize("legacy", ["missing-provenance", "schema-1", "missing-status"])
def test_resume_refuses_runs_made_before_status_was_recorded(
    recorded_run: Path, monkeypatch: pytest.MonkeyPatch, legacy: str,
) -> None:
    if legacy == "missing-provenance":
        (recorded_run / runner.PROVENANCE_FILE).unlink()
    elif legacy == "schema-1":
        rewrite_record(recorded_run, provenance_schema=1)
    else:
        (recorded_run / runner.RUN_STATUS_FILE).unlink()
    line = refused(recorded_run, monkeypatch)
    assert "made before runs recorded their status; start a new run" in line


def unfinished_attempt(out: Path, started: datetime) -> dict[str, Any]:
    status = driver_status(out)
    row = status["packages"]["fict-c"]["attempts"][-1]
    row.update({
        "kind": None, "class": None, "ended_at": None, "error_class": None,
        "message": None, "started_at": started.isoformat().replace("+00:00", "Z"),
    })
    write_status(out, status)
    return row


def test_resume_refuses_an_attempt_that_may_still_be_running(
    recorded_run: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    rewrite_record(recorded_run, package_time_limit_s=60, stop_grace_s=15)
    unfinished_attempt(recorded_run, NOW - timedelta(seconds=20))
    before = snapshot(recorded_run)
    reviewed = forbid_review(monkeypatch)
    with pytest.raises(ValueError) as raised:
        runner.resume_benchmark(
            recorded_run, review_fn=cli._review_fn, now=lambda: NOW,
        )
    message = str(raised.value)
    assert "may still be running; wait until " in message
    assert "12:00:55" in message
    assert "fict-c" in message
    assert reviewed == [] and snapshot(recorded_run) == before

    resume = runner.resume_benchmark

    def fixed_now(*args: Any, **options: Any) -> Any:
        return resume(*args, **options, now=lambda: NOW)

    monkeypatch.setattr(cli, "resume_benchmark", fixed_now, raising=False)
    line = refused(recorded_run, monkeypatch)
    assert "may still be running; wait until " in line and "12:00:55" in line


@pytest.mark.parametrize("field", ["commit", "checklist_digest", "prompt_digest"])
def test_resume_refuses_changed_code_inputs_naming_the_field_and_both_values(
    recorded_run: Path, monkeypatch: pytest.MonkeyPatch, field: str,
) -> None:
    actual = json.loads((recorded_run / runner.PROVENANCE_FILE).read_bytes())[field]
    recorded = "fict-other-commit" if field == "commit" else "f" * 64
    rewrite_record(recorded_run, **{field: recorded})
    line = refused(recorded_run, monkeypatch)
    assert field in line and actual in line and recorded in line


@pytest.mark.parametrize("unknown", ["recorded", "current"])
def test_resume_refuses_an_unknown_commit(
    recorded_run: Path, monkeypatch: pytest.MonkeyPatch, unknown: str,
) -> None:
    if unknown == "recorded":
        rewrite_record(recorded_run, commit=None)
    else:
        monkeypatch.setattr(runner, "current_commit", lambda root: None)
    line = refused(recorded_run, monkeypatch)
    assert "commit" in line
    assert "unknown" in line.lower() or "None" in line or "null" in line


def test_resume_refuses_a_changed_saved_set(
    recorded_run: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    saved = recorded_run / runner.SAVED_SET_FILE
    saved.write_bytes(saved.read_bytes() + b"\n")
    line = refused(recorded_run, monkeypatch)
    assert runner.SAVED_SET_FILE in line and "digest" in line


def test_resume_refuses_a_changed_case_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "checkout"
    set_file = checkout(root, case_file=True)
    point_at(root, monkeypatch)
    out, first = start_run(
        tmp_path, monkeypatch,
        [[ScriptedTurn(text="", fails=TransientError("fict unavailable"))]],
        set_file=set_file,
    )
    assert first.exit_code == 1, first.stdout + first.stderr
    case_file = root / CASE_FILE
    case_file.write_bytes(case_file.read_bytes() + b"\n")
    line = refused(out, monkeypatch)
    assert CASE_FILE in line
    assert "digest" in line or "sha256" in line


@pytest.mark.parametrize("difference", ["unexpected", "missing", "changed"])
def test_resume_refuses_a_different_profile_naming_the_recorded_display_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, difference: str,
) -> None:
    profile = example_profile_copy(tmp_path / "profiles")
    initial_options = () if difference == "unexpected" else ("--standards-profile", str(profile))
    out, first = start_run(
        tmp_path, monkeypatch,
        [[ScriptedTurn(text="", fails=TransientError("fict unavailable"))]],
        ("fict-a",), *initial_options,
    )
    assert first.exit_code == 1, first.stdout + first.stderr
    recorded_digest = sha256_of(profile)
    if difference == "changed":
        profile.write_bytes(profile.read_bytes() + b"\n# fict changed profile\n")
    options = () if difference == "missing" else ("--standards-profile", str(profile))
    line = refused(out, monkeypatch, *options)
    assert "profile" in line
    if difference != "unexpected":
        assert display_digest(recorded_digest) in line
    assert str(profile) not in line


@pytest.mark.parametrize("failure_at", ["settings", "factory", "effort"])
def test_resume_refuses_a_provider_that_does_not_resolve(
    recorded_run: Path, monkeypatch: pytest.MonkeyPatch, failure_at: str,
) -> None:
    factory_calls: list[bool] = []
    mapping_calls: list[str] = []

    class RefusedAdapter:
        def effort_mapping(self, effort: str) -> None:
            mapping_calls.append(effort)
            raise ValueError("fict recorded effort unavailable")

    def factory(*args: Any, **options: Any) -> RefusedAdapter:
        factory_calls.append(True)
        if failure_at == "factory":
            raise ValueError("fict recorded provider unavailable")
        return RefusedAdapter()

    if failure_at == "settings":
        rewrite_record(recorded_run, provider="fict-no-provider")
    monkeypatch.setattr(cli, "provider_factory", factory)
    line = refused(recorded_run, monkeypatch)
    if failure_at == "settings":
        assert "fict-no-provider" in line
        assert factory_calls == mapping_calls == []
        return
    name = "provider" if failure_at == "factory" else "effort"
    assert f"fict recorded {name} unavailable" in line
    assert factory_calls == [True]
    assert mapping_calls == ([] if failure_at == "factory" else ["high"])


def test_library_resume_refuses_an_unresolvable_provider_before_writing(
    recorded_run: Path,
) -> None:
    """The public resume function enforces section 11 without a CLI callback."""
    rewrite_record(recorded_run, provider="fict-no-provider")
    before = snapshot(recorded_run)
    with pytest.raises(ValueError, match="fict-no-provider"):
        runner.resume_benchmark(recorded_run, review_fn=cli._review_fn, clock=lambda: 0.0)
    assert snapshot(recorded_run) == before


def test_resume_runs_packages_the_run_never_reached(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = example_profile_copy(tmp_path / "profiles")
    original_bytes = profile.read_bytes()
    real_body = cli._review_fn

    def change_profile_after_the_first_review(*args: Any, **options: Any) -> Any:
        result = real_body(*args, **options)
        profile.write_bytes(original_bytes + b"\n# fict between-package interruption\n")
        return result

    monkeypatch.setattr(cli, "_review_fn", change_profile_after_the_first_review)
    out, first = start_run(
        tmp_path, monkeypatch, [[ScriptedTurn(text="First completed.")]], IDS,
        "--standards-profile", str(profile),
    )
    assert first.exit_code == 1, first.stdout + first.stderr
    assert "standards profile changed" in first.stderr
    assert list(driver_status(out)["packages"]) == ["fict-a"]
    first_files = snapshot(out / "fict-a")
    profile.write_bytes(original_bytes)
    monkeypatch.setattr(cli, "_review_fn", real_body)
    built = install_driver_providers(monkeypatch, [
        [ScriptedTurn(text="Previously unreached second.")],
        [ScriptedTurn(text="Previously unreached third.")],
    ])

    result = resume_command(out, "--standards-profile", str(profile))

    assert result.exit_code == 0, result.stdout + result.stderr
    assert len(built) == 2
    assert result.stdout.splitlines() == ["fict-b: completed", "fict-c: completed"]
    assert snapshot(out / "fict-a") == first_files
    for package_id in IDS[1:]:
        row = driver_row(out, package_id)
        assert (row["attempt"], row["resumed"], row["kind"]) == (1, True, "completed")


def test_resume_records_an_old_unfinished_attempt_interrupted_then_re_runs_it(
    recorded_run: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    rewrite_record(recorded_run, package_time_limit_s=60, stop_grace_s=15)
    prior = unfinished_attempt(recorded_run, NOW - timedelta(seconds=76))
    prior_files = snapshot(recorded_run / prior["folder"])
    install_driver_providers(monkeypatch, [[ScriptedTurn(text="Restarted after interruption.")]])

    runner.resume_benchmark(
        recorded_run, review_fn=cli._review_fn, now=lambda: NOW, clock=lambda: 0.0,
    )

    rows = driver_status(recorded_run)["packages"]["fict-c"]["attempts"]
    assert len(rows) == 2
    assert (rows[0]["kind"], rows[0]["class"]) == ("infrastructure", "interrupted")
    assert rows[0]["started_at"] == prior["started_at"]
    assert datetime.fromisoformat(rows[0]["ended_at"].replace("Z", "+00:00")) == NOW
    assert snapshot(recorded_run / prior["folder"]) == prior_files
    assert (rows[1]["attempt"], rows[1]["resumed"], rows[1]["kind"]) == (2, True, "completed")


@pytest.mark.parametrize("study", [PANE_STUDY, "trim_tool_descriptions"])
@pytest.mark.parametrize("changed", ["dirty", "carriage-return"])
def test_resume_of_a_pane_study_refuses_a_dirty_tree_and_a_carriage_return(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, study: str, changed: str,
) -> None:
    root = tmp_path / "checkout"
    set_file = checkout(root)
    point_at(root, monkeypatch)
    profile = root / EXAMPLE
    out, first = start_run(
        tmp_path, monkeypatch,
        [[ScriptedTurn(text="", fails=TransientError("fict unavailable"))]],
        ("pkg-1",), "--study", study, "--arm", "off", "--no-explain-findings",
        "--standards-profile", str(profile), set_file=set_file, out=root / IGNORED / "run",
    )
    assert first.exit_code == 1, first.stdout + first.stderr
    if changed == "dirty":
        readme = root / "README.md"
        readme.write_bytes(readme.read_bytes() + b"A fict tracked change.\n")
    else:
        # Match the saved digest to isolate row 6 from row 4. The file is ignored
        # and inside the checkout, so the tracked tree remains clean.
        saved = out / runner.SAVED_SET_FILE
        saved.write_bytes(saved.read_bytes().replace(b"\n", b"\r\n"))
        rewrite_record(out, set_digest=sha256_of(saved))
        assert runner.tree_dirty(root=root) is False
    if study == PANE_STUDY:
        line = refused(out, monkeypatch, "--standards-profile", str(profile))
        if changed == "dirty":
            assert "tracked" in line and "commit" in line
        else:
            assert runner.SAVED_SET_FILE in line
            assert "eol=lf" in line
    else:
        install_driver_providers(monkeypatch, [[ScriptedTurn(text="Lever resume completed.")]])
        result = resume_command(out, "--standards-profile", str(profile))
        assert result.exit_code == 0, result.stdout + result.stderr


@pytest.mark.parametrize("recorded_folder", ["fict-a", "attempts/fict-a/1"])
def test_resume_completes_an_interrupted_promotion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recorded_folder: str,
) -> None:
    out, first = start_run(
        tmp_path, monkeypatch, [[ScriptedTurn(text="Paid and kept.")]], ("fict-a",),
    )
    assert first.exit_code == 0, first.stdout + first.stderr
    kept_files = snapshot(out / "fict-a")
    attempt = out / "attempts/fict-a/1"
    (out / "fict-a").rename(attempt)
    status = driver_status(out)
    status["packages"]["fict-a"]["attempts"][0]["folder"] = recorded_folder
    write_status(out, status)
    reviewed = forbid_review(monkeypatch)
    install_driver_providers(monkeypatch, [[ScriptedTurn(text="Never requested.")]])

    result = resume_command(out)

    assert result.exit_code == 0, result.stdout + result.stderr
    assert reviewed == []
    assert result.stdout == ""
    assert snapshot(out / "fict-a") == kept_files
    assert not attempt.exists()
    package = driver_status(out)["packages"]["fict-a"]
    assert package["kept_attempt"] == 1 and len(package["attempts"]) == 1
    assert package["attempts"][0]["folder"] == "fict-a"


@pytest.mark.parametrize("halt", ["served-model", "profile"])
def test_resume_promotes_every_kept_attempt_before_a_halt_or_any_new_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, halt: str,
) -> None:
    old, new = "fict-model-a-2026-10-01", "fict-model-a-2026-11-01"
    monkeypatch.setenv("OPENAI_API_KEY", "fict-offline-key")
    profile = example_profile_copy(tmp_path / "profiles") if halt == "profile" else None
    options = () if profile is None else ("--standards-profile", str(profile))
    out, first = start_run(
        tmp_path, monkeypatch,
        [
            [ScriptedTurn(text="", fails=TransientError("fict unavailable"))],
            [ScriptedTurn(text="Kept b.", served_model=old)],
            [ScriptedTurn(text="Kept c.", served_model=old)],
        ],
        IDS, *options, provider="openai", model="fict-model-a",
    )
    assert first.exit_code == 1, first.stdout + first.stderr
    status = driver_status(out)
    for package_id in IDS[1:]:
        pending = out / "attempts" / package_id / "1"
        (out / package_id).rename(pending)
        status["packages"][package_id]["attempts"][0]["folder"] = (
            pending.relative_to(out).as_posix()
        )
    write_status(out, status)
    install_driver_providers(monkeypatch, [[ScriptedTurn(
        text="Changed responder.", served_model=new,
        tool_calls=(ScriptedToolCall("list_components"),),
    )]])
    promotion_state_at_review: list[bool] = []
    real_review = cli._review_fn

    def review(*args: Any, **kwargs: Any) -> Any:
        promotion_state_at_review.append(all((out / name).is_dir() for name in IDS[1:]))
        return real_review(*args, **kwargs)

    monkeypatch.setattr(cli, "_review_fn", review)
    if profile is not None:
        real_factory = cli.provider_factory

        def factory(*args: Any, **kwargs: Any) -> Any:
            adapter = real_factory(*args, **kwargs)
            profile.write_bytes(profile.read_bytes() + b"\n# fict moved after preflight\n")
            return adapter

        monkeypatch.setattr(cli, "provider_factory", factory)

    result = resume_command(out, *options)

    assert result.exit_code == 1, result.stdout + result.stderr
    assert all((out / name).is_dir() for name in IDS[1:])
    assert all(not (out / "attempts" / name / "1").exists() for name in IDS[1:])
    assert "promotion incomplete" not in result.stderr
    if halt == "served-model":
        assert promotion_state_at_review == [True]
        assert driver_row(out, "fict-a")["class"] == "served_model_changed"
    else:
        assert promotion_state_at_review == []
        assert "standards profile changed" in result.stderr


def test_recorded_timing_resolves_one_shared_set_of_legacy_defaults(
    recorded_run: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from inspect import signature

    from swreview.benchmark import attempt

    assert signature(runner.run_benchmark).parameters["package_time_limit_s"].default == (
        attempt.PACKAGE_TIME_LIMIT_S
    )
    provenance = runner.load_provenance(recorded_run)
    assert provenance is not None
    monkeypatch.setattr(attempt, "PACKAGE_TIME_LIMIT_S", 71)
    monkeypatch.setattr(attempt, "STREAM_ACTIVITY_WINDOW_S", 7)
    monkeypatch.setattr(attempt, "STOP_GRACE_S", 9)
    legacy = provenance.model_copy(update={
        "package_time_limit_s": None, "stream_activity_window_s": None, "stop_grace_s": None,
    })
    assert runner._recorded_timing(legacy) == (71, 7, 9)
    recorded = provenance.model_copy(update={
        "package_time_limit_s": 81, "stream_activity_window_s": 11, "stop_grace_s": 13,
    })
    assert runner._recorded_timing(recorded) == (81, 11, 13)


def test_resume_uses_the_same_legacy_timing_for_its_running_guard_and_scheduler(
    recorded_run: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from swreview.benchmark import attempt

    rewrite_record(
        recorded_run, package_time_limit_s=None, stream_activity_window_s=None, stop_grace_s=None,
    )
    unfinished_attempt(recorded_run, NOW - timedelta(seconds=36))
    monkeypatch.setattr(attempt, "PACKAGE_TIME_LIMIT_S", 30, raising=False)
    monkeypatch.setattr(attempt, "STREAM_ACTIVITY_WINDOW_S", 7)
    monkeypatch.setattr(attempt, "STOP_GRACE_S", 5)
    observed: list[tuple[float, float, float]] = []

    def schedule(*args: Any, **kwargs: Any) -> list[Path]:
        observed.append((
            kwargs["package_time_limit_s"], kwargs["stream_activity_window_s"],
            kwargs["stop_grace_s"],
        ))
        return []

    monkeypatch.setattr(runner, "_run_packages", schedule)
    runner.resume_benchmark(recorded_run, now=lambda: NOW, on_preflight=lambda provenance: None)
    assert observed == [(30, 7, 5)]


@pytest.mark.parametrize("first_refusal", ["legacy", "commit", "set", "profile"])
def test_resume_refusals_follow_the_contract_order_without_writing(
    recorded_run: Path, monkeypatch: pytest.MonkeyPatch, first_refusal: str,
) -> None:
    def provider_must_be_last(*args: Any, **options: Any) -> None:
        pytest.fail("provider resolved before an earlier resume refusal")

    monkeypatch.setattr(cli, "provider_factory", provider_must_be_last)
    rewrite_record(recorded_run, profile_digest="e" * 64)
    if first_refusal in {"legacy", "commit", "set"}:
        rewrite_record(recorded_run, set_digest="d" * 64)
    if first_refusal in {"legacy", "commit"}:
        rewrite_record(recorded_run, commit="fict-other-commit")
    if first_refusal == "legacy":
        (recorded_run / runner.PROVENANCE_FILE).unlink()
    line = refused(recorded_run, monkeypatch)
    expected = {
        "legacy": "made before runs recorded their status",
        "commit": "commit", "set": runner.SAVED_SET_FILE, "profile": "profile",
    }
    assert expected[first_refusal] in line


def test_resume_checks_running_attempts_before_code_inputs(
    recorded_run: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    rewrite_record(
        recorded_run, commit="fict-other-commit", package_time_limit_s=60, stop_grace_s=15,
    )
    unfinished_attempt(recorded_run, NOW - timedelta(seconds=20))
    before = snapshot(recorded_run)
    with pytest.raises(ValueError, match="may still be running"):
        runner.resume_benchmark(recorded_run, review_fn=cli._review_fn, now=lambda: NOW)
    assert snapshot(recorded_run) == before


@pytest.mark.parametrize("option", ["--provider", "--model", "--effort", "--max-answer-turns"])
def test_resume_accepts_no_option_that_changes_the_recorded_review(
    recorded_run: Path, option: str,
) -> None:
    before = snapshot(recorded_run)
    result = resume_command(recorded_run, option, "1")
    assert result.exit_code == 2
    assert option in result.stderr
    assert snapshot(recorded_run) == before


def test_resume_reads_the_recorded_attempt_settings(
    recorded_run: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = json.loads((recorded_run / runner.PROVENANCE_FILE).read_bytes())
    record["max_answer_turns"] = 0
    record["max_steps"] = 2
    record["retry_policy"] = {"retries": 0, "initial_delay_s": 0.0, "max_delay_s": 0.0}
    rewrite_record(recorded_run, **record)
    seen: list[dict[str, Any]] = []
    real_start = cli.start_review

    def start(*args: Any, **options: Any) -> Any:
        seen.append(options)
        return real_start(*args, **options)

    monkeypatch.setattr(cli, "start_review", start)
    built = install_driver_providers(monkeypatch, [[ScriptedTurn(
        text="Not reached after the recorded budget.",
        tool_calls=(ScriptedToolCall("list_components"),) * 3,
    )]])
    result = resume_command(recorded_run)
    assert result.exit_code == 0, result.stdout + result.stderr
    assert len(seen) == len(built) == 1
    assert seen[0]["max_steps"] == 2
    assert seen[0]["efficiency"].model_dump(mode="json") == record["efficiency"]
    assert seen[0]["model_view"].model_dump(mode="json") == record["model_view"]
    assert built[0]._retry_policy.retries == 0
    assert (driver_row(recorded_run, "fict-c")["kind"],
            driver_row(recorded_run, "fict-c")["class"]) == ("behavioural", "max_steps")
    assert load_session(recorded_run / "fict-c/session.json").model == record["model"]
    assert sha256_of(agent_checklist.CHECKLIST_FILE) == record["checklist_digest"]
    assert sets.load_saved_set(recorded_run / runner.SAVED_SET_FILE).name == "fict-driver"
