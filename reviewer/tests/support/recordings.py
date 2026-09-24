"""Where the replay's real recordings are on the owner's machine (feature 008, `contracts/replay.md`
section 8).

The three recorded reviews the replay fixtures were generated from - the big assembly's and the
small assembly's two - never enter the repository, and neither do their folder names, which
carry the designs' numbers (the owner's decision 11B of 2026-09-24). The owner keeps a mapping
beside the fixture denylist, outside the repository, at `%LOCALAPPDATA%\\SwReview\\recordings.json`:
one JSON object whose keys are the replay fixtures' names (`RECORDING_NAMES`) and whose values
are the recorded run folders' absolute paths:

    {"big-assembly": "<folder>", "small-assembly-a": "<folder>", "small-assembly-b": "<folder>"}

`recording_folder` reads it for a test. Where the mapping or a mapped folder is not on this
machine, which is CI, the test skips saying why, as it did when it looked for the dumps folder
itself. A mapping that is there but cannot say where a recording is fails the test instead: the
owner meant the recordings to be read, and a typo must not pass as a skip. No message names a
mapped folder, because its name carries a design number and a test's output can end up in a
public log.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.support.scramble import denylist_path

__all__ = ["RECORDINGS_PATH", "RECORDING_NAMES", "recording_folder"]

RECORDINGS_PATH = denylist_path().with_name("recordings.json")
"""The owner's mapping, beside `fixture-denylist.txt`; absent on every machine but the owner's."""

RECORDING_NAMES = ("big-assembly", "small-assembly-a", "small-assembly-b")
"""The mapping's keys: the replay fixture each recording generates."""


def recording_folder(name: str, path: Path = RECORDINGS_PATH) -> Path:
    """The folder of the recording `name` generates, read from the owner's mapping at `path`.

    Skips when the mapping or the folder is absent; fails when the mapping is not a JSON object,
    has no folder for `name`, or gives a relative one. A byte-order mark an editor saved is not
    part of the JSON.
    """
    if not path.is_file():
        pytest.skip(f"the recordings mapping is not on this machine: {path}")
    try:
        mapping = json.loads(path.read_text(encoding="utf-8-sig"))
    except ValueError as error:
        pytest.fail(f"{path} is not JSON ({error})")
    if not isinstance(mapping, dict):
        pytest.fail(f"{path} holds no JSON object from fixture names to recording folders")
    folder = mapping.get(name)
    if not isinstance(folder, str) or not folder.strip():
        pytest.fail(f"{path} gives no folder for {name!r}; its keys are {list(RECORDING_NAMES)}")
    recorded = Path(folder)
    if not recorded.is_absolute():
        pytest.fail(f"{path} gives {name!r} a relative folder; the mapping holds absolute paths")
    if not recorded.is_dir():
        pytest.skip(f"the {name} recording that {path} names is not on this machine")
    return recorded
