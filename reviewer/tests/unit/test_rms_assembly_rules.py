"""Unit tests for the four assembly-scope RMS rule evaluators and `MateGraph` (T032).

`specs/003-resilient-modeling/contracts/rules.md` ("Assembly scope") is normative: one
test class per rule, covering every row of its line - the pass, the fail or warn, every
skip condition with the reason the contract words, and every unresolved condition - plus
the two cross-cutting paragraphs that decide what an assembly rule may look at at all:

- **the root assembly document only.** `Mate` carries no owning document and the extractor
  reads the root's mates, so every `RuleResult` an assembly rule emits names
  `design.root_assembly_document_id`. A subassembly document is never a subject document;
  it surfaces through the coverage-only rule `rms.assembly.subassemblies`, which
  `checks/rms/report.py` writes as an undispatched item and which is asserted here only to
  be undispatched.
- **a missing input is unresolved for that subject, never a pass and never a fail**
  (constitution Principle I): an entity kind in neither table list, a mate whose entity
  list the dumper could only partly read, a constrained status that was never read, a mate
  whose suppression was not readable, a component the mate graph cannot reach, a component
  whose Toolbox identity was not readable.

Two things are asserted everywhere rather than once: one `RuleResult` per outcome (so a
rule cannot quietly emit a finding per mate), and the observed text of every finding names
the subject an engineer would search for.
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from swreview.checks.rms import RULES, coverage_only, evaluable
from swreview.checks.rms.assembly import MateGraph, evaluate_assembly
from swreview.checks.rms.results import RuleResult
from swreview.checks.rms_types import load_table
from swreview.ir.models import EvidencePackage, Gap
from tests.support.features import (
    AssemblySpec,
    InstanceSpec,
    MateSpec,
    PartSpec,
    SubassemblySpec,
    rms_package,
    toolbox_identity_gap,
)

TABLE = load_table()
ROOT = "doc:1"
LIMIT = TABLE.assembly.mate_chain_depth_limit

PLANE = "swSelDATUMPLANES"
AXIS = "swSelDATUMAXES"
FACE = "swSelFACES"
EDGE = "swSelEDGES"
VERTEX = "swSelVERTICES"
SKETCH_KIND = "swSelSKETCHSEGS"
UNKNOWN_KIND = "unknown(37)"

ASSEMBLY_RULE_IDS = tuple(rule.id for rule in evaluable() if rule.scope == "assembly")
DATA_GAP_RULE_IDS = tuple(rule.id for rule in coverage_only() if rule.scope == "assembly")


def test_the_kinds_these_tests_use_are_the_kinds_the_table_lists() -> None:
    """The fixtures below are only meaningful while the table still lists these kinds."""
    assert PLANE in TABLE.assembly.reference_entity_kinds
    assert AXIS in TABLE.assembly.reference_entity_kinds
    assert TABLE.assembly.geometry_entity_kinds == (FACE, EDGE, VERTEX)
    assert SKETCH_KIND not in TABLE.assembly.reference_entity_kinds
    assert SKETCH_KIND not in TABLE.assembly.geometry_entity_kinds


# --- helpers ----------------------------------------------------------------------


def part(document_id: str, name: str, *instances: InstanceSpec) -> PartSpec:
    """One part document and the instances of it the root assembly holds."""
    return PartSpec(
        document_id=document_id, name=name, instances=list(instances) if instances else None
    )


def mate(*names: str, kind: str = PLANE, **kwargs: object) -> MateSpec:
    """One mate joining `names`, every entity of the same kind."""
    return MateSpec(entities=[(name, kind) for name in names], **kwargs)  # type: ignore[arg-type]


def assembly_package(
    *,
    documents: Sequence[PartSpec] = (),
    mates: Sequence[MateSpec] = (),
    subassembly: SubassemblySpec | None = None,
    gaps: Sequence[Gap] = (),
) -> EvidencePackage:
    """A root assembly `doc:1` over `documents`, with `mates` and an optional subassembly."""
    return rms_package(
        parts=list(documents),
        assembly=AssemblySpec(
            document_id=ROOT, mates=list(mates), subassembly=subassembly
        ),
        gaps=list(gaps),
    )


def chain(*instances: InstanceSpec) -> Sequence[PartSpec]:
    """One part document whose instances are the components the chain tests mate."""
    return [part("doc:2", "link", *instances)]


def mate_gap(mate_id: str, reason: str) -> Gap:
    """One of the other two `mate`-kind gaps `MateDumper` keys to a mate: no persistent
    reference, and a distance or angle value it did not read. Neither says anything about
    the entity list, so neither may make a mate unresolved."""
    return Gap(
        kind="not_extracted",
        entity_kind="mate",
        entity_id=mate_id,
        reason=reason,
        error=None,
    )


def run(rule_id: str, package: EvidencePackage) -> dict[str, RuleResult]:
    """Dispatch every assembly rule, keep `rule_id`'s results, keyed by outcome.

    Going through `evaluate_assembly` rather than the bound function pins, in every test,
    that the rule is dispatched, that it is dispatched once, and that it reports on the
    root assembly document.
    """
    keyed: dict[str, RuleResult] = {}
    for result in evaluate_assembly(package, TABLE):
        assert result.document_id == ROOT, f"{result.rule_id} reported on {result.document_id}"
        if result.rule_id != rule_id:
            continue
        assert result.outcome not in keyed, (
            f"{rule_id} returned two {result.outcome} results for one document"
        )
        keyed[result.outcome] = result
    return keyed


def labels(package: EvidencePackage, result: RuleResult) -> list[str]:
    """The subjects of a result as an engineer reads them: a component's full instance
    path, a mate's id (the IR carries no mate name)."""
    by_id: dict[str, str] = {row.id: row.full_path for row in package.components}
    by_id.update({row.id: row.id for row in package.mates})
    return [by_id[subject] for subject in result.subjects]


def component_id(package: EvidencePackage, full_path: str) -> str:
    return next(row.id for row in package.components if row.full_path == full_path)


# --- rms.assembly.mates_to_reference_geometry -------------------------------------


class TestMatesToReferenceGeometry:
    RULE = "rms.assembly.mates_to_reference_geometry"

    def build(self, *mates: MateSpec, gaps: Sequence[Gap] = ()) -> EvidencePackage:
        return assembly_package(
            documents=[part("doc:2", "cover", InstanceSpec("cover-1"), InstanceSpec("base-1"))],
            mates=list(mates),
            gaps=gaps,
        )

    def test_no_mates_skips(self) -> None:
        package = assembly_package(documents=[part("doc:2", "cover")])

        keyed = run(self.RULE, package)

        assert list(keyed) == ["skip"]
        assert keyed["skip"].reason == "the root assembly has no mates"

    def test_reference_geometry_passes_and_names_the_mate_and_its_components(self) -> None:
        package = self.build(mate("cover-1", "base-1", kind=PLANE))

        keyed = run(self.RULE, package)

        assert list(keyed) == ["pass"]
        assert labels(package, keyed["pass"]) == ["mate:0001", "cover-1", "base-1"]

    def test_a_mate_of_two_reference_kinds_passes(self) -> None:
        package = self.build(
            MateSpec(entities=[("cover-1", PLANE), ("base-1", AXIS)]),
        )

        keyed = run(self.RULE, package)

        assert list(keyed) == ["pass"]

    @pytest.mark.parametrize("kind", [FACE, EDGE, VERTEX])
    def test_geometry_kinds_fail_and_name_the_mate_and_its_components(self, kind: str) -> None:
        package = self.build(mate("cover-1", "base-1", kind=kind))

        keyed = run(self.RULE, package)

        assert list(keyed) == ["fail"]
        result = keyed["fail"]
        assert labels(package, result) == ["mate:0001", "cover-1", "base-1"]
        assert result.result is not None
        assert result.result.status == "demonstrated"
        assert result.result.severity == "medium"
        assert result.result.requirement == RULES[self.RULE].statement
        assert kind in result.result.observed
        assert "cover-1" in result.result.observed

    def test_one_geometry_entity_is_enough_to_fail_the_mate(self) -> None:
        package = self.build(MateSpec(entities=[("cover-1", PLANE), ("base-1", FACE)]))

        keyed = run(self.RULE, package)

        assert list(keyed) == ["fail"]
        assert FACE in (keyed["fail"].result.observed if keyed["fail"].result else "")

    @pytest.mark.parametrize("kind", [UNKNOWN_KIND, SKETCH_KIND])
    def test_a_kind_in_neither_list_is_unresolved_for_that_mate(self, kind: str) -> None:
        package = self.build(mate("cover-1", "base-1", kind=kind))

        keyed = run(self.RULE, package)

        assert list(keyed) == ["unresolved"]
        result = keyed["unresolved"]
        assert labels(package, result) == ["mate:0001", "cover-1", "base-1"]
        assert result.reason is not None
        assert kind in result.reason

    def test_a_failing_mate_and_an_unreadable_one_land_in_two_buckets(self) -> None:
        package = self.build(
            mate("cover-1", "base-1", kind=FACE),
            mate("cover-1", "base-1", kind=UNKNOWN_KIND),
            mate("cover-1", "base-1", kind=PLANE),
        )

        keyed = run(self.RULE, package)

        assert sorted(keyed) == ["fail", "unresolved"]
        assert labels(package, keyed["fail"])[0] == "mate:0001"
        assert labels(package, keyed["unresolved"])[0] == "mate:0002"

    def test_a_compliant_and_an_unreadable_mate_pass_and_are_unresolved(self) -> None:
        package = self.build(
            mate("cover-1", "base-1", kind=PLANE),
            mate("cover-1", "base-1", kind=SKETCH_KIND),
        )

        keyed = run(self.RULE, package)

        assert sorted(keyed) == ["pass", "unresolved"]
        assert labels(package, keyed["pass"])[0] == "mate:0001"
        assert labels(package, keyed["unresolved"])[0] == "mate:0002"

    def test_a_suppressed_mate_is_still_graded_and_marked_suppressed(self) -> None:
        package = self.build(mate("cover-1", "base-1", kind=FACE, suppressed=True))

        keyed = run(self.RULE, package)

        assert list(keyed) == ["fail"]
        assert keyed["fail"].result is not None
        assert "suppressed" in keyed["fail"].result.observed
        assert any("suppressed" in limit for limit in keyed["fail"].result.coverage_limits)

    def test_a_geometry_kind_outranks_an_unlisted_one_on_the_same_mate(self) -> None:
        """Precedence, pinned: a geometry kind is dispositive evidence of the violation,
        so a mate that also carries an unclassified kind is reported `fail` and is not
        also reported unresolved - there is nothing left to resolve about it."""
        package = self.build(MateSpec(entities=[("cover-1", FACE), ("base-1", UNKNOWN_KIND)]))

        keyed = run(self.RULE, package)

        assert list(keyed) == ["fail"]
        assert FACE in (keyed["fail"].result.observed if keyed["fail"].result else "")

    def test_a_mate_whose_entity_list_is_incomplete_is_unresolved_rather_than_passing(
        self,
    ) -> None:
        """`MateDumper.ReadEntities` drops an entity it could not read, so the entities
        that survived are not the mate's entities: the unread one may be the face that
        violates the rule, and a pass here would be a claim about data nobody saw."""
        package = self.build(mate("cover-1", "base-1", kind=PLANE, entity_gap=True))

        keyed = run(self.RULE, package)

        assert list(keyed) == ["unresolved"]
        result = keyed["unresolved"]
        assert labels(package, result) == ["mate:0001", "cover-1", "base-1"]
        assert result.reason is not None
        assert "entity list incomplete" in result.reason

    def test_an_incomplete_mate_that_already_shows_a_geometry_kind_still_fails(self) -> None:
        """The violation is proven by what was read, so the unread entity changes nothing."""
        package = self.build(mate("cover-1", "base-1", kind=FACE, entity_gap=True))

        keyed = run(self.RULE, package)

        assert list(keyed) == ["fail"]

    def test_an_incomplete_mate_is_also_unresolved_for_its_unlisted_kinds(self) -> None:
        package = self.build(mate("cover-1", "base-1", kind=UNKNOWN_KIND, entity_gap=True))

        keyed = run(self.RULE, package)

        assert list(keyed) == ["unresolved"]
        reason = keyed["unresolved"].reason or ""
        assert "entity list incomplete" in reason
        assert UNKNOWN_KIND in reason

    def test_the_other_mate_gaps_do_not_make_a_mate_unresolved(self) -> None:
        """A distance mate and a mate without a persistent reference carry `mate`-kind
        gaps of their own; neither is about the entity list, so both still pass."""
        package = self.build(
            mate("cover-1", "base-1", kind=PLANE),
            gaps=[
                mate_gap(
                    "mate:0001",
                    "Mate 'Coincident1' has no persistent reference; it cannot be "
                    "navigated to.",
                ),
                mate_gap(
                    "mate:0001",
                    "Mate 'Coincident1' is a distance or angle mate; its value was not "
                    "read, so any check that needs it is unresolved.",
                ),
            ],
        )

        keyed = run(self.RULE, package)

        assert list(keyed) == ["pass"]

    def test_an_entity_gap_on_another_mate_leaves_this_one_passing(self) -> None:
        package = self.build(
            mate("cover-1", "base-1", kind=PLANE),
            mate("cover-1", "base-1", kind=PLANE, entity_gap=True),
        )

        keyed = run(self.RULE, package)

        assert sorted(keyed) == ["pass", "unresolved"]
        assert labels(package, keyed["pass"])[0] == "mate:0001"
        assert labels(package, keyed["unresolved"])[0] == "mate:0002"

    def test_the_finding_inputs_carry_the_subject_evidence_format(self) -> None:
        package = self.build(mate("cover-1", "base-1", kind=FACE))

        keyed = run(self.RULE, package)

        assert keyed["fail"].result is not None
        first = keyed["fail"].result.inputs[0]
        assert first.startswith("mate:0001 ")
        assert "persist_ref=" in first
        assert f"scope={ROOT}" in first


# --- rms.assembly.first_component_fixed -------------------------------------------


class TestFirstComponentFixed:
    RULE = "rms.assembly.first_component_fixed"

    def build(self, *instances: InstanceSpec) -> EvidencePackage:
        return assembly_package(documents=[part("doc:2", "cover", *instances)])

    def test_no_child_components_skips(self) -> None:
        keyed = run(self.RULE, assembly_package())

        assert list(keyed) == ["skip"]
        assert keyed["skip"].reason == "the root assembly has no child components"

    def test_a_fixed_first_component_passes(self) -> None:
        package = self.build(InstanceSpec("cover-1", is_fixed=True), InstanceSpec("base-1"))

        keyed = run(self.RULE, package)

        assert list(keyed) == ["pass"]
        assert labels(package, keyed["pass"]) == ["cover-1"]

    def test_a_fully_constrained_first_component_passes(self) -> None:
        package = self.build(InstanceSpec("cover-1", constrained_status_raw=3))

        keyed = run(self.RULE, package)

        assert list(keyed) == ["pass"]
        assert labels(package, keyed["pass"]) == ["cover-1"]

    @pytest.mark.parametrize(
        ("raw", "status"),
        [(2, "under_defined"), (4, "over_defined"), (5, "solver_error"), (6, "solver_error")],
    )
    def test_an_unfixed_under_over_or_erroring_first_component_fails(
        self, raw: int, status: str
    ) -> None:
        package = self.build(InstanceSpec("cover-1", constrained_status_raw=raw))

        keyed = run(self.RULE, package)

        assert list(keyed) == ["fail"]
        result = keyed["fail"]
        assert labels(package, result) == ["cover-1"]
        assert result.result is not None
        assert result.result.status == "demonstrated"
        assert result.result.severity == "medium"
        assert "cover-1" in result.result.observed
        assert status in result.result.observed

    @pytest.mark.parametrize(
        ("raw", "status"), [(1, "unknown"), (7, "unknown"), (None, "unavailable")]
    )
    def test_an_unreadable_constrained_status_is_unresolved(
        self, raw: int | None, status: str
    ) -> None:
        package = self.build(InstanceSpec("cover-1", constrained_status_raw=raw))

        keyed = run(self.RULE, package)

        assert list(keyed) == ["unresolved"]
        assert labels(package, keyed["unresolved"]) == ["cover-1"]
        assert keyed["unresolved"].reason is not None
        assert status in keyed["unresolved"].reason

    def test_a_later_fixed_component_does_not_rescue_the_first(self) -> None:
        package = self.build(
            InstanceSpec("cover-1", constrained_status_raw=2),
            InstanceSpec("base-1", is_fixed=True),
        )

        keyed = run(self.RULE, package)

        assert list(keyed) == ["fail"]
        assert labels(package, keyed["fail"]) == ["cover-1"]

    def test_the_subject_is_the_first_child_of_the_root_not_of_a_subassembly(self) -> None:
        """A component nested under a subassembly is not a child of `cmp:0001`, however
        early the package lists it."""
        package = assembly_package(
            documents=[
                part(
                    "doc:3",
                    "screw",
                    InstanceSpec("screw-1", parent_name="gearbox-1", is_fixed=True),
                    InstanceSpec("cover-1", constrained_status_raw=2),
                )
            ],
            subassembly=SubassemblySpec(document_id="doc:2", name="gearbox"),
        )

        keyed = run(self.RULE, package)

        assert list(keyed) == ["fail"]
        assert labels(package, keyed["fail"]) == ["cover-1"]


# --- MateGraph and rms.assembly.mate_chain_depth ----------------------------------


class TestMateGraph:
    def test_nodes_are_every_instance_but_the_root_assemblys_own(self) -> None:
        package = assembly_package(
            documents=chain(InstanceSpec("a", is_fixed=True), InstanceSpec("b")),
            subassembly=SubassemblySpec(document_id="doc:3", name="gearbox"),
        )

        graph = MateGraph.of(package)

        assert [node.full_path for node in graph.nodes] == ["a", "b", "gearbox-1"]
        assert "cmp:0001" not in graph.neighbours

    def test_edges_are_the_unsuppressed_mates_and_are_undirected(self) -> None:
        package = assembly_package(
            documents=chain(InstanceSpec("a", is_fixed=True), InstanceSpec("b"), InstanceSpec("c")),
            mates=[mate("a", "b"), mate("b", "c", suppressed=True)],
        )
        first, second, third = (component_id(package, name) for name in ("a", "b", "c"))

        graph = MateGraph.of(package)

        assert graph.neighbours[first] == (second,)
        assert graph.neighbours[second] == (first,)
        assert graph.neighbours[third] == ()

    def test_a_mate_whose_suppression_is_unreadable_is_no_edge_and_is_listed(self) -> None:
        package = assembly_package(
            documents=chain(InstanceSpec("a", is_fixed=True), InstanceSpec("b")),
            mates=[mate("a", "b", suppression_gap=True)],
        )

        graph = MateGraph.of(package)

        assert [row.id for row in graph.unreadable] == ["mate:0001"]
        assert graph.neighbours[component_id(package, "a")] == ()

    def test_roots_are_the_fixed_children_of_the_root_in_package_order(self) -> None:
        package = assembly_package(
            documents=chain(
                InstanceSpec("a"),
                InstanceSpec("b", is_fixed=True),
                InstanceSpec("c", is_fixed=True),
            ),
        )

        graph = MateGraph.of(package)

        assert [node.full_path for node in graph.roots] == ["b", "c"]

    def test_depths_are_breadth_first_from_the_first_fixed_child(self) -> None:
        package = assembly_package(
            documents=chain(
                InstanceSpec("a", is_fixed=True),
                InstanceSpec("b"),
                InstanceSpec("c"),
                InstanceSpec("lonely"),
            ),
            mates=[mate("a", "b"), mate("b", "c"), mate("a", "c")],
        )
        ids = {name: component_id(package, name) for name in ("a", "b", "c", "lonely")}

        depths = MateGraph.of(package).depths()

        assert depths == {ids["a"]: 0, ids["b"]: 1, ids["c"]: 1}

    def test_without_a_fixed_child_there_are_no_depths(self) -> None:
        package = assembly_package(
            documents=chain(InstanceSpec("a"), InstanceSpec("b")), mates=[mate("a", "b")]
        )

        assert MateGraph.of(package).depths() == {}


class TestMateChainDepth:
    RULE = "rms.assembly.mate_chain_depth"

    def links(self, count: int, **first: object) -> Sequence[PartSpec]:
        """`count` instances named `link-1..n`, the first one fixed unless said otherwise."""
        specs = [InstanceSpec(f"link-{number}") for number in range(1, count + 1)]
        specs[0] = InstanceSpec("link-1", **{"is_fixed": True, **first})  # type: ignore[arg-type]
        return chain(*specs)

    def straight_chain(self, count: int) -> Sequence[MateSpec]:
        return [mate(f"link-{number}", f"link-{number + 1}") for number in range(1, count)]

    def test_no_mates_skips(self) -> None:
        package = assembly_package(documents=self.links(2))

        keyed = run(self.RULE, package)

        assert list(keyed) == ["skip"]
        assert keyed["skip"].reason == "the root assembly has no mates"

    def test_a_chain_within_the_limit_passes(self) -> None:
        count = LIMIT + 1
        package = assembly_package(
            documents=self.links(count), mates=self.straight_chain(count)
        )

        keyed = run(self.RULE, package)

        assert list(keyed) == ["pass"]
        assert labels(package, keyed["pass"]) == [f"link-{n}" for n in range(1, count + 1)]

    def test_a_component_beyond_the_limit_warns(self) -> None:
        count = LIMIT + 2
        package = assembly_package(
            documents=self.links(count), mates=self.straight_chain(count)
        )

        keyed = run(self.RULE, package)

        assert list(keyed) == ["warn"]
        result = keyed["warn"]
        assert labels(package, result) == [f"link-{count}"]
        assert result.result is not None
        assert result.result.status == "suspected"
        assert result.result.severity == "low"
        assert f"link-{count}" in result.result.observed
        assert str(LIMIT) in result.result.observed
        assert "link-1" in result.result.observed

    def test_a_second_fixed_child_is_named_in_the_observed_text(self) -> None:
        count = LIMIT + 2
        specs = [InstanceSpec("link-1", is_fixed=True)]
        specs += [InstanceSpec(f"link-{number}") for number in range(2, count + 1)]
        specs.append(InstanceSpec("second-anchor", is_fixed=True))
        package = assembly_package(
            documents=chain(*specs), mates=self.straight_chain(count)
        )

        keyed = run(self.RULE, package)

        assert sorted(keyed) == ["unresolved", "warn"]
        assert keyed["warn"].result is not None
        assert "second-anchor" in keyed["warn"].result.observed

    def test_a_disconnected_component_is_unresolved(self) -> None:
        package = assembly_package(
            documents=chain(
                InstanceSpec("link-1", is_fixed=True),
                InstanceSpec("link-2"),
                InstanceSpec("lonely"),
            ),
            mates=[mate("link-1", "link-2")],
        )

        keyed = run(self.RULE, package)

        assert sorted(keyed) == ["pass", "unresolved"]
        assert labels(package, keyed["unresolved"]) == ["lonely"]
        assert keyed["unresolved"].reason is not None
        assert "not reachable" in keyed["unresolved"].reason
        assert "link-1" in keyed["unresolved"].reason

    def test_a_component_reached_only_by_a_suppressed_mate_is_unresolved(self) -> None:
        package = assembly_package(
            documents=chain(InstanceSpec("link-1", is_fixed=True), InstanceSpec("link-2")),
            mates=[mate("link-1", "link-2", suppressed=True)],
        )

        keyed = run(self.RULE, package)

        assert sorted(keyed) == ["pass", "unresolved"]
        assert labels(package, keyed["pass"]) == ["link-1"]
        assert labels(package, keyed["unresolved"]) == ["link-2"]

    def test_a_mate_with_a_suppression_gap_is_unresolved_and_is_no_edge(self) -> None:
        package = assembly_package(
            documents=chain(InstanceSpec("link-1", is_fixed=True), InstanceSpec("link-2")),
            mates=[mate("link-1", "link-2", suppression_gap=True)],
        )

        keyed = run(self.RULE, package)

        assert sorted(keyed) == ["pass", "unresolved"]
        assert labels(package, keyed["unresolved"]) == ["mate:0001", "link-2"]
        assert keyed["unresolved"].reason is not None
        assert "suppression state not readable" in keyed["unresolved"].reason

    def test_no_fixed_child_is_unresolved_for_the_document(self) -> None:
        package = assembly_package(
            documents=chain(InstanceSpec("link-1"), InstanceSpec("link-2")),
            mates=[mate("link-1", "link-2")],
        )

        keyed = run(self.RULE, package)

        assert list(keyed) == ["unresolved"]
        assert keyed["unresolved"].subjects == []
        assert keyed["unresolved"].reason == "no fixed child of the root assembly"


# --- rms.assembly.toolbox_parts_not_configurations --------------------------------


class TestToolboxPartsNotConfigurations:
    RULE = "rms.assembly.toolbox_parts_not_configurations"

    def test_no_toolbox_component_skips(self) -> None:
        package = assembly_package(
            documents=[part("doc:2", "cover", InstanceSpec("cover-1"))]
        )

        keyed = run(self.RULE, package)

        assert list(keyed) == ["skip"]
        assert keyed["skip"].reason == "no Toolbox component"

    def test_toolbox_instances_of_one_configuration_pass(self) -> None:
        package = assembly_package(
            documents=[
                part(
                    "doc:2",
                    "hex-screw",
                    InstanceSpec("screw-1", is_toolbox=True, referenced_configuration="M6x20"),
                    InstanceSpec("screw-2", is_toolbox=True, referenced_configuration="M6x20"),
                )
            ]
        )

        keyed = run(self.RULE, package)

        assert list(keyed) == ["pass"]
        assert labels(package, keyed["pass"]) == ["screw-1", "screw-2"]

    def test_one_toolbox_file_in_several_configurations_warns(self) -> None:
        package = assembly_package(
            documents=[
                part(
                    "doc:2",
                    "hex-screw",
                    InstanceSpec("screw-1", is_toolbox=True, referenced_configuration="M6x20"),
                    InstanceSpec("screw-2", is_toolbox=True, referenced_configuration="M8x30"),
                )
            ]
        )

        keyed = run(self.RULE, package)

        assert list(keyed) == ["warn"]
        result = keyed["warn"]
        assert labels(package, result) == ["screw-1", "screw-2"]
        assert result.result is not None
        assert result.result.status == "suspected"
        assert result.result.severity == "low"
        assert "doc:2" in result.result.observed
        assert "M6x20" in result.result.observed
        assert "M8x30" in result.result.observed

    def test_two_toolbox_files_of_one_configuration_each_pass(self) -> None:
        package = assembly_package(
            documents=[
                part(
                    "doc:2",
                    "hex-screw",
                    InstanceSpec("screw-1", is_toolbox=True, referenced_configuration="M6x20"),
                ),
                part(
                    "doc:3",
                    "washer",
                    InstanceSpec("washer-1", is_toolbox=True, referenced_configuration="M6"),
                ),
            ]
        )

        keyed = run(self.RULE, package)

        assert list(keyed) == ["pass"]

    def test_a_non_toolbox_file_in_several_configurations_is_not_a_finding(self) -> None:
        package = assembly_package(
            documents=[
                part(
                    "doc:2",
                    "bracket",
                    InstanceSpec("bracket-1", referenced_configuration="left"),
                    InstanceSpec("bracket-2", referenced_configuration="right"),
                )
            ]
        )

        keyed = run(self.RULE, package)

        assert list(keyed) == ["skip"]

    def test_a_component_with_a_toolbox_identity_gap_is_unresolved(self) -> None:
        package = assembly_package(
            documents=[
                part(
                    "doc:2",
                    "hex-screw",
                    InstanceSpec("screw-1", is_toolbox=True, referenced_configuration="M6x20"),
                    InstanceSpec("screw-2", suppression="lightweight"),
                )
            ],
            gaps=[toolbox_identity_gap("screw-2")],
        )

        keyed = run(self.RULE, package)

        assert sorted(keyed) == ["pass", "unresolved"]
        assert labels(package, keyed["pass"]) == ["screw-1"]
        assert labels(package, keyed["unresolved"]) == ["screw-2"]
        assert keyed["unresolved"].reason is not None
        assert "Toolbox identity not readable" in keyed["unresolved"].reason

    def test_an_unreadable_component_stops_the_rule_skipping(self) -> None:
        package = assembly_package(
            documents=[part("doc:2", "cover", InstanceSpec("cover-1", suppression="suppressed"))],
            gaps=[toolbox_identity_gap("cover-1")],
        )

        keyed = run(self.RULE, package)

        assert list(keyed) == ["unresolved"]
        assert labels(package, keyed["unresolved"]) == ["cover-1"]

    def test_the_gap_names_one_component_and_not_a_longer_path_that_ends_with_it(self) -> None:
        package = assembly_package(
            documents=[
                part(
                    "doc:2",
                    "hex-screw",
                    InstanceSpec("screw-1", is_toolbox=True, referenced_configuration="M6x20"),
                    InstanceSpec("screw-1b", parent_name="gearbox-1", is_toolbox=True),
                )
            ],
            subassembly=SubassemblySpec(document_id="doc:3", name="gearbox"),
            gaps=[toolbox_identity_gap("gearbox-1/screw-1b")],
        )

        keyed = run(self.RULE, package)

        assert labels(package, keyed["unresolved"]) == ["gearbox-1/screw-1b"]
        assert labels(package, keyed["pass"]) == ["screw-1"]


# --- the scope of the evaluator ---------------------------------------------------


class TestEvaluateAssembly:
    def package(self) -> EvidencePackage:
        return assembly_package(
            documents=[
                part(
                    "doc:3",
                    "cover",
                    InstanceSpec("cover-1", is_fixed=True),
                    InstanceSpec("shaft-1", parent_name="gearbox-1"),
                )
            ],
            mates=[mate("cover-1", "shaft-1")],
            subassembly=SubassemblySpec(document_id="doc:2", name="gearbox"),
        )

    def test_every_evaluable_assembly_rule_is_dispatched_once_per_outcome(self) -> None:
        results = evaluate_assembly(self.package(), TABLE)

        assert {result.rule_id for result in results} == set(ASSEMBLY_RULE_IDS)

    def test_results_name_the_root_assembly_document_only(self) -> None:
        package = self.package()

        documents = {result.document_id for result in evaluate_assembly(package, TABLE)}

        assert documents == {ROOT}
        assert package.design.root_assembly_document_id == ROOT

    def test_no_result_names_a_subassembly_document(self) -> None:
        package = self.package()
        subassemblies = {
            document.document_id
            for document in package.documents
            if document.kind == "assembly" and document.document_id != ROOT
        }
        assert subassemblies == {"doc:2"}

        results = evaluate_assembly(package, TABLE)

        assert not [result for result in results if result.document_id in subassemblies]

    def test_the_rules_keep_the_contracts_order(self) -> None:
        results = evaluate_assembly(self.package(), TABLE)

        seen: list[str] = []
        for result in results:
            if result.rule_id not in seen:
                seen.append(result.rule_id)
        assert seen == list(ASSEMBLY_RULE_IDS)

    def test_the_data_gap_rules_are_coverage_only_and_are_never_dispatched(self) -> None:
        assert DATA_GAP_RULE_IDS == (
            "rms.assembly.no_sibling_in_context_refs",
            "rms.assembly.positions_driven_by_globals",
            "rms.assembly.mates_described",
            "rms.assembly.subassemblies",
        )
        for rule_id in DATA_GAP_RULE_IDS:
            assert RULES[rule_id].fn is None
            assert RULES[rule_id].severity is None

        results = evaluate_assembly(self.package(), TABLE)

        assert not [result for result in results if result.rule_id in DATA_GAP_RULE_IDS]

    def test_the_subassembly_rule_carries_the_contracts_coverage_reason(self) -> None:
        """`report.py` writes this one as an undispatched item over the subassembly
        documents; the evaluator's part of the contract is not to evaluate them."""
        rule = RULES["rms.assembly.subassemblies"]

        assert rule.coverage == (
            "unresolved",
            "subassembly mates not extracted; assembly rules evaluated for the root "
            "document only",
        )
