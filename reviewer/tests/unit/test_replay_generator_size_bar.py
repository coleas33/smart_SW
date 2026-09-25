"""The fixture generator's size bar measures the scramble, not the code (008 T124, decision 23A).

`contracts/replay.md` section 8, research R2.58. The generator refuses to write a fixture in which a
result of 5,000 tokens or more moved by more than 5%. It compared the fixture's result with the
recorded size, so when feature 003's decision 20A made the part check return 182,848 and 15,892
tokens on the raw recorded packages against 204,858 and 17,437 recorded, it refused two fixtures
whose scramble had distorted nothing. The bar exists to catch the fictional names distorting a
result, so it now compares the fixture's result with the same call's result on the raw recorded
package, as the current code returns it - the play `original_sizes` already makes - with the same
5,000 tokens and 5%. For every call the current code reproduced that was already the comparison;
a call it changed is now held to the same bar.
"""

from __future__ import annotations

from pathlib import Path
from types import ModuleType

import pytest

from swreview.agent.providers import FRAMING_TOKENS, tool_result_text
from swreview.benchmark.recording import read_recording
from swreview.benchmark.replay import TurnPlan
from swreview.ir.loader import load_package
from swreview.tokens import count_tokens
from swreview.tools.context import context_for
from swreview.tools.registry import ToolRegistry
from tests.support import mechanical
from tests.support.narrowed import RMS_PART, SUMMARY, older_table, part_package, record

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
    """Decision 20A's part check: 10.7% below its recorded 204,858 tokens, and the fixture's
    scramble within a few tokens of the raw result. The recorded size is not an argument."""
    assert generator.size_problems({7: 182_848}, {7: 182_861}) == []


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
