"""What the drawings say about each reviewed document, and what only the engineer knows (011).

`contracts/questions.md` sections 3 and 4 are normative; `tools/drawings.check_drawings` records
what this module computes. Everything here is a pure reading of the package (and, from User
Story 7, the profile): the same package gives the same coverage and the same questions.

**Coverage**, one `drawing.context` item per part or assembly document the package reviews, in
traversal (id) order:

- `checked` - a usable view (`drawings/evidence.py`) of a drawing shows it: which drawings,
  how many views are usable, and every unusable view's reason;
- `unresolved` - drawings show it and none of their views is usable: each view's reason;
- `skipped` - no drawing shows it, and whether a same-name drawing sits beside it.

A drawing root's own document is not a subject (feature 006 grades it); its references are.
`drawing.context` is a coverage item's `check`, never a finding's and never a checklist item's
id, so it closes nothing.

**Questions**, at most four, each an ordinary `EvidenceRequest` specification:

- one about every drawing candidate - a same-name file beside a reviewed document, not open -
  whose first option, `CANDIDATE_CONFIRM`, is the one answer that has the product open it
  read-only (owner, 2026-09-23, research R5 Q2; `contracts/confirmed-open.md` section 1);
- one per document that two or more drawings show **in a usable view**, three at most: which one
  governs it. A drawing that shows the document only in another configuration or an out-of-date
  view does not compete with it - that is coverage, and an answer could not change what was
  extracted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from swreview.checks.result import CheckResult, DocumentResult
from swreview.checks.tolerances import profile_name
from swreview.drawings.evidence import DrawingIndex, id_order
from swreview.drawings.native import LENGTH_UNITS
from swreview.ir.models import Document, DrawingRecord, DrawingSheetRecord, EvidencePackage
from swreview.report.session import (
    MAX_OPTIONS,
    OPTION_MAX_LENGTH,
    QUESTION_MAX_LENGTH,
    CoverageBucket,
    CoverageItem,
    CoverageScope,
)

if TYPE_CHECKING:  # the standards package reaches the runner; only the types are needed here
    from swreview.checks.standards.profile import DrawingSection, StandardsProfile

__all__ = [
    "CANDIDATES_WHY",
    "CANDIDATE_CONFIRM",
    "CANDIDATE_OPTIONS",
    "COMPARED_SETTINGS",
    "CONFORMANCE_CHECK",
    "CONTEXT_CHECK",
    "GOVERNING_LIMIT",
    "GOVERNING_WHY",
    "NO_DRAWING_SECTION",
    "ConformanceRun",
    "CoverageStatus",
    "DocumentDrawingCoverage",
    "DrawingConformance",
    "DrawingContextResult",
    "QuestionSpec",
    "candidate_question",
    "compare_with_profile",
    "run_drawing_context",
]

CONTEXT_CHECK = "drawing.context"
"""The coverage `check` of every per-document item: never a finding's, never a checklist id."""

CANDIDATE_CONFIRM = "Yes, open it read-only and read it"
"""The candidate question's first option: the one answer that acts (`contracts/confirmed-open.md`
section 1). The page sends it verbatim and recognises nothing."""

CANDIDATE_OPTIONS: tuple[str, ...] = (
    CANDIDATE_CONFIRM,
    "Review without it",
    "It is not the right drawing",
)

CANDIDATES_BLOCK = "drawing.manufacturing_inputs"
"""The checklist item the candidate question blocks."""

CANDIDATES_WHY = (
    "Fits, stacks and callouts stay unresolved without a drawing. The review opens a file only "
    "when you confirm it, read-only, and closes it again."
)
GOVERNING_WHY = (
    "Open drawings of one part can disagree; the review uses them all, in a fixed order, until "
    "you say which governs."
)
ALL_APPLY = "They all apply"
GOVERNING_LIMIT = 3
"""At most three governing questions, in traversal order (SC-008: four questions at most)."""
CANDIDATES_NAMED = 10
"""How many candidate file names the candidate question's `what` names; the rest are counted."""

CoverageStatus = Literal["checked", "skipped", "unresolved"]


def _file_names(names: list[str]) -> str:
    """`a`, `a and b`, `a, b and c`: one spelling of a list of names in a sentence."""
    if len(names) <= 1:
        return "".join(names)
    return f"{', '.join(names[:-1])} and {names[-1]}"


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


@dataclass(frozen=True)
class DocumentDrawingCoverage:
    """What the drawings say about one reviewed document (`data-model.md` section 5)."""

    document_id: str
    read: tuple[str, ...]
    """The drawings any view of which shows the document, in document-id order."""
    read_names: tuple[str, ...]
    usable_views: int
    unusable: tuple[tuple[str, str], ...]
    """`(view id, why)` for every view of the document that cannot be used."""
    candidate: str | None
    """The same-name drawing file beside the document, when the extraction recorded one."""
    status: CoverageStatus

    @property
    def reason(self) -> str:
        """The coverage item's reason (`contracts/questions.md` section 3)."""
        reasons = [why for _, why in self.unusable]
        if self.status == "skipped":
            text = "no open drawing shows it"
            if self.candidate is not None:
                text += "; a drawing with its name sits beside it (candidate)"
            return text
        if self.status == "unresolved":
            return "; ".join(reasons)
        head = (
            f"read from {_file_names(list(self.read_names))}; "
            f"{_plural(self.usable_views, 'view')} usable"
        )
        return "; ".join([head, *reasons])

    def coverage_item(self) -> CoverageItem:
        return CoverageItem(
            check=CONTEXT_CHECK,
            scope=CoverageScope(document_ids=[self.document_id]),
            reason=self.reason,
            error=None,
        )


@dataclass(frozen=True)
class QuestionSpec:
    """One question `check_drawings` writes through `tools/session.record_evidence_request`."""

    key: str
    """`candidates` or `governing:<document id>`."""
    what: str
    why: str
    entity_ids: tuple[str, ...]
    question: str
    options: tuple[str, ...]
    blocks: str | None


@dataclass(frozen=True)
class DrawingConformance:
    """One drawing's comparison with the profile's drawing section (`contracts/profile.md` 2):
    which settings differ, which the profile leaves empty, which values were not read."""

    document_id: str
    differs: tuple[str, ...]
    skipped: tuple[str, ...]
    unread: tuple[str, ...]
    """Why each compared value that was not read could not be compared."""
    agrees: tuple[str, ...]
    """The settings compared and found in agreement."""


@dataclass(frozen=True)
class ConformanceRun:
    """What `compare_with_profile` found: the findings, the coverage and each drawing's
    comparison (for the brief), before anything is written."""

    findings: tuple[DocumentResult, ...] = ()
    coverage: tuple[tuple[CoverageBucket, CoverageItem], ...] = ()
    drawings: tuple[DrawingConformance, ...] = ()


@dataclass(frozen=True)
class DrawingContextResult:
    """Everything the drawing check records, computed before anything is written."""

    coverage: tuple[DocumentDrawingCoverage, ...]
    questions: tuple[QuestionSpec, ...]
    conformance: ConformanceRun = field(default_factory=ConformanceRun)
    """The drawing standard's comparison (User Story 7)."""


def _subjects(package: EvidencePackage) -> list[Document]:
    """The part and assembly documents the package reviews, in traversal (id) order."""
    return sorted(
        (document for document in package.documents if document.kind in ("part", "assembly")),
        key=lambda document: id_order(document.document_id),
    )


def _coverage(
    index: DrawingIndex, names: dict[str, str], document: Document
) -> DocumentDrawingCoverage:
    views = index.views_of(document.document_id)
    usable = [view for view in views if view.usable]
    unusable = tuple((view.view.id, view.why or "") for view in views if not view.usable)
    candidate = index.candidate_of(document.document_id)
    read = index.drawings_of(document.document_id)
    status: CoverageStatus = "checked" if usable else ("unresolved" if views else "skipped")
    return DocumentDrawingCoverage(
        document_id=document.document_id,
        read=read,
        read_names=tuple(names.get(drawing, drawing) for drawing in read),
        usable_views=len(usable),
        unusable=unusable,
        candidate=None if candidate is None else candidate.path,
        status=status,
    )


def _file_name_of(path: str) -> str:
    return path.replace("/", "\\").rsplit("\\", 1)[-1]


def candidate_question(index: DrawingIndex) -> QuestionSpec | None:
    """The one question about every drawing candidate, or `None` when there is none.

    Also what `tools/drawings.read_confirmed_candidates` compares an answered request with, so
    the question the product acts on is exactly the one it asked (`contracts/confirmed-open.md`
    section 1).
    """
    candidates = list(index.candidates)
    if not candidates:
        return None
    names = [_file_name_of(candidate.path) for candidate in candidates]
    shown = ", ".join(names[:CANDIDATES_NAMED])
    rest = len(names) - CANDIDATES_NAMED
    if rest > 0:
        shown += f" and {rest} more"
    what = (
        f"The same-name drawing {shown}, beside a reviewed file and not open"
        if len(names) == 1
        else f"The same-name drawings {shown}, each beside a reviewed file and not open"
    )
    return QuestionSpec(
        key="candidates",
        what=what,
        why=CANDIDATES_WHY,
        entity_ids=tuple(candidate.document_id for candidate in candidates),
        question=(
            f"A drawing with the same name sits beside {len(candidates)} reviewed file(s) but "
            "is not open. Should the review read it?"
        ),
        options=CANDIDATE_OPTIONS,
        blocks=CANDIDATES_BLOCK,
    )


def _governing_question(
    document: Document, drawings: tuple[str, ...], names: dict[str, str]
) -> QuestionSpec:
    stem = document.file_name.rsplit(".", 1)[0]
    template = f"{len(drawings)} open drawings show {{stem}}. Which one governs it?"
    room = QUESTION_MAX_LENGTH - len(template.format(stem=""))
    if len(stem) > room:
        stem = f"{stem[: room - 1]}…"
    files = [names.get(drawing, drawing) for drawing in drawings]
    offer = (
        len(files) <= MAX_OPTIONS - 1
        and len(set(files)) == len(files)
        and all(len(name) <= OPTION_MAX_LENGTH for name in files)
    )
    return QuestionSpec(
        key=f"governing:{document.document_id}",
        what=(
            f"Which of {len(drawings)} open drawings governs {document.file_name}: "
            + ", ".join(f"{drawing} {names.get(drawing, drawing)}" for drawing in drawings)
        ),
        why=GOVERNING_WHY,
        entity_ids=(document.document_id, *drawings),
        question=template.format(stem=stem),
        options=(*files, ALL_APPLY) if offer else (),
        blocks=None,
    )


# --- the drawing standard (User Story 7, `contracts/profile.md` sections 2 and 3) -------------

CONFORMANCE_CHECK = "drawing_profile.conformance"
"""The one new finding id. Its prefix is not `drawing.`, so it cannot close the checklist's
`drawing.manufacturing_inputs` item, which closes on any `drawing.` finding (research R2.18)."""

NO_DRAWING_SECTION = "the standards profile is absent, which has no drawing section"

COMPARED_SETTINGS: tuple[str, ...] = (
    "sheet_formats",
    "drafting_standard",
    "projection",
    "dimension_unit",
)
"""The settings compared, in the contract's order; the two templates are recorded for feature
012 and never compared - a finished drawing does not record the template it was made from."""

SETTING_LABELS: dict[str, str] = {
    "sheet_formats": "sheet format",
    "drafting_standard": "drafting standard",
    "projection": "projection",
    "dimension_unit": "dimension unit",
}
PROJECTION_WORDS: dict[bool, str] = {True: "first-angle", False: "third-angle"}


def _gap_note(package: EvidencePackage, entity_id: str) -> str:
    gap = next((item for item in package.gaps if item.entity_id == entity_id), None)
    return "" if gap is None else f" ({gap.entity_kind}: {gap.reason})"


def _sheets_compared(
    package: EvidencePackage, record: DrawingRecord
) -> tuple[list[DrawingSheetRecord], list[str]]:
    sheets = sorted(record.sheets, key=lambda item: item.index)
    unread = [] if sheets else [
        f"the sheets of drawing {record.document_id} were not read"
        f"{_gap_note(package, record.document_id)}"
    ]
    return sheets, unread


def _compare(
    package: EvidencePackage, record: DrawingRecord, section: DrawingSection, setting: str
) -> tuple[list[str], list[str]] | None:
    """`(the drawing's differing values, unread reasons)` for one setting, or `None` when the
    profile leaves it empty. Every sentence states the drawing's own value, never the
    profile's (006 FR-034)."""
    drawing = record.document_id
    if setting == "drafting_standard":
        if not section.drafting_standard:
            return None
        value = record.drafting_standard_name
        if value is None:
            return [], [
                f"the drafting standard of drawing {drawing} was not read"
                f"{_gap_note(package, drawing)}"
            ]
        agrees = value.strip().casefold() == section.drafting_standard.strip().casefold()
        return ([] if agrees else [f"the drawing's drafting standard is '{value}'"]), []
    if setting == "dimension_unit":
        if not section.dimension_unit:
            return None
        raw = record.length_unit_raw
        if raw is None:
            return [], [
                f"the unit drawing {drawing} is dimensioned in was not read"
                f"{_gap_note(package, drawing)}"
            ]
        named = LENGTH_UNITS.get(raw) or f"unit {raw} (swLengthUnit_e)"
        return ([] if named == section.dimension_unit else [
            f"the drawing is dimensioned in {named}"
        ]), []
    sheets, unread = _sheets_compared(package, record)
    if setting == "sheet_formats":
        if not section.sheet_formats:
            return None
        accepted = set(section.sheet_formats)
        differs = [
            f"sheet {sheet.name} uses the sheet format '{sheet.sheet_format_name}'"
            for sheet in sheets
            if sheet.sheet_format_name is not None and sheet.sheet_format_name not in accepted
        ]
        unread += [
            f"the sheet format of sheet {sheet.name} was not read{_gap_note(package, sheet.id)}"
            for sheet in sheets
            if sheet.sheet_format_name is None
        ]
        return differs, unread
    if not section.projection:
        return None
    wanted = section.projection == "first_angle"
    differs = [
        f"sheet {sheet.name} is drawn in {PROJECTION_WORDS[sheet.first_angle]} projection"
        for sheet in sheets
        if sheet.first_angle is not None and sheet.first_angle != wanted
    ]
    unread += [
        f"the projection of sheet {sheet.name} was not read{_gap_note(package, sheet.id)}"
        for sheet in sheets
        if sheet.first_angle is None
    ]
    return differs, unread


def _named(settings: list[str]) -> str:
    return _file_names(settings)


def _conformance_item(document_id: str, reason: str) -> CoverageItem:
    return CoverageItem(
        check=CONFORMANCE_CHECK,
        scope=CoverageScope(document_ids=[document_id]),
        reason=reason,
        error=None,
    )


def compare_with_profile(
    package: EvidencePackage, profile: StandardsProfile | None
) -> ConformanceRun:
    """Every attached or root drawing compared with the profile's drawing section
    (`contracts/profile.md` section 2), in document-id order.

    One `drawing_profile.conformance` finding per drawing that differs, naming each differing
    setting with the drawing's own values; a `checked` item for a drawing every compared setting
    of which agrees; an `unresolved` item naming each value that was not read; a `skipped` item
    naming the settings the profile leaves empty; and, without a version 3 profile, one
    `skipped` item for every drawing. Pure: nothing is recorded here.
    """
    records = sorted(package.drawing_records, key=lambda item: id_order(item.document_id))
    if not records:
        return ConformanceRun()
    section = profile.drawing if profile is not None else None
    if profile is None or section is None:
        reason = (
            NO_DRAWING_SECTION
            if profile is None
            else f"the standards profile is version {profile.version}, which has no drawing "
            "section"
        )
        item = CoverageItem(
            check=CONFORMANCE_CHECK,
            scope=CoverageScope(document_ids=[record.document_id for record in records]),
            reason=reason,
            error=None,
        )
        return ConformanceRun(coverage=(("skipped", item),))

    names = {document.document_id: document.file_name for document in package.documents}
    components = {}
    for component in package.components:
        components.setdefault(component.document_id, []).append(component.id)
    findings: list[DocumentResult] = []
    coverage: list[tuple[CoverageBucket, CoverageItem]] = []
    drawings: list[DrawingConformance] = []
    for record in records:
        drawing = record.document_id
        differs: list[tuple[str, list[str]]] = []
        unread: list[str] = []
        skipped: list[str] = []
        agrees: list[str] = []
        for setting in COMPARED_SETTINGS:
            outcome = _compare(package, record, section, setting)
            if outcome is None:
                skipped.append(setting)
                continue
            values, not_read = outcome
            unread.extend(not_read)
            if values:
                differs.append((setting, values))
            elif not not_read:
                agrees.append(setting)
        drawings.append(
            DrawingConformance(
                document_id=drawing,
                differs=tuple(setting for setting, _ in differs),
                skipped=tuple(skipped),
                unread=tuple(unread),
                agrees=tuple(agrees),
            )
        )
        if skipped:
            coverage.append((
                "skipped",
                _conformance_item(
                    drawing,
                    f"the profile leaves {_named(skipped)} empty, so drawing {drawing} was not "
                    "compared in them",
                ),
            ))
        if unread:
            coverage.append(("unresolved", _conformance_item(drawing, "; ".join(unread))))
        if agrees and not differs and not unread:
            coverage.append((
                "checked",
                _conformance_item(
                    drawing,
                    f"drawing {drawing} agrees with the profile's drawing standard in "
                    f"{_named(agrees)}",
                ),
            ))
        if differs:
            findings.append(
                _conformance_finding(
                    drawing, names.get(drawing, drawing), differs, skipped, unread,
                    tuple(components.get(drawing, ())), profile,
                )
            )
    return ConformanceRun(
        findings=tuple(findings), coverage=tuple(coverage), drawings=tuple(drawings)
    )


def _conformance_finding(
    drawing: str,
    file_name: str,
    differs: list[tuple[str, list[str]]],
    skipped: list[str],
    unread: list[str],
    component_ids: tuple[str, ...],
    profile: StandardsProfile,
) -> DocumentResult:
    stated = "; ".join(
        f"{SETTING_LABELS[setting]}: {', '.join(values)}" for setting, values in differs
    )
    limits = [f"not compared, left empty in the profile: {_named(skipped)}"] if skipped else []
    limits += [f"not compared, not read: {reason}" for reason in unread]
    result = CheckResult(
        check=CONFORMANCE_CHECK,
        status="demonstrated",
        severity="medium",
        observed=f"{file_name} ({drawing}) differs from the company's drawing standard - {stated}",
        requirement=(
            "every drawing follows the company's drawing standard, the drawing section of "
            f"{profile_name(profile)}: its accepted sheet formats, drafting standard, projection "
            "and dimension unit"
        ),
        inputs=[drawing],
        calculation=None,
        coverage_limits=limits,
        recommended_action=(
            f"Bring {file_name} to the drawing standard in each setting named, or record why this "
            "drawing differs."
        ),
    )
    return DocumentResult(result=result, documents=(drawing,), component_ids=component_ids)


def run_drawing_context(
    package: EvidencePackage,
    profile: StandardsProfile | None = None,
    index: DrawingIndex | None = None,
) -> DrawingContextResult:
    """The drawing check's coverage, questions and drawing-standard comparison over `package`
    (sections 3 and 4, and `contracts/profile.md` section 2)."""
    index = index or DrawingIndex.for_package(package)
    names = {document.document_id: document.file_name for document in package.documents}
    subjects = _subjects(package)
    coverage = tuple(_coverage(index, names, document) for document in subjects)

    questions: list[QuestionSpec] = []
    candidates = candidate_question(index)
    if candidates is not None:
        questions.append(candidates)
    governing = 0
    for document in subjects:
        competing = tuple(
            dict.fromkeys(
                view.drawing_id for view in index.views_of(document.document_id) if view.usable
            )
        )
        if len(competing) < 2:
            continue
        if governing == GOVERNING_LIMIT:
            break
        questions.append(_governing_question(document, competing, names))
        governing += 1
    return DrawingContextResult(
        coverage=coverage,
        questions=tuple(questions),
        conformance=compare_with_profile(package, profile),
    )
