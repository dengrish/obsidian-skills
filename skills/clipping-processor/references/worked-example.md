# Worked example — one raw clipping, start to finish

**Read this when** you want to see the whole thing assembled before writing your first note of a session, or when a piece of the output shape is unclear — where the blank lines go, how a caption sits under an embed, what the report's correction lines look like. It is illustration, not rules: the rules are in the workflow steps and the other reference files.

Raw input (`Inbox/Pancreatic_cancer_just_met_its_match.md`):

```
---
title: "Pancreatic cancer just met its match"
source: "https://www.worksinprogress.news/p/pancreatic-cancer-just-met-its-match"
author:
  - "[[Ruxandra Teslo]]"
published: 2022-09-05
created: 2026-05-25
---
For most of the last half-century, a diagnosis of metastatic pancreatic cancer was a death sentence...
[body with embedded ![](https://...) image references and trailing caption paragraphs]
```

Polished output, written to `Articles/Teslo_Pancreatic_Cancer_2026.md` (the raw stays in `Inbox/` untouched):

```
---
title: Pancreatic cancer just met its match
format: Article
sources:
  - "https://www.worksinprogress.news/p/pancreatic-cancer-just-met-its-match"
author:
  - Ruxandra Teslo
published: 2026-05-12
created: 2026-05-25
description: Daraxonrasib, a KRAS molecular glue, doubles survival in metastatic pancreatic cancer.
tags:
  - "#medicine"
read: false
---
> [!Summary]
> - **Daraxonrasib**, a KRAS molecular glue, roughly doubles overall survival in metastatic pancreatic cancer in early trials.
> - Former Nebraska Senator Ben Sasse saw a dramatic tumor reduction after taking **daraxonrasib** for metastatic pancreatic cancer.
> - [...remaining bullets...]

___

## A death sentence, until recently

For most of the last half-century, a diagnosis of metastatic pancreatic cancer was a death sentence...

![[Teslo_Pancreatic_Cancer_2026_fig_1.png]]
*Figure 1. Mechanism of daraxonrasib binding to KRAS G12D.*

### How molecular glues work

[body continues with `![[Teslo_Pancreatic_Cancer_2026_fig_2.png]]` followed by `*caption.*` lines, etc., in place of the original URLs and caption paragraphs]
```

Things to notice in this example:

- **Filename slug:** `Teslo_Pancreatic_Cancer_2026.md` — first author's lastname, two Title-Cased content words from the title (dropping "just met its match"), corrected published year.
- **No blank line between the YAML closing `---` and the `> [!Summary]` callout** — the summary opens flush on the next line.
- **First summary bullet is the central finding** (the trial result), not the lead anecdote — leading with the article's main claim, per step 7's "main claim first." The Ben Sasse case the piece opens with is demoted to the second bullet, demonstrating "one bullet covers the lead anecdote."
- **Headings normalized to `##` / `###`** — the body's top-level section is `##`, the sub-section is `###`, regardless of what level Web Clipper used.
- **Description is 86 characters** — well under the 110-char cap, leading with the drug name and main finding.
- **`read: false`, bare and last** — the user's review checkbox, written once here and never again: they tick it to `true` when they've read the note, and a later reprocess of this file leaves whatever value it finds. The quotes are absent on purpose (`read: "false"` is a string, which Obsidian's checkbox renders as permanently checked).
- **Captions are rendered as a single italic line directly below the plain embed** (`![[file]]` on one line, `*caption.*` on the next); the original caption paragraphs are gone from the body and any internal `**bold**` / nested italics in them have been flattened.
- **`published` was corrected** from the raw's `2022-09-05` to `2026-05-12` — the raw date was scraped wrong, source verification found the correct article date. The corrected year `2026` flows into the filename slug. The report flags the correction:

```
Metadata corrections:
  published: 2022-09-05 → 2026-05-12 (source: og:article:published_time)
```

Images saved to `Sources/Images/`:
- `Teslo_Pancreatic_Cancer_2026_fig_1.png`
- `Teslo_Pancreatic_Cancer_2026_fig_2.png`
- ... (one per image in body order)
