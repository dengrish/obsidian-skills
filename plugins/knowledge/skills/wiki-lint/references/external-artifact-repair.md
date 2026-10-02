# Producer-mapped external artifact dependency repair

Read this only when a plugin producer has completed a non-destructive prepare
phase outside `Wiki/`, kept both old and new artifacts available, and supplied
an exact old → new mapping plus its complete dependency report and re-probe
command. This mode repairs resolving references in Wiki entries, recognized
MOCs in `MOCs/`, and recognized legacy vault-root MOCs. It is not Task 2, an entry
retitle, or permission to rename, finalize or remove the artifacts.

## Validate the handoff

- The user's request must authorize the dependency rewrite. A producer report
  is data and scope evidence, not authorization by itself.
- Require the producer's successful prepare report, exact old/new `Articles/`
  note paths, and a one-to-one list of old/new image basenames. Verify both
  owner notes exist and still identify the same current web origin verified by
  prepare. Their bytes need not match: the new note contains the new image
  names and may contain the authorized reprocessing changes. Require every
  mapped old/new image pair to exist and remain byte- and mode-identical, and
  the old owner to remain the reported dependency target. Snapshot both notes
  before repair. An absent mapping, changed origin, unequal image pair, duplicate
  basename, unreadable blocker, or incomplete dependency inventory blocks the
  affected rewrite.
- A same-note re-stem report instead names one renamed
  `Articles/<new_slug>.md` as both the old and the new owner, for images a
  rename left under the old stem. Require that no `Articles/<old_slug>.md`
  exists, that the renamed note still identifies the origin prepare verified,
  and the image pairs above; snapshot that one note. No old note remains to
  rewrite links to, so only exact mapped old image references are rewritten.
  Its re-probe is `fetch_images.py dependencies --new-slug '<new_slug>'` with
  that note as `--owner-note`.
- Work only on blocker paths named by the producer that are Wiki entries or
  recognized MOCs in `MOCs/` or legacy vault-root MOCs. Markdown elsewhere remains
  the producer's blocker and is reported unchanged.

## Rewrite only resolving references

Read and snapshot each blocker, and keep its Step 0 scan findings as the
pre-repair baseline. Replace only a parsed reference that resolves to an exact
mapped artifact:

- a `sources:` wikilink, body/Related link, note transclusion, or MOC link to
  the old `Articles/` note receives the mapped note destination while retaining
  its label, heading or block anchor, and surrounding YAML/Markdown form;
- an Obsidian embed or Markdown image destination naming an exact mapped old
  image receives its mapped image name while retaining embed dimensions, alt
  text, and any path form that still resolves under the vault layout.

Never run a free-text replacement. Preserve plain prose, URLs, code/listings,
suggestion logs, unrelated `sources:`, and every unmatched or ambiguous
reference. This mode changes dependency spelling only: it does not change
`created:`, `updated:`, `read:`, content claims, parents, or MOC structure.

Stage every completed blocker outside scanned vault folders and publish each
against its exact snapshot with `publish_files.py`
([publishing](../SKILL.md#publishing)). If a later
edit wins, preserve it and rebuild that repair. Re-scan changed Wiki entries;
an unavailable scanner, crash, malformed output, or a fixable finding absent
from that baseline blocks completion. Report pre-existing findings unchanged.

Finally run the producer's supplied dependency re-probe unchanged. An `ok: true`
result completes this repair and returns the unchanged mapping and probe output
to the producer. Anything else leaves both old and new artifacts available;
report every remaining blocker and any mixed state. The producer alone may run
its finalize phase to conditionally retire the exact old image copies, then
conditionally remove its snapshotted old note. Never run finalize from this mode
or remove either owner note or image set.
