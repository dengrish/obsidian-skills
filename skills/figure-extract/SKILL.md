---
name: figure-extract
description: >
  Extract whole figures from one PDF or a folder of PDFs in an Obsidian vault
  into cropped PNGs, with captions left out and filenames tied to the source
  PDF. Use for requests such as "extract figures from my PDFs" or "rip the
  figures out of this paper", including populating Sources/Images/ from
  Sources/PDFs/. A reading note uses paper-summarize and wiki entries use
  wiki-build; renaming, filing or chapter splitting uses pdf-organize.
---

# Figure Extract

## Setup and scope

Read [shared/RUNTIME.md](../../shared/RUNTIME.md) once per task for vault
selection, script paths, Python dependencies, and host tools. Use one
interpreter with the plugin's `requirements.txt` installed for all commands.
Before extracting, run `python3 '<plugin>/shared/scripts/check_parsers.py'`
with it under the
[parser-check rule](../../shared/RUNTIME.md#only-for-pdf-and-image-workflows);
while it fails, extract nothing. The shipped scripts are the implementation;
do not copy their caption detection or crop logic into a separate script.

The deliverable is **whole-figure PNGs**, not PDF renames, summaries, or wiki
entries. `paper-summarize` owns document explanations and reading notes,
`pdf-organize` owns source naming and chapter splitting, `wiki-build` owns
wiki entries built from a source (new or enriched), `wiki-lint` owns
maintenance of existing entries, and `clipping-clean` owns Web Clipper
captures. An unspecified “process this PDF” request needs a stated
deliverable before selecting a workflow.

Normally read `Sources/PDFs/` recursively and write to the **flat**, shared
`Sources/Images/` folder. Use the paths the task establishes; do not infer an
external PDF should be imported into a vault. This skill does not split
lettered panels. Older panel PNGs remain valid content and must not be deleted
or renamed as cleanup.

## Workflow

### 1. Confirm source identity and extraction scope

Run `pdf-organize` first if the sources do not have canonical filenames;
Inbox PDFs need organizing and filing before ordinary vault extraction.
Every crop uses the source's exact on-disk stem, so a later rename requires
the organizer's guarded repair. The batch helper refuses unorganized names.
Use `--allow-unorganized` only for a deliberate one-off exception and explain
that downstream source identity will depend on the current name. The shared
rule is [conventions §1a](../../shared/CONVENTIONS.md#1a-source-file-names-and-why-pdf-organize-runs-first).

Folder sweeps skip [feed-owned attachments](../../shared/CONVENTIONS.md#1-vault-folder-layout)
and list them without failing the run. If the user names one, keep its name,
use the `--allow-unorganized` exception, and report it. Never rename a
collector-owned file or treat its photo attachments as extractor-owned
figures.

`--src` takes one PDF or a folder scanned recursively, following directory
symlinks; an unreadable subtree or a symlink loop blocks the run. When `--out`
is the vault's canonical `Sources/Images/`, each selected PDF's basename,
including case and Unicode variants, must have exactly one owner across the
whole vault, even for a single named file, and nothing is written if the vault
cannot be inventoried completely. An external PDF therefore has no owner there
and is refused: use an external `--out` for a one-off, or, when the user wants
it in the vault, copy it into `Inbox/` with their approval for `pdf-organize`
to file, then extract from the filed path. A refused PDF writes and adopts
nothing, even with `--overwrite`; other PDFs continue and the run exits
nonzero. When another vault file shares a PDF basename, report both paths and
give the user the
[shared-basename remedy](../../shared/CONVENTIONS.md#1a-source-file-names-and-why-pdf-organize-runs-first).

**In a recursive run containing both a book and its chapters, extract the
chapters and skip the whole book.** The skip is scoped to this run, not a
standing fact about the vault. Naming the book PDF directly selects it;
`--include-split-books` deliberately selects both representations and may
produce duplicate figures. Existing whole-book figures are reported, never
automatically deleted.

### 2. Extract with the shipped batch command

```bash
python3 '<skill>/scripts/batch_extract.py' \
    --src '<vault>/Sources/PDFs' \
    --out '<vault>/Sources/Images'
```

Replace `--src` with the full PDF path for one file. Add `--dry-run` for a
preview that writes **nothing**: no PNGs, review marks, manifest, or output
directory. For less common options, use the script's `--help`.

Crops recorded in `.figure-manifest.tsv` with matching bytes are skipped;
`--overwrite` re-crops them unless a review mark protects them. Limit a batch
`--overwrite` to the affected PDFs with `--src` unless the user asked for a
folder-wide refresh: every re-cropped PNG needs visual review again. Any other
occupant of a figure's slot is never replaced, even with `--overwrite`, and a
malformed or symlinked manifest blocks the run; never delete sidecars or
images to force a run. For occupied names (including every crop in a
`Sources/Images/` without a manifest), legacy adoption, sidecar failures, or a
source PDF revised at the same path (a verified skip proves ownership, not
freshness), follow
[ownership, adoption and review records](references/review-and-repair.md#ownership-legacy-adoption-and-review-records).

Extract a PDF alone with `--ed-prefix ED` when `<stem>_fig_ED*` files exist,
or when no `<stem>_fig*` crop exists yet and its captions number Extended Data
figures alongside its main figures; the default folds Extended Data into `S`
(`SI` stays distinct). After a default run, switch only a PDF whose summary
prints an `--ed-prefix ED` rerun, following [Extended Data and Supplementary figures](references/review-and-repair.md#extended-data-and-supplementary-figures).
Use `--keep-frame` to keep a publisher's surrounding frame, which is otherwise
cropped away.

Large folder summaries can exceed a host's displayed output: capture stdout
and stderr into unique files under the run's `<scratch>`, keep the exit status,
and read both files completely in slices before the next step.

Output is `[pdf_stem]_fig_<label>.png`, with the exact PDF stem including
`_src` and disambiguators. The label comes from the caption, **not extraction
order**: Figure 7 becomes `_fig_7.png`, Figure 1.2 becomes `_fig_1-2.png`, and
Figure S1 becomes `_fig_S1.png`. Follow
[conventions §8](../../shared/CONVENTIONS.md#8-figure-naming-and-sourcesimages);
existing consumer matching remains `[source_stem]_fig*`, including older
accepted names. Do not tighten it or rename legacy output to match new examples.

### 3. Inspect the summary and verify crops

**Read the complete summary before reporting success.** Check written and
verified-skipped counts separately from refused PDFs, blank crops, failed
writes, occupied names, and PDFs that could not be read. A detected caption is
not proof that an image reached disk.

Use [review and repair](references/review-and-repair.md) for any flagged crop,
caption collision, partial detection, missing figures, duplicate pixels, or
ownership failure. A “PARTIAL” result may be a real missed figure or an
unresolved external reference. Duplicates are review findings, not authority
to delete files.

**Visually review the output.** View every PNG this run wrote or replaced
(listed under each PDF as `wrote:`); verified skips need no re-check. Compare
these with their rendered pages: every flagged crop, every crop from a
multi-column page, and any PNG showing caption text, neighboring content or a
cut-off edge (a crop can hold its neighbor's chart without a warning). If
viewing every new PNG is impractical, as in a large folder sweep, view at
least the flagged and multi-column crops and report the rest as not visually
verified. If image viewing is unavailable, report that limit and leave
uncertain crops unresolved.

Caption text in a crop must be removed before a note embeds it. Repair a bad
crop with the reference's [explicit repair procedure](references/review-and-repair.md#set-and-verify-an-explicit-crop)
for coordinate units, naming exceptions, scratch copies, review marks and
cleanup. Record `--mark-reviewed '<stem>:<fig>'` for every explicitly repaired
crop, flagged or not, only after viewing it: the mark verifies nothing,
silences its warnings and protects the crop from a later batch `--overwrite`.
Preserve every recovery path named by a failed write.

### 4. Report completed and unresolved work

Give the source scope, output folder, figures written, verified skips, and any
legacy adoptions. Name skipped whole books and feed-owned attachments,
refused sources, conflicting occupants, failed PDFs, remaining warnings, and
explicit crop repairs. State what visual review was completed and any review
marks recorded. After a nonzero run, report the PDFs that succeeded without
calling the whole request complete. Preserve originals, legacy panels, and all
unrelated images.

At closeout, read the [shared suggestion-log rules](../../shared/SUGGESTIONS.md)
and apply them to `Reviews/figure-extract-suggestions.md` and to the logs of
producers whose outputs this run consumed.
