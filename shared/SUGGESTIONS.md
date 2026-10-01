# Shared suggestion logs

Read this before writing any suggestion log, when the
[closeout gate](RUNTIME.md#close-out) sends a run here; a run it does not send
here writes no log. A report-only, preview, or no-apply run writes no logs or
setup files. All logs live in `<vault>/Reviews/`:
**open issues first, then a short record of fixed ones** that stays until the
user removes it. They are shared issue records, not fully generated notes:
preserve existing items and unrelated content rather than rebuilding a log
from a scan. Routine skill runs improve their authorized vault outputs, not
skill source files; record evidence-backed changes to skill behavior here.

Use logs only when the run already has a selected or established vault.
A workflow that supports standalone paths with no vault reports suggestions
in the conversation; do not create `Reviews/` beside an external input or ask
for a vault solely for logging. This does not waive the selected workflow's
own vault requirement.

## Add or update one item

This section covers adding or updating an open item in an existing log. Read
on for anything else, including an item that may belong to another skill's
log, initializing or migrating a log, an older-format log, or recording,
verifying, reopening or removing a fixed issue.

Skill logs track evidenced workflow defects; they are not topic backlogs or
copies of the workflow's deliverables. Attribute a proposal to the behavior
that caused the evidenced defect. Write only actionable proposals supported by
artifacts actually inspected in the run. Name the affected path, observed
failure, and useful correction; include source/page evidence when relevant.
Do not manufacture suggestions, copy whole scan outputs, or create one issue
per occurrence of the same underlying problem. An all-skipped run may close
out from evidence already obtained; closeout does not authorize new audits or
expand the run's scope.

Snapshot the log with the first command below, then read it. Reuse one stable
ID per problem within each log; match the underlying issue before allocating
a new ID. Update an existing
item's evidence and reporting skills when new observations warrant it;
increment recurrence at most once per logical run, even across rescans,
retries, or delegated checks. Use one run timestamp in `YYYY-MM-DD HH:MM`
form. A coordinating agent passes that timestamp and the already-counted
log/issue IDs to invoked skills; when none was inherited, use the run's start
time. Combine parallel subtasks' findings before updating the same log. Keep
the first timestamp and update latest only on a new occurrence. `Reported by`
names the observing skill or skills, or `plugin review` for a
source-development review.

A skill log has this form, substituting its actual issue data. It has no H1
title: Obsidian already shows the filename as the note's title.

```markdown
Open issues come first. A fixed issue moves to Fixed and stays until the user removes it.

## Open

### [stable-id] Short actionable title

- **Issue:** Concrete behavior that needs correction.
- **Evidence:** Inspected artifact and the observed defect.
- **Suggested change:** Specific improvement and its intended result.
- **Reported by:** <observing-skill>
- **Seen:** ×1 · first YYYY-MM-DD HH:MM · latest YYYY-MM-DD HH:MM

## Fixed

### [stable-id] Short actionable title

- **Issue:** Concrete behavior that needed correction.
- **Fixed in:** <plugin> <version> (<source commit>), YYYY-MM-DD
- **Verified:** YYYY-MM-DD HH:MM — the check that confirmed the fix.
```

An empty section keeps its heading, followed by a blank line and
`No open suggestions.` or `No fixed suggestions.`; remove that sentence when
adding an item. Do not add dated sections or filler.

Publish with the shared `publish_files.py`, which follows the
[safe-write protocol](SAFE_WRITES.md): snapshot each log path before reading
it, write the reviewed result to a private draft, then publish, which creates
a missing log exclusively and replaces an existing one only against its
unchanged snapshot:

```bash
python3 '<plugin>/shared/scripts/publish_files.py' snapshot --vault '<vault>' \
    -o '<scratch>/log-snapshots.json' 'Reviews/<current-skill>-suggestions.md'
python3 '<plugin>/shared/scripts/publish_files.py' publish --vault '<vault>' \
    --snapshots '<scratch>/log-snapshots.json' \
    --manifest '<scratch>/log-manifest.json'
```

The manifest lists each log written, as
`[{"path": "Reviews/<current-skill>-suggestions.md", "draft": "<absolute draft path>"}]`.
`Reviews/` must have a unique, readable real directory owner; reject directory
or leaf symlinks, non-regular occupants, and case/Unicode-equivalent ownership
collisions. Create a missing `Reviews/` directory only after checking its name
has no other owner, by adding `--create-dir Reviews` to `publish`. If its path
or a log cannot be used safely, preserve the occupant and report the blocked
log update; complete other independent authorized work. When `snapshot` or
`publish` reports that a log changed since its snapshot, preserve that change:
rerun the snapshot with `--replace`, re-read and redo the update before
retrying; never overwrite newer content or blindly append. Scope is limited
to recognized logs, not arbitrary files under `Reviews/`.

Report what was added, updated, moved, or verified and the check used.

## Destination and attribution

Use `Reviews/<current-skill>-suggestions.md`, taking the exact skill name from
its loaded `SKILL.md` and matching folder under the current plugin's `skills/`.
Do not prefix the filename with a plugin namespace.

Content corrections follow the active workflow's ownership and history rules.
A workflow handling Wiki entries uses `Reviews/wiki-notes-suggestions.md` for
Wiki note-content issues that remain outside its repair scope. A workflow
producing investment research follows its own daily-note continuity rules for
factual corrections and keeps ideas, watchlist changes, and outcome learning
in its research records.

A skill may update its own log and the log of the skill that produced or
governs an output it actually consumed in this run. Establish the producer
from the run's handoff record, a valid legacy provenance footer, or a producer
record in the owning skill's private state. Notes otherwise carry no producer
record: attribute a recurring output pattern, or one serious well-evidenced
defect, to the skill whose instructions govern that output, and say in
**Evidence** that attribution is by governing rule. A file's folder alone establishes neither.
That skill may belong to another independently installed plugin; update its
existing canonical log without requiring its plugin or invoking its skill.
Do not blame a producer for work owned by its consumer: missing retrospective
link backfill is not a builder defect. If attribution is uncertain, report
that uncertainty without inventing an upstream owner.

## Log format and maintenance

The note-content log uses a skill log's intro, sections, and item format; its
**Fixed in** names the run that changed the notes, such as
`wiki-lint run, YYYY-MM-DD HH:MM`.

**Fixing.** Move an item to Fixed when a released plugin version or a
completed run fixes it. Keep its heading and **Issue** line, drop the other
lines, and add **Fixed in**. A planned or unreleased skill-source change
leaves the item open. Keep an unresolved portion as its own open item.

**Verifying.** A run that checks a fixed item's behavior or content, with the
relevant validation, adds **Verified**; no confirmation is required. A version
bump, nonrecurrence alone, or a finding absent from an incomplete scan is not
verification. A run that verifies an open item's fix moves it with both lines,
naming the installed version when the fixing release is unknown. When the
check fails, or a fixed issue recurs, move it back to Open under the same ID in
the full form, with **Evidence** that names the earlier fix and a fresh
**Seen** line.

**Removing.** Skills never delete fixed items: the user removes them after
review, or an explicitly requested cleanup does. Never clear a section because
the current run looks clean. Do not archive fixed items in another generated
report. Unchanged logs need no write, and empty canonical logs are kept rather
than deleted.

**Older logs.** A log without `## Open` and `## Fixed` predates this format.
The next run that writes it replaces the old intro with the current one, puts
the existing items under `## Open`, one heading level lower, and adds an empty
`## Fixed`. A log that still opens with an H1 title drops it on its next write.

## Setup and migration

On an apply-capable run in an established vault, initialize any missing
canonical skill logs for the skills shipped in the current plugin's `skills/`
directory. Derive the roster from that installed package rather than a fixed
list. Preserve any existing logs from either plugin; create the Wiki
note-content log only when needed by a Wiki workflow.
This initialization does not authorize adding issues to unrelated producer logs.

Existing logs may be migrated to these canonical paths when migration is
explicitly requested. Preserve unresolved content and verify the destination
before [conditionally removing](SAFE_WRITES.md#remove-or-move-an-old-pathname-conditionally)
the exact snapshotted old file. Do not maintain
parallel old filenames or delete unrecognized reports during ordinary runs.

## Reviewing the plugin itself

An explicit request to review or improve the plugin authorizes fixing its
canonical source repository now, with the relevant validation and Git history
as the durable record; never edit the installed plugin or its cache. Without
access to that repository, report the proposed fixes instead. Do not
substitute suggestions for authorized source fixes. Do not create dated
`obsidian-plugin-review-*` or `wiki-review-*` reports by default; the run
response reports changes and checks. Leave existing reports untouched unless
the user explicitly requests their migration or removal.
