"""The dump and grade artifacts of one re-model run (T091).

Five of the files in `contracts/run-artifacts.md` are written here, and not one rule is
evaluated in this module:

| File | What it is |
|---|---|
| `package-before.json` | the `ModelCheck`-profile dump of the copy at open, handed in |
| `package-after.json` | the same dump after the last change, handed in |
| `rms-before.json` | feature 003's `run_rms_check` over the first |
| `rms-after.json` | feature 003's `run_rms_check` over the second |
| `grades.json` | feature 003's `RmsGrade` before and after, plus the per-rule delta |

The dumps are **handed in** rather than taken here: they come off the bridge, from the
extractor's own dumper, and a module that went and got them would need a seat to be tested
at all. What this module owns is where they are filed, what is graded against what, and
which waivers are in force while that happens.

Three decisions carry the file.

**One store, refreshed once.** The two grades are only comparable if they were measured
against the same waivers (`contracts/run-artifacts.md`, "Exceptions carry-forward"). The
carried store is rebound to the copy, `ExceptionStore.refresh` is asked once - against
`package-before.json` - and the resulting store is handed to both `run_rms_check` calls
through its `exceptions` parameter. It is not refreshed again for the after grade, because
`fingerprint_kind_for` makes every `rms.*` exception a `feature_tree` fingerprint over
every feature row in index order: a second refresh would re-open every waiver over the
rename and the reorder this run just made, and move the delta for exactly the reason a
grade delta is supposed to be readable.

**Rebinding is to the copy, and it is the whole binding.** A `ReviewException` is bound to
`(persist_ref, persist_ref_scope)` pairs and carries a digest of the tree it was accepted
over. Both halves are path-derived: `persist_ref_scope` is a `document_id`, and the
`feature_tree` digest covers the document's id along with its rows. The copy is a byte copy
of the source, attested by hash, taken before any handle existed - the same tree under a
new path - so a carried exception is re-bound to it through `ExceptionStore.reaccept`,
which is feature 001's one re-bind operation and is not re-implemented here. Only `active`
exceptions are re-bound: a `needs_review` or `retired` one is the engineer's own decision
and this run does not reopen it. What that rebind cannot tell apart - a source that moved
between the waiver and this run - is not knowable from a dump of the copy alone, and is
named as a coverage limit by `report.py` rather than guessed at.

**The subject is a part opened alone**, so the part and equation families run and the
assembly family does not. It is not folded in under the `all` alias for the same reason
`POST /checks/rms` refuses it by name: those four rules are uncalibrated, and running them
over a package with no assembly document would report four rules unresolved about a
document that is not there.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from swreview.checks.rms.grade import RmsGrade, RmsGradeDelta, delta
from swreview.checks.rms.registry import RULES
from swreview.checks.rms.results import RuleOutcome
from swreview.checks.rms.run import (
    CarriedForward,
    RmsCheckRun,
    RmsScope,
    carry_forward,
    run_rms_check,
)
from swreview.exceptions import EXCEPTIONS_FILE_NAME, ExceptionStore, ReviewException
from swreview.ir.loader import PACKAGE_FILE_NAME, save_package
from swreview.ir.models import EvidencePackage
from swreview.remodel.plan import PACKAGE_BEFORE, part_document_ids

__all__ = [
    "ATTESTATION_FILE_NAME",
    "GRADES_FILE_NAME",
    "PACKAGE_AFTER",
    "RMS_AFTER_FILE_NAME",
    "RMS_BEFORE_FILE_NAME",
    "RMS_FAMILIES",
    "GradedRun",
    "NotAModelCheckDumpError",
    "RuleDelta",
    "Side",
    "carry_forward_exceptions",
    "grade_remodel_run",
    "rebind_to_copy",
    "rule_deltas",
    "write_package",
]

PACKAGE_AFTER = "package-after.json"
"""The dump of the copy after the last change. `PACKAGE_BEFORE` is `plan.py`'s, because
the plan names it and a second spelling is how the two would drift apart."""

RMS_BEFORE_FILE_NAME = "rms-before.json"
RMS_AFTER_FILE_NAME = "rms-after.json"
GRADES_FILE_NAME = "grades.json"

ATTESTATION_FILE_NAME = "source-attestation.json"
"""Where a prior `-remodel` run records the design id of **its source**. Its packages are
dumps of its own copy, so this is the only field in that folder the carry-forward can
match on (`contracts/run-artifacts.md`)."""

Side = Literal["before", "after"]

_ARTIFACT: dict[Side, str] = {"before": PACKAGE_BEFORE, "after": PACKAGE_AFTER}

_RMS_ARTIFACT: dict[Side, str] = {
    "before": RMS_BEFORE_FILE_NAME,
    "after": RMS_AFTER_FILE_NAME,
}

_WORK_DIR: dict[Side, str] = {"before": "rms-before", "after": "rms-after"}
"""Where each side's check actually runs.

`run_rms_check` grades the `package.json` of a directory and writes its `session.json`,
`report.md` and `check.json` beside it. The run folder already has a `session.json` - the
agent's - and its `report.md` is the engineer-facing product, so each check is given its
own folder under the run folder and the two artifacts the contract names are filed at the
top. Nothing is hidden by this: the check's own session and report stay on disk, under the
name of the grade they belong to, which is what Principle VI asks of evidence."""

RMS_FAMILIES: tuple[RmsScope, ...] = (RmsScope.part, RmsScope.equations)
"""The families a part opened alone is graded by; see the module docstring."""

NOT_MODEL_CHECK = (
    "the {side} dump was written by the {profile!r} dump profile; the re-modeler's "
    "packages are the ModelCheck-profile dumps of the copy that feature 003 US6 produces "
    "(contracts/run-artifacts.md), and filing another profile under {name} would say "
    "something untrue about what was graded"
)

TWO_DOCUMENTS = (
    "the before dump carries part {before} and the after dump carries part {after}; both "
    "are dumps of the same copy, so a run that graded two different documents has filed "
    "one of them in the wrong place"
)

_OUTCOME_BY_BUCKET: dict[str, str] = {
    "checked": "pass",
    "skipped": "skip",
    "unresolved": "unresolved",
    "out_of_scope": "out_of_scope",
}
"""A coverage bucket as the outcome the rule layer reached to land in it. The `failed`
bucket is not here: it holds tool failures, which are not rule results."""

_OUTCOME_BY_STATUS: dict[str, str] = {
    "demonstrated": "fail",
    "suspected": "warn",
    "checked_within_scope": "pass",
    "unresolved": "unresolved",
}
"""A recorded finding's status as the outcome behind it, the same mapping `grade.py` reads
from the other side. `checked_within_scope` is `pass` because a waived condition is
reported as checked within scope, which is what an acceptance means."""

_WORST_FIRST: tuple[str, ...] = (
    "fail",
    "warn",
    "unresolved",
    "skip",
    "out_of_scope",
    "pass",
)
"""How one rule's several entries - one per document, one per outcome it reached - become
the one outcome the delta names: the most alarming of them. A rule that failed on one
subject and passed on the rest is a rule that failed."""

Outcome = RuleOutcome | Literal["out_of_scope"]


class NotAModelCheckDumpError(ValueError):
    """A dump handed in under a profile the re-modeler's artifacts are not."""


class RuleDelta(BaseModel):
    """What one rule did between the two grades (`data-model.md` section 6)."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    rule_id: str
    before_outcome: Outcome | None
    after_outcome: Outcome | None
    """`None` when the rule reached no outcome at all on that side - it was never
    dispatched there. Absent is not a pass and is not written as one."""

    subjects_before: tuple[str, ...]
    subjects_after: tuple[str, ...]


@dataclass(frozen=True)
class GradedRun:
    """Everything the grade artifacts produced, and where each of them was written."""

    run_dir: Path
    package_before: Path
    package_after: Path
    rms_before: Path
    rms_after: Path
    grades_file: Path
    before: RmsCheckRun
    after: RmsCheckRun
    delta: RmsGradeDelta
    per_rule: tuple[RuleDelta, ...]
    carried_forward: CarriedForward
    exceptions: ExceptionStore | None
    """The one store both grades were measured against; `None` when none was carried."""

    rebound: tuple[str, ...]
    """The exceptions re-bound from the source to the copy, by id."""

    flagged: tuple[str, ...]
    """The exceptions the one `refresh` against `package-before.json` set
    `needs_review`, by id. Reported rather than silent: an exception that stopped
    waiving is why a rule came back, and a reader has to be able to see that."""


# --- 1. the two dumps -------------------------------------------------------------


def write_package(run_dir: Path | str, package: EvidencePackage, *, side: Side) -> Path:
    """File `package` as this run's `before` or `after` dump, and return the artifact.

    Written twice on purpose, and byte-identically: once as the check's own `package.json`
    in that side's working folder, where `run_rms_check` reads it, and once under the
    contract's name at the top of the run folder, where the pane and the report read it.
    The second is a byte copy of the first, so the two can never be different serializings
    of the same package.
    """
    directory = Path(run_dir)
    if package.extractor.profile != "model_check":
        raise NotAModelCheckDumpError(
            NOT_MODEL_CHECK.format(
                side=side, profile=package.extractor.profile, name=_ARTIFACT[side]
            )
        )
    package_file = save_package(package, directory / _WORK_DIR[side])
    target = directory / _ARTIFACT[side]
    shutil.copyfile(package_file, target)
    return target


# --- 2. the waivers both grades are measured against ------------------------------


def carry_forward_exceptions(
    run_dir: Path | str, *, source_design_id: str, run_root: Path | str | None
) -> CarriedForward:
    """Copy the newest same-**source** `exceptions.json` under `run_root` into `run_dir`.

    Feature 003's helper does the copying, the newest-wins ordering and the refusal of an
    unreadable candidate; what feature 004 supplies is how a candidate's source design is
    read, because this run's own packages are dumps of the copy and carry the copy's
    path-derived id. Matching on that id would select no candidate ever - not a Model
    check run's, and not a previous remodel run's.
    """
    return carry_forward(
        Path(run_dir),
        design_id=source_design_id,
        run_root=run_root,
        design_id_of=source_design_id_of,
    )


def source_design_id_of(directory: Path) -> str | None:
    """The design id of the **source** an earlier run folder was about, or `None`.

    A `-remodel` folder records it in `source-attestation.json` and nowhere else: its
    `package-before.json` is a dump of its own copy. A `-check` folder's package is a dump
    of the source itself, so its `design.design_id` is the source's. A folder carrying
    neither field is not a candidate; it is not refused either, because it is not this
    run's evidence and may be a folder no run of ours ever wrote.
    """
    attested = _json_field(directory / ATTESTATION_FILE_NAME, "source_design_id")
    if attested is not None:
        return attested
    design = _json_object(directory / PACKAGE_FILE_NAME, "design")
    return None if design is None else _string(design.get("design_id"))


def rebind_to_copy(
    store: ExceptionStore, package: EvidencePackage, document_id: str
) -> tuple[ReviewException, ...]:
    """Re-bind every active exception in `store` from the source to the copy.

    Two steps, in this order. The binding scopes are rewritten to the copy's document,
    because without that the pairs resolve against a dump of the copy to nothing and the
    store is effectively empty - the failure the carry-forward exists to prevent. Then
    feature 001's `reaccept` re-binds the exception to this package, which is the copy's
    tree: the same rows the waiver was granted over, under the copy's path-derived id.

    An exception whose components the copy does not carry is left with its scopes
    rewritten and its digest untouched, so the `refresh` that follows flags it
    `needs_review` rather than letting an unverifiable binding go on silencing a rule.

    Returns the exceptions that were re-bound, in store order.
    """
    rebound: list[ReviewException] = []
    for exception in store.exceptions:
        if exception.status != "active":
            continue
        exception.persist_ref_scopes = [document_id] * len(exception.component_persist_refs)
        try:
            store.reaccept(exception.id, package)
        except LookupError:
            continue
        rebound.append(exception)
    return tuple(rebound)


# --- 3. the per-rule delta --------------------------------------------------------


def rule_deltas(before: RmsCheckRun, after: RmsCheckRun) -> tuple[RuleDelta, ...]:
    """Every rule whose outcome moved between the two grades, in rule id order.

    A rule whose outcome is the same on both sides is not a row, even when it names
    different subjects: this run renames features, and a waived rule reported against
    `Fillet1` before and `Fillet1_2` after has not moved. What moved is the outcome.
    """
    was, subjects_before = _outcomes(before)
    now, subjects_after = _outcomes(after)
    return tuple(
        RuleDelta(
            rule_id=rule_id,
            before_outcome=was.get(rule_id),
            after_outcome=now.get(rule_id),
            subjects_before=subjects_before.get(rule_id, ()),
            subjects_after=subjects_after.get(rule_id, ()),
        )
        for rule_id in sorted(set(was) | set(now))
        if was.get(rule_id) != now.get(rule_id)
    )


def _outcomes(
    run: RmsCheckRun,
) -> tuple[dict[str, Outcome], dict[str, tuple[str, ...]]]:
    """One outcome and the subjects named, per rule, from what the check recorded.

    Both halves of the record are read - the coverage, which is where a rule that passed,
    skipped or went unresolved lands, and the findings, which is where a rule that failed,
    warned or was waived lands - because neither alone is the whole of what a rule did.
    Anything whose check is not a rule id is not a rule and is not counted, exactly as
    `grade.py` does not count it.
    """
    reached: dict[str, list[str]] = {}
    subjects: dict[str, set[str]] = {}
    for row in run.coverage:
        check = str(row["check"])
        outcome = _OUTCOME_BY_BUCKET.get(str(row["bucket"]))
        if check in RULES and outcome is not None:
            reached.setdefault(check, []).append(outcome)
    for finding in run.findings:
        check = str(finding["check"])
        if check not in RULES:
            continue
        reached.setdefault(check, []).append(_OUTCOME_BY_STATUS[str(finding["status"])])
        named = subjects.setdefault(check, set())
        for subject in run.subjects.get(str(finding["id"]), ()):
            feature_id = subject.get("feature_id")
            if isinstance(feature_id, str):
                named.add(feature_id)
    worst = {
        rule_id: _worst(outcomes) for rule_id, outcomes in reached.items()
    }
    return worst, {rule_id: tuple(sorted(named)) for rule_id, named in subjects.items()}


def _worst(outcomes: Sequence[str]) -> Outcome:
    for outcome in _WORST_FIRST:
        if outcome in outcomes:
            return outcome  # type: ignore[return-value]
    raise AssertionError(f"{outcomes} holds no outcome this build knows")


# --- 4. the run ------------------------------------------------------------------


def grade_remodel_run(
    run_dir: Path | str,
    *,
    before: EvidencePackage,
    after: EvidencePackage,
    source_design_id: str,
    run_root: Path | str | None = None,
    document_id: str | None = None,
) -> GradedRun:
    """File both dumps, grade each of them, and write `grades.json`.

    Args:
        run_dir: This run's folder.
        before: The `ModelCheck` dump of the copy at open.
        after: The same dump after the last change.
        source_design_id: The **source's** design id, as `source-attestation.json`
            records it. It is what the exceptions carry-forward matches on; this run's
            own packages carry the copy's id and would match nothing.
        run_root: The run root whose earlier folders a waiver may be carried forward from.
            `None` carries nothing forward and says so, exactly as a check does.
        document_id: The part being graded, when the dumps carry more than one.

    Raises:
        NotAModelCheckDumpError: a dump was written by another profile.
        ValueError: the two dumps do not carry the same part document.
        UnreadableExceptionsError: the carry-forward candidate cannot be parsed.
    """
    directory = Path(run_dir)
    package_before = write_package(directory, before, side="before")
    package_after = write_package(directory, after, side="after")
    document = _one_part(before, after, document_id)

    carried = carry_forward_exceptions(
        directory, source_design_id=source_design_id, run_root=run_root
    )
    store = _carried_store(directory)
    rebound: tuple[ReviewException, ...] = ()
    flagged: list[ReviewException] = []
    if store is not None:
        rebound = rebind_to_copy(store, before, document)
        flagged = store.refresh(before)

    before_run = _grade(directory, "before", document, store)
    after_run = _grade(directory, "after", document, store)
    rms_before = _write_rms(directory, "before", before_run)
    rms_after = _write_rms(directory, "after", after_run)
    per_rule = rule_deltas(before_run, after_run)
    grades_file = _write_grades(directory, before_run.grade, after_run.grade, per_rule)

    return GradedRun(
        run_dir=directory,
        package_before=package_before,
        package_after=package_after,
        rms_before=rms_before,
        rms_after=rms_after,
        grades_file=grades_file,
        before=before_run,
        after=after_run,
        delta=delta(before_run.grade, after_run.grade),
        per_rule=per_rule,
        carried_forward=carried,
        exceptions=store,
        rebound=tuple(item.id for item in rebound),
        flagged=tuple(item.id for item in flagged),
    )


def _grade(
    run_dir: Path, side: Side, document_id: str, store: ExceptionStore | None
) -> RmsCheckRun:
    """One side's check, over the dump already filed in that side's working folder."""
    return run_rms_check(
        run_dir / _WORK_DIR[side],
        scope=RmsScope.all,
        document_id=document_id,
        families=RMS_FAMILIES,
        exceptions=store,
    )


def _write_rms(run_dir: Path, side: Side, run: RmsCheckRun) -> Path:
    """One side's check as `rms-<side>.json`, naming the dump it was taken over."""
    carried = run.exceptions_carried_forward
    body = {
        "package": _ARTIFACT[side],
        "scope": run.scope.value,
        "families": [family.value for family in RMS_FAMILIES],
        "documents": run.documents,
        "assembly_document": run.assembly_document,
        "grade": run.grade.as_dict(),
        "findings": run.findings,
        "subjects": run.subjects,
        "coverage": run.coverage,
        "exceptions_carried_forward": {
            "from_run": carried.from_run,
            "count": carried.count,
            "reason": carried.reason,
        },
        "unavailable_scopes": run.unavailable_scopes,
        "session": _relative(run_dir, run.session_file),
        "report": _relative(run_dir, run.report_file),
        "check": _relative(run_dir, run.check_file),
    }
    return _write_json(run_dir / _RMS_ARTIFACT[side], body)


def _write_grades(
    run_dir: Path, before: RmsGrade, after: RmsGrade, per_rule: Sequence[RuleDelta]
) -> Path:
    """`grades.json`: both grades as feature 003 renders them, and what moved.

    `RmsGrade.as_dict` is what the Model check tab renders too, so the tab and the report
    cannot show two different numbers for one part. There is no letter here and there is
    nothing to derive one from.
    """
    body = {
        "before": before.as_dict(),
        "after": after.as_dict(),
        "per_rule": [row.model_dump(mode="json") for row in per_rule],
    }
    return _write_json(run_dir / GRADES_FILE_NAME, body)


# --- helpers ----------------------------------------------------------------------


def _one_part(
    before: EvidencePackage, after: EvidencePackage, document_id: str | None
) -> str:
    """The one part document both dumps are of, or a `ValueError` naming the two."""
    selected = document_id if document_id is not None else part_document_ids(before)[0]
    in_before = part_document_ids(before, [selected])[0]
    in_after = part_document_ids(after, [selected] if document_id is not None else None)[0]
    if in_before != in_after:
        raise ValueError(TWO_DOCUMENTS.format(before=in_before, after=in_after))
    return in_before


def _carried_store(run_dir: Path) -> ExceptionStore | None:
    """The `exceptions.json` this run carried forward, loaded, or `None`."""
    path = run_dir / EXCEPTIONS_FILE_NAME
    if not path.is_file():
        return None
    return ExceptionStore(path).load()


def _write_json(path: Path, body: Any) -> Path:
    path.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
    return path


def _relative(run_dir: Path, path: Path) -> str:
    """`path` named from the run folder, so the folder stays valid when it is moved."""
    return path.relative_to(run_dir.resolve()).as_posix()


def _json_field(path: Path, field: str) -> str | None:
    body = _json_object(path, None)
    return None if body is None else _string(body.get(field))


def _json_object(path: Path, field: str | None) -> dict[str, Any] | None:
    """`path` as a JSON object, or one member of it; `None` when it is neither.

    Read as JSON rather than through a model: this asks one question of every sibling run
    folder, and validating each of their artifacts to answer it would make the cost of a
    run grow with the number of runs the engineer has kept.
    """
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(body, dict):
        return None
    if field is None:
        return body
    found = body.get(field)
    return found if isinstance(found, dict) else None


def _string(value: Any) -> str | None:
    return value if isinstance(value, str) else None
