"""Generate `package.json` and `case.json` for the rms-equations fixture (T043).

Run once, from `reviewer/`, and commit what it writes:

    uv run python tests/golden/fixtures/rms-equations/generate_package.py

Like the rms-part generator, this is a script rather than a hand-built JSON file because
`tests/support/features.py` already knows how a package lays out documents, instances and
equation rows, and a second hand-maintained copy of that knowledge would drift from it
(constitution Principle V, DRY). What lives here is the *intent*: one part per answer the
two equation rules can give, so the baseline pins all four at once.

- **housing** (`doc:2`) passes both rules: two global variables and two dimensions driven
  from them.
- **cover** (`doc:3`) has an equation manager that was read and holds nothing. That is an
  answer, not a gap: it fails `rms.params.global_variables_present` and warns on
  `rms.params.dimensions_driven_by_equations`.
- **bracket** (`doc:4`) carries the `equations` gap. Its rows are the ones the extractor
  did manage to read, and they are not evidence of what the manager holds, so both rules
  are unresolved rather than passing on a partial read (constitution Principle I).
- **plate** (`doc:5`) is the half-read row: one global, and one row whose
  `GlobalVariable(i)` threw. Both rules are unresolved - a pass here would be asserted
  over a row nobody read - and the reason names the row.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

FIXTURE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(FIXTURE_DIR.parents[3]))

from tests.support.features import (  # noqa: E402
    AssemblySpec,
    PartSpec,
    equation,
    feature,
    folder,
    rms_package,
    sketch_feature,
)

from swreview.ir.loader import save_package  # noqa: E402
from swreview.ir.models import EvidencePackage, Gap  # noqa: E402

CASE_CALLABLE = "swreview.checks.golden_rms:equations_case"

GAP_DOCUMENT = "doc:4"
"""The document whose equation manager could not be read."""


def tree(prefix: str) -> tuple:
    """A minimal compliant Core group, so each part is a part and not a bare document.

    The equation rules read `equations[]` and never the tree; what the tree has to do
    here is only keep `tree_not_read` from reporting these documents as never opened,
    which is a different unresolved reason and has its own fixture (rms-part).
    """
    return (
        folder(
            "3-Core",
            sketch_feature(f"{prefix}-Sketch1", consumers=(f"{prefix}-Boss-Extrude1",)),
            feature(
                f"{prefix}-Boss-Extrude1", "Extrusion", parent_names=(f"{prefix}-Sketch1",)
            ),
        ),
    )


def housing() -> PartSpec:
    """Two globals, two dimensions driven from them: both rules pass."""
    return PartSpec(
        document_id="doc:2",
        name="housing",
        features=tree("housing"),
        equations=(
            equation('"thickness" = 3mm', is_global=True, value=0.003),
            equation('"depth" = 20mm', is_global=True, value=0.02),
            equation('"D1@housing-Sketch1" = "thickness" * 2', value=0.006),
            equation('"D2@housing-Sketch1" = "depth"', value=0.02),
        ),
    )


def cover() -> PartSpec:
    """An equation manager that holds nothing: one fail and one warn."""
    return PartSpec(document_id="doc:3", name="cover", features=tree("cover"))


def bracket() -> PartSpec:
    """Rows plus the `equations` gap: unresolved, however global the rows that were read."""
    return PartSpec(
        document_id=GAP_DOCUMENT,
        name="bracket",
        features=tree("bracket"),
        equations=(equation('"width" = 40mm', is_global=True, value=0.04),),
    )


def plate() -> PartSpec:
    """One readable global and one row whose `GlobalVariable(i)` threw: unresolved."""
    return PartSpec(
        document_id="doc:5",
        name="plate",
        features=tree("plate"),
        equations=(
            equation('"pitch" = 12mm', is_global=True, value=0.012),
            equation('"D1@plate-Sketch1" = "pitch"', is_global=None, value=0.012),
        ),
    )


def build() -> EvidencePackage:
    return rms_package(
        parts=[housing(), cover(), bracket(), plate()],
        assembly=AssemblySpec(document_id="doc:1", name="rms-equations-assy"),
        gaps=[
            Gap(
                kind="not_extracted",
                entity_kind="equations",
                entity_id=GAP_DOCUMENT,
                reason="The equation manager of bracket.SLDPRT was not read.",
                error=None,
            )
        ],
    )


def main() -> None:
    save_package(build(), FIXTURE_DIR)
    case = {"callable": CASE_CALLABLE}
    (FIXTURE_DIR / "case.json").write_text(json.dumps(case, indent=2) + "\n", encoding="utf-8")
    print(f"wrote package.json and case.json in {FIXTURE_DIR}")


if __name__ == "__main__":
    main()
