"""The one set root and the set's two written forms (T016, for T017).

Every benchmark set is read through one core, `load_set(path, *, root)`, and the root it
is given decides every path rule (`cases.md` 4.2 and 4.3 row 3; `provenance.md` 6.1; plan
decisions RF-4, RF-54, RF-61):

1. **Resolution.** A relative entry resolves against the root only in a set file lying in
   `<root>/benchmarks/sets/` itself. A set file anywhere else names every path absolutely,
   and a relative entry there is refused by row 3 with a `SetError`; one in another
   checkout's `benchmarks/sets/` (another worktree's, say) is refused naming both roots,
   since resolving it against either would give one set two saved forms and two
   `set_digest`s (FR-051). Absolute entries load from any location.
2. **The saved copy.** `load_saved_set` reads a run folder's `benchmark-set.json` through
   the same core, accepting its relative entries and resolving them against the root
   given, never against the run folder's grandparent.
3. **Two forms, one entry serializer.** `file_form` and `saved_form` write in-root paths,
   an entry's `case_file` among them, root-relative with `/` and private ones absolute, as
   UTF-8 JSON, indent 2, LF, with a final newline, so two copies of one tree at two
   locations give the same bytes. The saved form is the file form plus each entry's
   `case_file_sha256` (US4, T093), which moved
   `test_file_form_and_saved_form_are_one_serializer_until_us4` deliberately into
   `test_saved_form_is_the_file_form_plus_each_entry_s_case_file_sha256`.
4. **One inside-the-checkout rule.** `checkout_relative(path, *, root)` resolves both and
   gives the path relative to the root when it lies inside it, else `None`; the written
   forms, `benchmark run`'s private packages, committable folders and carriage-return rule,
   and compare's ledger folder all read it, and none restates it.
5. **The case file** (US4, T093; `cases.md` 4.1 to 4.3, `scripted-answers.md` 2.1 and 6;
   QA-6, QA-7). An entry's `case_file` resolves as its `path` does. Its `case_file_sha256` is
   the digest of the file's raw bytes (`digest.sha256_of`), filled at load and absent when the
   file cannot be read; a set file never holds one (`load_set` refuses it), and
   `load_saved_set` takes it as saved. Row 4 refuses a package path under
   `benchmarks/case_files` through the guard's own message, and row 5 a package path that is
   or lies under a named case file's folder, and a case file inside any entry's package
   folder, naming both paths.

Every set file here is written into a temporary checkout, a folder standing for a
repository root, so no test depends on where this checkout lies. Rows 1, 2 and 4 to 7 and
the keyed-set tests are US5's (T114); row 1's `case_file_sha256`, `case_file_sha256` itself
and the case-file halves of rows 4 and 5 are US4's (T093).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from swreview import cli
from swreview.agent.checklist import load_checklist
from swreview.agent.settings import PRIVATE_PANE_STUDY
from swreview.benchmark import compare, digest, runner, sets
from swreview.benchmark.runner import preflight_set, run_benchmark
from swreview.benchmark.sets import (
    BenchmarkPackageRef,
    BenchmarkSet,
    SetError,
    load_saved_set,
    load_set,
)
from swreview.ir.loader import AnswerKeyAccessError

OUTSIDE_RULE = "a set file outside benchmarks/sets names every path absolutely"


def sets_folder(checkout: Path) -> Path:
    """The folder whose set files may name relative paths, under `checkout`."""
    return checkout / "benchmarks" / "sets"


def write_set(
    set_path: Path, packages: list[dict[str, object]], *, name: str = "parity"
) -> Path:
    """Write a set file at exactly `set_path` naming `packages`."""
    set_path.parent.mkdir(parents=True, exist_ok=True)
    set_path.write_text(json.dumps({"name": name, "packages": packages}), encoding="utf-8")
    return set_path


def relative_entry(package_id: str = "pkg-1", *, held_out: bool = True) -> dict[str, object]:
    return {
        "package_id": package_id,
        "path": f"benchmarks/packages/{package_id}",
        "held_out": held_out,
    }


def absolute_entry(package_id: str, folder: Path, *, held_out: bool = False) -> dict[str, object]:
    return {"package_id": package_id, "path": str(folder), "held_out": held_out}


def refusal(path: Path, *, root: Path) -> str:
    """The message `load_set` refuses `path` with, under `root`."""
    with pytest.raises(SetError) as refused:
        load_set(path, root=root)
    return str(refused.value)


CASE_FILE_BYTES = b'{"case_file_version": 1}\r\n'
"""A case file's bytes as a set reads them: digested, never parsed, so they need not make a
loadable case file, and the carriage return shows nothing normalises them."""

PRIVATE_CASE_BYTES = b'{"case_file_version": 1, "private": true}\n'


def write_case_file(path: Path, content: bytes = CASE_FILE_BYTES) -> Path:
    """Write `content` at exactly `path`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def committed_case_file(checkout: Path, package_id: str) -> Path:
    """A case file where the generator writes a committed one, `benchmarks/case_files/`."""
    return write_case_file(checkout / "benchmarks" / "case_files" / f"{package_id}.json")


def case_file_entry(entry: dict[str, object], case_file: Path | str) -> dict[str, object]:
    """`entry` naming `case_file`: a `Path` as its absolute spelling, a string as given."""
    return {**entry, "case_file": str(case_file)}


# --- the root decides resolution (row 3) ------------------------------------------


def test_set_error_is_a_value_error() -> None:
    """So the command line prints one line and exits 1 (`cli.py` HANDLED_ERRORS)."""
    assert issubclass(SetError, ValueError)


def test_a_relative_entry_in_the_roots_sets_folder_resolves_against_the_root(
    tmp_path: Path,
) -> None:
    checkout = tmp_path / "checkout"
    set_path = write_set(sets_folder(checkout) / "parity.json", [relative_entry("pkg-1")])

    benchmark_set = load_set(set_path, root=checkout)

    assert benchmark_set.name == "parity"
    [ref] = benchmark_set.packages
    assert ref.package_id == "pkg-1"
    assert ref.path == (checkout / "benchmarks" / "packages" / "pkg-1").resolve()
    assert ref.held_out is True


def test_the_root_is_resolved_before_it_is_compared(tmp_path: Path) -> None:
    """A root spelled with `..` is the same checkout, not a second one."""
    checkout = tmp_path / "checkout"
    set_path = write_set(sets_folder(checkout) / "parity.json", [relative_entry("pkg-1")])

    benchmark_set = load_set(set_path, root=checkout / "benchmarks" / "..")

    expected = (checkout / "benchmarks" / "packages" / "pkg-1").resolve()
    assert benchmark_set.packages[0].path == expected


@pytest.mark.parametrize(
    "location",
    [
        "private/parity.json",
        "checkout/parity.json",
        "checkout/benchmarks/parity.json",
        "checkout/benchmarks/sets/nested/parity.json",
    ],
    ids=["a private folder", "the root", "benchmarks", "a folder below benchmarks-sets"],
)
def test_a_relative_entry_in_a_set_file_outside_benchmarks_sets_is_refused_by_row_3(
    tmp_path: Path, location: str
) -> None:
    """Only `<root>/benchmarks/sets/` itself resolves relative entries: a set file
    anywhere else never resolves a path against its own location."""
    checkout = tmp_path / "checkout"
    set_path = write_set(tmp_path / location, [relative_entry("pkg-1")])

    message = refusal(set_path, root=checkout)

    assert message.startswith("benchmark set parity.json:")
    assert OUTSIDE_RULE in message
    assert "pkg-1" in message
    assert "benchmarks/packages/pkg-1" in message


def test_the_refusal_names_the_relative_entry_and_not_an_absolute_one(tmp_path: Path) -> None:
    checkout = tmp_path / "checkout"
    set_path = write_set(
        tmp_path / "private" / "mixed.json",
        [
            absolute_entry("absolute-one", tmp_path / "private" / "absolute-one"),
            relative_entry("relative-one"),
        ],
    )

    message = refusal(set_path, root=checkout)

    assert message.startswith("benchmark set mixed.json:")
    assert OUTSIDE_RULE in message
    assert "relative-one" in message
    assert "absolute-one" not in message


@pytest.mark.parametrize(
    "location",
    [
        "private/parity.json",
        "checkout/benchmarks/sets/parity.json",
        "second/benchmarks/sets/parity.json",
    ],
    ids=["a private folder", "the root's sets folder", "another checkout's sets folder"],
)
def test_absolute_entries_load_from_any_location(tmp_path: Path, location: str) -> None:
    checkout = tmp_path / "checkout"
    inside = checkout / "benchmarks" / "packages" / "pkg-1"
    private = tmp_path / "private" / "pkg-2"
    set_path = write_set(
        tmp_path / location,
        [absolute_entry("pkg-1", inside), absolute_entry("pkg-2", private)],
    )

    benchmark_set = load_set(set_path, root=checkout)

    assert [ref.path for ref in benchmark_set.packages] == [inside.resolve(), private.resolve()]


def test_a_set_file_in_a_second_worktree_is_refused_naming_both_roots(tmp_path: Path) -> None:
    first = (tmp_path / "first").resolve()
    second = (tmp_path / "second").resolve()
    set_path = write_set(sets_folder(second) / "parity.json", [relative_entry("pkg-1")])

    message = refusal(set_path, root=first)

    assert message == (
        f"benchmark set parity.json: {set_path.resolve()} belongs to the checkout at "
        f"{second}, and this code runs from {first}: run it from that checkout"
    )

    benchmark_set = load_set(set_path, root=second)

    assert benchmark_set.packages[0].path == second / "benchmarks" / "packages" / "pkg-1"
    in_second = json.loads(benchmark_set.saved_form(root=second))
    assert in_second["packages"][0]["path"] == "benchmarks/packages/pkg-1"
    # The saved form follows the root given, never the set file's location: under the
    # first root the same entry lies outside it, so it is private and written absolute.
    in_first = json.loads(benchmark_set.saved_form(root=first))
    assert in_first["packages"][0]["path"] == (
        second / "benchmarks" / "packages" / "pkg-1"
    ).as_posix()


# --- the saved copy -----------------------------------------------------------------


def test_load_saved_set_resolves_relative_entries_against_the_root_given(
    tmp_path: Path,
) -> None:
    checkout = tmp_path / "checkout"
    saved = write_set(tmp_path / "runs" / "run-1" / "benchmark-set.json", [relative_entry()])

    benchmark_set = load_saved_set(saved, root=checkout)

    [ref] = benchmark_set.packages
    assert ref.path == (checkout / "benchmarks" / "packages" / "pkg-1").resolve()
    grandparents = (saved.resolve().parents[2] / "benchmarks" / "packages" / "pkg-1").resolve()
    assert ref.path != grandparents
    # The same copy read as a set file is refused: the run folder is no sets folder.
    assert OUTSIDE_RULE in refusal(saved, root=checkout)


def test_load_saved_set_meets_the_answer_key_guard_through_the_same_core(
    tmp_path: Path,
) -> None:
    checkout = tmp_path / "checkout"
    saved = write_set(
        tmp_path / "runs" / "run-1" / "benchmark-set.json",
        [{"package_id": "leaky", "path": "benchmarks/answer_keys/leaky", "held_out": False}],
    )

    with pytest.raises(AnswerKeyAccessError):
        load_saved_set(saved, root=checkout)


def test_load_saved_set_reads_a_copy_saved_before_this_feature(tmp_path: Path) -> None:
    """At `be01974` `benchmark run` saved the loaded set with every path absolute
    (`cli.py:2313-2314`); such a run folder still reads, whatever the root."""
    checkout = tmp_path / "checkout"
    set_path = write_set(sets_folder(checkout) / "parity.json", [relative_entry("pkg-1")])
    loaded = load_set(set_path, root=checkout)
    saved = tmp_path / "runs" / "old" / "benchmark-set.json"
    saved.parent.mkdir(parents=True)
    saved.write_text(loaded.model_dump_json(indent=2) + "\n", encoding="utf-8")

    assert load_saved_set(saved, root=tmp_path / "another-checkout") == loaded


def test_a_saved_form_reads_back_as_the_set_it_came_from(tmp_path: Path) -> None:
    checkout = tmp_path / "checkout"
    private = tmp_path / "private" / "pkg-2"
    set_path = write_set(
        sets_folder(checkout) / "parity.json",
        [relative_entry("pkg-1"), absolute_entry("pkg-2", private)],
    )
    loaded = load_set(set_path, root=checkout)
    saved = tmp_path / "runs" / "run-1" / "benchmark-set.json"
    saved.parent.mkdir(parents=True)
    saved.write_bytes(loaded.saved_form(root=checkout))

    assert load_saved_set(saved, root=checkout) == loaded


# --- the two forms ------------------------------------------------------------------


def two_entry_set(tmp_path: Path, checkout: Path) -> tuple[BenchmarkSet, Path]:
    """A loaded set of one in-root entry and one private entry, and the private folder."""
    private = (tmp_path / "private" / "pkg-2").resolve()
    set_path = write_set(
        sets_folder(checkout) / "parity.json",
        [relative_entry("pkg-1", held_out=True), absolute_entry("pkg-2", private)],
    )
    return load_set(set_path, root=checkout), private


def test_saved_form_writes_in_root_paths_relative_and_private_ones_absolute(
    tmp_path: Path,
) -> None:
    checkout = tmp_path / "checkout"
    benchmark_set, private = two_entry_set(tmp_path, checkout)

    form = benchmark_set.saved_form(root=checkout)

    assert form == (
        "{\n"
        '  "name": "parity",\n'
        '  "packages": [\n'
        "    {\n"
        '      "package_id": "pkg-1",\n'
        '      "path": "benchmarks/packages/pkg-1",\n'
        '      "held_out": true\n'
        "    },\n"
        "    {\n"
        '      "package_id": "pkg-2",\n'
        f'      "path": {json.dumps(private.as_posix())},\n'
        '      "held_out": false\n'
        "    }\n"
        "  ]\n"
        "}\n"
    ).encode()
    assert b"null" not in form  # absent optional fields are omitted, never written as null


def test_the_forms_are_utf8_json_with_lf_line_endings_and_one_final_newline(
    tmp_path: Path,
) -> None:
    checkout = tmp_path / "checkout"
    set_path = write_set(
        sets_folder(checkout) / "étude.json", [relative_entry("pkg-1")], name="étude"
    )
    benchmark_set = load_set(set_path, root=checkout)

    for form in (benchmark_set.saved_form(root=checkout), benchmark_set.file_form(root=checkout)):
        assert json.loads(form.decode("utf-8"))["name"] == "étude"
        assert '"name": "étude"'.encode() in form
        assert b"\r" not in form
        assert form.endswith(b"}\n")
        assert not form.endswith(b"\n\n")


def test_two_copies_of_one_tree_at_two_locations_give_byte_equal_saved_forms(
    tmp_path: Path,
) -> None:
    """FR-051: the saved bytes, and so `set_digest`, ignore where the checkout lies."""
    private = (tmp_path / "private" / "pkg-3").resolve()
    copies = [tmp_path / "a" / "checkout", tmp_path / "b" / "deeper" / "checkout"]
    forms = []
    for checkout in copies:
        set_path = write_set(
            sets_folder(checkout) / "parity.json",
            [
                relative_entry("pkg-1"),
                relative_entry("pkg-2", held_out=False),
                absolute_entry("pkg-3", private),
            ],
        )
        forms.append(load_set(set_path, root=checkout).saved_form(root=checkout))

    assert forms[0] == forms[1]
    for checkout in copies:
        assert checkout.resolve().as_posix().encode() not in forms[0]


def test_saved_form_is_the_file_form_plus_each_entry_s_case_file_sha256(tmp_path: Path) -> None:
    """RF-54: the same paths through the same entry serializer, and never a
    `case_file_sha256` in a set file. US4 added each entry's digest to the saved form only
    (T093), which turned this test's equality ("one serializer until US4") into "plus each
    entry's digest": a set naming no case file still gives byte-equal forms."""
    checkout = tmp_path / "checkout"
    benchmark_set, _ = two_entry_set(tmp_path, checkout)

    form = benchmark_set.file_form(root=checkout)

    assert form == benchmark_set.saved_form(root=checkout)
    assert b"case_file_sha256" not in form
    assert b"\r" not in form
    assert b"\\" not in form  # `/` separators on every platform, private paths included

    committed_case_file(checkout, "pkg-1")
    private_case = write_case_file(
        tmp_path / "vault" / "keys" / "pkg-2.case.json", PRIVATE_CASE_BYTES
    )
    set_path = write_set(
        sets_folder(checkout) / "cases.json",
        [
            case_file_entry(relative_entry("pkg-1"), "benchmarks/case_files/pkg-1.json"),
            case_file_entry(
                absolute_entry("pkg-2", tmp_path / "vault" / "packages" / "pkg-2"), private_case
            ),
            relative_entry("pkg-3", held_out=False),
        ],
    )
    with_cases = load_set(set_path, root=checkout)

    file_form = with_cases.file_form(root=checkout)
    saved_form = with_cases.saved_form(root=checkout)

    assert b"case_file_sha256" not in file_form
    for written in (file_form, saved_form):
        assert b"\r" not in written
        assert b"\\" not in written
    filed, saved = json.loads(file_form), json.loads(saved_form)
    digests = {
        "pkg-1": hashlib.sha256(CASE_FILE_BYTES).hexdigest(),
        "pkg-2": hashlib.sha256(PRIVATE_CASE_BYTES).hexdigest(),
    }
    assert saved["name"] == filed["name"] == "parity"
    assert saved["packages"] == [
        {**entry, "case_file_sha256": digests[entry["package_id"]]}
        if entry["package_id"] in digests
        else entry
        for entry in filed["packages"]
    ]
    assert [entry.get("case_file") for entry in filed["packages"]] == [
        "benchmarks/case_files/pkg-1.json",
        private_case.resolve().as_posix(),
        None,
    ]


def test_a_file_form_written_into_the_sets_folder_loads_as_the_same_set(
    tmp_path: Path,
) -> None:
    """The generator writes committed set files through `file_form` (T126)."""
    checkout = tmp_path / "checkout"
    benchmark_set, _ = two_entry_set(tmp_path, checkout)
    rewritten = sets_folder(checkout) / "rewritten.json"
    rewritten.write_bytes(benchmark_set.file_form(root=checkout))

    assert load_set(rewritten, root=checkout) == benchmark_set


# --- one inside-the-checkout rule ------------------------------------------------------


def test_checkout_relative_is_a_path_inside_the_root_relative_to_it(tmp_path: Path) -> None:
    """Both resolved, then the path relative to the root when it lies inside it, the root itself
    and a folder not made yet included, else `None`: a `..` that climbs out lies outside, as a
    lexical reading would not see, and so does a neighbour whose name only begins with the
    root's."""
    root = tmp_path / "checkout"
    inside = root / "benchmarks" / "packages" / "pkg-1"
    inside.mkdir(parents=True)

    assert sets.checkout_relative(inside, root=root) == Path("benchmarks", "packages", "pkg-1")
    assert sets.checkout_relative(str(inside), root=root / "benchmarks" / "..") == Path(
        "benchmarks", "packages", "pkg-1"
    )
    assert sets.checkout_relative(root, root=root) == Path(".")
    assert sets.checkout_relative(root / "runs" / "new", root=root) == Path("runs", "new")
    assert sets.checkout_relative(tmp_path / "private" / "pkg-2", root=root) is None
    assert sets.checkout_relative(root / "benchmarks" / ".." / ".." / "pkg-2", root=root) is None
    assert sets.checkout_relative(tmp_path / "checkout-copy" / "pkg-1", root=root) is None


def test_every_inside_the_checkout_reading_goes_through_checkout_relative(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The rule is written once: the written forms, `benchmark run`'s private packages (row 5
    and the pane study's set rule), its committable folders (row 5 and compare's ledger guard)
    and its carriage-return rule, and compare's ledger folder each read it through
    `checkout_relative`, a spy patched where each caller looks the name up seeing every path."""
    root = (tmp_path / "checkout").resolve()
    inside = root / "benchmarks" / "packages" / "pkg-1"
    outside = (tmp_path / "private" / "pkg-2").resolve()
    for folder in (inside, outside):
        folder.mkdir(parents=True)
    prompt = root / "prompt.md"
    prompt.write_bytes(b"one line\n")
    private_profile = outside.parent / "profile.yaml"
    private_profile.write_bytes(b"never read for its line endings\r\n")
    benchmark_set = BenchmarkSet(
        name="parity",
        packages=[
            BenchmarkPackageRef(package_id="pkg-1", path=inside),
            BenchmarkPackageRef(package_id="pkg-2", path=outside),
        ],
    )
    seen: list[Path] = []
    real = sets.checkout_relative

    def spy(path: Path | str, *, root: Path) -> Path | None:
        seen.append(Path(path))
        return real(path, root=root)

    monkeypatch.setattr(sets, "checkout_relative", spy)
    monkeypatch.setattr(runner, "checkout_relative", spy)

    def carriage_returns() -> None:
        cli._refuse_a_pane_study_breaking_its_file_rules(
            PRIVATE_PANE_STUDY,
            standards_profile=private_profile,
            is_example=False,
            benchmark_set=benchmark_set,
            commit="abc1234",
            dirty=False,
            digested=(prompt, None, private_profile),
            root=root,
        )

    readings = {
        "file form": (lambda: benchmark_set.file_form(root=root), [inside, outside]),
        "saved form": (lambda: benchmark_set.saved_form(root=root), [inside, outside]),
        "private packages": (
            lambda: cli._private_packages(benchmark_set, root=root),
            [inside, outside],
        ),
        "committable": (lambda: runner.committable(outside, root=root), [outside]),
        "ledger folder": (lambda: compare._ledger_dir(outside, root=root), [outside]),
        "carriage returns": (carriage_returns, [prompt, private_profile]),
    }
    for name, (reading, expected) in readings.items():
        seen.clear()
        reading()
        assert seen == expected, name


# --- the running checkout ------------------------------------------------------------


def test_repo_root_is_the_repository_root_and_the_runner_imports_it_back() -> None:
    assert sets.REPO_ROOT == Path(__file__).resolve().parents[3]
    assert (sets.REPO_ROOT / "benchmarks" / "sets" / "pilot.json").is_file()
    assert runner.REPO_ROOT is sets.REPO_ROOT


def test_the_committed_pilot_set_loads_unchanged_from_the_default_root() -> None:
    pilot = sets.REPO_ROOT / "benchmarks" / "sets" / "pilot.json"

    benchmark_set = load_set(pilot)

    assert benchmark_set.packages
    for ref in benchmark_set.packages:
        assert ref.path == sets.REPO_ROOT / "benchmarks" / "packages" / ref.package_id
    saved = json.loads(benchmark_set.saved_form())
    assert [entry["path"] for entry in saved["packages"]] == [
        f"benchmarks/packages/{ref.package_id}" for ref in benchmark_set.packages
    ]


# --- the runner forwards the root (RF-61) ---------------------------------------------


def test_run_benchmark_resolves_a_relative_entry_against_the_root_given(tmp_path: Path) -> None:
    package_dir = tmp_path / "benchmarks" / "packages" / "pkg-1"
    package_dir.mkdir(parents=True)
    set_path = write_set(sets_folder(tmp_path) / "parity.json", [relative_entry("pkg-1")])
    calls: list[Path] = []

    run_benchmark(
        preflight_set(set_path, None, load_checklist(), root=tmp_path),
        tmp_path / "out",
        provider="fake",
        model="m",
        effort="low",
        review_fn=lambda package_path, *_, **__: calls.append(package_path),
    )

    assert calls == [package_dir.resolve()]


def test_run_benchmark_without_a_root_reads_the_set_against_the_running_checkout(
    tmp_path: Path,
) -> None:
    """The default root is `REPO_ROOT`, so a temporary checkout's set is another
    checkout's and is refused before any review. Since feature 014 T097 the set is read by
    `preflight_set`, whose default root it is (RF-61)."""
    set_path = write_set(sets_folder(tmp_path) / "parity.json", [relative_entry("pkg-1")])
    calls: list[object] = []

    with pytest.raises(SetError):
        run_benchmark(
            preflight_set(set_path, None, load_checklist()),
            tmp_path / "out",
            provider="fake",
            model="m",
            effort="low",
            review_fn=lambda *args, **kwargs: calls.append((args, kwargs)),
        )

    assert calls == []
    assert not (tmp_path / "out" / "pkg-1").exists()


def test_benchmark_run_prints_row_3_on_one_line_and_exits_1(tmp_path: Path) -> None:
    set_path = write_set(tmp_path / "private" / "parity.json", [relative_entry("pkg-1")])
    out = tmp_path / "out"

    result = CliRunner().invoke(
        cli.app,
        ["benchmark", "run", "--set", str(set_path), "--out", str(out), "--provider", "fake"],
    )

    assert result.exit_code == 1
    assert result.stderr.startswith(f"error: SetError: benchmark set parity.json: {OUTSIDE_RULE}")
    assert result.stderr.strip().count("\n") == 0
    assert not (out / "pkg-1").exists()


# --- the case file resolves as the path does (US4, T093) --------------------------------------


def committed_case_set(checkout: Path) -> tuple[Path, Path]:
    """A set file in `checkout`'s sets folder whose one entry, `pkg-1`, names its committed
    case file, and that case file."""
    case_file = committed_case_file(checkout, "pkg-1")
    set_path = write_set(
        sets_folder(checkout) / "parity.json",
        [case_file_entry(relative_entry("pkg-1"), "benchmarks/case_files/pkg-1.json")],
    )
    return set_path, case_file


def test_a_relative_case_file_in_the_roots_sets_folder_resolves_against_the_root(
    tmp_path: Path,
) -> None:
    """`scripted-answers.md` 2.1: a committed case file is named repository-relative."""
    checkout = tmp_path / "checkout"
    set_path, case_file = committed_case_set(checkout)

    [ref] = load_set(set_path, root=checkout).packages

    assert ref.case_file == case_file.resolve()


def test_an_absolute_case_file_of_a_private_entry_loads_and_is_written_absolute(
    tmp_path: Path,
) -> None:
    """A private case file lies outside the root, named absolutely in a set file outside the
    repository, and both forms write it absolute with `/` (`scripted-answers.md` 2.1)."""
    checkout = tmp_path / "checkout"
    vault = tmp_path / "vault"
    case_file = write_case_file(vault / "keys" / "pkg-2.case.json")
    set_path = write_set(
        vault / "private.json",
        [case_file_entry(absolute_entry("pkg-2", vault / "packages" / "pkg-2"), case_file)],
    )

    benchmark_set = load_set(set_path, root=checkout)

    assert benchmark_set.packages[0].case_file == case_file.resolve()
    for form in (benchmark_set.file_form(root=checkout), benchmark_set.saved_form(root=checkout)):
        assert json.loads(form)["packages"][0]["case_file"] == case_file.resolve().as_posix()


@pytest.mark.parametrize(
    "location",
    ["private/parity.json", "checkout/benchmarks/parity.json"],
    ids=["a private folder", "benchmarks"],
)
def test_a_relative_case_file_in_a_set_file_outside_benchmarks_sets_is_refused_by_row_3(
    tmp_path: Path, location: str
) -> None:
    """Row 3 reads every path an entry names: an absolute package path does not carry a
    relative case file through."""
    checkout = tmp_path / "checkout"
    set_path = write_set(
        tmp_path / location,
        [
            case_file_entry(
                absolute_entry("pkg-1", tmp_path / "private" / "pkg-1"), "case_files/pkg-1.json"
            )
        ],
    )

    message = refusal(set_path, root=checkout)

    assert message == (
        f"benchmark set parity.json: {OUTSIDE_RULE}, and entry pkg-1 names the relative path "
        "case_files/pkg-1.json"
    )


def test_a_relative_case_file_in_a_second_worktree_is_refused_naming_both_roots(
    tmp_path: Path,
) -> None:
    first = (tmp_path / "first").resolve()
    second = (tmp_path / "second").resolve()
    set_path = write_set(
        sets_folder(second) / "parity.json",
        [
            case_file_entry(
                absolute_entry("pkg-1", second / "benchmarks" / "packages" / "pkg-1"),
                "benchmarks/case_files/pkg-1.json",
            )
        ],
    )

    message = refusal(set_path, root=first)

    assert message == (
        f"benchmark set parity.json: {set_path.resolve()} belongs to the checkout at "
        f"{second}, and this code runs from {first}: run it from that checkout"
    )


# --- case_file_sha256 (US4, T093; QA-7) -------------------------------------------------------


def test_case_file_sha256_is_filled_at_load_from_the_case_file_s_raw_bytes(
    tmp_path: Path,
) -> None:
    """Through the one raw-bytes digest (RF-48): the carriage return is digested as it lies,
    and one changed byte changes the digest, so the saved set and `set_digest` (QA-7)."""
    checkout = tmp_path / "checkout"
    set_path, case_file = committed_case_set(checkout)

    [ref] = load_set(set_path, root=checkout).packages

    assert ref.case_file_sha256 == hashlib.sha256(CASE_FILE_BYTES).hexdigest()
    assert sets.sha256_of is digest.sha256_of

    changed_bytes = CASE_FILE_BYTES.replace(b"1", b"2")
    case_file.write_bytes(changed_bytes)
    [changed] = load_set(set_path, root=checkout).packages

    assert changed.case_file_sha256 == hashlib.sha256(changed_bytes).hexdigest()
    assert changed.case_file_sha256 != ref.case_file_sha256


def test_an_entry_with_no_case_file_carries_no_case_file_and_no_digest(tmp_path: Path) -> None:
    """Nothing is looked up by convention (`scripted-answers.md` 2.1): a case file lying where
    the generator would write `pkg-2`'s is not that entry's, and neither form names one."""
    checkout = tmp_path / "checkout"
    committed_case_file(checkout, "pkg-1")
    committed_case_file(checkout, "pkg-2")
    set_path = write_set(
        sets_folder(checkout) / "parity.json",
        [
            case_file_entry(relative_entry("pkg-1"), "benchmarks/case_files/pkg-1.json"),
            relative_entry("pkg-2"),
        ],
    )

    benchmark_set = load_set(set_path, root=checkout)

    named, unnamed = benchmark_set.packages
    assert named.case_file_sha256 == hashlib.sha256(CASE_FILE_BYTES).hexdigest()
    assert unnamed.case_file is None
    assert unnamed.case_file_sha256 is None
    for form in (benchmark_set.file_form(root=checkout), benchmark_set.saved_form(root=checkout)):
        assert json.loads(form)["packages"][1] == {
            "package_id": "pkg-2",
            "path": "benchmarks/packages/pkg-2",
            "held_out": True,
        }


@pytest.mark.parametrize("kind", ["missing", "a folder"])
def test_a_case_file_that_cannot_be_read_loads_with_no_digest(tmp_path: Path, kind: str) -> None:
    """The set loader leaves the digest absent and refuses nothing: `preflight_set` refuses
    the entry by `scripted-answers.md` 2.3 row 1, naming the file (T097)."""
    checkout = tmp_path / "checkout"
    case_file = checkout / "benchmarks" / "case_files" / "pkg-1.json"
    if kind == "a folder":
        case_file.mkdir(parents=True)
    set_path = write_set(
        sets_folder(checkout) / "parity.json",
        [case_file_entry(relative_entry("pkg-1"), "benchmarks/case_files/pkg-1.json")],
    )

    benchmark_set = load_set(set_path, root=checkout)

    [ref] = benchmark_set.packages
    assert ref.case_file == case_file.resolve()
    assert ref.case_file_sha256 is None
    saved = json.loads(benchmark_set.saved_form(root=checkout))["packages"][0]
    assert saved["case_file"] == "benchmarks/case_files/pkg-1.json"
    assert "case_file_sha256" not in saved


@pytest.mark.parametrize(
    "names_a_case_file", [True, False], ids=["beside its case file", "alone"]
)
def test_load_set_refuses_a_set_file_holding_case_file_sha256_naming_the_field(
    tmp_path: Path, names_a_case_file: bool
) -> None:
    """`cases.md` 4.1: computed at load and carried into the saved set, never written in a
    set file (row 1's `case_file_sha256`; the rest of row 1 is US5's)."""
    checkout = tmp_path / "checkout"
    entry = relative_entry("pkg-1")
    if names_a_case_file:
        committed_case_file(checkout, "pkg-1")
        entry = case_file_entry(entry, "benchmarks/case_files/pkg-1.json")
    set_path = write_set(
        sets_folder(checkout) / "parity.json",
        [relative_entry("pkg-0"), {**entry, "case_file_sha256": "0" * 64}],
    )

    message = refusal(set_path, root=checkout)

    assert message.startswith("benchmark set parity.json:")
    assert "case_file_sha256" in message
    assert "pkg-1" in message
    assert "pkg-0" not in message


def test_row_1_s_case_file_sha256_comes_before_row_3(tmp_path: Path) -> None:
    """4.3's order: a set file outside `benchmarks/sets` naming a relative path and holding a
    digest is named by row 1."""
    checkout = tmp_path / "checkout"
    set_path = write_set(
        tmp_path / "private" / "parity.json",
        [{**relative_entry("pkg-1"), "case_file_sha256": "0" * 64}],
    )

    message = refusal(set_path, root=checkout)

    assert "case_file_sha256" in message
    assert OUTSIDE_RULE not in message


def test_load_saved_set_takes_each_case_file_sha256_as_saved(tmp_path: Path) -> None:
    """`cases.md` 4.2: a saved copy records the bytes the run read, so its digest reads back
    as saved, never recomputed from a case file changed since, and an entry the copy holds
    with no digest reads with none (`provenance.md` 6.1; QA-7)."""
    checkout = tmp_path / "checkout"
    set_path, case_file = committed_case_set(checkout)
    loaded = load_set(set_path, root=checkout)
    saved = tmp_path / "runs" / "run-1" / "benchmark-set.json"
    saved.parent.mkdir(parents=True)
    saved.write_bytes(loaded.saved_form(root=checkout))
    case_file.write_bytes(b"changed after the run\n")

    reread = load_saved_set(saved, root=checkout)

    assert reread == loaded
    assert reread.packages[0].case_file_sha256 == hashlib.sha256(CASE_FILE_BYTES).hexdigest()

    without_digest = json.loads(saved.read_bytes())
    del without_digest["packages"][0]["case_file_sha256"]
    saved.write_text(json.dumps(without_digest), encoding="utf-8")

    assert load_saved_set(saved, root=checkout).packages[0].case_file_sha256 is None


def test_both_forms_write_the_case_file_as_the_path_and_only_the_saved_form_its_digest(
    tmp_path: Path,
) -> None:
    """The entry serializer's exact bytes: `case_file` beside `path`, root-relative with `/`,
    and the saved form the file form plus one `case_file_sha256` line, the entry's last."""
    checkout = tmp_path / "checkout"
    set_path, _ = committed_case_set(checkout)
    benchmark_set = load_set(set_path, root=checkout)
    head = (
        "{\n"
        '  "name": "parity",\n'
        '  "packages": [\n'
        "    {\n"
        '      "package_id": "pkg-1",\n'
        '      "path": "benchmarks/packages/pkg-1",\n'
        '      "case_file": "benchmarks/case_files/pkg-1.json",\n'
        '      "held_out": true'
    )
    tail = "\n    }\n  ]\n}\n"
    sha = hashlib.sha256(CASE_FILE_BYTES).hexdigest()

    assert benchmark_set.file_form(root=checkout) == (head + tail).encode()
    assert benchmark_set.saved_form(root=checkout) == (
        head + f',\n      "case_file_sha256": "{sha}"' + tail
    ).encode()


def test_a_file_form_naming_case_files_loads_as_the_same_set(tmp_path: Path) -> None:
    """The generator's path (T126): a set file it writes through `file_form` holds no digest,
    and loading it computes each again from the same bytes."""
    checkout = tmp_path / "checkout"
    set_path, _ = committed_case_set(checkout)
    benchmark_set = load_set(set_path, root=checkout)
    rewritten = sets_folder(checkout) / "rewritten.json"
    rewritten.write_bytes(benchmark_set.file_form(root=checkout))

    assert load_set(rewritten, root=checkout) == benchmark_set


def test_two_copies_of_one_tree_naming_case_files_give_byte_equal_saved_forms(
    tmp_path: Path,
) -> None:
    """`scripted-answers.md` 6: a committed set names its case files relatively, so the saved
    bytes and `set_digest` are the same from any checkout (FR-051)."""
    copies = [tmp_path / "a" / "checkout", tmp_path / "b" / "deeper" / "checkout"]
    forms = []
    for checkout in copies:
        set_path, _ = committed_case_set(checkout)
        forms.append(load_set(set_path, root=checkout).saved_form(root=checkout))

    assert forms[0] == forms[1]
    assert b"case_file_sha256" in forms[0]
    for checkout in copies:
        assert checkout.resolve().as_posix().encode() not in forms[0]


# --- rows 4 and 5, the case-file halves (US4, T093; US4-9) -----------------------------------

ROW_5 = "the reviewer reads the package folder; keep keys and case files outside it"


@pytest.mark.parametrize(
    "package_path",
    [
        "benchmarks/case_files",
        "benchmarks/case_files/pkg-1",
        "benchmarks/case_files/nested/pkg-1",
        "Benchmarks/Case_Files/pkg-1",
    ],
    ids=["the folder", "a package in it", "a package below it", "spelled in capitals"],
)
def test_a_package_path_under_benchmarks_case_files_is_refused_by_the_guard(
    tmp_path: Path, package_path: str
) -> None:
    """Row 4: the guard's segments gain `benchmarks/case_files` (`ir/loader.py`), so its own
    `AnswerKeyAccessError` names the segment it met, with no code in `sets.py`."""
    checkout = tmp_path / "checkout"
    set_path = write_set(
        sets_folder(checkout) / "parity.json",
        [{"package_id": "pkg-1", "path": package_path, "held_out": False}],
    )

    with pytest.raises(AnswerKeyAccessError) as refused:
        load_set(set_path, root=checkout)

    message = str(refused.value)
    resolved = (checkout / package_path).resolve()
    assert message.startswith(f"{resolved} is inside benchmarks/case_files; "), message
    assert "answer_keys" not in message


@pytest.mark.parametrize(
    ("package", "case_file"),
    [
        ("vault/pkg-1", "vault/pkg-1/pkg-1.case.json"),
        ("vault/keys/pkg-1", "vault/keys/pkg-1.case.json"),
        ("vault/keys/deeper/pkg-1", "vault/keys/pkg-1.case.json"),
        ("vault/pkg-1", "vault/pkg-1/answers/pkg-1.case.json"),
    ],
    ids=[
        "the package folder is the case file's folder",
        "the package folder lies in the case file's folder",
        "the package folder lies below the case file's folder",
        "the case file lies below the package folder",
    ],
)
def test_row_5_refuses_a_package_folder_at_or_under_its_case_file_s_folder_and_the_reverse(
    tmp_path: Path, package: str, case_file: str
) -> None:
    """A private case file cannot sit in, or contain, a folder the reviewer loads
    (`scripted-answers.md` 6; D7)."""
    checkout = tmp_path / "checkout"
    package_dir = tmp_path / package
    case_path = write_case_file(tmp_path / case_file)
    set_path = write_set(
        tmp_path / "vault" / "private.json",
        [case_file_entry(absolute_entry("pkg-1", package_dir), case_path)],
    )

    message = refusal(set_path, root=checkout)

    assert message.startswith("benchmark set private.json: entry pkg-1"), message
    assert message.endswith(f": {ROW_5}"), message
    assert str(package_dir.resolve()) in message
    assert str(case_path.resolve()) in message


def test_row_5_reads_every_entry_against_every_case_file(tmp_path: Path) -> None:
    """One entry's package folder in another's case-file folder, and one entry's case file
    below another's package folder, are refused alike, naming both entries and both paths."""
    checkout = tmp_path / "checkout"
    vault = tmp_path / "vault"
    package_1 = vault / "packages" / "pkg-1"
    case_1 = write_case_file(vault / "keys" / "pkg-1.case.json")
    in_keys = vault / "keys" / "pkg-2"
    package_in_folder = write_set(
        vault / "package-in-folder.json",
        [
            case_file_entry(absolute_entry("pkg-1", package_1), case_1),
            absolute_entry("pkg-2", in_keys),
        ],
    )

    message = refusal(package_in_folder, root=checkout)

    assert "pkg-1" in message and "pkg-2" in message
    assert str(in_keys.resolve()) in message and str(case_1.resolve()) in message
    assert message.endswith(f": {ROW_5}")

    case_3 = write_case_file(package_1 / "answers" / "pkg-3.case.json")
    case_in_package = write_set(
        vault / "case-in-package.json",
        [
            absolute_entry("pkg-1", package_1),
            case_file_entry(absolute_entry("pkg-3", vault / "packages" / "pkg-3"), case_3),
        ],
    )

    message = refusal(case_in_package, root=checkout)

    assert "pkg-1" in message and "pkg-3" in message
    assert str(package_1.resolve()) in message and str(case_3.resolve()) in message
    assert message.endswith(f": {ROW_5}")


def test_row_5_lets_a_neighbour_whose_name_only_begins_with_the_folder_s_load(
    tmp_path: Path,
) -> None:
    """Folders compare by path, not by spelling: `keys-packages` does not lie in `keys`, and
    a case file in `pkg-2-answers` is not in `pkg-2`."""
    checkout = tmp_path / "checkout"
    vault = tmp_path / "vault"
    case_1 = write_case_file(vault / "keys" / "pkg-1.case.json")
    case_2 = write_case_file(vault / "pkg-2-answers" / "pkg-2.case.json")
    set_path = write_set(
        vault / "private.json",
        [
            case_file_entry(absolute_entry("pkg-1", vault / "keys-packages" / "pkg-1"), case_1),
            case_file_entry(absolute_entry("pkg-2", vault / "pkg-2"), case_2),
        ],
    )

    benchmark_set = load_set(set_path, root=checkout)

    assert [ref.case_file for ref in benchmark_set.packages] == [
        case_1.resolve(),
        case_2.resolve(),
    ]


def test_row_4_comes_before_row_5(tmp_path: Path) -> None:
    """4.3's order: a package under `benchmarks/case_files` holding its own case file meets
    the guard, not row 5."""
    checkout = tmp_path / "checkout"
    write_case_file(checkout / "benchmarks" / "case_files" / "pkg-1" / "pkg-1.json")
    set_path = write_set(
        sets_folder(checkout) / "parity.json",
        [
            case_file_entry(
                {"package_id": "pkg-1", "path": "benchmarks/case_files/pkg-1", "held_out": False},
                "benchmarks/case_files/pkg-1/pkg-1.json",
            )
        ],
    )

    with pytest.raises(AnswerKeyAccessError):
        load_set(set_path, root=checkout)


def test_load_saved_set_meets_row_5_through_the_same_core(tmp_path: Path) -> None:
    checkout = tmp_path / "checkout"
    saved = write_set(
        tmp_path / "runs" / "run-1" / "benchmark-set.json",
        [
            {
                **relative_entry("pkg-1"),
                "case_file": "benchmarks/packages/pkg-1/pkg-1.case.json",
                "case_file_sha256": "0" * 64,
            }
        ],
    )

    with pytest.raises(SetError) as refused:
        load_saved_set(saved, root=checkout)

    assert str(refused.value).endswith(f": {ROW_5}")
