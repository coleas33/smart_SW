"""Where a tolerance comes from, and the one question every stack-up asks (feature 010).

`contracts/tolerances.md` section 4 and `data-model.md` section 5 are normative. A check
that needs a tolerance asks a `ToleranceLookup` about a *subject* - a hole's size, a pin's
size, a hole's position - and gets back either a `ResolvedTolerance`, naming the source it
came from and carrying the `Dimension` `checks/result.limits_mm` reads, or an
`UnresolvedTolerance` listing every source searched and why none bound. There is no third
answer and no default: a tolerance the evidence does not contain is never inferred
(constitution Principle I, FR-025, SC-007).

This module landed with User Story 3, before any tolerance was read, with the types and
`NoSources`, whose every answer is unresolved. User Story 8 adds the readers - the ISO 286
table and the profile's general block - and `resolve_tolerance`, which walks the five sources
in precedence; `ResolverLookup` replaces `NoSources` as `check_joints`' lookup, and the
stack-up does not change when it does.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Protocol

import yaml

from swreview import units
from swreview.checks.result import limits_mm, round_length
from swreview.ir.models import (
    Dimension,
    EvidencePackage,
    ModelAnnotation,
    ModelDimension,
    Quantity,
    SourceRef,
    Tolerance,
)

if TYPE_CHECKING:  # the standards package reaches the runner; only the type is needed here
    from swreview.checks.standards.profile import StandardsProfile

__all__ = [
    "DEFAULT_ISO286_PATH",
    "DRAWING_NOT_AVAILABLE",
    "NO_SOURCE_READ_YET",
    "SOURCE_LABELS",
    "SOURCE_ORDER",
    "Iso286",
    "NoSources",
    "ResolvedTolerance",
    "ResolverLookup",
    "SourceKind",
    "SubjectKind",
    "ToleranceLookup",
    "ToleranceSubject",
    "UnresolvedTolerance",
    "drawing_tolerance",
    "general_tolerance_dimension",
    "iso_dimension",
    "load_iso286",
    "resolve_tolerance",
]

SourceKind = Literal["drawing", "annotation", "model_dimension", "hole_wizard", "general"]
SubjectKind = Literal["hole_size", "pin_size", "hole_position"]

SOURCE_ORDER: tuple[SourceKind, ...] = (
    "drawing",
    "annotation",
    "model_dimension",
    "hole_wizard",
    "general",
)
"""The sources in precedence (research R2.18): the first that binds a subject wins."""

SOURCE_LABELS: dict[SourceKind, str] = {
    "drawing": "drawing callout",
    "annotation": "model annotation",
    "model_dimension": "model dimension",
    "hole_wizard": "Hole Wizard class",
    "general": "general tolerance",
}
"""How a finding names each source to an engineer."""

NO_SOURCE_READ_YET = "no tolerance source is read yet"


@dataclass(frozen=True)
class ToleranceSubject:
    """What a contributor to a stack-up is: whose size or position, and how big nominally."""

    kind: SubjectKind
    nominal_mm: float
    document_id: str | None
    face_ids: tuple[str, ...] = ()
    instance_id: str | None = None
    component_id: str | None = None
    decimal_places: int | None = None
    """How many decimals the subject's dimension is written to (`.XX` is 2), which selects a
    general tolerance band. Only a drawing records it (feature 011); model-side subjects carry
    none, so the general block binds nothing for them."""

    @property
    def label(self) -> str:
        """`the size of hol:0018#1`, `the position of hol:0027#2`, `the pin size`."""
        what = {"hole_size": "the size", "pin_size": "the size", "hole_position": "the position"}
        whom = self.instance_id or self.component_id
        if whom is None:
            return "the pin size"
        return f"{what[self.kind]} of {whom}"


@dataclass(frozen=True)
class ResolvedTolerance:
    """A tolerance one source binds to a subject, and where it came from."""

    subject: ToleranceSubject
    source_kind: SourceKind
    cited: str
    """What an engineer opens to check it: the document and entity, or the profile section."""
    dimension: Dimension
    also_found: tuple[SourceKind, ...] = ()
    """Lower-precedence sources that carried a tolerance too."""
    conflict: str | None = None
    """Set when an `also_found` source disagrees; the consuming check makes it a limit."""


@dataclass(frozen=True)
class UnresolvedTolerance:
    """No source binds the subject. Never carries a number."""

    subject: ToleranceSubject
    searched: tuple[tuple[SourceKind, str], ...]
    """One `(source, why it did not bind)` per source, in precedence order."""

    def searched_text(self) -> str:
        return "; ".join(f"{SOURCE_LABELS[source]}: {why}" for source, why in self.searched)


class ToleranceLookup(Protocol):
    """The one question a stack-up asks. `NoSources` now; the resolver from US8."""

    def resolve(self, subject: ToleranceSubject) -> ResolvedTolerance | UnresolvedTolerance:
        """Bind `subject` to a tolerance from the first source that can, or say why not."""
        ...

    def holds_any_source(self) -> bool:
        """Whether any source could bind anything in this package at all. When none can,
        the stack-up is one skipped coverage item for every joint, not a finding per joint
        (`contracts/alignment.md` section 4)."""
        ...


class NoSources:
    """The lookup before any tolerance is read: every subject is unresolved, and says why.

    `resolve` lists all five sources with the same reason, so a stack-up that asks still
    names what it searched (FR-010).
    """

    def resolve(self, subject: ToleranceSubject) -> UnresolvedTolerance:
        return UnresolvedTolerance(
            subject=subject,
            searched=tuple((source, NO_SOURCE_READ_YET) for source in SOURCE_ORDER),
        )

    def holds_any_source(self) -> bool:
        return False


# --- the ISO 286 table (contracts/tolerances.md section 5) ------------------------------------

DEFAULT_ISO286_PATH = Path(__file__).with_name("iso286.yaml")
_ISO_CLASS = re.compile(r"^([A-Za-z]{1,2})(\d{1,2})$")
LENGTH_EQUAL_MM = 1e-6
"""Two lengths closer than this are the same size: the binding tolerance of research R2.18."""


@dataclass(frozen=True)
class Iso286:
    """`iso286.yaml`: IT grades by size range, and the classes the table can turn to limits."""

    version: int
    source: str
    ranges_mm: tuple[tuple[float, float], ...]
    grades_um: Mapping[str, tuple[float, ...]]
    classes: Mapping[str, tuple[Literal["hole", "shaft"], float]]

    def deviations_mm(
        self, designation: str, nominal_mm: float
    ) -> tuple[float, float, Literal["hole", "shaft"]] | str:
        """`(lower, upper, kind)` deviations in mm of a class such as `H7` on `nominal_mm`,
        or the reason the table cannot say: a class, grade or size it does not carry."""
        text = designation.strip()
        match = _ISO_CLASS.match(text)
        if match is None:
            return f"{designation!r} is not an ISO 286 tolerance class"
        letter, grade = match.group(1), f"IT{int(match.group(2))}"
        if letter not in self.classes:
            carried = " and ".join(sorted(self.classes))
            return f"class {text} is not in iso286.yaml, which carries {carried} only"
        if grade not in self.grades_um:
            return f"grade {grade} of {text} is not in iso286.yaml (IT5 to IT11)"
        index = next(
            (
                position
                for position, (over, up_to) in enumerate(self.ranges_mm)
                if over < nominal_mm <= up_to
            ),
            None,
        )
        if index is None:
            return (
                f"{round_length(nominal_mm)!r} mm is outside the sizes iso286.yaml carries "
                f"(over {self.ranges_mm[0][0]:g} up to {self.ranges_mm[-1][1]:g} mm)"
            )
        tolerance = self.grades_um[grade][index] / 1000.0
        kind, fundamental_um = self.classes[letter]
        fundamental = fundamental_um / 1000.0
        if kind == "hole":  # EI is the fundamental deviation; ES = EI + IT
            return round_length(fundamental), round_length(fundamental + tolerance), kind
        return round_length(fundamental - tolerance), round_length(fundamental), kind


def _parse_iso(document: object, path: Path) -> Iso286:
    if not isinstance(document, Mapping):
        raise ValueError(f"{path}: the ISO 286 table must be a mapping")
    ranges = tuple((float(low), float(high)) for low, high in document["size_ranges_mm"])
    grades = {
        str(name): tuple(float(value) for value in row)
        for name, row in document["it_grades_um"].items()
    }
    for name, row in grades.items():
        if len(row) != len(ranges):
            raise ValueError(f"{path}: {name} has {len(row)} values for {len(ranges)} ranges")
    classes: dict[str, tuple[Literal["hole", "shaft"], float]] = {}
    for letter, row in document["classes"].items():
        if row["kind"] not in ("hole", "shaft"):
            raise ValueError(f"{path}: class {letter} kind must be hole or shaft")
        classes[str(letter)] = (row["kind"], float(row["fundamental_deviation_um"]))
    return Iso286(
        version=int(document["version"]),
        source=" ".join(str(document["source"]).split()),
        ranges_mm=ranges,
        grades_um=grades,
        classes=classes,
    )


@lru_cache(maxsize=4)
def _load_iso_cached(path: Path) -> Iso286:
    return _parse_iso(yaml.safe_load(path.read_text(encoding="utf-8")), path)


def load_iso286(path: Path | str | None = None) -> Iso286:
    """Read the ISO 286 table; `path` defaults to the one beside this module. Cached."""
    return _load_iso_cached(Path(path or DEFAULT_ISO286_PATH).resolve())


def _mm(value: float) -> Quantity:
    return Quantity(value=round_length(value), unit="mm")


def iso_dimension(
    designation: str,
    nominal_mm: float,
    document_id: str,
    cited: str,
    table: Iso286 | None = None,
) -> Dimension | str:
    """A `Dimension` with the limits an ISO 286 class gives `nominal_mm`, citing where the
    class was read, or the reason the table cannot turn it to limits."""
    deviations = (table or load_iso286()).deviations_mm(designation, nominal_mm)
    if isinstance(deviations, str):
        return deviations
    lower, upper, _ = deviations
    source = SourceRef(document_id=document_id, annotation=cited)
    return Dimension(
        nominal=_mm(nominal_mm),
        tolerance=Tolerance(kind="bilateral", upper=_mm(upper), lower=_mm(lower), source=source),
        source=source,
        text_as_read=f"⌀{round_length(nominal_mm):g} {designation.strip()}",
    )


# --- the general tolerance block (contracts/tolerances.md section 3) ---------------------------


def _profile_name(profile: StandardsProfile) -> str:
    try:
        return f"the standards profile sha256 {profile.identity.sha256[:12]}"
    except RuntimeError:
        return "the standards profile (built in memory)"


def general_tolerance_dimension(
    profile: StandardsProfile | None, subject: ToleranceSubject
) -> Dimension | str:
    """The general block's tolerance for `subject`, or why it gives none.

    By decimal places (owner answer 2026-09-23): the band for the number of decimals the
    subject's dimension is written to. Never a position zone, never a value the profile does
    not declare, and nothing for a subject whose written precision is not recorded.
    """
    if subject.kind == "hole_position":
        return "a general tolerance block tolerances sizes, never a position zone"
    if profile is None:
        return "no standards profile is attached"
    if profile.general_tolerance is None:
        return f"the profile is version {profile.version}, which declares no general tolerance"
    bands = profile.general_tolerance.linear
    if not bands:
        return "the profile declares no general tolerance band"
    if subject.decimal_places is None:
        return (
            "the precision its dimension is written to is not recorded, so no decimal-place "
            "band applies (a drawing records it, feature 011)"
        )
    band = next((item for item in bands if item.decimal_places == subject.decimal_places), None)
    if band is None:
        return f"the profile declares no band for {subject.decimal_places} decimal places"
    cited = (
        f"general_tolerance of {_profile_name(profile)}, the {band.decimal_places}-decimal band"
    )
    document = subject.document_id or "package"
    source = SourceRef(document_id=document, annotation=cited)
    return Dimension(
        nominal=_mm(subject.nominal_mm),
        tolerance=Tolerance(
            kind="symmetric", upper=_mm(band.plus_minus_mm), lower=None, source=source
        ),
        source=source,
        text_as_read=f"{subject.nominal_mm:.{band.decimal_places}f}",
    )


# --- the resolver (contracts/tolerances.md section 4) -------------------------------------------

DRAWING_NOT_AVAILABLE = "not available before feature 011"

_Answer = tuple[Dimension, str] | str
"""`(dimension, cited)` when a source binds the subject, else why it does not."""

_POSITION_WORDS = ("posi", "position", "conc", "coax")
_ZONE = re.compile(r"(\d*\.?\d+)\s*(mm|in)?", re.IGNORECASE)


def drawing_tolerance(package: EvidencePackage, subject: ToleranceSubject) -> Dimension | None:
    """Source 1's slot (FR-024): feature 011's drawing dimension or hole callout on one of the
    subject's faces. `None` until feature 011 lands native drawing dimensions; it then fills
    this function, and the stack-up reads the records under the same citation rules."""
    del package, subject
    return None


def _subject_refs(package: EvidencePackage, subject: ToleranceSubject) -> set[str]:
    wanted = set(subject.face_ids)
    return {face.persist_ref for face in package.faces if face.id in wanted}


def _frame_zone(annotation: ModelAnnotation) -> tuple[float, str | None, int] | None:
    """The first position or coaxiality frame's zone value and the unit its text states."""
    for frame in annotation.frames:
        words = " ".join([*frame.symbols_raw, frame.symbol_xml_raw or ""]).lower()
        if not any(word in words for word in _POSITION_WORDS) or not frame.values_raw:
            continue
        match = _ZONE.search(frame.values_raw[0])
        if match is not None:
            unit = match.group(2).lower() if match.group(2) else None
            return float(match.group(1)), unit, frame.number
    return None


def _by_annotation(package: EvidencePackage, subject: ToleranceSubject) -> _Answer:
    if not package.model_annotations:
        return "the package carries no model annotation (DimXpert or MBD)"
    refs = _subject_refs(package, subject)
    attached = [
        item
        for item in package.model_annotations
        if item.kind == "gtol" and refs.intersection(item.attached_persist_refs)
    ]
    whom = subject.instance_id or subject.component_id or "the subject"
    if not attached:
        return f"no geometric tolerance is attached to the faces of {whom}"
    if subject.kind != "hole_position":
        return f"the geometric tolerances attached to {whom} state no size tolerance"
    for annotation in sorted(attached, key=lambda item: item.id):
        zone = _frame_zone(annotation)
        if zone is None:
            continue
        value, unit, number = zone
        if unit is None:
            return (
                f"{annotation.id} is attached to {whom} and states a position zone of "
                f"{value!r}, but the part's length unit is not in the package, so the zone's "
                "size is unknown"
            )
        cited = f"{annotation.id} (frame {number}) attached to a face of {whom}"
        source = SourceRef(
            document_id=annotation.document_id,
            annotation=annotation.id,
            persist_ref=annotation.persist_ref,
        )
        return (
            Dimension(
                nominal=Quantity(value=value, unit=unit),  # type: ignore[arg-type]
                tolerance=Tolerance(kind="basic", upper=None, lower=None, source=source),
                source=source,
                text_as_read=f"position {value!r} {unit}",
            ),
            cited,
        )
    return f"no geometric tolerance attached to {whom} is a position or coaxiality zone"


def _diameter_mm(dimension: ModelDimension) -> float | None:
    if not isinstance(dimension.nominal, Quantity):
        return None
    value = units.as_mm(dimension.nominal)
    return 2.0 * value if dimension.dimension_type == "radius" else value


def _doubled(tolerance: Tolerance) -> Tolerance:
    """A radius's tolerance as the diameter's: every length doubled."""
    return tolerance.model_copy(
        update={
            name: None if value is None else value.model_copy(update={"value": 2.0 * value.value})
            for name, value in (("upper", tolerance.upper), ("lower", tolerance.lower))
        }
    )


def _by_model_dimension(
    package: EvidencePackage, subject: ToleranceSubject, iso: Iso286
) -> _Answer:
    if subject.kind == "hole_position":
        return "a diameter dimension tolerances a size, not a position"
    if not package.model_dimensions:
        return "the package carries no model dimension"
    if subject.document_id is None:
        return "the document the subject belongs to is not known"
    matching = [
        item
        for item in package.model_dimensions
        if item.document_id == subject.document_id
        and item.dimension_type in ("diameter", "radius")
        and (size := _diameter_mm(item)) is not None
        and abs(size - subject.nominal_mm) <= LENGTH_EQUAL_MM
    ]
    nominal = round_length(subject.nominal_mm)
    if not matching:
        return f"no diameter or radius dimension of {subject.document_id} is {nominal!r} mm"
    if len(matching) > 1:
        names = ", ".join(item.id for item in sorted(matching, key=lambda item: item.id))
        return (
            f"{len(matching)} dimensions of {subject.document_id} are {nominal!r} mm ({names}), "
            "so none binds to one hole alone"
        )
    dimension = matching[0]
    label = f"{dimension.name} ({dimension.id})"
    tolerance = dimension.tolerance
    if tolerance is None:
        fit = dimension.fit_hole_class if subject.kind == "hole_size" else dimension.fit_shaft_class
        if fit is None:
            return (
                f"dimension {label} carries no tolerance the package can state "
                f"(tolerance type {dimension.tolerance_type_raw})"
            )
        cited = f"dimension {label}: fit class {fit}, per ISO 286-1 (iso286.yaml)"
        built = iso_dimension(fit, subject.nominal_mm, dimension.document_id, cited, iso)
        if isinstance(built, str):
            return f"dimension {label} names fit class {fit}, but {built}"
        return built, cited
    if tolerance.kind in ("none", "basic"):
        return f"dimension {label} is untoleranced ({tolerance.kind})"
    if dimension.dimension_type == "radius":
        tolerance = _doubled(tolerance)
    source = SourceRef(
        document_id=dimension.document_id,
        annotation=dimension.name,
        persist_ref=dimension.persist_ref,
    )
    return (
        Dimension(
            nominal=_mm(subject.nominal_mm),
            tolerance=tolerance,
            source=source,
            text_as_read=dimension.name,
        ),
        f"dimension {label}",
    )


def _by_hole_wizard(package: EvidencePackage, subject: ToleranceSubject, iso: Iso286) -> _Answer:
    if subject.kind != "hole_size" or subject.instance_id is None:
        return "the Hole Wizard states hole sizes only"
    hole_id = subject.instance_id.split("#", 1)[0]
    hole = next((item for item in package.holes if item.id == hole_id), None)
    if hole is None or hole.wizard is None:
        return f"no Hole Wizard data is recorded for {hole_id}"
    raw = hole.wizard.fit_class_raw
    if raw is None:
        return f"no fit class is recorded for {hole_id}"
    cited = f"the Hole Wizard fit class {raw} of {hole_id}, per ISO 286-1 (iso286.yaml)"
    built = iso_dimension(raw, subject.nominal_mm, hole.persist_ref_scope, cited, iso)
    if isinstance(built, str):
        return (
            f"the fit class {raw} of {hole_id} is no ISO 286 class iso286.yaml carries ({built}); "
            "a Hole Wizard fit is a screw clearance fit"
        )
    return built, cited


def _limits(dimension: Dimension, subject: ToleranceSubject) -> tuple[float, float]:
    if subject.kind == "hole_position":
        zone = units.as_mm(dimension.nominal)
        return zone, zone
    limits = limits_mm(dimension)
    return limits.min_mm, limits.max_mm


def resolve_tolerance(
    package: EvidencePackage,
    profile: StandardsProfile | None,
    subject: ToleranceSubject,
    iso: Iso286 | None = None,
) -> ResolvedTolerance | UnresolvedTolerance:
    """The first source that binds `subject`, in precedence, with every lower one that also
    carried a tolerance and a conflict when their limits differ; or every source searched and
    why none bound (`contracts/tolerances.md` section 4). Nothing else produces a limit."""
    iso = iso or load_iso286()
    drawing = drawing_tolerance(package, subject)
    answers: list[tuple[SourceKind, _Answer]] = [
        ("drawing", DRAWING_NOT_AVAILABLE if drawing is None else (drawing, "a drawing callout")),
        ("annotation", _by_annotation(package, subject)),
        ("model_dimension", _by_model_dimension(package, subject, iso)),
        ("hole_wizard", _by_hole_wizard(package, subject, iso)),
        ("general", _general_answer(profile, subject)),
    ]
    bound = [(kind, answer) for kind, answer in answers if not isinstance(answer, str)]
    if not bound:
        return UnresolvedTolerance(
            subject=subject,
            searched=tuple((kind, answer) for kind, answer in answers if isinstance(answer, str)),
        )
    (kind, (dimension, cited)), *others = bound  # type: ignore[misc]
    chosen = _limits(dimension, subject)
    differing = [
        other
        for other, (found, _) in others  # type: ignore[misc]
        if any(
            abs(a - b) > LENGTH_EQUAL_MM
            for a, b in zip(chosen, _limits(found, subject), strict=True)
        )
    ]
    conflict = None
    if differing:
        conflict = (
            f"{SOURCE_LABELS[kind]} and {', '.join(SOURCE_LABELS[item] for item in differing)} "
            f"give {subject.label} different tolerances; the {SOURCE_LABELS[kind]} is used"
        )
    return ResolvedTolerance(
        subject=subject,
        source_kind=kind,
        cited=cited,
        dimension=dimension,
        also_found=tuple(other for other, _ in others),
        conflict=conflict,
    )


def _general_answer(profile: StandardsProfile | None, subject: ToleranceSubject) -> _Answer:
    built = general_tolerance_dimension(profile, subject)
    if isinstance(built, str):
        return built
    assert built.tolerance.source.annotation is not None
    return built, built.tolerance.source.annotation


@dataclass(frozen=True)
class ResolverLookup:
    """The tolerance lookup `check_joints` asks (feature 010 US8, T085): the resolver over one
    package and the profile of the standards run attached to the review, if any."""

    package: EvidencePackage
    profile: StandardsProfile | None = None

    def resolve(self, subject: ToleranceSubject) -> ResolvedTolerance | UnresolvedTolerance:
        return resolve_tolerance(self.package, self.profile, subject)

    def holds_any_source(self) -> bool:
        """Whether any source could bind anything in this package: a model dimension with a
        tolerance or a fit class, a position frame whose value states its unit, or a Hole
        Wizard fit class that is an ISO 286 class. A Hole Wizard screw clearance fit, an
        untoleranced dimension and a unitless frame value can never bind; neither can the
        general block, because no subject's written precision is recorded before feature 011.
        With none of them the stack is one skipped item, rather than an unresolved finding per
        joint that says the same thing."""
        package = self.package
        return (
            any(_dimension_could_bind(item) for item in package.model_dimensions)
            or any(
                (zone := _frame_zone(item)) is not None and zone[1] is not None
                for item in package.model_annotations
                if item.kind == "gtol"
            )
            or any(
                hole.wizard is not None
                and hole.wizard.fit_class_raw is not None
                and _is_carried_class(hole.wizard.fit_class_raw)
                for hole in package.holes
            )
        )


def _dimension_could_bind(dimension: ModelDimension) -> bool:
    if dimension.dimension_type not in ("diameter", "radius"):
        return False
    if dimension.tolerance is not None:
        return dimension.tolerance.kind not in ("none", "basic")
    return dimension.fit_hole_class is not None or dimension.fit_shaft_class is not None


def _is_carried_class(designation: str) -> bool:
    match = _ISO_CLASS.match(designation.strip())
    return match is not None and match.group(1) in load_iso286().classes
