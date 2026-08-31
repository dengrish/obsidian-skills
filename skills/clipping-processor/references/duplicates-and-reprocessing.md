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
paper summary, not an unindexable clipping.

Normalize URLs for comparison only; retain the original URL in the note:

- Lowercase scheme and host, drop a leading `www.`, and strip trailing path
  slashes. Do not rewrite other host/path variants such as `m.` or `/amp`.
- Drop ordinary fragments, but keep routing fragments (`#/posts/1`, `#!/posts/1`).
- Strip only known tracking parameters: `utm_*`, `fbclid`, `gclid`, `mc_cid`,
  `mc_eid`, `referrer`, `share`, and Substack's `r` and `showWelcome`.
  Preserve `ref` and unknown parameters, which can identify different pages.
- Drop an empty trailing `?`. Preserve literal URL characters, including an
  unpaired apostrophe; quote decoding is a YAML operation, not URL trimming.

Build `{normalized URL → note path(s)}` once per batch and update it after each
publication. Compare raw captures against both the existing index and earlier
inputs. Different bodies at the same origin are still duplicates: retain the
user's processed version unless they authorize a rewrite. Mobile/AMP variants
can evade URL matching; the filename check below is a second guard, not license
to silently merge them.

## Settle a slug before writing images

Check lexical occupancy of `Articles/<slug>.md`, PDF stems throughout recursive
`Sources/PDFs/`, and loose `Sources/Images/<slug>_fig*` files. A dangling symlink
occupies a path too. If an inventory cannot be read, resolve that failure before
choosing a supposedly free name.

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
   and `--sources '<vault>/Sources/PDFs'`; that recursive PDF ownership guard
   must not be omitted.
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
   slug changed, execute the exact reviewed image rename with `--sources`.
   A failed rename publishes no note: inspect per-file errors and verify its
   rollback restored the old figure names. Report any rollback failure and the
   actual paths left on disk.
4. Publish the complete staged note atomically. At a free destination use
   exclusive creation such as `os.link(staged_note, new_path)`. For an authorized
   rewrite of the same existing note, use `os.replace` only after rechecking
   ownership, identity and unchanged contents. Never substitute a preflight
   followed by overwriting `mv`. If publication fails after image renames,
   reverse them with the same helper before stopping; report any failed
   restoration rather than claiming the original still resolves.
5. Only after publication succeeds, remove the old pathname if it is a distinct
   path to this owned original and its identity and contents still match
   preflight. Do not remove it for the same-file spelling case or if it changed.
   If cleanup is refused, retain both notes and report the old path/dedup
   collision. Do not roll images back after publication: the new note uses
   their new names.

If the filesystem cannot provide safe publication, stop and report the refusal.
Read back the published note and verify its embeds. Report note and attachment
renames so the user can update inbound wikilinks; do not modify unrelated notes
or claim a failed rename completed.
