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
3. **Two forms, one entry serializer.** `file_form` and `saved_form` write in-root paths
   root-relative with `/` and private ones absolute, as UTF-8 JSON, indent 2, LF, with a
   final newline, so two copies of one tree at two locations give the same bytes. They are
   equal until US4 adds each entry's `case_file_sha256` to the saved form (T093), which
   moves `test_file_form_and_saved_form_are_one_serializer_until_us4` deliberately.
4. **One inside-the-checkout rule.** `checkout_relative(path, *, root)` resolves both and
   gives the path relative to the root when it lies inside it, else `None`; the written
   forms, `benchmark run`'s private packages, committable folders and carriage-return rule,
   and compare's ledger folder all read it, and none restates it.

Every set file here is written into a temporary checkout, a folder standing for a
repository root, so no test depends on where this checkout lies. Rows 1, 2 and 4 to 7 and
the keyed-set tests are US5's (T114); `case_file_sha256` and the case-file halves of rows 4
and 5 are US4's (T093).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from swreview import cli
from swreview.agent.settings import PRIVATE_PANE_STUDY
from swreview.benchmark import compare, runner, sets
from swreview.benchmark.runner import run_benchmark
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


def test_file_form_and_saved_form_are_one_serializer_until_us4(tmp_path: Path) -> None:
    """RF-54: the same paths through the same entry serializer, and never a
    `case_file_sha256` in a set file. US4 adds each entry's digest to the saved form only
    (T093), which turns the equality here into "plus each entry's digest"."""
    checkout = tmp_path / "checkout"
    benchmark_set, _ = two_entry_set(tmp_path, checkout)

    form = benchmark_set.file_form(root=checkout)

    assert form == benchmark_set.saved_form(root=checkout)
    assert b"case_file_sha256" not in form
    assert b"\r" not in form
    assert b"\\" not in form  # `/` separators on every platform, private paths included


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
        set_path,
        tmp_path / "out",
        provider="fake",
        model="m",
        effort="low",
        review_fn=lambda package_path, *_, **__: calls.append(package_path),
        root=tmp_path,
    )

    assert calls == [package_dir.resolve()]


def test_run_benchmark_without_a_root_reads_the_set_against_the_running_checkout(
    tmp_path: Path,
) -> None:
    """The default root is `REPO_ROOT`, so a temporary checkout's set is another
    checkout's and is refused before any review."""
    set_path = write_set(sets_folder(tmp_path) / "parity.json", [relative_entry("pkg-1")])
    calls: list[object] = []

    with pytest.raises(SetError):
        run_benchmark(
            set_path,
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
