# Source-backed refactors of existing entries

Read this only when the current request explicitly authorizes a split, merge,
deletion, consolidation, redistribution or retitle of existing wiki content, or
an alias removal. An ordinary lint run
reports these candidates and stops; a long note, duplicate wording, or scanner
similarity never activates this mode by itself. Authorization already present
in the request is sufficient. This protocol requires no separate human review.
A pure retitle or semantic-invalid alias removal keeps its own protocol below
([retitle](#retitle-an-entry), [alias removal](#remove-a-semantic-invalid-alias));
never disguise either as a split or merge to avoid its authorization and
complete-reference-rewrite gate.

A correction confined to one existing entry and supported only by sources it
already cites uses [source-backed correction](source-backed-corrections.md), not
this structural protocol. Evidence from a source new to the target belongs to
`wiki-build` unless the authorized operation necessarily redistributes
existing content across entries.

This is maintenance of existing knowledge, not a second extraction route.
`wiki-build` still owns turning a new source into new candidates. A refactor
may create a split note only for a subject already substantively present in the
affected entry and supported by its durable source.

## Establish evidence and complete scope

1. Run the normal Step 0 scan over the whole wiki. Snapshot every affected
   entry and resolve its cited sources: vault files, and cited URLs read online.
   For a PDF/summary pair, verify claims against the original PDF. A missing,
   unreadable, unreachable or ambiguous source
   blocks only a movement that depends on it, such as a disputed or
   source-specific claim; accurate, well-established content may move to its
   owner without it. Never fill a gap with uncertain recollection.
2. Prove the proposed boundary. A split needs two or more independently
   definable subjects, each with source-supported substance. A merge needs one
   entity under alternate names, not merely related concepts. Inherent
   mechanisms, stages, conditions, and limitations remain with their subject.
3. Inventory every live reference to a slug or alias that may disappear across
   all vault Markdown, including body/Related links, `parents:`, MOCs, note
   transclusions, and relative Markdown links. Resolve each destination from
   its owning note, retaining path qualification and heading/block anchors.
   The entry scanner omits some of these surfaces, so scanner silence cannot
   prove that no inbound references remain. A split can send different
   references to different targets; an ambiguous reference remains unchanged
   and prevents deletion of the old entry. Preserve code/examples, independent
   source origins, distinct targets, image embeds, and literal suggestion-log examples;
   token equality never authorizes a rewrite. If an actual dependency owner is
   outside explicit write scope, report that blocker and retain the old entry.
   Existing authorization that covers the refactor and its dependencies needs
   no additional approval. Notes in vault-root `Investments/`
   remain outside this repair scope, including through linked-folder aliases.
   If one references an identity being retired, preserve that record and retain
   the referenced old entry; report the unresolved dependency.

## Build the refactored entries

- Apply wiki-build's current field, prose, equation, media, link, and
  flashcard rules. Every result is a source-backed atomic entry; no temporary redirect is
  created.
- A split moves each verified claim, equation, exhibit, and citation to its
  canonical owner. Leave enough concise relationship prose and wikilinks for
  orientation, without duplicating the full explanation across the results.
  A newly created split note gets today's `created:` and `updated:` dates and
  `read: false`. A retained original keeps `created:` and follows the builder's
  [body-change rule](../../wiki-build/references/merge.md#the-read-reset) for
  `updated:` and `read:`.
- A merge chooses one collision-free surviving identity from the evidence and
  requested scope. Preserve that entry's `created:` and user-owned appearance
  fields, integrate nonduplicate claims, union only valid source contributions
  and same-entity aliases, and apply the builder's
  [body-change rule](../../wiki-build/references/merge.md#the-read-reset) for
  `updated:` and `read:`. Report conflicting user-owned metadata from an entry
  that may be removed rather than silently selecting a value.
- A consolidation keeps the full treatment of an explanation duplicated across
  entries in its most specific canonical owner, moving any claim the owner
  lacks, and leaves each other entry one relating sentence and a link.
- Preserve the retained primary flashcard's recognized scheduling attachments
  and block ID byte-for-byte. Of the merged entries' primary cards, a merge
  keeps only the survivor's: a retired entry's primary card tests the same
  entity, so the merge authorization removes it. Do not discard a legacy
  extra merely to enforce the card-set rule; preserve it unless the
  authorized refactor inventory assigns its tested claim to a retained or new
  entry, or the request explicitly names that card for deletion. Quote every
  moved or removed card with all attachments in the report. Preserve existing
  exhibits unless source evidence and the requested refactor establish their
  new owner.

## Publish in dependency order

Stage complete drafts under `<scratch>` and publish creates and replacements
with `publish_files.py` ([publishing](../SKILL.md#publishing)). Step 4's
conditional removal uses `remove_expected` in a private driver under the
[shared safe-write protocol](../../../shared/SAFE_WRITES.md#remove-or-move-an-old-pathname-conditionally),
with the token rebuilt from the old entry's original snapshot record as
[publishing](../SKILL.md#publishing) describes. A refactor spans several files
but is not one filesystem transaction, so order prevents a disappearing
target:

1. Publish every new entry exclusively and conditionally replace retained
   entries from the exact snapshots used to plan them.
2. Rewrite each inspected inbound link. An otherwise unchanged entry whose
   only change is a rewritten link or `parents:` value keeps its dates and
   `read:`.
3. Re-scan and independently refresh the complete live-reference inventory.
   Verify that every changed link or transclusion resolves with its retained
   anchor, every moved source-specific claim keeps its source, and no obsolete destination
   remains referenced; the Wiki scan alone cannot establish this postcondition.
4. Only then conditionally remove an obsolete entry. Every substantive claim,
   equation, exhibit, card (including its scheduling attachments and block ID),
   citation, and user-owned metadata value must either survive in an identified
   destination or be named explicitly by the authorized request as content to
   delete. A merged-away primary card counts as accounted for once it is
   quoted in the report, because the survivor's primary card tests the same
   entity. An inbound link or embed that targets that card's block ID cannot
   keep its anchor, so it is an unresolved inbound reference that retains the
   old entry. Missing or unverified source support is a reason to retain the
   content, never evidence that it is disposable. If a later edit or an
   unresolved inbound reference appears, retain the file and report the mixed
   state; never force cleanup to make the refactor look done. A rollback
   restores only files whose published bytes are still unchanged.

Finish with Tasks 1–3 on the affected closure and re-scan until all fixable
findings introduced by the refactor are gone. Report source evidence, created,
retained, and removed paths, every inbound rewrite, review-state decisions,
unresolved content, and the final scan counts.

## Retitle an entry

A title or slug correction is a whole-entry rename, not an alias-list edit; a
request that explicitly authorizes it activates this protocol.

1. Derive the destination with `slugify.py`, then run every create-time
   collision probe against filenames, aliases and the other planned names
   with wiki-build's `vault_index.py` and `find_collisions.py`
   ([its step 3](../../wiki-build/SKILL.md#3-resolve-against-existing-entries)).
   Record the source entry and the free destination with `publish_files.py
   snapshot` before reading the entry's complete bytes and all user-owned
   metadata; the source record keeps its identity, digest and permissions.
   Refuse an occupied or ambiguous portable-equivalent destination; never
   pick one owner by directory order.
2. Rebuild the entry coherently under the new canonical title. Preserve its
   `created:`, sources, review state, scheduling metadata, appearance/publish
   properties and substantive content. A retitle alone advances `updated:`
   and never resets `read:`. Keep the old slug as an alias only when it is
   still a valid same-entity name; a proven wrong or misleading name is not
   retained merely to make old links resolve.
3. Inventory the references to the old filename and its aliases under
   [step 3 above](#establish-evidence-and-complete-scope). Rewrite only
   references that resolve to this exact owner, preserving display labels,
   headings, block anchors and surrounding bytes; a Related-footer label
   becomes the target's canonical title. Source evidence and external URLs
   are never rewritten because their text matches.
4. Publish [in dependency order](#publish-in-dependency-order): the
   destination entry exclusively, then every snapshotted inbound and hierarchy
   file conditionally, re-reading every result. Before removing the exact old
   entry version with `remove_expected` against step 1's source record,
   re-scan: every changed link must resolve uniquely to the new entry, the
   old slug must have no unresolved inbound surface, and the new entry must
   pass the current entry rules. Then rebuild the connected Task 3 closure
   from the resulting tree and re-scan.

## Remove a semantic-invalid alias

An explicitly authorized removal first identifies the canonical owner. It then
inventories and rewrites, under
[step 3 above](#establish-evidence-and-complete-scope), every real reference
that resolves through the alias and every link to this entry whose alias label
names a different entity, publishing
[in dependency order](#publish-in-dependency-order). A blocked dependency
retains the alias until it can be repaired. Delete the alias only after
verifying that no ambiguous owner, inbound alias-target link or such
mislabelled link remains. The removal advances the owner's `updated:` and
keeps its `read:`; an otherwise unchanged entry whose only change is a
rewritten link keeps its dates and `read:` under the
[shared date rule](../../../shared/CONVENTIONS.md#2a-wiki-entry--wikimd).
