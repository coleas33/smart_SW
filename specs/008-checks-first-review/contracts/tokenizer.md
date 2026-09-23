# Contract: The Tokenizer

Normative for `reviewer/src/swreview/tokens.py` and the vendored vocabulary (FR-003, FR-026).

## 1. The one encoding

`TOKENIZER_NAME = "o200k_base"`, the encoding the OpenAI models in use count with. Every token
count this feature prints or records - the replay's rounds, a step's `result_tokens`, the report's
largest results - comes from `count_tokens(text) -> int` over exactly the text the adapter sends
(`tool_result_text`, `model-view.md` section 6), and every surface that prints one names the
encoding. A Gemini recording is priced with the same encoding and labelled a shape comparison.

## 2. The vocabulary ships with the package

- Path: `reviewer/src/swreview/tokenizer/fb374d419588a4632f3f557e76b4b70aebbca790`, the name
  tiktoken caches the encoding's file under, 3,613,922 bytes.
- `ENCODING_SHA256` equals the `expected_hash` tiktoken carries for `o200k_base`
  (`tiktoken_ext.openai_public.o200k_base`).
- `.gitattributes` carries `reviewer/src/swreview/tokenizer/* -text`, so `core.autocrlf` can never
  rewrite it; hatchling packages it with `src/swreview`.
- Dependency: `tiktoken>=0.9,<1` at runtime.

## 3. Loading

1. `tokens.py` reads the vendored file and checks its sha256 against `ENCODING_SHA256` itself; a
   missing, truncated or altered file raises `TokenizerUnavailable` with one sentence naming the
   file and the expected hash, and **no network is attempted**.
2. It then calls `tiktoken.get_encoding("o200k_base")` with `TIKTOKEN_CACHE_DIR` set to the
   vendored folder, and restores the variable (or its absence) in a `finally`.
3. The encoding is loaded once per process (about 0.13 s) and cached.

## 4. Callers and failure

| Caller | On `TokenizerUnavailable` |
|---|---|
| The replay | Refuses with the sentence, exit 1: a replay that cannot count has nothing to report |
| `record_call` (step sizes) | Records `result_tokens = None` and `result_bytes` as measured; never raises, because a tool call must never raise |
| The report's largest results | Prints `unknown` for a step whose tokens are null |
