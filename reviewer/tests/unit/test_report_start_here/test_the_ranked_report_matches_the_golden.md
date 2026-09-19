# Design Review Report: dsn:1

- Session: 6f1c0a2e-9b6d-4a51-9f30-0b1f5a7c2d10
- Model: gpt-fixture
- Provider: openai (effort high sent as reasoning.effort=high; key from env)
- Started: 2026-09-18T21:57:55+00:00
- Ended: 2026-09-18T21:59:32+00:00

## Manifest Discrepancies

No discrepancies between the manifest and the reviewed documents.

## Summary

- Total findings: 8
- By status: demonstrated: 6, suspected: 2
- By severity: low: 2, medium: 6
- Open evidence requests: 3 of 3
- Coverage: Checked: 5, Skipped: 11, Unresolved: 39, Failed: 0, Out of Scope: 7

## Start here

1. **F-007** `interference.static` - needs your judgement (Static interference between the housing and the second pin)
2. **F-008** `interference.static` - needs your judgement (Static interference between the housing and the first pin)
3. **F-004** `rms.assembly.mates_to_reference_geometry` - rebuild breaker, demonstrated
4. **F-003** `rms.sketches.fully_defined` - rebuild breaker, demonstrated
5. **F-002** `rms.grouping.all_features_in_a_group` - discipline, demonstrated

Not amplified: 3 findings (0 checked within scope, 0 already decided, 0 informational, 3 beyond the top five).

What this run could not reach: 39 unresolved, 11 skipped, 0 failed, 7 out of scope.
- fasteners: list_fasteners returned zero instances, so no screw or bolt joint could be checked.
- holes.alignment: no hole was extracted from either pin, so no coaxial pair could be checked.
- interfaces.fit: pin geometry was not extracted, so the dowel fit could not be computed.
- interfaces.stack: no drawing dimensions, target gap or stack contributors were extracted.
- drawing.manufacturing_inputs: no drawing documents or sheets were included.
- 3 evidence requests are still open; 28 rules unresolved and 11 skipped.

Ranked by attention_policy_v1; the rule is in reviewer/src/swreview/report/attention.py.

## Findings

### Medium

#### F-002: Content features sit outside every group

- Check: rms.grouping.all_features_in_a_group
- Status: demonstrated
- Severity: medium
- Configuration: Default
- Components: cmp:0003 (cover-assy-1/housing-1)
- Drawing locations: document doc:2; document doc:2
- Provenance:

  | Document | Vault Path | Version | Revision | Configuration |
  |---|---|---|---|---|
  | doc:2 | /Designs/housing.SLDPRT | 3 | A | Default |
- Observed: two content features of housing-1 sit outside any group folder.
- Requirement: Every content feature lives inside a group.
- Inputs: none
- Calculation: no calculation
- Tool result steps: 0
- Coverage limits: none
- Recommended action: move both features into the group their intent belongs to.
- Group: none
- Captures: none
- Disposition: not yet dispositioned
- Exception: none
- Navigation: swreview://open?doc=doc:2&ref=Y21wOjAwMDM=

#### F-003: An under-defined sketch drives a Core feature

- Check: rms.sketches.fully_defined
- Status: demonstrated
- Severity: medium
- Configuration: Default
- Components: cmp:0003 (cover-assy-1/housing-1)
- Drawing locations: document doc:2
- Provenance:

  | Document | Vault Path | Version | Revision | Configuration |
  |---|---|---|---|---|
  | doc:2 | /Designs/housing.SLDPRT | 3 | A | Default |
- Observed: one sketch of housing-1 is under defined.
- Requirement: Every sketch is fully defined. Only under_defined fails.
- Inputs: none
- Calculation: no calculation
- Tool result steps: 0
- Coverage limits: none
- Recommended action: fully define the sketch before the geometry is relied on.
- Group: none
- Captures: none
- Disposition: not yet dispositioned
- Exception: none
- Navigation: swreview://open?doc=doc:2&ref=Y21wOjAwMDM=

#### F-004: Two mates reference faces rather than reference geometry

- Check: rms.assembly.mates_to_reference_geometry
- Status: demonstrated
- Severity: medium
- Configuration: Default
- Components: cmp:0001 (cover-assy-1)
- Provenance:

  | Document | Vault Path | Version | Revision | Configuration |
  |---|---|---|---|---|
  | doc:1 | /Designs/cover-assy.SLDASM | 7 | B | Default |
- Observed: two mates of the root assembly reference a face of housing-1 and a face of dowel-pin-1.
- Requirement: Mates reference planes, axes, points, or coordinate systems, not faces, edges, or vertices.
- Inputs:
  - housing-1
  - dowel-pin-1
- Calculation: no calculation
- Tool result steps: 1
- Coverage limits: none
- Recommended action: remate both to planes or axes so an edit cannot orphan them.
- Group: none
- Captures: none
- Disposition: not yet dispositioned
- Exception: none
- Navigation: swreview://open?doc=doc:1&ref=Y21wOjAwMDE=

#### F-005: The part declares no global variable

- Check: rms.params.global_variables_present
- Status: demonstrated
- Severity: medium
- Configuration: Default
- Components: cmp:0003 (cover-assy-1/housing-1)
- Provenance:

  | Document | Vault Path | Version | Revision | Configuration |
  |---|---|---|---|---|
  | doc:2 | /Designs/housing.SLDPRT | 3 | A | Default |
- Observed: housing-1 declares no global variable.
- Requirement: At least one global variable exists.
- Inputs: none
- Calculation: no calculation
- Tool result steps: 2
- Coverage limits: none
- Recommended action: name the driving sizes as global variables.
- Group: none
- Captures: none
- Disposition: not yet dispositioned
- Exception: none
- Navigation: swreview://open?doc=doc:2&ref=Y21wOjAwMDM=

#### F-007: Static interference between the housing and the second pin

- Check: interference.static
- Status: demonstrated
- Severity: medium
- Configuration: Default
- Components: cmp:0003 (cover-assy-1/housing-1), cmp:0004 (cover-assy-1/dowel-pin-2)
- Provenance:

  | Document | Vault Path | Version | Revision | Configuration |
  |---|---|---|---|---|
  | doc:2 | /Designs/housing.SLDPRT | 3 | A | Default |
  | doc:3 | /Designs/dowel-pin.SLDPRT | 2 | A | Default |
- Observed: housing-1 and dowel-pin-2 overlap by 0.8 mm^3 in the Default configuration.
- Requirement: Components do not occupy the same volume unless the fit is intended.
- Inputs:
  - housing-1
  - dowel-pin-2
- Calculation:
  - model: interference.static
  - inputs: configuration=Default, pair=cmp:0003 and cmp:0004, volume_as_reported=0.8 mm^3
  - assumptions: the pins are modelled at nominal diameter
  - excluded effects: thermal expansion; press-fit deformation
  - result: member_count=2.0, max_volume_mm3=0.8
  - units_out: mm^3
  - function: swreview.checks.interference.static (version 1)
- Tool result steps: none
- Coverage limits: measured in the Default configuration only.
- Recommended action: confirm whether the overlap is the intended press fit, or open the bore.
- Group: none
- Captures: none
- Disposition: not yet dispositioned
- Exception: none
- Navigation: swreview://open?doc=doc:2&ref=Y21wOjAwMDM=

#### F-008: Static interference between the housing and the first pin

- Check: interference.static
- Status: demonstrated
- Severity: medium
- Configuration: Default
- Components: cmp:0002 (cover-assy-1/dowel-pin-1), cmp:0003 (cover-assy-1/housing-1)
- Provenance:

  | Document | Vault Path | Version | Revision | Configuration |
  |---|---|---|---|---|
  | doc:3 | /Designs/dowel-pin.SLDPRT | 2 | A | Default |
  | doc:2 | /Designs/housing.SLDPRT | 3 | A | Default |
- Observed: housing-1 and dowel-pin-1 overlap by 0.5 mm^3 in the Default configuration.
- Requirement: Components do not occupy the same volume unless the fit is intended.
- Inputs:
  - housing-1
  - dowel-pin-1
- Calculation:
  - model: interference.static
  - inputs: configuration=Default, pair=cmp:0003 and cmp:0002, volume_as_reported=0.5 mm^3
  - assumptions: the pins are modelled at nominal diameter
  - excluded effects: thermal expansion; press-fit deformation
  - result: member_count=2.0, max_volume_mm3=0.5
  - units_out: mm^3
  - function: swreview.checks.interference.static (version 1)
- Tool result steps: none
- Coverage limits: measured in the Default configuration only.
- Recommended action: confirm whether the overlap is the intended press fit, or open the bore.
- Group: none
- Captures: none
- Disposition: not yet dispositioned
- Exception: none
- Navigation: swreview://open?doc=doc:3&ref=Y21wOjAwMDI=

### Low

#### F-001: Three of the six groups are missing from the part tree

- Check: rms.folders.present
- Status: suspected
- Severity: low
- Configuration: Default
- Components: cmp:0003 (cover-assy-1/housing-1)
- Provenance:

  | Document | Vault Path | Version | Revision | Configuration |
  |---|---|---|---|---|
  | doc:2 | /Designs/housing.SLDPRT | 3 | A | Default |
- Observed: housing-1 carries three of the six groups as folders.
- Requirement: Every one of the six groups exists as a folder.
- Inputs: none
- Calculation: no calculation
- Tool result steps: 0
- Coverage limits: none
- Recommended action: add the missing group folders before the next release.
- Group: none
- Captures: none
- Disposition: not yet dispositioned
- Exception: none
- Navigation: swreview://open?doc=doc:2&ref=Y21wOjAwMDM=

#### F-006: No dimension is driven by an equation

- Check: rms.params.dimensions_driven_by_equations
- Status: suspected
- Severity: low
- Configuration: Default
- Components: cmp:0003 (cover-assy-1/housing-1)
- Provenance:

  | Document | Vault Path | Version | Revision | Configuration |
  |---|---|---|---|---|
  | doc:2 | /Designs/housing.SLDPRT | 3 | A | Default |
- Observed: no dimension of housing-1 is driven by an equation.
- Requirement: At least one dimension is driven by an equation.
- Inputs: none
- Calculation: no calculation
- Tool result steps: 2
- Coverage limits: none
- Recommended action: drive the sizes that must move together from one equation.
- Group: none
- Captures: none
- Disposition: not yet dispositioned
- Exception: none
- Navigation: swreview://open?doc=doc:2&ref=Y21wOjAwMDM=


## Evidence Requests

| ID | What | Why | Entity IDs | Status | Answer | Answered At |
|---|---|---|---|---|---|---|
| ER-001 | The vault version and the local-modification state of every reviewed document | provenance cannot be confirmed from the manifest as dumped | doc:1, doc:2, doc:3 | open |  |  |
| ER-002 | A part drawing for the housing carrying material, tolerance and thread notes | drawing.manufacturing_inputs has no sheet to read | doc:2 | open |  |  |
| ER-003 | The pin geometry and the hole each pin seats in | interfaces.fit and holes.alignment cannot be computed without them | cmp:0002, cmp:0004 | open |  |  |

## Coverage

### Checked

| Check | Scope | Reason | Error |
|---|---|---|---|
| rms.refs.direction | configuration: Default; documents: doc:2 | 1 document(s) |  |
| rms.intent.every_feature_described | configuration: Default; documents: doc:2 | 1 document(s) |  |
| rms.sketches.not_over_defined | configuration: Default; documents: doc:2 | 1 document(s) |  |
| rms.sketches.one_sketch_per_feature | configuration: Default; documents: doc:2 | 1 document(s) |  |
| rms.assembly.first_component_fixed | configuration: Default; documents: doc:1 | 1 document(s) |  |

### Skipped

| Check | Scope | Reason | Error |
|---|---|---|---|
| rms.folders.ordered | configuration: Default; documents: doc:2 | 1 document(s): doc:2: fewer than two groups. |  |
| rms.groups.no_solids_in_ref_or_construction | configuration: Default; documents: doc:2 | 1 document(s): doc:2: no Reference or Construction group. |  |
| rms.core.shell_last | configuration: Default; documents: doc:2 | 1 document(s): doc:2: no Core group. |  |
| rms.detail.holes_last | configuration: Default; documents: doc:2 | 1 document(s): doc:2: no Detail group. |  |
| rms.detail.no_internal_references | configuration: Default; documents: doc:2 | 1 document(s): doc:2: no Detail group. |  |
| rms.detail.individually_suppressible | configuration: Default; documents: doc:2 | 1 document(s): doc:2: no Detail group. |  |
| rms.modify.transform_before_replicate | configuration: Default; documents: doc:2 | 1 document(s): doc:2: no Modify group. |  |
| rms.quarantine.chamfers_before_fillets | configuration: Default; documents: doc:2 | 1 document(s): doc:2: no Quarantine group. |  |
| rms.quarantine.largest_fillet_first | configuration: Default; documents: doc:2 | 1 document(s): doc:2: no Quarantine group. |  |
| rms.quarantine.only_fillets_and_chamfers | configuration: Default; documents: doc:2 | 1 document(s): doc:2: no Quarantine group. |  |
| rms.refs.quarantine_has_no_children | configuration: Default; documents: doc:2 | 1 document(s): doc:2: no Quarantine group. |  |

### Unresolved

| Check | Scope | Reason | Error |
|---|---|---|---|
| rms.folders.present | configuration: Default; documents: doc:3 | 1 document(s): doc:3: both pin instances are lightweight, so the tree was not read. |  |
| rms.folders.ordered | configuration: Default; documents: doc:3 | 1 document(s): doc:3: both pin instances are lightweight, so the tree was not read. |  |
| rms.grouping.all_features_in_a_group | configuration: Default; documents: doc:3 | 1 document(s): doc:3: both pin instances are lightweight, so the tree was not read. |  |
| rms.groups.no_solids_in_ref_or_construction | configuration: Default; documents: doc:3 | 1 document(s): doc:3: both pin instances are lightweight, so the tree was not read. |  |
| rms.core.shell_last | configuration: Default; documents: doc:3 | 1 document(s): doc:3: both pin instances are lightweight, so the tree was not read. |  |
| rms.detail.holes_last | configuration: Default; documents: doc:3 | 1 document(s): doc:3: both pin instances are lightweight, so the tree was not read. |  |
| rms.modify.transform_before_replicate | configuration: Default; documents: doc:3 | 1 document(s): doc:3: both pin instances are lightweight, so the tree was not read. |  |
| rms.quarantine.chamfers_before_fillets | configuration: Default; documents: doc:3 | 1 document(s): doc:3: both pin instances are lightweight, so the tree was not read. |  |
| rms.quarantine.largest_fillet_first | configuration: Default; documents: doc:3 | 1 document(s): doc:3: both pin instances are lightweight, so the tree was not read. |  |
| rms.quarantine.only_fillets_and_chamfers | configuration: Default; documents: doc:3 | 1 document(s): doc:3: both pin instances are lightweight, so the tree was not read. |  |
| rms.refs.direction | configuration: Default; documents: doc:3 | 1 document(s): doc:3: both pin instances are lightweight, so the tree was not read. |  |
| rms.refs.quarantine_has_no_children | configuration: Default; documents: doc:3 | 1 document(s): doc:3: both pin instances are lightweight, so the tree was not read. |  |
| rms.detail.no_internal_references | configuration: Default; documents: doc:3 | 1 document(s): doc:3: both pin instances are lightweight, so the tree was not read. |  |
| rms.intent.every_feature_described | configuration: Default; documents: doc:3 | 1 document(s): doc:3: both pin instances are lightweight, so the tree was not read. |  |
| rms.sketches.fully_defined | configuration: Default; documents: doc:3 | 1 document(s): doc:3: both pin instances are lightweight, so the tree was not read. |  |
| rms.sketches.not_over_defined | configuration: Default; documents: doc:3 | 1 document(s): doc:3: both pin instances are lightweight, so the tree was not read. |  |
| rms.sketches.one_sketch_per_feature | configuration: Default; documents: doc:3 | 1 document(s): doc:3: both pin instances are lightweight, so the tree was not read. |  |
| rms.detail.individually_suppressible | configuration: Default; documents: doc:3 | 1 document(s): doc:3: both pin instances are lightweight, so the tree was not read. |  |
| rms.params.global_variables_present | configuration: Default; documents: doc:3 | 1 document(s): doc:3: both pin instances are lightweight, so the tree was not read. |  |
| rms.params.dimensions_driven_by_equations | configuration: Default; documents: doc:3 | 1 document(s): doc:3: both pin instances are lightweight, so the tree was not read. |  |
| rms.assembly.mates_to_reference_geometry | configuration: Default; documents: doc:1 | 1 document(s): doc:1: one mate's entity kinds could not be read. |  |
| rms.assembly.mate_chain_depth | configuration: Default; documents: doc:1 | 1 document(s): doc:1: no fixed child of the root assembly. |  |
| rms.assembly.toolbox_parts_not_configurations | configuration: Default; documents: doc:1 | 1 document(s): doc:1: toolbox identity not readable. |  |
| rms.assembly.no_sibling_in_context_refs | configuration: Default; documents: doc:1 | external references not extracted |  |
| rms.assembly.positions_driven_by_globals | configuration: Default; documents: doc:1 | assembly equations not extracted |  |
| rms.assembly.mates_described | configuration: Default; documents: doc:1 | mate descriptions not extracted |  |
| rms.assembly.subassemblies | configuration: Default; documents: doc:1 | subassembly mates not extracted; assembly rules evaluated for the root document only |  |
| rms.types.unknown | configuration: Default; documents: doc:3 | feature type names not in the calibrated table: 3 feature(s) on the pin document. |  |
| fasteners | configuration: Default | list_fasteners returned zero instances, so no screw or bolt joint could be checked. |  |
| holes.alignment | components: cmp:0002, cmp:0004; configuration: Default | no hole was extracted from either pin, so no coaxial pair could be checked. |  |
| interfaces.fit | components: cmp:0002, cmp:0004; configuration: Default | pin geometry was not extracted, so the dowel fit could not be computed. |  |
| interfaces.stack | configuration: Default | no drawing dimensions, target gap or stack contributors were extracted. |  |
| drawing.manufacturing_inputs | configuration: Default | no drawing documents or sheets were included. |  |
| provenance | configuration: Default; documents: doc:2, doc:3 | the local-modification state is unavailable for two of the three documents. |  |
| modeling.resilience | configuration: Default | 5 checked, 11 skipped, 28 unresolved rule result(s) over 3 document(s); 6 finding(s). |  |
| coverage.closeout | configuration: Default | the package carries no hole, fastener or drawing evidence, so four checklist items closed out unresolved. |  |
| coverage.evidence_request | configuration: Default; documents: doc:1, doc:2, doc:3 | ER-001 is still open: The vault version and the local-modification state of every reviewed document. |  |
| coverage.evidence_request | configuration: Default; documents: doc:2 | ER-002 is still open: A part drawing for the housing carrying material, tolerance and thread notes. |  |
| coverage.evidence_request | configuration: Default | ER-003 is still open: The pin geometry and the hole each pin seats in. |  |

### Failed

None.

### Out of Scope

| Check | Scope | Reason | Error |
|---|---|---|---|
| rms.drawing.model_items_preferred | configuration: Default; documents: doc:1 | drawing-owned vs model dimensions not extracted; advisory by decision |  |
| rms.advisory.structural_vs_cosmetic_fillets | configuration: Default; documents: doc:1 | judgement-only; not decidable from extracted data |  |
| rms.advisory.core_shaping_cuts | configuration: Default; documents: doc:1 | judgement-only; not decidable from extracted data |  |
| rms.advisory.description_quality | configuration: Default; documents: doc:1 | judgement-only; not decidable from extracted data |  |
| rms.advisory.sketch_plane_choice | configuration: Default; documents: doc:1 | judgement-only; sketch planes not extracted |  |
| rms.advisory.avoid_multibody | configuration: Default; documents: doc:1 | judgement-only; body intent not decidable |  |
| interference | configuration: Default | the assembly holds no mechanism, so no position other than Default was checked. |  |


## Timing

- Baseline minutes: unknown
- Assisted supervision minutes: 0.0
- Assisted verification minutes: 0.0
- False alarm handling minutes: 0.0
- Unattended runtime minutes: 1.62
- Net saved minutes: unknown

## Tokens

- Rounds: 2
- Turns: 1
- Input tokens: 27000
- Cached input tokens: 11000
- Uncached input tokens: 16000
- Cache write tokens: 0
- Output tokens: 1600
- Reasoning tokens (OpenAI, inside the output tokens): 960
- Tool-result input tokens: not reported
- Total tokens: 28600
- Cached input share: unknown (probe L1 not recorded)
- Model latency: 39.50 s

## Investigation Trace

| Index | Tool | Status | Elapsed (s) |
|---|---|---|---|
| 0 | check_rms_part | ok | 0.25 |
| 1 | check_rms_assembly | ok | 0.5 |
| 2 | check_rms_equations | ok | 0.75 |
| 3 | check_interference | ok | 1.0 |
