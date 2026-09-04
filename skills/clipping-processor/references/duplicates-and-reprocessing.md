# Duplicates and reprocessing

- [Reprocessing an existing note](#reprocessing-an-existing-note)
- [Manual dedup index](#manual-dedup-index)
- [Settle a slug before writing images](#settle-a-slug-before-writing-images)
- [Publish an approved replacement](#publish-an-approved-replacement)

Use this reference for an approved rewrite, a filename collision, or the manual
fallback when the dedup helper cannot run. The normal scan and its verdicts are
in [Select the captures](../SKILL.md#1-select-the-captures-and-check-ownership).

## Reprocessing an existing note

Only a note whose first current `sources:` item is a web URL belongs to this
skill. Read legacy `source:` only when `sources:` is absent; malformed or
ambiguous current metadata cannot establish ownership through a stale value.
A PDF wikilink belongs to `paper-summarizer` and is not a clipping rewrite.

Naming a file already in `Articles/` for reprocessing authorizes that owned
rewrite. Naming a raw capture that matches another note requires an explicit
overwrite-or-skip decision; honor one already given in the conversation. An
explicit request to resume an interrupted clipping run or reprocess a selected
batch supplies that decision for matching notes this skill owns: re-read each
raw and run the complete workflow from its current files rather than continuing
an old scratch draft. Ordinary batch mode never overwrites a duplicate or
selects polished notes on its own.

Record the original bytes, file identity, permissions and metadata before
preparing the replacement. Exclude this one note from its own dedup scan.
Remove only its leading Summary callout and following `___` separator to get
the article body. Keep existing body prose, embeds and still-valid audit
placeholders. Do not summarize the old summary as if it were source prose.

Regenerate the summary, `format`, `description` and `tags`; report that manual
edits to those generated fields were replaced. Preserve `read:` as found, including an absent/unknown state, plus the capture URL,
clipping date and unrelated user metadata. Report an absent/unknown review state;
do not fill it with `false` to satisfy the generated schema. Apply only the targeted legacy migrations in
[frontmatter](metadata-verification.md#frontmatter-for-the-polished-note).

Retain existing figure numbers. An unchanged slug leaves existing attachments
alone; new remote images use the next free number. A changed slug needs a
reviewed dry-run rename plan, not early changes to files the original note uses.

## Manual dedup index

Use this only if `dedup_index.py` is unavailable and the complete `Articles/`
scope can still be read. An unreadable directory is a failed inventory, not an
empty one. Stop before notes or images are created if a complete scan cannot be
established.

Read each Markdown note's closed YAML frontmatter and first current `sources:`
item. Only if that key is absent may legacy scalar `source:` supply the origin.
Keep quoted scalars and lists intact; do not extract a later URL or infer
ownership from duplicate keys, an empty current list or malformed YAML. Report
unindexable notes and existing URL collisions. A valid first PDF wikilink is a
PDF reading note, not an unindexable clipping. Decode the complete note strictly
as UTF-8 (accepting a leading BOM) before trusting its frontmatter; invalid bytes
anywhere make the note unindexable rather than an owner.

Normalize URLs for comparison only; retain the original URL in the note:

- Lowercase scheme and host, drop a leading `www.`, and strip trailing path
  slashes. Do not rewrite other host/path variants such as `m.` or `/amp`.
- Drop ordinary fragments, but keep routing fragments (`#/posts/1`, `#!/posts/1`).
- Strip only conventional tracking parameters: `utm_*`, `fbclid`, `gclid`,
  `mc_cid` and `mc_eid`; strip `r` and `showWelcome` only on `substack.com`
  and its subdomains. Preserve `ref`, `referrer`, `share`, generic-domain `r`
  and `showWelcome`, and unknown parameters, which can identify different pages.
- Preserve the order and original spelling of surviving query fields. Origins
  may distinguish `+` from `%20`, a bare flag from `flag=`, or signed query
  bytes, as well as interpret repeated keys in order. Parsing/re-encoding or
  sorting them can collapse distinct pages into one false duplicate.
- Drop an empty trailing `?`. Preserve literal URL characters, including an
  unpaired apostrophe; quote decoding is a YAML operation, not URL trimming.

Build `{normalized URL → note path(s)}` once per batch and update it after each
publication. Compare raw captures against both the existing index and earlier
inputs. Different bodies at the same origin are still duplicates: retain the
user's processed version unless they authorize a rewrite. Mobile/AMP variants
can evade URL matching; the filename check below is a second guard, not license
to silently merge them.

## Settle a slug before writing images

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
| Note with the same normalized web origin | Batch: skip, keep raw, report the existing path and both URLs if the initial check missed them. Named capture: use the explicit overwrite decision, not filename similarity as authorization. |
| Different article, PDF summary, PDF or loose figure set | Choose `<slug>_2`, then `_3`, … until the note and image stem are free. Use the suffix for both. Report the collision. |
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
3. Stage the finished bytes in a unique temporary directory beside `Articles/`,
   outside the note folder and on its filesystem. Preserve the original note's
   permissions. Recheck the destination before publication.
4. Publish the complete staged note through the shared
   [safe-write protocol](../../../shared/SAFE_WRITES.md). At a free destination
   use exclusive creation. For an authorized rewrite, displace and verify the
   exact snapshotted note before linking the staged replacement into the empty
   public name; a recheck followed by `os.replace` still has a race. If
   publication fails, no attachment has moved and the unchanged old note still
   resolves.
5. A same-path rewrite finishes after read-back. For a changed slug, keep both
   notes in place and review the prepare phase before running it live:

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
   Keep that report unchanged for the next step.
   A refusal is not permission to copy by hand; retain the old note and images,
   conditionally withdraw only the exact new note if safe, and report every
   named recovery path.
6. Do not finalize while prepare reports blockers. If every blocker is a Wiki
   entry or recognized root MOC and the dependency rewrite is authorized, pass
   the exact prepare report and mapping to `wiki-linter`'s
   [producer-mapped dependency repair](../../wiki-linter/references/external-artifact-repair.md).
   The old and new images both resolve while it works. Foreign Markdown,
   unreadable files, an incomplete scan, or an unauthorized rewrite remain
   blockers; leave both versions in place and report the pending handoff.
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
8. With an `ok: true` re-probe, review and run the finalize phase using the
   identical arguments from prepare:

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
   only the exact old image copies and leaves the new copies in place. If any
   check fails, it retains both sets and reports the blocker or recovery path.
9. After finalize succeeds, conditionally remove the distinct old note through
   the shared protocol: displace it, verify the preflight identity and contents,
   then discard only that verified version. Do not use a check followed by
   `unlink`, remove it for the same-file spelling case, or remove it if it
   changed. A cleanup refusal keeps the path; never delete first and report
   broken references afterward. Report a mixed state rather than hiding it.

If the filesystem cannot provide safe publication, stop and report the refusal.
Read back the published note and verify its embeds. Report note and attachment
renames and the dependency re-probe result; do not modify unrelated notes or
claim a failed rename completed.
