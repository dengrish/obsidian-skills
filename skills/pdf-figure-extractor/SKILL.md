---
name: pdf-figure-extractor
description: >
  Extract whole figures from one PDF or a folder of PDFs into cropped PNGs,
  with captions removed and filenames tied to the source. Use for requests
  such as "extract figures from my PDFs" or "rip the figures out of this
  paper", including populating Sources/Images/ from Sources/PDFs/. For a
  paper explanation use paper-summarizer; for renaming or chapters use
  pdf-organizer.
---

# PDF Figure Extractor

## Setup and scope

Read [shared/RUNTIME.md](../../shared/RUNTIME.md) once per task for vault
selection, script paths, Python dependencies, and host tools. Below, `<skill>`
is this skill's directory. Use one interpreter with PyMuPDF and Pillow for
all commands. The shipped scripts are the implementation; do not copy their
caption detection or crop logic into a separate script.

The deliverable is **whole-figure PNGs**, not PDF renames, summaries, or wiki
entries. `paper-summarizer` owns paper explanations, `pdf-organizer` owns
source naming and chapter splitting, `wiki-builder` owns new wiki entries,
`wiki-linter` owns existing wiki maintenance, and `clipping-processor` owns
Web Clipper captures. An unspecified “process this PDF” request needs a
stated deliverable before selecting a workflow.

Normally read `Sources/PDFs/` recursively and write to the **flat**, shared
`Sources/Images/` folder. Use the paths the task establishes; do not infer an
external PDF should be imported into a vault. This skill does not split
lettered panels. Older panel PNGs remain valid content and must not be deleted
or renamed as cleanup.

## Workflow

### 1. Confirm source identity and extraction scope

Run `pdf-organizer` first if the sources do not have canonical filenames;
Inbox PDFs need organizing and filing before ordinary vault extraction.
Every crop uses the source's exact on-disk stem, so a later rename requires
the organizer's guarded repair. The batch helper refuses unorganized names.
Use `--allow-unorganized` only for a deliberate one-off exception and explain
that downstream source identity will depend on the current name. The shared
rule is [conventions §1a](../../shared/CONVENTIONS.md#1a-source-file-names-and-why-pdf-organizer-runs-first).

`--src` accepts a single PDF or a recursively scanned folder. Across that
scope, PDFs must have distinct stems, including case and Unicode normalization
variants. Colliding sources are refused before either writes or adopts
images, even with `--overwrite`; organize their names before retrying.
Other independent PDFs may continue, but the run exits nonzero.

**In a recursive run containing both a book and its chapters, extract the
chapters and skip the whole book.** This pairing uses the shared naming
functions: a book and chapter carry `_src` independently, while `_2` / `_3`
remain part of distinct document identities. The skip is scoped to this run,
not a standing fact about the vault. Naming the book PDF directly selects it;
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

Verified existing figures are skipped. `--overwrite` replaces **verified
output only**; an unknown or conflicting occupant is protected in both batch
and manual extraction. Malformed, protected, or symlinked ownership manifests
block extraction. Do not delete sidecars or occupied images to force a run.
Read [review and repair](references/review-and-repair.md) when ownership or
legacy migration needs attention.

On the first batch run without a manifest, adoption is limited to complete
legacy PNGs keyed to canonical, uniquely named PDFs within `--src`, and is
reported. Other images remain unclaimed. For an initial migration of existing
PDF figures, use the full intended `Sources/PDFs/` scope; a single-PDF run
cannot establish ownership of other papers' figures.

Choose `--ed-prefix ED` when Supplementary Figure 1 and Extended Data Figure 1
are distinct figures; the default folds both into `S`. `SI` remains distinct.
Use `--keep-frame` if the publisher's surrounding frame should be preserved;
otherwise detected frames are cropped away.

Output is `[pdf_stem]_fig_<label>.png`, with the exact PDF stem including
`_src` and disambiguators. The label comes from the caption, **not extraction
order**: Figure 7 becomes `_fig_7.png`, Figure 1.2 becomes `_fig_1-2.png`, and
Figure S1 becomes `_fig_S1.png`. Follow
[conventions §8](../../shared/CONVENTIONS.md#8-figure-naming-and-sourcesimages);
existing consumer matching remains `[source_stem]_fig*`, including older
accepted names. Do not tighten it or rename legacy output to match new examples.

### 3. Inspect the summary and verify crops

**Read the complete summary before reporting success.** Check written and
verified-skipped counts separately from blank crops, failed writes, occupied
names, and PDFs that could not be read. A detected caption is not proof that
an image reached disk.

Use [review and repair](references/review-and-repair.md) for any flagged crop,
caption collision, partial detection, missing figures, duplicate pixels, or
ownership failure. Render the relevant pages and compare them with the PNGs.
A “PARTIAL” result may be a real missed figure or a reference to another
work; inspect it rather than assuming either. Duplicates are review findings,
not authority to delete files.

**Inspect figures from multi-column papers even when the summary is clean.**
A crop can contain its neighbor's chart without triggering a warning. More
generally, clean geometry checks do not establish visual correctness. If
page/image viewing is unavailable, report the verification limit and leave
uncertain crops unresolved.

Caption text in a crop must be removed before a note embeds it. Set a manual
crop when needed, then inspect the resulting PNG. Only after checking and
repairing a flagged figure may you record `--mark-reviewed '<stem>:<fig>'`;
that option suppresses future warnings and does not itself verify anything.
The reference provides the crop and review commands with coordinate units.

### 4. Report completed and unresolved work

Give the source scope, output folder, figures written, verified skips, and any
legacy adoptions. Name skipped whole books, conflicting sources/occupants,
failed PDFs, remaining warnings, and manual repairs. State what visual review
was completed and any review marks recorded. Other PDFs may have succeeded
during a nonzero run; report that partial outcome without calling the whole
request complete. Preserve originals, legacy panels, and all unrelated images.
