# Implementation plan

The reviewer owns a separate `engineering_context` package: immutable Pydantic models,
pure numeric/binding functions, private revision store and bounded read projection.
Existing `units` supplies the single Pint registry. CLI delegates to those functions;
`ToolContext` accepts explicit injection and the registry conditionally offers two reads.
No IR schema migration or C# change is required.

Constitution check: inputs remain separate from extracted facts; missing values stay
unknown; arithmetic is checked software; no CAD mutation or engineering verdict is
introduced. Tests precede or accompany code with behavioral red evidence. Fictional
fixtures avoid private handoff data. Offline matching cannot satisfy a native gate.

Verification proceeds through focused model/numeric, storage, binding and privacy/tool
tests; CLI end-to-end tests; default-tool schema regression; Ruff and the full nonlive
Python suite. An independent review examines confirmation invalidation, repeated
instances, storage failure and projection leakage before the branch is pushed.
