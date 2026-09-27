"""The answer basis (feature 013 T105), against its `contracts/sources.md` section 3.

Every model answer opens with one line the backend computes from the turn's steps - never from
the model's text - saying how many results the answer read and, when the review read no drawing,
that no drawing was read. The rules this pins: a read is an `ok` step of a tool that is not a
writer or bookkeeping tool; failed steps read nothing; the words are the words file's.
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from swreview.ir.loader import load_package
from swreview.ir.models import EvidencePackage
from swreview.report.session import InvestigationStep
from swreview.report.sources import READ_EXCLUDED, answer_basis, reads_of
from swreview.report.summary import load_words
from swreview.tools.registry import session_tools
from tests.support.attention import attention_package
from tests.unit.test_review_summary import DRAWING_FIXTURES, candidates_package

NO_READ = "No evidence was read for this answer: this is general guidance."
NO_DRAWING = " No drawing was read in this review."


def step(index: int, tool: str, status: str = "ok") -> InvestigationStep:
    return InvestigationStep(
        index=index,
        tool=tool,
        arguments={},
        result_summary=f"{tool} ran",
        status=status,  # type: ignore[arg-type]
        error=None if status == "ok" else "the tool failed",
        elapsed_s=0.0,
    )


def steps(*tools: str) -> list[InvestigationStep]:
    return [step(index, tool) for index, tool in enumerate(tools)]


def basis(chain: Sequence[InvestigationStep], package: EvidencePackage | None = None) -> str:
    return answer_basis(
        chain, package if package is not None else attention_package(), load_words()
    )


def test_the_sittings_follow_up_turn_reads_as_general_guidance() -> None:
    """The sitting's follow-up called no tool, in a review that read no drawing (research
    R2.30): this is the line its answer now opens with."""
    assert basis([]) == (
        "No evidence was read for this answer: this is general guidance. "
        "No drawing was read in this review."
    )


def test_writers_and_bookkeeping_read_nothing() -> None:
    chain = steps(
        "request_evidence", "mark_coverage", "record_drawing_finding", "get_review_checklist"
    )

    assert reads_of(chain) == 0
    assert basis(chain) == NO_READ + NO_DRAWING


def test_a_failed_step_reads_nothing() -> None:
    chain = [step(0, "check_fit", status="error"), step(1, "get_package_summary", status="error")]

    assert basis(chain) == NO_READ + NO_DRAWING


def test_one_read_is_said_in_the_singular() -> None:
    assert basis(steps("check_rms_part", "mark_coverage")) == (
        "Based on 1 result read for this answer." + NO_DRAWING
    )


def test_several_reads_are_counted() -> None:
    chain = [*steps("check_rms_part", "list_fasteners", "get_package_summary")]
    chain.append(step(3, "check_fit", status="error"))

    assert basis(chain) == "Based on 3 results read for this answer." + NO_DRAWING


def test_a_capture_is_a_read() -> None:
    """`request_capture` is a session tool that hands the model a picture: evidence it reads."""
    assert reads_of(steps("request_capture")) == 1


def test_a_review_that_read_a_drawing_says_nothing_about_drawings() -> None:
    plate = load_package(DRAWING_FIXTURES / "plate-drawing").package

    assert basis(steps("get_drawing_brief"), plate) == "Based on 1 result read for this answer."


def test_a_candidate_found_but_not_opened_is_not_a_drawing_read() -> None:
    assert basis([], candidates_package(1)).endswith(NO_DRAWING)


def test_with_no_package_no_drawing_was_read() -> None:
    assert answer_basis([], None, load_words()) == NO_READ + NO_DRAWING


def test_the_excluded_tools_are_the_registrys_session_tools_but_the_capture() -> None:
    names = {tool.__name__ for tool in session_tools()}

    assert READ_EXCLUDED == names - {"request_capture"}


@pytest.mark.parametrize(
    ("count", "line"),
    [
        (0, NO_READ),
        (1, "Based on 1 result read for this answer."),
        (2, "Based on 2 results read for this answer."),
    ],
)
def test_the_words_are_the_words_files(count: int, line: str) -> None:
    words = load_words().answer_basis
    chain = steps(*["check_rms_part"] * count)

    assert basis(chain).removesuffix(words.no_drawing) == line


def test_the_module_loads_no_provider_settings_or_network_module() -> None:
    from tests.unit.test_review_summary import modules_loaded_by

    loaded = modules_loaded_by("swreview.report.sources")
    forbidden = ("swreview.agent.providers", "swreview.agent.settings", "httpx", "openai", "google")
    assert [name for name in loaded if name.startswith(forbidden)] == []
