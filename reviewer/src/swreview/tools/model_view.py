"""What the model reads of a tool result: the view beside the record (feature 008).

The model reads a **view**; the run folder keeps the **record** (`contracts/model-view.md`
section 1). A tool's return is never changed by anything here: every function takes a
payload and returns a new value, and the session, the package, the report and the stored
results keep the payload itself.

This module is the one place that knows what a tool result *looks like* to the model. It
lives under `tools/` because it knows tool shapes, which the provider adapters must not
import (`tools/registry.py` imports the providers, never the reverse).

User Story 2 lands the check digest - the counting helper the opening digest's family line
shares, and the one renderer of a check result the re-call guard answers with. User Story 3
adds reference stripping, the grouped gaps and the view table.

**Counted, never estimated, and every omission stated** (Principle I). A digest names at
most `ROW_CAP` rows and `ID_CAP` finding ids and says how many it left out of each; a
count is a count of the objects the tool recorded, never of anything re-derived.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

__all__ = [
    "ID_CAP",
    "ROW_CAP",
    "FindingCounts",
    "check_digest",
    "count_findings",
]

ROW_CAP = 25
"""How many finding rows a digest names, in payload order (data-model section 9)."""

ID_CAP = 200
"""How many finding ids a digest names. A finding past the 200th cannot be fetched with
`get_finding`, because the model never saw its id; `finding_ids_omitted` says so."""

ROW_FIELDS: tuple[str, ...] = ("id", "check", "status", "severity", "title")
"""What one digest row carries of a finding: enough to choose which one to fetch."""

_DIGESTED_KEYS = frozenset({"status", "findings", "finding", "subjects", "coverage"})
"""The payload keys the digest renders itself; every other top-level scalar is kept."""


@dataclass(frozen=True)
class FindingCounts:
    """How many findings, of how many rules, by status and by severity (keys sorted)."""

    findings: int
    rules: int
    by_status: dict[str, int]
    by_severity: dict[str, int]


def _sorted_counts(values: Iterable[str]) -> dict[str, int]:
    """A count per value, keys sorted, so the bytes do not depend on arrival or hash order."""
    return dict(sorted(Counter(values).items()))


def count_findings(rows: Iterable[tuple[str, str, str]]) -> FindingCounts:
    """Count `(check, status, severity)` triples: the one counting rule for findings.

    The check digest counts a payload's findings with it and the opening digest counts a
    folded family's session findings with it, so the model reads one rule's numbers in both
    places (research R2.20).
    """
    triples = list(rows)
    return FindingCounts(
        findings=len(triples),
        rules=len({check for check, _, _ in triples}),
        by_status=_sorted_counts(status for _, status, _ in triples),
        by_severity=_sorted_counts(severity for _, _, severity in triples),
    )


def _finding_rows(payload: Mapping[str, Any]) -> list[Mapping[str, Any]] | None:
    """The findings a check payload recorded, or `None` when it is not a findings envelope.

    An envelope carries a `findings` list (`report_results`, `record_results`) or one
    `finding` (`record_result`). Anything else - an error, `out_of_scope`, a contact, a
    summary whose `findings` is already a count - is not one, and neither is a list whose
    entries lack a finding's four identifying strings: the digest never guesses at a shape,
    because it runs inside a tool call, which must never raise.
    """
    findings = payload.get("findings")
    if isinstance(findings, list):
        rows = findings
    elif isinstance(payload.get("finding"), Mapping):
        rows = [payload["finding"]]
    else:
        return None
    for row in rows:
        if not isinstance(row, Mapping) or not all(
            isinstance(row.get(name), str) for name in ("id", "check", "status", "severity")
        ):
            return None
    return rows


def _subjects(payload: Mapping[str, Any], rows: list[Mapping[str, Any]]) -> int:
    """The payload's `subjects` map summed when present, else the distinct component ids."""
    subjects = payload.get("subjects")
    if isinstance(subjects, Mapping):
        return sum(len(entries) for entries in subjects.values() if isinstance(entries, list))
    return len({cid for row in rows for cid in row.get("component_ids") or ()})


def _coverage(coverage: Any) -> Any:
    """Coverage rows counted by bucket (keys sorted); a count or a map kept as given."""
    if isinstance(coverage, list):
        return _sorted_counts(
            str(row.get("bucket")) for row in coverage if isinstance(row, Mapping)
        )
    if isinstance(coverage, Mapping):
        return dict(coverage)
    return coverage


def check_digest(payload: Mapping[str, Any], *, counts_only: bool = False) -> dict[str, Any]:
    """What the model reads of a check tool's payload (FR-018, data-model section 9).

    The counts, at most `ROW_CAP` rows and `ID_CAP` ids with what each left out, the
    subjects, the coverage, and every other top-level scalar of the payload (`group_key`,
    `configuration`, `members`) as given; lists and objects the digest does not render -
    an interference group's `pairs`, its `exception` - are left out. `counts_only` drops
    the rows and the ids: the re-call guard's answer for a folded family, of which the
    model is told only counts (FR-014).

    A payload that is not a findings envelope is returned as an equal copy. The input is
    never mutated, and the same payload gives the same bytes in every process.
    """
    rows = _finding_rows(payload)
    if rows is None:
        return dict(payload)
    counts = count_findings((row["check"], row["status"], row["severity"]) for row in rows)
    digest: dict[str, Any] = {
        "status": payload.get("status"),
        "findings": counts.findings,
        "rules": counts.rules,
        "by_status": counts.by_status,
        "by_severity": counts.by_severity,
    }
    if not counts_only:
        ids = [row["id"] for row in rows]
        digest["rows"] = [
            {name: row.get(name) for name in ROW_FIELDS} for row in rows[:ROW_CAP]
        ]
        digest["rows_omitted"] = max(0, len(rows) - ROW_CAP)
        digest["finding_ids"] = ids[:ID_CAP]
        digest["finding_ids_omitted"] = max(0, len(ids) - ID_CAP)
    digest["subjects"] = _subjects(payload, rows)
    if "coverage" in payload:
        digest["coverage"] = _coverage(payload["coverage"])
    for key, value in payload.items():
        if key not in _DIGESTED_KEYS and isinstance(value, str | int | float):
            digest[key] = value
    return digest
