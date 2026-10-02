# Reviewing and repairing figure extraction

Read this when the batch summary reports questionable crops, missing figures,
collisions, or ownership problems, or when a page needs an explicit crop. The
[main workflow](../SKILL.md#workflow) owns scope, extraction, and the
visual-review scope. `<skill>` is the figure extractor's directory; use the
same interpreter and source identity as the original run.

For a specific problem, jump to [ownership records](#ownership-legacy-adoption-and-review-records),
[Extended Data figures](#extended-data-and-supplementary-figures),
[caption labels](#caption-labels-when-diagnosing-collisions), or
[explicit cropping](#set-and-verify-an-explicit-crop).

## Interpret the diagnostics

The summary distinguishes detection, successful writes, protected existing
files, and review findings. Do not merge these into one extraction count.

| Finding | What to inspect or do |
|---|---|
| Caption collisions | The first caption wins when two labels normalize to one filename. Render both reported pages and follow the summary's printed next step; an Extended Data/Supplementary pair uses [Extended Data and Supplementary figures](#extended-data-and-supplementary-figures). A continuation's later pages are not extracted; report that limitation. If the kept crop is prose or another figure, set an explicit crop for the dropped caption's figure on its page before marking the label reviewed. |
| Suspicious bboxes | Inspect the page and PNG. Reasons include a very small crop, low coverage of the figure region or of the content the caption was read against, a running head or body prose inside the crop, and caption overlap. A suspicious PNG may still have been written. |
| Caption text in crop | Re-crop before anything embeds it. Check all nearby captions, including the neighboring column's, not just the target figure's caption. |
| Caption position ambiguous | The detector has competing “beside” and “below” interpretations. “Contested” and “thin” describe different evidence; neither proves the crop is wrong. Compare both readings with the page. Margin-caption layouts commonly need this review. |
| Blank crops | Nothing was written. Render the caption's page and the next page; the figure may be overleaf. Crop the page where the figure actually appears. |
| Occupied filenames | An output is held by a file with no matching ownership record: a legacy crop from an earlier extractor run, another producer's file, or a changed PNG. This is neither a successful extraction nor a verified skip. Follow the ownership section below; `--overwrite` cannot resolve it. |
| Cross-chapter references | In a canonically named split chapter, every detected numeric caption agrees with the filename's chapter number and exactly one canonical same-book sibling chapter contains the cited caption. Dot, en-dash, and em-dash label separators compare as the same identity. The batch keeps these references visible but does not call them missing local captions; absent, ambiguous, unreadable, changing, or nonmatching siblings remain PARTIAL. |
| PARTIAL detection | Body text cites figure labels for which no caption matched after the confident cross-chapter references above are separated. Inspect the cited pages for missed captions, nonstandard layouts, or other external references. This signal is evidence of a possible miss, not proof. |
| Byte-identical duplicates | Under one stem, two labels may have received the same crop; the summary explains an S<N>/ED<N> pair. Under different stems, check for duplicate documents or book/chapter representations. Inspect the sources; identical bytes alone do not authorize deletion. |
| Failed to write | Detection succeeded but a collapsed crop or rendering error prevented a PNG. Inspect the error and source page; use a valid explicit crop when possible. |
| No figure captions detected | Check whether the PDF is figureless or uses a caption style the detector did not recognize; for a missed style, see the labelling rule under [caption labels](#caption-labels-when-diagnosing-collisions). Do not promise a complete extraction without inspecting it. |
| No extractable text | Inspect the PDF; it may be a scan without OCR. Use available OCR on a [readable working copy](#readable-working-copies) if appropriate, following runtime tool guidance. |
| Could not open or fully read PDF (including encrypted) | Report the file and error. An encrypted PDF needs a [readable working copy](#readable-working-copies). Corrupt downloads, HTML saved as PDF, or damaged pages need a valid source, not automatically OCR. Other PDFs continue and completed crops retain ownership records, but the run fails. |
| Zero pages | Report an empty PDF separately; OCR cannot supply missing pages. |
| Stem collisions | Neither colliding source is extracted or adopted, even with `--overwrite`. A canonical `<vault>/Sources/Images/` output makes this a whole-vault PDF-basename check even when `--src` names one file or a smaller subtree; arbitrary external outputs use the explicit source scope. When another vault file shares the basename, report both paths and give the user the [shared-basename remedy](../../../shared/CONVENTIONS.md#shared-pdf-basenames). For two colliding sources outside the vault, give one a unique stem with `pdf-organize` run without `--vault`. |

The [visual-review scope defined in the main workflow](../SKILL.md#3-inspect-the-summary-and-verify-crops)
still applies when no diagnostic fires. Top-of-page side-caption exceptions
always remain flagged: compare the complete figure with the crop, especially
separated panels or stages, and set an explicit crop for missing content. A
top-page continuation caption may instead produce a degenerate detection that
needs explicit repair. These are agent verification steps, not mandatory human
reviews.

### Extended Data and Supplementary figures

Under the default prefix, Extended Data and Supplementary figures share
`_fig_S<N>`. To switch a PDF after a default run, run the rerun command the
summary prints: that PDF alone with `--ed-prefix ED --overwrite-supplementary`
and an `--unmark-reviewed` for each S label whose collision kept an Extended
Data caption. It replaces only unmarked `_fig_S<N>` crops, so other S marks
keep protecting Supplementary repairs. Compare every PNG it lists under
`wrote:` with its page. A `_fig_S<N>` that no Supplementary caption claims,
such as one reported as identical to `_fig_ED<N>`, is a leftover Extended Data
crop: report it as mislabelled and delete it only with authorization. Later
runs, folder sweeps included, keep `--ed-prefix ED` for a PDF whose manifest
records `_fig_ED<N>` crops or whose `Sources/Images/` holds an unrecorded
`<stem>_fig_ED<N>.png`; adopt such a legacy crop only after comparing it with
its page.

## Readable working copies

For an encrypted PDF, or a scan that needs OCR, make a readable copy under
the exact vault basename in a fresh child of the run's `<scratch>`, never
inside the vault, where it would duplicate the basename and block both. Point
the batch (`--src`) and any explicit repair (its PDF argument) at that copy,
with the canonical `--out`, leave the original unchanged, and remove the copy
once its crops are verified.

## Ownership, legacy adoption, and review records

`Sources/Images/` is shared with clipping images. The default sidecars in
`--out` have separate purposes:

- `.figure-manifest.tsv` records figure ownership and digests. A current
  matching record lets extraction skip or deliberately replace that output.
- `.figure-review.txt` records `<pdf_stem><TAB><label>` marks for crops that
  were checked. A mark is keyed to the label, not the bbox: it silences
  warnings for that existing verified crop and protects it from a later broad
  batch `--overwrite` until the mark is removed. A review mark is not an
  ownership claim or permission to overwrite; remove it deliberately with a
  batch run of that PDF and `--unmark-reviewed '<pdf_stem>:<label>'` before
  deleting the crop or asking automatic detection to replace it. Do not
  hand-edit the ledger: one malformed line blocks every later run.

A malformed, protected, or symlinked manifest blocks before extraction or
review marks are written. A late save failure makes the run fail; resolve it
before retrying, rather than deleting the manifest to make output appear
unowned. Completed crops retain their ownership records when another PDF fails
or an ordinary interruption ends the run.

The manifest verifies crop ownership and current PNG bytes, not the PDF revision
that produced them. If a PDF was deliberately replaced or revised at the same
path, an ordinary rerun can still skip its older crops, and review marks protect
those crops even from batch `--overwrite`. Compare the affected figures with
the revised source. Use [explicit cropping](#set-and-verify-an-explicit-crop)
with `--overwrite` for a targeted refresh, then inspect the new PNGs; that
command deliberately replaces verified crops even when they have review marks.
For a chosen automatic refresh, run batch `--overwrite` with `--src` set to
the revised PDF and one `--unmark-reviewed` per affected reviewed figure, then
review its outputs again. A verified skip alone does not establish that
figures reflect a replaced PDF.

For both extraction commands, occupancy is semantic and portable, including
with `--overwrite`: every inventoried `<stem>_fig_<label>.*` spelling shares
one slot after case folding and Unicode normalization. Thus a clipping-owned
`.jpg` or `.webp`, a differently cased `.PNG`, or a normalization alias blocks
the new PDF crop even if the canonical `.png` path itself is absent. The sole
pass-through is the exact regular PNG pathname, which still needs a matching
manifest digest before it can be skipped or replaced. The refusal preserves
every occupant and reports its stored name. A conflicting different figure
slot does not block a named crop; an incomplete inventory still blocks because
the requested slot cannot be proved free.

The helpers apply the shared [safe-write protocol](../../../shared/SAFE_WRITES.md)
to crops and sidecars: new names are exclusive, and replacements require the
inspected file to remain unchanged. Crops also pass nonblank read-back before
publication. On a concurrent-write or restoration failure, preserve the named
staging/recovery directory and inspect both occupants before retrying; do not
replace a newer file or discard displaced bytes to force success.

The default batch treats every occupied name without an ownership record as
unclaimed. A matching canonical stem is not provenance: a URL-origin clipping
can have the same stem and exact figure filename. After inspecting a confirmed
historical extractor crop, select that exact file with a repeatable
`--adopt-legacy '<pdf_stem>:<figure_label>'` option. The summary prints one
such command per PDF for its unrecorded exact PNGs; drop every slot you have
not compared with its page. Adoption is limited to complete PNGs for eligible,
uniquely identified PDFs in this run and is revalidated before the sidecar is
saved. A missing, changed, truncated, symlinked, ambiguous, or differently
formatted file is left unchanged and unclaimed. A manifest may already exist,
but the selected slot must not already have an ownership record. Adoption
cannot be combined with `--overwrite`; migrate ownership first, then run any
requested re-extraction separately. Readable figure PNGs still participate in
duplicate detection independently of ownership.

A recorded crop whose bytes changed after extraction (an image optimizer or
a hand edit) is never skipped, replaced or adopted; report it. With the
user's authorization, either remove the changed PNG and rerun that PDF, or
delete its manifest line and adopt it after comparing it with its page.
Change the manifest only as a guarded vault edit: record it with
`<plugin>/shared/scripts/publish_files.py snapshot`, delete just that line in
a `<scratch>` draft (keep the TAB separators), and `publish` the draft against
that record.

A new explicit crop records its digest, creating the manifest when necessary.
Inspect legacy images and explicitly adopt each confirmed `STEM:FIG` before
repairing an existing crop. An explicit repair of a recorded crop updates its
digest so a later batch recognizes the repaired output.

Keep the default review ledger for canonical `Sources/Images/` output; if a
custom `--review-file` is used, repeat it whenever adding or removing marks.
It does not relax image ownership, and the organizer's rename never updates
it: re-mark renamed figures in a normal run with that ledger. See
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
| `Supplementary Figure A1`, `Extended Data Figure A1` | `SA1`; the Extended Data form is `EDA1` with `--ed-prefix ED` |
| `Extended Data Figure S1` | `S1` by default; `EDS1` with `--ed-prefix ED` |
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

A captioned figure the detector missed, such as `Abbildung 3`, or `Exhibit 2`
in a document with no other numbered figure series, may be cropped explicitly
under its printed number (`3`, `2`). Never label by page or extraction order,
invent a prefix, or reuse a number another series in the PDF uses; leave an
unnumbered or colliding exhibit unextracted and report it.

## Set and verify an explicit crop

1. Inspect detections and coverage for the affected PDF. Pass the same
   `--ed-prefix` and `--keep-frame` used in the batch so labels and geometry
   agree. The table gives each figure's output label (`Fig`), bbox, caption
   rectangle, and raw caption label.

   ```bash
   python3 '<skill>/scripts/auto_fig_bbox.py' '<PDF path>' --coverage
   ```

2. Render the problem page into a fresh child of the active run's `<scratch>`
   directory and view it.
   These tools use **one-based physical PDF page numbers**, not printed
   folios or the organizer's zero-based chapter indices. The renderer refuses
   the complete requested page set when any preview name is already occupied;
   choose another fresh child of `<scratch>` rather than deleting or replacing an
   unknown occupant.

   ```bash
   python3 '<skill>/scripts/render_page.py' '<PDF path>' 5 \
       --out '<scratch>/page-preview-<unique-id>' --dpi 72
   ```

   Pass several pages comma-separated (`10,11,13`). The render is in pixels;
   crop coordinates are PDF **points**, measured
   from the top-left. Multiply pixels by `72 / DPI`: at 72 DPI they are equal;
   at the default 100 DPI the factor is `0.72`. The renderer prints the
   conversion factor. An edge judged by eye can miss by tens of points; when
   it sits near text, take the caption's and neighboring text's positions
   from PyMuPDF's `page.get_text("words")`.

3. Set `PAGE:FIG_LABEL:x0,y0,x1,y1` in points, using the output label from
   step 1's `Fig` column or the
   [caption-label table](#caption-labels-when-diagnosing-collisions) (`S1`,
   not the printed `1`, for `Supplementary Figure 1`); output names follow
   the PDF's exact on-disk stem. The coordinates below illustrate the syntax;
   replace them with the measured crop for the actual page.

   ```bash
   python3 '<skill>/scripts/extract_figures.py' '<PDF path>' \
       --out '<vault>/Sources/Images' \
       --crop '5:2:80,140,520,360' --overwrite
   ```

   Pass the batch's non-default `--dpi` too, so the repair renders like its
   siblings; this command takes no `--keep-frame`, because the coordinates
   define the crop. With canonical output, this command applies the same whole-vault basename
   gate and remedies as `batch_extract.py` before it reads the ownership
   sidecar or writes a crop. For an encrypted source,
   use a [readable working copy](#readable-working-copies). Arbitrary external
   output remains a one-off and does not imply a vault scan.

   If intake deliberately used `--allow-unorganized`, repeat that flag on
   this explicit command and the review-mark command below. This includes a
   named collector-owned PDF attachment whose filename must remain unchanged.
   The exception changes only the naming gate; duplicate vault basenames and
   unknown or changed image occupants remain blocked.

   `--overwrite` is needed to replace a verified crop; without it that crop
   is skipped. Unknown occupants remain protected. Keep every caption
   rectangle out of the crop, including neighbors' captions from the coverage
   table and any caption the detector missed. For a caption below the figure
   use `y1 <= cap_y0 - 0.5`; for one above it, `y0 >= cap_y1 + 0.5`. For a
   caption beside the figure, keep the crop's x-range clear of the caption;
   the figure may extend above and below the caption band. The explicit crop
   tool warns on detected caption overlap; `--no-caption-check` only
   suppresses that diagnostic and does not permit captions in the delivered
   PNG.

4. View the resulting PNG and compare it with the source page. Only then
   record the review, including for a repair of a crop that was never
   flagged, with that PDF as `--src` and the same output folder. Pass one
   `--mark-reviewed` per checked figure of that PDF in one run:

   ```bash
   python3 '<skill>/scripts/batch_extract.py' \
       --src '<PDF path>' --out '<vault>/Sources/Images' \
       --mark-reviewed '<pdf_stem>:2'
   ```

   This records the mark and continues a normal run; it is not a mark-only
   command. Include the same namespace/frame options and custom
   `--review-file`, if used. The summary prints a complete command for one
   flagged figure, preserving the run's namespace, ledger, rendering and
   naming-exception options; for an unflagged repair, use the same command
   with the repaired label. It omits `--overwrite` so recording a review
   preserves an explicit crop repair.
   With `--dry-run`, marks apply only to the preview and nothing is persisted.

   After the crop and review record are verified, remove the scratch page
   previews. Preserve any staging or recovery directory named by a failed
   publication until the failure has been reconciled.

For several bad crops, `auto_fig_bbox.py --emit extract` can print one
explicit-extraction command with multiple `--crop` arguments. It includes the
current interpreter and the script's absolute path. Supply the PDF path and
matching detection options; edit the emitted coordinates and replace the
deliberate `--out` placeholder `/EDIT-THIS/path/to/vault/Sources/Images`.
The command covers every detected figure: delete the `--crop` lines for
figures you are not repairing, and add `--overwrite` only to replace verified
output (it also replaces reviewed crops). Repeat any `--allow-unorganized`
used at intake. Collapsed rectangles are
omitted and counted on stderr, so an emitted command is not evidence that all
figures have usable crops.
