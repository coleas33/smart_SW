"""Every part has a believable mass and a material (feature 010 US6, FR-016 to FR-018).

`contracts/mass-material.md` is normative. Three checks over the documents the component
tree reaches, each once, with no argument a model chooses:

- **`mass.material_assigned`**: a part passes with a material, or with its mass override
  read as true; fails with neither when the override was read as false; and is unresolved
  when it has no material and the override was not read. A rule with no calculation, so its
  passes are counted in one `checked` item rather than recorded as findings (research R2.21).
- **`mass.density`**: mass over volume against the range of the part's material class
  (`material_classes.yaml`, the one classifier engagement uses too). Outside the range is
  demonstrated with both numbers and the class row - saying so when the density is within
  2 percent of SOLIDWORKS' no-material 1000 kg/m3, whatever the material field reads. A pass
  is a finding with its calculation. A part whose mass is overridden gets no verdict: its
  mass is not the geometry's.
- **`mass.assembly_override`**: an assembly whose override was read as true is suspected, for
  the engineer to confirm; with the override unread, a mass that is not the sum of its read
  children, or a round number of grams while a child was never read, is suspected.

What could not be read - unread components, body gaps, parts with no class range or no
volume - is counted in one skipped `mass.coverage` item, never forgotten (FR-018). The
standards family's `material_assigned` is a release rule and is not touched.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from swreview.checks.material_classes import MaterialClasses, load_material_classes
from swreview.checks.result import CheckResult, unresolved
from swreview.findings import Calculation
from swreview.ir.models import ComponentInstance, Document, EvidencePackage
from swreview.report.session import CoverageItem, CoverageScope

__all__ = [
    "CHECK_ASSEMBLY_OVERRIDE",
    "CHECK_COVERAGE",
    "CHECK_DENSITY",
    "CHECK_MATERIAL_ASSIGNED",
    "DEFAULT_TOLERANCE",
    "DocumentResult",
    "MassChecks",
    "SUM_TOLERANCE",
    "run_mass_checks",
]

CHECK_MATERIAL_ASSIGNED = "mass.material_assigned"
CHECK_DENSITY = "mass.density"
CHECK_ASSEMBLY_OVERRIDE = "mass.assembly_override"
CHECK_COVERAGE = "mass.coverage"
FUNCTION = "swreview.checks.mass.run_mass_checks"
FUNCTION_VERSION = "1"

DEFAULT_TOLERANCE = 0.02
"""A density within 2 percent of the no-material default reads as that default (R2.16)."""

SUM_TOLERANCE = 0.001
"""An assembly mass within 0.1 percent of its children's sum is their sum."""

ROUND_GRAMS_FROM_KG = 0.1
"""A whole number of grams from 100 g up reads as typed rather than summed."""

DENSITY_PLACES = 3


@dataclass(frozen=True)
class DocumentResult:
    """One check's verdict on one document, and what the finding binds to."""

    result: CheckResult
    document_id: str
    component_ids: tuple[str, ...]
    """The document's instances; empty for the root assembly, which has none."""

    @property
    def document_ids(self) -> tuple[str, ...]:
        """Binds a finding to a document with no component instance (the root)."""
        return () if self.component_ids else (self.document_id,)


@dataclass(frozen=True)
class MassChecks:
    """The three checks' findings, their counted passes, and what was not read."""

    findings: tuple[DocumentResult, ...]
    checked: tuple[CoverageItem, ...]
    skipped: tuple[CoverageItem, ...]
    documents: int


def _number(value: float, places: int = 6) -> str:
    return repr(round(value, places))


def _plural(count: int, noun: str, plural: str | None = None) -> str:
    return f"{count} {noun if count == 1 else (plural or noun + 's')}"


class _Tree:
    """The documents the component tree reaches, and what was read of them."""

    def __init__(self, package: EvidencePackage) -> None:
        self.package = package
        self.documents = {item.document_id: item for item in package.documents}
        self.not_opened = {
            gap.entity_id
            for gap in package.gaps
            if gap.entity_kind == "document" and gap.kind == "not_extracted"
        }
        self.instances: dict[str, list[ComponentInstance]] = {}
        for component in sorted(package.components, key=lambda item: item.id):
            self.instances.setdefault(component.document_id, []).append(component)
        root = package.design.root_assembly_document_id
        reached = {root, *self.instances}
        self.reached = [self.documents[key] for key in sorted(reached) if key in self.documents]

    def read(self, component: ComponentInstance) -> bool:
        return (
            component.suppression == "resolved"
            and component.document_id not in self.not_opened
        )

    def opened(self, document: Document) -> bool:
        """The document was opened: not flagged unread, and the root or some instance read."""
        if document.document_id in self.not_opened:
            return False
        if document.document_id == self.package.design.root_assembly_document_id:
            return True
        return any(self.read(item) for item in self.instances.get(document.document_id, ()))

    def component_ids(self, document: Document) -> tuple[str, ...]:
        return tuple(item.id for item in self.instances.get(document.document_id, ()))

    def children(self, document: Document) -> list[ComponentInstance]:
        """The direct children of the document's first instance (or of the root)."""
        if document.document_id == self.package.design.root_assembly_document_id:
            parent = None
        else:
            owners = self.instances.get(document.document_id)
            if not owners:
                return []
            parent = owners[0].id
        return [item for item in self.package.components if item.parent_id == parent]


def _override_gap(package: EvidencePackage, document_id: str) -> str:
    reasons = [
        gap.reason
        for gap in package.gaps
        if gap.entity_kind == "mass_override" and gap.entity_id == document_id
    ]
    return "; ".join(reasons) if reasons else "no override value and no gap were recorded"


def _material_assigned(tree: _Tree, document: Document) -> CheckResult | None:
    """`None` for a pass, else the finding."""
    if document.material or document.mass_overridden is True:
        return None
    requirement = (
        "every part carries a material, or its mass is deliberately overridden, so its mass "
        "and centre of mass are not SOLIDWORKS' no-material default"
    )
    action = (
        f"Assign a material to {document.file_name}, or override its mass deliberately, then "
        "re-run the review."
    )
    if document.mass_overridden is None:
        return unresolved(
            CHECK_MATERIAL_ASSIGNED,
            f"whether the mass of {document.file_name} is overridden (it has no material, and "
            f"the override read left a mass_override gap: "
            f"{_override_gap(tree.package, document.document_id)})",
            [document.document_id],
            requirement=requirement,
            recommended_action=action,
        )
    return CheckResult(
        check=CHECK_MATERIAL_ASSIGNED,
        status="demonstrated",
        severity="medium",
        observed=(
            f"{document.file_name} has no material and its mass is not overridden: its mass is "
            "SOLIDWORKS' no-material default"
        ),
        requirement=requirement,
        inputs=[document.document_id],
        calculation=None,
        coverage_limits=[],
        recommended_action=action,
    )


def _density(
    document: Document, classes: MaterialClasses
) -> CheckResult | None:
    """The density verdict, or `None` when the part has no class range or no volume."""
    item = classes.for_material(document.material)
    mass = document.mass
    if item.density_kg_m3 is None or mass is None or mass.volume_m3 <= 0.0:
        return None
    density = round(mass.mass_kg / mass.volume_m3, DENSITY_PLACES)
    low, high = item.density_kg_m3
    default = classes.no_material_density_kg_m3
    at_default = abs(density - default) <= DEFAULT_TOLERANCE * default
    inside = low <= density <= high
    weighs = (
        f"{document.file_name} weighs {_number(mass.mass_kg)} kg for "
        f"{_number(mass.volume_m3 * 1e9)} mm3: {_number(density, DENSITY_PLACES)} kg/m3"
    )
    row = f"{_number(low)} to {_number(high)} kg/m3 of its material class {item.name}"
    if inside:
        status, severity = "checked_within_scope", "info"
        observed = f"{weighs}, within the {row} ({document.material})"
        action = ""
    else:
        status, severity = "demonstrated", "medium"
        observed = f"{weighs}, outside the {row} ({document.material})"
        if at_default:
            observed += (
                f"; the density is SOLIDWORKS' no-material default of {_number(default)} kg/m3, "
                "so the material is likely not applied to the body"
            )
        action = (
            f"Check the material applied to {document.file_name} and its bodies, or override "
            "its mass deliberately."
        )
    return CheckResult(
        check=CHECK_DENSITY,
        status=status,  # type: ignore[arg-type]
        severity=severity,  # type: ignore[arg-type]
        observed=observed,
        requirement=(
            "a part's density, mass over volume, lies in the range of its material's class and "
            "is not the no-material default"
        ),
        inputs=[document.document_id],
        calculation=Calculation(
            model=CHECK_DENSITY,
            inputs={
                "mass": f"{_number(mass.mass_kg)} kg",
                "volume": f"{_number(mass.volume_m3 * 1e9)} mm3",
                "configuration": mass.configuration,
                "material": document.material or "",
                "material_class": item.name,
                "class_source": item.source,
                "no_material_density_source": classes.no_material_density_source,
            },
            assumptions=[
                "density = mass / volume, both as SOLIDWORKS reported them for the configuration",
                f"within {DEFAULT_TOLERANCE * 100:g} percent of {_number(default)} kg/m3 reads "
                "as the no-material default",
                f"densities rounded to 1e-{DENSITY_PLACES} kg/m3",
            ],
            excluded_effects=[
                "a material assigned per body or per configuration other than the one read",
                "hollow or lattice geometry whose mass SOLIDWORKS computes from the solid",
            ],
            result={
                "density_kg_m3": density,
                "range_low_kg_m3": low,
                "range_high_kg_m3": high,
                "within_range": inside,
                "no_material_default": at_default,
            },
            units_out="kg/m3",
            function=FUNCTION,
            function_version=FUNCTION_VERSION,
        ),
        coverage_limits=[],
        recommended_action=action,
    )


def _assembly_override(tree: _Tree, document: Document) -> CheckResult | None:
    mass = document.mass
    if document.mass_overridden is False or mass is None:
        return None
    requirement = "an assembly's mass is its components', unless an override is deliberate"
    action = (
        f"Confirm the mass of {document.file_name} is intended, or remove the override so it "
        "is its components' sum."
    )

    def suspected(observed: str, result: dict[str, bool | str | float]) -> CheckResult:
        return CheckResult(
            check=CHECK_ASSEMBLY_OVERRIDE,
            status="suspected",
            severity="low",
            observed=observed,
            requirement=requirement,
            inputs=[document.document_id],
            calculation=Calculation(
                model=CHECK_ASSEMBLY_OVERRIDE,
                inputs={
                    "assembly_mass": f"{_number(mass.mass_kg)} kg",
                    "mass_overridden": str(document.mass_overridden),
                },
                assumptions=[
                    "suppressed components are left out of an assembly's mass",
                    "a component that was read with no mass (a surface body) weighs nothing",
                    f"a mass within {SUM_TOLERANCE * 100:g} percent of the sum is the sum",
                ],
                excluded_effects=["mass overrides inside sub-assemblies below the children"],
                result=result,
                units_out="kg",
                function=FUNCTION,
                function_version=FUNCTION_VERSION,
            ),
            coverage_limits=[],
            recommended_action=action,
        )

    if document.mass_overridden is True:
        return suspected(
            f"The assembly mass of {document.file_name} is overridden; confirm "
            f"{_number(mass.mass_kg)} kg is intended",
            {"overridden": True},
        )

    children = tree.children(document)
    considered = [item for item in children if item.suppression != "suppressed"]
    unread = [item for item in considered if not tree.read(item)]
    if not unread:
        total = sum(
            tree.documents[item.document_id].mass.mass_kg  # type: ignore[union-attr]
            if tree.documents[item.document_id].mass is not None
            else 0.0
            for item in considered
        )
        if abs(mass.mass_kg - total) <= SUM_TOLERANCE * total:
            return None
        return suspected(
            f"The assembly mass of {document.file_name} is {_number(mass.mass_kg)} kg, but its "
            f"{_plural(len(considered), 'read child', 'read children')} weigh "
            f"{_number(total)} kg together; it may be overridden",
            {"children_sum_kg": round(total, 9), "assembly_mass_kg": mass.mass_kg},
        )
    grams = mass.mass_kg * 1000.0
    if mass.mass_kg < ROUND_GRAMS_FROM_KG or not math.isclose(grams, round(grams), abs_tol=1e-6):
        return None
    never_read = [item for item in children if not tree.read(item)]
    return suspected(
        f"The assembly mass of {document.file_name} is a round {_number(mass.mass_kg)} kg while "
        f"{_plural(len(never_read), 'child', 'children')} "
        f"{'was' if len(never_read) == 1 else 'were'} never read; it may be overridden",
        {"assembly_mass_kg": mass.mass_kg, "unread_children": float(len(never_read))},
    )


def _coverage(
    tree: _Tree, classless: Sequence[Document], unread: Sequence[ComponentInstance]
) -> CoverageItem | None:
    lightweight = sum(1 for item in unread if item.suppression == "lightweight")
    suppressed = sum(1 for item in unread if item.suppression == "suppressed")
    not_opened = len(unread) - lightweight - suppressed
    bodies = sum(1 for gap in tree.package.gaps if gap.entity_kind == "body")
    if not unread and not bodies and not classless:
        return None
    count = len(unread)
    return CoverageItem(
        check=CHECK_COVERAGE,
        scope=CoverageScope(
            component_ids=sorted(
                {item.id for item in unread}
                | {cid for document in classless for cid in tree.component_ids(document)}
            )
        ),
        reason=(
            f"{_plural(count, 'component')} {'was' if count == 1 else 'were'} not read "
            f"(lightweight {lightweight}, suppressed {suppressed}, not opened {not_opened}); "
            f"{_plural(bodies, 'body', 'bodies')} could not be read; "
            f"{_plural(len(classless), 'part')} {'has' if len(classless) == 1 else 'have'} no "
            "material class with a density range or no volume"
        ),
        error=None,
    )


def run_mass_checks(
    package: EvidencePackage, classes: MaterialClasses | None = None
) -> MassChecks:
    """The three mass checks over every document the tree reaches (`contracts/code-first.md`
    section 6): findings with what they bind to, the counted passes, the coverage count."""
    classes = classes or load_material_classes()
    tree = _Tree(package)
    findings: list[DocumentResult] = []
    passed: list[Document] = []
    classless: list[Document] = []
    for document in tree.reached:
        if not tree.opened(document):
            continue
        components = tree.component_ids(document)
        if document.kind == "part":
            assigned = _material_assigned(tree, document)
            if assigned is None:
                passed.append(document)
            else:
                findings.append(DocumentResult(assigned, document.document_id, components))
            if document.mass_overridden is True:
                continue
            density = _density(document, classes)
            if density is None:
                classless.append(document)
            else:
                findings.append(DocumentResult(density, document.document_id, components))
        elif document.kind == "assembly":
            override = _assembly_override(tree, document)
            if override is not None:
                findings.append(DocumentResult(override, document.document_id, components))

    checked = []
    if passed:
        checked.append(
            CoverageItem(
                check=CHECK_MATERIAL_ASSIGNED,
                scope=CoverageScope(
                    component_ids=sorted(
                        {cid for document in passed for cid in tree.component_ids(document)}
                    )
                ),
                reason=(
                    f"{_plural(len(passed), 'part')} "
                    f"{'has' if len(passed) == 1 else 'have'} a material or a deliberate mass "
                    "override"
                ),
                error=None,
            )
        )
    unread = [item for item in package.components if not tree.read(item)]
    coverage = _coverage(tree, classless, sorted(unread, key=lambda item: item.id))
    return MassChecks(
        findings=tuple(findings),
        checked=tuple(checked),
        skipped=() if coverage is None else (coverage,),
        documents=len(tree.reached),
    )
