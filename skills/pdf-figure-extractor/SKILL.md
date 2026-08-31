---
name: pdf-figure-extractor
description: "Extract figures from PDFs into a flat output folder of cropped PNGs — a whole source folder and its subfolders, or a single named PDF — using the filename convention `[pdf_stem]_fig_N.png` (where N is the figure label from the caption). Handles every common caption style: numbered, dotted, dashed, supplementary, Extended Data, SI. Use whenever the user wants figures pulled out of PDFs, to rip figures out of a folder of papers, or to populate an Obsidian Sources/Images folder from a Sources/PDFs folder. Captions are clipped. Trigger on \"extract figures from my PDFs\", \"rip the figures out of this paper\", or any request whose deliverable is figure images. If the user wants the paper explained instead, use `paper-summarizer`; if they want it renamed or split into chapters, use `pdf-organizer`."
---

# PDF Figure Extractor

**Runtime setup:** Read [shared/RUNTIME.md](../../shared/RUNTIME.md) once per
task for vault selection, script paths, Python dependencies, and host tools.

Walks a source directory tree (or takes one named PDF), detects every figure caption, crops the figure (excluding the caption), trims white margins, and writes the result to a flat output directory.

## When to use this skill

Use whenever the **deliverable is figure images**. Symptoms:

- "extract all the figures from the PDFs in `<folder>`"
- "rip figures out of my papers folder"
- "pull the figures out of this paper" *(one PDF is fine — see below)*
- "I dropped some new papers in Sources, can you pull the figures into Sources/Images?"
- mentions of an `Sources/Images/` or vault-style folder layout

**A single PDF is in scope.** Pass the `.pdf` itself as `--src` — `batch_extract.py` accepts a file as well as a directory — or drop to the lower-level scripts (*Setting a crop by hand*, below). There is no separate single-PDF skill to hand the request to, and routing a figures-only request anywhere else produces an artifact nobody asked for.

Four skills in this plugin fire on a PDF; the cue in the request decides:

| The user wants | Skill |
|---|---|
| figure images, from one PDF or many | **this skill** |
| to understand what the paper found, without reading it | `paper-summarizer` |
| interlinked wiki or glossary entries about its concepts | `wiki-builder` |
| the file renamed, or a book split into per-chapter PDFs | `pdf-organizer` |
| nothing in particular — a bare PDF with no stated goal, or "process this PDF / my sources / Sources/PDFs/" | ask which of the four; a PDF with no stated deliverable has no default here |

**Run `pdf-organizer` first — this skill now enforces it.** Every figure this skill writes is keyed to the PDF's on-disk stem, so renaming the source afterwards orphans the whole set under a stem nothing looks for, invisibly (`CONVENTIONS.md` §1a). `batch_extract.py` therefore **refuses** any PDF whose stem `pdf-organizer` has not produced, names the offending files, and tells the user to organize them first. It is the one stage positioned to catch this, because it is the first that writes a filename derived from another file's name. `--allow-unorganized` overrides the refusal for a deliberate one-off, and the message says what that costs.

## Quick start

Resolve `<skill>` and `<vault>` and check Python dependencies using
`shared/RUNTIME.md`. Reuse an available interpreter with PyMuPDF and Pillow,
or install `requirements.txt` in an isolated virtual environment. Use that
interpreter for the command below. Confirm paths only if the task has not
already established them.

```bash
python3 '<skill>/scripts/batch_extract.py' \
    --src '<vault>/Sources/PDFs' \
    --out '<vault>/Sources/Images'
```

**Vault layout** (shared with `wiki-builder`, `wiki-linter` and `clipping-processor`):

- **Vault root:** `<vault>` selected using `shared/RUNTIME.md`
- **Image folder:** `<vault>/Sources/Images/` — **flat**, shared with every other skill, and the home of every figure in the vault whatever produced it. This is `--out`.
- **Document folder:** `<vault>/Sources/PDFs/`, walked recursively — this is `--src`. It is the same tree `paper-summarizer` reads; the two produce different artifacts and don't conflict, and running this skill first is what puts figures on disk for that one to embed.
- **Not `<vault>/Inbox/`.** New files land there unorganized, and a figure keyed to `download (1)` is keyed to a name that is about to change — which is exactly what `batch_extract.py` refuses (*Run `pdf-organizer` first*). Organize first; the documents move to `Sources/PDFs/` on their way.

The script is idempotent — figures whose PNG already exists are skipped, so re-running after dropping new PDFs into Sources/PDFs/ just processes the new ones. Pass `--overwrite` to force re-extraction, or `--dry-run` to see what would be extracted without writing anything. `scripts/extract_figures.py` skips existing files the same way, for the same reason: both write into the same flat `Sources/Images/`, and the two must not silently undo each other's work.

**Read the summary before replying.** Two of its buckets describe failures that are invisible everywhere else in the pipeline — **PARTIAL detection** (the body text cites figure numbers no caption matched) and **byte-identical duplicates** (one figure written under two stems). Neither is an error; both are silent losses if you skip past them. See *Edge cases the summary surfaces*.

## Output naming

Each figure becomes a PNG named `[pdf_stem]_fig_<N>.png`, where `pdf_stem` is the source PDF's on-disk filename stem (exactly as it appears, `_src` suffix and all) and `<N>` is the figure label captured from the source caption, with dots normalized to dashes.

| Source caption                  | On-disk suffix    | Notes |
|---------------------------------|-------------------|-------|
| `Figure 7`                      | `_fig_7`          | |
| `Figure 1.2`                    | `_fig_1-2`        | dots → dashes |
| `Figure 1-2` (already dashed)   | `_fig_1-2`        | |
| `Figure 1–2` (en dash)          | `_fig_1-2`        | typeset science texts — Alberts *Essential Cell Biology*, most Norton/Pearson titles. Normalized to ASCII |
| `Figure 1.2.4`                  | `_fig_1-2-4`      | three-level |
| `Figure A.1`                    | `_fig_A-1`        | appendix |
| `Figure A1`                     | `_fig_A1`         | compact appendix |
| `Figure S1`                     | `_fig_S1`         | supplementary |
| `Figure S2-3`                   | `_fig_S2-3`       | |
| `Figure SI1`                    | `_fig_SI1`        | Supporting Info (distinct from S) |
| `Supplementary Figure 1`        | `_fig_S1`         | marker word folds to S |
| `Suppl. Figure 1`               | `_fig_S1`         | |
| `Supp. Figure 1`                | `_fig_S1`         | |
| `Supplementary Fig. 1`          | `_fig_S1`         | |
| `Extended Data Figure 1`        | `_fig_S1`         | default (`--ed-prefix S`) |
| `Extended Data Figure 1` *(with `--ed-prefix ED`)* | `_fig_ED1` | distinct ED namespace |
| `Figure 1: Title`               | `_fig_1`          | colon style — Nature, Cell, PNAS |
| `Figure 1—Title`                | `_fig_1`          | tight em-dash / en-dash |
| `FIGURE 1` / `FIG. 1`           | `_fig_1`          | older IEEE / some publishers |
| `figure 1` / `Supplementary figure 1` | `_fig_1` / `_fig_S1` | case-insensitive keyword and marker |

Caption styles the skill rejects: prose references (`Figure 1 shows...`, `figure 1 illustrates...`), panel pointers (`Figure 1a`, `Figure S1A`), and plurals (`Figures 1 and 2 show...`). These are body-text references, not the start of a caption.

**An en dash between two digits is part of the label; before a letter it is punctuation.** `Figure 1–14 Cells come in…` is figure 1-14, while `Figure 1–Title goes here` is figure 1 with an en-dash caption separator. The two readings are both live and the distinguisher is what follows the dash — a digit or not. This matters more than it sounds: a book that numbers `Figure 1–N` has *every* caption in it normalize to `_fig_1` under the other reading, so 42 of 43 figures are dropped as filename collisions and the run reports two extractions. An em dash is never a label separator (no publisher numbers with one), which is what keeps `Figure 1—2D convolution` reading as a title.

**This filename is a contract, not a preference.** Two other skills depend on it exactly as written:

- `wiki-builder` decides whether a source has figures at all by listing `Sources/Images/[source_stem]_fig*` (`references/media.md`), and embeds whatever it finds. A different stem and it finds nothing — every entry ships with no images, and its own unused-figure diagnostic stays silent because it walks the same pattern. The failure is total and raises nothing. **The separator is the one part with slack:** §8a requires consumers to match `[source_stem]_fig`, never the stricter `[source_stem]_fig_`, so a name missing the `_` after `fig` still resolves. That looseness is deliberate (§8c) — it is what made an earlier naming divergence cost half the figures instead of all of them — and tightening this glob is the bug, not the fix. The stem is what has no slack.
- `pdf-organizer` is what makes `pdf_stem` stable. It renames source files, and a rename *after* this skill has run leaves every PNG filed under the old stem — still on disk, invisible to every consumer, and reported by nothing. That is the ordering constraint in `CONVENTIONS.md` §1a, not a caution.

`clipping-processor` writes its downloaded clipping images to the matching `[note_stem]_fig_<N>.<ext>` shape for the same reason, and `paper-summarizer` reads this glob to decide which figures a summary note can embed — a figure written under a stem it does not expect is simply absent from the note, with nothing raised. If a naming change is ever genuinely needed, it has to land in all of them at once.

`Supplementary`, `Suppl.`, `Supp.`, and `Extended Data` markers all fold into the `S` namespace by default — they're functionally the same category (non-main-text figures) and unifying them keeps the on-disk naming predictable across publishers. For Nature-style papers that have both Supplementary Figure 1 AND Extended Data Figure 1 as distinct figures, pass `--ed-prefix ED` (see Flags below). The `SI` (Supporting Information) prefix is kept in its own namespace because it usually means something different from supplementary in journals that use it.

## Panels (splitting retired)

Panel splitting — writing one PNG per lettered panel (a, b, c...) beside the whole figure — was removed on 2026-08-16. This skill writes **whole figures only**; there is no per-panel output, no `--no-split-panels` flag, and no `panel_split.py`.

Letter-suffixed files from earlier runs (`Biswas_LowNProteinEng_2021_fig_1a.png` beside `..._fig_1.png`) remain valid vault content: the naming grammar is still reserved — a whole figure's label never ends in a lowercase letter, and `Figure 1a`-style captions are still rejected as panel pointers — so existing panels stay distinguishable from composites, and consumers keep reading them under `CONVENTIONS.md` §8b (embed the composite by default; never count an unplaced panel as an unused figure).

## Flags

`--src PATH` — source directory (walked recursively) **or a single `.pdf` file**. Required.
`--out DIR` — output directory for cropped PNGs. Required.
`--overwrite` — re-extract figures even if the target PNG already exists. Default: skip existing.
`--dry-run` — detect and report, but write nothing at all: no PNGs, no review ledger, not even the `--out` directory. Combined with `--mark-reviewed` it validates the `STEM:FIG` syntax and counts those bboxes as reviewed *for the preview*, printing `Would record` rather than `Recorded` — the mark itself lands only on a real run.
`--dpi N` — render resolution. Default: 250.
`--ed-prefix PREFIX` — filename prefix for `Extended Data Figure N` captions. Default: `S` (collapses into supplementary). Pass `ED` to keep them distinct.
`--keep-frame` — preserve the publisher's figure frame in the output PNG. By default, the skill detects O'Reilly-style line-stroke frames (4 strokes forming a closed rectangle around the figure) and crops just *inside* them so the frame doesn't appear in the output — most users want clean figures without the decorative chrome.
`--include-split-books` — also extract from a book PDF whose chapter PDFs are in the same run. Default: skip the book (see *Split books*).
`--allow-unorganized` — extract from PDFs whose filename `pdf-organizer` has not produced. Default: refuse them and name them, because every figure is keyed to the PDF's stem and a later rename orphans the whole set under a name nothing looks for.
`--mark-reviewed STEM:FIG` — record that a flagged bbox has been checked, so later runs stop asking about it. Repeatable. Appends to the review ledger and then runs normally.
`--review-file PATH` — where that ledger lives. Default: `.figure-review.txt` inside `--out`. A dotfile, so Obsidian hides it and it can never be mistaken for a figure.

`--ed-prefix` and `--keep-frame` are also accepted by `scripts/auto_fig_bbox.py`, so a single-PDF debugging run reproduces the batch run's labels and crops instead of silently falling back to the defaults. `auto_fig_bbox.py --coverage` adds the caption-count-versus-references check for one PDF.

## Subfolder behavior

Source paths are walked recursively, but **output is flat** — every PNG lands directly in the output directory. The `pdf_stem` in each filename disambiguates across subfolders. If two source PDFs share the same filename stem (which would cause their figures to overwrite each other), the run-end summary surfaces a collision warning so the user can rename one.

## Split books

`pdf-organizer` splits a book into per-chapter PDFs and **keeps both**: the whole book stays in `Sources/PDFs/`, the chapters go to `Sources/PDFs/<Work>/`. A recursive walk of `Sources/PDFs/` therefore finds the book *and* every chapter, and extracting from both writes every figure twice — once under the book's stem, once under the chapter's. The two names never collide, so nothing overwrites and nothing deduplicates; whichever stem an entry cites, the other copy sits in `Sources/Images/` unused forever, and no diagnostic can report it because the unused-figure check is per-source and only ever looks at one stem.

**The chapters win.** `batch_extract.py` detects the shape — a PDF in the run whose stem is `<another PDF's core stem>_NN_Name` — and skips the book, naming it in the summary. The rule is not restated here: `batch_extract.py` imports `looks_canonical()`, `chapter_book_stem()` and `core_stem()` from `shared/scripts/naming.py` — pdf-organizer imports the same module for the wider surface it needs — because this file used to carry its own copy and the two disagreed about where a `_src` tail sits (`CONVENTIONS.md` §1a). **"Core" matters:** a book and its chapters carry `_src` independently, so `Prince_UDL_2026_src.pdf` is correctly recognised as the book of `Prince_UDL_2026_01_Intro.pdf`. A `_2`/`_3` disambiguator is **not** the same kind of marker and is never stripped: it names a different document, so a disambiguated book matches no chapter here, and pdf-organizer refuses to split one at all (`CONVENTIONS.md` §1a).

- **When the chapters are in the same run**, the book's own stem gets **no** figures in `Sources/Images/` — that is the design. If an entry cites the whole book rather than a chapter, re-point it at the chapter, or run with `--include-split-books` and accept both copies. **The skip is run-scoped, so it is a property of how you scope `--src`, not a standing fact about the vault:** the book sits at the top of `Sources/PDFs/` and its chapters in the child folder `Sources/PDFs/<Work>/`, so `--src '<vault>/Sources/PDFs'` — the documented invocation — meets both in one walk and skips the book. Scoping *into* a chapter folder, or naming the book file directly, no longer sees the pair and extracts whatever it was given. Scope to `Sources/PDFs/` unless you mean otherwise.
- Pointing `--src` at the book PDF itself still extracts from it — an explicit request wins; the skip only applies when the chapters are in the same run.
- `--include-split-books` gets both, deliberately.
- Figures left under a book's stem by a run from before this rule are reported as stale duplicates, with the glob to delete. They are not removed automatically: nothing in this plugin deletes from `Sources/Images/`.
- As a backstop, any figure whose bytes are identical to one already written under a **different** stem is reported. That catches the same document reaching the source tree twice by some other route — the failure this class of bug always takes.

## Edge cases the summary surfaces

After processing, the script prints a summary that groups PDFs by outcome. Use this as the basis for your reply to the user — don't just say "done", call out anything that needs their attention:

- **Caption collisions** — two captions in the same PDF normalizing to the same filename. The most common cause is a paper that uses both `Figure S1` style AND `Supplementary Figure 1` style for the same figure (usually correct to collapse them), or that has both Supplementary and Extended Data figures numbered 1 (where the collapse is undesired). The first caption wins; later ones are dropped. The report shows the raw caption forms (e.g., "kept 'Figure S1', dropped 'Extended Data Figure 1'") so the user can decide whether to rerun with `--ed-prefix ED` (gives Extended Data its own namespace), manually rename one source figure, or accept the collapse.
- **Suspicious bboxes** — figures whose crop rectangle looks wrong. Four shapes are caught: one that is simply too small (a caption-only rect, a degenerate match), one that **covers only a fraction of the figure region between the previous caption and this one** — the signature of a crop whose top edge was raised by text sitting *inside* the figure — one that has reached up into the running head or a paragraph of body prose, and one that overlaps a caption (below). The PNG is still written; render the page and verify, or set a manual crop. Once you have checked one, record it with `--mark-reviewed '<stem>:<fig>'` — the summary prints the whole command, the selected interpreter and script path included, ready to paste — and it stops being flagged on later runs. Without that, a hand-fixed crop is re-flagged forever and the list becomes noise nobody reads.
- **Caption text in crop** — the crop overlaps a caption on that page: its own, or (more often) the neighbouring column's, whose caption block starts a few points higher than this one's. It is a subset of the suspicious bboxes by mechanism and its own bucket by meaning, because it is the one thing this skill promises its output never contains. Re-crop those by hand before anything embeds them.
- **Caption position ambiguous** — a flag, not a bucket, and the one to know about *before* you meet it. "Is this caption *beside* its figure or *below* it?" is not decidable from geometry alone: a caption alongside a tall figure and one crossed by the next column's chart are the same shape. The detector scores both readings and takes the better; when the other reading has a real claim too (*contested*) or when it took the *side* reading with little behind it (*thin*), it says so and prints both scores. The two wordings are different on purpose — they are different situations.

  **Expect it on papers with margin captions, and expect most of those crops to be fine.** Measured over 319 figures: the flag fires on roughly four in five *side*-caption figures, nearly all of them cropped correctly, and on no ordinary bottom-caption page at all. It is deliberately tuned that way — at the setting that flagged only "close calls", it caught nothing, while seven genuinely wrong crops went out silent. So on a margin-caption paper the flag means **"look"**, not "broken"; on a paper with ordinary captions under the figures, a flag here is unusual and worth taking seriously. Four earlier versions of this decision were made silently by a veto, and each veto discarded a different real layout without a word.
- **Blank crops** — the rect rendered nothing but white, so **nothing was written**. Its own bucket, and not counted as an extraction: the usual cause is a caption at the foot of a page whose figure is overleaf, where the search region above the caption holds no content and the fallback rect covers the empty gap. Every other check passes such a crop — it is big enough, has no region to be measured against, holds no running head and less prose than it is wide — so before this bucket existed it was written as a pure-white PNG and reported as a clean extraction. Render that page *and the next one* and set the crop by hand on whichever page the figure is actually on.
- **Occupied filenames** — the output name is already held by a file this extractor did not write. `Sources/Images/` is shared: `clipping-processor` writes `<slug>_fig_<N>.<ext>` there too (`CONVENTIONS.md` §8b), so a clipping whose slug equals a PDF's stem owns `<stem>_fig_1.png`. These figures are **neither extracted nor skipped** — reporting them as a skip would be indistinguishable from an ordinary idempotent re-run while the paper's real Figure 1 was never written and every consumer embedded the clipping's picture as it. Ownership is tracked in a `.figure-manifest.tsv` sidecar beside the review ledger, written from the digests the run already computes. The first run against a folder without a manifest adopts only legacy PNGs keyed to canonical PDFs in its `--src` scope and reports the adoption; unrelated clipping stems remain unclaimed. Use the full `Sources/PDFs/` tree for an initial migration so existing figures from other papers are included. All readable figure PNGs still participate in duplicate detection regardless of ownership.
- **PARTIAL detection** — the body text cites figure numbers no caption matched. The line is `<file>  <N> caption(s) found, <M> cited; no caption for: Fig 4`. **This is the one bucket with no other witness anywhere in the pipeline.** A PDF that yields 3 of 4 figures produces a smaller, entirely consistent set of files: `wiki-builder`'s `Sources/Images/[stem]_fig*` glob walks the 3 that exist, its unused-figure diagnostic walks the same 3, and neither has any idea a fourth was ever expected. Check the named pages by hand: a caption low in the text area of a tall page, a caption style the regex misses, and a figure that lives in another document all produce it. The signal is evidence, not proof — a paper legitimately cites figures from other works, and a book chapter cites figures in other chapters — but a genuine miss looks exactly like this and looks like nothing else.
- **Byte-identical duplicates** — the same pixels written twice. Under **two different stems** it means the same document is in the source tree twice (see *Split books*); this is not an overwrite and not a collision, the two names coexist, and the copy nothing cites is unused and unreportable forever. Under the **same stem** it means two captions got the same crop — side-by-side panels with a caption each is the usual cause, and those need a manual crop.
- **Failed to write** — figures that were *detected* but never reached disk: a crop rectangle that collapsed to zero area (the search region got squeezed to nothing), or a render error. These are called out separately because without them the "figures extracted" count silently disagrees with what is in `Sources/Images/`. Each needs a manual crop.
- **PDFs with no figure captions detected** — text-bearing PDFs where the caption regex matched nothing. Common when a paper uses a non-standard caption style (e.g., bold "Fig 1" with no period or trailing text), or really has no figures.
- **PDFs with no extractable text** — pure scans without an OCR layer. The script can't find captions in these. Recommend running `ocrmypdf '<input>.pdf' '<output>.pdf'` first (single-quoted: the paths are the user's, not ours — `CONVENTIONS.md` §1b), then re-running the skill. `ocrmypdf` is not preinstalled on macOS — if `command -v ocrmypdf` finds nothing, say so and name the install (`brew install ocrmypdf`, or `python3 -m pip install ocrmypdf` plus a Tesseract install) rather than reporting the file as unprocessable.
- **PDFs that could not be opened** — the file is not a readable PDF at all: a truncated download, an HTML error page saved with a `.pdf` extension, a corrupt file. **This is not an OCR problem** and is reported in its own bucket precisely so it doesn't get an `ocrmypdf` recommendation that cannot help. Tell the user which file it is and that it needs re-downloading.
- **PDFs with zero pages** — structurally valid but empty. Also not an OCR problem; also its own bucket.
- **Stem collisions** — two source PDFs producing the same filename stem (rare but happens with `paper.pdf` in two subfolders). The user should rename one before re-running. Worth surfacing prominently: because the output folder is flat, both write to **one** set of filenames. Under the default (no `--overwrite`) the **first** PDF processed wins and the second's figures are silently skipped as already-existing — so `wiki-builder` embeds the first source's images in entries for the **second**. With `--overwrite` the last one processed wins instead. Either way one source's entries get another source's pictures, and nothing downstream can tell.

## Setting a crop by hand

The detector handles the bulk of cases (single-column papers, framed figures, side captions, pages carrying a `/Rotate`), but it isn't perfect, and "not perfect" has meant *every figure in one paper* often enough that this is a normal part of the workflow, not an exotic fallback. Budget for it when a paper's layout is unusual, and work through the figures in one pass rather than one at a time.

**On a multi-column page, expect to re-crop.** Two things were fixed and one was not, and the one that was not is large.

- Fixed: a column-width caption is no longer mistaken for a caption sitting *beside* its figure. That misread built the whole crop out of the other column — one paper's Figure 1 came out as 26% of Figure 1, all of Figure 2, and Figure 2's caption text, silently. The two readings are **scored against each other** rather than one being vetoed, and a close call is flagged as *caption position ambiguous* instead of being decided in silence; on a two-column page it usually is close, so expect the flag there.
- Fixed: a crop that reaches a caption — its own or any other on the page — is reported in the *Caption text in crop* bucket instead of being written without comment.
- **Not fixed: a bottom caption's crop spans the full width of the page.** The search region for a caption below its figure runs from the left margin to the right one, so **a figure in the neighbouring column at the same height is inside the crop** — not a sliver of it, the whole thing. On a real two-column page one figure's PNG came out 1383px wide holding 100% of its own chart and 67% of its neighbour's. Narrowing that region to the caption's own column moves crops on ordinary single-column papers too, so it has not been done.

The *Caption text in crop* bucket catches the subset of these where the neighbour's **caption** also falls inside the crop — which happens when the neighbour's caption block starts above this one's, a few points of stagger being enough. When only the neighbour's **picture** is inside, nothing reports it. **So on a multi-column paper, look at the figures**; do not take a clean summary as evidence that the crops are right.

```bash
# 1. Inspect the auto-detected bboxes for a single PDF. Table view prints
#    the figure bbox, the caption rect, and the raw caption label for each.
#    Pass the same --ed-prefix / --keep-frame the batch run used.
#    --coverage adds "captions found vs. figure numbers the text cites".
python3 '<skill>/scripts/auto_fig_bbox.py' /path/to/paper.pdf --coverage

# 2. Render a problem page to a PNG to read coordinates off it (output → /tmp).
#    The output line states the px → pt factor for the DPI it used.
python3 '<skill>/scripts/render_page.py' /path/to/paper.pdf 5

# 3. Extract with a manual crop (PAGE:FIG_NUM:x0,y0,x1,y1), in POINTS.
#    --stem MUST be the PDF's on-disk filename stem, or the figure lands
#    under a name nothing else in the vault looks for.
python3 '<skill>/scripts/extract_figures.py' /path/to/paper.pdf \
    --out '<vault>/Sources/Images' \
    --stem paper \
    --crop "5:2:80,140,520,360"

# 4. Record that you have dealt with it, so the batch run stops flagging it:
python3 '<skill>/scripts/batch_extract.py' --src ... --out ... --mark-reviewed paper:2
```

**Two things bite every time, and neither raises an error.**

- **`render_page.py` gives you pixels; `extract_figures.py`'s `--crop` takes points.** Multiply by `72 / DPI` — **0.72** at the default 100 DPI. A US Letter page is 612×792 pt and 850×1100 px at 100 DPI. Skip the conversion and the crop lands ~39% too far right and too far down: a wrong picture, not an error message. `render_page.py` prints the factor on every render, and `--dpi 72` makes the two the same number.
- **`y1` must stay above the caption's `y0`,** or the caption text ends up in the PNG — the one thing this skill promises it never does. `auto_fig_bbox.py`'s table prints the caption rect next to every bbox for exactly this; use `y1 = cap_y0 - 0.5`. `extract_figures.py` warns by name when a crop reaches into a detected caption (`--no-caption-check` turns it off).

**Overwrite behaviour is the same in both scripts: existing PNGs are skipped, `--overwrite` replaces them.** They write into the same flat `Sources/Images/`, so a manual crop and a batch run would otherwise silently undo each other depending only on which ran last. When you *are* redoing a crop by hand, pass `--overwrite` — it will tell you it skipped otherwise.

When an ownership manifest exists, a manual crop updates its own digest so the
next batch recognizes the repair and leaves it intact. Both scripts refuse a
conflicting or untracked occupied name even with `--overwrite`; inspect that
file and reconcile its ownership first. A malformed manifest is a blocker,
not permission to reset it or claim every image. Manual cropping leaves a
legacy folder with no manifest in that state; the batch migration remains the
operation that reports and records its adoption of historical output matching
canonical PDFs in the requested source scope.

`auto_fig_bbox.py --emit extract --stem '<pdf_stem>'` prints the whole `extract_figures.py` invocation with one `--crop` per detected figure, ready to paste — the fastest way to fix a batch of bad crops without re-running the batch. It emits the current Python interpreter and the script's absolute path, so it runs from the vault root as printed; the one thing you must edit is `--out`, deliberately emitted as the placeholder `/EDIT-THIS/path/to/vault/Sources/Images` because this script cannot know your vault and a bare relative `Sources/Images` would silently resolve against whatever directory you pasted into. Edit the coordinates in place too, and add `--overwrite` if the batch already wrote those files. Figures whose bbox collapsed to zero area are left out of it (they would abort the batch) and counted on stderr.

## What the scripts do internally

- `scripts/auto_fig_bbox.py` — parses the PDF for text blocks matching the caption regex. Matches every common figure-caption form: `Figure N`, `Figure N.M`, `Figure N-M` (ASCII hyphen or en dash, normalized to a hyphen for the filename), `Figure N.M.K`, appendix (`Figure A.1`), supplementary (`Figure S1`, `Supplementary Figure 1`, `Suppl. Figure 1`, `Supp. Figure 1`, `Extended Data Figure 1`), Supporting Information (`Figure SI1`), case-insensitively on the keyword (`FIGURE 1`, `figure 1`, `Fig. 1`, `Fig 1`), and tolerant of several caption-shape conventions after the number (period+space, whitespace+capital, colon, em-dash, en-dash, end of line). Panel references (`Figure 1a`), prose references (`Figure 1 shows...`), and plurals (`Figures 1 and 2`) are deliberately rejected.

  A caption is found **wherever in the block it starts**, not only at the top. PyMuPDF merges a caption into one block with whatever sits a line above it — an axis label, a page-number strip, the tail of a paragraph — and all of those captions used to be invisible; a real 4-figure paper extracted 3, silently. The caption's rect is then its own lines, so the merged text above it stays inside the figure rather than being cropped away with the caption.

  Once a caption is matched, the function computes a bounding rectangle by unioning all vector drawings and raster images in the region above (or beside, for side captions) the caption. **Text inside the figure counts as figure content, not as a preceding block** — bar value labels, schematic box labels, legend entries, axis tick rows. Those are "the last text above the caption" by pure y-ordering, and raising the crop's top edge past one silently discards everything above it; a bar chart cropped to the bottom 45% is the usual result. They are told apart from prose above the figure geometrically: a block that starts below the figure's own drawings and fits inside their horizontal span belongs to the figure. When an explicit figure-frame rectangle is detected (four line strokes forming a closed rect — common in O'Reilly titles), the frame defines the figure extent precisely. The caption itself is excluded.

  **A vector path covering the whole sheet is the sheet, and is dropped before any of that runs.** Page-layout tools leave a background or bleed rectangle on every page — Alberts *Essential Cell Biology* draws one past all four trim edges of all 42 pages of a chapter. One of them poisons everything downstream in a way that never names its own cause: it touches every content cluster, so "the figure this caption belongs to" becomes the page, the union bbox becomes the page, and every crop comes back full-bleed carrying the neighbouring text column. What the user sees is a wall of *suspicious bbox* warnings saying "the top edge has reached into a paragraph" — a true statement about a symptom two layers from the cause. The rule is drawings only and both dimensions: a full-page **raster** is a legitimate full-bleed photograph and is kept.

  Page geometry is read per page, not assumed. The header/footer margins are relative to the page's own height (an absolute bottom bound tuned for US Letter cut 82pt off every A4 page, taking any caption low in an A4 text area with it), and a page carrying `/Rotate 90` is detected in its unrotated content space — where PyMuPDF reports text and drawings — with the finished rectangle mapped through the page's rotation matrix at the end, because that is the space `get_pixmap(clip=...)` reads.

  `--coverage` additionally reports the captions found against the figure numbers cited in the body text — the only cheap signal that detection was *partial* rather than complete. A hyphenated citation (`Figures 4-6`) is expanded as a range when both ends are integers, the span is short and ascending, and no caption in that document spells a label with a hyphen; in a book that numbers its figures `4-2`, the same string stays one label.
- `scripts/extract_figures.py` — renders each crop rectangle at 250 DPI via PyMuPDF, then runs a pixel-level white-margin trim with Pillow to clean up extra whitespace the bbox detector pads in for axis labels and panel letters that might not be present. Skips existing PNGs unless `--overwrite`, and warns when a crop rect reaches into a detected caption.
- `scripts/render_page.py` — renders a page to PNG for eyeballing, and states the px → pt factor for the DPI it used.
- `scripts/batch_extract.py` — walks the source tree, calls the above for each PDF, skips a book whose chapters are in the same run, handles idempotency, tracks byte-identical output across stems, honours the review ledger, and prints the summary report. It is the only script in `scripts/` that is unique to this skill.

**`auto_fig_bbox.py`, `extract_figures.py` and `render_page.py` are the only implementation of PDF figure cropping in this plugin, and there must not be a second one.** These three were once duplicated into another skill that wrote into the same `Sources/Images/` folder under the same filenames; the copies drifted, and one PDF then produced two differently-cropped images at names that never collided — every consumer matching the strict prefix saw half of them, and nothing raised. The duplicate is gone. If another skill ever needs these crops, it calls these scripts; it does not copy them (`CONVENTIONS.md` §8b, §8c).

## Why captions and frames are excluded

Two things in a typical PDF figure are decorative chrome rather than content: the caption text below (or beside) the figure, and the thin rectangular frame some publishers (O'Reilly, many technical books) draw around it. Both get excluded from the output by default.

The detector finds the caption rect first and computes the figure bbox to end strictly above (or beside) it, so the figure's own caption is excluded by construction. That is a property of one caption and one crop, not of the page: a crop spanning the width of a two-column page can still reach the bottom of the *neighbouring* column's caption, which starts a few points higher than this one's. So every finished crop is also checked against **every** caption found on its page, and one that overlaps any of them is reported in the *Caption text in crop* bucket instead of being written silently. When an explicit figure frame is detected (four line strokes forming a closed rect inside the figure search region), the bbox crops just *inside* the strokes by 2 PDF points — enough to clear the typical 0.5–1.5pt stroke without clipping inner content. Pass `--keep-frame` to invert this and crop just *outside* the frame instead, useful when the frame carries meaning (e.g., signaling that a figure is composed of multiple panels).

This is the inverse of "figure + caption + frame" extractors that include all three — useful when the figure is going into a personal knowledge vault where the surrounding markdown already references the figure by number and the frame would just be visual noise.
