"""Generate `package.json`, `exceptions.json` and `case.json` for the rms-part fixture.

Run once, from `reviewer/`, and commit what it writes:

    uv run python tests/golden/fixtures/rms-part/generate_package.py

It is a script and not a fixture built by hand because the shape of a feature tree in
`package.json` - ids in traversal order, `folder_id`, `depth`, resolved child/parent/
consumer ids, one `persist_ref` per row - is exactly what `tests/support/features.py`
already knows how to lay out, and a second, hand-maintained copy of that knowledge would
drift from the builder the unit tests use (constitution Principle V, DRY). The *intent* -
which rule each feature seeds - lives here, in the three part specs below, and is
readable without reading the JSON.

Three parts, per T030:

- **frame** (`doc:2`) is compliant: six group folders in the method's order, every content
  feature described, every sketch fully defined and consumed once, the shell last in Core,
  the holes trailing Detail, the draft before the pattern in Modify, and Quarantine holding
  one chamfer then non-increasing fillets that nothing depends on.
- **bracket** (`doc:3`) seeds one violation of every part rule that is reachable while all
  six group folders exist - sixteen of the eighteen. The two that are not reachable here
  are `rms.folders.present`, which can only be violated by a *missing* group (widget below
  is missing two), and `rms.detail.individually_suppressible`, which needs a
  `suppress-test` run this package deliberately does not carry, so it stays unresolved.
  The duplicated `3-Core` folder after `4-Detail` does double duty exactly as the native
  recipe's part B does (`benchmarks/native/rms-part/RECIPE.md`): it fails
  `rms.folders.ordered`, and it is what puts a Core feature *after* a Detail feature in
  the tree so that `rms.refs.direction` can be violated by a physically possible tree.
- **widget** (`doc:4`) is the unknown-data part: a feature whose `GetChildren` failed
  (`child_ids: null`), a type name in no class set, and an `ICE` feature, each placed in
  the group whose rule reports it, plus two missing group folders.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

FIXTURE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(FIXTURE_DIR.parents[3]))

from pydantic_core import to_jsonable_python  # noqa: E402
from tests.support.features import (  # noqa: E402
    AssemblySpec,
    PartSpec,
    feature,
    fillet_feature,
    folder,
    rms_package,
    sketch_feature,
)

from swreview.exceptions import EXCEPTIONS_FILE_NAME, ExceptionStore  # noqa: E402
from swreview.ir.loader import save_package  # noqa: E402
from swreview.ir.models import EvidencePackage  # noqa: E402

CASE_CALLABLE = "swreview.checks.golden_rms:part_case"

UNDER_DEFINED = 2
OVER_DEFINED = 4
"""`swConstrainedStatus_e` raw values, as `checks/rms_types.yaml` maps them."""

WAIVED_RULE = "rms.quarantine.only_fillets_and_chamfers"
BRACKET_INSTANCE = "cmp:0003"
"""The waiver in the fixture: the bracket's stray Quarantine draft, accepted, so the
baseline pins the `waived` outcome as well as `fail`, `warn`, `pass`, `skip` and
`unresolved`."""


def frame() -> PartSpec:
    """The compliant part: every reachable part rule passes."""
    return PartSpec(
        document_id="doc:2",
        name="frame",
        features=(
            folder("1-Ref", feature("Axis1", "RefAxis")),
            folder(
                "2-Construction",
                sketch_feature("Sketch1", consumers=("Surface-Extrude1",)),
                feature("Surface-Extrude1", "SurfaceExtrude", parent_names=("Sketch1",)),
            ),
            folder(
                "3-Core",
                sketch_feature("Sketch2", consumers=("Boss-Extrude1",)),
                feature("Boss-Extrude1", "Extrusion", parent_names=("Sketch2",)),
                feature("Shell1", "Shell"),
            ),
            folder(
                "4-Detail",
                sketch_feature("Sketch3", consumers=("Cut-Extrude1",)),
                feature("Cut-Extrude1", "Cut", parent_names=("Sketch3",)),
                feature("Hole1", "HoleWzd"),
            ),
            folder(
                "5-Modify",
                feature("Draft1", "Draft"),
                feature("LPattern1", "LPattern"),
            ),
            folder(
                "6-Quarantine",
                feature("Chamfer1", "Chamfer"),
                fillet_feature("Fillet1", radius_m=0.006),
                fillet_feature("Fillet2", radius_m=0.003),
            ),
        ),
    )


def bracket() -> PartSpec:
    """One violation per part rule reachable with all six group folders present.

    The seed for each rule, in the order the catalogue lists them:

    - `rms.folders.ordered`: the second `3-Core` folder, after `4-Detail`;
    - `rms.grouping.all_features_in_a_group`: `Axis1`, above the first group folder;
    - `rms.groups.no_solids_in_ref_or_construction`: `Boss-Extrude1` in `2-Construction`;
    - `rms.core.shell_last`: `Boss-Extrude4` after `Shell1` in `3-Core`;
    - `rms.detail.holes_last`: `Cut-Extrude5` after `Hole1` in `4-Detail`;
    - `rms.modify.transform_before_replicate`: `LPattern1` before `Draft1`;
    - `rms.quarantine.chamfers_before_fillets`: `Fillet1` before `Chamfer1`;
    - `rms.quarantine.largest_fillet_first`: radii 2, 5, 1 mm;
    - `rms.quarantine.only_fillets_and_chamfers`: `Draft2` in `6-Quarantine`;
    - `rms.refs.direction`: `Boss-Extrude5`, in the re-opened `3-Core`, is sketched on
      `Cut-Extrude4` in `4-Detail`, so a dependent sits in an earlier group;
    - `rms.refs.quarantine_has_no_children`: `Fillet3` rounds an edge `Fillet1` made;
    - `rms.detail.no_internal_references`: `Cut-Extrude3` depends on `Cut-Extrude2`, both
      loose in `4-Detail`, so neither carve-out applies;
    - `rms.intent.every_feature_described`: `Draft1` carries an empty description;
    - `rms.sketches.fully_defined`: `Sketch2` is under defined;
    - `rms.sketches.not_over_defined`: `Sketch5` is over defined;
    - `rms.sketches.one_sketch_per_feature`: `Sketch3` feeds two extrusions.
    """
    return PartSpec(
        document_id="doc:3",
        name="bracket",
        features=(
            feature("Axis1", "RefAxis"),
            folder("1-Ref", feature("Axis2", "RefAxis")),
            folder(
                "2-Construction",
                sketch_feature(
                    "Sketch2", raw_status=UNDER_DEFINED, consumers=("Surface-Extrude1",)
                ),
                feature("Surface-Extrude1", "SurfaceExtrude", parent_names=("Sketch2",)),
                feature("Boss-Extrude1", "Extrusion"),
            ),
            folder(
                "3-Core",
                sketch_feature("Sketch3", consumers=("Boss-Extrude2", "Boss-Extrude3")),
                feature("Boss-Extrude2", "Extrusion", parent_names=("Sketch3",)),
                feature("Boss-Extrude3", "Extrusion", parent_names=("Sketch3",)),
                feature("Shell1", "Shell"),
                feature("Boss-Extrude4", "Extrusion"),
            ),
            folder(
                "4-Detail",
                sketch_feature("Sketch4", consumers=("Cut-Extrude2",)),
                feature("Cut-Extrude2", "Cut", child_names=("Cut-Extrude3",)),
                feature("Cut-Extrude3", "Cut", parent_names=("Cut-Extrude2",)),
                sketch_feature("Sketch5", raw_status=OVER_DEFINED, consumers=("Cut-Extrude5",)),
                feature("Hole1", "HoleWzd"),
                feature("Cut-Extrude5", "Cut", parent_names=("Sketch5",)),
                feature("Cut-Extrude4", "Cut", child_names=("Boss-Extrude5",)),
            ),
            folder("3-Core", feature("Boss-Extrude5", "Extrusion", parent_names=("Cut-Extrude4",))),
            folder(
                "5-Modify",
                feature("LPattern1", "LPattern"),
                feature("Draft1", "Draft", description=""),
            ),
            folder(
                "6-Quarantine",
                fillet_feature("Fillet1", radius_m=0.002, child_names=("Fillet3",)),
                feature("Chamfer1", "Chamfer"),
                fillet_feature("Fillet2", radius_m=0.005),
                fillet_feature("Fillet3", radius_m=0.001, parent_names=("Fillet1",)),
                feature("Draft2", "Draft"),
            ),
        ),
    )


def widget() -> PartSpec:
    """The unknown-data part: a null child list, an unlisted type, and `ICE`.

    Each unknown sits in the group whose rule has to report it rather than guess:
    `Widget1` in `1-Ref` for `rms.groups.no_solids_in_ref_or_construction`, `Ice1` in
    `4-Detail` for `rms.detail.holes_last`, `Widget2` in `6-Quarantine` for
    `rms.quarantine.only_fillets_and_chamfers`, and `Boss-Extrude1`'s null `child_ids`
    for the three reference rules. `2-Construction` and `5-Modify` are missing, which is
    what fails `rms.folders.present`.
    """
    return PartSpec(
        document_id="doc:4",
        name="widget",
        features=(
            folder("1-Ref", feature("Widget1", "NoSuchType")),
            folder(
                "3-Core",
                sketch_feature("Sketch1", consumers=("Boss-Extrude1",)),
                feature(
                    "Boss-Extrude1", "Extrusion", parent_names=("Sketch1",), child_names=None
                ),
            ),
            folder(
                "4-Detail",
                feature("Hole1", "HoleWzd"),
                feature("Ice1", "ICE"),
            ),
            folder(
                "6-Quarantine",
                feature("Chamfer1", "Chamfer"),
                feature("Widget2", "NoSuchType"),
            ),
        ),
    )


def build() -> EvidencePackage:
    return rms_package(
        parts=[frame(), bracket(), widget()],
        assembly=AssemblySpec(document_id="doc:1", name="rms-part-assy"),
    )


class _AcceptedFinding:
    """The `FingerprintTarget` shape `ExceptionStore.accept` reads."""

    def __init__(self, check: str, component_ids: list[str], configuration: str) -> None:
        self.check = check
        self.component_ids = component_ids
        self.configuration = configuration


def main() -> None:
    package = build()
    save_package(package, FIXTURE_DIR)

    store = ExceptionStore(FIXTURE_DIR / EXCEPTIONS_FILE_NAME)
    store.accept(
        _AcceptedFinding(
            check=WAIVED_RULE,
            component_ids=[BRACKET_INSTANCE],
            configuration=package.design.active_configuration,
        ),
        package,
        by="engineer",
        note="legacy bracket; the Quarantine draft is scheduled for removal at the next revision",
        at=datetime(2026, 9, 15, 9, 15, tzinfo=UTC),
    )
    store.save()

    case = {
        "callable": CASE_CALLABLE,
        "kwargs": {"exceptions": to_jsonable_python(store.exceptions)},
    }
    (FIXTURE_DIR / "case.json").write_text(json.dumps(case, indent=2) + "\n", encoding="utf-8")
    print(f"wrote package.json, {EXCEPTIONS_FILE_NAME} and case.json in {FIXTURE_DIR}")


if __name__ == "__main__":
    main()
