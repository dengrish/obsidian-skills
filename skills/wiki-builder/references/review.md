# Audits and run report

Read this at [workflow step 7](../SKILL.md#7-review-and-report), before finalizing any run that wrote entries. The [Quality Checklist](../SKILL.md#quality-checklist) remains the numbered acceptance contract. Steps mentioned below refer to the builder workflow.

- [The two audits](#the-two-audits)
- [Missed-entity audit](#missed-entity-audit-source-coverage)
- [Orphan-link audit](#orphan-link-audit-this-runs-entries)
- [Run report](#run-report)

## The two audits


Both run at the end of step 7, in this order: **missed-entity, then orphan-link.** The order is load-bearing. The missed-entity audit creates entries, and new entries carry new wikilinks; running it last means those links never reach the orphan sweep, so the run ships exactly the dangling links steps 6 and 7 exist to prevent. Do the recovery first, then audit the state it leaves behind.

**Whatever the audits create gets the Quality Checklist run over it** — recovered entries. The per-file pass is finished by then, so nothing else will: an audit-created entry ships a 130-character `description:`, a bare common-noun slug or a missing `## Flashcards` section exactly as easily as an in-run one.

### Missed-entity audit (source coverage)

The third failure shape the orphan sweep can't reach: **substantive terms in the source that should be entries, aren't, and aren't wikilinked from anywhere either.** For each source processed this run, re-walk it applying the same step-2 filters — (b) for any source, and (c) additionally for secondary ones.

**Enumerated lists get a verdict per item, not per list.** When the source runs through candidates in a list — an applications catalog, a "techniques include" paragraph, a bulleted survey — record an explicit entry/defer/reject-with-reason for *each item*, because wholesale judgment is exactly where siblings diverge silently: a real run accepted six items of one list and skipped two others whose predication was the same shape, and the skipped ones are invisible forever, since a term with no node and no report line is the one thing no later audit can surface. For each term that passes, check the wiki state:

- **Already an entry** (filename or alias match) → noted, move on.
- **Extracted this run** (on the accepted list) → noted, move on.
- **Rejected this run with a reason** (2a code-identifier, 2b substance, 2c durability, thin mention) → noted, move on.
- **None of the above** → an overlooked candidate. Run it through the step 3 → step 4 / step 5 flow it would have taken if step 2 had caught it: a new entry from the source's coverage, or a merge if it resolves under any collision probe. When the source's coverage is too thin for a full entry, it gets no node — list it under *Entities deferred* instead. Log every recovery in the report (slug, action, one-line note on what the source said).

The audit re-runs extraction with a different question than step 2: not "what's substantive here?" but "what did step 2 miss?" Reading the source *against* the wiki state is cognitively different from reading it cold — the existing entries give a concrete reference point that catches omissions forward extraction doesn't. **The bar is identical to step 2, not looser.** A passing mention is not a miss; it is a non-candidate that was correctly rejected, and the same goes for transient signal in a secondary source. The value here is completeness, not over-extraction on the second pass. Plausible misses on a transformer-era ML source: `tokenization`, `byte-pair-encoding`, `pretraining`, `transfer-learning`, `attention` as the broader concept behind `self-attention`. **Multi-source runs** audit per source in the run's own sequential order, so a term missed by source A is still recovered when B is audited.

### Orphan-link audit (this run's entries)

**Rebuild the index first** — the missed-entity audit just ran and may have created entries; resolving against the pre-audit index reads links into those entries as dangling, and the default fix below then destroys valid links (or the create-the-entry branch writes over a file that exists). Then walk the wikilinks in **the entries this run created or merged** — including everything the missed-entity audit just added — and check that each target resolves to a real file in `Wiki/`. Body wikilinks and Related-footer wikilinks only: `sources:` points at PDFs and notes rather than entries, and `parents:` belongs to another skill. **Resolution is case- and Unicode-normalization-insensitive, because that is how Obsidian and the vault's APFS volume resolve it**: a target that matches an existing entry apart from case (`[[roc-curve]]` against `ROC-curve.md`) is a *resolving link with a spelling defect* — fix the link's target to the on-disk slug, and never "stub" it, since on a case-insensitive volume that stub write opens the existing file and overwrites the whole entry. For every `Wiki/` target that genuinely doesn't exist:

- **Default fix: unlink to bare text** — replace `[[slug|Display Label]]` with the label as plain text, and drop the matching Related-footer item. A dangling link at this point is a workflow slip (step 6 links only targets that exist), so the link is what gets repaired. **Never create a placeholder file to make a link resolve.**
- **If the prose genuinely teaches about the target** (the positive trigger in `references/writing.md` §3), the miss is upstream: create the **full entry** from the source's coverage and keep the link. Coverage too thin for that → unlink, and list the entity under *Entities deferred*.

**This audit is scoped to this run's entries, and that is a deliberate narrowing.** Its guarantee is that no dangling link ships from this run — not that the vault contains none. Orphans inherited from earlier runs, and every other vault-wide linking concern, are `wiki-linter`'s: it is the skill that walks the whole vault, and giving one job to two skills is what produced the alternating add-then-prune churn described in step 6. The narrowing costs nothing this run can see, because every link this run wrote is a link this run gets to check.

## Run report

Each bullet appears only when it has content, except the audit bullets, which report their count even when zero (so it's visible the audit ran):

- **Sources processed** — filename(s), classification, counts: `attention.pdf — primary; 9 entries created, 2 merged`. When step 1 resolved a pairing, name both files and which one was read: `attention.pdf — primary (read in place of the note attention.md the run was handed)`.
- **Sources skipped (previously processed, no re-run intent)** — `<filename> (already in N entries)`
- **Sources skipped (no durable content)** — `<filename> — <classification>; <one-line reason>`
- **Entities accepted** — with type breakdown
- **Entities rejected** — one-line reason each (code-identifier 2a, substance 2b, durability 2c, or thin-mention-on-existing-entry)
- **Entities deferred (too thin this source)** — entities that read as real nodes-to-be but got only a sentence or two, so no entry was written and their mentions stay plain text; one line each naming what the source did say, so a future source picks them up deliberately.
- **New entries created**, **Legacy stubs promoted**, **Existing entries merged** (one-line note each), **Entries no-op-merged**. Each list also includes items the missed-entity and orphan-link audits produced, not just in-run ones; on a re-run under explicit intent the no-op bullet typically dominates.
- **`read:` reset** — the merged entries whose body gained content, so their checkbox is now `false` again, with the one-line reason each (new paragraph, new figure, rewritten explanation, promotion). **Name every close call and say which way it went**, including the ones that went to *no reset* — this bullet is the only place the user sees a checkbox of theirs being cleared, and a reset they disagree with costs them a re-read they didn't need.
- **Missed-entity audit** — per source, terms recovered, plus `(source, slug, action)` triples.
- **Orphan-link audit** — orphans found / entries created / links unlinked to bare text, plus slugs. Scoped to the entries this run created or merged.
- **Unused source figures** — per source, the `[source_stem]_fig*` files not placed, each with its skip reason (Condition 1 *no information*; Condition 2 *same aspect as …*; Condition 3 *maps only to an entity with no entry*). Panels — a label ending in a lowercase letter, `..._fig_3a.png` beside `..._fig_3.png` — are not listed here: they are pieces of a figure, not figures of their own. A figure with no documented reason is a default violation — re-walk and place it. A long list means the use-by-default rule was violated.
- **Review-pass fixes** — anything caught and fixed.
- **Notes for the user** — anything else, with two-options framing wherever a call could go either way: contested claims, Contested-topic exemptions, a Related footer past ~12, borderline substance/durability/classification calls, blank `tags:`, debatable tag calibration, an image or table replaced rather than added, a merged entry that became a split candidate, an entity thin in each source but substantive combined, a proposed rename or deletion, a contradiction noticed between two existing entries.

**Close every report with one standing line:** *vault-wide cross-linking is `wiki-linter`'s job — run it when you want cross-source connections.* It states a property of the skill boundary, not a finding about this run, so it reads identically every time and never gets dressed up as an observation about what this particular run left undone.
