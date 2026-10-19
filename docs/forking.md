# Forking smart_SW for an organisation

This guide is for an organisation that forks this public repository into a private downstream
repository and adds its own material: its standards profile, its review cases, its real designs.
The aim is a fork that stays mergeable with upstream, keeps the company's material out of the
public repository, and can still send generic fixes back.

Upstream is `https://github.com/coleas33/smart_SW`, licensed AGPL-3.0-or-later. Everything here
describes upstream as it is on `main`; the extension points are described in more depth in
[section 5 of `architecture.md`](architecture.md#5-extension-points).

## 1. Keep the fork mergeable

The rule that keeps merges clean: **private material lives in files and folders upstream does
not have, and upstream's files are never edited to hold company data.**

- Keep the company's tracked material in one top-level folder of its own (for example
  `company/`; upstream has no such folder). Upstream never writes there, so a merge never
  conflicts there. No code reads that folder: it holds the fork's master copies, and section 2
  says how each one reaches the place the product reads it from.
- Do not edit `config/standards.example.yaml`, the benchmark sets, the fixtures, the prompts or
  any spec to hold company values. Only three kinds of material can be supplied by path
  without an edit: the standards profile, a review checklist (on the command line only) and
  private benchmark sets (section 2). Everything in the "Not yet extensible" list of
  [`architecture.md`](architecture.md#5-extension-points) - the engineering tables, the
  attention policy, the wording, the system prompt, the checklist a pane review uses, the report
  layout - changes only by editing upstream files. If the fork needs one of them changed, ask
  upstream for an extension point (a feature request, as [`CONTRIBUTING.md`](../CONTRIBUTING.md)
  describes) rather than carrying the edit.
- Do not put company cases under `benchmarks/packages/`, `answer_keys/`, `case_files/` or
  `sets/`. Those folders belong to upstream's case generator: every file there is written from a
  case spec except the hand-kept `answer_keys/rms-part.json` and the per-machine slot
  `packages/bracket-assy/`, and `reviewer/tests/unit/test_benchmark_case_generator.py` fails on
  a file no case spec writes ([`benchmarks/README.md`](../benchmarks/README.md), "The generated
  cases"). Private cases go in a private set (section 2).
- When the fork needs a behaviour change, make it generic and send it upstream (section 4)
  rather than carrying a patch to an upstream file. A patch carried in the fork is a conflict on
  every merge that touches the same lines.
- Fork-only CI goes in a new workflow file, not in upstream's `.github/workflows/reviewer.yml`
  (section 5).

### Files a fork is expected to change

A few upstream files name upstream's maintainer or repository. A fork changes them to name its
own. These are edits of who maintains the copy, not company data, and they touch a few lines
each, so they conflict only when upstream changes the same lines.

| File | What names upstream |
|---|---|
| `.github/CODEOWNERS` | `* @coleas33`: the reviewer of every path. |
| `.github/ISSUE_TEMPLATE/config.yml` | The security contact link, a URL to upstream's `SECURITY.md`. |
| `SECURITY.md` | The reporting channel: GitHub's private vulnerability reporting on the repository. The fork decides its own channel; a vulnerability in upstream's code is worth reporting upstream too. |
| `CONTRIBUTING.md` | The maintainer's handle in the opening paragraph. |
| `README.md` | The clone URL in the quick start. |
| `docs/workstation-runbook.md` | The clone URL in section 3, "First install". |
| `docs/test-plan-2026-09-27/workstation-test-plan.md` | The clone command of the first-install steps. |

This guide and [ADR 0008](adr/0008-public-upstream-private-fork.md) name upstream on purpose
and stay as they are; so does the pinned commit link in
[`future-capabilities-roadmap-2026-10-14.md`](future-capabilities-roadmap-2026-10-14.md).

## 2. Where private material goes

These are the places the code already reads company material from. None of them needs a change
to an upstream file.

| Material | Where the code reads it | Notes |
|---|---|---|
| The standards profile (library folders, part-number pattern, property names, general tolerance, drawing standard, part roles) | In the pane, `%LOCALAPPDATA%\SwReview\standards.yaml` on each workstation, or the path in the settings file's `standards_profile_path`. On the command line, `--profile <yaml>` on `check standards` and `drawing brief`, and `--standards-profile <yaml>` on `review`, `benchmark run` and `benchmark replay`. | Shape: [`config/standards.example.yaml`](../config/standards.example.yaml) (version 4, fictional). Contract: [`specs/006-standards-check/contracts/profile.md`](../specs/006-standards-check/contracts/profile.md). `swreview profile upgrade` proposes the next version from an older file. |
| User settings: provider, model, effort, the key, endpoint override, run root, profile path, the send gate's default | `%APPDATA%\SwReview\settings.json`, written by the Task Pane; the key is DPAPI-protected for the Windows user | Per user and per machine; never committed (upstream's `.gitignore` ignores `settings.json` at any depth). Schema: [`specs/002-task-pane-assistant/contracts/settings.schema.json`](../specs/002-task-pane-assistant/contracts/settings.schema.json). |
| Run folders (reviews and checks, which name vault paths) | `Documents\SwReview\runs` by default, or the settings file's `run_root` | Never committed, in upstream or in the fork unless the fork has decided to keep them. |
| Logs and the tokenizer vocabulary | `%LOCALAPPDATA%\SwReview\logs\` and `%LOCALAPPDATA%\SwReview\tokenizer\` | Per machine. |
| Private review cases for the evaluation | A private benchmark set whose entries name packages, keys and case files by absolute paths outside the checkout | [`specs/014-design-review-eval/contracts/cases.md`](../specs/014-design-review-eval/contracts/cases.md#46-private-sets), "Private sets". |
| A review checklist other than the default | `swreview review --checklist <yaml>`, on the command line only | The pane always uses the packaged `reviewer/src/swreview/agent/checklist_v1.yaml`, so a fork's checklist never reaches a pane review. Copy the default into the fork's own folder rather than editing it. |
| The lists of identifiers that must never reach a public file | `%LOCALAPPDATA%\SwReview\repo-identifiers.txt` and `fixture-denylist.txt` | Read by `reviewer/tests/unit/test_tracked_files_carry_no_recorded_number.py`; its docstring gives the format. Used in section 4, with the warning there. |

### How company material reaches each workstation

The add-in reads the profile from a path on the workstation, never from the fork's checkout by
itself. Put it there in one of two ways: copy the fork's master copy to
`%LOCALAPPDATA%\SwReview\standards.yaml`, the default path, or point `standards_profile_path` in
that user's settings file at the file where it is (for example inside the fork's checkout on
that machine). The command line reads only the path it is given. Placing the profile, checking
its version and validating it is section 5 of the workstation runbook,
[`workstation-runbook.md`](workstation-runbook.md#5-the-standards-profile); where the other
per-machine files live, and how they are installed, is its
[section 1](workstation-runbook.md#1-where-everything-is).

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
   - Read the whole diff, the commit messages and the pull request text once more against the
     [public-repository rule](../CONTRIBUTING.md#the-public-repository-rule), screenshots
     included.
5. Run the gates and open the pull request as [`CONTRIBUTING.md`](../CONTRIBUTING.md) describes.

**The identifier list fails the fork's own suite.** The test reads the list from
`%LOCALAPPDATA%`, so it applies to every checkout the same Windows user tests on that machine,
the fork included. The fork tracks company files on purpose, so on a machine whose list names the
company's identifiers, the fork's default suite fails this test. Keep the list populated only
where upstream-bound checkouts are scrubbed: on an account or machine that tests no fork
checkout, or only for the scrub run above, emptying it afterwards. Run the scrub from the clean
upstream-bound clone of step 1, never from the fork.

## 5. CI in a private fork

Upstream's workflow, `.github/workflows/reviewer.yml`, runs the Python suite and the secrets
audit on GitHub-hosted Windows and Linux runners, and works unchanged in a private fork. Leave
the file as it is, so merges stay clean, and add fork-only jobs in workflow files of your own.

The C# solution is not built in upstream's CI;
[`CONTRIBUTING.md`](../CONTRIBUTING.md#the-gates) says why. A fork may build it on a
self-hosted Windows runner with SOLIDWORKS installed, but **only in a private repository the
organisation controls**, and that runner must never start SOLIDWORKS or run the seat (`[W]`)
tasks.

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
section of [`architecture.md`](architecture.md#4-trust-and-security-boundaries) describe what
leaves the machine and when.

## 7. Licence obligations

The facts below are stated for orientation only. They are not legal advice; have the
organisation's own legal review decide what applies to its use.

- The project is licensed under the GNU Affero General Public License, version 3 or (at your
  option) any later version. The full text is [`LICENSE`](../LICENSE).
- A fork that changes the code is a modified version under the licence. The AGPL-3.0 requires,
  among other conditions, that a conveyed copy or modified version be licensed under the same
  licence with its corresponding source available, and its section 13 adds a condition for a
  modified version that users interact with remotely over a computer network.
- [`NOTICE.md`](../NOTICE.md) lists the third-party methods, repositories, vendored files and
  dependencies, each with its own licence and conditions; keep it, and keep `LICENSE`, in the
  fork. Among them: PyMuPDF is AGPL-3.0-or-later or commercially licensed by Artifex; the
  SOLIDWORKS interop assemblies are Dassault Systèmes property and are never redistributed; and
  several repositories that were studied carry restrictions on reuse, which NOTICE.md records.
- Whether and how these conditions apply to the fork's own additions, to how the fork is
  deployed inside the organisation, and to anything the fork distributes, is a question for that
  legal review.
