"""The standards family's one review-only check tool: which documents get which checks.

FR-035 lets this family register **exactly one** tool, and the reason there is one at all
rather than none is the recording: `checks/rules/run.py` dispatches through
`ToolRegistry` with a `SessionSink`, so every finding's `tool_result_ids` names an
investigation step that exists in the session it cites. One tool and not one per scope,
which is where the rms family landed: its three scopes read different evidence and are
selectable from the command line, while here **all sixteen checks run on every run** and
the document kinds decide which apply (`contracts/standards-check.md` D1).

The tool is deliberately **outside `REGISTRATIONS`**, exactly as `remodel_tools` is, and is
offered only when the context carries a standards run - which only
`checks/standards/run.py` arranges. A review, a general-chat session and every other tab
carry none, so none of them can see it, `registry.TOOL_FUNCTIONS` does not move, and the
MCP function list and the terminal profile's tools are untouched (FR-035).

What is left here, as in `tools/rms_checks.py`, is the dispatch decision - *which* checks
each graded document gets - and it is three rules:

- **a document the package records a kind for** gets its own scope's checks and the
  document-scope check, and nothing else. A check whose scope does not match is not
  evaluated here at all: `checks/standards/report.py` writes it as an `out_of_scope`
  coverage row after the fact, which is why out of scope is not a seventh outcome;
- **a document the traversal reached and could not resolve** - no kind, or no path - is
  `unresolved` for **every** check, naming the reason the traversal gave. Not skipped, and
  certainly not passed: a document nobody could read is a coverage gap, and grading fewer
  documents than the package describes without saying so is the silent failure a release
  gate must not have (FR-004, FR-029);
- **a check this build does not run yet** is `unresolved` over the documents it would have
  graded, naming that nothing about it is claimed, and is listed in `unavailable_checks`.
  Today that is the four drawing checks, until `checks/standards/drawing.py` lands (T066).
  It is derived from the catalogue - a check with no evaluator bound, or one whose scope
  has no entry point - so it empties itself when the evaluators arrive rather than needing
  a list to be remembered.

No provider is constructed, no key is read and no network call is made on any path
(FR-045).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from swreview.checks.standards.assembly import evaluate_assembly
from swreview.checks.standards.document import evaluate_document
from swreview.checks.standards.part import evaluate_part
from swreview.checks.standards.profile import StandardsProfile
from swreview.checks.standards.registry import RULES, StandardsRule
from swreview.checks.standards.report import applies, report_results
from swreview.checks.standards.results import RuleResult, unresolved
from swreview.checks.standards.traversal import CheckedDocument
from swreview.ir.models import EvidencePackage
from swreview.tools.context import ToolContext, current_context, error_result
from swreview.tools.query import ToolResult
from swreview.tools.registry import STANDARDS_RUN_ATTRIBUTE

__all__ = [
    "NOT_BUILT",
    "NO_STANDARDS_RUN",
    "SCOPE_EVALUATORS",
    "StandardsRun",
    "attach_standards_run",
    "check_standards",
    "run_standards_checks",
    "standards_run",
    "unavailable_checks",
]

ScopeEvaluator = Callable[
    [CheckedDocument, EvidencePackage, StandardsProfile], list[RuleResult]
]
"""One scope's entry point: every check of that scope over one graded document."""

SCOPE_EVALUATORS: dict[str, ScopeEvaluator] = {
    "assembly": evaluate_assembly,
    "part": evaluate_part,
    "document": evaluate_document,
}
"""The scope entry points this build has.

The `drawing` scope joins this map when `checks/standards/drawing.py` lands (T066); until
then its four checks have no evaluator and `unavailable_checks` reports them. A scope is
in this map exactly when its checks can be run, which is what makes that report derived
rather than maintained.
"""

NO_STANDARDS_RUN = (
    "this tool grades the documents of a standards run and this context carries none; it "
    "is offered only by checks/standards/run.py, which decides the profile and the graded "
    "set before any check is dispatched"
)

NOT_BUILT = (
    "not yet available in this build: {check} is in the catalogue and no evaluator runs it "
    "yet, so nothing was evaluated for it and nothing about it is claimed"
)
"""What a check this build does not run reports. Reported rather than skipped: a run that
answered a check it does not run with silence would read like a clean one."""


@dataclass(frozen=True)
class StandardsRun:
    """What one standards run decided before any check was dispatched.

    The profile the documents are graded against and the graded set itself, computed once
    by `checks/standards/run.py` (FR-003) so that every check evaluates over the same set
    and a root that cannot be graded refuses the run before a folder is created.
    """

    profile: StandardsProfile
    documents: tuple[CheckedDocument, ...]


def attach_standards_run(context: ToolContext, run: StandardsRun) -> None:
    """Carry `run` on `context`, which is what makes the check tool offered at all.

    Set as an attribute rather than as a `ToolContext` field, because `tools/context.py` is
    reused unchanged by this feature (`specs/006-standards-check/plan.md`, Source Code): the
    tool layer must not import the family that fills the hook, and a fifth optional field on
    the context for one caller's object is a wider change than the one seam this needs. The
    attribute's name is `registry.STANDARDS_RUN_ATTRIBUTE`, which is where `_offered` reads
    it, so the two cannot disagree about it.
    """
    setattr(context, STANDARDS_RUN_ATTRIBUTE, run)


def standards_run(context: ToolContext) -> StandardsRun | None:
    """The standards run `context` carries, or `None` when it carries none."""
    return getattr(context, STANDARDS_RUN_ATTRIBUTE, None)


def check_standards() -> ToolResult:
    """Grade every document of this standards run against all sixteen release checks.

    Notes:
        There is no argument because there is no choice to offer: every check runs on every
        run and the kind of each graded document decides which apply. A check whose scope
        matches no graded document is an `out_of_scope` coverage row, never a silent
        absence, so a release gate can say that all sixteen were accounted for.

        Each failing check becomes **one** finding per document, naming every component
        instance that reaches it and every subject it read; each passing, skipped or
        unresolved check becomes one aggregated coverage item per bucket; and the
        `standards.release` summary carries the release verdict and the counts in every
        bucket. Each call re-evaluates the whole graded set and replaces its own coverage,
        so running it twice leaves one coverage item per check; findings are appended, as
        they are by every check tool.

        A `fail` outcome consults the retained exceptions for exactly this check, this
        document and this configuration: an `active` exception waives the finding and is
        cited on it, one whose fingerprint has changed leaves the finding standing and says
        so. Nothing is rebuilt, opened, loaded or resolved: the rebuild-error counts are as
        the documents stood when they were last rebuilt, and the report says so.
    """
    return run_standards_checks(current_context())


def run_standards_checks(context: ToolContext) -> ToolResult:
    """Grade the standards run `context` carries and write the results to its session.

    The tool above is this with the context taken from the call; nothing else runs the
    checks, so the command line, the route and the tab cannot be three evaluations of one
    design.
    """
    run = standards_run(context)
    if run is None:
        return error_result(NO_STANDARDS_RUN)

    results: list[RuleResult] = []
    for document in run.documents:
        results.extend(_results_for(document, context.ir, run.profile))
    return report_results(context, results, run.documents, run.profile.identity)


def unavailable_checks() -> list[dict[str, str]]:
    """The checks in the catalogue that this build does not run, with the reason.

    Derived from the catalogue rather than listed: a check is unavailable when no evaluator
    is bound to it or when its scope has no entry point, which is exactly the condition
    that makes it impossible to dispatch. The list empties itself when the evaluators land.
    """
    return [
        {"check": rule.id, "reason": NOT_BUILT.format(check=rule.id)}
        for rule in RULES.values()
        if not _available(rule)
    ]


def _available(rule: StandardsRule) -> bool:
    """Whether this build can dispatch `rule` at all."""
    return rule.fn is not None and rule.scope in SCOPE_EVALUATORS


def _results_for(
    document: CheckedDocument, package: EvidencePackage, profile: StandardsProfile
) -> list[RuleResult]:
    """Every check that applies to one graded document, in catalogue order."""
    if document.unresolved_reason is not None:
        return [
            unresolved(rule, document.document_id, document.unresolved_reason)
            for rule in RULES.values()
        ]

    kind = str(document.kind)
    results: list[RuleResult] = [
        unresolved(rule, document.document_id, NOT_BUILT.format(check=rule.id))
        for rule in RULES.values()
        if applies(rule, kind) and not _available(rule)
    ]
    for scope in _scopes_of(kind):
        results.extend(SCOPE_EVALUATORS[scope](document, package, profile))
    return results


def _scopes_of(kind: str) -> Sequence[str]:
    """The scopes a document of `kind` is graded under: its own, and the document scope.

    The document scope grades all three kinds (`contracts/rules.md`), so it is asked for
    every document rather than being one more entry in a kind-to-scope table.
    """
    return [scope for scope in (kind, "document") if scope in SCOPE_EVALUATORS]
