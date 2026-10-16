"""The origin of a finding: who decided it was worth recording, read from the session.

Feature 014 `contracts/scoring.md` section 5 (FR-007; research D9; owner decisions 17A, 20A).
An origin is **derived**, never stored on a finding (C-17): `finding_origin` reads the
finding's own fields and the session's steps and origin-marks record, first rule winning:

1. `carried_over_from` is set: `carried`.
2. `source` is `model`: `model` (`record_drawing_finding`, the model's reading).
3. The session has no origin-marks record: `unknown`. A session written before the marks reads
   every code finding's origin as unknown, `setup` and `configured_check` included (US1-12);
   the two rules above read their own fields, so they keep their origins.
4. It cites a step: the step with the highest index it cites. A step the session does not hold
   reads `unknown`, never guessed, with the record too (SR-25): the folder was altered or
   written by something other than the review. A marked step gives its mark, `prerun` or
   `regrade`; an unmarked one gives `code_only_call` when its tool is in `CODE_ONLY_TOOLS`, and
   otherwise `configured_check`.
5. It cites no step: `setup` when its check starts with a prefix in `SETUP_CHECK_PREFIXES`
   (the provenance set-up records), and otherwise `configured_check` (the argument-taking check
   tools, whose findings cite no step: research SP-3, owner decision 40A).

**Model origin** is `MODEL_ORIGINS`, named here once; every other value but `unknown` is code
origin. The scorer never refuses on origin: the pane study's refusal of a session without the
record, or of an `unknown` false alarm, is compare's (`verdict.md` 7, refusal 3).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from swreview import prerun
from swreview.checks.standards import registry as standards_registry
from swreview.findings import Finding
from swreview.report.session import ReviewSession
from swreview.tools import drawings

if TYPE_CHECKING:
    from swreview.benchmark.scorecard import PackageScore

__all__ = [
    "CODE_ONLY_TOOLS",
    "MODEL_ORIGINS",
    "SETUP_CHECK_PREFIXES",
    "Origin",
    "deciding_false_alarm_ids",
    "finding_origin",
]

Origin = Literal[
    "prerun",
    "regrade",
    "code_only_call",
    "configured_check",
    "model",
    "carried",
    "setup",
    "unknown",
]
"""FR-007's seven origins, the third split by kind (`scoring.md` 5.1): a step the pre-run made,
a step code re-ran after an answer, a code-only call the model made, a check the model set up,
the model's own reading, a finding carried from an earlier review, a set-up record, and a
session without the origin-marks record."""

MODEL_ORIGINS: frozenset[Origin] = frozenset({"model", "configured_check"})
"""The origins the model decided (17A, 20A): what the pane study's deciding false alarms are
read from."""

SETUP_CHECK_PREFIXES: tuple[str, ...] = ("provenance.",)
"""The checks code writes while preparing every review, citing no step: the provenance family
(`agent/runner.record_provenance`)."""

CODE_ONLY_TOOLS: frozenset[str] = frozenset(
    {
        *prerun.prerun_tools(),
        prerun.LIVE_INTERFERENCE_TOOL,
        drawings.DRAWINGS_TOOL,
        standards_registry.CHECK_TOOL,
    }
)
"""Every tool the pre-run may call, its live interference call, the drawing check and the
standards check (`scoring.md` 5.4), built from the constants that already name them, so a
pre-run change moves it with no second edit (RF-6). Every other check tool is a configured
check by rule 4's "otherwise"; no second set names them (RF-68)."""


def deciding_false_alarm_ids(score: PackageScore) -> list[str]:
    """The false alarms the verdict counts (17A, D15): model origin, and not tuned-on."""
    tuned_on = set(score.tuned_on_false_alarm_finding_ids)
    return [
        finding_id
        for finding_id in score.false_alarm_finding_ids
        if score.finding_origins.get(finding_id) in MODEL_ORIGINS and finding_id not in tuned_on
    ]


def finding_origin(finding: Finding, session: ReviewSession) -> Origin:
    """The origin of `finding` in `session`, by `scoring.md` 5.3's five rules, the first
    winning."""
    if finding.carried_over_from is not None:
        return "carried"
    if finding.source == "model":
        return "model"
    if session.origin_marks is None:
        return "unknown"
    if finding.tool_result_ids:
        cited = max(finding.tool_result_ids)
        step = next((one for one in session.steps if one.index == cited), None)
        if step is None:
            return "unknown"
        if step.origin_mark is not None:
            return step.origin_mark
        return "code_only_call" if step.tool in CODE_ONLY_TOOLS else "configured_check"
    if finding.check.startswith(SETUP_CHECK_PREFIXES):
        return "setup"
    return "configured_check"
