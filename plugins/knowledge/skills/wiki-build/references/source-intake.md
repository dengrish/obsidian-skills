# Source intake and prior coverage

Scope: durable-source intake, PDF identity, books and chapters, prior coverage
and classification for each source. Unusual sources and multi-source runs are
in [source cases](source-cases.md).

## Require a durable source

A source must be a durable file in the selected vault. For a bare URL, request
its Web Clipper capture and route that capture through `clipping-clean` first.
For pasted text, use an existing user-named vault file or obtain the exact
destination before saving it. Never invent a persistent source
filename or publish entries with unresolvable citations. Markdown sources keep
their literal on-disk names.

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
processing:

- A non-canonical vault PDF: route it through `pdf-organize`, unless it is an
  explicitly named
  [feed-owned attachment](source-cases.md#inbox-captures-feed-attachments-and-research-extracts),
  the only naming exception.
- No vault owner (a PDF outside the vault): unless the user asked to import
  it, ask before copying it into `Inbox/` for `pdf-organize`; without
  approval, stop and report. Leave the external original in place.
- Several owners: report both paths and follow the
  [duplicate-basename remedy](../../../shared/CONVENTIONS.md#1a-source-file-names-and-why-pdf-organize-runs-first).
- Anything else, such as an incomplete inventory: report the blocker.

After a fix, restart intake from the final path and rerun both checks.

## Books and chapters

A whole-book PDF whose chapter PDFs exist (pdf-organize's
`Sources/PDFs/<Work>/` split) is a split book; pair them over the complete
`vault_artifacts.py pdfs --vault '<vault>'` inventory with
`python3 '<plugin>/shared/scripts/naming.py' chapter '<stem>'`. A book and
its chapters are one document, and its chapters are processed as
[separate sources](source-cases.md#several-sources-in-one-run). With no
whole-book PDF, skip the pairing.

Query prior coverage for both representations: a confirmed citation of the
whole book covers its chapters, and a chapter citation covers that chapter.
When only chapter PDFs exist, query the chapters. A folder run without rerun
intent skips covered parts; a named book or chapter
[fills them in](#check-prior-coverage). Never cite both book and chapter pages
for the same claim. An unsplit book is an ordinary source.

## Check prior coverage

```bash
IDX=$(mktemp '<scratch>/vault-index.XXXXXX')
python3 '<skill>/scripts/vault_index.py' '<coverage-tree>' \
  --vault '<vault>' --source '<vault>/Sources/PDFs/Foo.pdf' \
  --source '<vault>/Articles/Foo.md' -o "$IDX"
```

Use the real Wiki as `<coverage-tree>` before any draft exists, and the
[overlaid tree](source-cases.md#several-sources-in-one-run) once an earlier
source has produced one. With neither a public Wiki nor a staged entry, omit
this check. Pass each actual source path with its extension, one `--source`
per file (both for a resolved PDF/note pair, whose stems may differ).

Read `source_matches`, `source_match_candidates`, `source_problems`,
`source_inventory_complete`, and ordinary `problems` in `$IDX`. Exit 1 means an
incomplete Wiki or source inventory; exit 0 with `ok: true` can still carry
parse, read or ownership problems that block the decision. A selected source
must exist, be readable, and have exactly one portable basename owner; a leaf
Markdown symlink is not source evidence.

Matching ignores case and Unicode normalization; a wrong folder qualification
never confirms a file.
Only a verified-paths
match with `identity_confirmed: true`, complete inventories, and resolved
ownership and metadata problems establishes coverage; unresolved candidates,
a legacy query without `--vault` (basename candidates only) and a body example
mentioning `[[Foo.pdf]]` never do. With nonempty `problems` or an ambiguous
identity, report the uncertainty before deciding: incomplete lookup data
implies neither an automatic skip nor permission to rewrite existing entries.

A folder or inbox-wide run skips a confirmed match unless the request states
rerun or resume intent ([skip, rerun and resume](source-cases.md#skip-rerun-and-resume)).
**A source the user names (a file, a chapter, or a book) is filled in, not
skipped.** Read it; each entity whose entry already cites this source is
finished and stays untouched (no re-merge, no `updated:` or `read:` change);
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
