# Images, tables and captions

Scope: source figures, recreated tables and captions. Report a source with no figures as such; never guess at images.

## Images

**Inventory every source figure before selecting:** the source's figure references and every matching local file and Markdown image reference, never only the images you expect to use.

Use [step 1](../SKILL.md#1-read-the-source)'s inventory command, never a recursive shell glob: it matches every case, extension and separator variant of the `<resolved_source_stem>_fig` prefix and returns direct regular files in `candidates`. `Sources/Images/` is flat: symlinks, nonregular occupants, portable-equivalent names and nested matches are `blocked_matches` that make the inventory unsafe, staging residue is reported but never consumed, and an unreadable directory leaves absence unproved. Read the complete JSON and resolve or report its findings; an empty partial result never means "this source has no figures."

- **PDF source.** Figures come from `figure-extract`, named `[pdf_stem]_fig_<N>.png` by the source's figure number ([CONVENTIONS §8](../../../shared/CONVENTIONS.md#8-figure-naming-and-sourcesimages)). **A source figure with no extracted file stays in the inventory as unavailable**, never fabricated or denied: when the inventory is empty, first [prepare missing PDF figures](#missing-pdf-figures), and report an unavailable figure that would materially help.
- **Markdown source.** Image references live in the note and resolve directly, even under an older filename prefix; a rendered one is never called unavailable or renamed. Downloads follow [§8](../../../shared/CONVENTIONS.md#8-figure-naming-and-sourcesimages). A failed download leaves `<!-- image download failed: … -->` in place: inventory it as an unavailable figure with that reason, and never copy the comment or its orphaned caption into an entry. An older note's remote `![alt](https://…)` image is inventoried from the text and reused in Markdown form, never rewritten as a wikilink, which would lose the URL.

**A figure and its panels are one exhibit, and the composite is the default.** A label ending in a lowercase letter (`…_fig_3a.png` beside `…_fig_3.png`) is a panel ([§8b](../../../shared/CONVENTIONS.md#8b-the-producer-conventions)): listed in `candidates`, but not a separate exhibit for selection or reporting. Use a panel only when the entry's subject is that panel's alone, and never beside its own figure; placing either discharges the other. Preserve existing filenames and panel identity.

### Missing PDF figures

When a PDF source shows or refers to figures but its complete, safe step-1
inventory has no `candidates`, an apply run extracts that PDF alone, once,
after the parser check passes and before selecting exhibits:

```bash
python3 '<plugin>/skills/figure-extract/scripts/batch_extract.py' \
    --src '<resolved pdf path>' --out '<images-folder>'
```

Carry any non-default option intake or an earlier extraction report names
(`--allow-unorganized`) into this and every repair command. Pass
`--ed-prefix ED` when captions number Extended Data figures separately. Respect the extractor's refusals and read its diagnostics.

Then complete figure-extract's
[visual review](../../figure-extract/SKILL.md#3-inspect-the-summary-and-verify-crops)
of the crops this run wrote. A named-entity run may view only the crops it
considers and report the rest as not visually verified. Repair only those crops, through its explicit-crop
workflow, and re-run the inventory after extraction and each repair.
Never overwrite, adopt or repair a pre-existing image; the image folder is
otherwise read-only. A preview/no-apply run writes nothing and reports the gap.

## Selection

**Include a figure only when it clarifies the entry's own definition, mechanism or an essential distinction better than concise prose**; appearing in the source is not enough.

**Most focused entries need zero or one figure.** A second figure earns its place when it shows a different facet the prose explains, such as a mechanism diagram plus the key quantitative plot (PCA's cumulative explained-variance elbow); an applications gallery never does. For an existing entry, use the [merge preservation rule](merge.md#exhibits-and-headings); this preference never authorizes silently removing its current images.

**Pair each selected figure with the most specific eligible entry it explains** (`lambdarank.md`, not `learning-to-rank.md`, for a gradient-scaling diagram); with none of the right scope, skip it. A figure never bypasses step 2's eligibility rules.

**Open each newly selected local image before embedding it.** Skip and report a wrong, unreadable or badly cropped one (caption text, neighboring charts), or repair a crop this run extracted; a host that cannot display images embeds no unviewed crop and says so. Preserved embeds and remote images need no new check.

**Give every unused exhibit a specific reason**, never an image limit; exhibits sharing a reason are grouped (`5-3, 5-6, 5-9: teach entities not requested`). Reconcile the whole inventory against embeds and reasons. An exhibit without a reason needs a decision, not automatic placement; many unused figures are fine. Valid reasons:

- No explanatory benefit: decorative, or prose is as clear.
- Redundant with a retained figure, named with the aspect it covers.
- Outside the entry's scope: an unnecessary application, example or implementation detail.
- No eligible entry: deferred or rejected under step 2, or outside the requested scope.
- Recreated as a Markdown [table](#tables).
- Unavailable or unusable asset: name the source figure and the limitation.

## Tables

When the source presents data as a table and that form genuinely serves the entry (a method comparison or parameter table), **recreate it in Markdown**; tables are never pre-extracted or **embedded as images**. **Recreate, don't transcribe:** drop rows and columns that do not earn their place, rename headers to the entry's terminology, and simplify cells, but **the cells that survive keep the source's values**: they are the table's content, not examples to abstract. Only source-presented tabular material qualifies, never a worked example's intermediate steps or other content the source does not tabulate. Cells allow LaTeX and Markdown formatting, with backticks only where [inline code](writing.md#body-structure) allows them, but no wikilinks. A table sits inline beside the prose it illustrates, with an italic caption on the line immediately below it.

## Placement and embed syntax

**Embed syntax.** Embed a `Sources/Images/` image as `![[Burges_LearningToRank_2010_fig_3.png]]` and a remote image from a Markdown source as `![alt](https://...)`, whose `alt` is plain alt-text, not the [caption](#captions).

**Place each exhibit on the line immediately after the sentence or paragraph it illustrates**: never above the opening definition, and never detached at the end of the body before the Related footer. Never group exhibits as a gallery: each sits beside its own motivating paragraph, which must earn its place without it, and one paragraph supports at most one exhibit; when two compete, choose the more helpful form rather than stack them or write prose to create slots. **Images and tables appear only in body prose**, never in the frontmatter, description, aliases or Related footer.

## Captions

Every image embed and every recreated [table](#tables) has a caption directly below it, in the same format — **never omit it**, even when the prose already explains the exhibit.

Describe what the exhibit shows, checked against the source, in standalone form, without source figure or table numbers (`Figure 3`) or attribution (`from Burges (2010)`). **No wikilinks and no Markdown formatting; LaTeX is allowed** for a quantity the exhibit depicts (`$|\Delta\text{NDCG}|$`). Entity names, Work titles and scientific names stay plain, as in display labels.

**Style.** A one-line sentence wrapped in `*...*` (italic) **on the line immediately below the embed (or the table), with no blank line between them** — the embed-and-caption (or table-and-caption) form one visual unit, with blank lines above and below to separate the unit from surrounding prose. Example: `*The gradient is scaled by $|\Delta\text{NDCG}|$ — the NDCG change from swapping a pair of items.*`.
