# How to state a contribution and its limits

- [The four claim rules, in full](#the-four-claim-rules-in-full)
- [Where the qualification goes](#where-the-qualification-goes)
- [Naming the size of a number](#naming-the-size-of-a-number)
- [The hedge ladder, and what sets its ceiling](#the-hedge-ladder-and-what-sets-its-ceiling)
- [Statistical statements](#statistical-statements)
- [The limitations taxonomy, by mode and design](#the-limitations-taxonomy-by-mode-and-design)
- [What an empirical document should have disclosed](#what-an-empirical-document-should-have-disclosed)
- [A phrasing bank](#a-phrasing-bank)
- [Sources](#sources)

Read before recording claims or drafting a summary. This reference owns claim
scope, confidence and evidential limitations. [Note format](note-format.md) owns
the section shape, body modes and length limits; [verification](review-checklist.md)
checks the resulting claims against the PDF.

## The four claim rules, in full

### 1. Scope clause, always

Every finding names the population, system or setting it holds for. Check that the wording is no broader than the population actually studied.

| Fails | Holds |
|---|---|
| improves survival | improved survival in previously-treated adults with metastatic disease |
| reduces inflammation in mice | reduced inflammation in male C57BL/6 mice at 8 weeks |
| the model outperforms humans | scored above the human baseline on this benchmark's 500 held-out items |
| people who exercise live longer | in this cohort of 34,000 Danish adults followed 12 years, those reporting more exercise died at lower rates |

**Watch the plural and the definite article.** "In mice" from a single strain, "patients" from one hospital, "the effect" from one subgroup — each quietly promotes a specific result to a general one. If the paper's own methods section narrows the population and the note's sentence does not, the note has overgeneralised.

**Dose, duration and setting are part of the scope.** A finding at 12 weeks is not a finding about durability. A finding at a dose nobody takes is not a finding about the drug as used.

### 2. Absolute numbers beside every relative one

A relative change with no absolute anchor reliably reads as larger than it is, and it is the standard way a small effect is made to sound decisive.

- **Write:** "cut recurrence from 45% to 8% — a 37-percentage-point absolute reduction".
- **Not:** "cut recurrence by 82%".
- **When the document gives only the relative figure**, say so: "the absolute rates are not reported". That absence is itself informative, and inventing the denominator is worse than naming the gap.
- **A hazard ratio, an odds ratio and a risk ratio are all relative** and all need the same treatment. So does "2.3× more likely".
- **Give the denominator.** "14 of 219" beats "6.4%" for anything small, and both together beat either.

### 3. Name the comparator

A comparative claim with no comparator is not a claim. "Versus placebo", "versus standard care", "versus the 2019 baseline", "versus no intervention", "versus the same patients before treatment" — these are five different studies, and which one it was decides what the number means.

**"Better" with no comparator is the commonest one-word overstatement in a summary.** So is "effective", which silently supplies a comparator of *nothing*.

### 4. A null result is not an absence

Absence of evidence is what the study reported. Absence of effect is a different claim, and this study did not make it.

| Fails | Holds |
|---|---|
| had no effect on quality of life | did not detect a difference in quality of life (95% CI −2.1 to +3.4 points, so a benefit up to 3.4 points is not ruled out) |
| was as safe as placebo | serious adverse events were similar in number (11 vs 9), but the trial was not sized to detect a difference in them |
| showed no difference between groups | the difference did not reach the study's significance threshold; the interval is wide enough to include a clinically meaningful effect in either direction |

**Always carry the interval on a null**, because the interval is the whole content of the result. A null with a tight interval around zero is genuine evidence of a small effect; a null with a wide interval is no information at all, and the two must not be written the same way.

**"Not statistically significant" is not a synonym for "small".** And a difference between a significant result and a non-significant one is not itself a finding unless the paper tested it directly.


## Where the qualification goes

Keep each claim and its qualification together without packing design, population, comparator and numbers into one long sentence.

**One plain sentence, then one qualifying sentence.** The claim goes first, in words a scientist from another field can take at speed. The scope, the comparator and the figures follow behind it. The **pair** is what has to satisfy the four rules; neither sentence has to on its own. The qualifier is also where the rung's limit sentence goes — the sentence that says what the study does not show (see the confidence ladder below).

| One sentence, every rule satisfied, nobody can read it | The same claim as a pair |
|---|---|
| Faecal transplant likely reduced recurrence of *C. difficile* infection from 45% to 8% within eight weeks in previously-treated adults with at least two prior recurrences, against placebo, in a 219-patient double-blind trial. | The trial shows that the transplant cuts recurrence by about four fifths. Recurrence fell from 45% to 8% within eight weeks, against placebo. The 219 adults had all had at least two prior recurrences. |
| eUniRep likely raises the rate of better-than-wild-type designs well above a one-hot sequence encoding given as few as 24 assayed mutants, in avGFP and TEM-1 β-lactamase. | Twenty-four measured mutants were enough to design a better protein. About one design in ten beat the natural protein. The same pipeline without pre-training gave almost none. The test covered two proteins. |

**The limit sentence sits immediately behind the result sentence, never further away.** Callout bullets are read out of order and section headings are read alone, so the pair has to survive being read as a unit of two. A modal verb alone does not explain the design constraint; state what the study does not show. Separate the two and the sentence that gets read is the unqualified one.

Verify scope clauses as claims in their own right. A fluent finding followed by no qualification is still an overstatement.

## Naming the size of a number

A reader outside the field cannot tell whether a hazard ratio of 0.62, a fold change of 3.1, an r of 0.51 or a benchmark score of 78.4 is a lot. Say what it means in words once, then give the figures:

| Fails | Holds |
|---|---|
| a hazard ratio of 0.62 | a 38% lower estimated event hazard, the instantaneous event rate among people still at risk (hazard ratio 0.62) |
| Pearson r = 0.51 | a positive linear association between the two measured variables (r = 0.51); this does not establish causation |
| a 3.1× improvement | 3.1 times as many, from 10 to 31, when those are the counts the paper reports |

This is not a substitute for the absolute numbers of rule 2 — it sits beside them. And it is done **once per quantity**: a note that re-explains the same statistic at every mention is as tiring as one that never explains it.

**Keep the measures distinct.** A hazard ratio is not a cumulative risk ratio or a ratio of event counts, and an odds ratio is not a risk ratio. Absolute risk also needs a population and a time horizon. Use the paper's reported absolute figures; if they are absent, name the gap rather than converting the ratio by intuition. See [Cochrane Handbook, effect measures](https://www.cochrane.org/authors/handbooks-and-manuals/handbook/current/chapter-06) and [time-to-event outcomes](https://www.cochrane.org/authors/handbooks-and-manuals/handbook/current/chapter-14#section-14-1-5-2).

Squaring a correlation is not a general-purpose estimate of explained variation. That interpretation requires the corresponding regression setup, such as simple least-squares regression with an intercept, and does not imply a causal explanation. Preserve the statistic and explain the association when the paper does not establish that setup.

## The hedge ladder, and what sets its ceiling

| Rung | When | The second sentence |
|---|---|---|
| 1 | an adequately powered randomised controlled experiment with its reported outcome prespecified | none needed beyond the scope: *"The trial shows that the transplant reduces recurrence."* |
| 2 | strong quasi-experimental design, or consistent evidence across designs, with the confounders addressed | *"The design is not randomised. Other causes are possible, and the authors tested for the known ones."* |
| 3 | a single observational study, a correlational finding, an underpowered or unregistered experiment | *"It does not show that exercise causes the difference."* |
| 4 | mechanistic, in-vitro, animal-only, simulation, a pilot, or a case series | *"The test was in cells only. The paper does not show an effect in people."* |

The rung governs a claim and its adjacent qualification, not a hedge word.
These statements sit off the effect ladder:

- A **null result** uses the null/interval rule above; do not force an effect rung
  onto an undetected effect.
- A **non-evidential statement** is attributed to whoever made it, not graded.
- A **descriptive qualitative finding** characterises the participants studied;
  attribute it and make no frequency estimate. A claim extending beyond those
  participants needs the conservative design limit, at rung 4.
- A **theoretical argument, formal result or normative recommendation** is
  attributed to the document and assessed through its premises, reasoning and
  cited evidence. Do not assign it an effect rung unless the document separately
  reports an empirical effect.
- A **notice action** states what an issuer corrected, withdrew or questioned
  and on what stated grounds. It does not independently establish the affected
  paper's findings, and it takes no effect rung.

The report names the applicable off-ladder case instead of leaving confidence
unexplained. For effect claims, apply the design ceiling below.


| Design | Ceiling | Why |
|---|---|---|
| Randomised controlled trial, adequately powered, preregistered, outcome as registered | rung 1 | randomisation is what licenses a causal verb |
| Randomised trial with a switched primary outcome, heavy attrition, or a subgroup-only result | rung 3 | the randomisation no longer protects the comparison being reported |
| Regression discontinuity, difference-in-differences, instrumental variable, natural experiment, with the identifying assumption argued | rung 2 | causal identification without randomisation, and it rests on an assumption the reader should see named |
| Prospective cohort with pre-specified confounders | rung 3 | confounding by indication cannot be excluded |
| Cross-sectional, case-control, retrospective chart review, correlational | rung 3 | and the direction of the arrow is usually not established either |
| Systematic review / meta-analysis | the ceiling of the studies it pooled, never higher | pooling does not upgrade the design; a meta-analysis of observational studies is observational, however large the summed sample |
| Animal, in-vitro, organoid, ex-vivo | rung 4, **and the claim is about that system** | the finding is about mice or cells; it is not a hedged finding about people |
| Simulation or mathematical model | rung 4, **and the claim is about the model** | a model's output is evidence about the model's assumptions |
| Machine-learning benchmark evaluation | rung 2 for the measurement when the comparison was controlled — same data, same budget, several seeds, variance reported — and rung 3 otherwise; **rung 3 at best for any claim about the capability** | a benchmark score is a claim about the benchmark, which is a proxy for the capability (see the proxy rule below). Rung 1 is not reachable: nothing here is randomised |
| Case report, case series | rung 4 | there is no comparison group at all, so there is no effect to size |
| Qualitative study | off the effect ladder | it characterises and it does not estimate; describe what it found and who it asked, and make no frequency claim from it |
| Pilot, feasibility, "preliminary" by the authors' own word | rung 4 | whatever the design |

**Take the more conservative (numerically higher) of two rungs — the design's,
and the authors' own.** Authors overstate their own observational findings
routinely; that does not license the note to. The reverse also holds: a rung-1
design whose authors hedge is written at their hedge, with a line noting that
the design would have supported more.

**Peer-review status does not move a rung**, and this note does not report it ([scope](note-format.md#body-content)). A preprint's design is its design; describe the design and let the rung follow from it. "Preprint" is not a design and can never stand in for one.


## Statistical statements

- **A p-value is not the probability the finding is wrong**, not the probability the null is true, and not a measure of effect size. If a p-value is the only number the document gives for a result, the note says the effect size is not reported.
- **Report the interval, not just the point estimate**, for anything the summary leans on. The interval is what tells a reader how much the study actually pinned down.
- **"Significant" without "statistically" reads as "important".** Where the note needs the technical sense, write "statistically significant"; where it means important, do not use the word.
- **A subgroup finding is a hypothesis**, not a result, unless it was pre-specified and the interaction was tested. Say which.
- **Multiplicity:** a paper reporting twenty outcomes and highlighting the one that reached significance is reporting a different kind of result from one that pre-registered a single primary outcome. Name that in *Limitations*.


## The limitations taxonomy, by mode and design

For an empirical note, consider all six categories below; normally write 2–4
limitations that would change how a reader acts on or cites the finding. One is
allowed only when a second material limitation would be filler, with that
advisory exception explained in the run report:

1. What the design cannot show.
2. Who or what was studied, and the population/setting it does not cover.
3. A proxy outcome substituted for the outcome of interest.
4. Precision: wide intervals, small samples/effects, subgroups or post-hoc work.
5. Material caveats the authors name.
6. Missing **methodological** disclosures: registration, blinding, attrition,
   sample-size justification, seeds or contamination checks. Funding, conflicts
   and ethics remain outside the note's scope.

Merge related limitations, fold repeated author caveats into the relevant
bullet, and omit categories that do not apply. Put a caveat about one number
beside that number, not again in Limitations. State the document-level constraint
once; avoid generic “more research is needed” filler.

For an argument/synthesis note, instead consider its declared scope and source
selection, premises not supported by its supplied evidence, counterarguments it
raises but does not resolve, dependence on a particular framework, currency,
and conditions outside which a conclusion or recommendation does not apply.

For a notice, consider the precise claims and versions covered, the evidence or
process the notice supplies, and questions it explicitly leaves unresolved. A
disagreement with the author is not itself a limitation. In either mode, keep
only boundaries supported by the PDF or by a directly verified absence in it;
do not invent a failed experiment, missing protocol or generic research caveat.

Use these design-specific prompts to find candidates:

- **Randomised trial** — attrition and how it was handled; whether patients, clinicians and assessors were blinded; whether the primary outcome matches the registered one; whether the comparator was a fair one (placebo where standard care exists is a real limitation); whether the trial was stopped early; whether the population was healthier than the people the treatment is for.
- **Cohort / observational** — confounding by indication, and which confounders were and were not measured; loss to follow-up; how exposure was ascertained (self-report is a limitation); reverse causation; whether the analysis was pre-specified.
- **Cross-sectional / survey** — response rate and who did not answer; self-report and recall; that cause and effect are indistinguishable in principle here, not merely unresolved.
- **Systematic review / meta-analysis** — **two distinct sets, and merging them hides one.** *Limits of the evidence*: the quality and risk of bias of the pooled studies, heterogeneity between them, small-study and publication bias, how few and how small they were. *Limits of the review process*: databases searched and languages included, whether screening and extraction were done in duplicate, whether the protocol was registered, how the certainty of evidence was graded, how current the search is. A summary that says "the studies were low quality" without saying "the search covered only English-language journals" has reported half.
- **Modelling / simulation** — which assumptions drive the result; whether the model was validated against anything outside its own fit; the range over which the parameters were varied; that the output is a consequence of the inputs.
- **Machine-learning benchmark** — train/test contamination and whether it was checked; whether the benchmark measures the capability it stands for; how many seeds and what the variance across them was; whether the baselines were tuned as hard as the proposed method; compute and data disparities; whether the evaluation set is public and therefore likely in the training data.
- **Animal / in-vitro** — species, strain, sex and age; whether the model reproduces the human condition or one feature of it; dose scaling; sample sizes that are typically small enough that a single outlier moves the result.
- **Case series** — selection: these are the cases someone chose to write up, which is the strongest possible selection effect.
- **Qualitative** — who was recruited and who was not; the analyst's framing; and that transferability, not generalisability, is the relevant question.

**A proxy outcome is a limitation on every empirical design.** A biomarker standing in for survival, a benchmark score standing in for capability, an intention standing in for a behaviour, a surrogate endpoint standing in for the thing the reader cares about — name the substitution, in the note, in the *Limitations* section, whether or not the paper does.


## What an empirical document should have disclosed

For an empirical document, a missing disclosure is a limitation, and it is the
one a reader could never notice on their own. Each design has a reporting
checklist stating what a complete report contains; hold the paper against the
right one and name what is not there. Non-empirical notes use the mode-specific
prompts above rather than pretending an empirical checklist applies.

| Design | Checklist | The items most often missing |
|---|---|---|
| Randomised trial | CONSORT | trial registration id, how randomisation was concealed, who was blinded, the flow of participants and why they dropped out, harms |
| Observational study | STROBE | how the sample was selected, which confounders were adjusted for, how missing data were handled, sensitivity analyses |
| Systematic review / meta-analysis | PRISMA | the protocol registration, the full search strategy and date, duplicate screening, risk-of-bias assessment, certainty grading |
| Animal study | ARRIVE | species, strain, sex, age, sample size and how it was chosen, randomisation and blinding, animals excluded and why |
| Diagnostic accuracy | STARD | the reference standard, and whether it was applied blind to the index test |
| Certainty of a body of evidence | GRADE | how confidence was rated down, and for what |

**Write the absence, not a hedge about it.** "The paper does not report how many patients withdrew" is a fact the reader can act on; "the methods are somewhat unclear" is not.


## A phrasing bank

| Instead of | Write |
|---|---|
| proves / confirms | the trial found; the data are consistent with |
| a breakthrough / a game-changer | the first result of its kind, in a 219-patient trial |
| significantly better | statistically significantly better, at a difference of X points |
| safe | no serious adverse events were reported in N participants over M weeks — a period too short to detect late harms |
| shows that X causes Y | in a randomised trial, X reduced Y from A to B (rung 1); or: X is associated with lower Y; the design cannot separate that from the reasons people had X (rung 3) |
| more research is needed | the open question is specifically whether the effect holds past 12 weeks |
| the authors conclude | *(only where they actually do — and then say it plainly)* |
| experts say | *(cut: a summary of one document has no experts in it)* |


## Sources

Background standards: Cochrane's plain-language summary standard; the eLife digest and PNAS Significance Statement formats; the PLOS author-summary guidance; the EU's Good Lay Summary Practice; ISO 24495-1:2023 on plain language; CONSORT, STROBE, PRISMA, ARRIVE, STARD and GRADE for what a complete report contains; the ASA statement on p-values and SAMPL for statistical reporting; and the IPCC AR6 visual style guide for the one-message-per-figure caption rule ([figures](figures.md)).


Figure selection remains judgment guided by the claim; [figures](figures.md#which-ones-to-carry) uses citation frequency only as a tiebreak.
