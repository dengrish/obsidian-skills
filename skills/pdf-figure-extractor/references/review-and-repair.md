# Reviewing and repairing figure extraction

Read this when the batch summary reports questionable crops, missing figures,
collisions, or ownership problems, or when a page needs an explicit crop. The
[main workflow](../SKILL.md#workflow) owns scope, extraction, and the mandatory
verification gate. `<skill>` is the figure extractor's directory; use the
same interpreter and source identity as the original run.

For a specific problem, jump to [ownership records](#ownership-legacy-adoption-and-review-records),
[caption labels](#caption-labels-when-diagnosing-collisions), or
[explicit cropping](#set-and-verify-an-explicit-crop).

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
| Cross-chapter references | In a canonically named split chapter, every detected numeric caption agrees with the filename's chapter number and exactly one canonical same-book sibling chapter contains the cited caption. Dot, en-dash, and em-dash label separators compare as the same identity. The batch keeps these references visible but does not call them missing local captions; absent, ambiguous, unreadable, changing, or nonmatching siblings remain PARTIAL. |
| PARTIAL detection | Body text cites figure labels for which no caption matched after the confident cross-chapter references above are separated. Inspect the cited pages for missed captions, nonstandard layouts, or other external references. This signal is evidence of a possible miss, not proof. |
| Byte-identical duplicates | Under one stem, two labels may have received the same crop. Under different stems, check for duplicate documents or book/chapter representations. Inspect the sources; identical bytes alone do not authorize deletion. |
| Failed to write | Detection succeeded but a collapsed crop or rendering error prevented a PNG. Inspect the error and source page; use a valid explicit crop when possible. |
| No figure captions detected | Check whether the PDF is figureless or uses a caption style the detector did not recognize. Do not promise a complete extraction without inspecting it. |
| No extractable text | Inspect the PDF; it may be a scan without OCR. Use available OCR on a scratch copy if appropriate, preserving the original and following runtime tool guidance. |
| Could not open or fully read PDF | Report the file and error. Corrupt downloads, HTML saved as PDF, or damaged pages need a valid source, not automatically OCR. Other PDFs continue and completed crops retain ownership records, but the run fails. |
| Zero pages | Report an empty PDF separately; OCR cannot supply missing pages. |
| Stem collisions | Neither colliding source is extracted or adopted, even with `--overwrite`. A canonical `<vault>/Sources/Images/` output makes this a whole-vault PDF-basename check even when `--src` names one file or a smaller subtree; arbitrary external outputs use the explicit source scope. Use `pdf-organizer` to establish distinct source identities, then retry. |

A clean summary is still insufficient for multi-column papers: a bounding box
may include a neighboring picture without including its caption. Inspect the
actual figures. Review marks suppress geometry warnings, so mark only figures
that have been visually checked and repaired where necessary.

The automatic side-caption detector has one conservative top-of-page
exception. A wide caption can be read as sitting beside its figure only when
strong, isolated drawing content fills the opposite side of its vertical band
and there is no drawing above the caption supporting the usual below-figure
layout. Several separated vector parts may jointly supply that anchor. The crop
then grows through nearby drawing stages and explanatory text confined to the
anchor-selected column; it does not bridge a larger blank gap to a later
figure. Every crop produced through this exception remains flagged: inspect it
against the source page and set an explicit crop if a separated panel or stage
is missing. This is an agent verification step, not a mandatory human review.
A top-page continuation caption without the initial side evidence remains a
failed, degenerate detection for explicit repair.

## Ownership, legacy adoption, and review records

`Sources/Images/` is shared with clipping images. The default sidecars in
`--out` have separate purposes:

- `.figure-manifest.tsv` records figure ownership and digests. A current
  matching record lets extraction skip or deliberately replace that output.
- `.figure-review.txt` records bounding boxes a person or agent has checked.
  A review mark is not an ownership claim or permission to overwrite. It also
  protects the checked crop from a later broad batch `--overwrite`; remove the
  exact ledger row deliberately before asking automatic detection to replace it.

Both batch and explicit-coordinate extraction protect unknown/conflicting occupied names,
including with `--overwrite`. A malformed, protected, or symlinked manifest
blocks before extraction or review marks are written. A late save failure
makes the run fail; resolve it before retrying, rather than deleting the
manifest to make output appear unowned. Completed crops retain their ownership
records when another PDF fails or an ordinary interruption ends the run.

For batch extraction, occupancy is semantic and portable: every inventoried
`<stem>_fig_<label>.*` spelling shares one slot after case folding and Unicode
normalization. Thus a clipping-owned `.jpg` or `.webp`, a differently cased
`.PNG`, or a normalization alias blocks the new PDF crop even if the canonical
`.png` path itself is absent. The sole pass-through is the exact regular PNG
pathname, which still needs a matching manifest digest before it can be skipped
or replaced. The refusal preserves every occupant and reports its stored name.

Crop bytes are staged outside the flat image folder and must pass nonblank
read-back before publication. A new name is created exclusively, so a file
that arrives after preflight is preserved. `--overwrite` carries the verified
digest into publication, displaces and rechecks that exact occupant, and never
replaces blindly over the live name. If two other writers race for one name and
the displaced file cannot be restored there, the refusal reports the hidden
sibling recovery directory that preserves it; inspect both occupants before
moving anything or retrying.

The manifest and review ledger use the same fail-closed publication rule. A
missing sidecar is created exclusively. An existing sidecar is replaced only
while its identity, permissions, and exact bytes still match the version the
caller parsed; a concurrent mark or ownership update is retained and the stale
write fails. If restoration is blocked by another writer, the error names the
outside-Images recovery directory holding the displaced bytes.

The default batch treats every occupied name without an ownership record as
unclaimed. A matching canonical stem is not provenance: a URL-origin clipping
can have the same stem and exact figure filename. After inspecting a confirmed
historical extractor crop, select that exact file with a repeatable
`--adopt-legacy '<pdf_stem>:<figure_label>'` option. Adoption is limited to
complete PNGs for eligible, uniquely identified PDFs in this run and is
revalidated before the sidecar is saved. A missing, changed, truncated,
symlinked, ambiguous, or differently formatted file is left unchanged and
unclaimed. A manifest may already exist, but the selected slot must not already
have an ownership record. Adoption cannot be combined with `--overwrite`;
migrate ownership first, then run any requested re-extraction separately.
Readable figure PNGs still participate in duplicate detection independently of
ownership.

A new explicit crop records its digest, creating the manifest when necessary,
but may not replace an occupied unrecorded name. Inspect legacy images and
explicitly adopt each confirmed `STEM:FIG` before repairing an existing crop.
An explicit repair of a recorded crop updates its digest so a later batch
recognizes the repaired output.

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

## Set and verify an explicit crop

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

   Use the resolved source PDF's exact on-disk stem. Before it reads the
   ownership sidecar or writes a crop, this direct command inventories portable
   PDF basenames across the whole vault just like `batch_extract.py`. An
   unreadable subtree or a second case/NFC-equivalent basename blocks the
   repair; organize the conflicting PDF name and retry. A readable scratch
   representation of an encrypted PDF may sit outside the vault only when one
   vault PDF uniquely owns that basename. Arbitrary external output remains a
   one-off and does not imply a vault scan.

   `--overwrite` is needed to replace a verified crop; without it that crop
   is skipped. Unknown occupants remain protected. Keep `y1` above the
   caption's `y0` (for a bottom caption, `y1 = cap_y0 - 0.5` is a useful
   boundary). Avoid neighboring captions too. The explicit crop tool warns on
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
   `--review-file`, if used. The summary prints a complete command for one
   flagged figure, preserving the run's namespace, ledger, rendering and
   source-selection options. Its absolute paths stay tied to the original
   source, output and ledger when run from another working directory. It
   omits `--overwrite` so recording a review preserves an explicit crop repair.
   With `--dry-run`, marks apply only to the preview and nothing is persisted.

For several bad crops, `auto_fig_bbox.py --emit extract --stem '<pdf_stem>'`
can print one explicit-extraction command with multiple `--crop` arguments.
It includes the current interpreter and the script's absolute path. Supply
the PDF path and matching detection options; edit the emitted coordinates
and replace the deliberate `--out` placeholder
`/EDIT-THIS/path/to/vault/Sources/Images`. Add `--overwrite` only to replace
verified output. Collapsed rectangles are omitted and counted on stderr,
so an emitted command is not evidence that all figures have usable crops.
