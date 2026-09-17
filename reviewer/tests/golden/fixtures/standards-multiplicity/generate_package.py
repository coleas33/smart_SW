"""Generate the `standards-multiplicity` golden: the counting rule, proved (T056).

Run once, from `reviewer/`, and commit what it writes:

    uv run python tests/golden/fixtures/standards-multiplicity/generate_package.py

SC-006's third half. FR-003 says a failing check produces **one finding per document**,
naming every instance and every path that reaches it - not one per instance, one per
parent, one per subject or one per blank field. This fixture makes that a measurement:

- **one sub-assembly under two parents.** `MR-40004` is instantiated once under `MR-40002`
  and once under `MR-40003`. It is exploded, records a rebuild error and carries an
  incomplete data card, so it fails three checks - and each of them is **one** finding
  naming **both** instances, not two findings and not two sets of assembly rows;
- **one part under many instances.** `MR-40010` is instantiated four times under each of
  the two sub-assemblies. It has neither a material nor a mass override, so
  `standards.part.material_assigned` fails once, naming all eight;
- **the error count is four**, which is the number of distinct failing
  **(check, document)** pairs and nothing else.

This fixture exists separately from `standards-seeded` because that one must contain
exactly one assembly document (SC-001), and a shared sub-assembly is exactly what it must
not have. The other two halves of SC-006 - the part reached through twenty instances and
the drawing carrying six overridden dimensions - live there.

**It carries no drawing**, so its four drawing rows are `out_of_scope` coverage in every
run (difference a, difference n; quickstart Scenario 4b).

One limit of the builder is worth stating, because the package would otherwise look
careless: `tests/support/standards.py` requires every component instance to carry a name
unique in the **package**, so the second occurrence of `MR-40004` cannot repeat its
children's names the way a real dump does. Its one child therefore hangs under the first
occurrence. Nothing this fixture measures depends on that: `MR-40004` is still reached
through two instances under two different parents, which is what the counting rule is
about, and its three findings name both of them.
"""

from __future__ import annotations

import sys
from pathlib import Path

FIXTURE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(FIXTURE_DIR.parents[3]))

from tests.checks.standards_fixtures import card, fixture_profile, write_fixture  # noqa: E402
from tests.support.features import FeatureSpec, SketchSpec  # noqa: E402
from tests.support.standards import (  # noqa: E402
    AssemblySpec,
    ComponentSpec,
    MateEntitySpec,
    MateSpec,
    PartSpec,
    standards_package,
)

from swreview.ir.models import EvidencePackage  # noqa: E402

PROFILE = fixture_profile()

ROOT_ASSEMBLY = "MR-40001"
LEFT_ASSEMBLY = "MR-40002"
RIGHT_ASSEMBLY = "MR-40003"
SHARED_ASSEMBLY = "MR-40004"
MANY_PART = "MR-40010"
PLAIN_PART = "MR-40011"

JOB_FOLDER = "jobs/twin"
MATERIAL = "Fictional Alloy 5"
CONFIGURATION = PROFILE.material.configuration

DEFINED = 3
COPIES = 4
"""How many instances of `MR-40010` hang under each of the two sub-assemblies: eight in
all, and still one finding."""


def part(name: str, *, material: str | None = MATERIAL) -> PartSpec:
    return PartSpec(
        name=name,
        folder=JOB_FOLDER,
        configuration=CONFIGURATION,
        properties=card(PROFILE),
        material=material,
        mass_overridden=False,
        features=(
            FeatureSpec(
                "Boss-Extrude1",
                "Extrude",
                contents=(
                    FeatureSpec(
                        "Sketch1",
                        "ProfileFeature",
                        sketch=SketchSpec(raw_status=DEFINED, text_segments=0),
                    ),
                ),
            ),
        ),
    )


def branch(assembly: str, shared_instance: str, first_copy: int) -> AssemblySpec:
    """One of the two parents of `MR-40004`, with its own four copies of `MR-40010`."""
    return AssemblySpec(
        name=assembly,
        folder=JOB_FOLDER,
        properties=card(PROFILE),
        components=(
            ComponentSpec(
                name=shared_instance,
                document=SHARED_ASSEMBLY,
                parent=f"{assembly}-1",
                is_fixed=True,
                constrained_status_raw=DEFINED,
            ),
            *(
                ComponentSpec(
                    name=f"{MANY_PART}-{first_copy + number}",
                    document=MANY_PART,
                    parent=f"{assembly}-1",
                    constrained_status_raw=DEFINED,
                )
                for number in range(COPIES)
            ),
        ),
    )


def build() -> EvidencePackage:
    return standards_package(
        profile=PROFILE,
        documents=(
            AssemblySpec(
                name=ROOT_ASSEMBLY,
                folder=JOB_FOLDER,
                properties=card(PROFILE),
                components=(
                    ComponentSpec(
                        name=f"{LEFT_ASSEMBLY}-1",
                        document=LEFT_ASSEMBLY,
                        is_fixed=True,
                        constrained_status_raw=DEFINED,
                    ),
                    ComponentSpec(
                        name=f"{RIGHT_ASSEMBLY}-1",
                        document=RIGHT_ASSEMBLY,
                        constrained_status_raw=DEFINED,
                    ),
                ),
                mates=(
                    MateSpec(
                        entities=(
                            MateEntitySpec(f"{LEFT_ASSEMBLY}-1", "swSelDATUMPLANES"),
                            MateEntitySpec(f"{RIGHT_ASSEMBLY}-1", "swSelDATUMPLANES"),
                        )
                    ),
                ),
            ),
            branch(LEFT_ASSEMBLY, f"{SHARED_ASSEMBLY}-1", first_copy=1),
            branch(RIGHT_ASSEMBLY, f"{SHARED_ASSEMBLY}-2", first_copy=COPIES + 1),
            AssemblySpec(
                name=SHARED_ASSEMBLY,
                folder=JOB_FOLDER,
                properties=card(PROFILE, blank=(0,), absent=(2,)),
                is_exploded=True,
                rebuild_error_count=1,
                components=(
                    ComponentSpec(
                        name=f"{PLAIN_PART}-1",
                        document=PLAIN_PART,
                        parent=f"{SHARED_ASSEMBLY}-1",
                        is_fixed=True,
                        constrained_status_raw=DEFINED,
                    ),
                ),
            ),
            part(MANY_PART, material=None),
            part(PLAIN_PART),
        ),
    )


def main() -> None:
    write_fixture(FIXTURE_DIR, build())


if __name__ == "__main__":
    main()
