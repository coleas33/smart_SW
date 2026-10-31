"""Unit tests for `swreview remodel ledger` (feature 004 T336; owner decisions 166A, 170A, 171A).

The reader parses what `RemodelProbeLedger.Render` writes - pinned to the C# renderer by one
golden fixture, which `RemodelProbeTests.Ledger_Render_WritesTheGoldenLedgerTheReaderIsPinnedTo`
renders byte for byte - and says per probe what it answered and, per seat switch, whether the
ledger lets the build switch it on and why not:

- **Start** (`RemodelStart.SeatValidated`) needs PROBE-1, 2, 3, 4 and 12 verified, each with a
  reason and no error (decision 148A's rule, which the plan states for PROBE-12's reopen), and the
  IDENTITY tolerance profile calibrated (decision 170A: PROBE-8's numbers are the calibration
  input, T138 and T187);
- a ledger for another SOLIDWORKS version than the frozen interop's is refused, and so is one any
  of whose strings looks like a path (decision 171A), with a refusal that repeats no value;
- the probes asked for with no row are the ones the run never finished (T333);
- PROBE-11's type names the RMS table does not know are listed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from swreview.cli import app
from swreview.remodel.ledger import (
    FROZEN_INTEROP_VERSION,
    START_PROBES,
    START_SWITCH,
    SW_VERSIONS,
    LedgerRefused,
    load_ledger,
    parse_ledger,
    path_kind,
    start_readiness,
    unknown_types,
)
from swreview.remodel.tolerances import IDENTITY
from tests.support import local_paths
from tests.support.remodel_ledger import GOLDEN_LEDGER, rendered_ledger
from tests.support.seat_tasks import REPO

CALIBRATED = IDENTITY.model_copy(update={"calibrated": True, "calibration_ref": "fictional"})
"""IDENTITY as T138 would leave it, for the cases that test everything else Start needs."""

IDENTITY_NOT_CALIBRATED = (
    "the IDENTITY tolerance profile is not calibrated: T138 freezes it against PROBE-8's "
    "numbers (decision 170A)"
)

Row = tuple[str, bool, str, dict[str, str]]


def start_rows(**changed: tuple[str, dict[str, str]]) -> list[Row]:
    """The five probes Start needs, each verified with a reason, but for `changed` (`PROBE_12=`)."""
    rows = {probe: ("verified", {"reason": f"{probe} answered."}) for probe in START_PROBES}
    rows.update({name.replace("_", "-"): row for name, row in changed.items()})
    return [(probe, True, verdict, raw) for probe, (verdict, raw) in rows.items()]


# --- the golden ledger: the renderer and the reader agree ------------------------------------


def test_the_golden_ledger_reads_as_render_wrote_it() -> None:
    ledger = load_ledger(GOLDEN_LEDGER)

    assert ledger.sw_version == "32.5.0"
    assert ledger.generated_at == "2026-10-31T12:00:00.0000000+00:00"
    assert len(ledger.requested) == 15
    assert (ledger.requested[0], ledger.requested[-1]) == ("PROBE-1", "PROBE-21")
    assert [row.probe_id for row in ledger.probes] == ledger.requested[:-1]
    assert ledger.unfinished == ["PROBE-21"]
    assert ledger.row("PROBE-21") is None
    first = ledger.row("PROBE-1")
    assert first is not None
    assert first.question == (
        'Does ISldWorks.CommandInProgress = true suppress the "Cannot reorder" message box?'
    )
    assert first.interop_members == ["ReorderFeature", "set_CommandInProgress"]
    second = ledger.row("PROBE-2")
    assert second is not None
    assert (second.blocking, second.verdict, second.duration_ms) == (True, "verified", 41)
    assert second.raw_result["equation_text"] == '"w" = 120'
    assert second.sw_version == "32.5.0"
    copy = ledger.row("PROBE-13")
    assert copy is not None
    assert (copy.blocking, copy.verdict) == (False, "refuted")
    assert copy.raw_result["file_copy_error"] == "IOException 0x80070020"


def test_a_byte_order_mark_and_crlf_line_ends_read_the_same(tmp_path: Path) -> None:
    """`File.WriteAllText(..., Encoding.UTF8)` writes a byte-order mark, and a checkout may turn
    the line ends to CRLF."""
    copy = tmp_path / GOLDEN_LEDGER.name
    text = GOLDEN_LEDGER.read_text(encoding="utf-8").replace("\r\n", "\n")
    copy.write_bytes(b"\xef\xbb\xbf" + text.replace("\n", "\r\n").encode("utf-8"))

    assert load_ledger(copy) == load_ledger(GOLDEN_LEDGER)


def test_the_frozen_version_is_the_interop_manifests() -> None:
    """The interop the build is frozen against (`remodel-interop-manifest.json`), and the spelling
    `ISldWorks.RevisionNumber` gives the same release, which is what a seat's ledger records."""
    manifest = json.loads(
        (
            REPO / "extractor" / "SwReview.Extractor.Tests" / "Fixtures" / "InteropSurface"
            / "remodel-interop-manifest.json"
        ).read_text(encoding="utf-8")
    )

    assert FROZEN_INTEROP_VERSION == manifest["assembly_version"] == "32.5.0.48"
    assert SW_VERSIONS == (FROZEN_INTEROP_VERSION, "32.5.0")


# --- what it prints ---------------------------------------------------------------------------


def test_the_command_prints_each_probes_verdict_and_why_and_the_start_switch() -> None:
    result = CliRunner().invoke(app, ["remodel", "ledger", str(GOLDEN_LEDGER)])

    assert result.exit_code == 0, result.output
    lines = result.stdout.splitlines()
    assert lines[0] == (
        "remodel-32.5.0.yaml: SOLIDWORKS 32.5.0, written 2026-10-31T12:00:00.0000000+00:00; "
        "14 of 15 requested probes finished"
    )
    assert lines[1] == (
        "PROBE-1 (blocking): verified - the illegal reorder blocked with CommandInProgress clear "
        "and returned once it was set: the flag suppresses the message box."
    )
    assert "PROBE-13: refuted - File.Copy failed against the open .SLDPRT, but the " \
        "FileShare.ReadWrite stream fallback succeeded." in lines
    assert "PROBE-20: unresolved - threw COMException 0x80004005" in lines
    assert "PROBE-21: not finished - the run stopped before this probe ended" in lines
    assert "PROBE-11 type names rms_types.yaml does not know: FictProbeType" in lines
    assert lines[-1] == f"{START_SWITCH}: not ready - {IDENTITY_NOT_CALIBRATED}"
    assert str(GOLDEN_LEDGER.parent) not in result.stdout


def test_the_json_carries_the_same_facts() -> None:
    result = CliRunner().invoke(app, ["remodel", "ledger", str(GOLDEN_LEDGER), "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["ledger"] == "remodel-32.5.0.yaml"
    assert (payload["sw_version"], payload["generated_at"]) == (
        "32.5.0", "2026-10-31T12:00:00.0000000+00:00"
    )
    assert payload["requested"][-1] == "PROBE-21"
    assert payload["unfinished"] == ["PROBE-21"]
    assert payload["unknown_types"] == ["FictProbeType"]
    by_id = {row["probe_id"]: row for row in payload["probes"]}
    assert by_id["PROBE-20"] == {
        "probe_id": "PROBE-20", "blocking": False, "verdict": "unresolved", "reason": None,
        "error": "COMException 0x80004005",
    }
    assert by_id["PROBE-12"]["verdict"] == "verified" and by_id["PROBE-12"]["error"] is None
    assert payload["switches"] == [
        {"switch": START_SWITCH, "ready": False, "reasons": [IDENTITY_NOT_CALIBRATED]}
    ]


# --- the Start switch -------------------------------------------------------------------------


def test_the_golden_ledger_holds_start_back_only_for_the_uncalibrated_profile() -> None:
    ledger = load_ledger(GOLDEN_LEDGER)

    held = start_readiness(ledger)
    ready = start_readiness(ledger, CALIBRATED)

    assert (held.switch, held.ready, held.reasons) == (
        START_SWITCH, False, (IDENTITY_NOT_CALIBRATED,)
    )
    assert (ready.ready, ready.reasons) == (True, ())


@pytest.mark.parametrize(
    ("rows", "requested", "reason"),
    [
        (start_rows()[1:], None, "PROBE-1 was not run"),
        (start_rows()[1:], list(START_PROBES), "PROBE-1 did not finish"),
        (start_rows(PROBE_3=("refuted", {"reason": "it moved"})), None, "PROBE-3 is refuted"),
        (start_rows(PROBE_4=("unresolved", {"reason": "?"})), None, "PROBE-4 is unresolved"),
        (
            start_rows(PROBE_12=("unresolved", {"error": "COMException 0x80004005"})),
            None,
            "PROBE-12 threw COMException 0x80004005",
        ),
        (
            start_rows(
                PROBE_12=("verified", {"reason": "read back", "error": "IOException 0x80131620"})
            ),
            None,
            "PROBE-12 threw IOException 0x80131620",
        ),
        (
            start_rows(PROBE_12=("verified", {"found_after_reopen": "True"})),
            None,
            "PROBE-12 gives no reason (decision 148A: a verdict with a reason and no error)",
        ),
        (
            start_rows(PROBE_2=("unresolved", {"error": "Could not open the part."})),
            None,
            "PROBE-2 threw (its message is not shown)",
        ),
    ],
    ids=["not-run", "not-finished", "refuted", "unresolved", "error", "error-beside-verified",
         "no-reason-148A", "message-withheld"],
)
def test_start_names_each_probe_that_holds_it_back(
    rows: list[Row], requested: list[str] | None, reason: str
) -> None:
    ledger = parse_ledger(rendered_ledger(rows, requested))

    readiness = start_readiness(ledger, CALIBRATED)

    assert (readiness.ready, readiness.reasons) == (False, (reason,))


def test_start_is_ready_with_the_five_verified_and_identity_calibrated() -> None:
    ledger = parse_ledger(rendered_ledger(start_rows()))

    assert start_readiness(ledger, CALIBRATED).ready
    assert start_readiness(ledger).reasons == (IDENTITY_NOT_CALIBRATED,)


# --- what it refuses --------------------------------------------------------------------------


@pytest.mark.parametrize("version", ["2024 SP5", "32.4.0", "32.5.1", "32.5.0.49", "33.0.0", ""])
def test_a_ledger_for_another_solidworks_version_is_refused(version: str) -> None:
    """*Changed on purpose by 004 T344 (review finding F5)*: the refusal repeats no value from
    the file, as every other refusal does, so it does not name the version either."""
    text = rendered_ledger(start_rows(), sw_version=version)

    with pytest.raises(LedgerRefused, match="only the frozen interop's version") as refused:
        parse_ledger(text)

    assert not version or version not in str(refused.value)


def test_a_row_from_another_version_than_its_ledgers_is_refused() -> None:
    text = rendered_ledger(start_rows()).replace(
        '    sw_version: "32.5.0.48"', '    sw_version: "32.5.0"', 1
    )

    with pytest.raises(LedgerRefused, match="PROBE-1's row"):
        parse_ledger(text)


PATHS = {
    "drive": "C:\\Users\\FICT-engineer\\Designs\\bracket.SLDPRT",
    "drive, forward": "E:/FICT-vault/bracket.SLDPRT",
    "unc": "\\\\fict-host\\share\\bracket.SLDPRT",
    "posix": "/home/fict-engineer/bracket.SLDPRT",
}
"""One fictional path of each kind the reader refuses, as the decoded string."""

NOT_PATHS = (
    "n/a (blocked)",
    "CommentsFolder / SelectionSetFolder / InkMarkupFolder",
    "reviewer/src/swreview/checks/rms_types.yaml",
    "1/2",
    "https://example.invalid/a",
    "IOException 0x80070020",
)
"""Strings real ledgers carry, or could, that name no path."""


def yaml_quoted(text: str) -> str:
    """`text` as the C# renderer quotes it, inside the double quotes."""
    return text.replace("\\", "\\\\").replace('"', '\\"')


@pytest.mark.parametrize("kind", sorted(PATHS))
@pytest.mark.parametrize("where", ["raw_result value", "raw_result key", "question"])
def test_a_ledger_naming_a_path_is_refused_and_the_refusal_repeats_it_nowhere(
    kind: str, where: str
) -> None:
    path = yaml_quoted(PATHS[kind])
    text = rendered_ledger(start_rows())
    if where == "raw_result value":
        text = text.replace('"reason": "PROBE-3 answered."', f'"reason": "copied {path}"')
    elif where == "raw_result key":
        text = text.replace('"reason": "PROBE-3 answered."', f'"type[{path}]": "Cut"')
    else:
        text = text.replace('question: "a question"', f'question: "{path}"', 1)

    with pytest.raises(LedgerRefused) as refused:
        parse_ledger(text)

    message = str(refused.value)
    assert "decision 171A" in message
    for piece in (PATHS[kind], path, "FICT", "fict", "bracket"):
        assert piece not in message, piece


@pytest.mark.parametrize("text", NOT_PATHS)
def test_a_string_that_names_no_path_is_read(text: str) -> None:
    ledger = parse_ledger(
        rendered_ledger(start_rows(PROBE_1=("verified", {"reason": yaml_quoted(text)})))
    )

    row = ledger.row("PROBE-1")
    assert row is not None and row.raw_result["reason"] == text


@pytest.mark.parametrize("text", [*PATHS.values(), *NOT_PATHS])
def test_the_path_rule_agrees_with_the_committable_scanner(tmp_path: Path, text: str) -> None:
    """The reader's rule (a product module cannot import the test-side scanner) flags exactly
    what `tests/support/local_paths.py`, the committable-path scanner, flags outside its
    fictional roots."""
    sample = tmp_path / "sample.txt"
    sample.write_text(text, encoding="utf-8")

    assert (path_kind(text) is not None) == bool(local_paths.scan_file(sample))


@pytest.mark.parametrize(
    ("text", "kind"),
    [(PATHS["drive"], "drive"), (PATHS["drive, forward"], "drive"), (PATHS["unc"], "UNC"),
     (PATHS["posix"], "POSIX"), ("glued" + PATHS["drive"], "drive")],
)
def test_path_kind_names_the_kind(text: str, kind: str) -> None:
    assert path_kind(text) == kind


MALFORMED = {
    "not-yaml": "sw_version: [\n",
    "not-a-mapping": "- a\n- b\n",
    "a-field-missing": rendered_ledger(start_rows()).replace("    verdict: verified\n", "", 1),
    "an-unknown-field": rendered_ledger(start_rows()) + 'notes: "x"\n',
    "an-unknown-verdict": rendered_ledger(start_rows()).replace(
        "verdict: verified", "verdict: maybe-later", 1
    ),
    "a-quoted-flag": rendered_ledger(start_rows()).replace("blocking: true", 'blocking: "yes"', 1),
    "a-row-twice": rendered_ledger(start_rows() + start_rows()[:1], list(START_PROBES)),
    "a-row-not-requested": rendered_ledger(start_rows(), list(START_PROBES[1:])),
    "requested-twice": rendered_ledger(start_rows(), [*START_PROBES, "PROBE-1"]),
    "not-a-probe-id": rendered_ledger(start_rows()).replace(
        '"PROBE-2"', '"maybe-later"'
    ),
    "a-reading-not-a-string": rendered_ledger(start_rows()).replace(
        '"reason": "PROBE-3 answered."', '"FICT-key": 5', 1
    ),
}


@pytest.mark.parametrize("kind", sorted(MALFORMED))
def test_a_ledger_not_in_renders_shape_is_refused_without_repeating_its_values(kind: str) -> None:
    with pytest.raises(LedgerRefused, match="RemodelProbeLedger.Render") as refused:
        parse_ledger(MALFORMED[kind])

    assert "maybe-later" not in str(refused.value)
    assert '"yes"' not in str(refused.value)
    assert "FICT" not in str(refused.value)


# --- what `yaml.safe_load` would settle silently (004 T344, review findings F3 and F7) ---------

TWICE = {
    "a-verdict": rendered_ledger(start_rows(PROBE_3=("refuted", {"reason": "it moved"}))).replace(
        "    verdict: refuted\n", "    verdict: refuted\n    verdict: verified\n", 1
    ),
    "the-version": rendered_ledger(start_rows()).replace(
        'sw_version: "32.5.0.48"\n', 'sw_version: "32.5.0.48"\nsw_version: "32.5.0.48"\n', 1
    ),
    "a-reading": rendered_ledger(start_rows()).replace(
        '"reason": "PROBE-3 answered."',
        '"reason": "PROBE-3 answered."\n      "reason": "PROBE-3 answered."',
    ),
    "a-verdict-merged": rendered_ledger(start_rows()).replace(
        "    verdict: verified\n", "    <<: {verdict: refuted}\n    verdict: verified\n", 1
    ),
}
"""A key twice in one mapping, which `yaml.safe_load` settles by keeping the last, so a row could
say `refuted` and then `verified` and be judged by the second; and a merge key doing the same."""


@pytest.mark.parametrize("kind", sorted(TWICE))
def test_a_key_twice_in_one_mapping_is_refused(kind: str) -> None:
    with pytest.raises(LedgerRefused, match="RemodelProbeLedger.Render") as refused:
        parse_ledger(TWICE[kind])

    for value in ("answered", "moved", "refuted", "32.5.0.48"):
        assert value not in str(refused.value), value


def alias_bomb(depth: int) -> str:
    """A list whose strings double at each level through aliases: a few lines that a walk of the
    loaded document would visit 2 ** depth times."""
    lines = ['laughs0: &l0 ["x", "x"]']
    lines += [f"laughs{n}: &l{n} [*l{n - 1}, *l{n - 1}]" for n in range(1, depth)]
    return "\n".join(lines) + "\n"


ALIASED = {
    "an-anchor-and-its-alias": rendered_ledger(start_rows())
    .replace('question: "a question"', 'question: &q "a question"', 1)
    .replace('question: "a question"', "question: *q", 1),
    "an-anchor-alone": rendered_ledger(start_rows()).replace(
        'method: "a method"', 'method: &m "a method"', 1
    ),
    "an-alias-bomb": rendered_ledger(start_rows()) + alias_bomb(16),
}
"""What `Render` never writes: an anchor or an alias. The path walk follows each alias again, so a
few lines of them would take exponential time before the shape is checked."""


@pytest.mark.parametrize("kind", sorted(ALIASED))
def test_an_anchor_or_alias_is_refused_before_anything_is_walked(kind: str) -> None:
    with pytest.raises(LedgerRefused, match="Render writes: it uses a YAML anchor or alias"):
        parse_ledger(ALIASED[kind])


@pytest.mark.parametrize("kind", ["missing", "a-folder"])
def test_a_ledger_that_cannot_be_read_is_refused_naming_its_file_and_no_folder(
    tmp_path: Path, kind: str
) -> None:
    """The reader prints the file's name, never its folder, which may name the user (review
    finding F4 of the second reviewer: the operating system's message repeats the whole path)."""
    ledger = tmp_path / "FICT-engineer" / "FICT-design" / "remodel-32.5.0.yaml"
    if kind == "a-folder":
        ledger.mkdir(parents=True)

    result = CliRunner().invoke(app, ["remodel", "ledger", str(ledger)])

    assert result.exit_code == 1
    assert result.stdout == ""
    [line] = result.stderr.splitlines()
    assert line.startswith("error: LedgerRefused: could not read remodel-32.5.0.yaml: "), line
    assert "FICT" not in line and tmp_path.name not in line
    with pytest.raises(LedgerRefused, match="could not read remodel-32.5.0.yaml"):
        load_ledger(ledger)


def test_the_command_refuses_in_one_line_and_exits_1(tmp_path: Path) -> None:
    ledger = tmp_path / "remodel-32.5.0.48.yaml"
    ledger.write_text(
        rendered_ledger(start_rows()).replace(
            '"reason": "PROBE-3 answered."', f'"reason": "{yaml_quoted(PATHS["drive"])}"'
        ),
        encoding="utf-8",
    )

    result = CliRunner().invoke(app, ["remodel", "ledger", str(ledger)])

    assert result.exit_code == 1
    assert result.stdout == ""
    [line] = result.stderr.splitlines()
    assert line.startswith("error: ") and "decision 171A" in line
    assert "FICT-engineer" not in line


# --- PROBE-11's census against the RMS table --------------------------------------------------


def test_the_type_names_the_table_does_not_know_are_listed_once_in_order() -> None:
    census = {
        "type[Sketch1]": "ProfileFeature",
        "type[Folder1]": "FtrFolder",
        "type[History]": "HistoryFolder",
        "type[Boss1]": "ICE",
        "type[Stock1]": "MirrorStock",
        "type[A]": "FictA",
        "type[B]": "(unreadable)",
        "type[C]": "FictB",
        "type[D]": "FictA",
        "reason": "a reason",
    }
    ledger = parse_ledger(rendered_ledger([("PROBE-11", False, "verified", census)]))

    assert unknown_types(ledger) == ["FictA", "FictB"]
    assert unknown_types(parse_ledger(rendered_ledger(start_rows()))) == []
    assert unknown_types(load_ledger(GOLDEN_LEDGER)) == ["FictProbeType"]
