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
overwrite-or-skip decision; honor one already given in the conversation. Batch
mode never overwrites a duplicate or selects polished notes on its own.

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
paper summary, not an unindexable clipping. Decode the complete note strictly as
UTF-8 (accepting a leading BOM) before trusting its frontmatter; invalid bytes
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
   that draft. Review any image rename with `fetch_images.py rename --dry-run`
   using both `--sources '<vault>/Sources/PDFs'` and
   `--owner-note '<vault>/Articles/<old_slug>.md'`. The helper snapshots the
   unchanged note, requires a web URL as its first current `sources:` item, and
   requires every attachment basename in the plan to appear as an exact
   rendered filename-only embed. Neither that positive clipping evidence nor
   the recursive PDF ownership guard may be omitted. Migrate a legacy scalar
   `source:` before this destructive attachment operation. In a canonical
   vault the helper also reads every Markdown note outside the owner and refuses
   inbound links to the old note, references to any old image name, unreadable
   notes and incomplete folder walks. It reports the exact blocker paths. Do
   not interpret a failed inventory as permission to proceed or rewrite those
   notes incidentally as part of the clipping reprocess.
2. Preflight both paths under the selected `Articles/`. The original must still
   be this clipping's regular, non-symlink file, with the identity and contents
   read at the start. Check destination occupancy with `os.path.lexists`, not
   `exists` or shell `-e`. Refuse any other occupant. A case/Unicode spelling of
   the same note is allowed only when `os.path.samefile` confirms it and the
   directory has **one** entry with that normalized name. Two distinct hard-link
   entries are not a spelling alias.
3. Stage the finished bytes in a unique temporary directory beside `Articles/`,
   outside the note folder and on its filesystem. Preserve the original note's
   permissions. Recheck the destination before any attachment mutation. If the
   slug changed, execute the exact reviewed image rename with `--sources` and
   the unchanged old `--owner-note`.
   A failed rename publishes no note: inspect per-file errors and verify its
   rollback restored the old figure names. Report any rollback failure and the
   actual paths left on disk.
4. Publish the complete staged note through the shared
   [safe-write protocol](../../../shared/SAFE_WRITES.md). At a free destination
   use exclusive creation. For an authorized rewrite, displace and verify the
   exact snapshotted note before linking the staged replacement into the empty
   public name; a recheck followed by `os.replace` still has a race. If
   publication fails after image renames, reverse them with the same helper
   before stopping; report any failed restoration or named recovery path rather
   than claiming the original still resolves.
5. After publication, re-probe the whole Markdown dependency surface before
   old-path cleanup:

   ```bash
   python3 '<skill>/scripts/fetch_images.py' dependencies \
       --attachments '<vault>/Sources/Images' \
       --owner-note '<vault>/Articles/<old_slug>.md' --old-slug '<old_slug>'
   ```

   An `ok: true` result means no other scanned note links the old note or
   references one of its old image names. Only then conditionally remove a
   distinct old pathname through the shared protocol: displace it, verify the
   preflight identity and contents, then discard only the verified version. Do
   not use a check followed by `unlink`, remove it for the same-file spelling
   case, or remove it if it changed. If the re-probe or cleanup is refused,
   retain the old note path and exact blocker report; never delete first and
   tell the user about broken inbound references afterward. A dependency first
   introduced after the image rename is a concurrent change, not permission to
   rewrite another note. Stop without declaring completion and either obtain
   authorization for one complete dependency rewrite or roll the replacement
   back through the same guarded paths. If rollback cannot safely restore every
   old note and image path, retain every recovery path and report the mixed
   state rather than hiding it.

If the filesystem cannot provide safe publication, stop and report the refusal.
Read back the published note and verify its embeds. Report note and attachment
renames and the dependency re-probe result; do not modify unrelated notes or
claim a failed rename completed.
