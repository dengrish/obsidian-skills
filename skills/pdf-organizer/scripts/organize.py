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
model re-derives wrongly — `keyed_files`' four-way stem fan-out, the
case-insensitive symlink-safe vault walk, the boundary-anchored single-pass
rewrite, and `_norm`-based +/-2 page verification — are now covered by
`--self-test` and compiled/imported by the plugin's test harness on every run.

Usage:
    # The reference check.  Run it before every rename.
    python3 organize.py check --vault ~/Obsidian/claude-main \\
        ~/Obsidian/claude-main/Sources/PDFs/download.pdf

    # Plan a rename (writes nothing) — this is also the reference report.
    python3 organize.py rename --vault ~/Obsidian/claude-main \\
        ~/Obsidian/claude-main/Sources/PDFs/download.pdf \\
        --to Prince_UDL_2026.pdf

    # Apply it: the file, its figures, its notes, its chapter folder and
    # chapters all move, and every `.md` reference is rewritten with them.
    python3 organize.py rename ... --to Prince_UDL_2026.pdf --apply

    # Outside a vault (a Downloads inbox): omit --vault.  The vault-wide
    # checks are reported as not-run rather than silently skipped.
    python3 organize.py rename ~/Downloads/download\\(1\\).pdf --to Smith_X_1776.pdf

    # Already in canonical form?  (Exit 0 = yes, 1 = no.)
    python3 organize.py canonical Prince_UDL_2026_02_SupLearn_src.pdf

    # Split a book.  chapters.json is a list of the chapter dicts described
    # in `references/book-splitting.md`.
    python3 organize.py split --vault ~/Obsidian/claude-main \\
        ~/Obsidian/claude-main/Sources/PDFs/Kuhn_StructSciRev_2012.pdf \\
        --chapters /tmp/chapters.json \\
        --out ~/Obsidian/claude-main/Sources/PDFs/Kuhn_StructSciRev_2012

    # The adversarial fixtures this module is held to.
    python3 organize.py selftest
"""
import argparse
import json
import os
import re
import sys
import unicodedata

# --- obsidian shared-layer bootstrap (canonical; see shared/CONVENTIONS.md) ---
import os as _os, sys as _sys
_here = _os.path.dirname(_os.path.abspath(__file__))
_env = _os.environ.get("OBSIDIAN_VAULT_SHARED")
if _env:                                   # explicit override: authoritative, no fallback
    _tried = [_os.path.abspath(_os.path.expanduser(_env))]
else:                                      # plugin-relative walk-up, at most 5 levels
    _tried, _d = [], _here
    for _ in range(5):
        _tried.append(_os.path.join(_d, "shared", "scripts"))
        _d = _os.path.dirname(_d)
_shared = next((_p for _p in _tried if _os.path.isdir(_p)), None)
if _shared is None:
    raise SystemExit("""obsidian: cannot find the plugin's shared/scripts/ folder, which holds
the one canonical copy of the conventions this script depends on.
Looked for:
  %s
Fix: install the whole plugin tree, or set OBSIDIAN_VAULT_SHARED to the
shared/scripts/ directory (unset it to use the plugin-relative walk-up).
Do NOT paste a second copy of the algorithm into this skill -- a divergent
copy is the bug the shared layer exists to prevent.""" % "\n  ".join(_tried))
_sys.path[:] = [_p for _p in _sys.path if _p not in (_shared, _here)]
_sys.path.insert(0, _shared)               # shared/scripts/ FIRST
_sys.path.append(_here)                    # own dir LAST: a local copy cannot shadow it
# --- end bootstrap ---

#: The filename shape is the plugin's, not this skill's: `pdf-figure-extractor`
#: reads the same rule to tell a book's chapters from the book.  It lives in
#: `shared/scripts/naming.py` and is imported, never restated — the two used to
#: hold separate copies and they disagreed about where `_src` sits, which cost
#: either every chapter's figures or a doubled set of them.  CONVENTIONS.md §1a.
from naming import (                       # noqa: E402  (after the bootstrap)
    CANONICAL,
    SAFE_NAME,
    chapter_book_stem,
    chapter_parts,
    core_stem,
    looks_canonical,
)
from figure_state import MANIFEST_FILE, REVIEW_FILE, rewrite_sidecar  # noqa: E402

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
    end the whole run at the first unreadable book (SKILL.md, *Batch Mode*
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


class RenameFailed(OSError):
    """A rename that got part-way and was rolled back.

    `rolled_back` is False when the rollback itself failed — the one state
    this module cannot repair, and the one the message has to say out loud.
    """

    def __init__(self, message, rolled_back=True):
        OSError.__init__(self, message)
        self.rolled_back = rolled_back


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
    seen = set()
    for dirpath, dirnames, filenames in os.walk(root, followlinks=True):
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

    Vault-wide and case-insensitive, because that is how Obsidian resolves a
    bare embed — a folder-local check is not the guarantee CONVENTIONS.md
    1a(1) promises.

    Every path is kept, not the first one walked: a name that already exists
    TWICE is the case the user most needs spelled out, and `setdefault` used
    to hand the blocker whichever copy `os.walk` reached first — so the
    message named one arbitrary file and the user fixed that one, re-ran, and
    was stopped again by the copy it had not mentioned.
    """
    out = {}
    for dirpath, dirnames, filenames in _walk(vault):
        for f in filenames + dirnames:
            # `_nfc_low`, not bare `lower()`: Obsidian (and the vault's APFS
            # volume) also folds Unicode normalization, so an NFD twin on disk
            # IS the name a derived NFC destination collides with.
            out.setdefault(_nfc_low(f), []).append(os.path.join(dirpath, f))
    return {low: sorted(paths) for low, paths in out.items()}


def _listdir(path):
    """`os.listdir`, or [] for anything unreadable.

    A permission-denied `Sources/Images/` must not abort a rename plan; it makes
    the plan incomplete, which is what `blockers` is for, not a traceback.
    """
    try:
        return os.listdir(path)
    except OSError:
        return []


def _nfc_low(name):
    """A filename reduced to the one spelling two of them are compared as.

    NFC first, then lowercased, and the SAME on both sides of every
    comparison — which is what `_dirkey` already does for directories and for
    the same two reasons.  Lowercased because the documented vault sits on a
    case-insensitive volume; NFC because macOS hands back NFD from
    `os.listdir` while the note that cites the file, the shell that typed it
    and this plugin's own earlier output all carry NFC, and the two spellings
    are byte-different, equal in every rendering, and so silently unequal to
    `str.lower()` alone.

    That miss is not cosmetic where `keyed_files` uses it: a source stored NFC
    whose figures are stored NFD fans out to the source alone, the rename
    moves the document and orphans the figures under a stem nothing looks for,
    and `references()` — which is asked about the names the fan-out found —
    comes back empty and tells the caller to proceed.  Reachable on APFS,
    which preserves whichever form each name was created with.

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
_SOURCES_ITEM = re.compile(r"\A\s+-\s*(.*)\Z")
_SOURCE_LINE = re.compile(r"\Asource\s*:\s*(.*)\Z", re.I)

#: The document a `source:` wikilink names.  Obsidian resolves by basename, so
#: only the last path segment matters.
_SRC_LINK = re.compile(r"\A!?\[\[([^\]|#]+)")


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

    A note with no readable frontmatter is claimed, which is the safe default
    here: those are this plugin's own older outputs, and leaving one behind
    under the old stem is the failure `keyed_files` exists to prevent.
    """
    def _named(raw_val):
        val = raw_val.strip()
        # A trailing YAML comment after the value is dropped the way
        # `dedup_index._yaml_scalar` and `paper_scan._yaml_scalar` drop it
        # (this docstring claims their two-key logic): for a quoted value the
        # closing quote ends it; for a bare one, ` #` does.  Without this,
        # `- "[[X.pdf]]" # note` still ended in `e`, the quote strip never
        # fired, and OUR OWN summary note read as somebody else's clipping —
        # left behind under the old stem by its document's rename.
        if val[:1] in "\"'":
            _close = val.find(val[0], 1)
            if _close != -1:
                val = val[:_close + 1]
        else:
            val = re.sub(r"\s+#.*\Z", "", val)
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1].strip()
        link = _SRC_LINK.match(val)
        if not link:
            return False              # a URL: somebody else's clipping
        base = link.group(1).strip().rstrip("/").split("/")[-1]
        # NFC on both sides, like every other name comparison in the
        # fan-out: an origin written NFC beside a note filed NFD is
        # byte-different, reads as somebody else's clipping, and the
        # note is left behind by its own document's rename.  The
        # `casefold` is the one this comparison already had, kept
        # rather than narrowed to `_nfc_low`'s `lower`: claiming a
        # note is the safe direction here, and nothing that used to
        # be claimed should stop being.
        return _nfc_low(os.path.splitext(base)[0]).casefold() \
            == _nfc_low(stem).casefold()

    try:
        with open(path, "r", encoding="utf-8-sig", errors="replace") as fh:
            for first in fh:
                if first.strip():
                    break
            else:
                return True
            if first.strip() != "---":
                return True
            pending = False
            for line in fh:
                if line.strip() == "---":
                    return True
                raw = line.rstrip("\n")
                if pending:
                    # Blank and comment-only lines between `sources:` and its
                    # first item are valid YAML (Obsidian still reads item 1);
                    # consuming the flag on one made the real item on the next
                    # line unread — and this reader's claimed-by-default then
                    # swept a URL clipping into the PDF's rename.  The sibling
                    # readers (dedup_index, paper_scan) skip them the same way.
                    if not raw.strip() or raw.lstrip().startswith("#"):
                        continue
                    pending = False
                    mi = _SOURCES_ITEM.match(raw)
                    if mi:
                        return _named(mi.group(1))
                if _SOURCES_KEY.match(raw):
                    pending = True    # the origin is the NEXT line
                    continue
                m = _SOURCE_LINE.match(raw)
                if not m:
                    continue
                return _named(m.group(1))
    except OSError:
        return True
    return True


def keyed_files(vault, path, _seen=None):
    """Every file whose *name* is derived from `path`'s stem.

    The file itself, its figures in `Sources/Images/`, any note named after it in
    a `NOTE_DIRS` folder, and — if it is a split book — its chapter folder
    under `Sources/PDFs/` and every chapter, each keyed the same way in turn.
    Returns {absolute path: basename}.  Matching is case-insensitive
    throughout, because the default vault sits on a case-insensitive volume
    and Obsidian resolves links case-insensitively either way — and
    normalisation-insensitive with it (`_nfc_low`), because a source stored
    NFC beside figures stored NFD is one document to every human reading the
    folder and two to `str.lower()`.

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
            if _nfc_low(f) == low + ".md" \
                    and _note_is_about(os.path.join(notedir, f), stem):
                out[os.path.join(notedir, f)] = f

    src = os.path.join(vault, "Sources/PDFs")
    identity = _nfc_low(core_stem(stem))
    for d in sorted(_listdir(src)):
        folder = os.path.join(src, d)
        if _nfc_low(core_stem(d)) != identity or not os.path.isdir(folder):
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
    NFC-in-note outright.  Lowercased for the reason `keyed_files` matches
    that way — the documented vault sits on a case-insensitive volume.

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
        # link alone, and SKILL.md's post-rename `assert not references(...)`
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
    permissive test then stopped seeing that link, so SKILL.md's post-rename
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


def references(vault, names, dirs=None):
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
    names = {n for n in names if n}
    if not names:
        return {}
    pat, lut, slut, _stems = _reference_re(names)
    hits = {}
    for md in md_files(vault):
        try:
            with open(md, encoding="utf-8", errors="replace") as fh:
                body = fh.read()
        except OSError:
            continue
        note_dir = os.path.relpath(os.path.dirname(md), vault)
        found = set()
        for m in pat.finditer(body):
            stem = _stem_match(m)
            if stem is not None:
                name = _canonical_name(slut, stem)
                if _qualifies(m, name, dirs, note_dir):
                    found.add(name)
            else:
                name = _canonical_name(lut, m.group("name"))
                # The basename branch used to skip `_qualifies` entirely, so a
                # `[[Sources/PDFs/download.pdf]]` naming a DIFFERENT file of
                # that basename was reported as a reference to the keyed one --
                # and then repointed at it by the rewrite.  That is the exact
                # failure `_qualifies` exists to prevent, and it was
                # unimplemented for the only file type this skill renames.
                if _qualifies_qual(_qual_before(body, m.start("name")),
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
    return (re.compile(r"(!?\[\[)((?!\w+:)[^\[\]\n|#]*/)(%s)(?=[ \t]*[\]\\|#])"
                       % esc),
            re.compile(r"(\]\()((?!\w+:)[^()\s\n]*/)(%s)(?=[)#])" % esc))


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
    for name in sorted(names, key=len, reverse=True):
        if not name:
            continue
        for rx in _debase_res(name):
            text = rx.sub(r"\1\3", text)
    return text


def rewrite_text(text, ren, stem_ren, dirs=None, note_dir=""):
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

    def repl(m):
        stem = _stem_match(m)
        if stem is not None:
            name = _canonical_name(slut, stem)
            if not _qualifies(m, name, dirs, note_dir):
                return m.group(0)         # names a different file: not ours
            return m.group("open") + _canonical_name(new_stem_of, stem)
        name = m.group("name")
        # The basename branch ran no `_qualifies` check at all, while
        # `references()` -- the guard that decides whether this rewrite may
        # happen -- runs one.  The two disagreed in the direction with no
        # safety net: beside a keyed `Inbox/download.pdf`, a note citing
        # `[[Sources/PDFs/download.pdf#page=3]]` (a DIFFERENT document) was
        # correctly NOT reported as a reference, so the caller renamed -- and
        # this line repointed the note at the renamed file anyway, after which
        # `debase_links` stripped the folder that was the only evidence of
        # what it used to mean.  Both the pre-check and the documented
        # post-rename `assert not references(vault, old, dirs=dirs)` pass on
        # the corrupted vault, because both ask about the OLD name and the
        # link no longer carries it.  Same call `references()` makes, on the
        # same canonical name, so the two cannot drift apart again.
        if not _qualifies_qual(_qual_before(text, m.start("name")),
                               _canonical_name(lut, name), dirs, note_dir):
            return m.group(0)
        return _canonical_name(new_of, name)

    return pat.sub(repl, text)


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
    identity = unicodedata.normalize("NFC", core_stem(old_stem))
    if identity != head and _nfc_low(nfc[:len(identity)]) == _nfc_low(identity):
        return core_stem(new_stem) + nfc[len(identity):]
    return basename                                   # not ours; leave it


def _inside(vault, path):
    """True when `path` is the vault itself or sits under it."""
    v = os.path.realpath(vault)
    p = os.path.realpath(path)
    return p == v or p.startswith(v + os.sep)


def _plan_figure_state(vault, ren):
    """Plan metadata updates for the images and PDF stems being renamed."""
    edits, blockers = {}, []
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
            with open(path, encoding="utf-8", newline="") as fh:
                body = fh.read()
            new = rewrite_sidecar(body, mapping, kind)
            if new != body:
                if not (os.access(path, os.W_OK)
                        and os.access(os.path.dirname(path), os.W_OK)):
                    raise ValueError("sidecar is not writable")
                edits[path] = new
        except (OSError, UnicodeError, ValueError) as exc:
            blockers.append("%s cannot safely follow the source rename (%s). "
                            "Repair its records first; do not delete/reset ownership metadata."
                            % (path, exc))
    return edits, blockers


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

    # THIS SKILL RENAMES THE STEM AND NEVER THE EXTENSION (SKILL.md, *Naming
    # Convention*: "always preserves the original extension; only the base
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

    keyed = keyed_files(vault, path) if have_vault \
        else {path: src_basename}
    ren = {b: _derive(old_stem, b, new_stem) for b in keyed.values()}

    # A source that arrived with no extension at all (`download`, a browser
    # save) is the one case where the caller's extension is new information
    # rather than a contradiction: there is nothing to preserve, so supply it.
    # Only the source file is affected — a derived figure or note keeps its
    # own extension, which `_derive` carries through in the tail.
    if not old_ext and new_ext:
        ren[src_basename] = new_stem + new_ext

    blockers = []

    # Renaming an already-split book must not mint chapter names a later
    # extractor refuses or attributes to a different book. In particular a
    # `_2` disambiguator cannot be inserted before the chapter segment.
    for old, new in ren.items():
        book = chapter_book_stem(old) if old.lower().endswith(".pdf") else None
        if book and _nfc_low(book) == _nfc_low(core_stem(old_stem)):
            new_book = chapter_book_stem(new)
            if not looks_canonical(new) or new_book is None \
                    or _nfc_low(new_book) != _nfc_low(core_stem(new_stem)):
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
            vreal = os.path.realpath(vault)
            dreal = os.path.realpath(dest)
            if dreal != vreal and not dreal.startswith(vreal + os.sep):
                blockers.append(
                    "destination %s is outside the vault %s. Moving a document "
                    "out of the vault while rewriting the notes that cite it "
                    "leaves every one of those links resolving to nothing."
                    % (dest, vault))

    # Two keyed names differing only in case OR Unicode normalization are two
    # files on a plain Linux volume and one file on the vault's own, and they
    # derive to ONE new name (`_derive` writes NFC).  Left alone, the second
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

    mine = {os.path.realpath(p) for p in keyed}
    existing = vault_names(vault) if have_vault else {}
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
    # `os.path.realpath` does not case-fold, so on a case-INSENSITIVE volume --
    # the documented default vault -- a case-only rename (`foo.pdf` ->
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
    # `_write`'s temp-file-plus-`os.replace` goes straight through a read-only
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
        for md in md_files(vault):
            try:
                with open(md, encoding="utf-8") as fh:
                    body = fh.read()
            except (OSError, UnicodeDecodeError) as exc:
                # A blocker here dead-ends every rename in the vault on one
                # stray legacy note, including renames that note does not
                # mention -- and SKILL.md says never work around a blocker.
                # It is only a blocker if the file could actually be citing
                # one of the names being changed, which is decidable: re-read
                # it leniently and look.
                try:
                    with open(md, encoding="utf-8", errors="replace") as fh:
                        loose = fh.read()
                except OSError:
                    loose = ""
                if loose and references_in_text(loose, ren, stem_ren):
                    blockers.append(
                        "%s cites a name this rename changes but could not be "
                        "read as UTF-8 (%s), so its links cannot be rewritten. "
                        "Fix the file's encoding, then re-run."
                        % (md, type(exc).__name__))
                else:
                    unreadable.append("%s (%s)" % (md, type(exc).__name__))
                continue
            new = rewrite_text(body, ren, stem_ren, dirs,
                               os.path.relpath(os.path.dirname(md), vault))
            if moved_names:
                new = debase_links(new, moved_names)
            if new != body:
                edits[md] = new
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
        edits.sidecars, sidecar_blockers = _plan_figure_state(vault, ren)
        blockers.extend(sidecar_blockers)
    return moves, edits, blockers


def references_in_text(text, ren, stem_ren):
    """Does `text` cite any name being renamed?  Cheap, lenient, read-only."""
    names = set(ren) | set(stem_ren)
    if not names:
        return False
    pat, _lut, _slut, _stems = _reference_re({n for n in names if n})
    return pat.search(text) is not None


def _write(path, text):
    """Replace `path`'s contents atomically.

    Temp file plus `os.replace`, so a write that dies part-way leaves the
    original intact rather than a truncated note — "nothing from this rename
    is on disk" has to be true of the notes as well as the files.
    """
    # `_walk` follows symlinks so a synced or shared subfolder is covered.
    # Replacing a symlinked note would sever it: the vault gets a regular file
    # and the shared original keeps the old, now-dangling reference.  Write
    # through the link instead, to the file it actually names.
    if os.path.islink(path):
        real = os.path.realpath(path)
        tmp = "%s.organize-%d.tmp" % (real, os.getpid())
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                fh.write(text)
            os.replace(tmp, real)
            return
        except BaseException:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise
    tmp = "%s.organize-%d.tmp" % (path, os.getpid())
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


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
    """
    moves, edits, blockers = plan_rename(vault, path, new_basename, dest)
    if not apply or blockers:
        return moves, edits, blockers

    done_edits, done_moves, made_dirs = {}, [], []
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
            with open(md, encoding="utf-8", newline="") as fh:
                done_edits[md] = fh.read()
            _write(md, new)
        for src, dst in moves:
            if os.path.realpath(src) != os.path.realpath(dst):
                os.rename(src, dst)
                done_moves.append((src, dst))
    except BaseException as exc:
        failed = []
        for src, dst in reversed(done_moves):
            try:
                os.rename(dst, src)
            except OSError as back:
                failed.append("%s -> %s (%s)" % (dst, src, back))
        for md, old_body in done_edits.items():
            try:
                _write(md, old_body)
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
    for ch in chapters:
        missing = {"heading_text", "filename", "start_idx", "end_idx"} - set(ch)
        if missing:
            problems.append("chapter %r: missing %s"
                            % (ch.get("filename", ch), ", ".join(sorted(missing))))
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
        if not looks_canonical(chap_stem):
            problems.append("%r: not a name pdf-organizer produces, so "
                            "pdf-figure-extractor and paper-summarizer will "
                            "refuse it as unorganized. Use "
                            "Author_Work_Year_NN_ChapterName.pdf with a "
                            "two-digit NN (CONVENTIONS.md 1a)." % name)
            continue
        of_book = chapter_book_stem(chap_stem)
        if of_book is None:
            problems.append("%r: has no `_NN_ChapterName` segment, so nothing "
                            "downstream can tell it is a chapter of this book."
                            % name)
            continue
        if book_stem is not None and core_stem(of_book) != core_stem(book_stem):
            problems.append("%r: names chapter of %r, but the book being split "
                            "is %r. Chapters carry their own book's stem, or "
                            "their figures are filed under the other book's."
                            % (name, of_book, book_stem))
            continue
        if len(needle) < 3:
            problems.append("%s: heading_text %r is too short to verify a page "
                            "mapping with — give the chapter's printed "
                            "heading, not a placeholder."
                            % (name, ch["heading_text"]))
            continue
        if not isinstance(start, int) or not isinstance(end, int):
            problems.append("%s: start_idx/end_idx must be integer 0-based "
                            "page indices, got %r and %r"
                            % (name, start, end))
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
        # `os.replace` would silently consume it. Matched case-insensitively,
        # because the default vault sits on a case-insensitive volume where
        # `..._01_NormSci.pdf` and `..._01_normsci.pdf` are one path.
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
                            "%r; filenames differing only in case are one file "
                            "on a case-insensitive volume) — keep more words "
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
    part-way removes what this run just created, so the same holds for the
    second pass.

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
    if looks_canonical(identity) and chapter_parts(identity) is None \
            and not looks_canonical(identity + "_01_Chapter"):
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
    taken = taken or {}
    # `_reader` first, and the writer import after it: both come from pypdf,
    # and `_reader` is the one that turns a missing pypdf into a `SplitRefused`
    # with an install line in it. Importing PdfWriter above that call meant the
    # bare `ImportError` escaped instead — which SKILL.md's *Batch Mode* step 4
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
    if not chapters:
        raise SplitRefused("%s: no chapters detected — ask the user for page "
                           "ranges rather than writing an empty folder."
                           % pdf_path)

    plan, problems, notes = _resolve(chapters, text, n_pages, out_dir, taken,
                                     core_stem(pdf_path))
    if problems:
        raise SplitRefused("Not splitting %s. Fix these first:\n  - "
                           % os.path.basename(pdf_path)
                           + "\n  - ".join(problems))

    # --- Pass 2: write. Every target is in range and proved free. A failure
    # part-way removes what this run just created — half a split is worse
    # than none, and these are files that did not exist a second ago. ---
    made_dir = not os.path.isdir(out_dir)
    os.makedirs(out_dir, exist_ok=True)
    tmp = os.path.join(out_dir, ".split-%d.part" % os.getpid())
    written = []
    try:
        for start, end, target, name in plan:
            writer = PdfWriter()
            for i in range(start, end):
                writer.add_page(reader.pages[i])
            with open(tmp, "wb") as fh:
                writer.write(fh)
            os.replace(tmp, target)
            written.append(target)
            if verbose:
                print("%s  pages %d-%d" % (name, start + 1, end))
    except BaseException as exc:
        for f in written + [tmp]:
            try:
                os.remove(f)
            except OSError:
                pass
        if made_dir:
            try:
                os.rmdir(out_dir)
            except OSError:
                pass
        raise SplitRefused("%s: write failed after %d of %d chapters (%s: %s). "
                           "Rolled back — nothing from this split is on disk."
                           % (pdf_path, len(written), len(plan),
                              type(exc).__name__, exc))
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
        mark = "" if os.path.realpath(src) != os.path.realpath(dst) \
            else "   (no change)"
        print("  %s\n    -> %s%s" % (src, dst, mark))
    print("Note rewrites (%d):" % len(edits))
    for md in sorted(edits):
        print("  %s" % md)
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


def _cmd_check(args):
    vault = os.path.expanduser(args.vault) if args.vault else None
    path = os.path.expanduser(args.path)
    if not vault or not os.path.isdir(vault):
        print("No vault to scan (--vault %s). The vault-wide reference check "
              "did NOT run; say so in the report rather than reporting the "
              "file as unreferenced." % (args.vault or "not given"))
        return 0
    keyed = keyed_files(vault, path)
    print("Names keyed to %s (%d):" % (os.path.basename(path), len(keyed)))
    for p, b in sorted(keyed.items()):
        print("  %-44s %s" % (b, p))
    refs = references(vault, set(keyed.values()), keyed_dirs(vault, keyed))
    if not refs:
        print("\nNo references. Rename immediately — this is the normal case.")
        return 0
    print("\nREFERENCED — do not rename without asking the user:")
    for md in sorted(refs):
        print("  %s\n    cites: %s" % (md, ", ".join(refs[md])))
    return 1


def _cmd_rename(args):
    vault = os.path.expanduser(args.vault) if args.vault else None
    path = os.path.expanduser(args.path)
    if not vault or not os.path.isdir(vault):
        print("No vault (--vault %s): the vault-wide uniqueness and reference "
              "checks did not run. Only the literal destination is checked."
              % (args.vault or "not given"))
    keyed = keyed_files(vault, path) if vault and os.path.isdir(vault) else {}
    old = set(keyed.values())
    # Located BEFORE the rename and reused after it: a rename changes basenames
    # and never directories, so this still says where each old name lived —
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
    if args.apply and old:
        left = references(vault, old, old_dirs)
        if left:
            print("INCOMPLETE — these notes still cite an old name:",
                  file=sys.stderr)
            for md in sorted(left):
                print("  %s: %s" % (md, ", ".join(left[md])), file=sys.stderr)
            return 1
        print("Verified: no note cites any of the %d old names." % len(old))
    return 0


def _cmd_split(args):
    vault = os.path.expanduser(args.vault) if args.vault else None
    with open(os.path.expanduser(args.chapters), encoding="utf-8") as fh:
        chapters = json.load(fh)
    taken = vault_names(vault) if vault and os.path.isdir(vault) else {}
    try:
        split_book(os.path.expanduser(args.pdf), chapters,
                   os.path.expanduser(args.out), taken)
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
    cases = []

    def check(label, got, want):
        cases.append((label, got == want, got, want))

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

    # 14. The extension is never changed (SKILL.md, *Naming Convention*).
    #     A caller passing a different one has the wrong file in hand, so it
    #     is refused; a source with no extension at all is the one case where
    #     the caller's is new information rather than a contradiction.  This
    #     used to be a silent discard, which turned `download` +
    #     `Smith_X_1776.pdf` into an extensionless `Smith_X_1776`, breaking
    #     every downstream `![[...pdf]]` embed with no blocker raised.
    import tempfile as _tf
    for src, new, want in (("download", "Smith_X_1776.pdf", "Smith_X_1776.pdf"),
                           ("paper.pdf", "Smith_X_1776.pdf", "Smith_X_1776.pdf"),
                           ("paper.pdf", "Smith_X_1776", "Smith_X_1776.pdf"),
                           ("download.PDF", "Smith_X_1776.pdf", "Smith_X_1776.PDF"),
                           ("notes.txt", "Smith_X_1776.pdf", None)):
        _v = _tf.mkdtemp()
        _p = os.path.join(_v, src)
        with open(_p, "wb") as _fh:
            _fh.write(b"%PDF")
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
            # The path is compared the way the vault resolves it: case-folded
            # (the documented vault is on a case-insensitive volume) and past a
            # heading anchor.
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
    _qv = _tf.mkdtemp()

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
    _dv = _tf.mkdtemp()

    def _dw(rel, body):
        p = os.path.join(_dv, *rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(body)
        return p

    _inbox_pdf = _dw("Inbox/download (1).pdf", "%PDF")
    _dw("Sources/Images/download (1)_fig_1.png", "x")
    _dw("Articles/download (1).md", "a note\n")
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
    _rv = _tf.mkdtemp()
    _rpdf = os.path.join(_rv, "Inbox", "download.pdf")
    os.makedirs(os.path.dirname(_rpdf))
    with open(_rpdf, "w", encoding="utf-8") as fh:
        fh.write("%PDF")
    _, _, _relb = plan_rename(_rv, _rpdf, "Smith_X_1776.pdf",
                              dest="Sources/PDFs")
    check("--dest: a relative destination is a blocker",
          bool(_relb) and "relative path" in _relb[0], True)
    _, _, _outb = plan_rename(_rv, _rpdf, "Smith_X_1776.pdf",
                              dest=_tf.mkdtemp())
    check("--dest: a destination outside the vault is a blocker",
          bool(_outb) and "outside the vault" in _outb[0], True)

    # 16d. A note citing the moved file by a FOLDER-QUALIFIED link must not be
    #      left pointing at the folder the file just left.  Rewriting the name
    #      inside the old qualification is a working link turned dangling --
    #      silently, and the post-rename re-probe cannot see it because it
    #      searches for old NAMES and this one carries the new one.
    _qv2 = _tf.mkdtemp()

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
    _fv = _tf.mkdtemp()

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
    _rv = _tf.mkdtemp()
    _rpdf = os.path.join(_rv, "Inbox", "download.pdf")
    os.makedirs(os.path.dirname(_rpdf))
    with open(_rpdf, "w", encoding="utf-8") as fh:
        fh.write("%PDF")
    _, _, _relb = plan_rename(_rv, _rpdf, "Smith_X_1776.pdf",
                              dest="Sources/PDFs")
    check("--dest: a relative destination is a blocker",
          bool(_relb) and any("relative path" in b for b in _relb), True)
    _, _, _outb = plan_rename(_rv, _rpdf, "Smith_X_1776.pdf",
                              dest=_tf.mkdtemp())
    check("--dest: a destination outside the vault is a blocker",
          bool(_outb) and any("outside the vault" in b for b in _outb), True)
    _, _, _novb = plan_rename(None, _rpdf, "Smith_X_1776.pdf",
                              dest=os.path.join(_rv, "Sources", "PDFs"))
    check("--dest: no vault to move into is a blocker",
          bool(_novb) and any("no vault" in b for b in _novb), True)
    _outside = os.path.join(_tf.mkdtemp(), "download.pdf")
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
    _nv = _tf.mkdtemp()

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
    # A note this plugin wrote before frontmatter existed is still claimed:
    # leaving one behind under the old stem is what keyed_files prevents.
    _nw("Articles/Doe_Foo_2025.md", "just a body\n")
    check("a note with no frontmatter is claimed",
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
    # End to end: the clipping is not merely un-keyed, it is absent from the
    # rename plan — the note stays where the user's clipping run put it.
    _nw("Articles/Doe_Foo_2025.md",
        '---\ntitle: x\nsources:\n  - "https://example.com/doe-foo"\n---\n'
        'prose\n')
    _cmoves, _, _cblock = plan_rename(_nv, _npdf, "Smith_Match_2026.pdf")
    check("a current-schema clipping is not in the rename plan",
          (sorted(os.path.basename(s) for s, _d in _cmoves), _cblock),
          (["Doe_Foo_2025.pdf"], []))

    # NFC/NFD twin figure files derive to ONE new name (`_derive` writes NFC)
    # and must be a BLOCKER, exactly like the case-twin pair: grouped under
    # `b.lower()` the twins landed in two groups, sailed past the guard, and
    # the second `os.rename` silently destroyed the first figure's bytes.
    _uv = _tf.mkdtemp()
    _updf = os.path.join(_uv, "Inbox", "Müller_Uber_2001.pdf")
    os.makedirs(os.path.dirname(_updf))
    with open(_updf, "w", encoding="utf-8") as fh:
        fh.write("%PDF")
    os.makedirs(os.path.join(_uv, "Sources", "Images"))
    _twins = ("Müller_Uber_2001_fig_1.png",         # NFC
              "Müller_Uber_2001_fig_1.png")         # NFD
    for _twin in _twins:
        with open(os.path.join(_uv, "Sources", "Images", _twin), "w") as fh:
            fh.write(_twin)
    # APFS cannot store both normalization spellings in one directory. Model
    # the listing a normalization-sensitive filesystem supplies, so the same
    # collision guard is exercised on macOS and Linux without skipping it.
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
    _mv = _tf.mkdtemp()
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
    _pv = _tf.mkdtemp()
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
    _qv3 = _tf.mkdtemp()

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
        _sv = _tf.mkdtemp()
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
        v = _tf.mkdtemp(prefix="orgtest-")
        for d in dirs:
            os.makedirs(os.path.join(v, d), exist_ok=True)
        return v

    def _put(v, rel, data=b"%PDF-1.4\n"):
        p_ = os.path.join(v, rel)
        os.makedirs(os.path.dirname(p_), exist_ok=True)
        mode = "wb" if isinstance(data, bytes) else "w"
        with open(p_, mode) as fh:
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
    with open(os.path.join(_v, "Articles/c.md")) as _fh:
        check("a URL ending in the new basename is left alone", _fh.read(), _url)

    # A symlinked source is refused, not moved as a link.
    _v = _vault("Store", "Sources/PDFs")
    _put(_v, "Store/real.pdf")
    os.symlink("../Store/real.pdf", os.path.join(_v, "Sources/PDFs/real.pdf"))
    _m, _e, _b = rename_all(_v, os.path.join(_v, "Sources/PDFs/real.pdf"),
                            "Smith_X_1776.pdf")
    check("a symlinked source is refused",
          any("is a symlink to" in b for b in _b), True)

    # A symlinked note is written THROUGH the link, not replaced.
    _v = _vault("Store", "Sources")
    _put(_v, "Store/n.md", "![[old.pdf]]\n")
    os.symlink("../Store/n.md", os.path.join(_v, "Sources/n.md"))
    _write(os.path.join(_v, "Sources/n.md"), "![[new.pdf]]\n")
    check("a symlinked note stays a symlink",
          os.path.islink(os.path.join(_v, "Sources/n.md")), True)
    with open(os.path.join(_v, "Store/n.md")) as _fh:
        check("the shared original is what got rewritten", _fh.read(),
              "![[new.pdf]]\n")

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
    with open(os.path.join(_v, "Wiki/concept.md")) as _fh:
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

    # 4. A source stored NFC beside figures stored NFD -- ordinary on APFS,
    #    which keeps whichever form each name was created with.  The fan-out
    #    compared raw `str.lower()`, so it found the document alone: the
    #    rename moved it, orphaned three figures under a stem nothing looks
    #    for, and `references()` -- asked only about the name it did find --
    #    came back empty and told the caller to go ahead.
    _nfc = unicodedata.normalize("NFC", "M\xfcller_Uber_2001")
    _nfd = unicodedata.normalize("NFD", "M\xfcller_Uber_2001")
    _v = _vault("Inbox", "Sources/PDFs", "Sources/Images", "Articles")
    _put(_v, "Inbox/%s.pdf" % _nfc)
    for _i in (1, 2, 3):
        _put(_v, "Sources/Images/%s_fig_%d.png" % (_nfd, _i))
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
          ["Muller_Uber_2001_fig_%d.png" % _i for _i in (1, 2, 3)])
    check("...the note among them",
          sorted(_listdir(os.path.join(_v, "Articles"))),
          ["Muller_Uber_2001.md"])
    _note_now = os.path.join(_v, "Articles/Muller_Uber_2001.md")
    _got = "(the note was left behind under its old stem)"
    if os.path.isfile(_note_now):                 # absent IS the failure
        with open(_note_now) as _fh:
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
        _manifest_body = ("# keep metadata comments\nDoe_Old_2025_fig_1.png\t" + "a" * 64
                          + "\nOther_fig_2.png\t" + "b" * 64 + "\n")
        _review_body = "# checked manually\nDoe_Old_2025\t1\tkeep my note\nOther:2\n"
        _manifest = _put(_v, "Sources/Images/" + MANIFEST_FILE, _manifest_body)
        _review = _put(_v, "Sources/Images/" + REVIEW_FILE, _review_body)
        _moves, _edits, _blockers = plan_rename(_v, _pdf, "Doe_New_2025.pdf")
        check("sidecar changes appear separately in a rename plan",
              (len(_edits), len(_edits.sidecars), _blockers), (0, 2, []))
        with open(_manifest) as _fh:
            check("a sidecar dry run writes nothing", _fh.read(), _manifest_body)
        # Force a move failure after the state updates to exercise rollback.
        with patch("os.rename", side_effect=OSError("injected move failure")):
            try:
                rename_all(_v, _pdf, "Doe_New_2025.pdf", apply=True)
                _rolled_back = False
            except RenameFailed as _exc:
                _rolled_back = _exc.rolled_back
        check("a failed rename rolls sidecars back too", _rolled_back, True)
        with open(_manifest) as _fh:
            check("manifest restored after failed move", _fh.read(), _manifest_body)
        with open(_review) as _fh:
            check("review ledger restored after failed move", _fh.read(), _review_body)
        rename_all(_v, _pdf, "Doe_New_2025.pdf", apply=True)
        with open(_manifest) as _fh:
            check("successful rename carries ownership and unrelated records",
                  parse_manifest(_fh.read()),
                  {"Doe_New_2025_fig_1.png": "a" * 64, "Other_fig_2.png": "b" * 64})
        with open(_review) as _fh:
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

    with _tf.TemporaryDirectory(prefix="org-inbox-test-") as _v:
        _pdf = _put(_v, "Inbox/Doe_Canonical_2025.pdf")
        _moves, _edits, _blockers = rename_all(
            _v, _pdf, os.path.basename(_pdf), apply=True,
            dest=os.path.join(_v, "Sources/PDFs"))
        check("a canonical Inbox PDF still reaches its permanent folder",
              (_blockers, os.path.exists(_pdf),
               os.path.isfile(os.path.join(_v, "Sources/PDFs/Doe_Canonical_2025.pdf"))),
              ([], False, True))

    with _tf.TemporaryDirectory(prefix="org-src-book-test-") as _v:
        _book = _put(_v, "Sources/PDFs/Doe_Book_2025_src.pdf")
        _chapter = _put(_v, "Sources/PDFs/Doe_Book_2025_src/Doe_Book_2025_01_Intro.pdf")
        _put(_v, "Sources/Images/Doe_Book_2025_01_Intro_fig_1.png")
        _put(_v, "Wiki/topic.md", "[[Doe_Book_2025_01_Intro.pdf#page=1]]\n"
             "![[Doe_Book_2025_01_Intro_fig_1.png]]\n")
        _moves, _edits, _blockers = rename_all(_v, _book, "Doe_Renamed_2025_src.pdf", apply=True)
        check("a `_src` book rename carries independently named chapters",
              (_blockers, os.path.isfile(os.path.join(_v,
               "Sources/PDFs/Doe_Renamed_2025_src/Doe_Renamed_2025_01_Intro.pdf")),
               os.path.isfile(os.path.join(_v, "Sources/Images/Doe_Renamed_2025_01_Intro_fig_1.png"))),
              ([], True, True))
        with open(os.path.join(_v, "Wiki/topic.md")) as _fh:
            check("chapter references follow a `_src` book rename too", _fh.read(),
                  "[[Doe_Renamed_2025_01_Intro.pdf#page=1]]\n"
                  "![[Doe_Renamed_2025_01_Intro_fig_1.png]]\n")
        _new_book = os.path.join(_v, "Sources/PDFs/Doe_Renamed_2025_src.pdf")
        _moves, _edits, _blockers = rename_all(_v, _new_book, "Doe_Renamed_2025_src_2.pdf", apply=True)
        check("renaming a split book cannot write invalid disambiguated chapters",
              (bool(_blockers), os.path.exists(_new_book)), (True, True))

    failed = [c for c in cases if not c[1]]
    for label, ok, got, want in cases:
        if not ok:
            print("FAIL  %s\n        got  %r\n        want %r"
                  % (label, got, want))
    print("%d/%d self-test cases pass" % (len(cases) - len(failed), len(cases)))
    return 1 if failed else 0


def main(argv=None):
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
