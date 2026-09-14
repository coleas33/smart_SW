# reviewer

The Python half of the pilot: IR models and units, ingest of exported files, the
deterministic checks that compute every number, the curated agent tools, the tool-runner
loop, the report, and the backends the SOLIDWORKS Task Pane talks to. Nothing here touches
the SOLIDWORKS API; live operations go through the C# bridge in `extractor/`.

Scenarios and expected output: `specs/001-agentic-design-review/quickstart.md` and
`specs/002-task-pane-assistant/quickstart.md`. Command-line contract:
`specs/001-agentic-design-review/contracts/cli.md`.

## Layout

```text
src/swreview/
  ir/           evidence-package models, loader, schema
  ingest/       BOM, manifest, drawing-PDF and STEP ingest
  units.py      the one unit registry; every Quantity crosses it
  geometry/     axis distance, face gap, envelope raycast (trimesh)
  checks/       deterministic checks; the only source of a verdict
  tools/        the curated tool surface the model is given
  agent/        settings.py (provider, model, effort, key source, redaction),
                providers/ (protocol, schema generation, OpenAI, Gemini, fake),
                runner.py, prompts/, checklist
  chat/         the Task Pane chat backend (loopback HTTP + SSE)
  mcp/          the read-only stdio toolset an external CLI connects to
  report/       session records and the Markdown report
  benchmark/    benchmark sets, runs and scorecards
  bridge/       client for the C# tool service
  cli.py        every command
```

## Build and test

```powershell
uv sync --all-extras          # add --reinstall-package swreview if "No module named swreview"
uv run pytest                 # unit + golden tests
uv run ruff check src tests
```

Two groups skip rather than fail on a checkout that cannot run them: `integration` needs a
native evidence package dumped on the workstation, and `live` needs a provider key in the
environment (it calls the real API). A checkout with neither runs green.

## Providers and keys

`review` and `benchmark run` take `--provider openai|gemini`, `--model <id>` and
`--effort low|medium|high|xhigh`. The default model is the provider's own and lives in one
place, `src/swreview/agent/settings.py`; no command line or session carries a hard-coded
model id. There is no Anthropic dependency.

The key is never an argument. It is read from the pane's settings file first and the
environment second (`OPENAI_API_KEY`; for Gemini `GOOGLE_API_KEY` ahead of
`GEMINI_API_KEY`), and the session records which of the two it came from. It is held as a
`SecretStr` excluded from every dump, and a redaction filter masks it in log records and in
provider error text before either reaches a run folder. `swreview audit-secrets <dir>...`
is the check that it never did.

## Third-party licenses

Runtime dependencies and their licenses are listed in `../NOTICE.md`.
