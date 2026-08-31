"""Crop figures from a PDF using user-specified rectangles, then trim white margins.

Each --crop spec is "PAGE:FIG_NUM:x0,y0,x1,y1":
  - PAGE     : 1-indexed page number
  - FIG_NUM  : the source's figure number (e.g. "2.1", "S1", "S2-3")
               — becomes the filename suffix "_fig_2-1", "_fig_S1", etc.
               Dots are normalized to dashes; dashes are preserved.
  - x0..y1   : bounding rectangle in PDF POINTS (origin top-left)

**Points, not pixels.** `render_page.py` writes its preview at 100 DPI, so a
coordinate read off that image is in pixels and must be scaled by 72/DPI —
0.72 at the default 100 DPI — before it goes in a --crop spec. (Render with
`--dpi 72` and the two are the same number.) Getting this wrong is not an
error, it is a crop of the wrong part of the page: a 612pt-wide US Letter
page is 850px wide at 100 DPI, so pixel coordinates land about 39% too far
right and too far down.

**y1 must stay above the caption.** The caption's top edge is the hard
bottom limit for a figure crop — `auto_fig_bbox.py` prints the caption rect
next to every bbox for exactly this, and a y1 below the caption's y0 puts
the caption text in the PNG, which is the one thing this skill promises it
never does. Crops that overlap a detected caption are warned about by name.

Existing files are **skipped**, matching `batch_extract.py`'s default; pass
--overwrite to replace them. Both scripts write into the same flat
`Sources/Images/` folder, so a manual fix would otherwise be silently undone by
the next batch run, or vice versa.

After cropping, each PNG is auto-trimmed to remove near-white margins on all
four sides (with `--trim-pad` pixels of breathing room). The PyMuPDF crop tends
to leave whitespace because `auto_fig_bbox.py` pads aggressively for axis labels
and panel letters that may or may not be present; the pixel-level trim cleans
that up without risk of clipping content (it only removes regions that are
literally white).

Use --no-trim to keep the raw PyMuPDF crop (e.g. for figures where surrounding
whitespace is meaningful).

This file is the ONE implementation of the `[pdf_stem]_fig_<N>.png` naming
in this plugin, and `normalize_fig_num` is the reason it has to stay that
way. It was duplicated into a second skill once; the copies drifted, the two
spelled the separator differently, and a single PDF then populated the vault
`Sources/Images/` folder twice under names that never collide and never
deduplicate. Every consumer matching the strict prefix saw half the figures
and reported nothing wrong. Do not vendor a second copy — call this one.

Usage:
    python3 extract_figures.py input.pdf \\
        --out '<vault>/Sources/Images' \\
        --stem Prince_UDL_2023_02_SupLearn_src \\
        --crop "3:2.1:70,130,300,330" \\
        --crop "4:2.2:95,130,540,510" \\
        --crop "5:S1:95,130,540,350"

    # Replace figures a batch run already wrote:
    python3 extract_figures.py input.pdf --overwrite --out ... --stem ... --crop ...

    # The adversarial fixtures this module is held to.
    python3 extract_figures.py --test

`--stem` is the source PDF's on-disk filename stem (including any `_src`
suffix it carries) — that is what `wiki-builder` globs for when it looks up
`Sources/Images/[source_stem]_fig*`.
"""
import argparse
import os
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


def parse_crop(spec):
    """Parse a "PAGE:FIG_NUM:x0,y0,x1,y1" spec; exit cleanly on malformed input."""
    parts = spec.split(":", 2)
    if len(parts) != 3:
        sys.exit(
            f"--crop {spec!r}: expected PAGE:FIG_NUM:x0,y0,x1,y1 "
            f"(three colon-separated fields, got {len(parts)})"
        )
    page_str, fig_str, rect_str = parts
    try:
        page_idx = int(page_str) - 1
    except ValueError:
        sys.exit(f"--crop {spec!r}: PAGE must be an integer, got {page_str!r}")
    # FIG_NUM is free text that becomes part of a filename
    # (`<stem>_fig_<N>.png`), so a separator or a parent hop in it targets a
    # path under `--out` — or a PyMuPDF traceback about one — instead of a
    # figure name.  Refuse it the way `--stem` is refused.  Checked on the RAW
    # label: normalization maps `.` to `-`, which would erase a `..` before
    # the guard could see it.
    for bad in ("/", "\\", "\x00"):
        if bad in fig_str:
            sys.exit(f"--crop {spec!r}: FIG_NUM {fig_str!r} contains {bad!r}: "
                     "a figure label is a filename fragment, not a path")
    if ".." in fig_str or not fig_str.strip():
        sys.exit(f"--crop {spec!r}: FIG_NUM {fig_str!r} is empty or contains "
                 "'..': a figure label is a filename fragment, not a path")
    fig_suffix = normalize_fig_num(fig_str)
    rect_tokens = rect_str.split(",")
    if len(rect_tokens) != 4:
        sys.exit(
            f"--crop {spec!r}: rect must have 4 comma-separated numbers, "
            f"got {len(rect_tokens)}"
        )
    try:
        coords = tuple(float(v) for v in rect_tokens)
    except ValueError as e:
        sys.exit(f"--crop {spec!r}: rect must contain numbers ({e})")
    return page_idx, fig_suffix, coords


def normalize_fig_num(fig_num):
    """Normalize a captured figure label into a filename-safe suffix.

    The captured label can use `.` (Prince UDL, most math/CS books), `-`
    (Géron, many O'Reilly titles), or a mix. We standardize on `-` so the
    on-disk name is predictable regardless of caption style — `Figure 1.2`,
    `Figure 1-2`, and `Figure 1 - 2` all become `_fig_1-2.png`.
    """
    return fig_num.replace(".", "-")


#: A trim keeping less than this fraction of the image is refused: the
#: background was misread, not cropped.  0.05 is far below any real margin trim
#: and far above the 0.003 a misread pale panel produced.
MIN_TRIM_KEEP = 0.05


def trim_white_margins(img_path, pad=4, tolerance=10):
    """Remove near-white margins from a PNG, leaving `pad` px of padding.

    `tolerance` is the per-channel difference from pure white (255,255,255)
    that still counts as "white" — handles antialiased edges where pixels are
    253-ish rather than exactly 255. Returns (orig_size, new_size) as
    ((w,h), (w,h)) tuples for logging.
    """
    try:
        from PIL import Image, ImageChops
    except ImportError:
        sys.exit(
            "Pillow required for --trim (default on). "
            "Use a virtual environment with the plugin dependencies "
            "(shared/RUNTIME.md), or pass --no-trim to skip cleanup."
        )

    img = Image.open(img_path)
    rgb = img.convert("RGB")
    orig_size = rgb.size  # (w, h)

    # Diff against a pure-white background; pixels within `tolerance` of white
    # become 0 (pure black after the threshold), so getbbox finds the
    # smallest rect containing real content.
    bg = Image.new("RGB", orig_size, (255, 255, 255))
    diff = ImageChops.difference(rgb, bg)
    diff = diff.point(lambda p: 255 if p > tolerance else 0)
    bbox = diff.getbbox()

    if bbox is None:
        return orig_size, orig_size  # entirely white — nothing to do

    x0, y0, x1, y1 = bbox
    w, h = orig_size
    x0 = max(0, x0 - pad)
    y0 = max(0, y0 - pad)
    x1 = min(w, x1 + pad)
    y1 = min(h, y1 + pad)

    if (x0, y0, x1, y1) == (0, 0, w, h):
        return orig_size, orig_size  # padded bbox covers whole image

    # A figure drawn on a very pale panel (#FBFBFB and lighter) is *within
    # tolerance of white*, so the whole panel reads as margin and the trim
    # keeps only whatever dark mark happens to sit on it -- a 1723x1147 figure
    # came out 79x78, and nothing in the pipeline looked at the result. A trim
    # that removes almost everything is a trim that misread the background.
    if (x1 - x0) * (y1 - y0) < MIN_TRIM_KEEP * w * h:
        return orig_size, orig_size

    cropped = img.crop((x0, y0, x1, y1))
    cropped.save(img_path)
    return orig_size, cropped.size


def render_is_blank(img_path, tolerance=10):
    """True when every pixel of `img_path` is within `tolerance` of white.

    The same predicate `trim_white_margins` reaches when its
    `diff.point(...).getbbox()` comes back None — "entirely white — nothing to
    do" — computed in one pass over the extrema instead of building two
    intermediate images, because this runs on every figure.

    Returns None when Pillow is not installed: "cannot tell", which callers
    must not read as "not blank"... except that not-blank is the only safe
    default, so they treat it as such and say nothing. `--no-trim` is the one
    path that reaches here without Pillow already being required.
    """
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        with Image.open(img_path) as im:
            bands = im.convert("RGB").getextrema()
    except OSError:
        return None
    return all(lo >= 255 - tolerance for lo, _hi in bands)


def extract_one_figure(doc, page_idx, bbox, out_path, dpi=250,
                       trim=True, trim_pad=4, trim_tolerance=10):
    """Programmatic entrypoint: crop one figure and write it to disk.

    This is the API used by `batch_extract.py`. The CLI `main()` below wraps
    this for interactive single-PDF use.

    Args:
        doc: an open fitz.Document.
        page_idx: 0-indexed page number.
        bbox: a fitz.Rect (or 4-tuple) in PDF points, top-left origin.
        out_path: destination PNG path. Parent directory must already exist.
        dpi: render resolution. 250 gives clean detail for most figures
            without exploding file sizes.
        trim: whether to remove near-white margins after the PyMuPDF crop.
            On by default because the bbox detector pads aggressively for
            axis labels and panel letters that may or may not be present.
        trim_pad: pixels of whitespace to keep around the trimmed content.
        trim_tolerance: per-channel distance from pure white that still
            counts as white (handles antialiased edges).

    Returns:
        (rendered_size, final_size, blank) — the first two (width, height)
        tuples in pixels; when `trim` is False, they are identical.

        `blank` is True when the crop rendered to nothing but white, and in
        that case **no file is written** (an existing `out_path` is left
        exactly as it was — the render happens on a temp path and is simply
        not moved into place). A caption whose figure is on the NEXT page
        produces this: `auto_fig_bbox`'s raster-only fallback synthesises a
        rect over the empty gap above the caption, and every check downstream
        passes it — big enough, no region to compare against, no header, less
        prose than the crop is wide. The one piece of code that noticed was
        `trim_white_margins` ("entirely white — nothing to do"), whose return
        value the batch caller discarded, so a 314x468 PNG of nothing was
        reported as `1 extracted, 0 suspicious, 0 failed`. Callers must not
        count a blank render as an extraction.

    Raises:
        ValueError: the bbox has no area. PyMuPDF answers a zero-area clip
            with a 1x1 PNG and an inverted one with an opaque error from
            its band writer, so both are rejected here with a message that
            names the rect.
    """
    rect = fitz.Rect(*bbox)
    if rect.width <= 0 or rect.height <= 0:
        raise ValueError(
            f"degenerate crop rect {tuple(round(v, 1) for v in rect)} "
            f"({rect.width:.1f}x{rect.height:.1f}) — nothing to render"
        )
    page = doc[page_idx]
    pix = page.get_pixmap(dpi=dpi, clip=rect)
    # Render and trim on a temp path beside the target, then os.replace into
    # place.  Writing the final path directly meant an interrupted run (a
    # closed laptop lid, a killed batch) left a truncated PNG under the real
    # figure name — and every later run's idempotent "already exists" skip
    # then preserved the corrupt file forever, as a broken embed in Obsidian.
    # Same-directory temp so the replace is atomic on one filesystem.  The
    # leading dot keeps it out of every `[stem]_fig*` glob (they anchor on the
    # stem) and out of Obsidian's file pane; the trailing `.png` stays, because
    # both PyMuPDF's save and Pillow's pick their format from the suffix.
    tmp_path = os.path.join(
        os.path.dirname(out_path) or ".",
        f".{os.path.splitext(os.path.basename(out_path))[0]}"
        f".part-{os.getpid()}.png")
    try:
        pix.save(tmp_path)
        rendered_size = (pix.width, pix.height)
        if trim:
            _, final_size = trim_white_margins(
                tmp_path, pad=trim_pad, tolerance=trim_tolerance,
            )
        else:
            final_size = rendered_size
        blank = bool(render_is_blank(tmp_path, tolerance=trim_tolerance))
        if blank:
            # Deliberately do NOT move it into place: an all-white PNG at a
            # figure's name is worse than no PNG at all — every consumer
            # embeds it, and the next run's "already exists" skip preserves it
            # forever. Leaving `out_path` untouched also means an `--overwrite`
            # re-crop that comes out blank cannot destroy the good figure that
            # is already there.
            os.remove(tmp_path)
        else:
            os.replace(tmp_path, out_path)
    except BaseException:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise
    return rendered_size, final_size, blank


# ---------------------------------------------------------------------------
# self-test
# ---------------------------------------------------------------------------
#
# `python3 extract_figures.py --test`.
#
# Every fixture is built inside a function — `tests/test_conventions.py`'s
# `check_scripts_run` imports this module and fails it for anything computed at
# module scope. Nothing is written outside a `tempfile` directory, which is
# removed again.
#
# The trim is the part worth the machinery. It is a pixel operation with no
# downstream witness: a figure trimmed to nothing is a PNG that exists, embeds,
# and is wrong, and the run that produced it reports a clean extraction.


def _st_pdf(path, width=612, height=792, caption="Figure 1. Synthetic."):
    """A one-page PDF with a drawn figure and a caption under it."""
    doc = fitz.open()
    page = doc.new_page(width=width, height=height)
    page.draw_rect(fitz.Rect(100, 150, 500, 350), fill=(0.2, 0.3, 0.7))
    page.insert_text((100, 400), caption, fontsize=9)
    doc.save(path)
    doc.close()
    return path


def _st_png(path, size, background, marks=()):
    """Write a PNG of `size` filled with `background`, plus `marks`.

    `marks` is [(box, colour)]. Pillow only — this is what the trim reads.
    """
    from PIL import Image, ImageDraw
    img = Image.new("RGB", size, background)
    if marks:
        d = ImageDraw.Draw(img)
        for box, colour in marks:
            d.rectangle(box, fill=colour)
    img.save(path)
    return path


def run_self_test():
    """Run the built-in cases; print `N/M self-test cases pass`, return 0/1."""
    import contextlib
    import io
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

    def exits(label, fn, *a, **kw):
        """Run `fn`, returning the SystemExit message (or None if it did not)."""
        state["n"] += 1
        try:
            fn(*a, **kw)
        except SystemExit as exc:
            return str(exc.code if exc.code is not None else "")
        state["bad"] += 1
        print("FAIL %s: expected a clean exit, got none" % label)
        return None

    # --- normalize_fig_num: the filename half of the naming contract -------
    for raw, want in (("7", "7"), ("1.2", "1-2"), ("1-2", "1-2"),
                      ("1.2.4", "1-2-4"), ("A.1", "A-1"), ("A1", "A1"),
                      ("S1", "S1"), ("S2-3", "S2-3"), ("SI1", "SI1"),
                      ("10.5.3", "10-5-3")):
        check("normalize_fig_num(%r)" % raw, normalize_fig_num(raw), want)

    # --- parse_crop --------------------------------------------------------
    check("parse_crop of a plain spec", parse_crop("3:2.1:70,130,300,330"),
          (2, "2-1", (70.0, 130.0, 300.0, 330.0)))
    check("parse_crop of a supplementary label", parse_crop("1:S2-3:0,0,1,1"),
          (0, "S2-3", (0.0, 0.0, 1.0, 1.0)))
    check("parse_crop keeps negatives and decimals",
          parse_crop("2:9:-1.5,0,10.25,3"),
          (1, "9", (-1.5, 0.0, 10.25, 3.0)))
    msg = exits("parse_crop with two fields", parse_crop, "3:70,130,300,330")
    ok("parse_crop names the three-field shape", msg and "three colon" in msg)
    msg = exits("parse_crop with a non-integer page", parse_crop, "x:1:1,2,3,4")
    ok("parse_crop names the bad page", msg and "PAGE must be an integer" in msg)
    msg = exits("parse_crop with three coordinates", parse_crop, "1:1:1,2,3")
    ok("parse_crop names the coordinate count", msg and "4 comma" in msg)
    msg = exits("parse_crop with a non-numeric coordinate",
                parse_crop, "1:1:a,b,c,d")
    ok("parse_crop names the bad number", msg and "must contain numbers" in msg)
    # FIG_NUM goes into the output filename, so a path-shaped label is refused
    # the way `--stem` is — it used to reach PyMuPDF as an unopenable path and
    # die with a raw traceback.
    msg = exits("parse_crop with a path-shaped label",
                parse_crop, "1:sub/../../escaped:1,2,3,4")
    ok("parse_crop says a label is not a path",
       msg and "filename fragment, not a path" in msg)
    msg = exits("parse_crop with a backslash label", parse_crop,
                "1:a\\b:1,2,3,4")
    ok("...a backslash is refused too",
       msg and "filename fragment" in msg)
    msg = exits("parse_crop with a '..' label", parse_crop, "1:..:1,2,3,4")
    ok("...'..' is refused on the RAW label, before dots become dashes",
       msg and "'..'" in msg)
    msg = exits("parse_crop with an empty label", parse_crop, "1::1,2,3,4")
    ok("...an empty label is refused", msg and "empty" in msg)
    check("...while dotted, dashed and supplementary labels still pass",
          [parse_crop("1:%s:1,2,3,4" % lab)[1]
           for lab in ("2.1", "S2-3", "A.1", "10.5.3")],
          ["2-1", "S2-3", "A-1", "10-5-3"])

    tmp = tempfile.mkdtemp(prefix="extract-figures-selftest-")
    try:
        # --- trim_white_margins -------------------------------------------
        try:
            import PIL                                          # noqa: F401
            have_pil = True
        except ImportError:
            have_pil = False
            print("SKIP: Pillow is not installed, so the trim cases were not "
                  "run. Install it with `python3 -m pip install Pillow` to "
                  "cover trim_white_margins.")
        if have_pil:
            from PIL import Image

            def size_on_disk(path):
                with Image.open(path) as im:
                    return im.size

            # (1) the ordinary case: white margins around a dark figure.
            p = _st_png(os.path.join(tmp, "trim_normal.png"), (200, 200),
                        (255, 255, 255), [((50, 60, 149, 139), (10, 20, 30))])
            check("trim: a figure with white margins",
                  trim_white_margins(p, pad=4), ((200, 200), (108, 88)))
            check("trim: the trimmed file is what is on disk",
                  size_on_disk(p), (108, 88))

            # (2) a dark background is not margin. Diffing against white makes
            # every pixel "content", so the whole image is kept.
            p = _st_png(os.path.join(tmp, "trim_dark.png"), (120, 90),
                        (18, 18, 24), [((10, 10, 40, 40), (250, 250, 250))])
            check("trim: a dark background is left alone",
                  trim_white_margins(p, pad=4), ((120, 90), (120, 90)))
            check("trim: the dark file is untouched on disk",
                  size_on_disk(p), (120, 90))

            # (3) the failure MIN_TRIM_KEEP exists for: a figure drawn on a
            # #FBFBFB panel is within tolerance of white, so the panel reads as
            # margin and the trim keeps only the one dark mark on it. A real
            # 1723x1147 figure came out 79x78 and nothing looked at it.
            p = _st_png(os.path.join(tmp, "trim_pale.png"), (400, 300),
                        (0xFB, 0xFB, 0xFB), [((20, 20, 29, 29), (0, 0, 0))])
            check("trim: a very pale panel is not trimmed away",
                  trim_white_margins(p, pad=4), ((400, 300), (400, 300)))
            check("trim: the pale panel survives on disk",
                  size_on_disk(p), (400, 300))
            # ...and the guard is a floor, not a blanket refusal: a small but
            # not absurd trim on the same pale panel still goes through.
            p = _st_png(os.path.join(tmp, "trim_pale_big.png"), (400, 300),
                        (0xFB, 0xFB, 0xFB), [((20, 20, 340, 260), (0, 0, 0))])
            ok("trim: a large mark on a pale panel still trims",
               trim_white_margins(p, pad=4)[1] != (400, 300))

            # (4) an all-white crop: nothing to find, nothing to do.
            p = _st_png(os.path.join(tmp, "trim_white.png"), (80, 60),
                        (255, 255, 255))
            check("trim: an entirely white image",
                  trim_white_margins(p, pad=4), ((80, 60), (80, 60)))
            check("trim: the white file is untouched on disk",
                  size_on_disk(p), (80, 60))

            # (5) already tight: content runs to every edge.
            p = _st_png(os.path.join(tmp, "trim_tight.png"), (100, 70),
                        (255, 255, 255), [((0, 0, 99, 69), (40, 40, 40))])
            check("trim: an already-tight crop",
                  trim_white_margins(p, pad=4), ((100, 70), (100, 70)))
            check("trim: the tight file is untouched on disk",
                  size_on_disk(p), (100, 70))

            # (6) tolerance is what decides whether a pale mark is content.
            p = _st_png(os.path.join(tmp, "trim_tol.png"), (120, 120),
                        (255, 255, 255), [((30, 30, 89, 89), (250, 250, 250))])
            check("trim: a 250-grey mark is white at tolerance 10",
                  trim_white_margins(p, pad=0, tolerance=10),
                  ((120, 120), (120, 120)))
            check("trim: the same mark is content at tolerance 2",
                  trim_white_margins(p, pad=0, tolerance=2),
                  ((120, 120), (60, 60)))

        # --- extract_one_figure -------------------------------------------
        pdf = _st_pdf(os.path.join(tmp, "Doe_Figs_2025.pdf"))
        doc = fitz.open(pdf)
        out = os.path.join(tmp, "Doe_Figs_2025_fig_1.png")
        rendered, final, blank = extract_one_figure(
            doc, 0, (100, 150, 500, 350), out, dpi=72, trim=False)
        check("extract_one_figure renders at the requested dpi",
              rendered, (400, 200))
        check("extract_one_figure without trim returns one size twice",
              final, rendered)
        check("extract_one_figure on a figure is not blank", blank, False)
        ok("extract_one_figure wrote the PNG", os.path.exists(out))
        ok("no temp file is left beside the output",
           not [f for f in os.listdir(tmp) if ".part-" in f])
        state["n"] += 1
        try:
            extract_one_figure(doc, 0, (100, 150, 100, 350),
                               os.path.join(tmp, "Doe_Figs_2025_fig_2.png"))
            state["bad"] += 1
            print("FAIL extract_one_figure accepted a degenerate rect — "
                  "PyMuPDF answers one with a 1x1 PNG in the vault")
        except ValueError as exc:
            if "degenerate" not in str(exc):
                state["bad"] += 1
                print("FAIL extract_one_figure's degenerate message: %s" % exc)
        ok("nothing was written for the degenerate rect",
           not os.path.exists(os.path.join(tmp, "Doe_Figs_2025_fig_2.png")))
        ok("no temp file survives a rejected rect",
           not [f for f in os.listdir(tmp) if ".part-" in f])
        # A failure AFTER the render, which is the case the temp file exists
        # for: an interrupted run must not leave a half-written PNG under the
        # real figure name, where every later run's "already exists" skip
        # preserves it forever as a broken embed.
        blocked = os.path.join(tmp, "Doe_Figs_2025_fig_3.png")
        os.makedirs(blocked)
        state["n"] += 1
        try:
            extract_one_figure(doc, 0, (100, 150, 500, 350), blocked, dpi=72,
                               trim=False)
            state["bad"] += 1
            print("FAIL extract_one_figure reported success writing onto a "
                  "directory")
        except OSError:
            pass
        ok("the temp file is cleaned up when the write fails late",
           not [f for f in os.listdir(tmp) if ".part-" in f])

        # --- an all-white render ------------------------------------------
        # A caption whose figure is on the NEXT page: `auto_fig_bbox`'s
        # raster-only fallback synthesises a rect over the empty gap above the
        # caption, every check downstream passes it, and a 314x468 PNG of
        # nothing was written and counted as an extraction. The one piece of
        # code that noticed was `trim_white_margins` ("entirely white —
        # nothing to do"), whose return value the batch caller discarded.
        if have_pil:
            white = _st_png(os.path.join(tmp, "blank_probe.png"), (40, 30),
                            (255, 255, 255))
            check("render_is_blank on an all-white PNG",
                  render_is_blank(white), True)
            near = _st_png(os.path.join(tmp, "near_white.png"), (40, 30),
                           (250, 250, 250))
            check("render_is_blank on a near-white PNG, inside tolerance",
                  render_is_blank(near, tolerance=10), True)
            check("...and outside it", render_is_blank(near, tolerance=2),
                  False)
            marked = _st_png(os.path.join(tmp, "one_mark.png"), (40, 30),
                             (255, 255, 255), [((5, 5, 9, 9), (0, 0, 0))])
            check("render_is_blank on a PNG with one dark mark",
                  render_is_blank(marked), False)

            blank_out = os.path.join(tmp, "Doe_Figs_2025_fig_9.png")
            rendered, final, blank = extract_one_figure(
                doc, 0, (100, 450, 500, 700), blank_out, dpi=72)
            check("extract_one_figure reports an all-white render", blank, True)
            check("...and still reports the size it rendered",
                  rendered, (400, 250))
            ok("...and writes NOTHING — a white PNG at a figure's name embeds "
               "everywhere and the next run's skip preserves it forever",
               not os.path.exists(blank_out))
            ok("...leaving no temp file behind",
               not [f for f in os.listdir(tmp) if ".part-" in f])
            # ...and it cannot destroy a good figure that is already there,
            # which an --overwrite re-crop would otherwise do.
            keep = os.path.join(tmp, "Doe_Figs_2025_fig_8.png")
            _st_png(keep, (12, 12), (10, 20, 30))
            before = open(keep, "rb").read()
            _r, _f, blank = extract_one_figure(doc, 0, (100, 450, 500, 700),
                                               keep, dpi=72)
            check("a blank re-render leaves the existing figure alone",
                  (blank, open(keep, "rb").read() == before), (True, True))
        doc.close()

        # --- main(): the CLI surface --------------------------------------
        def run(argv):
            """main() with `argv`, returning (exit code, stdout, stderr)."""
            so, se = io.StringIO(), io.StringIO()
            code = 0
            with contextlib.redirect_stdout(so), contextlib.redirect_stderr(se):
                try:
                    code = main(argv)
                except SystemExit as exc:
                    code = exc.code
                except Exception as exc:
                    # An unhandled exception is a failure of this case, not of
                    # the run: reported like any other wrong answer so the
                    # cases after it still execute and still get counted.
                    code = "unhandled %s: %s" % (type(exc).__name__, exc)
            return code, so.getvalue(), se.getvalue()

        outdir = os.path.join(tmp, "Images")
        base = [pdf, "--out", outdir, "--stem", "Doe_Figs_2025"]
        code, so, se = run(base + ["--crop", "1:1:100,150,500,350", "--dpi",
                                   "72", "--no-trim"])
        png = os.path.join(outdir, "Doe_Figs_2025_fig_1.png")
        check("a crop run exits 0", code, 0)
        ok("the crop run wrote the figure", os.path.exists(png))
        ok("the run said what it wrote", "Wrote" in so)

        # Skip-existing is the default, and it is what keeps a hand-set crop
        # from being undone by the next batch run.
        # Stand in for a crop the user set by hand: distinguishable bytes, so
        # "skipped" and "overwritten" are told apart by content, not mtime.
        with open(png, "wb") as fh:
            fh.write(b"a hand-set crop, not this run's render")
        stamp = open(png, "rb").read()
        code, so, se = run(base + ["--crop", "1:1:100,150,500,350", "--dpi",
                                   "72", "--no-trim"])
        check("a second run exits 0", code, 0)
        ok("the second run says it skipped", "Exists, skipped" in so)
        check("the existing file is untouched", open(png, "rb").read(), stamp)
        code, so, se = run(base + ["--crop", "1:1:100,150,500,350", "--dpi",
                                   "72", "--no-trim", "--overwrite"])
        ok("--overwrite replaces it", open(png, "rb").read() != stamp)
        ok("--overwrite says it wrote", "Wrote" in so)

        # A caption inside the crop is the one thing this skill promises never
        # to do, so a crop reaching past the caption's top edge is warned about.
        code, so, se = run(base + ["--crop", "1:3:100,150,500,420", "--dpi",
                                   "72", "--no-trim"])
        ok("a crop reaching below the caption top is warned about",
           "WARNING" in se and "caption" in se)
        code, so, se = run(base + ["--crop", "1:4:100,150,500,350", "--dpi",
                                   "72", "--no-trim"])
        check("a crop that stops above the caption is not warned about",
              "WARNING" in se, False)

        code, so, se = run(base + ["--crop", "9:1:1,2,3,4"])
        check("a page past the end exits non-zero", code != 0, True)
        ok("...and says which page", "out of range" in str(code))
        code, so, se = run(base + ["--crop", "1:1:300,150,100,350"])
        ok("an inverted rect is refused", "degenerate" in str(code))
        # A path-shaped FIG_NUM used to reach PyMuPDF as an unopenable path
        # under --out and die with a raw FzErrorSystem traceback.
        code, so, se = run(base + ["--crop",
                                   "1:sub/../../escaped:100,150,500,350"])
        ok("a path-shaped FIG_NUM is refused cleanly, not a traceback",
           "filename fragment, not a path" in str(code))
        ok("...and nothing named for it was written",
           not any("escaped" in f for _r, _d, fs in os.walk(outdir)
                   for f in fs))

        # `--stem` goes straight into a filename, so a path in it writes
        # outside `--out` entirely.
        code, so, se = run([pdf, "--out", outdir, "--stem", "../../escape",
                            "--crop", "1:1:1,2,3,4"])
        ok("--stem with a path separator is refused",
           "not a path" in str(code))
        code, so, se = run([pdf, "--out", outdir, "--stem", "..",
                            "--crop", "1:1:1,2,3,4"])
        ok("--stem of '..' is refused", "not a path" in str(code))
        # A separator with no dots in it: caught by the separator guard alone,
        # so that guard cannot be removed behind the `..` one.
        code, so, se = run([pdf, "--out", outdir, "--stem", "nested/name",
                            "--crop", "1:1:1,2,3,4"])
        ok("--stem with a separator and no dots is refused",
           "not a path" in str(code))
        code, so, se = run([pdf, "--out", outdir, "--stem", "   ",
                            "--crop", "1:1:1,2,3,4"])
        ok("an all-whitespace --stem is refused", "empty" in str(code))
        # `.` passed every guard and wrote `._fig_1.png` — a dotfile Obsidian
        # never shows and no `[stem]_fig*` glob finds, reported as success.
        code, so, se = run([pdf, "--out", outdir, "--stem", ".",
                            "--crop", "1:1:1,2,3,4"])
        ok("a dots-only --stem is refused (would write invisible dotfiles)",
           "dotfile" in str(code))
        code, so, se = run([pdf, "--out", outdir, "--stem", ". ",
                            "--crop", "1:1:1,2,3,4"])
        ok("...as is a dot-space one", "dotfile" in str(code))

        # The missing-argument path: named, not an argparse usage dump, and
        # exit 2 the way `paper_scan.py` reports the same thing.
        code, so, se = run([pdf, "--out", outdir])
        check("missing --stem/--crop exits 2", code, 2)
        ok("...naming both", "--stem" in se and "--crop" in se)

        # An HTML error page saved as `.pdf` opens fine in PyMuPDF and reads as
        # a document. Without the is_pdf guard the crop is written from it.
        html = os.path.join(tmp, "Doe_NotAPdf_2025.pdf")
        with open(html, "w", encoding="utf-8") as fh:
            fh.write("<html><body><h1>404</h1><p>Not found.</p></body></html>")
        code, so, se = run([html, "--out", outdir, "--stem", "Doe_NotAPdf_2025",
                            "--crop", "1:1:10,10,100,100"])
        ok("an HTML page named .pdf is refused", "not a PDF" in str(code))
        ok("...and nothing was written for it",
           not os.path.exists(os.path.join(outdir,
                                           "Doe_NotAPdf_2025_fig_1.png")))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("%d/%d self-test cases pass"
          % (state["n"] - state["bad"], state["n"]))
    return 1 if state["bad"] else 0


def main(argv=None):
    p = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=__doc__,
    )
    p.add_argument("pdf", nargs="?")
    p.add_argument("--out", help="Output directory (e.g. Sources/Images/)")
    p.add_argument(
        "--stem",
        help="Filename stem, e.g. Prince_UDL_2023_02_SupLearn",
    )
    p.add_argument(
        "--crop",
        action="append",
        help='Figure spec: "PAGE:FIG_NUM:x0,y0,x1,y1"',
    )
    p.add_argument("--dpi", type=int, default=250)
    p.add_argument(
        "--overwrite",
        action="store_true",
        help=(
            "Replace an output PNG that already exists. Default: skip it and "
            "say so, which is what batch_extract.py does — the two write into "
            "the same flat Sources/Images/ folder, and silently overwriting a "
            "hand-set crop (or having one silently overwritten) is the same "
            "bug in either direction."
        ),
    )
    p.add_argument(
        "--no-caption-check",
        dest="caption_check",
        action="store_false",
        help=(
            "Skip the warning when a crop rect overlaps a detected caption. "
            "The check is on by default: y1 below the caption's y0 puts the "
            "caption text in the PNG."
        ),
    )
    p.add_argument(
        "--no-trim",
        dest="trim",
        action="store_false",
        help="Skip the post-crop white-margin trim (default: trim).",
    )
    p.add_argument(
        "--trim-pad",
        type=int,
        default=4,
        help="Pixels of whitespace to keep around the trimmed content (default: 4).",
    )
    p.add_argument(
        "--trim-tolerance",
        type=int,
        default=10,
        help="Per-channel distance from pure white that still counts as white "
        "(default: 10, handles antialiasing).",
    )
    p.add_argument("--test", action="store_true", help="run the self-test")
    args = p.parse_args(argv)

    if args.test:
        return run_self_test()
    # Reported by name rather than left to argparse's `required=True`, because
    # `--test` takes no PDF and no crops: with the flags marked required,
    # argparse rejects the self-test invocation before `main()` can see it.
    # Same shape and same exit code as `paper_scan.py`'s missing-argument path.
    missing = [f for f in ("pdf", "out", "stem", "crop")
               if not getattr(args, f)]
    if missing:
        print("missing required argument(s): %s"
              % ", ".join("pdf" if m == "pdf" else "--" + m for m in missing),
              file=sys.stderr)
        return 2

    out_dir = os.path.expanduser(args.out)
    # `--stem` is free text on the command line: the model types it, and it is
    # not necessarily a PDF's on-disk stem. It goes straight into
    # `os.path.join(out_dir, f"{stem}_fig_{n}.png")`, so a separator or a
    # parent-directory hop writes outside `--out` entirely — `--stem
    # ../../x` lands two directories above the Sources/Images folder. A stem is
    # a filename fragment, not a path; refuse anything else, the same way
    # clipping-processor's `fetch_images.py` refuses a `--slug`.
    for bad in ("/", os.sep, "\x00"):
        if bad and bad in args.stem:
            sys.exit(f"--stem {args.stem!r} contains {bad!r}: a stem is a "
                     "filename fragment, not a path")
    if ".." in args.stem or not args.stem.strip():
        sys.exit(f"--stem {args.stem!r} is empty or contains '..': a stem is a "
                 "filename fragment, not a path")
    if not args.stem.strip(". "):
        # `.` passed every check above and wrote `._fig_1.png` — a dotfile
        # Obsidian does not show and no `[stem]_fig*` consumer glob ever
        # finds, while the run reported success.  fetch_images.validate_slug
        # (whose refusal this block copies) has the same third check for the
        # same incident.
        sys.exit(f"--stem {args.stem!r} is only dots/spaces: the files would "
                 "be invisible dotfiles. Pass the PDF's real stem")
    os.makedirs(out_dir, exist_ok=True)
    pdf_path = os.path.expanduser(args.pdf)
    # A one-line message beats a traceback for the two things that land in
    # a Sources/PDFs folder and are not readable PDFs: a truncated or non-PDF
    # download, and a PDF with zero pages.
    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        sys.exit(f"{pdf_path}: could not open as a PDF ({e})")
    # PyMuPDF opens HTML, XPS and EPUB natively, so an error page or a
    # truncated download named `.pdf` opens without raising, renders, and
    # writes a PNG of somebody's 404 page into Sources/Images/ under a real
    # figure name. `batch_extract.py` has always had this guard; this script
    # writes into the same folder and needs the same one.
    if not doc.is_pdf:
        fmt = (doc.metadata or {}).get("format") or "an unknown format"
        sys.exit(f"{pdf_path}: not a PDF — opened as {fmt} (an HTML error page "
                 f"or a truncated download saved with a .pdf extension)")
    if len(doc) == 0:
        sys.exit(f"{pdf_path}: PDF has zero pages — nothing to extract")

    # Caption rects, for the "is the caption inside this crop?" warning.
    # Imported lazily and defensively: the check is a convenience, and a
    # sibling-module import problem must not stop a manual crop from being
    # written — that crop is usually the fallback for something else that
    # already went wrong.
    find_caption_blocks = None
    to_page_space = None
    if args.caption_check:
        try:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            from auto_fig_bbox import find_caption_blocks, to_page_space
        except (Exception, SystemExit) as e:
            # SystemExit too: auto_fig_bbox exits with a message rather than
            # a traceback when PyMuPDF is missing, and that must not take
            # this script's own crop down with it.
            print(f"note: caption-overlap check unavailable ({e})", file=sys.stderr)

    for spec in args.crop:
        page_idx, fig_suffix, (x0, y0, x1, y1) = parse_crop(spec)
        if page_idx < 0 or page_idx >= len(doc):
            sys.exit(
                f"--crop {spec!r}: page {page_idx + 1} out of range "
                f"(PDF has {len(doc)} pages)"
            )
        if x0 >= x1 or y0 >= y1:
            sys.exit(
                f"--crop {spec!r}: degenerate rect — need x0 < x1 and "
                f"y0 < y1, got x={x0},{x1} y={y0},{y1}"
            )
        # The crop must end above the caption. This is the constraint every
        # hand-set crop gets wrong first, and nothing about the result says
        # so: the PNG is written, looks fine at a glance, and carries the
        # caption text the skill exists to leave out.
        if find_caption_blocks is not None:
            for cap_num, cap_raw, cap in find_caption_blocks(doc[page_idx]):
                # `--crop` coordinates are the ones `get_pixmap(clip=...)`
                # takes — the page's displayed space — while caption rects
                # come back in unrotated content space. On a `/Rotate`d page
                # the two are different, and comparing them compared nothing.
                cap = to_page_space(doc[page_idx], cap)
                if y1 > cap.y0 and x1 > cap.x0 and x0 < cap.x1 and y0 < cap.y1:
                    print(
                        f"WARNING: --crop {spec!r} reaches y1={y1:.0f}, below the "
                        f"top of the caption for {cap_raw!r} (y0={cap.y0:.1f}) — "
                        f"the caption will be in the PNG. Use y1 <= "
                        f"{cap.y0 - 0.5:.1f}.",
                        file=sys.stderr,
                    )
        out_path = os.path.join(out_dir, f"{args.stem}_fig_{fig_suffix}.png")
        # Skip-existing is batch_extract.py's documented default and this is
        # the same output folder, so it is the default here too. Without it,
        # a manual crop and a batch run silently overwrite each other's work
        # depending only on which ran last.
        if os.path.exists(out_path) and not args.overwrite:
            print(f"Exists, skipped: {out_path} (pass --overwrite to replace)")
            continue
        (rw, rh), (fw, fh), blank = extract_one_figure(
            doc, page_idx, (x0, y0, x1, y1), out_path,
            dpi=args.dpi, trim=args.trim,
            trim_pad=args.trim_pad, trim_tolerance=args.trim_tolerance,
        )
        if blank:
            print(
                f"BLANK: --crop {spec!r} rendered {rw}x{rh} pixels of nothing "
                f"but white — nothing was written to {out_path}. The rect is "
                f"over empty page: the usual cause is a caption whose figure "
                f"is on another page. Render the page "
                f"(scripts/render_page.py) and re-read the coordinates.",
                file=sys.stderr,
            )
            continue
        msg = f"Wrote {out_path}: {rw}x{rh}"
        if args.trim:
            if (fw, fh) != (rw, rh):
                msg += f" → trimmed to {fw}x{fh}"
            else:
                msg += " (no whitespace to trim)"
        print(msg)
    return 0


if __name__ == "__main__":
    # `sys.exit(main())`: `--test` and the missing-argument path both report
    # through the exit code, and a bare call throws it away.
    sys.exit(main())
