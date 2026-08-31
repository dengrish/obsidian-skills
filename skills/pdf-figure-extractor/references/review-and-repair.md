# Reviewing and repairing figure extraction

Read this when the batch summary reports questionable crops, missing figures,
collisions, or ownership problems, or when a page needs manual cropping. The
[main workflow](../SKILL.md#workflow) owns scope, extraction, and the mandatory
verification gate. `<skill>` is the figure extractor's directory; use the
same interpreter and source identity as the original run.

For a specific problem, jump to [ownership records](#ownership-legacy-adoption-and-review-records),
[caption labels](#caption-labels-when-diagnosing-collisions), or
[manual cropping](#set-and-verify-a-manual-crop).

## Interpret the diagnostics

The summary distinguishes detection, successful writes, protected existing
files, and review findings. Do not merge these into one extraction count.

| Finding | What to inspect or do |
|---|---|
| Caption collisions | Compare the reported raw captions. The first caption wins when two labels normalize to one filename. Supplementary and Extended Data may need separate namespaces with `--ed-prefix ED`; other collisions need page inspection before choosing a repair. |
| Suspicious bboxes | Inspect the page and PNG. The four checks cover a very small crop, only a fraction of the expected figure region, intrusion into running heads/body prose, and caption overlap. A suspicious PNG may still have been written. |
| Caption text in crop | Re-crop before anything embeds it. Check all nearby captions, including the neighboring column's, not just the target figure's caption. |
| Caption position ambiguous | The detector has competing “beside” and “below” interpretations. “Contested” and “thin” describe different evidence; neither proves the crop is wrong. Compare both readings with the page. Margin-caption layouts commonly need this review. |
| Blank crops | Nothing was written. Render the caption's page and the next page; the figure may be overleaf. Crop the page where the figure actually appears. |
| Occupied filenames | An output is held by a file with unproven or conflicting ownership. This is neither a successful extraction nor a verified skip. Follow the ownership section below; `--overwrite` cannot resolve it. |
| PARTIAL detection | Body text cites figure labels for which no caption matched. Inspect the cited pages for missed captions, nonstandard layouts, or references to figures in another document. This signal is evidence of a possible miss, not proof. |
| Byte-identical duplicates | Under one stem, two labels may have received the same crop. Under different stems, check for duplicate documents or book/chapter representations. Inspect the sources; identical bytes alone do not authorize deletion. |
| Failed to write | Detection succeeded but a collapsed crop or rendering error prevented a PNG. Inspect the error and source page; use a valid manual crop when possible. |
| No figure captions detected | Check whether the PDF is figureless or uses a caption style the detector did not recognize. Do not promise a complete extraction without inspecting it. |
| No extractable text | Inspect the PDF; it may be a scan without OCR. Use available OCR on a scratch copy if appropriate, preserving the original and following runtime tool guidance. |
| Could not open or fully read PDF | Report the file and error. Corrupt downloads, HTML saved as PDF, or damaged pages need a valid source, not automatically OCR. Other PDFs continue and completed crops retain ownership records, but the run fails. |
| Zero pages | Report an empty PDF separately; OCR cannot supply missing pages. |
| Stem collisions | Neither colliding source is extracted or adopted, even with `--overwrite`. Use `pdf-organizer` to establish distinct source identities, then retry. |

A clean summary is still insufficient for multi-column papers: a bounding box
may include a neighboring picture without including its caption. Inspect the
actual figures. Review marks suppress geometry warnings, so mark only figures
that have been visually checked and repaired where necessary.

## Ownership, legacy adoption, and review records

`Sources/Images/` is shared with clipping images. The default sidecars in
`--out` have separate purposes:

- `.figure-manifest.tsv` records figure ownership and digests. A current
  matching record lets extraction skip or deliberately replace that output.
- `.figure-review.txt` records bounding boxes a person or agent has checked.
  A review mark is not an ownership claim or permission to overwrite.

Both batch and manual extraction protect unknown/conflicting occupied names,
including with `--overwrite`. A malformed, protected, or symlinked manifest
blocks before extraction or review marks are written. A late save failure
makes the run fail; resolve it before retrying, rather than deleting the
manifest to make output appear unowned. Completed crops retain their ownership
records when another PDF fails or an ordinary interruption ends the run.

When a manifest is absent, a batch migration adopts only complete PNGs keyed
to canonical, uniquely named PDFs in the requested source scope. It reports
what it adopted. Truncated images, other formats named `.png`, unrelated
clipping stems, and colliding PDF stems remain unclaimed and unchanged.
Readable figure PNGs can still participate in duplicate detection regardless
of ownership.

A manual crop may add a **new** file to a folder without a manifest, but may
not replace an occupied name there. Inspect legacy images and perform the
scoped batch migration before repairing an existing crop. When a manifest is
present, a manual repair updates its digest so a later batch recognizes the
repaired output.

`--review-file` selects a custom review ledger; keep using that same path
when adding marks. It does not relax image ownership. The organizer's rename
repair tracks the default sidecars only, so a custom review ledger must be
included explicitly in any later rename review. See
[conventions §8](../../../shared/CONVENTIONS.md#8-figure-naming-and-sourcesimages)
for the shared figure contract.

## Caption labels when diagnosing collisions

Keep the PDF's exact on-disk stem for every output. Dots and numeric en dashes
in figure labels normalize to ASCII hyphens; caption order never renumbers
the figures.

| Caption form | Output label |
|---|---|
| `Figure 1.2`, `Figure 1-2`, `Figure 1–2` | `1-2` |
| `Figure 1.2.4` | `1-2-4` |
| `Figure A.1`, `Figure A1` | `A-1`, `A1` |
| `Figure S1`, `Supplementary Figure 1`, `Suppl. Figure 1`, `Supp. Figure 1` | `S1` |
| `Figure SI1` | `SI1`, distinct from `S1` |
| `Extended Data Figure 1` | `S1` by default; `ED1` with `--ed-prefix ED` |
| `Figure 1: Title`, `Figure 1—Title`, `Figure 1–Title` | `1` |

Caption keywords are case-insensitive and include `Fig.` / `FIG.` forms.
An en dash **between digits** belongs to the label; before a letter it
separates the caption text. An em dash separates caption text, so
`Figure 1—2D convolution` is Figure 1, not Figure 1-2.

Body prose such as “Figure 1 shows…”, plural references, and lettered panel
pointers such as `Figure 1a` or `Figure S1A` are not whole-figure captions.
Existing letter-suffixed panel files remain valid; consumers prefer the
composite and do not count an unused historical panel as an unplaced whole
figure. This workflow creates whole figures only.

## Set and verify a manual crop

1. Inspect detections and coverage for the affected PDF. Pass the same
   `--ed-prefix` and `--keep-frame` used in the batch so labels and geometry
   agree. The table gives the figure bbox, caption rectangle, and raw label.

   ```bash
   python3 '<skill>/scripts/auto_fig_bbox.py' '<PDF path>' --coverage
   ```

2. Render the problem page into a unique scratch directory and view it.
   These tools use **one-based physical PDF page numbers**, not printed
   folios or the organizer's zero-based chapter indices.

   ```bash
   python3 '<skill>/scripts/render_page.py' '<PDF path>' 5 \
       --out '<scratch>' --dpi 72
   ```

   The render is in pixels; crop coordinates are PDF **points**, measured
   from the top-left. Multiply pixels by `72 / DPI`: at 72 DPI they are equal;
   at the default 100 DPI the factor is `0.72`. The renderer prints the
   conversion factor.

3. Set `PAGE:FIG_LABEL:x0,y0,x1,y1` in points. Use the exact filename stem,
   including `_src` and any disambiguator, and the source caption's label.
   The coordinates below illustrate the syntax; replace them with the
   measured crop for the actual page.

   ```bash
   python3 '<skill>/scripts/extract_figures.py' '<PDF path>' \
       --out '<vault>/Sources/Images' --stem '<pdf_stem>' \
       --crop '5:2:80,140,520,360' --overwrite
   ```

   `--overwrite` is needed to replace a verified crop; without it that crop
   is skipped. Unknown occupants remain protected. Keep `y1` above the
   caption's `y0` (for a bottom caption, `y1 = cap_y0 - 0.5` is a useful
   boundary). Avoid neighboring captions too. The manual tool warns on
   detected caption overlap; `--no-caption-check` only suppresses that
   diagnostic and does not permit captions in the delivered PNG.

4. View the resulting PNG and compare it with the source page. Only then
   record that the flag has been resolved, using the original source scope
   and output folder:

   ```bash
   python3 '<skill>/scripts/batch_extract.py' \
       --src '<original source scope>' --out '<vault>/Sources/Images' \
       --mark-reviewed '<pdf_stem>:2'
   ```

   This records the mark and continues a normal run; it is not a mark-only
   command. Include the same namespace/frame options and custom
   `--review-file`, if used. The summary prints a complete mark command for
   each flagged figure. With `--dry-run`, marks apply only to the preview
   and nothing is persisted.

For several bad crops, `auto_fig_bbox.py --emit extract --stem '<pdf_stem>'`
can print one manual-extraction command with multiple `--crop` arguments.
It includes the current interpreter and the script's absolute path. Supply
the PDF path and matching detection options; edit the emitted coordinates
and replace the deliberate `--out` placeholder
`/EDIT-THIS/path/to/vault/Sources/Images`. Add `--overwrite` only to replace
verified output. Collapsed rectangles are omitted and counted on stderr,
so an emitted command is not evidence that all figures have usable crops.
