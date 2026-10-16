"""Pack authentic scripted runs without changing their streams or scores (T214).

Owner decision 28A; provenance 6.6, 6.7 and 8; RF-82, RF-83 and RF-84.
All adapters are scripted and all retry sleeps are injected. OpenAI settings and
the scripted provider cover the provider cases; Gemini is omitted under 94A.
"""

from __future__ import annotations

import gzip
import importlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from typer.testing import CliRunner

from swreview import cli
from swreview.agent import events
from swreview.agent.providers import ProviderName
from swreview.agent.providers.fake import (
    SYNTHETIC_USAGE,
    FakeProvider,
    ScriptedRound,
    ScriptedToolCall,
    ScriptedTurn,
)
from swreview.benchmark import prices, runner
from swreview.benchmark import scorecard as scorecard_module
from swreview.benchmark.digest import sha256_of_bytes
from tests.support.answer_keys import write_key
from tests.support.roles_review import write_package, write_profile
from tests.unit.test_benchmark_attempts import (
    TransientError,
    driver_status,
    install_driver_providers,
)
from tests.unit.test_benchmark_attempts import driver_sleeps as driver_sleeps
from tests.unit.test_benchmark_resume import (
    resume_command,
    snapshot,
    start_run,
    write_status,
)

pytestmark = pytest.mark.usefixtures("driver_sleeps")

MANIFEST = "event-streams.json"
MODEL = "gpt-5.6-sol"


def packing_module() -> ModuleType:
    # Import inside each test so the pre-implementation red run still exercises
    # the CLI's absent command and all authentic run fixtures.
    return importlib.import_module("swreview.benchmark.streams")


def pack_command(*folders: Path) -> Any:
    return CliRunner().invoke(cli.app, ["benchmark", "pack", *map(str, folders)])


def score_command(folder: Path, keys: Path) -> Any:
    return CliRunner().invoke(
        cli.app, ["benchmark", "score", str(folder), "--answer-keys", str(keys)],
    )


def manifest(folder: Path) -> dict[str, Any]:
    return json.loads((folder / MANIFEST).read_bytes())


def stream_bytes(folder: Path) -> dict[str, bytes]:
    return {
        path.relative_to(folder).as_posix(): path.read_bytes()
        for path in sorted(folder.rglob(events.EVENTS_FILE_NAME))
    }


@pytest.fixture
def packable_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A completed run retaining an eventful failure and a failure before any event."""
    real_review = cli._review_fn

    def before_first_event(package_dir: Path, *args: Any, **options: Any) -> Any:
        if package_dir.name == "fict-c":
            raise RuntimeError("fict attempt failed before its opening event")
        return real_review(package_dir, *args, **options)

    with monkeypatch.context() as initial:
        initial.setattr(cli, "_review_fn", before_first_event)
        out, first = start_run(
            tmp_path, initial,
            [
                [ScriptedTurn(text="First package completed.")],
                [ScriptedTurn(
                    text="", fails=TransientError("fict closing request failed"),
                    rounds=(ScriptedRound(
                        (ScriptedToolCall("list_components"),), SYNTHETIC_USAGE,
                    ),),
                )],
            ],
        )
    assert first.exit_code == 1, first.stdout + first.stderr
    status = driver_status(out)
    assert status["packages"]["fict-b"]["attempts"][0]["class"] == "provider_error"
    no_events = out / status["packages"]["fict-c"]["attempts"][0]["folder"]
    assert status["packages"]["fict-c"]["attempts"][0]["class"] == "internal_error"
    assert not (no_events / events.EVENTS_FILE_NAME).exists()
    install_driver_providers(monkeypatch, [
        [ScriptedTurn(text="Second attempt completed.")],
        [ScriptedTurn(text="The previously unopened review completed.")],
    ])
    resumed = resume_command(out)
    assert resumed.exit_code == 0, resumed.stdout + resumed.stderr
    assert driver_status(out)["packages"]["fict-b"]["kept_attempt"] == 2
    assert driver_status(out)["packages"]["fict-c"]["kept_attempt"] == 2
    return out


def test_pack_replaces_every_stream_with_its_packed_form_and_records_its_digest(
    packable_run: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    streams = packing_module()
    out = packable_run
    plain = stream_bytes(out)
    assert set(plain) == {
        "fict-a/events.jsonl", "fict-b/events.jsonl", "fict-c/events.jsonl",
        "attempts/fict-b/1/events.jsonl",
    }
    unrelated = out / "notes/nested/events.jsonl"
    unrelated.parent.mkdir(parents=True)
    unrelated.write_bytes(b"An unrelated file, not a run stream.\n")
    before = snapshot(out)
    writes: list[Path] = []
    real_write = streams.write_atomic

    def atomic_spy(path: Path, data: bytes) -> None:
        writes.append(path)
        if path == out / MANIFEST:
            assert all((out / relative).is_file() for relative in plain)
        real_write(path, data)

    monkeypatch.setattr(streams, "write_atomic", atomic_spy)

    streams.pack_run(out)

    expected = {
        relative + ".gz": sha256_of_bytes(data) for relative, data in plain.items()
    }
    assert manifest(out) == {"event_streams_version": 1, "streams": expected}
    record = streams.EventStreams.model_validate_json((out / MANIFEST).read_bytes())
    assert record.event_streams_version == 1 and record.streams == expected
    for relative, data in plain.items():
        assert not (out / relative).exists()
        assert gzip.decompress((out / (relative + ".gz")).read_bytes()) == data
    assert set(writes) == {out / relative for relative in expected} | {out / MANIFEST}
    assert len(writes) == len(expected) + 1
    text = (out / MANIFEST).read_bytes()
    assert text.endswith(b"\n") and b"\r" not in text
    assert list(json.loads(text)) == sorted(json.loads(text))
    assert list(json.loads(text)["streams"]) == sorted(expected)
    assert not any(row.startswith("attempts/fict-c/1/") for row in expected)
    after = snapshot(out)
    for relative, data in before.items():
        if relative not in plain:
            assert after[relative] == data
    assert unrelated.read_bytes() == b"An unrelated file, not a run stream.\n"
    assert not unrelated.with_suffix(".jsonl.gz").exists()


@pytest.mark.parametrize("redirected_folder", ["attempts/fict-b/1", "attempts/fict-b"])
def test_pack_refuses_an_earlier_attempt_or_its_parent_resolving_outside_the_run(
    packable_run: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, redirected_folder: str,
) -> None:
    streams = packing_module()
    redirected = packable_run / redirected_folder
    outside = tmp_path / "fict-outside"
    outside.mkdir()
    (outside / events.EVENTS_FILE_NAME).write_bytes(b"Fict outside stream.\n")
    before = snapshot(packable_run)
    outside_before = snapshot(outside)
    real_resolve = Path.resolve

    def resolve(path: Path, *args: Any, **kwargs: Any) -> Path:
        if path == redirected or redirected in path.parents:
            return outside / path.relative_to(redirected)
        return real_resolve(path, *args, **kwargs)

    # The same resolved paths as a directory symlink, without requiring
    # Windows elevation to create that link in the sandbox.
    monkeypatch.setattr(Path, "resolve", resolve)
    with pytest.raises(ValueError, match="outside the run"):
        streams.pack_run(packable_run)
    assert snapshot(packable_run) == before
    assert snapshot(outside) == outside_before


def test_packing_is_reproducible(packable_run: Path, tmp_path: Path) -> None:
    first = packable_run
    second = tmp_path / "same-streams"
    shutil.copytree(first, second)
    plain = stream_bytes(first)

    result = pack_command(first, second)

    assert result.exit_code == 0, result.stdout + result.stderr
    assert (first / MANIFEST).read_bytes() == (second / MANIFEST).read_bytes()
    for relative, data in plain.items():
        packed = (first / (relative + ".gz")).read_bytes()
        assert packed == (second / (relative + ".gz")).read_bytes()
        assert packed == gzip.compress(data, compresslevel=9, mtime=0)
        assert packed[:3] == b"\x1f\x8b\x08"
        assert packed[3] & 8 == 0  # FNAME: no source filename in the header.
        assert packed[4:8] == b"\x00\x00\x00\x00"


def withdrawal_run(
    folder: Path, monkeypatch: pytest.MonkeyPatch, provider: str,
) -> tuple[Path, Path]:
    """A real benchmark answer withdraws code findings after a billed failed attempt."""
    folder.mkdir(parents=True, exist_ok=True)
    package_id = "fict-roles"
    package = write_package(folder / "packages" / package_id)
    profile = write_profile(folder)
    case = folder / "case_files/roles-case.json"
    case.parent.mkdir(parents=True)
    case.write_bytes((json.dumps({
        "case_file_version": 1, "package_id": package_id,
        "answers": [{"id": "A-1", "part_roles": True, "answer": "All bought"}],
    }) + "\n").encode())
    set_file = folder / "set.json"
    set_file.write_bytes((json.dumps({"name": "fict-withdrawn", "packages": [{
        "package_id": package_id, "path": str(package), "case_file": str(case),
        "held_out": False,
    }]}) + "\n").encode())
    if provider == "openai":
        monkeypatch.setenv("OPENAI_API_KEY", "fict-offline-key")
        monkeypatch.setattr(FakeProvider, "name", ProviderName.OPENAI)
    out, first = start_run(
        folder, monkeypatch,
        [[ScriptedTurn(
            text="", fails=TransientError("fict failure after billed usage"), served_model=MODEL,
            rounds=(ScriptedRound((ScriptedToolCall("list_components"),), SYNTHETIC_USAGE),),
        )]],
        (package_id,), "--standards-profile", str(profile), "--no-explain-findings",
        provider=provider, model=MODEL, set_file=set_file,
    )
    assert first.exit_code == 1, first.stdout + first.stderr
    assert (out / runner.PROVENANCE_FILE).is_file(), first.stdout + first.stderr
    install_driver_providers(monkeypatch, [[
        ScriptedTurn(
            text="Reviewed the fictional parts.", served_model=MODEL,
            tool_calls=(ScriptedToolCall("check_rms_part"), ScriptedToolCall("check_hygiene")),
        ),
        ScriptedTurn(text="Reviewed after the part-role answer.", served_model=MODEL),
    ]])
    resumed = resume_command(out, "--standards-profile", str(profile))
    assert resumed.exit_code == 0, resumed.stdout + resumed.stderr
    keys = folder / "answer_keys"
    write_key(
        keys, package_id,
        forbidden=[{"checks": ["rms.*", "hygiene.*"], "component_ids": ["cmp:0002"]}],
    )
    return out, keys


@pytest.mark.parametrize("provider", ["fake", "openai"])
def test_a_packed_run_scores_as_before(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, provider: str,
) -> None:
    """94A: OpenAI pricing over a scripted adapter; no Gemini provider case."""
    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> datetime:
            return datetime(2026, 10, 15, 12, tzinfo=UTC)

    monkeypatch.setattr(scorecard_module, "datetime", FixedDateTime)
    out, keys = withdrawal_run(tmp_path, monkeypatch, provider)
    before_facts = {relative: runner.attempt_facts(out / relative) for relative in (
        "fict-roles", "attempts/fict-roles/1",
    )}
    assert all(facts.paid and facts.rounds for facts in before_facts.values())
    assert all(facts.served_models == [MODEL] for facts in before_facts.values())
    first = score_command(out, keys)
    assert first.exit_code == 0, first.stdout + first.stderr
    before = (out / "scorecard.json").read_bytes()
    card = json.loads(before)
    assert card["per_package"][0]["withdrawn_forbidden_hit_finding_ids"]
    failed, = card["failed_attempts"]
    assert failed["folder"] == "attempts/fict-roles/1"
    assert card["per_package"][0]["served_models"] == [MODEL]
    for relative, facts in before_facts.items():
        expected = prices.price_rounds(facts.rounds, table=prices.load_prices()).model_dump()
        actual = (
            failed["cost"] if relative.startswith("attempts/")
            else card["per_package"][0]["cost"]
        )
        assert actual == expected
        if provider == "openai":
            assert actual["amount"] > 0 and not actual["synthetic"]
        else:
            assert actual["synthetic"]
    assert card["aggregate"]["failed_attempts_cost"] == failed["cost"]

    packed = pack_command(out)
    assert packed.exit_code == 0, packed.stdout + packed.stderr
    after = score_command(out, keys)

    assert after.exit_code == 0, after.stdout + after.stderr
    assert (out / "scorecard.json").read_bytes() == before
    after_facts = {relative: runner.attempt_facts(out / relative) for relative in before_facts}
    assert after_facts == before_facts


@pytest.mark.parametrize("refusal", [
    "not_run", "no_status", "no_outcome", "promotion", "unrecorded", "different", "digest",
])
def test_pack_refusals_write_nothing_in_any_named_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, refusal: str,
) -> None:
    good, first = start_run(
        tmp_path / "fixture", monkeypatch, [[ScriptedTurn(text="Completed.")]], ("fict-a",),
    )
    assert first.exit_code == 0, first.stdout + first.stderr
    bad, last = tmp_path / "bad", tmp_path / "last"
    shutil.copytree(good, bad)
    shutil.copytree(good, last)
    plain = bad / "fict-a" / events.EVENTS_FILE_NAME
    packed = plain.with_suffix(".jsonl.gz")
    expected: str
    if refusal == "not_run":
        (bad / runner.PROVENANCE_FILE).unlink()
        expected = f"{bad} is not a run folder"
    elif refusal == "no_status":
        (bad / runner.RUN_STATUS_FILE).unlink()
        expected = f"{bad} was made before runs recorded their status; it cannot be packed"
    elif refusal == "no_outcome":
        status = driver_status(bad)
        package = status["packages"]["fict-a"]
        package["kept_attempt"] = None
        package["attempts"][0].update(kind=None, ended_at=None)
        write_status(bad, status)
        expected = (
            f"attempt 1 of fict-a has no outcome: run `swreview benchmark resume {bad}` first"
        )
    elif refusal == "promotion":
        (bad / "fict-a").rename(bad / "attempts/fict-a/1")
        expected = f"promotion incomplete: run `swreview benchmark resume {bad}`"
    elif refusal == "unrecorded":
        packed.write_bytes(gzip.compress(plain.read_bytes(), compresslevel=9, mtime=0))
        plain.unlink()
        expected = f"{packed} is packed but unrecorded"
    elif refusal == "different":
        packed.write_bytes(gzip.compress(b"fict different stream\n", compresslevel=9, mtime=0))
        expected = "the packed stream differs from the plain one beside it"
    else:
        (bad / MANIFEST).write_bytes((json.dumps({
            "event_streams_version": 1, "streams": {"fict-a/events.jsonl.gz": "0" * 64},
        }) + "\n").encode())
        expected = "its recorded digest differs from the stream"
    before = {folder: snapshot(folder) for folder in (good, bad, last)}

    result = pack_command(good, bad, last)

    assert result.exit_code == 1, result.stdout + result.stderr
    assert result.stdout == ""
    lines = result.stderr.strip().splitlines()
    assert len(lines) == 1, result.stderr
    assert str(bad) in lines[0] and expected in lines[0]
    assert {folder: snapshot(folder) for folder in before} == before


def test_an_unfinished_pack_is_refused_by_the_readers_and_finished_by_packing_again(
    packable_run: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    streams = packing_module()
    out = packable_run
    victim = out / "fict-a" / events.EVENTS_FILE_NAME
    real_unlink = Path.unlink

    def interrupted_delete(path: Path, *args: Any, **options: Any) -> None:
        if path == victim:
            raise OSError("fict interruption before deleting the plain stream")
        real_unlink(path, *args, **options)

    with monkeypatch.context() as interruption:
        interruption.setattr(Path, "unlink", interrupted_delete)
        with pytest.raises(OSError, match="fict interruption"):
            streams.pack_run(out)
    assert victim.is_file() and victim.with_suffix(".jsonl.gz").is_file()
    prior_rows = (out / MANIFEST).read_bytes()
    prior_packed = {path: path.read_bytes() for path in out.rglob(events.PACKED_EVENTS_FILE_NAME)}
    with pytest.raises(ValueError) as unfinished:
        events.event_stream(victim.parent)
    assert str(victim.parent) in str(unfinished.value)
    assert "swreview benchmark pack" in str(unfinished.value)
    keys = tmp_path / "answer_keys"
    for package_id in ("fict-a", "fict-b", "fict-c"):
        write_key(keys, package_id)
    refused = score_command(out, keys)
    assert refused.exit_code == 1, refused.stdout + refused.stderr
    assert str(unfinished.value) in refused.stderr
    writes: list[Path] = []
    real_write = streams.write_atomic

    def atomic_spy(path: Path, data: bytes) -> None:
        writes.append(path)
        real_write(path, data)

    monkeypatch.setattr(streams, "write_atomic", atomic_spy)

    finished = pack_command(out)

    assert finished.exit_code == 0, finished.stdout + finished.stderr
    assert writes == []
    assert not list(out.rglob(events.EVENTS_FILE_NAME))
    assert (out / MANIFEST).read_bytes() == prior_rows
    assert {path: path.read_bytes() for path in prior_packed} == prior_packed
    scored = score_command(out, keys)
    assert scored.exit_code == 0, scored.stdout + scored.stderr


def test_a_resumed_packed_run_packs_only_its_new_attempts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    out, first = start_run(
        tmp_path, monkeypatch,
        [[ScriptedTurn(text="Completed.")], [ScriptedTurn(
            text="", fails=TransientError("fict first attempt failed"),
        )]],
        ("fict-a", "fict-b"),
    )
    assert first.exit_code == 1, first.stdout + first.stderr
    packed = pack_command(out)
    assert packed.exit_code == 0, packed.stdout + packed.stderr
    prior_rows = manifest(out)["streams"]
    prior_packed = {path: path.read_bytes() for path in out.rglob(events.PACKED_EVENTS_FILE_NAME)}
    install_driver_providers(monkeypatch, [[ScriptedTurn(text="Second attempt completed.")]])

    resumed = resume_command(out)

    assert resumed.exit_code == 0, resumed.stdout + resumed.stderr
    new_plain = out / "fict-b" / events.EVENTS_FILE_NAME
    expected_new = sha256_of_bytes(new_plain.read_bytes())
    repacked = pack_command(out)
    assert repacked.exit_code == 0, repacked.stdout + repacked.stderr
    assert manifest(out)["streams"] == {**prior_rows, "fict-b/events.jsonl.gz": expected_new}
    assert {path: path.read_bytes() for path in prior_packed} == prior_packed
    assert not list(out.rglob(events.EVENTS_FILE_NAME))
    assert driver_status(out)["packages"]["fict-b"]["kept_attempt"] == 2


def test_packing_a_packed_run_says_already_packed(
    packable_run: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    streams = packing_module()
    first = pack_command(packable_run)
    assert first.exit_code == 0, first.stdout + first.stderr
    before = snapshot(packable_run)

    def no_write(*args: Any, **options: Any) -> None:
        pytest.fail("packing an already packed folder wrote a file or contacted a provider")

    monkeypatch.setattr(streams, "write_atomic", no_write)
    monkeypatch.setattr(cli, "provider_factory", no_write)

    result = pack_command(packable_run)

    assert result.exit_code == 0, result.stdout + result.stderr
    assert result.stdout == f"{packable_run}: already packed\n"
    assert result.stderr == ""
    assert snapshot(packable_run) == before


def test_a_run_without_any_event_stream_records_no_rows_and_says_already_packed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def before_first_event(*args: Any, **options: Any) -> None:
        raise RuntimeError("fict failure before the first event")

    monkeypatch.setattr(cli, "_review_fn", before_first_event)
    out, first = start_run(
        tmp_path, monkeypatch, [[ScriptedTurn(text="Never started.")]], ("fict-a",),
    )
    assert first.exit_code == 1, first.stdout + first.stderr
    assert driver_status(out)["packages"]["fict-a"]["attempts"][0]["class"] == "internal_error"
    assert not list(out.rglob(events.EVENTS_FILE_NAME))
    assert not (out / MANIFEST).exists()

    result = pack_command(out)

    assert result.exit_code == 0, result.stdout + result.stderr
    assert manifest(out) == {"event_streams_version": 1, "streams": {}}
    assert not list(out.rglob(events.PACKED_EVENTS_FILE_NAME))
    assert result.stdout == f"{out}: already packed\n"
    assert result.stderr == ""


def test_duplicate_run_arguments_and_an_alias_pack_the_run_once(
    packable_run: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    streams = packing_module()
    out = packable_run
    alias = out / ".." / out.name
    assert alias != out and alias.resolve() == out.resolve()
    expected = {out / (relative + ".gz") for relative in stream_bytes(out)} | {out / MANIFEST}
    writes: list[Path] = []
    real_write = streams.write_atomic

    def atomic_spy(path: Path, data: bytes) -> None:
        writes.append(path)
        real_write(path, data)

    monkeypatch.setattr(streams, "write_atomic", atomic_spy)

    result = pack_command(out, alias, out)

    assert result.exit_code == 0, result.stdout + result.stderr
    assert result.stdout == f"{out}: packed\n"
    assert result.stderr == ""
    assert len(writes) == len(expected) and set(writes) == expected
    assert not list(out.rglob(events.EVENTS_FILE_NAME))


def test_an_unreadable_packed_stream_beside_a_plain_one_refuses_every_named_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    good, first = start_run(
        tmp_path / "fixture", monkeypatch, [[ScriptedTurn(text="Completed.")]], ("fict-a",),
    )
    assert first.exit_code == 0, first.stdout + first.stderr
    bad, last = tmp_path / "bad", tmp_path / "last"
    shutil.copytree(good, bad)
    shutil.copytree(good, last)
    packed = bad / "fict-a" / events.PACKED_EVENTS_FILE_NAME
    packed.write_bytes(b"fict malformed gzip bytes\n")
    before = {folder: snapshot(folder) for folder in (good, bad, last)}

    result = pack_command(good, bad, last)

    assert result.exit_code == 1, result.stdout + result.stderr
    assert result.stdout == ""
    lines = result.stderr.strip().splitlines()
    assert len(lines) == 1, result.stderr
    assert str(packed) in lines[0] and "the packed stream is unreadable" in lines[0]
    assert {folder: snapshot(folder) for folder in before} == before
