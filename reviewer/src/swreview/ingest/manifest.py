"""Read `manifest.json` and compare it with the package actually reviewed (T032).

The manifest is what the vault says: one entry per document with its version, revision
and configuration, plus the drawing PDFs exported alongside it. `find_discrepancies`
answers the only question that matters before any engineering conclusion is drawn — is
the package under review the released design? (FR-003, constitution Principle I.)
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from swreview.ir.models import Design, Discrepancy, EvidencePackage, ManifestEntry

__all__ = ["DISCREPANCY_SEVERITY", "ManifestInput", "find_discrepancies", "read_manifest"]

DISCREPANCY_SEVERITY: tuple[str, ...] = (
    "missing_document",
    "local_modification",
    "version_mismatch",
    "config_mismatch",
)
"""Most to least severe.

A document that is absent cannot be reviewed at all; a locally modified one is not what
the vault holds; a stale version is the wrong design; a wrong configuration is the wrong
variant of the right design. Reports lead with this order.
"""


@dataclass(frozen=True)
class ManifestInput:
    """A parsed `manifest.json`: the design, its documents and its exported drawings."""

    design: Design
    entries: tuple[ManifestEntry, ...]
    drawings: dict[str, str]
    """`document_id` to the drawing PDF path, relative to `base_dir`."""
    base_dir: Path
    """The directory holding `manifest.json`; drawing paths resolve against it."""

    def entry(self, document_id: str) -> ManifestEntry | None:
        """The entry for `document_id`, or `None` when the manifest does not name it."""
        for entry in self.entries:
            if entry.document_id == document_id:
                return entry
        return None

    def drawing_path(self, document_id: str) -> Path | None:
        """The absolute path of the drawing PDF exported for `document_id`."""
        relative = self.drawings.get(document_id)
        return None if relative is None else self.base_dir / relative


def read_manifest(path: Path | str) -> ManifestInput:
    """Parse the `manifest.json` at `path`.

    Raises `pydantic.ValidationError` for a malformed design or entry and `ValueError`
    for a duplicate `document_id` or a drawing whose document has no entry: both would
    leave a reviewed document without provenance.
    """
    manifest_file = Path(path).resolve()
    content: dict[str, Any] = json.loads(manifest_file.read_text(encoding="utf-8"))

    design = Design.model_validate(content["design"])
    entries = tuple(ManifestEntry.model_validate(item) for item in content["entries"])

    seen: set[str] = set()
    for entry in entries:
        if entry.document_id in seen:
            raise ValueError(f"manifest names {entry.document_id!r} more than once")
        seen.add(entry.document_id)

    drawings: dict[str, str] = {}
    for item in content.get("drawings", []):
        document_id = item["document_id"]
        if document_id not in seen:
            raise ValueError(f"manifest drawing {document_id!r} has no matching entry")
        drawings[document_id] = item["file"]

    return ManifestInput(
        design=design,
        entries=entries,
        drawings=drawings,
        base_dir=manifest_file.parent,
    )


def find_discrepancies(
    manifest: ManifestInput, package: EvidencePackage
) -> list[Discrepancy]:
    """Compare `manifest` with `package`, most severe discrepancy first.

    The package's own `manifest.entries` carry what was actually extracted (version,
    revision, local modification); `package.documents` carry which configuration was
    read. An unknown value on either side — a `None` version or revision — produces no
    discrepancy: it is a gap, and inventing a mismatch from it would be a guess.
    """
    documents = {document.document_id: document for document in package.documents}
    extracted = {entry.document_id: entry for entry in package.manifest.entries}
    found: list[Discrepancy] = []

    for entry in manifest.entries:
        document = documents.get(entry.document_id)
        if document is None:
            found.append(
                Discrepancy(
                    document_id=entry.document_id,
                    kind="missing_document",
                    expected=entry.vault_path,
                    actual=None,
                    note=(
                        f"the manifest lists {entry.vault_path} but the package holds no "
                        "document with that id; nothing about it was reviewed"
                    ),
                )
            )
            continue
        found.extend(_compare_document(entry, extracted.get(entry.document_id), document))

    for document_id, document in documents.items():
        if manifest.entry(document_id) is not None:
            continue
        found.append(
            Discrepancy(
                document_id=document_id,
                kind="missing_document",
                expected=None,
                actual=document.file_name,
                note=(
                    f"{document.file_name} was reviewed but the manifest has no entry for "
                    "it: no version, revision or configuration provenance is available"
                ),
            )
        )

    found.sort(key=lambda d: (DISCREPANCY_SEVERITY.index(d.kind), d.document_id))
    return found


def _compare_document(
    entry: ManifestEntry,
    extracted: ManifestEntry | None,
    document: Any,
) -> list[Discrepancy]:
    """Version, local-modification and configuration checks for one document."""
    found: list[Discrepancy] = []

    if _is_modified(entry) or (extracted is not None and _is_modified(extracted)):
        found.append(
            Discrepancy(
                document_id=entry.document_id,
                kind="local_modification",
                expected="unmodified",
                actual="locally modified",
                note=(
                    f"{entry.vault_path} is modified locally; the reviewed content does "
                    "not match the vault copy of this version"
                ),
            )
        )

    if extracted is not None:
        found.extend(_compare_version(entry, extracted))

    if document.active_configuration != entry.configuration:
        found.append(
            Discrepancy(
                document_id=entry.document_id,
                kind="config_mismatch",
                expected=entry.configuration,
                actual=document.active_configuration,
                note=(
                    f"the manifest names configuration {entry.configuration!r} but "
                    f"{document.file_name} was reviewed as "
                    f"{document.active_configuration!r}"
                ),
            )
        )
    return found


def _compare_version(entry: ManifestEntry, extracted: ManifestEntry) -> list[Discrepancy]:
    """Version then revision; an unknown value on either side is not a mismatch."""
    if (
        entry.vault_version is not None
        and extracted.vault_version is not None
        and entry.vault_version != extracted.vault_version
    ):
        return [
            Discrepancy(
                document_id=entry.document_id,
                kind="version_mismatch",
                expected=entry.vault_version,
                actual=extracted.vault_version,
                note=(
                    f"the manifest names vault version {entry.vault_version} of "
                    f"{entry.vault_path}; version {extracted.vault_version} was reviewed"
                ),
            )
        ]
    if (
        entry.revision is not None
        and extracted.revision is not None
        and entry.revision != extracted.revision
    ):
        return [
            Discrepancy(
                document_id=entry.document_id,
                kind="version_mismatch",
                expected=entry.revision,
                actual=extracted.revision,
                note=(
                    f"the manifest names revision {entry.revision} of {entry.vault_path}; "
                    f"revision {extracted.revision} was reviewed"
                ),
            )
        ]
    return []


def _is_modified(entry: ManifestEntry) -> bool:
    """`True` only when the entry states a local modification; `None` stays unknown."""
    return entry.local_modified is True
