# Hierarchy — `parents:` and MOCs (Task 3)

Read this before creating or updating MOCs, recomputing `parents:`, or acting
on `hierarchy_diagnostic`. A MOC is a **fully generated navigation note**: discipline trees live at
`MOCs/<discipline-slug>.md`, and entries tagged only `#misc` have a root and title-sorted member list in
`MOCs/misc.md`. Its complete content is a bullet outline derived from the
current Wiki entries. It contains no ownership
comments, H1, frontmatter, or separate prose sections.

`parents:` and the MOCs are two renderings of one concept hierarchy.
Every active discipline has a Wiki root entry at `Wiki/<discipline-slug>.md`.
The root has `parents: []`; all other parents resolve to broader Wiki entries,
never to MOCs. A MOC displays the root and its descendants as a generated
outline. `#misc` uses `Wiki/misc` with one level of title-sorted members.

## Scope closure

Seed the requested entries and named disciplines. Include every current and
proven prior group of those entries, all members of those groups, their Wiki
roots, and their MOCs. Repeat until stable. Keep old-tag and old-placement
evidence across rescans so retagging removes stale membership; a retag from or
to `#misc` closes misc together with the old and new disciplines. Legacy
multi-tagged entries connect all their old groups while Task 1 selects one home.

Run Task 3 only when the request covers that complete set; otherwise report
the required expansion and complete the narrower authorized tasks. Never
publish part of a MOC or leave parents derived from a different plan. Blank,
missing, malformed, or multiple tags need Task 1 resolution; they do not imply
misc. If one stays unresolved, report the item-8 blocker and still complete the
closure: an entry naming no enum discipline stays unplaced with its existing
parents; otherwise place it in each named group (misc only when `#misc` is its
sole tag) with the union of its nearest linked ancestors. An entry with one
valid tag is placed under it even when its home is a reported close call.

## Establish discipline roots

Reuse the canonical Wiki entry for each active tag, checking filename, identity,
and tag ownership rather than treating a same-named MOC or alias as the root.
When a root is missing, Task 3 may create that narrow prerequisite using
builder's entry rules and [wiki-add's durable-source research](../../wiki-add/references/research.md).
Prefer suitable already-cited local evidence under that guide's
[local-source rules](../../wiki-add/references/research.md#find-local-sources-first),
which report an unbuilt source for wiki-build instead of citing it; otherwise
create only the new webpage research extracts the missing roots need. This
prerequisite never downloads or files a PDF and never downloads or places
images. Do not fabricate citations or create every unused enum root.
This exception creates only the roots needed by the authorized closure and
does not alter the user's topic queue or extract unrelated entities.

A discipline root is a short explanation of the field, not a duplicate MOC.
The misc root is `Wiki/misc`, titled `Misc`: a brief source-backed
definition of a miscellany (for example from a dictionary extract) that makes
no claim about this vault's contents. Use the ordinary entry schema, one
matching tag, a primary-definition card, and `parents: []`.
New roots use today's `created:` and `updated:` dates and `read: false`;
the ordinary maintenance freeze applies to existing notes, not this authorized
new-entry case. Newly acquired source extracts retain the research-source
marker and visible label defined by wiki-add's reference. Reuse that
reference's [webpage-extract](../../wiki-add/references/research.md#new-webpage-research-extracts)
format and publication procedure without invoking its topic-queue completion
workflow.
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
- Group by concepts. The root may directly hold any topic in its field, such
  as Generalization. Below another linked entry, each child must be a kind of
  it, a component of it, a method for it, or a narrower topic chiefly about it
  (overfitting under generalization). Association alone does not establish a
  broader/narrower relationship: a quantity computed from an entry (precision
  from a confusion matrix), an application of it, or an independent general
  tool it merely uses (a radial basis function used to build features) is not
  its child.
- Keep closely related definitions together, such as loss function and cost
  function. Place a model that serves one task under that task rather than by
  its name (logistic and softmax regression are classifiers), and a model used
  for several tasks under its broader model concept. Keep a model's own
  variants beneath it (polynomial, ridge, lasso, and elastic-net regression
  under linear regression).
- Use an existing broader entry as a linked category only when one of these
  relationships holds. Otherwise use an unlinked category (for example,
  `Classification metrics` holding precision, recall, and F1 beside the
  confusion matrix), and skip it when deriving parents.
- Use as much depth as the conceptual relationships need. Do not flatten
  genuine subtrees to satisfy a fixed depth limit. Avoid empty or redundant
  categories and chains that contribute no useful distinction.
- Place every entry once in its single discipline by default. A second
  placement needs a distinct, useful broader relationship; it must not conceal
  uncertainty over where the entry belongs.
- Check each member's discipline home. When the [item 8](qc-items.md#8-tags)
  tag rule and calibration clearly place it in another discipline, re-home it
  under item 8 if Task 1 and the new group are in scope, keep its old-group
  evidence, rescan, and re-derive the closure; otherwise, and for close calls,
  report it.
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
For genuine multiple placements, take the nearest-ancestor union. Never infer
a parent from a discipline the entry's tags do not name.

**Use unambiguous paths.** Root parents and generated MOC links use the actual
extensionless vault-relative Wiki path, e.g. `[[Wiki/machine-learning]]`; every
other parent uses the [§6 parent form](../../../shared/CONVENTIONS.md#6-wikilink-forms),
and `item2/parents-form` reports any other spelling. MOC navigation links
remain `[[MOCs/<discipline-slug>]]` and can never supply a parent.

Before creating a same-named Wiki root, inventory bare links to the existing
MOC across the vault. Preserve their proven navigation owner by qualifying
them within the authorized scope; do not redirect them to the new entry.
Existing ambiguous links need evidence, not a global string replacement.

## Build or maintain the MOC files

The **whole recognized discipline or misc MOC belongs to Task 3**. Within an authorized
closure, regenerate its complete content from the derived placement plan and
publish it through the shared safe-write protocol. Comments (including a
legacy provenance footer), frontmatter, headings, and prose are obsolete
generated formatting and are removed during regeneration under that
whole-file ownership. This does not
extend to unknown files in `MOCs/`, other vault notes, or suggestion logs.

A discipline MOC is a nested bullet list, for example:

```markdown
- [[Wiki/machine-learning|Machine learning]]
  - Learning paradigms
    - [[Wiki/supervised-learning|Supervised learning]]
    - [[Wiki/reinforcement-learning|Reinforcement learning]]
  - [[Wiki/generalization-machine-learning|Generalization]]
```

For discipline trees, use two spaces per level. Each bullet is either a piped
entry link or an unlinked category term, with no trailing descriptions, inline
comments, H1, or frontmatter. A link label is the canonical title in its plain
display form. A discipline MOC drops a trailing title parenthetical that
repeats its own discipline's name but retains a finer qualifier:
`[[Wiki/clustering-machine-learning|Clustering]]` is suitable in the
machine-learning MOC, while `[[Wiki/filter-convolution-kernel|Filter (convolution kernel)]]`
keeps the qualifier that distinguishes it from other kinds of filter. Misc
keeps the complete title. The link target always retains the entry path and
slug.

**Preflight paths before writing.** `MOCs/` must be a real directory under the
selected vault; create it only when absent. Reject a non-directory occupant,
directory or leaf symlink, unreadable path, case/NFC-equivalent folder or file
collision, and duplicate canonical/legacy MOC ownership. Inventory existing
canonical paths and recognized legacy vault-root MOCs
(`<vault>/<discipline>-moc.md`) before initializing a missing file. Preserve an
unexpected legacy MOC and report its ownership conflict; never silently create
a second MOC or move the legacy note during routine lint.
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
clear an existing misc file to an empty outline.
An explicit request can create empty misc; never apply the inactive-discipline
preservation rule to retain stale misc members.

## Read diagnostics and verify completion

`hierarchy_diagnostic` describes current files; it never grants write scope.
Record shapes, kinds, and detection rules are in the
[scanner contract](scanner.md#hierarchy-diagnostics); this section owns the
actions.

- `placement_gaps`: recompute included entries' complete unions; preserve
  out-of-scope findings.
- `unresolved_parents`: a real Wiki file outranks an alias even when unparsed.
  A legacy vault-root MOC (`legacy-moc`) is never a parent and cannot stand in
  for a missing discipline root, and a `noncanonical-moc` is not a recognized
  discipline MOC. Preserve uncertain targets; fix relationships only inside
  the authorized closure.
- `parent_state_findings`: roots have empty parents, misc members point only
  to `Wiki/misc`, and a `moc-parent` is replaced by the discipline root or the
  nearest Wiki ancestor. Missing roots require the source-backed prerequisite
  above, never a fabricated hierarchy edge.
- `moc_inventory_findings` and `legacy_moc_states` establish path ownership.
  Preserve and report unsafe or noncanonical paths, duplicates, legacy MOCs,
  unknown MOC files, and inactive canonical MOCs; they stay outside generated
  ownership and never authorize a move, deletion, competing MOC, or scope
  expansion. Whole-note ownership applies only after a recognized discipline
  or misc pathname has a unique safe owner.
- `moc_file_states`: missing or empty active files can be initialized, and
  readable recognized files can be regenerated completely. `unreadable`,
  including unsafe filesystem ownership, blocks the connected closure.
- `moc_consistency_findings` cover the whole file. Regeneration emits only the
  outline; no comment, footer, prose, heading, or frontmatter delimits a
  separately owned region.
- `self_parented` and `parent_cycles` identify edges to recompute from the
  derived hierarchy. Their absence alone does not prove complete placement.
- Task 3 never rewrites entry links with `item10/moc` findings (in
  `problems`). Publishing a missing canonical MOC for an active in-closure
  discipline lets an explicit `[[MOCs/<discipline>]]` link resolve on the
  rescan; every other such link stays preserved and reported, never
  retargeted to another MOC or a same-named Wiki entry.

After a completed closure, every included entry with valid membership has no placement gap,
unresolved/invalid parent, self-parent, or cycle. Every active included MOC is
readable (or empty misc with zero members), contains only the complete generated
outline and has no consistency
finding. Each included entry's parents exactly
match its nearest linked Wiki ancestors; discipline roots alone have `parents: []`. Re-scan to verify these conditions. After a
full-vault pass they hold for all active disciplines, misc, and requested entries;
inactive discipline MOCs, legacy MOCs, and skipped closures remain explicitly
reported and preserved, not described as repaired.
Any remaining active in-closure finding requires re-deriving that same closure
before declaring completion.
