"""Unit tests for building an evidence package from exported files (T036).

`build_package` is the day-one path: a manifest, a BOM and drawing PDFs, with no
SOLIDWORKS seat. Everything it cannot know from those files - persistent references,
transforms, suppression, document properties - stays a placeholder with a `Gap` naming
it, and every native entity wins over the exported stand-in for the same document
(contracts/cli.md `ingest`, constitution Principles I and IV).
"""

from __future__ import annotations

import base64
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pymupdf
import pytest

from swreview.ingest.package_builder import build_package
from swreview.ir.loader import load_package, save_package
from swreview.ir.models import EvidencePackage, Manifest, ManifestEntry

MANIFEST: dict[str, Any] = {
    "design": {
        "design_id": "dsn:1",
        "name": "cover-assy",
        "root_assembly_document_id": "ASM-1",
        "active_configuration": "Default",
        "drawing_document_ids": ["DRW-1"],
    },
    "entries": [
        {
            "document_id": "ASM-1",
            "vault_path": "Projects/cover-assy.SLDASM",
            "vault_version": 7,
            "revision": "B",
            "configuration": "Default",
            "local_modified": False,
            "export_method": "manual",
        },
        {
            "document_id": "PRT-1",
            "vault_path": "Projects/housing.SLDPRT",
            "vault_version": 12,
            "revision": "C",
            "configuration": "Default",
            "local_modified": False,
            "export_method": "manual",
        },
        {
            "document_id": "PRT-2",
            "vault_path": "Toolbox/socket head cap screw_am.SLDPRT",
            "vault_version": None,
            "revision": None,
            "configuration": "M6 x 20",
            "local_modified": None,
            "export_method": "manual",
        },
        {
            "document_id": "DRW-1",
            "vault_path": "Projects/housing.SLDDRW",
            "vault_version": 12,
            "revision": "C",
            "configuration": "Default",
            "local_modified": False,
            "export_method": "pdf",
        },
    ],
    "drawings": [{"document_id": "DRW-1", "file": "drawings/housing.pdf"}],
}

BOM = (
    "item,part_number,document_id,description,quantity,configuration\n"
    "1,P-1,PRT-1,Housing 6061-T6,1,Default\n"
    "2,P-2,PRT-2,Socket head cap screw M6 x 20,4,M6 x 20\n"
)


def make_inputs(
    directory: Path, manifest: dict[str, Any] | None = None, bom: str = BOM, *, drawing: bool = True
) -> tuple[Path, Path]:
    """Write `manifest.json`, `bom.csv` and a one-page drawing PDF into `directory`."""
    directory.mkdir(parents=True, exist_ok=True)
    manifest_path = directory / "manifest.json"
    manifest_path.write_text(json.dumps(manifest or MANIFEST, indent=2), encoding="utf-8")
    bom_path = directory / "bom.csv"
    bom_path.write_text(bom, encoding="utf-8")
    if drawing:
        (directory / "drawings").mkdir(exist_ok=True)
        document = pymupdf.open()
        page = document.new_page()
        page.insert_text((60.0, 60.0), "UNITS: MILLIMETERS", fontsize=9)
        page.insert_text((100.0, 200.0), "Ø40 H7", fontsize=10)
        document.save(directory / "drawings" / "housing.pdf")
        document.close()
    return manifest_path, bom_path


def build(directory: Path, **kwargs: Any) -> EvidencePackage:
    manifest_path, bom_path = make_inputs(directory)
    return build_package(directory, manifest_path, bom_path, **kwargs)


# --- exported-only packages --------------------------------------------------------


def test_documents_come_from_the_manifest_entries(tmp_path: Path) -> None:
    package = build(tmp_path / "pkg")

    assert [(d.document_id, d.kind) for d in package.documents] == [
        ("ASM-1", "assembly"),
        ("PRT-1", "part"),
        ("PRT-2", "part"),
        ("DRW-1", "drawing"),
    ]
    housing = package.documents[1]
    assert housing.file_name == "housing.SLDPRT"
    assert housing.active_configuration == "Default"
    assert housing.material is None
    assert housing.mass is None


def test_bom_text_is_kept_under_a_bom_prefixed_key(tmp_path: Path) -> None:
    """The description is real evidence; the key says it came from the BOM, not the file."""
    package = build(tmp_path / "pkg")

    screw = next(d for d in package.documents if d.document_id == "PRT-2")
    assert screw.custom_properties == {
        "BOM:Description": "Socket head cap screw M6 x 20",
        "BOM:Part Number": "P-2",
    }
    assert screw.config_properties == {}


def test_one_component_instance_per_bom_quantity(tmp_path: Path) -> None:
    package = build(tmp_path / "pkg")

    documents = [component.document_id for component in package.components]
    assert documents == ["PRT-1", "PRT-2", "PRT-2", "PRT-2", "PRT-2"]
    assert [component.id for component in package.components] == [
        "cmp:0001",
        "cmp:0002",
        "cmp:0003",
        "cmp:0004",
        "cmp:0005",
    ]
    assert [component.name for component in package.components[1:]] == [
        "socket head cap screw_am-1",
        "socket head cap screw_am-2",
        "socket head cap screw_am-3",
        "socket head cap screw_am-4",
    ]
    assert package.components[1].referenced_configuration == "M6 x 20"


def test_persist_refs_are_deterministic_placeholders_scoped_to_the_root(
    tmp_path: Path,
) -> None:
    package = build(tmp_path / "pkg")

    first = package.components[0]
    assert base64.b64decode(first.persist_ref).decode() == "exported:PRT-1:1"
    assert first.persist_ref_scope == "ASM-1"
    assert base64.b64decode(package.components[4].persist_ref).decode() == "exported:PRT-2:4"


def test_placeholder_refs_are_declared_once_as_a_gap(tmp_path: Path) -> None:
    package = build(tmp_path / "pkg")

    placeholders = [gap for gap in package.gaps if gap.entity_kind == "persist_ref"]
    assert len(placeholders) == 1
    assert placeholders[0].kind == "not_extracted"
    assert "placeholder" in placeholders[0].reason
    assert "SOLIDWORKS" in placeholders[0].reason


def test_extractor_names_the_ingest_and_has_no_solidworks_version(tmp_path: Path) -> None:
    package = build(tmp_path / "pkg")

    assert package.extractor.name == "swreview-ingest"
    assert package.extractor.sw_version is None


def test_design_and_manifest_entries_come_from_the_manifest(tmp_path: Path) -> None:
    package = build(tmp_path / "pkg")

    assert package.design.design_id == "dsn:1"
    assert package.design.root_assembly_document_id == "ASM-1"
    assert [entry.document_id for entry in package.manifest.entries] == [
        "ASM-1",
        "PRT-1",
        "PRT-2",
        "DRW-1",
    ]
    assert package.manifest.discrepancies == []


def test_a_locally_modified_entry_becomes_a_discrepancy(tmp_path: Path) -> None:
    manifest = json.loads(json.dumps(MANIFEST))
    manifest["entries"][1]["local_modified"] = True
    directory = tmp_path / "pkg"
    manifest_path, bom_path = make_inputs(directory, manifest)

    package = build_package(directory, manifest_path, bom_path)

    assert [(d.kind, d.document_id) for d in package.manifest.discrepancies] == [
        ("local_modification", "PRT-1")
    ]


def test_the_package_is_written_and_loads_back(tmp_path: Path) -> None:
    directory = tmp_path / "pkg"
    package = build(directory)

    assert (directory / "package.json").is_file()
    assert load_package(directory).package == package


# --- drawings ---------------------------------------------------------------------


def test_drawings_named_by_the_manifest_are_parsed(tmp_path: Path) -> None:
    package = build(tmp_path / "pkg")

    assert [(sheet.document_id, sheet.page) for sheet in package.drawings] == [("DRW-1", 1)]
    sheet = package.drawings[0]
    assert sheet.units == "mm"
    assert sheet.parse_status == "text"
    assert [d.nominal.value for d in sheet.dimensions] == [40.0]


def test_a_flattened_drawing_page_becomes_a_no_text_gap(tmp_path: Path) -> None:
    directory = tmp_path / "pkg"
    manifest_path, bom_path = make_inputs(directory)
    source = pymupdf.open(directory / "drawings" / "housing.pdf")
    flat = pymupdf.open()
    pixmap = source[0].get_pixmap(dpi=72)
    page = flat.new_page(width=source[0].rect.width, height=source[0].rect.height)
    page.insert_image(page.rect, pixmap=pixmap)
    source.close()
    flat.save(directory / "drawings" / "housing.pdf", incremental=False)
    flat.close()

    package = build_package(directory, manifest_path, bom_path)

    assert [sheet.parse_status for sheet in package.drawings] == ["no_text"]
    no_text = [gap for gap in package.gaps if gap.kind == "no_text"]
    assert [gap.entity_id for gap in no_text] == ["DRW-1:1"]


def test_a_missing_drawing_file_becomes_a_failed_sheet_and_a_gap(tmp_path: Path) -> None:
    directory = tmp_path / "pkg"
    manifest_path, bom_path = make_inputs(directory)
    (directory / "drawings" / "housing.pdf").unlink()

    package = build_package(directory, manifest_path, bom_path)

    assert [sheet.parse_status for sheet in package.drawings] == ["failed"]
    assert any(gap.kind == "tool_error" for gap in package.gaps)


def test_explicit_pdf_paths_override_the_manifest_list(tmp_path: Path) -> None:
    directory = tmp_path / "pkg"
    manifest_path, bom_path = make_inputs(directory)

    package = build_package(
        directory,
        manifest_path,
        bom_path,
        pdf_paths=[directory / "drawings" / "housing.pdf"],
    )

    assert [sheet.document_id for sheet in package.drawings] == ["DRW-1"]


def test_a_pdf_the_manifest_does_not_name_is_a_gap(tmp_path: Path) -> None:
    directory = tmp_path / "pkg"
    manifest_path, bom_path = make_inputs(directory)
    stray = directory / "drawings" / "stray.pdf"
    document = pymupdf.open()
    document.new_page()
    document.save(stray)
    document.close()

    package = build_package(directory, manifest_path, bom_path, pdf_paths=[stray])

    assert package.drawings == []
    unattributed = [gap for gap in package.gaps if gap.entity_id == "stray.pdf"]
    assert len(unattributed) == 1
    assert unattributed[0].kind == "not_extracted"


# --- BOM reconciliation ------------------------------------------------------------


def test_a_bom_document_absent_from_the_manifest_becomes_a_gap(tmp_path: Path) -> None:
    directory = tmp_path / "pkg"
    bom = BOM + "3,P-9,PRT-9,Gasket,1,Default\n"
    manifest_path, bom_path = make_inputs(directory, bom=bom)

    package = build_package(directory, manifest_path, bom_path)

    bom_gaps = [gap for gap in package.gaps if gap.entity_kind == "bom"]
    assert [gap.entity_id for gap in bom_gaps] == ["PRT-9"]
    assert not any(component.document_id == "PRT-9" for component in package.components)


# --- native packages win ------------------------------------------------------------


def native_package_dir(
    tmp_path: Path, make_package: Callable[..., EvidencePackage]
) -> tuple[Path, EvidencePackage]:
    """A saved native package whose one part document is `PRT-1`."""
    package = make_package()
    native = package.model_copy(
        update={
            "manifest": Manifest(
                entries=[
                    ManifestEntry(
                        document_id="PRT-1",
                        vault_path="Projects/housing.SLDPRT",
                        vault_version=12,
                        revision="C",
                        configuration="Default",
                        local_modified=False,
                        export_method="native",
                    )
                ],
                discrepancies=[],
            ),
            "documents": [
                document.model_copy(update={"document_id": "PRT-1"})
                for document in package.documents[1:]
            ],
            "components": [
                component.model_copy(update={"document_id": "PRT-1"})
                for component in package.components[:1]
            ],
            "holes": [],
            "fasteners": [],
            "extractor": package.extractor.model_copy(update={"sw_version": "2024 SP3"}),
        }
    )
    directory = tmp_path / "native"
    save_package(native, directory)
    return directory, native


def test_native_entities_win_for_the_same_document(
    tmp_path: Path, make_package: Callable[..., EvidencePackage]
) -> None:
    native_dir, native = native_package_dir(tmp_path, make_package)
    directory = tmp_path / "pkg"
    manifest_path, bom_path = make_inputs(directory)

    package = build_package(
        directory, manifest_path, bom_path, native_package_path=native_dir
    )

    housing = [d for d in package.documents if d.document_id == "PRT-1"]
    assert len(housing) == 1
    assert housing[0].material == "6061-T6"
    assert housing[0].path == native.documents[0].path
    instances = [c for c in package.components if c.document_id == "PRT-1"]
    assert [c.id for c in instances] == ["cmp:0001"]
    assert instances[0].persist_ref == native.components[0].persist_ref


def test_exported_entities_fill_in_documents_the_native_package_lacks(
    tmp_path: Path, make_package: Callable[..., EvidencePackage]
) -> None:
    native_dir, _ = native_package_dir(tmp_path, make_package)
    directory = tmp_path / "pkg"
    manifest_path, bom_path = make_inputs(directory)

    package = build_package(
        directory, manifest_path, bom_path, native_package_path=native_dir
    )

    assert {d.document_id for d in package.documents} == {"ASM-1", "PRT-1", "PRT-2", "DRW-1"}
    screws = [c for c in package.components if c.document_id == "PRT-2"]
    assert len(screws) == 4
    assert [c.id for c in screws] == ["cmp:0002", "cmp:0003", "cmp:0004", "cmp:0005"]


def test_the_native_extractor_and_its_solidworks_version_are_kept(
    tmp_path: Path, make_package: Callable[..., EvidencePackage]
) -> None:
    native_dir, _ = native_package_dir(tmp_path, make_package)
    directory = tmp_path / "pkg"
    manifest_path, bom_path = make_inputs(directory)

    package = build_package(
        directory, manifest_path, bom_path, native_package_path=native_dir
    )

    assert package.extractor.sw_version == "2024 SP3"
    assert package.extractor.name == "SwReview.Extractor"


def test_native_gaps_are_kept(
    tmp_path: Path, make_package: Callable[..., EvidencePackage]
) -> None:
    native_dir, native = native_package_dir(tmp_path, make_package)
    directory = tmp_path / "pkg"
    manifest_path, bom_path = make_inputs(directory)

    package = build_package(
        directory, manifest_path, bom_path, native_package_path=native_dir
    )

    assert native.gaps[0] in package.gaps


def test_a_version_mismatch_against_the_native_package_is_reported(
    tmp_path: Path, make_package: Callable[..., EvidencePackage]
) -> None:
    native_dir, _ = native_package_dir(tmp_path, make_package)
    manifest = json.loads(json.dumps(MANIFEST))
    manifest["entries"][1]["vault_version"] = 99
    directory = tmp_path / "pkg"
    manifest_path, bom_path = make_inputs(directory, manifest)

    package = build_package(
        directory, manifest_path, bom_path, native_package_path=native_dir
    )

    kinds = [(d.kind, d.document_id) for d in package.manifest.discrepancies]
    assert ("version_mismatch", "PRT-1") in kinds


def test_building_twice_gives_the_same_package_apart_from_its_identity(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "pkg"
    manifest_path, bom_path = make_inputs(directory)

    first = build_package(directory, manifest_path, bom_path)
    second = build_package(directory, manifest_path, bom_path)

    assert first.model_dump(exclude={"package_id", "created_at"}) == second.model_dump(
        exclude={"package_id", "created_at"}
    )


def test_the_builder_refuses_an_answer_key_directory(tmp_path: Path) -> None:
    directory = tmp_path / "benchmarks" / "answer_keys" / "pkg"
    manifest_path, bom_path = make_inputs(directory)

    with pytest.raises(Exception, match="answer_keys"):
        build_package(directory, manifest_path, bom_path)
