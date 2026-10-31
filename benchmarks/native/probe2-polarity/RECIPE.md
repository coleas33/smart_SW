# `probe2-polarity`: a made-up assembly that settles PROBE-2

One block, inserted three times into an assembly, built by hand in SOLIDWORKS 2024 SP5 at the
seat in the stage 1 sitting's optional 25-minute block (owner decision 172A). One instance is made
transparent, one is given an opaque appearance of the same colour, and one is left alone, so that
`swreview-extract probe standards` prints the nine appearance slots of all three and
`swreview seat transparency` reads which recorded value means transparent, and whether slot 7 is
the transparency slot on this build: feature 006's T102 (`specs/006-standards-check/research.md`
R2.8, R4 and R11).

**Nothing built from this recipe is ever committed, and it is not built in this folder.** Make
the files in a folder of your own outside the checkout (for example `Documents\made-up-seat\`):
an untracked file in the checkout makes the next `update-workstation.ps1` refuse the tree, and
the repository is public. This folder holds the recipe only.

## Files (outside the checkout)

| File | Contents |
|------|----------|
| `PROBE2-BLOCK.SLDPRT` | A 20 mm cube with no appearance of its own. |
| `PROBE2-POLARITY.SLDASM` | Three instances of the block, apart, two of them with a component-level appearance. |
| `probe-standards.txt` | What the probe printed; it goes in the sitting's handover folder, not the checkout. |

The decider finds the three instances by the names the probe prints: `PROBE2-BLOCK-1` is the
transparent one, `PROBE2-BLOCK-2` the opaque one and `PROBE2-BLOCK-3` the one left alone. The
FeatureManager shows them as `PROBE2-BLOCK<1>`, `<2>` and `<3>`. If an instance was deleted and
inserted again its number moves on; then pass the names the probe printed with `--transparent`,
`--opaque` and `--plain`.

## Build steps (about ten minutes)

1. New part from the default part template, millimetres (MMGS). Sketch a 20 x 20 mm Center
   Rectangle on the Top Plane, centred on the origin, and extrude it 20 mm. Give the part no
   appearance. Save it as `PROBE2-BLOCK.SLDPRT` in your folder.
2. New assembly from the default assembly template. Insert `PROBE2-BLOCK.SLDPRT` three times:
   the first at the origin (it is fixed), then two more, each clicked well to the right of the
   last so that no two blocks touch. Do not mate them.
3. **The opaque override, on `PROBE2-BLOCK<2>`.** Click the block in the graphics area, then the
   Appearances button (the sphere) in the context toolbar, and choose the row for the
   **component** - the instance in this assembly, `PROBE2-BLOCK<2>`, at the top of the list - not
   the part, a body or a face. In the Appearance PropertyManager set the colour by number to
   R 0, G 128, B 255. Switch to **Advanced**, open **Illumination** and leave **Transparent
   amount** at 0. OK.
4. **The transparent override, on `PROBE2-BLOCK<1>`.** The same way, on the component row: the
   same colour, R 0, G 128, B 255, and under **Advanced**, **Illumination**, **Transparent
   amount** 75 %. OK. This block, and only this one, now looks see-through; if all three do, the
   transparency went on the part: undo it, and set it on the component row.
5. **The control, `PROBE2-BLOCK<3>`.** Leave it alone: no appearance at any level.
6. Save the assembly as `PROBE2-POLARITY.SLDASM` in your folder and keep it open and active.

The two overrides must be the same colour, typed in by number: the decider asks that they differ
at the transparency slot and nowhere else, so a different colour reads as inconclusive. The
amount is 75 % rather than 50 % so that the transparent block's reading also shows the polarity
to the eye: 0.75 under `zero_is_opaque`, 0.25 under `one_is_opaque`, if the amount reaches the
slot as it reads. The decider takes the polarity from the opaque block alone and prints both.

## Using it

```powershell
# PROBE2-POLARITY.SLDASM open and active in SOLIDWORKS; the probe opens nothing and changes nothing
swreview-extract probe standards > "<your folder>\probe-standards.txt"
cd '<repo>\reviewer'
uv run swreview seat transparency "<your folder>\probe-standards.txt"
```

| It prints | What it means | What to do |
|-----------|---------------|------------|
| `verdict: zero_is_opaque` or `verdict: one_is_opaque` | The seat showed the polarity. | Copy the `verdict`, `reason` and three reading lines into the sitting's findings document; the owner makes the flip `next:` names (006 research R11). |
| `verdict: inconclusive`, reason starting `slot 7 refuted` | The two overrides are the same colour and read the same at slot 7 but differ at another slot, or have no slot 7: slot 7 does not carry the transparency on this build, so the dump reads the wrong slot. | Record it as it stands and stop: the fix is an extractor change, not the flip. |
| `verdict: inconclusive`, any other reason | A step above did not hold (the reason names it: overrides that differ nowhere, which is step 4 missed; a colour that differs; an override on the plain block; a block missing). | Fix that step, save, and run the two commands again. |

Afterwards close the assembly; nothing here was changed by the probe. Delete the files or keep
them in your own folder, but never copy them into the checkout.
