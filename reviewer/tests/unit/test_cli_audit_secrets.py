"""Unit tests for `swreview audit-secrets` (T029).

The command is the check the quickstart runs after a review: point it at the run folder
and the log folder and it says whether a configured secret reached a file. Three
properties are what make it worth running, and each is asserted here:

1. **It finds a key it was told about.** Any provider key variable that is set in the
   invoking environment, plus the bridge secret when `--bridge-secret-env` names the
   variable holding it, is searched for verbatim; a hit exits 1 and names the file.
2. **It is not blind when the shell holds nothing.** On the workstation the key is
   DPAPI-protected under `%APPDATA%` and reaches only the backend child's environment,
   so an audit run from a separate shell has no key to search for. The provider-shaped
   detectors (`sk-...`, `AIza...`) are what carry the check there, and they are on by
   default.
3. **A vacuous run is loud.** With no key variable set, no bridge secret and
   `--no-detectors`, the command has nothing to detect with. It exits non-zero and says
   so rather than printing a green "none" that means only "I did not look".

Nothing the command prints may contain a secret: the tests below assert the value is
absent from stdout and stderr for every kind of hit, because an audit that echoes what it
found copies the leak into the terminal scrollback and the CI log.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from swreview import cli

runner = CliRunner()

# --- the secrets these tests plant -----------------------------------------------

ENV_KEY = "corp-gateway-2f7c1a9e-not-provider-shaped"
"""A configured key that no detector would recognise, so a hit proves the *environment*
half of the command rather than the pattern half."""

OPENAI_SHAPED = "sk-proj-0aB1cD2eF3gH4iJ5kL6mN7oP8qR9sT0uV1wX2yZ3aB4cD5eF"
# Built from fragments so the source never holds a contiguous provider-shaped token
# (GitHub secret scanning would otherwise alert on a format-valid fake); the joined value
# is still AIza + 35 key characters, which is what the detector needs.
GOOGLE_SHAPED = "AIza" + "SyNOTAREALKEY" + "0123456789abcdefghijkl"
BRIDGE_SECRET = "bridge-8c41d0e6b2f74a1d9e3c5a7b0f2d4e68"
BRIDGE_ENV_VAR = "SWREVIEW_BRIDGE_SECRET"

KEY_ENV_VARS = ("OPENAI_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY")
"""Every variable the command reads a provider key from. Kept here as a literal rather
than imported, so a rename in `cli.py` has to be made deliberately in both places."""


@pytest.fixture(autouse=True)
def no_secrets_in_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Run every case against an empty environment, not the developer's own shell."""
    for name in (*KEY_ENV_VARS, BRIDGE_ENV_VAR):
        monkeypatch.delenv(name, raising=False)


def invoke(*args: str) -> Any:
    return runner.invoke(cli.app, ["audit-secrets", *args])


def plant(directory: Path, name: str, text: str) -> Path:
    """Write `text` into `name` under `directory`, creating parents."""
    target = directory / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return target


@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    """A run folder shaped like the real one: some files, one of them nested."""
    directory = tmp_path / "run"
    plant(directory, "session.json", '{"provider": "openai", "model": "gpt-5.6"}\n')
    plant(directory, "events.jsonl", '{"type": "turn.started"}\n')
    plant(directory, "logs/backend.log", "started on 127.0.0.1\n")
    return directory


# --- the environment half --------------------------------------------------------


def test_configured_key_in_a_file_exits_1_and_names_the_file(
    run_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", ENV_KEY)
    plant(run_dir, "logs/backend.log", f"Authorization: Bearer {ENV_KEY}\n")

    result = invoke(str(run_dir))

    assert result.exit_code == 1
    assert "backend.log" in result.stdout
    assert "OPENAI_API_KEY" in result.stdout


def test_a_clean_directory_exits_0_and_reports_none(
    run_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", ENV_KEY)

    result = invoke(str(run_dir))

    assert result.exit_code == 0, result.stdout + result.stderr
    assert "none" in result.stdout


def test_every_key_variable_is_searched_not_only_the_winning_one(
    run_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`GOOGLE_API_KEY` wins over `GEMINI_API_KEY` for a *run*; an audit wants both."""
    monkeypatch.setenv("GOOGLE_API_KEY", "google-" + ENV_KEY)
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-" + ENV_KEY)
    plant(run_dir, "events.jsonl", "gemini-" + ENV_KEY + "\n")

    result = invoke(str(run_dir), "--no-detectors")

    assert result.exit_code == 1
    assert "GEMINI_API_KEY" in result.stdout


def test_a_variable_that_is_set_but_empty_is_not_a_key(
    run_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The common Windows case. An empty key must not match every file, nor count as a
    source that keeps a `--no-detectors` run from being called vacuous."""
    monkeypatch.setenv("OPENAI_API_KEY", "   ")

    result = invoke(str(run_dir), "--no-detectors")

    assert result.exit_code != 0
    assert "nothing to detect with" in result.stderr


def test_every_directory_given_is_scanned(
    tmp_path: Path, run_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", ENV_KEY)
    logs = tmp_path / "logs"
    plant(logs, "addin.log", f"key={ENV_KEY}\n")

    result = invoke(str(run_dir), str(logs))

    assert result.exit_code == 1
    assert "addin.log" in result.stdout


# --- the detector half -----------------------------------------------------------


def test_openai_shaped_key_is_caught_when_the_shell_holds_none(run_dir: Path) -> None:
    plant(run_dir, "logs/backend.log", f'  "api_key": "{OPENAI_SHAPED}"\n')

    result = invoke(str(run_dir))

    assert result.exit_code == 1
    assert "backend.log" in result.stdout


def test_google_shaped_key_is_caught_when_the_shell_holds_none(run_dir: Path) -> None:
    plant(run_dir, "events.jsonl", f"GET ...?key={GOOGLE_SHAPED}\n")

    result = invoke(str(run_dir))

    assert result.exit_code == 1
    assert "events.jsonl" in result.stdout


def test_detectors_do_not_fire_on_short_lookalikes(run_dir: Path) -> None:
    plant(run_dir, "notes.md", "sk-abc and AIzaShort and sk- alone\n")

    result = invoke(str(run_dir))

    assert result.exit_code == 0, result.stdout + result.stderr


def test_detectors_can_be_turned_off_when_a_key_is_configured(
    run_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`--no-detectors` narrows the audit to the exact configured values, which is what a
    run with a key-shaped model id or a sample in the docs wants."""
    monkeypatch.setenv("OPENAI_API_KEY", ENV_KEY)
    plant(run_dir, "notes.md", f"example key: {OPENAI_SHAPED}\n")

    result = invoke(str(run_dir), "--no-detectors")

    assert result.exit_code == 0, result.stdout + result.stderr


# --- the bridge secret -----------------------------------------------------------


def test_bridge_secret_is_scanned_when_its_variable_is_named(
    run_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(BRIDGE_ENV_VAR, BRIDGE_SECRET)
    plant(run_dir, "chat-log.jsonl", f'{{"secret": "{BRIDGE_SECRET}"}}\n')

    result = invoke(str(run_dir), "--bridge-secret-env", BRIDGE_ENV_VAR, "--no-detectors")

    assert result.exit_code == 1
    assert "chat-log.jsonl" in result.stdout
    assert BRIDGE_ENV_VAR in result.stdout


def test_bridge_secret_is_not_searched_for_unless_asked(
    run_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(BRIDGE_ENV_VAR, BRIDGE_SECRET)
    plant(run_dir, "chat-log.jsonl", f'{{"secret": "{BRIDGE_SECRET}"}}\n')

    result = invoke(str(run_dir), "--no-detectors", "--bridge-secret-env", "OTHER_VAR")

    assert result.exit_code != 0
    assert "OTHER_VAR" in result.stderr


def test_named_bridge_variable_that_is_unset_is_not_a_source(
    run_dir: Path,
) -> None:
    """Naming a variable that holds nothing must not make a vacuous run look armed."""
    result = invoke(str(run_dir), "--bridge-secret-env", BRIDGE_ENV_VAR, "--no-detectors")

    assert result.exit_code != 0
    assert "nothing to detect with" in result.stderr


# --- the vacuous run -------------------------------------------------------------


def test_no_key_source_and_no_detectors_exits_non_zero(run_dir: Path) -> None:
    result = invoke(str(run_dir), "--no-detectors")

    assert result.exit_code != 0
    assert "nothing to detect with" in result.stderr
    assert "none" not in result.stdout


def test_detectors_alone_are_enough_to_arm_the_command(run_dir: Path) -> None:
    """No key anywhere, detectors on: the audit is real, so a clean tree is a real 0."""
    result = invoke(str(run_dir))

    assert result.exit_code == 0, result.stdout + result.stderr
    assert "none" in result.stdout


# --- what the command is allowed to print ----------------------------------------


def test_a_configured_key_never_appears_in_the_output(
    run_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", ENV_KEY)
    plant(run_dir, "logs/backend.log", f"Authorization: Bearer {ENV_KEY}\n")

    result = invoke(str(run_dir))

    assert result.exit_code == 1
    assert ENV_KEY not in result.stdout
    assert ENV_KEY not in result.stderr


def test_a_detected_key_never_appears_in_the_output(run_dir: Path) -> None:
    plant(run_dir, "logs/backend.log", f"key={OPENAI_SHAPED}\n")

    result = invoke(str(run_dir))

    assert result.exit_code == 1
    assert OPENAI_SHAPED not in result.stdout
    assert OPENAI_SHAPED not in result.stderr


def test_json_output_is_the_only_thing_on_stdout(
    run_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", ENV_KEY)
    plant(run_dir, "logs/backend.log", f"Bearer {ENV_KEY}\n")

    result = invoke(str(run_dir), "--json")

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["files_scanned"] == 3
    assert "env:OPENAI_API_KEY" in payload["sources"]
    leak = payload["leaks"][0]
    assert leak["file"].endswith("backend.log")
    assert leak["line"] == 1
    assert leak["source"] == "env:OPENAI_API_KEY"
    assert ENV_KEY not in result.stdout


def test_json_output_of_a_clean_scan(run_dir: Path) -> None:
    result = invoke(str(run_dir), "--json")

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["leaks"] == []
    assert payload["unreadable"] == []
    assert sorted(payload["sources"]) == ["shape:google-key", "shape:openai-key"]


def test_each_hit_is_reported_once_per_line_with_its_line_number(run_dir: Path) -> None:
    plant(run_dir, "events.jsonl", f"one {OPENAI_SHAPED}\nclean\nthree {GOOGLE_SHAPED}\n")

    result = invoke(str(run_dir), "--json")

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert [(leak["line"], leak["source"]) for leak in payload["leaks"]] == [
        (1, "shape:openai-key"),
        (3, "shape:google-key"),
    ]


# --- the files it walks ----------------------------------------------------------


def test_a_single_file_may_be_given_instead_of_a_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", ENV_KEY)
    target = plant(tmp_path, "one.log", f"{ENV_KEY}\n")

    result = invoke(str(target))

    assert result.exit_code == 1
    assert "one.log" in result.stdout


def test_undecodable_bytes_do_not_stop_the_scan(
    run_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", ENV_KEY)
    (run_dir / "thumb.png").write_bytes(b"\x89PNG\r\n\x1a\n\xff\xfe\xfd")
    plant(run_dir, "events.jsonl", f"{ENV_KEY}\n")

    result = invoke(str(run_dir))

    assert result.exit_code == 1
    assert "events.jsonl" in result.stdout


def test_an_unreadable_file_is_reported_rather_than_silently_skipped(
    run_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A file the audit could not read is coverage it does not have; reporting "none"
    over it would be the false green the whole command exists to prevent."""
    real_open = Path.open

    def refuse(self: Path, *args: Any, **kwargs: Any) -> Any:
        if self.name == "events.jsonl":
            raise PermissionError("locked by another process")
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", refuse)

    result = invoke(str(run_dir), "--json")

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["leaks"] == []
    assert [Path(name).name for name in payload["unreadable"]] == ["events.jsonl"]


def test_an_empty_directory_is_scanned_and_reports_none(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()

    result = invoke(str(empty), "--json")

    assert result.exit_code == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["files_scanned"] == 0


def test_a_missing_directory_is_an_error(tmp_path: Path) -> None:
    result = invoke(str(tmp_path / "absent"))

    assert result.exit_code == 1
    assert "absent" in result.stderr


def test_no_directory_argument_is_a_usage_error() -> None:
    assert invoke().exit_code == 2
