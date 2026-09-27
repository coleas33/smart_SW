"""What the drawings say about each reviewed document, and what only the engineer knows (011).

`contracts/questions.md` sections 3 and 4 are normative; `tools/drawings.check_drawings` records
what this module computes. Everything here is a pure reading of the package (and, from User
Story 7, the profile): the same package gives the same coverage and the same questions.

**Drawing states** (feature 013, `specs/013-engineer-first-review/contracts/drawing-capability.md`
sections 3 and 4). Drawings exist for custom parts and custom assemblies: the same-name `.SLDDRW`
in the same folder (research R2.26). Each reviewed part or assembly document is, in this order:

- `bought` - its part role is bought (013 `contracts/part-roles.md`): no drawing is expected, none
  is asked for, and it has no coverage item, since the bought-parts line names it once;
- `attached` - a view of an attached or root drawing shows it;
- `candidate` - a same-name drawing file sits beside it, not open;
- `absent` - none does: unresolved coverage naming the file it lacks, never a finding.

An unclear document is treated as custom, and while the part-roles question is open its reason
ends "(may be a bought part)". With no roles at all - a context that never classified - every part
and assembly is a subject, as before feature 013.

**Coverage**, one `drawing.context` item per reviewed document that is not bought, in traversal
(id) order:

- `checked` - a usable view (`drawings/evidence.py`) of a drawing shows it: which drawings,
  how many views are usable, and every unusable view's reason;
- `unresolved` - drawings show it and none of their views is usable: each view's reason; or no
  drawing shows it (013): the candidate's reason or the missing drawing's.

A drawing root's own document is not a subject (feature 006 grades it); its references are.
`drawing.context` is a coverage item's `check`, never a finding's and never a checklist item's
id, so it closes nothing.

**Questions**, at most four, each an ordinary `EvidenceRequest` specification:

- one about every candidate drawing file - a same-name file beside a reviewed document, not open,
  named once however many documents it sits beside - whose first option, `CANDIDATE_CONFIRM`, is
  the one answer that has the product open it read-only (owner, 2026-09-23, research R5 Q2;
  `contracts/confirmed-open.md` section 1). Asked only when the host opens closed drawings
  (013: `mode` `opens_closed`); otherwise each candidate's reason is the instruction line;
- one per document that two or more drawings show **in a usable view**, three at most, never a
  bought one: which one governs it. A drawing that shows the document only in another
  configuration or an out-of-date view does not compete with it - that is coverage, and an answer
  could not change what was extracted.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from swreview.checks.questions import QuestionSpec
from swreview.checks.result import CheckResult, DocumentResult
from swreview.checks.tolerances import profile_name
from swreview.drawings.evidence import DrawingIndex, file_key, file_name, id_order
from swreview.drawings.native import LENGTH_UNITS
from swreview.ir.models import (
    Document,
    DrawingCandidate,
    DrawingRecord,
    DrawingSheetRecord,
    EvidencePackage,
)
from swreview.report.names import and_list, plural
from swreview.report.session import (
    MAX_OPTIONS,
    OPTION_MAX_LENGTH,
    QUESTION_MAX_LENGTH,
    CoverageBucket,
    CoverageItem,
    CoverageScope,
)

if TYPE_CHECKING:  # the standards package reaches the runner; only the types are needed here
    from swreview.bridge.client import DrawingReadMode
    from swreview.checks.part_roles import PartRoles  # 013 T018, lane P
    from swreview.checks.standards.profile import DrawingSection, StandardsProfile

__all__ = [
    "ABSENT_REASON",
    "BOUGHT_REASON",
    "CANDIDATES_WHY",
    "CANDIDATE_CONFIRM",
    "CANDIDATE_OPTIONS",
    "CANDIDATE_REASON",
    "COMPARED_SETTINGS",
    "CONFORMANCE_CHECK",
    "CONTEXT_CHECK",
    "DRAWING_STATES",
    "GOVERNING_LIMIT",
    "GOVERNING_WHY",
    "MAYBE_BOUGHT",
    "NO_DRAWING_SECTION",
    "OPEN_THEN_REVIEW",
    "SAME_NAME_READ_REASON",
    "CandidateFile",
    "ConformanceRun",
    "CoverageStatus",
    "DocumentDrawingCoverage",
    "DocumentDrawingState",
    "DrawingConformance",
    "DrawingContextResult",
    "DrawingState",
    "QuestionSpec",
    "candidate_files",
    "candidate_question",
    "compare_with_profile",
    "drawing_states",
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

# --- the drawing states (013 `contracts/drawing-capability.md` sections 3 and 4) ----------------

DrawingState = Literal["attached", "candidate", "absent", "bought"]
DRAWING_STATES: tuple[DrawingState, ...] = ("attached", "candidate", "absent", "bought")
"""Every state, in the order `check_drawings`' payload counts them (section 7)."""

BOUGHT_REASON = "a bought part: no drawing is expected, and none is asked for"
CANDIDATE_REASON = "a drawing with its name sits beside it (candidate)"
"""A candidate's reason when the host opens closed drawings, so the candidate question asks."""
OPEN_THEN_REVIEW = "Open {drawing} in SOLIDWORKS, then press Review again with {model} active"
"""A candidate's reason when the host cannot open a closed drawing (research R2.25): `{drawing}`
the candidate file, `{model}` the root document's file name - Review refuses a drawing as the
active document, so an engineer who pressed it with the drawing active would meet that refusal
first. The summary's words file carries the same line for the pane (`open_then_review_one`)."""
ABSENT_REASON = "no drawing named {stem}.SLDDRW sits beside it"
SAME_NAME_READ_REASON = "its same-name drawing {drawing} was read, and no view of it shows it"
"""An absent document whose same-name drawing is attached but shows it in no view, where the
absent reason would say no drawing of its name sits beside it, which is not so."""
MAYBE_BOUGHT = "(may be a bought part)"
"""Ends an unclear document's reason while the part-roles question is open."""


@dataclass(frozen=True)
class DocumentDrawingState:
    """One reviewed document's drawing state (013 `data-model.md` section 9)."""

    document_id: str
    state: DrawingState
    reason: str
    maybe_bought: bool
    """Unclear while the part-roles question is open: a candidate's or a missing drawing's reason
    then says the document may be bought."""


@dataclass(frozen=True)
class CandidateFile:
    """One same-name drawing file beside one or more reviewed documents (013 section 3): a part
    and an assembly of one stem in one folder share one."""

    key: str
    """`drawings/evidence.file_key` of its path: one file however the rows spell it."""
    file_name: str
    """As the first row spells it."""
    document_ids: tuple[str, ...]
    """Every custom or unclear document it sits beside, in id order; the confirmed read names
    the first."""


@dataclass(frozen=True)
class DocumentDrawingCoverage:
    """What the drawings say about one reviewed document that is not bought (`data-model.md`
    section 5; 013 section 3)."""

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
    reason: str
    """The coverage item's reason: the document's drawing state's (013 section 3)."""

    def coverage_item(self) -> CoverageItem:
        return CoverageItem(
            check=CONTEXT_CHECK,
            scope=CoverageScope(document_ids=[self.document_id]),
            reason=self.reason,
            error=None,
        )


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
    states: Mapping[str, DocumentDrawingState] = field(default_factory=dict)
    """Each reviewed document's drawing state, in traversal order (013 section 3)."""


def _is_bought(roles: PartRoles | None, document_id: str) -> bool:
    """Whether the document is bought, and so no drawing subject: the roles do not grade it.

    With no roles - a context that never classified - nothing is bought, as before 013; an id the
    roles do not hold is graded (`PartRoles.graded`: errors fail toward grading), and the review's
    root is always graded, so it is never bought here.
    """
    return roles is not None and not roles.graded(document_id)


def _stem(document: Document) -> str:
    return document.file_name.rsplit(".", 1)[0]


def _same_name_path(path: str) -> str:
    """The same-name drawing beside `path`: its folder, its stem, `.SLDDRW` - discovery's rule
    (`OpenDrawingDiscovery.CandidatePath`), whichever separator the path was written with."""
    folder, _, name = path.replace("/", "\\").rpartition("\\")
    drawing = f"{name.rsplit('.', 1)[0]}.SLDDRW"
    return f"{folder}\\{drawing}" if folder else drawing


def _same_name_drawing_read(index: DrawingIndex, document: Document) -> str | None:
    """The file name of an attached or root drawing that is `document`'s same-name drawing, or
    `None`: the drawing whose views, had any shown the document, would have made it attached."""
    wanted = file_key(_same_name_path(document.path))
    for drawing_id in index.records:
        drawing = index.documents.get(drawing_id)
        if drawing is not None and file_key(drawing.path) == wanted:
            return drawing.file_name
    return None


def candidate_files(index: DrawingIndex, roles: PartRoles | None) -> tuple[CandidateFile, ...]:
    """The candidate rows grouped by drawing file (013 section 3, research R2.28), in the id order
    of each file's first document. A bought document's row is ignored: no drawing is expected of
    it. Pure, like everything here."""
    grouped: dict[str, list[DrawingCandidate]] = {}
    for candidate in index.candidates:  # in document-id order
        if not _is_bought(roles, candidate.document_id):
            grouped.setdefault(file_key(candidate.path), []).append(candidate)
    return tuple(
        CandidateFile(
            key=key,
            file_name=file_name(rows[0].path),
            document_ids=tuple(dict.fromkeys(row.document_id for row in rows)),
        )
        for key, rows in grouped.items()
    )


def _attached_reason(index: DrawingIndex, document_id: str) -> str:
    """An attached document's reason (`contracts/questions.md` section 3): the drawings it was
    read from and how many views are usable, then every unusable view's reason - or only those
    reasons, when no view is usable."""
    views = index.views_of(document_id)
    usable = sum(1 for view in views if view.usable)
    reasons = [view.why or "" for view in views if not view.usable]
    if not usable:
        return "; ".join(reasons)
    names = [index.file_name_of(drawing) for drawing in index.drawings_of(document_id)]
    return "; ".join([f"read from {and_list(names)}; {plural(usable, 'view')} usable", *reasons])


def _state(
    index: DrawingIndex,
    roles: PartRoles | None,
    mode: DrawingReadMode,
    candidate: CandidateFile | None,
    document: Document,
) -> DocumentDrawingState:
    document_id = document.document_id
    if _is_bought(roles, document_id):
        return DocumentDrawingState(document_id, "bought", BOUGHT_REASON, maybe_bought=False)
    maybe_bought = roles is not None and roles.note_for(document_id) is not None
    if index.views_of(document_id):
        reason = _attached_reason(index, document_id)
        return DocumentDrawingState(document_id, "attached", reason, maybe_bought)
    state: DrawingState
    if candidate is not None:
        state = "candidate"
        reason = (
            CANDIDATE_REASON
            if mode == "opens_closed"
            else OPEN_THEN_REVIEW.format(
                drawing=candidate.file_name, model=index.file_name_of(index.root_document_id)
            )
        )
    else:
        state = "absent"
        read = _same_name_drawing_read(index, document)
        reason = (
            ABSENT_REASON.format(stem=_stem(document))
            if read is None
            else SAME_NAME_READ_REASON.format(drawing=read)
        )
    if maybe_bought:
        reason = f"{reason} {MAYBE_BOUGHT}"
    return DocumentDrawingState(document_id, state, reason, maybe_bought)


def drawing_states(
    index: DrawingIndex, roles: PartRoles | None, mode: DrawingReadMode
) -> dict[str, DocumentDrawingState]:
    """Each reviewed part or assembly document's drawing state, in traversal (id) order (013
    `contracts/drawing-capability.md` section 3): `bought` first, then `attached`, `candidate` or
    `absent`. `mode` - what the host's `drawing.read` can do - words a candidate's reason only: the
    instruction line unless the host opens closed drawings. Pure: nothing is recorded here."""
    files = {
        document_id: file
        for file in candidate_files(index, roles)
        for document_id in file.document_ids
    }
    return {
        document.document_id: _state(index, roles, mode, files.get(document.document_id), document)
        for document in index.subjects()
    }


def _coverage(index: DrawingIndex, state: DocumentDrawingState) -> DocumentDrawingCoverage:
    views = index.views_of(state.document_id)
    usable = [view for view in views if view.usable]
    candidate = index.candidate_of(state.document_id)
    read = index.drawings_of(state.document_id)
    return DocumentDrawingCoverage(
        document_id=state.document_id,
        read=read,
        read_names=tuple(index.file_name_of(drawing) for drawing in read),
        usable_views=len(usable),
        unusable=tuple((view.view.id, view.why or "") for view in views if not view.usable),
        candidate=None if candidate is None else candidate.path,
        status="checked" if usable else "unresolved",
        reason=state.reason,
    )


def candidate_question(
    index: DrawingIndex, roles: PartRoles | None, mode: DrawingReadMode
) -> QuestionSpec | None:
    """The one question about every candidate drawing file, or `None` when there is none or the
    host cannot open a closed drawing (013 section 4: asked only on `opens_closed`).

    Each file is named once and counted once; `entity_ids` are every custom or unclear document of
    the files, in id order. Also what `tools/drawings.read_confirmed_candidates` compares an
    answered request with, rebuilt with the same roles and mode, so the question the product acts
    on is exactly the one it asked (`contracts/confirmed-open.md` section 1).
    """
    if mode != "opens_closed":
        return None
    files = candidate_files(index, roles)
    if not files:
        return None
    names = [file.file_name for file in files]
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
        entity_ids=tuple(
            sorted({document for file in files for document in file.document_ids}, key=id_order)
        ),
        question=(
            f"A drawing with the same name sits beside {len(files)} reviewed file(s) but "
            "is not open. Should the review read it?"
        ),
        options=CANDIDATE_OPTIONS,
        blocks=CANDIDATES_BLOCK,
    )


def _governing_question(
    index: DrawingIndex, document: Document, drawings: tuple[str, ...]
) -> QuestionSpec:
    stem = _stem(document)
    template = f"{len(drawings)} open drawings show {{stem}}. Which one governs it?"
    room = QUESTION_MAX_LENGTH - len(template.format(stem=""))
    if len(stem) > room:
        stem = f"{stem[: room - 1]}…"
    files = [index.file_name_of(drawing) for drawing in drawings]
    offer = (
        len(files) <= MAX_OPTIONS - 1
        and len(set(files)) == len(files)
        and all(len(name) <= OPTION_MAX_LENGTH for name in files)
    )
    return QuestionSpec(
        key=f"governing:{document.document_id}",
        what=(
            f"Which of {len(drawings)} open drawings governs {document.file_name}: "
            + ", ".join(f"{drawing} {index.file_name_of(drawing)}" for drawing in drawings)
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
    """` ({kind}: {reason})` of the first gap the dump recorded against `entity_id`, or empty."""
    # Deferred: importing the standards package loads its evaluators and the review stack.
    from swreview.checks.standards.results import find_gap

    gap = find_gap(package, entity_id)
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
    return and_list(settings)


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
    roles: PartRoles | None = None,
    mode: DrawingReadMode = "none",
) -> DrawingContextResult:
    """The drawing check's states, coverage, questions and drawing-standard comparison over
    `package` (sections 3 and 4, 013 `contracts/drawing-capability.md` sections 3 and 4, and
    `contracts/profile.md` section 2).

    `roles` are the review's part roles (013 `contracts/part-roles.md`), `None` on a context that
    never classified; `mode` is what the host's `drawing.read` can do, `none` - it offers nothing -
    unless the caller asked the host (absent means unable, research R2.24).
    """
    index = index or DrawingIndex.for_package(package)
    states = drawing_states(index, roles, mode)
    coverage = tuple(
        _coverage(index, state) for state in states.values() if state.state != "bought"
    )

    questions: list[QuestionSpec] = []
    candidates = candidate_question(index, roles, mode)
    if candidates is not None:
        questions.append(candidates)
    governing = 0
    for document in index.subjects():
        if _is_bought(roles, document.document_id):
            continue
        competing = tuple(
            dict.fromkeys(
                view.drawing_id for view in index.views_of(document.document_id) if view.usable
            )
        )
        if len(competing) < 2:
            continue
        if governing == GOVERNING_LIMIT:
            break
        questions.append(_governing_question(index, document, competing))
        governing += 1
    return DrawingContextResult(
        coverage=coverage,
        questions=tuple(questions),
        conformance=compare_with_profile(package, profile),
        states=states,
    )
