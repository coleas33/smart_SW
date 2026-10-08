"""Write every committed case (feature 014 `generator.md` 1 and 10; `cases.md` 1; GN-1; SC-006).

Run from `reviewer/`:

    uv run python -m tests.benchmark_cases.generate

It renders everything in memory, runs the spec checks and the names check, and only then writes:
each path it wrote, then each **stale** file - a file under `benchmarks/packages/`,
`answer_keys/`, `case_files/` or `sets/` that it did not write and that is neither hand-kept nor
under the native-package slot `packages/bracket-assy/` - as "stale: <path>: delete it or restore
its spec", exiting 1 if any remains. It never deletes. It reads the specs, the builders and
`config/standards.example.yaml` only: no run folder, recording, key, owner's list or clock.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from swreview.benchmark.sets import REPO_ROOT
from tests.benchmark_cases import designs, render
from tests.benchmark_cases.spec import CaseSpec, CaseSpecError, check_anchor_coverage, check_specs

GENERATED: tuple[str, ...] = (render.PACKAGES, render.ANSWER_KEYS, render.CASE_FILES, render.SETS)
"""The folders every file of which the generator writes (`cases.md` 1)."""

HAND_KEPT: frozenset[str] = frozenset({"benchmarks/answer_keys/rms-part.json"})
"""The one hand-kept file under the generated folders (`answer-key.md` 7.2)."""

NATIVE_SLOT = "benchmarks/packages/bracket-assy/"
"""The test suite's native-package slot (`reviewer/tests/conftest.py:27`), placed per machine and
named by no set: neither written nor stale (RF-75)."""


def every_spec() -> list[CaseSpec]:
    """Every spec of `designs.DESIGNS`, designs in order, specs in module order."""
    return [case for module in designs.DESIGNS for case in module.SPECS]


def render_all() -> dict[str, bytes]:
    """Every generated file by repository-relative POSIX path: `check_specs`, then
    `check_anchor_coverage`, over every spec; then each spec's files and set entries, and the
    three set files; then the names and fictional-roots check, before anything is written."""
    specs = every_spec()
    check_specs(specs)
    check_anchor_coverage(specs)
    rendered: dict[str, bytes] = {}
    cased = []
    for case in specs:
        rendered.update(render.render_spec(case))
        cased.append((case, render.set_entries(case)))
    rendered.update(render.set_files(cased))
    offences = render.names_offences(rendered)
    if offences:
        raise CaseSpecError(*offences[0])
    return rendered


def stale_files(root: Path, rendered: Mapping[str, bytes]) -> list[str]:
    """One "stale: <path>: delete it or restore its spec" line per file under the generated
    folders of the checkout at `root` that `rendered` lacks, hand-kept files and the native slot
    apart, sorted. Deletes nothing."""
    stale = []
    for folder in GENERATED:
        for path in (root / folder).rglob("*"):
            relative = path.relative_to(root).as_posix()
            if (
                path.is_file()
                and relative not in rendered
                and relative not in HAND_KEPT
                and not relative.startswith(NATIVE_SLOT)
            ):
                stale.append(f"stale: {relative}: delete it or restore its spec")
    return sorted(stale)


def main(root: Path = REPO_ROOT) -> int:
    """Write exactly `render_all()`'s bytes under `root` (`Path.write_bytes`, which keeps LF),
    print each path written, then each stale file; 1 if any stale file remains, else 0."""
    rendered = render_all()
    for relative, content in rendered.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        print(relative)
    stale = stale_files(root, rendered)
    for line in stale:
        print(line)
    return 1 if stale else 0


if __name__ == "__main__":
    raise SystemExit(main())
