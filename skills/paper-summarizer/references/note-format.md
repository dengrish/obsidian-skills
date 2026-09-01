# Paper summary note format

- [Frontmatter](#frontmatter)
- [Section roles and headings](#section-roles-and-headings)
- [Body content](#body-content)
- [Prose and key messages](#prose-and-key-messages)
- [Citations](#citations)
- [Complete shape](#complete-shape)

Read before drafting. This file owns the output shape, writing limits and
brevity targets; [summary standards](summary-standards.md) owns factual claims and
confidence, and [figures](figures.md) owns exhibit selection and captions.

## Frontmatter

Use the shared [source-note schema](../../../shared/CONVENTIONS.md#2b-source-note--a-note-about-a-document)
in its nine-key order. This example shows the paper variant:

```yaml
---
title: <the title printed in the PDF>
format: Paper
sources:
  - "[[Doe_GutMicrobiome_2025.pdf]]"
author:
  - <Name>
published: 2025-01-03
created: 2026-08-10
description: <one factual sentence, at most 110 characters>
tags:
  - "#biology"
read: false
---
```

- **Title:** the first page's actual title, not the filename; preserve its
  language. Quote YAML-special values. Do not append a subject or author name.
- **Format:** `Paper` for a standalone article/preprint; `Book` for a book or
  chapter; `Report` for a technical report, white paper, standard or thesis.
  A formal abstract resolves an otherwise ambiguous Paper/Report choice;
  a heading-search miss does not prove there is no abstract.
- **Sources:** first the double-quoted bare PDF wikilink. A second double-quoted
  URL is optional, only from a DOI/arXiv identifier printed in this document,
  normalized to `https://doi.org/...` or `https://arxiv.org/abs/...`. Never on
  `Book`, never blank, never inferred from a title or ISBN. Basename conflicts
  must be resolved upstream; a path-qualified link does not fix note/image
  namespace collisions. Do not write the retired `source`/`url` pair.
- **Author:** block-form list in the printed order, without wikilink wrappers.
  For more than about eight authors, list the first three and a final `et al.`
  item. Preserve a collective byline rather than mining individuals from a footnote.
- **Published:** valid `YYYY-MM-DD`, using every component the document prints.
  Pad an unstated month/day with `01` and report the padding. Do not look up a
  more precise date elsewhere. If the year is absent, stop for that note and
  surface the undated source; neither the filename nor outside knowledge supplies it.
- **Created:** the date the note is written. Clippings instead preserve their
  capture date; do not import that producer's rule here.
- **Description:** one factual sentence, at most 110 characters. Keep the main
  subject and finding, preferring specifics over filler. This field alone may
  compress the full scope clause to fit; the callout must state it in full.
- **Tags:** the subject's canonical discipline(s) from
  [CONVENTIONS §3](../../../shared/CONVENTIONS.md#3-the-discipline-tag-enum),
  as a block list of double-quoted `#` values, or blank when none applies.
- **Read:** bare `false` on creation; preserve the existing value on an approved
  rewrite, including an absent/unknown state. Report the latter; do not create
  `false` or force a boolean on an existing note to satisfy lint. A resulting
  format conflict leaves the original intact and the draft unpublished.

The fixed schema describes generated notes, not permission to discard user
metadata. Preserve unrelated fields on an existing note. If that conflicts with
lint's strict format, leave the original intact and report the conflict rather
than deleting properties to make lint pass. Apply only the shared schema's
explicit legacy migrations; preserve a retired `topics:` and report any legacy
value that cannot be migrated without guessing.

## Section roles and headings

The six roles are fixed and ordered. Their positions carry the roles; their
headings are short statements about this paper, never these labels:

<!-- canonical:summary-note:roles -->
```
Question
Methods
Results
Interpretation
Limitations
Availability
```
<!-- /canonical -->

| Role | A label, which this note never writes | A heading, which it does |
|---|---|---|
| Question | `## Question` | `## Nobody had measured no-till carbon past a decade` |
| Methods | `## Methods` | `## Twelve years of paired plots on one Iowa farm` |
| Results | `## Results` | `## No-till held 6 t/ha more carbon, all of it in the top 10 cm` |
| Interpretation | `## Interpretation` | `## Real storage, but shallower than the offset market assumes` |
| Limitations | `## Limitations` | `## One farm, one soil type, and no deep-core sampling` |
| Availability | `## Availability` | `## Plot data are public, the yield model is not` |

These are examples from one fictional tillage study, not reusable headings.
Each heading is 20–90 characters and at least three words, in sentence case
with no trailing full stop or all-capitals styling. Preserve technical casing
such as `p53` or `mRNA`. A heading must say something about this paper and obey
the claim rules; a cautious paragraph cannot repair an overstated heading.

## Body content

- **Question:** the question and why it remained open, usually one paragraph.
  If the stated aim and actual analysis differ, name that and carry the
  methodological consequence into Limitations.
- **Methods:** a short paragraph naming the design, then 3–8 numbered steps in
  simple past, active voice, one action each, targeting at most 20 words. Put
  each step's numbers inside it. A theory paper or comment without a procedure
  uses only the paragraph. Include methodological preregistration where the
  paper has it.
- **Results:** develop the main finding for a scientist from another field.
  Include harms and negative findings alongside benefits. A secondary experiment
  earns at most a sentence when it changes the main result's reading. Put every
  exhibit here, beneath its supporting claim; cite load-bearing numbers.
  The cap is **2,400 characters of prose**, excluding embeds, captions and tables.
- **Interpretation:** implications only as far as the design reaches. Every
  sentence is the authors' conclusion or explicitly marked as another reading.
- **Limitations:** 2–4 bullets that would change how the reader acts or cites.
  Use the [limitations sweep](summary-standards.md#the-limitations-taxonomy-by-design)
  to select them; do not repeat a row-level caveat or generic research filler.
- **Availability:** at most three bullets: Data, Code, and Materials only when
  applicable. State what is available and what is not; use “not stated” rather
  than silently omitting Data or Code. Preserve partial-release distinctions.

Funding, competing interests, peer-review status and ethics approval are outside
this note's scope. Preregistration is methodological: it belongs in Methods,
or a relevant missing-disclosure limitation, not in Availability.

## Prose and key messages

Write for a scientist outside the paper's field. Keep technical terms and gloss
unfamiliar ones once, in their own sentence. Use active voice, simple tenses and
one topic per paragraph, with at most six sentences per paragraph.

Aim for at most **25 words per prose sentence and 20 per numbered step**,
including callout bullets and exhibit captions. These are strong brevity targets.
Split or shorten first, preserving complete sentences and necessary qualifications.
Keep a longer sentence only when shortening or splitting it would make the
meaning, scope or qualification less clear. Use the shortest clear version and
explain the exception in the run report, not in the note. A word-count advisory
calls for this judgment; it is not permission to retain avoidable detail.

The Summary callout holds 3–7 `> - ` bullets, one line per bullet. Lead with the
main finding; include its scope, absolute comparison and confidence limitation,
then the supporting mechanism, effect size and chief caveat. Each bullet stands
alone, states the claim directly and preserves exact technical terms. Bold only
wiki-worthy entities. Do not put URLs or page citations in the callout.

## Citations

Use physical, 1-indexed pages of this PDF. Attach the citation to the preceding
full stop without a space:

```text
…enrolled 219 of a planned 220.<sup>[[Doe_GutMicrobiome_2025.pdf#page=3|3]]</sup>
```

The display text is digits only and equals the target page; the target is this
note's own `sources:` PDF. Cite load-bearing design/result/harms/null/limitation
and availability passages, not every sentence. Pages come from the recorded
claim set and are independently checked against the source before publication.
Citations appear only in body prose, never frontmatter, callout or captions.
There is no footnote syntax, numbered reference list or trailing bibliography.

## Complete shape

```text
---
<the source-note frontmatter>
---
> [!Summary]
> - <main finding and its qualification>
> - <supporting claim>
> - <chief limitation>

___

## <the question, and why it remained open>

<prose>

## <the study design and scale>

<design paragraph, then numbered procedure where applicable>

## <the main finding>

<prose, selected exhibits and superscript page citations>

## <the implication the design supports>

<prose>

## <the limitation that matters most>

- **<limitation>.** <prose>
- **<limitation>.** <prose>

## <what is available and what is not>

- **Data.** <prose>
- **Code.** <prose>
```

The first line is `---`, with no BOM or leading blank line. The Summary callout
starts immediately after the closing YAML fence. Put one blank line on each
side of the single `___` separator. Use six `##` headings with blank lines
around them, no H1 or H3, no other horizontal rules, and no empty sections.
Limitations and Availability are bullet lists; the other sections are prose
apart from the Methods procedure and Results exhibits. Every embed/table has
its italic caption on the next line. No figure or table number appears in the
prose or captions. End after Availability with a single newline.

Run `note_lint.py` on the complete draft. Fix its violations and review its
sentence-length advisories using the targets above. Its result covers mechanical
format, not the scientific meaning, physical page upper bounds or image contents.
The [verification checklist](review-checklist.md) covers those independent checks.
