# Agent guidance for smart_SW

This file is the shared guidance for any coding agent working in this repository (Codex reads it
directly; `CLAUDE.md` imports it). The project's rules are in the constitution,
[`.specify/memory/constitution.md`](.specify/memory/constitution.md), which supersedes everything
here; this file must stay consistent with it.

## What the project is

An assistant that reviews SOLIDWORKS designs: a C# extractor and SOLIDWORKS add-in
(`extractor/`, with the Task Pane) read the model through a read-only guard, and a Python
reviewer (`reviewer/`) runs deterministic checks, asks a language model to investigate and
explain, and writes a findings report. Numbers come from tested code; the model never computes
a verdict. Work is specified with Spec Kit, one package per feature under `specs/NNN-name/`
(`spec.md`, `plan.md`, `tasks.md`, contracts).

## Rules that are never bent

1. **SOLIDWORKS documents are read, not written**, except the bounded exceptions the
   constitution names. Never add a write path, or loosen a guard, without a constitution
   amendment.
2. **This repository is public.** Commit only fictional data, never anything real from a design,
   a company or a machine; the full list of what that excludes is
   [the public-repository rule in `CONTRIBUTING.md`](CONTRIBUTING.md#the-public-repository-rule).
   A downstream fork keeps its private material in its own files; see
   [`docs/forking.md`](docs/forking.md) and
   [ADR 0008](docs/adr/0008-public-upstream-private-fork.md).
3. **Keys never reach the repository, a command line or a log**, and are never written as plain
   text (the add-in keeps the key DPAPI-encrypted in the user's settings). Live tests
   (`-m live`) call a paid API and run only when asked.
4. **Test first.** Every behaviour change starts with a failing test, named in the task; an
   existing test is changed only deliberately, with the reason, never loosened.
5. **Never start SOLIDWORKS on a machine without a licence**, and never run seat tasks (`[W]`)
   anywhere but the pilot workstation.

## Gates before every commit

From `reviewer/`:

```text
uv sync --all-extras
uv run swreview tokenizer fetch
SWREVIEW_REQUIRE_TOKENIZER=1 uv run pytest -q -m "not live"
uv run ruff check src tests
```

A `--basetemp`, if given, must lie outside the checkout: `tests/conftest.py` refuses one inside
it.

**Python versions.** CI (`.github/workflows/reviewer.yml`) runs the same suite on Windows and
Linux under Python 3.11 and 3.12 on every pull request and every push to `main`, and a pull
request is merged only when CI is green. Locally, run the gates on Python 3.12, and run the
suite on 3.11 as well when a change could behave differently between the two and at every
feature slice gate (owner decision 95A of 2026-10-14; feature 014 ran it with
`uv run --python 3.11 --isolated`).

**The C# gate**, from the repository root, on Windows with SOLIDWORKS 2024 installed (licence
not needed to build):

```text
dotnet build extractor\SwReview.sln -c Release      # zero warnings
dotnet test  extractor\SwReview.sln -c Release --no-build
```

Feature gates in a `tasks.md` may add checks (the ledger check, the replay check, `-m perf`,
`-m simulation`); run what the task names.

## How work is done

- Work in a branch or git worktree, never with uncommitted edits in someone else's checkout.
- Follow the feature's `tasks.md` order; record decisions in the feature's `research.md` and tick
  tasks only when their acceptance holds.
- Keep changes surgical: touch what the task needs, match the surrounding style, remove only the
  orphans your change created.
- Commit messages: `Feature NNN Tnnn: what changed` for task work, `Record passing <slice> gate on
  main` for gate records; the body says why, and names owner decisions (`112A`) it applies.
- Prefer explicit code over clever code; DRY; handle more edge cases rather than fewer.
