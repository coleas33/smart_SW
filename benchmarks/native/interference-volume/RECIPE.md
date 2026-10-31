# `interference-volume`: two made-up cubes that overlap by 1000 mm3

Two copies of one 20 mm cube, the second moved 10 mm along each axis, built by hand in
SOLIDWORKS 2024 SP5 at the seat in the stage 1 sitting's optional 25-minute block (owner decision
172A). They overlap in a 10 x 10 x 10 mm block, **1000 mm3**, so the number
`swreview-extract interference` records for that pair says which unit `IInterference.Volume`
answers in - undocumented, and recorded as m3 with a gap until a seat measures it
(`InterferenceRunner.VolumeUnitVerified`, feature 001's T069; `specs/001-agentic-design-review/research.md`
R12, open question 5, and R15). `swreview seat volume-unit` judges it.

**Nothing built from this recipe is ever committed, and it is not built in this folder.** Make
the files, and the package the extractor writes, in a folder of your own outside the checkout
(for example `Documents\made-up-seat\`): an untracked file in the checkout makes the next
`update-workstation.ps1` refuse the tree, and the repository is public. This folder holds the
recipe only.

## Files (outside the checkout)

| File | Contents |
|------|----------|
| `VOL-CUBE.SLDPRT` | A 20 mm cube with one corner on the origin. |
| `VOL-OVERLAP.SLDASM` | Two instances of the cube, the second moved by (10, 10, 10) mm and fixed there. |
| `package\` | What `dump` and `interference` write; it goes in the sitting's handover folder, not the checkout. |

## Build steps (about ten minutes)

1. New part from the default part template, **millimetres (MMGS)**. Sketch a 20 x 20 mm Corner
   Rectangle on the Top Plane from the origin, and extrude it 20 mm. Save it as `VOL-CUBE.SLDPRT`
   in your folder.
2. New assembly from the default assembly template, millimetres. Insert `VOL-CUBE.SLDPRT` at the
   origin: the first component is fixed.
3. Insert `VOL-CUBE.SLDPRT` again anywhere. **Move Component**, choose **To XYZ Position**,
   select a face of the second cube (a face, not a vertex, so that its origin is what moves), set
   **X 10 mm, Y 10 mm, Z 10 mm** and Apply. Its origin is now 10 mm from the first cube's along
   each axis, so the two overlap by 10 mm along each. Right-click it, **Fix**. Do not mate them.
4. Check the geometry the way SOLIDWORKS shows it: **Tools, Evaluate, Interference Detection**,
   Calculate. One interference, between the two cubes, reading **1000 mm^3**. If it reads
   anything else, the move in step 3 is off: redo it. Close the dialog without changing anything.
5. Save the assembly as `VOL-OVERLAP.SLDASM` in your folder and keep it open and active.

## Using it

```powershell
# VOL-OVERLAP.SLDASM open and active in SOLIDWORKS
swreview-extract dump --out "<your folder>\package"
swreview-extract interference --pairs all --out "<your folder>\package"
cd '<repo>\reviewer'
uv run swreview seat volume-unit "<your folder>\package" --expected-mm3 1000
```

| It prints | What it means | What to do |
|-----------|---------------|------------|
| `unit: m3` | `IInterference.Volume` answers in cubic metres, as the extractor assumes. | Copy the `unit`, `reason` and `next` lines into the sitting's findings document; the owner makes the extractor change `next:` names (001 research R15). |
| `unit: mm3` | It answers in cubic millimetres; the extractor's label is wrong. | The same: record the three lines; the change `next:` names is the owner's. |
| `unit: inconclusive` | The number is neither, or there was not exactly one computed interference. The reason says which, and names cubic inches when the number is the overlap in those (an inch template). | Check step 4 and the templates' units, fix, and run the three commands again into a new folder. |

Afterwards close the assembly. Delete the files or keep them in your own folder, but never copy
them, or the package, into the checkout.
