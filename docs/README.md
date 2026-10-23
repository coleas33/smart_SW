# Documentation index

The project's documentation, grouped by who is reading. Every file directly in `docs/` is listed
once below. The authoritative statement of what a feature does is its spec package under
[`specs/`](../specs/README.md); the documents here explain, guide or record.

## Engineers at the pilot workstation

| Document | What it is |
|---|---|
| [`test-plan-2026-09-27/README.md`](test-plan-2026-09-27/README.md) | The current test plan for the licensed seat: what to read, in what order, and where the sitting starts. The folder holds the step-by-step [test plan](test-plan-2026-09-27/workstation-test-plan.md), the [handover](test-plan-2026-09-27/workstation-handover.md) and the blank [results sheet](test-plan-2026-09-27/workstation-results.md). |
| [`workstation-runbook.md`](workstation-runbook.md) | Installing, updating and checking the add-in on the workstation: where the per-machine files live, health checks, failure modes met so far, and how findings come back. |
| [`addin-load-fix.md`](addin-load-fix.md) | The three causes of "the add-in is ticked but no Task Pane appears", and their fixes. |
| [`pane-backend-proxy.md`](pane-backend-proxy.md) | Why the Task Pane pages could not reach the loopback backend behind a web filter, and the same-origin proxy that fixed it (done 2026-09-16). |

## Developers

| Document | What it is |
|---|---|
| [`architecture.md`](architecture.md) | How the extractor, the add-in and the reviewer fit together, the security boundaries and the extension points. |
| [`glossary.md`](glossary.md) | The project's terms. |
| [`reviewer-guide.md`](reviewer-guide.md) | The command-line entry points, what a review reads first, the checks and the Task Pane tabs. |
| [`../specs/README.md`](../specs/README.md) | Every feature's spec package and its status. |
| [`decisions.md`](decisions.md) | The decision log: the owner's numbered decisions and the architecture decision records. |
| [`../CONTRIBUTING.md`](../CONTRIBUTING.md) | How to contribute: questions, issues, pull requests, the gates, the Spec Kit workflow and the public-repository rule. |
| [`../CODE_OF_CONDUCT.md`](../CODE_OF_CONDUCT.md) | The code of conduct (Contributor Covenant 2.1); conduct problems are reported privately through the repository's Security tab. |
| [`../AGENTS.md`](../AGENTS.md) | The shared guidance for coding agents, with the gates run before every commit. |
| [`llm-efficiency-options.md`](llm-efficiency-options.md) | The language-model efficiency options of feature 005 and the results ledger the benchmark commands render. |
| [`engineering-context-foundation.md`](engineering-context-foundation.md) | The design draft behind feature 016 (engineering context), including structures beyond its first slice. |
| [`review-backlog.md`](review-backlog.md) | Should-fix findings from the adversarial review rounds, left unapplied, with their later resolutions. |
| [`development-handoff-2026-10-21.md`](development-handoff-2026-10-21.md) | Restart record for the interrupted decisions 157A, 159A and 160A: recovered cleanup work, branch preservation points, review findings and the remaining gates. |

## Organisations forking the repository

| Document | What it is |
|---|---|
| [`forking.md`](forking.md) | Running a private downstream fork: where company material goes, syncing upstream, contributing fixes back, CI and keys in a fork, and the licence facts. |
| [`../SECURITY.md`](../SECURITY.md) | Supported versions and how to report a vulnerability privately. |
| [`../NOTICE.md`](../NOTICE.md) | Third-party references, vendored files and dependency licences. |

## Future work

None of these is a commitment; each says what was decided and what was not.

| Document | What it is |
|---|---|
| [`future-capabilities-roadmap-2026-10-14.md`](future-capabilities-roadmap-2026-10-14.md) | The current roadmap: the remaining evaluation and send-gate work, and preparation for automated drawings, engineer-confirmed load context and later Simulation integration. Documentation only. |
| [`drawing-creation-d0-inventory.md`](drawing-creation-d0-inventory.md) | D0, the inventory the roadmap asks for before any drawing-creation feature (reserved number 012) is specified. |
| [`feature-request-resolve-lightweight.md`](feature-request-resolve-lightweight.md) | A feature request raised at the workstation on 2026-09-19: let the engineer resolve lightweight components before a review, by choice. |
| [`future/llm-assistants-2026-09-28.md`](future/llm-assistants-2026-09-28.md) | Two language-model assistant ideas (a concept assistant and a hand-calc assistant), researched and estimated; idea only. |

## History

| Document | What it is |
|---|---|
| [`history/README.md`](history/README.md) | Dated records kept as written: the original pilot proposal, workstation findings, handovers, status notes, feedback rounds and the September roadmap. |
| [`adr/README.md`](adr/README.md) | The architecture decision records, numbered. |
