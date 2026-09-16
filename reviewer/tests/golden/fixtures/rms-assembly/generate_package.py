"""Generate `package.json` and `case.json` for the rms-assembly fixture (T036).

Run once, from `reviewer/`, and commit what it writes:

    uv run python tests/golden/fixtures/rms-assembly/generate_package.py

A script rather than a hand-built JSON for the same reason as the rms-part fixture: the
shape of a root assembly in `package.json` - `cmp:NNNN` in package order, `parent_id`,
`full_path`, one `persist_ref` per instance, mate entities resolved to instance ids - is
what `tests/support/features.py` already lays out, and a second hand-maintained copy of
that knowledge would drift from the builder the unit tests use (constitution Principle V).
The *intent* - which rule each component and mate seeds - lives here and is readable
without reading the JSON.

One root assembly, `doc:1`, holding every outcome the four assembly rules of
`specs/003-resilient-modeling/contracts/rules.md` can reach:

- **`rms.assembly.mates_to_reference_geometry` fails** on the one face mate (`base-1` to
  `plate-1`) and passes on the six that reference planes.
- **`rms.assembly.first_component_fixed` fails**: `base-1` is the first child of `cmp:0001`
  in package order and is neither fixed nor fully constrained (`swUnderConstrained`). The
  fixed component, `plate-1`, comes later, which is exactly the tree the rule is about -
  "something in the assembly is fixed" is not the same claim as "the first component is".
- **`rms.assembly.mate_chain_depth` warns**: from the fixed `plate-1` the links run
  `link-1`, `link-2`, `link-3`, `link-4`, so `link-4` sits four mates out and the limit is
  three. The suppressed mate from `plate-1` straight to `link-4` is what makes that
  visible: if a suppressed mate were an edge, `link-4` would read as one mate from the
  root. `screw-1`, `screw-2` and `washer-1` are mated to nothing and are unresolved rather
  than deep.
- **`rms.assembly.toolbox_parts_not_configurations` warns**: `doc:6` is one Toolbox part
  file inserted as two configurations, `M4x10` and `M6x20`. `washer-1` carries the
  Toolbox-identity gap `ComponentTreeDumper.ReadIsToolbox` records, so it is unresolved -
  `is_toolbox` is false-on-failure and must not be read as "not Toolbox".

The subassembly `doc:2` is never graded: only the root's mates are extracted, so it
surfaces through the `rms.assembly.subassemblies` coverage item that names it. The parts
carry no feature rows and no equations, because an assembly call must not evaluate a part
or equation rule and a package with nothing for one to read makes that visible.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

FIXTURE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(FIXTURE_DIR.parents[3]))

from tests.support.features import (  # noqa: E402
    AssemblySpec,
    InstanceSpec,
    MateSpec,
    PartSpec,
    SubassemblySpec,
    rms_package,
    toolbox_identity_gap,
)

from swreview.ir.loader import save_package  # noqa: E402
from swreview.ir.models import EvidencePackage  # noqa: E402

CASE_CALLABLE = "swreview.checks.golden_rms:assembly_case"

ROOT = "doc:1"
SUBASSEMBLY = "doc:2"
BASE = "doc:3"
PLATE = "doc:4"
LINK = "doc:5"
SCREW = "doc:6"
WASHER = "doc:7"

UNDER_DEFINED = 2
"""`swConstrainedStatus_e.swUnderConstrained`, as `checks/rms_types.yaml` maps it."""

PLANE = "swSelDATUMPLANES"
FACE = "swSelFACES"
"""`swSelectType_e` names as `MateDumper` writes them: one reference kind, one geometry
kind. The table's two lists are what the rule reads, so nothing else is spelled here."""


def parts() -> list[PartSpec]:
    """The part documents, in the order that decides the `cmp:NNNN` ids.

    `base` is first because `rms.assembly.first_component_fixed` reports on the first
    child of the root instance in package order, and the fixture's point is that the fixed
    component is not it.
    """
    return [
        PartSpec(
            document_id=BASE,
            name="base",
            instances=(InstanceSpec("base-1", constrained_status_raw=UNDER_DEFINED),),
        ),
        PartSpec(
            document_id=PLATE,
            name="plate",
            instances=(InstanceSpec("plate-1", is_fixed=True),),
        ),
        PartSpec(
            document_id=LINK,
            name="link",
            instances=tuple(InstanceSpec(f"link-{number}") for number in (1, 2, 3, 4)),
        ),
        PartSpec(
            document_id=SCREW,
            name="screw",
            configuration="M4x10",
            configurations=("M4x10", "M6x20"),
            instances=(
                InstanceSpec("screw-1", is_toolbox=True),
                InstanceSpec("screw-2", is_toolbox=True, referenced_configuration="M6x20"),
            ),
        ),
        PartSpec(
            document_id=WASHER,
            name="washer",
            instances=(InstanceSpec("washer-1"),),
        ),
    ]


def mates() -> tuple[MateSpec, ...]:
    """The root assembly's mates, in the order that decides the `mate:NNNN` ids."""
    return (
        MateSpec(entities=(("base-1", FACE), ("plate-1", FACE)), type="COINCIDENT"),
        MateSpec(entities=(("plate-1", PLANE), ("link-1", PLANE)), type="COINCIDENT"),
        MateSpec(entities=(("link-1", PLANE), ("link-2", PLANE)), type="COINCIDENT"),
        MateSpec(entities=(("link-2", PLANE), ("link-3", PLANE)), type="COINCIDENT"),
        MateSpec(entities=(("link-3", PLANE), ("link-4", PLANE)), type="COINCIDENT"),
        MateSpec(
            entities=(("plate-1", PLANE), ("link-4", PLANE)),
            type="PARALLEL",
            suppressed=True,
        ),
        MateSpec(entities=(("plate-1", PLANE), ("gearbox-1", PLANE)), type="COINCIDENT"),
    )


def build() -> EvidencePackage:
    return rms_package(
        parts=parts(),
        assembly=AssemblySpec(
            document_id=ROOT,
            name="rms-assembly",
            mates=mates(),
            subassembly=SubassemblySpec(document_id=SUBASSEMBLY, name="gearbox"),
        ),
        gaps=(toolbox_identity_gap("washer-1"),),
    )


def main() -> None:
    save_package(build(), FIXTURE_DIR)
    case = {"callable": CASE_CALLABLE}
    (FIXTURE_DIR / "case.json").write_text(json.dumps(case, indent=2) + "\n", encoding="utf-8")
    print(f"wrote package.json and case.json in {FIXTURE_DIR}")


if __name__ == "__main__":
    main()
