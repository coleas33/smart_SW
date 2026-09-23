"""Nothing the model is sent tells it to call a tool lever 13 withheld (feature 008 T111).

FR-030 and `contracts/checks-first.md` section 7. Once checks first has run a check tool to
completion the tool leaves the array, and three sentences that ask the model to call such a
tool - step 3 and step 4 of the system prompt, and the `modeling.resilience` checklist item -
change with it, from one table (`agent/withheld_wording.py`). This module pins the new text,
proves every old sentence is still where the table expects it (so a rewording elsewhere
cannot silently stop matching), and sweeps everything a pane review sends - the system
prompt, the checklist in it and from `get_review_checklist`, the opening message and every
offered tool's description and parameters - for a withheld tool's name. Three places may
name one: the digest's `Evaluated:` lines (a report of what ran), `WITHHELD_LINE` (which says
it is not offered), and `list_equations`' description, which explains the equation rules'
verdict rather than asking for a call (research R2.53). With the lever off nothing moves.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from swreview.agent.checklist import load_checklist
from swreview.agent.providers import ProviderName
from swreview.agent.providers.fake import FakeProvider, ScriptedToolCall, ScriptedTurn
from swreview.agent.runner import (
    REDUCED_PROFILE_SKIPPED,
    SYSTEM_PROMPT_FILE,
    ReviewRun,
    start_review,
)
from swreview.agent.settings import pane_defaults
from swreview.agent.withheld_wording import (
    CHECKLIST_REWORDINGS,
    SYSTEM_PROMPT_REWORDINGS,
    reworded,
    reworded_checklist,
)
from swreview.ir.loader import save_package
from swreview.prerun import RMS_PRERUN_TOOLS, WITHHELD_LINE
from tests.support.prerun import (
    MODEL_DRIVEN_CALLS,
    STANDARDS_PROFILE,
    standards_prerun_package,
)

PANE = pane_defaults(ProviderName.FAKE)
LEVER_OFF = PANE.efficiency.model_copy(update={"withhold_prerun_tools": False})
SEVEN: tuple[str, ...] = tuple(call.name for call in MODEL_DRIVEN_CALLS)
EVERY_WITHHELD: tuple[str, ...] = (*SEVEN, "check_standards")
INTERFERENCE = "check_interference_group"

DESCRIPTIVE_MENTIONS: frozenset[tuple[str, str]] = frozenset(
    {("list_equations", "check_rms_equations")}
)
"""A tool description that names a withheld tool to explain a verdict, not to ask for a call.
Rewording it would move every array pin of every run, lever or no lever (research R2.53)."""

STEP_3 = (
    "3. Run every check through its check tool (`check_fastener_joint`, `check_fit`,\n"
    "   `check_axial_stack`, `check_hole_alignment`). Check tools\n"
    "   accept entity ids and source references, not typed numbers."
)
STEP_4 = (
    "4. The modelling method was graded before your first turn: checks first ran the three RMS\n"
    "   checks over every document, and the opening message gives their counts. Together they\n"
    "   close out `modeling.resilience`; do not mark that item covered by hand."
)
MODELING_RESILIENCE = (
    "Part feature trees follow the six-group discipline with one-directional references, "
    "fully defined sketches and described features; the root assembly mates to reference "
    "geometry with a fixed or fully constrained first component and shallow chains; parts "
    "carry global variables. Checks first ran the three RMS checks before the first turn. "
    "Drawing and judgement-only rules are recorded as out of scope with the reason."
)
"""The contract's text (`contracts/checks-first.md` section 7), pinned whole."""

FEATURE_003_SENTENCE = (
    "the evidence was written by the {profile!r} dump profile: the {phases} phases were "
    "never run, so {arrays} are empty because nothing read them - not because this design "
    "has none. Extract full evidence and review again to cover anything that depends on "
    "them (FR-022)."
)


def system_text() -> str:
    """The system prompt file as `build_system_prompt` reads it."""
    return SYSTEM_PROMPT_FILE.read_text(encoding="utf-8").strip()


def descriptions() -> list[str]:
    return [item.description for item in load_checklist().items]


# --- the table: every old sentence is where it is expected -------------------------------------


@pytest.mark.parametrize("entry", SYSTEM_PROMPT_REWORDINGS, ids=lambda entry: entry.new[:24])
def test_every_system_prompt_entry_matches_exactly_once(entry: Any) -> None:
    assert system_text().count(entry.old) == 1
    assert entry.withheld, "an entry applies only when named tools are withheld"


@pytest.mark.parametrize("entry", CHECKLIST_REWORDINGS, ids=lambda entry: entry.new[:24])
def test_every_checklist_entry_matches_exactly_once(entry: Any) -> None:
    assert sum(text.count(entry.old) for text in descriptions()) == 1


# --- the new text, pinned ------------------------------------------------------------------------


def test_with_everything_withheld_steps_3_and_4_read_as_the_contract_says() -> None:
    text = reworded(system_text(), EVERY_WITHHELD, SYSTEM_PROMPT_REWORDINGS)

    assert STEP_3 in text
    assert STEP_4 in text
    for name in (*RMS_PRERUN_TOOLS, INTERFERENCE):
        assert name not in text


def test_the_interference_tool_alone_changes_step_3_only() -> None:
    text = reworded(system_text(), (INTERFERENCE,), SYSTEM_PROMPT_REWORDINGS)

    assert STEP_3 in text
    assert all(name in text for name in RMS_PRERUN_TOOLS)


def test_step_4_changes_only_when_all_three_rms_tools_are_withheld() -> None:
    for partial in ((*RMS_PRERUN_TOOLS[:2],), (RMS_PRERUN_TOOLS[2], INTERFERENCE)):
        assert STEP_4 not in reworded(system_text(), partial, SYSTEM_PROMPT_REWORDINGS)
    assert STEP_4 in reworded(system_text(), RMS_PRERUN_TOOLS, SYSTEM_PROMPT_REWORDINGS)


def test_the_modelling_item_reads_as_the_contract_says_and_nothing_else_moves() -> None:
    before = load_checklist()
    after = reworded_checklist(before, EVERY_WITHHELD)

    changed = {
        item.id: item.description
        for item, was in zip(after.items, before.items, strict=True)
        if item != was
    }
    assert changed == {"modeling.resilience": MODELING_RESILIENCE}
    assert (after.version, [i.id for i in after.items]) == (
        before.version,
        [i.id for i in before.items],
    )


def test_with_nothing_withheld_the_prompt_and_the_checklist_are_todays() -> None:
    checklist = load_checklist()

    assert reworded(system_text(), (), SYSTEM_PROMPT_REWORDINGS) == system_text()
    assert reworded_checklist(checklist, ()) == checklist
    assert reworded_checklist(checklist, (INTERFERENCE,)) == checklist


def test_the_reduced_profile_sentence_of_feature_003_does_not_change() -> None:
    """FR-037's template, pinned: nothing about lever 13 may reach it."""
    assert REDUCED_PROFILE_SKIPPED == FEATURE_003_SENTENCE


# --- the sweep: a pane review sends no withheld name except where allowed ---------------------


class SpyProvider(FakeProvider):
    def __init__(self, **options: Any) -> None:
        super().__init__(**options)
        self.systems: list[str] = []

    def run(self, *, system: str, **options: Any) -> Any:
        self.systems.append(system)
        return super().run(system=system, **options)


def reviewed(tmp_path: Path, efficiency: Any, folder: str) -> tuple[ReviewRun, SpyProvider]:
    run_dir = tmp_path / folder
    save_package(standards_prerun_package(), run_dir)
    provider = SpyProvider(
        script=[
            ScriptedTurn(
                text="done", tool_calls=(ScriptedToolCall("get_review_checklist"),)
            )
        ],
        model="fake-scripted",
    )
    run = start_review(
        run_dir,
        run_dir,
        provider=provider,
        efficiency=efficiency,
        model_view=PANE.model_view,
        standards_profile=STANDARDS_PROFILE,
    )
    run.start()
    return run, provider


@pytest.fixture(scope="module")
def pane_review(tmp_path_factory: pytest.TempPathFactory) -> tuple[ReviewRun, SpyProvider]:
    return reviewed(tmp_path_factory.mktemp("wording"), PANE.efficiency, "pane")


def named(text: str) -> set[str]:
    return {name for name in EVERY_WITHHELD if re.search(rf"\b{name}\b", text)}


def test_the_review_under_test_withholds_all_eight(
    pane_review: tuple[ReviewRun, SpyProvider],
) -> None:
    run, _ = pane_review
    offered = {tool.name for tool in run.tools}

    assert not offered & set(EVERY_WITHHELD)
    assert WITHHELD_LINE.format(tools=", ".join(EVERY_WITHHELD)) in str(run.messages[0]["content"])


def test_the_system_prompt_names_no_withheld_tool(
    pane_review: tuple[ReviewRun, SpyProvider],
) -> None:
    _, spy = pane_review

    assert named(spy.systems[0]) == set()


def test_the_checklist_the_model_reads_back_names_no_withheld_tool(
    pane_review: tuple[ReviewRun, SpyProvider],
) -> None:
    run, _ = pane_review
    [step] = [step for step in run.session.steps if step.tool == "get_review_checklist"]
    stored = json.loads(
        (Path(run.out_dir) / "tool-results" / f"step-{step.index}.json").read_text(
            encoding="utf-8"
        )
    )

    assert named(json.dumps(stored["payload"])) == set()
    assert named(run.context.checklist.render()) == set()


def test_the_opening_names_withheld_tools_only_to_say_what_ran_and_what_is_not_offered(
    pane_review: tuple[ReviewRun, SpyProvider],
) -> None:
    run, _ = pane_review
    report_of_what_ran = re.compile(r"^  (\w+)(\(| x\d+ -> )")

    for line in str(run.messages[0]["content"]).splitlines():
        if line.startswith("Not offered to you this session"):
            continue
        ran = report_of_what_ran.match(line)
        mentioned = named(line) - ({ran.group(1)} if ran else set())
        assert mentioned == set(), line


def test_no_offered_tool_names_a_withheld_one_except_the_one_explanation(
    pane_review: tuple[ReviewRun, SpyProvider],
) -> None:
    run, _ = pane_review

    for tool in run.tools:
        text = tool.description + json.dumps(tool.schema)
        for name in named(text):
            assert (tool.name, name) in DESCRIPTIVE_MENTIONS, (tool.name, name)


def test_with_the_lever_off_the_system_prompt_still_asks_for_every_check(
    tmp_path: Path, pane_review: tuple[ReviewRun, SpyProvider]
) -> None:
    _, on = pane_review
    _, off = reviewed(tmp_path, LEVER_OFF, "off")

    assert off.systems[0] != on.systems[0]
    assert system_text() in off.systems[0]
    assert load_checklist().render() in off.systems[0]
