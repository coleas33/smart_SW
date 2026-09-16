"""The RMS rule registry must say exactly what `contracts/rules.md` says (T011).

The registry is the single catalogue the evaluators, the report layer, the tools, the CLI
and the docs read - never a second list (plan.md, design point 3) - so the one thing worth
asserting about it is that it has not drifted from the contract. The contract's tables are
parsed here rather than retyped: a rule added, removed, renamed, re-scoped, re-worded or
re-graded in `contracts/rules.md` and not in the registry fails this module, and so does
the reverse.

Two spellings differ by column and are normalised on the way in:

- a `statement` cell is prose with markdown code spans inside it (`` `ambiguous` counts as
  material``), and the registry stores the prose a reader sees in a finding's requirement,
  so the backticks are dropped;
- a `coverage reason` cell is one code span, sometimes followed by a parenthetical note
  about the item's scope, so the reason is the first code span and nothing else.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import get_args

import pytest

from swreview.checks.rms import RULES, RmsRule, by_scope, coverage_only, evaluable
from swreview.checks.rms.registry import RuleCoverageBucket, bind
from swreview.report.session import CoverageBucket
from tests.support.contracts import REPO_ROOT

CONTRACT = REPO_ROOT / "specs" / "003-resilient-modeling" / "contracts" / "rules.md"

EVALUABLE_SECTIONS: dict[str, str] = {
    "Part scope": "part",
    "Equation scope": "equations",
    "Assembly scope": "assembly",
}
"""Heading prefix of each table whose rows carry a severity, and the scope it declares."""

COVERAGE_SECTIONS: dict[str, str] = {
    "Data not yet extracted": "unresolved",
    "Out of scope in this version": "out_of_scope",
}
"""Heading prefix of each table whose rows carry a coverage bucket, and that bucket."""

EXPECTED_PER_SCOPE: dict[str, int] = {
    "part": 18,
    "equations": 2,
    "assembly": 8,
    "drawing": 1,
    "advisory": 5,
}
"""The counts the contract's preamble states: 18 part, 2 equations, 4 evaluable assembly,
4 data-gap assembly, 1 drawing, 5 advisory - 34 in total."""

_ID_CELL = re.compile(r"^`(rms\.[a-z0-9_.]+)`$")
_CODE_SPAN = re.compile(r"`([^`]+)`")


@dataclass(frozen=True)
class ContractRow:
    """One rule as `contracts/rules.md` states it."""

    rule_id: str
    scope: str
    severity: str | None
    statement: str
    coverage: tuple[str, str] | None


def _cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _prose(cell: str) -> str:
    """A statement cell as a reader should see it: markdown code spans unwrapped."""
    return cell.replace("`", "")


def _reason(cell: str) -> str:
    """A coverage reason cell: the first code span, without any parenthetical note."""
    match = _CODE_SPAN.search(cell)
    assert match is not None, f"coverage reason is not a code span: {cell!r}"
    return match.group(1)


def parse_contract(path: Path = CONTRACT) -> dict[str, ContractRow]:
    """Every `rms.*` row of the rule tables, keyed by rule id.

    Rows are recognised by their first cell being a backticked `rms.` id, so the
    suppress-test outcome table inside the part section contributes nothing.
    """
    rows: dict[str, ContractRow] = {}
    section = ""
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("#"):
            section = line.lstrip("#").strip()
            continue
        if not line.startswith("|"):
            continue
        cells = _cells(line)
        match = _ID_CELL.match(cells[0])
        if match is None:
            continue
        rule_id = match.group(1)
        assert rule_id not in rows, f"{rule_id} appears in two contract tables"
        for prefix, scope in EVALUABLE_SECTIONS.items():
            if section.startswith(prefix):
                rows[rule_id] = ContractRow(
                    rule_id=rule_id,
                    scope=scope,
                    severity=cells[1],
                    statement=_prose(cells[2]),
                    coverage=None,
                )
                break
        else:
            for prefix, bucket in COVERAGE_SECTIONS.items():
                if section.startswith(prefix):
                    rows[rule_id] = ContractRow(
                        rule_id=rule_id,
                        scope=cells[1],
                        severity=None,
                        statement=_prose(cells[2]),
                        coverage=(bucket, _reason(cells[3])),
                    )
                    break
            else:
                raise AssertionError(f"{rule_id} sits under an unknown section: {section!r}")
    return rows


CONTRACT_ROWS = parse_contract()


def test_the_contract_parser_read_the_whole_catalogue() -> None:
    """Guards the rest of the module: a broken parser must not weaken every assertion."""
    assert len(CONTRACT_ROWS) == 34
    assert CONTRACT_ROWS["rms.core.shell_last"] == ContractRow(
        rule_id="rms.core.shell_last",
        scope="part",
        severity="fail",
        statement="The shell is the last feature in Core.",
        coverage=None,
    )
    assert CONTRACT_ROWS["rms.assembly.subassemblies"].coverage == (
        "unresolved",
        "subassembly mates not extracted; assembly rules evaluated for the root document only",
    )
    assert CONTRACT_ROWS["rms.advisory.avoid_multibody"].coverage == (
        "out_of_scope",
        "judgement-only; body intent not decidable",
    )


class TestCatalogue:
    def test_exactly_the_contract_ids_are_registered(self) -> None:
        assert set(RULES) == set(CONTRACT_ROWS)
        assert len(RULES) == 34

    def test_every_rule_is_keyed_by_its_own_id(self) -> None:
        assert all(rule_id == rule.id for rule_id, rule in RULES.items())

    @pytest.mark.parametrize("rule_id", sorted(CONTRACT_ROWS))
    def test_scope_and_statement_match_the_contract(self, rule_id: str) -> None:
        rule, row = RULES[rule_id], CONTRACT_ROWS[rule_id]
        assert rule.scope == row.scope
        assert rule.statement == row.statement
        assert rule.statement.strip() != ""

    def test_counts_per_scope_match_the_contract_preamble(self) -> None:
        counts = {scope: len(rules) for scope, rules in by_scope().items()}
        assert counts == EXPECTED_PER_SCOPE
        assert sum(counts.values()) == 34


class TestEvaluableRules:
    def test_they_are_exactly_the_rules_the_contract_grades(self) -> None:
        graded = {row.rule_id for row in CONTRACT_ROWS.values() if row.severity is not None}
        assert {rule.id for rule in evaluable()} == graded
        assert len(graded) == 24

    @pytest.mark.parametrize(
        "rule_id",
        sorted(row.rule_id for row in CONTRACT_ROWS.values() if row.severity is not None),
    )
    def test_severity_statement_and_function_are_present(self, rule_id: str) -> None:
        rule = RULES[rule_id]
        assert rule.severity == CONTRACT_ROWS[rule_id].severity
        assert rule.severity in ("fail", "warn")
        assert rule.statement.strip() != ""
        assert callable(rule.fn)
        assert rule.coverage is None

    def test_four_of_the_eight_assembly_rules_are_evaluable(self) -> None:
        assembly = [rule for rule in evaluable() if rule.scope == "assembly"]
        assert len(assembly) == 4

    def test_no_drawing_or_advisory_rule_is_evaluable(self) -> None:
        assert not [rule for rule in evaluable() if rule.scope in ("drawing", "advisory")]


class TestCoverageOnlyRules:
    def test_they_are_exactly_the_rules_the_contract_does_not_grade(self) -> None:
        ungraded = {row.rule_id for row in CONTRACT_ROWS.values() if row.severity is None}
        assert {rule.id for rule in coverage_only()} == ungraded
        assert len(ungraded) == 10

    @pytest.mark.parametrize(
        "rule_id",
        sorted(row.rule_id for row in CONTRACT_ROWS.values() if row.severity is None),
    )
    def test_no_severity_no_function_and_the_contract_bucket_and_reason(
        self, rule_id: str
    ) -> None:
        rule = RULES[rule_id]
        assert rule.severity is None
        assert rule.fn is None
        assert rule.coverage == CONTRACT_ROWS[rule_id].coverage

    def test_the_buckets_split_four_data_gaps_from_six_out_of_scope_rules(self) -> None:
        buckets = [rule.coverage[0] for rule in coverage_only() if rule.coverage is not None]
        assert buckets.count("unresolved") == 4
        assert buckets.count("out_of_scope") == 6


class TestCoverageBuckets:
    """The registry names a subset of the session's buckets, and says so at import."""

    def test_the_rule_buckets_are_session_buckets(self) -> None:
        assert set(get_args(RuleCoverageBucket)) <= set(get_args(CoverageBucket))

    def test_the_rule_buckets_are_the_two_a_coverage_only_rule_can_land_in(self) -> None:
        assert set(get_args(RuleCoverageBucket)) == {"unresolved", "out_of_scope"}


class TestPartitions:
    def test_evaluable_and_coverage_only_partition_the_registry(self) -> None:
        ids = [rule.id for rule in evaluable()] + [rule.id for rule in coverage_only()]
        assert sorted(ids) == sorted(RULES)
        assert len(ids) == len(set(ids))

    def test_by_scope_partitions_the_registry(self) -> None:
        groups = by_scope()
        assert set(groups) == set(EXPECTED_PER_SCOPE)
        ids = [rule.id for rules in groups.values() for rule in rules]
        assert sorted(ids) == sorted(RULES)
        assert len(ids) == len(set(ids))

    def test_by_scope_groups_hold_only_their_own_scope(self) -> None:
        for scope, rules in by_scope().items():
            assert all(rule.scope == scope for rule in rules)

    def test_by_scope_returns_the_registered_objects(self) -> None:
        for rules in by_scope().values():
            assert all(rule is RULES[rule.id] for rule in rules)


class TestInvariant:
    """Data-model section 2: `fn` is present exactly when `severity` is present exactly
    when `coverage` is null - checked after `swreview.checks.rms` bound the evaluators."""

    @pytest.mark.parametrize("rule_id", sorted(CONTRACT_ROWS))
    def test_function_severity_and_coverage_agree(self, rule_id: str) -> None:
        rule = RULES[rule_id]
        assert (rule.fn is not None) == (rule.severity is not None)
        assert (rule.severity is not None) == (rule.coverage is None)


class TestBind:
    def test_an_unknown_rule_id_is_rejected(self) -> None:
        with pytest.raises(KeyError, match="rms.not.a.rule"):
            bind("rms.not.a.rule")(lambda: None)

    def test_a_coverage_only_rule_cannot_be_bound(self) -> None:
        with pytest.raises(ValueError, match="rms.advisory.core_shaping_cuts"):
            bind("rms.advisory.core_shaping_cuts")(lambda: None)

    def test_a_rule_cannot_be_bound_twice(self) -> None:
        with pytest.raises(ValueError, match="rms.core.shell_last"):
            bind("rms.core.shell_last")(lambda: None)

    def test_binding_returns_the_function_unchanged(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`RULES` is process-wide state, so the stand-in rule is installed through
        `monkeypatch`: a failure inside the test still leaves the catalogue as it was."""
        rule = RmsRule(
            id="rms.test.only",
            scope="part",
            severity="fail",
            statement="A rule that exists only in this test.",
        )
        monkeypatch.setitem(RULES, rule.id, rule)

        @bind(rule.id)
        def evaluator() -> str:
            return "evaluated"

        assert evaluator() == "evaluated"
        assert rule.fn is evaluator
