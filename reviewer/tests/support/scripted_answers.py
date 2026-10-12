"""A scripted model and a case file, for the answer driver's tests (feature 014 T098).

`contracts/scripted-answers.md` 7 and `questions.md` 9: each review is started with
`start_review(..., bridge=False)` over a fictional package and played by
`benchmark.answers.drive_review`, the scripted provider scripting exactly the turns a test
expects; a turn beyond its script is refused (`agent/providers/fake.py`), which is itself the
assertion that no answer turn was played.

- `SpyProvider`: the scripted provider, keeping the history each turn was sent, so a test reads
  the resumed user message as the model received it.
- `ask`, `turn` and `scripted`: a `request_evidence` call in the tool's own arguments, a
  scripted turn, and the model playing exactly the turns given.
- `case_file`: a case file written to disk and read back through `load_case_file`, the one reader
  `preflight_set` uses, so every case file a test drives with is one a run would accept.
- `drive`: one review started, driven and closed, with the events its stream carried.

Every package, id and answer is fictional.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from swreview.agent.checklist import load_checklist
from swreview.agent.providers import AgentEvent, TurnResult
from swreview.agent.providers.fake import FakeProvider, ScriptedToolCall, ScriptedTurn
from swreview.agent.runner import ReviewRun, start_review
from swreview.benchmark.answers import AnswerLog, drive_review, load_case_file
from swreview.benchmark.case_file import CASE_FILE_VERSION, CaseFile
from swreview.benchmark.sets import BenchmarkPackageRef
from swreview.checks.standards.profile import StandardsProfile
from swreview.ir.models import EvidencePackage

MODEL = "fake-scripted"
FIT = "interfaces.fit"
FASTENERS = "fasteners"


class SpyProvider(FakeProvider):
    """The scripted provider, keeping a copy of the history each turn was sent."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.sent: list[list[dict[str, Any]]] = []

    def run(self, **kwargs: Any) -> TurnResult:
        self.sent.append([dict(message) for message in kwargs["messages"]])
        return super().run(**kwargs)

    def user_message(self, turn: int) -> str:
        """The user message turn `turn` opened on (0 is the opening turn)."""
        last = self.sent[turn][-1]
        assert last["role"] == "user", last
        return str(last["content"])


def ask(*entity_ids: str, item: str | None = None, **fields: Any) -> ScriptedToolCall:
    """A `request_evidence` call naming `entity_ids`, blocking `item` when one is given, with
    `fields` (`question`, `options`) added."""
    arguments: dict[str, Any] = {
        "what": "A fictional value the review needs.",
        "why": "A check cannot be graded without it.",
        "entity_ids": list(entity_ids),
        **fields,
    }
    if item is not None:
        arguments["blocks"] = item
    return ScriptedToolCall("request_evidence", arguments)


def turn(*calls: ScriptedToolCall, text: str = "Reviewed.", **fields: Any) -> ScriptedTurn:
    """One scripted turn: `calls` in order, then `text`."""
    return ScriptedTurn(text=text, tool_calls=calls, **fields)


def scripted(*turns: ScriptedTurn) -> SpyProvider:
    """The scripted model playing exactly `turns`."""
    return SpyProvider(script=list(turns), model=MODEL)


def case_file(
    folder: Path,
    package_id: str,
    *entries: dict[str, Any],
    package: EvidencePackage,
    profile: StandardsProfile | None = None,
) -> CaseFile:
    """`<folder>/<package_id>.json` holding `entries`, read back through `load_case_file` against
    `package` and `profile`, as `preflight_set` reads a set's case files before the first review."""
    path = folder / f"{package_id}.json"
    folder.mkdir(parents=True, exist_ok=True)
    payload = {
        "case_file_version": CASE_FILE_VERSION,
        "package_id": package_id,
        "answers": list(entries),
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return load_case_file(
        path,
        entry=BenchmarkPackageRef(package_id=package_id, path=Path("packages") / package_id),
        package=package,
        checklist=load_checklist(),
        profile=profile,
    )


@dataclass
class Driven:
    """A review `drive` played: the run, the scripted model, the log and the stream."""

    run: ReviewRun
    provider: SpyProvider
    log: AnswerLog
    events: list[AgentEvent] = field(default_factory=list)

    def answered(self) -> list[dict[str, Any]]:
        """The `evidence.answered` bodies, in stream order."""
        return [event.body for event in self.events if event.type == "evidence.answered"]


def drive(
    package_dir: Path,
    out_dir: Path,
    provider: SpyProvider,
    case: CaseFile | None,
    *,
    max_answer_turns: int = 3,
    **options: Any,
) -> Driven:
    """Review `package_dir` into `out_dir` with `start_review(..., bridge=False)` and `provider`,
    play it through `drive_review` with `case` and the bound, and close it. `options` are
    `start_review`'s. A driver that raises propagates, the run closed first."""
    events: list[AgentEvent] = []
    run = start_review(
        package_dir,
        out_dir,
        provider=provider,
        bridge=False,
        callbacks=[events.append],
        **options,
    )
    try:
        log = drive_review(run, case, max_answer_turns=max_answer_turns)
    finally:
        run.close()
    return Driven(run=run, provider=provider, log=log, events=events)
