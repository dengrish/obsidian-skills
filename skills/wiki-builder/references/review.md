# Audits and run report

Read this at [workflow step 7](../SKILL.md#7-review-and-report), before finalizing any run that drafted or merged entries. The [Quality Checklist](../SKILL.md#quality-checklist) remains the numbered acceptance contract. Steps mentioned below refer to the builder workflow.

- [The three audits](#the-three-audits)
- [Missed-entity audit](#missed-entity-audit-source-coverage)
- [Overlap/ownership audit](#overlapownership-audit-this-runs-entries-and-their-relevant-neighbors)
- [Orphan-link audit](#orphan-link-audit-this-runs-entries)
- [Run report](#run-report)

## The three audits

Run them at the end of step 7 in this order: **missed-entity, overlap/ownership, then orphan-link.** The order is load-bearing. Missed-entity recovery can create a more specific owner for material already drafted elsewhere; the overlap sweep must see that entry. Recovery and overlap repair can also add or change wikilinks, so the orphan sweep runs last against the final state.

**Whatever the audits create or change gets the Quality Checklist run over it.** The per-file pass is finished by then, so nothing else will catch a recovered entry with an overlong description or an overlap repair that disturbed paragraph flow. Re-lint each affected file before continuing.

### Missed-entity audit (source coverage)

The third failure shape the orphan sweep can't reach: **substantive terms in the source that should be entries, aren't, and aren't wikilinked from anywhere either.** For each source processed this run, re-walk it applying the same step-2 filters — (b) for any source, and (c) additionally for secondary ones.

**Enumerated lists get a verdict per item, not per list.** When the source runs through candidates in a list — an applications catalog, a "techniques include" paragraph, a bulleted survey — record an explicit entry/defer/reject-with-reason for *each item*, because wholesale judgment is exactly where siblings diverge silently: a real run accepted six items of one list and skipped two others whose predication was the same shape, and the skipped ones are invisible forever, since a term with no node and no report line is the one thing no later audit can surface. For each term that passes, check the wiki state:

**Source headings get the same ledger.** Every heading that names a durable entity and is followed by substantive treatment receives an explicit existing/accepted/deferred/rejected verdict, even when it names a subtype of the source's main topic. A dedicated `Regression` subsection that explains regression-tree prediction and training cannot disappear inside the broader `Decision tree` candidate merely because the chapter title is broader. Thin organizational headings still fail the ordinary substance bar.

- **Already an entry** (filename or alias match) → noted, move on.
- **Extracted this run** (on the accepted list) → noted, move on.
- **Rejected this run with a reason** (2a code-identifier, 2b substance, 2c durability, thin mention) → noted, move on.
- **None of the above** → an overlooked candidate. Run it through the step 3 → step 4 / step 5 flow it would have taken if step 2 had caught it: a new entry from the source's coverage, or a merge if it resolves under any collision probe. When the source's coverage is too thin for a full entry, it gets no node — list it under *Entities deferred* instead. Log every recovery in the report (slug, action, one-line note on what the source said).

The audit re-runs extraction with a different question than step 2: not "what's substantive here?" but "what did step 2 miss?" Reading the source *against* the wiki state is cognitively different from reading it cold — the existing entries give a concrete reference point that catches omissions forward extraction doesn't. **The bar is identical to step 2, not looser.** A passing mention is not a miss; it is a non-candidate that was correctly rejected, and the same goes for transient signal in a secondary source. The value here is completeness, not over-extraction on the second pass. Plausible misses on a transformer-era ML source: `tokenization`, `byte-pair-encoding`, `pretraining`, `transfer-learning`, `attention` as the broader concept behind `self-attention`. **Multi-source runs** audit per source in the run's own sequential order, so a term missed by source A is still recovered when B is audited.

### Overlap/ownership audit (this run's entries and their relevant neighbors)

Compare every entry this run created, promoted, or merged, including missed-entity recoveries, with the other current-run entries **and with relevant existing canonical neighbors** resolved through its body and Related links. Also inspect an existing note when the active source's candidate ledger identifies it as the likely owner of a concept explained in current-run prose. This comparison set catches a new umbrella note duplicating an untouched specific note without turning the audit into a whole-vault lexical sweep. Look for duplicated explanatory work: the same worked example, mechanism walkthrough, or multi-sentence explanation of a neighboring entity appearing in more than one note. Judge meaning and ownership, not word overlap. A concise reciprocal contrast can be necessary in both entries, and two passages sharing terminology are not a finding by themselves.

Give the full treatment to the most specific canonical entry whose subject it explains. An umbrella or related note keeps only the shortest relationship needed for orientation and a wikilink. For example, if the run creates both `Law of large numbers` and `Hard voting`, the law note owns the full biased-coin illustration; the voting note keeps the consequence for ensemble errors and links to the law.

Fix prose contributed by the active source during this run before finalizing. This run already owns that draft and can remove or consolidate its duplicate treatment, including when an untouched existing note is the canonical owner. Do not edit that neighbor merely because it entered the comparison set. If the overlap is wholly pre-existing, or resolving it would move or delete material contributed by an earlier source, preserve it and report a proposal naming the passages and intended owner. `wiki-linter` may record that proposal; applying it belongs to a later source-backed editing pass. Re-run the per-entry checklist on every current-run repair.

### Orphan-link audit (this run's entries)

**Rebuild the private combined-view index first** — the missed-entity audit just ran and may have drafted entries; resolving against the pre-audit or public-only index reads links into those drafts as dangling, and the default fix below then destroys valid links (or the create-the-entry branch duplicates a staged path). Then walk the wikilinks in **the entries this run created or merged** — including everything the missed-entity audit just added — and check that each target resolves to exactly one entry in the proposed resolution tree. Body wikilinks and Related-footer wikilinks only: `sources:` points at PDFs and notes rather than entries, and `parents:` belongs to another skill. **The plugin compares link identity case- and Unicode-normalization-insensitively on every host.** A target with one such inventory match (`[[roc-curve]]` against `ROC-curve.md`) is an existing target with a spelling defect: rewrite it to the exact proposed on-disk slug. Never create a competing variant file; some filesystems alias the two spellings while others store both, and either outcome breaks portable ownership. Immediately before publication, rebuild this index from current public snapshots plus final drafts so a late occupant cannot invalidate the audit unnoticed. For every target that genuinely has no inventory match:

- **Default fix: unlink to bare text** — replace `[[slug|Display Label]]` with the label as plain text, and drop the matching Related-footer item. A dangling link at this point is a workflow slip (step 6 links only targets that exist), so the link is what gets repaired. **Never create a placeholder file to make a link resolve.**
- **If the prose genuinely teaches about the target** (the positive trigger in `references/writing.md` §3), the miss is upstream: create the **full entry** from the source's coverage and keep the link. Coverage too thin for that → unlink, and list the entity under *Entities deferred*.

**This audit is scoped to this run's entries, and that is a deliberate narrowing.** Its guarantee is that no dangling link ships from this run — not that the vault contains none. Orphans inherited from earlier runs, and every other vault-wide linking concern, are `wiki-linter`'s: it is the skill that walks the whole vault, and giving one job to two skills is what produced the alternating add-then-prune churn described in step 6. The narrowing costs nothing this run can see, because every link this run wrote is a link this run gets to check.

## Run report

Each bullet appears only when it has content, except the audit bullets, which report their count even when zero (so it's visible the audit ran):

- **Sources processed** — filename(s), classification, counts: `Vaswani_AttentionIsAllYouNeed_2017.pdf — primary; 9 entries created, 2 merged`. When step 1 resolved a pairing, name both files and which one was read: `Vaswani_AttentionIsAllYouNeed_2017.pdf — primary (read in place of the note attention.md the run was handed)`.
- **Sources skipped (previously processed, no rerun/resume intent)** — `<filename> (already in N entries)`
- **Sources skipped (no durable content)** — `<filename> — <classification>; <one-line reason>`
- **Entities accepted** — with type breakdown
- **Entities rejected** — one-line reason each (code-identifier 2a, substance 2b, durability 2c, or thin-mention-on-existing-entry)
- **Entities deferred (too thin this source)** — entities that read as real nodes-to-be but lack enough source-grounded substance for a self-contained atomic entry, so no entry was written and their mentions stay plain text; one line each naming what the source did say. When identified sources appear substantive only in combination, name the candidate and files so an explicit [candidate-specific synthesis](multi-source-synthesis.md) rerun can evaluate them.
- **New entries created**, **Legacy stubs promoted**, **Existing entries merged** (one-line note each), **Entries source-no-op-merged**. The source-no-op bullet says only that the active source contributed no net-new selected content; separately itemize any metadata append or QC fix, and identify which source-no-ops were byte-unchanged. Each list also includes items the missed-entity and orphan-link audits produced, not just in-run ones; on a re-run under explicit intent the source-no-op bullet typically dominates.
- **`read:` reset** — the merged entries whose pass added or rewrote unread explanatory body content, so their checkbox is now `false` again, with the one-line reason each (new paragraph, figure, equation, Person/Event date, rewritten explanation, promotion). Include QC-driven insertions on source-no-op merges. **Name every close call and say which way it went**, including the ones that went to *no reset* — this bullet is the only place the user sees a checkbox of theirs being cleared, and a reset they disagree with costs them a re-read they didn't need.
- **Missed-entity audit** — per source, terms recovered, plus `(source, slug, action)` triples.
- **Overlap/ownership audit** — overlap groups reviewed / resolved in current-run prose / proposed as legacy refactors, naming each canonical owner and affected entries. Report zero when none are found.
- **Orphan-link audit** — orphans found / entries created / links unlinked to bare text, plus slugs. Scoped to the entries this run created or merged.
- **Unused source figures** — reconcile every source's complete inventory, including local `[source_stem]_fig*` files, remote Markdown references, and figures with no available file. Give each unused exhibit a specific reason under the [selection rule](media.md#selection). Group panels under their composite rather than counting them separately. An unrecorded figure needs review and a decision, not automatic placement; a long skip list is acceptable when the reasons hold.
- **Atomicity decisions** — name borderline split/keep calls: an umbrella and children partitioned from this source, an inherent facet kept with its entity, or a pre-existing mixed entry proposed for later refactoring. Give the identity and source-support reason; note length alone is never the reason.
- **Presentation exceptions** — name an example beyond the usual single ~2-sentence illustration or an additional figure, and give one concrete line explaining its benefit under [writing guidance](writing.md#2-the-body) and [figure selection](media.md#selection). Put the justification here, not in the note itself.
- **Review-pass fixes** — anything caught and fixed, including paragraph-focus or progression repairs.
- **Source-backed relinks after an earlier prune** — entry → target, plus the active source's new substantive relationship. Rewording or moving an old sentence is never listed as evidence.
- **Semantic-invalid aliases proposed for removal** — entry, alias, active-source evidence that it names another entity, and the likely canonical owner when known. These are proposals, never review-pass fixes.
- **Notes for the user** — anything else, with two-options framing wherever a call could go either way: contested claims, Contested-topic exemptions, a Related footer past ~12, borderline substance/durability/classification calls, blank `tags:`, debatable tag calibration, a proposed consolidation or removal of existing media, an image or table replaced under the narrow same-aspect rule (name both and the benefit), a merged entry that became a split candidate, an entity thin in each source but substantive combined, a proposed rename or deletion, a contradiction noticed between two existing entries.

**Close every report with one standing line:** *vault-wide cross-linking is `wiki-linter`'s job — run it when you want cross-source connections.* It states a property of the skill boundary, not a finding about this run, so it reads identically every time and never gets dressed up as an observation about what this particular run left undone.
