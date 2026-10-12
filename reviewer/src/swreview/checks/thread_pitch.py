"""Fine and non-standard thread pitch (feature 010 amendment 2026-10-08, T117).

`contracts/fasteners.md` section 8 is normative; research R2.26 records the owner's decisions
50A to 53A and 57A and the defaults this module follows. The owner's request: "Add check for
fine pitch parts and threaded holes. Call out and flag to user to make sure they mean to use
it anywhere. We almost always use standard threads not fine... so it's a common mistake."

`run_thread_checks` reads four sources (section 8.2) and nothing else:

- every Hole Wizard hole whose `hole_type` is `tapped`; the other hole types carry a screw
  size, not a thread;
- every cosmetic thread;
- every fastener row, of any kind (a nut can be fine); a washer, pin or `other` row with no
  designation states no thread and is not a source, while a screw, bolt or nut row with none
  is unreadable;
- every screw, bolt or pin `recognise_fasteners` recognises by its name for a component with
  no row: the instances whose id starts `NAMED_FASTENER_ID_PREFIX`, never told apart by
  `identity_source`, which a row can carry too (D23).

A source's part is its component's document - the part a hole or a cosmetic thread is in, and
a fastener's own file (D11). A source whose component or document is not in the package has no
part to grade or group by, so it is listed as unreadable, never passed.

Then, in this order: a tapped hole or cosmetic thread of a bought part (feature 013's roles,
read as `checks/hygiene.py` reads them) is listed in the bought row - a fastener is classified
whatever its role, since choosing it is a design choice (52A); a tapped hole whose feature row
reads suppressed in its component's configuration, and a fastener row on a suppressed
component, is listed in the suppressed row; every other thread is classified by
`coarse_pitch.classify_pitch`. Fine threads and fine-only sizes are `thread.fine_pitch` and
threads coarser than the coarse pitch `thread.nonstandard_pitch`, one finding per check and
part (57A) listing each designation with its sources and its coarse alternative; coarse
threads are counted in one checked row, with no finding (R2.21); unreadable, unknown-size and
pipe threads are listed in one row each, never passed (50A). Last, what the extractor did not
read: the gaps that name no row (D20), the hole and fastener phases that did not run (D17),
and, on a `full` package with no source and neither of those, one row saying there is none.

Every row is the coverage-only id `thread.pitch`. Every sentence of sections 8.5 and 8.6 is a
constant below; the clauses of section 8.5's table are composed from `FINE_CLAUSE` or
`NONSTANDARD_CLAUSE` and one of the four `WHY_` phrases.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from swreview.checks.coarse_pitch import (
    DEFAULT_COARSE_PITCH_PATH,
    CoarsePitchTable,
    PitchVerdict,
    classify_pitch,
    load_coarse_pitch,
)
from swreview.checks.fastener_identity import NAMED_FASTENER_ID_PREFIX, recognise_fasteners
from swreview.checks.part_roles import PartRoles, note_unclear
from swreview.checks.result import CheckResult, DocumentResult
from swreview.ir.models import ComponentInstance, Document, EvidencePackage, Feature, Gap
from swreview.report.names import and_list, plural
from swreview.report.session import CoverageItem, CoverageScope

__all__ = [
    "CHECK_FINE_PITCH",
    "CHECK_NONSTANDARD_PITCH",
    "COVERAGE_CHECK",
    "ThreadChecks",
    "run_thread_checks",
]

CHECK_FINE_PITCH = "thread.fine_pitch"
CHECK_NONSTANDARD_PITCH = "thread.nonstandard_pitch"
COVERAGE_CHECK = "thread.pitch"
"""The id of every coverage row: a coverage-only id, never a finding's (section 8.4)."""

# --- the words of a finding (section 8.5) ------------------------------------------------------

REQUIREMENTS: Mapping[str, str] = {
    CHECK_FINE_PITCH: "threads use the coarse (standard) pitch unless a fine pitch is deliberate",
    CHECK_NONSTANDARD_PITCH: (
        "threads use the coarse (standard) pitch; no standard pitch of a size is coarser than it"
    ),
}
OBSERVED = "{clauses} in {part}"
CLAUSE_SEPARATOR = "; "
FINE_CLAUSE = "{designation} is fine pitch ({why}) on {sources}: {listed}"
NONSTANDARD_CLAUSE = (
    "{designation} is coarser than the standard pitch ({why}) on {sources}: {listed}"
)
WHY_METRIC = "{size}'s coarse pitch is {coarse}"
WHY_UNIFIED = "{size}'s coarse thread is UNC, {tpi} threads per inch"
WHY_METRIC_FINE_ONLY = "{size} has no coarse pitch in ISO 261"
WHY_UNIFIED_FINE_ONLY = "{size} has no UNC thread in ASME B1.1"
HOLE_ENTRY = "{feature} ({ids})"
THREAD_ENTRY = "cosmetic thread {id}"
ACTION_COARSE = (
    "Confirm {designations} {is_} intended in {part}, or change {it} to the coarse "
    "{alternatives}."
)
ACTION_FINE_ONLY = (
    "Confirm {designations} {is_} intended in {part}, or change {it} to a size that has a "
    "coarse thread."
)
ACTION_BOTH = (
    "Confirm {designations} are intended in {part}, or change {with_coarse} to the coarse "
    "{alternatives}, and {fine_only} to a size that has a coarse thread."
)
CITE_METRIC = "ISO 261 coarse pitch of {size}: {coarse} mm ({table} version {version})"
CITE_METRIC_FINE_ONLY = "ISO 261: {size} has fine pitches only ({table} version {version})"
CITE_UNIFIED = "ASME B1.1 UNC of {size}: {tpi} threads per inch ({table} version {version})"
CITE_UNIFIED_FINE_ONLY = "ASME B1.1: {size} has no UNC thread ({table} version {version})"
WRITTEN_AS = "written as '{text}' on {id}"
DRAWINGS_LIMIT = "thread callouts on drawings were not read for pitch"
SUPPRESSION_NOT_READ = "whether {feature} ({id}) is suppressed was not read: {reason}"
NO_FEATURE_TREE = "its part's feature tree was not read"
OTHER_CONFIGURATION = "the feature tree was read in configuration {read}, not {referenced}"
NO_FEATURE_OF_THAT_NAME = "the feature tree holds no feature of that name"
SUPPRESSION_UNREADABLE = "its suppression state could not be read"
COSMETIC_NOT_READ = (
    "a cosmetic thread carries no feature name, so whether it is suppressed was not read"
)

# --- the words of the coverage rows (section 8.6) ----------------------------------------------

CHECKED = "{threads} {have} the coarse pitch: {entries}"
CHECKED_ENTRY = "{designation} ({ids})"
NO_PITCH_WRITTEN = (
    "; {count} of them {have} no pitch written, read as coarse because ISO 965-1 omits the "
    "coarse pitch from a designation"
)
UNREADABLE = "{threads} could not be read for pitch, so their pitch was not checked: {items}"
UNKNOWN_SIZE = (
    "{threads} {have} a size in no pitch table (ISO 261 to M68, ASME B1.1 UNC to 2 in), so "
    "their pitch was not checked: {items}"
)
PIPE = "{threads} {were} not checked for pitch; a pipe thread has its own series: {items}"
BOUGHT = "{threads} in bought parts {were} not checked for pitch: {entries}"
BOUGHT_ENTRY = "{part} ({ids})"
SUPPRESSED = (
    "{threads} on suppressed features or components {were} not checked for pitch: {items}"
)
SUPPRESSED_FASTENER_ITEM = "{id} ({component})"
TEXT_ITEM = "'{text}' on {id}"
NO_DESIGNATION_ITEM = "no designation on {id}"
NOT_IN_PACKAGE_TAIL = " (its part is not in the package)"
NOT_READ = (
    "{gaps} left holes, cosmetic threads or fasteners unread, so their pitch was not checked: "
    "{reasons}"
)
NOT_READ_SEPARATOR = "; "
PHASES_NOT_RUN_PROFILE = (
    "tapped holes, cosmetic threads and fastener rows were not read for pitch: the hole and "
    "fastener phases did not run (profile {profile})"
)
PHASES_NOT_RUN = "{what} were not read for pitch: the {phases} did not run in this dump"
PHASES_NOT_RUN_WORDS: Mapping[tuple[str, ...], tuple[str, str]] = {
    ("hole",): ("tapped holes and cosmetic threads", "hole phase"),
    ("fastener",): ("fastener rows", "fastener phase"),
    ("hole", "fastener"): (
        "tapped holes, cosmetic threads and fastener rows",
        "hole and fastener phases",
    ),
}
NOTHING_AT_ALL = "no tapped hole, cosmetic thread or fastener in the package states a thread"

LIST_SEPARATOR = ", "

# --- the rules ----------------------------------------------------------------------------------

SourceKind = Literal["hole", "thread", "fastener"]
"""Each kind is also the `entity_kind` of the extractor's gaps about it."""
THREAD_PHASES: tuple[str, ...] = ("hole", "fastener")
"""The dump phases that read the sources: holes and cosmetic threads, then fastener rows."""
STATES_A_THREAD_WHEN_BLANK: tuple[str, ...] = ("screw", "bolt", "nut")
"""The fastener kinds that state a thread even with no designation, which is then unreadable;
a washer, pin or `other` with none states no thread (D13)."""
FULL_PROFILE = "full"
SUPPRESSED_COMPONENT = "suppressed"


@dataclass(frozen=True)
class ThreadChecks:
    """The findings, the coverage rows by bucket, and the counts the tool returns."""

    findings: tuple[DocumentResult, ...]
    checked: tuple[CoverageItem, ...]
    unresolved: tuple[CoverageItem, ...]
    skipped: tuple[CoverageItem, ...]
    threads: int
    """Every source read: each tapped hole, cosmetic thread and fastener instance that states a
    thread, or that should and does not, whatever became of it."""
    coarse: int
    """The sources counted in the checked row."""


@dataclass(frozen=True)
class _Source:
    """One thread the package states, in the words a finding or a row lists it by."""

    kind: SourceKind
    entity_id: str
    """A hole, cosmetic thread or fastener row id; a screw recognised by its name has no row,
    so its component id (section 8.5, `inputs`)."""
    component: ComponentInstance | None
    component_id: str
    document: Document | None
    """The part: the component's document; `None` when it is not in the package."""
    text: str | None
    feature_name: str | None = None
    """A tapped hole's Hole Wizard feature; cosmetic threads and fasteners have none."""

    @property
    def written(self) -> str:
        """The designation as written, trimmed; `""` when there is none."""
        return (self.text or "").strip()


@dataclass(frozen=True)
class _Judged:
    """A classified source, and the suppression limit its finding carries."""

    source: _Source
    verdict: PitchVerdict
    limit: str | None


@dataclass(frozen=True)
class _Designation:
    """The sources of one normalized designation, in source order, named by the first."""

    judged: tuple[_Judged, ...]

    @property
    def written(self) -> str:
        return self.judged[0].source.written

    @property
    def verdict(self) -> PitchVerdict:
        return self.judged[0].verdict

    @property
    def sources(self) -> tuple[_Source, ...]:
        return tuple(item.source for item in self.judged)


# --- sources ------------------------------------------------------------------------------------


def _states_a_thread(kind: str, designation: str | None) -> bool:
    return kind in STATES_A_THREAD_WHEN_BLANK or bool((designation or "").strip())


def _sources(package: EvidencePackage) -> list[_Source]:
    """Every source of section 8.2, in source order: tapped holes by id, cosmetic threads by id,
    then fasteners by component id (rows and screws named by their parts together).

    Fastener rows are read from the package, each once, whatever its `identity_source` (D23);
    a row's part is its component's document, the one `recognise_fasteners` gives it, so a row
    it does not return - its component or document missing - is a source with no part.
    """
    components = {item.id: item for item in package.components}
    documents = {item.document_id: item for item in package.documents}

    def source(
        kind: SourceKind,
        entity_id: str,
        component_id: str,
        text: str | None,
        feature_name: str | None = None,
    ) -> _Source:
        component = components.get(component_id)
        document = None if component is None else documents.get(component.document_id)
        return _Source(kind, entity_id, component, component_id, document, text, feature_name)

    holes = [
        source("hole", hole.id, hole.component_id, hole.thread_designation, hole.feature_name)
        for hole in sorted(package.holes, key=lambda item: item.id)
        if hole.hole_type == "tapped"
    ]
    threads = [
        source("thread", thread.id, thread.component_id, thread.designation)
        for thread in sorted(package.threads, key=lambda item: item.id)
    ]
    rows = [
        source("fastener", row.id, row.component_id, row.thread_designation)
        for row in package.fasteners
        if _states_a_thread(row.kind, row.thread_designation)
    ]
    named = [
        source(
            "fastener", item.component_id, item.component_id, item.fastener.thread_designation
        )
        for item in recognise_fasteners(package)
        if item.fastener.id.startswith(NAMED_FASTENER_ID_PREFIX)
        and _states_a_thread(item.fastener.kind, item.fastener.thread_designation)
    ]
    fasteners = sorted([*rows, *named], key=lambda item: (item.component_id, item.entity_id))
    return [*holes, *threads, *fasteners]


# --- suppression (section 8.2) -----------------------------------------------------------------


def _features_by_document(package: EvidencePackage) -> dict[str, list[Feature]]:
    by_document: dict[str, list[Feature]] = {}
    for feature in package.features:
        by_document.setdefault(feature.document_id, []).append(feature)
    return by_document


def _hole_suppression(
    source: _Source, features: Mapping[str, Sequence[Feature]]
) -> tuple[bool, str | None]:
    """Whether a tapped hole's feature reads suppressed, and, when that was not read, the limit
    its finding carries: the first case of section 8.2's table that holds (D5, D12)."""
    assert source.component is not None and source.document is not None
    referenced = source.component.referenced_configuration
    rows = features.get(source.document.document_id, ())
    reason: str
    if not rows:
        reason = NO_FEATURE_TREE
    else:
        in_configuration = [row for row in rows if row.configuration == referenced]
        named = [row for row in in_configuration if row.name == source.feature_name]
        if not in_configuration:
            read = and_list(sorted({row.configuration for row in rows}))
            reason = OTHER_CONFIGURATION.format(read=read, referenced=referenced)
        elif not named:
            reason = NO_FEATURE_OF_THAT_NAME
        elif any(row.suppressed is True for row in named):
            return True, None
        elif any(row.suppressed is None for row in named):
            reason = SUPPRESSION_UNREADABLE
        else:
            return False, None
    limit = SUPPRESSION_NOT_READ.format(
        feature=source.feature_name, id=source.entity_id, reason=reason
    )
    return False, limit


def _suppression(
    source: _Source, features: Mapping[str, Sequence[Feature]]
) -> tuple[bool, str | None]:
    """Whether the source is skipped as suppressed, and the limit its finding carries if not."""
    if source.kind == "hole":
        return _hole_suppression(source, features)
    if source.kind == "thread":
        return False, COSMETIC_NOT_READ
    # A screw named by its part is resolved by construction; a row's component may not be.
    assert source.component is not None
    return source.component.suppression == SUPPRESSED_COMPONENT, None


# --- findings (section 8.5) --------------------------------------------------------------------


def _designations(judged: Iterable[_Judged]) -> list[_Designation]:
    """The judged sources grouped by `parse_thread`'s normalized designation, in the order of
    each one's first source."""
    groups: dict[str, list[_Judged]] = {}
    for item in judged:
        assert item.verdict.spec is not None
        groups.setdefault(item.verdict.spec.normalized, []).append(item)
    return [_Designation(tuple(group)) for group in groups.values()]


def _metric(verdict: PitchVerdict) -> bool:
    assert verdict.spec is not None
    return verdict.spec.series == "metric"


def _why(verdict: PitchVerdict) -> str:
    if verdict.pitch_class == "fine_only_size":
        template = WHY_METRIC_FINE_ONLY if _metric(verdict) else WHY_UNIFIED_FINE_ONLY
        return template.format(size=verdict.size)
    if _metric(verdict):
        return WHY_METRIC.format(size=verdict.size, coarse=f"{verdict.coarse_pitch_mm:g}")
    return WHY_UNIFIED.format(size=verdict.size, tpi=f"{verdict.unc_tpi:g}")


def _cite(verdict: PitchVerdict, table: CoarsePitchTable) -> str:
    where = {"table": DEFAULT_COARSE_PITCH_PATH.name, "version": table.version}
    if verdict.pitch_class == "fine_only_size":
        template = CITE_METRIC_FINE_ONLY if _metric(verdict) else CITE_UNIFIED_FINE_ONLY
        return template.format(size=verdict.size, **where)
    if _metric(verdict):
        return CITE_METRIC.format(size=verdict.size, coarse=f"{verdict.coarse_pitch_mm:g}", **where)
    return CITE_UNIFIED.format(size=verdict.size, tpi=f"{verdict.unc_tpi:g}", **where)


def _of_kind(sources: Iterable[_Source], kind: SourceKind) -> list[_Source]:
    return [item for item in sources if item.kind == kind]


def _counted_sources(sources: Sequence[_Source]) -> str:
    """`{sources}`: a part's tapped holes by distinct feature name - the engineer changes the
    feature - its cosmetic threads by row, its fasteners by instance (D24)."""
    holes = {item.feature_name for item in _of_kind(sources, "hole")}
    counts = (
        (len(holes), "tapped hole"),
        (len(_of_kind(sources, "thread")), "cosmetic thread"),
        (len(_of_kind(sources, "fastener")), "fastener instance"),
    )
    return and_list([plural(count, noun) for count, noun in counts if count])


def _listed(sources: Sequence[_Source]) -> str:
    """`{list}`: each tapped hole feature with every instance's hole id, in feature-name order,
    then each cosmetic thread, then each fastener instance by its component id."""
    features: dict[str, list[str]] = {}
    for item in _of_kind(sources, "hole"):
        features.setdefault(item.feature_name or "", []).append(item.entity_id)
    entries = [
        HOLE_ENTRY.format(feature=name, ids=LIST_SEPARATOR.join(ids))
        for name, ids in sorted(features.items())
    ]
    entries += [THREAD_ENTRY.format(id=item.entity_id) for item in _of_kind(sources, "thread")]
    entries += [item.component_id for item in _of_kind(sources, "fastener")]
    return LIST_SEPARATOR.join(entries)


def _clause(designation: _Designation) -> str:
    template = (
        NONSTANDARD_CLAUSE if designation.verdict.pitch_class == "nonstandard" else FINE_CLAUSE
    )
    return template.format(
        designation=designation.written,
        why=_why(designation.verdict),
        sources=_counted_sources(designation.sources),
        listed=_listed(designation.sources),
    )


def _action(designations: Sequence[_Designation], part: str) -> str:
    written = and_list([item.written for item in designations])
    with_coarse = [item for item in designations if item.verdict.coarse_designation is not None]
    fine_only = [item for item in designations if item.verdict.coarse_designation is None]
    alternatives = and_list([str(item.verdict.coarse_designation) for item in with_coarse])
    one = len(designations) == 1
    agreement = {"is_": "is" if one else "are", "it": "it" if one else "them"}
    if not fine_only:
        return ACTION_COARSE.format(
            designations=written, part=part, alternatives=alternatives, **agreement
        )
    if not with_coarse:
        return ACTION_FINE_ONLY.format(designations=written, part=part, **agreement)
    return ACTION_BOTH.format(
        designations=written,
        part=part,
        with_coarse=and_list([item.written for item in with_coarse]),
        alternatives=alternatives,
        fine_only=and_list([item.written for item in fine_only]),
    )


def _unique(items: Iterable[str | None]) -> list[str]:
    """Each text once, in first-seen order, `None` left out."""
    return list(dict.fromkeys(item for item in items if item is not None))


def _finding(
    check: str,
    document: Document,
    judged: Sequence[_Judged],
    table: CoarsePitchTable,
    roles: PartRoles | None,
) -> DocumentResult:
    """One part's finding of one check: every designation, each with its sources (57A)."""
    designations = _designations(judged)
    sources = [item.source for item in judged]
    part = document.file_name
    result = CheckResult(
        check=check,
        status="suspected",
        severity="medium",
        observed=OBSERVED.format(
            clauses=CLAUSE_SEPARATOR.join(_clause(item) for item in designations), part=part
        ),
        requirement=REQUIREMENTS[check],
        inputs=[
            *(item.entity_id for item in sources),
            *(_cite(item.verdict, table) for item in designations),
            *(
                WRITTEN_AS.format(text=source.written, id=source.entity_id)
                for item in designations
                for source in item.sources
                if source.written != item.written
            ),
        ],
        calculation=None,
        coverage_limits=[DRAWINGS_LIMIT, *_unique(item.limit for item in judged)],
        recommended_action=_action(designations, part),
    )
    # The part-roles note promises that the answer may withdraw the finding, which only a
    # tapped hole or a cosmetic thread can be (D21).
    if roles is not None and any(item.kind != "fastener" for item in sources):
        result = note_unclear(result, roles.note_for(document.document_id))
    return DocumentResult(
        result=result,
        documents=(document.document_id,),
        component_ids=tuple(sorted({item.component_id for item in sources})),
    )


# --- coverage rows (section 8.6) ---------------------------------------------------------------


def _row(reason: str, sources: Sequence[_Source]) -> CoverageItem:
    """A row of sources, its scope their components and parts, each once, ascending."""
    return CoverageItem(
        check=COVERAGE_CHECK,
        scope=CoverageScope(
            component_ids=sorted({item.component_id for item in sources}),
            document_ids=sorted(
                {item.document.document_id for item in sources if item.document is not None}
            ),
        ),
        reason=reason,
        error=None,
    )


def _agreeing(count: int, singular: str, many: str) -> str:
    return singular if count == 1 else many


def _listing_row(
    template: str, noun: str, sources: Sequence[_Source], item: Callable[[_Source], str]
) -> CoverageItem:
    """A row listing each source by `item`, its count and verbs agreeing with it."""
    count = len(sources)
    return _row(
        template.format(
            threads=plural(count, noun),
            have=_agreeing(count, "has", "have"),
            were=_agreeing(count, "was", "were"),
            items=LIST_SEPARATOR.join(item(source) for source in sources),
        ),
        sources,
    )


def _text_item(source: _Source) -> str:
    """`'{text}' on {id}`, or `no designation on {id}`; with the tail when it has no part."""
    if source.written:
        item = TEXT_ITEM.format(text=source.written, id=source.entity_id)
    else:
        item = NO_DESIGNATION_ITEM.format(id=source.entity_id)
    return item if source.document is not None else item + NOT_IN_PACKAGE_TAIL


def _suppressed_item(source: _Source) -> str:
    if source.kind == "hole":
        return HOLE_ENTRY.format(feature=source.feature_name, ids=source.entity_id)
    return SUPPRESSED_FASTENER_ITEM.format(id=source.entity_id, component=source.component_id)


def _ids(sources: Iterable[_Source]) -> str:
    return LIST_SEPARATOR.join(item.entity_id for item in sources)


def _checked_row(coarse: Sequence[_Judged]) -> CoverageItem:
    entries = [
        CHECKED_ENTRY.format(designation=item.written, ids=_ids(item.sources))
        for item in _designations(coarse)
    ]
    count = len(coarse)
    reason = CHECKED.format(
        threads=plural(count, "thread"),
        have=_agreeing(count, "has", "have"),
        entries=LIST_SEPARATOR.join(entries),
    )
    unwritten = sum(1 for item in coarse if item.verdict.no_pitch_written)
    if unwritten:
        reason += NO_PITCH_WRITTEN.format(
            count=unwritten, have=_agreeing(unwritten, "has", "have")
        )
    return _row(reason, [item.source for item in coarse])


def _bought_row(bought: Sequence[_Source]) -> CoverageItem:
    """One entry per part, in the order of its first source; parts are told apart by document,
    since two files of one name can sit in two folders."""
    by_part: dict[str, tuple[Document, list[_Source]]] = {}
    for item in bought:
        assert item.document is not None
        by_part.setdefault(item.document.document_id, (item.document, []))[1].append(item)
    count = len(bought)
    reason = BOUGHT.format(
        threads=plural(count, "thread"),
        were=_agreeing(count, "was", "were"),
        entries=LIST_SEPARATOR.join(
            BOUGHT_ENTRY.format(part=document.file_name, ids=_ids(items))
            for document, items in by_part.values()
        ),
    )
    return _row(reason, bought)


def _unread_gaps(package: EvidencePackage) -> list[Gap]:
    """The `hole`, `thread` and `fastener` gaps that name no row of the array their kind stands
    for, by kind, then id with null first, then reason (D20): a gap about a row that was read
    (a hole's axis, a fastener's length) is about a source this check already reads."""
    read: dict[str, set[str]] = {
        "hole": {item.id for item in package.holes},
        "thread": {item.id for item in package.threads},
        "fastener": {item.id for item in package.fasteners},
    }
    kinds = list(read)  # the row's order of kinds: holes, cosmetic threads, fasteners
    unread = [
        gap
        for gap in package.gaps
        if gap.entity_kind in read
        and (gap.entity_id is None or gap.entity_id not in read[gap.entity_kind])
    ]
    return sorted(
        unread,
        key=lambda gap: (
            kinds.index(gap.entity_kind),
            gap.entity_id is not None,
            gap.entity_id or "",
            gap.reason,
        ),
    )


def _not_read_row(package: EvidencePackage, gaps: Sequence[Gap]) -> CoverageItem:
    components = {item.id for item in package.components}
    return CoverageItem(
        check=COVERAGE_CHECK,
        scope=CoverageScope(
            component_ids=sorted(
                {gap.entity_id for gap in gaps if gap.entity_id is not None} & components
            )
        ),
        reason=NOT_READ.format(
            gaps=plural(len(gaps), "extractor gap"),
            reasons=NOT_READ_SEPARATOR.join(gap.reason for gap in gaps),
        ),
        error=None,
    )


def _phases_reason(package: EvidencePackage) -> str | None:
    """Why no hole or fastener phase read this package's threads, or `None` (D17): a profile
    that runs neither, or a fresh `full` dump whose hole or fastener phase never ran. A reused
    package's rows are all `skipped` by design and are not read."""
    profile = package.extractor.profile
    if profile != FULL_PROFILE:
        return PHASES_NOT_RUN_PROFILE.format(profile=profile)
    if package.reused_from is not None:
        return None
    skipped = tuple(
        name
        for name in THREAD_PHASES
        if any(
            phase.name == name and phase.status == "skipped" for phase in package.extractor.phases
        )
    )
    if not skipped:
        return None
    what, phases = PHASES_NOT_RUN_WORDS[skipped]
    return PHASES_NOT_RUN.format(what=what, phases=phases)


def _bare_row(reason: str) -> CoverageItem:
    return CoverageItem(check=COVERAGE_CHECK, scope=CoverageScope(), reason=reason, error=None)


# --- the check -----------------------------------------------------------------------------------


def run_thread_checks(package: EvidencePackage, roles: PartRoles | None = None) -> ThreadChecks:
    """Every thread the package states, flagged, counted or listed (`contracts/fasteners.md`
    section 8), as plain values.

    With the review's part `roles`, a bought part's tapped holes and cosmetic threads are
    listed in the bought row rather than classified, and a finding holding an unclear part's
    tapped hole or cosmetic thread carries the part-roles note while the question is open;
    with none, every part is graded. Fasteners are classified whatever their role.
    """
    table = load_coarse_pitch()
    features = _features_by_document(package)
    sources = _sources(package)

    unreadable: list[_Source] = []
    unknown: list[_Source] = []
    pipe: list[_Source] = []
    bought: list[_Source] = []
    suppressed: list[_Source] = []
    coarse: list[_Judged] = []
    flagged: dict[tuple[str, str], list[_Judged]] = {}
    parts: dict[str, Document] = {}
    for source in sources:
        if source.document is None:
            unreadable.append(source)
            continue
        if (
            source.kind != "fastener"
            and roles is not None
            and not roles.graded(source.document.document_id)
        ):
            bought.append(source)
            continue
        is_suppressed, limit = _suppression(source, features)
        if is_suppressed:
            suppressed.append(source)
            continue
        verdict = classify_pitch(source.text, table)
        judged = _Judged(source, verdict, limit)
        if verdict.pitch_class == "unreadable":
            unreadable.append(source)
        elif verdict.pitch_class == "pipe":
            pipe.append(source)
        elif verdict.pitch_class == "unknown_size":
            unknown.append(source)
        elif verdict.pitch_class == "coarse":
            coarse.append(judged)
        else:
            check = (
                CHECK_NONSTANDARD_PITCH
                if verdict.pitch_class == "nonstandard"
                else CHECK_FINE_PITCH
            )
            parts[source.document.document_id] = source.document
            flagged.setdefault((source.document.document_id, check), []).append(judged)

    findings = tuple(
        _finding(check, parts[document_id], judged, table, roles)
        for (document_id, check), judged in sorted(flagged.items())
    )

    checked = (_checked_row(coarse),) if coarse else ()
    unresolved = tuple(
        _listing_row(template, "thread", listed, _text_item)
        for template, listed in ((UNREADABLE, unreadable), (UNKNOWN_SIZE, unknown))
        if listed
    )
    skipped: list[CoverageItem] = []
    if pipe:
        skipped.append(_listing_row(PIPE, "pipe thread", pipe, _text_item))
    if bought:
        skipped.append(_bought_row(bought))
    if suppressed:
        skipped.append(_listing_row(SUPPRESSED, "thread", suppressed, _suppressed_item))
    full = package.extractor.profile == FULL_PROFILE
    gaps = _unread_gaps(package) if full else []
    if gaps:
        skipped.append(_not_read_row(package, gaps))
    phases = _phases_reason(package)
    if phases is not None:
        skipped.append(_bare_row(phases))
    if full and not sources and not gaps and phases is None:
        skipped.append(_bare_row(NOTHING_AT_ALL))

    return ThreadChecks(
        findings=findings,
        checked=checked,
        unresolved=unresolved,
        skipped=tuple(skipped),
        threads=len(sources),
        coarse=len(coarse),
    )
