"""Session tools: the only tools that write, and they only write to the session.

One function per row of the "Session tools" table in contracts/agent-tools.md, plus
`record_drawing_finding` (the one non-numeric finding tool). Each of them enforces a rule
the model must not be able to talk its way around:

- `mark_coverage` cannot write the `failed` bucket - that bucket belongs to the tool
  layer, which writes it when a tool actually failed (contracts/agent-tools.md);
- `record_drawing_finding` cannot claim `demonstrated` or `checked_within_scope`: no
  calculation stands behind a drawing reading, so the strongest status it may take is
  `suspected` (constitution Principle II, FR-009), and it cannot carry a number the cited
  drawing evidence does not state (feature 007 FR-033, `contracts/gate.md` section 5);
- `request_capture` returns a capture that already exists or, with the live bridge wired,
  asks the bridge for one and records it; without a bridge it says `unresolved` and never
  invents a view (US3).
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Literal, get_args

from pydantic import ValidationError

from swreview.findings import build_finding
from swreview.ir.models import DrawingSheet, SourceRef
from swreview.report.attention import CHECKLIST_ITEM_IDS
from swreview.report.session import (
    MAX_OPTIONS,
    OPTION_MAX_LENGTH,
    QUESTION_MAX_LENGTH,
    CoverageItem,
    CoverageScope,
    EvidenceRequest,
)
from swreview.tools.context import (
    ToolContext,
    current_context,
    error_result,
    not_one_of,
    unknown_id,
)
from swreview.tools.query import ToolResult, as_json, sheet_reason
from swreview.tools.recording import title_from

ModelCoverageBucket = Literal["checked", "skipped", "unresolved", "out_of_scope"]
MODEL_COVERAGE_BUCKETS: tuple[str, ...] = get_args(ModelCoverageBucket)
"""The buckets `mark_coverage` accepts. `failed` is written by the tool layer only."""

DrawingFindingStatus = Literal["suspected", "unresolved"]
DRAWING_FINDING_STATUSES: tuple[str, ...] = get_args(DrawingFindingStatus)
DRAWING_FINDING_CHECK = "drawing.manufacturing_inputs"
DRAWING_FINDING_SEVERITY: dict[str, str] = {"suspected": "medium", "unresolved": "low"}

CaptureView = Literal["iso", "front", "back", "left", "right", "top", "bottom", "current"]
CAPTURE_VIEWS: tuple[str, ...] = get_args(CaptureView)


def request_evidence(
    what: str,
    why: str,
    entity_ids: list[str],
    question: str | None = None,
    options: list[str] | None = None,
    blocks: str | None = None,
) -> ToolResult:
    """Record something you need and the package does not have. Returns its id.

    Args:
        what: The evidence you need, in the engineer's terms.
        why: Which check it unblocks and what you would conclude with it.
        entity_ids: Component, hole, fastener or document ids the request is about.
        question: One decision, at most 140 characters; never guess a fit class, tolerance
            or thread depth.
        options: Answers to offer, only when the answers are a closed set: at most 5, each
            60 characters.
        blocks: The checklist item id this request blocks, such as fasteners.

    Notes:
        Use this instead of assuming a missing value. The request stays open in the report
        until an engineer answers it, and the check it blocks stays unresolved.
    """
    # The guidance of feature 009's contracts/questions.md section 1 - one decision per
    # request, options only for a closed set, never guess a fit class, a tolerance or a
    # thread depth - is in the argument descriptions and not in the Notes above: the Notes
    # are pinned byte-equal to the pre-split text by `test_docstring_split.py` (005 FR-039),
    # and an argument's description reaches the model with every lever on or off.
    #
    # Checked in the order of that section, each refusal naming its argument, so the model
    # can answer the one it got wrong; nothing is recorded until every check has passed.
    context = current_context()
    unknown = [entity_id for entity_id in entity_ids if context.entity_kind(entity_id) is None]
    if unknown:
        return error_result(f"entity_ids not in this package: {unknown}")
    refusal = _short_form_refusal(question, options or [], blocks)
    if refusal is not None:
        return error_result(refusal)
    request = record_evidence_request(
        context, what, why, entity_ids, question=question, options=options, blocks=blocks
    )
    return {"status": "open", "evidence_request": as_json(request)}


def record_evidence_request(
    context: ToolContext,
    what: str,
    why: str,
    entity_ids: list[str],
    question: str | None = None,
    options: list[str] | None = None,
    blocks: str | None = None,
) -> EvidenceRequest:
    """Open one evidence request on the session and announce it: the one writer (feature 011
    `contracts/questions.md` section 4).

    `request_evidence` calls it after its refusals, and feature 011's drawing check writes its
    questions through it, so the pane's panel and feature 008's batch route serve both. The
    request is validated through `EvidenceRequest` **before** its id is allocated, so a refused
    one takes no number; a validation error is the caller's to prevent, as `request_evidence`'s
    refusals do. Raises `ValueError` outside a review session.
    """
    context.require_session()  # first, so a sessionless context refuses before anything else
    draft = EvidenceRequest(
        id="ER-000",  # a placeholder of the right shape: validation runs before any id is taken
        what=what,
        why=why,
        entity_ids=list(entity_ids),
        status="open",
        answer=None,
        answered_at=None,
        question=question,
        options=list(options or []),
        blocks=blocks,
    )
    request = draft.model_copy(update={"id": next(context.evidence_request_ids)})
    context.record_evidence_request(request)
    return request


def _short_form_refusal(question: str | None, options: list[str], blocks: str | None) -> str | None:
    """Why the short form of a request is refused, or `None` when it is not.

    The limits are `EvidenceRequest`'s own; they are checked here first so the model gets
    one sentence naming the argument rather than a validation error.
    """
    if question is not None and (not question.strip() or len(question) > QUESTION_MAX_LENGTH):
        return (
            f"question must be one short question of at most {QUESTION_MAX_LENGTH} characters, "
            f"not blank (got {len(question)})"
        )
    if len(options) > MAX_OPTIONS:
        return f"options may offer at most {MAX_OPTIONS} answers (got {len(options)})"
    for index, option in enumerate(options):
        if not option.strip():
            return f"options[{index}] must not be blank"
        if len(option) > OPTION_MAX_LENGTH:
            return (
                f"options[{index}] must be at most {OPTION_MAX_LENGTH} characters "
                f"(got {len(option)})"
            )
    repeated = next(
        (option for index, option in enumerate(options) if option in options[:index]), None
    )
    if repeated is not None:
        return f"options offers {repeated!r} twice; each answer once"
    if blocks is not None and blocks not in CHECKLIST_ITEM_IDS:
        return (
            f"blocks {blocks!r} is not a checklist item id; use one of {list(CHECKLIST_ITEM_IDS)}"
        )
    return None


def mark_coverage(
    check: str,
    bucket: ModelCoverageBucket,
    scope: CoverageScope,
    reason: str,
) -> ToolResult:
    """Record what a check covered, or why it could not be run.

    Args:
        check: Check identifier, or a checklist item id such as `fasteners`.
        bucket: One of checked, skipped, unresolved, out_of_scope.
        scope: What it covered: component_ids, pairs (two ids each), configuration,
            positions, document_ids. State the ones the check actually covered.
        reason: Why this bucket, in one sentence.

    Notes:
        Nothing is silently skipped: every checklist item ends the review with a finding or a
        coverage entry. `failed` is not available here; the tool layer writes that bucket when
        a tool fails.
    """
    context = current_context()
    if bucket not in MODEL_COVERAGE_BUCKETS:
        if bucket == "failed":
            return error_result(
                "bucket 'failed' is written by the tool layer when a tool fails; "
                f"choose one of {list(MODEL_COVERAGE_BUCKETS)}"
            )
        return not_one_of("bucket", str(bucket), MODEL_COVERAGE_BUCKETS)
    unknown = [
        entity_id
        for entity_id in [*scope.component_ids, *scope.document_ids]
        if context.entity_kind(entity_id) is None
    ]
    if unknown:
        return error_result(f"scope names ids not in this package: {unknown}")
    item = CoverageItem(check=check, scope=scope, reason=reason, error=None)
    context.record_coverage(bucket, item)
    return {"status": "recorded", "bucket": bucket, "coverage_item": as_json(item)}


def record_drawing_finding(
    document_id: str,
    sheet: str,
    observed: str,
    requirement: str,
    source_refs: list[SourceRef],
    status: DrawingFindingStatus,
    recommended_action: str,
) -> ToolResult:
    """Record a drawing problem that no calculation stands behind.

    Args:
        document_id: Drawing document id the finding is about.
        sheet: Sheet name on that document.
        observed: What the drawing does or does not say.
        requirement: The governing requirement and where it comes from.
        source_refs: Where on the drawing this was read; each needs a document_id and a
            sheet, annotation, persist_ref or page.
        status: suspected or unresolved.
        recommended_action: What the engineer should do next.

    Notes:
        For missing manufacturing inputs, ambiguous callouts and unreadable sheets. Because
        nothing numeric backs it, the strongest status available is `suspected`;
        `demonstrated` and `checked_within_scope` are not.
    """
    # The number guard below is deliberately **not** described in this docstring. The
    # docstring is the tool description on the wire, pinned to the byte in
    # `test_tool_payload.py` and quoted in feature 005's `contracts/levers.md`; a sentence
    # here would move every one of those measurements. The model meets the rule as an
    # `error_result` it can answer, which is the shape the other five refusals already use.
    context = current_context()
    if context.document(document_id) is None:
        return unknown_id("document", document_id)
    if status not in DRAWING_FINDING_STATUSES:
        return error_result(
            f"status {status!r} is not available to a drawing finding; "
            f"no calculation backs it, so use one of {list(DRAWING_FINDING_STATUSES)}"
        )
    if not source_refs:
        return error_result("source_refs must name at least one place on the drawing")
    locations: list[SourceRef] = []
    for raw in source_refs:
        try:
            location = raw if isinstance(raw, SourceRef) else SourceRef.model_validate(raw)
        except ValidationError as exc:
            return error_result(f"source_ref is not valid: {exc.errors(include_url=False)}")
        if context.document(location.document_id) is None:
            return unknown_id("document", location.document_id)
        locations.append(location)

    invented = _unsourced_numbers(document_id, sheet, locations, observed, requirement)
    if invented is not None:
        return error_result(invented)

    try:
        finding = build_finding(
            finding_id=next(context.finding_ids),
            check=DRAWING_FINDING_CHECK,
            title=title_from(observed),
            status=status,
            severity=DRAWING_FINDING_SEVERITY[status],
            package=context.ir,
            configuration=context.ir.design.active_configuration,
            observed=observed,
            requirement=requirement,
            recommended_action=recommended_action,
            drawing_locations=locations,
            coverage_limits=_drawing_coverage_limits(document_id, sheet, status),
            numeric=False,
        )
    except ValueError as exc:
        return error_result(str(exc))
    context.record_finding(finding)
    return {"status": "recorded", "finding": as_json(finding)}


def _ingested_sheets(document_id: str, sheet: str | None) -> list[DrawingSheet]:
    """The ingested sheets of `document_id`, narrowed to `sheet` when one is named.

    `sheet is None` is a citation that reached the document without naming a sheet - a
    `page` or `persist_ref` locator - and cannot honestly be narrowed to one of them.
    """
    context = current_context()
    return [
        extracted
        for extracted in context.ir.drawings
        if extracted.document_id == document_id and (sheet is None or extracted.sheet_name == sheet)
    ]


def _drawing_coverage_limits(document_id: str, sheet: str, status: str) -> list[str]:
    """Why an unresolved drawing finding could not be settled, from the sheet itself."""
    if status != "unresolved":
        return []
    context = current_context()
    for extracted in _ingested_sheets(document_id, sheet):
        reason = sheet_reason(context.ir, extracted)
        if reason is not None:
            return [f"{document_id} sheet {sheet}: {reason}"]
        break
    return [f"{document_id} sheet {sheet}: the drawing does not state the required value"]


_UNIT = r"mm|cm|um|in|ft|deg|rad|m|°|\""
"""The trailing units a value may carry, longest spelling first so `mm` beats `m`.

They are part of the **token**, so a refusal says `0.05 mm` rather than `0.05`, and they
are not part of what is compared: `text_as_read` is a callout, and callouts state the unit
once on the sheet rather than on every dimension.
"""

_NUMBER_SCANNER = re.compile(
    r"""
      (?P<date>   \d{4}-\d{2}-\d{2})
    | (?P<ident>  [A-Za-z][A-Za-z0-9_]*[-:.]?\d[A-Za-z0-9_.]*)
    | (?P<place>  (?:sheet|view|page|annotation)\s+\d+)
    | (?P<thread> \d+/\d+-\d+)
    | (?P<value>  (?:[±+-])?(?P<core>\d+(?:\.\d+)?)(?:\s?(?:"""
    + _UNIT
    + r""")(?![A-Za-z]))?)
    """,
    re.VERBOSE | re.IGNORECASE,
)
"""One pass over a piece of prose, in which the first three groups are things to walk past.

The order is the whole of the rule (`contracts/gate.md` section 5). An ISO date, an
identifier and a locator (`Sheet 2`) are matched **first** and consumed, so the digits
inside them never reach the two groups that mean "a value": a thread callout, and a decimal
with an optional sign and an optional unit. Matching them rather than testing the
characters around a number is what keeps `2026-09-18` from being read as three values.

"Identifier" is *anything that starts with a letter and goes on to contain a digit*, with
`-`, `:` and `.` allowed inside it - `F-003`, `cmp:0002`, `dnt:0007`, `M6x1.0`, `Y14.5`.
Written that widely on purpose: the narrow version, which required the digit to follow a
`-` or a `:`, read the standard reference in "ASME Y14.5 hole callout practice" as a claim
that the drawing says `5`, and refused a finding whose only real number was correct.
"""


def _magnitude(core: str) -> str:
    """One key for one value, so `5`, `5.0` and `5.00` are the same number.

    The guard asks whether the drawing states the value, not whether the prose spells it
    the way the callout does; a sheet reading `40.0` backs a sentence reading `40 mm`, and
    refusing that would send the model round again to change nothing that matters. `Decimal`
    rather than `float` because the keys are compared for equality.
    """
    return str(Decimal(core).normalize())


def _numbers_in(text: str) -> list[tuple[str, str]]:
    """Every value `text` states, as (the token as written, the key it is compared on).

    The key drops the sign as well as the spelling: a sheet writes a tolerance as
    `+0.025/0` or `±0.1` and the prose restates the same magnitude with whichever sign the
    sentence needs, so it is the magnitude that has to have been read off the drawing. A
    thread callout is compared as written, because `1/4-20` is a designation and its three
    numbers mean nothing apart.
    """
    found: list[tuple[str, str]] = []
    for match in _NUMBER_SCANNER.finditer(text):
        if match.group("thread") is not None:
            found.append((match.group("thread"), match.group("thread")))
        elif match.group("value") is not None:
            found.append((match.group("value"), _magnitude(match.group("core"))))
    return found


def _cited_places(
    document_id: str, sheet: str, locations: list[SourceRef]
) -> list[tuple[str, str | None]]:
    """The finding's own place, then each citation's, in order and without repeats."""
    places: list[tuple[str, str | None]] = [(document_id, sheet)]
    for location in locations:
        place = (location.document_id, location.sheet)
        if place not in places:
            places.append(place)
    return places


def _place_label(place: tuple[str, str | None]) -> str:
    document_id, sheet = place
    return f"{document_id} sheet {sheet}" if sheet is not None else f"{document_id} (every sheet)"


def _drawing_evidence(place: tuple[str, str | None]) -> list[str]:
    """Every piece of drawing text one cited place reaches, from both extraction paths.

    The ingested sheet's dimension callouts and general notes, and the native sheet's note
    and annotation text. Nothing else is evidence of what a drawing *says*: a display
    dimension's computed value is the model's number, not the sheet's, and a finding backed
    by it would be a finding backed by the thing under review.
    """
    document_id, sheet = place
    context = current_context()
    texts: list[str] = []
    for extracted in _ingested_sheets(document_id, sheet):
        texts.extend(item.text_as_read for item in extracted.dimensions)
        texts.extend(note.text for note in extracted.general_notes)
    for record in context.ir.drawing_records:
        if record.document_id != document_id:
            continue
        for native in record.sheets:
            if sheet is not None and native.name != sheet:
                continue
            for view in native.views:
                texts.extend(note.text for note in view.notes if note.text is not None)
                texts.extend(
                    annotation.name
                    for annotation in view.annotations
                    if annotation.name is not None
                )
    return texts


def _unsourced_numbers(
    document_id: str, sheet: str, locations: list[SourceRef], *fields: str
) -> str | None:
    """The sixth refusal, or None: a value no cited sheet states (FR-033).

    The one path on which model prose becomes a claim in the report. The numeric tools put
    a calculation's own result in the finding; this one records what it was handed, so a
    number that was never on a drawing is indistinguishable in `report.md` from one that
    was. Returning a reason rather than raising is deliberate: the model answers it once,
    with a citation or with different words, and the turn continues.
    """
    places = _cited_places(document_id, sheet, locations)
    sourced = {
        value
        for place in places
        for text in _drawing_evidence(place)
        for _, value in _numbers_in(text)
    }
    unsourced: list[str] = []
    for text in fields:
        for token, value in _numbers_in(text):
            if value not in sourced and token not in unsourced:
                unsourced.append(token)
    if not unsourced:
        return None
    searched = ", ".join(_place_label(place) for place in places)
    return (
        f"not stated by any cited drawing evidence: {', '.join(unsourced)}. The "
        f"dimensions, notes and annotations of {searched} were searched. A drawing "
        f"finding may only carry a number the drawing says: cite the sheet that states "
        f"it, or say what the drawing does say."
    )


def get_review_checklist() -> list[dict[str, str]]:
    """The mandatory review checklist with the bucket each item currently sits in.

    Notes:
        `bucket` is `finding` when a finding already covers the item, one of `checked`,
        `skipped`, `unresolved`, `out_of_scope` when a coverage entry does, and `open` when
        nothing does yet. The review is not finished while anything is `open`.
    """
    context = current_context()
    return context.checklist.buckets(context.session)


def get_finding(finding_id: str) -> ToolResult:
    """One finding in full, exactly as the session records it.

    Args:
        finding_id: A finding id a check result's digest listed, such as F-001.
    """
    # No `Notes:` paragraph, on purpose: every byte of this docstring rides on every
    # request of a slimmed review, and the slimmed array must stay under `ARRAY_CEILING`
    # (`tests/unit/test_tool_payload.py`). The digest's `detail` sentence already tells the
    # model what this is for. It reads the session and changes nothing.
    context = current_context()
    if context.session is None:
        return error_result("get_finding reads a review session, and this context has none")
    finding = next((row for row in context.session.findings if row.id == finding_id), None)
    if finding is None:
        return unknown_id("finding", finding_id)
    return {"finding": as_json(finding)}


def request_capture(entity_id: str, view: CaptureView) -> ToolResult:
    """A rendered view of one entity, when the package already holds one.

    Args:
        entity_id: Component, hole or fastener id to look at.
        view: One of iso, front, back, left, right, top, bottom, current.

    Notes:
        Returns an existing capture from the package. Without the live SOLIDWORKS bridge
        there is no way to make a new one, and the result is `unresolved` rather than a
        description of what the view would show.
    """
    context = current_context()
    if context.entity_kind(entity_id) is None:
        return unknown_id("entity", entity_id)
    if view not in CAPTURE_VIEWS:
        return not_one_of("view", str(view), CAPTURE_VIEWS)
    captures = [capture for capture in context.ir.captures if entity_id in capture.component_ids]
    for capture in captures:
        if capture.view == view:
            return {"status": "found", "capture": as_json(capture)}
    if captures:
        return {
            "status": "found",
            "capture": as_json(captures[0]),
            "note": f"no {view!r} capture exists for {entity_id!r}; this is the "
            f"{captures[0].view!r} view already in the package",
        }
    if context.bridge is None:
        return {"status": "unresolved", "reason": "no capture and no bridge"}

    from swreview.bridge.client import BRIDGE_VIEWS
    from swreview.tools.bridge import capture_through_bridge

    entity = context.component(entity_id) or context.hole(entity_id) or context.fastener(entity_id)
    if entity is None:
        return {
            "status": "unresolved",
            "reason": f"{entity_id} carries no persistent reference the bridge could select",
        }
    if view not in BRIDGE_VIEWS:
        # Substituting a view the bridge can frame would answer a different question
        # from the one that was asked.
        return {
            "status": "unresolved",
            "reason": f"the bridge frames {list(BRIDGE_VIEWS)}, not {view!r}",
        }
    component_ids = [getattr(entity, "component_id", entity_id)]
    return capture_through_bridge(context, entity.persist_ref, view, component_ids)
