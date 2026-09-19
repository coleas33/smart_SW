"""The attention policy data file loads and says what the owner agreed (T004).

`attention_policy_v1.yaml` is the consequence table as data, beside the pure module that
will read it (`report/attention.py`, T019). This module pins the file's own shape - it
loads, it is versioned, every class is one of the six, the four owner decisions of research
R2.15 are in it, and it carries no percent sign, because the Standards page's body scan
forbids one anywhere in what it renders (research R2.14).

**The catalogue is not checked here.** "Every emittable check id has a class, and the file
names no id the product cannot emit" is T023, which lands after the read-through (T022), so
that no test pins a table nobody has agreed to. What is checked here is that the file is
well formed and that the decisions already taken are in it.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

import swreview.report

POLICY_FILE = Path(swreview.report.__file__).resolve().parent / "attention_policy_v1.yaml"

CONSEQUENCE_CLASSES: tuple[str, ...] = (
    "rebuild_breaker",
    "interface",
    "manufacturing",
    "unclassified",
    "discipline",
    "hygiene",
)
"""The six classes, in the order key 3 sorts them (data-model.md section 1)."""

PRERUN_FAMILIES: frozenset[str] = frozenset(
    {"fastener_joint", "hole_alignment", "fit", "axial_stack", "interference", "standards"}
)
"""The families the gate's brief has to say something about (`prerun.not_evaluated_families`,
plus the standards half T049 adds)."""

AGREED_CLASSES: dict[str, str] = {
    "rms.assembly.mates_to_reference_geometry": "rebuild_breaker",
    "rms.sketches.fully_defined": "rebuild_breaker",
    "rms.assembly.first_component_fixed": "rebuild_breaker",
    "rms.folders.present": "hygiene",
    "interference.static": "interface",
}
"""What the owner decided on 2026-09-19 over a preview of the same rule (research R2.15)."""

AGREED_PREFIXES: tuple[tuple[str, str], ...] = (
    ("rms.grouping.", "discipline"),
    ("rms.params.", "discipline"),
    ("fit.", "interface"),
    ("fastener.", "interface"),
    ("hole.", "interface"),
    ("stack.", "interface"),
    ("standards.drawing.", "manufacturing"),
)
"""The same four decisions, where they were taken over a family rather than one id."""


def policy() -> dict[str, Any]:
    document = yaml.safe_load(POLICY_FILE.read_text(encoding="utf-8"))
    assert isinstance(document, dict), f"{POLICY_FILE} is not a YAML mapping"
    return document


def test_the_policy_file_loads_and_is_versioned() -> None:
    assert policy()["version"] == "attention_policy_v1"


def test_the_needs_judgement_set_is_the_four_declared_prefixes() -> None:
    assert policy()["needs_judgement"] == ["interference.", "fit.", "fastener.", "hole."]


def test_every_class_is_one_of_the_six_and_none_is_unclassified() -> None:
    classes = policy()["classes"]
    assert isinstance(classes, dict) and classes, "the policy names no check id at all"

    wrong = {check: value for check, value in classes.items() if value not in CONSEQUENCE_CLASSES}
    undecided = sorted(check for check, value in classes.items() if value == "unclassified")

    assert wrong == {}, f"{wrong} are not one of {list(CONSEQUENCE_CLASSES)}"
    assert undecided == [], (
        f"{undecided} are listed as unclassified; `unclassified` is what an id the table "
        "does not name sorts as, never a class the table assigns"
    )


def test_the_table_names_each_check_id_once() -> None:
    """YAML keeps the last of two duplicate keys silently; the raw text is the only witness."""
    text = POLICY_FILE.read_text(encoding="utf-8")
    block = re.search(r"^classes:\n((?:(?:[ \t]+.*)?\n)*)", text, re.M)
    assert block is not None, "the policy file has no `classes:` block"

    keys = re.findall(r"^  ([^\s#][^:]*):", block.group(1), re.M)

    duplicated = sorted({key for key in keys if keys.count(key) > 1})
    assert duplicated == [], f"{duplicated} appear twice under `classes`"
    assert set(keys) == set(policy()["classes"])


def test_the_owner_s_decisions_of_2026_09_19_are_in_the_table() -> None:
    classes = policy()["classes"]

    disagreements = [
        f"{check}: {classes.get(check)} rather than {expected}"
        for check, expected in AGREED_CLASSES.items()
        if classes.get(check) != expected
    ]
    for prefix, expected in AGREED_PREFIXES:
        named = {check: value for check, value in classes.items() if check.startswith(prefix)}
        assert named, f"the table names no check id under {prefix!r}"
        disagreements.extend(
            f"{check}: {value} rather than {expected}"
            for check, value in named.items()
            if value != expected
        )

    assert disagreements == []


def test_one_blind_spot_sentence_per_pre_run_family() -> None:
    blind_spots = policy()["blind_spots"]

    assert set(blind_spots) == PRERUN_FAMILIES
    for family, sentence in blind_spots.items():
        assert isinstance(sentence, str) and sentence.endswith("."), (
            f"{family}'s blind spot is not a sentence: {sentence!r}"
        )


def test_the_four_triage_pass_preconditions_are_recorded() -> None:
    """FR-035: the question is answered by a written rule rather than re-argued."""
    preconditions = policy()["triage_pass_preconditions"]

    assert isinstance(preconditions, list)
    assert len(preconditions) == 4, preconditions
    assert all(isinstance(one, str) and one.strip().endswith(".") for one in preconditions)


def test_no_percent_sign_anywhere_in_the_policy_file() -> None:
    """Research R2.14: the Standards page's body scan forbids one in what it renders."""
    text = POLICY_FILE.read_text(encoding="utf-8")

    offenders = [
        f"line {number}: {line.strip()}"
        for number, line in enumerate(text.splitlines(), start=1)
        if "%" in line
    ]

    assert offenders == []
