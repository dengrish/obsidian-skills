"""Auto-detect figure bounding boxes from a PDF.

For each Figure caption (text block starting with "Figure N.M"), computes the
smallest rect containing all vector drawings + raster images in the page region
above (or beside) the caption, with padding for axis labels and panel labels.

This replaces the older workflow of guessing crop coordinates from text-block
gaps — that approach systematically clips axis labels and figure content that
extends past the body text width.

Side captions are detected symmetrically: a narrow caption block can sit
either to the LEFT of its figure (figure body on the right) or to the RIGHT
of its figure (figure body on the left).

A caption is found wherever it starts, not only at the top of a text block.
PyMuPDF merges a caption into one block with whatever sits just above it —
an axis label, a page-number strip, the tail of a paragraph — often enough
that anchoring the search at offset 0 loses figures silently (a 4-figure
paper yielded 3). The caption's own rect is then the lines from the caption
line down, so the merged text above it stays inside the crop where it
belongs.

Suspicious bboxes are flagged with a "# WARN: ..." line on stderr before
extraction. Examples include an implausibly small crop or one covering only
a fraction of the expected figure region. Review the reported reason and
compare the crop with the PDF; absence of a warning does not prove completeness.

`--coverage` compares the captions found against the figure numbers the body
text refers to, so a partial detection (3 captions found, 4 figures cited)
is visible instead of looking exactly like a complete one.

Captures: figure labels in the forms "N", "N.M", "N.M.K", "A.N", "AN", with
"." , "-" or an EN DASH separating the parts (a typeset book prints
"Figure 1-14" with the dash; see `LABEL_SEP`). Labels are normalized to ASCII
before they become filenames.
Panel-letter references in prose ("Figure 10.5a", "Figure 10.5a–b") are
deliberately NOT matched — those are body-text pointers to a specific
panel, not the start of a caption, so the whole match fails rather than
capturing a prefix.

This file is the ONE caption detector and bbox computer in this plugin. It
was duplicated into a second skill once, both writing into the same vault
`Sources/Images/` folder under the same filename convention
(`[pdf_stem]_fig_<N>.png`); the copies drifted, and the same PDF run through
both then yielded two different images competing for one filename — whichever
ran last won, silently. Do not vendor a second copy — call this one.

Usage:
    python3 auto_fig_bbox.py input.pdf
    python3 auto_fig_bbox.py input.pdf --pages 3,4,5
    python3 auto_fig_bbox.py input.pdf --emit extract --stem MyBook_Ch12
    python3 auto_fig_bbox.py input.pdf --keep-frame --ed-prefix ED
    python3 auto_fig_bbox.py input.pdf --coverage

    # The adversarial fixtures this module is held to.
    python3 auto_fig_bbox.py --test
"""
import argparse
import os
import re
import shlex
import sys

try:
    # `import pymupdf` is the modern spelling. The legacy `import fitz`
    # alias prints a deprecation notice **on stdout** in PyMuPDF >= 1.25,
    # which corrupts `auto_fig_bbox.py --emit extract` (its output is meant
    # to be a runnable shell command) — and the alias is slated for removal
    # outright. Fall back to it only for PyMuPDF older than 1.24.3, which
    # predates the `pymupdf` module name.
    import pymupdf as fitz
except ImportError:
    try:
        import fitz  # PyMuPDF < 1.24.3
    except ImportError:
        sys.exit(
            "PyMuPDF required. Use a Python environment with the plugin\n"
            "dependencies installed; see shared/RUNTIME.md. Install into a\n"
            "virtual environment, not the system Python."
        )

# Captures the figure label in any of these forms:
#   Figure 7              → "7"        (single-number figures, common in papers)
#   Figure 10.5           → "10.5"     (chapter.figure, dot-separated — Prince UDL, most math/CS books)
#   Figure 1-5            → "1-5"      (chapter-figure, dash-separated — Géron Hands-On ML, many O'Reilly titles)
#   Figure 10.5.3         → "10.5.3"   (three-part, rare but valid)
#   Figure A.1            → "A.1"      (appendix figures with a letter prefix)
#   Figure A1             → "A1"       (compact appendix form)
#   Figure S1             → "S1"       (supplementary figure — S prefix on the number itself)
#   Figure S2-3           → "S2-3"     (supplementary, chapter-figure)
#   Figure SI1            → "SI1"      (Supporting Information — Nature/ACS style, distinct from S)
#   Supplementary Figure 1 → "S1"      (supplementary marker BEFORE Figure — S is prepended)
#   Suppl. Figure 1        → "S1"      (alternate abbreviation)
#   Supp. Figure 1         → "S1"      (alternate abbreviation)
#   Supplementary Fig. 1   → "S1"      (compact "Fig." spelling)
#   Extended Data Figure 1 → "S1"      (Nature-style; folded into S by default, configurable)
#
# Case insensitivity: the "Figure" / "Fig." keyword and the supplementary
# marker word are matched case-insensitively, so "FIGURE 1", "figure 1",
# "Fig. 1", "SUPPLEMENTARY Figure 1", and "supplementary figure 1" all
# match. The figure number itself is case-sensitive — "S" and "SI" prefixes
# must be uppercase, since lowercase variants almost always mean prose ("as
# shown in figure s1 above"). The `(?![.-]\d)\b` panel-letter check still
# rejects "Figure 1A" / "Figure 1a" regardless of the keyword's case.
#
# Caption continuation: the lookahead recognizes five caption "shapes"
# after the figure number — period+space ("Figure 1. Title"), whitespace
# then a non-lowercase char ("Figure 1 Title", "Figure 1 1D conv"), end of
# line ("Figure 1"), colon ("Figure 1: Title" — common in Nature, Cell,
# PNAS), and an em-/en-dash with or without surrounding whitespace
# ("Figure 1—Title", "Figure 1 — Title"). Prose references like "Figure 1
# shows..." still fail because the verb after the number starts with a
# lowercase letter.
#
# A single label can mix dots and dashes (`1-5.3`) and the regex still
# captures the whole thing — `[.-]\d+` covers either separator at each step.
# `extract_figures.py` normalizes `.` to `-` for the filename suffix, so
# `Figure 1.5` and `Figure 1-5` both end up as `_fig_1-5.png`.
#
# The marker word (when present) is captured in group(1). `find_caption_blocks`
# looks up its normalized form in `MARKER_TO_PREFIX` and prepends the result
# to the figure number unless one is already there. The default mapping sends
# every marker to "S"; `batch_extract.py --ed-prefix ED` reconfigures
# "Extended Data" → "ED" for users whose papers have both supplementary AND
# Extended Data figures (common in Nature) that need to stay distinct.
#
# Panel references in prose ("Figure 10.5a", "Figure 10.5a–b", "Figure 1-5a")
# are intentionally NOT matched — those are body-text references to a
# specific panel, not the start of a figure caption. The `(?![.-]\d)\b` tail
# prevents the regex from backtracking and matching a prefix (e.g., "10"
# instead of "10.5" when followed by "a"); the trailing word boundary then
# also rules out a panel letter directly after the digit run.
#: The characters that may separate the parts of ONE figure label, as a regex
#: character class. ASCII `.` and `-` are the long-standing pair; U+2013 EN
#: DASH is here because a typeset book prints its chapter-figure labels with
#: one — Alberts, *Essential Cell Biology* numbers every figure `Figure 1–14`,
#: and so do most Norton/Pearson science texts.
#:
#: Before it was admitted, the en dash was matched only by the caption-shape
#: lookahead below, which reads a trailing dash as the punctuation before a
#: caption title (`Figure 1—Title`). Both readings are live and the regex
#: took the wrong one: `Figure 1–14 Cells come in…` matched label `1`, title
#: `14 Cells come in…`. That is not a near miss — EVERY caption in such a book
#: normalizes to `_fig_1`, so 42 of 43 figures were dropped as filename
#: collisions and the run reported two extractions and a wall of collisions.
#:
#: The two readings stay separable because a label separator is followed by a
#: DIGIT and a title dash is not (`Figure 1–Title`, `Figure 1 — Title`). EM
#: DASH is deliberately NOT in this class: no publisher numbers with one, and
#: leaving it out keeps `Figure 1—2D convolution` reading as a title.
LABEL_SEP = r'[.\-–]'

CAP_RE = re.compile(
    r'^\s*'
    r'((?i:Supplementary|Suppl?\.|Extended\s+Data))?\s*'   # group 1: optional marker
    r'(?i:Figure|Fig\.?)\s+'                                # Figure | Fig. | Fig (any case)
    r'(SI\d+(?:' + LABEL_SEP + r'\d+)*'                     # SI1, SI2-3 (Supporting Info)
    r'|S\d+(?:' + LABEL_SEP + r'\d+)*'                      # S1, S2-3, S1.2 (S-prefixed)
    r'|[A-Z]' + LABEL_SEP + r'?\d+(?:' + LABEL_SEP + r'\d+)*'   # A.1, A1, B-2 (appendix)
    r'|\d+(?:' + LABEL_SEP + r'\d+)*)'                      # plain numeric — group 2
    r'(?!' + LABEL_SEP + r'\d)\b'                           # not a truncated number
    r'(?=\.\s|\s+[^\sa-z]|\s*$|\s*:|\s*[–—])',              # caption-shape lookahead
    re.MULTILINE,
)
# The final lookahead distinguishes captions from prose references that
# happen to start with the same phrase. Real captions look like:
#   "Figure 1-23. Overfitting the training data"        (Géron — period+space)
#   "Figure 10.1 Invariance and equivariance"           (UDL — space+Capital)
#   "Figure 10.2 1D convolution with kernel size three" (UDL — space+digit, math caption)
#   "Figure 10.14 1×1 convolution. To change..."        (UDL — space+digit)
#   "Figure 1-23"                                       (label-only, end of line)
#   "Figure 1: Title goes here"                         (Nature/Cell/PNAS — colon)
#   "Figure 1—Title goes here"                          (some technical publishers — em-dash)
# Prose paragraphs that start with a figure reference look like:
#   "Figure 1-23 shows an example of..."                (verb after space)
#   "Figure 1-24 illustrates the gradient..."           (verb after space)
# The verb in a prose reference always starts with a LOWERCASE letter, so
# `\s+[^\sa-z]` (whitespace then a non-whitespace, non-lowercase character —
# digits, capitals, parentheses, math symbols — all OK) rejects prose
# references while accepting digit-led math captions. The `\s*:` and
# `\s*[–—]` alternatives add support for Nature-style colon captions and
# em-/en-dash captions; neither appears at the start of a prose reference.
# Excluding whitespace in the final class prevents backtracking from reading
# a second space in "Figure 1  shows..." as the start of a caption title.
# `header_y()` / `footer_y()` are loose page-margin bounds used to (a) discard
# the very top/bottom strip from text-block analysis and (b) seed the figure
# search region. They are intentionally small/large enough that any real
# running header or page-number row passes through to `collect_text_rects`
# — the `bbox_for_figure` code then raises `top` to just below the actual
# preceding prose/header block. Setting the header bound too aggressive (e.g.
# 125) clips real figure content on books whose pages are shorter than US
# Letter (Géron Hands-On ML pages are 504×661.5 pts and have body content
# starting at y~50).
#
# Both are PER PAGE and RELATIVE, because the bottom one has to be. It was an
# absolute `FOOTER_Y = 760`, tuned for US Letter (792pt) and applied to every
# page of every size: on A4 (842pt) it discarded the bottom 82pt, which is
# inside the text area of most A4 journal styles. A caption there was invisible
# to `find_caption_blocks`, the figure was never extracted, and the run exited 0
# — the PARTIAL bucket is the only thing that could have noticed, and only if
# the body text happened to cite that figure by number. Nothing in any of the
# four self-test suites could see it either: every fixture in all of them is
# 612x792, where a page-relative constant and an absolute one are the same
# number.
FOOTER_MARGIN = 32        # strip discarded at the foot of ANY page size
HEADER_Y_MAX = 50         # ...and at the head, whichever of these is smaller
#: 0.065, so that US Letter (792pt) lands on HEADER_Y_MAX exactly: the fraction
#: is here to shrink the strip on a SHORT page (Geron's 661.5pt pages put body
#: content at y~50), not to move a bound that was right for the page size every
#: previous version was tuned on.
HEADER_Y_FRACTION = 0.065
PAD = 8
LEFT_PAD_EXTRA = 24       # rotated y-axis labels + panel "a)" labels
BOTTOM_PAD_EXTRA = 14     # x-axis tick labels + axis title

# When an explicit figure FRAME rectangle is detected (4 line strokes forming
# a closed rect inside the search region — common in O'Reilly titles like
# Géron's Hands-On ML), the frame defines the figure extent exactly.
#
# By default the skill *strips* the frame: crops just INSIDE the frame
# strokes so the frame doesn't appear in the output PNG. This is what most
# users want — the frame is decorative chrome, not figure content.
# `batch_extract.py --keep-frame` reverses this and crops just OUTSIDE the
# frame instead, preserving it in the output. The mode is plumbed via the
# module-level `_STRIP_FRAME` flag, set by `configure_strip_frame()`.
#
# - FRAME_PAD: small uniform padding when KEEPING the frame. We use a tiny
#   value because the frame itself already encloses axis labels, panel
#   letters, and callouts — asymmetric pad-extras would just pull in prose
#   above/below the figure.
# - FRAME_STRIP_INSET: how far INSIDE the frame to crop when stripping.
#   2pt is enough to clear the stroke (typically 0.5–1.5pt wide) at any
#   reasonable DPI. Increase if a particular publisher's frame strokes are
#   thicker, but watch for tight figures where content sits right against
#   the frame — the inset can clip axis tick labels in extreme cases.
FRAME_PAD = 4
FRAME_STRIP_INSET = 2
# A "horizontal" or "vertical" line stroke has at most this much orthogonal
# extent. Slightly > 0 because line strokes sometimes have tiny artifacts.
LINE_ORTHO_EPS = 1.0
# Minimum figure-frame width — anything narrower is almost certainly not a
# figure frame (could be a code-block underline, equation rule, etc.)
MIN_FRAME_WIDTH = 100
MIN_FRAME_HEIGHT = 40

# Below these thresholds, a bbox is almost certainly an auto-detect failure
# (the detector found only the caption text rect, or some marginal scrap).
MIN_BBOX_WIDTH = 80
MIN_BBOX_HEIGHT = 60
MIN_BBOX_AREA = 8000

# A purely dimensional check misses the failure that matters most. A figure
# cropped to the bottom 45% of a bar chart — every value label gone — is
# still 70pt tall and clears all three thresholds above, and the detector
# degrades this way on exactly the information-dense figures worth keeping.
# So the bbox is also compared against the figure region it was cut from
# (the drawings between the previous caption and this one): a crop covering
# less than this fraction of that region's area has dropped figure content
# and is flagged.
MIN_REGION_COVERAGE = 0.62

# Vertical gap at which two content rects stop counting as one figure, used
# when clustering drawings into "the figure this caption belongs to". Large
# enough to bridge the whitespace inside a real figure (a schematic's frame
# rules sit ~50pt from its boxes; stacked panels are usually closer),
# small enough that a running-header rule or a table several inches up the
# page does not join the cluster and drag the figure region over the prose
# between them.
CONTENT_CLUSTER_GAP = 72

# How far outside the figure's own drawings a text block may sit and still
# count as part of the figure rather than prose above it. These mirror the
# crop's own asymmetric padding (PAD + LEFT_PAD_EXTRA on the left for
# rotated y-axis labels, PAD on the right): a block the crop would have
# included anyway is not a "preceding block".
INNER_SLOP_LEFT = PAD + LEFT_PAD_EXTRA
INNER_SLOP_RIGHT = PAD

# Default: strip the frame. `batch_extract.py --keep-frame` flips this off
# via `configure_strip_frame(False)`.
_STRIP_FRAME = True

#: The `--out` value in an emitted `--emit extract` command. This script cannot
#: know the vault path, so it has to be edited — and it says so in the path
#: itself, because the only alternative that looks like a value is a relative
#: one. A relative `Sources/Images` looks runnable and is not: pasted in the
#: normal working directory (the vault root) `extract_figures.py` would
#: `makedirs` a second Sources/Images folder wherever the shell happened to be,
#: filing figures at a name no consumer globs (CONVENTIONS.md §8a).
OUT_PLACEHOLDER = "/EDIT-THIS/path/to/vault/Sources/Images"


def configure_strip_frame(value):
    """Set whether detected figure frames should be excluded from the crop.

    True (default): crop just INSIDE the frame strokes — frame omitted from
        the output PNG. Best for personal-knowledge-vault use, since the
        frame is decorative.
    False: crop just OUTSIDE the frame strokes — frame appears in the output
        PNG. Useful when the frame carries meaning (e.g., signaling that a
        figure is composed of multiple panels).
    """
    global _STRIP_FRAME
    _STRIP_FRAME = bool(value)


def union(a, b):
    if a is None:
        return b
    if b is None:
        return a
    return fitz.Rect(min(a.x0, b.x0), min(a.y0, b.y0),
                     max(a.x1, b.x1), max(a.y1, b.y1))


def content_rect(page):
    """The page rect in the space `get_drawings()` / `get_text()` report in.

    On a page with `/Rotate 90` (a landscape figure or table rotated into a
    portrait sheet, and every scanner that guesses the orientation) PyMuPDF
    keeps THREE coordinate spaces apart and this module has to pick one:

      * `page.get_drawings()` and `page.get_text("dict")` answer in UNROTATED
        content space — the space the PDF's own operators are written in.
      * `page.rect` is the ROTATED (displayed) rect: 792x612 for a rotated US
        Letter page, so `page.rect.width` is the *height* of the space the
        drawings are in.
      * `page.get_pixmap(clip=...)` reads `clip` in the ROTATED space.

    Detection therefore runs entirely in unrotated space — this rect is what
    every page-width/height comparison in this module measures against — and
    `detect_figures` maps the finished bbox through `page.rotation_matrix`
    once, at the end, before yielding it to a caller that will hand it to
    `get_pixmap`. Mixing the two silently put the crop somewhere else on the
    sheet: a rotated page yielded 32% of the figure plus the caption, with
    nothing flagged, because every guard was comparing rotated page dimensions
    against unrotated content.
    """
    if getattr(page, "rotation", 0):
        return fitz.Rect(page.rect) * page.derotation_matrix
    return fitz.Rect(page.rect)


def to_page_space(page, rect):
    """Map a rect from unrotated content space to the page's displayed space.

    The identity on an unrotated page. `get_pixmap(clip=...)`, and every
    coordinate a user reads off `render_page.py`, live in the displayed space,
    so anything this module hands out crosses over here exactly once.
    """
    if rect is None:
        return None
    if getattr(page, "rotation", 0):
        return fitz.Rect(rect) * page.rotation_matrix
    return fitz.Rect(rect)


def header_y(page):
    """Top-margin bound for this page, in unrotated content space."""
    return min(HEADER_Y_MAX, content_rect(page).height * HEADER_Y_FRACTION)


def footer_y(page):
    """Bottom-margin bound for this page, in unrotated content space."""
    return content_rect(page).height - FOOTER_MARGIN


#: A positive-area DRAWING at least this share of the page in BOTH dimensions
#: is the sheet, not a figure on it. Page-layout tools emit a background or
#: bleed rectangle covering the whole trim area — Alberts, *Essential Cell
#: Biology* draws one at (-36,-36)-(633,813) on a 597x777 page, i.e. past every
#: edge, on all 42 pages of a chapter.
#:
#: One of these inside the search region ends figure detection before it
#: starts, and does it silently. `figure_content_span` clusters content by
#: vertical gap and a page-sized rect touches every cluster, so "the figure
#: this caption belongs to" becomes the page; the union bbox then becomes the
#: page too. Every crop comes back full-bleed, carrying the neighbouring text
#: column into a PNG meant to hold one figure — which is what the *suspicious
#: bbox* bucket was reporting as "the top edge has reached into a paragraph"
#: on 31 of 43 figures, describing a symptom whose cause was one rect.
#:
#: DRAWINGS ONLY, deliberately. A raster covering the whole sheet is a
#: legitimate full-bleed photograph and stays; a single vector path covering
#: the whole sheet has never been one figure among several. Both dimensions
#: must exceed the share — a full-width rule or a full-height column divider
#: is real page furniture the existing line handling already judges.
PAGE_COVER_SHARE = 0.95


def collect_content_rects(page):
    """Vector drawings + raster image rects on the page.

    Positive-area drawings (filled boxes, paths with a bounding region) are
    always included. Zero-area line drawings — horizontal or vertical
    strokes used to draw a figure's surrounding frame — are included only
    when they fall inside the page's body x-range (5%–95% of page width).
    This captures figure frames (O'Reilly-style framed figures) without
    pulling in printer crop marks at the page corners (Prince UDL has eight
    crop marks per page positioned outside the body region; including them
    would balloon every figure bbox to the full page).
    """
    rects = []
    pr = content_rect(page)
    body_x_min = pr.width * 0.05
    body_x_max = pr.width * 0.95
    cover_w = pr.width * PAGE_COVER_SHARE
    cover_h = pr.height * PAGE_COVER_SHARE
    for d in page.get_drawings():
        r = d.get("rect")
        if r is None:
            continue
        w, h = r.width, r.height
        if w > 0 and h > 0:
            if w >= cover_w and h >= cover_h:
                continue          # the sheet itself — see PAGE_COVER_SHARE
            rects.append(fitz.Rect(r))
            continue
        # Line drawing (exactly one of width/height is 0). Keep only if
        # the line sits inside the page body — outside that range it's
        # almost certainly a printer mark or page-decoration line.
        if (w == 0) != (h == 0):
            if r.x0 >= body_x_min and r.x1 <= body_x_max:
                rects.append(fitz.Rect(r))
    for img in page.get_images(full=True):
        xref = img[0]
        try:
            for bbox in page.get_image_rects(xref):
                rects.append(fitz.Rect(bbox))
        except Exception:
            pass
    return rects


def collect_frame_lines(page):
    """Return (horizontal_lines, vertical_lines) inside the page body.

    A line is a drawing whose rect has zero extent in one dimension. These
    are filtered to body-x-range like in `collect_content_rects` so printer
    crop marks (which sit outside the body) are excluded. Horizontal page-
    header / page-footer underlines are NOT filtered here — the caller is
    responsible for clamping to the figure search region.

    Returns:
        (hlines, vlines), each a list of fitz.Rect.
    """
    hlines, vlines = [], []
    pr = content_rect(page)
    body_x_min = pr.width * 0.05
    body_x_max = pr.width * 0.95
    for d in page.get_drawings():
        r = d.get("rect")
        if r is None:
            continue
        w, h = r.width, r.height
        is_h = h <= LINE_ORTHO_EPS and w > LINE_ORTHO_EPS
        is_v = w <= LINE_ORTHO_EPS and h > LINE_ORTHO_EPS
        if not (is_h or is_v):
            continue
        if r.x0 < body_x_min or r.x1 > body_x_max:
            continue
        (hlines if is_h else vlines).append(fitz.Rect(r))
    return hlines, vlines


def find_frame_rect(page, search_top, search_bot, search_left=None, search_right=None):
    """Detect a figure frame rectangle inside the search region.

    A frame is two vertical strokes (left and right edges) plus two
    horizontal strokes (top and bottom edges) whose endpoints meet at the
    same x-coordinates. Returns the enclosing fitz.Rect if found, else None.

    This is the most reliable way to crop figures in O'Reilly-style books
    (Géron's Hands-On ML, many published technical titles) where the
    publisher draws an explicit rectangular border around each figure: the
    frame defines the figure extent with zero ambiguity, no padding-guessing
    needed.
    """
    if search_left is None:
        search_left = 0
    if search_right is None:
        search_right = content_rect(page).width

    hlines, vlines = collect_frame_lines(page)
    # Filter to lines inside the search region
    SAFE = 2
    vlines = [v for v in vlines
              if v.y0 >= search_top - SAFE and v.y1 <= search_bot + SAFE
              and v.x0 >= search_left - SAFE and v.x1 <= search_right + SAFE]
    hlines = [h for h in hlines
              if h.y0 >= search_top - SAFE and h.y1 <= search_bot + SAFE
              and h.x0 >= search_left - SAFE and h.x1 <= search_right + SAFE]
    if len(vlines) < 2 or len(hlines) < 2:
        return None

    # The leftmost vertical line + rightmost vertical line are frame edges.
    vlines.sort(key=lambda v: v.x0)
    left_v, right_v = vlines[0], vlines[-1]
    if right_v.x0 - left_v.x0 < MIN_FRAME_WIDTH:
        return None

    # Horizontal lines that span between the vertical edges (allowing a few
    # pts of slop for stroke endpoints that don't quite meet).
    spanning = [
        h for h in hlines
        if h.x0 <= left_v.x0 + 5 and h.x1 >= right_v.x0 - 5
    ]
    if len(spanning) < 2:
        return None

    top_h = min(spanning, key=lambda h: h.y0)
    bot_h = max(spanning, key=lambda h: h.y1)
    if bot_h.y0 - top_h.y1 < MIN_FRAME_HEIGHT:
        return None

    return fitz.Rect(left_v.x0, top_h.y0, right_v.x0, bot_h.y1)


def collect_text_blocks(page):
    """(block_rect, block_text, lines) per body text block, header/footer aside.

    `lines` is [(line_rect, line_text), ...] in reading order. The line
    geometry is what lets `find_caption_blocks` anchor a caption PyMuPDF
    merged into a block with preceding text: the caption's rect becomes the
    lines from the caption line down, so the crop still ends just above the
    caption and the merged text above it (an axis label, most often) stays
    inside the figure.

    Image blocks are skipped explicitly. `get_text("blocks")` drops them by
    default and this must keep matching it — an image block arriving as a
    "text block" would raise the crop's top edge to just below the image.
    """
    out = []
    top_margin, bottom_margin = header_y(page), footer_y(page)
    for b in page.get_text("dict")["blocks"]:
        if b.get("type", 0) != 0:
            continue
        lines = []
        for ln in b.get("lines", []):
            txt = "".join(sp.get("text", "") for sp in ln.get("spans", []))
            lines.append((fitz.Rect(ln["bbox"]), txt))
        text = "\n".join(t for _, t in lines)
        if not text.strip():
            continue
        r = fitz.Rect(b["bbox"])
        if r.y1 < top_margin or r.y0 > bottom_margin:
            continue
        out.append((r, text, lines))
    return out


def collect_text_rects(page):
    """Body text block rects, excluding the page header and footer."""
    return [(r, t) for r, t, _ in collect_text_blocks(page)]


# Marker → filename-prefix mapping. The default collapses every "non-main-
# text" caption form into the same `S` namespace (so "Supplementary Figure 1",
# "Suppl. Figure 1", "Extended Data Figure 1", and "Figure S1" all produce
# the same filename — keeping things predictable across publishers). Users
# whose papers have BOTH supplementary AND Extended Data figures that need
# to stay distinct (common in Nature) can override the Extended Data prefix
# via `configure_marker_prefix("Extended Data", "ED")`, which `batch_extract`
# wires up to the `--ed-prefix` CLI flag.
#
# Keys are normalized to lowercase + single-spaced whitespace so the lookup
# is robust to "Supplementary" vs "supplementary" vs "SUPPLEMENTARY", and to
# "Extended Data" vs "Extended  Data".
MARKER_TO_PREFIX = {
    "supplementary": "S",
    "suppl.": "S",
    "supp.": "S",
    "extended data": "S",
}


def normalize_label(label):
    """A figure label reduced to its ASCII spelling: en dash → hyphen.

    `LABEL_SEP` lets a label be matched as the source typeset it, and a book
    that prints `Figure 1–14` is matched with the EN DASH still in it. The
    label does not stay that way: it becomes a filename
    (`<stem>_fig_1-14.png`), and `CONVENTIONS.md` §1b requires every name this
    plugin writes to be ASCII — a non-ASCII byte in a filename is stored in
    one Unicode normalization form on disk and cited in another in a note, and
    the two silently do not match.

    Applied to the LABEL only, never to `raw_label`: the raw form is what the
    collision report shows the user, and it has to keep the source's own
    spelling to be worth showing.
    """
    return label.replace("–", "-")


def _normalize_marker(marker):
    """Lowercase + single-space the marker text for dictionary lookup."""
    return re.sub(r"\s+", " ", marker.strip()).lower()


def configure_marker_prefix(marker, prefix):
    """Reconfigure the filename prefix for a given supplementary marker.

    Example: `configure_marker_prefix("Extended Data", "ED")` makes
    "Extended Data Figure 1" produce `_fig_ED1.png` instead of `_fig_S1.png`.
    Pass any case / whitespace variant of the marker — it's normalized
    before lookup.
    """
    MARKER_TO_PREFIX[_normalize_marker(marker)] = prefix


def find_caption_blocks(page):
    """All (fig_num, raw_label, rect) for text blocks starting with a figure caption.

    Figure labels are normalized: when the caption is preceded by a marker
    word ("Supplementary", "Suppl.", "Supp.", "Extended Data") in any case,
    the corresponding filename prefix is prepended to the figure number
    unless the number already starts with that prefix. So with the default
    mapping, `Supplementary Figure 1`, `Extended Data Figure 1`, and
    `Figure S1` all yield the normalized label "S1".

    `raw_label` preserves the form the source used (e.g., "Supplementary
    Figure 1", "Extended Data Figure 1", "Figure S1"). This is used only
    for diagnostics — specifically, when two captions in the same PDF
    normalize to the same filename, the collision report shows the raw
    forms so the user knows which captions collided.

    The scan is `finditer`, not `match`. `match` anchors at offset 0, which
    made the `re.MULTILINE` flag and the pattern's leading `^\\s*` dead
    weight: only the block's FIRST line could ever match. PyMuPDF merges a
    caption into one block with the text just above it whenever the two are
    a line apart — an axis label, a page-number strip, the last line of a
    paragraph — and every one of those captions was invisible. Silently: a
    real 4-figure paper extracted 3, and no count anywhere disagreed.

    The returned rect is the caption's OWN lines (from the caption line to
    the end of the block, or to the next caption in the same block), not the
    whole block. `bbox_for_figure` ends the crop just above that rect, so a
    merged axis label above the caption stays in the figure instead of being
    cropped away with the caption text.

    The cost of scanning every line is a false positive when a wrapped
    paragraph puts a caption-shaped string at the start of a line ("…shown
    in / Figure 3. The trend…"). That was possible before too — it just
    needed the paragraph's first line — and it is the failure worth having:
    an extra crop is visible in `Sources/Images/` and shows up as a caption
    collision or a duplicate, while a missed caption is visible nowhere at
    all.
    """
    out = []
    for rect, text, lines in collect_text_blocks(page):
        matches = list(CAP_RE.finditer(text))
        if not matches:
            continue
        # Offset at which each line starts inside `text` ("\n"-joined).
        line_start, pos = [], 0
        for _, ltxt in lines:
            line_start.append(pos)
            pos += len(ltxt) + 1
        seen = set()
        for k, m in enumerate(matches):
            supp_marker = m.group(1)
            fig_num = normalize_label(m.group(2))
            # Reconstruct the source caption label (everything matched up
            # to and including the number, minus the trailing punctuation).
            raw_label = m.group(0).strip()
            # Trim a trailing period or whitespace that the lookahead let
            # through, so "Figure S1" not "Figure S1.".
            raw_label = raw_label.rstrip(". \t")
            if supp_marker:
                prefix = MARKER_TO_PREFIX.get(_normalize_marker(supp_marker), "S")
                if not fig_num.startswith(prefix):
                    fig_num = prefix + fig_num
            if fig_num in seen:
                continue          # same label twice in one block — one figure
            seen.add(fig_num)
            first = _line_index(line_start, m.start())
            last = len(lines) - 1
            if k + 1 < len(matches):
                nxt = _line_index(line_start, matches[k + 1].start())
                last = max(first, nxt - 1)
            cap_rect = None
            for lr, _ in lines[first:last + 1]:
                cap_rect = union(cap_rect, lr)
            out.append((fig_num, raw_label, cap_rect or rect))
    return out


def _line_index(line_start, offset):
    """Index of the line containing `offset`, given each line's start offset."""
    i = 0
    for j, start in enumerate(line_start):
        if start <= offset:
            i = j
        else:
            break
    return i


# "Is this caption BESIDE its figure, or BELOW it?" is not decidable by any
# single geometric predicate, and three rounds of trying cost five working
# layouts. Each attempt was a veto — one more condition a side caption had to
# satisfy — and each veto fixed the layout it was written for and silently
# broke another, because the two shapes genuinely overlap:
#
#   * a caption centred on its figure and one crossed by the next column's
#     chart look the same (the centring veto; it threw away every top- and
#     bottom-aligned side caption, ~45% of positions);
#   * "the content must cover the caption's band" measured against the
#     CAPTION's height alone made a caption taller than its figure impossible
#     (101pt of caption beside a 100pt figure: rejected by construction);
#   * "another caption's column is on the figure's side" killed a side caption
#     because an unrelated figure lower down the page had an ordinary caption
#     starting past the midline;
#   * "anything directly above it in its own column makes it a bottom caption"
#     rejected on a 30x30 piece of unrelated art — and the crop then landed on
#     the art, with none of the real figure in it and nothing flagged.
#
# So the two readings are SCORED against each other instead, and the better one
# wins. A veto turns weak evidence into a wrong answer; a score lets weak
# evidence lose gracefully. Three things follow from that and matter as much as
# the scores:
#
#   * the bottom reading is the default and the side reading has to beat it by
#     `SIDE_MARGIN` — the bottom reading's failure mode is a crop that is too
#     big, the side reading's is a crop of the wrong part of the page;
#   * when the two are close, the figure is FLAGGED as ambiguous rather than
#     silently decided. Every one of the five failures above was silent, which
#     is the part that actually costs the user something;
#   * whatever the classification decides, `suspicious()` checks that the
#     finished crop actually contains the content that reading was based on.
#     That catches a misread regardless of how it happened.

#: Which rects join the side reading's ANCHOR: content sharing less than this
#: fraction of the shorter of (caption band, content band) is a touch, not a
#: placement, and is left out of it.
#:
#: It is deliberately NOT where the side-vs-bottom decision is made, and does
#: not behave like a threshold on that decision: moving it anywhere in
#: [0.02, 0.4] flips no reading in a 319-figure corpus, because `SIDE_MARGIN`
#: dominates. What it does affect is real but narrower — which content the
#: anchor spans, and therefore how far the side crop reaches
#: (`column_interval`) and what the anchor backstop in `suspicious()` requires
#: the crop to contain. Read it as anchor membership, not as a veto; the
#: strength of the evidence is the `share` it computes, and that is scored.
#:
#: It was briefly a hard floor at 0.9 on the DECISION, which rejected a caption
#: whose first line sits ten points above its figure's top edge — where
#: captions normally sit — and, measured against the caption's height rather
#: than the shorter of the two, made a caption taller than its figure
#: impossible by construction.
SIDE_BAND_MIN = 0.15

#: How far the side reading has to beat the bottom reading before it is taken.
#: Not a tuning knob so much as a statement about which error is cheaper: a
#: bottom crop that is too generous keeps the figure and some neighbours; a
#: side crop chosen wrongly is a picture of something else.
SIDE_MARGIN = 0.4

#: Below this, a reading has no evidence behind it at all and its rival is not
#: "close" — it is simply the only one. Above it on both sides, with less than
#: `SIDE_MARGIN` between them, the placement is reported as ambiguous.
#:
#: It is 0.02 because that is what was measured, not what was guessed. At the
#: 0.35 this shipped with, the clause was dead: the two readings score on
#: DISJOINT content — one on what is beside the caption, the other on what is
#: above it — so they almost never both run high, and across 319 figures in 51
#: layouts exactly one had both scores above 0.2. At 0.02, all seven of the
#: silently-wrong crops in that corpus became flagged ones, no figure anywhere
#: else in it gained a flag, no crop moved by a pixel, and the real paper was
#: unchanged. The number is low because the question it asks is "is there ANY
#: case for the other reading?", and the answer being yes is exactly when a
#: human should look.
PLACEMENT_CONTESTED = 0.02

#: A side reading taken on evidence weaker than this is reported as ambiguous
#: even when nothing contests it. The bottom reading is the default and needs
#: no confidence to be taken; the side reading is the deviation, and a weak one
#: is exactly the case that has gone wrong four times.
PLACEMENT_CONFIDENT = 0.6


class _Placement(object):
    """How a caption sits relative to its figure, and how sure that is."""

    __slots__ = ("side", "ambiguous", "side_score", "bottom_score", "anchor")

    def __init__(self, side=None, ambiguous="", side_score=0.0,
                 bottom_score=0.0, anchor=None):
        self.side = side
        #: "" when the reading is safe, else why it is not: "contested" (both
        #: readings have evidence and are close) or "thin" (the side reading
        #: was taken with little behind it). Truthy either way.
        self.ambiguous = ambiguous
        self.side_score = side_score
        self.bottom_score = bottom_score
        #: The content the winning reading was based on — what the crop must
        #: contain for the reading to have been worth anything.
        self.anchor = anchor


def _caption_owns(other, anchor):
    """True when caption `other` sits directly under `anchor`.

    Then `anchor` is that caption's figure, not content this caption is beside.
    Ownership, not position: the old rule was "any other caption starting past
    the page midline", which a second figure lower down the page satisfies
    without having anything to do with this one.
    """
    gap = other.y0 - anchor.y1
    if gap < -2 or gap > CONTENT_CLUSTER_GAP:
        return False
    overlap = min(other.x1, anchor.x1) - max(other.x0, anchor.x0)
    return overlap > 0.5 * min(other.width, anchor.width)


def _side_evidence(cap_rect, content, side, other_captions):
    """(anchor, strength) for "the figure is beside this caption".

    Strength is how much of the two bands' shorter side they share — a figure
    the caption sits alongside covers its band; one crossing it on the way
    past clips it. Measured symmetrically, so a tall caption beside a short
    figure and a short caption beside a tall one score alike.
    """
    anchor, best = None, 0.0
    for r in content:
        if r.width < 30 or r.height < 30:
            continue
        if side == "left" and not r.x0 > cap_rect.x1:
            continue
        if side == "right" and not r.x1 < cap_rect.x0:
            continue
        overlap = min(r.y1, cap_rect.y1) - max(r.y0, cap_rect.y0)
        share = overlap / max(1.0, min(cap_rect.height, r.height))
        if share < SIDE_BAND_MIN:
            continue                       # a touch, not a placement
        anchor = union(anchor, r)
        best = max(best, min(1.0, share))
    if anchor is None:
        return None, 0.0
    strength = best
    for other in other_captions:
        if other is not cap_rect and _caption_owns(other, anchor):
            strength *= 0.25    # that content already has a caption
    return anchor, strength


def _bottom_evidence(cap_rect, content):
    """(candidate, strength) for "the figure is above this caption".

    Strength is how much this looks like a caption sitting under that content:
    how much of the narrower of the two the horizontal overlap covers, times
    how close it is (`CONTENT_CLUSTER_GAP` away scores nothing).
    """
    best, cand = 0.0, None
    for r in content:
        if r.width < 30 or r.height < 30:
            continue
        if r.y1 > cap_rect.y0:
            continue                                   # not above
        gap = cap_rect.y0 - r.y1
        if gap > CONTENT_CLUSTER_GAP:
            continue                                   # too far to be its figure
        overlap = min(r.x1, cap_rect.x1) - max(r.x0, cap_rect.x0)
        if overlap <= 0:
            continue
        share = overlap / max(1.0, min(r.width, cap_rect.width))
        strength = share * (1.0 - gap / CONTENT_CLUSTER_GAP)
        if strength > best:
            best, cand = strength, r
    return cand, best


def _area(r):
    return 0.0 if r is None else max(0.0, r.width) * max(0.0, r.height)


def caption_placement(page, cap_rect, other_captions=()):
    """Score both readings of where this caption's figure is; return the better.

    Returns a `_Placement`: `.side` is "left" (figure to the RIGHT of the
    caption), "right" (figure to the LEFT) or None (figure ABOVE — the
    default); `.ambiguous` is True when the two readings came out close enough
    that the answer is a guess; `.anchor` is the content the winning reading
    was based on.

    Both readings are weighted by how much of a figure their candidate is,
    relative to each other: a 30x30 mark above the caption cannot outweigh a
    quarter-page chart beside it, however well-placed the mark is. That is what
    makes the scores comparable at all — the geometry alone is not.
    """
    pr = content_rect(page)
    if cap_rect.width >= pr.width * 0.5:
        # A caption spanning half the page is under its figure, full stop.
        # No content is consulted, so there is no anchor to check either.
        return _Placement()
    cap_mid = (cap_rect.x0 + cap_rect.x1) / 2
    side = "right" if cap_mid > pr.width / 2 else "left"

    content = collect_content_rects(page)
    anchor, side_strength = _side_evidence(cap_rect, content, side,
                                           other_captions)
    cand, bottom_strength = _bottom_evidence(cap_rect, content)

    biggest = max(_area(anchor), _area(cand), 1.0)
    side_score = side_strength * (_area(anchor) / biggest)
    bottom_score = bottom_strength * (_area(cand) / biggest)

    takes_side = side_score > bottom_score + SIDE_MARGIN
    # Two ways a placement is not to be trusted, and they are DIFFERENT things
    # — a message that describes one while the other fired is worse than no
    # message, in a module whose whole thesis is that a wrong answer must not
    # be silent. "contested": both readings have some evidence and are close.
    # "thin": the side reading was taken with nothing much behind it and
    # nothing contesting it either.
    contested = (min(side_score, bottom_score) >= PLACEMENT_CONTESTED
                 and abs(side_score - bottom_score) < SIDE_MARGIN)
    thin = takes_side and side_score < PLACEMENT_CONFIDENT
    return _Placement(
        side=side if takes_side else None,
        ambiguous="contested" if contested else ("thin" if thin else ""),
        side_score=side_score,
        bottom_score=bottom_score,
        anchor=anchor if takes_side else cand,
    )


def side_caption_position(page, cap_rect, other_captions=()):
    """"left" / "right" / None — where this caption's figure is.

    Thin wrapper over `caption_placement` for callers that only want the
    answer and not the evidence behind it.
    """
    return caption_placement(page, cap_rect, other_captions).side


def clip_content(content, top, bottom, left, right):
    """Content rects clipped to a search region; degenerate results dropped."""
    out = []
    for r in content:
        if r.y1 < top or r.y0 > bottom or r.x0 > right or r.x1 < left:
            continue
        c = fitz.Rect(max(r.x0, left), max(r.y0, top),
                      min(r.x1, right), min(r.y1, bottom))
        if c.x1 < c.x0 or c.y1 < c.y0:
            continue
        out.append(c)
    return out


def figure_content_span(content):
    """Union of the content rects contiguous with the bottom-most one.

    "The figure this caption belongs to" is the lowest cluster of drawings
    in the search region — the one nearest the caption. Rects are swept in
    y order and split into clusters wherever the vertical gap exceeds
    `CONTENT_CLUSTER_GAP`; the last cluster is returned. Taking the plain
    union instead would let one stray stroke — a running-header rule, a
    table's rules several inches up — define a region stretching over the
    prose in between, and every paragraph inside it would then read as part
    of the figure.

    Returns None when there is no content at all (raster-only figures whose
    image rects PyMuPDF does not report), which callers treat as "no
    opinion" rather than "empty figure".

    One sorted sweep, not a repeated scan: a single matplotlib figure can
    carry thousands of vector segments, and this runs once per caption.
    """
    if not content:
        return None
    rects = sorted(content, key=lambda r: (r.y0, r.y1))
    cluster = [rects[0]]
    bottom = rects[0].y1
    for r in rects[1:]:
        if r.y0 <= bottom + CONTENT_CLUSTER_GAP:
            cluster.append(r)
            bottom = max(bottom, r.y1)
        else:
            cluster = [r]              # a gap this big starts a new figure
            bottom = r.y1
    span = None
    for r in cluster:
        span = union(span, r)
    return span


#: Horizontal gap at which two content rects stop counting as one column, used
#: to stop a side caption's crop at its figure instead of at the edge of the
#: sheet. Deliberately generous — three quarters of `CONTENT_CLUSTER_GAP` —
#: because the failure it prevents (a stray mark or a further column joining
#: the crop) is visible in the PNG, while the failure a tight value would
#: cause (a multi-panel figure clipped at an internal gutter) is a silent
#: under-crop, and the region-coverage guard measures vertically only.
SIDE_COLUMN_GUTTER = 54


def column_interval(anchor, rects, gutter=None):
    """(x0, x1) of the column `anchor` belongs to, merging rects across `gutter`.

    The horizontal twin of `figure_content_span`: x-intervals are merged
    wherever they are less than `gutter` apart, and the merged interval
    containing the anchor is returned. Panels of one figure sit well inside a
    gutter of each other; the next column over does not.

    `gutter` defaults to `SIDE_COLUMN_GUTTER` READ AT CALL TIME, not bound as
    a default argument. As a default argument the module constant was captured
    at import, so changing it changed nothing — which is how a self-test came
    to pass with the gutter set to 0: the value under test was never the value
    in use.
    """
    if gutter is None:
        gutter = SIDE_COLUMN_GUTTER
    ivs = sorted([(r.x0, r.x1) for r in rects] + [(anchor.x0, anchor.x1)])
    groups, cur = [], list(ivs[0])
    for a, b in ivs[1:]:
        if a <= cur[1] + gutter:
            cur[1] = max(cur[1], b)
        else:
            groups.append(tuple(cur))
            cur = [a, b]
    groups.append(tuple(cur))
    for g0, g1 in groups:
        if g0 <= anchor.x0 and g1 >= anchor.x1:
            return g0, g1
    return anchor.x0, anchor.x1


def text_block_inside_figure(rect, span):
    """True when a text block belongs to the figure rather than sitting above it.

    `span` is the figure's drawing cluster (`figure_content_span`). A block
    counts as figure-internal when it starts below the figure's top edge AND
    its full width fits inside the figure's horizontal span, padded the way
    the crop itself pads (left for rotated y-axis labels, right a hair).
    That covers bar value labels, schematic box labels, legend entries and
    the axis tick row / axis title hanging below the plot — all of which are
    "a preceding text block" by pure y-ordering, and raising the crop's top
    edge past any of them throws away everything above it.

    Prose above the figure fails the first test (it ends before the drawings
    begin) and text in the neighbouring column of a two-column page fails
    the second, so both still push the top edge down as they should.
    """
    if span is None:
        return False
    if rect.y1 <= span.y0:
        return False                      # entirely above the figure — prose
    return (rect.x0 >= span.x0 - INNER_SLOP_LEFT
            and rect.x1 <= span.x1 + INNER_SLOP_RIGHT)


def bbox_for_figure(page, caption_rect, all_captions, all_text_blocks, diag=None):
    """Compute figure bbox for the figure that goes with `caption_rect`.

    `diag`, when a dict is passed in, is filled with what the sanity check
    needs to judge the result: `region` is the figure's drawing cluster
    between the previous caption and this one, i.e. what the crop *should*
    have covered.
    """
    other_caps = [r for _, r in all_captions if r is not caption_rect]
    placement = caption_placement(page, caption_rect, other_caps)
    side = placement.side
    if diag is not None:
        diag["placement"] = placement
    inner_text = []          # text blocks that are part of the figure itself
    # One `get_drawings()` pass for the whole figure: it is the expensive
    # call on this path, and a drawing-heavy page has thousands of paths.
    content = collect_content_rects(page)
    pr = content_rect(page)
    page_top, page_bottom = header_y(page), footer_y(page)

    if side in ("right", "left"):
        # Caption beside the figure. Use the full page band for Y bounds — the
        # figure body often extends well above and below the caption block,
        # and we isolate the figure column via the x-limits, so the
        # asymmetric Y extent doesn't pull in unrelated content.
        #
        # ...but only down to the next caption. The band used to run to the
        # foot of the page unconditionally, so nothing clamped the crop away
        # from a LATER caption sitting in the figure's own column, and the
        # side path is the one path that has no other bound at all.
        top = page_top
        bottom = page_bottom
        for r in other_caps:
            if r.y0 > caption_rect.y1:            # a caption below this one
                bottom = min(bottom, r.y0 - 0.5)
            elif r.y1 < caption_rect.y0:          # ...and one above it
                top = max(top, r.y1 + 4)
        if side == "right":
            # Figure occupies the column to the LEFT of the caption.
            left_limit = 0
            right_limit = caption_rect.x0 - 4
        else:
            # Figure occupies the column to the RIGHT of the caption.
            left_limit = caption_rect.x1 + 4
            right_limit = pr.width
        # The far edge stops at the figure's own column, not at the edge of
        # the sheet. The near edge is the caption's; the far one was the page
        # boundary, so anything between the figure and the margin — a further
        # column, a marginal note, a rule — was inside the search region and
        # joined the union. The column is grown from the content that covers
        # the caption's band (the figure the caption is beside, by the same
        # test that classified it) across `SIDE_COLUMN_GUTTER`, so a
        # multi-panel figure stays whole.
        # The anchor is the content the classification was made on — taken
        # from the placement rather than recomputed here, so there is one
        # definition of "the figure this caption is beside" and not two that
        # can drift.
        band = clip_content(content, top, bottom, left_limit, right_limit)
        anchor = placement.anchor
        if anchor is not None:
            col_x0, col_x1 = column_interval(anchor, band)
            if side == "right":
                left_limit = max(left_limit, col_x0)
            else:
                right_limit = min(right_limit, col_x1)
        region = figure_content_span(
            clip_content(content, top, bottom, left_limit, right_limit))
        # The region-coverage guard needs a region on THIS path too. It only
        # ever got one in the bottom-caption branch below, so `region` came
        # back None for every side caption and the whole guard was skipped —
        # on the one path whose crop is built from a different column of the
        # page, i.e. the path where a wrong crop is furthest wrong.
        if diag is not None:
            diag["region"] = region
    else:
        # Caption sits below figure. Top edge = page header bottom OR the
        # bottom of the previous caption / prose block above this caption.
        top = page_top
        for _, r in all_captions:
            if r is caption_rect:
                continue
            if r.y1 < caption_rect.y0:
                top = max(top, r.y1 + 4)
        # Bottom of the figure search region. We keep a small gap from the
        # caption text — but the gap has to be smaller than the typical
        # caption-to-figure spacing in the source, otherwise a figure whose
        # bottom frame line sits right against the caption (1–2 pt above
        # it) gets clipped. 0.5 pt is enough to keep the caption excluded
        # while leaving every frame line inside the search region.
        bottom = caption_rect.y0 - 0.5
        right_limit = pr.width
        left_limit = 0
        # The caption-to-caption region: everything this figure could
        # possibly occupy. The drawings inside it are clustered into "the
        # figure", and that cluster decides which text blocks below are
        # part of the figure and which are prose above it. Without the
        # distinction, a bar chart's own value labels raise the top edge and
        # the crop keeps only what sits under the lowest label.
        #
        # Measured from the UNRAISED top (`page_top`), not from `top`. The
        # region is the yardstick the coverage guard holds the finished bbox
        # against — "how much of the figure did the crop keep?" — and it was
        # being clipped by the very raise it exists to detect, so `bbox.y0`
        # could never precede `region.y0` and `cover` came out 1.00 however
        # much had been cut off: a crop starting at y=330 on a figure starting
        # at y=200 scored 100%. Clustering is what keeps the wider span from
        # dragging in the PREVIOUS figure — a caption's worth of vertical gap
        # is far more than CONTENT_CLUSTER_GAP.
        region = figure_content_span(
            clip_content(content, page_top, bottom, 0, pr.width))
        if diag is not None:
            diag["region"] = region
        for r, _ in all_text_blocks:
            if r is caption_rect:
                continue
            # A block starting at or below the search region's bottom edge is
            # the caption itself (or something under it), and it is neither
            # figure content nor a block that could push the top edge down.
            #
            # The identity test above cannot see it: `all_text_blocks` comes
            # from a second `collect_text_blocks` pass, so its rects are
            # different objects from the caption rect `find_caption_blocks`
            # built out of the caption's own LINES — `is` is never true on the
            # `detect_figures` path. The caption block therefore landed in
            # `inner_text` (it sits below the figure's top edge and inside its
            # x-span, which is what `text_block_inside_figure` asks), where the
            # union loop clips it away harmlessly — but the frame guard below
            # reads `inner_text` UNCLIPPED, saw the caption sitting below the
            # frame, called that a contradiction and discarded the frame. On a
            # real publisher-framed figure the caption is always there, so the
            # frame branch — the whole point of `--keep-frame` and of frame
            # stripping — was dead on every figure it was written for.
            if r.y0 >= bottom:
                continue
            if text_block_inside_figure(r, region):
                # Part of the figure, so it also belongs in the crop. Axis
                # tick rows and axis titles hang below the last drawing;
                # BOTTOM_PAD_EXTRA alone guesses at them, and a rotated
                # y-axis label sits outside the drawings on the left.
                inner_text.append(r)
                continue
            if (r.y1 < caption_rect.y0 - 5 and r.y1 > top
                    and r.x1 > caption_rect.x0 and r.x0 < caption_rect.x1):
                top = r.y1 + 4

    # Preferred path: if the publisher draws an explicit frame rectangle
    # around the figure (O'Reilly titles, many technical books), the frame
    # IS the figure boundary. Use it directly — no axis-label or panel-
    # letter pad-extras needed because those are already inside the frame.
    # This is more reliable than unioning the content rects, which can leak
    # above/below the figure when prose lines sit just outside the frame.
    #
    # Frame stripping (default): crop just INSIDE the stroke positions so
    # the frame doesn't appear in the output PNG. The publisher's frame is
    # decorative chrome; users dropping these into a personal knowledge
    # vault almost always want it gone. `--keep-frame` flips the inset to
    # a small outset, preserving the frame in the output.
    frame = find_frame_rect(
        page, top, bottom, search_left=left_limit, search_right=right_limit,
    )
    # A matplotlib axes-spine box is four strokes forming a closed rectangle,
    # which is indistinguishable from a publisher's frame by shape -- and the
    # frame branch returns before the `inner_text` union runs, so every tick
    # label, axis title and outside legend the detector had ALREADY classified
    # as figure content was thrown away.  That is what cropped two of this
    # skill's figures short of their own axes with no warning: the crop stops
    # ~26pt above the caption where a correct one stops 0.5pt above it.
    #
    # The detector contradicting itself is the signal: if content it called
    # figure-internal lies outside the frame, the frame is not the figure's
    # boundary.  Not a threshold -- a logical inconsistency, so it costs
    # nothing in false positives on a genuine publisher frame, where the
    # inner text is by construction inside.
    if frame is not None and inner_text:
        spill = [r for r in inner_text
                 if r.y1 > frame.y1 + 1 or r.y0 < frame.y0 - 1
                 or r.x1 > frame.x1 + 1 or r.x0 < frame.x0 - 1]
        if spill:
            frame = None
    if frame is not None:
        if _STRIP_FRAME:
            inset = FRAME_STRIP_INSET
            x0 = frame.x0 + inset
            y0 = frame.y0 + inset
            x1 = frame.x1 - inset
            y1 = frame.y1 - inset
        else:
            x0 = max(0, frame.x0 - FRAME_PAD)
            y0 = max(0, frame.y0 - FRAME_PAD)
            x1 = min(pr.width, frame.x1 + FRAME_PAD)
            y1 = min(pr.height, frame.y1 + FRAME_PAD)
        # Clamp to search region. When stripping the frame this is mostly
        # belt-and-braces (the inset already shrinks the bbox), but when
        # keeping it we need to make sure the outward pad doesn't cross
        # the caption or a preceding caption above.
        y0 = max(y0, top)
        if side == "right":
            y1 = min(y1, bottom)
            x1 = min(x1, right_limit)
        elif side == "left":
            y1 = min(y1, bottom)
            x0 = max(x0, left_limit)
        else:
            y1 = min(y1, caption_rect.y0 - 0.5)
        return fitz.Rect(x0, y0, x1, y1)

    # Union of all vector + image content in the figure band. Each rect is
    # clipped to the search region before union — content that extends past
    # the search bounds (e.g., a sidebar border that runs from above the
    # figure all the way past the caption) shouldn't pull the figure bbox
    # outside the intended region.
    bbox = None
    for r in list(content) + inner_text:
        if r.y1 < top or r.y0 > bottom:
            continue
        if r.x0 > right_limit or r.x1 < left_limit:
            continue
        clipped = fitz.Rect(
            max(r.x0, left_limit),
            max(r.y0, top),
            min(r.x1, right_limit),
            min(r.y1, bottom),
        )
        # Skip if the clipped rect is degenerate.
        if clipped.x1 < clipped.x0 or clipped.y1 < clipped.y0:
            continue
        bbox = union(bbox, clipped)

    # Fallback for raster-only figures whose image rect isn't reported.
    if bbox is None:
        if side in ("left", "right"):
            bbox = fitz.Rect(left_limit + 4, top + 4, right_limit - 4, bottom - 4)
        else:
            bbox = fitz.Rect(caption_rect.x0, top + 4,
                             caption_rect.x1, bottom - 4)

    # Asymmetric padding: more on left for rotated y-axis labels, more on
    # bottom for x-axis labels.
    x0 = max(0, bbox.x0 - PAD - LEFT_PAD_EXTRA)
    y0 = max(0, bbox.y0 - PAD)
    x1 = min(pr.width, bbox.x1 + PAD)
    y1 = min(pr.height, bbox.y1 + PAD + BOTTOM_PAD_EXTRA)

    # Clamp the padded bbox against the search region. Content is already
    # clipped to (top, bottom, left_limit, right_limit) during the union
    # above, so we just need to keep the asymmetric padding inside those
    # bounds.
    y0 = max(y0, top)
    if side == "right":
        y1 = min(y1, bottom)
        x1 = min(x1, right_limit)
    elif side == "left":
        y1 = min(y1, bottom)
        x0 = max(x0, left_limit)
    else:
        y1 = min(y1, caption_rect.y0 - 0.5)
    return fitz.Rect(x0, y0, x1, y1)


def degenerate(bbox):
    """True when the bbox has no area at all and cannot be rendered.

    `fitz.Rect.width` / `.height` clamp at 0, so an *inverted* rect (the
    search region collapsed to nothing — a caption with a prose block right
    above it, a side caption hard against the page edge) reports 0 rather
    than a negative number. Rendering one raises deep inside PyMuPDF's
    band writer ("Invalid bandwriter header dimensions"), and rendering a
    zero-area-but-not-inverted rect silently writes a 1x1 PNG into the
    vault. Callers check this first and skip, rather than crashing or
    writing a garbage attachment.
    """
    return bbox.width <= 0 or bbox.height <= 0


#: Body-prose characters inside a crop, at the document's own modal font size.
#: Over 150 means the crop has swallowed a paragraph.  Measured on the paper
#: that motivated this check: 419 chars for the figure that reached into prose,
#: 47 for the worst clean one.
MAX_PROSE_CHARS = 150


def prose_chars_in(page, bbox, body_size=None):
    """Characters of body-size text inside `bbox`.  0 when it cannot tell."""
    try:
        d = page.get_text("dict")
    except Exception:
        return 0
    sizes = {}
    spans = []
    for blk in d.get("blocks", []):
        for line in blk.get("lines", []):
            for sp in line.get("spans", []):
                txt = sp.get("text", "")
                if not txt.strip():
                    continue
                sz = round(float(sp.get("size", 0)), 1)
                sizes[sz] = sizes.get(sz, 0) + len(txt)
                spans.append((sz, sp.get("bbox"), len(txt)))
    if not sizes:
        return 0
    modal = body_size if body_size else max(sizes, key=sizes.get)
    n = 0
    for sz, sb, ln in spans:
        if abs(sz - modal) > 0.3 or not sb:
            continue
        r = fitz.Rect(sb)
        if r.x0 >= bbox.x0 - 1 and r.x1 <= bbox.x1 + 1 \
                and r.y0 >= bbox.y0 - 1 and r.y1 <= bbox.y1 + 1:
            n += ln
    return n


def header_bands(doc, min_share=0.4):
    """[(y0, y1, text)] for lines that repeat at the same height across pages.

    A running head is never figure content, so a crop containing one has
    reached above the figure.  This is the only signal that catches it: the
    top edge is set by the margin clamp, which a legitimate figure starting at
    the top margin also produces, so the clamp position alone is not evidence.
    One text pass per document, computed once and reused for every figure.
    """
    n = len(doc)
    if n < 3:
        return []
    seen = {}
    for i in range(n):
        try:
            page = doc[i]
            d = page.get_text("dict")
        except Exception:
            continue
        band = header_y(page) * 3      # per page: a short page has a short band
        for blk in d.get("blocks", []):
            for line in blk.get("lines", []):
                txt = "".join(sp.get("text", "") for sp in line.get("spans", []))
                txt = " ".join(txt.split())
                if len(txt) < 8:
                    continue
                bb = line.get("bbox")
                if not bb or bb[1] > band:
                    continue                 # only the top band of the page
                key = (txt, round(bb[1] / 4.0))
                lo, hi, c = seen.get(key, (bb[1], bb[3], 0))
                seen[key] = (min(lo, bb[1]), max(hi, bb[3]), c + 1)
    out = []
    for (txt, _), (lo, hi, c) in seen.items():
        if c >= max(3, int(n * min_share)):
            out.append((lo, hi, txt))
    return out


#: Tag on the `suspicious()` reason for a crop that has caption text in it, so
#: the batch report can give that outcome its own bucket. It is not one more
#: shape of "the bbox looks wrong": it is the skill's central promise broken —
#: the caption is the one thing the crop is guaranteed to leave out.
CAPTION_IN_CROP_TAG = "caption text inside the crop: "

#: Tag on the reason for a crop whose caption could be read as sitting beside
#: its figure or under it, with little to choose between them. Advisory: the
#: crop is usually right, and one look costs the reader nothing — where a
#: silently wrong reading costs a figure. Every side-caption failure this
#: module has had was silent.
CAPTION_AMBIGUOUS_TAG = "caption position ambiguous: "

#: How much of the content a placement was based on the finished crop has to
#: contain. A backstop independent of the classification: whichever reading
#: won, a crop holding none of the content that reading was chosen for is
#: wrong, and this is the one check that does not care why.
ANCHOR_MIN_COVER = 0.5

#: Minimum overlap, in points, between a crop and a caption before the crop
#: counts as containing it. Big enough to ignore a hairline touch at the
#: `caption_rect.y0 - 0.5` boundary the bottom-caption path aims for, small
#: enough that any actual sliver of a ~10pt caption line is caught.
CAPTION_OVERLAP_EPS = 2.0


def caption_in_crop(bbox, captions):
    """The first caption `bbox` visibly overlaps, or None.

    Every caption on the page, not just this figure's own: a crop built from
    the wrong column or the wrong half of a rotated sheet lands on somebody
    else's caption, and that is exactly the case with no other witness.
    """
    for entry in captions or ():
        cap = entry[-1]
        raw = entry[1] if len(entry) > 2 else None
        ox = min(bbox.x1, cap.x1) - max(bbox.x0, cap.x0)
        oy = min(bbox.y1, cap.y1) - max(bbox.y0, cap.y0)
        if ox > CAPTION_OVERLAP_EPS and oy > CAPTION_OVERLAP_EPS:
            return raw, cap
    return None


def suspicious(bbox, region=None, page=None, caption_rect=None, headers=None,
               captions=None, placement=None):
    """Return a short reason string if the bbox looks like an auto-detect failure, else ''.

    `region` is the figure's drawing cluster between the previous caption
    and this one — what the crop should have covered. The dimensional
    thresholds alone only catch a bbox that collapsed; they say nothing
    about one that is a perfectly plausible 400x71 rectangle holding the
    bottom 45% of a bar chart. Comparing against the region catches that,
    and it is the failure users actually hit, because the detector degrades
    on figures with text inside them — the information-dense ones.

    `captions` is every caption found on the page, as `find_caption_blocks`
    returns them. The crop is checked against all of them. `caption_rect` (this
    figure's own caption) is accepted for callers that have only that one, and
    is folded into the same check — it used to be accepted and then never read
    at all, so the only caption-overlap check in the plugin lived in
    `extract_figures.main()`, which `batch_extract.py` bypasses by calling
    `extract_one_figure()` directly. The batch path — the path that does all
    the work — had no caption check whatever, which is why two whole classes
    of wrong crop wrote caption text into PNGs with every bucket reading zero.

    `placement` is `caption_placement`'s verdict on where this caption's figure
    is. Two things come from it: the crop has to contain the content that
    verdict was based on (`ANCHOR_MIN_COVER` — a structural check that holds
    however the classification went), and a verdict the scores could not
    separate is reported as ambiguous rather than acted on in silence.
    """
    w, h = bbox.width, bbox.height
    area = w * h
    if degenerate(bbox):
        return f"degenerate rect {w:.0f}x{h:.0f} — nothing to render"
    if w < MIN_BBOX_WIDTH:
        return f"width {w:.0f} < {MIN_BBOX_WIDTH}"
    if h < MIN_BBOX_HEIGHT:
        return f"height {h:.0f} < {MIN_BBOX_HEIGHT}"
    if area < MIN_BBOX_AREA:
        return f"area {area:.0f} < {MIN_BBOX_AREA}"
    if region is not None and region.height > 0:
        # Vertical coverage only, and measured against the region rather
        # than the crop: the crop is legitimately narrower than the region
        # on a two-column page (the region can span both columns), but a
        # crop that starts well below the figure's own top edge has thrown
        # figure content away, and that is the failure being caught.
        overlap = min(region.y1, bbox.y1) - max(region.y0, bbox.y0)
        cover = max(0.0, overlap) / region.height
        if cover < MIN_REGION_COVERAGE:
            return (f"covers {cover * 100:.0f}% of the figure region above "
                    f"the caption (region y={region.y0:.0f}-{region.y1:.0f}, "
                    f"crop y={bbox.y0:.0f}-{bbox.y1:.0f}) — the top edge was "
                    f"raised past figure content")
    # Whichever way the caption was read, the crop has to hold the content that
    # reading was based on. A crop that does not is wrong no matter how the
    # classification got there — one misread put the crop on a 30x30 piece of
    # unrelated art with none of the figure in it, and nothing said a word.
    anchor = getattr(placement, "anchor", None)
    if anchor is not None and _area(anchor) > 0:
        ox = min(bbox.x1, anchor.x1) - max(bbox.x0, anchor.x0)
        oy = min(bbox.y1, anchor.y1) - max(bbox.y0, anchor.y0)
        held = max(0.0, ox) * max(0.0, oy) / _area(anchor)
        if held < ANCHOR_MIN_COVER:
            where = "beside" if placement.side else "above"
            return (f"the crop holds {held * 100:.0f}% of the content the "
                    f"caption was read against ({where} it, "
                    f"x={anchor.x0:.0f}-{anchor.x1:.0f}, "
                    f"y={anchor.y0:.0f}-{anchor.y1:.0f}) — it is cropping "
                    f"something the figure detection never looked at")
    # Everything above measures UNDER-coverage, so a crop that reaches too far
    # UP is structurally uncatchable by any of it — over-reach RAISES coverage.
    # These two close that side. Both were reproduced on a real paper where
    # every bucket read zero and two of seven crops were wrong.
    for hy0, hy1, txt in (headers or ()):
        if bbox.y0 <= hy0 + 1 and bbox.y1 >= hy1 - 1:
            return (f"the running page header ({txt[:40]!r}) is inside the crop "
                    f"— the top edge reached above the figure")
    if page is not None:
        n = prose_chars_in(page, bbox)
        if n > MAX_PROSE_CHARS:
            return (f"{n} characters of body-size text inside the crop — the "
                    f"top edge has reached into a paragraph")
    # Last, so a crop that also swallowed a paragraph or a running head is
    # still reported by the cause that explains the most about it.
    caps = list(captions or ())
    if caption_rect is not None and not any(e[-1] is caption_rect for e in caps):
        caps.append((None, None, caption_rect))
    hit = caption_in_crop(bbox, caps)
    if hit:
        raw, cap = hit
        named = f" for {raw!r}" if raw else ""
        return (f"{CAPTION_IN_CROP_TAG}the caption{named} (y={cap.y0:.0f}-"
                f"{cap.y1:.0f}, x={cap.x0:.0f}-{cap.x1:.0f}) overlaps the crop "
                f"(y={bbox.y0:.0f}-{bbox.y1:.0f}, x={bbox.x0:.0f}-"
                f"{bbox.x1:.0f}) — the caption will be in the PNG")
    # Weakest signal, so it is reported only when nothing else explains the
    # crop: the reading of where this caption's figure sits is not one to rely
    # on. The two ways that happens read differently and say so.
    kind = getattr(placement, "ambiguous", "")
    if kind:
        read_as = ("beside the caption" if placement.side
                   else "above the caption")
        scores = (f"side {placement.side_score:.2f} vs bottom "
                  f"{placement.bottom_score:.2f}")
        if kind == "contested":
            other = "above it" if placement.side else "beside it"
            return (f"{CAPTION_AMBIGUOUS_TAG}read as {read_as} ({scores}), "
                    f"but the content {other} has nearly as good a claim — "
                    f"check this crop is the right part of the page")
        return (f"{CAPTION_AMBIGUOUS_TAG}read as {read_as} on thin evidence "
                f"({scores}; nothing else on the page contests it) — check "
                f"this crop is the right part of the page")
    return ""


# Figure references in prose — "Figure 4 shows…", "see Figs. 1 and 2",
# "Figure 3a", "Supplementary Figure 2". Deliberately the LOOSE counterpart
# of CAP_RE: no caption-shape lookahead, plural keyword allowed, panel
# letters ignored. It exists to answer one question — "does the body text
# mention a figure number no caption was found for?" — which is the only
# cheap signal that detection was PARTIAL. Nothing else in the pipeline can
# tell 3-of-4 from 4-of-4: the batch report counts PDFs with *zero*
# captions, and downstream both the figure glob and the unused-figure
# diagnostic walk whatever files exist, so a missing figure is missing
# everywhere consistently and looks exactly like a paper with fewer figures.
#
# The number alternation uses the same `LABEL_SEP` the caption side does, so
# a book numbering its figures `Figure 1–14` has its references read the same
# way its captions are. Mismatched classes here are not cosmetic: the caption
# scan would record `1-14` while this one recorded `1`, and every figure in
# the document would appear in the PARTIAL bucket as "cited, no caption" —
# noise on the one signal that has no other witness.
REF_RE = re.compile(
    r'((?i:Supplementary|Suppl?\.|Extended\s+Data))?\s*'
    r'(?i:Figures|Figure|Figs\.?|Fig\.?)\s+'
    r'(SI\d+(?:' + LABEL_SEP + r'\d+)*'
    r'|S\d+(?:' + LABEL_SEP + r'\d+)*'
    r'|[A-Z]' + LABEL_SEP + r'?\d+(?:' + LABEL_SEP + r'\d+)*'
    r'|\d+(?:' + LABEL_SEP + r'\d+)*)'
)
#: The tail of a multi-figure reference: "Figures 1 and 2", "Figs. 1, 2, 3",
#: "Figures 1–3". Scanned from the end of a REF_RE match.
#:
#: The separator is its OWN group. It used to be non-capturing, and the caller
#: read it off `m2.group(0)` — the whole match, number included — so the range
#: test compared "to 8" against "to" and never fired: "Figures 6 to 8" and
#: "Figs. 1–3" recorded only their endpoints. Every figure named only by the
#: inside of a range was therefore absent from `caption_coverage`'s reference
#: set, which is the one signal in this pipeline that a detection was PARTIAL.
REF_MORE_RE = re.compile(r'\s*(,|&|and|to|[–—-])\s*(\d+(?:' + LABEL_SEP + r'\d+)*)')


def _normalize_ref(marker, label):
    if marker:
        prefix = MARKER_TO_PREFIX.get(_normalize_marker(marker), "S")
        if not label.startswith(prefix):
            label = prefix + label
    return label


#: Widest ASCII-hyphen range that reads as a range rather than a typo — the
#: same bound `REF_MORE_RE`'s en-dash expansion uses.
MAX_RANGE_SPAN = 20


def _uses_hyphen_labels(labels):
    """True when any caption in this document spells its label with a hyphen.

    One hyphenated caption anywhere makes `Figure 4-6` in the prose a
    chapter-style label for this document, not a range.
    """
    return any("-" in str(lab) for lab in labels or ())


def hyphen_range_members(label, hyphenated):
    """['4', '5', '6'] for '4-6' read as a range, or [] when it is a label.

    `REF_RE`'s number alternation is greedy over `[.-]\\d+`, so the commonest
    spelling of a figure range — `Figures 4-6`, with an ASCII hyphen — is
    captured whole as one chapter-style label. `REF_MORE_RE`'s range expansion
    never sees it, so `4-6` matched no caption and never could, while figures
    4, 5 and 6 went unrecorded as referenced: a guaranteed false PARTIAL, on
    the one signal in this pipeline that has no other witness.

    A hyphen inside a label is genuinely ambiguous — `Figure 4-2` is Géron's
    chapter-figure form — so three things have to hold before it reads as a
    range, and all three fail on a real chapter label:

      * both sides are plain integers (`4-2` qualifies, `A-1` and `1-2-3` do not);
      * the span ascends and is narrow (`0 < B - A <= MAX_RANGE_SPAN`), which
        `4-2` fails outright;
      * NO caption in this document uses a hyphenated label. A book that
        numbers its figures `4-2` is a book where `4-6` is a figure, and the
        caption side is the authority on which kind of document this is.
    """
    if hyphenated or not isinstance(label, str) or label.count("-") != 1:
        return []
    lo_s, hi_s = label.split("-")
    if not (lo_s.isdigit() and hi_s.isdigit()):
        return []
    lo, hi = int(lo_s), int(hi_s)
    if not 0 < hi - lo <= MAX_RANGE_SPAN:
        return []
    return [str(v) for v in range(lo, hi + 1)]


def find_figure_references(doc, page_idxs=None, caption_labels=None):
    """Every figure label the body text refers to → {label: mentions}.

    Labels are normalized exactly like caption labels (supplementary markers
    folded to the configured prefix), so the result is directly comparable
    with what `detect_figures` found.

    `caption_labels` is the labels the caption scan found in this document; it
    decides whether a hyphenated reference is a range or a label (see
    `hyphen_range_members`). Callers that already have them pass them in —
    `caption_coverage` does — and the labels are scanned here when they don't.
    """
    out = {}
    if page_idxs is None:
        page_idxs = range(len(doc))
    page_idxs = list(page_idxs)
    if caption_labels is None:
        caption_labels = [n for i in page_idxs
                          for n, _, _ in find_caption_blocks(doc[i])]
    hyphenated = _uses_hyphen_labels(caption_labels)

    def record(marker, label):
        # ASCII first, and BEFORE `hyphen_range_members` sees it. That helper
        # keys off `label.count("-")`, so an en-dash reference reaching it
        # unnormalized counts zero hyphens and is never considered as a range
        # — which is how `Figures 1–3` in a paper that numbers plainly would
        # have stopped recording figure 2 the moment `LABEL_SEP` began
        # capturing the whole span as one label.
        label = normalize_label(label)
        lab = _normalize_ref(marker, label)
        out[lab] = out.get(lab, 0) + 1
        # The literal is recorded above whatever happens next, so a document
        # that really does label figures `4-6` still matches its own caption.
        #
        # An en-dash span now reaches here as a whole label too (`LABEL_SEP`),
        # where it used to arrive as its low endpoint with `REF_MORE_RE`
        # expanding the rest. That is why the two spellings had to be given
        # ONE answer rather than each keeping its own: they are now the same
        # code path, and the ASCII one is the answer that leaves every
        # document without an en-dash label reporting exactly as before.
        for member in hyphen_range_members(label, hyphenated):
            mlab = _normalize_ref(marker, member)
            out[mlab] = out.get(mlab, 0) + 1

    for i in page_idxs:
        text = doc[i].get_text()
        for m in REF_RE.finditer(text):
            record(m.group(1), m.group(2))
            # "Figures 1 and 2" / "Figs. 1–3": keep consuming labels.
            pos, prev = m.end(), m.group(2)
            while True:
                m2 = REF_MORE_RE.match(text, pos)
                if not m2:
                    break
                sep = m2.group(1)
                nxt = m2.group(2)
                if sep in ("-", "–", "—", "to") and prev.isdigit() and nxt.isdigit():
                    lo, hi = int(prev), int(nxt)
                    if 0 < hi - lo <= 20:            # a range: 1–3 means 1,2,3
                        for v in range(lo + 1, hi + 1):
                            lab = _normalize_ref(m.group(1), str(v))
                            out[lab] = out.get(lab, 0) + 1
                        pos, prev = m2.end(), nxt
                        continue
                record(m.group(1), nxt)
                pos, prev = m2.end(), nxt
    return out


def caption_coverage(doc, found_labels, page_idxs=None):
    """(referenced, missing) — figure labels the text cites vs. captions found.

    `missing` is every label the body text refers to that no caption
    matched. It is evidence, not proof: a paper legitimately cites figures
    from other works ("Fig. 3 of Smith et al."), and a book chapter cites
    figures from other chapters. But a *silent* 3-of-4 is the failure this
    exists to make visible, and the alternative is no signal at all.

    The captions found are passed on to `find_figure_references` as well: they
    are what decides whether this document spells figure labels with hyphens,
    and therefore whether `Figures 4-6` in its prose is one chapter-style label
    or a range over three of them.
    """
    found = set(found_labels)
    referenced = find_figure_references(doc, page_idxs,
                                       caption_labels=found_labels)
    hyphenated = _uses_hyphen_labels(found)
    missing = []
    for k in sorted(referenced):
        if k in found:
            continue
        members = hyphen_range_members(k, hyphenated)
        if members and all(x in found for x in members):
            continue      # "4-6" cited, captions 4, 5 and 6 all present
        missing.append(k)
    return referenced, missing


def detect_figures(doc, page_idxs=None):
    """Programmatic entrypoint: detect every figure in a PDF document.

    This is the API used by `batch_extract.py` so the batch wrapper doesn't
    have to shell out and parse text output. The `main()` CLI below is kept
    for interactive single-PDF use and uses the same logic.

    Args:
        doc: an open fitz.Document.
        page_idxs: optional iterable of 0-indexed page numbers to restrict
            scanning to. None means scan every page.

    Yields:
        Tuples of (page_idx, fig_num, raw_label, bbox, cap_rect,
        suspicious_reason).
            - `fig_num` is the normalized label (with S prefix folded in
              for supplementary forms) — what the filename uses.
            - `raw_label` is the source caption form (e.g., "Figure S1",
              "Supplementary Figure 1", "Extended Data Figure 1") for
              diagnostics.
            - `bbox` is a `fitz.Rect` ready to pass into
              `page.get_pixmap(clip=...)` — i.e. in the page's DISPLAYED
              space, already mapped through `page.rotation_matrix` on a
              `/Rotate`d page (see `content_rect`). Detection itself runs in
              unrotated content space, where the text and drawing coordinates
              live; the crossing happens here, once, for both rects.
            - `cap_rect` is the caption block's own `fitz.Rect` — needed
              when hand-building a fallback crop, since the caption's
              edges anchor the figure on the opposite side. Same space as
              `bbox`, so the two stay comparable.
            - `suspicious_reason` is an empty string for normal-looking
              bboxes; a short diagnostic ("width 35 < 80", "degenerate
              rect 0x0 …", "covers 45% of the … figure region …") when the
              bbox failed the sanity check.
    """
    if page_idxs is None:
        page_idxs = range(len(doc))
    _headers = header_bands(doc)
    for i in page_idxs:
        page = doc[i]
        caps = find_caption_blocks(page)
        if not caps:
            continue
        # bbox_for_figure operates on (fig_num, rect) pairs for the
        # "neighboring captions" disambiguation. Re-pack the captions in
        # that shape (dropping raw_label, which it doesn't need).
        caps_for_bbox = [(fig_num, rect) for fig_num, _, rect in caps]
        text_blocks = collect_text_rects(page)
        for fig_num, raw_label, cap_rect in caps:
            diag = {}
            bbox = bbox_for_figure(page, cap_rect, caps_for_bbox, text_blocks,
                                   diag=diag)
            if bbox is None:
                continue
            # `suspicious` compares the bbox against text spans, header bands
            # and caption rects, all of which are unrotated — so it runs
            # BEFORE the crossing, not after.
            reason = suspicious(bbox, diag.get("region"), page, cap_rect,
                                _headers, caps, diag.get("placement"))
            yield (i, fig_num, raw_label, to_page_space(page, bbox),
                   to_page_space(page, cap_rect), reason)


def open_pdf(path):
    """Open a PDF, exiting with a one-line message instead of a traceback.

    Covers the two failure shapes that show up when a folder of downloads
    is pointed at these scripts: a file that isn't a PDF at all (truncated
    download, HTML error page saved with a .pdf extension) and a PDF with
    zero pages. Both are reported for what they are — neither is an OCR
    problem, which is what a bare "no text found" would imply.
    """
    try:
        doc = fitz.open(path)
    except Exception as e:
        sys.exit(f"{path}: could not open as a PDF ({e})")
    # PyMuPDF opens HTML, XPS and EPUB natively, so a saved error page or a
    # truncated download named `.pdf` opens without raising and reads as a
    # perfectly good text-bearing document — one with no figure captions in it.
    # `batch_extract.py` has always had this guard; without it here, the
    # single-PDF path reported "no captions found" and sent the user hunting
    # for an unusual caption style in a file that is not a PDF at all.
    if not doc.is_pdf:
        fmt = (doc.metadata or {}).get("format") or "an unknown format"
        sys.exit(f"{path}: not a PDF — opened as {fmt} (an HTML error page or "
                 f"a truncated download saved with a .pdf extension)")
    if len(doc) == 0:
        sys.exit(f"{path}: PDF has zero pages — nothing to scan")
    return doc


# ---------------------------------------------------------------------------
# self-test
# ---------------------------------------------------------------------------
#
# `python3 auto_fig_bbox.py --test`.
#
# Every fixture is built INSIDE a function. `tests/test_conventions.py`'s
# `check_scripts_run` imports this module and fails it for anything computed at
# module scope, and a table of synthetic pages is exactly the thing that grows
# into one. The documents are synthesised in memory with PyMuPDF; the only
# files written are inside a `tempfile` directory that is removed again.
#
# What this covers, and why each part is here rather than trusted:
#   * `CAP_RE` — every accepted caption style in references/review-and-repair.md's label table AND every
#     rejection class (prose references, panel pointers, plurals). The regex is
#     the whole detector: a style it misses is a figure that is missing from
#     `Sources/Images/` with nothing anywhere reporting a shortfall.
#   * label normalisation — the marker fold that decides the FILENAME.
#   * `suspicious()` including both over-reach checks, on real pages.
#   * `find_frame_rect` on a publisher frame and on a matplotlib axes box —
#     they are the same shape, and only `bbox_for_figure`'s contradiction
#     guard tells them apart.


def _st_frame(page, x0, y0, x1, y1):
    """Draw four line strokes forming a closed rectangle."""
    for a, b in (((x0, y0), (x1, y0)), ((x0, y1), (x1, y1)),
                 ((x0, y0), (x0, y1)), ((x1, y0), (x1, y1))):
        page.draw_line(fitz.Point(*a), fitz.Point(*b))


def _st_simple_doc(caption="Figure 1. A synthetic caption."):
    """Prose, a drawn figure, `caption` below it, prose below that."""
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((72, 90), "Prose above the figure, one line of it.",
                     fontsize=10)
    page.draw_rect(fitz.Rect(100, 200, 500, 400), fill=(0.3, 0.4, 0.8))
    page.insert_text((100, 430), caption, fontsize=9)
    page.insert_text((72, 470), "Prose below the caption, one line of it.",
                     fontsize=10)
    return doc


def _st_framed_doc():
    """A publisher-style framed figure: every mark inside the frame."""
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    _st_frame(page, 90, 150, 520, 380)
    page.draw_rect(fitz.Rect(150, 200, 400, 340), fill=(0.2, 0.4, 0.8))
    page.insert_text((160, 360), "inside label", fontsize=7)
    page.insert_text((90, 400), "Figure 2-1. A framed figure.", fontsize=9)
    return doc, fitz.Rect(90, 150, 520, 380)


def _st_axes_doc():
    """A matplotlib axes box: same four strokes, tick labels OUTSIDE them."""
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    _st_frame(page, 150, 150, 500, 330)
    page.draw_rect(fitz.Rect(200, 200, 300, 320), fill=(0.8, 0.2, 0.2))
    for i, x in enumerate(range(160, 500, 80)):
        page.insert_text((x, 342), "%d" % (i * 10), fontsize=7)
    page.insert_text((150, 380), "Figure 3. Matplotlib-style axes.", fontsize=9)
    return doc, fitz.Rect(150, 150, 500, 330)


def _st_header_doc(head=True, pages=4):
    """`pages` pages, each with the same running head when `head`."""
    doc = fitz.open()
    for i in range(pages):
        page = doc.new_page(width=612, height=792)
        if head:
            page.insert_text((72, 40), "JOURNAL OF SYNTHETIC RESULTS",
                             fontsize=8)
        page.insert_text((72, 120), "Body text on page %d." % (i + 1),
                         fontsize=10)
    return doc


def _st_two_column_doc():
    """A plain two-column US-Letter page: a chart and a caption in each column.

    The layout that broke `side_caption_position`: EVERY caption on a
    two-column page is narrower than half the page, so the width test admits
    all of them, and the neighbouring column's chart is a ≥30x30 drawing whose
    y-band overlaps the caption's. Figure 1's crop was then built out of
    column two — 26% of Figure 1, all of Figure 2 and Figure 2's caption text,
    with nothing flagged.

    Figure 2's chart deliberately starts ABOVE Figure 1's caption and ends
    just inside its band, which is what the neighbouring column does and what
    a figure a caption really sits beside never does.
    """
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    for k in range(4):
        page.insert_text((60, 90 + 12 * k),
                         "Left column body prose line %d here." % k, fontsize=9)
        page.insert_text((317, 90 + 12 * k),
                         "Right column body prose line %d." % k, fontsize=9)
    page.draw_rect(fitz.Rect(70, 200, 290, 330), fill=(0.2, 0.4, 0.8))
    page.insert_text((60, 350), "Figure 1. The left column figure caption,",
                     fontsize=8)
    page.insert_text((60, 360), "which wraps onto a second line here.",
                     fontsize=8)
    page.draw_rect(fitz.Rect(320, 240, 550, 370), fill=(0.8, 0.3, 0.2))
    page.insert_text((317, 390), "Figure 2. The right column figure caption,",
                     fontsize=8)
    page.insert_text((317, 400), "also wrapping to a second line.", fontsize=8)
    for k in range(6):
        page.insert_text((60, 430 + 12 * k),
                         "More left column prose line %d." % k, fontsize=9)
        page.insert_text((317, 430 + 12 * k),
                         "More right column prose line %d." % k, fontsize=9)
    return doc


def _st_rotated_doc(rotation):
    """The same page every time, carrying `/Rotate <rotation>`.

    Everything about it is unrotated: `get_drawings()` and `get_text("dict")`
    answer in content space whatever `/Rotate` says. Only `page.rect` and
    `get_pixmap(clip=...)` follow the rotation, which is what made a rotated
    page crop somewhere else entirely on the sheet.
    """
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((72, 100), "Prose above the figure on a rotated page.",
                     fontsize=10)
    page.draw_rect(fitz.Rect(100, 200, 500, 400), fill=(0.2, 0.4, 0.8))
    page.draw_circle(fitz.Point(300, 300), 60, color=(1, 0, 0), width=3)
    page.insert_text((100, 430), "Figure 1. A figure on a rotated page.",
                     fontsize=9)
    page.insert_text((72, 470), "Prose below the caption line.", fontsize=10)
    if rotation:
        page.set_rotation(rotation)
    return doc


def _st_a4_doc():
    """An A4 page (595x842) whose caption sits at y0=761.

    Inside the text area of most A4 journal styles, and 1pt below the absolute
    `FOOTER_Y = 760` that was tuned for US Letter: the caption was dropped
    before `find_caption_blocks` ever saw the block, the figure was never
    extracted, and the run exited 0. Every fixture in all four suites is
    612x792, where an absolute bound and a page-relative one are the same
    number, so nothing could see it.
    """
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.draw_rect(fitz.Rect(80, 600, 500, 750), fill=(0.25, 0.5, 0.35))
    page.insert_text((80, 770), "Figure 1. A caption in an A4 text area.",
                     fontsize=9)
    return doc


def _st_prose_doc():
    """Six lines of body prose above a figure, then the caption."""
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    line = ("Ordinary body prose that a crop reaching above the figure "
            "would swallow whole.")
    for k in range(6):
        page.insert_text((72, 100 + 14 * k), line, fontsize=10)
    page.draw_rect(fitz.Rect(100, 250, 500, 400), fill=(0.3, 0.3, 0.9))
    page.insert_text((100, 430), "Figure 1. Over-reaching crop.", fontsize=9)
    return doc


def _st_bleed_doc():
    """A page-sized bleed rectangle, a small figure, a caption, and prose.

    The shape a page-layout tool leaves behind: a background rect drawn past
    every trim edge on every page. Alberts, *Essential Cell Biology* emits
    (-36,-36)-(633,813) on a 597x777 page. It is not figure content, and one
    of them is enough to make every crop on the page full-bleed.
    """
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.draw_rect(fitz.Rect(-36, -36, 648, 828), fill=(1, 1, 1))
    # A figure in the LEFT column only; body prose in the right column is what
    # a page-wide crop would swallow.
    page.draw_rect(fitz.Rect(72, 200, 260, 380), fill=(0.2, 0.5, 0.8))
    page.insert_text((72, 400), "Figure 1. A left-column figure.", fontsize=9)
    for k in range(8):
        page.insert_text((330, 210 + 14 * k),
                         "Body prose in the neighbouring column.", fontsize=10)
    return doc


def run_self_test():
    """Run the built-in cases; print `N/M self-test cases pass`, return 0/1."""
    import shutil
    import tempfile

    state = {"n": 0, "bad": 0}

    def check(label, got, want):
        state["n"] += 1
        if got != want:
            state["bad"] += 1
            print("FAIL %s -> %r, expected %r" % (label, got, want))

    def ok(label, cond):
        state["n"] += 1
        if not cond:
            state["bad"] += 1
            print("FAIL %s" % label)

    # --- CAP_RE: every accepted style in references/review-and-repair.md's label table ------------------
    # (caption text, expected marker group, expected label group)
    for text, marker, label in (
            ("Figure 7. Title", None, "7"),
            ("Figure 1.2. Title", None, "1.2"),
            ("Figure 1-2. Title", None, "1-2"),
            ("Figure 1.2.4. Title", None, "1.2.4"),
            ("Figure A.1. Title", None, "A.1"),
            ("Figure A1. Title", None, "A1"),
            ("Figure S1. Title", None, "S1"),
            ("Figure S2-3. Title", None, "S2-3"),
            ("Figure SI1. Title", None, "SI1"),
            ("Supplementary Figure 1. Title", "Supplementary", "1"),
            ("Suppl. Figure 1. Title", "Suppl.", "1"),
            ("Supp. Figure 1. Title", "Supp.", "1"),
            ("Supplementary Fig. 1. Title", "Supplementary", "1"),
            ("Extended Data Figure 1. Title", "Extended Data", "1"),
            ("Figure 1: Title goes here", None, "1"),          # Nature colon
            ("Figure 1—Title goes here", None, "1"),           # tight em-dash
            ("Figure 1–Title goes here", None, "1"),           # tight en-dash
            ("Figure 1 — Title goes here", None, "1"),         # spaced em-dash
            ("FIGURE 1. Title", None, "1"),                    # older IEEE
            ("FIG. 1. Title", None, "1"),
            ("Fig 1. Title", None, "1"),                       # no period
            ("figure 1. lowercase keyword", None, "1"),
            ("Supplementary figure 1. Title", "Supplementary", "1"),
            ("Figure 1-23", None, "1-23"),                     # label, then EOL
            ("Figure 10.1 Invariance and equivariance", None, "10.1"),
            ("Figure 10.2 1D convolution with kernel size three", None, "10.2"),
            ("Extended  Data Figure 4. Doubled space", "Extended  Data", "4"),
            # EN DASH between two digits is a label separator, not the
            # punctuation before a title. Alberts/Norton science texts number
            # every figure this way, and reading the dash as a title marker
            # collapsed all 43 captions in one chapter to the label `1`.
            # The label group keeps the source spelling; `normalize_label`
            # converts it on the way to a filename.
            ("Figure 1–14 Cells come in a variety of shapes", None, "1–14"),
            ("Figure 1–1", None, "1–1"),                      # label, then EOL
            ("Figure 1–2. With a period", None, "1–2"),
            ("Figure S1–3. Supplementary, en-dashed", None, "S1–3"),
    ):
        m = CAP_RE.search(text)
        state["n"] += 1
        if not m:
            state["bad"] += 1
            print("FAIL CAP_RE rejected the caption %r" % text)
        elif (m.group(1), m.group(2)) != (marker, label):
            state["bad"] += 1
            print("FAIL CAP_RE %r -> marker %r label %r, expected %r / %r"
                  % (text, m.group(1), m.group(2), marker, label))

    # --- CAP_RE: every rejection class ------------------------------------
    # A caption-shaped prefix is not a caption. Matching one crops a figure
    # out of the middle of a paragraph and files it under a label that
    # belongs to a real figure elsewhere.
    for text in (
            "Figure 1 shows an example of overfitting",       # prose
            "Figure 1  shows an example of overfitting",      # PDF spacing
            "Figure 1\t shows an example of overfitting",
            "Figure 1-24 illustrates the gradient",           # prose
            "figure 1 shows the same thing in lower case",    # prose
            "Figure 1a. Panel pointer",                       # panel letter
            "Figure 1A. Panel pointer",
            "Figure 10.5a–b shows both panels",               # panel range
            "Figure S1A. Supplementary panel",
            "Figures 1 and 2 show the two conditions",        # plural
            "Figs. 1 and 2 show the two conditions",          # plural, abbrev
            "Figure S1a. Lowercase supplementary panel",
            "figure s1. lowercase s is prose, not a label",
            "Figure one. Spelled-out numbers are not labels",
            "as shown in Figure 1. The reference is mid-line",
            # The en dash must not turn prose into captions. These are the
            # exact shapes an en-dash-numbered book puts in its body text.
            "Figure 1–2 shows the central dogma",             # prose
            "As shown in Figure 1–6B and Figure 1–7A",        # panel pointer
            "Figures 1–3 and 1–4 show the same thing",        # plural
    ):
        state["n"] += 1
        if CAP_RE.search(text):
            m = CAP_RE.search(text)
            state["bad"] += 1
            print("FAIL CAP_RE accepted the non-caption %r (as %r)"
                  % (text, m.group(2)))

    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((72, 90), "Figure 1  shows the result discussed below.")
    page.draw_rect(fitz.Rect(90, 200, 470, 400), fill=(0.2, 0.3, 0.7))
    page.insert_text((90, 440), "Figure 1. The actual caption.")
    found = list(detect_figures(doc))
    check("PDF prose spacing cannot introduce a second caption",
          [row[1] for row in found], ["1"])
    ok("the detected caption belongs to the actual chart",
       len(found) == 1 and found[0][4].y0 > 400
       and found[0][3].y0 <= 200 and found[0][3].y1 >= 400)
    doc.close()

    # --- label normalisation, through the function that names the file ----
    def label_of(caption):
        doc = _st_simple_doc(caption)
        found = find_caption_blocks(doc[0])
        doc.close()
        return found[0][0] if found else None

    check("Supplementary Figure 1", label_of("Supplementary Figure 1. T"), "S1")
    check("Suppl. Figure 2", label_of("Suppl. Figure 2. T"), "S2")
    check("Supp. Fig. 3", label_of("Supp. Fig. 3. T"), "S3")
    check("Extended Data Figure 4 (default)",
          label_of("Extended Data Figure 4. T"), "S4")
    check("Figure S5 (no doubled prefix)", label_of("Figure S5. T"), "S5")
    check("Figure SI1 (its own namespace)", label_of("Figure SI1. T"), "SI1")
    check("Figure A.1", label_of("Figure A.1. T"), "A.1")
    check("Figure 1.2 (dots kept here; the filename converts them)",
          label_of("Figure 1.2. T"), "1.2")
    # `extract_figures.normalize_fig_num` is what turns that into `1-2`; the
    # two halves are tested in the file that owns each.
    #
    # The en dash does NOT survive into the label, because the label becomes a
    # filename and CONVENTIONS.md §1b requires those to be ASCII. This is the
    # assertion that keeps `_fig_1–14.png` off disk, where its two Unicode
    # normalization forms would compare unequal between the file and the note
    # citing it, silently.
    #
    # Asserted on the composition `find_caption_blocks` performs
    # (`normalize_label(m.group(2))`) rather than through `label_of`, because
    # the synthetic page CANNOT CARRY AN EN DASH: `_st_simple_doc` writes with
    # a base-14 Helvetica, whose Latin-1 encoding substitutes U+2013 with
    # `·` (U+00B7). A `label_of("Figure 1–14 …")` here reads back as
    # `Figure 1·14` and returns None — a fixture artifact that would look
    # exactly like the regex failing. The real end-to-end path is exercised
    # against a real en-dash-numbered PDF; what belongs in a self-test with no
    # fixtures on disk is the two halves, each where it can actually be seen.
    _en = CAP_RE.search("Figure 1–14 Cells come in a variety of shapes")
    check("Figure 1–14 (en dash normalised to a hyphen)",
          normalize_label(_en.group(2)) if _en else None, "1-14")
    _en = CAP_RE.search("Figure S1–3. T")
    check("Figure S1–3 (en dash normalised, prefix kept)",
          normalize_label(_en.group(2)) if _en else None, "S1-3")
    check("normalize_label leaves an ASCII label alone",
          normalize_label("1-14"), "1-14")
    check("normalize_label leaves a dotted label alone",
          normalize_label("10.5"), "10.5")
    state["n"] += 1
    if any(ord(c) > 127 for c in normalize_label("1–14")):
        state["bad"] += 1
        print("FAIL an en-dash label reached the filename layer non-ASCII")
    state["n"] += 1
    doc = _st_simple_doc("Supplementary Figure 1. T")
    raw = find_caption_blocks(doc[0])[0][1]
    doc.close()
    if raw != "Supplementary Figure 1":
        state["bad"] += 1
        print("FAIL raw_label -> %r, expected 'Supplementary Figure 1' (the "
              "collision report shows this, so it must be the source form)"
              % raw)

    # `--ed-prefix ED`, which is the whole reason the mapping is configurable.
    saved = dict(MARKER_TO_PREFIX)
    try:
        configure_marker_prefix("Extended Data", "ED")
        check("Extended Data Figure 4 (--ed-prefix ED)",
              label_of("Extended Data Figure 4. T"), "ED4")
        check("Supplementary Figure 4 is unaffected by --ed-prefix",
              label_of("Supplementary Figure 4. T"), "S4")
        check("configure_marker_prefix normalises its key",
              MARKER_TO_PREFIX.get("extended data"), "ED")
    finally:
        MARKER_TO_PREFIX.clear()
        MARKER_TO_PREFIX.update(saved)
    check("the default mapping is restored",
          MARKER_TO_PREFIX.get("extended data"), "S")
    check("_normalize_marker folds case and whitespace",
          _normalize_marker("Extended  DATA "), "extended data")

    # --- a caption PyMuPDF merged into the block above it ------------------
    # `finditer`, not `match`: the caption is on the block's SECOND line here,
    # which is what a merged axis label produces, and anchoring at offset 0
    # loses the figure with no count anywhere disagreeing.
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.draw_rect(fitz.Rect(100, 200, 500, 380), fill=(0.4, 0.4, 0.4))
    page.insert_text((100, 400), "0    10    20    30", fontsize=7)
    page.insert_text((100, 412), "Figure 9. Merged into the axis label above.",
                     fontsize=7)
    found = find_caption_blocks(page)
    check("a caption on the block's second line is found",
          [f[0] for f in found], ["9"])
    if found:
        ok("the caption rect starts at the caption line, not the axis label "
           "(%.1f > 400)" % found[0][2].y0, found[0][2].y0 > 400)
    else:
        state["n"] += 1
        state["bad"] += 1
    doc.close()

    # --- two captions in one block, and one label twice --------------------
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((72, 300), "Figure 4. First caption.", fontsize=8)
    page.insert_text((72, 312), "Figure 5. Second caption.", fontsize=8)
    check("two captions in one block", [f[0] for f in find_caption_blocks(page)],
          ["4", "5"])
    doc.close()

    check("_line_index picks the containing line",
          [_line_index([0, 10, 25], off) for off in (0, 9, 10, 24, 25, 99)],
          [0, 0, 1, 1, 2, 2])
    check("union(None, r)", union(None, fitz.Rect(1, 2, 3, 4)),
          fitz.Rect(1, 2, 3, 4))
    check("union(r, None)", union(fitz.Rect(1, 2, 3, 4), None),
          fitz.Rect(1, 2, 3, 4))
    check("union of two rects",
          union(fitz.Rect(0, 0, 10, 10), fitz.Rect(5, 5, 20, 6)),
          fitz.Rect(0, 0, 20, 10))

    # --- degenerate ------------------------------------------------------
    check("degenerate: inverted rect", degenerate(fitz.Rect(100, 100, 50, 50)),
          True)
    check("degenerate: zero height", degenerate(fitz.Rect(0, 0, 100, 0)), True)
    check("degenerate: a real rect", degenerate(fitz.Rect(0, 0, 100, 100)),
          False)

    # --- suspicious(): the dimensional floor -------------------------------
    check("suspicious: a healthy bbox",
          suspicious(fitz.Rect(0, 0, 400, 300)), "")
    ok("suspicious: too narrow",
       suspicious(fitz.Rect(0, 0, MIN_BBOX_WIDTH - 1, 300)).startswith("width"))
    ok("suspicious: too short",
       suspicious(fitz.Rect(0, 0, 400, MIN_BBOX_HEIGHT - 1)).startswith("height"))
    ok("suspicious: too small in area",
       suspicious(fitz.Rect(0, 0, 90, 70)).startswith("area"))
    ok("suspicious: degenerate first",
       suspicious(fitz.Rect(100, 100, 50, 50)).startswith("degenerate"))

    # --- suspicious(): under-coverage of the figure region -----------------
    region = fitz.Rect(100, 200, 500, 420)
    ok("suspicious: a crop covering the bottom third of the region",
       "covers 32%" in suspicious(fitz.Rect(100, 350, 500, 420), region))
    check("suspicious: a crop covering the whole region",
          suspicious(fitz.Rect(100, 195, 500, 425), region), "")

    # --- suspicious(): the two over-reach checks ---------------------------
    # Both were added because every under-coverage bucket read zero on a paper
    # where two of seven crops had reached into the page above the figure.
    hdoc = _st_header_doc(True)
    bands = header_bands(hdoc)
    check("header_bands on a doc with a running head",
          [t for _, _, t in bands], ["JOURNAL OF SYNTHETIC RESULTS"])
    ok("the band sits in the page's top strip",
       bool(bands) and bands[0][0] < header_y(hdoc[0]) and bands[0][1] > 30)
    hdoc.close()
    ndoc = _st_header_doc(False)
    check("header_bands on a doc with no running head", header_bands(ndoc), [])
    ndoc.close()
    sdoc = _st_header_doc(True, pages=2)
    check("header_bands needs at least three pages", header_bands(sdoc), [])
    sdoc.close()
    ok("suspicious: the running head is inside the crop",
       "running page header" in suspicious(
           fitz.Rect(60, 25, 520, 420), None, None, None, bands))
    check("suspicious: the crop stops below the running head",
          suspicious(fitz.Rect(60, 60, 520, 420), None, None, None, bands), "")

    pdoc = _st_prose_doc()
    ppage = pdoc[0]
    ok("prose_chars_in counts a swallowed paragraph (%d > %d)"
       % (prose_chars_in(ppage, fitz.Rect(60, 80, 520, 420)), MAX_PROSE_CHARS),
       prose_chars_in(ppage, fitz.Rect(60, 80, 520, 420)) > MAX_PROSE_CHARS)
    check("prose_chars_in on a crop holding only the figure",
          prose_chars_in(ppage, fitz.Rect(90, 240, 510, 410)), 0)
    ok("suspicious: body text inside the crop",
       "characters of body-size text" in suspicious(
           fitz.Rect(60, 80, 520, 420), None, ppage))
    check("suspicious: a crop holding only the figure",
          suspicious(fitz.Rect(90, 240, 510, 410), None, ppage), "")
    pdoc.close()

    # --- a page-sized bleed rect is the sheet, not a figure -----------------
    # Without the `PAGE_COVER_SHARE` filter this one rect decides everything:
    # `figure_content_span` clusters it with the real figure (it touches every
    # cluster), so the "figure region" is the page, the union bbox is the
    # page, and the crop carries the neighbouring prose column. That is not a
    # near miss on one figure — it is every figure on every page of the book,
    # and it surfaces only as a wall of "the top edge has reached into a
    # paragraph" warnings describing a symptom two layers downstream.
    bdoc = _st_bleed_doc()
    bpage = bdoc[0]
    rects = collect_content_rects(bpage)
    ok("the bleed rect is not collected as content",
       not any(r.width >= bpage.rect.width * PAGE_COVER_SHARE
               and r.height >= bpage.rect.height * PAGE_COVER_SHARE
               for r in rects))
    ok("...and the real figure still is",
       any(abs(r.x0 - 72) < 2 and abs(r.x1 - 260) < 2 for r in rects))
    bcaps = find_caption_blocks(bpage)
    check("the bleed page yields exactly one caption", len(bcaps), 1)
    bbox = bbox_for_figure(bpage, bcaps[0][2], [(n, r) for n, _, r in bcaps],
                           collect_text_rects(bpage))
    ok("the crop stays in the figure's own column (x1=%.0f, prose at 330)"
       % bbox.x1, bbox.x1 < 330)
    check("...so no body prose is inside it", prose_chars_in(bpage, bbox), 0)
    # A full-page RASTER is a legitimate full-bleed photograph and must not be
    # filtered: the rule is about vector paths, and this is the assertion that
    # keeps a later tightening from taking the photographs with it.
    idoc = fitz.open()
    ipage = idoc.new_page(width=612, height=792)
    ipix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 8, 8), False)
    ipix.clear_with(128)
    ipage.insert_image(fitz.Rect(0, 0, 612, 792), pixmap=ipix)
    ok("a full-page raster survives the filter",
       any(r.width > 612 * PAGE_COVER_SHARE for r in collect_content_rects(ipage)))
    idoc.close()
    bdoc.close()

    # --- find_frame_rect: a publisher frame and a matplotlib axes box ------
    # The same four strokes. `find_frame_rect` cannot tell them apart and is
    # not asked to; `bbox_for_figure` does, below.
    fdoc, frame = _st_framed_doc()
    check("find_frame_rect on a publisher frame",
          find_frame_rect(fdoc[0], header_y(fdoc[0]), 395), frame)
    adoc, axes = _st_axes_doc()
    check("find_frame_rect on a matplotlib axes box",
          find_frame_rect(adoc[0], header_y(adoc[0]), 375), axes)
    check("find_frame_rect above the frame finds nothing",
          find_frame_rect(fdoc[0], header_y(fdoc[0]), 140), None)
    check("find_frame_rect on a page with no strokes at all",
          find_frame_rect(_st_simple_doc()[0], HEADER_Y_MAX, 400), None)

    ndoc = fitz.open()
    npage = ndoc.new_page(width=612, height=792)
    _st_frame(npage, 200, 150, 200 + MIN_FRAME_WIDTH - 10, 300)
    check("find_frame_rect refuses a frame under MIN_FRAME_WIDTH",
          find_frame_rect(npage, header_y(npage), 400), None)
    ndoc.close()
    ndoc = fitz.open()
    npage = ndoc.new_page(width=612, height=792)
    _st_frame(npage, 100, 150, 500, 150 + MIN_FRAME_HEIGHT - 10)
    check("find_frame_rect refuses a frame under MIN_FRAME_HEIGHT",
          find_frame_rect(npage, header_y(npage), 400), None)
    ndoc.close()

    # --- the frame / inner_text contradiction guard ------------------------
    def bbox_of(doc):
        page = doc[0]
        caps = find_caption_blocks(page)
        blocks = collect_text_rects(page)
        return bbox_for_figure(page, caps[0][2],
                               [(n, r) for n, _, r in caps], blocks)

    saved_strip = _STRIP_FRAME
    try:
        configure_strip_frame(True)
        got = bbox_of(fdoc)
        check("a publisher frame is used, cropped just inside the strokes",
              tuple(round(v, 1) for v in got),
              (frame.x0 + FRAME_STRIP_INSET, frame.y0 + FRAME_STRIP_INSET,
               frame.x1 - FRAME_STRIP_INSET, frame.y1 - FRAME_STRIP_INSET))
        configure_strip_frame(False)
        got = bbox_of(fdoc)
        check("--keep-frame crops just outside the strokes",
              tuple(round(v, 1) for v in got),
              (frame.x0 - FRAME_PAD, frame.y0 - FRAME_PAD,
               frame.x1 + FRAME_PAD, frame.y1 + FRAME_PAD))
        configure_strip_frame(True)
        # The axes box is the same shape, but the tick labels the detector
        # already classified as figure content sit OUTSIDE it. That is a
        # contradiction, so the frame is not the figure's boundary — and the
        # crop has to keep the tick row it would otherwise have thrown away.
        got = bbox_of(adoc)
        ok("a matplotlib axes box is rejected as a frame (%.1f > %.1f)"
           % (got.y1, axes.y1), got.y1 > axes.y1 + 5)
        ok("the tick labels stay inside the crop", got.x0 < axes.x0)
    finally:
        configure_strip_frame(saved_strip)
    check("configure_strip_frame restored", _STRIP_FRAME, saved_strip)
    fdoc.close()
    adoc.close()

    # --- side captions -----------------------------------------------------
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.draw_rect(fitz.Rect(300, 200, 560, 400), fill=(0.5, 0.5, 0.5))
    page.insert_text((60, 300), "Figure 6. Beside it.", fontsize=8)
    caps = find_caption_blocks(page)
    check("a narrow caption with content to its right is a left caption",
          side_caption_position(page, caps[0][2]), "left")
    doc.close()
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((60, 300), "Figure 6. Nothing beside it.", fontsize=8)
    caps = find_caption_blocks(page)
    check("a narrow caption with nothing beside it is a bottom caption",
          side_caption_position(page, caps[0][2]), None)
    doc.close()
    doc = _st_simple_doc("Figure 1. A caption wide enough to span the page "
                         "from the left margin to the right one, as most are.")
    caps = find_caption_blocks(doc[0])
    check("a page-width caption is a bottom caption",
          side_caption_position(doc[0], caps[0][2]), None)
    doc.close()

    # --- two-column pages are not side captions ----------------------------
    # Every caption on a two-column page is narrower than half the page, so the
    # width test admits all of them and the neighbouring column's chart is
    # "content beside the caption". The crop was then built from the other
    # column: Figure 1's PNG held 26% of Figure 1, all of Figure 2, and Figure
    # 2's caption text -- silently, with 0 flagged and exit 0.
    doc = _st_two_column_doc()
    page = doc[0]
    caps = find_caption_blocks(page)
    check("both columns' captions are found", [c[0] for c in caps], ["1", "2"])
    cap1, cap2 = caps[0][2], caps[1][2]
    ok("a two-column caption IS under half the page wide (%.0f < %.0f) -- the "
       "width test alone cannot tell it from a side caption"
       % (cap1.width, page.rect.width * 0.5),
       cap1.width < page.rect.width * 0.5)
    ok("...and the other column DOES have a >=30x30 drawing across its y-band",
       any(r.width >= 30 and r.height >= 30 and r.x0 > cap1.x1
           and r.y1 >= cap1.y0 and r.y0 <= cap1.y1
           for r in collect_content_rects(page)))
    check("the left column's caption is not read as a side caption",
          side_caption_position(page, cap1, [cap2]), None)
    check("...nor the right column's", side_caption_position(page, cap2, [cap1]),
          None)
    got = {g[1]: g for g in detect_figures(doc)}
    b1 = got["1"][3]
    ok("Figure 1's crop keeps Figure 1's own chart (x0 %.0f <= 70, y0 %.0f "
       "<= 200)" % (b1.x0, b1.y0), b1.x0 <= 70 and b1.y0 <= 200)
    check("...and no caption is inside it",
          caption_in_crop(b1, caps), None)
    # BOTH edges, because only one of them was fixed and a one-sided
    # assertion hid the other. The left edge came out of the neighbouring
    # column (it used to start at x=205, inside Figure 2); the right edge
    # still runs to the page margin, because the bottom-caption path searches
    # the full page width and clamping THAT is a different change with a
    # different blast radius (it moves crops on ordinary single-column
    # papers). So the neighbour's picture is still inside this crop, and only
    # the neighbour's CAPTION is caught. SKILL.md says so in as many words;
    # this pins the shape so the day it changes, it changes deliberately.
    page_mid = page.rect.width / 2
    check("Figure 1's crop is measured on both edges: left edge in its own "
          "column, right edge still at the page margin (the documented limit "
          "of the bottom-caption path on a multi-column page)",
          (b1.x0 < page_mid, b1.x1 > page_mid), (True, True))
    doc.close()

    # A caption whose own column really is beside its figure still reads as a
    # side caption when ANOTHER caption sits on the figure's side -- no, it
    # does not: that other caption is what owns the content over there.
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.draw_rect(fitz.Rect(300, 200, 560, 400), fill=(0.5, 0.5, 0.5))
    page.insert_text((60, 300), "Figure 6. Beside it.", fontsize=8)
    page.insert_text((320, 430), "Figure 7. Under the same content.", fontsize=8)
    caps = find_caption_blocks(page)
    by_num = {n: r for n, _, r in caps}
    check("a caption on the figure's side disqualifies the side reading",
          side_caption_position(page, by_num["6"], [by_num["7"]]), None)
    check("...and with no such caption it is a side caption again",
          side_caption_position(page, by_num["6"], []), "left")
    doc.close()

    # Content that only CLIPS the caption's band on the way past is weak
    # evidence — and weak evidence has to lose gracefully, not be vetoed.
    # Vetoing it is what cost five working layouts: the same predicate that
    # rejects this rejects a caption whose first line sits above its figure's
    # top edge, a caption taller than its figure, and a caption with a
    # decorative mark above it. So the reading is taken (it is the only one
    # with any content behind it — the alternative here is a blank crop of the
    # empty page above the caption) and reported as ambiguous.
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.draw_rect(fitz.Rect(320, 240, 550, 350), fill=(0.8, 0.3, 0.2))
    page.insert_text((60, 350), "Figure 5. A column-width caption whose band",
                     fontsize=8)
    page.insert_text((60, 360), "the chart in the next column only clips.",
                     fontsize=8)
    caps = find_caption_blocks(page)
    ok("the neighbour does reach into the caption's y-band",
       any(r.x0 > caps[0][2].x1 and r.y1 >= caps[0][2].y0
           and r.y0 <= caps[0][2].y1 for r in collect_content_rects(page)))
    place = caption_placement(page, caps[0][2])
    ok("content that only clips the band is weak evidence (side %.2f < %.2f)"
       % (place.side_score, PLACEMENT_CONFIDENT),
       0 < place.side_score < PLACEMENT_CONFIDENT)
    ok("...so the placement is reported as ambiguous rather than decided in "
       "silence", place.ambiguous)
    got = list(detect_figures(doc))
    ok("...and the figure is flagged for it",
       got and got[0][5].startswith(CAPTION_AMBIGUOUS_TAG))
    doc.close()

    # The two-column shape that geometry beside the caption cannot settle:
    # the next column's chart covers this caption's band completely, and so
    # would a figure a top-aligned side caption belongs to. What decides it is
    # on the caption's OWN side — its figure, directly above it.
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.draw_rect(fitz.Rect(70, 200, 290, 330), fill=(0.2, 0.4, 0.8))
    page.draw_rect(fitz.Rect(320, 240, 550, 370), fill=(0.8, 0.3, 0.2))
    page.insert_text((60, 350), "Figure 5. A caption with its own figure",
                     fontsize=8)
    page.insert_text((60, 360), "above it and another column beside it.",
                     fontsize=8)
    caps = find_caption_blocks(page)
    cap5 = caps[0][2]
    ok("the neighbour covers the whole of this caption's band, so the shape "
       "alone cannot tell it from a top-aligned side caption",
       any(r.x0 > cap5.x1
           and min(r.y1, cap5.y1) - max(r.y0, cap5.y0) >= cap5.height
           for r in collect_content_rects(page)))
    ok("...and the caption has a figure of its own directly above it",
       _bottom_evidence(cap5, collect_content_rects(page))[1] > 0.5)
    check("a caption with its own figure above it is a bottom caption",
          side_caption_position(page, cap5), None)
    place = caption_placement(page, cap5)
    ok("...on the scores, not a veto (side %.2f vs bottom %.2f)"
       % (place.side_score, place.bottom_score),
       place.bottom_score > 0.35 and place.side_score > 0.35)
    ok("...and a decision that close is reported as ambiguous, not taken in "
       "silence", place.ambiguous)
    # ...and with that figure gone, the same page reads as a side caption:
    # the disqualifier is the figure above, not the caption's shape.
    doc2 = fitz.open()
    page2 = doc2.new_page(width=612, height=792)
    page2.draw_rect(fitz.Rect(320, 240, 550, 370), fill=(0.8, 0.3, 0.2))
    page2.insert_text((60, 350), "Figure 5. A caption with its own figure",
                      fontsize=8)
    page2.insert_text((60, 360), "above it and another column beside it.",
                      fontsize=8)
    caps2 = find_caption_blocks(page2)
    check("...and without it, the same caption reads as a side caption",
          side_caption_position(page2, caps2[0][2]), "left")
    doc2.close()
    doc.close()

    # --- a side caption is aligned with its figure, not centred on it -------
    # `SIDE_BALANCE_MIN = 0.3` required the caption to sit in the middle of
    # the figure's band. On a figure spanning y=200..430 only captions
    # starting between 260 and 360 survived it — the middle 55% — and every
    # other position fell through to the bottom-caption branch, whose crop is
    # then the empty sliver above the caption. That renders white, so the
    # blank-crop guard refused to write it: two real side-caption figures
    # became `0 extracted, 2 blank crop`.
    for cap_y0 in (200, 220, 240, 260, 300, 340, 360, 380, 400):
        doc = fitz.open()
        page = doc.new_page(width=612, height=792)
        page.draw_rect(fitz.Rect(300, 200, 560, 430), fill=(1, 0, 0))
        page.insert_text((60, cap_y0 + 9),
                         "Figure 6. A side caption beside the figure",
                         fontsize=8)
        page.insert_text((60, cap_y0 + 19), "it belongs to.", fontsize=8)
        caps = find_caption_blocks(page)
        check("a side caption at y0=%d (figure y=200-430) is a side caption"
              % cap_y0, side_caption_position(page, caps[0][2]), "left")
        got = list(detect_figures(doc))
        ok("...and its crop covers the figure, not the gap above the caption "
           "(y=%.0f-%.0f)" % (got[0][3].y0, got[0][3].y1),
           got[0][3].y0 <= 200 and got[0][3].y1 >= 430)
        doc.close()
    # A caption whose first line sits ABOVE the figure's top edge, which is
    # where captions normally start. A hard band-coverage floor rejected it
    # (it shares 57% of its band with the figure, not 90%) and the crop became
    # the empty sliver above the caption.
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.draw_rect(fitz.Rect(300, 200, 560, 430), fill=(1, 0, 0))
    page.insert_text((60, 199), "Figure 12. A side caption starting just",
                     fontsize=8)
    page.insert_text((60, 209), "above the figure's top edge.", fontsize=8)
    caps = find_caption_blocks(page)
    check("a caption starting above its figure's top edge is still a side "
          "caption", side_caption_position(page, caps[0][2]), "left")
    got = list(detect_figures(doc))
    ok("...and its crop is the figure, not the gap above the caption",
       got[0][3].y0 <= 200 and got[0][3].y1 >= 430)
    doc.close()

    # A caption TALLER than the figure it sits beside — the layout side
    # captions exist for. Measured against the caption's own height, coverage
    # could never reach its threshold, so the taller the caption the more
    # certainly it was rejected: at 101pt beside a 100pt figure it passed, at
    # 111pt it did not.
    scores = {}
    for n_lines in (2, 6, 11, 16, 26):
        doc = fitz.open()
        page = doc.new_page(width=612, height=792)
        page.draw_rect(fitz.Rect(300, 200, 560, 300), fill=(1, 0, 0))
        # Only the FIRST line is a caption opener; the rest are its
        # continuation. (A fixture whose every line began "Figure 13." was no
        # fixture at all: `find_caption_blocks` de-duplicates a label repeated
        # inside one block, so the caption rect came back one line tall
        # however many lines were drawn, and the caption was never taller than
        # the figure at any setting.)
        page.insert_text((60, 209), "Figure 13. A caption longer than the",
                         fontsize=8)
        for k in range(1, n_lines):
            page.insert_text((60, 209 + 10 * k),
                             "figure it sits beside, line %d." % k, fontsize=8)
        caps = find_caption_blocks(page)
        cap = caps[0][2]
        check("a caption %.0fpt tall beside a 100pt figure is a side caption"
              % cap.height, side_caption_position(page, cap), "left")
        scores[n_lines] = caption_placement(page, cap).side_score
        got = list(detect_figures(doc))
        ok("...and its crop holds the figure (y=%.0f-%.0f)"
           % (got[0][3].y0, got[0][3].y1),
           got[0][3].y0 <= 200 and got[0][3].y1 >= 300)
        doc.close()
    # The scores have to be EQUAL, not merely all above the line. Measured
    # against the caption's own height, confidence falls as the caption grows
    # — so the same layout gets less certain the more the author wrote, and at
    # some length flips. Measured against the shorter of the two bands, a
    # caption that spans its figure's band is a caption that spans its
    # figure's band, at any height.
    ok("a tall caption and a short one beside the same figure score alike "
       "(%s)" % ", ".join("%.2f" % scores[k] for k in sorted(scores)),
       max(scores.values()) - min(scores.values()) < 0.02
       and min(scores.values()) > PLACEMENT_CONFIDENT)

    # A second figure lower down the page, with an ordinary bottom caption
    # that happens to start past the page midline. It has nothing to do with
    # this caption, and "any other caption on the figure's side" blanked this
    # figure entirely because of it. Ownership is what matters: does that
    # caption sit directly UNDER the content this reading is based on.
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.draw_rect(fitz.Rect(300, 150, 560, 380), fill=(1, 0, 0))
    page.insert_text((60, 169), "Figure 14. A side caption beside", fontsize=8)
    page.insert_text((60, 179), "the figure to its right.", fontsize=8)
    page.draw_rect(fitz.Rect(320, 480, 560, 620), fill=(0, 0.5, 0))
    page.insert_text((320, 649), "Figure 15. An ordinary bottom caption",
                     fontsize=8)
    caps = find_caption_blocks(page)
    by_num = {n: r for n, _, r in caps}
    check("an unrelated caption past the midline does not kill the side "
          "reading", side_caption_position(page, by_num["14"],
                                           [by_num["15"]]), "left")
    check("_caption_owns: a caption directly under the content",
          _caption_owns(by_num["15"], fitz.Rect(320, 480, 560, 620)), True)
    check("_caption_owns: a caption far below it",
          _caption_owns(by_num["15"], fitz.Rect(300, 150, 560, 380)), False)
    got = {g[1]: g for g in detect_figures(doc)}
    ok("...so Figure 14 is extracted from beside its caption",
       got["14"][3].y0 <= 150 and got["14"][3].x0 >= 200)
    doc.close()

    # A decorative mark above the caption in its own column. As a veto this
    # made the caption a bottom caption, and the crop then landed ON THE MARK
    # — a picture of unrelated art with none of the figure in it and nothing
    # flagged. Scored, a 40x40 mark cannot outweigh a quarter-page chart.
    for gap in (20, 40, 60, 80):
        doc = fitz.open()
        page = doc.new_page(width=612, height=792)
        page.draw_rect(fitz.Rect(300, 200, 560, 430), fill=(1, 0, 0))
        page.draw_rect(fitz.Rect(60, 260 - gap, 100, 300 - gap), fill=(0, 0, 0))
        page.insert_text((60, 309), "Figure 16. A side caption with a mark",
                         fontsize=8)
        page.insert_text((60, 319), "above it.", fontsize=8)
        caps = find_caption_blocks(page)
        check("a %dpt-away decorative mark does not outweigh the figure "
              "beside it" % gap, side_caption_position(page, caps[0][2]),
              "left")
        got = list(detect_figures(doc))
        ok("...and the crop is the figure, not the mark (x0 %.0f > 200)"
           % got[0][3].x0, got[0][3].x0 > 200)
        doc.close()

    # The same class of layout, but with the art big enough to WIN: a small
    # figure beside the caption and a table above it in the caption's own
    # column. The bottom reading takes it and the crop is the table — the
    # right answer is not recoverable from the geometry, and the crop is
    # wrong. What must not happen is it being wrong in silence.
    #
    # This is what `PLACEMENT_CONTESTED` is for, and at the 0.35 it shipped
    # with the clause was dead: the two readings score on disjoint content, so
    # they rarely both run high, and across 319 figures exactly one had both
    # above 0.2. At 0.02 every silently-wrong crop of this shape is flagged,
    # nothing else in that corpus gains a flag, and no crop moves.
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.draw_rect(fitz.Rect(300, 300, 560, 337), fill=(1, 0, 0))    # the figure
    page.draw_rect(fitz.Rect(60, 105, 280, 280), fill=(0.85, 0.85, 0.85))  # a table
    page.insert_text((60, 329), "Figure 17. A side caption with a", fontsize=8)
    page.insert_text((60, 339), "table above it.", fontsize=8)
    caps = find_caption_blocks(page)
    place = caption_placement(page, caps[0][2])
    ok("both readings have some evidence (side %.2f, bottom %.2f)"
       % (place.side_score, place.bottom_score),
       min(place.side_score, place.bottom_score) >= PLACEMENT_CONTESTED)
    ok("...and neither is anywhere near confident — this is the band the old "
       "0.35 threshold could not see",
       max(place.side_score, place.bottom_score) < PLACEMENT_CONFIDENT
       and min(place.side_score, place.bottom_score) < 0.35)
    check("...so the placement is contested, not merely thin",
          place.ambiguous, "contested")
    got = list(detect_figures(doc))
    ok("...and the figure is flagged rather than cropped in silence",
       got[0][5].startswith(CAPTION_AMBIGUOUS_TAG))
    ok("...with a reason that says the other reading has a claim, and does "
       "not claim thin evidence", "nearly as good a claim" in got[0][5])
    doc.close()

    # The two clauses have to read differently: one fired while the message
    # described the other, printing "there is content above it with almost as
    # good a claim" next to `bottom 0.00` — there was no content above at all.
    thin = _Placement(side="left", ambiguous="thin", side_score=0.41,
                      bottom_score=0.0)
    contested = _Placement(side=None, ambiguous="contested", side_score=0.20,
                           bottom_score=0.44)
    r_thin = suspicious(fitz.Rect(0, 0, 400, 300), None, None, None, None,
                        None, thin)
    r_cont = suspicious(fitz.Rect(0, 0, 400, 300), None, None, None, None,
                        None, contested)
    ok("a thin reading says so", "thin evidence" in r_thin)
    check("...and does not claim a rival that scored zero",
          "nearly as good a claim" in r_thin, False)
    ok("a contested reading names the rival", "nearly as good a claim" in r_cont)
    check("...and does not call itself thin", "thin evidence" in r_cont, False)
    check("both carry the tag the batch report buckets on",
          (r_thin.startswith(CAPTION_AMBIGUOUS_TAG),
           r_cont.startswith(CAPTION_AMBIGUOUS_TAG)), (True, True))

    # ...and the threshold must not become a blanket flag: an ordinary
    # bottom-caption page has no side evidence at all, and stays quiet.
    doc = _st_simple_doc("Figure 1. An ordinary caption.")
    got = list(detect_figures(doc))
    check("an ordinary bottom caption is not flagged as ambiguous",
          got[0][5], "")
    ok("...because the side reading scores nothing at all",
       caption_placement(doc[0], find_caption_blocks(doc[0])[0][2])
       .side_score == 0.0)
    doc.close()

    # ...and the backstop that catches this class however the reading goes:
    # a crop holding none of the content the classification was based on.
    place = _Placement(side="left", anchor=fitz.Rect(300, 200, 560, 430))
    ok("suspicious: the crop holds none of the content it was read against",
       "the content the caption was read against" in suspicious(
           fitz.Rect(40, 200, 140, 300), None, None, None, None, None, place))
    check("suspicious: a crop that does hold it",
          suspicious(fitz.Rect(290, 190, 570, 440), None, None, None, None,
                     None, place), "")

    # The mirror image, which is the half of the docstring's promise that no
    # fixture covered: caption on the RIGHT, figure to the LEFT.
    for cap_y0 in (200, 400):
        doc = fitz.open()
        page = doc.new_page(width=612, height=792)
        page.draw_rect(fitz.Rect(52, 200, 312, 430), fill=(0, 0, 1))
        page.insert_text((360, cap_y0 + 9),
                         "Figure 7. A side caption to the right", fontsize=8)
        page.insert_text((360, cap_y0 + 19), "of its figure.", fontsize=8)
        caps = find_caption_blocks(page)
        check("a right-hand side caption at y0=%d" % cap_y0,
              side_caption_position(page, caps[0][2]), "right")
        got = list(detect_figures(doc))
        ok("...and its crop covers the figure to its left",
           got[0][3].y0 <= 200 and got[0][3].y1 >= 430 and got[0][3].x0 <= 52)
        doc.close()

    # The side path's own bounds: the crop is clamped above the next caption
    # (it ran to the foot of the page, so nothing kept it off one), and the
    # region-coverage guard is given a region on this path at all (it only
    # ever got one in the bottom-caption branch, so the guard was skipped on
    # the path whose crop comes from a different column of the page).
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.draw_rect(fitz.Rect(300, 150, 560, 520), fill=(0.4, 0.6, 0.4))
    page.insert_text((60, 340), "Figure 8. Beside it.", fontsize=8)
    page.insert_text((60, 500), "Figure 9. A later caption on this page.",
                     fontsize=8)
    caps = find_caption_blocks(page)
    by_num = {n: r for n, _, r in caps}
    check("a caption centred on a tall figure IS a side caption",
          side_caption_position(page, by_num["8"], [by_num["9"]]), "left")
    diag = {}
    bb = bbox_for_figure(page, by_num["8"],
                         [(n, r) for n, _, r in caps],
                         collect_text_rects(page), diag=diag)
    ok("the side crop stops above the next caption (%.1f <= %.1f)"
       % (bb.y1, by_num["9"].y0), bb.y1 <= by_num["9"].y0)
    check("...so no caption is inside the side crop",
          caption_in_crop(bb, caps), None)
    ok("the side path reports a region for the coverage guard",
       diag.get("region") is not None)
    doc.close()

    # ...and the far edge stops at the figure's column, not at the sheet. The
    # near edge is the caption's; the far one was the page boundary, so
    # anything out there joined the crop.
    check("column_interval merges panels across a normal internal gutter",
          column_interval(fitz.Rect(300, 0, 400, 1),
                          [fitz.Rect(300, 0, 400, 1), fitz.Rect(440, 0, 560, 1)]),
          (300, 560))
    check("column_interval stops at a column gutter",
          column_interval(fitz.Rect(300, 0, 460, 1),
                          [fitz.Rect(300, 0, 460, 1), fitz.Rect(540, 0, 575, 1)]),
          (300, 460))
    # Both fixtures below put the caption at the TOP of the band and the far
    # rect BELOW it, so the far rect is not itself an anchor — the anchor is
    # the near panel alone and `column_interval` is what decides whether the
    # far one is in or out. With both rects covering the caption's band the
    # anchor union already spans them and the constant is never consulted:
    # the test passed with the gutter monkeypatched to 0, which is no test.
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.draw_rect(fitz.Rect(300, 200, 460, 430), fill=(1, 0, 0))
    page.draw_rect(fitz.Rect(540, 300, 575, 340), fill=(0, 0.6, 0))
    page.insert_text((60, 209), "Figure 10. A side caption beside its figure.",
                     fontsize=8)
    caps = find_caption_blocks(page)
    anchor = caption_placement(page, caps[0][2]).anchor
    ok("the stray mark is NOT part of the anchor, so the gutter decides "
       "(anchor x=%.0f-%.0f)" % (anchor.x0, anchor.x1), anchor.x1 <= 460)
    got = list(detect_figures(doc))
    ok("the side crop stops at the figure's column, not the page edge "
       "(x1 %.0f < 540)" % got[0][3].x1, got[0][3].x1 < 540)
    ok("...while still covering the figure itself", got[0][3].x1 >= 460)
    doc.close()
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.draw_rect(fitz.Rect(300, 200, 400, 430), fill=(1, 0, 0))
    page.draw_rect(fitz.Rect(440, 300, 560, 430), fill=(0, 0, 1))
    page.insert_text((60, 209), "Figure 11. A two-panel figure beside it.",
                     fontsize=8)
    caps = find_caption_blocks(page)
    anchor = caption_placement(page, caps[0][2]).anchor
    ok("the far panel is NOT part of the anchor either (anchor x=%.0f-%.0f), "
       "so this measures the gutter and not the anchor union"
       % (anchor.x0, anchor.x1), anchor.x1 <= 400)
    got = list(detect_figures(doc))
    ok("a multi-panel figure is not clipped at its own internal gutter "
       "(x1 %.0f >= 560)" % got[0][3].x1, got[0][3].x1 >= 560)
    doc.close()

    # --- rotated pages ------------------------------------------------------
    # `/Rotate 90` keeps three coordinate spaces apart and the module used to
    # mix them: drawings and text answer unrotated, `page.rect` is the rotated
    # rect, and `get_pixmap(clip=...)` reads the rotated one. The crop landed
    # elsewhere on the sheet -- 32% of the figure plus the caption, nothing
    # flagged, exit 0.
    base = _st_rotated_doc(0)
    base_bbox = list(detect_figures(base))[0][3]
    check("content_rect on an unrotated page is page.rect",
          content_rect(base[0]), fitz.Rect(base[0].rect))
    for rot in (90, 180, 270):
        rdoc = _st_rotated_doc(rot)
        rpage = rdoc[0]
        check("content_rect ignores /Rotate %d (%s vs page.rect %s)"
              % (rot, tuple(content_rect(rpage)), tuple(rpage.rect)),
              content_rect(rpage), fitz.Rect(0, 0, 612, 792))
        rgot = list(detect_figures(rdoc))
        check("a rotated page still finds its caption",
              [g[1] for g in rgot], ["1"])
        rb = rgot[0][3]
        check("/Rotate %d: the bbox is the unrotated one mapped through "
              "rotation_matrix" % rot,
              tuple(round(v, 1) for v in rb),
              tuple(round(v, 1) for v in
                    fitz.Rect(base_bbox) * rpage.rotation_matrix))
        ok("/Rotate %d: the bbox is inside the page as get_pixmap sees it"
           % rot,
           rb.x0 >= rpage.rect.x0 - 1 and rb.y0 >= rpage.rect.y0 - 1
           and rb.x1 <= rpage.rect.x1 + 1 and rb.y1 <= rpage.rect.y1 + 1)
        ok("/Rotate %d: the crop is the same size, transposed where it should "
           "be" % rot,
           round(rb.width, 1) == round(
               base_bbox.width if rot == 180 else base_bbox.height, 1))
        check("/Rotate %d: nothing is flagged on a clean page" % rot,
              rgot[0][5], "")
        # The caption rect crosses into the same space as the bbox, or the
        # caption check downstream compares two different coordinate systems.
        ok("/Rotate %d: the caption rect crossed over too" % rot,
           rgot[0][4].y1 <= rpage.rect.y1 + 1
           and rgot[0][4].x1 <= rpage.rect.x1 + 1)
        check("/Rotate %d: no caption is inside the crop" % rot,
              caption_in_crop(rb, [(None, None, rgot[0][4])]), None)
        rdoc.close()
    check("to_page_space is the identity without a rotation",
          to_page_space(base[0], fitz.Rect(1, 2, 3, 4)), fitz.Rect(1, 2, 3, 4))
    base.close()

    # --- page margins are per page, and relative ----------------------------
    # `FOOTER_Y = 760` was absolute and tuned for US Letter, so on A4 (842pt)
    # it discarded the bottom 82pt -- inside the text area of most A4 journal
    # styles. The caption there was never seen and the figure was never
    # extracted, with nothing anywhere disagreeing.
    a4 = _st_a4_doc()
    a4page = a4[0]
    check("A4's footer bound is below its caption (%.0f)" % footer_y(a4page),
          footer_y(a4page) > 761, True)
    check("US Letter's bounds are unchanged",
          (header_y(_st_simple_doc()[0]), footer_y(_st_simple_doc()[0])),
          (50, 760))
    caps = find_caption_blocks(a4page)
    ok("the A4 caption block sits below the old absolute bound (y0=%.1f > 760)"
       % (caps[0][2].y0 if caps else -1), bool(caps) and caps[0][2].y0 > 760)
    check("an A4 caption low in the text area is found",
          [c[0] for c in caps], ["1"])
    a4got = list(detect_figures(a4))
    check("...and its figure is extracted", [g[1] for g in a4got], ["1"])
    ok("...covering the A4 figure", bool(a4got) and a4got[0][3].y0 <= 600
       and a4got[0][3].y1 >= 749)
    a4.close()

    # --- the region the coverage guard measures against ---------------------
    # `region` was computed from the search region AFTER `top` had been raised
    # by every caption above this one -- the same raise the guard exists to
    # detect -- so `bbox.y0` could never precede `region.y0` and `cover` came
    # out 1.00 however much had been cut off.
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.draw_rect(fitz.Rect(100, 200, 500, 430), fill=(0.3, 0.4, 0.8))
    page.insert_text((100, 330), "Figure 1. A caption inside the band above.",
                     fontsize=8)
    page.insert_text((100, 460), "Figure 2. The figure this crop belongs to.",
                     fontsize=8)
    caps = find_caption_blocks(page)
    by_num = {n: r for n, _, r in caps}
    diag = {}
    bb = bbox_for_figure(page, by_num["2"], [(n, r) for n, _, r in caps],
                         collect_text_rects(page), diag=diag)
    region = diag.get("region")
    ok("the region starts at the figure's own top edge, not at the raised top "
       "(%.0f <= 200)" % (region.y0 if region else -1),
       region is not None and region.y0 <= 200)
    ok("the crop starts below it (%.0f > %.0f)"
       % (bb.y0, region.y0 if region else -1), region is not None
       and bb.y0 > region.y0 + 10)
    ok("...so the coverage guard fires",
       "covers" in suspicious(bb, region))
    doc.close()

    # --- suspicious(): caption text inside the crop -------------------------
    # `caption_rect` was accepted and never read. The only caption-overlap
    # check in the plugin lived in `extract_figures.main()`, which
    # `batch_extract.py` bypasses -- so the batch path had none at all, which
    # is why two whole classes of wrong crop wrote caption text into PNGs with
    # every bucket reading zero.
    cap_a = ("1", "Figure 1", fitz.Rect(100, 420, 400, 440))
    cap_b = ("2", "Figure 2", fitz.Rect(320, 300, 560, 320))
    ok("suspicious: the crop reaches into its own caption",
       suspicious(fitz.Rect(90, 200, 500, 430), None, None, cap_a[2])
       .startswith(CAPTION_IN_CROP_TAG))
    ok("suspicious: the crop holds ANOTHER figure's caption",
       suspicious(fitz.Rect(90, 200, 500, 410), None, None, cap_a[2],
                  None, [cap_a, cap_b]).startswith(CAPTION_IN_CROP_TAG))
    ok("...and the reason names the caption it found",
       "'Figure 2'" in suspicious(fitz.Rect(90, 200, 500, 410), None, None,
                                  cap_a[2], None, [cap_a, cap_b]))
    check("suspicious: a crop stopping 0.5pt above the caption is clean",
          suspicious(fitz.Rect(90, 200, 500, 419.5), None, None, cap_a[2],
                     None, [cap_a]), "")
    check("caption_in_crop: no overlap at all",
          caption_in_crop(fitz.Rect(90, 200, 300, 290), [cap_a, cap_b]), None)
    ok("caption_in_crop: a sliver of caption counts",
       caption_in_crop(fitz.Rect(90, 200, 500, 425), [cap_a]) is not None)

    # --- clustering and figure-internal text -------------------------------
    check("figure_content_span on no content", figure_content_span([]), None)
    check("figure_content_span keeps the bottom-most cluster",
          figure_content_span([fitz.Rect(0, 0, 10, 10),
                               fitz.Rect(0, 400, 100, 500),
                               fitz.Rect(0, 500, 120, 540)]),
          fitz.Rect(0, 400, 120, 540))
    check("figure_content_span bridges a gap inside one figure",
          figure_content_span([fitz.Rect(0, 100, 100, 150),
                               fitz.Rect(0, 150 + CONTENT_CLUSTER_GAP - 5,
                                         100, 300)]),
          fitz.Rect(0, 100, 100, 300))
    span = fitz.Rect(100, 200, 500, 400)
    check("text_block_inside_figure: prose above the figure",
          text_block_inside_figure(fitz.Rect(100, 100, 500, 180), span), False)
    check("text_block_inside_figure: a bar value label",
          text_block_inside_figure(fitz.Rect(150, 250, 300, 260), span), True)
    check("text_block_inside_figure: the next column over",
          text_block_inside_figure(fitz.Rect(520, 250, 600, 260), span), False)
    check("text_block_inside_figure: no drawings to judge against",
          text_block_inside_figure(fitz.Rect(1, 1, 2, 2), None), False)

    # `clip_content` is what keeps content that runs PAST the search region —
    # a sidebar rule from above the figure down past the caption — from
    # dragging the bbox outside it.
    check("clip_content drops what is outside and clips what straddles",
          clip_content([fitz.Rect(0, 0, 10, 10),          # above the region
                        fitz.Rect(100, 190, 500, 260),    # over the top edge
                        fitz.Rect(150, 220, 250, 240),    # inside
                        fitz.Rect(0, 600, 10, 610)],      # below the region
                       200, 400, 50, 480),
          [fitz.Rect(100, 200, 480, 260), fitz.Rect(150, 220, 250, 240)])
    check("clip_content on an empty region", clip_content([], 0, 1, 0, 1), [])

    # The header/footer strips are dropped from the text-block analysis: a
    # running head read as a text block raises the crop's top edge to just
    # below it, and a page number does the same at the bottom.
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((72, 30), "RUNNING HEAD ABOVE THE MARGIN", fontsize=8)
    page.insert_text((72, 300), "Body text in the middle of the page.",
                     fontsize=10)
    page.insert_text((72, 785), "Page 12 in the footer strip.", fontsize=8)
    check("collect_text_rects drops the header and footer strips",
          [t for _, t in collect_text_rects(page)],
          ["Body text in the middle of the page."])
    doc.close()

    # --- detect_figures, end to end ----------------------------------------
    doc = fitz.open()
    for i, cap in enumerate(("Figure 1. First.", "Supplementary Figure 2. Next.")):
        page = doc.new_page(width=612, height=792)
        page.draw_rect(fitz.Rect(100, 200, 500, 400), fill=(0.2, 0.5, 0.4))
        page.insert_text((100, 430), cap, fontsize=9)
    got = list(detect_figures(doc))
    check("detect_figures labels", [g[1] for g in got], ["1", "S2"])
    check("detect_figures pages", [g[0] for g in got], [0, 1])
    check("detect_figures flags nothing on a clean page",
          [g[5] for g in got], ["", ""])
    ok("the crop ends above the caption",
       all(g[3].y1 <= g[4].y0 for g in got))
    check("detect_figures on one page only",
          [g[1] for g in detect_figures(doc, [1])], ["S2"])
    doc.close()

    # --- references and coverage -------------------------------------------
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    for k, line in enumerate((
            "Figure 4 shows the effect, and Figs. 1 and 2 show the controls.",
            "Figures 6 to 8 are in the appendix; see Supplementary Figure 3.",
            "Extended Data Figure 9 is cited too.")):
        page.insert_text((72, 120 + 14 * k), line, fontsize=9)
    refs = find_figure_references(doc)
    for want in ("4", "1", "2", "6", "7", "8", "S3", "S9"):
        # "7" is the one that matters: it is named only by the INSIDE of the
        # range "Figures 6 to 8". A range whose middle is dropped is a figure
        # nothing cites, so `caption_coverage` cannot report it missing.
        check("find_figure_references cites %s" % want, want in refs, True)
    edoc = fitz.open()
    epage = edoc.new_page(width=612, height=792)
    # `insert_htmlbox`, not `insert_text`: the base-14 font `insert_text` uses
    # cannot carry an en-dash, and a fixture that silently substitutes one
    # would be testing a different string than the one it reads like.
    epage.insert_htmlbox(fitz.Rect(60, 100, 560, 160),
                         "See Figures 1&#8211;3 and Figs. 5, 6 &amp; 7.")
    # The literal span `1-3` is recorded alongside its members, exactly as the
    # ASCII-hyphen case below records `4-6` alongside 4, 5 and 6. It did not
    # used to be: `REF_RE` stopped at `1` and `REF_MORE_RE` consumed the rest,
    # so there was no whole-span label to record. `LABEL_SEP` admitted the en
    # dash into the label (a book numbering `Figure 1–14` is otherwise
    # undetectable), which puts both spellings on ONE code path — and a single
    # path cannot record the literal for one spelling and drop it for the
    # other. Unified on the ASCII answer, which is what every document without
    # an en-dash label was already getting.
    check("an en-dash range expands to every figure inside it",
          sorted(find_figure_references(edoc)),
          ["1", "1-3", "2", "3", "5", "6", "7"])
    edoc.close()
    edoc = fitz.open()
    epage = edoc.new_page(width=612, height=792)
    epage.insert_text((72, 120), "Figure 4-2 and Figure 9 are chapter labels.",
                      fontsize=9)
    # A HYPHEN inside a number is part of the label (`Figure 1-2` is Géron's
    # chapter-figure form), so it is never expanded as a range. That is why the
    # range test above uses an en-dash: the two are different characters and
    # the distinction is the whole reason the label pattern admits `-`.
    check("a dashed chapter label is not read as a range",
          sorted(find_figure_references(edoc)), ["4-2", "9"])
    edoc.close()

    # --- an ASCII-hyphen range: the commonest spelling there is -------------
    # `REF_RE`'s number alternation is greedy over `[.-]\d+`, so "Figures 4-6"
    # was captured whole as one chapter-style label, `REF_MORE_RE`'s range
    # expansion never ran, and the phantom "4-6" matched no caption forever
    # while 4, 5 and 6 went unrecorded as cited. A complete six-figure paper
    # reported `6 caption(s) found, 7 cited; no caption for: Fig 4-6` -- a
    # guaranteed false positive on the one signal with no other witness.
    edoc = fitz.open()
    epage = edoc.new_page(width=612, height=792)
    epage.insert_text((72, 120), "Figures 4-6 show the ablations.", fontsize=9)
    refs = find_figure_references(edoc, caption_labels=["1", "2", "3", "4",
                                                       "5", "6"])
    for want in ("4", "5", "6"):
        check("a hyphen range cites %s" % want, want in refs, True)
    check("...and the literal form is recorded too", "4-6" in refs, True)
    _, missing = caption_coverage(edoc, ["1", "2", "3", "4", "5", "6"])
    check("a complete paper citing 'Figures 4-6' is not PARTIAL", missing, [])
    _, missing = caption_coverage(edoc, ["1", "2", "3", "4", "6"])
    ok("...but a real gap inside the range still is", "5" in missing)
    # The same string in a book that numbers its figures with hyphens is a
    # label, and expanding it there would invent citations to figures 5 and 6
    # of the whole book -- the false PARTIAL, in reverse.
    check("a hyphenated caption anywhere makes it a label, not a range",
          sorted(find_figure_references(edoc, caption_labels=["4-2", "4-6"])),
          ["4-6"])
    check("hyphen_range_members: an ascending pair",
          hyphen_range_members("4-6", False), ["4", "5", "6"])
    check("hyphen_range_members: a descending chapter label",
          hyphen_range_members("4-2", False), [])
    check("hyphen_range_members: a document that uses hyphenated labels",
          hyphen_range_members("4-6", True), [])
    check("hyphen_range_members: too wide to be a range",
          hyphen_range_members("1-99", False), [])
    check("hyphen_range_members: an appendix label",
          hyphen_range_members("A-1", False), [])
    check("hyphen_range_members: a three-part label",
          hyphen_range_members("1-2-3", False), [])
    check("_uses_hyphen_labels", _uses_hyphen_labels(["1", "S2", "4-2"]), True)
    check("_uses_hyphen_labels on plain labels",
          _uses_hyphen_labels(["1", "S2", "A.1"]), False)
    edoc.close()
    referenced, missing = caption_coverage(doc, ["4", "1"])
    check("caption_coverage: what has no caption",
          missing, sorted(set(referenced) - {"4", "1"}))
    ok("caption_coverage: a partial run is visible", "2" in missing)
    doc.close()

    # --- open_pdf refuses what is not a readable PDF ------------------------
    tmp = tempfile.mkdtemp(prefix="auto-fig-bbox-selftest-")
    try:
        good = os.path.join(tmp, "Doe_Foo_2025.pdf")
        d = _st_simple_doc()
        d.save(good)
        d.close()
        state["n"] += 1
        try:
            d = open_pdf(good)
            n_pages = len(d)
            d.close()
            if n_pages != 1:
                state["bad"] += 1
                print("FAIL open_pdf on a good PDF gave %d pages" % n_pages)
        except SystemExit as exc:
            state["bad"] += 1
            print("FAIL open_pdf refused a good PDF: %s" % exc)

        html = os.path.join(tmp, "Doe_Bar_2025.pdf")
        with open(html, "w", encoding="utf-8") as fh:
            fh.write("<html><body><h1>404</h1><p>Not found.</p></body></html>")
        state["n"] += 1
        try:
            open_pdf(html)
            state["bad"] += 1
            print("FAIL open_pdf accepted an HTML page named .pdf — it reads "
                  "as a text-bearing document with no captions, which sends "
                  "the user hunting for a caption style")
        except SystemExit as exc:
            if "not a PDF" not in str(exc):
                state["bad"] += 1
                print("FAIL open_pdf on HTML said %r, expected 'not a PDF'"
                      % str(exc))

        zero = os.path.join(tmp, "Doe_Empty_2025.pdf")
        with open(zero, "wb") as fh:
            fh.write(b"%PDF-1.4\n"
                     b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
                     b"2 0 obj\n<< /Type /Pages /Kids [] /Count 0 >>\nendobj\n"
                     b"trailer\n<< /Root 1 0 R /Size 3 >>\n%%EOF\n")
        state["n"] += 1
        try:
            open_pdf(zero)
            state["bad"] += 1
            print("FAIL open_pdf accepted a zero-page PDF")
        except SystemExit as exc:
            if "zero pages" not in str(exc):
                state["bad"] += 1
                print("FAIL open_pdf on a zero-page PDF said %r" % str(exc))

        junk = os.path.join(tmp, "Doe_Junk_2025.pdf")
        with open(junk, "wb") as fh:
            fh.write(b"\x00\x01not a document at all")
        state["n"] += 1
        try:
            open_pdf(junk)
            state["bad"] += 1
            print("FAIL open_pdf accepted a file that is not a document")
        except SystemExit:
            pass
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("%d/%d self-test cases pass"
          % (state["n"] - state["bad"], state["n"]))
    return 1 if state["bad"] else 0


def main():
    p = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=__doc__,
    )
    p.add_argument("pdf", nargs="?")
    p.add_argument("--pages")
    p.add_argument("--emit", choices=["table", "extract"], default="table")
    p.add_argument("--stem", default="STEM")
    p.add_argument(
        "--keep-frame", action="store_true",
        help=(
            "Keep the publisher's figure frame (the thin rectangle around "
            "the figure in O'Reilly-style books) inside the crop. Default: "
            "crop just inside the frame strokes so the frame doesn't appear "
            "in the output PNG. Must match whatever the batch run used, or "
            "a hand-set crop won't look like its neighbours."
        ),
    )
    p.add_argument(
        "--ed-prefix", default="S",
        help=(
            "Filename prefix for 'Extended Data Figure N' captions "
            "(default 'S' — collapses into supplementary). Pass 'ED' to "
            "keep Extended Data figures in a distinct namespace."
        ),
    )
    p.add_argument(
        "--coverage", action="store_true",
        help=(
            "Also report the captions found against the figure numbers the "
            "body text cites, so a partial detection (3 captions, 4 figures "
            "referenced) is visible instead of looking like a complete one."
        ),
    )
    p.add_argument("--test", action="store_true", help="run the self-test")
    args = p.parse_args()

    if args.test:
        return run_self_test()
    if not args.pdf:
        p.error("give a PDF path, or --test")

    # Same wiring batch_extract.py does, so a single-PDF debugging run
    # reproduces the batch run's labels and crops exactly.
    configure_marker_prefix("Extended Data", args.ed_prefix)
    configure_strip_frame(not args.keep_frame)

    pdf_path = os.path.expanduser(args.pdf)
    doc = open_pdf(pdf_path)
    if args.pages:
        page_idxs = []
        for tok in args.pages.split(","):
            tok = tok.strip()
            if not tok:
                continue
            try:
                idx = int(tok) - 1
            except ValueError:
                sys.exit(f"--pages: {tok!r} is not an integer page number")
            if idx < 0 or idx >= len(doc):
                sys.exit(
                    f"--pages: page {tok} out of range "
                    f"(PDF has {len(doc)} pages)"
                )
            page_idxs.append(idx)
    else:
        page_idxs = None
    n_warn = 0
    n_skipped = 0
    crop_lines = []
    found_labels = []
    for i, fig_num, raw_label, bbox, cap_rect, reason in detect_figures(doc, page_idxs):
        found_labels.append(fig_num)
        if reason:
            n_warn += 1
            print(
                f"# WARN page {i+1} Fig {fig_num} ({raw_label!r}): bbox looks wrong "
                f"({reason}) — likely auto-detect failure, please render "
                f"this page and set the crop manually.",
                file=sys.stderr,
            )
        if args.emit == "extract":
            # A degenerate rect would abort extract_figures.py on its
            # "degenerate rect" guard and take the whole pasted batch with
            # it, so leave it out of the command entirely. The WARN line
            # above already names the page and label to fix by hand.
            if degenerate(bbox):
                n_skipped += 1
                continue
            crop_lines.append(
                f'    --crop "{i+1}:{fig_num}:'
                f'{bbox.x0:.0f},{bbox.y0:.0f},{bbox.x1:.0f},{bbox.y1:.0f}"'
            )
        else:
            # Table mode also prints the caption rect — useful when
            # constructing a manual fallback crop, since the caption's
            # edges anchor the figure on the opposite side.
            print(
                f"page {i+1:>3}  Fig {fig_num:>6}  "
                f"bbox x={bbox.x0:6.1f}-{bbox.x1:6.1f} y={bbox.y0:6.1f}-{bbox.y1:6.1f}  "
                f"cap x={cap_rect.x0:6.1f}-{cap_rect.x1:6.1f} y={cap_rect.y0:6.1f}-{cap_rect.y1:6.1f}  "
                f"raw={raw_label!r}"
            )

    if args.emit == "extract":
        # One runnable command. Every line except the last carries the
        # continuation backslash — a trailing backslash on the final line
        # would leave the shell waiting at a PS2 prompt after a paste.
        # The --out path is a placeholder; it names itself as one, and every
        # other part of the line is runnable as printed.
        if not crop_lines:
            print(
                "# No usable figure crops detected — nothing to run.",
                file=sys.stderr,
            )
        else:
            # The current interpreter and a full path, because this text is pasted into a
            # shell whose working directory is normally the vault: macOS ships
            # no `python` binary at all, and a bare `extract_figures.py`
            # resolves to nothing there (SKILL.md's own invocation rule). The
            # sibling script is found from this file, so a plugin installed
            # anywhere emits a command that runs.
            extract_py = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "extract_figures.py")
            lines = [
                f"{shlex.quote(sys.executable)} {shlex.quote(extract_py)} {shlex.quote(pdf_path)}",
                f"    --out {shlex.quote(OUT_PLACEHOLDER)} "
                f"--stem {shlex.quote(args.stem)}",
            ] + crop_lines
            print(" \\\n".join(lines))

    if n_skipped:
        print(
            f"# {n_skipped} figure(s) omitted from the command (degenerate "
            f"bbox) — set those crops by hand.",
            file=sys.stderr,
        )
    if n_warn:
        print(
            f"# {n_warn} figure(s) flagged above — re-check those before "
            f"running extract_figures.py.",
            file=sys.stderr,
        )

    if args.coverage:
        referenced, missing = caption_coverage(doc, found_labels, page_idxs)
        print(
            f"# coverage: {len(set(found_labels))} caption(s) found, "
            f"{len(referenced)} figure number(s) cited in the body text.",
            file=sys.stderr,
        )
        if missing:
            print(
                "# CITED BUT NO CAPTION FOUND: "
                + ", ".join(f"Fig {m}" for m in missing)
                + " — the caption may have been clipped away by the page-margin "
                  "bounds (one low in the text area of a tall page), the "
                  "caption style may be one the regex misses, or those figures "
                  "may live in another document. Detection is PARTIAL until "
                  "you have checked which.",
                file=sys.stderr,
            )


if __name__ == "__main__":
    # `sys.exit(main())`, not a bare call: `--test` reports failure through the
    # exit code, and a self-test whose exit code is always 0 is a self-test no
    # harness can read.
    sys.exit(main())
