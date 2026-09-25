"""The fixture generator's size bar measures the scramble, not the code (008 T124, decision 23A).

`contracts/replay.md` section 8, research R2.58. The generator refuses to write a fixture in which a
result of 5,000 tokens or more moved by more than 5%. It compared the fixture's result with the
recorded size, so when feature 003's decision 20A made the part check return 182,865 and 15,548
tokens on the raw recorded packages against 204,858 and 17,437 recorded (the fixtures' results are
182,848 and 15,892), it refused two fixtures whose scramble had distorted nothing. The bar exists
to catch the fictional names distorting a result, so it now compares the fixture's result with the
same call's result on the raw recorded package, as the current code returns it - the play
`original_sizes` already makes - with the same 5,000 tokens and 5%. For every call the current
code reproduced that was already the comparison; a call it changed is now held to the same bar.

The review of 23A (T127): one call's raw result measures nothing. The live `bridge_interference`
call is answered on the raw package with the same fictional rows as on the fixture, so its raw
result is those rows against themselves; the recorded size was the only check that the rows reach
the recorded result, and on the big recording without `--groups 113` they did not (2,129 tokens
against 17,015). The live call is held to both: its raw result, and from 5,000 tokens its recorded
size, which `live_target` gives once to the rows and to the bar.
"""

from __future__ import annotations

from pathlib import Path
from types import ModuleType

import pytest

from swreview.agent.providers import FRAMING_TOKENS, tool_result_text
from swreview.agent.providers.fake import ScriptedToolCall
from swreview.benchmark.recording import read_recording
from swreview.benchmark.replay import TurnPlan
from swreview.ir.loader import load_package, save_package
from swreview.prerun import LIVE_INTERFERENCE_TOOL, PRERUN_INTERFERENCE_SETTINGS
from swreview.tokens import count_tokens
from swreview.tools.context import context_for
from swreview.tools.registry import ToolRegistry
from tests.support import mechanical
from tests.support.narrowed import RMS_PART, SUMMARY, older_table, part_package, record
from tests.support.prerun import LIVE_ROWS, live_prerun_package
from tests.support.replay import record_scripted_review
from tests.support.review_bridge import VOLUME_UNIT_GAP, ScriptedReviewBridge

pytestmark = pytest.mark.usefixtures("vocabulary")

GENERATOR = Path(__file__).resolve().parents[1] / "fixtures" / "replay" / "generate_fixtures.py"
EXAMPLE_PROFILE = Path(__file__).resolve().parents[3] / "config" / "standards.example.yaml"
PART_FIRST = [TurnPlan(rounds=((RMS_PART,), (SUMMARY,)), text="Done.")]
"""The part check followed by another round of its turn, so its recorded growth is observable."""


@pytest.fixture(scope="module")
def generator() -> ModuleType:
    return mechanical.load_generator(GENERATOR)


# --- the bar ------------------------------------------------------------------------------------


def test_the_bar_is_five_percent_of_a_result_of_five_thousand_tokens_or_more(
    generator: ModuleType,
) -> None:
    assert generator.LARGE_RESULT_TOKENS == 5_000
    assert generator.LARGE_RESULT_TOLERANCE == 0.05


def test_a_result_the_code_changed_passes_when_its_scramble_distorts_nothing(
    generator: ModuleType,
) -> None:
    """Decision 20A's part check on the big recording: 182,865 tokens on the raw package, 10.7%
    below its recorded 204,858, and 182,848 on the fixture, a scramble of 17 tokens. The recorded
    size is not an argument, so the 10.7% cannot refuse it."""
    assert generator.size_problems({8: 182_865}, {8: 182_848}) == []


def test_a_scramble_beyond_five_percent_refuses_either_way(generator: ModuleType) -> None:
    assert generator.size_problems({7: 100_000}, {7: 105_001}) == [
        "call 7 is 105001 tokens on the fixture against 100000 on the recorded package, "
        "beyond 5%"
    ]
    assert generator.size_problems({7: 100_000}, {7: 94_999}) == [
        "call 7 is 94999 tokens on the fixture against 100000 on the recorded package, "
        "beyond 5%"
    ]


def test_exactly_five_percent_passes(generator: ModuleType) -> None:
    assert generator.size_problems({7: 100_000, 8: 100_000}, {7: 105_000, 8: 95_000}) == []


def test_a_result_under_five_thousand_tokens_on_the_raw_package_is_not_measured(
    generator: ModuleType,
) -> None:
    assert generator.size_problems({3: 4_999}, {3: 9_998}) == []


def test_a_result_of_five_thousand_tokens_is_measured(generator: ModuleType) -> None:
    assert generator.size_problems({3: 5_000}, {3: 5_250}) == []
    assert generator.size_problems({3: 5_000}, {3: 5_251}) == [
        "call 3 is 5251 tokens on the fixture against 5000 on the recorded package, beyond 5%"
    ]


def test_every_large_result_is_named_in_call_order(generator: ModuleType) -> None:
    problems = generator.size_problems(
        {9: 20_000, 2: 10_000, 5: 1_000}, {9: 30_000, 2: 20_000, 5: 5_000}
    )

    assert [problem.split(" is ")[0] for problem in problems] == ["call 2", "call 9"]


def test_a_large_call_the_fixture_never_played_refuses(generator: ModuleType) -> None:
    assert generator.size_problems({3: 6_000}, {}) == ["call 3 was not played on the fixture"]


# --- the live call: its rows are the generator's, fitted to the recorded size (T127) -------------

LIVE = 12
"""The big recording's live call, among its recorded calls."""


def recorded_bar(fixture: int, recorded: int) -> str:
    return (
        f"call {LIVE} is {fixture} tokens on the fixture against {recorded} recorded, the size "
        "its live rows are fitted to, beyond 5%"
    )


def raw_bar(fixture: int, raw: int) -> str:
    return (
        f"call {LIVE} is {fixture} tokens on the fixture against {raw} on the recorded package, "
        "beyond 5%"
    )


def test_live_rows_fitted_short_of_the_recorded_result_refuse(generator: ModuleType) -> None:
    """The big recording without `--groups 113`: the judged groups' rows alone, 2,128 tokens on
    the raw package and 2,129 on the fixture, against 17,015 recorded. Against its raw result -
    its own rows - the call passes, which is how that fixture was written; against the size its
    rows are fitted to, it refuses."""
    live = generator.LiveTarget(index=LIVE, recorded=17_015)

    assert generator.size_problems({LIVE: 2_128}, {LIVE: 2_129}) == []
    assert generator.size_problems({LIVE: 2_128}, {LIVE: 2_129}, live=live) == [
        recorded_bar(2_129, 17_015)
    ]


def test_live_rows_fitted_to_the_recorded_result_pass(generator: ModuleType) -> None:
    """With `--groups 113`: 17,061 raw, 17,062 on the fixture, 17,015 recorded."""
    live = generator.LiveTarget(index=LIVE, recorded=17_015)

    assert generator.size_problems({LIVE: 17_061}, {LIVE: 17_062}, live=live) == []


def test_the_live_call_at_exactly_five_percent_of_its_recorded_size_passes(
    generator: ModuleType,
) -> None:
    live = generator.LiveTarget(index=LIVE, recorded=100_000)

    assert generator.size_problems({LIVE: 95_000}, {LIVE: 95_000}, live=live) == []
    assert generator.size_problems({LIVE: 105_000}, {LIVE: 105_000}, live=live) == []
    assert generator.size_problems({LIVE: 94_999}, {LIVE: 94_999}, live=live) == [
        recorded_bar(94_999, 100_000)
    ]


def test_a_live_call_recorded_under_five_thousand_tokens_is_not_held_to_it(
    generator: ModuleType,
) -> None:
    """The small recordings' live calls are 315 and 31 tokens: too small for the bar, as any
    other result that size is."""
    live = generator.LiveTarget(index=LIVE, recorded=4_999)

    assert generator.size_problems({LIVE: 315}, {LIVE: 4_000}, live=live) == []


def test_a_live_call_of_five_thousand_recorded_tokens_is_held_to_it(
    generator: ModuleType,
) -> None:
    live = generator.LiveTarget(index=LIVE, recorded=5_000)

    assert generator.size_problems({LIVE: 315}, {LIVE: 4_750}, live=live) == []
    assert generator.size_problems({LIVE: 315}, {LIVE: 4_749}, live=live) == [
        recorded_bar(4_749, 5_000)
    ]


def test_the_live_call_is_still_held_to_its_raw_result(generator: ModuleType) -> None:
    """Its rows reach the recorded size, but the scramble moved the result more than 5% from the
    same rows on the real names: the scramble bar refuses, as for any call."""
    live = generator.LiveTarget(index=LIVE, recorded=18_000)

    assert generator.size_problems({LIVE: 17_000}, {LIVE: 17_900}, live=live) == [
        raw_bar(17_900, 17_000)
    ]


def test_a_live_call_beyond_both_is_named_against_both(generator: ModuleType) -> None:
    live = generator.LiveTarget(index=LIVE, recorded=20_000)

    assert generator.size_problems({LIVE: 10_000}, {LIVE: 12_000}, live=live) == [
        raw_bar(12_000, 10_000),
        recorded_bar(12_000, 20_000),
    ]


def test_a_live_call_the_fixture_never_played_is_named_once(generator: ModuleType) -> None:
    live = generator.LiveTarget(index=LIVE, recorded=17_015)

    assert generator.size_problems({LIVE: 17_061}, {}, live=live) == [
        f"call {LIVE} was not played on the fixture"
    ]
    assert generator.size_problems({LIVE: 2_128}, {}, live=live) == [
        f"call {LIVE} was not played on the fixture"
    ]


def test_the_live_call_is_named_in_call_order_with_the_rest(generator: ModuleType) -> None:
    live = generator.LiveTarget(index=LIVE, recorded=17_015)

    problems = generator.size_problems(
        {2: 15_582, LIVE: 2_128, 20: 10_000}, {2: 20_000, LIVE: 2_129, 20: 20_000}, live=live
    )

    assert [problem.split(" is ")[0] for problem in problems] == ["call 2", "call 12", "call 20"]


LIVE_CALL = ScriptedToolCall(
    LIVE_INTERFERENCE_TOOL,
    {"component_ids": [], "configuration": "Default", "settings": PRERUN_INTERFERENCE_SETTINGS},
)
LIVE_SECOND = [TurnPlan(rounds=((SUMMARY,), (LIVE_CALL,), (SUMMARY,)), text="Done.")]
"""The live call in a round of its own after a summary, and a round after it, so its recorded
growth is observable."""


def test_live_target_is_the_live_calls_place_and_its_size_from_the_recorded_growth(
    generator: ModuleType, tmp_path: Path
) -> None:
    """What the rows are fitted to and what the bar holds the live call to are one value: the
    call's place among the recorded calls, and its recorded result sized from the growth of the
    round it was sent in, as `estimated_sizes` sizes a call the replay cannot reproduce."""
    package_dir = tmp_path / "package"
    save_package(live_prerun_package(), package_dir)
    answer = {"interferences": [dict(row) for row in LIVE_ROWS], "gaps": [dict(VOLUME_UNIT_GAP)]}
    run = record_scripted_review(
        tmp_path / "recording",
        package_dir,
        LIVE_SECOND,
        bridge=True,
        bridge_factory=lambda pipe, secret: ScriptedReviewBridge(
            results={"interference": [answer]}
        ),
    )
    recording = read_recording(run)
    live = generator.live_call(recording)
    assert live is not None
    growth = recording.growth_after(recording.turns[0].main_rounds[1])
    assert growth is not None

    target = generator.live_target(recording, live)

    assert target == generator.LiveTarget(index=1, recorded=growth - FRAMING_TOKENS)
    assert generator.all_calls(recording)[target.index].tool == LIVE_INTERFERENCE_TOOL


# --- what the bar is handed ---------------------------------------------------------------------


def test_original_sizes_hands_the_bar_the_current_codes_result_on_the_recorded_package(
    generator: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A recording whose part check the current code changed: recorded by a table that counted
    `SensorFolder`, played by today's. The usage adjustment starts from the recorded growth; the
    bar gets the current code's result on the same raw package."""
    monkeypatch.setattr(generator, "STANDARDS_PROFILE", EXAMPLE_PROFILE)
    run = record(
        tmp_path / "recording", part_package(), older_table(tmp_path / "older"), PART_FIRST
    )
    recording = read_recording(run)
    today = (
        ToolRegistry()
        .dispatch(context_for(load_package(run).package))
        .call("check_rms_part", {"document_id": None})
    )
    growth = recording.growth_after(recording.turns[0].main_rounds[0])
    assert growth is not None

    sizes, current = generator.original_sizes(recording, [], None, tmp_path / "scratch")

    assert current[0] == count_tokens(tool_result_text(today.payload))
    assert sizes[0] == (growth - FRAMING_TOKENS, "estimated")
    assert current[0] < sizes[0][0], "today's part check names one subject fewer"
    assert sizes[1] == (current[1], "reproduced")


def test_a_recording_the_code_reproduces_hands_the_bar_the_same_sizes(
    generator: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(generator, "STANDARDS_PROFILE", EXAMPLE_PROFILE)
    run = record(tmp_path / "recording", part_package(), turns=PART_FIRST)

    sizes, current = generator.original_sizes(
        read_recording(run), [], None, tmp_path / "scratch"
    )

    assert current == {index: size for index, (size, _) in sizes.items()}
    assert {how for _, how in sizes.values()} == {"reproduced"}
    assert set(current) == {0, 1}
