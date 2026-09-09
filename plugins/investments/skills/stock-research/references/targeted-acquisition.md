# Targeted acquisition for verified nominees

Use `stock_acquire.py` after reviewing collected feed nominations, prior-stock
work or explicitly named user stocks. It coordinates the existing raw-price
and estimate archival helpers. It does not discover securities, collect feeds,
request X or ShadowAlpha, scrape pages, establish market capitalization, or
choose investments. Source and quoted-class verification remain research
judgments that precede the plan. This reduces price and estimate preparation;
current news, fundamentals, filings and the other research checks still follow
the main workflow within the user's existing authorization and budget.

## Prepare one explicit plan

Put an ordered JSON array in the run-owned external scratch directory. Every
nominee must include the fields accepted by the existing price capture plan,
plus nomination origins. `estimates` is optional: select fiscal periods only
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
session calendar, every price request, every estimate request and transport
retries. `--max-seconds` defaults to 120 and uses the transport's existing bound.
Neither bound grows automatically. `--max-estimate-calls` defaults to three
and limits helper symbol attempts across all estimate batches; the transport
ledger reports actual HTTP attempts separately. Zero requests performs a
cache-only execution with visible unresolved targets.

All planned prices run in batches of at most 30 and 32 KiB. A successful identical
calendar request is reused across batches, with its original provider request
provenance. Estimate batches respect the existing limits of 30 period rows, 32 KiB and
ten symbol calls, keep each symbol's periods together, and spend the declared
whole-run estimate allowance in nomination order. There is no repeated
per-ten-nominee manual invocation. Recent eligible archives avoid new requests;
`--reuse-hours` retains the existing estimate freshness range of one to 24
hours, default 24. Provider denial or quota failures remain typed. Alpha
Vantage's existing persistent cooldown is respected across executions.

## Use the result and continue only unresolved work

The result retains the complete nomination scope and one limitations list per
target. `complete` means all requested price/estimate evidence is eligible; it
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
and their unresolved fiscal selections. A continued target can retain its
price declaration so a still-fresh archived price is reused. Run a fresh
offline plan before any explicit subsequent execution. Do not loop on quota,
access or uncertain interrupted requests; use the returned limitation and
retry timing. A new invocation is a new explicitly bounded execution, not
unused budget silently carried from the previous run. Requests first saved
beyond a fixed cutoff are excluded from continuation because re-fetching cannot
make them eligible for that edition.

For preparing a new manual or scheduled edition, omit `--as-of`, complete the
authorized acquisition, and use `ready_to_freeze_after`. It is the actual
completion time after all saves and the necessary whole-second boundary;
it is never a predicted future cutoff. Prices are reselected after estimate
work, and successful estimates are rechecked against the same final completion
time. An estimate that expires during later work becomes `stale` with its
original acquisition status and snapshot retained, and enters continuation
without another provider call. A partial result may still
prepare a limited review with its outstanding limitations recorded. Freeze the
research cutoff only after acquisition finishes.

For an already frozen edition, pass its unchanged ISO timestamp with
`--as-of`. Later price and estimate receipts remain archived as `future_only`
or `captured_future_only`/`reused_future_only`. They cannot enter that edition;
`ready_to_freeze_after` remains null. A repeat execution reuses those records
without another paid call or a backdated availability claim.

Current-news collection is not added by this coordinator. When source review
identifies a specific current-news question, use the existing bounded adapter
within the research run's explicit remaining scope and budget, and preserve
its separate provenance and limitations. Never route a targeted plan through
`market_acquire.py discover` or an assets/universe endpoint.
