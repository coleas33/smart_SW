"""The golden-harness adapter for the standards checks (T053 to T056).

`tests/golden/test_golden.py` calls `module:function(package, **kwargs)`, so each
`standards-*` fixture's `case.json` names `standards_case` here and the profile it is
graded against. One adapter for all four fixtures: they differ in what the package
contains, never in how it is run.

Three things are this adapter's own, and each of them is a decision the baseline depends
on:

1. **the real entry point, and only it.** `run_standards_check(package_dir, profile_path,
   out_dir)` is what `swreview check standards` and `POST /checks/standards` call, so the
   baseline pins what an engineer would actually be shown - the findings with their
   subjects, the aggregated coverage per check per bucket, the sixteen rendered check rows
   and the release verdict - and a check whose wording, bucket or verdict moves shows up as
   a diff rather than as a quietly different report;
2. **the package is copied into a scratch directory and the run folder is beside it.** The
   harness hands over a loaded `EvidencePackage` and no directory, and the entry point
   reads a directory; writing the copy is also what makes it impossible for a golden run to
   touch the fixture it is grading (SC-010). Nothing of the scratch paths reaches the
   result: `session.json`, `report.md` and `check.json` are written and are not part of
   what is compared, because their content is the session's and is pinned by the unit tests
   that own it;
3. **the profile identity is rendered as a token, not as this machine's path.** Every
   finding carries `profile:<path> sha256:<hash>` (FR-034), and the path is wherever this
   checkout happens to sit. The substitution is built from the values the run actually
   stamped, so a run that graded against the *wrong* profile leaves a real path and a real
   hash in the baseline rather than the token - which is exactly the diff that should be
   noticed.
"""

from __future__ import annotations

import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from swreview.checks.standards.run import StandardsCheckRun, run_standards_check
from swreview.ir.loader import save_package
from swreview.ir.models import EvidencePackage

__all__ = ["PROFILE_DIR", "standards_case"]

PROFILE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "standards"
"""The two fictional profiles (T002). No company value enters a golden (FR-001)."""

DEFAULT_PROFILE = "profile-a"


def standards_case(
    package_or_dir: EvidencePackage | Path | str, profile: str = DEFAULT_PROFILE
) -> dict[str, Any]:
    """Grade one fixture against a fictional profile and return what the run produced.

    `package_or_dir` is the loaded package the golden harness hands over, or the directory
    holding `package.json` for a caller that has one. `profile` names a file in
    `tests/fixtures/standards/`, which is the `--profile` the quickstart scenarios pass.
    """
    profile_path = PROFILE_DIR / f"{profile}.yaml"
    with tempfile.TemporaryDirectory(prefix="standards-golden-") as scratch:
        root = Path(scratch)
        if isinstance(package_or_dir, EvidencePackage):
            package_dir = root / "package"
            save_package(package_or_dir, package_dir)
        else:
            package_dir = Path(package_or_dir)
        run = run_standards_check(package_dir, profile_path, root / "run")
        return _rendered(run, profile)


def _rendered(run: StandardsCheckRun, profile: str) -> dict[str, Any]:
    """Everything the run concluded, with this machine's profile path tokenised."""
    tokens = {
        run.profile.path: f"<{profile}.yaml>",
        run.profile.sha256: f"<sha256 of {profile}.yaml>",
    }
    body = {
        "documents": run.documents,
        "document_kinds": run.document_kinds,
        "profile": {"path": run.profile.path, "sha256": run.profile.sha256},
        "verdict": _verdict(run),
        "findings": run.findings,
        "subjects": run.subjects,
        "coverage": run.coverage,
        "checks": run.checks,
        "unavailable_checks": run.unavailable_checks,
        "exceptions_carried_forward": {
            "from_run": run.exceptions_carried_forward.from_run,
            "count": run.exceptions_carried_forward.count,
            "reason": run.exceptions_carried_forward.reason,
        },
    }
    return _substituted(body, tokens)


def _verdict(run: StandardsCheckRun) -> dict[str, Any]:
    verdict = run.verdict
    return {
        "state": verdict.state,
        "counts": vars(verdict.counts).copy(),
        "waived": verdict.waived,
        "unresolved_check_ids": list(verdict.unresolved_check_ids),
        "notes": list(verdict.notes),
    }


def _substituted(value: Any, tokens: Mapping[str, str]) -> Any:
    """`value` with every machine-specific string replaced, at any depth."""
    if isinstance(value, str):
        for original, token in tokens.items():
            value = value.replace(original, token)
        return value
    if isinstance(value, Mapping):
        return {key: _substituted(item, tokens) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        return [_substituted(item, tokens) for item in value]
    return value
