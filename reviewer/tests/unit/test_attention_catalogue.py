"""Every check id the product can emit has a consequence class, and no id it cannot (T023).

`test_attention_policy_file.py` pins the file's *shape*; this module pins its *coverage*,
in both directions, because each direction fails silently in its own way:

- **an id with no class sorts as `unclassified`.** The rule is total by design - key 3
  falls back rather than raising - so a check family added next month would rank between
  `manufacturing` and `discipline` with the reason "unclassified check `x.y`" and nobody
  would notice until an engineer asked why. This module is what notices (FR-011);
- **an id the product cannot emit is a decision about nothing.** A row for a rule that was
  renamed or removed reads as an opinion the owner holds, is carried forward on every edit
  of the table, and hides the fact that the real id is missing.

The catalogue is assembled from the registries and the check modules themselves rather
than from a list written down here, so a rule added to `checks/rms/registry.py` or a
sixteenth standards check renamed shows up as a red line in this file on the commit that
made the change, not later.

Seven sources, which is every place a `Finding.check` value can come from:

1. `checks/rms/registry.py` `RULES` - the resilient-modeling catalogue;
2. `checks/standards/registry.py` `RULES` - the sixteen release standards checks;
3. the deterministic numeric checks, each of which owns its id as a module constant:
   `interference.CHECK`, the five `fastener.CHECK_*`, `fit.CHECK`, `stack.CHECK`,
   `hole_alignment.CHECK`, and feature 010's `joint_alignment.CHECK_NOMINAL` and
   `CHECK_STACK`, `fastener_identity.CHECK_IDENTITY` and `tool_access.CHECK_HEAD_FIT`;
4. `tools/session.py` `DRAWING_FINDING_CHECK` - the one id `record_drawing_finding`
   accepts, which is fixed rather than caller-supplied;
5. feature 010's document rules, each a module constant: the three `mass.CHECK_*` and
   `hygiene.HYGIENE_CHECKS`;
6. feature 011's drawing standard comparison, `drawing_context.CONFORMANCE_CHECK`
   (`drawing_profile.conformance`; added deliberately by feature 011 T056);
7. feature 010's thread pitch check, `thread_pitch.CHECK_FINE_PITCH` and
   `CHECK_NONSTANDARD_PITCH` (added deliberately by the amendment of 2026-10-08, T119);
8. nothing else: `build_finding` is the one finding constructor, and every caller of it
   passes a `check` from one of the sources above.

This test lands **after** the read-through (T022): the table it checks is one the owner
has argued over folder by folder, not one a test invented.
"""

from __future__ import annotations

from swreview.checks import (
    fastener,
    fastener_identity,
    fit,
    hole_alignment,
    hygiene,
    interference,
    joint_alignment,
    mass,
    stack,
    thread_pitch,
    tool_access,
)
from swreview.checks.drawing_context import CONFORMANCE_CHECK
from swreview.checks.rms.registry import RULES as RMS_RULES
from swreview.checks.standards.registry import RULES as STANDARDS_RULES
from swreview.report.attention import load_policy
from swreview.tools.session import DRAWING_FINDING_CHECK

FASTENER_CHECKS: frozenset[str] = frozenset(
    {
        fastener.CHECK_BOTTOMING,
        fastener.CHECK_ENGAGEMENT,
        fastener.CHECK_THREAD_MATCH,
        fastener.CHECK_HEAD_CLEARANCE,
        fastener.CHECK_UNSUPPORTED,
    }
)
"""The five ids `checks/fastener.py` declares. Spelled out rather than scraped off the
module's namespace by prefix, so deleting one is a failure here rather than a set that
quietly shrank to match the table."""

NUMERIC_CHECKS: frozenset[str] = frozenset(
    {
        interference.CHECK,
        fit.CHECK,
        stack.CHECK,
        hole_alignment.CHECK,
        joint_alignment.CHECK_NOMINAL,
        joint_alignment.CHECK_STACK,
        fastener_identity.CHECK_IDENTITY,
        tool_access.CHECK_HEAD_FIT,
        *FASTENER_CHECKS,
    }
)


RULE_CHECKS: frozenset[str] = frozenset(
    {
        mass.CHECK_MATERIAL_ASSIGNED,
        mass.CHECK_DENSITY,
        mass.CHECK_ASSEMBLY_OVERRIDE,
        *hygiene.HYGIENE_CHECKS,
    }
)
"""Feature 010's document rules, each a module constant: the three `mass.` ids and the five
`hygiene.` ids. None is a judgement family - a material is assigned or it is not, a part
number is its file name or it is not."""


THREAD_CHECKS: frozenset[str] = frozenset(
    {thread_pitch.CHECK_FINE_PITCH, thread_pitch.CHECK_NONSTANDARD_PITCH}
)
"""Feature 010's thread pitch findings (the amendment of 2026-10-08, `contracts/fasteners.md`
section 8.4): a table lookup, and still a judgement family - only the engineer knows whether
a fine pitch was meant."""


def emittable() -> frozenset[str]:
    """Every `Finding.check` value this build can write, from the seven sources."""
    return frozenset(
        {
            *RMS_RULES,
            *STANDARDS_RULES,
            *NUMERIC_CHECKS,
            *RULE_CHECKS,
            *THREAD_CHECKS,
            DRAWING_FINDING_CHECK,
            CONFORMANCE_CHECK,
        }
    )


def test_the_five_sources_between_them_name_every_emittable_check() -> None:
    """A sanity line on the catalogue itself, so a source that silently emptied - an
    import that resolved to a different module, a registry built at call time - is caught
    before it makes the two coverage tests below pass for the wrong reason."""
    assert len(RMS_RULES) == 34
    assert len(STANDARDS_RULES) == 16
    assert len(NUMERIC_CHECKS) == 13, "9 until feature 010 T036, 11 until T046, 12 until T060"
    assert len(RULE_CHECKS) == 8, "feature 010's mass (T066) and hygiene (T074) rules"
    assert DRAWING_FINDING_CHECK == "drawing.manufacturing_inputs"
    assert CONFORMANCE_CHECK == "drawing_profile.conformance"
    assert len(THREAD_CHECKS) == 2, "the thread pitch amendment's two finding ids (T119)"
    assert len(emittable()) == 75, (
        "the sources share no id (60 before feature 010, 72 before feature 011 T056, 73 "
        "before the thread pitch amendment's T119)"
    )


def test_every_emittable_check_id_has_a_consequence_class() -> None:
    """FR-011. An id with no class ranks as `unclassified` and nobody is told."""
    unclassified = sorted(emittable() - set(load_policy().classes))

    assert unclassified == [], (
        "these ids can reach a finding and the policy gives them no class, so they would "
        "rank between manufacturing and discipline with no opinion behind the placement"
    )


def test_the_policy_names_no_id_the_product_cannot_emit() -> None:
    """The other direction: a class for a rule that was renamed or removed is an opinion
    about nothing, and it hides the fact that the real id is missing."""
    unreachable = sorted(set(load_policy().classes) - emittable())

    assert unreachable == [], (
        "these ids have a consequence class and no check can emit them; delete the row or "
        "correct the id rather than leaving a decision about nothing in the table"
    )


def test_the_needs_judgement_prefixes_each_match_at_least_one_emittable_id() -> None:
    """Key 2 is a prefix rule, so a prefix that matches nothing is dead text that reads as
    a family the engineer is asked to judge."""
    ids = emittable()
    policy = load_policy()

    unmatched = [
        prefix
        for prefix in policy.needs_judgement
        if not any(check.startswith(prefix) for check in ids)
    ]

    assert unmatched == []


def test_the_judgement_families_are_the_numeric_checks_except_the_axial_stack() -> None:
    """Which emittable ids key 2 actually lifts, named rather than left to a prefix scan.

    Twelve of the thirteen numeric checks: only the engineer knows whether an overlap is the
    intended press fit, which two dimensions are one interface, or what a screw clamps.
    `stack.worst_case` is the one that is not, and deliberately: the engineer states the
    stack - the dimensions, their signs and the target are arguments to the check - so once
    it is stated, the arithmetic settles it and there is nothing left to judge.

    And the two thread pitch ids (edited deliberately by the amendment of 2026-10-08, T119):
    the coarse pitch is a table lookup, not a calculation, yet it is a judgement family all the
    same, because the table cannot know whether a fine pitch was meant - only the engineer
    does, and the owner asked for every one to be confirmed (51A).
    """
    policy = load_policy()

    judgement = {check for check in emittable() if policy.needs_judgement_of(check)}

    assert judgement == (NUMERIC_CHECKS - {stack.CHECK}) | THREAD_CHECKS
