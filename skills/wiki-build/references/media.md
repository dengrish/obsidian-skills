# Images and captions

> **When to read this:** Read this when the step-4 `vault_artifacts.py figures` report has candidates or findings, a Markdown source contains image references, or reading the source reveals figures with no available image file. Inventorying figures does not require using or extracting every one. When there are none, say so in the report rather than guessing at images.

---

## Images

**Inventory all source figures, then select for the entry's needs.** Include the source's figure references, all matching local files, and Markdown image references in the inventory before judging relevance. Do not narrow the inventory to the images you expect to use. A focused wiki entry usually needs zero or one figure; an informative source figure is still optional. The [selection rule](#selection) decides what earns a place. Source tables follow the separate [Markdown table rule](writing.md#body-structure), which selects useful rows and columns while preserving their values.

Use the shared inventory command from workflow step 4, not a recursive shell
glob. It compares the literal `<resolved_source_stem>_fig` prefix under NFC
normalization and case folding, accepts every extension and older separator
form, and returns only direct regular non-staging files in `candidates`.
`Sources/Images/` is flat: symlink/nonregular occupants, portable-equivalent
names, and matching files in normal nested folders are `blocked_matches` and
make the inventory unsafe. Recognizable staging residue is reported but never
consumed. An unreadable directory makes absence unproved. Read the complete
JSON, resolve or report those findings, and never turn an empty partial result
into “this source has no figures.” The stem is from the source actually being
read after source resolution: the PDF stem after a summary-to-PDF substitution,
or the cleaned Markdown note's stem for a clipping.

**Where images come from depends on the source type:**

- **PDF source.** Figures come from the `figure-extract` skill in the vault's `Sources/Images/` folder. Naming pattern: `[pdf_stem]_fig_<N>.png`, where `<N>` is the figure number exactly as it appears in the source — which may be a simple integer (`1`), a chapter-and-figure pair (`1-2` for "Figure 1.2"), or a deeper hierarchy (`1-2-4` for "Figure 1.2.4"); supplementary figures use an `S` prefix on the number (`S1`, `S2-3`). Examples: `Burges_LearningToRank_2010_fig_1.png`, `Geron_HandsOnML_2025_03_Classification_fig_3-2.png` (chapter 3, figure 2), `Prince_UDL_2026_12_Transformers_fig_1-2-4.png`, `Doe_GutMicrobiome_2025_fig_S1.png` (supplementary figure 1) — all canonical stems, which is what `pdf-organize` produces and what `figure-extract` refuses to key a figure to otherwise (`CONVENTIONS.md` §1a). The step-4 inventory also matches older naming forms and any extension, so never replace it with a narrower glob ([CONVENTIONS §8](../../../shared/CONVENTIONS.md#8-figure-naming-and-sourcesimages)). **A source figure with no extracted file stays in the inventory as unavailable.** Do not fabricate it or silently claim that the source has no figures; when the inventory is empty, first [prepare missing PDF figures](#missing-pdf-figures). Report an unavailable figure that would materially help the entry. **Tables are not pre-extracted** — when the source has a table worth recreating in the entry, identify it while reading the PDF and recreate it in Markdown per the Body Structure tables rule.
- **Markdown source.** Image references live in the source `.md` itself. **A note produced by `clipping-clean` names its downloaded images `[source_stem]_fig_<N>.<ext>` — the note's own filename stem, same string and same casing** — so the step-4 inventory and the unused-figure diagnostic below find them. Where a download failed, clipping-clean leaves `<!-- image download failed: … -->` at the image's position and keeps any former caption as an ordinary paragraph. Inventory each placeholder as an unavailable source figure with that skip reason; never copy the comment or its orphaned caption into an entry. Older or hand-made Markdown sources may still contain remote `![alt](https://…)` images, which have no file in `Sources/Images/`: inventory them from the source text, and reuse a selected one in Markdown form. Never rewrite it as a wikilink, which would resolve to nothing and lose the URL.

**A figure and its panels are one exhibit, and the composite is the default when selected.** A file whose label ends in a lowercase letter — `Burges_LearningToRank_2010_fig_3a.png` beside `Burges_LearningToRank_2010_fig_3.png` — is one panel of that figure (`CONVENTIONS.md` §8b). It appears as a raw file in the inventory's `candidates` array because it answers the `_fig` match, but it is not a separate exhibit for selection or reporting. Prefer the whole figure; use an available panel when the entry's subject is that panel's alone. Never place a figure and a panel of it in the same entry. For selection and reporting, an exhibit is the composite: an unplaced panel needs no separate skip reason, placing the composite discharges every panel under it, and placing any panel discharges the composite. Preserve existing filenames and panel identity.

### Missing PDF figures

Sometimes a PDF source shows or refers to figures, but its complete, safe
step-4 inventory has no `candidates`. After the parser check passes, an apply
run then extracts that PDF alone, once, before selecting exhibits:

```bash
python3 '<plugin>/skills/figure-extract/scripts/batch_extract.py' \
    --src '<resolved pdf path>' --out '<images-folder>'
```

Carry an intake exception such as `--allow-unorganized`, and any non-default
option that an earlier extraction report or the extractor's printed rerun
command names, into this command and any repair command. Pass
`--ed-prefix ED` when `<stem>_fig_ED*` files exist or the captions number
Extended Data figures alongside the main figures. Respect the extractor's
naming, collision and ownership refusals, and read its diagnostics.

Then complete figure-extract's
[visual review](../../figure-extract/SKILL.md#3-inspect-the-summary-and-verify-crops)
of the crops this run wrote: view each one, or at least every flagged and
multi-column crop. Repair only crops this run produced, through
figure-extract's explicit-crop workflow: one the review flags, or one that
proves defective at [selection](#selection). Re-run the inventory after the
extraction and after each repair. Never overwrite, adopt or repair a
pre-existing image; the image folder is otherwise read-only. A preview/no-apply
run writes nothing and reports the gap. An unsafe or partial inventory, or an
extraction that cannot supply a figure, leaves that figure unavailable and
reported under *Unused source figures*.

## Selection

**Include a figure only when it directly clarifies the entry's own definition, mechanism, or an essential distinction and offers a real explanatory benefit over concise prose alone.** A visual can make the same point clearer, but being informative or appearing in the source is not enough. Leave out decoration, routine applications, and visuals that teach a neighboring concept. Do not add a paragraph, topic, or example just to accommodate an image.

**Default to zero or one figure per focused entry.** An additional figure must explain an essential, nonredundant aspect of the same entity that the retained figure and concise prose cannot explain as clearly. Record that concrete benefit in one line in the run report. Different aspects are not automatically essential: a mechanism diagram does not create a need for an applications gallery. For an existing entry, use the [merge preservation rule](merge.md#frontmatter-and-related-footer); this preference never authorizes silently removing its current images.

**Pair each selected figure with the most specific eligible entry it directly explains.** A gradient-scaling diagram belongs in `lambdarank.md`, not the broader `learning-to-rank.md`. When no entry has the right scope, skip the figure instead of stretching the nearest entry to fit it. A figure can inform the substance judgment, but it does not bypass step 2's eligibility rules.

**Open each newly selected local image before embedding it.** A valid filename does not prove the contents. Confirm that the image is the intended whole figure or panel, is readable, and contains no caption text or neighboring chart; then write its caption from what it shows, checked against the source. Skip a defective crop as an unusable asset and report it; a crop this run's own extraction produced may instead return to [missing PDF figures](#missing-pdf-figures) for figure-extract's explicit-crop repair. If the host cannot display images, report that limit and embed no unviewed crop. Preserved existing embeds and remote images need no new check.

**Record a specific reason for every unused exhibit.** Valid reasons include:

- No explanatory benefit: decorative, or the concise prose already makes the point just as clearly.
- Redundant with a retained figure: name the figure and the aspect already covered.
- Outside the entry's scope, or an unnecessary application, example, or implementation detail.
- No eligible entry: the relevant entity was deferred or rejected under step 2.
- Unavailable or unusable asset: identify the source figure and any resulting limitation rather than inventing an embed.

The reason must describe this figure's contribution, not merely say that the note has reached its image limit.

**Diagnostic for forgotten figures.** Reconcile the complete inventory against embeds and recorded skip reasons (Quality Checklist item 12). An unused exhibit with no reason needs a selection decision, not automatic placement. Many unused figures are acceptable when their reasons hold; the check measures whether every figure was considered, not the proportion included. Report remote references, failure placeholders, and other unavailable source figures as well as local `[source_stem]_fig*` files, with panels grouped under their composite. For Markdown sources, include every rendered image reference even when an older local filename has a different source prefix. Resolve those references directly; the filename mismatch neither makes a resolving image unavailable nor authorizes renaming it.

## Placement and embed syntax

**Embed syntax.** Use Obsidian's image-embed wikilink form: `![[Burges_LearningToRank_2010_fig_3.png]]` for `Sources/Images/`-based images (Obsidian resolves the basename across the vault). For external URLs from a markdown source's clipping, use standard markdown image syntax `![alt](https://...)` since wikilinks don't handle remote URLs — the `alt` slot is plain alt-text (typically left empty or filled with a brief identifier), **not** the wiki-build caption. **The italic-caption-on-next-line rule (see *Captions* below) applies uniformly to both embed forms** — wikilink and markdown — so every image embed, however written, has its `*caption*` line directly below it.

**Placement: inline, on the line immediately after the sentence or paragraph the image illustrates.** Placement is determined by the image's motivating prose, not by a fixed slot.

Specifically forbidden:

- **Image without a caption below it.** Every embed has a one-line italic caption on the next line — see "Captions" below.
- **Image detached from its motivating prose, parked at the end of the body just before the Related footer.** This is the default "treat the image as a trailing afterthought" failure mode — and the most common image-placement mistake. If the image illustrates content from the second paragraph of a multi-paragraph body, the image goes between the second and third paragraphs — not at the bottom of the last paragraph. The rule is "next to the motivating prose" — wherever in the body that prose lives.
- **Image at the top of the entry**, before the first prose paragraph. The opening sentence is the canonical definition; nothing visual precedes it.
- **Multiple exhibits grouped as a gallery** anywhere in the body. Each selected image or table belongs beside its own motivating paragraph, and that paragraph must already earn its place without the exhibit. One paragraph supports at most one exhibit total: if two images, or an image and a table, compete for it, choose the more helpful form. Do not stack exhibits or write extra prose to create slots.

Example of correct inline placement:

```markdown
**LambdaRank** is a [[learning-to-rank|learning to rank]] method that sidesteps the non-differentiability of ranking metrics by defining gradients directly, scaled by the change in the target metric from swapping a pair of items.

It starts from [[ranknet|RankNet]]'s pairwise cross-entropy loss and scales each pair's gradient by the absolute change in [[ndcg|normalized discounted cumulative gain]] (NDCG) from swapping the two items in the current ranking.

![[Burges_LearningToRank_2010_fig_3.png]]
*The gradient is scaled by the NDCG change from swapping a pair of items.*

Swaps involving top positions, where NDCG is most sensitive, change the metric more, so those pairs receive larger updates than pairs deep in the list.

**Related:** [[ranknet|RankNet]] · [[ndcg|NDCG]] · ...
```

The image sits between the paragraph that introduces the gradient-scaling mechanism and the paragraph that explains its consequence — right where the diagram clarifies the surrounding text.

**Images and tables do not appear in the YAML frontmatter, in the description, in aliases, or in the Related footer** — only in the body prose, where they must serve this entity under [Body structure](writing.md#body-structure).

## Captions

Every image embed has a caption directly below it — **never omit it**, even when the surrounding prose already explains the figure. **Captions are brief and always italicized.** The same caption rule applies to recreated Markdown tables (see *Body Structure → Markdown tables*); a table's caption sits on the line immediately below the table, same format as an image caption.

Describe what the figure or table shows in standalone form — no source-relative figure/table numbers (`Figure 3`, `Table 2`), no source attribution (`from Burges (2010)`).

**Formatting — no wikilinks, no markdown formatting; LaTeX is allowed.** Wikilink syntax (`[[...]]`) and markdown formatting (`**bold**`, `*italic*`, backtick code) clutter the caption's role as a one-line self-description and conflict with the outer italic styling. LaTeX math is fine — `$\alpha$`, `$|\Delta\text{NDCG}|$`, `$O(n \log n)$` — when the caption refers to a quantity the figure or table depicts symbolically. Entity names that would be wikilinked in body prose stay bare in the caption; terms that would be emphasized with `**bold**` or `*italic*` in body prose stay plain in the caption (LaTeX symbols are the only inline markup allowed). Work titles and scientific taxon names that would be italicized in body prose also stay plain in captions — the no-formatting rule overrides typographic convention here, in the same trade-off as wikilink display labels (see the Limitation under Italic pattern 7).

**Style.** A one-line sentence wrapped in `*...*` (italic) **on the line immediately below the embed (or the table), with no blank line between them** — the embed-and-caption (or table-and-caption) form one visual unit, with blank lines above and below to separate the unit from surrounding prose. Example: `*The gradient is scaled by $|\Delta\text{NDCG}|$ — the NDCG change from swapping a pair of items.*`.
