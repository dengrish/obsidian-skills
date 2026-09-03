# Book splitting

Read this when the [organizer book test](../SKILL.md#5-test-for-a-book-and-split-only-when-justified)
identifies a book, or when the user explicitly requests chapter PDFs. Finish
any required guarded rename first; the selected book must have a stable
canonical name. `<skill>` is the directory containing the organizer's
`SKILL.md`. Use `scripts/organize.py split` or its `split_book` API.

## 1. Choose the chapter folder and check for an existing split

Inside a vault, chapters go in a folder named after the book, directly under
`Sources/PDFs/`: `Sources/PDFs/Kuhn_StructSciRev_2012/`. Outside a vault,
create that folder beside the book. **The original book stays where it is;
chapters are additions, not replacements.**

If the folder already contains chapter-pattern PDFs, stop and report that the
book was split before. Those filenames are authoritative. Never re-abbreviate
an existing set: a future explicitly requested re-split must reuse those
names or not proceed. The helper refuses occupied targets; an existing set
is not permission to overwrite or delete it.

Keep chapters in the shared source tree so recursive consumers meet them.
`pdf-figure-extractor` extracts from chapters rather than the whole book when
both are in its run. An ordinary `paper-summarizer` folder sweep skips recognized
books and chapters; a named chapter, or the skill's explicit chapter/book
override, can still select one. Scoping a figure run to the book file itself
deliberately selects that book. See
[source identity conventions §1a](../../../shared/CONVENTIONS.md#1a-source-file-names-and-why-pdf-organizer-runs-first)
for the common naming functions.

## 2. Find and verify chapter boundaries

Use two passes, preferring a table of contents:

1. Look in the first roughly ten pages for chapter titles and printed start
   pages, such as `Chapter 1: Introduction ... 1`, `I. The Problem ... 23`, or
   an unnumbered chapter title. Distinguish roman-numbered front matter from
   arabic-numbered body pages. Map printed page numbers to physical PDF pages
   by inspecting the page text; **do not assume a constant offset without
   checking it**.
2. If there is no usable TOC, scan headings throughout the book. Look for
   `Chapter N`, recurring prominent headings on new pages, or standalone
   chapter title pages. Do not infer reliable boundaries from page count
   alone.

Extract actual chapters only. Skip prefaces, forewords, introductions unless
labeled as a chapter, epilogues, afterwords, appendices, acknowledgments,
indexes, bibliographies/references, notes, glossaries, author biographies, and
lists of figures or tables. Ignore “Part” groupings and extract the chapters
within them.

A chapter ends at the next chapter's start. The last ends at the first
excluded back-matter section, or the end of the book if there is none.

**The chapter API uses zero-based physical PDF indices.** `start_idx` is the
first included page and `end_idx` is the page **after** the last included page.
These are not printed folio numbers or the one-based page numbers used by the
figure-cropping tools. For example, physical pages 43–78 use `start_idx=42`
and `end_idx=78`.

`split_book` checks each start against the original `heading_text`, searches
±2 pages for a nearby match, and can include a standalone chapter title page
immediately before the mapped start. A larger offset or unmatched heading is
refused. Review every reported adjustment: it can indicate that the mapping
for the rest of the book also needs correction. Do not treat automatic
adjustments as a substitute for checking the TOC-to-page mapping.

## 3. Choose chapter names once

Use `AuthorLastName_AbbreviatedTitle_Year_##_AbbreviatedChapterName.pdf`.
Reuse the book's author, abbreviated title, and year. Use its printed chapter
numbers, zero-padded to two digits; for unnumbered chapters assign
`01`, `02`, etc. from the first actual chapter. Abbreviate the chapter title
in recognizable CamelCase, retaining distinguishing words and avoiding new
or ambiguous acronyms.

| Chapter | Filename |
|---|---|
| 1: Introduction: A Role for History | `Kuhn_StructSciRev_2012_01_RoleHistory.pdf` |
| 2: The Route to Normal Science | `Kuhn_StructSciRev_2012_02_RouteNormSci.pdf` |
| 3: The Nature of Normal Science | `Kuhn_StructSciRev_2012_03_NatureNormSci.pdf` |

Keep the canonical relationship `<book core stem>_NN_Name`; do not shorten
the book title again for its chapters. “Core” removes only the `_src`
representation marker, **not** a `_2` or `_3` disambiguator. A chapter does not
inherit its book's `_src`: `Prince_UDL_2026_src.pdf` produces
`Prince_UDL_2026_01_Intro.pdf`. If a chapter already has its own marker, the
tail goes **after** the chapter name, as in
`Prince_UDL_2026_01_Intro_src.pdf`.

A disambiguated book cannot be split under this grammar. The helper refuses
it; distinguish the books in the abbreviated title before the year, carry
that change through the [guarded rename workflow](../SKILL.md#3-check-references-and-prepare-the-complete-rename-plan),
then split. Do not strip the disambiguator or borrow the other book's chapter
identity. Use `organize.py canonical` or the shared naming functions rather
than recreating the naming grammar.

Each resulting filename becomes the exact source stem for figures and note
references. It must be unique both in its destination and throughout the
vault, including case variants; the split helper checks this before writing.

## 4. Build the complete chapter list and split

Store a JSON array of chapter objects in a **unique scratch directory** from
runtime setup. Keep the original heading separately from the output name:

```json
[
  {
    "heading_text": "The Route to Normal Science",
    "filename": "Kuhn_StructSciRev_2012_02_RouteNormSci.pdf",
    "start_idx": 42,
    "end_idx": 78
  }
]
```

The page indices above illustrate the format, not verified boundaries for a
particular edition. Build and inspect the complete list for the actual PDF.

```bash
python3 '<skill>/scripts/organize.py' split '<book PDF path>' \
    --chapters '<scratch>/chapters.json' \
    --out '<vault>/Sources/PDFs/<book stem>' --vault '<vault>'
```

Outside a vault, omit `--vault` and put `--out` beside the book. For an API
caller, import the shipped helper and build its name map **at each split**:

```python
import sys
sys.path.insert(0, "<skill>/scripts")
from organize import split_book, vault_names

notes = split_book(pdf_path, chapters, out_dir, vault_names(vault))
```

Use `--vault` / `vault_names(vault)` whenever a vault is in scope. Rebuild
that map after every earlier rename or split; a snapshot from the start of
a batch cannot protect against names created later in the same batch. Without
a vault, pass an empty map and report that only destination checks ran.

The helper resolves **all chapters before writing any**. Every heading must
map to a verified start, all ranges must be in bounds and non-overlapping,
and every filename must pass `SAFE_NAME`, remain under 200 bytes, and have
an unoccupied destination both locally and vault-wide. Occupied symlinks and
case-equivalent names also block. `SplitRefused` lists unresolved problems;
do not bypass one by extracting just the chapters that passed.

During writing, the helper stages chapter files and rolls back files created
by this operation on failure. It does not replace the original book or remove
pre-existing user files. Read the returned notes and CLI diagnostics before
claiming success.

## 5. Verify and report

Report created filenames and physical page ranges, any adjusted start/end
pages, and unresolved boundaries. Say explicitly that the original book was
kept. A refused or unreadable book is a per-file batch outcome; report its
message in plain language and continue other independent files.

If whole-book figures already exist under the book's stem in
`Sources/Images/`, name them as possible duplicates of future chapter figures
for review. Do not automatically remove them or claim byte equality without
checking. This skill does not extract or delete figures.

## Conditions that stop the split

- **No detectable chapters or uncertain page mapping:** report what could
  not be established. Do not create an empty folder or invent boundaries.
  Ask for manual ranges only after completing any independent work.
- **Scanned or garbled text:** inspect available page renders and, if useful,
  use available OCR on a scratch copy under runtime guidance. Preserve the
  original. If OCR is unavailable, follow runtime dependency guidance and
  name any remaining limitation; do not claim verified boundaries merely to
  continue.
- **Corrupt download, HTML saved as PDF, or zero-byte input:** report the
  open error. This needs a valid source, not OCR.
- **Encrypted input that cannot be unlocked:** report and stop that file.
- **Already a single chapter or an existing split:** leave the chapter set
  intact; a chapter may be renamed through the normal guard, not split again.
- **Missing `pypdf`:** follow runtime dependency guidance. The stdlib rename
  helper remains available, but splitting cannot proceed in that interpreter.
