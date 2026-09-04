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
    python3 render_page.py input.pdf 16 --out ~/Desktop --dpi 150
    python3 render_page.py input.pdf 16 --dpi 72     # 1 px == 1 pt

    # The adversarial fixtures this module is held to.
    python3 render_page.py --test
"""
import argparse
import os
import sys
import tempfile


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
        sys.exit(
            "PyMuPDF required. Use a Python environment with the plugin\n"
            "dependencies installed; see shared/RUNTIME.md. Install into a\n"
            "virtual environment, not the system Python."
        )


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
        ok("a fresh preview prints no replacement notice",
           "replacing existing preview" not in se)

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
        ok("two default renders use distinct scratch directories",
           default_dirs[0] != default_dirs[1])
        for directory in default_dirs:
            shutil.rmtree(directory, ignore_errors=True)
        # A preview name already on disk — a re-render, or another PDF that
        # merely shares the stem — is replaced WITH a notice, never silently:
        # coordinates read off a stale or wrong preview are a wrong crop.
        code, so, se = run([pdf, "2", "--out", out, "--dpi", "72"])
        check("re-rendering an existing preview still exits 0", code, 0)
        ok("...and says it is replacing the file, naming it",
           "replacing existing preview" in se and p2 in se)
        ok("...and the preview is still written", os.path.exists(p2))

        code, so, se = run([pdf, "9", "--out", out])
        ok("a page past the end is refused", "out of range" in str(code))
        code, so, se = run([pdf, "x", "--out", out])
        ok("a non-numeric page is refused", "not an integer" in str(code))
        code, so, se = run([pdf, "1", "--out", out, "--dpi", "0"])
        check("a non-positive DPI exits 2", code, 2)
        ok("...explains the positive bound", "greater than zero" in se)

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
        ok("an HTML document named .pdf is refused", "not a PDF" in str(code))

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
        help="Resolution for the preview render (default: 100).",
    )
    p.add_argument("--test", action="store_true", help="run the self-test")
    args = p.parse_args(argv)

    if args.test:
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
        out_dir = (os.path.expanduser(args.out) if args.out
                   else tempfile.mkdtemp(prefix="obsidian-figure-preview-"))
        os.makedirs(out_dir, exist_ok=True)

        for idx in page_idxs:
            page = doc[idx]
            pix = page.get_pixmap(dpi=args.dpi)
            out_path = preview_path(out_dir, pdf_path, idx)
            # Previews are named `<stem>_page<N>.png`, so a re-render — or another
            # PDF that merely shares the stem, the exact collision batch_extract
            # warns about — lands on the same name. Replacing is what a preview
            # wants, but doing it silently is how coordinates get read off the
            # wrong document; every other writer in this plugin says so or skips.
            if os.path.lexists(out_path):
                print(f"note: replacing existing preview {out_path}",
                      file=sys.stderr)
            pix.save(out_path)
            scale = px_to_pt(args.dpi)
            print(
                f"Wrote {out_path}: {pix.width}x{pix.height} px "
                f"(page rect: {page.rect.width:.0f}x{page.rect.height:.0f} pts)"
            )
            print(
                f"  px → pt: multiply by {scale:.3f} "
                f"(x_pt = x_px * {scale:.3f}). --crop takes POINTS, and the "
                f"caption's top edge is the hard limit for y1."
            )
        return 0
    finally:
        doc.close()


if __name__ == "__main__":
    # `sys.exit(main())`: `--test` and the missing-argument path both report
    # through the exit code, and a bare call throws it away.
    sys.exit(main())
