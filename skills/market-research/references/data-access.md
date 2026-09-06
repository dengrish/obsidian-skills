# Retrieving market evidence

Use [market_data.py](../scripts/market_data.py) for repeatable retrieval, then
apply the [research method](research-method.md) to interpret the results and
open issuer releases or filings for shortlisted ideas. The helper retrieves
evidence; it does not rank stocks, calculate a track record, or publish notes.
It works with Python 3.10+ in either host and needs no extra Python packages.

## Setup and access checks

| Source | Local environment variables | Commands and purpose |
|---|---|---|
| SEC EDGAR | `SEC_USER_AGENT`: application/name and a real contact email | `sec-company`: identity and filings; `sec-facts`: selected reported XBRL facts |
| Nasdaq Trader | None | `symbols`: current exchange directories; `halts`: halt RSS |
| Alpaca | `ALPACA_API_KEY`, `ALPACA_SECRET_KEY` | `prices`: historical bars; `actions`: corporate actions; `sessions`: exchange calendar through the paper endpoint |
| Alpha Vantage | `ALPHA_VANTAGE_API_KEY` | `news`: news and provider sentiment; `earnings`: current earnings calendar |

API keys are sufficient; do not request account passwords. Configure secrets
locally in the environment of the process that runs the skill, including a
scheduler when applicable. Do not paste their values into command arguments,
shell history, notes, suggestion logs, or the repository. The helper does not
load `.env` files, persist credentials, create accounts, or change subscriptions.

```bash
python3 '<skill>/scripts/market_data.py' check
python3 '<skill>/scripts/market_data.py' check --live --source alpaca
```

The default check is offline: it reports missing/invalid configuration without
printing values or making requests. A live check probes only the selected source,
or all configured sources if no source is selected. It consumes requests and
tests a small sample: SEC submissions, Nasdaq directories, old Alpaca SIP bars,
or one Alpha Vantage earnings calendar. A successful sample does not establish
access to every endpoint, real-time data, or complete market coverage. Missing
credentials should limit only the affected source; continue with other usable
sources and host web tools, recording gaps.

## Query and result contract

Use explicit timestamps with seconds and a timezone, such as
`2026-09-04T09:00:00-04:00`. Replace example dates with the actual review window.
Save large JSON output in the run's owned scratch directory and read the full
relevant subset; truncated terminal output is not the full result.

```bash
python3 '<skill>/scripts/market_data.py' symbols > '<scratch>/symbols.json'
python3 '<skill>/scripts/market_data.py' sec-company --symbol AAPL --as-of '2026-09-04T09:00:00-04:00' --since '2026-09-01' > '<scratch>/filings.json'
python3 '<skill>/scripts/market_data.py' prices --symbols 'AAPL,MSFT,SPY' --start '2025-09-01T00:00:00-04:00' --end '2026-09-04T08:45:00-04:00' --adjustment split > '<scratch>/prices.json'
python3 '<skill>/scripts/market_data.py' news --symbol AAPL --since '2026-09-03T16:00:00-04:00' --as-of '2026-09-04T09:00:00-04:00' > '<scratch>/news.json'
```

Run the helper with a command followed by `--help` for its filters. Each retrieval
returns one JSON object with `market_data: 1`, `operation`, `complete`, and
sanitized `requests` provenance (URL, retrieval time, status, and response
digest/size when available). Retrieved results carry `warnings`, `query` and
`data`, plus `source` metadata where the adapter supplies it. Failed retrievals
instead carry an `error` with a safe code and explanation.
Exit 0 means complete **within the declared query scope**; exit 2 means invalid
input, unavailable access, or incomplete data. Inspect both the JSON and exit
status. A complete directory or selected financial concept is not a complete
investment screen. Live setup checks instead report access to their named sample.

Pagination is bounded and partial earlier pages are retained when supported;
read `pagination`, missing-symbol fields, and warnings before using a result.
Narrow a saturated window or explicitly increase its page budget when useful.
Do not silently discard an error, impute missing prices as zero, or interpret a
failed request as no announcement. The per-command defaults are 100 HTTP attempts
and 120 seconds; `--max-requests` and `--max-seconds` can bound a larger retrieval.
Responses are limited to 20 MiB each. These are local bounds, not shared account
quota tracking. Requests use verified HTTPS and fixed read-only endpoints, do
not follow redirects or inherit HTTP proxies, and never call order/holding APIs.

Retain relevant dated values, citations, query/feed/adjustment information and
limitations in the daily Research record under the [note format](note-format.md).
Do not paste entire feeds into notes or leave references pointing to scratch.
Retrieval timestamps and digests support provenance; they do not prove that an
article, revised dataset, or financial estimate was known at an earlier cutoff.

## Source-specific interpretation

**SEC.** No API key is needed, but provide a real identifying contact. The helper
spaces requests below the SEC's ten-per-second ceiling; do not run parallel
processes that collectively exceed it. It resolves a current ticker to a company
CIK, retrieves submissions, and filters filing acceptance times at the cutoff.
Without `--since`, coverage is the recent submissions block, not all history;
with it, relevant older submission pages are retrieved within `--max-pages`.
Current ticker mappings and company metadata are not historical security masters.
Acceptance time may precede public dissemination, especially near the cutoff.
Open the selected primary filing before treating a timing-sensitive fact as known.

The `sec-facts` command retains concept, taxonomy, units, periods, filing dates and accession
identities. It includes reported versions, not a computed comparable financial
series: distinguish quarterly/YTD/annual periods, amendments and restatements;
do not sum duplicate versions. Same-day facts need a known pre-cutoff accession
acceptance; otherwise they are omitted and coverage is incomplete. Use
`--concepts` or `--taxonomy` when the default small US-GAAP set does not fit the
issuer. Standard entity-wide XBRL excludes many custom/segment disclosures;
missing concepts require reading filings, not inferring zero values.
[SEC API documentation](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)
and [access guidance](https://www.sec.gov/about/developer-resources).

**Nasdaq.** `symbols` combines Nasdaq-listed and other-listed directories, retaining
provider spellings, exchange, ETF and test-issue flags and file timestamps. These
are current listings, not a historical or survivorship-free universe. An ETF flag
of N does not prove common-stock eligibility; inspect security descriptions and
issuer identity, then verify each provider's symbol spelling. `halts --date`
selects the halt date, not a resumption date. The default RSS covers the current
trade-halt day, not every unresolved older halt. Do not poll it more than once a
minute across runs. Resumption fields are scheduled times, not verified actual
trades; an empty feed is not clearance to trade. A current feed cannot reconstruct
the exact halt state known at a past cutoff.
[Directory definitions](https://www.nasdaqtrader.com/trader.aspx?id=symboldirdefs)
and [halt RSS documentation](https://www.nasdaqtrader.com/Trader.aspx?id=TradeHaltRSS).

**Alpaca.** The default `sip` feed requests consolidated historical data ending
at least 15 minutes before the current time; access still depends on account
entitlement. There is no automatic fallback to `iex`, which covers one exchange
and has different volume. Neither default establishes a real-time premarket
quote. Daily bars include only New York dates **before the requested end date**,
even for a historical afternoon cutoff. Choose the following date to include a
desired final day. The actual query end is returned. A `1Min` bar that straddles
the cutoff is excluded. Interval labels are not trade or fill timestamps.

Daily OHLC and volume have different eligibility rules: daily volume includes
eligible extended-hours trades, so it is not regular-session-only dollar turnover.
Minute data also need calendar/session filtering. Preserve the explicit
`--adjustment` basis when comparing prices or returns; adjusted history can
reflect later corporate actions. `--asof` sets ticker mapping, not a knowledge
cutoff. The helper paginates symbol-first results (10,000 bars total per page)
and reports symbols with no usable bars. This does not guarantee every expected
session is present; check calendar gaps before computing signals or outcomes.
[Bars documentation](https://docs.alpaca.markets/us/reference/stockbars) and
[market-data FAQ](https://docs.alpaca.markets/us/docs/market-data-faq).

`actions` filters by **process date**, not announcement or ex-date; current
complete records can arrive late. Confirm issuer announcements separately.
`sessions` uses the read-only paper calendar, including early closes and New
York daylight saving time. Its currently documented range is 1970–2029; use
another verified exchange calendar for later targets such as five-year reviews.
[Corporate actions](https://docs.alpaca.markets/us/reference/corporateactions-1)
and [calendar documentation](https://docs.alpaca.markets/us/reference/legacycalendar).

**Alpha Vantage.** Budget around the documented free allowance of 25 calls per
day across the account; the helper does not track usage by other processes or
automatically retry quota failures. `news` accepts one symbol per request or a
general/topic query. Multiple provider tickers and topics have AND semantics;
separate symbol requests are needed for a watchlist. News is capped at 1,000
items with no page cursor. A response reaching the requested cap is incomplete;
split the time window and deduplicate article URLs rather than assuming all
news was returned. Provider sentiment/relevance scores are discovery metadata,
not calibrated buying probabilities. Original publication time does not prove
that current article text, scores or indexing existed at that time.

`earnings` returns the current calendar, optionally filtered to a symbol. A
date-only schedule is not a confirmed premarket announcement time, and its
estimate is not historical pre-release consensus. A requested historical
`--as-of` therefore cannot establish a verified calendar vintage. General
calendar coverage may include securities outside the selected U.S. universe.
Confirm event timing and actual results with the issuer.
[API documentation](https://www.alphavantage.co/documentation/) and
[free allowance](https://www.alphavantage.co/support/).

For implementation or troubleshooting, the CLI delegates to
[public data](../scripts/market_public.py), [prices](../scripts/market_prices.py),
[news/calendars](../scripts/market_news.py), and the shared
[request transport](../scripts/market_http.py). These sibling modules have
offline self-tests but no separate operational retrieval interface.
