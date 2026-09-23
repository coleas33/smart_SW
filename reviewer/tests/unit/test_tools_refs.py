"""Resolving the entity id the model was shown to the reference SOLIDWORKS needs (008 T054).

The two bridge tools that act on an entity used to take its persistent reference - a base64
string of up to 1,656 characters the model had to copy out of an earlier result. With the
model's view stripped of references (FR-015) they take the short entity id instead, and
`resolve_entity_ref` turns it into the reference server-side (FR-016, research R2.27). It
refuses rather than guesses: an unknown id, an entity with no reference, and an id two kinds
hold with different references are each a refusal naming the id.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from swreview.ir.loader import load_package
from swreview.ir.models import Capture, CosmeticThread, DrawingRecord, EvidencePackage
from swreview.tools.refs import EntityRefRefused, resolve_entity_ref
from tests.support.packages import persist_ref
from tests.support.prerun import prerun_package

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "replay" / "big-assembly"


@pytest.fixture(scope="module")
def package() -> EvidencePackage:
    """The big fixture (components, features, mates, holes, faces, bodies, a cut-list item)
    with the kinds it lacks added: a fastener, a cosmetic thread, a capture with a
    reference and one without, and a drawing record."""
    base = load_package(FIXTURE).package
    component = base.components[0]
    face = base.faces[0]
    fastener = prerun_package().fasteners[0].model_copy(
        update={"id": "fst:0001", "component_id": component.id}
    )
    thread = CosmeticThread(
        id="thr:0001",
        persist_ref=persist_ref("thr:0001"),
        persist_ref_scope=component.document_id,
        component_id=component.id,
        face_id=face.id,
        designation="M6x1.0",
        depth=None,
        is_external=False,
    )
    captures = [
        Capture(
            id="cap:0001",
            persist_ref=persist_ref("cap:0001"),
            component_ids=[component.id],
            file="captures/cap-0001.png",
            view="iso",
            note="a fictional capture",
        ),
        Capture(
            id="cap:0002",
            persist_ref=None,
            component_ids=[],
            file="captures/cap-0002.png",
            view="fit",
            note="a capture with no entity",
        ),
    ]
    return base.model_copy(
        update={
            "fasteners": [fastener],
            "threads": [thread],
            "captures": captures,
            "drawing_records": [DrawingRecord(document_id="doc:9001")],
        }
    )


KINDS = (
    "components",
    "features",
    "mates",
    "holes",
    "threads",
    "fasteners",
    "faces",
    "bodies",
)


@pytest.mark.parametrize("kind", KINDS)
def test_each_kind_resolves_to_its_reference_and_scope(package: EvidencePackage, kind: str) -> None:
    entity = getattr(package, kind)[0]

    assert resolve_entity_ref(package, entity.id) == (entity.persist_ref, entity.persist_ref_scope)


def test_a_cut_list_item_with_a_reference_resolves(package: EvidencePackage) -> None:
    item = next((row for row in package.cut_list_items if row.persist_ref), None)
    if item is None:
        pytest.skip("the fixture's cut-list item carries no reference")
    assert resolve_entity_ref(package, item.id) == (item.persist_ref, item.persist_ref_scope)


def test_a_capture_resolves_with_no_scope(package: EvidencePackage) -> None:
    assert resolve_entity_ref(package, "cap:0001") == (persist_ref("cap:0001"), None)


def test_an_unknown_id_is_refused_by_name(package: EvidencePackage) -> None:
    with pytest.raises(EntityRefRefused, match="cmp:9999"):
        resolve_entity_ref(package, "cmp:9999")


@pytest.mark.parametrize(
    ("entity_id", "kind"), [("cap:0002", "capture"), ("doc:9001", "drawing record")]
)
def test_an_entity_with_no_reference_is_refused_naming_the_id_and_the_kind(
    package: EvidencePackage, entity_id: str, kind: str
) -> None:
    with pytest.raises(EntityRefRefused) as refused:
        resolve_entity_ref(package, entity_id)

    assert entity_id in str(refused.value)
    assert kind in str(refused.value)


def test_a_cut_list_item_with_no_reference_is_refused_naming_the_kind(
    package: EvidencePackage,
) -> None:
    item = package.cut_list_items[0].model_copy(update={"id": "cut:0900", "persist_ref": None})
    with_item = package.model_copy(update={"cut_list_items": [item]})

    with pytest.raises(EntityRefRefused, match="cut-list item"):
        resolve_entity_ref(with_item, "cut:0900")


def test_one_id_under_two_kinds_with_different_references_is_ambiguous(
    package: EvidencePackage,
) -> None:
    clash = package.holes[0].model_copy(update={"id": package.components[0].id})
    clashing = package.model_copy(update={"holes": [clash, *package.holes[1:]]})

    with pytest.raises(EntityRefRefused, match="ambiguous"):
        resolve_entity_ref(clashing, package.components[0].id)


def test_one_id_under_two_kinds_with_the_same_reference_resolves(
    package: EvidencePackage,
) -> None:
    component = package.components[0]
    twin = package.holes[0].model_copy(
        update={"id": component.id, "persist_ref": component.persist_ref}
    )
    twinned = package.model_copy(update={"holes": [twin]})

    assert resolve_entity_ref(twinned, component.id)[0] == component.persist_ref


def test_a_reference_passed_as_an_id_is_unknown(package: EvidencePackage) -> None:
    with pytest.raises(EntityRefRefused, match="no entity"):
        resolve_entity_ref(package, package.components[0].persist_ref)


def test_bodies_appended_after_the_context_was_built_are_found(package: EvidencePackage) -> None:
    grown = package.model_copy(deep=True)
    body = grown.bodies[0].model_copy(update={"id": "body:9999"})
    grown.bodies.append(body)

    assert resolve_entity_ref(grown, "body:9999") == (body.persist_ref, body.persist_ref_scope)
