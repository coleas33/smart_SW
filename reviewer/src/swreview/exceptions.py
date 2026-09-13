"""Accepted interference exceptions, bound to geometry and configuration (T067).

An exception is the one mechanism that lets the reviewer stay quiet about a condition it
can see, so the constitution (Principle VI) and FR-013 fence it in: it is bound to the
component instances it was accepted for, to the configuration it was accepted in, and to
a fingerprint of the geometry as it stood at acceptance time. Blanket exclusions - "skip
this component", "ignore interferences under 1 mm3" - are deliberately not expressible
here; there is no pattern, no glob and no threshold in this module.

Three consequences of that binding:

- `fingerprint` hashes only what an engineer would look at again: the transforms of the
  involved components and the parameters of their faces. It is order-independent, so the
  order SOLIDWORKS happened to report components and faces in cannot flip an exception,
  and it is rounded to 1e-9 m, so float noise cannot either.
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
import re
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from swreview.ids import SequentialIdAllocator
from swreview.ir.models import (
    ComponentInstance,
    EvidencePackage,
    FaceGeometry,
    PersistRef,
    Vec3,
)

__all__ = [
    "EXCEPTIONS_FILE_NAME",
    "ExceptionStatus",
    "ExceptionStore",
    "FingerprintTarget",
    "ReviewException",
    "fingerprint",
]

EXCEPTIONS_FILE_NAME = "exceptions.json"
"""The file an engineer keeps next to `package.json`, under version control."""

PLACES = 9
"""Transforms and face parameters are hashed to 1e-9 m: a nanometre is below any
modelling intent, and above the float noise a rebuild introduces."""

ExceptionStatus = Literal["active", "needs_review", "retired"]

_ID_PATTERN = re.compile(r"^EX-([0-9]+)$")


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
    """

    model_config = ConfigDict(strict=True, extra="forbid")

    id: str
    check: str
    component_persist_refs: list[PersistRef]
    persist_ref_scopes: list[str]
    configuration: str
    geometry_fingerprint: str
    accepted_by: str
    accepted_at: datetime = Field(strict=False)
    note: str
    status: ExceptionStatus = "active"

    @property
    def bindings(self) -> list[tuple[str, str]]:
        """The (persist_ref, scope) pairs this exception is bound to, in a stable order."""
        return sorted(zip(self.component_persist_refs, self.persist_ref_scopes, strict=True))


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


def fingerprint(package: EvidencePackage, component_ids: Sequence[str]) -> str:
    """A SHA-256 over the geometry an exception was accepted for.

    The hashed text is the sorted set of per-component tokens, each holding that
    component's transform and the sorted parameters of its faces. Sorting at both levels
    is what makes the digest independent of the order components and faces arrive in;
    rounding to `PLACES` is what makes it independent of rebuild noise. A changed
    radius, a moved component or a face that appeared or disappeared all change it.

    Component ids that the package does not contain raise `LookupError`: an exception
    must never be silently re-bound to whatever is left.
    """
    if not component_ids:
        raise ValueError("a geometry fingerprint needs at least one component")

    by_id = {component.id: component for component in package.components}
    missing = [cid for cid in component_ids if cid not in by_id]
    if missing:
        raise LookupError(f"package has no component {', '.join(sorted(missing))}")

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
        self, package: EvidencePackage, component_ids: Sequence[str], configuration: str
    ) -> ReviewException | None:
        """The exception bound to exactly these components in this configuration, if any.

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
            if exception.configuration == configuration and exception.bindings == wanted:
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
    ) -> ReviewException:
        """Accept a finding, binding the exception to its components and geometry.

        The exception is added to the store but not written: the caller decides when to
        `save()`, so a CLI can confirm first.
        """
        component_ids = list(finding_like.component_ids)
        bindings = _bindings_of(package, component_ids)
        exception = ReviewException(
            id=exception_id or self._next_id(),
            check=finding_like.check,
            component_persist_refs=[ref for ref, _ in bindings],
            persist_ref_scopes=[scope for _, scope in bindings],
            configuration=finding_like.configuration,
            geometry_fingerprint=fingerprint(package, component_ids),
            accepted_by=by,
            accepted_at=at or datetime.now(UTC),
            note=note,
            status="active",
        )
        self.exceptions.append(exception)
        return exception

    def refresh(self, package: EvidencePackage) -> list[ReviewException]:
        """Flag every `active` exception whose geometry or configuration has moved.

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
            ids = [by_binding.get(binding) for binding in exception.bindings]
            if any(component_id is None for component_id in ids):
                exception.status = "needs_review"
                changed.append(exception)
                continue
            current = fingerprint(package, [cid for cid in ids if cid is not None])
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
                package, _component_ids_of(package, exception)
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
