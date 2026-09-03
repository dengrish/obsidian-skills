# Choosing and captioning figures and rebuilt tables

- [What is eligible](#what-is-eligible)
- [Which ones to carry](#which-ones-to-carry)
- [Where they go](#where-they-go)
- [What the caption says](#what-the-caption-says)
- [Panels](#panels)
- [When the figure you need is not there](#when-the-figure-you-need-is-not-there)
- [Rebuilt tables](#rebuilt-tables)

Read when the inventory contains figures or a result merits a rebuilt table.
This reference owns exhibit selection, captions and table fidelity. [Note
format](note-format.md) owns the complete note shape.

## What is eligible

Only files that are already in `Sources/Images/` under this PDF's stem. The scan lists them; nothing else is embeddable.

- **Never invent a filename.** An embed of a file that does not exist renders in Obsidian as ordinary text — no broken-image marker, no error, nothing. It is the most silently-wrong thing this skill can write.
- **Never extract, crop or rename one.** PDF figure cropping has exactly one implementation in this plugin, in `pdf-figure-extractor`, and a second copy is the bug the shared layer exists to prevent (`CONVENTIONS.md` §8b).
- **Do not re-run extraction during drafting.** Prepare the figure inventory during [intake](../SKILL.md#1-select-and-inventory-the-work), before selecting exhibits. An unresolved extraction gap is reported; carry the supported claim in prose.

The scan matches on `[source_stem]_fig` and accepts any extension, which is §8a's consumer glob exactly. Matching the tighter `_fig_` instead would make figures written before this plugin's naming converged invisible — and invisible in the way that raises nothing (`CONVENTIONS.md` §8a, §8c).

**Labels are the caption's figure numbers, not sequence numbers.** `..._fig_3.png` is the paper's Figure 3. `..._fig_1-2.png` is Figure 1.2 with the dot written as a dash. `..._fig_S1.png` is a supplementary figure, and `Supplementary Figure 1`, `Suppl. Fig. 1`, `Supp. Figure 1` and `Extended Data Figure 1` all land there by default (`CONVENTIONS.md` §8b).

The scan identifies legacy panel files with `panel_of`; use the [panel rules](#panels) below when those files appear.

The label selects the file but does not appear in the prose or caption. Place the picture beneath the claim it supports instead of introducing a second figure-number reference.


## Which ones to carry

**Use only the figure embeds the explanation needs: usually zero to three, with four as a hard cap.** A note with every figure is the paper again, and the reason to summarise was that the reader was not going to read the paper. Zero is correct when prose fully carries the result or the available figures are irrelevant. **The cap counts embeds, not source figure identities** — three panels of one figure are three of your four, not one, and a note that reaches the cap that way is showing one figure and calling it a summary.

Take the figures that **are** the finding:

- the main result — the effect the abstract is about;
- the comparison that makes the result mean something;
- the one image a specialist would point at if asked "what did you actually see?".

Skip: study-flow and CONSORT diagrams, apparatus photographs, architecture schematics, maps of where the samples came from, and any figure whose content is a table. **Unless the method is itself the contribution** — for a paper whose result is a technique, the schematic *is* the finding, and it goes in *Results* under the claim about what the technique does. Even a method schematic belongs in *Results* under the contribution it illustrates; `note_lint.py` checks this placement.

**The tiebreak, when several look equally central**, is how often the body text refers to each one:

```bash
python3 '<skill>/scripts/paper_text.py' '<pdf path>' --cites
```

It counts every mention on every page, expanding compact plural lists and
ranges; the figure's own caption is included, so each figure starts one ahead —
read the counts as a ranking, not a measurement. **Pass the same `--ed-prefix`
the extraction run used**: `Extended Data Figure 1` is filed as `S1` by default
and as `ED1` under `--ed-prefix ED` (`CONVENTIONS.md` §8b), and a mismatch
scores it under a label no file on disk carries, so it reads as never cited.

Use the counts only to break a tie between substantively relevant figures, not to replace reading them.

**A supplementary figure can outrank a main one.** Papers routinely put the honest version of a result — the per-subject data, the sensitivity analysis, the failure cases — in the supplement. If that is the figure a reader needs, carry it and say in the caption that it is supplementary.


## Where they go

Each figure sits in *Results*, **directly under the claim it supports** — not collected in a gallery at the end, and not before the sentence that gives the reader a reason to look at it. A figure the surrounding text does not refer to is decoration.

The shape, exactly:

```
![[Doe_GutMicrobiome_2025_fig_2.png]]
*The two arms separated within a fortnight and stayed apart to week 8. Curves show time to first recurrence in 219 previously treated adults, transplant versus placebo. Numbers still at risk appear below each week.*
```

- A **bare wikilink embed** — Obsidian resolves it by basename anywhere in the vault, which is safe here because `pdf-organizer` guarantees the stem is unique (`CONVENTIONS.md` §1a).
- The caption on the **line immediately below**, italic, **no blank line between them** — a blank line makes Obsidian render them as two unrelated blocks.
- No `> [!Figure]` callout, no HTML, no width attribute.


## What the caption says

**One message per figure, and the message comes first.** The caption's first sentence is what the reader should take away. The second says what they are looking at. That order is the whole rule, and it is the one publishers' style guides converge on.

- **Fails:** *Kaplan–Meier curves for the two arms.* (says what it is, not what it shows)
- **Fails:** *Survival.* (a label, not a caption)
- **Fails:** *Figure 2 — The two arms separated inside the first fortnight…* (right message, but the number is banned — see below)
- **Holds:** the example above leads with the difference and then identifies population, comparator and display.

**The caption must stand alone.** A reader who scrolls the note reading only figures and captions should come away with the paper's argument. That means the caption carries its own scope clause and its own numbers, even where the paragraph above already has them.

**The four claim rules apply inside a caption too** ([summary standards](summary-standards.md#the-four-claim-rules-in-full)). A caption is where a hedge most often goes missing, because captions are written last and read as neutral description. "Treatment worked" under a figure is the same overstatement it would be in a sentence.

**Write it from the figure, not from the paper's caption.** The published caption is written for someone who has read the methods; it names panels and variables and assumes the design. Read what the figure actually shows, then say that. Where the published caption defines something you need — units, what an error bar is, what n is — take that and put it in the second sentence.

**Say what the error bars are.** Standard deviation, standard error and a 95% confidence interval are three different pictures, and a reader cannot tell them apart by eye. If the paper does not say, the caption says it does not.


## Panels

The extractor writes whole figures. Existing vaults can also contain legacy panel files: `..._fig_3a.png` is panel a beside the composite `..._fig_3.png`. The scan lists both and marks a panel with `panel_of: "3"`; the composite has `panel_of: null`. These legacy panels remain eligible.

**Default to the whole plate.** A figure's panels were laid out together because they argue together, and a reader meeting panel b alone has lost the comparison it was set against. Where the note's surrounding claim is about the whole argument, embed the composite and name the panel in the prose or the caption — *"the comparison that matters is the middle row: …"* — naming the panel by what it shows rather than by a figure number, which no caption carries ([note format](note-format.md#complete-shape)).

**Take a single panel when the claim under it is that panel's alone**, and the composite would bury it. The test is whether the other panels bear on the sentence the figure sits under. A plate carrying a method schematic, two structures and a supervision sweep, embedded under a claim about supervision, is three-quarters decoration; the sweep panel on its own is the exhibit. This is the case per-panel files exist for, and it is a minority of embeds.

**Never both.** A composite and a panel of it under one claim is the same picture twice, and the panel is inside the plate directly above it.

**Panels do not inflate the counts.** The four-embed cap counts embeds, so three panels of one figure are three of the four (above). And an unplaced panel is **not** an unused figure: placing the composite discharges every panel under it, placing any panel discharges the composite, and the report's "figures available but not used" count is over composites only. A paper whose 4 figures yielded 27 files has 4 exhibits, not 27.


## When the figure you need is not there

If intake never prepared an inventory for a paper with figures, return to
[intake](../SKILL.md#1-select-and-inventory-the-work). Do not make a new
extraction path inside drafting. If extraction already ran, inspect its actual
diagnostics and report a missing caption/output, scan limitation or failed
extraction honestly.

A table is not an extracted figure: rebuild it below when it carries the result.
For another unavailable exhibit, carry only the claim supported by the source
in prose with its page citation. Never substitute a nearby figure, invent an
embed or point at the missing figure's number. The report names the gap and any
follow-up extraction needed. Publication still requires source verification and
clean lint; missing media does not waive those gates.

## Rebuilt tables

Rebuild a table from the PDF when the comparison is part of the note's argument. The figure extractor does not produce tables; pointing at an unseen table is not a substitute for including its result.

**Rebuild when the table *is* a claim the note makes.** The primary outcome, the head-to-head comparison, the harms. Not when two numbers and a comparator fit in a sentence — a two-row table is a sentence wearing a border.

The shape, exactly, and it mirrors the figure shape:

```
| Tillage | Soil carbon, 0-30 cm (t/ha) |
|---|---|
| No-till | **48.1** |
| Conventional | 41.6 |
*No-till plots held about 6 t/ha more soil carbon after twelve years on this Iowa farm. Final means cover two of four regimes. The other regimes and per-depth rows are omitted.*
```

- **In *Results*, under the claim it supports.** Same rule as a figure, and `note_lint.py` enforces it.
- **Italic caption on the very next line**, no blank line between — again as for a figure, and for the same rendering reason.
- **No table number**, in the caption or anywhere else.
- **Values verbatim.** Copy the digits the paper printed. Do not round, rescale, convert units, or recompute an average from the subset of rows you kept: a recomputed number is one the [verification finder](review-checklist.md#locate-the-claims) cannot locate, and the paper never made that claim. Bolding the row or cell the claim is about is fine — that is emphasis, not arithmetic.
- **Trim to what the claim needs, and say so in the caption.** A 28-row benchmark becomes its four group averages; a 12-column table becomes the three columns compared. **A trimmed table that does not announce the trim is the most misleading thing this note can contain**, because unlike a vague sentence it looks complete and precise. One clause fixes it: *"the four task groups; the 28 subtasks are in the paper"*.
- **Keep the paper's orientation** — systems in columns if that is how the paper set them, rows if not. Transposing is a silent re-presentation, and two tables under two orientations read as two notes.
- **Four tables at most, one or two preferred.** Across both forms, aim for no
  more than about five total figure embeds plus rebuilt tables. That combined
  number is a brevity target rather than permission to exceed either form's
  separate four-item cap; use fewer whenever prose carries the result clearly.

**Where a trim would change the reading, do not trim — cut the table.** If the rows you would drop are the ones that disagree with the claim, keeping only the agreeing rows is not a summary, and no caption clause repairs it. Report the comparison in prose with both directions named, or rebuild the whole thing.
