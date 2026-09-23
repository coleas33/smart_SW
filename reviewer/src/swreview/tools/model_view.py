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

import re
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

__all__ = [
    "FINDING_DETAIL",
    "GAP_IDS_SHOWN",
    "ID_CAP",
    "MODEL_VIEWS",
    "REF_IN_TEXT",
    "ROW_CAP",
    "STRIPPED_KEYS",
    "FindingCounts",
    "check_digest",
    "count_findings",
    "grouped_gaps",
    "model_view",
    "strip_references",
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


# --- User Story 3: the view the model reads (`contracts/model-view.md` sections 2 to 4) -------

STRIPPED_KEYS = frozenset(
    {"persist_ref", "persist_ref_scope", "persist_ref_scopes", "component_persist_refs"}
)
"""The keys a persistent reference travels under in any tool result, at any depth (FR-015)."""

REF_IN_TEXT = re.compile(r" persist_ref=(?:none|[A-Za-z0-9+/]+={0,2})")
"""The reference inside a finding input string - `<kind> <id> <name> persist_ref=<b64|none>
scope=<id>`, the RMS and standards evidence format - with its leading space, so what is left
reads `<kind> <id> <name> scope=<id>`. The scope is a document id the model can use; the
reference is a string it cannot."""

FINDING_DETAIL = "get_finding(finding_id) returns one finding in full"
"""What every check tool's view ends with, so a model reading a digest knows the full finding
is one call away (FR-018)."""

GAP_IDS_SHOWN = 5
"""How many entity ids a grouped gap names; the rest are counted (`entity_ids_omitted`)."""

_QUOTED = re.compile(r"'[^']*'")


def strip_references(value: Any) -> Any:
    """`value` with every persistent reference left out: a new value, never the input.

    Keys in `STRIPPED_KEYS` are dropped from every mapping at any depth, and the inline
    `persist_ref=` token is cut out of every string (`REF_IN_TEXT`). Everything else - ids,
    names, numbers, the `scope=` of an input - is kept as it is.
    """
    if isinstance(value, Mapping):
        return {
            key: strip_references(item)
            for key, item in value.items()
            if key not in STRIPPED_KEYS
        }
    if isinstance(value, list | tuple):
        return [strip_references(item) for item in value]
    if isinstance(value, str):
        return REF_IN_TEXT.sub("", value)
    return value


def grouped_gaps(gaps: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """The gap rows grouped by what they say, for the model (FR-019, data-model section 10).

    Rows group by `(kind, entity_kind, reason)` with every single-quoted substring of the
    reason replaced by "…": the reasons embed document and component names, so grouping by
    the literal text would group almost nothing. Each group keeps the first row's full
    reason, counts its rows, and names the first `GAP_IDS_SHOWN` entity ids with the number
    it left out; a row with no entity id is counted and not listed. Groups come in the order
    their first row appeared.
    """
    groups: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in gaps:
        reason = str(row.get("reason", ""))
        key = (str(row.get("kind")), str(row.get("entity_kind")), _QUOTED.sub("'…'", reason))
        group = groups.setdefault(
            key,
            {
                "kind": row.get("kind"),
                "entity_kind": row.get("entity_kind"),
                "reason": reason,
                "rows": 0,
                "entity_ids": [],
                "entity_ids_omitted": 0,
            },
        )
        group["rows"] += 1
        entity_id = row.get("entity_id")
        if entity_id is None:
            continue
        if len(group["entity_ids"]) < GAP_IDS_SHOWN:
            group["entity_ids"].append(entity_id)
        else:
            group["entity_ids_omitted"] += 1
    return {"groups": list(groups.values()), "rows": len(gaps)}


def _check_view(payload: Mapping[str, Any]) -> dict[str, Any]:
    """A check tool's view: its digest and the `get_finding` sentence; an error as it is."""
    if "error" in payload:
        return dict(payload)
    return {**check_digest(payload), "detail": FINDING_DETAIL}


def _gaps_view(payload: Mapping[str, Any]) -> dict[str, Any]:
    """`list_gaps` returns a list, which the registry wraps under `result`."""
    rows = payload.get("result")
    return grouped_gaps(rows) if isinstance(rows, list) else dict(payload)


STANDARDS_CHECK_TOOL = "check_standards"
"""The standards family's check tool, named here rather than imported: every module under
`checks/standards/` reaches `agent/runner.py`, which imports `prerun.py`, which imports this
module, so importing the tool at the top of this file closes that cycle (`prerun._deferred`).
`test_model_view.py` asserts every name `registry.check_tools()` and `standards_tools()`
return is in `MODEL_VIEWS`, so this spelling cannot drift from the tool's."""


def _check_tool_names() -> tuple[str, ...]:
    """Every check tool the review can offer: the registry's list and the standards tool."""
    from swreview.tools.registry import check_tools

    return (*(function.__name__ for function in check_tools()), STANDARDS_CHECK_TOOL)


MODEL_VIEWS: dict[str, Callable[[Mapping[str, Any]], Any]] = {
    **dict.fromkeys(_check_tool_names(), _check_view),
    "list_gaps": _gaps_view,
}
"""The one table of per-tool views: every check tool reads its digest, `list_gaps` its grouped
gaps; every other tool its payload, stripped. One table the owner can read, and one a test
can prove no check tool escapes."""


def model_view(tool_name: str, payload: Mapping[str, Any]) -> Any:
    """What the model reads of one tool result with payload slimming on (FR-015 to FR-019).

    `MODEL_VIEWS[tool_name]` when the tool has a view of its own, the payload otherwise, and
    references stripped from either. Never mutates `payload`.
    """
    view = MODEL_VIEWS.get(tool_name)
    return strip_references(view(payload) if view is not None else payload)
