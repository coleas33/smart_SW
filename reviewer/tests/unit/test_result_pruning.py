"""Old tool results become stubs in the model's view (feature 008 T068, FR-020, FR-022).

95.7% of every request on the big assembly was earlier tool output resent in full. With
history pruning on, a tool result the model has already read for `prune_after_rounds`
rounds is replaced, in the request only, by a stub naming the tool, its arguments, its
counts and the ids it returned, and saying how to fetch it again. `prune_history` is a pure
function over the neutral history: both adapters and the replay call it on every request,
the history itself is never changed, and the same result always gives the same stub, so the
cached prefix up to the previous result survives (research R2.29, R2.30).
"""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from swreview.agent.providers.pruning import (
    PRUNED_NOTE,
    STUB_ID_CAP,
    prune_history,
    result_stub,
)

REVIEWER = Path(__file__).resolve().parents[2]


def user(text: str) -> dict[str, Any]:
    return {"role": "user", "content": text}


def assistant(*calls: tuple[str, dict[str, Any]], text: str = "") -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": text}
    if calls:
        message["tool_calls"] = [
            {"call_id": f"call_{name}", "name": name, "arguments": arguments}
            for name, arguments in calls
        ]
    return message


def tool(
    name: str, content: dict[str, Any], *, is_error: bool = False, call_id: str = ""
) -> dict[str, Any]:
    return {
        "role": "tool",
        "call_id": call_id or f"call_{name}",
        "name": name,
        "content": content,
        "is_error": is_error,
    }


def big(prefix: str = "cmp", count: int = 30) -> dict[str, Any]:
    """A result far larger than its stub: thirty objects with ids and prose."""
    return {
        "result": [
            {"id": f"{prefix}:{n:04d}", "name": f"component number {n}", "note": "x" * 60}
            for n in range(1, count + 1)
        ]
    }


def contents(messages: list[dict[str, Any]]) -> list[Any]:
    return [message.get("content") for message in messages]


def is_stub(message: dict[str, Any]) -> bool:
    content = message.get("content")
    return isinstance(content, dict) and content.get("pruned") == PRUNED_NOTE


# --- age -----------------------------------------------------------------------------------


def history_with(followers: int) -> list[dict[str, Any]]:
    """One big result followed by `followers` assistant messages."""
    messages = [
        user("review it"),
        assistant(("list_components", {})),
        tool("list_components", big()),
    ]
    for index in range(followers):
        messages.append(assistant(("get_package_summary", {}), text=f"round {index}"))
        messages.append(tool("get_package_summary", {"ok": True}))
    return messages


@pytest.mark.parametrize(
    ("followers", "pruned_at_1", "pruned_at_2"),
    [(0, False, False), (1, True, False), (2, True, True)],
)
def test_age_is_the_number_of_assistant_messages_after_the_result(
    followers: int, pruned_at_1: bool, pruned_at_2: bool
) -> None:
    messages = history_with(followers)

    assert is_stub(prune_history(messages, 1)[2]) is pruned_at_1
    assert is_stub(prune_history(messages, 2)[2]) is pruned_at_2


@pytest.mark.parametrize("age", [1, 2])
def test_a_result_is_seen_in_full_in_exactly_n_requests(age: int) -> None:
    """Request k carries the history up to k assistant messages; the result arrives after
    the first one and must be shown in full in `age` requests, then as a stub."""
    full: list[bool] = []
    for followers in range(0, 5):
        request = prune_history(history_with(followers), age)
        full.append(not is_stub(request[2]))

    assert full == [True] * age + [False] * (5 - age)


# --- what is never touched -----------------------------------------------------------------


def test_user_and_assistant_messages_are_never_replaced() -> None:
    opening = "Deterministic checks ran before this turn ... " + "digest " * 400
    messages = [
        user(opening),
        assistant(("list_components", {}), text="long reasoning " * 200),
        tool("list_components", big()),
        user("Evidence request ER-001 is answered: yes\n\nRe-run the check."),
        assistant(("get_package_summary", {})),
        tool("get_package_summary", {"ok": True}),
        user("The engineer answered your evidence requests:\n- ER-001: yes\n- ER-002: no"),
        assistant(text="done"),
    ]

    pruned = prune_history(messages, 1)

    for before, after in zip(messages, pruned, strict=True):
        if before["role"] != "tool":
            assert after == before


def test_an_error_result_is_never_replaced() -> None:
    messages = [
        user("go"),
        assistant(("list_components", {})),
        tool("list_components", {"error": "x" * 5000}, is_error=True),
        assistant(text="a"),
        assistant(text="b"),
    ]

    assert prune_history(messages, 1)[2] == messages[2]


def test_a_result_whose_stub_would_be_longer_is_kept() -> None:
    messages = [
        user("go"),
        assistant(("mark_coverage", {"check": "fit", "bucket": "skipped", "reason": "none"})),
        tool("mark_coverage", {"status": "recorded"}),
        assistant(text="a"),
        assistant(text="b"),
    ]

    assert prune_history(messages, 1)[2] == messages[2]


def test_an_unmatched_tool_message_is_kept() -> None:
    """OpenAI's `_append_unrun` answers calls it could not run after an assistant message
    that recorded no calls: there are no arguments to put in a stub, so it stays."""
    messages = [
        user("go"),
        assistant(text="cut off"),
        tool("list_components", big()),
        assistant(text="a"),
        assistant(text="b"),
    ]

    assert prune_history(messages, 1)[2] == messages[2]


def test_a_name_that_does_not_match_its_position_is_kept() -> None:
    messages = [
        user("go"),
        assistant(("list_holes", {})),
        tool("list_components", big()),
        assistant(text="a"),
    ]

    assert prune_history(messages, 1)[2] == messages[2]


# --- arguments by position -----------------------------------------------------------------


def test_parallel_calls_in_one_round_map_their_arguments_by_position() -> None:
    messages = [
        user("go"),
        assistant(
            ("get_component", {"component_id": "cmp:0001"}),
            ("get_component", {"component_id": "cmp:0002"}),
        ),
        tool("get_component", big("hol"), call_id=""),
        tool("get_component", big("fac"), call_id=""),
        assistant(text="done"),
    ]

    first, second = prune_history(messages, 1)[2:4]

    assert first["content"]["arguments"] == {"component_id": "cmp:0001"}
    assert second["content"]["arguments"] == {"component_id": "cmp:0002"}
    assert first["content"]["ids"][0] == "hol:0001"
    assert second["content"]["ids"][0] == "fac:0001"


# --- purity --------------------------------------------------------------------------------


def test_the_input_is_never_mutated() -> None:
    messages = history_with(3)
    before = copy.deepcopy(messages)

    pruned = prune_history(messages, 1)

    assert messages == before
    assert pruned is not messages


def test_pruning_is_idempotent() -> None:
    messages = history_with(3)

    once = prune_history(messages, 1)

    assert prune_history(once, 1) == once


# --- the stub ------------------------------------------------------------------------------


def test_the_stub_names_the_tool_its_arguments_counts_and_ids() -> None:
    stub = result_stub("list_mates", {"component_id": None}, {"result": big("mat", 55)["result"]})

    assert stub == {
        "pruned": PRUNED_NOTE,
        "tool": "list_mates",
        "arguments": {"component_id": None},
        "counts": {"result": 55},
        "ids": [f"mat:{n:04d}" for n in range(1, STUB_ID_CAP + 1)],
        "ids_omitted": 35,
        "refetch": "call list_mates again with these arguments to read it in full",
    }


def test_the_ids_are_capped_at_twenty() -> None:
    assert STUB_ID_CAP == 20
    few = result_stub("list_holes", {}, {"result": big("hol", 20)["result"]})
    many = result_stub("list_holes", {}, {"result": big("hol", 21)["result"]})

    assert (len(few["ids"]), few["ids_omitted"]) == (20, 0)
    assert (len(many["ids"]), many["ids_omitted"]) == (20, 1)


def test_refetch_names_get_finding_only_when_the_content_carries_finding_ids() -> None:
    digest = {
        "status": "recorded",
        "findings": 2,
        "rows": [{"id": "F-001"}, {"id": "F-002"}],
        "finding_ids": ["F-001", "F-002"],
    }
    plain = big()

    with_findings = result_stub("check_rms_part", {}, digest)
    without = result_stub("list_components", {}, plain)

    assert with_findings["refetch"] == (
        "call check_rms_part again with these arguments to read it in full or "
        "get_finding(<id>) for one finding"
    )
    assert with_findings["ids"] == ["F-001", "F-002"], "no id twice"
    assert "get_finding" not in without["refetch"]


def test_without_get_finding_offered_the_stub_does_not_name_it() -> None:
    """Pruning without payload slimming: `get_finding` is not offered, so no stub offers it."""
    digest = {"finding_ids": ["F-001"], "rows": [{"id": "F-001"}]}

    stub = result_stub("check_rms_part", {}, digest, finding_detail=False)

    assert "get_finding" not in stub["refetch"]


# --- a stub of a tool that is not offered (feature 008 amendment, T113) ------------------------

ALREADY_RUN_ANSWER: dict[str, Any] = {
    "status": "already_run",
    "ran_at_step": 3,
    "note": "Checks first ran this call before your first turn; its findings are in the "
    "session. It was not run again.",
    "outcome": {"status": "recorded", "findings": 2, "finding_ids": ["F-001", "F-002"]},
}
"""What the re-call guard answers a withheld tool with: a result like any other, so it ages
into a stub like any other."""


def test_a_stub_of_a_tool_not_offered_says_so_instead_of_asking_for_a_call() -> None:
    """Lever 13: a model that called a withheld tool anyway must not be told, two rounds
    later, to call it again (`contracts/checks-first.md` section 7)."""
    offered = {"list_components", "get_finding"}
    plain = result_stub("check_hygiene", {}, big(), offered=offered)
    findings = result_stub("check_rms_part", {}, {"finding_ids": ["F-001"]}, offered=offered)
    no_detail = result_stub(
        "check_rms_part", {}, {"finding_ids": ["F-001"]}, finding_detail=False, offered=offered
    )

    assert plain["refetch"] == (
        "check_hygiene is not offered this session, so it cannot be called again"
    )
    assert findings["refetch"] == (
        "check_rms_part is not offered this session, so it cannot be called again; "
        "get_finding(<id>) reads one finding"
    )
    assert no_detail["refetch"] == (
        "check_rms_part is not offered this session, so it cannot be called again"
    )
    for stub in (plain, findings, no_detail):
        assert "call " not in stub["refetch"].split(" is not offered")[1]
    offered_one = result_stub("check_hygiene", {}, big(), offered={"check_hygiene"})
    assert offered_one == result_stub("check_hygiene", {}, big()), "offered: today's stub"


def test_prune_history_takes_the_offered_names_from_its_caller() -> None:
    messages = [
        user("review it"),
        assistant(("check_rms_part", {}), ("list_components", {})),
        tool("check_rms_part", ALREADY_RUN_ANSWER),
        tool("list_components", big()),
        assistant(text="thinking"),
        assistant(text="still thinking"),
    ]

    offered = {"list_components", "get_finding"}
    pruned = prune_history(messages, 1, offered=offered)

    assert "is not offered this session" in pruned[2]["content"]["refetch"]
    assert pruned[3]["content"]["refetch"].startswith("call list_components again")


def test_without_offered_names_every_stub_is_todays() -> None:
    messages = [
        user("review it"),
        assistant(("check_rms_part", {})),
        tool("check_rms_part", ALREADY_RUN_ANSWER),
        assistant(text="thinking"),
    ]

    assert prune_history(messages, 1) == prune_history(messages, 1, offered=None)
    assert prune_history(messages, 1)[2]["content"]["refetch"].startswith(
        "call check_rms_part again"
    )
    everything = {"check_rms_part"}
    assert prune_history(messages, 1, offered=everything) == prune_history(messages, 1)


def test_the_stub_is_byte_identical_across_calls_and_hash_seeds() -> None:
    script = (
        "import json; from swreview.agent.providers.pruning import prune_history;"
        "from tests.unit.test_result_pruning import history_with;"
        "print(json.dumps(prune_history(history_with(3), 1)))"
    )
    outputs = {
        subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            check=True,
            cwd=REVIEWER,
            env={**os.environ, "PYTHONHASHSEED": seed},
        ).stdout
        for seed in ("0", "4242")
    }

    assert len(outputs) == 1
    assert json.dumps(prune_history(history_with(3), 1)) == json.dumps(
        prune_history(history_with(3), 1)
    )
