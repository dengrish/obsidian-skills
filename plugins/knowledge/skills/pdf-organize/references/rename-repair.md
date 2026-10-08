# Repairing a PDF's derived names and references

Read this before applying an organizer plan that moves derived files, rewrites
notes, or changes figure sidecars, and when verification fails. The
[organizer workflow](../SKILL.md#workflow) owns source selection, naming, and
authorization. This reference explains what its repair must preserve, not a
separate way to rename files.

## Establish the owned family

The helper's candidate family is the PDF, its same-stem
`Sources/Images/<stem>_fig*` images, an `Articles/` note whose origin
identifies this PDF, and the book's chapter folder with its chapters. Each
chapter has its own family. The rename plan moves only proven members and
repairs Markdown and Canvas references vault-wide; it never independently
renames unrelated notes or images.

- **Chapter folder.** A `Sources/PDFs/` folder named after the book, with
  or without `_src`, belongs to the family only when it holds at least one
  chapter PDF of this book. A topic folder that merely shares the name is
  never renamed. The folder's other files, such as an errata PDF or a
  reading plan, keep their names in the book's rename and move with it.
  The plan renames the folder in every link to one of them, and
  verification fails if a link still names the old folder.
- **Other representation.** When the book is split, its other copy (the
  same stem with or without `_src`) belongs to the family too, with its own
  figures and note, because both copies pair with one chapter set. Each copy
  keeps its own marker.

Resolve each blocker at its cause, then re-plan:

- **Investment records.** Records in vault-root `Investments/` stay
  unchanged, including when reached through a linked-folder alias. If one has
  a live dependency that the rename would change, the helper blocks the
  entire rename: keep the source's current name and location. The rename's
  reference repair never makes these historical records editable. Unrelated
  records and literal examples do not block.
- **Source note.** An `Articles/` note follows only when its origin
  identifies this PDF:
  - The origin is the note's first `sources:` item; legacy `source:` counts
    only when `sources:` is absent. Duplicate keys or a malformed `sources:`
    list never fall back to `source:`.
  - A bare `"[[Name.pdf]]"` origin identifies the PDF by its vault-unique
    basename. A folder-qualified origin (vault-relative, note-relative or
    unique shortest-suffix) must resolve to this PDF's actual location; one
    that names another folder never moves the note or changes its
    `published` date.
  - A foreign, missing, malformed, or unreadable origin establishes no
    ownership, and the note stays put. Publisher URLs remain external
    sources.
  - The only metadata-free exception is a legacy note whose entire body is
    an embed of this PDF.
  - An unquoted source wikilink naming this PDF is a blocker: quote the
    complete wikilink scalar and re-plan.
- **Figures.** A `_fig*` candidate moves only when the figure manifest
  records its exact current digest; any other candidate blocks the rename. A
  same-stem clipping, a deleted note, or no visible rival does not prove
  ownership. The label test decides who made an unrecorded crop under the
  current or target stem, and so whether the PDF may take that stem:
  - *A legacy figure-extract crop* has a label figure-extract writes (a
    caption label ending in a digit, or a legacy lowercase panel letter
    after one;
    [§8b](../../../shared/CONVENTIONS.md#8b-the-producer-conventions)) and
    matches its page, and no unrecorded crop under that stem has an
    uppercase panel letter. Record it under the current stem of the PDF it
    is named after, such as a chapter of a split book (the blocker prints
    one command per PDF), with
    `python3 '<plugin>/skills/figure-extract/scripts/batch_extract.py' --src '<current PDF>' --out '<vault>/Sources/Images' --adopt-legacy '<current stem>:<label>'`
    (repeat the option per figure; the PDF needs no `--allow-unorganized`
    for this), then re-plan the rename.
  - *Another tool's crop of this PDF* matches a figure on these pages, as
    each of a slide deck's crops does (one with an uppercase panel letter,
    such as `_fig_1A_B`, and every crop beside it); a note outside
    `Sources/` that embeds it, such as a `Slides/` deck, supports this. It shares the stem, current or target: the PDF
    still takes its natural name.
  - *Any other image*, such as a clipping-clean image or an image these
    pages do not show, sends a PDF that would keep that stem to a
    distinguishing abbreviated title by the
    [target-stem rule](../SKILL.md#3-check-references-and-prepare-the-complete-rename-plan).

  A crop of either of the last two kinds is not this PDF's figure-extract
  output, whatever it shows: pass `--foreign-image '<name>'` for it (repeat
  the option per file), and it keeps its name outside the family. An
  unconfirmed crop stays a blocker. Never infer ownership from the `_fig`
  name, delete a conflicting occupant, or reset the manifest to make the
  plan pass.
- **Aliases and symlinks.** Vault containment follows the logical path: a PDF
  beneath a linked source directory is in scope, but the link target's
  physical path is not. A case or normalization spelling counts only when
  filesystem identity proves it is the selected vault. A PDF reachable
  through several directory aliases, or a leaf PDF symlink to a moved source,
  blocks the rename: reconcile the reported aliases to one source path. Any
  leaf `.md` or `.canvas` symlink in the vault blocks the reference scan,
  because reading or rewriting it could reach a file outside the vault:
  reconcile it, or replace it with a regular in-scope file.
- **Link repair is the helper's job.** It repairs wikilinks, inline and
  reference-style Markdown links (also inside a callout), and HTML
  `src`/`href` values. It resolves folder-qualified links against the keyed
  file's actual location and handles extensionless links, percent-encoded
  paths, case and Unicode variants, and symlinked directories. Code, escaped
  wikilinks, and closed HTML/Obsidian comments are literal evidence, and their
  bytes are preserved; an unclosed comment opener does not hide a dependency.
  This applies vault-wide, including `Reviews/` logs. Outside that literal
  evidence, a rename rewrites the whole old filename in every link. It also
  rewrites the filename in plain text, so the mention follows the file, when
  the name is canonical (a PDF or its figure) or when a plain-text folder path
  leads to it from the vault root or from the note, as in
  `Sources/PDFs/download.pdf`. When the file changes folder (filing, or a
  renamed chapter folder), that path becomes its new vault path. Any other
  name in plain text, such as a download's bare `main.pdf`, can be ordinary
  prose: it is not a reference and stays unchanged. All other issue text stays unchanged. Never
  replace this with whole-body substring matching.
- **Canvas boards.** In an Obsidian `.canvas` board, a file card or a group
  background holds the file's full vault path, so it follows every move,
  including filing under the same basename. A text card is Markdown and is
  repaired like a note. Labels, edges and link cards stay unchanged, and so
  does every other byte of the board. A canvas that cannot be read as UTF-8
  JSON blocks the rename when it may cite a changed name; otherwise it is
  listed as not read. After an apply, the CLI also verifies that no canvas
  card still points at an old path.

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
- **Moved with the chapter folder, names unchanged** lists the folder's
  other files. Report them as moved, not renamed.
- **Not read, and cite nothing this rename changes** lists notes that could
  not be read as UTF-8, and canvases that could not be read as UTF-8 JSON.
  They remain untouched and must be reported as unread, not verified clean.
  An unreadable note or canvas that cites this rename is a blocker.
- **Figure sidecar updates** covers only the default figure ownership,
  review and pending Extended Data files in `Sources/Images/`; their changes
  are planned, applied, and rolled back with the rename. A custom figure-extract `--review-file` ledger
  is never updated and must not be hand-edited: report any known one as still
  holding old-stem marks.
- **Publication-date updates** gives the old and new `published` values of
  owned paper-summary notes when the canonical source year changes. The
  note's source link and this value are one staged rewrite and share the same
  stale-file guard and rollback. A target `nd` uses `null`. A valid date
  already in the numeric target year is the document's own date and is kept
  unchanged, so it is not listed. A null or a date from another year becomes
  `<year>-01-01`, which the
  [run report](../SKILL.md#6-report-outcomes-and-remaining-work) calls
  padding. Only the document's own evidence, through a paper-summarize
  correction, may supply a more precise date, never the old note's
  month/day. Missing, duplicate, quoted, invalid, multiline, or
  contradictory date metadata is a blocker; correct that field from the
  document before re-planning. A frontmatter fence shape also blocks:
  a UTF-8 byte-order mark, blank lines or indentation before the opening
  `---`, or trailing spaces or tabs on either fence. The blocker names the
  cause; fix those bytes in the note itself, since the date is not at fault.
  Notes that merely cite the PDF never receive this metadata repair.

On a failed apply or verification, follow
[SKILL step 4](../SKILL.md#4-apply-then-verify-the-whole-family): report the
remaining references and the rollback result, and never hand-patch them with
a global replacement, since an old stem can be part of the new stem.
