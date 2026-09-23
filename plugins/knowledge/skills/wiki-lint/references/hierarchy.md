# Hierarchy — `parents:` and MOCs (Task 3)

Read this before creating or updating MOCs, recomputing `parents:`, or acting
on `hierarchy_diagnostic`. A MOC is a **fully generated navigation note**: discipline trees live at
`MOCs/<discipline-slug>.md`, and entries tagged only `#misc` have a root and title-sorted member list in
`MOCs/misc.md`. Its complete content is a bullet outline derived from the
current Wiki entries. It contains no ownership
comments, H1, frontmatter, or separate prose sections, except the final
[skill-provenance footer](../../../shared/PROVENANCE.md). That metadata is not
part of the navigation tree. A footer-only misc MOC is an empty outline.

`parents:` and the MOCs are two renderings of one concept hierarchy.
Every active discipline has a Wiki root entry at `Wiki/<discipline-slug>.md`.
The root has `parents: []`; all other parents resolve to broader Wiki entries,
never to MOCs. A MOC displays the root and its descendants as a generated
outline. `#misc` uses `Wiki/misc` with one level of title-sorted members.

## Scope closure

Seed the requested entries and named disciplines. Include every current and
proven prior group of those entries, all members of those groups, their Wiki
roots, and their MOCs. Repeat until stable. Keep old-tag and old-placement
evidence across rescans so retagging removes stale membership. Legacy
multi-tagged entries connect all their old groups while Task 1 selects one home.

Run Task 3 only when the request covers that complete set; otherwise report
the required expansion and complete the narrower authorized tasks. Never
publish part of a MOC or leave parents derived from a different plan. Blank,
malformed, or uncertain tags need QC before placement; they do not imply misc.
Preserve a specific-discipline MOC that loses its final member and report it
as inactive. An authorized misc refresh clears an existing zero-member list
to an empty outline, retaining its provenance footer, and keeps the file.

## Establish discipline roots

Reuse the canonical Wiki entry for each active tag, checking filename, identity,
and tag ownership rather than treating a same-named MOC or alias as the root.
When a root is missing, Task 3 may create that narrow prerequisite using
builder's entry rules and [wiki-add's durable-source research](../../wiki-add/references/research.md).
Prefer suitable local evidence; otherwise acquire a concise, authoritative
source extract. Do not fabricate citations or create every unused enum root.
This exception creates only the roots needed by the authorized closure and
does not alter the user's topic queue or extract unrelated entities.

A discipline root is a short explanation of the field, not a duplicate MOC.
The misc root explains the organizational fallback. Use the ordinary entry
schema, one matching tag, a primary-definition card, and `parents: []`.
Preserve existing roots' substantive content, review state, and card history
under the normal correction rules. A blocked source or ambiguous root owner
blocks that group's publication; never fall back to an MOC parent.

## Derive the hierarchy

**Review every included MOC and every parent assignment semantically on every
Task 3 run.** Read the entries and compare siblings and candidate parents;
scanner silence and an unchanged membership list are not evidence that the
organization makes sense. The prior MOC is context, not the default answer.
Fix existing conceptual defects even when no entries were added. Keep an
already coherent structure stable rather than reorganizing for variety.

- Put the discipline's Wiki root at the single top-level bullet.
- Group by concepts, with each child a meaningful subtype, component, method,
  or narrower topic of its parent. Association alone does not establish a
  broader/narrower relationship. Keep closely related definitions together;
  inspect contrasts such as loss/cost and the whole regression family.
- Use existing broader entries as linked categories. Use an unlinked category
  only when no appropriate entry exists, and skip it when deriving parents.
- Use as much depth as the conceptual relationships need. Do not flatten
  genuine subtrees to satisfy a fixed depth limit. Avoid empty or redundant
  categories and chains that contribute no useful distinction.
- Place every entry once in its single discipline by default. A second
  placement needs a distinct, useful broader relationship; it must not conceal
  uncertainty over where the entry belongs.
- For misc, use its root followed by one level of member links sorted by
  case/Unicode-normalized canonical title, with vault-relative paths as ties.
  Do not invent conceptual subdivisions for this fallback bucket.

Keep a compact review ledger covering every included entry's home and parent,
with the reason for changed relationships. This can stay in run scratch;
do not create a dated review note in the vault.

## Populate `parents:`

Render parents from the same final tree: each entry receives its nearest
linked Wiki ancestor, skipping unlinked categories. A top-level branch below
the root receives `[[Wiki/<discipline-slug>]]`. The root itself is the sole
completed-placement exception with `parents: []`; nothing self-parents.
Misc members receive `[[Wiki/misc]]`, and its root keeps `[]`.

Write populated parents as a block list of double-quoted wikilinks. Preserve
unknown relationships until their QC or scope blocker is resolved. Recompute
stale, self-linked, or cyclic edges within the complete authorized closure.
For genuine multiple placements within the single home, take the nearest
ancestor union. Never infer parents across unrelated disciplines.

**Use unambiguous paths.** Root links use the actual extensionless vault-relative
Wiki path, e.g. `[[Wiki/machine-learning]]`. All generated MOC links use such
qualified paths and canonical display titles. Other entry parents may use an
unambiguous slug, but qualify shared basenames. MOC navigation links remain
`[[MOCs/<discipline-slug>]]` and can never supply a parent.

Before creating a same-named Wiki root, inventory bare links to the existing
MOC across the vault. Preserve their proven navigation owner by qualifying
them within the authorized scope; do not redirect them to the new entry.
Existing ambiguous links need evidence, not a global string replacement.

## Build or maintain the MOC files

The **whole recognized discipline or misc MOC belongs to Task 3**. Within an authorized
closure, regenerate its complete content from the derived placement plan and
publish it through the shared safe-write protocol, preserving/updating the
provenance footer under its shared rules. Other comments,
frontmatter, headings, and prose are obsolete generated formatting and are
removed during regeneration under that whole-file ownership. This does not
extend to unknown files in `MOCs/`, other vault notes, or suggestion logs.

A discipline MOC is a nested bullet list, for example:

```markdown
- [[Wiki/machine-learning|Machine learning]]
  - Learning paradigms
    - [[Wiki/supervised-learning|Supervised learning]]
    - [[Wiki/reinforcement-learning|Reinforcement learning]]
  - [[Wiki/generalization|Generalization]]
```

For discipline trees, use two spaces per level. Each bullet is either a piped entry link with its
canonical readable title or an unlinked category term. There are no trailing
descriptions, inline comments, H1, or frontmatter. The provenance footer follows
the outline after a blank line. Drop a trailing title
parenthetical that repeats this discipline's name, but retain a finer
qualifier: `[[Wiki/clustering-machine-learning|Clustering]]` is suitable in the
machine-learning MOC, while `[[Wiki/pruning-decision-trees|Pruning (decision trees)]]`
keeps the qualifier that distinguishes it from pruning neural networks.
The link target always retains the entry path and slug.

**Preflight paths before writing.** `MOCs/` must be a real directory under the
selected vault; create it only when absent. Reject a non-directory occupant,
directory or leaf symlink, unreadable path, case/NFC-equivalent folder or file
collision, and duplicate canonical/old-root MOC ownership. Inventory existing
canonical paths and recognized old root occupants before initializing a missing
file. Preserve an unexpected old root note and report its ownership conflict;
never silently create a second MOC or move the old note during routine lint.
Preserve the entire connected closure when ownership or readability is unsafe.

Before introducing a new MOC basename, inspect links to any Wiki entry sharing
it. Qualify only references whose prior entry owner is proven, within the
authorized reference scope, so creation does not redirect them to navigation.
Preserve already ambiguous targets and report any required out-of-scope repair.

Read and snapshot the existing MOC's complete bytes, identity, and permissions
when deriving the replacement. Compare complete output bytes and skip a no-op.
Create a missing file exclusively; conditionally replace an existing file only
against that original snapshot. Whole-note ownership never authorizes replacing
a later editor save. Publish and verify the MOC and corresponding parents in
the same task. If a path changes or a write is interrupted, report the actual
state and re-read/re-derive the same authorized closure before retrying; the
per-file guards do not make the group transactional.

**Inactive discipline MOCs.** If a discipline has zero valid members, preserve its
existing MOC byte-for-byte and report it as inactive, including stale links or
obsolete formatting. Do not create an empty replacement or delete the file
unless cleanup is explicitly requested. These preserved
findings do not prevent the active hierarchy from completing, but must not be
described as repaired. **Misc is different:** refresh its entire list from all
entries tagged only `#misc` in the authorized misc closure. If that list is empty,
clear an existing misc file to an empty outline and keep its provenance footer.
An explicit request can create empty misc; never apply the inactive-discipline
preservation rule to retain stale misc members.

## Read diagnostics and verify completion

`hierarchy_diagnostic` describes current files; it never grants write scope.

- `placement_gaps` records missing and represented disciplines per entry. Recompute included
  entries' complete unions; preserve out-of-scope findings.
- `unresolved_parents` uses `missing`, `ambiguous`, `unparsed`,
  `unreadable`, `legacy-moc`, or `noncanonical-moc`. A real Wiki file outranks
  an alias even when unparsed. An old root MOC cannot supply a canonical root,
  and a real `MOCs/<unknown>.md` outside the discipline enum is
  `noncanonical-moc` and cannot be a recognized root. Preserve uncertain targets; fix relationships
  only inside the authorized closure.
- `parent_state_findings` reports `moc-parent`, `missing-discipline-root`,
  `root-parent-mismatch`, and `misc-parent-mismatch`. Roots must have empty
  parents; misc members must point only to `Wiki/misc`. Missing roots require
  the source-backed prerequisite above, never a fabricated hierarchy edge.
- `moc_inventory_findings` and `legacy_moc_states` establish path ownership,
  including unsafe/noncanonical paths, duplicates, unexpected old root occupants,
  unknown MOC names, and inactive canonical MOCs. Old root notes are report-only
  occupants outside generated ownership. Whole-note ownership applies only
  after a recognized discipline or misc pathname has a unique safe owner.
- `moc_file_states` is `missing`, `empty`, `readable`, or `unreadable`.
  Missing/empty active files can be initialized; readable recognized files
  can be regenerated completely. `unreadable` carries the path and error and
  blocks the connected closure, including unsafe filesystem ownership.
- `moc_consistency_findings` validates the **whole file**: bullet structure,
  canonical targets/labels, entry coverage, duplicate placements,
  wrong-group links, discipline eponymous-root shape, misc member order and single child level, and parent-union
  consistency. A valid final provenance footer is metadata outside the outline;
  malformed or misplaced provenance is reported. Other comments, prose, headings,
  fences, and frontmatter are malformed outline lines; none delimit a separately
  owned region.
  Exact union comparison requires every expected group MOC to be readable/empty and
  structurally parseable with usable placements; any unsafe linked ancestor
  or occurrence blocks inference, even if another occurrence is usable.
- `self_parented` and `parent_cycles` identify edges to recompute from the
  derived hierarchy. Their absence alone does not prove complete placement.

After a completed closure, every included entry with valid membership has no placement gap,
unresolved/invalid parent, self-parent, or cycle. Every active included MOC is
readable (or empty misc with zero members), contains only the complete generated
outline plus its valid provenance footer when present, and has no consistency
finding. Each included entry's parents exactly
match its nearest linked Wiki ancestors; discipline roots alone have `parents: []`. Re-scan to verify these conditions. After a
full-vault pass they hold for all active disciplines, misc, and requested entries;
inactive discipline MOCs and skipped closures remain explicitly reported and
preserved.
Any remaining active in-closure finding requires re-deriving that same closure
before declaring completion.
