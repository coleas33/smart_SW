# Changelog

All notable changes to this project are recorded here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

There are no releases yet and no release tags; `main` is the only supported version (see
[`SECURITY.md`](SECURITY.md)). The reviewer package declares version `0.2.0` in
`reviewer/pyproject.toml` and the extractor `0.1.0` in `extractor/Directory.Build.props`, but
neither has been released under that number. Until a release is cut, the work is recorded below
as dated entries, one per feature or milestone, newest first. A date is when the work landed on
`main` (from `git log --first-parent main`); a range covers a feature that landed over several
days. Each feature's own status, including the tasks that still wait on the licensed seat, is in
[`specs/README.md`](specs/README.md).

## 2026-10-18: Continuous integration and documentation layout

- The Python suite runs on GitHub Actions under Windows and Linux with Python 3.11 and 3.12,
  followed by the secrets audit (`.github/workflows/reviewer.yml`). The C# gate stays local.
- [`AGENTS.md`](AGENTS.md) holds the shared guidance for coding agents.
- Dated notes moved to [`docs/history/`](docs/history/README.md), and the architecture proposal
  became [ADR 0001](docs/adr/0001-agentic-review-architecture.md).
- D0, the [drawing-creation inventory](docs/drawing-creation-d0-inventory.md), first phase.
- Community and project files for the public repository: [`CONTRIBUTING.md`](CONTRIBUTING.md),
  [`SECURITY.md`](SECURITY.md), this changelog, issue forms, a pull request template,
  `CODEOWNERS`, the documentation index [`docs/README.md`](docs/README.md), the
  [reviewer guide](docs/reviewer-guide.md), the [forking guide](docs/forking.md), the
  [architecture overview](docs/architecture.md), the [glossary](docs/glossary.md), the
  [decision log](docs/decisions.md) with ADRs 0002 to 0008, and the
  [specs index](specs/README.md). The front page [`README.md`](README.md) is shortened to a
  quick start that runs with no SOLIDWORKS and no key.

## 2026-10-06 to 2026-10-17: Feature 014, design-review evaluation

- Fictional benchmark cases with answer keys and scripted answers, a scorer, robust benchmark
  runs and their report; offline gates recorded through slice 8 on 2026-10-17. The seat task and
  the paid runs remain open. [Spec](specs/014-design-review-eval/spec.md).
- Owner decision 94A (2026-10-15): OpenAI is the only provider in use; the Gemini work is
  deferred.

## 2026-10-15: Feature 016, engineering context

- Requirements and applied forces saved against CAD evidence, with immutable revisions, explicit
  confirmation and bounded read-only context for reviews; entry from the Review pane and a
  read-only selection adapter. Native selection calibration and freshness wait on the seat.
  [Spec](specs/016-engineering-context/spec.md), [quickstart](specs/016-engineering-context/quickstart.md).

## 2026-10-15: Feature 015, the review send gate

- A checkbox on the Review tab, on by default, decides whether a review is sent to the model when
  the code checks finish; unticked, the review stops after the checks and offers Send to model.
  [Spec](specs/015-review-send-gate/spec.md).

## 2026-10-13: Workstation fixes

- Drawing extraction hardened and Remodel copy locks handled, from the
  [October 13 workstation feedback](docs/history/testing-feedback-2026-10-13.md).

## 2026-10-12: Feature 010 amendment, fine-pitch threads

- `check_threads` flags every fine or non-standard thread on every review for the engineer to
  confirm, against one table of ISO 261 coarse pitches and ASME B1.1 UNC threads.
  [Spec](specs/010-mechanical-checks/spec.md).

## 2026-09-26 to 2026-09-27: Feature 013, engineer-first review

- Bought parts are classified and left out of the grading (standards profile version 4,
  `part_roles`); every finding is shown grouped by type, and every row says whether code or the
  model wrote it. [Spec](specs/013-engineer-first-review/spec.md).

## 2026-09-23 to 2026-09-25: Feature 011, drawing context, read only

- A review reads the drawings already open in SOLIDWORKS: dimensions, tolerances, callouts,
  notes and tables; `check_drawings` and the per-part drawing brief. The read-only open of a
  candidate drawing ships off until a seat probe validates it.
  [Spec](specs/011-drawing-context/spec.md).

## 2026-09-23 to 2026-09-24: Feature 010, mechanical checks

- `check_joints`, `check_mass_material` and `check_hygiene`, argument-free and run with the
  checks first. [Spec](specs/010-mechanical-checks/spec.md).

## 2026-09-23: Feature 009, the engineer's workspace

- The Review tab's summary, questions for the engineer, the Results and Transcript switch, the
  kept reviews of the session and plain words throughout. Code complete; the workstation tasks
  are open. [Spec](specs/009-engineer-workspace/spec.md).

## 2026-09-22 to 2026-09-25: Feature 008, checks first and the token budget

- A pane review runs the deterministic checks before the model's first turn; payload slimming,
  history pruning and the offline `benchmark replay`. [Spec](specs/008-checks-first-review/spec.md).

## 2026-09-19: Feature 007, attention policy and procedural gate

- The fixed "Start here" ranking in every report, engineer timing, and the procedural gate
  (lever 11, off by default). [Spec](specs/007-attention-policy-gate/spec.md).

## 2026-09-17 to 2026-09-23: Feature 006, standards check

- The Standards tab: a release verdict against sixteen checks and a per-company profile, with
  no language model. [Spec](specs/006-standards-check/spec.md).

## 2026-09-16 to 2026-09-27: Feature 004, resilient re-modeler

- The Remodel tab plans a Resilient Modeling reorganisation on a copy of the document only; its
  Start switch stays off until a seat sitting has proved it (see the
  [workstation test plan](docs/test-plan-2026-09-27/workstation-test-plan.md), step 5.3).
  [Spec](specs/004-resilient-remodeler/spec.md).

## 2026-09-16: Feature 005, language-model efficiency

- Instrumentation and the efficiency flags, each off by default and adopted only on evidence.
  [Spec](specs/005-llm-efficiency/spec.md).

## 2026-09-15 to 2026-09-25: Feature 003, Resilient Modeling checks

- The `rms.*` checks and the Model check tab, with no language model; the suppress test as the
  one bounded console-only write. [Spec](specs/003-resilient-modeling/spec.md).

## 2026-09-13: Feature 002, Task Pane assistant; public release

- The Task Pane inside SOLIDWORKS with the review chat, provider settings, the in-process tool
  service, the terminal and the read-only MCP toolset; a provider layer for OpenAI and Gemini.
  The terminal's Ask tab is built but hidden since 2026-09-19, until the terminal is part of the
  pilot.
  [Spec](specs/002-task-pane-assistant/spec.md).
- The repository prepared for public release under AGPL-3.0-or-later, with
  [`NOTICE.md`](NOTICE.md).

## 2026-09-12: Feature 001, agentic design review

- The first build: the C# extractor and add-in, the Python reviewer's IR, units, ingest,
  deterministic checks, curated tools, agent loop, report, CLI and benchmark commands.
  [Spec](specs/001-agentic-design-review/spec.md).
