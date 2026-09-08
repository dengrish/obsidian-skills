# Dated company-size evidence

Use this procedure for the shortlist's **$2 billion issuer-size filter** when a
reliable dated USD market cap is not already available. Reuse verified filings,
prices and earlier research; do not query every feed mention or spend estimate
requests merely to populate a size field.

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

Obtain a timestamped **raw, unadjusted USD price** for the matching security, no
older than the latest completed reference session. Use a bounded `prices` request
with `--adjustment raw`, or a reliable timestamped quote; keep it separate from
split-adjusted trend/liquidity history. A bar close describes its completed
interval, not an invented exact last-trade timestamp. Respect SIP delay and cutoff.

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
