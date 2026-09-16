"""What the model is told about the pre-run, and what it is told was never evaluated
(T076, lever 5).

The digest is the half of lever 5 that carries the risk. A model handed "these checks are
done" may read it as "the review is done" and stop exploring, so the digest has to say, in
the same breath, what was **not** evaluated and why - and it must say it from the same
coverage the report renders rather than from prose written beside it. One source, two
renderings: every "NOT evaluated" line is a `skipped` coverage item with the same sentence,
so an engineer reading `report.md` and a model reading the first user message are reading
the same claim.

v1 pre-runs only the four checks that already enumerate themselves. Fastener joints and
hole alignment are enumerable in part and still not pre-run: a joint's clamped stack is
model-chosen, and `check_hole_alignment` without a tolerance `SourceRef` is `unresolved` by
design, so pre-running every pair would manufacture verdictless findings and degrade the
report. Both are counted into the digest instead.
"""

from __future__ import annotations

from typing import Any

from swreview.agent.providers.fake import FakeProvider, ScriptedTurn
from swreview.agent.runner import OPENING_MESSAGE, PROFILE_CHECK, ReviewRun, start_review
from swreview.ir.loader import save_package
from swreview.prerun import (
    NOT_EVALUATED_HEADER,
    PRERUN_CHECK_PREFIX,
    NotEvaluated,
    not_evaluated_families,
)
from swreview.report.session import ReviewSession
from tests.support.prerun import (
    MODEL_DRIVEN_CALLS,
    OFF,
    ON,
    empty_model_check_package,
    prerun_package,
)


def started(
    tmp_path: Any, out: str, *, package: Any = None, **options: Any
) -> tuple[ReviewRun, ReviewSession]:
    """One scripted review, played, with the run kept so its messages can be read."""
    package_dir = tmp_path / "package"
    if not package_dir.exists():
        save_package(package if package is not None else prerun_package(), package_dir)
    run = start_review(
        package_dir,
        tmp_path / out,
        provider=FakeProvider(script=[ScriptedTurn(text="done")], model="fake-scripted"),
        **options,
    )
    return run, run.start()


def opening_of(run: ReviewRun) -> str:
    """The first user message of the session: where the digest goes."""
    first = run.messages[0]
    assert first["role"] == "user"
    return str(first["content"])


def skipped_by_check(session: ReviewSession) -> dict[str, str]:
    return {
        item.check: item.reason
        for item in session.coverage.skipped
        if item.check.startswith(PRERUN_CHECK_PREFIX)
    }


# --- where the digest goes ---------------------------------------------------------------


def test_the_digest_is_prepended_to_the_opening_message_and_not_to_the_system_prompt(
    tmp_path: Any,
) -> None:
    """The system prompt is the cacheable prefix and the digest is per package: a digest in
    `system` invalidates the prefix for the whole session (contracts/levers.md, lever 3)."""
    on_run, _ = started(tmp_path, "on", efficiency=ON)
    off_run, _ = started(tmp_path, "off", efficiency=OFF)

    assert on_run.system == off_run.system
    assert opening_of(on_run).endswith(OPENING_MESSAGE)
    assert opening_of(on_run) != OPENING_MESSAGE
    assert opening_of(off_run) == OPENING_MESSAGE


# --- one source, two renderings ----------------------------------------------------------


def test_every_not_evaluated_line_is_a_skipped_coverage_item_with_the_same_sentence(
    tmp_path: Any,
) -> None:
    run, session = started(tmp_path, "on", efficiency=ON)
    digest = opening_of(run)
    written = skipped_by_check(session)

    families = not_evaluated_families(prerun_package(), ())
    assert {family.check for family in families} == set(written)
    for family in families:
        assert written[family.check] == family.reason
        assert family.label in digest
        assert family.reason in digest


def test_the_digest_names_the_two_families_that_are_enumerable_and_still_not_pre_run(
    tmp_path: Any,
) -> None:
    run, _ = started(tmp_path, "on", efficiency=ON)
    digest = opening_of(run)

    assert NOT_EVALUATED_HEADER in digest
    # One screw and one coaxial hole pair are in the fixture; both are counted, neither is
    # evaluated, and the digest says which is which.
    assert "1 fastener" in digest
    assert "1 coaxial hole pair" in digest


def test_the_counts_in_the_digest_equal_the_counts_in_the_session(tmp_path: Any) -> None:
    run, session = started(tmp_path, "on", efficiency=ON)
    digest = opening_of(run)

    assert f"Findings recorded: {len(session.findings)}" in digest
    for finding in session.findings:
        assert finding.id in digest
        assert finding.check in digest
    assert len(skipped_by_check(session)) == len(
        not_evaluated_families(prerun_package(), ())
    )


def test_the_digest_names_every_call_the_pre_run_made(tmp_path: Any) -> None:
    run, session = started(tmp_path, "on", efficiency=ON)
    digest = opening_of(run)

    for call in MODEL_DRIVEN_CALLS:
        assert call.name in digest
    assert [step.tool for step in session.steps] == [call.name for call in MODEL_DRIVEN_CALLS]


# --- the failure paths -------------------------------------------------------------------


def test_a_pre_run_check_that_fails_does_not_stop_the_review(tmp_path: Any) -> None:
    run, session = started(
        tmp_path, "failing", efficiency=ON, fail_tool=["check_rms_part"]
    )

    assert session.ended_at is not None
    assert [item.check for item in session.coverage.failed] == ["tool.check_rms_part"]
    # The other three still ran, and the digest says which one did not.
    assert [step.tool for step in session.steps] == [call.name for call in MODEL_DRIVEN_CALLS]
    assert session.steps[0].status == "error"
    assert "check_rms_part" in opening_of(run)
    assert "error" in opening_of(run)


def test_an_empty_model_check_package_enumerates_nothing_and_says_so(
    tmp_path: Any,
) -> None:
    """No interference, no hole, no fastener: the pre-run makes no call it cannot justify,
    and every family it did not evaluate - interference now among them - is a line in the
    digest and an item in coverage, not a silence."""
    run, session = started(
        tmp_path, "empty", package=empty_model_check_package(), efficiency=ON
    )
    digest = opening_of(run)

    assert [step.tool for step in session.steps] == [
        "check_rms_part",
        "check_rms_equations",
        "check_rms_assembly",
    ]
    assert f"Findings recorded: {len(session.findings)}" in digest
    assert "0 fastener" in digest
    assert "0 coaxial hole pair" in digest
    assert NOT_EVALUATED_HEADER in digest
    assert "interference" in skipped_by_check(session)[f"{PRERUN_CHECK_PREFIX}interference"]


def test_the_partial_evidence_item_is_not_written_twice(tmp_path: Any) -> None:
    """`record_partial_evidence` already says what the dump profile never extracted; the
    digest adds its own lines beside that one and never a second copy of it."""
    _, session = started(
        tmp_path, "empty", package=empty_model_check_package(), efficiency=ON
    )

    profile_items = [item for item in session.coverage.skipped if item.check == PROFILE_CHECK]
    assert len(profile_items) == 1


def test_a_not_evaluated_family_renders_the_same_sentence_into_both_places() -> None:
    """The unit of "one source, two renderings", without a run: the coverage item a family
    writes and the digest line it renders carry the same reason."""
    family = NotEvaluated(check="coverage.prerun.example", label="example", reason="because.")

    assert family.coverage_item().check == family.check
    assert family.coverage_item().reason == family.reason
