"""The benchmark set's summary: what a set holds, per judgement family (feature 014
`contracts/cases.md` 8; data-model section 5; FR-033, US5-2; plan decision CS-18).

`swreview benchmark set-summary <set file> [--answer-keys <dir>]` is its only printer; the case
generator never prints it, and nothing stores it. `summarize` reads the set (`sets.load_set`),
each package (`ir/loader.load_package`) and each key through the key's one reader,
`answer_key.load_answer_key`, found by `sets.key_path`, the one rule, so a keyed set names its
own keys and `--answer-keys` serves a set written before feature 014. It reads no case file and
contacts no provider.

Nothing here is re-derived (plan decision RF-67): a key's held-out model-produced defects are
`AnswerKey.held_out_model_defect_ids()`, and an entry's `held_out` flag is held to
`holds_held_out()` by the scorer's own `scorecard.held_out_flag_error`, so the flag's refusal has
one writer; a key naming another package than its entry is refused by
`scorecard.key_package_error`, the one writer of `answer-key.md` 4 row 2's set half. A family is
`families.family_of`'s and an anchor's `families.ANCHOR_FAMILY`'s, the one family rule.

## The rows

One per family, in `families.FAMILY_LABELS` order, an item counted once in each family it names:

- **held-out model-produced**: the defects each key's `held_out_model_defect_ids()` names;
- **with a clean twin**: of those, the ones some entry whose `twin_of` is their package keys as
  a correct condition with the same check and references, each covered item compared as the set
  of its references (`matching.covered_items`), so a fit's roles are not compared;
- **code-produced guards**: the known defects with `producer` `code`, held out or tuned on;
- **tuned-on items**: every entry tagged `tuned_on`. An entry on checks names the families of its
  check patterns; the part-roles question's count rule names `part_role`, the family no check
  reaches; an entry naming no check (expected coverage, an unanswerable request, an item's count
  rule) names `other`, this module's reading where the contract names only the part-roles rule;
- **anchors and analyst-found**: the `represents` ids of the set's entries, each once, by
  `ANCHOR_FAMILY`, in its order.

Then the total against `HELD_OUT_FLOOR`, printed and never refused (compare refuses the verdict,
`verdict.md` 7 row 4); the largest single design's share of that total, an entry naming no design
(every set written before feature 014) standing for its own, by its package id; the packages,
held out and private (outside the root, `sets.checkout_relative`); and each held-out item off
`current_stamp()`, through `stale_items`, the one lister, which the committed keys' stamp test
calls too (`cases.md` 5).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from swreview.agent.checklist import Checklist, load_checklist
from swreview.benchmark import matching
from swreview.benchmark.answer_key import current_stamp, load_answer_key
from swreview.benchmark.answer_key_model import (
    AnswerKey,
    CorrectCondition,
    ExpectedCoverage,
    ForbiddenEntry,
    KnownDefect,
    QuestionCount,
    Stamp,
    UnanswerableRequest,
)
from swreview.benchmark.families import ANCHOR_FAMILY, FAMILY_LABELS, Family, family_of
from swreview.benchmark.scorecard import held_out_flag_error, key_package_error
from swreview.benchmark.sets import (
    REPO_ROOT,
    BenchmarkPackageRef,
    checkout_relative,
    key_path,
    load_set,
)
from swreview.findings import first_refusal
from swreview.ir.loader import load_package
from swreview.ir.models import EvidencePackage, UnsupportedSchemaVersionError
from swreview.report.summary import Words, load_words

HELD_OUT_FLOOR = 34
"""FR-028's floor: the held-out model-produced defects a study set's keys name at least. The
summary prints a count below it and refuses nothing; compare refuses the verdict (`verdict.md` 7
row 4)."""

Item = (
    KnownDefect
    | CorrectCondition
    | ForbiddenEntry
    | ExpectedCoverage
    | UnanswerableRequest
    | QuestionCount
)
"""Any entry of a key's six lists (`answer-key.md` 2.1)."""

OTHER: frozenset[Family] = frozenset({"other"})
PART_ROLE: frozenset[Family] = frozenset({"part_role"})


@dataclass(frozen=True)
class FamilyRow:
    """One family's five columns (`cases.md` 8)."""

    held_out_model_produced: int
    with_a_clean_twin: int
    code_produced_guards: int
    tuned_on_items: int
    anchors: tuple[str, ...]
    """The anchors and analyst-found ids the set's entries represent, in `ANCHOR_FAMILY`'s
    order."""


@dataclass(frozen=True)
class SetSummary:
    """What `render_summary` prints of one set, never stored (data-model section 5)."""

    name: str
    packages: int
    held_out: int
    """The entries whose `held_out` flag is set, each flag held to its key."""

    private: int
    """The entries whose package lies outside the root."""

    designs: dict[str, int]
    """Each design's held-out model-produced defects, every design of the set, in set order."""

    rows: dict[Family, FamilyRow]
    """One row per family, in `FAMILY_LABELS` order."""

    held_out_model_produced: int
    """The total, read against `HELD_OUT_FLOOR`."""

    stale: list[str]
    """`stale_items` of the set's keys against `current_stamp()`."""

    @property
    def largest_design(self) -> tuple[str, int] | None:
        """The design holding the most held-out model-produced defects, with its count, the
        first in set order on a tie; `None` when no design holds one, so there is no share."""
        largest = max(self.designs.items(), key=lambda design: design[1], default=None)
        return largest if largest is not None and largest[1] > 0 else None


def summarize(
    set_path: Path | str, *, root: Path = REPO_ROOT, answer_keys: Path | None = None
) -> SetSummary:
    """The summary of the set at `set_path`, its paths resolved against `root` (`load_set`).

    Each entry's key is found by `sets.key_path` (its own in a keyed set, else
    `<answer_keys>/<package_id>.json`) and read against the entry's package, then held to the
    entry (`_key`). Refused, the first refusal ending the summary: a set `load_set` refuses (a
    `SetError`, as is a keyless set given no `answer_keys`), a package that cannot be read, a key
    the loader refuses (an `AnswerKeyError`), a key naming another package and a flag its key
    does not back, each one line naming the file or the package. A count below the floor is no
    refusal.
    """
    benchmark_set = load_set(set_path, root=root)
    checklist, words = load_checklist(), load_words()
    keyed = [
        (entry, _key(entry, answer_keys, checklist, words)) for entry in benchmark_set.packages
    ]
    rows = _rows(keyed)
    return SetSummary(
        name=benchmark_set.name,
        packages=len(keyed),
        held_out=sum(1 for entry, _ in keyed if entry.held_out),
        private=sum(1 for entry, _ in keyed if checkout_relative(entry.path, root=root) is None),
        designs=_designs(keyed),
        rows=rows,
        held_out_model_produced=sum(row.held_out_model_produced for row in rows.values()),
        stale=stale_items([key for _, key in keyed], current_stamp()),
    )


def stale_items(keys: Iterable[AnswerKey], stamp: Stamp) -> list[str]:
    """Each held-out item whose `held_out_against` is not `stamp`, as "{package} {id}", in the
    order of `keys`, the set's, and of each key's lists (`answer-key.md` 2.1): the one lister of
    stale items, which the summary calls with `current_stamp()` and the committed keys' stamp
    test too (`cases.md` 5). A tuned-on item holds no stamp and is never stale."""
    return [
        f"{key.package_id} {item.id}"
        for key in keys
        for item, _ in _items(key)
        if item.tag == "held_out" and item.held_out_against != stamp
    ]


def render_summary(summary: SetSummary) -> str:
    """The summary as `benchmark set-summary` prints it, one line each: the set; one line per
    family; the total against the floor; the largest design's share; one line per stale item."""
    total = summary.held_out_model_produced
    return "\n".join(
        [
            f"benchmark set {summary.name}: {summary.packages} packages ({summary.held_out} held "
            f"out, {summary.private} private), {len(summary.designs)} designs",
            *(
                f"{FAMILY_LABELS[family]}: held-out model-produced {row.held_out_model_produced}, "
                f"with a clean twin {row.with_a_clean_twin}, code-produced guards "
                f"{row.code_produced_guards}, tuned-on items {row.tuned_on_items}, anchors and "
                f"analyst-found {', '.join(row.anchors) or 'none'}"
                for family, row in summary.rows.items()
            ),
            f"held-out model-produced defects: {total} against the floor of {HELD_OUT_FLOOR}: "
            + ("met" if total >= HELD_OUT_FLOOR else f"below by {HELD_OUT_FLOOR - total}"),
            f"largest design share: {_share(summary.largest_design, total)}",
            *(f"stale: {item}" for item in summary.stale),
        ]
    )


def _share(largest: tuple[str, int] | None, total: int) -> str:
    """The largest design's share of `total`, "kalo 4 of 36, 11%", or "none" when no design
    holds a held-out model-produced defect."""
    if largest is None:
        return "none"
    design, count = largest
    return f"{design} {count} of {total}, {round(100 * count / total)}%"


def _key(
    entry: BenchmarkPackageRef, answer_keys: Path | None, checklist: Checklist, words: Words
) -> AnswerKey:
    """`entry`'s key, found by `sets.key_path` and read through the key's one reader against the
    entry's package, then held to the entry: the package it names first, then the flag, each
    refusal one `ValueError` line naming the package, the scorer's own words."""
    path = key_path(entry, answer_keys)
    key = load_answer_key(path, package=_package(entry), checklist=checklist, words=words)
    package_refusal = key_package_error(entry, key)
    if package_refusal is not None:
        raise ValueError(package_refusal)
    flag_refusal = held_out_flag_error(entry.package_id, entry.held_out, key)
    if flag_refusal is not None:
        raise ValueError(flag_refusal)
    return key


def _package(entry: BenchmarkPackageRef) -> EvidencePackage:
    """The package `entry` names, through `ir/loader.load_package`. One that cannot be read, a
    folder holding no `package.json` among them, is one `ValueError` line naming the entry, since
    the loader's own refusal of a malformed file names neither the entry nor its folder."""
    try:
        return load_package(entry.path).package
    except ValidationError as error:
        reason = first_refusal(error)
    except (OSError, UnsupportedSchemaVersionError) as error:
        reason = str(error)
    raise ValueError(f"{entry.package_id}: its package cannot be read ({reason})")


def _rows(keyed: list[tuple[BenchmarkPackageRef, AnswerKey]]) -> dict[Family, FamilyRow]:
    """The five columns of every family over the set's entries and their keys (`cases.md` 8)."""
    held_out: Counter[Family] = Counter()
    twinned: Counter[Family] = Counter()
    code: Counter[Family] = Counter()
    tuned_on: Counter[Family] = Counter()
    for entry, key in keyed:
        twin_keys = [twin_key for twin, twin_key in keyed if twin.twin_of == entry.package_id]
        for defect in _held_out_model_defects(key):
            family = family_of(defect.check)
            held_out[family] += 1
            if any(_keys_as_a_condition(twin_key, defect) for twin_key in twin_keys):
                twinned[family] += 1
        code.update(
            family_of(defect.check) for defect in key.known_defects if defect.producer == "code"
        )
        for item, named in _items(key):
            if item.tag == "tuned_on":
                tuned_on.update(named)
    represented = {anchor for entry, _ in keyed for anchor in entry.represents or []}
    return {
        family: FamilyRow(
            held_out_model_produced=held_out[family],
            with_a_clean_twin=twinned[family],
            code_produced_guards=code[family],
            tuned_on_items=tuned_on[family],
            anchors=tuple(
                anchor
                for anchor, of in ANCHOR_FAMILY.items()
                if of == family and anchor in represented
            ),
        )
        for family in FAMILY_LABELS
    }


def _designs(keyed: list[tuple[BenchmarkPackageRef, AnswerKey]]) -> dict[str, int]:
    """Each design's held-out model-produced defects, in set order. An entry naming no design, as
    in a set written before feature 014, stands for its own, by its package id: nothing says it
    shares a design with another."""
    designs: dict[str, int] = {}
    for entry, key in keyed:
        design = entry.design if entry.design is not None else entry.package_id
        designs[design] = designs.get(design, 0) + len(key.held_out_model_defect_ids())
    return designs


def _held_out_model_defects(key: AnswerKey) -> list[KnownDefect]:
    """The known defects `AnswerKey.held_out_model_defect_ids()` names, in key order (RF-67)."""
    ids = set(key.held_out_model_defect_ids())
    return [defect for defect in key.known_defects if defect.id in ids]


def _keys_as_a_condition(twin_key: AnswerKey, defect: KnownDefect) -> bool:
    """Whether `twin_key` keys `defect` as a correct condition: the same check, and the same
    covered items, each the set of its references (`matching.covered_items`)."""
    return any(
        condition.check == defect.check
        and set(matching.covered_items(condition)) == set(matching.covered_items(defect))
        for condition in twin_key.correct_conditions
    )


def _items(key: AnswerKey) -> list[tuple[Item, frozenset[Family]]]:
    """Every entry of `key`, in `answer-key.md` 2.1's order of its lists, with the families it
    names: an entry on checks those of its check patterns (`matching.entry_patterns`), each
    once; the part-roles question's count rule `part_role`; an entry naming no check `other`."""
    on_checks: list[KnownDefect | CorrectCondition | ForbiddenEntry] = [
        *key.known_defects,
        *key.correct_conditions,
        *key.forbidden,
    ]
    naming_no_check: list[ExpectedCoverage | UnanswerableRequest] = [
        *key.expected_coverage,
        *key.unanswerable_requests,
    ]
    return [
        *(
            (entry, frozenset(family_of(pattern) for pattern in matching.entry_patterns(entry)))
            for entry in on_checks
        ),
        *((entry, OTHER) for entry in naming_no_check),
        *((rule, PART_ROLE if rule.part_roles else OTHER) for rule in key.question_counts),
    ]
