"""Committed-case question probes for 014 ``questions.md`` section 8 (T155).

Each review starts from the case's oracle or null review. Requests use the real registry,
including its guard, step recorder and stored-result writer. Code questions use the product's
question writer; answer points use the driver's models. Expected column moves are declared
independently of scoring, including both newly assessed log columns and their removed reasons.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from swreview.benchmark import answers, questions, scorecard
from swreview.benchmark.case_file import ScriptedAnswer
from swreview.report.session import EvidenceRequest
from swreview.tools.registry import TOOL_RESULTS_DIR_NAME
from swreview.tools.session import record_evidence_request

if TYPE_CHECKING:
    from tests.support.scoring_probes import Change, Probe, ProbeReview

FIT = "interfaces.fit"
DRAWING = "drawing.manufacturing_inputs"

QUESTION_MATCHING_RULES = (
    "hole-instance",
    "fastener-instance",
    "document-instances",
    "distinct-instances",
    "unanswerable-documents",
    "item-only-reask",
    "part-roles-identity",
    "model-in-part-roles-words",
    "reask-outranks-repeat",
    "code-question-not-earlier",
    "error-answer-no-question",
    "before-after-answer",
)
"""Section 8's matching rules, with the distinct-instance boundary made explicit."""

_CONDITIONS_UNASSESSED = {
    "contradicted_condition_ids": scorecard.NO_CORRECT_CONDITION,
    "confirmed_condition_ids": scorecard.NO_CORRECT_CONDITION,
}
_LOG_UNASSESSED = {
    "unscripted_questions": questions.NO_ANSWER_LOG,
    "bound_reached": questions.NO_ANSWER_LOG,
}
_KALO_UNASSESSED = {
    **_CONDITIONS_UNASSESSED,
    "forbidden_hit_finding_ids": scorecard.NO_FORBIDDEN_ENTRY,
    "withdrawn_forbidden_hit_finding_ids": scorecard.NO_FORBIDDEN_ENTRY,
    "coverage_mismatches": scorecard.NO_EXPECTED_COVERAGE,
    "unanswerable_requests": questions.NO_UNANSWERABLE_REQUEST,
    "question_counts": questions.NO_QUESTION_COUNT_RULE,
    **_LOG_UNASSESSED,
}
_MIR_UNASSESSED = {**_CONDITIONS_UNASSESSED, **_LOG_UNASSESSED}


def _log_moves(
    *,
    case: str = "kalo-1",
    unscripted: list[dict[str, Any]] | None = None,
    bound: bool = False,
) -> dict[str, Change]:
    """The exact null-to-assessed transitions whenever a probe introduces an answer log."""
    from tests.support.scoring_probes import Change

    before = _MIR_UNASSESSED if case == "mir-sitting" else _KALO_UNASSESSED
    after = {column: reason for column, reason in before.items() if column not in _LOG_UNASSESSED}
    return {
        "unscripted_questions": Change(None, [] if unscripted is None else unscripted),
        "bound_reached": Change(None, bound),
        "not_assessed": Change(before, after),
    }


def _count_change(before: int, after: int, *, minimum: int) -> Change:
    """The corpus's two single-rule keys both name Q-1 and cap its count at one."""
    from tests.support.scoring_probes import Change

    return Change(
        [{"entry": "Q-1", "count": before, "min": minimum, "max": 1}],
        [{"entry": "Q-1", "count": after, "min": minimum, "max": 1}],
    )


def _seen_reask(review: ProbeReview) -> None:
    review.ask("cmp:0001", item=FIT)
    review.answer(review.session.evidence_requests[-1].id)
    review.ask(item=FIT)
    review.log()


def _refused_reask(review: ProbeReview) -> None:
    review.ask("cmp:0001", item=FIT)
    review.answer(review.session.evidence_requests[-1].id)
    review.ask("cmp:0001", item=FIT)
    review.log()


def _open_repeat(review: ProbeReview) -> None:
    review.ask("cmp:0001", item=FIT)
    review.ask("cmp:0001", item=FIT)


def _unanswerable_refused(review: ProbeReview) -> None:
    # Prepare the guard's open request without another counted tool call, then probe one
    # refusal. With no earlier recorded call this setup contributes no scorer open repeat.
    record_evidence_request(
        review.context,
        "The fictional pin's drawing.",
        "The probe has already requested it.",
        ["cmp:0002"],
    )
    review.ask("cmp:0002")
    call = questions.request_calls(
        review.session, review.folder, questions.QuestionIds(review.package)
    )[-1]
    assert isinstance(call, questions.RequestCall) and call.outcome == "already_asked"


def _unanswerable_documents(review: ProbeReview) -> None:
    # A component id names the entry's document; the recorded probe covers the direct doc id.
    review.ask("cmp:0002")


def _item_count_below(review: ProbeReview) -> None:
    """Remove the one oracle request/call of the disclosed minimum-one-item-question overlay."""
    requests = [step for step in review.session.steps if step.tool == questions.REQUEST_TOOL]
    assert len(requests) == 1
    review.session.steps[:] = [
        step for step in review.session.steps if step.tool != questions.REQUEST_TOOL
    ]
    review.session.evidence_requests[:] = [
        request for request in review.session.evidence_requests if request.blocks != FIT
    ]
    for step in requests:
        (review.folder / TOOL_RESULTS_DIR_NAME / f"step-{step.index}.json").unlink()


def _item_count_above(review: ProbeReview) -> None:
    review.ask("cmp:0001", item=FIT)
    review.ask("cmp:0001", item=FIT)


def _roles_request(review: ProbeReview) -> EvidenceRequest:
    return next(
        request
        for request in review.session.evidence_requests
        if questions.is_part_roles_question(request)
    )


def _write_roles_question(
    review: ProbeReview, original: EvidenceRequest, *, entity_ids: list[str] | None = None
) -> EvidenceRequest:
    """Use the code-question writer, as the runner does; it intentionally permits duplicates."""
    return record_evidence_request(
        review.context,
        original.what,
        original.why,
        original.entity_ids if entity_ids is None else entity_ids,
        question=original.question,
        options=original.options,
        blocks=original.blocks,
        allow_text=original.allow_text,
        source="code",
    )


def _roles_count_below(review: ProbeReview) -> None:
    original = _roles_request(review)
    review.session.evidence_requests.remove(original)


def _roles_count_above(review: ProbeReview) -> None:
    _write_roles_question(review, _roles_request(review))


def _roles_identity(review: ProbeReview) -> None:
    # Identity excludes entity ids: replacing the pin by the plate still counts exactly once.
    original = _roles_request(review)
    review.session.evidence_requests.remove(original)
    recorded = _write_roles_question(review, original, entity_ids=["cmp:0001"])
    assert questions.is_part_roles_question(recorded)


def _model_in_roles_words(review: ProbeReview) -> None:
    original = _roles_request(review)
    review.session.evidence_requests.remove(original)
    review.dispatch.call(
        questions.REQUEST_TOOL,
        {
            "what": original.what,
            "why": original.why,
            "entity_ids": ["cmp:0001"],
            "question": original.question,
            "options": original.options,
        },
    )
    assert not questions.is_part_roles_question(review.session.evidence_requests[-1])


def _unscripted(review: ProbeReview, reason: str) -> None:
    entries: list[ScriptedAnswer] = []
    if reason == "names_nothing":
        review.ask()
    elif reason == "ambiguous":
        # Disjoint entries on the same item are valid; the item-only request asks within both.
        review.ask(item=FIT)
        entries = [
            ScriptedAnswer(id="A-1", item=FIT, ids=["cmp:0001"], answer="press fit"),
            ScriptedAnswer(id="A-2", item=FIT, ids=["cmp:0002"], answer="sliding fit"),
        ]
    else:
        review.ask("cmp:0001", item=FIT)
    request = review.session.evidence_requests[-1]
    decision = questions.scripted_answer_for(
        request, entries, ids=questions.QuestionIds(review.package)
    )
    assert isinstance(decision, questions.Unscripted)
    assert decision.reason == reason
    row = answers.UnscriptedRequest(
        request_id=request.id,
        reason=decision.reason,
        entries=list(decision.entries) if reason == "ambiguous" else None,
    )
    review.answer(unscripted=[row])
    review.log("all_unscripted")


def _bound_reached(review: ProbeReview) -> None:
    review.ask("cmp:0001", item=FIT)
    # Bound zero: the first answer point has a ready delivery, held without answering it.
    review.points.append(
        answers.AnswerPoint(
            after_turn=0,
            steps_before=len(review.session.steps),
            sent=[],
            unscripted=[],
            held=[review.session.evidence_requests[-1].id],
        )
    )
    review.log("bound_reached")


def _instance_repeat(review: ProbeReview, component: str, alias: str) -> None:
    review.ask(component, item=FIT)
    review.ask(alias, item=FIT)


def _distinct_instances(review: ProbeReview) -> None:
    review.ask("cmp:0003", item=FIT)
    review.ask("cmp:0004", item=FIT)


def _reask_outranks_repeat(review: ProbeReview) -> None:
    review.ask("cmp:0003", item=FIT)
    review.answer(review.session.evidence_requests[-1].id)
    review.ask("cmp:0003", "cmp:0004", item=FIT)
    review.ask("cmp:0003", item=FIT)
    review.log()


def _code_question_not_earlier(review: ProbeReview) -> None:
    original = _roles_request(review)
    review.answer(original.id)
    review.ask(*original.entity_ids)
    review.log()


def _before_after_answer(review: ProbeReview) -> None:
    review.ask("cmp:0001", item=FIT)
    review.ask("cmp:0001", item=FIT)
    review.answer(review.session.evidence_requests[-1].id)
    review.ask("cmp:0001", item=FIT)
    review.log()


def _error_answer(review: ProbeReview) -> None:
    step = review.ask("cmp:9999", item=FIT)
    assert step.status == "error"


def question_probes() -> list[Probe]:
    """Every section 8 question column and matching rule, with independently declared moves."""
    from tests.support.scoring_probes import Change, Probe

    log = _log_moves()
    probes = [
        Probe("question-seen-reask", "kalo-1", "null", _seen_reask, {"re_asks": 1, **log}),
        Probe("question-refused-reask", "kalo-1", "null", _refused_reask, {"re_asks": 1, **log}),
        Probe("question-open-repeat", "kalo-1", "null", _open_repeat, {"open_repeats": 1}),
        Probe(
            "question-unanswerable-recorded",
            "mir-sitting",
            "oracle",
            lambda r: r.ask("doc:0003"),
            {"unanswerable_requests": 1},
            "U-1",
        ),
        Probe(
            "question-unanswerable-refused",
            "mir-sitting",
            "oracle",
            _unanswerable_refused,
            {"unanswerable_requests": 1},
            "U-1",
        ),
        Probe(
            "question-unanswerable-closed-by-code",
            "mir-sitting",
            "oracle",
            lambda r: r.ask("doc:0003", item=DRAWING),
            {"unanswerable_requests": 1},
            "U-1",
        ),
        Probe(
            "question-unmatched",
            "kalo-1",
            "null",
            lambda r: r.ask(),
            {"unmatched_requests": 1},
        ),
        Probe(
            "question-item-count-below",
            "kalo-fit-1",
            "oracle",
            _item_count_below,
            {"question_counts": _count_change(1, 0, minimum=1)},
            "Q-1",
            overlay="minimum-one-item-question",
        ),
        Probe(
            "question-item-count-above",
            "kalo-fit-1",
            "oracle",
            _item_count_above,
            {"question_counts": _count_change(0, 2, minimum=0), "open_repeats": 1},
            "Q-1",
        ),
        Probe(
            "question-part-roles-count-below",
            "mir-sitting",
            "oracle",
            _roles_count_below,
            {"question_counts": _count_change(1, 0, minimum=1)},
            "Q-1",
        ),
        Probe(
            "question-part-roles-count-above",
            "mir-sitting",
            "oracle",
            _roles_count_above,
            {"question_counts": _count_change(1, 2, minimum=1)},
            "Q-1",
        ),
        Probe("question-bound-reached", "kalo-1", "null", _bound_reached, _log_moves(bound=True)),
        Probe(
            "question-unanswerable-documents",
            "mir-sitting",
            "oracle",
            _unanswerable_documents,
            {"unanswerable_requests": 1},
            "U-1",
            "unanswerable-documents",
        ),
        Probe(
            "question-item-only-reask",
            "kalo-1",
            "null",
            _seen_reask,
            {"re_asks": 1, **log},
            rule="item-only-reask",
        ),
        Probe(
            "question-part-roles-identity",
            "mir-sitting",
            "oracle",
            _roles_identity,
            {},
            "Q-1",
            "part-roles-identity",
        ),
        Probe(
            "question-model-in-part-roles-words",
            "mir-sitting",
            "oracle",
            _model_in_roles_words,
            {"question_counts": _count_change(1, 0, minimum=1)},
            "Q-1",
            "model-in-part-roles-words",
        ),
        Probe(
            "question-reask-outranks-repeat",
            "kalo-1",
            "null",
            _reask_outranks_repeat,
            {"re_asks": 1, **log},
            rule="reask-outranks-repeat",
        ),
        Probe(
            "question-code-question-not-earlier",
            "mir-sitting",
            "oracle",
            _code_question_not_earlier,
            {"unanswerable_requests": 1, **_log_moves(case="mir-sitting")},
            "Q-1",
            "code-question-not-earlier",
        ),
        Probe(
            "question-error-answer-no-question",
            "kalo-fit-1",
            "oracle",
            _error_answer,
            {
                # The registry records failed coverage for the error's blocked item; its
                # request call still contributes to no question column or count rule.
                "coverage_bucket_mix": Change(
                    {"checked": 0, "skipped": 0, "unresolved": 0, "failed": 0, "out_of_scope": 0},
                    {"checked": 0, "skipped": 0, "unresolved": 0, "failed": 1, "out_of_scope": 0},
                )
            },
            "Q-1",
            "error-answer-no-question",
        ),
        Probe(
            "question-before-after-answer",
            "kalo-1",
            "null",
            _before_after_answer,
            {"re_asks": 1, "open_repeats": 1, **log},
            rule="before-after-answer",
        ),
        Probe(
            "question-distinct-instances",
            "kalo-1",
            "null",
            _distinct_instances,
            {},
            rule="distinct-instances",
        ),
    ]
    for kind, component, alias in (
        ("hole-instance", "cmp:0001", "hol:0001"),
        ("fastener-instance", "cmp:0005", "fst:0001"),
        ("document-instances", "cmp:0001", "doc:0002"),
    ):
        probes.append(
            Probe(
                f"question-{kind}",
                "kalo-1",
                "null",
                lambda r, cid=component, raw=alias: _instance_repeat(r, cid, raw),
                {"open_repeats": 1},
                rule=kind,
            )
        )
    for reason in ("no_answer", "ambiguous", "names_nothing"):
        row: dict[str, Any] = {"request_id": "ER-001", "reason": reason}
        if reason == "ambiguous":
            row["entries"] = ["A-1", "A-2"]
        moves: dict[str, int | Change] = _log_moves(unscripted=[row])
        if reason == "names_nothing":
            moves["unmatched_requests"] = 1
        probes.append(
            Probe(
                f"question-unscripted-{reason}",
                "kalo-1",
                "null",
                lambda r, value=reason: _unscripted(r, value),
                moves,
            )
        )
    return probes
