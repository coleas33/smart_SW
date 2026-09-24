"""A pytest plugin that turns feature 011's drawing binding switch on for a whole run.

Loaded only by `tests/unit/test_binding_switch_flip.py`, in a child pytest, with
`-p tests.support.flip_binding`: the run then sees the shipped value T066 will write, so the one
test that fails is the pin that reads it. Never loaded by the suite itself.
"""

from __future__ import annotations

import pytest


def pytest_configure(config: pytest.Config) -> None:
    from swreview.drawings import binding

    binding.DRAWING_BINDING_VALIDATED = True
