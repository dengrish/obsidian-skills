# Prospective evaluation of the actual nominee pool

Use this for stock-research's selection from the feed ideas it actually received.
The older [independent momentum comparison](comparison-strategy.md) keeps its
own identities, evidence, return windows and history.

The fixed strategy is `feed-nominees-v1`: **first verified security nomination
after activation**, with each security enrolled once. Multiple posts nominating
the same security produce one member with every source origin retained. A later
material argument or decision is an immutable observation of that member, not a
new independent success or a retrospective change to its initial group.

## Activate, then enroll published work

`market_notes.py prepare` activates the evaluator before a new edition is
published. For a manual workflow that does not use prepare, activate before
writing the first new daily report:

```bash
python3 '<skill>/scripts/stock_cohorts.py' start --vault '<vault>'
```

Activation freezes existing report hashes and securities in their journals,
assessments and thesis ledgers; these remain outside the prospective population.
Activation is idempotent and never resets. Neither activation nor formation
accepts a historical clock or a caller-selected member list.

After the ordinary daily publication and stock-note synchronization succeed:

```bash
python3 '<skill>/scripts/stock_cohorts.py' form --vault '<vault>'
```

Formation replays every unaccounted published report. It derives all nominations
from validated schema-2 `Feed dispositions` and `Research queue` journals.
Assessed nominations must link that report's actual assessment and agree with
its readiness ledger. `queued` and `blocked` nominations enroll immediately.
Reports with no new members still retain coverage and later observations;
postactivation legacy reports remain explicit coverage gaps without enrollment.

Members retain security identity, all post IDs/URLs/fingerprints, first-seen time,
source report/hash, decision cutoff, initial assessment/work state and formation
time. `generated_at` is the declared publication timestamp; actual formation is
the conservative time by which the published file was observed. Delay remains
visible: missed formations recovered later start measurement after recovery.

Initial groups are `ready`, `watch`, `rejected` and `unfinished`, retaining
`queued` versus `blocked`. An initially invalidated/expired assessment belongs
to rejected with its exact status retained. Later work, arguments and decisions
never relabel those groups. Reuse/monitoring without a current assessment does
not invent a contemporaneous ready decision.

Keep unresolved identities/posts and source gaps visible; zero members do not
prove complete source coverage or no useful ideas. User-only ideas and repeated
claims without a substantive nomination do not expand this feed population.

## Read the daily and monthly view

```bash
python3 '<skill>/scripts/stock_cohorts.py' context \
  --vault '<vault>' --as-of '<frozen cutoff>'
```

The ordinary outcomes helper also returns this read-only view under
`nominee_comparison`. It includes activation, frozen cohorts and initial counts,
checkpoint results, due windows, unresolved coverage, evidence links, and a
compact `summary_markdown`. `formation_due` and `unformed_reports` identify
published work still needing the idempotent formation command. Do not declare a
daily run complete while its postpublication formation is still outstanding.

Use the compact summary and relevant evidence links in the existing daily
**Outcome review** and monthly learning summary. Record material new formations,
transitions, observations and gaps; link unchanged detail. This feature writes
no separate dated report series and never rewrites a published daily note.

Create-only JSON under `Investments/Snapshots/Nominees/` preserves activation,
formations, transitions and checkpoints in an immutable predecessor chain.
Replay rechecks source hashes, derives membership/decisions again and recomputes
results. These are durable records, not scratch. Changed sources, missing links
or competing events fail visibly; writers share the vault publication lock.

## Observe the fixed return windows

Every member/group uses the **regular open on the first trading date after
actual formation's New York date**, after known report availability. A later
ready decision does not restart this clock; its separate recommendation outcome
can retain a first-ready baseline.

Evaluate `2w`, `1m`, `3m`, `6m` and `12m`. Two weeks means 14 calendar days;
monthly targets clamp to the last day of shorter months. Use the close of the
first verified regular session on or after the target, including closures and
early closes. Calendar boundaries are session markers, not observed auction
timestamps. A daily bar must have fully elapsed by the evidence cutoff. At an
11:30 ET run, that day's closing result is pending.

Prepare a saved JSON input using the existing price/calendar capture tools:

```json
{
  "stock_nominee_input": 1,
  "as_of": "2026-09-25T11:30:00-04:00",
  "sessions": {},
  "prices": [],
  "corporate_actions": {}
}
```

The empty containers illustrate the shape only; replace them with actual saved
`market_data` envelopes and verification records. `sessions` is one complete
exchange calendar from formation through cutoff. `prices` contains the full
saved Alpaca SIP, USD, split-adjusted `1Day` envelopes for every original member
and `SPY`; preserve the actual formation date in each query's symbol mapping
`asof`. Retain each security's corporate-action and identity evidence under its
symbol, using the existing comparison verification shape: `status: verified`,
`source` and a substantive `note`. Unsupported mappings, unresolved actions,
missing securities and incomplete retrievals remain unavailable.

```bash
python3 '<skill>/scripts/stock_cohorts.py' evaluate \
  --vault '<vault>' --cohort '<context cohort ID>' --horizon 2w \
  --input '<scratch>/nominee-observation.json'
```

Full input evidence is retained. Return is split-adjusted endpoint close /
split-adjusted baseline open − 1, using existing price/calendar/source/action
checks. Gross hypothetical returns exclude cash dividends, fees, spreads and
slippage; they imply no trades, fills, holdings or sell instructions.

Evaluation after the daily cutoff can supply its returned summary and evidence
link directly to the current draft when input `as_of` matches that frozen cutoff.
Keep calculation/publication time distinct from market-evidence time. Context
includes persisted events only through its requested cutoff, so it will see that
later-saved result on a subsequent run; do not alter the cutoff to force it in.

If evidence cannot be obtained, use `stock_nominee_input: 1`, `as_of`, and a
concrete `unavailable_reason` instead of fabricated market containers. The
result preserves every original member and null returns. A pending opening or
endpoint needs no stored checkpoint; it remains in the derived pending census.
An unavailable checkpoint remains due and may later become observed. An exact
retry changes nothing. Changing a previously observed checkpoint requires
`--replaces '<previous checkpoint SHA-256>'`; the new immutable artifact
retains the prior identity and corrected evidence. Describe the factual
correction in the existing Outcome review.

## Interpret selection with its denominator visible

Show per-horizon enrolled/observed/unavailable/pending counts, member returns,
matching SPY and initial-group equal-weight means. A mean requires **every
original group member**. Never omit delisted/renamed/acquired instruments,
replace missing returns with zero or renormalize survivors. Empty groups have
no return; missing benchmarks are unavailable.

`ready_minus_pool` subtracts the complete original pool mean from the initial
ready-group mean within that **same formation and window**. Empty or incomplete
required groups leave the difference unavailable. The ready group overlaps the
pool, so these are not independent samples. Missing SPY leaves benchmark excess
unavailable even if the stock-only mean or selection difference can be computed.

Monthly learning uses same-cohort/horizon differences with available/missing
denominators, never averages across unmatched date mixtures. Disclose delays,
overlapping exposures, market conditions, sample size and source gaps. Keep
two-week feedback separate from longer-horizon thesis outcomes.

This measures initial selection from first postactivation feed security
nominations. It does not establish author skill, portfolio performance or a
release's causal effect. Small, overlapping, selectively available samples
cannot establish proven alpha. Method changes need a new prospective version;
preserve this version and older independent momentum histories.
