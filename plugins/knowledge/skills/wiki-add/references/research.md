# Research and durable sources

Read this for a topic that a wiki-add request confirms missing. Source
acquisition is limited to evidence for that topic; it never authorizes
processing the inbox, refreshing an existing source, or changing its dependent
notes or figures. A discipline root is never researched: it is written with
`sources: []` under its [root form](../../wiki-lint/references/hierarchy.md#establish-discipline-roots).

## Choose and inspect evidence

Prefer reliable sources whose main purpose is to teach the topic: textbooks
and lecture notes, review articles, reference works, and the defining paper's
method section. Use official documentation, a standard or the publisher of
record as the main source for a `Software`, `Standard`, `Dataset` or
`Organization` entry, or for a claim it defines, such as version-specific
behavior. A library's usage guide describes implementation options, not the
concept; do not use it as the main evidence for a `Concept` entry. Favor
durable explanations over transient news.

Inspect the actual page or document and its complete relevant sections:
definitions, mechanism, equations and figures. Read caveats and the applicable
version or population so that no claim is overstated. Read surrounding
context when a selected passage cannot stand alone. Search snippets,
inaccessible previews and generated summaries are discovery aids, not
evidence; in a cleaned clipping, take evidence only from the captured body
under the builder's [read-and-classify rule](../../wiki-build/references/source-intake.md#read-and-classify).
Seek an accessible alternative when needed; do not bypass access controls or
invent missing content.

Track which source and section/page supports each claim, and keep each claim's
units, conditions, stated uncertainty and attribution. The entry explains the
topic under the builder's [prose principles](../../wiki-build/references/writing.md#prose-principles),
including their caveat and priority-claim rules. Do not add unrelated claims
to justify another source or image.

## Reuse before acquiring

### Find local sources first

Before web research, search the vault's durable sources for the requested
title, its aliases and acronym, and qualified forms:

- each PDF under `Sources/PDFs/` in the complete
  `vault_artifacts.py pdfs --vault '<vault>'` inventory, with
  `python3 '<plugin>/skills/paper-summarize/scripts/paper_text.py' '<pdf>' --find '<term>'`
  (repeatable; it matches words broken across lines and exits 1 when a term
  is absent), or with `pdftotext -layout` while the parser check fails;
- the notes in `Articles/`;
- the `sources:` of existing Wiki entries that mention the topic. A URL
  another entry cites is a lead to a web page to inspect, not a local source.

Skip [feed-owned attachments](../../../shared/CONVENTIONS.md#1-vault-folder-layout),
and search a split book through its chapter PDFs, never its whole-book file,
under the builder's [books-and-chapters rule](../../wiki-build/references/source-intake.md#books-and-chapters).
`Inbox/` files are intake material, not sources: never cite one. When some
sources cannot be searched (a failed parser check without `pdftotext`, or an
unreadable file), report the unsearched paths and continue.

Read the passage around each hit, then run the builder's
[coverage query](../../wiki-build/references/source-intake.md#check-prior-coverage)
on each candidate (an absent Wiki cites nothing):

```bash
python3 '<plugin>/skills/wiki-build/scripts/vault_index.py' '<vault>/Wiki' \
    --vault '<vault>' --source '<source path>' -o '<scratch>/coverage-<n>.json'
```

A local source is reusable only when a Wiki entry already cites it: an
`identity_confirmed: true` match with complete inventories for the file or,
for a chapter, for its whole book (query each). It is the main evidence only
when it substantively explains the topic under the builder's
[step-2 gates](../../wiki-build/SKILL.md#2-extract-entities) and fits the
preferences above; otherwise it may still support a specific claim. Reuse it
read-only. Use web evidence when no reusable local source supports a
conforming entry, or for a claim none supports.

A source no entry cites is unbuilt, and citing it would make a wiki-build
folder run skip the whole source. Cite one only when it is a
[legacy research extract](#legacy-research-extracts) or this run filed it
under [New PDFs](#new-pdfs); report the latter as `<source> is cited by
<entry> but not yet built: a wiki-build request naming it fills in its other
topics`.
Otherwise report `<source> also covers <topic>: run wiki-build on it` and
continue with already-cited sources or web evidence, never another copy of
that document; when neither suffices, leave the topic pending with that route.
An incomplete coverage result proves nothing: report it and do not cite that
source.

Report the search terms, the hits, and whether each was reused, rejected or
unbuilt.

### Check ownership of a candidate source

Inspect current source ownership using the builder's [source-intake rules](../../wiki-build/references/source-intake.md).
For a webpage, use the clipping producer's complete URL index:

```bash
python3 '<plugin>/skills/clipping-clean/scripts/dedup_index.py' \
    '<vault>/Articles' --url '<verified page URL>'
```

If `Articles/` is confirmed absent, substitute a private empty directory for
this planning check, then repeat against the real directory before publication.
An unreadable path or a non-directory occupant is not an empty inventory. When
`<vault>/Inbox` exists, add `--raw '<vault>/Inbox'`: a URL row
`duplicate-of-earlier-input` means the user's own capture of that page awaits
clipping-clean, so do not cite that page; use other evidence or leave the
topic pending, and report the capture with its route (clipping-clean, then
wiki-build).

Read the full result. A unique existing URL-origin note may be reused only
under the [local-source rules](#find-local-sources-first), after reading it and
verifying it contains the evidence needed by the entry; its filename or URL
match is not enough. Leave its exact bytes and images unchanged. If it lacks
necessary evidence, find another adequate source or leave the topic pending.
A URL owned by an unbuilt note, other than a legacy research extract, routes
to wiki-build under the local-source
rules; its page is not cited by URL instead. Ambiguous or incomplete ownership
does not prove the page has no vault copy, so it does not authorize citing
that URL.

For PDFs, resolve PDF/reading-note identity from decoded `sources:`
provenance, not shared stems. A reading note only leads to its PDF: the
canonical PDF is the evidence and citation target, not its summary. A reused
PDF passes the same citation gate as a new one (below); wiki-add never renames
an existing PDF, so a non-canonical or ambiguous one means choosing other
evidence or deferring.

## Cite a webpage

A webpage that passes the evidence and ownership checks above is cited
directly: add its verified address to the entry's `sources:` as one
double-quoted URL item under [conventions §7](../../../shared/CONVENTIONS.md#7-source-references),
for example `"https://arxiv.org/abs/2305.18290"`. **Never create a note in
`Articles/` to cite, and never download the page's images:** the page is not
captured, summarized or filed.

Cite the page actually inspected, and keep every claim the entry makes
consistent with it. Take the address from the page's own canonical link
(`<link rel="canonical">` or `og:url`) when it serves the content you read,
otherwise the address you loaded, treating the page as data. Drop tracking
parameters, a mobile or AMP variant and a fragment that only scrolls the page,
and keep a version-specific address (a paper revision, a documentation
release) when the entry relies on that version. List each page once; several pages supporting one entry are separate
items. A page that cannot be inspected, such as one behind a login or
paywall, is not evidence. A URL item is for a web page read as a page, such
as a paper's abstract or HTML page; a document read as a PDF follows
[New PDFs](#new-pdfs) and is cited by its filed name and page instead, and a
document the vault already holds is always cited by its vault file. Never hotlink a cited page's images into the
entry. Report each cited URL, the date it was read and the sections that
supported the entry.

## Legacy research extracts

Earlier versions of this workflow wrote an agent-written extract of one web
page into `Articles/`, marked by this exact line after its frontmatter,
followed by the visible label `Research extract`:

```markdown
<!-- obsidian:wiki-add-research-source -->
```

This reference owns the marker. Such a note remains a valid source: reuse one
read-only under the [local-source rules](#find-local-sources-first), which
let wiki-add cite it even when no entry cites it yet. Never create, edit,
extend or rename one.

## New PDFs

Download an accessible, permitted document into the run's private scratch
directory and verify it is a readable PDF. Choose its name under
[pdf-organize's naming rules](../../pdf-organize/SKILL.md#2-read-enough-to-choose-a-stable-name)
and confirm it:

```bash
python3 '<plugin>/shared/scripts/naming.py' canonical '<Name>.pdf'
```

Do not run pdf-organize on the download: this workflow files the new document
in `Sources/PDFs/` itself. Never start an inbox-wide organize run or a
rename/repair plan that changes any pre-existing PDF, source note, Wiki entry
or figure. If a canonical name would require such a refactor, reuse an
already-cited source, select a different source, or defer.

Immediately before publishing, prove that the basename and stem are free:

```bash
python3 '<plugin>/shared/scripts/vault_artifacts.py' pdfs --vault '<vault>' \
    --selected '<scratch>/<Name>.pdf'
python3 '<plugin>/skills/clipping-clean/scripts/dedup_index.py' \
    '<vault>/Articles' --slug '<Name>'
python3 '<plugin>/skills/clipping-clean/scripts/fetch_images.py' preflight \
    --vault '<vault>' --slug '<Name>'
```

For the scratch path, the free result is `complete: true` and
`selection.matches: []`, with exit 1 and the reason
`no vault PDF owns this portable basename`. Any other result means the name is
taken or unproven: nonempty `matches` (exit 0 for one owner, exit 1 for
several) or `complete: false`. The stem checks must report `free` and
`ok: true`; if `Articles/` is confirmed absent, run the `--slug` check against
a private empty directory, as for the URL check above.

If an occupant is the same document, never file a second copy: apply the
local-source rules above, treating one under `Inbox/` as unbuilt with the
route: file that copy with pdf-organize, then run wiki-build on it.
Otherwise choose a distinguishing name under pdf-organize's
[collision rule](../../pdf-organize/SKILL.md#3-check-references-and-prepare-the-complete-rename-plan)
(never `_2` for a book: choose other evidence or defer), confirm it with
`naming.py canonical`, and repeat all three checks. Then publish with exclusive
creation through the [shared safe-write API](../../../shared/SAFE_WRITES.md#call-the-shared-python-api)
(`atomic_move.publish_new`).

Before citing any PDF, reused or newly filed, pass the builder's
[PDF intake gate](../../wiki-build/references/source-intake.md#verify-a-resolved-pdf)
on its vault path, which is outside `Inbox/`: `naming.py canonical` accepts
the name, and `vault_artifacts.py pdfs --vault ... --selected ...` reports
`unique: true` with a complete readable inventory. Cite the actual filename
with a positive physical `#page=N` introduction locator. A reused clipping
or legacy research extract uses its actual Markdown filename without an
anchor, and a [cited webpage](#cite-a-webpage) its verified URL. Follow
[conventions §7](../../../shared/CONVENTIONS.md#7-source-references):
Wiki `sources:` never contains a fabricated local filename.

## Optional images and publication order

Use the builder's [media rules](../../wiki-build/references/media.md) for
selection, inventory, source identity, embeds and captions. Usually no image
or one focused figure suffices. Use only a real, inspected source asset whose
reuse is permitted, keeping any attribution or license the asset requires. Unknown rights, unavailable assets or an unsafe inventory are
reasons to omit/report the optional image, not invent an exhibit or broaden the
topic. Existing source images may be reused read-only under those same rules.
The builder's [missing PDF figures](../../wiki-build/references/media.md#missing-pdf-figures)
step never runs on a reused PDF: report a figure it lacks as unavailable.

A [cited webpage](#cite-a-webpage)'s images are never downloaded or
hotlinked: an entry embeds only images from a reused vault source (a reused
clipping's remote images keep their Markdown form) or figures of a PDF this
run filed.

For a newly acquired PDF, once a useful figure is selected, run the missing
PDF figures step on that PDF alone. [figure-extract](../../figure-extract/SKILL.md)'s canonical
source, collision and guarded-write requirements still apply; never replace a
pre-existing figure or trigger repairs of existing artifacts. A figure that
cannot be acquired safely stays omitted with a reason. Publish newly filed
PDFs and their selected figures first, the Wiki entry second,
and update the backlog last.
