# Merge Logic — integration, frontmatter, source-no-op merges, conflicts

> **When to read this:** as soon as step 3 reports a match. This guide owns collision adjudication and changes to an existing entry from a new source. All-create runs need it only if candidates collide with each other. Corrections using only already-cited sources belong to wiki-lint's [source-backed correction mode](../../wiki-lint/references/source-backed-corrections.md).

Contents: [Collisions](#collision-decisions) · [Integration](#integration-principle) · [Metadata](#frontmatter-and-related-footer) · [Exhibits](#exhibits-and-headings) · [Cards](#flashcards-on-merge) · [Review state](#the-read-reset) · [Source no-ops](#source-no-op-merges) · [Conflicts](#conflict-handling).

## Collision decisions

`find_collisions.py` checks filenames **and aliases**, then candidates against each other. A filename listing cannot replace it. The probes are:

| Probe | Comparison | Verdict |
| --- | --- | --- |
| (a) Basic slug equality | Candidate slug as-is | Merge only with one existing owner |
| (b) µ-variant | Microsign `µ` and Greek mu `μ` equivalents | Merge only with one existing owner |
| (c) Singular/plural | Shared inflection helper's regular and irregular forms | Adjudicate |
| (d) Hyphenation-collapse | Strip all hyphens on both sides | Adjudicate |
| (e) Word-order-permutation | Singularize tokens, then sort them | Adjudicate |
| (f) Stem-morphology | Gerund/noun and other morphological pairs | Adjudicate |
| (g) Token-superset | After stemming/singularization, one token set is a proper subset with at most two extra tokens | Adjudicate |

Multiple owners for (a) or (b) also require adjudication; never choose by index order. The other probes identify possible duplicates, not identity. `Weight tying` and `Tying weights` can name different techniques despite (e); `tokenization`, `tokenizer`, and `token` remain distinct despite (f); a qualified term and its base can be different entities despite (g). Do not reimplement the shared inflection table. Probes (f) and (g) are on by default and independently disabled by `--no-stem` and `--no-superset`. Probe (g) is create-time only: a vault-wide sweep would repeatedly flag legitimate disambiguated pairs.

When the evidence confirms a duplicate, route the incoming candidate to one canonical entry, usually the literature's most common form, and add a valid alternate slug as an alias. This does not authorize merging or deleting two pre-existing files. If the entities are distinct but confusable, use [same-surface-form handling](edge-cases.md#same-surface-form-different-technique); renaming an existing entry remains a refactoring proposal.

An empty wiki still needs candidate-to-candidate checks. Unreadable or malformed index entries can conceal aliases, so unresolved index problems keep unmatched candidates at `adjudicate` and block creation based on apparent absence.

## Merge Logic

### Integration principle

Integrate the active source into **one coherent explanation organized by the entity**, not by source chronology. Before rewriting, apply the [source-no-op test](#source-no-op-merges). For a regular merge:

- Preserve every substantive existing claim unless inspected evidence supports a correction under [Conflict handling](#conflict-handling). Uncited hand edits are still merge input; preserve and report an unresolved conflict rather than discarding them.
- Weave new facts into the relevant part of the body. Extend a paragraph only when they advance its controlling idea; otherwise split or reorder the affected prose. Apply the [paragraph-flow test](writing.md#prose-principles), including neighboring boundaries. Change the opener only for a meaningfully better main claim.
- Reapply [atomic scope and content selection](writing.md#2-the-body). There is no size target. Create and link a distinct entity substantively taught by the new source; do not move or delete pre-existing off-scope content without separate refactor authority. Report that proposal instead. Optional examples or figures do not earn a place merely by being available.
- A sentence rewrite does not create link provenance. Link a target only when the active source introduces it or contributes a substantive relationship to it. Rephrasing a carried-over claim never restores a previously pruned link; genuine new source support may do so and is reported.
- For `Software`, reapply the [API substance gate](api-surface.md). Using a library to teach another concept, or listing its classes/settings, earns neither software prose nor a source append. Integrate artifact-wide interface/design knowledge, not catalogs or recipes. Another API object exemplifying an already-covered convention is duplicate coverage.

Check the completed body for accidental concatenation: duplicate openers or bolded title introductions, duplicated mechanism explanations, stray YAML keys or digits, and unexpected `---` fences. The required separator before `## Flashcards` is legitimate. Resolve these into one body before publication.

### Frontmatter and Related footer

Shared [schema](../../../shared/CONVENTIONS.md#2-frontmatter-schemas) and [source-reference rules](../../../shared/CONVENTIONS.md#7-source-references) govern encoding. [Writing fields](writing.md#1-frontmatter-fields) govern meaning. Apply these update rules only when a value actually changes:

1. **`sources:`** Append a missing full citation with normal deduplication; report a rerun's anchor drift. Replace a Markdown summary reference with its PDF only after decoded provenance confirms the pair. Preserve independent clippings and unresolved references; report uncertainty. Record confirmed representation replacements in *Review-pass fixes*. PDFs use the entity's introducing physical page; Markdown has no anchor.
2. **`updated:`** Set to today's local date when the entry actually changes, including metadata or independent QC. Preserve the prior date for a byte-unchanged result. This is independent of the narrower [`read:` reset](#the-read-reset). Preserve `created:`.
3. **`aliases:`** Append only valid same-entity aliases observed in the new source, deduplicated in slug form including case/normalization equivalents. Preserve a pre-existing semantic-invalid alias and report its evidence and likely owner; removing it requires wiki-lint's [explicit refactor mode](../../wiki-lint/references/refactors.md) and complete inbound rewrite. That boundary does not prevent within-list duplicate cleanup.
4. **`tags:`** Keep exactly one supported home, never an additive discipline list. Correct a clearly wrong home, multiple homes, or blank/empty list from the entity's meaning and evidence; use `"#misc"` only when no specific home fits. Preserve/report genuinely ambiguous or malformed metadata. Report every old/new group for wiki-lint's hierarchy refresh.
5. **`parents:` and legacy `importance:`** Preserve exactly as found. This skill does not populate parents, migrate legacy importance, or strip it during a body rewrite.
6. **`description:`** Rewrite only when meaningfully more accurate, informative, or grammatically clear, or to fix a concrete [description defect](writing.md#description); different phrasing alone is insufficient. Source-no-op merges permit defect repairs, not new-content-driven rewrites.
7. **Related footer:** Source-driven integration preserves existing links and adds only substantive relationships introduced by the active source. A carried-over bare mention does not justify an addition. A source-no-op adds no source-driven neighbor. Separate targeted QC may canonicalize a target/label or remove a proven invalid link under its own rules; weak-link pruning belongs to wiki-lint. Follow the [footer format and size guidance](writing.md#the-related-footer), reporting growth past roughly 12 links rather than pruning unilaterally.

### Exhibits and headings

**Images.** Preserve existing images and captions with their motivating prose. If they no longer fit the entry, propose consolidation/removal; do not silently delete them or add a tangent to justify them. Select incoming figures under [media selection](media.md#selection). Replacement is allowed only for a strictly clearer or more complete depiction of the **same specific aspect**, not merely the same subject. Name both images and the concrete benefit in the report; preserve the underlying files. For example, keep a reinforcement-learning action/reward-loop diagram rather than replacing it with an applications gallery.

**Tables.** Preserve existing recreated tables with their motivating prose; propose consolidation if needed. Select new tables under [Body structure](writing.md#body-structure). Replace only when the new source presents **the same data** more completely or correctly, including useful added rows/columns or clearer headers. Related but different datasets, such as parameter and performance-comparison tables, do not subsume each other.

**Equations.** Follow [equations on merge](equations.md#4-normalization--the-sources-symbols-do-not-survive-contact), which owns preservation, authorized simplification, same-quantity replacement, and notation normalization. A new explanatory equation adds unread body content; a format-only normalization does not. Do not force mathematics into a simple verbal concept.

**Headings.** These are narrative organization, not preserved exhibits. Add, remove, rename, or reorder `##` headings when the integrated explanation warrants it under [Body structure](writing.md#body-structure), never merely because of length. A new-source subsection with a distinct supported identity becomes its own candidate; redistributing pre-existing content still needs separate refactor authority.

### Flashcards on merge

Read the canonical [card format](flashcards-and-emphasis.md#4-flashcards) and [review-history rules](../../wiki-lint/references/flashcards.md) before changing a card. They own the primary-answer contract, protected attachment forms, and semantic definition review. Missing visible scheduling metadata never proves an existing card is fresh.

- **Every merge, including source-no-ops:** run item-19 QC on every card. Restore a missing primary card from the entry's established main claim with `??`; repair current-rule defects in place. Apply the [line-1 equation-coverage rule](flashcards-and-emphasis.md#line-1-equation-coverage) to the same tested claim, preserving cue, answer-line bytes, and attachments during that targeted repair. It requires useful supported math, not an invented equation or different learning objective.
- **Regular merges, primary definition:** if integration substantively changes the main claim, re-derive line 1 and replace it only when meaningfully more accurate or unambiguous. Mere phrasing drift does not qualify. If inspected evidence corrects a claim and its card now contradicts the body, correct the card in place rather than removing and re-adding it.
- **Primary answer:** recompute its term content when the canonical title, qualifying alias counterpart, or the opener's direct binding changes. An already-listed alias can gain or lose qualification when that binding changes. Apply the canonical line-3 contract; preserve the cue and attached state.
- **Legacy extras:** review each against its own answer and tested claim, not the entry's title or opener. Preserve and quote every extra card in full, including attachments, in *Notes for the user*. Create no additional cards. A second source-supported entity may earn its own entry and card; background knowledge never supplies it. Moving/removing a pre-existing card requires an explicitly authorized source-backed refactor accounting for its claim and every attachment, or a request naming that card for deletion. A source merge alone supplies no such authority.

Every pre-existing `??`/`!!` cue and recognized scheduling/block-ID attachment stays byte-for-byte and in place, even when a content line changes. A conforming card stays unchanged. Card-only repairs advance `updated:` under the actual-change test and preserve `read:`.

### The `read:` reset

Apply the shared [review-checkbox contract](../../../shared/CONVENTIONS.md#2c-read--the-users-review-checkbox). Never infer missing, null, or unknown user state. For a known value, set `read: false` **only when adding or rewriting unread explanatory body content**, whether from the active source or independent step-7 QC: prose, an image or recreated table, a newly typeset equation, a Person/Event date, or a rewritten explanation.

Metadata/alias/source appends, description/card/footer/tag repairs, content removal, and format-only fixes do not reset it. `updated:` still follows any actual change. When the unread-content judgment is close, preserve `read:` and report the decision. Name every reset and every close no-reset call in the run report.

### Source-no-op merges

A candidate must first pass step 2's substance filter and, for secondary sources, durability filter. After [example selection](writing.md#prose-principles) and [figure selection](media.md#selection), compare **every selected source contribution** with the existing entry:

- A fact is already covered when present verbatim or as a clear paraphrase.
- A selected figure is already covered by the same `Sources/Images/` filename; a table by the same recreated data; an equation by the same quantity's definition. Different notation alone is not new content.
- For `Software`, compare interface/design ideas, not identifier spelling. Another named class following an already-explained estimator contract adds no idea; a substantively taught artifact-wide limitation may do so.

If all selected contributions are covered, classify the entry as **source-no-op-merged**. A documented decision to skip an optional example or figure does not make it net-new. One new selected fact, relationship, image, table, or equation makes the merge regular. Explicit reruns often produce source-no-ops, but still require this comparison.

A source-no-op skips source-driven body, description, card, and Related-footer rewriting. Conforming content stays byte-for-byte unchanged. It still applies the ordinary metadata append/preserve rules and **all step-7 QC and audits**, making only the targeted repairs those rules authorize. Examples include a supported Person/Event date, an equation warranted by carried-over prose, or removal of a navigation-only cue. Description/card defects can also be repaired; source-no-op is not an exemption from current rules.

Classification concerns the source's contribution, not the final bytes. An independent QC equation insertion can leave the active source a no-op while advancing `updated:` and resetting a known `read:` value; a new equation contributed by the active source is a regular merge. Pure metadata/card/format repairs advance `updated:` without resetting `read:`. A byte-unchanged result preserves both fields.

Report these separately as `Entries source-no-op-merged: N (the active source added no net-new selected content)`, not under regular `Existing entries merged`. Itemize metadata/QC changes normally, record review-state decisions, and identify byte-unchanged results. Do not describe a QC-changing run as leaving the wiki unchanged.

### Net-new fact test

Compare meaning before integrating wording. “LambdaRank scales pairwise gradients by the NDCG change from swapping items” adds nothing to an entry already saying it weights pairs by that swap's NDCG change. A source-supported relationship to LambdaLoss absent from the body is net-new. Integrate it at the appropriate conceptual location under the [integration principle](#integration-principle); do not append a source-shaped addendum.

### Conflict handling

Resolve a contradiction only from the active source and the existing entry's cited sources that can actually be inspected. Methods, scope, date, and authority may weigh evidence only when those sources establish them. Memory, uncited background knowledge, and assumed consensus cannot settle it.

- **Existing claim supported, new contradiction unsupported:** preserve the existing claim and omit the contradictory clause. Integrate unrelated supported contributions normally and record a qualifying source's contribution in `sources:`.
- **Existing claim disproved by inspected evidence:** correct it in place.
- **Evidence partial or unresolved:** synthesize only what the sources jointly support; otherwise preserve the existing claim, omit the contradictory clause, and report both claims with source pages.

Report every correction or unresolved conflict and its evidence. Write the resolved subject matter as ordinary prose under [prose principle 5](writing.md#prose-principles), not a transcript of which source said what.

**Contested-topic exemption.** Philosophical positions, historical interpretations, religious doctrines, and similar subjects can have legitimately coexisting views. When the disagreement is itself part of the subject, present source-supported views in parallel with light attribution, such as “the materialist reading argues …”; this applies both to fresh entries and merges. Scientific disputes or disagreements between an established and fringe view use the evidence rule above. Describe consensus or fringe status only when inspected sources establish it; otherwise preserve/report the unresolved disagreement.

Conflict detection here is per merge, not a comparison of every existing entry. Report any incidentally noticed cross-entry contradiction in *Notes for the user*; resolve it through separately requested source-backed wiki-lint correction/refactor work, according to whether cross-entry redistribution is needed.
