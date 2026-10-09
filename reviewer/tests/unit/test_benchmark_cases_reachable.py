"""Every committed case is reachable (feature 014 T145; `cases.md` 7 and 9; FR-054, SC-014, US5-4,
US5-8, US5-9, US5-16).

The validation over the committed set, apart from the generator: one row per case and leg over
every entry of `benchmarks/sets/committed.json` and `benchmarks/sets/pilot.json`, read through
`load_set` with the repository root, `cover-blind-tap` included. Each entry's spec is found in
`tests.benchmark_cases.designs` by its case id, a twin by its case's `twin(...)` (an entry with
no spec fails naming it), and each row calls `reachability.check_case` on the entry's committed
package and key, asserting its leg's failures are none:

- **(a, pane)**: code-only calls detect exactly the code-produced defects, and nothing unkeyed;
- **(b, off)** and **(b, pane)**: the correct reviewer detects every model-produced defect at its
  expected status, clears none, raises no model-origin false alarm and confirms every condition
  that carries a correct call;
- **(decoy, off)**, for a spec that lists decoys: no decoy's finding credits, flags or clears a
  known defect.

`check_case` runs a case's four reviews once per session (`reachability.REVIEWED`), so its four
rows cost one case. Every row also fails on a message that names no leg, so no failure is lost
between rows. In the default suite and never marked `integration`: a case that fails it cannot
be committed (research §8.6). `rms-part` is key-only and has one row, skipped, saying so.
"""

from __future__ import annotations

import pytest

from swreview.benchmark.sets import REPO_ROOT, BenchmarkPackageRef, load_set
from tests.benchmark_cases import generate, render
from tests.benchmark_cases.spec import CaseSpec, twin
from tests.support import reachability

SET_FILES: tuple[str, ...] = ("committed.json", "pilot.json")
"""The set files whose every entry is validated (`cases.md` 7, "Scope")."""

LEG_PREFIXES: dict[str, str] = {
    "a-pane": "(a) ",
    "b-off": "(b, off) ",
    "b-pane": "(b, pane) ",
    "decoy-off": "(decoy) ",
}
"""Each leg and configuration, as its row is named, and how its failures begin (`cases.md` 7's
message forms)."""

KEY_ONLY = "rms-part"
"""The hand-kept key-only case: it has no package to review (`cases.md` 7, "Scope")."""


def specs_by_case() -> dict[str, CaseSpec]:
    """Every case spec the generator renders, and each twin it derives, by case id."""
    found: dict[str, CaseSpec] = {}
    for case in generate.every_spec():
        found[case.case_id] = case
        if case.twin:
            derived = twin(case)
            found[derived.case_id] = derived
    return found


def committed_entries() -> dict[str, BenchmarkPackageRef]:
    """Every entry of the validated set files, by package id, in set order."""
    return {
        entry.package_id: entry
        for name in SET_FILES
        for entry in load_set(REPO_ROOT / "benchmarks" / "sets" / name, root=REPO_ROOT).packages
    }


SPECS = specs_by_case()
ENTRIES = committed_entries()


def rows() -> list[object]:
    """One row per entry and leg, the decoy leg only for a spec that lists decoys, then the
    key-only case's one skipped row."""
    found: list[object] = []
    for case_id in ENTRIES:
        case = SPECS.get(case_id)
        legs = [leg for leg in LEG_PREFIXES if leg != "decoy-off"]
        if case is not None and render.decoy_calls(case):
            legs.append("decoy-off")
        found.extend(pytest.param(case_id, leg, id=f"{case_id}:{leg}") for leg in legs)
    found.append(
        pytest.param(
            KEY_ONLY,
            None,
            id=KEY_ONLY,
            marks=pytest.mark.skip(reason="key-only: no package to review"),
        )
    )
    return found


@pytest.mark.parametrize(("case_id", "leg"), rows())
def test_every_committed_case_passes_each_leg_of_the_validation(case_id: str, leg: str) -> None:
    entry = ENTRIES[case_id]
    case = SPECS.get(case_id)
    if case is None:
        pytest.fail(f"{case_id} has no case spec in tests.benchmark_cases.designs")
    assert entry.key is not None, f"{case_id} names no key"

    failures = reachability.check_case(entry.path, entry.key, case)

    named = tuple(LEG_PREFIXES.values())
    unnamed = [message for message in failures if not message.startswith(named)]
    assert unnamed == [], "\n".join(unnamed)
    mine = [message for message in failures if message.startswith(LEG_PREFIXES[leg])]
    assert mine == [], "\n".join(mine)
