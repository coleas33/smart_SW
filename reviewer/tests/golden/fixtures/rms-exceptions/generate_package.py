"""Generate `package.json`, `exceptions.json` and `case.json` for the rms-exceptions fixture.

Run once, from `reviewer/`, and commit what it writes:

    uv run python tests/golden/fixtures/rms-exceptions/generate_package.py

A script rather than hand-written JSON for the reason the rms-part generator gives: the
layout of a feature tree - ids in traversal order, `folder_id`, `depth`, resolved child/
parent/consumer ids, one `persist_ref` per row - is what `tests/support/features.py`
already knows, and a hand-maintained second copy would drift from it (constitution
Principle V, DRY). The digests are computed here by `swreview.exceptions.fingerprint`,
through `ExceptionStore.accept`, so the fixture is honest: neither exception carries a
hash that was typed out.

Two parts, and one exception each. This fixture exists to pin what the *exception* half of
the report layer does (quickstart Scenario 5), not to seed rules, so each part breaks
exactly one rule and passes the rest:

- **housing** (`doc:2`) puts `Boss-Extrude2` after `Shell1` in Core, which fails
  `rms.core.shell_last`. `EX-001` is accepted against the tree that is in `package.json`,
  so `ExceptionStore.refresh` leaves it `active` and the finding comes back
  `checked_within_scope` with `exception:EX-001` among its coverage limits.
- **cover** (`doc:3`) puts `Fillet1` before `Chamfer1` in Quarantine, which fails
  `rms.quarantine.chamfers_before_fillets`. `EX-002` is accepted against the *earlier*
  revision of that part - `cover(second_hole=False)`, before `Hole2` was added to Detail -
  so the feature-tree digest it stores is not the digest of the tree in `package.json`.
  `refresh` moves it to `needs_review` and the finding stands, carrying the re-review
  marker. Nothing about the Quarantine condition itself changed: that is the point, an
  exception is bound to the tree it was accepted for and not to the condition alone.

`exceptions.json` therefore ships both records as `active`, which is the state an engineer
would actually have on disk - the file is not rewritten when a model changes, and the
reviewer refreshes it in memory on every run without writing back. `case.json` carries the
same two records inline, because the golden harness hands the adapter a loaded package and
no directory to find the file in.
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
    FeatureSpec,
    PartSpec,
    feature,
    fillet_feature,
    folder,
    rms_package,
    sketch_feature,
)
from tests.unit.test_tools_rms_checks import AcceptedFinding  # noqa: E402

from swreview.exceptions import EXCEPTIONS_FILE_NAME, ExceptionStore  # noqa: E402
from swreview.ir.loader import save_package  # noqa: E402
from swreview.ir.models import EvidencePackage  # noqa: E402

CASE_CALLABLE = "swreview.checks.golden_rms:part_case"

ACTIVE_RULE = "rms.core.shell_last"
ACTIVE_INSTANCE = "cmp:0002"
"""The housing's only instance: what `EX-001` is bound to, and what the report layer looks
an exception up by when it grades `doc:2`."""

STALE_RULE = "rms.quarantine.chamfers_before_fillets"
STALE_INSTANCE = "cmp:0003"
"""The cover's only instance: what `EX-002` is bound to."""

ACCEPTED_AT = datetime(2026, 9, 15, 9, 15, tzinfo=UTC)


def housing() -> PartSpec:
    """Compliant but for the shell: `Boss-Extrude2` sits in Core after `Shell1`."""
    return PartSpec(
        document_id="doc:2",
        name="housing",
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
                feature("Boss-Extrude2", "Extrusion"),
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


def cover(*, second_hole: bool) -> PartSpec:
    """Compliant but for Quarantine, which opens with `Fillet1` and only then `Chamfer1`.

    `second_hole` is the single difference between the revision `EX-002` was accepted
    against (`False`) and the revision in `package.json` (`True`): `Hole2` was added to the
    trailing hole block of Detail afterwards. It leaves every rule's verdict where it was -
    holes still trail Detail, and the Quarantine order is untouched - and it changes the
    feature-tree digest, which is exactly the case `refresh` exists for.
    """
    detail: tuple[FeatureSpec, ...] = (
        sketch_feature("Sketch3", consumers=("Cut-Extrude1",)),
        feature("Cut-Extrude1", "Cut", parent_names=("Sketch3",)),
        feature("Hole1", "HoleWzd"),
    )
    if second_hole:
        detail = (*detail, feature("Hole2", "HoleWzd"))
    return PartSpec(
        document_id="doc:3",
        name="cover",
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
            folder("4-Detail", *detail),
            folder(
                "5-Modify",
                feature("Draft1", "Draft"),
                feature("LPattern1", "LPattern"),
            ),
            folder(
                "6-Quarantine",
                fillet_feature("Fillet1", radius_m=0.004),
                feature("Chamfer1", "Chamfer"),
            ),
        ),
    )


def build(*, second_hole: bool) -> EvidencePackage:
    """The package; `second_hole=False` is the earlier revision `EX-002` was accepted for.

    Both revisions carry the same documents and the same component instances, so an
    exception accepted against either is bound to the same `(persist_ref, scope)` pairs and
    the digest is the only thing that can move.
    """
    return rms_package(
        parts=[housing(), cover(second_hole=second_hole)],
        assembly=AssemblySpec(document_id="doc:1", name="rms-exceptions-assy"),
    )


def main() -> None:
    package = build(second_hole=True)
    save_package(package, FIXTURE_DIR)

    store = ExceptionStore(FIXTURE_DIR / EXCEPTIONS_FILE_NAME)
    store.accept(
        AcceptedFinding(
            check=ACTIVE_RULE,
            component_ids=[ACTIVE_INSTANCE],
            configuration=package.design.active_configuration,
        ),
        package,
        by="engineer",
        note="the boss after the shell is a moulding pad the tool needs; accepted as modelled",
        at=ACCEPTED_AT,
    )
    store.accept(
        AcceptedFinding(
            check=STALE_RULE,
            component_ids=[STALE_INSTANCE],
            configuration=package.design.active_configuration,
        ),
        build(second_hole=False),
        by="engineer",
        note="cosmetic fillet kept ahead of the chamfer to match the legacy tool",
        at=ACCEPTED_AT,
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
