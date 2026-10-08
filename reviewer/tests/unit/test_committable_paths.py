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
from pathlib import Path
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
