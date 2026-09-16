# Design Review Report: dsn:1

- Session: 11111111-2222-4333-8444-555555555555
- Model: gpt-5.6
- Provider: openai (effort medium sent as reasoning.effort=medium; key from env)
- Started: 2026-09-12T09:00:00+00:00
- Ended: 2026-09-12T09:30:00+00:00

## Manifest Discrepancies

No discrepancies between the manifest and the reviewed documents.

## Summary

- Total findings: 1
- By status: demonstrated: 1
- By severity: high: 1
- Open evidence requests: 0 of 0
- Coverage: Checked: 1, Skipped: 0, Unresolved: 0, Failed: 0, Out of Scope: 0

## Findings

### High

#### F-001: Screw bottoms in a blind tapped hole

- Check: fastener.bottoming
- Status: demonstrated
- Severity: high
- Configuration: Default
- Components: cmp:0001 (housing-1)
- Provenance:

  | Document | Vault Path | Version | Revision | Configuration |
  |---|---|---|---|---|
  | doc:2 | /Designs/housing.SLDPRT | 3 | A | Default |
- Observed: o
- Requirement: r
- Inputs: none
- Calculation: no calculation
- Tool result steps: 0
- Coverage limits: none
- Recommended action: a
- Group: none
- Captures: none
- Disposition: not yet dispositioned
- Exception: none
- Navigation: swreview://open?doc=doc:2&ref=Y21wOjAwMDE=


## Evidence Requests

No evidence requests.

## Coverage

### Checked

| Check | Scope | Reason | Error |
|---|---|---|---|
| fastener.bottoming | components: cmp:0001 | ran |  |

### Skipped

None.

### Unresolved

None.

### Failed

None.

### Out of Scope

None.


## Timing

- Baseline minutes: 90.0
- Assisted supervision minutes: 10.0
- Assisted verification minutes: 8.0
- False alarm handling minutes: 2.0
- Unattended runtime minutes: 25.0
- Net saved minutes: 70.0

## Investigation Trace

| Index | Tool | Status | Elapsed (s) |
|---|---|---|---|
| 0 | list_holes | ok | 0.25 |
