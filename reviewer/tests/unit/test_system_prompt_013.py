"""The system prompt's feature 013 sentences, pinned (T067, T087).

`contracts/re-ask-guard.md` sections 2 and 3: step 1 says code has closed provenance, so the
manifest's vault-version and local-modification gaps are not the model's to chase; step 6 says an
answered request is final. They reach the model on every request of every review, so a change to
either moves what the model reads and passes the replay gate.
"""

from __future__ import annotations

from swreview.agent.checklist import load_checklist
from swreview.agent.runner import SYSTEM_PROMPT_FILE, build_system_prompt
from tests.support.packages import build_package

STEP_1_SENTENCE = (
    "The manifest's vault-version and local-modification gaps are answered by the provenance "
    "item, which code has closed."
)
STEP_6_SENTENCE = (
    "An answered request is final: never ask it again in other words; record the check with "
    "the answer as given."
)


def steps() -> dict[str, str]:
    """`{step number: its text on one line}` for the numbered steps of "How to work"."""
    text = SYSTEM_PROMPT_FILE.read_text(encoding="utf-8")
    body = text.split("## How to work", 1)[1].split("\n## ", 1)[0]
    found: dict[str, list[str]] = {}
    current = ""
    for line in body.splitlines():
        stripped = line.strip()
        head = stripped.split(". ", 1)[0]
        if head.isdigit():
            current = head
            found[current] = [stripped.split(". ", 1)[1]]
        elif current and stripped:
            found[current].append(stripped)
    return {number: " ".join(parts) for number, parts in found.items()}


def test_step_1_says_code_has_closed_provenance() -> None:
    assert steps()["1"].endswith(STEP_1_SENTENCE)


def test_step_6_says_an_answered_request_is_final() -> None:
    assert STEP_6_SENTENCE in steps()["6"]


def test_each_sentence_is_in_the_prompt_once() -> None:
    prompt = " ".join(
        build_system_prompt(load_checklist(), build_package()).split()
    )

    assert prompt.count(STEP_1_SENTENCE) == 1
    assert prompt.count(STEP_6_SENTENCE) == 1
