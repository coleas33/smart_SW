"""A run folder the repository could commit holds no private data (T053, for T054).

`specs/014-design-review-eval/contracts/provenance.md` 6.4 and `benchmark-run.md` 3 row 5 (PROV-09;
FR-051). A folder is **committable** when it lies inside the checkout root and `git check-ignore`
does not report it ignored; inside the root, a folder git cannot answer for counts as committable.
`benchmark run` refuses, before any review, a committable `--out` for a run whose set names a
package outside the root or whose profile is not the fictional example; an `--out` outside the
root, or an ignored one inside it, takes either.

The runs are `test_benchmark_run_pane_study.py`'s: a scripted `benchmark run --provider fake` over
a temporary git repository, the command pointed at it through `swreview.benchmark.sets.REPO_ROOT`,
a spy standing in for every review.

The committable-folder scanner, `tests/support/local_paths.py` (T055, for T056; `provenance.md`
6.6; PROV-14, RF-6, RF-84): it flags the checkout, home and temporary folders in any spelling, a
drive-letter, UNC or rooted path outside the named fictional roots, and a saved set naming a path
outside the repository, reading JSON as strings and a packed stream by its decompressed text; and
it finds nothing in section 6.6's reach of this checkout, nor in what an offline run over a
committed-style package, its score and its ledger write (T067, for T068; US2-11).

The packed event streams' git rules (T057, for T058; `provenance.md` 6.6; 28A, RF-84): a packed
stream is committable only in the study and pilot trees, a plain one nowhere but the replay
fixtures, and git reads every packed one as binary.
"""

from __future__ import annotations

import gzip
import json
import shutil
import subprocess
import tempfile
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

import pytest
import yaml

from swreview.benchmark import runner
from swreview.benchmark.compare import LEDGER_BEGIN, LEDGER_END
from swreview.benchmark.sets import REPO_ROOT, BenchmarkPackageRef, BenchmarkSet
from tests.checks.golden_standards import PROFILE_DIR
from tests.support import local_paths, mechanical, scramble
from tests.support.answer_keys import write_key
from tests.unit.test_benchmark_run_options import benchmark_run, invoke
from tests.unit.test_benchmark_run_pane_study import (
    IGNORED,
    PACKAGE,
    another_profile,
    checkout,
    point_at,
    private_package,
    refused,
    watch_reviews,
)
from tests.unit.test_benchmark_sets import relative_entry, sets_folder, write_set
from tests.unit.test_line_endings import attributes
from tests.unit.test_run_provenance import git


def committable_refusal(out: Path, what: str) -> str:
    """Row 5's message for `out`, the run's private data named by `what`."""
    return (
        f"{out} is inside the repository, where it may be committed; this run {what}: "
        "write it outside the repository"
    )


PRIVATE_PACKAGE = "names private package pkg-2"
ANOTHER_PROFILE = "grades against a profile other than the fictional example"


def no_git(*_args: Any, **_kwargs: Any) -> Any:
    """Stands in for `subprocess.run` where git is not on the path: git cannot answer."""
    raise OSError("git is not on the path")


def test_a_committable_run_folder_is_refused_for_a_private_package_or_another_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A study needs no declaring here: any run's folder inside the repository may be committed,
    so a private package or another profile is refused there, and taken anywhere git ignores or
    outside the checkout."""
    private = private_package(tmp_path / "private" / "pkg-2")
    root = tmp_path / "checkout"
    with_private = checkout(root, private=(private,))
    committed_only = write_set(sets_folder(root) / "committed.json", [relative_entry()])
    point_at(root, monkeypatch)
    reviewed = watch_reviews(monkeypatch)
    profile = another_profile(tmp_path / "profiles")
    inside = root / "runs" / "committable"

    for set_file, options, what in (
        (with_private, (), PRIVATE_PACKAGE),
        (committed_only, ("--standards-profile", str(profile)), ANOTHER_PROFILE),
        (with_private, ("--standards-profile", str(profile)), PRIVATE_PACKAGE),
    ):
        line = refused(benchmark_run(set_file, inside, *options), inside, reviewed)
        assert line.endswith(committable_refusal(inside, what)), line

    # Inside a root git cannot answer for, the folder counts as committable.
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    unanswered = tmp_path / "no-repository"
    unanswered_set = checkout(unanswered, private=(private,), repository=False)
    point_at(unanswered, monkeypatch)
    unanswered_out = unanswered / IGNORED / "run"
    line = refused(benchmark_run(unanswered_set, unanswered_out), unanswered_out, reviewed)
    assert line.endswith(committable_refusal(unanswered_out, PRIVATE_PACKAGE)), line

    point_at(root, monkeypatch)
    for out in (tmp_path / "runs" / "outside", root / IGNORED / "run"):
        result = benchmark_run(with_private, out, "--standards-profile", str(profile))
        assert result.exit_code == 0, result.stdout + result.stderr
    assert reviewed == [(root / PACKAGE).resolve(), private.resolve()] * 2

    result = benchmark_run(committed_only, root / "runs" / "fictional")
    assert result.exit_code == 0, result.stdout + result.stderr


def test_committable_is_inside_the_root_and_not_reported_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`runner.committable(path, *, root)`, the one reading row 5 and compare's ledger guard
    share: outside the root never, inside it unless git reports the path ignored, and inside it
    whenever git cannot answer."""
    root = tmp_path / "checkout"
    checkout(root)

    assert runner.committable(root / "runs" / "new", root=root) is True
    assert runner.committable(root / "README.md", root=root) is True
    assert runner.committable(root / IGNORED / "run", root=root) is False
    assert runner.committable(tmp_path / "elsewhere", root=root) is False

    monkeypatch.setattr("swreview.benchmark.runner.subprocess.run", no_git)
    assert runner.committable(root / IGNORED / "run", root=root) is True
    assert runner.committable(tmp_path / "elsewhere", root=root) is False


@pytest.mark.parametrize("folder", ["-x", "--stdin"])
def test_a_folder_named_like_an_option_is_asked_about_as_a_path(
    folder: str, tmp_path: Path
) -> None:
    """`git check-ignore` is handed the path after `--`, so a folder whose name starts with `-`
    is read as a path, never as an option: one the checkout ignores reads not committable, where
    `-x` would make git refuse the command and `--stdin` wait on standard input."""
    if shutil.which("git") is None:
        pytest.skip("git is not on the path")
    root = tmp_path / "checkout"
    checkout(root)
    with (root / ".gitignore").open("a", encoding="utf-8") as ignore:
        ignore.write(f"/{folder}/\n")
    (root / folder / "run").mkdir(parents=True)

    assert runner.committable(root / folder / "run", root=root) is False
    assert runner.committable(root / "runs" / folder, root=root) is True


# --- the committable-path scanner (T055, for T056; provenance.md 6.6) ---------------------


def written(path: Path, text: str) -> Path:
    """`text` written at `path` as UTF-8 bytes, its folder made; returns `path`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return path


def reasons(path: Path) -> list[str]:
    """What the scanner flags in the one file at `path`, by reason, in the file's order."""
    return [offence.reason for offence in local_paths.scan_file(path)]


def offences(path: Path) -> list[tuple[str, str]]:
    """What the scanner flags in the one file at `path`: each reason and the text it flags."""
    return [(offence.reason, offence.text) for offence in local_paths.scan_file(path)]


def forward(path: str) -> str:
    return path.replace("\\", "/")


def backward(path: str) -> str:
    return path.replace("/", "\\")


def vault_root(profile: Path) -> str:
    """The `vault_root` a profile file holds, read here apart from the scanner's own read."""
    return yaml.safe_load(profile.read_text(encoding="utf-8"))["vault_root"]


LOCAL_FOLDERS: tuple[tuple[str, Path], ...] = (
    (local_paths.CHECKOUT_FOLDER, REPO_ROOT / "benchmarks" / "studies" / "pane" / "run-1"),
    (local_paths.HOME_FOLDER, Path.home() / "Documents" / "notes.md"),
    (local_paths.TEMPORARY_FOLDER, Path(tempfile.gettempdir()) / "run-1" / "session.json"),
)
"""A path under each local folder and the reason naming it. On a developer's machine the home
folder holds the other two, so each is reported by the longest folder it lies under."""


@pytest.mark.parametrize(("reason", "path"), LOCAL_FOLDERS, ids=["checkout", "home", "temporary"])
def test_the_scanner_flags_the_checkout_home_and_temporary_folders_in_any_spelling(
    reason: str, path: Path, tmp_path: Path
) -> None:
    """Each local folder in forward slashes, backslashes, doubled backslashes and upper case in a
    plain file, and JSON-escaped in a JSON file, `\\u005c` and `\\/` escapes and a JSON file that
    does not parse included: one offence per mention, the folder's own."""
    text = str(path)
    plain = {
        "forward": forward(text),
        "backward": backward(text),
        "doubled": backward(text).replace("\\", "\\\\"),
        "upper": text.upper(),
    }
    for name, spelling in plain.items():
        flagged = reasons(written(tmp_path / f"{name}.md", f"the run wrote {spelling} today\n"))
        assert flagged == [reason], name

    escaped = json.dumps({"run_dir": text, "streams": [{forward(text): "a key names it"}]})
    assert reasons(written(tmp_path / "escaped.json", escaped)) == [reason, reason]
    documents = {
        "unicode": '{"run_dir": "' + backward(text).replace("\\", "\\u005c") + '"}',
        "slash": '{"run_dir": "' + forward(text).replace("/", "\\/") + '"}',
        "broken": '{"run_dir": "' + forward(text) + '"',
    }
    for name, document in documents.items():
        assert reasons(written(tmp_path / f"{name}.json", document)) == [reason], name


def test_the_scanner_flags_drive_letter_unc_and_rooted_paths_outside_the_fictional_roots(
    tmp_path: Path,
) -> None:
    """Drive-letter and UNC paths are found through `scramble.WINDOWS_ANCHOR`, imported rather
    than restated (RF-6), a drive letter written with `/` as well; a rooted path is a `/` at a
    token boundary followed by a non-space. Each is reported once, as the file spells it, however
    many separators it holds, in a plain file and in a JSON one."""
    assert local_paths.WINDOWS_ANCHOR is scramble.WINDOWS_ANCHOR
    assert not hasattr(scramble, "_WINDOWS_ANCHOR")
    cases = {
        "E:\\Vault\\Real\\bracket.SLDPRT": local_paths.DRIVE_PATH,
        "e:/vault/real/bracket.SLDPRT": local_paths.DRIVE_PATH,
        "E:\\\\Vault\\\\Real\\\\bracket.SLDPRT": local_paths.DRIVE_PATH,
        "\\\\fileserver\\share\\bracket.SLDPRT": local_paths.UNC_PATH,
        "\\\\Designs\\share\\bracket.SLDPRT": local_paths.UNC_PATH,
        "/srv/real-vault/bracket.SLDPRT": local_paths.ROOTED_PATH,
        "//fileserver/share/bracket.SLDPRT": local_paths.ROOTED_PATH,
    }
    for number, (path, reason) in enumerate(cases.items()):
        plain = local_paths.scan_file(written(tmp_path / f"{number}.md", f"read ({path}).\n"))
        assert [(offence.reason, offence.text) for offence in plain] == [(reason, path)], path
        as_json = written(tmp_path / f"{number}.json", json.dumps({"vault_path": path}))
        assert reasons(as_json) == [reason], path


def test_the_scanner_ignores_and_or_fractions_urls_and_relative_paths(tmp_path: Path) -> None:
    """A `/` after a word character, `:`, `/` or `.`, or before a space, starts no path, and a
    doubled backslash after a word character, as a relative Windows path's `repr` spells it, is
    no UNC path."""
    text = (
        "valid and/or missed, 1/2 of the holes, n/a; https://example.com/a/b?page=2 and "
        "./benchmarks/sets/pilot.json, ../config/standards.example.yaml, "
        "benchmarks/packages/cover-blind-tap, 'native\\\\cover-assy.SLDASM', valid / missed\n"
    )
    assert reasons(written(tmp_path / "ledger.md", text)) == []
    assert reasons(written(tmp_path / "message.json", json.dumps({"message": text}))) == []


def test_the_scanner_admits_only_the_four_local_path_placeholders(tmp_path: Path) -> None:
    """104A: separators after these four exact placeholders start no rooted or UNC path."""
    for placeholder in ("<run>", "<repo>", "<tmp>", "<home>"):
        for separator in ("/", "\\", "\\\\"):
            text = f"{placeholder}{separator}x"
            assert reasons(written(tmp_path / "placeholder.md", text)) == [], text

    flagged = {
        ">/srv/x": local_paths.ROOTED_PATH,
        "<other>/x": local_paths.ROOTED_PATH,
        "C:\\Users\\FICT\\x": local_paths.DRIVE_PATH,
        "/home/fict/x": local_paths.ROOTED_PATH,
        "\\\\FICT\\share\\x": local_paths.UNC_PATH,
        "<run>C:\\Users\\FICT\\x": local_paths.DRIVE_PATH,
        "<run>/x/C:\\Users\\FICT\\x": local_paths.DRIVE_PATH,
    }
    for text, reason in flagged.items():
        assert reasons(written(tmp_path / "flagged.md", text)) == [reason], text


def test_the_scanner_finds_nothing_in_a_message_scrubbed_of_local_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T182: every spelling is detected before scrubbing; the longest local folder wins."""
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
    run = tmp_path / "Run-FICT"
    assert run.is_relative_to(Path(tempfile.gettempdir()))
    spellings = (forward, backward, lambda text: backward(text).replace("\\", "\\\\"))
    messages: list[str] = []
    expected: list[str] = []
    for folder, placeholder, tail in (
        (run, "<run>", "attempts/pkg/events.jsonl"),
        (REPO_ROOT, "<repo>", "benchmarks/x"),
        (Path(tempfile.gettempdir()), "<tmp>", "scratch/x"),
        (Path.home(), "<home>", ".cache/x"),
    ):
        for prefix in (str(folder), str(folder).swapcase()):
            for spelling in spellings:
                messages.append(spelling(f"cannot read {prefix}/{tail}"))
                expected.append(spelling(f"cannot read {placeholder}/{tail}"))
    text = "\n".join(messages)
    assert len(local_paths.scan_file(written(tmp_path / "before.md", text))) == len(messages)

    from swreview.benchmark.scrub import without_local_paths

    scrubbed = without_local_paths(text, run_dir=run, root=REPO_ROOT)
    assert scrubbed == "\n".join(expected)
    assert "<run>/attempts/pkg/events.jsonl" in scrubbed
    assert reasons(written(tmp_path / "after.md", scrubbed)) == []
    unchanged = "cannot read attempts/pkg/events.jsonl"
    assert without_local_paths(unchanged, run_dir=run, root=REPO_ROOT) == unchanged


def test_the_scrub_preserves_longer_and_hyphenated_folder_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from swreview.benchmark.scrub import without_local_paths

    run, root, temporary, home = (tmp_path / name for name in ("run", "repo", "tmp", "home"))
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(temporary))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    for folder in (run, root, temporary, home):
        for suffix in ("2", "-other", "_copy"):
            text = f"cannot read {folder}{suffix}/x"
            assert without_local_paths(text, run_dir=run, root=root) == text


def test_the_scrub_covers_each_spelled_and_resolved_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from swreview.benchmark.scrub import without_local_paths

    folders = tuple(tmp_path / "alias" / ".." / name for name in ("run", "repo", "tmp", "home"))
    run, root, temporary, home = folders
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(temporary))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    for folder, placeholder in zip(folders, ("<run>", "<repo>", "<tmp>", "<home>"), strict=True):
        for form in (folder, folder.resolve()):
            text = f"cannot read {form}/x"
            assert without_local_paths(text, run_dir=str(run), root=str(root)) == (
                f"cannot read {placeholder}/x"
            )


def test_the_scrub_skips_a_bare_drive_or_root_anchor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from swreview.benchmark.scrub import without_local_paths

    anchor = Path(tmp_path.anchor)
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(anchor))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: anchor))
    text = f"root {anchor}; see {(anchor / '.cache' / 'FICT' / 'x').as_posix()}"
    assert without_local_paths(text, run_dir=anchor, root=anchor) == text


def test_a_relative_run_folder_does_not_scrub_parts_of_ordinary_words(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from swreview.benchmark.scrub import without_local_paths

    monkeypatch.chdir(tmp_path)
    text = (
        "Request timed out; read timeout about the output; cannot read "
        f"{(tmp_path / 'out/x').as_posix()}"
    )
    assert without_local_paths(text, run_dir=Path("out")) == (
        "Request timed out; read timeout about the output; cannot read <run>/x"
    )


def test_the_scrub_requires_a_leading_path_boundary(tmp_path: Path) -> None:
    """Only POSIX spellings need a word boundary; absolute drive/UNC paths are unambiguous.

    A dot is a boundary too, and escaped newline/tab/carriage-return boundaries are covered
    below. Relative single-name output folders still must not rewrite ordinary words (C10).
    """
    from swreview.benchmark.scrub import without_local_paths

    run = tmp_path / "run"
    text = f"fict{run}/x .{run}/y; cannot read {run}/z"
    first = "<run>" if run.drive else str(run)
    assert without_local_paths(text, run_dir=run) == f"fict{first}/x .<run>/y; cannot read <run>/z"


@pytest.mark.parametrize(("folder", "path"), [
    (r"C:\Users\fict\run", r"C:\Users\fict\run\private.txt"),
    (r"C:\Users\fict\run", "C:/Users/fict/run/private.txt"),
    (r"C:\Users\fict\run", r"C:\\Users\\fict\\run\\private.txt"),
    (r"\\fict-host\share\run", r"\\fict-host\share\run\private.txt"),
    (r"\\fict-host\share\run", "//fict-host/share/run/private.txt"),
    (r"\\fict-host\share\run", r"\\\\fict-host\\share\\run\\private.txt"),
    ("/home/fict/run", "/home/fict/run/private.txt"),
], ids=["drive", "forward-drive", "repr-drive", "unc", "forward-unc", "repr-unc", "posix"])
@pytest.mark.parametrize("escaped", [r"\n", r"\t", r"\r"], ids=["newline", "tab", "return"])
def test_the_scrub_accepts_escaped_control_boundaries_on_either_platform(
    monkeypatch: pytest.MonkeyPatch, folder: str, path: str, escaped: str,
) -> None:
    """Exercise foreign absolute paths on either host without resolving them into local paths."""
    from swreview.benchmark import scrub

    flavour = PurePosixPath if folder.startswith("/") else PureWindowsPath
    monkeypatch.setattr(flavour, "resolve", lambda path: path, raising=False)
    monkeypatch.setattr(flavour, "home", classmethod(lambda cls: cls(folder)), raising=False)
    monkeypatch.setattr(scrub, "Path", flavour)
    monkeypatch.setattr(tempfile, "gettempdir", lambda: folder)
    tail = path[path.index("run") + len("run"):]
    assert scrub.without_local_paths(
        f"line one{escaped}{path}", run_dir=folder, root=folder,
    ) == f"line one{escaped}<run>{tail}"


@pytest.mark.parametrize(("path", "reason"), [
    (r"E:\Users\fict\private.txt", local_paths.DRIVE_PATH),
    ("E:/Users/fict/private.txt", local_paths.DRIVE_PATH),
    (r"\\fict-host\share\private.txt", local_paths.UNC_PATH),
    ("/home/fict/private.txt", local_paths.ROOTED_PATH),
], ids=["drive", "forward-drive", "unc", "posix"])
@pytest.mark.parametrize("escaped", [r"\n", r"\t", r"\r"], ids=["newline", "tab", "return"])
def test_the_scanner_flags_paths_after_escaped_control_boundaries(
    tmp_path: Path, path: str, reason: str, escaped: str,
) -> None:
    text = f"line one{escaped}{path}"
    assert offences(written(tmp_path / "before.md", text)) == [(reason, path)]
    assert offences(written(tmp_path / "before.json", json.dumps({"message": text}))) == [
        (reason, path)
    ]


@pytest.mark.parametrize("separator", ["/", "\\"], ids=["forward", "native"])
@pytest.mark.parametrize("control", ["\n", "\t", "\r"], ids=["newline", "tab", "return"])
def test_run_benchmark_scrubs_repr_paths_after_control_characters(
    tmp_path: Path, separator: str, control: str,
) -> None:
    """A real fake-provider run records no private path from an internal two-line repr error."""
    from tests.unit.test_benchmark_attempts import driver_row, prepare_driver_set

    preflighted = prepare_driver_set(tmp_path)
    out = tmp_path / "run"
    path = f"{out.as_posix()}/attempts/fict-a/1/private.txt".replace("/", separator)

    def review(*args: Any, **kwargs: Any) -> None:
        raise PermissionError(f"cannot read {('line one' + control + path)!r}")

    assert runner.run_benchmark(
        preflighted, out, provider="fake", model="fict-model", effort="low",
        review_fn=review, clock=lambda: 0.0,
    ) == []
    row = driver_row(out)
    assert row["class"] == "internal_error"
    expected = f"<run>{separator}attempts{separator}fict-a{separator}1{separator}private.txt"
    assert row["message"] == f"cannot read {('line one' + control + expected)!r}"
    assert local_paths.scan_file(out / runner.RUN_STATUS_FILE) == []
    assert local_paths.scan_folder(out) == []


@pytest.mark.parametrize("separator", ["/", "\\\\"])
def test_html_escaped_scrub_placeholders_and_markup_scan_clean(
    tmp_path: Path, separator: str,
) -> None:
    import html

    text = " ".join(f"{placeholder}{separator}attempts/fict-a/1/private.txt" for placeholder in (
        "<run>", "<repo>", "<tmp>", "<home>",
    ))
    page = f"<p>{html.escape(text)} &lt;/script&gt;</p>"
    assert local_paths.scan_file(written(tmp_path / "failed.html", page)) == []


@pytest.mark.parametrize("path", ["/srv/fict-vault/private.txt", "C:/FictPrivate/x.txt"])
def test_html_unescaping_still_flags_real_escaped_paths(tmp_path: Path, path: str) -> None:
    encoded = "".join(f"&#{ord(char)};" for char in path)
    found = local_paths.scan_file(written(tmp_path / "escaped.html", f"<p>{encoded}</p>"))
    assert [offence.text for offence in found] == [path]


def test_relative_cli_out_passes_the_resolved_run_folder_and_preserves_failure_words(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from typer.testing import CliRunner

    from swreview import cli
    from swreview.agent.providers.fake import FakeProvider, ScriptedTurn
    from tests.unit.test_benchmark_attempts import (
        driver_row,
        install_driver_providers,
        prepare_driver_set,
    )

    prepare_driver_set(tmp_path)
    monkeypatch.chdir(tmp_path)
    out = tmp_path / "out"
    message = f"Request timed out; read timeout about the output; cannot read {out.as_posix()}/x"

    class BrokenProvider(FakeProvider):
        def run(self, **options: Any) -> Any:
            raise PermissionError(message)

    install_driver_providers(monkeypatch, [[ScriptedTurn(text="")]], kind=BrokenProvider)
    real_run = cli.run_benchmark
    folders: list[Path] = []

    def run(preflighted: Any, folder: Path, **options: Any) -> Any:
        folders.append(folder)
        return real_run(preflighted, folder, **options, clock=lambda: 0.0)

    monkeypatch.setattr(cli, "run_benchmark", run)
    result = CliRunner().invoke(cli.app, [
        "benchmark", "run", "--set", str(tmp_path / "set.json"), "--out", "out",
        "--provider", "fake",
    ])
    assert result.exit_code == 1, result.stdout + result.stderr
    assert folders == [out.resolve()]
    assert driver_row(out)["message"] == (
        "Request timed out; read timeout about the output; cannot read <run>/x"
    )


@pytest.mark.parametrize("separator", ["/", "\\\\"])
def test_failed_attempt_report_with_scrubbed_paths_scans_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, separator: str,
) -> None:
    from swreview.agent.providers.fake import FakeProvider, ScriptedTurn
    from swreview.benchmark.report_page import build_report
    from swreview.benchmark.scorecard import SCORECARD_FILE, score_run
    from tests.unit.test_benchmark_attempts import (
        driver_run,
        install_driver_providers,
        prepare_driver_set,
    )

    preflighted = prepare_driver_set(tmp_path)
    out = tmp_path / "run"
    path = f"{out.as_posix()}/attempts/fict-a/1/private.txt".replace("/", separator)

    class BrokenProvider(FakeProvider):
        def run(self, **options: Any) -> Any:
            raise PermissionError(f"cannot read '{path}'")

    install_driver_providers(monkeypatch, [[ScriptedTurn(text="")]], kind=BrokenProvider)
    assert driver_run(preflighted, out) == []
    assert local_paths.scan_folder(out) == []
    keys = tmp_path / "answer_keys"
    write_key(keys, "fict-a", known_defects=[])
    (out / SCORECARD_FILE).write_text(
        score_run(out, keys, preflighted.benchmark_set).model_dump_json(by_alias=True),
        encoding="utf-8",
    )
    report = tmp_path / "report"
    build_report([out], report)

    assert local_paths.scan_folder(report) == []


def test_an_html_end_tag_or_a_self_closing_tag_starts_no_path(tmp_path: Path) -> None:
    """The report slice's pages may be committed (`report.md` 4): an end tag's `/` (`</td>`,
    `</table>`, any case, a space before its `>`) and a self-closing tag's `/>` start no rooted
    path. A rooted path in a cell or an attribute is still found, ended by the tag after it, and
    so is one written straight after a `<`, which no end tag's name is."""
    page = (
        "<table><thead><tr><th>run</th></tr></thead>\n"
        "<tr><td>valid</td><td>1/2</td></tr></TABLE>\n"
        '<meta name="generator" content="swreview benchmark report" />\n<br/><hr />\n'
        '<p>see <a href="transcripts/pane/run-1/pkg-1.html">pkg-1</a></p >\n'
    )
    assert reasons(written(tmp_path / "index.html", page)) == []
    flagged = (
        "<td>/srv/real-vault/bracket.SLDPRT</td>"
        '<a href="/srv/other/notes.md">notes</a></srv/real-vault/x>\n'
    )
    assert offences(written(tmp_path / "flagged.html", flagged)) == [
        (local_paths.ROOTED_PATH, "/srv/real-vault/bracket.SLDPRT"),
        (local_paths.ROOTED_PATH, "/srv/other/notes.md"),
        (local_paths.ROOTED_PATH, "/srv/real-vault/x"),
    ]


def test_a_path_that_climbs_out_of_a_fictional_root_is_flagged(tmp_path: Path) -> None:
    """A path lies under a fictional root once its `..` are applied: one that starts at a root and
    climbs out of it is flagged by its anchor, as the file spells it, in a plain file and in a
    JSON one; one whose `..` stays inside the root passes."""
    example = vault_root(REPO_ROOT / runner.EXAMPLE_PROFILE)
    climbing = {
        scramble.FICTIONAL_ROOT + "..\\Users\\someone\\bracket.SLDPRT": local_paths.DRIVE_PATH,
        example + "/../Private/bracket.SLDPRT": local_paths.DRIVE_PATH,
        "/Designs/../srv/real-vault/bracket.SLDPRT": local_paths.ROOTED_PATH,
        "/Designs/a/../../srv/bracket.SLDPRT": local_paths.ROOTED_PATH,
    }
    for number, (path, reason) in enumerate(climbing.items()):
        plain = written(tmp_path / f"{number}.md", f"read {path}\n")
        assert offences(plain) == [(reason, path)], path
        as_json = written(tmp_path / f"{number}.json", json.dumps({"path": path}))
        assert reasons(as_json) == [reason], path
    for path in (
        scramble.FICTIONAL_ROOT + "Vault\\..\\Other\\bracket.SLDPRT",
        "/Designs/a/../b/bracket.SLDPRT",
    ):
        assert reasons(written(tmp_path / "staying.md", f"read {path}\n")) == [], path


def test_a_drive_path_glued_to_a_word_character_is_flagged(tmp_path: Path) -> None:
    """A drive letter and its backslash start a path wherever they stand, so a path run into the
    text before it is found: plain text quoting an escaped line (`...\\nE:\\...`), or a word typed
    against it; under a fictional root it still passes. A drive letter with `/`, which a URL's
    scheme ends in, and a UNC anchor's two backslashes still start one only at a token
    boundary."""
    path = "E:\\Vault\\Real\\bracket.SLDPRT"
    for number, text in enumerate(
        (f"line one\\n{path}\n", f"the run wrote{path} today\n", f"x_9{path}\n")
    ):
        assert offences(written(tmp_path / f"{number}.md", text)) == [
            (local_paths.DRIVE_PATH, path)
        ], text
    fictional = f"see{scramble.FICTIONAL_ROOT}Vault\\bracket.SLDPRT\n"
    assert reasons(written(tmp_path / "fictional.md", fictional)) == []
    anchors = "https://example.com/a and native\\\\cover-assy.SLDASM\n"
    assert reasons(written(tmp_path / "anchors.md", anchors)) == []


def test_text_like_an_escape_after_a_colon_reads_as_a_glued_drive_path(tmp_path: Path) -> None:
    """By decision (research 9.14, slice 3 follow-ups): since a drive letter and its backslash
    start a path wherever they stand, plain text such as `regex:\\d+` reads as the drive path
    `x:\\d+`. A false alarm on the refusing side, kept: a rule narrow enough to pass it would also
    pass a path typed against a word, which the test above flags."""
    text = "split it with regex:\\d+ first\n"

    assert offences(written(tmp_path / "regex.md", text)) == [(local_paths.DRIVE_PATH, "x:\\d+")]


def test_a_json_lines_file_and_a_packed_stream_are_read_line_by_line(tmp_path: Path) -> None:
    """Each line of a `.jsonl` file, and of an `events.jsonl.gz` once decompressed, is parsed as
    JSON on its own, so a path its escapes spell (`\\u005c` for each backslash) is found as the
    line means it, on every line, and a line that is not JSON is read as its text. Read as one
    text, the file would reach each offence as escaped."""
    path = "E:\\Vault\\Real\\bracket.SLDPRT"
    escaped = path.replace("\\", "\\u005c")
    lines = (
        '{"type": "tool.started", "arguments": {"path": "' + escaped + '"}}\n'
        "not json: /srv/real-vault/bracket.SLDPRT\n"
        '{"type": "tool.finished", "summary": "read ' + escaped + '"}\n'
    )
    plain = written(tmp_path / "plain" / "events.jsonl", lines)
    packed = tmp_path / "packed" / "events.jsonl.gz"
    packed.parent.mkdir()
    packed.write_bytes(gzip.compress(lines.encode("utf-8"), compresslevel=9, mtime=0))
    expected = [
        (local_paths.DRIVE_PATH, path),
        (local_paths.ROOTED_PATH, "/srv/real-vault/bracket.SLDPRT"),
        (local_paths.DRIVE_PATH, path),
    ]

    assert offences(plain) == expected
    assert offences(packed) == expected
    assert offences(written(tmp_path / "whole.md", lines))[0] == (local_paths.DRIVE_PATH, escaped)


def test_the_scanner_passes_each_named_fictional_root_and_nothing_beside_it(
    tmp_path: Path,
) -> None:
    """The roots the builders and the fictional profiles write absolute paths under (research
    8.8): the two `FICTIONAL_ROOT`s imported, the three `vault_root`s read from their files, and
    `/Designs/` (`tests/support/features.py:717`, `tests/support/packages.py:54`) and `/Library/`
    (`tests/golden/fixtures/bracket-assy-interference/package.json:60`), written inline. A path
    under each passes in either separator; one under a folder whose name only begins with the
    root's is flagged."""
    roots = (
        mechanical.FICTIONAL_ROOT,
        scramble.FICTIONAL_ROOT,
        vault_root(REPO_ROOT / runner.EXAMPLE_PROFILE),
        vault_root(PROFILE_DIR / "profile-a.yaml"),
        vault_root(PROFILE_DIR / "profile-b.yaml"),
        "/Designs/",
        "/Library/",
    )
    assert set(local_paths.FICTIONAL_ROOTS) == set(roots)
    for number, root in enumerate(roots):
        under = root.rstrip("\\/") + "/Vault/bracket.SLDPRT"
        for spelling in (forward(under), backward(under)):
            assert reasons(written(tmp_path / f"{number}.md", f"see {spelling}\n")) == [], spelling
            assert reasons(written(tmp_path / f"{number}.json", json.dumps([spelling]))) == []
        beside = root.rstrip("\\/") + "x/bracket.SLDPRT"
        flagged = reasons(written(tmp_path / f"{number}-beside.md", f"see {beside}\n"))
        assert len(flagged) == 1, beside


def test_the_scanner_flags_a_saved_set_naming_a_path_outside_the_repository(
    tmp_path: Path,
) -> None:
    """A private entry (`provenance.md` 6.1): a package entry's string with a drive or a root, in
    either platform's spelling, or a relative one climbing out of the repository, even under a
    fictional root; a repository-relative entry passes, and the rule reads only the saved set's
    file name. The saved form `benchmark run` writes passes for a committed-only set and is
    flagged for one naming a package outside the checkout."""
    entries = [
        {"package_id": "pkg-1", "path": "benchmarks/packages/pkg-1", "held_out": True},
        {"package_id": "pkg-2", "path": "C:\\FictionalVault\\pkg-2"},
        {"package_id": "pkg-3", "path": "/Designs/pkg-3"},
        {"package_id": "pkg-4", "path": "../private/pkg-4"},
    ]
    payload = json.dumps({"name": "pane", "packages": entries}, indent=2)
    saved = local_paths.scan_file(written(tmp_path / "run" / "benchmark-set.json", payload))
    assert [(offence.reason, offence.text) for offence in saved] == [
        (local_paths.PRIVATE_ENTRY, "C:\\FictionalVault\\pkg-2"),
        (local_paths.PRIVATE_ENTRY, "/Designs/pkg-3"),
        (local_paths.PRIVATE_ENTRY, "../private/pkg-4"),
    ]
    assert reasons(written(tmp_path / "run" / "pane.json", payload)) == []

    checkout = (tmp_path / "checkout").resolve()
    inside = BenchmarkPackageRef(package_id="pkg-1", path=checkout / PACKAGE)
    outside = BenchmarkPackageRef(
        package_id="pkg-2", path=(tmp_path / "private" / "pkg-2").resolve()
    )
    for folder, packages, private in (
        ("committed", [inside], False),
        ("private", [inside, outside], True),
    ):
        saved_set = tmp_path / folder / "benchmark-set.json"
        saved_set.parent.mkdir(parents=True)
        saved_set.write_bytes(
            BenchmarkSet(name="pane", packages=packages).saved_form(root=checkout)
        )
        assert (local_paths.PRIVATE_ENTRY in reasons(saved_set)) is private, folder


def test_the_scanner_reads_a_packed_stream_by_its_decompressed_text(tmp_path: Path) -> None:
    """RF-84: an `events.jsonl.gz` packed as `benchmark pack` packs is read through
    `gzip.decompress`, then UTF-8, its lines as JSON: one naming the checkout folder is flagged,
    one naming only a fictional root passes."""

    def packed(folder: str, path: str) -> Path:
        lines = [
            {"type": "session.started", "session_id": "s-1"},
            {"type": "tool.started", "arguments": {"path": path}},
        ]
        data = "".join(json.dumps(line) + "\n" for line in lines).encode("utf-8")
        target = tmp_path / folder / "events.jsonl.gz"
        target.parent.mkdir(parents=True)
        target.write_bytes(gzip.compress(data, compresslevel=9, mtime=0))
        return target

    local = packed("local", str(REPO_ROOT / "reviewer" / "runs" / "events.jsonl"))
    assert reasons(local) == [local_paths.CHECKOUT_FOLDER]
    fictional = packed("fictional", scramble.FICTIONAL_ROOT + "Vault\\cover-assy.SLDASM")
    assert reasons(fictional) == []


def test_a_file_the_scanner_cannot_read_as_text_is_flagged_not_passed(tmp_path: Path) -> None:
    """A file that is not UTF-8, a packed stream that does not decompress, or a saved set that is
    not a set cannot be shown to hold no local path: each is one offence naming it."""
    binary = tmp_path / "picture.png"
    binary.write_bytes(b"\x89PNG\r\n\x1a\n\xff\xfe\x00")
    truncated = tmp_path / "pkg-1" / "events.jsonl.gz"
    truncated.parent.mkdir()
    truncated.write_bytes(gzip.compress(b'{"type": "session.started"}\n', mtime=0)[:-6])
    not_packed = tmp_path / "pkg-2" / "events.jsonl.gz"
    not_packed.parent.mkdir()
    not_packed.write_bytes(b'{"type": "session.started"}\n')
    not_a_set = written(tmp_path / "run" / "benchmark-set.json", '["benchmarks/packages/pkg-1"]')
    for path in (binary, truncated, not_packed, not_a_set):
        assert [(offence.file, offence.reason) for offence in local_paths.scan_file(path)] == [
            (path, local_paths.UNREADABLE)
        ]


def test_a_folder_scan_reads_every_file_beneath_it(tmp_path: Path) -> None:
    """`scan_folder`: every file under the folder, at any depth, in path order."""
    run = tmp_path / "run"
    written(run / "run-provenance.json", json.dumps({"commit": "abc1234"}))
    session = written(run / "pkg-1" / "session.json", json.dumps({"out": str(REPO_ROOT / "x")}))
    prompts = written(
        run / "attempts" / "pkg-1" / "1" / "prompts.json",
        json.dumps({"text": "read E:\\Vault\\bracket.SLDPRT"}),
    )
    found = local_paths.scan_folder(run)
    assert [(offence.file, offence.reason) for offence in found] == [
        (prompts, local_paths.DRIVE_PATH),
        (session, local_paths.CHECKOUT_FOLDER),
    ]


def test_the_committable_reach_is_the_two_trees_unignored_files_and_the_ledger_block(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Section 6.6's reach over a temporary repository: every file under `benchmarks/studies/` and
    `benchmarks/pilots/` git does not ignore, a tracked one a rule would ignore included, and the
    ledger block of `docs/llm-efficiency-options.md`; nothing else. Where git cannot answer, every
    file of the two trees, the side that refuses (section 6.4)."""
    if shutil.which("git") is None:
        pytest.skip("git is not on the path")
    root = tmp_path / "checkout"
    local = json.dumps({"run_dir": str(REPO_ROOT / "benchmarks")})
    run = root / "benchmarks" / "studies" / "pane" / "run-1"
    study = written(run / "run-status.json", local)
    ignored = written(run / "pkg-1" / "events.jsonl", local)
    pilot = root / "benchmarks" / "pilots" / "pane" / "run-1"
    scorecard = written(pilot / "scorecard.json", local)
    tracked = written(pilot / "pkg-1" / "events.jsonl", local)
    written(root / "benchmarks" / "sets" / "pane.json", local)
    ledger = (
        f"{local}\n{LEDGER_BEGIN}\n\n| run |\n|---|\n| {REPO_ROOT} |\n\n{LEDGER_END}\n{local}\n"
    )
    document = written(root / "docs" / "llm-efficiency-options.md", ledger)
    written(root / ".gitignore", "**/events.jsonl\n")
    git(root, "init", "-q")
    git(root, "add", "-f", tracked.relative_to(root).as_posix())

    found = local_paths.scan_committable(root)
    assert [(offence.file, offence.reason) for offence in found] == [
        (tracked, local_paths.CHECKOUT_FOLDER),
        (scorecard, local_paths.CHECKOUT_FOLDER),
        (study, local_paths.CHECKOUT_FOLDER),
        (document, local_paths.CHECKOUT_FOLDER),
    ]

    monkeypatch.setattr("swreview.benchmark.runner.subprocess.run", no_git)
    assert ignored in {offence.file for offence in local_paths.scan_committable(root)}


def test_no_committable_file_holds_a_local_path_or_a_private_set_entry() -> None:
    """Section 6.6 over this checkout: no file under `benchmarks/studies/` or `benchmarks/pilots/`
    git does not ignore (none yet), nor the committed ledger block, names a local folder, a path
    outside the fictional roots or a private set entry."""
    assert [str(offence) for offence in local_paths.scan_committable()] == []


def test_an_offline_run_over_a_committed_style_package_writes_no_local_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """US2-11 (`provenance.md` 6.6 and 8; RF-25, RF-59; FR-051): in a temporary git repository
    holding the example profile, a fictional package under `benchmarks/packages/` and its set under
    `benchmarks/sets/`, the commands pointed at it through `sets.REPO_ROOT`, a scripted `benchmark
    run` with the example profile into `benchmarks/studies/<study>/<run>/`, then `score`, then
    `compare --out` a folder inside the repository: the scanner finds nothing in the run folder or
    the ledger. At `--max-answer-turns 0`, which the scripted-answers slice adds with the option
    (lane A3): the one-turn scripted review cannot play an anchor's scripted answer."""
    root = tmp_path / "checkout"
    set_file = checkout(root)
    point_at(root, monkeypatch)
    keys = root / "benchmarks" / "answer_keys"
    write_key(
        keys,
        "pkg-1",
        known_defects=[
            {
                "check": "drawing.manufacturing_inputs",
                "document_ids": ["doc:1"],
                "tag": "held_out",
                "description": "The tapped hole callout omits the thread depth",
            }
        ],
    )
    run = root / "benchmarks" / "studies" / "smoke" / "run-1"
    ledger = root / "benchmarks" / "ledgers" / "smoke"

    ran = benchmark_run(
        set_file,
        run,
        "--standards-profile",
        str(root / runner.EXAMPLE_PROFILE),
        "--max-answer-turns",
        "0",
    )
    assert ran.exit_code == 0, ran.stdout + ran.stderr
    scored = invoke("benchmark", "score", str(run), "--answer-keys", str(keys))
    assert scored.exit_code == 0, scored.stdout + scored.stderr
    compared = invoke("benchmark", "compare", str(run), "--out", str(ledger))
    assert compared.exit_code == 0, compared.stdout + compared.stderr

    assert (run / "pkg-1" / "session.json").is_file()
    assert (ledger / "ledger.md").is_file()
    found = local_paths.scan_folder(run) + local_paths.scan_folder(ledger)
    assert [str(offence) for offence in found] == []


# --- the packed event streams' git rules (T057, for T058; provenance.md 6.6) --------------


def ignored(path: str) -> bool:
    """Whether `git check-ignore -q --no-index` reports `path` ignored in this checkout, tracked
    or not; an answer other than yes (0) or no (1) fails the test."""
    proc = subprocess.run(
        ["git", "check-ignore", "-q", "--no-index", path],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode in (0, 1), proc.stderr
    return proc.returncode == 0


def test_packed_streams_are_committable_only_in_the_study_and_pilot_trees() -> None:
    """28A; RF-84, which supersedes RF-78's plain-stream test. A packed stream in a study's or a
    pilot's package or attempt folder is committable; a plain stream at each of those places is
    ignored, the working form never reaching a commit, and so is a packed one anywhere else, the
    anchored rule matching no `studies/` folder deeper in the tree. Every packed stream is binary,
    `*.gz binary` coming after `benchmarks/** eol=lf`, so no checkout converts a compressed byte."""
    if shutil.which("git") is None:
        pytest.skip("git is not on the path")
    places = [
        f"{tree.as_posix()}/pane/run-1/{folder}"
        for tree in local_paths.STUDY_TREES
        for folder in ("pkg-1", "attempts/pkg-1/1")
    ]
    elsewhere = [
        "benchmarks/packages/pkg-1",
        "benchmarks/runs/pane/run-1/pkg-1",
        "benchmarks/old/studies/pane/run-1/pkg-1",
        "runs/pane/run-1/pkg-1",
    ]
    committable = [f"{place}/events.jsonl.gz" for place in places]
    plain = [f"{place}/events.jsonl" for place in places]
    packed_elsewhere = [f"{folder}/events.jsonl.gz" for folder in elsewhere]

    assert [path for path in committable if ignored(path)] == []
    assert [path for path in plain + packed_elsewhere if not ignored(path)] == []
    packed = committable + packed_elsewhere
    found = attributes(REPO_ROOT, packed, "binary", "text", "eol")
    assert {path: (found[path]["binary"], found[path]["text"]) for path in packed} == {
        path: ("set", "unset") for path in packed
    }


# --- the committed packed streams and their digests (T214, for T215; RF-84) -------------


def test_committed_run_folders_hold_packed_streams_matching_their_digests() -> None:
    """Every tracked study and pilot run has its tracked packed streams and digest rows;
    an unavailable git skips this assertion rather than silently passing it."""
    if shutil.which("git") is None:
        pytest.skip("git is not on the path")
    assert [str(offence) for offence in local_paths.check_committed_streams()] == []


@pytest.fixture(params=("studies", "pilots"))
def committed_packed_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
) -> tuple[Path, Path]:
    """Commit a fictional run that the real run and pack commands wrote."""
    from swreview.agent.providers.fake import ScriptedTurn
    from tests.unit.test_benchmark_resume import start_run

    if shutil.which("git") is None:
        pytest.skip("git is not on the path")
    root = tmp_path / "checkout"
    set_file = checkout(root)
    point_at(root, monkeypatch)
    run, result = start_run(
        root,
        monkeypatch,
        [[ScriptedTurn(text="Fictional review completed.")]],
        ids=("pkg-1",),
        set_file=set_file,
        out=root / "benchmarks" / request.param / "fictional" / "run-1",
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    packed = invoke("benchmark", "pack", str(run))
    assert packed.exit_code == 0, packed.stdout + packed.stderr
    git(root, "add", "-A")
    git(
        root,
        "-c", "user.name=Fictional Tester",
        "-c", "user.email=tester@example.invalid",
        "-c", "commit.gpgsign=false",
        "commit", "-q", "-m", "a fictional packed run",
    )
    return root, run


@pytest.mark.parametrize(
    "damage",
    ("missing-stream", "missing-row", "edited-stream", "orphan-row", "untracked-record"),
)
def test_the_committed_stream_check_rejects_a_broken_packed_run(
    committed_packed_run: tuple[Path, Path], damage: str
) -> None:
    """Pin the checkout assertion in both trees with a real packed and committed run:
    losing a tracked stream, a row, its bytes or its target must name the affected file."""
    root, run = committed_packed_run
    assert local_paths.check_committed_streams(root) == []
    stream = run / "pkg-1" / "events.jsonl.gz"
    relative = stream.relative_to(run).as_posix()
    record = run / "event-streams.json"
    payload = json.loads(record.read_bytes())
    expected = stream
    if damage == "missing-stream":
        git(root, "rm", stream.relative_to(root).as_posix())
    elif damage == "missing-row":
        del payload["streams"][relative]
    elif damage == "edited-stream":
        edited = gzip.decompress(stream.read_bytes()) + b"\n"
        stream.write_bytes(gzip.compress(edited, compresslevel=9, mtime=0))
    elif damage == "orphan-row":
        orphan = "orphan/events.jsonl.gz"
        payload["streams"][orphan] = "0" * 64
        expected = run / orphan
    else:
        git(root, "rm", "--cached", record.relative_to(root).as_posix())
        expected = record
    if damage in {"missing-row", "orphan-row"}:
        record.write_bytes((json.dumps(payload, sort_keys=True, indent=2) + "\n").encode())

    found = local_paths.check_committed_streams(root)
    assert found, damage
    assert expected in {offence.file for offence in found}, [str(offence) for offence in found]


def test_the_committed_stream_check_leaves_an_untracked_run_alone(tmp_path: Path) -> None:
    """A still-running, untracked study or pilot need not already have packed streams."""
    if shutil.which("git") is None:
        pytest.skip("git is not on the path")
    root = tmp_path / "checkout"
    checkout(root)
    for tree in local_paths.STUDY_TREES:
        run = root / tree / "fictional" / "running"
        written(run / "run-provenance.json", "{}\n")
        written(run / "pkg-1" / "session.json", "{}\n")

    assert local_paths.check_committed_streams(root) == []


def test_the_committed_stream_check_cannot_pass_where_git_cannot_answer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(local_paths, "_git", lambda *_args: None)
    with pytest.raises(RuntimeError, match="git"):
        local_paths.check_committed_streams(tmp_path)
