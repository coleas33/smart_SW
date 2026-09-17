"""The library prefix matcher: four lists, one longest-match rule, never evaluation order (T005).

`contracts/profile.md` "Prefix semantics" is normative, and rules 5 and 6 exist because of a
defect in the macro this feature re-implements: its catch-all fasteners folder sat on the
two-mate list while its flat-head sub-folders sat on the one-mate list, and the one-mate list
won only because it happened to be tested first. Here the **longest** matching prefix decides,
within a list and across the two mate-count lists alike, and a tie falls to the one-mate
requirement. `test_the_longer_two_mate_prefix_wins` is the reversed case, which profile B
carries as a fixture row so it is exercised rather than assumed (FR-006).

Every profile these tests build is empty in every field the matcher does not read, which is
legal (`contracts/profile.md`, "Every key is required; every value may be empty") and keeps
invented values out of this file.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
import yaml

from swreview.checks.standards.library import PrefixMatch, PrefixMatcher
from swreview.checks.standards.profile import StandardsProfile, load_profile

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "standards"
PROFILE_A = FIXTURE_DIR / "profile-a.yaml"
PROFILE_B = FIXTURE_DIR / "profile-b.yaml"

LIST_NAMES = ("skip_prefixes", "sketch_exempt_prefixes", "one_mate_prefixes", "two_mate_prefixes")


def matcher(
    *,
    vault_root: str,
    skip: Sequence[str] = (),
    sketch_exempt: Sequence[str] = (),
    one_mate: Sequence[str] = (),
    two_mate: Sequence[str] = (),
) -> PrefixMatcher:
    """A matcher from a profile whose every other setting is empty."""
    profile: dict[str, Any] = {
        "version": 1,
        "vault_root": vault_root,
        "library": {
            "skip_prefixes": list(skip),
            "sketch_exempt_prefixes": list(sketch_exempt),
            "one_mate_prefixes": list(one_mate),
            "two_mate_prefixes": list(two_mate),
        },
        "data_card": {"properties": []},
        "part_number": {"pattern": ""},
        "revision": {
            "property": "",
            "initial": "",
            "header_text": "",
            "cell": {"row_from_end": 0, "column": 0},
        },
        "material": {"configuration": ""},
        "export_control": {"phrase": ""},
    }
    return PrefixMatcher.from_profile(StandardsProfile.model_validate(profile))


def library(path: Path) -> dict[str, list[str]]:
    """A fixture profile's four lists, as written."""
    return yaml.safe_load(path.read_text(encoding="utf-8"))["library"]


# --- rule 1: case-insensitive, path-normalized, anchored at the start ---------------------


@pytest.mark.parametrize(
    "path",
    [
        "D:/Vault/Library/Bonding/seal.SLDPRT",
        "d:/vault/library/bonding/seal.SLDPRT",
        "D:/VAULT/LIBRARY/BONDING/SEAL.SLDPRT",
        "D:\\Vault\\Library\\Bonding\\seal.SLDPRT",
        "D:/Vault/Library/Bonding/../Bonding/seal.SLDPRT",
        "D:/Vault/./Library/Bonding/seal.SLDPRT",
    ],
    ids=["as-written", "lower", "upper", "backslashes", "dot-dot", "dot"],
)
def test_a_path_matches_however_it_is_spelled(path: str) -> None:
    match = matcher(vault_root="D:/Vault", skip=["Library/Bonding/"]).match(path)

    assert match.skip == "Library/Bonding/"


@pytest.mark.parametrize("prefix", ["Library/Bonding/", "library\\bonding\\", "./Library/Bonding"])
def test_a_prefix_matches_however_it_is_spelled(prefix: str) -> None:
    match = matcher(vault_root="D:/Vault", skip=[prefix]).match("D:/Vault/Library/Bonding/a.SLDPRT")

    assert match.skip == prefix


def test_a_trailing_separator_on_the_path_is_ignored() -> None:
    """The folder itself is under the prefix that names it."""
    match = matcher(vault_root="D:/Vault", skip=["Library/Bonding/"]).match(
        "D:/Vault/Library/Bonding/"
    )

    assert match.skip == "Library/Bonding/"


def test_the_match_is_anchored_at_the_start() -> None:
    """A prefix in the middle of a path is not a prefix."""
    match = matcher(vault_root="D:/Vault", skip=["Library/Bonding/"]).match(
        "D:/Vault/Projects/Library/Bonding/a.SLDPRT"
    )

    assert match.skip is None


@pytest.mark.parametrize("entry", ["Library/Bonding/", "Library/Bonding"], ids=["sep", "no-sep"])
@pytest.mark.parametrize(
    "path",
    ["D:/Vault/Library/BondingTape/a.SLDPRT", "D:/Vault/Library/Bonding_old/a.SLDPRT"],
    ids=["longer-name", "suffixed-name"],
)
def test_a_sibling_whose_name_merely_starts_with_the_prefix_does_not_match(
    entry: str, path: str
) -> None:
    """Anchored at the start means anchored at a *segment* boundary, on every list.

    A folder named `Bonding` and a folder named `BondingTape` beside it are two folders. A
    string-prefix match would put the second one under the first one's entry, which on a
    release gate is a false SKIP - four part checks and the data-card check reported as
    skipped coverage for a document that should have been graded - and on the mate lists a
    silent reclassification of what a component is required to have. Both spellings of the
    entry are pinned, because rule 3 says a prefix is a prefix separator or not: the two
    spellings must not answer this differently.
    """
    subject = matcher(
        vault_root="D:/Vault",
        skip=[entry],
        sketch_exempt=[entry],
        one_mate=[entry],
        two_mate=[entry],
    )

    match = subject.match(path)

    assert match == PrefixMatch(
        skip=None,
        sketch_exempt=None,
        mate_requirement=0,
        mate_prefix=None,
        all_matches={name: [] for name in LIST_NAMES},
    )


def test_a_path_outside_the_vault_root_does_not_match_a_relative_prefix() -> None:
    match = matcher(vault_root="D:/Vault", skip=["Library/"]).match("E:/Scratch/Library/a.SLDPRT")

    assert match.skip is None


# --- rule 2: relative against the vault root, absolute as written -------------------------


def test_a_relative_prefix_resolves_against_the_vault_root() -> None:
    match = matcher(vault_root="D:/Vault", skip=["Library/"]).match("D:/Vault/Library/a.SLDPRT")

    assert match.skip == "Library/"


def test_an_absolute_prefix_matches_as_written() -> None:
    """The same file works on a second machine whose vault is mounted elsewhere - or not."""
    subject = matcher(vault_root="D:/Vault", skip=["E:/Shared/Library/"])

    assert subject.match("E:/Shared/Library/a.SLDPRT").skip == "E:/Shared/Library/"
    assert subject.match("D:/Vault/E:/Shared/Library/a.SLDPRT").skip is None


def test_a_vault_root_that_does_not_exist_on_this_machine_is_accepted() -> None:
    """A package can come from another machine; the match is textual and touches no disk."""
    match = matcher(vault_root="Z:/no-such-vault", skip=["Library/"]).match(
        "Z:/no-such-vault/Library/a.SLDPRT"
    )

    assert match.skip == "Library/"


def test_a_posix_vault_root_matches_a_posix_path() -> None:
    match = matcher(vault_root="/srv/vault", skip=["library/"]).match("/srv/vault/library/a.SLDPRT")

    assert match.skip == "library/"


# --- rule 3: a prefix is a prefix, separator or not ---------------------------------------


@pytest.mark.parametrize("prefix", ["Library/Bonding", "Library/Bonding/"])
@pytest.mark.parametrize(
    "path",
    ["D:/Vault/Library/Bonding", "D:/Vault/Library/Bonding/a.SLDPRT"],
    ids=["folder", "file"],
)
def test_a_prefix_matches_with_or_without_its_separator(prefix: str, path: str) -> None:
    assert matcher(vault_root="D:/Vault", skip=[prefix]).match(path).skip == prefix


def test_an_entry_naming_a_single_file_matches_that_file() -> None:
    """The macro's two-mate list mixed folder prefixes with one specific file (R5)."""
    subject = matcher(vault_root="D:/Vault", two_mate=["Projects/Shared/PART-1.SLDPRT"])

    match = subject.match("D:/Vault/Projects/Shared/PART-1.SLDPRT")

    assert match.mate_requirement == 2
    assert match.mate_prefix == "Projects/Shared/PART-1.SLDPRT"


def test_an_empty_entry_matches_nothing() -> None:
    """An empty string is not "every path"; a list that exempts everything is written out."""
    match = matcher(vault_root="D:/Vault", skip=[""]).match("D:/Vault/Library/a.SLDPRT")

    assert match.skip is None
    assert match.all_matches["skip_prefixes"] == []


# --- rule 4: the four lists are matched independently -------------------------------------


def test_a_match_in_one_list_never_cancels_a_match_in_another() -> None:
    subject = matcher(
        vault_root="D:/Vault",
        skip=["Library/Bonding/"],
        sketch_exempt=["Library/"],
        one_mate=["Library/Bonding/"],
        two_mate=["Library/"],
    )

    match = subject.match("D:/Vault/Library/Bonding/a.SLDPRT")

    assert match.skip == "Library/Bonding/"
    assert match.sketch_exempt == "Library/"
    assert match.mate_requirement == 1
    assert match.mate_prefix == "Library/Bonding/"


def test_a_path_in_no_list_answers_every_question_with_nothing() -> None:
    match = matcher(vault_root="D:/Vault", skip=["Library/"]).match("D:/Vault/Projects/a.SLDPRT")

    assert match == PrefixMatch(
        skip=None,
        sketch_exempt=None,
        mate_requirement=0,
        mate_prefix=None,
        all_matches={name: [] for name in LIST_NAMES},
    )


def test_every_list_is_named_in_all_matches_even_when_it_is_empty() -> None:
    match = matcher(vault_root="D:/Vault").match("D:/Vault/Library/a.SLDPRT")

    assert sorted(match.all_matches) == sorted(LIST_NAMES)


# --- rule 5: within a list, the longest match decides and every match is named -------------


def test_within_a_list_the_longest_match_decides() -> None:
    subject = matcher(
        vault_root="D:/Vault", skip=["Library/", "Library/Bonding/Tape/", "Library/Bonding/"]
    )

    match = subject.match("D:/Vault/Library/Bonding/Tape/a.SLDPRT")

    assert match.skip == "Library/Bonding/Tape/"


def test_every_match_in_a_list_is_named_in_profile_order() -> None:
    """The coverage reason names them all, so an engineer can see the whole picture."""
    subject = matcher(
        vault_root="D:/Vault",
        skip=["Library/", "Library/Bonding/Tape/", "Library/Bonding/", "Library/Wiring/"],
    )

    match = subject.match("D:/Vault/Library/Bonding/Tape/a.SLDPRT")

    assert match.all_matches["skip_prefixes"] == [
        "Library/",
        "Library/Bonding/Tape/",
        "Library/Bonding/",
    ]


def test_the_sketch_exemption_names_its_own_matches() -> None:
    subject = matcher(vault_root="D:/Vault", sketch_exempt=["Library/", "Library/Bonding/"])

    match = subject.match("D:/Vault/Library/Bonding/a.SLDPRT")

    assert match.sketch_exempt == "Library/Bonding/"
    assert match.all_matches["sketch_exempt_prefixes"] == ["Library/", "Library/Bonding/"]


# --- rule 6: across the two mate lists, longest wins; a tie falls to one mate --------------


def test_the_longer_one_mate_prefix_wins() -> None:
    """The macro's own case: a flat-head sub-folder inside the catch-all fasteners folder."""
    subject = matcher(
        vault_root="D:/Vault",
        one_mate=["Library/Fasteners/Flathead/"],
        two_mate=["Library/Fasteners/"],
    )

    match = subject.match("D:/Vault/Library/Fasteners/Flathead/a.SLDPRT")

    assert match.mate_requirement == 1
    assert match.mate_prefix == "Library/Fasteners/Flathead/"


def test_the_longer_two_mate_prefix_wins() -> None:
    """The reversed case, which evaluation order would have got wrong (FR-006)."""
    subject = matcher(
        vault_root="D:/Vault",
        one_mate=["Library/Hardware/"],
        two_mate=["Library/Hardware/Dowels/"],
    )

    match = subject.match("D:/Vault/Library/Hardware/Dowels/a.SLDPRT")

    assert match.mate_requirement == 2
    assert match.mate_prefix == "Library/Hardware/Dowels/"


def test_an_exact_tie_falls_to_the_one_mate_requirement() -> None:
    subject = matcher(
        vault_root="D:/Vault", one_mate=["Library/Hardware/"], two_mate=["library\\hardware\\"]
    )

    match = subject.match("D:/Vault/Library/Hardware/a.SLDPRT")

    assert match.mate_requirement == 1
    assert match.mate_prefix == "Library/Hardware/"


def test_both_mate_lists_name_their_matches_whichever_won() -> None:
    subject = matcher(
        vault_root="D:/Vault",
        one_mate=["Library/Hardware/"],
        two_mate=["Library/Hardware/Dowels/", "Library/"],
    )

    match = subject.match("D:/Vault/Library/Hardware/Dowels/a.SLDPRT")

    assert match.all_matches["one_mate_prefixes"] == ["Library/Hardware/"]
    assert match.all_matches["two_mate_prefixes"] == ["Library/Hardware/Dowels/", "Library/"]


def test_a_path_in_neither_mate_list_needs_no_mates() -> None:
    subject = matcher(vault_root="D:/Vault", one_mate=["Library/"], two_mate=["Catalog/"])

    match = subject.match("D:/Vault/Projects/a.SLDPRT")

    assert match.mate_requirement == 0
    assert match.mate_prefix is None


# --- empty lists exempt and reclassify nothing --------------------------------------------


def test_an_empty_list_is_never_itself_a_skip() -> None:
    """An empty exemption list says nothing is exempt, not that nothing is graded."""
    match = matcher(vault_root="D:/Vault").match("D:/Vault/Library/Bonding/a.SLDPRT")

    assert match.skip is None
    assert match.sketch_exempt is None
    assert match.mate_requirement == 0
    assert match.all_matches == {name: [] for name in LIST_NAMES}


# --- the two fixture profiles -------------------------------------------------------------


def test_profile_a_skips_a_library_part_and_exempts_its_sketches() -> None:
    lists = library(PROFILE_A)
    profile = load_profile(PROFILE_A)
    path = f"{profile.vault_root}/{lists['skip_prefixes'][0]}bracket.SLDPRT"

    match = PrefixMatcher.from_profile(profile).match(path)

    assert match.skip == lists["skip_prefixes"][0]
    assert match.sketch_exempt == lists["sketch_exempt_prefixes"][0]


def test_profile_a_takes_the_longer_one_mate_prefix() -> None:
    lists = library(PROFILE_A)
    profile = load_profile(PROFILE_A)
    one_mate = lists["one_mate_prefixes"][0]

    path = f"{profile.vault_root}/{one_mate}screw.SLDPRT"

    match = PrefixMatcher.from_profile(profile).match(path)

    assert match.mate_requirement == 1
    assert match.mate_prefix == one_mate
    assert match.all_matches["two_mate_prefixes"] != []


def test_profile_b_takes_the_longer_two_mate_prefix() -> None:
    """Profile B's two-mate entry is the longer of the overlapping pair, by construction."""
    lists = library(PROFILE_B)
    profile = load_profile(PROFILE_B)
    two_mate = lists["two_mate_prefixes"][0]
    one_mate = lists["one_mate_prefixes"][0]
    assert two_mate.casefold().startswith(one_mate.casefold())

    path = f"{profile.vault_root}/{two_mate}dowel.SLDPRT"

    match = PrefixMatcher.from_profile(profile).match(path)

    assert match.mate_requirement == 2
    assert match.mate_prefix == two_mate
    assert match.all_matches["one_mate_prefixes"] == [one_mate]


def test_a_document_path_written_relative_to_the_vault_is_matched_too() -> None:
    """A package may carry a vault-relative path; it is resolved the way a prefix is."""
    lists = library(PROFILE_A)
    profile = load_profile(PROFILE_A)

    match = PrefixMatcher.from_profile(profile).match(f"{lists['skip_prefixes'][1]}loom.SLDPRT")

    assert match.skip == lists["skip_prefixes"][1]
