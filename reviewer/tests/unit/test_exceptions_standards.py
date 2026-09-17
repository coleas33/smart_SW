"""Unit tests for document-scoped standards exceptions (T084).

A standards finding on a **drawing** carries no component instances, so the exception
machinery feature 001 built - bind to the instances, hash their geometry, match on the
bindings - has nothing to hold onto. An exception with no bindings at all is the blanket
exclusion the constitution prohibits, and two drawings both yield empty bindings, so one
drawing's waiver would answer for every other drawing (FR-041, RK-11, SC-008).

`data-model.md` section 5 names the four changes rather than leaving them to be
discovered, and this module is their contract:

1. `ReviewException.document_id` is optional with the default `null`, so every record
   already written loads unchanged;
2. `fingerprint_kind` gains `"standards"`, and `fingerprint` gains a **document-scoped**
   path that needs no component ids (it raises today with none) and hashes every input the
   sixteen checks read for that document - so a newly appearing subject re-opens the
   finding, and a fix elsewhere in the same check re-opens it too, which is the
   conservative direction;
3. `accept` gains a document-bound target, whose bindings are empty **by construction**
   when the finding carries no instances;
4. `match` takes and compares `document_id`.

Every one of them is additive, and the last four tests here are the regression that the
geometry and feature-tree paths are byte-for-byte what they were.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from swreview.checks.interference import CHECK as INTERFERENCE_CHECK
from swreview.checks.standards.assembly import FULLY_MATED, MATE_REFERENCES, NOT_HIDDEN
from swreview.checks.standards.document import DATA_CARD_COMPLETE
from swreview.checks.standards.drawing import (
    ANNOTATIONS_NOT_DANGLING,
    DIMENSIONS_NOT_OVERRIDDEN,
    NO_ITAR_STATEMENT,
    REVISION_MATCHES,
)
from swreview.checks.standards.part import CUT_LIST_EXCLUDED, SKETCHES_FULLY_DEFINED
from swreview.checks.standards.registry import RULES
from swreview.exceptions import (
    EXCEPTIONS_FILE_NAME,
    STANDARDS_CHECK_PREFIX,
    ExceptionStore,
    ReviewException,
    fingerprint,
    fingerprint_kind_for,
)
from swreview.ir.models import EvidencePackage
from tests.support.features import FeatureSpec, SketchSpec
from tests.support.packages import build_package
from tests.support.standards import (
    AnnotationSpec,
    AssemblySpec,
    ComponentSpec,
    CutListSpec,
    DimensionSpec,
    DrawingSpec,
    MateEntitySpec,
    MateSpec,
    NoteSpec,
    PartSpec,
    RevisionTableSpec,
    SheetSpec,
    ViewSpec,
    standards_package,
)

ACCEPTED_AT = datetime(2026, 9, 17, 10, 0, 0, tzinfo=UTC)

VAULT = "X:/vault"

ASSEMBLY_DOC = "doc:1"
PART_DOC = "doc:2"
DRAWING_DOC = "doc:3"
OTHER_DRAWING_DOC = "doc:4"
"""`standards_package` allocates `doc:N` in spec order, and `build()` below keeps that
order fixed so every test names the same four documents."""


# --- the package under test ------------------------------------------------------


ASSEMBLY = AssemblySpec(
    name="top-assy",
    folder="assemblies",
    properties={"PartNo": "1000-0001", "Description": "top level"},
    components=(
        ComponentSpec(name="bracket-1", document="bracket", is_fixed=True),
        ComponentSpec(name="bracket-2", document="bracket", constrained_status_raw=2),
    ),
    mates=(
        MateSpec(
            entities=(
                MateEntitySpec(component="bracket-1"),
                MateEntitySpec(component="bracket-2"),
            )
        ),
    ),
)

PART = PartSpec(
    name="bracket",
    folder="parts",
    material="6061-T6",
    properties={"PartNo": "1000-0002", "Description": ""},
    features=(
        FeatureSpec(name="Sketch1", type_name="ProfileFeature", sketch=SketchSpec(raw_status=3)),
        FeatureSpec(name="Boss-Extrude1", type_name="Extrusion"),
    ),
    cut_list=(CutListSpec(name="Cut-List-Item1", excluded_from_cut_list=True),),
)

DRAWING = DrawingSpec(
    name="bracket-drw",
    folder="drawings",
    properties={"PartNo": "1000-0002", "Revision": "A"},
    active_sheet="Sheet1",
    sheets=(
        SheetSpec(
            name="Sheet1",
            was_active=True,
            views=(
                ViewSpec(
                    name="Drawing View1",
                    references="bracket",
                    dimensions=(
                        DimensionSpec(name="D1@Sketch1", is_overridden=True),
                        DimensionSpec(name="D2@Sketch1", is_overridden=False),
                    ),
                    annotations=(AnnotationSpec(name="RevNote", is_dangling=False),),
                ),
                ViewSpec(
                    name="Sheet Format1",
                    view_type_raw=1,
                    notes=(NoteSpec(text="UNLESS OTHERWISE SPECIFIED"),),
                ),
            ),
            revision_tables=(
                RevisionTableSpec(rows=(("REV", "DATE"), ("A", "2026-01-02"))),
            ),
        ),
    ),
)

OTHER_DRAWING = DrawingSpec(
    name="plate-drw",
    folder="drawings",
    properties={"PartNo": "1000-0003", "Revision": "A"},
    active_sheet="Sheet1",
    sheets=(
        SheetSpec(
            name="Sheet1",
            was_active=True,
            views=(
                ViewSpec(
                    name="Drawing View1",
                    dimensions=(DimensionSpec(name="D1@Sketch1", is_overridden=True),),
                ),
            ),
        ),
    ),
)


def build(
    *,
    assembly: AssemblySpec = ASSEMBLY,
    part: PartSpec = PART,
    drawing: DrawingSpec = DRAWING,
    other: DrawingSpec = OTHER_DRAWING,
) -> EvidencePackage:
    """The four-document package every test starts from, with one spec swapped at a time."""
    return standards_package(documents=[assembly, part, drawing, other], vault_root=VAULT)


@dataclass(frozen=True)
class Target:
    """A `FingerprintTarget`: what `accept` reads off a finding, and nothing else."""

    check: str
    component_ids: tuple[str, ...] = ()
    configuration: str = "Default"


def sheet_with(*views: ViewSpec) -> DrawingSpec:
    """`DRAWING` with its first sheet's views replaced."""
    sheet = replace(DRAWING.sheets[0], views=views)
    return replace(DRAWING, sheets=(sheet,))


def component_ids_of(package: EvidencePackage, document_id: str) -> list[str]:
    """The ids of the instances whose parent is an instance of `document_id`."""
    owners = {row.id for row in package.components if row.document_id == document_id}
    return [row.id for row in package.components if row.parent_id in owners]


# --- the checks these tests name are real ----------------------------------------


def test_every_check_id_under_test_is_a_registered_standards_rule() -> None:
    """`contracts/rules.md` makes rule ids the stable name a waiver is written against, so
    an exception accepted for a made-up `standards.*` id would prove nothing: nothing in
    `exceptions.py` branches on anything but the family prefix."""
    named = {
        ANNOTATIONS_NOT_DANGLING,
        CUT_LIST_EXCLUDED,
        DATA_CARD_COMPLETE,
        DIMENSIONS_NOT_OVERRIDDEN,
        FULLY_MATED,
        MATE_REFERENCES,
        NOT_HIDDEN,
        NO_ITAR_STATEMENT,
        REVISION_MATCHES,
        SKETCHES_FULLY_DEFINED,
    }
    assert named <= set(RULES)
    assert all(check.startswith(STANDARDS_CHECK_PREFIX) for check in named)


# --- 1. the field ----------------------------------------------------------------


def test_document_id_defaults_to_null_so_an_existing_record_loads_unchanged() -> None:
    """Every `exceptions.json` written before this feature carries no `document_id`, and
    the store is `extra="forbid"` + `strict=True`: a field without a default would refuse
    to load a file an engineer keeps under version control."""
    store = ExceptionStore.from_records(
        [
            {
                "id": "EX-001",
                "check": INTERFERENCE_CHECK,
                "component_persist_refs": ["Y21wOjAwMDE="],
                "persist_ref_scopes": ["doc:1"],
                "configuration": "Default",
                "geometry_fingerprint": "0" * 64,
                "accepted_by": "engineer",
                "accepted_at": "2026-08-03T09:15:00Z",
                "note": "intended",
                "status": "active",
            }
        ]
    )

    assert store.get("EX-001").document_id is None


def test_a_standards_record_round_trips_through_the_file(tmp_path: Path) -> None:
    package = build()
    store = ExceptionStore(tmp_path / EXCEPTIONS_FILE_NAME)
    store.accept(
        Target(DIMENSIONS_NOT_OVERRIDDEN),
        package,
        by="engineer",
        note="one legacy dimension",
        at=ACCEPTED_AT,
        document_id=DRAWING_DOC,
    )
    store.save()

    reloaded = ExceptionStore(tmp_path / EXCEPTIONS_FILE_NAME).load()

    assert reloaded.exceptions == store.exceptions
    assert reloaded.get("EX-001").document_id == DRAWING_DOC
    assert reloaded.get("EX-001").fingerprint_kind == "standards"


def test_a_standards_exception_can_be_rebuilt_from_its_json() -> None:
    store = ExceptionStore()
    accepted = store.accept(
        Target(DIMENSIONS_NOT_OVERRIDDEN),
        build(),
        by="engineer",
        note="n",
        at=ACCEPTED_AT,
        document_id=DRAWING_DOC,
    )

    assert ReviewException(**accepted.model_dump()) == accepted


# --- 2. choosing the kind --------------------------------------------------------


def test_standards_checks_choose_the_standards_kind() -> None:
    assert fingerprint_kind_for(DIMENSIONS_NOT_OVERRIDDEN) == "standards"
    assert fingerprint_kind_for(DATA_CARD_COMPLETE) == "standards"
    assert fingerprint_kind_for("rms.sketches.not_over_defined") == "feature_tree"
    assert fingerprint_kind_for(INTERFERENCE_CHECK) == "geometry"
    assert fingerprint_kind_for("standardsx.not.a.check") == "geometry"


# --- 3. the document-scoped fingerprint ------------------------------------------


def test_a_standards_fingerprint_needs_no_component_ids() -> None:
    """The change that makes a drawing waiver possible at all: today this raises."""
    package = build()

    digest = fingerprint(package, [], "standards", document_id=DRAWING_DOC)

    assert len(digest) == 64
    assert digest == fingerprint(package, [], "standards", document_id=DRAWING_DOC)


def test_a_standards_fingerprint_needs_a_document() -> None:
    with pytest.raises(ValueError, match="document"):
        fingerprint(build(), [], "standards")


def test_a_standards_fingerprint_refuses_a_document_the_package_does_not_hold() -> None:
    """An exception must never be silently re-bound to whatever is left (FR-013)."""
    with pytest.raises(LookupError, match="doc:9"):
        fingerprint(build(), [], "standards", document_id="doc:9")


def test_a_standards_fingerprint_still_refuses_a_component_the_package_lacks() -> None:
    with pytest.raises(LookupError, match="cmp:9999"):
        fingerprint(build(), ["cmp:9999"], "standards", document_id=ASSEMBLY_DOC)


def test_the_components_a_standards_fingerprint_is_given_do_not_change_it() -> None:
    """The binding is the document. An assembly finding names its offending instances, but
    the digest covers every instance of the document, so a second offender re-opens it."""
    package = build()
    every = component_ids_of(package, ASSEMBLY_DOC)
    assert len(every) == 2

    assert fingerprint(package, [], "standards", document_id=ASSEMBLY_DOC) == fingerprint(
        package, every, "standards", document_id=ASSEMBLY_DOC
    )
    assert fingerprint(package, every[:1], "standards", document_id=ASSEMBLY_DOC) == fingerprint(
        package, every, "standards", document_id=ASSEMBLY_DOC
    )


def test_each_document_of_one_package_has_its_own_digest() -> None:
    package = build()

    digests = {
        document_id: fingerprint(package, [], "standards", document_id=document_id)
        for document_id in (ASSEMBLY_DOC, PART_DOC, DRAWING_DOC, OTHER_DRAWING_DOC)
    }

    assert len(set(digests.values())) == 4


def test_the_digest_is_stable_across_two_identical_packages() -> None:
    """Nothing about the run reaches it: two packages built the same way agree, so a
    re-extraction that changed nothing does not re-open a waiver."""
    assert fingerprint(build(), [], "standards", document_id=DRAWING_DOC) == fingerprint(
        build(), [], "standards", document_id=DRAWING_DOC
    )


def digest(package: EvidencePackage, document_id: str) -> str:
    return fingerprint(package, [], "standards", document_id=document_id)


@pytest.mark.parametrize(
    ("label", "spec"),
    [
        (
            "a newly appearing overridden dimension",
            sheet_with(
                replace(
                    DRAWING.sheets[0].views[0],
                    dimensions=(
                        *DRAWING.sheets[0].views[0].dimensions,
                        DimensionSpec(name="D3@Sketch1", is_overridden=True),
                    ),
                ),
                DRAWING.sheets[0].views[1],
            ),
        ),
        (
            "an override flag that was fixed elsewhere in the same check",
            sheet_with(
                replace(
                    DRAWING.sheets[0].views[0],
                    dimensions=(
                        DimensionSpec(name="D1@Sketch1", is_overridden=True),
                        DimensionSpec(name="D2@Sketch1", is_overridden=None),
                    ),
                ),
                DRAWING.sheets[0].views[1],
            ),
        ),
        (
            "a newly dangling annotation",
            sheet_with(
                replace(
                    DRAWING.sheets[0].views[0],
                    annotations=(AnnotationSpec(name="RevNote", is_dangling=True),),
                ),
                DRAWING.sheets[0].views[1],
            ),
        ),
        (
            "a note whose text changed",
            sheet_with(
                DRAWING.sheets[0].views[0],
                replace(
                    DRAWING.sheets[0].views[1],
                    notes=(NoteSpec(text="EXPORT CONTROLLED"),),
                ),
            ),
        ),
        (
            "a revision-table cell that changed",
            replace(
                DRAWING,
                sheets=(
                    replace(
                        DRAWING.sheets[0],
                        revision_tables=(
                            RevisionTableSpec(rows=(("REV", "DATE"), ("B", "2026-01-02"))),
                        ),
                    ),
                ),
            ),
        ),
        (
            "a second sheet",
            replace(
                DRAWING,
                sheets=(*DRAWING.sheets, SheetSpec(name="Sheet2", views=())),
            ),
        ),
        (
            "a data-card property that was filled in",
            replace(DRAWING, properties={"PartNo": "1000-0002", "Revision": "B"}),
        ),
        (
            "a data-card property that appeared",
            replace(
                DRAWING,
                properties={"PartNo": "1000-0002", "Revision": "A", "Material": "6061-T6"},
            ),
        ),
    ],
)
def test_a_drawings_digest_moves_when_any_input_its_checks_read_moves(
    label: str, spec: DrawingSpec
) -> None:
    """SC-008 in one table: every subject the four drawing checks and the data-card check
    read for a drawing is in the hash, so a newly appearing subject re-opens the finding
    rather than being silenced - and so does a fix elsewhere in the same check, which is
    the conservative direction."""
    assert digest(build(), DRAWING_DOC) != digest(build(drawing=spec), DRAWING_DOC), label


@pytest.mark.parametrize(
    ("label", "spec"),
    [
        (
            "a newly hidden instance",
            replace(
                ASSEMBLY,
                components=(
                    replace(ASSEMBLY.components[0], visibility_raw=0),
                    ASSEMBLY.components[1],
                ),
            ),
        ),
        (
            "an instance that is no longer fixed",
            replace(
                ASSEMBLY,
                components=(
                    replace(ASSEMBLY.components[0], is_fixed=False),
                    ASSEMBLY.components[1],
                ),
            ),
        ),
        (
            "a constrained status that changed",
            replace(
                ASSEMBLY,
                components=(
                    ASSEMBLY.components[0],
                    replace(ASSEMBLY.components[1], constrained_status_raw=1),
                ),
            ),
        ),
        (
            "a transparency reading that appeared",
            replace(
                ASSEMBLY,
                components=(
                    replace(
                        ASSEMBLY.components[0],
                        has_appearance_override=True,
                        transparency_raw=0.5,
                    ),
                    ASSEMBLY.components[1],
                ),
            ),
        ),
        (
            "an instance that became a pattern instance",
            replace(
                ASSEMBLY,
                components=(
                    ASSEMBLY.components[0],
                    replace(ASSEMBLY.components[1], is_pattern_instance=True),
                ),
            ),
        ),
        (
            "a newly appearing instance",
            replace(
                ASSEMBLY,
                components=(
                    *ASSEMBLY.components,
                    ComponentSpec(name="bracket-3", document="bracket"),
                ),
            ),
        ),
        (
            "a mate that was suppressed",
            replace(
                ASSEMBLY,
                mates=(replace(ASSEMBLY.mates[0], suppressed=True),),
            ),
        ),
        (
            "a mate entity that stopped resolving",
            replace(
                ASSEMBLY,
                mates=(
                    replace(
                        ASSEMBLY.mates[0],
                        entities=(
                            MateEntitySpec(component="bracket-1", resolution_status="unresolved"),
                            MateEntitySpec(component="bracket-2"),
                        ),
                    ),
                ),
            ),
        ),
        (
            "an assembly that was left exploded",
            replace(ASSEMBLY, is_exploded=True),
        ),
        (
            "a rebuild error count that moved",
            replace(ASSEMBLY, rebuild_error_count=2),
        ),
        (
            "a data-card property that appeared",
            replace(
                ASSEMBLY,
                properties={"PartNo": "1000-0001", "Description": "top level", "Rev": "A"},
            ),
        ),
    ],
)
def test_an_assemblys_digest_moves_when_any_input_its_checks_read_moves(
    label: str, spec: AssemblySpec
) -> None:
    assert digest(build(), ASSEMBLY_DOC) != digest(build(assembly=spec), ASSEMBLY_DOC), label


@pytest.mark.parametrize(
    ("label", "spec"),
    [
        (
            "a sketch that stopped being fully defined",
            replace(
                PART,
                features=(
                    replace(PART.features[0], sketch=SketchSpec(raw_status=2)),
                    PART.features[1],
                ),
            ),
        ),
        (
            "a sketch text-segment count that appeared",
            replace(
                PART,
                features=(
                    replace(PART.features[0], sketch=SketchSpec(raw_status=3, text_segments=1)),
                    PART.features[1],
                ),
            ),
        ),
        (
            "a feature that errored",
            replace(
                PART,
                features=(PART.features[0], replace(PART.features[1], error_code=1)),
            ),
        ),
        (
            "a newly appearing feature",
            replace(
                PART,
                features=(*PART.features, FeatureSpec(name="Fillet1", type_name="Fillet")),
            ),
        ),
        (
            "a renamed feature",
            replace(
                PART,
                features=(PART.features[0], replace(PART.features[1], name="Boss-Extrude2")),
            ),
        ),
        ("a material that was removed", replace(PART, material=None)),
        (
            "a material read in another configuration",
            replace(PART, material_configuration="Machined"),
        ),
        ("a mass that was overridden", replace(PART, mass_overridden=True)),
        (
            "a cut-list item that is no longer excluded",
            replace(
                PART,
                cut_list=(replace(PART.cut_list[0], excluded_from_cut_list=False),),
            ),
        ),
        (
            "a newly appearing cut-list item",
            replace(PART, cut_list=(*PART.cut_list, CutListSpec(name="Cut-List-Item2"))),
        ),
        ("a rebuild error count that moved", replace(PART, rebuild_error_count=3)),
        (
            "a data-card property that was filled in",
            replace(PART, properties={"PartNo": "1000-0002", "Description": "bracket"}),
        ),
    ],
)
def test_a_parts_digest_moves_when_any_input_its_checks_read_moves(
    label: str, spec: PartSpec
) -> None:
    assert digest(build(), PART_DOC) != digest(build(part=spec), PART_DOC), label


def test_a_documents_digest_ignores_what_happened_to_the_other_documents() -> None:
    """The binding is one document: a change on the plate drawing must not re-open a
    waiver accepted on the bracket drawing, or every waiver in the package would re-open
    on every edit anywhere."""
    moved = replace(
        OTHER_DRAWING,
        sheets=(
            replace(
                OTHER_DRAWING.sheets[0],
                views=(
                    replace(
                        OTHER_DRAWING.sheets[0].views[0],
                        dimensions=(DimensionSpec(name="D1@Sketch1", is_overridden=False),),
                    ),
                ),
            ),
        ),
    )

    assert digest(build(), DRAWING_DOC) == digest(build(other=moved), DRAWING_DOC)
    assert digest(build(), OTHER_DRAWING_DOC) != digest(build(other=moved), OTHER_DRAWING_DOC)


def test_the_order_the_package_records_a_documents_properties_in_does_not_matter() -> None:
    """The order SOLIDWORKS reported things in cannot flip a waiver, exactly as it cannot
    for the geometry and feature-tree kinds."""
    reordered = replace(DRAWING, properties={"Revision": "A", "PartNo": "1000-0002"})

    assert digest(build(), DRAWING_DOC) == digest(build(drawing=reordered), DRAWING_DOC)


def test_two_drawings_with_the_same_content_still_have_different_digests() -> None:
    """A digest is per document, so a copied drawing does not inherit the original's
    waiver even before `match` compares `document_id`."""
    twin = replace(DRAWING, name="plate-drw", properties=dict(DRAWING.properties))

    package = build(other=twin)

    assert digest(package, DRAWING_DOC) != digest(package, OTHER_DRAWING_DOC)


# --- 4. accept -------------------------------------------------------------------


def test_accepting_a_drawing_finding_binds_by_document_with_empty_bindings() -> None:
    package = build()
    store = ExceptionStore()

    accepted = store.accept(
        Target(DIMENSIONS_NOT_OVERRIDDEN),
        package,
        by="engineer",
        note="one legacy dimension, ECO-114",
        at=ACCEPTED_AT,
        document_id=DRAWING_DOC,
    )

    assert accepted.fingerprint_kind == "standards"
    assert accepted.document_id == DRAWING_DOC
    assert accepted.component_persist_refs == []
    assert accepted.persist_ref_scopes == []
    assert accepted.bindings == []
    assert accepted.geometry_fingerprint == digest(package, DRAWING_DOC)
    assert accepted.status == "active"
    assert store.exceptions == [accepted]


def test_accepting_an_assembly_finding_keeps_its_instance_bindings() -> None:
    """A standards finding that *does* carry instances keeps them - the document binding
    is additional, not a replacement, so the bridge can still re-check the references."""
    package = build()
    ids = component_ids_of(package, ASSEMBLY_DOC)
    store = ExceptionStore()

    accepted = store.accept(
        Target(NOT_HIDDEN, tuple(ids)),
        package,
        by="engineer",
        note="reference geometry is hidden deliberately",
        at=ACCEPTED_AT,
        document_id=ASSEMBLY_DOC,
    )

    assert accepted.document_id == ASSEMBLY_DOC
    assert len(accepted.bindings) == len(ids)
    assert accepted.geometry_fingerprint == digest(package, ASSEMBLY_DOC)


def test_accepting_a_standards_finding_without_a_document_is_refused() -> None:
    """An exception with no bindings and no document is the blanket exclusion the
    constitution prohibits, so it cannot be built at all."""
    store = ExceptionStore()

    with pytest.raises(ValueError, match="document"):
        store.accept(
            Target(DIMENSIONS_NOT_OVERRIDDEN),
            build(),
            by="engineer",
            note="n",
            at=ACCEPTED_AT,
        )

    assert store.exceptions == []


def test_a_document_bound_target_is_refused_for_a_non_standards_check() -> None:
    """`document_id` is set for `standards.*` exceptions and for nothing else: a geometry
    record carrying one would be compared against the `None` every other caller passes and
    would silently never match again."""
    store = ExceptionStore()

    with pytest.raises(ValueError, match="standards"):
        store.accept(
            Target(INTERFERENCE_CHECK, ("cmp:0001",)),
            build(),
            by="engineer",
            note="n",
            at=ACCEPTED_AT,
            document_id=ASSEMBLY_DOC,
        )

    assert store.exceptions == []


# --- 5. match --------------------------------------------------------------------


def accept_on(
    store: ExceptionStore, package: EvidencePackage, document_id: str
) -> ReviewException:
    return store.accept(
        Target(DIMENSIONS_NOT_OVERRIDDEN),
        package,
        by="engineer",
        note="legacy dimension",
        at=ACCEPTED_AT,
        document_id=document_id,
    )


def test_a_drawing_waiver_answers_for_its_own_document() -> None:
    package = build()
    store = ExceptionStore()
    accepted = accept_on(store, package, DRAWING_DOC)

    found = store.match(
        package, [], "Default", DIMENSIONS_NOT_OVERRIDDEN, document_id=DRAWING_DOC
    )

    assert found is accepted


def test_one_drawings_waiver_never_answers_for_another_drawing() -> None:
    """RK-11 in one assertion: both drawings yield empty bindings and the same check id,
    so without `document_id` the store would hand back the bracket drawing's waiver."""
    package = build()
    store = ExceptionStore()
    accept_on(store, package, DRAWING_DOC)

    assert (
        store.match(
            package, [], "Default", DIMENSIONS_NOT_OVERRIDDEN, document_id=OTHER_DRAWING_DOC
        )
        is None
    )


def test_a_standards_waiver_is_not_found_by_a_query_that_names_no_document() -> None:
    """The geometry callers pass no document, and a standards exception must not answer
    them even when the bindings happen to agree."""
    package = build()
    store = ExceptionStore()
    accept_on(store, package, DRAWING_DOC)

    assert store.match(package, [], "Default", DIMENSIONS_NOT_OVERRIDDEN) is None


def test_a_standards_waiver_still_answers_only_its_own_check() -> None:
    package = build()
    store = ExceptionStore()
    accept_on(store, package, DRAWING_DOC)

    assert (
        store.match(package, [], "Default", ANNOTATIONS_NOT_DANGLING, document_id=DRAWING_DOC)
        is None
    )


def test_a_standards_waiver_still_answers_only_its_own_configuration() -> None:
    package = build()
    store = ExceptionStore()
    accept_on(store, package, DRAWING_DOC)

    assert (
        store.match(package, [], "Machined", DIMENSIONS_NOT_OVERRIDDEN, document_id=DRAWING_DOC)
        is None
    )


def test_a_retired_standards_waiver_never_matches() -> None:
    package = build()
    store = ExceptionStore()
    accepted = accept_on(store, package, DRAWING_DOC)
    store.retire(accepted.id)

    assert (
        store.match(package, [], "Default", DIMENSIONS_NOT_OVERRIDDEN, document_id=DRAWING_DOC)
        is None
    )


def test_a_flagged_standards_waiver_still_matches_so_the_run_can_report_it() -> None:
    """`needs_review` matches on purpose: the run has to say the accepted condition needs
    re-review rather than silently re-raise the finding as new."""
    package = build()
    store = ExceptionStore()
    accepted = accept_on(store, package, DRAWING_DOC)
    accepted.status = "needs_review"

    found = store.match(
        package, [], "Default", DIMENSIONS_NOT_OVERRIDDEN, document_id=DRAWING_DOC
    )

    assert found is accepted


# --- 6. refresh over a standards waiver ------------------------------------------


def test_a_seeded_second_subject_flags_the_standards_waiver_for_re_review() -> None:
    """SC-008 end to end through the store: the drawing gains a second overridden
    dimension, the fingerprint no longer matches and the exception is flagged rather than
    going on silencing the check."""
    store = ExceptionStore()
    accept_on(store, build(), DRAWING_DOC)
    seeded = sheet_with(
        replace(
            DRAWING.sheets[0].views[0],
            dimensions=(
                *DRAWING.sheets[0].views[0].dimensions,
                DimensionSpec(name="D3@Sketch1", is_overridden=True),
            ),
        ),
        DRAWING.sheets[0].views[1],
    )

    flagged = store.refresh(build(drawing=seeded))

    assert [item.id for item in flagged] == ["EX-001"]
    assert store.get("EX-001").status == "needs_review"


def test_an_unchanged_package_leaves_a_standards_waiver_active() -> None:
    store = ExceptionStore()
    accept_on(store, build(), DRAWING_DOC)

    assert store.refresh(build()) == []
    assert store.get("EX-001").status == "active"


def test_a_standards_waiver_whose_document_is_gone_is_flagged_not_crashed() -> None:
    """An unverifiable exception must not keep silencing a check (FR-013), and a document
    the package no longer holds is exactly that."""
    store = ExceptionStore()
    accept_on(store, build(), OTHER_DRAWING_DOC)

    flagged = store.refresh(
        standards_package(documents=[ASSEMBLY, PART, DRAWING], vault_root=VAULT)
    )

    assert [item.id for item in flagged] == ["EX-001"]
    assert store.get("EX-001").status == "needs_review"


def test_reaccepting_a_standards_waiver_rebinds_it_to_the_package_as_it_is_now() -> None:
    store = ExceptionStore()
    accept_on(store, build(), DRAWING_DOC)
    seeded = sheet_with(
        replace(
            DRAWING.sheets[0].views[0],
            dimensions=(
                *DRAWING.sheets[0].views[0].dimensions,
                DimensionSpec(name="D3@Sketch1", is_overridden=True),
            ),
        ),
        DRAWING.sheets[0].views[1],
    )
    package = build(drawing=seeded)
    store.refresh(package)

    reaccepted = store.reaccept("EX-001", package)

    assert reaccepted.status == "active"
    assert reaccepted.document_id == DRAWING_DOC
    assert reaccepted.geometry_fingerprint == digest(package, DRAWING_DOC)
    assert store.refresh(package) == []


# --- 7. the regression: nothing about the other two kinds moved ------------------


def test_the_geometry_and_feature_tree_digests_are_byte_for_byte_what_they_were() -> None:
    """The two digests `test_exceptions_feature_tree.py` pinned before this feature, named
    again here: every digest in a shipped `exceptions.json` was computed by those paths."""
    package = build_package()

    assert (
        fingerprint(package, ["cmp:0001", "cmp:0002"])
        == "351d7938801df7a2b6883fc8274beb9e4ca6013b272f8e343d2e358fd7f12393"
    )
    assert (
        fingerprint(package, ["cmp:0001"])
        == "c1c6df68be2efc552ea93b6d6aac95f8d36730f5b46453d1c70c96143ea7a8f3"
    )


def test_the_geometry_and_feature_tree_kinds_still_refuse_an_empty_component_list() -> None:
    """Only the standards kind gained the empty-component path: a geometry exception with
    no components would be bound to nothing at all."""
    package = build()

    with pytest.raises(ValueError, match="at least one component"):
        fingerprint(package, [], "geometry")
    with pytest.raises(ValueError, match="at least one component"):
        fingerprint(package, [], "feature_tree")


def test_a_geometry_accept_is_unchanged_and_carries_no_document() -> None:
    package = build_package()
    store = ExceptionStore()

    accepted = store.accept(
        Target(INTERFERENCE_CHECK, ("cmp:0001", "cmp:0002")),
        package,
        by="engineer",
        note="press fit",
        at=ACCEPTED_AT,
    )

    assert accepted.fingerprint_kind == "geometry"
    assert accepted.document_id is None
    assert len(accepted.bindings) == 2
    assert (
        accepted.geometry_fingerprint
        == "351d7938801df7a2b6883fc8274beb9e4ca6013b272f8e343d2e358fd7f12393"
    )


def test_a_geometry_match_still_answers_a_caller_that_names_no_document() -> None:
    """Every existing caller of `match` passes four arguments and no document; the new
    parameter defaults to `None` and an existing record's `document_id` is `None`, so the
    comparison is one every shipped exception already passes."""
    package = build_package()
    store = ExceptionStore()
    accepted = store.accept(
        Target(INTERFERENCE_CHECK, ("cmp:0001", "cmp:0002")),
        package,
        by="engineer",
        note="press fit",
        at=ACCEPTED_AT,
    )

    found = store.match(package, ["cmp:0002", "cmp:0001"], "Default", INTERFERENCE_CHECK)

    assert found is accepted


def test_a_geometry_refresh_is_untouched_by_the_document_scoped_path() -> None:
    package = build_package()
    store = ExceptionStore()
    store.accept(
        Target(INTERFERENCE_CHECK, ("cmp:0001", "cmp:0002")),
        package,
        by="engineer",
        note="press fit",
        at=ACCEPTED_AT,
    )

    assert store.refresh(package) == []
    assert store.get("EX-001").status == "active"
