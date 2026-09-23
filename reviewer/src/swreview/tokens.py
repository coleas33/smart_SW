"""The one tokenizer: every token count feature 008 prints or records (`contracts/tokenizer.md`).

The replay's rounds, a step's `result_tokens` and the report's largest results are all counted
by `count_tokens`, over one named encoding - `o200k_base`, the one the OpenAI models in use
count with - and over exactly the text an adapter sends (`providers.tool_result_text`). Every
surface that prints a count names the encoding, so a number can always say how it was made.

**The vocabulary is not in the repository.** OpenAI publishes the `o200k_base` file with no
stated redistribution terms and this repository is public, so each machine fetches it once
into a per-user cache (`swreview tokenizer fetch`, the one code path here that may touch the
network) and every later load reads that cache with no network at all:

1. `tokenizer_dir()` names the folder: `SWREVIEW_TOKENIZER_DIR`, else
   `%LOCALAPPDATA%\\SwReview\\tokenizer` on Windows, else `$XDG_CACHE_HOME/swreview/tokenizer`
   or `~/.cache/swreview/tokenizer`.
2. The file's sha256 is checked here, against `ENCODING_SHA256`, before tiktoken sees it. A
   missing, truncated or altered file is a `TokenizerUnavailable` naming the folder, the
   expected hash and the fetch command - never a silent download: tiktoken's own loader
   re-fetches a cached file whose hash does not match, which is exactly the network call a
   replay must not make.
3. tiktoken is then asked for the encoding with `TIKTOKEN_CACHE_DIR` pointed at the folder,
   and the variable is put back as it was (set or absent) whatever happens.

The encoding is loaded once per process (`encoding()`, about 0.13 s) and reused.
"""

from __future__ import annotations

import functools
import hashlib
import os
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import tiktoken

__all__ = [
    "ENCODING_SHA256",
    "FETCH_COMMAND",
    "TOKENIZER_DIR_ENV",
    "TOKENIZER_NAME",
    "VOCABULARY_FILE_NAME",
    "TokenizerUnavailable",
    "count_tokens",
    "encoding",
    "fetch_vocabulary",
    "load_encoding",
    "tokenizer_dir",
    "vocabulary_path",
]

TOKENIZER_NAME = "o200k_base"
"""The one encoding every count is made with, and the name every count is printed beside."""

VOCABULARY_FILE_NAME = "fb374d419588a4632f3f557e76b4b70aebbca790"
"""The name tiktoken caches the encoding's file under: the sha1 of its download URL."""

ENCODING_SHA256 = "446a9538cb6c348e3516120d7c08b09f57c36495e2acfffe59a5bf8b0cfb1a2d"
"""The `expected_hash` tiktoken itself carries for `o200k_base`, checked here before loading."""

TOKENIZER_DIR_ENV = "SWREVIEW_TOKENIZER_DIR"
"""Names the cache folder outright; first match wins over the per-platform default."""

FETCH_COMMAND = "swreview tokenizer fetch"
"""What every refusal tells the operator to run."""

_TIKTOKEN_CACHE_ENV = "TIKTOKEN_CACHE_DIR"


class TokenizerUnavailable(RuntimeError):
    """The vocabulary is missing or not the one this build counts with; one sentence says so."""


def tokenizer_dir() -> Path:
    """The per-user folder the vocabulary lives in (contracts/tokenizer.md section 2)."""
    named = os.environ.get(TOKENIZER_DIR_ENV)
    if named:
        return Path(named)
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA")
        base = Path(local) if local else Path.home() / "AppData" / "Local"
        return base / "SwReview" / "tokenizer"
    xdg = os.environ.get("XDG_CACHE_HOME")
    base = Path(xdg) if xdg else Path.home() / ".cache"
    return base / "swreview" / "tokenizer"


def vocabulary_path() -> Path:
    """Where the vocabulary file is expected: `tokenizer_dir()` under its cache-key name."""
    return tokenizer_dir() / VOCABULARY_FILE_NAME


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _unavailable(folder: Path, problem: str) -> TokenizerUnavailable:
    return TokenizerUnavailable(
        f"the {TOKENIZER_NAME} vocabulary in {folder} {problem}, so no token can be counted; "
        f"run `{FETCH_COMMAND}` once on this machine to put the file with sha256 "
        f"{ENCODING_SHA256} there"
    )


def _checked_vocabulary(folder: Path) -> None:
    """Refuse unless `folder` holds the vocabulary with the expected hash. Never downloads."""
    path = folder / VOCABULARY_FILE_NAME
    try:
        content = path.read_bytes()
    except FileNotFoundError:
        raise _unavailable(folder, f"is missing ({VOCABULARY_FILE_NAME})") from None
    except OSError as exc:
        raise _unavailable(folder, f"could not be read ({type(exc).__name__}: {exc})") from exc
    digest = _sha256(content)
    if digest != ENCODING_SHA256:
        raise _unavailable(
            folder, f"is not the expected file ({len(content)} bytes with sha256 {digest})"
        )


@contextmanager
def _tiktoken_cache(folder: Path | str) -> Iterator[None]:
    """Point tiktoken's cache at `folder` for the duration, then restore the variable exactly."""
    before = os.environ.get(_TIKTOKEN_CACHE_ENV)
    os.environ[_TIKTOKEN_CACHE_ENV] = str(folder)
    try:
        yield
    finally:
        if before is None:
            os.environ.pop(_TIKTOKEN_CACHE_ENV, None)
        else:
            os.environ[_TIKTOKEN_CACHE_ENV] = before


def load_encoding() -> tiktoken.Encoding:
    """Check the cached vocabulary and load the encoding from it, with no network.

    Uncached, so every call re-checks the file; `encoding()` is the once-per-process form
    every counter uses.
    """
    folder = tokenizer_dir()
    _checked_vocabulary(folder)
    with _tiktoken_cache(folder):
        return tiktoken.get_encoding(TOKENIZER_NAME)


@functools.cache
def encoding() -> tiktoken.Encoding:
    """The encoding, loaded once per process by `load_encoding`."""
    return load_encoding()


def count_tokens(text: str) -> int:
    """How many `o200k_base` tokens `text` is.

    `disallowed_special=()` because the text is a tool result or a prompt, never a control
    sequence: a model's result that happens to spell `<|endoftext|>` is ordinary text and is
    counted as such rather than refused.
    """
    return len(encoding().encode(text, disallowed_special=()))


# --- fetching, once per machine ----------------------------------------------------------


def _download() -> bytes:
    """tiktoken's own loader for `o200k_base`, into a scratch cache that is then discarded.

    The loader downloads the file and checks tiktoken's own hash; the caller checks ours as
    well. `TIKTOKEN_CACHE_DIR` is borrowed for the call and restored afterwards, so the
    operator's own tiktoken cache is neither read nor written.
    """
    import tiktoken_ext.openai_public as openai_public

    with tempfile.TemporaryDirectory(prefix="swreview-tokenizer-") as scratch:
        try:
            with _tiktoken_cache(scratch):
                openai_public.o200k_base()
            return (Path(scratch) / VOCABULARY_FILE_NAME).read_bytes()
        except Exception as exc:  # noqa: BLE001 - every download failure is one sentence
            raise TokenizerUnavailable(
                f"downloading the {TOKENIZER_NAME} vocabulary failed ({type(exc).__name__}: "
                f"{' '.join(str(exc).split())}); run `{FETCH_COMMAND} --from <file>` with a copy "
                "of the file if this machine cannot reach the internet"
            ) from exc


def _read_source(source: Path) -> bytes:
    try:
        return source.read_bytes()
    except OSError as exc:
        raise TokenizerUnavailable(
            f"the file {source} could not be read ({type(exc).__name__}: {exc}), so the "
            f"{TOKENIZER_NAME} vocabulary was not fetched"
        ) from exc


def fetch_vocabulary(source: Path | None = None) -> tuple[Path, bool]:
    """Put the vocabulary into `tokenizer_dir()`; returns the path and whether it was written.

    A file already there with the expected hash is left untouched (and nothing is
    downloaded). Otherwise the content comes from `source` when given - a copy the operator
    already has - or from tiktoken's own loader, and is hash-checked before it is written
    through a temporary file and an atomic replace.
    """
    target = vocabulary_path()
    if target.is_file() and _sha256(target.read_bytes()) == ENCODING_SHA256:
        return target, False
    content = _read_source(source) if source is not None else _download()
    digest = _sha256(content)
    if digest != ENCODING_SHA256:
        origin = str(source) if source is not None else "the download"
        raise TokenizerUnavailable(
            f"{origin} is not the {TOKENIZER_NAME} vocabulary: its sha256 is {digest}, not "
            f"{ENCODING_SHA256}, so nothing was written to {target.parent}"
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f"{target.name}.{os.getpid()}.tmp")
    try:
        temporary.write_bytes(content)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target, True
