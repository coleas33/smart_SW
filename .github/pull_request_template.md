## Summary

<!-- What changed and why, in a few sentences. -->

## Linked issue or feature task

<!-- For example: Closes #12, or Feature 010 T121. Name the owner decisions (112A) it applies. -->

## Checklist

- [ ] Complies with the constitution's Principles I-VI (`.specify/memory/constitution.md`).
- [ ] Tests first: a test that failed before the change and passes after it is named here, and no
      existing test was loosened.
- [ ] CI is green, and the local gates in `AGENTS.md` ("Gates before every commit", including
      its Python versions rule) pass.
- [ ] If anything under `extractor/` changed: `dotnet build` (zero warnings) and `dotnet test` of
      `extractor/SwReview.sln` pass on Windows with SOLIDWORKS 2024 installed; counts below.
      Not applicable otherwise.
- [ ] No real data in the change, its tests, its commit messages, this description or a
      screenshot: no real design, part or drawing number or file, no company, customer or
      person's name, no user or machine name, no vault, network or project path, no standards
      profile, template or sheet format, no recording, dump, run folder, handover folder or log
      from real work, and no key or other credential (`CONTRIBUTING.md`, "The public-repository
      rule").
- [ ] The feature's `spec.md`, `tasks.md` and `research.md` (and contracts) are updated where the
      change affects them.
- [ ] Line endings are LF: `git ls-files --eol` shows `i/lf` for every changed text file.

## Gate results

<!-- The test and lint counts, and the C# counts if they apply. -->
