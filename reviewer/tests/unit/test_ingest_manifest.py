"""Unit tests for manifest ingest (T023).

The manifest is the provenance record: what the vault says about every document the
review touches. `find_discrepancies` compares it against the package actually reviewed,
because a review of the wrong version or a locally modified file is worth nothing
(constitution Principle I, FR-003).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, get_args

import pytest
from pydantic import ValidationError

from swreview.ingest.manifest import DISCREPANCY_SEVERITY, find_discrepancies, read_manifest
from swreview.ir.models import Discrepancy, EvidencePackage, Manifest, ManifestEntry

REPO_ROOT = Path(__file__).resolve().parents[3]
BENCHMARK_MANIFEST = REPO_ROOT / "benchmarks" / "packages" / "cover-blind-tap" / "manifest.json"


def entry_dict(**overrides: Any) -> dict[str, Any]:
    """A manifest entry matching `make_package`'s `doc:1` unless overridden."""
    entry = {
        "document_id": "doc:1",
        "vault_path": "/Designs/cover-assy.SLDASM",
        "vault_version": 7,
        "revision": "B",
        "configuration": "Default",
        "local_modified": False,
        "export_method": "native",
    }
    entry.update(overrides)
    return entry


def write_manifest(directory: Path, entries: list[dict[str, Any]], **overrides: Any) -> Path:
    """Write a `manifest.json` naming `entries` and return its path."""
    content: dict[str, Any] = {
        "design": {
            "design_id": "dsn:1",
            "name": "cover-assy",
            "root_assembly_document_id": "doc:1",
            "active_configuration": "Default",
            "drawing_document_ids": [],
        },
        "entries": entries,
        "drawings": [],
    }
    content.update(overrides)
    path = directory / "manifest.json"
    path.write_text(json.dumps(content, indent=2), encoding="utf-8")
    return path


# --- read_manifest ---------------------------------------------------------------


def test_read_manifest_parses_design_entries_and_drawings(tmp_path: Path) -> None:
    path = write_manifest(
        tmp_path,
        [
            entry_dict(),
            entry_dict(document_id="doc:2", vault_version=3, revision="A"),
            entry_dict(document_id="drw:1", export_method="pdf"),
        ],
        drawings=[{"document_id": "drw:1", "file": "drawings/housing.pdf"}],
    )

    manifest = read_manifest(path)

    assert manifest.design.design_id == "dsn:1"
    assert manifest.design.root_assembly_document_id == "doc:1"
    assert [e.document_id for e in manifest.entries] == ["doc:1", "doc:2", "drw:1"]
    assert isinstance(manifest.entries[0], ManifestEntry)
    assert manifest.entries[1].vault_version == 3
    assert manifest.drawings == {"drw:1": "drawings/housing.pdf"}
    assert manifest.base_dir == tmp_path


def test_read_manifest_reads_the_benchmark_package() -> None:
    manifest = read_manifest(BENCHMARK_MANIFEST)

    assert manifest.design.design_id == "cover-blind-tap"
    assert len(manifest.entries) == 6
    toolbox = next(e for e in manifest.entries if e.document_id == "PRT-1003")
    assert toolbox.vault_version is None
    assert toolbox.revision is None
    assert toolbox.configuration == "M6 x 20"
    assert manifest.drawings == {
        "DRW-2001": "drawings/housing.pdf",
        "DRW-2002": "drawings/cover.pdf",
    }


def test_read_manifest_lookup_by_document_id(tmp_path: Path) -> None:
    path = write_manifest(tmp_path, [entry_dict(), entry_dict(document_id="doc:2")])

    manifest = read_manifest(path)

    assert manifest.entry("doc:2").document_id == "doc:2"
    assert manifest.entry("doc:9") is None


def test_read_manifest_rejects_an_unknown_export_method(tmp_path: Path) -> None:
    path = write_manifest(tmp_path, [entry_dict(export_method="telepathy")])

    with pytest.raises(ValidationError):
        read_manifest(path)


def test_read_manifest_rejects_a_duplicate_document_id(tmp_path: Path) -> None:
    path = write_manifest(tmp_path, [entry_dict(), entry_dict()])

    with pytest.raises(ValueError, match="doc:1"):
        read_manifest(path)


def test_read_manifest_rejects_a_drawing_with_no_entry(tmp_path: Path) -> None:
    path = write_manifest(
        tmp_path,
        [entry_dict()],
        drawings=[{"document_id": "drw:9", "file": "drawings/x.pdf"}],
    )

    with pytest.raises(ValueError, match="drw:9"):
        read_manifest(path)


# --- find_discrepancies ----------------------------------------------------------


def test_no_discrepancies_when_the_manifest_matches_the_package(
    tmp_path: Path, make_package: Callable[..., EvidencePackage]
) -> None:
    package = make_package()
    path = write_manifest(
        tmp_path,
        [
            entry_dict(),
            entry_dict(
                document_id="doc:2",
                vault_path="/Designs/housing.SLDPRT",
                vault_version=3,
                revision="A",
                local_modified=None,
            ),
        ],
    )

    assert find_discrepancies(read_manifest(path), package) == []


def test_missing_document(tmp_path: Path, make_package: Callable[..., EvidencePackage]) -> None:
    package = make_package()
    path = write_manifest(
        tmp_path,
        [
            entry_dict(),
            entry_dict(document_id="doc:2", vault_version=3, revision="A", local_modified=None),
            entry_dict(document_id="doc:3", vault_path="/Designs/lid.SLDPRT"),
        ],
    )

    found = find_discrepancies(read_manifest(path), package)

    assert [(d.kind, d.document_id) for d in found] == [("missing_document", "doc:3")]
    assert found[0].expected == "/Designs/lid.SLDPRT"
    assert found[0].actual is None


def test_document_reviewed_without_a_manifest_entry_is_a_missing_document(
    tmp_path: Path, make_package: Callable[..., EvidencePackage]
) -> None:
    package = make_package()
    path = write_manifest(tmp_path, [entry_dict()])

    found = find_discrepancies(read_manifest(path), package)

    assert [(d.kind, d.document_id) for d in found] == [("missing_document", "doc:2")]
    assert found[0].expected is None
    assert found[0].actual == "housing.SLDPRT"
    assert "manifest" in found[0].note


def test_version_mismatch(tmp_path: Path, make_package: Callable[..., EvidencePackage]) -> None:
    package = make_package()
    path = write_manifest(
        tmp_path,
        [
            entry_dict(vault_version=9),
            entry_dict(document_id="doc:2", vault_version=3, revision="A", local_modified=None),
        ],
    )

    found = find_discrepancies(read_manifest(path), package)

    assert [(d.kind, d.document_id) for d in found] == [("version_mismatch", "doc:1")]
    assert found[0].expected == 9
    assert found[0].actual == 7


def test_revision_mismatch_is_reported_as_a_version_mismatch(
    tmp_path: Path, make_package: Callable[..., EvidencePackage]
) -> None:
    package = make_package()
    path = write_manifest(
        tmp_path,
        [
            entry_dict(revision="D"),
            entry_dict(document_id="doc:2", vault_version=3, revision="A", local_modified=None),
        ],
    )

    found = find_discrepancies(read_manifest(path), package)

    assert [(d.kind, d.document_id) for d in found] == [("version_mismatch", "doc:1")]
    assert found[0].expected == "D"
    assert found[0].actual == "B"


def test_a_null_vault_version_is_not_a_mismatch(
    tmp_path: Path, make_package: Callable[..., EvidencePackage]
) -> None:
    """An unknown version is a gap, never a mismatch: nothing is assumed about it."""
    package = make_package()
    path = write_manifest(
        tmp_path,
        [
            entry_dict(vault_version=None, revision=None),
            entry_dict(document_id="doc:2", vault_version=3, revision="A", local_modified=None),
        ],
    )

    assert find_discrepancies(read_manifest(path), package) == []


def test_local_modification(tmp_path: Path, make_package: Callable[..., EvidencePackage]) -> None:
    package = make_package()
    path = write_manifest(
        tmp_path,
        [
            entry_dict(local_modified=True),
            entry_dict(document_id="doc:2", vault_version=3, revision="A", local_modified=None),
        ],
    )

    found = find_discrepancies(read_manifest(path), package)

    assert [(d.kind, d.document_id) for d in found] == [("local_modification", "doc:1")]
    assert found[0].actual == "locally modified"


def test_local_modification_reported_by_the_package(
    tmp_path: Path, make_package: Callable[..., EvidencePackage]
) -> None:
    entries = [
        ManifestEntry(**entry_dict()),
        ManifestEntry(**entry_dict(document_id="doc:2", vault_version=3, local_modified=True)),
    ]
    package = make_package(manifest=Manifest(entries=entries, discrepancies=[]))
    path = write_manifest(
        tmp_path,
        [
            entry_dict(),
            entry_dict(document_id="doc:2", vault_version=3, local_modified=False),
        ],
    )

    found = find_discrepancies(read_manifest(path), package)

    assert [(d.kind, d.document_id) for d in found] == [("local_modification", "doc:2")]


def test_config_mismatch(tmp_path: Path, make_package: Callable[..., EvidencePackage]) -> None:
    package = make_package()
    path = write_manifest(
        tmp_path,
        [
            entry_dict(configuration="Machined"),
            entry_dict(document_id="doc:2", vault_version=3, revision="A", local_modified=None),
        ],
    )

    found = find_discrepancies(read_manifest(path), package)

    assert [(d.kind, d.document_id) for d in found] == [("config_mismatch", "doc:1")]
    assert found[0].expected == "Machined"
    assert found[0].actual == "Default"


def test_discrepancies_sorted_by_severity_then_document_id(
    tmp_path: Path, make_package: Callable[..., EvidencePackage]
) -> None:
    package = make_package()
    path = write_manifest(
        tmp_path,
        [
            entry_dict(configuration="Machined"),
            entry_dict(
                document_id="doc:2",
                vault_path="/Designs/housing.SLDPRT",
                vault_version=4,
                revision="A",
                local_modified=True,
            ),
            entry_dict(document_id="doc:3", vault_path="/Designs/lid.SLDPRT"),
            entry_dict(document_id="doc:0", vault_path="/Designs/base.SLDPRT"),
        ],
    )

    found = find_discrepancies(read_manifest(path), package)

    assert [(d.kind, d.document_id) for d in found] == [
        ("missing_document", "doc:0"),
        ("missing_document", "doc:3"),
        ("local_modification", "doc:2"),
        ("version_mismatch", "doc:2"),
        ("config_mismatch", "doc:1"),
    ]
    ranks = [DISCREPANCY_SEVERITY.index(d.kind) for d in found]
    assert ranks == sorted(ranks)


def test_severity_order_covers_every_discrepancy_kind() -> None:
    kinds = get_args(Discrepancy.model_fields["kind"].annotation)
    assert set(DISCREPANCY_SEVERITY) == set(kinds)
