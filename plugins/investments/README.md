# Investments

[investments:feed-collect](skills/feed-collect/SKILL.md) records timestamped
original posts, quote posts, reposts and self-replies from selected public X
accounts, excluding replies to others, with one maintained account note in
`Investments/Sources/X/`. Thread continuations retain parent/conversation links;
missing or older roots are not fetched automatically.
It preserves source content without summaries,
sentiment labels or buying recommendations. Attached photos are saved in
`Sources/Images/` and embedded locally; direct PDFs are saved in `Sources/PDFs/`
and linked. The collector owns those files through durable receipts.
Videos and animated media remain labeled links to supplied playable URLs or the
original posts; their files are not downloaded or transcribed.
Account notes contain only properties and timestamped posts. Properties include
stable note creation and update dates and a short sourced owner description;
source metadata, collection status and skill provenance stay in private state.
Reposts keep their own timestamps and original-source links; returned snippets
may be truncated, and referenced originals are not fetched separately.

Public RSS/Atom feeds enabled in `Investments/rss-feeds.md` produce one note per
article and a publication index in `Investments/Sources/RSS/`. The collector keeps
the supplied text, tables, links and local images without summarizing it. It
tracks unseen articles and revisions separately from X's three-day policy;
conditional requests avoid unchanged transfers where the publisher supports them.
Summary-only feeds and incomplete archive coverage remain explicit limitations.
RSS video and embedded-content URLs remain links too. Current notes can receive
formatting repairs from saved source without revising earlier evidence archives.
Image/PDF collection processes all available saved attachments by default,
subject to per-file safety limits and any explicit run budget. Both adapters
can finish attachment downloads without rereading posts or feeds. An image shown
only as a remote link is incomplete; an original-source link can remain beside
its local embed.

[investments:stock-research](skills/stock-research/SKILL.md) finds buying
opportunities in liquid U.S.-listed stocks for a 3–12 month momentum horizon,
starting from feed-collect’s published X notes and RSS articles. Run feed-collect first,
then stock-research; the research skill does not collect posts or replace missing
feeds with an independent discovery scan. It maintains a note for every
substantively analyzed stock, including rejected and watch ideas, under
`Investments/Stocks/`. These contain the latest assessment and dated history links.
It records concise daily decision briefs, detailed research, and later evaluations
of earlier recommendations in an Obsidian vault. Holdings reviews, sell
recommendations and trade execution are outside this skill's scope.

Every eligible new substantive idea receives a standard initial assessment.
Active theses receive dated monitoring, while deeper reassessment follows changed
evidence or a due review. The daily brief still highlights at most three ideas;
that is not a research quota. Visible, validated coverage tables in each new daily
report preserve processed posts, unfinished work and retry dates. They distinguish
complete research from queued or blocked checks and buying readiness. Earlier
reports remain unchanged; their prose backlog requires an explicit initial review.

Research distinguishes an interesting business, a completed assessment and a
verified entry opportunity. It follows material public documents linked by saved
posts without crawling new feeds, tests whether short-term claims fit the 3–12
month horizon, and explains both the leading choices and their shared business
risks. Monthly learning also reviews discovery gaps and research bottlenecks;
source popularity and repeated claims are not independent confirmation.

## Setup

Read [runtime setup](shared/RUNTIME.md) and the skill's
[data-access guide](skills/stock-research/references/data-access.md).
Both skills' core helpers use Python 3.10+ and the standard library, including system timezone
data. Targeted financial retrieval feeds the offline screener with momentum,
relative strength, trend and liquidity-proxy inputs for feed-nominated stocks.
Shortlist helpers separately verify regular-session coverage and sourced
market-cap eligibility; passing a screen is not a buying recommendation. Optional
SEC filing/section extraction uses pinned EdgarTools; its setup is in the
data-access guide. PDF/image packages and the `knowledge` plugin are not required.
Install the whole package to preserve its local helper paths.

For direct X collection, maintain `Investments/x-accounts.md` and configure
read-only API credentials under the
[X API guide](skills/feed-collect/references/x-api.md). Routine collection gathers
all available eligible posts from the past three days, using saved progress and
cached responses to avoid repeat reads. Previously saved older posts remain in
the notes. There is no default request or returned-post cap; explicit budgets
and provider limits can leave partial coverage. An explicit `--latest N`
establishes a per-account historical sample and can reach older posts; omitting
it restores the three-day policy. Attachment downloads
have their own budgets and can resume from saved URLs without X post rereads.
An ambiguous paid request is recorded and stops instead of silently
retrying. Collection state in `Investments/Sources/.feed-collect/` is durable,
not temporary scratch. Source edits and removals use a separate reconciliation
procedure; account notes are maintained records, not immutable research
editions. For blogs/newsletters, configure the separate
[RSS/Atom adapter](skills/feed-collect/references/rss-atom.md). It needs no X API
key; public feed bodies are supported, subscriber credentials and article-page
crawling are not. Preserve its `.rss-collect/` state alongside the article notes.
Collection does not interpret content. Published source notes and the collector’s read-only coverage
receipts are the input to stock-research. Uncollected, stale, incomplete or
unpublished source data remain explicit limitations; a feed mention is not a
buy recommendation.

Credentials remain outside the repository, plugin and vault. An explicitly
selected private JSON credentials file can be passed to the bundled data
script with `--credentials-file`; otherwise it uses configured environment
variables. Read-only data access covers SEC, Nasdaq, Alpaca, Alpha Vantage and
FRED, subject to account access and coverage limits. Credentials are never
included in plugin installation or publication.

Use the same selected Obsidian vault as `knowledge` if desired. Published
dated stock-research records remain immutable; earlier market-research editions
remain readable under their original names. Maintained stock notes do not replace
this evidence history. Scheduled research runs create one daily edition;
user-requested fresh reviews create timestamped manual editions under the
[note format](skills/stock-research/references/note-format.md#editions-and-retries).
Both share the same thesis and outcome history. Private run receipts allow a
started review to finish across midnight within eight hours; completed declared
checks bind to the exact final draft without requiring human review.
A prospective nominee comparison freezes the actual new idea pool, including
ready, watch, rejected and unfinished work. Its immutable records live under
`Investments/Snapshots/Nominees/`; daily and monthly notes summarize fixed future
windows against matching SPY observations without relabeling initial decisions.
Existing independent momentum cohorts retain their original evidence under
`Investments/Snapshots/Comparisons/` and their due checkpoints; automatic new
formations are retired. Existing inline records remain readable.
Selected estimate observations persist as immutable source JSON under
`Investments/Snapshots/Estimates/`, with separate verified availability receipts
under `Investments/Snapshots/EstimateReceipts/`. Legacy observations stay intact;
an embedded save timestamp alone does not prove availability at an earlier cutoff.
A targeted acquisition coordinator batches the explicitly justified nominees
through daily/minute history with exchange calendars, current prices and estimate
capture, shares a request budget, reuses archives and respects provider cooldowns.
History and its availability receipts persist under `Investments/Snapshots/PriceHistory/`;
acquisition alone does not prove regular-session liquidity or a price trigger.
Each new thesis defines its price test's measurement, session, duration and any
later-hold condition; historical ambiguity remains explicit. Both scheduled and manual reviews freeze their
cutoff only after preparation completes. The daily start remains 08:30 Pacific;
late captures cannot change an already frozen edition. Stock notes
keep usable current assessments separate from conflicts in older report links,
and new updates preserve the exact original report as evidence.
Exact SEC Form 4/4-A retrieval adds selective insider context without extra
credentials or parser dependencies; no buying score is inferred from a filing.
Each skill uses `Reviews/<skill>-suggestions.md` under the
[shared protocol](shared/SUGGESTIONS.md).

Scheduling is separate from installation. The intended sequence is feed-collect
then stock-research; each invocation remains separate unless the user explicitly
schedules both. When requested, invoke
`investments:stock-research` daily at 08:30 `America/Los_Angeles` (11:30
`America/New_York`), following daylight saving time. Preserve the selected
vault and credentials configuration in the host's task; installing this plugin
does not create or change a schedule.

This product uses the FRED® API but is not endorsed or certified by the Federal
Reserve Bank of St. Louis. Use of its FRED integration is subject to the
[FRED API Terms of Use](https://fred.stlouisfed.org/docs/api/terms_of_use.html).

## Developing and packaging

Canonical sources are maintained in
[obsidian-skills](https://github.com/dengrish/obsidian-skills). Edit the source
skill and shared helpers there, rebuild, and release this plugin independently.
Do not edit generated runtime copies or installed caches.
