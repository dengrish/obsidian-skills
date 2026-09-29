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
- the `sources:` of existing Wiki entries that mention the topic.

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
folder run skip the whole source. Cite one only when it carries this
workflow's [research-extract marker](#new-webpage-research-extracts) or this
run filed it under [New PDFs](#new-pdfs); report the latter as `<source> is
cited by <entry> but not yet built: a wiki-build request naming it fills in
its other topics`.
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
clipping-clean, so write no extract for it; use other evidence or leave the
topic pending, and report the capture with its route (clipping-clean, then
wiki-build).

Read the full result. A unique existing URL-origin note may be reused only
under the [local-source rules](#find-local-sources-first), after reading it and
verifying it contains the evidence needed by the entry; its filename or URL
match is not enough. Leave its exact bytes and images unchanged. If it lacks
necessary evidence, find another adequate source or leave the topic pending.
Ambiguous or incomplete ownership does not authorize a duplicate source note.

For PDFs, resolve PDF/reading-note identity from decoded `sources:`
provenance, not shared stems. A reading note only leads to its PDF: the
canonical PDF is the evidence and citation target, not its summary. A reused
PDF passes the same citation gate as a new one (below); wiki-add never renames
an existing PDF, so a non-canonical or ambiguous one means choosing other
evidence or deferring.

## New webpage research extracts

Create one note in `Articles/` for one verified webpage, using the shared
[source-note schema](../../../shared/CONVENTIONS.md#2b-source-note--a-note-about-a-document).
This is an agent-written research extract or summary, not a Web Clipper capture
or a claim to reproduce the original article in full. Put this exact marker
immediately after frontmatter, followed by the visible label `Research extract`:

```markdown
<!-- obsidian:wiki-add-research-source -->
```

This reference owns the marker. In the body identify the original page with a
Markdown link, the access date, and the fact that the text is an agent-written
extract/summary. Give specific source heading/section locators beside the
supported material; where headings are absent, identify the relevant passage
or labeled exhibit precisely. Never combine different pages into one
URL-origin note. Separate source records may support one Wiki entry.

Preserve full source text only when legally reusable. Otherwise write concise,
faithful paraphrases and, when useful, short attributed excerpts within
applicable copyright limits. Include the evidence needed to audit the requested
entry, including load-bearing equations and their conditions, without
reconstructing the whole page or importing unrelated sections. Distinguish
quoted words from paraphrase. Neither the marker nor attribution grants rights
to reproduce text or images. Record what the page says, with locators; add no
agent commentary or defensive clarification, and no separate scope or
limitations section unless the entry relies on it.

Verify metadata with the clipping producer's [metadata guidance](../../clipping-clean/references/metadata-verification.md),
using its evidence ordering, not its raw-capture or reprocessing path.
Use the actual page title, `Article` or `Post` as appropriate, exactly one
double-quoted verified original URL in `sources:`, and `created` set to today.
Use `author: []` if no human author is verified and `published: null` with an
`nd` filename when undated; never substitute access/update dates for publication
or invent an author. Apply §2b's description, tags and `read: false` rules.

Use the clipping producer's [source filename rules and slug helper](../../clipping-clean/references/filename-slug.md).
Before images or publication, follow its [source-stem ownership checks](../../clipping-clean/SKILL.md#2-verify-metadata-and-settle-the-final-name):
`dedup_index.py --url ... --slug ...` and `fetch_images.py preflight` inspect
the Articles namespace, recursive PDF stems and image prefixes. Recheck the URL
as well as the name; a new matching owner falls under the
[local-source rules](#find-local-sources-first), never overwrite.
Choose a free permitted suffix for a different source, leaving every existing
owner untouched.

Validate the private source draft with the builder's
`vault_index.parse_frontmatter` parser, imported from its trusted scripts
directory in a private driver. Require found frontmatter and no parse errors;
check its ordered fields, decoded values and raw list/quoting shapes against
§2b, including the sole verified URL, allowed format, dates, author list,
description length, discipline tags and boolean review state. Check the marker,
visible label, locators and every claim against the inspected page. The parser
alone is not a source-note schema or factual validator; the PDF reading-note
linter's PDF-only formats and body template do not apply. Publish only the
complete verified draft, exclusively through the shared safe-write API.

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
with a positive physical `#page=N` introduction locator. A web extract or
reused clipping instead uses its actual Markdown filename without an anchor.
Follow [conventions §7](../../../shared/CONVENTIONS.md#7-source-references):
Wiki `sources:` never contains a bare web URL or a fabricated local filename.

## Optional images and publication order

Use the builder's [media rules](../../wiki-build/references/media.md) for
selection, inventory, source identity, embeds and captions. Usually no image
or one focused figure suffices. Use only a real, inspected source asset whose
reuse is permitted; retain required attribution/license information in its
source record. Unknown rights, unavailable assets or an unsafe inventory are
reasons to omit/report the optional image, not invent an exhibit or broaden the
topic. Existing source images may be reused read-only under those same rules.
The builder's [missing PDF figures](../../wiki-build/references/media.md#missing-pdf-figures)
step never runs on a reused PDF: report a figure it lacks as unavailable.

For a new webpage extract, use the clipping producer's
[stage/place image helper](../../clipping-clean/references/images.md#download-and-publish),
retaining its network, byte-sniffing, owner-note and exclusive-write guards.
Only selected source images need downloading. There is no custom downloader or
overwrite fallback. Inspect successful staged images; omit failed optional
images from the private draft and report the limitation. Publish the reviewed
source note before `place`, because that helper verifies its exact owner embed;
verify the attachments before publishing a dependent Wiki entry. A placement
failure after source publication is partial state to reconcile/report, never
successful completion of an unresolved embed.

For a newly acquired PDF, once a useful figure is selected, run the missing
PDF figures step on that PDF alone. [figure-extract](../../figure-extract/SKILL.md)'s canonical
source, collision and guarded-write requirements still apply; never replace a
pre-existing figure or trigger repairs of existing artifacts. A figure that
cannot be acquired safely stays omitted with a reason. Complete verified
source artifacts and selected images first, publish the Wiki entry second,
and update the backlog last.
