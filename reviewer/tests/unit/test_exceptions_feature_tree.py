"""Unit tests for feature-tree exceptions (T015).

An RMS rule reads the feature tree, not the geometry, so an exception accepted for one
must be bound to the tree: `fingerprint_kind` says which hash a `ReviewException` carries
and `fingerprint(..., kind="feature_tree")` hashes every field the rules read
(data-model.md section 3). Two things are pinned hard here:

- the geometry path is byte-for-byte what it was before the field existed, so the digests
  already written into `exceptions.json` files and into the `bracket-assy-interference`
  golden fixture still match;
- `ExceptionStore.match` takes the check, so an `rms.*` exception accepted for a part's
  component instances can never silence an `interference.static` finding that happens to
  name the same components in the same configuration (FR-013).

The tree is built from IR `Feature` rows directly rather than through a builder: these
tests are the contract for the fingerprint, so what each row holds has to be visible here.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from swreview.exceptions import (
    EXCEPTIONS_FILE_NAME,
    RMS_CHECK_PREFIX,
    ExceptionStore,
    ReviewException,
    ReviewExceptionFile,
    fingerprint,
    fingerprint_kind_for,
)
from swreview.ir.models import (
    Design,
    Equation,
    EvidencePackage,
    Feature,
    FilletInfo,
    Quantity,
    SketchInfo,
)
from tests.support.packages import build_package, persist_ref

ACCEPTED_AT = datetime(2026, 9, 15, 9, 0, 0, tzinfo=UTC)

GOLDEN_EXCEPTIONS = (
    Path(__file__).resolve().parents[1]
    / "golden"
    / "fixtures"
    / "bracket-assy-interference"
    / "exceptions.json"
)

GEOMETRY_DIGEST_BOTH = "351d7938801df7a2b6883fc8274beb9e4ca6013b272f8e343d2e358fd7f12393"
"""The geometry digest of `build_package()` for `cmp:0001` and `cmp:0002`, pinned before
`fingerprint_kind` existed. It must never move: every digest in a shipped
`exceptions.json` was computed by that code path."""

GEOMETRY_DIGEST_ONE = "c1c6df68be2efc552ea93b6d6aac95f8d36730f5b46453d1c70c96143ea7a8f3"

BOTH = ["cmp:0001", "cmp:0002"]

RMS_CHECK = "rms.sketches.not_over_defined"
OTHER_RMS_CHECK = "rms.refs.no_external_references"
INTERFERENCE_CHECK = "interference.static"


# --- the tree under test ---------------------------------------------------------


def feature(
    index: int,
    name: str,
    type_name: str,
    *,
    document_id: str = "doc:2",
    description: str | None = None,
    depth: int = 0,
    folder_id: str | None = None,
    suppressed: bool | None = False,
    error_code: int | None = 0,
    child_ids: list[str] | None = None,
    parent_ids: list[str] | None = None,
    sketch: SketchInfo | None = None,
    fillet: FilletInfo | None = None,
) -> Feature:
    feature_id = f"feat:{index + 1:04d}"
    return Feature(
        id=feature_id,
        persist_ref=persist_ref(feature_id),
        persist_ref_scope=document_id,
        document_id=document_id,
        configuration="Default",
        name=name,
        type_name=type_name,
        description=description,
        index=index,
        depth=depth,
        folder_id=folder_id,
        suppressed=suppressed,
        error_code=error_code,
        child_ids=[] if child_ids is None else child_ids,
        parent_ids=[] if parent_ids is None else parent_ids,
        sketch=sketch,
        fillet=fillet,
    )


def base_features() -> list[Feature]:
    """Three rows covering a sketch, a plain feature, and a fillet inside a folder."""
    return [
        feature(
            0,
            "Sketch1",
            "ProfileFeature",
            description="outer profile",
            sketch=SketchInfo(raw_status=3, consumer_ids=["feat:0002"]),
            child_ids=["feat:0002"],
        ),
        feature(
            1,
            "Boss-Extrude1",
            "Extrusion",
            child_ids=["feat:0003"],
            parent_ids=["feat:0001"],
        ),
        feature(
            2,
            "Fillet1",
            "Fillet",
            description="break sharp edges",
            depth=1,
            folder_id="feat:0002",
            fillet=FilletInfo(default_radius=Quantity(value=0.002, unit="m")),
            parent_ids=["feat:0002"],
        ),
    ]


def base_equations() -> list[Equation]:
    return [
        Equation(
            document_id="doc:2",
            index=0,
            text='"D1@Sketch1" = 25',
            lhs="D1@Sketch1",
            is_global=False,
            value=25.0,
        ),
        Equation(
            document_id="doc:2",
            index=1,
            text='"thickness" = 3',
            lhs="thickness",
            is_global=True,
            value=3.0,
        ),
    ]


def rms_package(
    *,
    features: list[Feature] | None = None,
    equations: list[Equation] | None = None,
    configuration: str = "Default",
) -> EvidencePackage:
    """`build_package` plus a feature tree and equations on `doc:2`.

    Both default components of `build_package` instance `doc:2`, so an exception bound to
    either of them is bound to this tree.
    """
    return build_package(
        features=base_features() if features is None else features,
        equations=base_equations() if equations is None else equations,
        design=Design(
            design_id="dsn:1",
            name="cover-assy",
            root_assembly_document_id="doc:1",
            active_configuration=configuration,
            drawing_document_ids=[],
        ),
    )


def _with(rows: list[Feature], index: int, **updates: Any) -> list[Feature]:
    """`rows` with one row replaced; `model_copy` keeps the test to the changed field."""
    changed = list(rows)
    changed[index] = changed[index].model_copy(update=updates)
    return changed


def _equations_with(index: int, **updates: Any) -> list[Equation]:
    rows = base_equations()
    rows[index] = rows[index].model_copy(update=updates)
    return rows


def tree_moved() -> list[Feature]:
    """The fillet moved ahead of the extrusion: both indices change."""
    rows = base_features()
    rows[1] = rows[1].model_copy(update={"index": 2})
    rows[2] = rows[2].model_copy(update={"index": 1})
    return rows


def tree_inserted() -> list[Feature]:
    rows = base_features()
    rows.append(feature(3, "Chamfer1", "Chamfer"))
    return rows


CHANGED_TREES: dict[str, EvidencePackage] = {
    "inserted": rms_package(features=tree_inserted()),
    "renamed": rms_package(features=_with(base_features(), 1, name="Boss-Extrude2")),
    "retyped": rms_package(features=_with(base_features(), 1, type_name="Cut-Extrude")),
    "moved": rms_package(features=tree_moved()),
    "depth": rms_package(features=_with(base_features(), 2, depth=2)),
    "folder": rms_package(features=_with(base_features(), 2, folder_id="feat:0001")),
    "unfoldered": rms_package(features=_with(base_features(), 2, folder_id=None)),
    "suppressed": rms_package(features=_with(base_features(), 1, suppressed=True)),
    "suppression_unknown": rms_package(features=_with(base_features(), 1, suppressed=None)),
    "description_blanked": rms_package(features=_with(base_features(), 0, description="")),
    "description_lost": rms_package(features=_with(base_features(), 0, description=None)),
    "sketch_status": rms_package(
        features=_with(
            base_features(), 0, sketch=SketchInfo(raw_status=2, consumer_ids=["feat:0002"])
        )
    ),
    "sketch_consumers": rms_package(
        features=_with(
            base_features(),
            0,
            sketch=SketchInfo(raw_status=3, consumer_ids=["feat:0002", "feat:0003"]),
        )
    ),
    "sketch_consumers_unknown": rms_package(
        features=_with(base_features(), 0, sketch=SketchInfo(raw_status=3, consumer_ids=None))
    ),
    "sketch_lost": rms_package(features=_with(base_features(), 0, sketch=None)),
    "fillet_radius": rms_package(
        features=_with(
            base_features(),
            2,
            fillet=FilletInfo(default_radius=Quantity(value=0.003, unit="m")),
        )
    ),
    "fillet_radius_unknown": rms_package(
        features=_with(base_features(), 2, fillet=FilletInfo(default_radius=None))
    ),
    "children": rms_package(features=_with(base_features(), 1, child_ids=[])),
    "children_unknown": rms_package(features=_with(base_features(), 1, child_ids=None)),
    "equation_lhs": rms_package(equations=_equations_with(1, lhs="wall_thickness")),
    "equation_scope": rms_package(equations=_equations_with(1, is_global=False)),
    "equation_scope_unknown": rms_package(equations=_equations_with(1, is_global=None)),
    "equation_removed": rms_package(equations=base_equations()[:1]),
}


class Group:
    """The smallest thing `accept` needs: a check, the components, a configuration."""

    def __init__(
        self, check: str, component_ids: list[str], configuration: str = "Default"
    ) -> None:
        self.check = check
        self.component_ids = component_ids
        self.configuration = configuration


# --- the default and what already shipped ----------------------------------------


def test_fingerprint_kind_defaults_to_geometry() -> None:
    store = ExceptionStore.from_records(
        [
            {
                "id": "EX-001",
                "check": INTERFERENCE_CHECK,
                "component_persist_refs": [persist_ref("cmp:0001")],
                "persist_ref_scopes": ["doc:1"],
                "configuration": "Default",
                "geometry_fingerprint": GEOMETRY_DIGEST_ONE,
                "accepted_by": "engineer",
                "accepted_at": "2026-08-03T09:15:00Z",
                "note": "intended",
                "status": "active",
            }
        ]
    )

    assert store.get("EX-001").fingerprint_kind == "geometry"


def test_the_shipped_golden_exceptions_file_loads_unchanged() -> None:
    record = json.loads(GOLDEN_EXCEPTIONS.read_text(encoding="utf-8"))["exceptions"][0]

    document = ReviewExceptionFile.model_validate_json(GOLDEN_EXCEPTIONS.read_bytes())

    (exception,) = document.exceptions
    assert exception.id == "EX-001"
    assert exception.check == INTERFERENCE_CHECK
    assert exception.fingerprint_kind == "geometry"
    assert exception.status == "active"
    assert exception.geometry_fingerprint == record["geometry_fingerprint"]


def test_the_geometry_digest_is_byte_for_byte_what_it_was() -> None:
    package = build_package()

    assert fingerprint(package, BOTH) == GEOMETRY_DIGEST_BOTH
    assert fingerprint(package, ["cmp:0001"]) == GEOMETRY_DIGEST_ONE
    assert fingerprint(package, BOTH, "geometry") == GEOMETRY_DIGEST_BOTH


def test_a_feature_tree_does_not_move_the_geometry_digest() -> None:
    assert fingerprint(rms_package(), BOTH) == GEOMETRY_DIGEST_BOTH


# --- the feature-tree fingerprint ------------------------------------------------


def test_a_feature_tree_fingerprint_is_a_sha256_hex_digest() -> None:
    value = fingerprint(rms_package(), ["cmp:0001"], "feature_tree")

    assert len(value) == 64
    assert set(value) <= set("0123456789abcdef")


def test_the_feature_tree_fingerprint_is_stable_for_the_same_tree() -> None:
    assert fingerprint(rms_package(), BOTH, "feature_tree") == fingerprint(
        rms_package(), BOTH, "feature_tree"
    )


def test_the_two_kinds_hash_different_things() -> None:
    package = rms_package()

    assert fingerprint(package, BOTH, "feature_tree") != fingerprint(package, BOTH, "geometry")


def test_the_feature_tree_fingerprint_is_the_documents_not_the_components() -> None:
    """Both components instance `doc:2`, so either one binds to the same tree."""
    package = rms_package()

    assert fingerprint(package, ["cmp:0001"], "feature_tree") == fingerprint(
        package, ["cmp:0002"], "feature_tree"
    )


@pytest.mark.parametrize("change", sorted(CHANGED_TREES))
def test_every_field_a_rule_reads_changes_the_feature_tree_fingerprint(change: str) -> None:
    before = fingerprint(rms_package(), BOTH, "feature_tree")

    assert fingerprint(CHANGED_TREES[change], BOTH, "feature_tree") != before


def test_the_description_text_itself_is_not_hashed() -> None:
    reworded = rms_package(features=_with(base_features(), 0, description="the outer profile"))

    assert fingerprint(reworded, BOTH, "feature_tree") == fingerprint(
        rms_package(), BOTH, "feature_tree"
    )


def test_a_blank_description_is_not_a_description() -> None:
    """Three states, not two: `rms.intent.every_feature_described` fails on a blank
    description and only goes unresolved on a null one (contracts/rules.md), so blanking
    the text changes what the rule concluded and must not leave the digest where it was.
    """
    blank = fingerprint(CHANGED_TREES["description_blanked"], BOTH, "feature_tree")

    assert blank != fingerprint(rms_package(), BOTH, "feature_tree")
    assert blank != fingerprint(CHANGED_TREES["description_lost"], BOTH, "feature_tree")


def test_a_fillet_radius_change_below_one_nanometre_is_noise() -> None:
    nudged = rms_package(
        features=_with(
            base_features(),
            2,
            fillet=FilletInfo(default_radius=Quantity(value=0.002 + 1e-13, unit="m")),
        )
    )

    assert fingerprint(nudged, BOTH, "feature_tree") == fingerprint(
        rms_package(), BOTH, "feature_tree"
    )


def test_another_documents_tree_is_not_hashed() -> None:
    elsewhere = rms_package(
        features=[*base_features(), feature(0, "Sketch1", "ProfileFeature", document_id="doc:9")],
        equations=[
            *base_equations(),
            Equation(
                document_id="doc:9", index=0, text='"x" = 1', lhs="x", is_global=True, value=1.0
            ),
        ],
    )

    assert fingerprint(elsewhere, BOTH, "feature_tree") == fingerprint(
        rms_package(), BOTH, "feature_tree"
    )


def test_a_document_with_no_tree_still_fingerprints() -> None:
    empty = rms_package(features=[], equations=[])

    assert len(fingerprint(empty, BOTH, "feature_tree")) == 64
    assert fingerprint(empty, BOTH, "feature_tree") != fingerprint(
        rms_package(), BOTH, "feature_tree"
    )


def test_a_feature_tree_fingerprint_refuses_an_unknown_component() -> None:
    with pytest.raises(LookupError, match="cmp:9999"):
        fingerprint(rms_package(), ["cmp:9999"], "feature_tree")


def test_a_feature_tree_fingerprint_refuses_an_empty_component_list() -> None:
    with pytest.raises(ValueError, match="at least one component"):
        fingerprint(rms_package(), [], "feature_tree")


# --- choosing the kind -----------------------------------------------------------


def test_rms_checks_choose_the_feature_tree_kind() -> None:
    assert RMS_CHECK.startswith(RMS_CHECK_PREFIX)
    assert fingerprint_kind_for(RMS_CHECK) == "feature_tree"
    assert fingerprint_kind_for(INTERFERENCE_CHECK) == "geometry"
    assert fingerprint_kind_for("rmsx.not.a.rule") == "geometry"


def test_accepting_an_rms_finding_binds_to_the_feature_tree(tmp_path: Path) -> None:
    package = rms_package()
    store = ExceptionStore(tmp_path / EXCEPTIONS_FILE_NAME)

    accepted = store.accept(
        Group(RMS_CHECK, BOTH), package, by="engineer", note="legacy part", at=ACCEPTED_AT
    )

    assert accepted.fingerprint_kind == "feature_tree"
    assert accepted.geometry_fingerprint == fingerprint(package, BOTH, "feature_tree")


def test_accepting_an_interference_finding_still_binds_to_geometry(tmp_path: Path) -> None:
    package = rms_package()
    store = ExceptionStore(tmp_path / EXCEPTIONS_FILE_NAME)

    accepted = store.accept(
        Group(INTERFERENCE_CHECK, BOTH), package, by="engineer", note="press fit", at=ACCEPTED_AT
    )

    assert accepted.fingerprint_kind == "geometry"
    assert accepted.geometry_fingerprint == GEOMETRY_DIGEST_BOTH


def test_an_rms_exception_round_trips_through_the_file(tmp_path: Path) -> None:
    store = ExceptionStore(tmp_path / EXCEPTIONS_FILE_NAME)
    store.accept(Group(RMS_CHECK, BOTH), rms_package(), by="engineer", note="n", at=ACCEPTED_AT)
    store.save()

    reloaded = ExceptionStore(tmp_path / EXCEPTIONS_FILE_NAME).load()

    assert reloaded.exceptions == store.exceptions
    assert reloaded.get("EX-001").fingerprint_kind == "feature_tree"


def test_an_rms_exception_can_be_rebuilt_from_its_json(tmp_path: Path) -> None:
    store = ExceptionStore(tmp_path / EXCEPTIONS_FILE_NAME)
    accepted = store.accept(
        Group(RMS_CHECK, BOTH), rms_package(), by="engineer", note="n", at=ACCEPTED_AT
    )

    assert ReviewException(**accepted.model_dump()) == accepted


# --- matching by check -----------------------------------------------------------


def test_match_requires_the_check() -> None:
    store = ExceptionStore(exceptions=[])

    with pytest.raises(TypeError):
        store.match(rms_package(), BOTH, "Default")  # type: ignore[call-arg]


def test_an_rms_exception_is_never_returned_for_an_interference_query(tmp_path: Path) -> None:
    package = rms_package()
    store = ExceptionStore(tmp_path / EXCEPTIONS_FILE_NAME)
    store.accept(Group(RMS_CHECK, BOTH), package, by="engineer", note="n", at=ACCEPTED_AT)

    assert store.match(package, BOTH, "Default", INTERFERENCE_CHECK) is None
    assert store.match(package, BOTH, "Default", RMS_CHECK) is not None


def test_an_interference_exception_is_never_returned_for_an_rms_query(tmp_path: Path) -> None:
    package = rms_package()
    store = ExceptionStore(tmp_path / EXCEPTIONS_FILE_NAME)
    store.accept(Group(INTERFERENCE_CHECK, BOTH), package, by="engineer", note="n", at=ACCEPTED_AT)

    assert store.match(package, BOTH, "Default", RMS_CHECK) is None


def test_two_rms_exceptions_on_the_same_bindings_resolve_by_check(tmp_path: Path) -> None:
    package = rms_package()
    store = ExceptionStore(tmp_path / EXCEPTIONS_FILE_NAME)
    first = store.accept(Group(RMS_CHECK, BOTH), package, by="engineer", note="a", at=ACCEPTED_AT)
    second = store.accept(
        Group(OTHER_RMS_CHECK, BOTH), package, by="engineer", note="b", at=ACCEPTED_AT
    )

    assert store.match(package, BOTH, "Default", RMS_CHECK) is first
    assert store.match(package, BOTH, "Default", OTHER_RMS_CHECK) is second
    assert store.match(package, BOTH, "Default", "rms.nothing.here") is None


def test_a_retired_rms_exception_never_matches(tmp_path: Path) -> None:
    package = rms_package()
    store = ExceptionStore(tmp_path / EXCEPTIONS_FILE_NAME)
    accepted = store.accept(
        Group(RMS_CHECK, BOTH), package, by="engineer", note="n", at=ACCEPTED_AT
    )
    store.retire(accepted.id)

    assert store.match(package, BOTH, "Default", RMS_CHECK) is None


# --- refresh and re-accept -------------------------------------------------------


def accepted_rms_exception(tmp_path: Path) -> tuple[ExceptionStore, ReviewException]:
    store = ExceptionStore(tmp_path / EXCEPTIONS_FILE_NAME)
    accepted = store.accept(
        Group(RMS_CHECK, BOTH), rms_package(), by="engineer", note="n", at=ACCEPTED_AT
    )
    return store, accepted


def test_refresh_leaves_an_unchanged_feature_tree_exception_active(tmp_path: Path) -> None:
    store, accepted = accepted_rms_exception(tmp_path)

    assert store.refresh(rms_package()) == []
    assert accepted.status == "active"


@pytest.mark.parametrize("change", sorted(CHANGED_TREES))
def test_refresh_flags_a_changed_feature_tree_for_re_review(tmp_path: Path, change: str) -> None:
    store, accepted = accepted_rms_exception(tmp_path)

    assert store.refresh(CHANGED_TREES[change]) == [accepted]
    assert accepted.status == "needs_review"


def test_refresh_leaves_a_reworded_description_active(tmp_path: Path) -> None:
    store, accepted = accepted_rms_exception(tmp_path)
    reworded = rms_package(features=_with(base_features(), 0, description="the outer profile"))

    assert store.refresh(reworded) == []
    assert accepted.status == "active"


def test_refresh_flags_a_feature_tree_exception_when_the_configuration_changes(
    tmp_path: Path,
) -> None:
    store, accepted = accepted_rms_exception(tmp_path)

    store.refresh(rms_package(configuration="Cold"))

    assert accepted.status == "needs_review"


def test_a_geometry_exception_ignores_the_feature_tree(tmp_path: Path) -> None:
    """Geometry exceptions behave exactly as before: only geometry moves them."""
    store = ExceptionStore(tmp_path / EXCEPTIONS_FILE_NAME)
    accepted = store.accept(
        Group(INTERFERENCE_CHECK, BOTH), rms_package(), by="engineer", note="n", at=ACCEPTED_AT
    )

    assert store.refresh(CHANGED_TREES["inserted"]) == []
    assert accepted.status == "active"


def test_a_feature_tree_exception_ignores_the_geometry(tmp_path: Path) -> None:
    store, accepted = accepted_rms_exception(tmp_path)
    package = rms_package()
    moved = [list(row) for row in package.components[0].transform]
    moved[3][0] = 0.001
    package.components[0].transform = moved

    assert store.refresh(package) == []
    assert accepted.status == "active"


def test_reaccept_rebinds_a_feature_tree_exception_by_its_kind(tmp_path: Path) -> None:
    store, accepted = accepted_rms_exception(tmp_path)
    changed = CHANGED_TREES["renamed"]
    store.refresh(changed)

    reaccepted = store.reaccept(accepted.id, changed)

    assert reaccepted.status == "active"
    assert reaccepted.fingerprint_kind == "feature_tree"
    assert reaccepted.geometry_fingerprint == fingerprint(changed, BOTH, "feature_tree")
    assert store.refresh(changed) == []
