"""The package-reuse key and the refusals it cannot make (lever 9, T087 and T088).

Lever 9 (`EfficiencySettings.package_reuse`, **off**, and an extractor-side `--reuse`)
copies a previous run's `package.json` instead of dumping again. Two questions decide
whether that is allowed, and they are deliberately different questions:

- **Is this the same design, dumped the same way?** `package_reuse_key` answers it with a
  SHA-256 over the ordered tuple in data-model.md 9.2, stored as a top-level `reuse_key`
  on `EvidencePackage` so a reader can see what a package claims to be. A key decides
  **matching** and nothing else: two keys that differ mean "dump again", which costs one
  dump and is always safe.
- **Is matching enough?** `reuse_refusals` answers it. Four things change what a review
  would see without changing the key, and each is refused explicitly rather than hoped
  about: unsaved in-memory edits, a non-resolved component, an aborted dump, and a
  document referenced in more than one configuration. Extraction is minutes; a wrong
  finding is hours.

**Why the key needs schema 1.3.0.** VERIFIED that the manifest holds no modification
time, no file size and no content hash (`ir/models.py:187-194`,
`Dump/ManifestBuilder.cs:28-65`): `document_id` is a SHA-1 of the lowercased normalized
**path**, `vault_version` and `revision` are null unless a vault writes them, and
`local_modified` is hardcoded null with an `unsupported` gap on every document of every
dump (`ManifestBuilder.cs:57,92-98`). A key without `file_modified_utc` and
`file_size_bytes` reduces to path and configuration, which says nothing about whether
anything changed. Those two fields arrive in T089; this module reads them off a manifest
entry with `getattr(..., None)`, so a 1.2.0 entry reports **unknown** - and unknown is a
refusal, never a match by default (constitution Principle I).

Everything here is pure: an `EvidencePackage`, the dump options that produced it, and the
live document's save flag go in; a digest and a list of reasons come out. No file is read,
no run folder is scanned and no flag is consulted, so the whole lever is testable on a
machine with no SOLIDWORKS seat. It lives beside the benchmark modules because the A/B
harness is what will price it; nothing in the review path calls it while the flag is off.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from swreview.ir.models import EvidencePackage, ManifestEntry

# --- The dump options that change what a package contains ---------------------------

MESH_FORMATS: tuple[str, ...] = ("glb", "stl", "none")
"""`--meshes`, defaulting to glb (VERIFIED, `Console/CommandLine.cs:151-166`)."""

FACE_SCOPES: tuple[str, ...] = ("needed", "all")
"""`--faces`, defaulting to needed."""

FEATURE_SCOPES: tuple[str, ...] = ("tree", "none")
"""`--features`, defaulting to tree."""

EQUATION_SCOPES: tuple[str, ...] = ("on", "off")
"""`--equations`, defaulting to on."""

RESOLVED = "resolved"
"""The one `ComponentInstance.suppression` value a dump reads in full."""


@dataclass(frozen=True)
class DumpOptions:
    """The four `dump` options that change a package's content, with the CLI's defaults.

    They are arguments rather than package fields because the package does not record
    them today: the key is computed at dump time from what was asked for, and recomputed
    at reuse time from what is being asked for now.
    """

    meshes: str = "glb"
    faces: str = "needed"
    features: str = "tree"
    equations: str = "on"

    def __post_init__(self) -> None:
        for name, allowed in (
            ("meshes", MESH_FORMATS),
            ("faces", FACE_SCOPES),
            ("features", FEATURE_SCOPES),
            ("equations", EQUATION_SCOPES),
        ):
            value = getattr(self, name)
            if value not in allowed:
                raise ValueError(
                    f"{name} must be one of {', '.join(allowed)}; got {value!r}. A typo "
                    "hashed into the key is a package nothing will ever match again."
                )


# --- The parts the key is taken over -------------------------------------------------


@dataclass(frozen=True)
class DocumentKeyPart:
    """One manifest entry's contribution, in `document_id` order.

    `referenced_configurations` is the sorted set of configurations the *components*
    reference this document in: `ManifestEntry.configuration` is the document's own
    active configuration, while `ComponentInstance.referenced_configuration` is per
    instance (VERIFIED, `ir/models.py:245`), so a per-instance switch is otherwise
    invisible. What a *set* still cannot see is refused, see `reuse_refusals`.
    """

    document_id: str
    configuration: str
    referenced_configurations: tuple[str, ...]
    file_modified_utc: datetime | None
    file_size_bytes: int | None


@dataclass(frozen=True)
class ComponentKeyPart:
    """One component instance's suppression state, in `component_id` order.

    `MeshExporter` skips a non-resolved component with a gap
    (`Dump/MeshExporter.cs:57-69`), so resolving one changes what a review can see with no
    file change at all.
    """

    component_id: str
    suppression: str


@dataclass(frozen=True)
class ReuseKeyParts:
    """Everything the key is taken over, in the order data-model.md 9.2 states it.

    `package_id` and `created_at` are deliberately absent: `PackageWriter` assigns
    `Guid.NewGuid()` and a fresh timestamp on every dump (VERIFIED, `:136`), so a key
    including either would never match and the lever could not work.
    """

    extractor_name: str
    extractor_version: str
    schema_version: str
    profile: str
    options: DumpOptions
    root_assembly_document_id: str
    active_configuration: str
    documents: tuple[DocumentKeyPart, ...]
    components: tuple[ComponentKeyPart, ...]


def file_stat(entry: ManifestEntry) -> tuple[datetime | None, int | None]:
    """`(file_modified_utc, file_size_bytes)` of one entry, `None` when unknown.

    The single seam for the schema 1.3.0 fields T089 adds in C#. Until then every entry
    answers `(None, None)`, which `reuse_refusals` turns into a refusal: a key that cannot
    see a change must not be reused on.
    """
    return (
        getattr(entry, "file_modified_utc", None),
        getattr(entry, "file_size_bytes", None),
    )


def referenced_configurations(package: EvidencePackage) -> dict[str, tuple[str, ...]]:
    """Document id to the sorted set of configurations its instances reference."""
    found: dict[str, set[str]] = {}
    for component in package.components:
        found.setdefault(component.document_id, set()).add(component.referenced_configuration)
    return {document_id: tuple(sorted(values)) for document_id, values in found.items()}


def key_parts(package: EvidencePackage, options: DumpOptions) -> ReuseKeyParts:
    """Read the key's parts off a package. Sorted, so a traversal order is not a change."""
    references = referenced_configurations(package)
    documents = []
    for entry in sorted(package.manifest.entries, key=lambda entry: entry.document_id):
        modified, size = file_stat(entry)
        documents.append(
            DocumentKeyPart(
                document_id=entry.document_id,
                configuration=entry.configuration,
                referenced_configurations=references.get(entry.document_id, ()),
                file_modified_utc=modified,
                file_size_bytes=size,
            )
        )
    components = [
        ComponentKeyPart(component_id=component.id, suppression=component.suppression)
        for component in sorted(package.components, key=lambda component: component.id)
    ]
    return ReuseKeyParts(
        extractor_name=package.extractor.name,
        extractor_version=package.extractor.version,
        schema_version=package.schema_version,
        profile=package.extractor.profile,
        options=options,
        root_assembly_document_id=package.design.root_assembly_document_id,
        active_configuration=package.design.active_configuration,
        documents=tuple(documents),
        components=tuple(components),
    )


def canonical_form(parts: ReuseKeyParts) -> str:
    """The exact text the digest is taken over.

    JSON rather than a delimiter-joined string so that no value can impersonate the
    separator: a configuration named `a|b` is one value here, not two.
    """
    body: dict[str, Any] = {
        "extractor_name": parts.extractor_name,
        "extractor_version": parts.extractor_version,
        "schema_version": parts.schema_version,
        "profile": parts.profile,
        "meshes": parts.options.meshes,
        "faces": parts.options.faces,
        "features": parts.options.features,
        "equations": parts.options.equations,
        "root_assembly_document_id": parts.root_assembly_document_id,
        "active_configuration": parts.active_configuration,
        "documents": [
            {
                "document_id": document.document_id,
                "configuration": document.configuration,
                "referenced_configurations": list(document.referenced_configurations),
                "file_modified_utc": _instant(document.file_modified_utc),
                "file_size_bytes": document.file_size_bytes,
            }
            for document in parts.documents
        ],
        "components": [
            {"component_id": component.component_id, "suppression": component.suppression}
            for component in parts.components
        ],
    }
    return json.dumps(body, ensure_ascii=False, separators=(",", ":"), sort_keys=False)


def reuse_key(parts: ReuseKeyParts) -> str:
    """The SHA-256 hex digest of `canonical_form`."""
    return hashlib.sha256(canonical_form(parts).encode("utf-8")).hexdigest()


def package_reuse_key(package: EvidencePackage, options: DumpOptions) -> str:
    """The `EvidencePackage.reuse_key` of a package dumped with these options."""
    return reuse_key(key_parts(package, options))


def _instant(value: datetime | None) -> str | None:
    """A modification time as the instant it is, normalised to UTC.

    The same moment written `+00:00` and `-05:00` is the same file, and a false miss costs
    a whole dump. A naive value is a bug upstream rather than a moment, so it is rendered
    as it stands: without an offset it can never collide with a real instant.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        return value.isoformat()
    return value.astimezone(UTC).isoformat()


# --- What the key cannot catch --------------------------------------------------------

UNSAVED_CHANGES = "unsaved_changes"
SAVE_STATE_UNKNOWN = "save_state_unknown"
UNRESOLVED_COMPONENT = "unresolved_component"
ABORTED_DUMP = "aborted_dump"
AMBIGUOUS_REFERENCED_CONFIGURATION = "ambiguous_referenced_configuration"
UNKNOWN_FILE_STAT = "unknown_file_stat"

REFUSAL_CODES: tuple[str, ...] = (
    UNSAVED_CHANGES,
    SAVE_STATE_UNKNOWN,
    UNRESOLVED_COMPONENT,
    ABORTED_DUMP,
    AMBIGUOUS_REFERENCED_CONFIGURATION,
    UNKNOWN_FILE_STAT,
)
"""The closed list. Clock skew is **not** here: mtime can move backwards, the key is
equality and not ordering, so skew produces a false **miss** - one wasted dump, the safe
direction - never a stale package accepted as fresh."""


@dataclass(frozen=True)
class Refusal:
    """One reason reuse did not happen, in words the pane status line can print."""

    code: str
    reason: str


def reuse_refusals(
    package: EvidencePackage, *, unsaved_changes: bool | None
) -> tuple[Refusal, ...]:
    """Every reason this package must not be reused, not only the first.

    `unsaved_changes` is the live document's `GetSaveFlag` answer, already consulted by
    `suppress-test`: `True` refuses, and `None` - unreadable - refuses too. It is an
    argument rather than a package field because an in-memory edit changes nothing on
    disk, which is exactly why the key cannot see it.
    """
    refusals: list[Refusal] = []
    if unsaved_changes is None:
        refusals.append(
            Refusal(
                SAVE_STATE_UNKNOWN,
                "The active document's save state could not be read, so reuse cannot be "
                "shown to be safe.",
            )
        )
    elif unsaved_changes:
        refusals.append(
            Refusal(
                UNSAVED_CHANGES,
                "The active document has unsaved changes, which no file modification "
                "time can see.",
            )
        )
    for component in sorted(package.components, key=lambda component: component.id):
        if component.suppression != RESOLVED:
            refusals.append(
                Refusal(
                    UNRESOLVED_COMPONENT,
                    f"Component {component.id} is {component.suppression}, so the dump "
                    "read less of it than a resolved dump would.",
                )
            )
    refusals.extend(_aborted_dump_refusals(package))
    for document_id, configurations in sorted(referenced_configurations(package).items()):
        if len(configurations) > 1:
            refusals.append(
                Refusal(
                    AMBIGUOUS_REFERENCED_CONFIGURATION,
                    f"Document {document_id} is referenced in {len(configurations)} "
                    f"configurations ({', '.join(configurations)}), which the key records "
                    "as a set and cannot tell apart per instance.",
                )
            )
    for entry in sorted(package.manifest.entries, key=lambda entry: entry.document_id):
        modified, size = file_stat(entry)
        if modified is None or size is None:
            refusals.append(
                Refusal(
                    UNKNOWN_FILE_STAT,
                    f"Document {entry.document_id} has no recorded modification time or "
                    "file size, so a change to it would be invisible to the key.",
                )
            )
    return tuple(refusals)


def may_reuse(package: EvidencePackage, *, unsaved_changes: bool | None) -> bool:
    """Whether this package may be reused: exactly the absence of refusals."""
    return not reuse_refusals(package, unsaved_changes=unsaved_changes)


def _aborted_dump_refusals(package: EvidencePackage) -> Sequence[Refusal]:
    """A dump that stopped short, by either of the two routes data-model.md 9.3 allows.

    `extractor.completed` is the explicit one and arrives with schema 1.3.0; its absence
    is not itself a refusal, or no package written before that build could be read at all.
    The other route needs nothing new: `PackageWriter.RunPhase` records a failed phase as
    `GapKind.ToolError` with a **null** `entity_id` (`:429-450`, `GapCollector.Record`
    `:72-80`), while a per-entity `tool_error` names its entity and is the ordinary
    unknown a review is built to carry.
    """
    refusals: list[Refusal] = []
    if getattr(package.extractor, "completed", None) is False:
        refusals.append(
            Refusal(ABORTED_DUMP, "The extractor reported that this dump did not complete.")
        )
    for gap in package.gaps:
        if gap.kind == "tool_error" and gap.entity_id is None:
            refusals.append(
                Refusal(
                    ABORTED_DUMP,
                    f"The {gap.entity_kind} phase failed during this dump, so the package "
                    "is missing evidence a fresh dump would hold.",
                )
            )
    return refusals
