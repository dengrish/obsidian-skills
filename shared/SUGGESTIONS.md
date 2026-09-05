# Shared suggestion logs

Read this at the close of every skill run and before changing a suggestion
log. All logs live in `<vault>/Reviews/` and contain **open issues only**.
They are shared issue records, not fully generated notes: preserve existing
open items and unrelated content rather than rebuilding a log from a scan.
Routine skill runs improve their authorized vault outputs, not skill source
files; record evidence-backed changes to skill behavior here.

Use logs only when the run already has a selected or established vault.
Standalone PDF workflows with no vault report suggestions in the conversation;
do not create `Reviews/` beside an external input or ask for a vault solely for
logging. This does not waive a Wiki or source-note workflow's vault requirement.

## Destination and attribution

Use `Reviews/<current-skill>-suggestions.md`, with exactly these skill names:
`clipping-clean`, `figure-extract`, `paper-summarize`, `pdf-organize`, `wiki-add`,
`wiki-build`, and `wiki-lint`. Use `Reviews/wiki-notes-suggestions.md` for
note-content issues that remain outside the run's repair scope, rather than
misclassifying them as skill defects.

A skill may update its own log and the logs of producers whose outputs it
actually consumed in this run. Attribute a proposal to the behavior that
caused the evidenced defect, using verified provenance or the run's handoff
record; a file's folder alone does not establish its producer. For example,
wiki-lint may report an evidenced production issue to wiki-build, wiki-add,
or figure-extract, and wiki-build may report one to figure-extract after
using its figures. These are examples, not an exhaustive routing table.
Do not blame a producer for work owned by its consumer: missing retrospective
link backfill is not a builder defect. If attribution is uncertain, report
that uncertainty without inventing an upstream owner.

Write only actionable proposals supported by artifacts actually inspected
in the run. Name the affected path, observed failure, and useful correction;
include source/page evidence when relevant. Do not manufacture suggestions,
copy whole scan outputs, or create one issue per occurrence of the same
underlying problem. A clean run may have nothing to add. An all-skipped run
may close out from evidence already obtained; closeout does not authorize new
audits or expand the run's scope.

## Open-issue format and maintenance

Read the existing log first. Reuse one stable ID per problem within each log;
match the underlying issue before allocating a new ID. Preserve unrelated and
unresolved items. Update an existing item's evidence and reporting skills when
new observations warrant it; increment recurrence at most once per logical
run, even across rescans, retries, or delegated checks. Use one run timestamp
in `YYYY-MM-DD HH:MM` form. A coordinating agent passes that timestamp and the
already-counted log/issue IDs to invoked skills; use an initial scanner
timestamp only when none was inherited. Combine parallel subtasks' findings
before updating the same log. Keep the first timestamp and update latest only
on a new occurrence. `Reported by` names the observing skill or skills, or
`plugin review` for a source-development review.

A skill log has this form; substitute its actual skill name and issue data:

```markdown
# wiki-build suggestions

Open issues only; remove an item once its resolution is verified.

## [stable-id] Short actionable title

- **Issue:** Concrete behavior that needs correction.
- **Evidence:** Inspected artifact and the observed defect.
- **Suggested change:** Specific improvement and its intended result.
- **Reported by:** wiki-lint
- **Seen:** ×1 · first YYYY-MM-DD HH:MM · latest YYYY-MM-DD HH:MM
```

The note-content log uses `# Wiki notes suggestions` with the same intro and
item format. An empty log keeps its heading and intro, followed by a blank line
and `No open suggestions.` Remove that empty-state sentence when adding an
item. Do not add dated sections, resolved-history sections, or filler.

Remove an item automatically once its specific resolution is verified; no
additional confirmation is required. A planned change, a reported fix, a
missing artifact, version bump, nonrecurrence alone, or a finding absent from
an incomplete scan is not verified resolution. Check the affected behavior or content and relevant validation,
then remove only that verified issue block, never clear a whole log merely
because the current run looks clean. Keep unresolved portions as an open item.
Report what was added, updated, or removed and the verification used; do not
archive resolved entries in another generated report. Unchanged logs need no
write, and empty canonical logs are kept rather than deleted.

## Publication and setup

A report-only, preview, or no-apply run writes no logs or setup files. On an
apply-capable run in an established vault, initialize any missing canonical
skill logs so all seven exist; create the note-content log when needed. This initialization
does not authorize adding issues to unrelated producer logs.

Use the shared [safe-write protocol](SAFE_WRITES.md): snapshot complete log
bytes when read, stage the reviewed result privately, publish missing files
exclusively, and replace only that unchanged snapshot. `Reviews/` must have a
unique, readable real directory owner; reject directory or leaf symlinks,
non-regular occupants, and case/Unicode-equivalent ownership collisions.
Create a missing `Reviews/` directory only after checking its name has no
other owner. If its path or a log cannot be used safely, preserve the occupant
and report the blocked log update; complete other independent authorized work.
Preserve concurrent changes and re-read before retrying; never overwrite newer
content or blindly append. Scope is limited to recognized logs, not arbitrary
files under `Reviews/`.

Existing logs may be migrated to these canonical paths when migration is
explicitly requested. Preserve unresolved content and verify the destination
before conditionally removing the exact snapshotted old file. Do not maintain
parallel old filenames or delete unrecognized reports during ordinary runs.

## Reviewing the plugin itself

An explicit request to review or improve the plugin authorizes fixing its
source now, with the relevant validation and Git history as the durable record.
Do not substitute suggestions for authorized source fixes. Routine skill runs
never edit skill sources. Do not create dated `obsidian-plugin-review-*` or
`wiki-review-*` reports by default; the run response reports changes and checks.
Leave existing reports untouched unless the user explicitly requests their
migration or removal. Remove a corresponding open suggestion only after its
specific fix is verified.
