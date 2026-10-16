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

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any, get_args
from uuid import NAMESPACE_URL, uuid5

from swreview.agent.checklist import load_checklist
from swreview.agent.events import EVENTS_FILE_NAME, EventSink
from swreview.agent.runner import SESSION_FILE_NAME, ask_part_roles, classify_part_roles
from swreview.benchmark import answers, matching, prices, questions, scorecard
from swreview.benchmark.answer_key import _dimensions_named, _entities_named, load_answer_key
from swreview.benchmark.answer_key_model import (
    AnswerKey,
    CorrectCondition,
    KnownDefect,
    Producer,
    QuestionCount,
    Tag,
    is_family,
)
from swreview.benchmark.questions import REQUEST_TOOL
from swreview.benchmark.scorecard import PackageScore
from swreview.benchmark.sets import REPO_ROOT, BenchmarkPackageRef
from swreview.checks.standards.profile import StandardsProfile, load_profile
from swreview.findings import Finding, FindingIdAllocator, build_finding
from swreview.ir.loader import load_package
from swreview.ir.models import Dimension, EvidencePackage, Manifest, SourceRef
from swreview.report.session import (
    ORIGIN_MARKS_VERSION,
    CoverageItem,
    CoverageScope,
    EvidenceRequestIdAllocator,
    InvestigationStep,
    ReviewSession,
    Timing,
    save_session,
)
from swreview.report.summary import load_words
from swreview.tools.context import ToolContext, context_for
from swreview.tools.refs import resolve_dimension
from swreview.tools.registry import TOOL_RESULTS_DIR_NAME, ToolRegistry
from tests.support.mechanical import as_committed
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


def _score(
    key: AnswerKey, package_dir: Path, package: EvidencePackage,
    *, run_status: dict[str, str | None] | None = None,
) -> PackageScore:
    """One review folder's score, as `score_run` scores each package of a run."""
    return scorecard._score_package(
        package_dir,
        package_id=key.package_id,
        held_out=key.holds_held_out(),
        answer_key=key,
        package=package,
        words=load_words(),
        run_status=(
            {"kind": "completed", "class": None, "stop_reason": None}
            if run_status is None else run_status
        ),
        cost=prices.SYNTHETIC_COST,
        served_models=[],
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


# --- the golden view and version record (T154) -----------------------------------------------

GOLDEN_EXCLUDED = (
    "session_id",
    "baseline_minutes",
    "assisted_minutes",
    "unattended_runtime_minutes",
    "net_saved_minutes",
    "usage",
    "round_trips",
    "cached_input_share",
    "wall_clock_s",
    "seconds_to_first_finding",
    "tool_calls_by_name",
    "cost",
    "served_models",
)
GOLDEN_IDENTITY = ("package_id", "held_out", "graded_items")


def golden_view(score: PackageScore) -> dict[str, Any]:
    """Every scorer-written package field, serialized as a snapshot can read it."""
    return score.model_dump(mode="json", exclude=set(GOLDEN_EXCLUDED))


def goldens_sha256(folder: Path) -> str:
    """Hash paths and committed bytes in sorted path order (scoring.md 9.4, INT-12)."""
    digest = sha256()
    for path in sorted(folder.rglob("*.yml")):
        digest.update(path.relative_to(folder).as_posix().encode("utf-8") + b"\0")
        digest.update(as_committed(path) + b"\0")
    return digest.hexdigest()


def version_record_failures(rows: list[dict[str, Any]], digest: str, version: int) -> list[str]:
    """The record's two-way rule: a rules bump and a golden move accompany one another."""
    if not rows:
        return ["the version record holds no row"]
    failures = []
    if rows[-1].get("version") != version:
        failures.append(f"last version is not SCORING_RULES_VERSION {version}")
    if rows[-1].get("goldens_sha256") != digest:
        failures.append(f"last golden digest is not {digest}")
    seen: set[str] = set()
    for index, row in enumerate(rows):
        previous = rows[index - 1] if index else None
        if previous and row.get("version") != previous.get("version", 0) + 1:
            failures.append(f"row {index + 1}: versions must rise by one")
        unchanged = row.get("goldens_unchanged") is True
        if unchanged:
            reason = row.get("reason")
            if not isinstance(reason, str) or not reason.strip():
                failures.append(f"row {index + 1}: unchanged goldens need a reason")
            if not previous or row.get("goldens_sha256") != previous.get("goldens_sha256"):
                failures.append(f"row {index + 1}: declared unchanged goldens differ")
        elif row.get("goldens_sha256") in seen:
            failures.append(f"row {index + 1}: shared digest needs goldens_unchanged")
        seen.add(row.get("goldens_sha256", ""))
    return failures


@dataclass(frozen=True)
class Change:
    """An explicit before/after value for a status, origin, bucket mix or assessed column."""

    before: Any
    after: Any


@dataclass(frozen=True)
class Probe:
    name: str
    case: str
    base: str
    behaviour: Callable[[Any], None]
    moves: Mapping[str, int | Change]
    entry: str | None = None
    rule: str | None = None
    overlay: str | None = None


def _case(entry: BenchmarkPackageRef) -> tuple[AnswerKey, EvidencePackage]:
    package = load_package(entry.path).package
    if entry.key is None:
        raise ValueError(f"{entry.package_id}: its committed entry names no key")
    return load_answer_key(
        entry.key, package=package, checklist=load_checklist(), words=load_words()
    ), package


def validate_probe(probe: Probe, entries: Mapping[str, BenchmarkPackageRef]) -> None:
    """Keep a probe bound to real corpus entries, even when its base has a named overlay."""
    if probe.case not in entries:
        raise ValueError(f"probe {probe.name}: case {probe.case}, entry {probe.entry}, has gone")
    key, _ = _case(entries[probe.case])
    named = {
        item.id
        for field in (
            "known_defects",
            "correct_conditions",
            "forbidden",
            "expected_coverage",
            "unanswerable_requests",
            "question_counts",
        )
        for item in getattr(key, field)
    }
    if probe.entry is not None and probe.entry not in named:
        raise ValueError(f"probe {probe.name}: case {probe.case}, entry {probe.entry}, has gone")


def assert_probe_delta(probe: Probe, base: dict[str, Any], changed: dict[str, Any]) -> None:
    """Check independently declared deltas before accepting a regenerated snapshot."""
    moved = {name for name in base if base[name] != changed[name]}
    assert moved == set(probe.moves), (
        f"{probe.name}: moved {sorted(moved)}, declared {sorted(probe.moves)}"
    )
    for name, delta in probe.moves.items():
        before, after = base[name], changed[name]
        if isinstance(delta, Change):
            assert (before, after) == (delta.before, delta.after), (
                f"{probe.name}: {name}: expected {delta}, got {before!r} -> {after!r}"
            )
        else:
            if isinstance(before, list) and isinstance(after, list):
                actual = len(after) - len(before)
            elif isinstance(before, dict) and isinstance(after, dict):
                actual = len(after) - len(before)
            else:
                actual = after - before
            assert actual == delta, f"{probe.name}: {name}: delta {actual}, expected {delta}"


PROBE_KEY_OVERLAYS = {
    "condition-and-forbidden": (
        "mir-sitting has a forbidden rms family on the pin but no overlapping condition; "
        "this isolated base adds a correct rms.sketches.fully_defined condition on that pin."
    ),
    "minimum-one-item-question": (
        "kalo-fit-1's item rule permits zero questions; this isolated base raises its minimum "
        "to one so an item question-count miss below the minimum can be probed."
    ),
    "coverage-expects-checked": (
        "Every corpus coverage entry allows unresolved; this isolated mir-sitting base "
        "expects checked on CV-1 so unresolved can be a mismatching reading."
    ),
}


def _overlay_key(key: AnswerKey, name: str | None) -> AnswerKey:
    """Three disclosed fixture gaps, never edits to a committed key or its corpus identity."""
    if name is None:
        return key
    if name == "condition-and-forbidden" and key.package_id == "mir-sitting":
        forbidden = next(entry for entry in key.forbidden if entry.id == "FB-1")
        if any(entry.id == "C-1" for entry in key.correct_conditions):
            raise ValueError("mir-sitting: overlay condition C-1 already exists in its real key")
        condition = CorrectCondition(
            id="C-1",
            tag="tuned_on",
            description="The probe-only pin sketch condition.",
            check="rms.sketches.fully_defined",
            component_ids=forbidden.component_ids,
            document_ids=forbidden.document_ids,
        )
        return key.model_copy(update={"correct_conditions": [*key.correct_conditions, condition]})
    if name == "minimum-one-item-question" and key.package_id == "kalo-fit-1":
        return key.model_copy(
            update={
                "question_counts": [
                    rule.model_copy(update={"min": 1}) if rule.id == "Q-1" else rule
                    for rule in key.question_counts
                ]
            }
        )
    if name == "coverage-expects-checked" and key.package_id == "mir-sitting":
        return key.model_copy(
            update={
                "expected_coverage": [
                    entry.model_copy(update={"statuses": ["checked"]})
                    if entry.id == "CV-1"
                    else entry
                    for entry in key.expected_coverage
                ]
            }
        )
    raise ValueError(f"{key.package_id}: unknown or inapplicable probe key overlay {name}")


@dataclass
class ProbeReview:
    """One committed case's synthetic review; calls still use the product's real dispatch."""

    key: AnswerKey
    package: EvidencePackage
    folder: Path
    session: ReviewSession

    def __post_init__(self) -> None:
        self.run_status: dict[str, str | None] = {
            "kind": "completed", "class": None, "stop_reason": None,
        }
        self.context = context_for(self.package)
        self.context.session = self.session
        self.context.evidence_request_ids = EvidenceRequestIdAllocator(
            start=1
            + max(
                (int(request.id.removeprefix("ER-")) for request in self.session.evidence_requests),
                default=0,
            )
        )
        self.context.tool_results_dir = self.folder / TOOL_RESULTS_DIR_NAME
        self.sink = EventSink(self.folder / EVENTS_FILE_NAME, clock=lambda: STARTED_AT)
        self.context.emit = self.sink.emit
        self.dispatch = ToolRegistry().dispatch(self.context)
        self.points: list[answers.AnswerPoint] = []

    def entry(self, identifier: str):
        for field in (
            "known_defects",
            "correct_conditions",
            "forbidden",
            "expected_coverage",
            "unanswerable_requests",
            "question_counts",
        ):
            for item in getattr(self.key, field):
                if item.id == identifier:
                    return item
        raise ValueError(f"{self.key.package_id}: entry {identifier} has gone")

    def add(
        self, identifier: str, status: str = "suspected", *, check: str | None = None
    ) -> Finding:
        entry = self.entry(identifier)
        pattern = check or getattr(entry, "check", None) or entry.checks[0]
        defect = KnownDefect.model_construct(
            id=entry.id,
            tag=entry.tag,
            description=entry.description,
            check=pattern,
            component_ids=entry.component_ids,
            document_ids=entry.document_ids,
            producer="model",
            expected_status="unresolved" if status == "unresolved" else "suspected",
            references=getattr(entry, "references", []),
        )
        finding = _oracle_finding(defect, self.package, f"F-{901 + len(self.session.findings):03}")
        finding = finding.model_copy(update={"status": status})
        self.context.record_finding(finding)
        return finding

    def replace_finding(self, identifier: str, **updates: Any) -> None:
        defect = self.entry(identifier)
        index = next(
            i
            for i, finding in enumerate(self.session.findings)
            if matching.matches(finding, defect)
        )
        self.session.findings[index] = self.session.findings[index].model_copy(update=updates)

    def remove(self, identifier: str) -> None:
        entry = self.entry(identifier)
        self.session.findings[:] = [
            finding for finding in self.session.findings if not matching.matches(finding, entry)
        ]

    def ask(self, *ids: str, item: str | None = None):
        arguments = {
            "what": "A fictional probe value.",
            "why": "The probe needs evidence.",
            "entity_ids": list(ids),
        }
        if item is not None:
            arguments["blocks"] = item
        self.dispatch.call(REQUEST_TOOL, arguments)
        return self.session.steps[-1]

    def answer(self, *request_ids: str, unscripted=()) -> None:
        for request_id in request_ids:
            request = next(one for one in self.session.evidence_requests if one.id == request_id)
            request.status = "answered"
            request.answer = "press fit"
            request.answered_at = STARTED_AT + timedelta(minutes=1 + len(self.points))
        self.points.append(
            answers.AnswerPoint(
                after_turn=len(self.points),
                steps_before=len(self.session.steps),
                sent=[
                    answers.AnswerSent(request_id=request_id, entry=f"A-{i + 1}")
                    for i, request_id in enumerate(request_ids)
                ],
                unscripted=list(unscripted),
                held=[],
            )
        )

    def log(self, ended: str = "no_open_questions") -> None:
        answers.write_answer_log(
            self.folder,
            answers.AnswerLog(
                answer_log_version=answers.ANSWER_LOG_VERSION,
                points=self.points,
                ended=ended,
                last_turn_end="end",
                unused_entries=[],
            ),
        )

    def save(self) -> None:
        save_session(self.session, self.folder / SESSION_FILE_NAME)


def probe_scores(
    probe: Probe, entry: BenchmarkPackageRef, folder: Path
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Score a base and one behaviour under the same key, including any disclosed overlay."""
    key, package = _case(entry)
    key = _overlay_key(key, probe.overlay)
    views = []
    for label in ("base", "probe"):
        target = folder / label
        if probe.base == "oracle":
            session = oracle_review(
                key,
                package,
                target,
                profile=load_profile(REPO_ROOT / "config" / "standards.example.yaml"),
            )
        elif probe.base == "null":
            session = null_review(package, target)
        else:
            raise ValueError(f"{probe.name}: unknown base {probe.base}")
        if label == "probe":
            review = ProbeReview(key, package, target, session)
            probe.behaviour(review)
            review.save()
        views.append(golden_view(_score(
            key, target, package, run_status=review.run_status if label == "probe" else None,
        )))
    return views[0], views[1]


# --- scoring behaviours (T155) ---------------------------------------------------------------


def _alarm(review: ProbeReview, *, origin: str = "model") -> None:
    finding = review.add("D-1", check="provenance.probe")
    updates: dict[str, Any] = {"source": "model" if origin in ("model", "carried") else "code"}
    if origin == "carried":
        updates["carried_over_from"] = uuid5(NAMESPACE_URL, "probe/earlier-session")
    elif origin == "unknown":
        review.session.origin_marks = None
    elif origin in ("prerun", "regrade", "code_only_call", "configured_check"):
        step = ORACLE_STEP.model_copy(
            update={
                "index": len(review.session.steps),
                "tool": "check_hygiene" if origin != "configured_check" else "check_fit",
                "origin_mark": origin if origin in ("prerun", "regrade") else None,
            }
        )
        review.session.steps.append(step)
        updates["tool_result_ids"] = [step.index]
    elif origin == "setup":
        updates["tool_result_ids"] = []
    review.session.findings[-1] = finding.model_copy(update=updates)


def _status(review: ProbeReview, entry: str, status: str) -> None:
    review.replace_finding(
        entry, status=status, coverage_limits=[UNRESOLVED_LIMIT] if status == "unresolved" else []
    )


def _clear(review: ProbeReview, entry: str, *, beside_credit: bool = False) -> None:
    if beside_credit:
        review.add(entry, "checked_within_scope")
    else:
        _status(review, entry, "checked_within_scope")


def _coverage(review: ProbeReview, bucket: str) -> None:
    entry = review.entry("CV-1")
    review.context.withdraw_coverage((entry.item,), tuple(scorecard.Coverage.model_fields))
    if bucket != "not_reported":
        review.context.record_coverage(
            bucket,
            CoverageItem(
                check=entry.item,
                scope=CoverageScope(),
                reason="The probe's coverage reading.",
                error=None,
            ),
        )


def _unresolved(review: ProbeReview, *, withheld: bool) -> None:
    check = "mass.material_assigned"
    if withheld:
        review.session.withheld_checks.append(check)
    review.context.record_coverage(
        "unresolved",
        CoverageItem(
            check=check,
            scope=CoverageScope(),
            reason="The probe's unresolved coverage.",
            error=None,
        ),
    )


def _reference_miss(review: ProbeReview, identifier: str, how: str) -> None:
    defect = review.entry(identifier)
    finding = next(one for one in review.session.findings if matching.matches(one, defect))
    inputs = list(finding.inputs)
    if how == "extra-stack-contributor":
        existing = {
            (one.source.document_id, one.source.annotation)
            for one in inputs
            if isinstance(one, Dimension)
        }
        inputs.append(
            next(
                one
                for sheet in review.package.drawings
                for one in sheet.dimensions
                if (one.source.document_id, one.source.annotation) not in existing
            )
        )
    elif how == "role-swapped-fit":
        inputs.reverse()
    elif how == "another-pair":
        first = next(one for one in inputs if isinstance(one, str) and one.startswith("hol:"))
        original = next(one for one in review.package.holes if one.id == first)
        replacement = next(
            one.id
            for one in review.package.holes
            if one.id != first and one.component_id == original.component_id
        )
        inputs = [replacement if one == first else one for one in inputs]
    review.replace_finding(identifier, inputs=inputs)


def _doc_finding(review: ProbeReview, *, location: bool, component: bool = False) -> None:
    finding = review.add("D-2", "suspected")
    updates = {}
    if location:
        updates["drawing_locations"] = [
            SourceRef(document_id=review.entry("D-2").document_ids[0], sheet="Sheet1")
        ]
    if component:
        updates["component_ids"] = [review.package.components[0].id]
    review.session.findings[-1] = finding.model_copy(update=updates)


def _withdrawn(review: ProbeReview) -> None:
    """The real regrade reconciliation writes both the body and its withdrawal event."""
    from swreview.agent.providers.fake import FakeProvider
    from swreview.agent.runner import ReviewRun

    step = ORACLE_STEP.model_copy(
        update={"index": len(review.session.steps), "tool": "check_rms_part"}
    )
    review.session.steps.append(step)
    finding = review.add("FB-1", check="rms.sketches.fully_defined")
    finding = finding.model_copy(update={"source": "code", "tool_result_ids": [step.index]})
    review.session.findings[-1] = finding
    review.sink.emit("finding", review.context.finding_body(finding))
    run = ReviewRun(
        context=review.context,
        provider=FakeProvider(script=[], model="fake-scripted"),
        tools=review.dispatch,
        system="synthetic probe",
        sink=review.sink,
        out_dir=review.folder,
        effort="low",
        max_steps=10,
        dispatch=review.dispatch,
    )
    run._reconcile_restated(
        len(review.session.findings),
        {step.index: step.tool},
        [],
        {step.tool: "The real probe regrade no longer produces this finding."},
    )


def _unreadable(review: ProbeReview) -> None:
    with (review.folder / EVENTS_FILE_NAME).open("a", encoding="utf-8", newline="\n") as stream:
        stream.write("{not json\n")


def _part_overlap(review: ProbeReview) -> None:
    finding = review.add("D-1")
    review.session.findings[-1] = finding.model_copy(
        update={"component_ids": review.entry("D-1").component_ids[:1]}
    )


_DETECT = {
    "matched_defect_ids": 1,
    "missed_defect_ids": -1,
    "missed_known_defects": -1,
    "valid_findings": 1,
    "finding_origins": 1,
}
_ALARM = {"false_alarms": 1, "false_alarm_finding_ids": 1, "finding_origins": 1}
_LOST_TO_ALARM = {
    "matched_defect_ids": -1,
    "valid_findings": -1,
    "missed_defect_ids": 1,
    "missed_known_defects": 1,
    "false_alarms": 1,
    "false_alarm_finding_ids": 1,
}


def _scoring_probes() -> list[Probe]:
    probes = [
        Probe(
            "behavioural-stop", "kalo-1", "oracle",
            lambda r: r.run_status.update(kind="behavioural", **{"class": "max_steps"}),
            {"run_status": Change(
                {"kind": "completed", "class": None, "stop_reason": None},
                {"kind": "behavioural", "class": "max_steps", "stop_reason": None},
            )},
        ),
        Probe("credited", "kalo-1", "null", lambda r: r.add("D-1"), _DETECT, "D-1", "exact-check"),
        Probe(
            "flagged",
            "kalo-fit-2",
            "null",
            lambda r: r.add("D-1", "unresolved"),
            {name: delta for name, delta in _DETECT.items() if name != "valid_findings"}
            | {"flagged_defect_ids": 1, "unresolved_count": 1},
            "D-1",
        ),
        Probe(
            "status-mismatch",
            "kalo-fit-2",
            "oracle",
            lambda r: _status(r, "D-1", "suspected"),
            {
                "flagged_defect_ids": -1,
                "unresolved_count": -1,
                "valid_findings": 1,
                "status_mismatch_defect_ids": 1,
            },
            "D-1",
        ),
        Probe(
            "flagged-below-expected",
            "kalo-1",
            "oracle",
            lambda r: _status(r, "D-1", "unresolved"),
            {
                "matched_defect_ids": -1,
                "valid_findings": -1,
                "flagged_below_expected_defect_ids": 1,
                "unresolved_count": 1,
            },
            "D-1",
        ),
        Probe(
            "cleared-alone",
            "kalo-1",
            "oracle",
            lambda r: _clear(r, "D-1"),
            {"matched_defect_ids": -1, "valid_findings": -1, "cleared_defect_ids": 1},
            "D-1",
        ),
        Probe(
            "cleared-beside-credit",
            "kalo-1",
            "oracle",
            lambda r: _clear(r, "D-1", beside_credit=True),
            {"cleared_defect_ids": 1, "finding_origins": 1},
            "D-1",
        ),
        Probe(
            "missed",
            "kalo-1",
            "oracle",
            lambda r: r.remove("D-1"),
            {
                "matched_defect_ids": -1,
                "valid_findings": -1,
                "missed_defect_ids": 1,
                "missed_known_defects": 1,
                "finding_origins": -1,
            },
            "D-1",
        ),
        Probe("plain-false-alarm", "kalo-1", "null", _alarm, _ALARM, "D-1"),
        Probe(
            "contradiction",
            "kalo-fit-clean",
            "null",
            lambda r: r.add("C-1"),
            _ALARM | {"contradicted_condition_ids": 1, "tuned_on_false_alarm_finding_ids": 1},
            "C-1",
        ),
        Probe(
            "confirmation",
            "kalo-fit-clean",
            "null",
            lambda r: r.add("C-1", "checked_within_scope"),
            {"confirmed_condition_ids": 1, "finding_origins": 1},
            "C-1",
        ),
        Probe(
            "forbidden-hit",
            "kalo-contact",
            "null",
            lambda r: r.add("FB-1"),
            _ALARM | {"forbidden_hit_finding_ids": 1, "tuned_on_false_alarm_finding_ids": 1},
            "FB-1",
        ),
        Probe(
            "tuned-on-false-alarm",
            "kalo-fit-clean",
            "null",
            lambda r: r.add("C-1"),
            _ALARM | {"contradicted_condition_ids": 1, "tuned_on_false_alarm_finding_ids": 1},
            "C-1",
        ),
        Probe(
            "withdrawn-forbidden-hit",
            "mir-sitting",
            "oracle",
            _withdrawn,
            {"withdrawn_forbidden_hit_finding_ids": 1, "finding_origins": 1},
            "FB-1",
            "withdrawn-stream",
        ),
        Probe(
            "condition-and-forbidden",
            "mir-sitting",
            "null",
            lambda r: r.add("C-1"),
            _ALARM
            | {
                "forbidden_hit_finding_ids": 1,
                "tuned_on_false_alarm_finding_ids": 1,
                "contradicted_condition_ids": 1,
            },
            "FB-1",
            "condition-and-forbidden",
            "condition-and-forbidden",
        ),
        Probe(
            "family-at-depth",
            "mir-sitting",
            "oracle",
            lambda r: r.add("FB-1", check="rms.sketches.depth.probe"),
            _ALARM | {"forbidden_hit_finding_ids": 1, "tuned_on_false_alarm_finding_ids": 1},
            "FB-1",
            "family-at-depth",
        ),
        Probe(
            "family-boundary",
            "mir-sitting",
            "oracle",
            lambda r: r.add("FB-1", check="rmsx.probe"),
            _ALARM,
            "FB-1",
            "family-boundary",
        ),
        Probe(
            "sibling-rule",
            "kalo-1",
            "oracle",
            lambda r: r.replace_finding("D-1", check="fastener.engagement"),
            _LOST_TO_ALARM,
            "D-1",
            "sibling-rule",
        ),
        Probe("part-overlap", "kalo-1", "null", _part_overlap, _DETECT, "D-1", "part-overlap"),
        Probe(
            "drawing-location-overlap",
            "kalo-2",
            "null",
            lambda r: _doc_finding(r, location=True),
            _DETECT | {"status_mismatch_defect_ids": 1},
            "D-2",
            "drawing-location-overlap",
        ),
        Probe(
            "provenance-document-overlap",
            "kalo-2",
            "null",
            lambda r: _doc_finding(r, location=False),
            _DETECT | {"status_mismatch_defect_ids": 1},
            "D-2",
            "provenance-document-overlap",
        ),
        Probe(
            "component-provenance-not-read",
            "kalo-2",
            "null",
            lambda r: _doc_finding(r, location=False, component=True),
            _ALARM,
            "D-2",
            "component-provenance-not-read",
        ),
        Probe(
            "role-swapped-fit",
            "kalo-fit-1",
            "oracle",
            lambda r: _reference_miss(r, "D-1", "role-swapped-fit"),
            {},
            "D-1",
            "role-swapped-fit",
        ),
        Probe(
            "extra-stack-contributor",
            "brun-1",
            "oracle",
            lambda r: _reference_miss(r, "D-1", "extra-stack-contributor"),
            _LOST_TO_ALARM,
            "D-1",
            "extra-stack-contributor",
        ),
        Probe(
            "another-pair",
            "kalo-1",
            "oracle",
            lambda r: _reference_miss(r, "D-1", "another-pair"),
            _LOST_TO_ALARM,
            "D-1",
            "another-pair",
        ),
    ]
    for origin in (
        "prerun",
        "regrade",
        "code_only_call",
        "configured_check",
        "model",
        "carried",
        "setup",
        "unknown",
    ):
        probes.append(
            Probe(
                f"origin-{origin}",
                "kalo-1",
                "null",
                lambda r, value=origin: _alarm(r, origin=value),
                _ALARM
                | {"finding_origins": Change({}, {"F-901": origin})}
                | ({"carried_findings": 1} if origin == "carried" else {}),
                "D-1",
            )
        )
    for kind, case, entry in (
        ("joint", "kalo-1", "D-1"),
        ("hole-pair", "brun-1", "D-2"),
        ("joint-instances", "kalo-contact-positive", "D-2"),
        ("fit", "kalo-fit-1", "D-1"),
        ("stack", "brun-1", "D-1"),
    ):
        probes.append(
            Probe(
                f"reference-{kind}-resolved",
                case,
                "null",
                lambda r, one=entry: r.add(one),
                _DETECT,
                entry,
                f"{kind}-resolved",
            )
        )
        probes.append(
            Probe(
                f"reference-{kind}-unresolved",
                case,
                "null",
                lambda r, one=entry: r.add(one, "unresolved"),
                {
                    "missed_defect_ids": -1,
                    "missed_known_defects": -1,
                    "flagged_below_expected_defect_ids": 1,
                    "unresolved_count": 1,
                    "finding_origins": 1,
                },
                entry,
                f"{kind}-unresolved",
            )
        )
    mix = {name: 0 for name in scorecard.Coverage.model_fields}
    for bucket in ("checked", "unresolved", "skipped", "out_of_scope", "not_reported"):
        overlay = "coverage-expects-checked" if bucket == "unresolved" else None
        original = "checked" if overlay else "unresolved"
        before = mix | {original: 1}
        after = mix | ({bucket: 1} if bucket != "not_reported" else {})
        moves = {"coverage_mismatches": 1, "coverage_bucket_mix": Change(before, after)}
        if original == "unresolved":
            moves["unresolved_other"] = -1
        elif bucket == "unresolved":
            moves["unresolved_other"] = 1
        probes.append(
            Probe(
                f"coverage-mismatch-{bucket}",
                "mir-sitting",
                "oracle",
                lambda r, value=bucket: _coverage(r, value),
                moves,
                "CV-1",
                overlay=overlay,
            )
        )
    for withheld in (False, True):
        probes.append(
            Probe(
                "unresolved-withheld" if withheld else "unresolved-other",
                "kalo-1",
                "null",
                lambda r, value=withheld: _unresolved(r, withheld=value),
                {
                    "unresolved_because_withheld" if withheld else "unresolved_other": 1,
                    "coverage_bucket_mix": Change(mix, mix | {"unresolved": 1}),
                },
            )
        )
    # The base's exact not-assessed map is independently fixed by its key lists, not scored anew.
    unknown = {
        "contradicted_condition_ids": scorecard.NO_CORRECT_CONDITION,
        "confirmed_condition_ids": scorecard.NO_CORRECT_CONDITION,
        "unscripted_questions": questions.NO_ANSWER_LOG,
        "bound_reached": questions.NO_ANSWER_LOG,
    }
    probes.append(
        Probe(
            "event-stream-unreadable",
            "mir-sitting",
            "oracle",
            _unreadable,
            {
                "withdrawn_forbidden_hit_finding_ids": Change([], None),
                "not_assessed": Change(
                    unknown,
                    unknown
                    | {
                        "withdrawn_forbidden_hit_finding_ids": (
                            "the event stream cannot be read from line 2, and a withdrawal "
                            "could lie after it"
                        )
                    },
                ),
            },
            "FB-1",
        )
    )
    return probes


PROBES = tuple(_scoring_probes())
MATCHING_RULES = (
    "exact-check",
    "family-at-depth",
    "family-boundary",
    "sibling-rule",
    "part-overlap",
    "drawing-location-overlap",
    "provenance-document-overlap",
    "component-provenance-not-read",
    "joint-resolved",
    "joint-unresolved",
    "hole-pair-resolved",
    "hole-pair-unresolved",
    "joint-instances-resolved",
    "joint-instances-unresolved",
    "fit-resolved",
    "fit-unresolved",
    "stack-resolved",
    "stack-unresolved",
    "role-swapped-fit",
    "extra-stack-contributor",
    "another-pair",
    "withdrawn-stream",
    "condition-and-forbidden",
)


def _question_suite() -> tuple[tuple[Probe, ...], tuple[str, ...]]:
    from tests.support.scoring_question_probes import QUESTION_MATCHING_RULES, question_probes

    return tuple(question_probes()), QUESTION_MATCHING_RULES


_QUESTION_PROBES, _QUESTION_MATCHING_RULES = _question_suite()
PROBES += _QUESTION_PROBES
MATCHING_RULES += _QUESTION_MATCHING_RULES
