# Research and durable sources

Read this only for a requested topic confirmed missing. Source acquisition is
limited to evidence for that topic; it never authorizes processing the inbox,
refreshing an existing source, or changing its dependent notes or figures.

## Choose and inspect evidence

Prefer primary research, official documentation, standards bodies and other
authoritative publishers appropriate to the claim; use reliable secondary
explanations where they add necessary context. Favor durable explanations over
transient news. Inspect the actual page/document and its complete relevant
sections, including definitions, equations, figures, caveats and the applicable
version or population. Read surrounding context when a selected passage cannot
stand alone. Search snippets, inaccessible previews and generated summaries
are discovery aids, not evidence. Seek an accessible alternative when needed;
do not bypass access controls or invent missing content.

Track which source and section/page supports each claim. Preserve uncertainty,
units, mathematical conditions and attribution. For priority/superlative claims
such as “first” or “best,” follow the builder's [verification gate](../../wiki-build/SKILL.md#7-review-and-report):
independent reliable support or narrow attribution, otherwise omit. Do not add
unrelated claims to justify another source or image.

## Reuse before acquiring

Inspect current source ownership using the builder's [source-intake rules](../../wiki-build/references/source-intake.md).
For a webpage, use the clipping producer's complete URL index:

```bash
python3 '<plugin>/skills/clipping-processor/scripts/dedup_index.py' \
    '<vault>/Articles' --url '<verified page URL>'
```

If `Articles/` is confirmed absent, substitute a private empty directory for
this planning check, then repeat against the real directory before publication.
An unreadable path or a non-directory occupant is not an empty inventory.

Read the full result. A unique existing URL-origin note may be reused only
after reading it and verifying it contains the evidence needed by the entry.
Its filename or URL match is not enough. Leave its exact bytes and images
unchanged; do not reprocess it, add excerpts or refresh metadata. If it lacks
necessary evidence, find another adequate source or leave the topic pending.
Ambiguous or incomplete ownership does not authorize a duplicate source note.

For PDFs, reuse a verified readable existing document when available. Resolve
PDF/reading-note identity from decoded `sources:` provenance, not shared stems.
The actual canonical PDF is the evidence and citation target, not its summary.

## New webpage research extracts

Create one note in `Articles/` for one verified webpage, using the shared
[source-note schema](../../../shared/CONVENTIONS.md#2b-source-note--a-note-about-a-document).
This is an agent-written research extract or summary, not a Web Clipper capture
or a claim to reproduce the original article in full. Put this exact marker
immediately after frontmatter, followed by the visible label `Research extract`:

```markdown
<!-- obsidian:wiki-add-research-source -->
```

This reference owns the marker. It distinguishes these extracts from cleaned
captures for source consumers and reprocessing. In the body identify the
original page with a Markdown link, the access date, and the fact that the text
is an agent-written extract/summary. Give specific source heading/section
locators beside the supported material; where headings are absent, identify
the relevant passage or labeled exhibit precisely. Never combine different
pages into one URL-origin note. Separate source records may support one Wiki
entry.

Preserve full source text only when legally reusable. Otherwise write concise,
faithful paraphrases and, when useful, short attributed excerpts within
applicable copyright limits. Include the evidence needed to audit the requested
entry, including load-bearing equations and their conditions, without
reconstructing the whole page or importing unrelated sections. Distinguish
quoted words from paraphrase. Neither the marker nor attribution grants rights
to reproduce text or images.

Verify metadata with the clipping producer's [metadata guidance](../../clipping-processor/references/metadata-verification.md),
using its evidence ordering, not its raw-capture or reprocessing path.
Use the actual page title, `Article` or `Post` as appropriate, exactly one
double-quoted verified original URL in `sources:`, and `created` set to today.
Use `author: []` if no human author is verified and `published: null` with an
`nd` filename when undated; never substitute access/update dates for publication
or invent an author. Apply §2b's description, tags and `read: false` rules.

Use the clipping producer's [source filename rules and slug helper](../../clipping-processor/references/filename-slug.md).
Before images or publication, follow its [source-stem ownership checks](../../clipping-processor/SKILL.md#2-verify-metadata-and-settle-the-final-name):
`dedup_index.py --url ... --slug ...` and `fetch_images.py preflight` inspect
the Articles namespace, recursive PDF stems and image prefixes. Recheck the URL
as well as the name; a new matching owner returns to reuse, never overwrite.
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
directory and verify it is a readable PDF. Read the [PDF organizer](../../pdf-organizer/SKILL.md)
for canonical naming; apply its naming operation only to this new scratch
artifact. This workflow authorizes filing that newly acquired document in
`Sources/PDFs/`, using exclusive publication after current vault ownership
checks. Do not start an inbox-wide organize run or a rename/repair plan that
changes any pre-existing PDF, source note, Wiki entry or figure. If a canonical
name would require such a refactor, reuse a proven existing source, select a
different source, or defer.

Before citation, use `shared/scripts/naming.py canonical` and
`shared/scripts/vault_artifacts.py pdfs --vault ... --selected ...` under the
builder's [PDF intake gate](../../wiki-build/SKILL.md#1-read-the-source).
Require one portable-basename owner and a complete readable inventory. Cite
the actual filename with a positive physical `#page=N` introduction locator.
Web extracts instead use their actual Markdown filename without an anchor.
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

For a new webpage extract, use the clipping producer's
[stage/place image helper](../../clipping-processor/references/images.md#download-and-publish),
retaining its network, byte-sniffing, owner-note and exclusive-write guards.
Only selected source images need downloading. There is no custom downloader or
overwrite fallback. Inspect successful staged images; omit failed optional
images from the private draft and report the limitation. Publish the reviewed
source note before `place`, because that helper verifies its exact owner embed;
verify the attachments before publishing a dependent Wiki entry. A placement
failure after source publication is partial state to reconcile/report, never
successful completion of an unresolved embed.

For a newly acquired PDF, use [pdf-figure-extractor](../../pdf-figure-extractor/SKILL.md)
only on that scoped source when a useful figure is selected. Its canonical
source, collision and guarded-write requirements still apply; never replace a
pre-existing figure or trigger repairs of existing artifacts. A figure that
cannot be acquired safely stays omitted with a reason. Complete verified
source artifacts and selected images first, publish the Wiki entry second,
and update the backlog last.
