"""Which documents a standards run grades, once each, and by what reached them (T023).

FR-003 is the whole of this module: the graded set is the root document, every part and
sub-assembly reachable through the component tree, and - for a **drawing** root - every
document a view on any sheet references plus everything reachable through a referenced
assembly's own tree, **deduplicated by `document_id`**. A document reached twice is graded
once, and each `CheckedDocument` carries every instance that reaches it, so a failing check
can name them all in one finding (`contracts/rules.md`, granularity).

Two refusals are deliberately asymmetric (FR-004):

- a **reached** document whose kind or path the package does not record is carried as an
  **unresolved** graded document - the checks that would have applied to it become
  unresolved coverage naming it and the instances that reach it, and the run continues;
- only the **root** can refuse the run, because a root with no kind has no check sequence
  and a root with no path has nothing to match the profile's prefixes or its part-number
  convention against. The macro is silent in exactly these cases (difference k).

The part-number pattern is asserted here because `CheckedDocument.matches_part_number` is
where it is decided once per document; `contracts/rules.md` ("Matching the pattern") is
normative, including the rule that the name matched is the one **in the path** and never a
window title.

Every value-bearing string in this module comes from the fictional fixture profile or is
invented for it (FR-001): no company value appears here.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from swreview.checks.rules.run import CheckRunError
from swreview.checks.standards.profile import StandardsProfile, load_profile
from swreview.checks.standards.traversal import (
    CheckedDocument,
    UngradableRootError,
    graded_documents,
    part_number_matches,
)
from swreview.ir.models import EvidencePackage
from tests.support.standards import (
    AssemblySpec,
    ComponentSpec,
    DocumentSpec,
    DrawingSpec,
    PartSpec,
    SheetSpec,
    ViewSpec,
    standards_package,
)

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "standards"
PROFILE_A = FIXTURE_DIR / "profile-a.yaml"

PROFILE = load_profile(PROFILE_A)
"""The fictional profile every package here is written for: its `vault_root` is the root the
builder prefixes every path with, and its `part_number.pattern` is what `matches_part_number`
answers against."""


def package_of(*documents: DocumentSpec) -> EvidencePackage:
    """A standards package for `PROFILE`, whose first document is the root."""
    return standards_package(documents=list(documents), profile=PROFILE)


def with_components(package: EvidencePackage, **parents: str | None) -> EvidencePackage:
    """`package` with the named instances re-parented - an orphan, a self-parent, a top."""
    return package.model_copy(
        update={
            "components": [
                row.model_copy(update={"parent_id": parents[row.id]}) if row.id in parents else row
                for row in package.components
            ]
        }
    )


def without_document(package: EvidencePackage, document_id: str) -> EvidencePackage:
    """`package` with one document row dropped: a kind and a path it does not record."""
    return package.model_copy(
        update={"documents": [row for row in package.documents if row.document_id != document_id]}
    )


def with_document(package: EvidencePackage, document_id: str, **fields: Any) -> EvidencePackage:
    """`package` with one document row edited - a blank path, a different file name."""
    return package.model_copy(
        update={
            "documents": [
                row.model_copy(update=fields) if row.document_id == document_id else row
                for row in package.documents
            ]
        }
    )


def ids(documents: Sequence[CheckedDocument]) -> list[str]:
    return [document.document_id for document in documents]


def by_id(documents: Sequence[CheckedDocument], document_id: str) -> CheckedDocument:
    return next(document for document in documents if document.document_id == document_id)


def a_part(name: str = "MR-40021", **overrides: Any) -> PartSpec:
    return PartSpec(name=name, **overrides)


# --- the component tree --------------------------------------------------------------------


class TestTheGradedSet:
    def test_the_root_and_every_document_under_it_are_graded_once_each(self) -> None:
        package = package_of(
            AssemblySpec(
                name="MR-40000",
                components=(
                    ComponentSpec(name="sub-1", document="MR-40100"),
                    ComponentSpec(name="plate-1", document="MR-40021"),
                ),
            ),
            AssemblySpec(
                name="MR-40100",
                components=(ComponentSpec(name="plate-2", document="MR-40021", parent="sub-1"),),
            ),
            a_part(),
        )

        graded = graded_documents(package, PROFILE)

        assert ids(graded) == ["doc:1", "doc:2", "doc:3"]
        assert [document.kind for document in graded] == ["assembly", "assembly", "part"]

    def test_the_root_is_first_and_says_so(self) -> None:
        package = package_of(
            AssemblySpec(
                name="MR-40000", components=(ComponentSpec(name="plate-1", document="MR-40021"),)
            ),
            a_part(),
        )

        graded = graded_documents(package, PROFILE)

        assert graded[0].document_id == "doc:1"
        assert graded[0].reached_by == "root"
        assert graded[1].reached_by == "component_tree"

    def test_a_document_reached_through_many_instances_is_graded_once_carrying_them_all(
        self,
    ) -> None:
        package = package_of(
            AssemblySpec(
                name="MR-40000",
                components=tuple(
                    ComponentSpec(name=f"plate-{number}", document="MR-40021")
                    for number in range(1, 21)
                ),
            ),
            a_part(),
        )

        plate = by_id(graded_documents(package, PROFILE), "doc:2")

        assert len(plate.instances) == 20
        assert [row.id for row in plate.instances] == [
            row.id for row in package.components if row.document_id == "doc:2"
        ]

    def test_a_checked_document_carries_its_kind_path_file_name_and_configuration(self) -> None:
        package = package_of(
            AssemblySpec(name="MR-40000", configuration="AsBuilt"),
            a_part(folder="jobs/common/"),
        )

        root = graded_documents(package, PROFILE)[0]

        assert root.kind == "assembly"
        assert root.path == f"{PROFILE.vault_root}/MR-40000.SLDASM"
        assert root.file_name == "MR-40000.SLDASM"
        assert root.configuration == "AsBuilt"
        assert root.unresolved_reason is None

    def test_a_part_opened_alone_grades_only_itself(self) -> None:
        graded = graded_documents(package_of(a_part()), PROFILE)

        assert ids(graded) == ["doc:1"]
        assert graded[0].reached_by == "root"

    def test_the_root_of_a_run_is_not_reached_through_a_component_instance(self) -> None:
        """`CheckedDocument.instances` is what a finding names in `component_ids`, and the
        root assembly is not reached through its own instance: it is the root."""
        package = package_of(
            AssemblySpec(
                name="MR-40000", components=(ComponentSpec(name="plate-1", document="MR-40021"),)
            ),
            a_part(),
        )

        graded = graded_documents(package, PROFILE)

        assert graded[0].instances == ()
        assert graded[0].unresolved_instances == ()
        assert [row.id for row in graded[1].instances] == ["cmp:0002"]

    def test_the_synthesized_root_of_a_part_opened_alone_is_not_one_of_its_instances(self) -> None:
        """`contracts/rules.md` (fully_mated) says that instance is not a subject; it is not
        an instance through which the part is reached either."""
        synthesized = package_of(
            AssemblySpec(
                name="MR-40000", components=(ComponentSpec(name="plate-1", document="MR-40021"),)
            ),
            a_part(),
        ).components[0]
        part_alone = package_of(a_part()).model_copy(update={"components": [synthesized]})

        graded = graded_documents(part_alone, PROFILE)

        assert ids(graded) == ["doc:1"]
        assert graded[0].instances == ()

    def test_the_set_is_the_same_answer_every_time_it_is_asked_for(self) -> None:
        package = package_of(
            AssemblySpec(
                name="MR-40000", components=(ComponentSpec(name="plate-1", document="MR-40021"),)
            ),
            a_part(),
        )

        assert graded_documents(package, PROFILE) == graded_documents(package, PROFILE)
        assert isinstance(graded_documents(package, PROFILE), tuple)


# --- the drawing-rooted fan-out --------------------------------------------------------------


class TestADrawingRoot:
    def drawing_package(self) -> EvidencePackage:
        """A drawing whose one view references an assembly holding two parts."""
        return package_of(
            DrawingSpec(
                name="MR-40000",
                sheets=(
                    SheetSpec(
                        name="Sheet1",
                        views=(
                            ViewSpec(name="Sheet Format1", view_type_raw=1),
                            ViewSpec(name="View1", references="MR-40100"),
                        ),
                    ),
                ),
            ),
            AssemblySpec(
                name="MR-40100",
                components=(
                    ComponentSpec(name="plate-1", document="MR-40021"),
                    ComponentSpec(name="bracket-1", document="MR-40022"),
                ),
            ),
            a_part(),
            a_part("MR-40022"),
        )

    def test_the_drawing_the_models_it_references_and_their_trees_are_graded(self) -> None:
        graded = graded_documents(self.drawing_package(), PROFILE)

        assert ids(graded) == ["doc:1", "doc:2", "doc:3", "doc:4"]
        assert [document.reached_by for document in graded] == [
            "root",
            "drawing_reference",
            "component_tree",
            "component_tree",
        ]

    def test_the_drawing_itself_carries_no_component_instance(self) -> None:
        drawing = graded_documents(self.drawing_package(), PROFILE)[0]

        assert drawing.kind == "drawing"
        assert drawing.instances == ()
        assert drawing.unresolved_instances == ()

    def test_a_document_reached_by_a_view_and_by_a_tree_is_graded_once_as_the_reference(
        self,
    ) -> None:
        """The same part hangs under the referenced assembly and is drawn in its own view."""
        package = package_of(
            DrawingSpec(
                name="MR-40000",
                sheets=(
                    SheetSpec(
                        name="Sheet1",
                        views=(
                            ViewSpec(name="View1", references="MR-40100"),
                            ViewSpec(name="View2", references="MR-40021"),
                        ),
                    ),
                ),
            ),
            AssemblySpec(
                name="MR-40100",
                components=(ComponentSpec(name="plate-1", document="MR-40021"),),
            ),
            a_part(),
        )

        graded = graded_documents(package, PROFILE)
        plate = by_id(graded, "doc:3")

        assert ids(graded) == ["doc:1", "doc:2", "doc:3"]
        assert plate.reached_by == "drawing_reference"
        assert [row.id for row in plate.instances] == ["cmp:0003"]

    def test_a_view_that_references_nothing_in_the_package_adds_no_document(self) -> None:
        package = package_of(
            DrawingSpec(
                name="MR-40000",
                sheets=(
                    SheetSpec(
                        name="Sheet1",
                        views=(
                            ViewSpec(name="View1", referenced_model_path="/elsewhere/x.SLDPRT"),
                        ),
                    ),
                ),
            ),
        )

        assert ids(graded_documents(package, PROFILE)) == ["doc:1"]

    def test_every_sheet_is_read_not_only_the_active_one(self) -> None:
        package = package_of(
            DrawingSpec(
                name="MR-40000",
                active_sheet="Sheet1",
                sheets=(
                    SheetSpec(
                        name="Sheet1",
                        was_active=True,
                        views=(ViewSpec(name="View1", references="MR-40021"),),
                    ),
                    SheetSpec(
                        name="Sheet2", views=(ViewSpec(name="View2", references="MR-40022"),)
                    ),
                ),
            ),
            a_part(),
            a_part("MR-40022"),
        )

        assert ids(graded_documents(package, PROFILE)) == ["doc:1", "doc:2", "doc:3"]

    def test_a_forest_hung_under_a_synthesized_instance_of_the_drawing_is_walked_through(
        self,
    ) -> None:
        """The shape the real dumper emits (`research.md` R9), which the fixture builder
        produces: one subtree per referenced model under a synthesized forest root
        (`cmp:0001`) carrying the drawing's own document id. The drawing is graded once as
        the root and is never a component of itself."""
        package = package_of(
            DrawingSpec(
                name="MR-40000",
                sheets=(
                    SheetSpec(
                        name="Sheet1",
                        views=(
                            ViewSpec(name="View1", references="MR-40100"),
                            ViewSpec(name="View2", references="MR-40200"),
                        ),
                    ),
                ),
            ),
            AssemblySpec(
                name="MR-40100",
                components=(ComponentSpec(name="plate-1", document="MR-40021"),),
            ),
            AssemblySpec(
                name="MR-40200",
                components=(ComponentSpec(name="bracket-1", document="MR-40022"),),
            ),
            a_part(),
            a_part("MR-40022"),
        )

        graded = graded_documents(package, PROFILE)

        assert ids(graded) == ["doc:1", "doc:2", "doc:3", "doc:4", "doc:5"]
        assert graded[0].kind == "drawing"
        assert graded[0].instances == ()
        assert "cmp:0001" not in {row.id for document in graded for row in document.instances}
        assert [row.id for row in by_id(graded, "doc:2").instances] == ["cmp:0002"]
        assert [row.id for row in by_id(graded, "doc:3").instances] == ["cmp:0003"]
        assert [row.id for row in by_id(graded, "doc:4").instances] == ["cmp:0004"]
        assert [row.id for row in by_id(graded, "doc:5").instances] == ["cmp:0005"]


# --- the top of the forest -------------------------------------------------------------------


class TestAForestTopThatIsNotParentless:
    """FR-003 grades what the package describes. A top instance whose parent is missing from
    the package, or that names itself, is a defect in whatever wrote the dump; dropping its
    whole subtree would grade fewer documents than the package describes and say nothing
    about it, which is the one thing a release gate must not do."""

    def two_deep(self) -> EvidencePackage:
        return package_of(
            AssemblySpec(
                name="MR-40000", components=(ComponentSpec(name="sub-1", document="MR-40100"),)
            ),
            AssemblySpec(
                name="MR-40100",
                components=(ComponentSpec(name="plate-1", document="MR-40021", parent="sub-1"),),
            ),
            a_part(),
        )

    def test_a_subtree_whose_top_names_a_parent_the_package_does_not_carry_is_still_graded(
        self,
    ) -> None:
        package = with_components(self.two_deep(), **{"cmp:0002": "cmp:9999"})

        graded = graded_documents(package, PROFILE)

        assert ids(graded) == ["doc:1", "doc:2", "doc:3"]
        assert [row.id for row in by_id(graded, "doc:2").instances] == ["cmp:0002"]
        assert [row.id for row in by_id(graded, "doc:3").instances] == ["cmp:0003"]

    def test_a_subtree_whose_top_names_itself_as_its_parent_is_still_graded(self) -> None:
        package = with_components(self.two_deep(), **{"cmp:0002": "cmp:0002"})

        graded = graded_documents(package, PROFILE)

        assert ids(graded) == ["doc:1", "doc:2", "doc:3"]
        assert [row.id for row in by_id(graded, "doc:2").instances] == ["cmp:0002"]

    def test_a_cycle_below_the_top_terminates_and_grades_each_document_once(self) -> None:
        package = with_components(
            self.two_deep(), **{"cmp:0002": "cmp:0003", "cmp:0003": "cmp:0002"}
        )

        graded = graded_documents(package, PROFILE)

        assert ids(graded) == ["doc:1", "doc:2", "doc:3"]


# --- unresolved instances ---------------------------------------------------------------------


class TestUnresolvedInstances:
    @pytest.mark.parametrize("state", ["suppressed", "lightweight", "unloaded"])
    def test_an_unresolved_instance_is_carried_with_its_state(self, state: str) -> None:
        package = package_of(
            AssemblySpec(
                name="MR-40000",
                components=(
                    ComponentSpec(name="plate-1", document="MR-40021"),
                    ComponentSpec(name="plate-2", document="MR-40021", suppression=state),  # type: ignore[arg-type]
                ),
            ),
            a_part(),
        )

        plate = by_id(graded_documents(package, PROFILE), "doc:2")

        assert [row.id for row in plate.instances] == ["cmp:0002", "cmp:0003"]
        assert plate.unresolved_instances == (("cmp:0003", state),)

    def test_a_document_reached_only_through_unresolved_instances_is_still_graded(self) -> None:
        package = package_of(
            AssemblySpec(
                name="MR-40000",
                components=(
                    ComponentSpec(name="plate-1", document="MR-40021", suppression="suppressed"),
                ),
            ),
            a_part(),
        )

        plate = by_id(graded_documents(package, PROFILE), "doc:2")

        assert plate.reached_by == "component_tree"
        assert plate.unresolved_instances == (("cmp:0002", "suppressed"),)
        assert len(plate.instances) == len(plate.unresolved_instances)

    def test_a_resolved_instance_is_never_listed_as_unresolved(self) -> None:
        package = package_of(
            AssemblySpec(
                name="MR-40000",
                components=(ComponentSpec(name="plate-1", document="MR-40021"),),
            ),
            a_part(),
        )

        plate = by_id(graded_documents(package, PROFILE), "doc:2")

        assert plate.unresolved_instances == ()


# --- a reached document the package does not describe -------------------------------------------


class TestAnUnresolvedDocument:
    def reached_without_a_row(self) -> EvidencePackage:
        package = package_of(
            AssemblySpec(
                name="MR-40000",
                components=(ComponentSpec(name="virtual-1", document="MR-40021"),),
            ),
            a_part(),
        )
        return without_document(package, "doc:2")

    def test_it_is_graded_as_unresolved_rather_than_refusing_the_run(self) -> None:
        graded = graded_documents(self.reached_without_a_row(), PROFILE)
        unknown = by_id(graded, "doc:2")

        assert ids(graded) == ["doc:1", "doc:2"]
        assert unknown.kind is None
        assert unknown.path is None
        assert unknown.file_name is None
        assert unknown.configuration is None
        assert unknown.matches_part_number is False

    def test_the_reason_names_the_document_and_it_carries_the_instances_that_reach_it(
        self,
    ) -> None:
        unknown = by_id(graded_documents(self.reached_without_a_row(), PROFILE), "doc:2")

        assert unknown.unresolved_reason is not None
        assert "doc:2" in unknown.unresolved_reason
        assert [row.id for row in unknown.instances] == ["cmp:0002"]

    def test_a_reached_document_with_no_path_is_unresolved_too(self) -> None:
        package = package_of(
            AssemblySpec(
                name="MR-40000",
                components=(ComponentSpec(name="plate-1", document="MR-40021"),),
            ),
            a_part(),
        )

        plate = by_id(graded_documents(with_document(package, "doc:2", path=" "), PROFILE), "doc:2")

        assert plate.kind == "part"
        assert plate.path is None
        assert plate.unresolved_reason is not None
        assert "doc:2" in plate.unresolved_reason
        assert plate.matches_part_number is False


# --- only the root can refuse the run ------------------------------------------------------


class TestARootThatCannotBeGraded:
    def test_a_root_the_package_does_not_describe_refuses_the_run(self) -> None:
        package = without_document(package_of(a_part()), "doc:1")

        with pytest.raises(UngradableRootError) as refusal:
            graded_documents(package, PROFILE)

        assert "doc:1" in str(refusal.value)

    def test_a_root_that_has_never_been_saved_refuses_the_run_naming_the_reason(self) -> None:
        package = with_document(package_of(a_part()), "doc:1", path="")

        with pytest.raises(UngradableRootError) as refusal:
            graded_documents(package, PROFILE)

        assert "doc:1" in str(refusal.value)
        assert "never been saved" in str(refusal.value)

    def test_the_refusal_is_a_named_check_run_error(self) -> None:
        package = with_document(package_of(a_part()), "doc:1", path="   ")

        with pytest.raises(CheckRunError) as refusal:
            graded_documents(package, PROFILE)

        assert refusal.value.error_class == "UngradableRoot"

    def test_the_same_defect_below_the_root_does_not_refuse_the_run(self) -> None:
        """The asymmetry of FR-004, asserted as one pair rather than assumed."""
        package = package_of(
            AssemblySpec(
                name="MR-40000",
                components=(ComponentSpec(name="plate-1", document="MR-40021"),),
            ),
            a_part(),
        )

        graded = graded_documents(with_document(package, "doc:2", path=""), PROFILE)

        assert ids(graded) == ["doc:1", "doc:2"]


# --- the part-number convention ------------------------------------------------------------


class TestThePartNumberPattern:
    @pytest.mark.parametrize(
        ("pattern", "file_name", "expected"),
        [
            ("MR-#####.SLD???", "MR-40021.SLDPRT", True),
            ("MR-#####.SLD???", "mr-40021.sldprt", True),
            ("MR-#####.SLD???", "MR-4002X.SLDPRT", False),
            ("MR-#####.SLD???", "MR-4002.SLDPRT", False),
            ("MR-#####.SLD???", "MR-400211.SLDPRT", False),
            ("MR-#####.SLD???", "sub/MR-40021.SLDPRT", False),
            ("MR-#####.SLD???", "MR-40021.SLDPRT.bak", False),
            ("MR-#####.SLD???", "MR-40021", False),
            ("MR-?????.SLD???", "MR-4A021.SLDASM", True),
            ("MR-#####.SLD???", "", False),
            ("", "MR-40021.SLDPRT", False),
            ("", "", False),
        ],
    )
    def test_the_vocabulary_is_digit_any_character_and_literal(
        self, pattern: str, file_name: str, expected: bool
    ) -> None:
        assert part_number_matches(pattern, file_name) is expected

    def test_a_regular_expression_in_the_pattern_is_literal_text(self) -> None:
        """`#` and `?` are the only two wildcards; the rest is compared as written."""
        assert part_number_matches("MR-.*", "MR-40021") is False
        assert part_number_matches("MR-.*", "MR-.*") is True

    def test_a_graded_document_says_whether_its_name_follows_the_convention(self) -> None:
        package = package_of(
            AssemblySpec(
                name="MR-40000",
                components=(ComponentSpec(name="fixture-1", document="shop-fixture"),),
            ),
            a_part("shop-fixture"),
        )

        graded = graded_documents(package, PROFILE)

        assert by_id(graded, "doc:1").matches_part_number is True
        assert by_id(graded, "doc:2").matches_part_number is False

    def test_the_name_matched_is_the_one_in_the_path_not_the_recorded_file_name(self) -> None:
        """A title can hide an extension; the path cannot (difference l)."""
        package = with_document(package_of(a_part()), "doc:1", file_name="MR-40021")

        assert graded_documents(package, PROFILE)[0].matches_part_number is True

    def test_an_empty_pattern_matches_nothing(self) -> None:
        empty = StandardsProfile.model_validate(
            PROFILE.model_dump() | {"part_number": {"pattern": ""}}
        )

        assert graded_documents(package_of(a_part()), empty)[0].matches_part_number is False
