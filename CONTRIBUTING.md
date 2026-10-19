# Contributing to smart_SW

Thank you for looking. This is a small pilot project maintained by its owner
([@coleas33](https://github.com/coleas33)), who reviews and merges every change. Anyone may open
an issue or a pull request. The rules below exist because the repository is public, because it
drives a CAD system an engineer relies on, and because every number it reports must come from
tested code.

The project's rules are in the constitution,
[`.specify/memory/constitution.md`](.specify/memory/constitution.md), which supersedes this file.
[`AGENTS.md`](AGENTS.md) is the short form of the same rules for coding agents and people alike.

## Before you start

- **Larger changes start as an issue.** A new check, a new tab or command, a change to a
  contract under `specs/`, anything that touches the read-only guard, key handling or the send
  gate, and any constitution amendment: open an issue first (use the feature-request form) so the
  direction is agreed before the work. A small, self-contained fix can go straight to a pull
  request.
- **Never attach real material** to an issue or a pull request: see
  [The public-repository rule](#the-public-repository-rule).
- **Security problems are not issues.** Report them privately as [`SECURITY.md`](SECURITY.md)
  says.

## Development setup

Follow the [Quick start](README.md#quick-start) in `README.md`: it installs the reviewer with uv,
fetches the tokenizer vocabulary and runs the tests, with no SOLIDWORKS and no API key. The
reviewer's layout is in [`reviewer/README.md`](reviewer/README.md) and the extractor's in
[`extractor/README.md`](extractor/README.md).

## The gates

Every commit passes the gates in [`AGENTS.md`](AGENTS.md#gates-before-every-commit): from
`reviewer/`, the sync, the tokenizer, the test suite with the tokenizer required, and Ruff. CI
(`.github/workflows/reviewer.yml`) runs the same suite on Windows and Linux under Python 3.11
and 3.12, followed by the secrets audit; run both Pythons locally when a change could differ
between them. A feature's `tasks.md` may name further checks for its gates; run what the task
names.

**The C# gate is local.** CI does not build `extractor/SwReview.sln`: it compiles against the
SOLIDWORKS 2024 interop assemblies, which are not redistributable and are not on a hosted
runner. If you change anything under `extractor/`, run the build (zero warnings) and the tests
named in `AGENTS.md` on Windows with SOLIDWORKS 2024 installed (a licence is not needed to build),
and say in the pull request that you did and with what counts. The interop folder can be
overridden with `-p:SwRedist=<folder>` (`extractor/Directory.Build.props`). Never attach a
self-hosted runner to this repository: it is public, so any pull request could run code on that
machine.

Live tests (`-m live`) call a paid API with a real key. They run only when asked, never as part
of the gates.

## Test first

Every behaviour change starts with a failing test, named in the task, and then the code that
makes it pass (constitution principle III, "Test-First With Golden Fixtures"). An existing test is
changed only deliberately, with the reason in the commit, and never loosened to make a change
pass. Tests use the fictional fixtures already in the repository: the review packages under
`benchmarks/packages/`, the replay fixtures under `reviewer/tests/fixtures/replay/`, and the
example profile `config/standards.example.yaml`.

## The Spec Kit workflow

Work is specified with [GitHub Spec Kit](https://github.com/github/spec-kit). Each feature is a
package under `specs/NNN-name/`: `spec.md` (what and why), `plan.md`, `research.md`,
`data-model.md`, `contracts/`, `quickstart.md` and `tasks.md`. The index with each feature's
status is [`specs/README.md`](specs/README.md).

- The workflow skills are `/speckit-constitution`, `/speckit-specify`, `/speckit-plan`,
  `/speckit-tasks`, `/speckit-implement` and `/speckit-converge`, plus `/speckit-clarify`,
  `/speckit-analyze` and `/speckit-checklist` (under `.claude/skills/`).
- Follow the feature's `tasks.md` in order. Tick a task only when its acceptance holds.
- Tasks marked `[W]` need the licensed SOLIDWORKS seat and run only on the pilot workstation.
  Never start SOLIDWORKS on a machine without a licence.
- Decisions taken during a feature are recorded in its `research.md`; the owner's decisions are
  numbered (`112A`) and indexed in [`docs/decisions.md`](docs/decisions.md). A contribution that
  needs an owner decision asks for it in the issue or the pull request rather than assuming one.
- Keep changes surgical: touch what the task needs, match the surrounding style, and remove only
  the orphans your change created.

## Pull requests

- Open them against `main`, from a branch.
- Fill in the template: the summary, the issue or feature task, and the checklist.
- CI must pass. The C# gate, when it applies, is reported in the description.
- Update the feature's `spec.md`, `tasks.md` and `research.md` in the same pull request when the
  change affects them.

## Commit messages

As [`AGENTS.md`](AGENTS.md#how-work-is-done) says: `Feature NNN Tnnn: what changed` for task
work, and `Record passing <slice> gate on main` for gate records. Other changes start with their
area, as the history does (`Docs:`, `CI:`). The body says why, and names the owner decisions
(`112A`) it applies.

Files are committed with LF line endings (`.gitattributes`); `git ls-files --eol` shows `i/lf`
for every text file you changed.

## The public-repository rule

This repository is public. Commit, attach and paste **only fictional data**. Never commit, and
never put in an issue, a pull request, a log or a screenshot:

- a real design, part or drawing number, or a real product or assembly folder name;
- a company, customer or person's name, or a Windows user name (write a user folder as
  `%USERPROFILE%`, `%LOCALAPPDATA%` or `C:\Users\<you>`);
- a vault, network or project path from a real installation;
- a real standards profile (`config/standards.example.yaml` is the fictional one), template or
  sheet format;
- a SOLIDWORKS file, drawing, dump, recording, run folder, log or handover folder from real work;
- an API key or any other credential;
- per-machine state: the settings file (`%APPDATA%\SwReview\settings.json`), anything under
  `%LOCALAPPDATA%\SwReview`, `.venv`, `bin`, `obj`, or the ignored `dumps/` and `logs/` folders.

A committed test (`reviewer/tests/unit/test_tracked_files_carry_no_recorded_number.py`) scans
every tracked file against the owner's lists of forbidden numbers and identifiers, which are kept
outside the repository; it skips where the lists are absent, as in CI, so it does not replace
your own care. `swreview audit-secrets <folder>...` reports any configured key that reached a
file. Organisations that need private material alongside this code keep it in a private fork; see
[`docs/forking.md`](docs/forking.md).

## Third-party code

Respect each source's licence. [`NOTICE.md`](NOTICE.md) lists what the project references,
vendors or depends on; a new dependency or a vendored file adds its row there. Code may not be
copied from a source whose licence does not permit it (the constitution's "Third-party reuse"
constraint names the cases already met).

## Licence of contributions

The project is licensed under the GNU Affero General Public License v3.0 or later
([`LICENSE`](LICENSE)). By contributing you agree that your contribution is licensed under the
project licence.
