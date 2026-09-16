"""Forward-compatible package builders for the lever 9 reuse key (T087, T088).

The two fields the key cannot do without - `ManifestEntry.file_modified_utc` and
`file_size_bytes` (data-model.md 9.1, schema 1.3.0) - are written by the C# extractor in
T089, which is blocked on Q6 and is not written yet. The reuse tests must still be able
to say "this file was saved" today, so this module declares the 1.3.0 shape as pydantic
subclasses of the shipped 1.2.0 models and hands them to the ordinary builders:
`Manifest(entries=[...])` keeps a subclass instance as it was given (pydantic does not
re-validate model instances), so the extra members survive into the package.

That is deliberately the same seam the production code reads: `reuse.key_parts` takes
these fields off a manifest entry with `getattr(..., None)`, so a 1.2.0 entry reports
**unknown** - which refuses reuse (`tests/unit/test_reuse_refusals.py`) - and a 1.3.0
entry reports the value, with no change to the module when T089 lands.

`ExtractorInfo13` is the same trick for `extractor.completed`, the first of the two ways
data-model.md 9.3 allows an aborted dump to be refused.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from swreview.ir.models import (
    EvidencePackage,
    ExtractorInfo,
    Manifest,
    ManifestEntry,
)
from tests.support.packages import build_package

MODIFIED = datetime(2026, 9, 10, 8, 30, 0, tzinfo=UTC)
"""`FileInfo.LastWriteTimeUtc` of the root assembly in the baseline package."""

MODIFIED_PART = datetime(2026, 9, 9, 17, 5, 0, tzinfo=UTC)
"""The referenced part's own modification time: its own entry, its own clock."""

SIZE = 262_144
"""`file_size_bytes` of the root assembly in the baseline package."""

SIZE_PART = 98_304
"""`file_size_bytes` of the referenced part."""


class ManifestEntry13(ManifestEntry):
    """A `ManifestEntry` carrying the schema 1.3.0 additions (data-model.md 9.1).

    Both are optional with a `None` default, exactly as T089 will declare them, so a
    package written by an older extractor still loads.
    """

    file_modified_utc: datetime | None = None
    file_size_bytes: int | None = None


class ExtractorInfo13(ExtractorInfo):
    """`ExtractorInfo` carrying `completed`: false means a phase was skipped."""

    completed: bool | None = None


def reuse_entry(
    document_id: str,
    vault_path: str,
    *,
    configuration: str = "Default",
    file_modified_utc: datetime | None = MODIFIED,
    file_size_bytes: int | None = SIZE,
) -> ManifestEntry13:
    """One 1.3.0 manifest entry. The vault fields stay at their VERIFIED null values."""
    return ManifestEntry13(
        document_id=document_id,
        vault_path=vault_path,
        vault_version=None,
        revision=None,
        configuration=configuration,
        local_modified=None,
        export_method="native",
        file_modified_utc=file_modified_utc,
        file_size_bytes=file_size_bytes,
    )


def reuse_manifest(entries: list[ManifestEntry] | None = None) -> Manifest:
    """The two-entry manifest of `build_package`, with the 1.3.0 fields filled in."""
    if entries is None:
        entries = [
            reuse_entry("doc:1", "/Designs/cover-assy.SLDASM"),
            reuse_entry(
                "doc:2",
                "/Designs/housing.SLDPRT",
                file_modified_utc=MODIFIED_PART,
                file_size_bytes=SIZE_PART,
            ),
        ]
    return Manifest(entries=entries, discrepancies=[])


def reuse_package(**overrides: Any) -> EvidencePackage:
    """`build_package` with a 1.3.0 manifest; `overrides` replace top-level fields."""
    fields: dict[str, Any] = {"manifest": reuse_manifest()}
    fields.update(overrides)
    return build_package(**fields)
