# Review the complete draft

- [Run the mechanical sweep](#run-the-mechanical-sweep)
- [Compare structure with the source](#compare-structure-with-the-source)
- [Check metadata and shape](#check-metadata-and-shape)
- [Check the summary and cleaned body](#check-the-summary-and-cleaned-body)
- [Check attachments and audit results](#check-attachments-and-audit-results)
- [Fix or flag, then publish](#fix-or-flag-then-publish)

Read for every clipping after its completeness audit and before publication.
Review the saved scratch draft. Keep the published original and its image names
unchanged until [safe replacement](duplicates-and-reprocessing.md#publish-an-approved-replacement).

## Run the mechanical sweep

Run the following, then inspect every match in context. These commands do not
parse Markdown: ignore YAML and literal fenced/inline code when judging body
matches. Never edit source code to satisfy a prose detector.

```sh
f='<path to the completed scratch .md>'
echo "[1  H1 in body — expect NONE]";                          grep -nE '^# ' "$f"
echo "[2  Summary callouts — expect exactly 1]";               grep -cE '^> \[!Summary\]' "$f"
echo "[3  leftover raw image refs ![](…) — NONE]";             grep -nE '!\[[^]]*\]\(' "$f"
echo "[4  stray HTML tags — NONE outside code/kept tables]";   grep -noE '<(br|span|div|sup|sub|font|small|hr)[ />]' "$f"
echo "[5  clipping chrome — NONE]";                            grep -niE 'subscribe|read more|continue reading|sign in|share this|^comments|loading comments|write a comment' "$f"
echo "[6  backlink/nav panel header — NONE]";                  grep -niE '^[[:space:]>#*]*(backlinks?|what links here|mentioned in|citations of this page)([^A-Za-z0-9]|$)' "$f"
echo "[7  malformed emphasis: odd *-run count — see body ckl]";awk 'gsub(/\*+/,"&")%2==1 {print FNR": "$0}' "$f"
echo "[8  stacked list markers: source-check candidates]";        grep -nE '^(>[[:space:]]?)*[[:space:]]*([-*]|[0-9]+\.)([[:space:]]+([-*]|[0-9]+\.))+[[:space:]]' "$f"
echo "[9  currency \$-then-digit: each must be \\\$ or math]";  grep -nE '\$[0-9]' "$f"
echo "[10 unescaped \$ parity: must be EVEN after escaping]";   grep -oE '(^|[^\\])\$' "$f" | wc -l
echo "[11 dropped-\$ candidates: source-compare, NOISY]";       grep -nE '/[ =]|/1[KMB]([^A-Za-z0-9]|$)|/(GPU|hour|min|token)|per (hour|GPU|min)|[0-9]+/[0-9]|\([^)]*in (1[89]|20)[0-9]{2}\)' "$f"
echo "[12 nested-list deep indent: candidate, NOISY]";         grep -nE $'^(>[ \t]?)*\t\t' "$f"
echo "[12b sibling indent split: candidate, NOISY — run body-cleaning sibling-consistency script on \$f]"
echo "[13 footnote refs vs defs: the two lists must be identical]"
  printf '  refs: '; sed 's/^\[\^[0-9]*\]://' "$f" | grep -oE '\[\^[0-9]+\]' | tr -d '[]^' | sort -n | uniq | tr '\n' ' '; echo
  printf '  defs: '; grep -oE '^\[\^[0-9]+\]:' "$f" | tr -d '[]^:' | sort -n | uniq | tr '\n' ' '; echo
echo "[14 leftover HTML <table> — NONE unless complex]";       grep -nE '<table' "$f"
echo "[15 decorative HR BELOW the ___ separator — NONE]";      awk 'flag && /^([-*_]{3,}|<hr>)[[:space:]]*$/ {print FNR": "$0} /^___[[:space:]]*$/ {flag=1}' "$f"
```

If a runner rejects sliced output as invalid UTF-8, a permitted
`2>&1 | iconv -f utf-8 -t utf-8 -c` output filter can make the diagnostic readable.
It does not repair the note itself.

Read the results as follows:

- Required in rendered prose: no H1, exactly one actual Summary callout, no
  remote-image reference left without a failure placeholder, and no confirmed
  clipping damage. A code example is not a second callout.
- Odd asterisk runs, stacked markers and deep indentation are **candidates**.
  List bullets, escapes, multiline emphasis and genuine nested lists can match.
  Use the [body-cleaning rules](body-cleaning.md#repair-structure-and-markup)
  and sibling-consistency scan before repairing. A parent with children stays
  nested; peer dialogue turns should align.
- Currency-rate and inflation matches require comparison with the source.
  Fractions/dates are expected false positives. After literal currency dollars
  are escaped, check math-delimiter pairing; an even count alone is not proof.
- Stray-HTML matches may be intentional complex tables or non-math sup/sub.
  Preserve those cases according to body cleaning.
- Do not use a bare MathJax-delimiter grep as a verdict: escaped Wikipedia URL
  parentheses and literal brackets are legitimate. Inspect actual formulas.

## Compare structure with the source

Compare the ordered heading outline and coarse counts of lists, quotes, links,
images, tables and code blocks. Use the fetched source when available; when its
fetch failed, compare against the original capture and report the live-source
limit. A representative note-side outline/count scan is:

```python
import re, sys
body = open(sys.argv[1]).read()
body = re.sub(r'^---\n.*?\n---\n', '', body, count=1, flags=re.S)   # drop YAML
heads  = [(len(m.group(1)), m.group(2).strip())
          for m in re.finditer(r'^(#{1,6})\s+(.*)$', body, re.M)]
counts = dict(
    list_lines = len(re.findall(r'^\s*(?:>\s?)*\s*(?:[-*]|\d+\.)\s', body, re.M)),
    quote_lines= len(re.findall(r'^\s*>', body, re.M)),
    links      = len(re.findall(r'\[[^\]]+\]\([^)]+\)', body)),
    image_embeds = len(re.findall(r'!\[\[?', body)),
    code_fences  = body.count('```'),
)
print("HEADINGS:", *(f"{'#'*l} {t}" for l,t in heads), sep="\n  ")
print("COUNTS:", counts)
```

Counts are tripwires, not assertions. Exclude the note's generated callout and
source chrome from interpretation. Account for normalized heading levels,
converted footnotes, removed share links and known intentional omissions.
Inspect large divergences: a missing/misordered heading, an unexpectedly small
figure inventory, or a list/quote/link count differing by a large factor.

Use [body cleaning](body-cleaning.md) for confirmed structural damage and the
[completeness audit](completeness-audit.md) for source gaps. Do not auto-insert
missing prose. This text comparison cannot prove visual rendering; report that
limit where material. For a recurring new defect, report a minimal example and
suggested detector; do not edit an installed plugin during clipping processing.

## Check metadata and shape

- [ ] Generated frontmatter follows the shared
  [source-note schema](../../../shared/CONVENTIONS.md#2b-source-note--a-note-about-a-document)
  and [clipping metadata rules](metadata-verification.md#frontmatter-for-the-polished-note).
  Legacy migrations preserved their information in tags/report. Unrelated user
  fields, including `topics:`, were not stripped to enforce a generated schema.
- [ ] First current `sources:` item establishes web ownership; legacy `source:`
  is used only when current `sources:` is absent. This is not a PDF summary.
  The output has its one preserved capture URL, no substituted canonical URL.
- [ ] Corrected title, byline and publication date match their evidence;
  unverified values and padded dates are reported. Meaningful Unicode remains.
- [ ] Description is factual and at most 110 characters; format follows content
  (`Article`, `Post`, or `Video` for a substantive transcript), and tags follow
  the shared enum rather than invented synonyms.
- [ ] A new note uses bare `read: false`. A rewrite preserves the review state,
  including absent/unknown values, and reports those states rather than forcing
  a boolean. If a required schema check rejects that state, the draft stays
  unpublished. The capture URL and existing clipping date are unchanged.
- [ ] The Summary starts immediately after YAML, appears once, and has the
  prescribed blank-line/`___` boundary before the body. No stale old callout
  remains inside the article.
- [ ] Headings preserve source structure after normalization: H2 top-level,
  H3 children, genuine containers above their entries, no invented headings
  or body H1. A confirmed heading is not stranded as a bold-only line.

## Check the summary and cleaned body

- [ ] The first bullet is a standalone thesis. Every bullet names its own
  subject, states a complete claim and retains scope, confidence, terms and
  numbers. No contextless “It/This/They”, meta-framing or links.
- [ ] Bold emphasizes wiki-worthy entities without spreading to ordinary
  technical words; bullet count is appropriate to the article's length.
- [ ] The captured prose is preserved without paraphrase or truncation. Chrome,
  auto-generated backlink panels and run-on navigation are gone; curated
  further-reading links and intentional source content remain.
- [ ] Images are local embeds or reported failure placeholders. A confirmed
  caption is one italic line below the embed; ambiguous ledes remain prose.
  Caption/credit orphans are removed only with evidence, not when they could
  be a quotation, aside or retained failed-image caption.
- [ ] Decorative rules are removed only from body prose, not YAML, code or the
  Summary/body separator. Code and simple/complex tables follow body-cleaning
  fidelity rules. Footnote references and definitions correspond.
- [ ] Equations use Obsidian delimiters. Genuine formulas flattened to
  typographic text were restored only with source evidence; ordinals, prices,
  dates, chemical names and prose notation were not forced into math mode.
- [ ] Literal currency dollars are escaped and math delimiters balanced.
  Source comparison also catches **dropped** symbols or denominators, such as
  `0.03/1K tokens`, `33K tokens/` or a bare amount before an inflation note.
  Restore only what the clipping lost, not an author's original odd wording.
- [ ] Missing equation/diagram bodies are flagged, never reconstructed from a
  dangling label or a sentence with a missing symbol. Confirmed split/scrambled
  emphasis and list damage are repaired without flattening legitimate nesting.

## Check attachments and audit results

- [ ] Each draft embed resolves to a real file or through the reviewed rename
  mapping to an existing file. Planned names match the final note stem/casing.
  Do not rename live images just to make the draft pass this check.
- [ ] Completed images were opened for readability; their returned extensions
  match the format. No newly created extension twins or unexplained missing
  attachments remain. Preserve old/foreign files and report conflicts.
- [ ] Every capture has an explicit completeness verdict with the actual access
  limits. Each recovery, gap, placeholder and approximate placement is reported.
- [ ] Recovered captions follow the [fallback chain](completeness-audit.md#recover-missing-images).
  A synthesized caption draws only from its immediately preceding lead-in and
  carries its marker; an unsupported description becomes a bare embed.
- [ ] Reprocessing did not duplicate embeds or placeholders. One Lottie is
  represented by one verified GIF, or a labeled poster, or an actionable
  placeholder. A static poster is not presented as an animation.
- [ ] Converted GIFs were visually inspected, including the middle frame and
  labels. A bad render gets a draft poster embed at a fresh number or a source
  placeholder. Preserve any existing GIF; never replace its bytes with another
  format or placeholder text.

## Fix or flag, then publish

Fix confirmed mechanical damage **in the draft**. Existing-image renames stay
in the reviewed publication plan. Flag unresolved judgment calls and missing
source content for the user; do not silently invent an answer.

Log every fix/flag and any inability to complete a required check. Once the
review is complete, return to [publication](../SKILL.md#6-publish-safely),
then read back the published note and verify its final embeds before reporting
completion.
