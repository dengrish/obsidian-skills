# Daily market note format

Use `<vault>/Investments/YYYY-MM-DD-market-research.md`, with the review's
**America/New_York** date and one ordinary edition per calendar day. Keep prior
notes unchanged; place corrections and changed assessments in the next dated
note with a link to the affected record.

Each note has two parts: a short **Decision brief** for the user and a detailed
**Research record** for future research. Both are visible Markdown in the same
file. The record preserves evidence and concise reasons for conclusions; it is
not a transcript of the research process. It may be much longer than the brief,
but should not repeat full articles, entire social feeds, or unchanged earlier
analyses. No fixed word target applies to the record. The helper's 256 KiB file
safety limit is not a writing target.

## Metadata and outline

Use these six frontmatter keys, in this order. `market_research` is the integer
schema version `1`; `date` is an ISO date. Quote `as_of` and `generated_at` as ISO
datetimes with explicit UTC offsets, using New York's offset for each timestamp.
`as_of` is the latest permitted evidence timestamp, not the retrieval time of a
page. It must not follow `generated_at` or belong to another New York date.
Record the actual completion time in `generated_at`, not the scheduled start.

`session` is `premarket`, `closed`, `intraday`, `after-hours`, or `unknown`, based
on the verified exchange session at the cutoff. `coverage` is `normal`, `limited`,
or `unavailable`; normal means the declared screen was checked adequately, not
that every listed stock was assessed. Explain material missing data in the brief.
No Wiki/source-note frontmatter, flashcards, or review checkboxes are needed.

Keep exactly the two H2 headings and six H3 subsections below, in order. Opening
conclusion/coverage prose belongs directly under Decision brief. Research record
starts with its first subsection; use H4 or deeper headings for individual
candidates or supporting detail within a subsection. Keep the ledger only under
Thesis updates. Do not conceal content in HTML comments or code fences.

The following is a layout template; replace all illustrative values and prose:

```markdown
---
market_research: 1
date: 2026-09-08
as_of: "2026-09-08T11:30:00-04:00"
generated_at: "2026-09-08T11:46:00-04:00"
session: intraday
coverage: limited
---
# Market research — 2026-09-08

## Decision brief

No qualifying buying opportunity in the checked universe. State the important
change, cutoff, and limitation that affects today's buying assessment.

### Buying opportunities

No candidate meets the evidence and confirmation requirements. Replace this
with up to three concise buying candidates when supported.

### Next checks

State the next dated catalyst or observable condition that could qualify an idea.

## Research record

### Screening and sources

Record the checked universe, both discovery passes, dates, filters, sources,
coverage gaps, and relevant social-source findings or access limitations.

### Candidate assessments

Preserve the evidence, observations and concise rationale for shortlisted names,
including rejected candidates and what would justify revisiting them.

### Thesis updates

No active theses.

### Outcome review

No published ready ideas yet; no checkpoint observations are due. Check
monthly_review_due and complete the first monthly summary even when all counts
are zero.
```

The example date and statements are not an actual market assessment. Every
subsection must have content; use a truthful empty-state or coverage statement
instead of inventing candidates, observations, or results. On every run, including
the first, follow the helper's `monthly_review_due` result. A completed zero-record
review needs a short summary card and a `Monthly summaries` row under the
[outcome guide](outcomes-and-learning.md), not empty recommendation/checkpoint
tables. Incomplete reviews remain due. Otherwise Outcome review records the daily
due-check and relevant new records and links the latest monthly summary.

## Part 1: Decision brief

Aim for **200–350 words total**, fewer on quiet/closed days. State whether there
are qualified buying candidates or only ideas to watch. Show zero to three
leading ideas, with company and exchange:ticker, `watch`/`ready` state, why the
entry could be attractive, the confirmation condition, and the principal risk
or reason not to buy yet. Briefly mention a material deterioration in a previously
featured buying thesis; never turn it into an instruction to sell an assumed
holding. Finish with the next concrete checks.

Use an H4 heading for a candidate if useful, for example
`#### NASDAQ:EXAMPLE — Company name · watch`. Link its detailed assessment or
original thesis and retain primary citations beside material claims. Important
limitations must appear in the brief even when explained fully in the record.
Do not move the full ledger, screening tables, or outcome calculations here.
Include a learning finding only when it materially changes today's buying
assessment or a future research check.

The brief and record must agree on candidate identity, status, conditions,
observed values and risks. A `watch` is not presented as a confirmed purchase.
A `ready` means the research conditions for considering a new long position are
met; it does not imply portfolio suitability, a purchase, or guaranteed returns.
Current-holdings review, sell timing and rebalancing are outside this skill's scope.

## Part 2: Research record

Record enough information to resume and audit the work without reconstructing
it from the short brief. Organize each day's relevant material as follows:

- **Screening and sources:** persist the universe definition, source/provider,
  price-history period, liquidity/filter/ranking rules, coverage, candidate counts
  when known, and the announcement and price-screen results. Explain changes to
  the prior screen. For a thematic expansion, retain the theme, actual checked
  names, coverage and decisive exclusions. Preserve direct evidence URLs,
  publisher/author, publication and observation timestamps, and the facts
  supported. For social findings,
  identify the original claim, source/platform, deduplication and verification
  result; distinguish sampled conversations from representative measurements.
- **Candidate assessments:** group details under H4 exchange:ticker/thesis IDs.
  Retain the setup type, expected vs reported facts when verified, quarter-to-quarter
  changes, trend/benchmark observations, pricing assumptions, risks, confirmation,
  invalidation, milestone and review-by date. Record the leading rejected or
  deferred candidates with their decisive reason and reconsideration condition;
  do not preserve every irrelevant search hit. Separate verified observations,
  management claims, estimates, investment hypotheses and unresolved questions.
  Where relevant, retain the theme-to-company benefit and compact earnings
  comparisons from the [research method](research-method.md).
  Rejected names need not become tracked theses merely to appear in this record.
- **Thesis updates:** keep the canonical complete ledger below. Put fuller
  supporting changes under Candidate assessments, linked from the update cell.
- **Outcome review:** check daily for newly due and previously missing observations
  at two weeks and 1/3/6/12/24/60 months, retaining failed and closed theses. Record
  new observations, relevant provisional lessons, unresolved cases and the next known check; link
  unchanged earlier records instead of copying them. On the first completed run
  each month, consolidate the outcomes and lessons into a cumulative summary here;
  link the latest summary on other days. If nothing is eligible, say so truthfully.
  Use [Outcomes and learning](outcomes-and-learning.md) for record structure,
  evaluation conventions, corrections and retrieval; the two- and five-year
  observations do not extend the 3–12 month buying horizon.

Outcome review has three linked record types with stable IDs: the original buying
recommendation, checkpoint observations and lessons. Preserve the recommendation's
quoted reference price and timestamp separately from the fixed next-trading-date
regular-session opening used as its hypothetical evaluation baseline. The original
record also anchors the rationale, catalyst, confirmation, risks and benchmarks;
checkpoint records preserve dated inputs and results; lessons connect findings to
supporting and contrary cases, sample size, confidence and a specific future check.
Keep outcome and decision quality distinct, and label conclusions provisional when
evidence is limited or observations overlap. Daily runs use these records as
retrievable context, without rewriting old notes, retraining the model or editing
skill sources.

When there are records to journal, place the canonical tables under the H4 headings
`Recommendation records`, `Checkpoint records`, `Lesson records` and
`Monthly summaries` within Outcome review, using the syntax in that reference. Put detail
cards under separate H4 or deeper headings in the same subsection, with durable
links to and from their journal rows. Do not create empty tables merely to fill a
template. These headings do not change the note's two H2 and six H3 outline.

For claims that determine selection, status or risk, keep the source observation,
its date and verification or unresolved conflict beside the claim. Short visible
IDs such as `C1` can connect a claim, its evidence and later calculations within
the note; qualify cross-note references by filename and section. These labels
are ordinary body text, not new thesis or outcome IDs. Prose is sufficient when
clear; an extra table is not required, and historical notes need no conversion.

For decision-driving calculations, preserve the dated input values and their
sources or claim IDs, units, currency, formula or measurement definition, result,
cross-check and material limitations. Include periods, benchmark and adjustment
basis where relevant. Distinguish a quoted provider metric from a calculation
reproducible from retained data; a mutable URL alone does not preserve the data
as they appeared today. Retain only the observations needed to check the
conclusion, without copying entire paid datasets or copyrighted documents. Do not
invent unavailable historical observations to make a record look complete.

Published citations must not depend on the run's scratch files or other temporary
downloads. Use original durable URLs or existing stable vault sources. When the
only source is a user-supplied ephemeral packet, retain its relevant attributed
facts and source identifiers in the record and link to that section; do not invent
an original URL or leave a citation that breaks during scratch cleanup.

On later days, use filename-qualified links to specific earlier sections and
state what changed or was reverified. Preserve the initial rationale and material
new evidence locally in the relevant daily record; avoid copying the same
company background and unchanged evidence every day. Read linked earlier records
before relying on them. Today's omissions do not invalidate earlier evidence.

## Thesis continuity

Use this exact ledger only under `### Thesis updates`:

```markdown
| Thesis | State | Update / next check |
|---|---|---|
| NASDAQ:EXAMPLE@2026-09-08 | watch | New; confirmation pending. |
```

The thesis ID is `EXCHANGE:TICKER@YYYY-MM-DD`, with uppercase exchange/ticker
and the date first recorded. An ID first introduced in a new draft uses that
note's date; finding older source evidence does not backdate the thesis. Keep
published IDs unchanged, including earlier records whose ID date was inaccurate.
Verify the security and share class; do not merge
same-symbol instruments or treat a ticker change as a different economic identity
without checking. Keep the ID unchanged during that thesis. Use only these states:

- `watch`: a buying hypothesis worth monitoring; confirmation is absent or uncertain.
- `ready`: the stated buying confirmation is verified as of the cutoff, with no
  known triggered invalidation or material contrary evidence undermining it.
- `invalidated`: specified evidence contradicted the buying thesis; state why.
- `expired`: its catalyst, time window, or relevance passed; state why.

Carry every prior `watch`/`ready` ID into the next note, with a short change or
“unchanged; next check …”. With missing current evidence, say “not reverified”;
a prior ready thesis whose validity cannot be reverified returns to watch with
that explanation. Close ideas explicitly rather than dropping their rows. All
featured buying candidates must have matching ledger IDs/states and detailed
assessments. Once terminal, a materially different thesis gets a new ID linked to
the old one; do not revive an invalidated record or erase a failed prediction.
Invalidation/expiry qualifies future purchases, not sales of the user's holdings.

Link the first and most recent material analysis with qualified wikilinks such
as `[[Investments/2026-09-08-market-research#Candidate assessments]]`. Within table
cells use unpiped wikilinks and avoid literal `|` characters. The subsection
contains only its table or exact `No active theses.` sentence, with table rows
starting at column zero. Keep explanatory prose in Candidate assessments.

Keep the active list selective (about ten by default), but never omit an existing
thesis to meet a count target. Each new thesis records its expected opportunity,
next milestone, review-by date and any catalyst/thesis expiry in its initial
assessment. A watch's monitoring dates are distinct from its prospective buying
horizon.

At first readiness, state and justify a 3–12 month buying horizon and end date
from that readiness date using current evidence. Preserve the first-seen date,
earlier expectations and deadlines, and explain why the opportunity remains
prospective after time on watch. Routine confirmation may qualify the same ID;
it does not automatically extend catalyst or thesis expiry. If a fixed deadline
leaves no credible 3–12 month opportunity, keep the idea unready or expire it as
appropriate. A materially renewed rationale needs a new linked ID. Expire passed
thesis windows explicitly; revisit aging and invalidated ideas each week.

The day the last active idea closes must include its terminal row; the next day
may use `No active theses.`. Preserve prior terminal records for later outcome
reviews even when absent from today's active ledger. Evaluate each first-ready
thesis, including subsequent failures: create one original recommendation record
when it first becomes ready and reuse that recommendation ID for all checkpoint
observations. Follow the fixed next-trading-date opening convention in
[Outcomes and learning](outcomes-and-learning.md). Record future baselines or
horizons as pending until observed, never as actual fills or portfolio returns.
