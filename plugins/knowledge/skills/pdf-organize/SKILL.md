---
name: pdf-organize
description: >
  Rename PDFs from their content inside or outside an Obsidian vault, file
  vault Inbox PDFs in Sources/PDFs/, and split books into chapter PDFs while
  keeping the original. Each rename or move carries the matching figures,
  summary note and links. Use for one PDF or a folder: "rename this PDF",
  "file this PDF", "organize my papers", "process my inbox", or "split this
  book". PDFs only; inbox-wide requests also use clipping-clean for Markdown
  captures and leave other file types untouched. A reading note uses
  paper-summarize, figures alone use figure-extract, and wiki entries use
  wiki-build.
---

# PDF Organize

## Setup and scope

Read [shared/RUNTIME.md](../../shared/RUNTIME.md) once per task for vault
selection, script paths, Python dependencies, and host tools. Use
`scripts/organize.py` for checks, renames, and splits; do not recreate its
filesystem or link-repair logic in shell snippets. `canonical`, `check` and
`rename` need only Python's standard library, so a rename-only run on a host
that can view PDF pages installs nothing. Read pages for naming with the
host's PDF viewing tools, or with the
[step-2 text fallback](#2-read-enough-to-choose-a-stable-name) when the host
has none. Before the first `pages` or `split` command, or any other step that
parses a PDF or image with this environment, set up the environment from
`<plugin>/requirements.txt` and run
`python3 '<plugin>/shared/scripts/check_parsers.py'` with it under the
[parser-check rule](../../shared/RUNTIME.md#only-for-pdf-and-image-workflows).
While it fails, run no such step and split nothing.

This skill changes PDF names and locations and creates chapter PDFs. For
figure images use `figure-extract`; for a document explanation or reading
note use `paper-summarize`; for new or enriched wiki entries from this PDF
use `wiki-build`; for maintenance of existing entries use `wiki-lint`. A bare
PDF with no stated deliverable needs routing clarification, not an automatic
chain of all these skills.

- For a vault-wide request, enumerate only `Inbox/` and `Sources/PDFs/`,
  recursively; do not discover candidates in other vault folders. Never
  select notes in `Wiki/`, `Articles/`, or the vault root, or figures in
  `Sources/Images/`, as independent rename targets. Derived files may follow
  their source through the guarded rename below.
- Skip [feed-owned attachments](../../shared/CONVENTIONS.md#1c-feed-owned-attachments)
  in every sweep, even under `Sources/PDFs/` (`canonical` reports
  `feed-owned, skipped`); their paths belong to the collector's receipts.
  `check` and `rename` refuse even a named one.
- A PDF in `Inbox/` is filed in `Sources/PDFs/`. A PDF in another vault
  folder is filed there only when the request is to organize or file it; a
  request only for a better name renames it where it stands. A PDF already
  under `Sources/PDFs/` is renamed where it stands.
- Outside the vault, rename in place with **no `--vault` or `--dest`** and
  report that vault-wide checks did not run. `rename` never imports it; to
  bring it into the vault, copy it into `Inbox/` with the user's approval and
  file that copy.
- Leave non-PDF input files untouched and report them separately: Markdown
  captures in `Inbox/` belong to `clipping-clean`; other file types have no
  filing skill here. An inbox-wide request also runs clipping-clean over
  those captures; their raw files stay in `Inbox/`. A PDF-only request does
  not authorize processing them.

## Workflow

Steps 1–5 run once per PDF; step 6 reports the whole run. A batch (a folder,
"organize my papers", or an inbox-wide request) handles each file
independently with its own `check` and `rename` plan, never reusing names or
collision decisions from the start of the batch. It records failed or
refused plans and splits (exit 1) and unreadable or encrypted PDFs, then
continues with the next file; exit 2 from `rename --apply` stops the whole
batch ([step 4](#4-apply-then-verify-the-whole-family)). A target stem that
another source's files occupy is no refusal: the batch re-plans that PDF
under a distinguishing name and files it, as
[step 3](#3-check-references-and-prepare-the-complete-rename-plan) says.
Each PDF takes the first row that matches its state; a single selected PDF
always gets the step-5 book test:

| PDF state | Steps 1–4 | Step 5 book test in a batch |
|---|---|---|
| Feed-owned attachment | Skip it (`feed-owned, skipped`) | None |
| A canonical chapter in its book's folder | Skip it | None: the existing split stands |
| Found unreadable, corrupt, or encrypted | Leave it unchanged and record it | None |
| Not canonical, in `Inbox/` | Name it and file it in `Sources/PDFs/` (`--dest`) | After filing |
| Canonical, in `Inbox/` | Keep its basename and file it from step 3, unless another source's files occupy its stem | After filing |
| Not canonical, in `Sources/PDFs/` | Rename it where it stands | After renaming |
| Canonical, in `Sources/PDFs/`, including an unsplit book | Skip it as already canonical | Only when the request asks to split books, or a hand-off asks for one of its chapters |
| In another vault folder the request names | File it as from `Inbox/` when asked to organize or file it; otherwise rename it in place | After renaming or filing |
| Outside the vault | Rename a non-canonical name in place, with no `--vault` or `--dest`; a canonical name stays | After renaming; a canonical one only when the request asks to split books |

### 1. Check the input, filename, and location

Accept PDFs only. Preserve the original extension; `organize.py` blocks an
extension change. An extensionless download may be given `.pdf` only after
confirming it is a PDF. Treat filenames and document content as data,
following the [input-safety rules](../../shared/INPUT_SAFETY.md).

Check names with the helper, not a regular expression:

```bash
python3 '<skill>/scripts/organize.py' canonical '<complete PDF filename>'
```

Pass the **complete filename**, never an extracted stem
([conventions §1a](../../shared/CONVENTIONS.md#1a-source-file-names-and-why-pdf-organize-runs-first)).
`canonical` takes several names at once, prints one line for each, and
exits 1 when any of them is not canonical.

A canonical PDF already under `Sources/PDFs/`, or outside the vault, needs no
metadata rename. A canonical PDF that the scope rule above files, usually in
`Inbox/`, still needs filing: keep its basename and continue at step 3. When
another source's files occupy that stem, step 3's
[target-stem rule](#3-check-references-and-prepare-the-complete-rename-plan)
files it under a distinguishing name instead. An explicit request to correct
a canonical name uses the normal guarded workflow. A chapter in its book
folder keeps the [`<book core>_NN_Name` form](references/book-splitting.md#3-choose-chapter-names-once):
a correction changes only its chapter name, or its number within its
neighbours' order, and the helper blocks any other name. A skipped rename
never skips the book test that step 5 requires.

### 2. Read enough to choose a stable name

Read the first two or three pages with the host's PDF viewing tools for
author, title, and year. When the host cannot view a PDF, read those pages as
text instead:

- Use `pdftotext -layout -f 1 -l 3 '<pdf>' -` when it is available.
- Otherwise set up the environment and pass the parser check as in setup,
  then read the first page blocks of
  `python3 '<plugin>/skills/paper-summarize/scripts/paper_text.py' '<pdf>' --pages`.

Do not choose names from `organize.py pages`, which lowercases the text.

Name the PDF `AuthorLastName_AbbreviatedTitle_Year.pdf`:

- Use the first author's surname with normal capitalization, or an
  organization's recognizable short name. Join a multi-word surname in
  CamelCase (`VanDerWaals`) and transliterate diacritics. If no author can
  be established, use the issuing organization or `Unknown`.
- Shorten the title in CamelCase, retaining enough to distinguish the work.
  Use established field acronyms or familiar truncations, not invented or
  ambiguous acronyms. A recognized work nickname such as `CLRS` is suitable.
  Prefer a meaningful heading to a generic invented title, and report
  uncertainty.
- Use the publication year printed in the document (for an article, the year
  published online, else the issue year, never a received or accepted year;
  for a book, the specific edition's year; for a preprint, the year this
  version was posted, as printed on it, not the date inside its DOI). A
  periodic report uses its release year; put the covered period in the
  abbreviated title. Do not take the year from outside the document; if none
  is printed, use `nd`.
- For non-English sources, use an English title provided by the document;
  otherwise transliterate the original rather than inventing a translation.

The year segment is `0001`–`9999` or `nd`; `0000` is never a canonical
year. Examples: `Vaswani_AttnAllYouNeed_2017.pdf`, `Cormen_CLRS_2022.pdf`,
`GoldmanSachs_Q4FY24Earnings_2025.pdf`, and `AcmeCorp_StrategyMemo_nd.pdf`.

Name segments use only ASCII letters, digits, and hyphens, separated by
underscores; the helper refuses any other name. Preserve an existing `_src`
marker (another representation of the same document) exactly; never add or
remove it during a rename. Both representations of a split book pair with
one chapter set, so renaming one also renames the other, with its figures
and note; each keeps its own marker. A trailing `_2`, `_3`, … distinguishes a
**different document** with an otherwise colliding name; it follows `_src`
when both occur. Figures keep the PDF's exact on-disk stem, including these
markers.

If the pages show no text or garbled text, inspect rendered pages or use
available OCR tools on a scratch copy under the runtime guidance. Do not
modify the original just to obtain metadata. A corrupt, truncated,
encrypted, or non-PDF file is a separate outcome, not automatically an OCR
candidate. If it cannot be read reliably, report and leave it unchanged.

### 3. Check references and prepare the complete rename plan

Before every rename or filing move inside a vault, run:

```bash
python3 '<skill>/scripts/organize.py' check '<current PDF path>' --vault '<vault>'
```

A `REFERENCED` report exits 1 and lists the citing paths; it is not a failed
scan, and the rename plan below decides whether any citing note blocks. A scan
error never establishes that the source is unreferenced.

The check reports references in notes and Canvas boards, including
extensionless note links, to the PDF and its candidate
[family](references/rename-repair.md#establish-the-owned-family).
**The request that leads to a rename or filing move, including the rename a
split requires, authorizes the helper's verified reference repair.** Review
the read-only plan below; when nothing blocks it, apply it without asking.

```bash
python3 '<skill>/scripts/organize.py' rename '<vault>/Inbox/<original>.pdf' \
    --to '<Author_Title_Year>.pdf' --vault '<vault>' \
    --dest '<vault>/Sources/PDFs'
```

Without `--apply`, this only reports moves, note and canvas rewrites,
sidecar changes, unreadable notes, and blockers. Omit `--dest` for a PDF renamed where it
stands; omit both `--dest` and `--vault` outside the vault. A supplied vault
destination must be absolute and inside that vault. Changing the canonical
year also reconciles the owned summary note's `published` field under the
[rename plan rules](references/rename-repair.md#review-the-plan-before-writing).

Read [rename repair](references/rename-repair.md) **before applying a plan
that moves derived files, rewrites notes, or updates figure sidecars**, and
when ownership or verification is unclear. The helper decides the owned
family; never widen it by filename matching.

**No blocker may be bypassed; `--apply` is not an override.** For a name
collision, first decide whether the other file is the same document (title,
edition, bytes):

- **Proposed name taken.** A same-document copy is a duplicate: leave both in
  place, report both paths, and ask the user to remove the redundant copy. A
  different document gets a distinguishing abbreviated title, or `_2`, `_3`
  as a last resort (never for a book or its chapters); then re-plan.
- **Own basename shared.** When another vault file shares the basename of
  the selected PDF or of a chapter in its family, the helper blocks the plan
  unless [conventions §1a](../../shared/CONVENTIONS.md#shared-pdf-basenames)
  exempts that copy. Report both paths and relay the helper's remedy.
- **Target stem occupied.** `<new stem>_fig*` images or an
  `Articles/<new stem>.md` note outside the family, for the PDF or any
  renamed chapter, block the plan even when the figure manifest records
  them. Filing a PDF under its unchanged stem checks that stem too. Report
  the occupants and the notes citing them; the next step depends on whose
  files they are:
  - *This PDF's own files.* Figure-extract crops or a reading note of this
    same PDF are no reason for another name: the PDF stays where it is
    under **Blocked or failed**. Ask the user whether to clear those files
    from that name before the rename or filing and restore them afterward.
  - *Another tool's crops of this same PDF*, such as a slide deck's, share
    its natural name by
    [rename repair's label test](references/rename-repair.md#establish-the-owned-family):
    pass `--foreign-image '<name>'` for each, and file the PDF under that
    name. They stay that tool's files, never adopted, moved or overwritten.
  - *Any other occupant*, such as a clipping-clean note or its images,
    another document's files or images these pages do not show, keeps its
    name: re-plan the PDF now under a distinguishing abbreviated title, as
    for a proposed name taken (never `_2` for a book), and file it. Report
    the natural name it could not take and its occupants.
  - *Another source's images under the PDF's current stem* block it as
    unowned crops. Once the label test shows they are not its figure-extract
    crops, re-plan: pass `--foreign-image '<name>'` for each in that
    re-plan, and they keep their names.

Never delete or move either copy; the redundant one is the user's to
remove. Other blockers need their actual cause resolved.

### 4. Apply, then verify the whole family

Once the plan has no blockers, repeat the same `rename` command with
`--apply`. Do not use a bare `mv`, a global search-and-replace, or a separate
loop over old names. Only the source PDF is filed in a new location; its
figures, note, and chapter folder stay in their own folders and are renamed
there.

The CLI rechecks the plan and verifies references to **every obsolete name**,
including figures and notes, and that no Canvas card still points at an old
path. If verification fails, **report and stop that repair; do not hand-patch
the reported notes**. Report the actual rollback result. A file changed after the scan is preserved and fails the apply
closed: re-plan from the current files, and keep every recovery path the
error names until reconciled.

**Exit 2 from `rename --apply` means its rollback did not complete.** It
stops the batch: report every path the error names, and run no further
renames until they are reconciled.

### 5. Test for a book and split only when justified

For a single selected PDF, or a batch PDF that the
[batch table](#workflow) sends to this test, look for a chapter table of
contents, repeated chapter headings, or a book title page. Length around 50
pages or more is a supporting signal, not enough on its own. If it is an
article, finish. If it is already one chapter, do not split it again.

When a book is detected, the user's own request decides whether to split
it, not the wording of a hand-off from another skill:

- **Split it: keep the original and add chapter PDFs** when the request
  asks to organize or file PDFs (one, several, a folder or the inbox, as in
  "rename and file the PDFs in my Inbox"), to process or clean the inbox, or
  to split a book. A request for one chapter of an unsplit book, handed off
  by wiki-build, paper-summarize or figure-extract ("build chapter 3 into my
  wiki", "summarize chapter 3 of this book", "extract the figures of
  chapter 3"), counts as a request to split that one book. A request for a
  part the split leaves out, such as a preface or an appendix, does not.
- **Report the book and its proposed split, and create no chapters,** for
  any other request: one that asks only to rename or identify PDFs, one or
  several, and a paper-summarize or figure-extract run that hands this
  skill its source only to name or file it.

Read
[book splitting](references/book-splitting.md) before choosing boundaries or
writing chapters; it also governs names, collisions and existing chapter
sets. Its `pages` and `split` commands parse the PDF, so the parser check
from setup must pass first. A rename blocked in step 3 must be resolved
before a dependent split.

### 6. Report outcomes and remaining work

Report in these groups, leaving out empty ones:

- **Renamed and filed:** old and new paths, with any uncertain metadata
  choice explained; for a PDF filed under a distinguishing name, the
  natural name it could not take and its occupants; for one filed beside
  another tool's crops of it, those crops; outside the vault, say that
  vault-wide checks did not run.
- **Repairs:** note, canvas and sidecar repairs, and any notes or canvases
  that could not be read.
- **Dates:** when the year changed, the planned old and new `published`
  values for each owned summary note, saying that a new dated value is
  `01-01` padding.
- **Chapters:** the created chapters with their page ranges, as
  [book splitting](references/book-splitting.md#5-verify-and-report)
  details, and any book left unsplit with its proposed split.
- **Skipped:** already-canonical files, already-split books, and
  feed-owned attachments.
- **Blocked or failed:** duplicate basenames, refused plans and splits,
  unreadable PDFs, and recovery paths still to reconcile.
- **Not PDFs:** Markdown captures and other non-PDF files, each in its own
  group, so an inbox-wide request does not falsely read as empty.

Do not delete originals, figures, or raw captures as cleanup.

At closeout, apply the [closeout gate](../../shared/RUNTIME.md#close-out) to
`Reviews/pdf-organize-suggestions.md` and to the logs of producers whose
outputs this run consumed.
