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

Run the sweep on the complete scratch draft, then inspect every match in
context:

```bash
python3 '<skill>/scripts/body_checks.py' sweep '<path to the completed scratch .md>'
```

It prints numbered items 1–17 (with 12b), each with its expectation. It skips
the leading YAML block and fenced code, and reports an unclosed fence, whose
lines it scans as prose. It does not parse inline code: ignore literal inline
code when judging a match. Never edit source code to satisfy a prose detector.

Read the results as follows:

- Required in rendered prose: no H1, exactly one actual Summary callout, no
  remote-image reference (Markdown, or HTML such as `<img>`, `<picture>` or
  `<figure>`) left without a failure placeholder, and no confirmed clipping
  damage.
- Odd asterisk runs, stacked markers, deep indentation and sibling splits
  (items 7, 8, 12 and 12b) are **candidates**. List bullets, escapes, multiline
  emphasis and genuine nested lists can match. Use the
  [body-cleaning rules](body-cleaning.md#repair-structure-and-markup) and
  [nested-list repair](nested-lists.md) before repairing. A parent with
  children stays nested; peer dialogue turns should align.
- Currency-rate and inflation matches require comparison with the source.
  Fractions/dates are expected false positives. After literal currency dollars
  are escaped, check math-delimiter pairing; an even count alone is not proof.
- Stray-HTML matches may be intentional complex tables, a `<br>` in a pipe-table
  cell, or a retained sup/sub with no plain equivalent. Chrome and
  backlink-header matches are candidates: remove only confirmed chrome under
  body cleaning, and keep article prose that uses those words.
- Do not use a bare MathJax-delimiter grep as a verdict: escaped Wikipedia URL
  parentheses and literal brackets are legitimate. Inspect actual formulas.

## Compare structure with the source

Compare the ordered heading outline and coarse counts of lists, quotes, links,
images, tables and code blocks. Use the fetched source when available; when its
fetch failed, compare against the original capture and report the live-source
limit. The note-side outline and counts come from `outline`; the source-side
outline and counts come from `source` on the saved markup:

```bash
python3 '<skill>/scripts/body_checks.py' outline '<path to the completed scratch .md>'
python3 '<skill>/scripts/body_checks.py' source '<saved markup file>' --base-url '<capture URL>'
```

Counts are tripwires, not assertions. Exclude the note's generated callout and
source chrome from interpretation. A source heading tagged `[hidden]` is
screen-reader-only text that readers never saw: it is not a missing heading,
and no heading is added for it. Account for normalized heading levels,
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
  Unrelated user fields were preserved rather than stripped to enforce a
  generated schema; conflicting or uninterpretable values were reported.
- [ ] First current `sources:` item establishes web ownership; legacy `source:`
  is used only when current `sources:` is absent. This is not a PDF summary.
  The output has its one preserved capture URL (an overwrite keeps the existing
  note's origin), no substituted canonical URL.
- [ ] Corrected title, byline and publication date match their evidence. Every
  `author:` value is a human byline supported by the capture or usable source;
  capture-only values remain explicitly unverified against an unavailable live
  page. Publication names, editorial
  desks and social accounts are omitted rather than credited as people. The
  filename's optional author segment agrees with the first retained human
  author. Unverified values and padded dates are reported. Every published note
  has an evidence-backed title. A missing publication year is represented only
  by `published: null` plus the `nd` filename segment; a capture missing its
  title was retained raw and skipped rather than receiving an invented identity.
  Meaningful Unicode remains.
- [ ] Description is factual and at most 110 characters, and attributes an
  argued thesis, forecast or recommendation to whoever argues it
  ([rule](../SKILL.md#4-assemble-the-complete-draft); the interviewee or
  quoted subject in a reported piece); format follows content
  (`Article`, `Post`, or `Video` for a substantive transcript), and tags follow
  the shared enum rather than invented synonyms (`tags: []` when none fits).
- [ ] A new note uses bare `read: false`. A rewrite preserves the review state,
  including absent/unknown values, and reports those states rather than forcing
  a boolean. The capture URL and existing clipping date are unchanged.
- [ ] The Summary starts immediately after YAML, appears once, and has the
  prescribed blank-line/`___` boundary before the body. No stale old callout
  remains inside the article.
- [ ] Headings preserve source structure after normalization: H2 top-level,
  H3 children, genuine containers above their entries, no invented headings
  or body H1. A confirmed heading is not stranded as a bold-only line.

## Check the summary and cleaned body

- [ ] The summary meets [draft assembly](../SKILL.md#4-assemble-the-complete-draft):
  a standalone thesis first; one claim per bullet, naming its own subject and
  keeping scope, confidence, terms and numbers; opinions attributed to whoever
  holds them and facts stated directly; no contextless “It/This/They”,
  meta-framing or links; entry-worthy bold only; a bullet count that fits the
  article's length.
  Sweep item 16 lists the bullet count and the long or linked bullets to judge.
- [ ] The captured prose is preserved without paraphrase or truncation. Chrome,
  auto-generated backlink panels and run-on navigation are gone; curated
  further-reading links and intentional source content remain. Each split link
  that sweep item 17 lists was merged into one link or confirmed as separate
  links, per [body cleaning](body-cleaning.md#repair-structure-and-markup).
  Hidden AI-directed text was removed only on markup evidence, and reported.
- [ ] Images are local embeds or reported failure placeholders. A confirmed
  caption is one italic line below the embed; ambiguous ledes remain prose.
  Caption/credit orphans are removed only with evidence, not when they could
  be a quotation, aside or retained failed-image caption. Failure placeholders
  and reports use the helper's redacted URL locator; no image credentials,
  query string, fragment, or inline data payload was copied into the output.
- [ ] Decorative rules are removed only from body prose, not YAML, code or the
  Summary/body separator. Code and simple/complex tables follow body-cleaning
  fidelity rules. Footnote references and definitions correspond.
- [ ] Equations use Obsidian delimiters and follow [equations](equations.md).
  Genuine formulas flattened to typographic text were restored only with
  source evidence; ordinals, prices, dates, chemical names and prose notation
  were not forced into math mode.
- [ ] Literal currency dollars in the Summary and body are escaped (never in
  YAML values), and math delimiters are balanced.
  Source comparison also catches **dropped** symbols or denominators, such as
  `0.03/1K tokens`, `33K tokens/` or a bare amount before an inflation note.
  Restore only what the clipping lost, not an author's original odd wording.
- [ ] Missing equation/diagram bodies are flagged, never reconstructed from a
  dangling label or a sentence with a missing symbol. Confirmed split/scrambled
  emphasis and list damage are repaired without flattening legitimate nesting.

## Check attachments and audit results

- [ ] Each draft embed names a staged scratch file (a new or recovered image),
  an existing attachment (unchanged slug), or, for a changed slug, an existing
  old-slug attachment with only the slug replaced. Planned names match the
  final note stem/casing. Nothing is placed or renamed before publication; do
  not rename live images just to make the draft pass this check.
- [ ] Completed images were opened for readability; their returned extensions
  match the format. No newly created extension twins or unexplained missing
  attachments remain. Any SVG is inert and self-contained and passed the
  helper's active/external-content refusal. Preserve old/foreign files and
  report conflicts.
- [ ] Every capture has an explicit completeness verdict with the actual access
  limits. Each recovery, gap, placeholder and approximate placement is reported.
- [ ] Recovered captions follow the [fallback chain](completeness-audit.md#recover-missing-images).
  A synthesized caption draws only from its immediately preceding lead-in and
  carries its marker; an unsupported description becomes a bare embed.
- [ ] Reprocessing did not duplicate embeds or placeholders. One Lottie is
  represented by one verified GIF, or a labeled poster, or an actionable
  placeholder. A static poster is not presented as an animation.
- [ ] A reprocessed draft keeps the old note's block IDs byte-for-byte. Each
  block ID or linked heading it cannot match is reported with the notes that
  link it ([body source](duplicates-and-reprocessing.md#reprocessing-an-existing-note)).
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
