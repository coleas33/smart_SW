"""Package classes for lever 4, and the one call that answers "what would we offer?".

Lever 4's rule is decidable from the package before the first turn, so every fixture here
is a package and nothing in this module needs a provider, a key or a network. The two
lever 4 test modules - `test_tool_tiers.py` (selection) and `test_tool_tiers_withheld.py`
(the withheld path) - share these builders rather than each growing their own.

Byte figures live in `tests/unit/test_tool_payload.py` and are imported from there, never
restated here: two figures in this feature's package had already diverged by being typed
in twice.
"""

from __future__ import annotations

from typing import Any

from swreview.agent.settings import EfficiencySettings
from swreview.ir.models import EvidencePackage
from swreview.tools.context import context_for
from swreview.tools.registry import ToolDispatch, ToolRegistry
from tests.support.features import AssemblySpec, MateSpec, PartSpec, feature, rms_package

ON = EfficiencySettings(tool_tiers=True)
OFF = EfficiencySettings()
"""The lever under test, and the default every shipped run still has."""


def _part(name: str = "housing", document_id: str = "doc:2") -> PartSpec:
    return PartSpec(
        document_id=document_id,
        name=name,
        features=[feature("Boss-Extrude1", "Extrusion")],
    )


def full_assembly_with_tree() -> EvidencePackage:
    """A full dump of an assembly whose part tree came with it: every RMS rule is gradable."""
    return rms_package(parts=[_part()], assembly=AssemblySpec())


def full_assembly_without_tree() -> EvidencePackage:
    """A full dump with no part documents, so `features[]` is empty.

    This is the shape of an assembly reviewed from exported files, and the shape of the
    `cover-blind-tap` golden package. **Not** "no rule is gradable": the part and the
    equation rules have no tree to read, which is the tier's rule, but the four
    `rms.assembly.*` rules read the mates and the component instances and would grade this
    package. `assembly_without_tree_with_a_gradable_defect` is that fact as a fixture.
    """
    return rms_package(parts=[], assembly=AssemblySpec())


def assembly_without_tree_with_a_gradable_defect() -> EvidencePackage:
    """`features[]` empty, and one mate the assembly rules demonstrate a defect on.

    The tier withholds `check_rms_assembly` with the five feature-tree readers, so this
    finding is what the lever gives up for its bytes. The fixture exists so the sentence
    the withheld tool hands the model cannot claim the assembly rules were ungradable:
    here they are, grading.
    """
    return rms_package(
        parts=[_part("housing", "doc:2"), _part("cover", "doc:3")],
        assembly=AssemblySpec(
            mates=[MateSpec(entities=[("housing-1", "swSelFACES"), ("cover-1", "swSelEDGES")])]
        ),
    ).model_copy(update={"features": []})


def model_check_part_with_tree() -> EvidencePackage:
    """What the Model check tab dumps for a part: the `model_check` profile, tree included."""
    return as_model_check(rms_package(parts=[_part()]))


def part_only_without_tree() -> EvidencePackage:
    """A part document whose feature tree was never read: the rule fires on a part too."""
    return rms_package(parts=[_part()]).model_copy(update={"features": []})


def as_model_check(package: EvidencePackage) -> EvidencePackage:
    """The same package with `extractor.profile` set to `model_check`."""
    return package.model_copy(
        update={"extractor": package.extractor.model_copy(update={"profile": "model_check"})}
    )


def dispatch_for(
    package: EvidencePackage,
    *,
    efficiency: EfficiencySettings = OFF,
    bridge: Any | None = None,
) -> ToolDispatch:
    """The dispatch `start_review` would build for this package, these levers and this bridge.

    `bridge` is a sentinel rather than a client: `functions_for` only asks whether one is
    wired, and nothing here calls a bridge tool.
    """
    context = context_for(package)
    context.bridge = bridge
    return ToolRegistry().dispatch(context, efficiency=efficiency)


def offered(
    package: EvidencePackage,
    *,
    efficiency: EfficiencySettings = OFF,
    bridge: Any | None = None,
) -> list[str]:
    """The tool names this run puts on the wire, in the order an adapter encodes them."""
    return [tool.name for tool in dispatch_for(package, efficiency=efficiency, bridge=bridge)]
