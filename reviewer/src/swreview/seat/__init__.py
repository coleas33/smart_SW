"""Checks the engineer runs at the SOLIDWORKS seat, each offline and read-only.

`health` proves the runbook's health checks a file can prove (004 research R28, decision 166A);
`transparency` decides PROBE-2's polarity from the probe's printed lines (006 research R11) and
`volume_unit` the unit of a recorded interference volume against a known overlap (001 research
R15), both from a tiny made-up assembly built by hand at the seat (decision 172A).
"""

INCONCLUSIVE = "inconclusive"
"""Either decider's answer when the seat did not prove what was asked: never a guess."""
