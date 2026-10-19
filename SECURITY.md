# Security policy

## Supported versions

smart_SW is a pre-release pilot with no tagged releases. Only the current `main` branch is
supported: a fix lands on `main`, and there are no older versions to patch.

## Reporting a vulnerability

Report it privately, through GitHub's private vulnerability reporting: open the repository's
**Security** tab and choose **Report a vulnerability**. The report reaches the maintainer only.

Please do not:

- open a public issue, pull request or discussion about the vulnerability;
- post an API key, a token or any other credential anywhere, including in the private report
  (if a key was exposed, revoke it with its provider first, then report);
- attach a real design, drawing, standards profile, recording, run folder or a log that names
  real paths. Reproduce the problem with the fictional fixtures in the repository
  (`benchmarks/packages/`, `reviewer/tests/fixtures/replay/`, `config/standards.example.yaml`)
  wherever you can.

Include what you found, the commit you found it on (`git rev-parse --short HEAD`), how to
reproduce it, and what an attacker could do with it. This is a one-maintainer project with no
fixed response time.

## Scope

In scope is anything in this repository that could expose a secret or private data, or let the
product change a document it should only read:

| Area | What counts |
|---|---|
| Key handling | A provider key reaching a file, a command line, a log, a run folder or a request it should not; the DPAPI-protected settings (`%APPDATA%\SwReview\settings.json`) being readable or writable in a way they should not be; a gap in `swreview audit-secrets`. |
| The read-only guard | Any path by which the reviewer, a check, a tool given to a model or an add-in command writes to a SOLIDWORKS document, beyond the two bounded exceptions the constitution names (feature 003's suppress test and feature 004's re-modeler copy). |
| The send gate | A review, or any of its content, reaching the language model while the Review tab's send checkbox is unticked and Send to model has not been pressed (feature 015). |
| Private data leaking into the repository | Anything in the code, the tests or the tooling that writes a real design, path, profile, user name or key into a tracked file or a committed fixture, or a gap in the checks that keep them out. |
| The local backend and proxy | The Task Pane's loopback backend, its per-launch secret, the in-process tool service and the same-origin proxy: anything that lets another process or page on the machine, or a remote host, call them or read their traffic. |
| The read-only MCP toolset and the terminal | A way for an external CLI connected through `swreview mcp` or the terminal tab to run a shell command, write a file or reach beyond its allowlist. |

Out of scope: vulnerabilities in SOLIDWORKS itself, in a language-model provider's service, or
in a third-party dependency that is not specific to how this project uses it (report those
upstream; a dependency that this project uses unsafely is in scope).

How the boundaries are drawn is described in the security section of
[`docs/architecture.md`](docs/architecture.md); the constitution
([`.specify/memory/constitution.md`](.specify/memory/constitution.md)) states the read-only rule
and its exceptions.
