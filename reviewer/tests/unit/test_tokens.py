"""Unit tests for the one tokenizer (008 T001, `contracts/tokenizer.md`).

Every token count feature 008 prints or records comes from `swreview.tokens.count_tokens`,
over one named encoding, loaded from a per-user cache with **no network**. The vocabulary
file is not in the repository (the repository is public and the file carries no stated
redistribution terms), so these tests pin both halves of that:

- with the file in the cache, the encoding loads with every route to the network patched to
  raise, counts what the adapters send, and leaves `TIKTOKEN_CACHE_DIR` as it found it;
- with the file missing, truncated or altered, loading refuses in one sentence that names the
  folder, the expected hash and the fetch command - and still touches no network.

Tests that need exact counts take the shared `vocabulary` fixture (`tests/conftest.py`),
which skips with the fetch command in the reason when the file is absent, or fails when
`SWREVIEW_REQUIRE_TOKENIZER=1`. The refusal tests use a temporary folder and need no file.
"""

from __future__ import annotations

import hashlib
import os
import socket
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import requests
from typer.testing import CliRunner

from swreview import cli, tokens

SRC_ROOT = Path(tokens.__file__).resolve().parent
VOCABULARY_BYTES = 3_613_922
"""The size `contracts/tokenizer.md` section 2 records for the vocabulary file."""

runner = CliRunner()


class NetworkTouched(AssertionError):
    """Raised by the patched network; a test that sees it has reached for the internet."""


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Patch both routes to the network to raise, and record every attempt."""
    attempts: list[str] = []

    def refuse_get(*args: Any, **kwargs: Any) -> Any:
        attempts.append(f"requests.get{args!r}")
        raise NetworkTouched("requests.get was called")

    def refuse_connect(self: socket.socket, *args: Any, **kwargs: Any) -> Any:
        attempts.append(f"socket.connect{args!r}")
        raise NetworkTouched("socket.connect was called")

    monkeypatch.setattr(requests, "get", refuse_get)
    monkeypatch.setattr(socket.socket, "connect", refuse_connect)
    return attempts


@pytest.fixture
def cache_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An empty per-user cache, named through `SWREVIEW_TOKENIZER_DIR`."""
    folder = tmp_path / "tokenizer"
    folder.mkdir()
    monkeypatch.setenv(tokens.TOKENIZER_DIR_ENV, str(folder))
    return folder


def good_bytes(vocabulary: Path) -> bytes:
    return (vocabulary / tokens.VOCABULARY_FILE_NAME).read_bytes()


# --- the one encoding --------------------------------------------------------------


def test_the_encoding_is_named_o200k_base() -> None:
    assert tokens.TOKENIZER_NAME == "o200k_base"


def test_the_vocabulary_file_name_is_tiktokens_cache_key() -> None:
    url = "https://openaipublic.blob.core.windows.net/encodings/o200k_base.tiktoken"

    assert tokens.VOCABULARY_FILE_NAME == hashlib.sha1(url.encode()).hexdigest()


def test_the_expected_hash_is_the_one_tiktoken_carries() -> None:
    import inspect

    import tiktoken_ext.openai_public as public

    assert tokens.ENCODING_SHA256 in inspect.getsource(public.o200k_base)


def test_hello_world_is_two_tokens_with_the_network_off(
    vocabulary: Path, no_network: list[str]
) -> None:
    assert tokens.count_tokens("hello world") == 2
    assert tokens.encoding().encode("hello world") == [24912, 2375]
    assert no_network == []


def test_a_fresh_process_loads_the_encoding_with_the_network_off(vocabulary: Path) -> None:
    """In-process, tiktoken may already hold the encoding; a new process proves the load."""
    program = (
        "import socket, requests\n"
        "def refuse(*a, **k):\n"
        "    raise SystemExit('network touched')\n"
        "socket.socket.connect = refuse\n"
        "requests.get = refuse\n"
        "from swreview import tokens\n"
        "print(tokens.count_tokens('hello world'), tokens.encoding().encode('hello world'))\n"
    )
    environment = {**os.environ, tokens.TOKENIZER_DIR_ENV: str(vocabulary)}

    completed = subprocess.run(
        [sys.executable, "-c", program],
        capture_output=True,
        text=True,
        env=environment,
        timeout=120,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "2 [24912, 2375]"


def test_the_empty_string_is_no_tokens(vocabulary: Path) -> None:
    assert tokens.count_tokens("") == 0


@pytest.mark.parametrize(
    "text",
    ["a bore of 12 µm", "© the vendor", "Ø 12 H7", "first line\r\nsecond line", "<|endoftext|>"],
)
def test_awkward_text_counts_without_error(vocabulary: Path, text: str) -> None:
    """Units, symbols, CRLF and a special-token spelling are all ordinary text here."""
    assert tokens.count_tokens(text) > 0


# --- the refusal, with no network --------------------------------------------------


def refusal_of(folder: Path) -> str:
    with pytest.raises(tokens.TokenizerUnavailable) as raised:
        tokens.load_encoding()
    return str(raised.value)


def assert_names_everything(message: str, folder: Path) -> None:
    assert str(folder) in message
    assert tokens.ENCODING_SHA256 in message
    assert "swreview tokenizer fetch" in message
    assert "\n" not in message


def test_a_missing_file_refuses_with_the_fetch_command(
    cache_dir: Path, no_network: list[str]
) -> None:
    message = refusal_of(cache_dir)

    assert_names_everything(message, cache_dir)
    assert no_network == []


def test_a_truncated_file_refuses_with_the_fetch_command(
    vocabulary: Path, cache_dir: Path, no_network: list[str]
) -> None:
    (cache_dir / tokens.VOCABULARY_FILE_NAME).write_bytes(good_bytes(vocabulary)[:1000])

    message = refusal_of(cache_dir)

    assert_names_everything(message, cache_dir)
    assert no_network == []


def test_a_file_with_one_byte_changed_refuses_with_the_fetch_command(
    vocabulary: Path, cache_dir: Path, no_network: list[str]
) -> None:
    altered = bytearray(good_bytes(vocabulary))
    altered[len(altered) // 2] ^= 0x01
    (cache_dir / tokens.VOCABULARY_FILE_NAME).write_bytes(bytes(altered))

    message = refusal_of(cache_dir)

    assert_names_everything(message, cache_dir)
    assert no_network == []


def test_a_directory_where_the_file_should_be_refuses(
    cache_dir: Path, no_network: list[str]
) -> None:
    (cache_dir / tokens.VOCABULARY_FILE_NAME).mkdir()

    assert_names_everything(refusal_of(cache_dir), cache_dir)
    assert no_network == []


# --- where the cache lives -----------------------------------------------------------


@pytest.fixture
def no_cache_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    for name in (tokens.TOKENIZER_DIR_ENV, "XDG_CACHE_HOME"):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def test_the_environment_variable_wins(no_cache_env: pytest.MonkeyPatch, tmp_path: Path) -> None:
    no_cache_env.setenv(tokens.TOKENIZER_DIR_ENV, str(tmp_path / "mine"))
    no_cache_env.setenv("LOCALAPPDATA", str(tmp_path / "local"))

    assert tokens.tokenizer_dir() == tmp_path / "mine"


def test_on_windows_the_cache_is_under_local_app_data(
    no_cache_env: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    no_cache_env.setattr(sys, "platform", "win32")
    no_cache_env.setenv("LOCALAPPDATA", str(tmp_path / "local"))

    assert tokens.tokenizer_dir() == tmp_path / "local" / "SwReview" / "tokenizer"


def test_elsewhere_the_cache_follows_xdg(no_cache_env: pytest.MonkeyPatch, tmp_path: Path) -> None:
    no_cache_env.setattr(sys, "platform", "linux")
    no_cache_env.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))

    assert tokens.tokenizer_dir() == tmp_path / "xdg" / "swreview" / "tokenizer"


def test_elsewhere_without_xdg_the_cache_is_under_the_home_folder(
    no_cache_env: pytest.MonkeyPatch,
) -> None:
    no_cache_env.setattr(sys, "platform", "linux")

    assert tokens.tokenizer_dir() == Path.home() / ".cache" / "swreview" / "tokenizer"


# --- TIKTOKEN_CACHE_DIR is borrowed, never kept ---------------------------------------


def test_tiktoken_cache_dir_is_restored_when_it_was_set(
    vocabulary: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("TIKTOKEN_CACHE_DIR", str(tmp_path / "theirs"))

    tokens.load_encoding()

    assert os.environ.get("TIKTOKEN_CACHE_DIR") == str(tmp_path / "theirs")


def test_tiktoken_cache_dir_stays_absent_when_it_was_absent(
    vocabulary: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("TIKTOKEN_CACHE_DIR", raising=False)

    tokens.load_encoding()

    assert "TIKTOKEN_CACHE_DIR" not in os.environ


def test_tiktoken_cache_dir_is_restored_after_a_refusal(
    cache_dir: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("TIKTOKEN_CACHE_DIR", str(tmp_path / "theirs"))

    with pytest.raises(tokens.TokenizerUnavailable):
        tokens.load_encoding()

    assert os.environ.get("TIKTOKEN_CACHE_DIR") == str(tmp_path / "theirs")


# --- `swreview tokenizer fetch` ------------------------------------------------------


@pytest.fixture
def source_file(vocabulary: Path, tmp_path: Path) -> Path:
    """A copy of the good vocabulary somewhere the operator already has it."""
    path = tmp_path / "downloads" / "o200k_base.tiktoken"
    path.parent.mkdir()
    path.write_bytes(good_bytes(vocabulary))
    return path


def test_fetch_from_a_good_file_copies_it_into_the_cache(
    source_file: Path, cache_dir: Path, no_network: list[str]
) -> None:
    result = runner.invoke(cli.app, ["tokenizer", "fetch", "--from", str(source_file)])

    assert result.exit_code == 0, result.output
    target = cache_dir / tokens.VOCABULARY_FILE_NAME
    assert target.read_bytes() == source_file.read_bytes()
    assert str(target) in result.stdout
    assert no_network == []


def test_fetch_from_a_bad_file_refuses_in_one_sentence(
    tmp_path: Path, cache_dir: Path, no_network: list[str]
) -> None:
    bad = tmp_path / "bad.tiktoken"
    bad.write_bytes(b"not a vocabulary")

    result = runner.invoke(cli.app, ["tokenizer", "fetch", "--from", str(bad)])

    assert result.exit_code == 1
    assert result.stdout == ""
    lines = result.stderr.strip().splitlines()
    assert len(lines) == 1
    assert tokens.ENCODING_SHA256 in lines[0]
    assert not (cache_dir / tokens.VOCABULARY_FILE_NAME).exists()
    assert no_network == []


def test_fetch_from_a_missing_file_refuses_in_one_sentence(tmp_path: Path, cache_dir: Path) -> None:
    result = runner.invoke(cli.app, ["tokenizer", "fetch", "--from", str(tmp_path / "none")])

    assert result.exit_code == 1
    assert len(result.stderr.strip().splitlines()) == 1


def test_fetch_never_overwrites_a_file_that_already_matches(
    source_file: Path, cache_dir: Path, vocabulary: Path
) -> None:
    target = cache_dir / tokens.VOCABULARY_FILE_NAME
    target.write_bytes(good_bytes(vocabulary))
    os.utime(target, ns=(1_000_000_000_000_000_000, 1_000_000_000_000_000_000))
    before = target.stat().st_mtime_ns

    result = runner.invoke(cli.app, ["tokenizer", "fetch", "--from", str(source_file)])

    assert result.exit_code == 0, result.output
    assert target.stat().st_mtime_ns == before


def test_fetch_replaces_a_damaged_file_in_the_cache(source_file: Path, cache_dir: Path) -> None:
    target = cache_dir / tokens.VOCABULARY_FILE_NAME
    target.write_bytes(b"damaged")

    result = runner.invoke(cli.app, ["tokenizer", "fetch", "--from", str(source_file)])

    assert result.exit_code == 0, result.output
    assert target.read_bytes() == source_file.read_bytes()


class FakeResponse:
    def __init__(self, content: bytes) -> None:
        self.content = content

    def raise_for_status(self) -> None:
        return None


@pytest.fixture
def served(monkeypatch: pytest.MonkeyPatch, vocabulary: Path) -> Iterator[list[str]]:
    """`requests.get` answering with the good file: the download path, with no network."""
    urls: list[str] = []
    content = good_bytes(vocabulary)

    def get(url: str, *args: Any, **kwargs: Any) -> FakeResponse:
        urls.append(url)
        return FakeResponse(content)

    monkeypatch.setattr(requests, "get", get)
    yield urls


def test_fetch_without_a_file_downloads_through_tiktoken_and_checks_the_hash(
    served: list[str], cache_dir: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("TIKTOKEN_CACHE_DIR", str(tmp_path / "theirs"))

    result = runner.invoke(cli.app, ["tokenizer", "fetch"])

    assert result.exit_code == 0, result.output
    assert served and served[0].endswith("o200k_base.tiktoken")
    assert (cache_dir / tokens.VOCABULARY_FILE_NAME).stat().st_size == VOCABULARY_BYTES
    assert os.environ.get("TIKTOKEN_CACHE_DIR") == str(tmp_path / "theirs")
    assert not (tmp_path / "theirs").exists()


def test_fetch_without_a_file_refuses_when_the_download_fails(
    no_network: list[str], cache_dir: Path
) -> None:
    result = runner.invoke(cli.app, ["tokenizer", "fetch"])

    assert result.exit_code == 1
    assert len(result.stderr.strip().splitlines()) == 1
    assert not (cache_dir / tokens.VOCABULARY_FILE_NAME).exists()


def test_tokenizer_lists_fetch_in_its_help() -> None:
    result = runner.invoke(cli.app, ["tokenizer", "--help"])

    assert result.exit_code == 0
    assert "fetch" in result.stdout


# --- nothing is vendored ---------------------------------------------------------------


def test_no_file_in_the_shipped_source_is_the_vocabulary() -> None:
    """A size-and-hash scan: the vocabulary never enters `reviewer/src/swreview/`."""
    offenders: list[str] = []
    for path in SRC_ROOT.rglob("*"):
        if not path.is_file():
            continue
        if path.name == tokens.VOCABULARY_FILE_NAME or path.stat().st_size == VOCABULARY_BYTES:
            offenders.append(str(path))
            continue
        if path.stat().st_size > 1_000_000:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest == tokens.ENCODING_SHA256:
                offenders.append(str(path))

    assert offenders == []
