# Audits and run report

Scope: the step-7 audits and run report of a run that drafted or merged entries; the [Quality Checklist](../SKILL.md#quality-checklist) stays the acceptance contract.

## The three audits

Run them as [step 7.6](../SKILL.md#7-review-and-report), in this order: **missed-entity, overlap/ownership, then orphan-link**, since each can change what the next checks. **Whatever the audits create or change gets the Quality Checklist**, step 7.3's source check, the [editorial reread](writing.md#editorial-reread) and a `review_tree.py` rerun, as in step 7, before continuing.

### Missed-entity audit (source coverage)

This audit catches **substantive terms in the source that should be entries, aren't, and aren't wikilinked from anywhere either**, which the orphan sweep cannot see. Re-walk each source processed this run under the same step-2 filters ((b) always, (c) for secondary sources), per source in the run's order so a term source A missed is still recovered with B. A [named-entity](../SKILL.md#named-entity-requests) run audits only its named entities, confirming each retained source's contribution is integrated.

**Give verdicts per item, not per list or chapter.** Every item of an applications catalog, "techniques include" paragraph or bulleted survey gets entry, defer or reject-with-reason, since a skipped term with no node and no report line is invisible to every later audit. So does every heading that names a durable entity and is followed by substantive treatment, even a subtype of the main topic (a `Regression` subsection on regression trees does not vanish into `Decision tree`), while thin organizational headings still fail the substance bar. **Contrasted concepts get separate verdicts:** extracting sampling bias does not cover sampling noise; recover a supported counterpart, never one invented from symmetry or a passing mention.

For each item that passes, check the wiki state:

- **Processed for this source this run** (created, merged or source-no-op-merged), or already citing it in a [fill-in](source-intake.md#check-prior-coverage) run → noted; another source's result in the batch does not count.
- **An entry exists but was not processed for this source** → an overlooked merge, since existing ownership does not prove this source was integrated: run step 3 and the merge and no-op gates.
- **Rejected this run with a reason** (2a, 2b, 2c, thin mention) → noted.
- **None of these** → an overlooked candidate: take it through step 3, step 4 or 5, and step 6 (its own links, plus the first eligible mention of it in this run's other entries under [link provenance](merge.md#integration-principle)), or list it under *Entities deferred* when coverage is too thin, and log every recovery (slug, action, what the source said).

**The bar is identical to step 2, not looser:** the audit asks what step 2 missed, reading the source against the wiki state, and a passing mention or a secondary source's transient signal stays a correctly rejected non-candidate.

### Overlap/ownership audit (this run's entries and their relevant neighbors)

Compare every entry this run created or merged, recoveries included, with the other current-run entries **and with relevant existing canonical neighbors**: those its body and Related links resolve to, and any existing entry the missed-entity audit's wiki-state check found owning a concept that current-run prose explains. Look for duplicated explanatory work: the same worked example, mechanism walkthrough or multi-sentence explanation of a neighboring entity in more than one note. Judge meaning and ownership, not word overlap: a concise reciprocal contrast can belong in both entries, and shared terminology alone is no finding. Nor is a model entry's own prediction step and objective, or a one-line restatement of a neighbor's formula.

Give the full treatment to the most specific canonical entry whose subject it explains; an umbrella or related note keeps the shortest relationship needed for orientation and a wikilink (`Law of large numbers` owns the biased-coin illustration; `Hard voting` keeps its consequence for ensemble errors and a link).

Fix duplicate treatment in prose the active source contributed this run, even when an untouched existing note is the canonical owner, and re-run the per-entry checklist on each repair; never edit that neighbor merely because it entered the comparison. When the overlap is wholly pre-existing, or resolving it would move or delete an earlier source's material, preserve it and record a proposal naming the passages and intended owner in `Reviews/wiki-notes-suggestions.md` under the [shared suggestion rules](../../../shared/SUGGESTIONS.md).

### Orphan-link audit (this run's entries)

**Rebuild the private combined-view index first** by rerunning `review_tree.py`, so drafts the missed-entity audit added resolve; its `dangling` and `noncanonical` lists are the mechanical floor, and a `dangling` item that lists `unmirrored` paths keeps its link when the real vault has the target. Every body and Related-footer wikilink in **the entries this run created or merged**, audit additions included, must name exactly one entry by its filename; `sources:`, `parents:` and MOC navigation are outside the audit, and missing or unsafe MOC destinations are reported for wiki-lint. Apply each `noncanonical` link's `replacement` exactly as given, and never create a variant file. Retarget an `ambiguous` one to the entry the prose means, path-qualified when [§6](../../../shared/CONVENTIONS.md#6-wikilink-forms) requires, or report an inherited one the prose leaves open. For every target with no match:

- **Default fix: unlink to bare text** and drop the matching Related-footer item. **Never create a placeholder file to make a link resolve.**
- **If the prose genuinely teaches the target** under the [positive trigger](../SKILL.md#2-extract-entities), create its **entry** from the source's coverage and keep the link; with coverage too thin, unlink it and list it under *Entities deferred*.

Inherited orphans and vault-wide linking are `wiki-lint`'s ([linking ownership](../../../shared/CONVENTIONS.md#9-ownership-split-for-linking)). The audit is no refactoring exception: it repairs this run's links through the normal gates and edits nothing outside the [run's scope](../SKILL.md#scope-and-files).

## Run report

Include a bullet only when it has content; the audit bullets always report their counts, zero included:

- **Sources processed** — filename, classification and counts; for a pairing, both files and which was read.
- **Sources filled in or skipped** — per file: filled in (N entries already cited it), folder-run skip (already in N entries; name it to fill it in), or no durable content (classification and reason).
- **Entities accepted** — with type breakdown.
- **Entities rejected** — one-line reason each (2a, 2b, 2c, or a thin mention on an existing entry).
- **Entities deferred (too thin this source)** — real nodes-to-be without enough source-grounded substance for a self-contained entry; their mentions stay plain text. When identified sources are substantive only in combination, name the candidate and files for a [named-entity request](../SKILL.md#named-entity-requests).
- **Entities not requested (named-entity run)** — substantive entities the source teaches that the request did not name.

  For both lists give one line each with its page, what the source says and the [missing-entry routes](../../../shared/CONVENTIONS.md#9-ownership-split-for-linking), listing first the entities this run's published prose mentions in plain text. Record each of those in `Reviews/wiki-notes-suggestions.md` as `[missing-<slug>] Missing entry: <Title>`, naming its source and page.
- **New entries created**, each with the most specific existing entry its opener names as its kind or method, proposed as its parent for wiki-lint; **Existing entries merged** (one-line note each); **Entries source-no-op-merged** (no net-new selected content; itemize any metadata append or QC fix and name the byte-unchanged ones). Each list includes the audits' additions.
- **`read:` reset** — each merged entry whose pass added or rewrote unread explanatory body content (QC insertions on source-no-op merges included), with a one-line reason. **Name every close call and say which way it went**, including *no reset*: this is the only place the user sees a checkbox of theirs cleared.
- **Missed-entity audit** — per source, `(source, slug, action)` triples.
- **Overlap/ownership audit** — groups reviewed, resolved or proposed, each with its canonical owner.
- **Orphan-link audit** — orphans found, entries created, links unlinked, with slugs.
- **Unused source figures** — each unused exhibit or shared-reason group with its [selection](media.md#selection) reason, panels under their composite; any extraction run, its crops and which were visually reviewed.
- **Atomicity decisions** — borderline split or keep calls, with the identity and source-support reason, never length.
- **Review-pass fixes** — anything caught and fixed.
- **Unresolved findings and lint dispositions** — each unresolved in-scope finding or blocker and its cause, each finding step 7 reports without repairing, and each retained [review-only candidate](../SKILL.md#7-review-and-report) with its reason.
- **Source-backed relinks after an earlier prune** — entry → target and the active source's new relationship, never a reworded or moved old sentence.
- **Semantic-invalid aliases proposed for removal** — entry, alias, active-source evidence and likely owner; proposals, never review-pass fixes.
- **Notes for the user** — anything else, as two options where a call could go either way: contested claims or contradictions between entries; footers past ~12, preserved unexpected keys, inherited missing dates; borderline substance, classification or tag calls; proposed media changes (name both exhibits), splits, renames or deletions.

**Close every report with one standing line:** *Vault-wide cross-linking and placing new entries under `parents:` and in the MOCs are `wiki-lint`'s job — run it to connect and file this run's entries.* It states the skill boundary, not a finding, and never varies.
