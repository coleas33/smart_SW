"""The record of what a benchmark attempt sent (feature 014 T161; `contracts/benchmark-run.md` 12).

`prompts.json` in a benchmark package folder holds the system prompt and every user message the
attempt sent, as the provider received them (FR-057, D11; plan decisions INT-1, RUN-12). Every
review here is scripted and offline. `cli._review_fn` is called as `run_benchmark` calls it, with
an `AttemptRequest`, and `cli.provider_factory` is patched, as `test_cli.py`'s `fake_provider`
patches it, to return a scripted provider that keeps, for each turn, the system prompt and the
history it was sent.

- `test_the_system_prompt_and_opening_message_are_recorded_as_sent`: written before the first
  turn, and again when the review ends, through the one atomic writer.
- `test_every_answer_turn_message_is_recorded_byte_for_byte`: each answer turn's message as
  composed by code, the regrade line below the answers and a drawing read's outcome lines above
  them.
- `test_a_turn_that_raises_still_leaves_its_record`: the `finally` write.
- `test_the_pane_writes_no_prompts_record`: only a benchmark attempt writes it.
- `test_86a_*` (owner decision 86A): when the review itself failed, a failed second write is a
  note on that failure, which stays the one raised; otherwise it is raised.

`test_an_abandoned_attempt_still_records_its_opening` is the robustness slice's (T195): it needs
the attempt's worker.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

import pytest
from starlette.testclient import TestClient

import swreview.chat.server as chat_server
from swreview import atomic, cli
from swreview.agent.providers import AgentEvent, TurnResult
from swreview.agent.providers.fake import FakeProvider, ScriptedTurn
from swreview.agent.providers.openai_provider import OpenAIProviderError
from swreview.agent.runner import (
    REGRADED_LINE,
    ReviewRun,
    answers_message,
    run_review,
    start_review,
)
from swreview.agent.settings import MODEL_VIEW_OFF, EfficiencySettings, ProviderSettings
from swreview.benchmark import report_page
from swreview.benchmark.case_file import CaseFile
from swreview.benchmark.report_page import PROMPTS_FILE
from swreview.benchmark.runner import AttemptRequest
from swreview.checks.drawing_context import CANDIDATE_CONFIRM
from swreview.ir.loader import save_package
from tests.support import roles_review
from tests.support.drawings import DrawingBuilder
from tests.support.mechanical import PackageBuilder
from tests.support.packages import build_package
from tests.support.scripted_answers import FIT, SpyProvider, ask, turn
from tests.unit import test_answer_batch_roles as roles_batch
from tests.unit.test_benchmark_answers_roles import (
    ALL_BOUGHT,
    FIT_ANSWER,
    PIN_1,
    PLATE_1,
    roles_case,
)
from tests.unit.test_chat_server import MODEL, ORIGIN, TOKEN, ProviderControl, settle, start_session
from tests.unit.test_confirmed_drawing_read import FakeHost, merged

scripted_registry = roles_batch.scripted_registry

SOURCE = Path(chat_server.__file__).resolve().parents[1]


class PromptsProvider(SpyProvider):
    """The scripted provider `_review_fn` is handed: it keeps the system prompt and history each
    turn was sent, and, at its first turn, the bytes of `prompts.json` already in `folder`."""

    def __init__(self, folder: Path, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.folder = folder
        self.systems: list[str] = []
        self.at_first_turn: bytes | None = None

    def run(self, **kwargs: Any) -> TurnResult:
        if not self.systems:
            self.at_first_turn = (self.folder / PROMPTS_FILE).read_bytes()
        self.systems.append(kwargs["system"])
        return super().run(**kwargs)

    def user_messages(self) -> list[str]:
        """Each turn's opening user message, as the turn received it."""
        return [self.user_message(index) for index in range(len(self.sent))]


class RaisingProvider(PromptsProvider):
    """Raises on its opening turn, after keeping what it was sent."""

    def run(self, **kwargs: Any) -> TurnResult:
        self.systems.append(kwargs["system"])
        self.sent.append([dict(message) for message in kwargs["messages"]])
        raise RuntimeError("a fictional provider outage")


def install(
    monkeypatch: pytest.MonkeyPatch,
    folder: Path,
    *turns: ScriptedTurn,
    kind: type[PromptsProvider] = PromptsProvider,
) -> list[PromptsProvider]:
    """Patch `cli.provider_factory` to build one scripted `kind` per adapter asked for."""
    built: list[PromptsProvider] = []

    def factory(
        settings: ProviderSettings, efficiency: EfficiencySettings | None = None
    ) -> PromptsProvider:
        provider = kind(folder, script=list(turns), model=settings.model)
        built.append(provider)
        return provider

    monkeypatch.setattr(cli, "provider_factory", factory)
    return built


def attempt(case_file: CaseFile | None = None, profile: Path | None = None) -> AttemptRequest:
    return AttemptRequest(
        model_view=MODEL_VIEW_OFF,
        standards_profile=profile,
        case_file=case_file,
        max_answer_turns=3,
    )


def review(package_dir: Path, out: Path, request: AttemptRequest) -> Any:
    """`_review_fn` as `run_benchmark` calls it."""
    return cli._review_fn(
        package_dir, out, provider="fake", model="fake-1", effort="high", attempt=request
    )


def recorded(folder: Path) -> dict[str, Any]:
    """`prompts.json` as written: UTF-8, `\\n` line endings and a final newline."""
    data = (folder / PROMPTS_FILE).read_bytes()
    assert data.endswith(b"\n")
    assert b"\r" not in data
    return json.loads(data.decode("utf-8"))


def test_the_system_prompt_and_opening_message_are_recorded_as_sent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package_dir = tmp_path / "package"
    save_package(build_package(), package_dir)
    out = tmp_path / "run" / "pkg-1"
    built = install(monkeypatch, out, ScriptedTurn(text="Reviewed."))
    writes: list[Path] = []
    real = atomic.write_atomic

    def spy(path: Path, data: bytes) -> None:
        writes.append(Path(path))
        real(path, data)

    monkeypatch.setattr(atomic, "write_atomic", spy)

    review(package_dir, out, attempt())

    [provider] = built
    [system] = provider.systems
    opening = provider.user_message(0)
    assert provider.at_first_turn is not None
    at_first = json.loads(provider.at_first_turn.decode("utf-8"))
    assert at_first == {"prompts_version": 1, "system": system, "user_messages": [opening]}
    assert recorded(out) == {"prompts_version": 1, "system": system, "user_messages": [opening]}
    assert [path for path in writes if path.name == PROMPTS_FILE] == [out / PROMPTS_FILE] * 2


def test_every_answer_turn_message_is_recorded_byte_for_byte(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scripted_registry: None
) -> None:
    """(a) Through `_review_fn`: "All bought" at the first answer point, the model's fit question
    at the second; message 1 carries the regrade line below the answers."""
    profile = roles_review.write_profile(tmp_path)
    package_dir = roles_review.write_package(tmp_path / "packages" / "fict-roles")
    case = roles_case(tmp_path, package_dir, profile, ALL_BOUGHT, FIT_ANSWER)
    out = tmp_path / "run" / "fict-roles"
    built = install(
        monkeypatch,
        out,
        roles_batch.first_turn("check_rms_part", "check_hygiene"),
        turn(ask(PLATE_1, PIN_1, item=FIT), text="One more question."),
        turn(text="Noted."),
    )

    review(package_dir, out, attempt(case, profile))

    [provider] = built

    sent = provider.user_messages()
    assert len(sent) == 3
    record = recorded(out)
    assert record["system"] == provider.systems[0]
    assert record["user_messages"] == sent
    withdrawn = [
        AgentEvent.model_validate_json(line).body["finding_id"]
        for line in (out / "events.jsonl").read_text(encoding="utf-8").splitlines()
        if AgentEvent.model_validate_json(line).type == "finding.withdrawn"
    ]
    assert withdrawn
    assert record["user_messages"][1] == (
        answers_message([("ER-001", "All bought")])
        + "\n"
        + REGRADED_LINE.format(ids=", ".join(withdrawn))
    )


def test_every_answer_turn_message_is_recorded_byte_for_byte_with_a_drawing_read(
    tmp_path: Path, scripted_registry: None
) -> None:
    """(b) A benchmark attempt passes `bridge=False`, so no confirmed-candidate question arises in
    one (`test_confirmed_drawing_read.py`); the writer is called over a review driven as
    `test_answer_batch_roles.py`'s batch test drives one (a confirmed read, then the regrade, in
    one batch), and message 1 is the resumed message byte for byte: the outcome lines above the
    answers and the regrade line below them."""
    builder = PackageBuilder(design_stem=roles_review.ROOT_STEM, schema_version="1.6.0")
    plate = builder.document(roles_review.PLATE_STEM, "part")
    builder.component(plate)
    pin = builder.document(roles_review.PIN_STEM, "part")
    builder.component(pin)
    drawings = DrawingBuilder(builder.build().package)
    drawings.candidate(plate)
    folder = tmp_path / "run-0001"
    save_package(drawings.build(), folder)
    host = FakeHost(folder, {plate: merged(folder, plate)})
    provider = SpyProvider(
        script=[
            roles_batch.first_turn("check_drawings", "check_rms_part", "check_hygiene"),
            ScriptedTurn(text="resumed"),
        ],
        model="fake-scripted",
    )
    run = start_review(
        folder,
        folder,
        provider=provider,
        standards_profile=roles_review.write_profile(tmp_path),
        bridge=True,
        bridge_factory=lambda pipe, secret: host,
    )
    try:
        run.start()
        [candidate] = [
            item for item in run.session.evidence_requests if CANDIDATE_CONFIRM in item.options
        ]
        answers = [("ER-001", "All bought"), (candidate.id, CANDIDATE_CONFIRM)]
        run.answer_evidence_batch(answers)
    finally:
        run.close()

    report_page.write_prompts_record(run, folder)

    record = recorded(folder)
    resumed = provider.user_message(1)
    assert record["user_messages"] == [provider.user_message(0), resumed]
    outcomes, below = resumed.split("\n\n", 1)
    assert outcomes
    assert below.startswith(answers_message(answers) + "\n")
    assert below.splitlines()[-1].startswith(REGRADED_LINE.split("{", 1)[0])


def test_a_turn_that_raises_still_leaves_its_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package_dir = tmp_path / "package"
    save_package(build_package(), package_dir)
    out = tmp_path / "run" / "pkg-1"
    built = install(monkeypatch, out, kind=RaisingProvider)

    with pytest.raises(RuntimeError, match="^a fictional provider outage$"):
        review(package_dir, out, attempt())

    [provider] = built

    assert recorded(out) == {
        "prompts_version": 1,
        "system": provider.systems[0],
        "user_messages": [provider.user_message(0)],
    }


def _names_the_record(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return [
        f"{path.relative_to(SOURCE).as_posix()} line {node.lineno}"
        for node in ast.walk(tree)
        if (isinstance(node, ast.Name) and node.id == "PROMPTS_FILE")
        or (isinstance(node, ast.Attribute) and node.attr == "PROMPTS_FILE")
        or (isinstance(node, ast.alias) and node.name == "PROMPTS_FILE")
        or (isinstance(node, ast.Constant) and node.value == PROMPTS_FILE)
    ]


def test_the_pane_writes_no_prompts_record(tmp_path: Path) -> None:
    """INT-1: the `review` command's path and a pane review leave no record in their folders,
    and no module of the product's review, chat server or tools names it."""
    review_package = tmp_path / "review-package"
    save_package(build_package(), review_package)
    review_out = tmp_path / "review-out"
    run_review(
        review_package,
        review_out,
        provider=FakeProvider(script=[ScriptedTurn(text="Reviewed.")], model="fake-scripted"),
    )
    assert (review_out / "session.json").is_file()
    assert not (review_out / PROMPTS_FILE).exists()

    run_root = tmp_path / "pane-runs"
    pane_run = run_root / "20261014-120000-cover"
    save_package(build_package(), pane_run)
    app = chat_server.create_app(
        token=TOKEN,
        allow_origin=ORIGIN,
        run_root=run_root,
        provider_factory=ProviderControl().factory,
        list_models=lambda _: [],
    )
    headers = {"Authorization": f"Bearer {TOKEN}", "Origin": ORIGIN}
    with TestClient(app, headers=headers) as client:
        chat = start_session(client, pane_run, model=MODEL)
        settle(client, chat["chat_id"])
    assert (pane_run / "session.json").is_file()
    assert not list(run_root.rglob(PROMPTS_FILE))

    offences = [
        offence
        for package in ("agent", "chat", "tools")
        for path in sorted((SOURCE / package).rglob("*.py"))
        for offence in _names_the_record(path)
    ]
    assert offences == []


# --- owner decision 86A: the second write never hides the review's own failure --------------


class ProviderErrorRaising(PromptsProvider):
    """Raises a provider's own error on its opening turn, after keeping what it was sent."""

    def run(self, **kwargs: Any) -> TurnResult:
        self.systems.append(kwargs["system"])
        self.sent.append([dict(message) for message in kwargs["messages"]])
        raise OpenAIProviderError(
            "a fictional rate limit", error_class="RateLimitError", retryable=True
        )


def _second_write_fails(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """`write_prompts_record` raises an `OSError` on its second call; `ReviewRun.close` is
    recorded. The returned list names each, in order."""
    calls: list[str] = []
    real_write, real_close = report_page.write_prompts_record, ReviewRun.close

    def write(run: Any, folder: Path) -> None:
        calls.append("write")
        if calls.count("write") == 2:
            raise OSError("a fictional full disk")
        real_write(run, folder)

    def close(self: ReviewRun) -> None:
        calls.append("close")
        real_close(self)

    monkeypatch.setattr(report_page, "write_prompts_record", write)
    monkeypatch.setattr(ReviewRun, "close", close)
    return calls


def test_86a_a_provider_error_is_raised_and_the_failed_rewrite_is_a_note_on_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package_dir = tmp_path / "package"
    save_package(build_package(), package_dir)
    install(monkeypatch, tmp_path / "out", kind=ProviderErrorRaising)
    calls = _second_write_fails(monkeypatch)

    with pytest.raises(OpenAIProviderError) as raised:
        review(package_dir, tmp_path / "out", attempt())

    assert str(raised.value) == "a fictional rate limit"
    assert calls == ["write", "write", "close"]
    assert raised.value.__notes__ == [
        "the prompts record could not be rewritten: OSError: a fictional full disk"
    ]


def test_86a_with_no_failure_in_flight_the_failed_rewrite_is_raised(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package_dir = tmp_path / "package"
    save_package(build_package(), package_dir)
    install(monkeypatch, tmp_path / "out", ScriptedTurn(text="Reviewed."))
    calls = _second_write_fails(monkeypatch)

    with pytest.raises(OSError, match="^a fictional full disk$"):
        review(package_dir, tmp_path / "out", attempt())

    assert calls == ["write", "write", "close"]


def test_92a_the_one_line_error_carries_the_failed_rewrite_s_note(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The command line prints a refusal as one line; 86A's note is on it, never lost."""
    package_dir = tmp_path / "package"
    save_package(build_package(), package_dir)
    install(monkeypatch, tmp_path / "out", kind=ProviderErrorRaising)
    _second_write_fails(monkeypatch)

    with pytest.raises(OpenAIProviderError) as raised:
        review(package_dir, tmp_path / "out", attempt())

    assert cli._one_line(raised.value) == (
        "OpenAIProviderError: a fictional rate limit; the prompts record could not be rewritten: "
        "OSError: a fictional full disk"
    )


def test_92a_a_note_survives_a_message_cut_to_one_line_s_length() -> None:
    error = ValueError("x" * (cli.MESSAGE_LENGTH + 50))
    error.add_note("the prompts record could not be rewritten: OSError: a fictional full disk")

    line = cli._one_line(error)

    assert line.endswith(
        "…; the prompts record could not be rewritten: OSError: a fictional full disk"
    )
