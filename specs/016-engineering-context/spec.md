# Feature 016: engineering context foundation

**Status**: Offline delivery and pane entry complete; 2 workstation tasks open (see [specs/README.md](../README.md)). Drafted as: implementation authorized 2026-10-14, following the accepted
[foundation design](../../docs/engineering-context-foundation.md).

An engineer can attach requirements and applied forces to a saved extracted part,
assembly occurrence or face, inspect the exact proposed input, explicitly confirm it,
and supply it as bounded read-only context to a review. CAD evidence remains immutable.

## First delivery

1. A versioned, strict, immutable sidecar stores requirements and total applied forces.
   Force units are N, kN and lbf; unknown is distinct from zero. Provenance and
   assumptions stay explicit, including AI proposals confirmed by an engineer.
2. An anchor records the extracted document, configuration and exact occurrence/face,
   scoped persistent reference and dependency fingerprints. Only an exact saved
   package match can report `matched_snapshot`; it never verifies the live CAD model.
   Missing, suppressed, inconsistent and changed evidence requires review.
   *Amended 2026-10-15 (owner decision 107A):* the saved package as the review's own live
   interference check rewrote it, and nothing else, also matches.
3. Rigid right-handed frames rotate direction and translate points. Checked software
   converts units and preserves force magnitude. Reflected, scaled, nonfinite and
   projective transforms are refused. This provides context, without a solver verdict.
4. Private storage uses immutable revisions, a predecessor digest, an exclusive lock
   and compare-and-swap publication. Approval receipts retain the precise record and
   dependency digests presented to the engineer. Edits invalidate current approval;
   history is retained. CAD source directories and unsafe store paths are refused.
5. Offline CLI commands initialize, put, inspect and confirm records. Confirmation
   requires the exact displayed digests and actor. LLM tools can only read an explicitly
   supplied sidecar. Their bounded projections omit paths, persistent refs and actors.

## Acceptance cases

- A repeated component instance receives its own load; a sibling cannot inherit it.
- A 2 kN load rotated 90 degrees resolves to 2000 N in the root frame.
- Unknown force is visible and cannot be approved as a complete load.
- A changed package or record retains historical approval but requires review.
- Concurrent/stale publication and interrupted head replacement preserve the old head.
- Existing reviews and tool schema pins remain unchanged without explicit context.
- No CAD file, feature flag, native guard or native command is written or enabled.

Native selection/face rebinding, unsaved-state verification and workstation UI require
the SOLIDWORKS machine and remain a later gate. Pressure, moments, supports, automatic
drawings, structural analysis and safety conclusions are outside this delivery.
