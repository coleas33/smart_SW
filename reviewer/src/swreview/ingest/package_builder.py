"""Assemble an evidence package from exported files, or augment a native one (T036).

This is the day-one path of `swreview ingest`: a manifest, a BOM and drawing PDFs
produce a `package.json` with no SOLIDWORKS seat. What the exported files cannot state
is not invented:

- there are no persistent references in a PDF or a CSV, so component instances carry a
  deterministic placeholder (`base64("exported:<document_id>:<n>")`) scoped to the root
  assembly, and one `Gap` per package says so - a placeholder ref resolves to nothing on
  the workstation and must never be mistaken for a real one (Principle IV);
- transforms, suppression, fixity and Toolbox membership are not in the exported files
  either; the same `Gap` names them;
- `extractor.sw_version` is `None`, because no SOLIDWORKS produced this package.

When a native package is given it is the base and it wins: for any `document_id` it
already covers, its documents, component instances and drawing sheets are kept and no
exported stand-in is added (contracts/cli.md, `ingest`).
"""

from __future__ import annotations

import base64
import platform
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from swreview.ingest.bom import BomRow, bom_gaps, read_bom
from swreview.ingest.manifest import ManifestInput, find_discrepancies, read_manifest
from swreview.ingest.pdf_drawing import parse_drawing_pdf
from swreview.ir.loader import load_package, save_package
from swreview.ir.models import (
    SCHEMA_VERSION,
    ComponentInstance,
    Discrepancy,
    Document,
    DrawingSheet,
    EvidencePackage,
    ExtractorInfo,
    Gap,
    Manifest,
    ManifestEntry,
)

__all__ = ["build_package"]

INGEST_NAME = "swreview-ingest"
INGEST_VERSION = "0.1.0"

_DOCUMENT_KINDS = {
    ".sldasm": "assembly",
    ".sldprt": "part",
    ".slddrw": "drawing",
}
_CARRIED_FIELDS = (
    "mates",
    "holes",
    "threads",
    "fasteners",
    "faces",
    "bodies",
    "interferences",
    "captures",
)
"""Native-only entity lists carried through untouched; exported files produce none."""
_IDENTITY_TRANSFORM: list[list[float]] = [
    [1.0, 0.0, 0.0, 0.0],
    [0.0, 1.0, 0.0, 0.0],
    [0.0, 0.0, 1.0, 0.0],
    [0.0, 0.0, 0.0, 1.0],
]
_PLACEHOLDER_REASON = (
    "component instances built from the BOM carry placeholder persist_refs "
    "(base64 of 'exported:<document_id>:<n>'), an identity transform, resolved "
    "suppression and is_toolbox=False; the exported files state none of these, so no "
    "finding may navigate to a SOLIDWORKS entity or rely on component position until a "
    "native extraction replaces them"
)


def build_package(
    package_dir: Path | str,
    manifest_path: Path | str,
    bom_path: Path | str,
    pdf_paths: list[Path] | None = None,
    native_package_path: Path | str | None = None,
) -> EvidencePackage:
    """Build `package_dir/package.json` from the exported files and return the package.

    `pdf_paths`, when given, replaces the manifest's drawing list; each file is still
    attributed to a document through the manifest, and one that no entry names becomes a
    `Gap` rather than an invented document id. `native_package_path` names a package
    dumped on the workstation; it becomes the base and wins entity by entity.
    """
    manifest = read_manifest(manifest_path)
    rows = read_bom(bom_path)
    native = load_package(native_package_path).package if native_package_path else None

    gaps: list[Gap] = list(native.gaps) if native else []
    documents = _documents(manifest, rows, native)
    components = _components(manifest, rows, native, gaps)
    drawings = _drawings(manifest, pdf_paths, native, gaps)
    entries = _entries(manifest, native)

    provisional = _package(native, entries, [], manifest, documents, components, drawings, gaps)
    gaps.extend(bom_gaps(rows, provisional))
    discrepancies = find_discrepancies(manifest, provisional)

    package = _package(
        native, entries, discrepancies, manifest, documents, components, drawings, gaps
    )
    save_package(package, package_dir)
    return package


def _package(
    native: EvidencePackage | None,
    entries: list[ManifestEntry],
    discrepancies: list[Discrepancy],
    manifest: ManifestInput,
    documents: list[Document],
    components: list[ComponentInstance],
    drawings: list[DrawingSheet],
    gaps: list[Gap],
) -> EvidencePackage:
    """One package from the merged parts; the native design and extractor win."""
    carried: dict[str, list] = {}
    if native is not None:
        for field in _CARRIED_FIELDS:
            carried[field] = list(getattr(native, field))
    return EvidencePackage(
        **{
            **carried,
            "schema_version": SCHEMA_VERSION,
            "package_id": native.package_id if native else uuid4(),
            "created_at": datetime.now(UTC),
            "extractor": native.extractor
            if native
            else ExtractorInfo(
                name=INGEST_NAME,
                version=INGEST_VERSION,
                sw_version=None,
                machine=platform.node(),
            ),
            "manifest": Manifest(entries=entries, discrepancies=discrepancies),
            "design": native.design if native else manifest.design,
            "documents": documents,
            "components": components,
            "drawings": drawings,
            "gaps": list(gaps),
        }
    )


def _entries(manifest: ManifestInput, native: EvidencePackage | None) -> list[ManifestEntry]:
    """Native entries first - they state what was actually extracted - then the rest."""
    entries = list(native.manifest.entries) if native else []
    covered = {entry.document_id for entry in entries}
    entries.extend(entry for entry in manifest.entries if entry.document_id not in covered)
    return entries


def _documents(
    manifest: ManifestInput, rows: list[BomRow], native: EvidencePackage | None
) -> list[Document]:
    documents = list(native.documents) if native else []
    covered = {document.document_id for document in documents}
    by_document = {row.document_id: row for row in rows}
    for entry in manifest.entries:
        if entry.document_id in covered:
            continue
        documents.append(_document(entry, by_document.get(entry.document_id), manifest))
    return documents


def _document(entry: ManifestEntry, row: BomRow | None, manifest: ManifestInput) -> Document:
    """A document known only from its manifest entry and, when present, its BOM line.

    `custom_properties` keys are prefixed `BOM:` so the BOM is never mistaken for the
    document's own SOLIDWORKS custom properties; material, mass and configurations
    beyond the one reviewed are unknown and stay so.
    """
    vault_path = Path(entry.vault_path)
    kind = _DOCUMENT_KINDS.get(vault_path.suffix.lower())
    if kind is None:
        kind = "drawing" if entry.document_id in manifest.drawings else "part"
    properties: dict[str, str] = {}
    if row is not None:
        properties = {"BOM:Description": row.description, "BOM:Part Number": row.part_number}
    return Document(
        document_id=entry.document_id,
        kind=kind,  # type: ignore[arg-type]
        file_name=vault_path.name,
        path=entry.vault_path,
        configurations=[entry.configuration],
        active_configuration=entry.configuration,
        custom_properties=properties,
        config_properties={},
        material=None,
        mass=None,
    )


def _components(
    manifest: ManifestInput,
    rows: list[BomRow],
    native: EvidencePackage | None,
    gaps: list[Gap],
) -> list[ComponentInstance]:
    """Native instances, then one placeholder per BOM quantity for the documents left."""
    components = list(native.components) if native else []
    covered = {component.document_id for component in components}
    next_number = 1 + max(
        (int(component.id.removeprefix("cmp:")) for component in components), default=0
    )

    placeholders = 0
    paths = {entry.document_id: entry.vault_path for entry in manifest.entries}
    scope = manifest.design.root_assembly_document_id
    for row in rows:
        if row.document_id in covered or row.document_id not in paths:
            continue
        stem = Path(paths[row.document_id]).stem
        for instance in range(1, row.quantity + 1):
            components.append(
                ComponentInstance(
                    id=f"cmp:{next_number:04d}",
                    persist_ref=_placeholder_ref(row.document_id, instance),
                    persist_ref_scope=scope,
                    name=f"{stem}-{instance}",
                    full_path=f"{stem}-{instance}",
                    document_id=row.document_id,
                    parent_id=None,
                    referenced_configuration=row.configuration,
                    transform=_IDENTITY_TRANSFORM,
                    suppression="resolved",
                    is_fixed=False,
                    pattern_id=None,
                    is_toolbox=False,
                )
            )
            next_number += 1
            placeholders += 1

    if placeholders:
        gaps.append(
            Gap(
                kind="not_extracted",
                entity_kind="persist_ref",
                entity_id=None,
                reason=_PLACEHOLDER_REASON,
                error=None,
            )
        )
    return components


def _placeholder_ref(document_id: str, instance: int) -> str:
    return base64.b64encode(f"exported:{document_id}:{instance}".encode()).decode("ascii")


def _drawings(
    manifest: ManifestInput,
    pdf_paths: list[Path] | None,
    native: EvidencePackage | None,
    gaps: list[Gap],
) -> list[DrawingSheet]:
    """Parse the drawing PDFs the native package has no sheets for.

    Every sheet this path adds is stamped `pdf_ingest` by `parse_drawing_pdf`
    (`pdf_drawing.SOURCE`, FR-024); a sheet carried over from the native package keeps the
    source it already recorded, because this function did not write it.
    """
    sheets = list(native.drawings) if native else []
    covered = {sheet.document_id for sheet in sheets}

    for document_id, pdf in _drawing_files(manifest, pdf_paths, gaps):
        if document_id in covered:
            continue
        sheets.extend(parse_drawing_pdf(pdf, document_id, gaps=gaps))
    return sheets


def _drawing_files(
    manifest: ManifestInput, pdf_paths: list[Path] | None, gaps: list[Gap]
) -> list[tuple[str, Path]]:
    """Pair each PDF with the document it belongs to, per the manifest."""
    if pdf_paths is None:
        return [
            (document_id, manifest.base_dir / relative)
            for document_id, relative in manifest.drawings.items()
        ]

    by_name = {
        Path(relative).name: document_id
        for document_id, relative in manifest.drawings.items()
    }
    paired: list[tuple[str, Path]] = []
    for pdf in pdf_paths:
        document_id = by_name.get(Path(pdf).name)
        if document_id is None:
            gaps.append(
                Gap(
                    kind="not_extracted",
                    entity_kind="drawing_sheet",
                    entity_id=Path(pdf).name,
                    reason=(
                        f"{Path(pdf).name} was offered for ingest but no manifest drawing "
                        "entry names it; its sheets belong to no document and were not read"
                    ),
                    error=None,
                )
            )
            continue
        paired.append((document_id, Path(pdf)))
    return paired
