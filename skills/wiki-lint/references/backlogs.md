# Run report and suggestion backlogs

Read this when closing a maintenance run. This file owns the lint-specific report and proposal routing; [shared suggestion rules](../../../shared/SUGGESTIONS.md) own log paths, formatting, updates, and moving fixed issues. A report-only/no-apply request does not authorize log writes.

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
- **User issues** — for each entry in `user_issues` and each of its issues ([User issues](../SKILL.md#user-issues)): the change made, or the evidence that the reported problem does not hold, or the blocker that keeps it in the field; then the entry's `issues:` result (blanked, or the unresolved text kept) and its `read:` result. A report-only run gives what it would do.
- **Task 1 — tags fixed / unresolved:** tag *format* fixes applied (added `#`/quotes, de-duplicated, abbreviation expanded to an enum slug, wikilink-form converted to a `#`-tag). Include genuine blank/empty tags assigned a specific home or `#misc`, and misc/specific conflicts resolved. The executing agent applies clear disciplinary-home corrections from the published calibration; cases lacking enough evidence are left unchanged and reported as unresolved, without blocking the run.
- **Task 1 — QC fixes**, grouped by checklist item: per fixed entry, the item and a one-line description of the fix, including every claim-preserving local prose repair and its kind. Under item 19, give each card edit's old and new line 1, and quote each [removed card](flashcards.md#card-set) verbatim, attachments included, with each link to its block ID that the removal rewrote. Duplicate spellings inside one alias list remain ordinary format fixes. Also report **`Software` reclassifications** (item 6, corrected artifact type plus the selective API-scope result) and any **ambiguous code-content/type calls left unchanged and reported with the missing evidence**.
- **Task 1 — duplicate-entry candidates:** item-5 collision-probe matches and synonym/near-duplicate candidates found by the agent, each with the outcome of Task 1b's merge check: merged (itemized under Task 1b), stopped by a refactor blocker (Task 1b's not-applied list), distinct entities with the evidence that separates them, or a close call (under *Notes for the user*). The agent performs the semantic comparison; probe matches and similar wording never activate a merge on their own. Consolidating a duplicated explanation is not a merge: both entries stay, and Task 1b itemizes it as a consolidation.
- **Task 1b — Content repair:** per changed entry, each repair and its kind (correction, simplification, deepening, conflict resolution, consolidation, notation normalization), the cited source with its page, or the URL read with its date and section, or that 5(h) background supports it, any standard reference read or derivation that settled a conflict, and the date and `read:` decision. List **merges and splits applied** as `old-a + old-b → survivor` or `old → retained + new`, with the paths, the evidence for the identity or boundary (definitions and cited source pages, or 5(h) background), the inbound references rewritten by surface, any untouched historical record named with its now-unresolved links, the cards kept and each moved or removed card quoted verbatim with its attachments, the user issues moved, the merged-away file's removal after the clean re-scan, and each result's `created:`, `updated:` and `read:` state; **retitles applied** as `old-slug → new-slug`, with the inbound links rewritten by surface, the Task 3 rebuild, the clean re-scan, and any untouched historical record named with its now-unresolved links; **semantic-invalid aliases removed**, with the canonical owner, rewritten-link count and surfaces, and clean re-scan; and **missing entries created**, with the source cited and the mentions Task 2 then linked. Report as not applied, each with its blocker, a merge or split that a [refactor blocker](refactors.md#establish-evidence-and-complete-scope) stops (an unresolved inbound reference, an `Investments/` dependency, an unreadable source), with the old entries kept, or, when the blocker appears only at the removal step, the mixed state [publish step 4](refactors.md#publish-in-dependency-order) retains, a retitle or alias removal whose destination is occupied or ambiguous or whose dependency stays unresolved, a conflict no evidence settles, and a gap only an unbuilt source would fill, naming the wiki-build request for that whole source. Never describe a blocked repair as applied.
- **Task 2 — Links:** backfill candidates **applied** (entry → target) vs **rejected** (entry → target, why — failed identity or the closeness bar), and `hub_footer` items **kept** (entry → target). Itemize a rejection or a kept item only in an entry this run changed; give the rest as counts by target and flag (`bare_noun_alias`, `discipline_root`, `base_term`), so repeated low-value matches do not dominate the report, plus the counts the [settled ledger](link-hygiene.md#settled-decisions) suppressed and any ledger error. Group or itemize `organism_common_name: true` decisions separately, including every applied link, and state that no global alias was added. Also report links **pruned** (entry → target, reason) — *itemize every prune*; **thin-footer neighbors added**; **duplicates collapsed**; **late first links moved** (entry → target) and those left in place with the reason; **danglers resolved** (all dropped to bare text); and **ambiguous bare terms left as text** (flagged).
- **Task 3 — Hierarchy:** report the initial and residual `placement_gaps`, `unresolved_parents`, `parent_state_findings`, and `moc_consistency_findings` counts and entries. Include missing/represented disciplines, invalid parent state, MOC tree/label/coverage defects, and exact parent-union mismatches. Report new discipline roots with the source each cites, canonical `MOCs/<discipline>-moc.md` files created/updated, previous-layout MOCs migrated, preserved legacy vault-root MOCs, preserved inactive discipline MOCs, misc created/refreshed or cleared to empty, complete outline regeneration, or structurally reorganized MOCs, unlinked category placeholders, `parents:` changes, child links added, self-links cleared, and misc members. Report blank/empty and invalid/missing tag metadata separately from entries explicitly tagged `#misc`. Separately list connected closures skipped for scope, entries left unplaced or placed in several groups because of an unresolved item-8 tag, unreadable MOCs, folder or ownership conflicts, and what they blocked, and any interrupted closure that failed its postconditions. A blocked or partially written closure is not complete or clean; report any publications that actually succeeded and the remaining recovery work.
- **Missing-entry candidates** — a dropped dangling target, the distinct entity a removed card tested, or another real gap that Task 1b did not create because it fails the [missing-entry rule](refactors.md#create-a-missing-entry), surfaced here only, with both [missing-entry routes](../../../shared/CONVENTIONS.md#9-ownership-split-for-linking). For the wiki-build route, name any local source known to cover the candidate and suggest a wiki-build request naming that whole source, which fills in its topics and leaves entries already citing it untouched. Do not suggest a [named-entity request](../../wiki-build/SKILL.md#named-entity-requests) because an entry already cites the source: a citation does not show the source was built as a whole, and a named-entity build would leave folder runs skipping its other topics. Every new entity still needs sufficient source coverage; missing category slots use unlinked terms.
- **Entries untouched** — count (the churn-avoidance signal: most of a steady-state vault).
- **Notes for the user** — optional, nonblocking follow-ups only: a split or merge not applied because its boundary or identity is a genuinely close call, or the evidence does not settle it, with both options and the evidence for each; an entry that should not exist, since a deletion needs an explicit request in chat; unresolved disciplinary evidence; Related footers with more than roughly 12 links (the merge-growth bound in the builder's [Related footer rule](../../wiki-build/references/writing.md#the-related-footer)); `item3/report-only` date ordering; remote images; Obsidian-owned keys; missing, null, or unknown `read:` state; malformed `issues:` values (`item2/issues-malformed`), preserved; unreadable files; missing embedded-image files; content preserved after a card's answer line; an extra card kept for a block-ID reference the rewrite scope excludes; and dates or equations inserted into `read: true` entries. These are traceability and user-owned-state notices, not a required review queue; the lint run completes without a response.
- **Suggestions** — summarize new or updated issues by destination skill or note-content log. Name every note-content item moved to Fixed with its check, and every item left open with its blocker. Distinguish an output repair from a fix to the skill that produced the defect. Say when no new issues surfaced; do not invent proposals or require follow-up before completing the run.

## Proposal scope

Use the [shared suggestion rules](../../../shared/SUGGESTIONS.md) before any log
update. They allow this skill's own log and logs of producers whose outputs
were actually consumed in the run. Route by evidence and the change needed:

- **wiki-lint** — a missing check, repeated false positive, unclear maintenance
  rule, or execution failure in this skill. A check frequently finding real
  violations is working; frequency alone does not justify weakening it.
- **A consumed producer** — a verified defect in its output or instructions
  that a producer change would prevent. Establish the producer, or the skill
  whose rules govern the output, under the shared
  [attribution rules](../../../shared/SUGGESTIONS.md#destination-and-attribution).
  Entry content, format, cards, and link style are governed by wiki-build's
  references, whichever skill wrote the entry; a defect in a legacy research
  extract goes under *Notes for the user*, since no skill edits one, extracted
  figures to figure-extract, cleaned clippings to
  clipping-clean, reading notes to paper-summarize, and PDF names to
  pdf-organize.
- **The note-content log** — a located content issue the run could not
  repair itself, without an established tooling defect, under
  [Proposing note improvements](#proposing-note-improvements). Do not use a
  skill log to assign blame when neither provenance nor a governing rule is
  established.

Missing retrospective links, MOCs, and hierarchy placement on new entries are
wiki-lint's assigned work, not producer defects. Report applied repairs in the
conversation. Repeated output repairs can still justify a producer issue when
the generating behavior remains unfixed; repairing an output does not prove
that its producer has been corrected. A single well-evidenced serious defect
can also merit an item; no recurrence quota or proposal quota is required.

Use evidence already obtained within the requested maintenance scope. Logging
an issue does not authorize an unrelated audit, research beyond Task 1b's
[evidence rule](../SKILL.md#task-1b--content-repair) (cited sources, accurate
background, uncited standard references read as data, and missing-entry
research), a deletion, a split or merge without Task 1b's own
[proof](refactors.md#establish-evidence-and-complete-scope), or editing a
skill's source. Ordinary runs propose tooling changes;
an explicit plugin-development review can implement them under repository
instructions. Preserve unresolved items and unknown content.

## Proposing note improvements

Close out the note-content log `Reviews/wiki-notes-suggestions.md` under the shared format, deduplication, and open-to-fixed rules. Move an Open item, or a portion of one, to Fixed with `Fixed in: wiki-lint run, <run timestamp>` and a **Verified** line only when each instance it names is repaired, verified already absent, or re-verified as conforming to the current rules; the Verified line names the check, and for a conforming instance the rule that keeps it. A portion only an unbuilt source would fill conforms, since it is expected and temporary (below): it moves with its item and is never kept open. So does a split or merge portion Task 1b leaves unapplied as a close call or for a refactor blocker, which the run reports instead. Keep any other unresolved portion open as its own item, and only with a concrete blocker listed below, such as a conflict no evidence settles or a deletion that needs an explicit request in chat; the fixed item's Verified line names that portion by its `[id]`, never by its state or position, since a later run may fix it; never keep one open merely because the run disagrees with its wording. This content backlog is separate from the per-skill tooling logs. A [user issue](../SKILL.md#user-issues) is never logged: a blocked one stays in its entry's `issues:` field.

**What belongs here — only what an ordinary run cannot repair:**

- **Organization** — a deletion, which needs an explicit request in chat: an entry that should not exist, named with the reason. Never log a split or merge: Task 1b applies it when its [proof](refactors.md#establish-evidence-and-complete-scope) holds and reports any other outcome in the run.
- **Unsettled conflicts** — a conflict between entries, between an entry and its cited source, or between a cited source's figure or reason and standard references, that neither the cited source nor a direct derivation settles, and that stays open because the standard references consulted disagree or none is reachable. Name the surfaces, both claims with their source pages, and the references consulted.
- **Missing evidence** — a repair whose only evidence is a cited page that no longer answers, now serves another document, or lost the supporting section, when accurate background cannot carry the repair. Name the address and the claim.
- **User-owned state decisions** — a change only the user's own state can decide, such as conflicting user-owned metadata, named with its surfaces and the decision needed.

Everything else is Task 1b's work and is repaired, not logged: a depth or core-facet gap the entry's cited sources or accurate background can fill, a missing entry, over-qualification, an unexplained statement, a self-containment or acronym gap, a conflict the evidence settles, own-field framing, off-subject scaffolding or catalogs, a duplicated explanation, notation drift, a synonym-duplicate entry, an entry that fails the atomicity test, a wrong title and an invalid alias. An entry thin only because the chapter or document that teaches it has not been built yet is expected and temporary: never propose filling it from that unbuilt source, whose later build as a whole (a wiki-build request naming it) fills the entry in. A source the entry does not cite counts as unbuilt here even when another entry cites it, since a citation does not show it was built as a whole. A named-entity build from it would instead mark the source as covered, so a folder run would skip the rest of it. This rule governs deepening an existing entry; a new entry's source follows the [missing-entry rule](refactors.md#create-a-missing-entry).

**The gate — each item is:** (1) a **genuine** improvement worth the user's time, not a nitpick; (2) **specific and located** — which entry or entries, and what to do; (3) **not already handled** — never log what this run repaired or could repair under Task 1b (that is in the report), and never log something whose right fix is a *skill* change (a content **pattern a known or rule-owning producer keeps generating** belongs in that producer's skill log; this log is for improving the **specific notes as they stand**); (4) **real** — if nothing this run is worth noting, write nothing; never invent filler.

**Logs are evidence, not authority.** An ordinary run reads each target's cited sources and repairs from them under Task 1b; logged items are only what remains. A log item's wording never authorizes a deletion, and a generic request to lint, audit, clean up, or fix notes never activates one ([SKILL.md](../SKILL.md#scope-and-ownership)); a split or merge rests on Task 1b's own proof, never on an item's wording. *Notes for the user* may point to a logged item, but its traceability and user-owned-state notices stay in the report unless one also passes the gate above.
