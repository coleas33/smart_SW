# Forking smart_SW for an organisation

This guide is for an organisation that forks this public repository into a private downstream
repository and adds its own material: its standards profile, its review cases, its real designs.
The aim is a fork that stays mergeable with upstream, keeps the company's material out of the
public repository, and can still send generic fixes back.

Upstream is `https://github.com/coleas33/smart_SW`, licensed AGPL-3.0-or-later. Everything here
describes upstream as it is on `main`; the extension points are described in more depth in the
extension points section of [`architecture.md`](architecture.md).

## 1. Keep the fork mergeable

The rule that keeps merges clean: **private material lives in files and folders upstream does
not have, and upstream's files are never edited to hold company data.**

- Put the company's tracked material in one top-level folder of its own (for example
  `company/`; upstream has no such folder). Upstream never writes there, so a merge never
  conflicts there.
- Do not edit `config/standards.example.yaml`, the benchmark sets, the fixtures, the prompts or
  any spec to hold company values. Each of them has an extension point below that takes a path
  instead.
- Do not put company cases under `benchmarks/packages/`, `answer_keys/`, `case_files/` or
  `sets/`: every file there is written by upstream's generator, and
  `reviewer/tests/unit/test_benchmark_case_generator.py` fails on a file no case spec writes
  ([`benchmarks/README.md`](../benchmarks/README.md)). Private cases go in a private set
  (section 2).
- When the fork needs a behaviour change, make it generic and send it upstream (section 4)
  rather than carrying a patch to an upstream file. A patch carried in the fork is a conflict on
  every merge that touches the same lines.
- Fork-only CI goes in a new workflow file, not in upstream's `.github/workflows/reviewer.yml`
  (section 5).

## 2. Where private material goes

These are the places the code already reads company material from. None of them needs a change
to an upstream file.

| Material | Where the code reads it | Notes |
|---|---|---|
| The standards profile (library folders, part-number pattern, property names, general tolerance, drawing standard, part roles) | `%LOCALAPPDATA%\SwReview\standards.yaml` on each workstation, or the path in the settings file's `standards_profile_path`; on the command line, `--profile <yaml>` | Shape: [`config/standards.example.yaml`](../config/standards.example.yaml) (version 4, fictional). Contract: [`specs/006-standards-check/contracts/profile.md`](../specs/006-standards-check/contracts/profile.md). `swreview profile upgrade` proposes the next version from an older file. |
| User settings: provider, model, effort, the key, endpoint override, run root, profile path, the send gate's default | `%APPDATA%\SwReview\settings.json`, written by the Task Pane; the key is DPAPI-protected for the Windows user | Per user and per machine; never committed (upstream's `.gitignore` ignores `settings.json` at any depth). Schema: [`specs/002-task-pane-assistant/contracts/settings.schema.json`](../specs/002-task-pane-assistant/contracts/settings.schema.json). |
| Run folders (reviews and checks, which name vault paths) | `Documents\SwReview\runs` by default, or the settings file's `run_root` | Never committed, in upstream or in the fork unless the fork has decided to keep them. |
| Logs and the tokenizer vocabulary | `%LOCALAPPDATA%\SwReview\logs\` and `%LOCALAPPDATA%\SwReview\tokenizer\` | Per machine. |
| Private review cases for the evaluation | A private benchmark set whose entries name packages, keys and case files by absolute paths outside the checkout | [`specs/014-design-review-eval/contracts/cases.md`](../specs/014-design-review-eval/contracts/cases.md), "Private sets". |
| A review checklist other than the default | `swreview review --checklist <yaml>` | The default is `reviewer/src/swreview/agent/checklist_v1.yaml`; copy it into the fork's own folder rather than editing it. |
| The lists of identifiers that must never reach a public file | `%LOCALAPPDATA%\SwReview\repo-identifiers.txt` and `fixture-denylist.txt` | Read by `reviewer/tests/unit/test_tracked_files_carry_no_recorded_number.py`; its docstring gives the format. Used in section 4. |

Where the per-machine files live and how they are installed is in
[`workstation-runbook.md`](workstation-runbook.md), section 1.

## 3. Syncing with upstream

Add upstream as a second remote once, then merge it whenever you want its changes:

```text
git remote add upstream https://github.com/coleas33/smart_SW.git
git fetch upstream
git checkout main
git merge upstream/main
```

Then run the gates ([`AGENTS.md`](../AGENTS.md#gates-before-every-commit)) and, if anything under
`extractor/` changed, the C# gate, before pushing the merge to the fork. [`CHANGELOG.md`](../CHANGELOG.md)
and [`specs/README.md`](../specs/README.md) say what changed upstream. A merge that conflicts in
an upstream file means the fork has edited that file; section 1 is the way back.

## 4. Sending fixes back upstream

A generic fix found in the fork is welcome upstream, without the company's data. Work from a
separate, clean checkout of upstream, not from the fork:

1. Clone upstream (or a public fork of it) into its own folder and branch from `upstream/main`.
2. Re-make the change there by hand or by cherry-picking a commit that touches only upstream
   files. Never merge or rebase the fork's history into it: the fork's history holds company
   material even where the current files do not.
3. Replace every company value in the change, its tests and its commit message with fictional
   data, using the existing fixtures (`benchmarks/packages/`, `reviewer/tests/fixtures/replay/`,
   `config/standards.example.yaml`).
4. Run the scrub checks:
   - Put the company's identifiers in `%LOCALAPPDATA%\SwReview\repo-identifiers.txt` on the
     machine (one per line) and, from the clean checkout's `reviewer/`, run
     `uv run pytest tests/unit/test_tracked_files_carry_no_recorded_number.py`. It fails, naming
     the file and line, if any identifier is in a tracked file or a tracked file's path.
   - Run `uv run swreview audit-secrets <each changed file or folder>`: it reports a configured
     key and, with its detectors on by default, provider-shaped keys.
   - Read the whole diff, the commit messages and the pull request text once more for paths,
     user names, part numbers, customer names and screenshots.
5. Run the gates and open the pull request as [`CONTRIBUTING.md`](../CONTRIBUTING.md) describes.

## 5. CI in a private fork

Upstream's workflow, `.github/workflows/reviewer.yml`, runs the Python suite and the secrets
audit on GitHub-hosted Windows and Linux runners, and works unchanged in a private fork. Leave
the file as it is, so merges stay clean, and add fork-only jobs in workflow files of your own.

The C# solution is not built in upstream's CI: it compiles against the SOLIDWORKS 2024 interop
assemblies, which are not redistributable and are not on a hosted runner. Upstream runs that
gate locally. A fork may run it on a self-hosted Windows runner with SOLIDWORKS installed, but
**only in a private repository the organisation controls**: upstream's workflow warns that on a
public repository any pull request could run code on that machine. A build needs SOLIDWORKS
installed but not a licence; never let CI start SOLIDWORKS or run the seat (`[W]`) tasks.

Do not store a provider key as a CI secret unless the fork has decided to run live tests in CI:
the default suite needs none (upstream's CI uses a dummy value only so the secrets audit has
something to search for), and live tests (`-m live`) spend money.

## 6. Keys and the provider

The product's language-model provider is OpenAI (owner decision 94A,
[`specs/014-design-review-eval/research.md`](../specs/014-design-review-eval/research.md)).

- Inside SOLIDWORKS, each engineer enters the key in the Task Pane's settings; it is stored
  DPAPI-protected for that Windows user and reaches the backend only through its environment.
- On the command line the key is read from `OPENAI_API_KEY`. It is never a command-line argument
  and never written to a run folder; `swreview audit-secrets` checks that.
- An endpoint override is supported: `base_url` in the settings file, or `OPENAI_BASE_URL`.
- The Standards and Model check tabs use no model and no key. On the Review tab, a checkbox
  decides whether a review is sent to the model when the code checks finish; it is ticked by
  default, and unticked the review stops after the checks until the engineer presses Send to
  model (feature 015, the send gate).
- A web filter on the workstation once blocked the pane's pages from reaching the loopback
  backend; the pages now go through a same-origin proxy in the add-in
  ([`pane-backend-proxy.md`](pane-backend-proxy.md)).

What the organisation's agreement with its provider allows to be sent (designs, drawings,
properties) is the organisation's decision; [`SECURITY.md`](../SECURITY.md) and the security
section of [`architecture.md`](architecture.md) describe what leaves the machine and when.

## 7. Licence obligations

The facts below are stated for orientation only. They are not legal advice; have the
organisation's own legal review decide what applies to its use.

- The project is licensed under the GNU Affero General Public License, version 3 or (at your
  option) any later version. The full text is [`LICENSE`](../LICENSE).
- A fork is a modified version of the program. The AGPL-3.0 requires, among other conditions,
  that a conveyed copy or modified version be licensed under the same licence with its
  corresponding source available, and its section 13 adds a condition for a modified version
  that users interact with remotely over a computer network.
- [`NOTICE.md`](../NOTICE.md) lists the third-party methods, repositories, vendored files and
  dependencies, each with its own licence and conditions; keep it, and keep `LICENSE`, in the
  fork. Among them: PyMuPDF is AGPL-3.0-or-later or commercially licensed by Artifex; the
  SOLIDWORKS interop assemblies are Dassault Systèmes property and are never redistributed; and
  several repositories that were studied carry restrictions on reuse, which NOTICE.md records.
- Whether and how these conditions apply to the fork's own additions, to how the fork is
  deployed inside the organisation, and to anything the fork distributes, is a question for that
  legal review.
