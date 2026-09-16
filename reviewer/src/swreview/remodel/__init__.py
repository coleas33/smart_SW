"""The resilient re-modeler (feature 004, stage 1): plan, decide, and report.

Every module here is pure Python with no COM in any signature. The measurements come from
the bridge (`remodel.*`, `specs/004-resilient-remodeler/contracts/bridge-remodel.md`) and
every decision about what should move, what cannot be fixed, and whether the geometry is
unchanged is taken here, so a decision is table-testable without a SOLIDWORKS seat
(`plan.md`, "Structure Decision").
"""
