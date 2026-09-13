# cover-blind-tap

Day-one benchmark package for User Story 1 (exported files only).

## Seeded conditions

- Housing drawing (`drawings/housing.pdf`, DRW-2001): four M6x1.0 tapped holes called out
  with **drill depth 14 only**; usable thread depth is not specified. Expected result: the
  fastener bottoming/engagement check is `unresolved` with an evidence request for usable
  thread depth. It must not be cleared.
- Cover drawing (`drawings/cover.pdf`, DRW-2002): page 1 has a text layer; **page 2 is
  flattened** (no text layer). Expected result: page 2 is `parse_status: no_text` with a gap
  and unresolved coverage for anything it governed.
- Cover thickness 8.0 ±0.1, counterbore Ø11 depth 6.5; screws M6 x 20 (4x). With a 6.5 mm
  counterbore the clamped stack under the head is 1.5 mm, so the screw protrudes 18.5 mm
  into a hole drilled 14 deep: a bottoming risk that only becomes `demonstrated` once usable
  thread depth is supplied.

## Timing

- Human baseline review: _to be recorded_ (minutes)
- Assisted supervision / verification / false-alarm handling: _to be recorded_

## Results

- 2026-09-12: package built with `swreview ingest` from the manifest, BOM and generated
  PDFs. `swreview validate` reports 6 documents, 6 components, 2 gaps (placeholder persist
  refs for BOM-derived instances; DRW-2002 page 2 has no text layer), 0 discrepancies.
  Parsed dimensions include the seeded `4X M6x1.0 - 6H ↧ 14` callout (drill depth only).
- The agent review (`swreview review`) has not been run: no Anthropic credentials were
  available on this machine. Run it with `ANTHROPIC_API_KEY` set (or after `ant auth login`)
  and record the session id, findings, open evidence requests and coverage here, plus the
  baseline and assisted times.
