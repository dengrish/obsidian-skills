# Outcomes and learning

Use this guide during every daily run. Track the first time a buying thesis is
published as `ready`, preserve its original evidence, and evaluate fixed future
windows. Later `watch`, invalidated or expired states do not erase that record or
restart its clock. Never-ready watches remain a separate group. A new thesis in
the same stock needs a new linked ID; related recommendations and overlapping
windows are not independent evidence of skill.

The resulting learning is stored in dated notes and retrieved by later runs.
It does not retrain a model, authorize plugin edits, evaluate current holdings,
or generate sales. The **24- and 60-month (two- and five-year)** observations are
diagnostic; the buying thesis still has its independently chosen **3–12 month**
horizon. Use these longer windows to assess the durability of the business
improvement, distinguishing later developments from the original momentum thesis.

## Daily observations and monthly synthesis

Run `market_notes.py outcomes --vault '<vault>'` to rebuild the recommendation,
checkpoint and lesson index from published daily notes. No separate database or
mutable tracking file is authoritative. The helper returns recommendation origins,
calendar targets, due/unavailable/correction-affected checkpoints, active and
retired lesson links, the latest monthly summary, and whether a summary is due.
It validates record relationships and timestamps; it does not fetch prices or
establish market-calendar accuracy, causal explanations or investment merit.

Process `due_baselines` before `due_checkpoints`, fetching a pending/unavailable
baseline once per recommendation rather than once per horizon. A baseline task
only means its earliest possible date has passed; verify whether the actual
opening occurred and keep it pending when a closure or future session prevents it.

Read the most recent note and the returned active lessons/latest summary before
new analysis. Follow their original evidence and contrary cases where relevant;
a condensed summary alone is not proof. Reuse completed observations by link,
then collect newly mature or unresolved windows. A missed run does not remove a
due checkpoint. On data failure, record it as unavailable, state the reason and
next check, and retry later. Do not invent a value, substitute today's price for
an earlier endpoint, or turn an inaccessible record into an empty history.

On the first completed review each month, write a cumulative learning summary in
that day's Research record and register its link. Include counts of recommendations,
never-ready watches, observed/pending/unavailable/recheck windows, and the relevant
per-horizon sample sizes. Group comparable setups and distinguish company-specific
results from broad market/sector moves. A count of zero is a valid first summary.
If the review cannot be completed, leave it due and record the limitation rather
than registering a completed summary. The ordinary daily run retries it.

The summary links the current lessons and their evidence, explains changes since
the last summary, and identifies unresolved questions. Each subsequent daily
Outcome review links the latest summary and records only new events or material
changes. Full details remain in their original notes; do not copy the entire
history into every daily note. Only decision-relevant learning belongs in the
short Decision brief.

## Freeze the recommendation and price convention

When an ID first becomes `ready`, create its recommendation record and a detail
card under Outcome review, linked to the original Candidate assessments. Preserve:

- **Identity and origin:** thesis ID, company/share class/currency, first-ready
  note/date, setup type and original rationale. Retain earlier watch milestones
  and expiry dates separately from the prospective buying horizon and end date
  justified at first readiness under the note format's thesis-continuity rules.
- **Reference quote:** the price quoted in the recommendation, its source,
  timestamp, timezone, session, delay and adjustment basis. Record unavailable
  data explicitly. This quote is not an actual fill or the evaluation baseline.
- **Decision evidence:** confirmation actually observed, expected catalyst and
  milestone, risks, counterarguments and conditions that would invalidate it.
- **Evaluation convention:** stable convention ID, return/adjustment method,
  named broad-market and relevant sector benchmark instruments, and cost treatment.
  Choose these before observing outcomes; the first ready record defines them.
- **Baseline:** initially pending, then the sourced stock/benchmark opening
  values, session date and timestamp basis when available, with a link to the
  original record.

Use the **regular-session opening on the first trading date after the first-ready
note's New York date**, and only after known publication, as the hypothetical
baseline. Verify that session against the exchange calendar, including closures.
Do not treat a past premarket indication or same-day opening as a feasible
purchase after publication. Never switch to a more favorable price after seeing
results. If publication timing is uncertain, leave the baseline unavailable until
established.

A later daily note records the baseline only after the opening has occurred and
its data were available by that note's cutoff. Use the provider's documented
regular-session daily open/close fields consistently, identifying whether these
are daily bar values or official auction prices. `Baseline at` and `Observed at`
use sourced event timestamps when available. For date-only daily bars, use the
verified exchange session's opening/closing boundary as a **session marker**, and
label its basis and precision in the detail card. A calendar marker is not an
observed trade time: [NYSE openings can occur after 09:30](https://www.nyse.com/trade/auctions).
Retain the bar's date, field definition and evidence of availability by the cutoff;
a missing bar or unverified session marker stays unavailable. Never substitute a
later convenient session for the fixed baseline or endpoint.

Retain the observed quote and hypothetical baseline separately; neither asserts
that the user bought the stock. Freeze the baseline event, original raw opening
values and their provenance. Later corporate actions can require sourced
adjustments for a checkpoint calculation; they do not make those original
observations wrong or restart the baseline clock. Correct factual errors through
the correction journal below.

## Checkpoint timing, returns and decision quality

Evaluate **two weeks and 1, 3, 6, 12, 24 and 60 calendar months** from the actual
baseline's New York date. Two weeks means **14 calendar days**, not a fractional
month or ten trading sessions. For monthly horizons, clamp the day to the last day
of a shorter month. For every horizon, use the close of the first regular session
on or after that calendar target. Verify the session and its closing boundary,
including early closes and exceptional closures. The helper's calendar target is
only a research due date; it cannot establish that a trading session occurred.
An outcome becomes observable only after that close and by a later review's cutoff.
At the scheduled 11:30 ET review, today's close is normally still pending.
Only a verified earlier session close with data available by the cutoff can
already support that day's checkpoint; an intraday snapshot cannot replace it.

Use the two-week checkpoint for early feedback on the initial price response,
entry assumptions and newly available catalyst evidence. Keep its results separate
from longer-horizon results in summaries; it is not a verdict on a 3–12 month
thesis. Unfolding catalysts remain unresolved, and a short-term gain or loss alone
does not justify a new investing rule or a sell recommendation.

Keep the original target and actual observation dates when catching up late.
The publication date of the new record identifies when the result was recorded;
do not backdate the daily note. Record the sourced baseline/endpoint prices,
timestamp basis/precision, currency, source IDs/URLs, corporate actions and matching
benchmark observations. Preserve the raw baseline and endpoint observations,
then retain any adjustment factors and adjusted calculation inputs in the
checkpoint card. Price returns require consistent split-adjusted inputs and
disclosure of excluded cash dividends. Total returns need supported
dividend/reinvestment treatment for both stock and benchmark. Never divide an
adjusted close by a raw opening value: providers can mix these fields in one
response, as [Alpha Vantage's Daily Adjusted documentation](https://www.alphavantage.co/documentation/#dailyadj)
illustrates. Retain the inputs and formula, not just a percentage. A later split
requires a consistent calculation basis, not a correction to accurate raw history.

Show stock return, broad-market and sector returns where available, and their
differences over the same baseline/endpoint sessions and return convention;
disclose any difference in timestamp precision. Label gross results as
excluding fees, spreads and slippage. A net scenario needs reproducible stated
assumptions, not invented fills or expenses. Missing benchmark data is a limitation,
not a zero benchmark return. Preserve missing, delisted, acquired or renamed
instruments and resolve proceeds/identity changes only from supporting data.

Review **decision quality separately from price performance**: whether the stated
catalyst occurred, which operating assumptions held or failed, whether the price
already reflected the improvement, and which contrary evidence was available
when the recommendation was made. Separate contemporaneous omissions from facts
that emerged later; don't claim an unknowable outcome should have been predicted.
A rising price does not validate every part of the thesis, and a loss alone does
not establish faulty analysis. Causal explanations remain hypotheses where the
evidence cannot distinguish them.

Invalidation and expiry do not simulate a sale or truncate fixed forward windows.
All published recommendations, including failures, remain in the census. Maintain
per-horizon sample sizes, missingness and market context. Small, overlapping or
selected samples cannot establish a reliable investment edge. These are hypothetical
forward research returns, not actual trades, realized portfolio performance or
instructions to sell. Method changes need a new convention version, documented
before applying it prospectively; never optimize past benchmarks or endpoints.

## Structured journals in the daily note

All journal sections belong under `### Outcome review` in the Research record.
Use the exact H4 titles and table headers below when an event is recorded. Omit
a journal with no changes, or write exactly `No changes.` under its heading.
Do not create duplicate journals, repeat unchanged rows each day, or use these
reserved headings elsewhere. Use other H4/H5 headings for the detail cards that
the `Record` links point to. The helper indexes these tables; prose explains them.

Keep one row per recommendation/checkpoint/lesson/month in each journal per note.
A `Record` is an unpiped filename-qualified wikilink to an existing dated market
note and its actual section, or the current draft. Prefer the canonical form
`[[Investments/YYYY-MM-DD-market-research#Section]]`; never point to a future note,
missing heading, external URL or scratch file. A record link must identify the
detail supporting that row, not merely a generic note with no relevant evidence.
Use distinct descriptive headings so the references remain retrievable. For a
timestamped baseline or checkpoint, the linked card's note must also have a cutoff
at or after that event; an older pending card cannot contain a later observation.

#### Recommendation records

| Recommendation | First ready | Baseline at | Record | Replaces |
|---|---|---|---|---|
| NASDAQ:EXAMPLE@2026-09-08 | 2026-09-08 | pending | [[Investments/2026-09-08-market-research#Original recommendation EXAMPLE]] | - |

`Recommendation` uses the unchanged thesis ID. `First ready` is the date of its
first published ready state, which may be later than the date in the thesis ID.
`Baseline at` is `pending`, `unavailable`, or an ISO timestamp with seconds and an
explicit offset, representing the sourced opening event or the verified session
marker defined above. Use the verified New York opening offset. The baseline's
New York date must follow the first-ready date. Its timestamp must not precede the
first-ready note's known generation time or exceed the containing note's cutoff.
Put prices, timestamp basis/precision and full provenance in the linked detail
card. The pending-to-observed update points
to its new baseline card while retaining the original recommendation link there.

#### Checkpoint records

| Recommendation | Horizon | State | Observed at | Record | Replaces |
|---|---|---|---|---|---|
| NASDAQ:EXAMPLE@2026-09-08 | 2w | unavailable | - | [[Investments/2026-09-24-market-research#EXAMPLE two-week data gap]] | - |

The stable checkpoint key is the recommendation ID plus `Horizon`, one of
`2w`, `1m`, `3m`, `6m`, `12m`, `24m`, `60m`. The helper returns the same tokens in
its `horizon` field. Two weeks is `2w`; five years is `60m`. Earlier month-only
tables remain readable and are indexed under the corresponding month horizons;
do not rewrite historical notes. Use `Horizon` for new records.

`State` is `observed` or `unavailable`. For unavailable
observations use `-` in `Observed at` and explain missing data/next check in the
card. The helper derives future pending windows; no journal row is needed merely
to list them. For an observed window, enter the sourced closing event timestamp
or verified session closing marker, never a retrieval time or future close.
The baseline must be known, the New York observation date must be on/after the
computed target, and the timestamp must be at/before the current note's cutoff.
The caller additionally verifies the exact first eligible trading session and
data availability.

The linked checkpoint card records the recommendation/first-ready link, baseline
record/version, horizon, calendar target, observation and timestamp basis/precision,
sourced raw/adjusted inputs, returns/benchmarks, cost convention, original-thesis
assessment and limitations. Keep reference price, baseline and endpoint
unambiguous. The examples above show syntax only; do not publish them as facts or
leave their links unresolved.

#### Lesson records

| Lesson | Status | Record |
|---|---|---|
| lesson-2026-10-10-01 | provisional | [[Investments/2026-10-10-market-research#Lesson on earnings confirmation]] |

Lesson IDs use `lesson-YYYY-MM-DD-NN`, with their first-recorded date and a positive
sequence starting at `01`: use at least two digits, without redundant leading
zeros (`01` through `99`, then `100`, etc.). An ID first introduced in a new draft
uses that note's date, even when its evidence is older. Keep published IDs unchanged,
including earlier records whose ID date was inaccurate. Keep the ID when revising a lesson.
Status is `provisional`, `supported`, or `retired`. An updated row points to a new
card in the current draft that links the previous version and explains what changed; do not erase
contradictory or retired lessons. Later evidence may lower confidence or justify
a new status, but the history remains visible.

Each lesson card includes its **finding**, **scope/setup**, **supporting and contrary
recommendation/checkpoint IDs**, **number of distinct recommendations**, **decision
quality explanation**, **confidence/limitations**, **specific prospective research
check**, and **next reassessment condition/date**. Distinguish observed association
from its possible explanation. Identify evidence used to formulate the lesson
separately from subsequent recommendations used to test it.

A single win or loss normally produces a provisional question, not a universal
investing rule. Supported means repeated relevant evidence has survived explicit
contrary-case review and later observations; state the basis rather than claiming
a statistical threshold or causality that was never established. Retirement means
the lesson is contradicted, superseded or no longer useful; give the reason.

Use lessons to ask better evidence questions within the skill's current scope.
Do not weaken source verification, force a pick, change risk boundaries, or adjust
screens to flatter past results. If a lesson suggests changing plugin behavior,
record the evidence under the shared suggestion-log rules; routine research never
edits skill sources. No mandatory human review is added to daily publication.

#### Monthly summaries

| Month | Record |
|---|---|
| 2026-10 | [[Investments/2026-10-10-market-research#October learning summary]] |

Register the review only when completed. `Month` must match both the containing
note and the linked summary note's New York month, including a delayed first
successful review. Link its cumulative
counts, result comparison, active/provisional/retired lessons, contrary cases and
unresolved questions. An unavailable data feed can be disclosed within a completed
honest summary, but an unperformed/incomplete review must not be marked complete.
Daily retrieval uses the latest summary plus subsequent journal events so new
lessons are not lost between monthly consolidations.

## Corrections and publication

Old daily notes remain immutable. First observations and pending/unavailable-to-
observed updates use `-` in `Replaces`. Changing a finalized baseline or checkpoint
requires an explicit new row whose `Replaces` is the exact previous `Record` link.
For a `needs-recheck` checkpoint, explicitly replace that prior link even if its
stored observation was unavailable.
The new `Record` must identify a distinct detail card in the current draft;
another spelling of the old link or a return to an older card is not a new card.
Restoring an earlier correct value is allowed when the new card documents why.
Published historical rows remain readable without rewriting them.
The new detail card links the old one,
identifies the factual error, cites the corrected evidence, and explains affected
calculations. Do not silently substitute a favorable observation or present a new
convention as a factual correction.

A factual baseline correction makes previously calculated checkpoints `needs-recheck`
until each affected window is explicitly revised against the corrected baseline.
Checkpoint corrections with unresolved evidence links also remain `needs-recheck`.
They remain due even if the old result was observed; retained obsolete figures
are not current evidence. Handle corrections before deriving new lessons and
reassess lessons that relied on the superseded observations. Source corrections
are performed within the normal research workflow, without a mandatory human gate.

Before publication, run both `lint` and
`outcomes --vault '<vault>' --draft '<scratch>/daily.md'` using the bundled helper.
Resolve missing recommendation records, inconsistent first-ready dates, broken
references, future observations or conflicting corrections before publishing.
Keep genuine missing market data as pending/unavailable with a truthful record,
not as fabricated data to satisfy validation. Read back the published note and
confirm its journal appears in the rebuilt outcome index.
