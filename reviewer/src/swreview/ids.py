"""Sequential, zero-padded identifiers (`F-001`, `ER-001`) used inside one session."""

from __future__ import annotations

from collections.abc import Iterator


class SequentialIdAllocator(Iterator[str]):
    """Yields `<prefix>-001`, `<prefix>-002`, ... and keeps counting past the padding."""

    def __init__(self, prefix: str, start: int = 1, width: int = 3) -> None:
        self.prefix = prefix
        self.width = width
        self._next = start

    def __next__(self) -> str:
        identifier = f"{self.prefix}-{self._next:0{self.width}d}"
        self._next += 1
        return identifier
