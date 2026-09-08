# Retrieving market evidence

Use [market_data.py](../scripts/market_data.py) for repeatable retrieval, then
apply the [research method](research-method.md) to interpret the results and
open issuer releases or filings for shortlisted ideas. The helper retrieves
evidence; it does not rank stocks, calculate a track record, or publish notes.
Core retrieval works with Python 3.10+ in either host without extra packages.
The optional `sec-filing` command uses pinned EdgarTools for local HTML parsing.
Use the [offline screening guide](screening.md) for repeatable calculations on
saved price/calendar responses.

## Setup and access checks

| Source | Credential names | Commands and purpose |
|---|---|---|
| SEC EDGAR | `SEC_USER_AGENT`: application/name and a real contact email | `sec-company`: identity and filings; `sec-facts`: selected reported XBRL facts; optional `sec-filing`: one exact filing or section; `sec-ownership`: exact Form 4/4-A XML |
| Nasdaq Trader | None | `symbols`: current exchange directories; `halts`: halt RSS |
| Alpaca | `ALPACA_API_KEY`, `ALPACA_SECRET_KEY` | `prices`: historical bars; `actions`: corporate actions; `sessions`: paper exchange calendar; `news --provider alpaca`: bounded news sample |
| Alpha Vantage | `ALPHA_VANTAGE_API_KEY` | `news` (default provider): news and provider sentiment; `earnings`: current earnings calendar; `estimates`: current EPS/revenue estimates |
| FRED / ALFRED | `FRED_API_KEY` | `fred-series`: metadata and observations at a daily vintage; `fred-releases`: source release-date calendar |

API keys are sufficient; do not request account passwords. Supply the named
values through the process environment or an explicitly selected private JSON
file. Pass the file's path as `--credentials-file` after the command; the bundled
helper loads it directly, so no separate credential launcher is needed. The same
interface works in Codex and Claude on macOS and Linux.

The file contains one JSON object using only the credential names in the table.
Values must be nonempty strings without control characters; omit unavailable
credentials. Duplicate or unknown names are rejected. Keep the file outside the
plugin, repository and vault, owned by the current user, with mode `600` (or
read-only `400`) and no symlinks or hard links. A private parent folder with mode
`700` is recommended. Use a direct path without `..` traversal. The reader rejects
unsafe files, files over 32 KiB and files that change during reading before
contacting a provider. It never creates or changes the file.

An explicit file is authoritative for all named credentials: an omitted key
stays missing rather than falling back to an inherited environment value.
Without the option, environment-based configuration works as before. Loading
does not modify the parent process environment. Use the same selected file for
both offline checks and retrieval; no directory or credential store is searched
automatically. Do not open the file's contents into the conversation, execute it
as shell code, or paste values into arguments, history, notes or logs.

The helper does not load `.env` files, persist credentials, create accounts,
or change subscriptions. Setup and key rotation remain separate from research;
report missing or blocked configuration instead of repairing it during a run.
FRED requires the user's own [free account](https://fredhelp.stlouisfed.org/fred/account/fred-account-features/register/)
and [API key](https://fred.stlouisfed.org/docs/api/api_key.html); do not use its
documentation's demonstration key. Host-specific secure storage is separate
from this portable helper. Follow the [FRED API terms](https://fred.stlouisfed.org/docs/api/terms_of_use.html).

The examples below show both configuration routes. Add the same
`--credentials-file` option to any retrieval command when using a file. Never
put key values in this option. Public Nasdaq queries need no credentials and
can omit it.

```bash
python3 '<skill>/scripts/market_data.py' check
python3 '<skill>/scripts/market_data.py' check --credentials-file '<credentials.json>'
python3 '<skill>/scripts/market_data.py' check --credentials-file '<credentials.json>' --live --source alpaca
```

The default check is offline: it reports missing/invalid configuration without
printing values or making requests. A live check probes only the selected source,
or all configured sources if no source is selected. It consumes requests and
tests a small sample: SEC submissions, Nasdaq directories, old Alpaca SIP bars,
one Alpha Vantage earnings calendar, or FRED DGS10 metadata and a short prior-day
vintage sample. A successful sample does not establish
access to every endpoint, real-time data, or complete market coverage. Missing
credentials should limit only the affected source; continue with other usable
sources and host web tools, recording gaps.

### Optional filing parser

The offline `check` also reports `optional_dependencies.sec_filing_parser`.
A missing or incompatible EdgarTools installation does not fail the core-source
check. For deeper filings, install the tested parser in the selected isolated
environment during setup, not automatically during a scheduled research run:

```bash
'<venv>/bin/python' -m pip install -r '<skill>/scripts/requirements-filings.txt'
```

Use that interpreter for the data helper. This installs the Python library,
not an external skill, MCP server or another research framework. No additional
API key is needed. Existing `SEC_USER_AGENT` configuration still applies, and
web reading remains available when the optional dependency is unavailable.

## Retrieval plan

Use `market_data.py` with the configuration above for the evidence needed
at each stage. `market_notes.py` separately supplies history, due work and guarded
publication under `SKILL.md`; the sibling data modules are imports, not additional
commands to run. This is a plan for relevant retrieval, not a requirement to call
every endpoint on every day. Reuse adequately dated evidence when appropriate;
record sources used, material unavailable access and why a relevant check was
skipped in Screening and sources. A successful setup probe is not today's research.

| Stage | Commands and use |
|---|---|
| Review window and session | `sessions` for the last/next sessions and their opening/closing boundaries; verify exceptional closures against an exchange source. Reuse this calendar for price filtering and due outcome events. |
| Feed nominations and identity | `stock_feed.py context` reads local collection outputs. Use `symbols` only when useful for resolving a nominated instrument; preserve exact provider symbols, security type and dated identity evidence. Directory membership does not add candidates. |
| Candidate announcements | `news --provider alpaca --symbol '<symbol>'` for a bounded candidate-specific news window when configured; use `news --provider alpha_vantage` selectively for additional coverage within its account quota. Use `earnings` for upcoming scheduled risks, then verify timing and results on issuer pages. Neither news feed must duplicate the other on every run. |
| Candidate price history | `prices` for the nominated stocks, prior active theses and benchmarks over matching completed sessions, then the offline [screener](screening.md). Preserve its defined filters, coverage and exclusions. Its daily notional proxy is preliminary; verify regular-session liquidity separately for the shortlist. |
| Intraday assessment | On open-market runs, use `prices --timeframe 1Min` or a timestamped host quote for the shortlist's morning reaction. Respect feed delay and the cutoff; keep snapshots separate from completed-session signals, and compare partial volume only with matching historical session/time windows. |
| Shortlist and readiness | `sec-company` for relevant filings, then `sec-facts` for comparable reported fundamentals and optional `sec-filing` for the exact filing's narrative/tables. For expectations that matter, retrieve `estimates` and use the dated-snapshot workflow below. When insider activity changes the case, inspect an exact accession with `sec-ownership`. Open material cited sections and issuer releases; a parser is not a factual verifier. Check `halts` and current issuer/exchange notices before first readiness or when a trading-status concern arises; a current empty feed does not reconstruct an earlier cutoff or clear an older unresolved halt. |
| Corporate actions | `actions` when validating adjustments, unexplained price discontinuities, instrument changes or outcome inputs. Its process-date records need issuer corroboration; choose the relevant history and keep original raw observations. |
| Macro context | `fred-releases` for relevant upcoming releases and `fred-series` for a small dated set of rates, credit, employment or inflation observations when they affect a thesis. Verify fresh announcements with the releasing agency. |
| Outcome work | Use `sessions`, `prices` and relevant `actions` for due baselines/checkpoints returned by `market_notes.py outcomes`; retain fixed events, matching benchmark inputs and availability evidence. Do not refetch completed observations unless corrections or changed evidence require it. |

Use host search/page-reading for primary releases, transcripts, agency
announcements and material counterarguments about the nominated companies.
Social posts already come from `feed-collect`; do not query X, ShadowAlpha,
Reddit or Stocktwits as an independent discovery pass or fetch missing source
posts through paid APIs. An inaccessible post remains a collection limitation.
Missing market access limits the affected check, not the existence of an idea.

## Scope of retained acquisition helpers

The bundled directory/acquisition utilities remain available for inspecting
previous saved inputs and maintaining historical comparisons. The current skill
uses feed nominations only: do not run `market_acquire.py discover` or collect a
broad price/news universe. Use targeted commands for the nominated stocks,
benchmarks and due historical outcome instruments. A provider response containing
other symbols does not nominate those companies.

## Query and result contract

Use explicit timestamps with seconds and a timezone, such as
`2026-09-04T11:30:00-04:00`. Replace example dates with the actual review window.
Save large JSON output in the run's owned scratch directory and read the full
relevant subset; truncated terminal output is not the full result.

```bash
python3 '<skill>/scripts/market_data.py' symbols > '<scratch>/symbols.json'
python3 '<skill>/scripts/market_data.py' sec-company --symbol AAPL --as-of '2026-09-04T11:30:00-04:00' --since '2026-09-01' > '<scratch>/filings.json'
python3 '<skill>/scripts/market_data.py' prices --symbols 'AAPL,MSFT,SPY' --start '2025-09-01T00:00:00-04:00' --end '2026-09-04T11:15:00-04:00' --adjustment split > '<scratch>/prices.json'
python3 '<skill>/scripts/market_data.py' prices --symbols 'AAPL,MSFT,SPY' --start '2026-09-04T09:30:00-04:00' --end '2026-09-04T11:15:00-04:00' --timeframe 1Min --adjustment split > '<scratch>/intraday.json'
python3 '<skill>/scripts/market_data.py' news --symbol AAPL --since '2026-09-03T16:00:00-04:00' --as-of '2026-09-04T11:30:00-04:00' > '<scratch>/news.json'
python3 '<skill>/scripts/market_data.py' news --provider alpaca --symbol AAPL --since '2026-09-03T16:00:00-04:00' --as-of '2026-09-04T11:30:00-04:00' --sort LATEST --limit 10 --include-content > '<scratch>/alpaca-news.json'
python3 '<skill>/scripts/market_data.py' fred-series --series DGS10 --start '2026-01-01' --end '2026-09-03' --vintage-date '2026-09-03' > '<scratch>/treasury-yield.json'
python3 '<skill>/scripts/market_data.py' fred-releases --start '2026-09-04' --end '2026-09-11' > '<scratch>/macro-releases.json'
```

The SIP price examples end 15 minutes before the scheduled cutoff. Daily bars
still exclude the current date; the minute request supplies a separate delayed
intraday snapshot. Filter it to verified session boundaries and retain each
observation time. A later retrieval does not move the edition's evidence cutoff.

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
quota tracking. The acquisition coordinator shares them across its stages; the
estimate preflight additionally reuses snapshots and records provider cooldowns. Requests use verified HTTPS and fixed read-only endpoints, do
not follow redirects or inherit HTTP proxies, and never call order/holding APIs.

Retain relevant dated values, citations, query/feed/adjustment information and
limitations in the daily Research record under the [note format](note-format.md).
Do not paste entire feeds into notes or leave references pointing to scratch.
Retrieval timestamps and digests support provenance; they do not prove that an
article, revised dataset, or financial estimate was known at an earlier cutoff.

## Exact filing and section extraction

Select an accession from `sec-company` that is available by the research cutoff.
Pass that exact accession and CIK to `sec-filing`; no latest-filing fallback is
allowed. For older accessions, include `--since` and an adequate page budget so
their metadata can be found. Replace the example with the selected filing:

```bash
python3 '<skill>/scripts/market_data.py' sec-filing --cik 320193 --accession '0000320193-23-000106' --as-of '2026-09-04T11:30:00-04:00' --since '2023-11-01' > '<scratch>/filing-text.json'
```

The adapter verifies the accession against SEC submissions and fetches only its
validated primary HTML document through the existing bounded SEC transport.
EdgarTools parses that HTML locally in a short-lived worker with no API keys.
Its temporary library directories are cleaned; no user EdgarTools cache or
installed skill is changed. Parsing is limited to 30 seconds in addition to the
HTTP budget. The command neither downloads linked documents/images nor uses
EdgarTools' network, latest-company, or persistent-data interfaces.

The response identifies the filing, acceptance/filing-date availability basis,
original URL, parser version, detected `data.sections`, source/text digests and
rendered Markdown. Use an exact returned `section_id` when requesting `--section`;
generic aliases such as `Item 1` are rejected because different 10-Q parts can
reuse the same item number. Missing sections are
explicitly incomplete. The parser's sections and tables are extraction aids,
not guarantees of completeness or normalized financial statements. Use the
original document for omitted or ambiguous content, especially table units and
footnotes; earnings exhibits may require opening a separate issuer release.

Output is paged by `--offset` and `--max-chars` (default 20,000, maximum 100,000).
Follow `data.next_offset` while needed, keeping the same filing, section and
cutoff, and require unchanged source and full-text digests when joining pages.
Literal credential echoes are redacted before parsing; a warning identifies this
change, and the text digest then describes the redacted rendering. If entity
decoding or joined HTML text would reconstruct a credential, extraction fails
without returning text.
Excerpts remain incomplete rather than silently claiming the whole filing was
read. Character positions are locations in rendered text, not PDF page numbers.
Retain only decision-relevant excerpts and calculations in the daily note, with
the durable SEC URL and section; do not publish the entire filing or cite scratch.

## Dated estimates, not reconstructed expectations

For a small, already-justified shortlist, prefer the bounded capture helper to
ad hoc calls. Prepare an ordered JSON list of objects containing exact `symbol`,
`period` (fiscal period-end), `horizon` (`fiscal quarter` or `fiscal year`) and
`reason`. Order by tracked decision relevance and proximity of the next verified
event, not by the ease of obtaining a response. Keep the plan in owned scratch.

```bash
python3 '<skill>/scripts/market_capture.py' capture --vault '<vault>' --plan '<scratch>/estimate-plan.json' --work-dir '<scratch>' --max-calls 3 --reuse-hours 24
```

Add the selected `--credentials-file`. On a **fresh manual** run this optional
preflight occurs before `market_notes.py prepare`; the helper returns only after
its latest save is available at a real whole-second cutoff. An immediate prepare
can therefore use the capture without backdating it. Do not reopen an already
frozen edition. For a fixed scheduled or manual cutoff, pass `--as-of '<cutoff>'`;
new late captures remain available only to subsequent editions.

The helper reuses sufficiently recent matching snapshots before spending calls,
requests at most the stated number of uncached symbols in priority order, and
stops on the first quota error. A secret-free, immutable local cooldown receipt
under `Investments/Snapshots/ProviderStatus/` prevents repeated calls on subsequent
runs. Its conservative retry delay is **not** a verified provider reset time or
an account-wide usage meter. Other clients may consume the same account quota.
Existing eligible snapshots remain usable during cooldown. No subscription, key,
login or scheduled task is changed; failed access stays a bounded coverage gap.

Alpha Vantage's [EARNINGS_ESTIMATES](https://www.alphavantage.co/documentation/#earnings-estimates)
supplies quarterly/annual EPS and revenue estimates, analyst counts and reported
revision summaries. It uses the existing Alpha Vantage key; endpoint access and
quotas still need checking. Select the fiscal periods relevant to a leading or
tracked thesis, especially before earnings; do not query every screened stock.

```bash
python3 '<skill>/scripts/market_data.py' estimates --symbol IBM --period '2026-09-30' --as-of '<cutoff>' > '<scratch>/estimates.json'
python3 '<skill>/scripts/market_estimate_history.py' save --input '<scratch>/estimates.json' --vault '<vault>' --period '2026-09-30' --horizon 'fiscal quarter'
python3 '<skill>/scripts/market_estimate_history.py' history --vault '<vault>' --as-of '<cutoff>' --symbol IBM
python3 '<skill>/scripts/market_estimate_history.py' compare --older '<older-snapshot.json>' --newer '<newer-snapshot.json>'
```

Replace the example period with the actual thesis period and add the selected
`--credentials-file` to retrieval. Saving is separate from the read-only data
helper: it preserves one selected period/horizon in an immutable JSON file under
`Investments/Snapshots/Estimates/`, with observation/save times and source digest.
It excludes arbitrary provider text, request credentials and the rest of the feed.
Exact retries reuse the original snapshot; collisions never overwrite evidence.
These are source records, not daily analyses or a mutable database. Link the
specific snapshot and summarize only decision-relevant values in the daily note.

The provider gives no historical vintage or publication time. A fiscal period end
is not an availability date, and its trailing-window revision figures are current
provider claims, not independently preserved past observations. `--as-of` therefore
marks a later retrieval incomplete for that cutoff. When `coverage_complete` is
true, the snapshot helper can still preserve it for a **later** review; do not use
it in the earlier edition or shift that edition's cutoff. History exposes only
records whose observation and first-save times are available by the requested
cutoff. Do not replace a missing historical snapshot with current estimates.

Compare the same instrument, fiscal period, horizon and definitions. The helper
reports changes in preserved provider values, with percentages only from a
positive earlier value; missing values stay unavailable. Currency and EPS
accounting basis can be absent: independently establish them and comparable
corporate-action treatment before calling a change an economic revision or
calculating an earnings surprise. Keep provider estimates distinct from issuer
guidance and actual results. A quota/entitlement error leaves an explicit gap;
do not change subscriptions or repeatedly retry during the run.

## Selective insider-disclosure context

Use `sec-company --forms '4,4/A'` to discover relevant issuer accessions, then
retrieve only the exact filing needed to check a claim:

```bash
python3 '<skill>/scripts/market_data.py' sec-ownership --cik '<issuer-cik>' --accession '<accession>' --as-of '<cutoff>' --since '<earliest-filing-date>' > '<scratch>/ownership.json'
```

This standard-library XML reader uses the same SEC contact and bounded transport;
it does not require EdgarTools or an additional account. It verifies accession,
issuer, form and cutoff, preserving reporting owners, relationship, derivative and
non-derivative rows, transaction dates, ownership type, reported values, footnotes,
amendment context and the 10b5-1 indicator when present. Inspect the original XML
and relevant footnotes; `null` or an unparsed value is not zero. Keep a transaction
date separate from when the filing became available.

Under [SEC Form 4 instructions](https://www.sec.gov/files/form4.pdf), code `P`
includes private as well as open-market purchases. Awards, tax withholding and
option exercises are different events. Do not multiply a joint filing's rows by
its owner count, equate derivative exercises with discretionary common-stock
buying, or treat a 4/A as either an additional purchase or a complete replacement
without reconciling its corrections. A 10b5-1 checkbox supplies plan context,
not proof of discretionary timing. Use corroborated, material activity as context;
no automatic insider-buy score or readiness promotion follows from a filing.

## Source-specific interpretation

**SEC.** No API key is needed, but provide a real identifying contact. The helper
spaces requests below the SEC's ten-per-second ceiling; do not run parallel
processes that collectively exceed it. It resolves a current ticker to a company
CIK, retrieves submissions, and checks filing dates and acceptance times at the cutoff.
Without `--since`, coverage is the recent submissions block, not all history;
with it, relevant older submission pages are retrieved within `--max-pages`.
Current ticker mappings and company metadata are not historical security masters.
Acceptance can precede the assigned filing date: some evening submissions are
not disseminated until the next business day. The helper then uses conservative
date-only availability: future filing dates are excluded, and same-day timing
remains unproven. See the [SEC's filing-status guidance](https://www.sec.gov/submit-filings/filer-support-resources/how-do-i-guides/determine-status-my-filing).
Even same-day acceptance is not an exact public-dissemination timestamp. Open the
selected primary filing and verify publication evidence for timing-sensitive claims.

The `sec-facts` command retains concept, taxonomy, units, periods, filing dates and accession
identities. It includes reported versions, not a computed comparable financial
series: distinguish quarterly/YTD/annual periods, amendments and restatements;
do not sum duplicate versions. Same-day facts need a known pre-cutoff accession
acceptance no earlier than the assigned filing date; otherwise they are omitted
and coverage is incomplete. Use
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
and has different volume. Neither default establishes a real-time
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
The price command supports individual or comma-separated provider adjustments,
such as `split,spin-off`; `raw` and `all` must be used alone. The offline screener
still requires exactly `split`, so another adjustment basis is a separate analysis.
[Bars documentation](https://docs.alpaca.markets/us/reference/stockbars) and
[market-data FAQ](https://docs.alpaca.markets/us/docs/market-data-faq).

`actions` filters by **process date**, not announcement or ex-date; current
complete records can arrive late. Confirm issuer announcements separately.
Returned records must match the requested symbols, process dates and any
explicit `--types` filter. A mismatching page is rejected; validated earlier
pages remain available with incomplete coverage.
`sessions` uses the read-only paper calendar, including early closes and New
York daylight saving time. Its currently documented range is 1970–2029; use
another verified exchange calendar for later targets such as five-year reviews.
[Corporate actions](https://docs.alpaca.markets/us/reference/corporateactions-1)
and [calendar documentation](https://docs.alpaca.markets/us/reference/legacycalendar).

`news --provider alpaca` checks a bounded explicit window, with an optional
single-symbol filter and article bodies via `--include-content`. It retrieves
up to 50 articles per page, following cursors within `--max-pages` (default ten).
An unexhausted cursor, conflicting article revision or failed page means partial
coverage; previously validated pages remain available. Exact article-ID duplicates
are counted once, while different IDs sharing a URL remain distinguishable.
Narrow the window to investigate further, retaining and deduplicating article IDs.
An article may have no publisher URL; the helper preserves it with `url: null`
and its provider ID. Verify material claims through the issuer or another
primary source before citing them as evidence.
It does not apply the bars' 15-minute guard: the provider decides news access.
Compare a historical window with an explicit recent window to test entitlement.
Only a returned article's creation time within the last 15 minutes demonstrates
recent publication delivery; an empty HTTP 200 response or a fresh update to an
old story does not. Sort order uses **update time**. Publication/update times
and current text do not establish a historical text snapshot, and rows updated
after the cutoff are excluded. Broad results include stocks and crypto and are
not a liquid U.S. stock screen. REST access does not verify streaming access or
complete Benzinga coverage. [News endpoint](https://docs.alpaca.markets/us/reference/news-3).
The optional URL follows Alpaca's [official market-data schema](https://raw.githubusercontent.com/alpacahq/cli/main/api/specs/market-data-api.json).

**Alpha Vantage.** Budget around the documented free allowance of 25 calls per
day across the account; the helper does not track usage by other processes or
automatically retry quota failures. `news` accepts one symbol per request or a
general/topic query. Multiple provider tickers and topics have AND semantics;
separate symbol requests are needed for a watchlist. News is capped at 1,000
items with no page cursor. The helper enforces the requested output limit even
if the provider returns extra articles. A response reaching the requested cap is incomplete;
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

**FRED / ALFRED.** The `fred-series` command retrieves one series' metadata and observations
in native units and frequency. Both real-time bounds are pinned to the explicit
`--vintage-date`; observation dates identify measured periods, not release dates.
Missing `.` observations become null, never zero. Preserve units, seasonal
adjustment, vintage, retrieval timestamp and the provider's metadata. Compare
observations within the same vintage when calculating growth; compare separate
dated requests when studying revisions. A pinned real-time interval can be clipped
to the query date and is not each observation's original release or revision date.

Vintages have **daily**, not intraday, resolution. A same-day vintage retrieved
later does not prove availability by an intraday cutoff. For historical context,
a prior-day vintage is a conservative source-date proxy, not proof of exact FRED
ingestion. Use archived pre-cutoff snapshots or separate agency publication-time
evidence for same-day releases. Series-level `last_updated` is an update on FRED's
server, not every observation's first availability. FRED/ALFRED may lag the source;
ALFRED describes updates as typically within one business day. Verify fresh
morning announcements with the releasing agency.
[Vintage semantics](https://fred.stlouisfed.org/docs/api/fred/realtime_period.html),
[observations](https://fred.stlouisfed.org/docs/api/fred/series_observations.html),
and [update timing](https://alfred.stlouisfed.org/help).

`fred-releases` retrieves dates for all releases or `--release-id`, including
scheduled dates without data. Dates are source publications, not confirmed FRED
availability or release times. Future events are risks to monitor, not reported
outcomes; a current calendar cannot reconstruct its earlier announced schedule.
Both commands have a total record limit and page budget and mark partial results
explicitly. Check requested-history coverage; available history varies by series.
[Release dates](https://fred.stlouisfed.org/docs/api/fred/release_dates.html).

Use a small relevant subset for macro context, not an automatic buying signal:

| Series | Context |
|---|---|
| [DGS2](https://fred.stlouisfed.org/series/DGS2), [DGS10](https://fred.stlouisfed.org/series/DGS10) | Daily Treasury yields; calculate curve differences only on matching dates |
| [BAMLH0A0HYM2](https://alfred.stlouisfed.org/series?seid=BAMLH0A0HYM2) | Daily close high-yield credit spread; verify available history before comparing historical ranges |
| [ICSA](https://fred.stlouisfed.org/series/ICSA) | Weekly initial unemployment claims |
| [PAYEMS](https://fred.stlouisfed.org/series/PAYEMS), [UNRATE](https://fred.stlouisfed.org/series/UNRATE) | Monthly payrolls and unemployment |
| [CPIAUCSL](https://fred.stlouisfed.org/series/CPIAUCSL), [PCEPILFE](https://fred.stlouisfed.org/series/PCEPILFE) | Monthly headline CPI and core PCE price indexes; index levels are not inflation rates |

For implementation or troubleshooting, the CLI delegates to
[public data](../scripts/market_public.py), [filing extraction](../scripts/market_filings.py), [prices](../scripts/market_prices.py),
[news/calendars](../scripts/market_news.py), [macro data](../scripts/market_fred.py), and the shared
[request transport](../scripts/market_http.py). These sibling modules have
offline self-tests but no separate operational retrieval interface.
