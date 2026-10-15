"""One fictional package for 015's characterizations, waiting fixtures and answer tests.

The convention-only roles package supplies its unclear pin and named hygiene findings. One
same-name drawing beside the custom plate adds the second code question. The scripted seat
uses the real bridge's cached capability reader, so the drawing question depends on a ping
that says it opens closed drawings. A confirmed read returns the host's result shape; as in
the existing drawing-questions fixture, the host's package merge is not played.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from swreview.bridge.client import PROTOCOL_VERSION, BridgeClient, DrawingReadMode
from swreview.ir.loader import load_package, save_package
from tests.support.drawings import DrawingBuilder
from tests.support.review_bridge import VOLUME_UNIT_GAP, ScriptedReviewBridge
from tests.support.roles_review import PLATE_ID, write_package, write_profile


class QuestionsBridge(ScriptedReviewBridge):
    """The shared scripted bridge with the real cached capability reader."""

    def __init__(self) -> None:
        super().__init__(
            results={
                "ping": [
                    {"pong": True, "protocol": PROTOCOL_VERSION, "drawing_read": "opens_closed"}
                ],
                "interference": [{"interferences": [], "gaps": [dict(VOLUME_UNIT_GAP)]}],
                "drawing_read": [
                    {
                        "document_id": PLATE_ID,
                        "drawing_document_id": "doc:0004",
                        "opened": True,
                        "closed": True,
                        "sheets": 1,
                        "gaps": 0,
                    }
                ],
            }
        )
        self._drawing_read_mode: DrawingReadMode | None = None

    def drawing_read_mode(self) -> DrawingReadMode:
        return BridgeClient.drawing_read_mode(self)


@dataclass(frozen=True)
class QuestionsPackage:
    """The written run folder, its version 3 profile and its fresh scripted seat."""

    folder: Path
    profile: Path
    bridge: QuestionsBridge


def build_questions_package(folder: Path) -> QuestionsPackage:
    """Write deterministic fictional evidence, with its two code-owned questions."""
    write_package(folder)
    builder = DrawingBuilder(load_package(folder).package)
    builder.candidate(PLATE_ID)
    save_package(builder.build(), folder)
    return QuestionsPackage(folder, write_profile(folder), QuestionsBridge())
