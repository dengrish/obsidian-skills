"""Rename a source file (and everything keyed to its stem) and split books.

This is the machinery behind `pdf-organizer/SKILL.md`.  Two independent
halves, both importable and both runnable from the command line:

  * **Rename.**  `keyed_files` / `references` / `rename_all` — find every name
    derived from one source's stem (the file, its figures, its notes, its
    chapter folder and chapters), find every `.md` in the vault that cites any
    of them, and move the lot while rewriting every reference in one pass.
  * **Split.**  `split_book` — cut a book PDF into chapter PDFs, resolving
    every chapter before writing any of them.

Everything at module scope is stdlib.  `pypdf` is imported *inside*
`split_book`, so the rename half works in an environment that has no PDF
library at all, and importing this module has no side effects — which is what
`tests/test_conventions.py`'s `check_scripts_run` requires before it will
execute a bundled script.

Why this is a script and not a fenced block in SKILL.md: the four things a
model re-derives wrongly — `keyed_files`' four-way stem fan-out, the portable
case/normalization-folded symlink-safe vault walk, the boundary-anchored single-pass
rewrite, and `_norm`-based +/-2 page verification — are now covered by
`selftest` and compiled/imported by the plugin's test harness on every run.

Usage:
    # The reference check.  Run it before every rename.
    python3 organize.py check --vault '<vault>' \\
        '<vault>/Sources/PDFs/download.pdf'

    # Plan a rename (writes nothing), after inspecting the reference check.
    python3 organize.py rename --vault '<vault>' \\
        '<vault>/Sources/PDFs/download.pdf' \\
        --to Prince_UDL_2026.pdf

    # Apply it: the file, its figures, its notes, its chapter folder and
    # chapters all move, and every `.md` reference is rewritten with them.
    python3 organize.py rename ... --to Prince_UDL_2026.pdf --apply

    # Outside a vault (a Downloads inbox): omit --vault.  The vault-wide
    # checks are reported as not-run rather than silently skipped.
    python3 organize.py rename '<input-dir>/download(1).pdf' --to Smith_X_1776.pdf

    # Already in canonical form?  (Exit 0 = yes, 1 = no.)
    python3 organize.py canonical Prince_UDL_2026_02_SupLearn_src.pdf

    # Split a book.  chapters.json is a list of the chapter dicts described
    # in `references/book-splitting.md`; <run-temp> is unique to this run.
    python3 organize.py split --vault '<vault>' \\
        '<vault>/Sources/PDFs/Kuhn_StructSciRev_2012.pdf' \\
        --chapters '<run-temp>/chapters.json' \\
        --out '<vault>/Sources/PDFs/Kuhn_StructSciRev_2012'

    # The adversarial fixtures this module is held to.
    python3 organize.py selftest
"""
import argparse
import datetime
import errno
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import tempfile
import unicodedata
from urllib.parse import quote, unquote

_OBSIDIAN_SHARED_MODULES = (
    'atomic_move',
    'figure_state',
    'naming',
    'vault_artifacts',
    'yaml_scalars',
)

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

#: The filename shape is the plugin's, not this skill's: `pdf-figure-extractor`
#: reads the same rule to tell a book's chapters from the book.  It lives in
#: `shared/scripts/naming.py` and is imported, never restated — the two used to
#: hold separate copies and they disagreed about where `_src` sits, which cost
#: either every chapter's figures or a doubled set of them.  CONVENTIONS.md §1a.
from naming import (                       # noqa: E402  (after the bootstrap)
    CANONICAL,
    DISAMBIGUATOR,
    SAFE_NAME,
    chapter_book_stem,
    chapter_parts,
    core_stem,
    looks_canonical,
    split_tail,
)
from figure_state import (MANIFEST_FILE, REVIEW_FILE, rewrite_sidecar,
                          read_manifest, manifest_key, file_digest,
                          check_manifest_writable)  # noqa: E402
import atomic_move as _atomic_move          # noqa: E402
from atomic_move import (LinkUnavailable, MoveIncomplete, PublicationConflict,
                         file_identity, move_noreplace, publish_new,
                         remove_expected, replace_expected,
                         set_private_mode)  # noqa: E402
from vault_artifacts import inventory_source_figures  # noqa: E402
from yaml_scalars import parse_scalar, strip_comment  # noqa: E402

#: Folders never walked: VCS and editor state, and the trash, whose contents
#: are deleted notes that must not resurrect a "still referenced" verdict.
SKIP_DIRS = {".git", ".obsidian", ".trash", "node_modules"}

#: The character class that ends a filename token.  A name bounded by these on
#: both sides is a whole name and not a fragment of a longer one: it is what
#: keeps a rename of `Report_2020.pdf` away from `Other_Report_2020.pdf`.
#: The same class is used by `references()` and by `rewrite_text()` — they
#: MUST agree, and used not to: `references()` was a bare substring test, so
#: after the correct rename of `UDL_2026.pdf` to `Prince_UDL_2026.pdf` it
#: still found `UDL_2026.pdf` (inside the new name) and reported the repair as
#: incomplete.  Acting on that verdict is what doubled the prefix.
BOUNDARY = r"[A-Za-z0-9_.-]"

#: The longest basename any common filesystem accepts, in bytes.  Checked on
#: every DERIVED name, not just the one the user typed: a chapter is
#: `<new stem>_NN_ChapterName.pdf`, so a book name that fits can still produce
#: chapters that do not, and the failure would land halfway through the moves.
MAX_NAME_BYTES = 200


class SplitRefused(Exception):
    """Refusing to split, with a reason the user needs in words.

    A plain Exception, not SystemExit: a batch is a loop, and SystemExit would
    end the whole run at the first unreadable book (SKILL.md's batch workflow
    step 4).
    """


class Edits(dict):
    """{md path: new body}, plus the notes that could not be read at all.

    A plain dict to every caller — `plan_rename` and `rename_all` still return
    `(moves, edits, blockers)`, and everything that iterates it still sees
    note paths and bodies only.  `unreadable` rides alongside as an attribute
    rather than as an entry, because the one thing this mapping promises is
    that every key is a path this run may open: a non-UTF-8 note that cites
    nothing has no new body, is not an edit, and belongs in the report rather
    than in the write loop.
    """

    #: Set by `plan_rename`; a tuple of "<path> (<error class>)" strings.
    unreadable = ()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Keep the public dict note-only. These plugin-owned records are
        # displayed separately and join the same preflight/write/rollback.
        self.sidecars = {}
        # {path: (exact text, file identity)} captured by the plan. The apply
        # pass compares this again immediately before publication so an editor
        # save after the scan is never overwritten by the stale rewrite.
        self.expected = {}
        # {source path: (kind, identity-and-bytes snapshot)}. Regular files
        # carry a digest as well as inode identity; otherwise an in-place edit
        # after planning can be moved under a new stem while sidecar ownership
        # is rewritten for the older bytes.
        self.move_expected = {}
        # {owned note path: (old scalar, new scalar)} for the publication-date
        # changes included in this note rewrite. Kept out of the public dict so
        # every mapping entry remains a path/body pair, just like `sidecars`.
        self.published_updates = {}


class RenameFailed(OSError):
    """A rename that got part-way and was rolled back.

    `rolled_back` is False when the rollback itself failed — the one state
    this module cannot repair, and the one the message has to say out loud.
    """

    def __init__(self, message, rolled_back=True):
        OSError.__init__(self, message)
        self.rolled_back = rolled_back


class StaleRenamePlan(OSError):
    """A note or sidecar changed after its rewrite was computed."""

    def __init__(self, message, recovery_path=None, staging_path=None):
        OSError.__init__(self, message)
        self.recovery_path = recovery_path
        self.staging_path = staging_path


class InventoryFailed(OSError):
    """A directory could not be read completely enough to authorize writes."""


# ---------------------------------------------------------------------------
# walking the vault
# ---------------------------------------------------------------------------

def _walk(root):
    """`os.walk` with the skip list applied and symlink cycles cut.

    `followlinks=True` because a vault with a synced or shared subfolder is
    a symlink, `grep -r` skips it, and a reference living in there then reads
    as absent — the exact wrong answer for a check whose empty result
    authorises a rename.  The realpath set is what keeps a folder that links
    back into itself from walking forever.
    """
    def failed(exc):
        raise InventoryFailed(
            "cannot complete vault scan of %r: %s" %
            (getattr(exc, "filename", None) or root, exc)) from exc

    seen = set()
    for dirpath, dirnames, filenames in os.walk(
            root, followlinks=True, onerror=failed):
        real = os.path.realpath(dirpath)
        if real in seen:
            dirnames[:] = []
            continue
        seen.add(real)
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        yield dirpath, dirnames, filenames


def md_files(vault):
    """Every `.md` under `vault`, symlinked folders included."""
    for dirpath, _dirnames, filenames in _walk(vault):
        for f in filenames:
            if f.lower().endswith(".md"):
                yield os.path.join(dirpath, f)


def vault_names(vault):
    """{``_nfc_low`` basename: [paths]} for every file and folder in the vault.

    Vault-wide and folded to the plugin's portable name identity. A folder-local
    or literal-spelling check is not the uniqueness guarantee CONVENTIONS.md
    1a(1) promises across supported filesystems.

    Every path is kept, not the first one walked: a name that already exists
    TWICE is the case the user most needs spelled out, and `setdefault` used
    to hand the blocker whichever copy `os.walk` reached first — so the
    message named one arbitrary file and the user fixed that one, re-ran, and
    was stopped again by the copy it had not mentioned.
    """
    out = {}
    for dirpath, dirnames, filenames in _walk(vault):
        for f in filenames + dirnames:
            # `_nfc_low`, not bare `lower()`: an NFD twin and a derived NFC
            # destination share one portable collision identity.
            out.setdefault(_nfc_low(f), []).append(os.path.join(dirpath, f))
    return {low: sorted(paths) for low, paths in out.items()}


def _listdir(path):
    """`os.listdir`, or [] only when the optional directory is absent.

    An unreadable directory makes an ownership/collision inventory incomplete.
    Raise a typed error so the caller can turn that into a blocker rather than
    silently treating the directory as empty.
    """
    try:
        return os.listdir(path)
    except FileNotFoundError:
        return []
    except OSError as exc:
        raise InventoryFailed("cannot inventory %r: %s" % (path, exc)) from exc


def _nfc_low(name):
    """A filename reduced to the one spelling two of them are compared as.

    NFC first, then lowercased, identically on both sides of every comparison.
    This is the plugin's conservative portable identity: some filesystems alias
    case/normalization variants and others can store both, so raw comparison
    would produce different ownership and collision decisions by host. A name
    returned as NFD and a citation typed as NFC are byte-different despite
    representing the same spelling.

    That miss is not cosmetic where `keyed_files` uses it: a source stored NFC
    whose figures are stored NFD fans out to the source alone, the rename
    moves the document and orphans the figures under a stem nothing looks for,
    and `references()` — which is asked about the names the fan-out found —
    comes back empty and tells the caller to proceed.

    Not `casefold`: it maps `ß` to `ss`, which would key a figure named
    `Strasse_fig_1.png` to an unrelated `Straße.pdf` and rename a file that is
    nobody's.  Case folding belongs to `_ifold`, where a regex compiled `re.I`
    has already decided the two spellings are one.
    """
    return unicodedata.normalize("NFC", name).lower()


#: Folders holding a note whose *filename* is a source's stem.  Today that is
#: `Articles/` alone: it holds paper-summarizer's summary notes, which take the
#: PDF's stem, alongside clipping-processor's cleaned clippings, which do not.
#: A note folder missing from this tuple is a note the rename silently leaves
#: behind under a stem nothing looks for, so a vault reorganisation adds its
#: new folder here before it does anything else.
NOTE_DIRS = (("Articles",),)


#: The note's origin, in either shape it takes on disk.  The CURRENT schema
#: (CONVENTIONS.md 2b) is a block-form `sources:` list whose item 1 is the
#: origin; the scalar `source:` is the retired pre-rename shape, still read
#: as a fallback so an unmigrated note keeps its verdict.  Reading only the
#: scalar meant a current-schema note matched nothing, fell through to the
#: claimed-by-default branch, and a CLIPPING sharing a stem with the PDF was
#: renamed with it -- the exact failure `_note_is_about` exists to prevent.
#: All three anchored at the START of a frontmatter line -- not indented, so
#: a nested key under some other key cannot win over the real one.
_SOURCES_KEY = re.compile(r"\Asources\s*:\s*\Z", re.I)
_SOURCES_ITEM = re.compile(r"\A[ \t]*-(?:[ \t]+(.*))?\Z")
_SOURCE_LINE = re.compile(r"\Asource\s*:\s*(.*)\Z", re.I)

#: The document a `source:` wikilink names.  Obsidian resolves by basename, so
#: only the last path segment matters.
_SRC_LINK = re.compile(r"\A!?\[\[([^\]|#\r\n]+)(?:[#|][^\]\r\n]*)?\]\]\Z")


def _frontmatter_fence(line):
    """True for a column-zero YAML fence with optional trailing whitespace."""
    return line.rstrip("\r\n").rstrip(" \t") == "---"


_RAW_SRC_MARKER = re.compile(r"_src(?:_(?:%s))?\Z" % DISAMBIGUATOR)


def _existing_src_marker(stem):
    """Return an exact on-disk `_src` marker, including on raw intake names.

    ``split_tail`` deliberately assigns semantics only to canonical stems.
    The organizer also receives unorganized downloads, and its user contract
    says a literal legal `_src` tail already on such a name must survive the
    canonicalizing rename. Match only that exact tail shape; an interior
    ``src`` word or other suffix is ordinary title text.
    """
    marker = split_tail(stem)[1]
    return marker or ("_src" if _RAW_SRC_MARKER.search(stem) else "")


def _quoted_source_spans(text):
    """Quoted source scalars as (start, end, decoded value, quote style).

    Source ownership and reference repair must read the same YAML spelling:
    `Garc\\u00eda.pdf` and `O''Reilly.pdf` are filenames after decoding, not
    literal backslashes or doubled apostrophes. Other frontmatter and prose
    retain their original spelling.
    """
    start = len(text) - len(text.lstrip("\ufeff \t\r\n"))
    lines = text[start:].splitlines(keepends=True)
    if not lines or not _frontmatter_fence(lines[0]):
        return
    end = next((i for i in range(1, len(lines))
                if _frontmatter_fence(lines[i])), None)
    if end is None:
        return
    position = start + len(lines[0])
    in_sources = False
    for line in lines[1:end]:
        raw = line.rstrip("\r\n")
        scalar = None
        if raw.strip() and not raw.lstrip().startswith("#"):
            if in_sources:
                scalar = _SOURCES_ITEM.match(raw)
                if scalar is None:
                    in_sources = False
            if scalar is None:
                if _SOURCES_KEY.match(strip_comment(raw)):
                    in_sources = True
                else:
                    scalar = _SOURCE_LINE.match(raw)
            if scalar and scalar.group(1) is not None:
                encoded = scalar.group(1)
                try:
                    value, style = parse_scalar(encoded)
                except ValueError:
                    pass
                else:
                    if style in ("single", "double"):
                        clean = strip_comment(encoded)
                        left = len(clean) - len(clean.lstrip())
                        offset = position + scalar.start(1)
                        yield offset + left, offset + len(clean), value, style
        position += len(line)


_MARKDOWN_DESTINATION = re.compile(
    r"\]\([ \t]*(?:<(?P<angle>[^<>\r\n]+)>|(?P<bare>[^\s()<>]+))")


def _markdown_text_parts(text):
    """Decode local inline-link paths once, preserving their original spelling.

    Obsidian's Markdown links encode spaces and punctuation in PDF filenames.
    Match those decoded names with the same boundaries as wikilinks, without
    treating a literal `%20` inside a wikilink as a space or changing a URL.
    Query strings and page anchors stay outside the decoded path.
    """
    position = 0
    for match in _MARKDOWN_DESTINATION.finditer(text):
        group = "angle" if match.group("angle") is not None else "bare"
        target = match.group(group)
        if target.startswith("//") or re.match(r"[A-Za-z][A-Za-z0-9+.-]*:", target):
            continue
        path = re.split(r"[?#]", target, maxsplit=1)[0]
        try:
            decoded = unquote(path, errors="strict")
        except UnicodeError:
            continue
        if decoded == path and group == "bare":
            continue
        start, end = match.start(), match.start(group) + len(path)
        yield text[position:start], text[position:start], None
        # Complete wikilink boundaries let the existing qualification and
        # folder-removal checks see decoded spaces without treating them as
        # Markdown separators. Retain the original Markdown opening outside
        # this logical representation when encoding a changed path back.
        prefix = text[start:match.start(group)]
        yield text[start:end], "[[" + decoded + "]]", ("markdown", prefix)
        position = end
    yield text[position:], text[position:], None


def _source_text_parts(text):
    """Yield (original, decoded, style) chunks for one-pass link operations."""
    position = 0
    for start, end, value, style in _quoted_source_spans(text):
        yield from _markdown_text_parts(text[position:start])
        yield text[start:end], value, style
        position = end
    yield from _markdown_text_parts(text[position:])


def _map_source_text(text, transform):
    out = []
    for original, decoded, style in _source_text_parts(text):
        changed = transform(decoded)
        if changed == decoded:
            out.append(original)
        elif style == "single":
            out.append("'" + changed.replace("'", "''") + "'")
        elif style == "double":
            out.append(json.dumps(changed, ensure_ascii=False))
        elif isinstance(style, tuple) and style[0] == "markdown":
            # '%' is deliberately not safe: one URL decode must resolve a
            # literal percent in the filename, rather than decode it twice.
            out.append(style[1] + quote(changed[2:-2], safe="/:@!$&'*,;=+-._~"))
        else:
            out.append(changed)
    return "".join(out)


# External URIs are not vault references, even when their last path segment is
# the PDF being renamed. Cover hierarchical URLs, protocol-relative URLs and
# non-hierarchical schemes such as `mailto:`. Stop before brackets so an
# immediately adjacent wikilink remains independently repairable.
_EXTERNAL_URL = re.compile(
    r"(?<![A-Za-z0-9+.-])(?:[A-Za-z][A-Za-z0-9+.-]*:(?!:)|//)"
    r"[^\s<>\[\]\"]+")


def _external_url_spans(text):
    return [(m.start(), m.end()) for m in _EXTERNAL_URL.finditer(text)]


def _inside_span(position, spans):
    return any(start <= position < end for start, end in spans)


def _note_is_about(path, stem):
    """True when this note is a note ABOUT the document `stem` names.

    `Articles/` holds two kinds of note under one filename shape: a summary of
    a document (its origin is a wikilink to it) and a cleaned web clipping
    (its origin is a URL).  Only the first is derived from this document's
    name and may be carried along by its rename.  Renaming a clipping note
    because its slug happened to equal a PDF's stem breaks the dedup index
    that stops the user's polished note being clobbered on the next clipping
    run, and orphans that clipping's own figures.

    The origin is item 1 of the block-form `sources:` list (schema 2b, the
    shape both producers write today), with the retired scalar `source:` read
    as a fallback for unmigrated notes — the same two-key logic as
    clipping-processor's `dedup_index.read_source`.

    Unknown or malformed metadata establishes no ownership. A legacy note
    without a source field is accepted only when its entire body is an embed
    of this PDF; sharing a filename alone cannot make a user's note ours.
    """
    def _named(val):
        if not isinstance(val, str):
            return False
        val = val.strip()
        link = _SRC_LINK.match(val)
        if not link:
            return False
        base = link.group(1).strip().rstrip("/").split("/")[-1]
        return (os.path.splitext(base)[1].lower() == ".pdf"
                and _nfc_low(os.path.splitext(base)[0]) == _nfc_low(stem))

    def _legacy(body):
        body = body.strip()
        return body.startswith("![[") and _named(body)

    try:
        with open(path, encoding="utf-8-sig") as fh:
            body = fh.read().lstrip()
        lines = body.splitlines()
        if not lines or not _frontmatter_fence(lines[0]):
            return _legacy(body)
        end = next((i for i in range(1, len(lines))
                    if _frontmatter_fence(lines[i])), None)
        if end is None:
            return False
        source_values, sources_values = [], []
        sources_count, pending = 0, False
        for raw in lines[1:end]:
            if not raw.strip() or raw.lstrip().startswith("#"):
                continue
            if pending:
                pending = False
                item = _SOURCES_ITEM.match(raw)
                if item:
                    sources_values.append(parse_scalar(item.group(1))[0])
                    continue
            if re.match(r"\Asources\s*:", raw, re.I):
                sources_count += 1
                pending = bool(_SOURCES_KEY.match(strip_comment(raw)))
                continue
            source = _SOURCE_LINE.match(raw)
            if source:
                source_values.append(parse_scalar(source.group(1))[0])
        if sources_count:
            return (sources_count == 1 and len(sources_values) == 1
                    and _named(sources_values[0]))
        if source_values:
            return len(source_values) == 1 and _named(source_values[0])
        return _legacy("\n".join(lines[end + 1:]))
    except (OSError, UnicodeError, ValueError):
        return False


def _unquoted_source_claim(path, stem):
    """Whether malformed frontmatter visibly claims this PDF without quotes.

    A bare ``[[file.pdf]]`` is parsed by YAML as flow syntax, so it cannot
    establish ownership. Silently treating the same-stem note as unrelated is
    also unsafe: a rename would leave its source link behind. Surface the
    repair as an inventory blocker instead.
    """
    try:
        with open(path, encoding="utf-8-sig") as fh:
            lines = fh.read().splitlines()
    except (OSError, UnicodeError):
        return False
    if not lines or not _frontmatter_fence(lines[0]):
        return False
    end = next((i for i in range(1, len(lines))
                if _frontmatter_fence(lines[i])), None)
    if end is None:
        return False
    wanted = _nfc_low(stem)
    in_sources = False
    for raw in lines[1:end]:
        top_key = re.match(r"^([A-Za-z_][A-Za-z0-9_-]*)\s*:", raw)
        if top_key:
            in_sources = top_key.group(1).casefold() == "sources"
        match = re.match(
            r"^[ \t]*source\s*:[ \t]*"
            r"(!?\[\[[^\]\r\n]+\.pdf(?:#[^\]\r\n]*)?\]\])[ \t]*(?:#.*)?$",
            raw, re.I)
        if match is None and in_sources:
            match = re.match(
                r"^[ \t]*-[ \t]*"
                r"(!?\[\[[^\]\r\n]+\.pdf(?:#[^\]\r\n]*)?\]\])[ \t]*(?:#.*)?$",
                raw, re.I)
        if not match:
            continue
        target = match.group(1).lstrip("!")[2:-2].split("#", 1)[0]
        base = target.strip().rstrip("/").replace("\\", "/").rsplit("/", 1)[-1]
        if _nfc_low(os.path.splitext(base)[0]) == wanted:
            return True
    return False


_PUBLISHED_DATE = re.compile(r"\A([0-9]{4})-([0-9]{2})-([0-9]{2})\Z")
_TOP_LEVEL_KEY = re.compile(
    r"\A([A-Za-z_][A-Za-z0-9_-]*)([ \t]*):(.*)\Z")


def _canonical_year(stem):
    """Canonical source year (`YYYY` or `nd`), or None for an old junk stem."""
    if not looks_canonical(stem, is_stem=True):
        return None
    parts = core_stem(stem, is_stem=True).split("_")
    return parts[2] if len(parts) >= 3 else None


def _is_paper_summary_metadata(text):
    """Whether an owned note claims paper-summarizer publication metadata.

    Older source notes may consist only of a PDF embed or a legacy `source:`
    field. They still follow a source rename, but inventing a `published` field
    for them would silently convert a user note into a paper summary. A current
    summary is identifiable by its `published` key, even when that key is
    malformed, or by paper-summarizer's format enum when `published` is the
    missing field that must block the year repair.
    """
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        return False
    end = next((i for i in range(1, len(lines)) if lines[i] == "---"), None)
    if end is None:
        return False
    for line in lines[1:end]:
        if line.startswith((" ", "\t", "-")):
            continue
        match = _TOP_LEVEL_KEY.match(line)
        if not match:
            continue
        key = match.group(1)
        if key.casefold() == "published":
            return True
        if key == "format" and not match.group(2):
            try:
                value, style = parse_scalar(match.group(3))
            except ValueError:
                continue
            if style == "bare" and value in ("Paper", "Book", "Report"):
                return True
    return False


def _reconcile_published_year(text, target_year):
    """Rewrite one owned summary note's publication date for ``target_year``.

    Returns ``(text, old_surface, new_surface)``. The caller already proved
    that this note is owned by the renamed PDF and that its canonical year
    segment changes. This parser deliberately handles only the one top-level,
    single-line scalar accepted by paper-summarizer. Missing, duplicate,
    quoted, multiline, or invalid values raise ``ValueError`` so the rename
    transaction remains read-only.

    A dated target retains a valid existing month/day. A null value has no
    components to retain and becomes January 1, the summary schema's explicit
    padding rule. If carrying a month/day into the target year would make an
    impossible date (notably February 29 in a non-leap year), the source
    metadata is contradictory and requires another source-backed metadata
    decision rather than silently discarding those components.
    """
    if target_year != "nd" and not re.fullmatch(r"(?!0000)[0-9]{4}", target_year):
        raise ValueError("the target filename has no usable canonical year segment")

    lines = text.splitlines(keepends=True)

    def without_eol(line):
        return line.rstrip("\r\n")

    if not lines or without_eol(lines[0]) != "---":
        raise ValueError("frontmatter must open with `---` on line 1")
    end = next((i for i in range(1, len(lines))
                if without_eol(lines[i]) == "---"), None)
    if end is None:
        raise ValueError("frontmatter is not closed by a `---` line")

    candidates = []
    for index in range(1, end):
        line = without_eol(lines[index])
        if line.startswith((" ", "\t", "-")):
            continue
        match = _TOP_LEVEL_KEY.match(line)
        if match and match.group(1).casefold() == "published":
            candidates.append((index, match))
    if len(candidates) != 1:
        detail = "missing" if not candidates else "duplicated"
        raise ValueError("top-level `published` metadata is %s" % detail)

    index, match = candidates[0]
    if match.group(1) != "published" or match.group(2):
        raise ValueError("the publication key must use the exact `published:` schema")

    # Anything nested beneath this scalar makes its shape ambiguous. Comments
    # and blank separators are harmless; the next top-level key ends its value.
    for following in range(index + 1, end):
        candidate = without_eol(lines[following])
        if _TOP_LEVEL_KEY.match(candidate) and not candidate.startswith((" ", "\t", "-")):
            break
        if candidate.strip() and not candidate.lstrip().startswith("#"):
            raise ValueError("`published` has unsupported continuation content")

    raw = match.group(3)
    try:
        value, style = parse_scalar(raw)
    except ValueError as exc:
        raise ValueError("`published` is not a single valid YAML scalar (%s)" % exc) from exc
    if style != "bare":
        raise ValueError("`published` must be an unquoted date or YAML null")

    old_surface = strip_comment(raw).strip(" \t")
    if value is None:
        desired = "null" if target_year == "nd" else target_year + "-01-01"
    else:
        date_match = _PUBLISHED_DATE.fullmatch(value)
        if not date_match:
            raise ValueError("`published` must be a real YYYY-MM-DD date or YAML null")
        try:
            datetime.date(*(int(part) for part in date_match.groups()))
        except ValueError as exc:
            raise ValueError("`published: %s` is not a real date" % value) from exc
        if target_year == "nd":
            desired = "null"
        else:
            desired = target_year + "-" + date_match.group(2) + "-" + date_match.group(3)
            try:
                datetime.date(*(int(part) for part in desired.split("-")))
            except ValueError as exc:
                raise ValueError(
                    "the existing month/day %s cannot be preserved in target year %s"
                    % (value[5:], target_year)) from exc

    clean = strip_comment(raw)
    leading = clean[:len(clean) - len(clean.lstrip(" \t"))]
    suffix = raw[len(clean):]
    line = without_eol(lines[index])
    eol = lines[index][len(line):]
    lines[index] = "published:" + leading + desired + suffix + eol
    return "".join(lines), old_surface, desired


def keyed_files(vault, path, _seen=None):
    """Every file whose *name* is derived from `path`'s stem.

    The file itself, its figures in `Sources/Images/`, any note named after it in
    a `NOTE_DIRS` folder, and — if it is a split book — its chapter folder
    under `Sources/PDFs/` and every chapter, each keyed the same way in turn.
    Returns {absolute path: basename}. Matching uses `_nfc_low` throughout so
    a source and derived files have the same owner on every supported host,
    including when one spelling is NFC and another NFD.

    A probe that only looks for `OldName.pdf` misses all but the first.
    """
    seen = set() if _seen is None else _seen
    real = os.path.realpath(path)
    if real in seen:
        return {}
    seen.add(real)

    stem = os.path.splitext(os.path.basename(path))[0]
    low = _nfc_low(stem)
    out = {path: os.path.basename(path)}

    att = os.path.join(vault, "Sources/Images")
    for f in sorted(_listdir(att)):
        if _nfc_low(f).startswith(low + "_fig"):   # 8a: `_fig`, not `_fig_`
            out[os.path.join(att, f)] = f

    for parts in NOTE_DIRS:
        notedir = os.path.join(vault, *parts)
        for f in sorted(_listdir(notedir)):
            if _nfc_low(f) != low + ".md":
                continue
            note_path = os.path.join(notedir, f)
            if _note_is_about(note_path, stem):
                out[note_path] = f
            elif _unquoted_source_claim(note_path, stem):
                raise InventoryFailed(
                    "%s has an unquoted source wikilink for %s.pdf. Quote the "
                    "complete wikilink scalar, then re-run; malformed YAML "
                    "cannot establish safe note ownership." % (note_path, stem))

    src = os.path.join(vault, "Sources/PDFs")
    identity = _nfc_low(core_stem(stem, is_stem=True))
    for d in sorted(_listdir(src)):
        folder = os.path.join(src, d)
        if _nfc_low(core_stem(d, is_stem=True)) != identity or not os.path.isdir(folder):
            continue
        out[folder] = d
        for f in sorted(_listdir(folder)):
            book = chapter_book_stem(f)
            if (_nfc_low(f).startswith(low + "_")
                    or (book is not None and _nfc_low(book) == identity)):
                out.update(keyed_files(vault, os.path.join(folder, f), seen))
    return out


def _dirkey(path):
    """A vault-relative directory as one comparable key, or None.

    `/`-joined whatever the platform separator is, because a wikilink always
    spells its path that way; `.` and `..` collapsed here rather than by
    `os.path.normpath`, so that a `..` climbing ABOVE the vault root can be
    reported as None — it names nothing inside the vault, so it can be no
    keyed file's home.

    `_nfc_low` (NFC, then lowercased) rather than `_name_variants`'
    carry-every-spelling trick: that one feeds a regex, which matches literal
    text and so has to hold each form, while this is a set-membership test,
    where normalising both sides to one canonical form settles NFD-on-disk vs
    NFC-in-note outright. Lowercasing keeps the same portable identity used by
    `keyed_files`.

    Each segment is stripped, because one side of the comparison is text a
    human typed inside a wikilink: Obsidian resolves `[[ Articles/UDL_2026 ]]`
    exactly as it resolves the unpadded form, so a leading space that survives
    into the key makes the padded link name a directory the vault does not
    have — and an unmatched directory is read as "names a different file", so
    the reference is dropped and the rewrite leaves the link behind.
    """
    parts = []
    for seg in path.replace(os.sep, "/").split("/"):
        seg = seg.strip()
        if seg in ("", "."):
            continue
        if seg == "..":
            if not parts:
                return None                  # above the vault root
            parts.pop()
            continue
        parts.append(seg)
    return _nfc_low("/".join(parts))


def keyed_dirs(vault, keyed):
    """{basename: {vault-relative directory}} for a `keyed_files` result.

    The path information `references()` and `rewrite_text()` need to tell a
    link that names a keyed file from one that merely spells its basename.  A
    bare `[[UDL_2026]]` resolves by basename vault-wide and so names the keyed
    note wherever it lives; `[[Wiki/Sub/UDL_2026]]` names one exact path, and
    beside a keyed `Articles/UDL_2026.md` that path is a DIFFERENT
    file — see `_qualifies`.

    Taken from `keyed_files`' own output, so these are the directories the
    files occupy and not a guess.  Survives the rename it authorises: a rename
    changes basenames and never directories, so the same mapping is still the
    right one for the post-rename `references(vault, old)` check.
    """
    out = {}
    for p, b in keyed.items():
        key = _dirkey(os.path.relpath(os.path.dirname(p), vault))
        if key is not None:              # outside the vault: no link names it
            out.setdefault(b, set()).add(key)
    return out


# ---------------------------------------------------------------------------
# finding, and rewriting, references
# ---------------------------------------------------------------------------

def _name_variants(name):
    """`name` plus its other Unicode normalisation, lowercased.

    A filename stored NFD (what macOS hands back from `os.listdir`) and cited
    NFC inside a note are byte-different and literally will not match, which
    is invisible in every rendering of both.  Matching both forms costs one
    extra alternative per name; missing one reports a referenced file as free
    to rename.  Output names are ASCII, where the two forms coincide, so this
    only ever matters for the ugly input names this skill exists to replace.
    """
    out = {name.lower()}
    for form in ("NFC", "NFD"):
        out.add(unicodedata.normalize(form, name).lower())
    return out


def _alternation(names):
    """A regex alternation over `names`, longest first.

    Longest first is what makes the alternation a single pass rather than a
    sequence of them: at any position the longest whole name wins, so a
    chapter-folder key (`Prince_UDL_2026`) can never claim the opening of a
    chapter filename (`Prince_UDL_2026_01_Intro.pdf`) out from under it.
    """
    return "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True))


def _lookup(names):
    """{every lowercased spelling: canonical name} for a set of basenames."""
    lut = {}
    for n in names:
        for v in _name_variants(n):
            lut[v] = n
    return lut


def _ifold(text):
    """`text` reduced to the spelling `re.I` treats as one.

    `str.casefold` over `_nfc_low`'s NFC, because `re.I`'s equivalence classes
    are WIDER than `str.lower()`'s: MICRO SIGN `µ` (U+00B5) matches GREEK
    SMALL LETTER MU `μ` (U+03BC), `ſ` matches `s`, `ς` matches `σ`.  A pattern
    built from one spelling therefore matches the other, and the matched text
    is then a key no `_name_variants` spelling holds.

    Only ever used to look a match back up (`_canonical_name`), never to build
    the alternation: casefolding `Straße` gives `strasse`, which as a regex
    alternative would match an unrelated `Strasse.pdf` and report it as a
    reference to a file it has nothing to do with.
    """
    return _nfc_low(text).casefold()


def _canonical_name(lut, text):
    """The name `lut` holds for the matched `text`, or `text` unrecognised.

    Both call sites used to index `lut` directly with `text.lower()`.  In
    `references()` — the guard that authorises every rename, and on `--apply`
    the one that runs AFTER the writes — that was a bare `KeyError` traceback
    for any spelling `re.I` unifies and `str.lower()` does not: a note citing
    `[[μ_2001.pdf]]` beside a `µ_2001.pdf` on disk was enough.  In
    `rewrite_text` the same lookup was a `.get()` that degraded to silence.

    Exact spelling first, so a folded collision can never outrank a name
    spelled the way `_name_variants` recorded it; `_ifold` second, which
    settles the pairs case folding unifies.  A spelling neither resolves —
    `ı` against `i`, which `re.I` matches and `casefold` leaves apart — is
    handed back as it was found, and both callers do the conservative thing
    with it: `_qualifies_qual` has no directory for an unknown name so it
    counts as a reference, and `rewrite_text` maps it to itself and leaves the
    text alone.
    """
    hit = lut.get(text.lower())
    if hit is not None:
        return hit
    folded = _ifold(text)
    # Linear, and only on the miss path: `lut` holds one rename's keyed names.
    return next((n for v, n in lut.items() if _ifold(v) == folded), text)


def _reference_re(names):
    """Match any of `names` as a whole filename, or as a wikilink target.

    Two branches.  The first is a boundary-anchored full basename anywhere in
    the text — a `sources:` entry, an embed, prose.  The second is a wikilink
    to a markdown note, which carries no extension: `[[beta-concept]]`
    resolves to `beta-concept.md`, so a probe matching basenames alone is
    blind to every reference to a `.md` file.
    """
    lut = _lookup(names)
    stems = {os.path.splitext(n)[0]: n
             for n in names if n.lower().endswith(".md")}
    # Every spelling of a stem maps to the FILENAME, not back to the stem:
    # `references()` reports what it found as a name on disk, and the
    # self-reference discard below compares against a basename.
    slut = {}
    for stem, name in stems.items():
        for v in _name_variants(stem):
            slut[v] = name
    parts = [r"(?<!%s)(?P<name>%s)(?!%s)" % (BOUNDARY, _alternation(lut), BOUNDARY)]
    if stems:
        # The `open` group swallows an optional folder qualification, and the
        # rewrite puts it back verbatim — only the stem is replaced.
        #
        # It used to require `[[` IMMEDIATELY before the stem, which sees only
        # Obsidian's default "shortest path that is unique" link format.  Set
        # *New link format* to "Absolute path in vault" or "Relative path to
        # file" and every link is written `[[Articles/UDL_2026]]` —
        # invisible to this pattern.  That is not a cosmetic miss: it made
        # `references()` return {} for a file the vault does cite, so the
        # pre-rename check said "rename immediately", the rewrite left the
        # link alone, and references/rename-repair.md's post-rename verification
        # passed on a vault the rename had just broken.  The one guard with no
        # downstream safety net certified the damage as repaired.
        #
        # The terminator set includes a backslash for the reason `_debase_res`
        # says it does: inside a markdown table Obsidian escapes the display
        # pipe (`[[Articles/UDL_2026\|label]]`), and a lookahead of `[\]|#]`
        # alone matched no link in any table in the vault.  The two patterns
        # MUST agree, and did not -- so a summary note cited only from a table
        # was reported unreferenced, renamed, and left both links dangling,
        # with the post-rename re-probe blind to them by the same omission.
        # The `[ \t]*` on either side is the same class of miss one layer out:
        # `[[ UDL_2026 ]]` is padding Obsidian resolves through, so a pattern
        # that cannot see it reports a cited note as free to rename.
        parts.append(r"(?P<open>!?\[\[[ \t]*(?:[^\[\]|#\n]*/[ \t]*)?)"
                     r"(?P<stem>%s)(?=[ \t]*[\]\\|#])" % _alternation(slut))
    return re.compile("|".join(parts), re.I), lut, slut, stems


def _stem_match(m):
    """The wikilink-stem text of `m`, or None when `m` is a whole basename.

    The stem branch is absent from the pattern entirely when no markdown note
    is in play, so its group has to be probed rather than read.
    """
    if "stem" not in m.re.groupindex:
        return None
    return m.group("stem")


def _link_dirs(open_text, note_dir):
    """Every vault-relative directory a wikilink's `open` group could name.

    `open_text` is the match's `open` group — `[[` or `![[`, optionally
    followed by a folder qualification.  None when there is no qualification:
    a bare `[[Stem]]` resolves by basename vault-wide, so it names its file
    wherever that file lives and there is no path to check.

    TWO candidates, not one, because Obsidian writes two path formats and the
    link text does not say which: *Absolute path in vault* writes
    `Articles/Stem`, while *Relative path to file* writes
    `../Articles/Stem` climbing out of a folder but a bare
    `Articles/Stem` going into one — the same spelling as the absolute form.
    Obsidian resolves a qualified link against the vault root AND against the
    citing note's own folder, so both readings are tried here.  Accepting only
    the vault-root one would drop a real reference on every vault set to the
    relative format, which is the exact miss the folder-qualified branch was
    added to close.
    """
    qual = open_text.lstrip("!")[2:].rstrip("/")     # drop `!`, `[[`, the `/`
    if not qual:
        return None
    return {k for k in (_dirkey(qual), _dirkey(note_dir + "/" + qual))
            if k is not None}


#: A folder qualification sitting immediately before a matched basename, in
#: either syntax: `[[Sources/PDFs/` or `](Sources/PDFs/`.  Anchored at the end
#: so it only matches when it abuts the name.  The basename branch of
#: `_reference_re` has no `open` group -- it matches a full filename anywhere,
#: including in prose -- so the qualification has to be read off the text.
_QUAL_BEFORE = re.compile(r"(?:!?\[\[|\]\()(?!\w+:)([^\[\]()\n|#]*/)\Z")


def _qual_before(body, start):
    """The folder qualification abutting a basename match, or None."""
    m = _QUAL_BEFORE.search(body, max(0, start - 400), start)
    return m.group(1) if m else None


def _qualifies_qual(qual, name, dirs, note_dir):
    """`_qualifies`, given the qualification text rather than a match."""
    if dirs is None:
        return True
    want = dirs.get(name)
    if not want:
        return True
    if not qual:
        return True                      # bare: resolves by basename vault-wide
    got = {k for k in (_dirkey(qual.rstrip("/")),
                       _dirkey(note_dir + "/" + qual.rstrip("/")))
           if k is not None}
    return not got or bool(got & want)


def _qualifies(m, name, dirs, note_dir):
    """Does this wikilink match actually name the keyed file `name`?

    A bare `[[Stem]]` does: Obsidian resolves it by basename across the whole
    vault, which is the keyed file.  A folder-qualified `[[folder/Stem]]` names
    that one path, so it does ONLY when the keyed file lives there.

    The qualification used to be swallowed and echoed back unread, so a note
    citing `[[Wiki/Sub/UDL_2026]]` beside a keyed `Articles/UDL_2026.md`
    was reported as citing the keyed note and rewritten to
    `[[Wiki/Sub/Prince_UDL_2026]]` — a link to nothing, because `Wiki/Sub/` is
    not what the rename touched.  Worse than the dangling link: the same
    permissive test then stopped seeing that link, so references/rename-repair.md's post-rename
    `assert not references(vault, old)` passed.  The one guard with no
    downstream safety net certified the break as repaired.

    `dirs` is optional, and absent means the old permissive answer: every
    qualification is taken at its word.  `rewrite_text` is documented as usable
    standalone — the self-test calls it with a bare {old: new} map and no vault
    — and with no path information there is nothing to check.  A name `dirs`
    holds no entry for is the same case: unlocated, so unjudgeable, so counted
    as a reference exactly as before.
    """
    if dirs is None:
        return True
    want = dirs.get(name)
    if not want:
        return True
    got = _link_dirs(m.group("open"), note_dir)
    return got is None or bool(got & want)


def references(vault, names, dirs=None, directory_names=()):
    """{note path: [names it cites]} across every `.md` in the vault.

    Bounded on both sides, exactly like the rewrite: `Report_2020.pdf` does
    NOT match inside `Other_Report_2020.pdf`, and `UDL_2026.pdf` does NOT
    match inside `Prince_UDL_2026.pdf`.  A substring test gets both of those
    wrong, in both directions — before a rename it reports an unreferenced
    file as referenced and the rename is refused; after one it reports a
    finished repair as incomplete, and "finishing" it is what doubles the
    prefix on every link in the vault.

    `dirs` is `keyed_dirs(vault, keyed)`: where the keyed files actually live,
    which is what decides whether a folder-qualified wikilink names one of them
    or a different file of the same basename (`_qualifies`).  Omitting it keeps
    the old permissive answer — every qualification is taken at its word.
    """
    directory_keys = {_nfc_low(name) for name in directory_names}
    names = {n for n in names if n and _nfc_low(n) not in directory_keys}
    if not names:
        return {}
    pat, lut, slut, _stems = _reference_re(names)
    hits = {}
    for md in md_files(vault):
        try:
            occupant = os.stat(md, follow_symlinks=False)
            if stat.S_ISLNK(occupant.st_mode):
                raise InventoryFailed(
                    "leaf Markdown path %r is a symlink; its target is not an "
                    "editable file owned by this vault scan" % md)
            if not stat.S_ISREG(occupant.st_mode):
                raise InventoryFailed(
                    "leaf Markdown path %r is not a regular file" % md)
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(md, flags)
            with os.fdopen(descriptor, "r", encoding="utf-8",
                           errors="replace") as fh:
                opened_before = os.fstat(fh.fileno())
                if _file_identity(occupant) != _file_identity(opened_before):
                    raise InventoryFailed(
                        "leaf Markdown path %r changed while it was opened" % md)
                body = fh.read()
                opened_after = os.fstat(fh.fileno())
            final = os.stat(md, follow_symlinks=False)
            # Windows can expose stable metadata differently through a path
            # stat and an open handle.  Compare each view with itself, then
            # bind the two views with the portable file identity.
            if not (_change_identity(occupant) == _change_identity(final)
                    and _change_identity(opened_before)
                    == _change_identity(opened_after)
                    and _file_identity(occupant)
                    == _file_identity(opened_before)
                    and _file_identity(final) == _file_identity(opened_after)):
                raise InventoryFailed(
                    "leaf Markdown path %r changed while it was read" % md)
        except InventoryFailed:
            raise
        except OSError as exc:
            raise InventoryFailed("cannot read Markdown note %r during the "
                                  "reference scan: %s" % (md, exc)) from exc
        note_dir = os.path.relpath(os.path.dirname(md), vault)
        found = set()
        for _original, part, _style in _source_text_parts(body):
            urls = _external_url_spans(part)
            for m in pat.finditer(part):
                if _inside_span(m.start(), urls):
                    continue
                stem = _stem_match(m)
                if stem is not None:
                    name = _canonical_name(slut, stem)
                    if _qualifies(m, name, dirs, note_dir):
                        found.add(name)
                else:
                    name = _canonical_name(lut, m.group("name"))
                    if _qualifies_qual(_qual_before(part, m.start("name")),
                                       name, dirs, note_dir):
                        found.add(name)
        found.discard(os.path.basename(md))           # a note naming itself
        if found:
            hits[md] = sorted(found)
    return hits


#: A folder-qualified reference to one specific basename, in either syntax the
#: vault uses.  The folder segment is the middle group and is what gets
#: dropped.  Two patterns rather than one because the two syntaxes end
#: differently, and a form matched by the *rewrite* but missed here is left
#: pointing at the folder the file just left.
#:
#: The wikilink terminator set includes a backslash: inside a markdown table
#: Obsidian escapes the display pipe (`[[Dir/Name\|label]]`), so a lookahead of
#: `[\]|#]` alone silently skips every link in a table -- and the post-rename
#: re-probe cannot catch it, because it searches for the OLD name and this link
#: already carries the new one.  The folder class forbids `[` for the reason
#: `_reference_re` does: a `[` inside it means the match started in the wrong
#: place.
def _debase_res(name):
    esc = re.escape(name)
    # The markdown-link folder class must not swallow a scheme: a bare
    # `[^()\s]*` matched `https://example.org/papers/` and turned a working
    # URL into a bare filename.  This one is keyed on the NEW basename, so no
    # reference check can see it -- the pre-rename probe searches old names and
    # finds nothing, and the post-rename assert searches old names and passes.
    # It fires on the "refs empty -> rename immediately" path, silently.
    #
    # The wikilink terminator carries `[ \t]*` for the reason `_reference_re`'s
    # stem branch does: Obsidian resolves `[[ Sources/PDFs/X.pdf ]]` through
    # the padding, so the rewrite renames inside it and this pattern, without
    # the padding, then declined to drop the folder the file had just left --
    # the "matched by the rewrite, missed here" split this comment already
    # warns about, keyed on the NEW name where no reference check can see it.
    # The markdown form gets no such tolerance: a space before `)` is part of
    # the target, not padding a renderer looks past.
    uri_guard = r"(?![A-Za-z][A-Za-z0-9+.-]*:|//)"
    return (re.compile(r"(!?\[\[)(%s[^\[\]\n|#]*/)(%s)(?=[ \t]*[\]\\|#])"
                       % (uri_guard, esc)),
            re.compile(r"(\]\()(%s[^()\s\n]*/)(%s)(?=[)#])"
                       % (uri_guard, esc)))


def debase_links(text, names):
    """Drop the folder from every qualified wikilink naming one of `names`.

    Called only when a rename MOVED the file to a different folder.  The
    qualification in a note's link is the file's OLD folder, and rewriting the
    name inside it produces a link that resolves to nothing — a working link
    turned dangling, silently, which is the failure `_qualifies` exists to
    prevent in the other direction.  The bare form is always right instead:
    Obsidian resolves it by basename vault-wide, and §1a guarantees this
    plugin's basenames are unique, which is why `source:` and `sources:` are
    specified bare in the first place (`CONVENTIONS.md` §6, §7).

    Rewriting the folder rather than dropping it is not an option worth taking:
    a link may be absolute, `./`-relative or `../`-relative to whichever note
    cites it, so "the new folder" is a different string per note and getting
    one wrong is the same dangling link with more machinery behind it.
    """
    def debase(part):
        for name in sorted(names, key=len, reverse=True):
            if name:
                for rx in _debase_res(name):
                    part = rx.sub(r"\1\3", part)
        return part

    return _map_source_text(text, debase)


def _rewrite_directory_paths(original, rewritten, directory_ren):
    """Rename owned directory segments only in links to a renamed child.

    Directory basenames are not globally unique in a vault.  A split-book
    folder named ``Doe_Book_2025`` can coexist with an unrelated folder of the
    same name elsewhere, so matching that segment alone is not ownership.  The
    ordinary reference pass has already qualified the terminal filename against
    ``keyed_dirs``.  Use its actual before/after change as the evidence that a
    link names one of the renamed folder's children; a link whose terminal
    target did not change must retain every directory segment verbatim.
    """
    if not directory_ren:
        return rewritten
    lookup = {_nfc_low(old): new for old, new in directory_ren.items()}

    def target(before, after):
        if (not after or after.startswith("//")
                or re.match(r"[A-Za-z][A-Za-z0-9+.-]*:", after)):
            return after

        def split(value):
            split_at = min((index for marker in ("|", "#")
                            if (index := value.find(marker)) >= 0),
                           default=len(value))
            return value[:split_at], value[split_at:]

        old_path, _old_suffix = split(before)
        new_path, new_suffix = split(after)
        old_pieces = old_path.split("/")
        new_pieces = new_path.split("/")
        if (len(old_pieces) != len(new_pieces) or len(new_pieces) < 2
                or old_pieces[-1].strip() == new_pieces[-1].strip()):
            return after
        for index in range(len(new_pieces) - 1):
            # Filename rewriting never changes a qualification.  If another
            # transform did, decline the directory rewrite rather than infer
            # that two differently qualified paths name one folder.
            if (_nfc_low(old_pieces[index].strip())
                    != _nfc_low(new_pieces[index].strip())):
                return after
        for index in range(len(new_pieces) - 1):
            stripped = old_pieces[index].strip()
            replacement = lookup.get(_nfc_low(stripped))
            if replacement is not None:
                leading = new_pieces[index][
                    :len(new_pieces[index]) - len(new_pieces[index].lstrip())]
                trailing = new_pieces[index][len(new_pieces[index].rstrip()):]
                new_pieces[index] = leading + replacement + trailing
        return "/".join(new_pieces) + new_suffix

    wiki = re.compile(r"(?P<open>!?\[\[)(?P<target>[^\]\r\n]+)(?P<close>\]\])")
    original_wiki = list(wiki.finditer(original))
    rewritten_wiki = list(wiki.finditer(rewritten))
    if len(original_wiki) == len(rewritten_wiki):
        before = iter(original_wiki)
        rewritten = wiki.sub(
            lambda match: (match.group("open")
                           + target(next(before).group("target"),
                                    match.group("target"))
                           + match.group("close")), rewritten)

    def markdown(match):
        before_match = next(original_markdown_iter)
        group = "angle" if match.group("angle") is not None else "bare"
        before_group = ("angle" if before_match.group("angle") is not None
                        else "bare")
        if group != before_group:
            return match.group(0)
        original = match.group(0)
        value = match.group(group)
        changed = target(before_match.group(before_group), value)
        if changed == value:
            return original
        start = match.start(group) - match.start()
        end = start + len(value)
        return original[:start] + changed + original[end:]

    original_markdown = list(_MARKDOWN_DESTINATION.finditer(original))
    rewritten_markdown = list(_MARKDOWN_DESTINATION.finditer(rewritten))
    if len(original_markdown) == len(rewritten_markdown):
        original_markdown_iter = iter(original_markdown)
        rewritten = _MARKDOWN_DESTINATION.sub(markdown, rewritten)
    return rewritten


def rewrite_text(text, ren, stem_ren, dirs=None, note_dir="",
                 directory_ren=None):
    """Apply every old -> new basename to `text` in ONE pass.

    `ren` is {old basename: new basename}; `stem_ren` is {old stem: new stem}
    for the markdown notes among them, used for extensionless wikilinks.

    `dirs` is `keyed_dirs(vault, keyed)` and `note_dir` is the vault-relative
    folder of the note being rewritten — together they say which
    folder-qualified wikilinks name a renamed file rather than a different file
    of the same basename (`_qualifies`).  BOTH branches are checked, the
    wikilink stem and the full basename alike, and with the same calls
    `references()` makes: a qualification this rewrite would follow but that
    probe would not is a link repointed at a document the user never named.
    Both arguments are optional: this function is documented as usable
    standalone, on a bare {old: new} map with no vault behind it, and with no
    path information it rewrites every qualification as it always did.

    One compiled alternation, longest key first, boundary-anchored, applied by
    a single `re.sub`.  `re.sub` scans the INPUT and never re-examines what it
    has written, so no substitution can be re-substituted — regardless of what
    the keys look like relative to each other or to their replacements.

    The loop this replaces applied each key in turn to the running text, on
    the stated grounds that "every key is a full name, so no key is a prefix
    of another and the rewrite needs no ordering rule".  Both halves are
    false.  The chapter-folder key IS a prefix of every chapter filename
    (`Prince_UDL_2026` vs `Prince_UDL_2026_01_Intro.pdf`), and this skill's
    whole naming convention produces new stems that contain the old one
    (`UDL_2026` -> `Prince_UDL_2026`), so replacement output and later keys
    overlap by construction.  What kept that loop upright was the boundary
    anchors alone — an invariant nothing stated and nothing tested.  Here it
    is structural: there is one pass, so there is nothing to order.
    """
    ren = {o: n for o, n in ren.items() if o}
    if not ren:
        return text
    pat, lut, slut, _stems = _reference_re(set(ren))
    new_of = {}
    for o, n in ren.items():
        for v in _name_variants(o):
            new_of[v] = n
    new_stem_of = {}
    for o, n in stem_ren.items():
        for v in _name_variants(o):
            new_stem_of[v] = n

    def rewrite(part):
        urls = _external_url_spans(part)

        def repl(m):
            if _inside_span(m.start(), urls):
                return m.group(0)
            stem = _stem_match(m)
            if stem is not None:
                name = _canonical_name(slut, stem)
                if not _qualifies(m, name, dirs, note_dir):
                    return m.group(0)
                return m.group("open") + _canonical_name(new_stem_of, stem)
            name = m.group("name")
            if not _qualifies_qual(_qual_before(part, m.start("name")),
                                   _canonical_name(lut, name), dirs, note_dir):
                return m.group(0)
            return _canonical_name(new_of, name)

        rewritten = pat.sub(repl, part)
        return _rewrite_directory_paths(part, rewritten, directory_ren or {})

    return _map_source_text(text, rewrite)


# ---------------------------------------------------------------------------
# renaming
# ---------------------------------------------------------------------------

def _derive(old_stem, basename, new_stem):
    """`basename` with its leading `old_stem` swapped for `new_stem`.

    Case-insensitive, because `keyed_files` matches that way: a figure filed
    as `udl_2026_fig_1.png` beside a book named `UDL_2026.pdf` is one of that
    book's figures and has to move with it.  Normalisation-insensitive for the
    same reason and by the same helper — and here the two forms differ in
    LENGTH as well as in bytes, so the old prefix slice had to go through NFC
    rather than merely be compared through it: `len("Müller")` is 6 composed
    and 7 decomposed, and slicing an NFD figure name by the composed stem's
    length cut it mid-character and derived nothing.  A file `keyed_files`
    found and `_derive` declines to rename is a file the rename orphans.
    """
    nfc = unicodedata.normalize("NFC", basename)
    head = unicodedata.normalize("NFC", old_stem)
    if _nfc_low(nfc[:len(head)]) == _nfc_low(head):
        return new_stem + nfc[len(head):]
    # Book and chapter `_src` markers are independent. The book may carry
    # one while its chapter filenames do not, so those derived names begin
    # with its core identity. Keep each chapter's own suffix unchanged.
    identity = unicodedata.normalize("NFC", core_stem(old_stem, is_stem=True))
    if identity != head and _nfc_low(nfc[:len(identity)]) == _nfc_low(identity):
        return core_stem(new_stem, is_stem=True) + nfc[len(identity):]
    return basename                                   # not ours; leave it


def _inside(vault, path):
    """True when ``path`` is logically beneath this exact vault directory.

    Resolving both arguments with ``realpath`` is too strict for a vault whose
    ``Sources/PDFs`` directory deliberately links to another volume: the PDF
    is part of the selected vault through that logical path even though its
    physical target is elsewhere.  Comparing folded strings alone has the
    opposite problem on a case-sensitive filesystem, where ``Vault`` and
    ``vault`` can be two unrelated directories.

    Walk the candidate's *logical* ancestors instead.  A case/normalization
    spelling may identify the vault only when the filesystem says that
    ancestor has the selected vault's directory identity.  An explicit
    parent traversal is refused before ``abspath`` can hide a symlink/``..``
    escape, and a direct physical path to a linked directory's target has no
    logical vault ancestor, so it remains outside the selected scope.
    """
    try:
        vault_text = os.fsdecode(os.fspath(vault))
        path_text = os.fsdecode(os.fspath(path))

        # ``abspath`` collapses ``..`` lexically, but the filesystem resolves
        # it after any preceding symlink.  Reject the ambiguous spelling
        # rather than certify a path that can escape through ``link/..``.
        _drive, path_tail = os.path.splitdrive(path_text)
        if os.altsep:
            path_tail = path_tail.replace(os.altsep, os.sep)
        if os.pardir in path_tail.split(os.sep):
            return False

        vault_abs = os.path.abspath(vault_text)
        path_abs = os.path.abspath(path_text)
        vault_entry = os.lstat(vault_abs)
        vault_stat = os.stat(vault_abs)
        if not stat.S_ISDIR(vault_stat.st_mode):
            return False
        vault_entry_identity = (vault_entry.st_dev, vault_entry.st_ino,
                                stat.S_IFMT(vault_entry.st_mode))
        vault_identity = (vault_stat.st_dev, vault_stat.st_ino)

        def logical_key(value):
            native = os.path.normcase(os.path.normpath(value))
            return unicodedata.normalize("NFC", native).casefold()

        vault_key = logical_key(vault_abs)
        current = path_abs
        while True:
            if logical_key(current) == vault_key:
                candidate_entry = os.lstat(current)
                candidate_stat = os.stat(current)
                return (stat.S_ISDIR(candidate_stat.st_mode)
                        and (candidate_stat.st_dev, candidate_stat.st_ino)
                        == vault_identity
                        and (candidate_entry.st_dev, candidate_entry.st_ino,
                             stat.S_IFMT(candidate_entry.st_mode))
                        == vault_entry_identity)
            parent = os.path.dirname(current)
            if parent == current:
                return False
            current = parent
    except (OSError, TypeError, ValueError):
        return False


def _source_problem(path):
    """Why `path` cannot be a rename source, or None for a regular file/link.

    Symlinks reach the more specific ownership refusal in ``plan_rename``.
    Everything else must be an existing regular file; otherwise a dry run can
    advertise a move that fails only after note rewrites, and a directory whose
    name ends in ``.pdf`` can be moved into the source tree as if it were a PDF.
    """
    if not os.path.lexists(path):
        return "%s does not exist; refusing to plan a rename for a missing source" % path
    if not os.path.islink(path) and not os.path.isfile(path):
        return "%s is not a regular file; this skill renames PDF files, not directories or devices" % path
    return None


def obsolete_names(moves):
    """Basenames that disappeared, excluding filing and case-only changes."""
    return {os.path.basename(src) for src, dst in moves
            if re.fullmatch(re.escape(unicodedata.normalize(
                "NFC", os.path.basename(src))),
                unicodedata.normalize("NFC", os.path.basename(dst)), re.I) is None}


def _image_ownership_blockers(vault, source, keyed):
    """Require positive PDF-manifest ownership for every derived image."""
    images = os.path.join(vault, "Sources", "Images")
    candidates = [(path, name) for path, name in keyed.items()
                  if os.path.abspath(os.path.dirname(path)) == os.path.abspath(images)
                  and "_fig" in _nfc_low(name)]
    if not candidates:
        return []
    try:
        manifest = read_manifest(os.path.join(images, MANIFEST_FILE))
        blockers = []
        for image_path, image_name in candidates:
            try:
                key = manifest_key(manifest, image_name)
                snapshot = _stable_file_snapshot(image_path)
                owned = key is not None and snapshot[1] == manifest[key]
            except (OSError, UnicodeError, ValueError):
                owned = False
            if not owned:
                blockers.append(
                    "%s has no matching current PDF ownership record. "
                    "Matching a source stem is not ownership; explicitly adopt "
                    "or repair this legacy figure through pdf-figure-extractor "
                    "before renaming the PDF." % image_path)
        return blockers
    except (OSError, UnicodeError, ValueError) as exc:
        return ["Cannot establish PDF ownership of derived images (%s). "
                "Repair the figure records before renaming." % exc]


def _target_stem_blockers(vault, stem, mine):
    """Block a PDF rename onto a note/image namespace owned by another source."""
    blockers = []
    articles = os.path.join(vault, "Articles")
    wanted_note = _nfc_low(stem + ".md")
    for name in _listdir(articles):
        path = os.path.join(articles, name)
        if (_nfc_low(name) == wanted_note
                and os.path.realpath(path) not in mine):
            blockers.append(
                "%s already owns the target stem as an Articles note; choose "
                "another canonical PDF name" % path)

    images = os.path.join(vault, "Sources", "Images")
    if os.path.isdir(images):
        inventory = inventory_source_figures(images, stem)
        if not inventory.complete:
            blockers.append(
                "the target figure namespace %s_fig* could not be inventoried "
                "completely; repair access before renaming" % stem)
        for path in inventory.candidates + inventory.blocked_matches:
            if os.path.realpath(path) not in mine:
                blockers.append(
                    "%s already occupies the target figure stem %s_fig*; "
                    "establish its source owner or choose another PDF name"
                    % (path, stem))
    return blockers


def _file_identity(st):
    """The directory-entry identity an expected-content check is tied to."""
    return st.st_dev, st.st_ino, stat.S_IFMT(st.st_mode)


def _change_identity(st):
    """Metadata that changes when a file is replaced or written in place."""
    return (st.st_dev, st.st_ino, st.st_size,
            getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9)),
            getattr(st, "st_ctime_ns", int(st.st_ctime * 1e9)),
            stat.S_IMODE(st.st_mode))


def _stable_file_snapshot(path):
    """Identity and digest read from one stable, no-follow descriptor."""
    before = os.lstat(path)
    if not stat.S_ISREG(before.st_mode):
        raise StaleRenamePlan("%s is not a regular file" % path)
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise StaleRenamePlan(
            "%s changed or could not be opened safely: %s" % (path, exc)) from exc
    digest = hashlib.sha256()
    with os.fdopen(descriptor, "rb") as source:
        opened_before = os.fstat(source.fileno())
        if (not stat.S_ISREG(opened_before.st_mode)
                or _file_identity(before) != _file_identity(opened_before)):
            raise StaleRenamePlan("%s changed while it was opened" % path)
        while True:
            chunk = source.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
        opened_after = os.fstat(source.fileno())
    try:
        after = os.lstat(path)
    except OSError as exc:
        raise StaleRenamePlan(
            "%s changed while its move snapshot was read: %s" % (path, exc)) from exc
    if not (_change_identity(before) == _change_identity(after)
            and _change_identity(opened_before)
            == _change_identity(opened_after)
            and _file_identity(before) == _file_identity(opened_before)
            and _file_identity(after) == _file_identity(opened_after)):
        raise StaleRenamePlan(
            "%s changed while its move snapshot was read" % path)
    return _file_identity(after), digest.hexdigest()


def _move_snapshot(path):
    """Content-bearing move guard for files; identity guard for directories."""
    item = os.stat(path, follow_symlinks=False)
    if stat.S_ISREG(item.st_mode):
        return "regular", _stable_file_snapshot(path)
    if stat.S_ISDIR(item.st_mode):
        return "directory", _file_identity(item)
    raise StaleRenamePlan(
        "%s is a symlink or unsupported non-regular move source" % path)


def _move_snapshot_identity(snapshot):
    """Directory-entry identity accepted by the exclusive move primitive."""
    kind, value = snapshot
    return value[0] if kind == "regular" else value


def _read_snapshot(path):
    """Read exact text and reject a file that changes during that read."""
    entry = os.stat(path, follow_symlinks=False)
    if stat.S_ISLNK(entry.st_mode):
        raise StaleRenamePlan(
            "%s is a leaf symlink; refusing to read or rewrite its target" % path)
    if not stat.S_ISREG(entry.st_mode):
        raise StaleRenamePlan("%s is not a regular file" % path)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, "r", encoding="utf-8", newline="") as fh:
        before = os.fstat(fh.fileno())
        if _file_identity(entry) != _file_identity(before):
            raise StaleRenamePlan(
                "%s changed while it was being opened" % path)
        body = fh.read()
        after = os.fstat(fh.fileno())
    final = os.stat(path, follow_symlinks=False)
    if not (_change_identity(entry) == _change_identity(final)
            and _change_identity(before) == _change_identity(after)
            and _file_identity(entry) == _file_identity(before)
            and _file_identity(final) == _file_identity(after)):
        raise StaleRenamePlan(
            "%s changed while it was being read; refusing a mixed snapshot"
            % path)
    return body, _file_identity(after)


def _plan_figure_state(vault, ren):
    """Plan metadata updates for the images and PDF stems being renamed."""
    edits, expected, blockers = {}, {}, []
    stems = {os.path.splitext(old)[0]: os.path.splitext(new)[0]
             for old, new in ren.items() if old.lower().endswith(".pdf")}
    for filename, kind, mapping in ((MANIFEST_FILE, "manifest", ren),
                                     (REVIEW_FILE, "review", stems)):
        path = os.path.join(vault, "Sources", "Images", filename)
        if not os.path.lexists(path):
            continue
        try:
            if os.path.islink(path):
                raise ValueError("sidecar is a symlink; reconcile its real location first")
            body, identity = _read_snapshot(path)
            new = rewrite_sidecar(body, mapping, kind)
            if new != body:
                check_manifest_writable(path)
                real_dir = os.path.realpath(os.path.dirname(path) or ".")
                if (not os.access(real_dir, os.W_OK)
                        or not os.access(os.path.dirname(real_dir), os.W_OK)):
                    raise ValueError("sidecar or its outside-folder staging "
                                     "location is not writable")
                edits[path] = new
                expected[path] = (body, identity)
        except (OSError, UnicodeError, ValueError) as exc:
            blockers.append("%s cannot safely follow the source rename (%s). "
                            "Repair its records first; do not delete/reset ownership metadata."
                            % (path, exc))
    return edits, expected, blockers


def plan_rename(vault, path, new_basename, dest=None):
    """(moves, edits, blockers) for renaming `path` to `new_basename`.

    `dest` is where the SOURCE FILE lands — the folder a reorganised vault
    keeps its documents in (`Sources/PDFs/`), when the file arrived somewhere
    else (`Inbox/`).  It moves that one file and nothing else: a figure, a
    note or a chapter folder keyed to this stem is renamed **in its own
    home**, because those homes are where their consumers look.  Omit it and
    every keyed file, source included, is renamed in place — the behaviour
    every caller had before a destination existed.

    Writes nothing.  `moves` is [(src, dst)] deepest path first, so a chapter
    folder is renamed after its contents; `edits` is an `Edits` — a
    {md path: new body} dict carrying the notes that could not be read at all
    as `edits.unreadable`, out of the mapping, where nothing mistakes one for
    a path to open; `blockers` is a list of reasons in words.  A non-empty
    `blockers` means nothing may be written — see `rename_all`.

    `vault` may be None or a directory that does not exist: this skill is
    explicitly pointed at a Downloads inbox.  The vault-wide checks then have
    nothing to walk, which is the correct empty answer for a fresh download —
    but the literal-destination check below still runs, and it is the one that
    matters there.
    """
    src_basename = os.path.basename(path)
    old_stem, old_ext = os.path.splitext(src_basename)
    new_stem, new_ext = os.path.splitext(new_basename)
    have_vault = bool(vault) and os.path.isdir(vault)
    source_problem = _source_problem(path)
    if source_problem:
        return [], Edits(), [source_problem]
    if have_vault and not _inside(vault, path):
        return [], Edits(), [
            "%s is outside the vault passed as --vault. Its stem cannot "
            "establish ownership of files inside that vault. Omit --vault "
            "and --dest to rename this independent download in place; "
            "this command never imports it into the vault." % path]

    # Measured on the name that actually lands on disk, not the one the caller
    # typed: this skill keeps the source's own extension, so `--to '<stem>'` with
    # no extension is four bytes shorter here than the file it produces, and
    # the limit was being enforced against a string that never exists.
    written_basename = new_stem + (old_ext or new_ext)

    if not SAFE_NAME.match(new_stem) \
            or len(os.fsencode(written_basename)) > MAX_NAME_BYTES:
        return [], Edits(), [
            "%r is not a usable name — ASCII letters, digits, `_`, `-`, `.` "
            "only, under %d bytes" % (written_basename, MAX_NAME_BYTES)]

    # THE SOURCE IS A PDF, AND THIS SKILL ORGANISES NOTHING ELSE.  The rename
    # machinery below is extension-agnostic and was once pointed at any
    # text-bearing format, so the narrowing has to be a guard rather than a
    # habit: `Sources/PDFs/` is named for what it holds, `split_book` needs a
    # PDF, `pdf-figure-extractor` reads only PDFs, and `paper-summarizer` globs
    # `*.pdf`.  A `.epub` renamed into that folder is a file every consumer
    # walks straight past, and nothing reports it.
    #
    # A source with NO extension at all is the one thing that gets through: a
    # browser save (`download`) is overwhelmingly a PDF, the caller supplies
    # the extension for it, and the checks below vet the supplied one.
    #
    # FIRST of the three, because it is the only one whose advice is right for
    # a `.txt`: "pass `<stem>.txt` instead" would send the caller back with a
    # name this skill refuses just as hard.
    if old_ext and old_ext.lower() != ".pdf":
        return [], Edits(), [
            "refusing to rename %r: this skill organises PDFs, and %s is not "
            "one. Renaming it into Sources/PDFs/ would file it where every "
            "consumer globs *.pdf and none would ever see it. Leave it where "
            "it is, and name it in the report rather than dropping it "
            "silently." % (src_basename, old_ext)]

    # THIS SKILL RENAMES THE STEM AND NEVER THE EXTENSION (SKILL.md's filename rules: "always preserves the original extension; only the base
    # name changes").  A caller passing a different one believes it is
    # renaming some other file, so that is a blocker rather than a silent
    # preference — this used to be resolved by quietly discarding whatever the
    # caller asked for, which turned `download` + `Smith_X_1776.pdf` into an
    # extensionless `Smith_X_1776` with no blocker, breaking every downstream
    # `![[Smith_X_1776.pdf]]` embed and every `*.pdf` sweep.
    #
    # ABOVE the "name we write ends in .pdf" guard, and that ordering is the
    # whole of the check.  Below it, the only way here was `old_ext` and
    # `new_ext` both in {"", ".pdf"} — under which they never differ — so the
    # branch was unreachable and the mismatch a caller actually makes
    # (`.pdf` -> `.epub`) was answered by the generic PDFs-only refusal.
    # SKILL.md promises this message twice ("the message names the basename to
    # pass instead") and `--to`'s help text a third time; no reachable message
    # named one, and a promise the code cannot keep is read by the next caller
    # as a bug in their own invocation.
    if old_ext and new_ext and old_ext.lower() != new_ext.lower():
        return [], Edits(), [
            "refusing to rename %r to %r: that changes the extension from %s "
            "to %s. This skill renames the stem and preserves the extension, "
            "so a mismatch means the caller has the wrong file in hand. Pass "
            "%r." % (src_basename, new_basename, old_ext, new_ext,
                     new_stem + old_ext)]

    # What is left is a name whose extension contradicts no source: either
    # there is no source extension to preserve, or the two already agree.
    if new_ext and new_ext.lower() != ".pdf":
        return [], Edits(), [
            "refusing to write %r: this skill organises PDFs, so the name it "
            "writes ends in .pdf." % new_basename]
    if not old_ext and new_ext.lower() != ".pdf":
        return [], Edits(), [
            "refusing to file extensionless source %r without an explicit "
            ".pdf destination. Pass a canonical <Author>_<Title>_<Year>.pdf "
            "name after verifying the bytes are a PDF." % src_basename]
    if not looks_canonical(written_basename):
        return [], Edits(), [
            "%r is portable but not a canonical PDF name. Use "
            "<Author>_<AbbreviatedTitle>_<Year>.pdf (or the documented "
            "chapter form) so downstream skills can recognize it."
            % written_basename]
    old_src_marker = _existing_src_marker(old_stem)
    new_src_marker = _existing_src_marker(new_stem)
    if old_src_marker != new_src_marker:
        change = ("remove the existing `_src` representation marker"
                  if old_src_marker else
                  "add an `_src` representation marker")
        return [], Edits(), [
            "refusing to %s while "
            "renaming %r to %r. Preserve that marker exactly; it distinguishes "
            "another representation of the same document from a different "
            "document identity." % (change, src_basename, written_basename)]
    if not old_ext:
        try:
            with open(path, "rb") as source:
                header = source.read(1024)
        except OSError as exc:
            return [], Edits(), [
                "cannot verify extensionless source %r as PDF bytes: %s"
                % (src_basename, exc)]
        if b"%PDF-" not in header:
            return [], Edits(), [
                "extensionless source %r does not contain a PDF header in "
                "its first 1024 bytes; refusing to add .pdf by name alone."
                % src_basename]

    try:
        keyed = keyed_files(vault, path) if have_vault \
            else {path: src_basename}
    except InventoryFailed as exc:
        return [], Edits(), [
            "%s The owned source family cannot be established, so nothing "
            "may be renamed." % exc]
    ren = {b: _derive(old_stem, b, new_stem) for b in keyed.values()}
    directory_ren = {b: ren[b] for p, b in keyed.items()
                     if os.path.isdir(p) and not os.path.islink(p)}
    reference_ren = {old: new for old, new in ren.items()
                     if _nfc_low(old) not in {_nfc_low(name)
                                              for name in directory_ren}}

    # A source that arrived with no extension at all (`download`, a browser
    # save) is the one case where the caller's extension is new information
    # rather than a contradiction: there is nothing to preserve, so supply it.
    # Only the source file is affected — a derived figure or note keeps its
    # own extension, which `_derive` carries through in the tail.
    if not old_ext and new_ext:
        ren[src_basename] = new_stem + new_ext

    try:
        blockers = (_image_ownership_blockers(vault, path, keyed)
                    if have_vault else [])
    except InventoryFailed as exc:
        blockers = ["%s Image ownership cannot be established from an "
                    "incomplete inventory." % exc]
    # A paper-summary note is part of the owned source family, so a change to
    # the filename's canonical year must carry its `published` value in the
    # same guarded note rewrite. Ordinary citing notes are deliberately absent
    # from this map: their own publication metadata describes themselves, not
    # the PDF they happen to cite.
    published_year_targets = {}
    for owned_path, basename in keyed.items():
        if not basename.lower().endswith(".md"):
            continue
        old_note_stem = os.path.splitext(basename)[0]
        new_note_stem = os.path.splitext(ren[basename])[0]
        old_year = _canonical_year(old_note_stem)
        target_year = _canonical_year(new_note_stem)
        if target_year is None:
            blockers.append(
                "%s would not retain a canonical year segment after the rename; "
                "its publication metadata cannot be planned safely" % owned_path)
        elif target_year != old_year:
            published_year_targets[owned_path] = target_year
    mine = {os.path.realpath(p) for p in keyed}
    if have_vault and _nfc_low(new_stem) != _nfc_low(old_stem):
        blockers.extend(_target_stem_blockers(vault, new_stem, mine))

    # Renaming an already-split book must not mint chapter names a later
    # extractor refuses or attributes to a different book. In particular a
    # `_2` disambiguator cannot be inserted before the chapter segment.
    for old, new in ren.items():
        book = chapter_book_stem(old) if old.lower().endswith(".pdf") else None
        if book and _nfc_low(book) == _nfc_low(core_stem(old_stem, is_stem=True)):
            new_book = chapter_book_stem(new)
            if not looks_canonical(new) or new_book is None \
                    or _nfc_low(new_book) != _nfc_low(core_stem(new_stem, is_stem=True)):
                blockers.append("%s would become %s, which is not a canonical chapter "
                                "of the renamed book. Re-abbreviate the book title "
                                "before the year rather than adding a disambiguator."
                                % (old, new))

    # A relative `dest` resolves against whatever directory the shell happens
    # to be in, which is not the vault and is not this skill's to guess.  Left
    # unchecked it moves the document to `<cwd>/Sources/PDFs/`, rewrites every
    # vault reference to the new basename, and reports success — the file is
    # outside the vault and every link now resolves to nothing.
    if dest is not None:
        if not have_vault:
            blockers.append(
                "a destination was given (%s) but there is no vault to move "
                "into (--vault %s). Relocating a file needs a vault: outside "
                "one there is nothing to be inside, and nothing to rewrite."
                % (dest, vault or "not given"))
        elif not _inside(vault, path):
            # SKILL.md: "A file outside the vault is never imported." Deciding
            # that a download belongs in the vault is the user's call, not a
            # side effect of asking for a better filename.
            blockers.append(
                "%s is outside the vault %s, so it is renamed where it sits "
                "and no destination applies. Move it into the vault yourself "
                "first if that is what you meant." % (path, vault))
        if not os.path.isabs(dest):
            blockers.append(
                "destination %r is a relative path. It would resolve against "
                "the current working directory rather than the vault, so the "
                "file would be moved out of the vault while every reference "
                "to it was rewritten. Pass an absolute path." % dest)
        elif have_vault:
            if not _inside(vault, dest):
                blockers.append(
                    "destination %s is outside the vault %s. Moving a document "
                    "out of the vault while rewriting the notes that cite it "
                    "leaves every one of those links resolving to nothing."
                    % (dest, vault))

    # Two keyed names differing only in case or Unicode normalization may be
    # distinct on one filesystem and aliases on another, but derive to one new
    # name (`_derive` writes NFC). Left alone, the second
    # `os.rename` destroys the first silently — a file the user cannot get
    # back, in the operation with no downstream safety net.  Grouped under
    # `_nfc_low`, the SAME fold the fan-out used to collect these names: the
    # old `b.lower()` saw an NFC/NFD twin pair as two groups, and the pair
    # sailed past the guard into exactly that silent overwrite.
    by_lower = {}
    for b in sorted(ren):
        by_lower.setdefault(_nfc_low(b), []).append(b)
    for low, group in sorted(by_lower.items()):
        if len(group) > 1:
            blockers.append("%s all derive from one stem and differ only in "
                            "case/normalization, so they would be renamed onto "
                            "one name (%s)"
                            % (", ".join(repr(g) for g in group), ren[group[0]]))

    # Every DERIVED name has to be usable, not just the one the user typed.
    for old, new in sorted(ren.items()):
        if len(os.fsencode(new)) > MAX_NAME_BYTES:
            blockers.append("%s would become %r — %d bytes, over the %d-byte "
                            "limit. Abbreviate the title further."
                            % (old, new, len(os.fsencode(new)), MAX_NAME_BYTES))

    try:
        existing = vault_names(vault) if have_vault else {}
    except InventoryFailed as exc:
        blockers.append("%s Vault-wide basename uniqueness could not be "
                        "checked." % exc)
        existing = {}
    # Every colliding path, not just one: two files already sharing a
    # lowercased basename are two separate obstacles, and naming one of them
    # sends the user back around the same refusal after they have moved it.
    for new in sorted(set(ren.values())):
        clashes = [p for p in existing.get(_nfc_low(new), [])
                   if os.path.realpath(p) not in mine]
        if clashes:
            blockers.append("%s already exists at %s"
                            % (new, ", ".join(clashes)))

    # Deepest path first, so a chapter folder is renamed after its contents.
    src_real = os.path.realpath(path)
    # The names whose FOLDER changes, so `debase_links` knows what to strip.
    # Empty unless `dest` actually relocates the file: a rename in place keeps
    # every qualification valid, and stripping one there would be a gratuitous
    # rewrite of the user's chosen link style.
    moved_names = set()
    if dest and os.path.realpath(dest) != os.path.realpath(
            os.path.dirname(path) or "."):
        # The basename ONLY, never its extensionless stem.  A stem carries no
        # extension and so names nothing in particular: `[[Wiki/Smith_X_1776]]`
        # is a link to a NOTE of that slug, not to this document, and dropping
        # its folder repoints it at whatever Obsidian resolves by proximity --
        # the exact "link to a different file silently repointed" failure
        # `_qualifies` exists to prevent, with `_qualifies` bypassed.  An
        # extensionless link to a PDF does not resolve in Obsidian anyway, so
        # there is nothing on that side to fix.
        moved_names = {ren.get(src_basename, src_basename)}

    def _home(p):
        # The source file is the only one `dest` applies to.
        if dest and os.path.realpath(p) == src_real:
            return dest
        return os.path.dirname(p)

    moves = sorted(((p, os.path.join(_home(p), ren[b]))
                    for p, b in keyed.items()), key=lambda t: -len(t[0]))

    # The vault-wide check above does NOT cover the destination when the file
    # is outside the vault -- and this skill is explicitly pointed at a
    # Downloads inbox, where `vault_names` comes back empty by design. Without
    # this, renaming `download(1).pdf` onto a `Smith_Wealth_1776.pdf` already
    # sitting in that folder is a plain `os.rename`: it destroys the
    # destination with no error and no way back. `lexists`, not `exists`, so a
    # broken symlink still counts as something there.
    # `os.path.realpath` does not case-fold, so on a case-insensitive volume a
    # case-only rename (`foo.pdf` ->
    # `Foo.pdf`) has src and dst as the same file while the two realpaths
    # differ, and this refused it as a collision.  SKILL.md then tells the model
    # to append `_2`, producing a name `split_book` refuses to split forever.
    # `os.path.samefile` asks the filesystem instead of comparing strings.
    def _same(src, dst):
        try:
            return os.path.samefile(src, dst)
        except OSError:
            return os.path.realpath(src) == os.path.realpath(dst)

    blockers += ["%s already exists at %s" % (os.path.basename(dst), dst)
                 for src, dst in moves
                 if os.path.lexists(dst) and not _same(src, dst)]

    # A symlinked source: `os.rename` moves the LINK and leaves the real file
    # behind under its old name -- which is the exact hazard SKILL.md tells the
    # model to use this function to avoid. Moving it to a different depth also
    # dangles a relative target. Refuse rather than produce a vault where every
    # note points at a broken link and the document is unreachable.
    for src, dst in moves:
        if os.path.islink(src):
            blockers.append(
                "%s is a symlink to %s. Renaming it would move the link and "
                "leave the document behind under its old name -- and moving it "
                "to another folder would dangle a relative target. Rename the "
                "real file, or replace the link with the file, then re-run."
                % (src, os.readlink(src)))

    # Writability is settled HERE, not discovered half-way through the moves.
    # `os.rename` needs the containing directory writable — a read-only file
    # still moves — while a note needs the file itself writable, because
    # `_write`'s staged publication can go straight through a read-only
    # bit that a plain `open(path, "w")` would have stopped at. A note the
    # user protected on purpose is a refusal, and it is one the plan shows
    # before anything is written.
    for src, dst in moves:
        for d in {os.path.dirname(src), os.path.dirname(dst)}:
            # `dest` may not exist yet — the run that first uses it creates it
            # — so test the nearest ancestor that does. Testing the absent
            # directory itself reports every first run as unwritable.
            probe = d
            while probe and not os.path.isdir(probe):
                parent = os.path.dirname(probe)
                if parent == probe:
                    break
                probe = parent
            if not probe or not os.access(probe, os.W_OK):
                blockers.append("%s is not writable, so %s cannot be moved"
                                % (d, os.path.basename(src)))

    stem_ren = {os.path.splitext(o)[0]: os.path.splitext(n)[0]
                for o, n in ren.items() if o.lower().endswith(".md")}
    # Where the keyed files actually live, so a folder-qualified wikilink to
    # some OTHER file of the same basename is left alone rather than pointed at
    # a note this rename never created.  None outside a vault: nothing walked,
    # nothing to locate against, and `keyed` is the source file alone.
    dirs = keyed_dirs(vault, keyed) if have_vault else None
    edits = Edits()
    unreadable = []
    if have_vault:
        try:
            markdown_files = list(md_files(vault))
        except InventoryFailed as exc:
            blockers.append("%s Markdown references could not be scanned "
                            "completely." % exc)
            markdown_files = []
        for md in markdown_files:
            try:
                body, identity = _read_snapshot(md)
            except OSError as exc:
                # Unlike a decoding error, an I/O failure cannot be re-read
                # leniently to prove that the note cites nothing. Treating it
                # as a harmless unreadable note would authorize a rename on no
                # evidence at all.
                blockers.append(
                    "%s could not be read (%s), so the vault-wide reference "
                    "scan is incomplete. Restore access, then re-run."
                    % (md, exc))
                continue
            except UnicodeDecodeError as exc:
                # A blocker here dead-ends every rename in the vault on one
                # stray legacy note, including renames that note does not
                # mention -- and SKILL.md says never work around a blocker.
                # It is only a blocker if the file could actually be citing
                # one of the names being changed, which is decidable: re-read
                # it leniently and look.
                try:
                    with open(md, encoding="utf-8", errors="replace") as fh:
                        loose = fh.read()
                except OSError as retry:
                    blockers.append(
                        "%s could not be re-read to inspect its non-UTF-8 "
                        "contents (%s), so its references are unknown. "
                        "Restore access, then re-run." % (md, retry))
                    continue
                if loose and references_in_text(loose, ren, stem_ren):
                    blockers.append(
                        "%s cites a name this rename changes but could not be "
                        "read as UTF-8 (%s), so its links cannot be rewritten. "
                        "Fix the file's encoding, then re-run."
                        % (md, type(exc).__name__))
                else:
                    unreadable.append("%s (%s)" % (md, type(exc).__name__))
                continue
            new = rewrite_text(
                body, reference_ren, stem_ren, dirs,
                os.path.relpath(os.path.dirname(md), vault), directory_ren)
            if moved_names:
                new = debase_links(new, moved_names)
            if (md in published_year_targets
                    and _is_paper_summary_metadata(new)):
                try:
                    reconciled, old_published, new_published = \
                        _reconcile_published_year(new, published_year_targets[md])
                except ValueError as exc:
                    blockers.append(
                        "%s is the owned paper-summary note, but its `published` "
                        "metadata cannot follow the source year rename (%s). "
                        "Correct that one field from the source, then re-plan."
                        % (md, exc))
                else:
                    if reconciled != new:
                        edits.published_updates[md] = (
                            old_published, new_published)
                    new = reconciled
            if new != body:
                edits[md] = new
                edits.expected[md] = (body, identity)
                if not (os.access(md, os.W_OK)
                        and os.access(os.path.dirname(md), os.W_OK)):
                    blockers.append("%s cites this file but is not writable, "
                                    "so the rename would leave it dangling"
                                    % md)
    # Not a blocker: none of these cites a name being changed. Carried so the
    # run report can say what was skipped rather than implying a clean sweep --
    # BESIDE the mapping and never inside it, because every consumer of `edits`
    # reads a key as a note path and a value as that note's new body.  It used
    # to arrive as `edits["__unreadable__"]`, and `rename_all` then walked
    # `edits.items()` straight into `open("__unreadable__")`: one stray
    # latin-1 note that cites nothing dead-ended EVERY rename in the vault
    # with a `FileNotFoundError` naming a file that does not exist, and
    # `_report_plan` listed the sentinel as a note it was about to rewrite.
    edits.unreadable = tuple(unreadable)
    if have_vault:
        (edits.sidecars, sidecar_expected,
         sidecar_blockers) = _plan_figure_state(vault, ren)
        edits.expected.update(sidecar_expected)
        blockers.extend(sidecar_blockers)
    for src, _dst in moves:
        try:
            edits.move_expected[src] = _move_snapshot(src)
        except OSError as exc:
            blockers.append(
                "%s changed while the move plan was being finalized (%s: %s); "
                "nothing may be renamed" % (src, type(exc).__name__, exc))
    return moves, edits, blockers


def references_in_text(text, ren, stem_ren):
    """Does `text` cite any name being renamed?  Cheap, lenient, read-only."""
    names = set(ren) | set(stem_ren)
    if not names:
        return False
    pat, _lut, _slut, _stems = _reference_re({n for n in names if n})
    for _original, part, _style in _source_text_parts(text):
        urls = _external_url_spans(part)
        if any(not _inside_span(m.start(), urls) for m in pat.finditer(part)):
            return True
    return False


def _write(path, text, expected=None):
    """Publish complete text while preserving permissions and late edits.

    Runtime rename writes pass the exact text and inode identity read during
    planning. The current inode is hard-linked, verified, displaced, verified
    again, and the staged inode is then linked at the now-free name with
    exclusive-create semantics. A writer in any compare/write gap keeps the
    public path; the displaced predecessor is restored or retained in a named
    recovery directory. Rollback uses the same operation.
    """
    # Directory symlinks remain part of the selected recursive vault scope,
    # but a leaf symlink can target arbitrary bytes outside it. Never follow a
    # leaf for mutation; the planning scan reports it as a blocker instead.
    target = path
    previous = os.stat(target, follow_symlinks=False)
    if stat.S_ISLNK(previous.st_mode):
        raise StaleRenamePlan(
            "%s is a leaf symlink; refusing to rewrite its target" % target)
    if not stat.S_ISREG(previous.st_mode):
        raise StaleRenamePlan("%s is no longer a regular file" % target)
    if expected is None:
        expected = _read_snapshot(target)
    mode = stat.S_IMODE(previous.st_mode)
    logical_dir = os.path.abspath(os.path.dirname(path) or ".")
    is_image_sidecar = (
        os.path.basename(path) in (MANIFEST_FILE, REVIEW_FILE)
        and os.path.basename(logical_dir) == "Images"
        and os.path.basename(os.path.dirname(logical_dir)) == "Sources"
    )
    real_dir = os.path.realpath(os.path.dirname(target) or ".")
    # Sidecar staging stays outside the flat Images consumer folder. Ordinary
    # notes use their own directory so publication and hard links stay on the
    # target filesystem.
    stage_parent = (os.path.dirname(real_dir) if is_image_sidecar else real_dir)
    stage = tempfile.mkdtemp(prefix=".organize-stage-", dir=stage_parent)
    keep_stage = False
    try:
        staged = os.path.join(stage, os.path.basename(target))
        with open(staged, "x", encoding="utf-8", newline="") as fh:
            fh.write(text)
            set_private_mode(fh, staged, mode)
            published = (text, _file_identity(os.fstat(fh.fileno())))
        try:
            published = replace_expected(
                staged, target, expected, _read_snapshot, stage,
                stage_parent=stage_parent,
                recovery_prefix=".organize-recovery-")
        except LinkUnavailable as exc:
            keep_stage = True
            exc.keep_stage = True
            exc.staging_path = stage
            if getattr(exc, "recovery_path", None) is None:
                exc.recovery_path = staged
            if staged not in str(exc):
                exc.strerror = "%s; staged rewrite preserved at %s" % (
                    exc.strerror, staged)
                exc.args = (exc.errno, exc.strerror)
            raise
        except PublicationConflict as exc:
            keep_stage = True
            raise StaleRenamePlan(
                "%s; staged rewrite preserved at %s" % (exc, staged),
                recovery_path=exc.recovery_path,
                staging_path=stage) from exc
        except BaseException as exc:
            # The complete staged rewrite is the only recoverable output when
            # an unexpected publication error interrupts this transaction.
            keep_stage = True
            try:
                exc.keep_stage = True
                exc.staging_path = stage
                if getattr(exc, "recovery_path", None) is None:
                    exc.recovery_path = staged
            except (AttributeError, TypeError):
                pass
            raise
        return published
    finally:
        if not keep_stage:
            shutil.rmtree(stage, ignore_errors=True)


def rename_all(vault, path, new_basename, apply=False, dest=None):
    """Rename `path` **and every name keyed to it**, rewriting every `.md`
    reference in the same pass.

    Returns (moves, edits, blockers) exactly as `plan_rename` does, notes it
    could not read included (`edits.unreadable`); writes nothing unless
    `apply` and `blockers` is empty.  Call it with the default first and show
    the user the plan — that is also the reference report.

    Notes are rewritten BEFORE the files move, which is not cosmetic: a note
    named after the source (`Articles/<stem>.md`) is both a file this rename
    moves and a file
    whose body cites the rename, and writing the moves first left every edit
    keyed to a path that no longer existed.  Every rename of a PDF that had
    such a note — the ordinary vault case — died on that and rolled back, so
    the rename simply never happened.

    Every filesystem move is exclusive at the operation itself, including
    rollback. Note and sidecar publication displaces and revalidates the exact
    planned inode before linking the new one into the free name. A competing
    writer is preserved at the public path; when two predecessors cannot share
    it, the error names the private recovery copy instead of deleting either.
    """
    moves, edits, blockers = plan_rename(vault, path, new_basename, dest)
    if not apply or blockers:
        return moves, edits, blockers

    done_edits, done_moves, made_dirs = {}, [], []

    def move_stage_parent(source):
        """Keep private residue outside a flat Images folder when possible."""
        real_dir = os.path.realpath(os.path.dirname(source) or ".")
        logical_dir = os.path.abspath(os.path.dirname(source) or ".")
        candidate = real_dir
        if (os.path.basename(logical_dir).casefold() == "images"
                and os.path.basename(os.path.dirname(logical_dir)).casefold()
                == "sources"):
            outside = os.path.dirname(real_dir)
            try:
                if os.stat(outside).st_dev == os.lstat(source).st_dev:
                    candidate = outside
            except OSError:
                pass
        return candidate

    try:
        # Create `dest` before the first move, and remember whether we did, so
        # a rollback leaves the tree exactly as it found it.
        for src, dst in moves:
            d = os.path.dirname(dst)
            # Every level this run creates, deepest last, so the rollback can
            # unwind all of them. `os.makedirs` makes the intermediates too,
            # and recording only the leaf leaves `Sources/` behind after a
            # rollback that claims to leave the tree as it found it.
            missing = []
            probe = d
            while probe and not os.path.isdir(probe):
                missing.append(probe)
                parent = os.path.dirname(probe)
                if parent == probe:
                    break
                probe = parent
            if missing:
                os.makedirs(d)
                made_dirs.extend(reversed(missing))
        for md, new in list(edits.items()) + list(edits.sidecars.items()):
            expected = edits.expected[md]
            published = _write(md, new, expected=expected)
            done_edits[md] = (expected[0], published)
            # A source-family note can be rewritten and then renamed. Its
            # planned inode was just replaced by the staged inode, so the move
            # guard must follow the publication identity this transaction now
            # owns rather than reject its own earlier write as interference.
            if md in edits.move_expected:
                edits.move_expected[md] = _move_snapshot(md)
        for src, dst in moves:
            if os.path.abspath(src) != os.path.abspath(dst):
                expected_move = edits.move_expected[src]
                if _move_snapshot(src) != expected_move:
                    raise StaleRenamePlan(
                        "%s changed after the rename plan; refusing to move "
                        "different bytes" % src)
                identity = _move_snapshot_identity(expected_move)
                move_noreplace(src, dst, expected=identity,
                               stage_parent=move_stage_parent(src))
                # Record the move before readback so a failed content check
                # restores the same inode to its old name through the ordinary
                # exclusive rollback path.
                done_moves.append((src, dst, expected_move))
                if _move_snapshot(dst) != expected_move:
                    raise StaleRenamePlan(
                        "%s changed while it was being moved; refusing to "
                        "complete a rename derived from different bytes" % src)
    except BaseException as exc:
        failed = []
        if isinstance(exc, MoveIncomplete):
            failed.append("current move residue at %s and/or %s (%s)" %
                          (exc.src, exc.dst, exc))
        if (isinstance(exc, StaleRenamePlan)
                and exc.recovery_path is not None):
            failed.append("preserved displaced file at %s" % exc.recovery_path)
        for src, dst, expected_move in reversed(done_moves):
            try:
                identity = _move_snapshot_identity(expected_move)
                move_noreplace(dst, src, expected=identity,
                               stage_parent=move_stage_parent(dst))
            except OSError as back:
                failed.append("%s -> %s (%s)" % (dst, src, back))
        for md, (old_body, published) in reversed(list(done_edits.items())):
            try:
                _write(md, old_body, expected=published)
            except OSError as back:
                failed.append("%s (%s)" % (md, back))
        for d in reversed(made_dirs):
            try:
                os.rmdir(d)          # only ever removes one we just created
            except OSError:
                pass
        msg = ("rename of %s failed part-way (%s: %s)."
               % (os.path.basename(path), type(exc).__name__, exc))
        if failed:
            raise RenameFailed(
                msg + " The ROLLBACK ALSO FAILED, so the vault is in a mixed "
                "state. Undo these by hand before doing anything else:\n  - "
                + "\n  - ".join(failed), rolled_back=False) from exc
        staging_path = getattr(exc, "staging_path", None)
        if staging_path:
            raise RenameFailed(
                msg + " Rolled back all public changes. A complete staged "
                "rewrite remains at %s." % staging_path) from exc
        raise RenameFailed(
            msg + " Rolled back — nothing from this rename is on disk.") from exc
    return moves, edits, blockers


# `looks_canonical`, `chapter_parts`, `chapter_book_stem` and `core_stem` are
# imported from `shared/scripts/naming.py` at the top of this file and
# re-exported here, so `from organize import looks_canonical` keeps working
# for every caller SKILL.md documents.  They are not defined here: one home
# per fact (CONVENTIONS.md §1a, §5).


# ---------------------------------------------------------------------------
# splitting
# ---------------------------------------------------------------------------

def _norm(s):
    """Whitespace-collapsed, lowercased.

    PDF text extraction inserts line breaks and double spaces inside headings;
    comparing raw strings makes a correct mapping look wrong.
    """
    return re.sub(r"\s+", " ", (s or "")).strip().lower()


def _reader(pdf_path):
    """An open `PdfReader`, or `SplitRefused` with a reason in words."""
    try:
        from pypdf import PdfReader
    except ImportError as exc:                        # pragma: no cover
        raise SplitRefused(
            "pypdf is not installed, so no PDF can be split. Use a virtual "
            "environment with the plugin dependencies; see shared/RUNTIME.md. "
            "The rename half needs only the standard library.") from exc
    try:
        reader = PdfReader(pdf_path)
        if reader.is_encrypted:
            try:
                unlocked = reader.decrypt("")
            except Exception as exc:
                raise SplitRefused("%s: encrypted and unreadable (%s) — stop, "
                                   "don't split." % (pdf_path, type(exc).__name__))
            if not unlocked:
                raise SplitRefused("%s: encrypted, no password — stop, don't "
                                   "split." % pdf_path)
        len(reader.pages)
    except SplitRefused:
        raise
    except Exception as exc:
        raise SplitRefused("%s: not a readable PDF (%s: %s). Re-download it — "
                           "this is not an OCR problem."
                           % (pdf_path, type(exc).__name__, exc))
    return reader


def _resolve(chapters, text, n_pages, out_dir, taken, book_stem=None):
    """(plan, problems, notes) — pass 1 of `split_book`.  Writes nothing."""
    plan, problems, notes, seen = [], [], [], {}
    last_chapter_number = None
    for position, ch in enumerate(chapters, 1):
        if not isinstance(ch, dict):
            problems.append("chapter item %d: expected a JSON object, got %s"
                            % (position, type(ch).__name__))
            continue
        missing = {"heading_text", "filename", "start_idx", "end_idx"} - set(ch)
        if missing:
            problems.append("chapter %r: missing %s"
                            % (ch.get("filename", ch), ", ".join(sorted(missing))))
            continue
        if not isinstance(ch["heading_text"], str):
            problems.append("chapter item %d: heading_text must be a string, got %s"
                            % (position, type(ch["heading_text"]).__name__))
            continue
        if not isinstance(ch["filename"], str):
            problems.append("chapter item %d: filename must be a string, got %s"
                            % (position, type(ch["filename"]).__name__))
            continue
        name, needle = ch["filename"], _norm(ch["heading_text"])
        start, end = ch["start_idx"], ch["end_idx"]

        if not (SAFE_NAME.match(name) and name.lower().endswith(".pdf")
                and len(os.fsencode(name)) <= MAX_NAME_BYTES):
            problems.append("%r: not a usable filename — ASCII letters, "
                            "digits, `_`, `-`, `.` only, under %d bytes, "
                            "ending in .pdf. Transliterate and abbreviate "
                            "harder." % (name, MAX_NAME_BYTES))
            continue
        # §1a is a contract, and split_book is one of its two producers: a
        # chapter name that is merely `SAFE_NAME` can still be one both §1a
        # consumers refuse as unorganized, or one stamped with ANOTHER book's
        # stem -- which files this book's chapter figures under that book.
        # `looks_canonical` and `chapter_book_stem` were imported and never
        # applied to the names this function writes.
        chap_stem = os.path.splitext(name)[0]
        if not looks_canonical(chap_stem, is_stem=True):
            problems.append("%r: not a name pdf-organizer produces, so "
                            "pdf-figure-extractor and paper-summarizer will "
                            "refuse it as unorganized. Use "
                            "Author_Work_Year_NN_ChapterName.pdf with a "
                            "two-digit NN (CONVENTIONS.md 1a)." % name)
            continue
        of_book = chapter_book_stem(chap_stem, is_stem=True)
        if of_book is None:
            problems.append("%r: has no `_NN_ChapterName` segment, so nothing "
                            "downstream can tell it is a chapter of this book."
                            % name)
            continue
        if book_stem is not None and core_stem(of_book, is_stem=True) != core_stem(book_stem, is_stem=True):
            problems.append("%r: names chapter of %r, but the book being split "
                            "is %r. Chapters carry their own book's stem, or "
                            "their figures are filed under the other book's."
                            % (name, of_book, book_stem))
            continue
        chapter_number = int(chapter_parts(chap_stem, is_stem=True).number)
        if (last_chapter_number is not None
                and chapter_number <= last_chapter_number):
            problems.append(
                "%s: chapter number %02d is not after the preceding chapter "
                "number %02d; filenames must follow book order"
                % (name, chapter_number, last_chapter_number))
            continue
        last_chapter_number = chapter_number
        if len(needle) < 3:
            problems.append("%s: heading_text %r is too short to verify a page "
                            "mapping with — give the chapter's printed "
                            "heading, not a placeholder."
                            % (name, ch["heading_text"]))
            continue
        if (isinstance(start, bool) or isinstance(end, bool)
                or not isinstance(start, int) or not isinstance(end, int)):
            problems.append("%s: start_idx/end_idx must be integer 0-based "
                            "page indices, got %r and %r"
                            % (name, start, end))
            continue
        heading_pages = [index for index, page in enumerate(text)
                         if needle in page]
        if len(heading_pages) > 2:
            problems.append(
                "%s: heading_text %r appears on %d pages, so it may be a "
                "running header and cannot verify the start page. Use a "
                "longer heading or subtitle unique to the chapter opening."
                % (name, ch["heading_text"], len(heading_pages)))
            continue

        # Verify the mapped start page really carries the heading; TOC mappings
        # are commonly off by a page or two. Don't guess beyond +/-2.
        #
        # Both corrections are reported, and that is not decoration: a start
        # this function moved is the evidence that the caller's page mapping is
        # off — the 0-based/1-based slip `references/book-splitting.md` calls
        # the one pitfall the code cannot fix — and one chapter corrected by
        # one page means the whole TOC is, including every chapter that
        # happened to land on a page carrying its heading anyway.  That file
        # promises the correction is "corrected and reported rather than
        # shipped" and the workflow's step 6 tells the reader to repeat the
        # `note:` lines; `notes` was appended to for the end trim alone, so a
        # caller doing `notes = split_book(...)` got [] and reported a clean
        # split of a book whose starts had all been moved under them.
        if not (0 <= start < n_pages) or needle not in text[start]:
            for cand in (start - 1, start + 1, start - 2, start + 2):
                if 0 <= cand < n_pages and needle in text[cand]:
                    notes.append("%s: start corrected from page %d to %d — the "
                                 "heading is not on the page the mapping gave"
                                 % (name, start + 1, cand + 1))
                    start = cand
                    break
            else:
                problems.append("%s: heading %r not found within +/-2 pages "
                                "of %s" % (name, ch["heading_text"],
                                           ch["start_idx"]))
                continue

        # Pull in a standalone chapter title page immediately before.
        if start > 0 and len(text[start - 1]) < 200 and needle in text[start - 1]:
            notes.append("%s: start moved from page %d to %d to take in the "
                         "chapter title page before it" % (name, start + 1, start))
            start -= 1

        # `islink` as well as `exists`: a broken symlink is not `exists`, and
        # `os.replace` would silently consume it. Case variants share the
        # portable destination identity.
        target = os.path.join(out_dir, name)
        clash = next((f for f in _listdir(out_dir)
                      if f.lower() == name.lower()), None)
        if clash or os.path.islink(target):
            problems.append("%s: already in %s (as %s) — would be overwritten"
                            % (name, out_dir, clash or name))
            continue
        # Keyed on the lowercased name for the same reason: `seen` used to be
        # case-sensitive while the vault-wide `taken` check below was not, so
        # two chapters differing only in case both passed the resolve pass and
        # the second `os.replace` destroyed the first — a silent half-split,
        # inside the function whose whole design is "resolve everything, then
        # write".
        if name.lower() in seen:
            problems.append("%s: two chapters resolve to this filename (also "
                            "%r; filenames differing only in case share one "
                            "portable destination identity) — keep more words "
                            "in each" % (name, seen[name.lower()]))
            continue
        if name.lower() in taken:
            problems.append("%s: a file of this name is already in the vault "
                            "at %s — basenames must be unique vault-wide "
                            "(CONVENTIONS.md 1a(1))"
                            % (name, ", ".join(taken[name.lower()])))
            continue
        seen[name.lower()] = ch["heading_text"]
        plan.append([start, end, target, name])

    # Ranges: chapters run in book order and must not overlap. A start that
    # goes backwards means the page mapping is wrong, not that a chapter is
    # long — refuse. An end that runs into the next chapter or past EOF is
    # trimmed, and the trim is reported: it is evidence the TOC was misread.
    for i in range(1, len(plan)):
        if plan[i][0] <= plan[i - 1][0]:
            problems.append("%s: starts at page %d, at or before %s (%d) — the "
                            "page mapping is out of order; re-derive it first"
                            % (plan[i][3], plan[i][0] + 1, plan[i - 1][3],
                               plan[i - 1][0] + 1))
    if not problems:
        for i, (start, end, _target, name) in enumerate(plan):
            nxt = plan[i + 1][0] if i + 1 < len(plan) else n_pages
            if end > nxt:
                notes.append("%s: end trimmed from %d to %d" % (name, end, nxt))
                plan[i][1] = end = nxt
            if end <= start:
                problems.append("%s: empty page range after resolving the "
                                "start page (%d..%d)" % (name, start, end))
    return plan, problems, notes


def _publish_new(staged, target):
    """Publish a staged chapter only when ``target`` is still unoccupied.

    The shared helper links exclusively, reads the public entry back, and on a
    verification failure withdraws only the exact unmodified staged snapshot.
    A file created after inventory or an editor save after linking is retained.
    """
    target_dir = os.path.realpath(os.path.dirname(target) or ".")
    stage_parent = os.path.dirname(target_dir)
    return publish_new(
        staged, target, _published_snapshot, stage_parent=stage_parent,
        recovery_prefix=".organize-recovery-")


def _published_snapshot(path):
    """Identity and digest of one stable regular file."""
    return _stable_file_snapshot(path)


def _remove_published(path, expected, stage_parent):
    """Remove only the exact inode this split published at ``path``."""
    if not os.path.lexists(path):
        return None
    stage = tempfile.mkdtemp(prefix=".split-rollback-", dir=stage_parent)
    keep_stage = False
    try:
        try:
            remove_expected(
                path, expected, _published_snapshot, stage,
                stage_parent=stage_parent,
                recovery_prefix=".organize-recovery-")
        except PublicationConflict as exc:
            keep_stage = exc.keep_stage
            return ("%s was retained because cleanup conflicted with a "
                    "different identity or byte snapshot: %s" % (path, exc))
        # Both private names are hard links to exactly the inode this split
        # published. Cleaning the stage removes them; a later public occupant
        # is independent and remains untouched.
        return None
    finally:
        if not keep_stage:
            shutil.rmtree(stage, ignore_errors=True)


def _rollback_split(written, out_dir, made_dir):
    """Remove this split's published chapters; return any cleanup failures."""
    failures = []
    stage_parent = os.path.dirname(os.path.realpath(out_dir))
    for path, expected in written:
        try:
            problem = _remove_published(path, expected, stage_parent)
        except OSError as exc:
            problem = "%s (%s: %s)" % (path, type(exc).__name__, exc)
        if problem:
            failures.append(problem)
    if made_dir:
        try:
            os.rmdir(out_dir)
        except FileNotFoundError:
            pass
        except OSError as exc:
            failures.append("%s [output directory] (%s: %s)" %
                            (out_dir, type(exc).__name__, exc))
    return failures


def _split_failure_message(pdf_path, written_count, plan_count, exc,
                           cleanup_failures, staging_path=None):
    """Describe a failed split without overstating its rollback state."""
    lead = "%s: write failed after %d of %d chapters (%s: %s)." % (
        pdf_path, written_count, plan_count, type(exc).__name__, exc)
    if cleanup_failures:
        message = (lead + " ROLLBACK INCOMPLETE — these paths may remain; "
                   "inspect them before retrying:\n  - "
                   + "\n  - ".join(cleanup_failures))
        if staging_path:
            message += ("\nComplete staged chapters are preserved at %s."
                        % staging_path)
        return message
    if staging_path:
        return (lead + " Rolled back all public chapters. Complete staged "
                "chapters are preserved at %s." % staging_path)
    return lead + " Rolled back — nothing from this split is on disk."


def split_book(pdf_path, chapters, out_dir, taken=None, verbose=True):
    """Split `pdf_path` into one PDF per chapter, under `out_dir`.

    `chapters` is a list of dicts in book order, each with `heading_text`,
    `filename`, `start_idx` and `end_idx` (0-based; `end_idx` exclusive) —
    see `references/book-splitting.md`.  `taken` is `vault_names(vault)`:
    every basename already in the vault, so a chapter cannot collide with a
    file in another folder.  Returns the list of `note:` strings.

    **Two passes: resolve everything, then write.**  Splitting is destructive
    and half of it is worse than none, so nothing reaches disk until every
    chapter has a verified start page, a non-overlapping in-range end page, a
    usable filename, and a target proved free vault-wide.  A write that fails
    part-way attempts to remove what this run just created. Any cleanup failure
    is named as an incomplete rollback so the caller can inspect it before
    retrying.

    A `_2`/`_3`-disambiguated book is refused outright, before anything is read
    or written: it has no legal chapter name to give.
    """
    # A disambiguator marks a DIFFERENT document — one that wanted a name
    # already taken (naming.py, `split_tail`: `_src` is the same document in
    # another representation, `_N` is not).  A book carrying one has no legal
    # chapter name to give: `Book_2_01_Intro` is not canonical, because the
    # disambiguator may not precede the chapter segment, and
    # `Book_01_Intro_2` reads as a chapter of the OTHER book — so
    # pdf-figure-extractor would file this book's chapter figures under that
    # one.  Neither failure raises, which is why it is stopped here rather than
    # at the point the names collide.
    #
    # The test is the naming rule asked forward: mint the shape every chapter
    # of this book would take and ask `naming.py` whether that is a name this
    # plugin may write.  Restating the disambiguator's own pattern here is the
    # divergent second copy CONVENTIONS.md 1a exists to prevent — it is exactly
    # how `_src`'s position came to mean two different things.  Limited to a
    # canonical standalone book: a junk name is this skill's INPUT and not a
    # refusal, and a chapter is not a book.
    identity = core_stem(pdf_path)                    # `_src` off, `_N` kept
    if looks_canonical(identity, is_stem=True) and chapter_parts(identity, is_stem=True) is None \
            and not looks_canonical(identity + "_01_Chapter", is_stem=True):
        raise SplitRefused(
            "%s: refusing to split a disambiguated book. Its document identity "
            "%r carries a `_N` disambiguator, so it is a DIFFERENT document "
            "from the one that took the plain name — and its chapters have no "
            "legal name. "
            "`%s_01_Intro` is not canonical: the disambiguator may not come "
            "before the chapter segment. Moving it after the segment instead "
            "spells a chapter of the OTHER book, which is where this book's "
            "chapter figures would then be filed. Fix: re-abbreviate the title "
            "so the two books differ BEFORE the year (e.g. "
            "`Prince_UDLPractice_2026`), rename this one with `organize.py "
            "rename`, then split it."
            % (os.path.basename(pdf_path), identity, identity))
    if not isinstance(chapters, list):
        raise SplitRefused(
            "%s: chapter plan must be a JSON array/list, got %s. Nothing was written."
            % (pdf_path, type(chapters).__name__))
    if not chapters:
        raise SplitRefused("%s: no chapters detected — ask the user for page "
                           "ranges rather than writing an empty folder."
                           % pdf_path)
    if os.path.lexists(out_dir) and not os.path.isdir(out_dir):
        raise SplitRefused("%s: output path exists but is not a directory; "
                           "refusing to replace it." % out_dir)

    # An existing chapter set is authoritative even when the new plan chose
    # different abbreviations, so checking only the exact planned targets can
    # create two parallel splits of one book. Detect any recognized chapter of
    # this book before opening the PDF or creating the output directory.
    try:
        existing_chapters = []
        for name in _listdir(out_dir):
            book = chapter_book_stem(name)
            if (book is not None
                    and _nfc_low(core_stem(book, is_stem=True))
                    == _nfc_low(identity)):
                existing_chapters.append(name)
    except InventoryFailed as exc:
        raise SplitRefused("%s: cannot verify whether a chapter set already "
                           "exists (%s). Nothing was written." % (out_dir, exc))
    if existing_chapters:
        raise SplitRefused(
            "%s: an existing chapter set for this book is authoritative (%s). "
            "Leave it unchanged; do not create a second split."
            % (out_dir, ", ".join(sorted(existing_chapters))))
    taken = taken or {}
    # `_reader` first, and the writer import after it: both come from pypdf,
    # and `_reader` is the one that turns a missing pypdf into a `SplitRefused`
    # with an install line in it. Importing PdfWriter above that call meant the
    # bare `ImportError` escaped instead — which SKILL.md's batch workflow
    # does not catch (it names `SplitRefused` and `OSError`), so the first book
    # in a 40-file batch ended the whole run with a traceback, and `_reader`'s
    # polished message was unreachable through this function.
    reader = _reader(pdf_path)
    from pypdf import PdfWriter
    n_pages = len(reader.pages)
    if n_pages == 0:
        raise SplitRefused("%s: zero pages — nothing to split." % pdf_path)

    text = []
    for p in reader.pages:
        try:
            text.append(_norm(p.extract_text()))
        except Exception:
            text.append("")                  # a damaged page is not a crash
    if not any(text):
        raise SplitRefused("%s: no extractable text (a scan?). Chapter "
                           "boundaries can't be found — OCR it first, then "
                           "re-run." % pdf_path)
    try:
        plan, problems, notes = _resolve(chapters, text, n_pages, out_dir, taken,
                                         core_stem(pdf_path))
    except InventoryFailed as exc:
        raise SplitRefused("%s: chapter destinations could not be inventoried "
                           "completely (%s). Nothing was written."
                           % (out_dir, exc))
    if problems:
        raise SplitRefused("Not splitting %s. Fix these first:\n  - "
                           % os.path.basename(pdf_path)
                           + "\n  - ".join(problems))

    # --- Pass 2: write. Every target is in range and proved free. A failure
    # part-way attempts to remove what this run just created — half a split is
    # worse than none. Any cleanup failure is retained in the error. ---
    made_dir = not os.path.isdir(out_dir)
    written = []
    stage = None
    staged_complete = []
    keep_stage = False
    try:
        os.makedirs(out_dir, exist_ok=True)
        stage_parent = os.path.dirname(os.path.realpath(out_dir))
        stage = tempfile.mkdtemp(prefix=".split-stage-", dir=stage_parent)
        for ordinal, (start, end, target, name) in enumerate(plan, 1):
            writer = PdfWriter()
            for i in range(start, end):
                writer.add_page(reader.pages[i])
            tmp = os.path.join(stage, "chapter-%04d.part" % ordinal)
            with open(tmp, "xb") as fh:
                writer.write(fh)
            staged_complete.append(tmp)
            # Exclusive publication closes the plan/write race. os.replace
            # used to overwrite a chapter that appeared after preflight.
            published = _publish_new(tmp, target)
            written.append((target, published))
            if verbose:
                print("%s  pages %d-%d" % (name, start + 1, end))
    except BaseException as exc:
        if staged_complete:
            keep_stage = True
            try:
                exc.keep_stage = True
                exc.staging_path = stage
                if getattr(exc, "recovery_path", None) is None:
                    exc.recovery_path = staged_complete[-1]
            except (AttributeError, TypeError):
                pass
        cleanup_failures = _rollback_split(written, out_dir, made_dir)
        raise SplitRefused(_split_failure_message(
            pdf_path, len(written), len(plan), exc, cleanup_failures,
            staging_path=stage if keep_stage else None)) from exc
    finally:
        if stage is not None and not keep_stage:
            shutil.rmtree(stage, ignore_errors=True)
    if verbose:
        for n in notes:
            print("note:", n)
    return notes


# ---------------------------------------------------------------------------
# command line
# ---------------------------------------------------------------------------

def _report_plan(moves, edits, blockers, apply_done):
    print("Moves (%d):" % len(moves))
    for src, dst in moves:
        mark = "" if os.path.abspath(src) != os.path.abspath(dst) \
            else "   (no change)"
        print("  %s\n    -> %s%s" % (src, dst, mark))
    print("Note rewrites (%d):" % len(edits))
    for md in sorted(edits):
        print("  %s" % md)
    if edits.published_updates:
        print("Publication-date updates (%d):" % len(edits.published_updates))
        for md in sorted(edits.published_updates):
            old, new = edits.published_updates[md]
            print("  %s: %s -> %s" % (md, old, new))
    if edits.sidecars:
        print("Figure sidecar updates (%d):" % len(edits.sidecars))
        for path in sorted(edits.sidecars):
            print("  %s" % path)
    # Its own heading, not a line under "Note rewrites": these are notes this
    # run could not read and will not touch, and printing one where a rewrite
    # goes says the opposite of what happened.
    unreadable = getattr(edits, "unreadable", ())
    if unreadable:
        print("Not read, and cite nothing this rename changes (%d):"
              % len(unreadable))
        for u in sorted(unreadable):
            print("  %s" % u)
    if blockers:
        print("BLOCKED — nothing was written. Fix these first:")
        for b in blockers:
            print("  - %s" % b)
    elif apply_done:
        print("Applied.")
    else:
        print("No blockers. Re-run with --apply to write it.")


def _cli_vault(value):
    """Resolve an explicitly supplied vault, without silently dropping typos.

    Omitting ``--vault`` deliberately selects external-file mode. Supplying a
    path that is missing or not a directory is different: treating it as an
    omission bypasses the uniqueness/reference checks the caller requested.
    """
    if value is None:
        return None
    vault = os.path.expanduser(value)
    if not os.path.isdir(vault):
        raise ValueError("--vault is not a directory: %s. Fix the path; omit "
                         "--vault only for a document genuinely outside any "
                         "vault." % vault)
    return vault


def _cmd_check(args):
    try:
        vault = _cli_vault(args.vault)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    path = os.path.expanduser(args.path)
    problem = _source_problem(path)
    if problem:
        print(problem, file=sys.stderr)
        return 1
    if not vault:
        print("No vault to scan (--vault not given). The vault-wide reference check "
              "did NOT run; say so in the report rather than reporting the "
              "file as unreferenced.")
        return 0
    if not _inside(vault, path):
        print("The source is outside --vault. Omit --vault for an independent "
              "download; matching its basename cannot establish ownership of "
              "the vault's notes or images.", file=sys.stderr)
        return 1
    try:
        keyed = keyed_files(vault, path)
    except InventoryFailed as exc:
        print("Reference check incomplete: %s" % exc, file=sys.stderr)
        return 1
    print("Names keyed to %s (%d):" % (os.path.basename(path), len(keyed)))
    for p, b in sorted(keyed.items()):
        print("  %-44s %s" % (b, p))
    try:
        refs = references(
            vault, set(keyed.values()), keyed_dirs(vault, keyed),
            {name for path, name in keyed.items()
             if os.path.isdir(path) and not os.path.islink(path)})
    except InventoryFailed as exc:
        print("Reference check incomplete: %s" % exc, file=sys.stderr)
        return 1
    if not refs:
        print("\nNo referencing-note authorization is needed. Review the "
              "rename plan: collisions, ownership, or write guards can still "
              "block it.")
        return 0
    print("\nREFERENCED — apply only with authorization to repair these references:")
    for md in sorted(refs):
        print("  %s\n    cites: %s" % (md, ", ".join(refs[md])))
    return 1


def _cmd_rename(args):
    try:
        vault = _cli_vault(args.vault)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    path = os.path.expanduser(args.path)
    if not vault:
        print("No vault (--vault not given): the vault-wide uniqueness and reference "
              "checks did not run. Only the literal destination is checked."
              )
    try:
        keyed = keyed_files(vault, path) if vault else {}
    except InventoryFailed as exc:
        print("Rename plan incomplete: %s" % exc, file=sys.stderr)
        return 1
    old = set(keyed.values())
    old_directory_names = {name for path, name in keyed.items()
                           if os.path.isdir(path) and not os.path.islink(path)}
    # Located BEFORE the rename and reused after it, so this still says where
    # each old name lived, including when --dest files the source elsewhere —
    # which is what keeps the verification below from re-reading a link to a
    # different file of that basename as an unfinished repair.
    old_dirs = keyed_dirs(vault, keyed) if keyed else None
    try:
        moves, edits, blockers = rename_all(
            vault, path, args.to, apply=args.apply,
            dest=os.path.expanduser(args.dest) if args.dest else None)
    except RenameFailed as exc:
        print(str(exc), file=sys.stderr)
        return 1 if exc.rolled_back else 2
    _report_plan(moves, edits, blockers, args.apply)
    if blockers:
        return 1
    # Filing an already canonical PDF and changing letter case leave a valid
    # basename that the case-insensitive reference probe still recognizes.
    # Only names that actually became obsolete belong in this final check.
    old.intersection_update(obsolete_names(moves))
    if args.apply and old:
        try:
            left = references(vault, old, old_dirs, old_directory_names)
        except InventoryFailed as exc:
            print("INCOMPLETE — the post-rename reference scan failed: %s" % exc,
                  file=sys.stderr)
            return 1
        if left:
            print("INCOMPLETE — these notes still cite an old name:",
                  file=sys.stderr)
            for md in sorted(left):
                print("  %s: %s" % (md, ", ".join(left[md])), file=sys.stderr)
            return 1
        print("Verified: no note cites any of the %d old names." % len(old))
    return 0


def _cmd_split(args):
    try:
        vault = _cli_vault(args.vault)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    pdf = os.path.expanduser(args.pdf)
    out = os.path.expanduser(args.out)
    book_stem = os.path.splitext(os.path.basename(pdf))[0]
    if not os.path.isabs(out):
        print("--out must be absolute; relative paths depend on the shell's "
              "working directory and cannot establish the chapter family.",
              file=sys.stderr)
        return 1
    if vault:
        if not _inside(vault, pdf):
            print("The book is outside --vault. Omit --vault and place --out "
                  "beside the external book; this command does not import it.",
                  file=sys.stderr)
            return 1
        if not _inside(vault, out):
            print("--out is outside --vault. Vault chapters must remain inside "
                  "the selected vault's source tree.", file=sys.stderr)
            return 1
        expected_parent = os.path.join(vault, "Sources", "PDFs")
    else:
        expected_parent = os.path.dirname(os.path.abspath(pdf)) or "."
    try:
        correct_parent = os.path.samefile(os.path.dirname(out), expected_parent)
    except OSError:
        correct_parent = (os.path.realpath(os.path.dirname(out))
                          == os.path.realpath(expected_parent))
    if (not correct_parent
            or _nfc_low(os.path.basename(out)) != _nfc_low(book_stem)):
        print("--out must be the canonical chapter folder %s; other locations "
              "or basenames are invisible to later organizer and extractor "
              "runs." % os.path.join(expected_parent, book_stem),
              file=sys.stderr)
        return 1
    chapters_path = os.path.expanduser(args.chapters)
    try:
        with open(chapters_path, encoding="utf-8") as fh:
            chapters = json.load(fh)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        print("Cannot read --chapters %s (%s: %s). Nothing was written."
              % (chapters_path, type(exc).__name__, exc), file=sys.stderr)
        return 1
    try:
        taken = vault_names(vault) if vault else {}
    except InventoryFailed as exc:
        print("Cannot establish vault-wide chapter-name uniqueness: %s" % exc,
              file=sys.stderr)
        return 1
    try:
        split_book(pdf, chapters, out, taken)
    except SplitRefused as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


def _cmd_canonical(args):
    bad = 0
    for name in args.names:
        ok = looks_canonical(name)
        bad += not ok
        print("%-52s %s" % (name, "canonical" if ok else "NOT canonical"))
    return 1 if bad else 0


def _selftest():
    """The adversarial fixtures this module's behaviour is pinned to.

    Every case here is one a hand-written rewrite has actually got wrong, or
    would.  Run it after touching anything above:
    `python3 organize.py selftest`.
    """
    import tempfile as _tf

    cases = []
    _test_workspace = _tf.TemporaryDirectory(prefix="organize-selftest-")
    _workspace_mkdtemp = _tf.mkdtemp

    def _make_fixture_dir(*args, **kwargs):
        """Create every fixture below one workspace cleaned at test exit."""
        kwargs["dir"] = _test_workspace.name
        return _workspace_mkdtemp(*args, **kwargs)

    def check(label, got, want):
        cases.append((label, got == want, got, want))

    def _reports_path(error, path):
        rendered = str(error)
        # Nested OSErrors can re-escape a child path more than once. The
        # generated staging/recovery basename remains stable at every nesting
        # depth, while the raw and once-escaped full paths give stronger checks
        # when their representation is available.
        escaped = repr(path)[1:-1]
        return (path in rendered or escaped in rendered
                or os.path.basename(path) in rendered)

    check("a nested error still identifies its recovery directory",
          _reports_path(
              "nested failure retained .organize-recovery-1/topic.md",
              os.path.join("vault", ".organize-recovery-1")),
          True)

    def _try_symlink(source, target, **kwargs):
        """Create a self-test symlink when the host grants that capability."""
        try:
            os.symlink(source, target, **kwargs)
        except (OSError, AttributeError, NotImplementedError):
            return False
        return True

    # 1. The new stem contains the old stem — this skill's ordinary rename.
    ren = {"UDL_2026.pdf": "Prince_UDL_2026.pdf",
           "UDL_2026": "Prince_UDL_2026",
           "UDL_2026_01_Intro.pdf": "Prince_UDL_2026_01_Intro.pdf"}
    check("new stem contains old stem",
          rewrite_text("cite [[UDL_2026_01_Intro.pdf#page=3]] and "
                       "[[UDL_2026.pdf]]", ren, {}),
          "cite [[Prince_UDL_2026_01_Intro.pdf#page=3]] and "
          "[[Prince_UDL_2026.pdf]]")

    # 2. Idempotence: the output of a rewrite must be a fixed point of it.
    #    A rewrite that is not is one re-run away from `Prince_Prince_`.
    once = rewrite_text("[[UDL_2026.pdf]] [[UDL_2026_01_Intro.pdf]] "
                        "Sources/PDFs/UDL_2026/", ren, {})
    check("rewrite is idempotent", rewrite_text(once, ren, {}), once)

    # 3. Chapter-folder key is a prefix of every chapter filename.
    check("folder key does not eat chapter names",
          rewrite_text("Sources/PDFs/UDL_2026/UDL_2026_01_Intro.pdf", ren, {}),
          "Sources/PDFs/Prince_UDL_2026/Prince_UDL_2026_01_Intro.pdf")

    # 4. Old and new differ only in case.
    check("case-only rename",
          rewrite_text("[[udl_2026.pdf]]", {"udl_2026.pdf": "UDL_2026.pdf"}, {}),
          "[[UDL_2026.pdf]]")

    # 5. A longer unrelated name must not be rewritten (the regression the
    #    boundary anchors exist for).
    check("substring of a longer name is left alone",
          rewrite_text("[[Other_Report_2020.pdf]] and [[Report_2020.pdf]]",
                       {"Report_2020.pdf": "Smith_Report_2020.pdf"}, {}),
          "[[Other_Report_2020.pdf]] and [[Smith_Report_2020.pdf]]")

    # 6. Extensionless wikilink to a markdown note.
    check("extensionless wikilink",
          rewrite_text("[[UDL_2026]] and [[UDL_2026|label]] and [[UDL_2026.md]]",
                       {"UDL_2026.md": "Prince_UDL_2026.md"},
                       {"UDL_2026": "Prince_UDL_2026"}),
          "[[Prince_UDL_2026]] and [[Prince_UDL_2026|label]] and "
          "[[Prince_UDL_2026.md]]")

    # 7. A note stem that is a prefix of a chapter note stem.
    check("stem prefix does not eat a longer stem",
          rewrite_text("[[UDL_2026_01_Intro]] [[UDL_2026]]",
                       {"UDL_2026.md": "P_UDL_2026.md",
                        "UDL_2026_01_Intro.md": "P_UDL_2026_01_Intro.md"},
                       {"UDL_2026": "P_UDL_2026",
                        "UDL_2026_01_Intro": "P_UDL_2026_01_Intro"}),
          "[[P_UDL_2026_01_Intro]] [[P_UDL_2026]]")

    # 8. Shell metacharacters, quotes, spaces and unicode in the OLD name.
    for ugly in ("download (1).pdf", "It's a draft.pdf", "'; touch x; '.pdf",
                 "Muller_Uber_2001.pdf", "a*b?c[d].pdf", "über.pdf"):
        check("ugly input name %r survives" % ugly,
              rewrite_text("see [[%s]] here" % ugly,
                           {ugly: "Smith_X_1900.pdf"}, {}),
              "see [[Smith_X_1900.pdf]] here")

    # 9. `references` agrees with `rewrite_text` about what a whole name is.
    pat, lut, _slut, _stems = _reference_re({"Report_2020.pdf"})
    check("references() is bounded, not substring",
          [m.group(0) for m in pat.finditer("Other_Report_2020.pdf "
                                            "Report_2020.pdf")],
          ["Report_2020.pdf"])
    check("references() does not see the old name inside the new one",
          [m.group(0) for m in
           _reference_re({"UDL_2026.pdf"})[0].finditer("[[Prince_UDL_2026.pdf]]")],
          [])

    # 10. A wikilink is reported under the `.md` name it resolves to, which is
    #     also what the "a note naming itself" discard compares against.
    _pat, _lut, slut, _st = _reference_re({"UDL_2026.md", "UDL_2026.pdf"})
    check("wikilink stem reports the .md filename",
          slut.get("udl_2026"), "UDL_2026.md")

    # 11. Already-processed recognition.
    for name, want in (("Smith_WealthNations_1776_2.pdf", True),
                       ("Prince_UDL_2026_02_SupLearn_src.pdf", True),
                       ("AcmeCorp_StrategyMemo_nd.pdf", True),
                       ("Kuhn_StructSciRev_2012_01_RoleHistory.pdf", True),
                       ("Backup_2023.pdf", False),
                       ("Geron_ML_1.5.pdf", False),
                       ("download (1).pdf", False)):
        check("looks_canonical(%r)" % name, looks_canonical(name), want)

    # 12. A folder-qualified wikilink is a reference.  Obsidian writes these
    #     whenever *New link format* is "Absolute path in vault" or "Relative
    #     path to file", and the pattern used to require `[[` immediately
    #     before the stem — so `references()` returned {} for a cited file, the
    #     pre-rename guard said "rename immediately", and the post-rename
    #     verification passed on a vault the rename had just broken.
    for link, want in (("[[Articles/UDL_2026]]", True),
                       ("[[Articles/UDL_2026|note]]", True),
                       ("[[Articles/UDL_2026#heading]]", True),
                       ("![[Articles/UDL_2026]]", True),
                       ("[[UDL_2026]]", True),
                       ("[[Other/NotThisOne]]", False)):
        found = bool(_reference_re({"UDL_2026.md"})[0].search(link))
        check("references() sees %s" % link, found, want)

    # 13. The folder qualification survives the rewrite verbatim: only the
    #     stem is replaced, or the link resolves somewhere else entirely.
    check("folder-qualified rewrite keeps its path",
          rewrite_text("see [[Articles/UDL_2026|the note]]",
                       {"UDL_2026.md": "Prince_UDL_2026.md"},
                       {"UDL_2026": "Prince_UDL_2026"}),
          "see [[Articles/Prince_UDL_2026|the note]]")

    # 14. The extension is never changed (SKILL.md's filename rules).
    #     A caller passing a different one has the wrong file in hand, so it
    #     is refused; a source with no extension at all is the one case where
    #     the caller's is new information rather than a contradiction.  This
    #     used to be a silent discard, which turned `download` +
    #     `Smith_X_1776.pdf` into an extensionless `Smith_X_1776`, breaking
    #     every downstream `![[...pdf]]` embed with no blocker raised.
    for src, new, want in (("download", "Smith_X_1776.pdf", "Smith_X_1776.pdf"),
                           ("paper.pdf", "Smith_X_1776.pdf", "Smith_X_1776.pdf"),
                           ("paper.pdf", "Smith_X_1776", "Smith_X_1776.pdf"),
                           ("download.PDF", "Smith_X_1776.pdf", "Smith_X_1776.PDF"),
                           ("notes.txt", "Smith_X_1776.pdf", None)):
        _v = _make_fixture_dir()
        _p = os.path.join(_v, src)
        with open(_p, "wb") as _fh:
            _fh.write(b"%PDF-1.4\n")
        _m, _e, _b = plan_rename(_v, _p, new)
        got = None if _b else os.path.basename(_m[0][1])
        check("%s --to %s" % (src, new), got, want)

    # 15. A folder-qualified wikilink names ONE path, so it refers to the keyed
    #     file only when the keyed file lives there.  The qualification used to
    #     be echoed back unread, so `[[Wiki/Sub/UDL_2026]]` — a different note
    #     that merely shares a basename with the keyed one in
    #     `Articles/` — was rewritten to a link to nothing, and the
    #     post-rename `assert not references(...)` passed because the same
    #     permissive test had stopped seeing the link it had just broken.
    _ren = {"UDL_2026.md": "Prince_UDL_2026.md"}
    _sren = {"UDL_2026": "Prince_UDL_2026"}
    _dirs = {"UDL_2026.md": {"articles", "sources/pdfs"}}
    for label, note_dir, text, want in (
            ("same path",              "Notes",
             "[[Articles/UDL_2026]]",
             "[[Articles/Prince_UDL_2026]]"),
            ("different path",         "Notes",
             "[[Wiki/Sub/UDL_2026]]",       "[[Wiki/Sub/UDL_2026]]"),
            ("../ relative form",      "Notes",
             "[[../Articles/UDL_2026]]",
             "[[../Articles/Prince_UDL_2026]]"),
            ("../ to a different path", "Notes",
             "[[../Wiki/Sub/UDL_2026]]",    "[[../Wiki/Sub/UDL_2026]]"),
            # A link relative to the citing note's own folder, with no `./`:
            # from a note in `Sources/`, `[[PDFs/x]]` names `Sources/PDFs/x`.
            ("relative, no ./ prefix", "Sources",
             "[[PDFs/UDL_2026]]",           "[[PDFs/Prince_UDL_2026]]"),
            ("bare link",              "Notes",
             "[[UDL_2026]]",                "[[Prince_UDL_2026]]"),
            ("bare link, embed",       "Wiki/Sub",
             "![[UDL_2026]]",               "![[Prince_UDL_2026]]"),
            ("piped form",             "Notes",
             "[[Articles/UDL_2026|the note]]",
             "[[Articles/Prince_UDL_2026|the note]]"),
            ("piped, different path",  "Notes",
             "[[Wiki/Sub/UDL_2026|the note]]",
             "[[Wiki/Sub/UDL_2026|the note]]"),
            ("embed form",             "Notes",
             "![[Articles/UDL_2026]]",
             "![[Articles/Prince_UDL_2026]]"),
            ("embed, different path",  "Notes",
             "![[Wiki/Sub/UDL_2026]]",      "![[Wiki/Sub/UDL_2026]]"),
            # Path comparison uses the portable case-folded identity and ignores
            # the heading anchor.
            ("path differing only in case", "Notes",
             "[[ARTICLES/UDL_2026#heading]]",
             "[[ARTICLES/Prince_UDL_2026#heading]]"),
            # A `..` climbing past the vault root names nothing in the vault.
            ("path above the vault root", "Notes",
             "[[../../Articles/UDL_2026]]",
             "[[../../Articles/UDL_2026]]")):
        check("qualified link, %s" % label,
              rewrite_text(text, _ren, _sren, _dirs, note_dir), want)

    # A folder stored NFD on disk (what macOS hands back from `os.listdir`) and
    # cited NFC in the note is ONE folder, and comparing the raw strings makes
    # the keyed file's own home read as somebody else's — `_name_variants`
    # exists for the same failure in names.  The dir below is NFC and the link
    # is NFD, which is invisible in every rendering of the two.
    _udirs = {"UDL_2026.md": {_dirkey("Müller/Articles")}}
    check("qualified link, NFD path is the same folder",
          rewrite_text("[[Müller/Articles/UDL_2026]]",
                       _ren, _sren, _udirs, ""),
          "[[Müller/Articles/Prince_UDL_2026]]")

    # Absent path information is the documented permissive default: this is the
    # standalone call every case above #15 makes, and it must not change.
    check("qualified link, no dirs given is unchanged",
          rewrite_text("[[Wiki/Sub/UDL_2026]]", _ren, _sren),
          "[[Wiki/Sub/Prince_UDL_2026]]")

    # 16. End to end, on the vault that produced the bug: the report and the
    #     rewrite have to agree, and neither may touch the note citing a
    #     DIFFERENT file of the keyed basename.
    _qv = _make_fixture_dir()

    def _w(rel, body):
        p = os.path.join(_qv, *rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(body)
        return p

    _book = _w("Sources/PDFs/UDL_2026.pdf", "%PDF")
    _w("Articles/UDL_2026.md", "![[UDL_2026.pdf]]\n")
    _w("Wiki/Sub/UDL_2026.md", "a different document\n")
    _theirs = _w("Notes/cites-the-other.md", "[[Wiki/Sub/UDL_2026]]\n")
    _ours = _w("Notes/cites-the-keyed-one.md", "[[Articles/UDL_2026]]\n")
    _keyed = keyed_files(_qv, _book)
    _refs = references(_qv, set(_keyed.values()), keyed_dirs(_qv, _keyed))
    check("references() skips a qualified link to another file of that name",
          sorted(os.path.relpath(p, _qv) for p in _refs),
          sorted([os.path.join("Articles", "UDL_2026.md"),
                  os.path.join("Notes", "cites-the-keyed-one.md")]))
    rename_all(_qv, _book, "Prince_UDL_2026.pdf", apply=True)
    check("the note citing another file of that name is left alone",
          open(_theirs, encoding="utf-8").read(), "[[Wiki/Sub/UDL_2026]]\n")
    check("the note citing the keyed file is rewritten",
          open(_ours, encoding="utf-8").read(),
          "[[Articles/Prince_UDL_2026]]\n")

    # 16b. `--dest`: the SOURCE file moves to the destination folder; every
    #      other keyed name is renamed in its own home, because that home is
    #      where its consumer looks.  A figure moved into Sources/PDFs/ beside
    #      the document would be invisible to every `Sources/Images/` glob, and
    #      a note moved out of Articles/ invisible to wiki-builder -- both
    #      silent.  The destination is also created on demand, which is the
    #      first-run case for a vault that has never had one.
    _dv = _make_fixture_dir()

    def _dw(rel, body):
        p = os.path.join(_dv, *rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(body)
        return p

    _inbox_pdf = _dw("Inbox/download (1).pdf", "%PDF")
    _dimage = _dw("Sources/Images/download (1)_fig_1.png", "x")
    _dw("Sources/Images/" + MANIFEST_FILE,
        "download (1)_fig_1.png\t" + file_digest(_dimage) + "\n")
    _dw("Articles/download (1).md", "![[download (1).pdf]]\n")
    _dmoves, _, _dblock = plan_rename(_dv, _inbox_pdf,
                                      "Smith_WealthNations_1776.pdf",
                                      dest=os.path.join(_dv, "Sources", "PDFs"))
    check("--dest: no blocker when the destination does not exist yet",
          _dblock, [])
    check("--dest: every keyed file lands in the right home",
          sorted(os.path.relpath(d, _dv).replace(os.sep, "/")
                 for _s, d in _dmoves),
          sorted(["Articles/Smith_WealthNations_1776.md",
                  "Sources/Images/Smith_WealthNations_1776_fig_1.png",
                  "Sources/PDFs/Smith_WealthNations_1776.pdf"]))
    # Without a destination nothing relocates -- the behaviour every caller
    # had before `dest` existed, and the one a rename inside the vault wants.
    _pmoves, _, _ = plan_rename(_dv, _inbox_pdf, "Smith_WealthNations_1776.pdf")
    check("no --dest: the source is renamed where it stands",
          sorted(os.path.relpath(d, _dv).replace(os.sep, "/")
                 for _s, d in _pmoves),
          sorted(["Articles/Smith_WealthNations_1776.md",
                  "Inbox/Smith_WealthNations_1776.pdf",
                  "Sources/Images/Smith_WealthNations_1776_fig_1.png"]))
    rename_all(_dv, _inbox_pdf, "Smith_WealthNations_1776.pdf", apply=True,
               dest=os.path.join(_dv, "Sources", "PDFs"))
    check("--dest: applied, and Inbox/ is empty afterwards",
          sorted(os.listdir(os.path.join(_dv, "Inbox"))), [])
    check("--dest: the document is in the destination",
          os.path.isfile(os.path.join(_dv, "Sources", "PDFs",
                                      "Smith_WealthNations_1776.pdf")), True)

    # 16c. A relative or out-of-vault `dest` is refused, not resolved against
    #      whatever directory the shell was in.  Both would move the document
    #      outside the vault while rewriting every reference to it -- the one
    #      operation with no downstream safety net, reported as a success.
    _rv = _make_fixture_dir()
    _rpdf = os.path.join(_rv, "Inbox", "download.pdf")
    os.makedirs(os.path.dirname(_rpdf))
    with open(_rpdf, "w", encoding="utf-8") as fh:
        fh.write("%PDF")
    _, _, _relb = plan_rename(_rv, _rpdf, "Smith_X_1776.pdf",
                              dest="Sources/PDFs")
    check("--dest: a relative destination is a blocker",
          bool(_relb) and "relative path" in _relb[0], True)
    _, _, _outb = plan_rename(_rv, _rpdf, "Smith_X_1776.pdf",
                              dest=_make_fixture_dir())
    check("--dest: a destination outside the vault is a blocker",
          bool(_outb) and "outside the vault" in _outb[0], True)

    # 16d. A note citing the moved file by a FOLDER-QUALIFIED link must not be
    #      left pointing at the folder the file just left.  Rewriting the name
    #      inside the old qualification is a working link turned dangling --
    #      silently, and the post-rename re-probe cannot see it because it
    #      searches for old NAMES and this one carries the new one.
    _qv2 = _make_fixture_dir()

    def _qw(rel, body):
        p = os.path.join(_qv2, *rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(body)
        return p

    _qpdf = _qw("Inbox/download.pdf", "%PDF")
    # Every form a qualified reference takes: embed, plain link, display pipe,
    # heading anchor, and a `../`-relative spelling from a nested note.
    _qnote = _qw("Wiki/e.md",
                 "![[Inbox/download.pdf]]\n"
                 "[[Inbox/download.pdf]]\n"
                 "[[Inbox/download.pdf|the book]]\n"
                 "[[Inbox/download.pdf#page=4]]\n")
    _qdeep = _qw("Wiki/Sub/f.md", "[[../../Inbox/download.pdf]]\n")
    rename_all(_qv2, _qpdf, "Smith_X_1776.pdf", apply=True,
               dest=os.path.join(_qv2, "Sources", "PDFs"))
    check("--dest: every qualified form loses the old folder",
          open(_qnote, encoding="utf-8").read(),
          "![[Smith_X_1776.pdf]]\n"
          "[[Smith_X_1776.pdf]]\n"
          "[[Smith_X_1776.pdf|the book]]\n"
          "[[Smith_X_1776.pdf#page=4]]\n")
    check("--dest: a ../-relative qualification too",
          open(_qdeep, encoding="utf-8").read(), "[[Smith_X_1776.pdf]]\n")

    # 16e. The forms a narrower terminator set silently skipped, and the one
    #      form that must NOT be touched.  Each of these was a working link
    #      turned dangling, certified by a re-probe that searches old names.
    _fv = _make_fixture_dir()

    def _fw(rel, body):
        p = os.path.join(_fv, *rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(body)
        return p

    _fpdf = _fw("Inbox/download.pdf", "%PDF")
    # A markdown table escapes the display pipe; a markdown-style link ends in
    # `)` rather than `]]`.  Both are rewritten by the name pass, so both have
    # to be debased by this one.
    _ftable = _fw("Wiki/t.md",
                  "| a | [[Inbox/download.pdf\\|the book]] |\n"
                  "[the book](Inbox/download.pdf)\n"
                  "[the book](Inbox/download.pdf#page=3)\n")
    # A DIFFERENT file whose name equals the new STEM. Its qualification is
    # right and must survive: debasing the stem form drops the folder and
    # repoints the link at whatever Obsidian resolves by proximity -- and it
    # does so without consulting `dirs`, so `_qualifies` never sees it.
    _fw("Notes/Smith_X_1776.md", "one document of that slug\n")
    _fw("Wiki/Smith_X_1776.md", "a different document of that slug\n")
    _fother = _fw("Wiki/u.md", "[[Wiki/Smith_X_1776]] and [[Notes/download]]\n")
    rename_all(_fv, _fpdf, "Smith_X_1776.pdf", apply=True,
               dest=os.path.join(_fv, "Sources", "PDFs"))
    check("--dest: an escaped display pipe is debased too",
          open(_ftable, encoding="utf-8").read(),
          "| a | [[Smith_X_1776.pdf\\|the book]] |\n"
          "[the book](Smith_X_1776.pdf)\n"
          "[the book](Smith_X_1776.pdf#page=3)\n")
    check("--dest: an extensionless link to a DIFFERENT file is untouched",
          open(_fother, encoding="utf-8").read(),
          "[[Wiki/Smith_X_1776]] and [[Notes/download]]\n")

    # 16f. A relative destination has to be refused where the CLI can reach
    #      it.  Resolving it for the caller turns the refusal into the failure
    #      it describes: `--dest Sources/PDFs` run from inside the vault lands
    #      the document in `<vault>/Sources/Sources/PDFs/`, still "inside the
    #      vault", and the run reports success.
    _rv = _make_fixture_dir()
    _rpdf = os.path.join(_rv, "Inbox", "download.pdf")
    os.makedirs(os.path.dirname(_rpdf))
    with open(_rpdf, "w", encoding="utf-8") as fh:
        fh.write("%PDF")
    _, _, _relb = plan_rename(_rv, _rpdf, "Smith_X_1776.pdf",
                              dest="Sources/PDFs")
    check("--dest: a relative destination is a blocker",
          bool(_relb) and any("relative path" in b for b in _relb), True)
    _, _, _outb = plan_rename(_rv, _rpdf, "Smith_X_1776.pdf",
                              dest=_make_fixture_dir())
    check("--dest: a destination outside the vault is a blocker",
          bool(_outb) and any("outside the vault" in b for b in _outb), True)
    _, _, _novb = plan_rename(None, _rpdf, "Smith_X_1776.pdf",
                              dest=os.path.join(_rv, "Sources", "PDFs"))
    check("--dest: no vault to move into is a blocker",
          bool(_novb) and any("no vault" in b for b in _novb), True)
    _outside = os.path.join(_make_fixture_dir(), "download.pdf")
    with open(_outside, "w", encoding="utf-8") as fh:
        fh.write("%PDF")
    _, _, _impb = plan_rename(_rv, _outside, "Smith_X_1776.pdf",
                              dest=os.path.join(_rv, "Sources", "PDFs"))
    check("--dest: a file outside the vault is never imported",
          bool(_impb) and any("outside the vault" in b for b in _impb), True)

    # 16g. `Articles/` holds two kinds of note under one filename shape, and
    #      only a note ABOUT this document is derived from its name.  Renaming
    #      a clipping note because its slug matched a PDF's stem breaks the
    #      dedup index that stops the user's polished note being clobbered.
    _nv = _make_fixture_dir()

    def _nw(rel, body):
        p = os.path.join(_nv, *rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(body)
        return p

    _npdf = _nw("Sources/PDFs/Doe_Foo_2025.pdf", "%PDF")
    _nw("Articles/Doe_Foo_2025.md",
        '---\ntitle: x\nsource: https://example.com/doe-foo\n---\nprose\n')
    check("a clipping note that merely shares the stem is NOT keyed",
          sorted(os.path.basename(p) for p in keyed_files(_nv, _npdf)),
          ["Doe_Foo_2025.pdf"])
    _nw("Articles/Doe_Foo_2025.md",
        '---\ntitle: x\nsource: "[[Doe_Foo_2025.pdf]]"\n---\nprose\n')
    check("a summary note ABOUT this document IS keyed",
          sorted(os.path.basename(p) for p in keyed_files(_nv, _npdf)),
          ["Doe_Foo_2025.md", "Doe_Foo_2025.pdf"])
    # An indented `source:` under another key must not be read as the note's.
    _nw("Articles/Doe_Foo_2025.md",
        '---\ntitle: x\ncitation:\n  source: "[[Other_Paper_2020.pdf]]"\n'
        'source: "[[Doe_Foo_2025.pdf]]"\n---\nprose\n')
    check("a nested source: does not win over the real one",
          sorted(os.path.basename(p) for p in keyed_files(_nv, _npdf)),
          ["Doe_Foo_2025.md", "Doe_Foo_2025.pdf"])
    # A shared filename does not establish ownership of a legacy user note.
    _nw("Articles/Doe_Foo_2025.md", "just a body\n")
    check("a note with no source provenance remains unclaimed",
          sorted(os.path.basename(p) for p in keyed_files(_nv, _npdf)),
          ["Doe_Foo_2025.pdf"])
    _nw("Articles/Doe_Foo_2025.md", "![[Doe_Foo_2025.pdf]]\n")
    check("an exact legacy PDF embed establishes note ownership",
          sorted(os.path.basename(p) for p in keyed_files(_nv, _npdf)),
          ["Doe_Foo_2025.md", "Doe_Foo_2025.pdf"])
    # ...and the CURRENT schema (CONVENTIONS 2b): the origin is item 1 of a
    # block-form `sources:` list, not a scalar.  The reader used to see only
    # the scalar, so every current-schema note fell through to the
    # claimed-by-default branch — and a CLIPPING whose slug matched the PDF's
    # stem was renamed with it, the exact failure this guard exists to stop.
    _nw("Articles/Doe_Foo_2025.md",
        '---\ntitle: x\nsources:\n  - "https://example.com/doe-foo"\n---\n'
        'prose\n')
    check("a current-schema clipping (sources: item 1 a URL) is NOT keyed",
          sorted(os.path.basename(p) for p in keyed_files(_nv, _npdf)),
          ["Doe_Foo_2025.pdf"])
    _nw("Articles/Doe_Foo_2025.md",
        '---\ntitle: x\nsources:\n  - "[[Doe_Foo_2025.pdf]]"\n---\nprose\n')
    check("a current-schema summary note (sources: item 1 the wikilink) IS keyed",
          sorted(os.path.basename(p) for p in keyed_files(_nv, _npdf)),
          ["Doe_Foo_2025.md", "Doe_Foo_2025.pdf"])
    _nw("Articles/Doe_Foo_2025.md",
        '---\ntitle: x\nsources:\n  - "[[Doe_Foo_2025.pdf#page=3]]"\n---\n'
        'prose\n')
    check("...a page anchor on item 1 does not change the verdict",
          sorted(os.path.basename(p) for p in keyed_files(_nv, _npdf)),
          ["Doe_Foo_2025.md", "Doe_Foo_2025.pdf"])
    # A trailing YAML comment on a quoted item is dropped, as the sibling
    # readers drop it: without the strip, our OWN summary note read as
    # somebody else's clipping and was left behind by its document's rename.
    _nw("Articles/Doe_Foo_2025.md",
        '---\ntitle: x\nsources:\n  - "[[Doe_Foo_2025.pdf]]" # verified\n---\n'
        'prose\n')
    check("a trailing comment on the quoted item does not unclaim the note",
          sorted(os.path.basename(p) for p in keyed_files(_nv, _npdf)),
          ["Doe_Foo_2025.md", "Doe_Foo_2025.pdf"])
    # A comment or blank line BETWEEN `sources:` and item 1 is valid YAML;
    # consuming the pending flag on it left the real item unread, and the
    # claimed-by-default branch then swept a URL clipping into the rename.
    _nw("Articles/Doe_Foo_2025.md",
        '---\ntitle: x\nsources:\n  # capture URL\n'
        '  - "https://example.com/doe-foo"\n---\nprose\n')
    check("a comment line between sources: and item 1 does not blind the "
          "reader — the URL clipping stays un-keyed",
          sorted(os.path.basename(p) for p in keyed_files(_nv, _npdf)),
          ["Doe_Foo_2025.pdf"])
    _nw("Articles/Doe_Foo_2025.md",
        '---\ntitle: x\nsources:\n\n  - "[[Doe_Foo_2025.pdf]]"\n---\nprose\n')
    check("...and a blank line there does not unclaim a summary note",
          sorted(os.path.basename(p) for p in keyed_files(_nv, _npdf)),
          ["Doe_Foo_2025.md", "Doe_Foo_2025.pdf"])
    # An indented `---` is content inside a YAML block scalar, not the
    # frontmatter's closing fence. Treating `line.strip() == "---"` as a
    # delimiter stopped before the real `sources:` field and left this owned
    # summary behind during its PDF rename.
    _block_scalar_note = _nw(
        "Articles/Doe_Foo_2025.md",
        '---\nabstract: |\n  First paragraph.\n  ---\n  Second paragraph.\n'
        'sources:\n  - "[[Doe_Foo_2025.pdf]]"\n---\nprose\n')
    check("an indented block-scalar rule is not a frontmatter closing fence",
          sorted(os.path.basename(p) for p in keyed_files(_nv, _npdf)),
          ["Doe_Foo_2025.md", "Doe_Foo_2025.pdf"])
    _nw("Articles/Doe_Foo_2025.md",
        '--- \t\ntitle: x\nsources:\n  - "[[Doe_Foo_2025.pdf]]"\n---  \n')
    check("column-zero fences retain the readers' trailing-whitespace tolerance",
          sorted(os.path.basename(p) for p in keyed_files(_nv, _npdf)),
          ["Doe_Foo_2025.md", "Doe_Foo_2025.pdf"])
    _escaped_block = (
        '---\nabstract: |\n  Before.\n  ---\n  After.\n'
        'sources:\n  - "[[\\x44oe_Foo_2025.pdf]]"\n---\n')
    check("reference repair reaches quoted metadata after an indented rule",
          "[[Smith_Bar_2026.pdf]]" in rewrite_text(
              _escaped_block,
              {"Doe_Foo_2025.pdf": "Smith_Bar_2026.pdf"}, {}),
          True)
    # End to end: the clipping is not merely un-keyed, it is absent from the
    # rename plan — the note stays where the user's clipping run put it.
    _nw("Articles/Doe_Foo_2025.md",
        '---\ntitle: x\nsources:\n  - "https://example.com/doe-foo"\n---\n'
        'prose\n')
    _cmoves, _, _cblock = plan_rename(_nv, _npdf, "Smith_Match_2026.pdf")
    check("a current-schema clipping is not in the rename plan",
          (sorted(os.path.basename(s) for s, _d in _cmoves), _cblock),
          (["Doe_Foo_2025.pdf"], []))

    for _source_header in (
            "sources: # origin\n- 'https://example.org/O''Reilly'\n",
            "sources: null\n",
            "sources:\n  -\n",
            'sources:\n  - "[[Doe_Foo_2025.pdf]]\n',
            'source: "[[Doe_Foo_2025.pdf]]"\nsources:\n'
            '  - "https://example.org/clipping"\n'):
        _note = _nw("Articles/Doe_Foo_2025.md", "---\n" + _source_header + "---\n")
        check("foreign or malformed source metadata cannot claim a note: %r" % _source_header,
              _note_is_about(_note, "Doe_Foo_2025"), False)
    _note = _nw("Articles/Doe_Foo_2025.md",
                '---\nsources: # origin\n- "[[Doe_Foo_2025.pdf]]"\n---\n')
    check("commented keys and indentless source sequences preserve ownership",
          _note_is_about(_note, "Doe_Foo_2025"), True)
    with open(_note, "wb") as _fh:
        _fh.write(b"---\ntitle: caf\xe9\n---\n")
    check("unreadable source metadata cannot claim a foreign note",
          _note_is_about(_note, "Doe_Foo_2025"), False)

    # 16h. The organized filename and a paper summary's `published` value are
    #      one invariant. A source-year correction must not carry the owned
    #      note under a new stem while leaving contradictory metadata behind.
    _published_note = (
        "---\n"
        "title: Example\n"
        "sources:\n"
        "  - \"[[Doe_Foo_2024.pdf]]\"\n"
        "published: 2024-03-14   # document date\n"
        "created: 2026-09-04\n"
        "---\n"
        "See [[Doe_Foo_2024.pdf]].\n")
    _reconciled, _old_published, _new_published = \
        _reconcile_published_year(_published_note, "2026")
    check("a source-year correction preserves a valid month/day and comment",
          (_old_published, _new_published,
           "published: 2026-03-14   # document date" in _reconciled),
          ("2024-03-14", "2026-03-14", True))
    _null_note = _published_note.replace(
        "published: 2024-03-14   # document date", "published: null")
    check("a null publication date gains the target year with explicit padding",
          _reconcile_published_year(_null_note, "2026")[1:],
          ("null", "2026-01-01"))
    check("an undated target gets the canonical explicit null",
          _reconcile_published_year(_published_note, "nd")[1:],
          ("2024-03-14", "null"))
    check("a current summary with missing published metadata is recognized",
          _is_paper_summary_metadata(
              "---\nformat: Paper\nsources:\n  - \"[[Doe_Foo_2024.pdf]]\"\n---\n"),
          True)
    check("an embed-only legacy source note is not converted into a summary",
          _is_paper_summary_metadata("![[Doe_Foo_2024.pdf]]\n"), False)

    for _label, _bad_published, _target, _reason in (
            ("missing", "", "2026", "missing"),
            ("duplicate", "published: 2024-03-14\n"
             "published: 2024-03-15\n", "2026", "duplicated"),
            ("quoted", 'published: "2024-03-14"\n', "2026", "unquoted"),
            ("impossible", "published: 2024-02-30\n", "2026", "not a real date"),
            ("leap-day conflict", "published: 2024-02-29\n", "2025",
             "cannot be preserved")):
        _bad_note = "---\n" + _bad_published + "created: 2026-09-04\n---\n"
        try:
            _reconcile_published_year(_bad_note, _target)
            _error = ""
        except ValueError as _exc:
            _error = str(_exc)
        check("malformed or ambiguous publication metadata blocks: " + _label,
              _reason in _error, True)

    _yv = _make_fixture_dir()

    def _yw(rel, body):
        p = os.path.join(_yv, *rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(body)
        return p

    _ypdf = _yw("Sources/PDFs/Doe_Foo_2024.pdf", "%PDF")
    _ynote = _yw("Articles/Doe_Foo_2024.md", _published_note)
    _yother = _yw(
        "Wiki/context.md",
        "---\npublished: 1999-12-31\n---\n[[Doe_Foo_2024.pdf]]\n")
    _ymoves, _yedits, _yblock = plan_rename(
        _yv, _ypdf, "Doe_Foo_2026.pdf")
    check("the dry-run plans the owned note's publication-date update",
          (_yblock, _yedits.published_updates.get(_ynote),
           "published: 2026-03-14" in _yedits.get(_ynote, "")),
          ([], ("2024-03-14", "2026-03-14"), True))
    check("a citing note keeps its own publication date",
          ("published: 1999-12-31" in _yedits.get(_yother, ""),
           "published: 2026-12-31" not in _yedits.get(_yother, "")),
          (True, True))
    check("the dry-run leaves the source family unchanged",
          (os.path.isfile(_ypdf),
           "published: 2024-03-14" in open(
               _ynote, encoding="utf-8").read()),
          (True, True))
    rename_all(_yv, _ypdf, "Doe_Foo_2026.pdf", apply=True)
    _ypdf = os.path.join(_yv, "Sources/PDFs/Doe_Foo_2026.pdf")
    _ynote = os.path.join(_yv, "Articles/Doe_Foo_2026.md")
    check("the source, link, and publication date change in one transaction",
          (os.path.isfile(_ypdf),
           "published: 2026-03-14" in open(
               _ynote, encoding="utf-8").read(),
           "[[Doe_Foo_2026.pdf]]" in open(
               _ynote, encoding="utf-8").read()),
          (True, True, True))
    _ambiguous = open(_ynote, encoding="utf-8").read().replace(
        "published: 2026-03-14   # document date",
        "published: 2026-03-14\npublished: 2026-03-15")
    with open(_ynote, "w", encoding="utf-8") as _fh:
        _fh.write(_ambiguous)
    _ymoves, _yedits, _yblock = rename_all(
        _yv, _ypdf, "Doe_Foo_2027.pdf", apply=True)
    check("ambiguous owned metadata blocks the whole applied rename",
          (any("duplicated" in item for item in _yblock),
           os.path.isfile(_ypdf),
           open(_ynote, encoding="utf-8").read()),
          (True, True, _ambiguous))

    # NFC/NFD twin figure files derive to ONE new name (`_derive` writes NFC)
    # and must be a BLOCKER, exactly like the case-twin pair: grouped under
    # `b.lower()` the twins landed in two groups, sailed past the guard, and
    # the second `os.rename` silently destroyed the first figure's bytes.
    _uv = _make_fixture_dir()
    _updf = os.path.join(_uv, "Inbox", "Müller_Uber_2001.pdf")
    os.makedirs(os.path.dirname(_updf))
    with open(_updf, "w", encoding="utf-8") as fh:
        fh.write("%PDF")
    os.makedirs(os.path.join(_uv, "Sources", "Images"))
    _twins = ("Müller_Uber_2001_fig_1.png",         # NFC
              "Müller_Uber_2001_fig_1.png")         # NFD
    for _twin in _twins:
        with open(os.path.join(_uv, "Sources", "Images", _twin), "w",
                  encoding="utf-8") as fh:
            fh.write(_twin)
    # Model a normalization-sensitive directory listing so the collision guard
    # is exercised on every test host without depending on its filesystem.
    from unittest.mock import patch
    _real_listdir = _listdir
    _images_dir = os.path.join(_uv, "Sources", "Images")
    def _twin_listing(directory):
        return list(_twins) if directory == _images_dir else _real_listdir(directory)
    with patch.dict(globals(), _listdir=_twin_listing):
        _tm, _tren, _tblock = plan_rename(_uv, _updf, "Muller_New_2001.pdf")
    check("NFC/NFD twin figures deriving onto one name are a blocker, "
          "never a silent overwrite",
          any("case/normalization" in b and "one name" in b for b in _tblock),
          True)

    # 16h. Every level of an absent destination is created.
    _mv = _make_fixture_dir()
    _mpdf = os.path.join(_mv, "Inbox", "download.pdf")
    os.makedirs(os.path.dirname(_mpdf))
    with open(_mpdf, "w", encoding="utf-8") as fh:
        fh.write("%PDF")
    rename_all(_mv, _mpdf, "Smith_X_1776.pdf", apply=True,
               dest=os.path.join(_mv, "Sources", "PDFs"))
    check("--dest: intermediate levels are created, not just the leaf",
          os.path.isfile(os.path.join(_mv, "Sources", "PDFs",
                                      "Smith_X_1776.pdf")), True)

    # 16i. PDFs only.  The rename machinery is extension-agnostic, so nothing
    #      but this guard stops a `.epub` being filed into `Sources/PDFs/`,
    #      where every consumer globs `*.pdf` and none would ever see it.
    _pv = _make_fixture_dir()
    for _name, _to, _want in (("book.epub", "Smith_X_1776.epub", True),
                              ("book.epub", "Smith_X_1776.pdf", True),
                              ("paper.docx", "Smith_X_1776.docx", True),
                              ("notes.txt", "Smith_X_1776.txt", True),
                              ("paper.PDF", "Smith_X_1776.pdf", False),
                              ("paper.pdf", "Smith_X_1776.pdf", False),
                              # No extension at all: a browser save, and the
                              # caller supplies the one that lands on disk.
                              ("download", "Smith_X_1776.pdf", False)):
        _p = os.path.join(_pv, _name)
        with open(_p, "w", encoding="utf-8") as fh:
            fh.write("%PDF")
        _, _, _pb = plan_rename(_pv, _p, _to)
        check("PDFs only: %s -> %s blocked" % (_name, _to),
              bool(_pb) and any("organises PDFs" in b for b in _pb), _want)
    # ...and a rename that does NOT move keeps the qualification untouched.
    _qv3 = _make_fixture_dir()

    def _qw3(rel, body):
        p = os.path.join(_qv3, *rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(body)
        return p

    _spdf = _qw3("Sources/PDFs/download.pdf", "%PDF")
    _snote = _qw3("Wiki/e.md", "![[Sources/PDFs/download.pdf]]\n")
    rename_all(_qv3, _spdf, "Smith_X_1776.pdf", apply=True)
    check("no move: the qualification is left exactly as the user wrote it",
          open(_snote, encoding="utf-8").read(),
          "![[Sources/PDFs/Smith_X_1776.pdf]]\n")

    # 17. A `_N`-disambiguated book is not split: its chapters have no legal
    #     name, and minting one anyway files this book's chapters — and every
    #     figure pdf-figure-extractor pulls from them — under the OTHER book.
    #     The book file is deliberately never created: a refusal naming the
    #     disambiguator therefore proves the guard ran before anything was
    #     read, which is the whole point of putting it at the top.  The others
    #     fall through to `_reader` and are refused for the missing file
    #     instead — not for their name.
    for stem, refuses in (("Prince_UDL_2026", False),
                          ("Prince_UDL_2026_src", False),
                          ("Prince_UDL_2026_2", True),
                          ("Prince_UDL_2026_src_2", True),
                          ("download", False)):        # junk: input, not refusal
        _sv = _make_fixture_dir()
        _sp = os.path.join(_sv, stem + ".pdf")
        try:
            split_book(_sp, [], os.path.join(_sv, stem), verbose=False)
            got = ""
        except SplitRefused as exc:
            got = str(exc)
        check("split_book refuses %s.pdf" % stem,
              "disambiguated book" in got, refuses)
        check("split_book writes nothing for %s.pdf" % stem,
              os.path.isdir(os.path.join(_sv, stem)), False)

    # --- the review pass of 2026-08-10.  Every one of these was a reproduced
    # --- corruption path: a link repointed at the wrong document, a URL
    # --- mangled, a symlinked document orphaned, a chapter name no consumer
    # --- accepts, a vault-wide dead-end on one stray legacy note.
    def _vault(*dirs):
        v = _make_fixture_dir(prefix="orgtest-")
        for d in dirs:
            os.makedirs(os.path.join(v, *d.split("/")), exist_ok=True)
        return v

    def _put(v, rel, data=b"%PDF-1.4\n"):
        p_ = os.path.join(v, *rel.split("/"))
        os.makedirs(os.path.dirname(p_), exist_ok=True)
        mode = "wb" if isinstance(data, bytes) else "w"
        kwargs = ({} if mode == "wb" else
                  {"encoding": "utf-8", "newline": ""})
        with open(p_, mode, **kwargs) as fh:
            fh.write(data)
        return p_

    # A folder-qualified link naming a DIFFERENT file of the same basename.
    _v = _vault("Inbox", "Sources/PDFs", "Wiki")
    _put(_v, "Inbox/download.pdf"); _put(_v, "Sources/PDFs/download.pdf")
    _put(_v, "Wiki/concept.md",
         '---\nsources:\n  - "[[Sources/PDFs/download.pdf#page=3]]"\n---\n')
    _keyed = keyed_files(_v, os.path.join(_v, "Inbox/download.pdf"))
    check("qualified link to another file of the same basename is not a reference",
          references(_v, set(_keyed.values()),
                     dirs=keyed_dirs(_v, _keyed)), {})
    # ...and a bare link to it still is.
    _put(_v, "Wiki/bare.md", "cites [[download.pdf]]\n")
    check("a bare link is still a reference",
          bool(references(_v, set(_keyed.values()),
                          dirs=keyed_dirs(_v, _keyed))), True)

    # A URL ending in the NEW basename must survive untouched.
    _v = _vault("Inbox", "Sources/PDFs", "Articles")
    _put(_v, "Inbox/download.pdf")
    _url = "see [PDF](https://example.org/papers/Smith_X_1776.pdf)\n"
    _put(_v, "Articles/c.md", _url)
    rename_all(_v, os.path.join(_v, "Inbox/download.pdf"), "Smith_X_1776.pdf",
               apply=True, dest=os.path.join(_v, "Sources/PDFs"))
    with open(os.path.join(_v, "Articles/c.md"), encoding="utf-8") as _fh:
        check("a URL ending in the new basename is left alone", _fh.read(), _url)

    # A symlinked source is refused, not moved as a link.
    _v = _vault("Store", "Sources/PDFs")
    _put(_v, "Store/real.pdf")
    _source_link = os.path.join(_v, "Sources/PDFs/real.pdf")
    _have_source_link = _try_symlink("../Store/real.pdf", _source_link)
    _m, _e, _b = ((None, None, []) if not _have_source_link else
                  rename_all(_v, _source_link, "Smith_X_1776.pdf"))
    check("a symlinked source is refused",
          (not _have_source_link
           or any("is a symlink to" in b for b in _b)), True)

    # Symlinked directories are an intentional recursive scope; leaf symlinks
    # are not permission to rewrite an arbitrary target outside the vault.
    _v = _vault("Inbox", "Wiki", "Outside", "Sources/PDFs")
    _put(_v, "Inbox/download.pdf")
    _put(_v, "Outside/n.md", "![[download.pdf]]\n")
    _leaf_link = os.path.join(_v, "Wiki/n.md")
    _have_leaf_link = _try_symlink("../Outside/n.md", _leaf_link)
    _m, _e, _b = ((None, None, []) if not _have_leaf_link else rename_all(
        _v, os.path.join(_v, "Inbox/download.pdf"), "Smith_X_1776.pdf",
        dest=os.path.join(_v, "Sources/PDFs"), apply=True))
    check("a leaf Markdown symlink blocks the complete rename",
          (not _have_leaf_link
           or any("symlink" in blocker for blocker in _b)), True)
    check("the blocked plan leaves the symlink and its external target unchanged",
          (not _have_leaf_link or
           (os.path.islink(_leaf_link)
            and open(os.path.join(_v, "Outside/n.md"),
                     encoding="utf-8").read() == "![[download.pdf]]\n"
            and os.path.exists(os.path.join(_v, "Inbox/download.pdf")))),
          True)
    if _have_leaf_link:
        try:
            _write(_leaf_link, "![[new.pdf]]\n")
        except StaleRenamePlan as _exc:
            _refused_leaf = "symlink" in str(_exc)
        else:
            _refused_leaf = False
    else:
        _refused_leaf = True
    check("the low-level note writer also refuses a leaf symlink",
          _refused_leaf, True)

    _v = _vault("Wiki", "Outside")
    _race_note = _put(_v, "Wiki/race.md", "ordinary prose\n")
    _race_target = _put(_v, "Outside/race-target.md", "![[download.pdf]]\n")
    _real_open = os.open
    _swapped = []

    _race_probe = os.path.join(_v, "Wiki", ".symlink-probe")
    _have_race_link = _try_symlink(_race_target, _race_probe)
    if _have_race_link:
        os.unlink(_race_probe)

    def _swap_reference_to_link(path, flags, *args, **kwargs):
        if os.path.abspath(path) == os.path.abspath(_race_note) and not _swapped:
            os.unlink(_race_note)
            os.symlink(_race_target, _race_note)
            _swapped.append(True)
        return _real_open(path, flags, *args, **kwargs)

    if _have_race_link:
        try:
            with patch.object(os, "open", side_effect=_swap_reference_to_link):
                references(_v, {"download.pdf"})
            _reference_race_refused = False
        except InventoryFailed:
            _reference_race_refused = True
    else:
        _reference_race_refused = True
    check("a Markdown leaf swapped to a symlink before open blocks the scan",
          _reference_race_refused, True)

    # An unreadable note that cites nothing must not dead-end the vault.
    _v = _vault("Inbox", "Sources/PDFs", "Wiki")
    _put(_v, "Inbox/download.pdf")
    _put(_v, "Wiki/legacy.md", "caf\xe9 cites nothing\n".encode("latin-1"))
    _m, _e, _b = rename_all(_v, os.path.join(_v, "Inbox/download.pdf"),
                            "Smith_X_1776.pdf", dest=os.path.join(_v, "Sources/PDFs"))
    check("an unreadable note citing nothing is not a blocker", _b, [])
    check("...and is reported rather than passed over silently",
          bool(_e.unreadable), True)
    _put(_v, "Wiki/cites.md", "caf\xe9 [[download.pdf]]\n".encode("latin-1"))
    _m, _e, _b = rename_all(_v, os.path.join(_v, "Inbox/download.pdf"),
                            "Smith_X_1776.pdf", dest=os.path.join(_v, "Sources/PDFs"))
    check("an unreadable note that DOES cite it is still a blocker",
          any("could not be read as UTF-8" in b for b in _b), True)

    # split_book validates against 1a, not just SAFE_NAME.
    _txt = ["Chapter 1 Intro text for the needle", "more"]
    for _name, _label, _ok in (
            ("Kuhn_S_2012_1_Intro.pdf", "unpadded chapter number", False),
            ("Kuhn_S_2012_01_Role_History.pdf", "underscore in chapter name", False),
            ("Prince_UDL_2026_01_Intro.pdf", "another book's stem", False),
            ("JustSomeName.pdf", "no chapter segment", False)):
        _ch = [{"heading_text": "Chapter 1 Intro", "filename": _name,
                "start_idx": 0, "end_idx": 1}]
        _plan, _probs, _ = _resolve(_ch, _txt, 2, "/tmp/x", {}, "Kuhn_S_2012")
        check("split_book refuses %s" % _label, (bool(_plan), not _probs),
              (_ok, _ok))

    # --- the review pass of 2026-08-11.  Eight reproduced defects, each one a
    # --- guard that answered a question differently from the guard beside it:
    # --- a probe and a rewrite disagreeing about what a link names, a pattern
    # --- and its twin disagreeing about what ends a wikilink, a fan-out and a
    # --- derivation disagreeing about what a filename is, a diagnostic and the
    # --- function it diagnoses disagreeing about where the plugin is.

    # 1. `references()` says a qualified link names a DIFFERENT document; the
    #    rewrite must reach the same verdict.  It did not: it repointed the
    #    note at the renamed file and `debase_links` then dropped the folder
    #    that was the only evidence of what the link used to mean.  Both the
    #    pre-check and the documented post-rename re-probe pass on the wreck.
    _v = _vault("Inbox", "Sources/PDFs", "Wiki")
    _put(_v, "Inbox/download.pdf"); _put(_v, "Sources/PDFs/download.pdf")
    _body = '---\nsources:\n  - "[[Sources/PDFs/download.pdf#page=3]]"\n---\n'
    _put(_v, "Wiki/concept.md", _body)
    rename_all(_v, os.path.join(_v, "Inbox/download.pdf"), "Smith_X_1776.pdf",
               apply=True, dest=os.path.join(_v, "Sources/PDFs"))
    with open(os.path.join(_v, "Wiki/concept.md"), encoding="utf-8") as _fh:
        check("a qualified link to another file of that basename survives "
              "the rename it does not name", _fh.read(), _body)
    for _label, _text, _want in (
            ("another folder's file is left alone",
             "see [[Sources/PDFs/download.pdf#page=3]]",
             "see [[Sources/PDFs/download.pdf#page=3]]"),
            ("the markdown-link syntax too",
             "see [PDF](Sources/PDFs/download.pdf)",
             "see [PDF](Sources/PDFs/download.pdf)"),
            ("the keyed file's own folder is still rewritten",
             "see [[Inbox/download.pdf]]", "see [[Inbox/Smith_X_1776.pdf]]"),
            ("and a bare basename always is",
             "see [[download.pdf]]", "see [[Smith_X_1776.pdf]]")):
        check("rewrite_text checks the basename branch's qualification: %s"
              % _label,
              rewrite_text(_text, {"download.pdf": "Smith_X_1776.pdf"}, {},
                           {"download.pdf": {"inbox"}}, "Wiki"), _want)

    # 2. Obsidian escapes the display pipe inside a markdown table, and pads
    #    links people hand-edit.  `_debase_res` allowed for the backslash and
    #    the stem branch did not, so a note cited only from a table was
    #    reported unreferenced, renamed, and left dangling at both ends --
    #    with the post-rename re-probe blind to it by the same omission.
    for _link, _want in ((r"[[UDL_2026\|note]]", True),
                         (r"[[Articles/UDL_2026\|note]]", True),
                         (r"![[Articles/UDL_2026\|note]]", True),
                         ("[[ UDL_2026 ]]", True),
                         ("[[ Articles/UDL_2026 ]]", True),
                         ("[[ Other/NotThisOne ]]", False)):
        check("references() sees %s" % _link,
              bool(_reference_re({"UDL_2026.md"})[0].search(_link)), _want)
    check("an escaped display pipe is rewritten, not stepped over",
          rewrite_text(r"| paper | [[UDL_2026\|the note]] |",
                       {"UDL_2026.md": "Prince_UDL_2026.md"},
                       {"UDL_2026": "Prince_UDL_2026"}),
          r"| paper | [[Prince_UDL_2026\|the note]] |")
    check("a padded wikilink keeps its padding and gains the new stem",
          rewrite_text("[[ UDL_2026 ]]",
                       {"UDL_2026.md": "Prince_UDL_2026.md"},
                       {"UDL_2026": "Prince_UDL_2026"}),
          "[[ Prince_UDL_2026 ]]")
    # `debase_links` has to see everything the rewrite sees, or a padded link
    # keeps the folder the document just moved out of.  The leading pad leaves
    # with the folder — it is inside the qualification group — and the
    # trailing one stays; both forms are links Obsidian resolves by basename,
    # which is the whole point of dropping the folder.
    check("a padded qualified link is debased with the unpadded ones",
          debase_links("[[ Sources/PDFs/Smith_X_1776.pdf ]] and "
                       "[[Sources/PDFs/Smith_X_1776.pdf]]",
                       {"Smith_X_1776.pdf"}),
          "[[Smith_X_1776.pdf ]] and [[Smith_X_1776.pdf]]")
    _v = _vault("Articles", "Wiki")
    _put(_v, "Articles/UDL_2026.md", '---\nsource: "[[UDL_2026.pdf]]"\n---\n')
    _put(_v, "Wiki/table.md",
         "| paper | note |\n|---|---|\n| x | [[Articles/UDL_2026\\|summary]] |\n")
    _put(_v, "Wiki/padded.md", "see [[ Articles/UDL_2026 ]]\n")
    check("a link in a table, and a padded one, are references",
          sorted(os.path.basename(_p) for _p in
                 references(_v, {"UDL_2026.md"},
                            dirs={"UDL_2026.md": {"articles"}})),
          ["padded.md", "table.md"])

    # 3. The unreadable list rode in `edits` under a key that is not a path,
    #    so `rename_all` walked `edits.items()` into `open("__unreadable__")`:
    #    one stray latin-1 note citing nothing dead-ended EVERY rename in the
    #    vault, rolled back, and reported a failure naming a file that does
    #    not exist.  `_report_plan` printed it as a note about to be rewritten.
    _v = _vault("Inbox", "Sources/PDFs", "Wiki")
    _put(_v, "Inbox/download.pdf")
    _put(_v, "Wiki/legacy.md", "caf\xe9 cites nothing\n".encode("latin-1"))
    _m, _e, _b = plan_rename(_v, os.path.join(_v, "Inbox/download.pdf"),
                             "Smith_X_1776.pdf",
                             dest=os.path.join(_v, "Sources/PDFs"))
    check("every key in `edits` is a note that exists, so the plan report and "
          "the write loop can both take one at its word",
          [_md for _md in _e if not os.path.isfile(_md)], [])
    check("...and the unreadable note is still named, beside the edits",
          [os.path.basename(_u.split(" (")[0]) for _u in _e.unreadable],
          ["legacy.md"])
    try:
        rename_all(_v, os.path.join(_v, "Inbox/download.pdf"),
                   "Smith_X_1776.pdf", apply=True,
                   dest=os.path.join(_v, "Sources/PDFs"))
        _got = os.path.isfile(os.path.join(_v, "Sources/PDFs/Smith_X_1776.pdf"))
    except BaseException as _exc:                 # the traceback IS the bug
        _got = "%s: %s" % (type(_exc).__name__, str(_exc)[:70])
    check("one unreadable note does not dead-end the rename it never mentions",
          _got, True)

    # 4. A source stored NFC beside figures stored NFD. The fan-out
    #    compared raw `str.lower()`, so it found the document alone: the
    #    rename moved it, orphaned three figures under a stem nothing looks
    #    for, and `references()` -- asked only about the name it did find --
    #    came back empty and told the caller to go ahead.
    _nfc = unicodedata.normalize("NFC", "M\xfcller_Uber_2001")
    _nfd = unicodedata.normalize("NFD", "M\xfcller_Uber_2001")
    _v = _vault("Inbox", "Sources/PDFs", "Sources/Images", "Articles")
    _put(_v, "Inbox/%s.pdf" % _nfc)
    _nfd_images = []
    for _i in (1, 2, 3):
        _nfd_images.append(_put(
            _v, "Sources/Images/%s_fig_%d.png" % (_nfd, _i)))
    _put(_v, "Sources/Images/" + MANIFEST_FILE,
         "".join("%s\t%s\n" % (os.path.basename(_p), file_digest(_p))
                 for _p in _nfd_images))
    # The note's filename AND its `source:` link are both NFD, which is what a
    # tool that read the name back from `os.listdir` on macOS writes: the
    # `source:` test is the gate on the note half of the fan-out, so it has to
    # reconcile the two forms as well.
    _put(_v, "Articles/%s.md" % _nfd,
         '---\nsource: "[[%s.pdf]]"\n---\n' % _nfd)
    _keyed = keyed_files(_v, os.path.join(_v, "Inbox/%s.pdf" % _nfc))
    check("a source stored NFC keys the figures and note stored NFD",
          len(_keyed), 5)
    rename_all(_v, os.path.join(_v, "Inbox/%s.pdf" % _nfc),
               "Muller_Uber_2001.pdf", apply=True,
               dest=os.path.join(_v, "Sources/PDFs"))
    check("...and they are renamed with it rather than left orphaned",
          sorted(_listdir(os.path.join(_v, "Sources/Images"))),
          [MANIFEST_FILE] +
          ["Muller_Uber_2001_fig_%d.png" % _i for _i in (1, 2, 3)])
    check("...the note among them",
          sorted(_listdir(os.path.join(_v, "Articles"))),
          ["Muller_Uber_2001.md"])
    _note_now = os.path.join(_v, "Articles/Muller_Uber_2001.md")
    _got = "(the note was left behind under its old stem)"
    if os.path.isfile(_note_now):                 # absent IS the failure
        with open(_note_now, encoding="utf-8") as _fh:
            _got = _fh.read()
    check("...and its own NFD `source:` link points at the new name",
          _got, '---\nsource: "[[Muller_Uber_2001.pdf]]"\n---\n')
    # The control on the other side: `_nfc_low` lowercases and does NOT
    # casefold, so `ß` stays itself.  Folding it to `ss` here would key an
    # unrelated `Strasse_2001_fig_1.png` to this document and rename a file
    # that is nobody's -- which is why `_ifold` is a separate helper used only
    # where `re.I` has already declared two spellings equal.
    _v = _vault("Inbox", "Sources/Images")
    _put(_v, "Inbox/Stra\xdfe_2001.pdf")
    _put(_v, "Sources/Images/Strasse_2001_fig_1.png")
    check("case folding does not key an unrelated figure to a source",
          len(keyed_files(_v, os.path.join(_v, "Inbox/Stra\xdfe_2001.pdf"))), 1)

    # 5. `re.I`'s equivalence classes are wider than `str.lower()`'s, so the
    #    pattern matched a spelling the lookup had no key for and the guard
    #    that authorises every rename died with a bare `KeyError` -- on
    #    `--apply`, after the writes.  MICRO SIGN vs GREEK SMALL LETTER MU.
    _v = _vault("Inbox", "Wiki")
    _put(_v, "Inbox/\xb5_2001.pdf")
    _put(_v, "Wiki/n.md", "cites [[μ_2001.pdf]]\n")
    try:
        _got = sorted(os.path.basename(_p)
                      for _p in references(_v, {"\xb5_2001.pdf"}))
    except BaseException as _exc:                 # the traceback IS the bug
        _got = "%s: %s" % (type(_exc).__name__, _exc)
    check("a case-fold-equivalent spelling is answered, not raised on",
          _got, ["n.md"])
    check("...and the rewrite reaches it too, rather than degrading to silence",
          rewrite_text("[[μ_2001.pdf]]", {"\xb5_2001.pdf": "Mu_2001.pdf"}, {}),
          "[[Mu_2001.pdf]]")

    # 7. The extension-mismatch blocker sat BELOW the two PDFs-only guards,
    #    which left it reachable only when both extensions were in
    #    {"", ".pdf"} -- where they never differ.  SKILL.md promises its
    #    message twice and `--to`'s help text a third time.
    _v = _vault("Inbox")
    _put(_v, "Inbox/paper.pdf"); _put(_v, "Inbox/notes.txt")
    _put(_v, "Inbox/download")
    _, _, _xb = plan_rename(_v, os.path.join(_v, "Inbox/paper.pdf"),
                            "Smith_X_1776.epub")
    check("renaming a .pdf to .epub is refused as an extension mismatch",
          any("changes the extension" in _bl for _bl in _xb), True)
    check("...and the message names the basename to pass instead, as "
          "SKILL.md says it does",
          any("Pass 'Smith_X_1776.pdf'" in _bl for _bl in _xb), True)
    _, _, _tb = plan_rename(_v, os.path.join(_v, "Inbox/notes.txt"),
                            "Smith_X_1776.pdf")
    check("a non-PDF source is refused as a non-PDF, not sent back with a "
          ".txt name to pass",
          (any("organises PDFs" in _bl for _bl in _tb),
           any("Pass 'Smith_X_1776.txt'" in _bl for _bl in _tb)), (True, False))
    _, _, _nb = plan_rename(_v, os.path.join(_v, "Inbox/download"),
                            "Smith_X_1776.epub")
    check("an extensionless source has nothing to contradict, so it is held "
          "to the .pdf output rule instead",
          any("ends in .pdf" in _bl for _bl in _nb), True)

    # 8. `references/book-splitting.md` promises the +/-2 start correction is
    #    "corrected and reported rather than shipped", and the workflow's step
    #    6 tells the reader to repeat the `note:` lines.  `notes` was appended
    #    to for the end trim alone, so `notes = split_book(...)` came back []
    #    and the run reported a clean split of a book whose starts had all
    #    been moved under it.
    _ch = [{"heading_text": "Chapter 1 Intro", "filename":
            "Kuhn_S_2012_01_Intro.pdf", "start_idx": 0, "end_idx": 3}]
    _txt = [_norm(_p) for _p in ("front matter, no heading here",
                                 "Chapter 1 Intro " + "body " * 60, "more body")]
    _plan, _probs, _notes = _resolve(_ch, _txt, 3, "/tmp/x", {}, "Kuhn_S_2012")
    check("a start the +/-2 search moves is reported, with both page numbers",
          (bool(_plan), _probs, _notes),
          (True, [], ["Kuhn_S_2012_01_Intro.pdf: start corrected from page 1 "
                      "to 2 — the heading is not on the page the mapping gave"]))
    _ch = [{"heading_text": "Chapter 1 Intro", "filename":
            "Kuhn_S_2012_01_Intro.pdf", "start_idx": 1, "end_idx": 3}]
    _txt = [_norm(_p) for _p in ("Chapter 1 Intro",
                                 "Chapter 1 Intro " + "body " * 60, "more body")]
    _plan, _probs, _notes = _resolve(_ch, _txt, 3, "/tmp/x", {}, "Kuhn_S_2012")
    check("a title page pulled in ahead of the start is reported too",
          (_plan[0][0], _notes),
          (0, ["Kuhn_S_2012_01_Intro.pdf: start moved from page 2 to 1 to "
               "take in the chapter title page before it"]))
    _ch = [{"heading_text": "Chapter 1 Intro", "filename":
            "Kuhn_S_2012_01_Intro.pdf", "start_idx": 0, "end_idx": 2}]
    _txt = [_norm(_p) for _p in ("Chapter 1 Intro " + "body " * 60, "more body")]
    _plan, _probs, _notes = _resolve(_ch, _txt, 2, "/tmp/x", {}, "Kuhn_S_2012")
    check("a start that needed no correction reports nothing", _notes, [])

    # The extracted PNG follows a rename, so its ownership and review records
    # must follow too. Otherwise the next batch refuses this plugin's own file.
    from figure_state import parse_manifest, parse_reviewed
    with _tf.TemporaryDirectory(prefix="org-sidecar-test-") as _v:
        _pdf = _put(_v, "Sources/PDFs/Doe_Old_2025.pdf")
        _img = _put(_v, "Sources/Images/Doe_Old_2025_fig_1.png", b"figure bytes")
        _owned_digest = file_digest(_img)
        _manifest_body = ("# keep metadata comments\nDoe_Old_2025_fig_1.png\t" + _owned_digest
                          + "\nOther_fig_2.png\t" + "b" * 64 + "\n")
        _review_body = "# checked manually\nDoe_Old_2025\t1\tkeep my note\nOther:2\n"
        _manifest = _put(_v, "Sources/Images/" + MANIFEST_FILE, _manifest_body)
        _review = _put(_v, "Sources/Images/" + REVIEW_FILE, _review_body)
        _stage_parents = []
        _real_mkdtemp = tempfile.mkdtemp

        def _tracked_mkdtemp(*args, **kwargs):
            _stage_parents.append(kwargs.get("dir"))
            return _real_mkdtemp(*args, **kwargs)

        with patch.object(tempfile, "mkdtemp", side_effect=_tracked_mkdtemp):
            _write(_manifest, _manifest_body)
        check("figure sidecar staging stays outside Sources/Images",
              (bool(_stage_parents), set(map(os.path.realpath, _stage_parents))),
              (True, {os.path.realpath(os.path.join(_v, "Sources"))}))
        check("figure sidecar staging is cleaned after publication",
              [n for n in os.listdir(os.path.join(_v, "Sources"))
               if n.startswith(".organize-stage-")], [])
        _moves, _edits, _blockers = plan_rename(_v, _pdf, "Doe_New_2025.pdf")
        check("sidecar changes appear separately in a rename plan",
              (len(_edits), len(_edits.sidecars), _blockers), (0, 2, []))
        with open(_manifest, encoding="utf-8") as _fh:
            check("a sidecar dry run writes nothing", _fh.read(), _manifest_body)
        # Force a move failure after the state updates to exercise rollback.
        def _fail_move(_src, _dst, expected=None):
            raise OSError("injected move failure")

        with patch.dict(globals(), move_noreplace=_fail_move):
            try:
                rename_all(_v, _pdf, "Doe_New_2025.pdf", apply=True)
                _rolled_back = False
            except RenameFailed as _exc:
                _rolled_back = _exc.rolled_back
        check("a failed rename rolls sidecars back too", _rolled_back, True)
        with open(_manifest, encoding="utf-8") as _fh:
            check("manifest restored after failed move", _fh.read(), _manifest_body)
        with open(_review, encoding="utf-8") as _fh:
            check("review ledger restored after failed move", _fh.read(), _review_body)
        rename_all(_v, _pdf, "Doe_New_2025.pdf", apply=True)
        with open(_manifest, encoding="utf-8") as _fh:
            check("successful rename carries ownership and unrelated records",
                  parse_manifest(_fh.read()),
                  {"Doe_New_2025_fig_1.png": _owned_digest,
                   "Other_fig_2.png": "b" * 64})
        with open(_review, encoding="utf-8") as _fh:
            _body = _fh.read()
            check("successful rename carries reviewed figure labels",
                  parse_reviewed(_body), {("Doe_New_2025", "1"), ("Other", "2")})
            check("sidecar rename preserves comments and annotation columns",
                  _body, _review_body.replace("Doe_Old_2025", "Doe_New_2025"))
        _put(_v, "Sources/Images/" + MANIFEST_FILE, "malformed ownership\n")
        _new_pdf = os.path.join(_v, "Sources/PDFs/Doe_New_2025.pdf")
        _moves, _edits, _blockers = rename_all(_v, _new_pdf, "Doe_Next_2025.pdf", apply=True)
        check("malformed ownership blocks a rename before mutation",
              (bool(_blockers), os.path.exists(_new_pdf)), (True, True))

    import contextlib
    import io

    def _run_cli(argv):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main(argv)
        return code, stdout.getvalue(), stderr.getvalue()

    # Supplying a bad --vault is never the same as deliberately omitting it.
    # The old CLI silently selected external mode and --apply renamed the file
    # with no uniqueness or reference scan.
    with _tf.TemporaryDirectory(prefix="org-invalid-vault-test-") as _v:
        _pdf = _put(_v, "download.pdf", b"%PDF-1.4\n")
        _missing_vault = os.path.join(_v, "missing-vault")
        _code, _stdout, _stderr = _run_cli([
            "rename", _pdf, "--vault", _missing_vault,
            "--to", "Doe_Study_2025.pdf", "--apply"])
        check("an explicit invalid --vault blocks rather than selecting external mode",
              (_code, os.path.exists(_pdf),
               os.path.exists(os.path.join(_v, "Doe_Study_2025.pdf")),
               "--vault is not a directory" in _stderr),
              (1, True, False, True))
        _code, _stdout, _stderr = _run_cli([
            "check", _pdf, "--vault", _missing_vault])
        check("the reference-check CLI rejects the same invalid vault",
              (_code, "--vault is not a directory" in _stderr), (1, True))
        _chapters = _put(_v, "chapters.json", "[]\n")
        _out = os.path.join(_v, "chapters")
        _code, _stdout, _stderr = _run_cli([
            "split", _pdf, "--chapters", _chapters, "--out", _out,
            "--vault", _missing_vault])
        check("the split CLI rejects the same invalid vault before writing",
              (_code, os.path.lexists(_out),
               "--vault is not a directory" in _stderr), (1, False, True))

    # A directory or missing path whose spelling ends in .pdf is not a source
    # file. It used to produce a plausible dry-run plan (and a .pdf directory
    # could then be moved into Sources/PDFs/).
    with _tf.TemporaryDirectory(prefix="org-source-kind-test-") as _v:
        _directory = os.path.join(_v, "folder.pdf")
        os.mkdir(_directory)
        _moves, _edits, _blockers = plan_rename(
            None, _directory, "Doe_Study_2025.pdf")
        check("a .pdf directory is refused as a rename source",
              (bool(_moves), any("not a regular file" in b for b in _blockers)),
              (False, True))
        _moves, _edits, _blockers = plan_rename(
            None, os.path.join(_v, "missing.pdf"), "Doe_Study_2025.pdf")
        check("a missing rename source is refused during planning",
              (bool(_moves), any("does not exist" in b for b in _blockers)),
              (False, True))
        _code, _stdout, _stderr = _run_cli([
            "check", os.path.join(_v, "missing.pdf")])
        check("an external reference check rejects a missing source",
              (_code, "does not exist" in _stderr), (1, True))

    # Destination checks are diagnostic only. The write must still refuse a
    # name claimed after the plan and preserve both files byte-for-byte.
    with _tf.TemporaryDirectory(prefix="org-late-rename-target-") as _v:
        _src = _put(_v, "download.pdf", b"source bytes")
        _dst = os.path.join(_v, "Doe_Study_2025.pdf")
        _real_move = move_noreplace

        def _occupy_move_target(src, dst, expected=None, **kwargs):
            if dst == _dst and not os.path.lexists(dst):
                with open(dst, "wb") as _fh:
                    _fh.write(b"late destination")
            return _real_move(src, dst, expected=expected, **kwargs)

        with patch.dict(globals(), move_noreplace=_occupy_move_target):
            try:
                rename_all(None, _src, "Doe_Study_2025.pdf", apply=True)
                _late_failure = None
            except RenameFailed as _exc:
                _late_failure = _exc
        check("a rename destination created after preflight is never replaced",
              (open(_src, "rb").read(), open(_dst, "rb").read(),
               bool(_late_failure and _late_failure.rolled_back)),
              (b"source bytes", b"late destination", True))

    with _tf.TemporaryDirectory(prefix="org-case-only-move-") as _v:
        _src = _put(_v, "doe_study_2025.pdf", b"case-only bytes")
        _dst = os.path.join(_v, "Doe_Study_2025.pdf")
        rename_all(None, _src, "Doe_Study_2025.pdf", apply=True)
        check("an applied case-only move preserves the source on this filesystem",
              (os.listdir(_v), open(_dst, "rb").read()),
              (["Doe_Study_2025.pdf"], b"case-only bytes"))

    with _tf.TemporaryDirectory(prefix="org-snapshot-open-race-") as _v:
        _src = _put(_v, "source.pdf", b"inspected bytes")
        _replacement = _put(_v, "replacement.pdf", b"late bytes")
        _real_open = os.open
        _swapped = [False]

        def _swap_before_descriptor(path, flags, *args, **kwargs):
            if path == _src and not _swapped[0]:
                _swapped[0] = True
                os.replace(_replacement, _src)
            return _real_open(path, flags, *args, **kwargs)

        with patch.object(os, "open", side_effect=_swap_before_descriptor):
            try:
                _stable_file_snapshot(_src)
                _snapshot_failure = None
            except StaleRenamePlan as _exc:
                _snapshot_failure = _exc
        check("a move snapshot binds its digest to the inspected pathname owner",
              bool(_snapshot_failure), True)
        check("...and leaves the late occupant untouched",
              open(_src, "rb").read(), b"late bytes")

    with _tf.TemporaryDirectory(prefix="org-windows-stat-view-") as _v:
        _src = _put(_v, "Sources/PDFs/Doe_Study_2025.pdf", b"source bytes")
        _note = _put(
            _v, "Articles/Doe_Study_2025.md", b"[[Doe_Study_2025.pdf]]\n")
        _real_fstat = os.fstat

        class _ProjectedHandleStat:
            """Model Windows' stable but distinct handle metadata view."""

            def __init__(self, item):
                self.item = item

            def __getattr__(self, name):
                if name == "st_ctime_ns":
                    return getattr(self.item, name) + 100
                if name == "st_mode":
                    return stat.S_IFMT(self.item.st_mode) | 0o444
                return getattr(self.item, name)

        def _projected_fstat(descriptor):
            return _ProjectedHandleStat(_real_fstat(descriptor))

        with patch.object(os, "fstat", side_effect=_projected_fstat):
            _move_view = _stable_file_snapshot(_src)
            _body_view = _read_snapshot(_note)[0]
            _reference_view = references(_v, {os.path.basename(_src)})
        check("stable Windows handle metadata does not look like a move race",
              _move_view[1], hashlib.sha256(b"source bytes").hexdigest())
        check("stable Windows handle metadata does not block a guarded text read",
              _body_view, "[[Doe_Study_2025.pdf]]\n")
        check("stable Windows handle metadata does not erase reference results",
              sorted(os.path.basename(path) for path in _reference_view),
              ["Doe_Study_2025.md"])

    with _tf.TemporaryDirectory(prefix="org-late-source-identity-") as _v:
        _src = _put(_v, "download.pdf", b"planned source")
        _dst = os.path.join(_v, "Doe_Study_2025.pdf")
        _real_move = move_noreplace

        def _replace_planned_source(src, dst, expected=None, **kwargs):
            os.unlink(src)
            with open(src, "wb") as _fh:
                _fh.write(b"late source")
            return _real_move(src, dst, expected=expected, **kwargs)

        with patch.dict(globals(), move_noreplace=_replace_planned_source):
            try:
                rename_all(None, _src, "Doe_Study_2025.pdf", apply=True)
                _identity_failure = None
            except RenameFailed as _exc:
                _identity_failure = _exc
        check("a source replaced after planning is retained rather than renamed",
              (open(_src, "rb").read(), os.path.lexists(_dst),
               bool(_identity_failure and _identity_failure.rolled_back)),
              (b"late source", False, True))

    # Rewriting a regular file in place preserves its inode, so the exclusive
    # move helper's identity guard alone cannot see it. A manifest-owned figure
    # changed after planning must not be moved while the manifest is rewritten
    # with the digest of the older bytes.
    with _tf.TemporaryDirectory(prefix="org-late-source-bytes-") as _v:
        _pdf = _put(_v, "Sources/PDFs/Doe_Old_2025.pdf", b"pdf bytes")
        _image = _put(_v, "Sources/Images/Doe_Old_2025_fig_1.png",
                      b"planned image")
        _old_digest = file_digest(_image)
        _manifest = _put(
            _v, "Sources/Images/" + MANIFEST_FILE,
            "Doe_Old_2025_fig_1.png\t" + _old_digest + "\n")
        _new_image = os.path.join(
            _v, "Sources/Images/Doe_New_2025_fig_1.png")
        _real_move = move_noreplace

        def _mutate_planned_bytes(src, dst, expected=None, **kwargs):
            if (os.path.normcase(os.path.abspath(src))
                    == os.path.normcase(os.path.abspath(_image))):
                with open(src, "ab") as _fh:
                    _fh.write(b" changed in place")
            return _real_move(src, dst, expected=expected, **kwargs)

        with patch.dict(globals(), move_noreplace=_mutate_planned_bytes):
            try:
                rename_all(_v, _pdf, "Doe_New_2025.pdf", apply=True)
                _byte_failure = None
            except RenameFailed as _exc:
                _byte_failure = _exc
        with open(_manifest, encoding="utf-8") as _fh:
            _manifest_after = _fh.read()
        check("an in-place figure edit after planning aborts and restores old names",
              (open(_image, "rb").read(), os.path.lexists(_new_image),
               _manifest_after,
               bool(_byte_failure and _byte_failure.rolled_back)),
              (b"planned image changed in place", False,
               "Doe_Old_2025_fig_1.png\t" + _old_digest + "\n", True))

    # A rollback source can be reclaimed after its file moved. The reverse
    # move is exclusive too, so the late file stays at the old name and the
    # transaction reports the original at its new name for manual recovery.
    with _tf.TemporaryDirectory(prefix="org-late-rollback-source-") as _v:
        _pdf = _put(_v, "Sources/PDFs/Doe_Old_2025.pdf", b"pdf bytes")
        _image = _put(_v, "Sources/Images/Doe_Old_2025_fig_1.png",
                      b"image bytes")
        _put(_v, "Sources/Images/" + MANIFEST_FILE,
             "Doe_Old_2025_fig_1.png\t" + file_digest(_image) + "\n")
        _moves, _edits, _blockers = plan_rename(
            _v, _pdf, "Doe_New_2025.pdf")
        _first_src, _first_dst = _moves[0]
        _first_bytes = open(_first_src, "rb").read()
        _real_move, _calls = move_noreplace, []

        def _reclaim_before_rollback(src, dst, expected=None, **kwargs):
            _calls.append((src, dst))
            if len(_calls) == 2:
                with open(_first_src, "wb") as _fh:
                    _fh.write(b"late rollback source")
                raise OSError(28, "injected later move failure")
            return _real_move(src, dst, expected=expected, **kwargs)

        with patch.dict(globals(), move_noreplace=_reclaim_before_rollback):
            try:
                rename_all(_v, _pdf, "Doe_New_2025.pdf", apply=True)
                _rollback_failure = None
            except RenameFailed as _exc:
                _rollback_failure = _exc
        check("rollback never overwrites a source reclaimed after preflight",
              (open(_first_src, "rb").read(), open(_first_dst, "rb").read(),
               bool(_rollback_failure and not _rollback_failure.rolled_back)),
              (b"late rollback source", _first_bytes, True))

    # Directories cannot use the hard-link fallback. On supported hosts the
    # native exclusive rename must preserve even a late *empty* directory,
    # which ordinary POSIX rename would silently remove.
    with _tf.TemporaryDirectory(prefix="org-late-directory-target-") as _v:
        _book = _put(_v, "Sources/PDFs/Doe_Book_2025.pdf", b"book")
        _chapter = _put(
            _v, "Sources/PDFs/Doe_Book_2025/Doe_Book_2025_01_Intro.pdf",
            b"chapter")
        _old_folder = os.path.dirname(_chapter)
        _new_folder = os.path.join(_v, "Sources/PDFs/Doe_NewBook_2025")
        _new_chapter = os.path.join(_new_folder,
                                    "Doe_NewBook_2025_01_Intro.pdf")
        _real_move = move_noreplace
        _occupied_directory_mode = []

        def _occupy_directory_target(src, dst, expected=None, **kwargs):
            if (os.path.normcase(os.path.abspath(src))
                    == os.path.normcase(os.path.abspath(_old_folder))
                    and not os.path.lexists(dst)):
                os.mkdir(dst, 0o700)
                os.chmod(dst, 0o700)
                _occupied_directory_mode.append(
                    stat.S_IMODE(os.stat(dst).st_mode))
            return _real_move(src, dst, expected=expected, **kwargs)

        with patch.dict(globals(), move_noreplace=_occupy_directory_target):
            try:
                rename_all(_v, _book, "Doe_NewBook_2025.pdf", apply=True)
                _directory_failure = None
            except RenameFailed as _exc:
                _directory_failure = _exc
        _late_directory_mode = (_occupied_directory_mode[0]
                                if _occupied_directory_mode else None)
        check("a late empty directory is preserved by exclusive rename",
              (os.path.isdir(_old_folder), open(_chapter, "rb").read(),
               os.path.isdir(_new_folder),
               stat.S_IMODE(os.stat(_new_folder).st_mode),
               os.path.lexists(_new_chapter), bool(_directory_failure)),
              (True, b"chapter", True, _late_directory_mode,
               False, True))

    # The hard-link fallback can publish the destination and then fail to
    # unlink the source. That is explicit residue, never a successful rollback.
    with _tf.TemporaryDirectory(prefix="org-incomplete-move-") as _v:
        _src = _put(_v, "download.pdf", b"linked source")
        _dst = os.path.join(_v, "Doe_Study_2025.pdf")

        def _incomplete_move(src, dst, expected=None, **_kwargs):
            os.link(src, dst)
            raise MoveIncomplete(src, dst, OSError("injected unlink failure"))

        with patch.dict(globals(), move_noreplace=_incomplete_move):
            try:
                rename_all(None, _src, "Doe_Study_2025.pdf", apply=True)
                _incomplete_failure = None
            except RenameFailed as _exc:
                _incomplete_failure = _exc
        check("a partially landed move is retained and reported incomplete",
              (open(_src, "rb").read(), open(_dst, "rb").read(),
               bool(_incomplete_failure and not _incomplete_failure.rolled_back),
               "current move residue" in str(_incomplete_failure)),
              (b"linked source", b"linked source", True, True))

    # A note save after its rewrite was planned is newer user content. Refuse
    # it before displacement and leave the whole source family unmoved.
    with _tf.TemporaryDirectory(prefix="org-stale-note-") as _v:
        _pdf = _put(_v, "Sources/PDFs/Doe_Old_2025.pdf", b"pdf bytes")
        _note = _put(_v, "Wiki/topic.md", "[[Doe_Old_2025.pdf]]\n")
        _real_write = _write

        def _edit_before_write(path, text, expected=None):
            if (os.path.normcase(os.path.abspath(path))
                    == os.path.normcase(os.path.abspath(_note))):
                with open(path, "a", encoding="utf-8") as _fh:
                    _fh.write("editor addition\n")
            return _real_write(path, text, expected=expected)

        with patch.dict(globals(), _write=_edit_before_write):
            try:
                rename_all(_v, _pdf, "Doe_New_2025.pdf", apply=True)
                _stale_note_failure = None
            except RenameFailed as _exc:
                _stale_note_failure = _exc
        check("a note edited after planning is preserved and blocks apply",
              (open(_note, encoding="utf-8").read(), os.path.exists(_pdf),
               bool(_stale_note_failure and _stale_note_failure.rolled_back)),
              ("[[Doe_Old_2025.pdf]]\neditor addition\n", True, True))

    # Identity is guarded as well as text: an editor's atomic save can replace
    # a sidecar inode with byte-identical content before the apply reaches it.
    with _tf.TemporaryDirectory(prefix="org-stale-sidecar-") as _v:
        _pdf = _put(_v, "Sources/PDFs/Doe_Old_2025.pdf", b"pdf bytes")
        _image = _put(_v, "Sources/Images/Doe_Old_2025_fig_1.png", b"image")
        _manifest_body = ("Doe_Old_2025_fig_1.png\t" +
                          file_digest(_image) + "\n")
        _manifest = _put(_v, "Sources/Images/" + MANIFEST_FILE,
                         _manifest_body)
        _real_write = _write

        def _replace_sidecar_before_write(path, text, expected=None):
            if (os.path.normcase(os.path.abspath(path))
                    == os.path.normcase(os.path.abspath(_manifest))):
                _replacement = _put(_v, "replacement-sidecar", _manifest_body)
                os.replace(_replacement, path)
            return _real_write(path, text, expected=expected)

        with patch.dict(globals(), _write=_replace_sidecar_before_write):
            try:
                rename_all(_v, _pdf, "Doe_New_2025.pdf", apply=True)
                _stale_sidecar_failure = None
            except RenameFailed as _exc:
                _stale_sidecar_failure = _exc
        check("a byte-identical sidecar replacement is still a stale plan",
              (open(_manifest, encoding="utf-8").read(), os.path.exists(_pdf),
               bool(_stale_sidecar_failure
                    and _stale_sidecar_failure.rolled_back)),
              (_manifest_body, True, True))

    # Inject a writer in the exact old compare/os.replace gap: after the
    # planned note was displaced but before the staged rewrite is published.
    # Exclusive publication preserves the writer and saves the predecessor at
    # a named recovery path rather than clobbering either one.
    with _tf.TemporaryDirectory(prefix="org-note-cas-gap-") as _v:
        _pdf = _put(_v, "Sources/PDFs/Doe_Old_2025.pdf", b"pdf bytes")
        _old_note = "[[Doe_Old_2025.pdf]]\n"
        _note = _put(_v, "Wiki/topic.md", _old_note)
        _real_link_new = _atomic_move.link_noreplace
        _injected = {"done": False}

        def _occupy_before_text_publication(source, target):
            if (os.path.normcase(os.path.abspath(target))
                    == os.path.normcase(os.path.abspath(_note))
                    and not _injected["done"]):
                _injected["done"] = True
                with open(target, "w", encoding="utf-8") as _fh:
                    _fh.write("late editor save\n")
            return _real_link_new(source, target)

        with patch.object(
                _atomic_move, "link_noreplace",
                side_effect=_occupy_before_text_publication):
            try:
                rename_all(_v, _pdf, "Doe_New_2025.pdf", apply=True)
                _cas_failure = None
            except RenameFailed as _exc:
                _cas_failure = _exc
        _recoveries = [os.path.join(_v, "Wiki", name)
                       for name in os.listdir(os.path.join(_v, "Wiki"))
                       if name.startswith(".organize-recovery-")]
        _recovered = (open(os.path.join(_recoveries[0], "topic.md"),
                           encoding="utf-8").read() if _recoveries else None)
        check("the final text-publication CAS gap preserves both writers",
              (open(_note, encoding="utf-8").read(), _recovered,
               bool(_cas_failure and not _cas_failure.rolled_back),
               bool(_recoveries and
                    _reports_path(_cas_failure, _recoveries[0]))),
              ("late editor save\n", _old_note, True, True))

    # A link reaching the public name is still provisional until readback.
    # Inject an in-place editor save immediately after that link: conditional
    # rollback must retain the edit and recover the planned predecessor.
    with _tf.TemporaryDirectory(prefix="org-note-readback-gap-") as _v:
        _pdf = _put(_v, "Sources/PDFs/Doe_Old_2025.pdf", b"pdf bytes")
        _old_note = "[[Doe_Old_2025.pdf]]\n"
        _note = _put(_v, "Wiki/topic.md", _old_note)
        _real_link_new = _atomic_move.link_noreplace
        _injected = {"done": False}

        def _edit_after_text_publication(source, target):
            result = _real_link_new(source, target)
            if (os.path.normcase(os.path.abspath(target))
                    == os.path.normcase(os.path.abspath(_note))
                    and not _injected["done"]
                    and ".organize-stage-" in source):
                _injected["done"] = True
                with open(target, "w", encoding="utf-8") as _fh:
                    _fh.write("late editor readback save\n")
            return result

        with patch.object(
                _atomic_move, "link_noreplace",
                side_effect=_edit_after_text_publication):
            try:
                rename_all(_v, _pdf, "Doe_New_2025.pdf", apply=True)
                _readback_failure = None
            except RenameFailed as _exc:
                _readback_failure = _exc
        _recoveries = [os.path.join(_v, "Wiki", name)
                       for name in os.listdir(os.path.join(_v, "Wiki"))
                       if name.startswith(".organize-recovery-")]
        _recovered = (open(os.path.join(_recoveries[0], "topic.md"),
                           encoding="utf-8").read() if _recoveries else None)
        check("text readback preserves an editor save and the predecessor",
              (open(_note, encoding="utf-8").read(), _recovered,
               bool(_readback_failure and not _readback_failure.rolled_back),
               bool(_recoveries and
                    _reports_path(_readback_failure, _recoveries[0]))),
              ("late editor readback save\n", _old_note, True, True))

    # A platform/filesystem can reject the hard link after a complete rewrite
    # has been staged. Keep the distinct capability error and the usable draft.
    with _tf.TemporaryDirectory(prefix="org-note-no-link-") as _v:
        _note = _put(_v, "Wiki/topic.md", "original note\n")

        def _refuse_note_link(staged, target, *_args, **_kwargs):
            raise LinkUnavailable(
                staged, target,
                OSError(errno.ENOTSUP, "injected hard-link refusal", target))

        with patch.dict(globals(), replace_expected=_refuse_note_link):
            try:
                _write(_note, "complete rewrite\n")
                _note_link_error = None
            except LinkUnavailable as _exc:
                _note_link_error = _exc
        _stage = getattr(_note_link_error, "staging_path", None)
        _staged_note = (os.path.join(_stage, "topic.md") if _stage else None)
        check("a note link failure reports and preserves its complete rewrite",
              (isinstance(_note_link_error, LinkUnavailable),
               bool(_note_link_error and _note_link_error.keep_stage),
               bool(_stage and _reports_path(_note_link_error, _stage)),
               open(_note, encoding="utf-8").read(),
               open(_staged_note, encoding="utf-8").read()
               if _staged_note else None),
              (True, True, True, "original note\n", "complete rewrite\n"))
        if _stage:
            shutil.rmtree(_stage)

    # Remote URI paths are source data, not local vault references. Cover the
    # two forms the old `scheme://` span missed, and the filing debase pass as
    # well as the basename rewrite.
    _uri_body = ("[cdn](//cdn.example.org/files/download.pdf) "
                 "mailto:download.pdf [[download.pdf]]")
    check("protocol-relative and non-hierarchical URIs survive a rewrite",
          rewrite_text(_uri_body, {"download.pdf": "Doe_Study_2025.pdf"}, {}),
          ("[cdn](//cdn.example.org/files/download.pdf) "
           "mailto:download.pdf [[Doe_Study_2025.pdf]]"))
    _uri_new = ("[cdn](//cdn.example.org/files/Doe_Study_2025.pdf) "
                "[local](Inbox/Doe_Study_2025.pdf)")
    check("filing debases a local link without corrupting a protocol-relative URI",
          debase_links(_uri_new, {"Doe_Study_2025.pdf"}),
          ("[cdn](//cdn.example.org/files/Doe_Study_2025.pdf) "
           "[local](Doe_Study_2025.pdf)"))
    with _tf.TemporaryDirectory(prefix="org-external-uri-test-") as _v:
        _put(_v, "Wiki/only-remote.md",
             "//cdn.example.org/files/download.pdf mailto:download.pdf\n")
        check("external URI basenames do not count as vault references",
              references(_v, {"download.pdf"}), {})

    # Malformed JSON values are reported as chapter-plan problems rather than
    # escaping as AttributeError/TypeError, and YAML booleans are not accepted
    # as integer page indices through Python's bool-is-int relationship.
    _bad_chapters = [
        None,
        {"heading_text": 7, "filename": "Kuhn_S_2012_01_Intro.pdf",
         "start_idx": 0, "end_idx": 1},
        {"heading_text": "Chapter 1", "filename": 7,
         "start_idx": 0, "end_idx": 1},
        {"heading_text": "Chapter 1", "filename": "Kuhn_S_2012_01_Intro.pdf",
         "start_idx": False, "end_idx": 1},
    ]
    _bad_plan, _bad_problems, _bad_notes = _resolve(
        _bad_chapters, ["chapter 1"], 1, "/tmp/unused", {}, "Kuhn_S_2012")
    check("malformed chapter objects and boolean indices are refused cleanly",
          (bool(_bad_plan), len(_bad_problems), bool(_bad_notes)),
          (False, 4, False))

    # The final publication primitive is no-replace. A late destination must
    # retain its bytes, even after the earlier plan found the path free.
    with _tf.TemporaryDirectory(prefix="org-exclusive-chapter-test-") as _v:
        _staged = _put(_v, "staged.part", b"new chapter")
        _target = _put(_v, "chapter.pdf", b"late user file")
        try:
            _publish_new(_staged, _target)
            _exclusive = False
        except FileExistsError:
            _exclusive = True
        with open(_target, "rb") as _fh:
            _target_bytes = _fh.read()
        check("exclusive chapter publication preserves a late destination",
              (_exclusive, _target_bytes), (True, b"late user file"))

    with _tf.TemporaryDirectory(prefix="org-chapter-readback-test-") as _v:
        _staged = _put(_v, "staged.part", b"new chapter")
        _target = os.path.join(_v, "chapter.pdf")
        _real_link_new = _atomic_move.link_noreplace
        _injected = {"done": False}

        def _edit_chapter_after_publication(source, target):
            result = _real_link_new(source, target)
            if (source == _staged and target == _target
                    and not _injected["done"]):
                _injected["done"] = True
                with open(target, "wb") as _fh:
                    _fh.write(b"late chapter edit")
            return result

        with patch.object(
                _atomic_move, "link_noreplace",
                side_effect=_edit_chapter_after_publication):
            try:
                _publish_new(_staged, _target)
                _chapter_readback_refused = False
            except PublicationConflict:
                _chapter_readback_refused = True
        check("chapter readback preserves a post-link editor save",
              (_chapter_readback_refused, open(_target, "rb").read()),
              (True, b"late chapter edit"))

    # If a destination appears after split planning, preserve both that late
    # file and the complete staged chapter, and report the recovery location.
    with _tf.TemporaryDirectory(prefix="org-split-stage-test-") as _v:
        from pypdf import PdfReader as _TestPdfReader
        from pypdf import PdfWriter as _TestPdfWriter

        _book = os.path.join(_v, "Kuhn_S_2012.pdf")
        _source_writer = _TestPdfWriter()
        _source_writer.add_blank_page(width=100, height=100)
        with open(_book, "wb") as _fh:
            _source_writer.write(_fh)
        _reader_object = _TestPdfReader(_book)
        _reader_object.pages[0].extract_text = (
            lambda: "Chapter 1 Introduction " + "body " * 80)
        _out = os.path.join(_v, "Kuhn_S_2012")
        _chapter_target = os.path.join(
            _out, "Kuhn_S_2012_01_Intro.pdf")

        def _late_chapter_occupant(_staged, target):
            with open(target, "xb") as _fh:
                _fh.write(b"late user chapter")
            raise FileExistsError(errno.EEXIST, "injected late occupant", target)

        with patch.dict(
                globals(),
                _reader=lambda _path: _reader_object,
                _publish_new=_late_chapter_occupant):
            try:
                split_book(
                    _book,
                    [{"heading_text": "Chapter 1 Introduction",
                      "filename": "Kuhn_S_2012_01_Intro.pdf",
                      "start_idx": 0, "end_idx": 1}],
                    _out, verbose=False)
                _split_stage_error = None
            except SplitRefused as _exc:
                _split_stage_error = _exc
        _split_cause = getattr(_split_stage_error, "__cause__", None)
        _split_stage = getattr(_split_cause, "staging_path", None)
        _staged_parts = (sorted(os.listdir(_split_stage))
                         if _split_stage and os.path.isdir(_split_stage) else [])
        check("a late chapter occupant retains and reports the staged PDF",
              (open(_chapter_target, "rb").read(),
               bool(_split_stage
                    and _reports_path(_split_stage_error, _split_stage)),
               _staged_parts,
               open(os.path.join(_split_stage, _staged_parts[0]), "rb").read(4)
               if _staged_parts else None),
              (b"late user chapter", True, ["chapter-0001.part"], b"%PDF"))
        if _split_stage:
            shutil.rmtree(_split_stage)

    # Rollback may run after another writer replaced a published chapter. The
    # old pathname-only cleanup deleted that foreign file and then claimed the
    # split left nothing behind.
    with _tf.TemporaryDirectory(prefix="org-split-rollback-test-") as _v:
        _out = os.path.join(_v, "Kuhn_S_2012")
        _chapter = _put(_v, "Kuhn_S_2012/Kuhn_S_2012_01_Intro.pdf",
                        b"published chapter")
        _published_identity = _published_snapshot(_chapter)
        _replacement = _put(_v, "replacement.part", b"late foreign chapter")
        os.replace(_replacement, _chapter)
        _cleanup = _rollback_split(
            [(_chapter, _published_identity)], _out, True)
        _failure = _split_failure_message(
            os.path.join(_v, "Kuhn_S_2012.pdf"), 1, 2,
            OSError("injected publication failure"), _cleanup)
        check("split rollback preserves and names a late replacement",
              (open(_chapter, "rb").read(), "ROLLBACK INCOMPLETE" in _failure,
               _chapter in _failure, "different identity" in _failure,
               "nothing from this split is on disk" in _failure),
              (b"late foreign chapter", True, True, True, False))

    with _tf.TemporaryDirectory(prefix="org-split-rollback-edit-") as _v:
        _out = os.path.join(_v, "Kuhn_S_2012")
        _chapter = _put(_v, "Kuhn_S_2012/Kuhn_S_2012_01_Intro.pdf",
                        b"published chapter")
        _published = _published_snapshot(_chapter)
        # An in-place writer retains the inode; the digest is what prevents
        # rollback from deleting its later bytes.
        with open(_chapter, "wb") as _fh:
            _fh.write(b"late in-place edit")
        _cleanup = _rollback_split([(_chapter, _published)], _out, False)
        check("split rollback also preserves a same-inode late edit",
              (open(_chapter, "rb").read(),
               any("different identity" in item for item in _cleanup)),
              (b"late in-place edit", True))

    # Any recognized existing chapter of this book blocks a second split even
    # when the incoming plan picked a different abbreviation. This guard runs
    # before pypdf is needed.
    with _tf.TemporaryDirectory(prefix="org-existing-split-test-") as _v:
        _book = _put(_v, "Kuhn_S_2012.pdf", b"%PDF-1.4\n")
        _out = os.path.join(_v, "Kuhn_S_2012")
        _put(_v, "Kuhn_S_2012/Kuhn_S_2012_01_Intro.pdf", b"existing")
        try:
            split_book(_book, [{"heading_text": "Chapter 1",
                                "filename": "Kuhn_S_2012_01_Different.pdf",
                                "start_idx": 0, "end_idx": 1}],
                       _out, verbose=False)
            _existing_refusal = ""
        except SplitRefused as _exc:
            _existing_refusal = str(_exc)
        check("an existing chapter set blocks a parallel second split",
              "existing chapter set" in _existing_refusal, True)

    # Obsidian encodes local Markdown destinations. Repair those alongside
    # wikilinks, but decode only once and leave other documents/URLs alone.
    for _old in ("download (1).pdf", "download%20(1).pdf"):
        for _filing in (False, True):
            with _tf.TemporaryDirectory(prefix="org-url-link-test-") as _v:
                _home = "Inbox/Research Drafts" if _filing else "Sources/PDFs/Research Drafts"
                _pdf = _put(_v, _home + "/" + _old, b"original PDF bytes")
                _other = _put(_v, "Archive/" + _old, b"a different PDF")
                _url = "../" + quote(_home + "/" + _old)
                _foreign_url = "../Archive/" + quote(_old)
                _distinct = "download%20(1).pdf" if " " in _old else "download (1).pdf"
                _distinct_url = "../Archive/" + quote(_distinct)
                _body = ("[paper](" + _url + "#page=2)\n"
                         "[angle](<" + _url + "#page=3>)\n"
                         "[query](" + _url + "?download=1#page=4)\n"
                         "[other](" + _foreign_url + ")\n"
                         "[distinct](" + _distinct_url + ")\n"
                         "[publisher](https://example.org/" + quote(_old) + ")\n"
                         "[[" + _distinct + "]]\n")
                _note = _put(_v, "Wiki/topic.md", _body)
                _code, _, _ = _run_cli(["check", _pdf, "--vault", _v])
                check("the CLI sees URL-encoded local PDF references", _code, 1)
                _args = ["rename", _pdf, "--vault", _v,
                         "--to", "Doe_Method_2025.pdf", "--apply"]
                if _filing:
                    _args.extend(["--dest", os.path.join(_v, "Sources/PDFs")])
                _code, _, _ = _run_cli(_args)
                _new_url = ("Doe_Method_2025.pdf" if _filing else
                            "../" + quote(_home + "/Doe_Method_2025.pdf"))
                with open(_note, encoding="utf-8") as _fh:
                    check("encoded links follow rename/filing without changing foreign identities",
                          (_code, _fh.read()), (0, _body.replace(_url, _new_url)))
                _new_home = "Sources/PDFs" if _filing else _home
                with open(os.path.join(_v, _new_home, "Doe_Method_2025.pdf"), "rb") as _fh:
                    check("encoded-link repair preserves the source PDF", _fh.read(), b"original PDF bytes")
                with open(_other, "rb") as _fh:
                    check("encoded-link repair leaves same-basename foreign PDFs intact",
                          _fh.read(), b"a different PDF")

    for _legacy_first in (False, True):
        with _tf.TemporaryDirectory(prefix="org-source-precedence-test-") as _v:
            _legacy = 'source: "https://example.org/legacy"\n'
            _current = 'sources:\n- "[[Doe_Study_2025.pdf]]"\n'
            _fields = _legacy + _current if _legacy_first else _current + _legacy
            _note = _put(_v, "Articles/Doe_Study_2025.md", "---\n" + _fields + "---\n")
            check("current PDF provenance wins over a legacy URL in either key order",
                  _note_is_about(_note, "Doe_Study_2025"), True)

    with _tf.TemporaryDirectory(prefix="org-dotted-book-test-") as _v:
        _pdf = _put(_v, "Sources/PDFs/Doe_Book_2025.pdf")
        _put(_v, "Sources/PDFs/Doe_Book_2025.revised/Doe_Book_2025_01_Intro.pdf")
        check("a dotted foreign folder is not keyed to the undotted book",
              keyed_files(_v, _pdf), {_pdf: "Doe_Book_2025.pdf"})

    # Atomic note/sidecar rewrites must preserve privacy, including when the
    # transaction subsequently rolls back. A default 022 umask otherwise
    # turns deliberately group-readable 0640 files into world-readable 0644.
    for _rollback in (False, True):
        with _tf.TemporaryDirectory(prefix="org-private-write-test-") as _v:
            _pdf = _put(_v, "Sources/PDFs/Doe_Private_2025.pdf")
            _image = _put(_v, "Sources/Images/Doe_Private_2025_fig_1.png", b"private figure")
            _article = _put(_v, "Articles/Doe_Private_2025.md",
                            '---\nsources:\n- "[[Doe_Private_2025.pdf]]"\n---\n'
                            '![[Doe_Private_2025_fig_1.png]]\n')
            _wiki = _put(_v, "Wiki/topic.md", "[[Doe_Private_2025]]\n")
            _manifest = _put(_v, "Sources/Images/" + MANIFEST_FILE,
                             "Doe_Private_2025_fig_1.png\t" + file_digest(_image) + "\n")
            _review = _put(_v, "Sources/Images/" + REVIEW_FILE,
                           "Doe_Private_2025\t1\n")
            _protected = {_article: 0o640, _wiki: 0o640,
                          _manifest: 0o640, _review: 0o600}
            _before = {}
            for _file, _mode in list(_protected.items()):
                os.chmod(_file, _mode)
                _protected[_file] = stat.S_IMODE(os.stat(_file).st_mode)
                with open(_file, "rb") as _fh:
                    _before[_file] = _fh.read()
            _previous_umask = os.umask(0o022)
            try:
                with (patch.dict(globals(), move_noreplace=_fail_move)
                      if _rollback else contextlib.nullcontext()):
                    _code, _stdout, _stderr = _run_cli([
                        "rename", _pdf, "--vault", _v,
                        "--to", "Doe_Renamed_2025.pdf", "--apply"])
            finally:
                os.umask(_previous_umask)
            check("private-file CLI rename/rollback returns the expected status",
                  _code, 1 if _rollback else 0)
            _after_modes, _after_bodies = {}, {}
            for _file, _mode in _protected.items():
                _target = (_file.replace("Doe_Private_2025.md", "Doe_Renamed_2025.md")
                           if not _rollback and _file == _article else _file)
                _after_modes[_file] = stat.S_IMODE(os.stat(_target).st_mode)
                with open(_target, "rb") as _fh:
                    _after_bodies[_file] = _fh.read()
            check("note and sidecar permissions survive %s under umask 022"
                  % ("rollback" if _rollback else "an applied rename"),
                  _after_modes, _protected)
            check("note and sidecar contents %s with their permissions"
                  % ("roll back" if _rollback else "follow the rename"),
                  _after_bodies,
                  _before if _rollback else {
                      p: body.replace(b"Doe_Private_2025", b"Doe_Renamed_2025")
                      for p, body in _before.items()})

    # An old deterministic staging pathname may already belong to someone
    # else. Neither it nor a symlink target is permission to overwrite bytes.
    with _tf.TemporaryDirectory(prefix="org-temp-occupant-test-") as _v:
        _note = _put(_v, "note.md", "original note\n")
        _foreign = _put(_v, "unrelated.txt", "unrelated private bytes\n")
        os.chmod(_note, 0o640)
        os.chmod(_foreign, 0o600)
        _note_mode = stat.S_IMODE(os.stat(_note).st_mode)
        _foreign_mode = stat.S_IMODE(os.stat(_foreign).st_mode)
        _old_temp = "%s.organize-%d.tmp" % (_note, os.getpid())
        _have_temp_link = _try_symlink(_foreign, _old_temp)
        _previous_umask = os.umask(0o022)
        try:
            _write(_note, "new note\n")
        finally:
            os.umask(_previous_umask)
        with open(_foreign, encoding="utf-8") as _fh:
            check("a foreign old-style temporary symlink and its bytes survive",
                  (not _have_temp_link or
                   (os.path.islink(_old_temp)
                    and _fh.read() == "unrelated private bytes\n"
                    and stat.S_IMODE(os.stat(_foreign).st_mode)
                    == _foreign_mode)),
                  True)
        with open(_note, encoding="utf-8") as _fh:
            check("the note remains a regular private file after atomic replacement",
                  (os.path.islink(_note), _fh.read(), stat.S_IMODE(os.stat(_note).st_mode)),
                  (False, "new note\n", _note_mode))
        check("only the foreign temporary occupant remains after replacement",
              sorted(os.listdir(_v)), sorted(
                  ["note.md", "unrelated.txt"] +
                  ([os.path.basename(_old_temp)] if _have_temp_link else [])))

    for _old, _new in (("Doe_Canonical_2025.pdf", "Doe_Canonical_2025.pdf"),
                       ("doe_canonical_2025.pdf", "Doe_Canonical_2025.pdf")):
        with _tf.TemporaryDirectory(prefix="org-inbox-test-") as _v:
            _pdf = _put(_v, "Inbox/" + _old)
            _ref = _put(_v, "Wiki/topic.md", "[[Inbox/" + _old + "]]\n")
            _code, _stdout, _stderr = _run_cli([
                "rename", _pdf, "--vault", _v, "--to", _new, "--apply",
                "--dest", os.path.join(_v, "Sources/PDFs")])
            check("filing a canonical/case-only PDF reports success: " + _old,
                  (_code, os.path.exists(_pdf),
                   os.path.isfile(os.path.join(_v, "Sources/PDFs", _new))),
                  (0, False, True))
            with open(_ref, encoding="utf-8") as _fh:
                check("its existing reference remains valid after filing",
                      _fh.read(), "[[" + _new + "]]\n")

    with _tf.TemporaryDirectory(prefix="org-url-test-") as _v:
        _pdf = _put(_v, "Inbox/download.pdf")
        _url_body = ('---\nsources:\n- "https://example.org/papers/download.pdf"\n---\n'
                     '[Publisher](https://example.org/papers/download.pdf)\n'
                     '<https://example.org/papers/download.pdf>\n')
        _remote = _put(_v, "Articles/publisher.md", _url_body)
        check("publisher URLs are not references to the local PDF",
              references(_v, {"download.pdf"}), {})
        _local = _put(_v, "Wiki/topic.md",
                      '[Publisher](https://example.org/download.pdf)[[Inbox/download.pdf]]\n')
        _code, _, _ = _run_cli(["rename", _pdf, "--vault", _v,
                                "--to", "Doe_Method_2025.pdf", "--apply",
                                "--dest", os.path.join(_v, "Sources/PDFs")])
        with open(_remote, encoding="utf-8") as _fh:
            check("publisher URLs survive an applied rename byte for byte",
                  (_code, _fh.read()), (0, _url_body))
        with open(_local, encoding="utf-8") as _fh:
            check("a local link adjacent to a URL is still repaired", _fh.read(),
                  '[Publisher](https://example.org/download.pdf)[[Doe_Method_2025.pdf]]\n')

    for _stem, _quoted, _expected in (
            ("García", r'"[[Inbox/Garc\u00eda.pdf#page=2]]"',
             '"[[Doe_Method_2025.pdf#page=2]]"'),
            ("O'Reilly", "'[[Inbox/O''Reilly.pdf#page=2]]'",
             "'[[Doe_Method_2025.pdf#page=2]]'")):
        with _tf.TemporaryDirectory(prefix="org-yaml-source-test-") as _v:
            _pdf = _put(_v, "Inbox/" + _stem + ".pdf")
            _body = '---\ntitle: Preserve me\nsources: # origin\n- ' + _quoted + ' # verified\n---\nSummary.\n'
            _note = _put(_v, "Articles/" + _stem + ".md", _body)
            check("escaped YAML source is a located reference: " + _stem,
                  references(_v, {_stem + ".pdf"}), {_note: [_stem + ".pdf"]})
            _code, _, _ = _run_cli(["rename", _pdf, "--vault", _v,
                                    "--to", "Doe_Method_2025.pdf", "--apply",
                                    "--dest", os.path.join(_v, "Sources/PDFs")])
            _new_note = os.path.join(_v, "Articles/Doe_Method_2025.md")
            check("escaped-source note follows its PDF: " + _stem,
                  (_code, os.path.isfile(_new_note)), (0, True))
            if os.path.isfile(_new_note):
                with open(_new_note, encoding="utf-8") as _fh:
                    check("decoded source is rewritten without losing surrounding metadata",
                          _fh.read(), _body.replace(_quoted, _expected))

    with _tf.TemporaryDirectory(prefix="org-unowned-image-test-") as _v:
        _pdf = _put(_v, "Sources/PDFs/Doe_Old_2025.pdf", b"pdf bytes")
        _image = _put(_v, "Sources/Images/Doe_Old_2025_fig_1.png",
                      b"unattributed image bytes")
        _moves, _edits, _blockers = rename_all(
            _v, _pdf, "Doe_New_2025.pdf", apply=True)
        check("a loose same-stem image is never claimed without manifest ownership",
              (bool(_blockers), open(_pdf, "rb").read(),
               open(_image, "rb").read(), os.path.lexists(os.path.join(
                   _v, "Sources/Images/Doe_New_2025_fig_1.png"))),
              (True, b"pdf bytes", b"unattributed image bytes", False))

    with _tf.TemporaryDirectory(prefix="org-clipping-image-test-") as _v:
        _pdf = _put(_v, "Inbox/download.pdf")
        _body = ("---\nsources: # capture\n- 'https://example.org/O''Reilly'\n---\n"
                 "![[download_fig_1.jpg]]\n")
        _note = _put(_v, "Articles/download.md", _body)
        _image = _put(_v, "Sources/Images/download_fig_1.jpg", b"foreign clipping bytes")
        _moves, _edits, _blockers = rename_all(_v, _pdf, "Doe_Method_2025.pdf", apply=True)
        with open(_note, encoding="utf-8") as _fh, open(_image, "rb") as _im:
            check("a same-stem clipping's images block the whole rename unchanged",
                  (bool(_blockers), os.path.isfile(_pdf), _fh.read(), _im.read()),
                  (True, True, _body, b"foreign clipping bytes"))
        # A clipping may cite a PDF-owned image; a matching manifest digest
        # is the positive evidence that allows that image to follow the PDF.
        _put(_v, "Sources/Images/" + MANIFEST_FILE,
             "download_fig_1.jpg\t" + file_digest(_image) + "\n")
        _moves, _edits, _blockers = rename_all(_v, _pdf, "Doe_Method_2025.pdf", apply=True)
        check("verified PDF image ownership is sufficient despite a same-stem clipping",
              (_blockers, os.path.isfile(_note), os.path.isfile(os.path.join(
                  _v, "Sources/Images/Doe_Method_2025_fig_1.jpg"))), ([], True, True))

    with _tf.TemporaryDirectory(prefix="org-outside-source-test-") as _tmp:
        _v = os.path.join(_tmp, "vault")
        _inside_pdf = _put(_v, "Sources/PDFs/download.pdf", b"inside source")
        _outside_pdf = _put(_tmp, "Downloads/download.pdf", b"external source")
        _note = _put(_v, "Articles/download.md", "![[download.pdf]]\n")
        _image = _put(_v, "Sources/Images/download_fig_1.png", b"inside image")
        _snapshot = {p: open(p, "rb").read()
                     for p in (_inside_pdf, _outside_pdf, _note, _image)}
        _code, _, _ = _run_cli(["rename", _outside_pdf, "--vault", _v,
                                "--to", "Doe_Outside_2025.pdf", "--apply"])
        check("an independent download cannot take the vault's same-stem derivatives",
              (_code, {p: open(p, "rb").read() for p in _snapshot}), (1, _snapshot))
        _code, _, _ = _run_cli(["rename", _outside_pdf,
                                "--to", "Doe_Outside_2025.pdf", "--apply"])
        check("omitting --vault still supports an independent in-place rename",
              (_code, os.path.isfile(os.path.join(_tmp, "Downloads/Doe_Outside_2025.pdf")),
               os.path.isfile(_inside_pdf)), (0, True, True))

    # A linked source directory belongs to the vault through its logical path.
    # Resolving the candidate before the containment check rejects this normal
    # setup, while accepting the physical target path would let an unrelated
    # external invocation claim same-stem notes and figures from the vault.
    with _tf.TemporaryDirectory(prefix="org-linked-source-test-") as _tmp:
        _v = os.path.join(_tmp, "Vault")
        _store = os.path.join(_tmp, "pdf-store")
        os.makedirs(os.path.join(_v, "Inbox"))
        os.makedirs(os.path.join(_v, "Sources"))
        os.makedirs(_store)
        _linked_sources = os.path.join(_v, "Sources", "PDFs")
        _have_linked_sources = _try_symlink(
            _store, _linked_sources, target_is_directory=True)
        if _have_linked_sources:
            _inbox_pdf = _put(_v, "Inbox/download.pdf", b"linked destination")
            _moves, _edits, _blockers = rename_all(
                _v, _inbox_pdf, "Doe_Linked_2025.pdf", apply=True,
                dest=_linked_sources)
            _logical_pdf = os.path.join(_linked_sources, "Doe_Linked_2025.pdf")
            check("a linked source directory is an in-vault filing destination",
                  (_blockers, os.path.isfile(_logical_pdf)), ([], True))

            _moves, _edits, _blockers = rename_all(
                _v, _logical_pdf, "Doe_LinkedRevised_2025.pdf", apply=True)
            _logical_revised = os.path.join(
                _linked_sources, "Doe_LinkedRevised_2025.pdf")
            check("a PDF reached through a linked source directory stays in scope",
                  (_blockers, os.path.isfile(_logical_revised)), ([], True))

            _physical_pdf = os.path.join(_store, "Doe_LinkedRevised_2025.pdf")
            _moves, _edits, _blockers = plan_rename(
                _v, _physical_pdf, "Doe_Physical_2025.pdf")
            check("the linked directory's direct physical target stays outside",
                  (bool(_blockers), any("outside the vault" in b
                                        for b in _blockers)), (True, True))
            check("a symlink followed by parent traversal cannot escape scope",
                  _inside(_v, os.path.join(
                      _linked_sources, os.pardir, "escape.pdf")), False)
        else:
            for _label in (
                    "a linked source directory is an in-vault filing destination",
                    "a PDF reached through a linked source directory stays in scope",
                    "the linked directory's direct physical target stays outside",
                    "a symlink followed by parent traversal cannot escape scope"):
                check(_label + " (skipped without symlink privileges)", True, True)

    # Folded spelling is only a candidate identity. On an insensitive volume
    # the alternate spelling reaches the same inode and must work; on a
    # sensitive volume a distinct twin can exist and must remain outside.
    for _vault_name, _alias_name, _label in (
            ("CaseVault", "casevault", "case"),
            ("V\u00e4ult", unicodedata.normalize("NFD", "V\u00e4ult"),
             "Unicode normalization")):
        with _tf.TemporaryDirectory(prefix="org-vault-alias-test-") as _tmp:
            _v = os.path.join(_tmp, _vault_name)
            _alias = os.path.join(_tmp, _alias_name)
            os.makedirs(os.path.join(_v, "Inbox"))
            try:
                os.makedirs(os.path.join(_alias, "Inbox"))
            except FileExistsError:
                pass
            _same_directory = os.path.samefile(_v, _alias)
            check("%s alias follows filesystem directory identity" % _label,
                  _inside(_v, os.path.join(_alias, "Inbox", "future.pdf")),
                  _same_directory)

    with _tf.TemporaryDirectory(prefix="org-vault-symlink-alias-test-") as _tmp:
        _v = os.path.join(_tmp, "AliasVault")
        _alias = os.path.join(_tmp, "aliasvault")
        os.makedirs(_v)
        if not os.path.lexists(_alias):
            _have_alias_link = _try_symlink(
                _v, _alias, target_is_directory=True)
            check("a distinct folded-name symlink is not a filesystem alias",
                  (not _have_alias_link
                   or not _inside(_v, os.path.join(_alias, "future.pdf"))),
                  True)

    with _tf.TemporaryDirectory(prefix="org-src-book-test-") as _v:
        _book = _put(_v, "Sources/PDFs/Doe_Book_2025_src.pdf")
        _chapter = _put(_v, "Sources/PDFs/Doe_Book_2025_src/Doe_Book_2025_01_Intro.pdf")
        _book_image = _put(
            _v, "Sources/Images/Doe_Book_2025_01_Intro_fig_1.png")
        _put(_v, "Sources/Images/" + MANIFEST_FILE,
             "Doe_Book_2025_01_Intro_fig_1.png\t" +
             file_digest(_book_image) + "\n")
        _put(_v, "Wiki/topic.md", "[[Doe_Book_2025_01_Intro.pdf#page=1]]\n"
             "![[Doe_Book_2025_01_Intro_fig_1.png]]\n")
        _moves, _edits, _blockers = rename_all(_v, _book, "Doe_Renamed_2025_src.pdf", apply=True)
        check("a `_src` book rename carries independently named chapters",
              (_blockers, os.path.isfile(os.path.join(_v,
               "Sources/PDFs/Doe_Renamed_2025_src/Doe_Renamed_2025_01_Intro.pdf")),
               os.path.isfile(os.path.join(_v, "Sources/Images/Doe_Renamed_2025_01_Intro_fig_1.png"))),
              ([], True, True))
        with open(os.path.join(_v, "Wiki/topic.md"), encoding="utf-8") as _fh:
            check("chapter references follow a `_src` book rename too", _fh.read(),
                  "[[Doe_Renamed_2025_01_Intro.pdf#page=1]]\n"
                  "![[Doe_Renamed_2025_01_Intro_fig_1.png]]\n")
        _new_book = os.path.join(_v, "Sources/PDFs/Doe_Renamed_2025_src.pdf")
        _moves, _edits, _blockers = rename_all(_v, _new_book, "Doe_Renamed_2025_src_2.pdf", apply=True)
        check("renaming a split book cannot write invalid disambiguated chapters",
              (bool(_blockers), os.path.exists(_new_book)), (True, True))

    # Review regressions: directory names are link path segments, while the
    # same bare stem is an Obsidian note target and must remain untouched.
    with _tf.TemporaryDirectory(prefix="org-folder-link-test-") as _v:
        _book = _put(_v, "Sources/PDFs/Doe_Book_2025.pdf", b"%PDF-1.4\n")
        _put(_v, "Sources/PDFs/Doe_Book_2025/"
             "Doe_Book_2025_01_Intro.pdf", b"%PDF-1.4\n")
        _note = _put(
            _v, "Wiki/links.md",
            "[[Doe_Book_2025]]\n"
            "[[Sources/PDFs/Doe_Book_2025/"
            "Doe_Book_2025_01_Intro.pdf]]\n"
            "[[Archive/Doe_Book_2025/Unrelated.pdf]]\n")
        _moves, _edits, _blockers = plan_rename(
            _v, _book, "Roe_Book_2025.pdf")
        check("a split-book folder is rewritten only in link path context",
              (_blockers, _edits.get(_note)),
              ([], "[[Doe_Book_2025]]\n"
                    "[[Sources/PDFs/Roe_Book_2025/"
                    "Roe_Book_2025_01_Intro.pdf]]\n"
                    "[[Archive/Doe_Book_2025/Unrelated.pdf]]\n"))
        check("a case-only child rename also carries its directory spelling",
              rewrite_text(
                  "[[Sources/PDFs/doe_book_2025/"
                  "doe_book_2025_01_intro.pdf]]",
                  {"doe_book_2025_01_intro.pdf":
                   "Doe_Book_2025_01_Intro.pdf"}, {},
                  directory_ren={"doe_book_2025": "Doe_Book_2025"}),
              "[[Sources/PDFs/Doe_Book_2025/"
              "Doe_Book_2025_01_Intro.pdf]]")

    check("Dataview inline-field syntax does not mask a PDF reference",
          rewrite_text("paper::download.pdf\n",
                       {"download.pdf": "Doe_Study_2025.pdf"}, {}),
          "paper::Doe_Study_2025.pdf\n")

    with _tf.TemporaryDirectory(prefix="org-target-stem-test-") as _v:
        _pdf = _put(_v, "Sources/PDFs/download.pdf", b"%PDF-1.4\n")
        _put(_v, "Articles/Doe_Study_2025.md",
             "---\nsources:\n  - https://example.com/x\n---\n")
        _put(_v, "Sources/Images/Doe_Study_2025_fig_1.png", b"png")
        _moves, _edits, _blockers = plan_rename(
            _v, _pdf, "Doe_Study_2025.pdf")
        check("a target clipping note and image prefix block a PDF rename",
              (bool(_moves),
               any("Articles note" in item for item in _blockers),
               any("target figure stem" in item for item in _blockers)),
              (True, True, True))

    with _tf.TemporaryDirectory(prefix="org-malformed-source-test-") as _v:
        _pdf = _put(_v, "Sources/PDFs/Doe_Old_2025.pdf", b"%PDF-1.4\n")
        _put(_v, "Articles/Doe_Old_2025.md",
             "---\nsources:\n  - [[Doe_Old_2025.pdf]]\n---\n")
        _moves, _edits, _blockers = plan_rename(
            _v, _pdf, "Doe_New_2025.pdf")
        check("an unquoted source wikilink is an explicit ownership blocker",
              (bool(_moves), any("unquoted source wikilink" in item
                                 for item in _blockers)), (False, True))
        _other = _put(_v, "Articles/Other.md",
                      "---\nrelated:\n  - [[Doe_Old_2025.pdf]]\n---\n")
        check("an unrelated YAML list is not mistaken for malformed source metadata",
              _unquoted_source_claim(_other, "Doe_Old_2025"), False)

    with _tf.TemporaryDirectory(prefix="org-name-guard-test-") as _v:
        _pdf = _put(_v, "download.pdf", b"%PDF-1.4\n")
        check("rename refuses a portable but noncanonical target",
              any("not a canonical PDF name" in item for item in
                  plan_rename(None, _pdf, "Several_Title_Words_2025.pdf")[2]),
              True)
        _marked = _put(_v, "Doe_Study_2025_src.pdf", b"%PDF-1.4\n")
        check("rename cannot remove an existing `_src` marker",
              any("representation marker" in item for item in
                  plan_rename(None, _marked, "Doe_NewStudy_2025.pdf")[2]),
              True)
        _plain = _put(_v, "Doe_Plain_2025.pdf", b"%PDF-1.4\n")
        check("rename cannot add an `_src` marker",
              any("representation marker" in item for item in
                  plan_rename(None, _plain, "Doe_NewPlain_2025_src.pdf")[2]),
              True)
        check("rename preserves an existing `_src` marker",
              plan_rename(None, _marked,
                          "Doe_NewStudy_2026_src.pdf")[2], [])
        _raw_marked = _put(_v, "download_src.pdf", b"%PDF-1.4\n")
        check("a literal `_src` marker on raw intake can be preserved",
              plan_rename(None, _raw_marked,
                          "Doe_Download_2025_src.pdf")[2], [])
        check("a literal `_src` marker on raw intake cannot be dropped",
              any("representation marker" in item for item in
                  plan_rename(None, _raw_marked,
                              "Doe_Download_2025.pdf")[2]), True)
        _raw = _put(_v, "download", b"%PDF-1.4\n")
        check("an extensionless source cannot remain extensionless",
              any("explicit .pdf destination" in item for item in
                  plan_rename(None, _raw, "Doe_Study_2025")[2]), True)
        _chapters = _put(_v, "chapters.json", "[]\n")
        _wrong_out = os.path.join(_v, "arbitrary-folder")
        _code, _stdout, _stderr = _run_cli([
            "split", _pdf, "--chapters", _chapters, "--out", _wrong_out])
        check("split refuses a noncanonical output folder",
              (_code, "canonical chapter folder" in _stderr,
               os.path.lexists(_wrong_out)), (1, True, False))

    _repeated = [_norm("Chapter 1 Introduction") for _ in range(4)]
    _chapter = [{"heading_text": "Chapter 1 Introduction",
                 "filename": "Doe_Book_2025_01_Intro.pdf",
                 "start_idx": 2, "end_idx": 4}]
    check("a repeated running header cannot validate a chapter start",
          any("running header" in item for item in
              _resolve(_chapter, _repeated, 4, "/unused", {},
                       "Doe_Book_2025")[1]), True)
    _out_of_order = [
        {"heading_text": "Second", "filename": "Doe_Book_2025_02_Second.pdf",
         "start_idx": 0, "end_idx": 1},
        {"heading_text": "First", "filename": "Doe_Book_2025_01_First.pdf",
         "start_idx": 1, "end_idx": 2},
    ]
    check("chapter filename numbers must increase in input order",
          any("chapter number" in item for item in
              _resolve(_out_of_order, ["second", "first"], 2,
                       "/unused", {}, "Doe_Book_2025")[1]), True)

    failed = [c for c in cases if not c[1]]
    for label, ok, got, want in cases:
        if not ok:
            print("FAIL  %s\n        got  %r\n        want %r"
                  % (label, got, want))
    _test_workspace.cleanup()
    print("%d/%d self-test cases pass" % (len(cases) - len(failed), len(cases)))
    return 1 if failed else 0


def main(argv=None):
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfigure):
        try:
            reconfigure(encoding="utf-8", errors="backslashreplace")
        except (OSError, ValueError):
            pass
    p = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("check", help="the reference check, before a rename")
    c.add_argument("path")
    c.add_argument("--vault", default=None,
                   help="vault root; omit outside a vault")
    c.set_defaults(fn=_cmd_check)

    r = sub.add_parser("rename", help="plan or apply a rename")
    r.add_argument("path")
    r.add_argument("--to", required=True, metavar="NEW_BASENAME",
                   help="the new basename. The extension is never changed: "
                        "pass the source's own, or omit it. A different one "
                        "is refused rather than discarded.")
    r.add_argument("--vault", default=None)
    r.add_argument("--dest", default=None, metavar="DIR",
                   help="where the source file lands, when it should not stay "
                        "where it is — a vault's Sources/PDFs/ for a file "
                        "sitting in Inbox/. ABSOLUTE, and inside --vault when "
                        "one is given; both are refused otherwise, because a "
                        "path resolved against the shell's cwd moves the file "
                        "out of the vault while rewriting every link to it. "
                        "Figures, notes and chapter folders keyed to the same "
                        "stem are renamed in their own homes either way. "
                        "Created if absent.")
    r.add_argument("--apply", action="store_true",
                   help="write it. Without this, nothing is written.")
    r.set_defaults(fn=_cmd_rename)

    s = sub.add_parser("split", help="split a book into chapter PDFs")
    s.add_argument("pdf")
    s.add_argument("--chapters", required=True,
                   help="JSON list of chapter dicts")
    s.add_argument("--out", required=True, help="chapter output folder")
    s.add_argument("--vault", default=None)
    s.set_defaults(fn=_cmd_split)

    k = sub.add_parser("canonical", help="is a name already in output form?")
    k.add_argument("names", nargs="+")
    k.set_defaults(fn=_cmd_canonical)

    t = sub.add_parser("selftest", help="run the built-in adversarial cases")
    t.set_defaults(fn=lambda _args: _selftest())

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
