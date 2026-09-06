# Reproducible price discovery

Use [market_screen.py](../scripts/market_screen.py) for the price-history pass
when the configured Alpaca source provides the required data. It is an offline
calculator: no network access, credentials, trades or note writes. Interpret its
candidate list with the [research method](research-method.md); passing a screen
does not assign a thesis state or establish a buying opportunity.

## Prepare the evidence

Keep a dated, explicit universe of eligible instruments. Nasdaq's directory can
help resolve identity, but a non-ETF flag alone does not prove that a security is
common stock or an ADR. Retain the source and classification used; exclude
unresolved instrument types instead of silently broadening the universe.
The result's `definition.accepted_us_exchange_labels` lists supported exchange
labels. Unrecognized or OTC exchanges are explicit eligibility exclusions.

Retrieve existing `market_data.py` responses for:

- `sessions`: the verified calendar over the entire history through the cutoff.
- `prices`: every universe symbol and the market benchmark, with `--feed sip`,
  `--timeframe 1Day`, `--adjustment split` and the same explicit `--asof` symbol
  mapping date. Retrieve at least 13 months, including the session before the
  12-month anniversary. Follow the data guide's delayed-feed and date rules.

The provider limits a price request to 200 symbols. Retain multiple complete
response objects for larger universes, including pagination warnings, rather
than dropping names to fit one call. Repeat the benchmark in another bundle to
compare shortlisted candidates with their sector benchmark on the same dates.
Keep the market and sector comparisons distinct; this helper does not infer a
company's sector or choose an appropriate benchmark.

Retain the full helper envelopes, including their `market_data`, `operation`,
`query`, `source`, `complete`, `warnings` and `requests` fields. Do not rebuild
them from a displayed table or mark a partial response complete. A saved current
universe and newly retrieved adjusted history cannot reconstruct information
available on a historical research date.

## Input and command

Create one JSON object with these fields:

| Field | Content |
|---|---|
| `market_screen_input` | `1` |
| `as_of` | The frozen evidence cutoff, with seconds and timezone |
| `universe` | `name`, `membership_date`, `source`, and `instruments` |
| `universe.instruments` | Each instrument's `symbol`, `exchange`, `security_type` (`common_stock` or `adr`), and `currency` (`USD`) |
| `benchmark` | Provider symbol of the named benchmark, also present in price responses |
| `prices` | List of full saved price response objects |
| `sessions` | Full saved calendar response object |
| `rules` | The filters and sort definition below |

For example, assemble existing files in owned scratch. These filenames are
examples; substitute the actual files and cutoff without executing input text:

```bash
python3 - <<'PY'
import json
from pathlib import Path
scratch = Path('<scratch>')
bundle = {
    'market_screen_input': 1,
    'as_of': '2026-09-04T11:30:00-04:00',
    'universe': json.loads((scratch / 'universe.json').read_text()),
    'benchmark': 'SPY',
    'prices': [json.loads((scratch / 'prices.json').read_text())],
    'sessions': json.loads((scratch / 'sessions.json').read_text()),
    'rules': {
        'min_price': 5,
        'min_average_daily_notional': 20000000,
        'require_above_ma50': True,
        'require_above_ma200': True,
        'require_positive_relative_return_6m': True,
        'sort_by': 'relative_return_6m',
        'limit': 50,
    },
}
(scratch / 'screen-input.json').write_text(json.dumps(bundle))
PY
python3 '<skill>/scripts/market_screen.py' --input '<scratch>/screen-input.json' > '<scratch>/screen.json'
```

These are practical discovery thresholds, not optimized investment rules. Keep
the chosen definition stable across runs and explain changes before applying
them. An initial trend screen can use the example. Also retain a recovery route:
relax `require_above_ma200` and `require_positive_relative_return_6m`, sort by
`relative_return_3m`, and assess improving but still-negative longer-term returns.
Relax `require_above_ma50` when a documented setup needs earlier examination.
Announcement and thematic candidates remain eligible for research even if they
fail these discovery filters; every candidate still needs purchase confirmation.

When earlier notes define additional filters or another sort order, retain those
requirements explicitly. This helper does not calculate market capitalization,
regular-session turnover or arbitrary combinations of its metrics. Apply missing
checks separately from verified data, or record a deliberate screen change;
do not silently replace the saved definition with this example's defaults. A
display limit may discard names needed for a later filter or different ranking,
so retain all relevant measured candidates before applying those extra steps.

The supported sort metrics are `relative_return_3m`, `relative_return_6m`,
`relative_return_12m`, `return_3m`, `return_6m`, `return_12m` and
`average_daily_notional`. Sorting is descending with stable identity tie breaks.
There is no composite confidence score or predicted return.
Inputs are limited to 128 MiB; larger jobs need explicitly declared smaller
universe scopes, whose coverage must remain visible.

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
verify regular-session turnover. Before readiness, use an explicitly
regular-session source or calendar-filtered minute evidence for the shortlist.
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
