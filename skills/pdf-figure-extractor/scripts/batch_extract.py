"""Batch-extract figures from every PDF under a source directory tree.

Walks `--src` recursively, runs caption detection (auto_fig_bbox) and figure
cropping (extract_figures) on each PDF, and writes the results to a flat
`--out` directory using the naming convention:

    [pdf_stem]_fig_<N>.png

where pdf_stem is the source PDF's on-disk filename stem (exactly as it
appears, any `_src` suffix included) and <N> can be:
  - integer:          1, 23
  - dash-separated:   1-2, 1-2-4   (source captions like "Figure 1.2" or "Figure 1-2")
  - supplementary:    S1, S2-3     (source captions like "Figure S1",
                                    "Supplementary Figure 1", "Extended Data Figure 1")
  - appendix letter:  A-1, A1      (source captions like "Figure A.1", "Figure A1")

That name is the interface `wiki-builder` globs for (`Sources/Images/
[source_stem]_fig*`). Changing it here breaks that lookup silently — entries
get no images and the unused-figure diagnostic stays quiet, because it walks
the same pattern.

pdf_stem is also why `pdf-organizer` runs before this script and not after:
renaming a source PDF later leaves every PNG filed under the old stem, on
disk but invisible to every consumer.  See shared/CONVENTIONS.md 1a and 8.

Captions themselves are NOT included in the cropped PNGs — the bbox detector
clips just above the caption text.

Behavior:
  - Idempotent: existing PNGs with verified ownership are skipped. Unknown or
    changed occupants are refused, even with --overwrite.
  - Split books are extracted from the CHAPTERS, not from the whole book.
    pdf-organizer leaves both on disk — the book in `Sources/PDFs/`, the
    chapters in `Sources/PDFs/<Work>/` — and a recursive walk finds both, so every
    figure would otherwise be written twice under two different stems.
    Byte-identical, never colliding, and permanently half-unused, because
    whichever stem an entry cites, the other copy is invisible to the
    unused-figure diagnostic (it is per-source). See "Split books" below.
  - Reports: at the end, prints a summary table with counts of figures
    extracted per PDF, suspicious bboxes flagged for visual review, figures
    that failed to write, PDFs where detection looks PARTIAL (the body text
    cites figure numbers no caption was found for), byte-identical figures
    written under two stems, and the three distinct "produced nothing" cases
    — no captions found, no extractable text (a scan), and not a readable PDF
    at all. Only the second of those is an OCR problem.
  - Output is flat: the pdf_stem in each filename disambiguates across
    subfolders. When --out is a vault's canonical Sources/Images folder, every
    selected stem is checked against every PDF pathname in that vault, even for
    a single-file --src. Otherwise collision scope is the explicit --src, which
    preserves deliberate external one-off extraction. Colliding sources are
    refused before either can write; sources whose stems are unique continue.

Split books:
    pdf-organizer splits `Kuhn_StructSciRev_2012.pdf` into
    `Sources/PDFs/Kuhn_StructSciRev_2012/Kuhn_StructSciRev_2012_01_RoleHistory.pdf`
    and friends, and keeps the book itself. This script detects that shape —
    a PDF in the run whose stem is `<another PDF's stem>_NN_Name` — and skips
    the book, because the chapter stem is what everything downstream keys to
    (pdf-organizer's *Chapter filename format*, CONVENTIONS.md 1a). Pass
    `--include-split-books` to extract from the book as well; you then get
    both copies on purpose rather than by accident.

Usage:
    python3 batch_extract.py \\
        --src '<vault>/Sources/PDFs' \\
        --out '<vault>/Sources/Images'

    # --src also accepts a single PDF:
    python3 batch_extract.py --src /path/to/one_paper.pdf --out ...

    # Dry run — list what would be extracted without writing anything:
    python3 batch_extract.py --src ... --out ... --dry-run

    # Re-extract existing figures whose ownership and bytes are verified:
    python3 batch_extract.py --src ... --out ... --overwrite

    # During an absent-manifest migration, claim only inspected historical
    # extractor crops named exactly (repeat the option for more than one):
    python3 batch_extract.py --src ... --out ... \\
        --adopt-legacy Doe_Study_2025:1

    # Record that a flagged bbox has been checked (and fixed, if it needed it),
    # so later runs stop asking about it:
    python3 batch_extract.py --src ... --out ... \\
        --mark-reviewed Prince_UDL_2026_02_SupLearn:10-5

    # The adversarial fixtures this module is held to.
    python3 batch_extract.py --test
"""
import argparse
import errno
import hashlib
import os
import re
import shlex
import shutil
import stat
import sys
import warnings
from collections import defaultdict
from pathlib import Path

_OBSIDIAN_SHARED_MODULES = ('atomic_move', 'figure_state', 'naming',
                            'vault_artifacts')

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
# The bootstrap also puts this script's own directory on the path, which is
# what makes the sibling `auto_fig_bbox` / `extract_figures` imports below
# work when the script is run as a file rather than via `python -m`.

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


def _require_pymupdf():
    """Fail after argument parsing so --help remains available during setup."""
    if fitz is None:
        raise SystemExit(_PYMUPDF_ERROR)

from auto_fig_bbox import (
    CAPTION_IN_CROP_TAG,
    caption_coverage,
    configure_marker_prefix,
    configure_strip_frame,
    degenerate,
    detect_figures,
    find_caption_blocks,
)
from extract_figures import (extract_one_figure, normalize_fig_num,
                             validated_figure_suffix)
import atomic_move


#: The chapter-stem rule is `pdf-organizer`'s, so it is imported rather than
#: restated. This file used to carry its own `CHAPTER_STEM_RE`, whose chapter
#: name admitted no `_` — so a chapter carrying the `_src` suffix that
#: pdf-organizer's own recogniser puts at the *end*
#: (`Prince_UDL_2026_02_SupLearn_src`) was not recognised as a chapter, the
#: book was not skipped, and every figure was written twice under two stems
#: that never collide and never deduplicate. CONVENTIONS.md §1a, §8b.
from naming import (chapter_book_stem, chapter_parts, core_stem,
                    looks_canonical)  # noqa: E402
from figure_state import (MANIFEST_FILE, REVIEW_FILE, write_manifest,
                          write_review, figure_identity, manifest_key,
                          check_manifest_writable, parse_reviewed, read_sidecar,
                          read_manifest_snapshot)  # noqa: E402
from vault_artifacts import (find_vault_pdfs, inventory_pdfs,
                             inventory_source_figures,
                             output_vault_root,
                             source_stem_groups)  # noqa: E402

#: Default filename for the review ledger, written inside `--out`. A dotfile:
#: Obsidian hides it, and it can never be mistaken for a figure, because
#: every consumer globs `[source_stem]_fig*` and this matches no stem.
REVIEW_HEADER = (
    "# pdf-figure-extractor review marks.\n"
    "# One per line: <pdf_stem><TAB><figure label>[<TAB>note]\n"
    "# A flagged bbox listed here is reported as reviewed, not as needing\n"
    "# review, so a crop you have already checked (or fixed explicitly) stops\n"
    "# coming back every run. Delete a line to un-review it.\n"
)

#: Digests of the figures this extractor has written, beside the review ledger
#: and hidden for the same reasons (Obsidian ignores dotfiles, and it matches
#: no `[source_stem]_fig*` glob).
#:
#: `Sources/Images/` is SHARED. `clipping-processor` writes `<slug>_fig_<N>.
#: <ext>` into the same folder under the same convention (CONVENTIONS.md 8b),
#: so a clipping whose slug equals a paper's stem can already own
#: `<stem>_fig_1.png` — and the idempotent "already exists" skip then reports
#: `1 extracted, 1 skipped (already exist)`, which is exactly what an ordinary
#: re-run reports. The paper's real Figure 1 is never written and every
#: consumer embeds the clipping's picture as it. Knowing which files are this
#: extractor's own output is the only way to tell the two apart, and the digest
#: on the skip path is already being computed for the duplicate check, so
#: keeping it costs nothing on the common re-run path.
MANIFEST_HEADER = (
    "# pdf-figure-extractor output manifest.\n"
    "# One per line: <figure filename><TAB><sha256 of the bytes written>\n"
    "# This is how a re-run tells its own output from another skill's file at\n"
    "# the same name (Sources/Images/ is shared -- see CONVENTIONS.md 8b).\n"
    "# Removing a record or file is destructive: first verify the exact figure\n"
    "# and obtain any authorization the current task has not already supplied.\n"
)

#: Files this extractor writes: the `[stem]_fig_<N>.png` convention of 8b.
#: Used only to seed the duplicate-detection index. Ownership is never inferred
#: from this broad glob; legacy migration names exact files with --adopt-legacy.
FIGURE_GLOB = "*_fig_*.png"


def _configure_stdio():
    """Make paths and Unicode diagnostics printable on narrow host consoles."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="backslashreplace")
            except (OSError, ValueError):
                pass


def split_book_chapters(pdfs):
    """{book path: [chapter paths]} for every book split into chapters.

    Detection is purely by stem, which is what makes it safe: pdf-organizer
    guarantees the chapter stem is the book stem plus `_NN_Name`
    (*Chapter filename format*), and both files are in the same walk. No
    vault layout is assumed, so this works for a Downloads folder too.

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
    out = defaultdict(list)
    for p in pdfs:
        book = chapter_book_stem(p.stem, is_stem=True)
        if not book:
            continue
        for bp in by_stem.get(book.casefold(), []):
            if bp != p:
                out[bp].append(p)
    return {book: sorted(chs) for book, chs in out.items()}


_CHAPTER_FIGURE_LABEL_RE = re.compile(
    r"^(?P<chapter>[0-9]+)-[0-9]+(?:-[0-9]+)*$")


def _chapter_figure_label_match(label):
    """Match a numeric chapter label after normalizing supported separators."""
    normalized = (str(label).replace(".", "-").replace("–", "-")
                  .replace("—", "-"))
    return _CHAPTER_FIGURE_LABEL_RE.fullmatch(normalized)


def _normalized_chapter_figure_label(label):
    """Canonical separator spelling for one numeric chapter figure label."""
    match = _chapter_figure_label_match(label)
    return match.group(0) if match is not None else None


def _regular_file_snapshot(path):
    """Stable identity surface for a regular file, or ``None`` on failure."""
    try:
        item = os.stat(path)
    except OSError:
        return None
    if not stat.S_ISREG(item.st_mode):
        return None
    return (
        item.st_dev,
        item.st_ino,
        item.st_size,
        getattr(item, "st_mtime_ns", int(item.st_mtime * 1e9)),
        getattr(item, "st_ctime_ns", int(item.st_ctime * 1e9)),
        stat.S_IMODE(item.st_mode),
    )


def _caption_labels_for_chapter(pdf_path, cache):
    """Exact labels in one stable readable sibling, or ``None``.

    This evidence suppresses a PARTIAL warning, so a sibling that changes
    during the read cannot count as proof. Cached evidence is also tied to the
    same file identity and metadata rather than surviving an in-place edit or
    pathname replacement later in the run.
    """
    key = os.path.abspath(os.fspath(pdf_path))
    if key in cache:
        cached_snapshot, cached_labels = cache[key]
        if (cached_snapshot is not None
                and cached_snapshot == _regular_file_snapshot(key)):
            return cached_labels
        # Once an inventory member moves during the run, retain the warning.
        # Rescanning its replacement could combine evidence from two different
        # source snapshots under one supposedly complete PDF inventory.
        cache[key] = (None, None)
        return None
    before = _regular_file_snapshot(key)
    if before is None:
        cache[key] = (None, None)
        return None
    doc = None
    try:
        doc = fitz.open(key)
        if not getattr(doc, "is_pdf", True):
            raise ValueError("not a PDF")
        labels = {
            normalized
            for page_index in range(len(doc))
            for label, _raw, _bbox in find_caption_blocks(doc[page_index])
            for normalized in (_normalized_chapter_figure_label(label),)
            if normalized is not None
        }
    except Exception:
        labels = None
    finally:
        if doc is not None:
            doc.close()
    after = _regular_file_snapshot(key)
    if before != after:
        labels = None
        after = None
    cache[key] = (after, labels)
    return labels


def partition_cross_chapter_references(pdf_path, found_labels, missing,
                                       chapter_pdfs=(), caption_cache=None):
    """Separate confidently external chapter references from local misses.

    A split-chapter filename supplies an expected chapter number, but that alone
    is not enough: printed chapter numbering can differ from a split plan. We
    classify ``6-6`` as external to chapter 07 only when every detected numeric
    chapter-style caption agrees on the local prefix ``7`` *and* exactly one
    canonical same-book chapter 06 is in the complete source/vault inventory
    and contains an exact ``6-6`` caption. Dot, en-dash, and em-dash separators
    compare as hyphens. Mixed namespaces, ambiguous/absent/unreadable/changing
    siblings, labels absent from the sibling, and same-prefix misses remain PARTIAL
    evidence. External references stay reportable rather than vanishing.
    """
    parts = chapter_parts(Path(pdf_path).stem, is_stem=True)
    if parts is None or not looks_canonical(Path(pdf_path).stem, is_stem=True):
        return list(missing), []
    local_prefix = str(int(parts.number))
    found_prefixes = set()
    for label in found_labels:
        text = str(label)
        if not text[:1].isdigit():
            continue
        match = _chapter_figure_label_match(text)
        if match is None:
            # A plain numeric label or another numeric scheme means the PDF's
            # local namespace is mixed or uncertain. Do not hide any miss.
            return list(missing), []
        found_prefixes.add(match.group("chapter"))
    if found_prefixes != {local_prefix}:
        return list(missing), []

    cache = caption_cache if caption_cache is not None else {}
    book_key = figure_identity(parts.book)
    local_missing = []
    cross_chapter = []
    for label in missing:
        match = _chapter_figure_label_match(label)
        if match is None or match.group("chapter") == local_prefix:
            local_missing.append(label)
            continue
        wanted_chapter = int(match.group("chapter"))
        candidates = []
        for candidate in chapter_pdfs:
            candidate = Path(candidate)
            candidate_parts = chapter_parts(candidate.stem, is_stem=True)
            if (candidate_parts is not None
                    and looks_canonical(candidate.stem, is_stem=True)
                    and figure_identity(candidate_parts.book) == book_key
                    and int(candidate_parts.number) == wanted_chapter):
                candidates.append(candidate)
        normalized = _normalized_chapter_figure_label(label)
        sibling_labels = (_caption_labels_for_chapter(candidates[0], cache)
                          if len(candidates) == 1 else None)
        if sibling_labels is not None and normalized in sibling_labels:
            cross_chapter.append(label)
        else:
            local_missing.append(label)
    return local_missing, cross_chapter


def reviewable_stems(pdfs, include_split_books=False, allow_unorganized=False):
    """Exact source stems eligible for a review mark in this run.

    A mark suppresses a geometry warning by ``(stem, label)`` alone. It must
    therefore name one source the run will actually process, rather than a
    skipped/refused source or either member of a same-stem collision.
    """
    selected = list(pdfs)
    if not include_split_books:
        skipped = set(split_book_chapters(selected))
        selected = [source for source in selected if source not in skipped]
    if not allow_unorganized:
        selected = [source for source in selected
                    if looks_canonical(source.stem, is_stem=True)]
    groups = defaultdict(list)
    for source in selected:
        groups[figure_identity(source.stem)].append(source)
    return {source.stem for source in selected
            if len(groups[figure_identity(source.stem)]) == 1}


def load_reviewed(path):
    """{(pdf_stem, figure label)} marked reviewed in the ledger at `path`.

    The ledger's own format is TAB-separated (`REVIEW_HEADER`), and a line that
    has a tab is split on tabs ALONE. A `STEM:FIG` line is accepted too, for a
    ledger a user typed by hand in the same spelling `--mark-reviewed` takes,
    and it is split the way `mark_reviewed` splits it: on the LAST colon.

    Both halves used to be one `re.split(r"[\\t:]+")`, which broke every stem
    containing a colon. `mark_reviewed` writes `A:B<TAB>10-5` for
    `--mark-reviewed A:B:10-5` -- correctly, via `rpartition` -- and this read
    it back as the pair `("A", "B")`. The mark then matched no figure, so the
    bbox the user had just checked came back flagged on the next run, and the
    ledger looked like it had recorded something. The two ends of one file
    disagreed about its format, and nothing compared them.
    """
    text, _snapshot = read_sidecar(path)
    return parse_reviewed(text)


def mark_reviewed(path, entries, dry_run=False, allowed_stems=None):
    """Append `STEM:FIG` entries to the ledger; returns what was recorded.

    `dry_run` parses and validates the entries but writes nothing — not the
    ledger, and not the `--out` directory that `os.makedirs` below would
    otherwise create. `--dry-run` is documented as writing nothing at all, and
    it is the run a user makes against a path they have not committed to yet:
    a mistyped `--out` would be left behind as an empty folder in the vault.
    A malformed `STEM:FIG` still exits here, because reporting the syntax
    error only on the real run is the same surprise the other way round.
    """
    allowed_stems = None if allowed_stems is None else set(allowed_stems)
    recorded = []
    for e in entries:
        stem, sep, fig = e.rpartition(":")
        if not sep or not stem.strip() or not fig.strip():
            sys.exit(
                f"--mark-reviewed {e!r}: expected STEM:FIG, e.g. "
                f"--mark-reviewed Prince_UDL_2026_02_SupLearn:10-5"
            )
        stem = stem.strip()
        fig = fig.strip()
        if allowed_stems is not None and stem not in allowed_stems:
            sys.exit(
                f"--mark-reviewed {e!r}: {stem!r} is not the exact on-disk "
                "stem of one eligible, uniquely identified PDF in this run. "
                "Copy the stem and options from the flagged report; no review "
                "record was written"
            )
        recorded.append((stem, fig))
    rows = "".join(f"{stem}\t{fig}\n" for stem, fig in recorded)
    parse_reviewed(rows)
    previous, expected = read_sidecar(path)
    parse_reviewed(previous)
    if dry_run:
        return recorded
    body = previous
    if not body:                                 # a fresh ledger: explain itself
        body = REVIEW_HEADER
    elif not body.endswith(("\n", "\r")):
        body += "\n"
    body += rows
    write_review(path, body, expected=expected)
    return recorded


def load_manifest(path, with_snapshot=False):
    """{figure filename: sha256} recorded by earlier runs, or {} when absent.

    The returned snapshot distinguishes a missing file from an existing empty
    manifest. Missing ownership records never claim occupied image names;
    explicit absent-manifest migration is handled by `adopt_legacy_files`.
    """
    manifest, snapshot = read_manifest_snapshot(path)
    return (manifest, snapshot) if with_snapshot else manifest


def save_manifest(path, manifest, expected=None, return_snapshot=False):
    """Rewrite ownership records; False means the run must report failure.

    ``return_snapshot`` lets a long batch carry the version just published
    into the next conditional write. The default boolean result preserves the
    small programmatic API used by older callers.
    """
    try:
        snapshot = write_manifest(path, manifest, MANIFEST_HEADER,
                                  expected=expected)
        return snapshot if return_snapshot else True
    except (OSError, ValueError) as e:
        print(f"note: could not write {path} ({e}) — the next run cannot tell "
              f"its own figures from another skill's", file=sys.stderr)
        return False


def _legacy_png_snapshot(path):
    """Validate and snapshot one exact PNG before recording its ownership."""
    try:
        from PIL import Image
    except ImportError:
        sys.exit("Pillow is required to verify legacy PNGs before recording "
                 "ownership. Use the Python environment from shared/RUNTIME.md.")
    flags = (os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
             | getattr(os, "O_BINARY", 0))
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ValueError("it is not a readable regular file (%s)" % exc) from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise ValueError("it is not a regular file")
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with os.fdopen(os.dup(descriptor), "rb") as image_file:
                    with Image.open(image_file, formats=("PNG",)) as image:
                        image.verify()
                # Chunk validation alone does not decompress the pixel stream.
                with os.fdopen(os.dup(descriptor), "rb") as image_file:
                    with Image.open(image_file, formats=("PNG",)) as image:
                        image.load()
        except (OSError, ValueError, SyntaxError,
                Image.DecompressionBombError,
                Image.DecompressionBombWarning) as exc:
            raise ValueError("the PNG cannot be fully decoded (%s)" % exc) from exc
        os.lseek(descriptor, 0, os.SEEK_SET)
        digest = hashlib.sha256()
        for chunk in iter(lambda: os.read(descriptor, 65536), b""):
            digest.update(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    try:
        at_name = os.stat(path, follow_symlinks=False)
    except OSError as exc:
        raise ValueError("it changed while its bytes were validated") from exc
    stable = lambda item: (
        item.st_dev, item.st_ino, item.st_size,
        getattr(item, "st_mtime_ns", int(item.st_mtime * 1e9)),
        getattr(item, "st_ctime_ns", int(item.st_ctime * 1e9)),
        stat.S_IMODE(item.st_mode),
    )
    if not (stable(before) == stable(after) == stable(at_name)):
        raise ValueError("it changed while its bytes were validated")
    return stable(after) + (digest.hexdigest(),)


def adopt_legacy_files(out_dir, entries, eligible_stems, manifest,
                       manifest_existed):
    """Explicitly claim complete PNGs in currently unrecorded figure slots."""
    if not entries:
        return []
    eligible_stems = set(eligible_stems)
    planned = []
    seen_targets = set()
    for entry in entries:
        stem, sep, label = entry.rpartition(":")
        if not sep or not stem or not label:
            raise ValueError(
                "--adopt-legacy %r: expected STEM:FIG, for example "
                "Doe_Study_2025:1" % entry)
        if stem != stem.strip() or label != label.strip():
            raise ValueError(
                "--adopt-legacy %r: copy the exact on-disk stem and figure "
                "label without surrounding whitespace" % entry)
        if stem not in eligible_stems:
            raise ValueError(
                "--adopt-legacy %r: %r is not the exact on-disk stem of one "
                "eligible, uniquely identified PDF in this run" %
                (entry, stem))
        try:
            suffix = validated_figure_suffix(label)
        except ValueError as exc:
            raise ValueError("--adopt-legacy %r: %s" % (entry, exc)) from exc
        filename = "%s_fig_%s.png" % (stem, suffix)
        prior_key = manifest_key(manifest, filename)
        if prior_key is not None:
            raise ValueError(
                "--adopt-legacy %r names %s, which already has an ownership "
                "record; adoption is only for an unrecorded slot" %
                (entry, prior_key))
        identity = figure_identity(filename)
        if identity in seen_targets:
            raise ValueError(
                "--adopt-legacy %r repeats an already selected figure slot" %
                entry)
        seen_targets.add(identity)
        path = Path(out_dir) / filename
        if not path.exists() or path.is_symlink():
            raise ValueError(
                "--adopt-legacy %r requires the exact regular file %s" %
                (entry, path))
        siblings = [candidate for candidate in Path(out_dir).iterdir()
                    if figure_identity(candidate.name) == identity]
        if len(siblings) != 1 or siblings[0].name != filename:
            raise ValueError(
                "--adopt-legacy %r is ambiguous under portable filename "
                "identity; expected exactly %s" % (entry, path))
        try:
            snapshot = _legacy_png_snapshot(path)
        except (OSError, ValueError) as exc:
            raise ValueError(
                "--adopt-legacy %r refused %s: %s" %
                (entry, path, exc)) from exc
        planned.append((path, filename, snapshot))
    for _path, filename, snapshot in planned:
        manifest[filename] = snapshot[-1]
    return planned


def revalidate_legacy_adoptions(adoptions, manifest):
    """Drop and report any claim whose exact PNG changed before sidecar save."""
    stable = True
    for path, filename, expected in adoptions:
        try:
            current = _legacy_png_snapshot(path)
        except (OSError, ValueError) as exc:
            current = None
            detail = str(exc)
        else:
            detail = "its identity, bytes, permissions, or size changed"
        if current == expected:
            continue
        stable = False
        key = manifest_key(manifest, filename)
        if key is not None and manifest.get(key) == expected[-1]:
            del manifest[key]
        print("REFUSED: not recording ownership of %s: %s after adoption "
              "validation. The current file is unchanged by this run." %
              (path, detail), file=sys.stderr)
    return stable


def seed_output_index(out_dir):
    """Hash existing figure PNGs for cross-run duplicate detection."""
    seen = {}
    paths = sorted(Path(out_dir).iterdir()) if os.path.isdir(out_dir) else []
    for path in paths:
        if (not path.is_file() or path.suffix.casefold() != ".png"
                or "_fig_" not in path.stem.casefold()):
            continue
        try:
            digest = _sha256(str(path))
        except OSError:
            continue
        seen.setdefault(digest, str(path))
    return seen


def find_pdfs(src_dir):
    """Return every PDF under `src_dir`, in stable order.

    `src_dir` may also be a single PDF file — "extract the figures from
    this one paper" is a normal request, and requiring the user to point at
    a folder either drags in every sibling PDF or forces them down to the
    lower-level scripts for no reason.

    Matches both `.pdf` and `.PDF` (and any other case variant), including on
    case-sensitive filesystems where `*.pdf` would miss `paper.PDF`.

    Sorted output makes runs reproducible — helpful when diffing the summary
    report between runs to see what changed. macOS-specific cruft like
    `.DS_Store` is skipped implicitly because we filter on the `.pdf`
    extension.
    """
    src = Path(src_dir)
    if src.is_file():
        if src.suffix.lower() != ".pdf":
            sys.exit(f"--src: {src} is a file but not a .pdf")
        return [src]
    if not src.is_dir():
        sys.exit(f"--src: {src} is not a directory or a PDF file")
    inventory = inventory_pdfs(src)
    if not inventory.complete:
        detail = "; ".join(
            "%s: %s" % (item.path, item.message)
            for item in inventory.findings if item.severity == "error")
        sys.exit("--src could not be inventoried completely: %s" %
                 (detail or src))
    usable = []
    invalid = []
    for entry in inventory.entries:
        path = Path(entry.path)
        # AppleDouble resource-fork sidecars are metadata, not source PDFs.
        # Treating ``._Paper.pdf`` as a paper creates a second, unorganized
        # source and can make a removable-volume sweep fail needlessly.
        if path.name.startswith("._"):
            continue
        if entry.kind == "regular":
            usable.append(path)
            continue
        if entry.kind == "symlink":
            try:
                target = os.stat(path)
            except OSError as exc:
                invalid.append("%s (dangling or unreadable symlink: %s)" %
                               (path, exc))
                continue
            if stat.S_ISREG(target.st_mode):
                usable.append(path)
                continue
        invalid.append("%s (%s)" % (path, entry.kind))
    if invalid:
        sys.exit("--src contains PDF-named non-regular occupant(s): %s" %
                 "; ".join(invalid))
    return sorted(usable)


def page_has_text(page):
    """Return True if the page has any extractable text.

    A common source of "this PDF produced zero figures" is a scanned PDF with
    no OCR layer — every page is an image and `get_text()` returns ''. We use
    this as a cheap upstream check so we can label such PDFs in the report
    instead of silently skipping them. Note that `get_text()` returns '' for
    blank pages too, so we accept a PDF as "has text" if *any* page has text.
    """
    return bool(page.get_text().strip())


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _foreign_occupant(manifest, out_path):
    """(why this file is not our own output — '' if it is, its digest or None).

    Cheap and local: one lookup, and a digest only when there is something to
    compare it against — which the caller then reuses for the duplicate check,
    so an ordinary re-run hashes each existing figure exactly once, as it
    always did. The manifest is the only positive evidence available: a PNG
    carries no provenance, and re-rendering the crop to compare would cost
    exactly what the "already exists" skip exists to save.
    """
    if os.path.islink(out_path):
        return "it is a symlink, not a recorded output file", None
    name = os.path.basename(out_path)
    try:
        key = manifest_key(manifest, name)
    except ValueError as exc:
        return "its ownership is ambiguous (%s)" % exc, None
    recorded = manifest.get(key)
    if recorded is None:
        return ("no record of writing it — another skill writes "
                "<slug>_fig_<N> into this same folder"), None
    try:
        digest = _sha256(out_path)
    except OSError as exc:
        return "its ownership cannot be verified (%s)" % exc, None
    if digest != recorded:
        return "its bytes have changed since this extractor wrote it", digest
    return "", digest


def _figure_slot_conflict(out_dir, stem, fig_suffix, out_path):
    """Return an occupied semantic figure slot, or ``None`` when it is free.

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
    exact = os.path.abspath(os.fspath(out_path))
    direct = set(inventory.candidates)
    conflicts = []
    for candidate in inventory.candidates + inventory.blocked_matches:
        basename = os.path.basename(candidate)
        candidate_stem, _extension = os.path.splitext(basename)
        if figure_identity(candidate_stem) != slot:
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


def _note_output(result, seen_hashes, out_path, fig_num, stem, manifest=None,
                 digest=None):
    """Record a figure's bytes and report a byte-identical twin, if any.

    Byte-identical output under a DIFFERENT stem is the same figure written
    twice under two names that never collide and never deduplicate.
    Whichever stem an entry cites, the other copy is unused forever AND
    unreportable — the unused-figure diagnostic is per-source, so it never
    looks at the other stem. Existing files are hashed too: the second copy
    is usually written on a later run than the first, so `seen_hashes` is
    seeded from the whole of `--out` before the run starts
    (`seed_output_index`). It used to start empty and be filled only from
    paths the current run touched, which made that sentence false for exactly
    the case it describes.

    Under the SAME stem it means something else — two captions whose crops
    came out identical, i.e. the detector could not tell the two figures
    apart (side-by-side panels with a caption each is the usual cause). Both
    are worth saying; they are not the same problem, so they are recorded
    with a flag and reported separately.
    """
    if digest is None:
        try:
            digest = _sha256(out_path)
        except OSError:
            return
    if manifest is not None:
        name = os.path.basename(out_path)
        manifest[manifest_key(manifest, name) or name] = digest
    first = seen_hashes.setdefault(digest, out_path)
    if os.path.basename(first) != os.path.basename(out_path):
        same_stem = os.path.basename(first).startswith(stem + "_fig")
        result["duplicates"].append((fig_num, first, same_stem))


def process_pdf(pdf_path, out_dir, overwrite=False, dpi=250, dry_run=False,
                reviewed=(), seen_hashes=None, manifest=None,
                chapter_pdfs=(), chapter_caption_cache=None,
                manifest_commit=None):
    """Detect and extract every figure in one PDF.

    Args:
        reviewed: {(pdf_stem, figure label)} the user has marked as checked;
            a flagged bbox in this set is reported as reviewed instead of
            being re-flagged forever.
        seen_hashes: {sha256: output path} shared across the whole run, so
            two source PDFs producing a byte-identical PNG under different
            stems is noticed instead of written silently. Pass the same dict
            to every call, seeded from `--out` by `seed_output_index`.
        manifest: {figure filename: sha256} this extractor wrote, from
            `load_manifest`. Read before an "already exists" skip, so a file
            another skill put at that name is reported rather than skipped;
            updated in place with every figure written.
        manifest_commit: optional zero-argument callback invoked immediately
            after each published crop is added to ``manifest``. The CLI uses
            it to persist ownership incrementally instead of leaving an entire
            batch unrecorded until process exit.
        chapter_pdfs: complete source/vault PDF inventory used only to prove
            cross-chapter references against an exact sibling caption.
        chapter_caption_cache: optional shared sibling-caption cache.

    Returns a dict summarizing what happened — used by the caller to build
    the run-end report. Keys:
        extracted:  int   — figures newly written to disk
        skipped:    int   — figures whose output already existed BEFORE this run
        collisions: list  — (label, label) pairs where two captions in this
                            same PDF normalized to the same filename. The
                            first caption is the one that "won" (was written);
                            the second is the one that got dropped. Common
                            when a paper uses both `Figure S1` AND
                            `Supplementary Figure 1` style — they collapse
                            into the same S-prefixed slot by design, but the
                            user should know it happened.
        warnings:   list  — (fig_label, reason) for suspicious bboxes
        reviewed:   list  — (fig_label, reason) for suspicious bboxes the
                            user has already marked as checked in the review
                            ledger. Counted, not nagged about.
        duplicates: list  — (fig_label, other path, same_stem) where this
                            PDF produced a PNG byte-identical to one already
                            written. A different stem usually means the same
                            document is in the source tree twice; the same
                            stem means two captions got the same crop.
        missing:    list  — figure labels the body text cites that no caption
                            matched. Non-empty means detection was PARTIAL —
                            the failure that otherwise looks exactly like a
                            complete run, since nothing downstream counts
                            figures independently.
        cross_chapter: list — labels confidently identified as references to a
                            different chapter of a split book. They stay
                            visible but do not make local detection PARTIAL.
        referenced: int   — distinct local figure labels the body text cites;
                            confidently classified cross-chapter labels are
                            counted in ``cross_chapter`` instead
        failures:   list  — (fig_label, reason) for figures that were
                            detected but could not be written (degenerate
                            crop rect, render error). Without this the
                            count in the summary silently disagrees with
                            what is on disk.
        ownership_failures: list — (fig_label, reason) for crops successfully
                            written whose ownership record could not be
                            persisted. The image exists, but automatic
                            overwrite is unsafe until the sidecar is repaired.
        blank:      list  — (fig_label, page) for crops that rendered nothing
                            but white. Its own bucket because it is its own
                            failure: the bbox was plausible, the render
                            worked, and the result is a picture of empty
                            page — the shape a caption whose figure sits on
                            the NEXT page produces.
        occupied:   list  — (fig_label, path, why) for output names already
                            held by a file this extractor did not write.
                            NOT a skip: `Sources/Images/` is shared, and a
                            skip here means the paper's figure is never
                            written while the report says the figure is
                            already there.
        caption_in: list  — (fig_label, reason) for crops that contain caption
                            text. A subset of `warnings` by mechanism, its own
                            bucket by meaning: it is the one thing this skill
                            promises its output never contains.
        had_text:   bool  — False if the PDF appears to be a pure scan
        open_error: str   — non-empty when the file could not be opened or
                            fully analyzed (truncated download, HTML saved
                            with a .pdf extension, damaged later page). Distinct from had_text:
                            this is not an OCR problem and `ocrmypdf` will
                            not help.
        no_pages:   bool  — True for a structurally valid PDF with zero
                            pages. Also not an OCR problem.
        figures:    list  — figure labels seen (for logging)
    """
    stem = pdf_path.stem
    reviewed = set(reviewed)
    if seen_hashes is None:
        seen_hashes = {}
    # `manifest is None` means "no ownership information was supplied", which
    # is NOT the same as an empty manifest: an empty one says nothing on disk
    # is ours, and every existing figure would be reported as another skill's.
    # Callers that have no manifest get the old unconditional skip.
    result = {
        "extracted": 0,
        "skipped": 0,
        "collisions": [],
        "warnings": [],
        "reviewed": [],
        "duplicates": [],
        "missing": [],
        "cross_chapter": [],
        "referenced": 0,
        "failures": [],
        "ownership_failures": [],
        "blank": [],
        "occupied": [],
        "caption_in": [],
        "had_text": False,
        "open_error": "",
        "no_pages": False,
        "figures": [],
    }

    try:
        doc = fitz.open(str(pdf_path))
    except Exception as e:
        result["open_error"] = str(e)
        print(f"  ERROR: could not open {pdf_path.name}: {e}", file=sys.stderr)
        return result

    # PyMuPDF opens HTML, XPS and EPUB natively, so a truncated download or a
    # saved error page named `.pdf` opens without raising and reads as a
    # perfectly good text-bearing document. Left unchecked it lands in the "no
    # figure captions detected" bucket, which tells the operator to go hunting
    # for an unusual caption style in a file that is not a PDF at all; the
    # open_error bucket is the one that says re-download it.
    if not doc.is_pdf:
        fmt = (doc.metadata or {}).get("format") or "an unknown format"
        result["open_error"] = (
            f"not a PDF — opened as {fmt} (an HTML error page or a truncated "
            f"download saved with a .pdf extension)"
        )
        doc.close()
        return result

    if len(doc) == 0:
        result["no_pages"] = True
        doc.close()
        return result

    # Cheap upstream check for OCR-less scans. If no page has any text, we
    # can't find captions, so just bail out with a clear flag in the report.
    # An encrypted PDF opens, reports `is_pdf` and a page count, and then
    # raises on the first page access -- which aborted the WHOLE run with a
    # traceback, no summary, and every remaining PDF unprocessed. It sorts
    # first alphabetically often enough that one such file loses the lot.
    if getattr(doc, "needs_pass", False) or getattr(doc, "is_encrypted", False):
        doc.close()
        result["open_error"] = ("encrypted and password-protected, so no page "
                                "can be read. Decrypt it first (`qpdf "
                                "--decrypt in.pdf out.pdf`), then re-run.")
        return result
    try:
        result["had_text"] = any(page_has_text(page) for page in doc)
    except Exception as exc:                  # a damaged page is not a crash
        doc.close()
        result["open_error"] = ("could not be read past the first page (%s). "
                                "It is damaged; re-download it."
                                % type(exc).__name__)
        return result
    if not result["had_text"]:
        doc.close()
        return result

    # Track which output paths we've written in THIS run. Distinguishes
    # within-PDF caption collisions (two distinct captions normalizing to
    # the same filename) from idempotent re-run skips (file existed before
    # we started). Maps out_path → the first caption label that claimed it.
    written_this_run = {}

    try:
        for page_idx, fig_num, raw_label, bbox, _cap_rect, reason in detect_figures(doc):
            fig_suffix = normalize_fig_num(fig_num)
            out_path = os.path.join(out_dir, f"{stem}_fig_{fig_suffix}.png")
            replace_digest = None
            result["figures"].append(fig_num)

            # Within-run collision: we already wrote this filename earlier in
            # the same PDF. Record the raw caption forms so the report tells
            # the user which captions actually collided (e.g., "Figure S1" vs
            # "Extended Data Figure 1") rather than just two copies of "S1".
            if out_path in written_this_run:
                result["collisions"].append((written_this_run[out_path], raw_label))
                continue

            def record_reason():
                # Only a caption that wins its output slot can have a crop to
                # review. Recording this before collision resolution made a
                # dropped duplicate count as a suspicious extraction and could
                # claim its overlapping caption was present in a PNG that this
                # run never writes.
                #
                # A bbox the executor has already checked stays counted but
                # stops being asked about — without this, a hand-fixed crop is
                # re-flagged on every run forever and the flag list becomes
                # noise nobody reads.
                if not reason:
                    return
                if (stem, fig_num) in reviewed or (stem, fig_suffix) in reviewed:
                    result["reviewed"].append((fig_num, reason))
                else:
                    result["warnings"].append((fig_num, reason))
                    if reason.startswith(CAPTION_IN_CROP_TAG):
                        result["caption_in"].append((fig_num, reason))

            slot_conflict = _figure_slot_conflict(
                out_dir, stem, fig_suffix, out_path)
            if slot_conflict is not None:
                occupied_path, why = slot_conflict
                result["occupied"].append((fig_num, occupied_path, why))
                written_this_run[out_path] = raw_label
                continue

            def publication_guard():
                late_conflict = _figure_slot_conflict(
                    out_dir, stem, fig_suffix, out_path)
                if late_conflict is None:
                    return
                occupied_path, why = late_conflict
                raise FileExistsError(errno.EEXIST, why, occupied_path)

            # Prior-run idempotent skip: file existed before this run started.
            existed = os.path.lexists(out_path)
            if existed:
                why, digest = (_foreign_occupant(manifest, out_path)
                               if manifest is not None else ("", None))
                if why:
                    # NOT a skip. `Sources/Images/` is shared with
                    # clipping-processor, and a file at this name that this
                    # extractor did not write means the paper's own figure has
                    # never been extracted — while `1 skipped (already exist)`
                    # says the opposite, in the words of an ordinary re-run.
                    result["occupied"].append((fig_num, out_path, why))
                    written_this_run[out_path] = raw_label
                    continue
                # This is the exact, verified output for this figure, so its
                # current detection remains reviewable even on an idempotent
                # skip. Preserve that established behavior.
                record_reason()
                if not overwrite:
                    written_this_run[out_path] = raw_label
                    result["skipped"] += 1
                    _note_output(result, seen_hashes, out_path, fig_num, stem,
                                 manifest, digest=digest)
                    continue
                if ((stem, fig_num) in reviewed
                        or (stem, fig_suffix) in reviewed):
                    # A review mark commonly follows an explicit-coordinate
                    # repair. A broad automatic --overwrite must not undo that
                    # checked crop; remove the ledger row first to opt back in.
                    written_this_run[out_path] = raw_label
                    result["skipped"] += 1
                    _note_output(result, seen_hashes, out_path, fig_num, stem,
                                 manifest, digest=digest)
                    continue
                # `manifest is None` preserves the programmatic API's legacy
                # overwrite behavior, but publication still needs an exact
                # byte snapshot to reject a different occupant that arrives
                # while the replacement crop is rendering.
                if digest is None:
                    try:
                        digest = _sha256(out_path)
                    except OSError as exc:
                        result["occupied"].append((
                            fig_num, out_path,
                            "its bytes cannot be snapshotted for overwrite (%s)" % exc,
                        ))
                        written_this_run[out_path] = raw_label
                        continue
                replace_digest = digest
            else:
                # The semantic slot and exact path are both free. This caption
                # can therefore produce a crop (or an honest geometry failure),
                # so its finding belongs in the review counts.
                record_reason()

            # An existing verified crop may be the explicit repair of this very
            # detection failure. Check that output first; rejecting the bbox first
            # made the documented repair remain "missing" on every later run.
            if degenerate(bbox):
                result["failures"].append(
                    (fig_num, f"degenerate bbox on page {page_idx + 1} — set an explicit crop")
                )
                continue

            if dry_run:
                result["extracted"] += 1
                written_this_run[out_path] = raw_label
                continue

            try:
                _rendered, _final, blank, publication = extract_one_figure(
                    doc, page_idx, bbox, out_path, dpi=dpi,
                    replace_digest=replace_digest,
                    publication_guard=publication_guard,
                    return_publication=True)
                if blank:
                    # Nothing was written (extract_one_figure leaves the temp
                    # file behind rather than moving a picture of empty page into
                    # the vault), so this is not an extraction.
                    result["blank"].append((fig_num, page_idx + 1))
                    continue
                result["extracted"] += 1
                written_this_run[out_path] = raw_label
                # Record the bytes this guarded publication installed. The
                # public pathname can be replaced by another writer before the
                # sidecar update; re-hashing it here would forge ownership of
                # that writer's bytes and authorize a destructive overwrite.
                _note_output(result, seen_hashes, out_path, fig_num, stem,
                             manifest, digest=publication[1])
                if manifest_commit is not None:
                    try:
                        manifest_commit()
                    except Exception as exc:
                        result["ownership_failures"].append((
                            fig_num,
                            "crop was published but its ownership record could "
                            "not be persisted immediately: %s" % exc,
                        ))
                        print(
                            f"  ERROR: ownership save failed after publishing "
                            f"{stem} fig {fig_num}: {exc}. Stopping before any "
                            f"more crops are written.",
                            file=sys.stderr,
                        )
                        break
            except atomic_move.LinkUnavailable as e:
                retained = getattr(e, "staging_path", None)
                recovery = getattr(e, "recovery_path", None)
                locations = []
                if retained:
                    locations.append("staged crop preserved at %s" % retained)
                if recovery and recovery != retained:
                    locations.append("additional recovery state at %s" % recovery)
                location_note = ("; " + "; ".join(locations)) if locations else ""
                result["failures"].append((
                    fig_num,
                    f"safe publication is unavailable on page "
                    f"{page_idx + 1}: {e}{location_note}",
                ))
                print(
                    f"  ERROR: could not safely publish {stem} fig {fig_num} "
                    f"(page {page_idx+1}): {e}{location_note}",
                    file=sys.stderr,
                )
            except FileExistsError as e:
                # The name was safe at this figure's preflight, then changed
                # before publication. This is an occupied slot, not a render
                # failure and never permission to replace what arrived late.
                retained = getattr(e, "staging_path", None)
                recovery = getattr(e, "recovery_path", None)
                locations = []
                if retained:
                    locations.append("staged crop preserved at %s" % retained)
                if recovery and recovery != retained:
                    locations.append("additional recovery state at %s" % recovery)
                location_note = ("; " + "; ".join(locations)) if locations else ""
                result["occupied"].append(
                    (fig_num, out_path, "%s%s" % (e, location_note)))
                written_this_run[out_path] = raw_label
                print(
                    f"  ERROR: refused to publish {stem} fig {fig_num} "
                    f"(page {page_idx+1}): {e}{location_note}",
                    file=sys.stderr,
                )
            except Exception as e:
                retained = getattr(e, "staging_path", None)
                recovery = getattr(e, "recovery_path", None)
                locations = []
                if retained:
                    locations.append("staged crop preserved at %s" % retained)
                if recovery and recovery != retained:
                    locations.append("additional recovery state at %s" % recovery)
                location_note = ("; " + "; ".join(locations)) if locations else ""
                result["failures"].append(
                    (fig_num,
                     f"render failed on page {page_idx + 1}: {e}{location_note}")
                )
                print(
                    f"  ERROR: failed to extract {stem} fig {fig_num} "
                    f"(page {page_idx+1}): {e}{location_note}",
                    file=sys.stderr,
                )

        # Partial detection. Nothing else in the pipeline can see it: the summary
        # counts PDFs with ZERO captions, and downstream the figure glob and the
        # unused-figure diagnostic both walk whatever files exist — so 3 of 4
        # figures looks exactly like 4 of 4 everywhere.
        referenced, missing = caption_coverage(doc, result["figures"])
        missing, cross_chapter = partition_cross_chapter_references(
            pdf_path, result["figures"], missing, chapter_pdfs,
            chapter_caption_cache)
        result["referenced"] = len(referenced) - len(cross_chapter)
        result["missing"] = missing
        result["cross_chapter"] = cross_chapter

    except Exception as exc:
        result["open_error"] = (
            f"PDF analysis failed after {len(result['figures'])} detected figure(s) "
            f"({type(exc).__name__}: {exc}). Inspect the damaged page or PDF "
            f"before relying on this source's figure set."
        )
        print(f"  ERROR: {pdf_path.name}: {result['open_error']}", file=sys.stderr)
    finally:
        doc.close()
    return result


def mark_reviewed_command(src_dir, out_dir, stem, fig, *, ed_prefix="S",
                          keep_frame=False, include_split_books=False,
                          allow_unorganized=False, review_file=None, dpi=250):
    """Record a review with the original source and extraction context.

    The current Python interpreter and an absolute script path, for the same reason
    `auto_fig_bbox.py --emit extract` uses them: this text is pasted into a
    shell sitting in the vault, where macOS has no `python` binary at all and
    a bare script name resolves to nothing.

    This is a normal extraction run after recording the mark, so preserve the
    label namespace, ledger, geometry and source-eligibility choices. Never
    carry --overwrite: the crop may just have been repaired explicitly.
    """
    def bound_path(path):
        # Bind relative paths before this command is pasted into another cwd.
        # Do not resolve symlinks: a selected PDF's basename is its figure key.
        path = os.path.expanduser(str(path))
        return path if os.path.isabs(path) else os.path.join(os.getcwd(), path)

    argv = [sys.executable, os.path.abspath(__file__),
            "--src", bound_path(src_dir), "--out", bound_path(out_dir)]
    if ed_prefix != "S":
        argv += ["--ed-prefix", ed_prefix]
    if dpi != 250:
        argv += ["--dpi", str(dpi)]
    if review_file is not None:
        argv += ["--review-file", bound_path(review_file)]
    for flag, enabled in (("--keep-frame", keep_frame),
                          ("--include-split-books", include_split_books),
                          ("--allow-unorganized", allow_unorganized)):
        if enabled:
            argv.append(flag)
    argv += ["--mark-reviewed", f"{stem}:{fig}"]
    return " ".join(shlex.quote(arg) for arg in argv)


def print_summary(per_pdf, out_dir, skipped_books=None, review_file=None,
                  dry_run=False, src_dir="", *, ed_prefix="S", keep_frame=False,
                  include_split_books=False, allow_unorganized=False, dpi=250):
    """Print a human-readable summary of the batch run.

    Sections, in order: header, counts, figures that failed to write, crops
    written whose ownership record failed to persist, collisions (two
    captions in the same PDF mapping to the same filename),
    warnings (suspicious bboxes needing visual review), PARTIAL detection
    (figure numbers the text cites with no caption found), byte-identical
    duplicates, split books whose figures came from the chapters, zero-yield
    PDFs (likely scans or PDFs without "Figure" captions), and stem-collision
    warnings (two different source PDFs producing the same filename stem).
    """
    total_extracted = sum(r["extracted"] for r in per_pdf.values())
    total_skipped = sum(r["skipped"] for r in per_pdf.values())
    total_warnings = sum(len(r["warnings"]) for r in per_pdf.values())
    total_reviewed = sum(len(r["reviewed"]) for r in per_pdf.values())
    total_collisions = sum(len(r["collisions"]) for r in per_pdf.values())
    total_failures = sum(len(r["failures"]) for r in per_pdf.values())
    total_ownership_failures = sum(
        len(r.get("ownership_failures", ())) for r in per_pdf.values())
    total_dupes = sum(len(r["duplicates"]) for r in per_pdf.values())
    total_blank = sum(len(r.get("blank", ())) for r in per_pdf.values())
    total_occupied = sum(len(r.get("occupied", ())) for r in per_pdf.values())
    total_caption_in = sum(len(r.get("caption_in", ())) for r in per_pdf.values())
    total_cross_chapter = sum(
        len(r.get("cross_chapter", ())) for r in per_pdf.values())
    n_partial = sum(1 for r in per_pdf.values() if r["missing"] and r["figures"])
    skipped_books = skipped_books or {}
    n_pdfs = len(per_pdf)
    n_zero = sum(
        1 for r in per_pdf.values()
        if r["had_text"] and not r["figures"] and not r["open_error"]
    )
    # The three "produced nothing" buckets are kept apart on purpose: only
    # one of them is an OCR problem, and telling a user to run `ocrmypdf`
    # on a truncated download or an empty PDF sends them down a dead end.
    n_unreadable = sum(1 for r in per_pdf.values() if r["open_error"])
    n_no_pages = sum(1 for r in per_pdf.values() if r["no_pages"])
    n_no_text = sum(
        1 for r in per_pdf.values()
        if not r["had_text"] and not r["open_error"] and not r["no_pages"]
    )

    print()
    print("=" * 72)
    destination = "preview for" if dry_run else "wrote to"
    print(f"Summary: {n_pdfs} PDF(s) scanned, {destination} {out_dir}")
    print("=" * 72)
    label = "Figures to attempt" if dry_run else "Figures extracted"
    print(f"  {label}:    {total_extracted}")
    print(f"  Already existed:      {total_skipped} (skipped — pass --overwrite to redo)")
    print(f"  Caption collisions:   {total_collisions} (two captions → same filename)")
    print(f"  Suspicious bboxes:    {total_warnings} (inspect these visually)")
    if total_reviewed:
        print(f"  ...already reviewed:  {total_reviewed} (flagged, but marked "
              f"checked in {review_file or REVIEW_FILE})")
    if dry_run:
        # The duplicate check hashes PNGs on disk, and a dry run writes none.
        # Printing a bare `0` there reads as "checked, none found" — the one
        # thing it cannot mean — for the bucket whose whole purpose is to
        # surface a loss nothing else in the pipeline can see.
        print(f"  Duplicate figures:    {total_dupes} among the figures that "
              f"already exist (a dry run writes no bytes, so the ones it "
              f"would write are not compared)")
    else:
        print(f"  Duplicate figures:    {total_dupes} (byte-identical to a figure already written)")
    print(f"  Failed to write:      {total_failures} (detected but not extracted)")
    print(f"  Ownership save failed: {total_ownership_failures} (crop written; automatic overwrite unsafe)")
    print(f"  Blank crops:          {total_blank} (rendered nothing but white — not written)")
    print(f"  Caption text in crop: {total_caption_in} (the crop overlaps a caption)")
    print(f"  Occupied filenames:   {total_occupied} (a file this extractor did not write is in the way)")
    print(f"  PDFs with PARTIAL detection:      {n_partial} (text cites figures no caption matched)")
    if total_cross_chapter:
        print(f"  Cross-chapter references:         {total_cross_chapter} "
              "(reported separately; not local misses)")
    if skipped_books:
        print(f"  Split books skipped:              {len(skipped_books)} "
              f"(figures come from the chapter PDFs)")
    print(f"  PDFs with no figures detected:    {n_zero}")
    print(f"  PDFs with no extractable text:    {n_no_text} (likely scans — needs OCR)")
    print(f"  PDFs that could not be fully read:{n_unreadable} (not a readable PDF)")
    print(f"  PDFs with zero pages:             {n_no_pages}")
    print()

    if total_failures:
        print("Figures detected but NOT written (these are missing from Sources/Images/):")
        for pdf_path, r in per_pdf.items():
            for fig_num, reason in r["failures"]:
                print(f"  {pdf_path.name}  Fig {fig_num}  ({reason})")
        print()

    if total_ownership_failures:
        print("Crops written but ownership records NOT persisted (the images exist):")
        for pdf_path, r in per_pdf.items():
            for fig_num, reason in r.get("ownership_failures", ()):
                print(f"  {pdf_path.name}  Fig {fig_num}  ({reason})")
        print("  Preserve these crops and repair the ownership sidecar before any")
        print("  automatic overwrite. Do not re-extract them as if the PNGs were missing.")
        print()

    if total_blank:
        print("Blank crops — the rect rendered nothing but white, so NOTHING was written:")
        for pdf_path, r in per_pdf.items():
            for fig_num, page_no in r.get("blank", ()):
                print(f"  {pdf_path.name}  Fig {fig_num}  (page {page_no})")
        print("  The crop is over empty page. The usual cause is a caption at the foot of")
        print("  a page whose figure is overleaf: the search region above it holds no")
        print("  content, and the fallback rect covers the gap. Render that page and the")
        print("  next one (scripts/render_page.py) and set an explicit crop on whichever")
        print("  page the figure is actually on.")
        # One PDF where EVERY figure came out blank is not N independent
        # blank crops — it is one detection failure with N symptoms, and it
        # reads as an empty run unless the report says so. This is the shape
        # a layout the detector reads wrongly produces once the blank guard
        # stops the white PNGs from being written.
        for pdf_path, r in per_pdf.items():
            blanks = r.get("blank", ())
            if (blanks and not r["extracted"] and not r["skipped"]
                    and len(blanks) == len(set(r["figures"]))):
                print(f"  ALL {len(blanks)} figure(s) detected in {pdf_path.name} came out "
                      f"blank, and none were written.")
                print( "  That is one detection failure for the whole PDF, not "
                       "N independent blank crops:")
                print( "  the crops are landing off the figures entirely. Check its layout "
                       "before")
                print( "  cropping figure by figure — this PDF produced no images at all.")
        print()

    if total_caption_in:
        print("Caption text inside the crop — the one thing this skill promises it excludes:")
        for pdf_path, r in per_pdf.items():
            for fig_num, reason in r.get("caption_in", ()):
                print(f"  {pdf_path.name}  Fig {fig_num}  ({reason})")
        print("  The crop was built from the wrong part of the page — the neighbouring")
        print("  column of a two-column layout and a rotated page are the two shapes that")
        print("  produce it. The PNG is on disk and carries somebody's caption; re-crop it")
        print("  explicitly (see *Set and verify an explicit crop*) before anything embeds it.")
        print()

    if total_occupied:
        print("Output names already held by a file this extractor did not write:")
        for pdf_path, r in per_pdf.items():
            for fig_num, path, why in r.get("occupied", ()):
                print(f"  {pdf_path.name}  Fig {fig_num}  → {path}  ({why})")
        print("  These figures were NOT extracted and NOT skipped: Sources/Images/ is shared,")
        print("  and clipping-processor writes <slug>_fig_<N> there too, so a clipping whose")
        print("  slug equals this PDF's stem owns the name. Left as a skip, the PDF's real")
        print("  figure is never written and every consumer embeds the other file as it.")
        print("  Inspect each one. If it belongs to the clipping, route its note-and-image")
        print("  rename through clipping-processor; if the PDF identity must change, route it")
        print("  through pdf-organizer. If it is this extractor's own from an")
        print("  older run, inspect it and reconcile that exact ownership record first.")
        print("  --overwrite replaces verified own output only; it never claims a foreign file.")
        print()

    if total_collisions:
        print("Caption collisions (later caption dropped — typically multiple supplementary styles in one PDF):")
        for pdf_path, r in per_pdf.items():
            for kept, dropped in r["collisions"]:
                print(f"  {pdf_path.name}  kept '{kept}', dropped '{dropped}' (both normalized to the same filename)")
        print()

    if total_warnings:
        print("Suspicious bboxes (likely auto-detect failure — render, inspect, and set an explicit crop):")
        for pdf_path, r in per_pdf.items():
            for fig_num, reason in r["warnings"]:
                print(f"  {pdf_path.name}  Fig {fig_num}  ({reason})")
        # The example has to come from a PDF that actually carries a flag.
        # Keying it to the first PDF *processed* printed the header with
        # nothing under it whenever that PDF came back clean — the usual case
        # in a batch — so the one line that tells the user how to stop the
        # nagging was the line they never saw.
        example = next(((p, r["warnings"][0][0])
                        for p, r in per_pdf.items() if r["warnings"]), None)
        if example:
            print("  Once you have checked one (and fixed the crop if it needed it), record it:")
            # The whole command, not just the flag. It used to print the
            # `--mark-reviewed '<stem>':'<fig>'` fragment alone while the skill
            # documented it as "the exact command" — leaving the reader to
            # reconstruct the interpreter, the script's path and the two
            # required arguments from somewhere else. `auto_fig_bbox.py --emit
            # extract` has always emitted a runnable line; this is the same
            # rule. `shlex.quote` because these are the user's paths.
            print("    " + mark_reviewed_command(src_dir, out_dir,
                                                 example[0].stem, example[1],
                                                 ed_prefix=ed_prefix, keep_frame=keep_frame,
                                                 include_split_books=include_split_books,
                                                 allow_unorganized=allow_unorganized,
                                                 review_file=review_file, dpi=dpi))
        print()



    if total_cross_chapter:
        print("Cross-chapter figure references — visible, but not missing local captions:")
        for pdf_path, r in per_pdf.items():
            labels = r.get("cross_chapter", ())
            if labels:
                print(f"  {pdf_path.name}: "
                      + ", ".join(f"Fig {label}" for label in labels))
        print("  The split-chapter filename and every detected numeric caption agree on")
        print("  this chapter's local prefix, and one canonical same-book sibling contains")
        print("  the exact cited caption. Ambiguous, unreadable, or changing siblings remain PARTIAL.")
        print()

    if n_partial:
        print("PARTIAL detection — the body text cites figure numbers no caption matched.")
        print("Nothing downstream can see this: the figure glob and the unused-figure")
        print("diagnostic both walk the files that exist, so 3-of-4 looks like 4-of-4.")
        for pdf_path, r in per_pdf.items():
            if r["missing"] and r["figures"]:
                got = len(set(r["figures"]))
                print(f"  {pdf_path.name}  {got} caption(s) found, "
                      f"{r['referenced']} cited; no caption for: "
                      + ", ".join(f"Fig {m}" for m in r["missing"][:12]))
        print("  Inspect those pages visually (scripts/render_page.py). Three things produce")
        print("  it: a caption clipped away by the page-margin bounds (a caption low in the")
        print("  text area of a tall page, which is where an A4 journal style puts one), a")
        print("  caption style the regex misses, or a figure that lives in another document.")
        print()

    cross = [(p, f, o) for p, r in per_pdf.items()
             for f, o, same in r["duplicates"] if not same]
    within = [(p, f, o) for p, r in per_pdf.items()
              for f, o, same in r["duplicates"] if same]
    if cross:
        print("Byte-identical figures written under two different stems:")
        for pdf_path, fig_num, other in cross:
            print(f"  {pdf_path.name}  Fig {fig_num}  is identical to {other}")
        print("  The same document may be in the source tree twice. Whichever stem an entry")
        print("  cites, the other copy is unused and the per-source unused-figure check")
        print("  cannot report it. Inspect both sources, choose the canonical identity, and")
        print("  resolve the duplicate only with authorization for that destructive change.")
        print()
    if within:
        print("Byte-identical figures under the SAME stem (two captions, one crop):")
        for pdf_path, fig_num, other in within:
            print(f"  {pdf_path.name}  Fig {fig_num}  is identical to {other}")
        print("  The detector could not separate these figures — side-by-side panels with")
        print("  a caption each is the usual cause. Set explicit crops (see the skill's")
        print("  *Set and verify an explicit crop*), then --mark-reviewed them.")
        print()

    if skipped_books:
        print("Split books — figures were extracted from the chapters, not the book:")
        for book, chapters in sorted(skipped_books.items()):
            print(f"  {book.name}  ({len(chapters)} chapter PDF(s))")
            stale = sorted(
                f for f in (os.listdir(out_dir) if os.path.isdir(out_dir) else [])
                if f.startswith(book.stem + "_fig")
            )
            if stale:
                print(f"    NOTE: {len(stale)} figure(s) under the BOOK's stem are still "
                      f"in {out_dir}")
                print(f"    from a run before this rule existed — duplicates of the "
                      f"chapter figures.")
                print(f"    They are unused and unreportable. After verifying their origin,")
                print(f"    either keep the book with --include-split-books or remove exactly")
                print(f"    {book.stem}_fig* only when that cleanup is authorized.")
        print()

    if n_zero:
        print("PDFs with extractable text but no figure captions detected:")
        for pdf_path, r in per_pdf.items():
            if r["had_text"] and not r["figures"] and not r["open_error"]:
                print(f"  {pdf_path.name}")
        print()

    if n_no_text:
        print("PDFs with no extractable text (scanned — OCR with `ocrmypdf` first):")
        for pdf_path, r in per_pdf.items():
            if not r["had_text"] and not r["open_error"] and not r["no_pages"]:
                print(f"  {pdf_path.name}")
        print()

    if n_unreadable:
        print("PDFs that could not be opened or fully read (NOT an OCR problem — not a readable PDF):")
        for pdf_path, r in per_pdf.items():
            if r["open_error"]:
                print(f"  {pdf_path.name}  ({r['open_error']})")
        print()

    if n_no_pages:
        print("PDFs with zero pages (nothing to scan):")
        for pdf_path, r in per_pdf.items():
            if r["no_pages"]:
                print(f"  {pdf_path.name}")
        print()

    # Stem collisions: two source PDFs with the same portable base-name identity
    # would write to one figure namespace. Folding makes the refusal consistent
    # across filesystems that alias case variants and ones that can store both.
    stems = defaultdict(list)
    for pdf_path in per_pdf:
        stems[pdf_path.stem.casefold()].append(pdf_path)
    stem_collisions = {paths[0].stem: paths for paths in stems.values()
                       if len(paths) > 1}
    if stem_collisions:
        print("WARNING: filename stem collisions (these PDFs are refused):")
        for stem, paths in stem_collisions.items():
            print(f"  stem '{stem}':")
            for p in paths:
                print(f"    {p}")
        print()


def positive_int(value):
    """An argparse integer strictly above zero."""
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise argparse.ArgumentTypeError("must be an integer")
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


# ---------------------------------------------------------------------------
# self-test
# ---------------------------------------------------------------------------
#
# `python3 batch_extract.py --test`.
#
# Every fixture is built inside a function — `tests/test_conventions.py`'s
# `check_scripts_run` imports this module and fails it for anything computed at
# module scope. Nothing is written outside a `tempfile` directory, which is
# removed again; no vault path is touched and nothing is fetched.
#
# The buckets are the point. This script's whole contract with the user is that
# a PDF which produced no figures lands in the RIGHT bucket — an OCR-less scan,
# an encrypted file, a download that is not a PDF, and a PDF with no captions
# are four different instructions to the reader, and three of them are ruined
# by being told to run `ocrmypdf`.


def _st_fig_pdf(path, captions=("Figure 1. Synthetic.",), fill=(0.2, 0.3, 0.7)):
    """One page per caption, each with a drawn figure above it."""
    doc = fitz.open()
    for cap in captions:
        page = doc.new_page(width=612, height=792)
        page.draw_rect(fitz.Rect(100, 200, 500, 400), fill=fill)
        page.insert_text((100, 430), cap, fontsize=9)
    doc.save(str(path))
    doc.close()
    return Path(path)




def _st_scan_pdf(path):
    """A page with marks and no extractable text: an un-OCRed scan."""
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.draw_rect(fitz.Rect(50, 50, 500, 700), fill=(0.55, 0.55, 0.55))
    doc.save(str(path))
    doc.close()
    return Path(path)


def _st_html_pdf(path):
    """An HTML error page saved with a `.pdf` extension.

    PyMuPDF opens it natively, so it reads as a perfectly good text-bearing
    document — the failure mode the `is_pdf` bucket exists for.
    """
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("<html><body><h1>404 Not Found</h1>"
                 "<p>The document you requested is gone.</p></body></html>")
    return Path(path)


def _st_zero_page_pdf(path):
    """A structurally valid PDF with no pages (PyMuPDF refuses to save one)."""
    with open(path, "wb") as fh:
        fh.write(b"%PDF-1.4\n"
                 b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
                 b"2 0 obj\n<< /Type /Pages /Kids [] /Count 0 >>\nendobj\n"
                 b"trailer\n<< /Root 1 0 R /Size 3 >>\n%%EOF\n")
    return Path(path)


def _st_encrypted_pdf(path):
    """A password-protected PDF: opens, reports pages, raises on page access."""
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((100, 200), "Figure 1. Locked away.", fontsize=9)
    doc.save(str(path), encryption=fitz.PDF_ENCRYPT_AES_256,
             owner_pw="ownerpw", user_pw="userpw")
    doc.close()
    return Path(path)


def _st_tiny_fig_pdf(path, caption="Figure 1. Tiny."):
    """A figure small enough that the bbox is flagged as suspicious."""
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.draw_rect(fitz.Rect(100, 200, 130, 230), fill=(0, 0, 0))
    page.insert_text((100, 260), caption, fontsize=9)
    doc.save(str(path))
    doc.close()
    return Path(path)


def _st_next_page_figure_pdf(path):
    """A caption at the FOOT of a page whose figure is on the next one.

    The normal shape for a figure that would not fit: prose fills the page,
    the caption sits under it, and the figure itself is overleaf. The search
    region above the caption holds no content at all, so `auto_fig_bbox`'s
    raster-only fallback synthesises a rect over the empty gap — plausibly
    sized, no region to compare it against, no running head in it, less prose
    than the crop is wide — and every check passes. The result was a
    pure-white PNG reported as `1 extracted, 0 suspicious, 0 failed`.
    """
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    for k in range(9):
        page.insert_text((72, 100 + 13 * k),
                         "Body prose line %d of the running text here." % k,
                         fontsize=10)
    page.insert_text((72, 700),
                     "Figure 4. A caption whose figure is overleaf.",
                     fontsize=9)
    page2 = doc.new_page(width=612, height=792)
    page2.draw_rect(fitz.Rect(100, 100, 500, 400), fill=(0.3, 0.5, 0.2))
    doc.save(str(path))
    doc.close()
    return Path(path)


def _st_two_column_pdf(path):
    """Two figures side by side, their captions a few points apart in height.

    An ordinary two-column page. The left figure's crop runs the width of the
    page down to its own caption, so it reaches over the bottom of the right
    column's caption, which starts six points higher. The caption text is in
    the PNG — the one thing this skill promises its output never contains —
    and every bucket in the report read zero, because the only caption-overlap
    check in the plugin was in `extract_figures.main()`, which this script
    bypasses by calling `extract_one_figure()` directly.
    """
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.draw_rect(fitz.Rect(70, 200, 290, 400), fill=(0.2, 0.4, 0.8))
    page.draw_rect(fitz.Rect(320, 200, 550, 380), fill=(0.8, 0.3, 0.2))
    page.insert_text((317, 424),
                     "Figure 2. The right column caption, a line higher.",
                     fontsize=8)
    page.insert_text((60, 430), "Figure 1. The left column caption.",
                     fontsize=8)
    doc.save(str(path))
    doc.close()
    return Path(path)


def _st_top_caption_pdf(path):
    """A caption at the very top of a page: the search region collapses.

    The figure it belongs to is on the previous page, so there is nothing
    above the caption to crop and the rect comes out inverted — the
    `degenerate bbox` failure, which must be reported rather than written.
    """
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((100, 58), "Figure 3. Continued from the previous page.",
                     fontsize=9)
    page.insert_text((100, 400), "Body prose lower down the page.", fontsize=9)
    doc.save(str(path))
    doc.close()
    return Path(path)


def run_self_test():
    """Run the built-in cases; print `N/M self-test cases pass`, return 0/1."""
    import contextlib
    import io
    import shutil
    import subprocess
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

    class NarrowConsole:
        def __init__(self):
            self.calls = []

        def reconfigure(self, **kwargs):
            self.calls.append(kwargs)

    narrow_out, narrow_err = NarrowConsole(), NarrowConsole()
    with mock.patch.object(sys, "stdout", narrow_out), \
            mock.patch.object(sys, "stderr", narrow_err):
        _configure_stdio()
    check("narrow stdout is switched to UTF-8", narrow_out.calls,
          [{"encoding": "utf-8", "errors": "backslashreplace"}])
    check("narrow stderr is switched to UTF-8", narrow_err.calls,
          [{"encoding": "utf-8", "errors": "backslashreplace"}])

    tmp = tempfile.mkdtemp(prefix="batch-extract-selftest-")
    try:
        # --- the review ledger, both directions ---------------------------
        # `mark_reviewed` writes it and `load_reviewed` reads it. They are the
        # two ends of one file and nothing else compares them.
        ledger = os.path.join(tmp, "ledger", REVIEW_FILE)
        check("mark_reviewed parses STEM:FIG",
              mark_reviewed(ledger, ["Prince_UDL_2026_02_SupLearn:10-5"]),
              [("Prince_UDL_2026_02_SupLearn", "10-5")])
        check("load_reviewed reads it back",
              load_reviewed(ledger), {("Prince_UDL_2026_02_SupLearn", "10-5")})
        with open(ledger, encoding="utf-8") as fh:
            body = fh.read()
        ok("a fresh ledger explains itself", body.startswith(REVIEW_HEADER))
        ok("the entry is TAB-separated, as the header says",
           "Prince_UDL_2026_02_SupLearn\t10-5\n" in body)

        # The label is split off at the LAST colon, so a stem containing one
        # survives the round trip. `mark_reviewed` always got this right;
        # `load_reviewed` split on every colon and handed back ("A", "B") --
        # a mark that matches no figure, so the bbox the user just checked is
        # flagged again on the next run and the ledger looks like it worked.
        check("mark_reviewed on a stem containing a colon",
              mark_reviewed(ledger, ["Notes:2025_Draft:S1"]),
              [("Notes:2025_Draft", "S1")])
        check("load_reviewed on a stem containing a colon",
              ("Notes:2025_Draft", "S1") in load_reviewed(ledger), True)
        check("the ledger still holds the first entry",
              ("Prince_UDL_2026_02_SupLearn", "10-5") in load_reviewed(ledger),
              True)

        # `mark_reviewed` must carry the snapshot it parsed into publication.
        # Taking a fresh snapshot only inside write_review would silently fold
        # this run's stale body over another process's newly appended mark.
        before_concurrent_mark = open(ledger, encoding="utf-8").read()
        concurrent_row = "Concurrent_Paper_2025\t9\n"
        real_write_review = write_review

        def inject_review_update(path, text, expected=None):
            with open(path, "a", encoding="utf-8", newline="") as fh:
                fh.write(concurrent_row)
            return real_write_review(path, text, expected=expected)

        refused = False
        with mock.patch.dict(globals(), {"write_review": inject_review_update}):
            try:
                mark_reviewed(ledger, ["Doe_Late_2025:1"])
            except OSError:
                refused = True
        check("a concurrent review-ledger update is refused", refused, True)
        check("the concurrent review mark is preserved without the stale append",
              open(ledger, encoding="utf-8").read(),
              before_concurrent_mark + concurrent_row)

        # A hand-written `STEM:FIG` line is read the same way as the flag.
        hand = os.path.join(tmp, "hand-ledger.txt")
        with open(hand, "w", encoding="utf-8") as fh:
            fh.write("# a comment\n\n"
                     "Doe_Figs_2025:1\n"
                     "Notes:2025_Draft:S2\n"
                     "Doe_Figs_2025\tS3\tchecked by hand\n")
        check("a hand-written ledger", load_reviewed(hand),
              {("Doe_Figs_2025", "1"), ("Notes:2025_Draft", "S2"),
               ("Doe_Figs_2025", "S3")})
        check("a ledger that does not exist is empty, not an error",
              load_reviewed(os.path.join(tmp, "nope.txt")), set())
        with open(hand, "w", encoding="utf-8") as fh:
            fh.write("# retain this note\nDoe_Figs_2025\t1")
        mark_reviewed(hand, ["Doe_Figs_2025:2"])
        check("appending after an unterminated last line preserves both marks",
              load_reviewed(hand), {("Doe_Figs_2025", "1"), ("Doe_Figs_2025", "2")})

        for bad_entry in ("no-colon-at-all", ":1", "stem:", "  :  "):
            state["n"] += 1
            try:
                mark_reviewed(os.path.join(tmp, "unused.txt"), [bad_entry])
                state["bad"] += 1
                print("FAIL mark_reviewed accepted %r" % bad_entry)
            except SystemExit:
                pass
        ok("a refused entry wrote no ledger",
           not os.path.exists(os.path.join(tmp, "unused.txt")))

        # `--dry-run` validates and writes nothing -- not the ledger, and not
        # the `--out` directory `os.makedirs` would otherwise create.
        dry_ledger = os.path.join(tmp, "dry", REVIEW_FILE)
        check("mark_reviewed --dry-run still parses",
              mark_reviewed(dry_ledger, ["Doe_Figs_2025:2"], dry_run=True),
              [("Doe_Figs_2025", "2")])
        ok("mark_reviewed --dry-run wrote no ledger",
           not os.path.exists(dry_ledger))
        ok("mark_reviewed --dry-run created no directory",
           not os.path.isdir(os.path.join(tmp, "dry")))

        # --- split books ---------------------------------------------------
        def paths(*names):
            return [Path(os.path.join(tmp, n)) for n in names]

        book, ch1, ch2 = paths("Prince_UDL_2026.pdf",
                               "Prince_UDL_2026_01_Intro.pdf",
                               "Prince_UDL_2026_02_SupLearn.pdf")
        check("a book with its chapters in the run",
              split_book_chapters([book, ch1, ch2]), {book: [ch1, ch2]})
        check("a book alone is not skipped",
              split_book_chapters([book]), {})
        check("chapters alone pair with nothing",
              split_book_chapters([ch1, ch2]), {})
        # `_src` sits on either side independently, which is why both are
        # compared on the CORE stem.
        srcbook, = paths("Prince_UDL_2026_src.pdf")
        check("a `_src` book pairs with plain chapters",
              split_book_chapters([srcbook, ch1]), {srcbook: [ch1]})
        srcch, = paths("Prince_UDL_2026_01_Intro_src.pdf")
        check("a plain book pairs with `_src` chapters",
              split_book_chapters([book, srcch]), {book: [srcch]})
        # The legacy mid-`_src` chapter spelling: recognised as a chapter even
        # though `looks_canonical` rejects it, so the book is still skipped
        # while a vault's names are being fixed.
        legacy, = paths("Prince_UDL_2026_src_01_Intro.pdf")
        check("the legacy `<book>_src_NN_Name` chapter still pairs",
              split_book_chapters([book, legacy]), {book: [legacy]})
        # BOTH spellings of one split book in the walk: each is a book of the
        # same chapters, and each must be skipped — keeping one representative
        # extracted the twin whole and wrote every figure a second time.
        check("a plain book AND its `_src` twin are both skipped",
              split_book_chapters([book, srcbook, ch1]),
              {book: [ch1], srcbook: [ch1]})
        check("a skipped whole book is not eligible for a review mark",
              reviewable_stems([book, ch1]), {ch1.stem})
        check("an explicitly included whole book becomes reviewable",
              reviewable_stems([book, ch1], include_split_books=True),
              {book.stem, ch1.stem})
        # A `_2` disambiguator names a DIFFERENT document, so it pairs with
        # nothing -- pdf-organizer refuses to split one at all.
        dis, = paths("Prince_UDL_2026_2.pdf")
        check("a `_2` book is not the book of these chapters",
              split_book_chapters([dis, ch1]), {})
        upper, lower = paths("Kuhn_X_2012.pdf", "kuhn_x_2012_01_A.pdf")
        check("stems pair under the portable case-insensitive identity",
              split_book_chapters([upper, lower]), {upper: [lower]})
        unorganized_source, = paths("download (1).pdf")
        check("an unorganized source needs its explicit review override",
              reviewable_stems([unorganized_source]), set())
        check("the review override makes that source eligible",
              reviewable_stems([unorganized_source], allow_unorganized=True),
              {unorganized_source.stem})
        same_a = Path(tmp) / "A" / "Doe_Same_2025.pdf"
        same_b = Path(tmp) / "B" / "doe_same_2025.PDF"
        check("same-stem sources cannot share one ambiguous review mark",
              reviewable_stems([same_a, same_b]), set())
        for suffix in (".revised", ".pdf"):
            dotted_book, = paths("Prince_UDL_2026" + suffix + ".pdf")
            dotted_chapter, = paths("Prince_UDL_2026_01_Intro" + suffix + ".pdf")
            check("a dotted standalone stem cannot masquerade as a split book: " + suffix,
                  split_book_chapters([dotted_book, ch1]), {})
            check("a dotted chapter stem cannot suppress its undotted book: " + suffix,
                  split_book_chapters([book, dotted_chapter]), {})

        # --- find_pdfs -----------------------------------------------------
        src = os.path.join(tmp, "src")
        os.makedirs(os.path.join(src, "Prince_UDL_2026"))
        a = _st_fig_pdf(os.path.join(src, "Doe_Figs_2025.pdf"),
                        ("Figure 1. First.", "Supplementary Figure 2. Second."))
        b = _st_fig_pdf(os.path.join(src, "Prince_UDL_2026.pdf"))
        c = _st_fig_pdf(os.path.join(src, "Prince_UDL_2026",
                                     "Prince_UDL_2026_01_Intro.pdf"))
        upper_ext = _st_fig_pdf(os.path.join(src, "Doe_Upper_2025.PDF"))
        apple_double = os.path.join(src, "._Doe_Figs_2025.pdf")
        with open(apple_double, "wb") as fh:
            fh.write(b"AppleDouble resource fork, not a PDF source")
        with open(os.path.join(src, "notes.txt"), "w", encoding="utf-8") as fh:
            fh.write("not a pdf")
        found = find_pdfs(src)
        check("find_pdfs walks subfolders and ignores non-PDFs/AppleDouble",
              found, sorted([a, b, c, upper_ext]))
        ok("find_pdfs matches a .PDF extension too", upper_ext in found)
        check("find_pdfs on a single PDF", find_pdfs(str(a)), [a])
        linked_source = Path(tmp) / "linked-source"
        linked_source.mkdir()
        linked_pdf = _st_fig_pdf(linked_source / "Doe_Linked_2025.pdf")
        source_link = Path(src) / "linked"
        source_loop = Path(src) / "loop"
        try:
            source_link.symlink_to(linked_source, target_is_directory=True)
            have_source_links = True
        except (OSError, NotImplementedError):
            have_source_links = False
        if have_source_links:
            found_with_link = find_pdfs(src)
            ok("find_pdfs follows a symlinked source subfolder",
               source_link / linked_pdf.name in found_with_link)
            source_loop.symlink_to(Path(src), target_is_directory=True)
            state["n"] += 1
            try:
                find_pdfs(src)
                state["bad"] += 1
                print("FAIL find_pdfs silently accepted a directory symlink loop")
            except SystemExit as exc:
                if "inventory" not in str(exc).lower():
                    state["bad"] += 1
                    print("FAIL find_pdfs symlink-loop refusal was unclear: %s" % exc)
            source_loop.unlink()
            source_link.unlink()
        else:
            ok("symlinked source-subfolder regression skipped where unavailable", True)
            ok("source symlink-loop regression skipped where unavailable", True)
        pdf_directory = Path(src) / "Not_A_Paper_2025.pdf"
        pdf_directory.mkdir()
        state["n"] += 1
        try:
            find_pdfs(src)
            state["bad"] += 1
            print("FAIL find_pdfs treated a PDF-named directory as a paper")
        except SystemExit as exc:
            if "non-regular" not in str(exc):
                state["bad"] += 1
                print("FAIL PDF-named directory refusal was unclear: %s" % exc)
        pdf_directory.rmdir()
        if have_source_links:
            dangling_pdf = Path(src) / "Dangling_Study_2025.pdf"
            dangling_pdf.symlink_to(Path(src) / "missing.pdf")
            state["n"] += 1
            try:
                find_pdfs(src)
                state["bad"] += 1
                print("FAIL find_pdfs accepted a dangling PDF symlink")
            except SystemExit as exc:
                if "dangling" not in str(exc):
                    state["bad"] += 1
                    print("FAIL dangling PDF refusal was unclear: %s" % exc)
            dangling_pdf.unlink()
        else:
            ok("dangling PDF regression skipped where symlinks are unavailable", True)
        check("an arbitrary output does not imply a vault",
              output_vault_root(os.path.join(tmp, "figure-output")), None)
        inferred_images = os.path.join(tmp, "sample-vault", "Sources", "Images")
        check("the canonical image output implies its vault root",
              output_vault_root(inferred_images),
              Path(tmp) / "sample-vault")
        os.makedirs(inferred_images)
        lower_images = os.path.join(tmp, "sample-vault", "Sources", "images")
        if os.path.exists(lower_images):
            check("a case-insensitive Images alias keeps the vault-wide check",
                  output_vault_root(lower_images),
                  Path(tmp) / "sample-vault")
        else:
            ok("case-insensitive Images alias regression skipped on this filesystem", True)
        state["n"] += 1
        try:
            find_pdfs(os.path.join(src, "notes.txt"))
            state["bad"] += 1
            print("FAIL find_pdfs accepted a file that is not a PDF")
        except SystemExit:
            pass
        state["n"] += 1
        try:
            find_pdfs(os.path.join(tmp, "no-such-folder"))
            state["bad"] += 1
            print("FAIL find_pdfs accepted a folder that does not exist -- "
                  "a mistyped --src must not read as an empty vault")
        except SystemExit:
            pass

        # --- duplicate bytes ------------------------------------------------
        d1 = os.path.join(tmp, "Doe_One_2025_fig_1.png")
        d2 = os.path.join(tmp, "Doe_Two_2025_fig_1.png")
        d3 = os.path.join(tmp, "Doe_One_2025_fig_2.png")
        for p, payload in ((d1, b"same"), (d2, b"same"), (d3, b"different")):
            with open(p, "wb") as fh:
                fh.write(payload)
        check("_sha256 agrees for identical bytes", _sha256(d1), _sha256(d2))
        ok("_sha256 differs for different bytes", _sha256(d1) != _sha256(d3))
        seen, res = {}, {"duplicates": []}
        _note_output(res, seen, d1, "1", "Doe_One_2025")
        check("the first figure is not a duplicate of itself",
              res["duplicates"], [])
        _note_output(res, seen, d2, "1", "Doe_Two_2025")
        check("a byte-identical figure under another stem",
              res["duplicates"], [("1", d1, False)])
        res["duplicates"] = []
        _note_output(res, seen, d3, "2", "Doe_One_2025")
        check("different bytes are not a duplicate", res["duplicates"], [])
        # Same stem, same bytes: two captions the detector could not separate.
        d4 = os.path.join(tmp, "Doe_One_2025_fig_3.png")
        with open(d4, "wb") as fh:
            fh.write(b"same")
        res["duplicates"] = []
        _note_output(res, seen, d4, "3", "Doe_One_2025")
        check("a byte-identical figure under the SAME stem is flagged apart",
              res["duplicates"], [("3", d1, True)])
        res["duplicates"] = []
        _note_output(res, seen, os.path.join(tmp, "gone.png"), "9", "Doe_X_2025")
        check("a figure that is not on disk is not a duplicate",
              res["duplicates"], [])

        # --- process_pdf: which bucket each PDF lands in -------------------
        out = os.path.join(tmp, "Images")
        os.makedirs(out)
        r = process_pdf(a, out, dpi=72)
        check("a normal PDF: figures found", r["figures"], ["1", "S2"])
        check("a normal PDF: figures written", r["extracted"], 2)
        check("a normal PDF: nothing failed", r["failures"], [])
        check("a normal PDF: it has text", r["had_text"], True)
        check("a normal PDF: it opened", r["open_error"], "")
        ok("the PNGs are on disk under the PDF's stem",
           os.path.exists(os.path.join(out, "Doe_Figs_2025_fig_1.png"))
           and os.path.exists(os.path.join(out, "Doe_Figs_2025_fig_S2.png")))
        # Idempotent: the second run skips what the first wrote.
        r2 = process_pdf(a, out, dpi=72)
        check("a re-run skips what exists", (r2["extracted"], r2["skipped"]),
              (0, 2))
        r3 = process_pdf(a, out, dpi=72, overwrite=True)
        check("--overwrite re-extracts", (r3["extracted"], r3["skipped"]),
              (2, 0))
        reviewed_manifest = {
            path.name: _sha256(path) for path in Path(out).glob("*.png")
        }
        reviewed_overwrite = process_pdf(
            a, out, dpi=72, overwrite=True, manifest=reviewed_manifest,
            reviewed={(a.stem, "1"), (a.stem, "S2")})
        check("--overwrite preserves crops named in the review ledger",
              (reviewed_overwrite["extracted"], reviewed_overwrite["skipped"]),
              (0, 2))

        committed_out = os.path.join(tmp, "committed-per-crop")
        os.makedirs(committed_out)
        committed_manifest = {}
        commit_states = []

        def remember_commit():
            commit_states.append(sorted(committed_manifest))

        committed_result = process_pdf(
            a, committed_out, dpi=72, manifest=committed_manifest,
            manifest_commit=remember_commit)
        check("ownership is offered for persistence after every crop",
              (committed_result["extracted"], commit_states),
              (2, [["Doe_Figs_2025_fig_1.png"],
                   ["Doe_Figs_2025_fig_1.png", "Doe_Figs_2025_fig_S2.png"]]))

        scan = process_pdf(_st_scan_pdf(os.path.join(tmp, "Doe_Scan_2025.pdf")),
                           out, dpi=72)
        check("a scan has no text", scan["had_text"], False)
        check("a scan is not an open error", scan["open_error"], "")
        check("a scan has no zero-page flag", scan["no_pages"], False)

        html = process_pdf(_st_html_pdf(os.path.join(tmp, "Doe_Html_2025.pdf")),
                           out, dpi=72)
        ok("an HTML page named .pdf is an open error, not a scan",
           bool(html["open_error"]))
        check("...and is not reported as textless (it has text)",
              html["had_text"], False)

        zero = process_pdf(
            _st_zero_page_pdf(os.path.join(tmp, "Doe_Zero_2025.pdf")), out,
            dpi=72)
        check("a zero-page PDF", zero["no_pages"], True)
        check("...and is not an open error", zero["open_error"], "")

        enc = process_pdf(
            _st_encrypted_pdf(os.path.join(tmp, "Doe_Enc_2025.pdf")), out,
            dpi=72)
        ok("an encrypted PDF is reported, not raised through the run",
           "encrypted" in enc["open_error"])
        ok("...and says how to fix it", "qpdf" in enc["open_error"])

        junk = os.path.join(tmp, "Doe_Junk_2025.pdf")
        with open(junk, "wb") as fh:
            fh.write(b"\x00\x01 not a document at all")
        # `process_pdf` prints the open failure to stderr as it happens; that
        # is the behaviour under test, not something to let leak into the
        # self-test's own output.
        with contextlib.redirect_stderr(io.StringIO()):
            bad_open = process_pdf(Path(junk), out, dpi=72)
        ok("an unreadable file is an open error", bool(bad_open["open_error"]))

        # A caption with no room above it: detected, degenerate, NOT written.
        top = process_pdf(
            _st_top_caption_pdf(os.path.join(tmp, "Doe_Top_2025.pdf")), out,
            dpi=72)
        check("a degenerate bbox is detected", top["figures"], ["3"])
        check("...and counted as a failure, not an extraction",
              (top["extracted"], len(top["failures"])), (0, 1))
        # The REASON has to say degenerate, not just "failed": a collapsed
        # search region is a crop to set by hand, while a render error is a
        # different problem with a different fix. Letting the rect through to
        # PyMuPDF turns the first into the second, in the report only.
        ok("...saying the bbox was degenerate",
           "degenerate bbox" in top["failures"][0][1])
        ok("...naming the page", "page 1" in top["failures"][0][1])
        ok("no PNG was written for it",
           not os.path.exists(os.path.join(out, "Doe_Top_2025_fig_3.png")))
        repaired_path = os.path.join(out, "Doe_Top_2025_fig_3.png")
        shutil.copyfile(os.path.join(out, "Doe_Figs_2025_fig_1.png"), repaired_path)
        repaired_manifest = {os.path.basename(repaired_path): _sha256(repaired_path)}
        repaired_top = process_pdf(Path(os.path.join(tmp, "Doe_Top_2025.pdf")),
                                   out, dpi=72, manifest=repaired_manifest)
        check("a manual repair of degenerate detection is an existing crop",
              (repaired_top["skipped"], repaired_top["failures"]), (1, []))

        # A caption at the foot of a page whose figure is overleaf: the crop
        # is over empty page and renders pure white. It used to be written and
        # counted — `1 extracted, 0 suspicious, 0 failed` for a 314x468 PNG
        # with one colour in it.
        nxt = process_pdf(
            _st_next_page_figure_pdf(os.path.join(tmp, "Doe_Next_2025.pdf")),
            out, dpi=72)
        check("a caption whose figure is overleaf is detected",
              nxt["figures"], ["4"])
        check("...and its all-white crop is NOT an extraction",
              (nxt["extracted"], nxt["skipped"]), (0, 0))
        check("...it is a blank crop, in its own bucket",
              nxt["blank"], [("4", 1)])
        check("...and is not miscounted as a render failure or a flag",
              (nxt["failures"], nxt["warnings"]), ([], []))
        ok("...and no white PNG reached the output folder",
           not os.path.exists(os.path.join(out, "Doe_Next_2025_fig_4.png")))

        # Two side-by-side figures whose captions are a few points apart in
        # height: the left crop reaches over the right caption. The batch path
        # had no caption check at all, so this was written with every bucket
        # reading zero.
        twocol = process_pdf(
            _st_two_column_pdf(os.path.join(tmp, "Doe_TwoCol_2025.pdf")),
            out, dpi=72)
        check("both captions on a two-column page are found",
              sorted(twocol["figures"]), ["1", "2"])
        check("a crop holding another figure's caption is flagged",
              [f for f, _ in twocol["caption_in"]], ["1"])
        ok("...saying which caption is in it",
           "'Figure 2'" in twocol["caption_in"][0][1])
        ok("...and it is a warning as well, so the flag count still sees it",
           ("1", twocol["caption_in"][0][1]) in twocol["warnings"])

        # Resolve duplicate output labels before recording geometry findings.
        # A dropped caption has no PNG of its own, so saying that its caption is
        # in "the PNG" invents an extraction that never took place.
        collision_reason_pdf = _st_fig_pdf(
            os.path.join(tmp, "Doe_CollisionReason_2025.pdf"))
        original_detect_figures = globals()["detect_figures"]
        try:
            def collision_reason_detector(_doc):
                yield (0, "1", "Figure 1", fitz.Rect(100, 100, 300, 300),
                       fitz.Rect(100, 310, 300, 330), "")
                yield (0, "1", "Supplementary Figure 1",
                       fitz.Rect(100, 100, 300, 330),
                       fitz.Rect(100, 310, 300, 330),
                       CAPTION_IN_CROP_TAG + "synthetic overlap")

            globals()["detect_figures"] = collision_reason_detector
            dropped_reason = process_pdf(
                collision_reason_pdf, out, dpi=72, dry_run=True)
        finally:
            globals()["detect_figures"] = original_detect_figures
        check("a dropped caption collision contributes no crop warning",
              (len(dropped_reason["collisions"]), dropped_reason["warnings"],
               dropped_reason["caption_in"], dropped_reason["extracted"]),
              (1, [], [], 1))

        occupied_reason_pdf = _st_fig_pdf(
            os.path.join(tmp, "Doe_OccupiedReason_2025.pdf"))
        occupied_reason_out = os.path.join(tmp, "occupied-reason")
        os.makedirs(occupied_reason_out)
        with open(os.path.join(
                occupied_reason_out,
                "Doe_OccupiedReason_2025_fig_1.jpg"), "wb") as fh:
            fh.write(b"belongs to another producer")
        try:
            def occupied_reason_detector(_doc):
                yield (0, "1", "Figure 1", fitz.Rect(100, 100, 300, 330),
                       fitz.Rect(100, 310, 300, 330),
                       CAPTION_IN_CROP_TAG + "synthetic overlap")

            globals()["detect_figures"] = occupied_reason_detector
            occupied_reason = process_pdf(
                occupied_reason_pdf, occupied_reason_out, dpi=72,
                dry_run=True)
        finally:
            globals()["detect_figures"] = original_detect_figures
        check("an occupied semantic slot contributes no crop warning",
              (len(occupied_reason["occupied"]), occupied_reason["warnings"],
               occupied_reason["caption_in"], occupied_reason["extracted"]),
              (1, [], [], 0))

        # A suspicious bbox, and the ledger that stops it being re-flagged.
        tiny_pdf = _st_tiny_fig_pdf(os.path.join(tmp, "Doe_Tiny_2025.pdf"))
        tiny = process_pdf(tiny_pdf, out, dpi=72)
        check("a tiny figure is flagged", [w[0] for w in tiny["warnings"]], ["1"])
        ok("...with a reason", "width" in tiny["warnings"][0][1])
        tiny2 = process_pdf(tiny_pdf, out, dpi=72, overwrite=True,
                            reviewed={("Doe_Tiny_2025", "1")})
        check("a reviewed bbox stops being nagged about",
              (len(tiny2["warnings"]), len(tiny2["reviewed"])), (0, 1))

        # PARTIAL detection: the body text cites a figure no caption matched.
        partial_pdf = os.path.join(tmp, "Doe_Partial_2025.pdf")
        pdoc = fitz.open()
        page = pdoc.new_page(width=612, height=792)
        page.draw_rect(fitz.Rect(100, 200, 500, 400), fill=(0.4, 0.4, 0.4))
        page.insert_text((100, 430), "Figure 1. The only caption.", fontsize=9)
        page.insert_text((100, 500), "Figure 2 shows the other condition.",
                         fontsize=9)
        pdoc.save(partial_pdf)
        pdoc.close()
        part = process_pdf(Path(partial_pdf), out, dpi=72)
        check("a cited figure with no caption is reported missing",
              part["missing"], ["2"])
        ok("...and the citation count is kept", part["referenced"] >= 2)

        # A split chapter commonly cites a figure from an earlier chapter. It
        # is not a missed local caption only when the local namespace agrees
        # and the exact caption exists in one canonical sibling chapter.
        chapter_pdf = os.path.join(
            tmp, "Geron_HandsOnML_2025_07_DimReduction.pdf")
        cdoc = fitz.open()
        page = cdoc.new_page(width=612, height=792)
        page.draw_rect(fitz.Rect(100, 200, 500, 400), fill=(0.4, 0.4, 0.4))
        page.insert_text((100, 430), "Figure 7-1. The local caption.", fontsize=9)
        page.insert_text((100, 500),
                         "Figure 6.6 shows the earlier construction.", fontsize=9)
        page.insert_text((100, 520),
                         "Figure 7-2 shows the omitted local result.", fontsize=9)
        cdoc.save(chapter_pdf)
        cdoc.close()
        sibling_pdf = os.path.join(
            tmp, "Geron_HandsOnML_2025_06_DecisionTrees.pdf")
        sdoc = fitz.open()
        page = sdoc.new_page(width=612, height=792)
        page.draw_rect(fitz.Rect(100, 200, 500, 400), fill=(0.4, 0.4, 0.4))
        page.insert_text((100, 430), "Figure 6.6. The earlier caption.", fontsize=9)
        sdoc.save(sibling_pdf)
        sdoc.close()
        cached_sibling_pdf = os.path.join(
            tmp, "Geron_HandsOnML_2025_06_CacheProbe.pdf")
        shutil.copyfile(sibling_pdf, cached_sibling_pdf)
        sibling_cache = {}
        labels_before_change = _caption_labels_for_chapter(
            cached_sibling_pdf, sibling_cache)
        with open(cached_sibling_pdf, "ab") as fh:
            fh.write(b"\nchanged after caption evidence was cached\n")
        check("cached sibling evidence is invalidated by an in-place change",
              (labels_before_change,
               _caption_labels_for_chapter(cached_sibling_pdf, sibling_cache)),
              ({"6-6"}, None))
        chapter = process_pdf(
            Path(chapter_pdf), out, dpi=72,
            chapter_pdfs=[Path(chapter_pdf), Path(sibling_pdf)],
            chapter_caption_cache={})
        check("a different-prefix reference in an established split chapter is "
              "reported separately only after an exact dot-style sibling "
              "caption is found", chapter["cross_chapter"], ["6.6"])
        check("a same-prefix reference without a caption remains PARTIAL",
              chapter["missing"], ["7-2"])
        check("the local reference count excludes the classified external label",
              chapter["referenced"], 2)
        unproved = process_pdf(Path(chapter_pdf), out, dpi=72,
                               chapter_pdfs=[], chapter_caption_cache={})
        check("an absent sibling leaves a foreign-prefix reference PARTIAL",
              unproved["missing"], ["6.6", "7-2"])
        wrong_sibling_pdf = os.path.join(
            tmp, "Geron_HandsOnML_2025_06_Other.pdf")
        wdoc = fitz.open()
        page = wdoc.new_page(width=612, height=792)
        page.draw_rect(fitz.Rect(100, 200, 500, 400), fill=(0.4, 0.4, 0.4))
        page.insert_text((100, 430), "Figure 6.5. A different caption.", fontsize=9)
        wdoc.save(wrong_sibling_pdf)
        wdoc.close()
        wrong = process_pdf(
            Path(chapter_pdf), out, dpi=72,
            chapter_pdfs=[Path(wrong_sibling_pdf)], chapter_caption_cache={})
        check("a sibling without the exact caption leaves the reference PARTIAL",
              wrong["cross_chapter"], [])
        unreadable_sibling = Path(
            tmp, "Geron_HandsOnML_2025_06_Unreadable.pdf")
        unreadable_sibling.write_bytes(b"not a PDF")
        unreadable = process_pdf(
            Path(chapter_pdf), out, dpi=72,
            chapter_pdfs=[unreadable_sibling], chapter_caption_cache={})
        check("an unreadable sibling cannot prove a cross-chapter reference",
              unreadable["cross_chapter"], [])
        ambiguous = process_pdf(
            Path(chapter_pdf), out, dpi=72,
            chapter_pdfs=[Path(sibling_pdf), Path(wrong_sibling_pdf)],
            chapter_caption_cache={})
        check("two same-book sibling candidates remain ambiguous and PARTIAL",
              ambiguous["cross_chapter"], [])
        nonchapter_pdf = os.path.join(tmp, "Geron_ChapterExcerpt_2025.pdf")
        shutil.copyfile(chapter_pdf, nonchapter_pdf)
        nonchapter = process_pdf(Path(nonchapter_pdf), out, dpi=72)
        check("the same reference remains PARTIAL without a canonical chapter "
              "identity", nonchapter["missing"], ["6.6", "7-2"])
        check("a mixed numeric caption scheme keeps every miss as PARTIAL",
              partition_cross_chapter_references(
                  Path(chapter_pdf), ["7-1", "1"], ["6-6"]),
              (["6-6"], []))

        # Two source PDFs, same pixels, different stems.
        dup_dir = os.path.join(tmp, "dup")
        os.makedirs(dup_dir)
        one = _st_fig_pdf(os.path.join(tmp, "Doe_One_2025.pdf"))
        two = _st_fig_pdf(os.path.join(tmp, "Doe_Two_2025.pdf"))
        seen = {}
        r_one = process_pdf(one, dup_dir, dpi=72, seen_hashes=seen)
        r_two = process_pdf(two, dup_dir, dpi=72, seen_hashes=seen)
        check("the first copy is not a duplicate", r_one["duplicates"], [])
        check("the second copy is",
              [(f, os.path.basename(o), same)
               for f, o, same in r_two["duplicates"]],
              [("1", "Doe_One_2025_fig_1.png", False)])
        # ...and a dry run cannot see any of it, because it writes no bytes.
        dry_dir = os.path.join(tmp, "dryrun")
        os.makedirs(dry_dir)
        seen = {}
        d_one = process_pdf(one, dry_dir, dpi=72, dry_run=True, seen_hashes=seen)
        d_two = process_pdf(two, dry_dir, dpi=72, dry_run=True, seen_hashes=seen)
        check("a dry run counts what it would extract",
              (d_one["extracted"], d_two["extracted"]), (1, 1))
        check("a dry run writes nothing", os.listdir(dry_dir), [])
        check("a dry run finds no duplicates -- it has no bytes to compare",
              d_two["duplicates"], [])

        check("page_has_text on a text page",
              page_has_text(fitz.open(str(a))[0]), True)
        check("page_has_text on a scan",
              page_has_text(fitz.open(os.path.join(tmp,
                                                   "Doe_Scan_2025.pdf"))[0]),
              False)

        # --- ownership of an output name that already exists ----------------
        # `Sources/Images/` is shared: clipping-processor writes
        # `<slug>_fig_<N>.<ext>` into it too, so a clipping whose slug equals a
        # paper's stem can already own `<stem>_fig_1.png`. The skip reported
        # `1 extracted, 1 skipped (already exist)` — an ordinary re-run, word
        # for word — while the paper's real Figure 1 was never written and
        # every consumer embedded the clipping as it.
        own_dir = os.path.join(tmp, "Owned")
        os.makedirs(own_dir)
        own_pdf = _st_fig_pdf(os.path.join(tmp, "Doe_Owned_2025.pdf"))
        own_manifest = {}
        first = process_pdf(own_pdf, own_dir, dpi=72, manifest=own_manifest)
        check("a first run writes the figure", first["extracted"], 1)
        check("...and records it in the manifest",
              sorted(own_manifest), ["Doe_Owned_2025_fig_1.png"])
        again = process_pdf(own_pdf, own_dir, dpi=72, manifest=own_manifest)
        check("a re-run of our own output is an ordinary skip",
              (again["skipped"], again["occupied"]), (1, []))
        owned_png = Path(own_dir) / "Doe_Owned_2025_fig_1.png"
        webp_twin = Path(own_dir) / "Doe_Owned_2025_fig_1.webp"
        webp_bytes = b"clipping-owned webp in the same semantic figure slot"
        webp_twin.write_bytes(webp_bytes)
        twin_blocked = process_pdf(
            own_pdf, own_dir, dpi=72, manifest=own_manifest, overwrite=True)
        check("an extension twin blocks even beside a verified own PNG",
              (twin_blocked["extracted"], twin_blocked["skipped"],
               len(twin_blocked["occupied"])), (0, 0, 1))
        check("a blocked WebP twin and owned PNG are both preserved",
              (webp_twin.read_bytes(), _sha256(owned_png)),
              (webp_bytes, own_manifest[owned_png.name]))
        webp_twin.unlink()
        differently_cased = {key.upper(): value for key, value in own_manifest.items()}
        case_rerun = process_pdf(own_pdf, own_dir, dpi=72, manifest=differently_cased)
        check("equivalent ownership casing skips without rewriting the stored key",
              (case_rerun["skipped"], case_rerun["occupied"], sorted(differently_cased)),
              (1, [], ["DOE_OWNED_2025_FIG_1.PNG"]))
        ambiguous = dict(own_manifest, **differently_cased)
        ambiguous_rerun = process_pdf(own_pdf, own_dir, dpi=72, overwrite=True,
                                      manifest=ambiguous)
        check("ambiguous equivalent ownership never permits overwrite",
              (ambiguous_rerun["extracted"], len(ambiguous_rerun["occupied"])), (0, 1))
        # Now another skill takes the name.
        occupied_path = os.path.join(own_dir, "Doe_Owned_2025_fig_1.png")
        with open(occupied_path, "wb") as fh:
            fh.write(b"\x89PNG\r\n\x1a\n not this extractor's bytes")
        foreign = process_pdf(own_pdf, own_dir, dpi=72, manifest=own_manifest)
        check("a file we did not write is NOT a skip",
              (foreign["skipped"], foreign["extracted"]), (0, 0))
        check("...it is an occupied name, in its own bucket",
              [(f, os.path.basename(p)) for f, p, _ in foreign["occupied"]],
              [("1", "Doe_Owned_2025_fig_1.png")])
        ok("...saying the bytes are not the ones we wrote",
           "changed" in foreign["occupied"][0][2])
        foreign_bytes = Path(occupied_path).read_bytes()
        forced = process_pdf(own_pdf, own_dir, dpi=72, overwrite=True,
                             manifest=own_manifest)
        check("--overwrite cannot claim a foreign occupant",
              (forced["extracted"], len(forced["occupied"]), Path(occupied_path).read_bytes()),
              (0, 1, foreign_bytes))
        # A name with no manifest entry at all — the clipping got there first.
        never = process_pdf(own_pdf, own_dir, dpi=72, manifest={})
        ok("a name we have no record of writing is occupied too",
           [f for f, _p, _w in never["occupied"]] == ["1"]
           and "no record" in never["occupied"][0][2])
        # ...and a caller with no manifest at all keeps the old behaviour,
        # rather than reading an empty one as "none of this is mine".
        check("no manifest supplied means no ownership claim either way",
              process_pdf(own_pdf, own_dir, dpi=72)["skipped"], 1)

        # The semantic slot uses portable stem/label identity, not the exact
        # PNG pathname. Clipping-owned JPG/WebP spellings must therefore block
        # on every filesystem, including when case or Unicode normalization
        # would alias on a case-insensitive or normalization-insensitive host.
        alias_dir = Path(tmp) / "PortableSlots"
        alias_dir.mkdir()
        case_pdf = _st_fig_pdf(Path(tmp) / "Doe_CaseSlot_2025.pdf")
        case_alias = alias_dir / "doe_caseslot_2025_FIG_1.jpg"
        case_bytes = b"clipping-owned jpg under a portable case alias"
        case_alias.write_bytes(case_bytes)
        case_blocked = process_pdf(case_pdf, alias_dir, dpi=72, manifest={})
        check("a clipping JPG under a case alias occupies the PDF figure slot",
              (case_blocked["extracted"], len(case_blocked["occupied"])),
              (0, 1))
        check("the blocked case-alias JPG is preserved",
              case_alias.read_bytes(), case_bytes)

        unicode_pdf = _st_fig_pdf(Path(tmp) / "García_Slot_2025.pdf")
        unicode_alias = alias_dir / "Garci\u0301a_Slot_2025_fig_1.webp"
        unicode_bytes = b"clipping-owned webp under an NFD stem alias"
        unicode_alias.write_bytes(unicode_bytes)
        unicode_blocked = process_pdf(
            unicode_pdf, alias_dir, dpi=72, manifest={})
        check("a clipping WebP under an NFC-equivalent alias occupies the slot",
              (unicode_blocked["extracted"], len(unicode_blocked["occupied"])),
              (0, 1))
        check("the blocked Unicode-alias WebP is preserved",
              unicode_alias.read_bytes(), unicode_bytes)

        # APFS/HFS can expose the one PNG created through an NFC pathname with
        # an NFD directory spelling. That is the same directory entry, not a
        # competing variant. On filesystems where both spellings are distinct,
        # the NFD file correctly remains a collision instead.
        unicode_own_dir = Path(tmp) / "UnicodeOwned"
        unicode_own_dir.mkdir()
        unicode_own_pdf = _st_fig_pdf(Path(tmp) / "García_Own_2025.pdf")
        unicode_own_manifest = {}
        unicode_first = process_pdf(
            unicode_own_pdf, unicode_own_dir, dpi=72,
            manifest=unicode_own_manifest)
        unicode_nfc = unicode_own_dir / "García_Own_2025_fig_1.png"
        unicode_nfd = unicode_own_dir / "Garci\u0301a_Own_2025_fig_1.png"
        rendered_bytes = unicode_nfc.read_bytes()
        unicode_nfc.unlink()
        unicode_nfd.write_bytes(rendered_bytes)
        unicode_own_manifest = {
            unicode_nfd.name: hashlib.sha256(rendered_bytes).hexdigest()
        }
        aliases_one_entry = os.path.lexists(unicode_nfc)
        unicode_again = process_pdf(
            unicode_own_pdf, unicode_own_dir, dpi=72,
            manifest=unicode_own_manifest)
        if aliases_one_entry:
            check("an NFD directory spelling of our NFC PNG is the same output",
                  (unicode_first["extracted"], unicode_again["skipped"],
                   unicode_again["occupied"]), (1, 1, []))
        else:
            check("a distinct NFD PNG remains a portable-slot collision",
                  (unicode_again["skipped"], len(unicode_again["occupied"])),
                  (0, 1))

        # Publication happens after the per-figure ownership check and render.
        # Exercise a new name and an approved overwrite being taken during
        # that interval; neither late occupant may be clobbered.
        race_new_dir = os.path.join(tmp, "RaceNew")
        os.makedirs(race_new_dir)
        race_new_pdf = _st_fig_pdf(os.path.join(tmp, "Doe_RaceNew_2025.pdf"))
        race_new_path = os.path.join(race_new_dir,
                                     "Doe_RaceNew_2025_fig_1.png")
        race_new_bytes = b"late clipping image in a formerly empty slot"
        real_extract_one = extract_one_figure

        def reject_batch_hard_link(doc_arg, page_arg, bbox_arg, out_path,
                                   *args, **kwargs):
            exc = atomic_move.LinkUnavailable(
                out_path + ".stage", out_path,
                OSError(errno.ENOTSUP, "injected filesystem has no hard links"))
            exc.staging_path = out_path + ".stage"
            exc.recovery_path = exc.staging_path
            raise exc

        no_link_dir = os.path.join(tmp, "NoHardLinks")
        os.makedirs(no_link_dir)
        with mock.patch.dict(
                globals(), {"extract_one_figure": reject_batch_hard_link}), \
                contextlib.redirect_stderr(io.StringIO()):
            no_link = process_pdf(
                race_new_pdf, no_link_dir, dpi=72, manifest={})
        no_link_reason = " | ".join(reason for _fig, reason
                                    in no_link["failures"])
        check("batch classifies hard-link refusal as publication failure",
              (no_link["extracted"], len(no_link["occupied"]),
               len(no_link["failures"]),
               "safe publication is unavailable" in no_link_reason,
               "render failed" in no_link_reason,
               "staged crop preserved at" in no_link_reason),
              (0, 0, 1, True, False, True))

        def inject_batch_new(doc_arg, page_arg, bbox_arg, out_path,
                             *args, **kwargs):
            with open(out_path, "wb") as fh:
                fh.write(race_new_bytes)
            return real_extract_one(doc_arg, page_arg, bbox_arg, out_path,
                                    *args, **kwargs)

        with mock.patch.dict(globals(), {"extract_one_figure": inject_batch_new}), \
                contextlib.redirect_stderr(io.StringIO()):
            race_new = process_pdf(race_new_pdf, race_new_dir, dpi=72,
                                   manifest={})
        check("batch new-output publication refuses a late occupant",
              (race_new["extracted"], len(race_new["occupied"])), (0, 1))
        check("batch new-output publication preserves the late bytes",
              open(race_new_path, "rb").read(), race_new_bytes)
        race_new_reason = race_new["occupied"][0][2]
        race_new_stages = [
            os.path.join(tmp, name) for name in os.listdir(tmp)
            if name.startswith(".figure-stage-")
        ]
        check("batch reports and retains the recoverable late-occupant crop",
              (len(race_new_stages),
               bool(race_new_stages and race_new_stages[0] in race_new_reason),
               sorted(os.listdir(race_new_stages[0])) if race_new_stages else []),
              (1, True, ["Doe_RaceNew_2025_fig_1.png"]))
        for race_stage in race_new_stages:
            shutil.rmtree(race_stage)

        race_replace_dir = os.path.join(tmp, "RaceReplace")
        os.makedirs(race_replace_dir)
        race_replace_pdf = _st_fig_pdf(
            os.path.join(tmp, "Doe_RaceReplace_2025.pdf"))
        race_manifest = {}
        first_race = process_pdf(race_replace_pdf, race_replace_dir, dpi=72,
                                 manifest=race_manifest)
        check("the overwrite-race fixture begins as verified output",
              first_race["extracted"], 1)
        race_replace_path = os.path.join(
            race_replace_dir, "Doe_RaceReplace_2025_fig_1.png")
        recorded_before_race = dict(race_manifest)
        race_replace_bytes = b"foreign bytes written after batch preflight"

        def inject_batch_replace(doc_arg, page_arg, bbox_arg, out_path,
                                 *args, **kwargs):
            with open(out_path, "wb") as fh:
                fh.write(race_replace_bytes)
            return real_extract_one(doc_arg, page_arg, bbox_arg, out_path,
                                    *args, **kwargs)

        with mock.patch.dict(
                globals(), {"extract_one_figure": inject_batch_replace}), \
                contextlib.redirect_stderr(io.StringIO()):
            race_replace = process_pdf(
                race_replace_pdf, race_replace_dir, dpi=72, overwrite=True,
                manifest=race_manifest,
            )
        check("batch overwrite refuses a different late occupant",
              (race_replace["extracted"], len(race_replace["occupied"])),
              (0, 1))
        check("batch overwrite preserves the different late bytes",
              open(race_replace_path, "rb").read(), race_replace_bytes)
        check("a refused batch overwrite does not alter ownership records",
              race_manifest, recorded_before_race)

        # A process can replace the public path after the guarded crop CAS but
        # before `_note_output`. Ownership must follow the exact publication
        # snapshot returned by extract_one_figure, not a second pathname hash.
        post_publish_dir = Path(tmp) / "PostPublishReplacement"
        post_publish_dir.mkdir()
        post_publish_pdf = _st_fig_pdf(
            Path(tmp) / "Doe_PostPublish_2025.pdf")
        post_publish_path = (
            post_publish_dir / "Doe_PostPublish_2025_fig_1.png")
        post_publish_foreign = b"foreign replacement after batch publication"
        post_publish_snapshot = {}
        post_publish_manifest = {}

        def inject_post_publish_replace(doc_arg, page_arg, bbox_arg, out_path,
                                        *args, **kwargs):
            answer = real_extract_one(
                doc_arg, page_arg, bbox_arg, out_path, *args, **kwargs)
            post_publish_snapshot["digest"] = answer[3][1]
            replacement = Path(out_path + ".foreign")
            replacement.write_bytes(post_publish_foreign)
            os.replace(replacement, out_path)
            return answer

        with mock.patch.dict(
                globals(), {"extract_one_figure": inject_post_publish_replace}):
            post_publish = process_pdf(
                post_publish_pdf, post_publish_dir, dpi=72,
                manifest=post_publish_manifest)
        check("batch ownership records the publication, not a later path occupant",
              (post_publish["extracted"],
               post_publish_manifest[post_publish_path.name],
               _sha256(post_publish_path) == post_publish_snapshot["digest"]),
              (1, post_publish_snapshot["digest"], False))
        post_publish_again = process_pdf(
            post_publish_pdf, post_publish_dir, dpi=72, overwrite=True,
            manifest=post_publish_manifest)
        check("the later batch sees that replacement as foreign",
              (post_publish_again["extracted"],
               len(post_publish_again["occupied"])), (0, 1))
        check("batch overwrite preserves the foreign post-publication bytes",
              post_publish_path.read_bytes(), post_publish_foreign)

        # A different extension can arrive after the batch preflight while a
        # crop renders. The publication guard checks on both sides of the
        # atomic exact-name write and conditionally rolls our publication back.
        late_slot_dir = Path(tmp) / "RaceSlotNew"
        late_slot_dir.mkdir()
        late_slot_pdf = _st_fig_pdf(Path(tmp) / "Doe_RaceSlotNew_2025.pdf")
        late_slot_png = late_slot_dir / "Doe_RaceSlotNew_2025_fig_1.png"
        late_slot_webp = late_slot_dir / "Doe_RaceSlotNew_2025_fig_1.webp"
        late_slot_bytes = b"extension twin arriving during publication"
        real_slot_conflict = _figure_slot_conflict
        slot_checks = {"count": 0}

        def inject_late_slot(*args, **kwargs):
            slot_checks["count"] += 1
            if slot_checks["count"] == 3:
                late_slot_webp.write_bytes(late_slot_bytes)
            return real_slot_conflict(*args, **kwargs)

        with mock.patch.dict(
                globals(), {"_figure_slot_conflict": inject_late_slot}), \
                contextlib.redirect_stderr(io.StringIO()):
            late_slot = process_pdf(
                late_slot_pdf, late_slot_dir, dpi=72, manifest={})
        check("a late extension twin rejects and withdraws a new PNG",
              (late_slot["extracted"], len(late_slot["occupied"]),
               late_slot_png.exists()), (0, 1, False))
        check("the late extension twin itself is preserved",
              late_slot_webp.read_bytes(), late_slot_bytes)

        late_replace_dir = Path(tmp) / "RaceSlotReplace"
        late_replace_dir.mkdir()
        late_replace_pdf = _st_fig_pdf(
            Path(tmp) / "Doe_RaceSlotReplace_2025.pdf")
        late_replace_manifest = {}
        process_pdf(late_replace_pdf, late_replace_dir, dpi=72,
                    manifest=late_replace_manifest)
        late_replace_png = (
            late_replace_dir / "Doe_RaceSlotReplace_2025_fig_1.png")
        predecessor_bytes = b"verified predecessor restored after slot race"
        late_replace_png.write_bytes(predecessor_bytes)
        late_replace_manifest[late_replace_png.name] = _sha256(late_replace_png)
        late_replace_webp = (
            late_replace_dir / "Doe_RaceSlotReplace_2025_fig_1.webp")
        late_replace_bytes = b"extension twin arriving during replacement"
        slot_checks = {"count": 0}

        def inject_late_replace_slot(*args, **kwargs):
            slot_checks["count"] += 1
            if slot_checks["count"] == 3:
                late_replace_webp.write_bytes(late_replace_bytes)
            return real_slot_conflict(*args, **kwargs)

        with mock.patch.dict(
                globals(), {"_figure_slot_conflict": inject_late_replace_slot}), \
                contextlib.redirect_stderr(io.StringIO()):
            late_replace = process_pdf(
                late_replace_pdf, late_replace_dir, dpi=72, overwrite=True,
                manifest=late_replace_manifest)
        check("a late extension twin rolls a verified replacement back",
              (late_replace["extracted"], len(late_replace["occupied"]),
               late_replace_png.read_bytes()),
              (0, 1, predecessor_bytes))
        check("replacement rollback preserves the late twin and ownership",
              (late_replace_webp.read_bytes(),
               late_replace_manifest[late_replace_png.name]),
              (late_replace_bytes, _sha256(late_replace_png)))

        unverifiable_dir = os.path.join(tmp, "UnverifiableRender")
        os.makedirs(unverifiable_dir)
        unverifiable_pdf = _st_fig_pdf(
            os.path.join(tmp, "Doe_Unverifiable_2025.pdf"))
        extract_module = sys.modules[real_extract_one.__module__]
        with mock.patch.object(extract_module, "render_is_blank",
                               return_value=None), \
                contextlib.redirect_stderr(io.StringIO()):
            unverifiable_result = process_pdf(
                unverifiable_pdf, unverifiable_dir, dpi=72, manifest={})
        check("batch treats an unverifiable staged PNG as a failed write",
              (unverifiable_result["extracted"],
               len(unverifiable_result["failures"])), (0, 1))
        ok("batch publishes nothing when nonblank validation is unavailable",
           not os.path.lexists(os.path.join(
               unverifiable_dir, "Doe_Unverifiable_2025_fig_1.png")))

        check("load_manifest on a file that does not exist",
              load_manifest(os.path.join(tmp, "nope.tsv")), {})
        man_path = os.path.join(tmp, "man.tsv")
        save_manifest(man_path, {"a_fig_1.png": "a" * 64, "b_fig_2.png": "b" * 64})
        check("a manifest round-trips", load_manifest(man_path),
              {"a_fig_1.png": "a" * 64, "b_fig_2.png": "b" * 64})
        ok("...and explains itself at the top",
           open(man_path, encoding="utf-8").read().startswith("#"))
        planned_manifest, manifest_expected = load_manifest(
            man_path, with_snapshot=True)
        concurrent_manifest = open(man_path, encoding="utf-8").read()
        concurrent_manifest += "late_fig_3.png\t" + "c" * 64 + "\n"
        with open(man_path, "w", encoding="utf-8", newline="") as fh:
            fh.write(concurrent_manifest)
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            saved = save_manifest(man_path, planned_manifest,
                                  expected=manifest_expected)
        check("a stale batch manifest save reports failure", saved, False)
        check("a stale batch save preserves the concurrent manifest update",
              open(man_path, encoding="utf-8").read(), concurrent_manifest)

        # --- the digest index is seeded from what is already in --out -------
        # `_note_output`'s docstring has always said "existing files are hashed
        # too: the second copy is usually written on a later run than the
        # first". It was false: `seen_hashes` started empty every run and was
        # filled only from paths that run touched, so a byte-identical twin
        # already on disk from a PRIOR run — the case the sentence describes —
        # went unreported.
        seed_dir = os.path.join(tmp, "Seed")
        os.makedirs(seed_dir)
        prior = os.path.join(seed_dir, "Doe_Prior_2025_fig_1.png")
        shutil.copyfile(os.path.join(out, "Doe_Figs_2025_fig_1.png"), prior)
        seeded = seed_output_index(seed_dir)
        check("seeding hashes the figures already in --out",
              sorted(os.path.basename(p) for p in seeded.values()),
              ["Doe_Prior_2025_fig_1.png"])
        upper_seed = Path(seed_dir) / "Doe_Upper_2025_fig_2.PNG"
        upper_seed.write_bytes(b"uppercase-extension seed")
        check("seeding includes an uppercase PNG extension",
              sorted(os.path.basename(p) for p in seed_output_index(seed_dir).values()),
              ["Doe_Prior_2025_fig_1.png", "Doe_Upper_2025_fig_2.PNG"])
        upper_seed.unlink()
        clipping = Path(seed_dir) / "Smith_Web_2025_fig_1.png"
        clipping.write_bytes(b"an unrelated clipping image with different bytes")
        unorganized_image = Path(seed_dir) / "download_fig_1.png"
        unorganized_image.write_bytes(b"an image keyed to an unorganized PDF")
        mixed_manifest = {}
        mixed_seen = seed_output_index(seed_dir)
        check("indexing never claims a figure-shaped filename",
              mixed_manifest, {})
        check("unclaimed images still participate in the digest inventory",
              set(mixed_seen),
              {_sha256(prior), _sha256(str(clipping)),
               _sha256(str(unorganized_image))})

        explicit_manifest = {}
        explicit = adopt_legacy_files(
            seed_dir, ["Doe_Prior_2025:1"], {"Doe_Prior_2025"},
            explicit_manifest, False)
        check("one exact complete PNG can be selected for legacy adoption",
              ([item[1] for item in explicit], explicit_manifest),
              (["Doe_Prior_2025_fig_1.png"],
               {"Doe_Prior_2025_fig_1.png": _sha256(prior)}))
        ok("an unchanged explicit adoption revalidates before sidecar save",
           revalidate_legacy_adoptions(explicit, explicit_manifest))
        second_legacy = Path(seed_dir) / "Doe_Prior_2025_fig_2.png"
        shutil.copyfile(prior, second_legacy)
        repeated_manifest = {}
        repeated = adopt_legacy_files(
            seed_dir, ["Doe_Prior_2025:1", "Doe_Prior_2025:2"],
            {"Doe_Prior_2025"}, repeated_manifest, False)
        check("--adopt-legacy is repeatable but remains file-exact",
              ([item[1] for item in repeated], sorted(repeated_manifest)),
              (["Doe_Prior_2025_fig_1.png", "Doe_Prior_2025_fig_2.png"],
               ["Doe_Prior_2025_fig_1.png", "Doe_Prior_2025_fig_2.png"]))
        second_legacy.unlink()
        existing_manifest = {"Other_Study_2025_fig_1.png": "a" * 64}
        existing_adoption = adopt_legacy_files(
            seed_dir, ["Doe_Prior_2025:1"], {"Doe_Prior_2025"},
            existing_manifest, True)
        check("an existing manifest can adopt a distinct unrecorded slot",
              ([item[1] for item in existing_adoption],
               sorted(existing_manifest)),
              (["Doe_Prior_2025_fig_1.png"],
               ["Doe_Prior_2025_fig_1.png", "Other_Study_2025_fig_1.png"]))
        for entry, eligible, existed, phrase in (
                ("Doe_Prior_2025:2", {"Doe_Prior_2025"}, False,
                 "requires the exact regular file"),
                ("doe_prior_2025:1", {"Doe_Prior_2025"}, False,
                 "exact on-disk stem"),
                ("Doe_Prior_2025:../1", {"Doe_Prior_2025"}, False,
                 "filename fragment")):
            state["n"] += 1
            try:
                adopt_legacy_files(seed_dir, [entry], eligible, {}, existed)
                state["bad"] += 1
                print("FAIL unsafe explicit legacy adoption: %s" % entry)
            except ValueError as exc:
                if phrase not in str(exc):
                    state["bad"] += 1
                    print("FAIL unclear adoption refusal for %s: %s" %
                          (entry, exc))
        state["n"] += 1
        try:
            adopt_legacy_files(
                seed_dir, ["Doe_Prior_2025:1"], {"Doe_Prior_2025"},
                {"DOE_PRIOR_2025_FIG_1.PNG": "a" * 64}, True)
            state["bad"] += 1
            print("FAIL adoption accepted a slot already in the manifest")
        except ValueError as exc:
            if "already has an ownership record" not in str(exc):
                state["bad"] += 1
                print("FAIL unclear recorded-slot adoption refusal: %s" % exc)
        changed_manifest = dict(explicit_manifest)
        Path(prior).write_bytes(clipping.read_bytes())
        with contextlib.redirect_stderr(io.StringIO()):
            stable = revalidate_legacy_adoptions(explicit, changed_manifest)
        check("a changed legacy PNG loses its pending claim",
              (stable, changed_manifest), (False, {}))
        shutil.copyfile(os.path.join(out, "Doe_Figs_2025_fig_1.png"), prior)
        foreign_twin = Path(seed_dir) / "Doe_Prior_2025_fig_2.png"
        shutil.copyfile(str(clipping), str(foreign_twin))
        mixed_result = {"duplicates": []}
        _note_output(mixed_result, mixed_seen, str(foreign_twin), "2", "Doe_Prior_2025")
        check("duplicates against an unclaimed clipping remain reportable",
              mixed_result["duplicates"], [("2", str(clipping), False)])
        foreign_twin.unlink()
        twin_seen = seed_output_index(seed_dir)
        # `a` renders the same pixels the prior run left on disk, under its
        # own stem: the same document reaching the source tree twice.
        twin = process_pdf(a, seed_dir, dpi=72, seen_hashes=twin_seen)
        check("a twin of a figure written by an EARLIER run is reported",
              [(f, os.path.basename(o), same)
               for f, o, same in twin["duplicates"]][0],
              ("1", "Doe_Prior_2025_fig_1.png", False))
        empty_seen = seed_output_index(os.path.join(tmp, "no-such-dir"))
        check("seeding a folder that does not exist", empty_seen, {})

        # --- the --mark-reviewed line is a command, not a fragment ----------
        cmd = mark_reviewed_command("/v/Sources/PDFs", "/v/Sources/Images",
                                    "Doe_Tiny_2025", "1")
        ok("the mark-reviewed line preserves the Python environment",
           shlex.split(cmd)[0] == sys.executable)
        ok("...names this script by absolute path",
           os.path.abspath(__file__) in cmd)
        ok("...carries both required arguments",
           "--src /v/Sources/PDFs" in cmd and "--out /v/Sources/Images" in cmd)
        ok("...and the mark itself", "--mark-reviewed Doe_Tiny_2025:1" in cmd)
        ok("a path with a space is quoted for the shell",
           "'/v/My Vault/Sources/Images'" in mark_reviewed_command(
               "/v/s", "/v/My Vault/Sources/Images", "A", "1"))

        # --- print_summary --------------------------------------------------
        def summary(per_pdf, **kw):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                print_summary(per_pdf, out, **kw)
            return buf.getvalue()

        ok("the summary counts the figures extracted",
           "Figures extracted:    2" in summary({a: r}))
        text = summary({a: r, tiny_pdf: tiny, Path(partial_pdf): part,
                        Path(junk): bad_open})
        ok("the summary names the flagged bbox", "Doe_Tiny_2025.pdf" in text)
        ok("the summary prints the --mark-reviewed line for a PDF that has "
           "a flag", "--mark-reviewed Doe_Tiny_2025:1" in text)
        ok("the summary prints a runnable --mark-reviewed command, not just "
           "the flag", shlex.quote(sys.executable) in text and "--src " in text
           and "--out " in text)
        ok("the summary reports PARTIAL detection", "PARTIAL" in text)
        ok("...naming page-margin clipping as a cause, since the caption "
           "regex is only one of three", "page-margin" in text)
        # The three new outcomes each get their own line and their own
        # remediation: a blank crop, a caption inside a crop, and an output
        # name held by another skill's file are three different instructions.
        text = summary({Path(os.path.join(tmp, "Doe_Next_2025.pdf")): nxt})
        ok("the summary counts blank crops", "Blank crops:          1" in text)
        ok("...with their own section", "rendered nothing but white" in text)
        ok("...and their own remediation", "is on another page" in text
           or "figure is overleaf" in text or "overleaf" in text)
        # Every figure blank is one detection failure, not N blank crops —
        # and without a line saying so it reads as an empty run.
        ok("...and says so when EVERY figure in a PDF came out blank",
           "one detection failure for the whole PDF" in text)
        ok("...naming the PDF and the count",
           "ALL 1 figure(s) detected in Doe_Next_2025.pdf" in text)
        mixed = dict(nxt)
        mixed["extracted"] = 1
        mixed["figures"] = ["4", "5"]
        check("...and not when some figures did come out",
              "one detection failure for the whole PDF"
              in summary({Path(os.path.join(tmp, "Doe_Next_2025.pdf")): mixed}),
              False)
        text = summary({Path(os.path.join(tmp, "Doe_TwoCol_2025.pdf")): twocol})
        ok("the summary counts caption text inside a crop",
           "Caption text in crop: 1" in text)
        ok("...with its own section",
           "the one thing this skill promises it excludes" in text)
        text = summary({own_pdf: foreign})
        ok("the summary counts occupied output names",
           "Occupied filenames:   1" in text)
        ok("...and says they were neither extracted nor skipped",
           "NOT extracted and NOT skipped" in text)
        ok("...naming the other producer", "clipping-processor" in text)
        text = summary({a: r, tiny_pdf: tiny, Path(partial_pdf): part,
                        Path(junk): bad_open})
        ok("the summary keeps the unreadable file out of the OCR bucket",
           "not a readable PDF" in text)
        text = summary({one: r_one, two: r_two})
        ok("the summary reports cross-stem duplicates",
           "two different stems" in text)
        # Two PDFs whose stems differ only in case claim one portable figure
        # namespace and must be refused together.
        text = summary({Path(os.path.join(tmp, "A", "Doe_Figs_2025.pdf")): r,
                        Path(os.path.join(tmp, "B", "doe_figs_2025.pdf")): r})
        ok("the summary warns about a stem collision",
           "stem collisions" in text and "doe_figs_2025.pdf" in text)
        text = summary({a: r})
        check("...and says nothing when the stems are distinct",
              "stem collisions" in text, False)
        text = summary({b: r}, skipped_books={b: [c]})
        ok("the summary names a skipped book", "Split books" in text)
        # A dry run's duplicate count is not a finding: it hashes written
        # PNGs, and a dry run writes none.
        text = summary({one: d_one}, dry_run=True)
        ok("a dry run says the duplicate check did not run",
           "a dry run writes no bytes" in text)
        text = summary({one: r_one})
        ok("a real run reports the duplicate count plainly",
           "byte-identical to a figure already written" in text)

        # --- main(), end to end --------------------------------------------
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

        run_out = os.path.join(tmp, "run-out")
        for suffix in (".revised", ".pdf"):
            dotted = _st_fig_pdf(Path(tmp) / ("Doe_Dotted_2025" + suffix + ".pdf"))
            dotted_out = Path(tmp) / ("dotted-out-" + suffix[1:])
            code, so, se = run(["--src", str(dotted), "--out", str(dotted_out), "--dpi", "72"])
            check("the CLI refuses an exact dotted stem: " + dotted.name, code, 1)
            check("a refused dotted stem publishes and claims no figures",
                  (list(dotted_out.glob("*.png")), (dotted_out / MANIFEST_FILE).exists()), ([], False))

        # A clipping can have the same canonical stem and exact figure slot as
        # a PDF. Even a complete PNG is unclaimed by default; migration needs
        # the caller to select each exact STEM:FIG. Broken or disguised PNGs
        # remain ineligible even with that explicit selection.
        from PIL import Image
        legacy_pdf = _st_fig_pdf(Path(tmp) / "Doe_Legacy_2025.pdf")
        for kind in ("truncated", "wrong-format", "valid"):
            legacy_out = Path(tmp) / ("legacy-png-" + kind)
            legacy_out.mkdir()
            legacy_png = legacy_out / "Doe_Legacy_2025_fig_1.png"
            if kind == "truncated":
                legacy_png.write_bytes(b"\x89PNG\r\n\x1a\n")
            else:
                Image.new("RGB", (30, 20), (40, 90, 150)).save(
                    legacy_png, format="JPEG" if kind == "wrong-format" else "PNG")
            original = legacy_png.read_bytes()
            code, so, se = run(["--src", str(legacy_pdf), "--out", str(legacy_out), "--dpi", "72"])
            check("default migration refuses every occupied legacy slot: " + kind,
                  code, 1)
            check("default migration never replaces the occupant: " + kind,
                  legacy_png.read_bytes(), original)
            ok("default migration leaves the manifest absent: " + kind,
               not (legacy_out / MANIFEST_FILE).exists())
            ok("default migration reports the slot as another producer's: " + kind,
               "occupied by another skill's file" in so
               and "skipped (already exist)" not in so)

            code, so, se = run([
                "--src", str(legacy_pdf), "--out", str(legacy_out),
                "--dpi", "72", "--adopt-legacy", "Doe_Legacy_2025:1",
            ])
            check("explicit complete-PNG validation controls adoption: " + kind,
                  code, 0 if kind == "valid" else 1)
            check("explicit adoption never replaces the occupant: " + kind,
                  legacy_png.read_bytes(), original)
            check("only an explicitly selected complete PNG receives ownership: " + kind,
                  load_manifest(legacy_out / MANIFEST_FILE),
                  {legacy_png.name: _sha256(legacy_png)} if kind == "valid" else {})
            if kind != "valid":
                ok("invalid explicit adoptions are reported before extraction",
                   "--adopt-legacy" in se and "No sidecar or figure was written" in se)

        warning_png = Path(tmp) / "legacy-decompression-warning.png"
        Image.new("RGB", (100, 100), (40, 90, 150)).save(
            warning_png, format="PNG")
        warning_refused = False
        with mock.patch.object(Image, "MAX_IMAGE_PIXELS", 6000):
            try:
                _legacy_png_snapshot(warning_png)
            except ValueError as exc:
                warning_refused = "fully decoded" in str(exc)
        ok("legacy adoption treats a decompression-bomb warning as refusal",
           warning_refused)

        adopted_bytes = legacy_png.read_bytes()
        adopted_manifest = (legacy_out / MANIFEST_FILE).read_bytes()
        code, so, se = run([
            "--src", str(legacy_pdf), "--out", str(legacy_out),
            "--adopt-legacy", "Doe_Legacy_2025:1", "--overwrite",
        ])
        check("adoption and replacement require separate runs", code, 2)
        check("a refused combined migration changes neither file nor ledger",
              (legacy_png.read_bytes(),
               (legacy_out / MANIFEST_FILE).read_bytes()),
              (adopted_bytes, adopted_manifest))

        code, so, se = run(["--src", src, "--out", run_out, "--dpi", "72"])
        check("a clean run exits 0", code, 0)
        ok("the book is skipped in favour of its chapters",
           "Skipping Prince_UDL_2026.pdf" in so)
        ok("the chapter's figures are written",
           os.path.exists(os.path.join(run_out,
                                       "Prince_UDL_2026_01_Intro_fig_1.png")))
        ok("the book's figures are NOT written under the book's stem",
           not os.path.exists(os.path.join(run_out,
                                           "Prince_UDL_2026_fig_1.png")))
        code, so, se = run(["--src", src, "--out", run_out, "--dpi", "72",
                            "--include-split-books"])
        ok("--include-split-books extracts the book too",
           os.path.exists(os.path.join(run_out, "Prince_UDL_2026_fig_1.png")))

        # An unorganized filename is refused, and the run says so in its exit
        # code as well as its output: a batch that extracted nothing must not
        # report success to whatever called it.
        unorg = os.path.join(tmp, "unorganized")
        os.makedirs(unorg)
        _st_fig_pdf(os.path.join(unorg, "download (1).pdf"))
        code, so, se = run(["--src", unorg, "--out", run_out, "--dpi", "72"])
        ok("an unorganized PDF is refused", "REFUSED" in so)
        check("a run that refused everything exits non-zero", code, 1)
        ok("...and says nothing is left", "Nothing left to process." in so)
        code, so, se = run(["--src", unorg, "--out", run_out, "--dpi", "72",
                            "--allow-unorganized"])
        check("--allow-unorganized runs it", code, 0)
        ok("...and writes its figures",
           os.path.exists(os.path.join(run_out, "download (1)_fig_1.png")))

        # A PDF that could not be opened is a failed run, not a clean one.
        badsrc = os.path.join(tmp, "badsrc")
        os.makedirs(badsrc)
        _st_html_pdf(os.path.join(badsrc, "Doe_Broken_2025.pdf"))
        code, so, se = run(["--src", badsrc, "--out", run_out, "--dpi", "72"])
        check("a run whose PDF could not be opened exits non-zero", code, 1)
        ok("...and says it is not an OCR problem",
           "not an OCR problem" in so)

        # `--dry-run` writes nothing at all, `--out` directory included.
        dry_out = os.path.join(tmp, "dry-out")
        code, so, se = run(["--src", src, "--out", dry_out, "--dpi", "72",
                            "--dry-run", "--mark-reviewed", "Doe_Figs_2025:1"])
        check("a dry run exits 0", code, 0)
        ok("a dry run creates no output directory", not os.path.exists(dry_out))
        ok("a dry run says it would record the mark", "Would record" in so)
        ok("a dry run says it is one", "Dry run" in so)

        # `--mark-reviewed` on a real run lands in the ledger inside --out.
        code, so, se = run(["--src", src, "--out", run_out, "--dpi", "72",
                            "--mark-reviewed", "Doe_Figs_2025:1"])
        ok("a real run records the mark", "Recorded as reviewed" in so)
        check("...in the ledger inside --out",
              ("Doe_Figs_2025", "1") in load_reviewed(
                  os.path.join(run_out, REVIEW_FILE)), True)

        # Execute the command the summary actually advertises. Losing ED or
        # a custom ledger used to create an extra S1 PNG and leave the original
        # warning unresolved. The same command must retain eligibility for an
        # explicitly included whole book and an unorganized source, while not
        # replaying --overwrite over a crop just repaired by hand.
        review_root = Path(tmp) / "review command"
        review_src = review_root / "sources"
        review_src.mkdir(parents=True)
        review_pdf = _st_tiny_fig_pdf(review_src / "Doe_Review_2025.pdf",
                                      "Extended Data Figure 1. Tiny.")
        _st_fig_pdf(review_src / "Doe_Review_2025_01_Chapter.pdf")
        _st_fig_pdf(review_src / "download (2).pdf")
        review_out = review_root / "images"
        custom_ledger = review_root / "custom ledger.txt"
        review_args = ["--src", str(review_src), "--out", str(review_out),
                       "--ed-prefix", "ED", "--review-file", str(custom_ledger),
                       "--dpi", "72", "--keep-frame", "--include-split-books",
                       "--allow-unorganized"]
        code, so, se = run(review_args + ["--overwrite"])
        check("the review-command fixture extracts all selected sources", code, 0)
        commands = [line.strip() for line in so.splitlines()
                    if line.strip().startswith(shlex.quote(sys.executable) + " ")
                    and "--mark-reviewed" in line]
        check("a flagged run advertises one complete review command", len(commands), 1)
        repaired_png = review_out / "Doe_Review_2025_fig_ED1.png"
        before_repair = repaired_png.read_bytes()
        manual = subprocess.run(
            [sys.executable, str(Path(__file__).resolve().with_name("extract_figures.py")),
             str(review_pdf), "--out", str(review_out), "--stem", review_pdf.stem,
             "--crop", "1:ED1:90,185,140,245", "--dpi", "96", "--no-trim", "--overwrite"],
            capture_output=True, text=True, encoding="utf-8", cwd=tmp)
        check("the advertised command is tested after a real manual repair",
              manual.returncode, 0)
        repaired_bytes = repaired_png.read_bytes()
        ok("the manual repair differs from the automatic crop",
           repaired_bytes != before_repair)
        if commands:
            argv = shlex.split(commands[0])
            replay = subprocess.run(
                argv, capture_output=True, text=True, encoding="utf-8", cwd=tmp)
            check("the printed command accepts the same selected source set",
                  replay.returncode, 0)
            ok("the review rerun includes the explicitly selected whole book",
               "Skipping Doe_Review_2025.pdf" not in replay.stdout
               and "already reviewed:" in replay.stdout)
            check("the printed command records the ED mark in the selected ledger",
                  load_reviewed(custom_ledger), {(review_pdf.stem, "ED1")})
            check("the review command creates no unintended default ledger",
                  (review_out / REVIEW_FILE).exists(), False)
            check("the review command creates no unintended supplementary figure",
                  (review_out / "Doe_Review_2025_fig_S1.png").exists(), False)
            check("recording a review preserves the repaired crop's bytes",
                  repaired_png.read_bytes(), repaired_bytes)
            ok("review commands retain geometry options but omit overwrite",
               "--keep-frame" in argv and "--dpi" in argv
               and argv[argv.index("--dpi") + 1] == "72"
               and "--overwrite" not in argv)
            code, so, se = run(review_args)
            check("the original context can be rerun successfully", code, 0)
            ok("the original context sees the recorded review",
               "already reviewed:" in so and "Suspicious bboxes:    0" in so)

        # Relative CLI paths must stay bound to the initial working directory.
        # A second directory deliberately has a different PDF at the same
        # relative name: replaying unbound paths used to succeed there, write
        # an unrelated image and ledger, and leave the original unreviewed.
        relative_home = Path(tmp) / "relative review command"
        alternate_home = relative_home / "elsewhere"
        relative_src = "source files"
        relative_out = "figure images"
        relative_ledger = "reviews/custom ledger.txt"
        (relative_home / relative_src).mkdir(parents=True)
        (alternate_home / relative_src).mkdir(parents=True)
        relative_pdf = _st_tiny_fig_pdf(
            relative_home / relative_src / "Doe_Relative_2025.pdf",
            "Extended Data Figure 1. Tiny.")
        _st_fig_pdf(alternate_home / relative_src / relative_pdf.name,
                    captions=("Extended Data Figure 1. Different source.",), fill=(1, 0, 0))
        relative_args = [sys.executable, os.path.abspath(__file__),
                         "--src", relative_src, "--out", relative_out,
                         "--review-file", relative_ledger, "--ed-prefix", "ED", "--dpi", "72"]
        initial = subprocess.run(
            relative_args, capture_output=True, text=True, encoding="utf-8",
            cwd=relative_home)
        check("relative input, output and ledger paths work on the original run",
              initial.returncode, 0)
        commands = [line.strip() for line in initial.stdout.splitlines()
                    if line.strip().startswith(shlex.quote(sys.executable) + " ")
                    and "--mark-reviewed" in line]
        check("a relative-path run advertises one review command", len(commands), 1)
        if commands:
            replay = subprocess.run(shlex.split(commands[0]), capture_output=True,
                                    text=True, encoding="utf-8", cwd=alternate_home)
            check("the relative-path review command succeeds from another cwd",
                  replay.returncode, 0)
            check("the relative-path review command updates the original ledger",
                  load_reviewed(relative_home / relative_ledger), {(relative_pdf.stem, "ED1")})
            check("the review command leaves the unrelated working directory untouched",
                  ((alternate_home / relative_out).exists(),
                   (alternate_home / "reviews").exists()), (False, False))
            check("bound paths retain ED and custom-ledger selection",
                  ((relative_home / relative_out / "Doe_Relative_2025_fig_S1.png").exists(),
                   (relative_home / relative_out / REVIEW_FILE).exists()), (False, False))
            repeated = subprocess.run(
                relative_args, capture_output=True, text=True, encoding="utf-8",
                cwd=relative_home)
            check("the original relative-path invocation still succeeds", repeated.returncode, 0)
            ok("the original relative-path invocation sees its review mark",
               "already reviewed:" in repeated.stdout and "Suspicious bboxes:    0" in repeated.stdout)


        code, so, se = run(["--out", run_out])
        check("a missing --src exits 2", code, 2)
        ok("...naming it", "--src" in se)
        code, so, se = run(["--src", src, "--out", run_out, "--dpi", "0"])
        check("a non-positive DPI exits 2", code, 2)
        ok("...explains the positive bound", "greater than zero" in se)
        code, so, se = run(["--src", src, "--out", run_out,
                            "--ed-prefix", "X"])
        check("an unsupported Extended Data namespace exits 2", code, 2)
        missing_out = Path(tmp) / "missing-source-output"
        code, so, se = run(["--src", os.path.join(tmp, "empty-dir"),
                            "--out", str(missing_out)])
        ok("a --src that does not exist is refused",
           code == 1 and "does not exist" in se)
        ok("a missing source creates no output or review sidecar",
           not missing_out.exists())

        empty_src = Path(tmp) / "empty-source"
        empty_src.mkdir()
        empty_out = Path(tmp) / "empty-output"
        code, so, se = run(["--src", str(empty_src), "--out", str(empty_out)])
        check("a valid empty source reports no work successfully", code, 0)
        ok("a valid empty source leaves no output directory",
           not empty_out.exists())
        empty_mark_out = Path(tmp) / "empty-mark-output"
        code, so, se = run([
            "--src", str(empty_src), "--out", str(empty_mark_out),
            "--mark-reviewed", "Doe_Missing_2025:1",
        ])
        ok("an empty source cannot silently ignore a requested review mark",
           code == 1 and "contains no PDFs" in se)
        ok("the impossible empty-scope mark leaves no output or ledger",
           not empty_mark_out.exists())

        non_pdf_src = Path(tmp) / "not-a-pdf.txt"
        non_pdf_src.write_text("not a source document", encoding="utf-8")
        non_pdf_out = Path(tmp) / "non-pdf-output"
        code, so, se = run(["--src", str(non_pdf_src),
                            "--out", str(non_pdf_out)])
        ok("a single non-PDF source file is refused explicitly",
           code == 1 and "not a PDF" in se)
        ok("a non-PDF source file leaves no output directory",
           not non_pdf_out.exists())

        wrong_mark_out = Path(tmp) / "wrong-review-stem"
        code, so, se = run([
            "--src", str(one), "--out", str(wrong_mark_out),
            "--mark-reviewed", "Doe_Typo_2025:1",
        ])
        ok("a review mark must name an exact source stem",
           code != 0 and "exact on-disk" in str(code))
        ok("a mistyped review stem leaves no output or ledger",
           not wrong_mark_out.exists())

        collision_src = Path(tmp) / "colliding-sources"
        for folder, name, fill in (("A", "Doe_Same_2025.pdf", (1, 0, 0)),
                                   ("B", "doe_same_2025.PDF", (0, 0, 1))):
            (collision_src / folder).mkdir(parents=True)
            _st_fig_pdf(collision_src / folder / name, fill=fill)
        collision_out = Path(tmp) / "colliding-output"
        collision_args = ["--src", str(collision_src), "--out", str(collision_out),
                          "--dpi", "72"]
        code, so, se = run(collision_args)
        check("all colliding source stems are refused with failure status", code, 1)
        check("neither colliding source publishes an image",
              sorted(collision_out.glob("*.png")), [])
        collision_mark_out = Path(tmp) / "colliding-review-output"
        code, so, se = run([
            "--src", str(collision_src), "--out", str(collision_mark_out),
            "--mark-reviewed", "Doe_Same_2025:1",
        ])
        ok("a same-stem collision cannot persist one ambiguous review mark",
           code != 0 and "uniquely identified" in str(code))
        ok("the ambiguous mark leaves no output or review ledger",
           not collision_mark_out.exists())
        _st_fig_pdf(collision_src / "Doe_Unique_2025.pdf", fill=(0, 1, 0))
        for extra in ([], ["--overwrite"]):
            code, so, se = run(collision_args + extra)
            check("a mixed run reports the refused source stems", code, 1)
            check("a mixed run still extracts only the unambiguous source",
                  sorted(p.name for p in collision_out.glob("*.png")),
                  ["Doe_Unique_2025_fig_1.png"])
            check("migration does not claim a colliding source's figures",
                  sorted(load_manifest(collision_out / MANIFEST_FILE)),
                  ["Doe_Unique_2025_fig_1.png"])

        # A one-file --src is only the requested extraction scope, not proof
        # that its stem is unique across the vault whose flat Images namespace
        # it would publish into. Exercise a case/extension variant outside the
        # selected folder, then the same collision in a mixed recursive run.
        vault = Path(tmp) / "vault-wide-collision"
        selected_dir = vault / "Sources" / "PDFs" / "selected"
        elsewhere = vault / "Archive"
        selected_dir.mkdir(parents=True)
        elsewhere.mkdir(parents=True)
        vault_collision = _st_fig_pdf(
            selected_dir / "Doe_VaultWide_2025.pdf", fill=(1, 0, 0))
        vault_other = _st_fig_pdf(
            elsewhere / "doe_vaultwide_2025.PDF", fill=(0, 0, 1))
        vault_unique = _st_fig_pdf(
            selected_dir / "Doe_OnlyHere_2025.pdf", fill=(0, 1, 0))
        vault_images = vault / "Sources" / "Images"

        for extra in ([], ["--overwrite"]):
            code, so, se = run([
                "--src", str(vault_collision), "--out", str(vault_images),
                "--dpi", "72",
            ] + extra)
            check("a single-file vault run refuses a same-stem PDF elsewhere",
                  code, 1)
            ok("the vault-wide refusal names both colliding source paths",
               str(vault_collision) in so and str(vault_other) in so)
            check("a refused single-file run creates no image namespace",
                  vault_images.exists(), False)

        code, so, se = run([
            "--src", str(vault_collision), "--out", str(vault_images),
            "--mark-reviewed", vault_collision.stem + ":1",
        ])
        ok("a vault-colliding source cannot write an ambiguous review mark",
           code != 0 and "uniquely identified" in str(code))
        check("the refused mark leaves the review ledger absent",
              (vault_images / REVIEW_FILE).exists(), False)

        code, so, se = run([
            "--src", str(selected_dir), "--out", str(vault_images),
            "--dpi", "72",
        ])
        check("a recursive subset reports a collision outside that subset",
              code, 1)
        check("the recursive run publishes only its vault-unique source",
              sorted(path.name for path in vault_images.glob("*.png")),
              ["Doe_OnlyHere_2025_fig_1.png"])
        check("the recursive manifest never claims the colliding stem",
              sorted(load_manifest(vault_images / MANIFEST_FILE)),
              ["Doe_OnlyHere_2025_fig_1.png"])

        external_out = Path(tmp) / "deliberate-external-one-off"
        code, so, se = run([
            "--src", str(vault_collision), "--out", str(external_out),
            "--dpi", "72",
        ])
        check("an explicit external one-file output keeps one-off behavior",
              code, 0)
        check("the external run publishes the selected PDF's figure",
              sorted(path.name for path in external_out.glob("*.png")),
              ["Doe_VaultWide_2025_fig_1.png"])

        for kind in ("read-only", "symlink"):
            protected = Path(tmp) / ("protected-" + kind)
            protected.mkdir()
            sidecar = protected / MANIFEST_FILE
            original = "# protected ownership records\n"
            if kind == "symlink":
                backing = Path(tmp) / "shared-ownership.tsv"
                backing.write_text(original, encoding="utf-8")
                sidecar.symlink_to(backing)
            else:
                sidecar.write_text(original, encoding="utf-8")
                sidecar.chmod(0o444)
            try:
                code, so, se = run(["--src", str(one), "--out", str(protected),
                                    "--dpi", "72", "--mark-reviewed", one.stem + ":1"])
                check("a %s manifest blocks before extraction" % kind, code, 1)
                check("blocked ownership cannot leave an untracked PNG",
                      list(protected.glob("*.png")), [])
                check("the protected sidecar remains untouched",
                      sidecar.read_text(encoding="utf-8"), original)
                check("ownership preflight also precedes writing review marks",
                      (protected / REVIEW_FILE).exists(), False)
            finally:
                if kind == "read-only":
                    sidecar.chmod(0o644)

        late_failure_out = Path(tmp) / "late-manifest-failure"
        from unittest.mock import patch

        def fail_manifest_write(*args, **kwargs):
            raise OSError("injected full filesystem")

        with patch.dict(globals(), write_manifest=fail_manifest_write):
            code, so, se = run(["--src", str(one), "--out", str(late_failure_out),
                                "--dpi", "72"])
        check("a late ownership-save failure cannot report success", code, 1)
        ok("the ownership-save failure names the recovery problem", "could not write" in se)
        ok("an ownership-save failure reports the crop as written, not missing",
           "Crops written but ownership records NOT persisted" in so
           and "Figures detected but NOT written" not in so)
        check("the crop named by that ownership failure remains on disk",
              sorted(path.name for path in late_failure_out.glob("*.png")),
              ["Doe_One_2025_fig_1.png"])

        damaged_src = Path(tmp) / "damaged-late-page"
        damaged_src.mkdir()
        damaged_pdf = damaged_src / "A_Damaged_2025.pdf"
        healthy_pdf = damaged_src / "B_Healthy_2025.pdf"
        _st_fig_pdf(damaged_pdf, fill=(1, 0, 0))
        _st_fig_pdf(healthy_pdf, fill=(0, 0, 1))
        damaged_out = Path(tmp) / "damaged-output"
        damaged_out.mkdir()
        (damaged_out / MANIFEST_FILE).write_text(MANIFEST_HEADER, encoding="utf-8")
        original_detect = detect_figures

        def fail_after_detection(doc):
            yield from original_detect(doc)
            if Path(doc.name) == damaged_pdf:
                raise ValueError("injected damaged later page")

        with patch.dict(globals(), detect_figures=fail_after_detection):
            code, so, se = run(["--src", str(damaged_src), "--out", str(damaged_out),
                                "--dpi", "72"])
        check("a damaged later page is reported as a failed PDF", code, 1)
        ok("the page failure names the source and preserves its partial result",
           "A_Damaged_2025.pdf" in se and "after 1 detected figure" in se)
        check("later PDFs are still processed after a page-analysis failure",
              sorted(p.name for p in damaged_out.glob("*.png")),
              ["A_Damaged_2025_fig_1.png", "B_Healthy_2025_fig_1.png"])
        check("completed crops retain ownership after a page-analysis failure",
              load_manifest(damaged_out / MANIFEST_FILE),
              {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
               for p in damaged_out.glob("*.png")})
        code, so, se = run(["--src", str(damaged_src), "--out", str(damaged_out),
                            "--dpi", "72"])
        check("a repaired PDF can be rerun without claiming its prior PNGs as foreign", code, 0)

        interrupted_out = Path(tmp) / "interrupted-output"
        interrupted_out.mkdir()
        (interrupted_out / MANIFEST_FILE).write_text(MANIFEST_HEADER, encoding="utf-8")

        def interrupt_after_detection(doc):
            yield from original_detect(doc)
            raise KeyboardInterrupt()

        interrupted = False
        with patch.dict(globals(), detect_figures=interrupt_after_detection):
            try:
                run(["--src", str(damaged_pdf), "--out", str(interrupted_out),
                     "--dpi", "72"])
            except KeyboardInterrupt:
                interrupted = True
        check("Ctrl-C still interrupts the batch", interrupted, True)
        check("Ctrl-C saves ownership for the crop already published",
              load_manifest(interrupted_out / MANIFEST_FILE),
              {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
               for p in interrupted_out.glob("*.png")})
        check("the interruption fixture really wrote a crop before stopping",
              len(list(interrupted_out.glob("*.png"))), 1)

        zero_cli = Path(tmp) / "Doe_Empty_2025.pdf"
        _st_zero_page_pdf(zero_cli)
        code, so, se = run(["--src", str(zero_cli), "--out", str(damaged_out)])
        check("a zero-page PDF cannot report successful extraction", code, 1)

        invalid_review_out = Path(tmp) / "invalid-review"
        invalid_review_out.mkdir()
        (invalid_review_out / REVIEW_FILE).write_text("malformed record\n", encoding="utf-8")
        code, so, se = run(["--src", str(one), "--out", str(invalid_review_out)])
        check("a malformed review ledger is an explicit failure", code, 1)
        check("review preflight happens before writing figures",
              list(invalid_review_out.glob("*.png")), [])
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
    p.add_argument(
        "--src",
        help=(
            "Source directory (walked recursively for *.pdf), or a single "
            ".pdf file."
        ),
    )
    p.add_argument(
        "--out",
        help="Output directory for cropped figure PNGs.",
    )
    p.add_argument(
        "--overwrite", action="store_true",
        help=("Re-extract existing PNGs only when their recorded ownership and "
              "current bytes match. Never claim an unknown or changed file."),
    )
    p.add_argument(
        "--adopt-legacy", action="append", default=[], metavar="STEM:FIG",
        help=("Record one exact complete PNG in an unrecorded figure slot as "
              "historical extractor output (repeatable). Existing manifest "
              "records remain authoritative. The stem must identify one "
              "eligible selected PDF; no files are adopted by default."),
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="Detect and report without writing PNGs, sidecars or output directories.",
    )
    p.add_argument(
        "--dpi", type=positive_int, default=250,
        help="Render resolution (default 250).",
    )
    p.add_argument(
        "--ed-prefix", choices=("S", "ED"), default="S",
        help=(
            "Filename prefix for 'Extended Data Figure N' captions "
            "(default 'S' — collapses into supplementary). Pass 'ED' to "
            "keep Extended Data figures in a distinct namespace (e.g., "
            "Nature papers that have both 'Supplementary Figure 1' AND "
            "'Extended Data Figure 1' as different figures)."
        ),
    )
    p.add_argument(
        "--keep-frame", action="store_true",
        help=(
            "Keep the publisher's figure frame (the thin rectangle around "
            "the figure in O'Reilly-style books). Default: strip the frame "
            "so it doesn't appear in the output PNG."
        ),
    )
    p.add_argument(
        "--include-split-books", action="store_true",
        help=(
            "Also extract from a book PDF whose chapter PDFs are in the same "
            "run. Default: skip the book, because its figures would be "
            "written a second time under the book's stem — byte-identical, "
            "never colliding, and permanently unused whichever stem an entry "
            "cites."
        ),
    )
    p.add_argument(
        "--allow-unorganized", action="store_true",
        help=(
            "Extract from PDFs whose filename pdf-organizer has not produced. "
            "Default: refuse them and name them, because every figure is keyed "
            "to the PDF's stem and a later rename orphans the whole set under "
            "a name nothing looks for — invisibly, since the figure glob and "
            "the unused-figure diagnostic walk that same stem."
        ),
    )
    p.add_argument(
        "--review-file", default=None,
        help=(
            f"Ledger of bboxes you have already checked, so they stop being "
            f"flagged every run. Default: {REVIEW_FILE} inside --out."
        ),
    )
    p.add_argument(
        "--mark-reviewed", action="append", default=[], metavar="STEM:FIG",
        help=(
            "Record that a flagged bbox has been checked (repeatable), e.g. "
            "--mark-reviewed Prince_UDL_2026_02_SupLearn:10-5. Appends to the "
            "review file and continues with the run."
        ),
    )
    p.add_argument("--test", action="store_true", help="run the self-test")
    args = p.parse_args(argv)

    if args.test:
        _require_pymupdf()
        return run_self_test()
    # Reported by name rather than left to argparse's `required=True`: with the
    # flags marked required, argparse rejects `--test` (which needs neither)
    # before `main()` can see it. Same shape and exit code as
    # `paper_scan.py`'s missing-argument path.
    missing = [f for f in ("src", "out") if not getattr(args, f)]
    if missing:
        print("missing required argument(s): %s"
              % ", ".join("--" + m for m in missing), file=sys.stderr)
        return 2
    _require_pymupdf()
    if args.adopt_legacy and args.overwrite:
        print("REFUSED: --adopt-legacy cannot be combined with --overwrite. "
              "First record and verify the exact historical crops without "
              "changing them; re-extract in a later run.", file=sys.stderr)
        return 2

    # Wire the CLI choice into the caption→prefix mapping used by
    # find_caption_blocks. Calling this unconditionally is fine — if the
    # user didn't pass --ed-prefix, the value is 'S' which matches the
    # default and is a no-op.
    configure_marker_prefix("Extended Data", args.ed_prefix)
    configure_strip_frame(not args.keep_frame)

    src_dir = os.path.expanduser(args.src)
    out_dir = os.path.expanduser(args.out)

    source = Path(src_dir)
    if not source.exists():
        print(f"REFUSED: --src does not exist: {src_dir}", file=sys.stderr)
        return 1
    if source.is_file() and source.suffix.lower() != ".pdf":
        print(f"REFUSED: --src is a file but not a PDF: {src_dir}",
              file=sys.stderr)
        return 1
    if not source.is_file() and not source.is_dir():
        print(f"REFUSED: --src is neither a PDF nor a directory: {src_dir}",
              file=sys.stderr)
        return 1
    pdfs = find_pdfs(src_dir)
    if not pdfs:
        if args.mark_reviewed:
            print("REFUSED: --mark-reviewed cannot be applied because this "
                  "--src scope contains no PDFs; no review record was written",
                  file=sys.stderr)
            return 1
        print(f"No PDFs found under {src_dir}")
        return 0

    # A flat vault image namespace is keyed only by PDF stem. A single-file
    # selection therefore still has to compare its source against every PDF
    # pathname in the selected vault, not merely against its one-item --src
    # scope. Arbitrary output folders deliberately keep one-off behavior.
    vault_root = output_vault_root(out_dir)
    try:
        vault_pdfs = find_vault_pdfs(vault_root) if vault_root is not None else []
    except (OSError, ValueError) as exc:
        print("REFUSED: could not inventory PDF basenames across the inferred "
              "vault %s: %s. No sidecar or figure was written." %
              (vault_root, exc), file=sys.stderr)
        return 1
    by_source_stem = source_stem_groups(pdfs, vault_pdfs)
    selected_collision_keys = {
        figure_identity(source.stem) for source in pdfs
        if len(by_source_stem[figure_identity(source.stem)]) > 1
    }

    # Validate ownership before writing a review mark, creating output, or
    # rendering a PNG. A protected or malformed ledger is not a fresh run.
    manifest_file = os.path.join(out_dir, MANIFEST_FILE)
    try:
        manifest, manifest_snapshot = load_manifest(manifest_file,
                                                    with_snapshot=True)
        manifest_existed = manifest_snapshot[0]
        if not args.dry_run:
            check_manifest_writable(manifest_file)
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"REFUSED: could not safely read {manifest_file}: {exc}. "
              "Repair the ownership records before extracting; no figures were written.",
              file=sys.stderr)
        return 1
    adoptable_stems = reviewable_stems(
        pdfs,
        include_split_books=args.include_split_books,
        allow_unorganized=args.allow_unorganized,
    )
    adoptable_stems -= {
        source.stem for source in pdfs
        if figure_identity(source.stem) in selected_collision_keys
    }
    try:
        adoptions = adopt_legacy_files(
            out_dir, args.adopt_legacy, adoptable_stems, manifest,
            manifest_existed)
    except (OSError, UnicodeError, ValueError) as exc:
        print("REFUSED: %s. No sidecar or figure was written." % exc,
              file=sys.stderr)
        return 1
    review_file = os.path.expanduser(
        args.review_file or os.path.join(out_dir, REVIEW_FILE))
    marked = []
    try:
        reviewed = load_reviewed(review_file)
        if args.mark_reviewed:
            allowed_review_stems = reviewable_stems(
                pdfs,
                include_split_books=args.include_split_books,
                allow_unorganized=args.allow_unorganized)
            allowed_review_stems -= {
                source.stem for source in pdfs
                if figure_identity(source.stem) in selected_collision_keys
            }
            marked = mark_reviewed(review_file, args.mark_reviewed,
                                   dry_run=args.dry_run,
                                   allowed_stems=allowed_review_stems)
            verb = "Would record" if args.dry_run else "Recorded"
            for stem, fig in marked:
                print(f"{verb} as reviewed: {stem} Fig {fig}  → {review_file}")
            print()
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"REFUSED: could not safely use {review_file}: {exc}. "
              "Repair the review records before extracting; no figures were written.",
              file=sys.stderr)
        return 1
    # A dry run wrote no ledger, but it still has to report what the real run
    # would report — otherwise the marks the user just passed come back as
    # fresh flags and the dry run disagrees with the run it is previewing.
    reviewed |= set(marked)
    # Every figure this script writes is keyed to the PDF's on-disk stem, and
    # nothing downstream survives that stem changing: a later rename orphans
    # the whole set under a name no consumer looks for, and neither the
    # figure glob nor the unused-figure diagnostic can report it, because both
    # walk the same stem (CONVENTIONS.md §1a). So a PDF that has not been
    # through pdf-organizer is refused rather than extracted — the ordering is
    # a constraint, not a preference, and this is the only place in the
    # pipeline positioned to enforce it.
    # A split book and its chapters are both in the walk, and extracting
    # both writes every figure twice under two stems. The chapter stem is
    # what everything downstream keys to, so the book is what gets skipped.
    #
    # THIS RUNS BEFORE THE REFUSAL BELOW, and the order is load-bearing.
    # `naming.py` deliberately recognises the legacy `<book>_src_NN_Name`
    # spelling as a chapter while `looks_canonical` rejects it, precisely so a
    # vault still holding those files gets its book skipped while the names are
    # being fixed. Refusing first removes those chapters from `pdfs`, the
    # pairing is never seen, and the book is extracted after all -- the doubled
    # figures the carve-out exists to prevent, on the default path.
    skipped_books = {} if args.include_split_books else split_book_chapters(pdfs)
    if skipped_books:
        pdfs = [p for p in pdfs if p not in skipped_books]

    unorganized = []
    if not args.allow_unorganized:
        unorganized = [p for p in pdfs if not looks_canonical(p.stem, is_stem=True)]
        pdfs = [p for p in pdfs if p not in set(unorganized)]

    # A flat image folder cannot distinguish PDFs sharing a stem. Detect the
    # conflict before either source can publish or claim that stem's images.
    # Otherwise the second source silently reuses the first one's PNGs, even
    # though the ownership manifest correctly records those exact bytes.
    stem_collisions = {}
    for source in pdfs:
        group = by_source_stem[figure_identity(source.stem)]
        if len(group) > 1:
            stem_collisions[figure_identity(source.stem)] = group
    if stem_collisions:
        print("REFUSED: filename stem collisions; no figures will be written for these PDFs:")
        for group in sorted(stem_collisions.values(), key=lambda paths: str(paths[0])):
            for source in group:
                print(f"  {source}")
        print("  Give each source a unique PDF stem with pdf-organizer, then re-run.")
        print()
        pdfs = [p for p in pdfs if figure_identity(p.stem) not in stem_collisions]

    if unorganized:
        print("REFUSED: %d PDF(s) whose filename pdf-organizer has not "
              "produced." % len(unorganized))
        print("  Every figure is named after the PDF's stem, so extracting "
              "now and renaming later")
        print("  orphans the whole set silently. Run pdf-organizer on these "
              "first:")
        for p in sorted(unorganized):
            print(f"    {p}")
        print("  Then re-run. To extract anyway, pass --allow-unorganized "
              "(the figures are then")
        print("  keyed to a name that is expected to change).")
        print()
    # The book-skip is reported even when the refusal above emptied the run.
    # It used to sit after an early `return`, so a vault holding legacy
    # chapter names printed the refusal and nothing else -- leaving the
    # operator to conclude the book had been processed, when in fact it was
    # correctly skipped and its chapters were correctly refused. Both halves
    # of that outcome have to be visible for it to be actionable.
    for book, chapters in sorted(skipped_books.items()):
        print(f"Skipping {book.name}: split into {len(chapters)} chapter PDF(s); "
              f"figures come from those (--include-split-books to override)")
    if (unorganized or stem_collisions) and not pdfs:
        if skipped_books:
            print()
        print("Nothing left to process.")
        # Non-zero: every PDF the user pointed at was refused, so nothing was
        # extracted. Exiting 0 there tells a caller — a shell `&&`, a wrapper
        # script, the model reading `$?` — that the figures are in the vault.
        return 1

    if not args.dry_run:
        os.makedirs(out_dir, exist_ok=True)

    print(f"Found {len(pdfs)} PDF(s) under {src_dir}")
    if args.dry_run:
        print("Dry run — no files will be written.")
    print()

    # One pass over figures already in --out makes byte-identical output from
    # an earlier run visible to duplicate detection. Ownership is independent:
    # no occupied name is claimed unless the caller selected its currently
    # unrecorded slot exactly with --adopt-legacy.
    seen_hashes = seed_output_index(out_dir)
    if adoptions:
        verb = "Would record" if args.dry_run else "Selected for recording"
        print(f"{verb} {len(adoptions)} explicitly selected legacy figure(s) "
              f"as this extractor's output in {manifest_file}:")
        for path, _filename, _snapshot in adoptions:
            print(f"  {path}")
        print()

    # An adoption describes bytes that already exist, so publish those claims
    # before extraction starts. A later crash must not erase them, and an
    # existing manifest does not prevent adding another explicitly selected,
    # previously unrecorded slot.
    adoptions_stable = True
    if adoptions and not args.dry_run:
        adoptions_stable = revalidate_legacy_adoptions(adoptions, manifest)
        if not adoptions_stable:
            return 1
        next_snapshot = save_manifest(
            manifest_file, manifest, expected=manifest_snapshot,
            return_snapshot=True)
        if not next_snapshot:
            return 1
        manifest_snapshot = next_snapshot

    manifest_commit_failed = [False]

    def commit_manifest():
        """Persist the ownership of the crop just published, with CAS."""
        nonlocal manifest_snapshot
        next_snapshot = save_manifest(
            manifest_file, manifest, expected=manifest_snapshot,
            return_snapshot=True)
        if not next_snapshot:
            manifest_commit_failed[0] = True
            raise OSError("the ownership manifest could not be updated")
        manifest_snapshot = next_snapshot

    chapter_reference_pdfs = (list(vault_pdfs)
                              if vault_root is not None else list(pdfs))
    chapter_caption_cache = {}
    per_pdf = {}
    try:
        for pdf_path in pdfs:
            # `--src` may be a single PDF, in which case relative_to() returns
            # "." (or raises, on an odd path) — neither is a useful label.
            try:
                rel = pdf_path.relative_to(src_dir)
                if str(rel) in (".", ""):
                    rel = pdf_path.name
            except ValueError:
                rel = pdf_path.name
            print(f"Processing: {rel}")
            result = process_pdf(
                pdf_path, out_dir,
                overwrite=args.overwrite, dpi=args.dpi, dry_run=args.dry_run,
                reviewed=reviewed, seen_hashes=seen_hashes, manifest=manifest,
                chapter_pdfs=chapter_reference_pdfs,
                chapter_caption_cache=chapter_caption_cache,
                manifest_commit=(None if args.dry_run else commit_manifest),
            )
            per_pdf[pdf_path] = result
            n = result["extracted"]
            s = result["skipped"]
            c = len(result["collisions"])
            w = len(result["warnings"])
            f = len(result["failures"])
            ownership_f = len(result.get("ownership_failures", ()))
            if result["open_error"]:
                print("  → could not be opened or fully read as a PDF (not an OCR problem)")
            elif result["no_pages"]:
                print("  → PDF has zero pages")
            elif not result["had_text"]:
                print("  → no extractable text (scanned PDF?)")
            elif not result["figures"]:
                print("  → no figure captions detected")
            else:
                parts = [f"{n} extracted"]
                if s:
                    parts.append(f"{s} skipped (already exist)")
                if c:
                    parts.append(f"{c} collision{'s' if c > 1 else ''}")
                if w:
                    parts.append(f"{w} flagged")
                if result["reviewed"]:
                    parts.append(f"{len(result['reviewed'])} flagged but reviewed")
                if result["duplicates"]:
                    parts.append(f"{len(result['duplicates'])} duplicate")
                if result["blank"]:
                    parts.append(f"{len(result['blank'])} blank crop")
                if result["occupied"]:
                    parts.append(f"{len(result['occupied'])} name(s) occupied by "
                                 f"another skill's file")
                if result["missing"]:
                    parts.append(
                        "PARTIAL: no caption for "
                        + ", ".join(f"Fig {m}" for m in result["missing"][:6]))
                if result.get("cross_chapter"):
                    parts.append(
                        "cross-chapter reference "
                        + ", ".join(
                            f"Fig {m}" for m in result["cross_chapter"][:6]))
                if f:
                    parts.append(f"{f} failed")
                if ownership_f:
                    parts.append(
                        f"{ownership_f} ownership save failed (crop exists)")
                print(f"  → {', '.join(parts)}")
            if manifest_commit_failed[0]:
                break

    finally:
        # Ownership is committed immediately after every crop and before the
        # next caption is processed. This finally block deliberately performs
        # no end-of-batch rewrite: a stale whole-run snapshot was the source of
        # lost concurrent updates and unowned crops after abrupt termination.
        manifest_saved = (not manifest_commit_failed[0]
                          and adoptions_stable)

    print_summary(per_pdf, out_dir, skipped_books, review_file, args.dry_run,
                  src_dir=src_dir, ed_prefix=args.ed_prefix, keep_frame=args.keep_frame,
                  include_split_books=args.include_split_books,
                  allow_unorganized=args.allow_unorganized, dpi=args.dpi)

    # The exit code has to say whether the run did what it was asked. It was
    # always 0 — a run that refused every PDF, could not open half of them, or
    # detected figures it then failed to write reported success, and anything
    # reading `$?` (a shell `&&`, a wrapper, the model) took the report's word
    # for it without reading the report. Three outcomes are failures:
    # refusals, files that could not be opened at all, figures detected but not
    # written, and crops whose ownership could not be persisted. A suspicious
    # bbox is NOT one of them — it is advisory, the
    # PNG is on disk, and `--mark-reviewed` is the answer to it.
    # A blank crop and an occupied output name join that list for the same
    # reason: in both, a figure was detected and is NOT in `--out` afterwards.
    # A caption inside a crop does not — the PNG is there, it is just wrong,
    # and it is reported the way every other suspicious bbox is.
    failed = any(r["failures"] or r.get("ownership_failures")
                 or r["open_error"] or r["no_pages"]
                 or r["blank"] or r["occupied"]
                 for r in per_pdf.values())
    return 1 if (unorganized or stem_collisions or failed or not manifest_saved) else 0


if __name__ == "__main__":
    # `sys.exit(main())`: `--test`, the missing-argument path and the
    # refusal/failure exit codes all report through the return value.
    sys.exit(main())
