# Paper summary note format

- [Frontmatter](#frontmatter)
- [Section roles and headings](#section-roles-and-headings)
- [Choose the body mode](#choose-the-body-mode)
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
- **Format:** `Paper` for a standalone article, preprint or publication notice;
  `Book` for a book or chapter; `Report` for a technical report, white paper,
  standard or thesis.
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
  item. Preserve a collective byline rather than mining individuals from a
  footnote. If the document supplies no byline, write the canonical empty
  exception `author: []` and report it; never use bare `author:` or invent an
  author from an affiliation, publisher or filename.
- **Published:** valid `YYYY-MM-DD`, using every component the document prints.
  Pad an unstated month/day with `01` and report the padding. Do not look up a
  more precise date elsewhere. If the year is absent, the organized PDF must
  already carry its canonical `_nd` segment; write the explicit YAML null
  `published: null` and report it. A dated value paired with `_nd`, or a null
  paired with a year-bearing stem, routes back to `pdf-organizer` rather than
  being reconciled from outside knowledge.
- **Created:** the date the note is written. Clippings instead preserve their
  capture date; do not import that producer's rule here.
- **Description:** one factual sentence, at most 110 characters. Keep the main
  subject and contribution, preferring specifics over filler. This field alone may
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

Every note has six ordered section **positions**. The empirical body mode uses
the six canonical roles below. The other modes in [Choose the body
mode](#choose-the-body-mode) give those positions document-appropriate meanings
without changing the lintable structure. The canonical names are linter slot
identifiers for non-empirical notes, not instructions to call an argument a
method or a recommendation a result. Headings are short statements about this
document, never role labels:

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

| Empirical role | A label, which this note never writes | A heading, which it does |
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
such as `p53` or `mRNA`. A heading must say something about this document and
obey the claim rules; a cautious paragraph cannot repair an overstated heading.

The prose in this guide and `figures.md` explains the limits. This block is the
same contract in a machine-readable form so the conformance harness can stop a
documentation or linter edit from changing only one side:

<!-- canonical:summary-note:limits -->
```text
MAX_DESCRIPTION=110
MIN_HEADING=20
MAX_HEADING=90
MIN_HEADING_WORDS=3
MIN_BULLETS=3
MAX_BULLETS=7
MAX_SENTENCE_WORDS=25
MAX_STEP_WORDS=20
MAX_PARAGRAPH_SENTENCES=6
MIN_STEPS=3
MAX_STEPS=8
MAX_RESULTS_CHARS=2400
MIN_LIMITATIONS=1
PREFERRED_MIN_EMPIRICAL_LIMITATIONS=2
MAX_LIMITATIONS=4
MAX_LIMITATION_CHARS=420
MIN_AVAILABILITY=1
MAX_AVAILABILITY=3
MAX_FIGURES=4
MAX_TABLES=4
```
<!-- /canonical -->

## Choose the body mode

Choose from the document's primary contribution, not from the frontmatter
`format` alone:

- **Empirical:** any document whose main contribution reports or analyses
  observations or measurements, including experimental and qualitative work,
  systematic reviews with a reported synthesis procedure, evaluated models or
  simulations, benchmarks, and empirical books, chapters, theses or reports.
- **Argument/synthesis:** theoretical or conceptual papers, narrative reviews,
  non-empirical books or chapters, non-empirical reports, and standards. A
  formal model or derivation without an observational or computational
  evaluation belongs here even when the PDF calls part of it “results”.
- **Notice:** retractions, corrections, errata and expressions of concern.
  A comment that advances an argument uses argument/synthesis unless its main
  purpose is to change the publication record.

For a mixed document, choose the mode that fits its main contribution and use
the other material as support. Do not create a hybrid with extra sections.

| Position | Empirical | Argument/synthesis | Notice |
|---|---|---|---|
| 1 — Question | Research question and why it remained open | Problem, thesis or organizing question | Affected work and the issue that prompted the notice |
| 2 — Methods | Design, population/system and procedure | Stated scope, evidence base, premises and reasoning or selection approach | Issuer, stated grounds, evidence and process behind the action |
| 3 — Results | Main findings, including harms and nulls | Main argument, framework, conclusions, requirements or recommendations | Exact correction, withdrawal, warning or other change to the record |
| 4 — Interpretation | Implications licensed by the design | What follows from the argument and how its contribution can be used | Consequences for the affected claims, versions or uses |
| 5 — Limitations | Design and reporting constraints | Evidence gaps, assumptions, counterarguments and applicability bounds | What the notice does not decide, change or supply evidence about |
| 6 — Availability | Data, code and relevant materials | Supplied sources, code or supporting materials that matter to the argument | Affected record, supporting evidence or accompanying material named by the notice |

This choice changes meaning, not rigor or mechanics. Evidence and page-citation
rules, the Summary callout, six-heading order, length/count limits, exhibit
placement and Availability contract still apply. State only an approach, basis
or consequence the PDF supports; an absent empirical procedure is not a method
to reconstruct.

## Body content

- **Question / opening position:** in empirical mode, give the question and why
  it remained open, usually in one paragraph. If the stated aim and actual
  analysis differ, name that and carry the methodological consequence into
  Limitations. In the other modes, establish the thesis/problem or the affected
  work/issue without retelling the whole document.
- **Methods / basis position:** empirical mode uses a short design paragraph,
  then 3–8 numbered procedure steps in simple past, active voice, one action
  each, targeting at most 20 words. Put each step's numbers inside it. In the
  other modes, explain only the scope, premises, evidence selection, derivation,
  development process or grounds the document actually gives. Use numbered
  steps only for a real reported procedure, keep them contiguous and at 1–8
  steps, and use prose when a theory, narrative review, book or notice has no
  such procedure. The empirical 3-step minimum does not apply outside empirical
  mode. Include methodological preregistration where the document has it.
- **Results / contribution position:** develop the main finding, argument,
  recommendation or notice action for a scientist from another field. Empirical
  notes include harms and negative findings beside benefits. Argument/synthesis
  notes keep material contrary evidence, exceptions and conditions discussed by
  the document visible.
  Notice notes say exactly what changed without restating withdrawn claims as
  findings. A secondary contribution earns at most a sentence when it changes
  the main contribution's reading. Put every exhibit here, beneath its supporting
  claim; cite load-bearing numbers. The cap is **2,400 characters of prose**,
  excluding embeds, captions and tables.
- **Interpretation / consequence position:** state implications only as far as
  the design, reasoning or notice reaches. Every sentence is the authors' or
  issuer's conclusion, or explicitly marked as another reading.
- **Limitations / boundaries position:** use 1–4 bullets that would change how
  the reader acts on or cites the document. Empirical notes normally need 2–4;
  keep one only when a second material limitation would be filler, and explain
  that advisory exception in the run report. A compact argument or notice may
  have one without an exception. Use the [mode-appropriate limitations
  sweep](summary-standards.md#the-limitations-taxonomy-by-mode-and-design) to select them;
  do not repeat a local caveat or add generic research filler. Keep each bullet
  at or below 420 characters. Put detail that qualifies one claim beside that
  claim instead of turning the section into a second discussion.
- **Availability:** use 1–3 bullets with only relevant labels. Empirical notes
  name Data and add Code or Materials when relevant. Argument/synthesis notes
  use Sources, Materials, Data or Code only for supporting artifacts the
  document actually supplies or could reasonably have supplied. Notices use
  Record, Evidence or Materials for the affected version and support named by
  the notice. Use “not stated” when a relevant category could apply but the
  document gives no disclosure. Omit inapplicable labels rather than writing
  “not applicable” boilerplate.
  Preserve partial-release distinctions.

Funding, competing interests, peer-review status and ethics approval are outside
this note's scope. Preregistration is methodological: it belongs in the second
position, or a relevant missing-disclosure limitation, not in Availability.

## Prose and key messages

Write for a scientist outside the document's field. Keep technical terms and gloss
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
main contribution. For empirical mode, include its scope, absolute comparison
and confidence limit, then the supporting mechanism, effect size and chief
caveat. For argument/synthesis, give the thesis, decisive support and material
boundary; for notice mode, give the action, stated grounds and consequence.
Each bullet stands alone, states the claim directly and preserves exact technical
terms. Bold only wiki-worthy entities. Do not put URLs or page citations in the
callout.

## Citations

Use physical, 1-indexed pages of this PDF. Attach the citation to the preceding
full stop without a space:

```text
…enrolled 219 of a planned 220.<sup>[[Doe_GutMicrobiome_2025.pdf#page=3|3]]</sup>
```

The display text is digits only and equals the target page; the target is this
note's own `sources:` PDF. Cite load-bearing basis/approach, main-contribution,
harms/null, limitation and availability passages as applicable, not every
sentence. Pages come from the recorded claim set and are independently checked
against the source before publication.
Citations appear only in body prose, never frontmatter, callout or captions.
There is no footnote syntax, numbered reference list or trailing bibliography.

## Complete shape

This scaffold shows the empirical meanings. Argument/synthesis and notice notes
replace the six placeholder meanings with the corresponding row in [Choose the
body mode](#choose-the-body-mode); they do not add, drop or reorder sections.

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

For an argument/synthesis note, the six body positions can read like this:

```text
## The standard defines one interoperable event record

<problem or thesis>

## Three compatibility constraints organize the requirements

<scope, premises and evidence base in prose>

## Every event carries identity time and provenance

<main requirements, support and any selected exhibit>

## The schema lets independent tools exchange records

<implication and supported use>

## Adoption still depends on local extension rules

- **Applicability.** <the material source-backed boundary>

## The normative text and examples are supplied together

- **Sources.** <what the document supplies or does not state>
- **Materials.** <supporting schemas or examples, when relevant>
```

For a notice, keep the action and its remaining uncertainty separate:

```text
## The notice concerns the published dosage table

<affected work and stated issue>

## The publisher compared the table with source records

<issuer, stated grounds and review process>

## Two dosage entries are corrected in the record

<exact change without repeating the old claim as a finding>

## Readers should use the replacement table

<consequence for the affected version or use>

## The notice does not reassess the remaining findings

- **Scope.** <the one material question the notice leaves open>

## The corrected version is linked by the notice

- **Record.** <affected and corrected versions identified in the PDF>
- **Evidence.** <supporting material named by the notice, if any>
```

The first line is `---`, with no BOM or leading blank line. The Summary callout
starts immediately after the closing YAML fence. Put one blank line on each
side of the single `___` separator. Use six `##` headings with blank lines
around them, no H1 or H3, no other horizontal rules, and no empty sections.
The fifth and Availability sections are bullet lists; the other sections are
prose apart from a reported procedure in the second and exhibits in the third.
Every embed/table has its italic caption on the next line. No figure or table
number appears in the prose or captions. End after Availability with a single
newline.

Run `note_lint.py --mode <empirical|argument|notice>` on the complete draft,
using the body mode selected above. Fix its violations and review its
advisories using the targets above. Its result covers mechanical
format and the selected mode's list contract, not whether the mode was chosen
correctly, the scientific meaning, physical page upper bounds or image contents.
Add `--allow-unorganized` only when the source inventory used that same
deliberate override; this makes the otherwise blocking filename exception
visible while leaving all other lint checks active.
The [verification checklist](review-checklist.md) covers those independent checks.
