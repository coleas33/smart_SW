# `capabilities`: the seat evidence the build's switches are held to

The committed evidence for the three seat switches the build ships off (feature 004, research R27;
owner decisions 166A and 171A). Nothing here is written by a test or a build: a file is added by
hand, in a commit of its own, from a sitting on the pilot workstation. There is no evidence here
yet, so every switch stays off.

`reviewer/tests/unit/test_seat_switch_evidence.py` holds each switch to this folder in CI:

| Switch | Ships | May be true only with |
|---|---|---|
| `RemodelStart.SeatValidated` (`extractor/SwReview.Extractor/Rms/RemodelStart.cs`) | false | a probe ledger here that `swreview remodel ledger` judges ready, and the IDENTITY tolerance profile calibrated (004 research R13.3; decision 170A) |
| `DrawingOpenScope.SeatValidated` (`extractor/SwReview.Extractor/Sw/DrawingOpenScope.cs`) | false | `drawing-open.md`, probe D14's record (011 T077) |
| `DRAWING_BINDING_VALIDATED` (`reviewer/src/swreview/drawings/binding.py`) | `False` | `drawing-binding.md`, probes D6 and D8's record (011 T066) |

## Probe ledgers

A ledger is the `capabilities/remodel-<version>.yaml` that `swreview-extract probe remodel` writes
in its `--out` folder. Decision 171A lets one be committed here, because the probe measures only a
throwaway part it builds itself, once:

1. it was written by a build with 004 T335, which cuts every exception text to its type and
   HRESULT (`COMException 0x80004005`), never a message;
2. `swreview remodel ledger <file>` reads it without refusing - no string in it looks like a
   drive, UNC or POSIX path, and its version is the frozen interop's (`32.5.0`, as SOLIDWORKS
   2024 SP5 reports itself, or `32.5.0.48`);
3. the CI pins pass on it: the committable-path scanner (`reviewer/tests/support/local_paths.py`)
   finds no checkout, home or temporary folder in it, and every exception text in it is a type
   and an HRESULT.

Copy the ledger alone, never the run's `remodel-probe.log`, whose first line names the `--out`
folder. Keep each run in a folder of its own, named for the sitting and the run
(`<yyyy-mm-dd>-<run>/remodel-<version>.yaml`), since every run of one version writes the same file
name. Start's five probes (PROBE-1, 2, 3, 4 and 12) must be in one ledger: the reader judges one
file at a time (research R27.4).

## Drawing probe records

Feature 011's `probe drawings` prints a report of lines, not a record a test can read, and a report
with a D6 or D8 section carries design names and stays in the handoff folder (011
`contracts/probes.md` section 1). So each drawing switch needs a named file here, written on the
development machine from the report, holding only what 011 research R4 may hold - ids, counts,
member answers and enum numbers, never a name, path or value:

- `drawing-open.md`: probe D14's lines with every drawing replaced by `<drawing>`, and its own
  reading, `every answer as required` (011 `contracts/probes.md` section 4);
- `drawing-binding.md`: for each known callout of D6 and D8, its id, whether its attached face's
  reference equals the face phase's, and whether its name's shape matches the part's.

What makes either file sufficient stays T077's and T066's decision; the pin checks only that the
file is here when the switch is on.
