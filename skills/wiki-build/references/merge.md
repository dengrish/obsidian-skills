# Merge Logic — integration, frontmatter, source-no-op merges, conflicts

Scope: collisions and new-source merges; corrections from already-cited sources alone are wiki-lint's [source-backed correction mode](../../wiki-lint/references/source-backed-corrections.md).

## Collision decisions

`find_collisions.py` checks filenames **and aliases**, then candidates against each other:

| Probe | Comparison | Verdict |
| --- | --- | --- |
| (a) Basic slug equality | Candidate slug as-is | Merge only with one existing owner |
| (b) µ-variant | Microsign `µ` and Greek mu `μ` equivalents | Merge only with one existing owner |
| (c) Singular/plural | Regular and irregular inflections | Adjudicate |
| (d) Hyphenation-collapse | Hyphens stripped on both sides | Adjudicate |
| (e) Word-order-permutation | Singularized tokens, sorted | Adjudicate |
| (f) Stem-morphology | Gerund/noun and other morphological pairs | Adjudicate |
| (g) Token-superset | One stemmed token set extends the other by at most two tokens | Adjudicate |

Multiple owners for (a) or (b) also need adjudication; never choose by index order. The other probes flag possible duplicates, not identity. A confirmed duplicate goes to one canonical entry, usually the literature's most common form, with a valid alternate slug as an alias; this never authorizes merging or deleting two pre-existing files, and renaming an existing entry stays a refactoring proposal. Distinct but confusable entities follow [same-surface-form handling](special-titles.md#same-surface-form-different-technique).

An empty wiki still needs candidate-to-candidate checks. Index problems that can hide ownership (unreadable, unsafe or unparsed entries, malformed titles or aliases) keep unmatched candidates at `adjudicate`: never create from apparent absence, and report every index problem.

## Merge Logic

### Integration principle

Integrate the active source into **one coherent explanation organized by the entity**, not by source chronology. Before rewriting, apply the [source-no-op test](#source-no-op-merges). For a regular merge:

- **Preservation protects claims, not arrangement.** Keep every substantive existing claim, the meaning of each equation, every exhibit and every card unless inspected evidence corrects it under [conflict handling](#conflict-handling). Uncited hand edits, including their deliberate structure, are merge input too; preserve and report an unresolved conflict rather than discarding one. Otherwise paragraph order, wording, notation and which display leads are not protected.
- **Rebuild in teaching order.** Weave each new fact where it advances a paragraph's idea, and reorder, split or rewrite paragraphs into the [learner's order](writing.md#prose-principles) under the paragraph-flow test. When the merged material makes a more general definition central, restructure: the general definition first, in vault notation; then the specialized forms as cases; then derived results. Restate a carried-over equation in the unified notation when it is the same quantity. Change the opener only for a meaningfully better main claim, such as that more general definition.
- **Restructuring inside this entry is integration, not a refactor.** Reapply [atomic scope](writing.md#body-structure): create and link a distinct entity the new source substantively teaches, but moving pre-existing off-scope content to another entry, or deleting it, needs separate refactor authority; report that proposal instead. There is no size target, and an optional example or figure does not earn a place merely by being available.
- Link provenance follows [CONVENTIONS §9](../../../shared/CONVENTIONS.md#9-ownership-split-for-linking): link a target only when the active source introduces it or contributes a substantive relationship to it. Rewording a carried-over claim never restores a previously pruned link; genuine new source support may, and is reported.
- For `Software`, reapply the [API substance gate](api-surface.md#software-explain-the-artifact-not-its-reference-manual).

**Check the completed body.** Resolve accidental concatenation into one body: duplicate openers or bolded title introductions, duplicated mechanism explanations, stray YAML keys or digits, and unexpected `---` fences (the separator before `## Flashcards` is legitimate). Then re-read every carried-over sentence and symbol binding against the merged opener's scope: confirm each carried-over claim survives, remove carried-over hedges, defensive clarifications and repeated conventions that [principle 3](writing.md#prose-principles) excludes (never from an uncited hand edit), and report each removal.

### Frontmatter and Related footer

[Schema](../../../shared/CONVENTIONS.md#2-frontmatter-schemas) and [source-reference rules](../../../shared/CONVENTIONS.md#7-source-references) govern encoding, [writing fields](writing.md#1-frontmatter-fields) meaning. Apply these rules only when a value actually changes:

1. **`sources:`** Append a missing full citation, deduplicated, at the entity's introducing physical PDF page (Markdown unanchored); report a rerun's anchor drift. Replace a Markdown summary with its PDF only after decoded provenance confirms the pair (a *Review-pass fix*); preserve independent clippings and unresolved references, reporting uncertainty.
2. **`updated:`** Today's local date when the entry actually changes, metadata and independent QC included; a byte-unchanged result keeps it. `created:` never changes.
3. **`aliases:`** Append only valid same-entity aliases from the new source, deduplicated in slug form. Preserve a pre-existing semantic-invalid alias and report its evidence and likely owner; only wiki-lint's [explicit refactor mode](../../wiki-lint/references/refactors.md) removes it, though within-list duplicates may be cleaned up.
4. **`tags:`** Keep exactly one supported home. Correct a clearly wrong home, multiple homes, or a blank or empty list from the entity's meaning (`"#misc"` only when nothing fits); preserve and report ambiguous or malformed metadata; report old and new groups for wiki-lint's hierarchy refresh.
5. **`parents:` and legacy `importance:`** Preserve exactly as found: never populate parents, migrate legacy importance, or strip it during a body rewrite.
6. **`description:`** Rewrite only for a meaningfully more accurate, informative or grammatically clear result, or to fix a concrete [description defect](writing.md#description); rephrasing alone is insufficient, and a source-no-op permits defect repairs only.
7. **Related footer:** Keep existing links; add only substantive relationships the active source introduces, never from a carried-over bare mention or on a source-no-op. Targeted QC may canonicalize a target or label or remove a proven invalid link; weak-link pruning is wiki-lint's. Report growth past roughly 12 links rather than pruning ([footer guidance](writing.md#the-related-footer)).
8. **Keys outside the schema:** preserve Obsidian-owned and other unexpected keys exactly and in place under [§2a](../../../shared/CONVENTIONS.md#2a-wiki-entry--wikimd), and list them under *Notes for the user*.

### Exhibits and headings

**Images and tables.** Preserve existing images, recreated tables and captions with their motivating prose; for one that no longer fits, propose consolidation or removal, never deletion or a justifying tangent. Replace an image only with a strictly clearer or more complete depiction of the **same specific aspect**, not merely the same subject, and a table only with **the same data** presented more completely or correctly; different datasets never subsume each other. Name both exhibits and the benefit in the report; keep the underlying files.

**Equations** follow [equations on merge](equations.md#4-normalization--the-sources-symbols-do-not-survive-contact); a simple verbal concept gets no forced mathematics.

**Headings** are narrative organization, not preserved exhibits. Add, remove, rename, or reorder `##` headings when the integrated explanation warrants it under [Body structure](writing.md#body-structure), never merely because of length. A new-source subsection with a distinct supported identity becomes its own candidate; moving pre-existing content to another entry still needs separate refactor authority.

### Flashcards on merge

Before changing a card, read the [card format](flashcards-and-emphasis.md#4-flashcards) and wiki-lint's [high bar](../../wiki-lint/references/flashcards.md#card-freshness-and-the-rewrite-bars). A merge runs no vault scan, so every pre-existing card takes the high bar.

- **Every merge, including source-no-ops:** run item-19 QC on the primary card. Restore a missing card, except on a discipline root, from the entry's established main claim with `??`; repair current-rule defects in place. Bring card math under [line-1 equation coverage](flashcards-and-emphasis.md#line-1-equation-coverage) for the same tested claim, preserving the answer line and attachments; that repair never invents an equation or changes the learning objective.
- **Regular merges, primary definition:** if integration substantively changes the main claim, re-derive line 1 and replace it only when meaningfully more accurate or unambiguous. Mere phrasing drift does not qualify. If inspected evidence corrects a claim and its card now contradicts the body, correct the card in place rather than removing and re-adding it.
- **Primary answer:** recompute its content when the canonical title, qualifying alias counterpart, or the opener's direct binding changes; apply the answer contract, preserving the separator and attachments.
- **No second card:** a merge never adds a card. A key result the source adds belongs in the body, and a second source-supported entity earns its own entry.
- **Legacy extras:** any card beyond the primary card, under the [card set](flashcards-and-emphasis.md#card-set). Never repair or reword one; preserve and quote it in full, including attachments, in *Notes for the user*. Moving or removing a pre-existing card requires an explicitly authorized source-backed refactor accounting for its claim and every attachment, or a request naming that card for deletion; a source merge alone supplies no such authority.

Every pre-existing separator and recognized scheduling or block-ID attachment stays byte-for-byte and in place, even when a content line changes, apart from the [`??` restoration](flashcards-and-emphasis.md#line-2-the-separator). A conforming card stays unchanged.

### The `read:` reset

Apply the shared [review-checkbox contract](../../../shared/CONVENTIONS.md#2c-read--the-users-review-checkbox). Never infer missing, null, or unknown user state. For a known value, set `read: false` **only when adding or rewriting unread explanatory body content**, whether from the active source or independent step-7 QC: prose, an image or recreated table, a newly typeset equation, a Person/Event date, or a rewritten explanation.

Metadata/alias/source appends, description/card/footer/tag repairs, content removal, and format-only fixes do not reset it. `updated:` still follows any actual change. When the unread-content judgment is close, preserve `read:` and report the decision. Name every reset and every close no-reset call in the run report.

### Source-no-op merges

A candidate must first pass step 2's substance and, for a secondary source, durability filters. After [example](writing.md#prose-principles), [figure](media.md#selection) and [table](media.md#tables) selection, compare **every selected source contribution** with the existing entry: a fact is covered when present verbatim or as a clear paraphrase, a figure by the same `Sources/Images/` filename, a table by the same recreated data, an equation by the same quantity's definition (different notation alone is not new), and for `Software` an interface or design idea rather than identifier spelling. If all are covered, the entry is **source-no-op-merged**; one new selected fact, relationship, image, table or equation makes the merge regular, while a documented decision to skip an optional example or figure is not net-new. Explicit reruns still need this comparison.

A source-no-op skips source-driven body, description, card and Related-footer rewriting, leaving conforming content byte-for-byte unchanged. It still applies the metadata rules, including the active source's missing citation, and **all step-7 QC and audits**, making only their authorized repairs: a missing Person/Event date under [rare-types](rare-types.md#dates-in-the-opener-person-and-event), an equation warranted by carried-over prose, removal of a navigation-only cue, or a description or card defect.

Classification concerns the source's contribution, not the final bytes: an independent QC equation leaves the source a no-op while advancing `updated:` and resetting a known `read:` value, whereas an equation the active source contributes makes the merge regular. Report them under the [run report](review.md#run-report)'s source-no-op bullet, never describing a QC-changing run as leaving the wiki unchanged.

### Net-new fact test

Compare meaning before wording: "scales pairwise gradients by the NDCG change from swapping items" adds nothing to an entry already weighting pairs by that change; a new source-supported relationship to LambdaLoss is net-new. Integrate a net-new fact under the [integration principle](#integration-principle), never as a source-shaped addendum.

### Conflict handling

Resolve a contradiction only from the active source and the existing entry's cited sources you can inspect; methods, scope, date and authority weigh evidence only when those sources establish them, and memory, uncited background knowledge or assumed consensus never settle it.

- **Existing claim supported, new contradiction unsupported:** preserve the existing claim and omit the contradictory clause; integrate unrelated supported contributions and record a qualifying source in `sources:`.
- **Existing claim disproved by inspected evidence:** correct it in place.
- **Evidence partial or unresolved:** synthesize only what the sources jointly support; otherwise preserve the existing claim, omit the contradictory clause, and report both claims with source pages.

Report every correction or unresolved conflict with its evidence; write the resolved subject as ordinary prose under [prose principle 5](writing.md#prose-principles), not a source-by-source transcript.

**Contested-topic exemption.** When legitimately coexisting views (philosophical, historical or religious positions) make the disagreement part of the subject, present source-supported views in parallel with light attribution, in fresh entries and merges alike; the (a)–(d) source-meta prohibitions of [principle 5](writing.md#prose-principles) otherwise apply. Scientific and established-versus-fringe disputes use the evidence rule above, stating consensus or fringe status only when inspected sources establish it.

Detect conflicts within this merge only. Report an incidentally noticed cross-entry contradiction under *Notes for the user*; resolving it takes a separate source-backed wiki-lint request.
