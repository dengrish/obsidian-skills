# Vault conventions — the canonical statement

**This file owns shared vault contracts:** folder ownership, schemas, dates and
review state, tags, names, source identity, and cross-skill linking boundaries.
Shared runtime, input safety, safe publication and suggestion logs
have their own linked guides. Each skill's entrypoint selects its workflow and
authorization scope; its linked references own the detailed procedures and
output-specific writing rules. A consumer links to the rule's owner instead
of maintaining a second full definition. Concise execution reminders are useful,
but do not override that owner or widen the active workflow's permissions.

**Reading this file.** Read [input safety](INPUT_SAFETY.md) before handling
external values or content; consult §1's layout only when resolving folders or
routes. Read the other sections when the active skill's workflow needs them;
the contents below links directly to each subject. §5 (shared-module setup)
and §10 (validation) are for development or troubleshooting, not
required background for every vault run.

---

## Contents

1. [Vault folder layout](#1-vault-folder-layout)
   — and [1a. Source-file names, and why pdf-organize runs first](#1a-source-file-names-and-why-pdf-organize-runs-first),
   [1b. Safe vault writes](#1b-safe-vault-writes),
   [1c. Feed-owned attachments](#1c-feed-owned-attachments)
2. [Frontmatter schemas](#2-frontmatter-schemas)
   — and [2a. Wiki entry](#2a-wiki-entry--wikimd),
   [2b. Source note](#2b-source-note--a-note-about-a-document),
   [2c. `read` — the user's review checkbox](#2c-read--the-users-review-checkbox),
   [2d. `issues` — the user's issue inbox](#2d-issues--the-users-issue-inbox)
3. [The discipline-tag enum](#3-the-discipline-tag-enum)
4. [Slugs and filenames](#4-slugs-and-filenames)
5. [Reaching `shared/scripts/` from a skill](#5-reaching-sharedscripts-from-a-skill)
6. [Wikilink forms](#6-wikilink-forms)
7. [Source references](#7-source-references)
8. [Figure naming and `Sources/Images/`](#8-figure-naming-and-sourcesimages)
9. [Ownership split for linking](#9-ownership-split-for-linking)
10. [Validation](#10-validation)

---

## 1. Vault folder layout

Knowledge and investment workflows may share one vault. Resolve `<vault>` and
the run's private scratch through [runtime setup](RUNTIME.md); use folder
overrides only where the selected workflow supports them. Final publication
staging follows [SAFE_WRITES.md](SAFE_WRITES.md).

| Path | Holds | Written by | Read by |
|---|---|---|---|
| `Inbox/` | **everything new, unsorted** — Web Clipper `.md` captures and dropped-in documents alike. The **file extension is the dispatch**, and it is the whole of it: `.md` to one skill, `.pdf` to the other, **anything else to neither** | the user, the user's clipper; a rename's link repair respells a raw's link to the renamed file and changes nothing else | clipping-clean (`.md` only), pdf-organize (`.pdf` only); wiki-build (routing and preview), wiki-add and wiki-lint's missing-entry research (URL and same-document checks) read them but never cite them |
| `Articles/` | **flat**; notes *about* a document — cleaned clippings, PDF reading notes and legacy marked research extracts, one schema (§2b), with origin identified by `sources:` item 1 | clipping-clean, paper-summarize; pdf-organize moves an owned summary note and updates its `sources:` origin and `published:` year during a PDF rename; figure-extract's Extended Data switch repairs links to each `_fig_S<N>` crop it re-extracts as `_fig_ED<N>` (§8b); during a retitle, alias removal, split or merge, wiki-lint retargets every link that resolves to the retired name, never a note's claim wording or `sources:` | wiki-build, wiki-add (source reuse), clipping-clean (dedup index), paper-summarize (dedup and collision check), pdf-organize (rename preflight), wiki-lint (cited notes for content repair, and notes its missing-entry research reads under wiki-add's local-source rule) |
| `Sources/PDFs/` | organized source documents, recursive; feed-owned attachments use the separate route in §1c. Knowledge consumers check the canonical stem before deriving files or references (§1a) | pdf-organize (renames an `Inbox/` file **and moves it here**), wiki-add (newly acquired research PDFs only, named under pdf-organize's rules), feed-collect (raw linked PDFs), the user | figure-extract, paper-summarize, wiki-build, wiki-add, wiki-lint (PDFs Wiki entries already cite, and PDFs its missing-entry research reads under wiki-add's local-source rule); feed-collect within its own scope |
| `Sources/PDFs/<Work>/` | book-chapter PDFs, e.g. `Sources/PDFs/Prince_UDL_2026/`. The folder is what pdf-organize creates when it splits a book. paper-summarize's batch **scans** it — a book is only recognisable as one when a chapter turns up beside it — and then **skips** every chapter it finds, so a sweep never becomes a book's worth of summaries | pdf-organize, the user | figure-extract (extracts the chapters, skips the split book), paper-summarize (scans, skips), wiki-build (processes the chapters instead of the split book), wiki-add (cites the chapters, never the split book), wiki-lint (cited chapters, and chapters its missing-entry research reads) |
| `Sources/Images/` | **flat**; every figure and downloaded image, all extensions, whatever it came from | figure-extract (including the runs wiki-build and wiki-add start for a PDF's missing figures), clipping-clean, feed-collect (original photo attachments); **pdf-organize** renames in place only within its source rename (§1a) | wiki-build, wiki-add, paper-summarize, clipping-clean (its `rename` path re-reads the folder — §8a), wiki-lint (with `--images`, validates embeds and reports nested/staging residue without opening or deleting files); feed-collect within its own scope |
| `Wiki/` | wiki entries, one `.md` per entity (walked **recursively**) | wiki-build, wiki-add (missing requested entries only), wiki-lint; pdf-organize and clipping-clean repair references to a source they rename (§2a), and figure-extract's Extended Data switch repairs links to each `_fig_S<N>` crop it re-extracts as `_fig_ED<N>` (§8b) | wiki-build, wiki-add, wiki-lint, paper-summarize (indexes entries and reads a match to link a concept in a reading note) |
| `Investments/` | dated stock analyses at the top level, plus maintained stock notes, research evidence and source collections in dedicated subfolders; each investments skill governs its own format | stock-research (immutable dated records/evidence and maintained Stocks/ notes), feed-collect (maintained source collections); the user maintains `x-accounts.md`; clipping-clean respells only a link or embed to a clipping it renames, never in a dated record (see below) | the investments skills within their own scope |
| `add-to-wiki.md` at the *vault root* | requested-topic queue | the user; wiki-add checks off successful or already-existing items only | wiki-add |
| `MOCs/` | **flat**; fully generated `<discipline>-moc.md` nested outlines plus `misc-moc.md` for Wiki entries tagged `#misc`; no marker comments, H1, or frontmatter | wiki-lint; clipping-clean respells a link to a clipping it renames (§7) | wiki-lint (navigation/hierarchy diagnostics only; reads each before an in-place update) |
| `Reviews/` | `<current-skill>-suggestions.md` for installed skills, plus `Reviews/wiki-notes-suggestions.md` for Wiki note-content improvements; open issues, then fixed ones; and `.wiki-lint-settled.json`, wiki-lint's private ledger of settled link decisions (run state, not a log) | skills under the attribution and setup rules in [SUGGESTIONS.md](SUGGESTIONS.md); during their own renames, clipping-clean (a changed-slug reprocess) and wiki-lint (a retitle, alias removal, split or merge) retarget every link in a log that resolves to the renamed note, links inside issue text included, and pdf-organize (a PDF rename) and figure-extract (an Extended Data switch) rewrite the old file name in links and in the plain-text mentions [rename repair](../skills/pdf-organize/references/rename-repair.md#establish-the-owned-family) defines; none changes any other issue text; wiki-lint writes its settled ledger | skills consuming the relevant outputs or verifying a fix; wiki-lint reads the note-content log's open items as a worklist it re-verifies; wiki-lint's scanner reads the settled ledger (`--settled`) |

Suggestion logs use current skill names under `Reviews/`. The shared
[SUGGESTIONS.md](SUGGESTIONS.md) owns attribution, the log format, moving
items from Open to Fixed, safe publication, and explicitly requested migration;
do not duplicate those rules in skill-specific references.
Unexpected root `<discipline>-moc.md` notes are preserved and reported; do not
create a duplicate MOC or reinterpret their links as missing Wiki entries.
A previous-layout `MOCs/<discipline>.md` MOC follows the
[migration rule](../skills/wiki-lint/references/hierarchy.md#migrate-the-previous-moc-layout).

**Source routes.** Choose the skill by the requested result; these are not
mandatory stages. For PDFs, organize the filename before creating derived
files (§1a). Figure extraction supplies images to paper-summarize and
wiki-build; each prepares missing PDF figures with figure-extract under its
own procedure
([paper-summarize](../skills/paper-summarize/SKILL.md#prepare-the-figure-inventory),
[wiki-build](../skills/wiki-build/references/media.md#missing-pdf-figures)),
and each reads the PDF itself. A summary is a finished reading note, not a
required intermediate; builder may use it as fallback only under its
[verified missing-PDF rule](../skills/wiki-build/references/source-cases.md#resolve-a-markdown-source).
A web capture follows clipping-clean into `Articles/`, and an Inbox PDF is
filed by pdf-organize; only the cleaned note or filed PDF, never the raw
`Inbox/` file, can become a wiki-build source.
A source-first contribution, including a request naming entities from
identified sources, belongs to wiki-build. A topic without a source document
belongs to wiki-add (below). Corrections, simplification and deepening of
existing entries, consolidation of an explanation duplicated across them, and
merges and splits of existing entries belong to wiki-lint's
[content-repair step](../skills/wiki-lint/SKILL.md#task-1b--content-repair)
(Task 1b), under the citation scope in §7; that step also creates a missing
entry its own run establishes (§9). Its source-independent QC needs no source.

When one request asks for several results, run each skill once in dependency
order: intake first (pdf-organize or clipping-clean), then paper-summarize,
wiki-build or both from the organized PDF, or wiki-build from the cleaned
note, and wiki-lint last when the new entries' parents, MOCs or inbound links
were requested.

**Research route.** [wiki-add](../skills/wiki-add/SKILL.md) creates only
missing requested topics, from vault-root `add-to-wiki.md`, a backlog file the
user selects, or topics the user names without a source document; its
[research guide](../skills/wiki-add/references/research.md) owns acquisition,
naming, filing and the
[rule for reusing local sources](../skills/wiki-add/references/research.md#find-local-sources-first).
wiki-lint researches a missing entry its own run establishes the same way,
under that local-source rule and §9's citation limits, but never acquires or
files a PDF. This route does not change wiki-build's source-first extraction.

**Investment artifacts stay outside Knowledge maintenance.** The independent
investment skills own `Investments/`, including dated research, maintained
`Stocks/` notes and `Sources/` collections. These do not enter automatic Wiki
intake or source-note cleanup. Inventory their resolving links during rename
and refactor planning; a dependency requiring an investment-note edit blocks
retirement of its target, and a rename's reference repair does not waive that
ownership or the dated records' immutability. The one exception is
clipping-clean's changed-slug repair, which respells only a link or embed that
resolves to its own renamed clipping or image (§7), and never in a dated
`*-stock-research.md` or `*-market-research.md` record: such a reference stays
a blocker and keeps the old clipping in place. Preserve old market-research
records as well. Stock publication receipts under
`Investments/.stock-research/dossiers/` and feed state under
`Investments/Sources/.feed-collect/` (X) and `Investments/Sources/.rss-collect/`
(RSS/Atom) are durable data, never scratch. The collector may update its own
source collections; that is not permission for Knowledge to rewrite them.

An interrupted or partial wiki-build run is resumed by **wiki-build** with
explicit resume/re-run intent; wiki-lint repairs residue within its own
scope (§7) and cannot finish extraction or a source merge.

**`Inbox/` drains for PDFs and accumulates for clippings.** pdf-organize moves
PDFs into `Sources/PDFs/`; clipping-clean preserves the raw capture in
`Inbox/` because cleaning may remove material. Its dedup index, not the raw
file's location, records whether it was processed (§2b). On an inbox-wide run,
route `.pdf` and captured `.md` files separately. Both skills **name unsupported
files and leave them in place**; neither files an `.epub`, `.docx`, or spreadsheet.

**`Articles/` has two source-origin routes, identified by `sources:` item 1.**
All its producers write §2b notes-about-a-document with the same field order,
named under the §4c source-note rule, so the folder and the filename shape
settle nothing. The frontmatter does:

- **`sources:` item 1 is a URL** → a cleaned clipping or legacy wiki-add
  research extract. The note *is* the local source. The research-extract body marker
  described in §2b distinguishes an agent-written extract from a full-text
  clipping; clipping-clean must not reprocess a marked extract as a capture.
- **`sources:` item 1 is a `"[[Name.pdf]]"` wikilink** → a summary of that PDF. The
  **PDF** is the source; wiki-build reads the PDF and cites
  `[[Name.pdf#page=N]]` (§7), because only a PDF has pages and because this
  note is a restatement of the paper rather than the paper.

Every consumer of the folder branches on that one item: wiki-build's source intake,
clipping-clean's dedup index (a wikilink in `sources:` item 1 is another
skill's note, not a defect), wiki-add's source reuse, and paper-summarize's
collision check. A URL-origin note remains a URL dedup match whether it is a
clipping or a legacy research extract; the marker does not create a second URL identity.
The collision check inventories the flat basename namespace with NFC
normalization and case folding:
an `Articles/<stem>.md` portable equivalent whose `sources:` item 1 is not this
PDF is somebody else's note and is **never** overwritten, and multiple
equivalent basenames have no arbitrary owner.

**Two invariants the layout depends on:**

- **No skill discards user content.** Raw clippings and source documents remain
  records. A reprocess, retitle or source-backed refactor within its
  workflow's authorized scope may conditionally remove an obsolete note or
  attachment pathname only after its replacement,
  content, metadata, and dependent references have been published and verified.
  Content the user explicitly names for deletion (a wiki-lint deletion
  refactor) is removed only through that protocol,
  after its inbound references are resolved. Every wiki-lint card check
  (Task 1) and every wiki-build merge keeps an entry's one definition card
  and removes any other card once no link targets its block ID, quoting it
  verbatim in the run report
  ([card set](../skills/wiki-build/references/flashcards-and-emphasis.md#card-set));
  nothing else is discarded.
  A later occupant always survives. pdf-organize moving an `Inbox/` document
  to `Sources/PDFs/` is a move, and it carries every name derived from that
  file with it (§1a).
- **Other artifacts are outside `Wiki/`.** MOCs live in `MOCs/`, market research
  in `Investments/`, suggestion logs in `Reviews/`, and `add-to-wiki.md` in the
  vault root. wiki-lint walks entries
  only in `Wiki/`, so it never lints these artifacts as entries or lists a MOC
  inside another MOC. Passing the vault root where `Wiki/` is expected breaks
  these exclusions.

**Batch scope is limited to the selected skill's input folders.** Unrelated
projects, plugin data and legacy root notes remain outside that scope. Read
one if the user names it, but do not widen a batch scan or rewrite it on your
own initiative. pdf-organize also accepts an arbitrary external directory;
inside a vault its enumeration is an **allowlist** of `Inbox/` and
`Sources/PDFs/`, with only PDFs eligible. It does not scan every folder merely
because the user selected the vault root.

**Depended on by:** the knowledge skills. `Sources/Images/` is shared across the
plugin; pdf-organize reaches it only on the rename path above, where it is the
one skill that moves a file another skill wrote.
`Articles/` is outside wiki-lint's scan and maintenance scope. Its Task 1b
reads the notes and PDFs entries cite, its missing-entry research reads vault
material under wiki-add's local-source rule, and a retitle, alias removal,
split or merge retargets every link in `Articles/` notes that resolves to
the retired name, including one inside a claim, and never changes claim
wording or `sources:`. The folder's producers enforce their own notes'
schema and quality; paper-summarize also runs `note_lint.py` before
publication.

### 1a. Source-file names, and why pdf-organize runs first

Organize PDFs before deriving filenames and links from them. pdf-organize
renames source files to `LastName_AbbreviatedTitle_Year.pdf` and splits a book
into `LastName_AbbreviatedTitle_Year_NN_ChapterName.pdf` inside a
`Sources/PDFs/<Work>/` folder. Two facts follow from that, and both are
contracts other skills rely on.

**The shape, exactly** — and, like the slug algorithm of §4a, **the rule is the
script, not this table**. `shared/scripts/naming.py` is the single canonical
implementation; `looks_canonical()`, `chapter_parts()`, `core_stem()` and
`split_tail()` are its surface, and its consumers import them rather than
restating them:

These helpers accept a full filename by default. When a caller has already
removed the extension (for example, `Path.stem`), pass `is_stem=True` to
`looks_canonical`, `chapter_parts`, `chapter_book_stem` and `core_stem`.
Removing a second extension from `Doe_Study_2025.revised` would incorrectly
accept the unorganized PDF or merge its identity with another source.
`split_tail` always takes a stem and needs no flag.

<!-- canonical:source-filename -->
```
<Author>_<AbbrevTitle>_<Year>
<Author>_<AbbrevTitle>_<Year>_<NN>_<ChapterName>
```
<!-- /canonical -->

`Year` is a real four-digit year from `0001` through `9999`, or the literal
`nd`; `NN` is a zero-padded two-digit
chapter number. Either form may end with an optional `_src` marker and an
optional `_2`, `_3`, … disambiguator, in that order — and **that tail always
comes last, after the chapter segment**: `Prince_UDL_2026_02_SupLearn_src`,
never `Prince_UDL_2026_src_02_SupLearn`. Numeric disambiguators start at 2 and
have no leading zero, so `_0`, `_1` and `_02` are not output forms. Position
and identity are separate:

**`_src` and `_N` are not one thing.** They occupy the same end of the stem and
carry opposite meanings, and only one of them ever comes off:

- **`_src` is the user's own marker for the same document in another
  representation** (for example, a PDF beside a note the user converted from
  it). No skill adds or removes it, and pdf-organize preserves it exactly; a
  paper-summarize reading note takes its PDF's exact stem and needs no marker
  (§4c). A book and its chapters carry it independently — a book may be
  `Prince_UDL_2026_src.pdf` while its chapters are
  `Prince_UDL_2026_01_Intro.pdf` — so it **comes off** before a book is
  compared with a chapter. Both representations of a split book pair with
  its one chapter set, so a pdf-organize rename of either renames the other
  too, each keeping its own marker.
- **`_2`, `_3`, … mark a different document**, one whose name was already taken
  ((1) below). The disambiguator is part of that document's identity, so it is
  **never** stripped.

So the string to compare on is the **identity**, not a "tail-stripped stem":
`core_stem()` returns the stem with `_src` removed and any disambiguator kept,
and `split_tail()` returns that identity paired with the `_src` marker it
removed.

**A `_N`-disambiguated book therefore matches no chapter, and `split_book`
refuses to split one** — before it opens the file, not when the names collide.
That is deliberate, because no name would satisfy both consumers:
`Prince_UDL_2026_2_01_Intro` is not canonical (a disambiguator may not come
before the chapter segment), while `Prince_UDL_2026_01_Intro_2` is a well-formed
chapter of the *other* book, which is where figure-extract would then file
this book's figures. The refusal tells the operator to fix the name instead:
re-abbreviate the title so the two books differ **before** the year
(`Prince_UDLPractice_2026`), rename, then split.

`naming.py` also recognises the legacy `<book>_src_NN_Name` mis-spelling as a
chapter, deliberately: `looks_canonical()` still rejects it, so pdf-organize
re-renames it to `<book>_NN_Name_src`, moving the marker to the tail, but a
vault already holding those files still gets its book skipped rather than
every figure written twice while the name is being fixed.

**PDF consumers check canonical stems before deriving files or references** —
figure-extract, paper-summarize, wiki-build and wiki-add all key durable
output to the source's name. figure-extract and paper-summarize expose
`--allow-unorganized` for a deliberate one-off and state its cost. wiki-build
has no override: it routes a noncanonical PDF through pdf-organize before
restarting source resolution, except that an explicitly named feed-owned
attachment (§1c) keeps its collector name once a single vault owner is proven.
wiki-add also has no override; it names only its newly acquired PDFs, under
pdf-organize's rules, and cannot rename an existing source or its
dependencies. Reuse an already-cited canonical source, select different
evidence or defer when that boundary blocks intake.

**(1) pdf-organize guarantees a vault-unique PDF basename.** Its naming rule
produces one name per document. When a target name is already taken it
chooses a distinguishing title or, as a last resort, appends `_2`, `_3`, …
rather than overwriting — so no two files it has processed share a basename.
This guarantee is load-bearing, not incidental: Obsidian
resolves the bare link `"[[Name.pdf]]"` (§6) and the bare source reference
`[[Name.pdf#page=N]]` (§7) **by basename, vault-wide**, and an ambiguous
basename renders whichever file Obsidian happens to pick, silently. That is why
paper-summarize may write the bare form at all.

The guarantee covers files pdf-organize has processed. **A PDF that reached the
vault without going through it carries whatever name it arrived with**, so a
skill about to write a bare PDF link or citation for a PDF of unknown
provenance should still confirm the basename resolves to exactly one file with
the shared portable inventory:

```bash
python3 '<plugin>/shared/scripts/vault_artifacts.py' pdfs \
  --vault '<vault>' --selected '<resolved PDF path>'
```

Read its JSON even on a nonzero exit. The helper skips dot-prefixed files and
folders, follows directory symlinks without looping, treats a PDF-named
symlink as an occupant, compares basenames under NFC normalization and case
folding, and refuses to prove uniqueness from an unreadable or changing tree.
A folder-qualified input does not make the bare output link safe when another
vault path shares its basename.

#### Shared PDF basenames

**A shared PDF basename blocks the PDF skills until it is resolved.** Notes,
figures and references keyed to a basename that two vault files share cannot
be attributed to one copy, so pdf-organize will not file, rename or split a
PDF when another vault file shares its basename or that of a chapter in its
family, and the other PDF skills refuse that basename. Report both paths.
When one copy, normally the newcomer, has a non-canonical name, owns no
derived files and no note or canvas cites it (such as an unreferenced
`download.pdf`),
route it through pdf-organize, which still renames and files such a copy and
so resolves the ambiguity. Otherwise ask the user to remove the redundant copy
(same document), or to rename the newcomer (normally the copy outside
`Sources/PDFs/`) or move it out of the vault (different document). Renaming
the filed copy instead would hand its note, figures and citations to the
newcomer. Never delete or move either copy yourself. Two paths that are one
file reached through a symlink are not copies: ask the user to remove that
link or move it out of the vault, never the file it reaches.

#### PDF renames

**(2) A PDF rename must carry its complete derived family.** Wiki citations
and prior-coverage checks use its filename (§7); figures use its stem (§8);
summary filenames, origins and embeds also depend on that name. Ordinary Wiki
orphan audits exclude `sources:`, and summary lint checks citation form rather
than PDF existence. The Wiki scanner's `--images` check reports missing
embeds, but cannot discover every stale citation or unembedded old figure.
Later lint therefore cannot substitute for the organizer's complete repair.

**Establish a stable PDF name before extraction, summary writing or wiki
building.** These consumers do not have to run in that order; a summary is
not a prerequisite for wiki entries. A later rename must carry every affected
reference and derived file. pdf-organize checks references and reviews the
read-only rename plan before applying it; the rename request authorizes its
reference repair. Its `rename_all` workflow carries related files,
Markdown and Canvas references and default figure sidecars together, with
preflight and rollback. Inspect that plan and re-probe the old names
afterward; a successful file move alone does not establish that all
references moved.

**Depended on by:** paper-summarize (the bare `[[name.pdf]]` source link and
its note-naming rule both assume (1); `scripts/paper_scan.py` imports
`naming.py` to refuse an unorganized stem and to skip a split book),
wiki-build (`sources:`, the figure glob, and `naming.py chapter` to process a
split book through its chapters), figure-extract (the `[pdf_stem]` key;
imports `naming.py` to tell a book from its chapters and to refuse an
unorganized stem), pdf-organize (provides (1) and imports `naming.py` for the
same shape; its own run order is (2)). All three importing consumers carry the
§5 bootstrap, so there is no second copy of the rule in the tree. wiki-add
uses these existing naming and PDF-consumer helpers for acquired or reused
PDFs; it introduces no separate filename rule.

### 1b. Safe vault writes

Every vault writer follows [SAFE_WRITES.md](SAFE_WRITES.md), which owns
snapshotting, exclusive creation, guarded replacement/removal, and recovery.

Content workflows keep working drafts private through their final lint and
semantic review, then publish those reviewed bytes once. A preview, plan-only,
or no-apply run may write approved scratch files but never creates an output
folder or intermediate artifact in the vault. When a combined set must be
validated, build a private proposed-state view from stable copies plus staged
overlays; never use hard links that could turn an in-place review edit into a
public mutation.

**Depended on by:** workflows that write to the vault in either plugin.
pdf-organize, figure-extract,
clipping-clean, and stock-research implement the same guarantees in their
shipped helpers;
paper-summarize, wiki-build, wiki-add and wiki-lint apply them when
publishing notes, entries, queue checkoffs, logs, parents, and MOCs.

### 1c. Feed-owned attachments

The investments feed collector owns the photo and document attachments it
downloads into flat `Sources/Images/` and `Sources/PDFs/`: X attachments named
`x-<post-id>-<24 hex>.<ext>` and RSS/Atom attachments named
`rss-<32 hex>.<ext>`. `shared/scripts/naming.py feed` recognizes both. Its
receipts in the durable feed state named in §1's investment paragraph record
these paths, so the names are not knowledge figure numbers or inferred
document titles. Keep them out of routine knowledge intake, renaming and
orphan cleanup: folder sweeps skip them with an informational note and never
route them to pdf-organize, while vault-wide basename inventories still count
them. An explicit request to use one as a knowledge source does not authorize
renaming the collector's file or changing its receipt; a named PDF uses its
consumer's documented exception (§1a). Follow the consuming workflow's
citation schema: paper-summarize retains bare PDF links after proving
vault-wide basename uniqueness; the collector uses full vault-relative
attachment links.

**Depended on by:** figure-extract, paper-summarize, pdf-organize, wiki-build
and wiki-add, whose folder sweeps and source searches skip these files.

---

## 2. Frontmatter schemas

This section defines the shared frontmatter schemas for Wiki entries and
source notes. A skill writing either kind follows its schema exactly, including
field order. Daily market research has a separate purpose and follows its own
`investments:stock-research` note format; these schemas,
Wiki discipline tags, and Wiki review-checkbox rules do not apply to it.

### 2a. Wiki entry — `Wiki/*.md`

Fields appear in **exactly this order**:

<!-- canonical:frontmatter:wiki-entry -->
```
title, type, aliases, sources, created, updated, description, tags, parents, read, issues
```
<!-- /canonical -->

```yaml
---
title: "LambdaRank"
type: Concept
aliases:
  - "lambda-rank"
sources:
  - "[[Burges_LearningToRank_2010.pdf#page=4]]"
created: 2026-05-13
updated: 2026-05-14
description: "LambdaRank optimizes ranking metrics by scaling pairwise gradients by the change in NDCG from item swaps."
tags:
  - "#machine-learning"
parents: []
read: false
issues: ""
---
```

- **`aliases` is the only omittable key** (omit when there are none).
- **`tags` is a required block list containing exactly one** double-quoted,
  `#`-prefixed enum value. Use `"#misc"` when no specific discipline fits.
  Multiple, blank, empty, missing, or malformed Wiki
  tags are QC errors. This requirement does not change source-note schemas.
- **`sources` lists at least one source** — a vault document or an online
  page's URL (§7) — on every entry, a discipline root included.
- **`parents` is a list, and an empty one is written `parents: []`** — never a
  bare `parents:`, which is YAML `null` rather than the empty list that the
  vault's `multitext` property type (`.obsidian/types.json`) declares. A
  populated value stays block-form (see the quoting rule below).
- Everything else always has a value, except that `issues` may be blank
  (§2d). `description` is never omitted.
- `type` is one of fifteen: `Concept` `Person` `Organization` `Dataset`
  `Software` `Device` `Event` `Standard` `Gene/Protein` `Organism` `Chemical`
  `Reaction` `Place` `Work` `Quote`.
- `description` is ≤ 110 characters, entity as grammatical subject, plain text
  (no LaTeX, no markdown, no wikilinks).
- `created` never changes. `updated` equals `created` on creation and is bumped
  to today whenever a wiki-build run changes the entry, including a
  source-no-op merge whose independent QC or metadata work changes the file. A
  byte-unchanged source-no-op keeps the old date. wiki-lint's Tasks 1–3
  preserve both dates on existing entries, apart from removing an extra card
  (below). A missing discipline root created
  under Task 3, and a missing entry or an entry a split creates under Task 1b,
  use today's date for both fields. Removing an extra
  card, part of every wiki-lint run and wiki-build merge that checks the
  entry's card, under the
  [card set](../skills/wiki-lint/references/flashcards.md#card-set),
  advances `updated:` and leaves `read:` unchanged. wiki-lint's Task 1b
  content repairs, splits and merges, and an explicit correction or refactor
  request, follow wiki-build's creation rules and
  its [body-change rule](../skills/wiki-build/references/merge.md#the-read-reset)
  for the entries they change or create: `updated:` becomes today whenever
  the entry's body, card, title, description, aliases or sources change, and
  `read:` follows §2c. A split's retained original keeps
  its `created:`; a merge's surviving entry keeps its own `created:` and gets
  `read: false` (§2c). A producer's reference repair after
  its own rename (pdf-organize's PDF rename, clipping-clean's changed slug,
  figure-extract's Extended Data switch)
  rewrites only references to the files it renamed, and clipping-clean's
  also drops a `sources:` block-list item its rewrite made a copy of
  another item. Each leaves the `created:`,
  `updated:` and `read:` of every note it repairs unchanged. Inbound-link,
  `parents:` and MOC rewrites made by a retitle, alias removal or refactor likewise leave the
  dates and `read:` of every otherwise unchanged entry as they were. A retitle
  alone advances `updated:` and keeps `read:`, and so does an alias removal on
  the entry whose `aliases:` list it edits. Removing resolved user issues from
  `issues:` and the `read:` reset that follows (§2d) do not advance `updated:`
  on their own. A user issue is not an explicit request under these rules:
  the task that resolves it dates the entry as above, so an issue Tasks 1–3
  resolve advances `updated:` only for an extra-card removal.
- **`read` is a boolean, written `read: false` on creation.** It is the user's
  review checkbox (`.obsidian/types.json` pins it as `checkbox`), and §2c is
  the whole rule for who may write it.
- **`issues` is the user's issue inbox, the last schema key, written
  `issues: ""` on creation.** The user describes problems they noticed in the
  note there, and wiki-lint's next run resolves them. §2d is the whole rule
  for its values and who may write it.

**Quoting.** Canonical writers double-quote `title`, `description`, and every
item under `aliases`, `sources`, `tags`, `parents`. Never quote `type`,
`created`, `updated`, `read`. Double quotes only; escape a literal `"` as
`\"`. On lint, a nonempty plain `title`, `description`, or `aliases` item is
also conforming when its exact YAML spelling resolves losslessly as a string;
Obsidian's Properties editor removes unnecessary quotes, and restoring them
would create endless quote churn. Values that a YAML resolver could type as a
boolean, null, number, date, timestamp, or collection still require quotes.
Items under `tags` and `parents`, and every vault link under `sources`,
always require double quotes; a plain `http(s)://` URL under `sources` is
conforming on the same lossless-string terms, since Obsidian strips its quotes
too. The quotes on tags are load-bearing — an unquoted `- #machine-learning` is a YAML
comment, and the discipline is silently lost. `read` takes the bare YAML
booleans `true` and `false` — never `"false"`, never `yes`/`no`, never `0`/`1`;
a quoted value is a string and Obsidian's checkbox renders it as permanently
checked. `issues` is user text outside these rules: writers emit the canonical
blank `issues: ""` and keep a user's value exactly as spelled and quoted (§2d).

**Existing `importance:` values are preserved.** New entries omit this key.
When present, keep its value unchanged between `tags:` and `parents:`; it is
optional and is not a lint finding.

**Keys outside this schema are preserved.** Obsidian-owned appearance and
publish properties (the validators' `OBSIDIAN_KEYS`) and any other unexpected
key are user metadata. Keep each value exactly and in place, and report it; a
schema mismatch alone never authorizes deleting, reordering or repurposing it.

**Body math has a canonical home too.** The vault-wide equation policy —
explanatory value, evidence, display form, notation, normalization —
lives in `wiki-build/references/equations.md`, and wiki-lint enforces it
vault-wide under its QC item 12. Both Wiki validators import the conservative
`shared/scripts/equation_coverage.py` candidate floor; the executing agent
still performs the complete semantic coverage review. Section 2c records what
that enforcement may and may not write.

**Depended on by:** wiki-build (writes it, preserving an existing `issues:`
value on a merge), wiki-lint (validates and fixes
it; owns `parents:`, preserves existing dates in Tasks 1–3 apart from an
extra-card removal, follows the date exceptions above for its content
repairs, splits, merges, retitles and new entries, which it creates with
`parents: []` and places in the same run, and resolves user
issues under §2d), wiki-add (creates
requested entries with `parents: []`, `read: false` and `issues: ""` using
builder's rules and validators, without editing existing entries). The two validator owners bundle scripts
carrying the field order as a constant — `wiki-build/scripts/vault_index.py` (`SCHEMA_ORDER`)
and `wiki-lint/scripts/scan_vault.py` (`CANON`) — and both include
`importance` in that constant so a legacy entry is not misreported.

### 2b. Source note — a note *about* a document

One schema for notes in `Articles/`: `clipping-clean` writes cleaned
clippings and `paper-summarize` writes PDF reading notes. `Articles/` may also
hold legacy research extracts, which remain valid source notes; wiki-add cites
a web page by its URL (§7). These are notes about a document rather than an
entity.
Their **bodies** follow each producer's workflow — a cleaned article, a
structured PDF summary, or an agent-written extract of one web page — while
their frontmatter follows this shared convention. Future source-note producers
adopt it rather than inventing another schema.

A legacy research extract is clearly agent-written and is neither a full-text
capture nor a multi-page synthesis. Its body carries the exact marker
`<!-- obsidian:wiki-add-research-source -->` defined by the
[research guide](../skills/wiki-add/references/research.md#legacy-research-extracts).
This marker identifies the content kind; one page per note. No skill creates,
edits or extends one.
Reuse an existing note only under the
[local-source rule](../skills/wiki-add/references/research.md#find-local-sources-first),
never rewriting it. `clipping-clean` must preserve marked extracts and never
process them as full-text captures.

<!-- canonical:frontmatter:cleaned-note -->
```
title, format, sources, author, published, created, description, tags, read
```
<!-- /canonical -->

`sources` is a **block-form list, every item double-quoted** — the same name,
form and quoting as the wiki-entry field of §2a. Its cardinality is fixed by
producer:

- **On a cleaned clipping: exactly one item, the capture URL**, preserved
  verbatim from the raw capture's own `source:` key and never replaced by a
  fetched URL.
- **On a legacy research extract: exactly one item, the verified origin URL**
  of the page the note describes.
- **On a note about a local document: item 1 is the quoted wikilink to that
  PDF** (`"[[Prince_UDL_2026_01_Intro.pdf]]"`). A second item may carry the
  document's own printed DOI or arXiv identifier in URL form, never on
  `format: Book`; two items is the maximum.

```yaml
---
title: Pancreatic cancer just met its match
format: Article
sources:
  - "https://example.com/article"
author:
  - Ruxandra Teslo
published: 2026-01-14
created: 2026-01-20
description: Daraxonrasib, a KRAS molecular glue, roughly doubled metastatic pancreatic cancer survival in early trials.
tags:
  - "#medicine"
read: false
---
```

- `format` is `Article` | `Post` | `Video` for a web clipping, and
  `Paper` | `Book` | `Report` for a note built from a local PDF (a note about a
  book chapter is `Book`). A legacy research extract uses `Article` or `Post` for its
  source page. Unquoted.
- `sources` is the block-form list above.
- `author` is a block-form list when populated, even for one author, without
  `[[…]]` wrappers; quote an item only under the `title` rule below. With no
  eligible byline, write `author: []`, never bare `author:` (YAML null) or an
  empty item.
- `created` is the date the note is written, except on a clipping, which keeps
  its raw capture date verbatim. An authorized rewrite preserves it unless its
  correction is specifically in scope.
- `published` is a full `YYYY-MM-DD` publication date, every component the
  source's own evidence does not state padded with `01` and reported, or the
  explicit YAML null `published: null` when the source is undated.
- `description` is ≤ 110 characters of plain text (no Markdown escapes such as
  `\$`, no LaTeX, no wikilinks); each producer's reference owns its subject and
  attribution.
- `tags` uses §3's values and form — block-form, `#`-prefixed, double-quoted,
  never a wikilink — for the discipline or disciplines that own the document's
  substance; §3's exactly-one cardinality applies only to Wiki entries. When no
  discipline applies, write `tags: []`, never `"#misc"`, which is Wiki-only.
  Lint tolerates a legacy bare `tags:`.
- `read` is the boolean of §2c, written `read: false` on creation, unquoted.
- `title` and `description` are plain unless YAML would misread them: quote a
  value containing a colon or another YAML metacharacter, or one a YAML
  resolver could type as a boolean, null, number, date or timestamp (`1984`,
  `Yes`, `null`), as in §2a.

Each producer's reference owns its field decisions, such as author evidence,
date padding and undated names: clipping-clean's
[metadata rules](../skills/clipping-clean/references/metadata-verification.md#frontmatter-for-the-polished-note)
and paper-summarize's
[frontmatter procedure](../skills/paper-summarize/references/note-format.md#frontmatter).

**Preserve unexpected metadata.** New notes use this schema. When updating an
existing note, preserve fields outside the schema and report any that prevent
a safe rewrite; do not silently delete them or infer a metadata migration.
This does not authorize wiki-add to rewrite a reused source note: its
existing-source boundary remains read-only.

**Depended on by:** clipping-clean (writes it for a cleaned clipping), paper-summarize (writes
it for a summary note, and is the only producer whose `sources` opens with a
wikilink and may carry a second, printed-origin URL item), wiki-add (reuses
existing sources without edits), wiki-build
(reads a URL-origin clipping or marked extract as a source, using its filename
stem under §8; a PDF summary instead resolves to its original PDF, with only
the verified missing-PDF fallback defined by source intake), pdf-organize
(moves an owned summary note with its PDF, rewriting `sources:` item 1 and
reconciling `published:`).

### 2c. `read` — the user's review checkbox

Both schemas carry it, it means the same thing in both, and with a Wiki
entry's `issues` (§2d) it is one of the two fields in this vault whose value is
**the user's to set**. `.obsidian/types.json`
pins it as `checkbox`, so the value is a bare YAML boolean.

| Who | May write `read` | When |
|---|---|---|
| clipping-clean | `false` on creation; an authorized reprocess preserves the existing value, including an absent or unknown state | a new cleaned clipping note |
| paper-summarize | `false` on creation; an authorized rewrite preserves the existing value, including an absent or unknown state (regeneration is not new reading) | a new summary note in `Articles/` |
| wiki-build | `false`, on creation; `false` again on a **body-content revision** | the [body-change rule](../skills/wiki-build/references/merge.md#the-read-reset) |
| wiki-add | `false`, on creation only | a new requested entry; existing notes are never edited |
| wiki-lint | meaning-preserving spelling repair in Task 1; `false` for a new entry, a merge's surviving entry, or a content repair that adds or rewrites explanatory body content; `false` after resolving a user issue | existing entries keep their review state in Tasks 1–3, except an entry with at least one user issue resolved (§2d); Task 3's missing discipline roots, Task 1b's content repairs, splits, merges and new entries, and requested refactors follow the creation/body-change rules below |
| the user | `true`, whenever they have read it | this is the point of the field |

**The linter preserves the meaning of `read:`.** It may normalize recognizable
`true`/`false`, `yes`/`no`, or `0`/`1` spellings to a bare YAML boolean, including
quoted values such as `"false"` (`item2/read-type`). This corrects the
checkbox's representation without deciding whether the user has read the note.

These cases are **report-only**, with the note and the value found named under
*Notes for the user*:

- `item2/read-missing`: the key is absent.
- `item2/read-null`: the value is empty, `null`, or `~`.
- `item2/read-unknown`: the value is unrecognizable, such as an arbitrary
  string or a list.

None contains a known boolean answer to preserve. Do not substitute `false`
or `true`, even during otherwise mechanical frontmatter repairs. A resolved
user issue and a merge's surviving entry are the exceptions (below).

**The reset rule — body content only.** wiki-build's
[`read:` reset](../skills/wiki-build/references/merge.md#the-read-reset) is the
single body-change rule: an existing entry's known `read:` becomes `false`
only when a pass adds or rewrites unread explanatory body content. This
body-change reset is **narrower than the `updated:` bump**: every body-change
reset implies an `updated:` bump, but not every bump implies a reset.
`read:` records whether the user still needs to look at the note, and a new
`sources:` line creates no reading.
When the call is genuinely close, **do not reset**, and say which way it went
in the run report.

**A resolved user issue resets `read:` as well.** When a wiki-lint run
resolves at least one of an entry's user issues (§2d), `read:` becomes `false`
even if no body content changed, because the user asked to review the note
again. This overrides the narrower body-change rule for that entry, and it
applies to a missing, null or unknown value too (a missing key is inserted as
`read: false` directly before `issues:`): the user's issue supplies the answer
those report-only cases lack. This reset alone does not advance `updated:`;
the task that resolves the issue dates the entry (§2a). A blocked issue
resets nothing, and a report-only run writes neither field.

**Localized Task 1 edits: the rule for them lives here.**
wiki-lint may copy a missing Person/Event date into the required opener only
when that exact date is already stated elsewhere in the entry, or typeset a
calculation the note's own prose already states under item 12 (the equation policy's home is
`wiki-build/references/equations.md`). Even then the linter writes neither
`read:` nor `updated:`. For either case, it reports the insertion under *Notes for the user*,
naming every entry whose `read: true` now predates the added date or equation,
and the checkbox stays the user's to clear. A Task 1 card edit under
wiki-lint's
[card maintenance](../skills/wiki-lint/references/flashcards.md#improving-the-card),
a complete rewrite of line 1 included, likewise writes neither field; an
extra card's removal follows §2a. wiki-build's own merge pass is
the contrast: any newly added unread body content resets `read: false`, whether
it came from the active source or from the builder's independent QC.
wiki-lint's Task 1b content repairs, splits and merges, the entries it
creates, and a requested refactor use that same creation and
[body-change rule](../skills/wiki-build/references/merge.md#the-read-reset),
including `read: false` on a new entry, such as each entry a split creates,
and a reset when retained body content becomes newly unread: a split's
retained original keeps `read:` after a pure trim and resets it when its
explanation is rewritten. A merge's surviving entry is the exception: it
holds combined content the user has not read in that form, so it gets
`read: false` from any prior value, missing or unknown included (a missing
key is inserted directly before `issues:`); its dates follow §2a.
In Task 1b, deepening (an added example, reason or core facet included), a
rewritten explanation, an inserted equation and an explanation moved into its
owner reset `read:`;
trims, hedge removals, consolidation trims, notation renames, retitles, alias
removals, link-only changes, an added acronym or full-form parenthetical, and
naming and linking a contrast in an existing sentence advance `updated:` and
keep `read:`. An
otherwise unchanged entry whose only change is a rewritten inbound link or
`parents:` value keeps both (§2a), and so does every note a producer's
reference repair edits after its own rename.

The reset rule requires judgment about body substance. Scripts check the
field's presence, type and position, but cannot decide whether new reading
has been added.

**Depended on by:** the writers in the table above.

### 2d. `issues` — the user's issue inbox

Wiki entries carry it as their last schema key (preserved non-schema keys may
follow); source notes (§2b) do not. Like `read`, its value is **the user's to
set**: while reviewing a note, the user describes the problems they noticed
there, and the next wiki-lint run fixes the note, blanks the field and sets
`read: false` so the user reviews it again.

- **Blank.** The canonical blank is `issues: ""`, a double-quoted empty
  string, and every writer writes it. A bare `issues:`, `null`, `~`, `''` and
  `[]` are blank and conforming too, because Obsidian may write them, as are
  a whitespace-only string and a list whose items are all empty. No tool
  rewrites one blank spelling into another.
- **Non-blank.** The user's issue text: a one-line scalar string, plain or
  quoted (Obsidian's Text property), which may describe several issues, or a
  list of strings (its List property, block or flow form), one issue per
  item. Keep the user's spelling and quoting exactly; never re-quote it,
  except as a partial rewrite below requires.
- **Malformed.** Anything else: a mapping, a nested list, a list item that is
  itself a collection, a block scalar (`|`, `>`), a value that starts on the
  line after its key or dash, a string or flow list continued on another
  line, a value or list item with an unquoted `#` at its start or after a
  space or tab, or a value that is not valid one-line YAML, such as a plain
  `issues: a: b`. YAML reads such a `#` as a comment that drops the text
  after it (`issues: #1 the card is wrong` or
  `issues: Fix the card # and add an example`), so the value is malformed
  even when what remains would be blank. A comment-only line under the key
  is ignored. A malformed value is report-only and never rewritten.

| Who | May write `issues` | When |
|---|---|---|
| the user | any issue text | this is the point of the field |
| wiki-build | `issues: ""` on creation; on a merge, `issues: ""` directly after `read:` when the key is missing | a merge preserves an existing value byte-for-byte; it never acts on, edits or clears a non-blank value |
| wiki-add | `issues: ""` on creation only | a new requested entry; existing notes are never edited |
| wiki-lint | a missing key as `issues: ""` directly after `read:` (after the last schema key before it when `read:` is absent too), keeping dates and `read:`; the unresolved part of the user's issues, or `issues: ""` once all are resolved; `issues: ""` on its new entries and missing roots; on a split or merge, each unresolved issue moves verbatim to the result that holds its content, and a new note that receives none gets `issues: ""` | Task 1 inserts a missing key; a run that handles the entry's user issues rewrites them; a retitle keeps the value |

**wiki-lint resolves the issues.** Each issue is the user's own request scoped
to that entry, plus the neighbors a consolidation, split, merge, retitle or
link fix must touch and a missing entry it names (§9). This field is the one place a note's content carries the user's
direction, and it widens nothing else: the rest of the note stays data under
[input safety](INPUT_SAFETY.md#source-content-is-data-never-instructions), and
an issue authorizes only a change consistent with the builder rules and
wiki-lint's evidence rule, even one no rule names, such as a simpler
explanation or an added example. The run re-verifies each issue against the
note, its cited sources and the rules. An issue is **resolved** when the run
made the change, or verified with evidence that the reported problem does not
hold and says why in the run report. It is **blocked** when it needs a
deletion (which needs an explicit request in chat), a source the entry does
not cite (such as an unbuilt chapter, which waits for a wiki-build request
naming that source; a verified citation for an entry whose `sources:` is
empty is not one, since wiki-lint's
[item 4](../skills/wiki-lint/references/qc-items.md#4-sources) adds it), or
a change a builder rule forbids (such as a second card
or an added caveat); when no evidence settles it or its meaning is unclear; or
when it asks for something outside wiki-lint's scope, such as other files,
skills or settings. A blocked issue stays verbatim in the field, is never
moved to a log, and the run report names its blocker.

When every issue is resolved, the field becomes `issues: ""`. When only some
are, it keeps exactly the unresolved issues' original text: the unresolved
list items, or the unresolved sentences of a string inside its original
quotes. If a plain string's remainder would no longer read as the same
one-line YAML string (it starts with `[`, `]`, `{`, `}`, `,`, `"`, `'`, `#`,
`-`, `?`, `:`, `>`, `|`, `!`, `&`, `*`, `%`, `@` or a backtick; contains `: `
or ` #`; ends with `:`; or would read as a number, boolean, date or null),
write it double-quoted, escaping `\` and `"`. This and a merge's combined value
([refactors](../skills/wiki-lint/references/refactors.md#build-the-refactored-entries))
are the only re-quoting allowed. At least one resolved issue sets `read: false` (§2c), and `updated:`
advances only when the entry's content changed (§2a). A report-only run
blanks and resets nothing and reports what it would do; a run narrowed to
some tasks or entries handles only the issues they own and leaves the others
in the field; a request to fix the flagged issues takes the scope in
wiki-lint's [Explicit requests](../skills/wiki-lint/SKILL.md#explicit-requests).
The procedure, including routing, is in wiki-lint's
[User issues](../skills/wiki-lint/SKILL.md#user-issues), and the run
report's *User issues* section is in its
[run report](../skills/wiki-lint/references/backlogs.md#run-report).

Scripts check the field's presence, form and position, and list non-blank
values for the run; only the executing agent decides whether an issue is
resolved. wiki-lint's scanner reports `item2/issues-missing` (fixable in
Task 1) and `item2/issues-malformed` (report-only) and lists every non-blank
value under `user_issues`.

**Depended on by:** the writers in the table above; wiki-lint's scanner and
wiki-build's draft linter validate it.

---

## 3. The discipline-tag enum

Exactly **28 values**. No other value is valid. No abbreviations (`#ml`, `#ai`,
`#cs`, `#artificial-intelligence` are not on it — an AI/ML entry takes
`#machine-learning`), no synonyms, no invented members.

<!-- canonical:tag-enum -->
```
mathematics
statistics
physics
chemistry
biology
earth-science
medicine
engineering
computer-science
psychology
sociology
anthropology
economics
finance
political-science
linguistics
history
philosophy
literature
law
business
entrepreneurship
education
architecture
art
music
machine-learning
misc
```
<!-- /canonical -->

**Form in YAML** — block-form list, each value `#`-prefixed and double-quoted:

```yaml
tags:
  - "#machine-learning"
```

- **Tags are not wikilinks.** Each active tag has a corresponding Wiki root
  entry, maintained by wiki-lint's hierarchy workflow. The tag itself remains
  a quoted `#` value; links to that entry use its bare slug, such as
  `[[machine-learning]]`.
- **The quotes are mandatory.** An unquoted `- #machine-learning` parses as a
  YAML comment and the discipline is silently lost.
- **Wiki cardinality: exactly one.** Choose the best home for the concept as
  explained in this entry. Cross-disciplinary relationships belong in prose
  and Related links, not extra tags. When no specific discipline fits, use
  `"#misc"`. Never leave Wiki tags blank/empty. Source notes follow §2b: they
  write `tags: []`, not `"#misc"`, when no discipline applies.
- **Selection test:** tag the discipline that *owns* the entity — where it would
  be a primary topic in a textbook table of contents — not every discipline that
  *uses* it. Vault-specific boundaries, including machine learning versus
  statistics and mathematics, follow wiki-build's
  [tag rule](../skills/wiki-build/references/writing.md#tags) and, for
  boundary cases, its
  [tag calibration](../skills/wiki-build/references/calibration.md).
- **Derived artifact:** the MOC filename is the tag value with the `#` stripped
  plus `-moc.md`, in **`MOCs/`** (`#machine-learning` →
  `MOCs/machine-learning-moc.md`). The suffix keeps the MOC's basename apart
  from its Wiki root's. MOC navigation links use
  `[[MOCs/machine-learning-moc]]`; **no MOC may be a `parents:` target**.
  The hierarchy root is the separate entry `[[machine-learning]]`, whose
  own parents are `[]`. MOC tree links and parent forms are in §6.
- **Misc Wiki entries:** an entry whose sole tag is `"#misc"` has
  `[[misc]]` as its sole parent and appears in `MOCs/misc-moc.md`.
  [Hierarchy](../skills/wiki-lint/references/hierarchy.md) owns the
  `Wiki/misc` root and misc outline; QC
  [item 8](../skills/wiki-lint/references/qc-items.md#8-tags) owns repair of
  blank or empty tags.

**Depended on by:** wiki-build (assigns them, and its `scripts/lint_entry.py`
carries the list as `TAG_ENUM`), wiki-lint (validates and format-fixes them,
derives MOCs and the hierarchy from them; `scripts/scan_vault.py` carries the
list as `VALID_TAGS` plus safe abbreviation expansions in `TAG_ALIASES`),
clipping-clean (assigns them to cleaned notes), paper-summarize (assigns
them to summary notes; its `scripts/note_lint.py` carries the list as
`TAG_ENUM`), wiki-add (assigns them to new entries using the same
rules).

---

## 4. Slugs and filenames

### 4a. Wiki-entry slugs — `shared/scripts/slugify.py`

**The algorithm is the script, not a table.** `shared/scripts/slugify.py` is the
single canonical implementation; it carries a self-test of worked examples:

```bash
python3 '<plugin>/shared/scripts/slugify.py' 'C++'          # -> {"slug": "c-plus-plus", ...}
python3 '<plugin>/shared/scripts/slugify.py' 'C++' --stem   # -> c-plus-plus
python3 '<plugin>/shared/scripts/slugify.py' '-ase' --stem  # -> ase
python3 '<plugin>/shared/scripts/slugify.py' --test         # reports the passing case tally
```

As a module: `slugify(title)` → `"<slug>.md"`, `slug_stem(title)` → `"<slug>"`,
`base_term(title)` strips a space-separated trailing parenthetical
disambiguator (unspaced notation such as `SU(2)` stays whole), and
`mu_variants(title)` returns both µ spellings for the collision probe.
`SlugError` is raised when a title reduces to the empty slug, or when the stem
it produces exceeds the module's `MAX_STEM_BYTES` filename budget.

**Do not restate the table.** The preprocessing order is load-bearing: special
characters are substituted *before* the NFKD fold, which would otherwise
canonicalise distinct codepoints to one character. The script's docstring is
the explanation; the code is the rule.

**What an empty slug means.** A title that reduces to nothing (an all-symbol
title, a CJK title) is **not** slugged automatically — ask the user to retitle.
Writing a file literally named `.md`, or renaming an entry to `""`, is the
failure this raises to prevent. **An over-long slug is the same class**: past
the module's `MAX_STEM_BYTES` budget the eventual write dies with
ENAMETOOLONG, so the module raises `SlugError` there too — ask the user for a
shorter title rather than crashing the write.

**Consequences worth knowing without opening the script:** the slug derives from
the **full** title including any parenthetical (`Feature (machine learning)` →
`feature-machine-learning.md`), while the **base term** (`Feature`) is what the
body opener, the description subject and the flashcard answer use. `C`, `C++`,
`C#` and `C*` produce four distinct slugs, not one.

**Depended on by:** wiki-build (names every entry; `scripts/find_collisions.py`
and `scripts/lint_entry.py` import it), wiki-lint (recomputes a slug from
`title:` to find rename candidates and names the entries it retitles or
creates — `scripts/scan_vault.py` imports it too, and wraps
`slug_stem` in a `slug()` that returns `""` where the canonical module raises
`SlugError`), wiki-add (names requested entries with builder's collision and
slug helpers; it implements no other slug algorithm). A second implementation
would turn correctly named entries into false rename candidates.

### 4b. Aliases use the same slug rule

Every `aliases:` item is slug-form, because aliases *are* alternative slugs: a
future candidate that slugs to one of them resolves to this entry. An alias that
slugs identically to the filename is redundant — omit it.

**A semantic-invalid alias or a wrong title is a vault-wide repair, not a
local cleanup.** Removing an alias can redirect every inbound wikilink that
resolves through it, and a title or slug correction is a whole-entry rename,
not an alias-list edit. wiki-build never renames an existing entry or removes
its alias; it reports one it can disprove from the active source. wiki-lint
owns vault-wide discovery and, in an ordinary run's content-repair step,
applies the fix through its
[retitle](../skills/wiki-lint/references/refactors.md#retitle-an-entry) or
[alias-removal](../skills/wiki-lint/references/refactors.md#remove-a-semantic-invalid-alias)
protocol, which rewrites the inbound references it inventories before
retiring the old slug or alias. It retitles an entry whose title is a bare
cross-domain term under wiki-build's
[cross-domain tests](../skills/wiki-build/references/special-titles.md#cross-domain-term-disambiguation)
when the qualified title is determinate under those tests and its slug is
free (`Tree of life` becomes `Tree of life (biology)`, slug
`tree-of-life-biology`). It retitles an entry whose title is itself an API
identifier to its determinate conceptual title, retitles one whose
acronym-or-full-form choice breaks wiki-build's
[title rule](../skills/wiki-build/references/writing.md#title) to that rule's
determinate form (`PPO` becomes `Proximal policy optimization`), retitles
an `Organism` titled by a common name to the scientific name wiki-build's
[Organism rule](../skills/wiki-build/references/rare-types.md#the-ten-rare-types)
requires (`Zebrafish` becomes `Danio rerio`), and retitles a split's retained original whose title does not name exactly the
one subject it keeps, each when the new slug is free. It renames an entry whose filename does not match
its title's slug when that slug is free. It removes an alias proven to name
another entity, such as a bare cross-domain word, and the old bare
cross-domain slug of a retitled entry never stays as an alias. A retitle or
removal that these rules do not decide, such as a disputed intended title or
an occupied destination, is reported with the intended title, slug,
inbound-reference count and collision risk. A request naming one runs the
same protocol with no second human review. A duplicate spelling inside one
alias list is a format defect, not this semantic-removal case.

### 4c. Source-note filenames are a *different* rule

No producer of a §2b note uses the Wiki `slugify.py` rule for its filename.
PDF reading notes inherit a filename; URL-origin notes derive one.

**A summary note takes its PDF's stem, unchanged.** `Articles/Doe_Foo_2025.md`
for `Sources/PDFs/Doe_Foo_2025.pdf`. There is no derivation and no
judgment: the shared stem keeps the note's filename, figure glob and `sources:`
link aligned (§1a). It is a naming convention, not proof of existing ownership;
confirm a PDF/summary pair from the note's decoded origin as required in §7.
paper-summarize inherits the organizer's established name, or the deliberately
retained name under its reported naming exception.

**A clipping note is derived, because there is no file to inherit from.**
Its filename is `[<Author>_]<short_topic>_<year-or-nd>.md` — the first author's surname in
original case, omitted when there is no clean human author, a Title-Cased
2–4-word topic, and either a 4-digit year or `nd`, joined by underscores
(`Teslo_Pancreatic_Cancer_2026.md`, `LLMs_Deep_Dive_2025.md`). The mechanics
live in `clipping-clean/scripts/slug.py`; the judgment calls (which words
identify the topic, multi-author strings, suffixes, acronym and brand casing)
are in `clipping-clean/references/filename-slug.md`.

The rules must not be confused: kebab-case-lowercase is for wiki entries,
Title_Case_Underscored is for notes about sources. What connects them is §8 —
a source note's stem *is* the source stem the figure glob keys to, whether that
stem was derived from a web page's metadata or inherited from a PDF.

**Depended on by:** clipping-clean and paper-summarize (4c); wiki-build
and wiki-lint (4a, 4b); wiki-add (4a, 4b).

---

## 5. Reaching `shared/scripts/` from a skill

The plugin installs as one tree, so a skill script can reach `shared/scripts/`
by walking up from its own `__file__`. But a skill can also be **extracted
alone**, and then there is no `shared/` above it. Three things must not happen:
vendoring a second copy of the algorithm, dying with
a bare `ModuleNotFoundError` that tells the user nothing, or letting an
unrelated module on `PYTHONPATH` shadow a sibling script module.

Immediately before the snippet, assign `_OBSIDIAN_SHARED_MODULES` to a sorted,
literal tuple naming the shared modules the script and its sibling imports
need, without `.py`; for example,
`_OBSIDIAN_SHARED_MODULES = ("naming", "yaml_scalars")`. The convention test
derives this transitive import closure and rejects an incomplete declaration.
The default is `("slugify",)`, so the standalone pasted snippet still probes a
real module.

**Paste this snippet verbatim** after that declaration. It is path arithmetic,
and the test asserts every copy in the tree is byte-identical to
`plugin_paths.BOOTSTRAP`:

```python
# --- obsidian shared-layer bootstrap (canonical; see shared/RUNTIME.md) ---
import os as _os, sys as _sys
_here = _os.path.dirname(_os.path.realpath(__file__))
_required = tuple(_m + ".py" for _m in (
    globals().get("_OBSIDIAN_SHARED_MODULES") or ("slugify",)))
_env = _os.environ.get("OBSIDIAN_VAULT_SHARED")
if _env:                                   # explicit override: authoritative, no fallback
    _tried = [_os.path.abspath(_os.path.expanduser(_env))]
else:                                      # plugin-relative walk-up, at most 5 levels
    _tried, _d = [], _here
    for _ in range(5):
        _tried.append(_os.path.join(_d, "shared", "scripts"))
        _d = _os.path.dirname(_d)
    _tried.append(_here)                   # extracted skill with co-located helpers
_missing = {_p: [_m for _m in _required if not _os.path.isfile(_os.path.join(_p, _m))]
            for _p in _tried if _os.path.isdir(_p)}
_shared = next((_p for _p in _tried if _p in _missing and not _missing[_p]), None)
if _shared is None:
    raise SystemExit("""obsidian: cannot find the plugin's shared/scripts/ folder, which holds
the one canonical copy of the conventions this script depends on. A usable
folder must contain these required module(s): %s
Looked for:
  %s
Fix: install the whole plugin tree, or set OBSIDIAN_VAULT_SHARED to the
shared/scripts/ directory (unset it to use the plugin-relative walk-up).
Do NOT paste a second copy of the algorithm into this skill -- a divergent
copy is the bug the shared layer exists to prevent.""" % (
    ", ".join(_required), "\n  ".join(
        _p + (" (not a directory)" if _p not in _missing else
              " (missing: %s)" % ", ".join(_missing[_p]))
        for _p in _tried)))
_sys.path[:] = [_p for _p in _sys.path if _p not in (_shared, _here)]
_sys.path.insert(0, _shared)               # shared/scripts/ FIRST
if _here != _shared:
    _sys.path.insert(1, _here)              # sibling modules before unrelated paths
# --- end bootstrap ---
```

Then imports from `shared/` and co-located modules from the skill's own
`scripts/` both work, because the snippet puts both directories on `sys.path`.
Print it any time with
`python3 '<plugin>/shared/scripts/plugin_paths.py' --bootstrap`.

The bootstrap consults `$OBSIDIAN_VAULT_SHARED` first, then walks up for the
plugin root. A directory is usable only when every declared shared module is
present; an empty or wrong override therefore reaches the actionable
resolution error before Python reaches the import. The override is
authoritative: unset it to use walk-up resolution.

`shared/scripts/` is first on `sys.path`; the skill's own `scripts/` directory
is immediately second. A stray shared-module copy beside a script cannot
shadow the canonical module, while a same-named package on `PYTHONPATH` or in
site-packages cannot shadow a legitimate sibling such as `vault_index.py`.
When nothing resolves, the error names every searched location, each missing
module, and the one-line fix.

**Richer resolution — `shared/scripts/plugin_paths.py`.** Once the bootstrap has
run, `import plugin_paths` gives the full search with diagnostics:

1. `$OBSIDIAN_VAULT_SHARED`, if set — the explicit escape hatch. It must be a
   directory containing every requested module; an empty, partial or wrong
   directory is an error, never a silent skip. Unset it to use walk-up.
2. **Plugin-relative walk-up** (the normal path): the first ancestor within 5
   levels whose `shared/scripts/` contains every requested module. When none
   is named, those are the modules the starting script declares in
   `_OBSIDIAN_SHARED_MODULES`, else `slugify`, exactly as its bootstrap
   requires. From `skills/<skill>/scripts/` the plugin root is 3
   levels up, so 5 leaves slack without wandering into `$HOME`.
3. **Co-located fallback:** the script's own directory, if it holds the modules.
   This is the skill-extracted-alone case. It is supported so the skill still
   runs — and reported by `describe()`, so a local copy is visible rather than
   silently authoritative.

Failure raises `SharedLayerNotFound` (a subclass of `ImportError`) whose message
names every location tried, gives the one-line fix, and says explicitly not to
work around it by pasting a second copy of the algorithm.

Diagnose an install with:

```bash
python3 '<plugin>/shared/scripts/plugin_paths.py' \
  --from '<plugin>/skills/wiki-lint/scripts/scan_vault.py'
```

**Depended on by:** every skill script importing a shared module. Each carries
the bootstrap verbatim; shared algorithms are not copied into skill folders.

The shared modules own these rules: `slugify.py` (§4a), `plugin_paths.py` (this
section), `atomic_move.py` (exclusive source-family moves plus verified
regular-file creation, replacement, and removal; late source/destination
occupants are preserved and unsupported directory moves fail closed),
`publish_files.py` (the command-line form of the
[safe-write](SAFE_WRITES.md#call-the-shared-python-api) regular-file recipe:
`snapshot`, `verify`, `publish`, `remove` and `move` against recorded
snapshots),
`naming.py` (§1a), `plurals.py` (English inflection and light
collision stemming shared by both Wiki skills), `organism_names.py` (Organism
name and typography evidence shared by both Wiki skills), `entry_structure.py`
(shared sentence, opener, answer-surface, flashcard structure, and
meaning-preserving mathematical-title plain-text conversion),
`markdown_tables.py` (Markdown-table
spans and caption checks shared by both Wiki skills), `equation_coverage.py`
(the conservative missing-display, well-definedness-boilerplate,
one-equation-per-line and card-equation candidates and the non-norm `\ell`
check shared by both Wiki skills; paper-summarize's
`note_lint.py` reports the one-equation-per-line candidates as advisories),
`code_typography.py` (bracket special tokens and literal file extensions that
need backticks in prose), `introduced_aliases.py` (alternate names that body
prose introduces for the entry's subject), `entry_checks.py` (the per-entry
Wiki floors both Wiki linters apply: the cross-domain common-noun slug, non-`Software`
API surface, the description's entity subject, an acronym title's missing
full form in the opener, a list item's display, paragraph or nested list
indented short of its text column, merge scars, source-meta phrasing, emphasis, display
labels (including a label that drops its target title's head word), the
single-word alias hint, the card-set shape, the primary flashcard among
several and its answer on card line 3, Spaced
Repetition markers, and the discipline-root test),
`check_parsers.py` (installed-version floors for the PDF and image parsers,
knowledge only), `figure_state.py` (§8b),
`portable_names.py` (NFC + case-fold filename identity used for case and
normalization collisions), `vault_artifacts.py` (portable
PDF/Markdown source ownership, qualified local-link matching, and flat
source-figure inventories in §§1a, 7 and 8a), `note_provenance.py` (verified
plugin-bundle identity and legacy footer reading; see
[PROVENANCE.md](PROVENANCE.md)), and `yaml_scalars.py` (§2).

`yaml_scalars.py` decodes the single-line scalar values used in frontmatter:
YAML double-quote escapes, doubled apostrophes in single quotes, trailing
comments and bare null values. It is not a document parser. Callers still
validate fences, field types and schema-specific quoting. Its `text_scalar`
rejects a title, description or alias that decodes to a control or
line-separator character, such as a single-backslash `\tau`. Its
`plain_string_allowed` is the §2a lossless-plain test that both entry
checkers share. Its `parse_source_fields` helper reads the supported origin mapping and validates
the complete current list, decoding keys before rejecting ambiguous ownership.
An empty current `sources` never falls through to legacy `source`;
unsupported or malformed input must be reported rather than supplying a
guessed title or source identity. Frontmatter lines break only at CR, LF and
CRLF; U+2028, U+2029 and NEL are content. A quoted or flow value continues
only on indented lines, so one that runs into an unindented line or past the
closing fence is malformed. Reading a valid alternative YAML spelling
does not change the canonical output forms in §2.

---

## 6. Wikilink forms

| Form | Use |
|---|---|
| `[[slug]]` | body link whose display label would equal the slug |
| `[[MOCs/<discipline-slug>-moc]]` | discipline MOC navigation link only; never a `parents:` value |
| `[[slug]]` in `parents:` | parent that is a broader Wiki entry, including a discipline root (`[[machine-learning]]`, `[[misc]]`); use `[[Wiki/<entry-path>]]` only when another Wiki file, a `MOCs/` file or a legacy MOC shares the basename. A discipline root itself has `parents: []` |
| `[[Wiki/<relative-entry-path>\|Label]]` | every generated MOC tree entry link; use the actual vault-relative Wiki folder prefix and no `.md`. Labels follow [hierarchy](../skills/wiki-lint/references/hierarchy.md#build-or-maintain-the-moc-files) |
| `[[slug\|Display Label]]` | body link whose label differs by case, spacing or alias |
| `[[Wiki/<entry-path>\|Label]]` | body or Related link to an entry whose bare basename has another real vault owner, such as a discipline root beside a previous-layout MOC (`[[Wiki/statistics\|statistics]]`); never guess an ambiguous owner |
| `[[slug\|Canonical Title]]` | **every** `**Related:**` footer link to an entry, path-qualified as above when the basename is shared — always piped, even when slug-equal |
| `![[file.png]]` | image embed from `Sources/Images/` (Obsidian resolves the basename vault-wide) |
| `![alt](https://…)` | an existing remote image in an older URL-origin source note, or in an entry that reuses one: keep its Markdown form, since changing only its syntax to `![[…]]` resolves to nothing and loses the URL. Only clipping-clean replaces one, by downloading it (§8). An entry that cites a page only by its URL (§7) never hotlinks that page's images |
| `"[[file.pdf]]"` | a **link** to a local document — quoted, no anchor. This is `sources:` item 1 of a note about that document (§2b). Resolves **by basename, vault-wide**; §1a is what makes that safe |
| `![[file.pdf]]` | PDF **embed**, rendering the document inline. No skill here writes one today; a legacy note left by an older producer may carry one, and it is left alone (paper-summarize reports such a note as `legacy`; pdf-organize treats an embed-only note as the PDF's summary) |
| `[[Name.pdf#page=N]]` | source reference, §7 |

Rules that hold everywhere:

- **Every entity-link and `parents:` target must be a real file in `Wiki/`.** MOC navigation
  links instead name a real file in `MOCs/` using
  the qualified form above. No entry target, no entity link: an
  entity with no entry stays bare text.
  wiki-build either writes the entry or defers the entity (report-only);
  wiki-add creates only requested missing entities, so any unrequested missing
  target stays bare text;
  wiki-lint creates a missing entry its own run establishes (§9) and links
  its mentions in the same run; Task 1b first glosses each dangling term whose
  concept has no entry and whose sentence needs its meaning, and a link to a
  missing discipline root that Task 3 creates is held for that root.
  wiki-lint points a dangler whose concept already has an entry at that
  entry, drops other danglers to bare text, reports the remaining missing-entry candidates with the routes
  in §9, and backfills a link once a real entry exists. A hand-written link
  to a real vault note outside `Wiki/` and `MOCs/` is not a dangler:
  wiki-lint, and wiki-build in an entry it merges, keep it and report it.
- **`tags:` values are never wikilinks** (§3) and `sources:` points at documents,
  not entries (§7); neither participates in link audits.

Body-link placement (the first eligible occurrence of each resolved entry,
no self-links or navigation-only links, none in captions or table cells) and
display labels, including the four label carve-outs that must not be
"fixed", follow wiki-build's
[link form](../skills/wiki-build/references/writing.md#link-form) and
[display-label casing](../skills/wiki-build/references/writing.md#display-label-casing);
wiki-lint enforces them vault-wide (§9).

**Depended on by:** wiki-build (writes links inside its own entries),
wiki-add (links only inside its new requested entries),
wiki-lint (owns them vault-wide — §9), clipping-clean (`![[…]]` image
embeds), paper-summarize (the quoted `"[[file.pdf]]"` origin, `![[…]]` figure
embeds, body links to existing entries in its reading notes, and legacy
PDF-embed notes), pdf-organize (renaming a file changes
what every `[[…]]` naming it resolves to — §1a).

---

## 7. Source references

Every Wiki entry follows the same source-backed schema and requires real
source references; insufficient source coverage means no entry and a deferred
entity. An entry's `sources:` list names the documents that contributed to it.
Each item is written double-quoted and takes one of three forms; on lint a
plain `http(s)://` URL item also conforms (§2a). A vault document is a
wikilink carrying its **literal on-disk filename, extension included** — not a
slug, never invented, never renamed. An online page is its URL.

- **PDF:** `"[[Author_Title_Year.pdf#page=N]]"` — always with a page anchor;
  `N` is a positive decimal written without leading zeros (`[1-9][0-9]*`).
- **Markdown note:** `"[[Author_Title_Year.md]]"` — never an anchor.
- **Online page:** `"https://example.org/page"` — the full, verified `http(s)`
  address of the page actually read, with no display text or Markdown link.
  wiki-add cites one for a web page it researched, wiki-lint for the page a
  missing entry it creates was researched from or an entry with an empty
  `sources:` was verified against, and wiki-lint's missing-root
  prerequisite for the reference page a new root is derived from; each points
  to the page and never creates a note in `Articles/` just to have something to cite.
  Cite the page's canonical address, not a tracking, mobile or AMP variant,
  ranking its `<link rel="canonical">` over its `og:url` as wiki-add's
  [webpage rule](../skills/wiki-add/references/research.md#cite-a-webpage)
  details; keep a version-specific address only when the entry relies on that
  version, and list each page once. A URL never stands in for a vault document: when the
  vault holds the same document, cite that file only as wiki-add's
  [local-source rule](../skills/wiki-add/references/research.md#find-local-sources-first)
  allows; otherwise route the document to wiki-build and cite neither.

**`N` is the physical page** — the 1-indexed position within the PDF file, what
a viewer reports as "page X of Y" — **not the folio printed on the page.** A
book-chapter PDF whose chapter starts at printed page 87 has its first page at
`#page=1`.

**A document is cited in one representation, never two:** the PDF or its
summary note, a chapter PDF or its whole book, the vault file or its URL.
Different physical pages of that representation may each be cited, and the
same PDF legitimately appears with *different* anchors in different entries —
each entity is anchored where it is introduced.

**On a merge, compare full citations, including page anchors.** Do not append
an exact item, wikilink or URL, already present, and keep every existing URL
item exactly as written and in place, except for the same-document
replacement below. Preserve existing anchors. If a
rerun chooses another introducing page and adds that citation, report the
anchor drift under *Notes for the user* rather than appending it silently.

**Do not cite both representations of a verified PDF/summary pair.** A PDF
summary in `Articles/` (§2b) takes its PDF's stem, so `X.pdf` and `X.md` can
represent one document. An unrelated web clipping can also happen to have that
stem. **A matching stem is a provenance-review candidate, not proof of
identity.**

Before dropping a Markdown item, read that note's decoded `sources:` item 1
(legacy `source:` is a fallback only when `sources:` is absent). If it names
this PDF, retain the PDF citation and remove the redundant summary-note
citation. This is a replacement on a merge, not an append. If the note instead has a distinct URL origin, retain both
sources. Missing, malformed or ambiguous provenance is report-only: never
delete a source reference on the strength of its filename alone.

**A URL item and a vault copy of the same document are one document.** A
merge's active source replaces an entry's URL item, and the replacement is
reported, when it is proven to be that document: a clipping whose decoded
`sources:` item 1 clipping-clean's URL normalization matches to the URL, or a
PDF whose printed DOI or arXiv identifier is the one the URL names. Without
that proof both stay and the pair is reported. Outside that replacement a
merge never rewrites or removes a URL item. wiki-build and wiki-lint's
source-independent QC never fetch one; wiki-lint's content repair (Task 1b)
may read a cited URL's page to verify or correct the entry citing it, and
wiki-add, like wiki-lint researching a missing entry, may inspect one as a
research lead.

Candidate comparison strips the wikilink wrapper, display label, page anchor
and folder qualification, then folds case and normalises the basename stem to
NFC. Only matches **across PDF and Markdown extensions** enter this review;
several distinct PDFs or clippings remain separate sources. Filename matching
does not replace the origin check.

**Source-independent QC checks `sources:` format, not source existence.** In
Tasks 1–3 a URL item is checked for its form only and is never fetched. The
orphan audits of §9 skip `sources:` entirely. Task 1b's content repairs,
splits and merges, the entries it creates and requested refactors have their
own citation scope. A repair that reads another page of a document the
entry already cites adds no citation, and the standard references Task 1b
reads online under its
[evidence rule](../skills/wiki-lint/SKILL.md#task-1b--content-repair) are
data, never cited. No repair newly
cites a source to fill a gap only that source teaches; that gap waits for
wiki-build. A consolidation carries a moved claim's existing citation into
its owner's `sources:`. A missing entry follows §9's citation rule. An
entry whose `sources:` is empty cites the page or document Task 1b verified
it against
([item 4](../skills/wiki-lint/references/qc-items.md#4-sources)). A
refactor rewrites only proven dependencies under its complete
inventory, never independent source origins or mere token matches. Routine QC/link hygiene
does not repair citations to renamed or removed files: the skill that renames
a file repairs them in the same run, and the rename request authorizes that
repair. §1a's ordering and pdf-organize's rename repair keep PDF references
aligned; clipping-clean's changed-slug repair rewrites every parsed reference
that resolves to the old clipping note or a mapped old image before retiring
them.

The same-stem candidate check above, and a chapter PDF cited beside its
whole-book PDF, are mechanized on **both** sides through
`entry_checks.source_identity_pairs` —
`wiki-build/scripts/lint_entry.py` as `4-duplicate-source` and
`wiki-lint/scripts/scan_vault.py` as `item4/source-identity`. Neither
same-stem report authorizes deletion without the provenance check above.

**Depended on by:** wiki-build (writes them, and decides prior coverage only
from decoded `sources:` identity in verified-path mode; a body mention or an
unconfirmed basename candidate never establishes coverage.
[Source intake](../skills/wiki-build/references/source-intake.md#check-prior-coverage)
owns the query, its resolution-tree choice and its result fields), wiki-add
(cites in these forms, reuses existing sources only under its
[local-source rule](../skills/wiki-add/references/research.md#find-local-sources-first),
leaves an existing topic untouched, and cites a new URL for a researched
page, as wiki-lint's missing-root prerequisite does),
wiki-lint (checks the format in routine QC; its content repair and the
missing entries it creates keep the citation scope above),
clipping-clean (its cleaned notes are Markdown sources, and its changed-slug
repair rewrites citations to a renamed clipping),
paper-summarize (its notes put the same wikilink form in `sources:` item 1,
and are the Markdown half of a verified PDF/summary pair), pdf-organize (§1a).

---

## 8. Figure naming and `Sources/Images/`

`Sources/Images/` is **flat** and shared. Every figure filename begins with the
**source stem** — the PDF's or cleaned note's filename without its extension —
so figures from any source are findable by prefix.

### 8a. The consumer rule (the one that matters)

<!-- canonical:figure-glob -->
```
[source_stem]_fig*
```
<!-- /canonical -->

**Match on `[source_stem]_fig`, never on `[source_stem]_fig_`, and accept any
extension.** This includes older separator forms (§8c) as well as current
output. Use the same broad inventory for selection and unused-figure reporting.
PDF output is `.png`; clipping-clean emits the extensions in the
`clipping-image-extensions` block below, according to the bytes it actually
downloads. It converts a TIFF or ICO download to PNG before publication,
because Obsidian does not display either format. Consumers still accept any
extension, including existing `.tiff` and `.ico` files, rather than copying
this producer list into a restrictive glob.

The code block states the matching contract, not a shell-glob recipe. Consumers
that select source figures use the shared portable inventory:

```bash
python3 '<plugin>/shared/scripts/vault_artifacts.py' figures \
  --images '<vault>/Sources/Images' --stem '<resolved_source_stem>'
```

The resolved stem belongs to the source actually read: the chosen PDF after
any summary substitution, or the cleaned Markdown note. The helper compares
the literal loose prefix under NFC normalization and case folding. Its
`candidates` are direct regular non-staging files with unambiguous portable
names. It reports and excludes symlink/nonregular occupants, nested matches,
portable-equivalent names and recognizable staging residue; an unreadable
scope never proves absence. Read the complete JSON and do not consume
`blocked_matches`.

wiki-lint's whole-folder image index keeps the same portable identity for
embed existence while preserving every path in a report-only
`portable-name-collision` group. Thus an ambiguous basename remains present
for missing-image checks without hiding the ambiguity or authorizing cleanup.

<!-- canonical:clipping-image-extensions -->
```
png, jpg, gif, webp, svg, avif, bmp
```
<!-- /canonical -->

### 8b. The producer conventions

Both knowledge producers write the **same** shape — `_fig_` then the
number — and differ only in where the number comes from:

| Producer | Pattern | Number form | Example |
|---|---|---|---|
| `figure-extract` | `[pdf_stem]_fig_<N>.png` | caption label, dots and numeric en dashes → ASCII **dashes** | `Figure 1.2` → `..._fig_1-2.png` |
| `clipping-clean` | `<note_stem>_fig_<N>.<ext>` | sequential from 1 in capture order; audit recoveries and reprocess additions continue after the highest occupied number | `Teslo_Pancreatic_Cancer_2026_fig_3.webp` |

Feed-owned attachments follow the separate source-collection route in §1c.
They are not numbered knowledge figures and never enter the PDF extractor's
`.figure-manifest.tsv`; their source URLs and content digests live in feed state.

**figure-extract's `auto_fig_bbox.py`, `extract_figures.py` and
`render_page.py` own PDF figure cropping.** Call those helpers instead of
copying their algorithms into another skill.

**`pdf_stem` is the source PDF's on-disk stem, `_src` suffix included** — not
a summary note's stem. Consumers inventory figures by the stem of the source
they actually read (§8a), so a PDF figure filed under its summary note's stem
is invisible to them.

Shared sub-rules:

- **Supplementary markers fold to `S`.** `Supplementary Figure 1`, `Suppl. Fig. 1`,
  `Supp. Figure 1` and `Extended Data Figure 1` all become `_fig_S1` by default;
  `--ed-prefix ED` gives Extended Data its own namespace, and figure-extract's
  batch applies it by itself to a PDF whose `_fig_ED<N>` crops already exist.
  In a vault, switching a PDF to `ED` writes each Extended Data figure as
  `_fig_ED<N>`, and the same run points every link to its `_fig_S<N>` crop
  at the ED name before a Supplementary figure replaces that S crop. An S
  crop no Supplementary caption claims stays beside its ED crop as a
  leftover for the user to delete; such a crop's `S<N>` is missing from
  `python3 '<plugin>/skills/figure-extract/scripts/auto_fig_bbox.py' '<pdf>' --ed-prefix ED`.
  Consumers never embed or count that leftover, and report it for
  figure-extract.
  `SI` (Supporting Information) keeps its own namespace.
- **Legacy panels end in a lowercase letter inside `<N>`**, for example
  `Doe_Method_2025_fig_1a.png` beside the composite `_fig_1.png`. These remain
  valid inputs, but no producer creates new per-panel files. Preserve the
  lowercase letter and existing separator; case variants can collide on the
  vault's filesystem.

  **A whole figure's label never ends in a lowercase letter**: caption labels
  end in a digit (`1`, `S1`, `1-2`, `ED2`), and `Figure 1a` is rejected as a
  caption because it points at a panel. A consumer may therefore split
  `_fig_1a` into figure `1` and panel `a`.
- **Consumers prefer the composite.** 8a's glob matches panels too, so every
  consumer **embeds the whole figure by default, uses a panel only when the
  point is that one panel's, and never counts an unplaced panel as an unused
  figure.** Placing a panel discharges its parent, and placing the parent
  discharges every panel under it. Another tool's crop with an uppercase
  panel letter, such as a slide deck's `_fig_1A_B`, is a panel of its figure
  to every consumer.
- **PDF crops exclude captions and publisher frames by default.** Caption
  text is written next to the embed. The extractor documents deliberate frame
  overrides; web-image downloads preserve the source image's bytes.
- **The URL-origin note's stem *is* the source stem.** `Teslo_Pancreatic_Cancer_2026.md`
  → `Teslo_Pancreatic_Cancer_2026_fig_1.webp`. Same string, same casing. This is
  what lets wiki-build find a clipping's or research extract's images when it
  processes that note as a source. Don't diverge from it.
- **Captions sit immediately below the image embed**, italic, with no blank
  line between. Wiki and summary writers add explanatory captions under their
  own content rules. Clippings preserve source captions and add none to a
  captured image that has none; an image recovered by clipping-clean's
  [completeness audit](../skills/clipping-clean/references/completeness-audit.md#recover-missing-images)
  is captioned only through that audit's evidence-based fallback chain, which
  marks any synthesized text.
- **Nothing unfinished is ever written into the folder.** A download, a render
  or a format conversion happens at a temp path *outside* `Sources/Images/`,
  and only the finished file is moved in, under its final name and with the
  extension its own bytes justify. The two producers, the feed collector and
  pdf-organize's rename workflow share this folder; consumers can encounter any
  visible file. A same-filesystem rename or atomic link publishes the finished file without a
  window in which the name holds partial bytes. A cross-filesystem move may
  copy directly into its destination; stage on the destination filesystem,
  outside `Sources/Images/`, before publishing. A failed replacement must leave
  the previous good file intact.

**Figure ownership uses PDF records and conservative web-source checks.**
Producers compute names from a stem in a flat, shared folder, so different
sources can compute the same name. `shared/scripts/figure_state.py` is the
common parser for the PDF ownership manifest, the review ledger and
`.figure-ed-pending.txt`, figure-extract's record of `_fig_S<N>` crops that
still hold an Extended Data figure; it refuses malformed or ambiguous records
rather than treating them as permission to write.

- **The rule every producer follows:** a producer
  never overwrites a name it did not write, and a name it cannot attribute is
  **reported, never taken**. Refusing is the safe failure — a figure that is
  not written is visible in the run report, where one that is silently replaced
  is not.
- **Each producer's procedure owns its guards:** figure-extract's
  [ownership procedure](../skills/figure-extract/references/review-and-repair.md#ownership-legacy-adoption-and-review-records)
  (the `.figure-manifest.tsv` sidecar, portable-slot occupancy,
  `--adopt-legacy` and explicit crops),
  pdf-organize's [owned-family rule](../skills/pdf-organize/references/rename-repair.md#establish-the-owned-family)
  (it moves only manifest-owned figures), clipping-clean's
  [image](../skills/clipping-clean/references/images.md#download-and-publish)
  and [changed-slug](../skills/clipping-clean/references/duplicates-and-reprocessing.md)
  procedures (owner notes; recorded PDF slots and same-stem-PDF renames are
  refused), and wiki-add's
  [research guide](../skills/wiki-add/references/research.md#optional-images-and-publication-order)
  (existing images are reused read-only; PDF crops come only from
  figure-extract on a PDF it newly acquired).

### 8c. Legacy figure names: read, never produced

Older output sometimes placed the number directly after `_fig`. Existing
images keep those names; reading them does not authorize renaming or deletion.
The broad glob preserves their visibility and keeps naming anomalies visible
to the unused-figure diagnostic. All new knowledge figure output follows §8b;
the legacy form is a reading compatibility rule, not another permitted
producer convention.

**Depended on by:** figure-extract (produces; its Extended Data switch
repairs the links to each `_fig_S<N>` crop it re-extracts as `_fig_ED<N>`,
with pdf-organize's reference scan
and rewrite), clipping-clean
(**produces and consumes** — its `rename` path re-reads `Sources/Images/`
through 8a's loose glob to carry a note's whole figure set across a slug
change), wiki-build (consumes — the figure selection and unused-figure
accounting both walk 8a; PDF crops come only from figure-extract), wiki-add
(consumes suitable existing images; uses figure-extract for crops of a PDF it
newly filed), paper-summarize (consumes —
`scripts/paper_scan.py` walks 8a to inventory a stem's figures; PDF crops come
only from figure-extract), wiki-lint (checks embeds and reports flat-folder or
unfinished-artifact violations without moving/deleting them), pdf-organize
(its rename moves manifest-owned `<stem>_fig*` figures with the PDF
and blocks on any unrecorded occupant, §1a; another tool's crop of the same
PDF, such as a slide deck's, shares the stem and keeps its name by
[rename repair's label test](../skills/pdf-organize/references/rename-repair.md#establish-the-owned-family)).

---

## 9. Ownership split for linking

Linking is split by **workflow and reach**: wiki-add creates requested missing
entries, wiki-build extracts or merges new evidence from selected sources,
and wiki-lint maintains the existing wiki and its links within its run's
scope, including the missing entries its own run establishes.

Shared schemas, naming and link forms are defined in this file. wiki-build's
references own entry prose and the Related-footer and Flashcards formats.
wiki-add applies them to new requested entries, and wiki-lint applies them
to its repairs and the entries it creates; neither creates a competing
writing standard.

**Missing-entry routes.** wiki-lint creates a missing entry in its
content-repair step (Task 1b) only when its
[missing-entry rule](../skills/wiki-lint/references/refactors.md#create-a-missing-entry)
establishes it. That rule is the single owner of the creation test: a user
issue (§2d) asking for the concept's entry, an open
item of `Reviews/wiki-notes-suggestions.md` naming the concept (wiki-build
and wiki-add record there the missing entries their published prose mentions
in plain text) or the three-use
count of a load-bearing term, plus a stable identity that passes
wiki-build's substance and atomicity tests. The entry follows
wiki-build's entry rules. Its research may read the vault's PDFs and
`Articles/` notes under wiki-add's local-source rule, but it cites a document
the entries using the term already cite, at the page that teaches the term,
or else a reliable web page by URL. It never cites a document no entry cites,
and never acquires or files a PDF; Task 2 then links the mentions and Task 3
places the entry. A user's request for a new topic in chat goes to wiki-add
or wiki-build. For any other real
topic with no entry, report both routes:
wiki-add can research it (named directly, or queued in `add-to-wiki.md`, where
only the user adds topics), or wiki-build can build it from a supporting
source: a request naming that whole chapter or document, which fills in the
source's topics and leaves entries that already cite it untouched. An entry
citing a source does not show that the source was built as a whole, so a
[named-entity request](../skills/wiki-build/SKILL.md#named-entity-requests)
is the route only when the user asks for just that entity or when wiki-build's
deferral report names sources that are substantive only in combination. A
thin entry whose missing teaching lives only in a source it does not cite
waits for that same whole-source request; that rule governs deepening an
existing entry, not the source of a new one. Neither wiki-build nor wiki-lint
writes the queue.

### wiki-add — inside new requested entries only

wiki-add applies builder's entry-writing and linking rules to the missing
topics the user requested, whether queued or named directly. New entries have
`parents: []` and `read: false`. Their links may target existing entries,
including requested entries published earlier in the same run; a mention of
one published later stays plain text for wiki-lint's backfill. An existing
identity is skipped without auditing, merging, normalizing or otherwise
editing it. No inbound-link backfill, parent population or MOC work belongs to
this route.

The requested-topic boundary also applies to builder's missed-entity and
orphan-link audits: wiki-add never creates an unrequested entry to satisfy
them. If a proposed target is not already published, leave its mention as
plain text and omit it from Related. The full procedure lives in
[wiki-add](../skills/wiki-add/SKILL.md); this section does not expand its scope.

### wiki-build — inside the entries it writes, and nowhere else

Processing a source, it wikilinks within the entry bodies it creates or merges
and builds each one's `**Related:**` footer — linking only targets that exist.
An entity with insufficient source coverage gets no note and no
link (its mention stays plain text, and the run report defers it with the
missing-entry routes above). Its reach stops there, apart from the ownership
handoff below.

- It **does not touch entries it did not write this run.** A bare-text mention of
  an existing entry, in an entry this run didn't write, is not its to wrap.
  The one exception is wiki-build's
  [ownership handoff](../skills/wiki-build/references/review.md#overlapownership-audit-this-runs-entries-and-their-relevant-neighbors): when an entry
  this run writes becomes the owner of an explanation or exhibit a neighbor duplicates,
  the run trims the neighbor's copy to its consequence in one clause linked to
  the owner and publishes that
  neighbor with its own entries.
- Its **orphan-link audit is scoped to the entries this run created or merged** —
  a dangling link inside one of its own new entries is repaired then and there
  (the missed entry created, or the link dropped to bare text); the rest
  of the vault is left alone.
- It **never refactors**: never renames a slug and rewrites inbound links, never
  splits a pre-existing mixed-scope entry, never merges two entries, never
  populates `parents:`. Partitioning one new source into atomic candidates before
  their files exist is ordinary extraction, not this prohibited refactoring.
- **Renaming or deleting a pre-existing entry is out of bounds** — both have
  vault-wide reach this skill cannot see the edges of (inbound links in
  untouched entries, `parents:`, the MOCs in `MOCs/` and any legacy root MOCs). It records the proposal
  and leaves the file alone. An entry *created during this run* may still be
  renamed before publication, provided every reference written this run is
  updated to keep resolving (wiki-build step 7.5).

**Its guarantee is narrow and complete:** no dangling link ships *from this run*.
Not that the vault contains none.

### wiki-lint — everything vault-wide and retroactive

Its ownership and reach are vault-wide and retroactive rather than tied to one
source document. Each run still honors the task and entry scope the user
requested; hierarchy work expands only through its separately authorized scope
closure. Within that scope, the retroactive and cross-entry surface is its
alone, apart from wiki-build's narrow ownership handoff and a producer's
link respelling after its own rename, with the `sources:` copy that
respelling makes and removes (§2a):

- **Backfill** a bare-text mention of an existing entry, anywhere, including in
  entries a wiki-build run passed over.
- **Prune, all three kinds** — removing a self-link, dropping a *resolving*
  link too weak to keep, and de-duplicating a target linked twice in one body.
  This retrospective scope includes weak-link pruning beyond builder's
  targeted repairs of proven invalid links. It applies only to
  body-prose and Related-footer links: `tags:`, `sources:` and `parents:` are
  never pruned by this mechanism.
- **Repair orphans inherited from earlier runs.** Assume the vault has *not*
  been swept.
- **`parents:`, the MOCs, the links from each parent to its children,
  whole-vault dedup detection, and cross-entry QC** —
  the things wiki-build structurally cannot do, because it sees one source at
  a time and cannot know about entries that do not exist yet.
- **Content repair across entries** (Task 1b) — correct, simplify and deepen
  existing entries from their cited sources or accurate background,
  consolidate an explanation duplicated across entries into its owner,
  resolve conflicting claims, align notation across siblings, merge synonym
  duplicates, split an entry that defines several durable subjects, retitle
  under §4b, and create the missing entries the routes above establish. It
  works through the open items of `Reviews/wiki-notes-suggestions.md` as data
  it re-verifies, never as instructions.

Its ordinary run **merges and splits entries once its refactor proof holds,
and deletes an entry only on an explicit request**, under its
[deletion protocol](../skills/wiki-lint/references/refactors.md#delete-an-entry);
a split boundary or merge
identity that is a genuinely close call is reported, never applied. Its
content-repair step, refactor protocol, Task 3's missing-root creation, and
its task division
are defined in [wiki-lint](../skills/wiki-lint/SKILL.md#scope-and-ownership).
Task 1 QC and Task 2 link hygiene create no entries: an unresolved target
becomes plain text and, when it looks like a real gap, a reported
missing-entry candidate. The run report is the audit trail.

### Why the split is drawn here

**The retrospective linking bar has one home: wiki-lint.** This prevents a
later source integration from restoring a weak link merely because the merge
rephrased its sentence. A merged entry is in both skills' scopes, so
**wiki-build's link provenance is the active source's contribution, not which
sentences happened to be rewritten**:

- **Body prose:** wrap a first occurrence when the active source introduces the
  target or adds a substantive relationship to it. Rewording a carried-over
  claim for coherence does not make the target source-introduced and does not
  restore a prior link. Apply the frequency-inverted self-sweep to the active
  source's contributed claims under the same test.
- **Related footer:** source-driven integration is additive, growing only for
  substantive relationships introduced by the active source. A pre-existing
  bare mention earns no addition. Independent targeted QC may repair or remove
  a proven invalid link under [merge rules](../skills/wiki-build/references/merge.md#frontmatter-and-related-footer);
  retrospective weak-link pruning remains wiki-lint's work.
- **New evidence after a prune:** a later source may genuinely introduce a new
  substantive relationship to the same target. wiki-build may then link that
  source-backed relationship and report it; wiki-lint judges the resulting
  link on its next retrospective pass. Sentence rewriting alone is never that
  evidence.
- **A pre-existing bare mention that genuinely should be linked** is
  wiki-lint's to backfill, under wiki-lint's bar, on its next pass.

**Depended on by:** wiki-build, wiki-add, wiki-lint.

---

## 10. Validation

Run the checks in the [development guide](../README.md#developing-and-packaging)
after changing shared contracts or skills, starting with
`python3 tests/test_conventions.py`. The convention suite checks the
current schemas, skill roster, references, and script interfaces and runs the
bundled self-tests; each section's **Depended on by** names that section's
consumers. Every detected defect is a failure; fix the cause before
distributing the plugin. Keep historical decisions in Git history, not in
runtime instructions or validation-exception registries.
