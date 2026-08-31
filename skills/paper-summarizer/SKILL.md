---
name: paper-summarizer
description: 'Turn a scientific research PDF into a summary note in Articles/ that explains what the paper found without the reader opening it. Reads an organized PDF from Sources/PDFs/ and the figures in Sources/Images/, running pdf-figure-extractor first when figures are missing. One note per paper in a fixed shape: source-note YAML, a key-messages callout, then six sections - question, methods, results, interpretation, limitations, availability - each headed by a short sentence rather than a label. The note is self-contained: it embeds the figures that carry the argument, rebuilds the tables that are results, and never points at an exhibit the reader does not have. Pages are cited as superscript links. Every number is checked against the page it came from and the note is linted before it lands. Trigger on "summarise this paper", "what does this paper actually say", "explain this PDF", "summarise my papers", "write up the papers in Sources/PDFs". One PDF, or a folder.'
---

# Paper Summarizer

**Runtime setup:** Read [shared/RUNTIME.md](../../shared/RUNTIME.md) once per
task for vault selection, script paths, Python dependencies, and host tools.

**One research PDF in, one note in `Articles/` out.** The note's job is narrow and worth stating plainly: a reader who has not opened the paper should finish the note knowing what was asked, what was done, what was found, how much confidence the finding carries, and what would change their mind.

**That reader is a scientist from another field, and the note carries one result.** Both halves are constraints on the writing rather than notes about the audience: the vocabulary of this paper's subfield gets explained the first time it appears, the finding is stated plainly and qualified in the sentence after, and *Results* develops the paper's main result rather than touring all four. Step 7a is the whole of it, and two of its rules are checked mechanically. The PDF stays exactly where it is — this skill only reads it.

**The note is not the paper, and never pretends to be.** Downstream, the PDF is what counts: `wiki-builder` reads the PDF and cites it as `[[Foo.pdf#page=N]]`, an anchor no note can carry (`CONVENTIONS.md` §7). This note is a reading surface. It is an *end* of the pipeline, not a hand-off into the next one.

**The hard part is not writing the summary; it is not overstating it.** A summary of a paper is the one artifact in this vault whose failure mode is invisible: a claim widened by one word — a hedge dropped, a population generalised, a null read as an absence — is fluent, plausible, and wrong, and nothing downstream can detect it. This is measured, not feared. Peters & Chin-Yee (2025) found large language models broadened the scope of scientific findings in 26–73% of summaries **even when the prompt explicitly asked for accuracy**, at roughly five times the rate of the human-written summaries of the same papers, and newer models did it *more* than older ones. Ovelman (2024) found major result errors in 3 of 10 model-drafted plain-language summaries. So the guards in this skill are structural — a fixed hedge ladder, a mandatory scope clause, an absolute-numbers rule, and a verification pass run against the PDF *after* drafting, with a command whose exit code is the answer. Instructions to be careful are not among them, because that is the intervention already shown not to work.

## Vault layout

Unless told otherwise:

- **Vault root:** `<vault>` selected using `shared/RUNTIME.md`
- **Input:** `<vault>/Sources/PDFs/` walked recursively. Standalone papers under `Sources/PDFs/` are the work; the wider scan is deliberate, because a book is only recognisable as one when a chapter of it turns up in the same run (step 1). Book chapters under `Sources/PDFs/<Work>/` are found and then skipped, so scanning wide does not become a whole book's worth of summaries. A PDF named explicitly is processed wherever it lives, chapters included.
- **Output:** `<vault>/Articles/` — **flat, one `.md` per PDF, named after the PDF's stem.** `Sources/PDFs/Doe_GutMicrobiome_2025.pdf` → `Articles/Doe_GutMicrobiome_2025.md`. That shared stem is the whole of the pairing: it is the dedup key, the figure key, and what makes the embed resolve. Create the folder if it does not exist.
- **Figures:** `<vault>/Sources/Images/` (flat, shared). This skill **embeds** figures and never extracts, crops or renames one itself — that is `pdf-figure-extractor`'s job and there is exactly one implementation of it (`CONVENTIONS.md` §8b). The one time this folder gains a file during a run is step 1 invoking that skill, unmodified, to fill an empty inventory; everything after step 1 treats the folder as read-only.
- **Selection in batch mode:** every `.pdf` under `Sources/PDFs/`, minus the ones step 1 skips. A run that summarises 2 of 30 PDFs because the other 28 already have notes is the normal steady state.

If the user names a single PDF, process that one. If they say "summarise my papers" or name the folder, batch it in path-sorted order, one at a time, reporting once at the end.

## Where this sits in the pipeline

**Third, after `pdf-organizer` and `pdf-figure-extractor`, and both of those orderings are load-bearing rather than habitual.**

- **`pdf-organizer` first**, because this note's filename, the `sources:` wikilink inside it and every figure it embeds are all keyed to the PDF's on-disk stem, and a rename afterwards breaks all three at once with no error anywhere (`CONVENTIONS.md` §1a). Step 1 **refuses** a PDF whose stem `pdf-organizer` has not produced, exactly as `pdf-figure-extractor` does and for the same reason.
- **`pdf-figure-extractor` before this**, because this skill embeds only figures that are already on disk. Run it after, and the note ships figureless — no error, no diagnostic, just a summary of a visual paper with no pictures in it. **Step 1 runs it** when a paper cites figure numbers and the scan found no files for that stem, rather than reporting the gap and writing the note anyway: the figures have to exist before step 4 can choose among them, and adding one afterwards is a rewrite. That is the only skill this one invokes, and it invokes it at exactly one point in the run.

A PDF is the input to several skills here; the cue in the request decides which:

| The user wants | Skill |
|---|---|
| to understand a paper's findings without reading it | **this skill** |
| figure images out of it | `pdf-figure-extractor` |
| the file renamed, or a book split into per-chapter PDFs | `pdf-organizer` |
| interlinked wiki or glossary entries about its concepts | `wiki-builder` |

(A web page or Web Clipper capture is not a PDF and is `clipping-processor`'s.)

## How this package is laid out

This file is the spine: what each step decides and what it produces. **The rules every run needs are here** — the hedge ladder, the four claim rules, the section skeleton, the tag enum, the frontmatter. `references/` holds what is either long or genuinely conditional, and two of those are read on every run and say so outright rather than dressing themselves up as an "if" that never fails. Below, `<skill>` is the directory this SKILL.md sits in and `<plugin>` is the plugin root two levels above it (the folder holding `skills/` and `shared/`) — always give the scripts that full path, and always `python3` (macOS ships no `python` binary).

| Script | Does |
|---|---|
| `scripts/paper_scan.py` | one filesystem pass: which PDFs are in scope, which are done, which are refused, and what figures each stem already has (step 1) |
| `scripts/paper_text.py` | the paper by page, plus `--find` (which page a claim is on, exit 1 if none), `--cites` and `--sections` (steps 1, 2, 4 and 10) |
| `scripts/note_lint.py` | the finished note against the fixed format of step 11 — headings, callout, rules, embeds, rebuilt tables, citations, frontmatter shapes. Exit 1, one line per violation **sorted by line number**, and a final `N violation(s)` trailer; a clean note prints `<path>: clean` and exits 0 (step 11a) |

If a script cannot run, say so in the report and do that step by hand from the rules here — never from a plausible reconstruction of them.

---

## Workflow

### 1. Scan: what to summarise, and what pictures exist for it

**Decides:** the work list. **Produces:** a status and a figure inventory per PDF.

```bash
python3 '<skill>/scripts/paper_scan.py' \
    --src '<vault>/Sources/PDFs' \
    --notes '<vault>/Articles' \
    --images '<vault>/Sources/Images'
```

Single quotes on every path: they are the user's, not this file's (`CONVENTIONS.md` §1b).

**Point `--src` at the whole of `Sources/PDFs/`, not at a subfolder of it, and that is not a detail.** The book skip below is *run-scoped* — the script can only tell a book from a paper by finding one of its chapters in the same scan, and `pdf-organizer` puts chapters in `Sources/PDFs/<Work>/`. Scan below that level and a split book looks like an ordinary paper, gets summarised, and the summary has no figures because every figure was keyed to a chapter. The wide scan costs nothing, because chapters skip themselves.

**`--notes` is `Articles/`, which this skill shares with `clipping-processor`.** Its cleaned clippings sit in the same folder under the same `CONVENTIONS.md` §2b schema, and a clipping slug and a PDF stem can land on the same filename. That is what the `collision` status below exists for, and it is why the scan reads each existing note's `sources:` rather than just checking that a file is there.

Seven statuses, and that is the whole set:

- **`new`** — proceed to step 2.
- **`done`** — `Articles/<stem>.md` exists **and its `sources:` item 1 names this PDF**, so it is this skill's own earlier output. In batch mode skip it and record the skip. Named explicitly, ask whether to overwrite or skip, and wait — a rewrite discards whatever the user edited into the note, and nothing here can put it back.
- **`legacy`** — a note of that name exists, its `sources:` item 1 names this PDF, but its body is a bare `![[Name.pdf]]` embed rather than a summary. That is the light embed-note an older `clipping-processor` wrote for a PDF; those notes are still on disk in long-lived vaults and now share this folder. **Write nothing** — nothing here overwrites a user file (`CONVENTIONS.md` §1). Report the path and say that moving or renaming it lets the summary be written; do not offer to delete it.
- **`collision`** — a note of that name exists but its `sources:` item 1 names something else: a `clipping-processor` note whose slug matched, or a summary of a different PDF. **Write nothing.** Report both the note's path and its `sources:` item 1, and leave the resolution to the user — but say which way is cheap, because the two are not close. **Renaming the PDF through `pdf-organizer` is the repaired path**: `rename_all` carries the figures, any note about it and every `.md` reference in one pass, and refuses rather than overwriting. **Renaming the note by hand is the unrepaired one**: a clipping note's stem *is* the stem its own figures are filed under (`CONVENTIONS.md` §4c, §8), so a hand-rename orphans them, and every `[[Old.md]]` in a `sources:` list dangles with nothing reporting it (§7). Do **not** append `_2` to your own note to get out of the way either: the summary note's filename *is* its pairing with the PDF, and a `_2` note is paired with nothing.
- **`unorganized`** — a refusal: the stem is not one `pdf-organizer` produces. **Do not write a note.** Name the file and say that organizing it first is what keeps its note, its `sources:` link and its figures from being orphaned by a later rename. `--allow-unorganized` overrides this for a deliberate one-off; the report must say that it was used.
- **`book`** — a skip: a whole book whose chapters are in the same scan. The chapters are the unit, because `pdf-figure-extractor` extracts from the chapters only, so the book's own stem carries **no figures at all** and a note for it would be a figureless summary of something nobody reads end to end. Skip it, name the chapter folder, and offer the chapters instead. `--include-split-books` overrides the skip and summarises the book as well — the same flag, with the same name and the same meaning, that `pdf-figure-extractor` takes (its *Split books*); the report must say it was used, because the note it produces has no figures behind it. **The pairing is case-insensitive**, as the extractor's is: the documented vault sits on a case-insensitive volume, so `kuhn_x_2012_01_Intro.pdf` really is a chapter of `Kuhn_X_2012.pdf`, and the two skills must not disagree about which files are a book.
- **`chapter`** — a skip: a chapter of a split book. Real, summarisable, and skipped by a *folder sweep* only, because twenty-one chapter summaries is rarely what "summarise my papers" meant. Naming one processes it normally — and `--include-chapters` does the same for a whole sweep, which is how to ask for every chapter of a book at once. It is implied when `--src` names a single PDF, so an explicitly named chapter never needs it. Report the count and the folder so the user can ask.

**Read the figure count before writing anything, and act on a zero rather than reporting it.** A stem with no figures in `Sources/Images/` means `pdf-figure-extractor` has not run over this PDF, or ran before `pdf-organizer` renamed it. Tell the two possible causes apart with one command, and let the answer decide:

```bash
python3 '<skill>/scripts/paper_text.py' '<pdf path>' --cites
```

- **It lists figure numbers → the paper has figures and they were never extracted. Run `pdf-figure-extractor` now, before step 2**, over this PDF alone:

  ```bash
  python3 '<plugin>/skills/pdf-figure-extractor/scripts/batch_extract.py' \
      --src '<pdf path>' --out '<vault>/Sources/Images'
  ```

  Then **re-run `paper_scan.py`** so the figure inventory this run works from is the one now on disk. Read the extractor's own summary before continuing: its PARTIAL-detection and suspicious-bbox buckets are the only witness to a figure it missed or cropped wrong, and a bad crop is worth catching while nothing has been written yet. If the extractor refuses the PDF as unorganized, that is `pdf-organizer`'s job and it is the same refusal step 1 would have made — stop and say so.
- **It lists nothing → the paper genuinely has no figures** (a theory paper, a comment, a tables-only report). Write the note without embeds and say in the report which of the two happened, so a reader is not left wondering.

This is the one place this skill runs another skill, and the ordering is why: every embed is keyed to the PDF's stem, so the figures have to exist *before* step 4 chooses among them. Extracting afterwards is a rewrite. **Nothing else in the run may invoke the extractor** — once step 4 has chosen, a missing figure is reported and not fetched (`references/figures.md`).

### 2. Read the paper, by page

**Decides:** what the paper actually says. **Produces:** page-indexed text.

```bash
python3 '<skill>/scripts/paper_text.py' '<pdf path>' --sections
python3 '<skill>/scripts/paper_text.py' '<pdf path>' --pages
```

`--sections` first: it reports which physical pages hold the abstract, methods, results, limitations and data-availability statements. It also locates the funding, conflict-of-interest and ethics paragraphs — **this skill reports none of those** (step 7) — and the registration paragraph, which it does use: a preregistration identifier is methodological and belongs in *Methods*, and its absence from a design that should carry one belongs in *Limitations* (step 8, item 6).

**Page numbers here are physical** — the 1-indexed position in the file, what a viewer calls "page X of Y" — not the folio printed on the page (`CONVENTIONS.md` §7). A chapter PDF whose first printed page says 87 is page 1, and it is page 1 that a citation links to and displays.

**Read the results section and the actual figures, not the abstract.** An abstract is the authors' own most-favourable framing, written to be quoted; summarising it produces a summary of a summary, with every hedge already once removed. Where the abstract and the results disagree about an effect size, the results win and the disagreement is worth a line in the report.

If the PDF has no extractable text the script says so and stops — it is a scan. OCR it (`ocrmypdf '<in>.pdf' '<out>.pdf'`) or read it with the `pdf` skill, and never summarise a paper you could not read.

### 3. Extract the claim set, with the page each claim is on

**Decides:** every factual statement the note will make. **Produces:** a claim list, each with the page it is on.

Before any prose is written, list the paper's claims as bare assertions — the finding, the number, the population it holds for, and the physical page. This ordering is the point: a claim list built while drafting is shaped by the sentence it is going into, and a number written first is a number defended later.

**Four rules bind every claim, here and everywhere below.** They are not style preferences; each one is a specific way a summary goes wrong.

1. **Scope clause, always.** Every finding names the population, system or setting it holds for. "Improved survival in previously-treated adults with metastatic disease", not "improves survival". "In male mice at 8 weeks", not "in mice". This is the single most common failure mode measured in model-written summaries, and it is invisible after the fact because the widened sentence reads better than the true one.
2. **Absolute numbers beside every relative one.** "Cut the risk by 40% (from 5.0% to 3.0%)". A relative change alone is uninterpretable and reliably reads as larger than it is. If the paper gives only the relative figure, say that the absolute one is not reported.
3. **Name the comparator.** "Versus placebo", "versus standard care", "versus the 2019 baseline model". A comparative claim with no comparator is not a claim.
4. **A null result is not an absence.** "Did not detect a difference (95% CI −2.1 to +3.4, so a benefit up to 3.4 points is not ruled out)" — never "had no effect", never "was as good as", never "showed no difference". Absence of evidence is the thing being reported; absence of effect is a different claim that this study did not make.

**The four rules bind a claim, not a sentence.** Packing scope, comparator, absolute numbers and a hedge into one sentence is what produced the 60-word sentences this skill used to write, and a rule nobody can read is not a guard. Write the finding in a plain sentence, then qualify it in the next one — step 7a has the shape and the worked examples. What must never happen is a plain sentence with no qualifier after it: the pair is the unit, and half a pair is an overstatement.

**And every claim carries its confidence from a closed ladder.** Four rungs, no others. **The rung is a pair of sentences, not a word**: a plain statement of the result, then a statement of what the study does not show. A modal verb does not carry the constraint on its own — Haber et al. (2022) found that swapping a causal verb for an associational one does not stop a reader drawing a causal conclusion, which is why the rung is a sentence the reader cannot skim past (`references/summary-standards.md`).

| Rung | When | The second sentence |
|---|---|---|
| 1 | a randomised, controlled, adequately-powered experiment, or a preregistered replication | none needed beyond the scope: *"The trial shows that the transplant reduces recurrence."* |
| 2 | strong quasi-experimental design, or consistent evidence across designs, with the confounders addressed | *"The design is not randomised. Other causes are possible, and the authors tested for the known ones."* |
| 3 | a single observational study, a correlational finding, an underpowered or unregistered experiment | *"It does not show that exercise causes the difference."* |
| 4 | mechanistic, in-vitro, animal-only, simulation, a pilot, or a case series | *"The test was in cells only. The paper does not show an effect in people."* |

**Take the lower of two rungs: what the design supports, and what the authors themselves claim.** A paper that overstates its own observational data does not license the note to; a paper that calls its own result preliminary caps the note at rung 4 whatever its design. And **in-vitro, animal and simulation findings are about that system, full stop** — a cell-line result is a claim about cells, and the note says so rather than translating it into a claim about people. Peer-review status does **not** move a rung, and it is also not reported anywhere in this note (step 7): a preprint's design is its design, and the note describes that design rather than the venue.

**Three kinds of statement sit off the ladder entirely**, and forcing a rung onto any of them is what makes a note sound more certain than it is.

- A **null result** takes claim rule 4's sentence form, not a rung — the rung, if any, belongs to the claim the paper *does* make.
- A **non-evidential statement** — that a journal retracted the paper, that the authors call their own release low-risk — is *attributed*, not graded: say who said it.
- A **descriptive finding** — a typology, a mechanism participants named, an ethnographic account — is what **qualitative work** produces. It characterises and does not estimate, so there is no effect to grade. Write it as description, attributed, and make no frequency claim from it. The moment such a note says a finding *holds* of anything beyond the people studied, the ladder binds again, at rung 4.

Step 12's report says which of these applied when no rung was assigned, rather than leaving the rung line blank.

→ Read `references/summary-standards.md` **on every run, before drafting.** It holds the full rules behind this table — where each one comes from, the phrasings that fail, and the reporting-guideline checklists (CONSORT, STROBE, PRISMA, ARRIVE) that say what a study of a given design was supposed to disclose, which is what makes a *missing* disclosure visible.

### 4. Choose the exhibits — the figures, and the tables worth rebuilding

**Decides:** which two to four images and which tables the note carries. **Produces:** embeds and rebuilt tables, each with a caption.

**The note is self-contained, and that is a hard rule.** It never points at something the reader does not have. No "as Figure 2 shows", no "Table 5 reports the standard errors", no "see the supplement" — a reader of this note has the note, and a pointer into a document they are not reading is worse than silence, because it reads as a citation while carrying nothing. **Anything the argument needs is either in the note or is not mentioned.** `note_lint.py` rejects a figure or table number anywhere in the note, which catches the common form of this; the rest is yours.

**Saying what a rebuilt table leaves out is not a pointer, and is required.** "The 28 individual subtasks are in the paper" tells a reader what they are holding; "see Table 4" tells them to go somewhere. The difference is that the first names *no exhibit and no number* — it is a completeness disclosure about the note, not a reference into the source. A trim disclosure that names a figure or table number has crossed the line and the linter will say so.

That rule cuts both ways, and the second half is the one that costs work: **if an exhibit matters, put it in the note.** A figure is embedded. A table is *rebuilt* as a markdown table, because tables are not extracted to `Sources/Images/` and never will be — for a paper whose results are tabular, rebuilding one is not optional decoration, it is the only way its result reaches the reader at all.

#### Figures

Only figures step 1 found in `Sources/Images/` are eligible; never invent a filename, never re-extract, and never embed a figure whose file the scan did not list. `paper_text.py --cites` counts how often the body text refers to each figure number, which is a non-arbitrary tiebreak — a figure the paper leans on repeatedly is the figure carrying its argument.

**Cap it at four, and prefer two or three.** A note with every figure in it is the paper again. Take the ones that *are* the finding: the main result, the effect the abstract is about, the comparison. Skip study-flow diagrams, schematics and apparatus photos unless the method is itself the contribution.

**The scan lists whole figures and their individual panels, and the whole figure is the default.** A label ending in a lowercase letter is a panel — `..._fig_3a.png` beside the composite `..._fig_3.png` — and the scan marks each one with the figure it belongs to (`CONVENTIONS.md` §8b). Embed the composite unless the claim the exhibit sits under is one panel's alone and the rest of the plate is decoration under that sentence; then take the panel. Never both for one claim. **The cap counts embeds**, so three panels are three of the four, and an unplaced panel is not an unused figure. → `references/figures.md`

#### Tables

**Rebuild a table when it *is* a result the note claims** — the primary-outcome table, the benchmark comparison, the harms table. Rebuild none when the numbers fit in a sentence: two figures and a comparator belong in prose, not in a two-row table.

Five rules, and the third is the one that goes wrong:

1. **Markdown, in *Results*, with an italic caption on the very next line** — the same shape as a figure embed, for the same reason.
2. **Values verbatim.** Copy what the paper printed, digit for digit. Do not round, do not convert units, do not recompute a mean or a delta from the rows you kept — a recomputed number is a number the verification pass cannot find and the paper never claimed.
3. **Trim to what the claim needs, and say in the caption that you trimmed.** A 28-row benchmark table becomes the four group averages; a 12-column table becomes the three columns compared. A trimmed table that does not announce the trim is the most misleading object this note can contain, because it looks complete. Write *"the four task groups; the 28 individual subtasks are in the paper"* and the reader knows exactly what they are holding.
4. **Keep the paper's orientation.** If the paper puts the compared systems in columns, so does the rebuilt table; transposing it is a silent re-presentation of someone else's result, and a note carrying two tables under two orientations reads as two notes. Rename a row or column label for clarity where the paper's is cryptic — that is labelling, not data.
5. **Cap at four, prefer one or two**, and keep the total exhibit count — figures plus tables — to about five. Past that the note is the paper with fewer words.

```
| Tillage | Soil carbon, 0-30 cm (t/ha) |
|---|---|
| No-till | **48.1** |
| Conventional | 41.6 |
*No-till plots held about 6 t/ha more carbon after twelve years. Mean soil organic carbon at the final sampling, two of the four tillage regimes; the other two and the per-depth rows are in the paper.*
```

Each embed is a bare wikilink with an italic caption on the line directly below it, no blank line between:

```
![[Doe_GutMicrobiome_2025_fig_2.png]]
*The two arms separated inside the first fortnight and stayed apart to week 8. Kaplan–Meier curves for time to first recurrence, transplant against placebo, with the number of patients still at risk printed below each week.*
```

**No figure or table number, anywhere in the note.** Not `Figure 2 —` at the head of a caption, not "as Figure 2 shows" in the prose, not "Table 5 reports". Two reasons, and both are load-bearing. A number is a **pointer out of the note**, which the self-containment rule above forbids. And a figure number is a *second identity* for a file that drifts: the paper's `Figure 1.2` is `_fig_1-2` on disk, an `Extended Data Figure 1` is `_fig_S1`, and a caption spelling either one differently from the file is wrong in a way nothing else checks. The on-disk label still decides *which file* an embed names (`references/figures.md`); it just never reaches the prose.

#### Captions, for both

**One message per exhibit, and the message goes first** — the caption's first sentence says what the reader should take away, not what the axes or columns are; the second sentence says what they are looking at, and on a table says what was trimmed. A caption must stand alone: someone who reads only the exhibits and their captions should get the paper's argument.

→ Read `references/figures.md` when step 1's scan listed any figure for this stem, or when a table is worth rebuilding — the glob, the panel and supplementary cases, the table rules in full, what to do when the figure you want was not extracted, and the caption rules for both.

### 5. Assemble the frontmatter

The shared source-note schema, in this order (`CONVENTIONS.md` §2b — one schema for every note in this vault that is *about a document*, and this skill adopts it rather than inventing a second):

```yaml
---
title: <the paper's real title, from its first page>
format: <Paper|Book|Report>
sources:
  - "[[Doe_GutMicrobiome_2025.pdf]]"
  - "https://doi.org/10.1038/s41586-021-03819-2"   # the URL item only when the PDF prints a DOI or arXiv id; otherwise one item, never a blank second
author:
  - <Name>
published: 2025-01-03
created: 2026-08-10
description: <one factual sentence, 110 characters maximum>
tags:
  - "#biology"
read: false
---
```

Field by field:

- **`title`** — the title the first page states, not the filename. Unquoted unless it contains a colon or another YAML metacharacter.
- **`format`** — unquoted, exactly one of **`Paper`** (a standalone article or preprint — has an abstract and references), **`Book`** (a book or book chapter — the `_NN_ChapterName` pattern, or a first page saying "Chapter N"), **`Report`** (technical report, white paper, standards document, thesis). Unsure between `Paper` and `Report`: a formal abstract makes it `Paper`.
- **`sources`** — block-form list, every item double-quoted; **item 1 is the quoted wikilink to the PDF**, bare basename. `pdf-organizer` guarantees the basename is unique vault-wide, which is what makes the bare form safe (`CONVENTIONS.md` §1a). For a PDF that did not come through it, confirm with `find '<vault>' -name 'Doe_GutMicrobiome_2025.pdf'` (single-quoted — the basename is arbitrary text, §1b) and path-qualify the link if more than one comes back.
- **`sources` item 2** — the document's printed origin, and **normally absent**. Write it only when the document itself prints a DOI or an arXiv identifier, normalised to URL form (`arXiv:2401.01234` → `"https://arxiv.org/abs/2401.01234"`), double-quoted like every list item. **Never on `format: Book`** — a chapter has no per-chapter origin and an ISBN is not a URL. **Omit the item rather than writing it blank**, and never reconstruct a publisher page from the title. (The retired scalar `source` + `url` pair is this list's pre-rename shape.)
- **`author`** — block-form list, one entry per author, unquoted, no `[[…]]` wrapper. For a paper with more than about eight authors, the first three then a final `- et al.` entry.
- **`published`** — the publication date, **always `YYYY-MM-DD`, never a bare year**. Take every component the document actually prints, and **pad each one it does not with `01`**: a title page reading `3 Jan 2025` gives `2025-01-03`, one reading `March 2025` gives `2025-03-01`, one reading only `2025` gives `2025-01-01`. The padding is a placeholder and the note does not pretend otherwise — the full-date shape exists so the field sorts and filters as a date in Obsidian, which a bare year does not. **Do not go looking for the day elsewhere** (a publisher page, a DOI record); use what this PDF prints and pad the rest. Where the year itself is genuinely absent, that is `pdf-organizer`'s `nd` case and the filename already says so — there is no component to pad and none is invented, from the stem or from anywhere else. Stop for that note and surface the file in the run report: whether an undated document gets a summary is the user's call.
- **`created`** — today's date, `YYYY-MM-DD`.
- **`description`** — one factual sentence, **110 characters maximum**, stating the paper's main finding with its subject. Count before writing. Lead with the specifics: `Faecal transplant cut C. difficile recurrence from 45% to 8% in a 219-patient trial.` (84 chars) beats a vaguer sentence that fits more easily. **This field cannot carry a full scope clause and is the one place that is accepted** — 110 characters will not hold a population, a comparator and both absolute numbers. Fit what you can, prefer the numbers, and never let the *callout* inherit the compression: the first key message is where the scoped version of this claim has to be right.
- **`tags`** — one or more values from the 27-discipline enum (`CONVENTIONS.md` §3 is its one home): `mathematics`, `statistics`, `physics`, `chemistry`, `biology`, `earth-science`, `medicine`, `engineering`, `computer-science`, `psychology`, `sociology`, `anthropology`, `economics`, `finance`, `political-science`, `linguistics`, `history`, `philosophy`, `literature`, `law`, `business`, `entrepreneurship`, `education`, `architecture`, `art`, `music`, `machine-learning`. Tag where the paper's subject is *canonically classified*, not every field it touches. Block-form, `#`-prefixed, **double-quoted** — an unquoted `#` starts a YAML comment and the discipline vanishes silently. Never a wikilink.
- **`read`** — the bare boolean `false`, written once, at creation, and **last in the schema**. It is the user's review checkbox (`CONVENTIONS.md` §2d): they set it `true` when they have read the note, and nothing here ever writes `true`. Never quote it — `read: "false"` is a *string*, which Obsidian renders in a checkbox property as permanently ticked, so a quoted value marks the note read the moment it is written. On a rewrite, carry the existing value across unchanged.

### 6. Write the key messages

Immediately after the closing `---`, with no blank line between:

```
> [!Summary]
> - <message 1>
> - <message 2>
```

**Three to seven bullets, and the first one is the paper's central finding** — what the reader would tell someone else the paper showed. The rest carry the mechanism, the size of the effect, the main caveat. This is the part most readers will read instead of the note, so the caveat belongs *here*, not only in step 8.

- Each bullet is **one plain sentence, then its qualifier** — the shape of step 7a, in miniature. The qualifier carries the scope, the comparator and the numbers, and on a rung 2 to 4 claim it also carries the rung's limit sentence. A reader who reads only the callout must not be left with a result and no statement of what it does not show.
- Each bullet **stands alone**: no "It also showed…", no "This led to…". Bullets are read out of order in Obsidian's previews and search results.
- **State the claim, don't narrate the paper.** "Faecal transplant cut recurrence to 8%", not "The authors report that faecal transplant reduced recurrence."
- **Keep the technical terms exact** — organism, gene, drug, method, statistic. "Phase 3 trial", not "late-stage study"; "median overall survival of 13.2 months", not "about a year".
- **Bold the wiki-worthy nouns** with `**term**` — named methods, named organisms, named diseases, named models — the entities a later `wiki-builder` run would extract.
- **No URLs and no page citations.** The body carries those (step 9a).

### 7. Write the body

Six `##` sections, in this order, below a `___` rule — **always these six roles, always this order, and never one of these words as a heading.**

<!-- canonical:summary-note:roles -->
```
Question
Methods
Results
Interpretation
Limitations
Availability
```
<!-- /canonical -->

**The role is carried by position. The heading text is written for this paper.** Each `##` line is a **short sentence saying what that section actually found** — not a label naming what kind of section it is. A reader scanning Obsidian's outline pane should get the paper's argument from the six headings alone, without opening a single section.

The examples below are one fictional paper — a twelve-year tillage trial — carried through all six rows, so the set reads as one argument rather than six unrelated samples. **Do not reuse these words.** They are here to show the shape; a heading that would fit another paper is a heading that says nothing about this one.

| Role | A label, which this note never writes | A heading, which it does |
|---|---|---|
| Question | `## Question` | `## Nobody had measured no-till carbon past a decade` |
| Methods | `## Methods` | `## Twelve years of paired plots on one Iowa farm` |
| Results | `## Results` | `## No-till held 6 t/ha more carbon, all of it in the top 10 cm` |
| Interpretation | `## Interpretation` | `## Real storage, but shallower than the offset market assumes` |
| Limitations | `## Limitations` | `## One farm, one soil type, and no deep-core sampling` |
| Availability | `## Availability` | `## Plot data are public, the yield model is not` |

The rules a heading has to meet, all of them checked by `note_lint.py`:

- **A short sentence about *this* paper**, 20 to 90 characters, at least three words. Long enough to say something; short enough to read in an outline pane at a glance.
- **Sentence case, and no full stop.** A heading is a sentence in shape, not in punctuation.
- **Never a bare label.** `## Results`, `## Findings`, `## Background`, `## Discussion`, `## Data and code` and their kin are rejected outright, because falling back to the role name is exactly what a tired run does and it is invisible in a note that is otherwise well-formed.
- **The four claim rules bind here too** (step 3). A heading is the most-read line in its section and the easiest place for a hedge to go missing: `## Transplant cures recurrent C. difficile` is an overstatement that no amount of careful prose underneath repairs. Scope it, or write the finding narrowly enough that it does not need scoping.
- **No figure or table number**, as everywhere else in the note (step 4).

**Below, the six sections are named by their roles** — *Question*, *Methods*, *Results*, *Interpretation*, *Limitations*, *Availability*. That is what they **are**, not what they are **called**: this file, the reference files and the linter's messages all use the role name, and no note ever prints it.

- **Question** — the question, and why it was open. Usually one paragraph; take two where the field's state genuinely needs it. If the paper's stated aim and its actual analysis differ (an outcome switched, a hypothesis added after the fact), that belongs in *Limitations*, and the disagreement is worth naming here.
- **Methods** — **a short paragraph, then the experiment as numbered steps.** The paragraph names the design — randomised trial, cohort study, cross-sectional survey, retrospective chart review, mouse model, benchmark evaluation — because that is what sets the confidence rung in step 3 and a reader cannot infer it from the findings. The list then says what the researchers did, in the order they did it: **three to eight steps, simple past, active, one action each, 20 words at most**, with every number that belongs to a step inside that step. A paper with no procedure to walk through — a theory paper, a comment — takes the paragraph alone. Steps say what somebody already did, so they are descriptions in the simple past and never instructions to the reader.
- **Results** — **the paper's main result, developed until a reader from another field has actually got it**, and then whatever else changes how that result should be read. **This is where the exhibits go** — every figure embed and every rebuilt table, each one directly under the claim it supports, and nowhere else in the note. Cite the load-bearing numbers with a superscript page link (step 9a). Report **harms and negative results whenever benefits are reported** — a summary that carries only what worked is not a shorter version of the paper, it is a different one. **A secondary experiment gets one sentence**, or none: a second protein, a robustness check, a mechanism sub-study, each earns a line only where it qualifies the main finding, and the mechanism itself usually belongs in *Interpretation* rather than here. This section used to have no length cap, on the reasoning that a paper with four experiments gets four; what that produced was four results nobody read to the end of, and the cap in step 7a is the correction. A caveat attached to one number still belongs here beside it rather than in *Limitations* (step 8).
- **Interpretation** — the implication, and only as far as the design reaches. This section has one hard rule: **every sentence is either something the authors concluded, or is marked as not.** Where a reading is yours rather than theirs, write it as yours ("the authors do not say this, but…"). An unattributed inference here is indistinguishable from a finding.
- **Limitations** — step 8.
- **Availability** — step 9.

**The note stops at the science.** Who funded the work, what the authors declared, and whether a journal has refereed it are not written anywhere in this note — not in *Availability*, not in *Limitations*, not in the callout. That is a deliberate narrowing of an earlier, wider brief, and it is the user's standing instruction rather than a judgment about what matters. The one thing that survives from that material is **availability of the data and the code**, which is a fact about whether the result can be checked (step 9).

### 7a. Write it for a scientist from another field

**Decides:** whether the note can be read at all. **Produces:** the prose everything above is written in.

**The reader is a working scientist who does not work in this paper's field.** A chemist reading a genomics paper, a clinician reading a machine-learning one, the user six months from now in a subfield they have since left. They know what a control is, what a confidence interval means and what it costs to run an experiment. They do not know this field's vocabulary, its standard methods or what its numbers usually look like. Write for that person, and the specialist is still served; write for the specialist, and the note is closed to everyone else — which is most of the vault.

**The prose rules below are this vault's own.** They started life as a subset of a controlled-language standard for technical manuals; the standard and its approved-word dictionary are gone, and what stayed is the handful of rules that made the notes readable. Nothing here claims to follow a specification, and the report never says it does.

Five rules carry most of it, and two are checked by `note_lint.py`.

1. **Short sentences.** 25 words of prose, 20 in a numbered step. **(lint)** A longer sentence carries two claims, and the second one is the one nobody reads. The numbers are a house rule, not a standard, and they are what took this skill's longest sentence from 69 words to 24.
2. **Say it, then qualify it.** One plain sentence carrying the finding, then a short one carrying the scope, the comparator and the numbers. The pair, not the sentence, is what satisfies the four claim rules of step 3.

    | Fails | Holds |
    |---|---|
    | Fine-tuning a protein language model on sequences related to the target, then fitting a linear model on as few as 24 assayed mutants, likely raises the rate of better-than-wild-type designs well above the same pipeline run on a one-hot sequence encoding. | Twenty-four measured mutants were enough to design a better protein. About one design in ten beat the natural protein. The same pipeline without pre-training gave almost none. |

3. **Confidence is a sentence, not a word.** The rung from step 3 sets a second sentence saying what the study does not show. Prefer that pair to *likely*, *may* or *probably*: a modal verb is the first thing a skimming reader drops, and Haber et al. (2022) found it does not stop a causal reading anyway.
4. **Active voice, simple tenses, one topic per paragraph, six sentences at most.** **(lint on the paragraph.)** Simple past for what the researchers did; simple present for what is true now.
5. **Keep the field's term and gloss it once, in its own sentence.** *"Each design stayed within a trust radius of 15 mutations. No design differs from the natural protein by more than 15 changes."* The test: could a competent scientist in a **different** discipline write a one-line definition? If not, gloss it. Never gloss the same term twice.

**A number still needs its size named.** "A hazard ratio of 0.62" tells a reader outside the field nothing about whether that is a lot. Write what it means — "about a third fewer events" — then give the absolute figures, as step 3 requires.

**What none of this licenses.** Simplifying the wording is not simplifying the claim. Every guard in step 3 survives intact: the scope clause is still mandatory, it has just moved into the second sentence; the rung is still the lower of the design's and the authors'; a null is still not an absence. **If a sentence gets shorter because a qualification was dropped, that is the failure this whole skill is built to prevent**, and it is the one the verification pass in step 10 was written to catch.

### 8. Write the limitations

**Decides:** what would change how a reader acts on the finding. **Produces:** the shortest section in the note that is doing real work.

**Two to four bullets. Not five, not a checklist walk-through.** A limitations section that lists everything conceivable is one nobody reads to the end of, and the item that actually matters is buried in it — which is the same failure as omitting it. The bar for inclusion is one question:

> **Would a reader do something different if they knew this?**

Act differently, cite it differently, decide it does not apply to their case, wait for the replication. If the answer is no, it is not a limitation of this paper, it is a fact about research in general, and it does not go in.

**Consider all six of these; write only the ones that bite.** The sweep is how you find the caveat that matters — dropping the sweep is how you miss it. Writing all six out is what makes the section unreadable.

1. **What the design cannot show.** "This is an observational cohort, so it cannot separate the treatment's effect from the reasons people received it." Almost always makes the cut, and it is stated as its own sentence rather than smuggled into another as a qualifying clause.
2. **Who or what it was in**, and who it is therefore not about — one country, one hospital, one cell line, one benchmark, one six-month window.
3. **A proxy outcome** standing in for the thing anyone cares about: a biomarker for survival, a benchmark score for capability, self-report for behaviour.
4. **Precision** — a result resting on a wide interval, a small effect, a subgroup, or a post-hoc analysis.
5. **What the authors themselves list.** Include theirs when it bites; where it merely repeats something you have already written, fold it into that bullet rather than giving it its own.
6. **What is missing, methodologically** — the disclosure the design's reporting guideline asks for and the paper does not make: registration, blinding, attrition, sample-size justification, seeds, a contamination check. This is the one a reader could never notice on their own, so it clears the bar more often than the others. **Scope it to method**: those checklists also ask for funding, competing interests and ethics approval, which are out of scope for this note entirely (step 7).

**Three rules that keep it short without losing anything:**

- **Never write "this does not apply."** An item you considered and rejected is simply absent. Naming absences was an older rule here and it is what inflated this section; a reader cannot tell a considered-and-rejected item from an unconsidered one either way, so the line bought nothing and cost four.
- **A caveat about one number belongs beside that number**, in *Results* or in an exhibit caption — not here. *Limitations* is for what qualifies the paper, not what qualifies a row. **The two are not the same sentence at different volumes**: "the numbers in this table come from one run each" sits under that table, and "nothing in this paper's comparisons was controlled" is a *Limitations* bullet. Write the row-level one where the row is; write the paper-level one once, here; never write the same fact in both places.
- **Merge rather than enumerate.** Single runs, no seeds, mismatched fine-tuning protocols and copied baseline numbers are one limitation — the comparison is not controlled — not four.

**Do not soften and do not editorialise.** "The 12-week follow-up cannot speak to durability" is a limitation; "as with any study, more research is needed" is filler that displaces one. There is no evidence that stating limitations plainly costs a reader's interest, and the reverse is well documented — explicit caveats transmit uncertainty at no cost to engagement.

**The space this frees goes to the section that carries the finding.** *Results* is the longest section in the note and has the only length budget in it (step 7a) — spend that budget on the main result rather than on a caveat list. A note is allowed to be long where the paper is dense; it is not allowed to be long because *Limitations* was padded.

→ Read `references/summary-standards.md` for the per-design taxonomy: which limitations each study type is prone to, and which reporting checklist to hold it against. Use it to *find* candidates, then apply the bar above.

### 9. Write the availability

**Decides:** whether a reader could check the result themselves. **Produces:** the note's last section, and its shortest.

Three lines at most, each a `-` bullet, each either naming what is available or saying plainly that the paper does not state it:

- **Data** — where the data behind the results can be had, verbatim as the paper gives it (a repository name and accession, a URL, "available on request", "not stated"). Where a paper releases *some* of its data and not the rest — benchmark sets but not the training corpus, say — that distinction is the whole content of the line and is written out.
- **Code** — the same, for analysis code, training code or a model release.
- **Materials** — only where the paper offers something that is neither: model weights, a reagent, a protocol, a trained artifact. Omit the line entirely when there is nothing of the kind; this is the one bullet that may be absent.

Nothing else goes in this section. **Funding, competing interests, peer-review status and ethics approval are not written in this note at all** (step 7) — not here under another name, not folded into a *Limitations* bullet, and not as an aside in *Interpretation*.

**Preregistration is the one that looks like governance and is not.** Whether the primary outcome was pre-specified changes how the result should be read, so it is methodological and it stays: name it in *Methods* where the paper has one (with its identifier), and in *Limitations* item 6 where a design that should carry one does not. It does not get an *Availability* line.

**Say "not stated" rather than dropping a line.** A section that lists code and is silent on data reads as a paper that released both, and the reader has no way to tell the silence from the absence.

#### 9a. Citations

A citation is a **superscript inline link whose display text is the page number** — the whole of it, with no list anywhere in the note:

```
…enrolled 219 of a planned 220.<sup>[[Doe_GutMicrobiome_2025.pdf#page=3|3]]</sup>
```

which renders as `…enrolled 219 of a planned 220.`³ — the filename hidden, the digit raised, the click opening page 3 of the PDF.

- **`<sup>…</sup>` around the link, nothing between the tags and the brackets.** Obsidian renders `<sup>` natively, with no plugin. An unwrapped link is full-size text in the middle of a sentence, which is what the superscript exists to avoid.
- **The alias is the page number, digits only**, and it must equal the `#page=N` it points at. `note_lint.py` compares the two, because an alias that has drifted from its target is a citation that silently sends the reader to the wrong page.
- **It attaches to the character before it, with no space** — after the closing full stop, the way a numeric citation style sets it. A space renders as a floating digit.
- **The link must name this note's own PDF.** In a batch run the previous note's citation is one paste away, and it resolves perfectly well — into the wrong paper. The linter compares every target against `sources:` item 1.
- `N` is the **physical** page (step 2), not the printed folio.
- **No list at the bottom of the note.** There is nothing to keep in sync and nothing to renumber when a paragraph moves. Footnote syntax (`[^1]` and a definition block) is **not** used here and the linter rejects it.
- **Body prose only.** Not in the `> [!Summary]` callout (step 6), not inside a figure or table caption, not in the frontmatter.
- **Cite the load-bearing numbers, not every sentence** — the design, the primary result, the harms, a null, the authors' own limitations, the availability line. Repeating the same page in three consecutive sentences is noise; one citation covers the passage.
- **The page comes from step 3, not step 10.** Step 3 recorded the page each claim is on, which is what a citation is written from as the draft is written. Step 10 runs *after* the draft and re-checks those pages against the PDF; a page it corrects is a citation to correct too. Nothing here waits on step 10.

### 10. Verify against the PDF

**Decides:** whether every claim in the draft is actually in the paper. **Produces:** corrections, cuts, and a verdict line.

**This is a separate pass, run after drafting and against the source — not a re-read of your own draft.** The failure it catches is not carelessness; it is the measured tendency of a fluent summary to drift wider than its source, which re-reading the summary cannot surface because the summary is self-consistent.

Take every number, every proper noun and every scope clause out of the draft and put them through the finder in one command:

```bash
python3 '<skill>/scripts/paper_text.py' '<pdf path>' \
    --find '13.2 months' --find '0.62' --find 'previously treated'
```

Single-quoted, because the needles come off the paper (`CONVENTIONS.md` §1b). It exits **1** if any needle is unfound, and prints the page for each one that is. A `MISSING` line means the claim is **cut or corrected — never softened into something vaguer that survives**. A `loose` line matched only after spacing and hyphens were stripped: open that page and read it before citing it.

**Feed it the paper's own tokens, kept short.** `'0.62'`, `'13.2 months'`, `'C57BL/6'` — not a phrase you reassembled. The finder is a substring search, so a reconstructed `'hazard ratio 0.62'` misses a paper that wrote "a hazard ratio of 0.62", and that miss is a fact about your phrasing rather than about the claim. Re-run a `MISSING` needle once in the source's own wording before concluding the number is not there; if it is still missing, it is not there.

**Two things this pass cannot catch, and a clean result must not be read as covering them.** The finder is a substring search, so **widening a claim removes no token**: drop the population from "cut recurrence in adults with two prior recurrences" and every needle still verifies, exit 0. And a `FOUND` page is where the *string* is, not where the *finding* is — a number the paper quotes from someone else's study, or prints in its introduction, verifies exactly like its own result. So: **put each scope clause through the finder as its own needle**, and **open every page before it becomes a citation** and confirm the number there is this paper's result rather than its summary of prior work. `--sections` gives the page range the results occupy; a load-bearing number found only outside it is the case to look at hardest.

→ Read `references/review-checklist.md` **every time you reach this step.** It is the accumulated list of what has slipped through before, and it stays a separate file for length, not for conditionality.

### 11. Write the note

**The shape is fixed, and it is fixed so that every note in `Articles/` reads the same way.** This is the whole of it — nothing here is a default to be improved on for a particular paper:

```
---
<frontmatter from step 5, the nine keys of CONVENTIONS.md §2b in order>
---
> [!Summary]
> - <key message 1>
> - <key message 2>

___

## <a short sentence: the question, and why it was open>

<prose>

## <a short sentence: what kind of study, and how big>

<prose>

## <a short sentence: what it found>

<prose, figures, rebuilt tables, superscript page citations>

## <a short sentence: what that means, as far as the design reaches>

<prose>

## <a short sentence: the caveat that bites hardest>

- **<item 1>.** <prose>
- **<item 2>.** <prose>

## <a short sentence: what is available and what is not>

- **Data.** <prose>
- **Code.** <prose>
```

The rules that shape is made of, each one mechanically checkable and each one checked (step 11a):

1. The file opens with `---` on line 1. No blank line, no BOM, nothing above it.
2. The nine frontmatter keys in `CONVENTIONS.md` §2b order, the `sources` URL item optionally absent, nothing added and nothing reordered.
3. `> [!Summary]` on the line **immediately** after the closing `---` — no blank line between them, so the top of the note is flush.
4. The callout is `> - ` bullets only: three to seven of them, one line each, no nested bullets and no continuation lines.
5. One blank line, then `___` alone on its line, then one blank line. **Exactly one `___` in the note**, and no other horizontal rule of any spelling (`---`, `***`, `- - -`) below the frontmatter.
6. Six `##` sections, in the role order of step 7, each headed by a short sentence about this paper rather than by a role name, with a blank line above and below each. No `#` heading, no `###` subheading, none added, none dropped.
7. Every section has prose in it. *Limitations* and *Availability* are `-` bullet lists. *Methods* is a paragraph and then a numbered list of three to eight steps, or the paragraph alone where the paper has no procedure. The other three are paragraphs. *Limitations* holds **two to four** bullets — only what would change how a reader acts (step 8) — and *Availability* one to three (step 9). The four prose sections have no cap at all.
8. Each figure is a bare `![[…]]` embed, and each rebuilt table a markdown table, with an italic caption on the very next line, no blank line between, and no figure or table number anywhere (step 4). Four embeds and four tables at most, all of them inside *Results*.
9. Page citations are superscript inline links whose display text is the page number, `<sup>[[<stem>.pdf#page=5|5]]</sup>`, attached to the preceding character with no space, in body prose only — never in the callout, a caption or the frontmatter, and never as a footnote. The alias matches the page it opens and the target names this note's own PDF.
10. No figure or table number anywhere: not in a caption, not in the prose. If an exhibit matters it is in the note (step 4).
11. The note's last section is *Availability*, and the file ends with a single newline. There is no reference list, no appendix and no trailing block of any kind.
12. No sentence below the frontmatter runs over 25 words, or over 20 inside a numbered step — callout bullets and exhibit captions included. No paragraph holds more than six sentences (step 7a).
13. *Results* holds at most 2,400 characters of prose. Embeds, captions and rebuilt tables do not count toward it: an exhibit is how a result gets shorter (step 7).

Write to `<vault>/Articles/<pdf stem>.md`. **The PDF is not moved, renamed, copied or deleted** — there is no cleanup phase in this pipeline at all. Nothing else in the vault is written either: no figure, no attachment, no wiki entry.

If the note already exists and the user asked for a rewrite, read `read:` off the existing file first and write it back unchanged (step 5) — the summary and the frontmatter are regenerated, that field deliberately is not.

### 11a. Lint the note before it lands

**Draft to a scratch path outside the vault** — `/tmp/<stem>.md` is fine, and anywhere under `Articles/` is not, because a half-written note in that folder is one the next scan reads as this skill's own output. **Run the linter on the draft, every run, and fix what it reports before the file reaches `Articles/`:**

```bash
python3 '<skill>/scripts/note_lint.py' '<path to the drafted note>'
```

It checks the thirteen rules above — the sentence caps and the paragraph limit among them — plus the frontmatter's value shapes — `published` a full `YYYY-MM-DD`, `description` within 110 characters, `tags` double-quoted and inside the §3 enum, `read` a bare `false` — and exits **1** with one line per violation. Pass `--images '<vault>/Sources/Images'` and it also confirms every embed names a file that exists, which is the one failure Obsidian renders as ordinary text with no error of any kind.

This exists because prose cannot hold a format steady across notes written weeks apart: the shape above has drifted before in every direction it can — an extra heading, a blank line above the callout, a quoted `read`, a caption pushed one line down — and each drift is invisible in the note that has it. The linter is what makes the format a fact rather than an intention. **A note that has not been linted is not finished**, and step 12 reports the result either way.

### 12. Report

- The note path, and the PDF it came from.
- **`format`, `tags`, and the hedge rung** the note settled on, with one line on why — the rung is the single most consequential judgment in the run and the easiest for the user to check.
- **Figures embedded**, by filename, and **figures available but not used**, by count — **whole figures only**, since a panel nobody placed is not an unused figure (step 4). Where panels were on disk, say how many files the count came from, so a reader of the report can tell 4 unused exhibits from 27 unused files. If the stem had none at all, say so and name `pdf-figure-extractor`. **Tables rebuilt**, and for each one whether it was trimmed and to what.
- **Verification results** — how many needles were checked, how many were found, and every claim that was **cut or corrected** because it was not in the paper. If nothing was cut, say "verification: all N claims located" so the user knows the pass ran.
- **The lint result** (step 11a) — `note_lint.py` clean, or what it reported and what was fixed. A run that did not lint says so.
- **Whether `pdf-figure-extractor` was run** as part of this run (step 1), and if it was, what its own summary flagged.
- **Anything the paper did not state** that the note needed — an unstated data or code location, an absent methodological disclosure. Funding, competing interests and peer-review status are out of scope and are not reported as gaps.
- **Low-confidence calls** — a title built from the filename, an ambiguous design, an effect size the abstract and results disagreed about, a `published` date whose month or day was padded.
- In **batch mode**, lead with the counts (`N summarised, M already done, K skipped, J refused`), give per-file detail for everything summarised, refused or anomalous, and collapse the ordinary already-done skips to a count plus filenames.

---

## Reference files

Read one when its condition holds. Every condition is checkable before you open the file — a step number, a script's verdict, a count. Two of them hold on every run and say so outright.

- `references/summary-standards.md` — **read every run, before drafting (step 3).** The full claim rules behind the four in step 3 and the ladder above them, the per-design limitations taxonomy step 8 points at, and the reporting checklists that make a *missing* disclosure visible. It stays separate for length.
- `references/figures.md` — step 1's scan listed at least one figure for this stem, **or** the paper's result is a table (step 4). A tables-only paper with no figures at all still needs this file, for the rebuilt-table rules.
- `references/review-checklist.md` — **step 10, which every note reaches: read every run.** The trigger is the step number, not a circumstance.
- `references/edge-cases.md` — any one of these, each checkable before acting: the paper is a preprint, a systematic review or meta-analysis, a modelling or simulation study, a machine-learning benchmark paper, a case report or case series, or qualitative work; it has no abstract, no methods section, or no figures at all; it is a retraction, a correction, or a comment on another paper; it is not in English; the PDF is a scan with no text layer; the figure the argument needs was not extracted; the paper has more than about eight authors; two PDFs in the batch are the same paper.
- `references/worked-example.md` — before the first note of a session, for the whole output shape in one piece.

---

## What this skill does not do

- **Crop, rename or re-implement a figure.** It embeds what is in `Sources/Images/`, and where that is empty for a paper that has figures, step 1 runs `pdf-figure-extractor` — the one implementation — rather than doing any of it here. A second copy of PDF figure cropping is the bug the shared layer exists to prevent (`CONVENTIONS.md` §8b), and calling the other skill is how this one stays on the right side of that.
- **Rename or move the PDF.** That is `pdf-organizer`'s job and it belongs *before* this stage — a rename after this note exists breaks the `sources:` link, the figure embeds and the note's own pairing at once, and nothing here detects any of it (`CONVENTIONS.md` §1a).
- **Write wiki entries.** Extracting entities is `wiki-builder`'s, and it consumes the **PDF**, not this note: it cites `[[Foo.pdf#page=N]]`, and a note has no pages. Where a wiki entry ends up citing both `Foo.pdf` and this note, the `.pdf` is kept and the `.md` dropped (`CONVENTIONS.md` §7).
- **Process a web clipping.** A `.md` from `Inbox/` is `clipping-processor`'s.
- **Delete anything.** No PDF, no figure, no existing note. The only file this skill ever writes is its own note in `Articles/`.
- **Reproduce the paper.** The note is a summary with its confidence attached, not a replacement for reading the source — and where the finding matters to the reader, the note should make it easy to open the PDF at the right page rather than easy to skip it.
