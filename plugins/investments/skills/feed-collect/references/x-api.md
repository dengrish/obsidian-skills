# X collection: setup, storage and recovery

Read before initial setup, paid access, or recovery. This adapter collects public
X posts through the official API; it does not use the browser or ShadowAlpha.

## Accounts and credentials

Default input: `Investments/x-accounts.md`. Use one line per account:

```markdown
- [x] @selected_account
- [ ] @paused_account
```

Checked entries are enabled, not completed tasks; the collector never checks
them off. Handles are case-insensitive and limited to X's letters, digits and
underscores. Duplicate or malformed entries are setup errors. Initial official
user lookup binds a stable user ID to its existing account-note filename. A
renamed account must not be silently replaced with a new owner of its old handle.
Use the helper's supported identity syntax for a known, verified rename; never
guess an ID. Unchecking an account pauses acquisition without deleting history.

For a renamed account whose numeric ID has already been verified, retain that
identity explicitly, for example `- [x] @new_handle <!-- x-user-id: 123456 -->`.
The example ID is illustrative, not a source to collect. The original filename
stays attached to that ID. Do not resolve an old handle again to rebind its note
to whoever now owns the name.

Create an X developer app approved for the intended personal collection and
research use, with appropriate paid access. Use app-only bearer authentication
for public accounts. Configure `X_BEARER_TOKEN` in the environment or a user-owned
private regular JSON file (mode `600` or `400`, no symlinks or additional links).
For example, create a separate `x-api.json` in the user's chosen private keys
folder. Its one key is `X_BEARER_TOKEN`; add the value locally. Do not add X keys
to a market-only credentials file, whose schema intentionally rejects them.
API credentials, stored post bodies and collector state do not belong in Git.

The [official timeline guide](https://docs.x.com/x-api/posts/timelines/integrate)
documents `GET /2/users/{id}/tweets`, incremental IDs and pagination. Every timeline
request uses `exclude=retweets,replies`, including resumed pages, to avoid retrieving
those posts. This also excludes self-replies and thread continuations; quote posts
remain unless they are also replies. The documented timeline ceiling with replies
excluded is **800 recent posts**, not a complete historical archive. A normal
first run starts with seven days. The explicit `--latest N` sample can reach
older posts within the provider's available timeline, subject to its separate
paid-read budget. A long offline interval or provider visibility limits can
leave gaps even when pagination ends.

## Initial samples and incremental updates

`--latest N` establishes an initial sample target for each account, not a limit
on the lifetime size of its note. Future runs continue forward from the saved
boundary. Once established, that target is fixed: repeat the same `--latest N`
or omit it for ordinary forward updates. A different N is rejected; it does not
reset the sample or silently resume intentionally omitted older history.
Stop when the target is reached, the provider is exhausted or a budget
is reached; report those outcomes separately. Replies, reposts and duplicates
consume a returned-row budget even when they do not count toward the target.
The API's minimum page size is five. When fewer originals remain to reach the
target, the final page can contain up to four extra originals; retain purchased
posts and report the actual count rather than discard them or claim exactly N.
Initial-sample status and forward completion are reported separately. When a
saved older window finishes, continue toward the current requested cutoff while
budgets permit. A budget stop reports the completed and requested cutoffs and
its deferral reason; reaching the initial target alone does not establish that
the newest requested interval has been checked.

Preserve incomplete pages already collected by an older version. Do not reset
an account or restart a page to switch to sampling. A completed older window
may lack its original lower bound; `--history-before` supplies that verified
UTC boundary when older history is explicitly needed. Use retained request
evidence to establish it, never guess it from the newest saved post or today's
date. Once recorded, the boundary can be resumed without reentering it. An
unknown boundary limits older-history extension; it does not authorize repeat
paid reads. Completing a sample leaves older-history omission explicit.

Saved pagination tokens can expire. A rejected or expired token remains an
explicit recovery/gap condition; never restart from the newest page automatically
or describe the interrupted interval as complete. [X pagination notes](https://docs.x.com/x-api/fundamentals/pagination#notes)

## Paid-read discipline

The helper's request and post limits are hard bounds for each invocation, not a
promise of a dollar charge. Check [current X pricing](https://docs.x.com/x-api/getting-started/pricing)
and set a spending limit in the developer console. User lookup and other resource
types may be billable too. Avoid extra profile/metric refreshes and referenced-post
expansions; repeated manual runs must use the same saved state. New timeline
windows request only primary-post attachment metadata in the same response;
see [attachments](attachments.md). Do not change a saved page's query schema
mid-pagination to add media fields.

Defaults are 25 requests and 1,000 returned posts per invocation, shared across
the roster. `--max-requests` and `--max-posts` can set a smaller explicit budget.
Requests rotate among accounts so a busy feed does not consume every run. New
accounts also need an initial user lookup, which counts against the request
budget. Deferred or unfinished accounts remain visible in the result.

- Resolve a handle once, then collect by its stable user ID.
- Retain successful pages before generating notes. Publication is offline.
- Resume the saved window and next page after a budget stop or interruption.
  For ordinary collection, advance the completed boundary after exhausting that
  window. An initial sample may instead stop at its target and advance to its
  sample cutoff while preserving the unconsumed older cursor as intentionally
  omitted history. Preserve
  its exclusion filter; an incompatible saved filter blocks further requests
  instead of silently restarting or reusing a cursor with a different query.
- Deduplicate post IDs locally, including repeated rows returned by X. This
  prevents duplicate records; it cannot undo a provider's charge for duplicates
  that the provider itself returned. Unexpected reply/repost rows are not added
  to the account record, but still count toward the returned-post budget and
  cursor advancement so they do not cause repeated requests.
- Keep the request's safe filtering/paging parameters and its non-overlapping
  row-accounting totals after processing. Source text and credentials do not
  belong in these operational receipts. Old request records without this
  breakdown remain unknown; do not invent historical exclusion counts.
- Do not automatically retry a network timeout or an interrupted in-flight
  request. The server may already have returned billable data.

An account note contains source text and operational metadata only. Source text
is displayed literally so embedded HTML, wikilinks or instruction-like content
cannot become commands or change the note's generated structure. Record both
source creation time and first retrieval time in UTC. Prefer returned complete
long-post text to a short preview, without reconstructing missing text. Preserve
reference IDs and available attachment metadata. The collector downloads its own
photo attachments and directly linked PDFs under [the attachment rules](attachments.md).
It does not fetch quoted posts separately, transcribe videos or crawl linked pages.
Readable post text uses ordinary Markdown paragraphs with source markup escaped
and original line breaks preserved; source metadata is collapsed below it.
Render HTTP(S) URLs as explicit clickable links without changing their original
destinations or relying on automatic URL detection. Preserve query strings and
fragments; use matching API URL entities to distinguish URL punctuation from
surrounding prose when available. No link expansion or network request is
needed for formatting, and source link syntax cannot activate a remote embed.
The heading records publication time. First retrieval and last check times,
exact source text and the original timestamp spelling remain in state, without
repeated retrieval/check labels in the note. A new edited version records its own retrieval time rather than
claiming its changed wording was available when an older version was captured.

Current X documentation uses inconsistent `tweet`/`post` field names across
pages. The helper uses a fixed request schema and accepts supported response
aliases. A schema error is an access limitation; do not spend another request
trying undocumented field combinations automatically. Verify a small first
authenticated request against [the endpoint reference](https://docs.x.com/x-api/users/get-posts)
before treating the provider integration as live-tested.

## Durable state and uncertain requests

`Investments/Sources/.feed-collect/` holds source records, pagination, stable
identities and publication receipts. It is durable, private collection state.
Back it up together with the notes; do not copy it to plugin caches or put it in
an owned scratch directory. The account notes are readable projections of this
state. Deleting a note does not require downloading its sources again.

The state file has a 64 MiB capacity. Before a paid request, the helper reserves
headroom for its 8 MiB raw-response limit; this is conservative rather than a
guarantee because JSON serialization can expand received data. A capacity
preflight failure makes no API request. If received data nevertheless exceeds
the state limit, the helper preserves the full attempted state in the private
`preserved_recovery` directory it reports, leaving the prior state file intact.
Preserve that directory and resolve capacity/recovery before continuing. Do not
delete the state, repeat the request or use `resolve-pending --outcome retry`
to replace data already captured in that recovery file.

`status` and `plan` are offline. `publish` retries note generation from stored
data without network access. If publication finds a conflicting note or newer
editor change, retain both the source state and the occupant and report the
conflict. Never adopt or overwrite an unrelated note merely because its handle
matches. A stale lock must be reconciled against its owning process, not blindly
deleted while another run may be active.

An unresolved in-flight request blocks a silent replay. Inspect its status and
the provider's request/billing evidence. The helper's `resolve-pending` command
requires an explicit outcome. Retrying with a possible repeat charge requires
the user's authorization and its explicit acknowledgment flag. Abandonment must
remain a recorded gap, never a claim of complete collection. Do not use this
recovery command as routine error handling or raise budgets automatically.

## Edits and removals

Incremental new-post collection does not establish that previously stored posts
still exist unchanged. X's [content-compliance policy](https://docs.x.com/developer-terms/policy)
requires offline content to track edits and removals, including protected or
suspended content. This collection is maintained source material, not immutable
investment recommendation history. Do not preserve deleted text indefinitely in
notes, state, raw-response caches or recovery copies contrary to those rules.

`reconcile` is the explicit maintenance path: it checks specified stored IDs and
requires `--allow-paid-reread`. Treat this separately from new-post acquisition;
it can incur another read charge. Record its result and remove or update only
content whose changed status is positively established; an API outage or generic
authorization failure is not evidence that each post was deleted. Do not claim
full ongoing deletion synchronization from a one-off reconciliation. Before an
unattended long-lived archive is activated, establish an authorized maintenance
cadence/budget or verify access to X's compliance events. Never promise both
permanent verbatim retention and zero repeat reads.

For example, after replacing the placeholders with a selected account and known
post IDs, run one bounded check:

```bash
python3 '<skill>/scripts/feed_collect.py' reconcile --vault '<vault>' \
    --account '<handle>' --ids '<comma-separated-post-ids>' \
    --allow-paid-reread --credentials-file '<private-x-credentials.json>'
```

Paused accounts remain eligible for maintenance. A lookup of an old version can
return old text alongside a newer ID in its edit history. The helper then removes
the superseded body and records the latest ID; it does not purchase that version
automatically. The same explicit maintenance command can retrieve a latest ID
already established by the stored edit history. An arbitrary unknown ID remains
outside this command's scope. Old versions never replace a newer recorded one.

Blogs, newsletters and Substack are future adapters, not fallbacks. Implement
their own stable item IDs, conditional retrieval, source timestamps, licensing
and paid-access boundaries before collecting their bodies. Other skills may
later consume these source notes for interpretation; this adapter does not.
