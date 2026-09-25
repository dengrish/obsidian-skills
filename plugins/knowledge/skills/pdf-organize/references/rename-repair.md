# Repairing a PDF's derived names and references

Read this before applying an organizer plan that moves derived files, rewrites
notes, or changes figure sidecars; also use it for API calls and failed
verification. The [organizer workflow](../SKILL.md#workflow) owns source
selection, naming, and authorization. This reference explains what its repair
must preserve, not a separate way to rename files.

## Establish the owned family

`keyed_files` collects the candidate family: the PDF, its same-stem
`Sources/Images/<stem>_fig*` images, an `Articles/` note whose origin
identifies this PDF, and any split-book folder with its chapters. Each
chapter has its own family. A basename shared with another vault file blocks
the plan as
[SKILL step 3](../SKILL.md#3-check-references-and-prepare-the-complete-rename-plan)
describes. The rename plan moves only proven members and
repairs Markdown references vault-wide; it never independently renames
unrelated notes or images. Resolve each blocker at its cause, then re-plan:

- **Investment records.** Records in vault-root `Investments/` stay
  unchanged, including when reached through a linked-folder alias. If one has
  a live dependency that the rename would change, the helper blocks the
  entire rename: keep the source's current name and location. General
  authorization to repair source references does not make these historical
  records editable. Unrelated records and literal examples do not block.
- **Source note.** An `Articles/` note follows only when its first `sources:`
  item identifies this PDF; legacy `source:` counts only when `sources:` is
  absent. A bare `"[[Name.pdf]]"` origin identifies it by its vault-unique
  basename. A folder-qualified origin (vault-relative, note-relative or
  unique shortest-suffix) must resolve to this PDF's actual location; one
  that names another folder never moves the note or changes its `published`
  date. A foreign, missing, malformed, or unreadable origin establishes no
  ownership, and the note stays put; duplicate keys or a malformed `sources:`
  list never fall back to `source:`. Publisher URLs remain external sources.
  The only metadata-free exception is a legacy note whose entire body is an
  embed of this PDF. An unquoted source wikilink naming this PDF is a
  blocker: quote the complete wikilink scalar and re-plan. The helper reads
  quoted or escaped keys and values, flow and indentless lists, and comments,
  but producers still write the documented block-list form.
- **Figures.** A `_fig*` candidate moves only when the figure manifest
  records its exact current digest; any other candidate blocks the rename. A
  same-stem clipping, a deleted note, or no visible rival does not prove
  ownership. Adopt an unrecorded legacy image through figure-extract's
  explicit legacy-adoption procedure against the named PDF. Never infer
  ownership from the `_fig` name, delete a conflicting occupant, or reset the
  manifest to make the plan pass.
- **Aliases and symlinks.** Vault containment follows the logical path: a PDF
  beneath a linked source directory is in scope, but the link target's
  physical path is not. A case or normalization spelling counts only when
  filesystem identity proves it is the selected vault. A PDF reachable
  through several directory aliases, or a leaf PDF symlink to a moved source,
  blocks the rename: reconcile the reported aliases to one source path. Any
  leaf `.md` symlink in the vault blocks the reference scan, because reading
  or rewriting it could reach a file outside the vault: reconcile it, or
  replace it with a regular in-scope note.
- **Link repair is the helper's job.** It resolves folder-qualified links
  against the keyed file's actual location and handles extensionless links,
  case and Unicode variants, and symlinked directories. It decodes local
  Markdown URL escapes once; a literal percent sequence in a wikilink stays
  literal. Code, escaped wikilinks, and closed HTML/Obsidian comments are
  literal evidence, and their bytes are preserved; an unclosed comment opener
  does not hide a dependency. Frontmatter is read separately, so a comment
  delimiter in metadata hides neither the origin nor body links. This applies
  vault-wide, including `Reviews/` logs: an authorized rename repairs their
  navigation links without changing issue claims. Never replace it with
  whole-body substring matching.

The canonical contracts are
[source identity (§1a)](../../../shared/CONVENTIONS.md#1a-source-file-names-and-why-pdf-organize-runs-first),
[source references (§7)](../../../shared/CONVENTIONS.md#7-source-references), and
[figure ownership (§8)](../../../shared/CONVENTIONS.md#8-figure-naming-and-sourcesimages).
Read the relevant section when a plan involves that kind of derived file.

## Review the plan before writing

The CLI's `check` lists citing paths and names. `rename` without `--apply`
shows moves, note rewrites, sidecar updates, unreadable notes, and blockers.
Apply only under the
[organizer workflow's authorization rule](../SKILL.md#3-check-references-and-prepare-the-complete-rename-plan).

`rename_all` returns `(moves, edits, blockers)` and writes nothing while
`blockers` is nonempty. Resolve every blocker: occupied destinations anywhere
in the vault, collisions that differ only in case or Unicode normalization,
overlong derived names, extension mismatches, unsafe paths, permissions, and
malformed or conflicting sidecars. Do not force a partial family through.

`edits` maps note paths to their new text. Three associated fields are separate:

- `edits.unreadable` lists notes that could not be read as UTF-8 and that do
  not cite a name being changed. They remain untouched and must be reported
  as unread, not verified clean. An unreadable note that cites this rename
  is a blocker.
- `edits.sidecars` tracks only the default figure ownership and review files
  in `Sources/Images/`; their changes are planned, applied, and rolled back
  with the rename. The organizer never reads or updates a custom review
  ledger selected with figure-extract's `--review-file`: its marks keep the
  old stems and no longer match renamed figures. Do not hand-edit it as part
  of the rename; name any known custom ledger in the report as still holding
  old-stem marks.
- `edits.published_updates` records `(old, new)` publication-date scalars for
  owned paper-summary notes when the canonical source year changes. The note's
  source link and this field are one staged rewrite and share the same stale-file
  guard and rollback. A target `nd` uses `null`; a numeric target retains a
  valid month/day, or uses `01-01` when the old value was null. Missing,
  duplicate, quoted, invalid, multiline, or contradictory date metadata is a
  blocker, as is a month/day that is invalid in the target year. Correct the
  metadata from the document before re-planning; never discard date components
  to force the rename through. Notes that merely cite the PDF never receive
  this metadata repair.

## API calls and verification

Prefer the CLI unless a Python caller needs the API. Import the shipped
implementation; use the same interpreter selected in runtime setup:

```python
import os, sys
sys.path.insert(0, "<skill>/scripts")
from organize import keyed_dirs, keyed_files, obsolete_names, references, rename_all

keyed = keyed_files(vault, path)
old_dirs = keyed_dirs(vault, keyed)
old_folders = {name for p, name in keyed.items()
               if os.path.isdir(p) and not os.path.islink(p)}
refs = references(vault, set(keyed.values()), dirs=old_dirs,
                  directory_names=old_folders)
moves, edits, blockers = rename_all(
    vault, path, new_basename, dest=dest, apply=False
)
```

Pass `dirs` and `directory_names` to both reference checks, exactly as the
CLI does. Without `dirs` the permissive API may count a link to a different
folder's same-named note as a reference to this family; without
`directory_names` a chapter folder's name, which is a container rather than a
cited file, counts as a reference. Compute both **before** the move,
including when filing changes the PDF's directory; recomputed afterwards, a
correct rename reads as incomplete. Do not pass a prebuilt `vault_names` map
to the rename API; it scans afresh on each plan. Only the splitting API
accepts that map.

After all blockers are resolved and any required authorization is established:

```python
moves, edits, blockers = rename_all(
    vault, path, new_basename, dest=dest, apply=True
)
if blockers:
    raise RuntimeError("Rename blocked: " + "; ".join(blockers))
left = references(vault, obsolete_names(moves), dirs=old_dirs,
                  directory_names=old_folders)
if left:
    raise RuntimeError("Incomplete rename; report remaining references: " + repr(left))
```

Verify **all obsolete names**, not just the old PDF basename: an image embed
or source-note link can otherwise remain broken. `obsolete_names(moves)`
excludes basenames preserved during filing and changes of case alone. The
CLI performs this verification automatically.

On a failed verification, stop and report the remaining references. Do not
hand-patch them with global replacement: an old stem can be part of the new
stem, so a second replacement may corrupt already-correct links. If applying
raises `RenameFailed`, report whether rollback completed (`rolled_back`) and
any state or recovery paths the exception names, then handle it as in
[SKILL step 4](../SKILL.md#4-apply-then-verify-the-whole-family).
