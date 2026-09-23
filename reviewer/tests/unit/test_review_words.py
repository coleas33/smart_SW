"""`report/review_words_v1.yaml` (feature 009 T007): every word the backend supplies, once.

The Review tab prints and never words anything itself (FR-008, FR-024), so every label,
sentence and goal it shows comes from this one file, and a later wording change is a data
change (research R2.5). What this pins:

- **the file is strict.** `load_words()` parses it once and refuses a key the models do not
  name, anywhere, so a typo is a red test and not a silently missing word;
- **it can reach every tab.** No percent sign (the Standards body scan forbids one), and
  every template's placeholders are exactly the ones `report/summary.py` fills
  (data-model section 1);
- **the owner's words are pinned.** "Decide", "Fix", "Verify" (2026-09-23);
- **nothing is left without a word.** Every finding status, severity, coverage bucket,
  contact kind and backend error class has a label; every checklist item but the close-out
  and every classified check id has exactly one goal.
"""

from __future__ import annotations

import string
from pathlib import Path
from typing import Any, get_args

import pytest
import yaml
from pydantic import ValidationError

import swreview.chat.remodel  # noqa: F401 - registers the remodel routes' ChatError classes
from swreview.agent.checklist import CHECKLIST_FILE
from swreview.chat.server import ChatError
from swreview.findings import FindingStatus, Severity
from swreview.report.attention import CHECKLIST_ITEM_IDS, CLOSEOUT_ITEM_ID, load_policy
from swreview.report.session import CoverageBucket
from swreview.report.summary import WORDS_FILE, Words, load_words

CONTACT_KINDS = ("zero_volume", "possible_only", "thread_model")
"""Feature 010's contact kinds (its data model section 9), labelled here ahead of it."""

PLACEHOLDERS: dict[str, set[str]] = {
    "headline.none": set(),
    "headline.findings_one": set(),
    "headline.findings_many": {"n"},
    "headline.issues_one": set(),
    "headline.issues_many": {"n"},
    **{
        f"groups.{kind}.{form}": {"n"}
        for kind in ("decide", "fix", "verify", "decided", "within_scope")
        for form in ("one", "many")
    },
    **{
        f"groups.{kind}.label": set()
        for kind in ("decide", "fix", "verify", "decided", "within_scope")
    },
    "questions.one": set(),
    "questions.many": {"n"},
    "not_loaded.text": {"count", "total"},
    "contacts.one": set(),
    "contacts.many": {"n"},
    "resume.with_tokens": {"tokens"},
    "resume.without": set(),
}
"""Every template `report/summary.py` formats, and the fields it formats it with. Every
other string in the file is printed as it stands and so carries no placeholder at all."""


def raw_words() -> dict[str, Any]:
    return yaml.safe_load(WORDS_FILE.read_text(encoding="utf-8"))


def strings_of(node: Any, path: str = "") -> list[tuple[str, str]]:
    """Every string in the file with its dotted path, lists indexed."""
    if isinstance(node, str):
        return [(path, node)]
    if isinstance(node, dict):
        children = list(node.items())
    elif isinstance(node, list):
        children = list(enumerate(node))
    else:
        return []
    return [pair for key, value in children for pair in strings_of(value, _join(path, key))]


def _join(path: str, key: object) -> str:
    return f"{path}.{key}" if path else str(key)


def fields_of(template: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(template) if name is not None}


def chat_error_classes() -> set[str]:
    """The class-level `error_class` of every `ChatError` subclass, the base's included."""
    found = {ChatError.error_class}
    pending = list(ChatError.__subclasses__())
    while pending:
        cls = pending.pop()
        found.add(cls.error_class)
        pending.extend(cls.__subclasses__())
    return found


# --- the file and its loader -------------------------------------------------------------


def test_the_words_are_loaded_once() -> None:
    assert load_words() is load_words()
    assert load_words().version == "review_words_v1"
    assert load_words().labels.version == load_words().version


@pytest.mark.parametrize(
    "path",
    [(), ("headline",), ("groups", "decide"), ("resume",), ("labels",), ("goals", 0)],
)
def test_an_extra_key_anywhere_is_refused(path: tuple[object, ...]) -> None:
    data = raw_words()
    node: Any = data
    for key in path:
        node = node[key]
    node["unexpected"] = "a word nobody reads"

    with pytest.raises(ValidationError):
        Words.model_validate(data)


def test_no_percent_sign_anywhere_in_the_file() -> None:
    assert "%" not in WORDS_FILE.read_text(encoding="utf-8")


def test_every_template_carries_exactly_its_placeholders() -> None:
    wrong = {
        path: sorted(fields_of(text))
        for path, text in strings_of(raw_words())
        if fields_of(text) != PLACEHOLDERS.get(path, set())
    }
    assert wrong == {}


def test_every_template_the_summary_formats_is_in_the_file() -> None:
    paths = {path for path, _ in strings_of(raw_words())}
    assert set(PLACEHOLDERS) <= paths


# --- the owner's words --------------------------------------------------------------------


def test_the_three_owner_labels_are_decide_fix_verify() -> None:
    groups = load_words().groups
    assert (groups["decide"].label, groups["fix"].label, groups["verify"].label) == (
        "Decide",
        "Fix",
        "Verify",
    )


# --- the labels ------------------------------------------------------------------------------


def test_every_status_severity_and_bucket_has_a_label() -> None:
    labels = load_words().labels
    assert set(labels.status) == set(get_args(FindingStatus))
    assert set(labels.severity) == set(get_args(Severity))
    assert set(labels.bucket) == set(get_args(CoverageBucket))
    assert labels.status["checked_within_scope"] == "checked within scope"
    assert labels.bucket["out_of_scope"] == "out of scope"


def test_every_contact_kind_and_evidence_status_has_a_label() -> None:
    labels = load_words().labels
    assert set(labels.contact_kind) == set(CONTACT_KINDS)
    assert set(labels.evidence_status) == {"open", "answered"}


def test_every_backend_error_class_has_a_next_step_sentence() -> None:
    errors = load_words().labels.errors
    missing = sorted(chat_error_classes() - set(errors))
    assert missing == [], f"no labels.errors sentence for {missing}"
    assert all(sentence.strip() for sentence in errors.values())


def test_every_label_is_a_plain_word_not_a_token() -> None:
    """A label is what the engineer reads in place of a token, so none is one."""
    labels = load_words().labels
    for group in (labels.status, labels.severity, labels.bucket, labels.contact_kind):
        assert all("_" not in word for word in group.values())


# --- the goals ------------------------------------------------------------------------------


def test_the_goals_are_the_nine_of_the_contract_in_their_order() -> None:
    goals = load_words().goals
    assert [goal.id for goal in goals] == [
        "interference",
        "fasteners",
        "hole_alignment",
        "fits_and_stacks",
        "tool_access",
        "mass_and_material",
        "hygiene",
        "drawings",
        "modelling_practice",
    ]
    practice = goals[-1]
    assert (practice.title, practice.items, practice.prefixes) == (
        "Modelling practice",
        ["modeling.resilience"],
        ["rms."],
    )


def test_goal_ids_items_and_prefixes_are_unique() -> None:
    goals = load_words().goals
    ids = [goal.id for goal in goals]
    items = [item for goal in goals for item in goal.items]
    prefixes = [prefix for goal in goals for prefix in goal.prefixes]
    assert len(ids) == len(set(ids))
    assert len(items) == len(set(items))
    assert len(prefixes) == len(set(prefixes)), "a shared prefix would tie the longest match"


def checklist_ids_in_file() -> list[str]:
    checklist = yaml.safe_load(Path(CHECKLIST_FILE).read_text(encoding="utf-8"))
    return [item["id"] for item in checklist["items"]]


@pytest.mark.parametrize("source", ["file", "constant"])
def test_every_checklist_item_but_the_closeout_is_in_exactly_one_goal(source: str) -> None:
    ids = checklist_ids_in_file() if source == "file" else list(CHECKLIST_ITEM_IDS)
    goals = load_words().goals
    owners = {item: [goal.id for goal in goals if item in goal.items] for item in ids}
    wrong = {
        item: found
        for item, found in owners.items()
        if item != CLOSEOUT_ITEM_ID and len(found) != 1
    }
    assert wrong == {}
    assert all(CLOSEOUT_ITEM_ID not in goal.items for goal in goals)


def test_every_classified_check_maps_to_exactly_one_goal_by_longest_prefix() -> None:
    goals = load_words().goals
    unmapped: list[str] = []
    tied: list[str] = []
    for check in load_policy().classes:
        matches = [
            (len(prefix), goal.id)
            for goal in goals
            for prefix in goal.prefixes
            if check.startswith(prefix)
        ]
        if not matches:
            unmapped.append(check)
            continue
        longest = max(length for length, _ in matches)
        if len({goal for length, goal in matches if length == longest}) != 1:
            tied.append(check)
    assert unmapped == [], f"check ids with no goal: {sorted(unmapped)}"
    assert tied == []


def test_the_states_and_reasons_are_all_worded() -> None:
    words = load_words()
    assert set(words.goal_states) == {"issues", "checked", "not_reached", "not_applicable"}
    assert set(words.goal_reasons) == {
        "unresolved",
        "skipped",
        "failed",
        "out_of_scope",
        "no_check",
    }
    assert words.goal_reasons["unresolved"] == "evidence missing"
    assert words.goal_reasons["no_check"] == "no check ran"
