# Prospective mechanical momentum comparison

Use [market_comparison.py](../scripts/market_comparison.py) to form and evaluate
one fixed monthly **strategy diagnostic** alongside discretionary research. The
helper is offline: it reads saved evidence, preserves immutable JSON attachments
under `Investments/Snapshots/Comparisons/`, and prints compact Markdown cards and
journals. It never writes daily notes, fetches data, places trades or creates
ready recommendations. Publish its records through the ordinary daily-note workflow.

## Fixed definition and formation

The fixed strategy (ID `simple-momentum-v1`) uses the declared accessible universe already prepared for
the [price screen](screening.md), with SPY as its benchmark. Declare the universe
and source before examining the ranking; it must not be a shortlist of today's
favored ideas. Limited coverage is acceptable when visible. Freeze this universe's
identity, dated membership and classifications in the formation record. Explain
prospective scope changes, never narrow it after seeing which names win. No
additional market-wide daily fetch is required.

In `curated_social` mode, the nominated universe is a discretionary shortlist,
not an independent universe for this fixed comparison. Do not form
`simple-momentum-v1` from it. If due, record unavailable with the scope mismatch
unless the previously declared independent input is already available at this
cutoff. Do not acquire a broad universe solely for this diagnostic. Continue due
observations for earlier cohorts unchanged. A future comparison of the curated
pipeline would require a separately supported prospective definition.

Eligible instruments are USD common stocks/ADRs on the screener's supported U.S.
exchanges, priced at least $10, above their 200-session moving average, with a
20-session mean daily VWAP × volume of at least $25 million and a positive
six-calendar-month price return minus SPY's matching return. The daily notional
proxy includes extended hours; it is not proof of purchase-ready regular-session
liquidity. The existing screener defines matching completed sessions, price
adjustments and required history. Rank by descending relative six-month return,
breaking ties by exchange then symbol. Select at most three names, equally
weighted across the **actual selected count**. One name means weight one, not
one-third plus invented cash. Do not add qualitative overrides, tune thresholds
from results, or replace an unavailable member with a later winner.

The first review using this feature activates it prospectively. Thereafter form
once in the first published research edition of each New York calendar month,
including a manual or non-trading-day edition. Before assembling a new note,
inspect `comparison_formation_due` and
`comparison_formation_must_be_unavailable` from `market_notes.py outcomes`:

- Already formed: link its original card when useful; do not copy unchanged rows.
- Due: reuse the complete saved screen input at this edition's frozen cutoff.
- Missing data, unavailable access, evidence beyond the bounded attachment limit, or a missed first monthly
  formation: record **unavailable** now. Preserve that month; do not select later.
- Complete screen with no eligible names: record **empty**. Empty/unavailable
  months have no simulated cash return and remain part of the coverage census.

Do not backfill earlier months. A month with no published review has no formation;
disclose gaps in summaries. The helper overrides discretionary `rules`/`benchmark`
and recomputes selection from the full saved `market_screen_input` bundle. It
retains every declared instrument's decisive metrics/status, source/query/digest
evidence, membership, mapping, cutoff and calculator/strategy hashes in a linked
JSON attachment. The visible card shows selected members, the declared instrument
count, defining metadata, a vault-relative attachment link and its SHA-256. Full
calendar JSON and the unselected roster stay out of the daily note. No raw feed
archive or temporary-path citation is needed. If complete evidence exceeds the
32 MiB attachment limit, record unavailable rather than trimming the universe.
The universe hash binds its name, dated membership, source and complete instrument
identities/classifications in canonical exchange/symbol order. Card validation
checks that roster, fixed source-query conventions and fully elapsed daily bars;
do not manually rewrite a generated card to change its scope or timestamps.
Compact formation-calendar triples preserve the verified session dates and
boundaries. Validation reuses the screener's exact anniversary and 220-session
history rules, checking price-query coverage for every required session and
eligible instrument, including SPY; a reference-day-only query is insufficient.

```bash
python3 '<skill>/scripts/market_comparison.py' form \
  --input '<scratch>/screen-input.json' --note-key '<exact-daily-note-stem>' --vault '<vault>'
python3 '<skill>/scripts/market_comparison.py' unavailable \
  --as-of '<cutoff>' --reason '<specific limitation>' --note-key '<exact-daily-note-stem>' --vault '<vault>'
```

Use only the applicable command. Add its `journal_markdown` and `detail_markdown`
under the daily Research record's Outcome review. `Comparison cohorts` has exact
columns `Cohort | State | Record`; the ID is `simple-momentum-v1@YYYY-MM`, with
state `formed`, `empty` or `unavailable`. Its first card and membership are
immutable, independent of ready-thesis IDs. Subsequent observations may not
redefine formation. A future strategy needs a new supported definition/ID
introduced prospectively while preserving readers for previous definitions.

Pass `--vault` for every live formation/evaluation. The helper creates only
`Investments/Snapshots/Comparisons/<SHA-256>.json`, binding the exact owning daily
note stem and record kind to the complete canonical evidence. It stages complete
bytes privately, publishes exclusively, and verifies an identical retry without
changing the original. Unexpected occupants, symlinks, portable-name collisions,
directory replacements and different bytes stop the write. The daily note remains
unpublished until its independent review and normal publication checks finish;
an attachment left by an interrupted run can be verified and reused on retry.
Publication briefly pins the process working directory; use these single-threaded
CLIs, never invoke their writers concurrently from multiple threads.

Every outcomes/indexing read verifies the attachment's path, owner, content hash
and visible summary before running the same full roster, query, calendar and
return checks as an inline card. A missing or altered attachment makes the
comparison incomplete; never infer its contents from the brief. Historical
inline cards remain readable without migration. Omitting `--vault` is retained
only for offline fixtures and historical-format compatibility, not live notes.

## Fixed return windows and retained evidence

Evaluate formed cohorts at **3, 6 and 12 calendar months**, not every day. Their
baseline is the regular opening on the first trading date after the formation
note's New York date, after known publication. Their endpoint is the first
regular close on/after the baseline's calendar-month anniversary, clamped for
short months. Verify actual sessions and early closes; never choose a convenient
later baseline or endpoint. Calendar boundaries label **session markers**, not
official auction fills. Daily bars must have fully elapsed and been available
by the new note's cutoff; an intraday quote cannot replace them.

Read `due_comparison_checkpoints` from the ordinary outcomes index. Before any
baseline observation, its target is an earliest possible calendar date, not
proof that the opening or endpoint occurred. The evaluation helper verifies the
calendar and may return `pending` with no new journal. When a calendar cannot be
verified, keep the task due and state the limitation in prose. Do not fabricate
timestamps to create a row. Otherwise prepare this JSON input:

| Field | Required content |
|---|---|
| `market_comparison_input` | `1` |
| `as_of` | Current edition's frozen cutoff, including seconds and offset |
| `sessions` | Complete saved `market_data.py sessions` envelope, formation date through cutoff |
| `prices` | Full saved price envelopes for every original selected symbol and SPY; SIP, `1Day`, USD, `split`, retaining the formation's explicit `asof` mapping date |
| `corporate_actions` | Object keyed by each original symbol and SPY, each with `status`, `source` and `note` |

Retrieve price windows containing the fixed baseline and endpoint; include
history around closures as needed, without refetching a market-wide universe.
In each corporate-action entry, `verified` means a sourced check resolved the
instrument identity and split-adjusted price comparability over this interval;
the source and explanation are required. Otherwise use `unavailable` and explain
the gap. A symbol mapping request alone does not establish that a delisting,
merger, share-class change or successor series is comparable. Preserve original
identities and unresolved corporate-action cases; do not substitute a survivor
or invent proceeds, dividends or a terminal value.

```bash
python3 '<skill>/scripts/market_comparison.py' evaluate \
  --cohort-note '<vault>/Investments/<original-daily-note>.md' \
  --cohort 'simple-momentum-v1@YYYY-MM' --horizon 3m \
  --input '<scratch>/comparison-input.json' --note-key '<exact-daily-note-stem>' --vault '<vault>'
```

The visible card retains original identities, split-adjusted opening/closing
inputs and individual returns; its immutable attachment also retains source/query
evidence, verified calendar dates/session markers and corporate-action explanations.
For each instrument, return is
`endpoint close / baseline open - 1`; the basket is the arithmetic mean of
original selected members' returns, representing equal initial weights with no
interim rebalance. SPY uses the same sessions and convention. This is **gross
split-adjusted price return**, excluding dividends, fees, spreads and slippage.
The convention ID is `sip_split_adjusted_price_gross_v1`. Missing any member,
benchmark, complete price response or action evidence makes the basket unavailable;
the helper never renormalizes over survivors or invents zero/cash returns.

`Comparison checkpoints` has exact columns
`Cohort | Horizon | State | Baseline at | Observed at | Return | Benchmark return | Record | Replaces`.
States are `observed`/`unavailable`; return fields are decimal fractions or `-`.
Unavailable price results retain verified event markers and every original
member. Retry later; first observations and unavailable-to-observed updates use
`Replaces -` and a new current detail card. Correcting a finalized observation
requires `--replaces '<exact previous Record link>'` and an explanation of the
factual error. If correcting the baseline event affects multiple windows,
revise all affected windows against the same event or mark them unavailable;
old notes stay unchanged. A method change is not a factual correction.

## Interpret the diagnostic honestly

Monthly learning summaries retain formed/empty/unavailable/missing-month counts,
per-horizon sample sizes, individual member outcomes and matched SPY differences.
Link original cards and record new events; keep the Decision brief focused on
buying opportunities. Comparison membership is never itself a buy or sell signal.

This monthly strategy is **not a clean same-date selection experiment** against
discretionary picks. Different dates, universes, sectors, selected counts or
exposures can explain differences. Compare discretionary observations only when
formation/entry/end sessions, universe eligibility, benchmark, adjustment and
cost conventions match, disclosing residual differences and sample overlap.
Do not call unmatched differences “skill-added return,” optimize the comparison
to favor research, or infer a reliable edge from small overlapping cohorts.
Keep the fixed diagnostic separate from actual holdings and portfolio returns.
