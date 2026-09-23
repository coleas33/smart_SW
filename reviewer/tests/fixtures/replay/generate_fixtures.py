"""Generate one replay fixture from a recorded review (feature 008 T018, `contracts/replay.md` §8).

Run from `reviewer/`, on the machine that holds the recordings, and commit what it writes:

    uv run python tests/fixtures/replay/generate_fixtures.py --recorded <RUN_DIR> --name <NAME>
        [--groups N]

`--groups` is how many interference groups the recording's live detection found, when that is
more than the groups the model judged (the big recording's model wrote the count in its own
prose; nothing else in the folder records it).

**What it keeps.** The recording's shape: every recorded call, with its recorded arguments, in
its recorded round and turn; every round's recorded usage, adjusted by exactly the size
difference the fictional results make; the presentation request's usage, carried; the package's
structure - ids, SOLIDWORKS type names, enums, units, numbers, timestamps, the feature tree,
the mates, the persistent references' bytes other than the names inside them.

**What it scrambles.** Every identifying string, through `tests/support/scramble.FictionalMap`:
names, paths (under `C:\\FictionalVault\\`), property values, gap reasons, equation text,
configuration names, the names and paths inside persistent references, document ids, and the
model's prose in the recorded arguments (`request_evidence`'s `what` and `why`,
`mark_coverage`'s `reason` and `scope`). Paths and names are strict: every folder is scrambled
whole, file stems and component names keep only sizes, short numbers and single characters,
and every word of a path or a name - and every supplier code next to a catalogue number - is
scrambled wherever else it appears, in the package and in the arguments alike
(`scramble.strict_tokens`). Custom and configuration property keys and values are strict too:
every word of them is scrambled, generic or not, and so is the same word wherever else it
appears - a configuration name, a gap reason, the model's prose - so a company's property
names, workflow states and export-control wording cannot survive
(`scramble.property_tokens`). A property keeps only a whole value of numbers, fractions or
dates, sizes, short numbers and single characters, the head of a SOLIDWORKS link
(`SW-Mass@`, the configuration and document after it scrambled), and the words
`config/standards.example.yaml` itself names - public already, and what the profile the
fixtures are graded with must still find (`scramble.profile_words`, read from the profile
when the generator runs). The model's own text is not reused at all: each turn closes with a
fixed fictional sentence.

**What it adds.** When the recording made a live `bridge_interference` call, the rows that call
found, in the shape feature 008's checks first persists them (FR-009): the judged groups' rows
rebuilt from the recorded findings (ids, pairs, volumes, configuration and settings as
recorded) and fictional rows up to `--groups`, with extra rows until the live call's result is
the recorded size. They go into the fixture's `package.json`, and the recording's live call is
answered with them through `tests/support/review_bridge.ScriptedReviewBridge`.

**How the fixture is written.** The recorded call script is played through the current code
with `tests/support/replay.record_scripted_review`, graded with
`config/standards.example.yaml` (the profile the pilot ran). Each round's usage is the recorded
usage plus the running sum of (fixture minus original) result tokens over the results that
round is sent with. An original result's size is the current code's result on the original
package when it reproduces the recorded one (same status, same summary, and a size within the
framing noise of the recorded growth), and the recorded growth otherwise.

**It checks itself and refuses to write** unless the fixture's finding-key multiset equals the
recording's (through the same map) - less each recorded `interference.static` finding that a
contact of the fixture reclassifies, by the replay's own rule (`reclassifying_contacts` over
`judged_group`, imported, never copied; owner decision 3A of 2026-09-23), since feature 010's
code records a touching group as a contact - every result of 5,000 tokens or more is within
5% of its recorded size, no identifying token of the recording - three characters or more with a
letter, or five digits or more - remains in any string of the three files or inside a
persistent reference, no word of three letters or more of a recorded property key or value
remains in the fixture's property keys and values unless the example profile names it, and
no folder between the fictional root and a file name is named, in any case, like a folder the
recorded package carried. A generic word made strict only by a property (`not`, `and`) is
policed by the property check alone: the reviewer's own sentences use it. It then refreshes
the owner's denylist, `%LOCALAPPDATA%\\SwReview\\fixture-denylist.txt`, outside the
repository, with the tokens it replaced and the recorded folder names; neither is ever
written into the repository.

This file never contains a recorded string: every value it needs is read from the recording.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

FIXTURE_ROOT = Path(__file__).resolve().parent
REVIEWER = FIXTURE_ROOT.parents[2]
sys.path.insert(0, str(REVIEWER))

from tests.support.replay import record_scripted_review  # noqa: E402
from tests.support.review_bridge import (  # noqa: E402
    VOLUME_UNIT_GAP,
    ScriptedReviewBridge,
    interference_row,
)
from tests.support.scramble import (  # noqa: E402
    FICTIONAL_ROOT,
    FictionalMap,
    decoded_runs,
    denylist_path,
    folder_names,
    folders_of,
    is_allowed_token,
    letters,
    path_values,
    profile_words,
    property_strings,
    property_tokens,
    read_denylist,
    strict_property_words,
    strict_tokens,
    strings_of,
    tokens_of,
    without_reviewer_text,
    write_denylist,
)

from swreview.agent.providers import FRAMING_TOKENS, TokenUsage  # noqa: E402
from swreview.benchmark.recording import (  # noqa: E402
    RecordedCall,
    RecordedRound,
    Recording,
    read_recording,
)
from swreview.benchmark.replay import (  # noqa: E402
    JudgedGroup,
    PlayedRound,
    estimated_sizes,
    judged_group,
    play_review,
    reclassifying_contacts,
    same_summary,
    turn_plans,
)
from swreview.findings import SubjectKey, finding_subject_key  # noqa: E402
from swreview.ir.loader import PACKAGE_FILE_NAME  # noqa: E402
from swreview.ir.models import EvidencePackage  # noqa: E402
from swreview.tokens import count_tokens  # noqa: E402

STANDARDS_PROFILE = Path("..") / "config" / "standards.example.yaml"
"""Relative to `reviewer/`, because the path is written into the standards findings' coverage
limits: an absolute one would put this machine's folders into a public fixture."""
LIVE_TOOL = "bridge_interference"
FIXTURE_FILES = ("package.json", "session.json", "events.jsonl")
CLOSING_TEXT = "The review of this fictional assembly is complete; the open questions are recorded."
FOLLOW_UP_TEXT = "Is anything else left to check on this assembly?"
LARGE_RESULT_TOKENS = 5_000
LARGE_RESULT_TOLERANCE = 0.05
FRAMING_NOISE = 3
"""How far a reproduced result's size may sit from the recorded growth: the provider's framing
varied between 11 and 14 tokens around the 12 the replay adds (research R2.5)."""


# --- the recording's tokens and the denylist ---------------------------------------------


def identifying(token: str) -> bool:
    """A replaced token the leak check and the denylist police.

    Three characters or more with a letter, or five digits or more. Shorter numbers are
    scrambled wherever they sit inside a name, but a three-digit number alone identifies
    nobody and appears legitimately everywhere (a count, a digit run inside a float).
    """
    if token.isdigit():
        return len(token) >= 5
    return len(token) >= 3


def recorded_tokens(recording: Recording, raw_package: Mapping[str, Any]) -> set[str]:
    """Every token of the recording's package and arguments, the persistent refs' included."""
    found: set[str] = set()
    for text in strings_of(raw_package):
        found.update(tokens_of(text))
        for run in decoded_runs(text):
            found.update(tokens_of(run))
    for call in all_calls(recording):
        for text in strings_of(call.arguments):
            found.update(tokens_of(text))
    return found


def all_calls(recording: Recording) -> list[RecordedCall]:
    """Every recorded model call in order: the index the replay's played calls carry."""
    return [call for turn in recording.turns for r in turn.rounds for call in r.calls]


def round_of(recording: Recording, step: int) -> RecordedRound:
    for turn in recording.turns:
        for recorded in turn.rounds:
            if any(call.step == step for call in recorded.calls):
                return recorded
    raise LookupError(f"step {step} is in no recorded round")


# --- the live interference rows ------------------------------------------------------------


def live_call(recording: Recording) -> RecordedCall | None:
    calls = [call for call in all_calls(recording) if call.tool == LIVE_TOOL]
    if len(calls) > 1:
        raise SystemExit(
            f"{recording.run_dir} made {len(calls)} live {LIVE_TOOL} calls; this generator "
            "answers one"
        )
    return calls[0] if calls else None


def fixture_group(fmap: FictionalMap, group: JudgedGroup) -> JudgedGroup:
    """A recorded `(group key, configuration)` in the fixture's names.

    The key as free text and the configuration as a field value: exactly how `judged_rows`
    writes the rows the fixture's groups - and so its contacts - are built from, so a recorded
    finding and the contact the current code records for its group name the same group.
    """
    group_key, configuration = group
    return fmap.text(group_key), fmap.value(configuration)


def judged_rows(recording: Recording, fmap: FictionalMap) -> list[dict[str, Any]]:
    """The rows behind every recorded interference finding, from its calculation inputs."""
    rows: list[dict[str, Any]] = []
    for recorded in recording.findings:
        finding = recorded.finding
        if not finding.check.startswith("interference.") or finding.calculation is None:
            continue
        inputs = {key: str(value) for key, value in finding.calculation.inputs.items()}
        group_key, configuration = fixture_group(
            fmap, (inputs["group_key"], inputs["configuration"])
        )
        settings = {
            "treat_coincident_as_interference": inputs["treat_coincident_as_interference"]
            == "True",
            "treat_subassemblies_as_components": inputs["treat_subassemblies_as_components"]
            == "True",
            "include_multibody": inputs["include_multibody"] == "True",
            "ignore_hidden": inputs["ignore_hidden"] == "True",
            "fastener_folder_treatment": inputs["fastener_folder_treatment"],
        }
        for key, pair in inputs.items():
            if not key.endswith("_pair"):
                continue
            row_id = key[: -len("_pair")]
            volume_mm3 = float(inputs[f"{row_id}_volume_mm3"].split()[0])
            rows.append(
                interference_row(
                    row_id,
                    tuple(pair.split("+")),
                    group_key,
                    volume_m3=volume_mm3 / 1e9,
                    configuration=configuration,
                    settings=settings,
                )
            )
    return rows


def fictional_pairs(
    component_ids: Sequence[str], taken: set[frozenset[str]]
) -> Iterable[tuple[str, str]]:
    """Component pairs no judged group uses, in a fixed order."""
    for index, first in enumerate(component_ids):
        for second in component_ids[index + 1 :]:
            if frozenset((first, second)) not in taken:
                yield first, second


def all_rows(
    judged: list[dict[str, Any]],
    component_ids: Sequence[str],
    groups: int,
    extra: int,
    arguments: Mapping[str, Any],
    configuration: str,
) -> list[dict[str, Any]]:
    """The judged rows, one fictional row per group up to `groups`, then `extra` more rows."""
    judged_keys = {row["group_key"] for row in judged}
    taken = {frozenset(row["component_ids"]) for row in judged}
    used_ids = {row["id"] for row in judged}
    numbers = (f"int:{number:04d}" for number in range(1, 100_000))
    free_ids = (row_id for row_id in numbers if row_id not in used_ids)
    wanted = max(groups - len(judged_keys), 0)
    pairs = []
    for pair in fictional_pairs(component_ids, taken):
        if len(pairs) == wanted:
            break
        pairs.append(pair)
    if len(pairs) < wanted:
        raise SystemExit(f"the package has too few components for {groups} interference groups")
    settings = dict(arguments["settings"])
    rows = list(judged)
    for position in range(len(pairs) + extra):
        first, second = pairs[position % len(pairs)]
        rows.append(
            interference_row(
                next(free_ids),
                (first, second),
                f"{first}|{second}",
                volume_m3=0.0,
                configuration=configuration,
                settings=settings,
            )
        )
    return sorted(rows, key=lambda row: row["id"])


def live_result_tokens(
    package: Mapping[str, Any], rows: list[dict[str, Any]], arguments: Mapping[str, Any]
) -> int:
    """The tokens the live call's result has on the fixture package, through the real tool."""
    from swreview.tools.context import context_for
    from swreview.tools.registry import ToolRegistry

    context = context_for(EvidencePackage.model_validate(package))
    context.bridge = ScriptedReviewBridge(results={"interference": [answer_of(rows)]})
    result = ToolRegistry().dispatch(context).call(LIVE_TOOL, dict(arguments))
    return count_tokens(json.dumps(result.payload))


def answer_of(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {"interferences": rows, "gaps": [dict(VOLUME_UNIT_GAP)] if rows else []}


def with_rows(package: Mapping[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    """The package as checks first would have persisted the live call: its rows and its gap."""
    persisted = dict(package)
    persisted["interferences"] = rows
    if rows:
        persisted["gaps"] = [*package["gaps"], dict(VOLUME_UNIT_GAP)]
    return persisted


# --- sizes ---------------------------------------------------------------------------------


def original_sizes(
    recording: Recording,
    rows: list[dict[str, Any]],
    live: RecordedCall | None,
    scratch: Path,
) -> dict[int, tuple[int, str]]:
    """Each recorded call's result size in tokens, by call index, with how it was measured.

    The original package is played as recorded - no rows persisted, the live call answered
    with the rows - and a call counts as reproduced when its status and summary match the
    recording (ids compared as ids, the replay's own `same_summary`) and its size sits within
    the framing noise of the recorded growth. Every other call is sized from the recorded growth.
    """
    played = play_review(
        recording.package_path.parent,
        scratch / "original",
        turn_plans(recording, text=CLOSING_TEXT, follow_up_text=FOLLOW_UP_TEXT),
        model=recording.session.model,
        **bridge_options(live, rows),
    )
    calls = [call for played_round in played.rounds for call in played_round.calls]
    recorded = all_calls(recording)
    if len(calls) != len(recorded):
        raise SystemExit(f"the original replay made {len(calls)} calls; recorded {len(recorded)}")
    sizes: dict[int, tuple[int, str]] = {}
    reproduced: dict[int, int] = {}
    for index, (mine, theirs) in enumerate(zip(calls, recorded, strict=True)):
        size = count_tokens(mine.text)
        growth = recording.growth_after(round_of(recording, theirs.step))
        close = growth is None or abs(size + FRAMING_TOKENS - growth) <= FRAMING_NOISE
        single = len(round_of(recording, theirs.step).calls) == 1
        same = mine.status == theirs.status and same_summary(theirs.summary, mine.summary)
        if same and (close or not single):
            reproduced[theirs.step] = size
            sizes[index] = (size, "reproduced")
    for index, theirs in enumerate(recorded):
        if index in sizes:
            continue
        recorded_round = round_of(recording, theirs.step)
        known = {
            call.step: reproduced[call.step]
            for call in recorded_round.calls
            if call.step in reproduced
        }
        size, lower_bound = estimated_sizes(recording, recorded_round, known)[theirs.step]
        sizes[index] = (size, "lower bound" if lower_bound else "estimated")
    return sizes


def bridge_options(live: RecordedCall | None, rows: list[dict[str, Any]]) -> dict[str, Any]:
    options: dict[str, Any] = {"standards_profile": STANDARDS_PROFILE}
    if live is not None:
        answer = answer_of(rows)
        options["bridge"] = True
        options["bridge_factory"] = lambda pipe, secret: ScriptedReviewBridge(
            results={"interference": [answer]}
        )
    return options


def adjusted(recorded: TokenUsage, delta: int) -> TokenUsage:
    """The recorded usage with `delta` more input tokens (and a cached count still inside it)."""
    input_tokens = (recorded.input_tokens or 0) + delta
    cached = recorded.cached_input_tokens
    return recorded.model_copy(
        update={
            "input_tokens": input_tokens,
            "cached_input_tokens": None if cached is None else min(cached, input_tokens),
            "total_tokens": None
            if recorded.total_tokens is None
            else recorded.total_tokens + delta,
        }
    )


# --- the self-check --------------------------------------------------------------------------


def scrambled_key(fmap: FictionalMap, key: SubjectKey) -> SubjectKey:
    check, components, locations, inputs, configuration = key
    return (
        check,
        components,
        tuple(
            (
                fmap.value(document_id),
                None if sheet is None else fmap.value(sheet),
                None if view is None else fmap.value(view),
                None if annotation is None else fmap.value(annotation),
                page,
            )
            for document_id, sheet, view, annotation, page in locations
        ),
        inputs,
        fmap.value(configuration),
    )


def finding_problems(
    recording: Recording, written: Recording, fmap: FictionalMap
) -> tuple[list[str], int]:
    """Why the fixture's findings are not the recording's, and how many it reclassified.

    The recording's finding keys, through the map, must be the fixture's as a multiset - after
    taking out every recorded finding a contact of the fixture reclassifies (decision 3A,
    `contracts/replay.md` section 8). That is the replay's own rule, imported: a recorded
    `interference.static` finding whose group, carried into the fixture's names
    (`fixture_group`), is a contact's group and configuration. Since feature 010 the current
    code records a touching group as a contact, where the recorded review wrote a finding.
    """
    contacts = reclassifying_contacts(
        [
            None if group is None else fixture_group(fmap, group)
            for group in (judged_group(item.finding) for item in recording.findings)
        ],
        written.session.contacts,
    )
    expected = Counter(
        scrambled_key(fmap, finding_subject_key(item.finding))
        for item, contact in zip(recording.findings, contacts, strict=True)
        if contact is None
    )
    actual = Counter(finding_subject_key(item.finding) for item in written.findings)
    problems: list[str] = []
    if expected != actual:
        problems.append(
            f"the finding keys differ: {sum((expected - actual).values())} recorded keys are "
            f"missing and {sum((actual - expected).values())} are new"
        )
    return problems, sum(1 for contact in contacts if contact is not None)


def documents_of(folder: Path, name: str) -> list[Any]:
    """The JSON documents of one fixture file: one per line of the event log."""
    text = (folder / name).read_text(encoding="utf-8")
    if name.endswith(".jsonl"):
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    return [json.loads(text)]


def recorded_folders_found(folder: Path, recorded: set[str]) -> list[str]:
    """Every fixture folder, below the fictional root, named like a recorded folder."""
    names = {name.casefold() for name in recorded}
    return [
        f"{name} names the recorded folder {segment!r}"
        for name in FIXTURE_FILES
        for document in documents_of(folder, name)
        for value in path_values(document)
        if value.startswith(FICTIONAL_ROOT)
        for segment in folders_of(value)[1:]
        if segment.casefold() in names
    ]


def surviving_property_words(
    raw_package: Mapping[str, Any], folder: Path, public: frozenset[str]
) -> list[str]:
    """Every word of three letters or more of the recording's property keys and values that
    the fixture's property keys and values still carry, the profile's own words apart."""
    recorded = {
        word
        for text in property_strings(raw_package)
        for word in strict_property_words(text, public)
        if letters(word) >= 3
    }
    [package] = documents_of(folder, "package.json")
    written = {
        word for text in property_strings(package) for word in strict_property_words(text, public)
    }
    return [
        f"package.json keeps the recorded property word {word!r}"
        for word in sorted(recorded & written)
    ]


def leaks(folder: Path, denied: set[str]) -> list[str]:
    found: list[str] = []
    for name in FIXTURE_FILES:
        tokens: set[str] = set()
        for document in documents_of(folder, name):
            for value in strings_of(document):
                tokens.update(tokens_of(without_reviewer_text(value)))
                for run in decoded_runs(value):
                    tokens.update(tokens_of(run))
        found += [f"{name} still carries the recorded token {token!r}" for token in tokens & denied]
    return found


def self_check(
    recording: Recording,
    raw_package: Mapping[str, Any],
    fixture: Path,
    fmap: FictionalMap,
    sizes: Mapping[int, tuple[int, str]],
    fixture_sizes: Mapping[int, int],
    recorded_folders: set[str],
    public: frozenset[str],
    generic_property_words: set[str],
) -> tuple[list[str], int]:
    """Why the fixture must not be written - empty when it may - and how many recorded
    findings its contacts reclassified (`finding_problems`).

    `generic_property_words` are generic words made strict only by a property key or value.
    Outside the package the reviewer writes them in its own sentences (`not`, `and`), and the
    package keeps them in verbatim fields (`not_extracted`), so they are policed where they
    were recorded - the property keys and values (`surviving_property_words`) - rather than
    by the leak check.
    """
    problems, reclassified = finding_problems(recording, read_recording(fixture), fmap)
    for index, (size, how) in sorted(sizes.items()):
        if size < LARGE_RESULT_TOKENS:
            continue
        mine = fixture_sizes[index]
        if abs(mine - size) > LARGE_RESULT_TOLERANCE * size:
            problems.append(
                f"call {index} is {mine} tokens against {size} recorded ({how}), beyond 5%"
            )
    denied = {token for token in fmap.replaced if identifying(token)} - generic_property_words
    problems += leaks(fixture, denied)
    problems += surviving_property_words(raw_package, fixture, public)
    problems += recorded_folders_found(fixture, recorded_folders)
    return problems, reclassified


# --- the run ---------------------------------------------------------------------------------


def generate(recorded_dir: Path, name: str, groups: int | None) -> int:
    if Path.cwd().resolve() != REVIEWER:
        raise SystemExit(f"run this from {REVIEWER}; the standards profile path is relative to it")
    recording = read_recording(recorded_dir)
    raw = json.loads(recording.package_path.read_text(encoding="utf-8"))
    type_names = {feature["type_name"] for feature in raw.get("features", [])}
    denied_tokens, denied_folders = read_denylist(denylist_path())
    recorded_folders = folder_names(raw)
    public = profile_words(STANDARDS_PROFILE)
    name_words = strict_tokens(raw, *(call.arguments for call in all_calls(recording)))
    property_words = property_tokens(raw, public=public)
    fmap = FictionalMap(
        reserved=recorded_tokens(recording, raw) | denied_tokens,
        keep=type_names,
        strict=name_words | property_words,
        public=public,
    )
    package = fmap.package(raw)
    scrambled_arguments = {
        call.step: fmap.arguments(call.arguments) for call in all_calls(recording)
    }
    live = live_call(recording)

    rows: list[dict[str, Any]] = []
    if live is not None:
        judged = judged_rows(recording, fmap)
        target_groups = max(groups or 0, len({row["group_key"] for row in judged}))
        root = package["design"]["root_assembly_document_id"]
        component_ids = [
            component["id"]
            for component in package["components"]
            if component["document_id"] != root
        ]
        live_arguments = scrambled_arguments[live.step]
        configuration = fmap.value(str(live.arguments.get("configuration") or "Default"))
        recorded_size, _ = estimated_sizes(recording, round_of(recording, live.step), {})[live.step]

        def rows_with(extra: int) -> list[dict[str, Any]]:
            return all_rows(
                judged, component_ids, target_groups, extra, live_arguments, configuration
            )

        rows = rows_with(0)
        if recorded_size >= LARGE_RESULT_TOKENS and target_groups > len(judged):
            base = live_result_tokens(with_rows(package, rows), rows, live_arguments)
            step = live_result_tokens(
                with_rows(package, rows_with(10)), rows_with(10), live_arguments
            )
            per_row = max((step - base) / 10, 1.0)
            extra = max(round((recorded_size - base) / per_row), 0)
            rows = rows_with(extra)
        print(f"live interference: {len(rows)} rows in {target_groups} groups")

    fixture_package = with_rows(package, rows)
    EvidencePackage.model_validate(fixture_package)

    def arguments_of(call: RecordedCall) -> Mapping[str, Any]:
        return scrambled_arguments[call.step]

    fixture_turns = turn_plans(
        recording, arguments=arguments_of, text=CLOSING_TEXT, follow_up_text=FOLLOW_UP_TEXT
    )
    presentation = next(
        (r.usage for t in recording.turns for r in t.rounds if r.kind == "presentation"), None
    )

    with tempfile.TemporaryDirectory(prefix="swreview-fixture-") as scratch_name:
        scratch = Path(scratch_name)
        sizes = original_sizes(recording, rows, live, scratch)
        package_dir = scratch / "package"
        package_dir.mkdir()
        (package_dir / PACKAGE_FILE_NAME).write_text(
            json.dumps(fixture_package, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        fixture_sizes: dict[int, int] = {}

        def usage_for(played: PlayedRound) -> TokenUsage:
            for call in (*played.visible, *played.calls):
                fixture_sizes[call.index] = count_tokens(call.text)
            recorded_round = recording.turns[played.turn].main_rounds[played.index]
            delta = sum(count_tokens(call.text) - sizes[call.index][0] for call in played.visible)
            return adjusted(recorded_round.usage, delta)

        out = record_scripted_review(
            scratch / "fixture",
            package_dir,
            fixture_turns,
            usage_for=usage_for,
            presentation=presentation,
            model=recording.session.model,
            **bridge_options(live, rows),
        )
        problems, reclassified = self_check(
            recording,
            raw,
            out,
            fmap,
            sizes,
            fixture_sizes,
            recorded_folders,
            public,
            {word for word in property_words - name_words if is_allowed_token(word)},
        )
        if problems:
            for problem in problems:
                print(f"refused: {problem}", file=sys.stderr)
            return 1
        target = FIXTURE_ROOT / name
        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True)
        for file_name in FIXTURE_FILES:
            shutil.copyfile(out / file_name, target / file_name)

    # Only what names something on its own goes to the shared denylist: a generic word made
    # strict here (an upper-case material in a file stem) is generic in another fixture.
    entries = denied_tokens | {
        token for token in fmap.replaced if identifying(token) and not is_allowed_token(token)
    }
    folders = denied_folders | recorded_folders
    write_denylist(denylist_path(), entries, folders)
    estimated = sum(1 for _, how in sizes.values() if how != "reproduced")
    print(
        f"wrote {target}: {len(sizes)} calls ({estimated} sized from the recorded growth), "
        f"{len(recording.findings)} findings ({reclassified} reclassified as contacts); the "
        f"denylist holds {len(entries)} tokens and {len(folders)} folder names"
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--recorded", type=Path, required=True, help="the recorded run folder")
    parser.add_argument("--name", required=True, help="the fixture folder to write")
    parser.add_argument(
        "--groups",
        type=int,
        default=None,
        help="interference groups the live detection found, when more than were judged",
    )
    options = parser.parse_args(argv)
    return generate(options.recorded, options.name, options.groups)


if __name__ == "__main__":
    raise SystemExit(main())
