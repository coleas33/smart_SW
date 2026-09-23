"""Once checks first has run a check tool to completion, the model is not offered it again
(feature 008 amendment 2026-09-23, T109; FR-030, `contracts/checks-first.md` section 7).

The tool array is resent on every round, and after the pre-run a completed check tool can
only earn the model an `already_run` answer. Lever 13 takes those tools off the array the
adapters encode, and only those: a tool whose pre-run call failed, one a tier withheld, one
the pre-run did not reach, and `check_interference_group` while live detection can still add
a group nobody judged, all stay. The tool stays in the dispatch either way, so a model that
calls a withheld tool anyway is answered by the re-call guard - never "no tool named" - in
the scripted provider and in both real adapters. A name nothing registers is still "no tool
named", and the tools that error lists are the array the model was sent, never a withheld one.

Every test here plays a real `start_review` and reads what the provider was handed.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

import respx

from swreview.agent.providers import ProviderName
from swreview.agent.providers.fake import FakeProvider, ScriptedToolCall, ScriptedTurn
from swreview.agent.providers.gemini_provider import GeminiProvider
from swreview.agent.runner import ReviewRun, start_review
from swreview.agent.settings import (
    MODEL_VIEW_OFF,
    MODEL_VIEW_PANE,
    EfficiencySettings,
    pane_defaults,
)
from swreview.benchmark.recording import read_recording
from swreview.benchmark.replay import TurnPlan, replay_passes
from swreview.ir.loader import save_package
from swreview.ir.models import EvidencePackage, Interference, Volume
from swreview.prerun import ALREADY_RUN, WITHHELD_LINE
from swreview.report.session import load_session
from swreview.tools.context import RMS_NOT_GRADABLE
from tests.support.prerun import (
    FIRST_INSTANCE,
    GROUP_KEY,
    INTERFERENCE_SETTINGS,
    LIVE_ROWS,
    MODEL_DRIVEN_CALLS,
    SECOND_INSTANCE,
    STANDARDS_PROFILE,
    live_prerun_package,
    prerun_package,
    standards_prerun_package,
)
from tests.support.replay import record_scripted_review
from tests.support.review_bridge import VOLUME_UNIT_GAP, ScriptedReviewBridge
from tests.unit.test_gemini_provider import (
    StubClient,
    StubModels,
    call_part,
    chunk,
    stop,
    text_part,
)
from tests.unit.test_openai_provider import (
    RESPONSES_URL,
    completed,
    function_call_item,
    item_done,
    make_provider,
    message_item,
    request_bodies,
    stream_response,
)
from tests.unit.test_session import session_validator

PANE = pane_defaults(ProviderName.FAKE)
"""What a pane review runs with: checks first, lever 13, slimming (so `get_finding`) and
pruning."""

LEVER_OFF = PANE.efficiency.model_copy(update={"withhold_prerun_tools": False})
"""The pane with lever 13 off: checks first alone, the array every pane review sent before."""

SEVEN: tuple[str, ...] = tuple(call.name for call in MODEL_DRIVEN_CALLS)
"""The seven tools the pre-run runs to completion on `prerun_package()`, in its order."""

RMS: tuple[str, ...] = SEVEN[:3]
INTERFERENCE = "check_interference_group"
CODE_FIRST: tuple[str, ...] = SEVEN[4:]
STANDARDS = "check_standards"
UNKNOWN_TOOL = "no tool named"


class SpyProvider(FakeProvider):
    """The scripted provider, remembering what each turn was handed."""

    def __init__(self, **options: Any) -> None:
        super().__init__(**options)
        self.offered: list[list[str]] = []
        self.systems: list[str] = []

    def run(self, *, system: str, tools: Any, **options: Any) -> Any:
        self.offered.append([tool.name for tool in tools])
        self.systems.append(system)
        return super().run(system=system, tools=tools, **options)


def reviewed(
    tmp_path: Path,
    *,
    package: EvidencePackage | None = None,
    turns: tuple[ScriptedTurn, ...] = (ScriptedTurn(text="done"),),
    efficiency: EfficiencySettings = PANE.efficiency,
    folder: str = "run",
    **options: Any,
) -> tuple[ReviewRun, SpyProvider]:
    """One pane-shaped review of `package`, played; the run and what its provider saw."""
    run_dir = tmp_path / folder
    save_package(package if package is not None else prerun_package(), run_dir)
    provider = SpyProvider(script=list(turns), model="fake-scripted")
    options.setdefault("model_view", PANE.model_view)
    run = start_review(run_dir, run_dir, provider=provider, efficiency=efficiency, **options)
    run.start()
    return run, provider


def offered(provider: SpyProvider) -> list[str]:
    [first, *_] = provider.offered
    return first


def withheld_by_the_lever(tmp_path: Path) -> list[str]:
    """What lever 13 took off: the lever-off array less the lever-on array, in order."""
    _, on = reviewed(tmp_path, folder="on")
    _, off = reviewed(tmp_path, folder="off", efficiency=LEVER_OFF)
    kept = set(offered(on))
    assert kept <= set(offered(off))
    return [name for name in offered(off) if name not in kept]


def opening(run: ReviewRun) -> str:
    return str(run.messages[0]["content"])


def withheld_line(names: tuple[str, ...] | list[str]) -> str:
    return WITHHELD_LINE.format(tools=", ".join(names))


def model_steps(run: ReviewRun, count: int) -> list[Any]:
    return run.session.steps[-count:]


def prerun_steps_ok(run: ReviewRun) -> None:
    """Precondition: every call the pre-run made completed, so the rule's input is known."""
    failed = [step.tool for step in run.session.steps if step.status != "ok"]
    assert failed == [], f"a pre-run call failed: {failed}"


# --- the pane default ------------------------------------------------------------------------


def test_the_pane_offers_the_array_less_the_seven_tools_checks_first_ran(tmp_path: Path) -> None:
    run, spy = reviewed(tmp_path)
    prerun_steps_ok(run)

    names = offered(spy)
    assert not set(SEVEN) & set(names)
    assert "get_finding" in names, "the model reads a finding's detail through it"
    taken = withheld_by_the_lever(tmp_path / "pair")
    assert sorted(taken) == sorted(SEVEN), "those seven and nothing else"


def test_the_digest_names_exactly_the_tools_withheld_after_the_evaluated_block(
    tmp_path: Path,
) -> None:
    run, _ = reviewed(tmp_path)
    text = opening(run)

    assert withheld_line(SEVEN) in text
    lines = text.splitlines()
    at = lines.index(withheld_line(SEVEN))
    assert lines[at + 1].startswith("Findings recorded: ")
    assert text.count("Not offered to you this session") == 1


def test_a_follow_up_turn_is_offered_the_same_array(tmp_path: Path) -> None:
    run, spy = reviewed(
        tmp_path, turns=(ScriptedTurn(text="done"), ScriptedTurn(text="answered"))
    )
    run.continue_session("and the holes?")

    assert len(spy.offered) == 2
    assert spy.offered[1] == spy.offered[0]


# --- a withheld tool called anyway ---------------------------------------------------------


def test_a_call_to_every_withheld_tool_is_answered_by_the_guard(tmp_path: Path) -> None:
    """A model can hallucinate a tool it was not offered; the guard answers it, and no
    finding is recorded twice."""
    probe, _ = reviewed(tmp_path, folder="probe")
    findings_after_prerun = len(probe.session.findings)

    run, _ = reviewed(
        tmp_path, turns=(ScriptedTurn(text="done", tool_calls=MODEL_DRIVEN_CALLS),)
    )

    answered = model_steps(run, len(SEVEN))
    assert [step.tool for step in answered] == list(SEVEN)
    for step in answered:
        assert step.status == "ok", step
        assert f'"status":"{ALREADY_RUN}"' in step.result_summary
        assert UNKNOWN_TOOL not in step.result_summary
    assert len(run.session.findings) == findings_after_prerun


def openai_rounds() -> list[Any]:
    """One response calling all seven withheld tools together, then the closing text."""
    items = [
        function_call_item(
            call_id=f"call_{index}",
            name=call.name,
            arguments=json.dumps(dict(call.arguments)),
        )
        for index, call in enumerate(MODEL_DRIVEN_CALLS)
    ]
    for index, item in enumerate(items):
        item["id"] = f"fc_{index}"
    first = stream_response(
        *(item_done(item, index=index) for index, item in enumerate(items)), completed(*items)
    )
    return [first, stream_response(completed(message_item("done")))]


def test_the_openai_adapter_sends_no_withheld_schema_and_gets_the_guards_answers(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    save_package(prerun_package(), run_dir)
    with respx.mock:
        route = respx.post(RESPONSES_URL).mock(side_effect=openai_rounds())
        run = start_review(
            run_dir,
            run_dir,
            provider=make_provider(),
            efficiency=pane_defaults(ProviderName.OPENAI).efficiency,
            model_view=MODEL_VIEW_PANE,
        )
        run.start()
        bodies = request_bodies(route)

    sent = [tool["name"] for tool in bodies[0]["tools"]]
    assert not set(SEVEN) & set(sent)
    assert "get_finding" in sent
    assert [tool["name"] for tool in bodies[1]["tools"]] == sent, "fixed for the session"
    outputs = [
        json.loads(item["output"])
        for item in bodies[1]["input"]
        if item.get("type") == "function_call_output"
    ]
    assert [output["status"] for output in outputs] == [ALREADY_RUN] * len(SEVEN)
    assert UNKNOWN_TOOL not in json.dumps(bodies[1])


def test_the_gemini_adapter_declares_no_withheld_tool_and_gets_the_guards_answers(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    save_package(prerun_package(), run_dir)
    calls = [
        call_part(f"call_{index}", call.name, dict(call.arguments))
        for index, call in enumerate(MODEL_DRIVEN_CALLS)
    ]
    models = StubModels(rounds=[[chunk(*calls), stop()], [chunk(text_part("done")), stop()]])
    adapter = GeminiProvider(
        client=StubClient(models=models), model="gemini-3.5-flash", secrets=["unused"]
    )
    run = start_review(
        run_dir,
        run_dir,
        provider=adapter,
        efficiency=pane_defaults(ProviderName.GEMINI).efficiency,
        model_view=MODEL_VIEW_PANE,
    )
    run.start()

    for call in models.calls:
        declared = [d.name for d in call["config"].tools[0].function_declarations]
        assert not set(SEVEN) & set(declared)
        assert "get_finding" in declared
    answered = model_steps(run, len(SEVEN))
    assert [step.tool for step in answered] == list(SEVEN)
    assert all(f'"status":"{ALREADY_RUN}"' in step.result_summary for step in answered)
    responses = [
        part.function_response.response
        for content in models.calls[1]["contents"]
        for part in content.parts or ()
        if part.function_response is not None
    ]
    assert len(responses) == len(SEVEN)
    assert UNKNOWN_TOOL not in json.dumps(responses, default=str)


# --- a tool that does not exist --------------------------------------------------------------

HALLUCINATED = ScriptedToolCall("check_holes")
"""A name nothing registers: the dispatch answers it with the names the model may call."""

AVAILABLE = "; the tools available are "


def listed_in(error: str) -> list[str]:
    """The names an unknown-tool error offers the model, parsed from its one sentence."""
    head, _, names = error.partition(AVAILABLE)
    assert head == f"{UNKNOWN_TOOL} {HALLUCINATED.name!r}", error
    listed = ast.literal_eval(names)
    assert isinstance(listed, list), error
    return listed


def test_an_unknown_tool_error_lists_the_array_the_model_was_sent(tmp_path: Path) -> None:
    """FR-030: nothing sent to the model may tell it to call a withheld tool, and an error
    result is never pruned, so a list naming one would stay in the history all session."""
    run, spy = reviewed(tmp_path, turns=(ScriptedTurn(text="done", tool_calls=(HALLUCINATED,)),))

    [step] = model_steps(run, 1)
    assert step.status == "error" and step.error is not None
    listed = listed_in(step.error)
    assert not set(SEVEN) & set(listed)
    assert listed == sorted(offered(spy)), "the names offered, no more and no fewer"


def test_with_lever_13_off_an_unknown_tool_error_lists_every_tool_as_before(
    tmp_path: Path,
) -> None:
    run, spy = reviewed(
        tmp_path,
        efficiency=LEVER_OFF,
        turns=(ScriptedTurn(text="done", tool_calls=(HALLUCINATED,)),),
    )

    [step] = model_steps(run, 1)
    assert step.error is not None
    listed = listed_in(step.error)
    assert set(SEVEN) <= set(listed)
    assert listed == sorted(offered(spy))


def test_with_a_tier_and_lever_13_an_unknown_tool_error_names_neither_kind_of_withheld_tool(
    tmp_path: Path,
) -> None:
    """Lever 4 withholds the RMS tools on a package with no feature rows; lever 13 the four
    others the pre-run completed. The error lists what is on the array and nothing else."""
    package = prerun_package().model_copy(update={"features": [], "equations": []})
    efficiency = PANE.efficiency.model_copy(update={"tool_tiers": True})
    run, spy = reviewed(
        tmp_path,
        package=package,
        efficiency=efficiency,
        turns=(ScriptedTurn(text="done", tool_calls=(HALLUCINATED,)),),
    )

    [step] = model_steps(run, 1)
    assert step.error is not None
    listed = listed_in(step.error)
    assert not set(SEVEN) & set(listed)
    assert listed == sorted(offered(spy))


def test_the_openai_adapter_sends_an_unknown_tool_error_naming_no_withheld_tool(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    save_package(prerun_package(), run_dir)
    item = function_call_item(call_id="call_0", name=HALLUCINATED.name, arguments="{}")
    rounds = [
        stream_response(item_done(item, index=0), completed(item)),
        stream_response(completed(message_item("done"))),
    ]
    with respx.mock:
        route = respx.post(RESPONSES_URL).mock(side_effect=rounds)
        run = start_review(
            run_dir,
            run_dir,
            provider=make_provider(),
            efficiency=pane_defaults(ProviderName.OPENAI).efficiency,
            model_view=MODEL_VIEW_PANE,
        )
        run.start()
        bodies = request_bodies(route)

    [output] = [
        json.loads(entry["output"])
        for entry in bodies[1]["input"]
        if entry.get("type") == "function_call_output"
    ]
    sent = [tool["name"] for tool in bodies[0]["tools"]]
    assert listed_in(output["error"]) == sorted(sent)
    assert not set(SEVEN) & set(listed_in(output["error"]))


def test_the_gemini_adapter_sends_an_unknown_tool_error_naming_no_withheld_tool(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    save_package(prerun_package(), run_dir)
    models = StubModels(
        rounds=[
            [chunk(call_part("call_0", HALLUCINATED.name, {})), stop()],
            [chunk(text_part("done")), stop()],
        ]
    )
    adapter = GeminiProvider(
        client=StubClient(models=models), model="gemini-3.5-flash", secrets=["unused"]
    )
    run = start_review(
        run_dir,
        run_dir,
        provider=adapter,
        efficiency=pane_defaults(ProviderName.GEMINI).efficiency,
        model_view=MODEL_VIEW_PANE,
    )
    run.start()

    [response] = [
        part.function_response.response
        for content in models.calls[1]["contents"]
        for part in content.parts or ()
        if part.function_response is not None
    ]
    declared = [d.name for d in models.calls[0]["config"].tools[0].function_declarations]
    assert response is not None
    error = str(response["error"]["error"])  # Gemini's `error` field holds the payload
    assert listed_in(error) == sorted(declared)
    assert not set(SEVEN) & set(listed_in(error))


# --- one rule for "completed", one filter for the array --------------------------------------


def test_the_guards_ledger_and_lever_13_read_one_rule_for_a_completed_call(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """The safety argument: every withheld tool's pre-run calls are in the guard's ledger, so
    a call to one is always answered. Tightening the rule in one place tightens both - the
    tool is then neither withheld nor answered, so a model that calls it gets a real run."""
    from swreview import prerun

    original = prerun.answers_repeat

    def tightened(call: Any) -> bool:
        return call.tool != "check_hygiene" and original(call)

    monkeypatch.setattr(prerun, "answers_repeat", tightened)
    run, spy = reviewed(
        tmp_path,
        turns=(ScriptedTurn(text="done", tool_calls=(ScriptedToolCall("check_hygiene"),)),),
    )
    prerun_steps_ok(run)

    assert "check_hygiene" in offered(spy), "not answerable, so not withheld"
    assert withheld_line([name for name in SEVEN if name != "check_hygiene"]) in opening(run)
    [step] = model_steps(run, 1)
    assert step.tool == "check_hygiene" and step.status == "ok"
    assert ALREADY_RUN not in step.result_summary, "the ledger no longer answers it either"


def test_the_prompts_tool_notes_describe_the_guards_array(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """Lever 2's tool notes follow the array the adapter is handed, taken from the one filter
    that builds it, never from a second copy of the rule that must agree by hand."""
    from swreview.prerun import PrerunGuard

    notes = EfficiencySettings(
        prerun_checks=True, withhold_prerun_tools=True, trim_tool_descriptions=True
    )
    run, spy = reviewed(tmp_path, folder="plain", efficiency=notes)
    names = offered(spy)
    noted = [name for name in names if f"### {name}\n" in spy.systems[0]]
    assert noted, "precondition: some offered tool has notes"
    assert not any(f"### {name}\n" in spy.systems[0] for name in SEVEN)
    dropped = noted[0]

    original = PrerunGuard.__iter__

    def narrower(self: PrerunGuard) -> Any:
        return (tool for tool in original(self) if tool.name != dropped)

    monkeypatch.setattr(PrerunGuard, "__iter__", narrower)
    _, narrowed = reviewed(tmp_path, folder="narrowed", efficiency=notes)

    assert dropped not in offered(narrowed)
    assert f"### {dropped}\n" not in narrowed.systems[0]
    assert all(f"### {name}\n" in narrowed.systems[0] for name in noted[1:])


# --- the edges: what stays offered ----------------------------------------------------------


def test_a_failed_rms_call_keeps_all_three_rms_tools_and_withholds_the_other_four(
    tmp_path: Path,
) -> None:
    run, spy = reviewed(tmp_path, fail_tool=["check_rms_part"])

    names = offered(spy)
    assert set(RMS) <= set(names), "the RMS tools leave together or not at all"
    assert not {INTERFERENCE, *CODE_FIRST} & set(names)
    assert withheld_line((INTERFERENCE, *CODE_FIRST)) in opening(run)


def test_a_failed_code_first_call_keeps_only_that_tool(tmp_path: Path) -> None:
    run, spy = reviewed(tmp_path, fail_tool=["check_hygiene"])

    names = offered(spy)
    assert "check_hygiene" in names
    assert not (set(SEVEN) - {"check_hygiene"}) & set(names)
    assert withheld_line([name for name in SEVEN if name != "check_hygiene"]) in opening(run)


def test_a_failed_group_call_keeps_the_interference_tool(tmp_path: Path) -> None:
    _, spy = reviewed(tmp_path, fail_tool=[INTERFERENCE])

    assert INTERFERENCE in offered(spy)


def test_a_tier_withheld_rms_run_is_the_tiers_business_not_lever_13s(tmp_path: Path) -> None:
    """Lever 4 on a package with no feature rows: the pre-run never calls the RMS tools, so
    lever 13 claims none of them; the tier's own sentence and refusal are unchanged."""
    package = prerun_package().model_copy(update={"features": [], "equations": []})
    efficiency = PANE.efficiency.model_copy(update={"tool_tiers": True})
    run, spy = reviewed(
        tmp_path,
        package=package,
        efficiency=efficiency,
        turns=(ScriptedTurn(text="done", tool_calls=(ScriptedToolCall("check_rms_part"),)),),
    )

    names = offered(spy)
    assert not set(RMS) & set(names), "the tier withholds them"
    text = opening(run)
    line = next(line for line in text.splitlines() if line.startswith("Not offered to you"))
    assert not any(name in line for name in RMS)
    assert "RMS tools were not offered for this review" in text
    [refused] = model_steps(run, 1)
    assert refused.status == "error"
    assert refused.error is not None and refused.error.startswith(
        RMS_NOT_GRADABLE.split("{", 1)[0]
    )


def two_group_package(*, second_key: str, configuration: str = "Default") -> EvidencePackage:
    """`prerun_package()` with a second interference row under `second_key`."""
    package = prerun_package()
    extra = Interference(
        id="int:2",
        configuration=configuration,
        component_ids=[FIRST_INSTANCE, SECOND_INSTANCE],
        volume=Volume(value=7.0, unit="mm3"),
        settings=INTERFERENCE_SETTINGS,
        status="computed",
        error=None,
        group_key=second_key,
        is_fastener=False,
        is_possible=False,
    )
    return package.model_copy(update={"interferences": [*package.interferences, extra]})


def test_a_group_the_pre_run_did_not_reach_keeps_the_interference_tool(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """A cap on the groups judged - today none exists - must not withhold the tool: one
    group left out is one group the model could still need it for."""
    from swreview import prerun

    second = f"{GROUP_KEY}|second"
    original = prerun.planned_calls

    def capped(context: Any, tools: Any) -> Any:
        return tuple(
            call for call in original(context, tools) if call[1].get("group_key") != second
        )

    monkeypatch.setattr(prerun, "planned_calls", capped)
    run, spy = reviewed(tmp_path, package=two_group_package(second_key=second))
    prerun_steps_ok(run)

    assert INTERFERENCE in offered(spy)
    assert not (set(SEVEN) - {INTERFERENCE}) & set(offered(spy))


def test_every_group_judged_withholds_the_interference_tool(tmp_path: Path) -> None:
    run, spy = reviewed(tmp_path, package=two_group_package(second_key=f"{GROUP_KEY}|second"))
    prerun_steps_ok(run)

    assert INTERFERENCE not in offered(spy)
    groups = [step for step in run.session.steps if step.tool == INTERFERENCE]
    assert len(groups) == 2


def test_a_group_key_held_by_two_configurations_keeps_the_interference_tool(
    tmp_path: Path,
) -> None:
    """The pre-run calls a shared key once and the tool judges the active configuration's
    group only, so the other configuration's group was never judged."""
    run, spy = reviewed(
        tmp_path, package=two_group_package(second_key=GROUP_KEY, configuration="Alt")
    )
    prerun_steps_ok(run)

    assert INTERFERENCE in offered(spy)


def live_bridge() -> ScriptedReviewBridge:
    answer = {"interferences": [dict(row) for row in LIVE_ROWS], "gaps": [dict(VOLUME_UNIT_GAP)]}
    return ScriptedReviewBridge(results={"interference": [answer]})


def test_with_live_detection_offered_the_interference_tool_stays(tmp_path: Path) -> None:
    """The model can detect again - another configuration, other settings - and only this
    tool judges what that adds (research R2.53)."""
    bridge = live_bridge()
    run, spy = reviewed(
        tmp_path,
        package=live_prerun_package(),
        bridge=True,
        bridge_factory=lambda pipe, secret: bridge,
    )
    prerun_steps_ok(run)

    names = offered(spy)
    assert INTERFERENCE in names
    assert "bridge_interference" in names
    assert not (set(SEVEN) - {INTERFERENCE}) & set(names)
    assert withheld_line([name for name in SEVEN if name != INTERFERENCE]) in opening(run)


def test_with_no_profile_there_is_no_standards_tool_to_withhold(tmp_path: Path) -> None:
    run, spy = reviewed(tmp_path)

    assert STANDARDS not in offered(spy)
    assert STANDARDS not in withheld_line(SEVEN)
    assert "standards: no profile was configured for this review" in opening(run)


def test_an_attached_standards_run_that_completed_leaves_the_array(tmp_path: Path) -> None:
    run, spy = reviewed(
        tmp_path, package=standards_prerun_package(), standards_profile=STANDARDS_PROFILE
    )
    prerun_steps_ok(run)

    assert any(step.tool == STANDARDS for step in run.session.steps)
    assert STANDARDS not in offered(spy)
    assert withheld_line((*SEVEN, STANDARDS)) in opening(run)


def test_an_attached_standards_run_that_failed_stays_offered(tmp_path: Path) -> None:
    _, spy = reviewed(
        tmp_path,
        package=standards_prerun_package(),
        standards_profile=STANDARDS_PROFILE,
        fail_tool=[STANDARDS],
    )

    assert STANDARDS in offered(spy)


# --- the lever off, and on without a pre-run -----------------------------------------------


def test_with_the_lever_off_the_array_prompt_and_opening_are_todays(tmp_path: Path) -> None:
    """The system prompt's wording under the lever is `test_withheld_wording.py`'s."""
    on_run, _ = reviewed(tmp_path, folder="on")
    off_run, off = reviewed(tmp_path, folder="off", efficiency=LEVER_OFF)

    assert set(SEVEN) <= set(offered(off))
    assert "Not offered to you this session" not in opening(off_run)
    assert opening(on_run).replace(withheld_line(SEVEN) + "\n", "") == opening(off_run)
    _, all_off = reviewed(tmp_path, folder="all-off", efficiency=EfficiencySettings())
    assert off.systems == all_off.systems, "checks first alone leaves the system prompt alone"


def test_the_gate_with_lever_13_withholds_the_same_tools_and_its_brief_says_so(
    tmp_path: Path,
) -> None:
    """Lever 11 implies the pre-run, so lever 13 applies to it exactly as to lever 5; the
    brief's first part is the digest, line included."""
    gated = EfficiencySettings(procedural_gate=True, withhold_prerun_tools=True)
    run, spy = reviewed(tmp_path, efficiency=gated)

    assert not set(SEVEN) & set(offered(spy))
    assert withheld_line(SEVEN) in opening(run)


def test_the_command_lines_lever_pair_without_the_view_withholds_the_same_tools(
    tmp_path: Path,
) -> None:
    """`--lever prerun_checks --lever withhold_prerun_tools` with the model view off: the
    same seven leave, and `get_finding` is not offered because slimming is off."""
    both = EfficiencySettings(prerun_checks=True, withhold_prerun_tools=True)
    _, spy = reviewed(tmp_path, efficiency=both, model_view=MODEL_VIEW_OFF)

    assert not set(SEVEN) & set(offered(spy))
    assert "get_finding" not in offered(spy)


def test_the_lever_without_checks_first_withholds_nothing(tmp_path: Path) -> None:
    run, spy = reviewed(tmp_path, efficiency=EfficiencySettings(withhold_prerun_tools=True))

    assert run.session.steps == []
    assert set(SEVEN) <= set(offered(spy))
    assert "Not offered to you this session" not in opening(run)


# --- a session resumed from disk -----------------------------------------------------------


def test_a_pane_session_records_the_lever_validates_and_round_trips(tmp_path: Path) -> None:
    run, _ = reviewed(tmp_path)
    path = tmp_path / "run" / "session.json"
    written = json.loads(path.read_text(encoding="utf-8"))

    assert written["efficiency"]["withhold_prerun_tools"] is True
    session_validator().validate(written)
    loaded = load_session(path)
    assert loaded.efficiency == run.session.efficiency
    assert loaded.model_dump_json(indent=2) == run.session.model_dump_json(indent=2)


def test_replaying_a_recording_made_with_the_lever_applies_it_as_recorded(
    tmp_path: Path,
) -> None:
    package_dir = tmp_path / "package"
    save_package(prerun_package(), package_dir)
    recorded = record_scripted_review(
        tmp_path / "recording",
        package_dir,
        [TurnPlan(rounds=((ScriptedToolCall("get_package_summary"),),), text="done")],
        efficiency=PANE.efficiency,
        model_view=PANE.model_view,
    )
    passes = replay_passes(
        read_recording(recorded),
        tmp_path / "scratch",
        requested=(EfficiencySettings(), MODEL_VIEW_OFF),
    )

    assert passes.as_recorded.withhold_prerun_tools is True
    for name in SEVEN:
        assert f'"name": "{name}"' not in passes.first.prefix, name
        assert f'"name": "{name}"' in passes.second.prefix, name
