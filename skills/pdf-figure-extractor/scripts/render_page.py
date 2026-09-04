"""Render PDF pages to PNG for quick visual inspection.

When `auto_fig_bbox.py` produces a suspicious bbox (or flat-out fails on an
unusual layout — side-caption corners, raster-only figures with no detectable
image rect, etc.), the fastest fallback is to look at the page and set the
crop by eye. This script gets you that image in one call.

Output goes to a unique OS temporary directory by default (it's a throwaway
preview — no point cluttering the vault), and the written path is printed.
Default DPI is 100, which is sharp enough to read panel letters
and axis labels at typical screen scale, while being small enough to load
quickly.

**The image is in pixels; --crop wants points.** Multiply any coordinate you
read off the preview by 72/DPI — 0.72 at the default 100 DPI — before putting
it in an `extract_figures.py --crop` spec. Each line printed below states the
factor for the DPI actually used, so there is nothing to derive. A US Letter
page is 612x792 pt and 850x1100 px at 100 DPI; skip the conversion and the
crop lands about 39% too far right and too far down, which is a wrong crop,
not an error. `--dpi 72` makes pixels and points the same number.

Usage:
    python3 render_page.py input.pdf 16
    python3 render_page.py input.pdf 16,17,18
    python3 render_page.py input.pdf 16 --out '<scratch>' --dpi 150
    python3 render_page.py input.pdf 16 --dpi 72     # 1 px == 1 pt

    # The adversarial fixtures this module is held to.
    python3 render_page.py --test

An occupied preview name is refused before any requested page is rendered.
Use a fresh scratch directory for a re-render; symlinks, regular files and
other occupants are all preserved.
"""
import argparse
import math
import os
import shutil
import sys
import tempfile


_OBSIDIAN_SHARED_MODULES = ('atomic_move',)

# --- obsidian shared-layer bootstrap (canonical; see shared/CONVENTIONS.md) ---
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

import atomic_move


def _configure_stdio():
    """Make paths and Unicode diagnostics printable on narrow host consoles."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="backslashreplace")
            except (OSError, ValueError):
                pass


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
        fitz = None


_PYMUPDF_ERROR = (
    "PyMuPDF required. Use a Python environment with the plugin\n"
    "dependencies installed; see shared/RUNTIME.md. Install into a\n"
    "virtual environment, then run this command with that environment's "
    "Python."
)

# PyMuPDF allocates the raster before Pillow ever inspects the PNG. Keep the
# bound below Pillow's default decompression-bomb warning threshold and still
# allow a full Letter/A4 page at 600 DPI (about 34 million pixels). The figure
# cropper imports this helper so previews and final crops enforce one limit.
MAX_RENDER_PIXELS = 50_000_000


def _require_pymupdf():
    """Fail after argument parsing so --help remains available during setup."""
    if fitz is None:
        raise SystemExit(_PYMUPDF_ERROR)


def checked_render_dimensions(rect, dpi, label="render"):
    """Return a conservative pixel-size bound, refusing oversized renders.

    A transformed PyMuPDF rectangle can gain one boundary pixel on each axis,
    depending on its fractional origin. Account for that before multiplying so
    the check happens before ``Page.get_pixmap()`` allocates native memory.
    """
    try:
        dpi_value = float(dpi)
        width_points = float(rect.width)
        height_points = float(rect.height)
    except (AttributeError, OverflowError, TypeError, ValueError) as exc:
        raise ValueError(f"{label} has invalid geometry or DPI") from exc
    if (not math.isfinite(dpi_value) or dpi_value <= 0
            or not math.isfinite(width_points)
            or not math.isfinite(height_points)
            or width_points <= 0 or height_points <= 0):
        raise ValueError(f"{label} has invalid geometry or DPI")

    scaled_width = width_points * dpi_value / 72.0
    scaled_height = height_points * dpi_value / 72.0
    if not math.isfinite(scaled_width) or not math.isfinite(scaled_height):
        raise ValueError(
            f"{label} exceeds the {MAX_RENDER_PIXELS:,}-pixel pre-render "
            "safety cap; lower --dpi or render a smaller crop"
        )
    pixel_width = max(1, math.ceil(scaled_width) + 1)
    pixel_height = max(1, math.ceil(scaled_height) + 1)
    pixels = pixel_width * pixel_height
    if pixels > MAX_RENDER_PIXELS:
        raise ValueError(
            f"{label} is approximately {pixel_width:,}x{pixel_height:,} "
            f"({pixels:,} pixels), over the {MAX_RENDER_PIXELS:,}-pixel "
            "pre-render safety cap; lower --dpi or render a smaller crop"
        )
    return pixel_width, pixel_height


def parse_pages(spec, n_pages):
    """"16,17,18" → [15, 16, 17]; exit cleanly on anything else.

    Empty tokens are skipped so a trailing comma is not an error, and every
    page is range-checked BEFORE any of them is rendered — a run that writes
    two previews and then dies on the third has already put the user in the
    position of not knowing which files are current.
    """
    idxs = []
    for s in spec.split(","):
        s = s.strip()
        if not s:
            continue
        try:
            idx = int(s) - 1
        except ValueError:
            sys.exit(f"--pages: {s!r} is not an integer page number")
        if idx < 0 or idx >= n_pages:
            sys.exit(f"--pages: page {s} out of range (PDF has {n_pages} pages)")
        idxs.append(idx)
    if not idxs:
        sys.exit(f"--pages: {spec!r} names no page")
    return idxs


def preview_path(out_dir, pdf_path, idx):
    """Where the preview for 0-indexed page `idx` of `pdf_path` is written.

    The filename mirrors the PDF's own stem exactly — including any `_src`
    suffix. An earlier version stripped `_src` to match the markdown filename,
    which made `X.pdf` and `X_src.pdf` collide on one preview name, and no
    longer matches the figure convention either (figures key off the PDF stem,
    `_src` included).
    """
    stem = os.path.splitext(os.path.basename(pdf_path))[0]
    return os.path.join(out_dir, f"{stem}_page{idx + 1}.png")


class PreviewPublicationError(OSError):
    """A complete staged preview set could not be published safely."""

    def __init__(self, message, staging_path, recovery_paths=()):
        super().__init__(message)
        self.staging_path = staging_path
        self.recovery_paths = tuple(recovery_paths)


def preflight_preview_paths(out_dir, pdf_path, page_idxs):
    """Return distinct output paths only when every slot is unoccupied.

    The whole page list is checked before rasterization so a late occupied
    slot cannot leave an earlier requested preview behind. Publication still
    uses an exclusive hard link because this preflight does not reserve names.
    """
    paths = [preview_path(out_dir, pdf_path, idx) for idx in page_idxs]
    duplicates = sorted({path for path in paths if paths.count(path) > 1})
    if duplicates:
        raise ValueError(
            "the page list names the same preview slot more than once: %s" %
            ", ".join(duplicates))
    occupied = [path for path in paths if os.path.lexists(path)]
    if occupied:
        raise FileExistsError(
            "preview output already exists; use a fresh scratch directory: %s"
            % ", ".join(occupied))
    return paths


def _rollback_new_previews(publications, stage_parent):
    """Conditionally withdraw this run's earlier publications."""
    errors = []
    recoveries = []
    for path, published in reversed(publications):
        rollback = tempfile.mkdtemp(prefix=".render-page-rollback-",
                                    dir=stage_parent)
        keep = False
        try:
            atomic_move.remove_expected(
                path, published, atomic_move.regular_file_snapshot, rollback,
                stage_parent=stage_parent,
                recovery_prefix=".render-page-recovery-",
            )
        except OSError as exc:
            keep = bool(getattr(exc, "keep_stage", False))
            recovery = getattr(exc, "recovery_path", None)
            if recovery:
                recoveries.append(recovery)
            errors.append("%s: %s" % (path, exc))
        finally:
            if not keep:
                shutil.rmtree(rollback, ignore_errors=True)
    return errors, recoveries


def render_preview_set(doc, pdf_path, page_idxs, out_dir, dpi):
    """Stage every page, then publish the complete requested set safely."""
    paths = preflight_preview_paths(out_dir, pdf_path, page_idxs)
    resolved_out = os.path.realpath(out_dir)
    stage_parent = os.path.dirname(resolved_out) or os.curdir
    stage_dir = tempfile.mkdtemp(prefix=".render-page-stage-",
                                 dir=stage_parent)
    rendered = []
    keep_stage = False
    try:
        # Finish every raster before publishing the first pathname. A render
        # failure therefore exposes no partial preview set.
        for idx, out_path in zip(page_idxs, paths):
            staged = os.path.join(stage_dir, os.path.basename(out_path))
            page = doc[idx]
            pix = page.get_pixmap(dpi=dpi)
            pix.save(staged)
            rendered.append((idx, out_path, staged, pix.width, pix.height))

        publications = []
        try:
            for _idx, out_path, staged, _width, _height in rendered:
                published = atomic_move.publish_new(
                    staged, out_path, atomic_move.regular_file_snapshot,
                    stage_parent, recovery_prefix=".render-page-recovery-")
                publications.append((out_path, published))
        except BaseException as exc:
            rollback_errors, recoveries = _rollback_new_previews(
                publications, stage_parent)
            keep_stage = True
            detail = (
                "; earlier previews were rolled back"
                if publications and not rollback_errors else "")
            if rollback_errors:
                detail += "; rollback incomplete: " + "; ".join(rollback_errors)
            inherited = getattr(exc, "recovery_path", None)
            if inherited:
                recoveries.append(inherited)
            raise PreviewPublicationError(
                "%s%s; complete staged previews are preserved at %s" %
                (exc, detail, stage_dir),
                stage_dir,
                recoveries,
            ) from exc
        return [(idx, path, width, height)
                for idx, path, _staged, width, height in rendered]
    finally:
        if not keep_stage:
            shutil.rmtree(stage_dir, ignore_errors=True)


def px_to_pt(dpi):
    """The factor that turns a pixel coordinate read off the preview into pt.

    The whole reason this script prints anything at all besides a filename:
    `extract_figures.py --crop` takes POINTS, the preview is in PIXELS, and
    skipping the conversion is not an error — it is a crop of the wrong part
    of the page.
    """
    return 72.0 / dpi


def positive_int(value):
    """An argparse integer strictly above zero."""
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise argparse.ArgumentTypeError("must be an integer")
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def run_self_test():
    """Run the built-in cases; print `N/M self-test cases pass`, return 0/1.

    Fixtures are built inside this function: `tests/test_conventions.py`'s
    `check_scripts_run` imports this module and fails it for anything computed
    at module scope. Nothing is written outside a `tempfile` directory.
    """
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

    def exits(label, fn, *a):
        state["n"] += 1
        try:
            fn(*a)
        except SystemExit as exc:
            return str(exc.code if exc.code is not None else "")
        state["bad"] += 1
        print("FAIL %s: expected a clean exit, got none" % label)
        return None

    class NarrowConsole:
        def __init__(self):
            self.calls = []

        def reconfigure(self, **kwargs):
            self.calls.append(kwargs)

    narrow_out, narrow_err = NarrowConsole(), NarrowConsole()
    with mock.patch.object(sys, "stdout", narrow_out), \
            mock.patch.object(sys, "stderr", narrow_err):
        _configure_stdio()
    check("narrow stdout is switched to UTF-8",
          narrow_out.calls, [{"encoding": "utf-8", "errors": "backslashreplace"}])
    check("narrow stderr is switched to UTF-8",
          narrow_err.calls, [{"encoding": "utf-8", "errors": "backslashreplace"}])

    # --- parse_pages -------------------------------------------------------
    check("one page", parse_pages("16", 20), [15])
    check("several pages", parse_pages("16,17,18", 20), [15, 16, 17])
    check("whitespace and a trailing comma",
          parse_pages(" 3 , 4 , ", 20), [2, 3])
    check("the first page", parse_pages("1", 1), [0])
    msg = exits("a non-numeric page", parse_pages, "sixteen", 20)
    ok("...says what was wrong", msg and "not an integer" in msg)
    msg = exits("page 0", parse_pages, "0", 20)
    ok("...page numbers are 1-indexed", msg and "out of range" in msg)
    msg = exits("a page past the end", parse_pages, "21", 20)
    ok("...says how many pages there are", msg and "PDF has 20 pages" in msg)
    exits("a negative page", parse_pages, "-2", 20)
    exits("no page at all", parse_pages, ",", 20)
    # Every page is checked before anything is rendered.
    exits("a good page followed by a bad one", parse_pages, "1,99", 20)

    # --- preview_path ------------------------------------------------------
    check("the preview name is 1-indexed",
          preview_path("/out", "/src/Doe_Foo_2025.pdf", 15),
          os.path.join("/out", "Doe_Foo_2025_page16.png"))
    check("`_src` is kept, so X.pdf and X_src.pdf do not collide",
          preview_path("/out", "/src/Doe_Foo_2025_src.pdf", 0),
          os.path.join("/out", "Doe_Foo_2025_src_page1.png"))
    ok("...and the two names really do differ",
       preview_path("/out", "/src/Doe_Foo_2025.pdf", 0)
       != preview_path("/out", "/src/Doe_Foo_2025_src.pdf", 0))

    # --- px_to_pt ----------------------------------------------------------
    check("the default 100 DPI", px_to_pt(100), 0.72)
    check("--dpi 72 makes pixels and points the same number", px_to_pt(72), 1.0)
    check("150 DPI", px_to_pt(150), 0.48)

    # The estimate runs before PyMuPDF's native raster allocation. The extra
    # boundary pixel on each axis makes it a safe upper bound for fractional
    # clip origins rather than an exact output-size prediction.
    class RectSize:
        width = 612
        height = 792

    width, height = checked_render_dimensions(RectSize(), 600, "test page")
    ok("a full Letter page at 600 DPI remains below the render cap",
       width * height <= MAX_RENDER_PIXELS)
    huge_error = None
    try:
        checked_render_dimensions(RectSize(), 100_000, "test page")
    except ValueError as exc:
        huge_error = str(exc)
    ok("an extreme DPI is refused before rendering",
       bool(huge_error and "pre-render safety cap" in huge_error))

    # --- main(), end to end -------------------------------------------------
    tmp = tempfile.mkdtemp(prefix="render-page-selftest-")
    try:
        pdf = os.path.join(tmp, "Doe_Foo_2025.pdf")
        doc = fitz.open()
        for i in range(3):
            page = doc.new_page(width=612, height=792)
            page.insert_text((72, 100), "Page %d." % (i + 1), fontsize=10)
        doc.save(pdf)
        doc.close()

        def run(argv):
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

        out = os.path.join(tmp, "previews")
        code, so, se = run([pdf, "2,3", "--out", out, "--dpi", "72"])
        check("a render run exits 0", code, 0)
        p2 = os.path.join(out, "Doe_Foo_2025_page2.png")
        p3 = os.path.join(out, "Doe_Foo_2025_page3.png")
        ok("both previews were written",
           os.path.exists(p2) and os.path.exists(p3))
        ok("the run names what it wrote", p2 in so and p3 in so)
        ok("at 72 DPI a 612x792 pt page is 612x792 px",
           "612x792 px" in so)
        ok("the run states the px → pt factor for the DPI it used",
           "multiply by 1.000" in so)
        ok("...and says --crop takes points", "POINTS" in so)
        code, so, se = run([pdf, "1", "--out", out, "--dpi", "100"])
        ok("at 100 DPI the same page is 850x1100 px", "850x1100 px" in so)
        ok("...and the factor follows the DPI", "multiply by 0.720" in so)
        ok("the output directory is created when it does not exist",
           os.path.isdir(out))
        ok("a fresh preview prints no refusal", "REFUSED" not in se)

        # The default is unique per invocation, so concurrent inspections of
        # same-stem sources cannot overwrite each other's coordinate image.
        default_dirs = []
        for _ in range(2):
            code, so, se = run([pdf, "1", "--dpi", "72"])
            check("a default-directory render exits 0", code, 0)
            written = so.split("Wrote ", 1)[1].split(": ", 1)[0]
            default_dirs.append(os.path.dirname(written))
            ok("the default preview is written outside the source tree",
               os.path.isfile(written) and not written.startswith(tmp + os.sep))
            ok("the default run tells the caller to remove its temporary preview",
               "Remove it after visual review" in so)
        ok("two default renders use distinct scratch directories",
           default_dirs[0] != default_dirs[1])
        for directory in default_dirs:
            shutil.rmtree(directory, ignore_errors=True)

        # An occupied slot is user data, even when it resembles an earlier
        # preview. Refuse the whole page set before rasterization/publication.
        p2_before = open(p2, "rb").read()
        code, so, se = run([pdf, "2", "--out", out, "--dpi", "72"])
        check("an occupied preview is refused", code, 1)
        ok("...and the diagnostic names it and requests fresh scratch",
           p2 in se and "fresh scratch directory" in se)
        check("...and its bytes are preserved", open(p2, "rb").read(), p2_before)

        blocked_out = os.path.join(tmp, "blocked-previews")
        os.makedirs(blocked_out)
        blocked_p2 = preview_path(blocked_out, pdf, 1)
        with open(blocked_p2, "wb") as fh:
            fh.write(b"existing preview")
        code, so, se = run([pdf, "1,2", "--out", blocked_out, "--dpi", "72"])
        check("a later occupied slot refuses a multi-page request", code, 1)
        ok("...before an earlier preview is published",
           not os.path.lexists(preview_path(blocked_out, pdf, 0)))
        check("...and preserves the occupied bytes",
              open(blocked_p2, "rb").read(), b"existing preview")

        duplicate_out = os.path.join(tmp, "duplicate-previews")
        code, so, se = run([pdf, "1,1", "--out", duplicate_out, "--dpi", "72"])
        check("a repeated page is refused as one duplicate slot", code, 1)
        ok("...without publishing the duplicated name",
           not os.path.lexists(preview_path(duplicate_out, pdf, 0)))

        if hasattr(os, "symlink"):
            linked_out = os.path.join(tmp, "linked-previews")
            os.makedirs(linked_out)
            victim = os.path.join(tmp, "preview-link-target")
            with open(victim, "wb") as fh:
                fh.write(b"preserve target")
            linked_preview = preview_path(linked_out, pdf, 0)
            try:
                os.symlink(victim, linked_preview)
                have_link = True
            except (OSError, NotImplementedError):
                have_link = False
            if have_link:
                code, so, se = run([pdf, "1", "--out", linked_out, "--dpi", "72"])
                check("a symlink preview occupant is refused", code, 1)
                ok("...without removing the link", os.path.islink(linked_preview))
                check("...or touching its target", open(victim, "rb").read(),
                      b"preserve target")
            else:
                ok("symlink preview refusal skipped where unavailable", True)
                ok("symlink occupant preservation skipped where unavailable", True)
                ok("symlink target preservation skipped where unavailable", True)

        # A name that arrives after preflight is preserved. If another page
        # was already published, this run conditionally withdraws only that
        # exact new file so the requested set is not left half complete.
        race_out = os.path.join(tmp, "race-previews")
        os.makedirs(race_out)
        real_publish = atomic_move.publish_new
        publish_calls = {"count": 0}

        def race_publish(staged, target, snapshot, stage_parent, **kwargs):
            publish_calls["count"] += 1
            if publish_calls["count"] == 2:
                with open(target, "wb") as fh:
                    fh.write(b"late occupant")
            return real_publish(staged, target, snapshot, stage_parent, **kwargs)

        with mock.patch.object(atomic_move, "publish_new", side_effect=race_publish):
            code, so, se = run([pdf, "1,2", "--out", race_out, "--dpi", "72"])
        check("a late occupant makes the preview-set publication fail", code, 1)
        ok("...and the earlier publication is rolled back",
           not os.path.lexists(preview_path(race_out, pdf, 0)))
        check("...while the late occupant survives",
              open(preview_path(race_out, pdf, 1), "rb").read(), b"late occupant")
        ok("...and retained staged previews are named", "staged previews" in se)

        code, so, se = run([pdf, "9", "--out", out])
        ok("a page past the end is refused", "out of range" in str(code))
        code, so, se = run([pdf, "x", "--out", out])
        ok("a non-numeric page is refused", "not an integer" in str(code))
        code, so, se = run([pdf, "1", "--out", out, "--dpi", "0"])
        check("a non-positive DPI exits 2", code, 2)
        ok("...explains the positive bound", "greater than zero" in se)

        limited_out = os.path.join(tmp, "limited-previews")
        code, so, se = run([
            pdf, "1,2", "--out", limited_out, "--dpi", "100000"])
        ok("an oversized preview is refused with an actionable error",
           "pre-render safety cap" in str(code) and "lower --dpi" in str(code))
        ok("all preview sizes are checked before creating the output folder",
           not os.path.lexists(limited_out))

        zero = os.path.join(tmp, "Doe_Empty_2025.pdf")
        with open(zero, "wb") as fh:
            fh.write(b"%PDF-1.4\n"
                     b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
                     b"2 0 obj\n<< /Type /Pages /Kids [] /Count 0 >>\nendobj\n"
                     b"trailer\n<< /Root 1 0 R /Size 3 >>\n%%EOF\n")
        code, so, se = run([zero, "1", "--out", out])
        ok("a zero-page PDF is refused", "zero pages" in str(code))

        junk = os.path.join(tmp, "Doe_Junk_2025.pdf")
        with open(junk, "wb") as fh:
            fh.write(b"\x00\x01 not a document at all")
        code, so, se = run([junk, "1", "--out", out])
        ok("a file that is not a document is refused",
           "could not open" in str(code))

        html = os.path.join(tmp, "Doe_Html_2025.pdf")
        with open(html, "w", encoding="utf-8") as fh:
            fh.write("<html><body>Not a PDF.</body></html>")
        code, so, se = run([html, "1", "--out", out])
        ok("an HTML document named .pdf is refused",
           "not a PDF" in str(code) or "could not open as a PDF" in str(code))

        code, so, se = run([pdf])
        check("a missing page list exits 2", code, 2)
        ok("...naming it", "pages" in se)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("%d/%d self-test cases pass"
          % (state["n"] - state["bad"], state["n"]))
    return 1 if state["bad"] else 0


def main(argv=None):
    _configure_stdio()
    p = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=__doc__,
    )
    p.add_argument("pdf", nargs="?")
    p.add_argument(
        "pages", nargs="?",
        help="Comma-separated 1-indexed page numbers, e.g. '16' or '16,17,18'.",
    )
    p.add_argument(
        "--out",
        help="Output directory (default: a unique OS temporary directory).",
    )
    p.add_argument(
        "--dpi",
        type=positive_int,
        default=100,
        help=("Resolution for the preview render (default: 100); each page is "
              f"limited to {MAX_RENDER_PIXELS:,} pixels."),
    )
    p.add_argument("--test", action="store_true", help="run the self-test")
    args = p.parse_args(argv)

    if args.test:
        _require_pymupdf()
        return run_self_test()
    # Named rather than left to argparse's positional requirement: `--test`
    # takes neither argument, so a required positional rejects the self-test
    # before `main()` can see it. Same shape and exit code as
    # `paper_scan.py`'s missing-argument path.
    missing = [f for f in ("pdf", "pages") if not getattr(args, f)]
    if missing:
        print("missing required argument(s): %s" % ", ".join(missing),
              file=sys.stderr)
        return 2
    _require_pymupdf()

    pdf_path = os.path.expanduser(args.pdf)
    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        sys.exit(f"{pdf_path}: could not open as a PDF ({e})")
    try:
        if not doc.is_pdf:
            fmt = (doc.metadata or {}).get("format") or "an unknown format"
            sys.exit(f"{pdf_path}: not a PDF — opened as {fmt}")
        if getattr(doc, "needs_pass", False) or getattr(doc, "is_encrypted", False):
            sys.exit(f"{pdf_path}: encrypted/password-protected PDF — decrypt "
                     "a unique scratch copy before rendering pages")
        if len(doc) == 0:
            sys.exit(f"{pdf_path}: PDF has zero pages — nothing to render")
        page_idxs = parse_pages(args.pages, len(doc))
        # Size-check every page before creating the output directory. A later
        # oversized page must not leave earlier previews from a partially
        # completed invocation, and the check must precede native allocation.
        for idx in page_idxs:
            try:
                checked_render_dimensions(
                    doc[idx].rect, args.dpi, f"page {idx + 1}")
            except ValueError as exc:
                sys.exit(f"{pdf_path}: {exc}")
        automatic_out = args.out is None
        out_dir = (os.path.expanduser(args.out) if args.out
                   else tempfile.mkdtemp(prefix="obsidian-figure-preview-"))
        try:
            os.makedirs(out_dir, exist_ok=True)
            if not os.path.isdir(out_dir):
                raise NotADirectoryError("preview output is not a directory: %s"
                                         % out_dir)
            rendered = render_preview_set(
                doc, pdf_path, page_idxs, out_dir, args.dpi)
        except (FileExistsError, NotADirectoryError, PreviewPublicationError,
                ValueError) as exc:
            print("REFUSED: %s" % exc, file=sys.stderr)
            for recovery in getattr(exc, "recovery_paths", ()):
                print("  preserve recovery state at %s" % recovery,
                      file=sys.stderr)
            if automatic_out:
                try:
                    os.rmdir(out_dir)
                except OSError:
                    pass
            return 1
        except Exception as exc:
            print("ERROR: could not render the requested preview set: %s: %s"
                  % (type(exc).__name__, exc), file=sys.stderr)
            if automatic_out:
                try:
                    os.rmdir(out_dir)
                except OSError:
                    pass
            return 1

        for idx, out_path, width, height in rendered:
            page = doc[idx]
            scale = px_to_pt(args.dpi)
            print(
                f"Wrote {out_path}: {width}x{height} px "
                f"(page rect: {page.rect.width:.0f}x{page.rect.height:.0f} pts)"
            )
            print(
                f"  px → pt: multiply by {scale:.3f} "
                f"(x_pt = x_px * {scale:.3f}). --crop takes POINTS, and the "
                f"caption's top edge is the hard limit for y1."
            )
        if automatic_out:
            print("  Temporary preview directory: %s. Remove it after visual "
                  "review and any required crop repair." % out_dir)
        return 0
    finally:
        doc.close()


if __name__ == "__main__":
    # `sys.exit(main())`: `--test` and the missing-argument path both report
    # through the exit code, and a bare call throws it away.
    sys.exit(main())
