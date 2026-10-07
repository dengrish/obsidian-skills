# Source intake and prior coverage

Scope: durable-source intake, PDF identity, books and chapters, prior coverage
and classification for each source. Unusual sources and multi-source runs are
in [source cases](source-cases.md).

## Require a durable source

A source must be a durable file in the selected vault; an entry's URL item is never a builder source. For a bare URL that is the
source to build from, request its Web Clipper capture and route that capture
through `clipping-clean` first. A page named only beside a durable source is
reported unused, never clipped to cite it
([named-entity requests](../SKILL.md#named-entity-requests)).
For pasted text, use an existing user-named vault file or obtain the exact
destination before saving it. An apply run writes the text to a scratch file
and saves it with `publish_files.py`: snapshot the destination to
`<scratch>/source-snapshots.json`, which must record `absent`, then publish a
one-item `<scratch>/source-manifest.json`, kept apart from the entry manifest.
`--create-dir` creates only an absent direct child of the vault; create a
deeper absent folder as in [step 7.8](../SKILL.md#7-review-and-report). A
preview or no-apply run saves nothing and cites the proposed path
provisionally. The saved file is an
unpaired Markdown source. Never invent a persistent source
filename or publish entries with unresolvable citations. Markdown sources keep
their literal on-disk names.

**A source named by title, nickname or description** ("the METL paper")
rather than by path is identified first. Look for the name in the filenames of
the complete `vault_artifacts.py pdfs --vault '<vault>'` inventory, in the
`title:` and `description:` of notes about a document (such as `Articles/`
reading notes and slide notes), and on the first page of each `Sources/PDFs/`
file with `python3 '<plugin>/skills/paper-summarize/scripts/paper_text.py' '<pdf>' --find '<name>'`.
A document that only cites the name is not a candidate. A matching note leads
to the document its decoded `sources:` names
([resolve a Markdown source](source-cases.md#resolve-a-markdown-source)). A
filename match alone never decides: a slide deck or another derived file named
after the work leads to the document it names and is never the source itself.
Proceed when the candidates resolve to exactly one document, and report how it
was identified. When several documents remain, or none, list the candidates
and ask.

Files under `Inbox/` are intake material, never sources
([Inbox captures](source-cases.md#inbox-captures-feed-attachments-and-research-extracts)).
A folder run never selects an `Inbox/` file or a feed-owned attachment, and it
takes a split book through its [chapters](#books-and-chapters).

## Verify a resolved PDF

Before deriving citations, figure stems, or prior-coverage keys, verify the
canonical filename and unique portable-basename ownership across the vault,
since bare PDF page links cannot disambiguate two paths:

```bash
python3 '<plugin>/shared/scripts/naming.py' canonical '<resolved pdf path>'
python3 '<plugin>/shared/scripts/vault_artifacts.py' pdfs \
    --vault '<vault>' --selected '<resolved pdf path>'
```

Read the inventory JSON even on a nonzero exit. A non-canonical filename, an
incomplete inventory, or a selection that is not `unique` blocks PDF
processing; `unique` proves only who owns the basename, not that a PDF outside
the vault is that owner:

- A non-canonical vault PDF: route it through `pdf-organize`, unless it is an
  explicitly named
  [feed-owned attachment](source-cases.md#inbox-captures-feed-attachments-and-research-extracts),
  the only naming exception.
- A PDF outside the vault whose basename one vault PDF owns
  (`selection.matches`): that vault PDF is the cited document. First confirm
  the external file is the same document (identical bytes, matching page count
  and first-page text, or the user's word); then read the vault PDF, or use the
  external file only as its readable copy (such as a decrypted scratch copy).
  Otherwise stop and report both paths. Never import it under that basename.
- No vault owner (a PDF outside the vault with empty `selection.matches`):
  unless the user asked to import it, ask before copying it into `Inbox/` for
  `pdf-organize`; without approval, stop and report. Leave the external
  original in place.
- Several owners: report both paths and follow the
  [duplicate-basename remedy](../../../shared/CONVENTIONS.md#shared-pdf-basenames).
- Anything else, such as an incomplete inventory: report the blocker.

After a fix, restart intake from the final path and rerun both checks.

## Books and chapters

A whole-book PDF whose chapter PDFs exist (pdf-organize's
`Sources/PDFs/<Work>/` split) is a split book. Pair them over the complete
`vault_artifacts.py pdfs --vault '<vault>'` inventory with
`python3 '<plugin>/shared/scripts/naming.py' chapter '<pdf path>' ...`. Pass
each inventoried path unchanged, never a stem: the CLI always removes one
extension, so a dotted stem would be misread. It reports a chapter's book as
a core stem, the stem without a `_src` marker (a `_2` disambiguator stays), so
compare it with each book's core stem:
`Kuhn_StructSciRev_2012_01_RoleHistory.pdf` (chapter 01 of
`Kuhn_StructSciRev_2012`) belongs to `Kuhn_StructSciRev_2012_src.pdf`. A book
and its chapters are one document, and its chapters are processed as
[separate sources](source-cases.md#several-sources-in-one-run). With no
whole-book PDF, skip the pairing.

Query prior coverage for both representations: a confirmed citation of the
whole book covers its chapters, and a chapter citation covers that chapter.
When only chapter PDFs exist, query the chapters. A folder run without rerun
intent skips covered parts; a named book or chapter
[fills them in](#check-prior-coverage). An entry cites a split book in one
form, never both its whole-book PDF and its chapter PDFs: an entry that cites
the whole book already cites each chapter and gains no chapter citation. An
unsplit book is an ordinary source.

A request that names one chapter of a book ("build chapter 3 into my wiki",
"PCA from chapter 7") processes that chapter's PDF alone, found among the
paired chapters by number or title. When only chapter PDFs exist, find it by
its `_NN_` number or title in the book's `Sources/PDFs/<Work>/` folder of the
same inventory and process it directly. For an unsplit book, the request
authorizes
[pdf-organize](../../pdf-organize/SKILL.md#5-test-for-a-book-and-split-only-when-justified)
to split that one book, keeping the original; then pair and process the named
chapter PDF. A preview or no-apply run splits nothing and reports the proposed
split. If pdf-organize finds no chapter structure, or the split or a rename it
needs is blocked, build nothing from the book and report the blocker and the
proposed split. Never build a chapter from the whole-book PDF: an entry citing
the book marks the whole book covered, so folder runs skip its other chapters.

## Check prior coverage

```bash
IDX=$(mktemp '<scratch>/vault-index.XXXXXX')
python3 '<skill>/scripts/vault_index.py' '<coverage-tree>' \
  --vault '<vault>' --source '<vault>/Sources/PDFs/Foo.pdf' \
  --source '<vault>/Articles/Foo.md' -o "$IDX"
```

Use the real Wiki as `<coverage-tree>` before any draft exists, and the
[overlaid tree](source-cases.md#several-sources-in-one-run) once an earlier
source has produced one, queried together with the real Wiki while it reports
`unmirrored` paths. With neither a public Wiki nor a staged entry, omit
this check. Pass each actual source path with its extension, one `--source`
per file (both for a resolved PDF/note pair, whose stems may differ).

A clipping (a note whose first `sources:` item is a URL) may have a same-URL
twin: a [pending changed-slug handoff](../../clipping-clean/references/duplicates-and-reprocessing.md#finish-a-pending-changed-slug-handoff)
keeps the old and the new `Articles/` note of one page, possibly for good.
Find it with
`python3 '<plugin>/skills/clipping-clean/scripts/dedup_index.py' '<vault>/Articles' --url '<origin URL>'`
and pass every other note in its `checked` row's `matches` as one more
`--source`. The pair is one document: a confirmed citation of either note is
coverage, and an entry this run creates or merges cites only the note it
reads, never both. Report the pair under *Notes for the user*.

Read `source_matches`, `source_match_candidates`, `source_problems`,
`source_inventory_complete`, and ordinary `problems` in `$IDX`. Exit 1 means an
incomplete Wiki or source inventory; exit 0 with `ok: true` can still carry
parse, read or ownership problems that block the decision. A selected source
must exist, be readable, and have exactly one portable basename owner; a leaf
Markdown symlink is not source evidence.

Matching ignores case and Unicode normalization; a wrong folder qualification
never confirms a file. The lookup decides coverage as follows:

- **Covered:** only a verified-paths match with `identity_confirmed: true`
  and complete inventories establishes coverage; unresolved candidates, a
  legacy query without `--vault` (basename candidates only) and a body
  example mentioning `[[Foo.pdf]]` never do. A problem on an entry that is
  neither a match nor a candidate for this source does not undo a confirmed
  match: a folder run still skips the source and reports the problem.
- **Uncertain:** source problems, a problem on a matching or candidate
  entry, an ambiguous identity, and, when no match is confirmed, any
  problem that can hide a citation (an unreadable, unsafe or unparsed
  entry, or a malformed `sources:` item). Report that uncertainty before
  deciding: incomplete lookup data implies neither an automatic skip nor
  permission to rewrite existing entries.

A readable plain note without frontmatter cites nothing, so it is reported
but never makes coverage uncertain
([collision decisions](merge.md#collision-decisions)).

A folder or inbox-wide run skips a confirmed match unless the request states
rerun or resume intent ([skip, rerun and resume](source-cases.md#skip-rerun-and-resume)).
**A source the user names (a file, a chapter, or a book) is filled in, not
skipped.** Read it; each entity whose entry already cites this source, in
any form of the same document (the whole book for a chapter, a same-URL twin
for a clipping), is finished and stays untouched (no re-merge, no `updated:` or `read:` change);
every other substantive entity goes through the ordinary workflow, creating an
entry or merging into one that does not yet cite this source. A [named-entity request](../SKILL.md#named-entity-requests)
instead builds only its named entities.

Prior coverage concerns this source: an entry built from another source, such as
an overview chapter, is merge input that this source's net-new explanation
deepens.

## Read and classify

Read the complete source, mapping headings first for long documents ([named-entity
exception](../SKILL.md#1-read-the-source)). Track
the canonical on-disk name and the **physical PDF page introducing each
entity**. Read PDFs with available tools (`pdftotext -layout`, PyMuPDF),
inspecting rendered pages when useful;
renderings support comprehension only, and figures follow the
[media rules](media.md). Read Markdown directly.

In a cleaned clipping, the leading `> [!Summary]` callout, the `description`,
captions marked `(synthesized from context)` or as animation conversions or
static frames, and `<!-- … -->` placeholders are clipping-clean's annotations.
Use them only to orient; take every claim, number, qualifier, and attribution
from the captured body after the first `___` separator.

**Classify the source.** *Primary* = teaching durable knowledge is its main purpose (papers, chapters, reviews, substantive explainers, lecture notes) → the substance test alone gates extraction. *Secondary* = primarily transient signal (news, earnings, announcements, opinion posts) → the durability test applies **in addition**.

**Classify by the source's primary purpose, not incidental content:** an earnings roundup that pauses to explain a technology stays secondary. **Ambiguous → secondary.** Report the classification. Do not reclassify a news source merely to admit more candidates; a separately curated substantive note can instead be processed as its own source under the normal tests.
