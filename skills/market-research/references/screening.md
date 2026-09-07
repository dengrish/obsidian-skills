# Reproducible price discovery

Use [market_screen.py](../scripts/market_screen.py) for the price-history pass
when the configured Alpaca source provides the required data. It is an offline
calculator: no network access, credentials, trades or note writes. Interpret its
candidate list with the [research method](research-method.md); passing a screen
does not assign a thesis state or establish a buying opportunity.

## Acquire and prepare the evidence

Use [market_acquire.py](../scripts/market_acquire.py) `discover` for the normal
bounded acquisition pass; the [data guide](data-access.md) gives the command and
request/time budgets. It reads both full current Nasdaq directories, classifies
common shares and ADRs conservatively, collects 20 completed daily sessions,
then retrieves full history for **every measured daily-proxy pass**. It does not
start from a handpicked ticker list or select the best known companies first.
Announcement-driven and existing-thesis follow-ups remain separate routes.

[market_universe.py](../scripts/market_universe.py) supplies the reusable offline
stages. It rejects filtered directory snapshots, excludes ETFs, test issues,
preferreds, warrants, units, when-issued listings and ambiguous names, and retains
classification evidence and unresolved identities. It never rewrites a provider
symbol to guess another share class. Directory observations retain their actual
New York date; a later-date capture cannot reconstruct an earlier universe.
Same-date retrieval after the evidence cutoff is explicitly current discovery,
not proof of timestamp-level historical membership.

Batches traverse a declared SHA256 order of cutoff date and security identity.
This avoids an alphabetical or market-cap-first prefix and rotates by date, but
a budget-limited prefix is still an **incomplete sample**, not a representative
market-wide screen. Retain all missing identities and counts. The preliminary
price ≥ $10 / mean daily-notional ≥ $25 million filter is distinct from the
existing `liquid-us-v1` eligibility definition: it does not verify market cap or
regular-session turnover. Explain this prospective discovery expansion; retain
old outcome/comparison definitions and the original readiness checks.

For already saved envelopes, the offline commands replace handwritten input
assembly. These are owned-scratch example paths; substitute actual paths:

```bash
python3 '<skill>/scripts/market_universe.py' universe \
  --directory '<scratch>/directory.json' --as-of '<cutoff>' \
  > '<scratch>/universe.json'
python3 '<skill>/scripts/market_universe.py' prefilter \
  --universe '<scratch>/universe.json' --prices '<scratch>/daily-001.json' \
  --sessions '<scratch>/sessions.json' --as-of '<cutoff>' \
  > '<scratch>/prefilter.json'
python3 '<skill>/scripts/market_universe.py' prepare \
  --universe '<scratch>/prefilter.json' --prices '<scratch>/history-001.json' \
  --sessions '<scratch>/sessions.json' --as-of '<cutoff>' --benchmark SPY \
  > '<scratch>/screen-input.json'
python3 '<skill>/scripts/market_screen.py' --input '<scratch>/screen-input.json' \
  > '<scratch>/screen.json'
```

Repeat `--prices` for every original saved batch. Do not merge displayed tables
or alter `complete`, query, source, requests, warnings or bar data. An empty
prefilter result needs no full-history screen; distinguish a complete measured
zero-pass result from unavailable prices. Daily bars must use SIP, USD, split
adjustment and the cutoff's explicit symbol-mapping date. The complete calendar
must cover every session needed for the 200-session average, its 20-session
change and the calendar-month return anniversaries, including the preceding
12-month reference session. Sector comparisons
use an explicitly chosen appropriate benchmark and matching dates separately.

Preparation preserves all declared stage-two names and sets its default display
limit to the entire roster. Missing broad batches remain an incomplete screen
even when the measured subset has complete long history. Default trend gates
are off and sorting uses three-month relative return so recovery candidates stay
visible. To retain a previously declared screen, pass `--rules` with its JSON
rules, then apply any additional conditions the calculator does not implement.

The `market_screen_input: 1` bundle remains supported for custom declared
universes: `as_of`, `universe` (`name`, `membership_date`, `source`, `instruments`),
`benchmark`, original `prices` envelopes, original `sessions` envelope and
`rules`. Each instrument requires `symbol`, `exchange`, `security_type`
(`common_stock` or `adr`) and USD `currency`. An optional boolean
`universe.discovery_complete` carries prior-stage coverage; false cannot become
a complete screen merely by dropping unmeasured names.

These are practical discovery thresholds, not optimized investment rules.
Announcement and thematic candidates may still warrant research when they fail
discovery filters; every candidate needs the same eligibility and purchase
confirmation checks. The price screener does not itself calculate capitalization
or regular-session turnover; use the shortlist workflow below. Preserve all
measurements needed for later filters or ranking before applying a display limit.

The supported sort metrics are `relative_return_3m`, `relative_return_6m`,
`relative_return_12m`, `return_3m`, `return_6m`, `return_12m` and
`average_daily_notional`. Sorting is descending with stable identity tie breaks.
There is no composite confidence score or predicted return.
The offline input-file limit is 128 MiB. The coordinator retains measured results
and original batches if their duplicate assembled input exceeds this boundary,
with an explicit comparison-input limitation. Never shrink a monthly comparison
after ranking to fit the limit. A deliberately smaller future discovery scope
must be declared before selection and disclosed as a prospective change.

## Interpret and preserve the result

Returns use calendar-month anniversaries mapped to matching completed exchange
sessions, and relative return subtracts the benchmark's return. Moving averages
use 50/200 scheduled sessions; their changes compare with 20 sessions earlier.
Returns and moving-average changes are decimal fractions: `0.10` means 10%,
and a relative return of `0.02` means a two-percentage-point difference.
Prices and moving averages are split-adjusted USD; the notional proxy is USD
per day. The output repeats these units in its definition.
Check the reported window dates and actual available measurements. Missing
sessions, a missing reference close, mismatched feeds or adjustments, and limited
provider responses cannot be repaired with zeroes or shortened lookbacks.

The 20-session average of daily VWAP × volume is a **daily notional proxy**.
Alpaca's daily volume includes eligible extended-hours activity; it does not
verify regular-session turnover. For the shortlist, use the bundled calculator:

```bash
python3 '<skill>/scripts/market_universe.py' liquidity \
  --prices '<scratch>/shortlist-minute.json' --sessions '<scratch>/sessions.json' \
  --as-of '<cutoff>' --symbols '<shortlist-symbols>' \
  --market-caps '<scratch>/market-caps.json' > '<scratch>/eligibility.json'
```

Minute evidence must be SIP, USD and split-adjusted, using the same mapping date.
The calculator filters against actual calendar opening/closing times, including
early closes, and lists missing expected minutes separately for each session.
It never imputes zero trading or divides observed days by a shortened lookback.
Missing minutes may mean no eligible trade or unavailable data: the resulting
turnover stays unresolved until another explicit regular-session source settles
it. A provider's `complete` flag alone is not complete interval coverage.

The optional market-cap file is a JSON list of rows with `symbol`,
`market_cap_usd`, `currency: "USD"`, timezone-aware `as_of` and `available_at`,
`source_url` and `basis`. The basis identifies the issuer/share classes and ADR
ratio where applicable; do not multiply an ambiguous share count by a convenient
price. Measurement must be at least as recent as the reference session, and
measurement ≤ availability ≤ cutoff. Without this sourced input, capitalization
eligibility remains unresolved. Cap and turnover verification still do not
establish a buying opportunity.

Daily OHLC and volume use different eligibility rules; see
[Alpaca's aggregation documentation](https://docs.alpaca.markets/us/docs/market-data-faq).
This is split-adjusted price analysis, not a total-return outcome calculation.

Inspect `complete`, warnings, exclusions and coverage counts as well as the
ranked rows. A result limit is a display limit, not evidence that all passing
companies were reviewed. Exit 2 can retain useful partial measurements; report
the gap rather than calling the declared screen complete. Do not equate no
passing candidates with a failed or incomplete screen.

In the daily Research record retain the universe definition, exact rules, input,
rule and calculator digests, cutoff/reference session, coverage counts, and the
measurements and source observations needed to reproduce shortlisted or decisive exclusions.
A digest identifies input; it does not preserve that input. Keep relevant dated
values in the note or an already authorized durable source, with source URLs and
adjustment definitions. Do not cite temporary JSON paths after scratch cleanup
or copy entire licensed feeds into the note. The existing outcome journal remains
the record of subsequent recommendation performance.

## Fixed comparison alongside discretionary discovery

On the first research edition of each month, reuse the declared saved input for
the [prospective mechanical comparison](comparison-strategy.md). It recomputes
its own fixed momentum rules and preserves all decisive measurements, including
exclusions, independently of the discretionary screen or analyst shortlist.
Declare the accessible universe before ranking; disclose scope limits and
prospective universe changes. An incomplete first formation stays unavailable
for that month. This adds no daily market-wide fetch and never turns mechanical
selection into a ready recommendation.
