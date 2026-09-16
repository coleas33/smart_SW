# this part needs rebuilding: 0 of 3 features moved, 2 of 2 planned changes were applied, and the geometry gate reported pass

## Change list

3 change(s) were attempted: 2 applied, 1 failed, 0 rolled_back, 0 rollback_failed, and 0 left in flight when the run stopped.
The plan carried 2 change(s), of which 2 were applied. Planned changes that were not applied: none.

| # | kind | subject | outcome | note |
|---|------|---------|---------|------|
| 1 | rename | Fillet1 (feat:0001) | applied | - |
| 2 | describe | Hole1 (feat:0002) | applied | - |
| 3 | reorder | Fillet5 (feat:0003) | failed | not_addressable: could not be addressed after change 2 |

Every write of this run went to `C:\runs\20260916-142201-bracket-remodel\copy\bracket-RMS.SLDPRT`. That is read from evidence rather than from intent: 3 of 3 change record(s) in `changes.jsonl` name it as the target `VerifyTarget` confirmed, and 2 of 2 mutating request(s) in `remodel.log` name it (FR-041).

## Grade

| bucket | before | after | change |
|--------|--------|-------|--------|
| failed | 2 | 1 | -1 |
| warned | 2 | 2 | +0 |
| checked | 5 | 6 | +1 |
| skipped | 11 | 11 | +0 |
| unresolved | 4 | 4 | +0 |
| out of scope | 6 | 6 | +0 |

Fraction of the rules that reached a verdict: 0.556 before, 0.667 after.
Rules nobody could evaluate, before: rms.assembly.mates_described, rms.assembly.no_sibling_in_context_refs, rms.assembly.positions_driven_by_globals, rms.assembly.subassemblies; after: rms.assembly.mates_described, rms.assembly.no_sibling_in_context_refs, rms.assembly.positions_driven_by_globals, rms.assembly.subassemblies.

| rule | before | after | subjects before | subjects after |
|------|--------|-------|-----------------|----------------|
| rms.intent.every_feature_described | fail | pass | feat:0002 | none |

## Geometry

Verdict: **pass**, under the `IDENTITY` profile, calibrated by PROBE-8 2026-09-16.

| quantity | before | after | absolute | relative | bound | within |
|----------|--------|-------|----------|----------|-------|--------|
| volume_m3 | 0.00123456789 | 0.00123456789 | 0 | 0 | 1e-09 | yes |
| surface_area_m2 | 0.0456 | 0.0456 | 0 | 0 | 1e-09 | yes |
| center_of_mass_m | 0.01, 0.02, 0.03 | 0.01, 0.02, 0.03 | 0 | 0 | 1e-09 | yes |
| principal_moment_0 | 1.1e-05 | 1.1e-05 | 0 | 0 | 1e-09 | yes |
| principal_moment_1 | 2.2e-05 | 2.2e-05 | 0 | 0 | 1e-09 | yes |
| principal_moment_2 | 3.3e-05 | 3.3e-05 | 0 | 0 | 1e-09 | yes |
| solid_body_count | 1 | 1 | 0 | not read | exact | yes |
| face_count | 214 | 214 | 0 | not read | exact | yes |
| edge_count | 642 | 642 | 0 | not read | exact | yes |
| mass_kg | 3.21 | 3.21 | 0 | 0 | 1e-09 | yes |

The material did not change between the two readings.

What this comparison **cannot** detect, on this run as on every run:
- a reflection
- a rigid rotation about a symmetry axis
- compensating add and remove pairs
- any difference occupying no volume (split faces, cosmetic threads, material, custom properties, configuration data)
- surface-body and wire-body differences
- a difference produced by the baseline rollback and rebuild themselves, which sits inside the baseline reading and cannot be seen from it

## Rebuild list

1 feature(s) cannot be placed by reorganizing alone:

| feature | reason | blocking edge | detail |
|---------|--------|---------------|--------|
| Fillet7 (feat:0044) | backward_reference | feat:0061 -> feat:0044 | parent feat:0061 is in 6-Quarantine |

1 feature(s) are held away from the position the method wants for them:

- feat:0031: wanted at index 4, achievable at 12; held below its parent feat:0012 (feat:0012 -> feat:0031)

## Deviations

Choices this run made that a reader has to check:

- Fillet5 (feat:0002) -> 3-Core: reviewed as structural; move to Quarantine if cosmetic (fillet_default_core; no evidence it is cosmetic)

### Groups the model assigned

- Hole1 (feat:0003) -> 4-Detail, by gemini gemini-2.5-pro: a slot, not a hole

### What this run did not cover

- scope: every scope signal was read and none of them refuses this part
- target group: 0 of 3 content feature(s) have no target group; the judgement phase has not run, and an undecided feature is never moved
- feature descriptions: 0 description(s) unreadable and 1 blank of 3 content feature(s); the planner never invents description prose, so revision 1 proposes none, and an unreadable one is refused as a change target because it has no recoverable inverse (feat:0003)
- global variables: 1 feature reading(s) could justify a global; revision 1 proposes none, and a v1 global names a value and drives nothing (feat:0002)
- equations: 0 equation row(s): 0 global, 0 driving a dimension, 0 broken, 0 unjudgeable; revision 1 repairs none and adds none
- sketch dimensions: not carried by IR 1.2.0, so this version can neither name a dimension, rename one, nor drive one from a global (FR-030)
- folders: 2 folder(s) to create, 0 already correct, 0 refused
- changes: 2 change(s) planned, in the fixed order of section 1.11

### Refusals

- scope: none; every signal was read and none of them refuses this part
- folders: none

## Judgement

**Accepted descriptions**

- Hole1 (feat:0003): "Mounting slot" - openai gpt-5-mini: the sketch is a slot profile

**Accepted global variables**

- `shell_thickness` = 3 - gemini gemini-2.5-pro: three features share the wall (evidence: feat:0003 shell_thickness = 3.0 mm)

The globals added by this run **drive nothing yet**: a v1 global names a value and no dimension is driven from it, because the IR carries no dimensions and this version can neither name one nor prove what an equation on one would drive (FR-030).

**Rejected proposals**

- `propose_global` {"expression": "50", "name": "PlateWidth"}: global name must be lower_snake_case, 2 to 32 characters (rule `global.name_pattern`) - openai gpt-5-mini

## Attestation

- source: `C:\work\bracket.SLDPRT`
- length: 482913 bytes
- last write (UTC): 2026-09-14T09:11:03+00:00
- sha256: `4c4c4c4c4c4c4c4c4c4c4c4c4c4c4c4c4c4c4c4c4c4c4c4c4c4c4c4c4c4c4c4c`
- recorded at: 2026-09-16T14:22:01+00:00
- re-checked at: 2026-09-16T14:41:55+00:00
- copy: `C:\runs\20260916-142201-bracket-remodel\copy\bracket-RMS.SLDPRT`
- copy sha256 after save: `7777777777777777777777777777777777777777777777777777777777777777`

Verdict: the engineer's file is byte for byte what it was when the copy was made.

## Credit and status

The rules this run applied, the six groups and the group vocabulary are the **Resilient Modeling Strategy**'s; this tool implements them and claims none of them as its own.

**This copy is a proposal the engineer accepts or discards, and not an engineering acceptance result.** Nothing here says the part is correct: it says a tree was reorganized and that the measurements taken of it did not move. That is why there is no letter grade anywhere in this report.
