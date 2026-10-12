"""The case generator (feature 014 `specs/014-design-review-eval/contracts/generator.md`).

Every committed fictional case - its package, answer key, case file and set entry - is written
from one case spec by `python -m tests.benchmark_cases.generate`, through the formats' data-only
models and the fictional builders under `tests/support/`, never from check output (FR-027,
GN-1). `spec` holds the case spec and its checks, `seeds` the seed kinds, `designs` one module
per design, `stamps` the held-out stamp, `vocabulary` the case vocabulary, `render` the
renderers and `generate` the run.
"""
