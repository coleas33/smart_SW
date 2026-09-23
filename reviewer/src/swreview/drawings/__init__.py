"""Native drawing evidence, read as the checks need it (feature 011).

Pure readings of the package that `checks/`, `tools/` and the command line all consume, which
is why they are neither checks nor tools (`plan.md`, Structure Decision):

- `evidence` - which views show which document, and which of them a check may use;
- `native` - one conversion of a display dimension to the IR `Dimension` (from User Story 3);
- `binding` - which drawing record ties to which tolerance subject, behind the seat switch;
- `brief` - the bounded per-part brief (User Story 6).

Nothing here writes, loads a mesh or talks to SOLIDWORKS.
"""
