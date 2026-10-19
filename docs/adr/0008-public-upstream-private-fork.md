# ADR-008: Public upstream, private downstream fork

**Status:** Accepted
**Date:** 2026-10-18
**Deciders:** the project owner

## Context

The repository `coleas33/smart_SW` is public and licensed under the GNU Affero General Public
License v3.0 or later (`LICENSE`; `NOTICE.md` lists what it references, vendors and depends on).
A company that uses the product has private material the product needs to be useful there:
standards profiles, templates, part-number patterns, title-block rules, and real drawings and
designs. The repository already keeps such material out: the real standards profile lives
outside the repository and only `config/standards.example.yaml` is committed (006
`quickstart.md`, "Setting up the profile"), and owner decisions 11B, 13A and 16A keep design
numbers, folder names and people's names out of every tracked file, checked by a test.

This decision was taken by the owner on 2026-10-18 and is recorded here for the first time.

## Decision

- The repository stays public as the open-source upstream under AGPL-3.0, with `NOTICE.md` kept.
- A company forks it into an internal organisation as a downstream.
- Private material - standards profiles, templates, part-number patterns, title-block rules, real
  drawings and designs - lives only in the fork, in its own files.
- The fork adds those files through documented extension points rather than by editing code, so
  merges from upstream stay clean.
- Generic fixes flow back upstream without company data.
- The public repository carries only fictional data.

## Consequences

- Every committed example stays fictional (`FICT-...` identifiers, the fictional fixtures), as
  `AGENTS.md` rule 2 already requires.
- Where a fork must supply private data, the upstream needs a documented extension point (a path
  read from settings, as `StandardsProfilePath` is today) rather than a value in code; the
  forking guide, [`docs/forking.md`](../forking.md), names them.
- A fix made in the fork is offered upstream only after its company data is removed.
- The constitution does not yet mention the fork; `AGENTS.md` refers to it ("see the constitution
  and `SECURITY.md` when it exists"), so a constitution amendment or a corrected reference is
  still to do.

## Sources

- The owner's decision of 2026-10-18 (this record).
- [`LICENSE`](../../LICENSE) and [`NOTICE.md`](../../NOTICE.md).
- [`AGENTS.md`](../../AGENTS.md), "Rules that are never bent", rule 2.
- [`specs/006-standards-check/quickstart.md`](../../specs/006-standards-check/quickstart.md),
  "Setting up the profile (for the owner, on the workstation)".
- `reviewer/tests/unit/test_tracked_files_carry_no_recorded_number.py` (decisions 11B, 13A and
  16A); [decision log](../decisions.md).
