"""`CheckFamily`: the facts that differ between one check family and another (T009).

Feature 003's rule machinery hard-codes four things to its own family - the summary check
id, the rule-scope vocabulary, the rules version, and the severity vocabulary with its map
to a `Finding` status and severity. Feature 006 adds a second family over the same
machinery, so those four become **data** rather than module constants, carried on one
frozen descriptor per family (`specs/006-standards-check/data-model.md` section 3,
`research.md` R7).

Two things are asserted here and nowhere else:

- **the descriptor is facts, not behaviour.** It is a frozen dataclass of strings, sets and
  maps; a family is a list of facts, not a base class with hooks, so there is nothing on it
  to override. The two callables the report layer needs - a subject decorator and an extra
  coverage step - are supplied by the family *module* at the call, not carried here;
- **neither family's names leak into the neutral layer.** `checks/rules/results.py` imports
  no family's rule type: importing `RmsRule` there would be the `checks/standards` ->
  `checks/rms` dependency the design rejects, in the other direction (FR-028, R7). The
  assertion is over the import graph of the whole `checks/rules` package, because the
  property is the package's and not one module's.

The rms descriptor is asserted against today's values, byte for byte where a string is
printed - the four waiver status labels `swreview exceptions accept-rms` prints are the
ones an engineer reads, and feature 003's tests pin them unedited. The standards
descriptor is built here from the values `contracts/rules.md` and `contracts/cli.md` state
rather than imported: `STANDARDS_FAMILY` lands with the standards registry (T022), and what
this module has to prove before then is that the descriptor **admits** a family whose
severity vocabulary is not feature 003's.
"""

from __future__ import annotations

import ast
import dataclasses
from pathlib import Path

import pytest

from swreview.checks.rms.registry import RMS_FAMILY, RULES, RULES_VERSION
from swreview.checks.rules.family import CheckFamily

RULES_PACKAGE = Path(__file__).resolve().parents[2] / "src" / "swreview" / "checks" / "rules"

FAMILY_PACKAGES = ("swreview.checks.rms", "swreview.checks.standards")
"""The two family packages. A module of `checks/rules/` may import neither."""


def standards_family() -> CheckFamily:
    """The standards descriptor as `specs/006-standards-check/` states it.

    Built here rather than imported so this module can assert the shape before the
    standards registry exists; T022 replaces it with the real `STANDARDS_FAMILY` and the
    values below are what that one has to match.
    """
    return CheckFamily(
        name="standards",
        summary_check="standards.release",
        rules_version="1",
        scopes=frozenset({"assembly", "part", "drawing", "document"}),
        tools={
            "assembly": "check_standards_assembly",
            "part": "check_standards_part",
            "drawing": "check_standards_drawing",
            "document": "check_standards_document",
        },
        check_file_family="standards",
        severities=frozenset({"error", "warning"}),
        status_by_severity={
            "error": ("demonstrated", "medium"),
            "warning": ("suspected", "low"),
        },
        high_severity=frozenset(
            {
                "standards.assembly.mate_references",
                "standards.assembly.rebuild_errors",
                "standards.part.rebuild_errors",
                "standards.drawing.dimensions_not_overridden",
            }
        ),
        waiver_labels={
            "unknown": "invalid (unknown check)",
            "warning": "invalid (warning check)",
        },
    )


class TestFactsAndNoBehaviour:
    """A family is a list of facts: a frozen dataclass of strings, sets and maps."""

    def test_the_descriptor_is_a_frozen_dataclass(self) -> None:
        assert dataclasses.is_dataclass(CheckFamily)
        assert CheckFamily.__dataclass_params__.frozen is True

    def test_a_field_cannot_be_reassigned(self) -> None:
        with pytest.raises(dataclasses.FrozenInstanceError):
            RMS_FAMILY.summary_check = "something.else"  # type: ignore[misc]

    def test_it_carries_exactly_the_ten_facts_the_design_names(self) -> None:
        assert [field.name for field in dataclasses.fields(CheckFamily)] == [
            "name",
            "summary_check",
            "rules_version",
            "scopes",
            "tools",
            "check_file_family",
            "severities",
            "status_by_severity",
            "high_severity",
            "waiver_labels",
        ]

    def test_no_field_holds_a_callable(self) -> None:
        """The report layer's two hooks are supplied by the family module at the call.

        A callable here would make the descriptor a base class with hooks wearing a
        dataclass's clothes, which is the shape `research.md` R7 rejects by name.
        """
        for field in dataclasses.fields(CheckFamily):
            value = getattr(RMS_FAMILY, field.name)
            assert not callable(value), f"{field.name} is a callable, not a fact"

    def test_it_defines_no_method_of_its_own(self) -> None:
        own = {
            name
            for name, value in vars(CheckFamily).items()
            if callable(value) and not name.startswith("__")
        }
        assert own == set()


class TestTheRmsFamily:
    """Today's values, unchanged by the move (feature 003 passes unedited)."""

    def test_name_and_check_file_family(self) -> None:
        assert RMS_FAMILY.name == "rms"
        assert RMS_FAMILY.check_file_family == "rms"

    def test_the_summary_check_is_the_checklist_item_the_rules_answer(self) -> None:
        assert RMS_FAMILY.summary_check == "modeling.resilience"

    def test_the_rules_version_is_the_catalogue_s_own(self) -> None:
        assert RMS_FAMILY.rules_version == RULES_VERSION

    def test_the_scope_vocabulary_is_the_five_scopes_of_the_catalogue(self) -> None:
        assert RMS_FAMILY.scopes == frozenset(
            {"part", "assembly", "equations", "drawing", "advisory"}
        )
        assert {rule.scope for rule in RULES.values()} <= RMS_FAMILY.scopes

    def test_the_tools_are_the_three_scopes_this_build_dispatches(self) -> None:
        assert RMS_FAMILY.tools == {
            "part": "check_rms_part",
            "assembly": "check_rms_assembly",
            "equations": "check_rms_equations",
        }

    def test_the_severity_vocabulary_is_fail_and_warn(self) -> None:
        assert RMS_FAMILY.severities == frozenset({"fail", "warn"})
        assert {
            rule.severity for rule in RULES.values() if rule.severity is not None
        } == RMS_FAMILY.severities

    def test_a_fail_is_demonstrated_and_a_warn_is_suspected(self) -> None:
        assert RMS_FAMILY.status_by_severity == {
            "fail": ("demonstrated", "medium"),
            "warn": ("suspected", "low"),
        }

    def test_the_high_severity_rules_are_the_two_families_that_break_a_rebuild(
        self,
    ) -> None:
        assert RMS_FAMILY.high_severity == frozenset(
            {
                "rms.refs.direction",
                "rms.refs.quarantine_has_no_children",
                "rms.sketches.not_over_defined",
            }
        )

    def test_every_high_severity_id_is_a_fail_rule_of_the_catalogue(self) -> None:
        for rule_id in RMS_FAMILY.high_severity:
            assert RULES[rule_id].severity == "fail"

    def test_the_waiver_status_labels_are_byte_identical_to_today_s(self) -> None:
        """`swreview exceptions accept-rms` prints these; feature 003's tests pin them."""
        assert RMS_FAMILY.waiver_labels == {
            "unknown": "invalid (unknown rule)",
            "warn": "invalid (warn rule)",
            "unresolved": "invalid (data-gap rule)",
            "out_of_scope": "invalid (out-of-scope rule)",
        }


class TestTheDescriptorAdmitsASecondFamily:
    """Nothing on the descriptor is feature 003's vocabulary wearing a neutral name."""

    def test_a_family_whose_severities_are_not_fail_and_warn_is_legal(self) -> None:
        family = standards_family()

        assert family.severities == frozenset({"error", "warning"})
        assert family.severities.isdisjoint(RMS_FAMILY.severities)

    def test_its_summary_check_and_scopes_are_its_own(self) -> None:
        family = standards_family()

        assert family.summary_check == "standards.release"
        assert "document" in family.scopes
        assert "equations" not in family.scopes

    def test_its_waiver_labels_are_its_own_and_need_only_the_two_it_can_print(
        self,
    ) -> None:
        family = standards_family()

        assert family.waiver_labels == {
            "unknown": "invalid (unknown check)",
            "warning": "invalid (warning check)",
        }


class TestTheInvariant:
    """The descriptor refuses a family that contradicts itself."""

    def test_every_severity_is_mapped_to_a_status_and_a_severity(self) -> None:
        with pytest.raises(ValueError, match="severity"):
            dataclasses.replace(RMS_FAMILY, severities=frozenset({"fail", "warn", "note"}))

    def test_a_tool_for_a_scope_the_family_does_not_have_is_refused(self) -> None:
        with pytest.raises(ValueError, match="scope"):
            dataclasses.replace(
                RMS_FAMILY, tools={**RMS_FAMILY.tools, "drawings": "check_rms_drawings"}
            )

    def test_a_family_that_cannot_say_a_listed_id_is_unknown_is_refused(self) -> None:
        labels = {key: value for key, value in RMS_FAMILY.waiver_labels.items() if key != "unknown"}
        with pytest.raises(ValueError, match="unknown"):
            dataclasses.replace(RMS_FAMILY, waiver_labels=labels)

    def test_a_non_waivable_severity_with_no_label_is_refused(self) -> None:
        labels = {key: value for key, value in RMS_FAMILY.waiver_labels.items() if key != "warn"}
        with pytest.raises(ValueError, match="warn"):
            dataclasses.replace(RMS_FAMILY, waiver_labels=labels)


class TestTheNeutralLayerNamesNoFamily:
    """FR-028: `checks/rules/` is the machinery, and it knows of no family by name."""

    def _imported_modules(self, path: Path) -> list[str]:
        """Every module `path` imports, as a dotted name, absolute imports only."""
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        names: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                assert node.level == 0, f"{path.name}: relative imports are not used here"
                names.append(node.module)
        return names

    def test_the_package_has_the_six_modules_the_move_names(self) -> None:
        assert sorted(path.name for path in RULES_PACKAGE.glob("*.py")) == [
            "__init__.py",
            "family.py",
            "registry.py",
            "report.py",
            "results.py",
            "run.py",
        ]

    def test_results_imports_no_family_s_rule_type(self) -> None:
        """The assertion R7 names: `RuleResult` is built without knowing which family."""
        imported = self._imported_modules(RULES_PACKAGE / "results.py")

        assert not [
            module
            for module in imported
            if any(module.startswith(package) for package in FAMILY_PACKAGES)
        ]

    @pytest.mark.parametrize(
        "module_name",
        ["__init__.py", "family.py", "registry.py", "report.py", "results.py", "run.py"],
    )
    def test_no_module_of_the_neutral_layer_imports_a_family(self, module_name: str) -> None:
        imported = self._imported_modules(RULES_PACKAGE / module_name)

        assert not [
            module
            for module in imported
            if any(module.startswith(package) for package in FAMILY_PACKAGES)
        ]
