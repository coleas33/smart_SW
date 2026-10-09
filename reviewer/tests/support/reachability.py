"""The validation of every committed case (feature 014 `contracts/cases.md` 7; FR-054; CS-17,
RF-38; SC-014).

The one implementation of `cases.md` 7's legs, which the reachability test over the committed
set and its catches test (`test_benchmark_validation_catches.py`) both call. It lives here, not
under `tests/benchmark_cases/`, whose import rule (`generator.md` 9) it would break: it imports
the checks, the tools, the agent and the scorer, and reads the case specs for what never leaves
them, the correct calls and the decoys (`render.correct_calls` and `render.decoy_calls`, resolved
through `render.resolve`). It never writes a key.

**The reviews.** Each is the benchmark's own review function, `cli._review_fn`, over the package
folder with `config/standards.example.yaml`, explanations off and `max_answer_turns=0`, its
`cli.provider_factory` replaced, for that review only, by a `FakeProvider` playing one scripted
turn of the given calls and then an end; under one of two configurations, each as
`cli._review_settings` resolves it (FR-011, FR-015):

- **off**: every lever off, the pane study's off arm;
- **pane**: `--pane-defaults`.

Each review is scored with the real scorer, `scorecard._score_package`, against the key loaded
through `load_answer_key` with the package; a finding's origin is the score's `finding_origins`,
and model origin is `origins.MODEL_ORIGINS`.

**The legs**, in this order, each failure one line naming the leg, the configuration, the case and
the entry, a call written as `tool(arguments)` with its resolved ids, never a recorded string:

- **(a) code only**, under pane: the scripted turn calls every offered check with no required
  parameter that `prerun.planned_calls` did not plan (RF-38), read off the tools the review hands
  the model. It fails (1) a code-produced defect not detected (credited or flagged), or detected
  at a status mismatch; (2) a model-produced defect detected; (3) a demonstrated or suspected
  finding that matches no known defect and no forbidden entry; (4) a finding that contradicts a
  correct condition.
- **(b) correct reviewer**, under off and under pane: the scripted turn makes the spec's correct
  calls in order. It fails (1) a model-produced defect not credited or flagged, at a status
  mismatch, or flagged below expected; (2) a known defect cleared; (3) a model-origin false alarm,
  or a model-origin finding that contradicts a correct condition; (4) a correct condition that
  carries a correct call and is not confirmed.
- **decoys**, under off, for a case that has any: the scripted turn makes only the decoy calls,
  and fails a decoy's finding that credits, flags or clears a known defect.

A finding that contradicts a condition is named once, as the contradiction, never also as a
finding matching nothing. Leg (b) reads model-origin findings only, as its rule 3 says: a code
finding is leg (a)'s, so a package that is not clean is named once, by (a), whatever the pre-run
of (b, pane) writes.

**Cost** (`cases.md` 7): `REVIEWED` holds each case's failures for the session, keyed by what its
reviews read (the case, the package folder's bytes, the key's bytes, the correct and the decoy
calls), so a case is reviewed once whatever folder it is read from, and two specs rendering
differently never share a result.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal

import pytest

from swreview import cli, prerun
from swreview.agent import events
from swreview.agent.checklist import load_checklist
from swreview.agent.providers import (
    EffortLevel,
    EventCallback,
    ProviderName,
    ToolSet,
    TurnResult,
)
from swreview.agent.providers.fake import FakeProvider, ScriptedToolCall, ScriptedTurn
from swreview.agent.settings import DEFAULT_EFFORT, DEFAULT_MODELS
from swreview.benchmark import matching, scorecard
from swreview.benchmark.answer_key import load_answer_key
from swreview.benchmark.answer_key_model import REFERENCE_KEYED_CHECKS, AnswerKey, ReferenceKind
from swreview.benchmark.digest import sha256_of
from swreview.benchmark.origins import MODEL_ORIGINS
from swreview.benchmark.runner import EXAMPLE_PROFILE, AttemptRequest
from swreview.benchmark.scorecard import CREDITING_STATUSES, PackageScore
from swreview.benchmark.sets import REPO_ROOT
from swreview.findings import Finding
from swreview.ir.loader import load_package
from swreview.ir.models import EvidencePackage
from swreview.report.session import ReviewSession
from swreview.report.summary import Words, load_words
from swreview.tools import drawings
from swreview.tools.registry import ToolDispatch, check_tools, standards_tools
from tests.benchmark_cases import render
from tests.benchmark_cases.spec import CaseSpec, CaseSpecError, ToolCall, check_specs, twin

Configuration = Literal["off", "pane"]
CONFIGURATIONS: tuple[Configuration, ...] = ("off", "pane")
"""Leg (b)'s configurations, in the order its failures are listed."""

MODEL = DEFAULT_MODELS[ProviderName.FAKE]
"""The id the scripted provider reports."""

CLOSING_TEXT = "The scripted review ends here."
"""The scripted turn's closing text, after its calls."""

CHECK_TOOLS: frozenset[str] = frozenset(
    tool.__name__ for tool in (*check_tools(), drawings.check_drawings, *standards_tools())
)
"""Every check a review can offer, by name: `registry.check_tools()` and the two offered on
condition, `check_drawings` (drawing evidence) and `check_standards` (a standards run)."""

APART: dict[ReferenceKind, str] = {
    "joint": "joints",
    "recess": "recesses",
    "hole pair": "hole pairs",
    "joint instances": "joints",
    "fit": "fits",
    "stack": "stacks",
}
"""What a decoy's failure says the key's references do not tell apart, by the reference kind of
the defect's check (`REFERENCE_KEYED_CHECKS`)."""

DECOY_VERBS: Mapping[str, str] = {
    "demonstrated": "credits",
    "suspected": "credits",
    "unresolved": "flags",
    "checked_within_scope": "clears",
}
"""What a decoy's finding matching a known defect does to it, by the finding's status."""

REVIEWED: dict[tuple[str, ...], list[str]] = {}
"""Each case's failures, once per session, by what its reviews read (the module docstring)."""


# --- the scripted model ---------------------------------------------------------------------------


def _scripted(calls: Sequence[ToolCall]) -> FakeProvider:
    """A `FakeProvider` playing one turn of `calls`, then an end."""
    turn = ScriptedTurn(
        text=CLOSING_TEXT,
        tool_calls=tuple(ScriptedToolCall(call.tool, call.arguments) for call in calls),
    )
    return FakeProvider(script=(turn,), model=MODEL)


def code_only_calls(tools: ToolSet) -> tuple[ToolCall, ...]:
    """Leg (a)'s calls (RF-38): every check `tools` offers with no required parameter that
    `prerun.planned_calls` did not plan, in the dispatch's order, each with no argument.

    `tools` is what a pane review hands the model: the pre-run's guard around the dispatch,
    whose tools carry the review's context. The plan is asked of that context and dispatch, the
    ones the pre-run read, so a check offered, or planned, on a condition is decided as the
    review decided it."""
    if not isinstance(tools, prerun.PrerunGuard):
        raise ValueError("leg (a) runs under the pane defaults, whose pre-run guards the tools")
    dispatch: ToolDispatch = tools.tools
    context = dispatch.tools[0].context
    planned = {name for name, _ in prerun.planned_calls(context, dispatch)}
    return tuple(
        ToolCall(tool.name, {})
        for tool in dispatch
        if tool.name in CHECK_TOOLS
        and not tool.spec.schema["required"]
        and tool.name not in planned
    )


class CodeOnlyModel(FakeProvider):
    """Leg (a)'s scripted model. Its one turn is `code_only_calls` of the tools the review hands
    it, which exist only once the review has set up, so the turn is built when it is played: by a
    `FakeProvider` numbering its steps from where setup left them."""

    def __init__(self) -> None:
        super().__init__(script=(), model=MODEL)
        self._first_step = 0

    def start_steps_at(self, index: int) -> None:
        self._first_step = index

    def run(
        self,
        *,
        system: str,
        messages: Sequence[Mapping[str, Any]],
        tools: ToolSet,
        effort: EffortLevel,
        max_steps: int,
        on_event: EventCallback,
    ) -> TurnResult:
        player = _scripted(code_only_calls(tools))
        player.start_steps_at(self._first_step)
        return player.run(
            system=system,
            messages=messages,
            tools=tools,
            effort=effort,
            max_steps=max_steps,
            on_event=on_event,
        )


# --- one review -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Review:
    """One review as the legs read it: its folder, its session and its score."""

    folder: Path
    session: ReviewSession
    score: PackageScore


def _review(
    package_dir: Path,
    folder: Path,
    configuration: Configuration,
    model: FakeProvider,
    *,
    key: AnswerKey,
    package: EvidencePackage,
    words: Words,
) -> _Review:
    """`package_dir` reviewed into `folder` through `cli._review_fn` under `configuration`,
    `model` its provider, and scored against `key`."""
    resolved = cli._review_settings(
        ProviderName.FAKE,
        pane_defaults=configuration == "pane",
        lever=None,
        payload_slimming=False,
        history_pruning=False,
        prune_after=None,
        explain_findings=False,
    )
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(cli, "provider_factory", lambda settings, efficiency=None: model)
        session: ReviewSession = cli._review_fn(
            package_dir,
            folder,
            provider=ProviderName.FAKE.value,
            model=MODEL,
            effort=DEFAULT_EFFORT,
            efficiency=resolved.efficiency,
            explain_findings=resolved.explain_findings,
            attempt=AttemptRequest(
                model_view=resolved.model_view,
                standards_profile=REPO_ROOT / EXAMPLE_PROFILE,
                case_file=None,
                max_answer_turns=0,
            ),
        )
    score = scorecard._score_package(
        folder,
        package_id=key.package_id,
        held_out=key.holds_held_out(),
        answer_key=key,
        package=package,
        words=words,
    )
    return _Review(folder=folder, session=session, score=score)


# --- what a message says --------------------------------------------------------------------------


def _call_text(tool: str, arguments: Mapping[str, Any]) -> str:
    """A call as `tool(name=value, ...)`, each value as JSON, its ids resolved."""
    written = ", ".join(
        f"{name}={json.dumps(value, ensure_ascii=False)}" for name, value in arguments.items()
    )
    return f"{tool}({written})"


def _under(calls: Sequence[ToolCall]) -> str:
    """The calls a correct reviewer makes for one entry."""
    return "; ".join(_call_text(call.tool, call.arguments) for call in calls) or "no correct call"


def _documents(finding: Finding) -> str:
    """The documents a finding's provenance names."""
    return ", ".join(dict.fromkeys(entry.document_id for entry in finding.provenance))


def _apart(check: str) -> str:
    """Why a decoy's finding matched a known defect on `check`."""
    kind = REFERENCE_KEYED_CHECKS.get(check)
    if kind is None:
        return "the key's targets do not tell the decoy's from the planted defect's"
    return f"the key's references do not tell the {APART[kind]} apart"


# --- the legs -------------------------------------------------------------------------------------


def _contradictions(findings: Sequence[Finding], key: AnswerKey) -> list[tuple[Finding, str]]:
    """Each demonstrated or suspected finding matching a correct condition, with the condition's
    id, in key order, then session order (`scoring.md` 3.2)."""
    return [
        (finding, condition.id)
        for condition in key.correct_conditions
        for finding in findings
        if finding.status in CREDITING_STATUSES and matching.matches(finding, condition)
    ]


def _leg_a(case: str, key: AnswerKey, review: _Review) -> list[str]:
    """Leg (a)'s four rules over the code-only review."""
    score, findings = review.score, review.session.findings
    failures: list[str] = []
    detected = set(score.matched_defect_ids)
    for defect in key.known_defects:
        named = f"(a) {case} {defect.id} ({defect.check}, {defect.producer}-produced)"
        if defect.producer == "code" and defect.id not in detected:
            failures.append(f"{named} is not detected by code")
        elif defect.producer == "code" and defect.id in score.status_mismatch_defect_ids:
            failures.append(
                f"{named} is a status mismatch: code credits it while the key expects unresolved"
            )
        elif defect.producer == "model" and defect.id in detected:
            failures.append(
                f"{named} is detected by code-only calls: it is code-produced, or its seed "
                "withholds too little (16A)"
            )
    contradictions = _contradictions(findings, key)
    contradicting = {finding.id for finding, _ in contradictions}
    forbidden = set(score.forbidden_hit_finding_ids or ())
    by_id = {finding.id: finding for finding in findings}
    for finding_id in score.false_alarm_finding_ids:
        if finding_id in forbidden or finding_id in contradicting:
            continue
        finding = by_id[finding_id]
        failures.append(
            f"(a) {case} finding {finding.id} ({finding.check}, {finding.status}, "
            f"{_documents(finding)}) matches no known defect or forbidden entry: the package is "
            "not clean apart from its planted defects"
        )
    failures.extend(
        f"(a) {case} finding {finding.id} contradicts {condition}"
        for finding, condition in contradictions
    )
    return failures


def _leg_b(
    configuration: Configuration,
    case: str,
    key: AnswerKey,
    review: _Review,
    entry_calls: Mapping[str, Sequence[ToolCall]],
) -> list[str]:
    """Leg (b)'s four rules over the correct reviewer's review under `configuration`."""
    where = f"(b, {configuration}) {case}"
    score, findings = review.score, review.session.findings
    failures: list[str] = []
    for defect in key.known_defects:
        if defect.producer != "model":
            continue
        under = _under(entry_calls[defect.id])
        if defect.id in score.status_mismatch_defect_ids:
            failures.append(f"{where} {defect.id} is a status mismatch under {under}")
        elif defect.id in score.flagged_below_expected_defect_ids:
            failures.append(f"{where} {defect.id} is flagged below expected under {under}")
        elif defect.id not in score.matched_defect_ids:
            failures.append(f"{where} {defect.id} is not credited or flagged under {under}")
    for defect in key.known_defects:
        if defect.id in score.cleared_defect_ids:
            failures.extend(
                f"{where} {defect.id} is cleared by finding {finding.id}"
                for finding in findings
                if finding.status == "checked_within_scope" and matching.matches(finding, defect)
            )
    origins = score.finding_origins
    contradictions = [
        (finding, condition)
        for finding, condition in _contradictions(findings, key)
        if origins[finding.id] in MODEL_ORIGINS
    ]
    contradicting = {finding.id for finding, _ in contradictions}
    failures.extend(
        f"{where} finding {finding_id} is a model-origin false alarm"
        for finding_id in score.false_alarm_finding_ids
        if origins[finding_id] in MODEL_ORIGINS and finding_id not in contradicting
    )
    failures.extend(
        f"{where} finding {finding.id} contradicts {condition}"
        for finding, condition in contradictions
    )
    confirmed = set(score.confirmed_condition_ids or ())
    for condition in key.correct_conditions:
        calls = entry_calls[condition.id]
        if calls and condition.id not in confirmed:
            failures.append(f"{where} {condition.id} is not confirmed under {_under(calls)}")
    return failures


def _announced_in(folder: Path) -> dict[str, int]:
    """Each finding id and the step in flight when the review announced it: the last
    `tool.started` before its `finding` event, with no `tool.finished` between. Read off the
    event stream because a check that takes arguments writes findings citing no step
    (`scoring.md` 5.3, rule 5)."""
    in_flight: int | None = None
    announced: dict[str, int] = {}
    for event in events.replay_events(events.event_stream(folder)):
        if event.type == "tool.started":
            in_flight = event.body["step_index"]
        elif event.type == "tool.finished":
            in_flight = None
        elif event.type == "finding" and in_flight is not None:
            announced[event.body["id"]] = in_flight
    return announced


def _decoy_leg(case: str, key: AnswerKey, review: _Review) -> list[str]:
    """The decoys' rule: no decoy's finding matches a known defect, whatever its status."""
    announced = _announced_in(review.folder)
    steps = {step.index: step for step in review.session.steps}
    failures: list[str] = []
    for finding in review.session.findings:
        index = announced.get(finding.id)
        step = steps.get(index) if index is not None else None
        made_by = (
            _call_text(step.tool, step.arguments) if step is not None else f"finding {finding.id}"
        )
        failures.extend(
            f"(decoy) {case} {made_by} {DECOY_VERBS[finding.status]} {defect.id}: "
            f"{_apart(defect.check)}"
            for defect in key.known_defects
            if matching.matches(finding, defect)
        )
    return list(dict.fromkeys(failures))


# --- a case, a spec, a design ---------------------------------------------------------------------


def _entry_calls(spec: CaseSpec) -> dict[str, list[ToolCall]]:
    """Each seed's and each condition's own correct calls, resolved, by the id its key entry
    has (`D-<n>`, then `C-<n>`): `render.correct_calls` over the case holding that entry alone.
    A condition whose kind's call cannot confirm its clean form holds none (`generator.md` 4)."""
    calls = {
        f"D-{number}": render.correct_calls(replace(spec, seeds=(seed,), conditions=()))
        for number, seed in enumerate(spec.seeds, start=1)
    }
    calls.update(
        {
            f"C-{number}": render.correct_calls(replace(spec, seeds=(), conditions=(condition,)))
            for number, condition in enumerate(spec.conditions, start=1)
        }
    )
    return calls


def _folder_digest(folder: Path) -> str:
    """One digest of every file under `folder`, by its relative path and its bytes."""
    digest = hashlib.sha256()
    files = sorted(
        (path for path in folder.rglob("*") if path.is_file()),
        key=lambda path: path.relative_to(folder).as_posix(),
    )
    for path in files:
        content = path.read_bytes()
        digest.update(f"{path.relative_to(folder).as_posix()}\0{len(content)}\0".encode())
        digest.update(content)
    return digest.hexdigest()


def _calls_key(calls: Sequence[ToolCall]) -> str:
    return json.dumps(
        [[call.tool, call.arguments] for call in calls], ensure_ascii=False, sort_keys=True
    )


def _check(
    package_dir: Path,
    key_path: Path,
    spec: CaseSpec,
    correct: Sequence[ToolCall],
    decoys: Sequence[ToolCall],
) -> list[str]:
    """The four reviews of one case, into a temporary folder, and every leg's failures."""
    package = load_package(package_dir).package
    words = load_words()
    key = load_answer_key(key_path, package=package, checklist=load_checklist(), words=words)
    entry_calls = _entry_calls(spec)
    keyed = [defect.id for defect in key.known_defects]
    keyed.extend(condition.id for condition in key.correct_conditions)
    if keyed != list(entry_calls):
        raise ValueError(
            f"{key_path.name} keys {', '.join(keyed) or 'nothing'} where case spec "
            f"{spec.case_id} gives {', '.join(entry_calls) or 'nothing'}: regenerate the case"
        )
    case = spec.case_id
    # A review's files are closed when it ends; a cleanup Windows still refuses for a moment
    # must not fail a case that passed.
    with tempfile.TemporaryDirectory(prefix="reachability-", ignore_cleanup_errors=True) as out:
        folder = Path(out)

        def reviewed(name: str, configuration: Configuration, model: FakeProvider) -> _Review:
            return _review(
                package_dir,
                folder / name,
                configuration,
                model,
                key=key,
                package=package,
                words=words,
            )

        failures = _leg_a(case, key, reviewed("a-pane", "pane", CodeOnlyModel()))
        for configuration in CONFIGURATIONS:
            review = reviewed(f"b-{configuration}", configuration, _scripted(correct))
            failures.extend(_leg_b(configuration, case, key, review, entry_calls))
        if decoys:
            failures.extend(_decoy_leg(case, key, reviewed("decoys-off", "off", _scripted(decoys))))
    return failures


def check_case(package_dir: Path, key_path: Path, spec: CaseSpec) -> list[str]:
    """Every failure of `cases.md` 7's legs on the package at `package_dir` and the key at
    `key_path`, which `spec` wrote, the correct calls and the decoys read from `spec`: (a) under
    pane, (b) under off and under pane, then the decoys under off. `[]` when the case passes.
    Each case's reviews run once per session (`REVIEWED`)."""
    correct = render.correct_calls(spec)
    decoys = render.decoy_calls(spec)
    reviewed = (
        spec.case_id,
        _folder_digest(package_dir),
        sha256_of(key_path),
        _calls_key(correct),
        _calls_key(decoys),
    )
    if reviewed not in REVIEWED:
        REVIEWED[reviewed] = _check(package_dir, key_path, spec, correct, decoys)
    return list(REVIEWED[reviewed])


def check_spec(spec: CaseSpec) -> list[str]:
    """`check_case` on `spec`'s own package and key, rendered by `render.render_spec` into a
    temporary checkout. A twin is checked by its own `check_spec(twin(spec))`."""
    files = render.render_spec(spec)
    with tempfile.TemporaryDirectory(prefix="reachability-", ignore_cleanup_errors=True) as out:
        root = Path(out)
        for relative, content in files.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        return check_case(
            root / render.PACKAGES / spec.case_id,
            root / render.ANSWER_KEYS / f"{spec.case_id}.json",
            spec,
        )


def check_design(name: str) -> list[str]:
    """Design rule 9's acceptance for the design module `tests.benchmark_cases.designs.<name>`:
    `check_specs` over its `SPECS`, whose refusal is the one failure, nothing rendered; then
    `check_spec` over each spec and, for a spec with a twin, the twin; every failure, in order."""
    specs = importlib.import_module(f"tests.benchmark_cases.designs.{name}").SPECS
    try:
        check_specs(specs)
    except CaseSpecError as error:
        return [str(error)]
    failures: list[str] = []
    for spec in specs:
        failures.extend(check_spec(spec))
        if spec.twin:
            failures.extend(check_spec(twin(spec)))
    return failures
