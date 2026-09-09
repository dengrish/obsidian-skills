---
name: stock-research
description: Analyze investment ideas in feed-collect outputs for 3–12 month buying opportunities in liquid U.S.-listed stocks. Write a daily decision brief and research record, maintain one note per analyzed stock, and track earlier theses. Does not collect feeds, review holdings, recommend sales, or execute trades.
---

# Stock research

Find a small number of evidence-backed **long-only buying opportunities** and
explain what would justify considering a purchase, waiting for confirmation, or
rejecting the idea. Cover positive earnings/guidance momentum, earnings
overreactions, catalysts that could reverse a downtrend, and continued recovery
or consolidation without a new announcement. **No qualifying buying opportunity**
is a useful result. A thesis becoming invalid is a change to its buying rationale,
not a recommendation to sell an assumed holding. Do not review the user's current
portfolio, recommend sales or rebalancing, or place trades; those are separate tasks.

The user runs `feed-collect`, then this skill. Read its saved account notes and
collection receipts; do not invoke collection, call X or ShadowAlpha, or broaden
the idea source independently. Continue earlier theses even when their accounts
are no longer followed. An explicitly user-named stock is a labeled override,
not permission to add other stocks.

Read [runtime setup](../../shared/RUNTIME.md) and
[input safety](../../shared/INPUT_SAFETY.md).
Resolve the selected vault and this skill's actual directory. Follow the
[research method](references/research-method.md) when screening and the
[note format](references/note-format.md) when reading or writing daily records.
Use [stock note maintenance](references/stock-notes.md) for the continuously
updated notes in `Investments/Stocks/`. Use
[coverage and work scheduling](references/coverage.md) on every run: assess every
eligible new substantive idea, account for every active thesis, and carry unfinished
work without confusing research status with investment conclusions. Use
[outcomes and learning](references/outcomes-and-learning.md) for the daily checkpoint inventory, recommendation records and evidence-based lesson updates.
Investment notes have their own schema; do not apply Wiki/source-note fields,
flashcards, MOCs, or automatic source-document extraction to them.

## Establish the review window

The intended daily run starts at **08:30 America/Los_Angeles**, equivalent to
**11:30 America/New_York**, observing daylight saving time. On a normal trading
day this is an intraday review, with morning price action available to assess.
Installing or manually invoking this skill does not schedule it. A host scheduler
must separately invoke it with the selected vault and available research tools;
create or change that schedule only when the user requests scheduling.

For a scheduled retry, inspect `context` first and reuse a valid existing edition
under the rules below. For a **fresh scheduled or manual** run, first identify
the candidates justified by prior watch/deferred notes, the user's request or
already-collected feed posts. Resolve quoted securities and use the
[targeted acquisition coordinator](references/targeted-acquisition.md) for needed
raw prices and justified estimate periods. It batches this explicit plan, reuses
archives, and shares a bounded request budget. Other thesis-specific checks use
the data-access guide; the coordinator does not research the stocks for you.
This planning pass does not collect feeds, discover unrelated stocks or establish
the final nomination set. Recheck the inputs at the frozen cutoff. Acquisition
bounds are not research quotas: retain every uncompleted item and its limitation
under the coverage rules, without silently raising the request budget.

Then use `prepare` to create the canonical draft and a private run receipt in
owned scratch:

```bash
python3 '<skill>/scripts/market_notes.py' prepare --vault '<vault>' --mode manual --work-dir '<scratch>' --check independent-review
```

Use `--mode scheduled` for the scheduled task. Both modes freeze the actual
whole-second preparation time after acquisition has returned; 08:30 Pacific is
the intended start, not a fixed evidence cutoff. The independent-review declaration
is appropriate when a checker will actually be launched; omit it when delegation
is unavailable. `final-review` is always declared. Use the returned receipt with
`context`, `outcomes` and publication via `--run-receipt '<run>/run.json'`; it fixes
the evidence cutoff, mode and filename for up to eight elapsed hours, including
across New York midnight. It does not permit retrospective backfill. Register a
later checker with `review-start` when launching it; every declared check must
finish against the final draft before publication. Details and retries are in
[edition naming and run receipts](references/note-format.md#editions-and-retries).

Never move an already frozen cutoff to admit a late capture. New candidates
discovered later may contribute late price or estimate snapshots only to future
editions. A capture made after preparation cannot supply earlier evidence, even
if its bar describes an earlier trading interval. Use an eligible archive or
retain the limitation. Existing run receipts and published editions keep the
cutoff they originally recorded.

Record the actual preparation cutoff and generation time separately. Read news
since the previous completed
review's cutoff, including intervening after-hours releases and still-relevant
unreviewed windows recorded under the research method's coverage rules. On the
first run, cover the previous regular-session close through the cutoff, using older
material only as identified background. A late scheduled start uses its actual
preparation time and session label; it does not pretend to be the morning review.
Do not admit later prices or news into any frozen edition.

Verify the exchange calendar and actual session, including exceptional closures;
never derive holidays from weekdays alone. Run every calendar day when daily
execution is requested. On a closed-market day, write a short follow-up with the
last completed session and next scheduled session; do not present stale prices
as current trading. A scheduled run before 11:30 New York time uses the helper's
actual preparation cutoff and is described as an early edition.

If the selected edition already exists, read it and run the outcome inventory
below before reusing it. Context's `thesis_history` and `active_theses` describe
earlier editions available by the cutoff, including the same date; the selected
edition's states are in its existing note. The `valid` marker checks note structure, not
cross-note journal consistency; history and cross-note journals must validate.
Pending or unavailable market observations remain valid limitations.
A successful routine retry returns the existing note without rewriting that
edition's judgments, creating a numbered duplicate, or starting a second market run.
Report malformed history, inconsistent journals or an unsafe occupant instead of
replacing files. A fresh manual review is a new edition, not a retry; preserve
all earlier notes and carry forward their evidence and theses.

## Recover the prior theses

Use the context's chronological history and active thesis records. Read the most
recent completed note, then the detailed research records in the first and latest
note for each active thesis and intervening relevant updates before changing its
status. Reuse recorded screen definitions, dated observations and pending checks;
the short briefs alone are not sufficient research memory. Search earlier notes
for each proposed ticker, including invalidated ideas; do not research only past
winners. Read the existing stock note through `stock_dossiers.py context --vault '<vault>'
--ticker '<ticker>' --as-of '<cutoff>'` as a navigation aid. Its latest assessment
is usable only when available by this cutoff; follow its dated report links for
earlier context. Inspect the helper's history findings separately: a verified
current assessment does not establish that every older linked report is intact.
Use a verified preserved original when supplied; never adopt altered legacy
bytes, silently rewrite their fingerprints or treat a successful update as
history reconciliation. The daily history and outcome journals remain authoritative.
Inspect relevant existing user market notes listed outside the recognized
naming pattern as read-only background and identify gaps in their history.

Recover the [structured coverage history](references/coverage.md) as well as the
thesis ledger. A stock note's existence does not schedule daily full research.
Active ideas receive dated monitoring; material changes and due reviews trigger
substantive reassessment. Closed ideas return only on new substantive evidence or
their recorded reconsideration condition. Never infer an empty backlog from older
reports that lack structured coverage; inspect and explicitly account for that
legacy research before establishing the new journal.

The helper reports malformed or unreadable recognized history explicitly. Do not
treat incomplete history as an empty watchlist. Preserve files, report the exact
blocker, and retain a completed draft if publication cannot safely proceed.
Carry every open thesis into the new tracking table, even if unchanged or data
are unavailable. Close an idea explicitly with a reason rather than dropping it
from memory. Earlier notes are dated evidence, not text to revise retrospectively.

Run the outcome inventory before researching new candidates:

```bash
python3 '<skill>/scripts/market_notes.py' outcomes --vault '<vault>' --run-receipt '<run>/run.json'
```

Read its active lesson records and latest monthly summary, including supporting
and contrary examples relevant to today's candidates. These notes carry learning
across runs; a model's recollection is not the historical record. Save large helper
output in owned scratch and inspect the relevant IDs/paths rather than treating
truncated output as complete history. Resolve malformed/conflicting tracking
records before relying on the inventory; do not silently start a new track record.

## Research and rank

Read the [feed intake and screening guide](references/screening.md) and take a
read-only snapshot at the run's frozen cutoff:

```bash
python3 '<skill>/scripts/stock_feed.py' context --vault '<vault>' --cutoff '<cutoff>' > '<scratch>/feed-context.json'
```

The default window is the preceding 72 hours. When earlier research identifies
unreviewed saved posts, pass an earlier `--since` to recover that window and label
late discovery. This reads local material only; it does not spend X API calls,
collect missing posts, or alter the account roster or collection state. Read its
coverage diagnostics before interpreting the posts. Missing, stale, partial,
changed or unpublished account output is a limitation, not a clean empty result.

Run the offline coverage planner at the same cutoff:

```bash
python3 '<skill>/scripts/stock_coverage.py' context --vault '<vault>' --as-of '<cutoff>' --mode '<mode>' > '<scratch>/coverage-context.json'
```

Use its pending sources, prior queue, due work and processed fingerprints to avoid
restarting unchanged work. Preserve an older intake window when it identifies
unreviewed saved posts. Read the source text before classifying it; the planner
does not decide which posts contain investment arguments. Use this edition's
actual `manual` or `scheduled` mode in coverage commands.

Triage substantive stock ideas from the eligible posts, preserving source links,
authors, timestamps and disposition. Verify company/share-class identity rather
than treating every cashtag as a valid nomination. Distinguish the collector
account's own view from a quoted or reposted author's claim; repeated copies are
one originating piece of evidence. Carry prior open theses separately. Reuse
previously assessed posts by link; a new run need not re-research unchanged claims.

Use this nominated set for targeted announcement, business, price and risk checks.
Give every eligible new stock a [standard initial assessment](references/research-method.md#standard-initial-assessment-and-readiness).
Prioritize urgent active checks and older unfinished work, but do not arbitrarily
select a few new names and describe the remainder as covered. Repeated arguments
reuse earlier work; new material arguments prompt focused reassessment. Capacity
deferrals remain queued for the next run, while evidence blockers name the missing
fact and a dated retry or reconsideration condition.
Default to liquid U.S.-listed common stocks and ADRs, identifying exchange,
company, share class and currency. Exclude OTC/penny stocks, leveraged products,
options and short-sale strategies unless the user changes the scope. This is a
selective feed-based review, never a complete market scan. Do not fetch a broad
universe, independently nominate names from news/social search, or add unmentioned
thematic beneficiaries. Competitor and industry evidence can test a nominated
stock's thesis without turning those companies into new candidates.

Follow the bundled [data-access guide and retrieval plan](references/data-access.md#retrieval-plan)
to assign configured sources to the session, universe, announcement, price,
shortlist, corporate-action, macro and outcome checks. Check local setup without
network access first. When the user or task specifies a credentials file, pass
its path to the bundled `market_data.py` with `--credentials-file` for both checks
and retrieval; otherwise use the configured environment. Keep secret values
outside the conversation and plugin. Use the relevant commands; do not run
every endpoint merely to exercise a script. Preserve coverage, cutoffs,
partial-result warnings and material skipped/unavailable checks. Missing keys
limit only the affected source. Retrieval helpers supply evidence; the offline
screener calculates declared measurements and filters, while interpretation and
final selection still follow the research method. Optional filing extraction
must use an exact verified accession, never an implicit latest filing.
Complete the shortlist's [dated capitalization check](references/capitalization.md)
using an existing sourced cap or a labeled estimate from verified outstanding
shares and a matching raw price. Select cutoff-eligible archived price evidence
through the bundled capture helper; retain its observation time, availability
and evidence link rather than constructing an earlier availability timestamp.
Missing provider market-cap fields do not require abandoning this check;
ambiguous share bases remain unresolved.

For a shortlist whose expectations matter, read eligible archived estimates and
capture relevant current periods under the data-access guide's
[dated-snapshot workflow](references/data-access.md#dated-estimates-not-reconstructed-expectations).
New observations saved after the cutoff are evidence for later reviews only;
they never change the current edition's conclusions. Use exact Form 4/4-A
accessions selectively when insider-disclosure context changes the buying case.

Use available host web search, page-reading, and market-data capabilities for
primary-source verification and coverage beyond the helpers. No paid feed or
particular connector is assumed, and this skill does not install,
subscribe, log in, or bypass access restrictions. Open supporting pages; search
snippets and model recollection are leads, not verified financial evidence.
When reliable market data are unavailable, label coverage limited/unavailable,
retain prior theses with uncertainty, and avoid actionable rankings or invented
price levels. A tool failure is not evidence that nothing happened.

Use the collected posts as leads and arguments, not financial verification.
Targeted web research supplies primary evidence and material counterarguments for
the nominated stocks. Popularity, author confidence, claimed returns and repeated
mentions never substitute for a buying case. No additional social-monitoring pass
is required; unavailable source text or attachments stay explicit limitations.

Apply the relevant setup-specific evidence tests in the research method. Prefer
**zero to three leading buying ideas**, ranked by the quality of the catalyst, price
confirmation, downside/invalidation evidence, and fit to the 3–12 month horizon.
Treat these as judgments, not fabricated probabilities or a guaranteed edge.
Explain why the leading choices merit attention relative to the other assessed
ideas, including shared risks; use the research method's comparison criteria.
For each selected idea, provide:

- What changed: for news-driven setups, the actual announcement date/time and
  primary source; without a new catalyst, the dated price development and latest
  relevant business evidence.
- Why it could matter over the holding horizon, what the price may already assume,
  and the strongest counterargument. Compare relevant operating evidence with
  earlier quarters and corroborating industry evidence when available.
- Verified completed-session trend evidence and a separate timestamped intraday
  or premarket snapshot; distinguish facts from the overreaction/reversal hypothesis.
- An observable confirmation condition, invalidation condition, next milestone,
  and prospective 3–12 month buying window when first marked ready. Follow the
  research method's aging rules, preserving original watch dates and deadlines.

A premarket or intraday move cannot establish a confirmed closing breakout or
full-session volume signal. Do not assume an order will fill at the quoted price
or mark a hypothetical idea as a purchase.
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

Use the outcome helper's `nominee_comparison` inventory and
[prospective nominee comparison](references/nominee-comparison.md) to evaluate
the original idea pool, including watch, rejected and unfinished ideas. Initial
groups remain frozen; later decisions are separate observations. Review due
2-week and 1/3/6/12-month windows using matched sessions and benchmarks, retain
missing members, and include sample sizes and limitations in monthly learning.
Preparation activates this diagnostic prospectively; it never backfills older
reports as new experiments. Continue due 3/6/12-month windows for existing
[independent momentum cohorts](references/comparison-strategy.md), but do not
form new ones by default or substitute feed nominees for their old universe.
Neither comparison establishes skill outperformance or recommends a portfolio.

## Write and publish

Follow the note format's two parts. The **Decision brief** is for the user:
lead with the buying conclusion and what changed, present zero to three candidates
with their conditions and key risks, then the next checks. Aim for 200–350 words,
fewer on a quiet/closed day; do not hide material uncertainty to meet that default.
The **Research record** is durable evidence for future runs and can be much longer.
Retain relevant sources and observation times, feed coverage and nomination
dispositions, candidate and rejection rationales, calculations, verified source
claims, thesis continuity and outcome reviews. Keep the complete tracking table
here, not in the short brief. Every substantive
stock assessment must use the note format's exact H4/Status structure and link its
`Investments/Stocks/<TICKER>` note, including watch or rejected ideas. This section
will supply that stock note's latest assessment after daily publication.

Preserve decision-relevant detail without padding, copying full articles, dumping
entire feeds, or duplicating unchanged history. Link specific earlier records and
state today's changes. Charts belong where they clarify verified evidence, usually
in the record. Keep conclusions, citations and journal cards visible in ordinary
Markdown. Link preserved estimate snapshots and their availability receipts from
the record and summarize the relevant values; those source observations remain
immutable JSON files. Use the helper's verified availability when applying a cutoff.

Finish the draft in owned scratch, with the actual completion time, then stamp
its verified installed-plugin identity under [note provenance](../../shared/PROVENANCE.md).
Use `--vault` when forming/evaluating comparison cards: their bulky calendars,
source metadata and full rosters belong in immutable digest-verified attachments,
with a concise visible summary in the note. Preserve historical inline records.
Here `<plugin>` means this skill's installed root, never the development checkout.

```bash
python3 '<plugin>/shared/scripts/note_provenance.py' stamp --plugin '<plugin>' --skill stock-research --draft '<run>/draft.md' --output '<run>/daily-stamped.md'
python3 '<skill>/scripts/market_notes.py' lint '<run>/daily-stamped.md'
python3 '<skill>/scripts/market_notes.py' outcomes --vault '<vault>' --draft '<run>/daily-stamped.md' --run-receipt '<run>/run.json'
```

Each new edition must identify this bundle as its creator. Never use `--previous`
for a new edition or relabel an unchanged historical note. The metadata footer
remains separate from financial evidence.

Before publication, audit the claims that determine selection, readiness or risk
against their retained evidence and calculations. Check citations, timestamps,
quote sessions/delays, arithmetic, setup counterarguments and continuity against
the previous active theses. Where available, use a bounded independent checker
with the draft, cutoff and original evidence in a fresh context; ask for supported,
contradicted, unsupported or stale findings and recomputation of decisive values.
If delegation is unavailable, perform a fresh evidence-first check yourself.
Wait for every checker that was launched; a time limit or midnight is not a
reason to publish while it is still running. Another model's agreement is not
source verification. Correct unsupported claims
or downgrade the buying conclusion, then recheck the revised assessment; do not merely append a warning
while leaving the same unsupported recommendation. Verify every brief
candidate's state, conditions and risks agree with its
detailed assessment and ledger, and that the brief makes no current-holdings or
sell recommendation. The helper validates structure and preserves occupied files;
it cannot establish factual accuracy or an investment edge. No mandatory human
review is required to publish the research note. Follow [safe writes](../../shared/SAFE_WRITES.md),
preserve reported recovery stages on failure, and read back the published note.
Ensure its citations and retained evidence remain usable after owned scratch is
cleaned; no published reference should point to a run's temporary files.

Complete the visible [coverage journals](references/coverage.md) in the Research
record and check them against the saved feeds and prior editions:

```bash
python3 '<skill>/scripts/stock_coverage.py' check --vault '<vault>' --as-of '<cutoff>' --mode '<mode>' --draft '<run>/daily-stamped.md'
```

Distinguish valid accounting from completed research. A report may truthfully
publish queued or blocked work, but must identify that limitation and its next
steps; it cannot label unperformed research complete. The publisher repeats this
check and refuses lost backlog, missing dispositions and invalid reuse links.

Only after the checks above have finished and any findings are resolved, record
their completion for the **exact stamped draft**, then publish it. For example,
a run that declared an independent checker completes both checks:

```bash
python3 '<skill>/scripts/market_notes.py' review-complete --vault '<vault>' --run-receipt '<run>/run.json' --draft '<run>/daily-stamped.md' --check independent-review
python3 '<skill>/scripts/market_notes.py' review-complete --vault '<vault>' --run-receipt '<run>/run.json' --draft '<run>/daily-stamped.md' --check final-review
python3 '<skill>/scripts/market_notes.py' publish '<run>/daily-stamped.md' --vault '<vault>' --run-receipt '<run>/run.json'
```

A receipt records completed declared checks, not proof of factual truth. Any edit
to the draft, completion time or provenance requires restamping/revalidation and
fresh completion records for the revised bytes. Repeated independent launches
need distinct check names. Do not clear a pending checker to bypass the gate.

At closeout, including a successful same-day retry, maintain
`Reviews/stock-research-suggestions.md` under the
[shared suggestion-log rules](../../shared/SUGGESTIONS.md). On apply-capable
runs, create it if missing; retain the standard empty state when there are no
open issues. Record evidenced workflow defects, keeping investment ideas and
outcome learning in the daily notes.

After daily publication, update the [stock notes](references/stock-notes.md) for
every stock substantively assessed today, including rejected and deferred ideas:

```bash
python3 '<skill>/scripts/stock_dossiers.py' sync --vault '<vault>' --daily-note '<published-daily-note>' --work-dir '<scratch>'
```

The daily report retains the dated evidence and outcome journals; a stock note
summarizes its latest available assessment and links its history. Preserve earlier
daily notes and never use a later dossier state to reconstruct an earlier judgment.
Report incomplete dossier publication separately and resume it without creating
another daily edition. After publication, freeze all new nominee and decision
observations from the published reports:

```bash
python3 '<skill>/scripts/stock_cohorts.py' form --vault '<vault>'
```

The helper chooses the complete eligible pool; never pass a handpicked subset.
Its immutable evidence and timing summary belong in the next report's Outcome
review, since the just-published report cannot be edited. Include enrollment
counts or a failure in this run's closeout. On a scheduled retry, recover missing
enrollment as well as dossier updates before treating the run as unchanged.
If the strategy has not been activated, start it for future reports only; report
the missed prospective window without backfilling it. Do not claim the run
complete until these updates succeed or their exact remaining blockers are identified.

Clean owned scratch that is no longer needed, and return the daily note link,
created/updated stock notes, the main conclusion and any material limitation.
A scheduler should notify on a new completed daily note, a material thesis change, or a blocked run; an unchanged
same-day retry should stay quiet. Do not modify plugin sources during a research run.
