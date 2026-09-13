"""Deterministic geometry helpers shared by the US5 checks and the measurement tools.

Everything here works in metres, the unit the IR stores (SOLIDWORKS internal units), and
returns plain floats or `Quantity`; conversion for display or for a finding happens in
`swreview.units`. No function here reads the IR package or talks to SOLIDWORKS.
"""
