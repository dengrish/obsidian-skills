# Source cases: unusual sources and multi-source runs

Scope: unusual sources and multi-source runs. The
[reading plan](../SKILL.md#what-to-read-and-when) sends you to one section at a
time; each section stands alone.

## Resolve a Markdown source

A `.md` handed to this skill may be a *clipping*, real prose and a source in its own right, or a note **about a PDF** already in `Sources/PDFs/`, which is the same document under a second name. The path cannot tell them apart, and the difference decides which file is read and which name the prior-coverage check probes.

**The tell is `sources:` item 1, not the body.** Under [CONVENTIONS §2b](../../../shared/CONVENTIONS.md#2b-source-note--a-note-about-a-document), a note about a document opens its `sources:` list with the document's origin: a **URL** item for a web clipping, a **wikilink to a local PDF** for a note about that PDF. Read the complete frontmatter with the validated parser below. A block list, a flow list, a comment and a YAML escape must produce the same decoded source identity, and the line after `sources:` is not necessarily its first item. Neither a long `paper-summarize` note nor a bare `![[Something.pdf]]` embed-note tells you from its body which source to process.

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

**A first `sources:` item of the form `"[[Something.pdf]]"` means the note is *about* that PDF, and the PDF is the source.** Run `python3 '<plugin>/shared/scripts/vault_artifacts.py' pdfs --vault '<vault>'` and resolve the decoded target from its complete inventory, honoring folder qualification and comparing every path component under NFC normalization and case folding; preserve suffixes such as `_2` and `_01_ChapterName`. Apply [the resolved-PDF gate](source-intake.md#verify-a-resolved-pdf), process the PDF instead of the note, and record the substitution in the run report. If the inventory is incomplete or several files match a basename, report the uncertainty and resolve it before reading or automatically skipping the source. **This is not a preference:** an `Articles/` note is somebody's hedged restatement of the paper, so extracting from it builds the vault on a summary while the document goes unread, and every citation it produces is an anchorless `[[Foo.md]]`. Only if a complete inventory proves the PDF missing from disk does the note become the source; say so in the report, since those entries get no page anchors. A first item that is a **URL** is a web clipping: that note *is* the source.

An existing, uniquely resolved PDF and its provenance-confirmed summary are one source, cited as the PDF, never both. A clipping remains independent even when an unrelated PDF shares its stem. Preserve unresolved references rather than inferring identity from a filename.

**A current `sources:` key takes precedence even when its list is empty.** Only when that key is absent may the decoded `legacy_source` scalar supply the origin; classify that fallback as above, and never fall through from an empty current list to `source:`. If the selected origin field is absent or empty in otherwise valid frontmatter, or a Markdown source has no frontmatter after inspection, it is an **unpaired Markdown source**: process it as one and record the call in the run report. Malformed YAML, a non-list `sources:`, a null item, or conflicting current and older origins is not evidence of an unpaired source: report it and establish the identity before proceeding. Do not silently fall back to the summary or infer an automatic skip from malformed metadata.

## Inbox captures, feed attachments and research extracts

Files under `Inbox/` are intake material, not sources; never cite one while it is there.

- Route a raw `.md` capture through `clipping-clean` and an Inbox PDF through `pdf-organize`, then process the resulting `Articles/` note or `Sources/PDFs/` file.
- When clipping-clean reports a duplicate, process the note it names, unless it is a legacy wiki-add research extract (`research_extracts`): then ask whether to use the extract instead.
- A user's own note with no capture URL is not a clipping: ask the user to move it out of `Inbox/`, or approve a destination, and process it there.
- A preview run uses the producer only in its preview mode, extracts from the raw file, and cites the proposed path provisionally.

A folder run never selects an `Inbox/` file or a
[feed-owned attachment](../../../shared/CONVENTIONS.md#1-vault-folder-layout).
The only exception to [canonical PDF naming](source-intake.md#verify-a-resolved-pdf)
is an explicitly named feed-owned attachment
(`naming.py feed '<name>'` reports `feed-owned`), including one a named note's
`sources:` points to; a folder run skips such a note and reports it. Once
`--selected` proves one owner, the attachment keeps its collector name: never
rename it or route it to `pdf-organize`, report the exception, and pass
`--allow-unorganized` to any figure extraction for it.

A marked [legacy wiki-add research extract](../../wiki-add/references/research.md#legacy-research-extracts) is a selective, agent-written extract of a URL, not a full capture. Cite its Markdown filename, never its URL; use only claims its own text supports, never extend it from the live page, and read nothing into what it omits. No skill creates an extract any more, and a search result is never a source.

## Several sources in one run

**Folders and batches.** Process a folder's sources, including subfolders, in deterministic vault-relative path order; [source intake](source-intake.md#require-a-durable-source) decides which files a folder run selects. Run steps 1–6 per source, accumulating one private working set, then step 7 once across the run with one consolidated report. A later source that touches the same entry builds on that staged draft while retaining the original public snapshot as its publication precondition. Do not combine thin coverage across sources during an ordinary folder run; report a plausible combined candidate as deferred, naming the files so a [named-entity request](../SKILL.md#named-entity-requests) can evaluate it.

**Split books.** A folder run that reaches a split book, or a request naming one, processes its [chapters](source-intake.md#books-and-chapters) in order as separate sources and skips the whole-book file, reporting the substitution, unless the user explicitly asks for that file. Report each substantive table-of-contents section no chapter covers (often introductions, appendices, glossaries) as not processed.

**The overlaid tree.** Once an earlier source has produced a draft, run [step 7](../SKILL.md#7-review-and-report)'s `review_tree.py` command with the current manifest (same `--out`; each call rebuilds it) and use the `tree` it reports: the current Wiki's regular entries with every staged draft overlaid. Leave its lint findings for step 7. Each `unmirrored` path stays an occupied slug and leaves "no match" uncertain, as in the real index. Use this tree both as step 3's `<resolution-tree>` and as the `<coverage-tree>` of later [prior-coverage](source-intake.md#check-prior-coverage) queries, so later sources merge with, rather than collide with or ignore, earlier work, and staged coverage counts in skip decisions. Add `--wiki-origin '<vault>/Wiki'` (its actual public location) only to the coverage query's `vault_index.py` call, because note-relative links must not resolve from scratch.

**One named entity from several sources.** Prove that every passage names the same contextually resolved entity; an ambiguous surface, a homonym or two related concepts cannot be joined to make the substance test pass. The union must explain what the entity is, how it works, what it contrasts with or why it matters well enough for one self-contained atomic entry. Every retained source must contribute a specific verifiable claim, condition, equation, date or limitation; two passing mentions do not become substance, and a secondary source contributes only durable material. Record each retained claim against its source, list every contributing source in `sources:`, omit a named source whose text added no selected claim, and integrate one coherent entry rather than one paragraph per source.

The missed-entity audit runs [per source](review.md#missed-entity-audit-source-coverage), in the run's own order.

## Skip, rerun and resume

**In a folder or inbox-wide run, a confirmed prior match means SKIP:** do not read the source, extract or modify entries; report it with the number of entries citing it and the instruction to name the source to fill it in. A rerun churns body prose, resets `updated:` and, because churned prose is body content, clears `read:` on entries the user had already read, for no gain.

**Explicit rerun intent** in the request or this run's existing authorization ("re-process", "re-run", "apply the new rules to existing entries", or equivalent) additionally re-merges entries that already cite the source. Rerun and resume intent are run-level: if the prompt signals one, every previously processed source in the batch proceeds. Ambiguous intent is neither; unresolved source identity or malformed metadata is reported and resolved, never an automatic previously-processed verdict.

**Resume belongs to wiki-build.** A prior match proves that some entry cites the source, not that an interrupted run completed extraction, every merge, interlinking or the three audits. Under explicit resume intent ("resume the interrupted run", "finish the incomplete run"), re-read the complete source and run the normal workflow over it: existing coverage goes through the same collision and source-no-op-merge checks, and missing entities and source-dependent repairs go through their ordinary gates. This is deliberately a safe rerun, not an attempt to infer an interruption point from partial files. wiki-lint may clean source-independent residue before or after, but it cannot recover omitted source claims, entries, page anchors or figure choices and never owns completing the source run. On an authorized resume, this skill's audits cover every entry the resumed run creates or touches; inherited source-independent defects elsewhere stay wiki-lint's.

**If every source in the run is skipped** (previously processed with no rerun or resume intent, or no durable content under step 2(c)), nothing is created or merged, so every step-7 audit has empty scope. Report the skips and go directly to the [closeout](../SKILL.md#closeout), using only evidence already obtained; do not audit skipped entries, sources or unrelated entries.
