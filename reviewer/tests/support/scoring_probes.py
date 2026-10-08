"""The oracle and null reviews, written as package folders, and the one SC-001 and SC-002 assertion.

Feature 014 `contracts/scoring.md` 9.2 and `contracts/questions.md` 8 (research SR-24, RF-15,
RF-58, QA-21), the scorer slice's half and the key-extensions slice's (plan lanes table,
`scoring_probes.py` S1 and S3). `test_committed_answer_keys.py` and the golden scorecards build
their reviews here and assert through `assert_oracle_and_null`, so the two read one definition:

- **The oracle** (`oracle_review`): one finding per known defect, built with the product's
  `build_finding` against the package so its provenance is real, at the defect's expected status,
  `source` `model`, on the defect's parts, with a reference-keyed defect's first covered item in
  its `inputs` and a document-only defect's documents bound through `document_ids`. No finding for
  a correct condition or a forbidden entry. A demonstrated finding cites the session's one
  synthetic step; an unresolved one carries a coverage limit, as `build_finding` requires of each.
  One coverage row per expected-coverage entry, its check the entry's item, in the bucket of its
  first listed status, recorded as a review records one. Per question-count rule with `min` 1,
  one question of its kind: the part-roles question as `agent/runner.ask_part_roles` records it,
  over the roles `classify_parts` gives under `profile`, or one call of the real `request_evidence`
  naming the rule's item and its ids, its step and stored result written as a review writes them.
  No other request call and no answer log.
- **The null review** (`null_review`): an empty session.
- **Both are package folders, as a run leaves one** (RF-58): `session.json`, carrying
  `origin_marks`, and `events.jsonl` holding the one `session.started` event, written through the
  product's `EventSink`, and the oracle's stored request results under `tool-results/`, so the
  scorer's per-package function reads them as it reads a run.
- **A key-only key** has no package; its reviews are built on `stand_in_package(key)` (RF-15), and
  scored through `scorecard._score_package`, since `score_run` refuses a key-only key.

US5 adds the probes and the golden machinery (T154, T155).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import get_args
from uuid import NAMESPACE_URL, uuid5

from swreview.agent.events import EVENTS_FILE_NAME, EventSink
from swreview.agent.runner import SESSION_FILE_NAME, ask_part_roles, classify_part_roles
from swreview.benchmark import matching, questions, scorecard
from swreview.benchmark.answer_key import _dimensions_named, _entities_named
from swreview.benchmark.answer_key_model import (
    AnswerKey,
    KnownDefect,
    Producer,
    QuestionCount,
    Tag,
    is_family,
)
from swreview.benchmark.questions import REQUEST_TOOL
from swreview.benchmark.scorecard import PackageScore
from swreview.checks.standards.profile import StandardsProfile
from swreview.findings import Finding, FindingIdAllocator, build_finding
from swreview.ir.models import Dimension, EvidencePackage, Manifest, SourceRef
from swreview.report.session import (
    ORIGIN_MARKS_VERSION,
    CoverageItem,
    CoverageScope,
    InvestigationStep,
    ReviewSession,
    Timing,
    save_session,
)
from swreview.report.summary import load_words
from swreview.tools.context import ToolContext, context_for
from swreview.tools.refs import resolve_dimension
from swreview.tools.registry import TOOL_RESULTS_DIR_NAME, ToolRegistry
from tests.support.packages import build_package, persist_ref

STARTED_AT = datetime(2026, 9, 28, 9, 0, tzinfo=UTC)
"""When every synthetic review starts: its session's `started_at` and its one event's `at`."""

TIMING = Timing(
    baseline_minutes=None,
    assisted_supervision_minutes=0.0,
    assisted_verification_minutes=0.0,
    false_alarm_handling_minutes=0.0,
    unattended_runtime_minutes=0.0,
)
"""No engineer timed a synthetic review."""

ORACLE_STEP = InvestigationStep(
    index=0,
    tool="oracle",
    arguments={},
    result_summary="the oracle's one synthetic step, cited by each of its demonstrated findings",
    status="ok",
    error=None,
    elapsed_s=0.0,
)
"""A numeric status needs a calculation or a tool result (`findings.build_finding`): the step a
demonstrated oracle finding cites, which the oracle session holds."""

UNRESOLVED_LIMIT = "the oracle states this known defect unresolved, as its key expects"
"""The coverage limit an unresolved oracle finding carries, as `build_finding` requires."""

COVERAGE_REASON = "the oracle states this item as its key expects it"
"""The reason an oracle coverage row carries."""

COLUMNS_BY_KEY_LIST: dict[str, tuple[str, ...]] = {
    "correct_conditions": ("contradicted_condition_ids", "confirmed_condition_ids"),
    "forbidden": ("forbidden_hit_finding_ids", "withdrawn_forbidden_hit_finding_ids"),
    "expected_coverage": ("coverage_mismatches",),
    "unanswerable_requests": ("unanswerable_requests",),
    "question_counts": ("question_counts",),
}
"""The scorecard columns each key list grades: a key with no entry of a list does not grade them,
and they read `null`, their reason in `not_assessed` (`scoring.md` 7; FR-021)."""

ANSWER_LOG_COLUMNS: tuple[str, ...] = ("unscripted_questions", "bound_reached")
"""The columns that read an answer log, which no oracle or null review has and no key grades:
`null` on every review here, their reason in `not_assessed` (`questions.md` 8)."""

NOT_ASSESSED_WITHOUT_EXTENSIONS: dict[str, str] = {
    "forbidden_hit_finding_ids": scorecard.NO_FORBIDDEN_ENTRY,
    "withdrawn_forbidden_hit_finding_ids": scorecard.NO_FORBIDDEN_ENTRY,
    "coverage_mismatches": scorecard.NO_EXPECTED_COVERAGE,
    "unanswerable_requests": questions.NO_UNANSWERABLE_REQUEST,
    "question_counts": questions.NO_QUESTION_COUNT_RULE,
    "unscripted_questions": questions.NO_ANSWER_LOG,
    "bound_reached": questions.NO_ANSWER_LOG,
}
"""The seven columns a key holding none of the four extension lists leaves unassessed on a
package with no answer log, each with its reason (`scoring.md` 7, `questions.md` 6; FR-021)."""

SC_001_COLUMNS: tuple[str, ...] = (
    "matched_defect_ids",
    "flagged_defect_ids",
    "missed_defect_ids",
    "false_alarm_finding_ids",
    "contradicted_condition_ids",
    "confirmed_condition_ids",
    "flagged_below_expected_defect_ids",
    "status_mismatch_defect_ids",
    "cleared_defect_ids",
    "forbidden_hit_finding_ids",
    "withdrawn_forbidden_hit_finding_ids",
    "tuned_on_false_alarm_finding_ids",
    "re_asks",
    "open_repeats",
    "unanswerable_requests",
    "unmatched_requests",
    "unscripted_questions",
    "bound_reached",
)
"""The columns `assert_oracle_and_null` reads off each review's score as they are; it reads
`coverage_mismatches` as plain rows and `question_counts` as the rules each misses."""


# --- the stand-in package (RF-15) -------------------------------------------------------------


def stand_in_package(key: AnswerKey) -> EvidencePackage:
    """The package a key-only key's reviews are built on (RF-15): `build_package` with one
    component instance per component id the key names and one document, with its manifest entry,
    per document id it names, beside `build_package`'s own two documents, of whose part each
    component is an instance. The ids named are those of the known defects, the correct
    conditions and the forbidden entries, an unanswerable request's documents, and a
    question-count rule's ids, a rule's id a document where the key names it one and a component
    instance otherwise (`questions.md` 5.3 allows either), so the oracle's `request_evidence` call
    names ids the stand-in holds. So `build_finding` can attach provenance; nothing else about the
    stand-in is read, its holes, fasteners and gaps are dropped, and the key's ids stay unchecked,
    as the loader leaves them (US1-16)."""
    base = build_package()
    component, part, part_entry = base.components[0], base.documents[1], base.manifest.entries[1]
    entries = [*key.known_defects, *key.correct_conditions, *key.forbidden]
    named_documents = dict.fromkeys(
        [
            *(did for entry in entries for did in entry.document_ids),
            *(did for entry in key.unanswerable_requests for did in entry.documents),
        ]
    )
    component_ids = dict.fromkeys(
        [
            *(cid for entry in entries for cid in entry.component_ids),
            *(
                entity_id
                for rule in key.question_counts
                for entity_id in rule.ids
                if entity_id not in named_documents
            ),
        ]
    )
    base_document_ids = {document.document_id for document in base.documents}
    document_ids = [
        document_id for document_id in named_documents if document_id not in base_document_ids
    ]
    return build_package(
        components=[
            component.model_copy(
                update={
                    "id": component_id,
                    "persist_ref": persist_ref(component_id),
                    "name": component_id,
                    "full_path": component_id,
                }
            )
            for component_id in component_ids
        ],
        documents=[
            *base.documents,
            *(
                part.model_copy(
                    update={
                        "document_id": document_id,
                        "file_name": document_id,
                        "path": document_id,
                    }
                )
                for document_id in document_ids
            ),
        ],
        manifest=Manifest(
            entries=[
                *base.manifest.entries,
                *(
                    part_entry.model_copy(
                        update={"document_id": document_id, "vault_path": f"/Designs/{document_id}"}
                    )
                    for document_id in document_ids
                ),
            ],
            discrepancies=[],
        ),
        holes=[],
        fasteners=[],
        gaps=[],
    )


# --- the oracle and the null review (scoring.md 9.2; RF-58) ----------------------------------


def oracle_review(
    key: AnswerKey,
    package: EvidencePackage,
    folder: Path,
    *,
    profile: StandardsProfile | None = None,
) -> ReviewSession:
    """Write the oracle review of `key` on `package` into `folder` and return its session: one
    finding per known defect, in key order, and the one synthetic step its demonstrated findings
    cite, held only when one of them needs it; one coverage row per expected-coverage entry; and
    per question-count rule with `min` 1, in key order, one question of its kind (`questions.md`
    8). `profile` is read only to classify the parts for a `part_roles` rule."""
    ids = FindingIdAllocator()
    findings = [_oracle_finding(defect, package, next(ids)) for defect in key.known_defects]
    demonstrated = any(finding.status == "demonstrated" for finding in findings)
    steps = [ORACLE_STEP] if demonstrated else []
    session = _session(package, "oracle", steps=steps, findings=findings)
    context = context_for(package)
    context.session = session
    context.tool_results_dir = folder / TOOL_RESULTS_DIR_NAME
    for entry in key.expected_coverage:
        context.record_coverage(
            entry.statuses[0],
            CoverageItem(
                check=entry.item, scope=CoverageScope(), reason=COVERAGE_REASON, error=None
            ),
        )
    for rule in key.question_counts:
        if rule.min == 1:
            _ask_once(rule, context, profile)
    return _write_review(session, folder)


def _ask_once(rule: QuestionCount, context: ToolContext, profile: StandardsProfile | None) -> None:
    """The one question a rule with `min` 1 counts: the part-roles question, recorded as
    `start_review` asks it over the roles it attaches, or one recorded call of the real
    `request_evidence` naming the rule's item and its ids (the item alone when it names none)."""
    if rule.part_roles:
        classify_part_roles(context, profile, None)
        if ask_part_roles(context) is None:
            raise ValueError(
                f"{rule.id}: the roles of package {context.ir.package_id} ask no part-roles "
                "question under this profile, so the oracle cannot ask the one the rule counts"
            )
        return
    ToolRegistry().dispatch(context).call(
        REQUEST_TOOL,
        {
            "what": f"The value {rule.id} counts one question for.",
            "why": f"The oracle asks the one question {rule.id} expects.",
            "entity_ids": list(rule.ids),
            "blocks": rule.item,
        },
    )


def null_review(package: EvidencePackage, folder: Path) -> ReviewSession:
    """Write the null review of `package` into `folder` and return its session: no step, finding,
    coverage row or request."""
    return _write_review(_session(package, "null", steps=[], findings=[]), folder)


def _oracle_finding(defect: KnownDefect, package: EvidencePackage, finding_id: str) -> Finding:
    """The oracle's finding for `defect` (`scoring.md` 9.2)."""
    inputs, drawing_locations = _first_item_references(defect, package)
    return build_finding(
        finding_id=finding_id,
        check=_oracle_check(defect.check),
        title=f"Oracle finding for {defect.id}",
        status=defect.expected_status,
        severity="medium",
        package=package,
        configuration=package.design.active_configuration,
        observed=defect.description,
        requirement=f"{defect.id}, as its answer key states it",
        recommended_action="None: a synthetic review written from the answer key.",
        component_ids=defect.component_ids,
        drawing_locations=drawing_locations,
        document_ids=[] if defect.component_ids else defect.document_ids,
        inputs=inputs,
        tool_result_ids=[ORACLE_STEP.index] if defect.expected_status == "demonstrated" else [],
        coverage_limits=[UNRESOLVED_LIMIT] if defect.expected_status == "unresolved" else [],
        source="model",
    )


def _oracle_check(pattern: str) -> str:
    """The check an oracle finding states: the entry's exact check, or a family's id with
    `.oracle` appended, which the family covers and no rule writes."""
    return f"{pattern.removesuffix('.*')}.oracle" if is_family(pattern) else pattern


def _first_item_references(
    defect: KnownDefect, package: EvidencePackage
) -> tuple[list[Dimension | str], list[SourceRef]]:
    """A reference-keyed defect's first covered item as a finding names it (`scoring.md` 2.3):
    its ids as strings, then its dimensions resolved through `resolve_dimension`, whose sources
    are the finding's drawing locations; nothing for a defect on any other check."""
    if not defect.references:
        return [], []
    element = defect.references[0]
    dimensions = [
        resolve_dimension(package, dimension.model_dump())
        for dimension in _dimensions_named(element)
    ]
    entity_ids = [entity_id for _, entity_id in _entities_named(element)]
    return [*entity_ids, *dimensions], [dimension.source for dimension in dimensions]


def _session(
    package: EvidencePackage,
    review: str,
    *,
    steps: list[InvestigationStep],
    findings: list[Finding],
) -> ReviewSession:
    """A synthetic review's session, carrying `origin_marks` as every new session does."""
    return ReviewSession(
        session_id=uuid5(NAMESPACE_URL, f"{package.package_id}/{review}"),
        package_id=package.package_id,
        design_id=package.design.design_id,
        started_at=STARTED_AT,
        model=review,
        origin_marks=ORIGIN_MARKS_VERSION,
        steps=steps,
        findings=findings,
        timing=TIMING,
    )


def _write_review(session: ReviewSession, folder: Path) -> ReviewSession:
    """Write `session` into `folder` as a run leaves a package folder: `session.json`, and
    `events.jsonl` holding its one `session.started` event through the product's `EventSink`.
    A folder already holding either file is refused: the sink appends, so a second review written
    there would leave a stream of two."""
    for name in (SESSION_FILE_NAME, EVENTS_FILE_NAME):
        if (folder / name).exists():
            raise FileExistsError(f"{folder / name} exists; write each review into its own folder")
    save_session(session, folder / SESSION_FILE_NAME)
    EventSink(folder / EVENTS_FILE_NAME, clock=lambda: session.started_at).emit(
        "session.started",
        {
            "session_id": str(session.session_id),
            "package_id": str(session.package_id),
            "model": session.model,
        },
    )
    return session


# --- SC-001 and SC-002 (scoring.md 9.2) ------------------------------------------------------


def assert_oracle_matches_only_its_own_defects(key: AnswerKey, oracle: ReviewSession) -> None:
    """SC-002: the oracle holds one finding per known defect, in key order, and each matches its
    own defect and no other, through the one matcher."""
    assert len(oracle.findings) == len(key.known_defects), (
        f"{key.package_id}: the oracle holds {len(oracle.findings)} findings for "
        f"{len(key.known_defects)} known defects"
    )
    for finding, defect in zip(oracle.findings, key.known_defects, strict=True):
        matched = [other.id for other in key.known_defects if matching.matches(finding, other)]
        assert matched == [defect.id], (
            f"{key.package_id}: the oracle finding for {defect.id} matches {matched}"
        )


def assert_oracle_and_null(
    key: AnswerKey,
    package: EvidencePackage,
    folder: Path,
    *,
    profile: StandardsProfile | None = None,
) -> tuple[PackageScore, PackageScore]:
    """Write the oracle and null reviews of `key` on `package` into `folder/oracle` and
    `folder/null`, score each through the scorer's per-package function, assert SC-002 and SC-001
    on every column, and return the two scores, oracle first. `profile` reaches `oracle_review`.

    SC-001: the oracle detects every known defect, credited at its expected status or flagged when
    expected unresolved, and every failure column the key grades reads zero: no miss, no false
    alarm, no contradiction, nothing flagged below expected, no status mismatch, nothing cleared,
    no forbidden or withdrawn forbidden hit, no tuned-on false alarm, no coverage mismatch, and no
    re-ask, repeat, unanswerable or unmatched request or question-count miss. The null review
    detects none and raises no false alarm; its coverage reads not reported, a mismatch for each
    expected-coverage entry, and each rule with `min` 1 is a miss. A column reads `null`, its
    reason in `not_assessed`, exactly when the key has no entry of the list it reads, and the two
    answer-log columns always, so a stream or a stored result the builder failed to write fails
    here instead of reading "not assessed". Recall is 1 for the oracle and 0 for the null wherever
    the key has a known defect, and `null` for both where it has none (FR-006)."""
    oracle_session = oracle_review(key, package, folder / "oracle", profile=profile)
    null_review(package, folder / "null")
    assert_oracle_matches_only_its_own_defects(key, oracle_session)

    oracle, null = (_score(key, folder / review, package) for review in ("oracle", "null"))
    defect_ids = [defect.id for defect in key.known_defects]
    graded_conditions: list[str] | None = [] if key.correct_conditions else None
    graded_forbidden: list[str] | None = [] if key.forbidden else None
    graded_unanswerable: list[object] | None = [] if key.unanswerable_requests else None
    unassessed = sorted(
        [
            *(
                column
                for name, columns in COLUMNS_BY_KEY_LIST.items()
                if not getattr(key, name)
                for column in columns
            ),
            *ANSWER_LOG_COLUMNS,
        ]
    )
    common: dict[str, object] = {
        "false_alarm_finding_ids": [],
        "contradicted_condition_ids": graded_conditions,
        "confirmed_condition_ids": graded_conditions,
        "flagged_below_expected_defect_ids": [],
        "status_mismatch_defect_ids": [],
        "cleared_defect_ids": [],
        "forbidden_hit_finding_ids": graded_forbidden,
        "withdrawn_forbidden_hit_finding_ids": graded_forbidden,
        "tuned_on_false_alarm_finding_ids": [],
        "re_asks": [],
        "open_repeats": [],
        "unanswerable_requests": graded_unanswerable,
        "unmatched_requests": [],
        "unscripted_questions": None,
        "bound_reached": None,
        "not_assessed": unassessed,
    }
    assert _view(oracle, key) == {
        **common,
        "matched_defect_ids": defect_ids,
        "flagged_defect_ids": [
            defect.id for defect in key.known_defects if defect.expected_status == "unresolved"
        ],
        "missed_defect_ids": [],
        "coverage_mismatches": [] if key.expected_coverage else None,
        "question_count_misses": [] if key.question_counts else None,
        "recall": _expected_recall(key, 1.0),
    }, f"{key.package_id}: the oracle review"
    assert _view(null, key) == {
        **common,
        "matched_defect_ids": [],
        "flagged_defect_ids": [],
        "missed_defect_ids": defect_ids,
        "coverage_mismatches": (
            [
                {"entry": entry.id, "item": entry.item, "read": "not_reported"}
                for entry in key.expected_coverage
            ]
            if key.expected_coverage
            else None
        ),
        "question_count_misses": (
            [rule.id for rule in key.question_counts if rule.min == 1]
            if key.question_counts
            else None
        ),
        "recall": _expected_recall(key, 0.0),
    }, f"{key.package_id}: the null review"
    return oracle, null


def _score(key: AnswerKey, package_dir: Path, package: EvidencePackage) -> PackageScore:
    """One review folder's score, as `score_run` scores each package of a run."""
    return scorecard._score_package(
        package_dir,
        package_id=key.package_id,
        held_out=key.holds_held_out(),
        answer_key=key,
        package=package,
        words=load_words(),
    )


def _view(score: PackageScore, key: AnswerKey) -> dict[str, object]:
    """What SC-001 reads of one review's score: its columns, its coverage mismatches as plain
    rows, the rules its question counts miss, the columns it does not assess, and the recall
    figures a run of this package alone aggregates."""
    aggregate = scorecard._aggregate([score], [key])
    by_producer = aggregate.recall_by_producer
    mismatches = score.coverage_mismatches
    counts = score.question_counts
    return {
        **{column: getattr(score, column) for column in SC_001_COLUMNS},
        "coverage_mismatches": (
            None if mismatches is None else [mismatch.model_dump() for mismatch in mismatches]
        ),
        "question_count_misses": (
            None if counts is None else [row.entry for row in counts if row.missed]
        ),
        "not_assessed": sorted(score.not_assessed),
        "recall": {
            "held_out": aggregate.recall,
            **{
                f"{producer}.{tag}": getattr(getattr(by_producer, producer), tag)
                for producer in get_args(Producer)
                for tag in get_args(Tag)
            },
        },
    }


def _expected_recall(key: AnswerKey, detected: float) -> dict[str, float | None]:
    """`detected` for each recall figure over at least one of the key's known defects, `None` for
    each over none: held-out recall, then by producer and tag."""
    defects = key.known_defects

    def figure(selected: list[KnownDefect]) -> float | None:
        return detected if selected else None

    return {
        "held_out": figure([defect for defect in defects if defect.tag == "held_out"]),
        **{
            f"{producer}.{tag}": figure(
                [defect for defect in defects if (defect.producer, defect.tag) == (producer, tag)]
            )
            for producer in get_args(Producer)
            for tag in get_args(Tag)
        },
    }
