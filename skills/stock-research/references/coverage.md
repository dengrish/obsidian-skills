# Research coverage and work scheduling

Use this guide on every stock-research run. The source of new autonomous ideas
remains the saved feed, while prior research supplies continuing and unfinished
work. Research every eligible new substantive idea to the
[standard initial assessment](research-method.md#standard-initial-assessment-and-readiness).
Neither the short brief's three-idea limit nor an acquisition batch size limits
initial coverage. Investment conclusions and research completion are separate.

## Decide what needs work

| Situation | Required action |
| --- | --- |
| New substantive idea in an eligible saved post | Verify identity and scope, then perform a standard initial assessment. |
| Passing mention, unchanged repeated argument, or clearly ineligible security | Record the reason; reuse earlier research where applicable. Missing identity or evidence is a blocker, not an adverse finding. |
| Material new argument about an existing stock | Assess the changed premise against the earlier evidence; do not start the company's research from scratch. |
| Prior watch/ready thesis | Check relevant news/events, price conditions and next milestones each trading day; reverify readiness before retaining `ready`. |
| Changed condition, material event or due review | Perform a focused substantive reassessment and update the stock note. Review active thesis health at least weekly. |
| Rejected, invalidated or expired idea | Reconsider only on material new evidence or its recorded reconsideration condition/date. Its note alone does not schedule daily research. |
| Capacity prevents finishing | Keep the work queued for the next run with its original age; report incomplete coverage. |
| Evidence prevents finishing | Keep the exact missing check blocked with a dated retry and a concrete resolution condition. |
| No new posts, or missing/partial collection | Continue prior monitoring and due work. Preserve feed gaps; do not find replacement ideas elsewhere. |
| Additional same-day run | Resume unfinished work and process changed evidence or due checks; reuse still-valid dated checks. |
| Closed market or missed execution days | Check relevant news/events and catch up the available intervening window; never invent trading observations or claim skipped checks were performed. |

Routine monitoring checks the actual thesis conditions, current material news,
upcoming events and outstanding evidence. Record the observations/time and next
check in the daily record; a stock note changes only after substantive assessment.
The weekly health check also reviews thesis relevance, deadlines and unresolved
premises. A new material fact, crossed price condition or due event overrides a
planned reuse; absence of a new social post does not establish that nothing changed.
On repeat runs, identify the earlier check and explain why it remains current.
When evidence needed to reverify a prior `ready` idea is missing, record the gap
and return it to `watch`, without restarting its recommendation clock.

Process decision-changing active checks first, then older capacity deferrals,
other due checks, and new eligible ideas in first-seen order. Use security identity
to break otherwise equal ties. Finish all feasible initial assessments; this order
is not permission to leave a permanent backlog. Every remaining item must retain
its age, reason and next action. If the workload repeatedly exceeds capacity,
surface the growing backlog and oldest item in the brief instead of dropping names,
lowering assessment quality or silently changing the account roster.

For blockers, schedule a realistic retry based on the missing source or upcoming
event. Check sooner when that resolution event occurs. Do not make the same paid
request every run merely because an unresolved item is still present. Outstanding
readiness-only checks can remain attached to a completed `watch` assessment;
`blocked` means the required assessment or monitoring work itself could not finish.

## Reconstruct the queue before choosing work

The offline helper replays visible coverage tables in earlier daily reports,
verifies their history links and fingerprints, and compares them with saved feed
post and article revisions. There is no independently edited queue note or mutable research
cursor. The daily reports are the persistent record; do not edit them to clear
work. No provider calls or feed writes occur here.

```bash
python3 '<skill>/scripts/stock_coverage.py' context --vault '<vault>' --as-of '<cutoff>' --mode '<mode>' > '<scratch>/coverage-context.json'
```

Before fresh scheduled or manual preparation, use the actual current time to
identify known work for the [targeted acquisition coordinator](targeted-acquisition.md).
It batches the justified plan internally under one declared request budget.
Repeat intake at the final frozen cutoff. Any plan or budget limit leaves visible
unfinished work; it is not permission to discard candidates or silently reset
the budget through smaller invocations. An already frozen cutoff stays fixed;
only eligible earlier archives can fill its evidence needs.

Read the pending source work, older unfinished queue, active securities and new
post fingerprints. Unresolved older X posts extend the intake window to their
recorded publication time; an explicit `--since` can recover an additional known
gap. If the collector no longer retains a source, preserve the pending item and
report that limitation. It does not become processed merely by falling outside
the normal 72-hour window or because its author left the roster. An old source
can complete its already-recorded work without reactivating that account for new
ideas. Prior active theses likewise survive removal of their originating account.

RSS revisions enter new intake by first observation, even when their article was
published earlier. Unfinished work retains the exact revision ID instead of
expanding X's lookback to that article's publication date. A later article revision
does not silently replace the evidence underlying an unfinished or completed
assessment; compare the changed premise and keep the earlier source traceable.

The helper cannot decide whether an argument is substantive, verify a financial
claim or recognize every important event. Read each unprocessed source, make those
judgments, and retain concise reasons. An unchanged post fingerprint prevents
duplicate intake, not future reassessment when business or market facts change.
Pass the edition's actual `manual` or `scheduled` mode so assessment links and
history match the correct filename, including a second edition on the same day.

## Visible journals in each new daily record

New editions use `stock_research: 2`. Put these three exact H4 tables under
`### Screening and sources`. Keep an empty table's header and separator, with no
rows. Put explanatory prose before the journal headings or under a separate H4;
each reserved H4 contains only its exact table. Use unpiped qualified wikilinks,
comma-separated lists, no literal cell pipes, and timezone-aware ISO timestamps.
Do not use code fences or hidden comments in a daily research note.

**Coverage history** has columns `Report | SHA256`. The helper returns the exact
required anchors. At the first structured edition, inspect all earlier legacy
reports and include their qualified report links and actual byte fingerprints.
Explicitly recover their unfinished work, source dispositions and next checks;
an empty queue requires that inspection, not an assumption. Later editions anchor
the immediately preceding structured report plus any later legacy reports written
by an older runtime or imported from another host. Inspect and recover unfinished
work from those intervening reports too. This chain detects changed or missing
anchored history without maintaining another index.

Bootstrap fingerprints record which bytes were inspected; they do not reconcile
changed historical dossier evidence or endorse a rewritten original. Preserve
those diagnostics and use only verified original assessments for reuse. Never
alter old daily notes, receipts or provenance to make migration pass. If earlier
unfinished work cannot be established reliably, retain a specific limitation and
the recovery work rather than claiming a clean history.

**Feed dispositions** has columns
`Post | Fingerprint | Published | Disposition | Securities | Due | Reason`.
Use the planner's exact `journal_source` in `Post`: an X permalink or an RSS
revision token `rss:<URL hash>@<revision hash>`. Use its separate canonical article
link in explanatory prose. Copy the supplied coverage fingerprint and `Published`
timestamp. For an undated RSS item, the planner explicitly labels a first-observed
fallback; preserve that limitation, never call it a known publisher date.
The fingerprint includes the excerpt and relevant
attachment evidence, so newly available attachments prompt reconsideration too.
Record new or changed post versions, plus unresolved earlier rows until
resolved. `nominated` lists the verified `EXCHANGE:TICKER` identities with new or
materially changed arguments requiring assessment. `repeated` lists identities
whose arguments are unchanged and already assessed; retain their verified earlier
assessment links through the queue. A mixed post uses `nominated` for the identities
requiring assessment and explains any other already-covered arguments by link in
Reason. `no-idea` or `excluded` records a supported screening reason. `pending` means it
has not been evaluated; `blocked` names an unavailable premise, attachment or
unresolved identity. Use `-` for no known security, never invent one. Pending and
blocked sources retain a dated next check; completed source dispositions use `-`.
A post containing several new substantive stock ideas lists all their identities.
When only part of a post is blocked, retain the known securities and their
separate queue entries while explaining the unresolved remainder. Link each
resolved security back to that source; its assessment and nominee enrollment
need not wait for an unrelated symbol or attachment to be resolved.
When a new or changed partial source creates unfinished security work, that
assessment must address the new argument; reuse or monitoring of an older
assessment cannot clear it. Once the security's work is assessed, carrying
the unchanged source's unrelated blocker does not reopen that completed work.

**Research queue** has columns
`Security | First seen | State | Priority | Due | Sources | Assessment | Reason`.
Include every unfinished prior security, current active security, newly nominated
security, repeated argument's security, and stock substantively assessed this run.
One row per verified security
can cover several sources or thesis IDs; preserve the separate thesis ledger.
Retain original first-seen time when continuing work. Sources are the originating
X post IDs or exact RSS revision tokens, `user` for an explicit user request, or
`legacy:<canonical-daily-filename>.md` for work recovered from a legacy report.
Carry every source from an unfinished prior job into its resolution; explain any
obsolete argument in the assessment instead of silently dropping its source.
New nominations require `assessed`, `queued` or `blocked`; routine monitoring or
reuse alone cannot account for a declared new argument.
Unfinished substantive work retains that requirement across runs: an older
assessment cannot clear a later material argument or capacity deferral. The helper
also restores such work if an older report mistakenly marked it reused or monitored,
without rewriting that historical report.

- `queued`: capacity prevented completion; keep priority `capacity` on the next
  run and a due timestamp no later than the next review.
- `blocked`: name the missing evidence, dated retry and what would resolve it.
  A partial or status-changing assessment may link this edition's H4 without
  claiming the required work finished. For example, missing current evidence can
  require a `ready` thesis to become `watch` and its dossier to be updated while
  the price-monitoring task remains blocked.
- `assessed`: link the actual H4 assessment in this edition. This can support any
  justified investment status, including `watch` or `rejected`.
- `monitored`: relevant current checks were completed; link the earlier substantive
  assessment and record what was checked, its time and next check.
- `reused`: an unchanged argument or still-valid check was already covered; link
  the verified earlier assessment and explain reuse. If the public report is
  quarantined, use the exact receipt-verified archive H4 returned by dossier
  context, never a broken or altered public link or an unverified archive. It is not a fresh monitoring
  observation or permission to retain stale readiness.
- `closed`: the required work is no longer relevant or the idea is outside scope;
  give an evidenced reason and reconsideration condition where applicable.
  Closing a research task does not silently invalidate or expire a tracked thesis.

Use priorities `active`, `capacity`, `due` or `new` according to the work order
above. Due timestamps identify actual next checks, not invented provider freshness.
Keep substantive evidence and monitoring observations in ordinary prose beside
the journals or linked assessment, without reproducing the whole earlier report.

## Reconcile and publish

```bash
python3 '<skill>/scripts/stock_coverage.py' check --vault '<vault>' --as-of '<cutoff>' --mode '<mode>' --draft '<run>/daily-stamped.md'
```

The checker requires dispositions for newly available post versions, preserves
unfinished source/security work, checks active coverage and verifies assessment
references. It also rechecks the saved feed; a changed source snapshot requires
reconciliation, not overwriting source notes. `complete` describes valid accounting;
`research_complete` separately describes whether required work and source coverage
remain incomplete. A valid partial report may be published, but use `coverage:
limited` or `unavailable` and name the outstanding work. The publisher repeats
the coverage check before creating the immutable edition.

Summarize the helper's actual counts: posts reviewed or pending, newly nominated
securities, screened source exclusions, stocks assessed, monitored, reused, queued
and blocked. Distinguish completed standard assessments from substantive partial
assessments whose work remains unfinished. The journals do not count distinct
arguments mechanically: a manually counted argument total must be labeled as such,
and every substantive argument still needs assessment even when several concern
the same stock.
Keep post counts separate from stock counts, and do not count a repeated source
as a second independent recommendation. The short brief reports material remaining
work and the oldest capacity deferral. A quiet or closed day can have no new ideas;
it still accounts for due monitoring, unresolved work and outcome reviews.
