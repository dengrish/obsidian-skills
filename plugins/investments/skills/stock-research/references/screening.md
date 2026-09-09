# Feed intake and reproducible stock checks

Use [stock_feed.py](../scripts/stock_feed.py) to read `feed-collect` output, then
[market_screen.py](../scripts/market_screen.py) for repeatable price calculations
on the nominated stocks. Both are offline helpers. Neither nominates an investment,
fetches posts or decides that a stock is purchase-ready. Apply the
[research method](research-method.md) to their evidence.

## Read the collected feeds

```bash
python3 '<skill>/scripts/stock_feed.py' context --vault '<vault>' --cutoff '<cutoff>' > '<scratch>/feed-context.json'
```

The JSON snapshot identifies the checked roster, per-account publication and
coverage status, eligible posts and originating-post groups. It reads the saved
collection state and verifies the corresponding published source notes. Only
checked accounts in `Investments/x-accounts.md` and feeds in
`Investments/rss-feeds.md` supply new ideas; old untracked sources may remain in
collection state without authorizing their use. Either roster can be used alone. Feed notes,
state, attachments and the roster remain unchanged. Missing state, divergent note
bytes or malformed records are reported, never repaired by this consumer.

Default X intake covers the preceding 72 hours by post date. RSS intake uses
the observation time of each saved article revision, so a newly collected older
article or revision is not silently skipped. Preserve its separate publication
date; first observation does not make an old catalyst current.
Pass `--since '<earlier timestamp>'`
when previous research records identify a still-relevant unreviewed saved window.
It can recover only material that feed-collect retained; this does not request
more X history. Publication time, observation availability and the cutoff constrain
which post text is usable. Current note metadata or a pre-cutoff post date alone
cannot prove that later text was known at an earlier cutoff.

RSS articles have a stable `rss:<URL hash>` identity and a separate
`rss:<URL hash>@<revision hash>` evidence ID. Use the exact evidence ID in coverage
journals and retained-source requests. Unchanged polling does not create new work;
a new revision requires checking what changed, with unchanged arguments linked to
their earlier assessment. Do not substitute the current article for an earlier
revision at a historical cutoff. A summary-only feed or missing image may leave
the thesis unavailable. Preserve that limit rather than supplying imagined text.
An X post linking to an RSS article and the article itself may be the same argument,
not independent confirmation; retain both source identities when reconciling them.

Inspect each account's missing, stale, partial and attachment diagnostics. A
newly followed account without a note was not checked successfully; an account
with zero eligible posts and adequate collection coverage is a different result.
An unreadable chart cannot establish its plotted values. Usable accounts can
still supply ideas while another account is incomplete, but the report must retain
the limitation. Do not describe rejected or omitted evidence as a clean empty scan.

Read the actual post Markdown and distinguish original text, added quote commentary
and referenced/reposted content. Origin groups help avoid double counting; they
do not establish the truth or independence of a claim. Preserve original post IDs,
permalinks, collecting/original authors and timestamps beside material findings.
Read retained self-replies in publication order with their parent/conversation
links, within the same author's evidence. A shared conversation ID does not prove
common authorship or a complete thread. The intake snapshot marks missing parent
or root context; do not invent it or count continuations as independent endorsers.
Keep every post's coverage disposition, while one assessment can address the
linked argument across several posts. Earlier filtered intervals remain a source
gap, not proof that an author posted no supporting reasoning.
Use the research method's bounded linked-source follow-up for a post whose
argument is in a public article or saved attachment. A teaser is not proof of a
buying case, but inaccessible material is not evidence that no argument exists.
A recent repost of an old claim is a newly collected reference, not a fresh
company catalyst; retain both times and treat the original as dated background.
Use source links rather than temporary snapshot paths in published notes. Retain
only the decisive attributed claim and verification; do not republish full feeds.

Reconcile eligible posts with the durable [coverage record](coverage.md) and
verified earlier assessments. Every eligible new substantive stock idea receives
a standard initial assessment; there is no top-three or top-ten research quota.
Several new arguments about the same security can share one assessment, provided
each argument is addressed and its source relationship retained. An unchanged
argument reuses its earlier assessment by link. A new material argument about an
already covered stock requires evaluating the change, not restarting all research.

Screen out passing mentions, duplicates and positively ineligible securities with
the applicable evidence or earlier-assessment link. Missing identity, price or
financial data is an unresolved check, not proof of ineligibility. Do not count a
ticker mention, a screen result or a capacity deferral as a completed assessment.
The coverage guide governs unresolved work, original queue age, retry conditions
and same-day reuse. Preserve processed post IDs and dispositions in the daily
record; keep account/post, distinct idea, security and completed-assessment counts
separate. Overlapping windows do not require a mutable collection cursor.

## Prepare targeted price evidence

Freeze the nominated identities and reasons before price ranking. Include earlier
unfinished work, prior active theses due for checks and explicitly requested
companies as labeled origins, never unmentioned stocks found during primary-source
verification. Reuse adequate cutoff-eligible measurements instead of reacquiring
every existing stock note. Resolve exchange, issuer, share
class and currency using issuer/exchange evidence; `market_data.py symbols` may
help resolve identity, but downloading a directory does not expand the candidate
set. Retain unresolved identities and unmeasured names as gaps.

Retrieve original `sessions` and `prices` envelopes for that set and a named
benchmark through the [data guide](data-access.md). Build the existing custom
`market_screen_input: 1` contract:

- `as_of`: the frozen evidence cutoff.
- `universe`: `name: feed-nominated-v1`, `membership_date`, `source`,
  `instruments`, and `discovery_complete`. Each instrument has `symbol`,
  `exchange`, `security_type` (`common_stock` or `adr`) and `currency: USD`.
  Describe dated feed membership separately from verified security identity;
  false coverage cannot become complete by dropping unresolved names.
- `benchmark`: the selected broad benchmark; preserve matching observations.
- `prices` and `sessions`: the original full response envelopes, retaining
  queries, timestamps, warnings, completeness flags and all relevant bars.
- `rules`: state every filter explicitly as below, plus any separately verified
  eligibility criteria. A display limit is not a research limit.

Use `min_price: 10`, `min_average_daily_notional: 25000000`,
`require_above_ma50: false`, `require_above_ma200: false`,
`require_positive_relative_return_6m: false`,
`sort_by: "relative_return_3m"`, and `limit` equal to the full verified roster
length. These preliminary settings leave recovery setups visible; they do not
relax readiness or establish an optimized investment rule. A feed argument can
still warrant assessment when a preliminary filter fails; record that failure
and apply the same final eligibility requirements.

```bash
python3 '<skill>/scripts/market_screen.py' --input '<scratch>/screen-input.json' > '<scratch>/screen.json'
```

Skip the calculator when no identities are eligible; do not add filler stocks.
Daily inputs require SIP, USD, split adjustment and the cutoff's explicit mapping
date. Calendar/history coverage must support the 200-session average, its change
from 20 sessions earlier and the 12-month reference session; a short candidate list
does not shorten a lookback. Assess relevant sector benchmarks with matching
conventions separately. Sorting uses declared metrics and stable identity ties,
not a confidence score or predicted return. The 128 MiB input limit is a safety
boundary, not permission to discard inconvenient candidates or evidence.

Do not run the broad acquisition coordinator for this workflow. Retained helpers
for directory-based inputs and historical comparisons do not authorize a second
idea source. Complete price coverage of a nominated subset is not complete market
coverage or proof that every followed account published a full timeline.

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
verify regular-session turnover. For candidates whose eligibility needs
verification, use the bundled calculator:

```bash
python3 '<skill>/scripts/market_universe.py' liquidity \
  --prices '<scratch>/eligibility-minute.json' --sessions '<scratch>/sessions.json' \
  --as-of '<cutoff>' --symbols '<candidate-symbols>' \
  --market-caps '<scratch>/market-caps.json' > '<scratch>/eligibility.json'
```

Minute evidence must be SIP, USD and split-adjusted, using the same mapping date.
The calculator filters against actual calendar opening/closing times, including
early closes, and lists missing expected minutes separately for each session.
The minute starting at the close is excluded because it can mix auction and
extended-hours trades; no auction turnover is added separately. VWAP and volume
can use different eligible trade sets, so their product estimates trading
activity rather than measuring exact traded dollars.

The default liquidity filter is a **$25 million** average over **20 completed
sessions**. With complete source responses and requests covering the entire
calendar window, observed nonnegative minute notional divided by all 20 sessions
is a lower bound on this defined proxy. A sufficient bound can verify the filter
even with missing minutes. The full-window average remains unavailable, and
`complete` remains false; read `liquidity_threshold_verified` separately.
An insufficient bound with gaps is unknown, not a failed filter. Missing minutes
are never treated as zero trading, and the denominator never shrinks. Partial
responses or shortened requests cannot establish the bound. A source's `complete`
flag alone does not establish interval coverage.

The optional market-cap file is a JSON list of rows with `symbol`,
`market_cap_usd`, `currency: "USD"`, timezone-aware `as_of` and `available_at`,
`source_url` and `basis`. The basis identifies the issuer/share classes and ADR
ratio where applicable; do not multiply an ambiguous share count by a convenient
price. Measurement must be at least as recent as the reference session, and
measurement ≤ availability ≤ cutoff. When a dated cap is unavailable, use the
[capitalization workflow](capitalization.md) to acquire outstanding shares,
check subsequent changes and calculate a labeled disclosed-share estimate with
`market_capitalization.py`. Its share observation date remains distinct from the
price measurement date. Without adequate sourced evidence, capitalization stays
unresolved. Preserve the reported/estimated basis; size and liquidity filters do
not establish a buying opportunity.

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
measurements and source observations needed to reproduce assessed candidates or
decisive exclusions.
A digest identifies input; it does not preserve that input. Keep relevant dated
values in the note or an already authorized durable source, with source URLs and
adjustment definitions. Do not cite temporary JSON paths after scratch cleanup
or copy entire licensed feeds into the note. The existing outcome journal remains
the record of subsequent recommendation performance.

## Retain the earlier fixed comparison

Follow the [comparison guide](comparison-strategy.md) for existing cohort outcomes
and due monthly records. The feed-nominated subset is discretionary and cannot
replace a previously independent comparison universe. If matching predeclared
inputs are not already available, record a due formation as unavailable with the
scope mismatch. Do not fetch a broad universe for this diagnostic or tune a new
comparison after seeing today's candidates. Earlier cohorts remain unchanged.
