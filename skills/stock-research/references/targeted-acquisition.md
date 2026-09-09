# Targeted acquisition for verified nominees

Use `stock_acquire.py` after reviewing collected feed nominations, prior-stock
work or explicitly named user stocks. It coordinates price history, current raw
prices and estimate archives. It does not discover securities, collect feeds,
request X or ShadowAlpha, scrape pages, establish market capitalization, or
choose investments. Source and quoted-class verification remain research
judgments that precede the plan. This reduces evidence preparation;
current news, fundamentals, filings and the other research checks still follow
the main workflow within the user's existing authorization and budget.

## Prepare one explicit plan

Put an ordered JSON array in the run-owned external scratch directory. Every
nominee must include the fields accepted by the existing price capture plan,
plus nomination origins. Add `history` for the daily/minute windows needed to
evaluate that nominee; reused, still-applicable evidence or an explicit unresolved
limitation can justify omitting it. `estimates` is optional: select fiscal periods only
when they answer a specific question in that stock's review.

```json
[
  {
    "symbol": "AAA",
    "class_id": "A",
    "identity_source_url": "https://example.com/issuer-filing",
    "identity_available_at": "2026-09-07T13:00:00Z",
    "reason": "Verified named supplier in the collected source; assess the stated order catalyst",
    "origins": [
      {
        "kind": "feed",
        "source": "Investments/Sources/X/account.md; https://x.com/i/web/status/1234567890123456789",
        "available_at": "2026-09-08T13:00:00Z"
      }
    ],
    "history": [
      {
        "timeframe": "1Min",
        "start": "2026-08-01T00:00:00-04:00",
        "end": "2026-09-08T00:00:00-04:00",
        "adjustment": "split",
        "asof": "2026-09-08",
        "reason": "Verify regular-session turnover for a new candidate using the latest 20 completed sessions",
        "max_pages": 20
      }
    ],
    "estimates": [
      {
        "period": "2026-11-30",
        "horizon": "fiscal quarter",
        "reason": "The next reported fiscal quarter tests the explicitly stated order thesis"
      }
    ]
  }
]
```

These are illustrative declarations, not a real security or verified issuer
filing. Use the verified provider symbol and stable common-class or ADS identity
from the actual review. Never derive an identity, fiscal period or issuer size
from this example, a ticker match, a theme, a company-name guess or a price.

`origins` contains one to eight `{kind, source, available_at}` records. `kind` is
`feed`, `prior_stock` or `user`; `source` identifies the exact collected item,
prior stock record or explicit user request. A user origin covers only the
stock the user actually named. Availability and identity evidence must precede
the actual clock and, when supplied, the fixed research cutoff. The helper
validates these declarations and carries them into its result; it does not
independently read and verify the cited sources.

Each symbol appears once. Include zero to eight unique fiscal-period/horizon
pairs per symbol, using the existing estimate adapter's supported horizon.
Use the exact source note and retained post permalink, or the exact prior stock
record/user request, in `source`.

### Price history needed for this edition

Choose windows from the actual research question before freezing the cutoff:
daily bars for dated trend/support evidence; minute bars plus the exchange
calendar for regular-session liquidity or a specified intraday test. New
candidates approaching readiness need the [liquidity check](screening.md),
unless a still-applicable verified check is already available. A daily-volume
proxy cannot replace it. Do not fetch minute history automatically for every
rejected or unchanged stock.

Each nominee can declare up to four `history` requests with the exact fields
shown above. `timeframe` is `1Day` or `1Min`; `adjustment` is `raw` or `split`.
The existing screener and regular-session liquidity helper require `split`;
use `raw` only for a separately defined price comparison that needs it. For
liquidity, set `asof` to the intended cutoff's New York date. The calendar covers
through the later of that date and the query end date, within 372 calendar days.
Recheck date compatibility if acquisition crosses midnight; do not relabel the
saved mapping date to make it usable.
Supply timezone-aware start/end timestamps, the verified symbol-mapping `asof`
date, a reason, and a one-to-20 page limit. Windows are bounded to 370 days for
daily bars and 45 days for minute bars. Choose enough completed sessions for
the intended calculation; these calendar-day bounds do not guarantee 20 sessions.
The end must already be at least 15 minutes old for SIP access. Daily queries
include only New York dates before the requested end date; use the following
date to include a desired final day. Keep the actual provider query and its
adjustment basis with any derived calculation.

Matching windows are batched across nominees, with calendars fetched before
bars, using the same transport budget as current prices and estimates. History
runs first so longer retrieval does not age a newly captured current price.
The [history helper](../scripts/stock_history.py) archives the validated calendar
and bars together under `Investments/Snapshots/PriceHistory/`, with a separate
post-publication availability receipt. Its `snapshot` is evidence, not a
liquidity verdict. In a private Python driver using this skill's sibling modules,
`stock_history.payloads(vault, snapshot, receipt, as_of)` verifies exact saved
bytes and cutoff eligibility and returns normalized per-symbol `prices` and
`sessions` envelopes. Pass them to the existing calculation:

```python
saved = stock_history.payloads(vault, row['snapshot'], row['receipt'], as_of)
result = market_universe.liquidity(
    [saved['prices']], saved['sessions'], as_of, [row['symbol']])
```

The export labels its derivation and retains provider request hashes and receipt
availability; it does not fetch again or fabricate an original single-symbol
HTTP response. Use daily exports with the existing screen only when all of its
history, benchmark and mapping requirements are met.
Missing sessions/minutes, incomplete pagination and rejected symbols remain
limitations; no missing bar becomes zero turnover. An all-session daily close
is not an official regular-session close.

The plan holds at most 100 nominees and 256 KiB. That is an implementation
bound, not a coverage quota: retain any further justified nominees explicitly
in the coverage record and a subsequent plan. Do not silently drop names or
split a plan to reset an exhausted request budget.

## Inspect the offline plan, then execute

The default command inspects existing verified archives, estimates missing
coverage and checks saved provider cooldowns. It makes no provider requests,
loads no credentials, creates no vault state and writes no scratch artifacts.
Use the existing hidden `.obsidian-skills-tmp-*` directory outside the vault.

```bash
python3 '<skill>/scripts/stock_acquire.py' \
  --vault '<vault>' --plan '<scratch>/nominees.json' --work-dir '<scratch>' \
  --max-requests 20 --max-estimate-calls 3
```

When acquisition is within the authorized research scope, use the same plan
and budgets with `--execute`. Add the existing credential file option only for
execution; credentials retain the established redaction and loading rules.
`--execute` is the helper's network switch, not a requirement for a separate
human approval when the research request already authorizes these reads.

```bash
python3 '<skill>/scripts/stock_acquire.py' \
  --vault '<vault>' --plan '<scratch>/nominees.json' --work-dir '<scratch>' \
  --max-requests 20 --max-estimate-calls 3 --execute
```

One transport owns the entire execution's HTTP-attempt and elapsed-time
budgets. `--max-requests` defaults to 20, supports zero to 100, and includes the
session calendars, all history pages, every current-price request, every estimate request and transport
retries. `--max-seconds` defaults to 120 and uses the transport's existing bound.
Neither bound grows automatically. `--max-estimate-calls` defaults to three
and limits helper symbol attempts across all estimate batches; the transport
ledger reports actual HTTP attempts separately. Zero requests performs a
cache-only execution with visible unresolved targets.

Current raw prices run in batches of at most 30 and 32 KiB. A successful identical
calendar request is reused across batches, with its original provider request
provenance. Estimate batches respect the existing limits of 30 period rows, 32 KiB and
ten symbol calls, keep each symbol's periods together, and spend the declared
whole-run estimate allowance in nomination order. There is no repeated
per-ten-nominee manual invocation. Recent eligible archives avoid new requests;
`--reuse-hours` retains the existing estimate freshness range of one to 24
hours, default 24. Provider denial or quota failures remain typed. Alpha
Vantage's existing persistent cooldown is respected across executions. History
reuse matches the exact window, feed, adjustment, symbol mapping and class;
matching saved partial history is also reused within `--reuse-hours`, retaining
its missing coverage without another request. A changed reason or page budget
alone is not new evidence or permission to refetch the same observation.
For a fixed cutoff, a matching later receipt remains future-only even after the
normal reuse window; another fetch still could not repair that edition.

## Use the result and continue only unresolved work

The result retains the complete nomination scope and one limitations list per
target. `complete` means all requested history/current-price/estimate evidence is eligible; it
does not mean the investment thesis or issuer-capitalization review is complete.
Coverage failures, missing periods, stale prices, provider access failures,
quota cooldowns and request exhaustion remain visible. Successful evidence
from another provider is preserved when one source stops.

The returned private `scratch` directory holds the exact plan, fixed budgets,
per-request intent/completion records, capture results, `result.json` and
`continuation-plan.json`. `budget.http_attempts` and top-level `requests` count
physical transport attempts. Calendar provenance replayed to the archival
helpers does not increase that ledger. Intent without completion identifies an
interrupted operation; preserve it and inspect already saved archives before
considering a new request. The coordinator never automatically retries an
interrupted run or resumes with a larger budget.

Both the result and `budget.json` retain the configured `max_seconds` and
estimate `reuse_hours`. An injected transport whose time bound is unknown
reports null for `max_seconds`; a plan option does not assert or change that
transport's actual deadline.

The continuation plan includes only targets with unresolved acquisition needs
and their unresolved history and fiscal selections. A continued target can retain its
price declaration so a still-fresh archived price is reused. Run a fresh
offline plan before any explicit subsequent execution. Do not loop on quota,
access or uncertain interrupted requests; use the returned limitation and
retry timing. A new invocation is a new explicitly bounded execution, not
unused budget silently carried from the previous run. Requests first saved
beyond a fixed cutoff are excluded from continuation because re-fetching cannot
make them eligible for that edition.

For preparing a new manual or scheduled edition, omit `--as-of`, complete the
authorized acquisition, and use `ready_to_freeze_after`. It is the actual
completion time after all history, price and estimate saves and the necessary whole-second boundary;
it is never a predicted future cutoff. Prices are reselected after estimate
work, and successful estimates are rechecked against the same final completion
time. History is also rechecked at completion. Evidence that expires during later work becomes `stale` with its
original acquisition status and snapshot retained, and enters continuation
without another provider call. A partial result may still
prepare a limited review with its outstanding limitations recorded. Freeze the
research cutoff only after acquisition finishes.

For an already frozen edition, pass its unchanged ISO timestamp with
`--as-of`. Later history, price and estimate receipts remain archived as `future_only`
or `captured_future_only`/`reused_future_only`. They cannot enter that edition;
`ready_to_freeze_after` remains null. A repeat execution reuses those records
without another paid call or a backdated availability claim.

Current-news collection is not added by this coordinator. When source review
identifies a specific current-news question, use the existing bounded adapter
within the research run's explicit remaining scope and budget, and preserve
its separate provenance and limitations. Never route a targeted plan through
`market_acquire.py discover` or an assets/universe endpoint.
