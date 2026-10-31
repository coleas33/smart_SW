"""The fakes that assume a seat's answer name the probe that checks it (004 T339; decision 166A).

A fake answers as the seat is expected to; until a probe has run on the seat, that expectation is
only an assumption, and the tests built on the fake inherit it. Each such fake carries one comment
per assumption, next to the member that makes it:

    seat-assumption: PROBE-<n> <verdict>[|<verdict>] - <what the fake assumes>

where the verdicts are the ledger verdicts under which the fake still models the seat. A ledger's
`unresolved`, or no row, settles nothing; a `verified` or `refuted` the tag does not list refutes
the assumption, and this test turns red so the fake and the tests on it are looked at again.

With no ledger committed under `benchmarks/native/capabilities/` the test checks that the tags
are where they belong and parse; a fictional ledger that refutes one shows the check goes red.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pytest

from swreview.remodel.ledger import Ledger, load_ledger, parse_ledger
from tests.support.remodel_ledger import GOLDEN_LEDGER, committed_ledgers, rendered_ledger
from tests.support.seat_tasks import REPO

FAKES = REPO / "extractor" / "SwReview.Extractor.Tests" / "Fakes"
SUPPORT = REPO / "reviewer" / "tests" / "support"

TAG = re.compile(
    r"seat-assumption: (PROBE-\d+) ((?:verified|refuted)(?:\|(?:verified|refuted))*) - (\S.*)$"
)
COMMENT = re.compile(r"^\s*(?://|#)")

TAGGED: dict[Path, list[tuple[str, frozenset[str], str]]] = {
    FAKES / "RemodelProbeHostFakes.cs": [
        ("PROBE-1", frozenset({"verified", "refuted"}), "public sealed class ParkingReorder"),
    ],
    FAKES / "RemodelFakes.cs": [
        ("PROBE-1", frozenset({"verified"}), "public bool ReorderFeature(string featureName,"),
        ("PROBE-3", frozenset({"verified"}), "public bool ReorderFeature(string featureName,"),
        ("PROBE-4", frozenset({"verified"}), "public object? InsertFeatureTreeFolder(int type)"),
    ],
    SUPPORT / "remodel_bridge.py": [
        ("PROBE-6", frozenset({"verified", "refuted"}), "equation_wrote_nothing: frozenset[int]"),
        ("PROBE-4", frozenset({"verified"}), "def _wrap(self, name: str, members:"),
    ],
}
"""Each tagged file's assumptions, in file order: the probe, the verdicts it holds under, and the
start of the code line the tag stands above (004 research R27.6)."""


@dataclass(frozen=True)
class Assumption:
    file: Path
    line: int
    probe: str
    verdicts: frozenset[str]
    says: str
    member: str
    """The first code line after the tag, other comments and doc comments skipped."""

    def __str__(self) -> str:
        return f"{self.file.name}:{self.line} {self.probe} {'|'.join(sorted(self.verdicts))}"


def assumptions(path: Path) -> list[Assumption]:
    """Every tag in `path`, in order; a line that names a tag and does not parse fails here."""
    lines = path.read_text(encoding="utf-8").splitlines()
    found: list[Assumption] = []
    for index, line in enumerate(lines):
        if "seat-assumption:" not in line:
            continue
        match = TAG.search(line)
        assert match is not None and COMMENT.match(line), f"{path.name}:{index + 1}: {line.strip()}"
        member = next(
            later.strip() for later in lines[index + 1 :]
            if later.strip() and not COMMENT.match(later)
        )
        found.append(
            Assumption(path, index + 1, match.group(1), frozenset(match.group(2).split("|")),
                       match.group(3), member)
        )
    return found


def all_assumptions() -> list[Assumption]:
    return [assumption for path in TAGGED for assumption in assumptions(path)]


def refuted(tagged: list[Assumption], ledger: Ledger) -> list[Assumption]:
    """The assumptions `ledger` settles the other way: a definite verdict the tag does not list."""
    out: list[Assumption] = []
    for assumption in tagged:
        row = ledger.row(assumption.probe)
        settled = row is not None and row.verdict != "unresolved"
        if settled and row.verdict not in assumption.verdicts:
            out.append(assumption)
    return out


def test_each_fake_carries_its_assumptions_beside_the_member_that_makes_them() -> None:
    catalog = re.findall(
        r'new RemodelProbeDefinition\(\s*"(PROBE-\d+)"',
        (REPO / "extractor" / "SwReview.Extractor" / "Rms" / "RemodelProbe.cs").read_text(
            encoding="utf-8"
        ),
    )

    for path, expected in TAGGED.items():
        found = assumptions(path)
        assert [(item.probe, item.verdicts) for item in found] == [
            (probe, verdicts) for probe, verdicts, _ in expected
        ], path.name
        for item, (_, _, member) in zip(found, expected, strict=True):
            assert item.member.startswith(member), str(item)
            assert item.probe in catalog, str(item)


def test_no_other_file_in_the_fakes_or_the_support_carries_a_tag() -> None:
    """A tag added elsewhere joins `TAGGED`, so it is checked too."""
    tagged = {
        path for folder, pattern in ((FAKES, "*.cs"), (SUPPORT, "*.py"))
        for path in folder.glob(pattern)
        if "seat-assumption: PROBE-" in path.read_text(encoding="utf-8")
    }

    assert tagged == set(TAGGED)


def test_every_committed_ledger_agrees_with_the_tagged_assumptions() -> None:
    tagged = all_assumptions()

    for path in committed_ledgers():
        assert [str(item) for item in refuted(tagged, load_ledger(path))] == [], path.name


@pytest.mark.parametrize(
    ("verdicts", "refutes"),
    [
        ({"PROBE-4": "refuted"}, ["RemodelFakes.cs PROBE-4", "remodel_bridge.py PROBE-4"]),
        ({"PROBE-1": "refuted"}, ["RemodelFakes.cs PROBE-1"]),
        ({"PROBE-3": "refuted", "PROBE-6": "refuted"}, ["RemodelFakes.cs PROBE-3"]),
        ({"PROBE-1": "unresolved", "PROBE-3": "unresolved", "PROBE-4": "unresolved"}, []),
        ({"PROBE-1": "verified", "PROBE-3": "verified", "PROBE-4": "verified",
          "PROBE-6": "verified"}, []),
    ],
    ids=["probe-4-refuted", "probe-1-refuted", "probe-3-refuted", "unresolved", "all-verified"],
)
def test_a_fictional_ledger_that_refutes_an_assumption_turns_the_check_red(
    verdicts: dict[str, str], refutes: list[str]
) -> None:
    ledger = parse_ledger(
        rendered_ledger(
            [(probe, True, verdict, {"reason": "fictional"}) for probe, verdict in verdicts.items()]
        )
    )

    found = refuted(all_assumptions(), ledger)

    assert [f"{item.file.name} {item.probe}" for item in found] == refutes


def test_the_golden_ledger_refutes_no_assumption() -> None:
    assert refuted(all_assumptions(), load_ledger(GOLDEN_LEDGER)) == []
