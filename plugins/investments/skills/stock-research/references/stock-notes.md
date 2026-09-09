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

New publications also preserve one exact copy of the validated daily bytes at
`Investments/.stock-research/dossiers/evidence/<SHA256>.md`, shared by that daily
report's dossiers. These private, content-addressed evidence snapshots are durable
original evidence, not editable replacement reports. They are created before the
write-ahead receipt and reused only when their bytes match exactly; an existing
conflicting or unsafe occupant is never replaced. The receipt remains schema 1;
new history rows add `evidence_snapshot: true`, while legacy rows remain readable
without that field. Reading or retrying an already committed legacy row does not
backfill snapshots, change its original hash or upgrade its evidence contract.

## Coverage and content

Create or update a stock note for every substantively evaluated stock, including
watch, ready, rejected, invalidated and expired assessments. A passing mention or
nomination deferred before evaluation needs only a disposition in the daily
record. A partial assessment must identify its missing evidence and remain
unfinished in the [coverage record](coverage.md); a dossier does not establish
that research is complete. The coverage record governs new ideas, reuse, due
monitoring, outstanding assessments and retries independently of the dossier's
buying status.

Do not reassess every stock merely because it has a note. Active theses receive
the [research method's monitoring and due reviews](research-method.md#thesis-continuity-and-aging);
closed ideas return on new substantive evidence or a recorded reconsideration
condition. Existing active theses continue to be followed even if their originating
account leaves the roster; that does not restore the account as a new idea source.
Routine unchanged monitoring belongs in the daily coverage record, with a link to
the valid assessment, and does not rewrite the stock note. New material findings
or a substantive due reassessment update it from the newly published daily record.

When earlier notes predate structured coverage, explicitly review the available
prior daily dispositions, active theses and deferred work using the coverage
guide's migration procedure. Do not infer an empty queue from missing structured
records, treat every old note as active, or restart all historical research.

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
For an earlier cutoff, follow eligible verified `history[].evidence_note` paths instead. Do not
backfill a prior judgment from a dossier updated with later information. The daily
history/outcome inventory governs recommendation clocks, failures and prior
lessons; a dossier is a convenient current view, not an independent source of
financial facts. Preserve immutable daily reports when correcting a dossier.

Inspect `history_complete` and `history_diagnostics` separately from `status`.
A valid latest assessment can have `status: current` and incomplete history.
Changed, missing or unsafe source paths are explicitly quarantined in diagnostics,
with their original expected hashes retained. Do not follow those public links as
verified evidence. When an exact preserved snapshot is available, its path is
returned as `evidence_note` and, for the latest assessment, `current_source`; the
public-source conflict remains visible. Without verified original evidence for a
row, that row is omitted from usable `history`, not deleted from its receipt.
When the latest row has no verified original evidence, `status: unverified-current`
withholds `current`. Modified stock-note bytes still fail the ownership check.

The helper never treats a fresh source hash as reconciliation. Cosmetic byte
changes, including line endings, and material edits both remain conflicts; it
does not normalize whitespace, code or tables to infer equivalence. An archive
preserves the originally validated assessment without endorsing edited source
bytes. All context, including diagnostics and archive paths, is filtered by both
the recorded assessment cutoff and generation time. A snapshot does not make a
later judgment available to an earlier edition. Pending publications must still
be recovered before reading context.

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

Inspect `complete`, `analyzed`, `results`, `failures`, `history_complete` and
`history_diagnostics`; individual prepare/publish results use the same history
audit. `complete` confirms the requested writes, not repaired historical evidence.
A valid new dated assessment may update a verified owned stock note while older
conflicts remain quarantined and explicitly reported. A failure includes its
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

If the public daily changes, disappears or becomes unsafe during a pending
publication, retry `publish` with the retained original update plan. Only that
plan-bound pending receipt can authorize recovery from its exact contracted
evidence snapshot. The helper verifies the predecessor, source digest, assessment,
identity and frozen provenance before completing the saved transaction; it leaves
the public occupant untouched and reports its conflict after recovery. A fresh
plan, an orphan snapshot or a legacy pending row without a snapshot contract
cannot use this fallback. Normal `sync` still needs the public daily to discover
its assessments, so use the targeted original-plan `publish` command above when
that report can no longer be safely read. Replaying the exact committed plan then
returns `unchanged` without copying source bytes or repairing history; diagnostics
still describe any unresolved paths. Preserve unresolved pending artifacts
if their original evidence is unavailable; do not rehash or recreate the report.

The helper owns only its verified generated notes. Preserve unfamiliar occupants,
manual changes, identity conflicts and unsafe paths; report the exact blocker
rather than overwriting them. A current note must not regress to an older daily
assessment. Corrections belong in a new daily assessment, then in the maintained
view. No mandatory human approval or separate review report is required for
routine, safely verified updates.
