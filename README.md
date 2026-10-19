# smart_SW: SOLIDWORKS design review assistant

smart_SW reviews SOLIDWORKS parts, assemblies and drawings. A C# add-in and extractor read the
model through a read-only guard; a Python reviewer runs deterministic checks, asks a language
model to investigate and explain, and writes a findings report an engineer can verify and
disposition. Numbers come from tested code: the model decides what to investigate and explains,
and never computes a verdict.

## Status

This is a pilot, run on one licensed SOLIDWORKS workstation. There are no releases; `main` is
the only supported version. Most features are built and tested offline, and several still wait
on tasks that only the licensed seat can run. [`specs/README.md`](specs/README.md) gives each
feature's status and [`CHANGELOG.md`](CHANGELOG.md) what landed when. Dated pilot records
(findings, handovers, status notes, earlier roadmaps) are kept in
[`docs/history/`](docs/history/README.md).

## Quick start

This needs no SOLIDWORKS and no API key. It installs the reviewer, runs its tests, and runs two
offline commands over the fictional data committed in the repository. In Windows PowerShell:

```powershell
git clone https://github.com/coleas33/smart_SW.git
cd smart_SW\reviewer
uv sync --all-extras
uv run swreview tokenizer fetch
uv run pytest -m "not live"
uv run swreview check standards --package ..\benchmarks\packages\kalo-1 --profile ..\config\standards.example.yaml --out "$env:TEMP\swreview-quickstart\standards"
uv run swreview benchmark replay tests\fixtures\replay\small-assembly-a
```

- `tokenizer fetch` downloads the o200k_base vocabulary that every token count uses, once, into
  a per-user cache outside the checkout, and checks its sha256. Tests that count tokens skip
  without it, and the gates require it.
- `pytest -m "not live"` is the default suite. Tests that need a native package dumped on the
  workstation skip; `live` tests, which call a paid API, are deselected.
- `check standards` grades the fictional `kalo-1` package against the fictional example profile
  with no language model. It prints the verdict and writes `report.md`, `session.json`,
  `check.json` and `attention.json` into the `--out` folder, which must lie outside the package.
- `benchmark replay` prices a recorded, fictional review through the current code: no key, no
  network, nothing written. It prints each round's input tokens and compares the findings.

On Linux the commands are the same with `/` in the paths and an `--out` folder of your choice.
The gates a change must pass before it is committed are in
[`AGENTS.md`](AGENTS.md#gates-before-every-commit).

## What you need

| To | You need |
|---|---|
| Run the reviewer, its tests and the offline commands | Python 3.11 or 3.12 and [uv](https://docs.astral.sh/uv/); Windows or Linux (CI runs both) |
| Send a review to the model (`swreview review`, or the Review tab with "Send to the model when the checks finish" ticked, or Send to model pressed) | An OpenAI API key, in `OPENAI_API_KEY` or the Task Pane's settings |
| Build the extractor and the add-in | Windows, the .NET SDK, .NET Framework 4.8 (x64), and SOLIDWORKS 2024 installed for its interop assemblies (a licence is not needed to build) |
| Use the add-in | A licensed SOLIDWORKS 2024 seat; see [`docs/workstation-runbook.md`](docs/workstation-runbook.md) |

The Standards and Model check tabs need no language model and no key, and neither does a Review
with the send box unticked: it runs the code checks and stops before anything reaches the model.

## Layout

```text
extractor/    C# (.NET Framework 4.8, x64): SOLIDWORKS 2024 add-in, Task Pane (Review,
              Extract, Model check, Remodel and Standards tabs), console host, IR dump,
              interference, captures. Only this tree touches the SOLIDWORKS API.
reviewer/     Python 3.11+ (uv): IR models, units, ingest of exported files, deterministic
              checks, curated agent tools, a provider-neutral tool-runner loop, the Task Pane
              chat backend, the read-only MCP toolset, report, benchmarks.
benchmarks/   Review packages, native CAD inputs, answer keys (never readable by the
              reviewer), benchmark sets.
config/       A fictional example of the standards profile's shape.
specs/        Spec Kit artifacts for each feature.
docs/         Guides, runbooks, the test plan, decisions and history.
```

## Where to read next

- [`docs/README.md`](docs/README.md): the documentation index, by reader.
- [`docs/reviewer-guide.md`](docs/reviewer-guide.md): the commands, what a review reads first,
  the checks and the Task Pane tabs.
- [`docs/architecture.md`](docs/architecture.md): how the parts fit together.
- Testing on the pilot workstation: start with
  [`docs/test-plan-2026-09-27/README.md`](docs/test-plan-2026-09-27/README.md); the next
  licensed-seat sitting, in plain steps for the engineer who runs it, is
  [the workstation test plan](docs/test-plan-2026-09-27/workstation-test-plan.md), and installing
  and updating the add-in is [`docs/workstation-runbook.md`](docs/workstation-runbook.md).
- [`CONTRIBUTING.md`](CONTRIBUTING.md): how to contribute, the gates and the public-repository
  rule.
- [`docs/forking.md`](docs/forking.md): running a private downstream fork with company material.
- [`SECURITY.md`](SECURITY.md): reporting a vulnerability privately.

## Licence

AGPL-3.0-or-later; see [`LICENSE`](LICENSE). Third-party notices are in
[`NOTICE.md`](NOTICE.md). The reviewer depends on PyMuPDF (AGPL-3.0-or-later), which is why this
project carries the same licence.
