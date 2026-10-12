"""The case vocabulary (feature 014 `generator.md` 8; GN-6; FR-048, SC-011, D13).

Every name a generated case carries - file, component, configuration and feature names,
property names and values, package, case, design and set names, every path - is built from
`CASE_VOCABULARY` or is a size, a number or an id; sentences (key descriptions, answers, drawing
notes, the correct calls' texts) are the author's English and are not held to it. The tokens
are generated, never recorded, so a refusal naming one leaks nothing.

`CASE_VOCABULARY` is feature 011's drawing vocabulary, plus every token of the example profile's
string values, read from the loaded profile so the list cannot drift from it (research §8.14),
plus four short committed lists: generic part nouns, callout words, case-id words and the
Resilient Modeling group words (owner decision 54A). A word and the number run into it are read
apart, as the drawing fixtures read them, so a thread or fit class token (`6H`, `H7`, `g6`) and a
counted callout (`4X`) pass as sizes (`name_offences`).

The example profile is loaded here once: its names are what every design writes
(`generator.md` 5.2), and its tokens what the names check reads.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any

from swreview.benchmark.sets import REPO_ROOT
from swreview.checks.standards.profile import StandardsProfile, load_profile
from tests.support.drawings import DRAWING_VOCABULARY, drawing_fictional_offences

EXAMPLE_PROFILE_PATH = REPO_ROOT / "config" / "standards.example.yaml"
"""`config/standards.example.yaml`, the one profile every case is built and keyed against."""

EXAMPLE_PROFILE: StandardsProfile = load_profile(EXAMPLE_PROFILE_PATH)
"""The example profile, loaded once (`checks/standards/profile.py` `load_profile`)."""

PART_NOUNS: frozenset[str] = frozenset(
    {
        "plate",
        "pin",
        "dowel",
        "cover",
        "housing",
        "bracket",
        "base",
        "shaft",
        "bushing",
        "spacer",
        "flange",
        "clevis",
        "carriage",
        "rail",
        "shim",
        "clamp",
        "block",
        "mount",
        "gear",
        "bearing",
        "assy",
        "blind",
        "tap",
    }
)
"""Generic part nouns a design's names and summaries are built from."""

CALLOUT_WORDS: frozenset[str] = frozenset({"drill", "thread", "deep", "thru", "fixture", "value"})
"""The words a drawn callout and the house card's values are made of."""

CASE_ID_WORDS: frozenset[str] = frozenset(
    {
        "twin",
        "fit",
        "clean",
        "contact",
        "positive",
        "lightweight",
        "empty",
        "sitting",
        "groups",
        "committed",
        "pilot",
        "pane",
        "smoke",
    }
)
"""The words a case id or a set name is made of beside its design's (`cases.md` 2)."""

RMS_GROUP_WORDS: frozenset[str] = frozenset(
    {"ref", "construction", "core", "detail", "modify", "quarantine"}
)
"""The words of the six Resilient Modeling group folders' names, `1-Ref` to `6-Quarantine`, which
every compliant tree and R-7 lay and RMS matches exactly (`generator.md` 5.3 and 8; owner decision
54A). The generator may not import `checks/rms_types.yaml`'s loader (section 9), so
`test_benchmark_case_generator.py` holds this list to the table's `groups`."""

_WORD = re.compile(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])")
"""One word of a profile value: a lower-case run, a capitalised one, or an upper-case run, so
`ExampleVault` reads as `Example` and `Vault`, and `first_angle` as `first` and `angle`."""


def _strings(value: Any) -> Iterator[str]:
    """Every string among `value`'s values, at any depth (never a mapping's keys, which are
    the profile schema's field names)."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def profile_tokens(profile: StandardsProfile) -> frozenset[str]:
    """Every word of `profile`'s string values, lower-cased (research §8.14)."""
    return frozenset(
        word.lower()
        for text in _strings(profile.model_dump(mode="json"))
        for word in _WORD.findall(text)
    )


CASE_VOCABULARY: frozenset[str] = (
    DRAWING_VOCABULARY
    | profile_tokens(EXAMPLE_PROFILE)
    | PART_NOUNS
    | CALLOUT_WORDS
    | CASE_ID_WORDS
    | RMS_GROUP_WORDS
)
"""Every word a generated name may contain (`generator.md` 8)."""


def name_offences(text: str) -> list[str]:
    """The tokens of the name `text` that are neither `CASE_VOCABULARY` words (or several run
    together) nor a size, a number or an id, a word and the number run into it read apart."""
    return drawing_fictional_offences(text, CASE_VOCABULARY)
