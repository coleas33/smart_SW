"""The owner's recordings mapping is read strictly, and never names a folder in a message.

`tests/support/recordings.recording_folder` is how the replay's real-recording test finds the
three recorded reviews now that their folder names, which carry design numbers, are out of the
tree (decision 11B). The mapping is the owner's local file; these tests write their own in a
temporary folder, so they run everywhere.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.support.recordings import RECORDING_NAMES, RECORDINGS_PATH, recording_folder
from tests.support.scramble import denylist_path

REPLAY_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "replay"
FOLDER_NAME = "20990101-000000-FICT-0001"
"""A fictional run folder; the tests check it never appears in a skip or failure message."""


def mapping(tmp_path: Path, content: object, *, text: str | None = None) -> Path:
    path = tmp_path / "recordings.json"
    path.write_text(json.dumps(content) if text is None else text, encoding="utf-8")
    return path


def recorded(tmp_path: Path) -> Path:
    folder = tmp_path / "dumps" / FOLDER_NAME
    folder.mkdir(parents=True)
    return folder


def test_the_mapping_sits_beside_the_owners_denylist() -> None:
    assert RECORDINGS_PATH.parent == denylist_path().parent
    assert RECORDINGS_PATH.name == "recordings.json"


def test_every_recording_name_is_a_committed_replay_fixture() -> None:
    fixtures = {path.parent.name for path in REPLAY_FIXTURES.glob("*/package.json")}

    assert set(RECORDING_NAMES) == fixtures


def test_a_mapped_folder_is_returned(tmp_path: Path) -> None:
    folder = recorded(tmp_path)
    path = mapping(tmp_path, {name: str(folder) for name in RECORDING_NAMES})

    assert recording_folder("small-assembly-b", path) == folder


def test_a_byte_order_mark_is_not_part_of_the_json(tmp_path: Path) -> None:
    folder = recorded(tmp_path)
    path = mapping(tmp_path, None, text="\ufeff" + json.dumps({"big-assembly": str(folder)}))

    assert recording_folder("big-assembly", path) == folder


def test_an_absent_mapping_skips_naming_the_file(tmp_path: Path) -> None:
    path = tmp_path / "recordings.json"

    with pytest.raises(pytest.skip.Exception, match="recordings mapping is not on this machine"):
        recording_folder("big-assembly", path)


def test_an_absent_folder_skips_naming_the_recording_not_the_folder(tmp_path: Path) -> None:
    folder = tmp_path / "dumps" / FOLDER_NAME
    path = mapping(tmp_path, {"big-assembly": str(folder)})

    with pytest.raises(pytest.skip.Exception) as skipped:
        recording_folder("big-assembly", path)

    assert "big-assembly recording" in str(skipped.value)
    assert FOLDER_NAME not in str(skipped.value)


@pytest.mark.parametrize(
    ("content", "text", "says"),
    [
        (None, "{not json", "is not JSON"),
        (None, "", "is not JSON"),
        (["big-assembly"], None, "holds no JSON object"),
        ({"small-assembly-a": "x"}, None, "gives no folder for 'big-assembly'"),
        ({"big-assembly": None}, None, "gives no folder for 'big-assembly'"),
        ({"big-assembly": 7}, None, "gives no folder for 'big-assembly'"),
        ({"big-assembly": "  "}, None, "gives no folder for 'big-assembly'"),
        ({"big-assembly": FOLDER_NAME}, None, "a relative folder"),
    ],
    ids=["broken", "empty", "a list", "key missing", "null", "a number", "blank", "relative"],
)
def test_a_mapping_that_cannot_say_where_the_recording_is_fails(
    tmp_path: Path, content: object, text: str | None, says: str
) -> None:
    path = mapping(tmp_path, content, text=text)

    with pytest.raises(pytest.fail.Exception, match=says) as failed:
        recording_folder("big-assembly", path)

    assert FOLDER_NAME not in str(failed.value)
