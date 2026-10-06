# Repairing a PDF's derived names and references

Read this before applying an organizer plan that moves derived files, rewrites
notes, or changes figure sidecars, and when verification fails. The
[organizer workflow](../SKILL.md#workflow) owns source selection, naming, and
authorization. This reference explains what its repair must preserve, not a
separate way to rename files.

## Establish the owned family

The helper's candidate family is the PDF, its same-stem
`Sources/Images/<stem>_fig*` images, an `Articles/` note whose origin
identifies this PDF, and any split-book folder with its chapters. Each
chapter has its own family. The rename plan moves only proven members and
repairs Markdown references vault-wide; it never independently renames
unrelated notes or images. Resolve each blocker at its cause, then re-plan:

- **Investment records.** Records in vault-root `Investments/` stay
  unchanged, including when reached through a linked-folder alias. If one has
  a live dependency that the rename would change, the helper blocks the
  entire rename: keep the source's current name and location. The rename's
  reference repair never makes these historical records editable. Unrelated
  records and literal examples do not block.
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
  blocker: quote the complete wikilink scalar and re-plan.
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
  case and Unicode variants, and symlinked directories. Code, escaped
  wikilinks, and closed HTML/Obsidian comments are literal evidence, and their
  bytes are preserved; an unclosed comment opener does not hide a dependency.
  This applies vault-wide, including `Reviews/` logs: a rename rewrites each
  whole old filename outside that literal evidence, so links and filename
  mentions follow the file, and leaves all other issue text unchanged. Never
  replace it with whole-body substring matching.

The canonical contracts are
[source identity (§1a)](../../../shared/CONVENTIONS.md#1a-source-file-names-and-why-pdf-organize-runs-first),
[source references (§7)](../../../shared/CONVENTIONS.md#7-source-references), and
[figure ownership (§8)](../../../shared/CONVENTIONS.md#8-figure-naming-and-sourcesimages).
Read the relevant section when a plan involves that kind of derived file.

## Review the plan before writing

The CLI's `check` lists citing paths and names. `rename` without `--apply`
prints the moves and the sections below. The request that leads to the
rename or filing move authorizes the repair under the
[organizer workflow](../SKILL.md#3-check-references-and-prepare-the-complete-rename-plan);
apply once nothing below blocks it.

- **BLOCKED — nothing was written.** Resolve every blocker: occupied
  destinations anywhere in the vault, target-stem figures or `Articles/` notes
  outside the family, for the PDF or any renamed chapter (see
  [SKILL step 3](../SKILL.md#3-check-references-and-prepare-the-complete-rename-plan)),
  collisions that differ only in case or Unicode normalization, overlong
  derived names, extension mismatches, unsafe paths, permissions, and
  malformed or conflicting sidecars. Do not force a partial family through.
- **Not read, and cite nothing this rename changes** lists notes that could
  not be read as UTF-8. They remain untouched and must be reported as unread,
  not verified clean. An unreadable note that cites this rename is a blocker.
- **Figure sidecar updates** covers only the default figure ownership and
  review files in `Sources/Images/`; their changes are planned, applied, and
  rolled back with the rename. A custom figure-extract `--review-file` ledger
  is never updated and must not be hand-edited: report any known one as still
  holding old-stem marks.
- **Publication-date updates** gives the old and new `published` values of
  owned paper-summary notes when the canonical source year changes. The
  note's source link and this value are one staged rewrite and share the same
  stale-file guard and rollback. A target `nd` uses `null`. A valid date
  already in the numeric target year is the document's own date and is kept
  unchanged, so it is not listed. A null or a date from another year becomes
  `<year>-01-01`, which you report as padding. Only the document's own
  evidence, through a paper-summarize correction, may supply a more precise
  date, never the old note's month/day. Missing, duplicate, quoted, invalid,
  multiline, or contradictory date metadata is a blocker; correct that field
  from the document before re-planning. A frontmatter fence shape also blocks:
  a UTF-8 byte-order mark, blank lines or indentation before the opening
  `---`, or trailing spaces or tabs on either fence. The blocker names the
  cause; fix those bytes in the note itself, since the date is not at fault.
  Notes that merely cite the PDF never receive this metadata repair.

On a failed apply or verification, follow
[SKILL step 4](../SKILL.md#4-apply-then-verify-the-whole-family): report the
remaining references and the rollback result, and never hand-patch them with
a global replacement, since an old stem can be part of the new stem.
