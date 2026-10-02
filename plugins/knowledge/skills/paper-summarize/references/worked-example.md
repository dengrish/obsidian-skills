# Worked example: one PDF document

- [The input](#the-input)
- [The output note](#the-output-note)
- [Why these choices matter](#why-these-choices-matter)
- [Illustrative lint and verification](#illustrative-lint-and-verification)

Read when the assembled output is unclear. The paper is fictional; it is not an
external source or a completed live-vault run. [Note format](note-format.md),
[summary standards](summary-standards.md) and [figures](figures.md) own the rules.
This randomized trial uses empirical body mode; its section meanings are not a
template for an argument, book, standard or notice.

## The input

A fictional paper, realistic in every detail that matters. `Sources/PDFs/Doe_GutMicrobiome_2025.pdf`, 8 physical pages, four figures already sitting in `Sources/Images/` under this PDF's stem as `Doe_GutMicrobiome_2025_fig_1.png` through `_fig_4.png`. The facts the note below is built from, with physical pages:

- **Title:** *Encapsulated faecal microbiota transplant for recurrent Clostridioides difficile infection: a randomised, double-blind, placebo-controlled trial*
- **Authors:** Priya N. Doe, Marcus A. Feldman, Ingrid S. Halvorsen and eight others (eleven in total). **Year:** the title page prints `2025` and no month or day. **DOI:** printed on page 1 as `10.1016/S2468-1253(25)00114-6`.
- **Background,** page 2: after a second recurrence, 40–60% of patients relapse again after another vancomycin course. Colonoscopic transplant had been tested against placebo; earlier oral-capsule studies were open-label single-arm series.
- **Design,** page 3: randomised, double-blind, placebo-controlled trial at 14 hospitals in Denmark and the Netherlands. 219 adults with at least two laboratory-confirmed prior recurrences, all having finished a 10-day vancomycin course, randomised 1:1 to four transplant capsules over two days (110) or identical placebo capsules (109). Powered at 90% for a 20-percentage-point absolute difference; 219 of a planned 220 enrolled. Registered at ClinicalTrials.gov `NCT05712398` before the first patient. Capsules came from two stool banks; children were not eligible.
- **Procedures,** page 3: patients, treating clinicians and outcome assessors were masked. Recurrence (diarrhoea plus a positive stool toxin assay) was adjudicated by a committee blind to allocation. The paper does not say who generated the allocation sequence or how it was concealed, and does not report losses to follow-up between week 4 and week 8.
- **Primary outcome,** page 5: recurrence within 8 weeks — 8.2% (9 of 110) on transplant against 45.0% (49 of 109) on placebo; absolute reduction 36.8 percentage points (95% CI 25.9 to 47.7), risk ratio 0.18 (95% CI 0.09 to 0.36).
- **Harms,** page 6: abdominal cramping in the first 48 hours, 27 of 110 against 11 of 109; one *Escherichia coli* bacteraemia in the transplant arm within 7 days, adjudicated possibly related; no deaths in either arm within 8 weeks.
- **One null secondary,** page 6: gastrointestinal quality of life at 8 weeks (GIQLI, 144 points) — mean difference 2.6 points, 95% CI −3.1 to +8.3.
- **Exploratory engraftment,** page 7: week-8 stool samples from 87 transplant-arm patients; donor strains detectable in 71 of 78 who stayed recurrence-free and in 4 of 9 who recurred.
- **The authors' conclusions,** page 8: offer encapsulated transplant after a second recurrence in adults who completed vancomycin; the capsule route avoids colonoscopy without losing the effect size.
- **The authors' own limitations,** page 8: follow-up ends at 8 weeks; everyone enrolled had already relapsed at least twice; one donor supplied 38% of the capsules given.
- **Availability,** page 8: de-identified participant data 12 months after publication under a data-access agreement; no analysis code offered.
- **Figures:** 1 participant flow, 2 Kaplan–Meier recurrence curves, 3 subgroup forest plot, 4 donor-strain detection by recurrence status.

## The output note

The destination would be `Articles/Doe_GutMicrobiome_2025.md`; the PDF and its
figures remain unchanged. The example creation date is illustrative.

```
---
title: "Encapsulated faecal microbiota transplant for recurrent Clostridioides difficile infection: a randomised, double-blind, placebo-controlled trial"
format: Paper
sources:
  - "[[Doe_GutMicrobiome_2025.pdf]]"
  - "https://doi.org/10.1016/S2468-1253(25)00114-6"
author:
  - Priya N. Doe
  - Marcus A. Feldman
  - Ingrid S. Halvorsen
  - et al.
published: 2025-01-01
created: 2026-08-10
description: Encapsulated faecal transplant cut C. difficile recurrence from 45% to 8% in a 219-patient trial.
tags:
  - "#medicine"
read: false
---
> [!Summary]
> - **Encapsulated faecal microbiota transplant** cut 8-week recurrence of ***Clostridioides difficile*** infection from 45.0% on placebo to 8.2% in adults with at least two prior recurrences. The 219-patient trial was randomised and double-blind.
> - Abdominal cramping in the first 48 hours was more common on transplant than on placebo (27 of 110 against 11 of 109). One transplant patient had *Escherichia coli* bacteraemia within 7 days, adjudicated as possibly treatment-related.
> - Gastrointestinal quality of life at 8 weeks showed no detectable difference from placebo (mean difference 2.6 of 144 **GIQLI** points, 95% CI −3.1 to +8.3). A benefit as large as 8.3 points is not ruled out.
> - Persisting donor strains at week 8 were associated with staying recurrence-free, in an exploratory comparison outside the randomisation.
> - Follow-up ended at 8 weeks, so durability is untested.

___

## Recurrent C. difficile relapses again after vancomycin

After a second recurrence of *C. difficile* infection, 40–60% of patients relapse again after another vancomycin course.<sup>[[Doe_GutMicrobiome_2025.pdf#page=2|2]]</sup> Faecal microbiota transplant by colonoscopy had been tested against placebo, but the oral capsule form mostly in open-label single-arm series. The question was whether transplant capsules, given after vancomycin, prevent recurrence within 8 weeks better than identical placebo capsules.

## A 219-patient double-blind trial of transplant capsules

The trial was randomised, double-blind and placebo-controlled, at 14 hospitals in Denmark and the Netherlands. It was registered at ClinicalTrials.gov as NCT05712398 before the first patient was enrolled. Powered at 90% to detect a 20-percentage-point absolute difference, it enrolled 219 of a planned 220.<sup>[[Doe_GutMicrobiome_2025.pdf#page=3|3]]</sup> Capsules came from two stool banks.

1. 219 adults with at least two laboratory-confirmed prior recurrences completed a 10-day vancomycin course.
2. Investigators randomised them 1:1 — 110 to transplant capsules, 109 to identical placebo capsules.
3. The transplant arm took four transplant capsules over two consecutive days.
4. The trial masked patients, treating clinicians and outcome assessors.
5. A committee blind to allocation adjudicated recurrence within 8 weeks (diarrhoea plus a positive stool toxin assay).

## Capsules cut 8-week recurrence to 8% against 45% on placebo after repeat relapses

**The primary outcome.** Recurrence within 8 weeks occurred in 8.2% of the transplant arm (9 of 110) against 45.0% on placebo (49 of 109). That is an absolute reduction of 36.8 percentage points (95% CI 25.9 to 47.7). The risk ratio was 0.18 (95% CI 0.09 to 0.36).<sup>[[Doe_GutMicrobiome_2025.pdf#page=5|5]]</sup> In adults with at least two prior recurrences who have finished vancomycin, encapsulated transplant reduces recurrence against placebo.

![[Doe_GutMicrobiome_2025_fig_2.png]]
*The two arms separated within a fortnight and stayed apart to week 8. Curves show time to first recurrence in 219 previously treated adults, transplant versus placebo, with numbers still at risk below each week.*

**Harms.** Abdominal cramping in the first 48 hours was reported by 27 of 110 on transplant and 11 of 109 on placebo. One patient in the transplant arm developed *Escherichia coli* bacteraemia within 7 days, adjudicated as possibly treatment-related. There were no deaths in either arm within 8 weeks.<sup>[[Doe_GutMicrobiome_2025.pdf#page=6|6]]</sup>

**A secondary outcome with no detected difference.** On gastrointestinal quality of life at 8 weeks the trial did not detect a difference between the arms. The mean difference was 2.6 points on the 144-point GIQLI, 95% CI −3.1 to +8.3.<sup>[[Doe_GutMicrobiome_2025.pdf#page=6|6]]</sup> The interval leaves room for a benefit of up to 8.3 points or a deficit of up to 3.1.

**Engraftment, exploratory.** In week-8 transplant-arm samples, donor strains persisted in 71 of 78 who stayed well and 4 of 9 who recurred, an association outside the randomisation.<sup>[[Doe_GutMicrobiome_2025.pdf#page=7|7]]</sup>

## Authors recommend capsules after a second recurrence in adults

The authors conclude that encapsulated transplant should be offered after a second recurrence, in adults who have completed vancomycin. They also conclude that the capsule route removes the need for colonoscopy without giving up the effect size colonoscopic transplant has shown.<sup>[[Doe_GutMicrobiome_2025.pdf#page=8|8]]</sup> This trial did not compare the two routes.

## Eight weeks of follow-up, and one donor supplied 38%

- **Follow-up ends at 8 weeks**, the authors' own first limitation, so durability is untested.<sup>[[Doe_GutMicrobiome_2025.pdf#page=8|8]]</sup>
- **One donor dominated.** One donor supplied 38% of the capsules given, so the trial cannot separate transplant in general from this donor's material.<sup>[[Doe_GutMicrobiome_2025.pdf#page=8|8]]</sup>
- **Who it covers.** Adults at 14 hospitals in Denmark and the Netherlands, all with at least two prior recurrences and a completed vancomycin course. It is not about a first recurrence or about children.<sup>[[Doe_GutMicrobiome_2025.pdf#page=3|3]]</sup>
- **Unreported methods.** The paper does not say who generated the allocation sequence or how it was concealed. It does not report losses to follow-up between weeks 4 and 8 either; CONSORT asks for both.

## Participant data on request, no analysis code

- **Data.** De-identified participant data available 12 months after publication, under a data-access agreement.<sup>[[Doe_GutMicrobiome_2025.pdf#page=8|8]]</sup>
- **Code.** No analysis code is offered.
```

## Why these choices matter

- The primary recurrence comparison uses the randomized trial's confidence,
  while the exploratory engraftment claim is worded as an association. One
  paper can contain claims with different confidence.
- Absolute recurrence rates sit beside the risk ratio. Harms and the uncertain
  quality-of-life result remain visible beside the benefit; a null is not
  written as equivalence.
- One of four figures is selected. The participant-flow, subgroup and
  engraftment figures do not earn space, and the secondary engraftment finding
  gets one sentence. The primary comparison fits in prose, so this note does
  not repeat it in a table.
- The eight-week horizon is explained once, in Limitations, and stated in one
  short callout bullet. Other sections word their claims within 8 weeks
  instead of repeating the caveat. Interpretation attributes the authors'
  conclusions and adds only the limit their route comparison needs.
- The title page supplies only `2025`, so the note pads month/day to `01` and
  the report records that choice. The DOI is included because the fictional
  document prints it; neither date nor URL requires outside lookup.
- The short author list follows the eleven-person byline rule. Preregistration
  remains methodological information.
- Availability names restricted data access and missing code separately.

## Illustrative lint and verification

For a real note, save the completed draft to a unique scratch `.md` and lint it:

```bash
python3 '<skill>/scripts/note_lint.py' '<scratch>/Doe_GutMicrobiome_2025.md' \
    --mode empirical --images '<vault>/Sources/Images'
```

Lint cannot verify the science or the page citations, and every selected real
image still needs visual inspection. Do not create placeholder images to make
this fictional example pass the command above.

Then, on the real PDF, collect all numbers, names and scope tokens, use the
finder and read their pages. A few example needles are:

```bash
python3 '<skill>/scripts/paper_text.py' '<vault>/Sources/PDFs/Doe_GutMicrobiome_2025.pdf' \
    --find '9 of 110' --find '49 of 109' --find '0.18' \
    --find 'at least two prior recurrences' --find 'Clostridioides difficile'
```

Suppose a draft said donor strains persisted for **12 weeks**. The source facts
above support week 8. An unfound `12 weeks` needle would require retrying the
source's wording, then correcting the claim to week 8 and checking that page;
“persisted for some weeks” would conceal the error. A `loose` species-name match
would require opening the page to distinguish a line break from an accidental
join. These are illustrative decisions, not invented tool results from an
included PDF.

A real run reports source-check counts/corrections and lint separately, then
publishes only after both gates pass. It does not copy this example's facts or
an illustrative verdict into another paper's report.
