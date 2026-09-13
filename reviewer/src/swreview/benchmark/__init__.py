"""Benchmark harness: run the reviewer over withheld-answer-key packages and score it.

`benchmarks/answer_keys/` is never readable by the reviewer (constitution Principle VI,
FR-025). `sets.py` and `runner.py` only ever handle package paths; `answer_key.py` is the
one module allowed to read an answer key, and only `scorecard.py` calls it.
"""

from __future__ import annotations
