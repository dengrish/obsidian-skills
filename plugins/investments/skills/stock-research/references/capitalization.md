# Dated company-size evidence

Use this procedure for the shortlist's **$2 billion issuer-size filter** when a
reliable dated USD market cap is not already available. Reuse verified filings,
prices and earlier research; do not query every feed mention or spend estimate
requests merely to populate a size field.

## Capture before freezing the cutoff

On a **fresh scheduled or manual** run, use the
[targeted coordinator](targeted-acquisition.md) to capture needed raw prices before
`market_notes.py prepare` freezes the edition. Use previously collected feed
nominees, earlier deferred lists and tracked stocks, including a first-run or
catch-up shortlist drawn from the saved feed. This preflight does not collect
new posts, query social APIs, discover companies or acquire the whole market.
New nominees first discovered after preparation cannot gain pre-cutoff local
availability by fetching their older bars; archive them for a later edition.

Keep an ordered JSON plan in owned scratch. Every object has exactly `symbol`,
`class_id`, `identity_source_url`, `identity_available_at` and `reason`.
Use a canonical uppercase provider symbol and the exact quoted common class or
ADS identifier used in the share-count review. The public HTTPS identity source
and timezone-aware availability must support that mapping before capture;
the helper never infers an entire issuer or a share class from a ticker alone.
`reason` briefly names the saved nomination or tracked thesis. No URLs are
fetched from this plan. The plan permits at most 30 unique symbols.

```bash
python3 '<skill>/scripts/market_price_capture.py' capture --vault '<vault>' --plan '<scratch>/price-plan.json' --max-symbols 10 --credentials-file '<credentials-file>'
```

The default limits new acquisition to ten unreused symbols in plan order. An
explicit catch-up plan can use `--max-symbols 30`; `--max-symbols 0` performs
archive reuse only. The helper shares a three-attempt transport budget across
one bounded calendar request and one five-minute batch of raw USD SIP bars,
with no feed substitution or assumption of paid real-time access. It excludes
unfinished intervals and the minute starting at the scheduled close, which may
mix closing-auction and extended-hours trades. Missing or malformed securities
remain unresolved while unrelated valid securities can be retained from a
complete validated page; incomplete pagination or transport cannot establish
complete target coverage.

Observations and first-save receipts are immutable, content-addressed JSON
under `Investments/Snapshots/Prices/`, using the existing pinned safe writer.
The receipt is timestamped only **after** the observation's exclusive publication
and verified readback. The archive retains the actual provider-request times,
raw interval and price, reviewed class identity and session evidence. Failed
receipt publication leaves an unreceipted observation ineligible; later retries
do not manufacture an earlier save time. In fresh mode the helper waits through the
actual next whole second after successful publication, including partial
success, and also when reusing a receipt saved in the current fractional second,
so the immediately following preparation can admit those saves.
It never selects or advances the research edition itself.

For an **already frozen manual or scheduled cutoff**, pass `--as-of '<cutoff>'`.
The edition's actual preparation cutoff stays fixed. A capture first saved after it
is `future_only`, with `price: null` for that edition, even if the bar describes
an earlier interval. Reuse an eligible earlier archive or report the price-availability gap;
do not re-prepare the edition, backdate the receipt or infer publication time
from the bar label or the provider's delay policy.

Replay is offline and produces capitalization-compatible objects directly:

```bash
python3 '<skill>/scripts/market_price_capture.py' select --vault '<vault>' --plan '<scratch>/price-plan.json' --as-of '<cutoff>' > '<scratch>/capitalization-prices.json'
```

Only `items[].status: selected` has a usable `price`. Copy that object unchanged
into the corresponding capitalization plan, and retain its linked observation
and receipt evidence. Missing, stale and future-only records have `price: null`;
do not fill them with manually invented timestamps. An eligible earlier record
takes precedence over a later ineligible capture. Matching requires the same
symbol, quoted class and identity-source declaration. Reuse requires the
archived calendar to cover the cutoff date, a price from at least the latest
completed reference session, and an interval ending within 30 minutes of the
latest SIP-available regular-session endpoint. This handles weekends and early
closes without making an old morning price fresh for an afternoon decision.
The retained calendar covers fourteen preceding and seven following calendar
days; later calendar gaps require new evidence, not an assumed session.

This fixes capture timing only. It does not establish a complete share count,
economic equivalence, intervening changes, fair value or buying readiness.

## Acquire the inputs

Resolve the issuer and quoted share class. Use `sec-company` to identify relevant
filings, then read the latest available outstanding-share disclosure. The existing
facts adapter can surface domestic share-count candidates:

```bash
python3 '<skill>/scripts/market_data.py' sec-facts --symbol '<symbol>' \
  --taxonomy dei --concepts EntityCommonStockSharesOutstanding \
  --as-of '<cutoff>' > '<scratch>/share-facts.json'
```

Add the configured credentials file. Verify the exact accession, unit scale and
share date in the filing. SEC company facts omit custom and class-specific
contexts; read the primary filing or issuer release when the concept is absent
or incomplete, especially for foreign issuers and multiple classes. Never use
EPS weighted averages, authorized/treasury shares, or one class as the whole
issuer. See the [SEC API scope](https://www.sec.gov/search-filings/edgar-application-programming-interfaces).

Select the archived **raw, unadjusted USD price** for the matching security as
described above; keep it separate from split-adjusted trend/liquidity history.
An alternative reliable quote needs its own verified observation/publication
availability by the cutoff. A newly retrieved historical bar without that
evidence cannot be backdated. A bar close describes its completed interval,
not an invented exact last-trade timestamp. Respect SIP delay and cutoff.

Check filings and issuer announcements from the share date through that price
timestamp for splits, issuance, repurchases, exchanges and class conversions.
`actions` can corroborate this review but does not cover every share-count change.
Count completed changes once; an announced ATM capacity or buyback authorization
is not an executed share change. Verify economic equivalence across classes and
the ADR ratio. Ordinary dilution risks remain separate; unresolved prefunded
warrants, differing economic claims, missing classes or unquantified material
changes make this simple calculation unsuitable.

Preserve share observation dates, source availability, price time and review
sources separately. A document read after the cutoff can establish an earlier
fact only with verified pre-cutoff availability. Never relabel a newly retrieved
live market cap as historical evidence.

## Calculate a disclosed-share estimate

Prepare a JSON list, one object per issuer, with these fields. Source URLs are
HTTPS references to the inspected evidence, not a substitute for opening it.

| Field | Contents |
|---|---|
| `symbol`, `issuer_cik` | Verified quoted symbol and SEC issuer identity. |
| `share_count_basis` | `outstanding_common`. |
| `classes` | Each has `class_id`, `shares`, `uncertainty_shares`, `precision_basis`, `observed_on` (date), `available_at`, `source_url` and `conversion`. Include the full issuer's common share base. |
| `conversion` | `kind` (`same_common`, `equivalent_common`, `adr`), `shares_per_price_unit`, `available_at`, `source_url`, `basis`. `same_common` matches `price.class_id` and has ratio 1. Economic equivalence and ADR ratios require sourced explanations. |
| `price` | `symbol`, `class_id`, `usd`, `currency: "USD"`, `adjustment: "raw"`, `as_of`, `available_at`, `source_url`. |
| `review` | `through`, `available_at`, `source_urls`, `basis`; `latest_filings_checked`, `all_common_classes_included`, `corporate_actions_checked` are true; `unquantified_changes` and `unsupported_complexity` are false only when the inspected evidence justifies it. |
| `changes` | Events after the base count's observation date: `class_id`, `kind` (`share_delta` or `split`), `value`, `effective_at`, `available_at`, `source_url`. Use an empty list when no changes were found. |

All timestamps require timezones. `review.available_at` is the latest underlying
source availability, not the time the agent performed the analysis. `through`
is the exact price timestamp through which the sources were checked. A delta adds/subtracts outstanding shares and a
split multiplies them; do not include events already reflected in the base count.
The helper orders events by their effective times; same-day base/event ambiguity
or simultaneous changes with uncertain ordering require a newer verified base.
For ADRs the ratio is underlying shares per quoted depositary unit, so divide by
it. The helper cannot infer missing events or determine economic equivalence.
`uncertainty_shares` records the disclosed count's precision: zero only for an
exact count, otherwise a source-supported whole-share uncertainty with an
explanation in `precision_basis`. Changes must be exactly quantified; unknown
rounding or material changes remain unresolved.

```bash
python3 '<skill>/scripts/market_capitalization.py' --input '<scratch>/capitalization-plan.json' \
  --as-of '<cutoff>' > '<scratch>/market-caps.json' 2> '<scratch>/capitalization-status.json'
```

The offline helper emits compatible rows on standard output and per-symbol
diagnostics separately. Exit 2 can retain usable rows for other stocks; inspect
both outputs before passing them to `market_universe.py liquidity`. It makes no
network calls or vault writes. Retain the calculation's input and digest in the
research evidence; the consumer verifies the arithmetic and identity.

The formula sums each adjusted outstanding class count divided by its quoted-unit
ratio, then multiplies by the raw price. The method is
`latest_disclosed_shares_price_proxy`, with `estimate: true`. The default maximum
share age is **120 days**, a declared freshness policy rather than proof that the
count stayed unchanged. Older or materially uncertain counts need better evidence,
not a guessed haircut or a larger age limit just to pass the filter.

Report **estimated issuer size based on disclosed shares**, never exact current
cap or a guaranteed lower bound. `estimate_range_usd` propagates only the declared
count precision, not all possible uncertainty in actual capitalization. The size
filter stays unresolved if this range crosses its threshold; material uncertainty
outside that range must also be resolved. Size does not establish fair value, fully diluted valuation, purchase
readiness or the absence of dilution risk.
