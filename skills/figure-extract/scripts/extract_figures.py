"""Crop figures from a PDF using user-specified rectangles, then trim white margins.

Each --crop spec is "PAGE:FIG_NUM:x0,y0,x1,y1":
  - PAGE     : 1-indexed page number
  - FIG_NUM  : the figure's output label as auto_fig_bbox/batch_extract
               report it (e.g. "2.1", "S1" for Supplementary Figure 1
               rather than its printed "1", "S2-3")
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

**Keep every caption out of the crop.** A caption rect is a hard limit on the
side it faces: below the figure, y1 stays above its y0; above it, y0 stays
below its y1; beside it, the crop's x-range stays clear. `auto_fig_bbox.py`
prints the caption rect next to every bbox for exactly this, and caption text
in the PNG is the one thing this skill promises it never delivers. Crops that
overlap a detected caption are warned about by name. When the caption sits in
a corner of the figure's bounding box, `--blank-captions` whites out its words.

Existing files are skipped only after their ownership record and current
bytes are verified, matching `batch_extract.py`. Pass --overwrite to replace
verified output; unknown or changed occupants are refused. Both scripts use
the same flat `Sources/Images/` folder and preserve each other's explicit fixes
unless replacement is requested.

After cropping, each PNG is auto-trimmed to remove near-white margins on all
four sides (with `--trim-pad` pixels of breathing room). The PyMuPDF crop tends
to leave whitespace because `auto_fig_bbox.py` pads aggressively for axis labels
and panel letters that may or may not be present. The trim treats pixels within
`--trim-tolerance` of white as margin, refuses an extreme reduction, and keeps
a pale panel the trim would otherwise cut through.

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
        --crop "3:2.1:70,130,300,330" \\
        --crop "4:2.2:95,130,540,510" \\
        --crop "5:S1:95,130,540,350"

    # Replace figures a batch run already wrote:
    python3 extract_figures.py input.pdf --overwrite --out ... --crop ...

    # The adversarial fixtures this module is held to.
    python3 extract_figures.py --test

Output names use the source PDF's on-disk filename stem (including any `_src`
suffix it carries), which is what `wiki-build` globs for when it looks up
`Sources/Images/[source_stem]_fig*`; `--stem`, if given, must equal it.
"""
import argparse
import errno
import math
import os
import re
import shutil
import stat
import sys
import tempfile
import warnings
from collections import defaultdict
from pathlib import Path

_OBSIDIAN_SHARED_MODULES = ('atomic_move', 'figure_state', 'naming',
                            'portable_names', 'vault_artifacts')

# --- obsidian shared-layer bootstrap (canonical; see shared/RUNTIME.md) ---
import os as _os, sys as _sys
_here = _os.path.dirname(_os.path.realpath(__file__))
_required = tuple(_m + ".py" for _m in (
    globals().get("_OBSIDIAN_SHARED_MODULES") or ("slugify",)))
_env = _os.environ.get("OBSIDIAN_VAULT_SHARED")
if _env:                                   # explicit override: authoritative, no fallback
    _tried = [_os.path.abspath(_os.path.expanduser(_env))]
else:                                      # plugin-relative walk-up, at most 5 levels
    _tried, _d = [], _here
    for _ in range(5):
        _tried.append(_os.path.join(_d, "shared", "scripts"))
        _d = _os.path.dirname(_d)
    _tried.append(_here)                   # extracted skill with co-located helpers
_missing = {_p: [_m for _m in _required if not _os.path.isfile(_os.path.join(_p, _m))]
            for _p in _tried if _os.path.isdir(_p)}
_shared = next((_p for _p in _tried if _p in _missing and not _missing[_p]), None)
if _shared is None:
    raise SystemExit("""obsidian: cannot find the plugin's shared/scripts/ folder, which holds
the one canonical copy of the conventions this script depends on. A usable
folder must contain these required module(s): %s
Looked for:
  %s
Fix: install the whole plugin tree, or set OBSIDIAN_VAULT_SHARED to the
shared/scripts/ directory (unset it to use the plugin-relative walk-up).
Do NOT paste a second copy of the algorithm into this skill -- a divergent
copy is the bug the shared layer exists to prevent.""" % (
    ", ".join(_required), "\n  ".join(
        _p + (" (not a directory)" if _p not in _missing else
              " (missing: %s)" % ", ".join(_missing[_p]))
        for _p in _tried)))
_sys.path[:] = [_p for _p in _sys.path if _p not in (_shared, _here)]
_sys.path.insert(0, _shared)               # shared/scripts/ FIRST
if _here != _shared:
    _sys.path.insert(1, _here)              # sibling modules before unrelated paths
# --- end bootstrap ---

from figure_state import (MANIFEST_FILE, file_digest, read_manifest,
                          read_manifest_snapshot, read_sidecar, write_manifest,
                          manifest_key, figure_identity, check_manifest_writable,
                          sidecar_stem_problem)
import atomic_move
from naming import (chapter_book_stem, core_stem, is_feed_attachment,
                    looks_canonical)
from render_page import MAX_RENDER_PIXELS, checked_render_dimensions
from vault_artifacts import (LINK_ALIAS_REMEDY, UnlistedFolderError,
                             inventory_source_figures, link_aliases,
                             on_disk_spelling, output_vault_root,
                             verify_selected_pdf)

try:
    import pymupdf as fitz
except ImportError:
    fitz = None


_PYMUPDF_ERROR = (
    "PyMuPDF required. Use a Python environment with the plugin\n"
    "dependencies installed; see shared/RUNTIME.md. Install into a\n"
    "virtual environment, then run this command with that environment's "
    "Python."
)


def _require_pymupdf():
    """Fail after argument parsing so --help remains available during setup."""
    if fitz is None:
        raise SystemExit(_PYMUPDF_ERROR)


#: The remedy for a shared vault PDF basename (CONVENTIONS.md 1a), given by
#: both extraction commands; renaming the filed copy would hand its figures
#: to the newcomer.
DUPLICATE_BASENAME_REMEDY = (
    "another vault file shares this PDF basename; ask the user to remove the "
    "redundant copy or to rename the newcomer (normally the copy outside "
    "Sources/PDFs/) or move it out of the vault, then retry. If pdf-organize "
    "`check` accepts the newcomer, pdf-organize may rename it instead "
    "(CONVENTIONS.md §1a)")
#: A PDF with no vault owner; pdf-organize never imports an external file.
UNOWNED_PDF_REMEDY = (
    "a readable scratch copy must keep its vault PDF's exact basename; "
    "otherwise use an external --out for a one-off, or, with the user's "
    "approval, copy the PDF into Inbox/ for pdf-organize to file and extract "
    "from the filed path")


def vault_refusal(decision):
    """(category, remedy) for a canonical-output refusal of one selected PDF.

    `decision` is `verify_selected_pdf`'s non-unique result.
    """
    if not decision.inventory.complete:
        return ("vault inventory incomplete",
                "repair or remove the unreadable vault paths named, then retry")
    if not decision.matches:
        return ("no vault PDF owns this basename", UNOWNED_PDF_REMEDY)
    if len(decision.matches) > 1:
        links = sorted({link for found in link_aliases(
            decision.matches, decision.inventory.root).values() for link in found})
        if links:
            # One file under several paths: removing a path removes the file.
            return ("basename reached through a link",
                    LINK_ALIAS_REMEDY % ", ".join(links))
        return ("vault basename not unique", DUPLICATE_BASENAME_REMEDY)
    owner = os.path.basename(decision.matches[0])
    if owner != os.path.basename(decision.selected):
        # A case or Unicode variant of the owner's name: the figures would
        # be named after a stem the vault PDF does not have.
        return ("basename spelling differs",
                "use the vault PDF's exact basename %r" % owner)
    return ("vault owner not usable",
            decision.reason + "; inspect that vault PDF")


def split_book_chapters(pdfs, inventory=None):
    """{book path: [chapter paths]} for every book in `pdfs` split into chapters.

    Detection is purely by stem, which is what makes it safe: pdf-organize
    guarantees the chapter stem is the book stem plus `_NN_Name`
    (book-splitting reference, §3 *Choose chapter names once*). Chapters
    come from `pdfs` and, with the vault's canonical output, from the vault
    PDF `inventory`, because pdf-organize files a book's chapters in
    `Sources/PDFs/<stem>/` wherever the book sits. Without an inventory no
    vault layout is assumed, so this works for a Downloads folder too. Both
    batch_extract.py and an explicit crop use this one rule.

    Both sides are compared on the *core* stem — `_src` stripped, `_2` kept —
    because a book and its chapters carry those tails independently: a book
    may be `Prince_UDL_2026_src.pdf` while its chapters are
    `Prince_UDL_2026_01_Intro.pdf`, or the other way round. Comparing raw
    stems misses the pairing, and a missed pairing writes every figure twice.
    """
    # Stems use one portable case-insensitive identity so
    # `kuhn_x_2012_01_A.pdf` receives the same chapter decision relative to
    # `Kuhn_X_2012.pdf` on every supported filesystem.
    #
    # EVERY path per core stem is collected, not one representative: with both
    # spellings of a split book in the walk (`X.pdf` beside `X_src.pdf` — the
    # plain copy lingering after a rename), keeping one path per key skipped
    # that one and extracted the twin whole, writing every chapter figure a
    # second time under the twin's stem.  paper_scan.classify skips every stem
    # whose core is a book of some chapter; the two skills split the same
    # folder, and disagreeing is worse than either answer.
    by_stem = {}
    for p in pdfs:
        by_stem.setdefault(core_stem(p.stem, is_stem=True).casefold(), []).append(p)
    candidates = list(pdfs)
    if inventory is not None:
        candidates += [Path(entry.path) for entry in inventory.entries
                       if entry.kind in ("regular", "symlink")]

    def same_file(path):
        # A chapter in the run is in the inventory too, perhaps spelled
        # another way; it counts once, under its path in the run.
        try:
            info = os.stat(path)
        except OSError:
            return os.path.realpath(path)
        return info.st_dev, info.st_ino

    out = defaultdict(list)
    seen = set()
    for p in candidates:
        book = chapter_book_stem(p.stem, is_stem=True)
        if not book or book.casefold() not in by_stem:
            continue
        if inventory is not None:
            key = same_file(p)
            if key in seen:
                continue
            seen.add(key)
        for bp in by_stem[book.casefold()]:
            if bp != p:
                out[bp].append(p)
    return {book: sorted(chs) for book, chs in out.items()}


# ASCII digits only: the label becomes part of a filename. A marker prefix
# (`S`, or `ED` under `--ed-prefix ED`) may stand before an SI or appendix
# label, as auto_fig_bbox writes for `Supplementary Figure A1` (`SA1`) or
# `Extended Data Figure S1` (`EDS1`).
_FIG_LABEL = re.compile(
    r"(?:SI|ED|S)?[0-9]+(?:[.\-–][0-9]+)*"
    r"|(?:ED|S)?(?:SI|[A-Z][.\-–]?)[0-9]+(?:[.\-–][0-9]+)*")


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
    try:
        fig_suffix = validated_figure_suffix(fig_str)
    except ValueError as exc:
        sys.exit(f"--crop {spec!r}: {exc}")
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
    if not all(math.isfinite(v) for v in coords):
        sys.exit(f"--crop {spec!r}: rect coordinates must be finite numbers")
    return page_idx, fig_suffix, coords


def normalize_fig_num(fig_num):
    """Normalize a captured figure label into a filename-safe suffix.

    The captured label can use `.` (Prince UDL, most math/CS books), `-`
    (Géron, many O'Reilly titles), or a mix. We standardize on `-` so the
    on-disk name is predictable regardless of caption style — `Figure 1.2`,
    `Figure 1-2`, and `Figure 1–2` all become `_fig_1-2.png`. A spaced
    `Figure 1 - 2` is read as Figure 1 with a title.
    """
    return fig_num.replace(".", "-").replace("–", "-")


def validated_figure_suffix(fig_num):
    """Validate one whole-figure label and return its filename suffix."""
    # Check the raw value before normalization: converting dots to dashes
    # would erase a parent hop before the filename-fragment guard saw it.
    for bad in ("/", "\\", "\x00"):
        if bad in fig_num:
            raise ValueError(
                f"FIG_NUM {fig_num!r} contains {bad!r}: a figure label is a "
                "filename fragment, not a path")
    if ".." in fig_num or not fig_num.strip():
        raise ValueError(
            f"FIG_NUM {fig_num!r} is empty or contains '..': a figure label "
            "is a filename fragment, not a path")
    if not _FIG_LABEL.fullmatch(fig_num):
        raise ValueError(
            f"FIG_NUM {fig_num!r} is not a supported whole-figure label "
            "(examples: 2, 2.1, A.1, S2, SA1, ED3, SI4)")
    return normalize_fig_num(fig_num)


#: An output label split into its letter prefix and its number.
_LABEL_SERIES = re.compile(r"([A-Z]*)-?([0-9].*)")


def _series_mismatch(fig_suffix, captions):
    """The caption on the crop page that FIG_NUM probably meant, or None.

    `captions` are `find_caption_blocks` rows. When no caption on the page
    has FIG_NUM's output label but one has the same number in the other
    series (a plain main label against a marker or appendix prefix, e.g.
    `1` beside `Supplementary Figure 1`, which is `S1`, or an appendix label
    against its S-prefixed form, `A1` beside `SA1`), return that caption's
    (raw label, output label). A page without a caption of that number
    returns None: a crop overleaf of its caption is legitimate.
    """
    labels = [(normalize_fig_num(num), raw) for num, raw, _rect in captions]
    if any(label == fig_suffix for label, _raw in labels):
        return None
    want = _LABEL_SERIES.fullmatch(fig_suffix)
    if not want:
        return None
    w = want.group(1)
    for label, raw in labels:
        got = _LABEL_SERIES.fullmatch(label)
        if not got or got.group(2) != want.group(2):
            continue
        g = got.group(1)
        if bool(g) != bool(w) or g == "S" + w or w == "S" + g:
            return raw, label
    return None


def _extended_data_label(cap_raw, cap_label):
    """The `--ed-prefix ED` output label of an Extended Data caption, or None.

    `cap_label` is the caption's default-prefix label: `Extended Data Figure
    1`, `A1` and `S1` are `S1`, `SA1` and `S1`, which a batch run with
    `--ed-prefix ED` names `ED1`, `EDA1` and `EDS1`.
    """
    if (not re.match(r"\s*extended\s+data\b", cap_raw, re.I)
            or not cap_label.startswith("S")):
        return None
    printed = cap_raw.split()[-1]
    return "ED" + (cap_label if printed.startswith("S") else cap_label[1:])


def positive_int(value):
    """An argparse integer strictly above zero."""
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise argparse.ArgumentTypeError("must be an integer")
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def nonnegative_int(value):
    """An argparse integer at least zero."""
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise argparse.ArgumentTypeError("must be an integer")
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return parsed


def pixel_tolerance(value):
    """A channel-distance threshold that can still leave non-white pixels."""
    parsed = nonnegative_int(value)
    if parsed > 254:
        raise argparse.ArgumentTypeError("must be between 0 and 254")
    return parsed


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
    if pad < 0:
        raise ValueError("trim pad must be zero or greater")
    if not 0 <= tolerance <= 254:
        raise ValueError("trim tolerance must be between 0 and 254")
    try:
        from PIL import Image, ImageChops
    except ImportError:
        sys.exit(
            "Pillow required for --trim (default on). "
            "Use a virtual environment with the plugin dependencies "
            "(shared/RUNTIME.md), or pass --no-trim to skip cleanup."
        )

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(img_path, formats=("PNG",)) as source:
                source.load()
                img = source.copy()
    except (Image.DecompressionBombWarning,
            Image.DecompressionBombError) as exc:
        raise ValueError(
            "refusing PNG whose dimensions exceed Pillow's safety limit"
        ) from exc
    rgb = img.convert("RGB")
    orig_size = rgb.size  # (w, h)

    # Diff against a pure-white background; pixels within `tol` of white
    # become 0 (pure black after the threshold), so getbbox finds the
    # smallest rect containing real content.
    diff = ImageChops.difference(rgb, Image.new("RGB", orig_size,
                                                (255, 255, 255)))
    w, h = orig_size

    def padded_bbox(tol):
        found = diff.point(lambda p: 255 if p > tol else 0).getbbox()
        if found is None:
            return None
        x0, y0, x1, y1 = found
        return (max(0, x0 - pad), max(0, y0 - pad),
                min(w, x1 + pad), min(h, y1 + pad))

    bbox = padded_bbox(tolerance)
    if bbox is None:
        return orig_size, orig_size  # entirely white — nothing to do

    # A figure drawn on a pale panel (one rendered at 245 is within the default
    # tolerance) reads as margin, so the trim cut through the panel. When
    # most of the new edge is pale but not white, count only near-pure white
    # as margin: that keeps the whole panel and trims the page around it.
    # Pale tone that reaches three or more sides of the crop is the page
    # itself (a scan or tinted paper), so that trim stands.
    x0, y0, x1, y1 = bbox
    px = rgb.load()
    edge = ([px[x, y] for x in range(x0, x1) for y in (y0, y1 - 1)]
            + [px[x, y] for y in range(y0, y1) for x in (x0, x1 - 1)])
    if 2 * sum(2 < 255 - min(p) <= tolerance for p in edge) > len(edge):
        panel = padded_bbox(min(tolerance, 2))
        if sum(a == b for a, b in zip(panel, (0, 0, w, h))) < 3:
            x0, y0, x1, y1 = panel

    if (x0, y0, x1, y1) == (0, 0, w, h):
        return orig_size, orig_size  # padded bbox covers whole image

    # A trim that removes almost everything is a trim that misread the
    # background, such as pale figure content the edge check above misses.
    if (x1 - x0) * (y1 - y0) < MIN_TRIM_KEEP * w * h:
        return orig_size, orig_size

    cropped = img.crop((x0, y0, x1, y1))
    cropped.save(img_path)
    return orig_size, cropped.size


def _pixmap_is_blank(pix, tolerance=10):
    """Return whether a PyMuPDF pixmap contains only near-white pixels."""
    channels = pix.n - int(bool(pix.alpha))
    if channels not in (1, 3):
        # A saved PNG normally opens as DeviceGray or DeviceRGB. Keep the
        # predicate correct if a backend returns another colourspace anyway.
        pix = fitz.Pixmap(fitz.csRGB, pix)
        channels = pix.n - int(bool(pix.alpha))
    samples = pix.samples
    threshold = 255 - tolerance
    # Slice one colour channel at a time. `min()` runs in C over the resulting
    # bytes and avoids a Python loop for every pixel on the no-Pillow path.
    return all(min(samples[channel::pix.n], default=255) >= threshold
               for channel in range(channels))


def render_is_blank(img_path, tolerance=10):
    """True when every pixel of `img_path` is within `tolerance` of white.

    The same predicate `trim_white_margins` reaches when its
    `diff.point(...).getbbox()` comes back None — "entirely white — nothing to
    do" — computed in one pass over the extrema instead of building two
    intermediate images, because this runs on every figure.

    Pillow is the fast path. `--no-trim` deliberately works without Pillow,
    so PyMuPDF (already required for rendering) is the dependency-independent
    fallback. Returns None only when neither reader can validate the staged
    PNG; callers must fail closed on that result.
    """
    if not 0 <= tolerance <= 254:
        raise ValueError("blank tolerance must be between 0 and 254")
    try:
        from PIL import Image
    except ImportError:
        Image = None
    if Image is not None:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(img_path, formats=("PNG",)) as im:
                    bands = im.convert("RGB").getextrema()
                return all(lo >= 255 - tolerance for lo, _hi in bands)
        except (Image.DecompressionBombWarning,
                Image.DecompressionBombError):
            return None
        except (OSError, ValueError):
            pass
    try:
        return _pixmap_is_blank(fitz.Pixmap(img_path), tolerance=tolerance)
    except Exception:
        return None


def _stable_output_snapshot(path):
    """Snapshot one regular output's identity, bytes, mode, and size."""
    try:
        before = os.stat(path, follow_symlinks=False)
    except OSError as exc:
        raise FileExistsError(
            errno.EEXIST,
            "verified output disappeared or became unreadable after preflight",
            path,
        ) from exc
    if not stat.S_ISREG(before.st_mode):
        raise FileExistsError(
            errno.EEXIST,
            "output became a symlink or non-regular occupant after preflight",
            path,
        )
    try:
        digest = file_digest(path)
        after = os.stat(path, follow_symlinks=False)
    except OSError as exc:
        raise FileExistsError(
            errno.EEXIST,
            "verified output changed or became unreadable after preflight",
            path,
        ) from exc
    identity = lambda item: (
        item.st_dev, item.st_ino, item.st_size,
        getattr(item, "st_mtime_ns", int(item.st_mtime * 1e9)),
        getattr(item, "st_ctime_ns", int(item.st_ctime * 1e9)),
    )
    if identity(before) != identity(after):
        raise FileExistsError(
            errno.EEXIST,
            "verified output changed while its bytes were revalidated",
            path,
        )
    return ((after.st_dev, after.st_ino), digest,
            stat.S_IMODE(after.st_mode), after.st_size)


def _checked_visible_crop(page, rect, dpi, label="crop"):
    """Preflight the page-visible portion of a crop before rasterization."""
    visible = fitz.Rect(rect)
    visible.intersect(page.rect)
    if visible.width <= 0 or visible.height <= 0:
        raise ValueError(f"{label} does not intersect the PDF page")
    checked_render_dimensions(visible, dpi, label)
    return visible


def _stable_output_digest(path):
    """Digest one regular output, rejecting a concurrent identity change."""
    return _stable_output_snapshot(path)[1]


def _figure_slot_conflict(out_dir, stem, fig_suffix, out_path, inventory=None):
    """Return an occupied semantic figure slot, or ``None`` when it is free.

    ``inventory`` is an ``inventory_source_figures(out_dir, stem)`` result to
    reuse. Only a caller that writes nothing between checks (a dry run) may
    pass one; a writing run inventories afresh for every slot.

    The published PDF crop is always PNG, but the shared image folder also
    contains clipping output such as JPG and WebP. Consumers identify a figure
    by portable ``<stem>_fig_<label>`` identity before considering its
    extension, so checking only ``out_path`` can create two equally plausible
    files for one figure. The one direct regular path spelled exactly like the
    intended PNG is allowed through for the manifest/digest ownership check;
    every extension twin, case/NFC alias, nested match, symlink and nonregular
    occupant blocks without being changed.

    A missing output folder is conclusively empty for a dry-run preview. An
    existing folder whose shared inventory is incomplete cannot establish that
    the slot is free and therefore fails closed.
    """
    if not os.path.lexists(out_dir):
        return None
    if inventory is None:
        inventory = inventory_source_figures(out_dir, stem)
    if not inventory.complete:
        detail = "; ".join(
            "%s: %s" % (item.path, item.message)
            for item in inventory.findings
            if item.kind in {"unreadable", "changed-during-inventory"}
        ) or "the image folder could not be inventoried completely"
        return out_path, (
            "the portable figure namespace is incomplete, so this slot cannot "
            "be proved free (%s)" % detail
        )

    slot = figure_identity("%s_fig_%s" % (stem, fig_suffix))
    # The legacy separator-less `<stem>_fig<label>` spelling holds it too.
    compact = figure_identity("%s_fig%s" % (stem, fig_suffix))
    exact = os.path.abspath(os.fspath(out_path))
    direct = set(inventory.candidates)
    conflicts = []
    for candidate in inventory.candidates + inventory.blocked_matches:
        basename = os.path.basename(candidate)
        candidate_stem, _extension = os.path.splitext(basename)
        if figure_identity(candidate_stem) not in (slot, compact):
            continue
        candidate_abs = os.path.abspath(os.fspath(candidate))
        if candidate in direct:
            same_entry = candidate_abs == exact
            if not same_entry and os.path.lexists(out_path):
                try:
                    same_entry = os.path.samefile(candidate, out_path)
                except OSError:
                    same_entry = False
            if same_entry:
                # Normalization-insensitive filesystems can return an NFD
                # directory spelling for the NFC path we opened. It is one
                # file, not a semantic-slot twin; ownership is decided by the
                # manifest and digest below.
                continue
        conflicts.append(candidate)
    if not conflicts:
        return None
    conflicts.sort(key=lambda path: figure_identity(os.fspath(path)))
    return conflicts[0], (
        "the portable figure slot is occupied by %s; publishing %s would "
        "leave ambiguous extension, case, or Unicode variants" % (
            ", ".join(os.path.basename(path) for path in conflicts),
            os.path.basename(out_path),
        )
    )


def _restore_after_slot_conflict(out_path, published, predecessor,
                                 predecessor_snapshot, stage_dir, stage_parent):
    """Conditionally undo one crop after a late semantic-slot conflict."""
    rollback = os.path.join(stage_dir, ".slot-conflict-rollback")
    os.mkdir(rollback)
    if predecessor is None:
        atomic_move.remove_expected(
            out_path, published, _stable_output_snapshot, rollback,
            stage_parent=stage_parent, recovery_prefix=".figure-recovery-",
        )
        return
    if not os.path.lexists(out_path):
        atomic_move.link_noreplace(predecessor, out_path)
        if _stable_output_snapshot(out_path) != predecessor_snapshot:
            raise atomic_move.PublicationConflict(
                "%s could not be verified after restoration" % out_path,
                recovery_path=predecessor, keep_stage=True,
            )
        return
    atomic_move.replace_expected(
        predecessor, out_path, published, _stable_output_snapshot, rollback,
        stage_parent=stage_parent, recovery_prefix=".figure-recovery-",
    )


def _publish_staged(tmp_path, out_path, replace_snapshot=None,
                    before_publish=None, after_publish=None):
    """Publish a crop, with optional guards around its semantic name slot."""
    stage_dir = os.path.dirname(tmp_path)
    stage_parent = os.path.dirname(stage_dir)
    predecessor = None
    predecessor_snapshot = None
    try:
        if before_publish is not None:
            before_publish()
        if replace_snapshot is None:
            published = atomic_move.publish_new(
                tmp_path, out_path, _stable_output_snapshot, stage_parent,
                recovery_prefix=".figure-recovery-",
            )
        else:
            predecessor = os.path.join(stage_dir, ".predecessor")
            atomic_move.link_noreplace(out_path, predecessor)
            predecessor_snapshot = _stable_output_snapshot(predecessor)
            if predecessor_snapshot != replace_snapshot:
                raise atomic_move.PublicationConflict(
                    "%s changed after planning, before its predecessor could "
                    "be retained" % out_path)
            published = atomic_move.replace_expected(
                tmp_path, out_path, replace_snapshot,
                _stable_output_snapshot, stage_dir,
                stage_parent=stage_parent,
                recovery_prefix=".figure-recovery-",
            )
        if after_publish is not None:
            try:
                after_publish()
            except Exception as conflict:
                try:
                    _restore_after_slot_conflict(
                        out_path, published, predecessor, predecessor_snapshot,
                        stage_dir, stage_parent)
                except (OSError, atomic_move.PublicationConflict) as rollback_exc:
                    raise atomic_move.PublicationConflict(
                        "late figure-slot conflict (%s); rollback was incomplete: "
                        "%s; preserve %s" %
                        (conflict, rollback_exc, stage_dir),
                        recovery_path=(
                            getattr(rollback_exc, "recovery_path", None)
                            or stage_dir),
                        keep_stage=True,
                    ) from rollback_exc
                raise
        return published
    except atomic_move.LinkUnavailable:
        # A filesystem/permission capability failure is not evidence that the
        # destination became occupied. Preserve the shared helper's concrete
        # diagnosis so batch callers can report a publication failure instead
        # of blaming another skill's file.
        raise
    except OSError as exc:
        detail = getattr(exc, "strerror", None) or str(exc)
        if (replace_snapshot is None and isinstance(exc, FileExistsError)
                and not isinstance(exc, atomic_move.PublicationConflict)):
            detail = ("output became occupied after preflight; refusing to "
                      "replace it (%s)" % exc)
        conflict = FileExistsError(errno.EEXIST, detail, out_path)
        conflict.recovery_path = getattr(exc, "recovery_path", None)
        conflict.keep_stage = bool(getattr(exc, "keep_stage", False))
        raise conflict from exc


def extract_one_figure(doc, page_idx, bbox, out_path, dpi=250,
                       trim=True, trim_pad=4, trim_tolerance=10,
                       replace_digest=None, publication_guard=None,
                       return_publication=False, blank_rects=()):
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
        replace_digest: None for an exclusively new output. To replace an
            existing verified output, pass the SHA-256 observed during the
            ownership preflight; publication revalidates it before replacing.
        publication_guard: optional no-argument callback used by the batch
            caller to re-check the wider semantic figure slot immediately
            before and after publication. A post-publication failure
            conditionally withdraws the new crop or restores the predecessor.
        return_publication: preserve the historical three-tuple by default.
            When true, append the exact publication snapshot returned by the
            guarded filesystem operation. Ownership callers must use this
            snapshot rather than re-reading a pathname that another process
            can replace after publication.
        blank_rects: rects in the page's displayed space, in points, painted
            white in the render before the trim (`--blank-captions`).

    Returns:
        (rendered_size, final_size, blank) — the first two (width, height)
        tuples in pixels; when `trim` is False, they are identical. If
        `return_publication` is true, a fourth item is appended: the exact
        output snapshot, or None for a blank crop that published no file.

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
    if dpi <= 0:
        raise ValueError("dpi must be greater than zero")
    if trim_pad < 0:
        raise ValueError("trim pad must be zero or greater")
    if not 0 <= trim_tolerance <= 254:
        raise ValueError("trim tolerance must be between 0 and 254")
    raw_rect = tuple(float(v) for v in bbox)
    if len(raw_rect) != 4 or not all(math.isfinite(v) for v in raw_rect):
        raise ValueError("crop rect must contain four finite coordinates")
    rect = fitz.Rect(*raw_rect)
    if rect.width <= 0 or rect.height <= 0:
        raise ValueError(
            f"degenerate crop rect {tuple(round(v, 1) for v in rect)} "
            f"({rect.width:.1f}x{rect.height:.1f}) — nothing to render"
        )
    page = doc[page_idx]
    _checked_visible_crop(page, rect, dpi, f"crop on page {page_idx + 1}")
    replace_snapshot = None
    if replace_digest is not None:
        replace_snapshot = _stable_output_snapshot(out_path)
        if replace_snapshot[1] != replace_digest:
            raise FileExistsError(
                errno.EEXIST,
                "verified output changed after preflight; refusing overwrite",
                out_path,
            )
    pix = page.get_pixmap(dpi=dpi, clip=rect)
    # The pixmap's own rect is the clip in page pixels, not crop-relative.
    for r in blank_rects:
        r = fitz.Rect(r) & rect
        if not r.is_empty:
            pix.set_rect((r * fitz.Matrix(dpi / 72, dpi / 72)).irect,
                         (255,) * pix.n)
    # Render and trim in a unique sibling directory outside the flat output
    # folder, then publish a complete inode with the guarded helper above.
    # Writing the final path directly meant an interrupted run (a
    # closed laptop lid, a killed batch) left a truncated PNG under the real
    # figure name — and every later run's idempotent "already exists" skip
    # then preserved the corrupt file forever, as a broken embed in Obsidian.
    # A sibling of `Sources/Images/` stays on the same filesystem for atomic
    # publication without exposing an unfinished render to Obsidian or to a
    # consumer that inventories every file in the flat folder. The `.png`
    # suffix remains because PyMuPDF and Pillow select the format from it.
    # Resolve the DIRECTORY for placement only. If Sources/Images is a symlink
    # onto another volume, its logical parent may be on the wrong filesystem;
    # the resolved sibling is still atomic with the requested final path.
    output_dir = os.path.realpath(os.path.dirname(out_path) or ".")
    stage_parent = os.path.dirname(output_dir)
    stage_dir = tempfile.mkdtemp(prefix=".figure-stage-", dir=stage_parent)
    keep_stage = False
    publication = None
    try:
        tmp_path = os.path.join(stage_dir, os.path.basename(out_path))
        pix.save(tmp_path)
        rendered_size = (pix.width, pix.height)
        if trim:
            _, final_size = trim_white_margins(
                tmp_path, pad=trim_pad, tolerance=trim_tolerance,
            )
        else:
            final_size = rendered_size
        blank = render_is_blank(tmp_path, tolerance=trim_tolerance)
        if blank is None:
            raise RuntimeError(
                "rendered PNG could not be read back for nonblank validation; "
                "refusing to publish it"
            )
        if blank:
            # Deliberately do NOT move it into place: an all-white PNG at a
            # figure's name is worse than no PNG at all — every consumer
            # embeds it, and the next run's "already exists" skip preserves it
            # forever. Leaving `out_path` untouched also means an `--overwrite`
            # re-crop that comes out blank cannot destroy the good figure that
            # is already there.
            os.remove(tmp_path)
        else:
            if replace_snapshot is not None:
                os.chmod(tmp_path, replace_snapshot[2])
            try:
                if publication_guard is None:
                    publication = _publish_staged(
                        tmp_path, out_path, replace_snapshot=replace_snapshot)
                else:
                    publication = _publish_staged(
                        tmp_path, out_path, replace_snapshot=replace_snapshot,
                        before_publish=publication_guard,
                        after_publish=publication_guard)
            except BaseException as exc:
                # Once a complete, nonblank PNG exists, every publication
                # failure retains that recoverable draft.  The shared helper's
                # recovery_path may name a displaced predecessor, so expose the
                # crop stage separately and fill recovery_path only when no
                # more specific recovery location already exists.
                keep_stage = True
                try:
                    exc.keep_stage = True
                    exc.staging_path = stage_dir
                    if not getattr(exc, "recovery_path", None):
                        exc.recovery_path = stage_dir
                except (AttributeError, TypeError):
                    pass
                raise
    finally:
        if not keep_stage:
            shutil.rmtree(stage_dir, ignore_errors=True)
    result = (rendered_size, final_size, blank)
    return result + (publication,) if return_publication else result


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
    from unittest import mock

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
                      ("1–2", "1-2"),
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
    msg = exits("parse_crop with an arbitrary label", parse_crop,
                "1:results*:1,2,3,4")
    ok("...a label outside the producer grammar is refused",
       msg and "whole-figure label" in msg)
    msg = exits("parse_crop with a fullwidth digit label", parse_crop,
                "1:\uff11:1,2,3,4")
    ok("...a non-ASCII digit is refused before it reaches a filename",
       msg and "whole-figure label" in msg)
    msg = exits("parse_crop with a NaN coordinate", parse_crop,
                "1:2:1,nan,3,4")
    ok("...non-finite coordinates are refused", msg and "finite" in msg)
    check("...while dotted, dashed and supplementary labels still pass",
          [parse_crop("1:%s:1,2,3,4" % lab)[1]
           for lab in ("2.1", "S2-3", "A.1", "10.5.3")],
          ["2-1", "S2-3", "A-1", "10-5-3"])
    # auto_fig_bbox puts the marker prefix before an appendix or SI label
    # (`Supplementary Figure A1` -> SA1; under --ed-prefix ED, `Extended Data
    # Figure S1` -> EDS1). The explicit repair must accept what the batch
    # wrote, or a bad automatic crop under such a name cannot be repaired.
    def crop_label(lab):
        try:
            return parse_crop("1:%s:1,2,3,4" % lab)[1]
        except SystemExit as exc:
            return "refused: %s" % exc.code

    check("...and marker-prefixed appendix and SI labels pass too",
          [crop_label(lab) for lab in ("SA1", "SA.1", "EDS1", "EDA2", "EDSI1")],
          ["SA1", "SA-1", "EDS1", "EDA2", "EDSI1"])
    for bad in ("1a", "EDED1", "SAB1"):
        msg = exits("parse_crop with label %r" % bad, parse_crop,
                    "1:%s:1,2,3,4" % bad)
        ok("...%r stays outside the producer grammar" % bad,
           msg and "whole-figure label" in msg)

    # --- _series_mismatch: a printed number is not always the label ------
    supp1 = [("S1", "Supplementary Figure 1", None)]
    check("a bare 1 beside Supplementary Figure 1 names that caption",
          _series_mismatch("1", supp1), ("Supplementary Figure 1", "S1"))
    check("...and the reverse (S1 on a main Figure 1 page) is named too",
          _series_mismatch("S1", [("1", "Figure 1", None)]),
          ("Figure 1", "1"))
    check("...as is a bare number beside an appendix caption",
          _series_mismatch("1-2", [("A1.2", "Figure A1.2", None)]),
          ("Figure A1.2", "A1-2"))
    check("a label some caption on the page carries is not a mismatch",
          _series_mismatch("1", supp1 + [("1", "Figure 1", None)]), None)
    check("ED1 beside a default-prefix Extended Data caption is not one",
          _series_mismatch("ED1", [("S1", "Extended Data Figure 1", None)]),
          None)
    check("a page without a caption of that number is not one (overleaf)",
          _series_mismatch("2", supp1), None)
    # An appendix label beside its S-prefixed form is the same mistake:
    # `Supplementary Figure A1` is SA1, and A1 would replace main Figure A1.
    check("a printed A1 beside Supplementary Figure A1 names that caption",
          _series_mismatch("A1", [("SA1", "Supplementary Figure A1", None)]),
          ("Supplementary Figure A1", "SA1"))
    check("...and the reverse (SA1 on a main Figure A1 page) is named too",
          _series_mismatch("SA1", [("A1", "Figure A1", None)]),
          ("Figure A1", "A1"))
    check("...as is a dotted appendix label (A.1 beside SA-1)",
          _series_mismatch("A-1", [("SA-1", "Supplementary Figure A.1", None)]),
          ("Supplementary Figure A.1", "SA-1"))
    check("EDA1 beside a default-prefix Extended Data Figure A1 is quiet",
          _series_mismatch("EDA1", [("SA1", "Extended Data Figure A1", None)]),
          None)
    check("EDS1 beside a default-prefix Extended Data Figure S1 is quiet",
          _series_mismatch("EDS1", [("S1", "Extended Data Figure S1", None)]),
          None)
    check("S1 beside Figure SI1 is quiet (a different series)",
          _series_mismatch("S1", [("SI1", "Figure SI1", None)]), None)

    # --- _extended_data_label: the ED form an --ed-prefix ED batch wrote --
    check("an Extended Data caption's default label has an ED form",
          [_extended_data_label(raw, label) for raw, label in (
              ("Extended Data Figure 1", "S1"),
              ("Extended Data Fig. 2-3", "S2-3"),
              ("Extended Data Figure A1", "SA1"),
              ("Extended Data Figure A.1", "SA-1"),
              ("Extended Data Figure S1", "S1"),
              ("Extended  data Figure SI1", "SI1"))],
          ["ED1", "ED2-3", "EDA1", "EDA-1", "EDS1", "EDSI1"])
    check("...and any other caption has none",
          [_extended_data_label(raw, label) for raw, label in (
              ("Supplementary Figure 1", "S1"), ("Figure S1", "S1"),
              ("Figure 1", "1"))],
          [None, None, None])

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
                with Image.open(path, formats=("PNG",)) as im:
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

            # (3) a figure drawn on a #FBFBFB panel is within tolerance of
            # white, so the panel read as margin and the trim kept only the
            # one dark mark on it. A real 1723x1147 figure came out 79x78 and
            # nothing looked at it.
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
            # ...as does an axes box on an off-white (248) scanned page: pale
            # tone on every side of the crop is the page, not a panel.
            p = _st_png(os.path.join(tmp, "trim_offwhite.png"), (600, 450),
                        (248, 248, 248),
                        [((80, 60, 520, 61), (0, 0, 0)),
                         ((80, 389, 520, 390), (0, 0, 0)),
                         ((80, 60, 81, 390), (0, 0, 0)),
                         ((519, 60, 520, 390), (0, 0, 0))])
            check("trim: an off-white page is trimmed to the figure",
                  trim_white_margins(p, pad=4), ((600, 450), (449, 339)))
            # ...and a 245-grey panel on a white page keeps the whole panel
            # plus padding, not just the mark on it (288x188). The trim cut
            # through such a panel and an explicit re-crop repeated the cut.
            p = _st_png(os.path.join(tmp, "trim_panel.png"), (400, 300),
                        (255, 255, 255),
                        [((20, 20, 379, 279), (245, 245, 245)),
                         ((60, 60, 339, 239), (0, 0, 0))])
            check("trim: a pale panel on a white page is kept whole",
                  trim_white_margins(p, pad=4), ((400, 300), (368, 268)))
            check("trim: the kept panel is what is on disk",
                  size_on_disk(p), (368, 268))

            # (4) an all-white crop: nothing to find, nothing to do.
            p = _st_png(os.path.join(tmp, "trim_white.png"), (80, 60),
                        (255, 255, 255))
            check("trim: an entirely white image",
                  trim_white_margins(p, pad=4), ((80, 60), (80, 60)))
            check("trim: the white file is untouched on disk",
                  size_on_disk(p), (80, 60))

            p = _st_png(os.path.join(tmp, "trim_bomb_warning.png"),
                        (100, 100), (255, 255, 255))
            trim_bomb_error = None
            with mock.patch.object(Image, "MAX_IMAGE_PIXELS", 6000):
                try:
                    trim_white_margins(p, pad=4)
                except ValueError as exc:
                    trim_bomb_error = str(exc)
            ok("trim: a decompression-bomb warning is a clear refusal",
               bool(trim_bomb_error and "Pillow's safety limit"
                    in trim_bomb_error))
            check("trim: a refused oversized PNG remains unchanged",
                  size_on_disk(p), (100, 100))

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
        render_root = os.path.join(tmp, "render-root")
        render_images = os.path.join(render_root, "Images")
        os.makedirs(render_images)
        out = os.path.join(render_images, "Doe_Figs_2025_fig_1.png")
        stage_parents = []
        real_mkdtemp = tempfile.mkdtemp

        def tracked_mkdtemp(*args, **kwargs):
            if kwargs.get("prefix") == ".figure-stage-":
                stage_parents.append(kwargs.get("dir"))
            return real_mkdtemp(*args, **kwargs)

        with mock.patch.object(tempfile, "mkdtemp",
                               side_effect=tracked_mkdtemp):
            rendered, final, blank = extract_one_figure(
                doc, 0, (100, 150, 500, 350), out, dpi=72, trim=False)
        check("extract_one_figure renders at the requested dpi",
              rendered, (400, 200))
        check("extract_one_figure without trim returns one size twice",
              final, rendered)
        check("extract_one_figure on a figure is not blank", blank, False)
        ok("extract_one_figure wrote the PNG", os.path.exists(out))
        check("render staging is outside the flat image folder",
              stage_parents, [os.path.realpath(render_root)])
        ok("no staging directory remains after publication",
           not [f for f in os.listdir(render_root)
                if f.startswith(".figure-stage-")])

        # A directory symlink can point to another volume. Staging must follow
        # the resolved output directory's parent.
        logical_root = os.path.join(tmp, "logical-root")
        logical_images = os.path.join(logical_root, "Images")
        os.makedirs(logical_root)
        os.symlink(render_images, logical_images)
        linked_stage_parents = []

        def tracked_linked_mkdtemp(*args, **kwargs):
            if kwargs.get("prefix") == ".figure-stage-":
                linked_stage_parents.append(kwargs.get("dir"))
            return real_mkdtemp(*args, **kwargs)

        linked_out = os.path.join(
            logical_images, "Doe_Figs_2025_fig_7.png")
        with mock.patch.object(tempfile, "mkdtemp",
                               side_effect=tracked_linked_mkdtemp):
            extract_one_figure(doc, 0, (100, 150, 500, 350), linked_out,
                               dpi=72, trim=False)
        ok("a symlinked output folder stages by its resolved parent",
           linked_stage_parents == [
               os.path.realpath(render_root)])
        ok("publication follows a symlinked output folder",
           os.path.isfile(os.path.join(
               render_images, "Doe_Figs_2025_fig_7.png")))
        state["n"] += 1
        try:
            extract_one_figure(doc, 0, (100, 150, 100, 350),
                               os.path.join(render_images,
                                            "Doe_Figs_2025_fig_2.png"))
            state["bad"] += 1
            print("FAIL extract_one_figure accepted a degenerate rect — "
                  "PyMuPDF answers one with a 1x1 PNG in the vault")
        except ValueError as exc:
            if "degenerate" not in str(exc):
                state["bad"] += 1
                print("FAIL extract_one_figure's degenerate message: %s" % exc)
        ok("nothing was written for the degenerate rect",
           not os.path.exists(os.path.join(render_images,
                                           "Doe_Figs_2025_fig_2.png")))
        ok("no staging directory survives a rejected rect",
           not [f for f in os.listdir(render_root)
                if f.startswith(".figure-stage-")])
        for label, kwargs in (
                ("non-positive DPI", {"dpi": 0}),
                ("negative trim pad", {"trim_pad": -1}),
                ("impossible trim tolerance", {"trim_tolerance": 255})):
            state["n"] += 1
            try:
                extract_one_figure(
                    doc, 0, (100, 150, 500, 350),
                    os.path.join(render_images, "invalid-option.png"), **kwargs)
                state["bad"] += 1
                print("FAIL extract_one_figure accepted %s" % label)
            except ValueError:
                pass
        oversized = os.path.join(render_images, "oversized-render.png")
        oversized_error = None
        try:
            extract_one_figure(
                doc, 0, (100, 150, 500, 350), oversized,
                dpi=100_000, trim=False)
        except ValueError as exc:
            oversized_error = str(exc)
        ok("extract_one_figure refuses an oversized raster before allocation",
           bool(oversized_error and "pre-render safety cap"
                in oversized_error))
        ok("an oversized raster creates no output or staging directory",
           not os.path.lexists(oversized)
           and not [f for f in os.listdir(render_root)
                    if f.startswith(".figure-stage-")])
        # A failure AFTER the render, which is the case the temp file exists
        # for: an interrupted run must not leave a half-written PNG under the
        # real figure name, where every later run's "already exists" skip
        # preserves it forever as a broken embed.
        blocked = os.path.join(render_images, "Doe_Figs_2025_fig_3.png")
        os.makedirs(blocked)
        blocked_error = None
        state["n"] += 1
        try:
            extract_one_figure(doc, 0, (100, 150, 500, 350), blocked, dpi=72,
                               trim=False)
            state["bad"] += 1
            print("FAIL extract_one_figure reported success writing onto a "
                  "directory")
        except OSError as exc:
            blocked_error = exc
        blocked_stage = getattr(blocked_error, "staging_path", None)
        ok("a complete crop is retained and reported when publication fails late",
           bool(blocked_stage and os.path.isdir(blocked_stage)
                and os.path.isfile(os.path.join(
                    blocked_stage, os.path.basename(blocked)))))
        if blocked_stage:
            shutil.rmtree(blocked_stage)

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
            bomb_warning = _st_png(
                os.path.join(tmp, "decompression_warning.png"), (100, 100),
                (255, 255, 255))
            with mock.patch.object(Image, "MAX_IMAGE_PIXELS", 6000):
                check("a decompression-bomb warning fails closed",
                      render_is_blank(bomb_warning), None)
            real_import = __import__

            def import_without_pillow(name, *args, **kwargs):
                if name == "PIL" or name.startswith("PIL."):
                    raise ImportError("injected missing Pillow")
                return real_import(name, *args, **kwargs)

            with mock.patch("builtins.__import__",
                            side_effect=import_without_pillow):
                check("render_is_blank falls back to PyMuPDF without Pillow",
                      render_is_blank(white), True)
                check("the no-Pillow fallback still sees real content",
                      render_is_blank(marked), False)
            unreadable = os.path.join(tmp, "not-a-readable.png")
            with open(unreadable, "wb") as fh:
                fh.write(b"not an image")
            check("two failed image readers return cannot-verify",
                  render_is_blank(unreadable), None)

            blank_out = os.path.join(render_images,
                                     "Doe_Figs_2025_fig_9.png")
            rendered, final, blank = extract_one_figure(
                doc, 0, (100, 450, 500, 700), blank_out, dpi=72)
            check("extract_one_figure reports an all-white render", blank, True)
            check("...and still reports the size it rendered",
                  rendered, (400, 250))
            ok("...and writes NOTHING — a white PNG at a figure's name embeds "
               "everywhere and the next run's skip preserves it forever",
               not os.path.exists(blank_out))
            ok("...leaving no staging directory behind",
               not [f for f in os.listdir(render_root)
                    if f.startswith(".figure-stage-")])
            # ...and it cannot destroy a good figure that is already there,
            # which an --overwrite re-crop would otherwise do.
            keep = os.path.join(render_images, "Doe_Figs_2025_fig_8.png")
            _st_png(keep, (12, 12), (10, 20, 30))
            before = open(keep, "rb").read()
            _r, _f, blank = extract_one_figure(doc, 0, (100, 450, 500, 700),
                                               keep, dpi=72)
            check("a blank re-render leaves the existing figure alone",
                  (blank, open(keep, "rb").read() == before), (True, True))

        # A reader failure is not evidence that the crop contains pixels.
        # This is especially reachable under --no-trim, where Pillow is not a
        # required dependency. Fail closed before either publication mode.
        unverifiable = os.path.join(render_images,
                                    "Doe_Figs_2025_fig_unverifiable.png")
        with mock.patch.dict(globals(), {"render_is_blank": lambda *a, **kw: None}):
            state["n"] += 1
            try:
                extract_one_figure(doc, 0, (100, 150, 500, 350), unverifiable,
                                   dpi=72, trim=False)
                state["bad"] += 1
                print("FAIL an unverifiable staged PNG was published")
            except RuntimeError as exc:
                if "refusing to publish" not in str(exc):
                    state["bad"] += 1
                    print("FAIL unverifiable-PNG refusal was unclear: %s" % exc)
        ok("an unverifiable staged PNG leaves no output",
           not os.path.lexists(unverifiable))

        # A safe publish needs a hard link on the target filesystem. Preserve
        # that capability diagnosis; wrapping it as FileExistsError would make
        # the batch blame a nonexistent competing file.
        no_link_out = os.path.join(
            render_images, "Doe_Figs_2025_fig-no-hard-link.png")

        def refuse_hard_link(source, target, *args, **kwargs):
            raise atomic_move.LinkUnavailable(
                source, target,
                OSError(errno.ENOTSUP, "injected filesystem has no hard links"))

        no_link_error = None
        with mock.patch.object(atomic_move, "publish_new",
                               side_effect=refuse_hard_link):
            try:
                extract_one_figure(
                    doc, 0, (100, 150, 500, 350), no_link_out,
                    dpi=72, trim=False)
            except Exception as exc:
                no_link_error = exc
        check("hard-link capability failures retain their concrete type",
              (isinstance(no_link_error, atomic_move.LinkUnavailable),
               isinstance(no_link_error, FileExistsError),
               os.path.lexists(no_link_out),
               os.path.isfile(os.path.join(
                   getattr(no_link_error, "staging_path", ""),
                   os.path.basename(no_link_out))),
               getattr(no_link_error, "recovery_path", None)
               == getattr(no_link_error, "staging_path", None)),
              (True, False, False, True, True))
        if getattr(no_link_error, "staging_path", None):
            shutil.rmtree(no_link_error.staging_path)

        # New publication must be exclusive at the final operation. Simulate
        # another producer taking the name after rendering but before link().
        late_new = os.path.join(render_images, "Doe_Figs_2025_fig_late-new.png")
        late_new_bytes = b"late foreign occupant at a formerly empty name"
        real_link = os.link

        def occupy_before_link(source, target, *args, **kwargs):
            if target == late_new and not os.path.lexists(target):
                with open(target, "wb") as fh:
                    fh.write(late_new_bytes)
            return real_link(source, target, *args, **kwargs)

        late_new_error = None
        with mock.patch.object(os, "link", side_effect=occupy_before_link):
            state["n"] += 1
            try:
                extract_one_figure(doc, 0, (100, 150, 500, 350), late_new,
                                   dpi=72, trim=False)
                state["bad"] += 1
                print("FAIL exclusive publication replaced a late occupant")
            except FileExistsError as exc:
                late_new_error = exc
                if "occupied after preflight" not in str(exc):
                    state["bad"] += 1
                    print("FAIL late-occupant refusal was unclear: %s" % exc)
        check("exclusive publication preserves the late occupant",
              (open(late_new, "rb").read(),
               os.path.isfile(os.path.join(
                   getattr(late_new_error, "staging_path", ""),
                   os.path.basename(late_new)))),
              (late_new_bytes, True))

        # Publication includes readback. Mutating the just-linked inode also
        # mutates its private hard link, so the shared helper must compare
        # against the snapshot taken before publication and retain the newer
        # public bytes rather than report success.
        post_new = os.path.join(render_images,
                                "Doe_Figs_2025_fig_post-new.png")
        post_new_bytes = b"new writer changed bytes after the public link"
        injected_post_new = {"done": False}
        real_link_noreplace = atomic_move.link_noreplace

        def mutate_new_after_link(source, target):
            answer = real_link_noreplace(source, target)
            if target == post_new and not injected_post_new["done"]:
                injected_post_new["done"] = True
                with open(target, "wb") as fh:
                    fh.write(post_new_bytes)
            return answer

        with mock.patch.object(atomic_move, "link_noreplace",
                               side_effect=mutate_new_after_link):
            state["n"] += 1
            try:
                extract_one_figure(doc, 0, (100, 150, 500, 350), post_new,
                                   dpi=72, trim=False)
                state["bad"] += 1
                print("FAIL post-link mutation was reported as a new crop")
            except FileExistsError as exc:
                if "differs from its staged snapshot" not in str(exc):
                    state["bad"] += 1
                    print("FAIL post-link readback refusal was unclear: %s" % exc)
        check("new publication retains bytes written after its link",
              open(post_new, "rb").read(), post_new_bytes)

        # For a verified replacement, inject a foreign occupant after the
        # caller's digest preflight. The guarded displacement must restore it,
        # never let the new crop overwrite it through a final CAS gap.
        late_replace = os.path.join(
            render_images, "Doe_Figs_2025_fig_late-replace.png")
        with open(late_replace, "wb") as fh:
            fh.write(b"verified old output")
        replace_digest = file_digest(late_replace)
        late_replace_bytes = b"foreign replacement after digest preflight"
        real_publish = _publish_staged

        def change_before_guarded_publish(staged, target,
                                          replace_snapshot=None):
            with open(target, "wb") as fh:
                fh.write(late_replace_bytes)
            return real_publish(staged, target,
                                replace_snapshot=replace_snapshot)

        with mock.patch.dict(
                globals(), {"_publish_staged": change_before_guarded_publish}):
            state["n"] += 1
            try:
                extract_one_figure(
                    doc, 0, (100, 150, 500, 350), late_replace,
                    dpi=72, trim=False, replace_digest=replace_digest,
                )
                state["bad"] += 1
                print("FAIL verified overwrite replaced a late foreign occupant")
            except FileExistsError as exc:
                if "changed after planning" not in str(exc):
                    state["bad"] += 1
                    print("FAIL replacement-race refusal was unclear: %s" % exc)
        check("verified overwrite preserves the foreign replacement",
              open(late_replace, "rb").read(), late_replace_bytes)

        # Close the narrower CAS gap too: the name still held the expected
        # inode during the helper's observation and digest, then a foreign
        # inode arrived immediately before displacement. The move captures
        # that foreign inode privately, detects it, and restores it.
        cas_gap = os.path.join(render_images,
                               "Doe_Figs_2025_fig_cas-gap.png")
        with open(cas_gap, "wb") as fh:
            fh.write(b"verified inode before guarded displacement")
        cas_digest = file_digest(cas_gap)
        cas_foreign_bytes = b"foreign inode arriving after final observation"
        real_move = atomic_move.move_noreplace

        def replace_before_displacement(source, target, expected=None,
                                        **kwargs):
            if source == cas_gap:
                os.unlink(source)
                with open(source, "wb") as fh:
                    fh.write(cas_foreign_bytes)
            return real_move(source, target, expected=expected, **kwargs)

        with mock.patch.object(atomic_move, "move_noreplace",
                               side_effect=replace_before_displacement):
            state["n"] += 1
            try:
                extract_one_figure(
                    doc, 0, (100, 150, 500, 350), cas_gap,
                    dpi=72, trim=False, replace_digest=cas_digest,
                )
                state["bad"] += 1
                print("FAIL guarded displacement published across a CAS gap")
            except FileExistsError as exc:
                if "different occupant" not in str(exc):
                    state["bad"] += 1
                    print("FAIL CAS-gap refusal was unclear: %s" % exc)
        check("the occupant arriving in the CAS gap is restored intact",
              open(cas_gap, "rb").read(), cas_foreign_bytes)

        # A writer replacing the newly published name before readback keeps
        # that name. The verified predecessor is retained in a named sibling
        # recovery directory, and a successful replacement preserves mode.
        post_replace = os.path.join(
            render_images, "Doe_Figs_2025_fig_post-replace.png")
        post_replace_old = b"verified predecessor before readback race"
        with open(post_replace, "wb") as fh:
            fh.write(post_replace_old)
        os.chmod(post_replace, 0o600)
        post_replace_mode = stat.S_IMODE(os.stat(post_replace).st_mode)
        post_replace_digest = file_digest(post_replace)
        post_replace_late = b"writer replacing the public link before readback"
        injected_post_replace = {"done": False}

        def mutate_replacement_after_link(source, target):
            answer = real_link_noreplace(source, target)
            if target == post_replace and not injected_post_replace["done"]:
                injected_post_replace["done"] = True
                intruder = target + ".intruder"
                with open(intruder, "wb") as fh:
                    fh.write(post_replace_late)
                os.replace(intruder, target)
            return answer

        with mock.patch.object(
                atomic_move, "link_noreplace",
                side_effect=mutate_replacement_after_link):
            state["n"] += 1
            try:
                extract_one_figure(
                    doc, 0, (100, 150, 500, 350), post_replace,
                    dpi=72, trim=False,
                    replace_digest=post_replace_digest,
                )
                state["bad"] += 1
                print("FAIL post-link replacement mutation reported success")
            except FileExistsError as exc:
                if "differs from the staged snapshot" not in str(exc):
                    state["bad"] += 1
                    print("FAIL replacement readback refusal was unclear: %s" % exc)
        check("replacement retains the writer that won before readback",
              open(post_replace, "rb").read(), post_replace_late)
        post_recovery_dirs = [
            os.path.join(render_root, name) for name in os.listdir(render_root)
            if name.startswith(".figure-recovery-")
        ]
        check("replacement readback failure preserves one predecessor",
              len(post_recovery_dirs), 1)
        if post_recovery_dirs:
            recovered = os.path.join(post_recovery_dirs[0],
                                     os.path.basename(post_replace))
            check("recovered predecessor retains its exact bytes and mode",
                  (open(recovered, "rb").read(),
                   stat.S_IMODE(os.stat(recovered).st_mode)),
                  (post_replace_old, post_replace_mode))
            shutil.rmtree(post_recovery_dirs[0])
        else:
            check("missing recovered predecessor retains bytes and mode",
                  None, (post_replace_old, post_replace_mode))

        mode_replace = os.path.join(
            render_images, "Doe_Figs_2025_fig_mode.png")
        with open(mode_replace, "wb") as fh:
            fh.write(b"verified mode predecessor")
        os.chmod(mode_replace, 0o640)
        mode_before_replace = stat.S_IMODE(os.stat(mode_replace).st_mode)
        mode_digest = file_digest(mode_replace)
        extract_one_figure(doc, 0, (100, 150, 500, 350), mode_replace,
                           dpi=72, trim=False, replace_digest=mode_digest)
        check("successful replacement preserves output permissions",
              stat.S_IMODE(os.stat(mode_replace).st_mode), mode_before_replace)

        # If a second writer arrives after the verified predecessor was
        # displaced, it keeps the public name. Preserve the predecessor in a
        # reported sibling recovery directory because both cannot be restored
        # to one pathname without clobbering one of them.
        after_displace = os.path.join(
            render_images, "Doe_Figs_2025_fig_after-displace.png")
        after_displace_bytes = b"verified predecessor for recovery"
        with open(after_displace, "wb") as fh:
            fh.write(after_displace_bytes)
        after_displace_digest = file_digest(after_displace)
        second_writer_bytes = b"second writer after guarded displacement"
        injected_second_writer = {"done": False}

        def occupy_after_displacement(source, target, *args, **kwargs):
            if target == after_displace and not injected_second_writer["done"]:
                injected_second_writer["done"] = True
                with open(target, "wb") as fh:
                    fh.write(second_writer_bytes)
            return real_link(source, target, *args, **kwargs)

        with mock.patch.object(os, "link",
                               side_effect=occupy_after_displacement):
            state["n"] += 1
            try:
                extract_one_figure(
                    doc, 0, (100, 150, 500, 350), after_displace,
                    dpi=72, trim=False,
                    replace_digest=after_displace_digest,
                )
                state["bad"] += 1
                print("FAIL publication clobbered a post-displacement writer")
            except FileExistsError as exc:
                if "preserved at" not in str(exc):
                    state["bad"] += 1
                    print("FAIL recovery location was not reported: %s" % exc)
        check("the post-displacement writer keeps the public name",
              open(after_displace, "rb").read(), second_writer_bytes)
        recovery_dirs = [
            os.path.join(render_root, name) for name in os.listdir(render_root)
            if name.startswith(".figure-recovery-")
        ]
        check("one recovery directory preserves the displaced predecessor",
              len(recovery_dirs), 1)
        if recovery_dirs:
            recovered = os.path.join(recovery_dirs[0],
                                     os.path.basename(after_displace))
            check("the reported recovery copy retains its exact bytes",
                  open(recovered, "rb").read(), after_displace_bytes)
            shutil.rmtree(recovery_dirs[0])
        else:
            # Keep a stable tally even when the preceding assertion failed.
            check("the missing recovery copy retains its exact bytes", None,
                  after_displace_bytes)
        retained_stages = [
            os.path.join(render_root, name) for name in os.listdir(render_root)
            if name.startswith(".figure-stage-")
        ]
        ok("publication races retain complete crops in reported staging",
           bool(retained_stages) and all(
               any(name.endswith(".png") and os.path.isfile(os.path.join(stage, name))
                   for name in os.listdir(stage))
               for stage in retained_stages))
        for stage in retained_stages:
            shutil.rmtree(stage)
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
                    state["n"] += 1
                    state["bad"] += 1
                    print("FAIL main() raised an unhandled %s: %s" %
                          (type(exc).__name__, exc))
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
        check("a first explicit crop creates its ownership manifest",
              read_manifest(os.path.join(outdir, MANIFEST_FILE)),
              {os.path.basename(png): file_digest(png)})

        # A PDF folder that cannot be listed keeps the typed name.
        unlisted_dir = os.path.join(tmp, "unlisted")
        os.makedirs(unlisted_dir)
        unlisted_pdf = shutil.copy(pdf, unlisted_dir)
        real_listdir = os.listdir

        def listdir_refusing_pdf_folder(path="."):
            if (not isinstance(path, int) and os.path.abspath(
                    os.fspath(path)) == os.path.abspath(unlisted_dir)):
                raise PermissionError("injected")
            return real_listdir(path)

        unlisted_out = os.path.join(tmp, "UnlistedImages")
        with mock.patch.object(os, "listdir", listdir_refusing_pdf_folder):
            code, so, se = run([unlisted_pdf, "--out", unlisted_out,
                                "--crop", "1:1:100,150,500,350", "--dpi",
                                "72", "--no-trim"])
        check("an unlistable PDF folder keeps the typed name",
              (code, "using the typed name" in so, os.path.exists(
                  os.path.join(unlisted_out, "Doe_Figs_2025_fig_1.png"))),
              (0, True, True))

        twin_dir = os.path.join(tmp, "ExtensionTwin")
        os.makedirs(twin_dir)
        twin = os.path.join(twin_dir, "Doe_Figs_2025_fig_2.webp")
        with open(twin, "wb") as fh:
            fh.write(b"another producer's same-label image")
        code, so, se = run([
            pdf, "--out", twin_dir, "--stem", "Doe_Figs_2025",
            "--crop", "1:2:100,150,500,350", "--dpi", "72", "--no-trim",
        ])
        ok("an extension twin blocks an explicit PNG crop",
           code != 0 and "ambiguous extension" in str(code))
        check("the extension-twin refusal preserves the existing file",
              open(twin, "rb").read(), b"another producer's same-label image")
        ok("the extension-twin refusal publishes no PNG or manifest",
           not os.path.exists(os.path.join(
               twin_dir, "Doe_Figs_2025_fig_2.png"))
           and not os.path.exists(os.path.join(twin_dir, MANIFEST_FILE)))

        # A named repair owns one slot. An unrelated nested figure remains a
        # reported inventory defect, but does not turn this free slot into a
        # collision. A nested twin of the requested figure still blocks it.
        nested_dir = os.path.join(twin_dir, "old")
        os.makedirs(nested_dir)
        nested_figure = os.path.join(nested_dir, "Doe_Figs_2025_fig_3.png")
        _st_png(nested_figure, (20, 20), (80, 140, 200))
        nested_bytes = open(nested_figure, "rb").read()
        code, so, se = run([
            pdf, "--out", twin_dir, "--stem", "Doe_Figs_2025",
            "--crop", "1:1:100,150,500,350", "--dpi", "72", "--no-trim",
        ])
        check("a different nested figure does not block a named free crop",
              (code, os.path.isfile(os.path.join(
                  twin_dir, "Doe_Figs_2025_fig_1.png")),
               open(nested_figure, "rb").read()), (0, True, nested_bytes))
        code, so, se = run([
            pdf, "--out", twin_dir, "--stem", "Doe_Figs_2025",
            "--crop", "1:3:100,150,500,350", "--dpi", "72", "--no-trim",
        ])
        ok("a nested twin still blocks its exact figure slot",
           code != 0 and not os.path.exists(os.path.join(
               twin_dir, "Doe_Figs_2025_fig_3.png")))

        protected_manifest = os.path.join(twin_dir, MANIFEST_FILE)
        protected_body = open(protected_manifest, "rb").read()
        os.chmod(protected_manifest, 0o444)
        try:
            # Root/ACL-enabled processes may still pass os.access; the explicit
            # mode protection must be respected before publishing any crop.
            with mock.patch.object(os, "access", return_value=True):
                code, so, se = run([
                    pdf, "--out", twin_dir, "--stem", "Doe_Figs_2025",
                    "--crop", "1:4:100,150,500,350", "--dpi", "72", "--no-trim",
                ])
            check("a protected manifest refuses an explicit crop before publication",
                  (code != 0, os.path.exists(os.path.join(
                      twin_dir, "Doe_Figs_2025_fig_4.png")),
                   open(protected_manifest, "rb").read()),
                  (True, False, protected_body))
        finally:
            os.chmod(protected_manifest, 0o644)

        cli_no_link_root = os.path.join(tmp, "CliNoHardLinks")
        cli_no_link_dir = os.path.join(cli_no_link_root, "Images")
        with mock.patch.object(atomic_move, "publish_new",
                               side_effect=refuse_hard_link):
            code, so, se = run([
                pdf, "--out", cli_no_link_dir, "--stem", "Doe_Figs_2025",
                "--crop", "1:2:100,150,500,350", "--dpi", "72", "--no-trim",
            ])
        cli_no_link_stages = [
            os.path.join(cli_no_link_root, name)
            for name in os.listdir(cli_no_link_root)
            if name.startswith(".figure-stage-")
        ]
        check("the explicit CLI reports and retains an unpublished crop",
              (code != 0, "staged crop preserved at" in str(code),
               len(cli_no_link_stages),
               bool(cli_no_link_stages and os.path.isfile(os.path.join(
                   cli_no_link_stages[0], "Doe_Figs_2025_fig_2.png")))),
              (True, True, 1, True))
        for stage in cli_no_link_stages:
            shutil.rmtree(stage)

        unicode_slot_dir = os.path.join(tmp, "UnicodeSlot")
        os.makedirs(unicode_slot_dir)
        unicode_nfd = os.path.join(
            unicode_slot_dir, "Garci\u0301a_Study_2025_fig_1.png")
        unicode_nfc = os.path.join(
            unicode_slot_dir, "García_Study_2025_fig_1.png")
        with open(unicode_nfd, "wb") as fh:
            fh.write(b"one filesystem entry")
        conflict = _figure_slot_conflict(
            unicode_slot_dir, "García_Study_2025", "1", unicode_nfc)
        if os.path.lexists(unicode_nfc):
            check("an NFD spelling of the same output entry is not a twin",
                  conflict, None)
        else:
            ok("a distinct NFD pathname remains a portable-slot twin",
               conflict is not None)
        compact_dir = os.path.join(tmp, "CompactSlot")
        os.makedirs(compact_dir)
        with open(os.path.join(compact_dir, "Doe_Figs_2025_fig3.png"), "wb") as fh:
            fh.write(b"a pre-convergence crop")
        ok("a legacy separator-less name holds its figure slot",
           _figure_slot_conflict(compact_dir, "Doe_Figs_2025", "3", os.path.join(
               compact_dir, "Doe_Figs_2025_fig_3.png")) is not None)
        # A dry run may hand in one inventory for all of a PDF's slots; the
        # answer is the one a fresh inventory gives, slot by slot.
        compact_inventory = inventory_source_figures(compact_dir, "Doe_Figs_2025")
        check("a reused inventory answers each slot like a fresh one",
              [_figure_slot_conflict(
                  compact_dir, "Doe_Figs_2025", suffix, os.path.join(
                      compact_dir, "Doe_Figs_2025_fig_%s.png" % suffix),
                  inventory=compact_inventory) is not None
               for suffix in ("3", "4")], [True, False])

        # Skip-existing is the default, and it is what keeps a hand-set crop
        # from being undone by the next batch run.
        # Stand in for a crop the user set by hand: distinguishable bytes, so
        # "skipped" and "overwritten" are told apart by content, not mtime.
        with open(png, "wb") as fh:
            fh.write(b"a hand-set crop, not this run's render")
        stamp = open(png, "rb").read()
        # An exact --adopt-legacy selection (or an earlier tracked run)
        # established ownership before an explicit replacement is allowed.
        write_manifest(os.path.join(outdir, MANIFEST_FILE),
                       {os.path.basename(png): file_digest(png)},
                       expected=read_sidecar(
                           os.path.join(outdir, MANIFEST_FILE))[1])
        code, so, se = run(base + ["--crop", "1:1:100,150,500,350", "--dpi",
                                   "72", "--no-trim"])
        check("a second run exits 0", code, 0)
        ok("the second run says it skipped", "Exists, skipped" in so)
        check("the existing file is untouched", open(png, "rb").read(), stamp)
        code, so, se = run(base + ["--crop", "1:1:100,150,500,350", "--dpi",
                                   "72", "--no-trim", "--overwrite"])
        ok("--overwrite replaces it", open(png, "rb").read() != stamp)
        ok("--overwrite says it wrote", "Wrote" in so)

        # The CLI preflights the whole crop list before rendering. A file can
        # still arrive after that preflight, so exercise both publication
        # modes at the point the low-level writer is called.
        real_extract_one = extract_one_figure
        cli_new_dir = os.path.join(tmp, "CliLateNew")
        cli_new_path = os.path.join(cli_new_dir,
                                    "Doe_Figs_2025_fig_5.png")
        cli_new_bytes = b"another producer won the new-name race"

        def inject_cli_new(doc_arg, page_arg, bbox_arg, out_path, *args, **kwargs):
            with open(out_path, "wb") as fh:
                fh.write(cli_new_bytes)
            return real_extract_one(doc_arg, page_arg, bbox_arg, out_path,
                                    *args, **kwargs)

        with mock.patch.dict(globals(), {"extract_one_figure": inject_cli_new}):
            code, so, se = run([
                pdf, "--out", cli_new_dir, "--stem", "Doe_Figs_2025",
                "--crop", "1:5:100,150,500,350", "--dpi", "72", "--no-trim",
            ])
        ok("an explicit new crop refuses a name occupied after CLI preflight",
           code != 0 and "occupied after preflight" in str(code))
        check("the explicit new crop preserves that late occupant",
              open(cli_new_path, "rb").read(), cli_new_bytes)

        cli_replace_dir = os.path.join(tmp, "CliLateReplace")
        os.makedirs(cli_replace_dir)
        cli_replace_path = os.path.join(
            cli_replace_dir, "Doe_Figs_2025_fig_6.png")
        with open(cli_replace_path, "wb") as fh:
            fh.write(b"the extractor's verified previous output")
        cli_replace_digest = file_digest(cli_replace_path)
        write_manifest(
            os.path.join(cli_replace_dir, MANIFEST_FILE),
            {os.path.basename(cli_replace_path): cli_replace_digest},
            expected=read_sidecar(
                os.path.join(cli_replace_dir, MANIFEST_FILE))[1],
        )
        cli_replace_bytes = b"foreign bytes written while the crop rendered"

        def inject_cli_replace(doc_arg, page_arg, bbox_arg, out_path,
                               *args, **kwargs):
            with open(out_path, "wb") as fh:
                fh.write(cli_replace_bytes)
            return real_extract_one(doc_arg, page_arg, bbox_arg, out_path,
                                    *args, **kwargs)

        with mock.patch.dict(
                globals(), {"extract_one_figure": inject_cli_replace}):
            code, so, se = run([
                pdf, "--out", cli_replace_dir, "--stem", "Doe_Figs_2025",
                "--crop", "1:6:100,150,500,350", "--dpi", "72", "--no-trim",
                "--overwrite",
            ])
        ok("an explicit overwrite refuses bytes changed after CLI preflight",
           code != 0 and "changed after preflight" in str(code))
        check("the explicit overwrite preserves the late foreign bytes",
              open(cli_replace_path, "rb").read(), cli_replace_bytes)
        check("a refused explicit overwrite does not forge a new manifest digest",
              read_manifest(os.path.join(cli_replace_dir, MANIFEST_FILE))[
                  os.path.basename(cli_replace_path)],
              cli_replace_digest)

        # The publication CAS and manifest CAS cannot be one filesystem
        # transaction. A different producer may replace the public name in
        # between; the sidecar must describe the exact inode this crop
        # published, never whatever bytes happen to occupy the path afterward.
        cli_claim_dir = os.path.join(tmp, "CliPostPublishReplacement")
        os.makedirs(cli_claim_dir)
        cli_claim_path = os.path.join(
            cli_claim_dir, "Doe_Figs_2025_fig_8.png")
        cli_claim_foreign = b"foreign replacement after explicit publication"
        cli_claim_published = {}

        def inject_cli_post_publish(doc_arg, page_arg, bbox_arg, out_path,
                                    *args, **kwargs):
            answer = real_extract_one(
                doc_arg, page_arg, bbox_arg, out_path, *args, **kwargs)
            cli_claim_published["digest"] = answer[3][1]
            replacement = out_path + ".foreign"
            with open(replacement, "wb") as fh:
                fh.write(cli_claim_foreign)
            os.replace(replacement, out_path)
            return answer

        with mock.patch.dict(
                globals(), {"extract_one_figure": inject_cli_post_publish}):
            code, so, se = run([
                pdf, "--out", cli_claim_dir, "--stem", "Doe_Figs_2025",
                "--crop", "1:8:100,150,500,350", "--dpi", "72", "--no-trim",
            ])
        cli_claim_manifest = read_manifest(
            os.path.join(cli_claim_dir, MANIFEST_FILE))
        check("an explicit crop records its publication, not a later path occupant",
              (code, cli_claim_manifest[os.path.basename(cli_claim_path)],
               file_digest(cli_claim_path) == cli_claim_published["digest"]),
              (0, cli_claim_published["digest"], False))
        code, so, se = run([
            pdf, "--out", cli_claim_dir, "--stem", "Doe_Figs_2025",
            "--crop", "1:8:100,150,500,350", "--dpi", "72", "--no-trim",
            "--overwrite",
        ])
        ok("the exact publication digest makes that later occupant unowned",
           code != 0 and "bytes changed" in str(code))
        check("a later explicit overwrite preserves the foreign replacement",
              open(cli_claim_path, "rb").read(), cli_claim_foreign)

        # The crop and its ownership record are separate publications. If a
        # concurrent run updates the manifest while this crop renders, retain
        # that update and fail loudly instead of replacing it with this run's
        # stale in-memory map.
        late_manifest_dir = os.path.join(tmp, "CliLateManifest")
        os.makedirs(late_manifest_dir)
        late_manifest_path = os.path.join(late_manifest_dir, MANIFEST_FILE)
        write_manifest(late_manifest_path,
                       {"Keep_fig_1.png": "a" * 64},
                       expected=read_sidecar(late_manifest_path)[1])
        late_manifest_body = (
            "Keep_fig_1.png\t" + "a" * 64 + "\n"
            "Concurrent_fig_2.png\t" + "b" * 64 + "\n")

        def inject_cli_manifest_update(doc_arg, page_arg, bbox_arg, out_path,
                                       *args, **kwargs):
            answer = real_extract_one(doc_arg, page_arg, bbox_arg, out_path,
                                      *args, **kwargs)
            with open(late_manifest_path, "w", encoding="utf-8", newline="") as fh:
                fh.write(late_manifest_body)
            return answer

        with mock.patch.dict(
                globals(), {"extract_one_figure": inject_cli_manifest_update}):
            code, so, se = run([
                pdf, "--out", late_manifest_dir, "--stem", "Doe_Figs_2025",
                "--crop", "1:7:100,150,500,350", "--dpi", "72", "--no-trim",
            ])
        ok("an explicit crop reports a concurrent manifest update",
           code != 0 and "ownership record could not be updated" in str(code))
        check("the explicit crop preserves the concurrent manifest bytes",
              open(late_manifest_path, encoding="utf-8").read(),
              late_manifest_body)
        ok("the failed manifest CAS does not claim the newly written crop",
           "Doe_Figs_2025_fig_7.png" not in read_manifest(late_manifest_path))

        legacy = os.path.join(tmp, "Legacy")
        os.makedirs(legacy)
        foreign = os.path.join(legacy, "Doe_Figs_2025_fig_1.png")
        _st_png(foreign, (24, 18), (180, 20, 40))
        foreign_bytes = open(foreign, "rb").read()
        for overwrite in ([], ["--overwrite"]):
            code, so, se = run([pdf, "--out", legacy, "--stem", "Doe_Figs_2025",
                               "--crop", "1:2:100,150,500,350",
                               "--crop", "1:1:100,150,500,350"] + overwrite)
            ok("an untracked legacy occupant is refused before any crop", code != 0)
            check("a refused legacy crop preserves the other producer's image",
                  open(foreign, "rb").read(), foreign_bytes)
            check("legacy preflight leaves the entire image folder unchanged",
                  sorted(os.listdir(legacy)), [os.path.basename(foreign)])

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

        # A caption in the top-right corner of an L-shaped figure: every rect
        # holding the whole figure holds caption text. --blank-captions whites
        # out the caption's words and keeps the figure, on a /Rotate page too.
        for rotation in (0, 90):
            corner_pdf = os.path.join(tmp, "Doe_Corner%d_2025.pdf" % rotation)
            cdoc = fitz.open()
            cpage = cdoc.new_page(width=612, height=792)
            cpage.draw_rect(fitz.Rect(100, 150, 300, 400), color=None,
                            fill=(0.2, 0.3, 0.7))
            cpage.draw_rect(fitz.Rect(100, 400, 500, 550), color=None,
                            fill=(0.7, 0.2, 0.2))
            cpage.insert_text((320, 170), "Figure 1. An L-shaped figure whose",
                              fontsize=9)
            cpage.insert_text((320, 182), "caption sits in its top-right "
                              "corner.", fontsize=9)
            cpage.set_rotation(rotation)
            shown = cpage.rotation_matrix
            cdoc.save(corner_pdf)
            cdoc.close()
            crop = fitz.Rect(100, 150, 500, 550) * shown
            corner_args = [corner_pdf, "--crop", "1:1:%g,%g,%g,%g" % tuple(crop),
                           "--dpi", "72", "--no-trim"]
            corner_out = os.path.join(tmp, "Corner%d" % rotation)
            code, so, se = run(corner_args + ["--out", corner_out,
                                              "--blank-captions"])
            check("--blank-captions on a corner caption (rotation %d) exits 0 "
                  "unwarned" % rotation,
                  (code, "WARNING" in se, "blanked caption" in so),
                  (0, False, True))
            corner_png = os.path.join(corner_out,
                                      "Doe_Corner%d_2025_fig_1.png" % rotation)
            shot = (fitz.Pixmap(corner_png) if os.path.exists(corner_png)
                    else None)

            def colours(rect):
                r = fitz.Rect(rect) * shown
                return {shot.pixel(int(x - crop.x0), int(y - crop.y0))
                        for x in range(int(r.x0), int(r.x1))
                        for y in range(int(r.y0), int(r.y1))}

            check("...keeps the whole crop (rotation %d)" % rotation,
                  shot and (shot.width, shot.height), (400, 400))
            ok("...whites out the caption (rotation %d)" % rotation,
               shot is not None
               and colours((318, 158, 466, 187)) == {(255, 255, 255)})
            ok("...and keeps both blocks' fill (rotation %d)" % rotation,
               shot is not None and all(
                   len(c) == 1 and c != {(255, 255, 255)} for c in (
                       colours((280, 160, 300, 390)),
                       colours((310, 405, 490, 545)))))
        code, so, se = run([os.path.join(tmp, "Doe_Corner0_2025.pdf"),
                            "--crop", "1:1:100,150,500,550", "--dpi", "72",
                            "--no-trim", "--out", os.path.join(tmp, "Corner")])
        ok("...while the same crop without the flag still warns",
           "overlaps the caption" in se)
        code, so, se = run(base[:1] + ["--out", os.path.join(tmp, "NoCorner"),
                                       "--crop", "1:1:100,150,500,350",
                                       "--dpi", "72", "--no-trim",
                                       "--blank-captions"])
        ok("--blank-captions says when no caption was inside the crop",
           code == 0 and "nothing was blanked" in se)

        # `Supplementary Figure 1` is S1. Cropping it as `1` would write, and
        # with --overwrite replace, the main Figure 1 crop: say so by name.
        supp_pdf = _st_pdf(os.path.join(tmp, "Doe_Supp_2025.pdf"),
                           caption="Supplementary Figure 1. Synthetic.")
        supp_out = os.path.join(tmp, "SuppLabel")
        supp_base = [supp_pdf, "--out", supp_out, "--dpi", "72", "--no-trim"]
        code, so, se = run(supp_base + ["--crop", "1:S1:100,150,500,350"])
        check("the output label S1 on a Supplementary Figure 1 page is quiet",
              (code, "WARNING" in se), (0, False))
        code, so, se = run(supp_base + ["--crop", "1:1:100,150,500,350"])
        supp_main = os.path.join(supp_out, "Doe_Supp_2025_fig_1.png")
        ok("a bare printed number there is warned about by caption and file",
           code == 0 and "WARNING" in se
           and "'Supplementary Figure 1'" in se and "'S1'" in se
           and supp_main in se)
        code, so, se = run(supp_base + ["--crop", "1:1:100,150,500,350",
                                        "--overwrite"])
        ok("...and says --overwrite replaces the crop already there",
           "replaces the crop already there" in se)
        code, so, se = run(supp_base + ["--crop", "1:1:100,150,500,350",
                                        "--no-caption-check"])
        ok("...even when the caption-overlap check is off",
           "'Supplementary Figure 1'" in se)
        # The check runs under the default prefix, where `Extended Data
        # Figure 1` is S1. A PDF the batch extracted with --ed-prefix ED keeps
        # its Supplementary Figure 1 at S1, so the warning also names ED1.
        ed_pdf = _st_pdf(os.path.join(tmp, "Doe_ExtData_2025.pdf"),
                         caption="Extended Data Figure 1. Synthetic.")
        code, so, se = run([ed_pdf, "--out", os.path.join(tmp, "EdLabel"),
                            "--dpi", "72", "--no-trim",
                            "--crop", "1:1:100,150,500,350"])
        ok("a bare number on an Extended Data page names both S1 and ED1",
           code == 0 and "WARNING" in se
           and "'Extended Data Figure 1'" in se
           and "'S1' ('ED1' if this PDF uses --ed-prefix ED)" in se)
        code, so, se = run(supp_base + ["--crop", "1:1:100,150,500,350"])
        ok("...while a Supplementary caption's warning has no ED form",
           "WARNING" in se and "--ed-prefix ED" not in se)

        blank_cli = os.path.join(tmp, "BlankCli")
        code, so, se = run([
            pdf, "--out", blank_cli, "--stem", "Doe_Figs_2025",
            "--crop", "1:9:10,500,100,600", "--dpi", "72",
        ])
        check("a blank explicit crop exits non-zero", code, 1)
        ok("...and leaves no figure at the target name",
           not os.path.exists(os.path.join(blank_cli,
                                           "Doe_Figs_2025_fig_9.png")))

        duplicate_out = os.path.join(tmp, "DuplicateCrops")
        code, so, se = run([
            pdf, "--out", duplicate_out, "--stem", "Doe_Figs_2025",
            "--crop", "1:1.2:100,150,500,350",
            "--crop", "1:1-2:100,150,500,350",
        ])
        ok("two crop specs resolving to one target are refused",
           code != 0 and "same output label" in str(code))
        ok("...before an output directory is created",
           not os.path.lexists(duplicate_out))

        for option, value, phrase in (("--dpi", "0", "greater than zero"),
                                      ("--trim-pad", "-1", "zero or greater"),
                                      ("--trim-tolerance", "255", "between 0 and 254")):
            code, so, se = run(base + ["--crop", "1:8:100,150,500,350",
                                       option, value])
            check("invalid %s exits 2" % option, code, 2)
            ok("...and states its bound for %s" % option, phrase in se)

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

        # The whole crop list is preflighted before the output directory is
        # created. A bad later item cannot leave a good earlier item behind.
        preflight_out = os.path.join(tmp, "PreflightFailure")
        code, so, se = run([
            pdf, "--out", preflight_out, "--stem", "Doe_Figs_2025",
            "--crop", "1:1:100,150,500,350",
            "--crop", "9:2:100,150,500,350",
        ])
        ok("a bad later crop is refused before any output-side effect",
           code != 0 and not os.path.lexists(preflight_out))

        cap_out = os.path.join(tmp, "RenderCapFailure")
        code, so, se = run([
            pdf, "--out", cap_out, "--stem", "Doe_Figs_2025",
            "--crop", "1:1:100,150,500,350",
            "--crop", "1:2:100,150,500,350",
            "--dpi", "100000", "--no-trim",
        ])
        ok("oversized explicit crops are refused in whole-command preflight",
           code != 0 and "pre-render safety cap" in str(code))
        ok("the render cap is checked before creating the output directory",
           not os.path.lexists(cap_out))

        outside_out = os.path.join(tmp, "OutsidePageFailure")
        code, so, se = run([
            pdf, "--out", outside_out, "--stem", "Doe_Figs_2025",
            "--crop", "1:1:700,900,800,1000", "--dpi", "72",
        ])
        ok("a crop wholly outside its page is refused before rendering",
           code != 0 and "does not intersect" in str(code))
        ok("an off-page crop leaves no output directory",
           not os.path.lexists(outside_out))

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
        # The figure sidecars key each record by the stem. A stem they cannot
        # store ('#' reads as a comment, a leading space is invalid) is
        # refused before `--out` exists, even with the naming exception.
        for odd_stem in ("#1 Notes", " lead"):
            odd_pdf = os.path.join(tmp, "odd-stems", odd_stem + ".pdf")
            os.makedirs(os.path.dirname(odd_pdf), exist_ok=True)
            shutil.copyfile(pdf, odd_pdf)
            odd_out = os.path.join(tmp, "OddStemOut")
            code, so, se = run([odd_pdf, "--out", odd_out, "--allow-unorganized",
                                "--crop", "1:1:100,150,500,350", "--dpi", "72"])
            ok("a stem the sidecars cannot store is refused (%r)" % odd_stem,
               code != 0 and "could not be recorded" in str(code)
               and not os.path.lexists(odd_out))

        mismatch_out = os.path.join(tmp, "MismatchedStem")
        code, so, se = run([
            pdf, "--out", mismatch_out, "--stem", "Doe_Other_2025",
            "--crop", "1:1:100,150,500,350",
        ])
        ok("an explicit crop cannot publish under a stem other than its source",
           "exact on-disk stem" in str(code))
        ok("a mismatched stem leaves no output directory",
           not os.path.lexists(mismatch_out))

        # A direct repair into canonical Sources/Images shares the batch
        # extractor's vault-wide PDF basename gate.  Two case/NFC-equivalent
        # vault paths must be refused before a crop or sidecar is published.
        repair_vault = os.path.join(tmp, "RepairVault")
        repair_pdfs = os.path.join(repair_vault, "Sources", "PDFs")
        repair_images = os.path.join(repair_vault, "Sources", "Images")
        repair_archive = os.path.join(repair_vault, "Archive")
        os.makedirs(repair_pdfs)
        os.makedirs(repair_images)
        os.makedirs(repair_archive)
        repair_pdf = os.path.join(repair_pdfs, "Doe_Figs_2025.pdf")
        shutil.copyfile(pdf, repair_pdf)
        repair_collision = os.path.join(repair_archive, "Doe_Figs_2025.pdf")
        shutil.copyfile(pdf, repair_collision)
        code, so, se = run([
            repair_pdf, "--out", repair_images,
            "--stem", "Doe_Figs_2025",
            "--crop", "1:6:100,150,500,350", "--dpi", "72",
            "--no-trim",
        ])
        ok("manual canonical repair refuses a vault-wide PDF basename collision",
           code != 0 and "unique basename" in str(code))
        ok("...and leaves the duplicate to the user, not pdf-organize",
           "ask the user to remove the redundant copy" in str(code))
        ok("...naming the newcomer, not either copy, as the one to rename",
           "rename the newcomer" in str(code) and "move one" not in str(code))
        ok("...and noting that pdf-organize may rename an exempt newcomer",
           "refuses both" not in str(code)
           and "`check` accepts the newcomer" in str(code))
        check("collision refusal writes no figure or sidecar",
              os.listdir(repair_images), [])
        os.unlink(repair_collision)
        # A folder link shows the same PDF under a second path: the remedy
        # names the link, never the file, as a copy to remove.
        repair_shelf = os.path.join(repair_vault, "Shelf")
        os.symlink(repair_pdfs, repair_shelf, target_is_directory=True)
        code, so, se = run([
            repair_pdf, "--out", repair_images,
            "--crop", "1:6:100,150,500,350", "--dpi", "72", "--no-trim",
        ])
        ok("a basename reached through a folder link names that link",
           code != 0 and "symlink(s) %s show" % repair_shelf in str(code)
           and "redundant copy" not in str(code)
           and not os.listdir(repair_images))
        os.unlink(repair_shelf)

        ownerless_pdf = os.path.join(tmp, "ownerless", "Roe_Other_2024.pdf")
        os.makedirs(os.path.dirname(ownerless_pdf))
        shutil.copyfile(pdf, ownerless_pdf)
        code, so, se = run([
            ownerless_pdf, "--out", repair_images,
            "--stem", "Roe_Other_2024",
            "--crop", "1:6:100,150,500,350", "--dpi", "72", "--no-trim",
        ])
        ok("an external PDF with no vault owner is routed through Inbox/",
           code != 0 and "no vault PDF owns" in str(code)
           and "into Inbox/ for pdf-organize" in str(code))
        check("the ownerless refusal writes no figure or sidecar",
              os.listdir(repair_images), [])

        unorganized_pdf = os.path.join(repair_pdfs, "download (1).pdf")
        shutil.copyfile(pdf, unorganized_pdf)
        code, so, se = run([
            unorganized_pdf, "--out", repair_images,
            "--stem", "download (1)",
            "--crop", "1:1:100,150,500,350", "--dpi", "72", "--no-trim",
        ])
        ok("a vault crop refuses an unorganized source stem",
           code != 0 and "pdf-organize" in str(code)
           and "orphan" not in str(code))
        check("the unorganized vault crop publishes nothing",
              os.listdir(repair_images), [])

        # A feed attachment keeps its collector name, so its refusal names
        # only the --allow-unorganized exception, never pdf-organize.
        feed_pdf = os.path.join(repair_pdfs, "rss-" + "ab" * 16 + ".pdf")
        shutil.copyfile(pdf, feed_pdf)
        code, so, se = run([
            feed_pdf, "--out", repair_images,
            "--crop", "1:1:100,150,500,350", "--dpi", "72", "--no-trim",
        ])
        check("a vault crop of a named feed attachment names the exception",
              (code != 0, "--allow-unorganized" in str(code),
               "Organize it first" in str(code), os.listdir(repair_images)),
              (True, True, False, []))
        os.unlink(feed_pdf)

        # A split book's figures are its chapters', as in the batch: an
        # explicit crop of the book is refused for its chapter PDF.
        book_pdf = os.path.join(repair_pdfs, "Doe_Book_2019.pdf")
        shutil.copyfile(pdf, book_pdf)
        chapter_dir = os.path.join(repair_pdfs, "Doe_Book_2019")
        os.makedirs(chapter_dir)
        chapter_pdf = os.path.join(chapter_dir, "Doe_Book_2019_01_Intro.pdf")
        shutil.copyfile(pdf, chapter_pdf)
        book_crop = ["--out", repair_images, "--crop", "1:1:100,150,500,350",
                     "--dpi", "72", "--no-trim"]
        code, so, se = run([book_pdf] + book_crop)
        check("an explicit crop of a split book is refused for its chapters",
              (code != 0, "is a split book" in str(code),
               os.path.join("PDFs", "Doe_Book_2019'") in str(code),
               "--include-split-books" in str(code),
               os.listdir(repair_images)),
              (True, True, True, False, []))
        code, so, se = run([chapter_pdf] + book_crop)
        check("...the chapter PDF's crop is written under the chapter stem",
              (code, sorted(os.listdir(repair_images))),
              (0, sorted([MANIFEST_FILE, "Doe_Book_2019_01_Intro_fig_1.png"])))
        code, so, se = run([book_pdf, "--include-split-books"] + book_crop)
        check("...and --include-split-books crops the book's own pages",
              (code, "Doe_Book_2019_fig_1.png" in os.listdir(repair_images)),
              (0, True))
        for name in os.listdir(repair_images):
            os.unlink(os.path.join(repair_images, name))
        shutil.rmtree(chapter_dir)
        os.unlink(book_pdf)

        # A readable external scratch representation is allowed when one vault
        # source uniquely owns its basename (the encrypted-PDF recovery route).
        scratch_pdf = os.path.join(tmp, "scratch", "Doe_Figs_2025.pdf")
        os.makedirs(os.path.dirname(scratch_pdf))
        shutil.copyfile(pdf, scratch_pdf)
        code, so, se = run([
            scratch_pdf, "--out", repair_images,
            "--stem", "Doe_Figs_2025",
            "--crop", "1:6:100,150,500,350", "--dpi", "72", "--no-trim",
        ])
        check("external readable copy passes one-owner vault namespace check",
              code, 0)
        ok("external readable copy publishes under the vault owner's stem",
           os.path.isfile(os.path.join(repair_images,
                                       "Doe_Figs_2025_fig_6.png")))
        variant_scratch = os.path.join(tmp, "scratch-variant",
                                       "doe_figs_2025.pdf")
        os.makedirs(os.path.dirname(variant_scratch))
        shutil.copyfile(pdf, variant_scratch)
        code, so, se = run([
            variant_scratch, "--out", repair_images,
            "--crop", "1:5:100,150,500,350", "--dpi", "72", "--no-trim",
        ])
        ok("a readable copy named in another case is refused",
           code != 0 and "exact basename 'Doe_Figs_2025.pdf'" in str(code)
           and not any(name.endswith("_fig_5.png")
                       for name in os.listdir(repair_images)))

        # A typed case variant of the vault PDF opens the same file on an
        # insensitive filesystem; the crop keeps the stored spelling.
        typed_variant = os.path.join(repair_pdfs, "doe_figs_2025.pdf")
        if os.path.lexists(typed_variant):
            code, so, se = run([
                typed_variant, "--out", repair_images,
                "--crop", "1:6:100,150,500,350", "--dpi", "72", "--no-trim",
                "--overwrite",
            ])
            check("a typed case variant repairs the crop under the stored name",
                  (code, "Doe_Figs_2025_fig_6.png" in os.listdir(repair_images),
                   "doe_figs_2025_fig_6.png" in os.listdir(repair_images),
                   sorted(read_manifest(os.path.join(
                       repair_images, MANIFEST_FILE)))),
                  (0, True, False, ["Doe_Figs_2025_fig_6.png"]))
            code, so, se = run([
                typed_variant, "--out", repair_images,
                "--stem", "doe_figs_2025",
                "--crop", "1:6:100,150,500,350", "--dpi", "72",
            ])
            ok("a --stem in the typed case is refused, naming the stored stem",
               code != 0 and "on-disk stem 'Doe_Figs_2025'" in str(code)
               and "omit --stem" in str(code))
        else:
            ok("case-variant explicit-crop regressions skipped on this filesystem",
               True)
            ok("case-variant --stem regression skipped on this filesystem", True)

        # The same holds for a Unicode normalization variant.
        nfd_dir = os.path.join(tmp, "NfdSource")
        os.makedirs(nfd_dir)
        nfd_stem = "Mu\u0308ller_Figs_2025"
        shutil.copyfile(pdf, os.path.join(nfd_dir, nfd_stem + ".pdf"))
        nfc_typed = os.path.join(nfd_dir, "Müller_Figs_2025.pdf")
        nfd_out = os.path.join(tmp, "NfdOut")
        if os.path.lexists(nfc_typed):
            code, so, se = run([
                nfc_typed, "--out", nfd_out,
                "--crop", "1:1:100,150,500,350", "--dpi", "72", "--no-trim",
            ])
            check("an NFC-typed path writes the stored NFD stem",
                  (code, sorted(os.listdir(nfd_out))),
                  (0, sorted([MANIFEST_FILE, nfd_stem + "_fig_1.png"])))
        else:
            ok("normalization-variant regression skipped on this filesystem",
               True)

        # The missing-argument path: named, not an argparse usage dump, and
        # exit 2 the way `paper_scan.py` reports the same thing.
        code, so, se = run([pdf, "--out", outdir])
        check("missing --crop exits 2", code, 2)
        ok("...naming it, and not the optional --stem",
           "--crop" in se and "--stem" not in se)
        nostem_out = os.path.join(tmp, "NoStem")
        code, so, se = run([pdf, "--out", nostem_out, "--crop",
                            "1:7:100,150,500,350", "--dpi", "72", "--no-trim"])
        check("an explicit crop without --stem succeeds", code, 0)
        ok("...naming the output after the PDF's own stem",
           os.path.isfile(os.path.join(nostem_out, "Doe_Figs_2025_fig_7.png")))

        # An HTML error page saved as `.pdf` opens fine in PyMuPDF and reads as
        # a document. Without the is_pdf guard the crop is written from it.
        html = os.path.join(tmp, "Doe_NotAPdf_2025.pdf")
        with open(html, "w", encoding="utf-8") as fh:
            fh.write("<html><body><h1>404</h1><p>Not found.</p></body></html>")
        html_out = os.path.join(tmp, "HtmlFailure")
        code, so, se = run([html, "--out", html_out, "--stem", "Doe_NotAPdf_2025",
                            "--crop", "1:1:10,10,100,100"])
        ok("an HTML page named .pdf is refused",
           "not a PDF" in str(code) or "could not open as a PDF" in str(code))
        ok("...before creating an output directory",
           not os.path.lexists(html_out))

        # PyMuPDF opens a protected PDF object, but rendering it without a
        # password fails later with a backend exception. Refuse it before the
        # output folder exists and give the same scratch-copy recovery used by
        # the batch and paper-reading workflows.
        encrypted_plain = _st_pdf(os.path.join(tmp, "encrypted-plain.pdf"))
        encrypted = os.path.join(tmp, "Doe_Encrypted_2025.pdf")
        encrypted_doc = fitz.open(encrypted_plain)
        encrypted_doc.save(
            encrypted, encryption=fitz.PDF_ENCRYPT_AES_256,
            owner_pw="owner-secret", user_pw="reader-secret")
        encrypted_doc.close()
        encrypted_out = os.path.join(tmp, "EncryptedFailure")
        code, so, se = run([
            encrypted, "--out", encrypted_out, "--stem", "Doe_Encrypted_2025",
            "--crop", "1:1:100,150,500,350",
        ])
        ok("an encrypted PDF gets an actionable refusal",
           "encrypted/password-protected" in str(code) and "scratch" in str(code))
        ok("an encrypted PDF leaves no output directory",
           not os.path.lexists(encrypted_out))

        # Follow the documented recovery path: batch -> manual crop -> batch.
        # The second batch must keep the repair rather than declaring its
        # changed digest foreign and recommending automatic re-extraction.
        from pathlib import Path
        from batch_extract import process_pdf, save_manifest, load_manifest
        owned = os.path.join(tmp, "Owned")
        os.makedirs(owned)
        tracked = {}
        process_pdf(Path(pdf), owned, dpi=72, manifest=tracked)
        tracked["DOE_FIGS_2025_FIG_1.PNG"] = tracked.pop("Doe_Figs_2025_fig_1.png")
        tracked["Unrelated_fig_8.png"] = "a" * 64
        tracked_path = os.path.join(owned, MANIFEST_FILE)
        save_manifest(tracked_path, tracked,
                      expected=load_manifest(tracked_path)[1])
        owned_png = os.path.join(owned, "Doe_Figs_2025_fig_1.png")
        before = open(owned_png, "rb").read()
        code, so, se = run([pdf, "--out", owned, "--stem", "Doe_Figs_2025",
                           "--crop", "1:1:120,170,400,300", "--dpi", "72", "--overwrite"])
        check("manual repair of tracked output succeeds", code, 0)
        repaired = open(owned_png, "rb").read()
        ok("manual repair changes the actual crop bytes", repaired != before)
        recorded = load_manifest(tracked_path)[0]
        check("manual repair preserves unrelated ownership",
              recorded["Unrelated_fig_8.png"], "a" * 64)
        check("manual repair preserves an equivalent record's original casing",
              sorted(recorded), ["DOE_FIGS_2025_FIG_1.PNG", "Unrelated_fig_8.png"])
        rerun = process_pdf(Path(pdf), owned, dpi=72, manifest=recorded)
        check("the next batch accepts and preserves the manual repair",
              (rerun["skipped"], rerun["occupied"], open(owned_png, "rb").read()),
              (1, [], repaired))
        with open(tracked_path, "w", encoding="utf-8") as fh:
            fh.write("malformed ownership\n")
        code, so, se = run([pdf, "--out", owned, "--stem", "Doe_Figs_2025",
                           "--crop", "1:1:100,150,500,350", "--overwrite"])
        ok("corrupt ownership is refused before altering a manual crop", code != 0)
        check("a refused crop leaves image bytes intact", open(owned_png, "rb").read(), repaired)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("%d/%d self-test cases pass"
          % (state["n"] - state["bad"], state["n"]))
    return 1 if state["bad"] else 0


def _configure_stdio():
    """Keep source paths and publication diagnostics writable through pipes."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="backslashreplace")
            except (AttributeError, OSError, ValueError):
                pass


def main(argv=None):
    _configure_stdio()
    p = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=__doc__,
    )
    p.add_argument("pdf", nargs="?")
    p.add_argument("--out", help="Output directory (e.g. Sources/Images/)")
    p.add_argument(
        "--stem",
        help=("Optional; must equal the source PDF's exact on-disk stem "
              "(default: derived from the PDF path)."),
    )
    p.add_argument(
        "--crop",
        action="append",
        help='Figure spec: "PAGE:FIG_NUM:x0,y0,x1,y1"',
    )
    p.add_argument(
        "--dpi", type=positive_int, default=250,
        help=("Render resolution (default: 250); each crop is limited to "
              f"{MAX_RENDER_PIXELS:,} pixels."),
    )
    p.add_argument(
        "--overwrite",
        action="store_true",
        help=(
            "Replace existing PNGs only when their recorded ownership and "
            "current bytes match. Default: skip verified output. Unknown or "
            "changed files are refused with or without this flag."
        ),
    )
    p.add_argument(
        "--allow-unorganized", action="store_true",
        help=("Accept a deliberate source-naming exception when repairing a "
              "vault crop, matching batch_extract.py. The exact stem, "
              "whole-vault uniqueness and output ownership checks remain active."),
    )
    p.add_argument(
        "--include-split-books", action="store_true",
        help=("Crop a split book's own pages into the vault, matching "
              "batch_extract.py: only to repair a crop of a deliberate "
              "--include-split-books run. A split book's figures are its "
              "chapters'."),
    )
    p.add_argument(
        "--no-caption-check",
        dest="caption_check",
        action="store_false",
        help=(
            "Skip the warning when a crop rect overlaps a detected caption. "
            "The check is on by default: a crop that overlaps a caption puts "
            "caption text in the PNG."
        ),
    )
    p.add_argument(
        "--blank-captions", action="store_true",
        help=("White out the words of every detected caption inside the "
              "crop, for a caption that occupies a corner of the figure's "
              "bounding box; view the PNG afterwards."),
    )
    p.add_argument(
        "--no-trim",
        dest="trim",
        action="store_false",
        help="Skip the post-crop white-margin trim (default: trim).",
    )
    p.add_argument(
        "--trim-pad",
        type=nonnegative_int,
        default=4,
        help="Pixels of whitespace to keep around the trimmed content (default: 4).",
    )
    p.add_argument(
        "--trim-tolerance",
        type=pixel_tolerance,
        default=10,
        help="Per-channel distance from pure white that still counts as white "
        "(default: 10, handles antialiasing).",
    )
    p.add_argument("--test", action="store_true", help="run the self-test")
    args = p.parse_args(argv)

    if args.test:
        _require_pymupdf()
        return run_self_test()
    # Reported by name rather than left to argparse's `required=True`, because
    # `--test` takes no PDF and no crops: with the flags marked required,
    # argparse rejects the self-test invocation before `main()` can see it.
    # Same shape and same exit code as `paper_scan.py`'s missing-argument path.
    missing = [f for f in ("pdf", "out", "crop")
               if not getattr(args, f)]
    if missing:
        print("missing required argument(s): %s"
              % ", ".join("pdf" if m == "pdf" else "--" + m for m in missing),
              file=sys.stderr)
        return 2
    _require_pymupdf()

    out_dir = os.path.expanduser(args.out)
    pdf_path = os.path.expanduser(args.pdf)
    # A case or Unicode variant of the name opens the same file on an
    # insensitive filesystem (the macOS default), but the crops take the
    # stored spelling. A typed variant would rename an existing crop on
    # --overwrite and name new ones after a stem the PDF does not have.
    # A folder that cannot be listed keeps the typed name; canonical vault
    # output still needs the vault owner's exact basename below.
    if os.path.lexists(pdf_path):
        try:
            stored = os.path.basename(on_disk_spelling(pdf_path))
        except UnlistedFolderError as exc:
            print(f"Note: {exc}; using the typed name.")
            stored = os.path.basename(pdf_path)
        except ValueError as exc:
            sys.exit(f"{pdf_path}: {exc}")
        if stored != os.path.basename(pdf_path):
            print(f"Using the PDF's stored filename {stored!r} "
                  f"(typed as {os.path.basename(pdf_path)!r}).")
            pdf_path = os.path.join(os.path.dirname(pdf_path), stored)
    pdf_stem = os.path.splitext(os.path.basename(pdf_path))[0]
    # The stem defaults to, and must equal, the PDF's on-disk stem. It goes
    # straight into `os.path.join(out_dir, f"{stem}_fig_{n}.png")`, so the
    # filename-fragment checks below stay as defense in depth: a separator or
    # a parent-directory hop would write outside `--out`, the same way
    # clipping-clean's `fetch_images.py` refuses such a `--slug`.
    if args.stem is None:
        args.stem = pdf_stem
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
    if args.stem != pdf_stem:
        sys.exit(f"--stem {args.stem!r} does not equal the source PDF's exact "
                 f"on-disk stem {pdf_stem!r}. Figure identity follows that "
                 "filename; omit --stem to use that stem, or organize the "
                 "PDF first")
    # The crop is published before its ownership record. A stem the figure
    # sidecars cannot store would leave a crop no later run can own.
    problem = sidecar_stem_problem(args.stem)
    if problem:
        sys.exit(f"--stem {args.stem!r} {problem}, so its crops could not be "
                 "recorded. No sidecar or figure was written. Give the PDF a "
                 "canonical name with pdf-organize (run without --vault "
                 "outside the vault), or crop a renamed copy into an "
                 "external --out")

    # Parse every request before opening the source or creating `--out`. A
    # malformed later crop must not leave earlier files behind from what the
    # caller reasonably treats as one atomic preflighted command.
    parsed_crops = [(spec,) + parse_crop(spec) for spec in args.crop]
    targets = {}
    for spec, _page_idx, suffix, _rect in parsed_crops:
        key = figure_identity(suffix)
        if key in targets:
            sys.exit(f"--crop {spec!r} resolves to the same output label as "
                     f"{targets[key]!r}; each target may appear only once")
        targets[key] = spec

    # Manual repair writes into the same flat vault namespace as the batch
    # extractor.  It therefore needs the same whole-vault portable-basename
    # proof before reading a sidecar or publishing any crop.  An arbitrary
    # external output remains an explicit one-off target.
    vault_root = output_vault_root(out_dir)
    if vault_root is not None:
        if (is_feed_attachment(pdf_stem, is_stem=True)
                and not args.allow_unorganized):
            sys.exit(
                "Refusing explicit crops into the vault's canonical "
                "Sources/Images folder: %r is a collector-owned feed "
                "attachment whose name never changes. Repeat the "
                "--allow-unorganized exception to crop it under that name, "
                "and never route it to pdf-organize." % pdf_stem)
        if not looks_canonical(pdf_stem, is_stem=True) and not args.allow_unorganized:
            sys.exit(
                "Refusing explicit crops into the vault's canonical "
                "Sources/Images folder: the selected PDF stem %r has not "
                "been produced by pdf-organize. Organize it first so the "
                "crop is keyed to a durable name (a later rename must go "
                "through pdf-organize, which carries recorded crops), or "
                "repeat the batch's deliberate --allow-unorganized "
                "exception." % pdf_stem)
        decision = verify_selected_pdf(vault_root, pdf_path)
        if not decision.unique:
            detail = decision.reason
            if decision.matches:
                detail += ": " + ", ".join(decision.matches)
            errors = [item for item in decision.inventory.findings
                      if item.severity == "error"]
            if errors:
                detail += "; " + "; ".join(
                    "%s: %s" % (item.path, item.message)
                    for item in errors[:3])
            _category, remedy = vault_refusal(decision)
            sys.exit(
                "Refusing explicit crops into the vault's canonical "
                "Sources/Images folder: the source needs a unique basename "
                "with one vault PDF owner, but %s. %s%s. No sidecar or "
                "figure was written." % (detail, remedy[0].upper(), remedy[1:]))
        # A readable copy outside the vault names the crops, so a case or
        # Unicode variant of the owner's name would write variant names.
        owner_name = os.path.basename(decision.matches[0])
        if owner_name != os.path.basename(pdf_path):
            sys.exit(
                "Refusing explicit crops into the vault's canonical "
                "Sources/Images folder: the readable copy must keep the vault "
                "PDF's exact basename %r, not %r. No sidecar or figure was "
                "written." % (owner_name, os.path.basename(pdf_path)))
        # A split book's figures are its chapters' (CONVENTIONS.md 1a), as
        # in the batch: a whole-book crop would duplicate a chapter crop
        # under the book's stem. Like the batch, the refusal never offers
        # --include-split-books.
        chapters = [] if args.include_split_books else split_book_chapters(
            [Path(pdf_path)], decision.inventory).get(Path(pdf_path), [])
        if chapters:
            folders = sorted({str(chapter.parent) for chapter in chapters})
            sys.exit(
                "Refusing explicit crops into the vault's canonical "
                "Sources/Images folder: %s is a split book; its figures are "
                "those of its %d chapter PDF(s). Crop the figure from the "
                "chapter PDF in %s that holds it, with that chapter's own "
                "page numbers; never re-extract the whole book. No sidecar "
                "or figure was written." % (
                    os.path.basename(pdf_path), len(chapters),
                    " or ".join(repr(f) for f in folders)))

    if args.allow_unorganized and not looks_canonical(pdf_stem, is_stem=True):
        print("Source naming exception (--allow-unorganized): crops remain "
              "keyed to the exact source stem %r." % pdf_stem)

    # A one-line message beats a traceback for the two things that land in
    # a Sources/PDFs folder and are not readable PDFs: a truncated or non-PDF
    # download, and a PDF with zero pages.
    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        sys.exit(f"{pdf_path}: could not open as a PDF ({e})")

    def die(message):
        """Close the source before an actionable CLI refusal."""
        doc.close()
        raise SystemExit(message)

    # PyMuPDF opens HTML, XPS and EPUB natively, so an error page or a
    # truncated download named `.pdf` opens without raising, renders, and
    # writes a PNG of somebody's 404 page into Sources/Images/ under a real
    # figure name. `batch_extract.py` has always had this guard; this script
    # writes into the same folder and needs the same one.
    if not doc.is_pdf:
        fmt = (doc.metadata or {}).get("format") or "an unknown format"
        die(f"{pdf_path}: not a PDF — opened as {fmt} (an HTML error page "
            f"or a truncated download saved with a .pdf extension)")
    if getattr(doc, "needs_pass", False) or getattr(doc, "is_encrypted", False):
        die(f"{pdf_path}: encrypted/password-protected PDF. Decrypt into a "
            "unique scratch directory outside the vault, keep this exact "
            "basename for the readable copy, preserve the organized source "
            "unchanged, then run the explicit crop against that copy")
    if len(doc) == 0:
        die(f"{pdf_path}: PDF has zero pages — nothing to extract")

    # Page and geometry checks depend on the opened document, but still happen
    # before `--out` is created or any existing output is inspected or changed.
    for spec, page_idx, _fig_suffix, (x0, y0, x1, y1) in parsed_crops:
        if page_idx < 0 or page_idx >= len(doc):
            die(f"--crop {spec!r}: page {page_idx + 1} out of range "
                f"(PDF has {len(doc)} pages)")
        if x0 >= x1 or y0 >= y1:
            die(f"--crop {spec!r}: degenerate rect — need x0 < x1 and "
                f"y0 < y1, got x={x0},{x1} y={y0},{y1}")
        try:
            _checked_visible_crop(
                doc[page_idx], fitz.Rect(x0, y0, x1, y1), args.dpi,
                f"crop on page {page_idx + 1}",
            )
        except ValueError as exc:
            die(f"--crop {spec!r}: {exc}")

    # An explicit repair is this extractor's own output too. Without updating
    # its digest, the next batch called a repaired crop another skill's file
    # and recommended overwriting it with the original, wrong automatic crop.
    # A newly created explicit crop is extractor output and therefore receives
    # an ownership record even when this is the folder's first manifest. An
    # occupied legacy slot remains unowned and still requires the batch
    # extractor's exact --adopt-legacy STEM:FIG selection.
    manifest_path = os.path.join(out_dir, MANIFEST_FILE)
    try:
        manifest, manifest_snapshot = read_manifest_snapshot(manifest_path)
        check_manifest_writable(manifest_path)
    except (OSError, UnicodeError, ValueError) as exc:
        die(f"Refusing explicit crops: cannot safely read {manifest_path}: {exc}")
    # Preflight every target even in a legacy folder. An absent manifest is
    # not proof that an occupied slot belongs to this PDF: clippings share
    # these filenames. An explicit crop must not bypass the batch ownership guard.
    preflight_digests = {}
    for _spec, _page_idx, suffix, _rect in parsed_crops:
        target = os.path.join(out_dir, f"{args.stem}_fig_{suffix}.png")
        conflict = _figure_slot_conflict(out_dir, args.stem, suffix, target)
        if conflict is not None:
            occupied, why = conflict
            die(f"Refusing explicit crop of {target}: {why} ({occupied})")
        if not os.path.lexists(target):
            preflight_digests[target] = None
            continue
        if os.path.islink(target):
            die(f"Refusing explicit crop of {target}: it is a symlink, not a recorded output file")
        try:
            digest = file_digest(target)
        except OSError as exc:
            die(f"Refusing explicit crop of {target}: {exc}")
        key = manifest_key(manifest, os.path.basename(target))
        if manifest.get(key) != digest:
            die(f"Refusing explicit crop of {target}: ownership is unknown or its bytes changed. "
                "Inspect the occupant: adopt a confirmed legacy crop with the batch's "
                "--adopt-legacy, and repair a changed recorded crop only with the "
                "user's authorization (the skill's review reference, ownership "
                "section); --overwrite does not claim another file.")
        preflight_digests[target] = digest

    os.makedirs(out_dir, exist_ok=True)

    # Captions, for the label check and the "is the caption inside this
    # crop?" warning. Imported lazily and defensively: the checks are a
    # convenience, and a sibling-module import problem must not stop an
    # explicit crop from being written — that crop is usually the fallback
    # for something else that already went wrong.
    find_caption_blocks = None
    to_page_space = None
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from auto_fig_bbox import find_caption_blocks, to_page_space
    except (Exception, SystemExit) as e:
        # SystemExit too: auto_fig_bbox exits with a message rather than
        # a traceback when PyMuPDF is missing, and that must not take
        # this script's own crop down with it.
        print(f"note: caption checks unavailable ({e})", file=sys.stderr)

    blank_crops = 0
    for spec, page_idx, fig_suffix, (x0, y0, x1, y1) in parsed_crops:
        out_path = os.path.join(out_dir, f"{args.stem}_fig_{fig_suffix}.png")
        captions = []
        if find_caption_blocks is not None:
            try:
                captions = find_caption_blocks(doc[page_idx])
            except Exception as e:
                print(f"note: caption checks skipped on page {page_idx + 1} "
                      f"({e})", file=sys.stderr)
        # A printed number is not always the output label: `Supplementary
        # Figure 1` is `S1`. Passing `1` would write, and with --overwrite
        # replace, the main Figure 1 crop.
        mismatch = _series_mismatch(fig_suffix, captions)
        if mismatch is not None:
            cap_raw, cap_label = mismatch
            # This check runs under the default prefix; a PDF the batch
            # extracted with --ed-prefix ED names its Extended Data crops ED<N>.
            ed_label = _extended_data_label(cap_raw, cap_label)
            ed_form = (f" ({ed_label!r} if this PDF uses --ed-prefix ED)"
                       if ed_label else "")
            replaces = (", and --overwrite replaces the crop already there"
                        if args.overwrite and os.path.lexists(out_path) else "")
            print(
                f"WARNING: --crop {spec!r} is labelled {fig_suffix!r}, but no "
                f"caption on page {page_idx + 1} is; its caption {cap_raw!r} "
                f"has output label {cap_label!r}{ed_form}. This crop goes to "
                f"{out_path}{replaces}. Pass the Fig label auto_fig_bbox.py "
                f"reports, not the printed number.",
                file=sys.stderr,
            )
        # The crop must stay clear of every caption, whichever side it sits
        # on. This is the constraint every hand-set crop gets wrong first, and
        # nothing about the result says so: the PNG is written, looks fine at
        # a glance, and carries the caption text the skill exists to leave out.
        # A caption in a corner of the figure's bounding box cannot be cropped
        # out; --blank-captions whites out its words instead.
        blank_rects = []
        if args.caption_check or args.blank_captions:
            page = doc[page_idx]
            for cap_num, cap_raw, content_cap in captions:
                # `--crop` coordinates are the ones `get_pixmap(clip=...)`
                # takes — the page's displayed space — while caption rects
                # come back in unrotated content space. On a `/Rotate`d page
                # the two are different, and comparing them compared nothing.
                cap = to_page_space(page, content_cap)
                if not (y1 > cap.y0 and x1 > cap.x0 and x0 < cap.x1
                        and y0 < cap.y1):
                    continue
                if args.blank_captions:
                    # Word boxes, not the caption rect, so figure content
                    # beside a short caption line is kept.
                    blank_rects += [
                        to_page_space(page, fitz.Rect(w[:4])
                                      + (-0.5, -0.5, 0.5, 0.5))
                        for w in page.get_text("words", clip=content_cap)]
                    print(f"--crop {spec!r}: blanked caption {cap_raw!r} "
                          f"inside the crop")
                else:
                    print(
                        f"WARNING: --crop {spec!r} overlaps the caption for "
                        f"{cap_raw!r} (x={cap.x0:.1f}-{cap.x1:.1f}, "
                        f"y={cap.y0:.1f}-{cap.y1:.1f}) — the caption will be "
                        f"in the PNG. Move the crop edge facing the caption "
                        f"(for a caption below, y1 <= {cap.y0 - 0.5:.1f}).",
                        file=sys.stderr,
                    )
        if args.blank_captions and not blank_rects:
            print(f"WARNING: --blank-captions found no detected caption "
                  f"inside --crop {spec!r}; nothing was blanked.",
                  file=sys.stderr)

        def publication_guard():
            conflict = _figure_slot_conflict(
                out_dir, args.stem, fig_suffix, out_path)
            if conflict is None:
                return
            occupied, why = conflict
            raise FileExistsError(errno.EEXIST, why, occupied)
        # Skip-existing is batch_extract.py's documented default and this is
        # the same output folder, so it is the default here too. Without it,
        # an explicit crop and a batch run silently overwrite each other's work
        # depending only on which ran last.
        expected_digest = preflight_digests[out_path]
        if expected_digest is not None and not args.overwrite:
            try:
                current_digest = _stable_output_digest(out_path)
            except OSError as exc:
                die(f"Refusing to skip {out_path}: {exc}")
            if current_digest != expected_digest:
                die(f"Refusing to skip {out_path}: its verified bytes changed "
                    "after preflight. Inspect the current occupant and retry.")
            print(f"Exists, skipped: {out_path} (pass --overwrite to replace)")
            continue
        try:
            (rw, rh), (fw, fh), blank, publication = extract_one_figure(
                doc, page_idx, (x0, y0, x1, y1), out_path,
                dpi=args.dpi, trim=args.trim,
                trim_pad=args.trim_pad, trim_tolerance=args.trim_tolerance,
                replace_digest=(expected_digest if args.overwrite else None),
                publication_guard=publication_guard,
                return_publication=True, blank_rects=blank_rects,
            )
        except (OSError, RuntimeError, ValueError) as exc:
            staged = getattr(exc, "staging_path", None)
            recovery = getattr(exc, "recovery_path", None)
            locations = []
            if staged:
                locations.append(f"staged crop preserved at {staged}")
            if recovery and recovery != staged:
                locations.append(f"additional recovery state at {recovery}")
            suffix = ("; " + "; ".join(locations)) if locations else ""
            die(f"Refusing explicit crop of {out_path}: {exc}{suffix}")
        if blank:
            blank_crops += 1
            print(
                f"BLANK: --crop {spec!r} rendered {rw}x{rh} pixels of nothing "
                f"but white — nothing was written to {out_path}. The rect is "
                f"over empty page: the usual cause is a caption whose figure "
                f"is on another page. Render the page "
                f"(scripts/render_page.py) and re-read the coordinates.",
                file=sys.stderr,
            )
            continue
        try:
            name = os.path.basename(out_path)
            # `publication` describes the inode and bytes this run actually
            # installed. Re-reading `out_path` here could claim a foreign file
            # that replaced it between the guarded publication and sidecar CAS.
            manifest[manifest_key(manifest, name) or name] = publication[1]
            manifest_snapshot = write_manifest(
                manifest_path, manifest, expected=manifest_snapshot)
        except (OSError, UnicodeError, ValueError) as exc:
            die(f"Crop written to {out_path}, but its ownership record could not be updated: {exc}. "
                "Do not run automatic overwrite; preserve this explicit crop while repairing the sidecar.")
        msg = f"Wrote {out_path}: {rw}x{rh}"
        if args.trim:
            if (fw, fh) != (rw, rh):
                msg += f" → trimmed to {fw}x{fh}"
            else:
                msg += " (trim unchanged; no safe removable margin detected)"
        print(msg)
    doc.close()
    return 1 if blank_crops else 0


if __name__ == "__main__":
    # `sys.exit(main())`: `--test` and the missing-argument path both report
    # through the exit code, and a bare call throws it away.
    sys.exit(main())
