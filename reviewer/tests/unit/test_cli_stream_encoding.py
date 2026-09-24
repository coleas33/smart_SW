"""The command line prints what it has, whatever encoding its streams were opened in (011 T098).

A tool that captures `swreview`'s output on Windows - the seat assistant running `swreview check
standards`, a script piping `validate` - hands Python a cp1252 pipe, and a line carrying a
character cp1252 has no byte for (the diameter sign U+2300 in a finding title or a callout)
raised `UnicodeEncodeError` and exited 1 before the rest was printed. 011 T053 fixed `drawing
brief` alone, by writing its bytes; the entry point now reopens stdout and stderr as UTF-8 when
they are anything else (`cli.utf8_streams`, run by the root callback before any command).
"""

from __future__ import annotations

import io
import os
import subprocess
import sys
from pathlib import Path

import pytest

from swreview import cli
from swreview.ir.loader import save_package
from swreview.ir.models import Gap
from tests.support.packages import build_package

REVIEWER = Path(__file__).resolve().parents[2]
DIAMETER = "⌀"


def run_cli(*args: str, encoding: str) -> subprocess.CompletedProcess[bytes]:
    """`python -m swreview.cli` with both streams piped in `encoding`, as a capturing tool does."""
    environment = {**os.environ, "PYTHONIOENCODING": encoding}
    environment.pop("PYTHONUTF8", None)
    return subprocess.run(
        [sys.executable, "-m", "swreview.cli", *args],
        cwd=REVIEWER,
        env=environment,
        capture_output=True,
        timeout=120,
        check=False,
    )


@pytest.fixture
def package_with_a_diameter_sign(tmp_path: Path) -> Path:
    folder = tmp_path / "package"
    gap = Gap(
        kind="unsupported",
        entity_kind="hole",
        entity_id="hol:0001",
        reason=f"the callout reads {DIAMETER}6 H7 and was not parsed",
        error=None,
    )
    save_package(build_package(gaps=[gap]), folder)
    return folder


def test_a_line_cp1252_cannot_spell_is_printed_through_a_cp1252_pipe(
    package_with_a_diameter_sign: Path,
) -> None:
    completed = run_cli("validate", str(package_with_a_diameter_sign), encoding="cp1252")

    assert completed.returncode == 0, completed.stderr.decode("utf-8", "replace")
    assert f"{DIAMETER}6 H7".encode() in completed.stdout
    assert b"UnicodeEncodeError" not in completed.stderr


def test_an_error_naming_such_a_character_reaches_a_cp1252_stderr(tmp_path: Path) -> None:
    missing = tmp_path / f"no {DIAMETER} package"

    completed = run_cli("validate", str(missing), encoding="cp1252")

    assert completed.returncode == 1
    assert completed.stderr.startswith(b"error: ")
    assert DIAMETER.encode() in completed.stderr
    assert b"UnicodeEncodeError" not in completed.stderr


def test_a_utf8_stream_is_left_as_it_is(package_with_a_diameter_sign: Path) -> None:
    completed = run_cli("validate", str(package_with_a_diameter_sign), encoding="utf-8")

    assert completed.returncode == 0
    assert f"{DIAMETER}6 H7".encode() in completed.stdout


def test_utf8_streams_reopens_only_a_text_stream_in_another_encoding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    narrow = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
    wide = io.TextIOWrapper(io.BytesIO(), encoding="utf-8", errors="strict")
    monkeypatch.setattr(sys, "stdout", narrow)
    monkeypatch.setattr(sys, "stderr", wide)

    cli.utf8_streams()

    assert sys.stdout is narrow and narrow.encoding == "utf-8"
    assert sys.stderr is wide and wide.encoding == "utf-8" and wide.errors == "strict"
    print(DIAMETER, file=narrow)
    narrow.flush()
    assert narrow.buffer.getvalue().decode("utf-8").startswith(DIAMETER)


def test_utf8_streams_leaves_a_stream_it_cannot_reopen(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = io.StringIO()
    monkeypatch.setattr(sys, "stdout", captured)

    cli.utf8_streams()

    assert sys.stdout is captured
