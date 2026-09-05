# Run report and suggestion backlogs

Read this when closing a maintenance run. This file owns the lint-specific report and proposal routing; [shared suggestion rules](../../../shared/SUGGESTIONS.md) own log paths, formatting, updates, and verified issue removal. A report-only/no-apply request does not authorize log writes.

- [Run report](#run-report)
- [Proposal scope](#proposal-scope)
- [Proposing note improvements](#proposing-note-improvements)

## Run report


End every run with a single consolidated response in the conversation, not a dated Wiki review note:

- **Inventory** — N entries, per-discipline counts including misc, and untagged entries awaiting tag repair.
- **Image-folder observations** — every report-only `image_folder_findings`
  record, grouped by kind (nested item, staging residue, unreadable/unusable
  path, or portable-name collision). These observations never authorize moving,
  renaming, or deleting media.
- **Autonomous agent-review coverage** — `agent-reviewed/readable in-scope entries`, plus every skipped or unreadable file by name and reason. Scanner execution is counted separately from the agent's semantic pass; neither requires user review or sign-off.
- **Task 1 — tags fixed / unresolved:** tag *format* fixes applied (added `#`/quotes, de-duplicated, abbreviation expanded to an enum slug, wikilink-form converted to a `#`-tag). Include genuine blank/empty tags assigned a specific home or `#misc`, and misc/specific conflicts resolved. The executing agent applies clear disciplinary-home corrections from the published calibration; cases lacking enough evidence are left unchanged and reported as unresolved, without blocking the run.
- **Task 1 — QC fixes**, grouped by checklist item: per fixed entry, the item and a one-line description of the fix, including every claim-preserving local prose repair and its kind. Separately, **renames proposed for approval** — each as `old-slug → new-slug`, the inbound-wikilink count that would be rewritten, the reason (stale/variant filename vs. title correction), and a collision flag where the target file already exists — and, if the user approved any during the session, **renames applied** (only the approved ones). Report **semantic-invalid aliases proposed for removal** the same way: entry, alias, evidence that it names another entity, likely canonical owner, inbound alias-target count, and any ownership ambiguity. If approval led to action, list **semantic-invalid aliases removed** separately, with the canonical owner, rewritten-link count and surfaces, and clean re-scan result; never describe a proposal as applied. Duplicate spellings inside one alias list remain ordinary format fixes. Also report **`Software` reclassifications** (item 6, corrected artifact type plus the selective API-scope result) and any **ambiguous code-content/type calls left unchanged and reported with the missing evidence**.
- **Task 1 — duplicate-entry candidates:** item-5 collision-probe matches and synonym/near-duplicate candidates found by the agent are reported as merge proposals. The agent performs the semantic comparison; applying a merge remains approval-gated.
- **Task 2 — Links:** backfill candidates **applied** (entry → target) vs **rejected** (entry → target, why — failed identity or the closeness bar), with `bare_noun_alias: true` rejections grouped by surface/target and count so repeated low-value alias matches do not dominate the report (itemize any applied exception). Group or itemize `organism_common_name: true` decisions separately, including every applied link, and state that no global alias was added. Also report links **pruned** (entry → target, reason) — *itemize every prune*; **duplicates collapsed**; **danglers resolved** (all dropped to bare text); and **ambiguous bare terms left as text** (flagged).
- **Task 3 — Hierarchy:** report the initial and residual `placement_gaps`, `unresolved_parents`, `parent_state_findings`, and `moc_consistency_findings` counts and entries (`placed_unparented` remains the compatibility projection of placement gaps). Include missing/represented disciplines, invalid parent state, MOC tree/label/coverage defects, and exact parent-union mismatches. Report canonical `MOCs/<discipline>.md` files created/updated, authorized legacy path migrations and their verified inbound repairs, preserved inactive discipline MOCs, misc created/refreshed or cleared to empty, complete outline regeneration (including obsolete marker/prose removal), or structurally reorganized MOCs, unlinked category placeholders, `parents:` changes, legacy self-links cleared, and misc members. Report blank/empty and invalid/missing tag metadata separately from entries explicitly tagged `#misc`. Separately list connected closures skipped for scope, unreadable MOCs, folder or ownership conflicts, and what they blocked, and any interrupted closure that failed its postconditions. None may be described as partially updated or clean.
- **Missing-entry candidates** — dangling-link targets that were dropped but look like real gaps (a concept several entries lean on, a heavily-referenced name), surfaced here and in `Reviews/wiki-notes-suggestions.md` so the user can run a supporting source through wiki-build to create them properly. If that source already appears in any entry, say that the builder request must carry explicit **resume/re-run intent**; a plain process request will correctly hit its prior-coverage skip gate. Every new entity still needs sufficient source coverage; missing category slots use unlinked terms.
- **Entries untouched** — count (the churn-avoidance signal: most of a steady-state vault).
- **Notes for the user** — optional, nonblocking follow-ups only: authorization-gated retitles, alias removals, splits, merges, and other vault-wide refactors; unresolved disciplinary evidence; Related footers past the soft cap; `item3/report-only` date ordering; remote images; Obsidian-owned keys; missing, null, or unknown `read:` state; unreadable files; missing embedded-image files; and dates or equations inserted into `read: true` entries. These are traceability and user-owned-state notices, not a required review queue; the lint run completes without a response.
- **Suggestions** — summarize new or updated issues by destination skill or note-content log, and name items removed after verifying their resolution. Distinguish an output repair from a fix to the skill that produced the defect. Say when no new issues surfaced; do not invent proposals or require follow-up before completing the run.

## Proposal scope

Use the [shared suggestion rules](../../../shared/SUGGESTIONS.md) before any log
update. They allow this skill's own log and logs of producers whose outputs
were actually consumed in the run. Route by evidence and the change needed:

- **wiki-lint** — a missing check, repeated false positive, unclear maintenance
  rule, or execution failure in this skill. A check frequently finding real
  violations is working; frequency alone does not justify weakening it.
- **A consumed producer** — a verified defect in its output or instructions
  that a producer change would prevent. This may be wiki-build or wiki-add for
  entry generation, figure-extract for extracted images, or a source-intake
  skill whose artifacts were used. Establish the producer rather than assuming
  every entry came from wiki-build or every image from figure-extract.
- **The note-content log** — a located content gap or worthwhile improvement
  to existing notes, without an established tooling defect. Do not use a skill
  log to assign blame when provenance is unknown.

Missing retrospective links, MOCs, and hierarchy placement on new entries are
wiki-lint's assigned work, not producer defects. Report applied repairs in the
conversation. Repeated output repairs can still justify a producer issue when
the generating behavior remains unfixed; repairing an output does not prove
that its producer has been corrected. A single well-evidenced serious defect
can also merit an item; no recurrence quota or proposal quota is required.

Use evidence already obtained within the requested maintenance scope. Logging
an issue does not authorize an unrelated audit, new-source research, an entry
refactor, or editing a skill's source. Ordinary runs propose tooling changes;
an explicit plugin-development review can implement them under repository
instructions. Remove a logged item only when its specific resolution has been
verified under the shared rules. Preserve unresolved items and unknown content.

## Proposing note improvements

Use `Reviews/wiki-notes-suggestions.md` for worthwhile improvements to specific notes that remain after the permitted local repairs because they need more source evidence, a user-owned state decision, or separately scoped work. Apply the shared format, deduplication, and verified-resolution rules. This content backlog is separate from the per-skill tooling logs.

**What belongs here — broadly, anything that makes the notes better as a body of knowledge:**

- **Depth & gaps** — an entry thin relative to its importance, worth expanding; a concept many entries lean on but none defines (a missing node — often a recurring dangling target); an entry missing a salient aspect the rest of the vault assumes.
- **Clarity & coherence** — a definition that is circular, vague, or conflates senses; a title or qualifier, description, opener, equation, flashcard, or closely linked neighbor whose claims conflict or drift in scope; or a flow problem that cannot be repaired through Task 1's claim-preserving local operations. Name the exact surfaces or paragraph boundary and proposed action; any factual choice requires a source-backed decision. Length, a missing transition word, or lexical overlap alone is not evidence.
- **Scope & catalogs** — under item 9, source/tutorial scaffolding, extended worked narratives, or application catalogs that do not serve this entity; under item 6, `Software` prose that drifts from artifact-wide design into API inventories, defaults, version logs, or recipes; under item 15, an unnecessary or tangential example. Judge purpose, never length or item count. Substantive trimming is proposed for a separate source-backed editing request.
- **Organization** — two entries that are the **same concept under different names** (the synonym-duplicate the slug probes can't catch) and should be merged; an entry that independently defines several durable subjects and should be split into linked atomic notes; a cluster of entries a missing intermediate concept would organize better; lopsided coverage (a discipline with little substantive coverage). A split proposal names the existing slug, proposed note boundaries or titles, the source support that must be checked, and the intended wikilinks. A long note, several headings, or several sources alone is not a split candidate; inherent facets stay together.
- **Formatting & consistency beyond the QC floor** — patterns that are not rule *violations* but read as uneven: similar entries differing in whether they use sub-headings, inconsistent figure use, Related footers that are inconsistently full.

**The gate — each item is:** (1) a **genuine** improvement worth the user's time, not a nitpick; (2) **specific and located** — which entry or entries, and what to do; (3) **not already handled** — never log what the linter auto-fixed this run (that is in the report), and never log something whose right fix is a *skill* change (a content **pattern a known producer keeps generating** belongs in that producer's skill log; this log is for improving the **specific notes as they stand**); (4) **real** — if nothing this run is worth noting, write nothing; never invent filler.

**Faithful to the no-source stance.** With no source in hand, wiki-lint cannot verify facts, so these are observations and suggestions, not authoritative corrections. Routine Task 1 applies only the source-independent repairs enumerated by each QC item. A correction confined to a named entry may use sources it already cites under the source-backed correction protocol; a new source routes to builder. Splits, merges, and cross-entry redistribution use the refactor protocol and additionally require explicit authorization naming the operation or the affected entries and intended outcome. A generic request to lint, audit, clean up, or fix notes does not supply it. Pure renames and semantic-invalid-alias removals follow their approval and complete-reference-rewrite rules. The report's *Notes for the user* and this log carry the same content; the report names new or updated issues and verified closures, with their log paths.
