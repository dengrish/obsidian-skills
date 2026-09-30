# Hierarchy — `parents:` and MOCs (Task 3)

Read this before creating or updating MOCs, recomputing `parents:`, or acting
on `hierarchy_diagnostic`. A MOC is a **fully generated navigation note**: discipline trees live at
`MOCs/<discipline-slug>-moc.md`, and entries tagged only `#misc` have a root and title-sorted member list in
`MOCs/misc-moc.md`. Its complete content is a bullet outline derived from the
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
builder's entry rules. It writes the root from one reliable overview of the
field, such as a textbook introduction or an encyclopedia article (a
Wikipedia page will do), and cites that page by its URL under
[conventions §7](../../../shared/CONVENTIONS.md#7-source-references), or an
already-cited vault document that introduces the field. It creates no source
note, PDF or image. This prerequisite creates only
the roots the authorized closure needs. It never fabricates citations,
alters the user's topic queue or extracts unrelated entities.

A discipline root is a short explanation of the field, not a duplicate MOC.
It defines the field, states its method of inquiry and names its main
branches, linking those with entries. The misc root is `Wiki/misc`, titled
`Misc`: a brief definition of a miscellany that makes no claim about this
vault's contents. Use the ordinary entry schema, one matching tag,
`parents: []` and no Flashcards section; an existing root keeps its card
unless the user asks to remove it. Like every entry, a root cites at least
one source: the page or document it is derived from.
New roots use today's date for `created:` and `updated:` and set
`read: false`; the maintenance date freeze covers existing notes only.
Stage a new root under its own filename and lint it with
`python3 '<plugin>/skills/wiki-build/scripts/lint_entry.py' '<scratch>/<unique-dir>/<slug>.md'`;
resolve every finding before publication.
Preserve existing roots' substantive content, review state, and card history
under the normal correction rules. An ambiguous root owner blocks that
group's publication; never fall back to an MOC parent.

## Derive the hierarchy

**Review every included MOC and every parent assignment semantically on every
Task 3 run.** Read the entries and compare siblings and candidate parents;
scanner silence and an unchanged membership list are not evidence that the
organization makes sense. The prior MOC is context, not the default answer.
Fix existing conceptual defects even when no entries were added. Keep an
already coherent structure stable rather than reorganizing for variety.

- Put the discipline's Wiki root at the single top-level bullet, and nowhere
  else in the tree.
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
  relationships holds; an entry goes under the most specific existing entry
  its opener names as its kind or method (random forest, "trained via
  bagging", under Bagging). Otherwise use an unlinked category, and skip it
  when deriving parents. An unlinked category groups siblings along one axis
  and is named for it (`By incrementality`: batch and online learning). Keep
  named instances such as datasets apart from the concepts they illustrate.
- Order siblings and categories so each follows those it relies on;
  otherwise, and within a dependency cycle, keep the prior order and put a
  new sibling last.
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
the root receives `[[<discipline-slug>]]`. The root itself is the sole
completed-placement exception with `parents: []`; nothing self-parents.
Misc members receive `[[misc]]`, and its root keeps `[]`.

Write populated parents as a block list of double-quoted wikilinks. Preserve
unknown relationships until their QC or scope blocker is resolved. Recompute
stale, self-linked, or cyclic edges within the complete authorized closure.
For genuine multiple placements, take the nearest-ancestor union. Never infer
a parent from a discipline the entry's tags do not name.

**Use unambiguous paths.** Every parent, a discipline root included, uses the
[§6 parent form](../../../shared/CONVENTIONS.md#6-wikilink-forms): the bare
slug, or the extensionless vault-relative Wiki path only when another file
shares the basename. `item2/parents-form` reports any other spelling.
Generated MOC links always use the Wiki path, e.g.
`[[Wiki/machine-learning|Machine learning]]`. MOC navigation links are
`[[MOCs/<discipline-slug>-moc]]` and can never supply a parent.

**Link each parent down.** After publishing parents, rescan. For each included
parent in `unlinked_children`, append the listed children to its Related
footer with the supplied targets and canonical piped labels, `branch_heads`
first and each group in MOC order, until the footer holds twelve links. These
are the only Related links Task 3 adds, and it removes none.

## Build or maintain the MOC files

The **whole recognized discipline or misc MOC belongs to Task 3**. Within an authorized
closure, regenerate its complete content from the derived placement plan and
publish it with `publish_files.py` ([publishing](../SKILL.md#publishing)). Comments (including a
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

**Preflight from the latest scan.** Its MOC inventory already checks `MOCs/`
ownership from a guarded snapshot; act on its records under
[read diagnostics](#read-diagnostics-and-verify-completion) rather than
re-inspecting the folder. An unsafe or unreadable state blocks its connected
closure, which stays untouched. Pass `--create-dir MOCs` to `publish` when
every `moc_file_states` record is `missing` and `moc_inventory_findings` holds
no directory finding (`unsafe-directory`, `ambiguous-directory` or
`noncanonical-directory`), which is how an absent `MOCs/` looks (an empty
folder looks the same, and a `legacy-location` record can accompany either):
`publish` refuses a missing folder without the flag and ignores it when the
folder exists. A recognized legacy vault-root
MOC (`<vault>/<discipline>-moc.md`, a `legacy-location` record) stays in
place: report its ownership conflict, and never silently create a second MOC
or move that note during routine lint. It shares the canonical basename, so
bare links to that name stay ambiguous.

Before introducing a new MOC basename, inspect links to any Wiki entry sharing
it. Qualify only references whose prior entry owner is proven, within the
authorized reference scope, so creation does not redirect them to navigation.
Preserve already ambiguous targets and report any required out-of-scope repair.

Record each MOC path with `publish_files.py snapshot` before reading it to
derive the replacement. Compare complete output bytes and skip a no-op.
`publish` creates a missing file exclusively and replaces an existing file only
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

### Migrate the previous MOC layout

Before knowledge 1.4.0 a discipline MOC was `MOCs/<discipline-slug>.md`,
sharing its basename with the Wiki root, so root links carried `Wiki/`. The
scanner reports each such file as a `previous-layout` inventory finding and
in `legacy_moc_states`; while it exists, root parents stay qualified and bare
root links stay ambiguous. Task 3 migrates it instead of initializing a
second MOC, within an authorized closure for that discipline:

1. When the old file is readable and uniquely owned and the canonical path is
   free, move it there with `move_noreplace` under the shared
   [safe-write protocol](../../../shared/SAFE_WRITES.md#remove-or-move-an-old-pathname-conditionally).
   Record both paths with `publish_files.py snapshot` before reading the old
   file. The driver takes its expected identity from the old file's record,
   and the canonical path is re-recorded after the move, as
   [publishing](../SKILL.md#publishing) describes.
2. Rewrite links that resolved to the old file, `[[MOCs/<discipline-slug>…]]`,
   to the new name, preserving anchors and labels. A bare
   `[[<discipline-slug>]]` could have meant either file; preserve and report it.
3. Rescan, then respell the root's `Wiki/` parents that `item2/parents-form`
   now reports. Give body and Related links to the root the bare target too,
   preserving anchors and labels, unless another vault file shares its name.
4. Regenerate the MOC as usual and report the migration.

## Read diagnostics and verify completion

`hierarchy_diagnostic` describes current files; it never grants write scope.
Record shapes, kinds, and detection rules are in the
[scanner contract](scanner.md#hierarchy-diagnostics); this section owns the
actions.

- `placement_gaps`: recompute included entries' complete unions; preserve
  out-of-scope findings.
- `unresolved_parents`: a real Wiki file outranks an alias even when unparsed.
  A legacy vault-root or previous-layout MOC (`legacy-moc`) is never a parent
  and cannot stand in for a missing discipline root, and neither is an
  `unexpected-moc` target. Preserve uncertain targets; fix relationships only inside
  the authorized closure.
- `parent_state_findings`: roots have empty parents, misc members point only
  to `[[misc]]`, and a `moc-parent` is replaced by the discipline root or the
  nearest Wiki ancestor. Missing roots require the
  [root prerequisite](#establish-discipline-roots) above, never a fabricated
  hierarchy edge.
- `unlinked_children`: [link each parent down](#populate-parents).
- `moc_inventory_findings` and `legacy_moc_states` establish path ownership.
  Preserve and report unsafe or noncanonical paths, duplicates, legacy MOCs,
  unknown MOC files, and inactive canonical MOCs; they stay outside generated
  ownership and never authorize a move, deletion, competing MOC, or scope
  expansion. The one move is the previous-layout migration above. Whole-note
  ownership applies only after a recognized discipline or misc pathname has a
  unique safe owner.
- `moc_file_states`: missing or empty active files can be initialized, and
  readable recognized files can be regenerated completely. `unreadable`,
  including unsafe filesystem ownership, blocks the connected closure.
- `moc_consistency_findings` cover the whole file. Regeneration emits only the
  outline; no comment, footer, prose, heading, or frontmatter delimits a
  separately owned region.
- `self_parented` and `parent_cycles` identify edges to recompute from the
  derived hierarchy. Their absence alone does not prove complete placement.
- Outside the previous-layout migration above, Task 3 never rewrites entry
  links with `item10/moc` findings (in `problems`). Publishing a missing
  canonical MOC for an active in-closure discipline lets an explicit
  `[[MOCs/<discipline>-moc]]` link resolve on the rescan; every other such
  link stays preserved and reported, never retargeted to another MOC or a
  same-named Wiki entry.

After a completed closure, every included entry with valid membership has no placement gap,
unresolved/invalid parent, self-parent, or cycle. Every active included MOC is
readable (or empty misc with zero members), contains only the complete generated
outline and has no consistency
finding. Each included entry's parents exactly
match its nearest linked Wiki ancestors; discipline roots alone have `parents: []`. No included parent remains in `unlinked_children`, and the final scan's `problems` holds no fixable finding on a file Task 3 wrote that the pre-Task-3 scan lacked. Re-scan to verify these conditions. After a
full-vault pass they hold for all active disciplines, misc, and requested entries;
inactive discipline MOCs, legacy MOCs, and skipped closures remain explicitly
reported and preserved, not described as repaired.
Any remaining active in-closure finding requires re-deriving that same closure
before declaring completion.
