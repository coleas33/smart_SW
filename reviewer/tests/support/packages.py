"""Builders for minimal but valid evidence packages (T019).

Kept out of `conftest.py` so the golden fixture generator and the tests can share one
definition. The package deliberately carries a tapped hole whose `thread_depth` is
unknown, with the matching `Gap`: that is the case every fastener check must refuse to
clear (constitution Principle I).
"""

from __future__ import annotations

import base64
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from swreview.ir.models import (
    SCHEMA_VERSION,
    Axis,
    ComponentInstance,
    Design,
    Document,
    EvidencePackage,
    ExtractorInfo,
    Fastener,
    Gap,
    Hole,
    Manifest,
    ManifestEntry,
    Quantity,
    Vec3,
)

PACKAGE_ID = UUID("11111111-2222-4333-8444-555555555555")
CREATED_AT = datetime(2026, 9, 12, 12, 0, 0, tzinfo=UTC)
IDENTITY_TRANSFORM: list[list[float]] = [
    [1.0, 0.0, 0.0, 0.0],
    [0.0, 1.0, 0.0, 0.0],
    [0.0, 0.0, 1.0, 0.0],
    [0.0, 0.0, 0.0, 1.0],
]


def persist_ref(seed: str) -> str:
    """A deterministic, decodable stand-in for GetPersistReference3 bytes."""
    return base64.b64encode(seed.encode("utf-8")).decode("ascii")


def build_manifest() -> Manifest:
    """One entry per document, no discrepancies."""
    return Manifest(
        entries=[
            ManifestEntry(
                document_id="doc:1",
                vault_path="/Designs/cover-assy.SLDASM",
                vault_version=7,
                revision="B",
                configuration="Default",
                local_modified=False,
                export_method="native",
            ),
            ManifestEntry(
                document_id="doc:2",
                vault_path="/Designs/housing.SLDPRT",
                vault_version=3,
                revision="A",
                configuration="Default",
                local_modified=None,
                export_method="native",
            ),
        ],
        discrepancies=[],
    )


def build_package(**overrides: Any) -> EvidencePackage:
    """A minimal valid `EvidencePackage`; `overrides` replace top-level fields."""
    axis = Axis(
        origin=Vec3(x=0.0, y=0.0, z=0.01),
        direction=Vec3(x=0.0, y=0.0, z=1.0),
    )
    fields: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "package_id": PACKAGE_ID,
        "created_at": CREATED_AT,
        "extractor": ExtractorInfo(
            name="SwReview.Extractor",
            version="0.1.0",
            sw_version=None,
            machine="test",
        ),
        "manifest": build_manifest(),
        "design": Design(
            design_id="dsn:1",
            name="cover-assy",
            root_assembly_document_id="doc:1",
            active_configuration="Default",
            drawing_document_ids=[],
        ),
        "documents": [
            Document(
                document_id="doc:1",
                kind="assembly",
                file_name="cover-assy.SLDASM",
                path="native/cover-assy.SLDASM",
                configurations=["Default"],
                active_configuration="Default",
                custom_properties={"Project": "pilot"},
                config_properties={"Default": {"Revision": "B"}},
                material=None,
                mass=None,
            ),
            Document(
                document_id="doc:2",
                kind="part",
                file_name="housing.SLDPRT",
                path="native/housing.SLDPRT",
                configurations=["Default"],
                active_configuration="Default",
                custom_properties={},
                config_properties={},
                material="6061-T6",
                mass=None,
            ),
        ],
        "components": [
            ComponentInstance(
                id="cmp:0001",
                persist_ref=persist_ref("cmp:0001"),
                persist_ref_scope="doc:1",
                name="housing-1",
                full_path="housing-1",
                document_id="doc:2",
                parent_id=None,
                referenced_configuration="Default",
                transform=IDENTITY_TRANSFORM,
                suppression="resolved",
                is_fixed=True,
                pattern_id=None,
                is_toolbox=False,
            ),
            ComponentInstance(
                id="cmp:0002",
                persist_ref=persist_ref("cmp:0002"),
                persist_ref_scope="doc:1",
                name="housing-2",
                full_path="housing-2",
                document_id="doc:2",
                parent_id=None,
                referenced_configuration="Default",
                transform=IDENTITY_TRANSFORM,
                suppression="resolved",
                is_fixed=False,
                pattern_id=None,
                is_toolbox=False,
            ),
        ],
        "holes": [
            Hole(
                id="hole:1",
                persist_ref=persist_ref("hole:1"),
                persist_ref_scope="doc:2",
                component_id="cmp:0001",
                feature_name="M6 Tapped Hole1",
                hole_type="tapped",
                standard="ISO",
                size="M6",
                thread_designation="M6x1.0",
                thread_depth=None,
                hole_depth=Quantity(value=12.0, unit="mm"),
                end_condition="blind",
                diameter=Quantity(value=5.0, unit="mm"),
                axis=axis,
                face_ids=[],
            )
        ],
        "fasteners": [
            Fastener(
                id="fst:1",
                persist_ref=persist_ref("fst:1"),
                persist_ref_scope="doc:1",
                component_id="cmp:0002",
                kind="screw",
                identity_source="name_parse",
                thread_designation="M6x1.0",
                length=Quantity(value=20.0, unit="mm"),
                head_type="socket head cap",
                head_diameter=Quantity(value=10.0, unit="mm"),
                head_height=Quantity(value=6.0, unit="mm"),
                drive=None,
                axis=axis,
                material=None,
            )
        ],
        "gaps": [
            Gap(
                kind="not_extracted",
                entity_kind="hole",
                entity_id="hole:1",
                reason="usable thread depth not reported by the hole feature",
                error=None,
            )
        ],
    }
    fields.update(overrides)
    return EvidencePackage(**fields)
