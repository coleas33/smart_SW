"""Accepted interference exceptions, bound to geometry and configuration (T067).

An exception is the one mechanism that lets the reviewer stay quiet about a condition it
can see, so the constitution (Principle VI) and FR-013 fence it in: it is bound to the
component instances it was accepted for, to the configuration it was accepted in, and to
a fingerprint of the geometry as it stood at acceptance time. Blanket exclusions - "skip
this component", "ignore interferences under 1 mm3" - are deliberately not expressible
here; there is no pattern, no glob and no threshold in this module.

Three consequences of that binding:

- `fingerprint` hashes only what an engineer would look at again: for a geometry
  exception the transforms of the involved components and the parameters of their faces;
  for a feature-tree one (the `rms.*` rules) the feature rows and equations of the
  documents those components instance; for a standards one (the `standards.*` checks)
  every input the sixteen checks read for the one **document** it was accepted on. It is
  order-independent, so the order SOLIDWORKS happened to report components and faces in
  cannot flip an exception, and it is rounded to 1e-9 m, so float noise cannot either.
- `ExceptionStore.match` compares persist references **as strings**. That is a weaker
  test than the real one: SOLIDWORKS alone can tell whether a persist reference still
  resolves to the same instance, so the bridge (`swreview.bridge`, T073) re-checks a
  match against the live document before an exception silences anything on a workstation
  run. String equality is what the offline reviewer can honestly do.
- `refresh` never clears an exception. It can only move `active` to `needs_review`;
  returning to `active` is an engineer's act, through `reaccept`.

The class is `ReviewException`, not `Exception`: data-model.md calls the entity
`Exception`, but that name is taken by the language and shadowing it inside a package
called `swreview.exceptions` would be a trap for every `except` clause downstream.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, SerializerFunctionWrapHandler, model_serializer

from swreview.ids import SequentialIdAllocator
from swreview.ir.models import (
    ComponentInstance,
    CutListItem,
    DrawingRecord,
    DrawingSheetRecord,
    DrawingView,
    Equation,
    EvidencePackage,
    FaceGeometry,
    Feature,
    Mate,
    PersistRef,
    RevisionTable,
    Vec3,
    omit_when_null,
)

__all__ = [
    "EXCEPTIONS_FILE_NAME",
    "RMS_CHECK_PREFIX",
    "STANDARDS_CHECK_PREFIX",
    "ExceptionStatus",
    "ExceptionStore",
    "FingerprintKind",
    "FingerprintTarget",
    "ReviewException",
    "fingerprint",
    "fingerprint_kind_for",
]

EXCEPTIONS_FILE_NAME = "exceptions.json"
"""The file an engineer keeps next to `package.json`, under version control."""

PLACES = 9
"""Transforms and face parameters are hashed to 1e-9 m: a nanometre is below any
modelling intent, and above the float noise a rebuild introduces."""

ExceptionStatus = Literal["active", "needs_review", "retired"]

FingerprintKind = Literal["geometry", "feature_tree", "standards"]
"""What an exception is bound to. `geometry` is every check that reasons about shape;
`feature_tree` is the RMS rules, which read the tree and the equations and never look at
a face; `standards` is the sixteen standards checks, which are graded per **document** and
whose drawing checks have no component instances to bind to at all."""

RMS_CHECK_PREFIX = "rms."
"""The one place the geometry and feature-tree kinds are told apart. Every
resilient-modeling rule id begins with this prefix (`contracts/rules.md`), and those rules
read the feature tree, so an exception accepted for one must be bound to the tree rather
than to the geometry."""

STANDARDS_CHECK_PREFIX = "standards."
"""The same, for the standards family (feature 006 `contracts/rules.md`). These two
prefixes are the only check ids this module knows; nothing else here branches on one."""

_ID_PATTERN = re.compile(r"^EX-([0-9]+)$")


def fingerprint_kind_for(check: str) -> FingerprintKind:
    """The kind of fingerprint an exception for `check` binds to."""
    if check.startswith(RMS_CHECK_PREFIX):
        return "feature_tree"
    if check.startswith(STANDARDS_CHECK_PREFIX):
        return "standards"
    return "geometry"


class FingerprintTarget(Protocol):
    """What `ExceptionStore.accept` needs from the thing being excepted.

    Satisfied by `swreview.findings.Finding` and by
    `swreview.checks.interference.InterferenceGroup`; nothing here imports either, so a
    later check can be excepted without touching this module.
    """

    @property
    def check(self) -> str: ...

    @property
    def component_ids(self) -> Sequence[str]: ...

    @property
    def configuration(self) -> str: ...


class ReviewException(BaseModel):
    """One accepted condition, bound to the geometry and configuration it was accepted for.

    `component_persist_refs` and `persist_ref_scopes` are parallel lists: entry `i` of
    the first is resolved against the document named by entry `i` of the second, which is
    how every other persist reference in the IR is used.

    `geometry_fingerprint` keeps its name for the records already written, but it holds
    the digest of whichever kind `fingerprint_kind` names: an `rms.*` exception stores a
    feature-tree digest there. A record without `fingerprint_kind` is a geometry one,
    which is what every exception written before this field existed was.

    `document_id` is optional with the default `null`, so every record already written
    loads unchanged, and is set for `standards.*` exceptions only. It exists because a
    **drawing** finding has no component instances, and an exception with no bindings at
    all would be the blanket exclusion the constitution prohibits (FR-041).
    """

    model_config = ConfigDict(strict=True, extra="forbid")

    id: str
    check: str
    component_persist_refs: list[PersistRef]
    persist_ref_scopes: list[str]
    configuration: str
    geometry_fingerprint: str
    fingerprint_kind: FingerprintKind = "geometry"
    document_id: str | None = None
    accepted_by: str
    accepted_at: datetime = Field(strict=False)
    note: str
    status: ExceptionStatus = "active"

    @property
    def bindings(self) -> list[tuple[str, str]]:
        """The (persist_ref, scope) pairs this exception is bound to, in a stable order."""
        return sorted(zip(self.component_persist_refs, self.persist_ref_scopes, strict=True))

    @model_serializer(mode="wrap")
    def _omit_null_document_id(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        """Leave `document_id` out when it is null (`omit_when_null`).

        It is null for every geometry and feature-tree exception, which is all of them
        outside the standards family, so an `exceptions.json` the accept command rewrites
        keeps the bytes it had before this field existed.
        """
        return omit_when_null(handler, self, "document_id")


# --- fingerprint ----------------------------------------------------------------


def _number(value: float) -> str:
    rounded = round(value, PLACES)
    if rounded == 0:
        rounded = 0.0  # -0.0 and 0.0 are the same position.
    return f"{rounded:.{PLACES}f}"


def _numbers(values: Iterable[float]) -> str:
    return ",".join(_number(value) for value in values)


def _point(vector: Vec3) -> str:
    return _numbers((vector.x, vector.y, vector.z))


def _face_token(face: FaceGeometry) -> str:
    """The parameters of one face that an engineer would compare by eye.

    The bounding box and the area are left out on purpose: both are derived from the
    surface and the trimming curves, and both move under a rebuild that changed nothing
    an exception was about.
    """
    if face.kind == "cylinder" and face.cylinder is not None:
        cylinder = face.cylinder
        return (
            "cylinder:"
            f"r={_number(cylinder.radius_m)};"
            f"o={_point(cylinder.axis_origin)};"
            f"d={_point(cylinder.axis_dir)}"
        )
    if face.kind == "plane" and face.plane is not None:
        plane = face.plane
        return f"plane:o={_point(plane.origin)};n={_point(plane.normal)}"
    return f"{face.kind}:no-parameters-extracted"


def _component_token(component: ComponentInstance, faces: Sequence[FaceGeometry]) -> str:
    transform = ";".join(_numbers(row) for row in component.transform)
    face_tokens = sorted(_face_token(face) for face in faces)
    return f"transform[{transform}]faces[{'|'.join(face_tokens)}]"


def _feature_row(feature: Feature) -> list[object]:
    """The fields of one feature row an RMS rule reads (data-model.md section 3).

    The description's *text* is deliberately not here: an engineer rewording a
    description has not changed what any rule concluded, so only its state is hashed - and
    that state has three values, not two. `rms.intent.every_feature_described` fails on a
    blank description and goes unresolved on a null one (contracts/rules.md), so `None`
    (unreadable), `False` (blank) and `True` (described) must stay apart.
    `sketch.consumer_ids` contributes its length, which is what the rules ask of it, and
    `None` when the extractor could not read the children at all - an unknown count and a
    count of zero are different facts.

    `sketch` and `fillet` each contribute a presence flag ahead of their fields, for the
    same reason: a feature that has no sketch and a sketch whose status and consumers were
    both unreadable would otherwise hash to the same nulls, and they are not the same fact
    - the second is evidence a rule went unresolved on and must re-check.
    """
    sketch = feature.sketch
    fillet = feature.fillet
    radius = None if fillet is None or fillet.default_radius is None else fillet.default_radius
    return [
        feature.index,
        feature.type_name,
        feature.name,
        feature.depth,
        feature.folder_id,
        feature.suppressed,
        None if feature.description is None else feature.description != "",
        sketch is not None,
        None if sketch is None else sketch.raw_status,
        None if sketch is None or sketch.consumer_ids is None else len(sketch.consumer_ids),
        fillet is not None,
        None if radius is None else [_number(radius.value), radius.unit],
        feature.child_ids,
    ]


def _equation_row(equation: Equation) -> list[object]:
    """An equation's left-hand side and whether it is global; the value is not hashed."""
    return [equation.lhs, equation.is_global]


def _document_rows(package: EvidencePackage, document_id: str) -> dict[str, object]:
    """One document's feature rows in index order, plus its equations in index order."""
    features = sorted(
        (item for item in package.features if item.document_id == document_id),
        key=lambda item: item.index,
    )
    equations = sorted(
        (item for item in package.equations if item.document_id == document_id),
        key=lambda item: item.index,
    )
    return {
        "document_id": document_id,
        "features": [_feature_row(item) for item in features],
        "equations": [_equation_row(item) for item in equations],
    }


def _row_key(row: object) -> str:
    return json.dumps(row, separators=(",", ":"), ensure_ascii=False, sort_keys=True)


def _sorted_rows(rows: Iterable[object]) -> list[object]:
    """Rows in an order no dump can change, by their own serialized content.

    The standards evidence has no index to sort by the way a feature row does, and several
    of the records carry a `dsh:`/`dvw:`/`ddm:` id that is a *within-dump* identity: a
    re-dump renumbers them, so an exception must not be bound to one
    (`contracts/ir-additions.md`). Sorting by content is what makes the digest independent
    of both the traversal order and the numbering.
    """
    return sorted(rows, key=_row_key)


def _standards_component_row(component: ComponentInstance, mates: Sequence[Mate]) -> list[object]:
    """One instance as the four instance-signal checks and `one_fixed` read it.

    The unsuppressed mate count is what `fully_mated` grades against the profile's
    one-mate and two-mate prefixes; a suppressed mate constrains nothing.
    """
    unsuppressed = sum(
        1
        for mate in mates
        if not mate.suppressed
        and any(entity.component_id == component.id for entity in mate.entities)
    )
    transparency = component.transparency_raw
    return [
        component.id,
        component.is_fixed,
        component.constrained_status_raw,
        component.visibility_raw,
        None if transparency is None else _number(transparency),
        component.has_appearance_override,
        component.is_pattern_instance,
        unsuppressed,
    ]


def _standards_mate_row(mate: Mate) -> list[object]:
    """One mate as `mate_references` reads it: whether it is live, and how each end
    resolved. The mate's own `mate:` id is left out for the reason the drawing ids are."""
    return [
        mate.suppressed,
        _sorted_rows(
            [entity.component_id, entity.resolution_status] for entity in mate.entities
        ),
    ]


def _standards_feature_row(feature: Feature) -> list[object]:
    """One feature row as `sketches_fully_defined` and `part.rebuild_errors` read it.

    The sketch contributes a presence flag ahead of its two fields, for the reason the
    feature-tree row's does: a feature that has no sketch and a sketch whose status was
    unreadable are different facts, and the second is one a rule went unresolved on.
    """
    sketch = feature.sketch
    return [
        feature.index,
        feature.type_name,
        feature.name,
        feature.error_code,
        sketch is not None,
        None if sketch is None else sketch.raw_status,
        None if sketch is None else sketch.text_segment_count,
    ]


def _standards_cut_list_row(item: CutListItem) -> list[object]:
    """One cut-list item as `cut_list_excluded` reads it, by content and not by `cut:` id:
    a renamed item is not a waiver, and a renumbered one is not a new subject."""
    return [
        item.configuration,
        item.folder_name,
        item.folder_type_name,
        item.name,
        item.body_count,
        item.excluded_from_cut_list,
    ]


def _standards_revision_table_row(table: RevisionTable) -> dict[str, object]:
    """One revision table, cells included: which row and column carry the revision is a
    profile question, so every cell is an input this document's check read."""
    return {
        "current_revision_raw": table.current_revision_raw,
        "row_count": table.row_count,
        "column_count": table.column_count,
        "rows": [
            [row.index, row.is_header, list(row.cells)]
            for row in sorted(table.rows, key=lambda row: row.index)
        ],
    }


def _standards_view_row(view: DrawingView) -> dict[str, object]:
    """One view with the dimension override flags, annotation dangling flags and note
    texts the three remaining drawing checks read off it."""
    return {
        "name": view.name,
        "view_type_raw": view.view_type_raw,
        "referenced_document_id": view.referenced_document_id,
        "referenced_model_path": view.referenced_model_path,
        "dimensions": _sorted_rows(
            [dimension.name, dimension.is_overridden] for dimension in view.display_dimensions
        ),
        "annotations": _sorted_rows(
            [annotation.name, annotation.type_raw, annotation.is_dangling]
            for annotation in view.annotations
        ),
        "notes": _sorted_rows([note.text] for note in view.notes),
    }


def _standards_sheet_row(sheet: DrawingSheetRecord) -> dict[str, object]:
    return {
        "index": sheet.index,
        "name": sheet.name,
        "sheet_format_name": sheet.sheet_format_name,
        "was_active": sheet.was_active,
        "views": _sorted_rows(_standards_view_row(view) for view in sheet.views),
        "revision_tables": _sorted_rows(
            _standards_revision_table_row(table) for table in sheet.revision_tables
        ),
    }


def _standards_drawing_rows(record: DrawingRecord) -> dict[str, object]:
    return {
        "active_sheet_name": record.active_sheet_name,
        "sheets": [
            _standards_sheet_row(sheet)
            for sheet in sorted(record.sheets, key=lambda sheet: sheet.index)
        ],
    }


def _standards_rows(package: EvidencePackage, document_id: str) -> dict[str, object]:
    """Every input the sixteen standards checks read for one document (data-model.md §5).

    Four groups, and which of them is non-empty is what the document's kind decides:

    - the document row itself - its path and file name (which library prefix it is under
      and whether it follows the part-number convention are read off them), its
      configuration, its whole custom-property card (the data-card check's input, so a
      property that appears, disappears or stops being blank re-opens the waiver whatever
      the profile asks for), its material and the configuration that was read in, the
      mass-override flag, the rebuild-error count and the exploded flag;
    - for an assembly, the instances whose parent is an instance of this document, each
      with the seven readings the instance-signal checks make and its unsuppressed mate
      count, plus this document's mates and how each end resolved;
    - for a part, its feature rows in index order and its cut-list items;
    - for a drawing, its sheets, views, dimension override flags, annotation dangling
      flags, revision-table cells and note texts.

    So a **newly appearing subject re-opens the finding for re-review** rather than being
    silenced (SC-008), and a fix elsewhere in the same check re-opens it too - which is the
    conservative direction. What the digest cannot see is a change to the profile itself:
    the record on disk holds no profile, and `check.json` carries the profile's path and
    hash for exactly that comparison.
    """
    row = next((item for item in package.documents if item.document_id == document_id), None)
    if row is None:
        raise LookupError(f"package has no document {document_id}")

    # The instances of this assembly are the ones whose parent is an instance of it - the
    # same reading `checks.standards.assembly` grades. `ComponentInstance.document_id` is
    # the document an instance *is*, not the one it sits in.
    owners = {item.id for item in package.components if item.document_id == document_id}
    children = [item for item in package.components if item.parent_id in owners]
    mates = [item for item in package.mates if item.persist_ref_scope == document_id]
    features = sorted(
        (item for item in package.features if item.document_id == document_id),
        key=lambda item: item.index,
    )
    cut_list = [item for item in package.cut_list_items if item.document_id == document_id]
    drawing = next(
        (item for item in package.drawing_records if item.document_id == document_id), None
    )
    return {
        "document_id": document_id,
        "kind": row.kind,
        "file_name": row.file_name,
        "path": row.path,
        "active_configuration": row.active_configuration,
        "custom_properties": sorted(
            [name, value] for name, value in row.custom_properties.items()
        ),
        "material": row.material,
        "material_configuration": row.material_configuration,
        "mass_overridden": row.mass_overridden,
        "rebuild_error_count": row.rebuild_error_count,
        "is_exploded": row.is_exploded,
        "components": _sorted_rows(
            _standards_component_row(child, mates) for child in children
        ),
        "mates": _sorted_rows(_standards_mate_row(mate) for mate in mates),
        "features": [_standards_feature_row(item) for item in features],
        "cut_list": _sorted_rows(_standards_cut_list_row(item) for item in cut_list),
        "drawing": None if drawing is None else _standards_drawing_rows(drawing),
    }


def fingerprint(
    package: EvidencePackage,
    component_ids: Sequence[str],
    kind: FingerprintKind = "geometry",
    *,
    document_id: str | None = None,
) -> str:
    """A SHA-256 over what an exception of `kind` was accepted for.

    `geometry` hashes the sorted set of per-component tokens, each holding that
    component's transform and the sorted parameters of its faces. Sorting at both levels
    is what makes the digest independent of the order components and faces arrive in;
    rounding to `PLACES` is what makes it independent of rebuild noise. A changed
    radius, a moved component or a face that appeared or disappeared all change it.

    `feature_tree` hashes the documents those components instance instead: every feature
    row in index order over the fields an RMS rule reads, and the document's equations.
    An RMS rule never looks at a face, and a feature inserted, renamed, moved, suppressed
    or re-pointed is exactly what should re-open the exception.

    `standards` hashes one **document** instead, named by `document_id`, and needs no
    component at all: a drawing finding has no component instances. Any component ids it
    is given are still checked against the package, but they do not reach the digest -
    the binding is the document, so a second offending subject re-opens the waiver.

    Component ids that the package does not contain raise `LookupError`, and so does a
    `document_id` it does not contain: an exception must never be silently re-bound to
    whatever is left.
    """
    if kind == "standards":
        if document_id is None:
            raise ValueError(
                "a standards fingerprint needs the document it was accepted on"
            )
    elif not component_ids:
        raise ValueError(f"a {kind} fingerprint needs at least one component")

    by_id = {component.id: component for component in package.components}
    missing = [cid for cid in component_ids if cid not in by_id]
    if missing:
        raise LookupError(f"package has no component {', '.join(sorted(missing))}")

    if kind == "standards":
        assert document_id is not None, "refused above when the standards kind has no document"
        payload = json.dumps(
            _standards_rows(package, document_id),
            separators=(",", ":"),
            ensure_ascii=False,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    if kind == "feature_tree":
        document_ids = sorted({by_id[cid].document_id for cid in component_ids})
        payload = json.dumps(
            [_document_rows(package, document_id) for document_id in document_ids],
            separators=(",", ":"),
            ensure_ascii=False,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    faces_by_component: dict[str, list[FaceGeometry]] = {}
    for face in package.faces:
        faces_by_component.setdefault(face.component_id, []).append(face)

    tokens = sorted(
        _component_token(by_id[cid], faces_by_component.get(cid, []))
        for cid in dict.fromkeys(component_ids)
    )
    return hashlib.sha256("\n".join(tokens).encode("utf-8")).hexdigest()


# --- the store ------------------------------------------------------------------


def _exceptions_file(path: Path | str | None) -> Path | None:
    if path is None:
        return None
    resolved = Path(path)
    return resolved if resolved.suffix == ".json" else resolved / EXCEPTIONS_FILE_NAME


class ExceptionStore:
    """The `exceptions.json` next to a package, and the operations on it.

    Construction never touches the disk: `load()` reads, `save()` writes, and a store
    built with `exceptions=` and no path (the golden fixtures do this) works in memory.
    """

    def __init__(
        self,
        path: Path | str | None = None,
        exceptions: Iterable[ReviewException] | None = None,
    ) -> None:
        self.path = _exceptions_file(path)
        self.exceptions: list[ReviewException] = list(exceptions or ())

    @classmethod
    def from_records(cls, records: Iterable[dict[str, object]]) -> ExceptionStore:
        """A pathless store from the JSON records of `exceptions.json`."""
        return cls(exceptions=[ReviewException(**record) for record in records])

    def load(self) -> ExceptionStore:
        """Read the file into this store and return it; an absent file means none yet."""
        if self.path is None:
            raise ValueError("this exception store has no path to load from")
        if not self.path.is_file():
            self.exceptions = []
            return self
        document = ReviewExceptionFile.model_validate_json(self.path.read_bytes())
        self.exceptions = list(document.exceptions)
        return self

    def save(self) -> Path:
        """Write the store to its file, creating the directory if needed."""
        if self.path is None:
            raise ValueError("this exception store has no path to save to")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        document = ReviewExceptionFile(exceptions=list(self.exceptions))
        self.path.write_text(
            document.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )
        return self.path

    # --- lookup ---------------------------------------------------------------

    def get(self, exception_id: str) -> ReviewException:
        for exception in self.exceptions:
            if exception.id == exception_id:
                return exception
        raise KeyError(f"no exception {exception_id}")

    def for_check(self, check: str | None = None) -> list[ReviewException]:
        """Every exception that is not retired, optionally narrowed to one check."""
        return [
            exception
            for exception in self.exceptions
            if exception.status != "retired" and (check is None or exception.check == check)
        ]

    def match(
        self,
        package: EvidencePackage,
        component_ids: Sequence[str],
        configuration: str,
        check: str,
        document_id: str | None = None,
    ) -> ReviewException | None:
        """The exception bound to exactly these components, configuration, check and document.

        `check` is required, not optional: bindings alone do not identify a condition.
        One part document's component instances carry every RMS rule's exceptions as well
        as any interference exception naming the same instances, so an exception accepted
        for `rms.sketches.not_over_defined` must never come back for an
        `interference.static` query, nor for a different RMS rule.

        `document_id` is what covers **cross-document**, which the check alone does not: a
        standards exception on a drawing has no bindings, so two drawings' waivers would be
        indistinguishable and one would answer for the other (FR-041, RK-11, SC-008). It
        defaults to `None`, which is what an exception written before the field existed
        carries, so every geometry and feature-tree caller matches exactly as it did.

        Retired exceptions never match; `needs_review` ones do, because the caller has to
        report that the accepted condition needs re-review rather than silently re-raise
        the finding as new.

        The comparison is string equality on (persist_ref, scope) pairs. Only SOLIDWORKS
        can say whether a persist reference still resolves to the same instance, so a
        workstation run re-checks this through the bridge before the exception is honored.
        """
        wanted = sorted(_bindings_of(package, component_ids))
        for exception in self.exceptions:
            if exception.status == "retired":
                continue
            if (
                exception.check == check
                and exception.configuration == configuration
                and exception.document_id == document_id
                and exception.bindings == wanted
            ):
                return exception
        return None

    # --- transitions ----------------------------------------------------------

    def accept(
        self,
        finding_like: FingerprintTarget,
        package: EvidencePackage,
        by: str,
        note: str,
        *,
        at: datetime | None = None,
        exception_id: str | None = None,
        document_id: str | None = None,
    ) -> ReviewException:
        """Accept a finding, binding the exception to its components and its evidence.

        The check decides which evidence: an `rms.*` finding binds to the feature tree, a
        `standards.*` one to the document named by `document_id`, everything else to the
        geometry (`fingerprint_kind_for`).

        `document_id` is required for a standards check and refused for every other one. A
        standards acceptance waives the check **on a document**, and a drawing finding
        carries no component instances at all, so without it the record would have no
        binding whatever - the blanket exclusion the constitution prohibits (FR-041).

        The exception is added to the store but not written: the caller decides when to
        `save()`, so a CLI can confirm first.
        """
        component_ids = list(finding_like.component_ids)
        kind = fingerprint_kind_for(finding_like.check)
        if kind == "standards" and document_id is None:
            raise ValueError(
                f"{finding_like.check} is a standards check, so its exception must name the "
                "document it was accepted on: a drawing finding has no component instances, "
                "and an exception bound to nothing is a blanket exclusion"
            )
        if kind != "standards" and document_id is not None:
            raise ValueError(
                f"{finding_like.check} is not a standards check, and document_id is set on "
                "standards exceptions only"
            )
        # Empty by construction, not by accident: a drawing finding carries no instances,
        # and `document_id` above is what the exception is bound by instead.
        bindings = _bindings_of(package, component_ids) if component_ids else []
        exception = ReviewException(
            id=exception_id or self._next_id(),
            check=finding_like.check,
            component_persist_refs=[ref for ref, _ in bindings],
            persist_ref_scopes=[scope for _, scope in bindings],
            configuration=finding_like.configuration,
            geometry_fingerprint=fingerprint(
                package, component_ids, kind, document_id=document_id
            ),
            fingerprint_kind=kind,
            document_id=document_id,
            accepted_by=by,
            accepted_at=at or datetime.now(UTC),
            note=note,
            status="active",
        )
        self.exceptions.append(exception)
        return exception

    def refresh(self, package: EvidencePackage) -> list[ReviewException]:
        """Flag every `active` exception whose evidence or configuration has moved.

        Each exception is recomputed by its own `fingerprint_kind`, so a feature-tree
        exception is not disturbed by a component moving and a geometry one is not
        disturbed by a feature being renamed.

        Returns the exceptions this call changed. An exception whose components are no
        longer in the package is flagged too: the binding cannot be verified, and an
        unverifiable exception must not keep silencing a check (FR-013).
        """
        changed: list[ReviewException] = []
        by_binding = _binding_index(package)
        for exception in self.exceptions:
            if exception.status != "active":
                continue
            if exception.configuration != package.design.active_configuration:
                exception.status = "needs_review"
                changed.append(exception)
                continue
            # A standards exception is bound by its document, which is the binding that can
            # fail to verify when it has no instances at all.
            if exception.fingerprint_kind == "standards" and not _has_document(
                package, exception.document_id
            ):
                exception.status = "needs_review"
                changed.append(exception)
                continue
            ids = [by_binding.get(binding) for binding in exception.bindings]
            if any(component_id is None for component_id in ids):
                exception.status = "needs_review"
                changed.append(exception)
                continue
            current = fingerprint(
                package,
                [cid for cid in ids if cid is not None],
                exception.fingerprint_kind,
                document_id=exception.document_id,
            )
            if current != exception.geometry_fingerprint:
                exception.status = "needs_review"
                changed.append(exception)
        return changed

    def reaccept(
        self, exception_id: str, package: EvidencePackage | None = None
    ) -> ReviewException:
        """Return a flagged exception to `active`, re-binding it when a package is given.

        Without a package the status flips and the old fingerprint stands, which is only
        honest when nothing moved. With a package the exception is re-bound to the
        geometry as it is now - the usual case, and the reason `reaccept` exists rather
        than a bare status setter.
        """
        exception = self.get(exception_id)
        if package is not None:
            bindings = _bindings_of(package, _component_ids_of(package, exception))
            exception.component_persist_refs = [ref for ref, _ in bindings]
            exception.persist_ref_scopes = [scope for _, scope in bindings]
            exception.configuration = package.design.active_configuration
            exception.geometry_fingerprint = fingerprint(
                package,
                _component_ids_of(package, exception),
                exception.fingerprint_kind,
                document_id=exception.document_id,
            )
        exception.status = "active"
        return exception

    def retire(self, exception_id: str) -> ReviewException:
        """Retire an exception: it stops matching and never comes back on its own."""
        exception = self.get(exception_id)
        exception.status = "retired"
        return exception

    def _next_id(self) -> str:
        used = [
            int(match.group(1))
            for match in (_ID_PATTERN.match(item.id) for item in self.exceptions)
            if match is not None
        ]
        return next(SequentialIdAllocator(prefix="EX", start=max(used, default=0) + 1))


class ReviewExceptionFile(BaseModel):
    """The on-disk shape of `exceptions.json`: one list, nothing else."""

    model_config = ConfigDict(strict=True, extra="forbid")

    exceptions: list[ReviewException] = Field(default_factory=list)


def _bindings_of(
    package: EvidencePackage, component_ids: Sequence[str]
) -> list[tuple[str, str]]:
    by_id = {component.id: component for component in package.components}
    missing = [cid for cid in component_ids if cid not in by_id]
    if missing:
        raise LookupError(f"package has no component {', '.join(sorted(missing))}")
    return sorted(
        (by_id[cid].persist_ref, by_id[cid].persist_ref_scope)
        for cid in dict.fromkeys(component_ids)
    )


def _has_document(package: EvidencePackage, document_id: str | None) -> bool:
    """Whether `refresh` can still verify a document-bound exception against this package."""
    if document_id is None:
        return False
    return any(item.document_id == document_id for item in package.documents)


def _binding_index(package: EvidencePackage) -> dict[tuple[str, str], str]:
    """`(persist_ref, scope)` to component id: how an exception's binding is looked up."""
    return {
        (component.persist_ref, component.persist_ref_scope): component.id
        for component in package.components
    }


def _component_ids_of(package: EvidencePackage, exception: ReviewException) -> list[str]:
    by_binding = _binding_index(package)
    ids = [by_binding.get(binding) for binding in exception.bindings]
    if any(component_id is None for component_id in ids):
        raise LookupError(
            f"exception {exception.id} is bound to components this package does not contain"
        )
    return [component_id for component_id in ids if component_id is not None]
