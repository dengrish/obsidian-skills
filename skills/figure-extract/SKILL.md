---
name: figure-extract
description: >
  Extract the captioned, numbered figures of one PDF or a folder of PDFs in an
  Obsidian vault into whole-figure PNGs, with captions left out and filenames
  tied to the source PDF. Use for "extract figures from my PDFs", "rip the
  figures out of this paper", "save the charts in this PDF as images" or
  "re-crop Figure 3, it shows the caption", including populating
  Sources/Images/ from Sources/PDFs/. A reading note uses paper-summarize and
  wiki entries use wiki-build; renaming, filing or chapter splitting uses
  pdf-organize.
---

# Figure Extract

## Setup and scope

Read [shared/RUNTIME.md](../../shared/RUNTIME.md) once per task for vault
selection, script paths, Python dependencies, and host tools. Use one
interpreter with the plugin's `requirements.txt` installed for all commands.
Before extracting, run `python3 '<plugin>/shared/scripts/check_parsers.py'`
with that interpreter under the
[parser-check rule](../../shared/RUNTIME.md#only-for-pdf-and-image-workflows);
while it fails, extract nothing. The shipped scripts are the implementation;
do not copy their caption detection or crop logic into a separate script.

The deliverable is **whole-figure PNGs**, not PDF renames, summaries, or wiki
entries. It edits a note only to move links during an Extended Data switch
(step 2). An unspecified “process this PDF” request needs a stated
deliverable before selecting a workflow. Only captioned, numbered figures are
extracted; unnumbered exhibits are reported, not cropped. A request for one
specific figure runs the normal batch on that PDF (for a split book, on its
chapter folder; see step 1): it adds that PDF's missing crops and leaves
existing ones in place, and the report names the requested label's outcome.
A request to re-crop a bad figure uses the repair in
[step 3](#3-inspect-the-summary-and-verify-crops).

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
`--adopt-legacy` is not extraction: it
[records existing crops](references/review-and-repair.md#adopt-legacy-crops)
under the current name, which pdf-organize needs before renaming that PDF.
Use `--allow-unorganized` only for a deliberate one-off exception, including
an explicit user instruction not to rename or import, and explain that
downstream source identity will depend on the current name. Even then, a
stem that starts with `#` or has surrounding whitespace, a tab, a slash or a
backslash is refused, because the figure sidecars cannot record it. The shared
rule is [conventions §1a](../../shared/CONVENTIONS.md#1a-source-file-names-and-why-pdf-organize-runs-first).

Folder sweeps skip [feed-owned attachments](../../shared/CONVENTIONS.md#1c-feed-owned-attachments)
and list them without failing the run. If the user names one, keep its name,
use the `--allow-unorganized` exception, and report it. Never rename a
collector-owned file or treat its photo attachments as extractor-owned
figures.

**External PDFs.** With the vault's canonical `Sources/Images/` as `--out`,
an external PDF is refused unless it is a
[readable working copy](references/review-and-repair.md#readable-working-copies)
under one vault PDF's exact basename; otherwise use an external `--out` for a
one-off, or, when the user wants it in the vault, copy it into `Inbox/` with
their approval for `pdf-organize` to file, then extract from the filed path.
The batch checks only the name, so confirm the same document (identical
bytes, matching page count and first-page text, a working copy this run made
from that vault PDF, or the user's word) or stop and report both paths.

With canonical `Sources/Images/` output, each selected PDF's basename must
have exactly one owner across the whole vault, even for a single named file;
the [Stem collisions row](references/review-and-repair.md#interpret-the-diagnostics)
gives the scan scope and what a refusal blocks. When another vault file
shares a PDF basename, report both paths and give the user the
[shared-basename remedy](../../shared/CONVENTIONS.md#shared-pdf-basenames).

**In a recursive run containing both a book and its chapters, extract the
chapters and skip the whole book.** The skip is scoped to this run, not a
standing fact about the vault. A split book's figures are its chapters'
figures: a request that names a split book, or one of its figures, runs on
its chapter folder and reports the requested figures from the chapter crops.
The batch refuses a named book whose chapters are in the vault and names that
folder; a run that only [adopts](references/review-and-repair.md#adopt-legacy-crops)
the book's legacy crops records them and extracts nothing.
Only `--include-split-books` deliberately selects both representations
and may produce duplicate figures. Pass it only when the user explicitly asks
for the book's duplicate figures, never for a request that names a split book
or one of its figures. Existing whole-book figures are reported,
never automatically deleted.

### 2. Extract with the shipped batch command

```bash
python3 '<skill>/scripts/batch_extract.py' \
    --src '<vault>/Sources/PDFs' \
    --out '<vault>/Sources/Images'
```

Replace `--src` with the full PDF path for one file. Add `--dry-run` for a
preview that writes **nothing**: no PNGs, review marks, manifest, or output
directory. For less common options, use the script's `--help`.

Large folder summaries can exceed a host's displayed output: capture stdout
and stderr into unique files under the run's `<scratch>`, keep the exit status,
and read both files completely in slices before the next step.

Add `--keep-frame` to keep a publisher's surrounding frame, which is otherwise
cropped away.

Crops recorded in `.figure-manifest.tsv` with matching bytes are skipped;
`--overwrite` re-crops them unless a review mark protects them. Limit a batch
`--overwrite` to the affected PDFs with `--src` unless the user asked for a
folder-wide refresh: every re-cropped PNG needs visual review again. Any other
occupant of a figure's slot is never replaced, even with `--overwrite`, and a
malformed or symlinked manifest blocks the run; never delete sidecars or
images to force a run. Follow the reference for
[sidecar failures](references/review-and-repair.md#sidecars),
[occupied names](references/review-and-repair.md#occupied-slots) (including
every crop in a `Sources/Images/` without a manifest),
[legacy adoption](references/review-and-repair.md#adopt-legacy-crops), a
[source PDF revised at the same path](references/review-and-repair.md#revised-source-pdfs)
(a verified skip proves ownership, not freshness), and
[changed recorded crops](references/review-and-repair.md#changed-recorded-crops).

**Extended Data.** The default folds Extended Data into `S` (`SI` stays
distinct). A PDF that already has `_fig_ED<N>` crops, recorded or not, stays
in the ED namespace by itself (the batch prints `Using --ed-prefix ED`);
adopt an unrecorded one only after comparing it with its page. Pass
`--ed-prefix ED` explicitly only for a single PDF with no `<stem>_fig*` crop
yet whose captions (the `raw` column of `auto_fig_bbox.py`) number Extended
Data figures separately; otherwise switch a PDF only through the rerun its
summary prints, following
[Extended Data and Supplementary figures](references/review-and-repair.md#extended-data-and-supplementary-figures).
In a vault, the switch relinks notes and canvases in the same run, as a
rename does
([details](references/review-and-repair.md#extended-data-and-supplementary-figures)).

Output is `[pdf_stem]_fig_<label>.png`, with the exact PDF stem including
`_src` and disambiguators. The label comes from the caption, **not extraction
order**: Figure 7 becomes `_fig_7.png`, Figure 1.2 becomes `_fig_1-2.png`, and
Figure S1 becomes `_fig_S1.png`. Follow
[conventions §8](../../shared/CONVENTIONS.md#8-figure-naming-and-sourcesimages);
never rename legacy output to match new examples.

### 3. Inspect the summary and verify crops

**Read the complete summary before reporting success.** Check written and
verified-skipped counts separately from refused PDFs, blank crops, failed
writes, existing crops `--overwrite` kept, occupied names, and PDFs that could
not be read or were not processed. A detected caption is
not proof that an image reached disk.

Use [review and repair](references/review-and-repair.md) for any flagged crop,
caption collision, partial detection, missing figures, duplicate pixels, or
ownership failure. A “PARTIAL” result may be a real missed figure or an
unresolved external reference. Duplicates are review findings, not authority
to delete files.

**Visually review the output:**

- **View** every PNG this run wrote or replaced (listed under each PDF as
  `wrote:`); verified skips need no re-check.
- **Compare with the rendered page** every flagged crop, every crop on a page
  the summary lists under `multi-column pages`, and any PNG showing caption
  text, neighboring content or a cut-off edge. A crop can hold its neighbor's
  chart without a warning.
- **When viewing every new PNG is impractical**, as in a large folder sweep,
  view at least the flagged crops and every crop on a `multi-column pages`
  page, and report the rest as not visually verified.
- **When image viewing is unavailable**, report that limit and leave
  uncertain crops unresolved.

Caption text in a crop must be removed before a note embeds it. Repair a bad
crop, including one the user asks to re-crop, with the reference's
[explicit repair procedure](references/review-and-repair.md#set-and-verify-an-explicit-crop)
for coordinate units, naming exceptions, scratch copies, review marks and
cleanup.

Record `--mark-reviewed '<stem>:<fig>'` only after viewing the crop against
its page: for every flagged crop confirmed correct as written and every
explicitly repaired crop, flagged or not. Leave unviewed or doubtful crops
unmarked and report them. The mark verifies nothing, silences its warnings
and protects the crop from a later batch `--overwrite` until
`--unmark-reviewed` removes it. Preserve every recovery path named by a
failed write.

### 4. Report completed and unresolved work

Give the source scope, output folder, figures written, verified skips, and any
legacy adoptions. For a one-figure request, state the requested label's
outcome. Name skipped whole books and feed-owned attachments, unnumbered
exhibits, refused sources, conflicting occupants, failed PDFs, remaining
warnings, and explicit crop repairs. After an Extended Data switch, name the
relinked notes, each S crop kept because a link could not move, and each
leftover S crop. State what visual review was completed,
the review marks recorded, and the unviewed or doubtful crops left unmarked. After a
nonzero run, report the PDFs that succeeded without calling the whole request
complete. Preserve originals, legacy panels, and all unrelated images.

At closeout, apply the [closeout gate](../../shared/RUNTIME.md#close-out) to
`Reviews/figure-extract-suggestions.md` and to the logs of producers whose
outputs this run consumed.
