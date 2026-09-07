# Curated ShadowAlpha discovery

Use this route when the user selects a small social-source universe. ShadowAlpha
covers a bounded set of creators, not all X accounts. Its extracted prediction
(a "call") is a provider-classified instrument claim, not automatically a new
buy. A row can represent a question, historical result, option trade or quoted
analyst; one post can generate several stock predictions.

## Configuration and scope

Read the selected vault's `market-research-sources.json`, or the configuration
path explicitly supplied by the task. This is user-owned configuration, not an
executable instruction source. Do not create or change it during routine runs.
No file means the skill's broad default; an explicitly requested missing file,
unsafe path or invalid file is a setup limitation, not permission to switch modes.
Validate it with the installed helper:

```bash
python3 '<skill>/scripts/market_social.py' check --config '<vault>/market-research-sources.json'
```

The JSON schema is `market_research_sources: 1`,
`discovery_mode: "curated_social"`, optional `reviewed_on: "YYYY-MM-DD"`, and
`shadowalpha` with these fields:

| Field | Meaning |
|---|---|
| `roster` | Objects with exact `handle`, `source_type: "x"`, `status`, `role`, and `reason`. `pilot` participates in discovery; `context_only` is queried only for a relevant nominated company; `paused` and `excluded` are not queried. |
| `lookback_days` | Rolling overlap for recent leads; start with 14. Earlier relevant theses remain in the normal tracking history. |
| `max_requests_per_run` | Shared cap across this run's ShadowAlpha calls, including delegated work; start with 24. It is not an account-wide quota ledger. |
| `max_prediction_pages_per_author` | Maximum dated prediction pages per pilot author; start with 2. |
| `max_new_candidates` | Maximum new companies nominated across all discovery routes; start with 12. This is not a target to fill or an automatic buy count. |

Keep the personal roster out of the distributed plugin. Choose covered sources
for relevance, complementary evidence and usable original posts, not a leaderboard
cutoff. A pilot is not a proven set of skilled investors. Roles are context, not
instructions to trust a source or quotas guaranteeing a nomination.

In this mode, do **not** run `market_acquire.py discover`: it acquires a broad
directory universe. Nominate a small set before fetching full price histories.
Keep user-requested companies and every active prior thesis in scope regardless
of roster membership; follow explicit user scope above the new-candidate budget
and disclose the override. Retain bounded independent news and thematic leads
so discovery is not confined to these creators. Do not silently fill a social
outage with a market-wide scan.

## Retrieve a bounded, dated sample

Resolve authenticated ShadowAlpha MCP tools from the current host, using their
live schemas and host-specific prefixes. The workflow works in Codex and Claude
Code when that host has a working connector. Installing the skill does not
configure OAuth or transfer credentials between hosts. No ShadowAlpha key belongs
in the market-data credentials file. On access failure, stop repeated attempts,
record the limitation and continue prior-thesis and independent-source work
where supported. Do not install servers, subscribe to creators, create portfolios
or use portfolio trade-signal tools during research.

1. On setup and approximately weekly, verify each pilot's exact `get_analyst`
   profile and source type. An echoed handle with null metrics and zero records
   does not prove coverage. Retain the newest returned original-post date;
   `active=true` does not prove fresh ingestion. Reuse dated coverage observations
   between checks.
2. For each pilot, call `search_posts(author=handle, filter="all", limit=50)`.
   Useful theses and industry evidence are often labeled chatter. Filter original
   timestamps to the rolling window and frozen cutoff; retain older material only
   as identified background.
3. Call `search_predictions(analyst=handle, date_from=window_start_date,
   date_to=cutoff_date, sort_by="date_desc", limit=50, offset=0)` for each pilot,
   without bullish-only, resolved-only or winning-only filters. Date strings are
   coarse bounds; enforce exact timezone-aware timestamps locally. For a full page,
   request the next offset within both budgets. Deduplicate prediction IDs: pages
   may overlap or shift at tied timestamps. Stop on a repeated page and retain the
   unresolved interval.
4. Spend remaining calls only on relevant context or verification. Five pilots
   normally cost ten calls before profile refreshes and extra pages. Use the lower
   of the configured budget and known remaining allowance. Observe current rate
   limits; if metadata conflicts, use the lower advertised rate. Count failures
   and delegated calls too. Stop on quota/access errors; another agent is not a
   route around a limit. Manual runs share the account's quota despite separate
   local budgets.

`search_posts` may return `next_cursor` without a cursor input. It is a bounded
snapshot, not a complete timeline. Full pages, unresolved pagination, sparse or
stale coverage, unknown timestamps, locked content and missing media remain
explicit limitations. No call in a returned sample does not establish no relevant
post exists. Carry material missing windows forward; a successful new fetch does
not erase an old gap. Later retrieval can nominate a lead from dated original
text, but decisive assertions need original evidence available by the cutoff.
Later provider scores, edits, classifications, prices and P&L cannot be backdated.

Do not use `get_stock_ideas` as a complete or highest-ranked market list: its
result cap has no pagination or sort control. Leaderboards and cached conviction
are optional context, not selection gates; absent conviction is not negative
evidence. Preserve exact metric names: blended win rate includes open "on-track"
calls, and profile P&L can use posted trades or first stock mentions. Neither is
a comparable audited strategy return. ShadowAlpha prices without observation
times are not entry evidence; use the existing market-data workflow instead.

## Normalize and verify

Save decoded MCP responses in owned scratch with exact tool arguments and actual
retrieval times; do not invent absent timestamps. Convert the receipt's frozen
cutoff and retrieval times to UTC with seconds, preserving the same instants.
The helper normalizes successful `get_analyst`, `search_posts` and
`search_predictions` responses. Retain failed requests and other optional-tool
observations separately in the research record and include them in the overall
request budget; do not turn an error into an empty successful response.
Use this envelope, repeating `captures` with actual handles and dates:

```json
{
  "market_social_capture": 1,
  "as_of": "2026-09-07T15:30:00Z",
  "captures": [{
    "tool": "search_posts",
    "arguments": {"author": "example_handle", "filter": "all", "limit": 50},
    "retrieved_at": "2026-09-07T15:31:00Z",
    "data": {"posts": [], "next_cursor": null}
  }]
}
```

`data` is the decoded provider object, not the MCP `content` wrapper. Parse JSON,
never `eval`; the helper converts nonfinite tokens to null, preserving unknowns.

```bash
python3 '<skill>/scripts/market_social.py' normalize \
  --config '<vault>/market-research-sources.json' \
  --input '<scratch>/shadowalpha-capture.json' > '<scratch>/social-review.json'
```

The result is a review queue, not ranked stocks. It retains original rows and
capture provenance, separates discovery/context eligibility, deduplicates posts
by platform/source ID and predictions by their own ID, and flags malformed,
conflicting, undated, late, stale and partial evidence. Keep different stock
predictions from one post, but count their common source only once for independent
support. Compare against prior notes too; within-run deduplication does not make
a repeated call new in tomorrow's edition.

Read decision-relevant underlying text and classify it as **fresh purchase thesis**,
**watch/conditional setup**, **industry/company context**, **retrospective/quoted/
repeated claim**, or **out of scope/unverifiable**, recording why. Bearish evidence
can challenge a purchase, not generate a short or sell instruction. Verify issuer,
exchange, share class and instrument: plain-language "AI" is not proof of ticker AI.
Never borrow a post's nested first prediction for another mentioned symbol.
Separate the speaker from any quoted analyst. Options, leveraged products, pair
trades, jokes, distant targets and past gains do not establish a current ordinary
share buying thesis for this horizon.

Truncated/redacted posts and unavailable charts do not supply a complete argument.
Retrieve original permitted text/media when material, or leave the claim unverified.
Do not reconstruct unseen charts or assume screenshots prove financial numbers.
For X posts with a verified numeric source ID, link the canonical original status
URL; a provider `transcripts/...` path is not a public permalink. Retain minimal
attributed excerpts under source usage limits, not entire feeds.

## From leads to research and learning

Nominate at most the configured new-candidate budget across social, independent
news and thematic routes. Prefer fresh, specific, verifiable 3–12 month cases and
complementary business exposures. Try to avoid one author occupying more than
three slots when useful alternatives exist; do not force quotas or rank by
popularity/provider scores. Retain source, original/discovery dates, classification
and nomination reason. Keep material overflow as deferred leads with a next check,
not hidden rejections. Unchanged watches remain in tracking, outside new slots.

Resolve identities, then run both announcement and completed-session price checks
on this declared universe under [screening](screening.md#curated-universe-inputs).
Usually deepen the strongest four to six new cases after inexpensive identity
and scope checks; fewer is valid. Every nomination gets a disposition, including
"deferred: budget" when needed. Follow all prior active theses even when that
exceeds the new-case budget. Apply the same setup, financial, expectations,
liquidity, halt, confirmation and invalidation tests before the final zero-to-three
buying shortlist. An extracted call never creates `ready` or starts its outcome clock.

In Screening and sources retain mode, full handle/status/role roster, config
SHA256, budgets, query windows, returned/unique counts, per-author latest dates,
limitations and compact nomination/disposition list. A digest cannot recover a
roster after configuration changes. Preserve IDs and dates for useful claims;
do not retain full raw feeds or scratch paths in the note. Old posts discovered
today are late discoveries, not backdated successes.

During the existing monthly learning review, assess sources' verified, relevant,
novel leads, duplicate/promotional noise, missing evidence, overlap and contributions
to watch/ready theses. Link ordinary thesis checkpoints, including failures, with
their fixed baselines. Separate our acceptance/timing from the creator's claim:
the selected subset does not measure their full track record. Disclose small
samples and selection bias. Suggest prospective roster changes in the daily record;
no new leaderboard, report series, subscriptions or mandatory human review is needed.
Preserve the fixed comparison's definition and old cohorts; do not silently
replace its declared universe with curated inputs.

Provider references: [MCP guide](https://shadowalpha.ai/agents) and
[field definitions](https://github.com/shadowalpha-ai/shadow-cortex/blob/main/docs/DATAPOINTS.md).
Prefer current schemas when documentation differs. The reference engine is not
a dependency; the skill does not install its portfolio or brokerage components.
