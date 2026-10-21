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
from swreview.report.summary import WORDS_FILE, Words, goal_of, load_words

CONTACT_KINDS = ("zero_volume", "possible_only", "thread_model")
"""Feature 010's contact kinds (its data model section 9), labelled here ahead of it."""

PLACEHOLDERS: dict[str, set[str]] = {
    "headline.none": set(),
    "headline.findings_one": set(),
    "headline.findings_many": {"n"},
    "headline.issues_one": set(),
    "headline.issues_many": {"n"},
    "headline.checked": {"n"},
    "tally.item": {"label", "n"},
    "not_reached": {"titles"},
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
    "drawings.read_one": {"names"},
    "drawings.read_many": {"names"},
    "drawings.candidates_one": {"names"},
    "drawings.candidates_many": {"names"},
    "drawings.more": {"names", "n"},
    "drawings.open_then_review_one": {"names", "model"},
    "drawings.open_then_review_many": {"names", "model"},
    "contacts.one": set(),
    "contacts.many": {"n"},
    "resume.with_tokens": {"tokens"},
    "send.first_request": {"tokens"},
    "send.first_request_approximate": {"tokens"},
    "send.failed": {"reason", "time"},
    "send.not_started": {"reason", "time"},
    "send.restored_line": {"when"},
    "answer_basis.many": {"n"},
    "resume.without": set(),
    "finding_group_text.one": set(),
    "finding_group_text.many": {"n"},
    "finding_group_text.decided": {"d"},
    "finding_group_text.fold_tail": {"n"},
    "finding_group_text.reach_one": set(),
    "finding_group_text.reach_many": {"n"},
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
    [
        (),
        ("headline",),
        ("groups", "decide"),
        ("drawings",),
        ("resume",),
        ("send",),
        ("labels",),
        ("goals", 0),
        ("finding_groups", 0),
        ("finding_group_other",),
        ("finding_group_checked",),
        ("finding_group_text",),
        ("tally",),
        ("questions",),
        ("bought_parts",),
        ("answer_basis",),
    ],
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


def test_a_pass_is_checked_no_issue_in_the_groups_the_fold_and_the_goal_states() -> None:
    """013 research R3 C8: one word for the tally's passes, the fold and a checked goal."""
    words = load_words()
    assert words.groups["within_scope"].label == words.finding_group_checked.title
    assert words.groups["within_scope"].label == "Checked, no issue"
    assert words.groups["within_scope"].of(2) == "2 checked, no issue"
    assert words.headline.checked.format(n=2) == "2 checked, no issue"
    assert words.goal_states["checked"] == "checked, no issue"


def test_the_bought_parts_heading_and_the_text_box_placeholder_are_pane_words() -> None:
    """Feature 013 T033: the words file carries only these two part-roles words; the reasons,
    the rows' sentences and the question reach the model and are `checks/part_roles.py`'s
    constants (its `contracts/part-roles.md` section 3)."""
    words = load_words()
    assert words.bought_parts.heading == "Bought parts"
    assert words.questions.text_placeholder == "Or name the bought ones, separated by commas"


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


GOAL_TABLE: list[tuple[str, list[str], list[str], str]] = [
    (
        "interference",
        ["interference", "coverage.prerun.interference"],
        ["interference."],
        "interference_fit",
    ),
    (
        "fasteners",
        ["fasteners", "thread.fine_pitch", "thread.nonstandard_pitch"],
        ["fastener."],
        "fasteners",
    ),
    ("hole_alignment", ["holes.alignment"], ["hole.", "joint."], "interference_fit"),
    (
        "fits_and_stacks",
        ["interfaces.fit", "interfaces.stack"],
        ["fit.", "stack."],
        "interference_fit",
    ),
    ("tool_access", [], ["fastener.head_clearance", "fastener.head_fit"], "fasteners"),
    (
        "mass_and_material",
        ["mass.material"],
        ["mass.", "standards.part.material_assigned"],
        "mass_material",
    ),
    ("hygiene", ["provenance", "hygiene"], ["provenance.", "hygiene."], "hygiene"),
    (
        "standards",
        ["standards.release", "coverage.prerun.standards"],
        ["standards."],
        "standards",
    ),
    (
        "drawings",
        ["drawing.manufacturing_inputs"],
        ["drawing.", "drawing_profile.", "standards.drawing.", "rms.drawing."],
        "drawings",
    ),
    ("modelling_practice", ["modeling.resilience"], ["rms."], "modelling_practice"),
]
"""013 `contracts/grouped-list.md` section 2: the ten goals, their items, prefixes and group.
The `standards` goal is split out of `hygiene` (research R2.14). The Fasteners goal's items gain
the two thread pitch finding ids by name (feature 010's amendment of 2026-10-08, the owner's
decision 63A): its findings are listed under Fasteners and no goal line moves."""

SEVEN_GROUPS: list[tuple[str, str, bool]] = [
    ("interference_fit", "Interference and fit", True),
    ("fasteners", "Fasteners", True),
    ("drawings", "Drawings", True),
    ("standards", "Standards", True),
    ("modelling_practice", "Modelling practice", False),
    ("hygiene", "Hygiene", True),
    ("mass_material", "Mass and material", True),
]
"""013 research R2.13: the fixed order, Modelling practice arriving collapsed."""


def test_the_goals_are_the_ten_of_the_contract_in_their_order() -> None:
    goals = load_words().goals
    assert [(goal.id, goal.items, goal.prefixes, goal.group) for goal in goals] == GOAL_TABLE
    assert goals[-1].title == "Modelling practice"
    assert [goal.title for goal in goals if goal.id == "standards"] == ["Standards"]


def test_the_seven_groups_come_in_their_fixed_order_with_their_open_flags() -> None:
    words = load_words()
    assert [(group.id, group.title, group.open) for group in words.finding_groups] == SEVEN_GROUPS


def test_other_checks_and_the_checked_fold_are_worded() -> None:
    words = load_words()
    other, checked = words.finding_group_other, words.finding_group_checked
    assert (other.id, other.title, other.open) == ("other", "Other checks", True)
    assert (checked.title, checked.open, checked.exception_tail) == (
        "Checked, no issue",
        False,
        "within an accepted exception",
    )


def test_the_group_and_row_words() -> None:
    text = load_words().finding_group_text
    assert (text.one, text.many.format(n=3), text.decided.format(d=2)) == (
        "1 finding",
        "3 findings",
        "2 decided",
    )
    assert (text.fold_tail.format(n=3), text.reach_one, text.reach_many.format(n=2)) == (
        "×3",
        "reaches 1 component",
        "reaches 2 components",
    )


def test_the_separator_is_one_word_the_summary_and_the_rows_share() -> None:
    assert load_words().separator == " · "


def test_every_goal_names_one_of_the_seven_groups() -> None:
    words = load_words()
    groups = {group.id for group in words.finding_groups}
    assert {goal.group for goal in words.goals} <= groups
    assert words.finding_group_other.id not in groups


def test_every_group_has_a_goal_so_all_seven_render_by_default() -> None:
    words = load_words()
    assert {goal.group for goal in words.goals} == {group.id for group in words.finding_groups}


def test_every_classified_check_lands_in_one_of_the_seven_groups() -> None:
    """013 `contracts/grouped-list.md` section 7: no check id the policy classes falls to
    "Other checks"."""
    words = load_words()
    groups = {group.id for group in words.finding_groups}
    landed = {check: goal_of(check, words.goals) for check in load_policy().classes}
    assert {check for check, goal in landed.items() if goal is None} == set()
    assert {goal.group for goal in landed.values() if goal is not None} <= groups


@pytest.mark.parametrize(
    ("check", "group"),
    [
        ("standards.drawing.revision_matches", "drawings"),
        ("standards.part.sketches_fully_defined", "standards"),
        ("standards.part.material_assigned", "mass_material"),
        ("rms.drawing.model_items_preferred", "drawings"),
        ("rms.sketches.fully_defined", "modelling_practice"),
        ("hygiene.revision_present", "hygiene"),
        ("fastener.head_fit", "fasteners"),
        ("hole.coaxiality", "interference_fit"),
        ("stack.gap", "interference_fit"),
        ("drawing_profile.conformance", "drawings"),
        ("mass.density", "mass_material"),
        ("thread.fine_pitch", "fasteners"),
        ("thread.nonstandard_pitch", "fasteners"),
    ],
)
def test_a_check_lands_in_its_goals_group(check: str, group: str) -> None:
    goal = goal_of(check, load_words().goals)
    assert goal is not None and goal.group == group


def with_goal_group(data: dict[str, Any], goal_id: str, group: str) -> dict[str, Any]:
    for goal in data["goals"]:
        if goal["id"] == goal_id:
            goal["group"] = group
    return data


def test_a_goal_naming_a_group_the_file_does_not_list_is_refused() -> None:
    data = with_goal_group(raw_words(), "hygiene", "housekeeping")

    with pytest.raises(ValidationError, match="hygiene"):
        Words.model_validate(data)


def test_a_goal_without_a_group_is_refused() -> None:
    data = raw_words()
    del data["goals"][0]["group"]

    with pytest.raises(ValidationError):
        Words.model_validate(data)


def test_a_group_listed_twice_is_refused() -> None:
    data = raw_words()
    data["finding_groups"].append(dict(data["finding_groups"][0]))

    with pytest.raises(ValidationError, match="interference_fit"):
        Words.model_validate(data)


def test_other_checks_may_not_share_an_id_with_a_type_group() -> None:
    data = raw_words()
    data["finding_group_other"]["id"] = "hygiene"

    with pytest.raises(ValidationError, match="hygiene"):
        Words.model_validate(data)


def test_folding_mass_and_material_into_hygiene_is_one_valid_edit() -> None:
    """013 research R2.13: the owner may fold the seventh group away by one goal's `group`."""
    words = Words.model_validate(with_goal_group(raw_words(), "mass_and_material", "hygiene"))

    assert {goal.group for goal in words.goals} == {
        group.id for group in words.finding_groups
    } - {"mass_material"}


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


def test_every_classified_check_maps_to_exactly_one_goal_by_its_items_or_longest_prefix() -> None:
    """`goal_of`'s own rule (`report/finding_groups.py`): a classed id one goal's `items` name
    maps to that goal, every other one to exactly one goal by its longest prefix, and none is
    left unmapped or tied. Edited deliberately by feature 010's amendment of 2026-10-08 (the
    owner's decision 63A): the Fasteners goal owns the two thread pitch ids by name, in its
    `items`, never by a prefix, so this test, which asked every classed id to start with some
    goal's prefix, reads the items first as `goal_of` does."""
    goals = load_words().goals
    unmapped: list[str] = []
    tied: list[str] = []
    for check in load_policy().classes:
        named = [goal.id for goal in goals if check in goal.items]
        if named:
            if len(named) != 1:
                tied.append(check)
            continue
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


@pytest.mark.parametrize(
    ("check", "goal"),
    [
        ("joint.map", "hole_alignment"),
        ("hole.nominal_alignment", "hole_alignment"),
        ("hole.position_stack", "hole_alignment"),
        ("fastener.identity", "fasteners"),
        ("fastener.engagement", "fasteners"),
        ("fastener.head_clearance", "tool_access"),
        ("fastener.head_fit", "tool_access"),
        ("mass.density", "mass_and_material"),
        ("mass.coverage", "mass_and_material"),
        ("hygiene.part_number_matches_file", "hygiene"),
        ("hygiene.coverage", "hygiene"),
        ("thread.fine_pitch", "fasteners"),
        ("thread.nonstandard_pitch", "fasteners"),
    ],
)
def test_feature_010s_check_and_coverage_ids_land_in_their_goals(check: str, goal: str) -> None:
    """Feature 010's findings and its coverage-only rows (`joint.map`, `mass.coverage`,
    `hygiene.coverage`) each land in one goal: the coverage rows are what tell a goal line
    what the checks could not reach. The thread pitch rows, `thread.pitch`, are the one feature
    010 coverage id with no goal (the owner's decision 63A, 2026-10-08): they are listed with
    the review's coverage and never move the Fasteners line, which owns the two thread pitch
    finding ids by name."""
    found = goal_of(check, load_words().goals)

    assert found is not None and found.id == goal


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


def test_the_open_then_review_words_are_the_drawing_checks_instruction() -> None:
    """One instruction, two places (integration of lanes D and R, 2026-09-27): the summary's
    drawings words and the drawing check's coverage reason say the same thing, placeholder for
    placeholder, so neither can drift."""
    from swreview.checks.drawing_context import OPEN_THEN_REVIEW
    from swreview.report.summary import load_words

    drawings = load_words().drawings
    check = OPEN_THEN_REVIEW.format(drawing="FICT-1.SLDDRW", model="FICT-1.SLDASM")
    assert drawings.open_then_review_one.format(names="FICT-1.SLDDRW", model="FICT-1.SLDASM") == (
        check
    )
    assert drawings.open_then_review_many.format(names="FICT-1.SLDDRW", model="FICT-1.SLDASM") == (
        check
    )


# --- waiting to send (feature 015 T029) ----------------------------------------------------


SEND_SENTENCES = {
    "first_request": (
        "Send starts the model's review. Its first request is {tokens} input tokens; "
        "the requests after it are not counted in advance."
    ),
    "first_request_approximate": (
        "Send starts the model's review. Its first request is about {tokens} input tokens "
        "(approximate: Gemini counts tokens its own way); "
        "the requests after it are not counted in advance."
    ),
    "without": "Send starts the model's review.",
    "restored": "Send checks the saved evidence again, then starts the model's review.",
    "failed": (
        "The model did not answer: {reason} ({time}). "
        "Nothing else changed; Send to model is offered again."
    ),
    "not_started": (
        "Send to model could not start: {reason} ({time}). "
        "Nothing was sent; Send to model is offered again."
    ),
    "apply_answers": (
        "Applying your answers regrades the review by code. Nothing is sent to the model."
    ),
    "restored_line": "Its checks ran {when}; Send checks the saved evidence again first.",
    "rerun_failed": (
        "The saved evidence could not be checked again, so nothing changed and nothing was sent. "
        "The next Send tries again."
    ),
}
SEND_ERRORS = {
    "NoCredential": (
        "No key is available, so nothing was sent. "
        "Save a key in Settings; the review keeps waiting."
    ),
    "NotSent": (
        "This review has not been sent to the model, so it takes no follow-up yet. "
        "Press Send to model first."
    ),
    "NotWaiting": "This review is not waiting to be sent. Reload it to see where it stands.",
    "ReviewNotActive": (
        "This review is of another document. Open that document in SOLIDWORKS, then try again."
    ),
    "SettingNotSaved": "The settings could not be saved, so the stored settings stand.",
}


def test_the_send_block_is_the_nine_contract_sentences() -> None:
    words = load_words()
    assert words.send.__class__.__name__ == "SendWords"
    assert words.send.model_dump() == SEND_SENTENCES
    assert raw_words()["send"] == SEND_SENTENCES


@pytest.mark.parametrize("key", SEND_SENTENCES)
@pytest.mark.parametrize("mistake", ["missing", "misspelt"])
def test_every_send_key_is_required_and_typos_are_refused(key: str, mistake: str) -> None:
    data = raw_words()
    assert "send" in data
    value = data["send"].pop(key)
    if mistake == "misspelt":
        data["send"][key + "_typo"] = value
    with pytest.raises(ValidationError):
        Words.model_validate(data)


def test_read_only_sentences_are_separate_and_the_old_property_is_exact() -> None:
    words = load_words()
    assert words.read_only_lead == (
        "The backend restarted, so this review is shown from its run folder."
    )
    assert words.read_only_off == "Follow-ups, decisions and answers are off."
    assert words.read_only == (
        "The backend restarted, so this review is shown from its run folder. "
        "Follow-ups, decisions and answers are off."
    )
    assert "read_only" not in raw_words()
    assert "read_only" not in words.model_dump()
    assert words.send.restored_line.count("backend restarted") == 0


@pytest.mark.parametrize("key", ["read_only_lead", "read_only_off"])
def test_both_read_only_sentences_are_required(key: str) -> None:
    data = raw_words()
    assert key in data
    del data[key]
    with pytest.raises(ValidationError):
        Words.model_validate(data)


def test_the_replaced_read_only_file_key_is_refused() -> None:
    data = raw_words()
    data["read_only"] = load_words().read_only
    with pytest.raises(ValidationError):
        Words.model_validate(data)


def test_the_five_send_errors_are_exact_contract_sentences() -> None:
    errors = load_words().labels.errors
    assert {key: errors.get(key) for key in SEND_ERRORS} == SEND_ERRORS


RESTART_HOLDS = {
    "TurnRunning": "A review turn is still running. Wait for it to finish, or press Stop.",
    "RemodelRunning": "A remodel run is in progress. Wait for it to finish, then try again.",
    "BackendUnavailable": (
        "The review backend is not running or not answering. Save Settings to start it again, "
        "then retry."
    ),
}
"""The classes the add-in refuses a new review or a turn call with while the backend waits to be
restarted with settings saved during a turn (owner decision 143A): one for each thing that can
hold that restart back - a turn, a remodel run, a backend that does not answer - so the sentence
the page shows is true of what holds it. `RemodelRunning` is the add-in's own class; the backend
never sends it."""


def test_each_thing_that_holds_a_restart_back_has_a_true_sentence() -> None:
    errors = load_words().labels.errors
    assert {key: errors.get(key) for key in RESTART_HOLDS} == RESTART_HOLDS


SAVE_NOT_RESTARTED = {
    "BackendNotRestarted": (
        "The settings are saved, but the review backend did not restart with them. "
        "Save Settings again to retry the restart."
    ),
}
"""The class the add-in answers a settings save with when the save's restart fails, whatever it
threw (owner decision 150A): the settings are written and in force in the host before the backend
is restarted, so the sentence says they are saved, that the backend did not restart, and that saving
again retries the restart; the message in the fold gives the reason. `HostError`'s sentence, which
such a save used to meet, says nothing of either. The add-in's own class; the backend never sends
it."""


def test_a_save_whose_restart_failed_says_the_settings_are_saved() -> None:
    errors = load_words().labels.errors
    assert {key: errors.get(key) for key in SAVE_NOT_RESTARTED} == SAVE_NOT_RESTARTED


RUN_DIR_REFUSALS = {
    "InvalidRunDir": (
        "The backend refused the run folder's path: it writes only into a local folder inside "
        "the run root. Check the run root in Settings."
    ),
    "RunDirTaken": (
        "This run folder already holds another run's files, which a new review must not write "
        "over. Press Review to start the review in a new run folder."
    ),
}
"""The two classes a run folder is refused with before anything is written (owner decision 146A).
`InvalidRunDir` is the path rule's alone, and its sentence states the rule rather than that the
folder is outside the run root, which is untrue of a network path under a network run root or of
a path spelled with `..`. `RunDirTaken` is every refusal `chat/server.py`'s `_claim_run_dir`
makes for a folder that already holds another run's files - a check's, a re-modeler grade's, a
review's or any other session - which `InvalidRunDir`'s old sentence, "The run folder is not
inside the run root. Check the run root in Settings.", sent to the wrong place. The page shows a
class's sentence first and its message in a fold, so each sentence is true of every refusal that
carries its class, and says what to do."""


def test_each_refusal_of_a_run_folder_says_what_is_true_of_it() -> None:
    errors = load_words().labels.errors
    assert {key: errors.get(key) for key in RUN_DIR_REFUSALS} == RUN_DIR_REFUSALS


DOCUMENT_CHANGED = {
    "DocumentChanged": (
        "The active document or its configuration changed while the review was starting, so "
        "nothing was extracted. Make the part or assembly you want reviewed the active document, "
        "then press Review again."
    ),
}
"""The class the add-in refuses a new review with when the active document, read again once the
backend is ready, is not the one read when the review was asked for (owner decision 149A): a
settings restart the start makes or waits for takes seconds, in which the engineer can make
another document active, and the dump attaches to whatever is active when it runs. The add-in's
own class, as on the Remodel tab, whose page prints its message and reads no words file; the
backend never sends it. The sentence names no path and says what to do."""


def test_a_review_whose_document_changed_as_it_started_says_so_and_what_to_do() -> None:
    errors = load_words().labels.errors
    assert {key: errors.get(key) for key in DOCUMENT_CHANGED} == DOCUMENT_CHANGED


BRIDGE_ON_ANOTHER_DOCUMENT = {
    "BridgeOnAnotherDocument": (
        "The SOLIDWORKS bridge is not attached to this review's document yet, so the review did "
        "not start. It follows the active document once no review turn or remodel holds it. Wait "
        "a moment, then try again."
    ),
}
"""The class the add-in refuses a review's start with when the bridge the session would be given
is not on the review's document and configuration (owner decision 152A): the tool service it
belongs to is left on another document while a review turn or a remodel holds it, and for a moment
after a switch, and the session's live checks run over it and write into the review's package. The
add-in's own class, true of every start that carries it - a new review, a Retry, a context review
and a Recheck - so the way on is "try again", and the tool service is asked to follow the active
document as the refusal is made. The backend never sends it. The sentence names no path."""


def test_a_review_whose_bridge_is_on_another_document_says_so_and_what_to_do() -> None:
    errors = load_words().labels.errors
    labels = {key: errors.get(key) for key in BRIDGE_ON_ANOTHER_DOCUMENT}
    assert labels == BRIDGE_ON_ANOTHER_DOCUMENT
