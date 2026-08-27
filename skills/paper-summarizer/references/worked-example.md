# Worked example — one paper, start to finish

**Read this when** you are about to write the first note of a session and want the whole output shape in one piece, or when a piece of it is unclear — where the callout sits against the frontmatter, how a figure and its caption fall under the claim they support, how a table that is a result gets rebuilt, how a page is cited, what a verification pass looks like when it finds something. It is illustration, not rules: the rules are in the workflow steps and the other reference files.

The note below is the fixture the format is checked against. It passes `scripts/note_lint.py` with no findings; if you change it, re-lint it.

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

The paper also carries a funding statement, a competing-interests declaration and a journal name. **None of the three reaches the note** (SKILL.md step 7). They are in this input list only so that their absence downstream is visibly deliberate rather than an oversight.

## The output note

Written to `Articles/Doe_GutMicrobiome_2025.md`. The PDF is not moved, renamed or touched:

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

| Arm | Recurrence by 8 weeks |
|---|---|
| Transplant (n=110) | **8.2%** (9 of 110) |
| Placebo (n=109) | 45.0% (49 of 109) |
*Recurrence was about five times lower on transplant. The primary outcome only; the secondary outcomes and the subgroup rows are in the paper.*

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

## Things to notice in this example

- **No blank line between the closing `---` and `> [!Summary]`.** The callout opens flush on the next line; then one blank line, the `___` rule, another blank line, and the first `##`. That is the whole of step 11's assembly order, and `note_lint.py` fails a note that gets any part of it wrong.
- **The first bullet is the finding, and it carries all four claim rules at once** — the scope clause ("in adults with at least two prior recurrences"), the absolute pair beside the relative one (45.0% and 8.2%, then the risk ratio), the named comparator ("on placebo"), and a rung-1 verb. Drop the scope clause and it becomes "Faecal transplant cuts C. difficile recurrence to 8%", which reads better, is what a reader will actually remember, and is now a claim about everyone with this infection rather than about people who have already relapsed twice. That widening is the failure mode the whole skill is built around, and nothing downstream can see it.
- **A relative-only version would fail the same way.** "Cut recurrence by 82%" is arithmetically true of a risk ratio of 0.18 and tells the reader nothing about whether the baseline was 45% or 4.5%; relative changes reliably read as larger than they are.
- **Rung 1 is licensed here and nowhere else in the note.** The design is a randomised, blinded, placebo-controlled trial that met its enrolment target, and the authors claim causation, so "cut" and "reduces" survive the lower-of-two-rungs test for the primary outcome. The engraftment paragraph drops to rung 3 — "are associated with" — in the same note, because nobody was randomised to engraft.
- **Methods is a short paragraph and then numbered steps, because this paper has a procedure to walk through.** The paragraph holds the design facts (registration, powering, donors); the five steps are the protocol in order — enrolment, randomisation, dosing, masking, outcome adjudication — each under step 7a's 20-word cap. A theory paper or a comment takes the paragraph alone; a trial does not.
- **The null secondary is written as a null, not an absence.** "Did not detect a difference … 95% CI −3.1 to +8.3 … a benefit of up to 8.3 points is not ruled out". The two tempting alternatives — "quality of life was no different between the arms", "the capsules were as good as placebo on quality of life" — are a different claim, one this trial did not make and this sample size could not have supported.
- **Harms are reported in the same section as the benefit,** with the same precision: 27 of 110 against 11 of 109, and the single bacteraemia named rather than folded into "generally well tolerated". A summary carrying only what worked is not a shorter version of the paper.
- **`published: 2025-01-01` is padding, not a claim.** The title page prints only the year, so the month and day are `01` under step 5's rule and the run's report says so. Had it printed `12 March 2025` the value would be `2025-03-12`; had it printed `March 2025`, `2025-03-01`. The day is never fetched from a DOI record or a publisher page to fill the gap — the note carries what this PDF states, padded.
- **One rebuilt table, and it announces its trim.** The primary-outcome table is a result the note claims, so it is rebuilt in markdown rather than pointed at — nothing extracts tables, and "the paper's Table 2 has the comparison" would send the reader somewhere they are not. Its caption ends *"the primary outcome only; the secondary outcomes are in the paper"*, because a trimmed table that looks complete is worse than no table.
- **Nothing in the note names a figure, a table, an appendix or a supplement.** The note is self-contained: if an exhibit matters it is in the note, and if it is not in the note it is not mentioned. That is what makes the numbers safe to drop from the captions too.
- **Two figures out of four, each directly under the claim it supports.** Figure 1 is the participant flow diagram and figure 3 the subgroup forest plot; the first is study flow and the second a panel the paper itself calls underpowered, so neither earns a place. Between the remaining candidates the body text's citation counts settled it. Both files were already on disk, keyed to this PDF's stem (`CONVENTIONS.md` §8a); this skill embeds what it finds and never extracts, crops or renames one.
- **Neither caption carries a figure number, and neither does the prose.** The extracted files are `_fig_2` and `_fig_4` and the paper calls them Figure 2 and Figure 4, but the note says neither: the picture sits under the claim it belongs to, so the number points at nothing the reader needs, and carrying it means maintaining a second name for the figure that can silently disagree with the file (SKILL.md step 4).
- **Captions lead with the message, not the axes.** "The two arms separated inside the first fortnight and stayed apart to week 8" is the take-away; the Kaplan–Meier machinery is the second sentence. A caption reading only "Kaplan–Meier curves for time to first recurrence" tells a reader what they are looking at and nothing about why they are looking at it, and it does not stand alone.
- **Citations are superscript links showing the page number, and there is no list at the bottom.** `<sup>[[Doe_GutMicrobiome_2025.pdf#page=5|5]]</sup>` renders as a raised `5` that opens page 5 — the filename hidden, nothing to renumber when a paragraph moves, nothing at the end of the file to keep in sync. It sits **immediately after the closing full stop, with no space**, the way a numeric citation style sets it; a space renders as a floating digit. `N` is the **physical** page (`CONVENTIONS.md` §7): `#page=5` is the fifth page of the file, whatever folio is printed on it. Citations sit on the load-bearing numbers — the design, the primary outcome, the harms, the null, the authors' limitations, the data availability — and not on every sentence. **The note ends at *Availability***; there is no reference block after it.
- **The frontmatter details that are easy to get wrong.** `title:` is quoted because it contains a colon; the `sources:` list carries a second, double-quoted URL item only because the paper prints a DOI (`CONVENTIONS.md` §2b); the author list is the first three then `- et al.` for an eleven-author paper; one tag, double-quoted, from the enum in `CONVENTIONS.md` §3; `read: false` bare and last, since a quoted `"false"` renders as permanently ticked. `sources:` item 1 is the bare wikilink, and it is safe in that form because the PDF's basename is vault-unique (`CONVENTIONS.md` §1a) — which is also why the note is named after the PDF's stem and why the figure embeds resolve.
- **Every sentence in *Interpretation* is either theirs or marked as not theirs.** The conclusion and both of its explicit exclusions are attributed to the authors; the sentence about the 8-week horizon opens "The authors do not put it this way, but", because an unattributed inference in that section is indistinguishable from a finding.
- **Four limitations, not six, and nothing says "does not apply."** Step 8's sweep considers six categories; this note writes the four that would change what a reader does. The proxy-outcome item was considered and dropped — the primary outcome *is* the clinical event, so there is nothing to say — and it is simply absent rather than written out and dismissed, which is what used to make this section the longest in the note. The precision item went the same way: the interval is wide but entirely on one side of no effect, and the underpowered subgroup plot is not an exhibit this note carries. What survives includes the one a reader could never have noticed on their own — allocation concealment and attrition, both required by CONSORT and both absent.
- **The caveat about a single number is not in *Limitations*.** "Each cell is a single run" style qualifications live beside the number they qualify — in the prose of *Results* or in an exhibit caption — where a reader meets them while looking at the thing they bear on. *Limitations* is for what qualifies the paper.
- **What is not in this note, and was in the source.** The trial's funder manufactures the capsule under test; four of the eleven authors report consulting fees from it; it ran in *The Lancet Gastroenterology & Hepatology*. All three are real facts about the paper and none appears anywhere above — not in *Availability*, not in *Limitations*, not as an aside (step 7). **Preregistration is the exception that proves the split**: `NCT05712398` is in *Methods*, because whether the primary outcome was pre-specified changes how the result reads, which makes it method rather than governance.
- ***Availability* says "no analysis code is offered" rather than dropping the line.** A section that lists data and is silent on code reads as a paper that released both, and a reader cannot tell that silence from an absence.

## The verification pass that was run over it

Step 10 runs after the draft exists and against the PDF, never as a re-read of the draft. Every number, proper noun and scope clause in the note above went through the finder in one command:

```bash
python3 '<skill>/scripts/paper_text.py' '<vault>/Sources/PDFs/Doe_GutMicrobiome_2025.pdf' \
    --find '9 of 110' --find '49 of 109' --find '36.8 percentage points' \
    --find 'risk ratio 0.18' --find 'at least two prior recurrences' \
    --find '27 of 110' --find '11 of 109' --find 'Escherichia coli bacteraemia' \
    --find 'GIQLI' --find 'NCT05712398' \
    --find 'Clostridioides difficile' --find '12 weeks'
```

```
FOUND   '9 of 110'                               page(s) 5
FOUND   '49 of 109'                              page(s) 5
FOUND   '36.8 percentage points'                 page(s) 5
FOUND   'risk ratio 0.18'                        page(s) 5
FOUND   'at least two prior recurrences'         page(s) 3
FOUND   '27 of 110'                              page(s) 6
FOUND   '11 of 109'                              page(s) 6
FOUND   'Escherichia coli bacteraemia'           page(s) 6
FOUND   'GIQLI'                                  page(s) 3, 6
FOUND   'NCT05712398'                            page(s) 8
loose   'Clostridioides difficile'               page(s) 1, 3  (matched only with spacing and hyphens removed -- read the page before citing it)
MISSING '12 weeks'                               not on any page. Cut the claim or fix it; do not soften it.

10 of 12 needle(s) found exactly; 1 loose; 1 missing
A loose match is NOT a verification. Squashing spaces and hyphens is what recovers a word the PDF broke across a line -- and it is also what joins two things the paper kept apart ('...to 2015. 3 patients...' matches '2015.3'). Open each loose page and read it before citing.
```

Exit code 1, and two lines to act on. **The summary counts the loose match apart from the exact ones on purpose** — ten of the twelve are verified, not eleven — and the advisory under it is printed whenever any needle came back loose.

**`MISSING '12 weeks'` — one claim corrected.** The draft's engraftment paragraph said donor strains were "still detectable 12 weeks after dosing". The trial's exploratory sampling stopped at week 8; the twelve came from the drafting, not from the paper. The rule is cut or correct, never soften: "appeared to persist for some weeks" would have passed every future check and kept the error permanently. The sentence was rewritten to the week-8 form that appears in the note above, and the replacement needle re-run on its own:

```bash
python3 '<skill>/scripts/paper_text.py' '<vault>/Sources/PDFs/Doe_GutMicrobiome_2025.pdf' --find 'week 8'
```

```
FOUND   'week 8'                                 page(s) 3, 5, 6, 7

1 of 1 needle(s) found exactly; 0 loose; 0 missing
```

**`loose 'Clostridioides difficile'` — one page to open.** The match only came back after spacing and hyphens were stripped, because the PDF's text layer breaks the species name across a line on both pages. Pages 1 and 3 were opened and read: the name is right and nothing changed. A loose line is not a pass, it is an instruction to look.

## The lint that ran after it

Step 11a, on the drafted file, before it was written to `Articles/`:

```bash
python3 '<skill>/scripts/note_lint.py' '<draft>.md' --images '<vault>/Sources/Images'
```

```
<draft>.md: clean
```

The first run was not clean. It reported two lines, both of which the eye had read straight past:

```
<draft>.md:2: `published: 2025` must be a full YYYY-MM-DD date (pad an unstated month or day with 01)
<draft>.md:63: caption opens with an exhibit number, which this note never carries: '*Figure 2 — The two arms separated inside the first fortnigh'
2 violation(s)
```

Findings come back **sorted by line number**, and the run ends on a `N violation(s)` trailer — so the last line is the count to quote in the step 12 report, and the exit status is 1.

Both are habits from the format this one replaced, and both are invisible from inside a note that is otherwise well-formed — which is the entire reason the check is a script and not a bullet in a checklist.

Both results go in the step 12 report, which for this run said: *verification: 12 needles checked, 10 located exactly; 1 claim corrected (the 12-week durability sentence, cut back to week 8); 1 loose match (the species name, hyphenated across a line on pages 1 and 3, confirmed by eye). Lint: 2 violations, fixed (a numbered caption, and a bare-year `published`).*

Note that the paths and the needles are single-quoted in every command above. The paths are the user's and the needles are text lifted straight off a paper, so neither is this skill's to hand to a shell unquoted (`CONVENTIONS.md` §1b).
