# obsidian

Turn papers, book chapters and web clippings into a maintained Obsidian
knowledge base. Six skills cover the path from a PDF or a Web Clipper capture
to interlinked wiki entries, and then keep the vault linted and navigable.

They are separate skills because they fire at different moments, but they write
into **one vault under one set of conventions** — stated once in
[`shared/CONVENTIONS.md`](shared/CONVENTIONS.md).

## The pipeline

Everything new lands in `Inbox/`, and **the file extension is the fork**:

```
                              Inbox/
        ┌───────────────────────┼───────────────────────┐
   a .md capture              a .pdf            anything else
        │                       │               (.epub, .docx …)
        ▼                       ▼                       │
 clipping-processor        pdf-organizer                ✗
        │                       │              no skill files these;
        ▼                       ▼              they are named in the
 Articles/*.md          Sources/PDFs/          report and left alone
 (the raw stays          Author_Title_Year.pdf
  in Inbox)              (the file MOVES out of Inbox; a book is
        │                 also split into Sources/PDFs/<Work>/)
        │                       │
        │                       ▼
        │                pdf-figure-extractor ──▶ Sources/Images/*.png
        │                       │
        │                       ▼
        │                paper-summarizer ──▶ Articles/*.md  ✗ end
        │                       │             (what the paper found,
        │                       │              with its key figures)
        │                       │  (the PDF, not the summary)
        └───────────┬───────────┘
                    ▼
          wiki-builder ──▶ Wiki/*.md (one entry per entity)
                    │
                    ▼
          wiki-linter ──▶ links, parents:, MOCs
```

Each stage is usable on its own; nothing forces you through all six. Figures
land in `Sources/Images/` whether or not you ever summarise the PDF; a clipping
note is readable whether or not you ever extract entities from it.

**`Inbox/` drains for PDFs and accumulates for clippings.** pdf-organizer moves
a PDF out, because that file *is* the document and needs a permanent home.
clipping-processor never moves the raw: the polished note is a second copy of
the content, and the raw is the only record of what the clipper actually
grabbed. So already-processed `.md` files piling up in `Inbox/` is the normal
state, and "is this one done?" is answered by the dedup index, not by where the
file sits. A document that is neither — an `.epub`, a `.docx` — has no skill
here that files it; both inbox skills name what they left and why, rather than
letting a folder that is still not empty read as a failure.

**The two note-writing skills are siblings, not stages**, and they share an
output folder: `paper-summarizer` takes a research PDF from `Sources/PDFs/` and
`clipping-processor` takes a Web Clipper capture from `Inbox/`, and both write
into `Articles/`. Each **reads** the other's output, and has to: that is what
stops one overwriting the other in a folder they share. What tells the two note
kinds apart is `sources:` item 1 — a URL means the note *is* the source, a
`[[Name.pdf]]` wikilink means the PDF is. `wiki-builder` branches on exactly
that: it consumes cleaned clippings and the **PDFs**, never a summary note,
which is a restatement of the paper rather than the paper.

**But the first stage's position is a constraint, not a habit.** Everything
downstream keys to a source's on-disk filename — `wiki-builder` writes
`sources: "[[Name.pdf#page=N]]"`, `pdf-figure-extractor` names every figure
after the PDF's stem, `paper-summarizer` names its note after it and links it
as `sources:` item 1, `"[[name.pdf]]"` — so renaming
a source *after* those have run breaks references that **nothing in this plugin
detects**: the orphan audits deliberately skip `sources:`, and Obsidian renders
an unresolved link as ordinary text. Organize first. `CONVENTIONS.md` §1a states
the contract and what it costs to ignore.

**Every stage but the last is per-document. `wiki-linter` is the only
whole-vault pass** — that split is deliberate, and it is what stops two skills
from adding and pruning the same marginal link on alternating runs
(`CONVENTIONS.md` §9).

## The skills

| Skill | Fires when |
|---|---|
| **pdf-organizer** | a PDF needs a usable name and a home — "rename this PDF", "organize my papers", "process my inbox", "clean up these filenames", "split this book into chapters", or any `download(1).pdf`. It is what moves PDFs out of `Inbox/`, and it handles PDFs only |
| **pdf-figure-extractor** | you want figures out of PDFs — one paper or a whole folder — "extract the figures from my papers folder", "populate Sources/Images from Sources/PDFs" |
| **paper-summarizer** | you want to know what a research paper found without reading it — "summarise this paper", "what does this paper actually say", "write up the papers in Sources/PDFs" |
| **clipping-processor** | a Web Clipper capture needs cleaning up — "process my clippings", "clean up my Web Clipper captures". On an inbox-wide request it takes the `.md` captures and pdf-organizer takes the PDFs |
| **wiki-builder** | a source should become wiki entries — "make wiki entries from this PDF", "add this paper's concepts to my wiki", "build a glossary" |
| **wiki-linter** | the vault itself needs work, with no new source — "lint my wiki", "backfill the links", "rebuild the MOCs", "update the parents" |

The line between the PDF skills is *what you get out*: file names and chapter
files → pdf-organizer; figure images → pdf-figure-extractor; an explanation of
the findings → paper-summarizer; wiki entries about its concepts →
wiki-builder. A bare PDF with no stated goal has no default — ask. The line
between the two wiki skills is *reach*: a new source → wiki-builder; the
existing vault → wiki-linter.

## Vault layout

The default root is `/Users/dennisgrishin/Downloads/claude-main`; any skill
takes a per-request override.

```
<vault>/
├── Inbox/                    everything new — clippings (.md) and documents alike
│                             the extension decides which skill takes it
├── Articles/                 notes ABOUT a document — cleaned clippings and
│                             paper summaries, told apart by sources: item 1
├── Sources/
│   ├── PDFs/                 organized documents; pdf-organizer moves them here
│   │   └── <Work>/           book chapters, e.g. Sources/PDFs/Prince_UDL_2026/
│   │                         — pdf-organizer makes these when it splits a book
│   └── Images/               flat — every figure and downloaded image
├── Wiki/                     wiki entries, one .md per entity
├── <discipline>-moc.md       one map-of-content per discipline tag
└── *-suggestions.md          wiki-linter's three propose-only backlogs
```

MOCs and the suggestion logs live in the **vault root, not `Wiki/`** — that is
what keeps them out of the lint. Full table, with which skill writes and reads
each folder, in `CONVENTIONS.md` §1. A vault that has been in use a while may
also hold notes at the root that nothing here writes any more; they are the
user's files and are left alone.

**Nothing here deletes a user file.** Raw clippings, PDFs and images are
inputs; the only file any skill removes is a note it wrote itself, when a
reprocess renames it. pdf-organizer is the one skill that *renames and moves* a
user file — that is its whole job, it never overwrites (`_2`, `_3`, … on a
collision), it moves only inside the vault, and it is why it runs first.

## The shared layer

`shared/` holds the facts that more than one skill depends on, so they have one
home instead of five:

- **`shared/CONVENTIONS.md`** — the authority. Vault layout, the frontmatter
  schemas, the 27-value discipline-tag enum, slugs and filenames, wikilink
  forms, source references, figure naming, and the linking ownership split. Each
  section names the skills that depend on it, so an edit's blast radius is
  visible before you make it.
- **`shared/scripts/slugify.py`** — the canonical title → filename slug
  algorithm, with a 53-case self-test (`slugify.py --test`).
- **`shared/scripts/plugin_paths.py`** — how a skill script reaches
  `shared/scripts/` whether the plugin is installed whole or the skill was
  extracted alone (`CONVENTIONS.md` §5).
- **`shared/scripts/naming.py`** — the source-filename rule: what a renamed
  source is called, which stems are chapters of which book, and which marker at
  the end of a stem comes off before the two are compared (`CONVENTIONS.md` §1a).
  Imported by pdf-organizer, pdf-figure-extractor and paper-summarizer; the
  first two used to hold copies that disagreed in both directions at once.
- **`shared/scripts/plurals.py`** — the one English singulariser, so the
  duplicate-entry probes agree about which two word forms are the same word.
  Its two former copies disagreed on every irregular (`hypotheses`, `matrices`,
  `indices`, `leaves`, `mice`, `axes`), which let a near-duplicate pair fire for
  one caller and not for the whole-vault sweep that is the only thing which ever
  looks at a pair already in the vault.

## Run the test after editing any skill

```bash
python3 tests/test_conventions.py        # -v to list passing checks, --json for a machine
```

It re-derives every convention from `CONVENTIONS.md` and checks the skills
against it: the tag enum stated identically everywhere, no second copy of the
slug algorithm (and if one exists, that it agrees on 98 cases including `C++`,
`C#`, `Ca²⁺` and Greek capitals), one figure-naming pattern, one frontmatter
order per note type, one source-filename rule — no second copy of it under
`skills/` whatever that copy is named, and the prose restating it held to the
same order the code enforces — every `<placeholder>` standing for a path or a
URL single-quoted in every command line the plugin documents, fenced or not and
in `.py` files as well as `.md` ones, no skill claiming another skill does
something that skill has never heard of, every `references/…` path resolving
and reachable, and —
**plugin-wide, this file included** — no name used as a skill that is not a
directory under `skills/`. The roster is read from that directory, so adding or
removing a skill needs no edit here to stay checked.

This is not hygiene. Every convention it checks is one that has already drifted
and cost something: two slug implementations that disagreed on `C++` made the
linter propose renaming correctly-named entries, and an approved rename rewrites
links vault-wide. A 24-value copy of the tag enum silently dropped a discipline.
Three figure-naming conventions lost every figure when two skills ran over one
PDF. And the roster has now gone stale three times in both directions — a skill
routed to before it existed, and routed to after it was removed — each time
leaving contracts that could never be enforced and could never fail. The test
exists so those fail loudly the next time instead of quietly.

It prints `PENDING` for defects registered in `CONVENTIONS.md` §10 that a skill
edit still has to fix — loud and itemised, never counted as passes. Anything of
the same shape that is *not* registered is a hard failure, so the list can only
shrink.

**It checks conventions, not behaviour.** What a script actually *does* is
pinned by that script's own embedded suite, which builds its fixtures under
`tempfile` and deletes them:

```bash
python3 skills/wiki-linter/scripts/scan_vault.py --test        # the whole-vault scanner
python3 skills/wiki-builder/scripts/vault_index.py --test      # the index the other two read
python3 skills/wiki-builder/scripts/find_collisions.py --test  # the five probes, + (f), (g)
python3 skills/wiki-builder/scripts/lint_entry.py --test       # the mechanical checklist
python3 skills/pdf-organizer/scripts/organize.py selftest      # renames and book splits
python3 skills/paper-summarizer/scripts/paper_scan.py --test   # what to summarise
python3 skills/paper-summarizer/scripts/note_lint.py --test    # the summary-note format
python3 shared/scripts/slugify.py --test                       # and the shared layer
python3 shared/scripts/plurals.py --test
python3 shared/scripts/naming.py --test
```

Every one of them reports how many cases ran and passed — the skill scripts as
`N/M self-test cases pass`, the shared modules as `N/M` or as JSON — and all of
them exit non-zero on a failure. The four wiki suites exist because a green
convention run is not evidence about the scripts that drive *edits to the
vault*: whether a wikilink is dangling decides how the linter repairs it, and
mistaking a resolving look-alike for a dangler would overwrite a real entry —
no text-level check can see that.
