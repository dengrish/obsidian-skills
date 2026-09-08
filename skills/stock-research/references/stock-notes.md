# Maintained stock notes

Keep one note per verified security at `Investments/Stocks/<TICKER>.md`, using the
exact uppercase provider ticker, including share-class punctuation when relevant.
A stock note supplies the latest research view and links to dated daily evidence;
it is not a position record, price target database or separate recommendation
ledger. The immutable daily notes retain the original judgments and outcome
journals. A new publication updates the current view only when the stock received
a substantive assessment; do not rewrite every dossier on every run.

Publication receipts in `Investments/.stock-research/dossiers/` are durable
ownership and recovery data, not scratch. Preserve them with the stock notes;
do not delete or edit them during cleanup. Temporary update plans are separate
and remain in owned scratch until publication succeeds.

## Coverage and content

Create or update a stock note for every substantively evaluated stock, including
watch, ready, rejected, invalidated and expired assessments. A passing mention or
nomination deferred before evaluation needs only a disposition in the daily
record. Existing active theses continue to be followed even if their originating
account leaves the roster; that does not restore the account as a new idea source.

Each daily Candidate assessments section uses a verified identity heading such as
`#### NASDAQ:AAPL — Apple Inc.`, exactly one standalone `Status: watch` line
(or `ready`, `rejected`, `invalidated`, `expired`), and a link to
`[[Investments/Stocks/AAPL]]`. Keep source attribution, the concise current thesis,
decisive business/price evidence, counterargument, confirmation/invalidation
conditions and next check together under that heading. Use deeper headings for
detail. The helper copies the exact published assessment into the stock note;
do not write a second version whose values or conclusion could diverge.

The helper supplies consistent identity, created/updated metadata and verified
skill provenance, the latest assessment and dated links to previous daily
assessments. Preserve original company/security identity across updates. Where
available, retain a verified stable identifier with a standalone daily line such
as `Company ID: SEC:0000320193`. This allows a verified company-name change
without silently changing the issuer identity. A recycled ticker,
changed share class or conflicting company identity requires resolution; it is
not permission to overwrite another security's record or invent a successor.

## Read at the current cutoff

```bash
python3 '<skill>/scripts/stock_dossiers.py' context --vault '<vault>' --ticker AAPL --as-of '<cutoff>'
```

Use its current assessment only when available by the new edition's cutoff.
For an earlier cutoff, follow eligible historical daily links instead. Do not
backfill a prior judgment from a dossier updated with later information. The daily
history/outcome inventory governs recommendation clocks, failures and prior
lessons; a dossier is a convenient current view, not an independent source of
financial facts. Preserve immutable daily reports when correcting a dossier.

## Publish after the daily report

Prepare all substantive daily assessments and their stock links during research.
Complete evidence checks and publish the daily report first, then derive its
stock updates. The daily report is the authoritative source; it must never claim
a successful portfolio action or hide a source limitation that the stock note
exposes. A temporarily unresolved stock link is repaired by the following guarded
publication, not by making a second daily edition.

Update every substantive assessment with the normal batch command:

```bash
python3 '<skill>/scripts/stock_dossiers.py' sync --vault '<vault>' --daily-note '<published-daily-note>' --work-dir '<scratch>'
```

Inspect `complete`, `analyzed`, `results` and `failures`. A failure includes its
retained `recovery_draft` where available; successful stock writes need not be
repeated manually. A clean run with no substantive assessments has no dossiers to
create, not missing publications. Re-running sync is safe and should complete
outstanding updates before closeout.

For a targeted retry or one assessment:

```bash
python3 '<skill>/scripts/stock_dossiers.py' prepare --vault '<vault>' --daily-note '<published-daily-note>' --ticker AAPL --draft '<scratch>/AAPL-update.json'
python3 '<skill>/scripts/stock_dossiers.py' publish --vault '<vault>' --draft '<scratch>/AAPL-update.json'
```

The helper extracts identity, status and exact assessment text from the published
daily heading. Optional `--exchange`, `--company`, `--heading` and `--company-id`
flags validate that same metadata; they do not supply a different assessment.
The example CIK above is illustrative, not a default for other companies. The prepared update
binds the published daily bytes and prior stock-note bytes. Changed inputs require
repreparation; do not alter the captured receipt or copy a foreign assessment.

Read back the published stock notes and check their daily links, identity, cutoff,
status and provenance. Unchanged retries reuse the same assessment without adding
duplicate history. On an interrupted run, retain the named recovery artifacts and
resume the missing stock updates from the already published daily report; never
rewrite the report or create a fresh daily edition merely to repair this step.
A scheduled retry that reuses an existing report must also finish its outstanding
stock-note updates before reporting a complete run.

The helper owns only its verified generated notes. Preserve unfamiliar occupants,
manual changes, identity conflicts and unsafe paths; report the exact blocker
rather than overwriting them. A current note must not regress to an older daily
assessment. Corrections belong in a new daily assessment, then in the maintained
view. No mandatory human approval or separate review report is required for
routine, safely verified updates.
