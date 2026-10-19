## Summary

<!-- What changed and why, in a few sentences. -->

## Linked issue or feature task

<!-- For example: Closes #12, or Feature 010 T121. Name the owner decisions (112A) it applies. -->

## Checklist

- [ ] Tests first: a test that failed before the change and passes after it is named here, and no
      existing test was loosened.
- [ ] The gates in `AGENTS.md` ("Gates before every commit") pass under Python 3.11 and 3.12.
- [ ] If anything under `extractor/` changed: `dotnet build` (zero warnings) and `dotnet test` of
      `extractor/SwReview.sln` pass on Windows with SOLIDWORKS 2024 installed; counts below.
      Not applicable otherwise.
- [ ] No real data: no real design, part or drawing number, company, customer or person's name,
      vault or network path, standards profile, recording, run folder, log or key, in the
      change, its tests, this description or a screenshot.
- [ ] The feature's `spec.md`, `tasks.md` and `research.md` (and contracts) are updated where the
      change affects them.
- [ ] Line endings are LF: `git ls-files --eol` shows `i/lf` for every changed text file.

## Gate results

<!-- The test and lint counts, and the C# counts if they apply. -->
