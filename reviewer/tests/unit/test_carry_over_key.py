"""The carry-over key, per finding (T104, lever 11a).

The key is the whole of the carry-over decision: what it covers is what a carried finding
claims has not moved. It is

    finding.check
    Calculation.function_version (when the finding carries a calculation)
    sorted(finding.component_ids)
    fingerprint(package, finding.component_ids, fingerprint_kind_for(finding.check))

followed by the four inputs guard 5 names that no fingerprint sees - the extractor
profile, a digest of the package's gap set, the checklist version and the rms rules'
`RULES_VERSION` - each with its own test in its own section below,

and **no second hashing scheme is written**: `exceptions.fingerprint` already does both
kinds and `exceptions.fingerprint_kind_for` already picks between them by the `rms.`
prefix. The tests below assert that by recomputing each part with those very functions and
finding it verbatim in the key, so a private re-implementation inside `carry_over.py`
would fail here rather than pass quietly. That is the DRY line to hold in code review.

The two invariants data-model.md section 10.5 names are pinned at the bottom: carried plus
re-run equals the total the previous session held, and every carried finding's
`carry_over_key` recomputes to the same value against the current package.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from swreview import carry_over
from swreview.agent.checklist import load_checklist
from swreview.carry_over import carry_over_key, select_carry_over
from swreview.checks.rms import RULES
from swreview.checks.rms.registry import RULES_VERSION
from swreview.exceptions import fingerprint, fingerprint_kind_for
from swreview.findings import Calculation
from swreview.ir.models import EvidencePackage, Gap, Quantity
from tests.support.carry_over import (
    CARRIED_AT,
    COMPONENT,
    OTHER_RMS_CHECK,
    RMS_CHECK,
    carry_package,
    mutated_package,
    previous_session,
    rms_finding,
)


def test_both_checks_under_test_are_registered_rules() -> None:
    """`carry_over.py` branches on the `rms.` prefix alone, so nothing in this module
    would notice a renamed or deleted rule; `contracts/rules.md` makes rule ids stable and
    verbatim in `Finding.check`, so a made-up id proves nothing about carry-over."""
    assert {RMS_CHECK, OTHER_RMS_CHECK} <= set(RULES)


# --- what the key is made of ----------------------------------------------------------


def test_the_key_carries_the_check_the_components_and_the_existing_fingerprint() -> None:
    """Every member, in order, so a new one cannot be added without saying so here."""
    package = carry_package()
    finding = rms_finding(package)

    key = carry_over_key(package, finding)

    digest = fingerprint(package, [COMPONENT], fingerprint_kind_for(RMS_CHECK))
    assert json.loads(key) == [
        RMS_CHECK,
        None,
        [COMPONENT],
        "feature_tree",
        digest,
        "full",
        gap_digest(package),
        load_checklist().version,
        RULES_VERSION,
    ]


def gap_digest(package: EvidencePackage) -> str:
    """The gap-set digest of `package`, recomputed the way the key does it.

    Spelled out here rather than imported, so the key's member 6 is checked against a
    statement of what it should be and not against the code that produced it.
    """
    rows = sorted(
        json.dumps(
            [gap.kind, gap.entity_kind, gap.entity_id, gap.reason],
            separators=(",", ":"),
            ensure_ascii=False,
        )
        for gap in package.gaps
    )
    return hashlib.sha256("\n".join(rows).encode("utf-8")).hexdigest()


def test_the_fingerprint_in_the_key_is_the_one_exceptions_computes() -> None:
    """The whole of `exceptions.fingerprint`'s output appears verbatim. A second hashing
    scheme - even one that hashed the same fields - would not produce this string."""
    package = carry_package()

    key = carry_over_key(package, rms_finding(package))

    assert fingerprint(package, [COMPONENT], "feature_tree") in key


def test_the_kind_is_chosen_by_fingerprint_kind_for_and_not_by_a_second_rule() -> None:
    package = carry_package()
    finding = rms_finding(package, check="interference.static")

    key = carry_over_key(package, finding)

    assert fingerprint_kind_for("interference.static") == "geometry"
    assert json.loads(key)[3] == "geometry"


def test_the_component_ids_are_sorted_so_the_order_they_arrived_in_cannot_move_the_key() -> None:
    package = carry_package()
    one = rms_finding(package, component_ids=(COMPONENT,))
    same = rms_finding(package, finding_id="F-002", component_ids=(COMPONENT,))

    assert carry_over_key(package, one) == carry_over_key(package, same)
    assert json.loads(carry_over_key(package, one))[2] == sorted([COMPONENT])


def test_a_calculation_puts_its_function_version_in_the_key() -> None:
    package = carry_package()
    finding = rms_finding(package)
    calculated = finding.model_copy(
        update={
            "calculation": Calculation(
                model="tree",
                inputs={"radius": Quantity(value=2.0, unit="mm")},
                assumptions=[],
                excluded_effects=[],
                result={"ok": False},
                units_out="mm",
                function="grade_tree",
                function_version="2.0.0",
            )
        }
    )

    assert json.loads(carry_over_key(package, calculated))[1] == "2.0.0"
    assert carry_over_key(package, calculated) != carry_over_key(package, finding)


def test_a_different_check_is_a_different_key() -> None:
    package = carry_package()

    assert carry_over_key(package, rms_finding(package)) != carry_over_key(
        package, rms_finding(package, check=OTHER_RMS_CHECK)
    )


def test_one_changed_feature_row_moves_the_key() -> None:
    """The premise of the whole lever: the feature-tree fingerprint moves when the tree
    does. `mutated_package` renames exactly one row."""
    finding = rms_finding(carry_package())

    assert carry_over_key(carry_package(), finding) != carry_over_key(mutated_package(), finding)


# --- the four inputs the fingerprint does not see (guard 5) ---------------------------


def re_runs(previous_package: EvidencePackage, current_package: EvidencePackage) -> bool:
    """Whether a finding computed over `previous_package` is re-run against `current`."""
    previous = previous_session(previous_package, [rms_finding(previous_package)])
    decision = select_carry_over(current_package, previous, at=CARRIED_AT)
    return decision.carried == () and len(decision.re_run) == 1


def test_the_extractor_profile_is_in_the_key() -> None:
    """A `model_check` package has empty `holes[]`, `fasteners[]`, `faces[]` and `bodies[]`
    **by design** (`Dump/PackageWriter.cs:200-235`), so a verdict computed over a `full`
    dump and one computed over a `model_check` dump are answers to different questions.
    Neither fingerprint sees the profile: `feature_tree` hashes feature rows and equations,
    `geometry` transforms and face parameters, and both are equally present in both dumps.
    """
    package = carry_package()
    other = package.model_copy(
        update={"extractor": package.extractor.model_copy(update={"profile": "model_check"})}
    )

    assert carry_over_key(package, rms_finding(package)) != carry_over_key(
        other, rms_finding(package)
    )
    assert re_runs(package, other)


def test_the_gap_set_is_in_the_key() -> None:
    """A gap is the extractor saying "this was not read". The same tree dumped once with
    every feature read and once with a phase that failed hashes to **different** trees only
    if the rows differ - a gap on a document whose rows came through unchanged does not move
    the fingerprint at all, and a rule that went unresolved on missing data would be carried
    as though the data had been there.
    """
    package = carry_package()
    other = package.model_copy(
        update={
            "gaps": [
                *package.gaps,
                Gap(
                    kind="unsupported",
                    entity_kind="document",
                    entity_id="doc:2",
                    reason="the feature tree could not be walked past row 2",
                    error=None,
                ),
            ]
        }
    )

    assert carry_over_key(package, rms_finding(package)) != carry_over_key(
        other, rms_finding(package)
    )
    assert re_runs(package, other)


def test_the_checklist_version_is_in_the_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """The run grades against `checklist_v1.yaml`, and a carried verdict is a claim about
    what a review of *this* checklist would conclude. The previous run's key records the
    version it graded under; nothing else in the session does.
    """
    package = carry_package()
    previous = previous_session(package, [rms_finding(package)])
    assert json.loads(previous.findings[0].carry_over_key)[7] == load_checklist().version

    monkeypatch.setattr(carry_over, "_checklist_version", lambda: 2)

    decision = select_carry_over(package, previous, at=CARRIED_AT)
    assert decision.carried == ()
    assert len(decision.re_run) == 1


def test_the_rms_rule_version_is_in_the_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """The check version, which `Calculation.function_version` cannot supply here: today's
    `rms.*` findings carry no calculation (`checks/rms/results.py`), so that slot is a
    constant null for every carryable finding and the rules' own `RULES_VERSION` is what
    says which implementation produced the verdict.
    """
    package = carry_package()
    previous = previous_session(package, [rms_finding(package)])
    assert json.loads(previous.findings[0].carry_over_key)[8] == RULES_VERSION

    monkeypatch.setattr(carry_over, "RULES_VERSION", "2")

    decision = select_carry_over(package, previous, at=CARRIED_AT)
    assert decision.carried == ()
    assert len(decision.re_run) == 1


def test_a_component_the_package_does_not_hold_raises_rather_than_re_binding() -> None:
    """`exceptions.fingerprint` raises `LookupError` rather than silently binding to
    whatever is left, and the key inherits that rather than catching it."""
    package = carry_package()
    finding = rms_finding(package).model_copy(update={"component_ids": ["cmp:9999"]})

    with pytest.raises(LookupError, match="cmp:9999"):
        carry_over_key(package, finding)


# --- the two invariants ---------------------------------------------------------------


def test_carried_plus_re_run_equals_every_finding_the_previous_session_held() -> None:
    package = carry_package()
    findings = [
        rms_finding(package, finding_id="F-001"),
        rms_finding(package, finding_id="F-002", check=OTHER_RMS_CHECK),
        rms_finding(package, finding_id="F-003", status="suspected"),
        rms_finding(package, finding_id="F-004", check="interference.static"),
    ]
    previous = previous_session(package, findings)

    decision = select_carry_over(package, previous, at=CARRIED_AT)

    assert decision.total == len(findings)
    assert len(decision.carried) == 2
    assert len(decision.re_run) == 2


def test_every_carried_key_recomputes_to_the_same_value_against_the_current_package() -> None:
    package = carry_package()
    previous = previous_session(package, [rms_finding(package)])

    decision = select_carry_over(package, previous, at=CARRIED_AT)

    assert decision.carried
    for carried in decision.carried:
        assert carried.key == carry_over_key(package, carried.finding)


def test_nothing_is_carried_from_a_previous_run_of_another_design() -> None:
    """The key would raise `LookupError` on the components, but the selector says no
    before that: a session about another design is not evidence about this one."""
    package = carry_package()
    previous = previous_session(package, [rms_finding(package)])
    previous.design_id = "dsn:other"

    decision = select_carry_over(package, previous, at=CARRIED_AT)

    assert decision.carried == ()
    assert decision.total == 1
