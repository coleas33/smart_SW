# Contract: The Tokenizer

Normative for `reviewer/src/swreview/tokens.py`, `swreview tokenizer fetch`, and where the
vocabulary lives (FR-003, FR-026). Amended 2026-09-23: the vocabulary is **not** vendored into the
repository; it is fetched once into a per-user cache (research R2.7).

## 1. The one encoding

`TOKENIZER_NAME = "o200k_base"`, the encoding the OpenAI models in use count with. Every token
count this feature prints or records - the replay's rounds, a step's `result_tokens`, the report's
largest results - comes from `count_tokens(text) -> int` over exactly the text the adapter sends
(`tool_result_text`, `model-view.md` section 6), and every surface that prints one names the
encoding. A Gemini recording is priced with the same encoding and labelled a shape comparison.

## 2. The vocabulary lives in a per-user cache, never in the repository

- File name: `fb374d419588a4632f3f557e76b4b70aebbca790`, the name tiktoken caches the encoding's
  file under; 3,613,922 bytes; `ENCODING_SHA256` equals the `expected_hash` tiktoken carries for
  `o200k_base` (`tiktoken_ext.openai_public.o200k_base`).
- Folder, first match wins: the environment variable `SWREVIEW_TOKENIZER_DIR`; on Windows
  `%LOCALAPPDATA%\SwReview\tokenizer`; elsewhere `$XDG_CACHE_HOME/swreview/tokenizer` or
  `~/.cache/swreview/tokenizer`. `tokens.tokenizer_dir()` returns it.
- Why not vendored: the file is published by OpenAI with no stated redistribution terms, and this
  repository is public. A per-user cache keeps the public tree free of it at the cost of one
  fetch per machine.
- Dependency: `tiktoken>=0.9,<1` at runtime (MIT).

## 3. Fetching, once per machine

`swreview tokenizer fetch` is the only code path that touches the network for the tokenizer:

1. It calls tiktoken's own loader for `o200k_base` (which downloads the file and checks tiktoken's
   expected hash), with `TIKTOKEN_CACHE_DIR` pointed at a temporary folder and restored afterwards.
2. It checks the downloaded file's sha256 against `ENCODING_SHA256` itself, then copies it into
   `tokenizer_dir()` under its cache-key name, never overwriting a file whose hash already matches.
3. It prints the path and exits 0; any failure is one sentence and exit 1.
4. `--from <file>` copies a file the operator already has (for a machine without network) after
   the same hash check.

`extractor/tools/update-workstation.ps1` runs `uv run swreview tokenizer fetch` after
`uv sync`; the reviewer CI workflow runs it before the tests. A machine that already holds the
file in tiktoken's default cache can use `--from` on that file.

## 4. Loading, with no network

1. `tokens.py` reads the file from `tokenizer_dir()` and checks its sha256 against
   `ENCODING_SHA256` itself; a missing, truncated or altered file raises `TokenizerUnavailable`
   with one sentence naming the folder, the expected hash and the fetch command, and **no network
   is attempted**.
2. It then calls `tiktoken.get_encoding("o200k_base")` with `TIKTOKEN_CACHE_DIR` set to that
   folder, and restores the variable (or its absence) in a `finally`.
3. The encoding is loaded once per process (about 0.13 s) and cached.

## 5. Callers and failure

| Caller | On `TokenizerUnavailable` |
|---|---|
| The replay | Refuses with the sentence, exit 1: a replay that cannot count has nothing to report |
| `record_call` (step sizes) | Records `result_tokens = None` and `result_bytes` as measured; never raises, because a tool call must never raise |
| The report's largest results | Prints `unknown` for a step whose tokens are null |

## 6. Tests

A shared pytest fixture `vocabulary` supplies the folder: `SWREVIEW_TOKENIZER_DIR` or the default
cache. When the file is absent, tests that need exact counts are **skipped** with the fetch
command in the reason - unless `SWREVIEW_REQUIRE_TOKENIZER=1`, which the CI workflow and
`update-workstation.ps1` set, in which case they **fail**. Tests of the refusal paths use a
temporary folder and need no real file.
