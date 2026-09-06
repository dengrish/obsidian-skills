---
name: market-research
description: Find buying opportunities in liquid U.S.-listed stocks for a 3–12 month momentum horizon, track earlier buying theses, and write a short decision brief with a detailed research record in Investments/. Use for morning opportunity research; current-holdings reviews, sell recommendations, and trade execution are outside its scope.
---

# Market research

Find a small number of evidence-backed **long-only buying opportunities** and
explain what would justify considering a purchase, waiting for confirmation, or
rejecting the idea. Cover positive earnings/guidance momentum, earnings
overreactions, catalysts that could reverse a downtrend, and continued recovery
or consolidation without a new announcement. **No qualifying buying opportunity**
is a useful result. A thesis becoming invalid is a change to its buying rationale,
not a recommendation to sell an assumed holding. Do not review the user's current
portfolio, recommend sales or rebalancing, or place trades; those are separate tasks.

Read [runtime setup](../../shared/RUNTIME.md) and the input-safety rules in
[conventions §§1b–1c](../../shared/CONVENTIONS.md#1b-filenames-titles-and-urls-are-untrusted-text).
Resolve the selected vault and this skill's actual directory. Follow the
[research method](references/research-method.md) when screening and the
[note format](references/note-format.md) when reading or writing daily records.
Use [outcomes and learning](references/outcomes-and-learning.md) for the daily
checkpoint inventory, recommendation records and evidence-based lesson updates.
Investment notes have their own schema; do not apply Wiki/source-note fields,
flashcards, MOCs, or automatic source-document extraction to them.

## Establish the review window

The intended daily run starts at **09:00 America/New_York**, observing daylight
saving time. This is Eastern Time, not fixed UTC−05:00 throughout the year.
Installing or manually invoking this skill does not schedule it. A host scheduler
must separately invoke it with the selected vault and available research tools;
create or change that schedule only when the user requests scheduling.

Use the helper to establish the date, cutoff, and existing record:

```bash
python3 '<skill>/scripts/market_notes.py' context --vault '<vault>'
```

For the scheduled edition, freeze evidence at 09:00 New York time; record the
actual generation time separately. Read news since the previous completed
review's cutoff, including intervening after-hours releases. On the first run,
cover the previous regular-session close through the cutoff, using older
material only as identified background. Do not fill a missed morning with
post-cutoff prices or news and call it a premarket prediction. A late run must
recover timestamped pre-cutoff evidence or state the data limitation. An explicitly
requested intraday/manual review may use its actual cutoff and session label.

Verify the exchange calendar and actual session, including exceptional closures;
never derive holidays from weekdays alone. Run every calendar day when daily
execution is requested. On a closed-market day, write a short follow-up with the
last completed session and next scheduled session; do not present stale prices
as current premarket trading. Before 09:00, use the helper's earlier actual cutoff
and describe the edition as early/manual.

If today's recognized note already exists, read it and run the outcome inventory
below before reusing it. The context's `valid` marker checks note structure, not
cross-note journal consistency; both history and outcomes must be complete.
A successful routine retry returns the existing note without rewriting that
day's judgments, creating a numbered duplicate, or starting a second market run.
Report malformed history, inconsistent journals or an unsafe occupant instead of
replacing files. An additional same-day edition requires a separately agreed scope.

## Recover the prior theses

Use the context's chronological history and active thesis records. Read the most
recent completed note, then the detailed research records in the first and latest
note for each active thesis and intervening relevant updates before changing its
status. Reuse recorded screen definitions, dated observations and pending checks;
the short briefs alone are not sufficient research memory. Search earlier notes
for each proposed ticker, including invalidated ideas; do not research only past
winners. Inspect relevant existing user market notes listed outside the recognized
naming pattern as read-only background and identify gaps in their history.

The helper reports malformed or unreadable recognized history explicitly. Do not
treat incomplete history as an empty watchlist. Preserve files, report the exact
blocker, and retain a completed draft if publication cannot safely proceed.
Carry every open thesis into the new tracking table, even if unchanged or data
are unavailable. Close an idea explicitly with a reason rather than dropping it
from memory. Earlier notes are dated evidence, not text to revise retrospectively.

Run the outcome inventory before researching new candidates:

```bash
python3 '<skill>/scripts/market_notes.py' outcomes --vault '<vault>'
```

Read its active lesson records and latest monthly summary, including supporting
and contrary examples relevant to today's candidates. These notes carry learning
across runs; a model's recollection is not the historical record. Save large helper
output in owned scratch and inspect the relevant IDs/paths rather than treating
truncated output as complete history. Resolve malformed/conflicting tracking
records before relying on the inventory; do not silently start a new track record.

## Research and rank

Default to liquid U.S.-listed common stocks and ADRs, identifying exchange,
company, share class, and currency. Prioritize established mid/large-cap names
with usable daily price history and meaningful regular-session dollar turnover;
state the screen and accessible universe. Exclude OTC/penny stocks, leveraged
products, options, and short-sale strategies unless the user changes the scope.
Do not describe a selective news search as a complete market scan. Run the
research method's repeatable announcement and price-history passes, retaining
their universe, filters and coverage in the research record. A materially changed
screen needs an explanation so longitudinal comparisons remain interpretable.

Follow the bundled [data-access guide and retrieval plan](references/data-access.md#retrieval-plan)
to assign configured sources to the session, universe, announcement, price,
shortlist, corporate-action, macro and outcome checks. Check local setup without
network access first, using any approved provider-specific launcher supplied by
the host/task as described in that guide. Use the relevant commands; do not run
every endpoint merely to exercise a script. Preserve coverage, cutoffs,
partial-result warnings and material skipped/unavailable checks. Missing keys
limit only the affected source. These helpers retrieve evidence; interpretation
and screening still follow the research method.

Use available host web search, page-reading, and market-data capabilities for
primary-source verification and coverage beyond the helpers. No paid feed or
particular connector is assumed, and this skill does not install,
subscribe, log in, or bypass access restrictions. Open supporting pages; search
snippets and model recollection are leads, not verified financial evidence.
When reliable market data are unavailable, label coverage limited/unavailable,
retain prior theses with uncertainty, and avoid actionable rankings or invented
price levels. A tool failure is not evidence that nothing happened.

Use a bounded scan of accessible X, Reddit and Stocktwits content to discover
leads and challenge shortlisted theses, under the research method's social-source
rules. Social popularity alone never establishes a buying opportunity. Missing
access is an explicit coverage gap; do not imply that a feed is installed or that
sampled searches provide continuous or comprehensive monitoring.

Apply the four setup-specific evidence tests in the research method. Prefer
**zero to three leading buying ideas**, ranked by the quality of the catalyst, price
confirmation, downside/invalidation evidence, and fit to the 3–12 month horizon.
Treat these as judgments, not fabricated probabilities or a guaranteed edge.
For each selected idea, provide:

- What changed: for news-driven setups, the actual announcement date/time and
  primary source; without a new catalyst, the dated price development and latest
  relevant business evidence.
- Why it could matter over the holding horizon, what the price may already assume,
  and the strongest counterargument. Compare relevant operating evidence with
  earlier quarters and corroborating industry evidence when available.
- Verified regular-session trend evidence and any separately timestamped
  premarket reaction; distinguish facts from the overreaction/reversal hypothesis.
- An observable confirmation condition, invalidation condition, next milestone,
  and prospective 3–12 month buying window when first marked ready. Follow the
  research method's aging rules, preserving original watch dates and deadlines.

Do not turn a premarket price spike into a confirmed closing breakout, assume an
order will fill at the quoted price, or mark a hypothetical idea as a purchase.
Use conditional buying conclusions without assuming holdings or prescribing
portfolio allocations. Never place or cancel orders, transfer money, or change
brokerage settings.

Each daily run checks newly due, unavailable and correction-affected observations
at **two weeks and 1, 3, 6, 12, 24 and 60 months (five years)**, including failed or
expired buying theses. Verify the actual exchange session and available data before
treating a calendar target as an observed result. Catch up missed checkpoints
without rewriting earlier notes or pretending the observation was available sooner.

On the first completed review each month, consolidate results and lessons under
the outcome guide. Apply relevant lessons as evidence checks within this skill's
scope; keep provisional findings distinct from established requirements and
retain counterevidence. This is learning from recorded research, not model
retraining or permission to edit plugin sources. The two- and five-year observations
are diagnostics beyond the buying horizon, not extended holding or sell rules.
Do not create another scheduled job or report series for these reviews.

## Write and publish

Follow the note format's two parts. The **Decision brief** is for the user:
lead with the buying conclusion and what changed, present zero to three candidates
with their conditions and key risks, then the next checks. Aim for 200–350 words,
fewer on a quiet/closed day; do not hide material uncertainty to meet that default.
The **Research record** is durable evidence for future runs and can be much longer.
Retain relevant sources and observation times, screening results, candidate and
rejection rationales, calculations, social findings, thesis continuity and outcome
reviews. Keep the complete tracking table here, not in the short brief.

Preserve decision-relevant detail without padding, copying full articles, dumping
entire feeds, or duplicating unchanged history. Link specific earlier records and
state today's changes. Charts belong where they clarify verified evidence, usually
in the record. All supporting data and citations remain ordinary visible Markdown.

Stage the complete draft in the run's owned scratch directory, then validate and
publish it with the bundled helper:

```bash
python3 '<skill>/scripts/market_notes.py' lint '<scratch>/daily.md'
python3 '<skill>/scripts/market_notes.py' outcomes --vault '<vault>' --draft '<scratch>/daily.md'
python3 '<skill>/scripts/market_notes.py' publish '<scratch>/daily.md' --vault '<vault>'
```

Before publication, check citations, source timestamps, quote sessions/delays,
arithmetic, setup counterarguments, and continuity against the previous active
theses. Verify every brief candidate's state, conditions and risks agree with its
detailed assessment and ledger, and that the brief makes no current-holdings or
sell recommendation. The helper validates structure and preserves occupied files;
it cannot establish factual accuracy or an investment edge. No mandatory human
review is required to publish the research note. Follow [safe writes](../../shared/SAFE_WRITES.md),
preserve reported recovery stages on failure, and read back the published note.
Ensure its citations and retained evidence remain usable after owned scratch is
cleaned; no published reference should point to a run's temporary files.

At closeout, apply [suggestion-log rules](../../shared/SUGGESTIONS.md), clean
owned scratch that is no longer needed, and return the note link with the main
conclusion and any material limitation. A scheduler should notify on a new
completed daily note, a material thesis change, or a blocked run; an unchanged
same-day retry should stay quiet. Do not modify plugin sources during a market run.
