# Book splitting (PDF only)

Read this when the book test in `SKILL.md` (*When to split*) fires — and only
then. A rename-only run never opens this file, and that is most runs: all but two of
this skill's trigger phrases are renames or filing.

Everything below assumes the book has already been renamed to the canonical
form (or was already in it), because the chapter names are derived from the
book's stem. `<skill>` is the directory `SKILL.md` sits in.

---

## Detecting chapter boundaries

Use a two-pass approach.

**Pass 1 — Table of Contents (preferred):**
Look for a page labeled "Contents", "Table of Contents", or similar in the first ~10 pages. Parse it to extract chapter names and their starting page numbers. TOC entries typically follow patterns like:
- `Chapter 1: Introduction ......... 1`
- `1. Introduction  15`
- `I. The Problem  23`
- `The Boy Who Lived .............. 1` (unnumbered chapter title)

When parsing page numbers from a TOC, be aware that many books use separate numbering for front matter (roman numerals i, ii, iii…) and body text (arabic 1, 2, 3…). The page numbers printed in the TOC refer to the book's internal numbering, which may not match the PDF's physical page index. To map TOC page numbers to PDF page indices, scan each page's text for a printed page number (usually at the top or bottom) and build a mapping. This step is essential — without it, chapter splits will land on the wrong pages.

**The one pitfall the code cannot fix for you: 0-indexed vs 1-indexed.** `pypdf` indices are 0-based (`reader.pages[0]` is the first page); printed book page numbers are 1-based. Get the conversion wrong and every chapter silently loses its first page. `split_book` verifies each mapped start page against the chapter's `heading_text` and searches ±2 pages around it, so a small systematic offset is corrected and reported rather than shipped — but an offset larger than two, or a heading it cannot match, is refused, and that refusal is the signal that the mapping is wrong at the source. It also pulls in a standalone chapter title page sitting immediately before the mapped start, which is where the TOC usually points past.

**Only extract actual chapters.** Skip everything that isn't a real chapter: preface, foreword, introduction (unless it's labeled as Chapter 1 or similar), epilogue, afterword, appendices, acknowledgments, index, bibliography, references, notes, glossary, "about the author", list of figures/tables. The goal is to produce one PDF per real chapter — nothing else. If a book has "Part" groupings (e.g., "Part I: Foundations" containing Chapters 1-4), ignore the Part divisions and extract each chapter individually.

**Pass 2 — Heading scan (fallback):**
If no TOC is found, scan every page for chapter headings. Chapters may or may not be numbered — look for:
- "Chapter N" or "CHAPTER N" (where N is a number or word)
- Standalone title-like text on an otherwise mostly blank page (a chapter title page)
- Recurring structural patterns — if the book has a series of sections that each start on a new page with a prominent heading, those are likely chapters

Only extract actual chapters — skip all non-chapter sections as described above for TOC parsing.

**Determining chapter end pages:** Each chapter runs from its start page to one page before the next chapter starts. The last chapter runs to the end of the book or to the start of excluded back matter (index, bibliography, glossary), whichever comes first.

---

## Chapter filename format

```
AuthorLastName_AbbreviatedTitle_Year_##_AbbreviatedChapterName.pdf
```

- **AuthorLastName, AbbreviatedTitle, Year**: Same as the base rename convention (`SKILL.md`, *Naming Convention*).
- **Any `_src` or `_2` tail goes at the very end, after the chapter name** — `Prince_UDL_2026_02_SupLearn_src.pdf`, never `Prince_UDL_2026_src_02_SupLearn.pdf`. **A chapter does not inherit its book's tail:** splitting `Prince_UDL_2026_src.pdf` produces `Prince_UDL_2026_01_Intro.pdf`, and that chapter grows its own `_src` only when it, too, has a same-stemmed note beside it. Don't decide this by eye — `looks_canonical()` in `shared/scripts/naming.py` is the rule (`python3 '<skill>/scripts/organize.py' canonical '<name>'`), and `CONVENTIONS.md` §1a is why it is pinned: the ordering used to have two homes that disagreed, and the disagreement cost either every chapter's figures or a doubled set of them.
- **##**: Zero-padded chapter number (`01`, `02`, … `12`). If the book's chapters are already numbered, use those numbers. If they're unnumbered, assign sequential numbers starting from `01` for the first real chapter.
- **AbbreviatedChapterName**: Abbreviated chapter title in CamelCase, following the same abbreviation philosophy as the title above. Use field-standard acronyms and short word truncations freely — `DL`, `NLP`, `RL`, `CNN`, `DNA`, `QM`, `Intro`, `Bio`, `Comp`, etc., depending on what's standard in the document's field. Avoid inventing new acronyms — when in doubt, partially spell out. Watch for collisions: if two chapters in the same book would abbreviate to the same name (e.g., both about "Normal Science"), keep enough distinguishing words in each. `split_book` refuses to run when two chapters resolve to one filename — including two that differ only in case, which are one file on the user's volume — so a collision is a stop, not a silent overwrite.

**A chapter filename becomes the `[pdf_stem]` everything downstream keys to.** Figures for that chapter land in `Sources/Images/` as `[pdf_stem]_fig_N.png`, and a wiki entry citing the chapter carries the same string. Three consequences, and none of them is enforced by anything downstream:

- **The `_NN_` segment is what tells a chapter from its book.** A split leaves both files on disk — the book where it already was, the chapters in their own folder — and `pdf-figure-extractor` walks `Sources/PDFs/` recursively, so a run scoped to `Sources/PDFs/` meets both. It keys off exactly this shape to recognise the book and extract from the **chapters only**; without that, every figure is written twice, once under each stem, byte-identical and never colliding, and whichever stem an entry cites the other copy is unused forever with no diagnostic able to report it. So the chapter stem must stay `<book core stem>_NN_Name`: not a re-abbreviated book title, not a chapter number without the zero pad, not a folder-relative name. **"Core" means the book's stem with `_src` stripped, and nothing else** — a `_2`/`_3` disambiguator stays. The two markers are not one thing: `_src` marks the same document in another representation, so a book and its chapters grow it independently and it has to come off before they are compared, while a disambiguator marks a *different* book that wanted a name already taken (`CONVENTIONS.md` §1a) — strip that and one book's chapters pair with the other's. Both skills compare on `core_stem()` from `shared/scripts/naming.py` rather than on the raw stem, which is exactly this rule. A disambiguated book is not split at all: it has no legal chapter name to give, so `split_book` refuses it before it reads a page, and the fix is at the name — re-abbreviate the title so the two books differ before the year, rename, then split. See that skill's *Split books*.
- **Choose the name once and never re-derive it.** These abbreviations are judgment calls — nothing makes "The Route to Normal Science" come back as `RouteNormSci` rather than `RouteToNormSci` on a second run, so a re-split doubles the stems the vault has to track. The only thing pinning them is the chapter folder itself: if `Sources/PDFs/<Work>/` already holds chapter files, **those names are authoritative**, and a book that genuinely needs re-splitting is re-split *into the existing names* — read them off disk and reuse them — or not at all. Never regenerate a set that already exists.
- **Make each one unique vault-wide, not merely within the book's own folder.** `split_book`'s `taken` argument is how; see *Splitting workflow* below.

### Examples

For Thomas Kuhn's "The Structure of Scientific Revolutions" (4th edition, published 2012):

| Section | Filename |
|---|---|
| Ch. 1: Introduction: A Role for History | `Kuhn_StructSciRev_2012_01_RoleHistory.pdf` |
| Ch. 2: The Route to Normal Science | `Kuhn_StructSciRev_2012_02_RouteNormSci.pdf` |
| Ch. 3: The Nature of Normal Science | `Kuhn_StructSciRev_2012_03_NatureNormSci.pdf` |

---

## Splitting workflow

1. Obtain book metadata (author, title, year). Reuse it if already extracted from a prior step (e.g. Single File Mode step 2), or parse it from the filename if the file already matches the canonical convention. Otherwise, read the PDF's beginning to extract it.
2. Rename the original book PDF using the standard naming convention and keep it in place — **subject to the reference check**, exactly as any other rename is (`SKILL.md`, *The reference check*). If the filename already matches the convention, skip this step — there's nothing to rename.
3. **Decide where the chapters go, and check whether they are already there.** The destination is a folder named after the renamed book, without the `.pdf`. Inside the vault that folder goes **directly under `Sources/PDFs/`, beside the book** — splitting `Sources/PDFs/Kuhn_StructSciRev_2012.pdf` produces `Sources/PDFs/Kuhn_StructSciRev_2012/`, one level down and no deeper. **Both stay**, and the pairing is what downstream reads: `paper-summarizer` sweeps `Sources/PDFs/` recursively and recognises the book as a book only by meeting one of its chapters in the same walk — then skips the book, and skips the chapters as chapters. Bury the folder deeper, or put it outside `Sources/PDFs/`, and the two never meet: the book reads as an ordinary paper and gets summarised figureless, while `pdf-figure-extractor` stops recognising the split and writes every figure twice under two stems that never collide. Outside the vault, the folder simply sits beside the book. Either way, if the destination already holds chapter-pattern files, **the book has been split before — stop and report it** (*Chapter filename format*: those names are authoritative, and re-deriving them is what breaks the vault).
4. Detect chapter boundaries using the two-pass approach above.
5. **Build the chapter list and call `split_book`.** Each `chapter` dict carries both the original heading text (used to verify the page mapping) and the abbreviated filename (used for output), as separate fields — this is the one shape you adapt per book:

   ```python
   chapter = {
       "heading_text": "The Route to Normal Science",            # original, for verification
       "filename":     "Kuhn_StructSciRev_2012_02_RouteNormSci.pdf",
       "start_idx":    42,   # 0-based pypdf index of the mapped start page
       "end_idx":      78,   # 0-based pypdf index of the page AFTER the chapter (exclusive)
   }
   ```

   Then either import it:

   ```python
   from organize import split_book, vault_names, SplitRefused    # scripts/organize.py
   notes = split_book(pdf_path, chapters, out_dir, vault_names(vault))
   ```

   or hand it the list as JSON:

   ```bash
   python3 '<skill>/scripts/organize.py' split '<book>.pdf' \
       --chapters '/tmp/<book stem>-chapters.json' --out '<vault>/Sources/PDFs/<Work>' --vault '<vault>'
   ```

   (Name the chapters file after the book rather than a bare `/tmp/chapters.json` — a fixed name is silently clobbered if a second session is splitting a different book at the same moment.)

   Pass `taken` / `--vault` whenever there **is** a vault: `os.path.exists` inside the output folder is a folder-local check, and the uniqueness guarantee in `SKILL.md` (*What the naming scheme guarantees*) is vault-wide. Outside a vault, omit it.

   **What it guarantees, so you don't re-derive it.** `split_book` runs two passes — *resolve everything, then write*. Nothing reaches disk until every chapter has a start page verified against its `heading_text` (searching ±2 pages, pulling in a standalone title page immediately before), a non-overlapping in-range end page, a filename that passes `SAFE_NAME` and is under 200 bytes, and a target proved free both in the output folder (case-insensitively, `islink` as well as `exists`) and vault-wide. Anything unresolved raises `SplitRefused` listing **every** problem at once, and writes nothing. In the write pass each chapter goes to a temp file and is `os.replace`d into position; a failure part-way deletes what the run just created — and the output folder too, if the run made it — so a half-split never survives.

6. Report a summary of all chapters created with their filenames and page ranges, plus any chapter the resolve pass refused and why. Say that **the book itself stays in place and is not deleted** — the chapters are additions, not a replacement — and that figures are extracted from the chapters, not the book (*Chapter filename format*). If figures under the book's own stem are already in `Sources/Images/` from an earlier run, name them: they are now duplicates of the chapter figures, and nothing downstream will ever report them.

Every `SplitRefused` is a case the user needs to hear about in words, not a stack
trace — read the message out and say what you'd do next. It is a plain
`Exception` on purpose: a batch is a loop, and a `SystemExit` would have ended
the whole run at the first unreadable book (`SKILL.md`, *Batch Mode* step 4). The
`note:` lines are not failures but they are evidence — a trimmed end page, a
start the ±2 search moved, or a title page pulled in ahead of the mapped start
each mean the TOC was misread somewhere, so repeat them in the report. A
corrected start is the loudest of the three: one chapter off by a page usually
means the whole mapping is, including the chapters that happened to land on a
page carrying their heading anyway.

---

## Edge cases

- **No detectable chapters**: Tell the user you couldn't find chapter boundaries and ask if they want to specify page ranges manually. Don't create the output folder just to leave it empty — `split_book` refuses an empty chapter list rather than writing one.
- **Scanned / image-only PDFs**: If `pypdf` returns empty or garbage text for most pages, the PDF has no extractable text and you can't reliably find chapter boundaries. Tell the user, and offer to OCR the file first (`ocrmypdf` produces a searchable copy in place) before splitting. If the OCR tool isn't installed, say that rather than reporting the file as un-splittable.
- **Not a PDF at all**: a truncated download, an HTML error page saved with a `.pdf` extension, a zero-byte file. `pypdf` raises on open, and the fix is re-downloading — **this is not an OCR problem**, so don't recommend one. Report it as its own outcome.
- **Encrypted / password-protected PDFs**: If the PDF is locked and you can't unlock it, tell the user and stop. Don't try to split a file you can't read. (`split_book` checks `reader.is_encrypted` before touching `reader.pages`, which is where the error would otherwise surface, and tries the empty password first.)
- **Already-split chapters**: If a PDF looks like it's already a single chapter (short, starts with "Chapter N"), just rename it — don't try to split further.
- **A book that was already split**: the output folder exists and holds chapter-pattern files. Stop and report; see *Splitting workflow* step 3.
- **A chapter this run cannot place**: `split_book` refuses the whole book rather than writing the ones it could. Read the reasons out and fix the mapping — an out-of-order start, a heading it could not find, a name that collides vault-wide. Partial output is the failure mode being avoided, so don't work around it by splitting the good chapters first.
- **`pypdf` is not installed**: `split_book` says so and stops. The rename half of `scripts/organize.py` needs nothing beyond the standard library and is unaffected.
