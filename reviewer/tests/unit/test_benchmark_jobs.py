"""Packages at once, with deterministic worker checkpoints (T205, owner decision 36A).

The scheduler and scripted reviews share an injected clock. Event waits synchronize
worker checkpoints; their timeouts are deadlock guards, never simulated elapsed time.
Retry backoff never sleeps. 94A: provider-specific coverage uses OpenAI and scripted
adapters; the scripted SAFETY response needs no Gemini adapter.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from swreview import atomic, cli
from swreview.agent.providers import ProviderError, retry
from swreview.agent.providers.fake import FakeProvider, ScriptedTurn
from swreview.benchmark import attempt as attempt_driver
from swreview.benchmark import runner
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
from tests.unit.test_benchmark_resume import rewrite_record, snapshot
from tests.unit.test_run_provenance import example_profile_copy

IDS = ("fict-a", "fict-b", "fict-c")
NOW = datetime(2026, 10, 15, 12, tzinfo=UTC)
ReviewBody = Callable[..., Any]


@pytest.fixture(autouse=True)
def deterministic_time_and_retry(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> datetime:
            return NOW if tz is not None else NOW.replace(tzinfo=None)

    sleeps: list[float] = []
    monkeypatch.setattr(runner, "datetime", FixedDateTime)
    monkeypatch.setattr(retry, "sleep", sleeps.append)
    monkeypatch.setattr(retry, "uniform", lambda low, high: high / 2)
    return sleeps


class HeldReviews:
    """Hold real review bodies and release them in a chosen completion order."""

    def __init__(
        self, ids: Sequence[str], jobs: int, *, delegate: ReviewBody | None = None,
        order: Sequence[str] | None = None,
    ) -> None:
        self.ids = tuple(ids)
        self.jobs = jobs
        self.delegate = delegate
        self.order = tuple(ids if order is None else order)
        self.condition = threading.Condition()
        self.gates = {package_id: threading.Event() for package_id in ids}
        self.started: list[str] = []
        self.ended: set[str] = set()
        self.completed: list[str] = []
        self.released: set[str] = set()
        self.active: set[str] = set()
        self.maximum = 0
        self.workers: dict[str, threading.Thread] = {}
        self.requests: dict[str, runner.AttemptRequest] = {}
        self.entries: dict[str, tuple[float, frozenset[str]]] = {}
        self.time = 0.0
        self.after_start: Callable[[str], None] = lambda package_id: None

    def __call__(self) -> float:
        with self.condition:
            return self.time

    def body(self, package_dir: Path, folder: Path, **options: Any) -> Any:
        package_id = package_dir.name
        with self.condition:
            assert package_id not in self.started
            self.started.append(package_id)
            self.active.add(package_id)
            self.maximum = max(self.maximum, len(self.active))
            self.workers[package_id] = threading.current_thread()
            self.requests[package_id] = options["attempt"]
            self.entries[package_id] = (self.time, frozenset(self.ended))
            self.condition.notify_all()
        try:
            assert self.gates[package_id].wait(timeout=30), "review was never released"
            if options["attempt"].stop.is_set():
                return None
            if self.delegate is not None:
                return self.delegate(package_dir, folder, **options)
            return None
        finally:
            with self.condition:
                self.active.remove(package_id)
                self.ended.add(package_id)
                self.condition.notify_all()

    def done(self, **row: Any) -> None:
        with self.condition:
            self.completed.append(row["package_id"])
            self.condition.notify_all()

    def release(self, package_id: str) -> None:
        with self.condition:
            assert package_id in self.started
            self.released.add(package_id)
            self.gates[package_id].set()
            assert self.condition.wait_for(
                lambda: package_id in self.ended, timeout=30,
            ), f"{package_id} did not finish its review"

    def wait(self, running: Sequence[Any], timeout: float) -> None:
        assert running
        assert 0 < timeout <= attempt_driver.WAIT_SLICE_S
        for package_id in self.order:
            if package_id in self.completed:
                continue
            if package_id not in self.released:
                self.release(package_id)
            # A body has returned; the real poll must consume its queued result
            # before the next body is released. Never depend on OS scheduling.
            return

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        real_start = getattr(attempt_driver, "start_attempt", None)
        if real_start is None:
            return  # T205 must be red for --jobs, before T206 adds this seam.
        calls = 0

        def start(body: Callable[[], Any], **options: Any) -> Any:
            nonlocal calls
            calls += 1
            expected = calls
            running = real_start(body, **options)
            with self.condition:
                assert self.condition.wait_for(
                    lambda: len(self.started) >= expected, timeout=30,
                ), "started worker did not enter its review"
                package_id = self.started[expected - 1]
            self.after_start(package_id)
            return running

        monkeypatch.setattr(attempt_driver, "start_attempt", start)

    def close(self) -> None:
        for gate in self.gates.values():
            gate.set()
        with self.condition:
            assert self.condition.wait_for(lambda: not self.active, timeout=30), (
                "review worker did not leave its checkpoint during cleanup"
            )


@contextmanager
def controlled(
    monkeypatch: pytest.MonkeyPatch, reviews: HeldReviews,
    *, wait: Callable[[Sequence[Any], float], None] | None = None,
) -> Iterator[None]:
    """Inject the same public clock/wait seams into run and resume commands."""
    with monkeypatch.context() as patch:
        reviews.install(patch)
        patch.setattr(cli, "_review_fn", reviews.body)

        def wrap(real: Callable[..., Any]) -> Callable[..., Any]:
            def invoke(*args: Any, **options: Any) -> Any:
                original_done = options.get("on_package_done")

                def done(**row: Any) -> None:
                    if original_done is not None:
                        original_done(**row)
                    reviews.done(**row)

                options.update(
                    clock=reviews, wait_for_attempts=reviews.wait if wait is None else wait,
                    on_package_done=done,
                )
                return real(*args, **options)

            return invoke

        patch.setattr(cli, "run_benchmark", wrap(cli.run_benchmark))
        patch.setattr(cli, "resume_benchmark", wrap(cli.resume_benchmark))
        try:
            yield
        finally:
            reviews.close()


def command(folder: Path, out: Path, *options: str, provider: str = "fake") -> Any:
    return CliRunner().invoke(cli.app, [
        "benchmark", "run", "--set", str(folder / "set.json"), "--out", str(out),
        "--provider", provider, *options,
    ])


def library_run(
    preflighted: runner.PreflightedSet, out: Path, reviews: HeldReviews, **options: Any,
) -> list[Path]:
    return runner.run_benchmark(
        preflighted, out, provider="fake", model="fict-model-a", effort="high",
        **options,
        review_fn=reviews.body, clock=reviews, wait_for_attempts=reviews.wait,
        on_package_done=reviews.done,
    )


def scripted_body(scripts: dict[str, Sequence[ScriptedTurn]]) -> ReviewBody:
    """Choose each script by package, independent of the completion order."""
    real_review = cli._review_fn

    def review(package: Path, folder: Path, *, run_start: Any = None, **options: Any) -> Any:
        adapter = FakeProvider(
            script=scripts.get(package.name, [ScriptedTurn(text="Reviewed.")]),
            model=options["model"], clock=lambda: 0.0, sleep=lambda delay: None,
        )
        return real_review(
            package, folder, run_start=cli.RunStartAdapter(adapter), **options,
        )

    return review


def mixed_scripts() -> list[list[ScriptedTurn]]:
    return [
        [ScriptedTurn(text="Reviewed.")],
        [ScriptedTurn(text="", stop_reason="SAFETY", end_reason="error")],
        [ScriptedTurn(text="", fails=TransientError("fict exhausted request"))],
    ]


def test_packages_run_at_once_up_to_n_and_never_more(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    ids = (*IDS, "fict-d", "fict-e")
    prepare_driver_set(tmp_path, ids)
    reviews = HeldReviews(ids, 3, order=("fict-b", "fict-d", "fict-a", "fict-e", "fict-c"))
    first_wait = True

    def wait(running: Sequence[Any], timeout: float) -> None:
        nonlocal first_wait
        if first_wait:
            assert reviews.started == list(ids[:3])
            assert reviews.active == set(ids[:3])
            assert reviews.maximum == 3
            first_wait = False
        reviews.wait(running, timeout)

    with controlled(monkeypatch, reviews, wait=wait):
        result = command(tmp_path, tmp_path / "run", "--jobs", "3")
    assert result.exit_code == 0, result.stdout + result.stderr
    assert reviews.started == list(ids)
    assert reviews.maximum == 3
    assert "fict-b" in reviews.entries["fict-d"][1]
    assert reviews.completed == list(reviews.order)


def test_a_poll_pass_processes_ready_attempts_in_distinct_completion_time_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    preflighted = prepare_driver_set(tmp_path, IDS)
    reviews = HeldReviews(IDS, 3)
    completion_order = ("fict-c", "fict-a", "fict-b")
    waits: list[float] = []
    polled_times: list[float] = []
    real_poll = attempt_driver.RunningAttempt.poll

    def poll(running: Any, observed_at: float) -> Any:
        outcome = real_poll(running, observed_at)
        if outcome is not None:
            polled_times.append(running.completed_at)
        return outcome

    def wait(running: Sequence[Any], timeout: float) -> None:
        waits.append(timeout)
        assert len(waits) == 1
        assert len(running) == 3
        for completed_at, package_id in enumerate(completion_order, start=1):
            with reviews.condition:
                reviews.time = float(completed_at)
            reviews.release(package_id)
            worker = reviews.workers[package_id]
            worker.join(timeout=30)
            assert not worker.is_alive(), "worker did not publish its completion"

    reviews.install(monkeypatch)
    monkeypatch.setattr(attempt_driver.RunningAttempt, "poll", poll)
    try:
        assert runner.run_benchmark(
            preflighted, tmp_path / "run", provider="fake", model="fict-model-a",
            effort="high", review_fn=reviews.body, clock=reviews, jobs=3,
            wait_for_attempts=wait, on_package_done=reviews.done,
        ) == [tmp_path / "run" / package_id for package_id in IDS]
    finally:
        reviews.close()
    assert len(waits) == 1
    assert polled_times == [2.0, 3.0, 1.0]
    assert reviews.completed == list(completion_order)


def test_parallel_attempts_use_the_default_scheduler_wait(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    preflighted = prepare_driver_set(tmp_path, IDS)
    reviews = HeldReviews(IDS, 2)
    completion_order = iter(("fict-b", "fict-c", "fict-a"))
    waited_on: list[threading.Thread] = []
    real_wait = attempt_driver.RunningAttempt.wait

    def wait(running: Any, timeout: float, wait_for_result: Any = None) -> None:
        assert wait_for_result is None
        waited_on.append(running.worker)

        def queue_wait(results: Any, queue_timeout: float) -> Any:
            assert queue_timeout == timeout
            package_id = next(completion_order)
            reviews.release(package_id)
            worker = reviews.workers[package_id]
            worker.join(timeout=30)
            assert not worker.is_alive(), "worker did not publish its completion"
            return results.get_nowait()

        real_wait(running, timeout, wait_for_result=queue_wait)

    reviews.install(monkeypatch)
    monkeypatch.setattr(attempt_driver.RunningAttempt, "wait", wait)
    try:
        # Omit wait_for_attempts: the real scheduler default calls RunningAttempt.wait.
        assert runner.run_benchmark(
            preflighted, tmp_path / "run", provider="fake", model="fict-model-a",
            effort="high", review_fn=reviews.body, clock=reviews, jobs=2,
            on_package_done=reviews.done,
        ) == [tmp_path / "run" / package_id for package_id in IDS]
    finally:
        reviews.close()
    assert reviews.maximum == 2
    assert reviews.completed == ["fict-b", "fict-c", "fict-a"]
    assert waited_on == [reviews.workers["fict-a"]] * 3


def test_jobs_one_run_status_bytes_match_the_t196_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    ids = (*IDS, "fict-d")
    prepare_driver_set(tmp_path, ids)
    install_driver_providers(
        monkeypatch, mixed_scripts() + [[ScriptedTurn(text="Reviewed d.")]],
    )
    reviews = HeldReviews(ids, 1, delegate=cli._review_fn)

    def wait(running: Sequence[Any], timeout: float) -> None:
        reviews.wait(running, timeout)
        running[0].worker.join(timeout=30)
        assert not running[0].worker.is_alive(), "worker did not publish its completion"

    out = tmp_path / "run"
    with controlled(monkeypatch, reviews, wait=wait):
        result = command(tmp_path, out, "--jobs", "1")
    assert result.exit_code == 1, result.stdout + result.stderr
    # Literal T196 baseline bytes, captured before the concurrent scheduler existed.
    expected = b'''{
  "run_status_version": 1,
  "packages": {
    "fict-a": {
      "kept_attempt": 1,
      "attempts": [
        {
          "attempt": 1,
          "started_at": "2026-10-15T12:00:00Z",
          "ended_at": "2026-10-15T12:00:00Z",
          "resumed": false,
          "kind": "completed",
          "class": null,
          "stop_reason": null,
          "error_class": null,
          "message": null,
          "stream_active_at_limit": null,
          "folder": "fict-a"
        }
      ]
    },
    "fict-b": {
      "kept_attempt": 1,
      "attempts": [
        {
          "attempt": 1,
          "started_at": "2026-10-15T12:00:00Z",
          "ended_at": "2026-10-15T12:00:00Z",
          "resumed": false,
          "kind": "behavioural",
          "class": "provider_stop",
          "stop_reason": "SAFETY",
          "error_class": "ProviderError",
          "message": "scripted provider stopped the turn: SAFETY",
          "stream_active_at_limit": null,
          "folder": "fict-b"
        }
      ]
    },
    "fict-c": {
      "kept_attempt": null,
      "attempts": [
        {
          "attempt": 1,
          "started_at": "2026-10-15T12:00:00Z",
          "ended_at": "2026-10-15T12:00:00Z",
          "resumed": false,
          "kind": "infrastructure",
          "class": "provider_error",
          "stop_reason": null,
          "error_class": "TransientError",
          "message": "fict exhausted request",
          "stream_active_at_limit": null,
          "folder": "attempts/fict-c/1"
        }
      ]
    },
    "fict-d": {
      "kept_attempt": 1,
      "attempts": [
        {
          "attempt": 1,
          "started_at": "2026-10-15T12:00:00Z",
          "ended_at": "2026-10-15T12:00:00Z",
          "resumed": false,
          "kind": "completed",
          "class": null,
          "stop_reason": null,
          "error_class": null,
          "message": null,
          "stream_active_at_limit": null,
          "folder": "fict-d"
        }
      ]
    }
  }
}
'''
    assert (out / runner.RUN_STATUS_FILE).read_bytes() == expected


def test_jobs_one_runs_one_package_at_a_time_as_before(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    preflighted = prepare_driver_set(tmp_path, IDS)
    statuses: list[bytes] = []
    real_review = cli._review_fn
    for typed, json_output in ((True, False), (False, False), (True, True), (False, True)):
        install_driver_providers(monkeypatch, mixed_scripts())
        out = tmp_path / f"run-{typed}-{json_output}"
        reviews = HeldReviews(IDS, 1, delegate=real_review)
        options = [*(["--jobs", "1"] if typed else []), *(["--json"] if json_output else [])]
        with controlled(monkeypatch, reviews):
            result = command(tmp_path, out, *options)
        assert result.exit_code == 1, result.stdout + result.stderr
        assert reviews.maximum == 1
        assert reviews.started == list(IDS)
        assert all(set(IDS[:i]) <= reviews.entries[package_id][1]
                   for i, package_id in enumerate(IDS))
        assert result.stderr.splitlines() == [
            f"error: infrastructure failures: fict-c; run swreview benchmark resume {out}",
        ]
        if json_output:
            payload = json.loads(result.stdout)
            assert payload == {
                "set": str((tmp_path / "set.json").resolve()),
                "benchmark_set": "fict-driver", "out_dir": str(out),
                "saved_set_file": str(out / runner.SAVED_SET_FILE),
                "provenance_file": str(out / runner.PROVENANCE_FILE),
                "provider": "fake", "model": runner.load_provenance(out).model,
                "packages": [
                    {"package_id": "fict-a", "out_dir": str(out / "fict-a"),
                     "kind": "completed", "class": None, "stop_reason": None, "attempts": 1},
                    {"package_id": "fict-b", "out_dir": str(out / "fict-b"),
                     "kind": "behavioural", "class": "provider_stop", "stop_reason": "SAFETY",
                     "attempts": 1},
                    {"package_id": "fict-c", "kind": "infrastructure", "class": "provider_error",
                     "stop_reason": None, "attempts": 1},
                ],
            }
        else:
            assert result.stdout.splitlines() == [
                "fict-a: completed", "fict-b: behavioural provider_stop (SAFETY)",
                "fict-c: infrastructure provider_error (TransientError, 5 retries)",
            ]
        statuses.append((out / runner.RUN_STATUS_FILE).read_bytes())

    install_driver_providers(monkeypatch, mixed_scripts())
    out = tmp_path / "library-default"
    reviews = HeldReviews(IDS, 1, delegate=real_review)
    with monkeypatch.context() as patch:
        reviews.install(patch)
        try:
            # The public library default remains one; deliberately omit jobs.
            assert library_run(preflighted, out, reviews) == [out / "fict-a", out / "fict-b"]
        finally:
            reviews.close()
    assert reviews.maximum == 1
    assert reviews.started == list(IDS)
    statuses.append((out / runner.RUN_STATUS_FILE).read_bytes())
    assert all(data == statuses[0] for data in statuses)


def test_the_run_status_record_stays_valid_under_concurrency(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    deterministic_time_and_retry: list[float],
) -> None:
    class RateLimitError(ProviderError):
        retryable = True

    ids = tuple(f"fict-{letter}" for letter in "abcdefgh")
    prepare_driver_set(tmp_path, ids)
    scripts = {
        "fict-c": [ScriptedTurn(text="", fails=RateLimitError("fict rate limited"))],
        "fict-g": [ScriptedTurn(text="", fails=TransientError("fict request failed"))],
        "fict-e": [ScriptedTurn(text="", stop_reason="SAFETY", end_reason="error")],
    }
    reviews = HeldReviews(
        ids, 4, delegate=scripted_body(scripts),
        order=("fict-d", "fict-b", "fict-f", "fict-a", "fict-h", "fict-g", "fict-e", "fict-c"),
    )
    scheduler_thread = threading.get_ident()
    records: list[runner.RunStatus] = []
    real_write = atomic.write_atomic

    def write(path: Path, data: bytes) -> None:
        if path.name == runner.RUN_STATUS_FILE:
            assert threading.get_ident() == scheduler_thread
            record = runner.RunStatus.model_validate_json(data)
            if records:
                for package_id, package in records[-1].packages.items():
                    current = record.packages[package_id]
                    assert {row.attempt for row in package.attempts} <= {
                        row.attempt for row in current.attempts
                    }
                    for old, new in zip(package.attempts, current.attempts, strict=True):
                        assert old.started_at == new.started_at
                        if old.kind is not None:
                            assert (new.kind, new.class_, new.ended_at) == (
                                old.kind, old.class_, old.ended_at,
                            )
            records.append(record)
        real_write(path, data)

    monkeypatch.setattr(atomic, "write_atomic", write)
    out = tmp_path / "run"
    with controlled(monkeypatch, reviews):
        result = command(tmp_path, out, "--jobs", "4")
    assert result.exit_code == 1, result.stdout + result.stderr
    assert reviews.maximum == 4
    assert records and list(records[-1].packages) == list(ids)
    assert list(driver_status(out)["packages"]) == list(ids)
    for package_id, error_class in (("fict-c", "RateLimitError"), ("fict-g", "TransientError")):
        row = driver_row(out, package_id)
        assert (row["kind"], row["class"], row["error_class"]) == (
            "infrastructure", "provider_error", error_class,
        )
        assert runner.attempt_facts(out / row["folder"]).retries == retry.BENCHMARK_RETRY.retries
    assert len(deterministic_time_and_retry) == 2 * retry.BENCHMARK_RETRY.retries
    assert driver_row(out, "fict-e")["stop_reason"] == "SAFETY"


def test_each_package_keeps_its_own_folder_stream_and_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    preflighted = prepare_driver_set(tmp_path, IDS)
    reviews = HeldReviews(IDS, 3, delegate=scripted_body({}), order=tuple(reversed(IDS)))
    out = tmp_path / "run"
    renamed: list[tuple[Path, Path]] = []
    real_rename = Path.rename

    def rename(source: Path, target: Any) -> Path:
        if source.parent.parent.name == runner.ATTEMPTS_FOLDER:
            renamed.append((source, Path(target)))
        return real_rename(source, target)

    monkeypatch.setattr(Path, "rename", rename)
    with monkeypatch.context() as patch:
        reviews.install(patch)
        try:
            assert library_run(preflighted, out, reviews, jobs=3) == [out / id_ for id_ in IDS]
        finally:
            reviews.close()
    workers = list(reviews.workers.values())
    assert len(set(workers)) == 3
    assert all(worker.daemon and worker is not threading.current_thread() for worker in workers)
    assert len({id(request.stop) for request in reviews.requests.values()}) == 3
    assert len({id(request.listener) for request in reviews.requests.values()}) == 3
    session_ids: set[str] = set()
    for package_id in IDS:
        folder = out / package_id
        session_id = str(load_session(folder / "session.json").session_id)
        session_ids.add(session_id)
        stream = driver_events(folder)
        assert [event.seq for event in stream] == list(range(1, len(stream) + 1))
        assert {event.body["session_id"] for event in stream if "session_id" in event.body} == {
            session_id,
        }
        assert reviews.requests[package_id].run_dir == out
        assert not (out / "attempts" / package_id / "1").exists()
    assert len(session_ids) == 3
    assert sorted(renamed) == sorted(
        (out / "attempts" / package_id / "1", out / package_id) for package_id in IDS
    )


def test_the_run_start_adapter_serves_exactly_one_attempt_under_concurrency(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_driver_set(tmp_path, IDS)
    real_review = cli._review_fn
    real_start_review = cli.start_review
    real_take = cli.RunStartAdapter.take
    for provider in ("fake", "openai"):
        # 94A: OpenAI and scripted settings, never a Gemini adapter or a request.
        monkeypatch.setenv("OPENAI_API_KEY", "fict-jobs-key")
        built: list[FakeProvider] = []
        used: dict[str, FakeProvider] = {}
        taken: list[FakeProvider] = []
        lock = threading.Lock()
        barrier = threading.Barrier(3)

        def factory(
            settings: Any, efficiency: Any = None, *,
            _lock: Any = lock, _built: list[FakeProvider] = built,
        ) -> FakeProvider:
            with _lock:
                adapter = FakeProvider(
                    script=[ScriptedTurn(text="Reviewed.")], model=settings.model,
                )
                _built.append(adapter)
                return adapter

        def take(holder: Any, _lock: Any = lock, _taken: list[FakeProvider] = taken) -> Any:
            value = real_take(holder)
            if value is not None:
                with _lock:
                    _taken.append(value)
            return value

        def start_review(
            package: Path, folder: Path, *,
            _lock: Any = lock, _used: dict[str, FakeProvider] = used, **options: Any,
        ) -> Any:
            with _lock:
                _used[package.name] = options["provider"]
            return real_start_review(package, folder, **options)

        def body(*args: Any, _barrier: Any = barrier, **options: Any) -> Any:
            _barrier.wait(timeout=30)
            return real_review(*args, **options)

        reviews = HeldReviews(IDS, 3, delegate=body)

        def wait(
            running: Sequence[Any], timeout: float, _reviews: HeldReviews = reviews,
        ) -> None:
            for gate in _reviews.gates.values():
                gate.set()
            with _reviews.condition:
                assert _reviews.condition.wait_for(lambda: len(_reviews.ended) == 3, timeout=30)

        with monkeypatch.context() as patch:
            patch.setattr(cli, "provider_factory", factory)
            patch.setattr(cli, "start_review", start_review)
            patch.setattr(cli.RunStartAdapter, "take", take)
            with controlled(patch, reviews, wait=wait):
                result = command(tmp_path, tmp_path / provider, "--jobs", "3", provider=provider)
        assert result.exit_code == 0, result.stdout + result.stderr
        assert len(built) == 3
        assert taken == [built[0]]
        assert set(used) == set(IDS)
        assert len({id(adapter) for adapter in used.values()}) == 3
        assert sum(adapter is built[0] for adapter in used.values()) == 1


def test_lines_print_whole_as_packages_end_and_json_keeps_set_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_driver_set(tmp_path, IDS)
    real_echo = cli.typer.echo
    scheduler_thread = threading.get_ident()
    for json_output in (False, True):
        echoed: list[str] = []

        def echo(
            message: Any = None, *args: Any, _echoed: list[str] = echoed, **options: Any,
        ) -> Any:
            if isinstance(message, str) and (
                message.startswith(tuple(f"{id_}:" for id_ in IDS))
                or message.startswith("error: infrastructure failures:")
            ):
                assert threading.get_ident() == scheduler_thread
                assert "\n" not in message and "\r" not in message
                _echoed.append(message)
            return real_echo(message, *args, **options)

        scripts = dict(zip(IDS, mixed_scripts(), strict=True))
        reviews = HeldReviews(IDS, 3, delegate=scripted_body(scripts), order=tuple(reversed(IDS)))
        out = tmp_path / f"run-{json_output}"
        with monkeypatch.context() as patch:
            patch.setattr(cli.typer, "echo", echo)
            with controlled(patch, reviews):
                result = command(tmp_path, out, "--jobs", "3", *(["--json"] if json_output else []))
        assert result.exit_code == 1, result.stdout + result.stderr
        exit_line = f"error: infrastructure failures: fict-c; run swreview benchmark resume {out}"
        assert result.stderr.splitlines() == [exit_line]
        if json_output:
            rows = json.loads(result.stdout)["packages"]
            assert [row["package_id"] for row in rows] == list(IDS)
            assert [(row["kind"], row["class"], row["stop_reason"], row["attempts"])
                    for row in rows] == [
                ("completed", None, None, 1), ("behavioural", "provider_stop", "SAFETY", 1),
                ("infrastructure", "provider_error", None, 1),
            ]
            assert echoed == [exit_line]
        else:
            lines = [
                "fict-c: infrastructure provider_error (TransientError, 5 retries)",
                "fict-b: behavioural provider_stop (SAFETY)", "fict-a: completed",
            ]
            assert result.stdout.splitlines() == lines
            assert echoed == [*lines, exit_line]
        assert reviews.completed == list(reversed(IDS))


def test_a_silent_package_holds_only_its_own_slot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    preflighted = prepare_driver_set(tmp_path, IDS)
    reviews = HeldReviews(IDS, 2, order=("fict-b", "fict-c"))

    def after_start(package_id: str) -> None:
        if package_id == "fict-a":
            reviews.time = 4.0  # b starts four seconds after a, with its own W.

    reviews.after_start = after_start

    def wait(running: Sequence[Any], timeout: float) -> None:
        if "fict-a" not in reviews.completed:
            assert reviews.started == ["fict-a", "fict-b"]
            reviews.time = 8.0  # a reached W+G; b has not reached its own W.
            return
        reviews.wait(running, timeout)

    out = tmp_path / "run"
    with monkeypatch.context() as patch:
        reviews.install(patch)
        try:
            kept = runner.run_benchmark(
                preflighted, out, provider="fake", model="fict-model-a", effort="high",
                review_fn=reviews.body, jobs=2, clock=reviews, wait_for_attempts=wait,
                on_package_done=reviews.done, package_time_limit_s=5,
                stream_activity_window_s=1, stop_grace_s=3,
            )
            assert kept == [out / "fict-b", out / "fict-c"]
            assert "fict-a" not in reviews.ended
            assert reviews.workers["fict-a"].daemon
            assert reviews.workers["fict-a"].is_alive()
            assert reviews.requests["fict-a"].stop.is_set()
        finally:
            reviews.close()
    assert driver_row(out, "fict-a")["class"] == "abandoned"
    assert driver_row(out, "fict-a")["stream_active_at_limit"] is False
    assert reviews.entries["fict-c"][0] == 8.0
    assert "fict-a" not in reviews.entries["fict-c"][1]
    assert all(driver_row(out, package_id)["kind"] == "completed" for package_id in IDS[1:])


def test_ctrl_c_under_concurrency_records_every_running_attempt_interrupted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    ids = (*IDS, "fict-d", "fict-e")
    preflighted = prepare_driver_set(tmp_path, ids)
    reviews = HeldReviews(ids, 3)

    def interrupt(running: Sequence[Any], timeout: float) -> None:
        assert len(running) == 3
        assert reviews.started == list(ids[:3])
        assert reviews.active == set(ids[:3])
        raise KeyboardInterrupt

    out = tmp_path / "run"
    with monkeypatch.context() as patch:
        reviews.install(patch)
        try:
            with pytest.raises(KeyboardInterrupt):
                runner.run_benchmark(
                    preflighted, out, provider="fake", model="fict-model-a", effort="high",
                    review_fn=reviews.body, jobs=3, clock=reviews, wait_for_attempts=interrupt,
                )
            assert reviews.started == list(ids[:3])
            assert list(driver_status(out)["packages"]) == list(ids[:3])
            for package_id in ids[:3]:
                row = driver_row(out, package_id)
                assert (row["kind"], row["class"]) == ("infrastructure", "interrupted")
                assert datetime.fromisoformat(row["ended_at"].replace("Z", "+00:00")) == NOW
                assert reviews.requests[package_id].stop.is_set()
            assert not (out / "attempts/fict-d").exists()
        finally:
            reviews.close()


def test_a_profile_changed_under_concurrency_starts_no_further_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_driver_set(tmp_path, (*IDS, "fict-d"))
    profile = example_profile_copy(tmp_path / "profiles")
    recorded = sha256_of(profile)

    def body(package: Path, folder: Path, **options: Any) -> None:
        if package.name == "fict-a":
            profile.write_bytes(profile.read_bytes() + b"\n# fict changed profile\n")

    reviews = HeldReviews((*IDS, "fict-d"), 2, delegate=body, order=IDS[:2])
    out = tmp_path / "run"
    with controlled(monkeypatch, reviews):
        result = command(tmp_path, out, "--jobs", "2", "--standards-profile", str(profile))
    assert result.exit_code == 1, result.stdout + result.stderr
    assert reviews.started == list(IDS[:2])
    assert reviews.completed == list(IDS[:2])
    assert all(driver_row(out, package_id)["kind"] == "completed" for package_id in IDS[:2])
    assert not (out / "attempts/fict-c").exists()
    assert not (out / "attempts/fict-d").exists()
    line = result.stderr.strip()
    assert line == (
        "error: ValueError: standards profile changed: recorded "
        f"{display_digest(recorded)}, current {display_digest(sha256_of(profile))}"
    )
    assert str(profile) not in line and str(tmp_path) not in line


def test_ctrl_c_from_a_completion_callback_preserves_the_completed_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    ids = (*IDS, "fict-d", "fict-e")
    preflighted = prepare_driver_set(tmp_path, ids)
    reviews = HeldReviews(ids, 3)
    callbacks: list[str] = []

    def interrupt_after_completion(**row: Any) -> None:
        assert row["package_id"] == "fict-a"
        assert row["kind"] == "completed"
        callbacks.append(row["package_id"])
        raise KeyboardInterrupt

    out = tmp_path / "run"
    with monkeypatch.context() as patch:
        reviews.install(patch)
        try:
            with pytest.raises(KeyboardInterrupt):
                runner.run_benchmark(
                    preflighted, out, provider="fake", model="fict-model-a", effort="high",
                    review_fn=reviews.body, jobs=3, clock=reviews,
                    wait_for_attempts=reviews.wait, on_package_done=interrupt_after_completion,
                )
            assert callbacks == ["fict-a"]
            completed = driver_row(out, "fict-a")
            assert (completed["kind"], completed["class"]) == ("completed", None)
            assert completed["folder"] == "fict-a"
            assert driver_status(out)["packages"]["fict-a"]["kept_attempt"] == 1
            assert (out / "fict-a").is_dir()
            assert not (out / "attempts/fict-a/1").exists()
            for package_id in IDS[1:]:
                row = driver_row(out, package_id)
                assert (row["kind"], row["class"]) == ("infrastructure", "interrupted")
                assert row["ended_at"] is not None
                assert reviews.requests[package_id].stop.is_set()
            assert reviews.started == list(IDS)
            assert not (out / "attempts/fict-d").exists()
        finally:
            reviews.close()


def release_results(
    reviews: HeldReviews, running: Sequence[Any], *package_ids: str,
) -> None:
    """Publish worker results before the scheduler's next nonblocking poll."""
    for package_id in package_ids:
        reviews.release(package_id)
        worker = next(item.worker for item in running if item.worker is reviews.workers[package_id])
        worker.join(timeout=30)
        assert not worker.is_alive(), f"{package_id} did not publish its result"


@pytest.mark.parametrize("failure_type", [OSError, SystemExit])
def test_a_scheduler_exception_stops_and_records_every_in_flight_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure_type: type[BaseException],
) -> None:
    ids = (*IDS, "fict-d")
    preflighted = prepare_driver_set(tmp_path, ids)
    reviews = HeldReviews(ids, 3)
    failure = failure_type("fict stdout closed")

    def wait(running: Sequence[Any], timeout: float) -> None:
        release_results(reviews, running, "fict-a")

    def done(**row: Any) -> None:
        assert row["package_id"] == "fict-a"
        raise failure

    out = tmp_path / "run"
    with monkeypatch.context() as patch:
        reviews.install(patch)
        try:
            with pytest.raises(failure_type) as raised:
                runner.run_benchmark(
                    preflighted, out, provider="fake", model="fict-model-a", effort="high",
                    review_fn=reviews.body, jobs=3, clock=reviews,
                    wait_for_attempts=wait, on_package_done=done,
                )
            assert raised.value is failure
            assert driver_row(out, "fict-a")["kind"] == "completed"
            assert driver_status(out)["packages"]["fict-a"]["kept_attempt"] == 1
            assert reviews.started == list(IDS)
            for package_id in IDS[1:]:
                row = driver_row(out, package_id)
                assert (row["kind"], row["class"]) == ("infrastructure", "interrupted")
                assert row["ended_at"] == "2026-10-15T12:00:00Z"
                assert reviews.requests[package_id].stop.is_set()
            assert not (out / "attempts/fict-d").exists()
        finally:
            reviews.close()


@pytest.mark.parametrize("interrupt_at", ["callback", "wait"])
@pytest.mark.parametrize("finished_kind", ["completed", "behavioural", "infrastructure"])
def test_interrupt_preserves_results_already_polled_or_still_queued(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, interrupt_at: str, finished_kind: str,
) -> None:
    ids = (*IDS, "fict-d")
    preflighted = prepare_driver_set(tmp_path, ids)

    def body(package: Path, folder: Path, **options: Any) -> None:
        (folder / "marker.txt").write_bytes(b"fict review finished\n")
        if package.name == "fict-b":
            if finished_kind == "behavioural":
                failure = ProviderError("fict safety stop")
                failure.stop_reason = "SAFETY"
                raise failure
            if finished_kind == "infrastructure":
                raise OSError("fict review failure")

    reviews = HeldReviews(ids, 3, delegate=body)

    def wait(running: Sequence[Any], timeout: float) -> None:
        release_results(reviews, running, "fict-a", "fict-b")
        if interrupt_at == "wait":
            # Neither result has been consumed by poll yet.
            assert all(not item._results.empty() for item in running[:2])
            raise KeyboardInterrupt

    def done(**row: Any) -> None:
        assert interrupt_at == "callback" and row["package_id"] == "fict-a"
        raise KeyboardInterrupt

    out = tmp_path / "run"
    with monkeypatch.context() as patch:
        reviews.install(patch)
        try:
            with pytest.raises(KeyboardInterrupt):
                runner.run_benchmark(
                    preflighted, out, provider="fake", model="fict-model-a", effort="high",
                    review_fn=reviews.body, jobs=3, clock=reviews,
                    wait_for_attempts=wait, on_package_done=done,
                )
            expected_class = {
                "completed": None, "behavioural": "provider_stop",
                "infrastructure": "internal_error",
            }[finished_kind]
            row = driver_row(out, "fict-b")
            assert (row["kind"], row["class"]) == (finished_kind, expected_class)
            assert row["stop_reason"] == ("SAFETY" if finished_kind == "behavioural" else None)
            assert row["error_class"] == {
                "completed": None, "behavioural": "ProviderError", "infrastructure": "OSError",
            }[finished_kind]
            assert row["message"] == {
                "completed": None, "behavioural": "fict safety stop",
                "infrastructure": "fict review failure",
            }[finished_kind]
            assert row["ended_at"] == "2026-10-15T12:00:00Z"
            assert row["folder"] == "attempts/fict-b/1"
            assert (out / row["folder"] / "marker.txt").read_bytes() == b"fict review finished\n"
            kept = driver_status(out)["packages"]["fict-b"]["kept_attempt"]
            assert kept == (None if finished_kind == "infrastructure" else 1)
            assert driver_row(out, "fict-a")["kind"] == "completed"
            assert driver_status(out)["packages"]["fict-a"]["kept_attempt"] == 1
            assert (driver_row(out, "fict-c")["kind"], driver_row(out, "fict-c")["class"]) == (
                "infrastructure", "interrupted",
            )
            assert all(request.stop.is_set() for request in reviews.requests.values())
            assert reviews.started == list(IDS)
        finally:
            reviews.close()


@pytest.mark.parametrize("unreadable", ["deleted", "renamed", "permission"])
def test_an_unreadable_profile_halts_new_attempts_and_drains_running_attempts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, unreadable: str,
) -> None:
    ids = (*IDS, "fict-d")
    preflighted = prepare_driver_set(tmp_path, ids)
    profile = example_profile_copy(tmp_path / "profiles")
    recorded = sha256_of(profile)
    real_digest = runner.sha256_of
    changed = False

    def digest(path: Path) -> str:
        if changed and path == profile and unreadable == "permission":
            raise PermissionError("fict profile unreadable")
        return real_digest(path)

    monkeypatch.setattr(runner, "sha256_of", digest)

    def body(package: Path, folder: Path, **options: Any) -> None:
        nonlocal changed
        assert not options["attempt"].stop.is_set(), "profile changes must let workers drain"
        if package.name == "fict-a":
            if unreadable == "deleted":
                profile.unlink()
            elif unreadable == "renamed":
                profile.rename(profile.with_suffix(".moved"))
            changed = True

    reviews = HeldReviews(ids, 2, delegate=body)

    def wait(running: Sequence[Any], timeout: float) -> None:
        package_id = "fict-a" if "fict-a" not in reviews.completed else "fict-b"
        release_results(reviews, running, package_id)

    out = tmp_path / "run"
    with monkeypatch.context() as patch:
        reviews.install(patch)
        try:
            with pytest.raises(ValueError) as raised:
                runner.run_benchmark(
                    preflighted, out, provider="fake", model="fict-model-a", effort="high",
                    review_fn=reviews.body, jobs=2, clock=reviews,
                    wait_for_attempts=wait, on_package_done=reviews.done,
                    standards_profile=profile,
                )
            assert str(raised.value) == (
                f"standards profile changed: recorded {display_digest(recorded)}, current unknown"
            )
            assert reviews.started == list(IDS[:2])
            assert reviews.completed == list(IDS[:2])
            assert all(driver_row(out, id_)["kind"] == "completed" for id_ in IDS[:2])
            assert not any(request.stop.is_set() for request in reviews.requests.values())
            assert not (out / "attempts/fict-c").exists()
            assert not (out / "attempts/fict-d").exists()
        finally:
            reviews.close()


def test_a_cleanup_write_failure_preserves_the_scheduler_exception_and_sets_every_stop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    preflighted = prepare_driver_set(tmp_path, IDS)
    reviews = HeldReviews(IDS, 3)
    failure = KeyboardInterrupt("fict interrupt in completion callback")
    real_write = runner._write_run_status
    fail_writes = False

    def write(*args: Any, **options: Any) -> Any:
        if fail_writes:
            raise OSError("fict status disk unavailable")
        return real_write(*args, **options)

    def wait(running: Sequence[Any], timeout: float) -> None:
        release_results(reviews, running, "fict-a")

    def done(**row: Any) -> None:
        nonlocal fail_writes
        fail_writes = True
        raise failure

    monkeypatch.setattr(runner, "_write_run_status", write)
    reviews.install(monkeypatch)
    try:
        with pytest.raises(KeyboardInterrupt) as raised:
            runner.run_benchmark(
                preflighted, tmp_path / "run", provider="fake", model="fict-model-a",
                effort="high", review_fn=reviews.body, jobs=3, clock=reviews,
                wait_for_attempts=wait, on_package_done=done,
            )
        assert raised.value is failure
        assert all(request.stop.is_set() for request in reviews.requests.values())
        assert any("fict status disk unavailable" in note for note in failure.__notes__)
    finally:
        reviews.close()


def test_interrupt_marks_listeners_before_stopping_reviews_that_return_normally(
    tmp_path: Path,
) -> None:
    """P5: stop-triggered normal returns must never become kept reviews."""
    ids = IDS[:2]
    preflighted = prepare_driver_set(tmp_path, ids)
    running: list[attempt_driver.RunningAttempt] = []
    interrupted = False

    def clock() -> float:
        if interrupted and threading.current_thread() is threading.main_thread():
            # Replace the probe's 50 ms per poll with a deterministic checkpoint:
            # results caused by stop are queued before any subsequent handler poll.
            for item in running:
                if item.stop.is_set():
                    item.worker.join(timeout=30)
                    assert not item.worker.is_alive(), "stopped review did not return"
        return 0.0

    def body(package: Path, folder: Path, **options: Any) -> None:
        assert options["attempt"].stop.wait(timeout=30), "review was never stopped"
        (folder / "cut-short.txt").write_text("stopped mid-review by Ctrl-C")
        # cli._review_fn also returns normally after TurnStopped/end_stopped.

    def interrupt(attempts: Sequence[Any], timeout: float) -> None:
        nonlocal interrupted
        running.extend(attempts)
        interrupted = True
        raise KeyboardInterrupt

    out = tmp_path / "run"
    with pytest.raises(KeyboardInterrupt):
        runner.run_benchmark(
            preflighted, out, provider="fake", model="fict-model-a", effort="high",
            review_fn=body, jobs=2, clock=clock, wait_for_attempts=interrupt,
        )
    for item in running:
        item.worker.join(timeout=30)
        assert not item.worker.is_alive(), "stopped review did not publish its result"
    for package_id, item in zip(ids, running, strict=True):
        row = driver_row(out, package_id)
        assert (row["kind"], row["class"]) == ("infrastructure", "interrupted")
        assert driver_status(out)["packages"][package_id]["kept_attempt"] is None
        assert not (out / package_id).exists()
        assert (out / row["folder"] / "cut-short.txt").is_file()
        # Even a poll after the handler returns must see the listener's interrupt.
        outcome = item.poll(0.0)
        assert (outcome.kind, outcome.class_) == ("infrastructure", "interrupted")


@pytest.mark.parametrize("finished_kind", ["completed", "behavioural"])
def test_a_callback_failure_preserves_the_failed_promotion_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, finished_kind: str,
) -> None:
    preflighted = prepare_driver_set(tmp_path, IDS[:2])

    def body(package: Path, folder: Path, **options: Any) -> None:
        if finished_kind == "behavioural":
            failure = ProviderError("fict safety stop")
            failure.stop_reason = "SAFETY"
            raise failure

    reviews = HeldReviews(IDS[:2], 2, delegate=body)
    out = tmp_path / "run"
    original_rename = Path.rename
    failure = OSError("fict completion output closed")

    def rename(path: Path, target: Any) -> Path:
        if path == out / "attempts/fict-a/1":
            raise OSError("fict folder locked")
        return original_rename(path, target)

    def done(**row: Any) -> None:
        assert row["promotion_error"] == "fict folder locked"
        raise failure

    reviews.install(monkeypatch)
    monkeypatch.setattr(Path, "rename", rename)
    try:
        with pytest.raises(OSError) as raised:
            runner.run_benchmark(
                preflighted, out, provider="fake", model="fict-model-a", effort="high",
                review_fn=reviews.body, jobs=2, clock=reviews,
                wait_for_attempts=reviews.wait, on_package_done=done,
            )
        assert raised.value is failure
        row = driver_row(out, "fict-a")
        expected = (
            "fict safety stop; promotion failed: fict folder locked"
            if finished_kind == "behavioural" else "promotion failed: fict folder locked"
        )
        assert row["message"] == expected
        assert row["kind"] == finished_kind
        assert row["folder"] == "attempts/fict-a/1"
        assert driver_status(out)["packages"]["fict-a"]["kept_attempt"] == 1
        assert driver_row(out, "fict-b")["class"] == "interrupted"
    finally:
        reviews.close()


def test_jobs_below_one_is_a_usage_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    built = install_driver_providers(monkeypatch, [[ScriptedTurn(text="Unreached.")]])
    out = tmp_path / "run"
    result = command(tmp_path, out, "--jobs", "0")
    assert result.exit_code == 2, result.stdout + result.stderr
    diagnostic = result.stdout + result.stderr
    assert "--jobs" in diagnostic
    assert "No such option" not in diagnostic
    assert "1" in diagnostic and ("range" in diagnostic or "at least" in diagnostic)
    assert built == []
    assert not out.exists()


def test_resume_runs_at_the_recorded_jobs_and_takes_no_jobs_option(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_driver_set(tmp_path, IDS)
    real_review = cli._review_fn
    failures = {
        package_id: [ScriptedTurn(text="", fails=TransientError("fict request failed"))]
        for package_id in ("fict-a", "fict-c")
    }
    for old_record in (False, True):
        install_driver_providers(monkeypatch, [[ScriptedTurn(text="Preflight adapter.")]])
        first_reviews = HeldReviews(IDS, 3, delegate=scripted_body(failures))
        out = tmp_path / f"run-{old_record}"
        with controlled(monkeypatch, first_reviews):
            first = command(tmp_path, out, "--jobs", "3")
        assert first.exit_code == 1, first.stdout + first.stderr
        assert first.stderr.splitlines() == [
            "error: infrastructure failures: fict-a, fict-c; "
            f"run swreview benchmark resume {out}",
        ]
        assert first_reviews.started == list(IDS)
        assert first_reviews.maximum == 3
        assert runner.load_provenance(out).jobs == 3
        if old_record:
            path = out / runner.PROVENANCE_FILE
            record = json.loads(path.read_bytes())
            record.pop("jobs")
            path.write_bytes((json.dumps(record, indent=2) + "\n").encode())
            assert runner.load_provenance(out).jobs is None
        else:
            rewrite_record(out, jobs=3)

        before = snapshot(out)
        refused = CliRunner().invoke(cli.app, ["benchmark", "resume", str(out), "--jobs", "1"])
        assert refused.exit_code == 2
        assert "resume runs at the run's recorded --jobs" in refused.stdout + refused.stderr
        assert snapshot(out) == before

        failed_ids = ("fict-a", "fict-c")
        reviews = HeldReviews(failed_ids, 1 if old_record else 3, delegate=real_review)
        install_driver_providers(monkeypatch, [[ScriptedTurn(text="Fresh review.")]] * 2)
        kept = snapshot(out / "fict-b")
        with controlled(monkeypatch, reviews):
            result = CliRunner().invoke(cli.app, ["benchmark", "resume", str(out)])
        assert result.exit_code == 0, result.stdout + result.stderr
        assert reviews.started == list(failed_ids)
        assert reviews.maximum == (1 if old_record else 2)
        assert reviews.maximum <= (1 if old_record else 3)
        assert snapshot(out / "fict-b") == kept
        assert all(driver_row(out, package_id)["attempt"] == 2 for package_id in failed_ids)
        assert all(driver_row(out, package_id)["resumed"] is True for package_id in failed_ids)


@pytest.mark.parametrize("resumed", [False, True], ids=["run", "resume"])
def test_concurrent_attempts_keep_the_run_log_redactor_through_interleaved_removals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
    resumed: bool,
) -> None:
    """Force the probe's stale factory read while A exits and B enters redaction."""
    import logging

    from swreview.agent.settings import LogRecordRedactor

    ids = IDS[:2]
    prepare_driver_set(tmp_path, ids)
    key = "sk-fict-0123456789abcdef0123456789abcdef"
    monkeypatch.setenv("OPENAI_API_KEY", key)
    real_review = cli._review_fn
    out = tmp_path / "run"
    if resumed:
        install_driver_providers(monkeypatch, [
            [ScriptedTurn(text="", fails=TransientError("fict unavailable"))],
            [ScriptedTurn(text="", fails=TransientError("fict unavailable"))],
        ])
        reviews = HeldReviews(ids, 2, delegate=real_review)
        with controlled(monkeypatch, reviews):
            first = command(tmp_path, out, "--jobs", "2", provider="openai")
        assert first.exit_code == 1, first.stdout + first.stderr

    install_driver_providers(monkeypatch, [[ScriptedTurn(text="Reviewed.")]] * 2)
    package_thread = threading.local()
    barrier = threading.Barrier(2)
    a_installed, b_read, a_removed, a_done = (threading.Event() for _ in range(4))
    original_factory = logging.getLogRecordFactory()
    real_install, real_remove = LogRecordRedactor.install, LogRecordRedactor.remove
    installed_by: list[str | None] = []

    def install(redactor: LogRecordRedactor) -> None:
        package_id = getattr(package_thread, "package_id", None)
        installed_by.append(package_id)
        if package_id == "fict-b":
            assert a_installed.wait(timeout=30), "A never installed its redactor"
            # The old install's get/set pair, paused exactly where the probe pauses it.
            redactor._previous = logging.getLogRecordFactory()
            b_read.set()
            assert a_removed.wait(timeout=30), "A never removed its redactor"
            logging.setLogRecordFactory(redactor)
        else:
            real_install(redactor)
            if package_id == "fict-a":
                a_installed.set()
                assert b_read.wait(timeout=30), "B never read A's redactor"

    def remove(redactor: LogRecordRedactor) -> None:
        real_remove(redactor)
        if getattr(package_thread, "package_id", None) == "fict-a":
            a_removed.set()

    def review(package: Path, folder: Path, **options: Any) -> Any:
        package_thread.package_id = package.name
        barrier.wait(timeout=30)
        try:
            result = real_review(package, folder, **options)
            if package.name == "fict-b":
                assert a_done.wait(timeout=30), "A never finished its attempt"
                logging.getLogger("fict.benchmark.jobs.redactor").warning(
                    "Authorization: Bearer %s", key,
                )
            return result
        finally:
            if package.name == "fict-a":
                a_done.set()

    def wrap(real: Callable[..., Any]) -> Callable[..., Any]:
        def invoke(*args: Any, **options: Any) -> Any:
            def wait(running: Sequence[Any], timeout: float) -> None:
                for item in running:
                    item.worker.join(timeout=30)
                    assert not item.worker.is_alive(), "attempt did not finish"

            return real(*args, clock=lambda: 0.0, wait_for_attempts=wait, **options)

        return invoke

    monkeypatch.setattr(LogRecordRedactor, "install", install)
    monkeypatch.setattr(LogRecordRedactor, "remove", remove)
    monkeypatch.setattr(cli, "_review_fn", review)
    monkeypatch.setattr(cli, "run_benchmark", wrap(cli.run_benchmark))
    monkeypatch.setattr(cli, "resume_benchmark", wrap(cli.resume_benchmark))
    try:
        result = (
            CliRunner().invoke(cli.app, ["benchmark", "resume", str(out)])
            if resumed else command(tmp_path, out, "--jobs", "2", provider="openai")
        )
        assert result.exit_code == 0, result.stdout + result.stderr
        messages = [record.getMessage() for record in caplog.records
                    if record.name == "fict.benchmark.jobs.redactor"]
        assert messages == ["Authorization: Bearer [redacted]"]
        assert key not in caplog.text
        assert installed_by == [None], "only the command owns process-wide redaction"
    finally:
        logging.setLogRecordFactory(original_factory)


def test_default_library_review_still_redacts_logs_without_a_command_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    import logging

    from swreview.agent.settings import LogRecordRedactor

    preflighted = prepare_driver_set(tmp_path, IDS[:1])
    key = "sk-fict-library-0123456789abcdef0123456789abcdef"
    monkeypatch.setenv("OPENAI_API_KEY", key)
    installed: list[LogRecordRedactor] = []
    real_install = LogRecordRedactor.install

    def install(redactor: LogRecordRedactor) -> None:
        installed.append(redactor)
        real_install(redactor)

    class LoggingProvider(FakeProvider):
        def run(self, **options: Any) -> Any:
            logging.getLogger("fict.benchmark.library.redactor").warning(
                "Authorization: Bearer %s", key,
            )
            return super().run(**options)

    install_driver_providers(
        monkeypatch, [[ScriptedTurn(text="Reviewed.")]], kind=LoggingProvider,
    )
    monkeypatch.setattr(LogRecordRedactor, "install", install)
    before = logging.getLogRecordFactory()
    out = tmp_path / "run"
    assert runner.run_benchmark(
        preflighted, out, provider="openai", model="fict-model-a", effort="high",
        clock=lambda: 0.0,
    ) == [out / "fict-a"]
    assert len(installed) == 1
    assert logging.getLogRecordFactory() is before
    messages = [record.getMessage() for record in caplog.records
                if record.name == "fict.benchmark.library.redactor"]
    assert messages == ["Authorization: Bearer [redacted]"]
    assert key not in caplog.text


def test_log_redactor_install_and_remove_serialize_the_factory_read_and_restore(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    """Real factory methods cannot restore A between B's factory read and install."""
    import logging

    from swreview.agent import settings

    key = "sk-fict-factory-0123456789abcdef0123456789abcdef"
    before = logging.getLogRecordFactory()
    run_level = settings.configure_logging_redaction([key])
    a = settings.configure_logging_redaction([key])
    b = settings.LogRecordRedactor([key])
    original_get, original_set = logging.getLogRecordFactory, logging.setLogRecordFactory
    b_read, release_b, remove_checkpoint = (threading.Event() for _ in range(3))
    operation = threading.local()
    failures: list[BaseException] = []
    actual_lock = threading.Lock()
    acquired: list[str] = []

    class ObservedLock:
        def __enter__(self) -> None:
            name = getattr(operation, "name", "main")
            if name == "remove-a":
                # A has reached the lock; it must wait until B's install is complete.
                remove_checkpoint.set()
            actual_lock.acquire()
            acquired.append(name)

        def __exit__(self, *args: Any) -> None:
            actual_lock.release()

    def get_factory() -> Any:
        previous = original_get()
        if getattr(operation, "name", None) == "install-b":
            b_read.set()
            assert release_b.wait(timeout=30), "B's factory read was never released"
        return previous

    def set_factory(factory: Any) -> None:
        original_set(factory)
        if getattr(operation, "name", None) == "remove-a":
            # Baseline has no lock and reaches the old restore while B is paused.
            remove_checkpoint.set()

    def change(name: str, action: Callable[[], None]) -> None:
        operation.name = name
        try:
            action()
        except BaseException as error:
            failures.append(error)

    monkeypatch.setattr(settings, "_LOG_REDACTOR_LOCK", ObservedLock(), raising=False)
    monkeypatch.setattr(logging, "getLogRecordFactory", get_factory)
    monkeypatch.setattr(logging, "setLogRecordFactory", set_factory)
    installer = threading.Thread(target=change, args=("install-b", b.install), daemon=True)
    remover = threading.Thread(target=change, args=("remove-a", a.remove), daemon=True)
    try:
        installer.start()
        assert b_read.wait(timeout=30), "B never read the record factory"
        remover.start()
        try:
            assert remove_checkpoint.wait(timeout=30), "A never attempted removal"
        finally:
            release_b.set()
        installer.join(timeout=30)
        remover.join(timeout=30)
        assert not installer.is_alive() and not remover.is_alive()
        assert failures == []
        b.remove()
        logging.getLogger("fict.benchmark.factory.redactor").warning(
            "Authorization: Bearer %s", key,
        )
        messages = [record.getMessage() for record in caplog.records
                    if record.name == "fict.benchmark.factory.redactor"]
        assert messages == ["Authorization: Bearer [redacted]"]
        assert key not in caplog.text
        assert acquired[:2] == ["install-b", "remove-a"]
    finally:
        release_b.set()
        run_level.remove()
        original_set(before)


def test_default_library_resume_reuses_its_run_log_redactor_for_concurrent_attempts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    import logging

    from swreview.agent.settings import LogRecordRedactor

    ids = IDS[:2]
    prepare_driver_set(tmp_path, ids)
    key = "sk-fict-resume-0123456789abcdef0123456789abcdef"
    monkeypatch.setenv("OPENAI_API_KEY", key)
    install_driver_providers(monkeypatch, [
        [ScriptedTurn(text="", fails=TransientError("fict unavailable"))],
        [ScriptedTurn(text="", fails=TransientError("fict unavailable"))],
    ])
    reviews = HeldReviews(ids, 2, delegate=cli._review_fn)
    out = tmp_path / "run"
    with controlled(monkeypatch, reviews):
        first = command(tmp_path, out, "--jobs", "2", provider="openai")
    assert first.exit_code == 1, first.stdout + first.stderr
    installed: list[LogRecordRedactor] = []
    real_install = LogRecordRedactor.install
    both_running = threading.Barrier(2)

    def install(redactor: LogRecordRedactor) -> None:
        installed.append(redactor)
        real_install(redactor)

    class LoggingProvider(FakeProvider):
        def run(self, **options: Any) -> Any:
            both_running.wait(timeout=30)
            logging.getLogger("fict.benchmark.library.resume.redactor").warning(
                "Authorization: Bearer %s", key,
            )
            return super().run(**options)

    def wait(running: Sequence[Any], timeout: float) -> None:
        for item in running:
            item.worker.join(timeout=30)
            assert not item.worker.is_alive(), "resumed attempt did not finish"

    install_driver_providers(
        monkeypatch, [[ScriptedTurn(text="Reviewed.")]] * 2, kind=LoggingProvider,
    )
    monkeypatch.setattr(LogRecordRedactor, "install", install)
    before = logging.getLogRecordFactory()
    try:
        assert runner.resume_benchmark(
            out, clock=lambda: 0.0, wait_for_attempts=wait,
        ) == [out / package_id for package_id in ids]
        messages = [record.getMessage() for record in caplog.records
                    if record.name == "fict.benchmark.library.resume.redactor"]
        assert messages == ["Authorization: Bearer [redacted]"] * 2
        assert key not in caplog.text
        assert len(installed) == 1
        assert logging.getLogRecordFactory() is before
    finally:
        logging.setLogRecordFactory(before)
