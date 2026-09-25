# Duplicates and reprocessing

- [Reprocessing an existing note](#reprocessing-an-existing-note)
- [Settle a slug before writing images](#settle-a-slug-before-writing-images)
- [Publish an approved replacement](#publish-an-approved-replacement)
  - [Finish a pending changed-slug handoff](#finish-a-pending-changed-slug-handoff)

Use this reference for an approved rewrite or a filename collision. The normal
scan and its verdicts are in [Select the captures](../SKILL.md#1-select-the-captures-and-check-ownership).

## Reprocessing an existing note

An eligible clipping's first current `sources:` item is a web URL, and the note
does not carry the `<!-- obsidian:wiki-add-research-source -->` marker.
Marked research extracts remain distinct even when their URL matches a raw
capture; leave them unchanged. Read legacy `source:` only when `sources:` is
absent; malformed or ambiguous current metadata cannot establish ownership
through a stale value. A PDF origin belongs to `paper-summarize`.

Naming a file already in `Articles/` for reprocessing authorizes that owned
rewrite. Naming a raw capture that matches another note requires an explicit
overwrite-or-skip decision; honor one already given in the conversation. An
explicit request to resume an interrupted clipping run or reprocess a selected
batch supplies that decision for matching notes this skill owns: re-read each
raw and run the complete workflow from its current files rather than continuing
an old scratch draft. A published pending changed-slug handoff instead follows
[Finish a pending changed-slug handoff](#finish-a-pending-changed-slug-handoff),
which reruns prepare before step 6. Ordinary batch mode never overwrites a
duplicate or selects polished notes on its own.

Record the original bytes, file identity, permissions and metadata before
preparing the replacement: `expected = atomic_move.regular_file_snapshot(<note>)`,
kept unchanged through publication and cleanup. Exclude this one note from its
own dedup scan.

**Body source.** For a named `Articles/` note, remove only its leading Summary
callout and following `___` separator to get the article body. Keep existing
body prose, embeds and still-valid audit placeholders. Do not summarize the old
summary as if it were source prose. For an authorized overwrite or resume from
a raw capture, clean the raw afresh and stage its images and any audit
recoveries to scratch. Match each staged image to an attachment the existing
note already embeds, by identical bytes or else by caption, alt text and
position as in the [completeness audit](completeness-audit.md#inventory-and-match-media).
Use the matching embed name (only its slug changes for a changed slug) and
discard the staged copy; only unmatched images take new numbers. Keep an
equivalent existing converted-GIF embed or placeholder. Carry every unmatched
existing embed into the draft at its old position with its caption, under its
mapped name for a changed slug; never delete an attachment. Prepare requires
every old-slug attachment in the new note, so if an old embed cannot be placed,
stop and ask whether to keep the old slug.

Apply the [frontmatter rules](metadata-verification.md#frontmatter-for-the-polished-note)
to decide which fields regenerate and which preserve user state. In particular,
an unknown or absent review state is not permission to supply `false`; report
that state and any metadata conflicts as required there.

Retain existing figure numbers. An unchanged slug leaves existing attachments
alone; new images continue after the highest occupied number. A changed slug
needs a reviewed dry-run rename plan, not early changes to files the original
note uses.

## Settle a slug before writing images

Different bodies at the same origin are still duplicates: keep the user's
processed version unless they authorize a rewrite. URL variants the normalizer
keeps apart (scheme, an `m.` or AMP host, retained query fields) can pass the
URL check. This slug check treats such a variant as the same article (skip or
ask), never as license to merge silently or to create a `_2` copy.

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
| The same article: a note with the same normalized web origin, or one whose origin differs only by scheme, an `m.`/AMP host or path alias, or query fields the normalizer keeps, and whose title and author/date match this capture's verified metadata | Batch: skip, keep the raw, and report a dedup escape with the existing path and both URLs. Named capture: use the explicit overwrite-or-skip decision, not filename similarity as authorization. If sameness is uncertain, treat it as this row, not the next. A marked research extract is skipped and reported, never offered for overwrite. |
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
2. Preflight both paths under the selected `Articles/`. The original must still
   be this clipping's regular, non-symlink file, with the identity and contents
   read at the start. Check destination occupancy with `os.path.lexists`, not
   `exists` or shell `-e`. Refuse any other occupant. A case/Unicode spelling of
   the same note is allowed only when `os.path.samefile` confirms it and the
   directory has **one** entry with that normalized name. Two distinct hard-link
   entries are not a spelling alias.
3. Stage the finished bytes in a unique hidden temporary directory beside the
   resolved real `Articles/` directory, outside the note folder and on its filesystem. Preserve the original note's
   permissions. Recheck the destination before publication.
4. Publish the complete staged note through the shared
   [safe-write API](../../../shared/SAFE_WRITES.md#call-the-shared-python-api).
   At a free destination (a changed slug), call
   `atomic_move.publish_new(staged, target, atomic_move.regular_file_snapshot, stage_parent)`.
   For a same-name or same-file-spelling rewrite, call
   `atomic_move.replace_expected(staged, target, expected, atomic_move.regular_file_snapshot, stage_dir, stage_parent=stage_parent)`
   with the token recorded above and a fresh `stage_dir`. Never take a fresh
   snapshot at commit time, and never recheck and then call `os.replace`. If
   publication fails, no attachment has moved and the unchanged old note still
   resolves.
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
   Keep that report unchanged for the next step. Its top-level `ok: true` means
   only that the new-name copies exist; remaining dependents are listed in
   `dependency.blockers` (with `dependency.ok: false`), each a `path` and its
   `references`.
   A refusal is not permission to copy by hand; retain the old note and images,
   conditionally withdraw only the exact new note if safe, and report every
   named recovery path.
   After prepare succeeds, place any additional staged remote or recovered
   images through that same guarded image procedure, using the new owner note
   and the new figure numbers. They are separate from the old-image mapping.
   Resolve a refused placement with the documented placeholder and retain its
   scratch file. Once any new image has been published, keep its owner note
   public even if the later dependency handoff remains blocked.
6. Do not finalize while prepare's `dependency.blockers` is nonempty. If every
   blocker is a Wiki entry or recognized MOC (including one in `MOCs/`) and the
   dependency rewrite is authorized, pass `wiki-lint`'s
   [producer-mapped dependency repair](../../wiki-lint/references/external-artifact-repair.md)
   the unchanged prepare JSON, the absolute old and new note paths, and the
   step-7 `dependencies` command exactly as it will be re-run. If the user's
   request did not already authorize rewriting those entries, ask once, naming
   the blocker paths; the prepare report alone is not authorization. The old
   and new images both resolve while it works. Foreign Markdown, unreadable
   files, an incomplete scan, or an unauthorized rewrite remain blockers; leave
   both versions in place and report the pending handoff.
7. After the repair, run the same complete Markdown dependency re-probe:

   ```bash
   python3 '<skill>/scripts/fetch_images.py' dependencies \
       --attachments '<vault>/Sources/Images' \
       --owner-note '<vault>/Articles/<old_slug>.md' --old-slug '<old_slug>'
   ```

   An `ok: true` result means no other scanned note links the old note or
   references one of its old image names. Anything else leaves both versions
   resolving and returns to step 6; a new dependency is a blocker, not
   permission for an incidental rewrite.
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
9. After finalize succeeds, conditionally remove the distinct old note with
   `atomic_move.remove_expected(old_note, expected, atomic_move.regular_file_snapshot, stage_dir, stage_parent=stage_parent)`,
   passing the token recorded before the rewrite (or when finishing a pending
   handoff) and a fresh `stage_dir`; clean that `stage_dir` only after success.
   Do not use a check followed by `unlink`, remove it for the same-file
   spelling case, or remove it if it changed. A cleanup refusal
   keeps the path; never delete first and report broken references afterward.
   Report a mixed state rather than hiding it.

If the filesystem cannot provide safe publication, stop and report the refusal.
Read back the published note and verify its embeds. Report note and attachment
renames and the dependency re-probe result; do not modify unrelated notes or
claim a failed rename completed.

### Finish a pending changed-slug handoff

When the user asks to finish or resume a pending handoff left by step 6
(naming either note of the same-URL pair), confirm that both notes share the
web origin, the old note embeds the old-slug images and the new note embeds
their mapped names. Record `expected = atomic_move.regular_file_snapshot(<old note>)`
from the old note you read for this check; step 9 passes that token. Rerun
`rename --phase prepare --dry-run` with the original paths and slugs, review
it, then run the identical live command. Copies prepared earlier are verified
as `already-prepared`, and it returns the current mapping and dependency
report. Continue at step 6, then steps 7–9. Do not re-clean the raw or redraft
either note. A plain reprocess request for either note reports the pending
handoff and asks whether to finish it first.
