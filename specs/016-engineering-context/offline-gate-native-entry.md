# Pane context offline gate — 2026-10-14

Delivered on `016-engineering-context` after the offline foundation. This slice adds
saved-evidence preparation, requirement/total-force entry, explicit confirmation,
selection-assisted target prefill and exact context attachment in the Review pane.
The [quickstart](quickstart.md) describes the operator flow;
[pane-context.md](contracts/pane-context.md) defines its messages/routes and boundaries.

## Final verification

| Gate | Result |
|---|---|
| Forced Release solution rebuild, .NET SDK 9.0.304 | Passed; zero warnings and errors |
| Full extractor suite | 9,086 passed; zero skipped |
| Full add-in suite after the final pane fixture regeneration | 2,227 passed; zero skipped |
| Full Python nonlive suite with `SWREVIEW_REQUIRE_TOKENIZER=1` | 15,625 passed; 5 skipped; 7 live tests deselected; 570.93 seconds |
| Ruff over reviewer `src` and `tests` | Passed |
| Git staged whitespace check | Passed |

Python's two existing warnings are the Starlette/AnyIO deprecation and the serializer
warnings in the deliberately invalid-IR regression. The additional context symlink
test skips because the Windows test account lacks link-creation privilege; existing
store link/reparse regressions remain in the full suite. No SOLIDWORKS application,
paid provider or private handoff/profile is needed for these checks.

The extractor result came from the full Release solution test run. Subsequent fixes
affected the host/page, display contracts and generated add-in fixture; the complete
add-in suite was rerun against the final state. No extractor source changed afterward.

## Behavioral failures and independent review

Tests failed before entry routes and selection/pane implementations existed. Further
tests reproduced these concrete defects before their fixes:

- A positive native reference comparison could hide an indeterminate/missing competitor.
  Explicit tri-state comparison now refuses uncertain uniqueness. Unavailable/cyclic
  ancestry, changed selection/occurrence and late dirty state are also tested.
- A document notification during extraction could republish prepared context after the
  same document/configuration returned. Generation checks now invalidate that scope,
  including notifications during later scope reads before selection/provider calls.
- Live checks-first evidence updates could leave the opening/saved context summary
  showing the previous baseline. Summaries now reassess after those checks; historical
  confirmation remains separate from changed evidence applicability.
- Target projection exceeded its bounded label work, and reserved reference-like IDs
  could leak through operator fields. Projection now indexes once, constructs at most
  500 target labels, counts omissions and masks/refuses those identifiers.
- Withheld-path exceptions escaped neutral refusal, and a review waiting for an engineer
  allowed context edits. Both paths now refuse before loading/mutating context.

Offscreen WebView tests exercise literal hostile-text rendering, blank versus zero force,
partial vectors, frame axes/origin and root point, exact confirmation digests, explicit
edit gestures, late replies, stale previews, visible omissions and reuse without another
extraction. Native fake tests verify scoped identities and unchanged selection; they
do not establish actual native behavior.

The shared error labels and committed pane fixture were synchronized with the existing
`tests/fixtures/pane/generate_pane_fixture.py --write` generator. Fixture freshness and
privacy checks passed before the final full regression.

## Open workstation gate

T010/T015 remain open. The adapter always reports `native_calibrated: false` and
`freshness: cannot_establish`. A saved input confirmation does not certify live geometry,
carry approval across an extraction, apply Simulation loads or authorize drawing writes.
Run the [workstation checklist](native-entry.md#workstation-gate-still-required) on the
SOLIDWORKS machine and record native identity/configuration/dirty-state observations
before advancing calibration or freshness. Existing native capability switches remain
unchanged.
