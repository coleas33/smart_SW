"""One drawing file however its path is spelled: the shared file key (013 T010, research R2.28).

`drawings/evidence.file_key(path)` is the one rule that says two candidate paths name one file:
case and the separator ignored, as the extractor's discovery compares two paths. It moved from
`report/summary.py`, where it was private, so its four callers - the drawing check, the brief, the
confirmed read and the summary - group candidates by one rule (013 `contracts/drawing-capability.md`
section 3).
"""

from __future__ import annotations

import pytest

from swreview.drawings import evidence
from swreview.drawings.evidence import file_key
from swreview.report import summary

PATH = "C:\\Fictional\\Vault\\FICT-KALO-7001.SLDDRW"


@pytest.mark.parametrize(
    "spelled",
    [
        pytest.param(PATH, id="as-written"),
        pytest.param(PATH.lower(), id="lower-case"),
        pytest.param(PATH.upper(), id="upper-case"),
        pytest.param(PATH.replace("\\", "/"), id="forward-slashes"),
        pytest.param("C:\\Fictional/Vault\\fict-kalo-7001.slddrw", id="mixed-separators-and-case"),
    ],
)
def test_one_file_however_its_path_is_spelled(spelled: str) -> None:
    assert file_key(spelled) == file_key(PATH)


@pytest.mark.parametrize(
    "other",
    [
        pytest.param("C:\\Fictional\\Vault\\FICT-KALO-7002.SLDDRW", id="another-stem"),
        pytest.param("C:\\Fictional\\Other\\FICT-KALO-7001.SLDDRW", id="another-folder"),
        pytest.param("C:\\Fictional\\Vault\\FICT-KALO-7001.SLDPRT", id="another-extension"),
        pytest.param("D:\\Fictional\\Vault\\FICT-KALO-7001.SLDDRW", id="another-drive"),
    ],
)
def test_another_file_has_another_key(other: str) -> None:
    assert file_key(other) != file_key(PATH)


def test_the_key_is_the_backslash_spelling_folded_for_case() -> None:
    """Today's rule, word for word (`report/summary.py:706-709` before the move)."""
    assert file_key("C:/Fictional/Vault/FICT-Kalo-7001.SLDDRW") == (
        "c:\\fictional\\vault\\fict-kalo-7001.slddrw"
    )
    assert file_key("") == ""


def test_the_summary_uses_the_shared_key_and_keeps_no_copy_of_its_own() -> None:
    """One rule, not two that could drift: the summary's drawings line imports it."""
    assert not hasattr(summary, "_file_key")
    assert summary.file_key is evidence.file_key
