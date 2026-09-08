# Investments

[investments:feed-collect](skills/feed-collect/SKILL.md) records timestamped
original posts, quote posts and reposts from selected public X accounts, excluding
replies, with one maintained account note in `Investments/Sources/X/`.
It preserves source content without summaries,
sentiment labels or buying recommendations. Attached photos are saved in
`Sources/Images/` and embedded locally; direct PDFs are saved in `Sources/PDFs/`
and linked. The collector owns those files through durable receipts.
Account notes contain only properties and timestamped posts. Properties include
stable note creation and update dates and a short sourced owner description;
source metadata, collection status and skill provenance stay in private state.
Reposts keep their own timestamps and original-source links; returned snippets
may be truncated, and referenced originals are not fetched separately.

[investments:stock-research](skills/stock-research/SKILL.md) finds buying
opportunities in liquid U.S.-listed stocks for a 3–12 month momentum horizon,
starting from feed-collect’s published account notes. Run feed-collect first,
then stock-research; the research skill does not collect posts or replace missing
feeds with an independent discovery scan. It maintains a note for every
substantively analyzed stock, including rejected and watch ideas, under
`Investments/Stocks/`. These contain the latest assessment and dated history links.
It records concise daily decision briefs, detailed research, and later evaluations
of earlier recommendations in an Obsidian vault. Holdings reviews, sell
recommendations and trade execution are outside this skill's scope.

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
editions. Blogs and newsletters are not yet supported. Collection does not
interpret content. Published account notes and the collector’s read-only coverage
receipts are the input to stock-research. Uncollected, stale, incomplete or
unpublished account data remain explicit limitations; a feed mention is not a
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
A fixed monthly momentum comparison is recorded separately within those notes,
with bulky evidence in verified immutable `Investments/Snapshots/Comparisons/` attachments.
Existing inline comparison records remain readable.
Selected estimate observations persist as immutable source JSON under
`Investments/Snapshots/Estimates/`, with availability times for future comparisons.
A small ordered estimate preflight reuses recent observations and records a
conservative provider cooldown after quota failure; it never invents historical
consensus or changes an established cutoff.
For a fresh manual review, bounded raw-price capture can precede the research
cutoff too. Verified observations are archived and reused for dated size checks;
late captures cannot be backdated into a fixed scheduled edition. Stock notes
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
