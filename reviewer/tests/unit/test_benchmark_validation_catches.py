"""The validation catches what it is for (feature 014 T130; `cases.md` 7's last paragraph; CS-17;
FR-054; US5-8, US5-9, US5-16).

`tests/support/reachability.py` proves each committed case's producer tags and key reachability
with three legs: (a) code only, under the pane defaults; (b) a correct reviewer, under every lever
off and under the pane defaults; the decoys, under every lever off. This module proves the
validation itself, test-first: over `mount`, a small fictional design defined here (a plate, a
cover screwed to it with two screws, and the assembly's ingested sheet drawing two fits), built
with the builders and specified with the generator's own functions (`spec`, `seeds`, rendered by
`render.render_spec` inside `check_spec`), a correct case and its twin pass every leg, and each
deliberately wrong spec fails with the failures its leg gives, in `cases.md` 7's message forms:
the leg, the configuration, the case and the entry, the call written as `tool(arguments)` with
its resolved ids, never a recorded string.

1. **A correct case passes.** `mount-1` plants an unplaced thread mismatch and a transition fit,
   held out, and both it and its twin pass every leg: nothing below fails for want of a clean
   base.
2. **Each wrong spec fails, and only with its leg's failure** (`cases.md` 7's six): a seed tagged
   model-produced that code detects; a code seed the pre-run misses; a fit keyed to the wrong
   dimension pair; a twin whose clean form still fails; an unkeyed demonstrated finding in a clean
   base; a decoy sharing a planted entry's references. Then the rules those six do not reach
   (CS-17): a code defect at another status, a model defect flagged below expected, a
   model-origin false alarm, a cleared defect, and a twin condition its call does not confirm.
3. **Leg (a)'s call set** (RF-38): every offered check with no required parameter that the
   pre-run did not plan is called.
4. **Cost** (`cases.md` 7): a case's reviews run once per session.
5. **`check_design`**: the spec checks first, nothing rendered on a refusal; then every spec and
   its twin.

`mount`'s ids, which the messages name: `doc:0003` the cover, `doc:0006` the assembly's drawing,
`dim-1-1` to `dim-1-4` the bore, shaft, sibling bore and sibling shaft on its one sheet.
"""

from __future__ import annotations

import dataclasses
import re
import sys
from collections.abc import Mapping
from types import ModuleType
from typing import Any

import pytest

from swreview import cli, prerun
from swreview.ir.models import SourceRef
from tests.benchmark_cases import render, seeds, spec, stamps, vocabulary
from tests.benchmark_cases.spec import (
    CaseSpec,
    ComponentPlace,
    Design,
    DimensionPlace,
    DocumentPlace,
    HeldOut,
    HolePlace,
    Laid,
    Place,
    PlaceName,
    ScrewPlace,
    Seed,
    ToolCall,
    Tree,
    twin,
)
from tests.support import reachability
from tests.support.drawings import SheetBuilder
from tests.support.features import PartSpec, part_trees
from tests.support.mechanical import FICTIONAL_ROOT, Face, Instance, PackageBuilder
from tests.support.reachability import check_design, check_spec
from tests.support.standards import card

PROFILE = vocabulary.EXAMPLE_PROFILE
CURRENT = HeldOut(stamps.CURRENT)
Z = (0.0, 0.0, 1.0)

# --- the mount design ----------------------------------------------------------------------------

ROOT_STEM, PLATE_STEM, COVER_STEM = "EX-1101-00", "EX-1101-01", "EX-1101-02"
BOUGHT_FOLDER = PROFILE.part_roles.bought_folder_names[0]
VENDOR = PROFILE.part_roles.vendor_properties[0]
CLEARANCE_BORE = ("bilateral", 0.025, 0.0)
CLEARANCE_SHAFT = ("bilateral", -0.009, -0.025)

MOUNT_PLACES: dict[str, Place] = {
    "assy": DocumentPlace(),
    "plate_doc": DocumentPlace(tree=Tree()),
    "cover_doc": DocumentPlace(tree=Tree()),
    "assy_drw": DocumentPlace(),
    "plate": ComponentPlace(document="plate_doc"),
    "cover": ComponentPlace(document="cover_doc"),
    "tap_a": HolePlace(
        component="plate", thread="M5x0.8", thread_depth_mm=10.0, hole_depth_mm=12.0
    ),
    "tap_b": HolePlace(
        component="plate", thread="M5x0.8", thread_depth_mm=10.0, hole_depth_mm=12.0
    ),
    "clr_a": HolePlace(component="cover"),
    "clr_b": HolePlace(component="cover"),
    "screw_a": ScrewPlace(
        thread="M5-0.8", length_mm=12.0, hole="tap_a", clamped=("cover",), clamp_mm=4.0
    ),
    "screw_b": ScrewPlace(
        thread="M5-0.8", length_mm=12.0, hole="tap_b", clamped=("cover",), clamp_mm=4.0
    ),
    "bore": DimensionPlace(drawing="assy_drw", nominal_mm=10.0, limits=CLEARANCE_BORE, prefix="Ø"),
    "shaft": DimensionPlace(
        drawing="assy_drw", nominal_mm=10.0, limits=CLEARANCE_SHAFT, prefix="Ø"
    ),
    "sibling_bore": DimensionPlace(
        drawing="assy_drw", nominal_mm=8.0, limits=CLEARANCE_BORE, prefix="Ø"
    ),
    "sibling_shaft": DimensionPlace(
        drawing="assy_drw", nominal_mm=8.0, limits=CLEARANCE_SHAFT, prefix="Ø"
    ),
}
"""`mount`'s places: a joint and its sibling for the fastener kinds, a fit and its sibling on the
assembly's sheet for the fit kinds, and the custom plate whose tree the R-7 kinds read."""

HOLES: dict[str, tuple[str, str, float, float, float, float]] = {
    # name: (hole type, size, face diameter, x, face from, face to), z up from the joint face
    "tap_a": ("tapped", "M5x0.8", 4.2, 20.0, -12.0, 0.0),
    "tap_b": ("tapped", "M5x0.8", 4.2, 60.0, -12.0, 0.0),
    "clr_a": ("clearance", "Ø5.5", 5.5, 20.0, 0.0, 4.0),
    "clr_b": ("clearance", "Ø5.5", 5.5, 60.0, 0.0, 4.0),
}
DIMENSIONS = ("bore", "shaft", "sibling_bore", "sibling_shaft")


def custom_properties(place: Place, stem: str, summary: str) -> dict[str, str]:
    """A custom document's properties in the example profile's names (`generator.md` 5.2)."""
    assert isinstance(place, DocumentPlace)
    hygiene = PROFILE.hygiene
    assert hygiene is not None
    return {
        **card(PROFILE, revision="A" if place.revision else None),
        hygiene.part_number_property: stem,
        hygiene.description_property: summary,
    }


def lay_mount(variant: str | None, places: Mapping[str, Place]) -> Laid:
    """`mount`'s clean base with every form applied, through the builders (`generator.md` 5.1 to
    5.3): two custom aluminium parts with compliant trees, the plate fixed; two bought screws,
    each with its fastener row, seated on its tapped hole's axis unless its record says not;
    the assembly's drawing, an ingested sheet, carrying the four fit dimensions."""
    builder = PackageBuilder(
        ROOT_STEM, root_properties=custom_properties(places["assy"], ROOT_STEM, "mount assy")
    )
    ids: dict[str, str | SourceRef] = {"assy": builder.root_id}
    for name, stem, mass_kg, volume_mm3, summary in (
        ("plate_doc", PLATE_STEM, 0.2592, 96000.0, "mount plate"),
        ("cover_doc", COVER_STEM, 0.0648, 24000.0, "mount cover"),
    ):
        ids[name] = builder.document(
            stem,
            "part",
            material="6061-T6",
            mass_kg=mass_kg,
            volume_mm3=volume_mm3,
            properties=custom_properties(places[name], stem, summary),
        )
    ids["plate"] = builder.component(str(ids["plate_doc"]))
    ids["cover"] = builder.component(str(ids["cover_doc"]))
    for name, (hole_type, size, diameter, x, lo, hi) in HOLES.items():
        record = places[name]
        assert isinstance(record, HolePlace)
        ids[name] = builder.hole(
            str(ids[record.component]),
            hole_type=hole_type,  # type: ignore[arg-type]
            size=size,
            thread=record.thread,
            thread_depth_mm=record.thread_depth_mm,
            hole_depth_mm=record.hole_depth_mm,
            end_condition="blind" if record.thread else "through",
            instances=[Instance((x + record.offset_mm, 0.0, 0.0), Z, (Face(diameter, lo, hi),))],
        )
    screws: dict[str, str] = {}
    for serial, name in enumerate(("screw_a", "screw_b"), start=1):
        record = places[name]
        assert isinstance(record, ScrewPlace)
        x = HOLES[record.hole][3]
        # An unseated screw stands 1 mm off its hole's axis both ways: on no extracted axis.
        off = 0.0 if record.seated else 1.0
        document = builder.screw_document(
            "SHC", record.thread, record.length_mm, serial=serial, properties={VENDOR: "FICT"}
        )
        screws[name] = builder.screw(
            document, bearing_mm=(x + off, off, record.clamp_mm), direction=Z, fastener_row=True
        )

    built = builder.build()
    package = built.package
    for name, component in screws.items():
        ids[name] = next(row.id for row in package.fasteners if row.component_id == component)
    bought = {row.document_id for row in package.components if row.id in screws.values()}
    documents = [
        document.model_copy(
            update={"path": f"{FICTIONAL_ROOT}Vault\\{BOUGHT_FOLDER}\\{document.file_name}"}
        )
        if document.document_id in bought
        else document
        for document in package.documents
    ]
    paths = {document.document_id: document.path for document in documents}
    entries = [
        entry.model_copy(update={"vault_path": paths[entry.document_id]})
        for entry in package.manifest.entries
    ]
    components = [
        row.model_copy(update={"is_fixed": row.id == ids["plate"]}) for row in package.components
    ]
    trees = []
    for name, stem in (("plate_doc", PLATE_STEM), ("cover_doc", COVER_STEM)):
        record = places[name]
        assert isinstance(record, DocumentPlace) and record.tree is not None
        features, equations = spec.tree_specs(record.tree)
        trees.append(
            PartSpec(document_id=str(ids[name]), name=stem, features=features, equations=equations)
        )
    features, equations = part_trees(trees)
    package = package.model_copy(
        update={
            "documents": documents,
            "manifest": package.manifest.model_copy(update={"entries": entries}),
            "components": components,
            "features": features,
            "equations": equations,
        }
    )

    sheets = SheetBuilder(package)
    ids["assy_drw"] = sheets.drawing(
        ROOT_STEM, properties=custom_properties(places["assy_drw"], ROOT_STEM, "mount drawing")
    )
    sheets.sheet(str(ids["assy_drw"]), page=1)
    for name in DIMENSIONS:
        record = places[name]
        assert isinstance(record, DimensionPlace)
        ids[name] = sheets.dimension(
            str(ids[record.drawing]),
            record.sheet,
            record.nominal_mm,
            limits=record.limits,
            text=record.as_read(),
        )
    return Laid(package=sheets.build(), meshes=built.meshes, ids=ids)


MOUNT = Design(name="mount", places=MOUNT_PLACES, lay=lay_mount)

UNREVISED = dataclasses.replace(
    MOUNT, places={**MOUNT_PLACES, "cover_doc": DocumentPlace(revision=False, tree=Tree())}
)
"""`mount` with the cover's revision left out and no seed keying it: a base that is not clean."""

JOINT = {"fastener": "screw_a", "sibling": "screw_b"}
FIT = {
    "bore": "bore",
    "shaft": "shaft",
    "sibling_bore": "sibling_bore",
    "sibling_shaft": "sibling_shaft",
}

GOOD = CaseSpec(
    case_id="mount-1",
    design=MOUNT,
    seeds=(
        Seed(seeds.THREAD_MISMATCH_UNPLACED, JOINT, CURRENT),
        Seed(seeds.FIT_TRANSITION, FIT, CURRENT),
    ),
    twin=True,
)
"""A core case as a design task writes one: two held-out model-produced seeds of two families,
with its twin."""


def case(case_id: str, *seeded: Seed, design: Design = MOUNT, twin: bool = False) -> CaseSpec:
    return CaseSpec(case_id=case_id, design=design, seeds=seeded, twin=twin)


KEPT = dataclasses.replace(seeds.RMS_GLOBAL_VARIABLES, clean=seeds.RMS_GLOBAL_VARIABLES.plant)
KEPT_CASE = case("mount-5", Seed(KEPT, {"component": "plate"}, CURRENT), twin=True)
"""An R-7 seed whose clean form leaves the global variable out, as its plant does: a case whose
twin is not clean."""
KEPT_TWIN_FAILURE = "(a) mount-5-twin finding F-nnn contradicts C-1"

UNREVISED_CASE = case("mount-6", design=UNREVISED)
UNREVISED_FAILURE = (
    "(a) mount-6 finding F-nnn (hygiene.revision_present, demonstrated, doc:0003) matches no "
    "known defect or forbidden entry: the package is not clean apart from its planted defects"
)


def dimension(annotation: str) -> str:
    """A drawn dimension on `mount`'s assembly sheet as a message writes a call's argument."""
    return f'{{"document_id": "doc:0006", "sheet": "Sheet1", "annotation": "{annotation}"}}'


def fit_call(bore: str, shaft: str) -> str:
    return (
        f"check_fit(bore_dimension_ref={dimension(bore)}, shaft_dimension_ref={dimension(shaft)})"
    )


FIT_CALL = fit_call("dim-1-1", "dim-1-2")
SIBLING_FIT_CALL = fit_call("dim-1-3", "dim-1-4")


def wrong_pair(at: Mapping[str, str], places: Mapping[str, Place]) -> tuple[dict[str, Any], ...]:
    """A fit's key element naming the bore with the sibling's shaft: a pair no call checks."""
    return ({"bore": PlaceName(at["bore"]), "shaft": PlaceName(at["sibling_shaft"])},)


def assert_failures(failures: list[str], expected: list[str]) -> None:
    """`failures` are `expected`, in order, `F-nnn` in an expected message standing for the one
    finding id it names: the review's own numbering, which the message names and no test pins."""
    assert len(failures) == len(expected), failures
    for failure, message in zip(failures, expected, strict=True):
        pattern = r"F-\d{3}".join(re.escape(part) for part in message.split("F-nnn"))
        assert re.fullmatch(pattern, failure), (failure, message)


# --- 1. a correct case passes ---------------------------------------------------------------------


def test_a_correct_case_and_its_twin_pass_every_leg() -> None:
    """Leg (a): code detects neither held-out defect and the base is clean; leg (b): the joint
    and fit calls credit both, under off and pane, and confirm both twin conditions; decoys: the
    sibling joint, the sibling fit and the bore against itself touch neither."""
    assert check_spec(GOOD) == []
    assert check_spec(twin(GOOD)) == []


# --- 2. each wrong spec fails, with its leg's failure ---------------------------------------------


def test_a_seed_tagged_model_produced_that_code_detects_fails_leg_a() -> None:
    """US5-8: a `thread_mismatch_unplaced` whose screw is placed on the hole's axis, so the
    pre-run's joint map checks the thread itself."""
    placed = dataclasses.replace(
        seeds.THREAD_MISMATCH_UNPLACED, plant=seeds.THREAD_MISMATCH_PLACED.plant
    )

    assert check_spec(case("mount-2", Seed(placed, JOINT, CURRENT))) == [
        "(a) mount-2 D-1 (fastener.thread_match, model-produced) is detected by code-only calls: "
        "it is code-produced, or its seed withholds too little (16A)"
    ]


def test_a_code_seed_the_pre_run_misses_fails_leg_a() -> None:
    """A `thread_mismatch_placed`, code-produced, whose screw the plant leaves off every hole
    axis, so the joint map never places it."""
    unplaced = dataclasses.replace(
        seeds.THREAD_MISMATCH_PLACED, plant=seeds.THREAD_MISMATCH_UNPLACED.plant
    )

    assert check_spec(case("mount-3", Seed(unplaced, {"fastener": "screw_a"}, CURRENT))) == [
        "(a) mount-3 D-1 (fastener.thread_match, code-produced) is not detected by code"
    ]


def test_a_fit_keyed_to_the_wrong_dimension_pair_fails_leg_b_under_off_and_pane() -> None:
    """US5-9: a missing limit keyed to the bore and the sibling's shaft. The correct call flags
    the bore and shaft it checks, which the key does not name; its finding is unresolved, so no
    false alarm, and no decoy checks the keyed pair."""
    misnamed = dataclasses.replace(seeds.FIT_LIMIT_MISSING, references=wrong_pair)

    assert check_spec(case("mount-4", Seed(misnamed, FIT, CURRENT))) == [
        f"(b, off) mount-4 D-1 is not credited or flagged under {FIT_CALL}",
        f"(b, pane) mount-4 D-1 is not credited or flagged under {FIT_CALL}",
    ]


def test_a_twin_whose_clean_form_still_fails_contradicts_its_condition_under_leg_a() -> None:
    """An R-7 seed whose clean form leaves the global variable out: the twin's condition says the
    plate holds one, and the pre-run's RMS check says it does not. Only leg (a) reads it: the
    kind has no correct call, and a code finding is no model-origin false alarm."""
    assert check_spec(KEPT_CASE) == []
    assert_failures(check_spec(twin(KEPT_CASE)), [KEPT_TWIN_FAILURE])


def test_an_unkeyed_demonstrated_finding_in_a_clean_base_fails_leg_a() -> None:
    """The cover carries no revision and nothing keys it: hygiene's demonstrated finding on its
    document matches no entry. Leg (b) does not read it: under pane it is the pre-run's."""
    assert_failures(check_spec(UNREVISED_CASE), [UNREVISED_FAILURE])


def test_a_decoy_sharing_a_planted_entrys_references_clears_it() -> None:
    """US5-16: a transition fit keyed to its own pair and to the sibling's, so the sibling fit's
    clean finding, a decoy's, matches it."""

    def both_pairs(at: Mapping[str, str], places: Mapping[str, Place]) -> tuple[Any, ...]:
        return (
            {"bore": PlaceName(at["bore"]), "shaft": PlaceName(at["shaft"])},
            {"bore": PlaceName(at["sibling_bore"]), "shaft": PlaceName(at["sibling_shaft"])},
        )

    shared = dataclasses.replace(seeds.FIT_TRANSITION, references=both_pairs)

    assert check_spec(case("mount-7", Seed(shared, FIT, CURRENT))) == [
        f"(decoy) mount-7 {SIBLING_FIT_CALL} clears D-1: the key's references do not tell the "
        "fits apart"
    ]


def test_a_code_defect_at_another_status_is_a_status_mismatch_under_leg_a() -> None:
    """Leg (a) rule 1's "none a status mismatch" (CS-17): code demonstrates the placed thread
    mismatch a key expects unresolved."""
    hedged = dataclasses.replace(seeds.THREAD_MISMATCH_PLACED, expected_status="unresolved")

    assert check_spec(case("mount-8", Seed(hedged, {"fastener": "screw_a"}, CURRENT))) == [
        "(a) mount-8 D-1 (fastener.thread_match, code-produced) is a status mismatch: code "
        "credits it while the key expects unresolved"
    ]


def test_a_model_defect_the_evidence_cannot_support_is_flagged_below_expected() -> None:
    """Leg (b) rule 1 (US5-9, 13A): a missing limit keyed as suspected, which the fit check can
    only flag unresolved."""
    overstated = dataclasses.replace(seeds.FIT_LIMIT_MISSING, expected_status="suspected")

    assert check_spec(case("mount-9", Seed(overstated, FIT, CURRENT))) == [
        f"(b, off) mount-9 D-1 is flagged below expected under {FIT_CALL}",
        f"(b, pane) mount-9 D-1 is flagged below expected under {FIT_CALL}",
    ]


def test_a_correct_call_matching_no_entry_is_a_model_origin_false_alarm() -> None:
    """Leg (b) rule 3: a transition fit keyed to the wrong pair. The correct call's suspected
    finding credits nothing, so the defect is not credited and the finding is a false alarm the
    model decided (a configured check's)."""
    misnamed = dataclasses.replace(seeds.FIT_TRANSITION, references=wrong_pair)

    assert_failures(
        check_spec(case("mount-10", Seed(misnamed, FIT, CURRENT))),
        [
            f"(b, off) mount-10 D-1 is not credited or flagged under {FIT_CALL}",
            "(b, off) mount-10 finding F-nnn is a model-origin false alarm",
            f"(b, pane) mount-10 D-1 is not credited or flagged under {FIT_CALL}",
            "(b, pane) mount-10 finding F-nnn is a model-origin false alarm",
        ],
    )


def test_a_defect_planted_in_its_clean_form_is_cleared_by_its_correct_call() -> None:
    """Leg (b) rule 2: a transition fit whose plant draws clearance limits, so the correct call
    finds the fit clear."""
    unplanted = dataclasses.replace(seeds.FIT_TRANSITION, plant=seeds.CLEAN_FIT)

    assert_failures(
        check_spec(case("mount-11", Seed(unplanted, FIT, CURRENT))),
        [
            f"(b, off) mount-11 D-1 is not credited or flagged under {FIT_CALL}",
            "(b, off) mount-11 D-1 is cleared by finding F-nnn",
            f"(b, pane) mount-11 D-1 is not credited or flagged under {FIT_CALL}",
            "(b, pane) mount-11 D-1 is cleared by finding F-nnn",
        ],
    )


def test_a_twin_condition_its_correct_call_does_not_confirm_fails_leg_b() -> None:
    """Leg (b) rule 4: the twin's fit condition carries a correct call on the sibling pair, which
    is clear but is not the pair the condition names."""

    def sibling_call(at: Mapping[str, str], places: Mapping[str, Place]) -> tuple[ToolCall]:
        return (
            ToolCall(
                "check_fit",
                {
                    "bore_dimension_ref": PlaceName(at["sibling_bore"]),
                    "shaft_dimension_ref": PlaceName(at["sibling_shaft"]),
                },
            ),
        )

    elsewhere = dataclasses.replace(seeds.FIT_TRANSITION, correct_calls=sibling_call)
    source = case("mount-12", Seed(elsewhere, FIT, CURRENT), twin=True)

    assert check_spec(twin(source)) == [
        f"(b, off) mount-12-twin C-1 is not confirmed under {SIBLING_FIT_CALL}",
        f"(b, pane) mount-12-twin C-1 is not confirmed under {SIBLING_FIT_CALL}",
    ]


# --- 3. leg (a)'s call set ------------------------------------------------------------------------


def test_leg_a_calls_an_offered_check_the_pre_run_did_not_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RF-38: with `check_hygiene` taken out of the pre-run's plan, the hygiene finding on the
    unrevised cover is still written, by leg (a)'s own call; without that call the case would
    pass. The cache is emptied, so no earlier review of the same case answers for this one."""
    planned = prerun.planned_calls

    def without_hygiene(*args: Any, **kwargs: Any) -> tuple[tuple[str, dict[str, Any]], ...]:
        return tuple(call for call in planned(*args, **kwargs) if call[0] != "check_hygiene")

    monkeypatch.setattr(prerun, "planned_calls", without_hygiene)
    monkeypatch.setattr(reachability, "REVIEWED", {})

    assert_failures(check_spec(UNREVISED_CASE), [UNREVISED_FAILURE])


# --- 4. cost --------------------------------------------------------------------------------------


def test_a_case_is_reviewed_once_per_session(monkeypatch: pytest.MonkeyPatch) -> None:
    """`cases.md` 7, "Cost": the four reviews run on the first check and none on the second,
    though each check renders into its own temporary checkout."""
    reviews: list[Any] = []
    review_fn = cli._review_fn

    def counted(*args: Any, **kwargs: Any) -> Any:
        session = review_fn(*args, **kwargs)
        reviews.append(session)
        return session

    monkeypatch.setattr(cli, "_review_fn", counted)
    monkeypatch.setattr(reachability, "REVIEWED", {})

    first = check_spec(GOOD)
    assert len(reviews) == 4
    assert check_spec(GOOD) == first
    assert len(reviews) == 4


# --- 5. check_design ------------------------------------------------------------------------------


def design_module(monkeypatch: pytest.MonkeyPatch, *specs: CaseSpec) -> str:
    """A design module named `mount`, holding `specs`, where `check_design` imports it."""
    module = ModuleType("tests.benchmark_cases.designs.mount")
    module.SPECS = specs  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, module.__name__, module)
    return "mount"


def test_check_design_returns_the_spec_checks_refusal_and_renders_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Design rule 9's `check_specs` half: a refused spec list is the one failure."""

    def never(case: CaseSpec) -> dict[str, bytes]:
        raise AssertionError(f"{case.case_id} was rendered")

    monkeypatch.setattr(render, "render_spec", never)
    name = design_module(monkeypatch, GOOD, GOOD)

    assert check_design(name) == ["case spec mount-1: case id mount-1 is named twice (cases.md 2)"]


def test_check_design_checks_every_spec_and_its_twin(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every spec passes `check_specs`; the second's twin fails leg (a), and only its twin."""
    name = design_module(monkeypatch, GOOD, KEPT_CASE)

    assert_failures(check_design(name), [KEPT_TWIN_FAILURE])
