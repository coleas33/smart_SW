"""The library prefix matcher: which of the profile's four lists a document path is in.

`specs/006-standards-check/contracts/profile.md` "Prefix semantics" is normative. Two of its
six rules are corrections of a defect in the macro this feature re-implements, and both are
implemented here as **one** rule rather than as a special case:

- **Within a list, the longest matching prefix decides, and every match is named.** The
  coverage reason quotes the entries as the engineer wrote them, so a surprising answer can be
  traced to the line that produced it.
- **Across the two mate-count lists, the longest matching prefix decides; on an exact tie the
  one-mate requirement wins.** The macro's catch-all fasteners folder sat on its two-mate list
  while its flat-head sub-folders sat on its one-mate list, and the one-mate list won only
  because it was tested first. Under a longest-match rule the same answer falls out of the
  longer prefix, and the reversed case - a *two*-mate prefix that is the longer one - gets the
  answer evaluation order would have got wrong (FR-006).

Matching is **textual**: no path here is resolved against the disk. A package can come from
another machine, so a vault root that does not exist locally is accepted and `.`/`..` segments
are resolved in the string. A path written relative to the vault is resolved against
`vault_root` exactly as a relative prefix is: comparing a relative path against absolute
prefixes would answer "no match" for every list, which is a silent wrong answer rather than a
visible one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from swreview.checks.standards.profile import StandardsProfile

__all__ = ["LIST_NAMES", "LibraryPrefix", "MateRequirement", "PrefixMatch", "PrefixMatcher"]

LIST_NAMES: tuple[str, ...] = (
    "skip_prefixes",
    "sketch_exempt_prefixes",
    "one_mate_prefixes",
    "two_mate_prefixes",
)
"""The four lists, named as the profile names them, which is what a reason quotes."""

MateRequirement = Literal[0, 1, 2]
"""How many unsuppressed mates an under-constrained component under this path needs."""

_ABSOLUTE = re.compile(r"^(?:[A-Za-z]:[\\/]|[\\/])")


@dataclass(frozen=True, slots=True)
class LibraryPrefix:
    """One profile entry: what the engineer wrote, and what it is compared as."""

    written: str
    normalized: str


@dataclass(frozen=True, slots=True)
class PrefixMatch:
    """What the four lists say about one document path.

    `skip` and `sketch_exempt` are the longest matching entry of their list, as written, or
    `None`. `mate_requirement` is `0` when neither mate-count list matched, and otherwise the
    requirement of the longest matching prefix across the two lists together. `all_matches`
    carries **every** match of every list, in profile order, for the coverage reason.
    """

    skip: str | None
    sketch_exempt: str | None
    mate_requirement: MateRequirement
    mate_prefix: str | None
    all_matches: dict[str, list[str]]


@dataclass(frozen=True, slots=True)
class PrefixMatcher:
    """The profile's four lists, normalized once, ready to match paths against."""

    skip: tuple[LibraryPrefix, ...]
    sketch_exempt: tuple[LibraryPrefix, ...]
    one_mate: tuple[LibraryPrefix, ...]
    two_mate: tuple[LibraryPrefix, ...]
    root: str
    """The profile's `vault_root`, normalized once; relative entries resolve against it."""

    @classmethod
    def from_profile(cls, profile: StandardsProfile) -> PrefixMatcher:
        root = normalize(profile.vault_root)
        return cls(
            skip=_prepare(profile.library.skip_prefixes, root),
            sketch_exempt=_prepare(profile.library.sketch_exempt_prefixes, root),
            one_mate=_prepare(profile.library.one_mate_prefixes, root),
            two_mate=_prepare(profile.library.two_mate_prefixes, root),
            root=root,
        )

    def match(self, path: str) -> PrefixMatch:
        """Answer all four questions about `path`, independently of one another."""
        subject = _resolve(path, self.root)
        matches = {
            "skip_prefixes": _matching(self.skip, subject),
            "sketch_exempt_prefixes": _matching(self.sketch_exempt, subject),
            "one_mate_prefixes": _matching(self.one_mate, subject),
            "two_mate_prefixes": _matching(self.two_mate, subject),
        }
        requirement, mate_prefix = _mate_requirement(
            matches["one_mate_prefixes"], matches["two_mate_prefixes"]
        )
        return PrefixMatch(
            skip=_longest(matches["skip_prefixes"]),
            sketch_exempt=_longest(matches["sketch_exempt_prefixes"]),
            mate_requirement=requirement,
            mate_prefix=mate_prefix,
            all_matches={name: [prefix.written for prefix in matches[name]] for name in LIST_NAMES},
        )


def normalize(path: str) -> str:
    """One spelling for one path: forward slashes, no `.`/`..`, no trailing separator, folded.

    Case-folded because the file systems these paths come from are case-insensitive, and
    because the macro compared them that way.
    """
    segments: list[str] = []
    for segment in path.replace("\\", "/").split("/"):
        if segment == ".":
            continue
        if segment == ".." and segments and segments[-1] not in ("", ".."):
            segments.pop()
            continue
        segments.append(segment)
    collapsed = "/".join(segments)
    if len(collapsed) > 1:
        collapsed = collapsed.rstrip("/")
    return collapsed.casefold()


def _prepare(entries: list[str], root: str) -> tuple[LibraryPrefix, ...]:
    """One list, normalized once. A blank entry is dropped: it is not "every path"."""
    return tuple(
        LibraryPrefix(written=entry, normalized=_resolve(entry, root))
        for entry in entries
        if entry.strip()
    )


def _resolve(path: str, root: str) -> str:
    """An absolute path as written; a relative one against the vault root (rule 2)."""
    normalized = normalize(path)
    if not normalized or _ABSOLUTE.match(path):
        return normalized
    return f"{root.rstrip('/')}/{normalized}" if root else normalized


def _matching(prefixes: tuple[LibraryPrefix, ...], subject: str) -> list[LibraryPrefix]:
    """Every entry of one list `subject` is under, in profile order.

    The match is anchored at a **segment** boundary: `subject` is the entry itself, or lies
    under it. A plain `startswith` would put `.../Bonding_old/a.SLDPRT` under an entry naming
    `.../Bonding/`, which on the skip list is a false SKIP - a document reported as skipped
    coverage that a release gate should have graded - and on the mate lists a silent change to
    what a component is required to have. A release gate must not err in that direction.

    One rule for both spellings of an entry, because rule 3 says a prefix is a prefix whether
    or not it ends in a separator: an entry written with a trailing separator and one written
    without must answer the same question the same way, and both sides have lost their trailing
    separator by the time they get here. Rule 3's single-file case is the equality: an entry
    naming one file matches that file, which is what the macro's own two-mate list needed, and
    "any path that starts with it" still holds for anything under it.
    """
    return [
        prefix
        for prefix in prefixes
        if subject == prefix.normalized or subject.startswith(f"{prefix.normalized}/")
    ]


def _longest(matches: list[LibraryPrefix]) -> str | None:
    """The longest match of one list, as written; ties keep profile order (rule 5)."""
    if not matches:
        return None
    return max(matches, key=lambda prefix: len(prefix.normalized)).written


def _mate_requirement(
    one_mate: list[LibraryPrefix], two_mate: list[LibraryPrefix]
) -> tuple[MateRequirement, str | None]:
    """Rule 6, as one comparison: the longer prefix decides, and a tie falls to one mate."""
    best_one = max(one_mate, key=lambda prefix: len(prefix.normalized), default=None)
    best_two = max(two_mate, key=lambda prefix: len(prefix.normalized), default=None)
    if best_one is None and best_two is None:
        return 0, None
    if best_two is None:
        assert best_one is not None
        return 1, best_one.written
    if best_one is None:
        return 2, best_two.written
    if len(best_two.normalized) > len(best_one.normalized):
        return 2, best_two.written
    return 1, best_one.written
