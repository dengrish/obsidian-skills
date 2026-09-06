# Hierarchy — `parents:` and MOCs (Task 3)

Read this before creating or updating MOCs, recomputing `parents:`, or acting
on `hierarchy_diagnostic`. A MOC is a **fully generated navigation note**: discipline trees live at
`MOCs/<discipline-slug>.md`, and entries tagged only `#misc` have a flat list in
`MOCs/misc.md`. Its complete content is a bullet outline derived from the
current Wiki entries. It contains no ownership
comments, H1, frontmatter, or separate prose sections, except the final
[skill-provenance footer](../../../shared/PROVENANCE.md). That metadata is not
part of the navigation tree. A footer-only misc MOC is an empty outline.

`parents:` and the MOCs are **two renderings of one hierarchy**. Derive one
tree per included specific discipline, root it at `[[MOCs/<discipline-slug>]]`, and
use `[[MOCs/misc]]` as the parent of every misc member. Render complete MOCs
and parent unions from this one placement plan. A MOC's
pathname is deterministic; choosing a useful concept hierarchy still requires
reading the entries. Nothing self-parents.

## Scope closure

Task 3 operates on a closed entry/MOC-group set because a multi-tagged entry
stores one union of parents, and a retag can move an entry between outputs.
Groups are the discipline enum values, including the fallback `misc`:

1. Seed entries with every requested entry and groups with every named MOC or
   discipline. Add each entry's current valid discipline tags, including
   `misc` only when the explicit tag list contains only `"#misc"`. Also retain
   its prior groups established before an authorized tag change, by existing generated MOC placements, or
   by its previous parent route to a MOC. Keep this evidence when refreshing
   the scan after QC; otherwise the old output could retain stale membership.
2. For every included group, include its MOC and every current member. Include
   existing entries whose prior placement in that MOC must be removed or
   changed, then add their current and prior groups.
3. Repeat until neither entries nor groups change. Multi-tagged entries close
   all their disciplines together. Retagging from or to `#misc` includes
   `misc` and the old/new disciplines. Refresh misc, active discipline outputs,
   and complete parent unions in that authorized closure. If a specific discipline
   loses its last member, preserve and report its inactive MOC under the
   rule below rather than rewriting it.

A selected-entry request does not authorize these additional writes. If it
does not already cover the closure, skip Task 3 for that connected set and
report the exact groups, entries, and MOCs needed. Proceed when the request
covers that set or explicitly authorizes expansion. Task 1 and Task 2 may
still run on the narrower entry set. Never write a partial MOC or only part
of an entry's parent union.

Misc membership requires a structurally valid, nonempty tag list containing
only `"#misc"`. Entries with blank `tags:` or `tags: []` belong in the QC
repair worklist, without implied placement: inspect the note's disciplinary home in Task 1 and assign supported
specific tags, or misc if none fits, then refresh the scan. Missing, malformed,
duplicate, mixed misc/specific, or uncertain tag data must not be blindly
replaced with the fallback. Structurally unparseable frontmatter cannot
establish membership, including duplicate keys hidden by quoted or escaped
spellings. Unrelated field-level QC findings do not disqualify an otherwise
valid misc tag. Preserve parents and report membership that cannot be
established safely; every entry follows the same source-backed schema.

A specific discipline with no members follows the inactive preservation rule below.
For misc, an authorized refresh keeps an existing file and clears its stale
generated list to empty when no members remain; an explicit request may also
create an empty `MOCs/misc.md`. Never delete it merely because it is empty.

## Derive the hierarchy

Build a tree only for an included specific discipline with at least one valid member;
never create all enum disciplines by default. Closure guarantees that the
included entries contain the complete set carrying each included tag.

- **Root at the discipline's MOC.** `#machine-learning` produces
  `MOCs/machine-learning.md`, linked as `[[MOCs/machine-learning]]`. The MOC is
  a navigation file outside `Wiki/`, never an entity or a self-linking bullet.
  No separate anchor entry is required.
- **An eponymous entry is a branch.** If the discipline's own slug exists
  as an entry carrying that discipline tag, make it the single top-level
  bullet and nest the field's branches beneath it. Its parent is still the MOC.
- **Use at most three bullet levels.** One level is enough for a small field.
  Group by the field's conceptual taxonomy, not entity `type:` or filenames.
  An established subdivision uses its existing entry; otherwise use its
  canonical name as an unlinked category term. Include a category only when
  it organizes at least one entry.
- **Place every entry carrying the tag.** Multi-tagged entries appear in
  every tagged discipline's MOC. Most entries have one home within a field;
  use multiple placements only for a real conceptual need, once per distinct
  nearest linked parent.
- **Keep a useful existing structure.** Read the previous MOC for continuity.
  Re-derive from the current entries and reorganize when changed coverage
  warrants it. Keep existing group names, category spellings, and ordering
  when they still fit. Once the outline follows this contract and matches the
  current entries, an unchanged hierarchy should yield byte-identical output.
  Correct existing defects, but do not reorganize for variety.
- **List entries tagged only `#misc` in misc.** This fallback tag must never
  coexist with a specific discipline tag. Its MOC is a flat
  list of exact `[[Wiki/<relative-entry-path>|Canonical Title]]` links, sorted
  by case/Unicode-normalized canonical title with the exact vault-relative
  path as a stable tie-breaker. Keep complete canonical labels, including
  qualifiers. Do not add category terms, nesting, or a special eponymous
  branch: even an entry named `misc` is an ordinary list member. Every member
  has exactly `[[MOCs/misc]]` as its parent.

## Populate `parents:`

For every included entry, collect the nearest linked ancestor above each
of its placements in every tagged discipline. Skip unlinked category terms.
An ancestor is either a broader Wiki entry or, for a top-level branch,
that discipline's MOC. For example, `clustering` → unlinked “Centroid methods”
→ `k-means` gives `k-means` the parent `[[clustering]]`; a top-level
`clustering` has the parent `[[MOCs/machine-learning]]`.

Take the complete union across trees. A multi-tagged entry can have a broader
entry in one field and a MOC parent in another. Recompute stale, self-linked,
or cyclic parents from the derived trees inside the authorized closure;
preserve and report fields outside it. Every entry tagged only `#misc` appears
once in `MOCs/misc.md` and receives `[[MOCs/misc]]`, with no other parent.

Write populated parents as a block list with one double-quoted wikilink per
line. `parents: []` is the producer handoff before hierarchy maintenance, not a
completed placement for a valid entry. Preserve unknown relationships until
their QC or scope blocker is resolved; never use a bare YAML-null key.
Discipline tags and unlinked categories are never parent targets.

**Use unambiguous paths.** Every MOC root link is extensionless and qualified:
`[[MOCs/<discipline-slug>]]` or `[[MOCs/misc]]`. Every generated tree entry link uses the exact
extensionless vault-relative Wiki path, such as
`[[Wiki/methods/k-means|K-means]]`, with the actual prefix under folder
overrides. Entry-valued parents may use a slug only when it identifies one
owner; qualify them when a MOC or another note shares the basename.

A recognized, readable canonical MOC (a discipline or misc) with sole filename ownership
outranks a Wiki alias; qualify an existing bare link to that MOC while keeping
its label and anchor. Unknown MOC names receive no automatic qualification:
preserve and report bare or explicit navigation as `item10/moc`. A real Wiki
file and MOC sharing a basename, including an unknown MOC name, make the bare
target ambiguous. Preserve it until the intended owner is established.

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
- `parent_state_findings` uses `misc-parent-mismatch` when an entry tagged only `#misc`
  has a populated parent field that is not exactly `MOCs/misc`. Empty parents
  already produce a misc placement gap. Recompute only where valid membership
  and the authorized closure establish the complete parent union.
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
  depth, canonical targets/labels, entry coverage, duplicate placements,
  wrong-group links, discipline eponymous-root shape, misc list order/flatness, and parent-union
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
match its nearest linked ancestors across its discipline MOCs or `[[MOCs/misc]]`. Re-scan to verify these conditions. After a
full-vault pass they hold for all active disciplines, misc, and requested entries;
inactive discipline MOCs and skipped closures remain explicitly reported and
preserved.
Any remaining active in-closure finding requires re-deriving that same closure
before declaring completion.
