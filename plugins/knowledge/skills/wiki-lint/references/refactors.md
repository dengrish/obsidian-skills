# Source-backed refactors of existing entries

Read this before Task 1b consolidates a duplicated explanation, moves a
misplaced passage to its owner, retitles an entry, removes a semantic-invalid
alias or creates a missing entry, and when the current request explicitly
authorizes a split, merge or deletion. An ordinary run performs the first
five once its evidence identifies the duplicate and its owner, the wrong
title, the invalid alias or the missing concept. Splits, merges and deletions
run only on an explicit request: an ordinary run proposes them, and a long
note, duplicate wording, or scanner similarity never activates one. This
skill's definition of an ordinary run, or authorization already present in
the request, is sufficient. This protocol requires no separate human review.
A pure retitle or semantic-invalid alias removal keeps its own protocol below
([retitle](#retitle-an-entry), [alias removal](#remove-a-semantic-invalid-alias));
never disguise either as a split or merge to avoid its
complete-reference-rewrite gate.

A correction confined to one existing entry and supported only by sources it
already cites uses [source-backed correction](source-backed-corrections.md), not
this structural protocol. Evidence from a source new to the target belongs to
`wiki-build` unless the authorized operation necessarily redistributes
existing content across entries.

This is maintenance of existing knowledge, not a second extraction route.
`wiki-build` still owns turning a new source into new candidates. A refactor
may create a split note only for a subject already substantively present in the
affected entry and supported by its durable source. Task 1b's
[missing-entry rule](#create-a-missing-entry) is the only other creation, and
it is limited to a concept the wiki already relies on.

## Establish evidence and complete scope

1. Use the current pass's whole-wiki Step 0 scan, or run one for a standalone
   request. Snapshot every affected entry and resolve its cited sources: vault
   files, and cited URLs read online. For a PDF/summary pair, verify claims
   against the original PDF. A missing, unreadable, unreachable or ambiguous
   source blocks only a movement that depends on it, such as a disputed or
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
   token equality never authorizes a rewrite. The rewrite scope covers
   references in `Wiki/`, `MOCs/` and `parents:`, and in other vault notes,
   such as the navigation links of `Articles/` notes and `Reviews/` logs
   (never their claims, issue text or `sources:`). A dated historical record, such as a `wiki-review-*.md` report, stays
   untouched: report its links as now unresolved; they do not retain the old
   entry. The ordinary run's or the request's authorization covers these
   rewrites, with no additional approval. Notes in vault-root `Investments/`
   remain outside this repair scope, including through linked-folder aliases.
   If one references an identity being retired, preserve that record and retain
   the referenced old entry; report the unresolved dependency. Any other
   dependency owner this protocol cannot write is reported the same way.

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
- A consolidation keeps the full treatment of an explanation, argument,
  worked example or property with its justification duplicated across
  entries in its owner: the most specific entry whose subject it is about. A
  property every member of a family shares belongs to the family's entry
  (weight penalties' scale sensitivity to Regularization, not Ridge
  regression), and an argument about how a metric behaves belongs to that
  metric (the rare-positive argument to False positive rate); plots built on
  the metric keep the consequence and a link. Before choosing the owner,
  search the whole Wiki for the passage's distinctive tokens (a figure with
  its unit, a gene or experiment name) and plan every hit in the same
  consolidation. Between equally specific entries, the owner is the one
  already holding the fullest version, then the alphabetically first slug.
  If the owner already explains it, trim each other copy to its consequence
  for that entry in one clause, linked to the owner; the clause drops the
  owner's reasoning (no because- or since-clause restating it) and keeps a
  source verdict only in the owner, but never drops a fact that entry's core
  facets need. Otherwise move the fullest version into the owner, verified
  against the owner's cited sources or accurate background and carrying each
  source-specific claim's existing citation (adding that source to the
  owner's `sources:` when needed), then trim the others. A trimmed copy may
  lose links that served only the removed passage. A worked example lives in
  one entry; the others state its consequence and link the owner. Resolve a
  conflicting claim in the passage before consolidating it; while it stays
  unresolved, leave every copy unchanged and keep the conflict open, and never
  trim a copy that disagrees with the owner's. The owner and each trimmed
  entry follow the [Dates](../SKILL.md#dates) rule.
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
conditional removal uses `publish_files.py remove` under the
[shared safe-write protocol](../../../shared/SAFE_WRITES.md#remove-or-move-an-old-pathname-conditionally),
against the old entry's original snapshot record, as
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
   anchor, every moved source-specific claim keeps its source, and no obsolete
   destination remains referenced outside untouched historical records; the
   Wiki scan alone cannot establish this postcondition.
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

Inside a default pass, that pass's refresh, Task 2 and Task 3 finish the
refactor, with no nested pass; a standalone request finishes with Tasks 1, 2
and 3 on the affected closure, without Task 1b. Either way, re-scan until all fixable findings
introduced by the refactor are gone. Report source evidence, created,
retained, and removed paths, every inbound rewrite, untouched historical
records with their now-unresolved links, review-state decisions, unresolved
content, and the final scan counts.

## Retitle an entry

A title or slug correction is a whole-entry rename, not an alias-list edit.
Task 1b runs this protocol when all of these hold:

- the title is a bare cross-domain term under QC item 5 (a word or phrase in
  test (c)'s corpus, or a term that fails test (a), of the builder's
  [disambiguation rule](../../wiki-build/references/special-titles.md#cross-domain-term-disambiguation)),
  the title is itself an API identifier (QC item 6), or the filename differs
  from its title's slug;
- the qualified or conceptual title is determinate;
- and the destination slug is free.

Otherwise it reports the case with its blocker. For an existing entry, test
(a) must actually fire, its encyclopedia landing checked as a disambiguation
page or another sense; the unchecked-landing default governs new titles
only, so doubt alone is reported. A request that explicitly authorizes a
retitle also activates this protocol.

1. Derive the destination with `slugify.py`, then run every create-time
   collision probe against filenames, aliases and the other planned names
   with wiki-build's `vault_index.py` and `find_collisions.py`
   ([its step 3](../../wiki-build/SKILL.md#3-resolve-against-existing-entries)).
   Record the source entry and the free destination with `publish_files.py
   snapshot` before reading the entry's complete bytes and all user-owned
   metadata; the source record keeps its identity, digest and permissions.
   A probe match whose entry is the one being retitled (its old filename or
   one of its own aliases) is expected, not a collision. Any other match
   follows wiki-build's collision decisions, and the retitle proceeds only
   when they find a distinct entity. Refuse an occupied or ambiguous
   portable-equivalent destination; never pick one owner by directory order.
2. Rebuild the entry coherently under the new canonical title. Preserve its
   `created:`, sources, review state, scheduling metadata, appearance/publish
   properties and substantive content. A retitle alone advances `updated:`
   and never resets `read:`. Keep the old slug as an alias only when it is
   still a valid same-entity name. A bare cross-domain old slug never stays,
   since the bare term is never an alias, and a proven wrong or misleading
   name is not retained merely to make old links resolve.
3. Inventory the references to the old filename and its aliases under
   [step 3 above](#establish-evidence-and-complete-scope), whose write scope
   applies: inbound links in `Wiki/`, `MOCs/`, `parents:` and other vault
   notes are rewritten, a dated historical record stays untouched and is
   reported, and an `Investments/` reference blocks the retitle. Rewrite only
   references that resolve to this exact owner, preserving display labels,
   headings, block anchors and surrounding bytes; a Related-footer label
   becomes the target's canonical title. Source evidence and external URLs
   are never rewritten because their text matches.
4. Publish [in dependency order](#publish-in-dependency-order): the
   destination entry exclusively, then every snapshotted inbound and hierarchy
   file conditionally, re-reading every result. Before removing the exact old
   entry version with `publish_files.py remove` against step 1's source
   record, re-scan: every changed link must resolve uniquely to the new entry, the
   old slug must have no unresolved inbound surface apart from untouched
   historical records, and the new entry must pass the current entry rules.
   Then rebuild the connected Task 3 closure from the resulting tree, which a
   default pass's Task 3 does, and re-scan.

## Remove a semantic-invalid alias

Task 1b removes an alias once evidence proves it names another entity, such
as a bare cross-domain term, which is
[never an alias](../../wiki-build/references/special-titles.md#cross-domain-term-disambiguation);
an explicit request also runs this protocol. The removal first identifies the
canonical owner. It then inventories and rewrites, under
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

## Create a missing entry

Task 1b creates a missing entry for a concept with a stable identity that
passes wiki-build's [substance and atomicity tests](../../wiki-build/SKILL.md#2-extract-entities)
when an open note-content item names it, or when it is a load-bearing term:
one at least three entries use without a resolving link (a one-clause inline
gloss still counts as a use). A use is a sentence that needs the term's
meaning to make its point; a word inside a dataset column or variable name
("median house value"), a measurement ("135 million nucleotide pairs") or a
list of examples is not a use. A concept failing those tests is reported. It
extracts no other topic from the evidence.

1. Derive the canonical title under the builder's
   [title](../../wiki-build/references/writing.md#title) and
   [special-title](../../wiki-build/references/special-titles.md) rules, run
   [its step-3 probes](../../wiki-build/SKILL.md#3-resolve-against-existing-entries),
   and snapshot the free slug. A same-entity owner means the term needs a
   link, which Task 2 adds; an occupied or ambiguous slug is reported.
2. Choose the evidence. When a document that the entries using the term
   already cite teaches it, cite that document at the page that teaches the
   term. Otherwise follow wiki-add's [research rules](../../wiki-add/references/research.md)
   and cite a reliable web page by its URL under
   [Cite a webpage](../../wiki-add/references/research.md#cite-a-webpage).
   Research may read the vault's PDFs and `Articles/` notes under its
   [local-source rule](../../wiki-add/references/research.md#find-local-sources-first),
   but never cites a PDF or note no entry cites. Never create a source note,
   acquire or file a PDF, or write `add-to-wiki.md`. Citing a document the
   using entries already cite leaves wiki-build's coverage unchanged; the
   rule that an uncited source counts as unbuilt governs deepening an
   existing entry, not a new entry's source.
3. Draft it under wiki-build's entry rules: its
   [writing guide](../../wiki-build/references/writing.md) and
   [Quality Checklist](../../wiki-build/SKILL.md#quality-checklist), one
   discipline tag, one `??` definition card, `parents: []`, `read: false`, and
   today's `created:` and `updated:`. Run wiki-build's
   [overlap/ownership audit](../../wiki-build/references/review.md#overlapownership-audit-this-runs-entries-and-their-relevant-neighbors)
   on the draft against the entries it links and the entries using the term.
   Stage it under its slug and resolve every
   `lint_entry.py` finding as wiki-build's
   [step 7](../../wiki-build/SKILL.md#7-review-and-report) does.
4. Publish it with `publish_files.py` ([publishing](../SKILL.md#publishing)),
   which creates the file exclusively. Then trim each using entry's inline
   re-definition of the term to its role there plus a link to the new entry,
   as a consolidation trim under [Dates](../SKILL.md#dates). Task 1b hands
   Task 2 the mentions it counted for the three-use test as the new entry's
   link worklist; Task 2 judges each under the closeness bar and links the
   using entry's first eligible body-prose occurrence under the
   [backfill rules](link-hygiene.md#backfill-add-missing-links), and Task 3
   places the entry.
