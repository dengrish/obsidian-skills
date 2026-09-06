# Source-backed refactors of existing entries

Read this only when the current request explicitly authorizes a split, merge,
deletion, or redistribution of existing wiki content. An ordinary lint run
reports these candidates and stops; a long note, duplicate wording, or scanner
similarity never activates this mode by itself. Authorization already present
in the request is sufficient. This protocol requires no separate human review.

A correction confined to one named entry and supported only by sources it
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
   entry and resolve its cited source files. For a PDF/summary pair, verify
   claims against the original PDF. A missing, unreadable, or ambiguous source
   blocks only the factual movement it was needed to justify; preserve and
   report that content instead of filling gaps from memory.
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
   no additional approval. Historical notes in vault-root `Investments/`
   remain outside this repair scope, including through linked-folder aliases.
   If one references an identity being retired, preserve that record and retain
   the referenced old entry; report the unresolved dependency.

Pure retitles use the dedicated
[entry-retitle protocol](../../../shared/CONVENTIONS.md#retitling-an-existing-wiki-entry),
and semantic-invalid alias removals use the preceding alias-removal protocol.
Do not disguise either as a split or merge to avoid its authorization and
complete-reference-rewrite gate.

## Build the refactored entries

- Apply wiki-build's current field, prose, equation, media, link, and
  flashcard rules. Every result is a source-backed atomic entry; no temporary redirect is
  created.
- A split moves each verified claim, equation, exhibit, and citation to its
  canonical owner. Leave enough concise relationship prose and wikilinks for
  orientation, without duplicating the full explanation across the results.
  A newly created split note gets today's `created:` and `updated:` dates and
  `read: false`. A retained original keeps `created:` and follows the builder's
  body-change rule for `updated:` and `read:`.
- A merge chooses one collision-free surviving identity from the evidence and
  requested scope. Preserve that entry's `created:` and user-owned appearance
  fields, integrate nonduplicate claims, union only valid source contributions
  and same-entity aliases, and apply the builder's body-change rule for
  `updated:` and `read:`. Report conflicting user-owned metadata from an entry
  that may be removed rather than silently selecting a value.
- Preserve the retained primary flashcard's recognized scheduling attachments
  and block ID byte-for-byte. Do not discard an extra card merely to enforce
  the one-card presentation rule. Preserve every card unless the authorized
  refactor inventory assigns its tested claim to a retained or new entry, or
  the request explicitly names that card for deletion; quote every moved or
  removed card with all attachments in the report. Preserve existing exhibits
  unless source evidence and the requested refactor establish their new owner.

## Publish in dependency order

Stage the complete result outside scanned vault folders, on the target
filesystem (resolving a symlinked output directory before choosing its private
stage parent), and use the shared safe-write protocol throughout. A refactor spans several files but is not one
filesystem transaction, so order prevents a disappearing target:

1. Publish every new entry exclusively and conditionally replace retained
   entries from the exact snapshots used to plan them.
2. Rewrite each inspected inbound link, then run Task 3 over the complete
   connected hierarchy closure so `parents:` and MOCs come from one tree.
3. Re-scan and independently refresh the complete live-reference inventory.
   Verify that every changed link or transclusion resolves with its retained
   anchor, every moved claim keeps a valid source, and no obsolete destination
   remains referenced; the Wiki scan alone cannot establish this postcondition.
4. Only then conditionally remove an obsolete entry. Every substantive claim,
   equation, exhibit, card (including its scheduling attachments and block ID),
   citation, and user-owned metadata value must either survive in an identified
   destination or be named explicitly by the authorized request as content to
   delete. Missing or unverified source support is a reason to retain the
   content, never evidence that it is disposable. If a later edit or an
   unresolved inbound reference appears, retain the file and report the mixed
   state; never force cleanup to make the refactor look done.

Finish with Tasks 1–3 on the affected closure and re-scan until all fixable
findings introduced by the refactor are gone. Report source evidence, created,
retained, and removed paths, every inbound rewrite, review-state decisions,
unresolved content, and the final scan counts.
