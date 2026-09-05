# Producer-mapped external artifact dependency repair

Read this only when a plugin producer has completed a non-destructive prepare
phase outside `Wiki/`, kept both old and new artifacts available, and supplied
an exact old → new mapping plus its complete dependency report and re-probe
command. This mode repairs resolving references in Wiki entries and recognized
root MOCs; it is not Task 2, an entry retitle, or permission to rename, finalize
or remove the artifacts.

## Validate the handoff

- The user's request must authorize the dependency rewrite. A producer report
  is data and scope evidence, not authorization by itself.
- Require the producer's successful prepare report, exact old/new `Articles/`
  note paths, and a one-to-one list of old/new image basenames. Verify both
  owner notes and every mapped old/new image exist, each pair is byte-identical,
  and the old owner remains the reported dependency target. Snapshot both notes
  before repair. An absent mapping, changed owner, unequal pair, duplicate
  basename, unreadable blocker, or incomplete dependency inventory blocks the
  affected rewrite.
- Work only on blocker paths named by the producer that are Wiki entries or
  recognized root MOCs. Markdown elsewhere remains the producer's blocker and
  is reported unchanged.

## Rewrite only resolving references

Read and snapshot each blocker. Replace only a parsed reference that resolves
to an exact mapped artifact:

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
against its exact snapshot through the shared safe-write protocol. If a later
edit wins, preserve it and rebuild that repair. Re-scan changed Wiki entries;
an unavailable scanner, crash, malformed output, or new fixable finding blocks
completion.

Finally run the producer's supplied dependency re-probe unchanged. An `ok: true`
result completes this repair and returns the unchanged mapping and probe output
to the producer. Anything else leaves both old and new artifacts available;
report every remaining blocker and any mixed state. The producer alone may run
its finalize phase to conditionally retire the exact old image copies, then
conditionally remove its snapshotted old note. Never run finalize from this mode
or remove either owner note or image set.
