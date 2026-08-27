# Choosing and captioning the exhibits — figures, and rebuilt tables

**Read this when** step 1's scan listed at least one figure for this stem, or when the paper's result is a table. The first is a checkable condition — `paper_scan.py` prints the count per PDF before anything is written — and the second is decided in step 4.

The note carries pictures because a reader who is not going to open the paper still has to be able to see the result. Two things decide whether that works: **which** figures the note carries, and **what the caption says they mean**.

---

## What is eligible

Only files that are already in `Sources/Images/` under this PDF's stem. The scan lists them; nothing else is embeddable.

- **Never invent a filename.** An embed of a file that does not exist renders in Obsidian as ordinary text — no broken-image marker, no error, nothing. It is the most silently-wrong thing this skill can write.
- **Never extract, crop or rename one.** PDF figure cropping has exactly one implementation in this plugin, in `pdf-figure-extractor`, and a second copy is the bug the shared layer exists to prevent (`CONVENTIONS.md` §8b).
- **Never re-run the extractor mid-note** to get a figure you wanted. Finish the note without it, flag the gap in the report, and let the user decide — a figure extracted after the fact is a rewrite, not an addition.

The scan matches on `[source_stem]_fig` and accepts any extension, which is §8a's consumer glob exactly. Matching the tighter `_fig_` instead would make figures written before this plugin's naming converged invisible — and invisible in the way that raises nothing (`CONVENTIONS.md` §8a, §8c).

**Labels are the caption's figure numbers, not sequence numbers.** `..._fig_3.png` is the paper's Figure 3. `..._fig_1-2.png` is Figure 1.2 with the dot written as a dash. `..._fig_S1.png` is a supplementary figure, and `Supplementary Figure 1`, `Suppl. Fig. 1`, `Supp. Figure 1` and `Extended Data Figure 1` all land there by default (`CONVENTIONS.md` §8b).

**A label ending in a lowercase letter is a panel, and the composite is the default.** `..._fig_1a.png` is panel a of Figure 1, sitting in the same folder as the whole `..._fig_1.png`; the scan marks it with `panel_of: "1"` and marks the composite `panel_of: null` (`CONVENTIONS.md` §8b). Carry the whole figure. Reach for a single panel only when the claim in the note is that one panel's — "the eUniRep designs cluster away from wild type" wants panel d, not the six-panel plate that also carries the method schematic — and never carry both a figure and a panel of it, which is the same picture twice under one claim. **An unplaced panel is not an unused figure**, and it does not count as one anywhere in the report: placing the composite discharges every panel under it.

**The label picks the file and then stops.** It never reaches the note: a caption carries no figure number and neither does the prose around it (SKILL.md step 4). This is exactly why — there are two spellings of every label, the paper's (`Figure 1.2`) and the disk's (`_fig_1-2`), and a note that prints either one has taken on a second identity for the figure that nothing checks and that goes stale the moment an extraction runs with a different `--ed-prefix`. The picture sits under the claim it supports, which is the only pointer a reader needs.

---

## Which ones to carry

**Two or three. Four is the cap and it should feel like one.** A note with every figure is the paper again, and the reason to summarise was that the reader was not going to read the paper. **The cap counts embeds, not exhibits** — three panels of one figure are three of your four, not one, and a note that reaches the cap that way is showing one figure and calling it a summary.

Take the figures that **are** the finding:

- the main result — the effect the abstract is about;
- the comparison that makes the result mean something;
- the one image a specialist would point at if asked "what did you actually see?".

Skip: study-flow and CONSORT diagrams, apparatus photographs, architecture schematics, maps of where the samples came from, and any figure whose content is a table. **Unless the method is itself the contribution** — for a paper whose result is a technique, the schematic *is* the finding, and it goes in *Results* under the claim about what the technique does. **Every embed in the note sits in *Results*, with no exception** (SKILL.md step 11, rule 8): one section owns the pictures, and `note_lint.py` rejects an embed anywhere else.

**The tiebreak, when several look equally central**, is how often the body text refers to each one:

```bash
python3 '<skill>/scripts/paper_text.py' '<pdf path>' --cites
```

It counts every mention on every page, the figure's own caption included, so a figure with a long caption starts one ahead — read the counts as a ranking, not a measurement. **Pass the same `--ed-prefix` the extraction run used**: `Extended Data Figure 1` is filed as `S1` by default and as `ED1` under `--ed-prefix ED` (`CONVENTIONS.md` §8b), and a mismatch scores it under a label no file on disk carries, so it reads as never cited.

A figure the paper keeps returning to is the figure carrying its argument. This is a heuristic and it is offered as one — there is no authoritative rule for which figure is a paper's argument, and inventing one would be worse than naming the gap.

**A supplementary figure can outrank a main one.** Papers routinely put the honest version of a result — the per-subject data, the sensitivity analysis, the failure cases — in the supplement. If that is the figure a reader needs, carry it and say in the caption that it is supplementary.

---

## Where they go

Each figure sits in *Results*, **directly under the claim it supports** — not collected in a gallery at the end, and not before the sentence that gives the reader a reason to look at it. A figure the surrounding text does not refer to is decoration.

The shape, exactly:

```
![[Doe_GutMicrobiome_2025_fig_2.png]]
*The two arms separated inside the first fortnight and stayed apart to week 8. Kaplan–Meier curves for time to first recurrence, transplant against placebo, with the number of patients still at risk printed below each week.*
```

- A **bare wikilink embed** — Obsidian resolves it by basename anywhere in the vault, which is safe here because `pdf-organizer` guarantees the stem is unique (`CONVENTIONS.md` §1a).
- The caption on the **line immediately below**, italic, **no blank line between them** — a blank line makes Obsidian render them as two unrelated blocks.
- No `> [!Figure]` callout, no HTML, no width attribute.

---

## What the caption says

**One message per figure, and the message comes first.** The caption's first sentence is what the reader should take away. The second says what they are looking at. That order is the whole rule, and it is the one publishers' style guides converge on.

- **Fails:** *Kaplan–Meier curves for the two arms.* (says what it is, not what it shows)
- **Fails:** *Survival.* (a label, not a caption)
- **Fails:** *Figure 2 — The two arms separated inside the first fortnight…* (right message, but the number is banned — see below)
- **Holds:** the example above — and it is the same caption `SKILL.md` step 4 and `references/worked-example.md` carry, word for word, because one example with three spellings is the drift this plugin keeps finding.

**The caption must stand alone.** A reader who scrolls the note reading only figures and captions should come away with the paper's argument. That means the caption carries its own scope clause and its own numbers, even where the paragraph above already has them.

**The four claim rules apply inside a caption too** (SKILL.md step 3). A caption is where a hedge most often goes missing, because captions are written last and read as neutral description. "Treatment worked" under a figure is the same overstatement it would be in a sentence.

**Write it from the figure, not from the paper's caption.** The published caption is written for someone who has read the methods; it names panels and variables and assumes the design. Read what the figure actually shows, then say that. Where the published caption defines something you need — units, what an error bar is, what n is — take that and put it in the second sentence.

**Say what the error bars are.** Standard deviation, standard error and a 95% confidence interval are three different pictures, and a reader cannot tell them apart by eye. If the paper does not say, the caption says it does not.

---

## Panels

Earlier `pdf-figure-extractor` runs (panel splitting was retired 2026-08-16; the extractor now writes whole figures only) wrote a multi-panel figure twice over: the whole plate as `..._fig_3.png`, and one file per lettered panel beside it as `..._fig_3a.png`. Those per-panel files remain in vaults and stay usable, `..._fig_3b.png` and so on (`CONVENTIONS.md` §8b). Both answer the `_fig` glob, so the scan lists both, and choosing between them is a decision this file makes rather than one the folder makes for you.

**Default to the whole plate.** A figure's panels were laid out together because they argue together, and a reader meeting panel b alone has lost the comparison it was set against. Where the note's surrounding claim is about the whole argument, embed the composite and name the panel in the prose or the caption — *"the comparison that matters is the middle row: …"* — naming the panel by what it shows rather than by a figure number, which no caption carries (SKILL.md step 4).

**Take a single panel when the claim under it is that panel's alone**, and the composite would bury it. The test is whether the other panels bear on the sentence the figure sits under. A plate carrying a method schematic, two structures and a supervision sweep, embedded under a claim about supervision, is three-quarters decoration; the sweep panel on its own is the exhibit. This is the case per-panel files exist for, and it is a minority of embeds.

**Never both.** A composite and a panel of it under one claim is the same picture twice, and the panel is inside the plate directly above it.

**Panels do not inflate the counts.** The four-embed cap counts embeds, so three panels of one figure are three of the four (above). And an unplaced panel is **not** an unused figure: placing the composite discharges every panel under it, placing any panel discharges the composite, and step 12's "figures available but not used" count is over composites only. A paper whose 4 figures yielded 27 files has 4 exhibits, not 27.

---

## When the figure you need is not there

Finish the note, then say so in the report. In order of likelihood:

- **The extractor has not run over this PDF.** The scan shows zero figures for a stem that clearly has some. **Step 1 handles this and it does not reach here** — it runs `pdf-figure-extractor` over the PDF and re-scans before step 2, because a figure added after step 4 has chosen is a rewrite. If you are reading this line with an empty inventory, step 1 was skipped; go back to it rather than extracting from here.
- **The extractor ran but missed this caption.** Its own run summary reports this as PARTIAL detection — the body text cites a figure number no caption matched. That report is the only witness; nothing downstream can see the gap.
- **The figure is a table.** Tables are never extracted to `Sources/Images/` and never will be. Two numbers go in prose under a page citation; a table that *is* a result gets **rebuilt** as markdown (below). What is never acceptable is describing a table the reader cannot see, or pointing at its number.
- **The PDF is a scan.** Nothing was extracted because nothing could be. `references/edge-cases.md`.

In every case the note is written without the figure and the gap is named. A note that silently has no pictures reads as a paper that had none.

---

## Rebuilt tables

A figure is embedded; a table is **rebuilt**, because nothing extracts tables and nothing ever will. For a paper whose results are tabular — most benchmark papers, most trials' primary-outcome tables — this is the only way the result reaches a reader of the note at all, and skipping it while writing "the paper's Table 2 has the comparison" is the exact failure the self-containment rule exists to stop.

**Rebuild when the table *is* a claim the note makes.** The primary outcome, the head-to-head comparison, the harms. Not when two numbers and a comparator fit in a sentence — a two-row table is a sentence wearing a border.

The shape, exactly, and it mirrors the figure shape:

```
| Tillage | Soil carbon, 0-30 cm (t/ha) |
|---|---|
| No-till | **48.1** |
| Conventional | 41.6 |
*No-till plots held about 6 t/ha more carbon after twelve years. Mean soil organic carbon at the final sampling, two of the four tillage regimes; the other two and the per-depth rows are in the paper.*
```

- **In *Results*, under the claim it supports.** Same rule as a figure, and `note_lint.py` enforces it.
- **Italic caption on the very next line**, no blank line between — again as for a figure, and for the same rendering reason.
- **No table number**, in the caption or anywhere else.
- **Values verbatim.** Copy the digits the paper printed. Do not round, rescale, convert units, or recompute an average from the subset of rows you kept: a recomputed number is one the step-10 finder cannot locate, and the paper never made that claim. Bolding the row or cell the claim is about is fine — that is emphasis, not arithmetic.
- **Trim to what the claim needs, and say so in the caption.** A 28-row benchmark becomes its four group averages; a 12-column table becomes the three columns compared. **A trimmed table that does not announce the trim is the most misleading thing this note can contain**, because unlike a vague sentence it looks complete and precise. One clause fixes it: *"the four task groups; the 28 subtasks are in the paper"*.
- **Keep the paper's orientation** — systems in columns if that is how the paper set them, rows if not. Transposing is a silent re-presentation, and two tables under two orientations read as two notes.
- **Four at most, one or two preferred**, and figures plus tables together should stay around five. Past that the note is the paper with the prose removed.

**Where a trim would change the reading, do not trim — cut the table.** If the rows you would drop are the ones that disagree with the claim, keeping only the agreeing rows is not a summary, and no caption clause repairs it. Report the comparison in prose with both directions named, or rebuild the whole thing.
