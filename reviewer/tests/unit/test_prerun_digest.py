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

import re
from collections.abc import Sequence
from typing import Any

from swreview.agent.package_brief import package_brief
from swreview.agent.providers.fake import FakeProvider, ScriptedTurn
from swreview.agent.runner import OPENING_MESSAGE, PROFILE_CHECK, ReviewRun, start_review
from swreview.ir.loader import save_package
from swreview.prerun import (
    DIGEST_HEADER,
    GATE_INSTRUCTION,
    GATE_JUDGEMENT_HEADER,
    GATE_START_HERE_HEADER,
    NOT_EVALUATED_HEADER,
    PRERUN_CHECK_PREFIX,
    STANDARDS_FAMILY_NAME,
    STANDARDS_NO_PROFILE,
    NotEvaluated,
    PrerunResult,
    gate_brief,
    not_evaluated_families,
)
from swreview.report.attention import rank
from swreview.report.markdown import render_report
from swreview.report.session import ReviewSession, load_session
from tests.support.attention import REVIEW_SESSION_FILE
from tests.support.prerun import (
    GATE_ON,
    MODEL_DRIVEN_CALLS,
    OFF,
    ON,
    empty_model_check_package,
    prerun_package,
)
from tests.unit.test_report_start_here import section_of


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
    assert opening_of(off_run) == f"{package_brief(off_run.context.ir)}\n\n{OPENING_MESSAGE}"


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
    # Feature 010 T036 and T046, edited deliberately: with `check_joints` planned, both lines
    # are what the joint map could not reach. The fixture's one screw is recognised and not
    # placed - its holes carry no cylinder face - instead of "1 fastener" counted for the
    # model to judge; and the hole-alignment line names the faceless holes instead of a
    # coaxial pair count.
    assert "  fastener joints: 1 recognised fastener was not placed in any joint." in digest
    assert "1 fastener in the package" not in digest
    assert (
        "  hole alignment: 2 holes have no cylinder face or belong to a component that "
        "was not read; they are in no joint."
    ) in digest
    assert "coaxial hole pair" not in digest


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
    digest and an item in coverage, not a silence.

    Feature 010 T028, edited deliberately: `check_joints` takes no argument and is always
    planned, and on a `model_check` package it records the one skipped row that says the
    hole phase did not run - a statement, not a silence."""
    run, session = started(
        tmp_path, "empty", package=empty_model_check_package(), efficiency=ON
    )
    digest = opening_of(run)

    assert [step.tool for step in session.steps] == [
        "check_rms_part",
        "check_rms_equations",
        "check_rms_assembly",
        "check_joints",
    ]
    assert [item.reason for item in session.coverage.skipped if item.check == "joint.map"] == [
        "the hole phase did not run (profile model_check)"
    ]
    assert f"Findings recorded: {len(session.findings)}" in digest
    # Feature 010 T037 and T046, edited deliberately (was `"0 fastener" in digest`): with
    # check_joints planned, a package with no hole row and no fastener leaves the joint map
    # nothing to have missed, so neither the fastener-joint nor the hole-alignment family
    # renders a line.
    assert f"{PRERUN_CHECK_PREFIX}fastener_joint" not in skipped_by_check(session)
    assert "fastener joints:" not in digest
    assert f"{PRERUN_CHECK_PREFIX}hole_alignment" not in skipped_by_check(session)
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


# --- the gate off, and the gate on (T044, FR-030, FR-031) --------------------------------


def digest_of(run: ReviewRun) -> str:
    """Lever 5's message with the brief and opening instruction taken back off."""
    message = opening_of(run)
    assert message.endswith(f"\n\n{OPENING_MESSAGE}")
    body = message.removesuffix(f"\n\n{OPENING_MESSAGE}")
    return body.split("\n\n", 1)[1]


def test_with_the_gate_off_lever_5_still_sends_the_digest_and_nothing_else(
    tmp_path: Any,
) -> None:
    """FR-030. The off arm of lever 11's A/B is a build with lever 5 on and nothing added:
    the message is the digest, a blank line and the opening instruction, which is what every
    assertion above this line is written against."""
    run, _ = started(tmp_path, "lever5", efficiency=ON)

    message = opening_of(run)

    assert message == (
        f"{package_brief(run.context.ir)}\n\n{digest_of(run)}\n\n{OPENING_MESSAGE}"
    )
    assert digest_of(run).startswith(DIGEST_HEADER)
    for header in (GATE_START_HERE_HEADER, GATE_JUDGEMENT_HEADER, GATE_INSTRUCTION):
        assert header not in message


def test_the_gate_alone_runs_the_pre_run_and_opens_with_the_unchanged_digest(
    tmp_path: Any,
) -> None:
    """Lever 11 implies lever 5's pre-run (`contracts/gate.md` section 1), renders the same
    digest from it, and puts the brief's second part immediately after it.

    The one line the gate's digest carries that lever 5's does not is the standards family:
    with the gate on and no `--standards-profile`, "no profile was configured for this
    review" is a gap the gate reports (FR-027), and lever 5 has never asked the question.
    Asserted as a whole-list equality rather than as a substring, so a *second* difference
    between the two arms' digests could not slip past.
    """
    lever5, lever5_session = started(tmp_path, "lever5", efficiency=ON)
    gated, gated_session = started(tmp_path, "gated", efficiency=GATE_ON)

    message = opening_of(gated)
    head, separator, _ = message.partition(f"\n\n{GATE_START_HERE_HEADER}\n")

    assert [step.tool for step in gated_session.steps] == [
        step.tool for step in lever5_session.steps
    ]
    assert separator, "the brief's second part follows the digest"
    gated_digest = head.split("\n\n", 1)[1]
    assert gated_digest.splitlines() == [
        *digest_of(lever5).splitlines(),
        f"  {STANDARDS_FAMILY_NAME}: {STANDARDS_NO_PROFILE}",
    ]
    assert message != opening_of(lever5)
    assert gated.system == lever5.system, "the brief is a user message, never the prefix"


def test_the_briefs_start_here_ids_are_the_reports_start_here_ids_in_order() -> None:
    """FR-031, and structurally: both sides read `ranking.rows` through
    `attention.start_here_lines`, so this fails only if one of them stops doing that.

    The committed 2026-09-18 review session is the fixture, because it is the one whose
    ordering was argued over: eight findings, two of them needing judgement, and a sixth row
    that the cap leaves out of both renderings.
    """
    session = load_session(REVIEW_SESSION_FILE)
    ranking = rank(session)

    brief = gate_brief(PrerunResult(calls=(), not_evaluated=()), ranking)
    report = render_report(session, ranking=ranking)

    in_brief = finding_ids(brief.splitlines())
    in_report = finding_ids(section_of(report, "## Start here"))
    assert in_brief == in_report
    assert len(in_brief) == ranking.top_n


FINDING_ID = re.compile(r"\*\*(F-\d+)\*\*")
"""How both renderings spell an amplified row's finding id: `attention.start_here_lines`
writes `**F-001**` and neither caller rewrites it."""


def finding_ids(lines: Sequence[str]) -> list[str]:
    """Every amplified finding id in one rendering, in the order it appears."""
    return [match.group(1) for line in lines for match in FINDING_ID.finditer(line)]
