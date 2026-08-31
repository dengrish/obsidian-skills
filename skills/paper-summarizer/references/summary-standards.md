# How to state a finding, and its limits

**Read this on every run, before drafting** (SKILL.md step 3). Its trigger is a step number, not a circumstance, and it is listed that way in SKILL.md rather than as an "if" that never fails. It stays a separate file for length: it is the longest thing in this package, and folded into the spine it would be the part a truncated read loses.

It holds three things the spine states only in summary: the claim rules in full, with the phrasings that fail; the design-by-design limitations taxonomy step 8 points at; and the reporting checklists that make a *missing* disclosure visible.

---

## Why this is structure and not advice

The failure this file exists to prevent is not laziness. It is measured, it is specific, and it survives being told not to do it.

- **Peters & Chin-Yee (2025)** compared model-written summaries of research papers against the papers themselves and against human-written summaries of the same papers. Models broadened the scope of the findings in **26–73% of summaries** depending on the model, at roughly **five times the odds** of the human summaries — and **the rate did not fall when the prompt explicitly demanded accuracy.** In several comparisons it rose. Newer, more capable models overgeneralised *more* than older ones, not less.
- **Ovelman et al. (2024)** had model-drafted plain-language summaries reviewed by the authors of the underlying reviews: **3 of 10 contained errors in the results** serious enough to mislead.
- **Greenland et al. (2016)** catalogue the misinterpretations that survive every level of expertise, of which the load-bearing one here is reading a non-significant result as evidence of no effect.
- **Haber et al. (2022)** found that swapping a causal verb for an associational one does **not** stop readers drawing a causal conclusion. The design constraint has to be stated as its own sentence, not carried by a verb choice.
- **Adams et al. (2019)** found that adding explicit caveats to a health-research summary lowered readers' certainty **without** lowering their interest or their trust. Hedging honestly costs nothing a summary is for.
- **Lundh et al. (2017)** found industry-sponsored trials more likely to report results favourable to the sponsor (risk ratio ≈ 1.27). This note does **not** report funding (SKILL.md step 7), so the finding does not become a line in the output; it is here because it is the reason a *result* can lean without any single number being wrong, which is what the claim rules below are defending against.

The intervention that does not work is being careful. The interventions that do are the ones below: a fixed vocabulary, a required clause, a mandatory second number, and a verification pass whose result is an exit code rather than a feeling.

---

## The four claim rules, in full

### 1. Scope clause, always

Every finding names the population, system or setting it holds for. This is the single most common failure measured above, and it is invisible after the fact, because the widened sentence is the better-sounding one.

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
- **When the paper gives only the relative figure**, say so: "the absolute rates are not reported". That absence is itself informative, and inventing the denominator is worse than naming the gap.
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

---

## Where the qualification goes

The four rules above say **what** a claim must carry. They do not say where in the sentence to put it, and the answer the first version of this skill reached by default — all of it, in the main clause — is what made the notes unreadable. A 60-word sentence carrying a design, a population, a comparator and two numbers satisfies every rule above and communicates none of them.

**One plain sentence, then one qualifying sentence.** The claim goes first, in words a scientist from another field can take at speed. The scope, the comparator and the figures follow behind it. The **pair** is what has to satisfy the four rules; neither sentence has to on its own. The qualifier is also where the rung's limit sentence goes — the sentence that says what the study does not show (SKILL.md step 3).

| One sentence, every rule satisfied, nobody can read it | The same claim as a pair |
|---|---|
| Faecal transplant likely reduced recurrence of *C. difficile* infection from 45% to 8% within eight weeks in previously-treated adults with at least two prior recurrences, against placebo, in a 219-patient double-blind trial. | The trial shows that the transplant cuts recurrence by about four fifths. Recurrence fell from 45% to 8% within eight weeks, against placebo. The 219 adults had all had at least two prior recurrences. |
| eUniRep likely raises the rate of better-than-wild-type designs well above a one-hot sequence encoding given as few as 24 assayed mutants, in avGFP and TEM-1 β-lactamase. | Twenty-four measured mutants were enough to design a better protein. About one design in ten beat the natural protein. The same pipeline without pre-training gave almost none. The test covered two proteins. |

**The limit sentence sits immediately behind the result sentence, never further away.** Callout bullets are read out of order and section headings are read alone, so the pair has to survive being read as a unit of two. A modal verb is not a fallback for it: Haber et al. (2022), above, found that *may* and *is associated with* do not stop a causal reading, so the second sentence is the only thing carrying the constraint. Separate the two and the sentence that gets read is the unqualified one.

**A plain sentence with no qualifier behind it is the new failure mode.** The old shape could not lose a scope clause without losing the sentence; this one can, and it reads perfectly well when it does. That is why step 10's verification puts every scope clause through the finder as its own needle, and why the checklist asks for the pair rather than for the clause.

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

SKILL.md's table is the ladder. This is how to place a paper on it.

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

**Take the lower of two rungs — the design's, and the authors' own.** Authors overstate their own observational findings routinely; that does not license the note to. The reverse also holds: a rung-1 design whose authors hedge is written at their hedge, with a line noting that the design would have supported more.

**Peer-review status does not move a rung**, and this note does not report it (SKILL.md step 7). A preprint's design is its design; describe the design and let the rung follow from it. "Preprint" is not a design and can never stand in for one.

---

## Statistical statements

- **A p-value is not the probability the finding is wrong**, not the probability the null is true, and not a measure of effect size. If a p-value is the only number the paper gives for a result, the note says the effect size is not reported.
- **Report the interval, not just the point estimate**, for anything the summary leans on. The interval is what tells a reader how much the study actually pinned down.
- **"Significant" without "statistically" reads as "important".** Where the note needs the technical sense, write "statistically significant"; where it means important, do not use the word.
- **A subgroup finding is a hypothesis**, not a result, unless it was pre-specified and the interaction was tested. Say which.
- **Multiplicity:** a paper reporting twenty outcomes and highlighting the one that reached significance is reporting a different kind of result from one that pre-registered a single primary outcome. Name that in *Limitations*.

---

## The limitations taxonomy, by design

Step 8's six categories are the sweep to run on every paper — *considered* on every paper, and written only where they bite, since the section holds two to four bullets. These are the additional ones each design is prone to — the ones a reader who does not know the design would never think to ask about.

- **Randomised trial** — attrition and how it was handled; whether patients, clinicians and assessors were blinded; whether the primary outcome matches the registered one; whether the comparator was a fair one (placebo where standard care exists is a real limitation); whether the trial was stopped early; whether the population was healthier than the people the treatment is for.
- **Cohort / observational** — confounding by indication, and which confounders were and were not measured; loss to follow-up; how exposure was ascertained (self-report is a limitation); reverse causation; whether the analysis was pre-specified.
- **Cross-sectional / survey** — response rate and who did not answer; self-report and recall; that cause and effect are indistinguishable in principle here, not merely unresolved.
- **Systematic review / meta-analysis** — **two distinct sets, and merging them hides one.** *Limits of the evidence*: the quality and risk of bias of the pooled studies, heterogeneity between them, small-study and publication bias, how few and how small they were. *Limits of the review process*: databases searched and languages included, whether screening and extraction were done in duplicate, whether the protocol was registered, how the certainty of evidence was graded, how current the search is. A summary that says "the studies were low quality" without saying "the search covered only English-language journals" has reported half.
- **Modelling / simulation** — which assumptions drive the result; whether the model was validated against anything outside its own fit; the range over which the parameters were varied; that the output is a consequence of the inputs.
- **Machine-learning benchmark** — train/test contamination and whether it was checked; whether the benchmark measures the capability it stands for; how many seeds and what the variance across them was; whether the baselines were tuned as hard as the proposed method; compute and data disparities; whether the evaluation set is public and therefore likely in the training data.
- **Animal / in-vitro** — species, strain, sex and age; whether the model reproduces the human condition or one feature of it; dose scaling; sample sizes that are typically small enough that a single outlier moves the result.
- **Case series** — selection: these are the cases someone chose to write up, which is the strongest possible selection effect.
- **Qualitative** — who was recruited and who was not; the analyst's framing; and that transferability, not generalisability, is the relevant question.

**A proxy outcome is a limitation on every design.** A biomarker standing in for survival, a benchmark score standing in for capability, an intention standing in for a behaviour, a surrogate endpoint standing in for the thing the reader cares about — name the substitution, in the note, in the *Limitations* section, whether or not the paper does.

---

## What the paper should have disclosed

A missing disclosure is a limitation, and it is the one a reader could never notice on their own. Each design has a reporting checklist stating what a complete report contains; hold the paper against the right one and name what is not there.

| Design | Checklist | The items most often missing |
|---|---|---|
| Randomised trial | CONSORT | trial registration id, how randomisation was concealed, who was blinded, the flow of participants and why they dropped out, harms |
| Observational study | STROBE | how the sample was selected, which confounders were adjusted for, how missing data were handled, sensitivity analyses |
| Systematic review / meta-analysis | PRISMA | the protocol registration, the full search strategy and date, duplicate screening, risk-of-bias assessment, certainty grading |
| Animal study | ARRIVE | species, strain, sex, age, sample size and how it was chosen, randomisation and blinding, animals excluded and why |
| Diagnostic accuracy | STARD | the reference standard, and whether it was applied blind to the index test |
| Certainty of a body of evidence | GRADE | how confidence was rated down, and for what |

**Write the absence, not a hedge about it.** "The paper does not report how many patients withdrew" is a fact the reader can act on; "the methods are somewhat unclear" is not.

---

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
| experts say | *(cut: a summary of one paper has no experts in it)* |

---

## Sources

Cochrane's plain-language summary standard (the only widely-used summary format that *mandates* a limitations section, which is why step 8 is a step rather than a habit); the eLife digest and PNAS Significance Statement formats; the PLOS author-summary guidance; the EU's Good Lay Summary Practice; ISO 24495-1:2023 on plain language; CONSORT, STROBE, PRISMA, ARRIVE, STARD and GRADE for what a complete report contains; the ASA statement on p-values and SAMPL for statistical reporting; and the IPCC AR6 visual style guide for the one-message-per-figure caption rule (`references/figures.md`).

The empirical claims at the top of this file are Peters & Chin-Yee (2025), Ovelman et al. (2024), Greenland et al. (2016), Haber et al. (2022), Adams et al. (2019) and Lundh et al. (2017).

**No authoritative guidance exists on which figure of a paper carries its argument** — that judgment is genuinely unstandardised, which is why `references/figures.md` falls back on a mechanical tiebreak (how often the body text refers to each figure) rather than pretending to a rule.
