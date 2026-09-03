# Repairing a PDF's derived names and references

Read this before applying an organizer plan that moves derived files, rewrites
notes, or changes figure sidecars; also use it for API calls and failed
verification. The [organizer workflow](../SKILL.md#workflow) owns source
selection, naming, and authorization. This reference explains what its repair
must preserve, not a separate way to rename files.

## Establish the owned family

`keyed_files` discovers the PDF, its owned figures and `Articles/` note, and
any split-book folder and chapters. Each chapter has its own derived family.
The rename carries that family and repairs Markdown references vault-wide;
it does not independently rename unrelated notes or images.

- An `Articles/` note follows only when its first `sources:` item identifies
  this PDF. Legacy `source:` is a fallback only when the current field is
  absent. Quoted YAML escapes, comments, and indentless lists are supported;
  a foreign, missing, malformed, or unreadable origin does not establish
  ownership. The sole metadata-free legacy exception is a body consisting
  only of an embed of this PDF. Publisher URLs remain external sources.
- Figure candidates follow the consumer convention
  `[pdf_stem]_fig*`, including older accepted names, but **every image moves only
  when the figure manifest records its exact current digest**. A same-stem
  clipping, a deleted note, or no visible rival does not prove PDF ownership.
  An unrecorded legacy image must first pass pdf-figure-extractor's explicit
  legacy-adoption procedure against the named PDF. Do not infer ownership from
  the `_fig` name, delete a conflicting occupant, or reset a manifest to make
  the plan pass.
- Folder-qualified links are resolved against the keyed file's actual
  location. Extensionless note links, case variants, Unicode normalization,
  and symlinked **directories** are handled by the helper. Vault containment
  follows the logical path: a PDF reached beneath a linked source directory
  is in scope, while the link target's direct physical path is not. A
  case/normalization spelling is accepted only when filesystem identity proves
  it is the selected vault. A leaf `.md` symlink is a blocker: following it
  for a rewrite could mutate an external target outside the selected vault, so
  reconcile the link or establish a regular in-scope note before retrying.
  Local Markdown URL escapes
  are decoded once; a literal percent sequence in a wikilink stays literal.
  Do not replace this with whole-body substring matching.

The canonical contracts are
[source identity (§1a)](../../../shared/CONVENTIONS.md#1a-source-file-names-and-why-pdf-organizer-runs-first),
[source references (§7)](../../../shared/CONVENTIONS.md#7-source-references), and
[figure ownership (§8)](../../../shared/CONVENTIONS.md#8-figure-naming-and-sourcesimages).
Read the relevant section when a plan involves that kind of derived file.

## Review the plan before writing

The CLI's `check` lists citing paths and names. `rename` without `--apply`
shows moves, note rewrites, sidecar updates, unreadable notes, and blockers.
When the source family is referenced, apply only after the user has
authorized this repair; an authorization already given need not be repeated.
Prepare the full read-only plan before requesting any missing approval.

`rename_all` returns `(moves, edits, blockers)` and writes nothing while
`blockers` is nonempty. Resolve every blocker: occupied destinations anywhere
in the vault, collisions that differ only in case or Unicode normalization,
overlong derived names, extension mismatches, unsafe paths, permissions, and
malformed or conflicting sidecars. Do not force a partial family through.

`edits` maps note paths to their new text. Two associated fields are separate:

- `edits.unreadable` lists notes that could not be read as UTF-8 and that do
  not cite a name being changed. They remain untouched and must be reported
  as unread, not verified clean. An unreadable note that cites this rename
  is a blocker.
- `edits.sidecars` tracks the default figure ownership and review files in
  `Sources/Images/`. Their changes are planned and applied or rolled back
  with the rename. A custom review ledger selected with `--review-file` is
  outside this default lookup: include it explicitly in the review and
  report any marks that could not be carried before claiming completeness.

Filing moves only the source PDF to `Sources/PDFs/`. Figures remain in
`Sources/Images/`, the source note in `Articles/`, and a chapter family under
`Sources/PDFs/`, each renamed in its own home.

## API calls and verification

Prefer the CLI unless a Python caller needs the API. Import the shipped
implementation; use the same interpreter selected in runtime setup:

```python
import sys
sys.path.insert(0, "<skill>/scripts")
from organize import keyed_dirs, keyed_files, obsolete_names, references, rename_all

keyed = keyed_files(vault, path)
old_dirs = keyed_dirs(vault, keyed)
refs = references(vault, set(keyed.values()), dirs=old_dirs)
moves, edits, blockers = rename_all(
    vault, path, new_basename, dest=dest, apply=False
)
```

Pass `dirs` to both reference checks. Without it the permissive API may count
a link to a different folder's same-named note as a reference to this family.
Keep `old_dirs` from **before** the move, including when filing changes the
PDF's directory. Do not pass a prebuilt `vault_names` map to the rename API;
it scans afresh on each plan. Only the splitting API accepts that map.

After all blockers are resolved and any required authorization is established:

```python
moves, edits, blockers = rename_all(
    vault, path, new_basename, dest=dest, apply=True
)
if blockers:
    raise RuntimeError("Rename blocked: " + "; ".join(blockers))
left = references(vault, obsolete_names(moves), dirs=old_dirs)
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
raises `RenameFailed`, report whether rollback completed and any remaining
state named in the exception. Do not claim that a failed operation succeeded
or delete files to conceal a partial result. A file changed after planning is
new input, so the apply refuses to overwrite it. Re-plan from that version. If
a second writer claimed a name during publication, the exception may name
private recovery paths holding displaced versions; retain every file until
their contents are reconciled.
