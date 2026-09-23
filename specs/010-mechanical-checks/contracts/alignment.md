# Contract: Alignment and the Stack-Up

Normative for FR-007 to FR-010 and User Story 3. `checks/joint_alignment.py`; the zone rule in
`checks/result.py`.

## 1. Nominal alignment (`hole.nominal_alignment`)

For each joint with at least two members (instances or an instance and a cylinder), with `F`
from `data-model.md` section 4 and research R2.5:

- `fixture = "fixed"` when the joint has a tapped instance, else `"floating"`.
- For each clearance-type instance `i` (clearance, counterbore bore, countersink bore):
  `term_i = (H_i - F) / 2`; a tapped instance contributes no term.
- `allowed = Σ term_i`; `offset` = the joint's `offset_mm`.

| Condition | Status | Severity |
|---|---|---|
| `F` unknown, or an `H_i` unknown | unresolved, naming it | medium |
| any `term_i < 0` | demonstrated: `"<F> mm fastener cannot pass <instance> (<H_i> mm)"` | high |
| `offset > allowed` (after rounding to `PLACES`) | demonstrated, both numbers | high |
| otherwise | checked within scope | info |

`Calculation.result`: `offset_mm`, `allowed_offset_mm`, `terms` (per instance), `fixture`,
`position_budget_mm = 2 * allowed`, `callout`. `inputs` cite every `H` and `F` with its source.
A line-to-line joint (`allowed == 0`) that passes adds the coverage limit
`"<joint> has no clearance: the fit is line to line and any position error prevents assembly"`.

## 2. The callout (FR-008)

| Fixture | `callout` |
|---|---|
| fixed | `"position ⌀<2·allowed> total at nominal size, to be shared between <clearance instance> and the tapped <instance> (fixed-fastener rule)"` |
| floating | `"position ⌀<H_i - F> at nominal size on each of <instances> (floating-fastener rule)"` |

When the stack-up resolved the sizes, the callout adds `"; ⌀<H_min - F_max> at maximum material"`.

## 3. The zone rule (FR-009)

`permitted_radial_offset_mm(zone_mm) -> zone_mm / 2`, one function. `hole.coaxiality` compares
its offset with it and records `zone_mm` (the tolerance value) and `permitted_offset_mm`;
`within_tolerance = offset_mm <= permitted_offset_mm`. The assumption line becomes `"the
tolerance value is a position or coaxiality zone; the axis may move half of it from true
position"`.

## 4. The stack-up (`hole.position_stack`)

Contributors: every clearance-type instance's size (`hole_size`), the fastener or pin size
(`pin_size`; for a screw the thread's nominal major diameter is `F_max` by the fixed-fastener
convention and needs no tolerance, `F_min` is not used), and every instance's position
(`hole_position`). Each is resolved through the `ToleranceLookup` (US3: `NoSources`; US8: the
resolver).

| Model | When | `z` |
|---|---|---|
| `size_and_position` | every contributor resolved | `Σ permitted_radial_offset_mm(zone_i)` |
| `size_only` | every size resolved, a position not | 0; `excluded_effects` names each unresolved position with its sources searched |
| unresolved | a size contributor has no source | - |

With `c_min = Σ (H_i,min - F_max)/2` and `c_max = Σ (H_i,max - F_min)/2` (for a screw
`F_min = F_max`, the nominal):

| Condition | Status |
|---|---|
| `max(0, e - z) > c_max` | demonstrated |
| `e + z <= c_min` | checked within scope |
| otherwise | suspected: `"passes at some sizes within tolerance and fails at others"` |
| unresolved model | unresolved: names the contributor and `searched` |

Every contributor's `ResolvedTolerance.cited` is in `inputs`, and `limits_mm` is the only reader
of a limit. When the package holds no tolerance source of any kind (no `wizard` class, no model
dimension, no annotation, no general block, no drawing), the tool records **one** `skipped`
coverage item `hole.position_stack` for all joints - `"no tolerance source is read for this
package; searched: <sources>"` - and no per-joint finding.

## 5. Folding

Per research R2.21: results with equal check, status, severity and `Calculation.result` within a
pattern group are one finding listing every joint id and instance id, with `"<n> joints"` in its
observed text.
