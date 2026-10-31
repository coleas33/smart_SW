"""Ledgers in `RemodelProbeLedger.Render`'s shape, for the tests that read one (feature 004).

`rendered_ledger` writes a small ledger in the exact text the C# renderer writes; it moved here
from `tests/unit/test_workstation_test_plan.py` (004 T336) so the plan's `Show-RemodelLedger` test
and `swreview remodel ledger`'s tests build theirs one way. The plan test pins the prefixes it
relies on against the C# source, and `GOLDEN_LEDGER` - which the C# test
`RemodelProbeTests.Ledger_Render_WritesTheGoldenLedgerTheReaderIsPinnedTo` renders byte for byte -
pins the whole shape for the reader. `committed_ledgers` is what the CI pins read from
`CAPABILITIES` (004 T338 and T339), and `CALIBRATED` is IDENTITY as T138 would leave it, for the
cases that test everything else Start needs (004 T346).
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from swreview.remodel.tolerances import IDENTITY
from tests.support.seat_tasks import REPO

__all__ = ["CALIBRATED", "CAPABILITIES", "GOLDEN_LEDGER", "committed_ledgers", "rendered_ledger"]

GOLDEN_LEDGER = (
    Path(__file__).resolve().parents[1] / "fixtures" / "remodel" / "ledger" / "remodel-32.5.0.yaml"
)
"""A fictional run of the whole probe catalog that stopped in its last probe, PROBE-21."""

CAPABILITIES = REPO / "benchmarks" / "native" / "capabilities"
"""Where seat evidence is committed (decision 171A; its README)."""

CALIBRATED = IDENTITY.model_copy(update={"calibrated": True, "calibration_ref": "fictional"})
"""IDENTITY as T138 would leave it."""


def committed_ledgers(root: Path = CAPABILITIES) -> list[Path]:
    """Every probe ledger under `root`, at any depth: each `probe remodel` run's folder may be
    kept whole, so two runs' ledgers can share a name."""
    return sorted(root.rglob("remodel-*.yaml")) if root.is_dir() else []


def rendered_ledger(
    records: Sequence[tuple[str, bool, str, dict[str, str]]],
    requested: Sequence[str] | None = None,
    sw_version: str = "32.5.0.48",
) -> str:
    """A ledger in `RemodelProbeLedger.Render`'s shape: `(probe id, blocking, verdict,
    raw_result)` per probe, and the `requested:` list, which defaults to the rows' own probes,
    as the renderer's does."""
    asked = [probe for probe, _, _, _ in records] if requested is None else list(requested)
    lines = [f'sw_version: "{sw_version}"', 'generated_at: "2026-10-02T12:00:00.0000000+00:00"']
    lines += ["requested:", *(f'  - "{probe}"' for probe in asked)] if asked else ["requested: []"]
    lines.append("probes:" if records else "probes: []")
    for probe, blocking, verdict, raw in records:
        lines += [
            f'  - probe_id: "{probe}"',
            '    question: "a question"',
            '    method: "a method"',
            f"    blocking: {'true' if blocking else 'false'}",
            '    fallback: "a fallback"',
            f"    verdict: {verdict}",
            f'    sw_version: "{sw_version}"',
            "    duration_ms: 12",
            "    interop_members: []",
        ]
        if raw:
            lines.append("    raw_result:")
            lines += [f'      "{key}": "{value}"' for key, value in raw.items()]
        else:
            lines.append("    raw_result: {}")
    return "\n".join(lines) + "\n"
