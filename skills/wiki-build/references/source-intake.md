# Source intake and prior coverage

Read this at [workflow step 1](../SKILL.md#1-read-the-source), before
extracting from any source. This reference owns source-file intake, identity,
prior-coverage decisions, and classification.

- [Require a durable source](#require-a-durable-source)
- [Resolve a Markdown source](#resolve-a-markdown-source)
- [Verify a resolved PDF](#verify-a-resolved-pdf)
- [Books and chapters](#books-and-chapters)
- [Check prior coverage](#check-prior-coverage)
- [Read and classify](#read-and-classify)

## Require a durable source

A source must be a durable file in the selected vault. For a bare URL, request
its Web Clipper capture and route that capture through `clipping-clean` first.
For pasted text, use an existing user-named vault file or obtain the exact
destination before saving it. A topic named without a source document belongs
to [wiki-add](../../wiki-add/SKILL.md). Never invent a persistent source
filename or publish entries with unresolvable citations. Markdown sources keep
their literal on-disk names.

Files under `Inbox/` are intake material, not sources; never cite one while it
is there.

- Route a raw `.md` capture through `clipping-clean` and an Inbox PDF through
  `pdf-organize`, then process the resulting `Articles/` note or
  `Sources/PDFs/` file.
- When clipping-clean reports a duplicate, process the note it names, unless
  it is a wiki-add research extract (`research_extracts`): then ask whether to
  use the extract instead.
- A user's own note with no capture URL is not a clipping: ask the user to
  move it out of `Inbox/`, or approve a destination, and process it there.
- A preview run uses the producer only in its preview mode, extracts from the
  raw file, and cites the proposed path provisionally.

A folder run never selects an `Inbox/` file or a
[feed-owned attachment](../../../shared/CONVENTIONS.md#1-vault-folder-layout),
and it takes a split book through its [chapters](#books-and-chapters).

A marked [wiki-add research extract](../../wiki-add/references/research.md) is
a selective, agent-written extract of a URL, not a full capture. Cite its
Markdown filename, never its URL; use only claims its own text supports, never
extend it from the live page, and read nothing into what it omits. An ordinary
builder run never creates an extract, and a search result is never a source.

## Resolve a Markdown source

A `.md` handed to this skill may be a *clipping* note — real prose, and a source in its own right — or a note **about a PDF** that is already sitting in `Sources/PDFs/`, which is the same document under a second name. The two are indistinguishable by path, and the difference decides both which file gets read and which name the already-processed check has to probe.

**The tell is `sources:` item 1, not the body.** Per `CONVENTIONS.md` §2b, a note about a document opens its `sources:` list with the document's origin — a **URL** item for a web clipping, and a **wikilink to a local PDF** for a note about that PDF. Read the complete frontmatter with the validated parser below. A block list, a flow list, a comment and a YAML escape must produce the same decoded source identity. The line after `sources:` is not necessarily its first item. A `paper-summarize` note may contain hundreds of words of structured summary while an older embed-note contains just `![[Something.pdf]]`; neither body tells you which source to process.

```bash
python3 - '<skill>/scripts' '<cleaned-note>.md' <<'PY'
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from vault_index import parse_frontmatter
fm = parse_frontmatter(Path(sys.argv[2]).read_text(encoding="utf-8-sig"))
field = fm.get("sources")
print(json.dumps({"sources": fm.values("sources"),
                  "sources_kind": field.kind if field else None,
                  "legacy_source": fm.scalar("source"),
                  "errors": fm.errors}, ensure_ascii=False, indent=2))
PY
```

**A first `sources:` item of the form `"[[Something.pdf]]"` means the note is *about* that PDF, and the PDF is the source.** Run `python3 '<skill>/../../shared/scripts/vault_artifacts.py' pdfs --vault '<vault>'` and resolve the decoded target from its complete inventory, honoring folder qualification while comparing every path component with NFC normalization and case folding; preserve suffixes such as `_2` and `_01_ChapterName`. Apply [the resolved-PDF gate](#verify-a-resolved-pdf) before continuing. Process the resolved PDF instead of the note, and record the substitution in the run report. If the inventory is incomplete or several files match a basename, report the uncertainty and resolve it before reading or automatically skipping the source. **This is not a preference:** an `Articles/` note is somebody's hedged restatement of the paper, so extracting entries from it builds the vault on a summary while the document itself goes unread, and every `sources:` item it produces is an anchorless `[[Foo.md]]`. Only if a complete inventory proves the PDF genuinely missing from disk does the note become the source — say so in the report, since those entries get no page anchors. A first item that is a **URL** is a web clipping: that note *is* the source, and you carry on with it.

**A current `sources:` key takes precedence even when its list is empty.** Only when that key is absent may the decoded `legacy_source` scalar supply the origin; classify that eligible fallback as above. Never fall through from an empty current list to `source:`. If the selected origin field is absent or empty in otherwise valid frontmatter, the note is an **unpaired markdown source**: process it as one and record the call in the run report. A markdown source with no frontmatter can likewise be unpaired after inspecting it. Malformed YAML, a non-list `sources:`, a null item, or conflicting current and older origins is not evidence of an unpaired source: report it and establish the identity before proceeding. Do not silently fall back to the summary or infer an automatic skip from malformed metadata.

## Verify a resolved PDF

Before deriving citations, figure stems, or prior-coverage keys, verify the
canonical filename and unique portable-basename ownership across the vault.
Bare PDF page links cannot disambiguate two paths:

```bash
python3 '<skill>/../../shared/scripts/naming.py' canonical '<resolved pdf path>'
python3 '<skill>/../../shared/scripts/vault_artifacts.py' pdfs \
    --vault '<vault>' --selected '<resolved pdf path>'
```

Read the inventory JSON even on a nonzero exit. A non-canonical filename, an
incomplete inventory, or a selection that is not `unique` blocks PDF
processing:

- A non-canonical vault PDF: route it through `pdf-organize`.
- No vault owner (a PDF outside the vault): unless the user asked to import
  it, ask before copying it into `Inbox/` for `pdf-organize`; without
  approval, stop and report. Leave the external original in place.
- Several owners: report both paths and follow the
  [duplicate-basename remedy](../../../shared/CONVENTIONS.md#1a-source-file-names-and-why-pdf-organize-runs-first).
- Anything else, such as an incomplete inventory: report the blocker.

After a fix, restart intake from the final path and rerun both checks.

The only naming exception is an explicitly named
[feed-owned attachment](../../../shared/CONVENTIONS.md#1-vault-folder-layout)
(`naming.py feed '<name>'` reports `feed-owned`), including one a named note's
`sources:` points to; a folder run skips such a note and reports it. Once
`--selected` proves one owner, the attachment keeps its collector name: never
rename it or route it to `pdf-organize`, report the exception, and pass
`--allow-unorganized` to any figure extraction for it.

## Books and chapters

A whole-book PDF whose chapter PDFs exist (pdf-organize's
`Sources/PDFs/<Work>/` split) is a split book; pair them over the complete
`vault_artifacts.py pdfs --vault '<vault>'` inventory with
`python3 '<skill>/../../shared/scripts/naming.py' chapter '<stem>'`. A book and
its chapters are one document:

- A folder run that reaches both, or a request naming the split book,
  processes its chapters in order as separate sources and skips the
  whole-book file, reporting the substitution, unless the user explicitly asks
  for that file. Report each substantive table-of-contents section no chapter
  covers (often introductions, appendices, glossaries) as not processed.
- Query prior coverage for both representations: a confirmed citation of the
  whole book covers its chapters, and a chapter citation covers that chapter;
  without rerun intent, skip covered parts. Never cite both book and chapter
  pages for the same claim.

An unsplit book is an ordinary source.

## Check prior coverage

```bash
IDX=$(mktemp '<scratch>/vault-index.XXXXXX')
python3 '<skill>/scripts/vault_index.py' '<coverage-tree>' \
  --vault '<vault>' --source '<vault>/Sources/PDFs/Foo.pdf' \
  --source '<vault>/Articles/Foo.md' -o "$IDX"
```

Use the real Wiki as `<coverage-tree>` before any draft exists. Once an earlier
source in the same run has produced a draft, use the current unique private
overlaid resolution tree so that staged coverage participates in later-source
skip decisions; add `--wiki-origin '<vault>/Wiki'` with its actual public
location, because note-relative links must not resolve from scratch. Supply
actual absolute or vault-relative source paths with extensions, using one
`--source` for an unpaired source and both paths for a resolved PDF/note pair;
the note need not have the PDF's stem.

Read `source_matches`, `source_match_candidates`, `source_problems`,
`source_inventory_complete`, and ordinary `problems` in `$IDX`. Exit 1 means a
Wiki or source directory could not be completely inventoried. Exit 0 and
`ok: true` can still carry parse/read or source-ownership problems that block
the decision. The helper inventories PDF and Markdown basename owners across
the vault. A selected source must exist, be readable, and have exactly one
portable basename owner; a leaf Markdown symlink is not source evidence.

Verified-paths matching uses decoded frontmatter `sources:`, preserves numeric
disambiguators, and compares each path component with NFC and case folding.
Bare, vault-relative, note-relative, and shortest-suffix wikilinks can confirm
the actual file; a wrong folder qualification cannot. Unresolved candidates
remain visible separately and never establish prior coverage. Only a verified-paths
match with `identity_confirmed: true`, complete inventories, and resolved
ownership/metadata problems can establish coverage. A legacy query
without `--vault` returns only `identity_confirmed: false` basename candidates.
A body example mentioning `[[Foo.pdf]]` does not count as having processed Foo.

If neither a public Wiki nor a staged entry exists, there is no prior coverage
to inspect: omit this check and use a unique empty private resolution tree for
candidate planning and review. Do not create the vault's `Wiki/` directory at
intake, collision planning, or during a preview/no-apply run. An authorized
step-7 publication may create it only when reviewed drafts actually survive to
publication. If `problems` is nonempty or the source identity is ambiguous,
review and report the uncertainty before deciding; do not infer either an
automatic skip or permission to rewrite existing entries from incomplete
lookup data.

The index never follows a leaf `.md` symlink for provenance. It records the
slug as occupied, leaves its metadata empty, and reports the symlink; content
behind that link cannot prove prior coverage. Preserve the occupant and resolve
the filesystem issue separately rather than treating the empty record as a
free slug or reading the link target as a vault-owned entry.

**Any confirmed source match means the default action is to SKIP** — don't read it, don't extract, don't modify entries. Re-runs churn body prose, reset `updated:`, and — because churned prose is body content — clear `read:` on entries the user had already read, for no gain. **Proceed only on explicit re-run or resume intent in the user's request or existing authorization for this run** ("re-process", "re-run", "resume the interrupted run", "finish the incomplete run", "apply the new rules to existing entries", or equivalent). A plain "process Foo.pdf" does not qualify, even about a known-processed source. Ambiguous intent after a confirmed match → skip; unresolved source identity or malformed metadata → report and resolve, not an automatic previously-processed verdict. Ordinary intent is run-level: if the prompt signals it, all previously-processed sources in the batch proceed. The one narrow exception is an explicit candidate-specific request, which reopens only its named candidate and sources under [the candidate-specific protocol](multi-source-synthesis.md).

**Resume belongs to wiki-build.** A prior match proves that some entry cites the source; it does not prove that an interrupted run completed extraction, every merge, interlinking, or the three audits. Under explicit resume intent, re-read the complete source and run the normal workflow over it. Existing coverage goes through the same collision and source-no-op-merge checks, while missing entities and source-dependent repairs go through their ordinary gates. This is deliberately a safe re-run rather than an attempt to infer an interruption point from partial files. wiki-lint may clean source-independent residue before or after this run, but it cannot recover omitted source claims, entries, page anchors, or figure choices and is never the owner of completing the source run.

**If every source in the run is skipped** — previously processed with no re-run/resume intent, or no durable content under step 2(c) — nothing is created and nothing is merged, so all step-7 audits have empty scope and entry processing is a no-op. Report the skips, then use the [shared suggestion closeout](../../../shared/SUGGESTIONS.md) only for evidence already obtained; do not audit skipped entries or sources for log maintenance. On an authorized resume, this skill's audits cover every entry the resumed run creates or touches; inherited source-independent defects elsewhere in the vault remain wiki-lint's scope.

## Read and classify

Read the complete source, mapping headings first for long documents and
reading in entity-dense passes when needed. Track the canonical on-disk name
and the **physical PDF page introducing each entity**. Use available PDF tools,
`pdftotext -layout`, or PyMuPDF and inspect rendered pages when useful.
Renderings support comprehension only; embedded figures follow the separate
[media rules](media.md). Read Markdown directly.

In a cleaned clipping, the leading `> [!Summary]` callout, the `description`,
captions marked `(synthesized from context)` or as animation conversions or
static frames, and `<!-- … -->` placeholders are clipping-clean's annotations.
Use them only to orient; take every claim, number, qualifier, and attribution
from the captured body after the first `___` separator.

**Classify the source.** *Primary* = teaching durable knowledge is its main purpose (papers, chapters, reviews, substantive explainers, lecture notes) → the substance test alone gates extraction. *Secondary* = primarily transient signal (news, earnings, announcements, opinion posts) → the durability test applies **in addition**.

**Classify by the source's primary purpose, not incidental content.** An earnings roundup remains secondary when it pauses to explain a technology: the durability test admits the lasting explanation and rejects the quarter's result. **Ambiguous → secondary.** Report the classification. Do not reclassify a news source merely to admit more candidates; a separately curated substantive note can instead be processed as its own source under the normal tests.
