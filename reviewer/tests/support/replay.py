"""Recorded reviews built from a script, for the replay's tests and fixtures (008 T014).

`record_scripted_review` writes a real review run folder - a copy of `package.json`,
`session.json` and `events.jsonl` (and whatever else a review writes) - by playing a script
through the current code with `swreview.benchmark.replay.play_review`, the same driver the
replay uses. What makes it a *recording* is the usage it writes: every round reports the input
the replay's accounting says it cost, so a replay of the folder can be checked against known
numbers. By default:

    input = DEFAULT_PREFIX_TOKENS
          + DEFAULT_OUTPUT_TOKENS x (the model's answers already in the history)
          + count_tokens of every engineer message after the opening, up to this turn
          + Σ (count_tokens(tool_result_text(result)) + FRAMING_TOKENS) over the visible results

`usage_for` replaces that with any rule over the round as played (the fixture generator uses
the recorded usage plus the size difference its fictional results make).

It writes in two passes, because a round's usage is emitted before its calls run: the first
plays the script in a scratch folder to learn every round's results, the second plays it again
into `out` with each round's usage computed from the first. The code is deterministic, so the
two passes see the same results - which the second pass asserts rather than assumes.

A `start_review` keyword that builds a bridge must build a fresh one each time
(`bridge_factory=lambda pipe, secret: ScriptedReviewBridge(...)`): each pass consumes its
script.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from swreview.agent.providers import FRAMING_TOKENS, TokenUsage
from swreview.agent.runner import ANSWER_MESSAGE
from swreview.benchmark.replay import PlayedRound, TurnPlan, play_review
from swreview.tokens import count_tokens

__all__ = [
    "DEFAULT_OUTPUT_TOKENS",
    "DEFAULT_PREFIX_TOKENS",
    "UsageFor",
    "default_usage",
    "folder_hashes",
    "record_scripted_review",
    "rewrite_events",
    "rewrite_session",
    "usage",
]

DEFAULT_PREFIX_TOKENS = 11_006
"""The first round's input on the big recording: the system prompt, the tools, the opening."""

DEFAULT_OUTPUT_TOKENS = 40
"""What each scripted round "outputs", held constant so the arithmetic is easy to check."""

UsageFor = Callable[[PlayedRound], TokenUsage]


def usage(input_tokens: int, output_tokens: int = DEFAULT_OUTPUT_TOKENS) -> TokenUsage:
    """A round's usage with the counts a real OpenAI round reports."""
    return TokenUsage(
        input_tokens=input_tokens,
        cached_input_tokens=0,
        cache_write_tokens=None,
        output_tokens=output_tokens,
        reasoning_tokens=0,
        tool_result_input_tokens=None,
        total_tokens=input_tokens + output_tokens,
        latency_s=0.25,
    )


def engineer_messages(turns: Sequence[TurnPlan], through: int) -> list[str]:
    """Every engineer message after the opening, up to and including turn `through`."""
    messages: list[str] = []
    for plan in turns[1 : through + 1]:
        if plan.kind == "follow_up":
            messages.append(plan.user_text)
        elif plan.kind == "answer":
            [(request_id, answer)] = plan.answers
            messages.append(ANSWER_MESSAGE.format(request_id=request_id, answer=answer))
    return messages


def default_usage(turns: Sequence[TurnPlan]) -> UsageFor:
    """The accounting in this module's docstring, over one script."""

    def usage_for(played: PlayedRound) -> TokenUsage:
        words = sum(count_tokens(text) for text in engineer_messages(turns, played.turn))
        results = sum(count_tokens(call.text) + FRAMING_TOKENS for call in played.visible)
        outputs = DEFAULT_OUTPUT_TOKENS * played.prior_rounds
        return usage(DEFAULT_PREFIX_TOKENS + outputs + words + results)

    return usage_for


def record_scripted_review(
    out: Path | str,
    package_dir: Path | str,
    turns: Sequence[TurnPlan],
    *,
    usage_for: UsageFor | None = None,
    presentation: TokenUsage | None = None,
    **start_review_kwargs: Any,
) -> Path:
    """Write a recorded review of `package_dir` into `out` (which must be new or empty).

    Returns `out`. `presentation`, when given, turns the presentation request on and is its
    usage, carried verbatim.
    """
    out_path = Path(out)
    if out_path.exists() and any(out_path.iterdir()):
        raise FileExistsError(f"{out_path} is not empty; a recording is written into a new folder")
    rule = usage_for if usage_for is not None else default_usage(turns)

    with tempfile.TemporaryDirectory(prefix="swreview-record-") as scratch:
        first = play_review(
            package_dir,
            Path(scratch) / "run",
            turns,
            presentation=presentation,
            **start_review_kwargs,
        )
    usages = {(played.turn, played.index): rule(played) for played in first.rounds}

    second = play_review(
        package_dir,
        out_path,
        turns,
        usages=usages,
        presentation=presentation,
        **start_review_kwargs,
    )
    learned = [[call.text for call in played.visible] for played in first.rounds]
    written = [[call.text for call in played.visible] for played in second.rounds]
    if learned != written:
        raise AssertionError(
            "the two passes of one script saw different results; the review is not "
            "deterministic, so the usage written would not match what the replay counts"
        )
    return out_path


# --- editing a recording, the way older code or an older extractor would have written it ----


def rewrite_events(run_dir: Path, change: Callable[[dict[str, Any]], dict[str, Any]]) -> None:
    """Rewrite every event of `run_dir/events.jsonl` through `change`, keeping line order."""
    path = run_dir / "events.jsonl"
    events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    path.write_text("".join(json.dumps(change(event)) + "\n" for event in events), encoding="utf-8")


def rewrite_session(run_dir: Path, change: Callable[[dict[str, Any]], None]) -> None:
    """Edit `run_dir/session.json` in place through `change`, which mutates the parsed JSON."""
    path = run_dir / "session.json"
    session = json.loads(path.read_text(encoding="utf-8"))
    change(session)
    path.write_text(json.dumps(session, indent=2), encoding="utf-8")


def folder_hashes(folder: Path) -> dict[str, str]:
    """A sha256 per file under `folder`, keyed by relative path: "nothing was written"."""
    return {
        path.relative_to(folder).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(folder.rglob("*"))
        if path.is_file()
    }
