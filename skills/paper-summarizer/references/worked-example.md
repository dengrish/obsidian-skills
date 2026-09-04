# Worked example: one paper

- [The input](#the-input)
- [The output note](#the-output-note)
- [Why these choices matter](#why-these-choices-matter)
- [Illustrative verification and lint](#illustrative-verification-and-lint)

Read when the assembled output is unclear. The paper is fictional; it is not an
external source or a completed live-vault run. [Note format](note-format.md),
[summary standards](summary-standards.md) and [figures](figures.md) own the rules.
The note fence below is lintable as a scratch fixture; re-lint it after editing.

## The input

A fictional paper, realistic in every detail that matters. `Sources/PDFs/Doe_GutMicrobiome_2025.pdf`, 8 physical pages, four figures already sitting in `Sources/Images/` under this PDF's stem as `Doe_GutMicrobiome_2025_fig_1.png` through `_fig_4.png`. The handful of facts the note below is built from:

- **Title:** *Encapsulated faecal microbiota transplant for recurrent Clostridioides difficile infection: a randomised, double-blind, placebo-controlled trial*
- **Authors:** Priya N. Doe, Marcus A. Feldman, Ingrid S. Halvorsen and eight others (eleven in total). **Year:** the title page prints `2025` and no month or day. **DOI:** printed on page 1 as `10.1016/S2468-1253(25)00114-6`.
- **Design:** randomised, double-blind, placebo-controlled trial at 14 hospitals in Denmark and the Netherlands. 219 adults with at least two laboratory-confirmed prior recurrences, all having finished a 10-day vancomycin course, randomised 1:1 to four encapsulated transplant capsules over two days (110) or identical placebo capsules (109). Powered at 90% for a 20-percentage-point absolute difference; 219 of a planned 220 enrolled. Registered at ClinicalTrials.gov `NCT05712398` before the first patient. Page 3.
- **Primary outcome:** recurrence within 8 weeks — 8.2% (9 of 110) on transplant against 45.0% (49 of 109) on placebo; absolute reduction 36.8 percentage points (95% CI 25.9 to 47.7), risk ratio 0.18 (95% CI 0.09 to 0.36). Page 5.
- **One harm:** abdominal cramping in the first 48 hours, 27 of 110 against 11 of 109; one *Escherichia coli* bacteraemia in the transplant arm within 7 days, adjudicated possibly related. Page 6.
- **One null secondary:** gastrointestinal quality of life at 8 weeks (GIQLI, 144 points) — mean difference 2.6 points, 95% CI −3.1 to +8.3. Page 6.
- **The authors' own limitations,** page 8: follow-up ends at 8 weeks; everyone enrolled had already relapsed at least twice; one donor supplied 38% of the capsules given.
- **Availability,** page 8: de-identified participant data 12 months after publication under a data-access agreement; no analysis code offered.

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
> - Oral **encapsulated faecal microbiota transplant** cut recurrence of **Clostridioides difficile** infection within 8 weeks in adults with at least two prior recurrences. Recurrence fell from 45.0% (49 of 109) on placebo to 8.2% (9 of 110) — an absolute reduction of 36.8 percentage points. The risk ratio was 0.18 (95% CI 0.09 to 0.36), in a randomised, double-blind, placebo-controlled trial.
> - Abdominal cramping in the first 48 hours was more common on transplant than on placebo (27 of 110 against 11 of 109). One patient in the transplant arm had **Escherichia coli** bacteraemia within 7 days, adjudicated by the safety committee as possibly treatment-related.
> - The trial did not detect a difference in gastrointestinal quality of life at 8 weeks against placebo. The mean difference was 2.6 points on the 144-point **GIQLI** (95% CI −3.1 to +8.3). A benefit as large as 8.3 points is not ruled out.
> - Detectable donor strains at week 8 were associated with staying recurrence-free. Nobody was randomised to engraft, so this does not establish engraftment as the mechanism.
> - Follow-up ended at 8 weeks in both arms, so the trial supports no claim, at any strength, about durability past two months.

___

## Recurrent C. difficile relapses again after vancomycin

After a second recurrence of *C. difficile* infection, another vancomycin course leaves a large minority of patients relapsing again. The paper puts that figure at 40–60%. Faecal microbiota transplant delivered by colonoscopy has been tested against placebo before. The encapsulated oral form — the one an ordinary outpatient service could actually deliver — had mostly been tested in open-label single-arm series. A single-arm series has no placebo arm to read a recurrence rate against. The question here is narrow: given after a standard vancomycin course, do transplant capsules prevent recurrence at 8 weeks against identical placebo capsules?

## A 219-patient double-blind trial of transplant capsules

A randomised, double-blind, placebo-controlled trial at 14 hospitals in Denmark and the Netherlands, registered at ClinicalTrials.gov as NCT05712398 before the first patient was enrolled. The trial was powered at 90% to detect a 20-percentage-point absolute difference and enrolled 219 of a planned 220.<sup>[[Doe_GutMicrobiome_2025.pdf#page=3|3]]</sup> Donor material came from two stool banks, and one donor supplied 38% of the capsules given.

1. 219 adults with at least two laboratory-confirmed prior recurrences completed a 10-day vancomycin course.
2. They were randomised 1:1 — 110 to transplant capsules, 109 to identical placebo capsules.
3. The transplant arm took four encapsulated capsules over two consecutive days.
4. Patients, treating clinicians and outcome assessors were all masked.
5. Recurrence within 8 weeks (diarrhoea plus a positive stool toxin assay) was adjudicated by a committee blind to allocation.

## Recurrence fell from 45% to 8% within eight weeks

**The primary outcome.** Recurrence within 8 weeks occurred in 8.2% of the transplant arm (9 of 110) against 45.0% on placebo (49 of 109). That is an absolute reduction of 36.8 percentage points (95% CI 25.9 to 47.7). The risk ratio was 0.18 (95% CI 0.09 to 0.36).<sup>[[Doe_GutMicrobiome_2025.pdf#page=5|5]]</sup> In adults with at least two prior recurrences who have finished vancomycin, encapsulated transplant reduces recurrence against placebo.

![[Doe_GutMicrobiome_2025_fig_2.png]]
*The two arms separated inside the first fortnight and stayed apart to week 8. Kaplan–Meier curves for time to first recurrence, transplant against placebo, with the number of patients still at risk printed below each week.*

**Harms.** Abdominal cramping in the first 48 hours was reported by 27 of 110 on transplant and 11 of 109 on placebo. One patient in the transplant arm developed *Escherichia coli* bacteraemia within 7 days, which the independent safety committee adjudicated as possibly treatment-related. There were no deaths in either arm within 8 weeks.<sup>[[Doe_GutMicrobiome_2025.pdf#page=6|6]]</sup>

**A secondary outcome that did not move.** On gastrointestinal quality of life at 8 weeks the trial did not detect a difference between the arms. The mean difference was 2.6 points on the 144-point GIQLI, 95% CI −3.1 to +8.3.<sup>[[Doe_GutMicrobiome_2025.pdf#page=6|6]]</sup> A benefit of up to 8.3 points is not ruled out by this result, and neither is a 3.1-point deficit.

**Engraftment, exploratory.** 96 patients gave a stool sample at week 8. Donor strains were still detectable in 71 of 78 who had stayed recurrence-free, and in 4 of 18 who had recurred.<sup>[[Doe_GutMicrobiome_2025.pdf#page=7|7]]</sup> This comparison is observational inside a randomised trial: patients were randomised to capsules, not to engraftment. So detectable donor strains are associated with staying well, rather than shown to be how the treatment works.

![[Doe_GutMicrobiome_2025_fig_4.png]]
*Donor strains were still present at week 8 in most patients who stayed well and in few of those who recurred. Genus-level composition for each sampled patient at baseline, week 1 and week 8, split by recurrence status; one column is one patient.*

## Worth offering after a second recurrence in adults

The authors conclude that encapsulated transplant should be offered after a second recurrence, in adults who have completed vancomycin. They also conclude that the capsule route removes the need for colonoscopy, without giving up the effect size that route has shown.<sup>[[Doe_GutMicrobiome_2025.pdf#page=8|8]]</sup> They are explicit that this says nothing about a first recurrence: everyone enrolled had already relapsed at least twice. It says nothing about children either, who were not eligible. The authors do not put it this way, but the harms line is what makes the 8-week horizon bite in practice. A one-off treatment with cramping in a quarter of patients and one bloodstream infection in 110 needs a durability figure this trial lacks.

## Eight weeks of follow-up, and one donor supplied 38%

- **What the design cannot show.** Randomisation and masking let the trial attribute the difference in recurrence to the capsules. They do not separate the effect of transplant in general from the effect of *this donor material*. One donor supplied 38% of the capsules given.
- **Who it was in.** 219 adults at 14 hospitals in two northern European countries, all with at least two prior recurrences and all having completed vancomycin. It is not about a first recurrence, not about children, and not about patients who cannot swallow capsules.
- **Follow-up ends at 8 weeks**, the authors' own first limitation and the one that constrains this note most.<sup>[[Doe_GutMicrobiome_2025.pdf#page=8|8]]</sup> No durability claim is available here, at any strength. And this is a one-off treatment whose harms are already on the record.
- **What is missing, methodologically.** The paper states the 1:1 ratio and the masking, but never says who generated the allocation sequence or how it was concealed. It also reports no losses to follow-up between week 4 and week 8. CONSORT asks for both; their absence cannot be seen from the results.

## Participant data on request, no analysis code

- **Data.** De-identified participant data available 12 months after publication, under a data-access agreement.<sup>[[Doe_GutMicrobiome_2025.pdf#page=8|8]]</sup>
- **Code.** No analysis code is offered.
```

## Why these choices matter

- The primary recurrence comparison uses the randomized trial's confidence,
  while the exploratory engraftment claim is explicitly observational. One
  paper can contain claims with different confidence.
- Absolute recurrence rates sit beside the risk ratio. Harms and the uncertain
  quality-of-life result remain visible beside the benefit; a null is not
  written as equivalence.
- Two of four figures are selected, with one rebuilt primary-outcome table.
  The participant-flow and underpowered subgroup figures do not earn space.
  The table caption discloses omitted secondary/subgroup rows.
- The title page supplies only `2025`, so the note pads month/day to `01` and
  the report records that choice. The DOI is included because the fictional
  document prints it; neither date nor URL requires outside lookup.
- The short author list follows the eleven-person byline rule. Preregistration
  remains methodological information, while funding, conflicts and review
  status are outside this note's scope.
- Availability names restricted data access and missing code separately.
  The main limitation is the eight-week horizon, not generic research filler.

## Illustrative verification and lint

On a real PDF, collect all numbers, names and scope tokens, then use the finder
and read their pages. A few example needles are:

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

Save only the output note fence to a unique scratch `.md`, then run:

```bash
python3 '<skill>/scripts/note_lint.py' '<scratch>/Doe_GutMicrobiome_2025.md'
```

The fixture passes mechanical lint. For a real note with these embeds, also pass
`--images '<vault>/Sources/Images'` and inspect each actual figure; omitting the
option here checks the textual example without claiming its fictional images
exist. Lint cannot verify the fictional science or the page citations.

A real run reports source-check counts/corrections and lint separately, then
publishes only after both gates pass. It does not copy this example's facts or
an illustrative verdict into another paper's report.
