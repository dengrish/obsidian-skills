# Duplicates and reprocessing

- [Reprocessing an existing note](#reprocessing-an-existing-note)
- [Settle a slug before writing images](#settle-a-slug-before-writing-images)
- [Publish an approved replacement](#publish-an-approved-replacement)
  - [Finish a pending changed-slug handoff](#finish-a-pending-changed-slug-handoff)
  - [Re-stem a renamed note's images](#re-stem-a-renamed-notes-images)

Use this reference for an approved rewrite or a filename collision. The normal
scan and its verdicts are in [Select the captures](../SKILL.md#1-select-the-captures-and-check-ownership).

## Reprocessing an existing note

An eligible clipping's first current `sources:` item is a web URL, and the note
is not a marked [research extract](../SKILL.md#1-select-the-captures-and-check-ownership). Read legacy
`source:` only when `sources:` is absent; malformed or ambiguous current
metadata cannot establish ownership through a stale value. A PDF origin belongs
to `paper-summarize`.

Naming a file already in `Articles/` for reprocessing authorizes that owned
rewrite. Naming a raw capture that matches another note requires an explicit
overwrite-or-skip decision; honor one already given in the conversation. An
explicit request to reprocess a selected batch supplies that decision for
matching notes this skill owns: re-read each raw and run the complete workflow
from its current files rather than continuing an old scratch draft. Ordinary
batch mode never overwrites a duplicate or selects polished notes on its own.

**Resume.** Resuming an interrupted run processes captures still `new`,
restores missing attachments of a matching owned note from its raw (as under
*Body source* below) without rewriting the note, and finishes a pending
changed-slug handoff by [its procedure](#finish-a-pending-changed-slug-handoff).
Every other match stays a `duplicate` skip.

Before reading the note for the rewrite, record its bytes, identity and mode
in the run's snapshot file; it must record `file`:

```bash
python3 '<plugin>/shared/scripts/publish_files.py' snapshot --vault '<vault>' \
    -o '<scratch>/clipping-snapshots.json' 'Articles/<old_slug>.md'
```

Once a changed slug is settled, record `'Articles/<new_slug>.md'` in the same
file; it must record `absent`. A case/Unicode respelling of the same note needs
no second record. This JSON record is the expected version through publication
and cleanup; never re-record it at commit time. Exclude this one note from its
own dedup scan.

**Body source.** For a named `Articles/` note, remove only its leading Summary
callout and following `___` separator to get the article body. Keep existing
body prose, embeds and still-valid audit placeholders. Do not summarize the old
summary as if it were source prose. For an authorized overwrite from a raw
capture, clean the raw afresh and stage its images to scratch. A staged image
that matches an attachment the note already embeds (identical bytes, else
caption, alt text and position, as in the
[completeness audit](completeness-audit.md#inventory-and-match-media)) keeps
that embed's name: discard the staged copy, first restoring the attachment with
`fetch_images.py place` (existing slug and `--owner-note`) if it is missing.
Only unmatched images take new numbers. Carry every other existing embed,
converted GIF or placeholder into the draft at its old position with its
caption, and never delete an attachment. A missing attachment that cannot be
restored becomes a reported `<!-- missing attachment: … -->` placeholder;
[image handling](images.md#existing-embeds-on-a-reprocess) covers a changed slug.

For a changed slug, resolve every old-slug embed in the old note that lacks its
exact attachment before step 4 of the
[replacement](#publish-an-approved-replacement). Either restore it with
`fetch_images.py place` (old slug, `--owner-note` the old note), or first
publish an approved same-slug rewrite of the old note that replaces that embed
with the `<!-- missing attachment: … -->` placeholder, then record the old note
afresh with `snapshot --replace` and re-read it. Prepare refuses a missing old
attachment, and by step 5 the new note is already public.

Apply the [frontmatter rules](metadata-verification.md#frontmatter-for-the-polished-note)
to decide which fields regenerate and which preserve user state. In particular,
an unknown or absent review state is not permission to supply `false`; report
that state and any metadata conflicts as required there.

Retain existing figure numbers. An unchanged slug leaves existing attachments
alone; new images continue after the highest occupied number. A changed slug
maps each existing attachment by replacing only the slug; `rename --phase
prepare --dry-run` reviews that plan after the new note is public (step 5).
Nothing changes files the original note uses before then.

## Settle a slug before writing images

Different bodies at the same origin are still duplicates: keep the user's
processed version unless they authorize a rewrite. A URL variant that passed
the URL check is still the same article (first table row), never a `_2` copy.

Check `Articles/<slug>.md` with `dedup_index.py --slug '<slug>'`; check
PDF stems throughout recursive
`Sources/PDFs/` and loose
`Sources/Images/<slug>_fig*` files. The Articles check uses the flat direct-child
namespace under NFC normalization and case folding; any `.md` directory entry,
including a directory or dangling symlink, occupies the name. More than one
equivalent spelling is ambiguous and cannot supply an arbitrary owner. If any
inventory cannot be read, resolve that failure before choosing a supposedly
free name.

| Existing owner | Action |
|---|---|
| The same article: a note with the same normalized web origin, or one whose origin differs only by scheme, an `m.`/AMP host or path alias, or query fields the normalizer keeps, and whose title and author/date match this capture's verified metadata | Batch: skip, keep the raw, and report a dedup escape with the existing path and both URLs. Named capture: use the explicit overwrite-or-skip decision, not filename similarity as authorization. If sameness is uncertain, treat it as this row, not the next. Never offer a marked research extract for overwrite. |
| A different source (URL and title/identity differ), PDF summary, PDF or loose figure set | Choose `<slug>_2`, then `_3`, … until the note and image stem are free. Use the suffix for both. Report the collision. |
| Current note being explicitly reprocessed | Keep its stem if still correct, or plan its own note/image rename below. |

Do not rename another owner's figures to free a stem. If a new collision appears
at final publication, return to this check and prepare/review the new draft and
image plan; appending a suffix only to the note leaves its images under the
wrong owner.

## Publish an approved replacement

This sequence applies to same-name rewrites and changed-slug reprocesses. The
original note remains intact until successful publication. `Inbox/` raws are
never moved, deleted or rewritten, including after a successful reprocess.

1. Complete the replacement at a unique scratch path outside the vault, using
   planned new image names. Finish the completeness audit and review against
   that draft. For a changed slug, replace only the slug in each planned image
   name; preserve its figure tail and extension. Do not copy, move or rename a
   live attachment before both owner notes are public.
2. Preflight both paths under the selected `Articles/` with
   `publish_files.py verify --vault '<vault>' --snapshots '<scratch>/clipping-snapshots.json'`.
   It rechecks every record in the run's file, so judge only this
   replacement's own entries. The original must report `unchanged`: still this
   clipping's regular, non-symlink file with the recorded identity and bytes.
   A distinct new destination must report `unchanged`, that is, still absent.
   Records of notes already published earlier in this run are expected to
   report `changed`, `appeared` or `removed`; a nonzero exit caused only by
   those entries does not refuse this preflight. An `error` result, or any
   other status on this replacement's own entries, does. Refuse any other
   occupant. A case/Unicode spelling of the same note is allowed only when
   `os.path.samefile` confirms it and the directory has **one** entry with that
   normalized name. Two distinct hard-link entries are not a spelling alias.
3. Stage nothing in the vault by hand. Each writer in step 4 stages its own
   copy of the reviewed draft, with the old note's recorded `mode`, in a
   unique hidden directory outside the note folder and on its filesystem.
4. Publish the complete note. A same-name rewrite runs `publish_files.py
   publish` against the record with the manifest
   `[{"path": "Articles/<slug>.md", "draft": "<absolute draft path>"}]`, as in
   [publication](../SKILL.md#6-publish-safely); it replaces only the recorded
   version and keeps its mode. A changed slug or a same-file case/Unicode
   respelling runs the shipped writer instead, because `publish_files.py`
   cannot give a new name the original note's permissions and refuses a case
   alias. Run it first with `--dry-run`, review the plan, then run the
   identical command without `--dry-run`:

   ```bash
   python3 '<skill>/scripts/fetch_images.py' rename --phase publish-note [--dry-run] \
       --vault '<vault>' --snapshots '<scratch>/clipping-snapshots.json' \
       --draft '<absolute draft path>' \
       --owner-note '<vault>/Articles/<old_slug>.md' \
       --new-owner-note '<vault>/Articles/<new_slug>.md' \
       --old-slug '<old_slug>' --new-slug '<new_slug>'
   ```

   The writer follows the shared
   [safe-write API](../../../shared/SAFE_WRITES.md#call-the-shared-python-api).
   It rebuilds the expected token from the old note's JSON record `r` as
   `atomic_move.RegularFileSnapshot(identity=tuple(r["identity"]), digest=r["digest"], mode=r["mode"], size=r["size"])`,
   never from a fresh snapshot. It refuses an old note that no longer matches
   its record, a draft whose first current `sources:` item is another web
   origin, and a legacy research extract. At a free destination recorded
   `absent` (a changed slug), it calls
   `atomic_move.publish_new(staged, target, atomic_move.regular_file_snapshot, stage_parent)`
   with the old note's recorded mode and leaves the old note in place. For a
   same-file spelling change, it calls
   `atomic_move.replace_expected(staged, target, expected, atomic_move.regular_file_snapshot, stage_dir, stage_parent=stage_parent)`
   with that token and a fresh `stage_dir`. Any other occupant of the portable
   name, and any case alias that is not the same single directory entry, is
   refused. Its JSON `action` is `created`, `respelled`, or `unchanged` on a
   rerun. A `failed` publication attempt names its retained `stage_dir` and
   any `recovery_path`. Never recheck and then call `os.replace`, and never
   publish through a private driver. If publication fails, no attachment has
   moved and the unchanged old note still resolves.
5. Read back the published note. For a same-path rewrite, place every newly
   staged remote or recovered image through the guarded
   [image publication procedure](images.md#download-and-publish), then verify
   its embeds before finishing. Existing attachments keep their names and bytes.
   For a changed slug, keep both notes in place. Run prepare first with `--dry-run`,
   review the plan, then run the identical command without `--dry-run`:

   ```bash
   python3 '<skill>/scripts/fetch_images.py' rename --phase prepare [--dry-run] \
       --attachments '<vault>/Sources/Images' \
       --sources '<vault>/Sources/PDFs' \
       --owner-note '<vault>/Articles/<old_slug>.md' \
       --new-owner-note '<vault>/Articles/<new_slug>.md' \
       --old-slug '<old_slug>' --new-slug '<new_slug>'
   ```

   The helper snapshots both notes, requires the same current web source, and
   requires every old image and mapped destination to be an exact rendered
   filename-only embed in its corresponding owner. It also applies the PDF
   ownership and destination-collision guards. Prepare exclusively copies the
   exact old bytes to the new names, rolls back copies it cannot complete, and
   retains every old name. Its JSON supplies the exact one-to-one mapping and
   complete dependency report by checking every Markdown note outside the owner.
   Its top-level `ok: true` means only that the new-name copies exist; remaining
   dependents are listed in `dependency.blockers` (with `dependency.ok: false`),
   each a `path` and its `references`. Step 6 repairs them.
   A refusal is not permission to copy by hand; retain the old note and images,
   conditionally withdraw only the exact new note if safe, and report every
   named recovery path.
   After prepare succeeds, place any additional staged remote or recovered
   images through that same guarded image procedure, using the new owner note
   and the new figure numbers. They are separate from the old-image mapping.
   Resolve a refused placement with the documented placeholder and retain its
   scratch file. Once any new image has been published, keep its owner note
   public even if link repair later leaves a blocker.
6. Repair every link to the old note and its mapped images, as Obsidian does
   on a rename. The reprocess request authorizes this; do not ask again or hand
   it to another skill. Run repair first with `--dry-run`, review the plan,
   then run the identical command without `--dry-run`. It takes prepare's
   exact arguments:

   ```bash
   python3 '<skill>/scripts/fetch_images.py' rename --phase repair [--dry-run] \
       --attachments '<vault>/Sources/Images' \
       --sources '<vault>/Sources/PDFs' \
       --owner-note '<vault>/Articles/<old_slug>.md' \
       --new-owner-note '<vault>/Articles/<new_slug>.md' \
       --old-slug '<old_slug>' --new-slug '<new_slug>'
   ```

   Repair refuses to run until prepare has published the new names. It
   recomputes prepare's dependency inventory over every visible Markdown note
   outside the old owner, never editing either owner, including Wiki entries,
   MOCs, `Reviews/` logs and notes under `Articles/` and `Investments/`. A
   dated `Investments/*-stock-research.md` or `*-market-research.md` record
   is immutable; repair reports it `blocked`. In each other dependent note it
   rewrites only the parsed wikilinks, embeds, Markdown inline and
   reference-style links, and HTML `src`/`href` values that resolve to the
   old note or to an exact mapped old image, pointing each at its mapped new
   name. Each keeps its path form, display label, `#heading` or `^block`
   anchor, `|size` and alt text; code, math, prose and URLs are never
   touched. It snapshots each note before reading it and publishes the
   rewrite against that snapshot through the shared safe-write API. Nothing
   else changes: a Wiki entry keeps `created:`, `updated:` and `read:`
   byte-for-byte. Its JSON has one row per note: the `path`, a `status`
   (`rewritten`, which the dry-run shows as `would-rewrite`; `unchanged`; or
   `blocked`) and `references`, each `{line, from, to}` holding the raw old
   and new target text. A `blocked` row adds its `reason`, the old names
   found (`dependencies`) and any retained `recovery` path. The command exits
   1 while any row is blocked. In the dry-run, check that every pair maps an
   old name to its mapped new one.

   A `blocked` note is left unchanged and stays a blocker: it is unreadable,
   changed after its snapshot, failed to publish, or holds an ambiguous
   reference. A reference is ambiguous when it may sit in code, math, a
   comment or plain text, when its spelling is encoded or its folder is not
   the renamed file's, or when it is a bare name and another vault file has
   the old or the new name. Repair rewrites none of that note's references;
   such references are left for the user. Leave both versions in place and
   resolving, report the remaining blockers, and never finalize while any
   remain. Never hand-patch a note around a helper refusal. A `blocked` row
   for the new note means the draft still names the old note or an old
   image: correct the draft, record the new note with `snapshot --replace`,
   republish it as the same-name rewrite in step 4, then rerun repair.
   Rerunning the identical command is safe; it rewrites only what is left.
7. After the repair, run the same complete Markdown dependency re-probe:

   ```bash
   python3 '<skill>/scripts/fetch_images.py' dependencies \
       --attachments '<vault>/Sources/Images' \
       --owner-note '<vault>/Articles/<old_slug>.md' --old-slug '<old_slug>'
   ```

   An `ok: true` result means no other scanned note links the old note or
   references one of its old image names. Anything else leaves both versions
   resolving. A dependent that appeared after the repair gets one more step-6
   run and re-probe; whatever still remains is a reported blocker.
8. With an `ok: true` re-probe, run finalize first with `--dry-run`, review the
   plan, then run it live using the identical paths and slugs from prepare:

   ```bash
   python3 '<skill>/scripts/fetch_images.py' rename --phase finalize [--dry-run] \
       --attachments '<vault>/Sources/Images' \
       --sources '<vault>/Sources/PDFs' \
       --owner-note '<vault>/Articles/<old_slug>.md' \
       --new-owner-note '<vault>/Articles/<new_slug>.md' \
       --old-slug '<old_slug>' --new-slug '<new_slug>'
   ```

   Finalize repeats the owner, byte-identity, PDF, mapping and dependency checks;
   the earlier probe is not standing cleanup authority. It conditionally retires
   only the exact old image copies and leaves the new copies in place, rechecking
   external dependencies around every retirement. A newly introduced link causes
   rollback. If any check fails, it retains both sets and reports the blocker or
   recovery path.
9. After finalize succeeds, conditionally remove the distinct old note against
   its record (made before the rewrite, or when finishing a pending handoff):

   ```bash
   python3 '<plugin>/shared/scripts/publish_files.py' remove --vault '<vault>' \
       --snapshots '<scratch>/clipping-snapshots.json' 'Articles/<old_slug>.md'
   ```

   It refuses a path with no record or one whose bytes, identity or mode
   changed, and reports any retained stage directory in its JSON outcome.
   Do not use a check followed by `unlink`, remove it for the same-file
   spelling case, or remove it if it changed. A cleanup refusal
   keeps the path; never delete first and report broken references afterward.
   Report a mixed state rather than hiding it.

If the filesystem cannot provide safe publication, stop and report the refusal.
Read back the published note and verify its embeds. Report note and attachment
renames, each note the live repair marked `rewritten` with its old → new
references, every remaining blocker with its reason and any `recovery` path,
and the dependency re-probe result; do not modify unrelated notes or
claim a failed rename completed.

### Finish a pending changed-slug handoff

A same-URL pair stays pending when repair left a blocker, or when an older
version of this skill stopped before repairing links. A resume, a request to
finish it, or a reprocess request naming either note finishes it without a
separate question. Confirm that both notes share the web origin, the old note
embeds the old-slug images and the new note embeds their mapped names. Record
the old note with `publish_files.py snapshot --replace` in this run's snapshot
file before reading it for this check; step 9 removes it against that record.
Rerun `rename --phase prepare --dry-run` with the original paths and slugs,
review it, then run the identical live command. Copies prepared earlier are
verified as `already-prepared`, and it returns the current mapping and
dependency report. Continue with steps 6–9: repair, the re-probe, finalize and
old-note removal. Do not re-clean the raw or redraft either note. A reprocess
request reprocesses the new note only after the handoff finishes; remaining
blockers stop it.

### Re-stem a renamed note's images

A note renamed outside this workflow can keep embedding images under its old
stem; `dedup_index.py` lists it under `stem_mismatch`. On request, re-stem
them with the same prepare, repair and finalize commands, passing
`'<vault>/Articles/<new_slug>.md'` as both `--owner-note` and
`--new-owner-note`. This applies only while no `Articles/<old_slug>.md` exists
and every `<old_slug>_fig*` file is an exact rendered embed of the renamed
note.

1. Prepare copies each image to its new-stem name and lists the note's own
   old references under `dependency.owner_references`.
2. Record the note with `publish_files.py snapshot`, replace only the old stem
   in each listed reference, and publish it against that record with
   `publish_files.py publish`.
3. Repair the other notes' `dependency.blockers` automatically as in
   [steps 6–7](#publish-an-approved-replacement): run repair (a dry-run, then
   live) with the renamed note as both owners. It rewrites only old-image
   references, since there is no old note to relink. It accepts the renamed
   note before or after its own embeds are republished, but refuses one left
   half republished.
4. Re-probe with `dependencies --new-slug '<new_slug>'` and that note as
   `--owner-note`. A note that repair reports `blocked` stays a blocker; keep
   both image sets and report it.
5. Finalize refuses while the note still references an old name, and retires
   the old copies only after a clean re-probe.
