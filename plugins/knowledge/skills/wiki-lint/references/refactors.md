# Source-backed refactors of existing entries

Read this before Task 1b consolidates a duplicated explanation, moves a
misplaced passage to its owner, merges or splits entries, retitles an entry,
removes a semantic-invalid alias, creates a missing entry or glosses a
dangling link's term, and when the current request explicitly authorizes a
deletion. An ordinary run performs
all of these but deletion once its evidence identifies the duplicate and its
owner, a wrong title the [retitle triggers](#retitle-an-entry) cover, the
invalid alias or the missing concept, or proves
[step 2](#establish-evidence-and-complete-scope)'s boundary for a merge or
split; Task 1b's [merge and split rules](../SKILL.md#task-1b--content-repair)
name what never activates one and where a close call goes. A deletion runs
only under [Delete an entry](#delete-an-entry); a merge's removal of the
merged-away file is part of the merge, not a deletion. The ordinary run's
definition, or the request, is the whole authorization.
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
affected entry and supported by its cited sources.
Task 1b's [missing-entry rule](#create-a-missing-entry) is the only other
creation, limited to a concept the wiki relies on, taught by a vault document
the entries using it cite.

## Establish evidence and complete scope

1. Use the current pass's whole-wiki Step 0 scan, or run one for a standalone
   request. Snapshot every affected entry and resolve its cited sources: vault
   files, and cited URLs read online. For a PDF/summary pair, verify claims
   against the original PDF. A missing, unreadable, unreachable or ambiguous
   source blocks every movement that depends on it: only content a readable
   cited source supports, or a 5(h) clarification, moves. Never
   fill a gap with uncertain recollection.
2. Prove the proposed boundary against the entries' definitions and cited
   sources. A split needs two or more independently
   definable subjects, each with source-supported substance that passes the
   builder's [substance test](../../wiki-build/SKILL.md#2-extract-entities).
   A merge needs one entity under alternate names, not merely related
   concepts. Inherent mechanisms, stages, conditions, and limitations remain
   with their subject.
3. Inventory every live reference to a slug or alias that may disappear across
   all vault Markdown and Obsidian Canvas boards, including body/Related links,
   `parents:`, MOCs, note transclusions, relative Markdown links, and a
   `.canvas` file card's vault path and text card's Markdown. Resolve each destination from
   its owning note, retaining path qualification and heading/block anchors.
   The entry scanner omits some of these surfaces, so scanner silence cannot
   prove that no inbound references remain. A split can send different
   references to different targets; an ambiguous reference remains unchanged
   and prevents deletion of the old entry. Preserve code/examples, independent
   source origins, distinct targets, image embeds, and literal suggestion-log examples;
   token equality never authorizes a rewrite. The rewrite scope covers
   references in `Wiki/`, `MOCs/` and `parents:`, and in every other vault
   note, including `Articles/` notes, `Inbox/` captures, every `Reviews/`
   log with its Fixed section, and older dated reports. A link, embed or
   transclusion there that resolves to the retiring name is rewritten under
   these rules, even inside a claim sentence or a log item's heading,
   **Issue** or **Verified** line; only the link changes. The wording of
   claims and issue text, and every `sources:` value, stay unchanged. In a
   Canvas board, a file card's path takes the destination's vault path and
   a text card's link is rewritten as in a note; every other byte of the
   board stays, and a board that is not valid JSON but may cite the name is
   a dependency this protocol cannot write. The ordinary run's or the
   request's authorization covers these rewrites, with no additional
   approval. Notes in vault-root `Investments/` remain outside this repair
   scope, including through linked-folder aliases.
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
  Every note a split creates gets today's `created:` and `updated:` dates and
  `read: false`. An ordinary run's split keeps the original entry as the owner
  of one subject: the one its title names, or, when the title names several
  (`Precision and recall`) or none, the one with the fullest treatment, then
  the alphabetically first resulting slug. When the retained original's title
  does not name exactly that one subject, the same Task 1b retitles it to the
  subject's canonical title under [Retitle an entry](#retitle-an-entry) after
  the split publishes. Retiring the original outright is a deletion and runs
  only on an explicit request. A retained original keeps `created:` and follows
  the builder's
  [body-change rule](../../wiki-build/references/merge.md#the-read-reset) for
  `updated:` and `read:`: a pure trim keeps `read:`, and a rewritten
  explanation resets it. Each unresolved
  [user issue](../SKILL.md#user-issues) moves verbatim to the result that now
  holds the content it concerns. A new note that receives none gets
  `issues: ""`; the retained original keeps the issues left with it, becomes
  `issues: ""` once all have moved, and keeps a blank spelling it already
  had.
- A merge chooses one collision-free surviving identity from the evidence and
  the run's scope, titled by the builder's
  [title rule](../../wiki-build/references/writing.md#title), its
  acronym-or-full-form choice included. Preserve that entry's `created:` and
  user-owned appearance fields, integrate nonduplicate claims, and union only valid source
  contributions, each document in one representation
  ([merge rule 1](../../wiki-build/references/merge.md#frontmatter-and-related-footer)),
  and same-entity aliases. The survivor gets today's
  `updated:` and `read: false`, whatever any merged entry's prior `read:`,
  in place of the builder's
  [body-change rule](../../wiki-build/references/merge.md#the-read-reset),
  because it holds combined content the user has not read in that form.
  Carry every merged entry's unresolved
  [user issue](../SKILL.md#user-issues) text into the survivor's `issues:`
  verbatim, carrying a text that several merged entries hold identically
  once. When several entries hold text, write a block list with one item
  per original list item or string, unless every value is a string: join
  their texts as sentences into one double-quoted string, ending each text
  that lacks closing punctuation with a period, escaping `\` and `"`, so the
  property stays Text. When none holds text, the survivor keeps
  its blank spelling, or gets `issues: ""` when the key is missing. Report
  conflicting user-owned metadata from an entry that may be removed rather
  than silently selecting a value.
- A consolidation keeps the full treatment of an explanation, argument,
  worked example, property with its justification, or exhibit duplicated
  across entries or held outside its owner, in that owner: the most specific
  entry whose subject it is about. A
  property the sources state for a whole family belongs to the family's entry
  (regularized models' scale sensitivity to Regularization, not Ridge
  regression), and an argument about how a metric behaves belongs to that
  metric (the rare-positive argument to False positive rate); plots built on
  the metric keep the consequence and a link. Before choosing the owner,
  search the whole Wiki for the passage's distinctive tokens (a figure with
  its unit, a gene or experiment name) and plan every hit in the same
  consolidation. Between equally specific entries, the owner is the one
  already holding the fullest version, then the alphabetically first slug.
  If the owner already explains it, trim each other copy to its consequence
  for that entry in one clause, linked to the owner; the clause drops the
  owner's reasoning (keeping only the one-clause reason or key value the
  [atomicity test](../../wiki-build/references/writing.md#body-structure)
  allows) and keeps a source verdict only in the owner, but never drops a fact that entry's core
  facets need. Otherwise move the fullest version into the owner, verified
  against its cited sources (new information they do not give is
  [trimmed](source-backed-corrections.md#correct-and-publish), never moved)
  and carrying each
  source-specific claim's existing citation (adding that source to the
  owner's `sources:` when it cites no form of that document), then trim the
  others. A trimmed copy may lose links that served only the removed passage. A worked example or
  exhibit lives in one entry; the others state its consequence and link the
  owner, and an exhibit moves with its caption and carries its source
  citation. Resolve a
  conflicting claim in the passage before consolidating it; while it stays
  unresolved, leave every copy unchanged and keep the conflict open, and never
  trim a copy that disagrees with the owner's. The owner and each trimmed
  entry follow the [Dates](../SKILL.md#dates) rule.
- Preserve the retained primary flashcard's recognized scheduling attachments
  and block ID byte-for-byte. Of the merged entries' primary cards, a merge
  keeps only the survivor's: a retired entry's primary card tests the same
  entity, so the merge removes it. Remove every other card
  under the [card set](flashcards.md#card-set) rule, naming any distinct
  entity it tested as a missing-entry candidate. Each link or embed to a
  removed card's block ID, primary or extra, becomes a plain link to the
  survivor, keeping any label, in
  [publish step 2](#publish-in-dependency-order) under the
  [rewrite scope](#establish-evidence-and-complete-scope). Quote every moved
  or removed card with all attachments in the report. Preserve existing exhibits unless
  source evidence and the refactor establish their new owner.

## Publish in dependency order

Stage complete drafts under `<scratch>` and publish creates and replacements
with `publish_files.py` ([publishing](../SKILL.md#publishing)). An old path's
removal (step 4 below, a retitle's old entry, a deletion) uses the shared
[conditional removal](../../../shared/SAFE_WRITES.md#remove-or-move-an-old-pathname-conditionally)
against the same snapshot file:

```bash
python3 '<plugin>/shared/scripts/publish_files.py' remove --vault '<vault>' \
    --snapshots '<scratch>/lint-snapshots.json' '<vault-relative path>'
```

`remove` deletes each path only while its bytes, identity and mode match its
original record, and refuses a path with no record. Remove against the record
taken before the bytes that decided the removal were read (re-recorded with
`snapshot --replace` first if this run already published the path); never
re-record it after that read. A refactor spans several files but is not one
filesystem transaction, so order prevents a disappearing target:

1. Publish every new entry exclusively and conditionally replace retained
   entries from the exact snapshots used to plan them.
2. Rewrite each inspected inbound link. An otherwise unchanged entry whose
   only change is a rewritten link or `parents:` value keeps its dates and
   `read:`.
3. Re-scan and independently refresh the complete live-reference inventory.
   Verify that every changed link or transclusion resolves, keeping its
   anchor unless that anchor was a removed card's block ID, which becomes a
   plain link; that every moved source-specific claim keeps its source; and
   that no obsolete destination remains referenced; the Wiki scan alone
   cannot establish this postcondition.
4. Only then conditionally remove an obsolete entry. Every substantive claim,
   equation, exhibit, card (including its scheduling attachments and block ID),
   citation, and user-owned metadata value must either survive in an identified
   destination or, on an explicit request, be named by that request as content
   to delete. A merged-away entry's `read:` and `issues:` are accounted for
   by the survivor's `read: false` and carried issue text under the
   [merge rule](#build-the-refactored-entries) above. A merged-away primary
   card counts as accounted for once it is quoted in the report, because the
   survivor's primary card tests the same
   entity; so does an extra card removed under the
   [card set](flashcards.md#card-set) rule. Step 2 has already rewritten each
   link or embed to a removed card's block ID, the merged-away primary card's
   included, as a plain link to the survivor, keeping any label. Only such a
   reference in a note the rewrite scope excludes, such as an `Investments/`
   note, is an unresolved inbound reference that retains the old entry.
   Missing or unverified source support is a reason to retain the content, never
   evidence that it is disposable. If a later edit or an
   unresolved inbound reference appears, retain the file and report the mixed
   state; never force cleanup to make the refactor look done. A rollback
   restores only files whose published bytes are still unchanged.

Inside a default pass, that pass's refresh, Task 2 and Task 3 finish the
refactor, with no nested pass; a standalone request finishes as
[explicit requests](../SKILL.md#explicit-requests) defines. Either way, re-scan until all fixable findings
introduced by the refactor are gone. Report source evidence, created,
retained, and removed paths, every inbound rewrite, review-state decisions,
unresolved content, and the final scan counts.

## Retitle an entry

A title or slug correction is a whole-entry rename, not an alias-list edit.
Task 1b runs this protocol when all of these hold:

- the title is a bare cross-domain term under QC item 5 (a word or phrase in
  test (c)'s corpus, or a term that fails test (a), of the builder's
  [disambiguation rule](../../wiki-build/references/special-titles.md#cross-domain-term-disambiguation)),
  the title is itself an API identifier (QC item 6), the filename differs
  from its title's slug, the title's acronym-or-full-form choice breaks the
  builder's [title rule](../../wiki-build/references/writing.md#title)
  (`PPO` for Proximal policy optimization, under QC item 5), an `Organism`
  is titled by a common name where the builder's
  [Organism rule](../../wiki-build/references/rare-types.md#the-ten-rare-types)
  requires its scientific name (`Zebrafish` for Danio rerio, under QC item
  5), or the title of a split's retained original does not name exactly its
  one remaining subject;
- the qualified, conceptual or other-form title is determinate;
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
   A destination that differs from the old filename only in case or Unicode
   normalization is a respelling of the same file: record only the source,
   whose own match is not an occupant.
2. Rebuild the entry coherently under the new canonical title. Preserve its
   `created:`, sources, review state, `issues:` value, scheduling metadata,
   appearance/publish properties and substantive content. A retitle alone
   advances `updated:` and never resets `read:`; an issue it resolves is
   then cleared, and `read:` reset, under
   [User issues](../SKILL.md#user-issues). Keep the old slug as an alias only
   when the [alias rule](../../wiki-build/references/writing.md#aliases)
   admits it. A bare cross-domain old slug
   never stays, since the bare term is never an alias, and a proven wrong or
   misleading name is not retained merely to make old links resolve.
3. Inventory the references to the old filename and its aliases under
   [step 3 above](#establish-evidence-and-complete-scope), whose write scope
   applies: inbound links in `Wiki/`, `MOCs/`, `parents:`, other vault
   notes and Canvas boards are rewritten, and an `Investments/` reference
   blocks the retitle. Rewrite only
   references that resolve to this exact owner, preserving display labels,
   headings, block anchors and surrounding bytes; a Related-footer label
   becomes the target's canonical title. Source evidence and external URLs
   are never rewritten because their text matches.
4. Publish [in dependency order](#publish-in-dependency-order): the
   destination entry exclusively, then every snapshotted inbound and hierarchy
   file conditionally, re-reading every result. Before removing the exact old
   entry version with `publish_files.py remove` against step 1's source
   record, re-scan: every changed link must resolve uniquely to the new entry, the
   old slug must have no unresolved inbound surface, and the new entry must
   pass the current entry rules apart from findings that pair it with the old
   file (`item9/duplicate-sentence`, `item12/duplicate-embed-candidate`, and
   an alias or exact collision with the old slug), which the removal clears.
   Then rebuild the connected Task 3 closure from the resulting tree, which a
   default pass's Task 3 does, and re-scan.

   A respelling has no exclusive create and no removal. Publish the rebuilt
   entry under its old spelling against step 1's record. Re-record that path
   with `snapshot --replace`, re-read it to confirm its title still slugs to
   the new spelling, and move it:

   ```bash
   python3 '<plugin>/shared/scripts/publish_files.py' move --vault '<vault>' \
       --snapshots '<scratch>/lint-snapshots.json' '<old path>' '<new path>'
   ```

   `move` keeps the same file. It refuses a changed entry and any other file
   that shares the new name's case/Unicode identity. Then publish the inbound
   and hierarchy rewrites and re-scan: every changed link must resolve
   uniquely to the entry, and neither `item5` nor `rename_candidates` may
   list it. Rebuild the Task 3 closure as above.

### Finish an interrupted retitle

An entry found beside its own retitle destination is a retitle that
published the destination but never removed the old file. That holds when
the destination defines the same entity under the old entry's determinate
retitled title, carries the old entry's `created:`, and holds every claim,
equation, exhibit, card (block ID included) and source of the old entry, and
each of its user issues that the retitle did not resolve. Finish that
retitle; do not merge. Record both files with `publish_files.py snapshot`
before reading them, rewrite the inbound references still pointing at the
old entry under step 3, then run step 4's re-scan and remove the old entry
against its record. The destination keeps its `read:` and `issues:` value;
only an issue this run resolves resets `read:` under
[User issues](../SKILL.md#user-issues). When the old entry holds anything
the destination lacks, such as a later user edit or issue, the pair goes to
the [merge check](qc-items.md#5-filename-collision-and-disambiguation).

## Remove a semantic-invalid alias

Task 1b removes an alias once evidence proves it names another entity, such
as a bare cross-domain term, which is
[never an alias](../../wiki-build/references/special-titles.md#cross-domain-term-disambiguation),
or is a name its cited sources do not use and 5(h) does not admit
([aliases](../../wiki-build/references/writing.md#aliases));
an explicit request also runs this protocol. The removal first identifies the
canonical owner, this entry for such an unsourced name. It then inventories and rewrites, under
[step 3 above](#establish-evidence-and-complete-scope), every real reference
that resolves through the alias and every link to this entry whose alias label
names a different entity, publishing
[in dependency order](#publish-in-dependency-order). A blocked dependency
retains the alias until it can be repaired. Delete the alias only after
verifying that no ambiguous owner, inbound alias-target link or such
mislabelled link remains. The removal advances the owner's `updated:` and
keeps its `read:`, unless it resolves a [user issue](../SKILL.md#user-issues);
an otherwise unchanged entry whose only change is a
rewritten link keeps its dates and `read:` under the
[shared date rule](../../../shared/CONVENTIONS.md#2a-wiki-entry--wikimd).

## Create a missing entry

Task 1b creates a missing entry only for a concept that a vault document the
entries using the term already cite teaches, with a stable identity that
passes wiki-build's [substance and atomicity tests](../../wiki-build/SKILL.md#2-extract-entities),
when a [user issue](../SKILL.md#user-issues) asks for its entry, when an
open note-content item names it, or when it is a load-bearing term:
one at least three entries use without a resolving link. A one-clause inline
gloss still counts as a use, and so does a dangling body-prose link to the
term. A use is a sentence that needs the term's meaning to make its point; a
word inside a dataset column or variable name ("median house value"), a
measurement ("135 million nucleotide pairs"), a list of examples or a
Related-footer item, dangling or not, is not a use. Count the uses before
adding any gloss, keep the count across the whole Task 1b sweep, and
adjudicate every term that reaches three entries in the same run. A concept
failing those tests, including one no cited document teaches, gets no entry:
it is a reported [missing-entry candidate](backlogs.md#run-report) for a
later wiki-build of a source that teaches it or for wiki-add, and each using
entry whose sentence needs the term's meaning keeps, or regains, its brief
[5(h)](../../wiki-build/references/writing.md#prose-principles) definition.
It extracts no other topic from the evidence.

1. Derive the canonical title under the builder's
   [title](../../wiki-build/references/writing.md#title) and
   [special-title](../../wiki-build/references/special-titles.md) rules, run
   [its step-3 probes](../../wiki-build/SKILL.md#3-resolve-against-existing-entries),
   and snapshot the free slug. A same-entity owner gets no entry: Task 2
   links the term to it, or retargets its dangling links there; an occupied
   or ambiguous slug is reported.
2. Cite that teaching document at the page that teaches the term, and no
   other source: never research the term on the web or in a vault document
   no entry cites. Citing an already cited document leaves wiki-build's
   coverage unchanged; the rule that an uncited source counts as unbuilt
   governs deepening an existing entry, not a new entry's source.
3. Draft it from step 2's evidence, adding beyond it only the clarification
   [5(h)](../../wiki-build/references/writing.md#prose-principles) admits,
   under wiki-build's entry rules: its
   [writing guide](../../wiki-build/references/writing.md) and
   [Quality Checklist](../../wiki-build/references/quality-checklist.md), one
   discipline tag, one `??` definition card, `parents: []`, `read: false`,
   `issues: ""`, and today's `created:` and `updated:`. Run wiki-build's
   [overlap/ownership audit](../../wiki-build/references/review.md#overlapownership-audit-this-runs-entries-and-their-relevant-neighbors)
   on the draft against the entries it links and the entries using the term.
   Stage it under its slug and resolve every
   `lint_entry.py` finding as wiki-build's
   [step 7](../../wiki-build/SKILL.md#7-review-and-report) does.
4. Publish it with `publish_files.py` ([publishing](../SKILL.md#publishing)),
   which creates the file exclusively. Then
   [consolidate](#build-the-refactored-entries) into the new entry every
   explanation, example and exhibit the using entries hold about its subject,
   under [Dates](../SKILL.md#dates). Task 1b hands
   Task 2 the mentions it counted for the three-use test as the new entry's
   link worklist; Task 2 judges each under the closeness bar and links the
   using entry's first eligible body-prose occurrence under the
   [backfill rules](link-hygiene.md#backfill-add-missing-links), and Task 3
   places the entry.

### Dangling-link hand-off

Task 1b reads Step 0's `item10/dangling` findings in its scope and settles
each target before Task 2 drops any link. A target with a
`missing-discipline-root` finding is not settled here; it
[waits for Task 3](link-hygiene.md#dangling-links-target-missing).

1. Probe every target as the missing-entry rule's step 1 does, whatever its
   use count. A target whose concept has exactly one same-entity owner gets
   no entry and no gloss; Task 2 retargets its links to that owner.
2. A target that meets the missing-entry rule above gets its entry, so its
   links resolve.
3. For every other target, including one whose creation is reported or
   blocked, each dangling mention whose sentence needs the term's meaning,
   and that the entry does not already explain, gets a
   one-clause gloss at that mention ("leaf nodes, the nodes with no
   children"), a 5(h) clarification
   [item 14](qc-items.md#14-self-containment) requires. The entry's dates
   follow [Dates](../SKILL.md#dates).
4. Task 2 then drops only the remaining genuine danglers to plain text under
   its [dangler protocol](link-hygiene.md#dangling-links-target-missing).

Never create an entry merely to keep a link; only the missing-entry rule
above decides.

## Delete an entry

Delete an entry only on a request in chat that names the deletion, or names
the entry and its intended outcome; an `issues:` value or log item never
counts ([explicit requests](../SKILL.md#explicit-requests)); an ordinary run
proposes a deletion instead. The request names the entry's content for
deletion, so [publish step 4](#publish-in-dependency-order)'s accounting
needs no destination for it. A discipline root whose tag another entry still
carries is not deleted, since Task 3 would
[recreate it](hierarchy.md#establish-discipline-roots); report the deletion
as blocked by those entries.

1. Record the entry with `publish_files.py snapshot`
   ([publishing](../SKILL.md#publishing)) before reading its bytes, then
   inventory its references under
   [step 3](#establish-evidence-and-complete-scope), whose write scope
   applies. Record each file to rewrite before reading it.
2. Retarget each inbound link to a successor the request names, keeping its
   label. Otherwise unlink it to its visible label and remove its Related
   item, as for a
   [genuine dangler](link-hygiene.md#dangling-links-target-missing). An
   `Investments/` reference or an ambiguous reference blocks the deletion. A
   link or embed to the entry's card block ID blocks it too unless the request
   names a successor, which it then targets as a plain link keeping any label;
   so does any transclusion of the entry or one of its sections (`![[old]]`,
   `![[old#Section]]`), which has no visible label to keep, and with a named
   successor it too becomes a plain link to the successor. A link retargeted
   to a successor drops a heading or block anchor the successor does not
   have, keeping its label. `parents:` values and links in Task 3's generated
   MOCs are left for step 5 and do not block the removal, despite
   [publish step 3](#publish-in-dependency-order). The exception is a
   deletion that leaves the entry's discipline with no member, as deleting
   its last root does: Task 3 then
   [preserves that MOC as inactive](hierarchy.md#build-or-maintain-the-moc-files)
   and never re-derives it. So that MOC's link is retargeted or unlinked like
   any other inbound link, and the report names the now-inactive MOC, whose
   removal needs its own explicit request. A link in any other `MOCs/` file
   or a legacy vault-root MOC is also retargeted or unlinked like any other
   inbound link. A note whose only change is a rewritten link keeps its
   dates and `read:`.
3. Quote the entry's card, with its attachments, and any non-blank `issues:`
   text in the report.
4. Re-scan, then run `publish_files.py remove` against step 1's record. A
   later edit to the entry, or an inbound reference step 2 could not resolve
   (not the `parents:` values and active generated-MOC links step 5
   re-derives),
   retains the file; report the mixed state.
5. The request's closing Task 3
   ([explicit requests](../SKILL.md#explicit-requests)) then re-derives the
   children's `parents:` and the MOCs; inside a default pass, its own
   refresh, Task 2 and Task 3 do this.
