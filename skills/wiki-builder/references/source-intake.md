# Source intake and prior coverage

Read this before resolving a Markdown source, uncertain source identity, or incomplete prior-coverage results in [workflow step 1](../SKILL.md#1-read-the-source). The normal PDF route and its skip gate remain in the entrypoint. This reference owns the validated parser recipe, legacy-origin handling, and detailed source classification.

- [Resolve a Markdown source](#resolve-a-markdown-source)
- [Check prior coverage](#check-prior-coverage)
- [Read and classify](#read-and-classify)

## Resolve a Markdown source

A `.md` handed to this skill may be a *clipping* note — real prose, and a source in its own right — or a note **about a PDF** that is already sitting in `Sources/PDFs/`, which is the same document under a second name. The two are indistinguishable by path, and the difference decides both which file gets read and which name the already-processed check has to probe.

**The tell is `sources:` item 1, not the body.** Per `CONVENTIONS.md` §2b, a note about a document opens its `sources:` list with the document's origin — a **URL** item for a web clipping, and a **wikilink to a local PDF** for a note about that PDF. Read the complete frontmatter with the validated parser below. A block list, a flow list, a comment and a YAML escape must produce the same decoded source identity. The line after `sources:` is not necessarily its first item. A `paper-summarizer` note may contain hundreds of words of structured summary while an older embed-note contains just `![[Something.pdf]]`; neither body tells you which source to process.

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

**A first `sources:` item of the form `"[[Something.pdf]]"` means the note is *about* that PDF, and the PDF is the source.** Resolve that decoded local target within the selected vault, honoring any folder qualification and comparing names with NFC normalization and case folding; preserve suffixes such as `_2` and `_01_ChapterName`. Process the resolved PDF instead of the note, and record the substitution in the run report. If several files match a basename, report the ambiguity and resolve it before reading or automatically skipping the source. **This is not a preference:** an `Articles/` note is somebody's hedged restatement of the paper, so extracting entries from it builds the vault on a summary while the document itself goes unread, and every `sources:` item it produces is an anchorless `[[Foo.md]]`. Only if the PDF is genuinely missing from disk does the note become the source — say so in the report, since those entries get no page anchors. A first item that is a **URL** is a web clipping: that note *is* the source, and you carry on with it.

**An absent or empty `sources:` list is a third outcome with its own rule.** A note written under the retired `topics:` schema carries a scalar `source:` instead (`CONVENTIONS.md` §2c); inspect the decoded `legacy_source` from the same parser and branch on it as above. If both are absent or empty in otherwise valid frontmatter, the note is an **unpaired markdown source**: process it as one, and record the call in the run report. A markdown source with no frontmatter can likewise be unpaired after inspecting it. Malformed YAML, a non-list `sources:`, a null item, or conflicting modern and legacy origins is not evidence of an unpaired source: report it and establish the identity before proceeding. Do not silently fall back to the summary or infer an automatic skip from malformed metadata.

## Check prior coverage

```bash
IDX=$(mktemp -t vault-index-XXXXXX.json)
python3 '<skill>/scripts/vault_index.py' '<wiki-folder>' \
  --source 'Foo.pdf' --source 'Foo.md' -o "$IDX"
```

Substitute the actual on-disk names with their extensions, using one `--source` for an unpaired source and both actual names for a resolved PDF/note pair; the note need not have the PDF's stem. Read `source_matches` and `problems` in `$IDX`. Matching uses only decoded frontmatter `sources:`, compares literal target basenames after NFC normalization and case folding, accepts folder-qualified targets and page anchors, and preserves numeric disambiguators. A body example mentioning `[[Foo.pdf]]` does not count as having processed Foo. The walk includes subfolders. If the wiki does not exist yet, there are no prior entries to inspect; omit this step and create its folder at step 3 only if candidates survive extraction. If `problems` is nonempty or the source identity is ambiguous, review and report the uncertainty before deciding; do not infer either an automatic skip or permission to rewrite existing entries from incomplete lookup data.

**Any confirmed source match means the default action is to SKIP** — don't read it, don't extract, don't modify entries. Re-runs churn body prose, reset `updated:`, and — because churned prose is body content — clear `read:` on entries the user had already read, for no gain. **Proceed only on explicit re-run or resume intent in the user's request or existing authorization for this run** ("re-process", "re-run", "resume the interrupted run", "finish the incomplete run", "apply the new rules to existing entries", or equivalent). A plain "process Foo.pdf" does not qualify, even about a known-processed source. Ambiguous intent after a confirmed match → skip; unresolved source identity or malformed metadata → report and resolve, not an automatic previously-processed verdict. Intent is run-level: if the prompt signals it, all previously-processed sources in the batch proceed.

**Resume belongs to wiki-builder.** A prior match proves that some entry cites the source; it does not prove that an interrupted run completed extraction, every merge, interlinking, or the two audits. Under explicit resume intent, re-read the complete source and run the normal workflow over it. Existing coverage goes through the same collision and no-op-merge checks, while missing entities and source-dependent repairs go through their ordinary gates. This is deliberately a safe re-run rather than an attempt to infer an interruption point from partial files. wiki-linter may clean source-independent residue before or after this run, but it cannot recover omitted source claims, entries, page anchors, or figure choices and is never the owner of completing the source run.

**If every source in the run is skipped** — previously processed with no re-run/resume intent, or no durable content under step 2(c) — nothing is created and nothing is merged, so both step-7 audits have empty scope and the run is a genuine no-op. Report the skips and stop. On an authorized resume, this skill's audits cover every entry the resumed run creates or touches; inherited source-independent defects elsewhere in the vault remain wiki-linter's scope.

## Read and classify

Read the whole source in one pass — extraction needs relationships across sections, not within chunks. PDFs: read with the `pdf` skill, or extract via `pdftotext -layout` / PyMuPDF, rasterizing pages where you need to see figure content (for your comprehension only — embedded figures come from `Sources/Images/`, never from your rasterization). Markdown: read directly. For very long sources, map the headings first, then read in entity-dense passes; keep one source inside one run. Note the canonical on-disk filename, and track **the physical page where each entity is introduced** — each entity gets its own `#page=N`. Sources are real files on disk; a URL or pasted excerpt has to be saved into the vault first.

**Classify the source.** *Primary* = teaching durable knowledge is its main purpose (papers, chapters, reviews, substantive explainers, lecture notes) → the substance test alone gates extraction. *Secondary* = primarily transient signal (news, earnings, announcements, opinion posts) → the durability test applies **in addition**.

**Classify by the source's primary purpose, not incidental content.** An earnings roundup remains secondary when it pauses to explain a technology: the durability test admits the lasting explanation and rejects the quarter's result. **Ambiguous → secondary.** Report the classification. Do not reclassify a news source merely to admit more candidates; a separately curated substantive note can instead be processed as its own source under the normal tests.
