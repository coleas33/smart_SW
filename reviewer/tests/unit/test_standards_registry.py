"""The standards catalogue must say exactly what `contracts/rules.md` says (T021).

The registry is the single catalogue the evaluators, the report layer, the tool, the command
line and the tab read - never a second list - so the one thing worth asserting about it is
that it has not drifted from the contract. The contract's four scope tables are **parsed**
here rather than retyped: a check added, removed, renamed, re-scoped, re-worded or re-graded
in `contracts/rules.md` and not in the registry fails this module, and so does the reverse.
Even the expected counts and the two warning ids come from the contract's own preamble
sentences, so this file states no number the contract does not.

Two spellings differ by column and are normalised on the way in:

- a **severity** cell is `error` in the three model tables and `**error**` in the drawing
  table, where the contract bolds it to make the two warnings stand out; the emphasis is
  markdown, not vocabulary;
- a **statement** cell is the prose a finding reports as its requirement, so a code span
  inside it is unwrapped exactly as feature 003's registry test unwraps one.

`standards.release` is asserted **absent**: it is the family's summary coverage item and not
a seventeenth check (`contracts/rules.md`, data-model section 3).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import get_args

import pytest

import swreview.checks.standards  # noqa: F401  - importing it is what binds the evaluators
from swreview.checks.rules.family import WAIVABLE_STATUS
from swreview.checks.rules.registry import binder, catalogue, coverage_only, evaluable
from swreview.checks.standards.registry import (
    RULES,
    RULES_VERSION,
    STANDARDS_FAMILY,
    RuleScope,
    RuleSeverity,
    StandardsRule,
    by_scope,
    rules_in,
)
from tests.support.contracts import REPO_ROOT

CONTRACT = REPO_ROOT / "specs" / "006-standards-check" / "contracts" / "rules.md"

SCOPE_SECTIONS: dict[str, str] = {
    "Assembly scope": "assembly",
    "Part scope": "part",
    "Drawing scope": "drawing",
    "Document scope": "document",
}
"""Heading prefix of each table of checks, and the scope every row under it declares."""

NUMBER_WORDS: dict[str, int] = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "fourteen": 14,
    "sixteen": 16,
}
"""Enough of the contract's counting words to read its preamble. A word it uses and this
map does not hold fails the parser guard rather than being read as zero."""

HIGH_SEVERITY = frozenset(
    {
        "standards.assembly.mate_references",
        "standards.assembly.rebuild_errors",
        "standards.part.rebuild_errors",
        "standards.drawing.dimensions_not_overridden",
    }
)
"""The four data-integrity checks reported `high` rather than `medium` (data-model
section 3, "Severity, outcome and finding mapping")."""

_ID_CELL = re.compile(r"^`(standards\.[a-z0-9_.]+)`$")
_CODE_SPAN = re.compile(r"`([^`]+)`")
_PER_SCOPE = re.compile(r"([a-z]+) (assembly|part|drawing|document)-scope")
_TOTAL = re.compile(r"([A-Za-z]+) ids:(.+?)\.", re.DOTALL)
_WARNING_SENTENCE = re.compile(r"\*\*warning\*\* for\s+(.+?)\.\s", re.DOTALL)
_ERROR_COUNT = re.compile(r"\*\*error\*\* for ([a-z]+),")


@dataclass(frozen=True)
class ContractRow:
    """One check as `contracts/rules.md` states it."""

    check_id: str
    scope: str
    severity: str
    statement: str


def _cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _severity(cell: str) -> str:
    """A severity cell as vocabulary: the drawing table's bold emphasis dropped."""
    return cell.replace("*", "").strip()


def _prose(cell: str) -> str:
    """A statement cell as a reader should see it: markdown code spans unwrapped."""
    return cell.replace("`", "")


def parse_contract(path: Path = CONTRACT) -> dict[str, ContractRow]:
    """Every `standards.*` row of the four scope tables, keyed by check id."""
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
        check_id = match.group(1)
        assert check_id not in rows, f"{check_id} appears in two contract tables"
        for prefix, scope in SCOPE_SECTIONS.items():
            if section.startswith(prefix):
                rows[check_id] = ContractRow(
                    check_id=check_id,
                    scope=scope,
                    severity=_severity(cells[1]),
                    statement=_prose(cells[2]),
                )
                break
        else:
            raise AssertionError(f"{check_id} sits under an unknown section: {section!r}")
    return rows


def parse_preamble(path: Path = CONTRACT) -> tuple[int, dict[str, int], frozenset[str]]:
    """The contract's own counts and its two warning ids, read from its prose.

    Three sentences carry them - "Sixteen ids: seven assembly-scope, ...", "**error** for
    fourteen, **warning** for `x` and `y`" - and reading them here is what keeps this file
    from stating a number of its own that the contract could drift away from.
    """
    text = path.read_text(encoding="utf-8")

    counted = _TOTAL.search(text)
    assert counted is not None, "the preamble no longer states a total"
    total = NUMBER_WORDS[counted.group(1).lower()]

    per_scope = {
        scope: NUMBER_WORDS[word.lower()]
        for word, scope in _PER_SCOPE.findall(counted.group(2))
    }
    assert set(per_scope) == set(SCOPE_SECTIONS.values()), (
        f"the preamble no longer counts every scope: {sorted(per_scope)}"
    )

    sentence = _WARNING_SENTENCE.search(text)
    assert sentence is not None, "the preamble no longer names the warning checks"
    warnings = frozenset(_CODE_SPAN.findall(sentence.group(1)))

    errors = _ERROR_COUNT.search(text)
    assert errors is not None, "the preamble no longer counts the error checks"
    assert NUMBER_WORDS[errors.group(1).lower()] + len(warnings) == total

    return total, per_scope, warnings


CONTRACT_ROWS = parse_contract()
TOTAL, PER_SCOPE, WARNING_CHECKS = parse_preamble()


def test_the_contract_parser_read_the_whole_catalogue() -> None:
    """Guards the rest of the module: a broken parser must not weaken every assertion."""
    assert len(CONTRACT_ROWS) == 16
    assert CONTRACT_ROWS["standards.assembly.not_exploded"] == ContractRow(
        check_id="standards.assembly.not_exploded",
        scope="assembly",
        severity="error",
        statement="An assembly is not left in an exploded state.",
    )
    assert CONTRACT_ROWS["standards.drawing.revision_matches"].severity == "warning"
    assert CONTRACT_ROWS["standards.document.data_card_complete"].scope == "document"


def test_the_preamble_states_the_counts_this_module_asserts() -> None:
    assert TOTAL == 16
    assert PER_SCOPE == {"assembly": 7, "part": 4, "drawing": 4, "document": 1}
    assert sum(PER_SCOPE.values()) == TOTAL
    assert WARNING_CHECKS == {
        "standards.drawing.revision_matches",
        "standards.drawing.no_itar_statement",
    }


class TestCatalogue:
    def test_exactly_the_contract_ids_are_registered(self) -> None:
        assert set(RULES) == set(CONTRACT_ROWS)
        assert len(RULES) == TOTAL

    def test_every_check_is_keyed_by_its_own_id(self) -> None:
        assert all(check_id == rule.id for check_id, rule in RULES.items())

    @pytest.mark.parametrize("check_id", sorted(CONTRACT_ROWS))
    def test_scope_and_statement_match_the_contract(self, check_id: str) -> None:
        rule, row = RULES[check_id], CONTRACT_ROWS[check_id]
        assert rule.scope == row.scope
        assert rule.statement == row.statement
        assert rule.statement.strip() != ""

    def test_the_catalogue_is_in_contract_order(self) -> None:
        """A report that walks the catalogue reads in the order an engineer reviewed it."""
        assert list(RULES) == list(CONTRACT_ROWS)

    def test_counts_per_scope_match_the_contract_preamble(self) -> None:
        counts = {scope: len(rules) for scope, rules in by_scope().items()}
        assert counts == PER_SCOPE
        assert sum(counts.values()) == TOTAL

    def test_by_scope_partitions_the_catalogue(self) -> None:
        partition = by_scope()
        assert set(partition) == set(get_args(RuleScope)) == STANDARDS_FAMILY.scopes
        assert [rule.id for rules in partition.values() for rule in rules] != []
        assert {rule.id for rules in partition.values() for rule in rules} == set(RULES)
        for scope, rules in partition.items():
            assert all(rule.scope == scope for rule in rules)
            assert [rule.id for rule in rules] == [
                check_id for check_id, row in CONTRACT_ROWS.items() if row.scope == scope
            ]


class TestSeverity:
    @pytest.mark.parametrize("check_id", sorted(CONTRACT_ROWS))
    def test_severity_matches_the_contract(self, check_id: str) -> None:
        assert RULES[check_id].severity == CONTRACT_ROWS[check_id].severity

    def test_the_two_warning_checks_are_the_two_the_contract_names(self) -> None:
        warned = {rule.id for rule in RULES.values() if rule.severity == "warning"}
        assert warned == WARNING_CHECKS

    def test_the_other_fourteen_are_errors(self) -> None:
        errored = {rule.id for rule in RULES.values() if rule.severity == "error"}
        assert errored == set(RULES) - WARNING_CHECKS
        assert len(errored) == 14

    def test_no_severity_outside_this_family_s_vocabulary(self) -> None:
        assert set(get_args(RuleSeverity)) == STANDARDS_FAMILY.severities == {"error", "warning"}
        assert {rule.severity for rule in RULES.values()} <= STANDARDS_FAMILY.severities


class TestTheRuleInvariant:
    """A severity xor a coverage reason - and all sixteen carry a severity."""

    @pytest.mark.parametrize("check_id", sorted(CONTRACT_ROWS))
    def test_every_check_carries_a_severity_and_no_coverage_reason(self, check_id: str) -> None:
        rule = RULES[check_id]
        assert rule.severity is not None
        assert rule.coverage is None

    def test_this_family_has_no_coverage_only_check(self) -> None:
        assert coverage_only(RULES) == ()
        assert {rule.id for rule in evaluable(RULES)} == set(RULES)

    def test_a_check_carrying_both_is_refused(self) -> None:
        with pytest.raises(ValueError, match="never both and never neither"):
            StandardsRule(
                id="standards.assembly.invented",
                scope="assembly",
                statement="Invented.",
                severity="error",
                coverage=("unresolved", "invented"),
            )

    def test_a_check_carrying_neither_is_refused(self) -> None:
        with pytest.raises(ValueError, match="never both and never neither"):
            StandardsRule(id="standards.assembly.invented", scope="assembly", statement="I.")

    def test_a_check_with_no_statement_is_refused(self) -> None:
        with pytest.raises(ValueError, match="needs a statement"):
            StandardsRule(
                id="standards.assembly.invented", scope="assembly", statement=" ", severity="error"
            )


class TestEvaluators:
    """Every one of the sixteen is dispatched, so every one of them takes an evaluator.

    The evaluators themselves are bound by `checks/standards/{assembly,part,drawing,
    document}.py`, which land with their own checks; what the catalogue owes them is an
    id that binds and a statement to report, and that is what is asserted here over a
    **copy** of the catalogue, so this module leaves no evaluator bound in the real one.
    """

    def test_binding_every_id_completes_the_catalogue(self) -> None:
        copies = catalogue(*(replace(rule, fn=None) for rule in RULES.values()))
        bind = binder(copies, "contracts/rules.md")
        for check_id in copies:
            bind(check_id)(lambda *args, **kwargs: [])
        assert all(callable(rule.fn) for rule in copies.values())
        assert all(rule.statement.strip() for rule in copies.values())

    def test_an_id_the_catalogue_does_not_hold_is_refused(self) -> None:
        copies = catalogue(*(replace(rule) for rule in RULES.values()))
        bind = binder(copies, "contracts/rules.md")
        with pytest.raises(KeyError, match="contracts/rules.md"):
            bind("standards.release")(lambda *args, **kwargs: [])


class TestRulesIn:
    """`rules_in` is what the four scope entry points walk (T099).

    Each of `checks/standards/{assembly,part,drawing,document}.py` used to hold its own copy
    of "the checks of my scope, and each of them has a function to call". The invariant now
    lives here, so these assertions are the four copies' replacement rather than an addition
    to them.
    """

    @pytest.mark.parametrize("scope", sorted(get_args(RuleScope)))
    def test_it_is_the_scope_s_partition_with_every_evaluator_bound(self, scope: str) -> None:
        rules = rules_in(scope)
        assert rules == by_scope()[scope]
        assert all(callable(rule.fn) for rule in rules)

    def test_the_four_scopes_together_are_the_whole_catalogue(self) -> None:
        walked = [rule.id for scope in get_args(RuleScope) for rule in rules_in(scope)]
        assert sorted(walked) == sorted(RULES)

    def test_a_check_with_no_evaluator_refuses_the_scope_before_any_of_it_runs(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Naming the check, and before the scope's first check is dispatched: a scope
        entry point that graded the rest would grade a document against fifteen."""
        unbound = "standards.part.rebuild_errors"
        monkeypatch.setattr(RULES[unbound], "fn", None)
        with pytest.raises(ValueError, match=unbound):
            rules_in("part")

    def test_a_scope_this_family_does_not_have_is_a_key_error(self) -> None:
        with pytest.raises(KeyError):
            rules_in("equations")


class TestTheFamily:
    def test_it_names_itself_the_standards_family(self) -> None:
        assert STANDARDS_FAMILY.name == "standards"
        assert STANDARDS_FAMILY.check_file_family == "standards"

    def test_the_summary_check_is_standards_release(self) -> None:
        assert STANDARDS_FAMILY.summary_check == "standards.release"

    def test_standards_release_is_not_one_of_the_sixteen(self) -> None:
        assert STANDARDS_FAMILY.summary_check not in RULES
        assert not any(rule.id == "standards.release" for rule in RULES.values())

    def test_the_scopes_are_the_four_the_contract_tables_declare(self) -> None:
        assert STANDARDS_FAMILY.scopes == frozenset(SCOPE_SECTIONS.values())

    def test_every_scope_is_dispatched_as_a_tool(self) -> None:
        """One review-only tool runs the whole check, so every scope names that one."""
        assert set(STANDARDS_FAMILY.tools) == STANDARDS_FAMILY.scopes
        assert len(set(STANDARDS_FAMILY.tools.values())) == 1

    def test_error_is_demonstrated_and_warning_is_suspected(self) -> None:
        assert STANDARDS_FAMILY.status_by_severity == {
            "error": ("demonstrated", "medium"),
            "warning": ("suspected", "low"),
        }

    def test_only_the_error_checks_are_waivable(self) -> None:
        waivable = {
            severity
            for severity, (status, _) in STANDARDS_FAMILY.status_by_severity.items()
            if status == WAIVABLE_STATUS
        }
        assert waivable == {"error"}

    def test_the_waiver_labels_are_the_two_the_command_line_prints(self) -> None:
        assert STANDARDS_FAMILY.waiver_labels == {
            "unknown": "invalid (unknown check)",
            "warning": "invalid (warning check)",
        }

    def test_the_four_data_integrity_checks_are_high_severity(self) -> None:
        assert STANDARDS_FAMILY.high_severity == HIGH_SEVERITY
        assert HIGH_SEVERITY <= set(RULES)

    def test_the_rules_version_is_the_catalogue_s_own(self) -> None:
        assert STANDARDS_FAMILY.rules_version == RULES_VERSION
        assert RULES_VERSION.strip() != ""
