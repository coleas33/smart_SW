# Pre-test readiness batch — 2026-09-20

The owner authorized this batch after reviewing the four recommendations. Ship it on
`codex/pretest-readiness-2026-09-20`, preserving the preceding handoff and reviewer fixes.
Live CAD probes, paid reviews, efficiency adoption, and remodel enablement remain testing
work; this batch makes those tests reproducible and refuses known-invalid remodel runs.

## Scope and acceptance

1. **Remodel preflight:** at runner entry, validate stage-1 calibration and plan eligibility before provider
   construction, bridge operations, or applying changes. Reuse the verification rule;
   regression tests must prove invalid inputs make no provider or write calls.
2. **Benchmark parity:** expose the existing explanation option in Review and benchmark
   CLI commands, record it independently in run provenance, and refuse mismatched sessions
   or study arms. Preserve legacy CLI defaults; testing pane behavior explicitly enables
   explanations. Token usage and timing already include the presentation request.
3. **Compact queries:** provide bounded, selectable evidence pages behind a default-off
   experiment. Preserve existing tool behavior when off. Stable IDs and continuation
   metadata must let callers retrieve omitted evidence without treating omission as absence.
4. **Local handoff:** export an explicit run folder through an allowlist into a new ZIP,
   with a manifest, build/settings/coverage/usage information, hashes, and missing artifacts.
   Exclude machine settings and credentials, reject escaping links, and never overwrite.
   The bundle is local engineering evidence and may contain design names and paths.

## Implementation and verification

Independent agents own remodel preflight, compact queries, and the handoff module. The
primary agent owns CLI integration, benchmark parity, integration checks, and release.
Use existing fixtures and fake providers/bridges; run focused tests first, then Python
lint/full offline tests and the C# solution tests for the combined changes. Publish the
branch only after reviewing the staged files; real design dumps, logs, settings, generated
test outputs, and credentials are excluded from Git.

Completed local verification: 6,829 Python tests passed (4 skipped, 6 live tests
deselected), 1,843 extractor tests passed, and 1,288 add-in tests passed. Python lint,
the whitespace check, and an artifact audit for the CI sentinel credential passed.
Live testing and held-out efficiency measurements remain in the testing handoff.

## Constitution check

- I/II: missing evidence stays explicit; no new model-derived engineering numerics.
- III: regressions cover refusal boundaries, pagination completeness, comparison parity,
  and archive input/output constraints alongside the implementation.
- IV: existing evidence IDs and records remain authoritative; no IR schema change.
- V: reuse existing validation, settings, usage, and redaction code; no general framework.
- VI: reports and coverage remain inspectable; experimental savings are not claimed before
  held-out validation. Handoff exports identify incomplete evidence.

No document mutation permission or tolerance calibration is added by this batch.
